from __future__ import annotations

import json

from edtech_analytics import cli


def test_bad_config_exits_2(monkeypatch):
    monkeypatch.setenv("EDTECH_RISK_CUTOFF_DAY", "-1")
    assert cli.main(["asl"]) == 2


def test_asl_lists_states(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("EDTECH_DATA_DIR", str(tmp_path))
    assert cli.main(["asl"]) == 0
    states = json.loads(capsys.readouterr().out)
    assert states[0] == "BuildSilver"
    assert "PipelineFailed" in states


def test_ingest_fixtures(monkeypatch, tmp_path, capsys, fixtures_dir):
    monkeypatch.setenv("EDTECH_DATA_DIR", str(tmp_path))
    assert cli.main(["ingest", "--archive", str(fixtures_dir)]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["new"] is True
    assert out["rows"]["courses"] == 4


def test_verify_without_data_is_a_config_error(monkeypatch, tmp_path):
    monkeypatch.setenv("EDTECH_DATA_DIR", str(tmp_path))
    assert cli.main(["verify"]) == 2
