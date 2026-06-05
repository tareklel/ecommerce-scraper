# Ticket: Frontend v0 — Design Discussion

**Status: blocked on `tickets/website_description.md`**

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

**Question to resolve:** Is the frontend a separate product with its own release
cadence, or is it tightly coupled to data pipeline changes during v0?

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

**Question to resolve:** Is v0 a shippable product (→ Next.js) or an internal
data validation tool (→ plain HTML from `plp_debug_ui.md`)? This hinges on the
website description.

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

**Question to resolve:** Does the website description change this order? For
example, if the primary user action is "search for a specific item," then a
search bar becomes a higher priority than a browsing PLP.

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
| Image CDN (CloudFront) | `tickets/image_serving.md` | blocked on description |
| Product API (Lambda + cache export) | `tickets/product_api.md` | blocked on description |
| Custom domain + SSL cert (ACM) | not yet written | needed before any public URL |
| AWS account for frontend hosting | not yet written | Vercel is simpler for Next.js; S3+CloudFront for static |
| CORS config on API | not yet written | needed for browser → API calls |
| Auth / access control on API | not yet written | at minimum a shared key during dev |

**Question to resolve:** Vercel vs AWS for frontend hosting? Vercel is near-zero
config for Next.js and free at low traffic. AWS keeps everything in one account and
avoids a third-party dependency. For a Gulf-focused product, AWS `me-central-1`
(Bahrain) or `eu-central-1` (Frankfurt) origin may matter for latency.

---

## Discussion Output Required

Before any code is written, this ticket should produce written decisions on:

- [ ] Repo location
- [ ] Framework
- [ ] v0 scope (PLP only, or PLP + PDP)
- [ ] Design process (wireframes / v0.dev / debug-first)
- [ ] Hosting (Vercel vs AWS)
- [ ] Domain name
