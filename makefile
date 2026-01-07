# load variables form .env file
include .env
export $(shell sed 's/=.*//' .env)

IMAGE_NAME = ecommerce-scraper
FF_TEST_URL = https://www.farfetch.com/ae/shopping/women/louis-vuitton-pre-owned/clothing-1/items.aspx
OUNASS_TEST_URL=https://www.ounass.ae/api/women/designers/burberry/bags
LEVEL_TEST_URL=https://www.levelshoes.com/women/brands/miu-miu/bags
TF_DIR = infra/terraform

pytest-local:
	poetry run pytest -v

# Build only if image missing
docker-build:
	@if [ -z "$$(docker images -q $(IMAGE_NAME):latest)" ]; then \
		echo "🌟 Image not found — building..."; \
		docker build -t $(IMAGE_NAME):latest .; \
	else \
		echo "✅ Image exists — skipping build."; \
	fi

# Force rebuild
rebuild:
	docker build --no-cache -t $(IMAGE_NAME):latest .

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