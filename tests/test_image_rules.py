import pytest

from ecommercecrawl.rules.image_rules import (
    normalize_image_url,
    normalize_ordered_image_urls,
)


@pytest.mark.parametrize(
    ("raw_url", "allow_bare_host", "expected"),
    [
        (
            " //cdn.example.com/a.jpg?width=720#hero ",
            False,
            "https://cdn.example.com/a.jpg?width=720#hero",
        ),
        (
            "http://cdn.example.com/a.jpg",
            False,
            "https://cdn.example.com/a.jpg",
        ),
        (
            "cdn.example.com/a.jpg",
            True,
            "https://cdn.example.com/a.jpg",
        ),
        ("cdn.example.com/a.jpg", False, None),
        ("javascript:alert(1)", False, None),
        ("https:///missing-host.jpg", False, None),
        ("https://user:secret@cdn.example.com/a.jpg", False, None),
        (None, False, None),
    ],
)
def test_normalize_image_url(raw_url, allow_bare_host, expected):
    assert normalize_image_url(
        raw_url,
        allow_bare_host=allow_bare_host,
    ) == expected


def test_normalize_ordered_image_urls_preserves_order_and_query_parameters():
    assert normalize_ordered_image_urls(
        [
            "http://cdn.example.com/hero.jpg?version=1",
            "https://cdn.example.com/hero.jpg?version=1",
            "https://cdn.example.com/side.jpg?version=2",
        ]
    ) == [
        "https://cdn.example.com/hero.jpg?version=1",
        "https://cdn.example.com/side.jpg?version=2",
    ]


def test_normalize_ordered_image_urls_distinguishes_empty_from_all_invalid():
    assert normalize_ordered_image_urls([]) == []
    assert normalize_ordered_image_urls([None, "data:image/png;base64,abc"]) is None
