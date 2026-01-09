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

  policy = jsonencode({
    rules = [
      {
        rulePriority = 1
        description  = "Keep last 10 images"
        selection = {
          tagStatus   = "any"
          countType   = "imageCountMoreThan"
          countNumber = 10
        }
        action = {
          type = "expire"
        }
      }
    ]
  })
}
