"""Shared normalization for ordered product-image galleries."""

from collections.abc import Iterable
from urllib.parse import urlsplit, urlunsplit


def normalize_image_url(raw_url, *, allow_bare_host: bool = False) -> str | None:
    """Return one absolute HTTPS image URL, or ``None`` for invalid input.

    Query parameters and fragments are preserved because downstream download
    identity uses the complete normalized URL.
    """
    if not isinstance(raw_url, str):
        return None

    value = raw_url.strip()
    if not value:
        return None
    if value.startswith("//"):
        value = f"https:{value}"
    elif allow_bare_host and "://" not in value:
        bare_value = value.lstrip("/")
        bare_host = bare_value.split("/", 1)[0]
        if "." not in bare_host:
            return None
        value = f"https://{bare_value}"

    try:
        parsed = urlsplit(value)
    except ValueError:
        return None

    scheme = parsed.scheme.lower()
    try:
        hostname = parsed.hostname
        has_credentials = parsed.username is not None or parsed.password is not None
    except ValueError:
        return None

    if (
        scheme not in {"http", "https"}
        or not hostname
        or any(character.isspace() for character in parsed.netloc)
        or has_credentials
    ):
        return None

    # Both supported retailer CDNs serve HTTPS. Canonicalizing HTTP here also
    # prevents duplicate identities for the same image.
    return urlunsplit(("https", parsed.netloc, parsed.path, parsed.query, parsed.fragment))


def normalize_ordered_image_urls(
    raw_urls: Iterable,
    *,
    allow_bare_host: bool = False,
) -> list[str] | None:
    """Normalize and deduplicate one explicitly present source gallery.

    An empty iterable is a confirmed empty gallery. A nonempty iterable with
    no valid URL is an extraction failure and returns ``None``.
    """
    candidates = list(raw_urls)
    if not candidates:
        return []

    result: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        normalized = normalize_image_url(
            candidate,
            allow_bare_host=allow_bare_host,
        )
        if normalized is None or normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)

    return result or None
