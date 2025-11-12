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
  timeout = 30

  filename         = data.archive_file.verifier_zip.output_path
  source_code_hash = data.archive_file.verifier_zip.output_base64sha256
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

  depends_on = [aws_lambda_permission.allow_s3_invoke_verifier]
}