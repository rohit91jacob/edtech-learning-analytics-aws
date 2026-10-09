"""Static results site (``edtech report``): plain HTML + CSS + inline SVG, no external assets.

Every number on the page is read from the DuckDB marts, the ``ml`` tables written by the model
step, the silver data-quality results and ``ops/verification.json``. Nothing is typed in by hand.
"""

from __future__ import annotations

import html
import json
import math
from datetime import UTC, datetime
from pathlib import Path

import duckdb

from edtech_analytics import oulad
from edtech_analytics.config import Settings

# Categorical slots 1-4 of the validated reference palette (light / dark steps).
SERIES = {
    "Distinction": ("#2a78d6", "#3987e5"),
    "Pass": ("#eb6834", "#d95926"),
    "Fail": ("#1baf7a", "#199e70"),
    "Withdrawn": ("#eda100", "#c98500"),
}

CSS = """
.viz-root{color-scheme:light;--surface-1:#fcfcfb;--surface-2:#f3f2ef;--text-primary:#0b0b0b;
--text-secondary:#52514e;--text-muted:#77756f;--grid:#e4e2dd;--border:#d6d4ce;--accent:#2a78d6;
--s1:#2a78d6;--s2:#eb6834;--s3:#1baf7a;--s4:#eda100}
@media (prefers-color-scheme:dark){:root:where(:not([data-theme="light"])) .viz-root{color-scheme:dark;
--surface-1:#1a1a19;--surface-2:#242422;--text-primary:#fff;--text-secondary:#c3c2b7;--text-muted:#9a998f;
--grid:#383835;--border:#45443f;--accent:#3987e5;--s1:#3987e5;--s2:#d95926;--s3:#199e70;--s4:#c98500}}
*{box-sizing:border-box}
body{margin:0;font:15px/1.5 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
.viz-root{background:var(--surface-1);color:var(--text-primary);min-height:100vh}
main{max-width:1080px;margin:0 auto;padding:24px 20px 64px}
h1{font-size:26px;margin:0 0 4px}h2{font-size:19px;margin:40px 0 8px;padding-top:8px;border-top:1px solid var(--border)}
h3{font-size:15px;margin:20px 0 6px}
p,li{color:var(--text-secondary)}.muted{color:var(--text-muted);font-size:13px}
a{color:var(--accent)}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:12px;margin:20px 0}
.tile{background:var(--surface-2);border-radius:8px;padding:12px 14px}
.tile .v{font-size:24px;font-weight:650;color:var(--text-primary)}.tile .k{font-size:13px;color:var(--text-secondary)}
table{border-collapse:collapse;width:100%;margin:8px 0 4px;font-size:13.5px}
th,td{text-align:left;padding:5px 8px;border-bottom:1px solid var(--grid);vertical-align:top}
th{color:var(--text-secondary);font-weight:600}td.n,th.n{text-align:right;font-variant-numeric:tabular-nums}
.wrap{overflow-x:auto}
.badge{display:inline-block;padding:0 6px;border-radius:4px;font-size:12px;border:1px solid var(--border)}
.ok::before{content:"\\2713 "}.warn::before{content:"! "}.bad::before{content:"\\2717 "}
.note{background:var(--surface-2);border-left:3px solid var(--border);padding:8px 12px;margin:12px 0}
svg text{fill:var(--text-secondary);font-size:12px}
svg .axis{stroke:var(--border)}svg .gridline{stroke:var(--grid)}
svg .line{fill:none;stroke-width:2;stroke-linejoin:round;stroke-linecap:round}
.legend{display:flex;gap:16px;flex-wrap:wrap;font-size:13px;color:var(--text-secondary);margin:4px 0}
.swatch{display:inline-block;width:12px;height:3px;border-radius:2px;vertical-align:middle;margin-right:6px}
details{margin:6px 0}summary{cursor:pointer;color:var(--text-secondary)}
"""


def _e(value) -> str:
    return html.escape(str(value))


def _pct(value, digits: int = 1) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return "–"
    return f"{100 * float(value):.{digits}f}%"


def _num(value, digits: int = 0) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return "–"
    return f"{float(value):,.{digits}f}"


def _table(headers: list[str], rows: list[list], numeric: set[int] | None = None) -> str:
    numeric = numeric or set()
    head = "".join(
        f'<th class="{"n" if i in numeric else ""}">{_e(h)}</th>' for i, h in enumerate(headers)
    )
    body = "".join(
        "<tr>"
        + "".join(f'<td class="{"n" if i in numeric else ""}">{c}</td>' for i, c in enumerate(r))
        + "</tr>"
        for r in rows
    )
    return f'<div class="wrap"><table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>'


def _line_chart(series: dict[str, list[tuple[int, float]]], title: str) -> str:
    """Multi-series line chart (one y axis, 0-100%) with direct end labels and native tooltips."""
    width, height, left, right, top, bottom = 760, 300, 48, 110, 16, 36
    xs = [x for pts in series.values() for x, _ in pts]
    x0, x1 = min(xs), max(xs)
    pw, ph = width - left - right, height - top - bottom

    def sx(x):
        return left + (x - x0) / max(x1 - x0, 1) * pw

    def sy(y):
        return top + (1 - y) * ph

    parts = [
        f'<svg viewBox="0 0 {width} {height}" role="img" aria-label="{_e(title)}" width="100%">'
    ]
    for tick in (0, 0.25, 0.5, 0.75, 1.0):
        y = sy(tick)
        parts.append(
            f'<line class="gridline" x1="{left}" x2="{left + pw}" y1="{y:.1f}" y2="{y:.1f}"/>'
        )
        parts.append(
            f'<text x="{left - 6}" y="{y + 4:.1f}" text-anchor="end">{int(tick * 100)}%</text>'
        )
    for tick in range(x0, x1 + 1, 5):
        parts.append(
            f'<text x="{sx(tick):.1f}" y="{height - 14}" text-anchor="middle">{tick}</text>'
        )
    parts.append(
        f'<text x="{left + pw / 2:.1f}" y="{height - 1}" text-anchor="middle">course week</text>'
    )
    parts.append(
        f'<line class="axis" x1="{left}" x2="{left + pw}" y1="{sy(0):.1f}" y2="{sy(0):.1f}"/>'
    )
    label_ys: list[float] = []
    for i, (name, pts) in enumerate(series.items(), start=1):
        path = " ".join(
            f"{'M' if j == 0 else 'L'}{sx(x):.1f},{sy(y):.1f}" for j, (x, y) in enumerate(pts)
        )
        parts.append(f'<path class="line" style="stroke:var(--s{i})" d="{path}"/>')
        for x, y in pts:
            parts.append(
                f'<circle cx="{sx(x):.1f}" cy="{sy(y):.1f}" r="6" fill="transparent">'
                f"<title>{_e(name)} · week {x}: {_pct(y)} active</title></circle>"
            )
        lx, ly = pts[-1]
        y = sy(ly)
        while any(abs(y - other) < 14 for other in label_ys):
            y += 14
        label_ys.append(y)
        parts.append(
            f'<text x="{sx(lx) + 8:.1f}" y="{y + 4:.1f}" style="fill:var(--text-primary)">{_e(name)} {_pct(ly, 0)}</text>'
        )
    parts.append("</svg>")
    legend = "".join(
        f'<span><span class="swatch" style="background:var(--s{i})"></span>{_e(name)}</span>'
        for i, name in enumerate(series, start=1)
    )
    return f'<div class="legend">{legend}</div>' + "".join(parts)


def _metrics(con) -> dict:
    rows = con.execute("SELECT metric, value FROM ml.risk_model_metrics").fetchall()
    out = {}
    for key, value in rows:
        try:
            out[key] = json.loads(value)
        except (TypeError, json.JSONDecodeError):
            out[key] = value
    return out


def _dq_summary(con, settings: Settings) -> list[list]:
    path = (settings.warehouse_dir / settings.silver_namespace / "ops_dq_results").as_posix()
    rows = con.execute(
        f"""
        WITH r AS (SELECT * FROM iceberg_scan('{path}')),
        latest AS (SELECT layer, max(checked_at) AS checked_at FROM r GROUP BY layer)
        SELECT r.layer, count(*) AS checks,
               sum(CASE WHEN r.passed THEN 1 ELSE 0 END) AS passed,
               sum(CASE WHEN NOT r.passed AND r.severity = 'error' THEN 1 ELSE 0 END) AS errors,
               sum(CASE WHEN NOT r.passed AND r.severity = 'warn' THEN 1 ELSE 0 END) AS warnings
        FROM r JOIN latest USING (layer, checked_at) GROUP BY r.layer ORDER BY r.layer DESC
        """
    ).fetchall()
    out = [list(r) for r in rows]
    gold_path = settings.ops_dir / "dq_results_gold.json"
    if gold_path.exists():
        gold = json.loads(gold_path.read_text(encoding="utf-8"))["results"]
        out.append(
            [
                "gold",
                len(gold),
                sum(r["passed"] for r in gold),
                sum((not r["passed"]) and r["severity"] == "error" for r in gold),
                sum((not r["passed"]) and r["severity"] == "warn" for r in gold),
            ]
        )
    return out


def build_site(settings: Settings, out_dir: Path) -> dict:
    con = duckdb.connect(str(settings.duckdb_path), read_only=True)
    con.execute("LOAD iceberg")
    try:
        return _build(con, settings, out_dir)
    finally:
        con.close()


def _build(con, settings: Settings, out_dir: Path) -> dict:
    manifest = json.loads(
        (settings.current_raw_version() / "_manifest.json").read_text(encoding="utf-8")
    )
    q = con.execute
    n_enrol, n_pres, withdrawal, pass_rate = q(
        "SELECT sum(n_enrolments), count(*), sum(withdrawal_rate * n_enrolments) / sum(n_enrolments),"
        " sum(pass_rate * n_enrolments) / sum(n_enrolments) FROM marts.dim_module_presentation"
    ).fetchone()
    vle_rows = manifest["row_counts"]["studentVle"]
    metrics = _metrics(con)
    verification_path = settings.ops_dir / "verification.json"
    verification = (
        json.loads(verification_path.read_text(encoding="utf-8"))
        if verification_path.exists()
        else None
    )

    # Engagement curves (pooled over presentations).
    curve_rows = q(
        """
        SELECT cohort_value, course_week, sum(active_students) * 1.0 / sum(enrolled)
        FROM marts.mart_engagement_weekly_cohorts
        WHERE cohort_dimension = 'final_result' AND course_week <= 37
        GROUP BY 1, 2 ORDER BY 1, 2
        """
    ).fetchall()
    curves: dict[str, list[tuple[int, float]]] = {k: [] for k in SERIES}
    for cohort, week, share in curve_rows:
        curves.setdefault(cohort, []).append((int(week), float(share)))
    curves = {k: v for k, v in curves.items() if v}
    weeks_shown = [0, 4, 8, 10, 12, 16, 20, 24, 28, 32, 36]
    curve_table = _table(
        ["final result", *[f"wk {w}" for w in weeks_shown]],
        [[_e(k), *[_pct(dict(v).get(w)) for w in weeks_shown]] for k, v in curves.items()],
        numeric=set(range(1, len(weeks_shown) + 1)),
    )
    reg = q(
        """
        SELECT cohort_value, sum(enrolled) FILTER (WHERE course_week = 0),
               sum(active_students) FILTER (WHERE course_week = 0) * 1.0 / sum(enrolled) FILTER (WHERE course_week = 0),
               sum(active_students) FILTER (WHERE course_week = 8) * 1.0 / sum(enrolled) FILTER (WHERE course_week = 8),
               sum(active_students) FILTER (WHERE course_week = 20) * 1.0 / sum(enrolled) FILTER (WHERE course_week = 20)
        FROM marts.mart_engagement_weekly_cohorts WHERE cohort_dimension = 'registration_timing'
        GROUP BY 1 ORDER BY 1
        """
    ).fetchall()
    reg_withdrawal = dict(
        q(
            "SELECT registration_cohort, avg(CASE WHEN is_withdrawn THEN 1.0 ELSE 0 END) FROM intermediate.int_enrolments GROUP BY 1"
        ).fetchall()
    )

    funnel = q(
        """
        SELECT code_module, count(*) AS n,
               sum(submitted) * 1.0 / sum(enrolled), sum(passed) * 1.0 / nullif(sum(submitted), 0),
               sum(mastered) * 1.0 / nullif(sum(submitted), 0), sum(mastered) * 1.0 / sum(enrolled)
        FROM marts.mart_assessment_mastery_funnel
        WHERE assessment_type <> 'Exam' AND NOT is_formative
        GROUP BY 1 ORDER BY 1
        """
    ).fetchall()
    first_assessment = q(
        """
        WITH first AS (
            SELECT * FROM marts.mart_assessment_mastery_funnel
            WHERE assessment_type <> 'Exam' AND NOT is_formative
            QUALIFY row_number() OVER (PARTITION BY presentation_key ORDER BY assessment_seq) = 1
        )
        SELECT sum(enrolled), sum(submitted), sum(passed), sum(mastered) FROM first
        """
    ).fetchone()
    formative = q(
        "SELECT count(*) FROM marts.mart_assessment_mastery_funnel WHERE is_formative"
    ).fetchone()[0]
    ungraded_modules = [
        r[0]
        for r in q(
            "SELECT code_module FROM marts.mart_assessment_mastery_funnel WHERE assessment_type <> 'Exam'"
            " GROUP BY 1 HAVING bool_and(is_formative) ORDER BY 1"
        ).fetchall()
    ]
    exams_without = q(
        "SELECT count(*) FILTER (WHERE NOT has_results), count(*) FROM marts.mart_assessment_mastery_funnel WHERE assessment_type = 'Exam'"
    ).fetchone()

    ttfs = q(
        """
        SELECT final_result, count(*), avg(CASE WHEN has_submitted THEN 0.0 ELSE 1.0 END),
               quantile_cont(first_submission_day, 0.5), quantile_cont(days_after_start_or_registration, 0.5),
               avg(CASE WHEN submitted_by_first_cutoff THEN 1.0 ELSE 0.0 END)
        FROM marts.fct_first_submission GROUP BY 1
        ORDER BY CASE final_result WHEN 'Distinction' THEN 1 WHEN 'Pass' THEN 2 WHEN 'Fail' THEN 3 ELSE 4 END
        """
    ).fetchall()

    slices = q("SELECT * FROM ml.risk_model_slices").df()
    per_module = q("SELECT * FROM ml.risk_model_per_module ORDER BY slice_value").df()
    coefs = q(
        "SELECT feature, coefficient FROM ml.risk_model_coefficients ORDER BY abs_coefficient DESC LIMIT 10"
    ).fetchall()

    activity = q(
        f"""
        SELECT activity_type, count(*) AS modules, sum(n_users) AS users, sum(n_offered) AS offered,
               sum(n_users) * 1.0 / nullif(sum(n_offered), 0) AS usage_rate,
               sum(pass_rate_users * n_users) / nullif(sum(n_users), 0) AS pass_users,
               sum(pass_rate_non_users * (n_offered - n_users)) / nullif(sum(n_offered - n_users), 0) AS pass_non_users,
               sum(n_offered - n_users) AS non_users
        FROM marts.mart_vle_activity_effectiveness
        GROUP BY 1 HAVING sum(n_offered) >= {100}
        ORDER BY usage_rate DESC
        """
    ).fetchall()
    fairness = q(
        "SELECT slice_dimension, slice_value, n_enrolments, share_of_enrolments, pass_rate, withdrawal_rate,"
        " pass_rate_gap_pp, withdrawal_rate_gap_pp, small_sample FROM marts.mart_outcome_fairness_slices"
        " ORDER BY CASE slice_dimension WHEN 'overall' THEN 0 WHEN 'age_band' THEN 1 WHEN 'imd_band' THEN 2 ELSE 3 END, slice_value"
    ).fetchall()
    dq_rows = _dq_summary(con, settings)
    generated = datetime.now(UTC).isoformat(timespec="seconds")
    full = manifest["row_counts"]["studentVle"] == oulad.PUBLISHED_ROW_COUNTS["studentVle"]

    summary = {
        "generated_at": generated,
        "raw_version": manifest["version"],
        "full_release": full,
        "enrolments": int(n_enrol),
        "presentations": int(n_pres),
        "vle_rows": int(vle_rows),
        "withdrawal_rate": float(withdrawal),
        "pass_rate": float(pass_rate),
        "risk_model_test_auc": metrics.get("test_auc"),
        "risk_model_test_auc_ci95": metrics.get("test_auc_ci95"),
        "baseline_clicks_only_test_auc": metrics.get("baseline_clicks_only_test_auc"),
        "holdout_presentation": metrics.get("holdout_presentation"),
        "dq": [
            dict(zip(["layer", "checks", "passed", "errors", "warnings"], r, strict=True))
            for r in dq_rows
        ],
        "verification": None
        if verification is None
        else {k: verification[k] for k in ("matches", "documented_mismatches", "mismatches")},
    }

    sections: list[str] = []
    data_kind = (
        "the full OULAD release"
        if full
        else "a <strong>small sample</strong> of OULAD (test fixtures): numbers are not representative"
    )
    sections.append(
        f"""
<h1>Learning analytics on the Open University dataset</h1>
<p>Engagement, mastery and withdrawal-risk analytics built from {data_kind}: 22 module
presentations from 2013–2014, released by the Open University under {oulad.LICENCE}
(<a href="{oulad.PAPER_URL}">Kuzilek et al., 2017</a>). The pipeline is
S3 → EMR Serverless PySpark → Apache Iceberg → dbt (Athena) → Step Functions, run here on local
emulators: local PySpark with an Iceberg Hadoop catalog, DuckDB in place of Athena, and a local
runner that executes the Step Functions definition. Nothing on this page ran on AWS.</p>
<p class="note">The data is a <strong>static release</strong>: it has not changed since 2015. The site
is rebuilt weekly to prove the pipeline still runs end to end from the public download, not because
new learners appear. Khan Academy-style learner data is not public, so this project uses OULAD, the
closest open dataset with assessments and clickstream.</p>
<p class="muted">Generated {generated} · raw version <code>{_e(manifest["version"])}</code> ·
source <a href="{oulad.DATA_DOI_URL}">{oulad.DATA_DOI_URL}</a></p>
<div class="tiles">
<div class="tile"><div class="v">{_num(n_enrol)}</div><div class="k">student enrolments</div></div>
<div class="tile"><div class="v">{_num(vle_rows)}</div><div class="k">VLE clickstream rows</div></div>
<div class="tile"><div class="v">{_pct(pass_rate)}</div><div class="k">passed (incl. distinction)</div></div>
<div class="tile"><div class="v">{_pct(withdrawal)}</div><div class="k">withdrew</div></div>
<div class="tile"><div class="v">{_num(metrics.get("test_auc"), 3)}</div><div class="k">risk model AUC on held-out {_e(metrics.get("holdout_presentation"))}</div></div>
</div>"""
    )

    if verification:
        rows = []
        for r in verification["results"]:
            cls = {"match": "ok", "documented_mismatch": "warn"}.get(r["status"], "bad")
            rows.append(
                [
                    _e(r["check"]),
                    _e(r["published"]),
                    _e(r["computed"]),
                    f'<span class="badge {cls}">{_e(r["status"].replace("_", " "))}</span>',
                    _e(r["note"]),
                ]
            )
        sections.append(
            f"""<h2>Verification against published figures</h2>
<p>{verification["matches"]} checks match the paper, {verification["documented_mismatches"]} differ
because the published sources disagree with the data or with each other (explained), and
{verification["mismatches"]} are unexplained mismatches.</p>"""
            + _table(["check", "published", "computed", "status", "note"], rows)
        )

    sections.append(
        "<h2>Weekly engagement by final result</h2>"
        "<p>Share of each outcome group with at least one VLE click in the course week, pooled over all "
        "presentations. Week 10 of the October (J) presentations falls around the December holidays, the "
        "likely reason for the dip there.</p>"
        + _line_chart(curves, "Share of students active per course week, by final result")
        + "<details><summary>Table view</summary>"
        + curve_table
        + "</details>"
        + "<h3>By registration timing</h3>"
        + _table(
            ["registered", "enrolments", "active wk 0", "active wk 8", "active wk 20", "withdrew"],
            [
                [
                    _e(r[0]),
                    _num(r[1]),
                    _pct(r[2]),
                    _pct(r[3]),
                    _pct(r[4]),
                    _pct(reg_withdrawal.get(r[0])),
                ]
                for r in reg
            ],
            numeric={1, 2, 3, 4, 5},
        )
        + '<p class="muted">early = more than 30 days before the start, on_time = 0–30 days before, late = after the start.</p>'
    )

    fa = first_assessment
    sections.append(
        "<h2>Assessment mastery funnel</h2>"
        f"<p>Funnel per assessment: enrolled → submitted → passed (score ≥ 40, OULAD's pass mark) → mastered "
        f"(score ≥ {settings.mastery_threshold}, this project's definition). Summed over each module's graded "
        f"TMAs and CMAs. {formative} zero-weight (formative) assessments and the exams are excluded; "
        f"{exams_without[0]} of {exams_without[1]} exams have no results in the release, as the paper notes."
        + (
            f" Not shown: {', '.join(ungraded_modules)}, whose TMAs and CMAs all carry 0% weight."
            if ungraded_modules
            else ""
        )
        + "</p>"
        + _table(
            [
                "module",
                "assessments",
                "submitted / enrolled",
                "passed / submitted",
                "mastered / submitted",
                "mastered / enrolled",
            ],
            [
                [_e(r[0]), _num(r[1]), _pct(r[2]), _pct(r[3]), _pct(r[4]), _pct(r[5])]
                for r in funnel
            ],
            numeric={1, 2, 3, 4, 5},
        )
        + f"<p>First graded assessment of every presentation: {_num(fa[0])} enrolled → {_num(fa[1])} submitted "
        f"({_pct(fa[1] / fa[0] if fa[0] else None)}) → {_num(fa[2])} passed → {_num(fa[3])} mastered.</p>"
    )

    sections.append(
        "<h2>Time to first submission</h2>"
        "<p>Day of the first non-banked submission (day 0 = presentation start), by final result.</p>"
        + _table(
            [
                "final result",
                "enrolments",
                "never submitted",
                "median first-submission day",
                "median days after start or registration",
                "submitted by first cut-off",
            ],
            [[_e(r[0]), _num(r[1]), _pct(r[2]), _num(r[3]), _num(r[4]), _pct(r[5])] for r in ttfs],
            numeric={1, 2, 3, 4, 5},
        )
    )

    m = metrics
    ci = m.get("test_auc_ci95") or [None, None]
    slice_rows = [
        [
            _e(r.slice_dimension),
            _e(r.slice_value),
            _num(r.n),
            _pct(r.base_rate),
            _pct(r.mean_predicted),
            _num(r.auc, 3),
            _pct(r.tpr),
            _pct(r.fpr),
        ]
        for r in slices.itertuples()
    ]
    module_rows = [
        [
            _e(r.slice_value),
            _num(r.n),
            _pct(r.base_rate),
            _num(r.auc, 3),
            _pct(r.tpr),
            _pct(r.flag_rate),
        ]
        for r in per_module.itertuples()
    ]
    sections.append(
        f"""<h2>Withdrawal-risk baseline model</h2>
<p>Logistic regression on features observable by course day {settings.risk_cutoff_day} (clicks, active
days, recency, submissions and scores so far, prior attempts, credits, prior education, module).
Trained on {_num(m.get("train_rows"))} enrolments from {len(m.get("train_presentations", []))} presentations
and evaluated only on the {len(m.get("test_presentations", []))} held-out
{_e(m.get("holdout_presentation"))} presentations ({_num(m.get("test_rows"))} enrolments still registered on
day {settings.risk_cutoff_day}, of whom {_pct(m.get("test_base_rate"))} later withdrew).
Age, IMD band, disability, gender and region are <strong>not</strong> model inputs; they are used only to
slice the evaluation.</p>"""
        + _table(
            ["metric", "value"],
            [
                [
                    "test ROC AUC (95% bootstrap CI)",
                    f"{_num(m.get('test_auc'), 3)} ({_num(ci[0], 3)}–{_num(ci[1], 3)})",
                ],
                ["train ROC AUC", _num(m.get("train_auc"), 3)],
                ["clicks-only baseline, test AUC", _num(m.get("baseline_clicks_only_test_auc"), 3)],
                [
                    "test average precision (base rate " + _pct(m.get("test_base_rate")) + ")",
                    _num(m.get("test_average_precision"), 3),
                ],
                ["test Brier score", _num(m.get("test_brier"), 3)],
                [
                    f"at threshold {_num(m.get('threshold'), 2)} ({_e(m.get('threshold_rule'))})",
                    f"recall {_pct(m.get('test_tpr'))}, precision {_pct(m.get('test_precision'))}, flags {_pct(m.get('test_flag_rate'))} of students",
                ],
            ],
        )
        + f"<p>An AUC of {_num(m.get('test_auc'), 2)} is a modest baseline: it is the probability that a random "
        "future withdrawer is ranked above a random stayer. Many withdrawals happen months after day "
        f"{settings.risk_cutoff_day}, so this is a deliberately hard target, not a tuned model.</p>"
        + "<h3>By module (held-out presentations)</h3>"
        + _table(
            ["module", "n", "withdrew", "AUC", "recall", "flagged"],
            module_rows,
            numeric={1, 2, 3, 4, 5},
        )
        + "<h3>Fairness slices (held-out presentations)</h3>"
        + _table(
            [
                "dimension",
                "value",
                "n",
                "withdrew",
                "mean predicted risk",
                "AUC",
                "recall (TPR)",
                "false-positive rate",
            ],
            slice_rows,
            numeric={2, 3, 4, 5, 6, 7},
        )
        + '<p class="muted">AUC is left blank for slices under 50 students. Compare "withdrew" with "mean predicted risk" '
        "to see under- or over-prediction for a group.</p>"
        + "<details><summary>Largest coefficients (standardised features)</summary>"
        + _table(["feature", "coefficient"], [[_e(f), _num(c, 3)] for f, c in coefs], numeric={1})
        + "</details>"
    )

    sections.append(
        "<h2>VLE activity types and passing</h2>"
        "<p>Students who stayed to the end (not withdrawn), pooled over modules that offer the activity type. "
        "<strong>This is association, not effect</strong>: engaged students use more of everything, and the "
        "non-user groups for core materials are tiny and atypical.</p>"
        + _table(
            [
                "activity type",
                "modules",
                "offered to",
                "usage rate",
                "pass rate: users",
                "pass rate: non-users",
                "non-users",
            ],
            [
                [
                    _e(r[0]),
                    _num(r[1]),
                    _num(r[3]),
                    _pct(r[4]),
                    _pct(r[5]),
                    _pct(r[6]) + (" *" if (r[7] or 0) < 100 else ""),
                    _num(r[7]),
                ]
                for r in activity
            ],
            numeric={1, 2, 3, 4, 5, 6},
        )
        + '<p class="muted">* fewer than 100 non-users: do not read the comparison.</p>'
    )

    sections.append(
        "<h2>Outcomes by age, deprivation and disability</h2>"
        "<p>Descriptive outcome gaps in percentage points versus the whole population. IMD band is the "
        "deprivation decile of the student's area (0–10% = most deprived). Caveats: the bands were coarsened "
        "by the release's k-anonymity step, they are confounded with each other and with module choice and "
        "study load, and they say nothing about why outcomes differ.</p>"
        + _table(
            [
                "dimension",
                "value",
                "enrolments",
                "share",
                "pass rate",
                "withdrawal rate",
                "pass gap (pp)",
                "withdrawal gap (pp)",
            ],
            [
                [
                    _e(r[0]),
                    _e(r[1]) + (" *" if r[8] else ""),
                    _num(r[2]),
                    _pct(r[3]),
                    _pct(r[4]),
                    _pct(r[5]),
                    _num(r[6], 1),
                    _num(r[7], 1),
                ]
                for r in fairness
            ],
            numeric={2, 3, 4, 5, 6, 7},
        )
    )

    sections.append(
        "<h2>Data-quality gates (latest run)</h2>"
        + _table(
            ["layer", "checks", "passed", "failed errors", "warnings"],
            [[_e(r[0]), _num(r[1]), _num(r[2]), _num(r[3]), _num(r[4])] for r in dq_rows],
            numeric={1, 2, 3, 4},
        )
        + '<p class="muted">Warnings are known properties of the release (e.g. 93 withdrawn students without an '
        "unregistration day); errors stop the pipeline.</p>"
        + '<p class="muted">Code: <a href="https://github.com/rohit91jacob/edtech-learning-analytics-aws">'
        "github.com/rohit91jacob/edtech-learning-analytics-aws</a> (MIT). Data: OULAD, © The Open University, "
        f'CC BY 4.0, <a href="{oulad.DATA_DOI_URL}">{oulad.DATA_DOI_URL}</a>; changes: aggregated and modelled.</p>'
    )

    out_dir.mkdir(parents=True, exist_ok=True)
    page = (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        "<title>OULAD learning analytics</title>"
        f'<style>{CSS}</style></head><body><div class="viz-root"><main>'
        + "".join(sections)
        + "</main></div></body></html>"
    )
    (out_dir / "index.html").write_text(page, encoding="utf-8")
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary
