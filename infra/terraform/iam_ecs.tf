# --------------------------------------------------------
# IAM for ECS tasks
# - execution role: pulls image + writes logs
# - task role: app permissions (S3 upload)
# --------------------------------------------------------

# ECS Task Execution Role (managed policy includes ECR + CloudWatch Logs).
resource "aws_iam_role" "ecs_task_execution" {
  name = "${var.ecs_name}-execution-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17",
    Statement = [{
      Effect    = "Allow",
      Principal = { Service = "ecs-tasks.amazonaws.com" },
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy_attachment" "ecs_task_execution" {
  role       = aws_iam_role.ecs_task_execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

# ECS Task Role (app permissions only; no infrastructure privileges).
resource "aws_iam_role" "ecs_task" {
  name = "${var.ecs_name}-task-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17",
    Statement = [{
      Effect    = "Allow",
      Principal = { Service = "ecs-tasks.amazonaws.com" },
      Action    = "sts:AssumeRole"
    }]
  })
}

# S3 access for the scraper output (bucket + objects).
resource "aws_iam_role_policy" "ecs_task_s3" {
  name = "${var.ecs_name}-s3-policy"
  role = aws_iam_role.ecs_task.id

  policy = jsonencode({
    Version = "2012-10-17",
    Statement = [
      {
        Effect = "Allow",
        Action = [
          "s3:GetObject",
          "s3:PutObject"
        ],
        Resource = "${aws_s3_bucket.price_comparison_bucket.arn}/*"
      },
      {
        Effect = "Allow",
        Action = [
          "s3:ListBucket"
        ],
        Resource = aws_s3_bucket.price_comparison_bucket.arn
      }
    ]
  })
}
