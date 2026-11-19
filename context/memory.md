# Memory

## Summary (entries 2026-02-24 to 2026-11-04)

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
- Terraform state: both repos in this repo's versioned S3 state bucket (scraper-pipeline under its own key), S3 lock files (`use_lockfile`), Terraform 1.10+ required.
- Secrets: one Secrets Manager secret `ecommerce-scraper/env` with Make helpers. Never put values in `.env` or Terraform.

## Log (last 10 entry days, newest first)

## 2026-11-19 - Run email: counts to check day on day, Zyte's real cost
- `lambda/crawl_flow_helper/handler.py` summary: "Counts to check" at the top (per site, crawled rows / in gold / with images fell >10% since the previous full run, or Zyte cost more than doubled and >$1; warning only); each full run's counts saved to `bronze/dev/crawl-flow/run-counts/` (`--limit` and crawls-only runs neither compared nor saved). Zyte section: real cost, requests and 520s per site from Zyte's Stats API, key in Parameter Store `/ecommerce-scraper/zyte-stats/` (user choice over Secrets Manager); any failure is one "not available" line, never a failed email.
- Rule: no estimated costs in the email (user: "i dont want estimates"). "Site says" totals deferred. Ticket `tickets/run_count_reconciliation.md`; doc `docs/cicd_architecture.md`; 14 new tests.

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

## 2026-11-14 - Cettire: where things stand and what is next
- **State:** `cettire` spider (step 1: search-service listings + product pages) is built, on branch `claude/project-viability-assessment-sxolr2`, not on main, so not in the crawler image. Proven in three live `--limit 1` runs in the dev crawler task (this branch's code unpacked over the image, bronze uploads off, outputs under `probes/dev/cettire/live1..3`). Nothing has been written to bronze.
- **User decision:** do the downstream onboarding in scraper-pipeline first, then build step 2 (efficient crawl) on a gold export like Ounass. Not the interim "known products file" option.
- **Next steps, in order:** (1) scraper-pipeline onboarding per `ticket/onboard-cettire.md` on branch `claude/cettire-onboarding-ticket` of `tareklel/scraper-pipeline-pc` (unmerged; registry rows last); (2) merge this branch so the image has the spider; (3) first real crawl into bronze; (4) step 2 on a gold export; (5) reviewed brand mapping to replace the name-matched allowlist.
- **Open small items:** stored search key (infra), completeness shortfall as a manifest degradation, confirm the stock finding in a browser, whether given-up product pages should degrade the run.
- **Working notes for a future session:** this cloud session cannot reach `cettire.com` or Zyte directly; all site access ran inside the dev ECS task via AWS SSO (device login, 1-hour sessions, `AdministratorAccess` is the only role). The agent safety check blocked a direct whole-category search call and, once, the first direct search call until the user gave explicit permission.

## 2026-11-14 - Cettire third live run confirms the fixes
- `live3` (`--limit 1`): 7 min (was 40), 80 rows / 40 products, no duplicates, no out-of-stock from the page, quality gate pass; 35 of 40 product pages fetched, 5 refused and written from search data. Product pages ran at about 7.5 s each, so a full first pass of about 7,800 would take roughly 16 hours. Next: step 2 (skip product pages for known products).

## 2026-11-14 - Cettire second live run succeeded; three fixes
- Live run 2 (`--limit 1`, output under `probes/dev/cettire/live2/`): quality gate pass, 40 products, 39 of 40 product pages fetched, key read from the site in about 3.5 min, run took 40 min.
- Fixed after it: (1) duplicate rows when a product page was set aside for a retry round (the errback wrote rows each time; `AccessDeferred` now writes nothing); (2) new `access_no_defer` request flag in `ecommercecrawl/access.py`, set on Cettire product pages so a refused page is given up at once instead of holding the run through two 15-minute cool-downs (documented in `docs/ounass_plp_efficient_crawl.md` section 5); (3) stock and sizes are no longer taken from the product page, which is rendered for the site's default region and marked 10 of 40 in-stock products sold out. 592 tests pass (15 skipped in the cloud container).
- Third live run started to confirm the fixes.

## 2026-11-14 - Cettire allowlist needs a real brand mapping (user note)
- Ticket gains "Brand allowlist: rule, and the mapping work it still needs". Rule: crawl Cettire only for brands Level Shoes carries. The current `resources/cettire_brand_allowlist.csv` is a first pass: name-matched with three aliases, from shoulder-bag brands only, a frozen snapshot of dev gold, not tied to `dim_map_brand`. Needed and not yet planned: Cettire's full brand list, a reviewed Cettire -> canonical brand mapping in scraper-pipeline, the allowlist derived from it, and a report of unmapped brands.

## 2026-11-14 - Cettire first live run failed at the key fetch; fetch made more patient
- Live test (`--limit 1`, dev crawler task running this branch's code unpacked over the image, bronze uploads off, output under `probes/dev/cettire/live1/`): the spider had no stored key, Zyte refused all 4 plain fetches of the key page (520), run ended `failed` / `crash` with the error named. Nothing crawled.
- Key fetch now rotates over three Cettire pages (`API_KEY_PAGE_URLS`), 12 attempts with a 5 s pause; 2 new tests (42 Cettire tests pass). Second live run started; result not yet known.
- scraper-pipeline: ticket `ticket/onboard-cettire.md` pushed on branch `claude/cettire-onboarding-ticket` of `tareklel/scraper-pipeline-pc` (not merged).

## 2026-11-14 - Cettire spider, step 1 (full crawl), not yet run live
- New `cettire` spider (`spiders/cettire_crawl.py`, `rules/cettire_rules.py`, `constants/cettire_constants.py`), registered in `run_crawler.py`; seeds `resources/cettire_urls.csv`, allowlist `resources/cettire_brand_allowlist.csv` (64 brands); settings `CETTIRE_URLS_PATH`, `CETTIRE_BRAND_ALLOWLIST_PATH`, `CETTIRE_SEARCH_API_KEY`; quality-gate exceptions for `cettire` (`was_price`, `primary_label`, `text`, `designer_color`).
- Flow: listing URL -> search-service query; one facet call, then one call (up to 1,000) per group of allowlisted brands, direct via `requests`; each product page through Zyte plain HTML; two rows per product (EN, AR). Field mapping table is in the ticket's "Build status".
- Choices: `price_discount` computed, 0 at full price; AR rows have no `text`; `text.description` is None (Cettire has no prose); a failed product page still writes the search rows; search key optional, re-read from a page through Zyte when missing or rejected.
- 40 new tests with hand-written fixtures (no site data committed); full suite 587 passed, 15 skipped in the cloud container (scrapy-zyte-api would not build there on Python 3.13). Rules also checked by hand against saved real responses.
- Not done: live run, optional key secret (infra), scraper-pipeline registry and mappings, shortfall as a manifest degradation, step 2 efficient crawl.

## 2026-11-14 - Cettire research note
- Added `notes/2026-11-14-cettire-research.md`: the full research record (architecture, access matrix, PDP and PLP findings, search-service request and 51 response fields, paging and brand-group tests, catalogue statistics, brand overlap tables with Level Shoes and Ounass, all 319 shoulder-bag brands, affiliate check, cost estimate, compliance notes, decisions, open questions). The ticket links to it.
- Correction after adding two brand aliases: 223 Cettire shoulder-bag brands (3,605 products) are on neither Level Shoes nor Ounass (earlier figure 225 / 3,698). Cost is $1-3 a month with a daily run, not per day.

## 2026-11-14 - Cettire cost estimate
- User accepted the 64-brand Level Shoes allowlist as is. Estimate for about 7,800 products: daily listing refresh has no Zyte cost; product pages via Zyte plain HTTP are $1-10 one-off for the first run and about $0.15-1.30 a month after (about 1,000 new products a month); overall about $2-11 one-off and $1-3 a month. Zyte tier for Cettire and tote-bag counts are assumptions. Details in `tickets/cettire_crawl.md`.

## 2026-11-14 - Cettire catalogue analysis; allowlist to Level Shoes brands
- Cettire's size is brand breadth (319 shoulder-bag brands, thin stock, colours as separate products), not expired stock; most of the long tail is accessible brands, 225 brands on neither Level Shoes nor Ounass.
- User decision: allowlist Cettire to brands Level Shoes carries. 64 of Level's 92 bag brands are on Cettire and hold 4,175 of 9,506 shoulder bags; totes not counted (estimate about 3,600). Brand table is in `tickets/cettire_crawl.md`.

## 2026-11-14 - Cettire: API key handling and product-page plan
- User decision: store the search-service API key and reuse it; refresh from a page (one Zyte fetch) only when it is rejected, then retry once.
- Proposed (not yet agreed): Ounass-style split, search service as the listing phase every run, product pages via Zyte plain HTML only for new products.

## 2026-11-14 - Cettire route chosen: search service, brand groups of up to 1,000
- User decision (no affiliate feed found): crawl via the search service with `pageSize: 1000`.
- `vendorQuery` filters by brand name and accepts several brands; Shoulder Bags has 319 brands, none over 333 products, so 11 brand-group calls cover about 9,500 products (about 22 calls per run with Tote Bags). Three groups tested: correct brands and type, no duplicates, but about 1.5% fewer products than `totalNumber` (cause unknown).
- Planned shape is in `tickets/cettire_crawl.md` (fifth probe). Build not started.

## 2026-11-14 - Cettire affiliate feed check
- Web search only: Cettire has an affiliate programme (Partnerize about 5% / 30-day cookie, BlueAff; FlexOffers closed). No public listing mentions a product feed or Saudi publishers; a feed can only be confirmed after approval. Recorded in `tickets/cettire_crawl.md`; applying is the user's step.

## 2026-11-14 - Cettire fourth probe: direct requests from AWS
- User corrected an assumption: only Ounass goes through Zyte; Level Shoes and Bloomingdale's are fetched directly.
- Direct from the dev ECS task (user-approved): Cettire product and listing pages return 403 (DataDome); `search.cettire.com` answers 200 with the page-config `x-api-key`, and with `langCode: "ar"` returns both `title` and `title_ar`.
- Paging by `currentPage` is unreliable (repeats, always echoes page 0); the site uses a "Load more" button. `pageSize: 1000` works in one call. A `pageSize: 10000` call was blocked by the agent session's safety check and not run.
- The safety check treated direct search-service calls as unauthorized access; the ticket carries a compliance note and says to check for an affiliate feed first.
- User rejected browser rendering for listings on cost grounds.

## 2026-11-14 - Cettire third probe: PLP and PDP
- 7 more Zyte requests. Plain-HTML listing pages contain no products. The grid comes from a POST to `search.cettire.com/search-ai/pro-search/api/aiRecommendForProduct` (96 per page, `x-api-key` from the public page config), captured through a browser-rendered listing.
- Each listing item is complete: `title` and `title_ar`, vendor, category EN/AR, `sa_sar_price_f` / `sa_sar_compare_at_price_f`, stock, colour, size, 3-4 images. So Arabic names are available from listings.
- Saudi women's Shoulder Bags about 9,500 and Tote Bags 8,216 (about 17,700 products; ~185 listing pages).
- Plain-HTML product pages are complete (3 checked) and agree with the listing; they add full gallery and description.
- Open for the user: read listings by browser render with network capture, or by calling the search service directly.

## 2026-11-14 - Cettire decisions: English first, plain fetch, Zyte only temporarily
- User decisions, recorded at the top of `tickets/cettire_crawl.md`: build English only for now (Arabic deferred); use the plain HTML fetch like Ounass (`http_response`), no browser rendering.
- **Zyte for Cettire is temporary.** It was used only because the cloud session could not reach `cettire.com` directly; a direct (non-Zyte) request has never been tested. Test direct access from a laptop and from AWS as soon as possible, and if it works run the Cettire crawler without Zyte. Do not treat "Zyte is necessary" as established.

## 2026-11-14 - Cettire second probe: Arabic comes from the site's API
- 4 more Zyte requests (retries on 520, network capture). Browser-rendered product pages call `api.cettire.com/graphql` and get a `lang: ar_SA` object with Arabic title and description; server-rendered HTML always requests `en_US`, cookies make no difference.
- Saudi prices include duties and taxes (`priceIncludeTax: true`). Product sitemap is ~480,000 URLs with no category or gender. Listing grid source still unknown (capture limit hit).
- Ticket now lists crawl options A (browser per product), B (HTML + translate downstream), C (GraphQL API; `robots.txt` disallows `/graphql` on the main host, user decision needed).

## 2026-11-14 - Cettire first probe (through Zyte, from the dev crawler task)
- 16 Zyte requests in four runs of the `ecommerce-scraper` ECS task with a command override (user-approved); pages kept under `probes/dev/cettire/` in the bucket. Results are in `tickets/cettire_crawl.md`.
- Site: Next.js on Reaction Commerce GraphQL, CloudFront, DataDome. Saudi is the `/sa/` path; language is the `spc-lng` cookie.
- Zyte HTTP mode is unreliable (pages/sitemaps 4 of 12, rest `520 Website Ban`); browser mode 2 of 2. Direct requests not tested.
- Product pages carry everything in `__NEXT_DATA__` (English), including the SAR price and was-price under `regionCode: "sa"`. Listing grids are loaded by the browser, and Arabic product names appear only after browser rendering.
- Open: listing source (GraphQL API vs browser), Arabic without a browser, Zyte success rate and cost.

## 2026-11-14 - Cettire ticket: AR/EN/SA confirmed by the user
- `tickets/cettire_crawl.md`: the user confirmed Cettire has Arabic, English and a Saudi storefront, so the "no Arabic" decision section is removed; the probe still has to find how language is selected and whether AR and EN share a product ID.
- Probe still not run: the user declined a cloud environment allowing `cettire.com`, so it must run from the laptop or another session.

## 2026-11-14 - Ticket: Cettire crawler (Saudi handbags, AR + EN)
- Added `tickets/cettire_crawl.md` (open, not started). Reason: Bloomingdale's returns 59 products for the two bag listings against ~3,100 (Ounass) and 2,140 (Level Shoes) in flow run `d66af788`.
- Phase 0 probe comes first and must answer whether Zyte is necessary (direct requests from laptop, from AWS, and at crawl volume), how the Saudi storefront/SAR/language are selected, and whether an Arabic storefront exists (user decision if not).
- No site fact is verified: the cloud session could not reach `www.cettire.com` (its own network policy).
- Found while checking run `d66af788`, not yet fixed: 65 Level Shoes products with blank category never reach gold; 186 stale Arabic-only Bloomingdale's rows (July/August) remain in gold.

## 2026-11-13 - CI/CD step 6 applied: daily schedule; mapping-gaps line in the email
- `aws_scheduler_schedule.crawl_flow` starts a full flow run at 02:00 Asia/Dubai daily, end_date 2026-11-20T20:00Z (7 runs, 2026-11-14 to 20), no retries; role `ecommerce-scraper-crawl-flow-scheduler` can only `states:StartExecution` the flow (user-approved). Terraform ignores `state`; `scripts/crawl_schedule.py` + `make schedule-status|on|off` (+ 3 tests). Scheduled runs skip the `make crawl-flow` registry check.
- Summary email adds "Mapping gaps: N brand spelling(s) to review; M product drop(s) from gold" from scraper-pipeline's `silver_mapping_gaps` when the full dbt run happened; a failed query never fails the summary. Helper role gained Glue read on that table (user-approved). Checked by invoking the helper: 0 to review, 2 drops.
- Targeted apply 3 added, 2 changed; re-plan clean. `tickets/crawl_scheduler.md` marked superseded. 562 tests pass. Next: review the 7 daily runs, then weekly.

## 2026-11-13 - Crawls-only test runs; step 5 done
- `make crawl-flow CRAWL_LIMIT=1 STOP_AFTER=crawls` (flow input `stop_after: "crawls"`, always a string from the helper's start so the Choice can read it): the `AnyPublished` Choice goes straight to `Summary`; subject "SUCCEEDED (crawls only): n/m crawls published". A short run without it takes about 20 min, mostly dbt and ECS start-ups. Targeted apply (helper + state machine, 0 added, 2 changed). 5 new tests (553 pass).
- `CRAWL_LIMIT=1` run `34994259` on the 5b crawler image succeeded (3/3, cache refreshed, email sent): step 5 done.
- Ticket step 11 now points at `../price-comparison-web/tickets/cicd.md` (website CI/CD planned by that session with the user).

## 2026-11-13 - CI/CD step 5b: crawler crashes reported as `crash`
- `PostCrawlPipeline` attaches `FirstErrorRecorder` (root log handler, ERROR with exc_info) from spider_opened to spider_closed; the first error goes into manifest `first_error` (`error`, `location`, `logged_as`). Checked against a real Scrapy 2.13 crawl failing in `start_requests`.
- New failure reason `crash` (crawler `crawler_run_status` and verifier `FAILURE_REASONS`, identical texts): no rows, no blocking, error recorded; order aborted, startup_check, access, crash, quality. Verifier writes `_FAIL_CRASH` with `first_error`; flow helper shows `crash: <error> (<file:line>)` in the summary/email. Runs with rows are unchanged.
- `docs/crawl_run_status.md` updated; 9 new tests (548 pass). scraper-pipeline reads `failure_reason` as free text, so no change there.

## 2026-11-13 - CI/CD step 5a: run summary emailed after every run
- `Notify` state after `Summary` publishes to SNS topic `ecommerce-scraper-crawl-flow-runs` (email subscription; a failed email doesn't change the run's result). Helper summary gains a subject ("Crawl flow dev SUCCEEDED: 3/3 crawls published" / "... FAILED at dbt test"), one line per degradation, a "Blocked by the site:" section, an API-cache line and a console link. 7 new tests (539 pass).
- IAM (user-approved): `sns:Publish` on that topic only, on the state machine role. Targeted apply 2 added, 3 changed; re-plan clean.
- The alert address is never in a tracked file: variable `crawl_alert_email` (sensitive, default empty) set in gitignored `infra/terraform/local.auto.tfvars` (`*.auto.tfvars` added to `.gitignore`).
- Tested: images-only run `a4e4812c` succeeded, the email arrived. Next: 5b, a `crash` failure reason for crawls that raise and write nothing.

## 2026-11-13 - CI/CD step 4 done: registry check before a crawl start
- `scripts/check_crawl_registry.py` (+ 8 tests), run by `make crawl-flow` for crawl starts: refuses when `price-comparison-dbt:latest` doesn't contain the newest scraper-pipeline `main` commit that changed `crawl_plp_registry.csv` (GitHub compare API), and prints active sites from the CSV at the image's commit. `SKIP_REGISTRY_CHECK=1` skips it. Checked live (image `sha-d043b14`, 3 sites x 4 URLs).
- User decided no separate CSV check in CI (the flow's seed tests already run before any crawl); the Level Shoes/Bloomingdale's URL host rule was asked of the scraper-pipeline session as a dbt test. Phase 2 cap already shows as a degradation in the summary. Ticket step 4 ticked; architecture doc updated.

## 2026-11-11 - CI/CD step 3 done: first fully green crawl flow
- Deployed `d7ce530` and scraper-pipeline `882fe8f`; targeted apply of the helper Lambda and state machine (0 added, 2 changed, no IAM).
- Short run `c413745c` (`CRAWL_LIMIT=1`) failed `dbt test` only on the unisex Bloomingdale's bag and correctly skipped the cache refresh; scraper-pipeline fixed it (`d043b14`, unisex → women, brand map fixes).
- Full run `929c20b5` succeeded in 86 min: 3 crawls success (Level Shoes 73 min, 4 gifts skipped), dbt test 48 pass / 1 warn / 0 errors, cache refreshed after the tests. Ticket step 3 ticked; next is step 4.

## 2026-11-11 - Cache refresh after dbt test; gift skip; --limit; readable failures
- Second flow run (`300a4856`): all three crawls published; dbt test failed 3 of 46 (Arabic brands, fixed in scraper-pipeline `511e18e`; the price-0 Level Shoes gift, fixed by gold requiring `price > 0` in `31ba452`).
- Level Shoes skips `productType: gift-with-product` listing items. `--limit` now caps listing pages per seed URL for Level Shoes and Bloomingdale's (Ounass still ignores it).
- Flow: every dbt step runs `exec --no-cache-refresh`; a new `Run_refresh_cache` step (`dbt_job.py refresh-cache`, scraper-pipeline) runs only after `dbt test` passes, so a failing test keeps the last good cache. Summary shows "exit code N (reason) task <id>" instead of raw ECS JSON.
- 524 tests pass. Docs (`cicd_architecture.md`), ticket step 3 updated. Next: dbt image with the new wrapper, targeted apply, `CRAWL_LIMIT=1` run, then a full run.

## 2026-11-10 - First crawl flow run; Level Shoes and Bloomingdale's fixes
- First `make crawl-flow CRAWL_LIMIT=20` (after pushing `2bfd26c`, image `sha-2bfd26c`): every step ran, flow succeeded with Ounass published (6,454 rows); dbt 24/24, images, quality checker, images+ 4/4, test 46/46; API cache refreshed twice.
- Level Shoes failed: new products' `analytics` block has only `constructor.variationId`, so `get_id_from_item` raised KeyError at start. `level_rules.py` listing getters now return None for missing keys (parse_pdp fills them); id falls back to `vpn`, brand to `brandName` (equal to the analytics values where both exist).
- Bloomingdale's failed the quality gate (gender/category/subcategory 100% blank): breadcrumbs moved from microdata to JSON-LD. `_extract_breadcrumbs` reads JSON-LD first, microdata as fallback. New labels are already in the scraper-pipeline category map.
- Both checked against live pages; 8 new tests; full suite 517 pass. Ticket step 3 updated.

## 2026-11-10 - CI/CD step 3 built and applied (first run pending)
- Crawler reads `CRAWL_RUN_ID` (mastercrawl.py; malformed stops the crawl). Helper Lambda `ecommerce-scraper-crawl-flow-helper` (start check, registry reader writing Level Shoes/Bloomingdale's `--urls-source` CSVs, verification check, gate, image marker, summary). State machine `ecommerce-scraper-crawl-flow-dev` in `infra/terraform/orchestration.tf`; checker S3 trigger removed; `make crawl-flow`, `make ecs-run-quality-checker`.
- Applied with `-target` in two stages (IAM user-approved); definition validated by AWS. Smoke tests passed after one fix: `s3:GetBucketLocation` moved out of the prefix-conditioned statement (user-approved). Full suite 509 + 21 helper tests pass.
- Next: push `main` (crawler image needs `CRAWL_RUN_ID`), then `make crawl-flow CRAWL_LIMIT=20`.

## 2026-11-10 - Step 3 edge cases documented; registry CSV checked
- `docs/cicd_architecture.md` gains an "Edge cases" table (15 cases: frequency, handling, result).
- The user's new `crawl_plp_registry.csv` (12 rows: Ounass, Level Shoes, Bloomingdale's; SA tote and shoulder bags, ar+en) passes every rule of the two registry dbt tests offline, and the Level Shoes and Bloomingdale's spiders' rules parse every URL as a PLP with the right country and language. Not yet committed in scraper-pipeline or seeded; told the scraper-pipeline and website sessions how to proceed.

## 2026-11-10 - CI/CD step 3 design agreed (not built)
- Checked with the scraper-pipeline and website sessions first: image filter live in dev; website's export change (releases/ + manifest, legacy keys kept) pending the user's OK, and it makes the cache refresh depend on `gold_site_nav`; prod dbt will run a pinned image (ECR rule for `prod-` needed then).
- Flow: start check → registry seed + tests → crawl list from the registry (Ounass PLP-efficient; Level Shoes and Bloomingdale's via `--urls-source` CSVs the helper Lambda writes from Athena) → parallel crawls with `CRAWL_RUN_ID` → wait for verification → full dbt run → image pipeline → quality checker (flow-run, also on `_FAILED`; S3 trigger removed) → `dbt run --select silver_product_image_download_status+` → dbt test → summary. Images-only start too.
- Recorded in `tickets/cicd_pipeline.md` step 3 (step 4 trimmed) and `docs/cicd_architecture.md`. Waiting on the user's registry URLs for the first test run.

## 2026-11-09 - CI/CD step 2 done: dbt runs in AWS (dev)
- scraper-pipeline pushed (with the other session's site-nav commits); first dbt image build passed. Cloud task: registry seed + tests, full run 24/24 with automatic dev cache refresh, full test 46/46; lock checked both ways.
- Next: step 3, the state machine. Website image filter is built (other session) but not deployed to dev; deploy before step 3 runs.

## 2026-11-09 - AGENTS.md: working alongside other agent sessions
- Added a "Working Alongside Other Agents" section to `context/AGENTS.md`, matching scraper-pipeline `d47a6a6`: check for other sessions and worktrees before starting, send a heads-up before editing outside this repo or in claimed files, answer heads-ups with context, commit only your own files by path. The dbt-lock rule was left out (it applies to scraper-pipeline).

## 2026-11-09 - CI/CD step 2: cloud dbt task built (not yet run)
- scraper-pipeline: Dockerfile, image workflow, `terraform/dbt_job.tf` applied with `-target` (11 added: ECR, task, logs, SG, 3 IAM roles, user-approved), `make dbt-job-dev`. Dev API cache Lambda redeployed; first wrapper run (laptop) refreshed the cache, 23/23 models, 43/43 tests.
- Next: GitHub variable `AWS_DBT_IMAGE_ROLE_ARN`, push scraper-pipeline `main`, test the cloud task. `docs/cicd_architecture.md` and step 2 updated.

## 2026-11-09 - CI/CD step 2: dbt lock built (laptop side)
- scraper-pipeline `scripts/dbt_job.py`: every table-writing dbt `make` target takes the S3 lock, renews it, refreshes the dev API cache when gold built (even if other models failed), then releases. Prod gets its own lock, no refresh. Checked in dev.
- `docs/cicd_architecture.md` wrapper diagram updated (refresh on gold even when dbt fails; lock-lost path). Step 2 next: redeploy the dev API cache Lambda, then the cloud parts.

## 2026-11-09 - CI/CD step 2: lock renewal and image filter decided
- dbt lock is renewed every few minutes while dbt runs; a crashed run's lock expires within minutes. A run that finds its lock taken over stops.
- The website API will hide products without images, so the cache refresh after the flow's first gold build is safe (no skip exception). Ticket: `../price-comparison-web/tickets/hide_products_without_images.md`, to build before step 3.
- Updated `docs/cicd_architecture.md` (diagram, notes, change log) and `tickets/cicd_pipeline.md` step 2. Docs only.

## 2026-11-09 - CI/CD step 2 plan agreed (not built)
- Plan lives in scraper-pipeline `ticket/migrate-dbt-to-cloud-jobs.md`, "▶ Agreed plan". Dev only.
- Decided (user): one S3 lock shared by laptop and cloud dbt runs; the API cache refreshes whenever gold builds, from the same wrapper, so the EventBridge rule stays off. Seen 2026-11-04: dev cache written Oct 29, dev gold rebuilt Nov 2.
- `docs/cicd_architecture.md` gains the wrapper diagram (lock, run, cache refresh).
