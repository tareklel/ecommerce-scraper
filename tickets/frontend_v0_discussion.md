# Ticket: Frontend v0 — Design Discussion

**Status: mostly resolved — two open items remain (domain, contractor timing)**

---

## Decisions Made

### Repo
**`price-comparison-web` as a sibling repo in `../`.**
The debug UI (`tickets/plp_debug_ui.md`) can live in `ui/` inside this repo temporarily,
but the real Next.js product starts in its own repo from day one. No mixing with the
scraper.

### Framework
**Next.js with static export, hosted on AWS (S3 + CloudFront).**

Static export means Next.js builds every page into plain HTML at build time. The result
is a folder of files served by S3 + CloudFront — no running server, no Lambda, nothing
computed per request. CloudFront edge nodes in Riyadh and Jeddah serve pre-built HTML
to Saudi mobile users with sub-second load times. The site rebuilds daily after dbt runs.
This is the right shape for a daily-refresh product catalogue.

Vercel (the company behind Next.js) also runs a hosting platform that deploys Next.js
with minimal config. It is not being used — it adds a third-party dependency to an
otherwise AWS-native stack and offers no meaningful advantage given CloudFront already
covers the Gulf.

Key Next.js capabilities this product needs:
- `next-intl` for Arabic-first routing with RTL layout (`dir="rtl"` applied at the
  locale level, not manually per component)
- Static export for S3+CloudFront deployment
- SEO: product pages need to be indexable (Arabic product names in `<title>` and meta)
- Image optimisation: `next/image` with CloudFront as the loader

Remix is not being used. Next.js is the right choice: more mature Arabic/RTL ecosystem,
more contractors know it, better training data.

Plain HTML + Tailwind is right for the **debug UI only** (`tickets/plp_debug_ui.md`).

### Design Process
**Build the debug UI in Next.js with real data first, then design.**

The debug UI is not a throwaway — it uses Next.js (same as the real product) and lives
in `price-comparison-web` from the start. Its cards and filter logic become the foundation
of the real PLP. Figma is skipped: a luxury fashion PLP is a well-understood layout
pattern and the unknowns are content questions (how long are Arabic names, what does
SAR + discount look like, how much image coverage exists) answered by seeing real data,
not by wireframing.

### Hosting
**AWS: S3 + CloudFront for the static Next.js export.**
Same account, same Terraform patterns, CloudFront edge coverage in Riyadh and Jeddah.
No new vendor relationships.

### v0 Scope
**PLP + PDP, in that order.** Confirmed by product brief.
No search bar at v0. Browse-first (new arrivals default, category/brand filters).
Cross-site product matching, price history, and alerts are mid-term.

### Contractor
Zero JS experience is a real constraint but not an immediate blocker.

What can be built without a contractor:
- The plain HTML debug UI entirely
- Next.js project setup, routing, API wiring, filter/pagination logic (generated)
- Basic Tailwind responsive grid layout (generated)

Where a contractor is worth it:
- Arabic typography: font selection (Cairo, IBM Plex Arabic, Noto Naskh) and
  text rendering on mobile. Getting this wrong makes the site look non-native.
- Luxury mobile UX feel: image loading, scroll behaviour, touch interactions.
  The gap between "technically correct" and "feels like Farfetch" lives here.
- RTL edge cases: bidirectional text, mixed AR/EN strings, filter drawer positioning.

**Plan:** no contractor until after the debug UI is working with real data. At that
point, 2–3 weeks with someone who knows Next.js + Arabic RTL to build the visual shell.
After that, the codebase is maintainable and extendable going forward.

---

## Priority Order

1. Create `price-comparison-web` repo, scaffold Next.js with static export + `next-intl`
2. Product API running locally (`tickets/product_api.md` — local first, cloud later)
3. Debug UI in Next.js (`tickets/plp_debug_ui.md`) — real data, local browser
4. CloudFront image serving (`tickets/image_serving.md`) — presigned URLs for local dev,
   CloudFront before public URL
5. PLP polish in Next.js — Arabic-first, mobile-first, new arrivals default, sale filter
6. PDP — product image, name, price, retailer buy link; cross-site comparison is mid-term

---

## Infrastructure Prerequisites

To **see the site in a local browser** (no cloud needed):

| Prerequisite | Notes |
|---|---|
| Product API on `localhost:8000` | FastAPI reading from a local JSON snapshot of the gold table |
| CORS: allow `localhost:3000` | One line in FastAPI dev config |
| Images: presigned S3 URLs | Acceptable shortcut for dev sessions — no new infra |

To **put the site on a public URL** (cloud work):

| Prerequisite | Ticket | Status |
|---|---|---|
| Image CDN (CloudFront) | `tickets/image_serving.md` | ready for implementation |
| Product API deployed (Lambda) | `tickets/product_api.md` | ready for implementation |
| S3 bucket + CloudFront for frontend static files | not yet written | |
| Custom domain + SSL cert (ACM) | not yet written | blocked on domain name |
| CORS config on deployed API | not yet written | |
| API auth (shared key) | not yet written | |

---

## Remaining Open Items

- [ ] Domain name — TBD; needed before ACM cert and CloudFront custom domain are set up
- [ ] Contractor timing — after debug UI confirms data quality, before Next.js visual
      shell is built; scope: Arabic RTL polish + luxury mobile UX, ~2–3 weeks
