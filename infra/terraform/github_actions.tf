# ------------------------------------------------------------
# GitHub Actions → AWS for building and promoting the crawler image
# (.github/workflows/crawler-image.yml, promote-crawler-image.yml).
#
# GitHub signs each workflow run with a short-lived OIDC token; AWS exchanges
# it for temporary credentials. No AWS keys are stored in GitHub.
#
# The repository is public, so anyone can open a pull request. The trust
# policy therefore only accepts this repo's `main` branch (the build) and its
# `production` environment (the approved promotion), never PRs or other
# branches.
# ------------------------------------------------------------

resource "aws_iam_openid_connect_provider" "github_actions" {
  url            = "https://token.actions.githubusercontent.com"
  client_id_list = ["sts.amazonaws.com"]
  # No thumbprint_list: AWS verifies GitHub's OIDC certificates itself, and
  # the AWS provider (~> 6.0) no longer requires pinned thumbprints.
}

resource "aws_iam_role" "github_actions_crawler_image" {
  name        = "${var.ecs_name}-github-actions"
  description = "Assumed by GitHub Actions to push and promote the crawler image in ECR."

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Principal = {
          Federated = aws_iam_openid_connect_provider.github_actions.arn
        }
        Action = "sts:AssumeRoleWithWebIdentity"
        Condition = {
          StringEquals = {
            "token.actions.githubusercontent.com:aud" = "sts.amazonaws.com"
            # Jobs that use an environment present the environment form of
            # `sub`, so the promote job needs its own entry.
            "token.actions.githubusercontent.com:sub" = [
              "repo:${var.github_repository}:ref:refs/heads/main",
              "repo:${var.github_repository}:environment:production",
            ]
          }
        }
      }
    ]
  })
}

resource "aws_iam_role_policy" "github_actions_crawler_image" {
  name = "${var.ecs_name}-github-actions-ecr"
  role = aws_iam_role.github_actions_crawler_image.id

  # Only the crawler's ECR repository: push, re-tag, describe. Nothing on ECS,
  # S3, Lambda or secrets.
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "EcrLogin"
        Effect   = "Allow"
        Action   = ["ecr:GetAuthorizationToken"]
        Resource = "*"
      },
      {
        Sid    = "PushAndPromoteCrawlerImage"
        Effect = "Allow"
        Action = [
          "ecr:BatchCheckLayerAvailability",
          "ecr:BatchGetImage",
          "ecr:CompleteLayerUpload",
          "ecr:DescribeImages",
          "ecr:GetDownloadUrlForLayer",
          "ecr:InitiateLayerUpload",
          "ecr:PutImage",
          "ecr:UploadLayerPart"
        ]
        Resource = aws_ecr_repository.scraper.arn
      }
    ]
  })
}
