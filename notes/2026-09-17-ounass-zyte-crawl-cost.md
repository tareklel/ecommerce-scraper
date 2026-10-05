# Note: Ounass Zyte Crawl Cost — `women/bags`, Saudi

**Date:** 2026-09-17
**Scope:** Ounass only (Level Shoes and Bloomingdale's don't use Zyte, so they're
out of scope for this cost model). Single category (`women/bags`), single TLD
(`en-saudi.ounass.com` / `saudi.ounass.com`, i.e. Saudi), for now.

## Inputs

- **Zyte per-request cost**, from actual billing: $0.0646 for 148 requests →
  **$0.0004365/request** (~$0.437 / 1,000 requests). All requests observed used
  `httpResponseBody`; none used `browserHtml` (see `ecommercecrawl/crawler_api/zyte_api.py`
  and the `OUNASS_PDP_BROWSER_HTML_FALLBACK` setting added 2026-09-16 — Ounass
  PDPs don't need browser rendering).
- **`women/bags` category size**, live-checked via `https://en-saudi.ounass.com/api/women/bags`
  (plain `curl`, no Zyte spend): `hitsPerPage: 48`, `totalPages: 137` →
  **6,545 total products**. This corrects an earlier estimate of ~160/6,160 —
  use the live `totalPages × hitsPerPage` going forward, not a fixed number,
  since inventory drifts.
- **PLP hit payload already contains price + stock**: sampled a PLP hit and
  confirmed it includes `price`, `isInStock`, and a full `sizesById` map with
  per-size `isInStock` / `stock.maxAvailableQty`. A PLP page request gives
  price *and* size-level stock for every product on it — no PDP crawl needed
  to refresh price/stock on products still listed. PDP is only required for
  (a) initial full text/image capture and (b) confirming status of a product
  that has disappeared from the PLP entirely.

## Cost model — efficient (PLP-first) strategy

| Component | Requests | Frequency | Monthly requests | Cost |
|---|---|---|---|---|
| Daily PLP sweep (1 language, price+stock refresh) | 137/sweep | daily × 31 | 4,247 | $1.85 |
| PDP confirm for delisted items | 1/item | ~200/month | 200 | $0.09 |
| New-product full PDP capture (2 languages) | 2/item | ~200 new/month | 400 | $0.17 |
| **Steady-state monthly total** | | | **4,847** | **≈ $2.12** |

**One-time baseline** to seed the full catalog in both languages:
6,545 × 2 (PDP) + 137 × 2 (PLP) = 13,364 requests ≈ **$5.83**, once.

## Cost model — naive (full PDP re-crawl) strategy, for comparison

Full PDP re-crawl of every product, both languages, every day:
6,545 × 2 × 31 = 405,790 PDP requests/month ≈ $177, plus PLP overhead
(137 × 2 × 31 = 8,494 requests ≈ $3.71) → **≈ $180.9/month**.

**The PLP-first approach is ~85x cheaper** than daily full PDP re-crawl, for
this one category alone.

## Follow-ups

- This is `women/bags` only. A full-site monthly estimate needs product
  counts for every other category/designer path crawled — can be pulled the
  same way (direct `curl` against the `/api/...` PLP endpoints, zero Zyte
  spend) if/when needed.
- See `tickets/ounass_plp_efficient_crawl.md` for the crawler-side design to
  actually implement this (PLP-extract-without-PDP path, delisted-item
  confirmation pass, and the scraper-pipeline dependency it requires).
