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
      command   = var.ecs_command
      environment = [
        { name = "S3_BUCKET", value = var.price_comparison_bucket },
        { name = "S3_UPLOAD_ENABLED", value = var.s3_upload_enabled }
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
