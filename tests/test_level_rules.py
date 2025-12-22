import pytest
from types import SimpleNamespace

from ecommercecrawl.rules import level_rules as rules


def test_get_products_returns_value():
    payload = {"products": [{"id": 1}, {"id": 2}]}
    assert rules.get_products(payload) == payload["products"]


def test_get_products_missing_key():
    assert rules.get_products({"other": []}) is None


@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://www.levelshoes.com/women/bags", "ae"),
        ("https://en-saudi.levelshoes.com/women/bags", "sa"),
        ("https://ar-saudi.levelshoes.com/women/bags", "sa"),
        ("https://en-kuwait.levelshoes.com/men/bags", "kw"),
        ("https://en-qatar.levelshoes.com/women/sale", "qa"),
        ("https://levels.example.com/women/bags", None),
    ],
)
def test_get_country(url, expected):
    assert rules.get_country(url) == expected


@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://www.levelshoes.com/men/shoes", "men"),
        ("https://www.levelshoes.com/women/bags", "women"),
        ("https://www.levelshoes.com/kids/sneakers", "kids"),
        ("https://www.levelshoes.com/stories/all", None),
    ],
)
def test_get_gender(url, expected):
    assert rules.get_gender(url) == expected


def test_get_language_defaults_to_en():
    url = "https://www.levelshoes.com/women/bags"
    assert rules.get_language(url) == "en"


def test_get_language_detects_arabic_from_path():
    url = "https://www.levelshoes.com/ar/women/bags"
    assert rules.get_language(url) == "ar"


def test_get_language_detects_arabic_from_subdomain():
    url = "https://ar-saudi.levelshoes.com/women/bags"
    assert rules.get_language(url) == "ar"


def test_get_language_raises_for_non_plp():
    with pytest.raises(ValueError):
        rules.get_language("https://www.levelshoes.com/stories/all")


@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://www.levelshoes.com/women/brands/miu-miu/bags", "brands/miu-miu/bags"),
        ("https://www.levelshoes.com/women/sale?color=black", "sale"),
        ("https://www.levelshoes.com/women", None),
    ],
)
def test_get_urlpath(url, expected):
    assert rules.get_urlpath(url) == expected


@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://www.levelshoes.com/women/bags", True),
        ("https://www.levelshoes.com/women/sale?color=black", True),
        ("https://www.levelshoes.com/bally-bag.html", False),
        ("https://www.levelshoes.com/stories/all", False),
    ],
)
def test_is_plp(url, expected):
    assert rules.is_plp(url) is expected


def test_is_pdp_true_when_html_and_no_gender():
    response = SimpleNamespace(url="https://www.levelshoes.com/bally-bag.html")
    assert rules.is_pdp(response) is True


def test_is_pdp_false_when_gender_present_in_html_url():
    response = SimpleNamespace(url="https://www.levelshoes.com/women/bally-bag.html")
    assert rules.is_pdp(response) is False


def test_is_pdp_false_when_not_html():
    response = SimpleNamespace(url="https://www.levelshoes.com/women/bags")
    assert rules.is_pdp(response) is False
