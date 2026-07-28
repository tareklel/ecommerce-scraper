# Ticket: Image Serving — CloudFront vs Presigned URLs

**Status: done ✓** (CloudFront live — implemented in `price-comparison-web`, 2026-06-27)

---

## Decision: CloudFront (Option B)

CloudFront distribution sits in front of `bronze/{env}/images/by-hash/` with OAC so S3 stays private.

**Current CDN host**: `https://d2wbzj01hegmbm.cloudfront.net`  
**URL scheme**: `/i/{sha256}.{ext}` → rewrites to `bronze/{env}/images/by-hash/{sha256}.{ext}` at the edge via CloudFront Function.

The placeholder CloudFront domain is **temporary** — upgrade to a custom domain (`images.{domain}`) once the product site name is confirmed. This is the only thing still pending; the CDN itself is production-ready.

Presigned URLs were considered (Option A) but ruled out — they expire, can't be cached, and create a migration cost. They were used only in a single offline debug session before CloudFront went live.

---

## What was built (in `price-comparison-web`)

| File | What |
|------|------|
| `infra/cloudfront_images.tf` | CloudFront distribution, OAC, CloudFront Function, immutable Cache-Control response headers policy |
| `infra/cloudfront_function.js` | URI rewrite `/i/{hash}` → `bronze/dev/images/by-hash/{hash}` |
| `infra/s3_image_bucket_policy.tf` | OAC `s3:GetObject` on `bronze/dev/images/by-hash/*` and `bronze/prod/images/by-hash/*` |
| `infra/outputs.tf` | `image_cdn_host` output |
| `src/lib/image-url.ts` | `imageUrl(hash)` helper |
| `api/tests/test_cdn_smoke.py` | 4 smoke tests (accessible, immutable cache-control, edge hit, 403 on missing) |

**Note on path**: Images are stored as `bronze/{env}/images/by-hash/{sha256}` (env-prefixed), not the flat `bronze/images/by-hash/` path assumed in early planning. OAC policy covers both `dev` and `prod` prefixes.

---

## Remaining

- [ ] **Custom domain** — placeholder `d2wbzj01hegmbm.cloudfront.net` → `images.{domain}` once site name confirmed. ~10 lines of Terraform + ACM cert.
- [ ] **Image resizing** — tracked in separate `image_resizing.md` ticket (CloudFront Functions `?w=400` scheme). Unblocked now that CDN is live.
