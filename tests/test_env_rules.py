from canary.rules import TIERS, apply_noise


def test_noise_identity_and_monotone():
    for t in TIERS.values():
        assert apply_noise(t, 1.0) == t
        n = apply_noise(t, 2.0)
        assert max(n.delay_choices) >= max(t.delay_choices)
        assert n.p_leak <= t.p_leak and 1 <= n.interview_lr <= t.interview_lr
        assert t.log_rate_benign <= n.log_rate_mole <= t.log_rate_mole
