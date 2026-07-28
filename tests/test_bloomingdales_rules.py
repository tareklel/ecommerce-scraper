import pytest
from scrapy.http import HtmlResponse, Request

from ecommercecrawl.rules import bloomingdales_rules as rules


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


def test_is_first_plp_page_true():
    assert rules.is_first_plp_page("https://bloomingdales.sa/womens-bags/") is True


def test_is_first_plp_page_false_for_update_grid():
    url = "https://bloomingdales.sa/on/demandware.store/Sites-BloomingDales_SA-Site/ar_SA/Search-UpdateGrid?cgid=foo&start=48"
    assert rules.is_first_plp_page(url) is False


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


# ── get_cgid ─────────────────────────────────────────────────────────────────

def test_get_cgid_extracts_from_data_url():
    html = '<button class="js-show-more-btn" data-url="/on/demandware.store?cgid=women-womens-bags-cross-body-bags&start=48&sz=48">'
    assert rules.get_cgid(html) == "women-womens-bags-cross-body-bags"


def test_get_cgid_returns_none_when_missing():
    assert rules.get_cgid("<div>no category here</div>") is None


# ── get_update_grid_url ───────────────────────────────────────────────────────

def test_get_update_grid_url_ar():
    url = rules.get_update_grid_url(
        "https://bloomingdales.sa/womens-bags/", "women-womens-bags", 48
    )
    assert "ar_SA" in url
    assert "cgid=women-womens-bags" in url
    assert "start=48" in url
    assert "bloomingdales.sa" in url


def test_get_update_grid_url_en():
    url = rules.get_update_grid_url(
        "https://en.bloomingdales.sa/womens-bags/", "women-womens-bags", 96
    )
    assert "en_SA" in url
    assert "start=96" in url
    assert "en.bloomingdales.sa" in url


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


# ── extract_product (integration — AR fixture) ────────────────────────────────

def test_extract_product_from_ar_fixture():
    with open("tests/fixtures/bloomingdales_pdp.html", encoding="utf-8") as f:
        html = f.read()
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
