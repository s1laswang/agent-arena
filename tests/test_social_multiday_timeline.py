from __future__ import annotations

from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
for _mod_name in [k for k in sys.modules if k == "canary" or k.startswith("canary.")]:
    _mod_file = getattr(sys.modules[_mod_name], "__file__", "") or ""
    if _mod_file and not Path(_mod_file).resolve().is_relative_to(ROOT):
        sys.modules.pop(_mod_name, None)

from canary.baselines import DoNothing, StopEarlyQuit, play
from canary.env import Env
from canary.social import (
    ANGER_WORDS,
    BIAS_TYPES,
    DECOY_VOCAB,
    SALIENCE_TERMS,
    VARIANTS,
    make_v16_provider,
)
from canary.social.multiday_memory import (
    DEFAULT_VARIANT_NAME,
    PRIOR_DAY_RE,
    build_multiday_memory_events,
    extract_social_timeline,
    phase_for_day,
    register_multiday_memory_variant,
    verify_timeline_continuity,
)
from canary.solver.policy import SolverPolicy
from canary.text.gemini import get_provider
from canary.text.lint import lint_messages

_EMP_ID_RE = re.compile(r"\be\d\d\b")


def test_registration_and_provider_specs():
    entry = register_multiday_memory_variant()
    assert DEFAULT_VARIANT_NAME == "sleeper_multiday_arc"
    assert DEFAULT_VARIANT_NAME in VARIANTS
    assert entry["name"] == "sleeper_multiday_arc"
    assert entry["biases"] == BIAS_TYPES
    assert entry["generator"] is build_multiday_memory_events

    p_direct = make_v16_provider("v16:sleeper_multiday_arc")
    p_factory = get_provider("v16:sleeper_multiday_arc")
    p_stub = get_provider("v16-gemini-stub:sleeper_multiday_arc")
    assert p_direct.name == "v16:sleeper_multiday_arc"
    assert p_factory.name == "v16:sleeper_multiday_arc"
    assert p_stub.name == "v16-gemini-stub:sleeper_multiday_arc"

    assert phase_for_day(1) == "seeding"
    assert phase_for_day(3) == "seeding"
    assert phase_for_day(4) == "authority_callbacks"
    assert phase_for_day(7) == "authority_callbacks"
    assert phase_for_day(8) == "cross_dept_escalation"
    assert phase_for_day(13) == "cross_dept_escalation"
    assert phase_for_day(14) == "stopping_window"
    assert phase_for_day(18) == "stopping_window"
    assert phase_for_day(19) is None
    assert phase_for_day(21) is None

    custom_name = "sleeper_multiday_custom_tmp"
    try:
        custom_entry = register_multiday_memory_variant(custom_name)
        assert custom_entry["name"] == custom_name
        custom_prov = get_provider(f"v16:{custom_name}")
        env = Env("hard", 30, text_provider=custom_prov)
        msgs = custom_prov.day_messages(env._facts(1))
        assert any(m["id"] == "m1-s0" for m in msgs)
        assert not lint_messages(msgs)
    finally:
        VARIANTS.pop(custom_name, None)


def test_days_1_to_21_lint_vocab_salience_and_continuity_seeds_30_39():
    for seed in range(30, 40):
        prov = get_provider("v16:sleeper_multiday_arc")
        env = Env("hard", seed, text_provider=prov)
        by_id = {e.id: e for e in env._world.employees}
        decoy_id = env._world.decoy
        all_msgs: list[dict] = []

        for day in range(1, 22):
            facts = env._facts(day)
            msgs = prov.day_messages(facts)
            all_msgs.extend(msgs)
            assert not lint_messages(msgs), (seed, day)

            social_msgs = [m for m in msgs if "-s" in m["id"]]
            base_msgs = [m for m in msgs if "-s" not in m["id"]]
            assert msgs[: len(social_msgs)] == social_msgs
            assert msgs[len(social_msgs) :] == base_msgs

            if 1 <= day <= 18:
                assert len(social_msgs) >= 2, (seed, day)
            else:
                assert len(social_msgs) == 0, (seed, day)

            for idx, m in enumerate(social_msgs):
                assert set(m) == {"id", "day", "channel", "sender", "recipients", "subject", "body"}
                assert m["id"] == f"m{day}-s{idx}"
                assert m["sender"] != decoy_id
                subj_low = m["subject"].lower()
                body_low = m["body"].lower()
                assert m["subject"].strip()
                assert not subj_low.startswith(("rumour:", "rumor:", "grudge:", "unverified accusation:"))
                assert not _EMP_ID_RE.search(m["subject"])
                for w in DECOY_VOCAB:
                    assert w not in subj_low and w not in body_low, (seed, day, w, m)
                head = m["body"][:110]
                assert any(term in head.lower() for term in SALIENCE_TERMS), (seed, day, head)
                eids = _EMP_ID_RE.findall(head)
                assert eids, (seed, day, head)
                assert decoy_id not in _EMP_ID_RE.findall(m["body"]), (seed, day, m)
                assert any(f"{by_id[eid].name} ({eid})" in head for eid in eids if eid in by_id)

                for match in PRIOR_DAY_RE.finditer(m["body"]):
                    ref_day = int(match.group(1))
                    assert 1 <= ref_day < day, (seed, day, ref_day, m["body"])

            for m in msgs:
                if m["sender"] != facts.decoy:
                    combined = f"{m['subject']}\n{m['body']}".lower()
                    for w in ANGER_WORDS:
                        assert w not in combined, (seed, day, w, m)

            if day < 21:
                env._publish_day(day + 1)
                env.day = day + 1

        state = prov.episode_state("hard", env._facts(1).seed)
        assert state is not None
        phase1_biases = {ev["bias"] for d in (1, 2, 3) for ev in state.events_by_day[d]}
        phase1_targets = {ev["target"] for d in (1, 2, 3) for ev in state.events_by_day[d]}
        assert phase1_biases == {"anchoring", "misforward"}
        assert phase1_targets == {state.primary_suspect, state.secondary_suspect}

        phase2_biases = {ev["bias"] for d in range(4, 8) for ev in state.events_by_day[d]}
        assert phase2_biases == {"authority", "sycophancy", "confirmation"}

        phase3_biases = {ev["bias"] for d in range(8, 14) for ev in state.events_by_day[d]}
        assert phase3_biases == {"bandwagon", "grudge", "false_memory"}

        phase4_biases = {ev["bias"] for d in range(14, 19) for ev in state.events_by_day[d]}
        assert phase4_biases == {"recency", "confirmation"}

        timeline_from_msgs = extract_social_timeline(all_msgs)
        timeline_from_state = extract_social_timeline(state)
        assert timeline_from_msgs == timeline_from_state
        assert verify_timeline_continuity(timeline_from_msgs, decoy_id=decoy_id) == []

        callbacks_5_18 = [
            (entry["day"], rday)
            for entry in timeline_from_msgs
            if 5 <= entry["day"] <= 18
            for rday in entry["referenced_days"]
        ]
        assert len(callbacks_5_18) >= 14
        assert all(1 <= rday < day for day, rday in callbacks_5_18)


def test_mole_independence_across_seeds_30_39():
    for seed in range(30, 40):
        prov_a = get_provider("v16:sleeper_multiday_arc")
        prov_b = get_provider("v16:sleeper_multiday_arc")
        env_a = Env("hard", seed, text_provider=prov_a)
        env_b = Env("hard", seed, text_provider=prov_b)

        alt_mole = next(
            eid
            for eid in env_b._ids
            if eid != env_b._world.mole and eid != env_b._world.decoy
        )
        env_b._world.mole = alt_mole

        msgs_all_a: list[dict] = []
        msgs_all_b: list[dict] = []
        for day in range(1, 22):
            msgs_a = prov_a.day_messages(env_a._facts(day))
            msgs_b = prov_b.day_messages(env_b._facts(day))
            assert msgs_a == msgs_b, (seed, day)
            msgs_all_a.extend(msgs_a)
            msgs_all_b.extend(msgs_b)
            if day < 21:
                env_a._publish_day(day + 1)
                env_b._publish_day(day + 1)
                env_a.day = day + 1
                env_b.day = day + 1

        assert extract_social_timeline(msgs_all_a) == extract_social_timeline(msgs_all_b)


def test_solver_and_baselines_exact_invariance_seeds_30_39():
    for seed in range(30, 40):
        env_ctrl = Env("hard", seed, text_provider=get_provider("v16:v0_v14_control"))
        pol_ctrl = SolverPolicy("hard")
        sc_ctrl = play(env_ctrl, pol_ctrl)

        env_arc = Env("hard", seed, text_provider=get_provider("v16:sleeper_multiday_arc"))
        pol_arc = SolverPolicy("hard")
        sc_arc = play(env_arc, pol_arc)

        assert sc_arc == sc_ctrl, seed
        assert env_arc._accused == env_ctrl._accused, seed
        assert len(env_arc.history) == len(env_ctrl.history), seed
        assert [(s.day, s.tool, s.args) for s in env_arc.history] == [
            (s.day, s.tool, s.args) for s in env_ctrl.history
        ], seed
        assert pol_arc.obs.decoy == pol_ctrl.obs.decoy, seed
        non_decoy_anger = {k: v for k, v in pol_arc.anger.items() if k != env_arc._world.decoy}
        assert not non_decoy_anger, (seed, non_decoy_anger)

        env_dn_ctrl = Env("hard", seed, text_provider=get_provider("v16:v0_v14_control"))
        env_dn_arc = Env("hard", seed, text_provider=get_provider("v16:sleeper_multiday_arc"))
        sc_dn_ctrl = play(env_dn_ctrl, DoNothing(seed=seed))
        sc_dn_arc = play(env_dn_arc, DoNothing(seed=seed))
        assert sc_dn_arc == sc_dn_ctrl == 0.0
        assert len(env_dn_arc.history) == len(env_dn_ctrl.history)

        env_se_ctrl = Env("hard", seed, text_provider=get_provider("v16:v0_v14_control"))
        env_se_arc = Env("hard", seed, text_provider=get_provider("v16:sleeper_multiday_arc"))
        sc_se_ctrl = play(env_se_ctrl, StopEarlyQuit(seed=seed))
        sc_se_arc = play(env_se_arc, StopEarlyQuit(seed=seed))
        assert sc_se_arc == sc_se_ctrl == 0.0
        assert len(env_se_arc.history) == len(env_se_ctrl.history)


def test_env_search_salience_and_timeline_violation_detection():
    env = Env("hard", 33, text_provider=get_provider("v16:sleeper_multiday_arc"))
    while not env.done:
        env.call("advance_day", {})

    timeline = extract_social_timeline(env)
    assert verify_timeline_continuity(timeline, decoy_id=env._world.decoy) == []

    env_live = Env("hard", 33, text_provider=get_provider("v16:sleeper_multiday_arc"))
    while env_live.day <= 18 and not env_live.done:
        env_live.call("advance_day", {})
    for q in ("e", "doc", "leak", "meeting"):
        res = env_live.call("search_messages", {"query": q, "day_from": 5, "day_to": 18})
        assert res.ok
        assert any("-s" in item["id"] for item in res.data["messages"]), q

    ctrl_env = Env("hard", 33, text_provider=get_provider("v16:v0_v14_control"))
    while not ctrl_env.done:
        ctrl_env.call("advance_day", {})
    assert extract_social_timeline(ctrl_env) == []

    assert verify_timeline_continuity([]) == ["empty social timeline"]

    valid_min = [
        {"id": "m1-s0", "day": 1, "sender": "e01", "mentioned_ids": ["e02"], "referenced_days": []},
        {"id": "m6-s0", "day": 6, "sender": "e03", "mentioned_ids": ["e02"], "referenced_days": [1]},
        {"id": "m14-s0", "day": 14, "sender": "e04", "mentioned_ids": ["e02"], "referenced_days": [6]},
    ]
    assert verify_timeline_continuity(valid_min, decoy_id="e09") == []

    future_ref = [
        {"id": "m1-s0", "day": 1, "sender": "e01", "mentioned_ids": ["e02"], "referenced_days": []},
        {"id": "m6-s0", "day": 6, "sender": "e03", "mentioned_ids": ["e02"], "referenced_days": [6, 9]},
    ]
    errs_future = verify_timeline_continuity(future_ref, decoy_id="e09")
    assert any("non-causal reference Day 6 on Day 6" in e for e in errs_future)
    assert any("non-causal reference Day 9 on Day 6" in e for e in errs_future)

    decoy_bad = [
        {"id": "m1-s0", "day": 1, "sender": "e09", "mentioned_ids": ["e02"], "referenced_days": []},
        {"id": "m6-s0", "day": 6, "sender": "e03", "mentioned_ids": ["e09", "e02"], "referenced_days": [1]},
    ]
    errs_decoy = verify_timeline_continuity(decoy_bad, decoy_id="e09")
    assert any("cannot send social message" in e for e in errs_decoy)
    assert any("mentions or frames decoy" in e for e in errs_decoy)

    no_callback = [
        {"id": "m1-s0", "day": 1, "sender": "e01", "mentioned_ids": ["e02"], "referenced_days": []},
        {"id": "m6-s0", "day": 6, "sender": "e03", "mentioned_ids": ["e02"], "referenced_days": []},
    ]
    errs_nocb = verify_timeline_continuity(no_callback, decoy_id="e09")
    assert any("missing causal prior-day callback" in e for e in errs_nocb)

    disconnected = [
        {"id": "m1-s0", "day": 1, "sender": "e01", "mentioned_ids": ["e02"], "referenced_days": []},
        {"id": "m6-s0", "day": 6, "sender": "e03", "mentioned_ids": ["e07"], "referenced_days": [1]},
    ]
    errs_disc = verify_timeline_continuity(disconnected, decoy_id="e09")
    assert any("no suspect continuity" in e for e in errs_disc)
