from canary.rules import TIERS, apply_noise


def test_noise_identity_and_monotone():
    for t in TIERS.values():
        assert apply_noise(t, 1.0) == t
        n = apply_noise(t, 2.0)
        assert max(n.delay_choices) >= max(t.delay_choices)
        assert n.p_leak <= t.p_leak and 1 <= n.interview_lr <= t.interview_lr
        assert t.log_rate_benign <= n.log_rate_mole <= t.log_rate_mole


def test_fingerprint_accuracy_flips_variants():
    import dataclasses
    from canary.env import Env
    wrong = total = 0
    for seed in range(60):
        env = Env("easy", seed)
        env.p = dataclasses.replace(env.p, fingerprint_accuracy=0.5)
        ids = [e["id"] for e in env.call("list_employees", {}).data["employees"]]
        mole = env._world.mole
        for d in range(6):
            env.call("plant_canary", {"doc_title": f"t{d}", "assignment": {e: ("A" if i % 2 else "B") for i, e in enumerate(ids)}})
            env.call("advance_day", {})
        lab = {e: ("A" if i % 2 else "B") for i, e in enumerate(ids)}[mole]
        for it in env.call("check_leak_feed", {}).data["items"]:
            if "variant" in it:
                total += 1; wrong += it["variant"] != lab
    assert total > 50 and 0.3 < wrong / total < 0.7
    assert "probability 0.5" in env.instruction()


def test_verdict_public():
    from canary.env import Env
    env = Env("easy", 3)
    v0 = env.verdict()
    assert v0["done"] is False and v0["accused"] is None and v0["score"] == 0.0 and v0["final_day"] == 1
    env.call("accuse", {"employee": env._world.mole})
    v = env.verdict()
    assert v["done"] and v["correct"] and v["accused"] == env._world.mole and v["score"] > 0 and v["end_reason"] == "accused"


def test_set_world_secret_first():
    import canary.world as W
    try:
        W.set_world_secret(b"x" * 32); a = W.world_seed("easy", 900_001)
        W.set_world_secret(b"y" * 32); b = W.world_seed("easy", 900_001)
        assert a != b and W.world_seed("easy", 7) == W.world_seed("easy", 7)
    finally:
        W.set_world_secret(None)
