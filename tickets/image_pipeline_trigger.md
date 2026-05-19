# Ticket: Production Trigger for `run_image_pipeline.py`

## Goal

Define and implement how `run_image_pipeline.py` is triggered in production —
either on a schedule or event-driven after a crawl completes.

---

## Options

### Option A — Scheduled cron (EventBridge Scheduler)
Run the image pipeline on a fixed schedule (e.g. daily at 02:00 UTC) regardless
of whether new crawl data landed.

**Pros:** Simple. No coupling to crawl pipeline. Easy to reason about.  
**Cons:** May run when there's nothing to download (Athena query returns 0 rows —
harmless but wasteful). Delay between crawl completion and image download.

**Implementation:**
- EventBridge Scheduler rule targeting ECS `run_task` on the `image-pipeline` task definition
- Terraform: `aws_scheduler_schedule` resource in a new `scheduler.tf`
- IAM: scheduler needs `ecs:RunTask` + `iam:PassRole` on the image pipeline task role

---

### Option B — Event-driven after crawl completes
Trigger the image pipeline when a crawl `_SUCCESS` marker lands in S3
(same pattern as `image_pipeline_trigger` Lambda for the quality checker).

**Pros:** Images downloaded as soon as crawl data is available. No wasted runs.  
**Cons:** Tighter coupling. Crawl pipeline must write a detectable completion signal.
Multiple crawls completing close together could cause concurrent pipeline runs.

**Implementation:**
- New Lambda (or extend `bronze_manifest_verifier`) triggered by crawl `_SUCCESS`
- Calls `ecs.run_task()` on `image-pipeline`
- Must handle concurrency: if a run is already in flight, skip or queue

---

### Option C — Hybrid: daily cron + idempotent re-runs
Schedule daily but make re-runs safe (already handled — Athena query skips
images with `status=ok` in `image_download_log`).

**Recommendation:** Start with Option A (cron). Simplest to ship, zero risk of
missed triggers. Revisit Option B once crawl cadence and volume are known.

---

## Decision

- [ ] Choose trigger strategy

---

## Implementation (Option A — Cron)

### Terraform (`infra/terraform/scheduler.tf`)

```hcl
resource "aws_scheduler_schedule" "image_pipeline_daily" {
  name       = "image-pipeline-daily"
  group_name = "default"

  flexible_time_window { mode = "OFF" }
  schedule_expression          = "cron(0 2 * * ? *)"   # 02:00 UTC daily
  schedule_expression_timezone = "UTC"

  target {
    arn      = "arn:aws:ecs:${var.region}:${data.aws_caller_identity.current.account_id}:cluster/${aws_ecs_cluster.scraper.name}"
    role_arn = aws_iam_role.image_pipeline_scheduler.arn

    ecs_parameters {
      task_definition_arn = aws_ecs_task_definition.image_pipeline.arn
      launch_type         = "FARGATE"

      network_configuration {
        assign_public_ip = true
        subnets          = data.aws_subnets.default.ids
        security_groups  = [aws_security_group.ecs_task.id]
      }
    }

    input = jsonencode({
      containerOverrides = [{
        name    = "image-pipeline"
        command = [
          "python run_image_pipeline.py",
          "--athena-database ${var.glue_database_name}",
          "--athena-workgroup ${var.athena_workgroup_name}",
          "--athena-output-loc s3://${var.price_comparison_bucket}/${var.athena_results_prefix}",
          "--storage-mode s3"
        ]
      }]
    })
  }
}
```

### IAM (`infra/terraform/iam.tf` addition)

```hcl
resource "aws_iam_role" "image_pipeline_scheduler" {
  name = "${var.ecs_name}-${var.region}-image-pipeline-scheduler-role"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "scheduler.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy" "image_pipeline_scheduler_policy" {
  name = "${var.ecs_name}-image-pipeline-scheduler-policy"
  role = aws_iam_role.image_pipeline_scheduler.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["ecs:RunTask"]
        Resource = aws_ecs_task_definition.image_pipeline.arn
      },
      {
        Effect   = "Allow"
        Action   = ["iam:PassRole"]
        Resource = [
          aws_iam_role.ecs_task_execution.arn,
          aws_iam_role.ecs_task_image_pipeline.arn
        ]
      }
    ]
  })
}
```

---

## Files to Change

| File | Change |
|------|--------|
| `infra/terraform/scheduler.tf` | New — EventBridge Scheduler rule |
| `infra/terraform/iam.tf` | Add scheduler IAM role + policy |

---

## Open Questions

- [ ] What time of day should the pipeline run? (depends on crawl schedule)
- [ ] Should there be a max concurrency guard to prevent overlapping runs?
- [ ] Alert/notification if the pipeline errors (CloudWatch alarm on ECS task stop code)?
