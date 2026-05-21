# -------------------------------------------------------
# ECS Fargate (on-demand)
# -------------------------------------------------------

# Use the AWS default VPC to keep networking simple.
data "aws_vpc" "default" {
  default = true
}

# Pull all subnets in the default VPC (used when running tasks).
data "aws_subnets" "default" {
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.default.id]
  }
}

# Security group for the task. Egress-only so it can reach the internet.
resource "aws_security_group" "ecs_task" {
  name   = "${var.ecs_name}-task-sg"
  vpc_id = data.aws_vpc.default.id

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

# ECS cluster to host our on-demand tasks.
resource "aws_ecs_cluster" "scraper" {
  name = var.ecs_name
}

# Task definition: the blueprint for each run.
resource "aws_ecs_task_definition" "scraper" {
  family                   = var.ecs_name
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.ecs_cpu
  memory                   = var.ecs_memory
  execution_role_arn       = aws_iam_role.ecs_task_execution.arn
  task_role_arn            = aws_iam_role.ecs_task.arn

  # Container settings (image, command, env, logs).
  container_definitions = jsonencode([
    {
      name      = "scraper"
      image     = "${aws_ecr_repository.scraper.repository_url}:${var.image_tag}"
      essential = true
      # Use a shell entrypoint so we can chain multiple runs in one task.
      entryPoint = var.ecs_entrypoint
      command    = var.ecs_command
      environment = [
        { name = "S3_BUCKET", value = var.price_comparison_bucket },
        { name = "S3_UPLOAD_ENABLED", value = var.s3_upload_enabled }
      ]
      secrets = [
        for key in var.ecs_secret_env_keys : {
          name      = key
          valueFrom = "${aws_secretsmanager_secret.scraper_env.arn}:${key}::"
        }
      ]
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          awslogs-group         = aws_cloudwatch_log_group.ecs_scraper.name
          awslogs-region        = var.region
          awslogs-stream-prefix = "ecs"
        }
      }
    }
  ])
}

# -------------------------------------------------------
# Image pipeline task — run_image_pipeline.py
# -------------------------------------------------------

resource "aws_ecs_task_definition" "image_pipeline" {
  family                   = "${var.ecs_name}-image-pipeline"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.ecs_cpu
  memory                   = var.ecs_memory
  execution_role_arn       = aws_iam_role.ecs_task_execution.arn
  task_role_arn            = aws_iam_role.ecs_task_image_pipeline.arn

  container_definitions = jsonencode([
    {
      name       = "image-pipeline"
      image      = "${aws_ecr_repository.scraper.repository_url}:${var.image_tag}"
      essential  = true
      entryPoint = ["/bin/sh", "-c"]
      command    = ["python run_image_pipeline.py --app-env ${var.app_env} --athena-workgroup ${var.athena_workgroup_name} --athena-output-loc s3://${var.price_comparison_bucket}/${var.athena_results_prefix} --storage-mode s3"]
      environment = [
        { name = "S3_BUCKET", value = var.price_comparison_bucket }
      ]
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          awslogs-group         = aws_cloudwatch_log_group.ecs_scraper.name
          awslogs-region        = var.region
          awslogs-stream-prefix = "image-pipeline"
        }
      }
    }
  ])
}

# -------------------------------------------------------
# Image quality checker task — scripts/image_quality_checker.py
# -------------------------------------------------------

resource "aws_ecs_task_definition" "image_quality_checker" {
  family                   = "${var.ecs_name}-image-quality-checker"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.ecs_cpu
  memory                   = var.ecs_memory
  execution_role_arn       = aws_iam_role.ecs_task_execution.arn
  task_role_arn            = aws_iam_role.ecs_task_image_pipeline.arn

  container_definitions = jsonencode([
    {
      name       = "image-quality-checker"
      image      = "${aws_ecr_repository.scraper.repository_url}:${var.image_tag}"
      essential  = true
      entryPoint = ["/bin/sh", "-c"]
      # dt and run-id are injected at runtime via Lambda → ECS RunTask command override
      # dt and run-id are injected at runtime via Lambda → ECS RunTask command override
      command    = ["python scripts/image_quality_checker.py --app-env ${var.app_env} --dt PLACEHOLDER --run-id PLACEHOLDER"]
      environment = [
        { name = "S3_BUCKET", value = var.price_comparison_bucket }
      ]
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          awslogs-group         = aws_cloudwatch_log_group.ecs_scraper.name
          awslogs-region        = var.region
          awslogs-stream-prefix = "image-quality-checker"
        }
      }
    }
  ])
}
