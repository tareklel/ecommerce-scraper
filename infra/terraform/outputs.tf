# ------------------------------------
# Outputs to wire up manual run/test
# ------------------------------------

# ECR URL used for docker tag/push.
output "ecr_repository_url" {
  value = aws_ecr_repository.scraper.repository_url
}

# ECS cluster and task definition for aws ecs run-task.
output "ecs_cluster_name" {
  value = aws_ecs_cluster.scraper.name
}

output "ecs_task_definition_arn" {
  value = aws_ecs_task_definition.scraper.arn
}

# IAM roles (handy for debugging permissions).
output "ecs_task_execution_role_arn" {
  value = aws_iam_role.ecs_task_execution.arn
}

output "ecs_task_role_arn" {
  value = aws_iam_role.ecs_task.arn
}

# Network info to pass into run-task.
output "ecs_task_security_group_id" {
  value = aws_security_group.ecs_task.id
}

output "default_subnet_ids" {
  value = data.aws_subnets.default.ids
}
