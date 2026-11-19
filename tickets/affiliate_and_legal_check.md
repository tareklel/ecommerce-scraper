# Ticket: Affiliate programmes and the legal position

**Status: deferred until after launch (decided by the user 2026-11-19). No
research before launch.**
**Priority: Low until the site has traffic; then this is the route to feeds and
income.**

Source: `launch/2026-11-13-state-of-price-comparison.md` in the workspace repo,
section 5, gap 6. Written 2026-11-13 as a research ticket; rescoped 2026-11-19.

## Decision (user, 2026-11-19)

"Do things first and ask for forgiveness later." Phase 1 is to build a site
that does price comparison and a gallery of available products well, launch it
and get traffic. Only then approach affiliate networks and ask for product
feeds: competitors we don't crawl first, then the retailers we crawl. The
user expects the crawled retailers' terms not to agree with what we do today,
so reading them now would not change the plan.

The one thing kept for before launch is our own legal pages. They belong to
the website: `../price-comparison-web/tickets/about_and_legal_pages.md`
(launch tracker item 8).

## Why the ticket was written

- The site shows retailers' products and prices, taken by crawling.
- We download their product images and serve copies from our own CDN.
- "Buy" links carry nothing that tells the retailer the visit came from us, so
  we earn nothing and they can't see the traffic.

## What was ruled out for phase 1, and why

| Item (2026-11-13 list) | Decision |
| --- | --- |
| Affiliate programme per retailer covering Saudi, network, pay | After launch. Networks want a live site with traffic. Cettire is already known: Partnerize (about 5%, 30-day cookie) and BlueAff (`notes/2026-11-14-cettire-research.md` section 9). |
| Product feed from the programme | After launch; usually visible only after acceptance. The crawlers work meanwhile. |
| Programme terms on prices, images, deep links | After launch; only matters once a programme is joined. |
| Site terms of use and `robots.txt` on automated access | Not researched; the user accepts the risk for phase 1. |
| Stated route to request removal | Not researched. Our own removal contact on the legal pages covers the practical need. |
| Tracking tag on buy links | When a programme is joined. A plain source tag (`utm_source=...`) is a cheap option any time. |
| Serve image copies vs link to the retailer's | Keep copies for phase 1; revisit if a retailer objects. |
| Review by a lawyer (Saudi / UAE commercial law) | Not before the soft launch. |

## Kept: our own legal pages, before launch

Handed to the website ticket above. Suggested contents (general practice, not
legal advice):

1. What we are: an independent discovery and comparison site; we don't sell,
   ship or take payment; purchases are made with the retailer on its terms.
2. Prices and stock come from retailers' sites and can be out of date; the
   retailer's price and availability at checkout prevail.
3. Brand names, logos and product images belong to their owners and are shown
   to identify products; no affiliation or endorsement implied.
4. A removal and contact route (an email address) for brands and retailers,
   with a promise to act quickly. This is the "forgiveness" channel: an
   annoyed retailer's first step should be an email to us.
5. Privacy policy and cookie notice: what is collected (analytics, cookies)
   and why. Saudi PDPL applies once visitors are tracked.
6. Terms of use: site provided as is, no warranty, limited liability,
   governing law.
7. Later: an affiliate disclosure, once links earn commission.
8. Arabic and English versions.

## Phase 2 (after launch, once there is traffic)

1. Apply to affiliate programmes of competitors we don't crawl, asking for
   product feeds.
2. Then the retailers we crawl (Ounass, Level Shoes, Bloomingdale's, Cettire),
   asking for feeds that could replace crawling.
3. When a programme is accepted: read its terms on prices, images and links,
   and open tickets for tracking tags and any image change in the repos that
   own them.

## Done when

- Phase 1: the legal pages are live (tracked in the website ticket).
- Phase 2: a decision per retailer and competitor (applied, accepted, feed or
  not), recorded here or in a dated note in `notes/`.
