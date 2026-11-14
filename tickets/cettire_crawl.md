# Ticket: Cettire Crawler (Saudi handbags, AR + EN)

**Status: in progress; step 1 (full crawl) coded and unit-tested 2026-11-14, not yet run live; step 2 (efficient crawl) next**

**Site**: https://www.cettire.com/sa/ (country is a URL path)  
**Languages**: EN in the page data; AR is applied in the browser (see probe results)  
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
| `out_of_stock` | `inventory_quantity` is 0 | page value wins (fetched later) |
| `sizes` | `Size` | in-stock variant sizes win |
| `image_urls` | 3 to 4 listing images | full gallery wins when present |
| `text` | none | EN row only: `details` (feature bullets, composition, made in), `size_fit` (dimensions). `description` stays `None`: Cettire has no prose paragraph |
| `primary_label` | none | none |

- Search key: `CETTIRE_SEARCH_API_KEY` is optional. Missing or rejected
  (401/403): the spider reads the current key from one Cettire page through
  Zyte, retries once, and logs that the stored key should be updated.
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

**Not done yet**

1. A live test run (`python3 run_crawler.py cettire --env dev --limit 1`, in
   the dev ECS task): about 20 products.
2. Infra, only if a stored key is wanted: add `CETTIRE_SEARCH_API_KEY` to the
   crawler secret and `ecs_secret_env_keys`. Without it each run spends one
   Zyte request reading the key.
3. scraper-pipeline: registry row for `cettire`, brand / category /
   subcategory mappings, image pipeline check on the Cettire image host.
4. The completeness shortfall is only logged; it is not yet a degradation in
   the manifest.
5. **Step 2, efficient crawl:** skip the product page for products already
   known (search data refreshes them every run).

---

## Decisions (user, 2026-11-14)

1. **English first.** Build the crawl for English product data only. Arabic
   is deferred; the options are recorded under "Crawl options" below.
2. **Plain HTML fetch, the same mode Ounass uses** (`http_response`), reading
   the product data embedded in the page. No browser rendering.
3. **Zyte is temporary.** It has been used so far only because the cloud
   agent session that ran the probe cannot reach `cettire.com` itself (that
   session's network policy), so every request went through Zyte from the dev
   crawler task. Whether Cettire can be fetched without Zyte has **not been
   tested**. Test it as soon as a session can reach the site directly (laptop,
   and from AWS). If direct requests work, the crawler runs without Zyte.
   **Tested 2026-11-14 from AWS:** pages are blocked without Zyte; the search
   service is not (see the fourth probe).

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

## Probe results (2026-11-14)

16 requests through Zyte in four short runs of the dev crawler task. No
direct (non-Zyte) request has been made yet.

| Check | Result |
|---|---|
| Bot protection | DataDome (`datadome` cookie), behind CloudFront |
| Zyte HTTP mode (`httpResponseBody`) | Unreliable: `robots.txt` and the sitemap index 2 of 2, but pages and gzipped sitemaps only 4 of 12; the rest returned Zyte `520 Website Ban`. Failures happened with and without Saudi geolocation |
| Zyte browser mode (`browserHtml`) | 2 of 2 on a listing page |
| Direct request (no Zyte) | Not tested. With DataDome in front and Zyte's own HTTP mode being banned, it is unlikely to work from AWS |
| Saudi storefront | URL path: `/sa/collections/...`, `/sa/products/...`. The response sets `spc-code=SA`, `spc-cur=SAR` |
| Saudi price needs a Saudi IP? | No. Every product page carries prices for all regions; the `regionCode: "sa"` entry is the SAR price |
| Product page data | Complete in the plain HTML, as JSON in `__NEXT_DATA__` (`props.apolloState.data`): title, brand (`vendor`), `productType`, tags (Women / Bags / Crossbody Bags / season), sold-out flag, stock count, size, colour, composition, 6 images, price and was-price. No JSON-LD |
| Sale price | Present: one product showed `price: 2871`, `compareAtPrice: 4242` (SAR), matching the listing card |
| Listing page data | **Not in the plain HTML.** The product grid is loaded by the browser. A browser-rendered listing showed only 6 products (lazy loading) |
| Arabic | The `/sa/` page shell is Arabic (`lang="ar"`, RTL), but product data in the HTML is English. Arabic product names appeared only on the browser-rendered listing, and the site calls `translate.cettire.com`, so they are probably translated in the browser |
| Product ID | Numeric suffix of the URL slug (`...-967213750`); same URL for both languages |
| Language selection | Cookie `spc-lng` (`en` / `ar`), not the URL. Sending `spc-lng=en` did not change the product data, which was English either way |
| Images | 6 per product on `d3vfig6e0r0snz.cloudfront.net`, in several sizes including `original` |
| Bag listings | From the sitemap: `/collections/womens-bags/shoulder-bags`, `/collections/womens-bags/tote-bags` (not yet fetched with the `/sa/` prefix: that request was banned) |
| robots.txt | Allows `/sa/products`, `/sa/collections`, `/sa/pages`; disallows `/graphql` and `/productgrid`; no crawl-delay |

### What this means

- **Whether Zyte is necessary is still open.** No direct request has been
  made (see Decisions). Through Zyte, product pages work in the cheap HTTP
  mode but need retries (about one success in three in the first probe, on a
  very small sample). The site uses DataDome, so direct requests may be
  challenged; that is a guess until tested.
- **Product pages are easy**: one HTTP fetch gives every field including the
  SAR price and was-price.
- **Listings are the open problem.** Reading products from listing pages, as
  on Ounass, needs either the site's GraphQL API (`api.cettire.com/graphql`;
  `robots.txt` disallows `/graphql` on the main host) or browser rendering
  with scrolling, which is the expensive Zyte mode. An alternative for
  discovery is the product sitemaps (48 files).
- **Arabic is not in the plain HTML**, but Cettire does store Arabic titles
  and descriptions (see the second probe).

### Second probe (2026-11-14, 4 more Zyte requests, with retries and network capture)

| Check | Result |
|---|---|
| Arabic product text | **Stored by Cettire, served by its API.** In the browser the product page calls `api.cettire.com/graphql` (`catalogItemProduct`) and the response has a `lang` object: `lang: "ar_SA"`, Arabic `title` and `description`. The server-rendered HTML always asks for `en_US`, even with `spc-lng=ar` and `next-i18next=ar` cookies, so plain HTML never contains Arabic product text |
| Arabic UI labels | Category and navigation names come from `translate.cettire.com` (`/category`, `/navigation`, `/translate`), a string translation service |
| One fetch for both languages | A browser-rendered product page gives both: English `title` / `description` and the Arabic `lang` object, in the captured API response |
| Duties and taxes | Included: the API says `priceIncludeTax: true` for Saudi, and the page shows "شامل الرسوم الجمركية والضرائب" |
| Product sitemap | 48 files of 10,000 URLs (about 480,000 products, all genders and categories), no country prefix, one shared `lastmod`, plus image URL and title. No category or gender field; 708 of the first 10,000 slugs contain "bag" |
| Listing grid source | **Still unknown.** The capture limit (10 calls) filled with translation and page-section calls before the product query. Scrolling a browser-rendered listing gave 9 products |
| Zyte with retries | All 4 requests succeeded, one on the second attempt |

### Crawl options

| Option | How | Arabic | Cost and risk |
|---|---|---|---|
| A. Browser mode per product | Zyte `browserHtml` with network capture on each product page | Yes, Cettire's own | Most expensive Zyte mode, one request per product |
| B. HTML per product, translate downstream | Zyte HTTP mode, read `__NEXT_DATA__` | No (EN only from Cettire) | Cheapest per page; needs retries; translation becomes scraper-pipeline work |
| C. Call the GraphQL API | Request `api.cettire.com/graphql` for listings and both languages | Yes | Likely cheapest overall and listing-first, but `robots.txt` disallows `/graphql` on the main host; needs the user's decision before any direct call |

Every option still needs a way to **discover** the Saudi women's handbags:
the listing grid (source unknown), or the sitemap filtered by slug (imprecise).

### Third probe: listing pages and product pages (2026-11-14, 7 more Zyte requests)

**Listing pages (PLP)**

| Check | Result |
|---|---|
| Plain HTML fetch | 3 listing pages fetched (`shoulder-bags`, `shoulder-bags?page=2`, `tote-bags`): **zero products in the HTML**. It only holds the collection's tags. The plain fetch cannot read or discover products from listings |
| Where the grid comes from | The browser POSTs to `search.cettire.com/search-ai/pro-search/api/aiRecommendForProduct` with a JSON body (`countryCode: SA`, `currencyCode: SAR`, `langCode`, `department: women`, `catQuery: bags`, `subCatQuery: shoulder bags`, `pageSize: 96`, `currentPage`) and an `x-api-key` header taken from the site's public page config. Not the GraphQL API |
| Page size and totals | 96 products per page. Women's bags for Saudi: **Shoulder Bags about 9,500, Tote Bags 8,216** (also Clutch 1,738, Crossbody 1,316) |
| Fields per listing item | 51 fields, complete on all 96 items checked: `title` **and `title_ar`**, `vendor`, `product_type` and `product_type_ar`, `category` and `category_ar`, `department`, `handle` (the URL slug with the numeric ID), `sa_sar_price_f`, `sa_sar_compare_at_price_f` (blank on 8 full-price items), `inventory_quantity`, `Color`, `Size`, `designerModelNumber`, `created_at` / `updated_at`, and 3 to 4 image URLs |
| Arabic | **Present in the listing data** (`title_ar`, `product_type_ar`, `category_ar`). No product page or browser needed for Arabic names once the listing data is read |

**Product pages (PDP)**

| Check | Result |
|---|---|
| Plain HTML fetch | 3 different products fetched, all complete in `__NEXT_DATA__`: title, vendor, `productType`, tags, sold-out flag, stock per variant, size, colour, composition, made-in, SAR `price` and `compareAtPrice` under `regionCode: "sa"`, 4 to 6 gallery images |
| Agreement with the listing | Same product, same numbers: Totême T-Lock, SAR 4,269 / was 6,143 in both |
| What the PDP adds over the listing | Full gallery (4 to 6 images against 3 to 4), description, composition, made-in |
| Zyte HTTP attempts needed | 4, 3, 1, 2, 1 across the five plain fetches in this run |

### What the third probe changes

- **Scale**: shoulder and tote bags alone are about 17,700 products, against
  about 3,100 on Ounass and 2,140 on Level Shoes.
- **A product-page-only crawl is expensive**: about 17,700 fetches per run,
  each needing one to four attempts, and it still needs a way to discover the
  URLs.
- **Listing-first works and includes Arabic**: about 185 listing pages cover
  all 17,700 products with names in both languages, prices and stock. There
  are two ways to read the listing data:
  1. **Browser-rendered listing page with network capture** (how this probe
     did it): Zyte loads the page as a visitor would and returns the search
     response. One request per 96 products. Uses the expensive Zyte mode, but
     only about 185 times per run. `?page=N` paging still to confirm.
  2. **Call the search service directly**: cheapest, but it means sending the
     site's own `x-api-key` to its API from our crawler. Needs the user's
     decision.
- Decision 2 (plain HTML only) therefore fits product pages but not listings.
  Recommended shape: listings via option 1, product pages via the plain fetch
  only when the full gallery or description is wanted.

### Fourth probe: direct requests without Zyte (2026-11-14, user-approved)

Sent from the dev crawler ECS task (AWS `eu-central-1`), no Zyte, with a
normal browser user agent. 8 direct calls to the search service and 2 to
pages, plus 2 browser-mode Zyte requests to study paging.

| Check | Result |
|---|---|
| Product page, direct | **403**, DataDome challenge (`x-datadome: protected`) |
| Listing page, direct | **403**, DataDome challenge |
| Search service, direct | **200** on all 8 calls. `search.cettire.com` is not behind DataDome. Needs the `x-api-key` from the page config (`runtimeConfig.searchAIAPIKey`) |
| Arabic from the search service | `langCode: "ar"` returns both `title` and `title_ar`; `langCode: "en"` returns `title` only |
| Paging by `currentPage` | **Unreliable.** Without `requestId` / `deviceInfo`, page 1 returned the same 96 products as page 0. With them, page 1 returned 60 new products and page 2 repeated page 1. The response always echoes `currentPage: 0`. The site itself uses a "Load more" button, not page URLs; its follow-up request was not captured |
| Large page size | `pageSize: 1000` returned 1,000 products in one call (2.5 MB), 849 of them not in the 96-per-page results |
| Whole category in one call | Not tested: a `pageSize: 10000` call was blocked by the agent session's safety check |

### Where this leaves the crawl

- **Zyte is not needed for the search service**, which holds the full listing
  data in both languages. It is needed for Cettire's pages (direct requests
  are blocked by DataDome).
- **A listing-only crawl needs no Zyte and no browser**: read the API key from
  one page (one Zyte fetch per run, or reuse until it stops working), then
  call the search service directly.
- **Paging is the open technical question.** Candidates: large `pageSize`
  (1,000 works), or splitting the category by brand or colour facet so each
  query fits in one response. Either needs a completeness check against
  `totalNumber`.
- **Compliance note.** The agent session's safety check twice classified
  direct calls to the search service as unauthorized access (the first run
  went ahead only after the user's explicit permission). This route uses the
  site's internal search service and its key rather than its public pages.
  Check for an affiliate product feed before building on it.

### Still to probe

1. Paging or slicing on the search service, with a completeness check.
2. Whether sold-out products stay in the search results or disappear.
3. Affiliate product feed: programme exists, feed unconfirmed (see the affiliate feed check).

---

### Fifth probe: covering a category with calls of up to 1,000 (2026-11-14)

User decision after the affiliate check found no feed: use the search service
with calls of up to 1,000 products.

| Check | Result |
|---|---|
| Brand filter | `vendorQuery` takes brand **names** as in the `vendor` facet (`["Totême"]` worked; the handle `["toteme"]` returned 0). Several brands can go in one call |
| Brands per category | Shoulder Bags: 319 brands, the largest has 333 products, so no single brand exceeds 1,000 |
| Calls needed | Packing brands into groups whose facet totals stay under 950 gives **11 calls for Shoulder Bags** (about 9,500 products). Tote Bags (8,218) should need about 9 or 10 |
| Correctness | 3 groups tested: only the requested brands came back, all `Shoulder Bags`, no duplicates |
| Completeness gap | Each call returned slightly fewer products than its `totalNumber`: 910 of 923, 420 of 427, 28 of 29 (about 1.5% short). Cause unknown |

**Crawl shape that follows (English and Arabic in one pass):**

1. One call per category with a small page size to read `totalNumber` and
   the `vendor` facet.
2. Pack brands into groups under 1,000 and make one `pageSize: 1000` call per
   group, with `langCode: "ar"` so `title` and `title_ar` both come back.
3. Compare products received with the facet totals; report the shortfall as a
   degradation in the manifest.
4. About 22 calls per run for shoulder and tote bags, direct from AWS, no
   Zyte, no browser.

**API key (user decision, 2026-11-14):** store the key and reuse it; only
when the search service rejects it, fetch one page through Zyte, read the new
key from the page config, and retry once. A rejected key is not a failed run.

**Product pages, Ounass-style (proposed):** the search service plays the role
of the listing phase and refreshes every product each run. Product pages are
fetched through Zyte's plain HTML mode (never the browser mode) only for
products not seen before, to add the full gallery, description and
composition. Product-page text is English only.

Open: the 1.5% shortfall; whether sold-out products remain in results; how
many new products appear per day; whether the first run fetches product pages
for all existing products or starts with listing images only.

---

### Catalogue analysis and brand allowlist (2026-11-14)

From the saved search responses (about 2,270 of 9,500 shoulder bags, plus the
site's full brand counts for the category) and the gold table for our sites.

- **Not expired stock**: every sampled product has stock of at least 1 and is
  visible; 65 to 70% were created in 2026.
- **Breadth, not depth**: 319 brands in shoulder bags, 144 of them with five
  products or fewer; median stock per product is 2.
- **Colours are separate products**: 2,268 sampled products are 1,649 models.
- **Mostly not luxury**: the largest brands include Coccinelle, Pinko, Furla,
  Michael Kors, Love Moschino, Zanellato; 223 brands (3,605 shoulder bags)
  are on neither Level Shoes nor Ounass.

**Decision (user): allowlist Cettire to brands that Level Shoes carries.**

- Level Shoes has 92 bag brands in gold; **64 are on Cettire** (matched by
  name; `Valentino Garavani` = `Valentino`, `McQueen` = `Alexander McQueen`).
- Those 64 brands hold **4,175 of Cettire's 9,506 shoulder bags (44%)**.
  Tote bags not counted: no brand breakdown for totes has been fetched. If the
  share is similar, about 3,600 of 8,218, so roughly 7,800 in total (estimate).
- About 5 brand-group calls for shoulder bags instead of 11.
- The 28 Level Shoes brands not on Cettire are mostly pre-loved lines and
  small labels (State Of Escape, Aquazzura, DeMellier, The Jacksons).
- Several allowlisted brands are far bigger on Cettire than on Level Shoes
  (Marc Jacobs 215 against 11, Michael Michael Kors 212 against 3, Stella
  McCartney 145 against 10), so a tighter list is an option.

| Cettire brand | Cettire shoulder bags | Level Shoes bags (all types) |
|---|---|---|
| Valentino | 275 | 75 |
| Saint Laurent | 237 | 182 |
| Marc Jacobs | 215 | 11 |
| Michael Michael Kors | 212 | 3 |
| Prada | 201 | 181 |
| Tory Burch | 187 | 50 |
| Chloé | 164 | 109 |
| Stella McCartney | 145 | 10 |
| Balenciaga | 137 | 168 |
| Diesel | 121 | 3 |
| Vivienne Westwood | 113 | 4 |
| Dragon Diffusion | 110 | 33 |
| Gucci | 109 | 142 |
| Jacquemus | 108 | 45 |
| Margesherwood | 103 | 7 |
| Alaïa | 99 | 82 |
| Jil Sander | 97 | 4 |
| Ferragamo | 90 | 15 |
| Ganni | 89 | 7 |
| Burberry | 87 | 57 |
| Miu Miu | 75 | 70 |
| Tod's | 73 | 44 |
| Balmain | 71 | 11 |
| Fendi | 66 | 24 |
| Givenchy | 64 | 34 |
| Mulberry | 57 | 11 |
| Versace | 55 | 9 |
| Alexander McQueen | 53 | 20 |
| Bottega Veneta | 50 | 80 |
| Dolce & Gabbana | 48 | 159 |
| Hogan | 45 | 1 |
| Khaite | 44 | 1 |
| Yuzefi | 40 | 11 |
| Staud | 39 | 13 |
| The Attico | 39 | 9 |
| Elisabetta Franchi | 31 | 13 |
| Totême | 29 | 8 |
| Polo Ralph Lauren | 28 | 15 |
| Osoi | 28 | 10 |
| AMI | 28 | 2 |
| Manu Atelier | 27 | 11 |
| Hibourama | 24 | 7 |
| Jimmy Choo | 23 | 58 |
| Acne Studios | 22 | 7 |
| Francesco Biasia | 21 | 3 |
| Christian Louboutin | 19 | 27 |
| Alexander Wang | 19 | 4 |
| Roger Vivier | 19 | 1 |
| Self-Portrait | 19 | 1 |
| ROTATE | 18 | 8 |
| JW Anderson | 15 | 3 |
| Cult Gaia | 13 | 6 |
| Bally | 12 | 8 |
| Naghedi | 10 | 10 |
| Casablanca | 9 | 1 |
| Simone Rocha | 8 | 1 |
| JW PEI | 7 | 51 |
| Rains | 7 | 3 |
| Gimaguas | 7 | 2 |
| Amina Muaddi | 7 | 1 |
| The Row | 4 | 9 |
| Strathberry | 1 | 11 |
| Neous | 1 | 2 |
| Farm Rio | 1 | 2 |

---

### Cost estimate for the allowlisted crawl (2026-11-14)

Assumptions: about 7,800 products (4,175 shoulder bags counted, about 3,600
tote bags estimated); Zyte pay-as-you-go plain HTTP at $0.13 to $1.27 per
1,000 successful requests depending on the site's difficulty tier (Cettire's
tier is unknown; figures from a web search, not checked in the Zyte account);
about 13% of sampled products were created in the last 30 days, so roughly
1,000 new products a month (the sample leans towards newer products).

| Item | Volume | Cost |
|---|---|---|
| Daily listing refresh via the search service | about 10 direct calls per run | No Zyte cost; a few minutes of Fargate |
| API key refresh | one Zyte page fetch, only when the key is rejected | Negligible |
| Product pages, first run (one-off) | about 7,800 Zyte plain fetches | $1 to $10 |
| Product pages, ongoing | about 1,000 a month | $0.15 to $1.30 a month |
| Fargate for the first product-page run | roughly 9 to 17 hours at about $0.025 an hour | under $0.50, one-off |
| Image storage | about 39,000 images; size per image not measured | well under $1 a month at about 6 GB |

Totals: about **$2 to $11 one-off**, then **about $1 to $3 a month** (per month, with a daily run). Skipping
product pages (listing data and its 4 images only) makes Zyte cost zero.

Not included: whether Cettire's image CDN can be downloaded directly
(untested), and dbt / Athena cost for the extra rows.

---

### Affiliate feed check (2026-11-14, web search only)

- Cettire runs an affiliate programme. Public directories list it on
  **Partnerize** (about 5% revenue share, 30-day cookie) and BlueAff as open,
  FlexOffers as closed, and on link-monetisation networks (Sovrn/VigLink,
  Cuelinks). Reported commission rates conflict (4%, 5%, 12%).
- **No public listing mentions a product feed.** Whether Cettire publishes
  one is only visible inside the network after approval.
- No listing mentions Saudi Arabia or Middle East publishers.
- Not easy access: it needs an application and approval, and Partnerize is
  described as selective with new publishers.
- Next step is the user's: apply through Partnerize (or ask Cettire's
  affiliate team) and ask specifically for a product feed with SAR prices
  and Arabic titles.

---

## Phase 0 checklist (original; see probe results above for what is answered)

Follow `context/crawling_methodology.md`. Write `scripts/probe_cettire.py`
in the style of `scripts/probe_bloomingdales.py` and record results in a
"Probe Results" table in this ticket.

### 0.1 Is Zyte necessary? (the main question)

Walk the methodology's decision tree and record the answer for each row:

| Check | How | Result |
|---|---|---|
| Direct request, laptop | plain `curl` / `requests` to the home page, a handbag listing, a product page | |
| Direct request, AWS | same three URLs from an ECS task in `eu-central-1` (data-centre IPs are often treated differently from a home connection) | |
| Direct request at crawl volume | ~200 requests at the crawler's normal pace (`DOWNLOAD_DELAY = 1`), watch for 403 / 429 / challenge pages appearing part-way | |
| WAF identified | response headers (`cf-ray`, `x-akamai-*`, ...) | |
| Zyte `httpResponseBody` | only if direct fails | |
| Zyte `browserHtml` | only if Zyte HTTP fails; document cost | |

Zyte counts as **not necessary** only if the AWS and crawl-volume rows pass,
not just the laptop row.

Also check whether Saudi prices depend on where the request comes from. If
SAR prices only appear for a Saudi IP, Zyte with Saudi geolocation
(`CRAWLER_API_ZYTE_GEOLOCATION_BY_HOST`) is needed for correctness even if
the site does not block us.

### 0.2 Saudi storefront, currency and language

- How is the Saudi storefront selected: URL path, subdomain, cookie, or IP?
- Are prices shown in SAR, and are they final prices (duties and taxes
  included) or does checkout add to them?
- Cettire has Arabic, English and a Saudi storefront (confirmed by the user,
  2026-11-14; not yet checked by a request). How is language selected (path,
  subdomain, cookie) and do AR and EN share a product ID?

### 0.3 Where the data lives

- Is product data in the page HTML, in embedded JSON, or loaded from an API
  (the site's own or a search provider)? Check the network tab.
- Does the listing or API response carry everything the product schema needs
  (`ecommercecrawl/constants/product_schema.py`): id, name, brand, price,
  was-price, currency, category, subcategory, stock, images?
- How does pagination work and what is the page size?
- How many women's handbags does the Saudi storefront list in total?

### 0.4 Images

- Image count per product, URL format, and whether the listing exposes the
  full gallery or only the first image.

### 0.5 robots.txt and terms

- Record what `robots.txt` says about listing and product paths, and any
  crawl-delay.

---

## Build plan (only after Phase 0 passes)

Follow the existing spider → quality gate → image pipeline pattern.

1. **Spider and rules**: `ecommercecrawl/spiders/cettire_crawl.py`,
   `ecommercecrawl/rules/cettire_rules.py`, with fixture-based tests.
2. **Listing-first if the listing data is complete.** The Ounass
   PLP-efficient crawl reads 99% of products from listing pages; Level Shoes
   fetches one page per product and takes 72 of the flow's 86 minutes. If
   Cettire's listing or API carries the full schema, crawl listings and fetch
   product pages only for what the listing lacks.
3. **Category must never be blank.** 65 Level Shoes products are dropped from
   gold because the site's listing data has no category for them and the
   crawler has no fallback. For Cettire, fall back to the category of the
   seed listing the product was found on.
4. **Sale prices**: confirm `was_price` and `price_discount` are populated on
   at least one discounted product, with a test. Return `0`, not `None`, for
   "no discount" (see the 2026-10-29 Ounass fix in `context/memory.md`).
5. **Zyte routing**: per the Phase 0 answer. If direct works, make sure the
   Cettire hosts are not routed through Zyte.
6. **Seeds**: Saudi women's handbag listings, AR and EN, added to
   scraper-pipeline's `crawl_plp_registry.csv` (that repo's change; give its
   session a heads-up per `context/AGENTS.md`).
7. **Quality gate**: default rule set; list field exceptions explicitly.
8. **Docs**: site appears in `docs/crawl_run_status.md` where sites are
   listed; update `context/REPO_CHARTER.md` site list.
9. **Downstream (scraper-pipeline)**: brand, category and subcategory
   mappings for the new site; Cettire will bring many brand spellings.
10. **Rollout**: `make crawl-flow CRAWL_LIMIT=1 STOP_AFTER=crawls`, then a
    full run, then confirm products reach gold with images.

---

## Done when

- Phase 0 table is filled in and the Zyte question has a recorded answer.
- A full crawl of Saudi women's handbags publishes with `run_status: success`.
- Crawled products appear in `gold_product_serving_latest` with images, and
  the count is reported next to Ounass and Level Shoes.
- AR and EN rows share a product ID.

---

## Open questions

- Are Cettire's Saudi prices duty-inclusive? If not, they are not comparable
  with Ounass and Level Shoes prices and the site must say so.
- Catalogue churn: how fast do products appear and sell out, and is a daily
  crawl enough?
- Keep or retire Bloomingdale's once Cettire is live.
