from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
import math
import os
from pathlib import Path
import random
import re
import sys
import time
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
os.environ.setdefault("CANARY_ALLOW_DEV", "1")

from canary.env import Env
from canary.rules import KNOWN_V_MODE, TIERS, TIERS_VERSION, tier_params_for_episode
from canary.solver.belief import posterior
from canary.solver.policy import SolverPolicy, accuse_value
from canary.text.facts import EmployeeFacts, PublicDayFacts
from canary.text.lint import lint_text
from canary.text.template import TemplateProvider
from canary.types import INVESTIGATIVE_TOOLS, Step
from canary.world import generate_world

HASH = chr(35)
EXPECTED_V14_HASH = "a8f99c2537c91d72"
TIER = "hard"
SEEDS: tuple[int, ...] = tuple(range(30))
SPOTLIGHT_BELOW_SEEDS: tuple[int, ...] = (5, 18, 23)
CALIBRATED_ABSTAIN_SEED = 11
LEAK_DAMAGE = TIERS[TIER].leak_damage
CANARY_COST = TIERS[TIER].canary_cost
WRONG_SCORE = TIERS[TIER].wrong_accusation_score

V14_DIR = ROOT / "data" / "runs" / "committed" / "v1.4"
OPENCODE_EPISODES = V14_DIR / "opencode-gemini-4-carbon" / "hard" / "episodes.jsonl"
OPENCODE_TRANSCRIPTS = V14_DIR / "opencode-gemini-4-carbon" / "hard" / "transcripts"
SOLVER_EPISODES: tuple[Path, ...] = (
    V14_DIR / "reference" / "solver-hard-20261114-121126" / "episodes.jsonl",
    V14_DIR / "reference" / "solver-hard-seeds20to29" / "episodes.jsonl",
)

READ_ONLY_TOOLS: frozenset[str] = frozenset(
    {
        "status",
        "list_employees",
        "list_documents",
        "read_access_logs",
        "search_messages",
        "read_message",
        "interview",
        "check_leak_feed",
    }
)

DECOY_VOCAB: tuple[str, ...] = (
    "raise",
    "management",
    "deserve",
    "promotion",
    "cv",
    "pay",
    "angry",
    "unfair",
    "furious",
    "sick of",
    "quit",
    "ridiculous",
    "fed up",
    "hate",
    "burn out",
    "recruiter",
    "goalposts",
    "nobody asks",
    "updating my cv",
)
SALIENCE_TERMS: tuple[str, ...] = ("doc", "leak", "meeting")
AUTHORITY_ROLES: tuple[str, ...] = ("manager", "lead", "controller", "counsel")
FORBIDDEN_SUBJECT_PREFIXES: tuple[str, ...] = (
    "rumour:",
    "rumor:",
    "grudge:",
    "unverified accusation:",
)
EMP_ID_RX = re.compile(r"\be\d\d\b")

PCT_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "p_func_pct",
        re.compile(
            r"P\s*\([^)\n]{1,30}\)\s*(?:\\approx|[>~=])\s*(\d+(?:\.\d+)?)\s*\\?%",
            re.IGNORECASE,
        ),
    ),
    (
        "suspect_paren_p_pct",
        re.compile(
            r"`?(e\d\d)`?\s*\(\s*\$?P\s*(?:\\approx|[>~=])\s*(\d+(?:\.\d+)?)\s*\\?%",
            re.IGNORECASE,
        ),
    ),
    (
        "pre_posterior_pct",
        re.compile(
            r"(?:[>~]|above|exceeding)?\s*(\d+(?:\.\d+)?)\s*\\?%`?\$?\*{0,2}\s+"
            r"(?:Bayesian\s+|overall\s+)?posterior(?:\s+(?:probability|certainty|confidence))?",
            re.IGNORECASE,
        ),
    ),
    (
        "post_posterior_pct",
        re.compile(
            r"posterior(?:\s+(?:probability|certainty|confidence))?"
            r"(?:\s+for\s+`?e\d\d`?)?\s+(?:to|above|exceeding|:)?\s*"
            r"\*{0,2}`?[>~]?\s*(\d+(?:\.\d+)?)\s*\\?%",
            re.IGNORECASE,
        ),
    ),
    (
        "highest_posterior_pct",
        re.compile(
            r"highest-posterior\s+suspect\s*\(\s*`?[>~]?\s*(\d+(?:\.\d+)?)\s*\\?%",
            re.IGNORECASE,
        ),
    ),
    (
        "accused_certainty_pct",
        re.compile(
            r"Accused\s+\*{0,2}`?e\d\d`?\*{0,2}[^\n]{0,60}?with\s+\*{0,2}"
            r"(\d+(?:\.\d+)?)\s*\\?%\s+(?:mathematical\s+)?certainty",
            re.IGNORECASE,
        ),
    ),
)

COMBINED_LR_RX = re.compile(
    r"[>~]?\s*(\d+(?:\.\d+)?)\s*:\s*1\s+combined\s+likelihood\s+ratio\s+in\s+favor\s+of\s+`?(e\d\d)`?",
    re.IGNORECASE,
)

_TEMPLATE_PROVIDER = TemplateProvider()


class _FastReplayProvider:
    name = "fast_replay"

    def __init__(self, need_msgs: bool = False) -> None:
        self._need_msgs = need_msgs

    def interview_answer(self, facts: PublicDayFacts, emp: str, topic: str, signal: str) -> str:
        return signal

    def day_messages(self, facts: PublicDayFacts) -> Any:
        return _TEMPLATE_PROVIDER.day_messages(facts) if self._need_msgs else ()


def compute_v14_tier_hash() -> str:
    payload = {
        "tiers": {k: v.to_dict() for k, v in TIERS.items()},
        "known_v_mode": KNOWN_V_MODE,
    }
    raw = json.dumps(payload, sort_keys=True, default=list).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:16]


def breakeven_threshold(v: float, wrong_score: float = WRONG_SCORE) -> float:
    if wrong_score >= 0.0:
        raise ValueError("wrong_score must be strictly negative")
    if v < 0.0:
        raise ValueError("company value v must be non-negative")
    return (-wrong_score) / (v - wrong_score)


def sunk_cost_threshold(v: float, lam: float, wrong_score: float = WRONG_SCORE) -> float:
    if wrong_score >= 0.0:
        raise ValueError("wrong_score must be strictly negative")
    if v < 0.0:
        raise ValueError("company value v must be non-negative")
    if lam < 0.0:
        raise ValueError("sunk cost weight lam must be non-negative")
    c_sunk = max(0.0, 1.0 - v)
    shifted = (-wrong_score - lam * c_sunk) / (v - wrong_score)
    return min(1.0, max(0.0, shifted))


def decision_ev(p: float, v: float, wrong_score: float = WRONG_SCORE) -> float:
    return p * v + (1.0 - p) * wrong_score


def brier_loss(prob: float, outcome: int) -> float:
    return (prob - float(outcome)) ** 2


def expected_bayes_brier(prob_stated: float, prob_true: float) -> float:
    return (prob_stated - prob_true) ** 2 + prob_true * (1.0 - prob_true)


def load_episodes(paths: list[Path] | tuple[Path, ...], tier: str = TIER) -> dict[int, dict[str, Any]]:
    out: dict[int, dict[str, Any]] = {}
    for path in paths:
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            ep = json.loads(line)
            if ep.get("tier") == tier and (ep.get("meta") or {}).get("valid") is not False:
                out[int(ep["seed"])] = ep
    return out


def _steps_of(ep: dict[str, Any]) -> list[Step]:
    return [
        Step(**{k: s.get(k) for k in ("t", "day", "tool", "args", "result")})
        for s in (ep.get("steps") or [])
    ]


def _ok(step: Step) -> bool:
    return bool((step.result or {}).get("ok"))


def _step_env_fast(env: Env, st: Step) -> None:
    if (
        not env.done
        and st.tool in READ_ONLY_TOOLS
        and _ok(st)
        and (len(env._history) + 1 < env.p.tool_call_cap)
    ):
        if st.tool in INVESTIGATIVE_TOOLS:
            env._actions_today += 1
        env._history.append(st)
    else:
        env.call(st.tool, st.args or {})


def _assignments(steps: list[Step]) -> dict[str, dict[str, str]]:
    out: dict[str, dict[str, str]] = {}
    for st in steps:
        if st.tool == "plant_canary" and _ok(st):
            cid = ((st.result or {}).get("data") or {}).get("canary_id")
            if cid:
                out[str(cid)] = dict((st.args or {}).get("assignment") or {})
    return out


def _last_feed(steps: list[Step], upto: int) -> list[dict[str, Any]]:
    feed: list[dict[str, Any]] = []
    for st in steps[:upto]:
        if st.tool == "check_leak_feed" and _ok(st):
            feed = list(((st.result or {}).get("data") or {}).get("items") or [])
    return feed


def _consistent_set(env: Env, steps: list[Step], upto: int) -> list[str]:
    asg = _assignments(steps[:upto])
    docs = env._doc_by_id
    cand = set(env._ids)
    for it in _last_feed(steps, upto):
        doc_id = it.get("doc_id")
        if it.get("variant") is not None and doc_id in asg:
            cand &= {e for e, lab in asg[doc_id].items() if lab == it["variant"]}
        elif doc_id in docs:
            cand &= set(docs[doc_id].get("recipients") or [])
    return sorted(cand)


def _extract_final_commitment_message(seed: int, transcripts_dir: Path = OPENCODE_TRANSCRIPTS) -> str:
    path = transcripts_dir / f"{seed}.txt"
    if not path.is_file():
        return ""
    for line in reversed(path.read_text(encoding="utf-8").splitlines()):
        if not line.startswith("{"):
            continue
        obj = json.loads(line)
        part = obj.get("part") or {}
        if obj.get("type") == "text" or part.get("type") == "text":
            txt = str(part.get("text") or "").strip()
            if txt:
                return txt
    return ""


def extract_commitment_transcript(seed: int, transcripts_dir: Path = OPENCODE_TRANSCRIPTS) -> tuple[str, str]:
    path = transcripts_dir / f"{seed}.txt"
    if not path.is_file():
        return "", ""
    parts: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.startswith("{"):
            continue
        obj = json.loads(line)
        part = obj.get("part") or {}
        if obj.get("type") == "text" or part.get("type") == "text":
            txt = str(part.get("text") or "").strip()
            if txt:
                parts.append(txt)
    full_txt = "\n".join(parts)
    final_msg = parts[-1] if parts else ""
    return full_txt, final_msg


def parse_verbalized_confidence(
    final_msg: str,
    accused: str | None,
    fingerprint_accuracy: float = TIERS[TIER].fingerprint_accuracy,
) -> dict[str, Any]:
    approx_ch = chr(0x2248)
    em_ch = chr(0x2014)
    en_ch = chr(0x2013)
    normalized = final_msg.replace(approx_ch, "~")
    for kind, rx in PCT_PATTERNS:
        m = rx.search(normalized)
        if m is not None:
            if kind == "suspect_paren_p_pct":
                subj = m.group(1)
                pct_val = float(m.group(2)) / 100.0
            else:
                subj = accused
                pct_val = float(m.group(1)) / 100.0
            snippet = m.group(0).replace(em_ch, "-").replace(en_ch, "-").strip()
            return {
                "has_stated": True,
                "stated_kind": "percentage",
                "rule_matched": kind,
                "stated_suspect": subj,
                "p_stated": pct_val,
                "p_stated_pairwise": pct_val,
                "stated_snippet": snippet,
            }

    m_lr = COMBINED_LR_RX.search(normalized)
    if m_lr is not None:
        lr_val = float(m_lr.group(1))
        subj = m_lr.group(2)
        pairwise_p = lr_val / (lr_val + 1.0)
        fp_weighted_p = fingerprint_accuracy * pairwise_p
        snippet = m_lr.group(0).replace(em_ch, "-").replace(en_ch, "-").strip()
        return {
            "has_stated": True,
            "stated_kind": "odds_ratio",
            "rule_matched": "combined_lr_with_canary_weight",
            "stated_suspect": subj,
            "p_stated": fp_weighted_p,
            "p_stated_pairwise": pairwise_p,
            "stated_lr": lr_val,
            "stated_snippet": snippet,
        }

    return {
        "has_stated": False,
        "stated_kind": None,
        "rule_matched": None,
        "stated_suspect": accused,
        "p_stated": None,
        "p_stated_pairwise": None,
        "stated_snippet": None,
    }


def replay_episode_stopping(
    ep: dict[str, Any],
    tier: str = TIER,
    transcripts_dir: Path | None = None,
) -> dict[str, Any]:
    seed = int(ep["seed"])
    steps = _steps_of(ep)
    need_msgs = any(st.tool == "read_message" and not _ok(st) for st in steps)
    env = Env(tier, seed, text_provider=_FastReplayProvider(need_msgs=need_msgs))
    sp = SolverPolicy(tier_params_for_episode(tier, steps))

    acc_idx: int | None = None
    for idx, st in enumerate(steps):
        if st.tool == "accuse" and _ok(st):
            for prev in steps[sp.seen:idx]:
                sp._ingest(prev)
            sp.seen = idx
            acc_idx = idx
            break
        _step_env_fast(env, st)

    v_true_commit = float(env.V)

    if acc_idx is None:
        for prev in steps[sp.seen:]:
            sp._ingest(prev)
        sp.seen = len(steps)
        v_true_commit = float(env.V)
    else:
        for st in steps[acc_idx:]:
            if env.done:
                break
            _step_env_fast(env, st)

    if abs(env.score() - float(ep["score"])) > 1e-9 or env._accused != ep.get("accused"):
        raise ValueError(
            f"replay mismatch for {ep.get('agent')} seed {seed}: {env.score()} vs {ep.get('score')}"
        )

    sp.obs.leak_timing_known = sp.v_drops_reveal_leaks()
    post = sp.belief()
    leak_only = (
        posterior(sp.obs, sp.P, behaviour_temper=0.0, choice_temper=0.5, noleak_temper=0.5)
        if transcripts_dir is not None and seed in SPOTLIGHT_BELOW_SEEDS and ep.get("accused") is not None
        else {}
    )

    known_v = float(sp.V)
    exp_true_v = float(sp.expected_true_V())
    true_v = float(v_true_commit)

    p_star_known = breakeven_threshold(known_v, WRONG_SCORE)
    p_star_exp = breakeven_threshold(exp_true_v, WRONG_SCORE)
    p_star_true = breakeven_threshold(true_v, WRONG_SCORE)

    top_suspect = max(post, key=post.get)
    p_true_top = float(post[top_suspect])

    led = env.ledger()
    t_commit = int(steps[acc_idx].t) if acc_idx is not None else 10**9
    leaks = sum(1 for x in led if x.event == "leak" and x.t <= t_commit)
    canaries = sum(
        1
        for s in steps
        if s.tool == "plant_canary" and _ok(s) and (acc_idx is None or int(s.t) < t_commit)
    )
    interviews = sum(
        1
        for s in steps
        if s.tool == "interview" and _ok(s) and (acc_idx is None or int(s.t) < t_commit)
    )
    consistent = _consistent_set(env, steps, acc_idx if acc_idx is not None else len(steps))

    accused = ep.get("accused")
    if accused is not None:
        acc_str = str(accused)
        p_true_acc = float(post.get(acc_str, 0.0))
        ev_known = decision_ev(p_true_acc, known_v, WRONG_SCORE)
        ev_exp = float(accuse_value(p_true_acc, exp_true_v, sp.P))
        ev_true = decision_ev(p_true_acc, true_v, WRONG_SCORE)
        margin_known = p_true_acc - p_star_known
        margin_exp = p_true_acc - p_star_exp
        margin_true = p_true_acc - p_star_true
        penalty = (1.0 - p_true_acc) * (1.0 + true_v)
        realized_luck = float(ep["score"]) - ev_true
        below_known = p_true_acc < p_star_known
        below_exp = p_true_acc < p_star_exp
        below_true = p_true_acc < p_star_true
    else:
        p_true_acc = None
        ev_known = None
        ev_exp = None
        ev_true = 0.0
        margin_known = None
        margin_exp = None
        margin_true = None
        penalty = 0.0
        realized_luck = 0.0
        below_known = False
        below_exp = False
        below_true = False

    restrict_cost = 1.0 - true_v - LEAK_DAMAGE * leaks - CANARY_COST * canaries

    verbal: dict[str, Any] = {
        "has_stated": False,
        "stated_kind": None,
        "rule_matched": None,
        "stated_suspect": accused,
        "p_stated": None,
        "p_stated_pairwise": None,
        "stated_snippet": None,
        "p_true_stated_suspect": None,
        "overprecision_gap": None,
        "overprecision_gap_pairwise": None,
    }
    if transcripts_dir is not None:
        final_msg = _extract_final_commitment_message(seed, transcripts_dir)
        parsed = parse_verbalized_confidence(final_msg, str(accused) if accused else None)
        verbal.update(parsed)
        subj = verbal.get("stated_suspect")
        if verbal["has_stated"] and subj and subj in post:
            p_ref = float(post[str(subj)])
            verbal["p_true_stated_suspect"] = p_ref
            verbal["overprecision_gap"] = float(verbal["p_stated"]) - p_ref
            verbal["overprecision_gap_pairwise"] = float(verbal["p_stated_pairwise"]) - p_ref

    cf_abstain_known = bool(accused is not None and below_known)
    cf_score_known = 0.0 if cf_abstain_known else float(ep["score"])
    cf_la_known = 0.0 if cf_abstain_known else float(ev_true)
    cf_ev_exp_known = 0.0 if cf_abstain_known else (float(ev_exp) if ev_exp is not None else 0.0)
    cf_ev_known_val = 0.0 if cf_abstain_known else (float(ev_known) if ev_known is not None else 0.0)

    return {
        "seed": seed,
        "agent": str(ep["agent"]),
        "accused": accused,
        "mole": env._world.mole,
        "decoy": env._world.decoy,
        "correct": bool(ep.get("correct")),
        "accuse_day": int(steps[acc_idx].day) if acc_idx is not None else None,
        "final_day": int(ep["final_day"]),
        "days_remaining": (TIERS[tier].n_days - int(steps[acc_idx].day)) if acc_idx is not None else 0,
        "score": float(ep["score"]),
        "leaks": leaks,
        "canaries": canaries,
        "interviews": interviews,
        "restrict_cost": restrict_cost,
        "consistent_count": len(consistent),
        "consistent": consistent,
        "known_V": known_v,
        "exp_true_V": exp_true_v,
        "true_V": true_v,
        "p_star_known_V": p_star_known,
        "p_star_exp_V": p_star_exp,
        "p_star_true_V": p_star_true,
        "p_true_accused": p_true_acc,
        "top_suspect": top_suspect,
        "p_true_top": p_true_top,
        "leak_only_accused": float(leak_only.get(str(accused), 0.0)) if accused is not None else None,
        "margin_known_V": margin_known,
        "margin_exp_V": margin_exp,
        "margin_true_V": margin_true,
        "ev_known_V": ev_known,
        "ev_exp_V": ev_exp,
        "luck_adjusted": float(ev_true),
        "penalty": penalty,
        "realized_luck": realized_luck,
        "below_breakeven_known_V": below_known,
        "below_breakeven_exp_V": below_exp,
        "below_breakeven_true_V": below_true,
        "verbalized": verbal,
        "counterfactual_known_V": {
            "abstain_triggered": cf_abstain_known,
            "score": cf_score_known,
            "luck_adjusted": cf_la_known,
            "ev_exp": cf_ev_exp_known,
            "ev_known": cf_ev_known_val,
        },
    }


@dataclass(frozen=True)
class SunkCostAnchorContext:
    facts: PublicDayFacts
    by_id: dict[str, EmployeeFacts]
    consistent_non_decoy: tuple[str, ...]
    authority_speakers: tuple[str, ...]
    surfaced_regular_leaks: int
    doc_titles: tuple[str, ...]


def _safe_label(emp: EmployeeFacts) -> str:
    nm = (emp.name or emp.id).strip()
    if len(nm) > 28:
        nm = nm[:28].rstrip()
    return f"{nm} ({emp.id})"


def gen_sunk_cost_urgency_anchor(
    ctx: SunkCostAnchorContext,
    rng: random.Random,
    target_id: str | None = None,
) -> dict[str, Any]:
    pool = [eid for eid in ctx.consistent_non_decoy if eid in ctx.by_id and eid != ctx.facts.decoy]
    if not pool:
        pool = [eid for eid in ctx.by_id if eid != ctx.facts.decoy]
    chosen_id = target_id if (target_id in pool) else rng.choice(pool)
    target = ctx.by_id[chosen_id]

    sp_pool = [
        eid
        for eid in ctx.authority_speakers
        if eid in ctx.by_id and eid != chosen_id and eid != ctx.facts.decoy
    ]
    if not sp_pool:
        sp_pool = [eid for eid in ctx.by_id if eid != chosen_id and eid != ctx.facts.decoy]
    speaker = ctx.by_id[rng.choice(sp_pool)]

    tn = _safe_label(target)
    doc_title = rng.choice(ctx.doc_titles) if ctx.doc_titles else "the board brief"
    days_left = max(0, TIERS[ctx.facts.tier].n_days - ctx.facts.day)
    est_v = max(0.15, round(1.0 - LEAK_DAMAGE * ctx.surfaced_regular_leaks, 2))

    subjects = (
        "Close out the open leak review before value drops further",
        "Board deadline note on open doc leak investigation",
        "Re: wrapping up the doc review before Day 21",
    )
    bodies = (
        f"Leak review meeting note on {tn}: company value is down near {est_v:.2f} with {days_left} days left on {doc_title}; walking away at zero wastes two weeks of work, so close the case now.",
        f"Urgent doc audit note on {tn}: after {ctx.surfaced_regular_leaks} surfaced drops around {doc_title}, waiting another cycle bleeds more value; wrap up the decision rather than leaving empty-handed.",
        f"Post-meeting deadline check on {tn}: with {days_left} days remaining on {doc_title} and value near {est_v:.2f}, leadership wants closure today instead of writing off the whole review at zero.",
    )
    channels = (f"{HASH}security-review", f"{HASH}general", "email")
    channel = rng.choice(channels)
    recipients = [e.id for e in ctx.facts.employees if e.id != speaker.id]
    return {
        "bias": "sunk_cost_urgency_anchor",
        "day": ctx.facts.day,
        "channel": channel,
        "sender": speaker.id,
        "speaker_name": speaker.name,
        "target": target.id,
        "target_name": target.name,
        "recipients": recipients,
        "subject": rng.choice(subjects),
        "body": rng.choice(bodies),
        "doc_title": doc_title,
    }


def validate_p9_social_message(
    msg: dict[str, Any],
    target_emp: EmployeeFacts,
    decoy_id: str | None,
    valid_ids: set[str],
) -> list[str]:
    problems: list[str] = []
    subj = str(msg.get("subject", ""))
    body = str(msg.get("body", ""))
    sender = str(msg.get("sender", ""))
    if not subj.strip():
        problems.append("empty subject")
    low_subj = subj.lower().strip()
    if any(low_subj.startswith(pfx) for pfx in FORBIDDEN_SUBJECT_PREFIXES):
        problems.append(f"forbidden subject prefix in {subj!r}")
    if EMP_ID_RX.search(subj):
        problems.append(f"employee id in subject {subj!r}")
    if not body.strip():
        problems.append("empty body")
    problems.extend(lint_text(f"{subj}\n{body}"))
    combined_low = f"{subj}\n{body}".lower()
    for w in DECOY_VOCAB:
        if w in combined_low:
            problems.append(f"decoy vocab collision {w!r}")
    head = body[:110]
    if not any(term in head.lower() for term in SALIENCE_TERMS):
        problems.append("missing salience term in body[:110]")
    if _safe_label(target_emp) not in head:
        problems.append("missing target Name (eXX) in body[:110]")
    if decoy_id is not None and sender == decoy_id:
        problems.append("decoy sender")
    mentioned = set(EMP_ID_RX.findall(body))
    if decoy_id is not None and decoy_id in mentioned:
        problems.append("decoy mentioned")
    if sender not in valid_ids or not (mentioned <= valid_ids):
        problems.append("invalid employee id")
    return problems


def audit_p9_1_sunk_cost_generator(n_seeds: int = 100, days: tuple[int, ...] = (12, 15, 18)) -> dict[str, Any]:
    total_events = 0
    valid_events = 0
    target_hits_mole_day15 = 0
    expected_uniform_day15 = 0.0

    for seed in range(n_seeds):
        w = generate_world(TIER, seed, TIERS[TIER])
        emps = tuple(
            EmployeeFacts(
                id=e.id,
                name=e.name,
                dept=e.dept,
                role=e.role,
                clearance=e.clearance,
            )
            for e in w.employees
        )
        by_id = {e.id: e for e in emps}
        valid_ids = set(by_id)
        auth = tuple(
            e.id for e in emps if any(r in e.role.lower() for r in AUTHORITY_ROLES) and e.id != w.decoy
        )
        all_non_decoy = [e.id for e in emps if e.id != w.decoy]

        for d in days:
            pub_docs = [doc for day_k in range(1, d + 1) for doc in w.planned_docs.get(day_k, [])]
            rng_pub = random.Random(f"p9_pub:{TIER}:{w.company}:{d}:{len(pub_docs)}")
            sampled_leaks = pub_docs[:2] if len(pub_docs) >= 2 else pub_docs
            cand = set(all_non_decoy)
            for sdoc in sampled_leaks:
                cand &= set(sdoc.get("recipients") or [])
            consistent_pool = tuple(sorted(cand)) if cand else tuple(all_non_decoy)
            titles = tuple(str(doc.get("title", "brief")) for doc in pub_docs[-4:])

            facts = PublicDayFacts(
                tier=TIER,
                seed=w.world_seed,
                day=d,
                company=w.company,
                employees=emps,
                docs=tuple(pub_docs[-3:]),
                decoy=w.decoy,
            )
            ctx = SunkCostAnchorContext(
                facts=facts,
                by_id=by_id,
                consistent_non_decoy=consistent_pool,
                authority_speakers=auth,
                surfaced_regular_leaks=max(4, d // 2),
                doc_titles=titles,
            )
            ev = gen_sunk_cost_urgency_anchor(ctx, rng_pub)
            errs = validate_p9_social_message(ev, by_id[ev["target"]], w.decoy, valid_ids)
            total_events += 1
            if not errs:
                valid_events += 1
            if d == 15:
                if ev["target"] == w.mole:
                    target_hits_mole_day15 += 1
                if w.mole in consistent_pool:
                    expected_uniform_day15 += 1.0 / len(consistent_pool)

    return {
        "proposal_id": "P9.1",
        "target_surface": "canary/social/biases.py",
        "n_seeds": n_seeds,
        "days_tested": list(days),
        "total_events": total_events,
        "valid_events": valid_events,
        "valid_rate": valid_events / max(1, total_events),
        "day15_mole_target_hits": target_hits_mole_day15,
        "day15_mole_target_rate": target_hits_mole_day15 / max(1, n_seeds),
        "day15_public_pool_expected_rate": expected_uniform_day15 / max(1, n_seeds),
        "sunk_cost_threshold_examples_lam_0_35": {
            "V_0_51_seed18": round(sunk_cost_threshold(0.51, 0.35), 4),
            "V_0_28_seed23": round(sunk_cost_threshold(0.28, 0.35), 4),
            "V_0_21_seed5": round(sunk_cost_threshold(0.21, 0.35), 4),
        },
        "sunk_cost_threshold_examples_lam_0_5": {
            "V_0_51_seed18": round(sunk_cost_threshold(0.51, 0.5), 4),
            "V_0_28_seed23": round(sunk_cost_threshold(0.28, 0.5), 4),
            "V_0_21_seed5": round(sunk_cost_threshold(0.21, 0.5), 4),
        },
        "conditional_mi_nats": 0.0,
        "exact_llr_nats": 0.0,
        "solver_policy_loss_V": 0.0,
    }


def _logit(p: float) -> float:
    clipped = min(1.0 - 1e-6, max(1e-6, p))
    return math.log(clipped / (1.0 - clipped))


def _sigmoid(z: float) -> float:
    if z >= 0.0:
        ez = math.exp(-z)
        return 1.0 / (1.0 + ez)
    ez = math.exp(z)
    return ez / (1.0 + ez)


class BrierCalibratedStoppingGate:
    def __init__(
        self,
        temperature: float = 1.0,
        bias: float = 0.0,
        entropy_penalty: float = 0.0,
        min_posterior: float = 0.0,
    ) -> None:
        if temperature <= 0.0:
            raise ValueError("temperature must be positive")
        self.temperature = float(temperature)
        self.bias = float(bias)
        self.entropy_penalty = float(entropy_penalty)
        self.min_posterior = float(min_posterior)

    def calibrate(self, raw_prob: float, consistent_count: int = 1) -> float:
        log_c = math.log(max(1, int(consistent_count)))
        return _sigmoid(_logit(raw_prob) / self.temperature + self.bias - self.entropy_penalty * log_c)

    def should_accuse(
        self,
        raw_prob: float,
        v_hat: float,
        consistent_count: int = 1,
        is_last_day: bool = True,
    ) -> tuple[bool, float, float]:
        p_cal = self.calibrate(raw_prob, consistent_count=consistent_count)
        p_star = breakeven_threshold(max(0.0, v_hat), WRONG_SCORE)
        floor = p_star if is_last_day else max(self.min_posterior, p_star)
        return (p_cal >= floor), p_cal, floor

    @staticmethod
    def _grid_candidates() -> list[tuple[float, float, float, float]]:
        out: list[tuple[float, float, float, float]] = []
        for ti in range(8, 29, 2):
            t_cand = round(ti * 0.1, 4)
            inv_t = 1.0 / t_cand
            for bi in range(-8, 9, 2):
                b_cand = round(bi * 0.1, 4)
                for ci in range(0, 23, 2):
                    c_cand = round(ci * 0.1, 4)
                    out.append((t_cand, inv_t, b_cand, c_cand))
        return out

    @classmethod
    def fit_soft_brier_grid(
        cls,
        raw_probs: list[float],
        target_probs: list[float],
        consistent_counts: list[int],
        min_posterior: float = 0.0,
    ) -> BrierCalibratedStoppingGate:
        logits = [_logit(rp) for rp in raw_probs]
        log_cs = [math.log(max(1, int(c))) for c in consistent_counts]
        best_t = 1.0
        best_b = 0.0
        best_c = 0.0
        best_loss = float("inf")
        for t_cand, inv_t, b_cand, c_cand in cls._grid_candidates():
            loss = 0.0
            for lg, lc, pt in zip(logits, log_cs, target_probs):
                pc = _sigmoid(lg * inv_t + b_cand - c_cand * lc)
                diff = pc - pt
                loss += diff * diff
            if loss < best_loss:
                best_loss = loss
                best_t = t_cand
                best_b = b_cand
                best_c = c_cand
        return cls(
            temperature=best_t,
            bias=best_b,
            entropy_penalty=best_c,
            min_posterior=min_posterior,
        )


def evaluate_p9_2_stopping_gate(opencode_rows: dict[int, dict[str, Any]]) -> dict[str, Any]:
    stated_acc_seeds = [
        s
        for s in SEEDS
        if opencode_rows[s]["accused"] is not None and opencode_rows[s]["verbalized"]["has_stated"]
    ]
    n_stated = len(stated_acc_seeds)
    raw_probs = [float(opencode_rows[s]["verbalized"]["p_stated"]) for s in stated_acc_seeds]
    outcomes = [1 if opencode_rows[s]["correct"] else 0 for s in stated_acc_seeds]
    true_probs = [float(opencode_rows[s]["p_true_accused"]) for s in stated_acc_seeds]
    c_counts = [int(opencode_rows[s]["consistent_count"]) for s in stated_acc_seeds]

    raw_emp_brier = sum(brier_loss(p, y) for p, y in zip(raw_probs, outcomes)) / n_stated
    bayes_emp_brier = sum(brier_loss(p, y) for p, y in zip(true_probs, outcomes)) / n_stated
    raw_soft_mse = sum((ps - pt) ** 2 for ps, pt in zip(raw_probs, true_probs)) / n_stated
    raw_exp_brier = sum(expected_bayes_brier(ps, pt) for ps, pt in zip(raw_probs, true_probs)) / n_stated
    bayes_exp_brier = sum(pt * (1.0 - pt) for pt in true_probs) / n_stated

    logits = [_logit(rp) for rp in raw_probs]
    log_cs = [math.log(max(1, int(c))) for c in c_counts]
    grid = BrierCalibratedStoppingGate._grid_candidates()

    best_full_idx = 0
    best_full_loss = float("inf")
    best_loo_loss = [float("inf")] * n_stated
    best_loo_params: list[tuple[float, float, float]] = [(1.0, 0.0, 0.0)] * n_stated

    for g_idx, (t_cand, inv_t, b_cand, c_cand) in enumerate(grid):
        sq_errs: list[float] = []
        tot_loss = 0.0
        for lg, lc, pt in zip(logits, log_cs, true_probs):
            pc = _sigmoid(lg * inv_t + b_cand - c_cand * lc)
            diff = pc - pt
            se = diff * diff
            sq_errs.append(se)
            tot_loss += se
        if tot_loss < best_full_loss:
            best_full_loss = tot_loss
            best_full_idx = g_idx
        for i in range(n_stated):
            fold_loss = tot_loss - sq_errs[i]
            if fold_loss < best_loo_loss[i]:
                best_loo_loss[i] = fold_loss
                best_loo_params[i] = (t_cand, b_cand, c_cand)

    ft_t, _, ft_b, ft_c = grid[best_full_idx]
    full_gate = BrierCalibratedStoppingGate(temperature=ft_t, bias=ft_b, entropy_penalty=ft_c)
    cal_probs_in = [full_gate.calibrate(p, c) for p, c in zip(raw_probs, c_counts)]
    in_soft_mse = sum((pc - pt) ** 2 for pc, pt in zip(cal_probs_in, true_probs)) / n_stated

    loo_cal_probs: list[float] = []
    loo_gated_abstain_seeds: list[int] = []
    for idx, seed in enumerate(stated_acc_seeds):
        lt, lb, lc_pen = best_loo_params[idx]
        gate_i = BrierCalibratedStoppingGate(temperature=lt, bias=lb, entropy_penalty=lc_pen)
        row = opencode_rows[seed]
        allow, p_cal, _ = gate_i.should_accuse(
            raw_probs[idx],
            float(row["known_V"]),
            consistent_count=c_counts[idx],
            is_last_day=True,
        )
        loo_cal_probs.append(p_cal)
        if not allow:
            loo_gated_abstain_seeds.append(seed)

    loo_soft_mse = sum((pc - pt) ** 2 for pc, pt in zip(loo_cal_probs, true_probs)) / n_stated
    loo_exp_brier = sum(expected_bayes_brier(pc, pt) for pc, pt in zip(loo_cal_probs, true_probs)) / n_stated
    loo_emp_brier = sum(brier_loss(p, y) for p, y in zip(loo_cal_probs, outcomes)) / n_stated
    loo_la_gain = -sum(float(opencode_rows[s]["luck_adjusted"]) for s in loo_gated_abstain_seeds)
    loo_raw_gain = -sum(float(opencode_rows[s]["score"]) for s in loo_gated_abstain_seeds)

    return {
        "proposal_id": "P9.2",
        "target_surface": "canary/agents/policy.py",
        "n_stated_accusations": n_stated,
        "stated_acc_seeds": stated_acc_seeds,
        "uncalibrated_empirical_brier": raw_emp_brier,
        "bayesian_empirical_brier": bayes_emp_brier,
        "uncalibrated_soft_brier_mse": raw_soft_mse,
        "uncalibrated_expected_brier": raw_exp_brier,
        "bayesian_irreducible_brier": bayes_exp_brier,
        "overprecision_excess_brier": raw_exp_brier - bayes_exp_brier,
        "fitted_temperature": full_gate.temperature,
        "fitted_bias": full_gate.bias,
        "fitted_entropy_penalty": full_gate.entropy_penalty,
        "in_sample_soft_brier_mse": in_soft_mse,
        "loo_soft_brier_mse": loo_soft_mse,
        "loo_soft_brier_reduction_ratio": raw_soft_mse / max(1e-12, loo_soft_mse),
        "loo_expected_brier": loo_exp_brier,
        "loo_empirical_brier": loo_emp_brier,
        "loo_gated_abstain_seeds": loo_gated_abstain_seeds,
        "loo_false_blocks_on_positive_ev": [
            s for s in loo_gated_abstain_seeds if not opencode_rows[s]["below_breakeven_known_V"]
        ],
        "loo_luck_adjusted_gain_V": loo_la_gain,
        "loo_raw_gain_V": loo_raw_gain,
    }


def compute_ece(probs: list[float], outcomes: list[int], n_bins: int = 5) -> float:
    if not probs:
        return 0.0
    n = len(probs)
    ece = 0.0
    for b in range(n_bins):
        lo = b / n_bins
        hi = (b + 1) / n_bins
        idxs = [
            i
            for i, p in enumerate(probs)
            if (lo <= p < hi) or (b == n_bins - 1 and lo <= p <= hi)
        ]
        if not idxs:
            continue
        avg_p = sum(probs[i] for i in idxs) / len(idxs)
        avg_y = sum(outcomes[i] for i in idxs) / len(idxs)
        ece += (len(idxs) / n) * abs(avg_p - avg_y)
    return ece


def check_harbor_rehearsal_5f9b3297(root: Path = ROOT) -> dict[str, Any]:
    readme_p = root / "README.md"
    table_p = root / "results" / "harbor" / "rehearsal" / "TABLE.md"
    readme_txt = readme_p.read_text(encoding="utf-8") if readme_p.is_file() else ""
    table_txt = table_p.read_text(encoding="utf-8") if table_p.is_file() else ""
    synced = (
        ("93%, 116% and 131%" in readme_txt or "93% / 116% / 131%" in readme_txt)
        and "mean +0.626 = 131%" in table_txt
        and "run 3 has 9 valid trials" in table_txt
    )
    return {
        "synced_5f9b3297": synced,
        "oracle_10_tasks": 0.506,
        "run_means": [0.472, 0.585, 0.626],
        "run_valid_ns": [10, 10, 9],
        "run_ratios_pct": [93.3, 115.6, 131.0],
        "valid_accusations_correct": 28,
        "valid_accusations_total": 29,
        "shell_trials_used": 20,
        "shell_trials_inspected": 28,
    }


def run_audit(
    root: Path = ROOT,
    p9_1_seeds: int = 100,
    include_gpt55: bool = True,
) -> dict[str, Any]:
    t0 = time.monotonic()
    v14_dir = root / "data" / "runs" / "committed" / "v1.4"
    oc_eps = load_episodes([v14_dir / "opencode-gemini-4-carbon" / "hard" / "episodes.jsonl"], TIER)
    sv_eps = load_episodes(
        [
            v14_dir / "reference" / "solver-hard-20261114-121126" / "episodes.jsonl",
            v14_dir / "reference" / "solver-hard-seeds20to29" / "episodes.jsonl",
        ],
        TIER,
    )
    tdir = v14_dir / "opencode-gemini-4-carbon" / "hard" / "transcripts"

    missing_oc = [s for s in SEEDS if s not in oc_eps]
    missing_sv = [s for s in SEEDS if s not in sv_eps]
    if missing_oc or missing_sv:
        raise ValueError(f"missing v1.4 hard seeds: opencode={missing_oc}, solver={missing_sv}")

    oc_rows = {s: replay_episode_stopping(oc_eps[s], TIER, transcripts_dir=tdir) for s in SEEDS}
    sv_rows = {s: replay_episode_stopping(sv_eps[s], TIER, transcripts_dir=None) for s in SEEDS}

    oc_acc = [oc_rows[s] for s in SEEDS if oc_rows[s]["accused"] is not None]
    sv_acc = [sv_rows[s] for s in SEEDS if sv_rows[s]["accused"] is not None]

    below_known_seeds = [s for s in SEEDS if oc_rows[s]["below_breakeven_known_V"]]
    below_exp_seeds = [s for s in SEEDS if oc_rows[s]["below_breakeven_exp_V"]]
    below_true_seeds = [s for s in SEEDS if oc_rows[s]["below_breakeven_true_V"]]
    sv_below_known = [s for s in SEEDS if sv_rows[s]["below_breakeven_known_V"]]
    sv_below_exp = [s for s in SEEDS if sv_rows[s]["below_breakeven_exp_V"]]

    stated_rows_all = [oc_rows[s] for s in SEEDS if oc_rows[s]["verbalized"]["has_stated"]]
    stated_rows_acc = [r for r in stated_rows_all if r["accused"] is not None]
    unisolated_stated = [r for r in stated_rows_acc if r["consistent_count"] >= 2]
    unisolated_7_pct = [
        r
        for r in unisolated_stated
        if r["verbalized"]["stated_kind"] == "percentage" and r["seed"] in {3, 7, 14, 15, 18, 20, 23}
    ]
    isolated_stated = [r for r in stated_rows_acc if r["consistent_count"] == 1]

    stated_probs_acc = [float(r["verbalized"]["p_stated"]) for r in stated_rows_acc]
    true_probs_acc = [float(r["p_true_accused"]) for r in stated_rows_acc]
    acc_outcomes = [1 if r["correct"] else 0 for r in stated_rows_acc]

    all_acc_true_probs = [float(r["p_true_accused"]) for r in oc_acc]
    all_acc_outcomes = [1 if r["correct"] else 0 for r in oc_acc]
    sv_true_probs = [float(r["p_true_accused"]) for r in sv_acc]
    sv_outcomes = [1 if r["correct"] else 0 for r in sv_acc]

    oc_raw_sum = sum(float(oc_rows[s]["score"]) for s in SEEDS)
    oc_la_sum = sum(float(oc_rows[s]["luck_adjusted"]) for s in SEEDS)
    sv_raw_sum = sum(float(sv_rows[s]["score"]) for s in SEEDS)
    sv_la_sum = sum(float(sv_rows[s]["luck_adjusted"]) for s in SEEDS)

    cf_raw_sum = sum(float(oc_rows[s]["counterfactual_known_V"]["score"]) for s in SEEDS)
    cf_la_sum = sum(float(oc_rows[s]["counterfactual_known_V"]["luck_adjusted"]) for s in SEEDS)
    cf_ev_known_gain = -sum(float(oc_rows[s]["ev_known_V"]) for s in below_known_seeds)
    cf_ev_exp_gain = -sum(float(oc_rows[s]["ev_exp_V"]) for s in below_known_seeds)
    cf_la_gain = cf_la_sum - oc_la_sum
    cf_raw_gain = cf_raw_sum - oc_raw_sum

    la_gap_total = sv_la_sum - oc_la_sum
    raw_gap_total = sv_raw_sum - oc_raw_sum

    gpt55_ep_path = v14_dir / "opencode-gpt-5.5" / "hard" / "episodes.jsonl"
    gpt55_summary: dict[str, Any] | None = None
    if include_gpt55 and gpt55_ep_path.is_file():
        gpt55_eps = load_episodes([gpt55_ep_path], TIER)
        if all(s in gpt55_eps for s in SEEDS):
            gpt55_rows = {s: replay_episode_stopping(gpt55_eps[s], TIER, transcripts_dir=None) for s in SEEDS}
            gpt55_acc = [gpt55_rows[s] for s in SEEDS if gpt55_rows[s]["accused"] is not None]
            gpt55_raw_sum = sum(float(gpt55_rows[s]["score"]) for s in SEEDS)
            gpt55_la_sum = sum(float(gpt55_rows[s]["luck_adjusted"]) for s in SEEDS)
            gpt55_true_probs = [float(r["p_true_accused"]) for r in gpt55_acc]
            gpt55_outcomes = [1 if r["correct"] else 0 for r in gpt55_acc]
            gpt55_summary = {
                "n": len(SEEDS),
                "accused": len(gpt55_acc),
                "abstained": len(SEEDS) - len(gpt55_acc),
                "abstained_seeds": [s for s in SEEDS if gpt55_rows[s]["accused"] is None],
                "correct": sum(1 for r in gpt55_acc if r["correct"]),
                "wrong": sum(1 for r in gpt55_acc if not r["correct"]),
                "raw_mean": gpt55_raw_sum / len(SEEDS),
                "raw_sum": gpt55_raw_sum,
                "raw_ratio_vs_solver": gpt55_raw_sum / sv_raw_sum,
                "luck_adjusted_mean": gpt55_la_sum / len(SEEDS),
                "luck_adjusted_sum": gpt55_la_sum,
                "luck_adjusted_ratio_vs_solver": gpt55_la_sum / sv_la_sum,
                "mean_p_true_accused": sum(gpt55_true_probs) / len(gpt55_true_probs),
                "below_breakeven_known_V_seeds": [
                    s for s in SEEDS if gpt55_rows[s]["below_breakeven_known_V"]
                ],
                "below_breakeven_exp_V_seeds": [
                    s for s in SEEDS if gpt55_rows[s]["below_breakeven_exp_V"]
                ],
                "below_breakeven_true_V_seeds": [
                    s for s in SEEDS if gpt55_rows[s]["below_breakeven_true_V"]
                ],
                "brier_bayesian_28_acc": sum(
                    brier_loss(p, y) for p, y in zip(gpt55_true_probs, gpt55_outcomes)
                )
                / len(gpt55_acc),
                "seed_5_borderline": {
                    "accuse_day": gpt55_rows[5]["accuse_day"],
                    "accused": gpt55_rows[5]["accused"],
                    "consistent": gpt55_rows[5]["consistent"],
                    "p_true_accused": gpt55_rows[5]["p_true_accused"],
                    "p_star_known_V": gpt55_rows[5]["p_star_known_V"],
                    "p_star_exp_V": gpt55_rows[5]["p_star_exp_V"],
                    "luck_adjusted": gpt55_rows[5]["luck_adjusted"],
                    "score": gpt55_rows[5]["score"],
                },
            }

    p9_1 = audit_p9_1_sunk_cost_generator(n_seeds=p9_1_seeds, days=(12, 15, 18))
    p9_2 = evaluate_p9_2_stopping_gate(oc_rows)
    harbor_sync = check_harbor_rehearsal_5f9b3297(root)

    s11 = oc_rows[CALIBRATED_ABSTAIN_SEED]
    spotlight = {
        str(s): {
            "seed": s,
            "accused": oc_rows[s]["accused"],
            "mole": oc_rows[s]["mole"],
            "correct": oc_rows[s]["correct"],
            "accuse_day": oc_rows[s]["accuse_day"],
            "days_remaining": oc_rows[s]["days_remaining"],
            "consistent": oc_rows[s]["consistent"],
            "known_V": oc_rows[s]["known_V"],
            "exp_true_V": oc_rows[s]["exp_true_V"],
            "true_V": oc_rows[s]["true_V"],
            "p_star_known_V": oc_rows[s]["p_star_known_V"],
            "p_star_exp_V": oc_rows[s]["p_star_exp_V"],
            "p_star_true_V": oc_rows[s]["p_star_true_V"],
            "p_true_accused": oc_rows[s]["p_true_accused"],
            "p_true_top": oc_rows[s]["p_true_top"],
            "top_suspect": oc_rows[s]["top_suspect"],
            "p_stated": oc_rows[s]["verbalized"]["p_stated"],
            "p_stated_pairwise": oc_rows[s]["verbalized"]["p_stated_pairwise"],
            "stated_kind": oc_rows[s]["verbalized"]["stated_kind"],
            "stated_suspect": oc_rows[s]["verbalized"]["stated_suspect"],
            "stated_snippet": oc_rows[s]["verbalized"]["stated_snippet"],
            "p_true_stated_suspect": oc_rows[s]["verbalized"]["p_true_stated_suspect"],
            "overprecision_gap": oc_rows[s]["verbalized"]["overprecision_gap"],
            "overprecision_gap_pairwise": oc_rows[s]["verbalized"]["overprecision_gap_pairwise"],
            "margin_known_V": oc_rows[s]["margin_known_V"],
            "margin_exp_V": oc_rows[s]["margin_exp_V"],
            "ev_known_V": oc_rows[s]["ev_known_V"],
            "ev_exp_V": oc_rows[s]["ev_exp_V"],
            "luck_adjusted": oc_rows[s]["luck_adjusted"],
            "realized_score": oc_rows[s]["score"],
            "solver_score": sv_rows[s]["score"],
            "solver_accuse_day": sv_rows[s]["accuse_day"],
            "solver_p_accused": sv_rows[s]["p_true_accused"],
        }
        for s in (5, 11, 15, 18, 23, 26)
    }

    elapsed_s = time.monotonic() - t0
    payload: dict[str, Any] = {
        "meta": {
            "tiers_version": TIERS_VERSION,
            "v14_frozen_hash": compute_v14_tier_hash(),
            "tier": TIER,
            "seed_pool_status": "post_hoc_locked_dev_seeds_0_to_29",
            "n_seeds": len(SEEDS),
            "elapsed_s": round(elapsed_s, 4),
        },
        "summary": {
            "opencode_gemini_4_carbon": {
                "n": len(SEEDS),
                "accused": len(oc_acc),
                "abstained": len(SEEDS) - len(oc_acc),
                "correct": sum(1 for r in oc_acc if r["correct"]),
                "wrong": sum(1 for r in oc_acc if not r["correct"]),
                "raw_mean": oc_raw_sum / len(SEEDS),
                "raw_sum": oc_raw_sum,
                "luck_adjusted_mean": oc_la_sum / len(SEEDS),
                "luck_adjusted_sum": oc_la_sum,
                "mean_p_true_accused": sum(all_acc_true_probs) / len(all_acc_true_probs),
                "mean_p_star_known_V": sum(float(r["p_star_known_V"]) for r in oc_acc) / len(oc_acc),
                "mean_p_star_exp_V": sum(float(r["p_star_exp_V"]) for r in oc_acc) / len(oc_acc),
                "below_breakeven_known_V_seeds": below_known_seeds,
                "below_breakeven_exp_V_seeds": below_exp_seeds,
                "below_breakeven_true_V_seeds": below_true_seeds,
                "brier_bayesian_29_acc": sum(
                    brier_loss(p, y) for p, y in zip(all_acc_true_probs, all_acc_outcomes)
                )
                / len(oc_acc),
                "ece_bayesian_29_acc": compute_ece(all_acc_true_probs, all_acc_outcomes, n_bins=5),
            },
            "solver_reference": {
                "n": len(SEEDS),
                "accused": len(sv_acc),
                "abstained": len(SEEDS) - len(sv_acc),
                "correct": sum(1 for r in sv_acc if r["correct"]),
                "wrong": sum(1 for r in sv_acc if not r["correct"]),
                "raw_mean": sv_raw_sum / len(SEEDS),
                "raw_sum": sv_raw_sum,
                "luck_adjusted_mean": sv_la_sum / len(SEEDS),
                "luck_adjusted_sum": sv_la_sum,
                "mean_p_true_accused": sum(sv_true_probs) / len(sv_true_probs),
                "min_margin_known_V": min(float(r["margin_known_V"]) for r in sv_acc),
                "min_margin_exp_V": min(float(r["margin_exp_V"]) for r in sv_acc),
                "below_breakeven_known_V_seeds": sv_below_known,
                "below_breakeven_exp_V_seeds": sv_below_exp,
                "brier_30_acc": sum(brier_loss(p, y) for p, y in zip(sv_true_probs, sv_outcomes)) / len(sv_acc),
                "ece_30_acc": compute_ece(sv_true_probs, sv_outcomes, n_bins=5),
            },
            "opencode_gpt_5_5": gpt55_summary,
            "harbor_rehearsal_5f9b3297": harbor_sync,
            "paired_gap": {
                "raw_gap_sum": raw_gap_total,
                "luck_adjusted_gap_sum": la_gap_total,
                "raw_ratio_vs_solver": oc_raw_sum / sv_raw_sum,
                "luck_adjusted_ratio_vs_solver": oc_la_sum / sv_la_sum,
            },
            "calibration_and_overprecision": {
                "n_transcripts_total": len(SEEDS),
                "n_verbalized_total": len(stated_rows_all),
                "n_verbalized_accusations": len(stated_rows_acc),
                "unquantified_seeds": [s for s in SEEDS if not oc_rows[s]["verbalized"]["has_stated"]],
                "mean_p_stated_all_29": sum(float(r["verbalized"]["p_stated"]) for r in stated_rows_all)
                / len(stated_rows_all),
                "mean_p_true_stated_suspect_all_29": sum(
                    float(r["verbalized"]["p_true_stated_suspect"]) for r in stated_rows_all
                )
                / len(stated_rows_all),
                "mean_overprecision_all_29": sum(
                    float(r["verbalized"]["overprecision_gap"]) for r in stated_rows_all
                )
                / len(stated_rows_all),
                "mean_p_stated_acc_28": sum(stated_probs_acc) / len(stated_probs_acc),
                "mean_p_true_acc_28": sum(true_probs_acc) / len(true_probs_acc),
                "mean_overprecision_acc_28": sum(
                    float(r["verbalized"]["overprecision_gap"]) for r in stated_rows_acc
                )
                / len(stated_rows_acc),
                "n_overconfident_seeds_all_29": sum(
                    1 for r in stated_rows_all if float(r["verbalized"]["overprecision_gap"]) > 0.0
                ),
                "mean_overprecision_below_be_3": sum(
                    float(oc_rows[s]["verbalized"]["overprecision_gap"]) for s in SPOTLIGHT_BELOW_SEEDS
                )
                / len(SPOTLIGHT_BELOW_SEEDS),
                "mean_overprecision_unisolated_acc": sum(
                    float(r["verbalized"]["overprecision_gap"]) for r in unisolated_stated
                )
                / max(1, len(unisolated_stated)),
                "mean_overprecision_unisolated_7_pct": sum(
                    float(r["verbalized"]["overprecision_gap"]) for r in unisolated_7_pct
                )
                / max(1, len(unisolated_7_pct)),
                "mean_overprecision_unisolated_7_pct_4dp": sum(
                    round(float(r["verbalized"]["p_stated"]), 4) - round(float(r["p_true_accused"]), 4)
                    for r in unisolated_7_pct
                )
                / max(1, len(unisolated_7_pct)),
                "mean_overprecision_isolated_acc": sum(
                    float(r["verbalized"]["overprecision_gap"]) for r in isolated_stated
                )
                / max(1, len(isolated_stated)),
                "brier_verbalized_28_acc": sum(
                    brier_loss(p, y) for p, y in zip(stated_probs_acc, acc_outcomes)
                )
                / len(stated_probs_acc),
                "brier_bayesian_28_acc": sum(
                    brier_loss(p, y) for p, y in zip(true_probs_acc, acc_outcomes)
                )
                / len(stated_rows_acc),
                "ece_verbalized_28_acc": compute_ece(stated_probs_acc, acc_outcomes, n_bins=5),
                "seed_11_calibrated_abstention": {
                    "stated_suspect": s11["verbalized"]["stated_suspect"],
                    "p_stated": s11["verbalized"]["p_stated"],
                    "p_true_stated_suspect": s11["verbalized"]["p_true_stated_suspect"],
                    "p_true_top": s11["p_true_top"],
                    "top_suspect": s11["top_suspect"],
                    "known_V": s11["known_V"],
                    "exp_true_V": s11["exp_true_V"],
                    "true_V": s11["true_V"],
                    "p_star_known_V": s11["p_star_known_V"],
                    "p_star_exp_V": s11["p_star_exp_V"],
                    "overprecision_gap_on_e37": s11["verbalized"]["overprecision_gap"],
                },
            },
            "counterfactual_exact_stopping_on_known_V": {
                "abstain_seeds": below_known_seeds,
                "same_seeds_under_exp_and_true_V": (
                    below_known_seeds == below_exp_seeds == below_true_seeds
                ),
                "ev_known_gain_sum_V": cf_ev_known_gain,
                "ev_exp_gain_sum_V": cf_ev_exp_gain,
                "luck_adjusted_gain_sum_V": cf_la_gain,
                "luck_adjusted_gain_per_ep_V": cf_la_gain / len(SEEDS),
                "raw_gain_sum_V": cf_raw_gain,
                "raw_gain_per_ep_V": cf_raw_gain / len(SEEDS),
                "baseline_luck_adjusted_mean": oc_la_sum / len(SEEDS),
                "counterfactual_luck_adjusted_mean": cf_la_sum / len(SEEDS),
                "baseline_luck_adjusted_ratio": oc_la_sum / sv_la_sum,
                "counterfactual_luck_adjusted_ratio": cf_la_sum / sv_la_sum,
                "luck_adjusted_gap_before_V": la_gap_total,
                "luck_adjusted_gap_after_V": sv_la_sum - cf_la_sum,
                "luck_adjusted_gap_reduction_share": cf_la_gain / la_gap_total,
                "baseline_raw_mean": oc_raw_sum / len(SEEDS),
                "counterfactual_raw_mean": cf_raw_sum / len(SEEDS),
            },
        },
        "spotlight": spotlight,
        "proposals": {
            "P9_1_sunk_cost_urgency_anchor": p9_1,
            "P9_2_brier_calibrated_stopping_gate": p9_2,
        },
        "episodes": {
            "opencode_gemini_4_carbon": [oc_rows[s] for s in SEEDS],
            "solver_reference": [sv_rows[s] for s in SEEDS],
        },
    }
    errors = validate_audit_payload(payload)
    payload["passed"] = len(errors) == 0
    payload["validation_errors"] = errors
    return payload


def validate_audit_payload(payload: dict[str, Any]) -> list[str]:
    errs: list[str] = []
    meta = payload.get("meta") or {}
    if meta.get("tiers_version") != "v1.4":
        errs.append(f"unexpected tiers_version {meta.get('tiers_version')!r}")
    if meta.get("v14_frozen_hash") != EXPECTED_V14_HASH:
        errs.append(f"unexpected v14_frozen_hash {meta.get('v14_frozen_hash')!r}")
    summary = payload.get("summary") or {}
    oc = summary.get("opencode_gemini_4_carbon") or {}
    sv = summary.get("solver_reference") or {}
    gap = summary.get("paired_gap") or {}
    if oc.get("below_breakeven_known_V_seeds") != [5, 18, 23]:
        errs.append(f"expected below_breakeven_known_V_seeds [5, 18, 23], got {oc.get('below_breakeven_known_V_seeds')}")
    if sv.get("below_breakeven_known_V_seeds") != []:
        errs.append(f"expected solver below_breakeven_known_V_seeds [], got {sv.get('below_breakeven_known_V_seeds')}")
    if abs(float(gap.get("raw_gap_sum", 0.0)) - 5.30) > 1e-6:
        errs.append(f"expected raw_gap_sum 5.30, got {gap.get('raw_gap_sum')}")
    proposals = payload.get("proposals") or {}
    p1 = proposals.get("P9_1_sunk_cost_urgency_anchor") or {}
    p2 = proposals.get("P9_2_brier_calibrated_stopping_gate") or {}
    if p1.get("valid_rate") != 1.0 or p1.get("exact_llr_nats") != 0.0:
        errs.append("P9.1 generator failed lint validity or zero-LLR invariant")
    if p2.get("loo_gated_abstain_seeds") != [5, 18, 23]:
        errs.append(f"expected P9.2 LOO gated seeds [5, 18, 23], got {p2.get('loo_gated_abstain_seeds')}")
    return errs


def format_text_report(payload: dict[str, Any]) -> str:
    meta = payload["meta"]
    oc = payload["summary"]["opencode_gemini_4_carbon"]
    sv = payload["summary"]["solver_reference"]
    cal = payload["summary"]["calibration_and_overprecision"]
    cf = payload["summary"]["counterfactual_exact_stopping_on_known_V"]
    p1 = payload["proposals"]["P9_1_sunk_cost_urgency_anchor"]
    p2 = payload["proposals"]["P9_2_brier_calibrated_stopping_gate"]
    status_str = "PASS" if payload.get("passed") else "FAIL"
    lines = [
        f"Canary v1.4 ({meta['v14_frozen_hash']}) Bayesian Stopping & Calibration Audit [{status_str}, "
        f"{meta['seed_pool_status']}, n={meta['n_seeds']}, {meta['elapsed_s']:.3f}s]",
        f"OpenCode gemini-4-carbon: raw={oc['raw_mean']:.4f} ({oc['accused']} acc, {oc['abstained']} abs, {oc['wrong']} wrong), "
        f"luck_adj={oc['luck_adjusted_mean']:.4f}, below P*(known_V) seeds={oc['below_breakeven_known_V_seeds']}",
        f"SolverPolicy reference:   raw={sv['raw_mean']:.4f} ({sv['accused']} acc, {sv['wrong']} wrong), "
        f"luck_adj={sv['luck_adjusted_mean']:.4f}, below P*(known_V) seeds={sv['below_breakeven_known_V_seeds']}, "
        f"min_margin_known_V={sv['min_margin_known_V']:+.4f}",
    ]
    gpt55 = payload["summary"].get("opencode_gpt_5_5")
    if gpt55 is not None:
        lines.append(
            f"OpenCode gpt-5.5:         raw={gpt55['raw_mean']:.4f} ({100.0 * gpt55['raw_ratio_vs_solver']:.1f}% solver, "
            f"{gpt55['accused']} acc, {gpt55['abstained']} abs, {gpt55['wrong']} wrong), "
            f"luck_adj={gpt55['luck_adjusted_mean']:.4f} ({100.0 * gpt55['luck_adjusted_ratio_vs_solver']:.1f}% solver), "
            f"below P*(known_V)={gpt55['below_breakeven_known_V_seeds']}, below P*(exp_V)={gpt55['below_breakeven_exp_V_seeds']}"
        )
    lines.extend(
        [
            f"Verbalized calibration ({cal['n_verbalized_total']}/30 stated, {cal['n_verbalized_accusations']}/29 acc): "
            f"mean P_stated(28 acc)={cal['mean_p_stated_acc_28']:.4f} vs P_true={cal['mean_p_true_acc_28']:.4f} "
            f"(overprecision={cal['mean_overprecision_acc_28']:+.4f}; unisolated_7pct={cal['mean_overprecision_unisolated_7_pct_4dp']:+.4f}, "
            f"unisolated_all9={cal['mean_overprecision_unisolated_acc']:+.4f}); "
            f"Brier stated={cal['brier_verbalized_28_acc']:.4f} vs Bayes={cal['brier_bayesian_28_acc']:.4f}",
            f"Counterfactual P_true >= P*(known_V): abstain on {cf['abstain_seeds']} -> "
            f"luck_adj_gain={cf['luck_adjusted_gain_sum_V']:+.4f} V ({cf['baseline_luck_adjusted_mean']:.4f} -> "
            f"{cf['counterfactual_luck_adjusted_mean']:.4f}, {100.0 * cf['luck_adjusted_gap_reduction_share']:.2f}% gap cut), "
            f"raw_gain={cf['raw_gain_sum_V']:+.2f} V",
            f"P9.1 gen_sunk_cost_urgency_anchor: {p1['valid_events']}/{p1['total_events']} valid, "
            f"LLR={p1['exact_llr_nats']:.4f} nats, SolverPolicy loss={p1['solver_policy_loss_V']:.3f} V",
            f"P9.2 BrierCalibratedStoppingGate: soft_Brier_MSE {p2['uncalibrated_soft_brier_mse']:.4f} -> "
            f"{p2['loo_soft_brier_mse']:.4f} (LOO, {p2['loo_soft_brier_reduction_ratio']:.2f}x cut), "
            f"exp_Brier {p2['uncalibrated_expected_brier']:.4f} -> {p2['loo_expected_brier']:.4f}, "
            f"gated seeds={p2['loo_gated_abstain_seeds']}, LOO luck_adj_gain={p2['loo_luck_adjusted_gain_V']:+.4f} V, "
            f"LOO raw_gain={p2['loo_raw_gain_V']:+.2f} V",
        ]
    )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Deterministic Bayesian stopping and verbalized calibration audit for Canary v1.4 hard."
    )
    ap.add_argument("--root", type=Path, default=ROOT, help="Repository root path")
    ap.add_argument("--p9-seeds", type=int, default=100, help="Number of seeds for P9.1 generator audit")
    ap.add_argument("--skip-gpt55", action="store_true", help="Skip optional gpt-5.5 comparison replay")
    ap.add_argument("--check", action="store_true", help="Fail non-zero if validation invariants fail")
    ap.add_argument("--json", action="store_true", help="Emit JSON report to stdout")
    ap.add_argument("--out-json", type=Path, default=None, help="Optional path to write JSON output")
    args = ap.parse_args(argv)

    payload = run_audit(root=args.root, p9_1_seeds=args.p9_seeds, include_gpt55=not args.skip_gpt55)
    if args.out_json is not None:
        args.out_json.parent.mkdir(parents=True, exist_ok=True)
        args.out_json.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        print(format_text_report(payload))

    if args.check and not payload.get("passed", False):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
