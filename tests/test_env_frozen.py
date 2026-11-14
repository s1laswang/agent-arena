import hashlib, json
from canary import rules
from canary.rules import KNOWN_V_MODE, TIERS, TIERS_V13, TIERS_VERSION


def _hash(tiers=None):
    tiers = TIERS if tiers is None else tiers
    obj = {"tiers": {k: v.to_dict() for k, v in tiers.items()}, "known_v_mode": KNOWN_V_MODE}
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=list).encode()).hexdigest()[:16]


def test_tiers_v14_frozen():
    """Tiers v1.4 (TIERS + KNOWN_V_MODE) are frozen (CONTRACT §14). Changes need a new version + CEO sign-off."""
    assert TIERS_VERSION == "v1.4" and _hash() == "a8f99c2537c91d72"


def test_tiers_v13_history_frozen():
    """The v1.3 tiers stay reproducible: TIERS_V13 hashes to the v1.3 freeze (CONTRACT §13)."""
    assert _hash(TIERS_V13) == "8df71cf570bb48bc"
    assert TIERS_V13["easy"] == TIERS["easy"] and TIERS_V13["medium"] == TIERS["medium"]  # v1.4 changed only hard


def test_tiers_version_context_restores():
    before = dict(TIERS)
    with rules.tiers_version("v1.3"):
        assert rules.TIERS_VERSION == "v1.3" and rules.tier_params("hard").n_days == 14
        from canary.env import Env
        assert "lasts at most 14 days" in Env("hard", 0).instruction()
    assert rules.TIERS_VERSION == "v1.4" and TIERS == before and rules.tier_params("hard").n_days == 21
