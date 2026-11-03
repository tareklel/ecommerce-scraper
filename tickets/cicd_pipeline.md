# Ticket: CI/CD for the Crawler, Data Pipeline and Website

**Status: in progress; follow "▶ Next steps" below.** The crawler image
slice is done. Written 2026-10-13 after deploy problems surfaced while
building the Ounass PLP-efficient crawl. The sections after "Next steps"
record why CI/CD is needed, the target, and history.

Scope spans all three repos (`ecommerce-scraper`, `../scraper-pipeline`,
`../price-comparison-web`). It lives here because the most urgent piece (the
crawler image) is in this repo.

---

## ▶ Next steps (updated 2026-11-02)

Work top to bottom and tick items off as they finish. Check each item against
the repos before starting, because this list can go out of date.
Diagrams, AWS services and config locations: `docs/cicd_architecture.md`. Update
it whenever a step changes what's there.

**Decided 2026-11-02 (user):**
- Orchestrate with **Step Functions**: first test runs by hand, then from an
  EventBridge schedule (step 6).
- **Run daily for 7 days, then switch to about weekly** while the site is
  unfinished (user, 2026-11-03). Thresholds are already set for weekly: G8 warn
  age 8 days, stale-crawl warning 14 days.
- **What gets crawled comes from `../scraper-pipeline/canonical_seeds/crawl_plp_registry.csv`**
  (`is_active` per listing): version-controlled, reviewed and tested, no
  second list. Sites to run = sites with active rows. A CSV edit takes effect
  only after `dbt seed`, so the flow seeds first (steps 3 and 4).
- **Images stay on** in every run: gold only serves validated images.
- Runs use dev until `../scraper-pipeline/ticket/migrate-validated-dev-to-prod.md`
  passes.

**Verified 2026-11-02:** scraper-pipeline's Terraform has no `backend` block
and its state is still a local file on OneDrive; dbt has no cloud job yet;
scraper-pipeline and price-comparison-web have no `.github/workflows`.

**Steps:**

- [ ] **1. Move scraper-pipeline's Terraform state to S3 with locking.**
  Biggest risk, smallest fix. `terraform/backend.hcl.example` and
  `terraform/state/` are the starting points. Back up the state first and
  confirm `terraform plan` shows no changes afterwards.
- [ ] **2. Run dbt in AWS (dev).** This blocks the flow in step 3. Plan is in
  `../scraper-pipeline/ticket/migrate-dbt-to-cloud-jobs.md`: a dbt container
  image built by GitHub Actions (same pattern as the crawler image), run as an
  ECS task. Watch for:
  - **Never `--full-refresh` the Ounass silver models**
    (`docs/ounass_plp_efficient_crawl.md`, section 7).
  - The flow runs dbt twice, so the API-cache export rule in
    `terraform/eventbridge_api_export.tf` would fire twice if enabled. Decide
    how it should fire before enabling it.
- [ ] **3. Build the state machine (dev, Terraform).** Follow "Orchestration
  proposal" below: crawls in parallel, wait for verification, dbt, image
  pipeline and quality checker, dbt again. A failed crawl doesn't stop the
  others. It starts with `dbt seed --select crawl_plp_registry` plus that
  seed's tests, before any crawl and any Zyte spend, because the crawl-start
  export reads the seeded table. No schedule is attached yet.
  Remove the S3 notification that starts the quality checker
  (`infra/terraform/lambda.tf`), or it runs twice. Optional: re-try a crawl
  that failed with `failure_reason: access` a few
  hours later, since a missed site now waits a week.
- [ ] **4. Drive runs from the registry, with one start command.** A run is:
  1. Edit `crawl_plp_registry.csv` if needed, commit and push. CI rebuilds the
     dbt image, which carries the seeds.
  2. `make crawl-flow` (to be written), which prints the active sites and
     starts the state machine. It must fail if the dbt image isn't built from
     the latest registry commit, or the run seeds the old list.
  3. Check the result. After a long break, check whether Phase 2 hit
     `OUNASS_PLP_EFFICIENT_MAX_PHASE2_PDPS` (10,000), because that skips
     product pages for the whole run.

  To build:
  - **Other sites need a reader.** Only Ounass PLP-efficient reads the registry
    today: the export supports only `ounass`, and Level Shoes and Bloomingdale's
    crawl from a `--urls-source` CSV. Export each other site's active URLs to
    S3 for `--urls-source`, and list the active sites for the flow.
  - **Site key vs spider name:** the registry uses `level-shoes`
    (`dim_canonical_site`), the spider is `level`, so the flow needs a mapping.
  - **Crawl mode isn't in the registry.** Proposed: Ounass always runs
    `--plp-efficient`, others run normally.
  - **Whole-site off** means flipping every row of that site to `is_active`
    false. Fine for now; revisit if it becomes annoying.
  - **Fast CSV check in CI:** the seed's dbt tests need Athena, so also check
    the CSV's columns and values in the PR.

  Adding other sites is safe for Ounass (checked 2026-11-02): both export
  queries filter on `site = 'ounass'` and `is_active = true`. As a backstop, the
  crawler's G1 skips any row for another site, though more than 25% bad rows
  would stop the run. New rows must use canonical values or the seed's
  `test_crawl_plp_registry_canonical` fails.
- [ ] **5. Add run alerts.** See "Crawl run alerting" below: one summary per
  run, and an alert on `failed` / `killed`. Report access problems apart from
  content problems.
- [ ] **6. Add the schedule: daily for 7 days, then weekly.**
  - Config lives in this repo's Terraform: a new
    `infra/terraform/orchestration.tf` (schedule and state machine), with
    `crawl_schedule_expression` and `crawl_schedule_end_date` in
    `variables.tf`. Region `eu-central-1`.
  - Start: daily, for example `cron(0 2 * * ? *)`, with `end_date` 7 days out so
    it stops by itself if nobody is watching.
  - After 7 days, review the runs, then set weekly, for example
    `cron(0 2 ? * SUN *)`, and clear `end_date`. Before going weekly, check the
    sold-out cutoff: products sold out 3+ days are dropped and not rechecked,
    so one weekly sighting may be enough to drop them.
  - On/off is the schedule's `state`. Use `lifecycle { ignore_changes = [state] }`
    so Terraform doesn't switch it back, plus `make schedule-on` /
    `make schedule-off`. `aws scheduler update-schedule` needs the full
    definition resent, not just the state.
  - Idle state machines cost nothing, and missed runs aren't caught up.
  - Update `tickets/crawl_scheduler.md`, which still describes daily per-site
    rules that start ECS directly.
  - PLP-efficient Part 7 needs a daily schedule for 1–2 weeks of shadow mode;
    revisit the frequency when it starts.
- [ ] **7. Terraform plan on PR, apply on merge (both repos).** Deploy the
  pending 2026-07-30 API-cache code deliberately through it. Until then, keep
  using targeted applies: an untargeted apply can ship that code to prod.
- [ ] **8. dbt in CI** (`dbt parse` / compile and Python tests on PRs).
- [ ] **9. Nightly Terraform drift check.**
- [ ] **10. Replace `tests/fixtures/bloomingdales_pdp.html`** with a small
  synthetic fixture, so CI covers Bloomingdale's `extract_product`.
- [ ] **11. Discuss CI/CD for the website (web UI), after everything above is
  done.** Not planned yet, and it needs its own discussion first: expect it to
  raise its own problems. Don't start it from the "Rough target" row below
  without that discussion. Its `infra/` also has a local `terraform.tfstate`
  (seen 2026-11-03), the same risk as step 1.

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

## Rough target

| Layer | Every PR / push | On merge to `main` | Prod |
|---|---|---|---|
| Crawler image (this repo) | `pytest` | build, push `<sha>` to ECR | manual "promote `<sha>` to `latest`" |
| Lambdas + infra (Terraform, both repos) | `fmt`, `validate`, `plan` posted on the PR | apply to dev | apply to prod behind a required approval |
| dbt (scraper-pipeline) | `dbt parse` / compile, Python tests | `dbt build` changed models in dev | same, behind approval |
| Website (price-comparison-web), to be discussed last (step 11) | lint, tests, build | deploy to dev | approval → prod |

Cross-cutting:
- **Auth:** GitHub Actions → AWS via **OIDC**, with narrow per-job roles and
  no stored AWS keys.
- **Traceability:** images tagged by commit SHA; the crawl manifest could
  record the image SHA each crawl ran with.
- **Drift detection:** a nightly `terraform plan` that alerts if AWS differs
  from `main`.
- **Crawl run alerting (added 2026-10-19):** today a degraded or failed crawl
  is only visible by querying `crawl_manifest_raw` in Athena: no SNS topic,
  CloudWatch alarm or metric filter exists. Wanted:
  - an alert when a run is `failed` (any `failure_reason`) or `killed`
    (a `crawl_started_raw` record with no manifest);
  - an alert, or a daily digest, when a run is `degraded`, listing its
    `degradations`;
  - access problems (a hostname blocked by Ounass) reported apart from content
    problems, since they need different responses (see
    `docs/ounass_plp_efficient_crawl.md`, section 5);
  - likely mechanism: a CloudWatch metric filter on the crawler's end-of-run
    `RUN DEGRADED` / `ACCESS` log lines (log group `/ecs/<ecs_name>`), or the
    verifier Lambda publishing to SNS when it writes a failure marker.
  Context: run statuses defined in PLP-efficient Part 4b
  (`tickets/ounass_plp_efficient_crawl.md`).

**Crawler image build fixes (2026-10-23):** the `poetry install` step in
the `dockerfile` failed intermittently (`ChefInstallError`): Poetry installs
into its own environment, downgrading `packaging` mid-install while a
parallel source build read it. Fixed with `installer.parallel false`. The
workflow's path filter also only listed `Dockerfile`, while the file is
`dockerfile`, so dockerfile edits never triggered a build; both names are
listed now. Longer term: install Poetry in its own virtualenv in the image.

**Order of work:** see "▶ Next steps" at the top of this ticket.


### Orchestration proposal (2026-10-22; decided 2026-11-02, see "Next steps")

**Today nothing runs on a schedule:** crawls (`make ecs-run`), dbt
(`make dbt-run` on a laptop) and the image pipeline
(`make ecs-run-image-pipeline`) are all started by hand. Only two links are
automatic: the verifier Lambda (crawl manifest → markers, publish) and the
image quality checker (after the image pipeline's `_SUCCESS`).

**Flow wanted (about weekly for now, started by hand):**
1. **Crawls** in parallel (one ECS task per site/mode; Ounass PLP-efficient
   included). A failed crawl doesn't stop the others.
2. **Wait for verification:** read each run's `run_status` (verified
   manifest) before going on. Optionally re-try a crawl that failed with
   `failure_reason: access` a few hours later (blocking comes in windows).
3. **dbt build** (silver + gold), if at least one crawl published.
4. **Image pipeline** (reads the dbt-built image catalog), then the image
   **quality checker**, and **wait for it to finish**: gold only serves
   images that are downloaded and validated (`image_validated`).
5. **dbt build again** (or only the image models), so downloaded images
   reach gold. On 2026-10-22 a dbt run started 7 minutes before the quality
   checker finished and left all 16,087 new images out of gold; today the
   checker is started by a Lambda, outside any flow, so the orchestration
   should run it as an explicit step instead.
6. **Notify:** one summary per run of every crawl's status and degradations;
   an alert on `failed` / `killed` (the "Crawl run alerting" item above).

**Recommended tool: AWS Step Functions + EventBridge Scheduler.**
- Everything is already ECS tasks and Lambdas in one AWS account; Step
  Functions starts ECS tasks and waits for them (`ecs:runTask.sync`), has
  retries, waits, branches and parallel steps built in, and shows each run
  as a diagram with per-step logs.
- Cost: pennies a month (charged per state transition); EventBridge
  Scheduler starts it on a cron.
- Defined in Terraform next to the existing ECS/Lambda resources.
- **Prerequisite:** dbt must run in AWS: a dbt container image (from
  scraper-pipeline) run as an ECS task, built by the same GitHub Actions
  pattern as the crawler image.

**Alternatives considered:** Airflow (MWAA): powerful but ~$350+/month
minimum and heavy to run for a handful of steps. Dagster / Prefect: good
data-asset tooling, but another service and account to run. dbt Cloud:
only covers the dbt step. Revisit Dagster if the pipeline grows into many
interdependent data assets.

---

## Done: crawler image via GitHub Actions (2026-10-15; kept as history)

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
