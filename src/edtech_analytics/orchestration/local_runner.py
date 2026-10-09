"""Execute the Step Functions definition locally.

``pipeline.asl.json`` is the single source of truth for the orchestration: Terraform renders it
into the real state machine, and this runner renders the same file with local values and walks
it state by state (Task / Fail / Succeed, ``Next``, ``End`` and ``Catch``). Each Task resource is
mapped to a local executor:

=====================================================  =================================================
ASL resource                                           local executor
=====================================================  =================================================
``arn:aws:states:::emr-serverless:startJobRun.sync``   ``spark/job.py`` in-process, same arguments
``arn:aws:states:::codebuild:startBuild.sync``         ``dbt build`` on DuckDB + gold DQ checks
``arn:aws:states:::sns:publish``                       a log line
=====================================================  =================================================

``Retry`` blocks are honoured for EMR throttling errors only on AWS; locally they never fire.
An execution record is written to ``ops/executions/<name>.json``.
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from edtech_analytics.config import Settings

log = logging.getLogger(__name__)

ASL_PATH = Path(__file__).with_name("pipeline.asl.json")
EMR_RESOURCE = "arn:aws:states:::emr-serverless:startJobRun.sync"
CODEBUILD_RESOURCE = "arn:aws:states:::codebuild:startBuild.sync"
SNS_RESOURCE = "arn:aws:states:::sns:publish"
MAX_TRANSITIONS = 50
PLACEHOLDER = re.compile(r"\$\{([a-z_]+)\}")


class StateFailedError(RuntimeError):
    def __init__(self, state: str, error: str, cause: str) -> None:
        super().__init__(f"{state}: {error}: {cause}")
        self.state = state
        self.error = error
        self.cause = cause


class TaskError(RuntimeError):
    """Raised by an executor; mapped to the ASL error name in ``error_name``."""

    def __init__(self, error_name: str, message: str) -> None:
        super().__init__(message)
        self.error_name = error_name


def template_variables(settings: Settings) -> dict[str, str]:
    """Values substituted into the ASL template for a local run."""
    return {
        "application_id": "local",
        "job_role_arn": "local",
        "code_uri": "local",
        "catalog": "hadoop",
        "silver_db": settings.silver_namespace,
        "warehouse_uri": settings.warehouse_dir.as_posix(),
        "raw_uri": settings.raw_dir.as_posix(),
        "logs_uri": (settings.ops_dir / "spark-logs").as_posix(),
        "spark_submit_parameters": "",
        "dbt_project_name": "local-dbt",
        "topic_arn": "local",
    }


def render(variables: dict[str, str], text: str | None = None) -> dict:
    """Render ``${name}`` placeholders like Terraform's templatefile(); unknown names fail."""
    raw = text if text is not None else ASL_PATH.read_text(encoding="utf-8")
    missing = sorted(set(PLACEHOLDER.findall(raw)) - set(variables))
    if missing:
        raise KeyError(f"no value for ASL placeholders: {', '.join(missing)}")
    # JSONPath ($.x) and context-object ($$.x) syntax never matches ${name}.
    rendered = PLACEHOLDER.sub(lambda m: json.dumps(variables[m[1]])[1:-1], raw)
    return json.loads(rendered)


@dataclass
class Execution:
    name: str
    started_at: str
    status: str = "RUNNING"
    history: list[dict] = field(default_factory=list)
    error: dict | None = None


Executor = Callable[[dict], dict]


class LocalStateMachine:
    def __init__(self, definition: dict, executors: dict[str, Executor]) -> None:
        self.definition = definition
        self.executors = executors

    def states(self) -> list[str]:
        return list(self.definition["States"])

    def run(self, name: str | None = None) -> Execution:
        execution = Execution(
            name=name or f"local-{uuid.uuid4().hex[:8]}",
            started_at=datetime.now(UTC).isoformat(timespec="seconds"),
        )
        context: dict = {}
        current = self.definition["StartAt"]
        for _ in range(MAX_TRANSITIONS):
            state = self.definition["States"][current]
            kind = state["Type"]
            started = datetime.now(UTC)
            entry = {"state": current, "type": kind, "started_at": started.isoformat()}
            if kind == "Fail":
                execution.history.append({**entry, "status": "FAILED"})
                execution.status = "FAILED"
                execution.error = {"Error": state.get("Error"), "Cause": state.get("Cause")}
                return execution
            if kind == "Succeed":
                execution.history.append({**entry, "status": "SUCCEEDED"})
                execution.status = "SUCCEEDED"
                return execution
            if kind != "Task":
                raise ValueError(f"local runner does not support state type {kind}")

            executor = self.executors.get(state["Resource"])
            if executor is None:
                raise ValueError(f"no local executor for {state['Resource']}")
            try:
                result = executor({**state.get("Parameters", {}), "_execution": execution.name})
            except Exception as exc:
                error_name = getattr(exc, "error_name", "States.TaskFailed")
                entry.update(status="FAILED", error=error_name, cause=str(exc))
                execution.history.append(entry)
                log.error("state failed", extra={"state": current, "error": str(exc)})
                catcher = _matching_catch(state, error_name)
                if catcher is None:
                    execution.status = "FAILED"
                    execution.error = {"Error": error_name, "Cause": str(exc)}
                    return execution
                context["error"] = {"Error": error_name, "Cause": str(exc)}
                current = catcher["Next"]
                continue
            entry.update(
                status="SUCCEEDED",
                seconds=round((datetime.now(UTC) - started).total_seconds(), 1),
                output=result,
            )
            execution.history.append(entry)
            log.info("state succeeded", extra={"state": current, "seconds": entry["seconds"]})
            result_path = state.get("ResultPath")
            if isinstance(result_path, str) and result_path.startswith("$."):
                context[result_path[2:]] = result
            if state.get("End"):
                execution.status = "SUCCEEDED"
                return execution
            current = state["Next"]
        raise RuntimeError("state machine exceeded the transition limit")


def _matching_catch(state: dict, error_name: str) -> dict | None:
    for catcher in state.get("Catch", []):
        errors = catcher["ErrorEquals"]
        if "States.ALL" in errors or error_name in errors:
            return catcher
    return None


def save_execution(settings: Settings, execution: Execution) -> Path:
    directory = settings.ops_dir / "executions"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{execution.name}.json"
    path.write_text(json.dumps(execution.__dict__, indent=2, default=str), encoding="utf-8")
    return path
