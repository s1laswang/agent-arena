"""The research dataset is consistent and every live hazard family is grounded."""
from blindspot import failures, world


def test_cases_have_sources_and_ids_unique():
    cs = failures.cases()
    assert len(cs) >= 30
    for cid, c in cs.items():
        assert len(c["sources"]) >= 2, cid
        assert all(s["url"].startswith("http") for s in c["sources"]), cid
        assert c["category"] in {"accidental", "structural", "cultural", "external_fraud"}, cid


def test_every_family_maps_to_a_pattern_and_cases_exist():
    cs = failures.cases()
    for fam in world.FAMILIES:
        p = failures.pattern_for_family(fam)
        assert p is not None, fam
        assert p["id"] == world.HAZARD_META[fam]["pattern"], fam
        for cid in p["cases"]:
            assert cid in cs, (fam, cid)
    for p in failures.patterns():
        for cid in p["cases"]:
            assert cid in cs, (p["id"], cid)
