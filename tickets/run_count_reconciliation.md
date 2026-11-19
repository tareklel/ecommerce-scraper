# Ticket: Count check in every run email

**Status: done 2026-11-19 for the agreed scope (day-on-day checks, Zyte real
cost), deployed and checked live. "Site says" totals not built (see "▶ Agreed
scope").**
**Priority: High. Build before the crawl flow goes on a schedule
(`tickets/cicd_pipeline.md` step 6).**
**Before starting: discuss this ticket with the user in an `ecommerce-scraper`
session and agree the scope. Do not start from this ticket alone.**

Source: `notes/2026-11-13-state-of-price-comparison.md`, section 5, gap 3.

## ▶ Agreed scope (with the user, 2026-11-18/19)

Built:
- **Counts to check**, at the top of the email and in the subject ("· N to
  check"): per site, crawled rows / in gold / with images fell more than 10%
  since the previous full run (counts under 50 before are not compared), or
  the site vanished from gold; Zyte's real cost more than doubled and is over
  $1. Warning only: the run status doesn't change, so `docs/crawl_run_status.md`
  is untouched. With no drop the email says "Counts to check: none".
- **Saved counts**: each full run writes `bronze/dev/crawl-flow/run-counts/latest.json`
  (last known value of every count, with the run it came from) and
  `runs/<flow_id>.json`. `--limit` and crawls-only runs are neither compared
  nor saved.
- **Zyte section** (every run that crawls): real cost, requests and 520s per
  site from Zyte's Stats API (`groupby_domain`, the run's time window), run
  total vs the previous run. The user asked for real figures, no estimates.
  The key is Zyte's dashboard "stats" key (read-only usage, not the crawler's
  key) with the organization ID, in Parameter Store
  `/ecommerce-scraper/zyte-stats/api-key` (SecureString) and
  `.../organization-id`, entered by hand. Parameter Store, not Secrets
  Manager: free, and the helper can't read the crawler's secrets. One retry;
  any failure (no key, wrong key, Zyte down) is one "Zyte cost: not available
  (reason)" line and never fails the email. The 520 line takes over
  ecommerce-scraper-fb's proposal.
- Tests in `tests/test_crawl_flow_helper.py` (a deliberate drop, Zyte failure
  paths); `docs/cicd_architecture.md` (edge cases, settings, change log).

Not built (user: "keep d2d for now"):
- "Site says": the site's own product total per listing, compared with what
  the crawl saw. Bloomingdale's (`total`) and Cettire (brand facet counts)
  report one; Ounass gives pages × page size; Level Shoes unknown. Needs a
  crawler change (manifest field) and a crawler image build.
- Separating products scraper-pipeline drops after 14 days unseen from real
  losses (needs scraper-pipeline data); such a drop can show as a warning.

Deployed 2026-11-19 (targeted apply of the helper Lambda and its policy, user
approved; a second code-only apply fixed Zyte's numbers arriving as decimal
strings). Live check, a non-saving summary over the 2026-11-19 02:00 run's
window: Cettire $0.26 for 2,492 requests (511 hit 520 on the first try, 21%),
Ounass $0.14 for 314 requests. So Cettire costs about $0.10 per 1,000
requests, against about $0.45 for Ounass. The first saved counts come from the
images-only run `409d759e` when it ends; the next run compares against them.
Still to see on a real run: whether Zyte's figures are complete by the time the
email is written (if not, the email says "no usage recorded by Zyte yet").

## Why this is high priority

Three times, products went missing for weeks or months and nothing reported it.
Each was found by accident while working on something else:

| What was lost | How long | How it was found |
|---|---|---|
| About 18% of Ounass products per crawl (listing sort paginated with ties) | Nov 2025 – Oct 2026 | Dry run #2 of the listing-based crawl |
| About 95 Ounass bag products (brand or gender not in the seed maps) | Unknown, at least weeks | Dry run #4 |
| 131 products with no brand, 115 of them Level Shoes | Unknown | A failing `dbt test` in the second flow run |

Today you start each run by hand and read its result. Once the flow runs on a
schedule, nobody is watching, and a loss like these can run until a shopper
notices. The run email is the one thing you will still read, so the counts
belong there.

## What to build

One short block per retailer in the run summary, showing how many products
survive each step:

```
Counts (ounass, sa):
  site says        6,545
  seen in listings 6,512
  published rows   6,454
  in gold          6,380
  with images      6,310   <- what the website shows
```

And a "Counts to check" section at the top of the email when a step loses more
than expected, compared with the step before it or with the previous run.

## What already exists

- The Ounass listing API reports its own total (`totalPages` × `hitsPerPage`,
  used in `notes/2026-09-17-ounass-zyte-crawl-cost.md`).
- The listing-based crawl's manifest block has per-listing counts
  (`ecommercecrawl/plp_efficient.py`).
- The flow helper already runs Athena queries and adds a mapping-gaps line to
  the summary (`lambda/crawl_flow_helper/handler.py`, `_mapping_gaps_line`).
- scraper-pipeline's `silver_mapping_gaps` counts products dropped from gold
  for a missing brand, category or gender.
- scraper-pipeline's `ticket/gold-drop-stale-products.md` (open) will remove
  products unseen for 14 days; the counts here must say how many left for that
  reason, so it doesn't read as a loss.

## To find out first

- Do Level Shoes and Bloomingdale's listing pages report a total product count?
  If not, "site says" is blank for them and the check starts at "seen in
  listings".
- Where the gold and with-images counts come from: one Athena query in the
  helper, or a small table built by dbt. The helper is simpler; a table can be
  tested.
- The threshold for "more than expected", and whether crossing it only warns
  or marks the run degraded. Start with a warning.

## Done when

- Every run email shows the count block for each retailer crawled.
- A drop above the threshold appears under "Counts to check", naming the
  retailer and the step.
- A test feeds the summary a deliberate drop and sees the warning.
- `docs/cicd_architecture.md` describes the block. If a new degradation or
  status is added, `docs/crawl_run_status.md` is updated in the same commit.

## Other repos

scraper-pipeline, if the counts come from a dbt table. Send that session a
heads-up before starting.
