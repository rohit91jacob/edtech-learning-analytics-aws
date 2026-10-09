"""Reconcile pipeline outputs with figures published independently of this repo.

Sources:
* Kuzilek, Hlosta & Zdrahal (2017), "Open University Learning Analytics dataset", Scientific Data
  4:170171 (https://doi.org/10.1038/sdata.2017.171): table row counts in "Data Records", the module
  summary in Table 1, and statements about the data (score range, withdrawals, exam weights).
* The OULAD.names description file shipped in the UCI Machine Learning Repository archive.

Each check compares a number computed from the silver Iceberg tables or the dbt marts with the
published figure. ``status`` is ``match``, ``mismatch`` (an unexplained difference, which fails a
strict run) or ``documented_mismatch`` (the source itself is inconsistent; explained in ``note``).
On the sampled test fixtures every count differs by construction, so those runs are not strict.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime

import duckdb

from edtech_analytics import oulad
from edtech_analytics.config import Settings

UCI_NAMES_URL = "https://archive.ics.uci.edu/dataset/349/open+university+learning+analytics+dataset"
PAPER_TABLE1_URL = "https://www.nature.com/articles/sdata2017171/tables/1"


@dataclass
class Verification:
    check: str
    source: str
    published: str
    computed: str
    status: str
    note: str = ""


def _scan(settings: Settings, table: str) -> str:
    path = (settings.warehouse_dir / settings.silver_namespace / table).as_posix()
    return f"iceberg_scan('{path}')"


def run_verification(settings: Settings) -> list[Verification]:
    con = duckdb.connect(str(settings.duckdb_path), read_only=True)
    con.execute("LOAD iceberg")
    out: list[Verification] = []

    def scalar(sql: str):
        return con.execute(sql).fetchone()[0]

    silver_for = {
        "courses": "courses",
        "assessments": "assessments",
        "vle": "vle_sites",
        "studentInfo": "students",
        "studentRegistration": "registrations",
        "studentAssessment": "student_assessments",
        "studentVle": "student_vle",
    }
    try:
        for raw_table, published in oulad.PUBLISHED_ROW_COUNTS.items():
            computed = int(scalar(f"SELECT COUNT(*) FROM {_scan(settings, silver_for[raw_table])}"))
            out.append(
                Verification(
                    f"rows in {raw_table}",
                    f"Kuzilek et al. 2017, Data Records ({oulad.PAPER_URL})",
                    f"{published:,}",
                    f"{computed:,}",
                    "match" if computed == published else "mismatch",
                )
            )

        names_students = 32953  # "students in courses: 32953" in OULAD.names
        students = int(scalar(f"SELECT COUNT(*) FROM {_scan(settings, 'students')}"))
        out.append(
            Verification(
                "students in courses (UCI OULAD.names)",
                f"OULAD.names in the UCI archive ({UCI_NAMES_URL})",
                f"{names_students:,}",
                f"{students:,}",
                "documented_mismatch" if students == 32593 else "mismatch",
                "OULAD.names says 32,953; the paper and both archives have 32,593 rows. "
                "The description file transposes two digits.",
            )
        )

        modules = con.execute(
            f"SELECT code_module, COUNT(DISTINCT code_presentation), COUNT(*) "
            f"FROM {_scan(settings, 'students')} GROUP BY 1 ORDER BY 1"
        ).fetchall()
        by_module = {m: (p, n) for m, p, n in modules}
        domains = dict(
            con.execute("SELECT code_module, domain FROM reference.module_domains").fetchall()
        )
        for module, (domain, presentations, n_students) in oulad.PUBLISHED_MODULE_SUMMARY.items():
            p, n = by_module.get(module, (0, 0))
            ok = p == presentations and n == n_students and domains.get(module) == domain
            out.append(
                Verification(
                    f"Table 1: module {module} ({domain})",
                    f"Kuzilek et al. 2017, Table 1 ({PAPER_TABLE1_URL})",
                    f"{presentations} presentations, {n_students:,} students",
                    f"{p} presentations, {n:,} students",
                    "match" if ok else "mismatch",
                )
            )

        n_presentations = int(scalar("SELECT COUNT(*) FROM marts.dim_module_presentation"))
        out.append(
            Verification(
                "module presentations",
                f"Kuzilek et al. 2017, abstract ({oulad.PAPER_URL})",
                "22",
                str(n_presentations),
                "match" if n_presentations == 22 else "mismatch",
            )
        )
        stem = int(scalar("SELECT COUNT(*) FROM reference.module_domains WHERE domain = 'STEM'"))
        out.append(
            Verification(
                "STEM / Social Sciences modules",
                f"Kuzilek et al. 2017, Data selection ({oulad.PAPER_URL})",
                "4 STEM, 3 Social Sciences",
                f"{stem} STEM, {len(domains) - stem} Social Sciences",
                "match" if stem == 4 and len(domains) == 7 else "mismatch",
            )
        )

        lo, hi = con.execute(
            f"SELECT MIN(score), MAX(score) FROM {_scan(settings, 'student_assessments')}"
        ).fetchone()
        out.append(
            Verification(
                "assessment score range",
                f"Kuzilek et al. 2017, table studentAssessment ({oulad.PAPER_URL})",
                "0 to 100",
                f"{lo:g} to {hi:g}",
                "match" if lo >= 0 and hi <= 100 else "mismatch",
            )
        )

        unreg_not_withdrawn, withdrawn_no_date = con.execute(
            f"SELECT SUM(CASE WHEN r.date_unregistration IS NOT NULL AND s.final_result <> 'Withdrawn' THEN 1 ELSE 0 END),"
            f" SUM(CASE WHEN r.date_unregistration IS NULL AND s.final_result = 'Withdrawn' THEN 1 ELSE 0 END)"
            f" FROM {_scan(settings, 'students')} s JOIN {_scan(settings, 'registrations')} r"
            f" USING (code_module, code_presentation, id_student)"
        ).fetchone()
        out.append(
            Verification(
                "unregistered students have final_result Withdrawn",
                f"Kuzilek et al. 2017, table studentRegistration ({oulad.PAPER_URL})",
                "all unregistered students are Withdrawn",
                f"{unreg_not_withdrawn} unregistered students are not Withdrawn; "
                f"{withdrawn_no_date} Withdrawn students have no unregistration day",
                "match"
                if not unreg_not_withdrawn and not withdrawn_no_date
                else "documented_mismatch",
                "The release contradicts this statement in a few rows (Fail with an "
                "unregistration day). The pipeline keeps final_result as the label and treats a "
                "missing unregistration day as unknown.",
            )
        )

        bad_weights = con.execute(
            f"SELECT code_module || '_' || code_presentation, SUM(weight) FROM {_scan(settings, 'assessments')}"
            " WHERE assessment_type <> 'Exam' GROUP BY 1 HAVING SUM(weight) <> 100 ORDER BY 1"
        ).fetchall()
        exams_not_100 = int(
            scalar(
                f"SELECT COUNT(*) FROM {_scan(settings, 'assessments')}"
                " WHERE assessment_type = 'Exam' AND weight <> 100"
            )
        )
        out.append(
            Verification(
                "non-exam weights sum to 100% (exams weigh 100%)",
                f"Kuzilek et al. 2017, table assessments ({oulad.PAPER_URL})",
                "'Typically' 100% per presentation; exams 100%",
                f"{len(bad_weights)} presentations differ"
                + (": " + ", ".join(f"{k}={v:g}%" for k, v in bad_weights) if bad_weights else "")
                + f"; {exams_not_100} exams not at 100%",
                "match" if not bad_weights and not exams_not_100 else "documented_mismatch",
                "The paper says 'typically'; the presentations listed above are the exceptions "
                "found in the release.",
            )
        )
    finally:
        con.close()
    return out


def write_report(settings: Settings, results: list[Verification], strict: bool) -> dict:
    payload = {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "strict": strict,
        "matches": sum(r.status == "match" for r in results),
        "documented_mismatches": sum(r.status == "documented_mismatch" for r in results),
        "mismatches": sum(r.status == "mismatch" for r in results),
        "results": [asdict(r) for r in results],
    }
    settings.ops_dir.mkdir(parents=True, exist_ok=True)
    (settings.ops_dir / "verification.json").write_text(json.dumps(payload, indent=2), "utf-8")
    return payload


def is_full_release(settings: Settings) -> bool:
    """True when this run must reproduce the published figures (strict verification).

    Anything that was downloaded (figshare, or the UCI mirror, which is not md5-pinned) claims to
    be the official release, so it is always checked strictly: a truncated or altered download
    then fails verification (exit 4) instead of being reported as a "sample". A local archive
    (the committed fixtures, ``--archive``) is strict only if it has the full clickstream.
    """
    manifest = json.loads(
        (settings.current_raw_version() / "_manifest.json").read_text(encoding="utf-8")
    )
    if str(manifest.get("source", "")).startswith(("https://", "http://")):
        return True
    return manifest["row_counts"].get("studentVle") == oulad.PUBLISHED_ROW_COUNTS["studentVle"]
