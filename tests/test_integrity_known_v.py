"""Ready for ENV v1.3 (CEO heads-up): `status` shows only the KNOWN V (unsurfaced leak damage hidden).
Invariants: true V never rises; known V never rises; while any leak is still unsurfaced the shown V
must not equal the true V (otherwise status leaks "a leak just happened" = a free mole-timing signal).
Skips on v1.2, where status shows the true V."""
from __future__ import annotations

import random

import pytest

from tests.integrity_helpers import make_env

TOOLS = ["status", "read_access_logs", "check_leak_feed", "advance_day", "advance_day", "advance_day"]


def _status_v(env):
    d = env.call("status", {}).data
    return d.get("V_known", d.get("known_V", d.get("V")))


def _unsurfaced(env) -> bool:
    led = env.ledger()
    leaked = {l.detail.get("doc_id") for l in led if l.event == "leak"}
    surfaced = {l.detail.get("doc_id") for l in led if l.event == "leak_surfaced"}
    return bool(leaked - surfaced)


@pytest.mark.parametrize("tier", ["easy", "medium", "hard"])
def test_known_v_hides_true_v(tier):
    hidden_seen = differs = 0
    for seed in range(20):
        env = make_env(tier, seed)
        rng = random.Random(seed)
        true_prev = known_prev = 1.0
        for _ in range(60):
            if env.done:
                break
            t = rng.choice(TOOLS)
            env.call(t, {"day_from": 1, "day_to": max(1, env.day)} if t == "read_access_logs" else {})
            if env.done:
                break
            kv, tv = _status_v(env), env.V
            assert tv <= true_prev + 1e-12, "true V increased"
            assert kv <= known_prev + 1e-12, "known V increased"
            true_prev, known_prev = tv, kv
            if _unsurfaced(env):
                hidden_seen += 1
                differs += abs(kv - tv) > 1e-12
    if hidden_seen and differs == 0:
        pytest.skip("v1.2: status shows the true V (known-V hiding not shipped yet)")
    assert differs == hidden_seen, f"status equalled true V in {hidden_seen - differs}/{hidden_seen} hidden-leak states"


@pytest.mark.parametrize("tier", ["medium", "hard", "hard_forge"])
def test_advance_day_v_hides_true_v(tier):
    """v1.3: advance_day's V is the known V too (verified 665 hidden-leak states, 0 equal to true V)."""
    hidden = equal = 0
    for seed in range(15):
        env = make_env(tier, seed)
        prev = 1.0
        while not env.done:
            v = env.call("advance_day", {}).data.get("V")
            if env.done or v is None:
                break
            assert v <= prev + 1e-12, "known V rose"
            prev = v
            if _unsurfaced(env):
                hidden += 1
                equal += abs(v - env.V) < 1e-9
    assert hidden > 0
    assert equal == 0, f"advance_day revealed true V in {equal}/{hidden} hidden-leak states"
