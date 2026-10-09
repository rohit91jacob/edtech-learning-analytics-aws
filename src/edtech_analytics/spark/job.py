"""Single Spark entrypoint for every batch step, locally and on EMR Serverless.

    spark-submit job.py silver   --raw-root <dir|s3://...> --warehouse <dir|s3://...> [--catalog glue]
    spark-submit job.py features --warehouse ...
    spark-submit job.py dq --layer silver|features --warehouse ...

On EMR Serverless the Step Functions state machine passes these as ``entryPointArguments``.
Exit codes: 0 ok, 1 failure, 3 data-quality gate failed.

Shipped to EMR Serverless (Python 3.9): no 3.10+ syntax.
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid

from edtech_analytics.spark import dq, features, silver
from edtech_analytics.spark.session import build_session

EXIT_DQ = 3


def resolve_raw_version(spark, raw_root: str) -> str:
    """Read the CURRENT pointer written last by the landing step."""
    rows = spark.read.text(raw_root.rstrip("/") + "/CURRENT").collect()
    if not rows or not rows[0][0].strip():
        raise RuntimeError(f"{raw_root}/CURRENT is empty")
    return rows[0][0].strip()


def parse_args(argv):
    parser = argparse.ArgumentParser(prog="edtech-spark-job")
    parser.add_argument("step", choices=["silver", "features", "dq"])
    parser.add_argument("--warehouse", required=True)
    parser.add_argument("--catalog", choices=["hadoop", "glue"], default="hadoop")
    parser.add_argument("--namespace", default="silver")
    parser.add_argument("--raw-root", help="raw/oulad root (contains CURRENT)")
    parser.add_argument("--layer", choices=["silver", "features"], default="silver")
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--master", default=None, help="only for local runs, e.g. local[*]")
    parser.add_argument("--driver-memory", default="4g")
    parser.add_argument("--shuffle-partitions", type=int, default=16)
    parser.add_argument("--log-level", default="WARN")
    parser.add_argument("--no-fail-on-error", action="store_true")
    return parser.parse_args(argv)


def run(argv=None, spark=None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    spark = spark or build_session(
        f"edtech-{args.step}",
        catalog_type=args.catalog,
        warehouse=args.warehouse,
        master=args.master,
        driver_memory=args.driver_memory,
        shuffle_partitions=args.shuffle_partitions,
        log_level=args.log_level,
    )
    run_id = args.run_id or uuid.uuid4().hex[:12]
    if args.step == "silver":
        if not args.raw_root:
            raise SystemExit("--raw-root is required for the silver step")
        version = resolve_raw_version(spark, args.raw_root)
        audits = silver.build_silver(
            spark,
            raw_root=f"{args.raw_root.rstrip('/')}/{version}",
            raw_version=version,
            namespace=args.namespace,
        )
        print(
            json.dumps(
                {"step": "silver", "raw_version": version, "tables": [a.__dict__ for a in audits]}
            )
        )
        return 0
    if args.step == "features":
        rows = features.build_weekly_activity(spark, namespace=args.namespace)
        print(json.dumps({"step": "features", "rows": rows}))
        return 0
    results = dq.run_checks(spark, namespace=args.namespace, layer=args.layer, run_id=run_id)
    errors = dq.failed_errors(results)
    print(
        json.dumps(
            {
                "step": "dq",
                "layer": args.layer,
                "run_id": run_id,
                "checks": len(results),
                "errors": [e.name for e in errors],
                "warnings": [r.name for r in results if r.severity == "warn" and not r.passed],
                "results": [r.__dict__ for r in results],
            }
        )
    )
    if errors and not args.no_fail_on_error:
        return EXIT_DQ
    return 0


if __name__ == "__main__":
    sys.exit(run())
