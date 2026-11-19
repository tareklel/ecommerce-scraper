# Ticket: The crawl flow only ever runs the `latest` crawler image

**Status: in progress (written 2026-11-19)**
**Priority: High. A stale image silently undid a shipped fix during the daily trial.**

## What went wrong

- 2026-11-18: `ba26ece` taught the image downloader to accept Cettire. CI built it
  into `ecommerce-scraper:latest` at 05:37 UTC.
- 2026-11-19 02:00 Dubai run: the image step still rejected every Cettire job
  (`skipped_invalid` 30,458, `ok` 3,497). The run email said
  `cettire: 15,570 crawled -> 15,944 in gold -> 0 with images`.
- Cause: the image-download task family had two active versions.
  - Revision 2 is Terraform's (`image = ...:latest`).
  - Revision 3 was registered by hand on 2026-07-30 with the image
    `ecommerce-scraper:schema-v2-dev-20260730`. Apart from the image it was
    identical to revision 2.
  - The flow names task families without a revision
    (`arn_without_revision`), so ECS ran the newest active one: revision 3, the
    July image, every night since the flow was built. Terraform showed "no
    changes" because its revision 2 was untouched.
- Fixed by hand 2026-11-19: revision 3 deregistered (user-approved). An
  images-only flow run started the same day to download the Cettire backlog.

## Rule

Every ECS task the crawl flow starts from this repo (crawler, image download,
image quality checker) runs the `ecommerce-scraper:latest` image. A rollback moves
`latest` (`promote-crawler-image.yml`); it never pins a task to another tag.
The dbt task belongs to scraper-pipeline and is out of scope here.

## What to build

1. **Pin the flow to Terraform's revisions.** In
   `infra/terraform/orchestration.tf`, the three tasks are referenced by their
   exact Terraform `arn` (with revision), not `arn_without_revision`. A version
   registered outside Terraform is then never run.
   - Consequence: when Terraform replaces one of these task definitions, apply
     the state machine in the same apply (target both). Otherwise the flow points
     at a deregistered revision, and item 2 refuses the run.
2. **Start check refuses a run on any other image.** The helper's `start` reads
   the three task definitions the flow will run (env var `FLOW_TASK_DEFINITIONS`,
   from Terraform) and refuses the run when any of them is not `ACTIVE` or any of
   its containers' images doesn't end in `:latest`. The refusal names the task,
   revision and image, and says what to do.
   - IAM: the helper role gains `ecs:DescribeTaskDefinition`. This action takes
     no resource-level restriction, so the resource is `*`. It is read-only.
3. **A refused start sends an email.** Today `StartRefused` ends the run with
   no email, so a refused scheduled run would fail silently. Refusals (this
   check, another run in progress, bad input) now publish to the run-results
   topic before failing.
4. **Rule in `context/AGENTS.md`:** never register ECS task definitions by hand
   or pin a task to a non-`latest` tag.
5. Tests for 2, and `docs/cicd_architecture.md` (start check, edge case,
   decision log) updated.

## Done when

- [ ] 1–5 built, tests pass, pushed.
- [ ] Targeted apply (helper Lambda, its policy, state machine) with the plan
      shown to the user first, because of the IAM change.
- [ ] A live `start` invoke returns normally with today's task definitions, and a
      test invoke against a non-`latest` image is refused.
- [ ] Next scheduled run's email shows Cettire images in gold.
