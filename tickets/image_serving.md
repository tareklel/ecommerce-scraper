# Ticket: Image Serving — CloudFront vs Presigned URLs

**Status: rumination — blocked on website description (see `tickets/website_description.md`)**

## Goal

Surface product images stored at `bronze/images/by-hash/{sha256}` to the UI layer.
Images are content-addressed (filename = SHA256 of content), immutable, and currently
private in S3. Nothing can display them without a serving layer.

---

## Option A: S3 Presigned URLs

The API generates a time-limited signed URL per image at request time using boto3.

**Strengths**
- Zero infrastructure — no Terraform, no new AWS resources
- Works immediately; good for the first debugging session
- Bucket stays private; no public exposure

**Weaknesses**
- URLs expire (max 7 days with IAM roles, default 1 hour) — the UI cannot safely
  cache or bookmark any image link
- Every URL generation is a synchronous SDK call in the API request path, adding
  latency proportional to the number of products on the page
- Cannot be cached by a browser or CDN — every page load re-fetches from S3 origin
- Leaks internal S3 key structure and bucket name to the browser
- Dead end: cannot be used in a mobile app, email, or any surface outside the
  immediate session

**Long-term fit:** None. Presigned URLs are a temporary debug shortcut. Using them
beyond the first prototype creates a migration cost later (all cached/shared URLs
break when keys are regenerated).

---

## Option B: CloudFront Distribution

A CloudFront distribution sits in front of `bronze/images/by-hash/` with an
Origin Access Control policy so S3 stays private. The distribution serves
`https://images.{domain}/by-hash/{sha256}`.

**Strengths**
- Stable, permanent URLs — `s3_blob_key` in the gold table maps directly to a URL
  with no runtime SDK call
- Images are content-addressed and immutable → `Cache-Control: max-age=31536000`
  is safe; CloudFront and browser cache the image forever after first fetch
- Edge cached globally — fast for users in UAE/KSA regardless of S3 region
- Hides S3 internals; custom domain possible
- URL structure is predictable: the API just prefixes the blob key with the CDN host,
  no per-request AWS call needed
- Scales to mobile app, email thumbnails, social sharing without any change

**Weaknesses**
- Small Terraform addition (~30 lines: distribution, OAC policy, S3 bucket policy)
- Small cost: CloudFront data transfer (~$0.0085/GB out), negligible at MVP scale
- Cache invalidation needed if an image is ever replaced (shouldn't happen with
  content-addressed storage — hash changes if content changes)

**Long-term fit:** This is the production path. Because filenames are hashes,
the same URL works across environments (dev/prod point to the same hash namespace).
It also feeds into product matching: two products with the same `s3_blob_key` are
likely the same physical item.

---

## Recommendation

**CloudFront.** The setup is ~30 lines of Terraform and saves a migration later.
The content-addressed key scheme means cache TTL can be infinite — CloudFront becomes
nearly free at this scale because images are fetched once per edge location, ever.

Presigned URLs are acceptable for a single offline debugging session but should not
be committed to any API or UI code.

---

## Work Items (CloudFront path)

| File | Change |
|------|--------|
| `infra/terraform/cloudfront.tf` | New — distribution, OAC, S3 bucket policy attachment |
| `infra/terraform/variables.tf` | `image_cdn_domain` output |
| API config | `IMAGE_CDN_HOST` env var; API prepends it to `s3_blob_key` |

---

## Open Questions

- [ ] Custom domain (`images.{domain}`) now or placeholder CloudFront domain for MVP?
- [ ] Should `bronze/images/by-hash/` remain in `eu-central-1` or move to a region
      closer to the target audience (me-central-1 / Bahrain)?
- [ ] Do we want image resizing at the CDN layer (CloudFront Functions or Lambda@Edge)
      for thumbnails vs full-size? Not needed for MVP but worth plumbing for.
