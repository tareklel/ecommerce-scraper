# Memory

## Summary (entries 2026-02-24 to 2026-11-14)

Full entries: `archive/ecommerce-scraper/memory-archive.md` in the workspace repo
(`tareklel/price-comparison-workspace`), and this file's git history.

**What exists**
- A Scrapy crawler on ECS (eu-central-1) run through `run_crawler.py` (`--urls`, `--urls-source` local or `s3://` CSV, Ounass `--category`, `--plp-efficient`). Sites: Ounass, Level Shoes, Bloomingdale's (SFCC, no Zyte) and Cettire (see the log). Farfetch is blocked by Akamai (`tickets/blocked/`). `context/crawling_methodology.md` is the guide for onboarding a site, and `ecommercecrawl/constants/product_schema.py` is the field contract.
- Ounass goes through Zyte (the `crawler_api` layer). Product pages use `httpResponseBody`, and the browserHtml fallback is off (`OUNASS_PDP_BROWSER_HTML_FALLBACK`). Saudi hosts exit via Zyte geolocation `TR` (`CRAWLER_API_ZYTE_GEOLOCATION_BY_HOST`); prices don't change by exit country. Listings sort by `sortBy=onlineDateWithStock-desc`: the old sort hid ~18% of products each day (fixed 2026-10-23).
- Publish flow: the crawler uploads to `bronze/<env>/crawl-unverified/`. `lambda/bronze_manifest_verifier` checks hash, rows and the quality gate, then copies passing runs (success or degraded) to `crawls/`. It writes markers and a verified manifest (`{run_id, raw_json}` wrapper) and registers Glue partitions, including manifests of failed runs. Statuses: success / degraded / failed (aborted, startup_check, quality, verification, access) / killed (a `crawl-started/` record with no manifest). Every failure carries `meaning` / `what_to_do`. Docs `docs/crawl_run_status.md` and `docs/fail_quality_contract.md` are enforced by tests.
- Access layer (`ecommercecrawl/access.py`): access failures are retried in rounds after a cool-down, with a per-host `access` block and `kind: access` degradations. Principle: an access error is never a content error. Level Shoes listing fetches (plain `requests`) bypass this layer.
- Quality gate (`quality_gate.py`): blank-ratio threshold 0.2, per-site exclusions in `resources/quality_gate_exclusions.json`. Listing-extract rows have their own required-field rule.
- Images: `run_image_pipeline.py` (pending images from Athena → download → `download_log`), then `scripts/image_quality_checker.py` (→ `validated`). Blobs are at `bronze/<env>/images/by-hash/<sha256>.<ext>` with Content-Type set, served by CloudFront `/i/{sha256}.{ext}`. Order: crawl → dbt → image pipeline → checker finished → dbt. Gold needs images both downloaded and validated.
- Ounass PLP-efficient mode (`plp_efficient.py`, `plp_parity.py`; doc `docs/ounass_plp_efficient_crawl.md`; ticket `tickets/ounass_plp_efficient_crawl.md`): known products are refreshed from listings and the rest get product pages (Phase 2, 10k ceiling). Startup checks G1–G11: G8 (gold age, warns at 8 days) and stale-crawl (14 days) only warn, and G4/G11 need ≥ 20 products. Parity G9 runs per host, with on-sale top-ups. Steady state is ~300–400 requests a run. Registry rows are category listings with no brand; brand-scoped rows are a possible future direction.
- Discounts: `0` when there is genuinely no discount, `None` when not observed (silver coalesces nulls).
- CI/CD: GitHub Actions runs pytest, then builds the crawler image and pushes `sha-<7>` and `latest` (auto-deploy). `promote-crawler-image.yml` is for rollback, and `legacy-20260803` is a rollback tag. The laptop can't build images (company HTTPS inspection). Tests that need gitignored saved pages skip in CI. The crawl flow plan is in `tickets/cicd_pipeline.md` ("▶ Next steps") and `docs/cicd_architecture.md`. Schedule decided: daily for 7 days, then about weekly.
- dbt runs in AWS (scraper-pipeline ECS task, 2026-11-09) and on the laptop behind one shared S3 lock, renewed while dbt runs; the same wrapper refreshes the dev API cache whenever gold builds (the EventBridge rule stays off). The website API hides products without images.
- Crawl flow (built 2026-11-10/11, `infra/terraform/orchestration.tf`): Step Functions `ecommerce-scraper-crawl-flow-dev` with helper Lambda `ecommerce-scraper-crawl-flow-helper` (start check, registry reader writing `--urls-source` CSVs, verification wait, gate, summary). Order: registry seed + tests → parallel crawls (`CRAWL_RUN_ID`) → dbt run → image pipeline → quality checker → dbt test → `Run_refresh_cache` only after dbt test passes, so a failing test keeps the last good cache. `make crawl-flow` (`CRAWL_LIMIT`), edge cases in `docs/cicd_architecture.md`. Level Shoes skips gift-with-product items; `--limit` caps listing pages per seed URL (Ounass ignores it).
- Cettire (researched and built from 2026-11-14; `tickets/cettire_crawl.md`, `notes/2026-11-14-cettire-research.md`): pages sit behind DataDome (direct requests 403). Listings come from `search.cettire.com` called directly with the page-config `x-api-key` (now kept in Parameter Store, `docs/cettire_search_key.md`), one call of up to 1,000 per brand group; it returns `title` and `title_ar`, SAR prices, stock, colour, size and 3-4 images, so AR and EN rows come from search. Product pages (Zyte plain HTML) add only the full gallery and English copy; stock and sizes are never taken from them. Allowlist: 64 brands Level Shoes carries, a name-matched first pass (a reviewed brand mapping is still needed). Refused product pages are given up at once (`access_no_defer`). Cost estimate $1-3 a month. An affiliate programme exists (Partnerize); no feed confirmed.
- Terraform state: both repos in this repo's versioned S3 state bucket (scraper-pipeline under its own key), S3 lock files (`use_lockfile`), Terraform 1.10+ required.
- Secrets: one Secrets Manager secret `ecommerce-scraper/env` with Make helpers. Never put values in `.env` or Terraform.
- Run plumbing (2026-11-13): EventBridge Scheduler starts the flow at 02:00 Asia/Dubai (`aws_scheduler_schedule.crawl_flow`, `make schedule-status|on|off`); a summary email goes to SNS `ecommerce-scraper-crawl-flow-runs` after every run (address only in gitignored `infra/terraform/local.auto.tfvars`); `make crawl-flow STOP_AFTER=crawls` for crawls-only tests; `make crawl-flow` refuses when the dbt image lacks the newest registry CSV (`scripts/check_crawl_registry.py`, `SKIP_REGISTRY_CHECK=1`); crawls that raise and write nothing fail as `crash` with `first_error` in the manifest.

## Log (last 10 entry days, newest first)

## 2026-11-27 - Cettire: Zyte gets through with a mobile device (user test)
- User's Zyte request with `device: "mobile"`, `geolocation: "AU"`, `followRedirect: true` returned a product page that the crawler's requests got 520 on. Recorded in `tickets/cettire_crawl.md` and the key doc's open items, with what is still untested (no AU, page contents, listings, volume). No code change; product pages stay off.
- Memory: 2026-11-14 moved to the workspace archive; its lasting Cettire facts are in the summary.

## 2026-11-24 - Product brief names the product
- `context/product-brief.md`: "[Name TBD]" is now Kayaliya (كاياليا, kayaliya.com), decided 2026-11-20 (`../price-comparison-web/tickets/name_and_domain.md`). Docs only.

## 2026-11-23 - Cettire product pages switched off (temporary, switchable)
- 11-21/22/23 runs: Cettire degraded, not failed: ~15.8k rows from search each night, but every product page refused by Zyte (520 `download/temporary-error`, 4 attempts each, unbilled); 11-21 and 11-22 flows took 6h18. Search key fine (`51200e93`).
- User decision: listings keep running, product pages off until Zyte gets through. New Terraform variable `cettire_fetch_product_pages` (`"false"`) sets `CETTIRE_FETCH_PRODUCT_PAGES` on the crawler task. Targeted apply 1 added / 3 changed / 1 destroyed (task revision 3; flow, helper and flow IAM policy follow the revision; policy text checked identical). Switch back: `"true"` + same targeted apply (`tickets/cettire_crawl.md`). Re-plan clean; dev test (`--limit 1`, uploads off) on revision 3: 40 rows, pass, no Zyte requests (its 20 products were all known, so the off path itself rests on the unit tests).
- Found: DEBUG logging printed the Parameter Store reply, so the Cettire search key was in CloudWatch in plain text on every run since 11-20.

## 2026-11-23 - Schedule +2 days; AWS SDK loggers kept at INFO
- User: 2 more daily runs, 11-24 and 11-25 (`crawl_schedule_end_date` 2026-11-25T20:00Z; targeted apply 0/1/0; schedule ENABLED, ends 2026-11-26 00:00 Dubai). `tickets/cicd_pipeline.md` step 6 updated.
- `settings.py` holds `botocore`/`boto3`/`s3transfer` at INFO whatever `LOG_LEVEL` is, so the search key no longer reaches CloudWatch (test fails without the fix; 689 pass). Old copies in `/ecs/ecommerce-scraper` not deleted: 7-day retention clears them by 11-30.

## 2026-11-21 - Cettire: Zyte blocked on every page; product pages now cut off after 20 refusals
- 11-20 run: 0 of 2,000 product pages (all Zyte 520), run 6 h (flow finished 04:19, not ~23:30). Probe 11-21: a product page refused with no exit country, SA, AE, GB, another country path and browser mode; Cettire `robots.txt` and Ounass fine, so Cettire blocks Zyte, likely after 3 nights of 2,000 pages (11-16/17/18 got ~99.5%). Search service still accepts the stored key. 5,956 of 8,160 products already have descriptions.
- New `CETTIRE_PDP_STOP_AFTER_REFUSALS` (default 20): after that many refused pages in a row the spider stops product pages for the run; `StoppedProductPagesMiddleware` (`ecommercecrawl/middlewares.py`, priority 50) drops already-queued ones before download; products are written from search data. 5 new tests.

## 2026-11-20 - Daily trial extended by 3 runs, regroup 2026-11-24
- User decision after the trial's errors: daily runs 2026-11-21 to 2026-11-23 (`crawl_schedule_end_date` 2026-11-23T20:00Z in `infra/terraform/variables.tf`, targeted apply 0/1/0, status confirmed). Weekly-or-daily decided with the user on Tuesday 2026-11-24 (`tickets/cicd_pipeline.md` step 6).

## 2026-11-20 - Level Shoes details and Arabic size/fit captured again
- Level Shoes changed its product page: detail bullets are now `<div data-testid="lineitems-item">` (was `<li>`), and the Arabic size/fit heading is `المقاس والتصميم` (was `المقاس والملاءمة`). So dev silver had details for 17 of 2,339 products and Arabic size/fit for none. `extract_product_details` in `level_rules.py` reads both layouts and headings; 2 tests on hand-written HTML in the new layout. Checked on live en/ar pages; takes effect from the next crawl. Old saved test pages (`tests/levels_html_fixtures/pdp/`) are all the old layout.

## 2026-11-20 - Cettire search key kept in Parameter Store, renewed by the spider
- The 11-20 Cettire run failed (`crash`, 0 rows): the key was never stored and Zyte got 520 on all 12 tries to read it from a page. Spider now reads `/ecommerce-scraper/cettire/search-api-key` (SecureString); missing/rejected -> read via Zyte and saved back; Zyte refused -> run fails; saved fails -> run goes on `degraded` (new kind `setup`). `CETTIRE_SEARCH_API_KEY` setting removed (user design).
- Crawler task role may read/write that one parameter (`aws_iam_role_policy.ecs_task_cettire_search_key`, applied 1/0/0, user-approved). 7 new tests, 674 pass. Ticket, `docs/cicd_architecture.md`, `docs/crawl_run_status.md` updated.
- Then Zyte refused every Cettire page (listing plain + browser fallback `e2e9dae`, a product page, TR geolocation). First key loaded by hand from the 11-14 probe pages (user-approved, fingerprint `51200e93`); still accepted: dev test run read it from Parameter Store, no Zyte, 38 rows, quality pass. Next proposed: renew from saved product addresses, fingerprint log.
- Built: renewal tries up to 10 product addresses saved by the last run (`s3://<bucket>/resources/cettire/key-pages.json`, no new IAM: bucket write already allowed) before the listing pages, plain then browser; key logged by fingerprint only. 681 tests pass.
- Documented in `docs/cettire_search_key.md` (user: "i dont want to guess it next time"); `context/AGENTS.md` now requires that doc to change with the behaviour.

## 2026-11-19 - Affiliate and legal check deferred until after launch
- User decision: no affiliate or terms research before launch ("do things first, ask forgiveness later"); launch, get traffic, then ask affiliate networks for feeds, competitors first, then crawled retailers. Only our own legal pages stay before launch (website ticket `about_and_legal_pages.md`, suggested contents listed). `tickets/affiliate_and_legal_check.md` rescoped.

## 2026-11-19 - Run email: counts to check day on day, Zyte's real cost
- `lambda/crawl_flow_helper/handler.py` summary: "Counts to check" at the top (per site, crawled rows / in gold / with images fell >10% since the previous full run, or Zyte cost more than doubled and >$1; warning only); each full run's counts saved to `bronze/dev/crawl-flow/run-counts/` (`--limit` and crawls-only runs neither compared nor saved). Zyte section: real cost, requests and 520s per site from Zyte's Stats API, key in Parameter Store `/ecommerce-scraper/zyte-stats/` (user choice over Secrets Manager); any failure is one "not available" line, never a failed email.
- Rule: no estimated costs in the email (user: "i dont want estimates"). "Site says" totals deferred. Deployed and checked live (Cettire $0.26 / 2,492 requests, Ounass $0.14 / 314 over the 11-19 run); fix: Zyte sends numbers as decimal strings. Ticket `tickets/run_count_reconciliation.md`; doc `docs/cicd_architecture.md`; 15 new tests.

## 2026-11-19 - Cettire images: the image task ran a July image; flow now runs only `latest`
- The 11-19 run still had Cettire 15,944 in gold, 0 with images: the image task family had a revision 3 registered by hand on 2026-07-30 with `ecommerce-scraper:schema-v2-dev-20260730`, and the flow (family name, no revision) ran it every night, so `ba26ece` never ran. Terraform showed no changes (its revision 2 is on `latest`). Revision 3 deregistered (user-approved); an images-only run picked up the 30,458 Cettire images on revision 2 / `latest`.
- Guard (`tickets/run_latest_image_only.md`): state machine names exact Terraform task revisions; helper `start` refuses unless each is ACTIVE and on `:latest` (`FLOW_TASK_DEFINITIONS`, IAM `ecs:DescribeTaskDefinition`); refusals now emailed (`NotifyRefused`). Rule added to `context/AGENTS.md`; `docs/cicd_architecture.md` updated. 653 tests pass. Applied 2026-11-19 (user-approved, 0/3/0); live `start` invoke passed.

## 2026-11-18 - Launch report moved to the workspace repo
- `notes/2026-11-13-state-of-price-comparison.md` now lives in `tareklel/price-comparison-workspace` as `launch/2026-11-13-state-of-price-comparison.md`, next to the live tracker `launch/LAUNCH.md`; a pointer stays here so ticket references still resolve.

## 2026-11-18 - Memory compacted
- Summary of entries up to 2026-11-03 plus the last 10 entry days; older entries moved word for word to the workspace repo's `archive/ecommerce-scraper/memory-archive.md`. `context/AGENTS.md`: entries of 1–3 lines, and the 10-entry-day roll-over rule.

## 2026-11-18 - Bloomingdale's listings page through the Commerce API again
- The storefront rebuild (PWA Kit) removed the "show more" / `Search-UpdateGrid` paging; the old cgid regex picked a promo block's ID and each listing gave only its first ~28 products (English shoulder bags: 27 of 457), which is why scraper-pipeline's 14-day unseen rule left 64 Bloomingdale's products in gold.
- Spider now: page settings (`commerceAPI.parameters`) + listing cgid (`refine_1=cgid%3D...`) -> anonymous guest login (PKCE authorize 303 -> token, via `/mobify/proxy/api`; user-approved probe) -> `product-search` 48 per call until `total` -> product pages built as `<brand>-<English name>-<productId>.html` (matched the site's links 25/25 in both languages). First batch still crawled from the page; any failure is a run degradation. New generic hook: a spider's `run_degradations` reach the manifest. Dead UpdateGrid rules removed.
- Local crawl `--limit 2`: 99 rows (was 27 for the whole listing), quality pass. Tests: 646 pass. Ticket `tickets/done/bloomingdales_crawl.md` has a dated update.

## 2026-11-18 - Cettire images: the downloader rejected the site
- The 2026-11-17 run email showed Cettire 15,832 rows in gold, 0 with images. `ecommercecrawl/image_downloader.py` `SITE_ALIASES` had no `cettire`, so `normalize_site` raised and every Cettire job was logged `skipped_invalid` / `invalid_job_input` (61,185 since 2026-11-15). Those log rows carry no site, key or URL, so they never match the pending-images query and the same jobs came back every run.
- Added `cettire` to `SITE_ALIASES` and a Cettire branch in `get_site_headers` (plain user-agent, `https://www.cettire.com/` referer). The CDN (`d3vfig6e0r0snz.cloudfront.net`) served a direct download (200, JPEG), checked through `download_one_job` locally.
- Tests: `normalize_site("cettire")`, the Cettire headers, and a guard that every site in the crawl flow helper's `SITES` is accepted by `normalize_site`.
- The next image step downloads the whole backlog (61,185 images); the step's timeout is 3 hours.
- Found, not fixed yet: the crawl flow helper's `check_crawl` reads `bronze/.../manifests/.../data.json` as the manifest, but the verifier writes `{run_id, raw_json}` with the manifest as a JSON string inside `raw_json`. So every published crawl shows `success` (never `degraded`), with no degradations and no row count ("? crawled" in the email).
- Fixed the same day: `check_crawl` unpacks `raw_json` before reading `run_status`, `degradations` and `artifacts.rows`; the test now uses the verifier's wrapped format. Helper Lambda deployed (code only); a live `check_crawl` on the 2026-11-17 Cettire run returned `rows: 15588`. None of the 35 manifests since 2026-11-10 was `degraded`, so no degraded run had been hidden.

## 2026-11-17 - Run email says why a dbt step failed
- The 2026-11-16 run email only said "FAILED at dbt test: exit code 1 (Essential container in task exited)". The real cause (`test_silver_product_image_download_status_gallery_contract`, 30,673 rows) was only in the dbt task's CloudWatch log.
- `lambda/crawl_flow_helper/handler.py`: when a dbt-task step fails (`seed_registry`, `dbt_run`, `dbt_run_images`, `dbt_test`, `refresh_cache`), the summary reads that task's log stream (`/ecs/price-comparison-dbt-dev`, `dbt/dbt/<task id>`; task ID from the caught failure or `last_task`) and adds a "dbt said:" block: each error block after dbt's "Completed with ..." line (up to 10; warnings left out), the `Done. PASS=...` line, and a CloudWatch link. If dbt printed no errors (e.g. the dbt lock timed out), it shows the log's last 5 lines. A log read error becomes the line itself and never fails the summary.
- Parser built against dbt 1.12's real output (`[ERROR]: in test X (path)` then `Got N results, ...`), checked against the 2026-11-16 log.
- `infra/terraform/orchestration.tf`: `local.dbt_log_group`, `DBT_LOG_GROUP` env var, and a `ReadDbtTaskLog` statement (`logs:GetLogEvents` on that log group only).
- Tests: 5 new in `tests/test_crawl_flow_helper.py`. `docs/cicd_architecture.md`: an edge-case row and a decision-log row.
- Found while deploying: the per-site counts change (`01c4950`, its `GOLD_TABLE` env var and Glue grant) had been committed but never applied, so the 2026-11-16 email had no counts lines. Both applied 2026-11-17 in one targeted apply (helper Lambda + its policy); a live `summary` invoke with the 2026-11-16 failure showed the dbt error block and the counts.

## 2026-11-16 - Level Shoes listing fallbacks; per-site counts in the run email; Cettire switched on
- Level Shoes: gender falls back to the listing being crawled ("Women") before the PDP breadcrumb (Arabic "للنساء", 228 products); category/subcategory fall back to the listing URL slugs (`/women/bags/tote-bags` -> bags | tote-bags) when neither the listing analytics nor the PDP breadcrumb has them (Bottega Veneta Large Cabat tote: breadcrumb Home > Women > product). Checked live in both languages. scraper-pipeline asked for the `level-shoes,bags,tote-bags` map row.
- Run email: each crawl line shows its rows (manifest `artifacts.rows`, via check_crawl); after the full dbt run, per site "crawled -> in gold -> with images" from `gold_product_serving_latest`. Helper role gains Glue read on that table (user-approved). Plan 0 added, 2 changed; the apply was blocked by the session's permission classifier, so it waits for the user.
- Cettire: scraper-pipeline `ce5ca1c` switched its two registry rows to TRUE (user request) after checking the helper is deployed with `cettire` and both images are current; first scheduled Cettire run 2026-11-17 02:00 Dubai. Terms-of-use item removed from `tickets/cettire_crawl.md` (user).
- 628 tests pass.

## 2026-11-16 - Cettire product pages switched on by default
- User decision ("just flip it"): `CETTIRE_FETCH_PRODUCT_PAGES` defaults to true, with efficient mode and `CETTIRE_MAX_PRODUCT_PAGES` 2000/run. The 2,000 cap was the agent's own choice (not asked for); the user agreed to it once told why: an uncapped first night is ~16 h and holds the whole crawl flow (dbt, cache refresh, email) for all sites. First Cettire night: all products from search plus up to 2,000 pages; ~4 nights for the one-off pass, then only new products. Env var false turns pages off.

## 2026-11-16 - Cettire efficient mode (step 2) built
- Spider reads scraper-pipeline's `gold_cettire_pdp_known` from S3 (`dbt/<env>/gold_cettire_pdp_known/`, gzipped tab-separated `portal_itemid`, `image_urls_json`, `\N` = null; verified the format with a throwaway Athena table): known products skip the page and get their stored gallery; others get a page up to `CETTIRE_MAX_PRODUCT_PAGES` per run (default 2000); unreadable list = no pages. Default `CETTIRE_FETCH_PRODUCT_PAGES` still false. 7 new tests, 601 pass.
- scraper-pipeline: `gold_cettire_pdp_known` (TEXTFILE table) + contract test, built in dev (empty) through the lock.

## 2026-11-16 - Crawl-flow helper redeployed with Cettire
- Targeted Terraform apply of `aws_lambda_function.crawl_flow_helper` from main `4128583` (user-approved): 0 added, 1 changed, 0 destroyed; the deployed handler lists `cettire` in `SITES`. Run from the cloud session with a downloaded Terraform 1.17.2 and the locked providers from releases.hashicorp.com (the provider registry is blocked there). Cettire registry rows are still inactive.
- Not built yet: efficient mode for Cettire product pages. Note for it: search-only rows carry 3-4 `image_urls`, which would replace a 4-6 image product-page gallery downstream (the dim keeps only null galleries), so known products need null `image_urls` (or the full gallery) in efficient mode; `text` null is already retained downstream.

## 2026-11-15 - Cettire product pages off by default
- User decision: the next Cettire crawl takes every allowlisted product (~7,800) but no product pages. New setting `CETTIRE_FETCH_PRODUCT_PAGES` (env var, default false): rows come from the search service only, so no Zyte product-page requests, no `text`, 3-4 images per product. Turn on only with the efficient crawl (pages for new products only). 2 new tests; 594 pass.

## 2026-11-15 - Cettire joins the crawl flow (code), registry English only
- User decision: Cettire registry rows are English only, one per listing; no stand-in Arabic row. The spider still writes EN and AR rows from each URL; Arabic quality is downstream's job, and a future switch could turn AR rows off.
- `cettire` added to the crawl flow helper's `SITES` (urls_source); test and `docs/cicd_architecture.md` updated (42 helper tests pass). **Needs a targeted Terraform apply of the helper Lambda before any active Cettire registry row**, else the flow fails for every site.

## 2026-11-15 - Cettire spider merged to main; image built
- PR #1 merged by the user. The `Crawler image` workflow on main passed (tests, including the Zyte-dependent ones that could not run in the cloud container, then image build). The crawler image now contains the `cettire` spider; the crawl flow still won't crawl it until scraper-pipeline's registry has Cettire rows and `lambda/crawl_flow_helper/handler.py` has a `cettire` site entry.
- Downstream (scraper-pipeline): ticket, seeds and silver models on main; dev `bronze_cettire_raw` holds the 40-product test partition; shared-model wiring is on branch `claude/cettire-onboarding-shared` (checked read-only against dev, not merged; merging puts the test products into dev gold).

## 2026-11-15 - Cettire silver models proven in dev on the live-test rows
- With the user's go-ahead ("all three"): the `live3` test output (40 products) was attached as a partition of `price_comparison_dev.bronze_cettire_raw` from `probes/dev/cettire/bronze_sample/`, the changed seeds were loaded and the four Cettire silver models and their tests were run through scraper-pipeline's dev lock; all passed, no unmapped brand/category/gender. The crawler's output shape is therefore confirmed readable downstream, including the numeric `price_discount` and the null `was_price` at full price.
- Dev silver holds 40 Cettire test products; nothing in gold. Details in scraper-pipeline's `ticket/onboard-cettire.md` (branch `claude/cettire-onboarding-dev-table`, not yet merged).

## 2026-11-15 - Cettire downstream: seeds and silver models merged; dev bronze table created
- In `tareklel/scraper-pipeline-pc`, the user merged the ticket (PR #1) and the seeds + four Cettire silver models (PR #2) into `main`. The models read `bronze_cettire_raw`, and the crawl flow runs a full `dbt run`, so this session created `price_comparison_dev.bronze_cettire_raw` (empty) with the user's AWS sign-in and checked the four models' SQL read-only against dev (valid, 0 rows).
- Still open downstream: `dbt seed` in dev, the prod table, the shared models that list sites, registry rows (last), and in this repo a `cettire` entry in `lambda/crawl_flow_helper/handler.py`'s site table plus bronze partition registration for the new table.
- This repo's PR #1 (the spider) is still open.

## 2026-11-15 - Cettire downstream onboarding started: seeds
- In `tareklel/scraper-pipeline-pc`, branch `claude/cettire-onboarding-seeds` (stacked on the ticket branch, no PR yet): Cettire rows in the site, slug (`ct`), brand (64), category (4) and gender seeds. CSV only; not loaded with `dbt seed`, no model reads them. Next there: the per-site silver models copied from Level Shoes, then the shared models that list sites.
- This session is subscribed to ecommerce-scraper PR #1 and scraper-pipeline-pc PR #1.

## 2026-11-15 - Cettire pull requests opened
- ecommerce-scraper PR #1 (spider, research, ticket) and scraper-pipeline-pc PR #1 (onboarding ticket), both to `main`, not merged. Merging the crawler PR builds a new image; it does not start crawling Cettire because the registry has no Cettire rows.

## 2026-11-15 - Cettire ticket tidied; open items recorded
- `tickets/cettire_crawl.md` cut from about 650 to about 290 lines: decisions rewritten to the current set, the five probe write-ups and the original phase-0 checklist / build plan replaced by a short research summary pointing to `notes/2026-11-14-cettire-research.md`, new "Other open items" (pull requests, tote bags by brand, affiliate application, terms of use unread, Arabic descriptions, probe data in the dev bucket, AWS role for agent sessions), "Done when" and "Open questions" rewritten. The research note gains section 11a on the live test runs. No finding was dropped: all are in the note.
