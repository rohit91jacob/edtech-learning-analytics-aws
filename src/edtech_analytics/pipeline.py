"""Local end-to-end pipeline: ingest -> state machine (Spark + dbt) -> model -> verification."""

from __future__ import annotations

import logging
import uuid
from pathlib import Path

from edtech_analytics.config import Settings
from edtech_analytics.orchestration import local_runner
from edtech_analytics.quality import gold
from edtech_analytics.spark import job

log = logging.getLogger(__name__)


class DataQualityError(RuntimeError):
    """An error-level data-quality check failed (exit code 3)."""


class LocalSpark:
    """Creates the SparkSession on first use so dbt-only runs never start a JVM."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._spark = None

    def get(self):
        if self._spark is None:
            from edtech_analytics.spark.session import build_session

            self.settings.warehouse_dir.mkdir(parents=True, exist_ok=True)
            self._spark = build_session(
                "edtech-local",
                warehouse=self.settings.warehouse_dir.as_posix(),
                master=self.settings.spark_master,
                driver_memory=self.settings.spark_driver_memory,
                shuffle_partitions=self.settings.spark_shuffle_partitions,
                log_level=self.settings.spark_log_level,
            )
        return self._spark

    def stop(self) -> None:
        if self._spark is not None:
            self._spark.stop()
            self._spark = None


def run_spark_job(settings: Settings, spark: LocalSpark, args: list[str]) -> int:
    argv = list(args)
    if not settings.dq_fail_on_error and argv and argv[0] == "dq":
        argv.append("--no-fail-on-error")
    return job.run(argv, spark=spark.get())


def executors(settings: Settings, spark: LocalSpark, run_id: str) -> dict:
    def emr(params: dict) -> dict:
        args = params["JobDriver"]["SparkSubmit"]["EntryPointArguments"]
        rc = run_spark_job(settings, spark, [*args, "--run-id", run_id])
        if rc != 0:
            error = "EdTech.DataQualityFailed" if rc == job.EXIT_DQ else "States.TaskFailed"
            raise local_runner.TaskError(error, f"spark job {args[0]} exited {rc}")
        return {"JobRunName": params.get("Name"), "State": "SUCCESS"}

    def codebuild(params: dict) -> dict:
        from edtech_analytics.transform.dbt_runner import run_dbt

        run_dbt(settings, "build")
        results = gold.run_gold_checks(settings, run_id)
        errors = [r.name for r in results if r.severity == "error" and not r.passed]
        if errors and settings.dq_fail_on_error:
            raise local_runner.TaskError(
                "EdTech.DataQualityFailed", f"gold checks failed: {errors}"
            )
        return {"BuildStatus": "SUCCEEDED", "gold_checks": len(results), "gold_errors": errors}

    def sns(params: dict) -> dict:
        log.info("notification", extra={"subject": params.get("Subject")})
        return {"MessageId": "local"}

    return {
        local_runner.EMR_RESOURCE: emr,
        local_runner.CODEBUILD_RESOURCE: codebuild,
        local_runner.SNS_RESOURCE: sns,
    }


def run_state_machine(
    settings: Settings, spark: LocalSpark | None = None
) -> local_runner.Execution:
    owned = spark is None
    spark = spark or LocalSpark(settings)
    run_id = uuid.uuid4().hex[:12]
    definition = local_runner.render(local_runner.template_variables(settings))
    machine = local_runner.LocalStateMachine(definition, executors(settings, spark, run_id))
    try:
        execution = machine.run(name=f"local-{run_id}")
    finally:
        if owned:
            spark.stop()
    path = local_runner.save_execution(settings, execution)
    log.info("execution finished", extra={"status": execution.status, "record": str(path)})
    return execution


def dq_failed(execution: local_runner.Execution) -> bool:
    return any(h.get("error") == "EdTech.DataQualityFailed" for h in execution.history)


def run_pipeline(settings: Settings, *, archive: Path | None = None, force: bool = False):
    from edtech_analytics.ingest.landing import ingest

    ingest(settings, archive=archive, force=force)
    execution = run_state_machine(settings)
    if execution.status != "SUCCEEDED":
        if dq_failed(execution):
            raise DataQualityError("a data-quality gate failed; see ops/executions")
        raise RuntimeError(f"state machine {execution.name} failed: {execution.error}")
    return execution
