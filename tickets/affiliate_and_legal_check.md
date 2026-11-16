# Ticket: Affiliate programmes and the legal position, before launch

**Status: open, research only, nothing to build yet (written 2026-11-13)**
**Priority: High. Answer before the site is public.**
**Before starting: discuss this ticket with the user in an `ecommerce-scraper`
session and agree the scope. Do not start from this ticket alone.**

Source: `notes/2026-11-13-state-of-price-comparison.md`, section 5, gap 6.

## Why this is high priority

Nothing in the three repos mentions affiliate programmes, revenue, or whether
we may show retailers' prices and images the way we do. Three facts make this
worth an answer before launch, not after:

- The site shows three retailers' products and prices, taken by crawling.
- We download their product images and serve them from our own CDN.
- Every "buy" link sends a shopper to a retailer, with nothing that tells the
  retailer the visit came from us.

If a retailer objects after launch, the fix is rushed and public. If a retailer
runs an affiliate programme, we may be giving away the product's only income,
and possibly crawling data they would hand us as a feed.

## Questions to answer, per retailer (Ounass, Level Shoes, Bloomingdale's, Cettire)

Cettire is partly done (2026-11-14, `tickets/cettire_crawl.md` and
`notes/2026-11-14-cettire-research.md`): it has an affiliate programme
(Partnerize, BlueAff), no public product feed was found, and its terms of use
are not read yet.

1. Is there an affiliate or partner programme that covers Saudi Arabia? Through
   which network? What does it pay, and on what?
2. Does the programme supply a product feed (products, prices, stock, images)?
   A feed could replace some crawling and its cost.
3. What do the programme's terms say about showing prices, using product
   images, and linking straight to product pages?
4. What do the site's terms of use and `robots.txt` say about automated access?
5. Is there a stated way to ask for content to be removed?

## Questions about our own site

- Should buy links carry a tracking tag, and where would it be added (the
  pipeline's export, or the website)?
- What the about and legal pages must say
  (`../price-comparison-web/tickets/about_and_legal_pages.md`).
- Whether to keep serving copies of the images or link to the retailer's own.

## How to do it

- An agent session can read the public pages (terms, robots.txt, affiliate
  sign-up pages) and write up what each says, with links.
- The legal reading is not something an agent should decide. Take the write-up
  to someone qualified in Saudi and UAE commercial law for a short review.

## Done when

- A dated note in `notes/` records the answers per retailer, with links.
- You have decided: apply to any programme before launch, or after.
- Any change that follows (tracking tags, image handling, page text) has its
  own ticket in the repo that owns it.
