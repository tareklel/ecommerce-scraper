# ------------------------
# ECR: container registry
# ------------------------

# This repository is where we push the Docker image.
# ECS pulls from here when a task is triggered.
resource "aws_ecr_repository" "scraper" {
  name = var.ecr_repository_name

  image_scanning_configuration {
    scan_on_push = true
  }
}

# Keep the registry tidy while we iterate.
# If you want to keep more history, bump countNumber.
resource "aws_ecr_lifecycle_policy" "scraper" {
  repository = aws_ecr_repository.scraper.name

  # ECS runs `:latest`, so the image carrying it must never expire. ECR applies
  # rules by priority, and an image matched by a higher-priority rule can't be
  # expired by a lower one. Rule 1 matches `latest` and keeps 1 image (only one
  # image can hold that tag), which shields it from the sha- cleanup in rule 2
  # even though it also has a sha- tag. Without rule 1, rule 2 would match it:
  # a tag-prefix rule matches an image if ANY of its tags matches. Images with
  # other tags (e.g. schema-v2-dev-20260730) match no rule and are kept.
  policy = jsonencode({
    rules = [
      {
        rulePriority = 1
        description  = "Protect the live image (latest)"
        selection = {
          tagStatus     = "tagged"
          tagPrefixList = ["latest"]
          countType     = "imageCountMoreThan"
          countNumber   = 1
        }
        action = {
          type = "expire"
        }
      },
      {
        rulePriority = 2
        description  = "Keep the last 20 CI builds (sha- tags) for promotion and rollback"
        selection = {
          tagStatus     = "tagged"
          tagPrefixList = ["sha-"]
          countType     = "imageCountMoreThan"
          countNumber   = 20
        }
        action = {
          type = "expire"
        }
      },
      {
        rulePriority = 3
        description  = "Expire untagged images (e.g. a former latest) after 14 days"
        selection = {
          tagStatus   = "untagged"
          countType   = "sinceImagePushed"
          countUnit   = "days"
          countNumber = 14
        }
        action = {
          type = "expire"
        }
      }
    ]
  })
}
