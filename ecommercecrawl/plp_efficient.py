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
from urllib.parse import urlparse

from ecommercecrawl.constants.ounass_constants import (
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


def _check_plp_rows(rows, vocab, config, result):
    seen_urls = set()
    for number, raw in enumerate(rows, start=1):
        row = normalize_row(raw)
        problems = [Problem("G1", SKIP, e, "plp_list", number)
                    for e in _canonical_errors(row, vocab, config.site)]
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
