from __future__ import annotations

import ast
from pathlib import Path
import re
import sys
import types

import pytest

from canary.baselines import DoNothing, StopEarlyQuit, play
from canary.env import Env
from canary.social import (
    ANGER_WORDS,
    AUTHORITY_ROLES,
    BIAS_TYPES,
    DECOY_VOCAB,
    SALIENCE_TERMS,
    VARIANTS,
    make_v16_provider,
    register_fr8_variant,
)
from canary.solver.policy import SolverPolicy
from canary.text.gemini import get_provider
from canary.text.lint import lint_messages
from canary.text.template import TemplateProvider

CORE_VARIANTS = (
    "v1_anchoring_authority_confirmation",
    "v2_recency_bandwagon_sycophancy",
    "v3_grudge_falsemem_misforward",
    "v4_triad_authority_recency_grudge",
    "v5_full9_cocktail",
)

_PRIOR_DAY_RE = re.compile(r"\bDay ([1-9]|1\d|20)\b")
_EMP_ID_RE = re.compile(r"\be\d\d\b")


def test_default_env_unchanged_and_v0_matches_template():
    env_default = Env("hard", 30)
    env_control = Env("hard", 30, text_provider=get_provider("v16:v0_v14_control"))
    assert env_default.provider.name == "template"
    assert env_control.provider.name == "v16:v0_v14_control"
    while not env_default.done:
        r1 = env_default.call("advance_day", {})
        r2 = env_control.call("advance_day", {})
        assert r1 == r2
    assert env_default._msg_order == env_control._msg_order
    assert env_default._messages == env_control._messages
    assert not any("-s" in mid for mid in env_default._msg_order)


def test_mole_independence_across_21_days():
    prov_a = get_provider("v16:v5_full9_cocktail")
    prov_b = get_provider("v16:v5_full9_cocktail")
    env_a = Env("hard", 30, text_provider=prov_a)
    env_b = Env("hard", 30, text_provider=prov_b)

    alt_mole = next(
        eid
        for eid in env_b._ids
        if eid != env_b._world.mole and eid != env_b._world.decoy
    )
    env_b._world.mole = alt_mole

    for day in range(1, 22):
        msgs_a = prov_a.day_messages(env_a._facts(day))
        msgs_b = prov_b.day_messages(env_b._facts(day))
        assert msgs_a == msgs_b
        if day < 21:
            env_a._publish_day(day + 1)
            env_b._publish_day(day + 1)
            env_a.day = day + 1
            env_b.day = day + 1

    day1_facts = env_a._facts(1)
    st_a = prov_a.episode_state("hard", day1_facts.seed)
    st_b = prov_b.episode_state("hard", day1_facts.seed)
    assert st_a is not None and st_b is not None
    assert st_a.primary_suspect == st_b.primary_suspect
    assert st_a.secondary_suspect == st_b.secondary_suspect
    assert st_a.primary_suspect != env_a._world.decoy
    assert st_a.secondary_suspect != env_a._world.decoy
    assert st_a.primary_suspect != st_a.secondary_suspect

    by_id = {e.id: e for e in day1_facts.employees}
    r0 = set(day1_facts.docs[0]["recipients"]) - {day1_facts.decoy}
    r1 = set(day1_facts.docs[1]["recipients"]) - {day1_facts.decoy}
    if r0 & r1:
        assert st_a.primary_suspect in (r0 & r1)
    for auth_id in st_a.authority_speakers:
        assert any(tok in by_id[auth_id].role.lower() for tok in AUTHORITY_ROLES)
    assert len(st_a.grudge_pairs) == 2
    for sp_id, tg_id in st_a.grudge_pairs:
        assert sp_id != day1_facts.decoy and tg_id != day1_facts.decoy


def test_lint_decoy_vocab_and_salience_across_seeds_30_49():
    for variant in CORE_VARIANTS:
        prov = get_provider(f"v16:{variant}")
        for seed in range(30, 50):
            env = Env("hard", seed, text_provider=prov)
            by_id = {e.id: e for e in env._world.employees}
            for day in range(1, 22):
                facts = env._facts(day)
                msgs = prov.day_messages(facts)
                assert not lint_messages(msgs), (variant, seed, day)

                social_msgs = [m for m in msgs if "-s" in m["id"]]
                base_msgs = [m for m in msgs if "-s" not in m["id"]]
                assert msgs[: len(social_msgs)] == social_msgs
                assert msgs[len(social_msgs) :] == base_msgs

                if day == 1:
                    assert len(social_msgs) >= 1

                for idx, m in enumerate(social_msgs):
                    assert set(m) == {"id", "day", "channel", "sender", "recipients", "subject", "body"}
                    assert m["id"] == f"m{day}-s{idx}"
                    subj_low = m["subject"].lower()
                    body_low = m["body"].lower()
                    assert m["subject"].strip()
                    assert not subj_low.startswith(("rumour:", "rumor:", "grudge:", "unverified accusation:"))
                    assert not _EMP_ID_RE.search(m["subject"])
                    for w in DECOY_VOCAB:
                        assert w not in subj_low and w not in body_low, (variant, seed, day, w, m)
                    head = m["body"][:110]
                    assert any(term in head.lower() for term in SALIENCE_TERMS), (variant, seed, day, head)
                    eids = _EMP_ID_RE.findall(head)
                    assert eids, (variant, seed, day, head)
                    assert any(f"{by_id[eid].name} ({eid})" in head for eid in eids if eid in by_id)

                for m in msgs:
                    if m["sender"] != facts.decoy:
                        combined = f"{m['subject']}\n{m['body']}".lower()
                        for w in ANGER_WORDS:
                            assert w not in combined, (variant, seed, day, w, m)

                if day < 21:
                    env._publish_day(day + 1)
                    env.day = day + 1


def test_multiday_memory_and_search_salience():
    for variant in CORE_VARIANTS:
        env = Env("hard", 33, text_provider=get_provider(f"v16:{variant}"))
        env.call("advance_day", {})
        day1_search = env.call("search_messages", {"query": "e"})
        assert day1_search.ok
        day1_hits = day1_search.data["messages"]
        assert day1_hits and day1_hits[0]["id"].startswith("m1-s")

        while env.day <= 14 and not env.done:
            env.call("advance_day", {})

        mid_social = [
            m
            for m in env._messages.values()
            if "-s" in m["id"] and 5 <= m["day"] <= 14
        ]
        assert len(mid_social) >= 4
        prior_refs = []
        for m in mid_social:
            for match in _PRIOR_DAY_RE.finditer(m["body"]):
                ref_day = int(match.group(1))
                if ref_day < m["day"]:
                    prior_refs.append((m["day"], ref_day))
        assert prior_refs, variant

        for q in ("e", "doc", "leak", "meeting"):
            res = env.call("search_messages", {"query": q, "day_from": 5, "day_to": 14})
            assert res.ok
            assert any("-s" in item["id"] for item in res.data["messages"]), (variant, q)


def test_solver_calibration_and_baselines_on_seeds_30_39():
    control_outcomes: dict[int, tuple[float, str | None, int, str | None]] = {}
    for seed in range(30, 40):
        env_ctrl = Env("hard", seed, text_provider=get_provider("v16:v0_v14_control"))
        pol_ctrl = SolverPolicy("hard")
        sc_ctrl = play(env_ctrl, pol_ctrl)
        assert pol_ctrl.obs.decoy in (None, env_ctrl._world.decoy)
        control_outcomes[seed] = (sc_ctrl, env_ctrl._accused, len(env_ctrl.history), pol_ctrl.obs.decoy)

        env_dn = Env("hard", seed, text_provider=get_provider("v16:v5_full9_cocktail"))
        assert play(env_dn, DoNothing(seed=seed)) == 0.0

        env_se = Env("hard", seed, text_provider=get_provider("v16:v5_full9_cocktail"))
        assert play(env_se, StopEarlyQuit(seed=seed)) == 0.0

    for variant in CORE_VARIANTS:
        for seed in range(30, 40):
            env = Env("hard", seed, text_provider=get_provider(f"v16:{variant}"))
            pol = SolverPolicy("hard")
            sc = play(env, pol)
            assert pol.obs.decoy in (None, env._world.decoy)
            non_decoy_anger = {k: v for k, v in pol.anger.items() if k != env._world.decoy}
            assert not non_decoy_anger, (variant, seed, non_decoy_anger)
            got = (sc, env._accused, len(env.history), pol.obs.decoy)
            assert got == control_outcomes[seed], (variant, seed, got, control_outcomes[seed])


def test_all_9_single_bias_variants_and_fr8_adapter():
    assert len(BIAS_TYPES) == 9
    for bias in BIAS_TYPES:
        vname = f"b_{bias}"
        assert vname in VARIANTS
        prov = get_provider(f"v16:{vname}")
        env = Env("hard", 30, text_provider=prov)
        for day in range(1, 7):
            msgs = prov.day_messages(env._facts(day))
            assert not lint_messages(msgs)
            assert any("-s" in m["id"] for m in msgs)
            env._publish_day(day + 1)
            env.day = day + 1

    custom_name = "fr8_test_combo_tmp"
    try:
        entry = register_fr8_variant(
            custom_name,
            {"biases": ["authority", "anchoring"], "days": [1, 2, 3], "per_day": 1},
        )
        assert entry["name"] == custom_name
        prov = make_v16_provider(f"v16:{custom_name}")
        env = Env("hard", 31, text_provider=prov)
        msgs = prov.day_messages(env._facts(1))
        assert any(m["id"] == "m1-s0" for m in msgs)
        assert not lint_messages(msgs)
    finally:
        VARIANTS.pop(custom_name, None)


def test_gemini_chatter_dispatch_fallback_and_item_reject(monkeypatch):
    monkeypatch.setitem(sys.modules, "canary.social.gemini_chatter", None)
    p_gem = get_provider("v16-gemini:v1_anchoring_authority_confirmation")
    p_stub = get_provider("v16-gemini-stub:v1_anchoring_authority_confirmation")
    p_tpl = get_provider("v16:v1_anchoring_authority_confirmation")
    assert p_gem.name == "v16-gemini:v1_anchoring_authority_confirmation"
    assert p_stub.name == "v16-gemini-stub:v1_anchoring_authority_confirmation"

    env = Env("hard", 30)
    f1 = env._facts(1)
    assert p_stub.day_messages(f1) == p_tpl.day_messages(f1)

    calls: list[bool] = []
    fake_mod = types.ModuleType("canary.social.gemini_chatter")

    def fake_render(facts, social_msgs, stub=False, **_kw):
        calls.append(stub)
        out = []
        for idx, m in enumerate(social_msgs):
            if idx == 0:
                m_emp = _EMP_ID_RE.search(m["body"]).group(0)
                emp_obj = next(e for e in facts.employees if e.id == m_emp)
                out.append(
                    dict(
                        m,
                        body=f"Meeting leak note on {emp_obj.name} ({emp_obj.id}): custom Gemini rewrite passed.",
                    )
                )
            else:
                out.append(dict(m, body="I think the mole wants a raise."))
        return out

    fake_mod.render_with_gemini = fake_render
    monkeypatch.setitem(sys.modules, "canary.social.gemini_chatter", fake_mod)

    p_stub2 = get_provider("v16-gemini-stub:v1_anchoring_authority_confirmation")
    rendered = p_stub2.day_messages(f1)
    tpl_msgs = get_provider("v16:v1_anchoring_authority_confirmation").day_messages(f1)
    assert calls == [True]
    assert "custom Gemini rewrite passed." in rendered[0]["body"]
    assert rendered[1] == tpl_msgs[1]
    assert p_stub2.rejects == 1
    assert not lint_messages(rendered)

    with pytest.raises(ValueError):
        get_provider("v16:unknown_variant_xyz")


def test_static_mole_blindness_in_social_package():
    social_dir = Path(__file__).resolve().parents[1] / "canary" / "social"
    for py_file in sorted(social_dir.glob("*.py")):
        tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute):
                assert node.attr not in ("_world", "mole"), (py_file.name, node.attr)
            elif isinstance(node, ast.ImportFrom) and node.module:
                assert "world" not in node.module, (py_file.name, node.module)

