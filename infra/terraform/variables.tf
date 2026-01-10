variable "region" {
  default = "me-central-1"
}

variable "price_comparison_bucket" {
  description = "bucket for main scraper tasks"
  type        = string
  default     = "price-comparison-bucket"
}

# -----------------------------
# Container image + ECS defaults
# -----------------------------

# ECR repository to store the scraper image (e.g., <account>.dkr.ecr.<region>.amazonaws.com/<name>).
variable "ecr_repository_name" {
  description = "ECR repository name for the scraper image"
  type        = string
  default     = "ecommerce-scraper"
}

# Image tag that ECS should run (kept as a variable so we can bump tags without editing TF).
variable "image_tag" {
  description = "Container image tag to run in ECS"
  type        = string
  default     = "latest"
}

# Name prefix for ECS resources (cluster, task definition, IAM roles, log group).
variable "ecs_name" {
  description = "Base name for ECS cluster/task resources"
  type        = string
  default     = "ecommerce-scraper"
}

# Fargate sizing (CPU/memory must be a valid Fargate combo).
variable "ecs_cpu" {
  description = "Fargate task CPU units"
  type        = string
  default     = "512"
}

variable "ecs_memory" {
  description = "Fargate task memory (MiB)"
  type        = string
  default     = "1024"
}

# CloudWatch log retention (keep short while iterating early in the project).
variable "ecs_log_retention_days" {
  description = "CloudWatch log retention in days"
  type        = number
  default     = 7
}

# Default container command; we can override this later per run.
variable "ecs_command" {
  description = "Default container command for the task"
  type        = list(string)
  default = [
    "python3 run_crawler.py ounass --urls https://www.ounass.ae/api/women/designers/burberry/bags && python3 run_crawler.py level --urls https://www.levelshoes.com/women/brands/toteme/bags"
  ]
}

# Override the image ENTRYPOINT so we can chain multiple commands.
variable "ecs_entrypoint" {
  description = "Container entrypoint for ECS (use /bin/sh -c for chained commands)"
  type        = list(string)
  default     = ["/bin/sh", "-c"]
}

# Toggle S3 upload behavior in the pipeline.
variable "s3_upload_enabled" {
  description = "Enable S3 upload in the scraper pipeline"
  type        = string
  default     = "true"
}
