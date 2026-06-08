# Ticket: PLP Debug UI — Visual API Validator

**Status: ready for implementation**

## Purpose

This is not the product. It is a visual sanity check for the API and data pipeline —
the analogue of opening a spreadsheet to confirm the numbers look right, except the
"spreadsheet" renders as a product listing page (PLP). The goal is to catch data
problems (missing images, wrong prices, garbled Arabic text, broken discount math)
that are invisible in raw JSON but obvious in a visual layout.

Build this before building the real frontend. It removes the risk of discovering a
broken data model only after a polished UI is already layered on top of it.

---

## What It Shows

Each product card displays:
- Product name (in the selected language)
- Brand (canonical)
- Site name (e.g. `ounass`, `level-shoes`)
- Price + currency
- Price before discount (if discounted)
- Discount percentage (if present)
- Product image (from CDN)
- Link to original PDP (opens in new tab)

---

## Interactions

### Language toggle
Switch between `en` and `ar`. The toggle filters the API response to only show
rows where `language = {selected}`. Arabic view should render RTL. This is the
primary test for whether i18n data is correct — garbled names or missing Arabic
rows are immediately visible.

### Top-bar filters (AND logic)
Three dropdowns populated from the API response (or a `/filters` endpoint):
- **Category** — canonical values from `category_canonical`
- **Subcategory** — canonical values from `subcategory_canonical`, scoped to
  selected category
- **Brand** — canonical values from `brand_canonical`

Selecting a filter re-fetches `/products` with the new query params. No client-side
filtering — the API must handle it, so filters also validate API correctness.

### Site toggle (optional for MVP)
Checkbox or pill toggle per site (ounass / level-shoes) to isolate one site's data.

---

## Technology Options

### Option A: Streamlit

Python-only, no HTML/CSS/JS knowledge required. Deploys with `streamlit run app.py`.

**Strengths**
- You already know Python — no context switch
- A working PLP with filters and language toggle is ~150 lines of code
- Built-in layout primitives (columns, sidebar, selectbox, image)
- Fast iteration: change Python, browser refreshes

**Weaknesses**
- Looks like a data tool, not a product page — card layout and RTL rendering require
  custom HTML components (`st.markdown` with unsafe HTML or `st.components.v1.html`)
- Arabic RTL text needs a `direction: rtl` CSS override in an HTML component;
  doable but not native
- Not deployable as a production frontend — useful only for internal validation

**When to choose:** If the goal is purely data validation and you want to be running
within an hour, use Streamlit.

### Option B: Plain HTML + Fetch (single file)

A single `index.html` with vanilla JS `fetch()` calls to the API, Tailwind CSS via
CDN for styling, no build step.

**Strengths**
- No build tools, no npm, no Node — open the file in a browser
- Tailwind's `dir="rtl"` attribute handles Arabic layout correctly
- Looks closer to a real PLP — product grid, card proportions, image sizing
- Easier to evolve into the real frontend later (copy the card component into Next.js)
- Zero new dependencies

**Weaknesses**
- Requires writing HTML and basic JS — unfamiliar territory, but the patterns are
  mechanical (fetch → map → render cards) and easy to explain/generate

**When to choose:** If the goal is to see something that looks like an actual product
page and can be shared with a non-technical stakeholder, use this. The step from
"data looks right" to "show someone else" is much smaller.

---

## Recommendation

**Option B (plain HTML)** for this use case. The RTL/Arabic requirement means
Streamlit needs custom HTML components anyway, eliminating its main advantage.
A single-file HTML approach gets you a grid that looks like a PLP, handles RTL
natively via Tailwind, and produces a shareable artifact. The JS involved is
`fetch → JSON.parse → template string` — generatable without prior JS experience.

---

## Layout Sketch

```
┌──────────────────────────────────────────────────────────────────┐
│  [Category ▼]  [Subcategory ▼]  [Brand ▼]          [EN] [AR]    │
├──────────────────────────────────────────────────────────────────┤
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐        │
│  │  [img]   │  │  [img]   │  │  [img]   │  │  [img]   │        │
│  │ Name     │  │ Name     │  │ Name     │  │ Name     │        │
│  │ Brand    │  │ Brand    │  │ Brand    │  │ Brand    │        │
│  │ Site     │  │ Site     │  │ Site     │  │ Site     │        │
│  │ SAR 850  │  │ SAR 850  │  │ SAR 850  │  │ SAR 850  │        │
│  │ ~~1200~~ │  │          │  │ ~~1200~~ │  │          │        │
│  │ -29%     │  │          │  │ -29%     │  │          │        │
│  └──────────┘  └──────────┘  └──────────┘  └──────────┘        │
└──────────────────────────────────────────────────────────────────┘
```

Arabic mode: entire layout flips RTL (`<html dir="rtl">`), product name and brand
render in Arabic, filters remain in the same positions but text aligns right.

---

## Acceptance Criteria

- Grid renders product image, name, brand, site, price, discounted price (if applicable)
- Each card links to the original PDP
- Language toggle switches between en/ar rows and flips layout direction
- Category → subcategory → brand filters narrow the grid; clearing a filter widens it
- Missing image shows a placeholder, not a broken image icon
- Works locally by pointing `API_BASE_URL` at `http://localhost:8000`

---

## Work Items

| File | Change |
|------|--------|
| `ui/index.html` | New — single-file PLP debug UI |
| `ui/README.md` | How to run locally (set API base URL, open in browser) |

---

## Open Questions

- [ ] Should the UI be committed to this repo or a separate `frontend` repo?
      For MVP debug purposes, a `ui/` folder here is fine — revisit when the real
      frontend repo decision is made in `tickets/frontend_v0_discussion.md`.
- [x] Pagination: numbered pages. Simpler to debug, bookmarkable.
- [x] Language toggle: show bilingual stacked cards (Arabic name above, English below)
      for data validation purposes. Arabic-first per product brief, so Arabic sits on top.
      The real product will show single language; the debug UI shows both to surface gaps.
- [x] Products with no image: show a placeholder (grey box with "no image" label), never
      hide. Coverage gaps need to be visible for data validation.
- [x] Default view: Arabic. Arabic is the primary language per product brief. The toggle
      starts on AR; clicking EN switches the layout to LTR.
