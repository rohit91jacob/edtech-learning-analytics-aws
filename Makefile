# Developer entrypoints. `make help` lists targets. Settings come from .env when present.
-include .env
export

UV ?= uv
SITE ?= site
FIXTURES ?= tests/fixtures/oulad

.DEFAULT_GOAL := help
.PHONY: help install lint format test test-unit test-spark ingest silver features dq run dbt dq-gold \
        train verify report pipeline pipeline-fixtures package-emr fixtures tf-fmt tf-validate \
        tf-lint tf-checkov infra-check athena-compile clean

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-18s %s\n", $$1, $$2}'

install: ## Create the virtualenv (dev tools + Athena adapter)
	$(UV) sync --frozen --all-extras

lint: ## Ruff lint + format check
	$(UV) run ruff check .
	$(UV) run ruff format --check .

format: ## Auto-fix lint and format
	$(UV) run ruff check --fix .
	$(UV) run ruff format .

test-unit: ## Fast tests (no JVM): ingest, S3 (moto), ASL, packaging, model helpers
	$(UV) run pytest tests/unit

test-spark: ## Spark + dbt end-to-end on the fixtures, incl. rerun idempotency (needs Java 17)
	$(UV) run pytest tests/spark

test: ## All tests with coverage
	$(UV) run pytest --cov

ingest: ## Download OULAD (figshare, md5-checked) and land it in raw/
	$(UV) run edtech ingest

silver: ## Spark: raw CSV -> silver Iceberg tables
	$(UV) run edtech spark silver

features: ## Spark: clickstream -> weekly activity tables
	$(UV) run edtech spark features

dq: ## Spark DQ gates for silver and features
	$(UV) run edtech spark dq --layer silver
	$(UV) run edtech spark dq --layer features

dbt: ## dbt build (models + tests) on DuckDB
	$(UV) run edtech dbt build

dq-gold: ## Gold reconciliation checks
	$(UV) run edtech dq-gold

run: ## Execute the Step Functions definition locally (Spark + DQ + dbt + gold DQ)
	$(UV) run edtech run

train: ## Train and evaluate the withdrawal-risk baseline (held-out 2014J)
	$(UV) run edtech train

verify: ## Reconcile against the OULAD paper's published figures
	$(UV) run edtech verify

report: ## Write the static results site to ./site (open site/index.html)
	$(UV) run edtech report --out $(SITE)

pipeline: ## Everything on the real download: ingest -> run -> train -> verify -> report
	$(UV) run edtech pipeline --report $(SITE)

pipeline-fixtures: ## Everything on the committed fixtures (EDTECH_DATA_DIR=data/fixtures)
	EDTECH_DATA_DIR=data/fixtures $(UV) run edtech pipeline --archive $(FIXTURES) --report $(SITE)

package-emr: ## Build dist/emr/job.py + edtech_spark.zip for EMR Serverless
	$(UV) run edtech package-emr --out dist/emr

fixtures: ## Rebuild the test fixtures from a downloaded archive (ARCHIVE=path/to/zip)
	$(UV) run python scripts/build_fixtures.py $(ARCHIVE)

# Every AWS endpoint points at a closed local port, so the compile can never reach AWS.
ATHENA_OFFLINE = AWS_ACCESS_KEY_ID=offline AWS_SECRET_ACCESS_KEY=offline AWS_EC2_METADATA_DISABLED=true 	AWS_ENDPOINT_URL=http://127.0.0.1:9 AWS_MAX_ATTEMPTS=1 EDTECH_SILVER_SCHEMA=edtech_dev_silver

athena-compile: ## Compile the dbt project for the Athena target (offline, no AWS calls)
	cd dbt && $(ATHENA_OFFLINE) $(UV) run dbt compile --profiles-dir . --target athena --no-populate-cache
	$(UV) run python scripts/check_athena_sql.py dbt/target/compiled

tf-fmt: ## terraform fmt -check
	terraform -chdir=infra fmt -check -recursive

tf-validate: ## terraform init -backend=false + validate
	terraform -chdir=infra init -backend=false -input=false
	terraform -chdir=infra validate

tf-lint: ## tflint (all modules)
	cd infra && tflint --init && tflint --recursive --config "$$(pwd)/.tflint.hcl"

tf-checkov: ## checkov static analysis of the Terraform
	uvx --from checkov checkov -d infra --framework terraform --quiet --compact

infra-check: tf-fmt tf-validate tf-lint tf-checkov ## All Terraform checks

clean: ## Remove local caches (not data)
	rm -rf .pytest_cache .ruff_cache .coverage coverage.xml htmlcov dist dbt/target dbt/logs
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
