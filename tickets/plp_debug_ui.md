# Ticket: PLP Debug UI — Visual API Validator

**Status: ready for implementation**

## Purpose

Visual sanity check for the API and data pipeline before the real product is designed.
The goal is to catch data problems — missing images, wrong prices, garbled Arabic text,
broken discount math — that are invisible in raw JSON but obvious in a grid of product
cards.

Build this before designing the real PLP. It removes the risk of discovering a broken
data model after a polished UI is layered on top of it. The debug UI code also becomes
the foundation of the real PLP — no throwaway.

---

## Technology: Next.js

**Not plain HTML.** The real product uses Next.js; starting here means the debug UI
code graduates into the real PLP rather than being thrown away.

Running locally: `npm run dev` → open `localhost:3000`. That is the entire dev loop.
No cloud, no deployment. Hot-reload means changes appear in the browser immediately.

This lives in the `price-comparison-web` repo (new, sibling to this repo in `../`).

### Local images
CloudFront is not needed to see images locally. Use presigned S3 URLs as a shortcut
for dev sessions — they expire but that's fine when you're just looking at the data.
Replace with CloudFront CDN URLs once `tickets/image_serving.md` is implemented.

---

## What It Shows

Each product card:
- Product name in Arabic (top) and English (below) — bilingual stacked for data validation
- Brand (canonical)
- Site name (`ounass`, `level-shoes`)
- Price in SAR + currency
- Price before discount struck through (if discounted)
- Discount percentage badge (if present)
- Product image
- Link to original PDP (opens in new tab)

Default view: Arabic (RTL layout). Language toggle switches to English (LTR).

---

## Interactions

### Language toggle
AR (default) / EN. Flips `dir` on the root element — entire layout mirrors.
Both name variants are always present on the card; the toggle changes which is
shown prominently vs dimmed.

### Top-bar filters (AND logic)
Three dropdowns populated from the API:
- **Category** — `category_canonical`
- **Subcategory** — `subcategory_canonical`, scoped to selected category
- **Brand** — `brand_canonical`

Filters re-fetch `/products` with updated query params. No client-side filtering —
this validates the API, not just the UI.

### Site toggle
Pill toggle per site to isolate one site's data.

---

## Layout Sketch

```
┌──────────────────────────────────────────────────────────────────┐
│  [Category ▼]  [Subcategory ▼]  [Brand ▼]          [AR] [EN]    │
├──────────────────────────────────────────────────────────────────┤
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐        │
│  │  [img]   │  │  [img]   │  │  [img]   │  │  [img]   │        │
│  │ AR name  │  │ AR name  │  │ AR name  │  │ AR name  │        │
│  │ EN name  │  │ EN name  │  │ EN name  │  │ EN name  │        │
│  │ Brand    │  │ Brand    │  │ Brand    │  │ Brand    │        │
│  │ Site     │  │ Site     │  │ Site     │  │ Site     │        │
│  │ SAR 850  │  │ SAR 850  │  │ SAR 850  │  │ SAR 850  │        │
│  │ ~~1200~~ │  │          │  │ ~~1200~~ │  │          │        │
│  │ -29%     │  │          │  │ -29%     │  │          │        │
│  └──────────┘  └──────────┘  └──────────┘  └──────────┘        │
└──────────────────────────────────────────────────────────────────┘
```

Arabic mode: full RTL, cards flow right-to-left, text aligns right.
No-image products: grey placeholder box with "لا توجد صورة / no image" — never hidden.

---

## Acceptance Criteria

- Grid renders bilingual product name, brand, site, SAR price, discounted price
- Each card links to the original PDP
- AR toggle: RTL layout, Arabic name prominent; EN toggle: LTR, English prominent
- Category → subcategory → brand filters narrow the grid
- No-image products show placeholder, not broken icon
- Runs locally at `localhost:3000` with API at `localhost:8000`

---

## Work Items

| File | Repo | Change |
|------|------|--------|
| `app/page.tsx` | `price-comparison-web` | PLP page — product grid, filter bar, language toggle |
| `components/ProductCard.tsx` | `price-comparison-web` | Bilingual card component |
| `components/FilterBar.tsx` | `price-comparison-web` | Category/subcategory/brand dropdowns |
| `.env.local` | `price-comparison-web` | `NEXT_PUBLIC_API_BASE_URL=http://localhost:8000` |

---

## Resolved Questions

- [x] Framework: Next.js (not plain HTML) — debug code graduates to real product
- [x] Language toggle: bilingual stacked cards (AR top, EN below) for data validation
- [x] No-image: show placeholder, never hide
- [x] Default view: Arabic (RTL)
- [x] Pagination: numbered pages
- [x] Images locally: presigned S3 URLs (dev shortcut, replaced by CloudFront later)
- [x] Repo: `price-comparison-web` in `../`
