"""Settings (environment variables with safe defaults) and the local lake layout.

Every path the pipeline touches is derived from ``EDTECH_DATA_DIR`` so a run is fully described by
one directory: ``raw/`` plays the role of the S3 raw bucket, ``warehouse/`` the Iceberg warehouse
bucket, ``warehouse.duckdb`` the Athena workgroup, and ``ops/`` holds run metadata.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

# The official data citation in the OULAD paper (Kuzilek et al., 2017) is this figshare record.
# The OU's own landing page (analyse.kmi.open.ac.uk) now redirects to a page whose download link
# returns 404, so figshare is primary and the UCI mirror is the fallback. The two archives differ
# only in how they encode missing values ("" vs "?"); silver normalises both to NULL.
FIGSHARE_URL = "https://ndownloader.figshare.com/files/8606371"
FIGSHARE_MD5 = "7412686fd77cf0e0ee1e8c3e9b354308"
UCI_URL = (
    "https://archive.ics.uci.edu/static/public/349/open+university+learning+analytics+dataset.zip"
)

# Spark 3.5.8 + Iceberg 1.10.1 is the pair Amazon EMR 7.14.0 ships.
ICEBERG_VERSION = "1.10.1"
ICEBERG_PACKAGE = f"org.apache.iceberg:iceberg-spark-runtime-3.5_2.12:{ICEBERG_VERSION}"

OULAD_TABLES = (
    "courses",
    "assessments",
    "vle",
    "studentInfo",
    "studentRegistration",
    "studentAssessment",
    "studentVle",
)


class ConfigError(ValueError):
    """Raised for invalid configuration (CLI exit code 2)."""


def _env(name: str, default: str) -> str:
    value = os.environ.get(name, "").strip()
    return value or default


def _int_env(name: str, default: int) -> int:
    raw = _env(name, str(default))
    try:
        return int(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} must be an integer, got {raw!r}") from exc


def _bool_env(name: str, default: bool) -> bool:
    raw = _env(name, "true" if default else "false").lower()
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    raise ConfigError(f"{name} must be a boolean, got {raw!r}")


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    source_url: str = FIGSHARE_URL
    source_md5: str | None = FIGSHARE_MD5
    fallback_url: str = UCI_URL
    http_timeout: int = 120
    http_retries: int = 4
    spark_master: str = "local[*]"
    spark_driver_memory: str = "4g"
    spark_shuffle_partitions: int = 16
    spark_log_level: str = "WARN"
    silver_namespace: str = "silver"
    dq_fail_on_error: bool = True
    holdout_presentation: str = "2014J"
    risk_cutoff_day: int = 28
    mastery_threshold: int = 70
    log_format: str = "text"
    log_level: str = "INFO"
    extra: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_env(cls) -> Settings:
        data_dir = Path(_env("EDTECH_DATA_DIR", "data")).expanduser().resolve()
        md5 = _env("EDTECH_SOURCE_MD5", FIGSHARE_MD5)
        settings = cls(
            data_dir=data_dir,
            source_url=_env("EDTECH_SOURCE_URL", FIGSHARE_URL),
            source_md5=None if md5.lower() == "none" else md5,
            fallback_url=_env("EDTECH_FALLBACK_URL", UCI_URL),
            http_timeout=_int_env("EDTECH_HTTP_TIMEOUT_SECONDS", 120),
            http_retries=_int_env("EDTECH_HTTP_RETRIES", 4),
            spark_master=_env("EDTECH_SPARK_MASTER", "local[*]"),
            spark_driver_memory=_env("EDTECH_SPARK_DRIVER_MEMORY", "4g"),
            spark_shuffle_partitions=_int_env("EDTECH_SPARK_SHUFFLE_PARTITIONS", 16),
            spark_log_level=_env("EDTECH_SPARK_LOG_LEVEL", "WARN"),
            silver_namespace=_env("EDTECH_SILVER_NAMESPACE", "silver"),
            dq_fail_on_error=_bool_env("EDTECH_DQ_FAIL_ON_ERROR", True),
            holdout_presentation=_env("EDTECH_HOLDOUT_PRESENTATION", "2014J"),
            risk_cutoff_day=_int_env("EDTECH_RISK_CUTOFF_DAY", 28),
            mastery_threshold=_int_env("EDTECH_MASTERY_THRESHOLD", 70),
            log_format=_env("EDTECH_LOG_FORMAT", "text"),
            log_level=_env("EDTECH_LOG_LEVEL", "INFO"),
        )
        settings.validate()
        return settings

    def validate(self) -> None:
        if not 0 < self.risk_cutoff_day < 270:
            raise ConfigError("EDTECH_RISK_CUTOFF_DAY must be between 1 and 269")
        if not 0 < self.mastery_threshold <= 100:
            raise ConfigError("EDTECH_MASTERY_THRESHOLD must be between 1 and 100")
        if self.holdout_presentation not in {"2013B", "2013J", "2014B", "2014J"}:
            raise ConfigError("EDTECH_HOLDOUT_PRESENTATION must be one of 2013B/2013J/2014B/2014J")
        if self.log_format not in {"text", "json"}:
            raise ConfigError("EDTECH_LOG_FORMAT must be 'text' or 'json'")

    # Lake layout -------------------------------------------------------------------------------
    @property
    def raw_dir(self) -> Path:
        """Stand-in for s3://<raw-bucket>/oulad/."""
        return self.data_dir / "raw" / "oulad"

    @property
    def downloads_dir(self) -> Path:
        return self.data_dir / "downloads"

    @property
    def warehouse_dir(self) -> Path:
        """Stand-in for s3://<lake-bucket>/warehouse/ (Iceberg Hadoop catalog locally)."""
        return self.data_dir / "warehouse"

    @property
    def duckdb_path(self) -> Path:
        """Stand-in for the Athena workgroup: dbt-duckdb builds the marts here."""
        return self.data_dir / "warehouse.duckdb"

    @property
    def ops_dir(self) -> Path:
        return self.data_dir / "ops"

    @property
    def current_raw_marker(self) -> Path:
        return self.raw_dir / "CURRENT"

    def current_raw_version(self) -> Path:
        """The raw version directory the last successful ingest pointed at."""
        if not self.current_raw_marker.exists():
            raise ConfigError(f"no raw data yet under {self.raw_dir}; run `edtech ingest` first")
        version = self.current_raw_marker.read_text(encoding="utf-8").strip()
        return self.raw_dir / version
