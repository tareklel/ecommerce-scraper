# Ticket: Cettire Crawler (Saudi handbags, AR + EN)

**Status: in progress; step 1 (full crawl) built and proven in live test runs 2026-11-14; next is the downstream onboarding in scraper-pipeline, then step 2 (efficient crawl) on a gold export**

**Site**: https://www.cettire.com/sa/ (country is a URL path)  
**Languages**: EN and AR names from the search service; product-page text is EN only  
**Country**: SA  
**Currency**: SAR (confirmed)  
**Scope**: women's handbags only, Arabic and English  
**Platform**: Next.js front end on a Reaction Commerce GraphQL back end, CloudFront, DataDome bot protection  
**Probe date**: 2026-11-14 (through Zyte from the dev crawler ECS task; pages kept under `s3://price-comparison-bucket-eu-central-1/probes/dev/cettire/`)

---

**Research record:** all findings, evidence, field lists and brand tables are
in `notes/2026-11-14-cettire-research.md`. Keep new research there; keep this
ticket for decisions and the work to do.

---

## Build status

**Step 1, full crawl (search service + product page): code written
2026-11-14, unit-tested, not yet run against the live site.**

- `ecommercecrawl/spiders/cettire_crawl.py`, `rules/cettire_rules.py`,
  `constants/cettire_constants.py`; registered as `cettire` in
  `run_crawler.py`.
- Seeds: `resources/cettire_urls.csv` (shoulder bags, tote bags). Allowlist:
  `resources/cettire_brand_allowlist.csv` (the 64 Level Shoes brands).
- Per listing: one small search call for brand counts, then one call of up to
  1,000 products per group of allowlisted brands; each product page fetched
  through Zyte plain HTML and merged in.
- Output: two rows per product (EN, AR) in the Level Shoes shape, plus
  `sizes`, `designer_model_number`, `designer_color`.

| Field | Search service | Product page |
|---|---|---|
| `portal_itemid`, `url` | numeric ID at the end of the slug | |
| `product_name` | `title` (EN row), `title_ar` (AR row) | |
| `category`, `subcategory` | `category` / `product_type` and their `_ar` versions | |
| `brand`, `gender`, `color` | `vendor`, `department`, `Color` | fills blanks only |
| `price`, `was_price`, `currency` | `sa_sar_price_f`, `sa_sar_compare_at_price_f`, SAR | fills blanks only |
| `price_discount` | computed whole percent; `0` at full price, `None` when the price is missing | |
| `out_of_stock` | `inventory_quantity` is 0 | not used: the page is rendered for the default region, not Saudi |
| `sizes` | `Size` | fills blanks only |
| `image_urls` | 3 to 4 listing images | full gallery wins when present |
| `text` | none | EN row only: `details` (feature bullets, composition, made in), `size_fit` (dimensions). `description` stays `None`: Cettire has no prose paragraph |
| `primary_label` | none | none |

- Search key: kept in Parameter Store, `/ecommerce-scraper/cettire/search-api-key`
  (SecureString; the crawler may read and write that one parameter only). Missing,
  unreadable or rejected (401/403): the spider reads the current key from a
  Cettire page through Zyte, saves it back and retries once. Pages tried, in
  order: up to 10 product addresses saved by the last run that got products
  (`s3://<bucket>/resources/cettire/key-pages.json`, written after the first
  listing of every run), then the three listing pages; one plain fetch each
  (at least 4), then 8 in browser mode. Product pages first because they got
  through ~99% on 11-17/18 while listing pages failed from 11-19;
  `/sa/products/<id>` alone is "page not found", so the full address is kept.
  Logs show a key fingerprint (first 8 of its SHA-256), never the key.
- 2026-11-20 state: Zyte is refused on every Cettire page tried (listing
  pages plain and browser, a product page plain, a listing page plain with
  geolocation TR: all 520). The first key was loaded by hand (user-approved)
  from the pages saved in the 11-14 probes (fingerprint `51200e93`, the same in
  all 16 saved pages that carry one) and Cettire still accepted it: a dev test run
  (`--limit 1`, uploads off) read it from Parameter Store, made no Zyte
  request, wrote 38 rows, quality pass. So the key lasted at least 6 days.
  While Zyte is refused, new products' pages fail and are written from search
  data. Built the same day: renewal from saved product addresses and the
  fingerprint log (above). Still open: a second proxy as another renewal route
  (Oxylabs settings exist, account status unknown). Zyte
  refused throughout: the run fails. Key works but can't be saved: the run goes
  on and is `degraded` (`kind: setup`). Decided 2026-11-20 (user), after the
  11-20 run failed on 12 Zyte 520s reading the key; replaces the earlier
  `CETTIRE_SEARCH_API_KEY` setting.
- A product page that fails or has no data does not drop the product: its
  rows are written from the search data.
- `--limit N`: at most N brand groups per listing and 20 products per call.
- Completeness: received against listed counts is logged per listing
  (`Cettire listing summary`), with a warning when short.
- Tests: `tests/test_cettire_rules.py`, `tests/test_cettire_spider.py`
  (40 tests, hand-written fixtures in `tests/cettire_fixtures.py`). The rules
  were also checked by hand against the saved real responses: 1,000 search
  products gave 1,998 rows with no blank required field, and three real
  product pages parsed with prices matching the search data.

**First live runs (2026-11-14, `--limit 1`, dev crawler task, bronze uploads
off, output under `probes/dev/cettire/live1` and `live2`)**

- Run 1 failed in a minute: no stored key, and Zyte refused all 4 fetches of
  the key page. Reported correctly as `failed` / `crash`. Fixed: 12 attempts
  with a pause, rotating over three pages.
- Run 2 succeeded: quality gate passed, 40 products (20 per listing), 39 of 40
  product pages fetched, reading the key took about 3.5 minutes.
  - EN rows: `Bags | Shoulder Bags`, `Bags | Tote Bags`. AR rows: `أكياس |
    حقائب الكتف`, `أكياس | حقائب اليد`.
  - Rows carry 2 to 6 images; 39 of 42 EN rows have `text`.
- Three problems found in run 2, fixed afterwards:
  1. **Duplicate rows**: the one refused product page was written three
     times, once per retry round. A request set aside for a round now writes
     nothing.
  2. **30 minutes lost to one page**: the access retry rounds waited 15
     minutes twice for a single product page, so the run took 40 minutes.
     Cettire product pages now skip the rounds (`access_no_defer`) and fall
     back to search data at once.
  3. **Wrong stock from the page**: 10 of 40 products were marked sold out by
     the product page while the Saudi search listed them in stock. The page is
     rendered for the site's default region, so stock and sizes now come from
     the search only. Not yet confirmed against the site in a browser.

- **Run 3 (`live3`) confirmed the fixes**: 7 minutes instead of 40, 80 rows
  for 40 products, no duplicates, nothing marked out of stock, quality gate
  passed. 35 of 40 product pages fetched; the 5 refused ones were written
  from search data straight away. Key read took 2 minutes; the 40 product
  pages took 5 minutes (about 7.5 seconds each). At that pace a first full run
  with every product page (about 7,800) would take roughly 16 hours, which is
  the case for step 2 and for spreading the first product-page pass.

**Order of work from here (user decision, 2026-11-14): downstream first,
then the efficient crawl built on a gold export, like Ounass.**

1. **Downstream onboarding in scraper-pipeline** (next). Ticket:
   `../scraper-pipeline/ticket/onboard-cettire.md` (branch
   `claude/cettire-onboarding-ticket` of `tareklel/scraper-pipeline-pc`, not
   merged yet). Seeds, per-site models, unions, image check and tests, so
   Cettire rows reach silver and gold. Registry rows go in last, because
   active rows make the scheduled crawl flow crawl Cettire.
2. **Get this branch onto main and into the crawler image.** The dev image is
   built from main and does not contain the spider; the live tests ran this
   branch's code unpacked over the image. Until it is merged, the crawl flow
   cannot run Cettire.
3. **First real crawl into bronze** (uploads on), once step 1 can read it.
   Decide then whether the first run fetches every product page (about 16
   hours at the measured pace) or spreads them.
4. **Step 2, efficient crawl**, built on a gold export of known Cettire
   products: the search service refreshes every product each run; a product
   page is fetched only for products that have not had one. Needs step 1,
   and an export from scraper-pipeline like the Ounass efficient-crawl
   inputs.
5. **Brand mapping for the allowlist** (see the next section): the current
   list is a name-matched first pass. Shares the `dim_map_brand` work in
   step 1.

**Joining the nightly crawl flow (2026-11-15)**

- **Registry: English only, one row per listing** (user decision). Each
  Cettire listing URL serves both languages through the search service, so
  the spider writes EN and AR rows from one URL; no stand-in Arabic registry
  row. Arabic quality is left to downstream; if a single-language mode is
  ever wanted, add a switch to turn the AR rows off.
- `cettire` added to `SITES` in `lambda/crawl_flow_helper/handler.py`
  (`urls_source`, like Level Shoes). **The helper Lambda is deployed by a
  targeted Terraform apply, not by CI**: apply it before any Cettire registry
  row goes active, or the flow refuses to start for every site
  (`UnknownRegistrySite`).
- **Product pages off by default** (user decision, 2026-11-15: no
  ~7,800-page first crawl). `CETTIRE_FETCH_PRODUCT_PAGES` (env var, default
  false): the spider writes every allowlisted product from the search data
  alone (names in both languages, price, stock, colour, size, 3 to 4 images),
  with no Zyte requests apart from reading the search key when it is not
  stored. No descriptions (`text` null on every row). Turn it on only with
  the efficient crawl, which fetches pages for new products alone.
- **Step 2, efficient mode — built 2026-11-16** (branch, with
  scraper-pipeline's `gold_cettire_pdp_known`): the spider reads the list of
  products whose page was already read (tab-separated gzipped text under
  `s3://<bucket>/dbt/<env>/gold_cettire_pdp_known/`, built in the nightly dbt
  run; the crawler role reads S3, not Athena). For those products it never
  fetches the page and writes their stored gallery instead of the 3 to 4
  search images (downstream keeps an old gallery only when the new one is
  null). Product copy needs nothing: downstream keeps the last non-null text.
  Pages are fetched only for products not on the list, at most
  `CETTIRE_MAX_PRODUCT_PAGES` per run (default 2,000, about 4 hours), so the
  one-off pass over ~7,800 products takes about four nights and then only new
  products cost a page. An unreadable list means no pages that run.
  `CETTIRE_FETCH_PRODUCT_PAGES` now defaults to **true** (user decision,
  2026-11-16): the first Cettire night writes every product from search data
  and fetches the first 2,000 product pages; about four nights complete the
  pass. Set the env var to false to stop page fetches.
- Registry rows are added in scraper-pipeline with `is_active = FALSE`.
  Switching them to TRUE is what starts the nightly crawl.

Smaller items, any time:

- ~~Stored search key~~: done 2026-11-20, in Parameter Store and renewed by
  the spider itself (see "Search key" above).
- The completeness shortfall is only logged; make it a degradation in the
  manifest.
- Confirm the stock finding in a browser from a Saudi connection (product
  page said sold out, Saudi search said in stock, on 10 of 40 products).
- Product pages given up on access do not degrade the run today; decide
  whether the manifest should count them.

---

## Brand allowlist: rule, and the mapping work it still needs

**Rule (user, 2026-11-14): Cettire is crawled only for brands that Level
Shoes carries.** The crawler enforces it with
`resources/cettire_brand_allowlist.csv`: only those brand names are sent to
the search service, so other brands are never fetched.

**The current list is a first pass, not a real mapping.** It was built once,
by hand-run script, and has these gaps:

| Gap | Detail |
|---|---|
| Name matching only | Level Shoes brand names from gold were matched to Cettire's by normalised spelling (case, accents, punctuation) plus three hand-written aliases (`Valentino Garavani` = `Valentino`, `McQueen` = `Alexander McQueen`, `Michael Kors` = `Michael Michael Kors`). Any brand spelled differently in a way nobody spotted is silently missing |
| Shoulder bags only | Cettire's brand list was read for shoulder bags (319 brands). Brands that appear only under tote bags were never seen, so they can't be on the list |
| Not all of Cettire | No one has looked at Cettire's full brand list across categories, or at sub-lines (`Michael Michael Kors`, `Love Moschino`, `Kurt Geiger London`, `Adidas By Stella McCartney`) and whether each belongs to a Level Shoes brand |
| Unmatched Level Shoes brands unreviewed | 28 Level Shoes brands had no Cettire match (e.g. State Of Escape, Aquazzura, DeMellier, The Jacksons). Nobody checked whether Cettire has them under another name |
| Frozen snapshot | The list reflects Level Shoes' brands in dev gold on 2026-11-14. When Level Shoes adds or drops a brand, the CSV does not follow |
| No link to canonical brands | The list is plain names. It is not tied to scraper-pipeline's `dim_canonical_brand` / `dim_map_brand`, which is where "the same brand on two sites" is supposed to be defined |

**Work needed (not yet discussed or planned in detail):**

1. Get Cettire's complete brand list for every category we crawl (one small
   search call per listing returns the `vendor` facet).
2. Map each Cettire brand to a canonical brand in scraper-pipeline's
   `dim_map_brand` (site `cettire`), reviewing sub-lines and near-matches by
   eye. This is the real mapping; it also serves the downstream onboarding
   (`../scraper-pipeline/ticket/onboard-cettire.md`).
3. Derive the allowlist from that mapping: a Cettire brand is allowed when
   its canonical brand has products on Level Shoes. Decide whether the list
   is generated (an export, like the Ounass efficient-crawl inputs) or stays
   a committed CSV refreshed by a script.
4. Report brands that are on Cettire but unmapped, so new ones are reviewed
   instead of silently skipped.
5. Decide the rule's scope: "brand exists on Level Shoes at all" (today) or
   "brand has bags on Level Shoes"; and whether Ounass brands should count
   later.

---

## Decisions (user, 2026-11-14)

1. **Source**: listings come from Cettire's search service, called directly
   (no Zyte, no browser), in calls of up to 1,000 products per group of
   brands. Browser rendering was rejected on cost.
2. **Zyte only where needed**: product pages (plain HTML mode) and reading
   the search key when it is missing or rejected. Zyte was first used only
   because the agent session could not reach the site; tested from AWS, pages
   are blocked without it and the search service is not.
3. **Brands**: only brands Level Shoes carries (see "Brand allowlist").
4. **Languages**: English and Arabic names in one pass. Arabic descriptions
   are deferred (they need a browser or the site's product API).
5. **Search key**: stored and reused; re-read from the site only when
   rejected.
6. **Order of work**: downstream onboarding first, then the efficient crawl
   on a gold export.

---

## Why

Bloomingdale's yields too few products to matter. From the daily crawl flow
run of 2026-11-13 (`d66af788`), same two listings (tote bags, shoulder bags):

| Site | Products | Rows (AR + EN) |
|---|---|---|
| Ounass | ~3,100 | 6,219 |
| Level Shoes | 2,140 | 4,280 |
| Bloomingdale's | 59 | 118 |

The product's value proposition is range (`context/product-brief.md`), so the
third site should add thousands of bags, not dozens. Cettire is a large
multi-brand luxury retailer that ships to Saudi.

Bloomingdale's stays in the flow for now; whether to retire it is a separate
decision once Cettire is live.

---

## What the research found (summary)

Full detail, evidence, request and response fields, brand tables, cost and
affiliate notes: `notes/2026-11-14-cettire-research.md`.

- **Site**: Next.js on a Reaction Commerce back end, behind DataDome. Saudi is
  the `/sa/` URL path; language is a cookie; one URL per product.
- **Listing pages hold no products in their HTML.** The grid comes from the
  search service, which answers directly from AWS and returns names in both
  languages, brand, category, SAR price and was-price (duties and taxes
  included), stock, colour, size and 3 to 4 images.
- **Paging by page number is unreliable**; one call can return 1,000
  products, and a brand filter makes each call fit. Calls return about 1.5%
  fewer products than the site's own counts (cause unknown).
- **Product pages** need Zyte (direct requests get a 403), are refused about
  one time in eight, take about 7.5 seconds each, and add only the full
  gallery and English copy. Their stock flag is for the default region, not
  Saudi.
- **Catalogue**: about 9,500 shoulder bags and 8,200 tote bags for Saudi
  women across 319 brands (shoulder bags); mostly accessible brands. The
  Level Shoes allowlist keeps 4,175 shoulder bags; tote bags are estimated at
  about 3,600, not counted.
- **Cost**: about $2 to $11 one-off and $1 to $3 a month with a daily run,
  nearly all of it product pages.
- **Affiliate programme** exists (Partnerize, BlueAff); no product feed found
  in public listings.

---

## Other open items

- **Images (fixed 2026-11-18, check the next run)**: from the first flow run
  to 2026-11-17, every Cettire image job was rejected by the image downloader
  as an unsupported site (`cettire` was missing from `SITE_ALIASES`), so gold
  had 15,832 Cettire rows and 0 with images. Fixed in
  `ecommercecrawl/image_downloader.py`; the CDN allows direct downloads. The
  next image step downloads the whole backlog (61,185 images, 7,917
  products). Check the run email's Cettire "with images" count.
- **Pull requests** (opened 2026-11-15, not merged): crawler work,
  https://github.com/tareklel/ecommerce-scraper/pull/1; downstream ticket,
  https://github.com/tareklel/scraper-pipeline-pc/pull/1. Merging the crawler
  PR builds a new image but does not start crawling Cettire (no registry rows
  yet).
- **Tote bags by brand**: never analysed. The allowlist was built from
  shoulder-bag brands, so tote-only brands are missing and the tote count is
  an estimate. One small search call returns the breakdown.
- **Affiliate application** (user): apply through Partnerize or ask Cettire's
  affiliate team whether a product feed with SAR prices and Arabic titles
  exists. A feed could replace the search-service route.
- **Arabic descriptions**: deferred. Arabic rows have names and categories
  but no `text`.
- **Probe data in the dev bucket**: `probes/dev/cettire/` holds copies of
  Cettire pages, search responses, live-test outputs and tarballs of the
  crawler code. Delete once the downstream work no longer needs a sample.
- **AWS access for agent sessions**: every check needed a fresh sign-in with
  the only available role, `AdministratorAccess`. A read-only role would be
  safer.

---

## Done when

- Cettire rows flow from a scheduled crawl through bronze, silver and gold,
  with images, and the product count is reported next to Ounass and Level
  Shoes.
- The crawl runs in efficient mode: search service every run, product pages
  only for products that have not had one.
- The allowlist comes from a reviewed brand mapping.

---

## Open questions

- Catalogue churn: how fast do products appear and sell out, and is a daily
  crawl enough?
- Do sold-out products stay in the search results or disappear?
- How often does the search key change?
- Keep or retire Bloomingdale's once Cettire is live.
