"""
PLP-efficient parity check (Part 5b, guardrail G9; see
docs/ounass_plp_efficient_crawl.md, section 3 "Parity check").

Is the listing still telling the truth? Every run compares listing prices with
product-page prices for a sample of products, per hostname, before that
hostname's listing rows are written.

Comparisons come from two places:
  - free: products the run fetches a product page for anyway (Phase 2: new
    products, and known ones whose listing fields disagreed with gold), whose
    listing entry was seen with a price;
  - top-up: listing-refreshed products whose product page is fetched only for
    the check, when the free ones don't reach the sample size. On-sale
    products first, so discounts are covered.

A mismatch is re-checked by fetching the listing page and the product page
again: agreement now means the price changed between the two fetches
(cleared), disagreement is a confirmed mismatch. Access problems and sold-out
products are excluded, never counted as mismatches.

Pure Python (no Scrapy): the spider reports observations, this decides.
"""

import math
import random
from urllib.parse import urlparse

# Comparison states.
WAITING = "waiting"          # product page not back yet
AGREE = "agree"
MISMATCH = "mismatch"        # first comparison disagrees; re-check not sent yet
RECHECKING = "rechecking"
CLEARED = "cleared"          # re-check agrees: a real price change between fetches
CONFIRMED = "confirmed"
EXCLUDED = "excluded"

# Exclusion reasons. Only ACCESS can make a hostname borrow another's verdict.
ACCESS = "access"
SOLD_OUT = "sold_out"
NO_PRODUCT_DATA = "no_product_data"        # page fetched but nothing usable parsed
DIFFERENT_PRODUCT = "different_product"    # the page is another product ID
MOVED = "moved"                            # re-check: entry no longer on that listing page

PASS = "pass"
FAIL = "fail"
NOT_CHECKED = "not_checked"

FREE = "free"
TOP_UP = "top_up"

MAX_LOGGED_MISMATCHES = 20


def _num(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def prices_equal(a, b):
    a, b = _num(a), _num(b)
    return a is not None and b is not None and abs(a - b) < 0.01


def discounts_equal(a, b):
    # No discount is None on both paths; treat 0 the same.
    return abs((_num(a) or 0.0) - (_num(b) or 0.0)) < 0.01


def first_label(labels):
    return labels[0] if isinstance(labels, list) and labels else None


def item_key(item):
    """(country, language, portal_itemid) of a product-page row, lowercased like listing rows."""
    def low(value):
        return str(value).strip().lower() if value not in (None, "") else None
    sku = item.get("portal_itemid")
    return (low(item.get("country")), low(item.get("language")), str(sku).strip() if sku else None)


class ParityCheck:
    def __init__(self, config, seed=None):
        self.config = config
        self.rng = random.Random(seed)
        self.listing = {}        # key -> {"host", "page_url", "price", "discount", "label"}
        self.comparisons = {}    # key -> comparison dict
        self.verdicts = None

    # --- listing side ----------------------------------------------------------

    def listing_seen(self, key, page_url, price, discount, label):
        """A listing entry with a selling price. First sighting wins (overlapping listings)."""
        if price is None or key in self.listing:
            return
        self.listing[key] = {
            "host": (urlparse(page_url).hostname or "").lower(),
            "page_url": page_url, "price": price, "discount": discount, "label": label,
        }

    # --- sample ------------------------------------------------------------------

    def _new_comparison(self, key, source, pdp_url):
        seen = self.listing[key]
        self.comparisons[key] = {
            "host": seen["host"], "source": source, "pdp_url": pdp_url,
            "state": WAITING, "reason": None,
            "listing": {k: seen[k] for k in ("price", "discount", "label")},
            "pdp": None, "recheck_listing": None, "recheck_pdp": None, "label_differs": False,
        }

    def plan(self, phase2_urls_by_key, held_by_host):
        """
        Choose the comparisons once Phase 2 is known. `phase2_urls_by_key`:
        products whose product page Phase 2 fetches anyway; `held_by_host`:
        {host: {key: listing row}} waiting for a verdict. Returns the top-up
        product pages to fetch, as [(key, url)].
        """
        for key, url in phase2_urls_by_key.items():
            if key in self.listing:
                self._new_comparison(key, FREE, url)
        sample = self.config.parity_sample
        top_ups = []
        for host in sorted(held_by_host):
            free = [c for c in self.comparisons.values() if c["host"] == host]
            need = max(0, sample - len(free))
            if not need:
                continue
            free_on_sale = sum(1 for c in free if c["listing"]["discount"])
            want_on_sale = min(need, max(0, math.ceil(sample / 2) - free_on_sale))
            candidates = [k for k in sorted(held_by_host[host])
                          if k in self.listing and k not in self.comparisons]
            on_sale = [k for k in candidates if self.listing[k]["discount"]]
            self.rng.shuffle(on_sale)
            chosen = on_sale[:want_on_sale]
            rest = [k for k in candidates if k not in set(chosen)]
            self.rng.shuffle(rest)
            chosen += rest[:need - len(chosen)]
            for key in chosen:
                url = held_by_host[host][key]["url"]
                self._new_comparison(key, TOP_UP, url)
                top_ups.append((key, url))
        return top_ups

    def is_compared(self, key):
        return key in self.comparisons

    def top_up_keys(self):
        return {k for k, c in self.comparisons.items() if c["source"] == TOP_UP}

    # --- product page side --------------------------------------------------------

    def _exclude(self, comparison, reason):
        comparison["state"], comparison["reason"] = EXCLUDED, reason

    def pdp_seen(self, key, item):
        """The product page for a sampled product (first fetch)."""
        c = self.comparisons.get(key)
        if c is None or c["state"] != WAITING:
            return
        c["pdp"] = {"price": item.get("price"), "discount": item.get("price_discount"),
                    "label": first_label(item.get("primary_label"))}
        if item_key(item)[2] != key[2]:
            self._exclude(c, DIFFERENT_PRODUCT)
        elif str(item.get("out_of_stock")).lower() == "true":
            self._exclude(c, SOLD_OUT)
        elif _num(item.get("price")) is None:
            self._exclude(c, NO_PRODUCT_DATA)
        else:
            listing = c["listing"]
            c["label_differs"] = listing["label"] != c["pdp"]["label"]
            same = (prices_equal(listing["price"], item.get("price"))
                    and discounts_equal(listing["discount"], item.get("price_discount")))
            c["state"] = AGREE if same else MISMATCH

    def pdp_failed(self, key, access_error):
        c = self.comparisons.get(key)
        if c is not None and c["state"] == WAITING:
            self._exclude(c, ACCESS if access_error else NO_PRODUCT_DATA)

    # --- re-checks ----------------------------------------------------------------

    def take_rechecks(self):
        """Mismatches to re-check now, as [(key, listing_page_url, pdp_url)]; each once."""
        out = []
        for key, c in sorted(self.comparisons.items()):
            if c["state"] == MISMATCH:
                c["state"] = RECHECKING
                out.append((key, self.listing[key]["page_url"], c["pdp_url"]))
        return out

    def _settle_recheck(self, c):
        lst, pdp = c["recheck_listing"], c["recheck_pdp"]
        if lst is None or pdp is None:
            return
        if "excluded" in lst or "excluded" in pdp:
            reason = lst.get("excluded") or pdp.get("excluded")
            self._exclude(c, reason)
            return
        same = (prices_equal(lst["price"], pdp["price"])
                and discounts_equal(lst["discount"], pdp["discount"]))
        c["state"] = CLEARED if same else CONFIRMED

    def recheck_listing_seen(self, key, price, discount, found=True):
        c = self.comparisons.get(key)
        if c is None or c["state"] != RECHECKING:
            return
        c["recheck_listing"] = ({"price": price, "discount": discount} if found and price is not None
                                else {"excluded": MOVED})
        self._settle_recheck(c)

    def recheck_pdp_seen(self, key, item):
        c = self.comparisons.get(key)
        if c is None or c["state"] != RECHECKING:
            return
        if str(item.get("out_of_stock")).lower() == "true":
            c["recheck_pdp"] = {"excluded": SOLD_OUT}
        elif _num(item.get("price")) is None:
            c["recheck_pdp"] = {"excluded": NO_PRODUCT_DATA}
        else:
            c["recheck_pdp"] = {"price": item.get("price"), "discount": item.get("price_discount")}
        self._settle_recheck(c)

    def recheck_failed(self, key, part, access_error):
        """`part`: "listing" or "pdp"."""
        c = self.comparisons.get(key)
        if c is None or c["state"] != RECHECKING:
            return
        c[f"recheck_{part}"] = {"excluded": ACCESS if access_error else NO_PRODUCT_DATA}
        self._settle_recheck(c)

    # --- verdict --------------------------------------------------------------------

    def finish(self, hosts):
        """
        Verdict per hostname. Anything still waiting (page never came back) is
        excluded first. Own verdict with enough usable comparisons, or with any
        usable ones when none was lost to access; otherwise borrowed from the
        hostnames with their own verdict (one listing format across Ounass), or
        not checked when there are none.
        """
        for c in self.comparisons.values():
            if c["state"] in (WAITING, MISMATCH, RECHECKING):
                self._exclude(c, NO_PRODUCT_DATA)
        cfg = self.config
        hosts = sorted(set(hosts) | {c["host"] for c in self.comparisons.values()})
        verdicts = {}
        for host in hosts:
            mine = [c for c in self.comparisons.values() if c["host"] == host]
            states = [c["state"] for c in mine]
            excluded = {}
            for c in mine:
                if c["state"] == EXCLUDED:
                    excluded[c["reason"]] = excluded.get(c["reason"], 0) + 1
            confirmed = states.count(CONFIRMED)
            usable = states.count(AGREE) + states.count(CLEARED) + confirmed
            v = {
                "sampled": len(mine),
                "free": sum(1 for c in mine if c["source"] == FREE),
                "top_up": sum(1 for c in mine if c["source"] == TOP_UP),
                "on_sale": sum(1 for c in mine if c["listing"]["discount"]),
                "compared": usable, "agree": states.count(AGREE),
                "cleared_on_recheck": states.count(CLEARED), "confirmed": confirmed,
                "excluded": excluded, "label_differs": sum(1 for c in mine if c["label_differs"]),
                "verdict": None, "basis": None,
            }
            if usable >= cfg.parity_min_comparisons or (usable and not excluded.get(ACCESS)):
                failed = (confirmed >= cfg.parity_min_mismatches
                          and confirmed / usable >= cfg.parity_max_mismatch_ratio)
                v["verdict"], v["basis"] = (FAIL if failed else PASS), "own"
            verdicts[host] = v
        own = [v["verdict"] for v in verdicts.values() if v["basis"] == "own"]
        for v in verdicts.values():
            if v["basis"] is None:
                if own:
                    v["verdict"], v["basis"] = (FAIL if FAIL in own else PASS), "borrowed"
                else:
                    v["verdict"], v["basis"] = NOT_CHECKED, None
        self.verdicts = verdicts
        return verdicts

    def mismatch_examples(self, host):
        """Confirmed and cleared mismatches for the log, listing vs product page."""
        out = []
        for key, c in sorted(self.comparisons.items()):
            if c["host"] == host and c["state"] in (CONFIRMED, CLEARED):
                out.append({"portal_itemid": key[2], "state": c["state"], "listing": c["listing"],
                            "product_page": c["pdp"], "recheck_listing": c["recheck_listing"],
                            "recheck_product_page": c["recheck_pdp"]})
        return out[:MAX_LOGGED_MISMATCHES]
