# Ticket: Frontend v0 — Design Discussion

**Status: closed — repo created, decisions implemented**

---

## What Was Done

- `price-comparison-web` repo created at `../price-comparison-web` and pushed to
  github.com/tareklel/price-comparison-web
- Next.js 16 scaffolded (TypeScript, Tailwind CSS, App Router, `src/` directory)
- `next-intl` installed for Arabic/English i18n
- `context/` layer added: REPO_CHARTER.md, AGENTS.md, product-brief.md, memory.md
- `CLAUDE.md` indexes root AGENTS.md (Next.js version rules) + all context files
- `.env.example` created with `NEXT_PUBLIC_API_BASE_URL` and `NEXT_PUBLIC_IMAGE_CDN_HOST`
- Node.js v24.16.0 installed via nvm; nvm wired into `~/.zshrc`

---

## Decisions Made

### Repo
`price-comparison-web` as a sibling repo in `../`. Debug UI code starts there from
day one — no throwaway, no `ui/` folder in this repo.

### Framework
**Next.js 16, static export, hosted on AWS (S3 + CloudFront).**
Static export: Next.js builds HTML at build time, CloudFront serves it from Riyadh/
Jeddah edge nodes. Daily rebuild after dbt run. No running server.
Vercel not used — adds a third-party dependency to an AWS-native stack.
`next-intl` for Arabic-first routing with RTL layout.

### Design Process
Debug UI in Next.js with real data first. The debug UI code graduates into the real
PLP — not throwaway. Figma skipped: a luxury fashion PLP is a well-understood pattern
and the unknowns are content questions answered by seeing real data, not wireframing.

### Hosting
AWS: S3 + CloudFront. Same account, same Terraform patterns.

### v0 Scope
PLP + PDP. No search bar at v0. Browse-first (new arrivals default, category/brand
filters). Cross-site comparison, price history, alerts are mid-term.

### Contractor
No contractor until after the debug UI is working with real data. Then 2–3 weeks
for Arabic RTL polish + luxury mobile UX feel.

---

## Where Everything Went

All active work is now in `../price-comparison-web/tickets/`:

| Item | Ticket |
|---|---|
| Product API | `product_api.md` |
| Debug UI | `plp_debug_ui.md` |
| Real PLP (Next.js) | `plp_nextjs.md` |
| PDP | `pdp.md` |
| Frontend hosting and deployment | `frontend_hosting.md` |
| API auth and CORS | `api_auth_cors.md` |
| Image CDN | `../ecommerce-scraper/tickets/image_serving.md` |

Remaining open: domain name, contractor timing.
