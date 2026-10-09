"""Heavy aggregation over the 10.6M-row clickstream: silver.student_weekly_activity.

Grain: module x presentation x student x course week x VLE activity type. ``course_week`` is
``floor(date / 7)``, so week 0 is days 0-6 of the presentation and negative weeks are the
pre-start period when materials are already open. This is the only clickstream table dbt reads;
it keeps the warehouse marts cheap on Athena (bytes scanned) and on DuckDB.

silver.student_weekly_engagement has the same grain without the activity type. It is computed
from the clickstream, not summed from the table above, because distinct active days and sites
cannot be added up across activity types.

Shipped to EMR Serverless (Python 3.9): no 3.10+ syntax.
"""

from __future__ import annotations

from pyspark.sql import SparkSession
from pyspark.sql import functions as F

from edtech_analytics.spark.session import table_name
from edtech_analytics.spark.silver import TABLE_PROPERTIES

WEEKLY_ACTIVITY = "student_weekly_activity"
WEEKLY_ENGAGEMENT = "student_weekly_engagement"


def build_weekly_activity(spark: SparkSession, *, namespace: str) -> dict:
    vle = spark.table(table_name(namespace, "student_vle"))
    sites = spark.table(table_name(namespace, "vle_sites")).select(
        "id_site", "code_module", "code_presentation", "activity_type"
    )
    weekly = (
        vle.join(sites, ["id_site", "code_module", "code_presentation"], "left")
        .withColumn("course_week", F.floor(F.col("date") / F.lit(7)).cast("int"))
        .groupBy("code_module", "code_presentation", "id_student", "course_week", "activity_type")
        .agg(
            F.sum("sum_click").cast("long").alias("clicks"),
            F.countDistinct("date").cast("int").alias("active_days"),
            F.countDistinct("id_site").cast("int").alias("distinct_sites"),
            F.count(F.lit(1)).cast("int").alias("log_rows"),
            F.min("date").cast("int").alias("first_day"),
            F.max("date").cast("int").alias("last_day"),
        )
        .repartition("code_module", "code_presentation")
        .sortWithinPartitions("code_module", "code_presentation", "id_student", "course_week")
    )
    _write(weekly, namespace, WEEKLY_ACTIVITY)

    engagement = (
        vle.withColumn("course_week", F.floor(F.col("date") / F.lit(7)).cast("int"))
        .join(sites, ["id_site", "code_module", "code_presentation"], "left")
        .groupBy("code_module", "code_presentation", "id_student", "course_week")
        .agg(
            F.sum("sum_click").cast("long").alias("clicks"),
            F.countDistinct("date").cast("int").alias("active_days"),
            F.countDistinct("id_site").cast("int").alias("distinct_sites"),
            F.countDistinct("activity_type").cast("int").alias("distinct_activity_types"),
            F.count(F.lit(1)).cast("int").alias("log_rows"),
            F.min("date").cast("int").alias("first_day"),
            F.max("date").cast("int").alias("last_day"),
        )
        .repartition("code_module", "code_presentation")
        .sortWithinPartitions("code_module", "code_presentation", "id_student", "course_week")
    )
    _write(engagement, namespace, WEEKLY_ENGAGEMENT)
    return {
        WEEKLY_ACTIVITY: spark.table(table_name(namespace, WEEKLY_ACTIVITY)).count(),
        WEEKLY_ENGAGEMENT: spark.table(table_name(namespace, WEEKLY_ENGAGEMENT)).count(),
    }


def _write(frame, namespace: str, table: str) -> None:
    writer = (
        frame.writeTo(table_name(namespace, table))
        .using("iceberg")
        .partitionedBy(F.col("code_module"), F.col("code_presentation"))
    )
    for key, value in TABLE_PROPERTIES.items():
        writer = writer.tableProperty(key, value)
    writer.createOrReplace()
