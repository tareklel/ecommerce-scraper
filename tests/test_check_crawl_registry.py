import json

import pytest

from scripts import check_crawl_registry as reg

REGISTRY_SHA = "d043b1442bf30a5a2662153a7e9c727405df0c1d"
CSV = (
    "url,site,country,language,gender,category,subcategory,brand,is_active\n"
    "https://saudi.ounass.com/api/women/bags/tote-bags,ounass,sa,ar,women,bags,tote_bags,,TRUE\n"
    "https://en-saudi.ounass.com/api/women/bags/tote-bags,ounass,sa,en,women,bags,tote_bags,,TRUE\n"
    "https://en-saudi.levelshoes.com/women/bags/tote-bags,level-shoes,sa,en,women,bags,tote_bags,,TRUE\n"
    "https://en.bloomingdales.sa/womens-bags-tote-bags/,bloomingdales,sa,en,women,bags,tote_bags,,FALSE\n"
)


def _fake(image_tags=("sha-d043b14", "latest"), compare="ahead", commits=None, csv_text=CSV):
    calls = []

    def run(args):
        calls.append(args)
        if args[:2] == ["aws", "ecr"]:
            return json.dumps(list(image_tags))
        path = args[2]
        if "/commits?" in path:
            return json.dumps([{"sha": REGISTRY_SHA}] if commits is None else commits)
        if "/compare/" in path:
            return compare + "\n"
        if "/contents/" in path:
            assert path.endswith("?ref=d043b14")
            return csv_text
        raise AssertionError(args)

    run.calls = calls
    return run


@pytest.mark.parametrize("status", ["ahead", "identical"])
def test_passes_and_lists_active_sites_when_the_image_has_the_registry(status):
    lines = []
    sites = reg.check(run=_fake(compare=status), out=lines.append)
    assert sites == {"ounass": 2, "level-shoes": 1}
    assert lines[0] == "dbt image sha-d043b14 has the latest registry (d043b14). Active sites:"
    assert lines[1:] == ["  level-shoes: 1 URL(s)", "  ounass: 2 URL(s)"]


@pytest.mark.parametrize("status", ["behind", "diverged"])
def test_refuses_when_the_image_predates_the_registry(status):
    with pytest.raises(reg.CheckFailed, match="wait for the dbt image build"):
        reg.check(run=_fake(image_tags=("latest", "sha-882fe8f"), compare=status), out=lambda _: None)


def test_compares_the_registry_commit_with_the_image_commit():
    run = _fake()
    reg.check(run=run, out=lambda _: None)
    compare = [a for a in run.calls if "/compare/" in a[2]][0]
    assert compare[2].endswith(f"/compare/{REGISTRY_SHA}...d043b14")


def test_refuses_an_image_without_a_sha_tag():
    with pytest.raises(reg.CheckFailed, match="no sha- tag"):
        reg.check(run=_fake(image_tags=("latest",)), out=lambda _: None)


def test_refuses_a_registry_with_no_active_rows():
    header = CSV.splitlines()[0] + "\n"
    with pytest.raises(reg.CheckFailed, match="no active rows"):
        reg.check(run=_fake(csv_text=header), out=lambda _: None)


def test_refuses_when_no_commit_touches_the_registry():
    with pytest.raises(reg.CheckFailed, match="no commit"):
        reg.check(run=_fake(commits=[]), out=lambda _: None)
