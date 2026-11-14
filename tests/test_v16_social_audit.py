"""Tests for canary.social_audit V1.6 6-check TextProvider fairness and replay gate."""
from __future__ import annotations

import inspect
import json
from dataclasses import asdict

import pytest

from canary.analysis.accuse import audit_episode
from canary.baselines import Heuristic
from canary.env import Env
from canary.eval import run_episode
from canary.social_audit import (
    ANGER_WORDS,
    CHECK_NAMES,
    SanitizedTemplateProvider,
    audit_text_provider,
    main,
    resolve_text_provider,
    verify_and_score_episodes,
)
from canary.solver.policy import SolverPolicy
from canary.text.facts import PublicDayFacts

CHAN_PREFIX = chr(35)


class NonDeterministicProvider:
    """Bad mock provider whose outputs drift across calls on identical PublicDayFacts."""

    name = "bad_nondet"

    def __init__(self) -> None:
        self._base = SanitizedTemplateProvider()
        self._counter = 0

    def day_messages(self, facts: PublicDayFacts) -> list[dict]:
        self._counter += 1
        msgs = self._base.day_messages(facts)
        msgs[0] = {**msgs[0], "body": f"{msgs[0]['body']} [{self._counter}]"}
        return msgs

    def interview_answer(self, facts: PublicDayFacts, employee: str, topic: str, signal: str) -> str:
        self._counter += 1
        return f"{self._base.interview_answer(facts, employee, topic, signal)} ({self._counter})"


class MoleSnoopingProvider:
    """Bad mock provider that peeks at caller frame env._world.mole to leak hidden truth."""

    name = "bad_mole_snoop"

    def __init__(self) -> None:
        self._base = SanitizedTemplateProvider()

    def _find_mole(self) -> str | None:
        frame = inspect.currentframe()
        while frame is not None:
            for val in frame.f_locals.values():
                world = getattr(val, "_world", None)
                mole = getattr(world, "mole", None)
                if isinstance(mole, str):
                    return mole
            frame = frame.f_back
        return None

    def day_messages(self, facts: PublicDayFacts) -> list[dict]:
        msgs = self._base.day_messages(facts)
        mole = self._find_mole()
        if mole:
            msgs[0] = {**msgs[0], "body": f"{msgs[0]['body']} [hint:{mole}]"}
        return msgs

    def interview_answer(self, facts: PublicDayFacts, employee: str, topic: str, signal: str) -> str:
        ans = self._base.interview_answer(facts, employee, topic, signal)
        mole = self._find_mole()
        if mole == employee:
            return ans + " Honestly, nervous."
        return ans


class NonDecoyAngerProvider:
    """Bad mock provider where an innocent non-decoy employee uses ANGER_WORDS."""

    name = "bad_nondecoy_anger"

    def __init__(self) -> None:
        self._base = SanitizedTemplateProvider()

    def day_messages(self, facts: PublicDayFacts) -> list[dict]:
        msgs = self._base.day_messages(facts)
        non_decoy = next(e.id for e in facts.employees if e.id != facts.decoy)
        msgs.append(
            {
                "id": f"m{facts.day}-extra-anger",
                "day": facts.day,
                "channel": f"{CHAN_PREFIX}general",
                "sender": non_decoy,
                "recipients": [e.id for e in facts.employees if e.id != non_decoy],
                "subject": "",
                "body": "Skipped for promotion again and tired of a flat raise.",
            }
        )
        return msgs

    def interview_answer(self, facts: PublicDayFacts, employee: str, topic: str, signal: str) -> str:
        return self._base.interview_answer(facts, employee, topic, signal)


class SilentDecoyProvider:
    """Bad mock provider where the angry decoy never emits disgruntled messages."""

    name = "bad_silent_decoy"

    def __init__(self) -> None:
        self._base = SanitizedTemplateProvider()

    def day_messages(self, facts: PublicDayFacts) -> list[dict]:
        neutral_facts = PublicDayFacts(
            tier=facts.tier,
            seed=facts.seed,
            day=facts.day,
            company=facts.company,
            employees=facts.employees,
            docs=facts.docs,
            decoy=facts.decoy,
            decoy_mood="neutral",
            restricted=facts.restricted,
            extra=facts.extra,
        )
        return self._base.day_messages(neutral_facts)

    def interview_answer(self, facts: PublicDayFacts, employee: str, topic: str, signal: str) -> str:
        return self._base.interview_answer(facts, employee, topic, signal)


class LintDirtyProvider:
    """Bad mock provider emitting forbidden confession and rival address tokens."""

    name = "bad_lint_dirty"

    def __init__(self) -> None:
        self._base = SanitizedTemplateProvider()

    def day_messages(self, facts: PublicDayFacts) -> list[dict]:
        msgs = self._base.day_messages(facts)
        if facts.day == 1:
            msgs[0] = {
                **msgs[0],
                "body": "Forwarding to drop@corvid-rival.io from e01; i leaked the deck.",
            }
        return msgs

    def interview_answer(self, facts: PublicDayFacts, employee: str, topic: str, signal: str) -> str:
        if topic == "contacts_outside" and signal == "evasive":
            return "Fine, I am the mole and sent it out."
        return self._base.interview_answer(facts, employee, topic, signal)


class DecoyHijackRegressionProvider:
    """Bad mock provider that floods non-decoy angry lines on days 1..3 so SolverPolicy misidentifies decoy."""

    name = "bad_decoy_hijack"

    def __init__(self) -> None:
        self._base = SilentDecoyProvider()

    def day_messages(self, facts: PublicDayFacts) -> list[dict]:
        msgs = self._base.day_messages(facts)
        hijack = next(e.id for e in facts.employees if e.id != facts.decoy)
        for idx, line in enumerate(
            (
                "Skipped for promotion again.",
                "Another flat raise while people burn out.",
                "Management moves the goalposts; this place does not deserve us.",
                "Nobody asks us anything; updating my CV for a recruiter.",
            )
        ):
            msgs.append(
                {
                    "id": f"m{facts.day}-hijack-{idx}",
                    "day": facts.day,
                    "channel": f"{CHAN_PREFIX}general",
                    "sender": hijack,
                    "recipients": [e.id for e in facts.employees if e.id != hijack],
                    "subject": "",
                    "body": line,
                }
            )
        return msgs

    def interview_answer(self, facts: PublicDayFacts, employee: str, topic: str, signal: str) -> str:
        return self._base.interview_answer(facts, employee, topic, signal)


class CorruptZeroBaselinesProvider:
    """Bad mock provider that corrupts Env state on late days so DoNothing scores positive."""

    name = "bad_zero_baselines"

    def __init__(self) -> None:
        self._base = SanitizedTemplateProvider()

    def day_messages(self, facts: PublicDayFacts) -> list[dict]:
        msgs = self._base.day_messages(facts)
        if facts.day >= 20:
            frame = inspect.currentframe()
            while frame is not None:
                self_obj = frame.f_locals.get("self")
                if isinstance(self_obj, Env) and getattr(self_obj, "_accused", None) is None:
                    self_obj._accused = self_obj._world.mole
                    self_obj._correct = True
                    self_obj._done = True
                    self_obj._end_reason = "accused"
                    break
                frame = frame.f_back
        return msgs

    def interview_answer(self, facts: PublicDayFacts, employee: str, topic: str, signal: str) -> str:
        return self._base.interview_answer(facts, employee, topic, signal)


def test_sanitized_template_passes_all_6_checks():
    rep = audit_text_provider("sanitized_template", tier="hard", seeds=range(30, 40))
    assert tuple(rep["checks"].keys()) == CHECK_NAMES
    for name in CHECK_NAMES:
        assert rep["checks"][name]["passed"] is True, (name, rep["checks"][name])
    assert rep["all_passed"] is True
    assert rep["failed_checks"] == []

    c2 = rep["checks"]["anger_words_hygiene"]
    assert c2["non_decoy_violation_count"] == 0
    assert c2["max_other_anger_n2"] == 0
    assert c2["decoy_isolated_count"] == 10
    assert c2["min_decoy_anger_n1"] >= 3

    c4 = rep["checks"]["solver_calibration_parity"]
    assert c4["solver_acc"] >= c4["template_acc"]
    assert c4["solver_mean_score"] >= c4["template_mean_score"] - 1e-9
    assert c4["false_decoy_ids"] == 0


def test_template_provider_audit_pinpoints_recruiter_hygiene():
    rep = audit_text_provider("template", tier="hard", seeds=range(30, 40))
    assert tuple(rep["checks"].keys()) == CHECK_NAMES
    assert rep["checks"]["public_facts_only"]["passed"] is True
    assert rep["checks"]["lint_clean"]["passed"] is True
    assert rep["checks"]["solver_calibration_parity"]["passed"] is True
    assert rep["checks"]["zero_baselines"]["passed"] is True
    assert rep["checks"]["replay_and_paired_gap"]["passed"] is True

    c2 = rep["checks"]["anger_words_hygiene"]
    assert c2["passed"] is False
    assert c2["non_decoy_words_found"] == ["recruiter"]
    assert c2["min_decoy_anger_n1"] >= 3
    assert c2["max_other_anger_n2"] >= 1
    assert rep["failed_checks"] == ["anger_words_hygiene"]


def test_bad_providers_fail_check_1_public_facts_only():
    rep_nd = audit_text_provider(NonDeterministicProvider(), tier="hard", seeds=range(30, 32))
    assert rep_nd["checks"]["public_facts_only"]["passed"] is False
    assert rep_nd["all_passed"] is False

    rep_snoop = audit_text_provider(MoleSnoopingProvider(), tier="hard", seeds=range(30, 32))
    assert rep_snoop["checks"]["public_facts_only"]["passed"] is False
    assert rep_snoop["all_passed"] is False


def test_bad_providers_fail_check_2_anger_words_hygiene():
    rep_leak = audit_text_provider(NonDecoyAngerProvider(), tier="hard", seeds=range(30, 33))
    c2_leak = rep_leak["checks"]["anger_words_hygiene"]
    assert c2_leak["passed"] is False
    assert c2_leak["non_decoy_violation_count"] > 0
    assert set(c2_leak["non_decoy_words_found"]).issubset(set(ANGER_WORDS))

    rep_silent = audit_text_provider(SilentDecoyProvider(), tier="hard", seeds=range(30, 33))
    c2_silent = rep_silent["checks"]["anger_words_hygiene"]
    assert c2_silent["passed"] is False
    assert c2_silent["min_decoy_anger_n1"] == 0
    assert c2_silent["decoy_isolated_count"] == 0


def test_bad_provider_fails_check_3_lint_clean():
    rep = audit_text_provider(LintDirtyProvider(), tier="hard", seeds=range(30, 32))
    c3 = rep["checks"]["lint_clean"]
    assert c3["passed"] is False
    assert c3["message_error_count"] > 0
    assert c3["interview_error_count"] > 0
    assert rep["all_passed"] is False


def test_bad_provider_fails_check_4_solver_calibration_parity():
    rep = audit_text_provider(DecoyHijackRegressionProvider(), tier="hard", seeds=range(30, 34))
    c4 = rep["checks"]["solver_calibration_parity"]
    assert c4["passed"] is False
    assert c4["false_decoy_ids"] > 0
    assert rep["all_passed"] is False


def test_bad_provider_fails_check_5_zero_baselines():
    rep = audit_text_provider(CorruptZeroBaselinesProvider(), tier="hard", seeds=range(30, 32))
    c5 = rep["checks"]["zero_baselines"]
    assert c5["passed"] is False
    assert c5["do_nothing_scores_all_zero"] is False
    assert rep["all_passed"] is False


def test_check_6_verify_and_score_episodes_and_tamper_detection():
    seeds = [30, 31, 32, 33]
    agent_eps = [run_episode(Env("hard", s), Heuristic(seed=s)) for s in seeds]
    solver_eps = [run_episode(Env("hard", s), SolverPolicy("hard")) for s in seeds]

    compact_agent = [
        {
            "tier": ep.tier,
            "seed": ep.seed,
            "agent": ep.agent,
            "score": ep.score,
            "accused": ep.accused,
            "correct": ep.correct,
            "final_day": ep.final_day,
            "end_reason": ep.end_reason,
            "steps": [{"tool": st.tool, "args": st.args} for st in ep.steps],
        }
        for ep in agent_eps
    ]

    scored = verify_and_score_episodes(compact_agent, solver_eps, tier="hard", provider="template")
    assert scored["passed"] is True
    assert scored["n_paired"] == 4
    assert scored["mismatches"] == []
    assert len(scored["paired_diff_ci95"]) == 2
    assert len(scored["raw_gap_ci95"]) == 2
    assert len(scored["frontier_solver_ratio_ci95"]) == 2
    assert len(scored["luck_adjusted_diff_ci95"]) == 2

    for ep, row in zip(agent_eps, scored["per_seed"]):
        expected_p = audit_episode(ep)["p_accused"]
        assert row["p_accused"] == pytest.approx(expected_p)
        expected_luck = 0.0 if not ep.accused else expected_p * float(ep.meta["V"]) - (1.0 - expected_p)
        assert row["luck_adjusted_score"] == pytest.approx(expected_luck, abs=1e-5)

    invalid_ep = {
        "tier": "hard",
        "seed": 99,
        "agent": "heuristic",
        "score": 0.0,
        "accused": None,
        "correct": False,
        "final_day": 1,
        "end_reason": "error",
        "meta": {"valid": False, "error": "rate limit"},
        "steps": [],
    }
    scored_with_invalid = verify_and_score_episodes(
        compact_agent + [invalid_ep], solver_eps, tier="hard", provider="template"
    )
    assert scored_with_invalid["passed"] is True
    assert scored_with_invalid["n_paired"] == 4
    assert scored_with_invalid["invalid_agent_seeds"] == [99]
    assert scored_with_invalid["agent_mean_score"] == pytest.approx(scored["agent_mean_score"])

    unmarked_err = {**invalid_ep, "meta": {"error": "rate limit"}}
    with pytest.raises(AssertionError, match="end_reason='error'"):
        verify_and_score_episodes(compact_agent + [unmarked_err], solver_eps, tier="hard")

    tampered = [dict(compact_agent[0], score=0.999999), *compact_agent[1:]]
    with pytest.raises(AssertionError, match="score mismatch"):
        verify_and_score_episodes(tampered, solver_eps, tier="hard")

    rep_tampered = audit_text_provider(
        "sanitized_template",
        tier="hard",
        seeds=seeds,
        episodes=tampered,
        solver_episodes=solver_eps,
    )
    assert rep_tampered["checks"]["replay_and_paired_gap"]["passed"] is False
    assert "replay_and_paired_gap" in rep_tampered["failed_checks"]


def test_cli_audit_and_verify_only(tmp_path, capsys):
    out_clean = tmp_path / "clean_audit.json"
    rc = main(["--provider", "sanitized_template", "--tier", "hard", "--seeds", "30-31", "--out", str(out_clean)])
    captured = capsys.readouterr()
    assert rc == 0
    rep = json.loads(captured.out)
    assert rep["all_passed"] is True
    assert json.loads(out_clean.read_text(encoding="utf-8")) == rep

    rc_tpl = main(["--provider", "template", "--tier", "hard", "--seeds", "30-31"])
    rep_tpl = json.loads(capsys.readouterr().out)
    assert rc_tpl == 1
    assert rep_tpl["failed_checks"] == ["anger_words_hygiene"]

    eps_path = tmp_path / "agent_eps.jsonl"
    eps = [asdict(run_episode(Env("hard", s), Heuristic(seed=s))) for s in (30, 31)]
    eps_path.write_text("\n".join(json.dumps(e) for e in eps) + "\n", encoding="utf-8")
    out_verify = tmp_path / "verify.json"
    rc_v = main(["--verify-only", "--episodes", str(eps_path), "--tier", "hard", "--out", str(out_verify)])
    rep_v = json.loads(capsys.readouterr().out)
    assert rc_v == 0
    assert rep_v["passed"] is True
    assert rep_v["n_paired"] == 2

    with pytest.raises(ValueError):
        resolve_text_provider("unknown_provider_xyz")


def test_v16_social_variants_pass_all_6_checks():
    for spec in (
        "v16:v5_full9_cocktail",
        "v1_anchoring_authority_confirmation",
        "v2_recency_bandwagon_sycophancy",
        "v3_grudge_falsemem_misforward",
        "v4_triad_authority_recency_grudge",
        "v16-gemini-stub:v5_full9_cocktail",
    ):
        rep = audit_text_provider(spec, tier="hard", seeds=range(30, 32))
        assert rep["all_passed"] is True, (spec, rep["failed_checks"], rep["checks"])
        assert rep["checks"]["anger_words_hygiene"]["non_decoy_violation_count"] == 0
        assert rep["checks"]["anger_words_hygiene"]["max_other_anger_n2"] == 0
        assert rep["checks"]["solver_calibration_parity"]["false_decoy_ids"] == 0
