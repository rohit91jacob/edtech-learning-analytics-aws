from __future__ import annotations

import boto3
import pytest
from moto import mock_aws

from edtech_analytics.ingest.landing import land
from edtech_analytics.ingest.s3 import land_to_s3


@pytest.fixture
def s3(monkeypatch):
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "eu-west-2")
    with mock_aws():
        client = boto3.client("s3", region_name="eu-west-2")
        client.create_bucket(
            Bucket="raw", CreateBucketConfiguration={"LocationConstraint": "eu-west-2"}
        )
        yield client


def test_mirror_to_s3_is_idempotent(settings, fixtures_dir, s3):
    landed = land(settings, fixtures_dir)
    first = land_to_s3(settings, "raw", client=s3)
    n_files = len(landed.manifest["files"])
    assert (first.uploaded, first.skipped) == (n_files, 0)
    second = land_to_s3(settings, "raw", client=s3)
    assert (second.uploaded, second.skipped) == (0, n_files)

    pointer = s3.get_object(Bucket="raw", Key="oulad/CURRENT")["Body"].read().decode()
    assert pointer == landed.version
    keys = {o["Key"] for o in s3.list_objects_v2(Bucket="raw")["Contents"]}
    assert f"oulad/{landed.version}/studentVle/studentVle.part-000.csv.gz" in keys
    head = s3.head_object(Bucket="raw", Key=f"oulad/{landed.version}/courses/courses.csv")
    assert len(head["Metadata"]["sha256"]) == 64


def test_kms_encryption_is_requested(settings, fixtures_dir, s3):
    land(settings, fixtures_dir)
    kms = boto3.client("kms", region_name="eu-west-2")
    key_id = kms.create_key()["KeyMetadata"]["KeyId"]
    land_to_s3(settings, "raw", client=s3, kms_key_id=key_id)
    head = s3.head_object(Bucket="raw", Key="oulad/CURRENT")
    assert head["ServerSideEncryption"] == "aws:kms"
