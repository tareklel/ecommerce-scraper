IMAGE_NAME = ecommerce-scraper
FF_TEST_URL = https://www.farfetch.com/ae/shopping/women/louis-vuitton-pre-owned/clothing-1/items.aspx

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

run-ff-local:
	poetry run python3 run_crawler.py farfetch $(FF_TEST_URL)

pytest-local:
	poetry run pytest -v

docker-run-ff-dev:
	docker run --rm -v $(PWD)/output:/app/output $(IMAGE_NAME):latest run_crawler.py farfetch $(FF_TEST_URL) --env dev