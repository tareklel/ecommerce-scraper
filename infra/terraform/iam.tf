# -------------------------------------------------------
# IAM for image_pipeline_trigger Lambda
# -------------------------------------------------------

resource "aws_iam_role" "image_pipeline_trigger_role" {
  name = "image_pipeline_trigger_role_${var.region}"

  assume_role_policy = jsonencode({
    Version = "2012-10-17",
    Statement = [{
      Effect    = "Allow",
      Principal = { Service = "lambda.amazonaws.com" },
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy" "image_pipeline_trigger_policy" {
  name = "image_pipeline_trigger_policy"
  role = aws_iam_role.image_pipeline_trigger_role.id

  policy = jsonencode({
    Version = "2012-10-17",
    Statement = [
      {
        Effect   = "Allow",
        Action   = ["ecs:RunTask"],
        Resource = aws_ecs_task_definition.image_quality_checker.arn
      },
      {
        # Allow ECS to assume the task role on behalf of RunTask caller.
        Effect   = "Allow",
        Action   = ["iam:PassRole"],
        Resource = [
          aws_iam_role.ecs_task_execution.arn,
          aws_iam_role.ecs_task_image_pipeline.arn,
        ]
      },
      {
        Effect = "Allow",
        Action = ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"],
        Resource = "*"
      }
    ]
  })
}

# -------------------------------------------------------
# IAM Role for bronze_manifest_verifier Lambda
# -------------------------------------------------------

resource "aws_iam_role" "bronze_manifest_verifier_role" {
  name = "bronze_manifest_verifier_role_${var.region}"

  assume_role_policy = jsonencode({
    Version = "2012-10-17",
    Statement = [{
      Effect    = "Allow",
      Principal = { Service = "lambda.amazonaws.com" },
      Action    = "sts:AssumeRole"
    }]
  })
}

# Lambda Permissions (S3 + Logs)
resource "aws_iam_role_policy" "bronze_manifest_verifier_policy" {
  name = "bronze_manifest_verifier_policy"
  role = aws_iam_role.bronze_manifest_verifier_role.id

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
          "s3:GetBucketLocation",
          "s3:ListBucket"
        ],
        Resource = aws_s3_bucket.price_comparison_bucket.arn
      },
      {
        Effect = "Allow",
        Action = [
          "athena:StartQueryExecution",
          "athena:GetQueryExecution"
        ],
        Resource = "*"
      },
      {
        Effect = "Allow",
        Action = [
          "glue:GetDatabase",
          "glue:GetDatabases",
          "glue:GetTable",
          "glue:GetTables",
          "glue:GetPartition",
          "glue:GetPartitions",
          "glue:CreatePartition",
          "glue:BatchCreatePartition"
        ],
        Resource = "*"
      },
      {
        Effect = "Allow",
        Action = [
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:PutLogEvents"
        ],
        Resource = "*"
      }
    ]
  })
}
