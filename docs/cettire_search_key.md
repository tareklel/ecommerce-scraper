# Cettire search key

How the Cettire crawler gets, keeps and renews the key for Cettire's search
service. Describes how it works today; update it in the same commit as any
change to this behaviour (spider, constants, IAM, storage locations).

## What the key is and why it matters

Cettire's listings come from its own search service (`search.cettire.com`),
which the crawler calls directly, without Zyte. Every call needs an
`x-api-key`. Cettire publishes that key in the page config of every page on
its site (`__NEXT_DATA__` → `runtimeConfig.searchAIAPIKey`), so anyone who
loads a page has it.

**Without a valid key the Cettire crawl writes nothing.** With one, it writes
every product from the search data even when product pages can't be fetched.

The key is not the Zyte key. Three different keys, three places:

| Key | Used for | Lives in |
|---|---|---|
| Cettire search key | Cettire's search service | Parameter Store `/ecommerce-scraper/cettire/search-api-key` (this doc) |
| Zyte crawler key (`ZYTE_API_KEY`) | sending page requests through Zyte | Secrets Manager `ecommerce-scraper/env` |
| Zyte usage key | the run email's Zyte cost line | Parameter Store `/ecommerce-scraper/zyte-stats/` |

## Where everything lives

| What | Where |
|---|---|
| The key | Parameter Store `/ecommerce-scraper/cettire/search-api-key`, SecureString, eu-central-1. One key for dev and prod (it's Cettire's) |
| Pages to renew it from | `s3://price-comparison-bucket-eu-central-1/resources/cettire/key-pages.json`: up to 10 product addresses from the last run that got products |
| Crawler's permission | `aws_iam_role_policy.ecs_task_cettire_search_key` in `infra/terraform/iam_ecs.tf`: read and write on that one parameter only. The S3 file needs nothing extra (the crawler can already write to the bucket) |
| Code | `ecommercecrawl/spiders/cettire_crawl.py` ("search key" section); numbers in `ecommercecrawl/constants/cettire_constants.py` |
| Overrides (tests, local runs) | settings `CETTIRE_SEARCH_KEY_PARAMETER`, `CETTIRE_KEY_PAGES_URI` |
| Tests | `tests/test_cettire_spider.py` |

The key is never in Git, Terraform, `.env` or logs. Logs show a fingerprint
instead: the first 8 characters of the key's SHA-256 (for example `51200e93`).
The AWS SDK loggers (`botocore`, `boto3`, `s3transfer`) are held at INFO in
`ecommercecrawl/settings.py` even when the crawl logs at DEBUG: at DEBUG,
botocore logs response bodies, including the decrypted parameter.

## What happens on every Cettire run

```
start
 ├─ read the key from Parameter Store
 │    found → use it
 │    missing or unreadable → renew (below)
 ├─ search calls (direct, no Zyte)
 │    Cettire rejects the key (401/403) → renew (below), then retry once;
 │    rejected again → the run fails
 ├─ after the first listing: save 10 product addresses to key-pages.json
 └─ crawl as usual

renew: read the key from a Cettire page through Zyte
 1. plain fetch, one try per page: the saved product pages first, then the
    3 bag listing pages (at least 4 tries in all)
 2. then 8 tries in Zyte's browser mode over the same pages
 → a page gives the key: save it to Parameter Store, carry on
      (save fails: carry on, run marked degraded, kind "setup")
 → every try refused: the run fails; the saved key is left as it was
```

A normal run makes **no** Zyte request for the key. Zyte is only used when
Cettire changes the key, or the parameter is empty.

## What you'll see

In the crawler log (CloudWatch `/ecs/ecommerce-scraper`):

| Line | Meaning |
|---|---|
| `Using the saved Cettire search key (fingerprint xxxxxxxx).` | Normal |
| `Saved 10 Cettire product addresses to s3://... for key renewal.` | Normal |
| `Cettire search service rejected the saved key; reading the current one from the site.` | Cettire changed the key; renewal starting |
| `Read the Cettire search key (fingerprint yyyyyyyy) from <page> (plain/browser fetch, attempt N).` | Renewal worked. A new fingerprint means a new key |
| `Saved the new Cettire search key (fingerprint yyyyyyyy) to ...` | Stored for the next runs |

In the run email:

| Email says | Meaning | What to do |
|---|---|---|
| Cettire `failed (crash: RuntimeError: Could not fetch a Cettire page through Zyte to read the search key (... attempts ...))` | The key was missing or rejected, and Zyte was refused on every page | See "When renewal fails" |
| Cettire `failed (crash: HTTPError ... 401/403 ...)` or `... rejected the key read from the site` | A freshly read key was also rejected | The page config or the search service changed; needs a look at the spider |
| Cettire degraded, `setup ...: Could not save the new Cettire search key` | The run worked but the new key wasn't stored, so the next run renews again | Check the IAM policy above still exists |

## When renewal fails

Cettire products stay in gold for 14 days, so one or two failed nights don't
change the website. Other sites are not affected.

1. **Wait a night.** Zyte refusals come and go; the next run tries again.
2. **Check whether Zyte gets through**: a one-off dev task that fetches a
   Cettire product page through Zyte and reports status codes only (as on
   2026-11-20; the script is not kept in the repo).
3. **Load a key by hand** if you have one (for example from a Cettire page
   saved earlier, or a browser on a normal connection: page source, search
   `searchAIAPIKey`). Easiest without the value landing in shell history: AWS
   console → Systems Manager → Parameter Store →
   `/ecommerce-scraper/cettire/search-api-key` → Edit. Reading a key out of
   files counts as a security-sensitive action under `context/AGENTS.md`: an
   agent must ask first and show the exact command.

Check which key is stored, without showing it:

```
aws ssm get-parameter --region eu-central-1 --name /ecommerce-scraper/cettire/search-api-key \
  --with-decryption --query Parameter.Value --output text \
  | python3 -c 'import hashlib,sys; print(hashlib.sha256(sys.stdin.read().strip().encode()).hexdigest()[:8])'
```

## History

| Date | What happened |
|---|---|
| 2026-11-14 | Key found in the page config during the research probes; the crawler read it from a page through Zyte at the start of every run and kept it only for that run |
| 2026-11-16 to 18 | Reading it took 1 to 4 minutes of Zyte retries (listing pages); product pages still got through ~99% (2,000 a night, 9 to 20 refused) |
| 2026-11-19 night | Cettire run failed: all 12 Zyte tries refused, nothing crawled |
| 2026-11-20 | Key stored in Parameter Store and renewed by the spider (user design). Zyte refused every Cettire page that day: listing pages plain and browser, a product page, geolocation TR. First key loaded by hand from the 11-14 probe pages (fingerprint `51200e93`); Cettire still accepted it, so the key lasted at least 6 days. Renewal from saved product pages and fingerprint logging added |
| 2026-11-23 | Found: crawls logged at DEBUG, so botocore printed the Parameter Store reply, key included, into CloudWatch on every run since 11-20. AWS SDK loggers now held at INFO (test in `tests/test_settings.py`). Copies already in the log group were not deleted: its 7-day retention removes the last of them by 2026-11-30 |

## Open

- How often Cettire changes the key is unknown; the fingerprint in the logs
  will show it.
- If Zyte stays refused on the night the key changes, renewal fails until Zyte
  gets through. A second proxy as another renewal route would cover this
  (Oxylabs settings exist in the repo; account status unknown).
- A possible way through Zyte (user test, 2026-11-27): `device: "mobile"`
  with `geolocation: "AU"` returned a Cettire product page that plain requests
  got 520 on. Renewal does not use it yet, and whether the mobile page carries
  the key is untested; see `tickets/cettire_crawl.md`.
