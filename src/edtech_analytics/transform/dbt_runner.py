"""Run the dbt project programmatically against the local DuckDB "Athena" stand-in."""

from __future__ import annotations

import gc
import json
import logging
import os
from pathlib import Path

from edtech_analytics.config import Settings

log = logging.getLogger(__name__)

PROJECT_DIR = Path(__file__).resolve().parents[3] / "dbt"


class DbtError(RuntimeError):
    """dbt returned a failure (a model error or a failing test)."""


def dbt_vars(settings: Settings) -> dict[str, object]:
    return {
        "risk_cutoff_day": settings.risk_cutoff_day,
        "holdout_presentation": settings.holdout_presentation,
        "mastery_threshold": settings.mastery_threshold,
    }


def dbt_env(settings: Settings) -> dict[str, str]:
    return {
        "EDTECH_LAKE_WAREHOUSE": settings.warehouse_dir.as_posix(),
        "EDTECH_DUCKDB_PATH": settings.duckdb_path.as_posix(),
        "EDTECH_SILVER_SCHEMA": settings.silver_namespace,
    }


def run_dbt(settings: Settings, command: str = "build", *extra: str, target: str | None = None):
    """Invoke ``dbt <command>`` in-process; raises DbtError unless every node succeeded."""
    from dbt.cli.main import dbtRunner  # deferred: importing dbt is slow

    settings.data_dir.mkdir(parents=True, exist_ok=True)
    os.environ.update(dbt_env(settings))
    args = [
        command,
        "--project-dir",
        str(PROJECT_DIR),
        "--profiles-dir",
        str(PROJECT_DIR),
        "--vars",
        json.dumps(dbt_vars(settings)),
        *extra,
    ]
    if target:
        args += ["--target", target]
    log.info("running dbt", extra={"dbt_args": args})
    try:
        result = dbtRunner().invoke(args)
    finally:
        release_duckdb()
    if not result.success:
        raise DbtError(f"dbt {command} failed: {result.exception or 'see dbt output above'}")
    return result


def release_duckdb() -> None:
    """Close the DuckDB handle dbt-duckdb keeps for the life of the process.

    Without this, the model/report steps in the same process cannot open the warehouse with a
    different configuration (e.g. read-only).
    """
    try:
        from dbt.adapters.duckdb.connections import DuckDBConnectionManager
    except ImportError:  # pragma: no cover - adapter always installed
        return
    env = DuckDBConnectionManager._ENV
    conn = getattr(env, "conn", None)
    if conn is not None:
        conn.close()
    DuckDBConnectionManager.close_all_connections()
    gc.collect()
