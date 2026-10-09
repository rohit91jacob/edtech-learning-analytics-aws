"""Download the OULAD archive and land it, immutably and content-addressed, in the raw zone.

Layout (identical locally and in S3)::

    raw/oulad/version=<sha256[:16]>/<table>/<file>.csv[.gz]
    raw/oulad/version=<sha256[:16]>/_manifest.json
    raw/oulad/CURRENT                         -> "version=<sha256[:16]>"

A version directory is written to a temporary name and renamed into place, and ``CURRENT`` is
replaced last, so a crash never leaves a half-written version visible. Re-running with the same
input is a no-op.
"""

from __future__ import annotations

import gzip
import hashlib
import io
import json
import logging
import os
import re
import shutil
import tempfile
import time
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import requests

from edtech_analytics import oulad
from edtech_analytics.config import OULAD_TABLES, Settings

log = logging.getLogger(__name__)

USER_AGENT = "edtech-learning-analytics-aws/0.1 (+https://github.com/rohit91jacob/edtech-learning-analytics-aws)"
_FILE_RE = re.compile(r"^(?P<table>[A-Za-z]+)(?:\.part-\d{3})?\.csv(?:\.gz)?$")


class IngestError(RuntimeError):
    """The source archive is missing, corrupt or not the expected OULAD layout."""


@dataclass(frozen=True)
class LandingResult:
    version: str
    path: Path
    created: bool
    manifest: dict


def _md5(path: Path) -> str:
    digest = hashlib.md5(usedforsecurity=False)
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download(settings: Settings, *, force: bool = False) -> Path:
    """Download the archive once; later runs reuse it if the checksum still matches."""
    settings.downloads_dir.mkdir(parents=True, exist_ok=True)
    target = settings.downloads_dir / "anonymisedData.zip"
    if target.exists() and not force:
        if settings.source_md5 is None or _md5(target) == settings.source_md5:
            log.info("archive already downloaded", extra={"path": str(target)})
            return target
        log.warning("cached archive checksum mismatch; downloading again")

    errors: list[str] = []
    for url in (settings.source_url, settings.fallback_url):
        try:
            _fetch(url, target, settings)
        except (requests.RequestException, IngestError) as exc:
            errors.append(f"{url}: {exc}")
            log.warning("download failed", extra={"url": url, "error": str(exc)})
            continue
        if url == settings.source_url and settings.source_md5:
            actual = _md5(target)
            if actual != settings.source_md5:
                target.unlink(missing_ok=True)
                errors.append(f"{url}: md5 {actual} != expected {settings.source_md5}")
                continue
        log.info("downloaded archive", extra={"url": url, "bytes": target.stat().st_size})
        return target
    raise IngestError("could not download OULAD: " + "; ".join(errors))


def _fetch(url: str, target: Path, settings: Settings) -> None:
    tmp = target.with_suffix(".part")
    for attempt in range(1, settings.http_retries + 1):
        try:
            with requests.get(
                url,
                stream=True,
                timeout=settings.http_timeout,
                headers={"User-Agent": USER_AGENT},
            ) as resp:
                if resp.status_code in {429, 500, 502, 503, 504}:
                    raise requests.HTTPError(f"HTTP {resp.status_code}", response=resp)
                resp.raise_for_status()
                with tmp.open("wb") as fh:
                    for chunk in resp.iter_content(chunk_size=1 << 20):
                        fh.write(chunk)
            if not zipfile.is_zipfile(tmp):
                raise IngestError("response is not a zip archive")
            tmp.replace(target)
            return
        except requests.RequestException:
            if attempt == settings.http_retries:
                raise
            delay = 2**attempt
            log.info("retrying download", extra={"attempt": attempt, "sleep_s": delay})
            time.sleep(delay)


def _iter_source_files(source: Path):
    """Yield (table, filename, bytes) from a zip archive or a directory of CSV / CSV.gz files."""
    if source.is_dir():
        for path in sorted(source.rglob("*")):
            match = _FILE_RE.match(path.name)
            if path.is_file() and match:
                yield match["table"], path.name, path.read_bytes()
        return
    if not zipfile.is_zipfile(source):
        raise IngestError(f"{source} is neither a directory nor a zip archive")
    with zipfile.ZipFile(source) as zf:
        for info in sorted(zf.infolist(), key=lambda i: i.filename):
            name = Path(info.filename).name
            match = _FILE_RE.match(name)
            if not info.is_dir() and match:
                yield match["table"], name, zf.read(info)


def _header_and_rows(name: str, payload: bytes) -> tuple[tuple[str, ...], int]:
    raw = gzip.decompress(payload) if name.endswith(".gz") else payload
    text = io.StringIO(raw.decode("utf-8"))
    header = tuple(col.strip().strip('"') for col in text.readline().strip().split(","))
    rows = sum(1 for line in text if line.strip())
    return header, rows


def land(settings: Settings, source: Path, *, source_url: str | None = None) -> LandingResult:
    """Land ``source`` (zip or directory) as an immutable raw version and point CURRENT at it."""
    files = list(_iter_source_files(source))
    tables = {table for table, _, _ in files}
    missing = sorted(set(OULAD_TABLES) - tables)
    if missing:
        raise IngestError(f"{source} is missing OULAD tables: {', '.join(missing)}")
    unknown = sorted(tables - set(OULAD_TABLES))
    if unknown:
        raise IngestError(f"{source} has unexpected tables: {', '.join(unknown)}")

    content = hashlib.sha256()
    entries = []
    row_counts: dict[str, int] = dict.fromkeys(OULAD_TABLES, 0)
    for table, name, payload in files:
        header, rows = _header_and_rows(name, payload)
        expected = oulad.EXPECTED_COLUMNS[table]
        if header != expected:
            raise IngestError(f"{name}: header {header} != expected {expected}")
        sha = hashlib.sha256(payload).hexdigest()
        content.update(f"{table}/{name}:{sha}\n".encode())
        row_counts[table] += rows
        entries.append(
            {"table": table, "file": name, "sha256": sha, "bytes": len(payload), "rows": rows}
        )

    version = f"version={content.hexdigest()[:16]}"
    final = settings.raw_dir / version
    created = False
    if not (final / "_manifest.json").exists():
        settings.raw_dir.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix=".landing-", dir=settings.raw_dir))
        try:
            for table, name, payload in files:
                (staging / table).mkdir(exist_ok=True)
                (staging / table / name).write_bytes(payload)
            manifest = {
                "dataset": "OULAD",
                "version": version,
                "source": source_url or str(source.name),
                "licence": oulad.LICENCE,
                "citation": oulad.PAPER_URL,
                "landed_at": datetime.now(UTC).isoformat(timespec="seconds"),
                "row_counts": row_counts,
                "files": entries,
            }
            (staging / "_manifest.json").write_text(json.dumps(manifest, indent=2), "utf-8")
            if final.exists():  # a crashed earlier attempt without a manifest
                shutil.rmtree(final)
            staging.rename(final)
            created = True
        finally:
            if staging.exists():
                shutil.rmtree(staging, ignore_errors=True)

    _write_atomic(settings.current_raw_marker, version)
    manifest = json.loads((final / "_manifest.json").read_text("utf-8"))
    log.info(
        "landed raw version",
        extra={"version": version, "new_version": created, "rows": manifest["row_counts"]},
    )
    return LandingResult(version=version, path=final, created=created, manifest=manifest)


def _write_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(text)
    Path(tmp).replace(path)


def ingest(
    settings: Settings, *, archive: Path | None = None, force: bool = False
) -> LandingResult:
    if archive is not None:
        return land(settings, archive)
    path = download(settings, force=force)
    return land(settings, path, source_url=settings.source_url)
