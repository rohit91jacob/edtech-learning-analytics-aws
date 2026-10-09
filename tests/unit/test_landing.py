from __future__ import annotations

import gzip
import json
import shutil
import zipfile

import pytest

from edtech_analytics.ingest import landing
from edtech_analytics.ingest.landing import IngestError, land


def _count_rows(path):
    raw = gzip.decompress(path.read_bytes()) if path.suffix == ".gz" else path.read_bytes()
    return len(raw.decode().strip().splitlines()) - 1


def test_land_fixtures_writes_manifest_and_pointer(settings, fixtures_dir):
    result = land(settings, fixtures_dir)
    assert result.created
    assert settings.current_raw_marker.read_text() == result.version
    manifest = json.loads((result.path / "_manifest.json").read_text())
    expected_vle = sum(_count_rows(p) for p in fixtures_dir.glob("studentVle.part-*.csv.gz"))
    assert manifest["row_counts"]["studentVle"] == expected_vle
    assert manifest["row_counts"]["studentInfo"] == _count_rows(fixtures_dir / "studentInfo.csv")
    assert manifest["licence"] == "CC BY 4.0"
    assert len(list((result.path / "studentVle").iterdir())) == 4


def test_land_is_idempotent(settings, fixtures_dir):
    first = land(settings, fixtures_dir)
    stamp = (first.path / "_manifest.json").stat().st_mtime_ns
    second = land(settings, fixtures_dir)
    assert not second.created
    assert second.version == first.version
    assert (first.path / "_manifest.json").stat().st_mtime_ns == stamp
    assert len(list(settings.raw_dir.glob("version=*"))) == 1


def test_land_from_zip_matches_directory(settings, fixtures_dir, tmp_path):
    archive = tmp_path / "sample.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        for path in sorted(fixtures_dir.iterdir()):
            zf.write(path, f"nested/{path.name}")
    from_zip = land(settings, archive)
    from_dir = land(settings, fixtures_dir)
    assert from_zip.version == from_dir.version


def test_changed_input_creates_new_version(settings, fixtures_dir, tmp_path):
    first = land(settings, fixtures_dir)
    copy = tmp_path / "copy"
    shutil.copytree(fixtures_dir, copy)
    courses = copy / "courses.csv"
    courses.write_text(courses.read_text().replace('"268"', '"269"'))
    second = land(settings, copy)
    assert second.version != first.version
    assert settings.current_raw_marker.read_text() == second.version


def test_missing_table_is_rejected(settings, fixtures_dir, tmp_path):
    copy = tmp_path / "copy"
    shutil.copytree(fixtures_dir, copy)
    (copy / "vle.csv").unlink()
    with pytest.raises(IngestError, match="missing OULAD tables: vle"):
        land(settings, copy)


def test_header_drift_is_rejected(settings, fixtures_dir, tmp_path):
    copy = tmp_path / "copy"
    shutil.copytree(fixtures_dir, copy)
    path = copy / "courses.csv"
    lines = path.read_text().splitlines()
    lines[0] = '"code_module","code_presentation","length"'
    path.write_text("\n".join(lines) + "\n")
    with pytest.raises(IngestError, match="header"):
        land(settings, copy)


def test_download_verifies_checksum_and_reuses_cache(settings, fixtures_dir, monkeypatch, tmp_path):
    archive = tmp_path / "src.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        for path in fixtures_dir.iterdir():
            zf.write(path, path.name)
    calls = []

    def fake_fetch(url, target, _settings):
        calls.append(url)
        shutil.copy(archive, target)

    monkeypatch.setattr(landing, "_fetch", fake_fetch)
    good = settings.__class__(data_dir=settings.data_dir, source_md5=landing._md5(archive))
    path = landing.download(good)
    assert path.exists()
    landing.download(good)
    assert calls == [good.source_url]  # second call used the cache

    bad = settings.__class__(data_dir=settings.data_dir / "other", source_md5="0" * 32)
    path = landing.download(bad)  # primary fails the checksum, fallback mirror is used
    assert calls[-1] == bad.fallback_url
    assert path.exists()


def test_fallback_download_is_recorded_as_the_source(settings, fixtures_dir, monkeypatch, tmp_path):
    archive = tmp_path / "src.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        for path in fixtures_dir.iterdir():
            zf.write(path, path.name)

    def fake_fetch(url, target, _settings):
        shutil.copy(archive, target)

    monkeypatch.setattr(landing, "_fetch", fake_fetch)
    # The primary fails its md5 pin, so the (unpinned) UCI mirror is what actually lands.
    pinned = settings.__class__(data_dir=settings.data_dir, source_md5="0" * 32, http_retries=1)
    result = landing.ingest(pinned)
    assert result.manifest["source"] == pinned.fallback_url
    unpinned = settings.__class__(data_dir=tmp_path / "other", source_md5=None, http_retries=1)
    assert landing.ingest(unpinned).manifest["source"] == unpinned.source_url


def test_downloaded_data_is_always_verified_strictly(settings, fixtures_dir, tmp_path):
    from edtech_analytics.verify import is_full_release

    land(settings, fixtures_dir)  # committed sample via --archive: not strict
    assert not is_full_release(settings)
    # Same (short) content arriving from a URL claims to be the release: a truncated download
    # must fail strict verification rather than be published as a "sample".
    downloaded = settings.__class__(data_dir=tmp_path / "dl", source_md5=None)
    land(downloaded, fixtures_dir, source_url=downloaded.fallback_url)
    assert is_full_release(downloaded)
