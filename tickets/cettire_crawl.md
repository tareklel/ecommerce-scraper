# Ticket: Cettire Crawler (Saudi handbags, AR + EN)

**Status: open, not started** (written 2026-11-14)

**Site**: https://www.cettire.com (Saudi storefront URL to confirm in the probe)  
**Languages**: AR and EN (user-confirmed 2026-11-14)
**Country**: SA
**Currency**: SAR (to confirm)
**Scope**: women's handbags only, Arabic and English
**Probe date**: not probed yet

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

## Nothing below is verified yet

No request has been made to Cettire. The cloud agent session that wrote this
ticket could not reach `www.cettire.com` (blocked by that session's network
policy, not by Cettire), so every site fact here is a question for Phase 0.

---

## Phase 0: feasibility probe (do this first, no spider code before it)

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
