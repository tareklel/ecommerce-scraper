"""
PLP-efficient parity check, Part 5b (ecommercecrawl/plp_parity.py and its
wiring in PlpEfficientRun / the Ounass spider). Synthetic data only.
"""

import json

import pytest
import scrapy
from scrapy.exceptions import DontCloseSpider
from scrapy.http import TextResponse

from ecommercecrawl import access
from ecommercecrawl import plp_efficient as pe
from ecommercecrawl import plp_parity as parity
from tests.test_ounass_plp_efficient import (
    TOTE, _listing_response, _pdp_reply, _spider, hit, make_run, pdp, plp,
)
from ecommercecrawl.constants import ounass_constants as constants

AR = "saudi.ounass.com"
EN = "en-saudi.ounass.com"
EN_TOTE = "https://en-saudi.ounass.com/api/women/bags/tote-bags"


def config(**kw):
    kw.setdefault("parity_sample", 20)
    return pe.Config(**kw)


def key(sku, lang="ar"):
    return ("sa", lang, sku)


def item(sku, price, discount=None, sold_out=False, lang="AR"):
    return {"country": "SA", "language": lang, "portal_itemid": sku, "price": price,
            "price_discount": discount, "out_of_stock": sold_out, "primary_label": None}


def checked(n, host_url=TOTE, lang="ar", **cfg):
    """A ParityCheck with n held products on one hostname, all sampled as top-ups."""
    check = parity.ParityCheck(config(**cfg), seed="run")
    held = {}
    for i in range(n):
        k = key(str(i), lang)
        check.listing_seen(k, host_url + "?p=0", 1000, None, None)
        held[k] = {"url": f"https://{host_url.split('/')[2]}/shop-{i}.html"}
    host = host_url.split("/")[2]
    top_ups = check.plan({}, {host: held})
    return check, top_ups


# --- comparison rules ---------------------------------------------------------------

def test_discount_none_and_zero_are_the_same():
    assert parity.discounts_equal(None, 0) and parity.discounts_equal(25, 25.0)
    assert not parity.discounts_equal(None, 25)
    assert parity.prices_equal(1800, "1800.0") and not parity.prices_equal(1800, 1795)


# --- sample -------------------------------------------------------------------------

def test_new_products_are_free_comparisons_and_reduce_top_ups():
    check = parity.ParityCheck(config(parity_sample=5), seed="run")
    held = {}
    for i in range(10):
        check.listing_seen(key(str(i)), TOTE + "?p=0", 1000, None, None)
        held[key(str(i))] = {"url": f"https://{AR}/shop-{i}.html"}
    for sku in ("n1", "n2"):
        check.listing_seen(key(sku), TOTE + "?p=1", 500, None, None)
    top_ups = check.plan({key("n1"): f"https://{AR}/shop-n1.html",
                          key("n2"): f"https://{AR}/shop-n2.html"}, {AR: held})
    assert len(top_ups) == 3                                  # 5 - 2 free
    assert {c["source"] for k, c in check.comparisons.items() if k[2].startswith("n")} == {"free"}


def test_enough_new_products_means_no_top_up():
    check = parity.ParityCheck(config(parity_sample=2), seed="run")
    check.listing_seen(key("0"), TOTE, 1000, None, None)
    for sku in ("n1", "n2", "n3"):
        check.listing_seen(key(sku), TOTE, 500, None, None)
    top_ups = check.plan({key(s): f"https://{AR}/{s}" for s in ("n1", "n2", "n3")},
                         {AR: {key("0"): {"url": f"https://{AR}/0"}}})
    assert top_ups == [] and len(check.comparisons) == 3      # every free one is compared


def test_top_ups_prefer_on_sale_products_up_to_half_the_sample():
    check = parity.ParityCheck(config(parity_sample=4), seed="run")
    held = {}
    for i in range(10):
        check.listing_seen(key(str(i)), TOTE, 1000, 25 if i < 5 else None, None)
        held[key(str(i))] = {"url": f"https://{AR}/{i}"}
    check.plan({}, {AR: held})
    on_sale = [c for c in check.comparisons.values() if c["listing"]["discount"]]
    assert len(check.comparisons) == 4 and len(on_sale) == 2


def test_on_sale_top_ups_even_when_new_products_fill_the_sample():
    # Dry run #5: 49 free comparisons per hostname, only 1 on sale.
    check = parity.ParityCheck(config(parity_sample=4), seed="run")
    held = {}
    for i in range(10):
        check.listing_seen(key(str(i)), TOTE, 1000, 25 if i < 5 else 0, None)
        held[key(str(i))] = {"url": f"https://{AR}/{i}"}
    for sku in ("n1", "n2", "n3", "n4", "n5"):
        check.listing_seen(key(sku), TOTE, 500, 10 if sku == "n1" else 0, None)
    top_ups = check.plan({key(s): f"https://{AR}/{s}" for s in ("n1", "n2", "n3", "n4", "n5")},
                         {AR: held})
    assert len(top_ups) == 1                                  # 2 on sale wanted, 1 free on sale
    assert check.comparisons[top_ups[0][0]]["listing"]["discount"] == 25


def test_no_on_sale_rows_means_no_extra_top_ups():
    check = parity.ParityCheck(config(parity_sample=2), seed="run")
    check.listing_seen(key("0"), TOTE, 1000, 0, None)
    for sku in ("n1", "n2"):
        check.listing_seen(key(sku), TOTE, 500, 0, None)
    assert check.plan({key(s): f"https://{AR}/{s}" for s in ("n1", "n2")},
                      {AR: {key("0"): {"url": f"https://{AR}/0"}}}) == []


def test_product_seen_without_price_is_not_compared():
    check = parity.ParityCheck(config(), seed="run")
    check.listing_seen(key("1"), TOTE, None, None, None)
    assert check.plan({key("1"): f"https://{AR}/1"}, {}) == [] and not check.comparisons


# --- verdicts -----------------------------------------------------------------------

def test_all_agree_passes():
    check, top_ups = checked(12)
    for k, _ in top_ups:
        check.pdp_seen(k, item(k[2], 1000))
    v = check.finish([AR])[AR]
    assert (v["verdict"], v["basis"], v["compared"], v["confirmed"]) == ("pass", "own", 12, 0)


def test_one_confirmed_mismatch_is_only_a_warning():
    check, top_ups = checked(12)
    for k, _ in top_ups:
        check.pdp_seen(k, item(k[2], 900 if k[2] == "0" else 1000))
    assert [r[0] for r in check.take_rechecks()] == [key("0")]
    check.recheck_listing_seen(key("0"), 1000, None)
    check.recheck_pdp_seen(key("0"), item("0", 900))
    v = check.finish([AR])[AR]
    assert v["verdict"] == "pass" and v["confirmed"] == 1


def test_confirmed_mismatches_over_the_ratio_fail_the_hostname():
    check, top_ups = checked(10)
    for k, _ in top_ups:
        check.pdp_seen(k, item(k[2], 900 if k[2] in ("0", "1") else 1000))
    for k, _, _ in check.take_rechecks():
        check.recheck_listing_seen(k, 1000, None)
        check.recheck_pdp_seen(k, item(k[2], 900))
    v = check.finish([AR])[AR]
    assert (v["verdict"], v["confirmed"], v["compared"]) == ("fail", 2, 10)    # 20%, 2 minimum


def test_wrong_discount_is_a_mismatch():
    check, top_ups = checked(1)
    [(k, _)] = top_ups
    check.pdp_seen(k, item(k[2], 1000, discount=30))
    assert check.comparisons[k]["state"] == parity.MISMATCH


def test_price_change_between_fetches_is_cleared_by_the_recheck():
    check, top_ups = checked(10)
    for k, _ in top_ups:
        check.pdp_seen(k, item(k[2], 800 if k[2] in ("0", "1", "2") else 1000))  # a sale started
    for k, _, _ in check.take_rechecks():
        check.recheck_listing_seen(k, 800, 20)        # the listing now shows the sale too
        check.recheck_pdp_seen(k, item(k[2], 800, discount=20))
    v = check.finish([AR])[AR]
    assert (v["verdict"], v["cleared_on_recheck"], v["confirmed"]) == ("pass", 3, 0)


def test_recheck_entry_moved_off_its_page_is_excluded():
    check, top_ups = checked(1)
    [(k, _)] = top_ups
    check.pdp_seen(k, item(k[2], 900))
    check.take_rechecks()
    check.recheck_listing_seen(k, None, None, found=False)
    check.recheck_pdp_seen(k, item(k[2], 900))
    assert check.comparisons[k]["reason"] == parity.MOVED


def test_sold_out_and_other_product_are_excluded_not_mismatches():
    check, top_ups = checked(2)
    (k0, _), (k1, _) = sorted(top_ups)
    check.pdp_seen(k0, item(k0[2], 700, sold_out=True))
    check.pdp_seen(k1, item("someone-else", 700))
    reasons = {c["reason"] for c in check.comparisons.values()}
    assert reasons == {parity.SOLD_OUT, parity.DIFFERENT_PRODUCT}


def test_blocked_hostname_borrows_the_verdict_of_checked_ones():
    check = parity.ParityCheck(config(parity_sample=12), seed="run")
    held = {AR: {}, EN: {}}
    for i in range(12):
        for host_url, lang, host in ((TOTE, "ar", AR), (EN_TOTE, "en", EN)):
            check.listing_seen(key(str(i), lang), host_url, 1000, None, None)
            held[host][key(str(i), lang)] = {"url": f"https://{host}/{i}"}
    check.plan({}, held)
    for k, c in check.comparisons.items():
        if c["host"] == AR:
            check.pdp_seen(k, item(k[2], 1000))
        else:
            check.pdp_failed(k, access_error=True)          # EN product pages blocked
    verdicts = check.finish(held)
    assert (verdicts[AR]["verdict"], verdicts[AR]["basis"]) == ("pass", "own")
    assert (verdicts[EN]["verdict"], verdicts[EN]["basis"]) == ("pass", "borrowed")
    assert verdicts[EN]["excluded"] == {parity.ACCESS: 12}


def test_nothing_checkable_anywhere_is_not_checked():
    check, top_ups = checked(5)
    for k, _ in top_ups:
        check.pdp_failed(k, access_error=True)
    v = check.finish([AR])[AR]
    assert (v["verdict"], v["basis"]) == ("not_checked", None)


def test_page_that_never_came_back_is_excluded_at_the_verdict():
    check, _ = checked(3)
    v = check.finish([AR])[AR]
    assert v["excluded"] == {parity.NO_PRODUCT_DATA: 3} and v["verdict"] == "not_checked"


# --- run: rows held, written or dropped -----------------------------------------------

def _run_with_held(n, **cfg):
    run = make_run([plp()], [pdp(str(i)) for i in range(n)], **cfg)
    run.page_requested(0)
    run.page_parsed(0)
    for i in range(n):
        assert run.handle_hit(0, hit(str(i)), TOTE + "?p=0")[0] == "hold"
    run.select_phase2()
    return run


def test_failed_hostname_drops_its_listing_rows_as_content_degradation():
    run = _run_with_held(12, parity_sample=10)
    top_ups = run.plan_parity()
    for k, _ in top_ups:
        run.parity.pdp_seen(k, item(k[2], 999))              # every listing price wrong
        run.pdp_row_written(item(k[2], 999))
    for k, _, _ in run.parity.take_rechecks():
        run.parity.recheck_listing_seen(k, 1800, None)
        run.parity.recheck_pdp_seen(k, item(k[2], 999))
    assert run.release_rows() == []
    assert run.release == {"written": 0, "dropped": {AR: 2}, "replaced_by_product_page": 10}
    block = pe.manifest_block(run=run)
    json.dumps(block)
    [d] = [d for d in block["degradations"] if d["scope"] == AR]
    assert d["kind"] == "content" and "parity failed" in d["message"] and "2 listing rows dropped" in d["message"]
    assert block["refreshed_from_listing"] == 0


def test_unchecked_hostname_drops_rows_as_access_degradation():
    run = _run_with_held(12, parity_sample=10)
    for k, _ in run.plan_parity():
        run.parity.pdp_failed(k, access_error=True)
    assert run.release_rows() == []
    [d] = [d for d in pe.manifest_block(run=run)["degradations"] if d["scope"] == AR]
    assert d["kind"] == "access" and "parity not checked" in d["message"]


def test_passing_hostname_writes_rows_except_products_with_a_product_page_row():
    run = _run_with_held(12, parity_sample=10)
    for k, _ in run.plan_parity():
        run.parity.pdp_seen(k, item(k[2], 1800))
        run.pdp_row_written(item(k[2], 1800))
    rows = run.release_rows()
    assert len(rows) == 2 and run.refreshed_from_listing() == 2
    assert pe.manifest_block(run=run)["degradations"] == []


# --- spider wiring ------------------------------------------------------------------------

def _swept_spider(n, **settings):
    spider = _spider([plp()], [pdp(str(i)) for i in range(n)], **settings)
    list(spider.start_requests())
    list(spider.parse(_listing_response(f"{TOTE}?{constants.PLPSORT_KEY}={constants.PLPSORT}&p=0", 0,
                                        [hit(str(i)) for i in range(n)])))
    with pytest.raises(DontCloseSpider):
        spider._plp_efficient_on_idle()
    return spider, list(spider.crawler.engine.requests)


def test_spider_rechecks_a_mismatch_with_both_pages_then_clears_it(monkeypatch):
    spider, requests = _swept_spider(3, OUNASS_PLP_EFFICIENT_PARITY_SAMPLE=1)
    [top_up] = requests
    _pdp_reply(spider, monkeypatch, top_up, price=1500)           # listing said 1800
    with pytest.raises(DontCloseSpider):
        spider._plp_efficient_on_idle()                           # schedules the re-check
    listing_again, pdp_again = spider.crawler.engine.requests[1:]
    assert listing_again.url.endswith("&p=0") and listing_again.dont_filter
    assert pdp_again.url == top_up.url and pdp_again.dont_filter and pdp_again.meta["parity_recheck"]
    sku = top_up.meta["parity_key"][2]
    body = json.dumps({"hits": [hit(sku, sell=1500, before=1500)]}).encode()
    spider._plp_efficient_parity_recheck_listing(
        TextResponse(url=listing_again.url, body=body, encoding="utf-8", request=listing_again))
    assert _pdp_reply(spider, monkeypatch, pdp_again, price=1500) == []   # re-check rows aren't written
    with pytest.raises(DontCloseSpider):
        spider._plp_efficient_on_idle()                           # verdict + release
    v = spider.plp_run.parity.verdicts[AR]
    assert (v["verdict"], v["cleared_on_recheck"]) == ("pass", 1)


class _ZyteError(Exception):
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


def test_spider_blocked_product_page_is_excluded_as_access(monkeypatch):
    spider, requests = _swept_spider(3, OUNASS_PLP_EFFICIENT_PARITY_SAMPLE=1)
    [top_up] = requests
    spider._plp_efficient_pdp_failed(_failure(top_up, access.AccessDeferred("later")))
    assert spider.plp_run.parity.comparisons[top_up.meta["parity_key"]]["state"] == parity.WAITING
    spider._plp_efficient_pdp_failed(_failure(top_up, _ZyteError(520)))
    assert spider.plp_run.parity.comparisons[top_up.meta["parity_key"]]["reason"] == parity.ACCESS
    spider._plp_efficient_on_idle()                               # not checked: nothing released
    assert spider.plp_run.release["dropped"] == {AR: 3}           # incl. the blocked one


def test_spider_refused_product_page_reaching_the_callback_is_access():
    spider, requests = _swept_spider(3, OUNASS_PLP_EFFICIENT_PARITY_SAMPLE=1)
    [top_up] = requests
    refused = TextResponse(url=top_up.url, status=403, body=b"denied", encoding="utf-8", request=top_up)
    assert list(spider.parse_pdp(refused)) == []
    assert spider.plp_run.parity.comparisons[top_up.meta["parity_key"]]["reason"] == parity.ACCESS


def test_access_middleware_ignores_data_requests():
    class _Crawler:
        class settings:
            @staticmethod
            def getint(name, default):
                return default

            @staticmethod
            def getfloat(name, default):
                return default
    mw = access.AccessRetryMiddleware(_Crawler())
    request = scrapy.Request("data:,")
    response = TextResponse(url="data:,", body=b"", request=request)
    assert mw.process_response(request, response, None) is response
    assert mw.summary()["hosts"] == {}
