import hashlib, json
from canary.rules import TIERS, TIERS_VERSION


def test_tiers_v12_frozen():
    """Tiers v1.2 are frozen (CONTRACT §12). Changing them needs a new version + CEO sign-off."""
    h = hashlib.sha256(json.dumps({k: v.to_dict() for k, v in TIERS.items()}, sort_keys=True, default=list).encode()).hexdigest()[:16]
    assert TIERS_VERSION == "v1.2" and h == "59d8875fa5b98d0a"
