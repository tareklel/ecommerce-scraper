# -------------------------------------------------------
# Crawl flow (dev): Step Functions state machine plus its helper Lambda.
#
# Order: start check → registry seed + tests → crawl list from the registry →
# crawls in parallel (each waits for verification) → dbt run (full) → image
# pipeline → quality checker → dbt run (image models) → dbt test → cache
# refresh → summary → email (SNS).
# {"start_at": "images"} skips straight to the image pipeline.
#
# Design, decisions and edge cases: tickets/cicd_pipeline.md (step 3) and
# docs/cicd_architecture.md ("What happens on each run", "Edge cases").
# No schedule yet (step 6). Dev only: the dbt task and every command use dev.
# -------------------------------------------------------

data "aws_caller_identity" "current" {}

locals {
  crawl_flow_name = "${var.ecs_name}-crawl-flow-dev"
  # Built from the name, not the resource, so the helper's policy can name the
  # state machine without a dependency cycle.
  crawl_flow_arn = "arn:aws:states:${var.region}:${data.aws_caller_identity.current.account_id}:stateMachine:${local.crawl_flow_name}"

  # The dbt task and its roles belong to scraper-pipeline's Terraform
  # (terraform/dbt_job.tf); referenced by name.
  dbt_task_family         = "price-comparison-dbt-dev"
  dbt_task_definition_arn = "arn:aws:ecs:${var.region}:${data.aws_caller_identity.current.account_id}:task-definition/${local.dbt_task_family}"

  crawler_network = {
    AwsvpcConfiguration = {
      Subnets        = data.aws_subnets.default.ids
      SecurityGroups = [aws_security_group.ecs_task.id]
      AssignPublicIp = "ENABLED"
    }
  }
  dbt_network = {
    AwsvpcConfiguration = {
      Subnets        = data.aws_subnets.default.ids
      SecurityGroups = [data.aws_security_group.dbt_task.id]
      AssignPublicIp = "ENABLED"
    }
  }

  # dbt commands run through scripts/dbt_job.py in the image (lock, dbt).
  # --no-cache-refresh: the API cache is refreshed only by the refresh_cache
  # step, after dbt test passes, so data failing a test never reaches the API.
  dbt_prefix = ["--target", "dev", "exec", "--no-cache-refresh", "--", "dbt"]
  dbt_flags  = ["--project-dir", "dbt", "--profiles-dir", "dbt", "--target", "dev"]

  lambda_retry = [{
    ErrorEquals = [
      "Lambda.ServiceException",
      "Lambda.AWSLambdaException",
      "Lambda.SdkClientException",
      "Lambda.TooManyRequestsException"
    ]
    IntervalSeconds = 2
    MaxAttempts     = 3
    BackoffRate     = 2
  }]

  # Steps that run one ECS task, wait for it, and stop the flow (through the
  # summary) if it fails or exits non-zero. A missing ExitCode (the container
  # never started) counts as a failure.
  ecs_steps = {
    seed_registry = {
      task_definition = local.dbt_task_definition_arn
      network         = local.dbt_network
      # `build` seeds the registry and runs its tests in one task.
      override = { Name = "dbt", Command = concat(local.dbt_prefix, ["build"], local.dbt_flags, ["--select", "crawl_plp_registry"]) }
      timeout  = 14400 # includes up to 2 hours waiting for the dbt lock
      next     = "ListCrawls"
    }
    dbt_run = {
      task_definition = local.dbt_task_definition_arn
      network         = local.dbt_network
      override        = { Name = "dbt", Command = concat(local.dbt_prefix, ["run"], local.dbt_flags) }
      timeout         = 14400
      next            = "Run_image_pipeline"
    }
    image_pipeline = {
      task_definition = aws_ecs_task_definition.image_pipeline.arn_without_revision
      network         = local.crawler_network
      override = {
        Name        = "image-pipeline"
        "Command.$" = "States.Array(States.Format('python run_image_pipeline.py --app-env dev --athena-workgroup ${var.athena_workgroup_name} --athena-output-loc s3://${var.price_comparison_bucket}/${var.athena_results_prefix} --storage-mode s3 --log-level INFO --run-id {}', $.flow.image_run_id))"
      }
      timeout = 10800
      next    = "FindImageMarker"
    }
    quality_checker = {
      task_definition = aws_ecs_task_definition.image_quality_checker.arn_without_revision
      network         = local.crawler_network
      override = {
        Name        = "image-quality-checker"
        "Command.$" = "States.Array(States.Format('python scripts/image_quality_checker.py --app-env dev --dt {} --run-id {}', $.image_marker.dt, $.image_marker.run_id))"
      }
      timeout = 7200
      next    = "Run_dbt_run_images"
    }
    dbt_run_images = {
      task_definition = local.dbt_task_definition_arn
      network         = local.dbt_network
      override        = { Name = "dbt", Command = concat(local.dbt_prefix, ["run"], local.dbt_flags, ["--select", "silver_product_image_download_status+"]) }
      timeout         = 14400
      next            = "Run_dbt_test"
    }
    dbt_test = {
      task_definition = local.dbt_task_definition_arn
      network         = local.dbt_network
      override        = { Name = "dbt", Command = concat(local.dbt_prefix, ["test"], local.dbt_flags) }
      timeout         = 14400
      next            = "Run_refresh_cache"
    }
    refresh_cache = {
      task_definition = local.dbt_task_definition_arn
      network         = local.dbt_network
      override        = { Name = "dbt", Command = ["--target", "dev", "refresh-cache"] }
      timeout         = 10800 # includes up to 2 hours waiting for the dbt lock
      next            = "Summary"
    }
  }

  ecs_step_states = merge(
    {
      for name, step in local.ecs_steps : "Run_${name}" => {
        Type     = "Task"
        Resource = "arn:aws:states:::ecs:runTask.sync"
        Parameters = {
          Cluster              = aws_ecs_cluster.scraper.arn
          TaskDefinition       = step.task_definition
          LaunchType           = "FARGATE"
          NetworkConfiguration = step.network
          Overrides            = { ContainerOverrides = [step.override] }
        }
        ResultSelector = { "containers.$" = "$.Containers" }
        ResultPath     = "$.last_task"
        TimeoutSeconds = step.timeout
        Catch          = [{ ErrorEquals = ["States.ALL"], ResultPath = "$.failure", Next = "Failed_${name}" }]
        Next           = "Check_${name}"
      }
    },
    {
      for name, step in local.ecs_steps : "Check_${name}" => {
        Type = "Choice"
        Choices = [{
          And = [
            { Variable = "$.last_task.containers[0].ExitCode", IsPresent = true },
            { Variable = "$.last_task.containers[0].ExitCode", NumericEquals = 0 }
          ]
          Next = step.next
        }]
        Default = "Failed_${name}"
      }
    },
    {
      for name in concat(keys(local.ecs_steps), ["list_crawls", "crawls", "image_marker"]) : "Failed_${name}" => {
        Type       = "Pass"
        Result     = name
        ResultPath = "$.failed_step"
        Next       = "Summary"
      }
    }
  )

  helper_invoke = {
    Type     = "Task"
    Resource = "arn:aws:states:::lambda:invoke"
    Retry    = local.lambda_retry
  }

  crawl_branch = {
    StartAt         = "InitCrawl"
    ProcessorConfig = { Mode = "INLINE" }
    States = {
      InitCrawl = {
        Type       = "Pass"
        Parameters = { "crawl.$" = "$.crawl", task_error = {}, polls = 0 }
        Next       = "RunCrawl"
      }
      RunCrawl = {
        Type     = "Task"
        Resource = "arn:aws:states:::ecs:runTask.sync"
        Parameters = {
          Cluster              = aws_ecs_cluster.scraper.arn
          TaskDefinition       = aws_ecs_task_definition.scraper.arn_without_revision
          LaunchType           = "FARGATE"
          NetworkConfiguration = local.crawler_network
          Overrides = {
            ContainerOverrides = [{
              Name        = "scraper"
              "Command.$" = "States.Array($.crawl.command)"
              Environment = [
                { Name = "APP_ENV", Value = "dev" },
                { Name = "CRAWL_RUN_ID", "Value.$" = "$.crawl.run_id" }
              ]
            }]
          }
        }
        ResultSelector = { "containers.$" = "$.Containers" }
        ResultPath     = "$.task"
        TimeoutSeconds = 36000
        # A failed or timed-out crawl doesn't stop the others; its markers
        # (or their absence) decide its status below.
        Catch = [{ ErrorEquals = ["States.ALL"], ResultPath = "$.task_error", Next = "CheckCrawl" }]
        Next  = "CheckCrawl"
      }
      CheckCrawl = merge(local.helper_invoke, {
        Parameters = {
          FunctionName = aws_lambda_function.crawl_flow_helper.arn
          Payload      = { action = "check_crawl", "crawl.$" = "$.crawl", "polls.$" = "$.polls" }
        }
        ResultSelector = { "check.$" = "$.Payload" }
        ResultPath     = "$.verification"
        Next           = "CrawlVerified"
      })
      CrawlVerified = {
        Type    = "Choice"
        Choices = [{ Variable = "$.verification.check.done", BooleanEquals = true, Next = "CrawlDone" }]
        Default = "CountPoll"
      }
      CountPoll = {
        Type       = "Pass"
        InputPath  = "$.verification.check.polls"
        ResultPath = "$.polls"
        Next       = "WaitForVerifier"
      }
      WaitForVerifier = { Type = "Wait", Seconds = 60, Next = "CheckCrawl" }
      CrawlDone = {
        Type = "Pass"
        Parameters = {
          "site.$"       = "$.crawl.site"
          "run_id.$"     = "$.crawl.run_id"
          "command.$"    = "$.crawl.command"
          "result.$"     = "$.verification.check"
          "task_error.$" = "$.task_error"
        }
        End = true
      }
    }
  }

  crawl_flow_definition = {
    Comment        = "Crawl flow (dev). See infra/terraform/orchestration.tf."
    StartAt        = "Start"
    TimeoutSeconds = 86400
    States = merge(local.ecs_step_states, {
      Start = merge(local.helper_invoke, {
        Parameters = {
          FunctionName = aws_lambda_function.crawl_flow_helper.arn
          Payload = {
            action                = "start"
            "execution_arn.$"     = "$$.Execution.Id"
            "state_machine_arn.$" = "$$.StateMachine.Id"
            "input.$"             = "$"
          }
        }
        # Replaces the raw input with {"flow": {...}}: start_at, limit, run IDs.
        ResultSelector = { "flow.$" = "$.Payload" }
        ResultPath     = "$"
        # Another run in progress, or bad input: refuse before doing anything.
        Catch = [{ ErrorEquals = ["States.ALL"], ResultPath = "$.failure", Next = "StartRefused" }]
        Next  = "StartAt"
      })
      StartRefused = { Type = "Fail", Error = "CrawlFlowRefused", CausePath = "$.failure.Cause" }
      StartAt = {
        Type    = "Choice"
        Choices = [{ Variable = "$.flow.start_at", StringEquals = "images", Next = "Run_image_pipeline" }]
        Default = "Run_seed_registry"
      }
      ListCrawls = merge(local.helper_invoke, {
        Parameters = {
          FunctionName = aws_lambda_function.crawl_flow_helper.arn
          Payload      = { action = "list_crawls", "flow.$" = "$.flow" }
        }
        ResultSelector = { "crawls.$" = "$.Payload.crawls" }
        ResultPath     = "$.crawl_list"
        Catch          = [{ ErrorEquals = ["States.ALL"], ResultPath = "$.failure", Next = "Failed_list_crawls" }]
        Next           = "Crawls"
      })
      Crawls = {
        Type          = "Map"
        ItemsPath     = "$.crawl_list.crawls"
        ItemSelector  = { "crawl.$" = "$$.Map.Item.Value" }
        ItemProcessor = local.crawl_branch
        ResultPath    = "$.crawls"
        Catch         = [{ ErrorEquals = ["States.ALL"], ResultPath = "$.failure", Next = "Failed_crawls" }]
        Next          = "Gate"
      }
      Gate = merge(local.helper_invoke, {
        Parameters = {
          FunctionName = aws_lambda_function.crawl_flow_helper.arn
          Payload      = { action = "gate", "crawls.$" = "$.crawls" }
        }
        ResultSelector = { "published.$" = "$.Payload.published", "total.$" = "$.Payload.total" }
        ResultPath     = "$.gate"
        Next           = "AnyPublished"
      })
      AnyPublished = {
        Type    = "Choice"
        Choices = [{ Variable = "$.gate.published", NumericGreaterThan = 0, Next = "Run_dbt_run" }]
        Default = "Summary"
      }
      FindImageMarker = merge(local.helper_invoke, {
        Parameters = {
          FunctionName = aws_lambda_function.crawl_flow_helper.arn
          Payload      = { action = "find_image_marker", "flow.$" = "$.flow" }
        }
        ResultSelector = {
          "found.$"  = "$.Payload.found"
          "dt.$"     = "$.Payload.dt"
          "marker.$" = "$.Payload.marker"
          "run_id.$" = "$.Payload.run_id"
        }
        ResultPath = "$.image_marker"
        Catch      = [{ ErrorEquals = ["States.ALL"], ResultPath = "$.failure", Next = "Failed_image_marker" }]
        Next       = "ImagesToCheck"
      })
      # _SUCCESS or _FAILED: validate what downloaded. No marker: nothing to
      # download, so go straight to the image models.
      ImagesToCheck = {
        Type    = "Choice"
        Choices = [{ Variable = "$.image_marker.found", BooleanEquals = true, Next = "Run_quality_checker" }]
        Default = "Run_dbt_run_images"
      }
      Summary = merge(local.helper_invoke, {
        Parameters = {
          FunctionName = aws_lambda_function.crawl_flow_helper.arn
          Payload      = { action = "summary", "state.$" = "$" }
        }
        ResultSelector = { "status.$" = "$.Payload.status", "subject.$" = "$.Payload.subject", "text.$" = "$.Payload.text" }
        ResultPath     = "$.summary"
        Next           = "Notify"
      })
      # Email the summary after every run. A failed email doesn't change the
      # run's result.
      Notify = {
        Type     = "Task"
        Resource = "arn:aws:states:::sns:publish"
        Parameters = {
          TopicArn    = aws_sns_topic.crawl_flow_runs.arn
          "Subject.$" = "$.summary.subject"
          "Message.$" = "$.summary.text"
        }
        ResultPath = null
        Catch      = [{ ErrorEquals = ["States.ALL"], ResultPath = "$.notify_error", Next = "Outcome" }]
        Next       = "Outcome"
      }
      Outcome = {
        Type    = "Choice"
        Choices = [{ Variable = "$.summary.status", StringEquals = "succeeded", Next = "Succeeded" }]
        Default = "Failed"
      }
      Succeeded = { Type = "Succeed" }
      Failed    = { Type = "Fail", Error = "CrawlFlowFailed", CausePath = "$.summary.text" }
    })
  }
}

data "aws_security_group" "dbt_task" {
  name   = "price-comparison-dbt-task-sg"
  vpc_id = data.aws_vpc.default.id
}

data "aws_iam_role" "dbt_execution" {
  name = "price-comparison-dbt-execution"
}

data "aws_iam_role" "dbt_task_dev" {
  name = "price-comparison-dbt-task-dev"
}

# -------------------------------------------------------
# Helper Lambda (lambda/crawl_flow_helper)
# -------------------------------------------------------

data "archive_file" "crawl_flow_helper_zip" {
  type        = "zip"
  source_dir  = "${path.root}/../../lambda/crawl_flow_helper"
  output_path = "${path.module}/.terraform/tmp/crawl_flow_helper.zip"
  excludes    = ["__pycache__"]
}

resource "aws_iam_role" "crawl_flow_helper" {
  name = "${var.ecs_name}-crawl-flow-helper-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17",
    Statement = [{
      Effect    = "Allow",
      Principal = { Service = "lambda.amazonaws.com" },
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy" "crawl_flow_helper" {
  name = "${var.ecs_name}-crawl-flow-helper-policy"
  role = aws_iam_role.crawl_flow_helper.id

  # Dev only. Reads the seeded registry (Athena), writes per-site URL lists,
  # reads crawl markers and manifests and image markers, lists flow runs.
  policy = jsonencode({
    Version = "2012-10-17",
    Statement = [
      {
        Sid      = "Logs"
        Effect   = "Allow"
        Action   = ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"]
        Resource = "*"
      },
      {
        Sid      = "ListFlowRuns"
        Effect   = "Allow"
        Action   = ["states:ListExecutions"]
        Resource = local.crawl_flow_arn
      },
      {
        Sid      = "QueryRegistry"
        Effect   = "Allow"
        Action   = ["athena:StartQueryExecution", "athena:GetQueryExecution", "athena:GetQueryResults"]
        Resource = "arn:aws:athena:${var.region}:${data.aws_caller_identity.current.account_id}:workgroup/${var.athena_workgroup_name}"
      },
      {
        Sid    = "ReadRegistryTable"
        Effect = "Allow"
        Action = ["glue:GetDatabase", "glue:GetTable", "glue:GetPartitions"]
        Resource = [
          "arn:aws:glue:${var.region}:${data.aws_caller_identity.current.account_id}:catalog",
          "arn:aws:glue:${var.region}:${data.aws_caller_identity.current.account_id}:database/${var.dbt_database_name}",
          "arn:aws:glue:${var.region}:${data.aws_caller_identity.current.account_id}:table/${var.dbt_database_name}/crawl_plp_registry"
        ]
      },
      {
        Sid      = "ListFlowPrefixes"
        Effect   = "Allow"
        Action   = ["s3:ListBucket"]
        Resource = aws_s3_bucket.price_comparison_bucket.arn
        Condition = {
          StringLike = {
            "s3:prefix" = [
              "dbt/dev/*",
              "bronze/dev/crawls/markers/*",
              "bronze/dev/images/download_log/meta/*",
              "${var.athena_results_prefix}crawl-flow/*"
            ]
          }
        }
      },
      {
        # Athena checks the results bucket's region; this request has no
        # prefix, so it can't sit under the prefix condition above.
        Sid      = "BucketLocation"
        Effect   = "Allow"
        Action   = ["s3:GetBucketLocation"]
        Resource = aws_s3_bucket.price_comparison_bucket.arn
      },
      {
        Sid    = "ReadRegistryDataAndRunResults"
        Effect = "Allow"
        Action = ["s3:GetObject"]
        Resource = [
          "${aws_s3_bucket.price_comparison_bucket.arn}/dbt/dev/*",
          "${aws_s3_bucket.price_comparison_bucket.arn}/bronze/dev/crawls/markers/*",
          "${aws_s3_bucket.price_comparison_bucket.arn}/bronze/dev/crawls/manifests/*"
        ]
      },
      {
        Sid      = "AthenaResults"
        Effect   = "Allow"
        Action   = ["s3:GetObject", "s3:PutObject", "s3:AbortMultipartUpload", "s3:ListMultipartUploadParts"]
        Resource = "${aws_s3_bucket.price_comparison_bucket.arn}/${var.athena_results_prefix}crawl-flow/*"
      },
      {
        Sid      = "WriteCrawlInputs"
        Effect   = "Allow"
        Action   = ["s3:PutObject"]
        Resource = "${aws_s3_bucket.price_comparison_bucket.arn}/bronze/dev/crawl-inputs/*"
      }
    ]
  })
}

resource "aws_lambda_function" "crawl_flow_helper" {
  function_name    = "${var.ecs_name}-crawl-flow-helper"
  role             = aws_iam_role.crawl_flow_helper.arn
  handler          = "handler.handler"
  runtime          = "python3.11"
  timeout          = 180
  memory_size      = 256
  filename         = data.archive_file.crawl_flow_helper_zip.output_path
  source_code_hash = data.archive_file.crawl_flow_helper_zip.output_base64sha256

  environment {
    variables = {
      APP_ENV          = "dev"
      BUCKET           = var.price_comparison_bucket
      ATHENA_WORKGROUP = var.athena_workgroup_name
      ATHENA_OUTPUT    = "s3://${var.price_comparison_bucket}/${var.athena_results_prefix}crawl-flow/"
      REGISTRY_TABLE   = "\"${var.dbt_database_name}\".\"crawl_plp_registry\""
      MAX_VERIFY_POLLS = "15"
    }
  }
}

# -------------------------------------------------------
# Run summary email (step 5)
# -------------------------------------------------------

resource "aws_sns_topic" "crawl_flow_runs" {
  name = "${var.ecs_name}-crawl-flow-runs"
}

# The address lives in the gitignored local.auto.tfvars. AWS emails a
# confirmation link; nothing arrives until it's clicked.
resource "aws_sns_topic_subscription" "crawl_flow_runs_email" {
  count     = nonsensitive(var.crawl_alert_email != "") ? 1 : 0
  topic_arn = aws_sns_topic.crawl_flow_runs.arn
  protocol  = "email"
  endpoint  = var.crawl_alert_email
}

# -------------------------------------------------------
# State machine
# -------------------------------------------------------

resource "aws_iam_role" "crawl_flow" {
  name = "${var.ecs_name}-crawl-flow-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17",
    Statement = [{
      Effect    = "Allow",
      Principal = { Service = "states.amazonaws.com" },
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy" "crawl_flow" {
  name = "${var.ecs_name}-crawl-flow-policy"
  role = aws_iam_role.crawl_flow.id

  # Start and watch the four tasks (crawler, image pipeline, quality checker,
  # dbt), pass only their roles to ECS, call the helper Lambda and email the
  # summary.
  policy = jsonencode({
    Version = "2012-10-17",
    Statement = [
      {
        Sid    = "RunFlowTasks"
        Effect = "Allow"
        Action = ["ecs:RunTask"]
        Resource = [
          "${aws_ecs_task_definition.scraper.arn_without_revision}:*",
          "${aws_ecs_task_definition.image_pipeline.arn_without_revision}:*",
          "${aws_ecs_task_definition.image_quality_checker.arn_without_revision}:*",
          "${local.dbt_task_definition_arn}:*"
        ]
      },
      {
        Sid      = "WatchAndStopTasks"
        Effect   = "Allow"
        Action   = ["ecs:DescribeTasks", "ecs:StopTask"]
        Resource = "*"
        Condition = {
          ArnEquals = { "ecs:cluster" = aws_ecs_cluster.scraper.arn }
        }
      },
      {
        # Step Functions' managed rule that reports when a .sync task stops.
        Sid      = "SyncTaskEvents"
        Effect   = "Allow"
        Action   = ["events:PutTargets", "events:PutRule", "events:DescribeRule"]
        Resource = "arn:aws:events:${var.region}:${data.aws_caller_identity.current.account_id}:rule/StepFunctionsGetEventsForECSTaskRule"
      },
      {
        Sid    = "PassTaskRoles"
        Effect = "Allow"
        Action = ["iam:PassRole"]
        Resource = [
          aws_iam_role.ecs_task_execution.arn,
          aws_iam_role.ecs_task.arn,
          aws_iam_role.ecs_task_image_pipeline.arn,
          data.aws_iam_role.dbt_execution.arn,
          data.aws_iam_role.dbt_task_dev.arn
        ]
        Condition = {
          StringEquals = { "iam:PassedToService" = "ecs-tasks.amazonaws.com" }
        }
      },
      {
        Sid      = "CallHelper"
        Effect   = "Allow"
        Action   = ["lambda:InvokeFunction"]
        Resource = [aws_lambda_function.crawl_flow_helper.arn, "${aws_lambda_function.crawl_flow_helper.arn}:*"]
      },
      {
        Sid      = "NotifyRunResult"
        Effect   = "Allow"
        Action   = ["sns:Publish"]
        Resource = aws_sns_topic.crawl_flow_runs.arn
      }
    ]
  })
}

resource "aws_sfn_state_machine" "crawl_flow" {
  name       = local.crawl_flow_name
  role_arn   = aws_iam_role.crawl_flow.arn
  type       = "STANDARD"
  definition = jsonencode(local.crawl_flow_definition)

  depends_on = [aws_iam_role_policy.crawl_flow]
}
