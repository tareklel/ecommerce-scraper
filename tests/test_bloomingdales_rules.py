import os

import pytest
from scrapy.http import HtmlResponse, Request

from ecommercecrawl.rules import bloomingdales_rules as rules


def _read_local_fixture(path, **open_kwargs):
    """
    Read a saved real product page used as a fixture.

    These pages are gitignored on purpose (*.html; downloaded product data
    must not be committed, see context/AGENTS.md), so they exist only on
    machines that captured them. Elsewhere (e.g. CI) the test is skipped
    rather than failed, and the skip reason shows in the test report.
    """
    if not os.path.exists(path):
        pytest.skip(f"local-only fixture not present: {path} (gitignored real product page)")
    with open(path, **open_kwargs) as f:
        return f.read()


def make_response(html: str, url: str) -> HtmlResponse:
    return HtmlResponse(url=url, request=Request(url=url), body=html, encoding="utf-8")


# ── Language ────────────────────────────────────────────────────────────────

def test_get_language_en():
    assert rules.get_language("https://en.bloomingdales.sa/womens-bags/") == "EN"


def test_get_language_ar():
    assert rules.get_language("https://bloomingdales.sa/womens-bags/") == "AR"


def test_get_language_en_prefix_is_not_sa_specific():
    # Pattern is en. prefix, not tied to SA — future GCC domains work the same way
    assert rules.get_language("https://en.bloomingdales.kw/womens-bags/") == "EN"
    assert rules.get_language("https://bloomingdales.kw/womens-bags/") == "AR"


# ── URL classification ───────────────────────────────────────────────────────

@pytest.mark.parametrize("url", [
    "https://bloomingdales.sa/womens-bags/",
    "https://en.bloomingdales.sa/womens-bags-crossbody-bags/",
    "https://bloomingdales.sa/womens-shoes/",
])
def test_is_plp_true(url):
    assert rules.is_plp(url) is True


@pytest.mark.parametrize("url", [
    "https://bloomingdales.sa/marc-jacobs-scene-vanity-bag-BAG219542223xBLK.html",
    "https://bloomingdales.sa/on/demandware.store/Sites-BloomingDales_SA-Site/ar_SA/Search-UpdateGrid?cgid=foo&start=48",
    "https://bloomingdales.sa/",
])
def test_is_plp_false(url):
    assert rules.is_plp(url) is False


@pytest.mark.parametrize("url", [
    "https://bloomingdales.sa/marc-jacobs-scene-vanity-bag-BAG219542223xBLK.html",
    "https://en.bloomingdales.sa/khaite-kye-mini-crossbody-bag-BAG219032925xBLK.html",
    "https://bloomingdales.sa/some-shoe-219019583.html",
])
def test_is_pdp_true(url):
    assert rules.is_pdp(url) is True


@pytest.mark.parametrize("url", [
    "https://bloomingdales.sa/womens-bags/",
    "https://bloomingdales.sa/womens-bags/brands.html",  # no PID pattern
])
def test_is_pdp_false(url):
    assert rules.is_pdp(url) is False


# ── extract_pid ──────────────────────────────────────────────────────────────

def test_extract_pid_variant():
    url = "https://en.bloomingdales.sa/marc-jacobs-scene-vanity-bag-BAG219542223xBLK.html"
    assert rules.extract_pid(url) == "BAG219542223XBLK"


def test_extract_pid_numeric_falls_back_to_dom():
    url = "https://bloomingdales.sa/some-product-219019583.html"
    html = '<span class="js-product-id-vg">SHO219019583XBLK</span>'
    assert rules.extract_pid(url, html) == "SHO219019583XBLK"


def test_extract_pid_numeric_without_dom():
    url = "https://bloomingdales.sa/some-product-219019583.html"
    assert rules.extract_pid(url) == "219019583"


def test_extract_pid_returns_none_for_non_pdp():
    assert rules.extract_pid("https://bloomingdales.sa/womens-bags/") is None


# ── Listing product search (Commerce API) ─────────────────────────────────────

# The shape of the listing page's settings (2026-11-18), with made-up values.
COMMERCE_API_PAGE = (
    '..."commerceAPI":{"proxyPath":"\\u002Fmobify\\u002Fproxy\\u002Fapi","parameters":'
    '{"clientId":"client-1","organizationId":"f_ecom_test","shortCode":"abc","siteId":"BloomingDales_SA"}}...'
    '<meta href="https://x.demandware.net/dw/shop/v99_9/product_search?count=25&amp;start=0'
    '&amp;refine_1=cgid%3Dwomen-womens-bags-shoulder-bags&amp;c_source=web"/>'
    # Promo blocks elsewhere on the page carry other cgids; they must not win.
    '{\\"key\\": \\"cgid\\", \\"value\\": \\"bloomingdales-resort-women\\"}'
)


def test_get_commerce_api_reads_the_page_settings():
    assert rules.get_commerce_api(COMMERCE_API_PAGE) == {
        "client_id": "client-1", "organization_id": "f_ecom_test",
        "site_id": "BloomingDales_SA", "proxy_path": "/mobify/proxy/api",
    }


def test_get_commerce_api_none_without_settings():
    assert rules.get_commerce_api("<div>old page</div>") is None


def test_get_listing_cgid_takes_the_listing_search_not_promo_blocks():
    assert rules.get_listing_cgid(COMMERCE_API_PAGE) == "women-womens-bags-shoulder-bags"


def test_get_listing_cgid_none_when_missing():
    assert rules.get_listing_cgid("<div>no category here</div>") is None


@pytest.mark.parametrize("url, locale, currency", [
    ("https://en.bloomingdales.sa/womens-bags-shoulder-bags/", "en-SA", "SAR"),
    ("https://bloomingdales.sa/womens-bags-shoulder-bags/", "ar-SA", "SAR"),
])
def test_search_locale_and_currency(url, locale, currency):
    assert rules.get_search_locale(url) == locale
    assert rules.get_currency(url) == currency


def test_get_guest_code_reads_code_and_usid():
    assert rules.get_guest_code("https://en.bloomingdales.sa/callback?code=c1&usid=u1") == ("c1", "u1")
    assert rules.get_guest_code("") == (None, None)


def test_pkce_pair_challenge_is_the_verifier_hash():
    import base64, hashlib
    verifier, challenge = rules.pkce_pair()
    digest = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    assert challenge == digest and "=" not in verifier


@pytest.mark.parametrize("host", ["https://en.bloomingdales.sa", "https://bloomingdales.sa"])
def test_build_pdp_url_matches_the_sites_own_links(host):
    # Real pairs from the shoulder-bag listing, 2026-11-18 (both languages use the English slug).
    hit = {"productId": "BAG219546375xBrown", "c_brand_en": "Furla", "c_brand": "فورلا",
           "c_name_en": "Large Sfera Soft Shoulder Bag ", "productName": "حقيبة"}
    assert rules.build_pdp_url(f"{host}/womens-bags-shoulder-bags/", hit) == (
        f"{host}/furla-Large-Sfera-Soft-Shoulder-Bag-BAG219546375xBrown.html")
    hit = {"productId": "BAG219846812xRed", "c_brand_en": "STAUD", "c_name_en": "Ollie Bag"}
    assert rules.build_pdp_url(f"{host}/x/", hit) == f"{host}/staud-Ollie-Bag-BAG219846812xRed.html"


def test_build_pdp_url_none_without_an_id_or_name():
    assert rules.build_pdp_url("https://en.bloomingdales.sa/x/", {"c_brand_en": "Furla", "c_name_en": "Bag"}) is None
    assert rules.build_pdp_url("https://en.bloomingdales.sa/x/", {"productId": "BAG1x", "c_brand_en": "Furla"}) is None


def test_built_pdp_url_is_a_pdp_with_the_right_pid():
    url = rules.build_pdp_url("https://en.bloomingdales.sa/x/", {
        "productId": "BAG219546375xBrown", "c_brand_en": "Furla", "c_name_en": "Large Sfera Soft Shoulder Bag"})
    assert rules.is_pdp(url) and rules.extract_pid(url) == "BAG219546375XBROWN"


# ── get_pdp_urls ──────────────────────────────────────────────────────────────

def test_get_pdp_urls_extracts_variant_hrefs():
    html = """
    <a href="/marc-jacobs-scene-vanity-bag-BAG219542223xBLK.html">bag</a>
    <a href="/khaite-kye-mini-BAG219032925xBLK.html">bag2</a>
    <a href="/womens-bags/">not a pdp</a>
    """
    resp = make_response(html, "https://bloomingdales.sa/womens-bags/")
    urls = rules.get_pdp_urls(resp)
    assert len(urls) == 2
    assert all("bloomingdales.sa" in u and u.endswith(".html") for u in urls)


def test_get_pdp_urls_deduplicates():
    html = """
    <a href="/bag-BAG219542223xBLK.html">1</a>
    <a href="/bag-BAG219542223xBLK.html">2</a>
    """
    resp = make_response(html, "https://bloomingdales.sa/womens-bags/")
    assert len(rules.get_pdp_urls(resp)) == 1


# ── extract_color ─────────────────────────────────────────────────────────────

def test_extract_color_known_code():
    url = "https://bloomingdales.sa/bag-BAG219542223xBLK.html"
    assert rules.extract_color("", url) == "Black"


def test_extract_color_multi_word_code():
    url = "https://bloomingdales.sa/bag-BAG219542223xLight___PastelPink.html"
    result = rules.extract_color("", url)
    assert result is not None
    assert "Pink" in result or "pink" in result.lower()


def test_extract_color_no_x_in_pid():
    assert rules.extract_color("", "https://bloomingdales.sa/product-219019583.html") is None


# ── extract_price_discount ────────────────────────────────────────────────────

def test_extract_price_discount_finds_percentage():
    html = '<span class="blm-price__percentage">70% OFF</span>'
    assert rules.extract_price_discount(html) == "70% OFF"


def test_extract_price_discount_returns_none_when_missing():
    assert rules.extract_price_discount("<div>full price product</div>") is None


# ── extract_was_price ─────────────────────────────────────────────────────────

def test_extract_was_price_reads_standard_content():
    # SFCC renders content= as a child meta/attribute inside the element body
    html = '<span class="blm-price__standard"><meta content="1250.00"></span>'
    assert rules.extract_was_price(html) == 1250.0


def test_extract_was_price_returns_none_when_missing():
    assert rules.extract_was_price("<div>no sale</div>") is None


# ── extract_primary_label ─────────────────────────────────────────────────────

def test_extract_primary_label_anchored_to_badges_container():
    # carousel badge must be > 600 chars from the badges container start
    # to be outside the extraction window
    padding = " " * 650
    html = (
        '<div class="blm-pdpmain__badges">'
        '<span class="blm-badge">NEW SEASON</span>'
        "</div>"
        + padding
        + '<div class="carousel"><span class="blm-badge">OTHER PRODUCT LABEL</span></div>'
    )
    result = rules.extract_primary_label(html)
    assert result == ["NEW SEASON"]


def test_extract_primary_label_returns_none_when_no_badges():
    assert rules.extract_primary_label("<div>no badges</div>") is None


# ── Breadcrumbs ─────────────────────────────────────────────────────────────

JSONLD_BREADCRUMBS = """
<script type="application/ld+json">{"@context":"https://schema.org","@type":"BreadcrumbList","itemListElement":[
{"@type":"ListItem","position":2,"item":{"@id":"https://en.bloomingdales.sa/women/","name":"Women"}},
{"@type":"ListItem","position":1,"item":{"@id":"https://en.bloomingdales.sa/marc-jacobs/","name":"Marc Jacobs"}},
{"@type":"ListItem","position":3,"item":{"@id":"https://en.bloomingdales.sa/bags/","name":"Women&#39;s Bags"}},
{"@type":"ListItem","position":4,"item":{"@id":"https://en.bloomingdales.sa/shoulder/","name":"Shoulder Bags"}},
{"@type":"ListItem","position":5,"item":{"@id":"https://en.bloomingdales.sa/x.html","name":"Scene Small Shoulder Bag"}}
]}</script>
"""

MICRODATA_BREADCRUMBS = """
<ol itemscope itemtype="http://schema.org/BreadcrumbList">
<li><span itemprop="name">Marc Jacobs</span></li><li><span itemprop="name">Women</span></li>
<li><span itemprop="name">Bags</span></li><li><span itemprop="name">Totes</span></li>
</ol>
"""

JSONLD_PRODUCT = """
<script type="application/ld+json">{"@context":"https://schema.org","@type":"Product","name":"Scene Small Shoulder Bag",
"brand":{"@type":"Brand","name":"Marc Jacobs"},"image":["https://img.example/a.jpg"],
"offers":{"@type":"Offer","price":"2500","priceCurrency":"SAR","availability":"https://schema.org/InStock"}}</script>
"""


def test_breadcrumbs_read_from_jsonld_in_position_order():
    assert rules._extract_breadcrumbs(JSONLD_BREADCRUMBS) == [
        "Marc Jacobs", "Women", "Women's Bags", "Shoulder Bags", "Scene Small Shoulder Bag",
    ]


def test_breadcrumbs_fall_back_to_microdata():
    assert rules._extract_breadcrumbs(MICRODATA_BREADCRUMBS) == ["Marc Jacobs", "Women", "Bags", "Totes"]


def test_breadcrumbs_empty_when_neither_is_present():
    assert rules._extract_breadcrumbs("<div>nothing</div>") == []


def test_extract_product_takes_gender_and_category_from_jsonld_breadcrumbs():
    url = "https://en.bloomingdales.sa/marc-jacobs-Scene-Small-Shoulder-Bag-BAG219542221xBLK.html"
    p = rules.extract_product(make_response(JSONLD_PRODUCT + JSONLD_BREADCRUMBS, url))
    assert (p["gender"], p["category"], p["subcategory"]) == ("Women", "Women's Bags", "Shoulder Bags")


# ── extract_product (integration — AR fixture) ────────────────────────────────

def test_extract_product_from_ar_fixture():
    html = _read_local_fixture("tests/fixtures/bloomingdales_pdp.html", encoding="utf-8")
    url = "https://bloomingdales.sa/marc-jacobs-BAG219542223xBLK.html"
    resp = make_response(html, url)
    p = rules.extract_product(resp)

    assert p["portal_itemid"] == "BAG219542223XBLK"
    assert p["brand"] == "Marc Jacobs"
    assert p["currency"] == "SAR"
    assert isinstance(p["price"], float) and p["price"] > 0
    assert isinstance(p["image_urls"], list) and len(p["image_urls"]) >= 1
    assert all(u.startswith("https://") for u in p["image_urls"])
    # text struct: all-null normalisation must return None or a valid struct
    text = p.get("text")
    assert text is None or (
        isinstance(text, dict)
        and any(v is not None for v in text.values())
    )
