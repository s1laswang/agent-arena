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
