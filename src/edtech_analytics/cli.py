"""``edtech`` command line.

Exit codes: 0 ok · 1 failure · 2 usage/configuration · 3 data-quality gate failed ·
4 verification mismatch.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from edtech_analytics import logs
from edtech_analytics.config import ConfigError, Settings

log = logging.getLogger("edtech")

EXIT_FAILURE, EXIT_CONFIG, EXIT_DQ, EXIT_VERIFY = 1, 2, 3, 4


def _print(payload) -> None:
    sys.stdout.write(json.dumps(payload, indent=2, default=str) + "\n")


def cmd_ingest(settings: Settings, args) -> int:
    from edtech_analytics.ingest.landing import ingest

    result = ingest(settings, archive=args.archive, force=args.force)
    _print(
        {"version": result.version, "new": result.created, "rows": result.manifest["row_counts"]}
    )
    return 0


def cmd_land_s3(settings: Settings, args) -> int:
    from edtech_analytics.ingest.s3 import land_to_s3, s3_client

    client = s3_client(endpoint_url=args.endpoint_url, region=args.region)
    result = land_to_s3(
        settings, args.bucket, prefix=args.prefix, client=client, kms_key_id=args.kms_key_id
    )
    _print(result.__dict__)
    return 0


def cmd_spark(settings: Settings, args) -> int:
    from edtech_analytics.pipeline import LocalSpark, run_spark_job

    spark = LocalSpark(settings)
    try:
        base = ["--warehouse", settings.warehouse_dir.as_posix()]
        base += ["--namespace", settings.silver_namespace]
        if args.step == "silver":
            rc = run_spark_job(
                settings, spark, ["silver", "--raw-root", settings.raw_dir.as_posix(), *base]
            )
        elif args.step == "features":
            rc = run_spark_job(settings, spark, ["features", *base])
        else:
            rc = run_spark_job(settings, spark, ["dq", "--layer", args.layer, *base])
    finally:
        spark.stop()
    return EXIT_DQ if rc == 3 else rc


def cmd_dbt(settings: Settings, args) -> int:
    from edtech_analytics.transform.dbt_runner import run_dbt

    run_dbt(settings, args.dbt_command, *args.dbt_args, target=args.target)
    return 0


def cmd_dq_gold(settings: Settings, args) -> int:
    import uuid

    from edtech_analytics.quality.gold import run_gold_checks

    results = run_gold_checks(settings, uuid.uuid4().hex[:12])
    _print([r.__dict__ for r in results])
    failed = [r for r in results if r.severity == "error" and not r.passed]
    return EXIT_DQ if failed and settings.dq_fail_on_error else 0


def cmd_run(settings: Settings, args) -> int:
    from edtech_analytics.pipeline import dq_failed, run_state_machine

    execution = run_state_machine(settings)
    _print({"execution": execution.name, "status": execution.status, "error": execution.error})
    if execution.status == "SUCCEEDED":
        return 0
    return EXIT_DQ if dq_failed(execution) else EXIT_FAILURE


def cmd_train(settings: Settings, args) -> int:
    from edtech_analytics.model.risk import train

    report = train(settings)
    keys = ["holdout_presentation", "train_rows", "test_rows", "train_auc", "test_auc"]
    keys += ["test_auc_ci95", "baseline_clicks_only_test_auc", "test_average_precision"]
    _print({k: report.metrics[k] for k in keys})
    return 0


def cmd_verify(settings: Settings, args) -> int:
    from edtech_analytics.verify import is_full_release, run_verification, write_report

    strict = is_full_release(settings) if args.strict is None else args.strict
    payload = write_report(settings, run_verification(settings), strict)
    _print({k: payload[k] for k in ("strict", "matches", "documented_mismatches", "mismatches")})
    return EXIT_VERIFY if strict and payload["mismatches"] else 0


def cmd_report(settings: Settings, args) -> int:
    from edtech_analytics.report.site import build_site

    summary = build_site(settings, args.out)
    _print(summary)
    return 0


def cmd_pipeline(settings: Settings, args) -> int:
    from edtech_analytics.pipeline import DataQualityError, run_pipeline

    try:
        execution = run_pipeline(settings, archive=args.archive, force=args.force)
    except DataQualityError as exc:
        log.error(str(exc))
        return EXIT_DQ
    log.info("state machine succeeded", extra={"execution": execution.name})
    rc = cmd_train(settings, args)
    rc = rc or cmd_verify(settings, argparse.Namespace(strict=None))
    if rc == 0 and args.report:
        rc = cmd_report(settings, argparse.Namespace(out=args.report))
    return rc


def cmd_package_emr(settings: Settings, args) -> int:
    from edtech_analytics.aws.emr_package import build

    _print(build(args.out))
    return 0


def cmd_asl(settings: Settings, args) -> int:
    from edtech_analytics.orchestration.local_runner import render, template_variables

    definition = render(template_variables(settings))
    _print(definition if args.full else list(definition["States"]))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="edtech", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("ingest", help="download OULAD (or use --archive) and land it in raw/")
    p.add_argument("--archive", type=Path, help="zip or directory of CSV/CSV.gz files")
    p.add_argument("--force", action="store_true", help="download again even if cached")
    p.set_defaults(func=cmd_ingest)

    p = sub.add_parser("land-s3", help="mirror the current raw version to an S3 bucket")
    p.add_argument("--bucket", required=True)
    p.add_argument("--prefix", default="oulad")
    p.add_argument("--endpoint-url", help="e.g. http://localhost:4566 for LocalStack")
    p.add_argument("--region", default=None)
    p.add_argument("--kms-key-id", default=None)
    p.set_defaults(func=cmd_land_s3)

    p = sub.add_parser("spark", help="run one Spark step locally")
    p.add_argument("step", choices=["silver", "features", "dq"])
    p.add_argument("--layer", choices=["silver", "features"], default="silver")
    p.set_defaults(func=cmd_spark)

    p = sub.add_parser("dbt", help="run dbt against the local DuckDB warehouse")
    p.add_argument("dbt_command", nargs="?", default="build")
    p.add_argument("dbt_args", nargs=argparse.REMAINDER)
    p.add_argument("--target", default=None)
    p.set_defaults(func=cmd_dbt)

    p = sub.add_parser("dq-gold", help="gold reconciliation checks over the marts")
    p.set_defaults(func=cmd_dq_gold)

    p = sub.add_parser("run", help="execute the Step Functions definition locally")
    p.set_defaults(func=cmd_run)

    p = sub.add_parser("train", help="train and evaluate the withdrawal-risk baseline")
    p.set_defaults(func=cmd_train)

    p = sub.add_parser("verify", help="reconcile outputs with published figures")
    group = p.add_mutually_exclusive_group()
    group.add_argument("--strict", dest="strict", action="store_true", default=None)
    group.add_argument("--no-strict", dest="strict", action="store_false")
    p.set_defaults(func=cmd_verify)

    p = sub.add_parser("report", help="write the static results site")
    p.add_argument("--out", type=Path, default=Path("site"))
    p.set_defaults(func=cmd_report)

    p = sub.add_parser("pipeline", help="ingest -> state machine -> train -> verify [-> report]")
    p.add_argument("--archive", type=Path)
    p.add_argument("--force", action="store_true")
    p.add_argument("--report", type=Path, default=None, help="also write the site here")
    p.set_defaults(func=cmd_pipeline)

    p = sub.add_parser("package-emr", help="build the EMR Serverless job artefacts")
    p.add_argument("--out", type=Path, default=Path("dist/emr"))
    p.set_defaults(func=cmd_package_emr)

    p = sub.add_parser("asl", help="print the locally rendered state machine")
    p.add_argument("--full", action="store_true")
    p.set_defaults(func=cmd_asl)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        settings = Settings.from_env()
    except ConfigError as exc:
        sys.stderr.write(f"configuration error: {exc}\n")
        return EXIT_CONFIG
    logs.configure(settings.log_level, settings.log_format)
    try:
        return args.func(settings, args)
    except ConfigError as exc:
        log.error(str(exc))
        return EXIT_CONFIG
    except Exception:
        log.exception("command failed")
        return EXIT_FAILURE


if __name__ == "__main__":
    sys.exit(main())
