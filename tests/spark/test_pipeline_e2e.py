"""End-to-end on the committed fixtures: ingest -> state machine (Spark, DQ, dbt, gold DQ) ->
model -> verification -> site, then a full rerun that must reproduce identical outputs, and a
corrupted input that must be stopped by the silver quality gate.

Needs Java 17 (PySpark) and network access to Maven Central (Iceberg jar) and the DuckDB
extension repository (iceberg extension) on first run.
"""

from __future__ import annotations

import hashlib
import json
import shutil

import duckdb
import pytest

from edtech_analytics import cli
from edtech_analytics.config import Settings
from edtech_analytics.model.risk import train
from edtech_analytics.pipeline import DataQualityError, run_pipeline
from edtech_analytics.report.site import build_site
from edtech_analytics.verify import run_verification, write_report

pytestmark = [pytest.mark.spark, pytest.mark.e2e]

SILVER = [
    "courses",
    "assessments",
    "vle_sites",
    "students",
    "registrations",
    "student_assessments",
    "student_vle",
    "student_weekly_activity",
    "student_weekly_engagement",
]
MARTS = [
    "marts.dim_module_presentation",
    "marts.mart_engagement_weekly_cohorts",
    "marts.mart_assessment_mastery_funnel",
    "marts.fct_first_submission",
    "marts.mart_time_to_first_submission",
    "marts.mart_dropout_risk_features",
    "marts.mart_vle_activity_effectiveness",
    "marts.mart_outcome_fairness_slices",
]


def _fingerprint(settings: Settings) -> dict[str, str]:
    """Order-independent content hash of every silver table and mart."""
    con = duckdb.connect(str(settings.duckdb_path), read_only=True)
    con.execute("LOAD iceberg")
    out = {}
    try:
        sources = {
            t: f"iceberg_scan('{(settings.warehouse_dir / 'silver' / t).as_posix()}')"
            for t in SILVER
        }
        sources.update({m: m for m in MARTS})
        for name, rel in sources.items():
            rows = con.execute(f"SELECT * FROM {rel}").fetchall()
            digest = hashlib.sha256()
            for row in sorted(repr(r) for r in rows):
                digest.update(row.encode())
            out[name] = f"{len(rows)}:{digest.hexdigest()[:16]}"
    finally:
        con.close()
    return out


@pytest.fixture(scope="module")
def lake(tmp_path_factory, request):
    from pathlib import Path

    fixtures = Path(request.config.rootpath) / "tests" / "fixtures" / "oulad"
    settings = Settings(
        data_dir=tmp_path_factory.mktemp("lake"),
        source_md5=None,
        spark_master="local[2]",
        spark_driver_memory="2g",
        spark_shuffle_partitions=4,
    )
    execution = run_pipeline(settings, archive=fixtures)
    return settings, execution, fixtures


def test_state_machine_succeeded(lake):
    _, execution, _ = lake
    assert execution.status == "SUCCEEDED"
    assert [h["state"] for h in execution.history][-1] == "NotifySuccess"


def test_silver_reconciles_with_raw(lake):
    settings, _, _ = lake
    manifest = json.loads((settings.current_raw_version() / "_manifest.json").read_text())
    con = duckdb.connect(str(settings.duckdb_path), read_only=True)
    con.execute("LOAD iceberg")
    pairs = {"students": "studentInfo", "student_vle": "studentVle", "vle_sites": "vle"}
    for silver, raw in pairs.items():
        path = (settings.warehouse_dir / "silver" / silver).as_posix()
        n = con.execute(f"SELECT COUNT(*) FROM iceberg_scan('{path}')").fetchone()[0]
        assert n == manifest["row_counts"][raw]
    con.close()


def test_quality_gates_all_passed(lake):
    settings, execution, _ = lake
    gold = json.loads((settings.ops_dir / "dq_results_gold.json").read_text())["results"]
    assert gold
    assert all(r["passed"] for r in gold if r["severity"] == "error")
    dq_states = [h for h in execution.history if "QualityGate" in h["state"]]
    assert [h["status"] for h in dq_states] == ["SUCCEEDED", "SUCCEEDED"]


def test_model_verification_and_site(lake, tmp_path):
    settings, _, _ = lake
    report = train(settings)
    assert 0.0 <= report.metrics["test_auc"] <= 1.0
    assert report.metrics["test_presentations"] == ["AAA_2014J", "CCC_2014J"]
    results = run_verification(settings)
    payload = write_report(settings, results, strict=False)
    assert payload["mismatches"] > 0  # a sample cannot match the full release's counts
    summary = build_site(settings, tmp_path / "site")
    page = (tmp_path / "site" / "index.html").read_text(encoding="utf-8")
    assert "small sample" in page
    assert summary["full_release"] is False
    assert summary["enrolments"] == 288
    assert "<svg" in page


def test_rerun_is_idempotent(lake):
    settings, _, fixtures = lake
    before = _fingerprint(settings)
    versions_before = sorted(p.name for p in settings.raw_dir.glob("version=*"))
    execution = run_pipeline(settings, archive=fixtures)
    assert execution.status == "SUCCEEDED"
    assert sorted(p.name for p in settings.raw_dir.glob("version=*")) == versions_before
    assert _fingerprint(settings) == before


def test_corrupt_input_is_stopped_by_silver_gate(tmp_path, lake):
    _, _, fixtures = lake
    bad = tmp_path / "bad"
    shutil.copytree(fixtures, bad)
    path = bad / "studentAssessment.csv"
    lines = path.read_text().splitlines()
    first = lines[1].split(",")
    first[-1] = '"150"'  # impossible score
    lines[1] = ",".join(first)
    lines.append(lines[2])  # duplicate result row
    path.write_text("\n".join(lines) + "\n")
    settings = Settings(
        data_dir=tmp_path / "lake",
        source_md5=None,
        spark_master="local[2]",
        spark_driver_memory="2g",
        spark_shuffle_partitions=4,
    )
    with pytest.raises(DataQualityError):
        run_pipeline(settings, archive=bad)
    record = sorted((settings.ops_dir / "executions").glob("*.json"))[-1]
    history = json.loads(record.read_text())["history"]
    assert [h["state"] for h in history] == [
        "BuildSilver",
        "SilverQualityGate",
        "NotifyFailure",
        "PipelineFailed",
    ]
    assert not (settings.duckdb_path).exists()  # dbt never ran


def test_cli_exit_code_for_dq_failure(tmp_path, monkeypatch, lake):
    _, _, fixtures = lake
    bad = tmp_path / "bad"
    shutil.copytree(fixtures, bad)
    path = bad / "studentInfo.csv"
    text = path.read_text().replace('"Withdrawn"', '"Dropped"', 1)
    path.write_text(text)
    monkeypatch.setenv("EDTECH_DATA_DIR", str(tmp_path / "lake"))
    monkeypatch.setenv("EDTECH_SOURCE_MD5", "none")
    monkeypatch.setenv("EDTECH_SPARK_MASTER", "local[2]")
    monkeypatch.setenv("EDTECH_SPARK_DRIVER_MEMORY", "2g")
    assert cli.main(["pipeline", "--archive", str(bad)]) == 3
