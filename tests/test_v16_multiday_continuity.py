from __future__ import annotations

import re

from canary.baselines import play
from canary.env import Env
from canary.social import (
    ANGER_WORDS,
    BIAS_TYPES,
    DECOY_VOCAB,
    HORIZON_DAYS,
    SALIENCE_TERMS,
    VARIANTS,
    get_variant_spec,
    make_v16_provider,
    register_fr8_variant,
    validate_social_message,
)
from canary.solver.policy import SolverPolicy
from canary.text.facts import EmployeeFacts, PublicDayFacts
from canary.text.gemini import get_provider
from canary.text.lint import lint_messages

CORE_VARIANTS = (
    "v1_anchoring_authority_confirmation",
    "v2_recency_bandwagon_sycophancy",
    "v3_grudge_falsemem_misforward",
    "v4_triad_authority_recency_grudge",
    "v5_full9_cocktail",
)

GRUDGE_VARIANTS = (
    "b_grudge",
    "v3_grudge_falsemem_misforward",
    "v4_triad_authority_recency_grudge",
    "v5_full9_cocktail",
)

_DAY_REF_RE = re.compile(r"\bDay (\d+)\b")


def _run_21_days(prov, tier: str = "hard", seed: int = 30) -> tuple[Env, dict[int, list[dict]], int]:
    env = Env(tier, seed, text_provider=prov)
    facts_seed = env._facts(1).seed
    by_day: dict[int, list[dict]] = {}
    while not env.done:
        d = env.day
        env.call("advance_day", {})
        by_day[d] = [env._messages[mid] for mid in env._msg_order if env._messages[mid]["day"] == d]
    return env, by_day, facts_seed


def test_late_horizon_days_19_to_21_schedule_and_search_coverage():
    assert HORIZON_DAYS == 21
    assert set(VARIANTS["v5_full9_cocktail"]["schedule"]) == set(range(1, 22))
    for vname in CORE_VARIANTS:
        sched = VARIANTS[vname]["schedule"]
        assert {19, 20, 21}.issubset(set(sched)), vname

    for bias in BIAS_TYPES:
        assert set(VARIANTS[f"b_{bias}"]["schedule"]) == set(range(1, 22))

    combo_spec = get_variant_spec("authority+grudge+recency")
    assert set(combo_spec["schedule"]) == set(range(1, 22))

    tmp_list = "fr8_list_21d_tmp"
    tmp_dict = "fr8_dict_21d_tmp"
    try:
        e_list = register_fr8_variant(tmp_list, ["anchoring", "confirmation"])
        e_dict = register_fr8_variant(tmp_dict, {"biases": ["authority", "recency"]})
        assert set(e_list["schedule"]) == set(range(1, 22))
        assert set(e_dict["schedule"]) == set(range(1, 22))
    finally:
        VARIANTS.pop(tmp_list, None)
        VARIANTS.pop(tmp_dict, None)

    for vname in CORE_VARIANTS:
        prov = get_provider(f"v16:{vname}")
        env = Env("hard", 32, text_provider=prov)
        while env.day < 21 and not env.done:
            env.call("advance_day", {})
        assert env.day == 21 and not env.done

        for q in ("e", "doc", "leak", "meeting"):
            res = env.call("search_messages", {"query": q, "day_from": 19, "day_to": 20})
            assert res.ok
            hits = res.data["messages"]
            assert any("-s" in item["id"] for item in hits), (vname, q)
            if q == "e":
                assert any(item["id"].startswith("m19-s") for item in hits), vname
                assert any(item["id"].startswith("m20-s") for item in hits), vname

        env.call("advance_day", {})
        assert env.done
        by_day = {
            d: [env._messages[mid] for mid in env._msg_order if env._messages[mid]["day"] == d]
            for d in range(1, 22)
        }
        for late_day in (19, 20, 21):
            social_late = [m for m in by_day[late_day] if "-s" in m["id"]]
            assert len(social_late) >= 1, (vname, late_day)
            assert social_late[0]["id"] == f"m{late_day}-s0"
            assert not lint_messages(by_day[late_day])


def test_deterministic_prior_day_callbacks_across_days_1_to_21():
    for vname in CORE_VARIANTS:
        prov_1 = make_v16_provider(f"v16:{vname}")
        prov_2 = make_v16_provider(f"v16:{vname}")
        _, msgs_1, fseed_1 = _run_21_days(prov_1, "hard", 35)
        _, msgs_2, fseed_2 = _run_21_days(prov_2, "hard", 35)
        assert fseed_1 == fseed_2
        assert msgs_1 == msgs_2

        st_1 = prov_1.episode_state("hard", fseed_1)
        st_2 = prov_2.episode_state("hard", fseed_2)
        assert st_1 is not None and st_2 is not None
        assert st_1.events_by_day == st_2.events_by_day
        assert st_1.grudge_counts == st_2.grudge_counts

        for ev in st_1.events_by_day.get(1, ()):
            assert ev["ref_day"] is None
            assert not _DAY_REF_RE.findall(ev["body"])

        late_callbacks: list[tuple[int, int]] = []
        two_digit_callbacks: list[tuple[int, int]] = []
        for day in range(2, 22):
            for ev in st_1.events_by_day.get(day, ()):
                body_days = [int(x) for x in _DAY_REF_RE.findall(ev["body"])]
                for ref_d in body_days:
                    assert 1 <= ref_d < day, (vname, day, ref_d, ev["body"])
                if ev["ref_day"] is not None:
                    assert 1 <= ev["ref_day"] < day
                    assert f"Day {ev['ref_day']}" in ev["body"]
                    if day >= 19:
                        late_callbacks.append((day, ev["ref_day"]))
                    if ev["ref_day"] >= 10:
                        two_digit_callbacks.append((day, ev["ref_day"]))
                if ev["bias"] == "anchoring" and day >= 3:
                    assert ev["ref_day"] == 1, (vname, day, ev["body"])

        assert len(late_callbacks) >= 3, vname
        if vname != "v1_anchoring_authority_confirmation":
            assert two_digit_callbacks, vname

    prov_v2 = make_v16_provider("v16:v2_recency_bandwagon_sycophancy")
    _, _, fseed_36 = _run_21_days(prov_v2, "hard", 36)
    st_v2 = prov_v2.episode_state("hard", fseed_36)
    assert st_v2 is not None
    day3_evs = st_v2.events_by_day[3]
    assert day3_evs[0]["bias"] == "authority" and day3_evs[1]["bias"] == "sycophancy"
    assert day3_evs[1]["ref_day"] is None
    day4_syc = [ev for ev in st_v2.events_by_day[4] if ev["bias"] == "sycophancy"][0]
    assert day4_syc["ref_day"] == 3
    assert "Day 3" in day4_syc["body"]
    day21_syc = [ev for ev in st_v2.events_by_day[21] if ev["bias"] == "sycophancy"][0]
    assert day21_syc["ref_day"] == 19
    assert "Day 19" in day21_syc["body"]


def test_escalating_grudge_counts_and_stages_across_days_1_to_21():
    for vname in GRUDGE_VARIANTS:
        prov = make_v16_provider(f"v16:{vname}")
        _, _, fseed_37 = _run_21_days(prov, "hard", 37)
        state = prov.episode_state("hard", fseed_37)
        assert state is not None
        pair_0, pair_1 = state.grudge_pairs
        assert pair_0 != pair_1

        prev_totals: dict[tuple[str, str], int] = {}
        seen_seq: dict[tuple[str, str], list[int]] = {pair_0: [], pair_1: []}
        origin_day: dict[tuple[str, str], int] = {}

        for day in range(1, 22):
            cur_totals = state.grudge_counts_through(day)
            for pair, prev_val in prev_totals.items():
                assert cur_totals.get(pair, 0) >= prev_val
            day_grudges = [ev for ev in state.events_by_day.get(day, ()) if ev["bias"] == "grudge"]
            if day_grudges:
                assert sum(cur_totals.values()) == sum(prev_totals.values()) + len(day_grudges)
            for ev in day_grudges:
                pair = (ev["sender"], ev["target"])
                assert pair in seen_seq
                seen_seq[pair].append(ev["grudge_count"])
                c = ev["grudge_count"]
                body = ev["body"]
                if c == 1:
                    origin_day[pair] = day
                    assert ev["ref_day"] is None
                    assert "Doc handoff dispute" in body or "Meeting review issue" in body
                elif c == 2:
                    assert ev["ref_day"] == origin_day[pair]
                    assert f"Day {origin_day[pair]}" in body
                    assert "Second doc clash" in body or "doc meeting friction" in body
                elif c == 3:
                    assert ev["ref_day"] == origin_day[pair]
                    assert f"since Day {origin_day[pair]}" in body
                    assert "Ongoing doc feud" in body or "Escalating leak meeting note" in body
                else:
                    assert c >= 4
                    assert f"since Day {origin_day[pair]}" in body
                    assert f"clash #{c}" in body
                    assert ev["ref_day"] is not None and origin_day[pair] < ev["ref_day"] < day
                    assert f"Day {ev['ref_day']}" in body
            prev_totals = cur_totals

        assert state.grudge_counts == prev_totals
        for pair in (pair_0, pair_1):
            seq = seen_seq[pair]
            assert seq == list(range(1, len(seq) + 1)), (vname, pair, seq)
            assert len(seq) >= 3, (vname, pair, seq)

    prov_bg = make_v16_provider("v16:b_grudge")
    _, _, fseed_38 = _run_21_days(prov_bg, "hard", 38)
    st_bg = prov_bg.episode_state("hard", fseed_38)
    assert st_bg is not None
    p0, p1 = st_bg.grudge_pairs
    assert st_bg.grudge_counts[p0] == 11
    assert st_bg.grudge_counts[p1] == 11

    intraday_name = "fr8_intraday_grudge_tmp"
    try:
        register_fr8_variant(
            intraday_name,
            {
                "schedule": {
                    1: [{"bias": "grudge", "pair_index": 0}, {"bias": "grudge", "pair_index": 0}],
                    2: [{"bias": "grudge", "pair_index": 0}, {"bias": "grudge", "pair_index": 0}],
                }
            },
        )
        p_intra = make_v16_provider(f"v16:{intraday_name}")
        _, _, fseed_39 = _run_21_days(p_intra, "hard", 39)
        st_intra = p_intra.episode_state("hard", fseed_39)
        assert st_intra is not None
        assert [ev["grudge_count"] for ev in st_intra.events_by_day[1]] == [1, 2]
        assert [ev["grudge_count"] for ev in st_intra.events_by_day[2]] == [3, 4]
        assert st_intra.grudge_counts[st_intra.grudge_pairs[0]] == 4
    finally:
        VARIANTS.pop(intraday_name, None)


def test_shared_provider_timeline_isolation_and_out_of_order_recovery():
    shared = make_v16_provider("v16:v5_full9_cocktail")

    env_restricted = Env("hard", 41, text_provider=shared)
    fseed_41 = env_restricted._facts(1).seed
    shared.day_messages(env_restricted._facts(1))
    st_init = shared.episode_state("hard", fseed_41)
    assert st_init is not None
    env_restricted.call("restrict_access", {"employee": st_init.primary_suspect})
    while not env_restricted.done:
        if env_restricted.day == 6 and st_init.primary_suspect in env_restricted._restricted:
            env_restricted.call("unrestrict_access", {"employee": st_init.primary_suspect})
        env_restricted.call("advance_day", {})

    _, msgs_shared_clean, _ = _run_21_days(shared, "hard", 41)
    fresh = make_v16_provider("v16:v5_full9_cocktail")
    _, msgs_fresh_clean, _ = _run_21_days(fresh, "hard", 41)
    assert msgs_shared_clean == msgs_fresh_clean

    st_shared = shared.episode_state("hard", fseed_41)
    st_fresh = fresh.episode_state("hard", fseed_41)
    assert st_shared is not None and st_fresh is not None
    assert st_shared.events_by_day == st_fresh.events_by_day
    assert st_shared.grudge_counts == st_fresh.grudge_counts

    env_probe = Env("hard", 42)
    fseed_42 = env_probe._facts(1).seed
    for d in range(1, 11):
        if d < 10:
            env_probe._publish_day(d + 1)
            env_probe.day = d + 1
    shared.day_messages(env_probe._facts(10))

    _, msgs_42_shared, _ = _run_21_days(shared, "hard", 42)
    fresh_42 = make_v16_provider("v16:v5_full9_cocktail")
    _, msgs_42_fresh, _ = _run_21_days(fresh_42, "hard", 42)
    assert msgs_42_shared == msgs_42_fresh
    assert shared.episode_state("hard", fseed_42).events_by_day == fresh_42.episode_state("hard", fseed_42).events_by_day


def test_long_names_depts_and_seeds_0_to_29_full_21_day_invariants():
    long_emps = tuple(
        EmployeeFacts(
            id=f"e{i:02d}",
            name=f"Aleksanteri-Maximilian Virtanen-Karjalainen {i}",
            dept="Cross-Platform Infrastructure",
            role="senior compliance lead" if i < 3 else "principal systems engineer",
            clearance=3,
        )
        for i in range(12)
    )
    prov_long = make_v16_provider("v16:v5_full9_cocktail")
    valid_ids = {e.id for e in long_emps}
    by_id = {e.id: e for e in long_emps}
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
        assert social_msgs
        st_long = prov_long.episode_state("hard", 777)
        assert st_long is not None
        for m, ev in zip(social_msgs, st_long.events_by_day[day]):
            errs = validate_social_message(
                m,
                target_emp=by_id[ev["target"]],
                decoy_id="e00",
                valid_ids=valid_ids,
            )
            assert not errs, (day, ev["bias"], errs, m["body"])

    prov_sweep = make_v16_provider("v16:v5_full9_cocktail")
    for seed in range(0, 30):
        _, by_day, _ = _run_21_days(prov_sweep, "hard", seed)
        assert set(by_day) == set(range(1, 22))
        decoy = Env("hard", seed)._world.decoy
        for day in (1, 10, 19, 20, 21):
            msgs = by_day[day]
            assert not lint_messages(msgs)
            social_msgs = [m for m in msgs if "-s" in m["id"]]
            assert len(social_msgs) >= 2
            for m in social_msgs:
                low = f"{m['subject']}\n{m['body']}".lower()
                for w in DECOY_VOCAB:
                    assert w not in low
                assert any(t in m["body"][:110].lower() for t in SALIENCE_TERMS)
            for m in msgs:
                if m["sender"] != decoy:
                    low = f"{m['subject']}\n{m['body']}".lower()
                    for w in ANGER_WORDS:
                        assert w not in low

    for seed in (0, 1, 2):
        p_stub = make_v16_provider("v16-gemini-stub:v5_full9_cocktail")
        _, stub_days, _ = _run_21_days(p_stub, "hard", seed)
        assert p_stub.rejects == 0
        for d in (19, 20, 21):
            assert len([m for m in stub_days[d] if "-s" in m["id"]]) == 3

        env_ctrl = Env("hard", seed, text_provider=get_provider("v16:v0_v14_control"))
        pol_ctrl = SolverPolicy("hard")
        sc_ctrl = play(env_ctrl, pol_ctrl)

        env_v5 = Env("hard", seed, text_provider=get_provider("v16:v5_full9_cocktail"))
        pol_v5 = SolverPolicy("hard")
        sc_v5 = play(env_v5, pol_v5)
        assert (sc_v5, env_v5._accused, len(env_v5.history)) == (sc_ctrl, env_ctrl._accused, len(env_ctrl.history))
