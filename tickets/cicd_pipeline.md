# Ticket: CI/CD for the Crawler, Data Pipeline and Website

**Status: to plan. One slice in progress: the crawler image via GitHub
Actions (see "In progress").** Written 2026-10-13 as a placeholder after
deploy problems surfaced while building the Ounass PLP-efficient crawl. This
ticket records **why** CI/CD is needed and a rough target; the actual plan is
the first task.

Scope spans all three repos (`ecommerce-scraper`, `../scraper-pipeline`,
`../price-comparison-web`). It lives here because the most urgent piece (the
crawler image) is in this repo.

---

## Objective

Make deployments repeatable, visible and off the laptop:

- **`main` is what runs in dev; prod is an explicit, approved promotion.**
- Every change to infrastructure shows its effect (a `terraform plan`)
  before it's applied.
- You can always tell exactly which commit is running in the cloud.
- Builds and deploys don't depend on the laptop's network.

---

## Why (evidence, 2026-10-13)

There is no CI/CD in any repo (no `.github/workflows`); every deploy is a
manual `make` / `terraform apply` from the laptop. In one session this
produced:

1. **Crawler image 2+ months behind `main`.** ECR `ecommerce-scraper:latest`
   was pushed 2026-08-03. Since then `28c7fc7` (browserHtml fallback made
   opt-in, a Zyte cost fix) and `2e1a482` (Content-Type on S3 image uploads)
   never reached the cloud. Cloud crawls still use the more expensive
   behaviour.
2. **API-cache Lambda code undeployed for 2.5 months.**
   `scripts/export_api_cache.py` changed 2026-07-30 (Product Schema V2), but
   both the dev and prod Lambdas still run the 2026-07-10 code, while
   `scraper-pipeline/ticket/migrate-validated-dev-to-prod.md` says "prod
   Lambda code already deployed".
3. **An untargeted `terraform apply` would have shipped (2) to prod as a side
   effect** of an unrelated change. It was avoided only by reading the plan by
   hand and using `-target`.
4. **The laptop can't build.** The company network inspects HTTPS, so
   `docker build` (pip inside the container) and `pip install` fail with
   `CERTIFICATE_VERIFY_FAILED`. Workarounds involve exporting or trusting the
   company certificate, which `context/AGENTS.md` rules out (and which
   endpoint security has flagged before).
5. **scraper-pipeline's Terraform state is a local file on OneDrive**
   (`terraform/terraform.tfstate`), with no remote backend and no locking.
   OneDrive already corrupted that repo's `.venv` (symlinks turned into text
   files). Losing or mangling the state file means Terraform no longer knows
   what it manages. ecommerce-scraper already uses an S3 backend.
6. **No version traceability.** Images are only tagged `latest`, so "is the
   cloud on the latest code?" can only be answered by comparing dates.

---

## Rough target (to be refined in planning)

| Layer | Every PR / push | On merge to `main` | Prod |
|---|---|---|---|
| Crawler image (this repo) | `pytest` | build, push `<sha>` to ECR | manual "promote `<sha>` to `latest`" |
| Lambdas + infra (Terraform, both repos) | `fmt`, `validate`, `plan` posted on the PR | apply to dev | apply to prod behind a required approval |
| dbt (scraper-pipeline) | `dbt parse` / compile, Python tests | `dbt build` changed models in dev | same, behind approval |
| Website (price-comparison-web) | lint, tests, build | deploy to dev | approval → prod |

Cross-cutting:
- **Auth:** GitHub Actions → AWS via **OIDC**, with narrow per-job roles and
  no stored AWS keys.
- **Traceability:** images tagged by commit SHA; the crawl manifest could
  record the image SHA each crawl ran with.
- **Drift detection:** a nightly `terraform plan` that alerts if AWS differs
  from `main`.

**Rough order:**
1. Move scraper-pipeline's Terraform state to S3 with locking (biggest risk,
   smallest fix).
2. Crawler image CI (build on push, manual promote).
3. Terraform plan-on-PR / apply-on-merge for both repos. Deploy the pending
   2026-07-30 API-cache code deliberately through it.
4. dbt in CI.
5. Website pipeline; nightly drift checks.

---

## ▶ In progress: crawler image via GitHub Actions (direction agreed 2026-10-15)

First slice of this ticket, pulled forward because the cloud crawler image
is stale and the laptop can't build it.

**Facts checked 2026-10-15:**
- ECR `ecommerce-scraper:latest` pushed 2026-08-03 08:51 +04
  (`sha256:751475c4…`). ECS task `ecommerce-scraper` runs `:latest`, so moving
  that tag is the deploy.
- A local `make ecr-push` attempt failed at the Dockerfile's
  `pip install poetry` (`CERTIFICATE_VERIFY_FAILED`). Nothing was pushed, but
  its `docker-prune` emptied local Docker. The user may still try a manual
  push from their own terminal (commands: build `--no-cache`,
  `make ecr-login`, tag `latest` + `<sha>`, push both).
- **No IAM OIDC provider exists** in account `565562062476`; one must be
  created.
- `gh` CLI installed and logged in as `tareklel`.
- The repo `tareklel/ecommerce-scraper` is **public**:
  - Actions minutes are free and unlimited;
  - environment approval gates are available on the free plan;
  - the AWS role must trust only `main` and the `production` environment,
    never PRs (anyone can open one).
- This repo's Terraform is initialised with the S3 backend
  (`ecommerce-tf-state-eu-central-1-565562062476`), aws provider `~> 6.0`.

**Proposed setup (not yet written; review files before anything is
applied or pushed):**
1. `.github/workflows/crawler-image.yml`: on push to `main` touching
   `ecommercecrawl/`, `run_*.py`, `scripts/`, `Dockerfile`, `pyproject.toml`,
   `poetry.lock` (plus manual run).
   - test job: Python 3.11 + Poetry 1.8.5 (as in the Dockerfile), then
     `poetry run pytest`.
   - build job (needs test): OIDC → AWS, buildx `linux/amd64` with GHA
     layer cache, push **`sha-<7>`** only. It never moves `latest`.
2. `.github/workflows/promote-crawler-image.yml`: manual input `sha-…`, in
   the `production` environment (the user is the required reviewer).
   Re-tags that image as `latest` via ECR `batch-get-image` + `put-image`, so
   there's no rebuild. Rollback = promote an older SHA.
3. `infra/terraform/github_actions.tf`:
   - the OIDC provider `token.actions.githubusercontent.com`
     (audience `sts.amazonaws.com`);
   - role `ecommerce-scraper-github-actions`, trust `sub` =
     `repo:tareklel/ecommerce-scraper:ref:refs/heads/main` **or**
     `repo:tareklel/ecommerce-scraper:environment:production`. Jobs that use
     an environment get the environment form of `sub`, so both are needed.
   - permissions: `ecr:GetAuthorizationToken` plus push/pull/describe on the
     `ecommerce-scraper` repository only;
   - output the role ARN.
4. **ECR lifecycle fix** (`infra/terraform/ecr.tf`): today's rule "keep last
   10, any tag" can expire the image tagged `latest`. Plan: expire untagged
   images after a few days and keep the last ~20 `sha-` images. **Verify in
   AWS docs first** how a `tagPrefixList` rule treats an image tagged both
   `sha-…` and `latest`. If it can still expire it, choose another design.
5. GitHub settings via `gh`: create the `production` environment with the
   user as required reviewer; store the role ARN as repo variable
   `AWS_CRAWLER_IMAGE_ROLE_ARN`.
6. After it works: push the workflows, let CI build `sha-<HEAD>`, promote it.
   That also fixes today's stale cloud image. Keep `make ecr-push` as a
   manual fallback; update this ticket and `context/memory.md`.

**Needs explicit approval, each separately:** the Terraform apply (new OIDC
provider and IAM role), the GitHub environment and variable, and pushing
the workflows to `main` (which triggers the first build).

**Progress (2026-10-15):**
- [x] Steps 1–4 written: `.github/workflows/crawler-image.yml`,
  `.github/workflows/promote-crawler-image.yml`,
  `infra/terraform/github_actions.tf` (+ `github_repository` variable, role
  ARN output), new `ecr.tf` lifecycle policy. Terraform fmt and validate OK;
  workflow YAML parses.
- [x] ECR multi-tag question resolved from AWS docs: a tag-prefix rule
  matches if **any** tag matches, so a `sha-` rule alone could expire
  `latest`. But a higher-priority rule that matches an image shields it from
  lower ones, so rule 1 (`latest`, keep 1) protects the live image.
- [x] **Terraform applied** (approved): 4 added, 1 replaced (lifecycle
  policy), 0 changed. Role:
  `arn:aws:iam::565562062476:role/ecommerce-scraper-github-actions`.
  Lifecycle preview: only 4 untagged July 28–29 leftovers expire; `latest`,
  `schema-v2-dev-20260730` and the parts `latest` references are kept.
- [x] Step 5 (2026-10-15, run by the user): GitHub `production` environment
  (required reviewer: tareklel, `prevent_self_review: false`, deployment
  branch policy `main` only) and repo variable `AWS_CRAWLER_IMAGE_ROLE_ARN`.
  No secrets were created: OIDC issues short-lived credentials per run.
  Rebuild: `terraform apply` in `infra/terraform` plus
  `gh api -X PUT repos/tareklel/ecommerce-scraper/environments/production`
  (reviewer id 16095919), `.../deployment-branch-policies -f name=main`, and
  `gh variable set AWS_CRAWLER_IMAGE_ROLE_ARN`. In zsh don't name a
  variable `UID`; it's read-only.
- [x] 2026-10-15: the current live image (2026-08-03,
  `sha256:751475c4…`) is also tagged **`legacy-20260803`**. No lifecycle rule
  matches `legacy-`, so it's kept permanently as a rollback target; the
  promote workflow accepts `legacy-YYYYMMDD` as well as `sha-…`.
- [x] Step 6a: pushed `f27b920` + `6dee88c`. First CI run (`38741337257`) failed
  in the test job: 15 tests read saved real product pages
  (`tests/farfetch_html_fixtures/*.html`, `tests/fixtures/bloomingdales_pdp.html`)
  that are gitignored and so absent in CI. They must not be committed
  (downloaded product data, `context/AGENTS.md`). Fix: those tests now skip,
  with a stated reason, when the page is absent; locally they still run.
  Simulated CI result: 284 passed, 15 skipped.
- [x] Step 6b: CI green (`38741812757`, 284 passed / 15 skipped), then the
  user promoted `sha-f3737dd`. **Cloud crawler up to date as of 2026-10-15
  13:27 UTC** (`latest` = `sha256:503f669f…`); the old image is kept as
  `legacy-20260803`.
- [x] **Switched to auto-deploy (option A, 2026-10-15):** a manual approval
  per deploy was too much friction for a solo workflow. `crawler-image.yml`
  now pushes `sha-<7>` **and** `latest` once tests pass, and its run
  summary names the previously live image. `promote-crawler-image.yml` is
  kept for rollback or deploying an older build. The `production`
  environment no longer needs a reviewer (branch policy `main` only
  remains). Consequence: any crawler-code change pushed to `main` goes live
  at the next crawl, so keep `main` deployable.
- [x] Auto-deploy verified 2026-10-15: run `38743279982` (push of
  `6f94c7f`) tested, built and moved `latest` to `sha-6f94c7f`
  (`sha256:b440ea60…`) with no manual step.
- [ ] Follow-up: replace `tests/fixtures/bloomingdales_pdp.html` with a small
  **synthetic** fixture (Bloomingdale's is a live crawler, so CI should
  cover `extract_product`). Farfetch fixtures can stay local-only; that
  crawler is blocked.

## Known constraints and pitfalls

- **ECR cleanup rule can delete the live image.** `infra/terraform/ecr.tf`
  keeps "the last 10 images, any tag". With per-commit SHA images and manual
  promotion, an older image tagged `latest` would be expired after 10 newer
  builds, and ECS would have nothing to pull. The rule must exclude `latest`.
- **ECS runs `:latest`**, so moving that tag *is* the deploy. Auto-moving it on
  every merge would ship every commit straight to cloud crawls.
- **Creating OIDC providers and roles is a permissions change in AWS:** each
  needs explicit approval (`context/AGENTS.md`).
- **Docs-only commits** should be filtered out so they don't trigger builds.

## Cost estimate (2026-10-13)

- **GitHub Actions:** ~30 commits/month peak × ~8 min ≈ 220 min, well
  inside the 2,000 free Linux minutes/month for private repos.
- **ECR:** about $0.47/month today (10 × ~465 MB); per-commit builds don't add
  to it while the cap is 10.
- AWS CodeBuild would cost about the same; GitHub Actions is preferred for its
  simpler setup and logs next to commits.

---

## Related

- `tickets/crawl_scheduler.md`: scheduled crawls would run the deployed image.
- `../scraper-pipeline/ticket/migrate-dbt-to-cloud-jobs.md`: dbt cloud jobs
  (fold into step 4).
- `../scraper-pipeline/ticket/migrate-validated-dev-to-prod.md`: holds the
  pending API-cache Lambda redeploy note.
- `tickets/ounass_plp_efficient_crawl.md`: where these problems surfaced.

## First task when picked up

Turn the rough target into a reviewed plan: which repos first, approval
rules per environment, OIDC role boundaries, and the Terraform state
migration steps.
