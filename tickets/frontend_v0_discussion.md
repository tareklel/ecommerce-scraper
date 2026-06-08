# Ticket: Frontend v0 — Design Discussion

**Status: open for discussion — product brief complete, decisions below need owner input**

## Purpose

This is a structured discussion, not an implementation ticket. The output is a
set of decisions that unblock actual build work. Nothing here should be built
until the website description is written and this discussion has been resolved.

---

## 1. Which Repo

**Options:**

- **New repo (`price-comparison-web` or similar)** — clean separation between
  crawler infra and the frontend. Standard for a product that will have its own
  deploy pipeline, CI, and contributors who don't need to touch the scraper.
  Recommended if the frontend will eventually be a standalone product.

- **Subfolder in this repo (`ui/`)** — lower friction during early prototyping,
  single git history, easier to co-commit frontend and API changes. Becomes awkward
  when the frontend team (or tools like Vercel) want to own the root of the repo.

- **Subfolder in `scraper-pipeline/` (`scraper-pipeline/frontend/`)** — probably
  wrong; that repo owns data models, not user-facing code.

**From product brief:** The site is described as a standalone luxury discovery platform —
this is a real product, not a data tool. A separate repo is the right long-term shape.
For the debug UI phase (`tickets/plp_debug_ui.md`), a `ui/` folder in this repo is
acceptable. Move to a dedicated repo before the first public URL is registered.

**Question to resolve:** When exactly does the debug UI become the real product? At what
point do we cut a new repo?

---

## 2. Which Coding Framework

The choice depends on the website description. Some options:

**Next.js (React)**
- Industry standard for content-heavy sites that need SEO (product pages get indexed)
- Good RTL/i18n support via `next-intl` or built-in i18n routing
- Can be statically exported (no server needed) or server-rendered (SSR for fast
  first load)
- Vercel deployment is near-zero config; AWS deployment via Lambda/ECS is more work
- Requires JS/TS experience — if this is a constraint, the UI stays a debug tool
  longer and a developer hire/contractor is needed before v0 launches

**Remix**
- Similar to Next.js, better data-loading model, strong server-rendering story
- Smaller ecosystem than Next.js, less relevant to evaluate until framework choice
  is narrowed

**Plain HTML + Tailwind (no framework)**
- Zero build tooling, fast to prototype, easy to generate with AI assistance
- Ceiling is low: no component reuse, no routing, manual state management
- Right for the debug UI (`plp_debug_ui.md`), wrong for a shippable product

**From product brief:** The site is a real product — clean, mobile-first, Arabic-first,
closer to a luxury retailer than a data tool. Next.js is the right framework for
production. Key requirements it handles: SSR for fast first load on mobile, `next-intl`
for Arabic-first routing with RTL layout, SEO for product pages.

The plain HTML debug UI (`tickets/plp_debug_ui.md`) comes first to validate data. Next.js
is the framework for the real frontend that follows it.

**Question to resolve:** JS/TS experience or contractor needed before Next.js build begins?

---

## 3. First Priorities After Framework Decision

Proposed v0 scope, in order:

1. **PLP (product listing page)** — grid of products, filters (brand/category/
   subcategory), language toggle (en/ar), links out to retailer
2. **Image serving working end-to-end** — CloudFront CDN serving images from
   `bronze/images/by-hash/` (see `tickets/image_serving.md`)
3. **API working end-to-end** — `/products` endpoint serving the gold table
   (see `tickets/product_api.md`)
4. **Basic PDP (product detail page)** — single product, all available prices
   across sites, image, buy links — this is the core value proposition
5. **Search / brand browse** — find a specific item or browse by brand

Items 4 and 5 are not in scope until items 1–3 are stable and the data looks
correct visually.

**From product brief:** Browsing PLP is the primary action — users come to discover
range and find deals, not to search for a specific item. Order is confirmed. No search
bar at v0. PDP is in scope early (brief explicitly mentions product detail pages).

Updated priority order:
1. Debug UI with real data (`tickets/plp_debug_ui.md`) — validate data before designing
2. CloudFront image serving (`tickets/image_serving.md`)
3. Product API (`tickets/product_api.md`)
4. PLP in Next.js — Arabic-first, mobile-first, new arrivals default, sale filter
5. PDP — single product, retailer buy link, image; cross-site comparison is mid-term

---

## 4. How to Design Before Deployment

Options for validating the design before writing production code:

**a. Figma / hand-drawn wireframes**
Walk through the key screens (PLP, PDP, search results) as static mocks before
writing any HTML. Cheap to change, easy to share. Requires either Figma experience
or a designer. Good fit if you want to agree on layout and hierarchy before coding.

**b. v0.dev (AI UI generator)**
Describe the page in plain English, get a React component back. Fast way to get
a visual starting point with no design skills. Output is usable code, not just a
mock. Useful for the PLP layout and card design specifically.

**c. Build the debug UI first (`plp_debug_ui.md`)**
Wire up real data before designing anything. See what the actual product catalogue
looks like in a grid — real product names, real prices, real images — then design
around the real content rather than placeholder text. This often surfaces surprises
(very long Arabic names, large price ranges, sparse image coverage) that invalidate
a design made in isolation.

**Recommendation:** Option c first (debug UI with real data), then option b (v0.dev
for the visual shell), then refine in code. Avoids designing for data that doesn't
match reality.

---

## 5. Underlying Infrastructure to Set Up

Prerequisites before any frontend can go live. These are the tickets/discussions
to resolve first:

| Prerequisite | Ticket | Status |
|---|---|---|
| Image CDN (CloudFront) | `tickets/image_serving.md` | ready for implementation |
| Product API (Lambda + cache export) | `tickets/product_api.md` | ready for implementation |
| Custom domain + SSL cert (ACM) | not yet written | needed before any public URL |
| AWS account for frontend hosting | not yet written | Vercel is simpler for Next.js; S3+CloudFront for static |
| CORS config on API | not yet written | needed for browser → API calls |
| Auth / access control on API | not yet written | at minimum a shared key during dev |

**From product brief:** SA-first, mobile-first, clean and fast. Latency to Saudi matters.
CloudFront has edge nodes in Riyadh and Jeddah — an AWS-hosted static Next.js export
served via CloudFront would have the best latency profile for the target audience.
Vercel's edge network also covers the Gulf but adds a third-party dependency.

**Question to resolve:** Preference for keeping everything in AWS vs Vercel's simpler
Next.js deployment experience?

---

## Discussion Output Required

Before any code is written, this ticket should produce written decisions on:

- [ ] Repo location
- [ ] Framework
- [ ] v0 scope (PLP only, or PLP + PDP)
- [ ] Design process (wireframes / v0.dev / debug-first)
- [ ] Hosting (Vercel vs AWS)
- [ ] Domain name
