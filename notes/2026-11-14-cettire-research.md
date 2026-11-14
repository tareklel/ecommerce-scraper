# Cettire research (2026-11-14)

**What this is:** everything learned about Cettire while deciding whether and
how to add it as a fourth site (Saudi, women's handbags). It is a record of
findings and evidence for future analysis. The work to be done lives in
`tickets/cettire_crawl.md`; the decisions are repeated here for context.

**How the evidence was gathered.** The agent session could not reach
`cettire.com` itself, so every request ran inside the dev crawler ECS task
(`ecommerce-scraper`, AWS `eu-central-1`) with a command override:

- 29 requests through Zyte (plain HTTP mode and browser mode, some with
  network capture), plus retries on Zyte `520 Website Ban`.
- 14 direct requests without Zyte: 12 to the search service, 2 to pages.
- Our own sites were read from `gold_product_serving_latest` (dev) and from
  the bronze files of flow run `d66af788` (2026-11-13).

Raw responses are kept under
`s3://price-comparison-bucket-eu-central-1/probes/dev/cettire/` (`r1` to `r9`
through Zyte, `d1` to `d4` direct). The request files that held the site's
API key were deleted after each run.

**Sample caveat.** Catalogue statistics come from about 2,270 of the roughly
9,500 Saudi women's shoulder bags (the 1,000 top-ranked, the three largest
brands, the 158 smallest brands, one mid-size brand) plus the site's own
facet counts for the whole category. Tote bags were not sampled by brand.

---

## 1. Why Cettire

Bloomingdale's returns too few products. Flow run `d66af788`, shoulder and
tote bag listings:

| Site | Products | Rows (AR + EN) |
|---|---|---|
| Ounass | about 3,100 | 6,219 |
| Level Shoes | 2,140 | 4,280 |
| Bloomingdale's | 59 | 118 |

## 2. Site architecture

| Aspect | Finding |
|---|---|
| Front end | Next.js 7 (`x-powered-by: Next.js 7.0.3`), page data in a `__NEXT_DATA__` script |
| Back end | Reaction Commerce GraphQL at `api.cettire.com/graphql` (IDs are base64 `reaction/...`) |
| Listing search | Separate service: `search.cettire.com/search-ai/pro-search/api/aiRecommendForProduct` |
| Translation | `translate.cettire.com` (`/translate`, `/category`, `/navigation`) translates UI strings in the browser |
| CDN and images | CloudFront; product images on `d3vfig6e0r0snz.cloudfront.net` |
| Bot protection | DataDome on `www.cettire.com` (`datadome` cookie, `x-datadome: protected`). Not on `search.cettire.com` |
| Country | URL path: `/sa/collections/...`, `/sa/products/...`; response sets `spc-code=SA`, `spc-cur=SAR`, `spc-nat` |
| Language | Cookie `spc-lng` (`en` / `ar`) and `next-i18next`, not the URL. `/sa/` pages render with `lang="ar"` and RTL by default |
| Product ID | Numeric suffix of the URL slug (`...-967213750`); same URL for both languages |
| Product URL | `/sa/products/<handle>`; the server redirects to `/sa/products/<handle>/<variantId>` |
| Bag collections | `/collections/womens-bags/shoulder-bags`, `/collections/womens-bags/tote-bags` (also backpacks, belt-bags, clutch-bags, crossbody-bags, luggage-and-travel) |

### robots.txt

- No crawl-delay. `Sitemap: https://www.cettire.com/sitemap.xml`.
- Allows `/products`, `/collections`, `/pages` and the same under 67 country
  prefixes including `/sa/`, `/ae/`, `/kw/`, `/qa/`, `/bh/`, `/om/`.
- Disallows 168 other country prefixes, `/graphql` (and `-alpha`, `-beta`,
  `/graphiql`), `/productgrid`, cart, checkout, account and login paths.
- It covers `www.cettire.com` only; `search.cettire.com` and
  `api.cettire.com` are separate hosts whose robots files were not fetched.

### Sitemaps

- Index lists 197 files: products, collections and pages, each in a default
  set and `gb`, `au`, `ca` sets. No Saudi set.
- 48 default product files of 10,000 URLs each (about 480,000 products).
  Entries have the URL (no country prefix), one shared `lastmod`, an image URL
  and title. No category or gender; 708 of the first 10,000 slugs contain
  "bag".
- 4,834 collection URLs.
- Conclusion: the sitemap is not a practical way to find Saudi women's
  handbags.

## 3. Access: what works from where

| Target | Direct from AWS | Zyte plain HTTP | Zyte browser |
|---|---|---|---|
| `robots.txt`, sitemap index | not tested | 2 of 2 | not needed |
| Gzipped sitemaps | not tested | intermittent `520` | not needed |
| Product page | **403** DataDome | works, 1 to 4 attempts | works |
| Listing page | **403** DataDome | works, but the HTML has no products | works (shows 9 products without interaction) |
| Search service | **200**, 12 of 12 | not needed | captured from the browser |

- Zyte plain HTTP, first runs without retries: 4 of 12 page and sitemap
  fetches succeeded, the rest `520 Website Ban`, with and without Saudi
  geolocation. With up to four attempts, every later fetch succeeded
  (attempt counts seen: 1, 1, 1, 2, 2, 3, 4).
- A browser-mode request to a listing URL with `?page=2` returned a
  non-temporary Zyte ban ("check your URL query parameters").
- No request has been made from a laptop or home connection.

## 4. Product pages (PDP)

Plain HTML contains everything in `__NEXT_DATA__` under
`props.apolloState.data`. No JSON-LD. Three products checked.

| Data | Where | Notes |
|---|---|---|
| Title, description | `CatalogProduct.title`, `.description` | English only in the HTML |
| Brand | `CatalogProduct.vendor` | |
| Category | `CatalogProduct.productType`; `Tag` objects (e.g. Women, Bags, Crossbody Bags, Season_FW26) | |
| Stock | `CatalogProduct.isSoldOut`, `isLowQuantity`; `CatalogProductVariant.inventoryAvailableToSell` | |
| Variant | `CatalogProductVariant.size`, `.color`, `.barcode` | Bags are "Only One Size" |
| Model | `designerModelNumber`, `designerColor` | Possible key for matching products across sites |
| Other | `composition`, `madeIn`, `dimensions`, `highlights` | |
| Price | `CurrencyPriceInfo` list on the variant: `price`, `compareAtPrice`, `currencyCode`, `regionCode` | One entry per region (69 on one page). Saudi is `regionCode: "sa"`, `currencyCode: "SAR"`. No Saudi IP or cookie needed |
| Images | `ImageSizes` under `media` | 4 to 6 per product, sizes `small` / `medium` / `large` / `original` |

- Prices agree with the listing data (Totême T-Lock: SAR 4,269, was 6,143 in
  both; Jacquemus Bambino: 2,871, was 4,242).
- Saudi prices include duties and taxes: the API returns
  `priceIncludeTax: true` for `SA`, and the page says
  "شامل الرسوم الجمركية والضرائب".
- **Arabic**: the server-rendered HTML always requests `en_US`
  (`catalogItemProduct(... userPrefer: {lang: "en_US"})`), even with
  `spc-lng=ar` and `next-i18next=ar` cookies. In a browser the page re-queries
  the GraphQL API and receives a `lang` object with `lang: "ar_SA"` and an
  Arabic `title` and `description`. So Cettire stores Arabic product text, but
  it is not in the plain HTML.

## 5. Listing pages (PLP)

- Plain HTML of three listing pages contained **no products**, only the
  collection's tags (`tag`, `tags` queries).
- The grid is filled in the browser by the search service (section 6), not by
  the GraphQL API.
- The page shows a "تحميل المزيد" (Load more) button; there are no page links.

## 6. The search service

`POST https://search.cettire.com/search-ai/pro-search/api/aiRecommendForProduct`

Headers the site sends: `content-type: application/json`, `x-api-key`,
`origin` and `referer` of `https://www.cettire.com`, browser `user-agent`.
The key is published in every page's config:
`__NEXT_DATA__.runtimeConfig.searchAIAPIKey`. It did not change during the
day of testing. It is not recorded in this repo.

Request body as captured from the site (IDs removed):

```json
{"userVipLevel": 0, "countryCode": "SA", "regionCode": "sa",
 "currencyCode": "SAR", "langCode": "ar",
 "requestId": "<40 hex>", "deviceInfo": {"sessionId": "<uuid>", "deviceId": "<64 hex>"},
 "productQueryInfo": {"query": "", "rankingType": "rank_score",
   "department": "women", "catQuery": "bags", "subCatQuery": "shoulder bags",
   "cat3Query": "", "designNumberQuery": "", "tagQuery": [], "seasonQuery": [],
   "vendorQuery": [], "colorQuery": [], "sizeQuery": [],
   "comparePriceQuery": false, "pageSize": 96, "rollbackRequest": false,
   "returnCat3Facets": true, "returnHMFacet": true, "currentPage": 0},
 "blockProductRules": []}
```

Response: `result`, `totalNumber`, `remainNumber`, `prodSearchId`,
`productQueryInfo` (an echo that always shows `pageSize: 20`,
`currentPage: 0`), `products`, `facets`.

Each product has `repProductId`, `repVariantId`, `price` and a `variantData`
object with 51 fields:

| Group | Fields |
|---|---|
| Identity | `product_id`, `objectID`, `handle` (URL slug with the numeric ID), `designerModelNumber`, `designerColor` |
| Names | `title`, `title_ar` (only with `langCode: "ar"`), `variant_title` |
| Brand | `vendor`, `vendor_ar`, `vendor_handle` |
| Category | `category`, `category_ar` and 9 more languages, `category3`, `product_type`, `product_type_ar`, `department` (list), `tags` |
| Price | `sa_sar_price_f`, `sa_sar_compare_at_price_f` (blank when not on sale), `www_usd_price_f`, `www_usd_compare_at_price_f` |
| Stock | `inventory_quantity`, `old_inventory_quantity`, `is_global_inventory`, `available_regions` (empty when global), `visibility`, `finalSales`, `finalSaleRegions` |
| Variant | `Color`, `Size` |
| Images | `largeImage`, `image_set2_url`, `media_medium`, `set3_medium`, `product_images` (1 URL) |
| Dates | `created_at`, `updated_at`, `published_at` |
| Other | `position`, `vipLevel` |

Facets returned: `product_type`, `vendor`, `color`, `size`, `department`,
`tags`, `category3`.

Behaviour found by testing:

| Test | Result |
|---|---|
| `langCode: "en"` | `title` only; `title_ar` absent |
| `langCode: "ar"` | both `title` and `title_ar` |
| `currentPage: 1` without `requestId` / `deviceInfo` | same 96 products as page 0 |
| `currentPage: 1` with them | 60 new products of 96 |
| `currentPage: 2` with them | identical to page 1 |
| `pageSize: 1000` | 1,000 unique products in one response (2.5 MB) |
| `pageSize: 10000` | not run (blocked by the agent session's safety check) |
| `vendorQuery: ["Totême"]` | 28 products, all Totême |
| `vendorQuery: ["toteme"]` (handle) | 0 products |
| `vendorQuery` with 3 or 162 brand names | only those brands, all Shoulder Bags, no duplicates |
| Products returned against `totalNumber` | 910 of 923, 420 of 427, 28 of 29: about 1.5% short, cause unknown |

Field completeness on 96 items: no blanks in title, title_ar, vendor,
product_type, category, handle, SAR price, stock, colour, size, main image,
model number; `sa_sar_compare_at_price_f` blank on 8 (full price).

## 7. Catalogue size and shape (Saudi, women)

Product-type facet for women's bags:

| Type | Products |
|---|---|
| Shoulder Bags | 9506 |
| Tote Bags | 8218 |
| Clutch Bags | 1736 |
| Crossbody Bags | 1314 |
| Bag Accessories | 740 |
| Backpacks | 393 |
| Luggage And Travel | 326 |
| Belt Bags | 92 |

Shoulder bags in detail:

- **319 brands.** The top 10 hold 26% of products, the top 50 hold 69%;
  144 brands have five products or fewer.
- **Colours**: black 2,890, brown 2,215, beige 1,084, red 667, green 481,
  white 407.
- **Not expired stock**: every sampled product has `inventory_quantity` of at
  least 1 and `visibility: YES`; 65 to 70% were created in 2026; most carry
  `Season_FW26`.
- **Thin stock**: about a third of sampled products have exactly one unit;
  median 2. This fits a retailer listing boutique inventory rather than its
  own warehouse, which is an interpretation, not something the data proves.
- **Colours are separate products**: 2,268 sampled products are 1,649 distinct
  brand-and-model pairs; one Pinko model appears in 14 colours.
- **Discounting**: 88 to 97% of sampled products have a was-price.
- **Price (SAR)**: top-ranked 1,000: median 4,605 (10th percentile 1,457, 90th
  10,979); three largest brands: median 1,276; 158 smallest brands: median
  1,482.
- **New products**: 13.4% of the sample was created in the last 30 days
  (1.8% in the last 7). The sample leans towards newer products.
- **Listing images**: 4 per product on 97.5% of the sample.

## 8. Brand overlap with our sites

Our brands are from gold (dev, English rows, all bag subcategories): Level
Shoes 92 brands / 2,159 products; Ounass 128 brands / 3,401 products. Cettire
counts are shoulder bags only. Matching is by normalised brand name with a
few aliases (`Valentino Garavani` = `Valentino`, `McQueen` =
`Alexander McQueen`, `Michael Kors` = `Michael Michael Kors`,
`Kate Spade New York` = `Kate Spade`). Product-level overlap was not measured.

| Set | Brands on Cettire | Cettire shoulder bags |
|---|---|---|
| Level Shoes brands | 64 of 92 | 4175 (44%) |
| Ounass brands | 80 of 128 | 5391 (57%) |
| Level Shoes or Ounass | 96 | 5901 |
| On neither | 223 | 3605 |

Level Shoes brands not found on Cettire (their Level Shoes product counts):
State Of Escape (24), Aquazzura (22), DeMellier (21), The Jacksons (19), Tammy & Benjamin (16), Monfaradi Mare (12), Louis Vuitton Pre-Loved (9), Makette (9), Vonto (7), Hai (7), DOTTHZ (7), Chanel Pre-Loved (7), Advene (4), St Agni (3), Dania Shinkar (3), Hermès Pre-Loved (3), Rosantica (2), Dior Pre-Loved (2), Poolside (2), Vanina (2), Studio Amelia (1), Loeffler Randall (1), TOUCHLESS (1), Ahikoza (1), Palera Milano (1), Olympia Le Tan (1), Puma (1), Jellycat (1).

Ounass brands not found on Cettire (their Ounass product counts): Fauré Le Page (76), DeMellier (53), Freja NYC (29), 0711 Tbilisi (27), FENDI Pre-Loved (24), Dior Pre-Loved (19), Chanel Pre-Loved (19), Gucci Pre-Loved (14), MANC (14), Louis Vuitton Pre-Loved (13), Gabriele Frantzen (12), Serapian (11), Cooperative Studio (11), BOSS (10), Aspinal of London (10), Loeffler Randall (10), BVLGARI (9), Talel (8), Reformation (8), ALEMAIS (7), Maison de Sabré (6), 3.1 Phillip Lim (6), Celine Pre-Loved (5), Studio Amelia (5), Aquazzura (5), Hermès Pre-Loved (4), Dolce Vita (4), Pucci (4), St Agni (3), Okhtein (3), MACH & MACH (3), Rue de Verneuil (3), Hunting Season (2), Prada Pre-Loved (2), Veronica Beard (2), Malone Souliers (2), Adanola (2), Maje (2), René Caovilla (2), Goyard Pre-Loved (2), Bottega Veneta Pre-Loved (1), Golden Goose (1), SKIMS (1), Versace Pre-Loved (1), Valentino Garavani Pre-Loved (1), Sensi Studio (1), SANDRO (1), Rosantica (1).

### Level Shoes brands on Cettire (the allowlist)

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

### Ounass brands on Cettire

| Cettire brand | Cettire shoulder bags | Ounass bags (all types) |
|---|---|---|
| Pinko | 316 | 12 |
| Valentino | 275 | 71 |
| Saint Laurent | 237 | 161 |
| Furla | 235 | 7 |
| Marc Jacobs | 215 | 137 |
| Michael Michael Kors | 212 | 123 |
| Love Moschino | 207 | 47 |
| Prada | 201 | 85 |
| Tory Burch | 187 | 91 |
| Themoirè | 187 | 4 |
| Chloé | 164 | 88 |
| Stella McCartney | 145 | 39 |
| Balenciaga | 137 | 28 |
| Dragon Diffusion | 110 | 15 |
| Gucci | 109 | 125 |
| Jacquemus | 108 | 115 |
| Margesherwood | 103 | 21 |
| Alaïa | 99 | 79 |
| Jil Sander | 97 | 7 |
| Ferragamo | 90 | 17 |
| Ganni | 89 | 19 |
| Burberry | 87 | 20 |
| Loewe | 83 | 92 |
| Miu Miu | 75 | 34 |
| Tod's | 73 | 21 |
| Balmain | 71 | 3 |
| Marni | 68 | 10 |
| Givenchy | 64 | 14 |
| Maison Margiela | 59 | 13 |
| Benedetta Bruzziches | 57 | 8 |
| Rabanne | 56 | 8 |
| Versace | 55 | 30 |
| Alexander McQueen | 53 | 9 |
| Bottega Veneta | 50 | 93 |
| Coach | 48 | 210 |
| Dolce & Gabbana | 48 | 9 |
| Hogan | 45 | 1 |
| MCM | 44 | 69 |
| Khaite | 44 | 11 |
| Yuzefi | 40 | 36 |
| Kate Spade | 40 | 172 |
| Staud | 39 | 78 |
| The Attico | 39 | 18 |
| Longchamp | 38 | 148 |
| Victoria Beckham | 33 | 3 |
| Elisabetta Franchi | 31 | 6 |
| Emporio Armani | 29 | 86 |
| Totême | 29 | 20 |
| Tom Ford | 29 | 5 |
| Soeur | 29 | 2 |
| Osoi | 28 | 19 |
| Polo Ralph Lauren | 28 | 11 |
| AMI | 28 | 6 |
| Off-White | 28 | 2 |
| Manu Atelier | 27 | 15 |
| Jimmy Choo | 23 | 85 |
| Lemaire | 23 | 9 |
| Max Mara | 21 | 6 |
| Hereu | 20 | 2 |
| Christian Louboutin | 19 | 24 |
| Alexander Wang | 19 | 2 |
| Self-Portrait | 19 | 1 |
| Armani Exchange | 18 | 24 |
| Savette | 18 | 10 |
| JW Anderson | 15 | 15 |
| Bally | 12 | 8 |
| Naghedi | 10 | 24 |
| Dries Van Noten | 9 | 1 |
| JW PEI | 7 | 54 |
| Giorgio Armani | 7 | 13 |
| Brunello Cucinelli | 7 | 10 |
| Amina Muaddi | 7 | 1 |
| Zimmermann | 5 | 6 |
| Kenzo | 5 | 3 |
| Elleme | 3 | 9 |
| Loulou De Saison | 2 | 4 |
| Strathberry | 1 | 42 |
| Boyy | 1 | 12 |
| Missoni | 1 | 3 |
| Neous | 1 | 1 |

## 9. Affiliate programme (web search only)

- Cettire runs one. Directories list it on Partnerize (about 5% revenue share,
  30-day cookie) and BlueAff as open, FlexOffers as closed, and on
  link-monetisation networks (Sovrn/VigLink, Cuelinks). Reported commission
  rates conflict (4%, 5%, 12%).
- No public listing mentions a product feed, or Saudi or Middle East
  publishers. A feed can only be confirmed after approval.
- Sources: [FlexOffers](https://www.flexoffers.com/affiliate-programs/cettire-affiliate-program/),
  [affi.io](https://affi.io/m/cettire),
  [Affilitizer](https://www.affilitizer.com/programs/cettire.com),
  [Cuelinks](https://www.cuelinks.com/campaigns/cettire-affiliate-program),
  [Sovrn/VigLink](https://www.viglink.com/merchants/124028/cettire-affiliate-program).

## 10. Cost estimate (allowlisted crawl)

Assumes about 7,800 products (4,175 shoulder bags counted, about 3,600 tote
bags estimated), Zyte pay-as-you-go plain HTTP at $0.13 to $1.27 per 1,000
successful requests depending on tier (Cettire's tier unknown; prices from a
web search, not the Zyte account), and about 1,000 new products a month.

| Item | Volume | Cost |
|---|---|---|
| Daily listing refresh via the search service | about 10 direct calls per run | No Zyte cost |
| API key refresh | one Zyte page fetch when the key is rejected | Negligible |
| Product pages, first run | about 7,800 Zyte plain fetches | $1 to $10, one-off |
| Product pages, ongoing | about 1,000 a month | $0.15 to $1.30 a month |
| Fargate for the first product-page run | roughly 9 to 17 hours | under $0.50, one-off |
| Image storage | about 39,000 images, size not measured | well under $1 a month |

Totals: about $2 to $11 one-off, then about **$1 to $3 a month** with a daily
run. Browser rendering was rejected by the user on cost grounds.

## 11. Compliance and risk notes

- The chosen route calls the site's internal search service with the key its
  pages publish, rather than reading public pages. The agent session's safety
  check classified those calls as unauthorized access twice; the first ran
  only after the user's explicit permission, and a whole-category
  (`pageSize: 10000`) call was not run.
- `robots.txt` on the main host disallows `/graphql` and `/productgrid`; it
  says nothing about the search host.
- Cettire's terms of use were not read.
- Advice given to the user: keep volume low (about 10 calls a run, paced),
  send the request the site's own page sends, read the key from the page
  rather than hard-coding it, do not rotate IPs or fake device identities,
  and pursue the affiliate programme in parallel.

## 12. Decisions taken (user, 2026-11-14)

1. English first; the search service returns Arabic names in the same call,
   so names in both languages come for free. Arabic descriptions deferred.
2. No browser rendering.
3. Read listings from the search service directly, `pageSize` up to 1,000,
   split by brand groups.
4. Store the API key; refresh from a page through Zyte only when rejected.
5. Allowlist: brands Level Shoes carries (64 brands, list above).
6. Zyte only where needed: product pages (plain HTTP) and the key refresh.

## 13. Open questions

- Tote-bag brand breakdown and exact allowlisted count.
- The 1.5% shortfall between products returned and `totalNumber`.
- Whether sold-out products stay in search results.
- How often the API key changes.
- Real new-product rate per day.
- Whether the image CDN allows direct downloads.
- Zyte tier and real price for Cettire product pages.
- Product-level overlap with Level Shoes and Ounass (model number looks
  usable as a key).
- First run: product pages for all products, or listing data only.

## Appendix: all 319 Cettire shoulder-bag brands (Saudi, women)

| Brand | Shoulder bags | On Level Shoes | On Ounass |
|---|---|---|---|
| Coccinelle | 333 |  |  |
| Pinko | 316 |  | yes |
| Valentino | 275 | yes | yes |
| Zanellato | 260 |  |  |
| Saint Laurent | 237 | yes | yes |
| Furla | 235 |  | yes |
| Marc Jacobs | 215 | yes | yes |
| Michael Michael Kors | 212 | yes | yes |
| Love Moschino | 207 |  | yes |
| Prada | 201 | yes | yes |
| Themoirè | 187 |  | yes |
| Tory Burch | 187 | yes | yes |
| Chloé | 164 | yes | yes |
| V73 | 162 |  |  |
| Gianni Chiarini | 153 |  |  |
| Kurt Geiger | 150 |  |  |
| Stella McCartney | 145 | yes | yes |
| Balenciaga | 137 | yes | yes |
| Isabel Marant | 134 |  |  |
| Orciani | 124 |  |  |
| Diesel | 121 | yes |  |
| Liu Jo | 119 |  |  |
| A.P.C. | 117 |  |  |
| Vivienne Westwood | 113 | yes |  |
| Dragon Diffusion | 110 | yes | yes |
| Gucci | 109 | yes | yes |
| Jacquemus | 108 | yes | yes |
| Margesherwood | 103 | yes | yes |
| Alaïa | 99 | yes | yes |
| Jil Sander | 97 | yes | yes |
| Etro | 94 |  |  |
| Ferragamo | 90 | yes | yes |
| Ganni | 89 | yes | yes |
| Burberry | 87 | yes | yes |
| Loewe | 83 |  | yes |
| Miu Miu | 75 | yes | yes |
| Hidesins | 74 |  |  |
| Tod's | 73 | yes | yes |
| Balmain | 71 | yes | yes |
| Marni | 68 |  | yes |
| Fendi | 66 | yes |  |
| Courrèges | 65 |  |  |
| Moschino | 65 |  |  |
| Givenchy | 64 | yes | yes |
| Mc2 Saint Barth | 64 |  |  |
| Zadig & Voltaire | 62 |  |  |
| Wandler | 61 |  |  |
| Maison Margiela | 59 |  | yes |
| Kurt Geiger London | 58 |  |  |
| Benedetta Bruzziches | 57 |  | yes |
| Mulberry | 57 | yes |  |
| Rabanne | 56 |  | yes |
| Versace | 55 | yes | yes |
| Alexander McQueen | 53 | yes | yes |
| Bottega Veneta | 50 | yes | yes |
| Coach | 48 |  | yes |
| Dolce & Gabbana | 48 | yes | yes |
| Roberto Cavalli | 48 |  |  |
| Biasia | 46 |  |  |
| Hogan | 45 | yes | yes |
| Khaite | 44 | yes | yes |
| MCM | 44 |  | yes |
| Kate Spade | 40 |  | yes |
| Yuzefi | 40 | yes | yes |
| Aesther Ekme | 39 |  |  |
| Staud | 39 | yes | yes |
| The Attico | 39 | yes | yes |
| Longchamp | 38 |  | yes |
| Marc Ellis | 37 |  |  |
| My Best Bag | 37 |  |  |
| Karl Lagerfeld | 35 |  |  |
| Allsaints | 34 |  |  |
| Coperni | 34 |  |  |
| By Far | 33 |  |  |
| Victoria Beckham | 33 |  | yes |
| Borbonese | 32 |  |  |
| Elisabetta Franchi | 31 | yes | yes |
| Emporio Armani | 29 |  | yes |
| Soeur | 29 |  | yes |
| Tom Ford | 29 |  | yes |
| Totême | 29 | yes | yes |
| AMI | 28 | yes | yes |
| La Carrie | 28 |  |  |
| Michael Kors | 28 |  |  |
| Off-White | 28 |  | yes |
| Osoi | 28 | yes | yes |
| Polo Ralph Lauren | 28 | yes | yes |
| MM6 Maison Margiela | 27 |  |  |
| Manu Atelier | 27 | yes | yes |
| Paco Rabanne | 27 |  |  |
| Jack Gomme | 25 |  |  |
| Hibourama | 24 | yes |  |
| Majo | 24 |  |  |
| Campomaggi | 23 |  |  |
| Jimmy Choo | 23 | yes | yes |
| Lancel | 23 |  |  |
| Lemaire | 23 |  | yes |
| Patrizia Pepe | 23 |  |  |
| TWINSET | 23 |  |  |
| Acne Studios | 22 | yes |  |
| Francesco Biasia | 21 | yes |  |
| Ibeliv | 21 |  |  |
| Max Mara | 21 |  | yes |
| Hereu | 20 |  | yes |
| Lacoste | 20 |  |  |
| Mino Bossi | 20 |  |  |
| Alexander Wang | 19 | yes | yes |
| Bao Bao Issey Miyake | 19 |  |  |
| Christian Louboutin | 19 | yes | yes |
| Roger Vivier | 19 | yes |  |
| Self-Portrait | 19 | yes | yes |
| Armani Exchange | 18 |  | yes |
| MINOBOSSI | 18 |  |  |
| ROTATE | 18 | yes |  |
| Savette | 18 |  | yes |
| Ermanno Scervino | 17 |  |  |
| Patou | 17 |  |  |
| Philipp Plein | 17 |  |  |
| Samsøe Samsøe | 17 |  |  |
| By Malene Birger | 16 |  |  |
| Vanessa Bruno | 16 |  |  |
| JW Anderson | 15 | yes | yes |
| Anine Bing | 14 |  |  |
| Casadei | 14 |  |  |
| FANE | 14 |  |  |
| Reptile's House | 14 |  |  |
| Cult Gaia | 13 | yes |  |
| Golden Goose Deluxe Brand | 13 |  |  |
| Il Bisonte | 13 |  |  |
| Just Cavalli | 13 |  |  |
| Olend | 13 |  |  |
| Palm Angels | 13 |  |  |
| Pierre Hardy | 13 |  |  |
| Weekend Max Mara | 13 |  |  |
| Bally | 12 | yes | yes |
| Kara | 12 |  |  |
| Lanvin | 12 |  |  |
| Lauren Ralph Lauren | 12 |  |  |
| Alexander Smith | 11 |  |  |
| Amiri | 11 |  |  |
| Guess | 11 |  |  |
| Le Tanneur | 11 |  |  |
| Anya Hindmarch | 10 |  |  |
| Klattermusen | 10 |  |  |
| Naghedi | 10 | yes | yes |
| Casablanca | 9 | yes |  |
| Dries Van Noten | 9 |  | yes |
| Filippo Catarzi | 9 |  |  |
| Liffner | 9 |  |  |
| Manebí | 9 |  |  |
| Marsèll | 9 |  |  |
| Mugler | 9 |  |  |
| Dsquared2 | 8 |  |  |
| Giuseppe Zanotti | 8 |  |  |
| Moncler | 8 |  |  |
| Simone Rocha | 8 | yes |  |
| Simonetta Ravizza | 8 |  |  |
| Trussardi | 8 |  |  |
| ATP Atelier | 7 |  |  |
| Alviero Martini | 7 |  |  |
| Amina Muaddi | 7 | yes | yes |
| Brunello Cucinelli | 7 |  | yes |
| Gimaguas | 7 | yes |  |
| Giorgio Armani | 7 |  | yes |
| Iro | 7 |  |  |
| JW PEI | 7 | yes | yes |
| Magda Butrym | 7 |  |  |
| Rains | 7 | yes |  |
| Schell | 7 |  |  |
| Sprayground | 7 |  |  |
| Yohji Yamamoto | 7 |  |  |
| Dondup | 6 |  |  |
| MM By Max Mara | 6 |  |  |
| Marks & Angels | 6 |  |  |
| Rick Owens | 6 |  |  |
| Amato Daniele | 5 |  |  |
| Discord Yohji Yamamoto | 5 |  |  |
| Ermanno Firenze | 5 |  |  |
| Federico Cina | 5 |  |  |
| Fiorucci | 5 |  |  |
| Kenzo | 5 |  | yes |
| N°21 | 5 |  |  |
| Our Legacy | 5 |  |  |
| Pollini | 5 |  |  |
| Steve Madden | 5 |  |  |
| Thom Browne | 5 |  |  |
| Zimmermann | 5 |  | yes |
| CFCL | 4 |  |  |
| CUBA LAB | 4 |  |  |
| Durazzi Milano | 4 |  |  |
| Essentiel Antwerp | 4 |  |  |
| Fabiana Filippi | 4 |  |  |
| Issey Miyake | 4 |  |  |
| La Milanesa | 4 |  |  |
| MSGM | 4 |  |  |
| Sportmax | 4 |  |  |
| Stand Studio | 4 |  |  |
| The Row | 4 | yes |  |
| Twenty Four Haitch | 4 |  |  |
| Ulla Johnson | 4 |  |  |
| Ann Demeulemeester | 3 |  |  |
| Au Départ | 3 |  |  |
| DKNY | 3 |  |  |
| Dentro | 3 |  |  |
| Elleme | 3 |  | yes |
| Fabi | 3 |  |  |
| Ferragamo Eyewear | 3 |  |  |
| Kiko Kostadinov | 3 |  |  |
| Officine Générale | 3 |  |  |
| Paloma Wool | 3 |  |  |
| Plan C | 3 |  |  |
| Proenza Schouler | 3 |  |  |
| Repetto | 3 |  |  |
| Roberto Festa | 3 |  |  |
| Rouje | 3 |  |  |
| Ruslan Baginskiy | 3 |  |  |
| Sessun | 3 |  |  |
| Silvia Gnecchi | 3 |  |  |
| Studio Nicholson | 3 |  |  |
| Adidas Originals | 2 |  |  |
| Alberta Ferretti | 2 |  |  |
| Ash | 2 |  |  |
| Auralee | 2 |  |  |
| Ballantyne | 2 |  |  |
| Barbour | 2 |  |  |
| Blumarine | 2 |  |  |
| Carlyn | 2 |  |  |
| Chiara Ferragni | 2 |  |  |
| Eastpak | 2 |  |  |
| Erdem | 2 |  |  |
| Gabriela Hearst | 2 |  |  |
| Germanier | 2 |  |  |
| Giancarlo Nevola | 2 |  |  |
| Herno | 2 |  |  |
| Hugo Boss | 2 |  |  |
| Junya Watanabe | 2 |  |  |
| K-Way | 2 |  |  |
| Laneus | 2 |  |  |
| Loulou De Saison | 2 |  | yes |
| Maliparmi | 2 |  |  |
| Marine Serre | 2 |  |  |
| Misbhv | 2 |  |  |
| Miss Sixty | 2 |  |  |
| Munthe | 2 |  |  |
| Nenette | 2 |  |  |
| Niccolò Pasqualetti | 2 |  |  |
| Nike | 2 |  |  |
| Officine Creative | 2 |  |  |
| P.A.R.O.S.H. | 2 |  |  |
| Paul Smith | 2 |  |  |
| Premiata | 2 |  |  |
| Rodo | 2 |  |  |
| Sergio Rossi | 2 |  |  |
| Sundek | 2 |  |  |
| Yves Salomon | 2 |  |  |
| 10 Corso Como | 1 |  |  |
| A.EMERY | 1 |  |  |
| Adidas By Stella McCartney | 1 |  |  |
| Alysi | 1 |  |  |
| Ambush | 1 |  |  |
| Antonelli | 1 |  |  |
| Avenue 67 | 1 |  |  |
| Aya Muse | 1 |  |  |
| Boyy | 1 |  | yes |
| Calcaterra | 1 |  |  |
| Calvin Klein | 1 |  |  |
| Carhartt WIP | 1 |  |  |
| Carven | 1 |  |  |
| Celine | 1 |  |  |
| Collina Strada | 1 |  |  |
| Comme des Garçons Girl | 1 |  |  |
| Destree | 1 |  |  |
| Ea7 Emporio Armani | 1 |  |  |
| Farm Rio | 1 | yes |  |
| Fear Of God Essentials | 1 |  |  |
| ForBitches | 1 |  |  |
| Gedebe | 1 |  |  |
| Gestuz | 1 |  |  |
| Helen Kaminski | 1 |  |  |
| Hervé Chapelier | 1 |  |  |
| John Richmond | 1 |  |  |
| Junya Watanabe MAN | 1 |  |  |
| Justine Clenquet | 1 |  |  |
| Kate Cate | 1 |  |  |
| Knwls | 1 |  |  |
| Lancaster | 1 |  |  |
| Maeden | 1 |  |  |
| Maison Mihara Yasuhiro | 1 |  |  |
| Marimekko | 1 |  |  |
| Medea | 1 |  |  |
| Meli Melo | 1 |  |  |
| Melitta Baumeister | 1 |  |  |
| Miista | 1 |  |  |
| Missoni | 1 |  | yes |
| Moreau Paris | 1 |  |  |
| Muun | 1 |  |  |
| Nanushka | 1 |  |  |
| Neous | 1 | yes | yes |
| Paula Canovas Del Vas | 1 |  |  |
| Pleats Please Issey Miyake | 1 |  |  |
| Porter-Yoshida & Co | 1 |  |  |
| Raf Simons | 1 |  |  |
| Ralph Lauren | 1 |  |  |
| Rebecca Minkoff | 1 |  |  |
| Rick Owens DRKSHDW | 1 |  |  |
| Sacai | 1 |  |  |
| Simkhai | 1 |  |  |
| Simon Miller | 1 |  |  |
| Sofia | 1 |  |  |
| Strathberry | 1 | yes | yes |
| Stuart Weitzman | 1 |  |  |
| Sunnei | 1 |  |  |
| The Frankie Shop | 1 |  |  |
| Valextra | 1 |  |  |
| Vasic | 1 |  |  |
| Vee Collective | 1 |  |  |
| Vic Matie | 1 |  |  |
| Vipera | 1 |  |  |
| Y-3 | 1 |  |  |
