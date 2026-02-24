# IAM Role for Lambda
resource "aws_iam_role" "bronze_manifest_verifier_role" {
  name = "bronze_manifest_verifier_role"

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
