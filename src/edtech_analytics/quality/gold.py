"""Gold-layer data-quality gate over the dbt marts (DuckDB).

dbt's own tests guard each model's grain and domains. These checks reconcile the marts against
each other and against the silver Iceberg tables, which is what makes the published numbers
trustworthy: no enrolment is lost or double counted between layers.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

import duckdb

from edtech_analytics.config import Settings


@dataclass(frozen=True)
class GoldCheck:
    name: str
    severity: str
    sql: str
    description: str


@dataclass
class GoldResult:
    name: str
    layer: str
    severity: str
    violations: int
    passed: bool
    description: str


def _silver(settings: Settings, table: str) -> str:
    path = (settings.warehouse_dir / settings.silver_namespace / table).as_posix()
    return f"iceberg_scan('{path}')"


def checks(settings: Settings) -> list[GoldCheck]:
    students = _silver(settings, "students")
    return [
        GoldCheck(
            "dim_covers_every_enrolment",
            "error",
            f"SELECT ABS((SELECT SUM(n_enrolments) FROM marts.dim_module_presentation)"
            f" - (SELECT COUNT(*) FROM {students}))",
            "dim_module_presentation enrolment counts add up to silver.students",
        ),
        GoldCheck(
            "first_submission_one_row_per_enrolment",
            "error",
            f"SELECT ABS((SELECT COUNT(*) FROM marts.fct_first_submission)"
            f" - (SELECT COUNT(*) FROM {students}))",
            "fct_first_submission has exactly one row per enrolment",
        ),
        GoldCheck(
            "fairness_overall_matches_silver",
            "error",
            f"SELECT ABS((SELECT n_enrolments FROM marts.mart_outcome_fairness_slices"
            f" WHERE slice_dimension = 'overall') - (SELECT COUNT(*) FROM {students}))",
            "the overall fairness slice is the whole population",
        ),
        GoldCheck(
            "fairness_withdrawal_rate_matches_silver",
            "error",
            "SELECT CASE WHEN ABS((SELECT withdrawal_rate FROM marts.mart_outcome_fairness_slices"
            " WHERE slice_dimension = 'overall') - (SELECT AVG(CASE WHEN final_result = 'Withdrawn'"
            f" THEN 1.0 ELSE 0.0 END) FROM {students})) > 1e-9 THEN 1 ELSE 0 END",
            "overall withdrawal rate equals the silver rate",
        ),
        GoldCheck(
            "risk_features_population",
            "error",
            "SELECT ABS((SELECT COUNT(*) FROM marts.mart_dropout_risk_features)"
            " - (SELECT COUNT(*) FROM intermediate.int_enrolments WHERE unregistration_day IS NULL"
            " OR unregistration_day >= (SELECT 0 + ?)))",
            "risk table = every enrolment still registered at the cut-off day",
        ),
        GoldCheck(
            "risk_features_have_both_splits",
            "error",
            "SELECT CASE WHEN COUNT(DISTINCT split) = 2 THEN 0 ELSE 1 END"
            " FROM marts.mart_dropout_risk_features",
            "the held-out presentation and the training presentations are both present",
        ),
        GoldCheck(
            "risk_features_both_classes",
            "error",
            "SELECT COUNT(*) FROM (SELECT split FROM marts.mart_dropout_risk_features"
            " GROUP BY split HAVING COUNT(DISTINCT label_withdrawn) < 2)",
            "each split has withdrawn and non-withdrawn enrolments (AUC is defined)",
        ),
        GoldCheck(
            "funnel_covers_every_assessment",
            "error",
            "SELECT ABS((SELECT COUNT(*) FROM marts.mart_assessment_mastery_funnel)"
            f" - (SELECT COUNT(*) FROM {_silver(settings, 'assessments')}))",
            "one funnel row per assessment",
        ),
        GoldCheck(
            "funnel_submissions_match_silver",
            "error",
            "SELECT ABS((SELECT SUM(submitted + banked) FROM marts.mart_assessment_mastery_funnel)"
            f" - (SELECT COUNT(*) FROM {_silver(settings, 'student_assessments')}))",
            "every silver assessment result is counted once in the funnel",
        ),
        GoldCheck(
            "activity_effectiveness_rates_bounded",
            "error",
            "SELECT COUNT(*) FROM marts.mart_vle_activity_effectiveness"
            " WHERE pass_rate_users NOT BETWEEN 0 AND 1 OR pass_rate_non_users NOT BETWEEN 0 AND 1",
            "pass rates are proportions",
        ),
        GoldCheck(
            "fairness_small_slices",
            "warn",
            "SELECT COUNT(*) FROM marts.mart_outcome_fairness_slices WHERE small_sample",
            "slices with fewer than 100 enrolments (read with care)",
        ),
    ]


def run_gold_checks(settings: Settings, run_id: str) -> list[GoldResult]:
    con = duckdb.connect(str(settings.duckdb_path))
    try:
        con.execute("LOAD iceberg")
        results = []
        for check in checks(settings):
            params = [settings.risk_cutoff_day] if "?" in check.sql else []
            violations = int(con.execute(check.sql, params).fetchone()[0] or 0)
            results.append(
                GoldResult(
                    check.name,
                    "gold",
                    check.severity,
                    violations,
                    violations == 0,
                    check.description,
                )
            )
    finally:
        con.close()
    _persist(settings, run_id, results)
    return results


def _persist(settings: Settings, run_id: str, results: list[GoldResult]) -> Path:
    settings.ops_dir.mkdir(parents=True, exist_ok=True)
    path = settings.ops_dir / "dq_results_gold.json"
    payload = {
        "run_id": run_id,
        "checked_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "results": [asdict(r) for r in results],
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path
