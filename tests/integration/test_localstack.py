"""Integration against LocalStack (CI only: needs EDTECH_AWS_ENDPOINT_URL).

* the raw zone lands in S3 and a second landing uploads nothing;
* the Terraform-rendered state machine is accepted by Step Functions, and an execution takes the
  failure path (LocalStack community has no EMR Serverless, so the first task fails), which
  proves the Catch -> NotifyFailure (SNS) -> Fail wiring end to end in a real ASL interpreter.
"""

from __future__ import annotations

import json
import os
import time

import boto3
import pytest

from edtech_analytics.ingest.landing import land
from edtech_analytics.ingest.s3 import land_to_s3
from edtech_analytics.orchestration.local_runner import render

ENDPOINT = os.environ.get("EDTECH_AWS_ENDPOINT_URL")
pytestmark = [
    pytest.mark.localstack,
    pytest.mark.skipif(not ENDPOINT, reason="needs a LocalStack endpoint"),
]
REGION = os.environ.get("AWS_DEFAULT_REGION", "eu-west-2")
ACCOUNT = "000000000000"


def client(name: str):
    return boto3.client(name, endpoint_url=ENDPOINT, region_name=REGION)


def test_raw_landing_round_trip(settings, fixtures_dir):
    s3 = client("s3")
    s3.create_bucket(Bucket="edtech-raw", CreateBucketConfiguration={"LocationConstraint": REGION})
    landed = land(settings, fixtures_dir)
    first = land_to_s3(settings, "edtech-raw", client=s3)
    second = land_to_s3(settings, "edtech-raw", client=s3)
    assert first.uploaded == len(landed.manifest["files"])
    assert second.uploaded == 0
    body = s3.get_object(Bucket="edtech-raw", Key="oulad/CURRENT")["Body"].read().decode()
    assert body == landed.version


def test_state_machine_failure_path():
    sns = client("sns")
    topic = sns.create_topic(Name="edtech-dev-pipeline")["TopicArn"]
    iam = client("iam")
    role = iam.create_role(
        RoleName="edtech-dev-pipeline-sfn",
        AssumeRolePolicyDocument=json.dumps(
            {
                "Version": "2012-10-17",
                "Statement": [
                    {
                        "Effect": "Allow",
                        "Principal": {"Service": "states.amazonaws.com"},
                        "Action": "sts:AssumeRole",
                    }
                ],
            }
        ),
    )["Role"]["Arn"]
    definition = render(
        {
            "application_id": "00fnotreal000000",
            "job_role_arn": f"arn:aws:iam::{ACCOUNT}:role/edtech-dev-emr-job",
            "code_uri": "s3://edtech-code/jobs",
            "catalog": "glue",
            "silver_db": "edtech_dev_silver",
            "warehouse_uri": "s3://edtech-lake/warehouse",
            "raw_uri": "s3://edtech-raw/oulad",
            "logs_uri": "s3://edtech-lake/emr-logs/",
            "spark_submit_parameters": "--conf spark.executor.cores=4",
            "dbt_project_name": "edtech-dev-dbt",
            "topic_arn": topic,
        }
    )
    sfn = client("stepfunctions")
    arn = sfn.create_state_machine(
        name="edtech-dev-pipeline", definition=json.dumps(definition), roleArn=role
    )["stateMachineArn"]
    execution = sfn.start_execution(stateMachineArn=arn, input="{}")["executionArn"]
    status = "RUNNING"
    for _ in range(60):
        status = sfn.describe_execution(executionArn=execution)["status"]
        if status != "RUNNING":
            break
        time.sleep(1)
    assert status == "FAILED"
    events = sfn.get_execution_history(executionArn=execution, maxResults=200)["events"]
    entered = [
        e["stateEnteredEventDetails"]["name"] for e in events if "stateEnteredEventDetails" in e
    ]
    assert entered[0] == "BuildSilver"
    assert "NotifyFailure" in entered
    assert "BuildActivityFeatures" not in entered
