"""Mirror a landed raw version to S3 (the real raw bucket, LocalStack in CI, or moto in tests).

Objects are keyed exactly like the local raw zone. Each object carries its sha256 as metadata, so
re-uploads are skipped when the bytes are already there, and ``CURRENT`` is written last: readers
that follow the pointer never see a partially uploaded version.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

import boto3
from botocore.exceptions import ClientError

from edtech_analytics.config import Settings

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class S3LandingResult:
    bucket: str
    prefix: str
    version: str
    uploaded: int
    skipped: int


def s3_client(endpoint_url: str | None = None, region: str | None = None):
    return boto3.client("s3", endpoint_url=endpoint_url, region_name=region)


def _remote_sha(client, bucket: str, key: str) -> str | None:
    try:
        head = client.head_object(Bucket=bucket, Key=key)
    except ClientError as exc:
        if exc.response["Error"]["Code"] in {"404", "NoSuchKey", "NotFound"}:
            return None
        raise
    return head.get("Metadata", {}).get("sha256")


def land_to_s3(
    settings: Settings,
    bucket: str,
    *,
    prefix: str = "oulad",
    client=None,
    kms_key_id: str | None = None,
) -> S3LandingResult:
    client = client or s3_client()
    version_dir = settings.current_raw_version()
    manifest = json.loads((version_dir / "_manifest.json").read_text("utf-8"))
    version = manifest["version"]
    sha_by_file = {(e["table"], e["file"]): e["sha256"] for e in manifest["files"]}

    extra: dict[str, str] = {}
    if kms_key_id:
        extra = {"ServerSideEncryption": "aws:kms", "SSEKMSKeyId": kms_key_id}

    uploaded = skipped = 0
    for (table, name), sha in sorted(sha_by_file.items()):
        key = f"{prefix}/{version}/{table}/{name}"
        if _remote_sha(client, bucket, key) == sha:
            skipped += 1
            continue
        path: Path = version_dir / table / name
        client.upload_file(str(path), bucket, key, ExtraArgs={"Metadata": {"sha256": sha}, **extra})
        uploaded += 1

    client.put_object(
        Bucket=bucket,
        Key=f"{prefix}/{version}/_manifest.json",
        Body=json.dumps(manifest, indent=2).encode(),
        ContentType="application/json",
        **extra,
    )
    client.put_object(Bucket=bucket, Key=f"{prefix}/CURRENT", Body=version.encode(), **extra)
    log.info(
        "mirrored raw version to s3",
        extra={"bucket": bucket, "version": version, "uploaded": uploaded, "skipped": skipped},
    )
    return S3LandingResult(bucket, prefix, version, uploaded, skipped)
