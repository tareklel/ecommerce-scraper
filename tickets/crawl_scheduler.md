# Ticket: Crawl Scheduler — EventBridge Daily Trigger per Site

**Status: draft — not reviewed**

## Goal

Crawls are currently triggered manually via `make ecs-run-crawler`. This ticket
adds a daily EventBridge Scheduler rule per site so the system runs and data
stays fresh without manual intervention.

---

## Current State

- ECS task definition for the scraper exists (`infra/terraform/ecs.tf`)
- Secrets Manager wiring injects runtime env into the container
- No automated trigger exists — crawls are ad-hoc

---

## Design

One EventBridge Scheduler rule per site. Each rule fires at a staggered time to
avoid concurrent Athena/S3 load and make failure diagnosis easier.

Suggested schedule (UTC, adjust once crawl duration is known):

| Site | Cron | Rationale |
|------|------|-----------|
| `level-shoes` | `cron(0 1 * * ? *)` | 01:00 UTC daily |
| `ounass` | `cron(0 3 * * ? *)` | 03:00 UTC daily, after level-shoes |

Each rule passes a `containerOverrides.command` with site-specific args.

---

## Terraform (`infra/terraform/scheduler.tf`)

```hcl
locals {
  crawl_schedule = {
    level-shoes = { cron = "cron(0 1 * * ? *)", site = "level-shoes" }
    ounass      = { cron = "cron(0 3 * * ? *)", site = "ounass" }
  }
}

resource "aws_scheduler_schedule" "crawl_daily" {
  for_each = local.crawl_schedule

  name       = "crawl-daily-${each.key}"
  group_name = "default"

  flexible_time_window { mode = "OFF" }
  schedule_expression          = each.value.cron
  schedule_expression_timezone = "UTC"

  target {
    arn      = "arn:aws:ecs:${var.region}:${data.aws_caller_identity.current.account_id}:cluster/${aws_ecs_cluster.scraper.name}"
    role_arn = aws_iam_role.crawl_scheduler.arn

    ecs_parameters {
      task_definition_arn = aws_ecs_task_definition.scraper.arn
      launch_type         = "FARGATE"

      network_configuration {
        assign_public_ip = true
        subnets          = data.aws_subnets.default.ids
        security_groups  = [aws_security_group.ecs_task.id]
      }
    }

    input = jsonencode({
      containerOverrides = [{
        name    = "scraper"
        command = [
          "python run_crawler.py --site ${each.value.site} --env prod"
        ]
      }]
    })
  }
}
```

---

## IAM (`infra/terraform/iam.tf` addition)

```hcl
resource "aws_iam_role" "crawl_scheduler" {
  name = "${var.ecs_name}-${var.region}-crawl-scheduler-role"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "scheduler.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy" "crawl_scheduler_policy" {
  name = "${var.ecs_name}-crawl-scheduler-policy"
  role = aws_iam_role.crawl_scheduler.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["ecs:RunTask"]
        Resource = aws_ecs_task_definition.scraper.arn
      },
      {
        Effect   = "Allow"
        Action   = ["iam:PassRole"]
        Resource = [
          aws_iam_role.ecs_task_execution.arn,
          aws_iam_role.ecs_task.arn
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
| `infra/terraform/scheduler.tf` | New — EventBridge Scheduler rules per site |
| `infra/terraform/iam.tf` | Add scheduler IAM role + policy |

---

## Open Questions

- [ ] Should scheduled crawls use `--urls-source` (recrawl seed from dbt) or full-site discovery mode?
- [ ] If the recrawl_loop ticket ships first, does the scheduler feed recrawl seeds instead of full crawls?
- [ ] Alert/notification on ECS task stop with non-zero exit code? (CloudWatch + SNS)
- [ ] Should schedules be disabled by default in Terraform (`enabled = false`) and enabled manually first run?
