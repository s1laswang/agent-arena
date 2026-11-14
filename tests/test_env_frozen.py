import hashlib, json
from canary.rules import KNOWN_V_MODE, TIERS, TIERS_VERSION


def _hash():
    obj = {"tiers": {k: v.to_dict() for k, v in TIERS.items()}, "known_v_mode": KNOWN_V_MODE}
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=list).encode()).hexdigest()[:16]


def test_tiers_v13_frozen():
    """Tiers v1.3 (TIERS + KNOWN_V_MODE) are frozen (CONTRACT §12-13). Changes need a new version + CEO sign-off."""
    assert TIERS_VERSION == "v1.3" and _hash() == "8df71cf570bb48bc"
