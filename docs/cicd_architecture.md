# CI/CD and Orchestration Architecture

The planned AWS setup for deploying and running the crawl pipeline, kept as a
long-term reference. **Status (2026-11-03): mostly not built.** Green-blue boxes
in the diagrams are planned; the rest exists. The order of work is in
`tickets/cicd_pipeline.md` ("▶ Next steps"), and step numbers below refer to it.

Update this doc whenever a step changes what's here, and add a change log row.
Names of planned items are proposals until built. Everything runs in dev until
`../scraper-pipeline/ticket/migrate-validated-dev-to-prod.md` passes.

The diagrams are Mermaid, so they stay editable as text. GitHub renders them;
VS Code's preview needs a Mermaid extension.

---

## What happens on each run

Step Functions decides the order; ECS and Lambda do the work. A failed crawl
doesn't stop the other sites. Frequency: daily for 7 days, then about weekly.

```mermaid
flowchart TD
  sched["EventBridge Scheduler<br/>daily for 7 days, then weekly"]:::planned
  manual["make crawl-flow<br/>start by hand, any time"]:::planned
  sched -->|cron| s1
  manual -->|starts| s1

  subgraph sfn["Step Functions state machine (planned)"]
    s1["1. Seed the registry<br/>dbt seed + its tests"]:::planned
    s2["2. List active sites<br/>sites with active rows"]:::planned
    s3["3. Crawl in parallel<br/>one failure doesn't stop others"]:::planned
    s4["4. Wait for verification<br/>until each run has a status"]:::planned
    s5["5. dbt build<br/>silver and gold"]:::planned
    s6["6. Download images"]:::planned
    s7["7. Check image quality<br/>explicit step, no S3 trigger"]:::planned
    s8["8. dbt build again<br/>new images reach gold"]:::planned
    s9["9. Send summary<br/>statuses and degradations"]:::planned
    s1 --> s2 --> s3 --> s4
    s4 -->|"1+ published"| s5
    s5 --> s6 --> s7 --> s8 --> s9
    s4 -.->|"nothing published"| s9
  end

  dbt1["ECS: dbt task"]:::planned
  reg[("Athena table<br/>crawl_plp_registry")]
  s1 -->|runs| dbt1 -->|writes| reg

  lister["Lambda: site lister"]:::planned
  urls[("S3: URL lists<br/>for non-Ounass crawls")]
  s2 -->|calls| lister -->|writes| urls

  scraper["ECS: scraper, per site"]
  exportfn["Lambda: PLP-efficient export<br/>Ounass only"]
  unverified[("S3: crawl-unverified/")]
  s3 -->|runs| scraper
  scraper -->|"gets inputs"| exportfn
  scraper -->|uploads| unverified

  verifier["Lambda: verifier"]
  published[("S3: crawls/ and manifests<br/>passing runs only")]
  unverified -.->|"S3 event"| verifier
  verifier -->|publishes| published
  s4 -.->|"polls run status"| published

  dbt2["ECS: dbt task"]:::planned
  silver[("Athena + Glue<br/>silver and gold")]
  s5 -->|runs| dbt2 -->|builds| silver

  images["ECS: image pipeline"]
  blobs[("S3: images/by-hash")]
  s6 -->|runs| images -->|writes| blobs

  checker["ECS: quality checker"]
  results[("S3: image results<br/>gold serves validated only")]
  s7 -->|runs| checker -->|writes| results

  dbt3["ECS: dbt task"]:::planned
  gold[("Athena + Glue<br/>gold")]
  apicache["Lambda: API cache export"]
  s8 -->|runs| dbt3 -->|builds| gold
  gold -.->|"after dbt, rule disabled today"| apicache

  sns["SNS topic<br/>alerts on failed or killed"]:::planned
  inbox["Your inbox"]
  s9 -->|sends| sns -->|emails| inbox

  classDef planned fill:#ddf0f5,stroke:#0b6f8a,color:#16232d
```

**To resolve when building:**
- Remove the S3 notification that starts the quality checker
  (`infra/terraform/lambda.tf`), or it runs twice (step 3).
- dbt runs twice per flow, so the API cache rule
  (`../scraper-pipeline/terraform/eventbridge_api_export.tf`) would fire twice if
  enabled (step 2).
- Never `--full-refresh` the Ounass silver models
  (`docs/ounass_plp_efficient_crawl.md`, section 7).

---

## How code reaches AWS

A push to GitHub starts a build, which logs in to AWS with short-lived
credentials and pushes an image. Running tasks pick up that image on their next
start.

```mermaid
flowchart LR
  crawler["ecommerce-scraper<br/>crawler code"]
  pipeline["scraper-pipeline<br/>dbt models, registry CSV"]
  infra["infra/terraform<br/>in both repos"]

  buildcrawler["GitHub Actions<br/>test, build image"]
  builddbt["GitHub Actions<br/>build dbt image"]:::planned
  applytf["Terraform plan and apply<br/>laptop now, Actions at step 7"]:::planned

  oidc["OIDC + IAM<br/>short-lived login, no stored keys<br/>crawler role exists, others planned"]

  ecrcrawler[("ECR: ecommerce-scraper<br/>tags sha-... and latest")]
  ecrdbt[("ECR: dbt image")]:::planned
  awsres["Scheduler, Step Functions,<br/>ECS, Lambda, SNS, IAM"]
  tfstate[("S3: Terraform state<br/>scraper-pipeline moves here, step 1")]

  crawler -->|push| buildcrawler -->|assumes| oidc
  pipeline -->|push| builddbt -->|assumes| oidc
  infra -->|change| applytf -->|assumes| oidc
  oidc -->|pushes| ecrcrawler
  oidc -->|pushes| ecrdbt
  oidc -->|applies| awsres
  awsres -.->|"records state"| tfstate

  web["price-comparison-web<br/>discuss last, no plan yet (step 11)"]:::later

  classDef planned fill:#ddf0f5,stroke:#0b6f8a,color:#16232d
  classDef later fill:none,stroke:#888888,stroke-dasharray:4 4
```

---

## AWS services

| Service | Job | Status |
|---|---|---|
| EventBridge Scheduler | Starts the flow on a cron | Planned |
| Step Functions | Runs the steps in order, with waits and branches | Planned |
| ECS on Fargate | Runs scraper, image and quality tasks, plus a dbt task | Exists; dbt task planned |
| Lambda | Verifier, export and API cache; site lister | Exists; site lister planned |
| ECR | Stores container images | Exists; dbt repository planned |
| S3 | Crawl data, images, URL lists, Terraform state | Exists |
| Athena + Glue | dbt builds and queries the tables here | Exists |
| SNS | Sends the run summary and failure alerts | Planned |
| IAM + OIDC | Logins for GitHub; roles for the scheduler and flow | Exists; more roles planned |
| Secrets Manager | Holds crawler secrets such as the Zyte key | Exists |
| CloudWatch Logs | Logs from each task | Exists |

Region: `eu-central-1`.

---

## Where each setting lives

Git holds the settings and AWS holds the deployed copy. Only the on/off switch
lives in AWS alone, so pausing doesn't need a commit.

| Setting | Name | Location | Change with |
|---|---|---|---|
| Run frequency | `crawl_schedule_expression` | `infra/terraform/variables.tf` | Terraform |
| Automatic stop after 7 days | `crawl_schedule_end_date` | `infra/terraform/variables.tf` | Terraform |
| On or off | schedule `state` | AWS; Terraform ignores it | `make schedule-on` / `make schedule-off` |
| Timezone and target | the schedule resource | `infra/terraform/orchestration.tf` | Terraform |
| Steps in the flow | the state machine definition | `infra/terraform/orchestration.tf` | Terraform |
| What gets crawled | `crawl_plp_registry.csv` | `../scraper-pipeline/canonical_seeds/` | commit, push; the flow seeds it first |
| Warning thresholds | `OUNASS_PLP_EFFICIENT_*` | `ecommercecrawl/settings.py` | commit, push |

---

## Change log

| Date | Change | Commit |
|---|---|---|
| 2026-11-03 | Doc created from the agreed plan (mostly not built) | — |
