# Ticket: Cettire Crawler (Saudi handbags, AR + EN)

**Status: open; probed 2026-11-14; English first with the plain fetch; listing source still to find**

**Site**: https://www.cettire.com/sa/ (country is a URL path)  
**Languages**: EN in the page data; AR is applied in the browser (see probe results)  
**Country**: SA  
**Currency**: SAR (confirmed)  
**Scope**: women's handbags only, Arabic and English  
**Platform**: Next.js front end on a Reaction Commerce GraphQL back end, CloudFront, DataDome bot protection  
**Probe date**: 2026-11-14 (through Zyte from the dev crawler ECS task; pages kept under `s3://price-comparison-bucket-eu-central-1/probes/dev/cettire/`)

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

### Still to probe (English-first scope)

1. How the listing grid gets its products (capture only the product query),
   page size, and total women's handbags for Saudi.
2. Zyte success rate over ~100 requests, and cost per 1,000 successful pages
   for HTTP mode against browser mode.
3. **Direct requests without Zyte**, from a laptop and from AWS, at crawl
   pace. If they work, drop Zyte for this site (Decision 3).

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
