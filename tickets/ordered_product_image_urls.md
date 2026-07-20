# Emit Ordered Product Image Galleries for Ounass and Level Shoes

## Status

Draft; implementation must be coordinated with both pipeline tickets:

- `../scraper-pipeline/ticket/support-multiple-product-images.md`
- `../scraper-pipeline/ticket/reset-dev-raw-for-product-schema-v2.md`

Do not deploy this scraper change while the active bronze tables still declare
`image_urls string`. The same reset also changes both sites' `text` fields to a
typed struct, so the image change must not trigger a partial V2 crawl first.

## Goal

Make both supported spiders emit every authoritative product image as an
ordered `image_urls` list instead of emitting only the first URL.

The output must preserve the site's gallery order, place the source hero image
first, use absolute HTTPS URLs, and distinguish extraction failure from an
explicitly empty source gallery.

## Feasibility Evidence

Both sources already expose the complete ordered gallery; current helpers
explicitly select element 0:

- Ounass `pdp.images` is an ordered list. The saved `test_ounass.ipynb` payload
  contains four entries, each with `oneX`, `oneXMobile`, and `twoX`. Current
  `get_image_url` reads only `images[0].oneX` and removes the scheme.
- Level Shoes PLP/PDP product data contains an explicit `image.url` hero and an
  ordered `imagePreviewGallery`. The saved `miumiu.html` fixture contains four
  product-gallery URLs; the hero repeats as the first gallery member. Current
  `get_image_urls_from_item` returns only `imagePreviewGallery[0].url`.
- Level Shoes direct PDP recrawls bypass PLP metadata. The current fallback
  `extract_first_image_url` also returns only one URL even though the page's
  `__NEXT_DATA__.props.pageProps.productDetails` contains the full gallery.
- `ecommercecrawl/constants/product_schema.py` already describes `image_urls`
  as an ordered list, so the spiders currently violate their declared contract.
- `scripts/backfill/build_image_jobs_from_gz.py` already fans out a list into
  one scalar downloader job per URL.

This is therefore an extraction/contract correction, not a discovery project.

## Output Contract

Every product row contains the `image_urls` key.

```json
{
  "image_urls": [
    "https://cdn.example/hero.jpg",
    "https://cdn.example/side.jpg",
    "https://cdn.example/detail.jpg"
  ]
}
```

| Value | Meaning |
|---|---|
| `null` | The gallery field was missing/malformed or extraction failed |
| `[]` | The authoritative source explicitly returned a valid empty gallery |
| Non-empty list | Successful ordered observation; element 0 is the source hero |

Rules:

1. Preserve authoritative site order; never sort URLs.
2. Prepend an explicit hero URL when the source supplies one.
3. Normalize `//host/path` and known bare Ounass CDN hosts to
   `https://host/path`.
4. Keep only absolute HTTP(S) URLs and prefer HTTPS.
5. Deduplicate exact normalized URLs while preserving the first occurrence.
6. Preserve query parameters; they can encode CDN transform or version state.
7. Do not use `[]` for a missing selector, malformed object, or parsing error.
8. Do not collect generic page `<img>` elements; they include recommendations,
   navigation art, swatches, and badges.

Update the canonical product-schema description to `list[str] | None` and
document the three states. Keep the output key required even though its value
may be null on extraction failure. The quality gate already treats both null
and an empty list as blank.

## Shared Normalization Helper

Add one small shared helper, or equivalent consistently tested site helpers,
that:

```text
input:  optional hero plus an iterable of candidate URL values
output: None, [], or ordered unique absolute URLs
```

The helper must not collapse the semantic difference between a missing source
and an explicitly present empty list. It must tolerate non-string candidates
without raising the entire product parse.

Do not remove or reorder URL query parameters. Exact normalized URL identity is
used by the downstream image-download log.

## Ounass Changes

### Extraction

Replace scalar `get_image_url(state)` with `get_image_urls(state)` in
`ecommercecrawl/rules/ounass_rules.py`.

Use `state['pdp']['images']` as the authoritative ordered source:

- For each image object, prefer `oneX` to preserve the existing chosen variant.
- If an individual object lacks `oneX`, use a documented fallback order such as
  `twoX`, then `oneXMobile`; do not emit multiple variants of the same image.
- Normalize the current `//...` or bare-host values to absolute HTTPS.
- Preserve list order and deduplicate after normalization.
- Return null for missing/malformed `pdp.images`.
- Return `[]` only when `pdp.images` is explicitly a valid empty list.

Update `get_data` to emit the returned list directly.

### Required tests

- Four ordered `oneX` entries produce four absolute HTTPS URLs.
- Scheme-relative, bare-host, and already absolute forms normalize correctly.
- A repeated URL is emitted once at its first position.
- An invalid member does not discard valid members.
- Missing/malformed `pdp.images` returns null.
- Explicit `pdp.images = []` returns `[]`.
- `get_data` emits a list and keeps the first source image at index 0.
- Spider PDP output preserves the list through JSON serialization.

## Level Shoes Changes

### PLP-discovered products

Change `get_image_urls_from_item(item)` in
`ecommercecrawl/rules/level_rules.py` to:

1. Read `item.image.url` as the explicit hero when present.
2. Append every `item.imagePreviewGallery[*].url` in source order.
3. Deduplicate after normalizing, because the hero normally repeats as gallery
   element 0.
4. Return null for a missing/malformed gallery source and `[]` only for an
   explicitly valid empty gallery with no hero.

### Direct PDP and recrawl products

Replace `extract_first_image_url(response)` with an array-returning
`extract_image_urls(response)`.

Source priority:

1. Parse `script#__NEXT_DATA__` and use
   `props.pageProps.productDetails.image.url` plus
   `props.pageProps.productDetails.imagePreviewGallery[*].url`.
2. If the authoritative Next.js object is unavailable, use a JSON-LD Product
   image list, with OpenGraph hero prepended and deduplicated.
3. Use Twitter/OpenGraph only as a scalar last resort, returning a singleton
   list.
4. Do not scan all DOM images as a gallery fallback.

Update the Level spider PDP placeholder to call the array extractor. Preserve a
valid PLP-provided list; use the PDP fallback only when the meta value is null.
An explicitly empty PLP gallery must stay empty rather than being confused with
extraction failure.

### Required tests

- PLP item hero plus four gallery members returns four URLs, not five, because
  the repeated hero is deduplicated.
- PLP gallery ordering is unchanged.
- Saved `tests/levels_html_fixtures/pdp/miumiu.html` produces all four product
  images and excludes menu/recommendation images.
- A direct PDP seed and a PLP-discovered PDP produce the same gallery for the
  same fixture.
- JSON-LD list fallback returns every listed image in order.
- OpenGraph scalar fallback returns a singleton list.
- Missing/malformed source returns null; explicit empty source returns `[]`.
- `_handle_item` and `parse_pdp` both emit list-valued `image_urls`.

## Downloader and Backfill Compatibility

The Athena-driven image downloader continues to receive one scalar `url` per
row after the pipeline ticket unnests the silver array. Do not redesign
`run_image_pipeline.py` to accept arrays.

Add a regression test for `scripts/backfill/build_image_jobs_from_gz.py` proving
that one crawler row with four ordered image URLs produces four scalar jobs in
the same order.

The transitional direct JSONL reader in `ecommercecrawl/image_downloader.py`
currently accepts `payload.image_urls` as if it were scalar. Either:

- make it fan out list values consistently, or
- remove/document that transitional crawler-row input and require the backfill
  job builder.

The local smoke test below must use the supported backfill builder, so it tests
the same scalar-job boundary used operationally.

## Deterministic Local Tests

Add focused tests for the gallery helpers and spider propagation, then run:

```bash
PYTEST_ADDOPTS="-p no:cacheprovider" .venv/bin/pytest -q \
  tests/test_ounass_rules.py \
  tests/test_level_rules.py \
  tests/test_ounass.py \
  tests/test_level.py \
  tests/test_build_image_jobs_from_gz.py
```

Baseline note from 2026-07-17: the current narrower command over
`test_ounass_rules.py`, `test_level_rules.py`, and `test_level.py` has 79 passing
tests and three unrelated stale assertions. They concern structured `text` and
the concurrent `was_price` work, not image extraction. Update those stale
expectations before claiming the final focused suite is green; do not hide them
with `--ignore` or a broad test selection workaround.

## Required Live Local Smoke Test

Add a repeatable, non-S3 target:

```bash
make smoke-product-image-galleries-local
```

The target should load the same local crawler secrets as existing crawl targets
and run one direct, known multi-image PDP per site. Provide URL overrides:

```text
OUNASS_IMAGE_SMOKE_URL
LEVEL_IMAGE_SMOKE_URL
```

Candidate defaults observed in current local fixtures/crawls:

```text
https://saudi.ounass.com/shop-safiyaa-finley-peplum-dress-for-women-219174599_2709.html
https://www.levelshoes.com/miu-miu-wander-matelass-satin-mini-bag-blue-satin-women-mini-bags-qmbhpt.html
```

If a candidate is no longer live, update the default to another stable
multi-image PDP and record the replacement in the validation log.

Implement a small smoke validator rather than relying on visual log inspection.
For each newly created crawler artifact it must assert:

- exactly the expected site was crawled
- `image_urls` is a JSON array
- at least two URLs were extracted
- every URL is absolute HTTP(S), nonblank, and unique
- order is stable and the expected hero is first
- no obvious navigation/static/recommendation image entered the gallery

Then pass each crawler gzip through the existing job builder:

```bash
poetry run python3 scripts/backfill/build_image_jobs_from_gz.py \
  --input-gz <crawler-output.jsonl.gz> \
  --output-jsonl <temporary-jobs.jsonl>
```

Assert that job count equals gallery cardinality and job order matches array
order. Download every emitted URL locally:

```bash
poetry run python3 run_image_downloader.py \
  --input-jsonl <temporary-jobs.jsonl> \
  --output-dir <temporary-image-dir> \
  --results-path <temporary-results.jsonl>
```

The smoke passes only when every URL returns downloader status `ok` and each
saved file passes the existing image validation checks. It must print a compact
summary without credentials or signed headers:

```text
site=ounass products=1 gallery_urls=4 jobs=4 downloaded_ok=4 hero=<redacted-to-host-and-path>
site=level-shoes products=1 gallery_urls=4 jobs=4 downloaded_ok=4 hero=<redacted-to-host-and-path>
SMOKE PASS
```

Keep smoke output under an automatically created temporary directory or a
dedicated ignored output path. Do not upload crawl rows, jobs, images, or
results to S3.

## Cross-Market Verification

The downstream product dimension is keyed by site and product rather than
country/language. During implementation, smoke or sample the same product across
available Saudi/UAE and English/Arabic variants when the identifier is shared.

If normalized galleries differ for the same `site, primary_key`, record that as
a blocking data-grain finding for the pipeline ticket; do not let latest crawl
order arbitrarily select one market's gallery.

## Files to Change

| File | Change |
|---|---|
| `ecommercecrawl/rules/ounass_rules.py` | Extract and normalize every ordered Ounass image |
| `ecommercecrawl/rules/level_rules.py` | Return full Level PLP and direct-PDP galleries |
| `ecommercecrawl/spiders/level_crawl.py` | Propagate array values through both spider paths |
| `ecommercecrawl/constants/product_schema.py` | Document required key and three-state array value |
| `context/crawling_methodology.md` | Document source hero/order/normalization rules |
| `docs/image_downloader_blob_contract.md` | Document array-to-scalar job boundary |
| `tests/test_ounass_rules.py` | Ounass extraction contract tests |
| `tests/test_level_rules.py` | Level PLP/PDP extraction contract tests |
| `tests/test_ounass.py` | Spider propagation tests |
| `tests/test_level.py` | Both Level spider paths emit arrays |
| `tests/test_build_image_jobs_from_gz.py` | Array fan-out regression test |
| `scripts/smoke_product_image_galleries.py` | Automated live local crawl/output/download validator |
| `makefile` | `smoke-product-image-galleries-local` target and URL overrides |

Preserve unrelated in-progress `was_price` and structured-text changes already
present in the worktree.

## Rollout Coordination

1. Implement and pass deterministic extraction tests.
2. Run the live local smoke and attach its exact summary to this ticket.
3. Confirm the in-progress structured-text output and its tests are also ready.
4. Execute the approved dev archive/reset umbrella runbook.
5. Cut both bronze product tables to the array-image and structured-text V2
   types.
6. Deploy gallery and structured-text scraper changes before resuming writes.
7. Run full UAE/Saudi and English/Arabic dev crawls.
8. Validate both arrays and text structs in Athena before dbt full refresh.

## Acceptance Criteria

- Both spiders emit `image_urls` as a JSON array for successful products.
- Ounass returns every ordered `pdp.images[*]` image as absolute HTTPS.
- Level returns the explicit hero plus all authoritative gallery members from
  both PLP-discovered and direct-PDP flows.
- URLs are unique, ordered, absolute, and use one consistent source variant.
- Null and explicit-empty states are distinguishable and tested.
- The backfill builder emits one scalar job per array member in array order.
- Focused tests and the full existing test suite pass without hiding baseline
  failures.
- `make smoke-product-image-galleries-local` crawls one multi-image product per
  site, verifies at least two URLs each, downloads every URL, validates the
  files, prints `SMOKE PASS`, and performs no S3 writes.
- The exact smoke summary and tested PDP URLs are recorded in a validation log
  before deployment.

## Validation Log

Populate during implementation:

```text
Date:
Commit:
Ounass PDP:
Ounass extracted/downloaded:
Level Shoes PDP:
Level Shoes extracted/downloaded:
Focused pytest result:
Full pytest result:
Smoke result:
```

## Out of Scope

- Bronze/dbt/gold changes owned by `scraper-pipeline`.
- Gallery-size limits for the website.
- Deleting old raw or content-addressed image blobs.
- Selecting among multiple resolutions beyond the documented per-site variant.
- Video/media gallery support.
