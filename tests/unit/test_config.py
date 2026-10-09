from __future__ import annotations

import pytest

from edtech_analytics.config import ConfigError, Settings


def test_defaults(monkeypatch, tmp_path):
    monkeypatch.setenv("EDTECH_DATA_DIR", str(tmp_path))
    s = Settings.from_env()
    assert s.data_dir == tmp_path.resolve()
    assert s.holdout_presentation == "2014J"
    assert s.risk_cutoff_day == 28
    assert s.raw_dir == tmp_path.resolve() / "raw" / "oulad"
    assert s.duckdb_path.name == "warehouse.duckdb"


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("EDTECH_RISK_CUTOFF_DAY", "0"),
        ("EDTECH_RISK_CUTOFF_DAY", "abc"),
        ("EDTECH_MASTERY_THRESHOLD", "101"),
        ("EDTECH_HOLDOUT_PRESENTATION", "2015B"),
        ("EDTECH_DQ_FAIL_ON_ERROR", "maybe"),
        ("EDTECH_LOG_FORMAT", "xml"),
    ],
)
def test_invalid_values_fail_fast(monkeypatch, name, value):
    monkeypatch.setenv(name, value)
    with pytest.raises(ConfigError):
        Settings.from_env()


def test_md5_can_be_disabled(monkeypatch):
    monkeypatch.setenv("EDTECH_SOURCE_MD5", "none")
    assert Settings.from_env().source_md5 is None


def test_current_raw_version_requires_ingest(settings):
    with pytest.raises(ConfigError, match="edtech ingest"):
        settings.current_raw_version()
