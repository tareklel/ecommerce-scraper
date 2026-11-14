import pytest

from ecommercecrawl.constants import cettire_constants as constants
from ecommercecrawl.constants.product_schema import REQUIRED_FIELDS
from ecommercecrawl.rules import cettire_rules as rules
from tests.cettire_fixtures import CDN, pdp_html, search_hit, search_payload

LISTING = "https://www.cettire.com/sa/collections/womens-bags/shoulder-bags"
PRODUCT = "https://www.cettire.com/sa/products/acme-flap-shoulder-bag-900000001"


# ---- URLs

def test_url_kinds_and_country():
    assert rules.is_plp(LISTING) and not rules.is_pdp(LISTING)
    assert rules.is_pdp(PRODUCT) and not rules.is_plp(PRODUCT)
    assert not rules.is_plp("https://example.com/sa/collections/womens-bags")
    assert rules.get_country(PRODUCT) == "SA"


def test_listing_query_reads_department_category_and_subcategory():
    assert rules.listing_query(LISTING) == {
        "department": "women", "catQuery": "bags", "subCatQuery": "shoulder bags",
    }
    assert rules.listing_query("https://www.cettire.com/sa/collections/mens-bags")["subCatQuery"] == ""


@pytest.mark.parametrize("url", [PRODUCT, "https://www.cettire.com/sa/collections/sale"])
def test_listing_query_rejects_urls_it_cannot_read(url):
    with pytest.raises(ValueError):
        rules.listing_query(url)


def test_portal_itemid_is_the_numeric_slug_suffix():
    assert rules.portal_itemid_from_handle("acme-flap-shoulder-bag-900000001") == "900000001"
    assert rules.portal_itemid_from_handle("no-number-here") is None
    assert rules.portal_itemid_from_handle(None) is None


# ---- search request

def test_search_body_carries_saudi_filters_and_brands():
    body = rules.build_search_body(rules.listing_query(LISTING), vendors=["Acme"], page_size=1000,
                                   request_id="abc", device_info={"sessionId": "s"})
    assert (body["countryCode"], body["regionCode"], body["currencyCode"]) == ("SA", "sa", "SAR")
    # Arabic mode is what makes the service return title_ar next to title.
    assert body["langCode"] == "ar"
    info = body["productQueryInfo"]
    assert info["department"] == "women" and info["catQuery"] == "bags"
    assert info["subCatQuery"] == "shoulder bags"
    assert info["vendorQuery"] == ["Acme"] and info["pageSize"] == 1000
    assert body["requestId"] == "abc" and body["deviceInfo"] == {"sessionId": "s"}


def test_allowlist_matches_brands_ignoring_accents_and_case():
    counts = {"Chloé": 10, "Saint Laurent": 5, "Coccinelle": 300}
    assert rules.allowed_vendor_counts(counts, ["CHLOE", "saint laurent"]) == {"Chloé": 10, "Saint Laurent": 5}


def test_empty_allowlist_keeps_every_brand():
    counts = {"A": 1, "B": 2}
    assert rules.allowed_vendor_counts(counts, []) == counts


def test_brand_groups_stay_under_the_cap():
    counts = {"A": 600, "B": 500, "C": 300, "D": 100}
    groups = rules.pack_brand_groups(counts, max_products=950)
    assert sorted(name for group in groups for name in group) == ["A", "B", "C", "D"]
    assert all(sum(counts[n] for n in group) <= 950 for group in groups)


def test_a_brand_over_the_cap_gets_its_own_group():
    groups = rules.pack_brand_groups({"Huge": 1500, "Small": 10}, max_products=950)
    assert groups == [["Huge"], ["Small"]]


def test_get_hits_and_vendor_counts_tolerate_missing_parts():
    assert rules.get_hits(None) == [] and rules.get_hits({"products": [{"x": 1}]}) == []
    assert rules.vendor_counts({}) == {} and rules.vendor_counts({"facets": {"vendor": None}}) == {}
    assert len(rules.get_hits(search_payload())) == 1


# ---- search hit -> rows

def test_hit_becomes_an_english_and_an_arabic_row():
    english, arabic = rules.rows_from_hit(search_hit(), "2026-11-14T00-00-00-000", "2026-11-14")
    assert (english["language"], arabic["language"]) == ("EN", "AR")
    assert english["product_name"] == "Acme Flap Shoulder Bag"
    assert arabic["product_name"] == "حقيبة كتف أكمي"
    assert (english["category"], english["subcategory"]) == ("Bags", "Shoulder Bags")
    assert (arabic["category"], arabic["subcategory"]) == ("حقائب", "حقائب الكتف")
    for row in (english, arabic):
        assert row["site"] == "cettire" and row["country"] == "SA"
        assert row["url"] == PRODUCT and row["portal_itemid"] == "900000001"
        assert row["brand"] == "Acme" and row["gender"] == "women"
        assert (row["price"], row["was_price"], row["currency"]) == (3000.0, 4000.0, "SAR")
        assert row["price_discount"] == 25
        assert row["sizes"] == ["Only One Size"] and row["out_of_stock"] is False
        assert row["image_urls"] == [f"{CDN}/list.jpg", f"{CDN}/set2.jpg", f"{CDN}/media.jpg", f"{CDN}/set3.jpg"]
        assert row["designer_model_number"] == "MODEL123"


def test_rows_cover_every_required_schema_field():
    for row in rules.rows_from_hit(search_hit(), "run", "2026-11-14"):
        assert REQUIRED_FIELDS <= set(row)
        assert all(row[field] is not None for field in REQUIRED_FIELDS)


@pytest.mark.parametrize("compare", [None, "", 3000, 2500])
def test_full_price_is_discount_zero_not_blank(compare):
    row = rules.rows_from_hit(search_hit(price=3000, compare=compare), "run", "d")[0]
    assert row["was_price"] is None
    # 0, not None: a real 0 is what clears an ended sale downstream.
    assert row["price_discount"] == 0


def test_missing_price_leaves_discount_unknown():
    row = rules.rows_from_hit(search_hit(price=None), "run", "d")[0]
    assert row["price"] is None and row["price_discount"] is None


def test_zero_stock_is_out_of_stock_and_unknown_stock_is_not():
    assert rules.rows_from_hit(search_hit(quantity=0), "run", "d")[0]["out_of_stock"] is True
    assert rules.rows_from_hit(search_hit(quantity=None), "run", "d")[0]["out_of_stock"] is False


def test_images_skip_blanks_and_duplicates():
    hit = search_hit(image_set2_url="", media_medium=f"{CDN}/list.jpg")
    assert rules.hit_image_urls(hit) == [f"{CDN}/list.jpg", f"{CDN}/set3.jpg"]
    assert rules.hit_image_urls({}) is None


def test_hit_without_an_id_gives_no_rows():
    assert rules.rows_from_hit(search_hit(handle="no-id"), "run", "d") == []


# ---- product page

def test_product_page_fields():
    product = rules.extract_product(pdp_html())
    assert product["portal_itemid"] == "900000001"
    assert product["product_name"] == "Acme Flap Shoulder Bag" and product["brand"] == "Acme"
    assert product["gender"] == "women" and product["subcategory"] == "Shoulder Bags"
    # The Saudi price entry, not the first (USD) one.
    assert (product["price"], product["was_price"], product["currency"]) == (3000.0, 4000.0, "SAR")
    assert product["price_discount"] == 25
    assert product["out_of_stock"] is False and product["sizes"] == ["Only One Size"]
    # Largest size of each gallery image, in gallery order.
    assert product["image_urls"] == [f"{CDN}/g{i}-original.jpg" for i in range(3)]
    assert product["text"] == {
        "description": None,
        "details": ["Flap closure", "Gold-tone hardware", "100% Calf Leather", "Made in Italy"],
        "size_fit": ["Width: 20cm, Height: 12cm", "Strap: 50cm"],
    }


def test_sold_out_product_page():
    product = rules.extract_product(pdp_html(sold_out=True))
    assert product["out_of_stock"] is True and product["sizes"] is None
    # Still priced, from the sold-out variant.
    assert product["price"] == 3000.0


def test_page_without_product_data_returns_none():
    assert rules.extract_product("<html>Please enable JS</html>") is None
    assert rules.extract_product(pdp_html(with_product=False)) is None
    assert rules.extract_product("<script>__NEXT_DATA__ = {broken") is None


def test_search_key_is_read_from_the_page_config():
    assert rules.extract_search_api_key(pdp_html(api_key="k-123")) == "k-123"
    assert rules.extract_search_api_key("<html></html>") is None


# ---- merge

def test_merge_adds_gallery_to_both_rows_and_copy_to_english_only():
    rows = rules.rows_from_hit(search_hit(), "run", "d")
    english, arabic = rules.merge_pdp_into_rows(rows, rules.extract_product(pdp_html(images=5)))
    assert len(english["image_urls"]) == 5 and english["image_urls"] == arabic["image_urls"]
    assert english["text"]["details"][0] == "Flap closure"
    # The page copy is English, so the Arabic row has none.
    assert arabic["text"] is None
    # Names and prices stay as the search service gave them.
    assert arabic["product_name"] == "حقيبة كتف أكمي" and english["price"] == 3000.0


def test_merge_takes_stock_from_the_page_and_fills_blanks():
    rows = rules.rows_from_hit(search_hit(price=None, compare=None), "run", "d")
    english, _ = rules.merge_pdp_into_rows(rows, rules.extract_product(pdp_html(sold_out=True)))
    assert english["out_of_stock"] is True
    assert (english["price"], english["was_price"], english["price_discount"]) == (3000.0, 4000.0, 25)


def test_merge_without_page_data_keeps_the_search_rows():
    rows = rules.rows_from_hit(search_hit(), "run", "d")
    assert rules.merge_pdp_into_rows(rows, None) == rows


def test_constants_keep_brand_groups_below_the_page_size():
    assert constants.BRAND_GROUP_MAX_PRODUCTS < constants.SEARCH_PAGE_SIZE
