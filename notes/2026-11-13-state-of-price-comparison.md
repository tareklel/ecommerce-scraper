# State of Price Comparison — Nov 2026

**Date:** 2026-11-13
**Covers:** `ecommerce-scraper`, `../scraper-pipeline`, `../price-comparison-web`
(`../product-matching` is noted where relevant).
**Question:** can a products-only first version launch by 31 December 2026, and
has the year's effort gone to the right things?

## 1. Bottom line

- **A year-end soft launch is possible, but only if almost every remaining
  session goes to the website and to prod.** My estimate is 14–19 working
  sessions of launch work against 12–23 sessions available in the 7 weeks left.
  There is no room for more crawler or pipeline hardening.
- **The data side is ahead of what a first version needs. The user-facing side
  is behind.** After 14 months the site still runs only on `localhost`, prod
  holds no data, and the product has no name or domain.
- **Work has sped up sharply since October**: about 4 times the commits per
  working day of the first eight months, and about 5 times the lines. Most of
  that speed went into the crawler (54% of lines), least into the website (18%).
- **The biggest miss, judged as an experienced engineer would:** nothing was
  deployed end to end early. Building crawler → pipeline → website in order
  meant integration problems and silent data loss were found late, and no real
  shopper has seen the product yet.
- **Three launch blockers are decisions, not code**: the name and domain, the
  launch scope, and sign-off on the mobile design. The domain has been listed as
  "the single blocker" for going live since 9 June.

## 2. Where each part stands

| | State today | Evidence |
|---|---|---|
| **Crawler** | 3 working retailers (Ounass, Level Shoes, Bloomingdale's); Farfetch blocked. One command runs crawl → dbt → images → tests → cache refresh in AWS and emails a summary. 553 tests. | First fully green run 2026-11-11 (86 min). Not on a schedule yet. |
| **Pipeline** | 24 dbt models, 51 dbt tests, canonical brand/category seeds in Arabic and English, a release export with a manifest. Runs in AWS behind a lock. | Dev only. Prod is "not touched" (`ticket/migrate-validated-dev-to-prod.md`). |
| **Website** | Listing pages, product pages, filters, Arabic and English, nav from a seed. 90 site tests, 34 API tests. | `localhost` only. No CI, no hosting, Terraform state still a local file holding the API keys. CI/CD plan written today, not built. |
| **Data served** | About 11,300 language rows in dev (Arabic and English counted separately), all Saudi women's bags. | The crawl registry now lists only tote and shoulder bags for each retailer. |
| **Product matching** | One commit (April), uncommitted edits since. | Correctly parked: comparison is not in the first version. |

I read these states from the repos' files and logs. I did not query AWS.

## 3. Has work accelerated?

Yes. Measured from git history across the three repos since the restart in
September 2025:

| Period | Commits | Working days | Commits per working day | Lines added per working day |
|---|---|---|---|---|
| Sep 2025 – Apr 2026 (8 months) | 84 | 51 | 1.6 | ~220 |
| May – Sep 2026 (5 months) | 119 | 41 | 2.9 | ~745 |
| Oct 1 – Nov 13, 2026 (6 weeks) | 138 | 21 | 6.6 | ~1,135 |

Two things changed at once: you worked more days (about 14 a month now, against
6 to 8 before) and each day produced more.

The periods line up with how you worked with AI. Commits before mid-May carry no
AI co-author line. May to September are mostly Claude Sonnet 4.6 and Sonnet 5.
From 5 October, 124 commits carry Claude Opus 5.5, and that is when the agent
started doing whole steps itself: targeted Terraform applies, deploys, live test
runs, and coordinating with sessions in the other repos.

The outcome matches the numbers. In six weeks: the Ounass listing-based crawl
(Parts 0–6), an access-failure layer, run statuses, image builds in GitHub
Actions for the crawler and dbt, Terraform state in S3, dbt in AWS, the crawl
flow, run emails, the release manifest and the seeded nav.

Caveats: commit and line counts are rough measures, and commits got smaller and
more frequent in the last period. Lock files, notebooks, CSV and JSON are
excluded from the line counts.

**Where the speed went (Oct–Nov lines added):** crawler 54%, pipeline 28%,
website 18%. By kind: code 35%, docs and tickets 32%, tests 24%, infrastructure 9%.

## 4. Did the investment go to the right things?

**Paid off, and a first version needs it:**

- Arabic and English canonical seeds for brands and categories. This is the
  product's actual edge and the hardest part to copy.
- Images stored by content hash behind a CDN, served only after validation.
- The quality gate and publish-on-pass, so a bad crawl never reaches the site.
- Building images in GitHub Actions and the single crawl flow. These removed
  the stale-deploy problem and the manual run order.
- The release manifest, so products, names and nav change together.

**Sound work, done earlier than needed:**

- **The listing-based Ounass crawl.** It took most of October, the fastest
  period of the project. It cuts one category's daily cost from about $181 to
  about $2 a month, but crawls are weekly and there are no users, so the saving
  today is small. It will matter when the catalogue widens. It did also expose a
  pagination bug that had hidden about 18% of Ounass products per crawl since
  November 2025.
- **The dev/prod split (May).** Built before there was a product. Prod is still
  an empty shell, and filling it is now its own migration ticket.
- **Crawl-health models and killed-run detection.** Useful once crawls run
  daily without you. Not needed to launch.
- **Farfetch (Sep–Oct 2025).** The first spider and its tests targeted a site
  that is now blocked: only costly browser rendering gets through. The
  feasibility checklist that screens new sites was written in July 2026.

**Needed for launch, and barely started:**

- A deployed site, on any address.
- A name and a domain.
- A mobile design pass on a real phone. Product images are served full size
  with plain `<img>` tags; resizing is "not started".
- Prod data.
- A rule for stale products. Products the crawler stops seeing stay in gold
  with their last price (open question in the pipeline log, 2026-11-11). The
  registry lists two bag subcategories while the Arabic menu shows ten, so the
  others are likely to age silently.
- Search engine basics, visitor analytics, and an about or legal page.

## 5. Gaps an experienced engineer would have caught

1. **No thin end-to-end version early.** The website repo started in month 10.
   A rough deployed page fed by one small crawl in month 2 would have surfaced
   the crawl → dbt → images → dbt ordering problem, the cache refreshing before
   tests, and the mapping gaps months sooner. It would also have put the product
   in front of a shopper.
2. **CI and remote state came in month 14.** Until October the cloud crawler
   ran an August image missing two commits, the cache export ran July code until
   9 November, and the prod API still runs old code. Terraform state lived in a
   synced folder. These are normally week-one setup.
3. **No count reconciliation.** Three separate silent losses ran for weeks or
   months: the pagination bug (11 months), about 95 Ounass products dropped for
   missing brand or gender mappings, and 131 products with no brand. One line per
   run comparing the site's own total → crawled → silver → gold → served would
   have caught each the same day. `silver_mapping_gaps` (built today) covers part
   of it.
4. **Per-retailer copies of the models.** Each retailer has its own dim, fact
   and i18n model: nine files, about 2,500 lines, largely the same shape, plus
   a branch in gold. A fourth retailer means roughly 900 more lines of SQL, and
   every fix has to be made three times. For a product whose promise is range,
   this is the main limit on growth.
5. **The work environment.** The project sits on a company-managed laptop in a
   company OneDrive folder. That has cost real time: Docker builds fail behind
   the HTTPS inspection, AWS calls fail with certificate errors, OneDrive turned
   virtualenv links into text files, and `.env` files and a state file with API
   keys sync to company storage. Separately from the lost time, it is worth
   checking your employer's policy on personal projects and devices.
6. **Business questions with no ticket.** Nothing in the three repos mentions
   affiliate programmes, revenue, or the legal position on showing retailers'
   prices and re-hosting their images. Worth checking before launch: retailers
   that run affiliate programmes often supply product feeds, which could replace
   some crawling and give a clearer footing.
7. **Decisions left open for months.** The brief still says "Name TBD". The
   ticket for the real listing page still says it is blocked on a debug UI that
   was finished in June. (The roadmap also planned the design around a
   contractor; that plan was dropped on 2026-11-13 and the design is now done
   by you and Claude.)

## 6. Path to a year-end launch

**Define launch narrowly:** a public address on your domain, Saudi women's bags
from three retailers, Arabic and English, refreshed on a schedule, visible to
Google. Nothing else.

Estimated sessions (my estimates, with the design pass the least certain):

| Order | Work | Sessions |
|---|---|---|
| 1 | Decide name, buy domain, confirm scope (yours alone) | 0 |
| 2 | Website CI/CD steps 1–5: state to S3, checks, dev API from GitHub, secrets, dev site live behind a password | 3–4 |
| 3 | Mobile design pass on the dev site, on your phone; smaller images | 3–5 |
| 4 | Registry covers every subcategory shown, or gold drops products unseen for N days | 1 |
| 5 | Prod data: tables, one deliberate prod crawl, dbt, images, cache | 2–3 |
| 6 | Schedule the flow (ticket step 6) | 1 |
| 7 | Screenshot review pack and promotion to prod | 2 |
| 8 | Domain and HTTPS, page titles, sitemap, robots, analytics, about/legal page | 2–3 |
| | **Total** | **14–19** |

**Sessions available:** at the Oct–Nov pace (about 3.3 days a week), 23. At the
14-month average (about 1.8 days a week), 12.

**Leave until after launch:** crawler ticket steps 7–10 (Terraform in CI, dbt in
CI, drift check, fixture), the crawl-health dashboard, brand-scoped registry
rows, new retailers, merging the per-retailer models, moving the API to ECS,
further nav redesign, product matching.

For smaller images, consider making two fixed sizes in the existing image
quality step, which already opens every image with Pillow, instead of the
planned Lambda@Edge resizer. It needs no new region, no Node build, and nothing
built on the laptop.

## 7. Moving faster with quality

1. **One launch list for all three repos.** Today there are three ticket
   folders, three memory logs and a stale roadmap. One short file with the table
   above, and every session starts from its top open line.
2. **Whenever you sit down to work, the website gets the first session; the
   data side is break-fix only.** This is about where your working time goes,
   not about leaving anything running while you are away. On the data side, fix
   what a run email reports as broken, and nothing else.
3. **Widen what the agent may do without asking first.** The rule "explain the
   plan before any file change" made sense a year ago. You already relaxed it for
   targeted Terraform. Extend that: code, tests and docs inside one repo, and dev
   deploys through CI, proceed and are reported after. IAM, prod, spending,
   deletes and cross-repo edits still wait for you.
4. **Batch your decisions.** Your time is the limit, not the agent's. Each
   session should end with a short list of decisions only you can make, so you
   can answer them from your phone between sessions.
5. **Pull the dev site and screenshot pack forward.** Once they exist you can
   review work without the laptop, and a few Saudi shoppers can try it. That
   feedback is worth more now than another test.
6. **Take the laptop out of the loop.** All builds and deploys through GitHub
   Actions (already the direction), and consider running agent sessions in the
   cloud against the GitHub repos. That removes the proxy failures and lets work
   continue when you are away from the machine.
7. **Add the count line to the run email**: site total → crawled → gold →
   with images → served, per retailer.
8. **Trim the paper trail.** A third or more of all lines written since May are
   docs and tickets.
   Keep contracts, diagrams and the "▶ next steps" sections; move history out.
   This repo's `context/memory.md` is now too long to read in one pass (it hit
   the read limit in this session), so archive entries older than about 60 days.

## 8. Decisions only you can make

- The name and the domain.
- Launch scope: bags only at launch, or wait for more categories.
- When the mobile design is good enough to launch. You sign it off; there is
  no contractor.
- Whether prices and stock may be up to a week old at launch, or daily.
- Whether this project stays on the company laptop.
- Whether to look into affiliate programmes before or after launch.

## 9. Tickets for the launch path

Added 2026-11-13 after this report. "New" tickets were written from it.
Before starting any of the new tickets, discuss it with the user in an
`ecommerce-scraper` session and agree the scope; each ticket says so too.

Update 2026-11-16: since this report, cloud sessions onboarded Cettire as a
fourth retailer (`tickets/cettire_crawl.md`, `../scraper-pipeline/ticket/onboard-cettire.md`).
That is range work rather than launch work, so the session estimate in section 6
did not shrink.

| Work | Ticket | |
|---|---|---|
| Name and domain | `../price-comparison-web/tickets/name_and_domain.md` | New |
| Website CI/CD, dev site, promotion | `../price-comparison-web/tickets/cicd.md` | In progress |
| Mobile design pass | `../price-comparison-web/tickets/plp_nextjs.md` | Exists, status line out of date |
| Smaller images | `../price-comparison-web/tickets/image_resizing.md` | Exists |
| Products not seen for 14 days leave gold | `../scraper-pipeline/ticket/gold-drop-stale-products.md` | Written 2026-11-13 by the pipeline session |
| Prod data | `../scraper-pipeline/ticket/migrate-validated-dev-to-prod.md` | Exists |
| Schedule the flow | `tickets/cicd_pipeline.md`, step 6 | Exists |
| Domain and HTTPS | `../price-comparison-web/tickets/frontend_hosting.md` | Exists |
| Page titles, sitemap, robots | `../price-comparison-web/tickets/seo_technical.md` | Exists |
| Visitor analytics and errors | `../price-comparison-web/tickets/analytics.md` | New |
| About, terms, privacy, contact | `../price-comparison-web/tickets/about_and_legal_pages.md` | New |
| Affiliate programmes and legal position | `tickets/affiliate_and_legal_check.md` | New |
| Count check in every run email | `tickets/run_count_reconciliation.md` | New |
| One set of silver models (after launch) | `../scraper-pipeline/ticket/merge-per-site-silver-models.md` | New |
