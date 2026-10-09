"""Data-quality gates for the Spark layers (silver tables and the clickstream feature table).

Each check is a Spark SQL query returning the number of violating rows. ``error`` checks stop the
pipeline (the job exits non-zero, which fails the Step Functions state); ``warn`` checks are
recorded for the run report. Results are appended to the Iceberg table ``<namespace>.ops_dq_results``.

Shipped to EMR Serverless (Python 3.9): no 3.10+ syntax.
"""

from __future__ import annotations

from dataclasses import astuple, dataclass
from datetime import datetime, timezone

from pyspark.sql import SparkSession

from edtech_analytics.spark.session import table_name


@dataclass(frozen=True)
class Check:
    name: str
    layer: str
    severity: str
    sql: str
    description: str


@dataclass
class CheckResult:
    name: str
    layer: str
    severity: str
    violations: int
    passed: bool
    description: str


def _unique(table: str, keys: str) -> str:
    return (
        f"SELECT COUNT(*) FROM (SELECT {keys} FROM {{{table}}} GROUP BY {keys} HAVING COUNT(*) > 1)"
    )


def _not_null(table: str, cols: list) -> str:
    cond = " OR ".join(f"{c} IS NULL" for c in cols)
    return f"SELECT COUNT(*) FROM {{{table}}} WHERE {cond}"


def _domain(table: str, col: str, values: list, allow_null: bool = False) -> str:
    vals = ", ".join(f"'{v}'" for v in values)
    null_clause = "" if allow_null else f" OR {col} IS NULL"
    return f"SELECT COUNT(*) FROM {{{table}}} WHERE {col} NOT IN ({vals}){null_clause}"


PRESENTATION_KEY = "code_module, code_presentation"
ENROLMENT_KEY = "code_module, code_presentation, id_student"
IMD_BANDS = [f"{i * 10}-{(i + 1) * 10}%" for i in range(10)]

SILVER_CHECKS = [
    Check("courses_not_empty", "silver", "error",
          "SELECT CASE WHEN COUNT(*) = 0 THEN 1 ELSE 0 END FROM {courses}",
          "courses has rows"),
    Check("students_not_empty", "silver", "error",
          "SELECT CASE WHEN COUNT(*) = 0 THEN 1 ELSE 0 END FROM {students}",
          "students has rows"),
    Check("student_vle_not_empty", "silver", "error",
          "SELECT CASE WHEN COUNT(*) = 0 THEN 1 ELSE 0 END FROM {student_vle}",
          "student_vle has rows"),
    Check("load_no_cast_failures", "silver", "error",
          "SELECT COALESCE(SUM(cast_failures), 0) FROM {ops_load_audit}",
          "every non-empty raw value parsed to its declared type"),
    Check("load_rows_reconcile", "silver", "error",
          "SELECT COUNT(*) FROM {ops_load_audit} WHERE raw_rows <> silver_rows",
          "silver row count equals raw row count for every table (no rows dropped)"),
    Check("courses_pk_unique", "silver", "error", _unique("courses", PRESENTATION_KEY),
          "one row per module presentation"),
    Check("assessments_pk_unique", "silver", "error", _unique("assessments", "id_assessment"),
          "id_assessment is unique"),
    Check("vle_sites_pk_unique", "silver", "error", _unique("vle_sites", "id_site"),
          "id_site is unique"),
    Check("students_pk_unique", "silver", "error", _unique("students", ENROLMENT_KEY),
          "one row per student enrolment"),
    Check("registrations_pk_unique", "silver", "error", _unique("registrations", ENROLMENT_KEY),
          "one registration per student enrolment"),
    Check("student_assessments_pk_unique", "silver", "error",
          _unique("student_assessments", "id_assessment, id_student"),
          "one result per student and assessment"),
    Check("students_keys_not_null", "silver", "error",
          _not_null("students", ["code_module", "code_presentation", "id_student", "final_result"]),
          "enrolment keys and outcome present"),
    Check("student_vle_keys_not_null", "silver", "error",
          _not_null("student_vle", ["code_module", "code_presentation", "id_student", "id_site", "date", "sum_click"]),
          "clickstream keys present"),
    Check("final_result_domain", "silver", "error",
          _domain("students", "final_result", ["Pass", "Distinction", "Fail", "Withdrawn"]),
          "final_result is one of the four published outcomes"),
    Check("assessment_type_domain", "silver", "error",
          _domain("assessments", "assessment_type", ["TMA", "CMA", "Exam"]),
          "assessment_type is TMA, CMA or Exam"),
    Check("age_band_domain", "silver", "error",
          _domain("students", "age_band", ["0-35", "35-55", "55<="]),
          "age_band is one of the three published bands"),
    Check("imd_band_domain", "silver", "error",
          _domain("students", "imd_band", IMD_BANDS, allow_null=True),
          "imd_band is a decile band (after normalising '10-20')"),
    Check("disability_domain", "silver", "error",
          _domain("students", "disability", ["Y", "N"]), "disability is Y or N"),
    Check("score_range", "silver", "error",
          "SELECT COUNT(*) FROM {student_assessments} WHERE score < 0 OR score > 100",
          "assessment scores are within 0-100"),
    Check("sum_click_positive", "silver", "error",
          "SELECT COUNT(*) FROM {student_vle} WHERE sum_click <= 0",
          "each clickstream row has at least one click"),
    Check("students_have_course", "silver", "error",
          f"SELECT COUNT(*) FROM {{students}} s LEFT ANTI JOIN {{courses}} c USING ({PRESENTATION_KEY})",
          "every enrolment points at a known module presentation"),
    Check("registrations_match_students", "silver", "error",
          f"SELECT (SELECT COUNT(*) FROM {{registrations}} r LEFT ANTI JOIN {{students}} s USING ({ENROLMENT_KEY}))"
          f" + (SELECT COUNT(*) FROM {{students}} s LEFT ANTI JOIN {{registrations}} r USING ({ENROLMENT_KEY}))",
          "registrations and students are 1:1"),
    Check("student_assessments_have_assessment", "silver", "error",
          "SELECT COUNT(*) FROM {student_assessments} sa LEFT ANTI JOIN {assessments} a USING (id_assessment)",
          "every result points at a known assessment"),
    Check("student_assessments_enrolled", "silver", "error",
          "SELECT COUNT(*) FROM {student_assessments} sa JOIN {assessments} a USING (id_assessment) "
          f"LEFT ANTI JOIN {{students}} s USING ({ENROLMENT_KEY})",
          "every result belongs to a student enrolled on that assessment's presentation"),
    Check("student_vle_known_site", "silver", "error",
          f"SELECT COUNT(*) FROM {{student_vle}} v LEFT ANTI JOIN {{vle_sites}} s USING (id_site, {PRESENTATION_KEY})",
          "every click points at a VLE site of the same presentation"),
    Check("student_vle_enrolled", "silver", "error",
          f"SELECT COUNT(*) FROM {{student_vle}} v LEFT ANTI JOIN {{students}} s USING ({ENROLMENT_KEY})",
          "every click belongs to an enrolled student"),
    Check("student_vle_day_in_presentation", "silver", "error",
          "SELECT COUNT(*) FROM {student_vle} v JOIN {courses} c USING (code_module, code_presentation) "
          "WHERE v.date < -60 OR v.date > c.module_presentation_length + 30",
          "click days fall between 60 days before start and 30 days after the end"),
    Check("withdrawn_without_unregistration_date", "silver", "warn",
          f"SELECT COUNT(*) FROM {{students}} s JOIN {{registrations}} r USING ({ENROLMENT_KEY}) "
          "WHERE s.final_result = 'Withdrawn' AND r.date_unregistration IS NULL",
          "Withdrawn students with no unregistration day (93 in the full release)"),
    Check("imd_band_missing", "silver", "warn",
          "SELECT COUNT(*) FROM {students} WHERE imd_band IS NULL",
          "students without an IMD band (1,111 in the full release)"),
    Check("missing_scores", "silver", "warn",
          "SELECT COUNT(*) FROM {student_assessments} WHERE score IS NULL",
          "submitted assessments with no score (173 in the full release)"),
]  # fmt: skip

FEATURE_CHECKS = [
    Check("weekly_activity_pk_unique", "features", "error",
          _unique("student_weekly_activity",
                  "code_module, code_presentation, id_student, course_week, activity_type"),
          "one row per enrolment, week and activity type"),
    Check("weekly_activity_clicks_reconcile", "features", "error",
          "SELECT ABS((SELECT COALESCE(SUM(clicks), 0) FROM {student_weekly_activity})"
          " - (SELECT COALESCE(SUM(sum_click), 0) FROM {student_vle}))",
          "weekly clicks sum exactly to the raw clickstream"),
    Check("weekly_activity_rows_reconcile", "features", "error",
          "SELECT ABS((SELECT COALESCE(SUM(log_rows), 0) FROM {student_weekly_activity})"
          " - (SELECT COUNT(*) FROM {student_vle}))",
          "every clickstream row is counted in exactly one weekly bucket"),
    Check("weekly_activity_type_known", "features", "error",
          "SELECT COUNT(*) FROM {student_weekly_activity} WHERE activity_type IS NULL",
          "every click resolved to an activity type"),
    Check("weekly_engagement_pk_unique", "features", "error",
          _unique("student_weekly_engagement", "code_module, code_presentation, id_student, course_week"),
          "one row per enrolment and week"),
    Check("weekly_engagement_clicks_reconcile", "features", "error",
          "SELECT ABS((SELECT COALESCE(SUM(clicks), 0) FROM {student_weekly_engagement})"
          " - (SELECT COALESCE(SUM(sum_click), 0) FROM {student_vle}))",
          "weekly engagement clicks sum exactly to the raw clickstream"),
    Check("weekly_engagement_days_bounded", "features", "error",
          "SELECT COUNT(*) FROM {student_weekly_engagement} WHERE active_days < 1 OR active_days > 7",
          "active days per enrolment-week are between 1 and 7"),
    Check("weekly_activity_days_bounded", "features", "error",
          "SELECT COUNT(*) FROM {student_weekly_activity} WHERE active_days < 1 OR active_days > 7",
          "active days per week are between 1 and 7"),
]  # fmt: skip

CHECKS_BY_LAYER = {"silver": SILVER_CHECKS, "features": FEATURE_CHECKS}


def _render(sql: str, namespace: str) -> str:
    tables = {
        name: table_name(namespace, name)
        for name in (
            "courses",
            "assessments",
            "vle_sites",
            "students",
            "registrations",
            "student_assessments",
            "student_vle",
            "student_weekly_activity",
            "student_weekly_engagement",
            "ops_load_audit",
        )
    }
    return sql.format(**tables)


def run_checks(spark: SparkSession, *, namespace: str, layer: str, run_id: str) -> list:
    results = []
    for check in CHECKS_BY_LAYER[layer]:
        violations = int(spark.sql(_render(check.sql, namespace)).first()[0] or 0)
        results.append(
            CheckResult(
                check.name,
                check.layer,
                check.severity,
                violations,
                violations == 0,
                check.description,
            )
        )
    _persist(spark, namespace, run_id, results)
    return results


def _persist(spark: SparkSession, namespace: str, run_id: str, results: list) -> None:
    checked_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    rows = [(*astuple(r), run_id, checked_at) for r in results]
    frame = spark.createDataFrame(
        rows,
        "name string, layer string, severity string, violations long, passed boolean, "
        "description string, run_id string, checked_at string",
    )
    target = table_name(namespace, "ops_dq_results")
    if spark.catalog.tableExists(target):
        frame.writeTo(target).append()
    else:
        frame.writeTo(target).using("iceberg").create()


def failed_errors(results: list) -> list:
    return [r for r in results if r.severity == "error" and not r.passed]
