# EdTech learning analytics on AWS (OULAD)

[![ci](https://github.com/rohit91jacob/edtech-learning-analytics-aws/actions/workflows/ci.yml/badge.svg)](https://github.com/rohit91jacob/edtech-learning-analytics-aws/actions/workflows/ci.yml)
[![refresh](https://github.com/rohit91jacob/edtech-learning-analytics-aws/actions/workflows/refresh.yml/badge.svg)](https://github.com/rohit91jacob/edtech-learning-analytics-aws/actions/workflows/refresh.yml)
[![Live results](https://img.shields.io/badge/live%20results-GitHub%20Pages-0b5cad.svg)](https://rohit91jacob.github.io/edtech-learning-analytics-aws/)
[![License: MIT](https://img.shields.io/badge/code-MIT-blue.svg)](LICENSE)
[![Data: CC BY 4.0](https://img.shields.io/badge/data-CC%20BY%204.0-green.svg)](DATA_LICENSE.md)
![Python 3.12](https://img.shields.io/badge/python-3.12-blue.svg)
![Spark 3.5.8](https://img.shields.io/badge/spark-3.5.8-orange.svg)
![Iceberg 1.10.1](https://img.shields.io/badge/iceberg-1.10.1-lightblue.svg)
![dbt 1.12](https://img.shields.io/badge/dbt-1.12-ff694b.svg)
![Terraform](https://img.shields.io/badge/terraform-validated%2C%20not%20deployed-844fba.svg)

Mastery-learning analytics in the style of an EdTech product (engagement, an assessment
mastery funnel, time to first submission, withdrawal risk, which learning activities go with
passing, and outcome gaps by group), built as an AWS batch lakehouse:
**S3 → EMR Serverless (PySpark) → Apache Iceberg → dbt on Athena → Step Functions.**

* **Real data, honestly scoped.** Khan Academy's learner data is not public, so this project uses
  the **Open University Learning Analytics Dataset** (OULAD, CC BY 4.0): 32,593 student enrolments
  on 22 module presentations (2013–2014), their assessments, and 10,655,280 rows of daily VLE
  clickstream. It is downloaded at runtime from the figshare record cited by the paper.
* **Emulated cloud, real code paths.** Nothing here runs on AWS. The PySpark jobs that would run on
  EMR Serverless run locally with the same Spark and Iceberg versions as `emr-7.14.0`; the Iceberg
  Glue catalog is a local Hadoop catalog; DuckDB stands in for Athena under the same dbt project
  (which CI also compiles for Athena); and the **same Step Functions definition** that Terraform
  deploys is executed by a local runner. S3 code is tested against moto, and against LocalStack
  in CI.
* **Verified.** Every table's row count and the paper's module table (Kuzilek et al., 2017, Table 1)
  match exactly: 17 of 20 checks match, and the other 3 are places where the published sources
  contradict the data or each other, explained in [verification](docs/verification.md).
* **Gated.** 30 silver and 8 feature checks in Spark, 59 dbt tests and 11 gold reconciliation
  checks. Error-level failures stop the state machine before anything downstream runs (exit 3).
* **A baseline model, evaluated honestly.** Logistic regression for withdrawal risk at course day
  28, trained on 15 presentations and scored only on the 7 held-out 2014J presentations:
  **ROC AUC 0.669** (95% bootstrap CI 0.654–0.681) against 0.591 for a clicks-only baseline, with
  per-module and fairness-slice metrics. It is modest, and the site says so.

The weekly `refresh` workflow rebuilds everything from the public download and publishes the
results site: **[rohit91jacob.github.io/edtech-learning-analytics-aws](https://rohit91jacob.github.io/edtech-learning-analytics-aws/)**.

## Architecture

```mermaid
flowchart LR
  SRC[("OULAD on figshare<br/>anonymisedData.zip<br/>md5-pinned; UCI fallback")]

  subgraph S3["S3 (local dir / LocalStack / moto)"]
    RAW[("raw/oulad/version=sha/<br/>immutable, manifest, CURRENT")]
  end

  subgraph SFN["Step Functions: pipeline.asl.json (local runner / AWS)"]
    direction LR
    J1["EMR Serverless<br/>BuildSilver"] --> G1{{"SilverQualityGate<br/>30 checks"}}
    G1 --> J2["EMR Serverless<br/>BuildActivityFeatures"] --> G2{{"FeatureQualityGate<br/>8 checks"}}
    G2 --> DBT["CodeBuild: dbt build<br/>+ 59 tests (+ 11 gold checks locally)"]
    DBT --> OK["SNS success"]
    J1 & G1 & J2 & G2 & DBT -. Catch .-> FAIL["SNS failure → Fail"]
  end

  subgraph ICE["Iceberg (Hadoop catalog / Glue Data Catalog)"]
    SIL[("silver: 7 typed tables<br/>+ weekly activity, engagement<br/>+ ops_load_audit, ops_dq_results")]
  end

  subgraph WH["DuckDB / Athena"]
    MARTS[("marts: engagement cohorts · mastery funnel<br/>time to first submission · risk features<br/>activity effectiveness · fairness slices")]
  end

  SRC -->|edtech ingest| RAW -->|edtech land-s3| RAW
  RAW --> J1
  J1 --> SIL
  J2 --> SIL
  SIL --> DBT --> MARTS
  MARTS --> ML["edtech train<br/>logistic regression<br/>held-out 2014J"]
  MARTS --> VER{"edtech verify<br/>vs the OULAD paper"}
  ML --> SITE["edtech report<br/>static site → GitHub Pages"]
  VER --> SITE
```

| Component | Code | What it does |
|---|---|---|
| Ingest | `ingest/landing.py` | Downloads the archive (retries, md5 check, UCI fallback), checks every header, lands it content-addressed with a manifest that records the URL it really came from; `CURRENT` is written last. Downloaded data is always verified strictly. Reruns are no-ops. |
| S3 landing | `ingest/s3.py` | Mirrors the raw version to a bucket with SSE-KMS; skips objects whose sha256 is already there. Tested on moto and LocalStack. |
| Silver job | `spark/silver.py` | Reads every column as a string, normalises both missing-value encodings, casts explicitly and **counts** cast failures, writes Iceberg v2 (zstd) tables atomically. |
| Features job | `spark/features.py` | Aggregates the 10.6M-row clickstream to enrolment × week (× activity type) so the warehouse never scans the raw clicks. |
| Spark DQ | `spark/dq.py` | Keys, domains, referential integrity, ranges, exact click reconciliation. Results appended to `ops_dq_results`; errors exit 3. |
| Spark entry point | `spark/job.py` | One CLI for every step; the Step Functions `EntryPointArguments` call it. Python 3.9-compatible for the EMR 7.x image. |
| dbt | `dbt/` | Staging → intermediate → 8 marts, 59 tests, cross-database macros (DuckDB `quantile_cont` / Athena `approx_percentile`, safe division). |
| Gold DQ | `quality/gold.py` | Reconciles marts with each other and with silver. |
| Orchestration | `orchestration/pipeline.asl.json`, `local_runner.py` | One ASL file: Terraform renders it into the real state machine; the local runner walks the same states, `Catch`es and failure path. |
| Model | `model/risk.py` | Logistic regression, temporal hold-out, bootstrap CI, clicks-only baseline, slice metrics; no protected attributes as inputs. |
| Verification | `verify.py` | 20 checks against the paper and the UCI description file. |
| Results site | `report/site.py` | Plain HTML and inline SVG generated from the marts (no JavaScript, no external assets). |
| EMR packaging | `aws/emr_package.py` | Reproducible `job.py` + `edtech_spark.zip` (`--py-files`). |
| Infrastructure | `infra/` | Terraform modules: storage + KMS, Glue + Athena, EMR Serverless + job role, Step Functions + CodeBuild + SNS + schedule + alarm, budget, GitHub OIDC deploy role. |

## Tech stack

All Python dependencies are pinned in `uv.lock`.

| Layer | Technology | Version |
|---|---|---|
| Language | Python | 3.12 (Spark job modules also compile on 3.9, the EMR 7.x runtime) |
| Batch processing | Apache Spark (PySpark) | 3.5.8 (= `emr-7.14.0`) |
| Table format | Apache Iceberg (`iceberg-spark-runtime-3.5_2.12`) | 1.10.1 (= `emr-7.14.0`) |
| JVM | Temurin / OpenJDK | 17 |
| Warehouse (local Athena stand-in) | DuckDB + `iceberg` extension | 1.5.6 |
| Transformations | dbt-core, dbt-duckdb, dbt-athena (compile only) | 1.12.5, 1.11.0, 1.11.1 |
| Model | scikit-learn, pandas | 1.9.1, 3.0.6 |
| AWS SDK / emulators | boto3, moto (tests), LocalStack (CI) | 1.43, 5.2, 4.14.0 |
| Infrastructure | Terraform, AWS provider, tflint, checkov | 1.16.5, ~> 6.68, 0.64.0, 3.3.26 |
| Packaging | uv, hatchling | 0.10 |
| Quality tooling | pytest 9, ruff 0.16, sqlglot (Trino parse check), pre-commit, gitleaks, Dependabot | |

## Data sources

| Source | What | Licence | Refresh cadence | Used? |
|---|---|---|---|---|
| [OULAD](https://doi.org/10.6084/m9.figshare.5081998.v1) (figshare; [UCI mirror](https://archive.ics.uci.edu/dataset/349/open+university+learning+analytics+dataset)) | 7 CSV tables: courses, assessments, VLE materials, student info, registrations, assessment results, daily VLE clicks | CC BY 4.0 | **Static.** Released 2015 (files dated 2015), figshare record 2017; the archive is md5-pinned | Yes, primary |
| ASSISTments (WPI) | tutoring logs | Terms forbid sharing ("I agree to not give this data to anyone else") and require a written agreement | – | No, see [DATA_LICENSE.md](DATA_LICENSE.md) |
| Khan Academy | – | Not public | – | No |

**Known gaps and quirks in OULAD** (all handled and documented): 11 exams have no date; 18 of 24
exams have no results in the release; 1,111 enrolments have no IMD band; one IMD band is spelled
`10-20` instead of `10-20%`; 93 withdrawn enrolments have no unregistration day and 9 unregistered
ones are not `Withdrawn`; 56 non-exam assessments carry 0% weight; demographics were generalised
for k-anonymity (k = 5), so bands are coarse; the OU's own download link now returns 404.

## Data model

| Layer | Tables (grain) |
|---|---|
| Raw | 7 CSV files per content-addressed version, `_manifest.json`, `CURRENT` |
| Silver (Iceberg) | `courses` (presentation), `assessments` (assessment), `vle_sites` (material), `students`, `registrations` (enrolment), `student_assessments` (result), `student_vle` (daily clicks; 10.66M), `student_weekly_activity` (enrolment × week × activity type; 2.52M), `student_weekly_engagement` (enrolment × week; 627k), `ops_load_audit`, `ops_dq_results` |
| Staging / intermediate (dbt) | `stg_oulad__*` views; `int_enrolments`, `int_assessment_submissions`, `int_enrolment_activity` |
| Marts (dbt) | `dim_module_presentation`, `mart_engagement_weekly_cohorts`, `mart_assessment_mastery_funnel`, `fct_first_submission`, `mart_time_to_first_submission`, `mart_dropout_risk_features`, `mart_vle_activity_effectiveness`, `mart_outcome_fairness_slices` |
| ML (DuckDB `ml`) | `risk_model_metrics`, `risk_model_slices`, `risk_model_per_module`, `risk_model_coefficients` |

Columns and definitions (active week, pass mark, "mastered", cohorts, leakage guards) are in the
**[data dictionary](docs/data_dictionary.md)**.

## What the data shows (full release, local run of 9 October 2026)

* **Engagement separates outcomes from week 0.** 51.5% of students who later withdraw click in the
  VLE in the first course week, against 86.5% of those who pass and 89.8% with distinction.
* **Mastery funnel.** On the first graded assessment of each presentation, 30,059 enrolled →
  22,640 submitted (75.3%) → 21,786 passed → 15,293 scored 70 or more.
* **Time to first submission.** 54.9% of students who withdraw never submit anything; among those
  who pass, 0.1%.
* **Outcome gaps.** Pass rate is 35.2% in the most deprived IMD decile and 57.5% in the least
  deprived; 38.1% for students declaring a disability against 48.2% for those who do not. These
  are descriptive gaps, confounded with module choice and study load, not causal estimates.
* **Model fairness.** On the held-out presentations the model's AUC is similar across disability
  groups (0.661 vs 0.669), but it under-predicts risk for students declaring a disability (mean
  predicted 21.3% vs an actual 27.4% withdrawal rate).

## Quickstart

### Prerequisites

* Python 3.12 and [uv](https://docs.astral.sh/uv/)
* Java 17 for the Spark steps, on Linux, macOS or WSL2 (native Windows Spark needs Hadoop's
  `winutils.exe`; this project was developed with the Spark steps in WSL2 Ubuntu)
* Internet access to figshare (47 MB archive), Maven Central (47 MB Iceberg jar) and the DuckDB
  extension repository (`iceberg` extension), all on first run only
* About 4 GB of free RAM and 1 GB of disk for the full release

### Run it

```bash
git clone https://github.com/rohit91jacob/edtech-learning-analytics-aws.git
cd edtech-learning-analytics-aws
uv sync --frozen --all-extras

make pipeline-fixtures   # the committed 288-student sample: 2-6 minutes
make pipeline            # the full release: download, Spark, dbt, model, verification, site
open site/index.html
```

A clean full run (archive already downloaded; raw zone, warehouse and marts rebuilt from scratch)
took **11 min 42 s** on a 12-core laptop in WSL2 (Ubuntu, Spark `local[*]`, 4 GB driver, data on the
Linux filesystem); downloading the archive from figshare added about 6 minutes on that network. A rerun on an existing warehouse produces identical
tables. Exit codes: `0` ok, `1` failure, `2` configuration, `3` data-quality gate, `4`
verification mismatch.

```console
$ uv run edtech train
{
  "holdout_presentation": "2014J",
  "train_rows": 18334,
  "test_rows": 9219,
  "train_auc": 0.716,
  "test_auc": 0.669,
  "test_auc_ci95": [0.654, 0.681],
  "baseline_clicks_only_test_auc": 0.591,
  "test_average_precision": 0.323
}
```

(Values rounded here; the command prints full precision.) `make help` lists every target;
`edtech --help` every command.

## Local emulator → real AWS service

| Concern | Local / CI (what actually ran) | Real AWS (Terraform in `infra/`, validated, not deployed) |
|---|---|---|
| Object storage | Filesystem under `EDTECH_DATA_DIR`; moto in unit tests; LocalStack S3 in CI | S3 buckets (raw, lake, code, Athena results, access logs), SSE-KMS, versioning, TLS-only policies |
| Spark compute | PySpark 3.5.8 `local[*]` | EMR Serverless application, `emr-7.14.0`, ARM64, capped at 16 vCPU / 64 GB, auto-stop after 10 idle minutes |
| Table catalog | Iceberg Hadoop catalog on disk | Iceberg `GlueCatalog` + `S3FileIO` (same code, `--catalog glue`) |
| SQL warehouse | DuckDB reading Iceberg with `iceberg_scan` | Athena engine v3 workgroup (enforced config, KMS results, 10 GiB per-query scan cap) |
| dbt | `dbt build --target dev` (DuckDB) | `dbt build --target athena` in CodeBuild; CI compiles this target offline and parses every model as Trino SQL |
| Orchestration | `local_runner.py` executing `pipeline.asl.json` | Step Functions (`emr-serverless:startJobRun.sync`, `codebuild:startBuild.sync`, `sns:publish`), X-Ray, full logging, KMS; CI also creates and runs it on LocalStack (failure path) and moto |
| Scheduling | GitHub Actions `refresh.yml`, weekly | EventBridge Scheduler, weekly, **disabled** by default |
| Alerting | Failure issue opened by `refresh.yml` | SNS topic (KMS) + CloudWatch alarm on `ExecutionsFailed` |
| Cost guardrails | – | AWS Budget on the `project` tag (alerts at 80% actual, 100% forecast), EMR max capacity, Athena scan cap, lifecycle rules |
| CI/CD auth | – | GitHub OIDC role (upload artefacts, land raw data, start the pipeline only); `deploy.yml` is a no-op unless `AWS_DEPLOY_ROLE_ARN` is set |

## Cost notes

Not measured: nothing was deployed. Order-of-magnitude reasoning for one full run in `eu-west-2`:
the Spark work took a few minutes on one laptop, so EMR Serverless should need a few vCPU-hours
at most (EMR Serverless bills per vCPU-second and GB-second, ARM64 cheaper than x86); Athena bills
per TB scanned, and the marts read under 100 MB of Iceberg data per build (81 MB for the whole
local warehouse); S3 holds well under 1 GB. The guardrails are therefore set low: a USD 25 monthly
budget, an EMR capacity ceiling and a 10 GiB per-query Athena cap. Check the current AWS price
pages before deploying.

## Testing and CI

```bash
uv run pytest tests/unit     # 39 tests, no JVM (ingest, moto S3/KMS/Step Functions, ASL, packaging)
uv run pytest tests/spark    # 11 tests (about 13 minutes): Spark + Iceberg + dbt end to end on the fixtures
```

The end-to-end tests run the whole state machine on the fixtures, then check that silver
reconciles with the raw files, every gate passed, the model, verification and site run, a full
**rerun leaves every silver table and mart byte-identical** (content hashes), and that a corrupted
input (an impossible score plus a duplicate result, or an unknown `final_result`) is stopped by the
silver gate with exit 3 before dbt runs.

| Workflow | Trigger | What it does |
|---|---|---|
| [`ci.yml`](.github/workflows/ci.yml) | push, PR | `lint` (lockfile, ruff, Python 3.9 compile of the Spark modules, gitleaks, 300 KB file limit) · `unit` · `pipeline` (Spark + dbt tests, CLI pipeline on fixtures, dbt rebuild, EMR artefacts) · `dbt-athena` (offline compile + Trino parse) · `terraform` (fmt, validate, tflint, checkov) · `localstack` (S3 landing, Step Functions failure path) |
| [`refresh.yml`](.github/workflows/refresh.yml) | Mondays 05:17 UTC, manual | Full pipeline on the real download, site to GitHub Pages; a failing scheduled run opens an issue |
| [`keepalive.yml`](.github/workflows/keepalive.yml) | 1st and 15th | Re-enables the scheduled workflows so GitHub's 60-day rule never disables them |
| [`deploy.yml`](.github/workflows/deploy.yml) | manual | Only if `AWS_DEPLOY_ROLE_ARN` is set: OIDC login, upload artefacts, optionally land data and start the pipeline |

All actions are pinned by commit SHA. **The `localstack`, `pipeline` and Pages jobs need GitHub's
runners and were not run on the author's machine** (no Docker locally); everything they call was
run locally in WSL2, except the LocalStack test file itself.

## Project structure

```
├── src/edtech_analytics/
│   ├── cli.py, config.py, logs.py, oulad.py, pipeline.py, verify.py
│   ├── ingest/          # download + content-addressed landing; S3 mirror
│   ├── spark/           # EMR Serverless jobs (Python 3.9-compatible): session, silver, features, dq, job
│   ├── orchestration/   # pipeline.asl.json (shared with Terraform) + local runner
│   ├── quality/         # gold reconciliation checks
│   ├── transform/       # in-process dbt runner
│   ├── model/           # withdrawal-risk baseline
│   ├── report/          # static results site
│   └── aws/             # EMR artefact packaging
├── dbt/                 # staging / intermediate / marts, seeds, macros, singular tests
├── infra/               # Terraform root + modules (s3_bucket, storage, catalog, emr_serverless,
│                        #   orchestration, guardrails, github_oidc)
├── tests/               # unit/, spark/ (e2e), integration/ (LocalStack), fixtures/oulad/ (real, CC BY 4.0)
├── scripts/             # build_fixtures.py, check_athena_sql.py
├── docs/                # data_dictionary.md, runbook.md, verification.md
└── .github/             # ci, refresh, keepalive, deploy; Dependabot
```

## Limitations

* **Emulated, not deployed.** IAM policies, EMR sizing and Athena behaviour are untested against a
  real account. CI only compiles and parses the Athena SQL; percentile results on Athena would be
  approximate (`approx_percentile`).
* **Python gold checks are DuckDB-only.** On AWS, dbt's tests are the warehouse gate.
* **The model is a baseline.** AUC 0.669 on the held-out presentations; it is weak for some modules
  (GGG 0.512: it flags no GGG students at its threshold) and under-predicts risk for students
  declaring a disability. Do not use it for decisions about individuals.
* **Associations, not effects.** Activity-type "effectiveness" compares users with non-users among
  students who did not withdraw; engaged students use more of everything.
* **Static, historical data** from one UK distance-learning university in 2013–2014. It is not Khan
  Academy data and says nothing about Khan Academy learners.
* **Feature timing.** Scores count from their submission day, although marking happens later; the
  cut-off is rounded down to whole course weeks for clickstream features.

## License

Code: [MIT](LICENSE). Data: OULAD, © The Open University, [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/);
see [DATA_LICENSE.md](DATA_LICENSE.md) for attribution.
