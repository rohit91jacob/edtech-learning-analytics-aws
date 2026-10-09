"""Raw OULAD CSV -> typed, conformed silver Iceberg tables.

Every column is read as a string and cast explicitly, so a value that does not parse is counted
(``cast_failures`` in ``ops_load_audit``) instead of silently becoming NULL. Both encodings of a
missing value used by the two public mirrors ("" on figshare, "?" on UCI) are normalised to NULL.

Each table is replaced atomically (one Iceberg snapshot per table per run) from a deterministic
input, so re-running the job on the same raw version produces identical tables.

Shipped to EMR Serverless (Python 3.9): no 3.10+ syntax.
"""

from __future__ import annotations

from dataclasses import dataclass

from pyspark.sql import Column, DataFrame, SparkSession
from pyspark.sql import functions as F
from pyspark.sql.types import StringType, StructField, StructType

from edtech_analytics.spark.session import table_name

RAW_COLUMNS = {
    "courses": ("code_module", "code_presentation", "module_presentation_length"),
    "assessments": (
        "code_module",
        "code_presentation",
        "id_assessment",
        "assessment_type",
        "date",
        "weight",
    ),
    "vle": ("id_site", "code_module", "code_presentation", "activity_type", "week_from", "week_to"),
    "studentInfo": (
        "code_module",
        "code_presentation",
        "id_student",
        "gender",
        "region",
        "highest_education",
        "imd_band",
        "age_band",
        "num_of_prev_attempts",
        "studied_credits",
        "disability",
        "final_result",
    ),
    "studentRegistration": (
        "code_module",
        "code_presentation",
        "id_student",
        "date_registration",
        "date_unregistration",
    ),
    "studentAssessment": ("id_assessment", "id_student", "date_submitted", "is_banked", "score"),
    "studentVle": (
        "code_module",
        "code_presentation",
        "id_student",
        "id_site",
        "date",
        "sum_click",
    ),
}

# silver table -> (raw table, {column: spark type}, partition columns)
SILVER_TABLES = {
    "courses": (
        "courses",
        {
            "code_module": "string",
            "code_presentation": "string",
            "module_presentation_length": "int",
        },
        (),
    ),
    "assessments": (
        "assessments",
        {
            "id_assessment": "int",
            "code_module": "string",
            "code_presentation": "string",
            "assessment_type": "string",
            "date": "int",
            "weight": "double",
        },
        (),
    ),
    "vle_sites": (
        "vle",
        {
            "id_site": "int",
            "code_module": "string",
            "code_presentation": "string",
            "activity_type": "string",
            "week_from": "int",
            "week_to": "int",
        },
        (),
    ),
    "students": (
        "studentInfo",
        {
            "code_module": "string",
            "code_presentation": "string",
            "id_student": "int",
            "gender": "string",
            "region": "string",
            "highest_education": "string",
            "imd_band": "string",
            "age_band": "string",
            "num_of_prev_attempts": "int",
            "studied_credits": "int",
            "disability": "string",
            "final_result": "string",
        },
        (),
    ),
    "registrations": (
        "studentRegistration",
        {
            "code_module": "string",
            "code_presentation": "string",
            "id_student": "int",
            "date_registration": "int",
            "date_unregistration": "int",
        },
        (),
    ),
    "student_assessments": (
        "studentAssessment",
        {
            "id_assessment": "int",
            "id_student": "int",
            "date_submitted": "int",
            "is_banked": "int",
            "score": "double",
        },
        (),
    ),
    "student_vle": (
        "studentVle",
        {
            "code_module": "string",
            "code_presentation": "string",
            "id_student": "int",
            "id_site": "int",
            "date": "int",
            "sum_click": "int",
        },
        ("code_module", "code_presentation"),
    ),
}

TABLE_PROPERTIES = {
    "format-version": "2",
    "write.parquet.compression-codec": "zstd",
}


@dataclass
class LoadAudit:
    table: str
    raw_rows: int
    silver_rows: int
    cast_failures: int


def _raw_schema(raw_table: str) -> StructType:
    return StructType([StructField(c, StringType(), True) for c in RAW_COLUMNS[raw_table]])


def _clean(col: str) -> Column:
    trimmed = F.trim(F.col(col))
    return F.when(trimmed.isin("", "?"), F.lit(None)).otherwise(trimmed)


def read_raw(spark: SparkSession, raw_root: str, raw_table: str) -> DataFrame:
    """Read one raw table directory (plain or gzipped CSV parts) with an all-string schema."""
    return (
        spark.read.option("header", "true")
        .option("quote", '"')
        .option("escape", '"')
        .option("mode", "FAILFAST")
        .schema(_raw_schema(raw_table))
        .csv(f"{raw_root.rstrip('/')}/{raw_table}/")
    )


def conform(raw: DataFrame, table: str, raw_version: str) -> tuple[DataFrame, Column]:
    """Return the typed frame plus an expression counting cast failures per row."""
    _, columns, _ = SILVER_TABLES[table]
    cleaned = raw.select([_clean(c).alias(c) for c in raw.columns])
    typed_cols = []
    failure_terms = []
    for name, dtype in columns.items():
        value = cleaned[name]
        if name == "imd_band":
            # The release spells one band "10-20" while the other nine carry a % sign.
            value = F.when(value == "10-20", F.lit("10-20%")).otherwise(value)
        typed = value.cast(dtype) if dtype != "string" else value
        typed_cols.append(typed.alias(name))
        if dtype != "string":
            failure_terms.append(F.when(value.isNotNull() & typed.isNull(), 1).otherwise(0))
    failures = sum(failure_terms[1:], failure_terms[0]) if failure_terms else F.lit(0)
    frame = cleaned.select(
        *typed_cols, failures.alias("_cast_failures"), F.lit(raw_version).alias("_raw_version")
    )
    return frame, F.col("_cast_failures")


def _derive(table: str, frame: DataFrame) -> DataFrame:
    if table == "courses":
        return frame.withColumn(
            "presentation_year", F.substring("code_presentation", 1, 4).cast("int")
        ).withColumn(
            "presentation_start_month",
            F.when(F.col("code_presentation").endswith("B"), F.lit(2))
            .when(F.col("code_presentation").endswith("J"), F.lit(10))
            .otherwise(F.lit(None).cast("int")),
        )
    if table == "student_assessments":
        return frame.withColumn("is_banked", F.col("is_banked") == 1)
    if table == "students":
        return frame.withColumn("is_disabled", F.col("disability") == "Y")
    return frame


def build_silver(
    spark: SparkSession,
    *,
    raw_root: str,
    raw_version: str,
    namespace: str,
    tables: tuple[str, ...] | None = None,
) -> list[LoadAudit]:
    spark.sql(f"CREATE NAMESPACE IF NOT EXISTS lake.{namespace}")
    audits = []
    for table in tables or tuple(SILVER_TABLES):
        raw_table, _, partitions = SILVER_TABLES[table]
        raw = read_raw(spark, raw_root, raw_table)
        typed, failures = conform(raw, table, raw_version)
        # Two passes over the raw files (stats, then write) are cheaper than caching 10M rows.
        stats = typed.agg(F.count(F.lit(1)).alias("n"), F.sum(failures).alias("f")).first()
        silver = _derive(table, typed.drop("_cast_failures"))
        if partitions:
            silver = silver.repartition(*partitions).sortWithinPartitions(*partitions)
        writer = silver.writeTo(table_name(namespace, table)).using("iceberg")
        for key, value in TABLE_PROPERTIES.items():
            writer = writer.tableProperty(key, value)
        if partitions:
            writer = writer.partitionedBy(*[F.col(p) for p in partitions])
        writer.createOrReplace()
        written = spark.table(table_name(namespace, table)).count()
        audits.append(LoadAudit(table, int(stats["n"]), int(written), int(stats["f"] or 0)))
    _write_audit(spark, namespace, raw_version, audits)
    return audits


def _write_audit(spark: SparkSession, namespace: str, raw_version: str, audits: list) -> None:
    rows = [(a.table, a.raw_rows, a.silver_rows, a.cast_failures, raw_version) for a in audits]
    frame = spark.createDataFrame(
        rows,
        "table_name string, raw_rows long, silver_rows long, cast_failures long, raw_version string",
    )
    target = table_name(namespace, "ops_load_audit")
    if spark.catalog.tableExists(target):
        # Keep one row per table: replace the rows for the tables this run loaded.
        names = ",".join(f"'{a.table}'" for a in audits)
        existing = spark.table(target).where(f"table_name NOT IN ({names})")
        frame = existing.unionByName(frame)
        frame = frame.localCheckpoint()
    frame.writeTo(target).using("iceberg").createOrReplace()
