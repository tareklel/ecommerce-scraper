# Package Lambda Code

data "archive_file" "verifier_zip" {
  type       = "zip"
  source_dir = "${path.root}/../../lambda/bronze_manifest_verifier"
  # Write into .terraform under the working directory, safely ignored
  output_path = "${path.module}/.terraform/tmp/bronze_manifest_verifier.zip"
}


# Lambda Function

resource "aws_lambda_function" "bronze_manifest_verifier" {
  function_name = "bronze_manifest_verifier"

  role    = aws_iam_role.bronze_manifest_verifier_role.arn
  handler = "handler.handler"
  runtime = "python3.11"
  timeout = 60

  filename         = data.archive_file.verifier_zip.output_path
  source_code_hash = data.archive_file.verifier_zip.output_base64sha256

  environment {
    variables = {
      APP_ENV          = var.app_env
      ATHENA_TABLE     = var.athena_table
      BRONZE_DATABASE  = var.bronze_database_name
    }
  }
}


# Allow S3 to Invoke Lambda

resource "aws_lambda_permission" "allow_s3_invoke_verifier" {
  statement_id  = "AllowS3Invoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.bronze_manifest_verifier.function_name
  principal     = "s3.amazonaws.com"
  source_arn    = aws_s3_bucket.price_comparison_bucket.arn
}


# S3 Lambda Notification (Filtered)

resource "aws_s3_bucket_notification" "bronze_notifications" {
  bucket = aws_s3_bucket.price_comparison_bucket.id

  lambda_function {
    lambda_function_arn = aws_lambda_function.bronze_manifest_verifier.arn
    events              = ["s3:ObjectCreated:*"]

    # Only trigger when manifest.json is uploaded under bronze/
    filter_prefix = "bronze/"
    filter_suffix = "manifest.json"
  }

  lambda_function {
    lambda_function_arn = aws_lambda_function.bronze_manifest_verifier.arn
    events              = ["s3:ObjectCreated:*"]

    # Trigger when manifest verification writes the success marker.
    filter_prefix = "bronze/${var.app_env}/crawls/metadata/"
    filter_suffix = "_SUCCESS"
  }

  lambda_function {
    lambda_function_arn = aws_lambda_function.image_pipeline_trigger.arn
    events              = ["s3:ObjectCreated:*"]

    # Trigger quality checker when image pipeline writes _SUCCESS marker.
    filter_prefix = "bronze/${var.app_env}/images/download_log/meta/"
    filter_suffix = "_SUCCESS"
  }

  depends_on = [
    aws_lambda_permission.allow_s3_invoke_verifier,
    aws_lambda_permission.allow_s3_invoke_image_trigger,
  ]
}


# -------------------------------------------------------
# image_pipeline_trigger Lambda
# -------------------------------------------------------

data "archive_file" "image_pipeline_trigger_zip" {
  type        = "zip"
  source_dir  = "${path.root}/../../lambda/image_pipeline_trigger"
  output_path = "${path.module}/.terraform/tmp/image_pipeline_trigger.zip"
}

resource "aws_lambda_function" "image_pipeline_trigger" {
  function_name = "image_pipeline_trigger"

  role    = aws_iam_role.image_pipeline_trigger_role.arn
  handler = "handler.handler"
  runtime = "python3.11"
  timeout = 30

  filename         = data.archive_file.image_pipeline_trigger_zip.output_path
  source_code_hash = data.archive_file.image_pipeline_trigger_zip.output_base64sha256

  environment {
    variables = {
      ECS_CLUSTER           = aws_ecs_cluster.scraper.name
      ECS_TASK_DEFINITION   = aws_ecs_task_definition.image_quality_checker.family
      ECS_CONTAINER_NAME    = "image-quality-checker"
      ECS_SUBNET_IDS        = join(",", data.aws_subnets.default.ids)
      ECS_SECURITY_GROUP_ID = aws_security_group.ecs_task.id
      APP_ENV               = var.app_env
    }
  }
}

resource "aws_lambda_permission" "allow_s3_invoke_image_trigger" {
  statement_id  = "AllowS3InvokeImageTrigger"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.image_pipeline_trigger.function_name
  principal     = "s3.amazonaws.com"
  source_arn    = aws_s3_bucket.price_comparison_bucket.arn
}
