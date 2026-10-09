"""SparkSession factory with an Iceberg catalog named ``lake``.

* ``hadoop`` catalog (local runs, CI): Iceberg metadata and data files live under a filesystem
  warehouse directory, which plays the role of the S3 lake bucket.
* ``glue`` catalog (EMR Serverless): the same ``lake.<namespace>.<table>`` names resolve to AWS Glue
  Data Catalog databases/tables, with data in S3 through Iceberg's S3FileIO. On EMR the Iceberg
  runtime jar is supplied by the job's ``spark.jars`` setting, so no Maven download happens there.

This module is shipped to EMR Serverless (Python 3.9): keep it free of 3.10+ syntax.
"""

from __future__ import annotations

import os
from pathlib import Path

from pyspark.sql import SparkSession

ICEBERG_PACKAGE = "org.apache.iceberg:iceberg-spark-runtime-3.5_2.12:1.10.1"
CATALOG = "lake"


def build_session(
    app_name: str,
    *,
    catalog_type: str = "hadoop",
    warehouse: str,
    master: str | None = None,
    driver_memory: str = "4g",
    shuffle_partitions: int = 16,
    log_level: str = "WARN",
) -> SparkSession:
    if catalog_type not in ("hadoop", "glue"):
        raise ValueError("catalog_type must be 'hadoop' or 'glue'")
    builder = SparkSession.builder.appName(app_name)
    if master:
        builder = (
            builder.master(master)
            .config("spark.driver.memory", driver_memory)
            .config("spark.ui.enabled", "false")
            .config("spark.ui.showConsoleProgress", "false")
            .config("spark.sql.session.timeZone", "UTC")
        )
        jars_dir = os.environ.get("EDTECH_SPARK_JARS_DIR")
        if jars_dir:
            jars = sorted(str(p) for p in Path(jars_dir).iterdir() if p.suffix == ".jar")
            builder = builder.config("spark.jars", ",".join(jars))
        else:
            builder = builder.config("spark.jars.packages", ICEBERG_PACKAGE)

    prefix = "spark.sql.catalog." + CATALOG
    builder = (
        builder.config(
            "spark.sql.extensions",
            "org.apache.iceberg.spark.extensions.IcebergSparkSessionExtensions",
        )
        .config(prefix, "org.apache.iceberg.spark.SparkCatalog")
        .config(prefix + ".warehouse", warehouse)
        .config("spark.sql.shuffle.partitions", str(shuffle_partitions))
        .config("spark.sql.adaptive.enabled", "true")
    )
    if catalog_type == "hadoop":
        builder = builder.config(prefix + ".type", "hadoop")
    else:
        builder = builder.config(
            prefix + ".catalog-impl", "org.apache.iceberg.aws.glue.GlueCatalog"
        ).config(prefix + ".io-impl", "org.apache.iceberg.aws.s3.S3FileIO")

    spark = builder.getOrCreate()
    spark.sparkContext.setLogLevel(log_level)
    return spark


def table_name(namespace: str, table: str) -> str:
    return f"{CATALOG}.{namespace}.{table}"
