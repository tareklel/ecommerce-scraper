variable "region" {
  default = "eu-central-1"
}

variable "price_comparison_bucket" {
  description = "bucket for main scraper tasks"
  type        = string
  default     = "price-comparison-bucket-eu-central-1"
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
variable "github_repository" {
  description = "GitHub owner/repo whose main branch and production environment may assume the crawler-image CI role"
  type        = string
  default     = "tareklel/ecommerce-scraper"
}

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
    "echo 'Set ECS_RUN_COMMAND override for this task'"
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

# On/off switch for Cettire product pages (CETTIRE_FETCH_PRODUCT_PAGES in the
# crawler task). Off: listings still run and every product is written from
# Cettire's search data; known products keep their stored gallery; no Zyte
# requests for Cettire. Off since 2026-11-23 (user decision): Zyte has been
# refused on every Cettire page since the 11-20 run. Switch back with "true"
# and a targeted apply of aws_ecs_task_definition.scraper and
# aws_sfn_state_machine.crawl_flow (the flow pins the task revision).
variable "cettire_fetch_product_pages" {
  description = "Fetch Cettire product pages through Zyte (\"true\"/\"false\")"
  type        = string
  default     = "false"

  validation {
    condition     = contains(["true", "false"], var.cettire_fetch_product_pages)
    error_message = "cettire_fetch_product_pages must be \"true\" or \"false\"."
  }
}

variable "scraper_env_secret_name" {
  description = "Secrets Manager JSON secret that stores crawler runtime secrets"
  type        = string
  default     = "ecommerce-scraper/env"
}

variable "ecs_secret_env_keys" {
  description = "JSON keys from scraper_env_secret_name to expose as ECS container environment variables"
  type        = list(string)
  default = [
    "ZYTE_API_KEY"
  ]
}

variable "athena_table" {
  description = "Optional Athena table override for bronze partitions (defaults to bronze_<site>_raw)"
  type        = string
  default     = ""
}

variable "athena_workgroup_name" {
  description = "Athena workgroup name (matches scraper-pipeline Terraform)"
  type        = string
  default     = "price-comparison"
}

variable "athena_data_catalog" {
  description = "Athena data catalog used by the bronze manifest verifier lambda"
  type        = string
  default     = "AwsDataCatalog"
}

variable "athena_results_prefix" {
  description = "Prefix inside the data bucket for Athena query results (matches scraper-pipeline Terraform)"
  type        = string
  default     = "athena-results/"
}

variable "app_env" {
  description = "Deployment environment: dev or prod. Drives S3 prefixes, database names, and Lambda env vars."
  type        = string
  default     = "dev"
  validation {
    condition     = contains(["dev", "prod"], var.app_env)
    error_message = "app_env must be dev or prod."
  }
}

variable "glue_database_name" {
  description = "Glue Data Catalog database name used by dbt (matches scraper-pipeline Terraform)"
  type        = string
  default     = "price_comparison_dev"
}

variable "bronze_database_name" {
  description = "Glue database for bronze tables (crawl raw, image log, image validated)"
  type        = string
  default     = "price_comparison_dev"
}

variable "dbt_database_name" {
  description = "Glue database for dbt output tables (silver, gold)"
  type        = string
  default     = "price_comparison_dev"
}

variable "crawl_alert_email" {
  description = "Address that gets the crawl flow's summary email after every run. Set it in the gitignored infra/terraform/local.auto.tfvars, never in a tracked file; empty = no subscription."
  type        = string
  default     = ""
  sensitive   = true
}

variable "crawl_schedule_expression" {
  description = "When the crawl flow runs (EventBridge Scheduler). Daily for the first 7 days, then about weekly (tickets/cicd_pipeline.md step 6)."
  type        = string
  default     = "cron(0 2 * * ? *)"
}

variable "crawl_schedule_timezone" {
  description = "Time zone of crawl_schedule_expression."
  type        = string
  default     = "Asia/Dubai"
}

variable "crawl_schedule_end_date" {
  description = "UTC time after which the schedule stops starting runs (RFC 3339), so a daily schedule can't run on unwatched. Empty = no end."
  type        = string
  default     = "2026-11-23T20:00:00Z" # midnight Dubai after the 10th daily run: the 7-day trial (2026-11-14 to 2026-11-20) extended by 3 runs (user, 2026-11-20)
}
