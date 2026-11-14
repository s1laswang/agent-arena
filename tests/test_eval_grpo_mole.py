from __future__ import annotations

import json
import random

from canary import rules
from canary.mole.dsl import MoleDoc, MoleView
from train.eval_grpo_mole import (
    GRPOMolePolicy,
    evaluate_mole_policy,
    parse_seeds,
    sanitize_peft_config_dict,
)


def test_sanitize_peft_config_strips_newer_peft_keys():
    verda_cfg = {
        "alora_invocation_tokens": None,
        "arrow_config": None,
        "base_model_name_or_path": "Qwen/Qwen2.5-1.5B-Instruct",
        "bias": "none",
        "corda_config": None,
        "kasa_config": None,
        "lora_alpha": 32,
        "lora_dropout": 0.0,
        "monteclora_config": None,
        "peft_type": "LORA",
        "peft_version": "0.21.3",
        "r": 16,
        "target_modules": ["q_proj", "k_proj", "v_proj", "o_proj"],
        "trainable_token_indices": None,
        "velora_config": None,
    }
    clean = sanitize_peft_config_dict(verda_cfg)
    assert clean["r"] == 16
    assert clean["lora_alpha"] == 32
    assert clean["target_modules"] == ["q_proj", "k_proj", "v_proj", "o_proj"]
    assert "alora_invocation_tokens" not in clean
    assert "kasa_config" not in clean
    assert "velora_config" not in clean
    try:
        from peft import LoraConfig
    except ImportError:
        return
    init_keys = {
        k: v
        for k, v in clean.items()
        if k not in {"peft_type", "base_model_name_or_path", "auto_mapping", "inference_mode"}
    }
    lcfg = LoraConfig(**init_keys)
    assert lcfg.r == 16


def test_parse_seeds():
    h = parse_seeds("heldout", 5)
    assert h == list(rules.HELDOUT_SEEDS)[:5]
    w = parse_seeds("ws3", 4)
    assert w == [200000, 200001, 200002, 200003]
    r = parse_seeds("800010-800015", 3)
    assert r == [800010, 800011, 800012]


def test_grpo_mole_policy_decide_memoize_and_fallback():
    pol = GRPOMolePolicy(
        None,
        None,
        "cpu",
        generate_fn=lambda _: '{"leak": "most_recipients", "frame": "decoy"}',
    )
    v = MoleView(
        day=2,
        docs=(
            MoleDoc("d1", "Doc A", 5, 1),
            MoleDoc("d2", "Doc B", 18, 0),
        ),
        days_since_last_leak=1,
        i_am_restricted=0,
        n_restricted_colleagues=0,
        recent_low_recipient_docs=0,
        peers=("e01", "e02"),
        restricted_peers=(),
        decoy="e02",
        can_leak=True,
    )
    mv1 = pol.decide(v, random.Random(0))
    mv2 = pol.decide(v, random.Random(0))
    assert mv1 == {"leak": "d2", "frame": "e02"}
    assert mv2 == mv1
    assert pol.calls == 1
    assert pol.invalid == 0

    bad_pol = GRPOMolePolicy(None, None, "cpu", generate_fn=lambda _: "not valid json")
    mv_bad = bad_pol.decide(v, random.Random(0))
    assert mv_bad["frame"] is None
    assert bad_pol.invalid == 1


def test_evaluate_mole_policy_end_to_end_easy():
    pol = GRPOMolePolicy(
        None,
        None,
        "cpu",
        generate_fn=lambda _: '{"leak": "most_recipients", "frame": "decoy"}',
    )
    rep = evaluate_mole_policy(
        pol,
        tier="easy",
        seeds=[800000, 800001],
        workers=1,
        min_solver_acc=0.5,
        rl_policy_path=None,
    )
    assert rep["n"] == 2
    assert "grpo_mole" in rep and "default_mole" in rep and "diff_grpo_minus_default" in rep
    assert 0.0 <= rep["grpo_mole"]["solver"]["acc"] <= 1.0
    assert rep["action_stats"]["distinct_actions"] == 1
    json.dumps(rep)
