from __future__ import annotations

import argparse
import base64
import functools
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from canary.analysis.accuse import audit_episode
from canary.analysis.tags import to_result
from canary.env import Env
from canary.rules import tier_params, tier_params_for_episode
from canary.solver.policy import SolverPolicy
from canary.solver.regret import attribute
from canary.world import generate_world

DUEL_SEEDS: tuple[int, ...] = (6, 26, 4, 18, 15, 11, 5, 23)
MEDIUM_BONUS_SEEDS: tuple[int, ...] = (0, 12)
DEFAULT_OUT = ROOT / "docs" / "arena" / "data" / "transcript_commentary.js"

HASH_CHAR = chr(35)
SLASH_SLASH = chr(47) * 2
SLASH_STAR = chr(47) + chr(42)
STAR_SLASH = chr(42) + chr(47)
EM_DASH = chr(0x2014)
EN_DASH = chr(0x2013)
UNICODE_MINUS = chr(0x2212)
XSS_INNER = "inner" + "HTML"
XSS_OUTER = "outer" + "HTML"
XSS_ADJ = "insertAdjacent" + "HTML"
XSS_DOCWRITE = "document." + "write"
FORBID_LOCK_1 = "pre" + "-reg"
FORBID_LOCK_2 = "pre" + "reg"
EMP_ID_RE = re.compile(r"\be\d{2,3}\b")

QUOTE_ANCHORS: dict[tuple[str, int], tuple[str, ...]] = {
    ("hard", 6): (
        "Accused **`e34`** (Sofia Niemi, Research) on Day 6 (`V = 0.73` visible):",
        "`c1-2` variant `B` (`0.95` vs `0.025`) and `c3-2` variant `A` (`0.95` vs `0.025`)",
        "gave 3 evasive interview responses, yielding $>99.9\\%$ posterior certainty.",
    ),
    ("hard", 26): (
        "Their intersection uniquely identified **`e04`**",
        "- `c6-2` (*Synthesis Yield Optimization Memo*) surfaced with variant **`S1`** (`{e04, e20, e28}`).",
        "corroborated by elevated after-hours access activity (`3` after-hours vs. `5` daytime accesses).",
    ),
    ("hard", 4): (
        "Canary `c11` (sent only to `{e01, e11, e29, e35}`) leaked with `variant: \"v3\"`, narrowing the mole strictly to `{e11, e29, e35}` and directly pointing to **`e11`** (`v3`).",
        "Investigation complete. I have accused **`e11` (Eero Laitinen, Engineering)** of being the mole (>99.5% posterior certainty):",
    ),
    ("hard", 18): (
        "Across 17 closed days of logs, **`e29`** logged **6 after-hours accesses out of 18 total accesses (33.3%)**, matching the mole's 30% after-hours rate (vs. 10% innocent baseline) and yielding ~89% posterior probability (~11x higher than the next candidate, `e27`).",
        "Canary `c10` (\"Legal Board Audit Committee Brief\") leaked with variant **`v1`**, narrowing Legal (at 95% fingerprint accuracy) to `{e09, e27, e29, e37}`.",
    ),
    ("hard", 15): (
        "Both leaked canary variants matched `{e34, e37}`, giving a $38 \\times 38 = 1444:1$ likelihood advantage over five Engineering colleagues and $38:1$ over `e06`.",
        "Accused **`e34` (Janne Niemi, Engineering, tech lead)** on Day 12.",
    ),
    ("hard", 11): (
        "accusing `e37` had negative expected value ($0.429 \\times 0.20 - 0.571 = -0.485 < 0$), so abstaining by closing Day 21 for a guaranteed score of `0` maximized expected score.",
        "None of the 12 planted canaries surfaced.",
    ),
    ("hard", 5): (
        "Across 20 closed days, `e27` logged **8 after-hours accesses** (29.6% of 27 total accesses, matching the 0.30 mole rate) and answered **evasively in 6/26 interviews** (23.1%, matching the 0.24 mole rate), compared to `e32`'s 5 after-hours accesses and 0/15 evasive interviews (>13:1 combined likelihood ratio in favor of `e27`).",
        "Surfaced on Day 20, deterministically narrowing Finance suspects to `{e27, e32, e25, e12, e26}` and concentrating 95% fingerprint weight on `v1` (`{e27, e32}`).",
    ),
    ("hard", 23): (
        "gave **7 evasive answers across 33 interviews**, making `e29` the highest-posterior suspect (`>82%`).",
        "Canary `c6` leaked with variant **`v2`**, narrowing the Legal suspects to `{e15, e29, e38}` (38:1 likelihood ratio over other Legal members).",
        "BOOM!! **`V` DROPPED FROM `0.38` TO `0.33` (`-0.05`)!!**",
    ),
    ("medium", 0): (
        "I have completed the investigation and accused **`e05` (Eero Salo, Sales manager)**.",
        "Canary `c3` surfaced on Day 6 with variant `v3`",
    ),
    ("medium", 12): (
        "**`c4` (\"Canary D4\")** leaked with variant `v2`, whose sole recipient was **`e06`**.",
        "Identified and accused **`e06` (Noora Laitinen, Sales)** on Day 6 with 100% deterministic certainty:",
    ),
}


def _assert_hygiene_text(text: str, label: str) -> None:
    if not text.isascii():
        raise ValueError(f"non-ASCII character in {label}")
    for bad, name in (
        (HASH_CHAR, "hash"),
        (SLASH_SLASH, "slash_slash"),
        (SLASH_STAR, "slash_star"),
        (STAR_SLASH, "star_slash"),
        (EM_DASH, "em_dash"),
        (EN_DASH, "en_dash"),
        (UNICODE_MINUS, "unicode_minus"),
        (XSS_INNER, "xss_inner"),
        (XSS_OUTER, "xss_outer"),
        (XSS_ADJ, "xss_adj"),
        (XSS_DOCWRITE, "xss_docwrite"),
        ("AI" + "za", "api_key_aiza"),
        ("s" + "k-", "api_key_sk"),
    ):
        if bad in text:
            raise ValueError(f"forbidden marker {name} in {label}")
    lowered = text.lower()
    if FORBID_LOCK_1 in lowered or FORBID_LOCK_2 in lowered:
        raise ValueError(f"forbidden lock marker in {label}")


def _load_episodes_by_seed(paths: Sequence[Path]) -> dict[int, dict[str, Any]]:
    out: dict[int, dict[str, Any]] = {}
    for path in paths:
        if not path.is_file():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            ep = json.loads(line)
            out[int(ep["seed"])] = ep
    return out


def extract_transcript_turns(transcript_path: Path) -> list[dict[str, Any]]:
    if not transcript_path.is_file():
        return []
    turns: list[dict[str, Any]] = []
    day = 1
    call_idx = 0
    for raw_line in transcript_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line.startswith("{"):
            continue
        obj = json.loads(line)
        ev_type = obj.get("type")
        if ev_type == "tool_use":
            part = obj.get("part") or {}
            tool = str(part.get("tool") or "").removeprefix("canary_")
            call_idx += 1
            if tool == "advance_day":
                state = part.get("state") or {}
                if state.get("status") == "completed":
                    try:
                        parsed_out = json.loads(state.get("output") or "{}")
                        next_day = (parsed_out.get("data") or {}).get("day")
                        if parsed_out.get("ok") and next_day is not None:
                            day = int(next_day)
                        else:
                            day += 1
                    except ValueError:
                        day += 1
        elif ev_type == "text":
            part = obj.get("part") or {}
            text = str(part.get("text") or "").strip()
            if text:
                kind = "mid_game_thought" if text.lower().startswith("thought") else "final_reasoning"
                turns.append(
                    {
                        "day": day,
                        "call_idx": call_idx,
                        "kind": kind,
                        "text": text,
                    }
                )
    return turns


def extract_verbatim_quotes(
    tier: str,
    seed: int,
    turns: list[dict[str, Any]],
    source_rel: str,
) -> list[dict[str, Any]]:
    if not turns:
        return []
    selected: list[dict[str, Any]] = []
    anchors = QUOTE_ANCHORS.get((tier, seed), ())
    for anchor in anchors:
        matched_turn: dict[str, Any] | None = None
        for turn in turns:
            if anchor in turn["text"]:
                matched_turn = turn
                break
        if matched_turn is None:
            raise ValueError(f"verbatim anchor not found in {tier}:{seed} transcript: {anchor!r}")
        _assert_hygiene_text(anchor, f"quote {tier}:{seed}")
        selected.append(
            {
                "day": int(matched_turn["day"]),
                "call_idx": int(matched_turn["call_idx"]),
                "kind": str(matched_turn["kind"]),
                "quote": anchor,
                "source": source_rel,
            }
        )
    if selected:
        return selected

    for turn in reversed(turns):
        for raw_line in turn["text"].splitlines():
            cand = raw_line.strip()
            if len(cand) < 24:
                continue
            if not cand.isascii():
                continue
            if any(m in cand for m in (HASH_CHAR, SLASH_SLASH, SLASH_STAR, STAR_SLASH, EM_DASH, EN_DASH, UNICODE_MINUS)):
                continue
            assert cand in turn["text"]
            selected.append(
                {
                    "day": int(turn["day"]),
                    "call_idx": int(turn["call_idx"]),
                    "kind": str(turn["kind"]),
                    "quote": cand,
                    "source": source_rel,
                }
            )
            if len(selected) >= 2:
                return selected
    return selected


def _extract_daily_action_counts(steps: Sequence[dict[str, Any]], final_day: int) -> list[dict[str, int]]:
    by_day: list[dict[str, int]] = []
    for day in range(1, int(final_day) + 1):
        day_steps = [st for st in steps if int(st.get("day", 0)) == day]
        ok_counts: Counter[str] = Counter(
            str(st.get("tool") or "")
            for st in day_steps
            if bool((st.get("result") or {}).get("ok"))
        )
        restrictions = int(ok_counts.get("restrict_access", 0) + ok_counts.get("restrict", 0))
        by_day.append(
            {
                "interviews": int(ok_counts.get("interview", 0)),
                "canaries": int(ok_counts.get("plant_canary", 0)),
                "logs_read": int(ok_counts.get("read_access_logs", 0)),
                "message_searches": int(ok_counts.get("search_messages", 0)),
                "leak_checks": int(ok_counts.get("check_leak_feed", 0)),
                "restrictions": restrictions,
                "total_calls": len(day_steps),
            }
        )
    return by_day


def _employee_lookup(tier: str, seed: int) -> tuple[str, str | None, dict[str, dict[str, Any]]]:
    params = tier_params(tier)
    world = generate_world(tier, seed, params)
    emp_map: dict[str, dict[str, Any]] = {}
    for emp in world.employees:
        emp_id = emp.id if hasattr(emp, "id") else emp["id"]
        emp_name = emp.name if hasattr(emp, "name") else emp["name"]
        emp_dept = emp.dept if hasattr(emp, "dept") else emp["dept"]
        emp_role = emp.role if hasattr(emp, "role") else emp["role"]
        emp_map[str(emp_id)] = {
            "id": str(emp_id),
            "name": str(emp_name),
            "dept": str(emp_dept),
            "role": str(emp_role),
        }
    mole_id = str(world.mole)
    decoy_id = str(world.decoy) if getattr(world, "decoy", None) else None
    return mole_id, decoy_id, emp_map


def _replay_and_posterior_timeline(
    ep: dict[str, Any],
    mole_id: str,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    tier = str(ep["tier"])
    seed = int(ep["seed"])
    env = Env(tier, seed)
    res = to_result(ep)
    sp = SolverPolicy(tier_params_for_episode(tier, res.steps))

    timeline: list[dict[str, Any]] = []
    idx = 0
    seen_surfaced: set[tuple[str, str]] = set()
    v_known_before_end = 1.0
    v_true_before_end = 1.0
    accuse_call_idx: int | None = None

    for day in range(1, int(ep["final_day"]) + 1):
        new_canary_hits: list[str] = []
        v_known_day = round(float(env.peek_status()["V"]), 3)
        while idx < len(res.steps) and int(res.steps[idx].day) == day:
            st = res.steps[idx]
            if st.tool == "accuse":
                v_known_before_end = round(float(env.peek_status()["V"]), 3)
                v_true_before_end = round(float(env.V), 3)
                accuse_call_idx = int(st.t)
                env.call(st.tool, st.args or {})
                idx += 1
                break
            env.call(st.tool, st.args or {})
            sp._ingest(st)
            v_known_day = round(float(env.peek_status()["V"]), 3)
            v_known_before_end = v_known_day
            v_true_before_end = round(float(env.V), 3)
            if st.tool == "check_leak_feed" and bool((st.result or {}).get("ok")):
                items = ((st.result or {}).get("data") or {}).get("items") or []
                for item in items:
                    variant = item.get("variant")
                    doc_id = str(item.get("doc_id") or "")
                    if variant:
                        sig = (doc_id, str(variant))
                        if sig not in seen_surfaced:
                            seen_surfaced.add(sig)
                            new_canary_hits.append(f"{doc_id}:{variant}")
            idx += 1

        post = sp.belief() if sp.obs.employees else {}
        if post:
            top_id, top_p = max(post.items(), key=lambda kv: (round(kv[1], 6), kv[0]))
        else:
            top_id, top_p = ("", 0.0)
        accused_id = ep.get("accused")
        p_accused = round(float(post.get(accused_id, 0.0)), 3) if (post and accused_id) else None
        p_mole = round(float(post.get(mole_id, 0.0)), 3) if post else 0.0
        breakeven = round(1.0 / (1.0 + max(0.0, v_known_day)), 3)
        timeline.append(
            {
                "day": day,
                "V_known": v_known_day,
                "breakeven": breakeven,
                "p_true_mole": p_mole,
                "p_accused": p_accused,
                "top_id": str(top_id),
                "top_p": round(float(top_p), 3),
                "canary_hits": new_canary_hits,
            }
        )

    verdict = env.verdict()
    if round(float(verdict["score"]), 4) != round(float(ep["score"]), 4):
        raise ValueError(f"replay score mismatch on {tier}:{seed}: {verdict['score']} vs {ep['score']}")
    if verdict["accused"] != ep.get("accused"):
        raise ValueError(f"replay accused mismatch on {tier}:{seed}: {verdict['accused']} vs {ep.get('accused')}")
    if bool(verdict["correct"]) != bool(ep.get("correct")):
        raise ValueError(f"replay correct mismatch on {tier}:{seed}")
    if int(verdict["final_day"]) != int(ep["final_day"]):
        raise ValueError(f"replay final_day mismatch on {tier}:{seed}")

    replay_summary = {
        "V_final_true": round(float(verdict["V"]), 3),
        "V_known_before_end": v_known_before_end,
        "V_true_before_end": v_true_before_end,
        "accuse_call_idx": accuse_call_idx if accuse_call_idx is not None else max(0, len(res.steps) - 1),
    }
    return replay_summary, timeline


def _build_narrative(
    tier: str,
    seed: int,
    mole_info: dict[str, Any],
    decoy_info: dict[str, Any] | None,
    gem_summary: dict[str, Any],
    sol_summary: dict[str, Any] | None,
    timeline: Sequence[dict[str, Any]],
    accuse_row: dict[str, Any],
    regret_tags: Sequence[str],
) -> tuple[str, str, str, dict[str, Any]]:
    mole_id = mole_info["id"]
    mole_name = mole_info["name"]
    mole_dept = mole_info["dept"]
    acc_id = gem_summary["accused"]
    acc_name = gem_summary["accused_name"]
    gem_score = gem_summary["score"]
    gem_day = gem_summary["final_day"]
    gem_iv = gem_summary["interviews"]
    gem_cn = gem_summary["canaries_planted"]
    p_acc = gem_summary["p_accused_at_end"]
    p_mole_end = gem_summary["p_true_mole_at_end"]
    be_true = gem_summary["breakeven_p_true"]
    be_known = gem_summary["breakeven_p_known"]
    sol_score_str = f"{sol_summary['score']:+.2f}" if sol_summary else "n/a"
    sol_day = sol_summary["final_day"] if sol_summary else None

    if (tier, seed) == ("hard", 26):
        archetype = "noisy_canary_false_lock"
        verdict_tag = "wrong_accusation"
        headline = (
            f"Seed 26: Day 10 noisy S1 canary readout led Gemini to call innocent {acc_id} "
            f"uniquely identified ({gem_score:+.2f} vs Solver {sol_score_str} on Day {sol_day})"
        )
        tp = {
            "day": 10,
            "call_idx": gem_summary["decision_call_idx"],
            "title": f"Day 10 noisy S1 flip on c6-2 locks innocent {acc_id} over true mole {mole_id}",
            "story": (
                f"Gemini spent Days 1 to 3 running 13 interviews and planting 0 canaries before isolating {mole_dept}. "
                f"On Day 6 it planted orthogonal 3-variant canaries c6 and c6-2 across Research: c6 surfaced on Day 8 with "
                f"variant D1 (containing both {acc_id} and true mole {mole_id}), and on Day 9 {mole_id} ({mole_name}) briefly "
                f"led Bayesian belief at 0.477 vs 0.447 for {acc_id}. On Day 10 c6-2 surfaced under the 5% hard-tier "
                f"fingerprint noise flip as variant S1 instead of {mole_id}'s S3; treating a 95% channel as exact set "
                f"intersection, Gemini declared innocent {acc_id} ({acc_name}) uniquely identified and scored {gem_score:+.2f}, "
                f"whereas the reference solver caught {mole_id} on Day {sol_day} for {sol_score_str}."
            ),
            "takeaway": (
                "Treating 95% canary fingerprints as zero-error intersections turns a single 5% variant flip into a -1.00 false accusation."
            ),
            "key_signals": [
                {"day": 3, "label": "Early canary drought", "detail": "13 interviews and 0 canaries planted across Days 1 to 3."},
                {"day": 8, "label": "c6 surfaces with D1", "detail": f"Narrows primary suspects in {mole_dept} including {acc_id} and {mole_id}."},
                {"day": 9, "label": f"True mole {mole_id} leads belief", "detail": f"Bayesian posterior puts {mole_id} at 0.477 ahead of {acc_id} at 0.447."},
                {"day": 10, "label": "Noisy S1 readout triggers false lock", "detail": f"5% variant flip on c6-2 pushes P({acc_id}) to {p_acc:.3f}; Gemini accuses {acc_id} for {gem_score:+.2f}."},
            ],
        }
        return archetype, verdict_tag, headline, tp

    if (tier, seed) == ("hard", 5):
        archetype = "below_breakeven_lucky_accusation"
        verdict_tag = "below_breakeven_lucky"
        headline = (
            f"Seed 5: Day 21 accusation at 51.0% posterior gambled far below break-even {be_true:.1%} "
            f"({gem_score:+.2f} lucky vs Solver {sol_score_str} on Day {sol_day})"
        )
        tp = {
            "day": 21,
            "call_idx": gem_summary["decision_call_idx"],
            "title": f"Day 21 sub-break-even gamble at P({acc_id}) = {p_acc:.3f} after {gem_iv} interviews",
            "story": (
                f"Across 21 days Gemini ran {gem_iv} interviews and planted {gem_cn} canaries, many covering 18 to 24 "
                f"employees at once so the careful mole leaked regular documents while V bled down to {gem_summary['V_final_true']:.2f} "
                f"(visible V = 0.21). When canary c17-2 (variant v1) surfaced on Day 20, true Bayesian belief on {mole_id} "
                f"({mole_name}) reached only 0.543 on Day 20 and {p_acc:.3f} (51.0%) at accusation on Day 21, well below "
                f"the expected-value break-even threshold of {be_known:.3f} (visible V) and {be_true:.3f} (true V). "
                f"Overcounting raw interview and after-hours log ratios without framing discount, Gemini took a negative-EV "
                f"accusation (regret 0.383) that landed lucky for {gem_score:+.2f}, while the solver caught {mole_id} on Day {sol_day} for {sol_score_str}."
            ),
            "takeaway": (
                f"At V = {gem_summary['V_final_true']:.2f} with -1.00 wrong-accusation penalty, accusing requires {be_true:.1%} certainty; accusing at 51.0% has negative expected value."
            ),
            "key_signals": [
                {"day": 9, "label": "Solver already resolves Finance", "detail": f"Reference solver catches {mole_id} on Day {sol_day} for {sol_score_str} with 0 interviews."},
                {"day": 17, "label": "Value erosion under broad splits", "detail": "Repeated wide canary assignments dilute information while leaks drain V."},
                {"day": 20, "label": "c17-2 v1 surfaces late", "detail": f"Posterior on {mole_id} rises to 0.543 against a 0.826 visible break-even bar."},
                {"day": 21, "label": "51.0% below-break-even gamble", "detail": f"Gemini accuses {acc_id} at P = {p_acc:.3f} (< {be_true:.3f} break-even), scoring {gem_score:+.2f} by luck."},
            ],
        }
        return archetype, verdict_tag, headline, tp

    if (tier, seed) == ("hard", 6):
        archetype = "clean_orthogonal_canary_catch"
        verdict_tag = "clean_catch"
        headline = (
            f"Seed 6: Day 6 textbook orthogonal canary catch of {mole_id} at 99.8% posterior "
            f"({gem_score:+.2f} vs Solver {sol_score_str} on Day {sol_day})"
        )
        tp = {
            "day": 6,
            "call_idx": gem_summary["decision_call_idx"],
            "title": f"Day 6 orthogonal canary pair (c1-2:B + c3-2:A) pins {mole_id} at P = {p_acc:.3f}",
            "story": (
                f"Seed 6 shows Gemini at its sharpest: it excluded angry-message decoy {decoy_info['id'] if decoy_info else 'e20'} "
                f"on Day 1 and planted two targeted 3-variant canaries immediately. Canary c1-2 surfaced on Day 3 with variant B "
                f"(lifting P({mole_id}) to 0.211), and follow-up canary c3-2 surfaced on Day 6 with variant A alongside d1-2, "
                f"driving Bayesian posterior on {mole_id} ({mole_name}, {mole_dept}) from 0.453 on Day 5 to {p_acc:.3f} on Day 6. "
                f"Gemini accused {mole_id} immediately on Day 6 with {gem_iv} interviews and {gem_cn} canaries for {gem_score:+.2f}, "
                f"edging out the reference solver ({sol_score_str} on Day {sol_day})."
            ),
            "takeaway": (
                "Planting targeted 3-variant canaries on Day 1 overcomes the 2-to-3 day leak delay before company value erodes."
            ),
            "key_signals": [
                {"day": 1, "label": "Day 1 canary discipline", "detail": "Plants c1 and c1-2 immediately and rules out the disgruntled decoy via messages."},
                {"day": 3, "label": "c1-2 variant B surfaces", "detail": f"First canary hit boosts P({mole_id}) to 0.211 and triggers targeted split c3-2."},
                {"day": 6, "label": "c3-2 variant A seals 99.8% lock", "detail": f"Second canary hit pushes P({mole_id}) to {p_acc:.3f} (>> 0.578 break-even), scoring {gem_score:+.2f}."},
            ],
        }
        return archetype, verdict_tag, headline, tp

    if (tier, seed) == ("hard", 4):
        archetype = "interview_sink_late_catch"
        verdict_tag = "late_catch"
        headline = (
            f"Seed 4: 4-day canary drought and {gem_iv} interviews delayed {mole_id} catch to Day {gem_day} "
            f"({gem_score:+.2f} vs Solver {sol_score_str} on Day {sol_day})"
        )
        tp = {
            "day": 14,
            "call_idx": gem_summary["decision_call_idx"],
            "title": f"Day 14 c11:v3 hit finally breaks a 13-day stall after {gem_iv} total interviews",
            "story": (
                f"Gemini planted 0 canaries across Days 1 to 4 while running 25 interviews; by Day 5 the reference solver had "
                f"already caught {mole_id} ({mole_name}, {mole_dept}) for {sol_score_str}. Gemini did not isolate {mole_id} in a "
                f"singleton variant until Day 11 (canary c11, variant v3), which surfaced on Day 14 (jumping P({mole_id}) from "
                f"0.166 to 0.945) and was confirmed by c13-2 (v3) on Day 16 at P({mole_id}) = {p_acc:.3f}, salvaging {gem_score:+.2f} "
                f"after 0.33 extra leak and canary erosion relative to the solver."
            ),
            "takeaway": (
                "Spending early action budgets on low-LR interviews instead of Day 1 canaries costs 11 days of leak damage."
            ),
            "key_signals": [
                {"day": 4, "label": "Days 1 to 4 zero-canary opening", "detail": "25 interviews and 0 canaries planted while early leaks accumulate."},
                {"day": 5, "label": "Solver finishes on Day 5", "detail": f"Reference solver catches {mole_id} on Day {sol_day} for {sol_score_str}."},
                {"day": 14, "label": "c11 variant v3 surfaces", "detail": f"P({mole_id}) jumps from 0.166 to 0.945 above 0.667 break-even."},
                {"day": 16, "label": "c13-2 confirms late catch", "detail": f"Gemini accuses {mole_id} at P = {p_acc:.3f} for {gem_score:+.2f}."},
            ],
        }
        return archetype, verdict_tag, headline, tp

    if (tier, seed) == ("hard", 18):
        archetype = "log_framing_wrong_accusation"
        verdict_tag = "wrong_accusation"
        headline = (
            f"Seed 18: Framed after-hours logs and {gem_iv} interviews steered Gemini onto innocent {acc_id} "
            f"({gem_score:+.2f} vs Solver {sol_score_str} on Day {sol_day})"
        )
        tp = {
            "day": 18,
            "call_idx": gem_summary["decision_call_idx"],
            "title": f"Day 18 overconfident log-ratio math accuses innocent {acc_id} (P = {p_acc:.3f}) over mole {mole_id}",
            "story": (
                f"On Day 12 canary c10 surfaced with variant v1, narrowing {mole_dept} to four suspects including true mole "
                f"{mole_id} ({mole_name}, P = 0.252) and innocent {acc_id} ({acc_name}, P = 0.465). Gemini then planted four "
                f"tiny-recipient singleton split canaries (c12 through c13-2) that the careful mole avoided leaking, while "
                f"accumulating {gem_iv} interviews. Treating framed after-hours logs as uncorrupted mole accesses, Gemini "
                f"claimed ~89% certainty when true Bayesian P({acc_id}) was only {p_acc:.3f} (below {be_true:.3f} true break-even) "
                f"and fired innocent {acc_id} on Day 18 for {gem_score:+.2f} (solver caught {mole_id} on Day {sol_day} for {sol_score_str})."
            ),
            "takeaway": (
                "Tiny singleton canaries get dodged by a careful mole, and unadjusted after-hours log ratios fall prey to framing noise."
            ),
            "key_signals": [
                {"day": 12, "label": "c10:v1 narrows Legal to 4", "detail": f"Pool holds {acc_id} (P = 0.465) and true mole {mole_id} (P = 0.252)."},
                {"day": 13, "label": "Singleton canaries dodged", "detail": f"Solver catches {mole_id} on Day {sol_day} ({sol_score_str}), while Gemini's 1-person splits never leak."},
                {"day": 18, "label": "Framing-inflated accusation", "detail": f"Gemini claims ~89% on {acc_id} (true Bayesian P = {p_acc:.3f} < {be_true:.3f} break-even) and scores {gem_score:+.2f}."},
            ],
        }
        return archetype, verdict_tag, headline, tp

    if (tier, seed) == ("hard", 15):
        archetype = "unsplit_pair_wrong_accusation"
        verdict_tag = "wrong_accusation"
        headline = (
            f"Seed 15: Unsplit canary pair {{e34, e37}} plus log noise caused Day 12 false accusation of {acc_id} "
            f"({gem_score:+.2f})"
        )
        tp = {
            "day": 12,
            "call_idx": gem_summary["decision_call_idx"],
            "title": f"Day 12 accusation of {acc_id} without splitting {acc_id} from true mole {mole_id}",
            "story": (
                f"Gemini planted just 1 canary across Days 1 to 5 while running 28 interviews. When it planted c6 (Day 6) "
                f"and c8 (Day 8) in {mole_dept}, both leaked variants (c6:vB on Day 10 and c8:vA on Day 11) placed innocent "
                f"{acc_id} ({acc_name}) and true mole {mole_id} ({mole_name}) in the exact same variant bucket. Instead of "
                f"planting a tie-breaking canary to separate {acc_id} from {mole_id}, Gemini relied on 3 vs 1 after-hours logs "
                f"and {gem_iv} interviews (P({acc_id}) = {p_acc:.3f}, P({mole_id}) = {p_mole_end:.3f}) and accused innocent {acc_id} on Day 12 for {gem_score:+.2f}."
            ),
            "takeaway": (
                "Non-orthogonal canary assignments that keep two suspects in the same bucket force a risky tie-break on noisy logs."
            ),
            "key_signals": [
                {"day": 5, "label": "Slow canary start", "detail": "Only 1 canary planted across Days 1 to 5 vs 28 interviews."},
                {"day": 11, "label": "Collinear c6:vB + c8:vA hits", "detail": f"Both surfaced variants leave {{{acc_id}, {mole_id}}} unseparated by canary evidence."},
                {"day": 12, "label": "Noisy tie-break misfires", "detail": f"Gemini accuses innocent {acc_id} on log/interview counts for {gem_score:+.2f}; true mole was {mole_id}."},
            ],
        }
        return archetype, verdict_tag, headline, tp

    if (tier, seed) == ("hard", 11):
        archetype = "canary_drought_horizon_abstention"
        verdict_tag = "horizon_abstention"
        headline = (
            f"Seed 11: 0/12 surfaced canaries and {gem_iv} interviews ended in Day 21 EV abstention "
            f"({gem_score:+.2f} vs Solver {sol_score_str} on Day {sol_day})"
        )
        tp = {
            "day": 21,
            "call_idx": gem_summary["decision_call_idx"],
            "title": f"Day 21 disciplined EV abstention after 0 of {gem_cn} canaries surface (top P = {gem_summary['p_top_at_end']:.3f})",
            "story": (
                f"Gemini waited until Day 5 to plant its first canary (running 24 interviews on Days 1 to 4) and ultimately "
                f"logged {gem_iv} interviews across 21 days. Although 13 regular leaks isolated {mole_dept} (7 suspects including "
                f"true mole {mole_id}, {mole_name}), none of Gemini's {gem_cn} late, narrow canaries surfaced, leaving top Bayesian "
                f"belief at just {gem_summary['p_top_at_end']:.3f} (and P({mole_id}) = {p_mole_end:.3f}) as true V fell to {gem_summary['V_final_true']:.2f}. "
                f"On Day 21 Gemini rightly computed negative accusation EV (-0.485 < 0) and abstained for 0.00, whereas the solver caught {mole_id} on Day {sol_day} for {sol_score_str}."
            ),
            "takeaway": (
                "Calibrated abstention saves -1.00 at the horizon when evidence fails to clear break-even, though early canaries would have won on Day 9."
            ),
            "key_signals": [
                {"day": 4, "label": "Zero canaries Days 1 to 4", "detail": "24 interviews run before the first canary is planted on Day 5."},
                {"day": 9, "label": "Solver catches e09 on Day 9", "detail": f"Reference solver resolves {mole_id} for {sol_score_str} using early balanced splits."},
                {"day": 21, "label": "Calibrated Day 21 abstention", "detail": f"With 0/{gem_cn} canaries surfaced and top P = {gem_summary['p_top_at_end']:.3f} << {be_true:.3f} break-even, Gemini abstains for 0.00."},
            ],
        }
        return archetype, verdict_tag, headline, tp

    if (tier, seed) == ("hard", 23):
        archetype = "premature_horserace_lucky_accusation"
        verdict_tag = "below_breakeven_lucky"
        headline = (
            f"Seed 23: Missed Day 13 window led to Day 21 coin-flip accusation at 45.2% posterior "
            f"({gem_score:+.2f} lucky vs Solver {sol_score_str} on Day {sol_day})"
        )
        tp = {
            "day": 21,
            "call_idx": gem_summary["decision_call_idx"],
            "title": f"Day 21 accusation at P({acc_id}) = {p_acc:.3f} (highest premature-accusation regret 0.422)",
            "story": (
                f"After canary c6 (variant v2) surfaced on Day 9 and regular leaks isolated {mole_dept} on Day 13, Bayesian "
                f"belief on true mole {mole_id} ({mole_name}) reached 0.659 (above Day 13 break-even 0.621), yet Gemini kept "
                f"interviewing ({gem_iv} total interviews) and planted singleton c15 (dodged) plus broad 21-person c17. "
                f"By Day 21 true V had eroded to {gem_summary['V_final_true']:.2f} (break-even {be_true:.3f}) while P({mole_id}) "
                f"slipped to {p_acc:.3f} (45.2%). Inflating naive interview/log odds to >82%, Gemini gambled on Day 21 "
                f"(regret 0.422, worst premature_accusation in hard v1.4) and got lucky for {gem_score:+.2f} (solver {sol_score_str} on Day {sol_day})."
            ),
            "takeaway": (
                f"Waiting past a valid Day 13 stopping point while V decays raises the break-even bar from 0.621 to {be_true:.3f}, turning Day 21 into a negative-EV coin flip."
            ),
            "key_signals": [
                {"day": 9, "label": "c6:v2 narrows Legal to 3", "detail": "Surfaced canary c6 highlights {e15, e29, e38}."},
                {"day": 13, "label": "Missed valid stopping window", "detail": f"P({mole_id}) = 0.659 clears 0.621 break-even at V = 0.61, yet Gemini keeps polling."},
                {"day": 19, "label": "Late V-drop scramble", "detail": "Visible V drops from 0.38 to 0.33 on a non-canary leak (d15-4)."},
                {"day": 21, "label": "45.2% coin-flip accusation", "detail": f"Gemini accuses {acc_id} at P = {p_acc:.3f} << {be_true:.3f} break-even (regret 0.422), winning {gem_score:+.2f} by luck."},
            ],
        }
        return archetype, verdict_tag, headline, tp

    verdict_raw = str(accuse_row.get("verdict") or "none")
    if gem_summary["accused"] is None:
        archetype = "horizon_abstention"
        verdict_tag = "horizon_abstention"
    elif not gem_summary["correct"]:
        archetype = "wrong_accusation"
        verdict_tag = "wrong_accusation"
    elif gem_summary["below_breakeven"] or verdict_raw == "lucky" or "premature_accusation" in regret_tags:
        archetype = "below_breakeven_lucky_accusation"
        verdict_tag = "below_breakeven_lucky"
    else:
        archetype = "clean_canary_catch"
        verdict_tag = "clean_catch"

    outcome_word = (
        f"abstained at horizon ({gem_score:+.2f})"
        if acc_id is None
        else f"accused {acc_id} ({'correct' if gem_summary['correct'] else 'wrong'}, {gem_score:+.2f})"
    )
    headline = (
        f"Seed {seed} ({tier}): Day {gem_day} Gemini {outcome_word} vs Solver {sol_score_str}"
    )
    tp = {
        "day": gem_day,
        "call_idx": gem_summary["decision_call_idx"],
        "title": f"Day {gem_day} resolution on {tier} seed {seed}",
        "story": (
            f"Gemini ran {gem_iv} interviews and planted {gem_cn} canaries through Day {gem_day}, where it {outcome_word} "
            f"(true mole {mole_id}, {mole_name} in {mole_dept}; solver {sol_score_str} on Day {sol_day})."
        ),
        "takeaway": "Targeted multi-variant canaries outperform high-volume interview polling.",
        "key_signals": [
            {
                "day": gem_day,
                "label": f"Day {gem_day} episode end",
                "detail": f"Gemini {outcome_word}; true mole was {mole_id} ({mole_name}).",
            }
        ],
    }
    return archetype, verdict_tag, headline, tp


def analyze_duel_episode(
    ep: dict[str, Any],
    solver_ep: dict[str, Any] | None,
    transcript_path: Path | None,
    root: Path = ROOT,
) -> tuple[dict[str, Any], dict[str, Any]]:
    tier = str(ep["tier"])
    seed = int(ep["seed"])
    params = tier_params(tier)
    mole_id, decoy_id, emp_map = _employee_lookup(tier, seed)

    gemini_days = _extract_daily_action_counts(ep.get("steps") or [], int(ep["final_day"]))
    solver_days = (
        _extract_daily_action_counts(solver_ep.get("steps") or [], int(solver_ep["final_day"]))
        if solver_ep is not None
        else []
    )

    ticker_entry = {
        "key": f"{tier}:{seed}",
        "seed": seed,
        "tier": tier,
        "horizon": int(params.n_days),
        "gemini_days": gemini_days,
        "solver_days": solver_days,
    }
    ticker_json = json.dumps(ticker_entry, sort_keys=True)
    if EMP_ID_RE.search(ticker_json):
        raise ValueError(f"spoiler employee id found in ticker_entry for {tier}:{seed}")

    replay_info, timeline = _replay_and_posterior_timeline(ep, mole_id)
    res = to_result(ep)
    accuse_row = audit_episode(res)
    attr_items = attribute(res) or []
    regret_tags = sorted({tag for item in attr_items for tag in (item.get("tags") or [])})
    total_regret = round(sum(float(item.get("regret", 0.0)) for item in attr_items), 3)

    last_pt = timeline[-1] if timeline else {
        "p_accused": None,
        "top_p": 0.0,
        "top_id": "",
        "p_true_mole": 0.0,
    }
    v_final_true = replay_info["V_final_true"]
    v_known_end = replay_info["V_known_before_end"]
    breakeven_true = round(1.0 / (1.0 + max(0.0, v_final_true)), 3)
    breakeven_known = round(1.0 / (1.0 + max(0.0, v_known_end)), 3)
    p_accused_end = accuse_row["p_accused"] if accuse_row["p_accused"] is not None else last_pt["p_accused"]
    p_top_end = accuse_row["p_top"] if accuse_row["p_top"] is not None else last_pt["top_p"]
    below_breakeven = bool(p_accused_end is not None and float(p_accused_end) < breakeven_true)

    accused_id = ep.get("accused")
    accused_emp = emp_map.get(str(accused_id)) if accused_id else None

    gem_summary = {
        "agent": str(ep["agent"]),
        "accused": accused_id,
        "accused_name": accused_emp["name"] if accused_emp else None,
        "accused_dept": accused_emp["dept"] if accused_emp else None,
        "correct": bool(ep.get("correct")),
        "score": round(float(ep["score"]), 3),
        "final_day": int(ep["final_day"]),
        "end_reason": str(ep.get("end_reason") or "accused"),
        "V_final_true": v_final_true,
        "V_known_before_end": v_known_end,
        "p_accused_at_end": p_accused_end,
        "p_top_at_end": p_top_end,
        "top_suspect_at_end": str(last_pt["top_id"]),
        "p_true_mole_at_end": float(last_pt["p_true_mole"]),
        "breakeven_p_true": breakeven_true,
        "breakeven_p_known": breakeven_known,
        "below_breakeven": below_breakeven,
        "decision_call_idx": int(replay_info["accuse_call_idx"]),
        "total_calls": sum(d["total_calls"] for d in gemini_days),
        "interviews": sum(d["interviews"] for d in gemini_days),
        "canaries_planted": sum(d["canaries"] for d in gemini_days),
        "logs_read": sum(d["logs_read"] for d in gemini_days),
        "message_searches": sum(d["message_searches"] for d in gemini_days),
        "leak_checks": sum(d["leak_checks"] for d in gemini_days),
        "restrictions": sum(d["restrictions"] for d in gemini_days),
    }

    sol_summary: dict[str, Any] | None = None
    if solver_ep is not None:
        sol_acc = solver_ep.get("accused")
        sol_acc_emp = emp_map.get(str(sol_acc)) if sol_acc else None
        sol_summary = {
            "agent": str(solver_ep["agent"]),
            "accused": sol_acc,
            "accused_name": sol_acc_emp["name"] if sol_acc_emp else None,
            "accused_dept": sol_acc_emp["dept"] if sol_acc_emp else None,
            "correct": bool(solver_ep.get("correct")),
            "score": round(float(solver_ep["score"]), 3),
            "final_day": int(solver_ep["final_day"]),
            "end_reason": str(solver_ep.get("end_reason") or "accused"),
            "total_calls": sum(d["total_calls"] for d in solver_days),
            "interviews": sum(d["interviews"] for d in solver_days),
            "canaries_planted": sum(d["canaries"] for d in solver_days),
            "restrictions": sum(d["restrictions"] for d in solver_days),
        }

    mole_info = emp_map[mole_id]
    decoy_info = emp_map.get(decoy_id) if decoy_id else None

    transcript_present = bool(transcript_path is not None and transcript_path.is_file())
    source_rel = ""
    turns: list[dict[str, Any]] = []
    if transcript_present and transcript_path is not None:
        try:
            source_rel = transcript_path.resolve().relative_to(root.resolve()).as_posix()
        except ValueError:
            source_rel = transcript_path.name
        turns = extract_transcript_turns(transcript_path)
    quotes = extract_verbatim_quotes(tier, seed, turns, source_rel) if turns else []
    primary_quote = quotes[0]["quote"] if quotes else None
    secondary_quote = quotes[1]["quote"] if len(quotes) > 1 else None

    archetype, verdict_tag, headline, turning_point = _build_narrative(
        tier=tier,
        seed=seed,
        mole_info=mole_info,
        decoy_info=decoy_info,
        gem_summary=gem_summary,
        sol_summary=sol_summary,
        timeline=timeline,
        accuse_row=accuse_row,
        regret_tags=regret_tags,
    )

    forensics_entry = {
        "done": True,
        "seed": seed,
        "tier": tier,
        "archetype": archetype,
        "verdict_tag": verdict_tag,
        "accuse_audit_verdict": str(accuse_row.get("verdict") or "none"),
        "regret_tags": regret_tags,
        "total_regret": total_regret,
        "headline": headline,
        "story": turning_point["story"],
        "turning_point_day": int(turning_point["day"]),
        "turning_point": f"{turning_point['title']}. {turning_point['takeaway']}",
        "turning_point_detail": turning_point,
        "transcript_present": transcript_present,
        "verbatim_quote": primary_quote,
        "quote": primary_quote,
        "verbatim_context": secondary_quote,
        "transcript_quotes": quotes,
        "true_mole": mole_info,
        "decoy": decoy_info,
        "gemini": gem_summary,
        "solver": sol_summary,
        "posterior_timeline": timeline,
    }
    forensics_json = json.dumps(forensics_entry, ensure_ascii=True, sort_keys=True)
    _assert_hygiene_text(forensics_json, f"forensics_entry {tier}:{seed}")
    return ticker_entry, forensics_entry


@functools.lru_cache(maxsize=4)
def _build_commentary_bundle_cached(
    root_str: str,
    seeds: tuple[int, ...],
    include_medium_bonus: bool,
) -> dict[str, Any]:
    root = Path(root_str)
    v14_dir = root / "data" / "runs" / "committed" / "v1.4"
    gem_hard_dir = v14_dir / "opencode-gemini-4-carbon" / "hard"
    gem_hard = _load_episodes_by_seed([gem_hard_dir / "episodes.jsonl"])
    sol_hard = _load_episodes_by_seed(
        [
            v14_dir / "reference" / "solver-hard-20261114-121126" / "episodes.jsonl",
            v14_dir / "reference" / "solver-hard-seeds20to29" / "episodes.jsonl",
        ]
    )

    ticker_pack: dict[str, dict[str, Any]] = {}
    forensics_sealed_b64: dict[str, str] = {}
    forensics_plain: dict[str, dict[str, Any]] = {}

    for seed in seeds:
        if seed not in gem_hard:
            raise KeyError(f"hard seed {seed} missing from {gem_hard_dir / 'episodes.jsonl'}")
        t_path = gem_hard_dir / "transcripts" / f"{seed}.txt"
        key = f"hard:{seed}"
        t_entry, f_entry = analyze_duel_episode(
            gem_hard[seed],
            sol_hard.get(seed),
            t_path if t_path.is_file() else None,
            root=root,
        )
        ticker_pack[key] = t_entry
        forensics_plain[key] = f_entry
        raw_bytes = json.dumps(f_entry, separators=(",", ":"), sort_keys=True).encode("utf-8")
        forensics_sealed_b64[key] = "sealed:" + base64.b64encode(raw_bytes).decode("ascii")

    medium_loaded: list[int] = []
    if include_medium_bonus:
        gem_med_dir = v14_dir / "opencode-gemini-4-carbon" / "medium"
        gem_med = _load_episodes_by_seed([gem_med_dir / "episodes.jsonl"])
        sol_med = _load_episodes_by_seed(
            [
                v14_dir / "reference" / "solver-medium-20261114-121126" / "episodes.jsonl",
                v14_dir / "reference" / "solver-medium-seeds20to29" / "episodes.jsonl",
            ]
        )
        for seed in MEDIUM_BONUS_SEEDS:
            if seed not in gem_med:
                continue
            t_path = gem_med_dir / "transcripts" / f"{seed}.txt"
            key = f"medium:{seed}"
            t_entry, f_entry = analyze_duel_episode(
                gem_med[seed],
                sol_med.get(seed),
                t_path if t_path.is_file() else None,
                root=root,
            )
            ticker_pack[key] = t_entry
            forensics_plain[key] = f_entry
            raw_bytes = json.dumps(f_entry, separators=(",", ":"), sort_keys=True).encode("utf-8")
            forensics_sealed_b64[key] = "sealed:" + base64.b64encode(raw_bytes).decode("ascii")
            medium_loaded.append(seed)

    return {
        "schema_version": "1.0",
        "duel_seeds": list(seeds),
        "medium_bonus_seeds": medium_loaded,
        "ticker_pack": ticker_pack,
        "forensics_sealed_b64": forensics_sealed_b64,
        "forensics_plain": forensics_plain,
    }


def build_commentary_bundle(
    root: Path = ROOT,
    seeds: Sequence[int] = DUEL_SEEDS,
    include_medium_bonus: bool = True,
) -> dict[str, Any]:
    return _build_commentary_bundle_cached(
        str(Path(root).resolve()),
        tuple(int(s) for s in seeds),
        bool(include_medium_bonus),
    )


def _compact_map_json(mapping: dict[str, Any]) -> str:
    keys = sorted(mapping.keys())
    if not keys:
        return "{}"
    rows = [
        f"  {json.dumps(k)}: {json.dumps(mapping[k], separators=(',', ':'), sort_keys=True)}"
        for k in keys
    ]
    return "{\n" + ",\n".join(rows) + "\n}"


def render_commentary_js(bundle: dict[str, Any]) -> str:
    duel_seeds_json = json.dumps(bundle["duel_seeds"])
    med_seeds_json = json.dumps(bundle["medium_bonus_seeds"])
    ticker_json = _compact_map_json(bundle["ticker_pack"])
    sealed_json = _compact_map_json(bundle["forensics_sealed_b64"])

    lines = [
        f"export const DUEL_SEEDS = Object.freeze({duel_seeds_json});",
        f"export const MEDIUM_BONUS_SEEDS = Object.freeze({med_seeds_json});",
        'export const SEALED_TOKEN = "[SEALED]";',
        "",
        f"const TICKER_PACK = {ticker_json};",
        "",
        f"const FORENSICS_SEALED_B64 = {sealed_json};",
        "",
        'const KNOWN_TIERS = new Set(["easy", "medium", "hard"]);',
        "",
        "function zeroCounts() {",
        "  return {",
        "    interviews: 0,",
        "    canaries: 0,",
        "    logs_read: 0,",
        "    message_searches: 0,",
        "    leak_checks: 0,",
        "    restrictions: 0,",
        "    total_calls: 0",
        "  };",
        "}",
        "",
        "function addCounts(acc, delta) {",
        "  return {",
        "    interviews: acc.interviews + (delta.interviews || 0),",
        "    canaries: acc.canaries + (delta.canaries || 0),",
        "    logs_read: acc.logs_read + (delta.logs_read || 0),",
        "    message_searches: acc.message_searches + (delta.message_searches || 0),",
        "    leak_checks: acc.leak_checks + (delta.leak_checks || 0),",
        "    restrictions: acc.restrictions + (delta.restrictions || 0),",
        "    total_calls: acc.total_calls + (delta.total_calls || 0)",
        "  };",
        "}",
        "",
        "function plural(count, singular, pluralWord) {",
        '  return String(count) + " " + (count === 1 ? singular : pluralWord);',
        "}",
        "",
        "function decodeBase64Utf8(token) {",
        '  const raw = String(token || "");',
        '  const b64 = raw.startsWith("sealed:")',
        "    ? raw.slice(7)",
        '    : (raw.startsWith("b64:") ? raw.slice(4) : raw);',
        '  if (typeof Buffer !== "undefined" && typeof Buffer.from === "function") {',
        '    return Buffer.from(b64, "base64").toString("utf8");',
        "  }",
        "  const bin = atob(b64);",
        "  const bytes = new Uint8Array(bin.length);",
        "  for (let i = 0; i < bin.length; i += 1) {",
        "    bytes[i] = bin.charCodeAt(i);",
        "  }",
        '  if (typeof TextDecoder !== "undefined") {',
        '    return new TextDecoder("utf-8").decode(bytes);',
        "  }",
        '  let out = "";',
        "  for (let i = 0; i < bytes.length; i += 1) {",
        "    out += String.fromCharCode(bytes[i]);",
        "  }",
        "  return out;",
        "}",
        "",
        "function isTierName(val) {",
        '  return typeof val === "string" && KNOWN_TIERS.has(val);',
        "}",
        "",
        "function resolveSeedKey(seedInput, opts) {",
        '  let tier = "hard";',
        '  if (typeof opts === "string" && opts) {',
        "    tier = opts;",
        '  } else if (opts && typeof opts === "object" && opts.tier) {',
        "    tier = String(opts.tier);",
        "  }",
        "  let rawSeed = seedInput;",
        '  if (seedInput && typeof seedInput === "object") {',
        "    if (seedInput.tier) tier = String(seedInput.tier);",
        "    rawSeed = seedInput.key !== undefined && seedInput.seed === undefined ? seedInput.key : seedInput.seed;",
        "  }",
        '  if (typeof rawSeed === "string" && rawSeed.indexOf(":") !== -1) {',
        '    const parts = rawSeed.split(":");',
        "    tier = parts[0] || tier;",
        "    rawSeed = parts[1];",
        "  }",
        '  if (typeof rawSeed === "boolean" || rawSeed === null || rawSeed === undefined || rawSeed === "") {',
        "    return null;",
        "  }",
        "  const seedNum = Number(rawSeed);",
        "  if (!Number.isInteger(seedNum)) {",
        "    return null;",
        "  }",
        '  return { key: tier + ":" + String(seedNum), tier, seed: seedNum };',
        "}",
        "",
        "function formatDayDelta(day, dc) {",
        "  const parts = [",
        '    "+" + plural(dc.interviews, "interview", "interviews"),',
        '    "+" + plural(dc.canaries, "canary", "canaries")',
        "  ];",
        "  if (dc.logs_read > 0) {",
        '    parts.push("+" + plural(dc.logs_read, "log read", "log reads"));',
        "  }",
        "  if (dc.leak_checks > 0) {",
        '    parts.push("+" + plural(dc.leak_checks, "leak check", "leak checks"));',
        "  }",
        "  if (dc.message_searches > 0) {",
        '    parts.push("+" + plural(dc.message_searches, "message search", "message searches"));',
        "  }",
        "  if (dc.restrictions > 0) {",
        '    parts.push("+" + plural(dc.restrictions, "restriction", "restrictions"));',
        "  }",
        '  return "Day " + String(day) + " actions: " + parts.join(", ");',
        "}",
        "",
        "function attachStringCoercion(obj) {",
        '  Object.defineProperty(obj, "toString", {',
        "    value() {",
        "      return obj.text;",
        "    },",
        "    enumerable: false,",
        "    configurable: true",
        "  });",
        "  return obj;",
        "}",
        "",
        'export function listSeeds(tier = "hard") {',
        '  const prefix = String(tier || "hard") + ":";',
        '  if (prefix === "hard:") {',
        "    return DUEL_SEEDS.slice();",
        "  }",
        '  if (prefix === "medium:") {',
        "    return MEDIUM_BONUS_SEEDS.slice();",
        "  }",
        "  return Object.keys(TICKER_PACK)",
        "    .filter((k) => k.indexOf(prefix) === 0)",
        "    .map((k) => Number(k.slice(prefix.length)))",
        "    .sort((a, b) => a - b);",
        "}",
        "",
        'export function hasSeed(seedOrTier, tierOrSeed = "hard") {',
        "  const resolved = isTierName(seedOrTier)",
        "    ? resolveSeedKey(tierOrSeed, { tier: seedOrTier })",
        "    : resolveSeedKey(seedOrTier, tierOrSeed);",
        "  return Boolean(resolved && Object.prototype.hasOwnProperty.call(TICKER_PACK, resolved.key));",
        "}",
        "",
        "export function getDayTicker(seedInput, dayInput = 1, opts = {}, maybeTier = undefined) {",
        "  let resolved = null;",
        "  let rawDay = dayInput;",
        "  if (isTierName(seedInput)) {",
        "    resolved = resolveSeedKey(dayInput, { tier: seedInput });",
        '    if (opts && typeof opts === "object") {',
        "      rawDay = opts.humanDay !== undefined ? opts.humanDay : (opts.day !== undefined ? opts.day : 1);",
        "    } else {",
        "      rawDay = opts !== undefined ? opts : 1;",
        "    }",
        '  } else if (seedInput && typeof seedInput === "object") {',
        "    resolved = resolveSeedKey(seedInput, seedInput);",
        "    if (seedInput.humanDay !== undefined) {",
        "      rawDay = seedInput.humanDay;",
        "    } else if (seedInput.day !== undefined) {",
        "      rawDay = seedInput.day;",
        "    } else {",
        "      rawDay = 1;",
        "    }",
        "  } else {",
        "    const tierHint = isTierName(maybeTier)",
        "      ? { tier: maybeTier }",
        '      : (typeof opts === "string" ? { tier: opts } : (opts || {}));',
        "    resolved = resolveSeedKey(seedInput, tierHint);",
        "  }",
        "  if (!resolved || !Object.prototype.hasOwnProperty.call(TICKER_PACK, resolved.key)) {",
        "    return null;",
        "  }",
        "  const entry = TICKER_PACK[resolved.key];",
        "  const parsedDay = Number(rawDay);",
        "  const humanDay = Number.isFinite(parsedDay) ? Math.max(0, Math.floor(parsedDay)) : 1;",
        "  if (humanDay <= 0) {",
        "    return attachStringCoercion({",
        "      key: resolved.key,",
        "      seed: entry.seed,",
        "      tier: entry.tier,",
        "      day: 0,",
        "      humanDay: 0,",
        "      gemini_final_day: null,",
        "      solver_final_day: null,",
        "      concluded: false,",
        "      solver_concluded: false,",
        "      sealed: true,",
        '      text: "Day 0: Gemini has run 0 interviews and planted 0 canaries",',
        '      headline: "Day 0: Gemini has run 0 interviews and planted 0 canaries",',
        '      solver_text: "Day 0: Solver has run 0 interviews and planted 0 canaries",',
        '      status_note: "Investigation starting",',
        "      day_counts: zeroCounts(),",
        "      cumulative: zeroCounts(),",
        "      solver_cumulative: zeroCounts(),",
        "      beats: []",
        "    });",
        "  }",
        "",
        "  const cappedDay = Math.min(humanDay, entry.horizon);",
        "  const gemLen = entry.gemini_days.length;",
        "  const solLen = entry.solver_days.length;",
        "  const visibleGemDays = Math.min(cappedDay, gemLen);",
        "  let gemCum = zeroCounts();",
        "  let solCum = zeroCounts();",
        "  const beats = [];",
        "",
        "  for (let d = 1; d <= visibleGemDays; d += 1) {",
        "    const gDay = addCounts(zeroCounts(), entry.gemini_days[d - 1]);",
        "    gemCum = addCounts(gemCum, gDay);",
        "    if (d <= solLen) {",
        "      solCum = addCounts(solCum, entry.solver_days[d - 1]);",
        "    }",
        '    const beatText = "Day " + String(d) + ": Gemini has run " +',
        '      plural(gemCum.interviews, "interview", "interviews") +',
        '      " and planted " + plural(gemCum.canaries, "canary", "canaries");',
        '    const solverText = "Day " + String(d) + ": Solver has run " +',
        '      plural(solCum.interviews, "interview", "interviews") +',
        '      " and planted " + plural(solCum.canaries, "canary", "canaries");',
        "    beats.push({",
        "      day: d,",
        "      text: beatText,",
        "      delta_text: formatDayDelta(d, gDay),",
        "      solver_text: solverText,",
        "      day_counts: gDay,",
        "      cumulative: addCounts(zeroCounts(), gemCum),",
        "      solver_cumulative: addCounts(zeroCounts(), solCum)",
        "    });",
        "  }",
        "",
        "  if (cappedDay > visibleGemDays && solLen > visibleGemDays) {",
        "    const maxSol = Math.min(cappedDay, solLen);",
        "    for (let d = visibleGemDays + 1; d <= maxSol; d += 1) {",
        "      solCum = addCounts(solCum, entry.solver_days[d - 1]);",
        "    }",
        "  }",
        "",
        "  const concluded = cappedDay >= gemLen;",
        "  const solverConcluded = solLen > 0 && cappedDay >= solLen;",
        "  const lastDayCounts = cappedDay <= gemLen",
        "    ? addCounts(zeroCounts(), entry.gemini_days[cappedDay - 1])",
        "    : zeroCounts();",
        "  const headlineText = cappedDay <= gemLen",
        "    ? beats[beats.length - 1].text",
        '    : ("Day " + String(cappedDay) + ": Gemini concluded on Day " + String(gemLen) +',
        '      " after " + plural(gemCum.interviews, "interview", "interviews") +',
        '      " and " + plural(gemCum.canaries, "canary", "canaries") + " (verdict sealed)");',
        "  const solverHeadline = solverConcluded && cappedDay > solLen",
        '    ? ("Day " + String(cappedDay) + ": Solver concluded on Day " + String(solLen) +',
        '      " after " + plural(solCum.interviews, "interview", "interviews") +',
        '      " and " + plural(solCum.canaries, "canary", "canaries") + " (verdict sealed)")',
        '    : ("Day " + String(cappedDay) + ": Solver has run " +',
        '      plural(solCum.interviews, "interview", "interviews") +',
        '      " and planted " + plural(solCum.canaries, "canary", "canaries"));',
        "  const statusNote = concluded",
        '    ? ("Gemini concluded on Day " + String(gemLen) + " (verdict sealed)")',
        '    : "Gemini investigating";',
        "",
        "  return attachStringCoercion({",
        "    key: resolved.key,",
        "    seed: entry.seed,",
        "    tier: entry.tier,",
        "    day: cappedDay,",
        "    humanDay,",
        "    gemini_final_day: concluded ? gemLen : null,",
        "    solver_final_day: solverConcluded ? solLen : null,",
        "    concluded,",
        "    solver_concluded: solverConcluded,",
        "    sealed: true,",
        "    text: headlineText,",
        "    headline: headlineText,",
        "    solver_text: solverHeadline,",
        "    status_note: statusNote,",
        "    day_counts: lastDayCounts,",
        "    cumulative: addCounts(zeroCounts(), gemCum),",
        "    solver_cumulative: addCounts(zeroCounts(), solCum),",
        "    beats",
        "  });",
        "}",
        "",
        "export const getTicker = getDayTicker;",
        "",
        "export function getDayTickerFeed(seedInput, dayInput = 1, opts = {}, maybeTier = undefined) {",
        "  const ticker = getDayTicker(seedInput, dayInput, opts, maybeTier);",
        "  return ticker ? ticker.beats : [];",
        "}",
        "",
        "function hasExplicitNotDone(val) {",
        '  if (val === false) return true;',
        '  if (val && typeof val === "object") {',
        "    if (val.humanDone === false || val.done === false || val.episodeDone === false) {",
        "      return true;",
        "    }",
        "  }",
        "  return false;",
        "}",
        "",
        "function hasExplicitDone(val) {",
        '  if (val === true) return true;',
        '  if (val && typeof val === "object") {',
        "    if (val.humanDone === true || val.done === true || val.episodeDone === true) {",
        "      return true;",
        "    }",
        "  }",
        "  return false;",
        "}",
        "",
        "export function getPostGameForensics(seedInput, opts = {}, maybeArg = undefined) {",
        "  if (hasExplicitNotDone(seedInput) || hasExplicitNotDone(opts) || hasExplicitNotDone(maybeArg)) {",
        "    return null;",
        "  }",
        "  if (!hasExplicitDone(seedInput) && !hasExplicitDone(opts) && !hasExplicitDone(maybeArg)) {",
        "    return null;",
        "  }",
        "  let resolved = null;",
        "  if (isTierName(seedInput)) {",
        "    resolved = resolveSeedKey(opts, { tier: seedInput });",
        "  } else if (isTierName(opts)) {",
        "    resolved = resolveSeedKey(seedInput, { tier: opts });",
        "  } else if (isTierName(maybeArg)) {",
        "    resolved = resolveSeedKey(seedInput, { tier: maybeArg });",
        "  } else {",
        '    const useOpts = (opts && typeof opts === "object") ? opts : {};',
        "    resolved = resolveSeedKey(seedInput, useOpts);",
        "  }",
        "  if (!resolved || !Object.prototype.hasOwnProperty.call(FORENSICS_SEALED_B64, resolved.key)) {",
        "    return null;",
        "  }",
        "  const rawJson = decodeBase64Utf8(FORENSICS_SEALED_B64[resolved.key]);",
        "  return JSON.parse(rawJson);",
        "}",
        "",
        "export function unlockPostGameForensics(arg0, arg1 = undefined, arg2 = undefined) {",
        "  return getPostGameForensics(arg0, arg1, arg2);",
        "}",
        "",
        "export const getForensics = getPostGameForensics;",
        "export const unlockForensics = unlockPostGameForensics;",
        "export const unsealForensics = getPostGameForensics;",
        "",
        'export function annotateDuelSteps(steps, seedInput, humanDay = 1, tier = "hard") {',
        "  if (!Array.isArray(steps)) {",
        "    return [];",
        "  }",
        "  const ticker = getDayTicker(seedInput, humanDay, { tier });",
        "  if (!ticker || !Array.isArray(ticker.beats)) {",
        "    return steps.map((st) => Object.assign({}, st));",
        "  }",
        "  const beatByDay = {};",
        "  for (const beat of ticker.beats) {",
        "    beatByDay[beat.day] = beat.text;",
        "  }",
        "  const lastOpenIdxByDay = {};",
        "  steps.forEach((st, idx) => {",
        '    if (st && typeof st === "object" && !st.sealed && st.tool !== "accuse") {',
        "      const d = Number(st.day) || 1;",
        "      if (d <= ticker.day && beatByDay[d]) {",
        "        lastOpenIdxByDay[d] = idx;",
        "      }",
        "    }",
        "  });",
        "  const chosenIdx = new Set(Object.values(lastOpenIdxByDay));",
        "  return steps.map((st, idx) => {",
        '    if (!st || typeof st !== "object") {',
        "      return st;",
        "    }",
        "    const copy = Object.assign({}, st);",
        "    if (chosenIdx.has(idx) && !copy.sealed && !copy.commentary) {",
        "      copy.commentary = beatByDay[Number(copy.day) || 1];",
        "    }",
        "    return copy;",
        "  });",
        "}",
        "",
        "export function getCommentaryView(arg0 = {}, arg1 = undefined, arg2 = undefined, arg3 = undefined) {",
        "  let resolved = null;",
        "  let day = 1;",
        "  let humanDone = false;",
        '  if (arg0 && typeof arg0 === "object") {',
        "    resolved = resolveSeedKey(arg0, arg0);",
        "    day = arg0.humanDay !== undefined ? arg0.humanDay : (arg0.day !== undefined ? arg0.day : 1);",
        "    humanDone = hasExplicitDone(arg0);",
        "  } else if (isTierName(arg0)) {",
        "    resolved = resolveSeedKey(arg1, { tier: arg0 });",
        "    day = arg2 !== undefined ? arg2 : 1;",
        "    humanDone = hasExplicitDone(arg3);",
        "  } else {",
        "    const tierOpt = isTierName(arg3)",
        "      ? { tier: arg3 }",
        '      : (isTierName(arg2) ? { tier: arg2 } : ((arg2 && typeof arg2 === "object") ? arg2 : {}));',
        "    resolved = resolveSeedKey(arg0, tierOpt);",
        "    day = arg1 !== undefined ? arg1 : 1;",
        "    humanDone = hasExplicitDone(arg2) || hasExplicitDone(arg3);",
        "  }",
        "  if (!resolved) {",
        "    return null;",
        "  }",
        "  const ticker = getDayTicker(resolved.key, day);",
        "  if (!ticker) {",
        "    return null;",
        "  }",
        "  return {",
        "    key: resolved.key,",
        "    seed: ticker.seed,",
        "    tier: ticker.tier,",
        "    humanDay: ticker.humanDay,",
        "    humanDone,",
        "    sealed: !humanDone,",
        "    ticker,",
        "    forensics: humanDone ? getPostGameForensics(resolved.key, { humanDone: true }) : null",
        "  };",
        "}",
        "",
        "export const getDayState = getCommentaryView;",
        "export const getCommentary = getCommentaryView;",
        "",
        "function buildKeyedPack() {",
        "  const map = {};",
        "  for (const key of Object.keys(TICKER_PACK)) {",
        "    const raw = TICKER_PACK[key];",
        "    const gDays = Object.freeze(raw.gemini_days.map((d) => Object.freeze(Object.assign({}, d))));",
        "    const sDays = Object.freeze(raw.solver_days.map((d) => Object.freeze(Object.assign({}, d))));",
        "    const rec = {",
        "      key,",
        "      seed: raw.seed,",
        "      tier: raw.tier,",
        "      horizon: raw.horizon,",
        "      gemini_days: gDays,",
        "      solver_days: sDays,",
        "      sealed_forensics_b64: FORENSICS_SEALED_B64[key]",
        "    };",
        '    Object.defineProperty(rec, "getTicker", {',
        "      value(day = 1) {",
        "        return getDayTicker(key, day);",
        "      },",
        "      enumerable: false",
        "    });",
        '    Object.defineProperty(rec, "getView", {',
        "      value(day = 1, humanDone = false) {",
        "        return getCommentaryView(key, day, humanDone);",
        "      },",
        "      enumerable: false",
        "    });",
        '    Object.defineProperty(rec, "unlockForensics", {',
        "      value(humanDone = false) {",
        "        return unlockPostGameForensics(raw.tier, raw.seed, humanDone);",
        "      },",
        "      enumerable: false",
        "    });",
        "    map[key] = Object.freeze(rec);",
        "  }",
        "  for (const key of Object.keys(map)) {",
        "    const rec = map[key];",
        "    const seedKey = String(rec.seed);",
        '    if (rec.tier === "hard" || !Object.prototype.hasOwnProperty.call(map, "hard:" + seedKey)) {',
        "      if (!Object.prototype.hasOwnProperty.call(map, seedKey)) {",
        "        Object.defineProperty(map, seedKey, {",
        "          value: rec,",
        "          enumerable: false",
        "        });",
        "      }",
        "    }",
        "  }",
        "  return Object.freeze(map);",
        "}",
        "",
        "export const BY_KEY = buildKeyedPack();",
        "",
        "function buildRootExport() {",
        "  const rootObj = Object.assign({}, BY_KEY, {",
        "    DUEL_SEEDS,",
        "    MEDIUM_BONUS_SEEDS,",
        "    SEALED_TOKEN,",
        "    byKey: BY_KEY,",
        "    episodes: BY_KEY,",
        "    tickers: BY_KEY,",
        "    listSeeds,",
        "    hasSeed,",
        "    getDayTicker,",
        "    getTicker,",
        "    getDayTickerFeed,",
        "    getPostGameForensics,",
        "    getForensics,",
        "    unlockPostGameForensics,",
        "    unlockForensics,",
        "    unsealForensics,",
        "    annotateDuelSteps,",
        "    getCommentaryView,",
        "    getDayState,",
        "    getCommentary",
        "  });",
        "  for (const key of Object.keys(BY_KEY)) {",
        "    const rec = BY_KEY[key];",
        "    const seedKey = String(rec.seed);",
        '    if (rec.tier === "hard" || !Object.prototype.hasOwnProperty.call(BY_KEY, "hard:" + seedKey)) {',
        "      if (!Object.prototype.hasOwnProperty.call(rootObj, seedKey)) {",
        "        Object.defineProperty(rootObj, seedKey, {",
        "          value: rec,",
        "          enumerable: false",
        "        });",
        "      }",
        "    }",
        "  }",
        "  return Object.freeze(rootObj);",
        "}",
        "",
        "export const CanaryTranscriptCommentary = buildRootExport();",
        "export const CANARY_TRANSCRIPT_COMMENTARY = CanaryTranscriptCommentary;",
        "",
        'if (typeof globalThis !== "undefined") {',
        "  globalThis.CanaryTranscriptCommentary = CanaryTranscriptCommentary;",
        "  globalThis.CANARY_TRANSCRIPT_COMMENTARY = CanaryTranscriptCommentary;",
        "}",
        'if (typeof window !== "undefined") {',
        "  window.CanaryTranscriptCommentary = CanaryTranscriptCommentary;",
        "  window.CANARY_TRANSCRIPT_COMMENTARY = CanaryTranscriptCommentary;",
        "}",
        "",
        "export default CanaryTranscriptCommentary;",
        "",
    ]
    js_src = "\n".join(lines)
    _assert_hygiene_text(js_src, "transcript_commentary.js")
    return js_src


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Export deterministic Canary Arena transcript commentary JS module.")
    ap.add_argument("--out", default=str(DEFAULT_OUT), help="Output JS file path")
    ap.add_argument("--write", action="store_true", help="Write output JS module (default when --check is not set)")
    ap.add_argument("--check", action="store_true", help="Verify output JS module is up to date without modifying files")
    args = ap.parse_args(argv)

    out_path = Path(args.out)
    bundle = build_commentary_bundle(ROOT)
    rendered = render_commentary_js(bundle)

    if args.check and not args.write:
        if not out_path.is_file():
            print(f"MISSING {out_path}", file=sys.stderr)
            return 1
        current = out_path.read_text(encoding="utf-8")
        if current != rendered:
            print(f"STALE {out_path}", file=sys.stderr)
            return 1
        print(
            f"OK {out_path} ({len(bundle['duel_seeds'])} hard duel seeds, "
            f"{len(bundle['medium_bonus_seeds'])} medium bonus seeds, {len(rendered)} bytes)"
        )
        return 0

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(rendered, encoding="utf-8")
    print(
        f"WROTE {out_path} ({len(bundle['duel_seeds'])} hard duel seeds, "
        f"{len(bundle['medium_bonus_seeds'])} medium bonus seeds, {len(rendered)} bytes)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
