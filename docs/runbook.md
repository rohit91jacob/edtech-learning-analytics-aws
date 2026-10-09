# Runbook

Exit codes of every `edtech` command: `0` ok · `1` failure · `2` usage or configuration ·
`3` data-quality gate failed · `4` verification mismatch (strict runs on the full release).

## Routine run (local)

```bash
make pipeline          # ingest -> state machine -> train -> verify -> site
```

`ingest` is a no-op when the archive is cached with the pinned md5 and the raw version already
exists. Every Spark table is replaced atomically (`createOrReplace`, one Iceberg snapshot per table)
and every dbt model is rebuilt from silver, so a rerun produces identical tables; the end-to-end
test `test_rerun_is_idempotent` asserts this with content hashes.

Run a single stage:

```bash
uv run edtech spark silver | features | dq --layer silver|features
uv run edtech dbt build [-- --select mart_dropout_risk_features+]
uv run edtech dq-gold
uv run edtech train | verify | report --out site
uv run edtech run      # just the state machine
```

## A data-quality gate failed (exit 3)

1. Find the failing check. Silver/feature checks: the JSON line printed by the job, or
   `SELECT * FROM iceberg_scan('<data>/warehouse/silver/ops_dq_results') ORDER BY checked_at DESC`.
   Gold checks: `ops/dq_results_gold.json`. dbt tests: the dbt output (`dbt/target/run_results.json`).
2. The execution record `ops/executions/<name>.json` shows which state failed and that
   `NotifyFailure` ran. Nothing downstream of the failed gate ran (dbt does not build on bad
   silver; the model is not retrained).
3. Typical causes: a changed source file (check `raw/oulad/*/_manifest.json`: a new version means
   the archive changed), a code change that breaks a join, or a deliberately corrupted test input.
4. Fix and rerun `make pipeline`. Only use `EDTECH_DQ_FAIL_ON_ERROR=false` to inspect outputs
   locally, never in the scheduled refresh.

## Verification mismatch (exit 4)

Strict mode applies only when the raw version has the full release's 10,655,280 clickstream rows.
A new `mismatch` means the computed figure no longer equals the paper. Compare `ops/verification.json`
with [verification.md](verification.md). If the archive changed upstream, the md5 check at
download time would already have failed, so suspect a code change first.

## Download problems

* `md5 ... != expected`: figshare served different bytes. The pipeline deletes the file and uses
  the UCI mirror (no checksum; its archive differs only in missing-value encoding). Investigate
  before updating `FIGSHARE_MD5` in `config.py`.
* Both mirrors down: pass a local copy, `edtech ingest --archive /path/to/anonymisedData.zip`.
* Behind a proxy, set `HTTPS_PROXY`; `EDTECH_HTTP_TIMEOUT_SECONDS` / `EDTECH_HTTP_RETRIES` tune
  the retry loop (exponential backoff).

## Spark problems

* `HADOOP_HOME and hadoop.home.dir are unset` on Windows: Spark needs Hadoop's `winutils.exe` on
  native Windows. Run the Spark steps in WSL2 or Linux (that is how this project was developed).
* The first run downloads the Iceberg runtime jar (47 MB) from Maven Central. Offline, point
  `EDTECH_SPARK_JARS_DIR` at a directory containing
  `iceberg-spark-runtime-3.5_2.12-1.10.1.jar`.
* Out of memory on the full release: raise `EDTECH_SPARK_DRIVER_MEMORY` (default `4g`).

## Rebuilding from scratch

Bronze is immutable, so this is always safe:

```bash
rm -rf "$EDTECH_DATA_DIR/warehouse" "$EDTECH_DATA_DIR/warehouse.duckdb" "$EDTECH_DATA_DIR/ops"
make pipeline
```

## Scheduled refresh failed

`refresh.yml` opens (or comments on) an issue titled **Scheduled refresh is failing**.

1. Open the linked run. The pipeline step's exit code tells you the class of failure (above).
2. Network errors on figshare: re-run the workflow. The archive is deliberately not cached in
   CI, so every refresh re-downloads it; if figshare stays down the UCI mirror is tried next and
   recorded as the `source` in the raw `_manifest.json` (that mirror is not md5-pinned, so the
   strict verification step is what guards it).
3. Dependency breakage (Dependabot merged a bad minor version): reproduce with `uv sync --frozen`
   at that commit, pin or revert.
4. Close the issue after a green run. `keepalive.yml` re-enables the schedule twice a month, so
   GitHub's 60-day inactivity rule does not silently stop it.

## Deploying to AWS

Nothing in this repository has been deployed; the Terraform is validated in CI only. To deploy:

1. Use an account you control. Create an S3 state bucket and uncomment the backend in
   `infra/versions.tf`. Copy `infra/terraform.tfvars.example` to `terraform.tfvars`.
2. Activate the `project` cost-allocation tag in Billing (the budget filters on it).
3. `terraform -chdir=infra init && terraform -chdir=infra plan` and review. Apply as a human with
   an administrator session; the CI deploy role cannot change infrastructure.
4. Set repository variables from the outputs: `AWS_DEPLOY_ROLE_ARN`, `EDTECH_CODE_BUCKET`,
   `EDTECH_RAW_BUCKET`, `EDTECH_STATE_MACHINE_ARN`, `EDTECH_KMS_KEY_ARN` (and `AWS_REGION`), and
   create a protected GitHub environment named `aws-dev`.
5. Run **deploy** (workflow dispatch) with `land_raw` and `start_pipeline` ticked. It uploads
   `job.py`, `edtech_spark.zip` and the dbt bundle, mirrors OULAD into the raw bucket and starts
   the state machine.
6. Failures publish to the SNS topic (subscribe with `notification_emails`) and the
   `<project>-<env>-pipeline-failed` alarm. EMR job logs land in `s3://<lake>/emr-logs/`, dbt logs
   in `/edtech/<env>/codebuild/dbt`.

Things that will differ on real AWS and are untested here: IAM policy completeness (written least
privilege, never exercised), EMR Serverless sizing, Athena semantics of the compiled SQL (only
parsed as Trino), and Lake Formation, if the account enforces it on the Glue catalog.

## Tearing down

`terraform destroy` refuses to delete non-empty buckets unless `force_destroy = true` (keep it
false outside throwaway dev). The KMS key has a 30-day deletion window.
