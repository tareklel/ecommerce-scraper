# Terraform owns the secret metadata and IAM wiring only. Secret values are
# written directly to AWS Secrets Manager so they never enter Terraform state.
resource "aws_secretsmanager_secret" "scraper_env" {
  name        = var.scraper_env_secret_name
  description = "JSON environment secret for ecommerce scraper runtime credentials"
}
