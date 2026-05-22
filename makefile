SHELL := /bin/bash

# Load local, non-secret Make config from .env. Runtime secrets are fetched from
# AWS Secrets Manager below so .env can stay out of Docker images and git.
ifneq (,$(wildcard .env))
include .env
export $(shell sed -n 's/^\([A-Za-z_][A-Za-z0-9_]*\)=.*/\1/p' .env)
endif

# Environment: dev (default) or prod.
# All S3 paths, database names, and Terraform vars are driven by this.
# Override for prod operations: APP_ENV=prod make <target>
APP_ENV ?= dev

IMAGE_NAME = ecommerce-scraper
# Use this for ECR tagging/pushing; keep in sync with Terraform image_tag when needed.
IMAGE_TAG ?= latest
# Region should match infra/terraform/variables.tf (var.region).
AWS_REGION ?= eu-central-1
# One JSON Secrets Manager secret is the source of truth for crawler secrets.
AWS_SECRET_ENV_NAME ?= ecommerce-scraper/env
AWS_SECRET_EXPORTS_SCRIPT = scripts/secret_json_to_exports.py
# Recipes that execute crawler code locally call this first so users do not need
# a separate "with secrets" command. ECS receives the same values via Terraform.
LOAD_AWS_SECRET_ENV = set -o pipefail; eval "$$(AWS_PROFILE=$(AWS_PROFILE) aws secretsmanager get-secret-value --region $(AWS_REGION) --secret-id $(AWS_SECRET_ENV_NAME) --query SecretString --output text | python3 $(AWS_SECRET_EXPORTS_SCRIPT))"
DOCKER_SECRET_ENV_FLAGS = --env ZYTE_API_KEY --env ZYTE_API_ENABLED --env CRAWLER_API_ZYTE_GEOLOCATION --env OXY_LABS_USERNAME --env OXY_LABS_PASSWORD --env OXY_PROXY --env OXY_COUNTRY

# Optional: override ECS command at runtime (used by ecs-run).
ECS_RUN_COMMAND ?=
# Saved test command (previous Terraform default) for quick reuse.
ECS_TEST_COMMAND = python3 run_crawler.py ounass --urls https://www.ounass.ae/api/women/designers/burberry/bags && python3 run_crawler.py level --urls https://www.levelshoes.com/women/brands/toteme/bags
# Script that renders ECS --overrides JSON from ECS_RUN_COMMAND.
ECS_OVERRIDES_SCRIPT = scripts/ecs_overrides.py

FF_TEST_URL = https://www.farfetch.com/ae/shopping/women/louis-vuitton-pre-owned/clothing-1/items.aspx
OUNASS_TEST_URL ?= https://saudi.ounass.com/api/women/designers/ami/bags
LEVEL_TEST_URL ?= https://www.levelshoes.com/women/brands/miu-miu/bags
IMAGE_DOWNLOADER_INPUT_JSONL ?= resources/image_download_test_jobs.jsonl
IMAGE_DOWNLOADER_OUTPUT_DIR ?= output/images
IMAGE_DOWNLOADER_MAX_WORKERS ?= 10
IMAGE_DOWNLOADER_TIMEOUT_SECONDS ?= 20
BACKFILL_INPUT_GZ ?=
BACKFILL_JOBS_OUTPUT_JSONL ?= output/backfill/image_jobs.jsonl
BACKFILL_SITE_OVERRIDE ?=
BACKFILL_NO_DEDUPE ?= false
BACKFILL_IMAGE_OUTPUT_DIR ?= output/images_backfill
BACKFILL_MAX_WORKERS ?= 10
BACKFILL_TIMEOUT_SECONDS ?= 20
QUALITY_GATE_INPUT_JSONL ?= output/2026/02/26/2026-02-26T13-51-38-133/metadata/sample_ounass.jsonl
QUALITY_GATE_BLANK_THRESHOLD ?= 0.8
QUALITY_GATE_MIN_ROWS_FOR_BLANK_CHECK ?= 20
QUALITY_GATE_EXCEPTIONS_FILE ?= resources/quality_gate_exclusions.json
QUALITY_GATE_EXTRA_ARGS ?=
TF_DIR = infra/terraform

pytest-local:
	poetry run pytest -v

# Build only if image missing
docker-build:
	@if [ -z "$$(docker images -q $(IMAGE_NAME):latest)" ]; then \
		echo "🌟 Image not found — building..."; \
		echo "🏗️ Building linux/amd64 image..."; \
		docker buildx build --platform linux/amd64 -t $(IMAGE_NAME):latest .; \
	else \
		echo "✅ Image exists — skipping build."; \
	fi

# Remove unused Docker resources before expensive rebuilds to avoid local disk exhaustion.
docker-prune:
	echo "🧹 Pruning unused Docker images, containers, networks, and build cache..."; \
	docker system prune -af; \
	docker builder prune -af

# Force rebuild
docker-rebuild: docker-prune
	echo "🏗️ Rebuilding linux/amd64 image (no cache)..."; \
	docker buildx build --platform linux/amd64 --no-cache -t $(IMAGE_NAME):latest .

# farfetch
run-ff-local:
	$(LOAD_AWS_SECRET_ENV); \
	poetry run python3 run_crawler.py farfetch --urls $(FF_TEST_URL)

run-ff-test-upload:
	$(LOAD_AWS_SECRET_ENV); \
	APP_ENV=$(APP_ENV) \
	AWS_PROFILE=$(AWS_PROFILE) \
	S3_BUCKET=$(S3_BUCKET) \
	S3_UPLOAD_ENABLED=true \
	poetry run python3 run_crawler.py farfetch --urls $(FF_TEST_URL)

docker-run-ff:
	$(LOAD_AWS_SECRET_ENV); \
	docker run --rm $(DOCKER_SECRET_ENV_FLAGS) -v $(PWD)/output:/app/output $(IMAGE_NAME):latest run_crawler.py farfetch --urls $(FF_TEST_URL) --env $(APP_ENV)

# ounass
run-ounass-local:
	$(LOAD_AWS_SECRET_ENV); \
	poetry run python3 run_crawler.py ounass --urls $(OUNASS_TEST_URL)

run-ounass-test-upload:
	$(LOAD_AWS_SECRET_ENV); \
	APP_ENV=$(APP_ENV) \
	AWS_PROFILE=$(AWS_PROFILE) \
	S3_BUCKET=$(S3_BUCKET) \
	S3_UPLOAD_ENABLED=true \
	poetry run python3 run_crawler.py ounass --urls $(OUNASS_TEST_URL)

# Intentional fail_quality smoke test — forces quality gate failure to verify Lambda emits _FAIL_QUALITY.
run-ounass-test-upload-faulty-quality:
	$(LOAD_AWS_SECRET_ENV); \
	APP_ENV=$(APP_ENV) \
	AWS_PROFILE=$(AWS_PROFILE) \
	S3_BUCKET=$(S3_BUCKET) \
	S3_UPLOAD_ENABLED=true \
	QUALITY_GATE_ENABLED=true \
	QUALITY_GATE_MIN_ROWS_FOR_BLANK_CHECK=1 \
	QUALITY_GATE_BLANK_THRESHOLD=0 \
	QUALITY_GATE_EXCEPTIONS_FILE= \
	poetry run python3 run_crawler.py ounass --urls $(OUNASS_TEST_URL)

# level
run-level-local:
	$(LOAD_AWS_SECRET_ENV); \
	poetry run python3 run_crawler.py level --urls $(LEVEL_TEST_URL)

run-level-test-upload:
	$(LOAD_AWS_SECRET_ENV); \
	APP_ENV=$(APP_ENV) \
	AWS_PROFILE=$(AWS_PROFILE) \
	S3_BUCKET=$(S3_BUCKET) \
	S3_UPLOAD_ENABLED=true \
	poetry run python3 run_crawler.py level --urls $(LEVEL_TEST_URL)

# Run any local command with .env plus AWS Secrets Manager values loaded.
# Usage:
#   make run-with-env COMMAND="poetry run python3 run_crawler.py level --env dev --urls-source s3://..."
run-with-env:
	@test -n "$(COMMAND)" || (echo 'Set COMMAND="your command".' && exit 1)
	$(LOAD_AWS_SECRET_ENV); \
	APP_ENV=$(APP_ENV) \
	$(COMMAND)

# image downloader
run-image-downloader-local:
	poetry run python3 run_image_downloader.py \
		--input-jsonl $(IMAGE_DOWNLOADER_INPUT_JSONL) \
		--output-dir $(IMAGE_DOWNLOADER_OUTPUT_DIR) \
		--max-workers $(IMAGE_DOWNLOADER_MAX_WORKERS) \
		--timeout-seconds $(IMAGE_DOWNLOADER_TIMEOUT_SECONDS)

# backfill from crawler jsonl.gz -> jobs -> downloaded images
build-image-backfill-jobs:
	@test -n "$(BACKFILL_INPUT_GZ)" || (echo "Set BACKFILL_INPUT_GZ=/path/to/file.jsonl.gz" && exit 1)
	poetry run python3 scripts/backfill/build_image_jobs_from_gz.py \
		--input-gz "$(BACKFILL_INPUT_GZ)" \
		--output-jsonl "$(BACKFILL_JOBS_OUTPUT_JSONL)" \
		$(if $(BACKFILL_SITE_OVERRIDE),--site-override "$(BACKFILL_SITE_OVERRIDE)",) \
		$(if $(filter true,$(BACKFILL_NO_DEDUPE)),--no-dedupe,)

run-image-backfill-from-jobs-local:
	poetry run python3 run_image_downloader.py \
		--input-jsonl "$(BACKFILL_JOBS_OUTPUT_JSONL)" \
		--output-dir "$(BACKFILL_IMAGE_OUTPUT_DIR)" \
		--max-workers $(BACKFILL_MAX_WORKERS) \
		--timeout-seconds $(BACKFILL_TIMEOUT_SECONDS)

run-image-backfill-local: build-image-backfill-jobs run-image-backfill-from-jobs-local

# quality gate
run-quality-gate-local:
	poetry run python3 run_quality_gate.py \
		--input-jsonl $(QUALITY_GATE_INPUT_JSONL) \
		--blank-threshold $(QUALITY_GATE_BLANK_THRESHOLD) \
		--min-rows-for-blank-check $(QUALITY_GATE_MIN_ROWS_FOR_BLANK_CHECK) \
		$(if $(QUALITY_GATE_EXCEPTIONS_FILE),--blank-field-exceptions-file $(QUALITY_GATE_EXCEPTIONS_FILE),) \
		$(QUALITY_GATE_EXTRA_ARGS)


# terraform — TF_VAR_app_env ensures var.app_env matches APP_ENV without needing a tfvars file.
tf-init:
	cd $(TF_DIR) && terraform init

tf-plan:
	cd $(TF_DIR) && TF_VAR_app_env=$(APP_ENV) terraform plan

tf-apply:
	cd $(TF_DIR) && TF_VAR_app_env=$(APP_ENV) terraform apply -auto-approve

tf-destroy:
	cd $(TF_DIR) && TF_VAR_app_env=$(APP_ENV) terraform destroy -auto-approve


aws-login:
	aws sso login --profile $(AWS_PROFILE) --region $(AWS_REGION)

# Update one key in the remote JSON secret without putting the value in .env or
# Terraform state. Existing JSON keys are preserved.
# Usage: make secrets-put KEY=ZYTE_API_KEY
secrets-put:
	@test -n "$(KEY)" || (echo "Set KEY, for example: make secrets-put KEY=ZYTE_API_KEY" && exit 1)
	@set -e; \
	read -rsp "$(KEY): " SECRET_VALUE; echo; \
	test -n "$$SECRET_VALUE" || (echo "$(KEY) cannot be empty" && exit 1); \
	EXISTING_SECRET=$$(AWS_PROFILE=$(AWS_PROFILE) aws secretsmanager get-secret-value --region $(AWS_REGION) --secret-id $(AWS_SECRET_ENV_NAME) --query SecretString --output text 2>/dev/null || printf '{}'); \
	SECRET_JSON=$$(EXISTING_SECRET="$$EXISTING_SECRET" SECRET_KEY="$(KEY)" SECRET_VALUE="$$SECRET_VALUE" python3 -c 'import json, os; values = json.loads(os.environ.get("EXISTING_SECRET") or "{}"); values[os.environ["SECRET_KEY"]] = os.environ["SECRET_VALUE"]; print(json.dumps(values, separators=(",", ":")))'); \
	AWS_PROFILE=$(AWS_PROFILE) aws secretsmanager put-secret-value --region $(AWS_REGION) --secret-id $(AWS_SECRET_ENV_NAME) --secret-string "$$SECRET_JSON" >/dev/null || (echo "Secret $(AWS_SECRET_ENV_NAME) does not exist yet. Run make tf-apply first, or import the existing AWS secret into Terraform." && exit 1); \
	echo "Updated $(KEY) in $(AWS_SECRET_ENV_NAME)."

# Show which keys exist in the remote JSON secret without printing values.
secrets-list:
	@AWS_PROFILE=$(AWS_PROFILE) aws secretsmanager get-secret-value \
		--region $(AWS_REGION) \
		--secret-id $(AWS_SECRET_ENV_NAME) \
		--query SecretString \
		--output text | python3 -c 'import json,sys; print("\n".join(sorted(json.load(sys.stdin).keys())))'

# -----------------------------
# ECR image push (manual start)
# -----------------------------

# Log Docker into ECR (uses Terraform output for the registry URL).
ecr-login:
	@set -o pipefail; \
	ACCOUNT_ID=$$(AWS_PROFILE=$(AWS_PROFILE) aws sts get-caller-identity --query Account --output text); \
	REGISTRY=$$ACCOUNT_ID.dkr.ecr.$(AWS_REGION).amazonaws.com; \
	AWS_PROFILE=$(AWS_PROFILE) aws ecr get-login-password --region $(AWS_REGION) \
		| docker login --username AWS --password-stdin $$REGISTRY

# Tag + push a freshly rebuilt local image into ECR (does not run the task).
ecr-push: docker-rebuild ecr-login
	 @ECR_URL=$$(cd $(TF_DIR) && AWS_PROFILE=$(AWS_PROFILE) terraform output -raw ecr_repository_url); \
	 docker tag $(IMAGE_NAME):latest $$ECR_URL:$(IMAGE_TAG); \
	 docker push $$ECR_URL:$(IMAGE_TAG)

# --------------------------------
# ECS run (manual test invocation)
# --------------------------------

# Run one Fargate task using outputs from Terraform.
# APP_ENV is baked into the task definition by tf-apply — override with APP_ENV=prod make tf-apply first.
# make ecs-run ECS_RUN_COMMAND="python3 run_crawler.py level --urls-source s3://..."
ecs-run:
	@CLUSTER=$$(cd $(TF_DIR) && AWS_PROFILE=$(AWS_PROFILE) terraform output -raw ecs_cluster_name); \
	TASK_DEF=$$(cd $(TF_DIR) && AWS_PROFILE=$(AWS_PROFILE) terraform output -raw ecs_task_definition_arn); \
	SUBNETS=$$(cd $(TF_DIR) && AWS_PROFILE=$(AWS_PROFILE) terraform output -json default_subnet_ids | python3 -c 'import json,sys; print(",".join(json.load(sys.stdin)))'); \
	SG=$$(cd $(TF_DIR) && AWS_PROFILE=$(AWS_PROFILE) terraform output -raw ecs_task_security_group_id); \
	OVERRIDES=$$(ECS_RUN_COMMAND="$(ECS_RUN_COMMAND)" python3 $(ECS_OVERRIDES_SCRIPT)); \
	if [ -n "$$OVERRIDES" ]; then \
		AWS_PROFILE=$(AWS_PROFILE) aws ecs run-task \
			--region $(AWS_REGION) \
			--cluster $$CLUSTER \
			--task-definition $$TASK_DEF \
			--launch-type FARGATE \
			--network-configuration "awsvpcConfiguration={subnets=[$$SUBNETS],securityGroups=[$$SG],assignPublicIp=ENABLED}" \
			--overrides "$$OVERRIDES"; \
	else \
		AWS_PROFILE=$(AWS_PROFILE) aws ecs run-task \
			--region $(AWS_REGION) \
			--cluster $$CLUSTER \
			--task-definition $$TASK_DEF \
			--launch-type FARGATE \
			--network-configuration "awsvpcConfiguration={subnets=[$$SUBNETS],securityGroups=[$$SG],assignPublicIp=ENABLED}"; \
	fi

# Run the saved test command (ounass -> level) via ECS override.
ecs-run-test: ECS_RUN_COMMAND = $(ECS_TEST_COMMAND)
ecs-run-test: ecs-run

# --------------------------------
# Image pipeline
# --------------------------------

IMAGE_PIPELINE_LIMIT ?=
IMAGE_PIPELINE_LOG_LEVEL ?= INFO

_IMAGE_PIPELINE_CMD = python run_image_pipeline.py \
	--app-env $(APP_ENV) \
	--athena-workgroup price-comparison \
	--athena-output-loc s3://$(S3_BUCKET)/athena-results/ \
	--storage-mode s3 \
	--log-level $(IMAGE_PIPELINE_LOG_LEVEL) \
	$(if $(IMAGE_PIPELINE_LIMIT),--limit $(IMAGE_PIPELINE_LIMIT),)

# Run image pipeline locally.
# make run-image-pipeline-local
# make run-image-pipeline-local IMAGE_PIPELINE_LIMIT=5 APP_ENV=prod
run-image-pipeline-local:
	$(LOAD_AWS_SECRET_ENV); \
	APP_ENV=$(APP_ENV) \
	AWS_PROFILE=$(AWS_PROFILE) \
	S3_BUCKET=$(S3_BUCKET) \
	poetry run $(_IMAGE_PIPELINE_CMD)

# Run image pipeline via ECS.
# make ecs-run-image-pipeline
# make ecs-run-image-pipeline APP_ENV=prod
ecs-run-image-pipeline:
	@CLUSTER=$$(cd $(TF_DIR) && AWS_PROFILE=$(AWS_PROFILE) terraform output -raw ecs_cluster_name); \
	TASK_DEF=$$(cd $(TF_DIR) && AWS_PROFILE=$(AWS_PROFILE) terraform output -raw ecs_image_pipeline_task_definition_arn); \
	SUBNETS=$$(cd $(TF_DIR) && AWS_PROFILE=$(AWS_PROFILE) terraform output -json default_subnet_ids | python3 -c 'import json,sys; print(",".join(json.load(sys.stdin)))'); \
	SG=$$(cd $(TF_DIR) && AWS_PROFILE=$(AWS_PROFILE) terraform output -raw ecs_task_security_group_id); \
	CMD="$(_IMAGE_PIPELINE_CMD)"; \
	AWS_PROFILE=$(AWS_PROFILE) aws ecs run-task \
		--region $(AWS_REGION) \
		--cluster $$CLUSTER \
		--task-definition $$TASK_DEF \
		--launch-type FARGATE \
		--network-configuration "awsvpcConfiguration={subnets=[$$SUBNETS],securityGroups=[$$SG],assignPublicIp=ENABLED}" \
		--overrides "{\"containerOverrides\":[{\"name\":\"image-pipeline\",\"command\":[\"$$CMD\"]}]}"

# Run quality checker locally for a given date partition.
# make run-quality-checker-local DT=2026-05-21 RUN_ID=<run_id>
# make run-quality-checker-local DT=2026-05-21 RUN_ID=<run_id> APP_ENV=prod
run-quality-checker-local:
	$(LOAD_AWS_SECRET_ENV); \
	APP_ENV=$(APP_ENV) \
	AWS_PROFILE=$(AWS_PROFILE) \
	S3_BUCKET=$(S3_BUCKET) \
	poetry run python scripts/image_quality_checker.py \
		--dt $(DT) \
		--run-id $(RUN_ID) \
		--app-env $(APP_ENV) \
		--log-level $(IMAGE_PIPELINE_LOG_LEVEL)
