from __future__ import annotations

import ast
import io
import json
from pathlib import Path
import random
import re
import sys
import tokenize

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
for _mod_name in [k for k in sys.modules if k == "canary" or k.startswith("canary.")]:
    _mod_file = getattr(sys.modules[_mod_name], "__file__", "") or ""
    if _mod_file and not Path(_mod_file).resolve().is_relative_to(ROOT):
        sys.modules.pop(_mod_name, None)

from canary.baselines import BASELINES, DoNothing, StopEarlyQuit, play
from canary.env import Env
from canary.social import (
    ANGER_WORDS,
    BIAS_TYPES,
    DECOY_VOCAB,
    SALIENCE_TERMS,
    SocialDayContext,
    VARIANTS,
    make_v16_provider,
    validate_social_message,
)
from canary.social.gemini_chatter import SOCIAL_SCHEMA, SOCIAL_SYSTEM, build_social_prompt
import canary.social.horizon_escalation as horizon_escalation
from canary.social.horizon_escalation import (
    DEFAULT_VARIANT_NAME,
    HORIZON_DAYS,
    HORIZON_DAY_REF_RE,
    HORIZON_ESCALATION_SCHEDULE,
    HORIZON_PHASES,
    build_horizon_escalation_events,
    horizon_phase_for_day,
    register_horizon_escalation_variant,
    summarize_horizon_metrics,
    verify_horizon_continuity,
)
from canary.social.multiday_memory import extract_social_timeline, verify_timeline_continuity
from canary.solver.policy import SolverPolicy
from canary.text.facts import EmployeeFacts, PublicDayFacts
from canary.text.gemini import get_provider
from canary.text.lint import lint_messages
from canary.text.llm_cache import cached_chat

_EMP_ID_RE = re.compile(r"\be\d\d\b")


def _run_horizon(prov, tier: str = "hard", seed: int = 0) -> tuple[Env, dict[int, list[dict]], int]:
    env = Env(tier, seed, text_provider=prov)
    facts_seed = env._facts(1).seed
    by_day: dict[int, list[dict]] = {}
    for day in range(1, env.p.n_days + 1):
        by_day[day] = prov.day_messages(env._facts(day))
        if day < env.p.n_days:
            env._publish_day(day + 1)
            env.day = day + 1
    return env, by_day, facts_seed


def test_registration_and_opt_in_provider_specs():
    entry = register_horizon_escalation_variant()
    assert DEFAULT_VARIANT_NAME == "v6_horizon_escalation"
    assert HORIZON_DAYS == 21
    assert "v6_horizon_escalation" in VARIANTS
    assert VARIANTS["v6_horizon_escalation"] is entry
    assert entry["name"] == "v6_horizon_escalation"
    assert entry["control"] is False
    assert entry["biases"] == BIAS_TYPES
    assert entry["generator"] is build_horizon_escalation_events
    assert entry["runner"] is build_horizon_escalation_events
    assert set(HORIZON_ESCALATION_SCHEDULE) == set(range(1, 22))

    assert horizon_phase_for_day(1) == "seeding"
    assert horizon_phase_for_day(3) == "seeding"
    assert horizon_phase_for_day(4) == "authority_callbacks"
    assert horizon_phase_for_day(7) == "authority_callbacks"
    assert horizon_phase_for_day(8) == "cross_dept_escalation"
    assert horizon_phase_for_day(13) == "cross_dept_escalation"
    assert horizon_phase_for_day(14) == "mid_horizon_pressure"
    assert horizon_phase_for_day(18) == "mid_horizon_pressure"
    assert horizon_phase_for_day(19) == "late_stopping_window"
    assert horizon_phase_for_day(21) == "late_stopping_window"
    assert horizon_phase_for_day(0) is None
    assert horizon_phase_for_day(22) is None

    p_tpl = get_provider("v16:v6_horizon_escalation")
    p_direct = make_v16_provider("v16:v6_horizon_escalation")
    p_stub = get_provider("v16-gemini-stub:v6_horizon_escalation")
    p_social_v2 = get_provider("social-v2-template:v6_horizon_escalation")
    assert p_tpl.name == "v16:v6_horizon_escalation"
    assert p_direct.name == "v16:v6_horizon_escalation"
    assert p_stub.name == "v16-gemini-stub:v6_horizon_escalation"
    assert p_social_v2.name == "social-v2:v6_horizon_escalation"

    assert get_provider("v16").variant == "v5_full9_cocktail"
    assert get_provider("social-v2").variant == "v5_full9_cocktail"

    custom_name = "v6_horizon_escalation_custom_tmp"
    try:
        custom_entry = register_horizon_escalation_variant(custom_name)
        assert custom_entry["name"] == custom_name
        assert custom_entry["runner"] is build_horizon_escalation_events
        custom_prov = get_provider(f"v16:{custom_name}")
        env = Env("hard", 0, text_provider=custom_prov)
        msgs = custom_prov.day_messages(env._facts(1))
        assert any(m["id"] == "m1-s0" for m in msgs)
        assert not lint_messages(msgs)
    finally:
        VARIANTS.pop(custom_name, None)


def test_full_days_1_to_21_continuity_callbacks_and_escalation_seeds_0_to_9():
    for seed in range(0, 10):
        prov_1 = get_provider("v16:v6_horizon_escalation")
        prov_2 = get_provider("v16:v6_horizon_escalation")
        env_1, by_day_1, fseed_1 = _run_horizon(prov_1, "hard", seed)
        _, by_day_2, fseed_2 = _run_horizon(prov_2, "hard", seed)
        assert fseed_1 == fseed_2
        assert by_day_1 == by_day_2

        by_id = {e.id: e for e in env_1._world.employees}
        decoy_id = env_1._world.decoy
        all_msgs: list[dict] = []

        for day in range(1, 22):
            msgs = by_day_1[day]
            all_msgs.extend(msgs)
            assert lint_messages(msgs) == [], (seed, day)

            social_msgs = [m for m in msgs if "-s" in m["id"]]
            base_msgs = [m for m in msgs if "-s" not in m["id"]]
            assert msgs[: len(social_msgs)] == social_msgs
            assert msgs[len(social_msgs) :] == base_msgs
            assert len(social_msgs) == 3, (seed, day)

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
                assert any(f"{by_id[eid].name[:28].rstrip()} ({eid})" in head for eid in eids if eid in by_id)

                refs = [int(x.group(1)) for x in HORIZON_DAY_REF_RE.finditer(m["body"])]
                if day == 1:
                    assert refs == [], (seed, m["body"])
                for ref_d in refs:
                    assert 1 <= ref_d < day, (seed, day, ref_d, m["body"])

            for m in msgs:
                if m["sender"] != decoy_id:
                    combined = f"{m['subject']}\n{m['body']}".lower()
                    for w in ANGER_WORDS:
                        assert w not in combined, (seed, day, w, m)

        state = prov_1.episode_state("hard", fseed_1)
        assert state is not None
        assert verify_horizon_continuity(state.events_by_day, decoy_id=decoy_id) == [], seed

        timeline = extract_social_timeline(all_msgs)
        assert timeline == extract_social_timeline(state)
        assert verify_timeline_continuity(timeline, decoy_id=decoy_id) == [], seed

        metrics = summarize_horizon_metrics(state.events_by_day)
        assert metrics["total_messages"] == 63
        assert metrics["phase_messages"] == {
            "seeding": 9,
            "authority_callbacks": 12,
            "cross_dept_escalation": 18,
            "mid_horizon_pressure": 15,
            "late_stopping_window": 9,
        }
        assert metrics["phase_callbacks"]["late_stopping_window"] == 9
        assert metrics["post_day1_callbacks"] == 58
        assert metrics["post_day1_messages"] == 60
        assert metrics["two_digit_callbacks"] >= 20
        assert metrics["max_callback_span_days"] == 20
        assert metrics["cross_dept_bandwagon"] == 8
        assert metrics["distinct_speaker_depts"] >= 3

        pair_0, pair_1 = state.grudge_pairs
        assert pair_0 != pair_1
        assert metrics["grudge_max_by_pair"][pair_0] == 6
        assert metrics["grudge_max_by_pair"][pair_1] == 6

        for day in (3, 14, 21):
            anch_evs = [ev for ev in state.events_by_day[day] if ev["bias"] == "anchoring"]
            assert anch_evs and anch_evs[0]["ref_day"] == 1
            assert "Day 1" in anch_evs[0]["body"]


def test_late_window_days_19_to_21_search_coverage_and_grudge_stages():
    env_v5 = Env("hard", 2, text_provider=get_provider("v16:v5_full9_cocktail"))
    while not env_v5.done:
        env_v5.call("advance_day", {})
    v5_late_social = [m for m in env_v5._messages.values() if "-s" in m["id"] and m["day"] >= 19]
    assert v5_late_social == []

    prov_v5 = env_v5.provider
    st_v5 = prov_v5.episode_state("hard", env_v5._facts(1).seed)
    assert st_v5 is not None
    v5_errs = verify_horizon_continuity(st_v5.events_by_day, decoy_id=env_v5._world.decoy)
    assert any("Day 19: missing social events" in e for e in v5_errs)
    assert any("Day 20: missing social events" in e for e in v5_errs)
    assert any("Day 21: missing social events" in e for e in v5_errs)

    prov_v6 = get_provider("v16:v6_horizon_escalation")
    env_v6 = Env("hard", 2, text_provider=prov_v6)
    while env_v6.day < 21 and not env_v6.done:
        env_v6.call("advance_day", {})
    assert env_v6.day == 21 and not env_v6.done

    for query in ("e", "doc", "leak", "meeting"):
        res = env_v6.call("search_messages", {"query": query, "day_from": 19, "day_to": 20})
        assert res.ok
        hits = res.data["messages"]
        assert any(item["id"].startswith("m19-s") for item in hits), query
        assert any(item["id"].startswith("m20-s") for item in hits), query

    env_v6.call("advance_day", {})
    assert env_v6.done
    for late_day in (19, 20, 21):
        day_social = [m for m in env_v6._messages.values() if m["day"] == late_day and "-s" in m["id"]]
        assert len(day_social) == 3

    st_v6 = prov_v6.episode_state("hard", env_v6._facts(1).seed)
    assert st_v6 is not None
    p0, p1 = st_v6.grudge_pairs
    stages_by_pair: dict[tuple[str, str], list[tuple[int, str, int | None]]] = {p0: [], p1: []}
    for day in range(1, 22):
        for ev in st_v6.events_by_day[day]:
            if ev["bias"] == "grudge":
                pair = (ev["sender"], ev["target"])
                stages_by_pair[pair].append((ev["grudge_count"], ev["grudge_stage"], ev["ref_day"]))

    for pair, seq in stages_by_pair.items():
        assert [x[0] for x in seq] == [1, 2, 3, 4, 5, 6]
        assert [x[1] for x in seq] == [
            "initial_dispute",
            "second_clash",
            "ongoing_feud",
            "sustained_escalation",
            "sustained_escalation",
            "sustained_escalation",
        ]
        assert seq[0][2] is None
        assert all(ref is not None for _, _, ref in seq[1:])


def test_counterfactual_mole_swap_identity_and_static_hygiene():
    for seed in range(0, 10):
        prov_a = get_provider("v16:v6_horizon_escalation")
        prov_b = get_provider("v16:v6_horizon_escalation")
        env_a = Env("hard", seed, text_provider=prov_a)
        env_b = Env("hard", seed, text_provider=prov_b)

        alt_mole = next(
            eid
            for eid in env_b._ids
            if eid != env_b._world.mole and eid != env_b._world.decoy
        )
        env_b._world.mole = alt_mole

        for day in range(1, 22):
            msgs_a = prov_a.day_messages(env_a._facts(day))
            msgs_b = prov_b.day_messages(env_b._facts(day))
            assert msgs_a == msgs_b, (seed, day)
            if day < 21:
                env_a._publish_day(day + 1)
                env_b._publish_day(day + 1)
                env_a.day = day + 1
                env_b.day = day + 1

        fseed = env_a._facts(1).seed
        st_a = prov_a.episode_state("hard", fseed)
        st_b = prov_b.episode_state("hard", fseed)
        assert st_a is not None and st_b is not None
        assert st_a.events_by_day == st_b.events_by_day

    mod_path = Path(horizon_escalation.__file__).resolve()
    test_path = Path(__file__).resolve()
    report_path = ROOT / "docs" / "reports" / "v16_horizon_escalation.md"
    assert report_path.is_file()

    mod_src = mod_path.read_text(encoding="utf-8")
    tree = ast.parse(mod_src, filename=str(mod_path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            assert node.attr not in ("_world", "mole")
        elif isinstance(node, ast.ImportFrom) and node.module:
            assert "world" not in node.module
    assert "mole" not in mod_src.lower()

    for py_path in (mod_path, test_path):
        src = py_path.read_text(encoding="utf-8")
        tokens = list(tokenize.generate_tokens(io.StringIO(src).readline))
        comment_tokens = [tok for tok in tokens if tok.type == tokenize.COMMENT]
        assert not comment_tokens, (py_path.name, comment_tokens)

    for path in (mod_path, test_path, report_path):
        txt = path.read_text(encoding="utf-8")
        assert "\u2014" not in txt and "\u2013" not in txt, path.name


def test_solver_do_nothing_and_stop_early_exact_invariance_seeds_0_to_9():
    assert BASELINES["do_nothing"] is DoNothing
    assert BASELINES["stop_early"] is StopEarlyQuit

    ctrl_scores: list[float] = []
    v6_scores: list[float] = []

    for seed in range(0, 10):
        env_ctrl = Env("hard", seed, text_provider=get_provider("v16:v0_v14_control"))
        pol_ctrl = SolverPolicy("hard")
        sc_ctrl = play(env_ctrl, pol_ctrl)
        ctrl_scores.append(sc_ctrl)

        env_v6 = Env("hard", seed, text_provider=get_provider("v16:v6_horizon_escalation"))
        pol_v6 = SolverPolicy("hard")
        sc_v6 = play(env_v6, pol_v6)
        v6_scores.append(sc_v6)

        assert sc_v6 == sc_ctrl, seed
        assert env_v6._accused == env_ctrl._accused, seed
        assert len(env_v6.history) == len(env_ctrl.history), seed
        assert [(s.day, s.tool, s.args) for s in env_v6.history] == [
            (s.day, s.tool, s.args) for s in env_ctrl.history
        ], seed
        assert pol_v6.obs.decoy == pol_ctrl.obs.decoy, seed
        non_decoy_anger = {k: v for k, v in pol_v6.anger.items() if k != env_v6._world.decoy}
        assert not non_decoy_anger, (seed, non_decoy_anger)

        env_dn_ctrl = Env("hard", seed, text_provider=get_provider("v16:v0_v14_control"))
        env_dn_v6 = Env("hard", seed, text_provider=get_provider("v16:v6_horizon_escalation"))
        sc_dn_ctrl = play(env_dn_ctrl, DoNothing(seed=seed))
        sc_dn_v6 = play(env_dn_v6, DoNothing(seed=seed))
        assert sc_dn_v6 == sc_dn_ctrl == 0.0
        assert [(s.day, s.tool, s.args) for s in env_dn_v6.history] == [
            (s.day, s.tool, s.args) for s in env_dn_ctrl.history
        ]

        env_se_ctrl = Env("hard", seed, text_provider=get_provider("v16:v0_v14_control"))
        env_se_v6 = Env("hard", seed, text_provider=get_provider("v16:v6_horizon_escalation"))
        sc_se_ctrl = play(env_se_ctrl, StopEarlyQuit(seed=seed))
        sc_se_v6 = play(env_se_v6, StopEarlyQuit(seed=seed))
        assert sc_se_v6 == sc_se_ctrl == 0.0
        assert [(s.day, s.tool, s.args) for s in env_se_v6.history] == [
            (s.day, s.tool, s.args) for s in env_se_ctrl.history
        ]

    assert round(sum(ctrl_scores) / len(ctrl_scores), 3) == 0.576
    assert round(sum(v6_scores) / len(v6_scores), 3) == 0.576


def test_v5_full9_cocktail_offline_gemini_cache_100_percent_hit_regression(monkeypatch):
    assert "v6_horizon_escalation" in VARIANTS
    monkeypatch.setenv("CANARY_OFFLINE", "1")
    cache_dir = ROOT / "data" / "gemini_cache"
    assert cache_dir.is_dir()

    class _NoNetworkClient:
        def chat(self, *args, **kwargs):
            raise AssertionError("unexpected live LLM call during offline cache regression test")

    total_cached_days = 0
    for seed in (0, 1, 2):
        prov_gem = get_provider(
            "v16-gemini:v5_full9_cocktail",
            cache_dir=str(cache_dir),
            client=_NoNetworkClient(),
        )
        prov_tpl = get_provider("v16:v5_full9_cocktail")
        env = Env("hard", seed, text_provider=prov_gem)

        seed_hits = 0
        for day in range(1, 22):
            facts = env._facts(day)
            msgs_tpl = prov_tpl.day_messages(facts)
            social_tpl = [m for m in msgs_tpl if "-s" in m["id"]]

            if social_tpl:
                state_tpl = prov_tpl.episode_state("hard", facts.seed)
                assert state_tpl is not None
                raw_evs = state_tpl.events_by_day[day]
                prompt_items = []
                for idx, m in enumerate(social_tpl):
                    item = dict(m)
                    if idx < len(raw_evs):
                        item["target"] = str(raw_evs[idx]["target"])
                        item["meta"] = {
                            "bias": str(raw_evs[idx]["bias"]),
                            "target": str(raw_evs[idx]["target"]),
                        }
                    prompt_items.append(item)
                prompt = build_social_prompt(facts, prompt_items)
                cached_entry = cached_chat(
                    cache_dir,
                    _NoNetworkClient(),
                    "gemini-4-carbon",
                    SOCIAL_SYSTEM,
                    prompt,
                    response_schema=SOCIAL_SCHEMA,
                    label="REAL",
                )
                assert cached_entry["provenance"]["label"] == "REAL"
                parsed = json.loads(cached_entry["text"])
                assert len(parsed["bodies"]) == len(social_tpl)
                seed_hits += 1
                total_cached_days += 1

            msgs_gem = prov_gem.day_messages(facts)
            assert lint_messages(msgs_gem) == []
            social_gem = [m for m in msgs_gem if "-s" in m["id"]]
            assert len(social_gem) == len(social_tpl)
            if social_tpl:
                assert any(a["body"] != b["body"] for a, b in zip(social_gem, social_tpl)), (seed, day)

            if day < 21:
                env._publish_day(day + 1)
                env.day = day + 1

        assert seed_hits == 18, seed
        assert prov_gem.rejects == 0, seed

    assert total_cached_days == 54


def test_long_names_stub_mode_tiers_and_verifier_edge_cases(monkeypatch, tmp_path):
    long_emps = tuple(
        EmployeeFacts(
            id=f"e{i:02d}",
            name=f"Aleksanteri-Maximilian Virtanen-Karjalainen {i}",
            dept=f"Cross-Platform Dept {i % 4}",
            role="senior compliance lead" if i < 3 else "principal systems engineer",
            clearance=3,
        )
        for i in range(12)
    )
    valid_ids = {e.id for e in long_emps}
    by_id = {e.id: e for e in long_emps}
    prov_long = get_provider("v16:v6_horizon_escalation")
    for day in range(1, 22):
        docs = (
            {
                "doc_id": f"d{day}-0",
                "title": f"Day {day} Security Architecture Review Packet",
                "day": day,
                "recipients": [f"e{i:02d}" for i in range(1, 7)],
            },
            {
                "doc_id": f"d{day}-1",
                "title": f"Day {day} Operations Audit Summary",
                "day": day,
                "recipients": [f"e{i:02d}" for i in range(3, 9)],
            },
        )
        facts = PublicDayFacts(
            tier="hard",
            seed=777,
            day=day,
            company="Borealis Dynamics",
            employees=long_emps,
            docs=docs,
            decoy="e00",
            decoy_mood="angry",
        )
        msgs = prov_long.day_messages(facts)
        social_msgs = [m for m in msgs if "-s" in m["id"]]
        assert len(social_msgs) == 3
        st_long = prov_long.episode_state("hard", 777)
        assert st_long is not None
        for m, ev in zip(social_msgs, st_long.events_by_day[day]):
            errs = validate_social_message(
                m,
                target_emp=by_id[ev["target"]],
                decoy_id="e00",
                valid_ids=valid_ids,
            )
            assert errs == [], (day, ev["bias"], errs, m["body"])
    assert verify_horizon_continuity(prov_long.episode_state("hard", 777).events_by_day, decoy_id="e00") == []

    for tier in ("easy", "medium"):
        prov_tier = get_provider("v16:v6_horizon_escalation")
        _, tier_days, _ = _run_horizon(prov_tier, tier, 4)
        for day, msgs in tier_days.items():
            assert lint_messages(msgs) == []
            assert len([m for m in msgs if "-s" in m["id"]]) == 3, (tier, day)

    monkeypatch.delenv("CANARY_OFFLINE", raising=False)
    monkeypatch.delenv("SLEEPER_OFFLINE", raising=False)
    stub_prov = get_provider("v16-gemini-stub:v6_horizon_escalation", cache_dir=str(tmp_path / "stub_cache"))
    _, stub_days, _ = _run_horizon(stub_prov, "hard", 5)
    assert stub_prov.rejects == 0
    for late_d in (19, 20, 21):
        late_stub_social = [m for m in stub_days[late_d] if "-s" in m["id"]]
        assert len(late_stub_social) == 3
        assert all("though nothing is verified" in m["body"] for m in late_stub_social)

    env_ctx = Env("hard", 6)
    f1 = env_ctx._facts(1)
    by_emp = {e.id: e for e in f1.employees}
    non_decoy = [e.id for e in f1.employees if e.id != f1.decoy]
    pair_a = (non_decoy[2], non_decoy[0])
    ctx_intraday = SocialDayContext(
        facts=f1,
        by_id=by_emp,
        primary_suspect=non_decoy[0],
        secondary_suspect=non_decoy[1],
        authority_speakers=(non_decoy[2],),
        grudge_pairs=(pair_a,),
        peers=tuple(non_decoy[2:]),
        seen_docs={},
        prior_events=(),
        today_events=(),
        grudge_counts={pair_a: 1},
    )
    ev_intra = horizon_escalation._gen_horizon_grudge(ctx_intraday, random.Random("intra"), pair_index=0)
    assert ev_intra["grudge_count"] == 2
    assert ev_intra["grudge_stage"] == "intraday_clash"
    assert ev_intra["ref_day"] is None
    assert HORIZON_DAY_REF_RE.findall(ev_intra["body"]) == []

    assert verify_horizon_continuity({}) == ["empty events_by_day"]
    bad_map = {
        1: [{"sender": "e00", "target": "e00", "body": "Doc check on Day 2 for e00", "bias": "grudge", "grudge_count": 1, "speaker_dept": "ops"}],
        2: [{"sender": "e01", "target": "e02", "body": "Doc check on Day 5 for e02", "bias": "anchoring", "speaker_dept": "ops"}],
    }
    bad_errs = verify_horizon_continuity(bad_map, decoy_id="e00", horizon_days=2)
    assert any("decoy e00 sent social event" in e for e in bad_errs)
    assert any("unexpected Day reference" in e for e in bad_errs)
    assert any("non-causal reference Day 5" in e for e in bad_errs)
