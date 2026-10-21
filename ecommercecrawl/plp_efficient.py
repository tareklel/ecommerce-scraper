"""
Inputs and startup checks for the Ounass PLP-efficient crawl.

Reference: docs/ounass_plp_efficient_crawl.md, section 2 (Inputs) and
section 5 ("Startup checks, in detail"). Plain functions with no Scrapy, so
the spider (Part 3) and scripts/preflight_ounass_plp_efficient.py run exactly
the same code and can't disagree.

Flow: invoke_export() -> load_inputs_from_manifest() (or load_inputs() for
local files) -> validate() -> ValidationResult, which carries every problem
plus the decision for each row (valid / skipped / quarantined / held back).
"""

import csv
import io
import json
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import ROUND_HALF_UP, Decimal
from urllib.parse import urlparse

from ecommercecrawl.constants.ounass_constants import (
    COUNTRY_CURRENCY,
    TLD_COUNTRY_MAP,
    TLD_LANGUAGE_MAP,
)

# Columns of the CSV contracts written by scraper-pipeline's export
# (scripts/export_plp_efficient_inputs.py there). Extra columns are allowed;
# missing ones fail G2.
PLP_COLUMNS = (
    "url", "site", "country", "language", "gender",
    "category", "subcategory", "brand",
)
PDP_COLUMNS = (
    "portal_itemid", "primary_key", "site", "country", "language", "url",
    "gender", "category", "subcategory", "brand",
    "out_of_stock", "last_available_date", "last_crawl_date",
)
VOCABULARY_KEYS = ("country", "language", "gender", "category_subcategory", "brand")

# Scope keys compared between a PLP row and a PDP row. Values are
# canonical, lowercase keys; brand on a PLP row is optional (None = any).
SCOPE_KEYS = ("site", "country", "language", "gender", "category", "subcategory")

# Severities, mildest first. A single STOP means the crawl doesn't start.
WARN = "warn"
SKIP = "skip"              # PLP row left out (its products are held back)
QUARANTINE = "quarantine"  # PDP row left out (not refreshed, not PDP-crawled)
STOP = "stop"


class ExportError(RuntimeError):
    """The scraper-pipeline export could not produce inputs; the run must stop."""


@dataclass(frozen=True)
class Problem:
    check: str          # e.g. "G1", "G2", "G7", "G8", "G10", "STALE", "COVERAGE"
    severity: str       # WARN / SKIP / QUARANTINE / STOP
    message: str
    source: str | None = None   # "plp_list", "pdp_list", "vocabulary", "manifest"
    row: int | None = None      # 1-based data row (header not counted)


@dataclass
class Inputs:
    plp_rows: list | None
    pdp_rows: list | None
    vocabulary: dict | None
    manifest: dict | None = None
    plp_columns: list = field(default_factory=list)
    pdp_columns: list = field(default_factory=list)
    sources: dict = field(default_factory=dict)
    load_errors: dict = field(default_factory=dict)


@dataclass
class Config:
    max_bad_plp_rows_ratio: float = 0.25
    max_bad_pdp_rows_ratio: float = 0.05
    gold_warn_age_days: float = 2
    gold_max_age_days: float = 3
    stale_crawl_days: int = 7
    max_phase2_pdps: int = 10000
    missing_ratio_cap: float = 0.25
    field_mismatch_ratio: float = 0.05
    site: str = "ounass"

    @classmethod
    def from_settings(cls, settings):
        """Build from Scrapy settings or any mapping with .get()."""
        def get(name, default, cast):
            value = settings.get(name, default)
            return cast(value) if value is not None else default

        return cls(
            max_bad_plp_rows_ratio=get("OUNASS_PLP_EFFICIENT_MAX_BAD_PLP_ROWS_RATIO", 0.25, float),
            max_bad_pdp_rows_ratio=get("OUNASS_PLP_EFFICIENT_MAX_BAD_PDP_ROWS_RATIO", 0.05, float),
            gold_warn_age_days=get("OUNASS_PLP_EFFICIENT_GOLD_WARN_AGE_DAYS", 2, float),
            gold_max_age_days=get("OUNASS_PLP_EFFICIENT_GOLD_MAX_AGE_DAYS", 3, float),
            stale_crawl_days=get("OUNASS_PLP_EFFICIENT_STALE_CRAWL_DAYS", 7, int),
            max_phase2_pdps=get("OUNASS_PLP_EFFICIENT_MAX_PHASE2_PDPS", 10000, int),
            missing_ratio_cap=get("OUNASS_PLP_EFFICIENT_MISSING_RATIO_CAP", 0.25, float),
            field_mismatch_ratio=get("OUNASS_PLP_EFFICIENT_FIELD_MISMATCH_RATIO", 0.05, float),
        )


@dataclass
class ValidationResult:
    problems: list = field(default_factory=list)
    valid_plp_rows: list = field(default_factory=list)
    skipped_plp_rows: list = field(default_factory=list)
    valid_pdp_rows: list = field(default_factory=list)
    quarantined_pdp_rows: list = field(default_factory=list)
    # Valid PDP rows only covered by skipped PLPs: neither refreshed nor
    # PDP-crawled, so a broken listing row can't trigger a burst of PDP crawls.
    held_back_pdp_rows: list = field(default_factory=list)
    # Valid PDP rows no listing covers: they go straight to Phase 2.
    uncovered_pdp_rows: list = field(default_factory=list)
    stale_pdp_rows: list = field(default_factory=list)
    gold_age_days: float | None = None

    @property
    def stop(self):
        return any(p.severity == STOP for p in self.problems)

    def by_severity(self, severity):
        return [p for p in self.problems if p.severity == severity]


# ---------------------------------------------------------------------------
# Normalization and matching
# ---------------------------------------------------------------------------

def _clean(value):
    if value is None:
        return None
    value = str(value).strip()
    return value or None


def normalize_row(row):
    """
    Canonical keys lowercased and trimmed; empty strings become None.
    Inputs use scraper-pipeline's lowercase keys (`ar`/`en`), so language is
    effectively compared case-insensitively.
    """
    out = {key: _clean(value) for key, value in row.items()}
    for key in SCOPE_KEYS + ("brand",):
        if out.get(key) is not None:
            out[key] = out[key].lower()
    return out


def scope_key(row):
    return tuple(row.get(key) for key in SCOPE_KEYS)


def plp_covers_pdp(plp, pdp):
    """True if a (normalized) PLP row's scope includes a (normalized) PDP row."""
    if scope_key(plp) != scope_key(pdp):
        return False
    return plp.get("brand") is None or plp.get("brand") == pdp.get("brand")


def _build_scope_index(plp_rows):
    """scope key -> set of brands (None = any brand) for fast coverage lookups."""
    index = {}
    for plp in plp_rows:
        index.setdefault(scope_key(plp), set()).add(plp.get("brand"))
    return index


def _covered(index, pdp):
    brands = index.get(scope_key(pdp))
    return bool(brands) and (None in brands or pdp.get("brand") in brands)


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------

def _s3_client():
    import boto3

    return boto3.client("s3")


def read_text(source, s3_client=None):
    """Read a local path or an s3://bucket/key URI as UTF-8 text."""
    if source.startswith("s3://"):
        parsed = urlparse(source)
        bucket, key = parsed.netloc, parsed.path.lstrip("/")
        if not bucket or not key:
            raise ValueError(f"Invalid S3 URI: {source}")
        client = s3_client or _s3_client()
        body = client.get_object(Bucket=bucket, Key=key)["Body"].read()
        return body.decode("utf-8-sig")
    with open(source, encoding="utf-8-sig") as f:
        return f.read()


def parse_csv(text):
    reader = csv.DictReader(io.StringIO(text))
    rows = [dict(row) for row in reader]
    return list(reader.fieldnames or []), rows


def load_inputs(plp_source, pdp_source, vocabulary_source, manifest=None, s3_client=None):
    """
    Load the three inputs. A source that's missing or unreadable is recorded
    in load_errors (and left as None) so G2 can report it, rather than
    raising on the first one.
    """
    inputs = Inputs(
        plp_rows=None, pdp_rows=None, vocabulary=None, manifest=manifest,
        sources={"plp_list": plp_source, "pdp_list": pdp_source,
                 "vocabulary": vocabulary_source},
    )
    for name, source in inputs.sources.items():
        if not source:
            inputs.load_errors[name] = "no source given"
            continue
        try:
            text = read_text(source, s3_client=s3_client)
            if name == "vocabulary":
                inputs.vocabulary = json.loads(text)
            elif name == "plp_list":
                inputs.plp_columns, inputs.plp_rows = parse_csv(text)
            else:
                inputs.pdp_columns, inputs.pdp_rows = parse_csv(text)
        except Exception as exc:  # report every unreadable input, don't stop at the first
            inputs.load_errors[name] = f"{type(exc).__name__}: {exc}"
    return inputs


def load_inputs_from_manifest(manifest, s3_client=None):
    files = (manifest or {}).get("files") or {}

    def uri(name):
        return (files.get(name) or {}).get("uri")

    return load_inputs(uri("plp_list"), uri("pdp_list"), uri("vocabulary"),
                       manifest=manifest, s3_client=s3_client)


def invoke_export(lambda_name, site="ounass", lambda_client=None):
    """
    Run scraper-pipeline's export Lambda synchronously and return its manifest.
    Raises ExportError on any failure: the crawl must stop before spending
    Zyte budget when it can't get fresh inputs.
    """
    if lambda_client is None:
        import boto3
        from botocore.config import Config as BotoConfig

        # The export can take a while (Athena); never retry it blindly.
        lambda_client = boto3.client(
            "lambda",
            config=BotoConfig(read_timeout=900, connect_timeout=10,
                              retries={"max_attempts": 0}),
        )
    try:
        response = lambda_client.invoke(
            FunctionName=lambda_name,
            InvocationType="RequestResponse",
            Payload=json.dumps({"site": site, "source": "ecommerce-scraper"}).encode("utf-8"),
        )
    except Exception as exc:
        raise ExportError(f"Could not invoke {lambda_name}: {exc}") from exc

    payload = response["Payload"].read().decode("utf-8")
    if response.get("FunctionError"):
        raise ExportError(f"{lambda_name} failed: {payload[:500]}")
    if response.get("StatusCode") != 200:
        raise ExportError(f"{lambda_name} returned status {response.get('StatusCode')}")
    manifest = json.loads(payload)
    if not isinstance(manifest, dict) or not manifest.get("files"):
        raise ExportError(f"{lambda_name} returned no manifest: {payload[:500]}")
    return manifest


# ---------------------------------------------------------------------------
# Startup checks
# ---------------------------------------------------------------------------

def _parse_date(value):
    try:
        return date.fromisoformat(str(value).strip()[:10]) if value else None
    except ValueError:
        return None


def _check_files(inputs):
    """G2: all three inputs present, with every expected column."""
    problems = []
    for name, error in inputs.load_errors.items():
        problems.append(Problem("G2", STOP, f"{name} unavailable ({error})", source=name))
    if inputs.plp_rows is not None:
        missing = [c for c in PLP_COLUMNS if c not in inputs.plp_columns]
        if missing:
            problems.append(Problem("G2", STOP, f"plp_list missing columns {missing}", source="plp_list"))
    if inputs.pdp_rows is not None:
        missing = [c for c in PDP_COLUMNS if c not in inputs.pdp_columns]
        if missing:
            problems.append(Problem("G2", STOP, f"pdp_list missing columns {missing}", source="pdp_list"))
    if inputs.vocabulary is not None:
        missing = [k for k in VOCABULARY_KEYS if k not in inputs.vocabulary]
        if missing:
            problems.append(Problem("G2", STOP, f"vocabulary missing keys {missing}", source="vocabulary"))
    return problems


def _vocabulary_sets(vocabulary):
    def lower_set(key):
        return {str(v).strip().lower() for v in vocabulary.get(key) or []}

    pairs = {
        (str(c).strip().lower(), str(s).strip().lower())
        for c, s in (vocabulary.get("category_subcategory") or [])
    }
    return {
        "country": lower_set("country"),
        "language": lower_set("language"),
        "gender": lower_set("gender"),
        "brand": lower_set("brand"),
        "pairs": pairs,
    }


def _canonical_errors(row, vocab, site):
    """Shared G1/G10 checks: required scope keys present and canonical."""
    errors = []
    for key in SCOPE_KEYS:
        if row.get(key) is None:
            errors.append(f"{key} is empty")
    if row.get("site") and row["site"] != site:
        errors.append(f"site '{row['site']}' is not '{site}'")
    for key in ("country", "language", "gender"):
        if row.get(key) and row[key] not in vocab[key]:
            errors.append(f"{key} '{row[key]}' not in vocabulary")
    if row.get("category") and row.get("subcategory") and \
            (row["category"], row["subcategory"]) not in vocab["pairs"]:
        errors.append(f"category/subcategory '{row['category']}/{row['subcategory']}' not in vocabulary")
    if row.get("brand") and row["brand"] not in vocab["brand"]:
        errors.append(f"brand '{row['brand']}' not in vocabulary")
    return errors


def _host_errors(row):
    """G7: the URL is a JSON listing endpoint whose host serves the row's country and language."""
    url = row.get("url")
    if not url:
        return ["url is empty"]
    parsed = urlparse(url)
    errors = []
    if parsed.scheme != "https":
        errors.append("url is not https")
    if not parsed.path.startswith("/api/"):
        errors.append("url is not an /api/ listing endpoint")
    host = (parsed.hostname or "").lower()
    if host not in TLD_COUNTRY_MAP:
        errors.append(f"host '{host}' is not a known Ounass host")
        return errors
    if row.get("country") and TLD_COUNTRY_MAP[host] != row["country"]:
        errors.append(f"host '{host}' serves country '{TLD_COUNTRY_MAP[host]}', row says '{row['country']}'")
    host_language = TLD_LANGUAGE_MAP.get(host, "").lower()
    if row.get("language") and host_language != row["language"]:
        errors.append(f"host '{host}' serves language '{host_language}', row says '{row['language']}'")
    return errors


def _page_kind_errors(row):
    """
    G1 page-kind guard (2026-10-20). A listing returns whatever its URL
    contains, whatever the row says; only a category page with no brand
    shows exactly the products the row claims. Ounass no longer serves
    brand + category listings, and brand pages (/designers/) mix every
    category, so on any other combination most of the page would look "new"
    (a daily Phase 2 product-page flood) or mismatched (G11). Brand-page
    support would need entry-level filtering by breadcrumbs + brand
    (ticket, "Brand pages"); until then such rows are rejected.
    """
    errors = []
    if row.get("brand"):
        errors.append("brand must be blank: category listings show every brand "
                      "(brand-scoped rows are not supported yet)")
    if "/designers/" in (urlparse(row.get("url") or "").path or ""):
        errors.append("url is a brand (/designers/) page, which mixes every category; "
                      "use a category listing")
    return errors


def _check_plp_rows(rows, vocab, config, result):
    seen_urls = set()
    for number, raw in enumerate(rows, start=1):
        row = normalize_row(raw)
        problems = [Problem("G1", SKIP, e, "plp_list", number)
                    for e in _canonical_errors(row, vocab, config.site)]
        problems += [Problem("G1", SKIP, e, "plp_list", number) for e in _page_kind_errors(row)]
        problems += [Problem("G7", SKIP, e, "plp_list", number) for e in _host_errors(row)]
        if row.get("url") in seen_urls:
            problems.append(Problem("G1", SKIP, "duplicate url", "plp_list", number))
        seen_urls.add(row.get("url"))
        result.problems.extend(problems)
        (result.skipped_plp_rows if problems else result.valid_plp_rows).append(row)

    total = len(rows)
    bad = len(result.skipped_plp_rows)
    if total and bad / total > config.max_bad_plp_rows_ratio:
        result.problems.append(Problem(
            "G1", STOP,
            f"{bad} of {total} listing rows are invalid ({bad / total:.0%} > "
            f"{config.max_bad_plp_rows_ratio:.0%}): likely a broken registry or vocabulary",
            "plp_list"))
    elif not result.valid_plp_rows:
        result.problems.append(Problem("G1", STOP, "no valid listing rows to sweep", "plp_list"))


def _check_pdp_rows(rows, vocab, config, result):
    if not rows:
        result.problems.append(Problem(
            "G10", WARN,
            "pdp_list is empty: every product seen on a listing will be treated as new",
            "pdp_list"))
        return
    seen = set()
    for number, raw in enumerate(rows, start=1):
        row = normalize_row(raw)
        errors = _canonical_errors(row, vocab, config.site)
        for key in ("portal_itemid", "url", "brand"):
            if row.get(key) is None:
                errors.append(f"{key} is empty")
        identity = (row.get("site"), row.get("country"), row.get("language"), row.get("portal_itemid"))
        if identity in seen:
            errors.append("duplicate product for this site/country/language")
        seen.add(identity)
        if errors:
            result.problems.extend(Problem("G10", QUARANTINE, e, "pdp_list", number) for e in errors)
            result.quarantined_pdp_rows.append(row)
        else:
            result.valid_pdp_rows.append(row)

    total = len(rows)
    bad = len(result.quarantined_pdp_rows)
    if bad / total > config.max_bad_pdp_rows_ratio:
        result.problems.append(Problem(
            "G10", STOP,
            f"{bad} of {total} product rows are invalid ({bad / total:.0%} > "
            f"{config.max_bad_pdp_rows_ratio:.0%}): gold or the vocabulary is likely broken",
            "pdp_list"))


def _check_gold_age(manifest, config, now, result):
    """G8: how long ago gold was rebuilt (the export file itself is always fresh)."""
    if manifest is None:
        result.problems.append(Problem(
            "G8", WARN, "gold age unknown: no export manifest (local input files)", "manifest"))
        return
    built_raw = manifest.get("gold_built_at")
    try:
        built = datetime.fromisoformat(str(built_raw))
        if built.tzinfo is None:
            built = built.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        result.problems.append(Problem(
            "G8", STOP, f"gold_built_at missing or unreadable ({built_raw!r})", "manifest"))
        return
    age = (now - built).total_seconds() / 86400
    result.gold_age_days = age
    if age >= config.gold_max_age_days:
        result.problems.append(Problem(
            "G8", STOP,
            f"gold last rebuilt {age:.1f} days ago (>= {config.gold_max_age_days:g}): dbt is likely stuck",
            "manifest"))
    elif age >= config.gold_warn_age_days:
        result.problems.append(Problem(
            "G8", WARN, f"gold last rebuilt {age:.1f} days ago", "manifest"))


def _check_coverage(config, result):
    """Which valid products a valid listing covers, only a skipped one covers, or none covers."""
    valid_index = _build_scope_index(result.valid_plp_rows)
    skipped_index = _build_scope_index(result.skipped_plp_rows)
    for pdp in result.valid_pdp_rows:
        if _covered(valid_index, pdp):
            continue
        if _covered(skipped_index, pdp):
            result.held_back_pdp_rows.append(pdp)
        else:
            result.uncovered_pdp_rows.append(pdp)
    if len(result.uncovered_pdp_rows) > config.max_phase2_pdps:
        result.problems.append(Problem(
            "COVERAGE", WARN,
            f"{len(result.uncovered_pdp_rows)} products are covered by no listing, above the "
            f"Phase 2 ceiling of {config.max_phase2_pdps}: Phase 2 would be skipped "
            "(check the PDP list's scope)",
            "pdp_list"))


def _check_stale_crawls(config, today, result):
    """Warn (never stop) about products not crawled recently; gold rebuilds don't refresh this date."""
    cutoff_days = config.stale_crawl_days
    stale, unknown = [], 0
    for pdp in result.valid_pdp_rows:
        crawled = _parse_date(pdp.get("last_crawl_date"))
        if crawled is None:
            unknown += 1
        elif (today - crawled).days > cutoff_days:
            stale.append((crawled, pdp))
    result.stale_pdp_rows = [pdp for _, pdp in sorted(stale, key=lambda item: item[0])]
    if stale:
        oldest = min(crawled for crawled, _ in stale)
        result.problems.append(Problem(
            "STALE", WARN,
            f"{len(stale)} products not crawled for more than {cutoff_days} days; "
            f"oldest last crawled {oldest.isoformat()}",
            "pdp_list"))
    if unknown:
        result.problems.append(Problem(
            "STALE", WARN, f"{unknown} products have no last_crawl_date", "pdp_list"))


def validate(inputs, config=None, now=None):
    """
    Run every startup check and return all problems plus the per-row decision.
    Never raises on bad data: problems are reported so preflight can list them all.
    """
    config = config or Config()
    now = now or datetime.now(timezone.utc)
    result = ValidationResult()

    result.problems.extend(_check_files(inputs))
    if result.stop:
        # Without complete inputs, the remaining checks have nothing reliable to look at.
        return result

    vocab = _vocabulary_sets(inputs.vocabulary)
    _check_plp_rows(inputs.plp_rows, vocab, config, result)
    _check_pdp_rows(inputs.pdp_rows, vocab, config, result)
    _check_gold_age(inputs.manifest, config, now, result)
    _check_coverage(config, result)
    _check_stale_crawls(config, now.date(), result)
    return result


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def format_report(inputs, result, max_rows_per_check=20):
    """Human-readable report: problems grouped by check, then a summary."""
    lines = []
    status = "WOULD STOP" if result.stop else "OK: the crawl would start"
    lines.append(f"PLP-efficient startup checks: {status}")
    if inputs.manifest:
        lines.append(f"  export: {inputs.manifest.get('export_id')} ({inputs.manifest.get('app_env')})")
    lines.append("")

    by_check = {}
    for problem in result.problems:
        by_check.setdefault((problem.check, problem.severity), []).append(problem)
    order = {STOP: 0, QUARANTINE: 1, SKIP: 2, WARN: 3}
    for (check, severity), problems in sorted(by_check.items(), key=lambda kv: (order[kv[0][1]], kv[0][0])):
        lines.append(f"[{severity.upper()}] {check}: {len(problems)}")
        for p in problems[:max_rows_per_check]:
            where = f"{p.source} row {p.row}: " if p.row else (f"{p.source}: " if p.source else "")
            lines.append(f"    - {where}{p.message}")
        if len(problems) > max_rows_per_check:
            lines.append(f"    ... and {len(problems) - max_rows_per_check} more")
    if not result.problems:
        lines.append("No problems found.")

    lines.append("")
    lines.append("Summary")
    plp_total = len(inputs.plp_rows or [])
    pdp_total = len(inputs.pdp_rows or [])
    lines.append(f"  listings: {len(result.valid_plp_rows)} valid, "
                 f"{len(result.skipped_plp_rows)} skipped (of {plp_total})")
    lines.append(f"  products: {len(result.valid_pdp_rows)} valid, "
                 f"{len(result.quarantined_pdp_rows)} quarantined (of {pdp_total})")
    per_locale = {}
    for pdp in result.valid_pdp_rows:
        per_locale[(pdp.get("country"), pdp.get("language"))] = \
            per_locale.get((pdp.get("country"), pdp.get("language")), 0) + 1
    for (country, language), count in sorted(per_locale.items()):
        lines.append(f"    {country}/{language}: {count}")
    lines.append(f"  held back (only a skipped listing covers them): {len(result.held_back_pdp_rows)}")
    lines.append(f"  covered by no listing (go straight to Phase 2): {len(result.uncovered_pdp_rows)}")
    lines.append(f"  stale (not crawled recently): {len(result.stale_pdp_rows)}")
    if result.gold_age_days is not None:
        lines.append(f"  gold last rebuilt: {result.gold_age_days:.1f} days ago")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Run state (Part 3): Phase 1 decisions per listing entry, Phase 2 selection
# ---------------------------------------------------------------------------

def _clean_label(value):
    # Same whitespace normalization as ounass_rules.get_primary_label.
    if not isinstance(value, str):
        return None
    label = " ".join(value.split()).strip()
    return label or None


def _as_number(value):
    return int(value) if float(value).is_integer() else float(value)


def plp_hit_selling_price(hit):
    """
    Selling price as the PDP path records it: priceByCustomerGroupId["-1"]
    (Part 0 parity: 42/42). The entry's plain `price` key is the pre-sale
    price on sale items, so it must not be used as the price.
    """
    value = (hit.get("priceByCustomerGroupId") or {}).get("-1")
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def plp_hit_discount(hit):
    """
    Discount % as the PDP path records it: computed from the entry's two prices,
    rounded half up (Part 0 parity: 42/42). None when there is no discount, as
    on the PDP path. Not discountPercentBySaleId, which was 5 points high on
    some sale items, and not discountText, which is translated display text.
    """
    sell = plp_hit_selling_price(hit)
    try:
        before = float(hit["price"]) if hit.get("price") is not None else None
    except (TypeError, ValueError):
        before = None
    if not sell or not before or sell >= before:
        return None
    percent = (Decimal(1) - Decimal(str(sell)) / Decimal(str(before))) * 100
    return int(percent.quantize(Decimal(1), rounding=ROUND_HALF_UP)) or None


def plp_hit_primary_label(hit):
    """
    Highest-priority badge, shaped like the PDP's primary_label ([label] or
    None). Promotion-campaign labels (e.g. EXTRA25) only exist on the PDP:
    accepted loss.
    """
    badges = [b for b in (hit.get("badges") or [])
              if isinstance(b, dict) and _clean_label(b.get("value"))]
    if not badges:
        return None
    top = max(badges, key=lambda b: b.get("priority") or 0)
    return [_clean_label(top["value"])]


class PlpEfficientRun:
    """
    Bookkeeping for one PLP-efficient crawl. Pure Python (no Scrapy): the
    spider reports listing pages and entries to it, and asks it what to
    PDP-crawl in Phase 2. Every decision is counted so it can go in the run
    manifest (Part 4).

    Products are identified by (country, language, portal_itemid): country and
    language come from the listing row, portal_itemid is the entry's
    visibleSku. Nothing is parsed from URLs.
    """

    def __init__(self, result, config, run_id, crawl_date, site="ounass"):
        self.config = config
        self.run_id = run_id
        self.crawl_date = crawl_date
        self.site = site
        self.plps = list(result.valid_plp_rows)
        self.pdps = {self.pdp_key(p): p for p in result.valid_pdp_rows}
        self.quarantined = {self.pdp_key(p) for p in result.quarantined_pdp_rows}
        self.startup_held_back = {self.pdp_key(p) for p in result.held_back_pdp_rows}
        # Which valid listings cover each known product (scope match, brand
        # wildcard). Products covered by none go straight to Phase 2.
        index = {}
        for idx, plp in enumerate(self.plps):
            index.setdefault(scope_key(plp), []).append((idx, plp.get("brand")))
        self.covering = {}
        for key, pdp in self.pdps.items():
            self.covering[key] = [idx for idx, brand in index.get(scope_key(pdp), [])
                                  if brand is None or brand == pdp.get("brand")]
        self.crawled = set()
        self.new_urls = {}   # url -> index of the listing it was found on
        self.stats = [
            {"url": plp["url"], "pages_requested": 0, "pages_parsed": 0, "pages_failed": 0,
             "pages_failed_access": 0,
             "emitted": 0, "matched": 0, "mismatched": 0, "unusable": 0, "new": 0,
             "stopped": None}
            for plp in self.plps
        ]
        self.phase2 = None

    @staticmethod
    def pdp_key(row):
        return (row.get("country"), row.get("language"), row.get("portal_itemid"))

    # --- Phase 1 -------------------------------------------------------------

    def page_requested(self, idx):
        self.stats[idx]["pages_requested"] += 1

    def page_parsed(self, idx):
        self.stats[idx]["pages_parsed"] += 1

    def page_failed(self, idx, access=False):
        """A listing page lost for good. `access`: blocked/refused, not a content problem."""
        self.stats[idx]["pages_failed"] += 1
        if access:
            self.stats[idx]["pages_failed_access"] += 1

    def failed_on_access_only(self, idx):
        stats = self.stats[idx]
        return bool(stats["pages_failed"]) and stats["pages_failed_access"] == stats["pages_failed"]

    def stop_plp(self, idx, reason):
        if not self.stats[idx]["stopped"]:
            self.stats[idx]["stopped"] = reason

    def is_stopped(self, idx):
        return bool(self.stats[idx]["stopped"])

    def check_currency(self, idx, hit):
        """G7 during the sweep: the entry's price currency must be the listing country's."""
        country = self.plps[idx]["country"]
        expected = COUNTRY_CURRENCY.get(country)
        got = hit.get("localeCurrency")
        if expected and got and got != expected:
            self.stop_plp(idx, f"G7: {got} prices on a '{country}' listing (expected {expected})")
            return False
        return True

    def handle_hit(self, idx, hit, plp_url):
        """
        Decide what to do with one listing entry. Returns one of:
          ("emit", row)       known product, fields match: PLP-extract row, no PDP request
          ("new", url)        not in the PDP list: PDP-crawl it in Phase 2
          ("mismatch", None)  known ID, fields differ (G11 drift count): Phase 2 decides
          ("skip", reason)    quarantined, already refreshed by an overlapping listing, ...
        """
        plp = self.plps[idx]
        stats = self.stats[idx]
        sku = _clean(hit.get("visibleSku"))
        if not sku:
            return ("skip", "entry without visibleSku")
        key = (plp["country"], plp["language"], sku)
        if key in self.quarantined:
            return ("skip", "quarantined product")
        pdp = self.pdps.get(key)
        if pdp is None:
            slug = _clean(hit.get("slug"))
            if not slug:
                return ("skip", "new product without slug")
            parsed = urlparse(plp_url)
            url = f"{parsed.scheme}://{parsed.netloc}/{slug}.html"
            if url not in self.new_urls:
                self.new_urls[url] = idx
                stats["new"] += 1
            return ("new", url)
        if key in self.crawled:
            return ("skip", "already refreshed by an overlapping listing")
        if not plp_covers_pdp(plp, pdp):
            stats["mismatched"] += 1
            return ("mismatch", None)
        stats["matched"] += 1
        row = self._extract_row(hit, plp, pdp, plp_url)
        if row is None:
            # No usable price: leave it for a Phase 2 PDP visit.
            stats["unusable"] += 1
            return ("skip", "entry has no selling price")
        self.crawled.add(key)
        stats["emitted"] += 1
        return ("emit", row)

    def _extract_row(self, hit, plp, pdp, plp_url):
        price = plp_hit_selling_price(hit)
        if price is None or price <= 0:
            return None
        url = pdp["url"]
        # G6 URL rule: the row's url is the product's own PDP URL from gold,
        # never the listing URL. Downstream keeps the latest non-blank url as
        # the website link and the recrawl address.
        parsed = urlparse(url)
        if parsed.path.startswith("/api/") or url == plp_url:
            return None
        return {
            "run_id": self.run_id,
            "site": self.site,
            "crawl_date": self.crawl_date,
            "url": url,
            # Same derivation as the PDP path (ounass_rules.get_language).
            "language": TLD_LANGUAGE_MAP.get(parsed.netloc),
            "country": plp["country"],
            "portal_itemid": pdp["portal_itemid"],
            "price": _as_number(price),
            "price_discount": plp_hit_discount(hit),
            "primary_label": plp_hit_primary_label(hit),
            "plp_extract_flag": 1,
            # Analysis only; no downstream model may treat it as the product's address.
            "plp_source_url": plp_url,
        }

    # --- Phase 2 -------------------------------------------------------------

    def listing_health(self):
        """
        Per listing: None if healthy, else why its leftovers are held back.
        G3 (a page failed / nothing parsed), G7 (currency, set during the sweep),
        G11 (field-mismatch drift), G4 (too many expected products unseen).
        """
        cfg = self.config
        health = {}
        for idx, stats in enumerate(self.stats):
            seen = stats["matched"] + stats["mismatched"]
            if stats["stopped"]:
                health[idx] = stats["stopped"]
            elif stats["pages_failed"]:
                cause = "blocked by the site (access)" if self.failed_on_access_only(idx) else "failed"
                health[idx] = f"G3: {stats['pages_failed']} listing page(s) {cause}"
            elif stats["pages_parsed"] == 0:
                health[idx] = "G3: no listing page was parsed"
            elif stats["pages_parsed"] < stats["pages_requested"]:
                # Requested but neither parsed nor reported failed: lost silently.
                missing = stats["pages_requested"] - stats["pages_parsed"]
                health[idx] = f"G3: {missing} listing page(s) never came back"
            elif seen and stats["mismatched"] / seen > cfg.field_mismatch_ratio:
                health[idx] = (f"G11: {stats['mismatched']} of {seen} matched products disagree "
                               f"with the listing's fields (> {cfg.field_mismatch_ratio:.0%})")
            else:
                health[idx] = None
        # G4 on listings still healthy: unseen share of expected products,
        # not counting ones gold already has as sold out (Ounass drops a sold-out
        # colour's own entry, so those are expected to be missing).
        expected = {idx: [] for idx in range(len(self.plps))}
        for key, idxs in self.covering.items():
            if key in self.quarantined:
                continue
            for idx in idxs:
                expected[idx].append(key)
        for idx, keys in expected.items():
            if health[idx] is not None:
                continue
            counted = [k for k in keys if str(self.pdps[k].get("out_of_stock")).lower() != "true"]
            unseen = [k for k in counted if k not in self.crawled]
            if counted and len(unseen) / len(counted) > cfg.missing_ratio_cap:
                health[idx] = (f"G4: {len(unseen)} of {len(counted)} expected products not seen "
                               f"(> {cfg.missing_ratio_cap:.0%})")
        return health

    def select_phase2(self):
        """
        What to PDP-crawl now that every listing has been swept. Products whose
        only covering listings are unhealthy are held back (not crawled this
        run), so a broken listing can't trigger a burst of PDP requests.
        """
        health = self.listing_health()
        healthy = {idx for idx, reason in health.items() if reason is None}
        urls, held_back = [], set(self.startup_held_back)
        counts = {"known_unseen": 0, "uncovered": 0, "new": 0, "held_back": 0,
                  "held_back_new": 0}
        for key, pdp in self.pdps.items():
            if key in self.crawled or key in self.startup_held_back:
                continue
            covering = self.covering.get(key) or []
            if not covering:
                urls.append(pdp["url"])
                counts["uncovered"] += 1
            elif any(idx in healthy for idx in covering):
                urls.append(pdp["url"])
                counts["known_unseen"] += 1
            else:
                held_back.add(key)
        for url, idx in self.new_urls.items():
            if idx in healthy:
                urls.append(url)
                counts["new"] += 1
            else:
                counts["held_back_new"] += 1
        urls = list(dict.fromkeys(urls))
        counts["held_back"] = len(held_back)
        exceeded = len(urls) > self.config.max_phase2_pdps
        self.phase2 = {
            "urls": [] if exceeded else urls,
            "candidates": len(urls),
            "phase2_ceiling_exceeded": exceeded,
            "counts": counts,
            "listing_health": {self.plps[idx]["url"]: reason for idx, reason in health.items()},
        }
        return self.phase2

    def summary(self):
        """Counts for logs now and the run manifest's plp_efficient block (Part 4)."""
        return {
            "listings": len(self.plps),
            "known_products": len(self.pdps),
            "quarantined": len(self.quarantined),
            "refreshed_from_listing": len(self.crawled),
            "new_products": len(self.new_urls),
            "per_listing": self.stats,
            "phase2": self.phase2,
        }


# ---------------------------------------------------------------------------
# Run manifest block (Part 4)
# ---------------------------------------------------------------------------

MANIFEST_MAX_MESSAGES = 50
ACCESS = "access"     # same kinds as ecommercecrawl/access.py
CONTENT = "content"


def _degradation(kind, scope, message):
    """One manifest `degradations` entry: kind access (site refused us) or content."""
    return {"kind": kind, "scope": scope, "message": message}


def manifest_block(inputs=None, result=None, run=None, startup_error=None, mode="live"):
    """
    The run manifest's `plp_efficient` block: what the run was given, what the
    startup checks decided, what each listing did and what Phase 2 got.

    `degradations` lists (as {kind, scope, message}) every piece of work skipped in a run
    that otherwise completed (a skipped or held-back listing, quarantined or
    held-back products, Phase 2 skipped by the ceiling). `startup_stopped`
    means the run made no request at all. Both feed the run status (Part 4b).
    """
    block = {
        "mode": mode,
        "startup_stopped": bool(startup_error) or bool(result is not None and result.stop),
        "startup_error": str(startup_error) if startup_error else None,
        "inputs": None,
        "startup": None,
        "listings": None,
        "phase2": None,
        "refreshed_from_listing": None,
        "new_products": None,
        "degradations": [],
    }
    degradations = block["degradations"]

    if inputs is not None:
        export = inputs.manifest or {}
        block["inputs"] = {
            "sources": dict(inputs.sources),
            "export_id": export.get("export_id"),
            "app_env": export.get("app_env"),
            "gold_built_at": export.get("gold_built_at"),
            "plp_rows": len(inputs.plp_rows) if inputs.plp_rows is not None else None,
            "pdp_rows": len(inputs.pdp_rows) if inputs.pdp_rows is not None else None,
        }

    if result is not None:
        by_check = {}
        for problem in result.problems:
            by_check.setdefault(problem.check, {}).setdefault(problem.severity, 0)
            by_check[problem.check][problem.severity] += 1
        block["startup"] = {
            "gold_age_days": result.gold_age_days,
            "listings_valid": len(result.valid_plp_rows),
            "listings_skipped": [row.get("url") for row in result.skipped_plp_rows],
            "products_valid": len(result.valid_pdp_rows),
            "products_quarantined": len(result.quarantined_pdp_rows),
            "products_held_back": len(result.held_back_pdp_rows),
            "products_uncovered": len(result.uncovered_pdp_rows),
            "products_stale": len(result.stale_pdp_rows),
            "problems_by_check": by_check,
            "stop_messages": [p.message for p in result.by_severity(STOP)][:MANIFEST_MAX_MESSAGES],
        }
        if result.skipped_plp_rows:
            degradations.append(_degradation(
                CONTENT, "startup", f"{len(result.skipped_plp_rows)} listing(s) skipped at startup"))
        if result.quarantined_pdp_rows:
            degradations.append(_degradation(
                CONTENT, "startup", f"{len(result.quarantined_pdp_rows)} product(s) quarantined"))
        if result.held_back_pdp_rows:
            degradations.append(_degradation(
                CONTENT, "startup",
                f"{len(result.held_back_pdp_rows)} product(s) held back (only skipped listings cover them)"))

    if run is not None:
        health = run.phase2["listing_health"] if run.phase2 else {}
        listings = []
        for idx, stats in enumerate(run.stats):
            reason = health.get(stats["url"]) if run.phase2 else stats["stopped"]
            listings.append({**stats, "held_back_reason": reason})
            if reason:
                # A listing lost only to blocking is an access problem, not a content one.
                kind = ACCESS if reason.startswith("G3") and run.failed_on_access_only(idx) else CONTENT
                degradations.append(_degradation(kind, stats["url"], f"listing held back: {reason}"))
        block["listings"] = listings
        block["refreshed_from_listing"] = len(run.crawled)
        block["new_products"] = len(run.new_urls)
        if run.phase2:
            block["phase2"] = {k: v for k, v in run.phase2.items() if k not in ("urls", "listing_health")}
            if run.phase2["phase2_ceiling_exceeded"]:
                degradations.append(_degradation(
                    CONTENT, "phase2",
                    f"Phase 2 skipped: {run.phase2['candidates']} product pages exceed the ceiling "
                    f"of {run.config.max_phase2_pdps}"))
    return block
