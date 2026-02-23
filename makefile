# load variables form .env file
include .env
export $(shell sed 's/=.*//' .env)

IMAGE_NAME = ecommerce-scraper
# Use this for ECR tagging/pushing; keep in sync with Terraform image_tag when needed.
IMAGE_TAG ?= latest
# Region should match infra/terraform/variables.tf (var.region).
AWS_REGION ?= me-central-1

# Optional: override ECS command at runtime (used by ecs-run).
ECS_RUN_COMMAND ?=
# Saved test command (previous Terraform default) for quick reuse.
ECS_TEST_COMMAND = python3 run_crawler.py ounass --urls https://www.ounass.ae/api/women/designers/burberry/bags && python3 run_crawler.py level --urls https://www.levelshoes.com/women/brands/toteme/bags
# Script that renders ECS --overrides JSON from ECS_RUN_COMMAND.
ECS_OVERRIDES_SCRIPT = scripts/ecs_overrides.py

FF_TEST_URL = https://www.farfetch.com/ae/shopping/women/louis-vuitton-pre-owned/clothing-1/items.aspx
OUNASS_TEST_URL=https://www.ounass.ae/api/women/designers/burberry/bags
LEVEL_TEST_URL ?= https://www.levelshoes.com/women/brands/miu-miu/bags
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

# Force rebuild
docker-rebuild:
	echo "🏗️ Rebuilding linux/amd64 image (no cache)..."; \
	docker buildx build --platform linux/amd64 --no-cache -t $(IMAGE_NAME):latest .

# farfetch 
run-ff-local:
	poetry run python3 run_crawler.py farfetch --urls $(FF_TEST_URL)

run-ff-test-upload:
	AWS_PROFILE=$(AWS_PROFILE) \
	S3_BUCKET=$(S3_BUCKET) \
	S3_UPLOAD_ENABLED=true \
	poetry run python3 run_crawler.py farfetch --urls $(FF_TEST_URL)

docker-run-ff-dev:
	docker run --rm -v $(PWD)/output:/app/output $(IMAGE_NAME):latest run_crawler.py farfetch --urls $(FF_TEST_URL) --env dev

# ounass
run-ounass-local:
	poetry run python3 run_crawler.py ounass --urls $(OUNASS_TEST_URL)

run-ounass-test-upload:
	AWS_PROFILE=$(AWS_PROFILE) \
	S3_BUCKET=$(S3_BUCKET) \
	S3_UPLOAD_ENABLED=true \
	poetry run python3 run_crawler.py ounass --urls $(OUNASS_TEST_URL)

# level
run-level-local:
	poetry run python3 run_crawler.py level --urls $(LEVEL_TEST_URL)

run-level-test-upload:
	AWS_PROFILE=$(AWS_PROFILE) \
	S3_BUCKET=$(S3_BUCKET) \
	S3_UPLOAD_ENABLED=true \
	poetry run python3 run_crawler.py level --urls $(LEVEL_TEST_URL)


# terraform
tf-init:
	cd $(TF_DIR) && terraform init

tf-plan:
	cd $(TF_DIR) && terraform plan

tf-apply:
	cd $(TF_DIR) && terraform apply -auto-approve

tf-destroy:
	cd $(TF_DIR) && terraform destroy -auto-approve


aws-login:
	aws sso login --profile $(AWS_PROFILE) --region $(AWS_REGION)
# -----------------------------
# ECR image push (manual start)
# -----------------------------

# Log Docker into ECR (uses Terraform output for the registry URL).
ecr-login:
	@ECR_URL=$$(cd $(TF_DIR) && terraform output -raw ecr_repository_url); \
	REGISTRY=$$(echo $$ECR_URL | cut -d/ -f1); \
	AWS_PROFILE=$(AWS_PROFILE) aws ecr get-login-password --region $(AWS_REGION) \
		| docker login --username AWS --password-stdin $$REGISTRY

# Tag + push the local image into ECR (does not run the task).
ecr-push: docker-build ecr-login
	@ECR_URL=$$(cd $(TF_DIR) && terraform output -raw ecr_repository_url); \
	docker tag $(IMAGE_NAME):latest $$ECR_URL:$(IMAGE_TAG); \
	docker push $$ECR_URL:$(IMAGE_TAG)

# --------------------------------
# ECS run (manual test invocation)
# --------------------------------

# Run one Fargate task using outputs from Terraform.
ecs-run:
	@CLUSTER=$$(cd $(TF_DIR) && terraform output -raw ecs_cluster_name); \
	TASK_DEF=$$(cd $(TF_DIR) && terraform output -raw ecs_task_definition_arn); \
	SUBNETS=$$(cd $(TF_DIR) && terraform output -json default_subnet_ids | python3 -c 'import json,sys; print(",".join(json.load(sys.stdin)))'); \
	SG=$$(cd $(TF_DIR) && terraform output -raw ecs_task_security_group_id); \
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
