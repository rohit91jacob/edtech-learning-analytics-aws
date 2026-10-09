from __future__ import annotations

from pathlib import Path

import pytest

from edtech_analytics.config import Settings

FIXTURES = Path(__file__).parent / "fixtures" / "oulad"


@pytest.fixture
def fixtures_dir() -> Path:
    return FIXTURES


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(data_dir=tmp_path / "lake", source_md5=None, http_retries=1)
