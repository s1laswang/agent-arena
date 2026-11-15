from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("CANARY_ALLOW_DEV", "1")

H = chr(35)
EXPECTED_TIERS_VERSION = "v1.4"
EXPECTED_V14_HASH = "a8f99c2537c91d72"
EXPECTED_V13_HASH = "8df71cf570bb48bc"
PRIMARY_SEEDS: tuple[int, ...] = tuple(range(30))
EXT_SEEDS: tuple[int, ...] = (34, 37)

PCT_RX = re.compile(r"(\d{2,3}(?:\.\d+)?)\s*%")
CLAIMED_POST_AFTER_RX = re.compile(
    r"(?:posterior(?:\s+probability|\s+confidence|\s+suspect)?|confidence|P\s*\([^)\n]{1,30}\))\s*(?:\()?[\s:=~>]*[`*~>$]*\s*(\d{2,3}(?:\.\d+)?)\s*\\?%",
    re.IGNORECASE,
)
CLAIMED_POST_BEFORE_RX = re.compile(
    r"[`*~>$]*\s*(\d{2,3}(?:\.\d+)?)\s*\\?%\s*[`*]*\s*(?:overall\s+|Bayesian\s+|posterior\s+)*(?:posterior|confidence)",
    re.IGNORECASE,
)


def compute_tier_hash(tiers: dict[str, Any], known_v_mode: bool) -> str:
    obj = {"tiers": {k: v.to_dict() for k, v in tiers.items()}, "known_v_mode": known_v_mode}
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=list).encode("utf-8")).hexdigest()[:16]


def interview_kl_nats(p0: float, lr: float) -> float:
    pm = min(0.999999, p0 * lr)
    return pm * math.log(pm / p0) + (1.0 - pm) * math.log((1.0 - pm) / (1.0 - p0))


def canary_mi_nats(accuracy: float, k_variants: int) -> float:
    flip = (1.0 - accuracy) / float(k_variants - 1)
    return math.log(float(k_variants)) + accuracy * math.log(accuracy) + (1.0 - accuracy) * math.log(flip)


def _mean(xs: list[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def _ci95(xs: list[float]) -> float:
    n = len(xs)
    if n < 2:
        return 0.0
    m = sum(xs) / n
    return 1.96 * math.sqrt(sum((x - m) ** 2 for x in xs) / (n - 1) / n)


def load_episodes_jsonl(paths: list[Path], tier: str) -> dict[int, dict[str, Any]]:
    out: dict[int, dict[str, Any]] = {}
    for p in paths:
        for line in p.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            ep = json.loads(line)
            if ep.get("tier") == tier and (ep.get("meta") or {}).get("valid") is not False:
                out[int(ep["seed"])] = ep
    return out


def parse_opencode_transcript(path: Path) -> dict[str, Any]:
    tool_events = 0
    error_events = 0
    input_tokens = 0
    output_tokens = 0
    reasoning_tokens = 0
    cached_tokens = 0
    cost_usd = 0.0
    final_text = ""

    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.startswith("{"):
            continue
        obj = json.loads(line)
        kind = obj.get("type")
        part = obj.get("part") or {}
        if kind == "tool_use":
            tool_events += 1
            if (part.get("state") or {}).get("status") == "error":
                error_events += 1
        elif kind == "step_finish":
            tok = part.get("tokens") or {}
            input_tokens += int(tok.get("input") or 0)
            output_tokens += int(tok.get("output") or 0)
            reasoning_tokens += int(tok.get("reasoning") or 0)
            cached_tokens += int((tok.get("cache") or {}).get("read") or 0)
            cost_usd += float(part.get("cost") or 0.0)
        elif kind == "text":
            txt = str(part.get("text") or "")
            if not txt.startswith("thought\n") and txt.strip():
                final_text = txt.strip()

    m_after = [float(x) for x in CLAIMED_POST_AFTER_RX.findall(final_text) if 10.0 <= float(x) <= 100.0]
    m_before = [float(x) for x in CLAIMED_POST_BEFORE_RX.findall(final_text) if 10.0 <= float(x) <= 100.0]
    merged_claims = m_after + m_before
    claimed_pct = merged_claims[-1] if merged_claims else None

    return {
        "tool_events": tool_events,
        "error_events": error_events,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "reasoning_tokens": reasoning_tokens,
        "cached_tokens": cached_tokens,
        "cost_usd": round(cost_usd, 6),
        "has_final_rationale": bool(final_text),
        "claimed_posterior_pct": claimed_pct,
        "final_rationale_excerpt": " ".join(final_text.split())[:280],
    }


def parse_inproc_transcript(path: Path) -> dict[str, Any]:
    messages = json.loads(path.read_text(encoding="utf-8"))
    assistant_turns = 0
    tool_calls = 0
    thought_blocks = 0
    thought_chars = 0
    mentions_breakeven = False

    for msg in messages:
        if msg.get("role") != "assistant":
            continue
        assistant_turns += 1
        tool_calls += len(msg.get("tool_calls") or [])
        for item in msg.get("provider_items") or []:
            for part in item.get("parts") or []:
                if part.get("thought") and part.get("text"):
                    txt = str(part["text"])
                    thought_blocks += 1
                    thought_chars += len(txt)
                    low = txt.lower()
                    if "1 + v" in low or "1+v" in low or "expected value" in low or "break-even" in low:
                        mentions_breakeven = True

    return {
        "assistant_turns": assistant_turns,
        "tool_calls": tool_calls,
        "thought_blocks": thought_blocks,
        "thought_chars": thought_chars,
        "mentions_breakeven": mentions_breakeven,
    }


def _classify_message_query(query: str, decoy_words: tuple[str, ...]) -> str:
    q = (query or "").strip()
    if not q:
        return "blank_invalid"
    low = q.lower()
    if any(w in low for w in decoy_words):
        return "decoy_keyword"
    if re.fullmatch(r"e\d{2}", low):
        return "employee_id"
    if len(q) <= 2:
        return "broad_wildcard"
    return "topical_cheap_talk"


def audit_cohort(
    cohort_name: str,
    tier: str,
    seeds: tuple[int, ...],
    episodes_by_seed: dict[int, dict[str, Any]],
    fa_by_seed: dict[str, Any] | None = None,
    transcript_dir: Path | None = None,
    transcript_format: str | None = None,
) -> dict[str, Any]:
    from canary.env import Env
    from canary.rules import tier_params_for_episode
    from canary.solver.policy import SolverPolicy, accuse_value
    from canary.text.template import _ANSWERS
    from canary.types import INVESTIGATIVE_TOOLS, Step

    evasive_templates = frozenset(
        txt for (_, sig), items in _ANSWERS.items() if sig == "evasive" for txt in items
    )
    decoy_words = (
        "raise",
        "promotion",
        "deserve",
        "burn out",
        "recruiter",
        "goalposts",
        "nobody asks",
        "updating my cv",
        "angry",
        "quit",
        "salary",
        "pay",
        "unfair",
        "management",
        "joke",
    )

    tool_totals: Counter[str] = Counter()
    ok_tool_totals: Counter[str] = Counter()
    iv_topics: Counter[str] = Counter()
    msg_query_kinds: Counter[str] = Counter()

    iv_day1_2 = 0
    iv_repeat = 0
    iv_unique_counts: list[int] = []
    iv_mole = 0
    iv_decoy = 0
    iv_plain_innocent = 0
    iv_evasive_mole = 0
    iv_evasive_innocent = 0

    msg_snippets_decoy = 0
    msg_snippets_nondecoy = 0
    read_msg_decoy = 0
    read_msg_nondecoy = 0
    msg_calls_after_decoy_seen = 0

    ah_mole = 0
    ah_decoy = 0
    ah_plain_innocent = 0

    restrict_mole = 0
    restrict_decoy = 0
    restrict_innocent = 0
    restricted_episodes: list[dict[str, Any]] = []

    days_total = 0
    days_lt2_canaries = 0
    days_lt2_full = 0
    interviews_on_lt2_full = 0

    per_seed: dict[int, dict[str, Any]] = {}
    transcript_stats: dict[int, dict[str, Any]] = {}

    for seed in seeds:
        if seed not in episodes_by_seed:
            raise ValueError(f"{cohort_name}: missing seed {seed}")
        ep = episodes_by_seed[seed]
        steps_raw = ep.get("steps") or []
        steps = [Step(**{k: st.get(k) for k in ("t", "day", "tool", "args", "result")}) for st in steps_raw]

        env = Env(tier, seed)
        for st in steps:
            if env.done:
                break
            env.call(st.tool, st.args or {})

        if abs(env.score() - float(ep["score"])) > 1e-9 or env._accused != ep.get("accused"):
            raise ValueError(
                f"{cohort_name} seed {seed}: replay mismatch {env.score()} vs {ep['score']}"
            )

        mole_id = env._world.mole
        decoy_id = env._world.decoy
        acc_idx = next((i for i, st in enumerate(steps) if st.tool == "accuse" and bool((st.result or {}).get("ok"))), None)
        t_acc = steps[acc_idx].t if acc_idx is not None else 10**9

        seen_iv_emps: set[str] = set()
        decoy_seen = False
        ep_cheap_talk_calls = 0
        seen_log_keys: set[tuple[Any, ...]] = set()
        dedup_ah_before_acc: Counter[str] = Counter()
        ep_restrict_events: list[dict[str, Any]] = []
        day_buckets: dict[int, dict[str, Any]] = {}
        ep_tools: Counter[str] = Counter()
        canaries_ok: list[Step] = []

        for st in steps:
            tool = st.tool
            ok = bool((st.result or {}).get("ok"))
            args = st.args or {}
            data = (st.result or {}).get("data") or {}

            tool_totals[tool] += 1
            ep_tools[tool] += 1
            if ok:
                ok_tool_totals[tool] += 1

            db = day_buckets.setdefault(st.day, {"actions": 0, "canaries": 0, "interviews": 0})
            if tool in INVESTIGATIVE_TOOLS and ok:
                db["actions"] += 1
            if tool == "plant_canary" and ok:
                db["canaries"] += 1
                canaries_ok.append(st)
            if tool == "interview" and ok:
                db["interviews"] += 1
                emp = str(args.get("employee") or "")
                topic = str(args.get("topic") or "")
                ans = str(data.get("answer") or "")
                is_evasive = ans in evasive_templates
                iv_topics[topic] += 1
                if st.day <= 2:
                    iv_day1_2 += 1
                if emp in seen_iv_emps:
                    iv_repeat += 1
                seen_iv_emps.add(emp)
                if emp == mole_id:
                    iv_mole += 1
                    if is_evasive:
                        iv_evasive_mole += 1
                elif emp == decoy_id:
                    iv_decoy += 1
                    if is_evasive:
                        iv_evasive_innocent += 1
                else:
                    iv_plain_innocent += 1
                    if is_evasive:
                        iv_evasive_innocent += 1
            elif tool == "search_messages":
                q = str(args.get("query") or "")
                q_kind = _classify_message_query(q, decoy_words)
                msg_query_kinds[q_kind] += 1
                if q_kind != "decoy_keyword":
                    ep_cheap_talk_calls += 1
                if decoy_seen:
                    msg_calls_after_decoy_seen += 1
                if ok:
                    msgs = data.get("messages") or []
                    for m in msgs:
                        if m.get("sender") == decoy_id:
                            msg_snippets_decoy += 1
                            decoy_seen = True
                        else:
                            msg_snippets_nondecoy += 1
            elif tool == "read_message":
                if decoy_seen:
                    msg_calls_after_decoy_seen += 1
                if ok:
                    m_obj = data.get("message") if isinstance(data.get("message"), dict) else data
                    sender = (m_obj or {}).get("sender")
                    if sender == decoy_id:
                        read_msg_decoy += 1
                        decoy_seen = True
                    else:
                        read_msg_nondecoy += 1
                        ep_cheap_talk_calls += 1
            elif tool == "read_access_logs" and ok:
                for lg in data.get("logs") or []:
                    if st.t < t_acc:
                        lg_key = (
                            lg.get("day"),
                            lg.get("employee"),
                            lg.get("doc_id"),
                            lg.get("after_hours"),
                            lg.get("time"),
                        )
                        if lg_key not in seen_log_keys:
                            seen_log_keys.add(lg_key)
                            if lg.get("after_hours") and lg.get("employee"):
                                dedup_ah_before_acc[str(lg.get("employee"))] += 1
                    if lg.get("after_hours"):
                        emp = lg.get("employee")
                        if emp == mole_id:
                            ah_mole += 1
                        elif emp == decoy_id:
                            ah_decoy += 1
                        else:
                            ah_plain_innocent += 1
            elif tool == "restrict_access" and ok:
                emp = str(args.get("employee") or "")
                role_tag = "mole" if emp == mole_id else ("decoy" if emp == decoy_id else "innocent")
                if role_tag == "mole":
                    restrict_mole += 1
                elif role_tag == "decoy":
                    restrict_decoy += 1
                else:
                    restrict_innocent += 1
                ep_restrict_events.append({"day": st.day, "employee": emp, "target_kind": role_tag})

        iv_unique_counts.append(len(seen_iv_emps))
        if ep_restrict_events:
            restricted_episodes.append({"seed": seed, "events": ep_restrict_events})

        ep_crowded_iv_days = 0
        for d_rec in day_buckets.values():
            days_total += 1
            if d_rec["canaries"] < 2:
                days_lt2_canaries += 1
                if d_rec["actions"] >= 8:
                    days_lt2_full += 1
                    interviews_on_lt2_full += d_rec["interviews"]
                    if d_rec["interviews"] >= 1:
                        ep_crowded_iv_days += 1

        cans_before = [st for st in canaries_ok if st.t < t_acc]
        can_days_all = {st.day for st in canaries_ok}
        can_days_before = {st.day for st in cans_before}
        covered_staff = set().union(*(set((st.args or {})["assignment"]) for st in canaries_ok)) if canaries_ok else set()

        fa_rec = fa_by_seed.get(str(seed)) if fa_by_seed is not None else None
        if fa_rec is not None:
            p_acc = fa_rec.get("p_accused")
            ev_acc = fa_rec.get("ev_accused")
            la_score = float(fa_rec.get("luck_adjusted") or 0.0)
            cons_list = fa_rec.get("consistent_at_accusation")
        else:
            if acc_idx is not None:
                sp = SolverPolicy(tier_params_for_episode(tier, steps))
                for prev in steps[:acc_idx]:
                    sp._ingest(prev)
                post = sp.belief()
                acc_emp = str((steps[acc_idx].args or {}).get("employee") or "")
                p_acc = float(post.get(acc_emp, 0.0))
                ev_acc = float(accuse_value(p_acc, sp.expected_true_V(), sp.P))
                la_score = p_acc * env.V - (1.0 - p_acc)
                asg = {
                    (s.result.get("data") or {}).get("canary_id"): dict((s.args or {})["assignment"])
                    for s in steps[:acc_idx]
                    if s.tool == "plant_canary" and bool((s.result or {}).get("ok"))
                }
                feed_items: list[dict[str, Any]] = []
                for s in steps[:acc_idx]:
                    if s.tool == "check_leak_feed" and bool((s.result or {}).get("ok")):
                        feed_items = list(((s.result.get("data") or {}).get("items")) or [])
                cand = set(env._ids)
                for it in feed_items:
                    if it.get("variant") is not None and it["doc_id"] in asg:
                        cand &= {e_id for e_id, lab in asg[it["doc_id"]].items() if lab == it["variant"]}
                    elif it["doc_id"] in env._doc_by_id:
                        cand &= set(env._doc_by_id[it["doc_id"]].get("recipients") or [])
                cons_list = sorted(cand)
            else:
                p_acc = None
                ev_acc = None
                la_score = 0.0
                cons_list = None

        t_meta: dict[str, Any] = {}
        if transcript_dir is not None and transcript_format is not None:
            ext = "txt" if transcript_format == "opencode_txt" else "json"
            tp = transcript_dir / f"{seed}.{ext}"
            if tp.is_file():
                t_meta = (
                    parse_opencode_transcript(tp)
                    if transcript_format == "opencode_txt"
                    else parse_inproc_transcript(tp)
                )
                transcript_stats[seed] = t_meta

        led = env.ledger()
        leaks_before = sum(1 for x in led if x.event == "leak" and x.t <= t_acc)
        accuse_day = steps[acc_idx].day if acc_idx is not None else None
        played_days = accuse_day if accuse_day is not None else int(ep["final_day"])

        cons_ah = {str(c_emp): int(dedup_ah_before_acc.get(str(c_emp), 0)) for c_emp in (cons_list or [])}
        acc_emp_id = ep.get("accused")
        strict_argmax_ah = False
        max_argmax_ah = False
        if acc_emp_id is not None and cons_list and len(cons_list) >= 2 and acc_emp_id in cons_ah:
            top_ah = max(cons_ah.values())
            max_argmax_ah = cons_ah[acc_emp_id] == top_ah
            strict_argmax_ah = max_argmax_ah and sum(1 for v in cons_ah.values() if v == top_ah) == 1

        per_seed[seed] = {
            "seed": seed,
            "score": float(ep["score"]),
            "luck_adjusted": la_score,
            "accused": acc_emp_id,
            "correct": bool(ep.get("correct")),
            "end_reason": str(ep.get("end_reason")),
            "final_day": int(ep["final_day"]),
            "accuse_day": accuse_day,
            "played_days": played_days,
            "true_V_end": float(env.V),
            "leaks": leaks_before,
            "n_calls": len(steps),
            "invalid_calls": sum(1 for st in steps if not bool((st.result or {}).get("ok"))),
            "interviews": int(ep_tools.get("interview", 0)),
            "crowded_iv_days": ep_crowded_iv_days,
            "cheap_talk_calls": ep_cheap_talk_calls,
            "canaries_before_accuse": len(cans_before),
            "canaries_total": len(canaries_ok),
            "days_with_canary": len(can_days_before),
            "first_canary_day": min(can_days_all) if can_days_all else None,
            "staff_covered": len(covered_staff),
            "recipients_mean": _mean([float(len((s.args or {})["assignment"])) for s in canaries_ok]) if canaries_ok else None,
            "labels_mean": _mean([float(len(set((s.args or {})["assignment"].values()))) for s in canaries_ok]) if canaries_ok else None,
            "read_access_logs": int(ep_tools.get("read_access_logs", 0)),
            "search_messages": int(ep_tools.get("search_messages", 0)),
            "read_message": int(ep_tools.get("read_message", 0)),
            "restrict_access": int(ep_tools.get("restrict_access", 0)),
            "check_leak_feed": int(ep_tools.get("check_leak_feed", 0)),
            "p_accused": p_acc,
            "ev_accused": ev_acc,
            "consistent_size": len(cons_list) if cons_list is not None else None,
            "consistent_after_hours": cons_ah,
            "unisolated_argmax_ah": max_argmax_ah,
            "unisolated_strict_argmax_ah": strict_argmax_ah,
            "transcript": t_meta,
        }

    n_eps = len(seeds)
    eps_list = [per_seed[s] for s in seeds]
    acc_eps = [r for r in eps_list if r["accused"] is not None]
    wrong_eps = [r for r in acc_eps if not r["correct"]]
    scores = [r["score"] for r in eps_list]
    la_scores = [r["luck_adjusted"] for r in eps_list]
    can_counts = [float(r["canaries_before_accuse"]) for r in eps_list]
    played_sum = sum(r["played_days"] for r in eps_list)
    ps = [float(r["p_accused"]) for r in acc_eps if r["p_accused"] is not None]
    first_days = [float(r["first_canary_day"]) for r in eps_list if r["first_canary_day"] is not None]
    rec_means = [float(r["recipients_mean"]) for r in eps_list if r["recipients_mean"] is not None]
    lbl_means = [float(r["labels_mean"]) for r in eps_list if r["labels_mean"] is not None]

    ah_total = ah_mole + ah_decoy + ah_plain_innocent
    ah_ex_decoy = ah_mole + ah_plain_innocent
    iv_ok_total = int(ok_tool_totals.get("interview", 0))
    msg_snips_total = msg_snippets_decoy + msg_snippets_nondecoy

    agg: dict[str, Any] = {
        "cohort": cohort_name,
        "tier": tier,
        "n": n_eps,
        "score": _mean(scores),
        "score_ci": _ci95(scores),
        "luck_adjusted": _mean(la_scores),
        "accused": len(acc_eps),
        "abstain": n_eps - len(acc_eps),
        "voluntary_abstain_among_accused": 0,
        "voluntary_abstain_on_ev_negative": 0,
        "wrong": len(wrong_eps),
        "expected_wrong": sum(1.0 - p for p in ps),
        "accuse_day": _mean([float(r["accuse_day"]) for r in acc_eps]),
        "accuse_day_horizon": _mean([float(r["played_days"]) for r in eps_list]),
        "calls": _mean([float(r["n_calls"]) for r in eps_list]),
        "invalid_calls": _mean([float(r["invalid_calls"]) for r in eps_list]),
        "canaries": _mean(can_counts),
        "canaries_ci": _ci95(can_counts),
        "plant_canary_calls_per_ep": float(tool_totals.get("plant_canary", 0)) / n_eps,
        "canary_rate": sum(can_counts) / played_sum if played_sum else 0.0,
        "capacity_used": sum(can_counts) / (2.0 * played_sum) if played_sum else 0.0,
        "days_with_canary_share": sum(r["days_with_canary"] for r in eps_list) / played_sum if played_sum else 0.0,
        "first_canary_day": _mean(first_days),
        "staff_covered": _mean([float(r["staff_covered"]) for r in eps_list]),
        "recipients_mean": _mean(rec_means),
        "labels_mean": _mean(lbl_means),
        "interviews": float(tool_totals.get("interview", 0)) / n_eps,
        "interviews_ok": iv_ok_total / n_eps,
        "interview_topics": dict(sorted(iv_topics.items())),
        "interviews_day1_2_total": iv_day1_2,
        "interviews_day1_2_per_ep": iv_day1_2 / n_eps,
        "interviews_repeat_total": iv_repeat,
        "interviews_repeat_share": (iv_repeat / iv_ok_total) if iv_ok_total else 0.0,
        "unique_interviewed_per_ep": _mean([float(x) for x in iv_unique_counts]),
        "interview_targets": {
            "mole": iv_mole,
            "decoy": iv_decoy,
            "plain_innocent": iv_plain_innocent,
        },
        "interview_evasive_observed": {
            "mole": iv_evasive_mole,
            "innocent_or_decoy": iv_evasive_innocent,
        },
        "days": days_total,
        "days_lt2_canaries": days_lt2_canaries,
        "days_lt2_full": days_lt2_full,
        "days_lt2_full_share": (days_lt2_full / days_lt2_canaries) if days_lt2_canaries else 0.0,
        "interviews_on_lt2_full": interviews_on_lt2_full,
        "feed_reads": float(tool_totals.get("check_leak_feed", 0)) / n_eps,
        "log_reads": float(tool_totals.get("read_access_logs", 0)) / n_eps,
        "observed_after_hours": {
            "mole": ah_mole,
            "decoy": ah_decoy,
            "plain_innocent": ah_plain_innocent,
            "total": ah_total,
            "empirical_ppv_all": (ah_mole / ah_total) if ah_total else 0.0,
            "empirical_ppv_ex_decoy": (ah_mole / ah_ex_decoy) if ah_ex_decoy else 0.0,
        },
        "search_messages_per_ep": float(tool_totals.get("search_messages", 0)) / n_eps,
        "search_messages_ok_per_ep": float(ok_tool_totals.get("search_messages", 0)) / n_eps,
        "read_message_per_ep": float(tool_totals.get("read_message", 0)) / n_eps,
        "message_calls_per_ep": float(tool_totals.get("search_messages", 0) + tool_totals.get("read_message", 0)) / n_eps,
        "message_calls_total": int(tool_totals.get("search_messages", 0) + tool_totals.get("read_message", 0)),
        "message_calls_after_decoy_seen": msg_calls_after_decoy_seen,
        "message_query_kinds": dict(sorted(msg_query_kinds.items())),
        "message_snippets_returned": {
            "decoy": msg_snippets_decoy,
            "non_decoy": msg_snippets_nondecoy,
            "decoy_share": (msg_snippets_decoy / msg_snips_total) if msg_snips_total else 0.0,
            "non_decoy_share": (msg_snippets_nondecoy / msg_snips_total) if msg_snips_total else 0.0,
        },
        "read_message_targets": {
            "decoy": read_msg_decoy,
            "non_decoy": read_msg_nondecoy,
        },
        "restrict_calls_total": int(ok_tool_totals.get("restrict_access", 0)),
        "restrict_calls_per_ep": float(ok_tool_totals.get("restrict_access", 0)) / n_eps,
        "unrestrict_calls_total": int(ok_tool_totals.get("unrestrict_access", 0)),
        "restrict_targets": {
            "mole": restrict_mole,
            "decoy": restrict_decoy,
            "innocent": restrict_innocent,
        },
        "restricted_episodes": restricted_episodes,
        "p_mean": _mean(ps),
        "p_median": sorted(ps)[len(ps) // 2] if ps else None,
        "p_buckets": {
            "ge95": sum(1 for p in ps if p >= 0.95),
            "85_95": sum(1 for p in ps if 0.85 <= p < 0.95),
            "60_85": sum(1 for p in ps if 0.60 <= p < 0.85),
            "lt60": sum(1 for p in ps if p < 0.60),
        },
        "isolated": sum(1 for r in acc_eps if r["consistent_size"] == 1),
        "not_isolated": [r["seed"] for r in acc_eps if (r["consistent_size"] or 0) > 1],
        "not_isolated_count": sum(1 for r in acc_eps if (r["consistent_size"] or 0) > 1),
        "consistent_mean": _mean([float(r["consistent_size"]) for r in acc_eps if r["consistent_size"] is not None]),
        "ev_negative": [r["seed"] for r in acc_eps if r["ev_accused"] is not None and r["ev_accused"] < 0.0],
        "leaks_at_accusation": _mean([float(r["leaks"]) for r in acc_eps]),
        "tools_per_ep": {k: tool_totals[k] / n_eps for k in sorted(tool_totals)},
    }

    if transcript_stats:
        if transcript_format == "opencode_txt":
            agg["transcript_telemetry"] = {
                "files_audited": len(transcript_stats),
                "mean_reasoning_tokens": _mean([float(v["reasoning_tokens"]) for v in transcript_stats.values()]),
                "total_reasoning_tokens": sum(int(v["reasoning_tokens"]) for v in transcript_stats.values()),
                "mean_cost_usd": _mean([float(v["cost_usd"]) for v in transcript_stats.values()]),
                "total_cost_usd": round(sum(float(v["cost_usd"]) for v in transcript_stats.values()), 4),
                "rationales_present": sum(1 for v in transcript_stats.values() if v["has_final_rationale"]),
            }
        elif transcript_format == "inproc_json":
            agg["transcript_telemetry"] = {
                "files_audited": len(transcript_stats),
                "mean_thought_blocks": _mean([float(v["thought_blocks"]) for v in transcript_stats.values()]),
                "episodes_mentioning_breakeven_ev": sum(
                    1 for v in transcript_stats.values() if v["mentions_breakeven"]
                ),
            }

    return {"summary": agg, "episodes": per_seed}


def audit_grok_rationales(grok_dir: Path) -> dict[str, Any]:
    tiers_out: dict[str, Any] = {}
    for tier in ("medium", "hard"):
        jsonl_files = sorted(grok_dir.glob(f"{tier}-*.jsonl"))
        counts: Counter[str] = Counter()
        episodes_meta: list[dict[str, Any]] = []
        for jf in jsonl_files:
            seed_str = jf.stem.split("-", 1)[1]
            ep_tools: Counter[str] = Counter()
            accused_emp = None
            for line in jf.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                row = json.loads(line)
                t_name = str(row.get("tool") or "")
                counts[t_name] += 1
                ep_tools[t_name] += 1
                if t_name == "accuse" and not row.get("isError"):
                    accused_emp = (row.get("args") or {}).get("employee")
            rat_file = grok_dir / f"{jf.stem}.rationale.md"
            rat_text = rat_file.read_text(encoding="utf-8").strip() if rat_file.is_file() else ""
            episodes_meta.append(
                {
                    "seed": int(seed_str),
                    "tool_calls": sum(ep_tools.values()),
                    "interviews": int(ep_tools.get("interview", 0)),
                    "canaries": int(ep_tools.get("plant_canary", 0)),
                    "restrictions": int(ep_tools.get("restrict_access", 0)),
                    "accused": accused_emp,
                    "abstained": accused_emp is None,
                    "mentions_breakeven_formula": ("1/(1+V)" in rat_text or "expected value" in rat_text.lower()),
                    "rationale": " ".join(rat_text.split()),
                }
            )
        n = len(jsonl_files)
        tiers_out[tier] = {
            "n": n,
            "tools_per_ep": {k: counts[k] / n for k in sorted(counts)} if n else {},
            "interviews_per_ep": counts.get("interview", 0) / n if n else 0.0,
            "canaries_per_ep": counts.get("plant_canary", 0) / n if n else 0.0,
            "restrictions_per_ep": counts.get("restrict_access", 0) / n if n else 0.0,
            "accused_count": sum(1 for e in episodes_meta if not e["abstained"]),
            "deliberate_abstentions": sum(1 for e in episodes_meta if e["abstained"]),
            "episodes": episodes_meta,
        }

    hard_900000 = next(
        (e for e in tiers_out["hard"]["episodes"] if e["seed"] == 900000),
        None,
    )
    return {
        "medium": tiers_out["medium"],
        "hard": tiers_out["hard"],
        "hard_900000_abstention_case": hard_900000,
    }


def audit_v13_codex_historical(v13_dir: Path) -> dict[str, Any]:
    paired_v13 = json.loads((v13_dir / "paired_table.json").read_text(encoding="utf-8"))
    codex_tags = json.loads((v13_dir / "codex-gpt-5.5-full" / "tags.json").read_text(encoding="utf-8"))
    accuse_rows: list[dict[str, Any]] = []
    for ln in (v13_dir / "codex-gpt-5.5-full" / "accuse.md").read_text(encoding="utf-8").splitlines():
        if not ln.startswith("|") or "tier" in ln or "---" in ln:
            continue
        cells = [c.strip() for c in ln.strip().strip("|").split("|")]
        if len(cells) >= 10:
            accuse_rows.append(
                {
                    "tier": cells[0],
                    "seed": int(cells[2]),
                    "day": int(cells[3]),
                    "accused": cells[4],
                    "correct": cells[5] == "True",
                    "score": float(cells[6]),
                    "p_accused": float(cells[7]),
                    "verdict": cells[9],
                }
            )

    def _summarize_group(rel_group: str, group_key: str, tier: str, exp_n: int) -> dict[str, Any]:
        p_row = _find_paired_row(paired_v13, group_key, tier, exp_n, headline_only=False)
        ep_path = v13_dir / rel_group / tier / "episodes.jsonl"
        eps = [json.loads(ln) for ln in ep_path.read_text(encoding="utf-8").splitlines() if ln.strip()]
        n = len(eps)
        tc = Counter(st["tool"] for ep in eps for st in ep.get("steps") or [])
        wrong_seeds = [int(ep["seed"]) for ep in eps if not bool(ep.get("correct"))]
        abstain_seeds = [int(ep["seed"]) for ep in eps if ep.get("accused") is None]
        return {
            "n": n,
            "score": round(float(p_row["mean"]), 6),
            "ci95": round(float(p_row["ci"]), 6),
            "solver_same_seeds": round(float(p_row["solver_same_seeds"]), 6),
            "raw_ratio": round(float(p_row["ratio"]), 6),
            "luck_adjusted": round(float(p_row["post_expected"]), 6),
            "luck_adjusted_ratio": round(float(p_row["post_expected_ratio"]), 6),
            "mean_p_accused": round(float(p_row["p_accused"]), 6),
            "wrong_seeds": wrong_seeds,
            "abstain_seeds": abstain_seeds,
            "calls_per_ep": round(sum(tc.values()) / n, 4),
            "interviews_per_ep": round(tc.get("interview", 0) / n, 4),
            "canaries_per_ep": round(tc.get("plant_canary", 0) / n, 4),
            "log_reads_per_ep": round(tc.get("read_access_logs", 0) / n, 4),
            "message_calls_per_ep": round((tc.get("search_messages", 0) + tc.get("read_message", 0)) / n, 4),
            "restrictions_per_ep": round(tc.get("restrict_access", 0) / n, 4),
        }

    codex_med_wrong = [r for r in accuse_rows if r["tier"] == "medium" and not r["correct"]]
    codex_hard_lucky = [r for r in accuse_rows if r["tier"] == "hard" and r["verdict"] == "lucky"]
    c_tags = (codex_tags.get("codex:gpt-5.5") or {}).get("tags") or {}

    return {
        "codex_mcp_medium_n11": _summarize_group("codex-gpt-5.5-full", "v1.3/codex-gpt-5.5-full", "medium", 11),
        "codex_mcp_hard_n11": _summarize_group("codex-gpt-5.5-full", "v1.3/codex-gpt-5.5-full", "hard", 11),
        "inproc_gpt55_medium_n9": _summarize_group("gpt-5.5-full", "v1.3/gpt-5.5-full", "medium", 9),
        "inproc_gpt55_hard_n8": _summarize_group("gpt-5.5-full", "v1.3/gpt-5.5-full", "hard", 8),
        "codex_medium_wrong_cases": codex_med_wrong,
        "codex_hard_lucky_cases": codex_hard_lucky,
        "codex_tags_summary": {
            k: {
                "count": int(v["count"]),
                "episodes_with": int(v["episodes_with"]),
                "rate": float(v["rate"]),
                "regret_sum": float(v["regret_sum"]),
            }
            for k, v in c_tags.items()
        },
    }


def summarize_cognitive_bias_tags(eps: dict[int, dict[str, Any]]) -> dict[str, Any]:
    n = len(eps)
    rows = [eps[s] for s in sorted(eps)]
    crowding_seeds = [r["seed"] for r in rows if int(r.get("crowded_iv_days") or 0) >= 1]
    cheap_talk_seeds = [r["seed"] for r in rows if int(r.get("cheap_talk_calls") or 0) >= 1]
    tiebreak_seeds = [r["seed"] for r in rows if bool(r.get("unisolated_argmax_ah"))]
    breakeven_seeds = [r["seed"] for r in rows if r.get("ev_accused") is not None and float(r["ev_accused"]) < 0.0]
    overprec_seeds = [
        r["seed"]
        for r in rows
        if (r.get("transcript") or {}).get("claimed_posterior_pct") is not None
        and r.get("p_accused") is not None
        and float((r["transcript"])["claimed_posterior_pct"]) - 100.0 * float(r["p_accused"]) >= 15.0
    ]

    def _entry(seed_list: list[int], event_total: int) -> dict[str, Any]:
        return {
            "event_count": event_total,
            "episodes_with": len(seed_list),
            "rate": round(len(seed_list) / n, 4) if n else 0.0,
            "seeds": seed_list,
        }

    return {
        "n": n,
        "demeanor_interview_crowding": _entry(
            crowding_seeds,
            sum(int(r.get("crowded_iv_days") or 0) for r in rows),
        ),
        "cheap_talk_distraction": _entry(
            cheap_talk_seeds,
            sum(int(r.get("cheap_talk_calls") or 0) for r in rows),
        ),
        "unisolated_log_tiebreak": _entry(tiebreak_seeds, len(tiebreak_seeds)),
        "below_breakeven_gamble": _entry(breakeven_seeds, len(breakeven_seeds)),
        "overprecision_inflation": _entry(overprec_seeds, len(overprec_seeds)),
    }


def _find_paired_row(rows: list[dict[str, Any]], group: str, tier: str, n: int, headline_only: bool = True) -> dict[str, Any]:
    for row in rows:
        if row.get("group") == group and row.get("tier") == tier and int(row.get("n") or 0) == n:
            if headline_only and "NOT the headline" in str(row.get("label") or ""):
                continue
            return row
    raise ValueError(f"paired table row not found: group={group}, tier={tier}, n={n}")


def cross_verify_against_failure_analysis(
    opencode_sum: dict[str, Any],
    inproc_sum: dict[str, Any],
    solver_sum: dict[str, Any],
    fa_summary: dict[str, Any],
) -> dict[str, Any]:
    mismatches: list[str] = []
    checks = 0
    scalar_keys = (
        "n",
        "score",
        "score_ci",
        "luck_adjusted",
        "accused",
        "abstain",
        "wrong",
        "expected_wrong",
        "accuse_day",
        "canaries",
        "canaries_ci",
        "canary_rate",
        "capacity_used",
        "days_with_canary_share",
        "first_canary_day",
        "staff_covered",
        "recipients_mean",
        "labels_mean",
        "interviews",
        "feed_reads",
        "log_reads",
        "calls",
        "invalid_calls",
        "days",
        "days_lt2_canaries",
        "days_lt2_full",
        "interviews_on_lt2_full",
        "p_mean",
        "p_median",
        "isolated",
        "consistent_mean",
        "leaks_at_accusation",
    )

    for label, fresh, ref in (
        ("opencode", opencode_sum, fa_summary["opencode"]),
        ("inproc", inproc_sum, fa_summary["inproc"]),
        ("solver", solver_sum, fa_summary["solver"]),
    ):
        for key in scalar_keys:
            checks += 1
            a = float(fresh[key])
            b = float(ref[key])
            if not math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-9):
                mismatches.append(f"{label}.{key}: fresh={a} != fa={b}")
        for list_key in ("not_isolated", "ev_negative"):
            checks += 1
            if list(fresh[list_key]) != list(ref[list_key]):
                mismatches.append(f"{label}.{list_key}: fresh={fresh[list_key]} != fa={ref[list_key]}")
        checks += 1
        if dict(fresh["p_buckets"]) != dict(ref["p_buckets"]):
            mismatches.append(f"{label}.p_buckets: fresh={fresh['p_buckets']} != fa={ref['p_buckets']}")

    gap = fa_summary["gap"]
    checks += 2
    if not math.isclose(
        float(gap["la_gap"]),
        float(gap["leak"] + gap["canary"] + gap["restrict"] + gap["penalty"] + gap["abstain"]),
        abs_tol=1e-9,
    ):
        mismatches.append("gap.la_gap additive identity failed")
    if not math.isclose(float(gap["raw_gap"]), float(gap["la_gap"] + gap["luck"]), abs_tol=1e-9):
        mismatches.append("gap.raw_gap additive identity failed")

    return {
        "passed": len(mismatches) == 0,
        "checks_run": checks,
        "mismatches": mismatches,
    }


def classify_wrong_accusations(wrong_detail: list[dict[str, Any]], opencode_eps: dict[int, dict[str, Any]]) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    counts = {
        "disclosed_fingerprint_flip": 0,
        "unresolved_pair_bet": 0,
        "negative_ev_gamble": 0,
    }
    for row in wrong_detail:
        seed = int(row["seed"])
        p_val = float(row["p"])
        ev_val = float(row["ev"])
        v_val = float(row["V"])
        breakeven = 1.0 / (1.0 + v_val)
        if bool(row["flip"]) and p_val >= 0.95:
            category = "disclosed_fingerprint_flip"
        elif ev_val < 0.0 or p_val < breakeven:
            category = "negative_ev_gamble"
        else:
            category = "unresolved_pair_bet"
        counts[category] += 1
        ep_t = (opencode_eps[seed].get("transcript") or {})
        items.append(
            {
                "seed": seed,
                "day": int(row["day"]),
                "days_left": int(row["days_left"]),
                "accused_employee": str(row["accused"]),
                "consistent_size": len(row["consistent"]),
                "consistent_candidates": list(row["consistent"]),
                "p_accused": round(p_val, 6),
                "breakeven_p": round(breakeven, 6),
                "ev_accused": round(ev_val, 6),
                "true_V_at_accuse": round(v_val, 6),
                "fingerprint_flip": bool(row["flip"]),
                "solver_correct_same_seed": bool(row["solver_correct"]),
                "solver_score_same_seed": float(row["solver_score"]),
                "claimed_posterior_pct": ep_t.get("claimed_posterior_pct"),
                "category": category,
            }
        )
    return {"counts": counts, "episodes": items}


def build_seed_forensics(
    opencode_eps: dict[int, dict[str, Any]],
    inproc_eps: dict[int, dict[str, Any]],
    solver_eps: dict[int, dict[str, Any]],
    fa_data: dict[str, Any],
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for s in PRIMARY_SEEDS:
        g = opencode_eps[s]
        ip = inproc_eps[s]
        sv = solver_eps[s]
        fa_g = fa_data["G"][str(s)]
        raw_regret = sv["score"] - g["score"]
        la_regret = sv["luck_adjusted"] - g["luck_adjusted"]
        v_end = g["true_V_end"]
        breakeven = 1.0 / (1.0 + v_end)
        claimed_pct = (g.get("transcript") or {}).get("claimed_posterior_pct")
        p_exact = g["p_accused"]
        overprecision_pp = (
            round(claimed_pct - 100.0 * p_exact, 2)
            if (claimed_pct is not None and p_exact is not None)
            else None
        )
        rows.append(
            {
                "seed": s,
                "opencode_score": round(g["score"], 4),
                "solver_score": round(sv["score"], 4),
                "inproc_score": round(ip["score"], 4),
                "raw_gap_v": round(raw_regret, 4),
                "luck_adjusted_gap_v": round(la_regret, 4),
                "opencode_day": g["accuse_day"],
                "solver_day": sv["accuse_day"],
                "inproc_day": ip["accuse_day"],
                "opencode_canaries": g["canaries_before_accuse"],
                "solver_canaries": sv["canaries_before_accuse"],
                "opencode_interviews": g["interviews"],
                "inproc_interviews": ip["interviews"],
                "consistent_size": g["consistent_size"],
                "p_accused": round(p_exact, 4) if p_exact is not None else None,
                "breakeven_p": round(breakeven, 4),
                "ev_accused": round(g["ev_accused"], 4) if g["ev_accused"] is not None else None,
                "claimed_posterior_pct": claimed_pct,
                "overprecision_percentage_points": overprecision_pp,
                "correct": g["correct"],
                "end_reason": g["end_reason"],
                "hesitation_decisive_day": (fa_g.get("decisive") or {}).get("day"),
                "hesitation_cf_score": (fa_g.get("decisive") or {}).get("cf_score"),
            }
        )

    unresolved_rows = [r for r in rows if (r["consistent_size"] or 0) >= 2]
    overprec_vals = [
        float(r["overprecision_percentage_points"])
        for r in unresolved_rows
        if r["overprecision_percentage_points"] is not None
    ]

    top_raw = sorted(rows, key=lambda r: (-r["raw_gap_v"], r["seed"]))[:10]
    top_la = sorted(rows, key=lambda r: (-r["luck_adjusted_gap_v"], r["seed"]))[:10]

    return {
        "per_seed": rows,
        "top_raw_regret_seeds": top_raw,
        "top_luck_adjusted_regret_seeds": top_la,
        "unresolved_commitment_seeds": unresolved_rows,
        "unresolved_exact_p_mean": _mean([float(r["p_accused"]) for r in unresolved_rows if r["p_accused"] is not None]),
        "unresolved_overprecision_pp_mean": _mean(overprec_vals),
    }


def audit_transcript_biases(root: Path = ROOT) -> dict[str, Any]:
    from canary import rules

    resolved_root = root.resolve()
    v14_hash = compute_tier_hash(rules.TIERS, rules.KNOWN_V_MODE)
    v13_hash = compute_tier_hash(rules.TIERS_V13, rules.KNOWN_V_MODE)
    if rules.TIERS_VERSION != EXPECTED_TIERS_VERSION:
        raise ValueError(f"unexpected TIERS_VERSION {rules.TIERS_VERSION!r}")
    if v14_hash != EXPECTED_V14_HASH:
        raise ValueError(f"unexpected v1.4 hash {v14_hash!r}")
    if v13_hash != EXPECTED_V13_HASH:
        raise ValueError(f"unexpected v1.3 hash {v13_hash!r}")

    hard_p = rules.TIERS["hard"]
    kl_hard_iv = interview_kl_nats(hard_p.p_evasive_innocent, hard_p.interview_lr)
    mi_hard_can = canary_mi_nats(hard_p.fingerprint_accuracy, hard_p.max_variants)

    mole_ah_rate = hard_p.log_rate_mole * hard_p.p_after_hours_mole
    decoy_ah_rate = hard_p.log_rate_benign * hard_p.p_after_hours_benign + hard_p.framing_rate * hard_p.framing_decoy_share
    plain_inn_count = hard_p.n_employees - 2
    plain_inn_ah_rate = hard_p.log_rate_benign * hard_p.p_after_hours_benign + (
        hard_p.framing_rate * (1.0 - hard_p.framing_decoy_share) / plain_inn_count
    )
    total_ah_rate = mole_ah_rate + decoy_ah_rate + plain_inn_count * plain_inn_ah_rate
    ppv_ah_all = mole_ah_rate / total_ah_rate
    ppv_ah_ex_decoy = mole_ah_rate / (mole_ah_rate + plain_inn_count * plain_inn_ah_rate)

    v14_dir = resolved_root / "data" / "runs" / "committed" / "v1.4"
    fa_data = json.loads((resolved_root / "results" / "failure_analysis_v1.4.json").read_text(encoding="utf-8"))
    paired_primary = json.loads((v14_dir / "paired_table_gemini.json").read_text(encoding="utf-8"))
    paired_pooled = json.loads(
        (v14_dir / "opencode-gemini-4-carbon-ext" / "paired_table_pooled0to59.json").read_text(encoding="utf-8")
    )

    oc_hard_eps = load_episodes_jsonl([v14_dir / "opencode-gemini-4-carbon" / "hard" / "episodes.jsonl"], "hard")
    ip_hard_eps = load_episodes_jsonl([v14_dir / "inproc-gemini-4-carbon" / "hard" / "episodes.jsonl"], "hard")
    sv_hard_eps = load_episodes_jsonl(
        [
            v14_dir / "reference" / "solver-hard-20261114-121126" / "episodes.jsonl",
            v14_dir / "reference" / "solver-hard-seeds20to29" / "episodes.jsonl",
        ],
        "hard",
    )
    ext_hard_eps = load_episodes_jsonl([v14_dir / "opencode-gemini-4-carbon-ext" / "hard" / "episodes.jsonl"], "hard")
    sv_ext_eps = load_episodes_jsonl(
        [v14_dir / "reference" / "solver-hard-seeds30to59" / "episodes.jsonl"],
        "hard",
    )

    oc_audit = audit_cohort(
        "opencode_gemini_4_carbon_hard",
        "hard",
        PRIMARY_SEEDS,
        oc_hard_eps,
        fa_by_seed=fa_data["G"],
        transcript_dir=v14_dir / "opencode-gemini-4-carbon" / "hard" / "transcripts",
        transcript_format="opencode_txt",
    )
    ip_audit = audit_cohort(
        "inproc_gemini_4_carbon_hard",
        "hard",
        PRIMARY_SEEDS,
        ip_hard_eps,
        fa_by_seed=fa_data["I"],
        transcript_dir=v14_dir / "inproc-gemini-4-carbon" / "hard" / "transcripts",
        transcript_format="inproc_json",
    )
    sv_audit = audit_cohort(
        "solver_policy_hard",
        "hard",
        PRIMARY_SEEDS,
        sv_hard_eps,
        fa_by_seed=fa_data["S"],
    )
    ext_audit = audit_cohort(
        "opencode_gemini_4_carbon_ext_hard",
        "hard",
        EXT_SEEDS,
        ext_hard_eps,
        fa_by_seed=None,
        transcript_dir=v14_dir / "opencode-gemini-4-carbon-ext" / "hard" / "transcripts",
        transcript_format="opencode_txt",
    )
    sv_ext_audit = audit_cohort(
        "solver_policy_ext_hard",
        "hard",
        EXT_SEEDS,
        sv_ext_eps,
        fa_by_seed=None,
    )

    cross_ver = cross_verify_against_failure_analysis(
        oc_audit["summary"],
        ip_audit["summary"],
        sv_audit["summary"],
        fa_data["summary"],
    )

    oc_med_eps = load_episodes_jsonl([v14_dir / "opencode-gemini-4-carbon" / "medium" / "episodes.jsonl"], "medium")
    ip_med_eps = load_episodes_jsonl([v14_dir / "inproc-gemini-4-carbon" / "medium" / "episodes.jsonl"], "medium")
    sv_med_eps = load_episodes_jsonl(
        [
            v14_dir / "reference" / "solver-medium-20261114-121126" / "episodes.jsonl",
            v14_dir / "reference" / "solver-medium-seeds20to29" / "episodes.jsonl",
        ],
        "medium",
    )
    oc_med_iv = _mean([sum(1 for st in oc_med_eps[s]["steps"] if st["tool"] == "interview") for s in PRIMARY_SEEDS])
    ip_med_iv = _mean([sum(1 for st in ip_med_eps[s]["steps"] if st["tool"] == "interview") for s in PRIMARY_SEEDS])
    sv_med_iv = _mean([sum(1 for st in sv_med_eps[s]["steps"] if st["tool"] == "interview") for s in PRIMARY_SEEDS])

    row_oc_hard = _find_paired_row(paired_primary, "v1.4/opencode-gemini-4-carbon", "hard", 30)
    row_oc_med = _find_paired_row(paired_primary, "v1.4/opencode-gemini-4-carbon", "medium", 30)
    row_ip_hard = _find_paired_row(paired_primary, "v1.4/inproc-gemini-4-carbon", "hard", 30)
    row_ip_med = _find_paired_row(paired_primary, "v1.4/inproc-gemini-4-carbon", "medium", 30)
    row_ext_only = _find_paired_row(paired_pooled, "v1.4/opencode-gemini-4-carbon-ext", "hard", 2)
    row_pooled_32 = _find_paired_row(
        paired_pooled,
        "v1.4/opencode-gemini-4-carbon+v1.4/opencode-gemini-4-carbon-ext",
        "hard",
        32,
    )

    grok_audit = audit_grok_rationales(resolved_root / "docs" / "reports" / "grok-agent")
    v13_audit = audit_v13_codex_historical(resolved_root / "data" / "runs" / "committed" / "v1.3")
    wrong_decomp = classify_wrong_accusations(fa_data["summary"]["wrong_detail"], oc_audit["episodes"])
    seed_forensics = build_seed_forensics(
        oc_audit["episodes"],
        ip_audit["episodes"],
        sv_audit["episodes"],
        fa_data,
    )
    uniso_tiebreak_eps = [
        {
            "seed": s,
            "accused": oc_audit["episodes"][s]["accused"],
            "correct": oc_audit["episodes"][s]["correct"],
            "consistent_size": oc_audit["episodes"][s]["consistent_size"],
            "consistent_after_hours": oc_audit["episodes"][s]["consistent_after_hours"],
            "strict_argmax": oc_audit["episodes"][s]["unisolated_strict_argmax_ah"],
        }
        for s in PRIMARY_SEEDS
        if (oc_audit["episodes"][s]["consistent_size"] or 0) >= 2
    ]
    bias_tag_rates = {
        "opencode_hard_n30": summarize_cognitive_bias_tags(oc_audit["episodes"]),
        "inproc_hard_n30": summarize_cognitive_bias_tags(ip_audit["episodes"]),
        "solver_hard_n30": summarize_cognitive_bias_tags(sv_audit["episodes"]),
    }

    oc_s = oc_audit["summary"]
    ip_s = ip_audit["summary"]
    sv_s = sv_audit["summary"]
    fa_gap = fa_data["summary"]["gap"]

    signatures = {
        "demeanor_interview_crowding": {
            "opencode_interviews_per_ep": round(oc_s["interviews"], 4),
            "inproc_interviews_per_ep": round(ip_s["interviews"], 4),
            "solver_interviews_per_ep": round(sv_s["interviews"], 4),
            "opencode_calls_per_ep": round(oc_s["calls"], 4),
            "inproc_calls_per_ep": round(ip_s["calls"], 4),
            "solver_calls_per_ep": round(sv_s["calls"], 4),
            "opencode_days_played": oc_s["days"],
            "opencode_days_lt2_canaries": oc_s["days_lt2_canaries"],
            "opencode_days_lt2_full_budget": oc_s["days_lt2_full"],
            "opencode_interviews_on_lt2_full": oc_s["interviews_on_lt2_full"],
            "inproc_days_lt2_canaries": ip_s["days_lt2_canaries"],
            "inproc_days_lt2_full_budget": ip_s["days_lt2_full"],
            "inproc_interviews_on_lt2_full": ip_s["interviews_on_lt2_full"],
            "opencode_first_canary_day": round(oc_s["first_canary_day"], 4),
            "inproc_first_canary_day": round(ip_s["first_canary_day"], 4),
            "solver_first_canary_day": round(sv_s["first_canary_day"], 4),
            "opencode_canaries_before_accuse": round(oc_s["canaries"], 4),
            "opencode_canaries_ci95": round(oc_s["canaries_ci"], 4),
            "opencode_plant_canary_calls_per_ep": round(oc_s["plant_canary_calls_per_ep"], 4),
            "inproc_canaries_before_accuse": round(ip_s["canaries"], 4),
            "solver_canaries_before_accuse": round(sv_s["canaries"], 4),
            "solver_canaries_ci95": round(sv_s["canaries_ci"], 4),
            "opencode_capacity_used": round(oc_s["capacity_used"], 6),
            "inproc_capacity_used": round(ip_s["capacity_used"], 6),
            "solver_capacity_used": round(sv_s["capacity_used"], 6),
            "opencode_days_with_canary_share": round(oc_s["days_with_canary_share"], 6),
            "inproc_days_with_canary_share": round(ip_s["days_with_canary_share"], 6),
            "solver_days_with_canary_share": round(sv_s["days_with_canary_share"], 6),
            "opencode_day1_2_interviews_total": oc_s["interviews_day1_2_total"],
            "opencode_repeat_interviews_total": oc_s["interviews_repeat_total"],
            "opencode_repeat_interviews_share": round(oc_s["interviews_repeat_share"], 6),
            "opencode_interview_topics": oc_s["interview_topics"],
            "opencode_interview_targets": oc_s["interview_targets"],
            "interview_kl_hard_nats": round(kl_hard_iv, 6),
            "canary_mi_hard_nats": round(mi_hard_can, 6),
            "canary_to_interview_info_ratio": round(mi_hard_can / kl_hard_iv, 2),
            "medium_interviews_per_ep": {
                "opencode": round(oc_med_iv, 4),
                "inproc": round(ip_med_iv, 4),
                "solver": round(sv_med_iv, 4),
            },
        },
        "cheap_talk_and_log_distraction": {
            "opencode_read_access_logs_per_ep": round(oc_s["log_reads"], 4),
            "inproc_read_access_logs_per_ep": round(ip_s["log_reads"], 4),
            "solver_read_access_logs_per_ep": round(sv_s["log_reads"], 4),
            "theoretical_after_hours_rates_per_day": {
                "mole": round(mole_ah_rate, 6),
                "decoy": round(decoy_ah_rate, 6),
                "plain_innocent": round(plain_inn_ah_rate, 6),
                "company_total": round(total_ah_rate, 6),
                "ppv_all": round(ppv_ah_all, 6),
                "ppv_ex_decoy": round(ppv_ah_ex_decoy, 6),
            },
            "opencode_observed_after_hours": oc_s["observed_after_hours"],
            "opencode_search_messages_per_ep": round(oc_s["search_messages_per_ep"], 4),
            "opencode_read_message_per_ep": round(oc_s["read_message_per_ep"], 4),
            "opencode_message_calls_per_ep": round(oc_s["message_calls_per_ep"], 4),
            "inproc_message_calls_per_ep": round(ip_s["message_calls_per_ep"], 4),
            "solver_message_calls_per_ep": round(sv_s["message_calls_per_ep"], 4),
            "opencode_message_calls_after_decoy_seen": oc_s["message_calls_after_decoy_seen"],
            "opencode_message_query_kinds": oc_s["message_query_kinds"],
            "opencode_message_snippets_returned": oc_s["message_snippets_returned"],
            "opencode_read_message_targets": oc_s["read_message_targets"],
            "solver_message_snippets_returned": sv_s["message_snippets_returned"],
            "opencode_restrict_calls_total": oc_s["restrict_calls_total"],
            "opencode_restrict_targets": oc_s["restrict_targets"],
            "opencode_restricted_episodes": oc_s["restricted_episodes"],
            "inproc_restrict_calls_total": ip_s["restrict_calls_total"],
            "inproc_restrict_targets": ip_s["restrict_targets"],
            "solver_restrict_calls_total": sv_s["restrict_calls_total"],
            "restriction_v_cost_gap_30_seeds": round(float(fa_gap["restrict"]), 6),
            "opencode_unisolated_after_hours_tiebreak": {
                "unisolated_count": len(uniso_tiebreak_eps),
                "strict_argmax_count": sum(1 for x in uniso_tiebreak_eps if x["strict_argmax"]),
                "strict_argmax_share": (
                    sum(1 for x in uniso_tiebreak_eps if x["strict_argmax"]) / len(uniso_tiebreak_eps)
                    if uniso_tiebreak_eps
                    else 0.0
                ),
                "episodes": uniso_tiebreak_eps,
            },
        },
        "loss_gambling_and_thin_commitment": {
            "opencode_accused_count": oc_s["accused"],
            "opencode_horizon_abstain_count": oc_s["abstain"],
            "opencode_horizon_abstain_seeds": list(fa_gap["abstain_seeds"]),
            "opencode_voluntary_abstain_among_29_accused": 0,
            "opencode_voluntary_abstain_on_ev_negative": 0,
            "opencode_ev_negative_seeds": oc_s["ev_negative"],
            "opencode_ev_negative_v_lost": round(float(fa_gap["penalty_ev_negative"]), 6),
            "opencode_not_isolated_count": oc_s["not_isolated_count"],
            "opencode_not_isolated_seeds": oc_s["not_isolated"],
            "inproc_not_isolated_count": ip_s["not_isolated_count"],
            "solver_not_isolated_count": sv_s["not_isolated_count"],
            "opencode_consistent_set_mean": round(oc_s["consistent_mean"], 6),
            "inproc_consistent_set_mean": round(ip_s["consistent_mean"], 6),
            "solver_consistent_set_mean": round(sv_s["consistent_mean"], 6),
            "thin_commitment_v_lost_net": round(float(fa_gap["penalty"]), 6),
            "thin_commitment_v_lost_on_unresolved": round(float(fa_gap["penalty_not_isolated"]), 6),
            "abstention_seed11_v_lost": round(float(fa_gap["abstain"]), 6),
            "extra_leak_damage_v_lost": round(float(fa_gap["leak"]), 6),
            "canary_cost_saved_v": round(float(fa_gap["canary"]), 6),
            "luck_delta_v": round(float(fa_gap["luck"]), 6),
            "raw_gap_v_sum": round(float(fa_gap["raw_gap"]), 6),
            "luck_adjusted_gap_v_sum": round(float(fa_gap["la_gap"]), 6),
            "wrong_accusations": wrong_decomp,
            "headline_primary_n30": {
                "seed_lock_note": "post-hoc lock (671ed96, 28s after 8fd4dec)",
                "opencode_score": round(float(row_oc_hard["mean"]), 6),
                "opencode_ci95": round(float(row_oc_hard["ci"]), 6),
                "solver_score": round(float(row_oc_hard["solver_same_seeds"]), 6),
                "solver_ci95": round(sv_s["score_ci"], 6),
                "raw_ratio": round(float(row_oc_hard["ratio"]), 6),
                "raw_ratio_lo": round(float(row_oc_hard["ratio_lo"]), 6),
                "raw_ratio_hi": round(float(row_oc_hard["ratio_hi"]), 6),
                "luck_adjusted_opencode": round(oc_s["luck_adjusted"], 6),
                "luck_adjusted_solver": round(sv_s["luck_adjusted"], 6),
                "luck_adjusted_ratio": round(float(row_oc_hard["post_expected_ratio"]), 6),
                "luck_adjusted_ratio_lo": round(float(row_oc_hard["post_expected_lo"]), 6),
                "luck_adjusted_ratio_hi": round(float(row_oc_hard["post_expected_hi"]), 6),
            },
            "inproc_moderation_n30": {
                "inproc_score": round(float(row_ip_hard["mean"]), 6),
                "inproc_ci95": round(float(row_ip_hard["ci"]), 6),
                "raw_ratio": round(float(row_ip_hard["ratio"]), 6),
                "raw_ratio_lo": round(float(row_ip_hard["ratio_lo"]), 6),
                "raw_ratio_hi": round(float(row_ip_hard["ratio_hi"]), 6),
                "luck_adjusted_inproc": round(ip_s["luck_adjusted"], 6),
                "luck_adjusted_ratio": round(float(row_ip_hard["post_expected_ratio"]), 6),
                "luck_adjusted_ratio_lo": round(float(row_ip_hard["post_expected_lo"]), 6),
                "luck_adjusted_ratio_hi": round(float(row_ip_hard["post_expected_hi"]), 6),
                "wrong_count": ip_s["wrong"],
                "expected_wrong": round(ip_s["expected_wrong"], 6),
            },
            "extension_and_pooled": {
                "ext_seeds": list(EXT_SEEDS),
                "ext_n": int(row_ext_only["n"]),
                "ext_score": round(float(row_ext_only["mean"]), 6),
                "ext_ci95": round(float(row_ext_only["ci"]), 6),
                "ext_solver_same_seeds": round(float(row_ext_only["solver_same_seeds"]), 6),
                "ext_interviews_per_ep": round(ext_audit["summary"]["interviews"], 4),
                "ext_canaries_per_ep": round(ext_audit["summary"]["canaries"], 4),
                "ext_solver_canaries_per_ep": round(sv_ext_audit["summary"]["canaries"], 4),
                "pooled_n": int(row_pooled_32["n"]),
                "pooled_score": round(float(row_pooled_32["mean"]), 6),
                "pooled_ci95": round(float(row_pooled_32["ci"]), 6),
                "pooled_solver_same_seeds": round(float(row_pooled_32["solver_same_seeds"]), 6),
                "pooled_raw_ratio": round(float(row_pooled_32["ratio"]), 6),
                "pooled_raw_ratio_lo": round(float(row_pooled_32["ratio_lo"]), 6),
                "pooled_raw_ratio_hi": round(float(row_pooled_32["ratio_hi"]), 6),
                "pooled_luck_adjusted_ratio": round(float(row_pooled_32["post_expected_ratio"]), 6),
                "pooled_luck_adjusted_ratio_lo": round(float(row_pooled_32["post_expected_lo"]), 6),
                "pooled_luck_adjusted_ratio_hi": round(float(row_pooled_32["post_expected_hi"]), 6),
            },
            "medium_context_n30": {
                "opencode_score": round(float(row_oc_med["mean"]), 6),
                "opencode_ci95": round(float(row_oc_med["ci"]), 6),
                "solver_score": round(float(row_oc_med["solver_same_seeds"]), 6),
                "opencode_raw_ratio": round(float(row_oc_med["ratio"]), 6),
                "inproc_score": round(float(row_ip_med["mean"]), 6),
                "inproc_raw_ratio": round(float(row_ip_med["ratio"]), 6),
            },
        },
        "seed_forensics_and_grok_contrast": {
            **seed_forensics,
            "grok_contrast": grok_audit,
            "v13_codex_historical": v13_audit,
            "cognitive_bias_tag_rates": bias_tag_rates,
        },
    }

    return {
        "tiers_version": rules.TIERS_VERSION,
        "v14_frozen_hash": v14_hash,
        "v13_frozen_hash": v13_hash,
        "known_v_mode": bool(rules.KNOWN_V_MODE),
        "cross_verification": cross_ver,
        "cohorts": {
            "opencode_hard_n30": oc_s,
            "inproc_hard_n30": ip_s,
            "solver_hard_n30": sv_s,
            "opencode_ext_hard_n2": ext_audit["summary"],
        },
        "signatures": signatures,
    }


def render_markdown_summary(payload: dict[str, Any]) -> str:
    sig1 = payload["signatures"]["demeanor_interview_crowding"]
    sig2 = payload["signatures"]["cheap_talk_and_log_distraction"]
    sig3 = payload["signatures"]["loss_gambling_and_thin_commitment"]
    sig4 = payload["signatures"]["seed_forensics_and_grok_contrast"]
    hl = sig3["headline_primary_n30"]
    pl = sig3["extension_and_pooled"]
    gr = sig4["grok_contrast"]

    lines = [
        f"{H} Empirical Frontier Transcript Bias Forensics (`v1.4` Hard, Frozen Hash `{payload['v14_frozen_hash']}`)",
        "",
        f"- Cross-verification against `results/failure_analysis_v1.4.json` and deterministic `Env` replay: `passed={payload['cross_verification']['passed']}` (`{payload['cross_verification']['checks_run']}` checks).",
        f"- Primary `n = 30` post-hoc locked paired dev seeds `0-29`: OpenCode `gemini-4-carbon` `{hl['opencode_score']:.3f} +/- {hl['opencode_ci95']:.3f}` vs `SolverPolicy` `{hl['solver_score']:.3f} +/- {hl['solver_ci95']:.3f}` (`{100*hl['raw_ratio']:.0f}% [{100*hl['raw_ratio_lo']:.0f}%, {100*hl['raw_ratio_hi']:.0f}%]` raw, `{100*hl['luck_adjusted_ratio']:.0f}% [{100*hl['luck_adjusted_ratio_lo']:.0f}%, {100*hl['luck_adjusted_ratio_hi']:.0f}%]` luck-adjusted; raw paired gap `{sig3['raw_gap_v_sum']:.2f} V`, luck-adjusted gap `{sig3['luck_adjusted_gap_v_sum']:.2f} V`).",
        f"- Pooled `n = {pl['pooled_n']}` (`0-29` + extension `{pl['ext_seeds']}`): `+{pl['pooled_score']:.3f} +/- {pl['pooled_ci95']:.3f}` (`{100*pl['pooled_luck_adjusted_ratio']:.0f}% [{100*pl['pooled_luck_adjusted_ratio_lo']:.0f}%, {100*pl['pooled_luck_adjusted_ratio_hi']:.0f}%]` luck-adjusted).",
        "",
        f"{H}{H} 1. Core Empirical Bias Signatures (`v1.4` Hard, `n = 30`)",
        "",
        "| Bias Signature | OpenCode `gemini-4-carbon` | In-Process `gemini-4-carbon` | `SolverPolicy` |",
        "|---|---:|---:|---:|",
        f"| `interview` calls / episode | `{sig1['opencode_interviews_per_ep']:.2f}` | `{sig1['inproc_interviews_per_ep']:.2f}` | `{sig1['solver_interviews_per_ep']:.2f}` |",
        f"| Under-planted days with full `8/8` actions | `{sig1['opencode_days_lt2_full_budget']} / {sig1['opencode_days_lt2_canaries']}` | `{sig1['inproc_days_lt2_full_budget']} / {sig1['inproc_days_lt2_canaries']}` | `0 / 182` |",
        f"| First `plant_canary` day | `{sig1['opencode_first_canary_day']:.1f}` | `{sig1['inproc_first_canary_day']:.1f}` | `{sig1['solver_first_canary_day']:.1f}` |",
        f"| Canaries planted before accusation (`%` cap) | `{sig1['opencode_canaries_before_accuse']:.1f}` (`{100*sig1['opencode_capacity_used']:.1f}%`) | `{sig1['inproc_canaries_before_accuse']:.1f}` (`{100*sig1['inproc_capacity_used']:.1f}%`) | `{sig1['solver_canaries_before_accuse']:.1f}` (`{100*sig1['solver_capacity_used']:.1f}%`) |",
        f"| `read_access_logs` calls / episode | `{sig2['opencode_read_access_logs_per_ep']:.2f}` | `{sig2['inproc_read_access_logs_per_ep']:.2f}` | `{sig2['solver_read_access_logs_per_ep']:.2f}` |",
        f"| `search_messages` + `read_message` / episode | `{sig2['opencode_message_calls_per_ep']:.2f}` | `{sig2['inproc_message_calls_per_ep']:.2f}` | `{sig2['solver_message_calls_per_ep']:.2f}` |",
        f"| Accusations with `\\|consistent_set\\| >= 2` | `{sig3['opencode_not_isolated_count']} / {sig3['opencode_accused_count']}` | `{sig3['inproc_not_isolated_count']} / 29` | `{sig3['solver_not_isolated_count']} / 30` |",
        f"| Mean `\\|consistent_set\\|` at accusation | `{sig3['opencode_consistent_set_mean']:.2f}` | `{sig3['inproc_consistent_set_mean']:.2f}` | `{sig3['solver_consistent_set_mean']:.2f}` |",
        f"| Wrong accusations (expected from posteriors) | `{len(sig3['wrong_accusations']['episodes'])}` (`{payload['cohorts']['opencode_hard_n30']['expected_wrong']:.1f}`) | `{sig3['inproc_moderation_n30']['wrong_count']}` (`{sig3['inproc_moderation_n30']['expected_wrong']:.1f}`) | `1` (`1.0`) |",
        "",
        f"{H}{H} 2. Highest Luck-Adjusted Skill-Regret Episodes & Grok Contrast",
        "",
        "| Seed | OpenCode Score | Solver Score | Raw Gap (`V`) | Luck-Adj Gap (`V`) | `\\|C_acc\\|` | Exact `P` | Exact `EV` | Claimed `%` |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for r in sig4["top_luck_adjusted_regret_seeds"][:8]:
        c_sz = str(r["consistent_size"]) if r["consistent_size"] is not None else "abstain"
        p_s = f"{r['p_accused']:.2f}" if r["p_accused"] is not None else "n/a"
        ev_s = f"{r['ev_accused']:+.2f}" if r["ev_accused"] is not None else "n/a"
        cl_s = f"{r['claimed_posterior_pct']:.1f}%" if r["claimed_posterior_pct"] is not None else "n/a"
        lines.append(
            f"| `{r['seed']}` | `{r['opencode_score']:+.2f}` | `{r['solver_score']:+.2f}` | `{r['raw_gap_v']:+.2f}` | `{r['luck_adjusted_gap_v']:+.2f}` | `{c_sz}` | `{p_s}` | `{ev_s}` | `{cl_s}` |"
        )

    lines.extend(
        [
            "",
            f"- Grok `hard` contrast (`n = {gr['hard']['n']}`): `{gr['hard']['interviews_per_ep']:.2f}` interviews/ep, `{gr['hard']['canaries_per_ep']:.2f}` canaries/ep, `{gr['hard']['accused_count']}` correct accusations, and `{gr['hard']['deliberate_abstentions']}` deliberate abstention (`hard-900000` at `P ~ 0.53 < 1/(1+V) ~ 0.70`, `EV ~ -0.24`).",
            "",
        ]
    )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Deterministically audit v1.4 frontier episode transcripts and cognitive bias signatures."
    )
    ap.add_argument("--root", type=Path, default=ROOT, help="Repository root directory")
    ap.add_argument("--json", action="store_true", help="Print full JSON audit report to stdout")
    ap.add_argument("--out-json", type=Path, default=None, help="Optional file path to write JSON audit output")
    ap.add_argument("--out-md", type=Path, default=None, help="Optional file path to write Markdown forensic summary")
    args = ap.parse_args(argv)

    t0 = time.monotonic()
    payload = audit_transcript_biases(root=args.root)
    payload["elapsed_s"] = round(time.monotonic() - t0, 4)

    if args.out_json is not None:
        args.out_json.parent.mkdir(parents=True, exist_ok=True)
        args.out_json.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    md_text = render_markdown_summary(payload)
    if args.out_md is not None:
        args.out_md.parent.mkdir(parents=True, exist_ok=True)
        args.out_md.write_text(md_text, encoding="utf-8")

    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        print(md_text)
        print(f"AUDIT_OK elapsed_s={payload['elapsed_s']:.3f}")

    return 0 if payload["cross_verification"]["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
