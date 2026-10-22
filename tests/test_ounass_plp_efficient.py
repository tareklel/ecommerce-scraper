"""
PLP-efficient crawl, Part 3: listing-entry decisions, Phase 2 selection and the
spider wiring (ecommercecrawl/plp_efficient.py PlpEfficientRun,
ecommercecrawl/spiders/ounass_crawl.py). Synthetic data only.
"""

import json
from datetime import datetime, timedelta, timezone

import pytest
import scrapy
from scrapy.exceptions import DontCloseSpider
from scrapy.http import TextResponse
from scrapy.settings import Settings

from ecommercecrawl import plp_efficient as pe
from ecommercecrawl.constants import ounass_constants as constants
from ecommercecrawl.spiders.ounass_crawl import OunassSpider

NOW = datetime.now(timezone.utc)
TOTE = "https://saudi.ounass.com/api/women/bags/tote-bags"
SHOULDER = "https://saudi.ounass.com/api/women/bags/shoulder-bags"

VOCAB = {
    "country": ["sa"], "language": ["ar", "en"], "gender": ["women"],
    "category_subcategory": [["bags", "tote_bags"], ["bags", "shoulder_bags"]],
    "brand": ["brand_a", "brand_b"],
}


def plp(url=TOTE, subcategory="tote_bags", **kw):
    row = {"url": url, "site": "ounass", "country": "sa", "language": "ar", "gender": "women",
           "category": "bags", "subcategory": subcategory, "brand": ""}
    row.update(kw)
    return row


def pdp(item_id, subcategory="tote_bags", **kw):
    row = {"portal_itemid": item_id, "primary_key": f"{item_id}_ounass", "site": "ounass",
           "country": "sa", "language": "ar",
           "url": f"https://saudi.ounass.com/shop-made-up-{item_id}_19.html",
           "gender": "women", "category": "bags", "subcategory": subcategory, "brand": "brand_a",
           "out_of_stock": "false", "last_available_date": NOW.date().isoformat(),
           "last_crawl_date": NOW.date().isoformat()}
    row.update(kw)
    return row


def hit(sku, sell=1800, before=1800, badges=None, currency="SAR", slug=None):
    return {"visibleSku": sku, "slug": slug or f"shop-made-up-{sku}_19",
            "price": before, "priceByCustomerGroupId": {"-1": sell, "5": sell},
            "localeCurrency": currency, "badges": badges or []}


def validated(plp_rows, pdp_rows):
    inputs = pe.Inputs(
        plp_rows=plp_rows, pdp_rows=pdp_rows, vocabulary=VOCAB,
        manifest={"export_id": "t", "gold_built_at": NOW.isoformat(), "files": {"x": {}}},
        plp_columns=list(pe.PLP_COLUMNS), pdp_columns=list(pe.PDP_COLUMNS))
    return inputs, pe.validate(inputs, pe.Config(), now=NOW)


def make_run(plp_rows, pdp_rows, **config):
    _, result = validated(plp_rows, pdp_rows)
    return pe.PlpEfficientRun(result, pe.Config(**config), "run-1", "2026-10-16")


# --- Extraction rules (Part 0 parity) -----------------------------------------

def test_selling_price_uses_customer_group_price_not_price_key():
    assert pe.plp_hit_selling_price(hit("1", sell=3995, before=6150)) == 3995


@pytest.mark.parametrize("sell, before, expected", [
    (1800, 2400, 25),    # 25.0%
    (115, 135, 15),      # 14.81% -> 15
    (675, 1000, 33),     # exactly 32.5% -> rounds half UP
    (1850, 1850, None),  # full price -> no discount, like the PDP path
])
def test_discount_is_computed_from_the_two_prices(sell, before, expected):
    assert pe.plp_hit_discount(hit("1", sell=sell, before=before)) == expected


def test_primary_label_is_highest_priority_badge():
    badges = [{"value": "  NEW   SEASON ", "priority": 30}, {"value": "EXCLUSIVE", "priority": 10}]
    assert pe.plp_hit_primary_label(hit("1", badges=badges)) == ["NEW SEASON"]
    assert pe.plp_hit_primary_label(hit("1")) is None


# --- Phase 1: one listing entry -----------------------------------------------

def test_matching_known_product_emits_plp_extract_row():
    run = make_run([plp()], [pdp("100")])
    action, row = run.handle_hit(0, hit("100", sell=1800, before=2400,
                                        badges=[{"value": "NEW SEASON", "priority": 30}]),
                                 TOTE + "?p=0")
    assert action == "emit"
    assert row == {
        "run_id": "run-1", "site": "ounass", "crawl_date": "2026-10-16",
        "url": "https://saudi.ounass.com/shop-made-up-100_19.html",  # from gold, never the listing
        "language": "AR", "country": "sa", "portal_itemid": "100",
        "price": 1800, "price_discount": 25, "primary_label": ["NEW SEASON"],
        "plp_extract_flag": 1, "plp_source_url": TOTE + "?p=0",
    }


def test_same_product_on_overlapping_listing_is_emitted_once():
    run = make_run([plp(), plp(url=TOTE + "-2")], [pdp("100")])
    assert run.handle_hit(0, hit("100"), TOTE)[0] == "emit"
    assert run.handle_hit(1, hit("100"), TOTE + "-2") == ("skip", "already refreshed by an overlapping listing")


def test_unknown_product_is_new_and_queued_for_phase2_by_its_slug():
    run = make_run([plp()], [pdp("100")])
    action, url = run.handle_hit(0, hit("999", slug="shop-brand-new-bag-999_15"), TOTE)
    assert (action, url) == ("new", "https://saudi.ounass.com/shop-brand-new-bag-999_15.html")


def test_known_id_with_different_fields_counts_as_mismatch():
    # Gold says shoulder bags, but it was seen on the tote listing (reclassification / drift).
    run = make_run([plp(), plp(url=SHOULDER, subcategory="shoulder_bags")],
                   [pdp("100", subcategory="shoulder_bags")])
    assert run.handle_hit(0, hit("100"), TOTE) == ("mismatch", None)
    assert run.stats[0]["mismatched"] == 1


def test_quarantined_product_is_skipped():
    run = make_run([plp()], [pdp(str(i)) for i in range(30)] + [pdp("bad", brand="unknown")])
    assert run.handle_hit(0, hit("bad"), TOTE) == ("skip", "quarantined product")


def test_entry_without_selling_price_is_left_for_phase2():
    run = make_run([plp()], [pdp("100")])
    entry = hit("100")
    entry["priceByCustomerGroupId"] = {}
    assert run.handle_hit(0, entry, TOTE)[0] == "skip"
    assert ("sa", "ar", "100") not in run.crawled


def test_wrong_currency_stops_that_listing():
    run = make_run([plp()], [pdp("100")])
    assert not run.check_currency(0, hit("100", currency="AED"))
    assert run.is_stopped(0) and "G7" in run.stats[0]["stopped"]


# --- Phase 2 selection ----------------------------------------------------------

def _swept(run, idx=0):
    run.page_requested(idx)
    run.page_parsed(idx)


def test_g4_cap_holds_back_unseen_products_and_new_finds_of_that_listing():
    run = make_run([plp()], [pdp("1"), pdp("2"), pdp("3"), pdp("9", subcategory="shoulder_bags")])
    _swept(run)
    run.handle_hit(0, hit("1"), TOTE)
    run.handle_hit(0, hit("2"), TOTE)
    run.handle_hit(0, hit("777"), TOTE)          # new
    phase2 = run.select_phase2()                 # 1 of 3 expected unseen = 33% > 25%
    assert "G4" in phase2["listing_health"][TOTE]
    assert phase2["counts"]["held_back"] == 1 and phase2["counts"]["held_back_new"] == 1
    # The product no listing covers still goes to Phase 2.
    assert phase2["urls"] == ["https://saudi.ounass.com/shop-made-up-9_19.html"]


def test_phase2_includes_unseen_known_under_the_cap():
    run = make_run([plp()], [pdp(str(i)) for i in range(10)] + [pdp("u", subcategory="shoulder_bags")])
    _swept(run)
    for i in range(9):                           # 9 of 10 seen -> 10% unseen, under 25%
        run.handle_hit(0, hit(str(i)), TOTE)
    run.handle_hit(0, hit("777"), TOTE)
    phase2 = run.select_phase2()
    assert phase2["listing_health"][TOTE] is None
    assert phase2["counts"] == {"known_unseen": 1, "uncovered": 1, "new": 1, "held_back": 0,
                                "held_back_new": 0}
    assert set(phase2["urls"]) == {
        "https://saudi.ounass.com/shop-made-up-9_19.html",
        "https://saudi.ounass.com/shop-made-up-u_19.html",
        "https://saudi.ounass.com/shop-made-up-777_19.html",
    }


def test_g4_cap_ignores_products_gold_already_has_as_sold_out():
    rows = [pdp("1"), pdp("2", out_of_stock="true"), pdp("3", out_of_stock="true")]
    run = make_run([plp()], rows)
    _swept(run)
    run.handle_hit(0, hit("1"), TOTE)            # the only in-stock product was seen
    phase2 = run.select_phase2()
    assert phase2["listing_health"][TOTE] is None
    assert phase2["counts"]["known_unseen"] == 2  # sold-out ones still get their PDP check


def test_partially_fetched_listing_holds_back_its_products_and_new_finds():
    run = make_run([plp()], [pdp(str(i)) for i in range(10)])
    _swept(run)
    run.page_requested(0)
    run.page_failed(0)                           # one page failed (G3)
    run.handle_hit(0, hit("0"), TOTE)
    run.handle_hit(0, hit("777"), TOTE)
    phase2 = run.select_phase2()
    assert "G3" in phase2["listing_health"][TOTE]
    assert phase2["urls"] == []
    assert phase2["counts"]["held_back"] == 9 and phase2["counts"]["held_back_new"] == 1


def test_g11_drift_keeps_emitted_rows_but_holds_back_leftovers():
    # Tote listing: 9 known matching, 1 known ID whose gold fields say shoulder bags.
    rows = [pdp(str(i)) for i in range(9)] + [pdp("x", subcategory="shoulder_bags")] + \
           [pdp(f"t{i}") for i in range(3)]      # 3 tote products never seen
    run = make_run([plp(), plp(url=SHOULDER, subcategory="shoulder_bags")], rows,
                   missing_ratio_cap=1.0)        # isolate G11 from the G4 cap
    _swept(run, 0)
    _swept(run, 1)
    emitted = [run.handle_hit(0, hit(str(i)), TOTE)[0] for i in range(9)]
    run.handle_hit(0, hit("x"), TOTE)            # mismatch: 1 of 10 = 10% > 5%
    phase2 = run.select_phase2()
    assert emitted == ["emit"] * 9               # already-written rows stay
    assert "G11" in phase2["listing_health"][TOTE]
    assert not any("/shop-made-up-t" in u for u in phase2["urls"])  # leftovers held back
    assert "https://saudi.ounass.com/shop-made-up-x_19.html" in phase2["urls"]  # healthy shoulder listing


def test_ceiling_exceeded_skips_phase2():
    run = make_run([plp()], [pdp(str(i), subcategory="shoulder_bags") for i in range(5)],
                   max_phase2_pdps=3)
    _swept(run)
    phase2 = run.select_phase2()
    assert phase2["phase2_ceiling_exceeded"] and phase2["urls"] == [] and phase2["candidates"] == 5


# --- Spider wiring --------------------------------------------------------------

def _settings():
    return Settings({
        "CRAWLER_API_SERVICE": "zyte", "OUNASS_FETCH_BACKEND": "auto", "OUNASS_REQUESTS_TLDS": [],
        "OUNASS_CRAWLER_API_PLP_REQUEST_TYPE": "http_response",
        "OUNASS_CRAWLER_API_PDP_REQUEST_TYPE": "http_response",
    })


def _listing_response(url, idx, hits, page=0, total_pages=1):
    body = json.dumps({"routeType": "plp", "page": page,
                       "pagination": {"totalPages": total_pages}, "hits": hits})
    request = scrapy.Request(url, meta={"plp_idx": idx})
    return TextResponse(url=url, body=body.encode("utf-8"), encoding="utf-8", request=request)


class _FakeEngine:
    def __init__(self):
        self.requests = []

    def crawl(self, request):
        self.requests.append(request)


class _FakeStats:
    def __init__(self):
        self.values = {}

    def set_value(self, key, value):
        self.values[key] = value


class _FakeCrawler:
    def __init__(self):
        self.engine = _FakeEngine()
        self.stats = _FakeStats()


def _spider(plp_rows, pdp_rows):
    spider = OunassSpider(plp_efficient=True)
    spider.settings = _settings()
    spider.crawler = _FakeCrawler()
    inputs, _ = validated(plp_rows, pdp_rows)
    spider._load_plp_efficient_inputs = lambda: inputs
    return spider


def test_spider_off_by_default_and_pdp_rows_carry_flag_0(monkeypatch):
    spider = OunassSpider()
    assert not spider.plp_efficient_enabled()
    monkeypatch.setattr("ecommercecrawl.spiders.ounass_crawl.rules.get_state",
                        lambda response: {"country": "AE", "currency": "AED",
                                          "pdp": {"visibleSku": "1", "images": [], "contentTabs": []}})
    response = TextResponse(url="https://www.ounass.ae/shop-x-1.html", body=b"<html></html>",
                            encoding="utf-8")
    [row] = list(spider.parse_pdp(response))
    assert row["plp_extract_flag"] == 0


def test_spider_startup_stop_makes_no_request():
    spider = _spider([plp(subcategory="nope")], [pdp("1")])
    assert list(spider.start_requests()) == []
    assert spider.plp_run is None and spider.plp_efficient_result.stop


def test_spider_sweeps_listing_emits_rows_and_schedules_phase2():
    spider = _spider([plp()], [pdp(str(i)) for i in range(10)])
    [seed] = list(spider.start_requests())
    assert seed.url == TOTE and seed.meta["plp_idx"] == 0 and seed.errback is not None

    # Unsorted page 0: schedules every sorted page, processes nothing itself.
    first = list(spider.parse(_listing_response(TOTE, 0, [hit("0")], total_pages=2)))
    assert [r.url for r in first] == [
        f"{TOTE}?{constants.PLPSORT_KEY}={constants.PLPSORT}&p=0",
        f"{TOTE}?{constants.PLPSORT_KEY}={constants.PLPSORT}&p=1",
    ]
    assert all(r.meta["plp_idx"] == 0 for r in first)

    sorted_p0 = list(spider.parse(_listing_response(first[0].url, 0,
                                                    [hit(str(i)) for i in range(5)], total_pages=2)))
    sorted_p1 = list(spider.parse(_listing_response(first[1].url, 0,
                                                    [hit(str(i)) for i in range(5, 9)] + [hit("777")],
                                                    page=1, total_pages=2)))
    rows = [r for r in sorted_p0 + sorted_p1 if isinstance(r, dict)]
    assert len(rows) == 9 and all(r["plp_extract_flag"] == 1 for r in rows)
    assert not any(isinstance(r, scrapy.Request) and "shop-" in r.url for r in sorted_p0 + sorted_p1)

    with pytest.raises(DontCloseSpider):
        spider._plp_efficient_on_idle()
    scheduled = {r.url for r in spider.crawler.engine.requests}
    assert scheduled == {"https://saudi.ounass.com/shop-made-up-9_19.html",   # known, unseen
                         "https://saudi.ounass.com/shop-made-up-777_19.html"}  # new
    assert all(r.callback == spider.parse_pdp for r in spider.crawler.engine.requests)
    # Second idle: Phase 2 already done, the spider may close.
    spider._plp_efficient_on_idle()


def test_spider_failed_listing_page_holds_back_its_products():
    spider = _spider([plp()], [pdp(str(i)) for i in range(4)])
    [seed] = list(spider.start_requests())

    class _Failure:
        request = seed
        value = RuntimeError("520")

    spider._plp_efficient_listing_failed(_Failure())
    spider._plp_efficient_on_idle()              # nothing to schedule: no DontCloseSpider
    assert spider.crawler.engine.requests == []
    assert "G3" in spider.plp_run.phase2["listing_health"][TOTE]


# --- Run manifest block (Part 4) ----------------------------------------------

def test_manifest_block_startup_stop_explains_why():
    spider = _spider([plp(subcategory="nope")], [pdp("1")])
    list(spider.start_requests())
    block = spider.plp_efficient_manifest_block()
    json.dumps(block)                                  # must be JSON-serialisable
    assert block["startup_stopped"] is True
    assert block["startup"]["stop_messages"]
    assert block["inputs"]["export_id"] == "t"
    assert block["listings"] is None and block["phase2"] is None


def test_manifest_block_export_failure():
    spider = OunassSpider(plp_efficient=True)
    spider.settings = _settings()

    def fail():
        raise pe.ExportError("lambda timed out")
    spider._load_plp_efficient_inputs = fail
    assert list(spider.start_requests()) == []
    block = spider.plp_efficient_manifest_block()
    assert block["startup_stopped"] is True and "lambda timed out" in block["startup_error"]
    assert block["inputs"] is None


def test_manifest_block_clean_run_has_no_degradations():
    spider = _spider([plp()], [pdp(str(i)) for i in range(3)])
    list(spider.start_requests())
    list(spider.parse(_listing_response(f"{TOTE}?{constants.PLPSORT_KEY}={constants.PLPSORT}&p=0", 0,
                                        [hit(str(i)) for i in range(3)])))
    spider._plp_efficient_on_idle()                    # nothing left for Phase 2
    block = spider.plp_efficient_manifest_block()
    json.dumps(block)
    assert block["startup_stopped"] is False
    assert block["degradations"] == []
    assert block["refreshed_from_listing"] == 3
    assert block["phase2"]["scheduled"] == 0
    [listing] = block["listings"]
    assert listing["emitted"] == 3 and listing["held_back_reason"] is None


def test_manifest_block_names_held_back_listing_and_ceiling():
    rows = [pdp(str(i)) for i in range(4)] + [pdp(f"s{i}", subcategory="shoulder_bags") for i in range(5)]
    run = make_run([plp()], rows, max_phase2_pdps=3)
    run.page_requested(0)
    run.page_failed(0)                                 # G3
    run.select_phase2()
    block = pe.manifest_block(result=None, run=run)
    [held] = [d for d in block["degradations"] if "listing held back" in d["message"]]
    assert "G3" in held["message"] and held["kind"] == "content" and held["scope"] == TOTE
    assert any("Phase 2 skipped" in d["message"] for d in block["degradations"])
    assert block["phase2"]["phase2_ceiling_exceeded"] is True


def test_manifest_block_is_none_in_normal_mode():
    assert OunassSpider().plp_efficient_manifest_block() is None


# --- Access layer integration (Part 5a) -------------------------------------------

from ecommercecrawl import access as access_layer


class _ZyteError(Exception):
    """Stand-in for zyte_api.RequestError."""
    def __init__(self, status):
        super().__init__(status)
        self.status = status
_ZyteError.__name__ = "RequestError"


def _failure(request, exc):
    class _F:
        pass
    f = _F()
    f.request, f.value = request, exc
    return f


def test_deferred_listing_page_is_not_a_g3_failure():
    spider = _spider([plp()], [pdp("1")])
    [seed] = list(spider.start_requests())
    spider._plp_efficient_listing_failed(_failure(seed, access_layer.AccessDeferred("later")))
    assert spider.plp_run.stats[0]["pages_failed"] == 0


def test_listing_lost_to_blocking_is_an_access_degradation():
    spider = _spider([plp()], [pdp(str(i)) for i in range(3)])
    [seed] = list(spider.start_requests())
    spider._plp_efficient_listing_failed(_failure(seed, _ZyteError(520)))
    spider._plp_efficient_on_idle()
    assert "access" in spider.plp_run.phase2["listing_health"][TOTE]
    block = spider.plp_efficient_manifest_block()
    [held] = [d for d in block["degradations"] if d["scope"] == TOTE]
    assert held["kind"] == "access"


def test_blocked_listing_response_is_not_parsed_as_content():
    spider = _spider([plp()], [pdp("1")])
    list(spider.start_requests())
    url = f"{TOTE}?{constants.PLPSORT_KEY}={constants.PLPSORT}&p=0"
    request = scrapy.Request(url, meta={"plp_idx": 0})
    blocked = TextResponse(url=url, status=403, body=b"<html>denied</html>", encoding="utf-8",
                           request=request)
    assert list(spider.parse(blocked)) == []
    stats = spider.plp_run.stats[0]
    assert stats["pages_failed_access"] == 1 and stats["pages_parsed"] == 0


def test_phase2_waits_for_access_retry_rounds():
    spider = _spider([plp()], [pdp("1")])
    list(spider.start_requests())

    class _Busy:
        def busy(self):
            return True
    spider.crawler.access_retry = _Busy()
    spider._plp_efficient_on_idle()
    assert spider.plp_run.phase2 is None          # not chosen yet
    spider.crawler.access_retry = None
    spider._plp_efficient_on_idle()
    assert spider.plp_run.phase2 is not None



def test_normal_mode_flags_listing_requests_not_product_pages():
    spider = OunassSpider()
    spider.settings = _settings()
    [listing] = list(spider._handle_seed_url("https://saudi.ounass.com/api/women/designers/ami"))
    [product] = list(spider._handle_seed_url("https://saudi.ounass.com/shop-x-1.html"))
    assert listing.meta.get(access_layer.LISTING_META_KEY) is True
    assert access_layer.LISTING_META_KEY not in product.meta



def test_stale_gold_warns_in_log_and_manifest_but_does_not_stop(caplog):
    spider = _spider([plp()], [pdp("1")])
    inputs, _ = validated([plp()], [pdp("1")])
    inputs.manifest["gold_built_at"] = (NOW - timedelta(days=6)).isoformat()
    spider._load_plp_efficient_inputs = lambda: inputs
    with caplog.at_level("WARNING"):
        requests = list(spider.start_requests())
    assert requests                                   # the crawl starts
    assert any("startup warning G8" in r.message for r in caplog.records)
    block = spider.plp_efficient_manifest_block()
    assert any(m.startswith("G8: gold last rebuilt 6.0 days ago") for m in block["startup"]["warning_messages"])
