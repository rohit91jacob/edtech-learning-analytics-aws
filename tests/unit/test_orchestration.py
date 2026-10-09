from __future__ import annotations

import json
import re
from pathlib import Path

import boto3
import pytest
from moto import mock_aws

from edtech_analytics.orchestration import local_runner as lr

ROOT = Path(__file__).resolve().parents[2]
EXPECTED_ORDER = [
    "BuildSilver",
    "SilverQualityGate",
    "BuildActivityFeatures",
    "FeatureQualityGate",
    "DbtBuildAndTest",
    "NotifySuccess",
]


def _definition(settings):
    return lr.render(lr.template_variables(settings))


def test_definition_renders_to_valid_asl(settings):
    definition = _definition(settings)
    assert definition["StartAt"] == "BuildSilver"
    for name, state in definition["States"].items():
        assert "${" not in json.dumps(state), name
        if state["Type"] == "Task" and name not in {"NotifySuccess", "NotifyFailure"}:
            assert state["Catch"][0]["Next"] == "NotifyFailure"


def test_unknown_placeholder_fails():
    with pytest.raises(KeyError, match="nope"):
        lr.render({}, '{"a": "${nope}"}')


def test_terraform_passes_every_placeholder():
    """The Terraform templatefile() call must provide exactly the placeholders the ASL uses."""
    asl = (ROOT / "src/edtech_analytics/orchestration/pipeline.asl.json").read_text()
    used = set(lr.PLACEHOLDER.findall(asl))
    tf = (ROOT / "infra/modules/orchestration/main.tf").read_text()
    block = re.search(r"templatefile\((.*?)\n  \}\)", tf, re.S).group(1)
    provided = set(re.findall(r"^\s+(\w+)\s+=", block, re.M))
    assert used == provided


def _fake(log, fail_on=None, error="States.TaskFailed"):
    def make(kind):
        def run(params):
            name = params.get("Name") or params.get("ProjectName") or params.get("Subject")
            log.append(name)
            if name == fail_on:
                raise lr.TaskError(error, "boom")
            return {"ok": kind}

        return run

    return {
        lr.EMR_RESOURCE: make("emr"),
        lr.CODEBUILD_RESOURCE: make("codebuild"),
        lr.SNS_RESOURCE: make("sns"),
    }


def test_happy_path_visits_states_in_order(settings):
    calls: list[str] = []
    execution = lr.LocalStateMachine(_definition(settings), _fake(calls)).run("t1")
    assert execution.status == "SUCCEEDED"
    assert [h["state"] for h in execution.history] == EXPECTED_ORDER
    assert calls[:4] == [
        "edtech-silver",
        "edtech-dq-silver",
        "edtech-features",
        "edtech-dq-features",
    ]


def test_failure_is_caught_notified_and_fails(settings):
    calls: list[str] = []
    machine = lr.LocalStateMachine(
        _definition(settings),
        _fake(calls, fail_on="edtech-dq-silver", error="EdTech.DataQualityFailed"),
    )
    execution = machine.run("t2")
    assert execution.status == "FAILED"
    states = [h["state"] for h in execution.history]
    assert states == ["BuildSilver", "SilverQualityGate", "NotifyFailure", "PipelineFailed"]
    assert execution.history[1]["error"] == "EdTech.DataQualityFailed"
    assert "edtech-features" not in calls


def test_emr_arguments_match_the_spark_job_cli(settings):
    from edtech_analytics.spark.job import parse_args

    definition = _definition(settings)
    for state in definition["States"].values():
        if state.get("Resource") == lr.EMR_RESOURCE:
            args = state["Parameters"]["JobDriver"]["SparkSubmit"]["EntryPointArguments"]
            parsed = parse_args(args)
            assert parsed.catalog == "hadoop"
            assert parsed.warehouse == settings.warehouse_dir.as_posix()


def test_state_machine_accepted_by_stepfunctions_api(monkeypatch):
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    aws_values = {
        "application_id": "00fabcdefghij012",
        "job_role_arn": "arn:aws:iam::123456789012:role/edtech-dev-emr-job",
        "code_uri": "s3://edtech-dev-code/jobs",
        "catalog": "glue",
        "silver_db": "edtech_dev_silver",
        "warehouse_uri": "s3://edtech-dev-lake/warehouse",
        "raw_uri": "s3://edtech-dev-raw/oulad",
        "logs_uri": "s3://edtech-dev-logs/emr/",
        "spark_submit_parameters": "--conf spark.executor.cores=4",
        "dbt_project_name": "edtech-dev-dbt",
        "topic_arn": "arn:aws:sns:eu-west-2:123456789012:edtech-dev-pipeline",
    }
    definition = lr.render(aws_values)
    with mock_aws():
        sfn = boto3.client("stepfunctions", region_name="eu-west-2")
        arn = sfn.create_state_machine(
            name="edtech-dev-pipeline",
            definition=json.dumps(definition),
            roleArn="arn:aws:iam::123456789012:role/edtech-dev-sfn",
        )["stateMachineArn"]
        described = sfn.describe_state_machine(stateMachineArn=arn)
    assert json.loads(described["definition"])["StartAt"] == "BuildSilver"
