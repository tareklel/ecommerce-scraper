# -------------------------------
# CloudWatch Logs for ECS output
# -------------------------------

# Container stdout/stderr will appear here.
resource "aws_cloudwatch_log_group" "ecs_scraper" {
  name              = "/ecs/${var.ecs_name}"
  retention_in_days = var.ecs_log_retention_days
}
