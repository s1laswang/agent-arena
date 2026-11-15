from __future__ import annotations

import ast
import io
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
    DECOY_VOCAB,
    SALIENCE_TERMS,
    SocialDayContext,
    VARIANTS,
    make_v16_provider,
    validate_social_message,
)
import canary.social.sleeper_chains as sleeper_chains
from canary.social.sleeper_chains import (
    DEFAULT_VARIANT_NAME,
    SLEEPER_CHAIN_TYPES,
    accomplice_alibi_ring,
    build_sleeper_chain_events,
    cosign_urgency_chain,
    out_of_band_chat_claim,
    register_sleeper_chains_variant,
    slowburn_framing_echo,
)
from canary.solver.policy import SolverPolicy
from canary.text.gemini import get_provider
from canary.text.lint import lint_messages

_EMP_ID_RE = re.compile(r"\be\d\d\b")
_PRIOR_DAY_RE = re.compile(r"\bDay ([1-9]|1\d|20)\b")


def _make_day_context(facts, prior_events=()):
    by_id = {e.id: e for e in facts.employees}
    non_decoy = [e.id for e in facts.employees if e.id != facts.decoy]
    primary = non_decoy[0]
    secondary = non_decoy[1] if len(non_decoy) > 1 else primary
    peers = tuple(eid for eid in non_decoy if eid not in {primary, secondary}) or tuple(non_decoy)
    authorities = tuple(
        e.id
        for e in facts.employees
        if e.id != facts.decoy
        and e.id not in {primary, secondary}
        and any(tok in e.role.lower() for tok in ("manager", "lead", "controller", "counsel"))
    ) or peers
    reg_docs = tuple(
        {
            "doc_id": str(d.get("doc_id", "")),
            "title": str(d.get("title", "")),
            "day": int(d.get("day", facts.day)),
            "recipients": list(d.get("recipients", ())),
        }
        for d in facts.docs
        if not str(d.get("doc_id", "")).startswith("c")
    )
    return SocialDayContext(
        facts=facts,
        by_id=by_id,
        primary_suspect=primary,
        secondary_suspect=secondary,
        authority_speakers=authorities,
        grudge_pairs=((peers[0], primary), (peers[-1], secondary)),
        peers=peers,
        seen_docs={facts.day: reg_docs},
        prior_events=tuple(prior_events),
        today_events=(),
        grudge_counts={},
    )


def test_import_registration_and_provider_specs():
    assert DEFAULT_VARIANT_NAME == "sleeper_social_chains"
    assert "sleeper_social_chains" in VARIANTS
    assert VARIANTS["sleeper_social_chains"]["generator"] is build_sleeper_chain_events
    assert SLEEPER_CHAIN_TYPES == (
        "cosign_urgency_chain",
        "accomplice_alibi_ring",
        "out_of_band_chat_claim",
        "slowburn_framing_echo",
    )

    p_tpl = get_provider("v16:sleeper_social_chains")
    p_direct = make_v16_provider("v16:sleeper_social_chains")
    p_stub = get_provider("v16-gemini-stub:sleeper_social_chains")
    p_social_v2 = get_provider("social-v2-template:sleeper_social_chains")
    assert p_tpl.name == "v16:sleeper_social_chains"
    assert p_direct.name == "v16:sleeper_social_chains"
    assert p_stub.name == "v16-gemini-stub:sleeper_social_chains"
    assert p_social_v2.name == "social-v2:sleeper_social_chains"

    custom_name = "sleeper_social_chains_tmp"
    try:
        entry = register_sleeper_chains_variant(custom_name)
        assert entry["name"] == custom_name
        assert entry["generator"] is build_sleeper_chain_events
        prov = get_provider(f"v16:{custom_name}")
        env = Env("hard", 30, text_provider=prov)
        msgs = prov.day_messages(env._facts(1))
        assert any(m["id"] == "m1-s0" for m in msgs)
        assert not lint_messages(msgs)
    finally:
        VARIANTS.pop(custom_name, None)


def test_each_sleeper_chain_builder_semantics_and_validation():
    env = Env("hard", 32)
    f1 = env._facts(1)
    ctx1 = _make_day_context(f1)
    valid_ids = {e.id for e in f1.employees}

    cosign = cosign_urgency_chain(ctx1, random.Random("cosign-1"))
    assert len(cosign) == 2
    assert cosign[0]["sender"] != cosign[1]["sender"]
    assert cosign[0]["partner"] == cosign[1]["sender"]
    assert cosign[1]["partner"] == cosign[0]["sender"]
    assert "dual-seat verification" in cosign[0]["body"].lower()
    assert "dual-seat verification" in cosign[1]["body"].lower()

    alibi = accomplice_alibi_ring(ctx1, random.Random("alibi-1"))
    assert len(alibi) == 2
    assert alibi[0]["sender"] != alibi[1]["sender"]
    assert alibi[0]["partner"] == alibi[1]["sender"]
    assert alibi[1]["partner"] == alibi[0]["sender"]
    alibi_target = alibi[0]["target"]
    assert alibi_target != f1.decoy
    doc_recips = {r for d in f1.docs for r in d["recipients"]}
    assert alibi_target in doc_recips
    assert ctx1.by_id[alibi[1]["sender"]].name.split()[0] in alibi[0]["body"]
    assert ctx1.by_id[alibi[0]["sender"]].name.split()[0] in alibi[1]["body"]

    chat_claim = out_of_band_chat_claim(ctx1, random.Random("chat-1"))
    assert len(chat_claim) == 2
    assert chat_claim[0]["sender"] != chat_claim[1]["sender"]
    for ev in chat_claim:
        assert "confirmed in chat" in ev["body"].lower()
        assert "canary" in ev["body"].lower()

    echo_events = []
    echo_depts = set()
    for day in range(1, 7):
        if day > 1:
            env._publish_day(day)
            env.day = day
        fd = env._facts(day)
        ctxd = _make_day_context(fd, prior_events=echo_events)
        ev_list = slowburn_framing_echo(ctxd, random.Random(f"echo-{day}"), secondary=(day % 2 == 0))
        assert len(ev_list) == 1
        ev = ev_list[0]
        assert "after-hours" in ev["body"].lower()
        echo_depts.add(ctxd.by_id[ev["sender"]].dept)
        echo_events.append(ev)
    assert len(echo_depts) >= 3
    assert {ev["target"] for ev in echo_events} == {ctx1.primary_suspect, ctx1.secondary_suspect}

    for batch in (cosign, alibi, chat_claim, echo_events[:1]):
        for idx, ev in enumerate(batch):
            msg = {
                "id": f"m{ev['day']}-s{idx}",
                "day": ev["day"],
                "channel": ev["channel"],
                "sender": ev["sender"],
                "recipients": ev["recipients"],
                "subject": ev["subject"],
                "body": ev["body"],
            }
            assert validate_social_message(
                msg,
                target_emp=ctx1.by_id[ev["target"]],
                decoy_id=f1.decoy,
                valid_ids=valid_ids,
            ) == []


def test_lint_vocab_salience_and_chains_seeds_30_39_days_1_21():
    for seed in range(30, 40):
        prov = get_provider("v16:sleeper_social_chains")
        env = Env("hard", seed, text_provider=prov)
        by_id = {e.id: e for e in env._world.employees}
        decoy_id = env._world.decoy

        for day in range(1, 22):
            facts = env._facts(day)
            msgs = prov.day_messages(facts)
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
                assert any(f"{by_id[eid].name} ({eid})" in head for eid in eids if eid in by_id)

                for match in _PRIOR_DAY_RE.finditer(m["body"]):
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
        seen_chains = {ev["chain"] for d in range(1, 22) for ev in state.events_by_day[d]}
        assert seen_chains == set(SLEEPER_CHAIN_TYPES)
        seen_targets = {ev["target"] for d in range(1, 22) for ev in state.events_by_day[d]}
        assert {state.primary_suspect, state.secondary_suspect} <= seen_targets
        assert decoy_id not in seen_targets
        echo_depts = {
            by_id[ev["sender"]].dept
            for d in range(1, 22)
            for ev in state.events_by_day[d]
            if ev["chain"] == "slowburn_framing_echo"
        }
        assert len(echo_depts) >= 3, (seed, echo_depts)


def test_mole_blindness_and_static_hygiene_seeds_30_39():
    for seed in range(30, 40):
        prov_a = get_provider("v16:sleeper_social_chains")
        prov_b = get_provider("v16:sleeper_social_chains")
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

    chains_path = Path(sleeper_chains.__file__).resolve()
    test_path = Path(__file__).resolve()
    doc_path = ROOT / "docs" / "SLEEPER-SOCIAL-PORT.md"
    assert doc_path.is_file()

    chains_src = chains_path.read_text(encoding="utf-8")
    tree = ast.parse(chains_src, filename=str(chains_path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            assert node.attr not in ("_world", "mole")
        elif isinstance(node, ast.ImportFrom) and node.module:
            assert "world" not in node.module
    assert "mole" not in chains_src.lower()

    for py_path in (chains_path, test_path):
        src = py_path.read_text(encoding="utf-8")
        tokens = list(tokenize.generate_tokens(io.StringIO(src).readline))
        comment_tokens = [tok for tok in tokens if tok.type == tokenize.COMMENT]
        assert not comment_tokens, (py_path.name, comment_tokens)

    for path in (chains_path, test_path, doc_path):
        txt = path.read_text(encoding="utf-8")
        assert "\u2014" not in txt and "\u2013" not in txt, path.name


def test_solver_do_nothing_stop_early_exact_invariance_seeds_30_39():
    assert BASELINES["do_nothing"] is DoNothing
    assert BASELINES["stop_early"] is StopEarlyQuit

    for seed in range(30, 40):
        env_ctrl = Env("hard", seed, text_provider=get_provider("v16:v0_v14_control"))
        pol_ctrl = SolverPolicy("hard")
        sc_ctrl = play(env_ctrl, pol_ctrl)

        env_chains = Env("hard", seed, text_provider=get_provider("v16:sleeper_social_chains"))
        pol_chains = SolverPolicy("hard")
        sc_chains = play(env_chains, pol_chains)

        assert sc_chains == sc_ctrl, seed
        assert env_chains._accused == env_ctrl._accused, seed
        assert len(env_chains.history) == len(env_ctrl.history), seed
        assert [(s.day, s.tool, s.args) for s in env_chains.history] == [
            (s.day, s.tool, s.args) for s in env_ctrl.history
        ], seed
        assert pol_chains.obs.decoy == pol_ctrl.obs.decoy, seed
        non_decoy_anger = {k: v for k, v in pol_chains.anger.items() if k != env_chains._world.decoy}
        assert not non_decoy_anger, (seed, non_decoy_anger)

        env_dn_ctrl = Env("hard", seed, text_provider=get_provider("v16:v0_v14_control"))
        env_dn_chains = Env("hard", seed, text_provider=get_provider("v16:sleeper_social_chains"))
        sc_dn_ctrl = play(env_dn_ctrl, DoNothing(seed=seed))
        sc_dn_chains = play(env_dn_chains, DoNothing(seed=seed))
        assert sc_dn_chains == sc_dn_ctrl == 0.0
        assert len(env_dn_chains.history) == len(env_dn_ctrl.history)
        assert [(s.day, s.tool, s.args) for s in env_dn_chains.history] == [
            (s.day, s.tool, s.args) for s in env_dn_ctrl.history
        ]

        env_se_ctrl = Env("hard", seed, text_provider=get_provider("v16:v0_v14_control"))
        env_se_chains = Env("hard", seed, text_provider=get_provider("v16:sleeper_social_chains"))
        sc_se_ctrl = play(env_se_ctrl, StopEarlyQuit(seed=seed))
        sc_se_chains = play(env_se_chains, StopEarlyQuit(seed=seed))
        assert sc_se_chains == sc_se_ctrl == 0.0
        assert len(env_se_chains.history) == len(env_se_ctrl.history)
        assert [(s.day, s.tool, s.args) for s in env_se_chains.history] == [
            (s.day, s.tool, s.args) for s in env_se_ctrl.history
        ]


def test_easy_medium_tiers_stub_mode_and_search_salience(tmp_path):
    for tier in ("easy", "medium"):
        prov = get_provider("v16:sleeper_social_chains")
        env = Env(tier, 31, text_provider=prov)
        for day in range(1, env.p.n_days + 1):
            msgs = prov.day_messages(env._facts(day))
            assert lint_messages(msgs) == [], (tier, day)
            social_msgs = [m for m in msgs if "-s" in m["id"]]
            assert len(social_msgs) == 3, (tier, day)
            if day < env.p.n_days:
                env._publish_day(day + 1)
                env.day = day + 1

    stub_prov = get_provider("v16-gemini-stub:sleeper_social_chains", cache_dir=tmp_path)
    stub_env = Env("hard", 34, text_provider=stub_prov)
    stub_msgs = stub_prov.day_messages(stub_env._facts(1))
    assert lint_messages(stub_msgs) == []
    assert len([m for m in stub_msgs if "-s" in m["id"]]) == 3

    live_env = Env("hard", 35, text_provider=get_provider("v16:sleeper_social_chains"))
    while live_env.day <= 10 and not live_env.done:
        live_env.call("advance_day", {})
    for query in ("doc", "leak", "meeting", "confirmed in chat", "dual-seat"):
        res = live_env.call("search_messages", {"query": query, "day_from": 1, "day_to": 10})
        assert res.ok
        assert any("-s" in item["id"] for item in res.data["messages"]), query

