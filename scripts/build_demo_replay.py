from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from dataclasses import asdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DEFAULT_OUT_REL = Path("docs/demo/replay.html")
MAX_HTML_BYTES = 2_000_000

OPENCODE_DIRS: tuple[str, ...] = (
    "data/runs/committed/v1.4/opencode-gemini-4-carbon/hard",
)
SOLVER_DIRS: tuple[str, ...] = (
    "data/runs/committed/v1.4/reference/solver-hard-20261114-121126",
    "data/runs/committed/v1.4/reference/solver-hard-seeds20to29",
)
INPROC_DIRS: tuple[str, ...] = (
    "data/runs/committed/v1.4/inproc-gemini-4-carbon/hard",
)


def sanitize_ascii(text: str) -> str:
    replacements = {
        chr(8212): " - ",
        chr(8211): "-",
        chr(8722): "-",
        chr(8745): " intersect ",
        chr(8594): "->",
        chr(177): "+/-",
        chr(8216): "'",
        chr(8217): "'",
        chr(8220): '"',
        chr(8221): '"',
        chr(8230): "...",
        chr(35): "",
    }
    out_chars: list[str] = []
    for ch in str(text):
        if ch in replacements:
            out_chars.append(replacements[ch])
        elif 32 <= ord(ch) < 127 or ch in ("\n", "\t"):
            out_chars.append(ch)
        else:
            out_chars.append(" ")
    cleaned = "".join(out_chars)
    cleaned = cleaned.replace("<!--", "").replace("-->", "")
    cleaned = cleaned.replace("/*", "").replace("*/", "")
    while "//" in cleaned:
        cleaned = cleaned.replace("//", "/")
    return " ".join(cleaned.split())


def load_committed_episode(root: Path, rel_dirs: tuple[str, ...], seed: int) -> dict[str, Any]:
    for rel in rel_dirs:
        fp = root / rel / "episodes.jsonl"
        if not fp.is_file():
            continue
        for line in fp.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            ep = json.loads(line)
            if int(ep["seed"]) == seed:
                copied = dict(ep)
                copied.setdefault("tier", "hard")
                copied["_source_rel"] = f"{rel}/episodes.jsonl"
                return copied
    raise ValueError(f"seed {seed} not found in {rel_dirs}")


def extract_transcript_rationale(root: Path, seed: int) -> dict[str, Any]:
    tx_path = root / "data/runs/committed/v1.4/opencode-gemini-4-carbon/hard/transcripts" / f"{seed}.txt"
    if not tx_path.is_file():
        return {"has_transcript": False, "final_text": "", "uniquely_identified": False}
    raw_lines = tx_path.read_text(encoding="utf-8").splitlines()
    last_text = ""
    for line in raw_lines:
        stripped = line.strip()
        if not stripped.startswith("{"):
            continue
        try:
            obj = json.loads(stripped)
        except ValueError:
            continue
        if obj.get("type") == "text":
            part = obj.get("part") or {}
            txt = str(part.get("text") or "")
            if txt.strip():
                last_text = txt
    has_unique = "uniquely identified" in last_text.lower()
    cleaned = sanitize_ascii(last_text.replace("**", "").replace("`", "").replace("*", ""))
    return {
        "has_transcript": True,
        "final_text": cleaned[:1500],
        "uniquely_identified": has_unique,
        "transcript_rel": f"data/runs/committed/v1.4/opencode-gemini-4-carbon/hard/transcripts/{seed}.txt",
    }


def probe_roster_and_decoy(tier: str, seed: int) -> tuple[list[dict[str, Any]], str | None, dict[str, int]]:
    from canary.env import Env
    from canary.rules import tier_params
    from canary.solver.policy import SolverPolicy
    from canary.types import Step

    probe_env = Env(tier, seed)
    emps = probe_env.call("list_employees", {}).data["employees"]
    roster = [dict(e) for e in emps]
    params = tier_params(tier)
    decoy_id: str | None = None
    if params.decoy:
        probe_env.call("advance_day", {})
        probe_env.call("advance_day", {})
        sp = SolverPolicy(params)
        sp.obs.employees = [str(e["id"]) for e in roster]
        for word in SolverPolicy.ANGER_WORDS:
            r = probe_env.call("search_messages", {"query": word})
            sp._ingest(Step(t=0, day=probe_env.day, tool="search_messages", args={"query": word}, result=asdict(r)))
            if sp.obs.decoy is not None:
                decoy_id = str(sp.obs.decoy)
                break

    log_env = Env(tier, seed)
    for _ in range(9):
        log_env.call("advance_day", {})
    logs = log_env.call("read_access_logs", {"day_from": 1, "day_to": 9}).data["logs"]
    ah_counts: Counter[str] = Counter()
    for entry in logs:
        if entry.get("after_hours"):
            ah_counts[str(entry.get("employee", ""))] += 1
    return roster, decoy_id, {k: int(v) for k, v in sorted(ah_counts.items())}


def summarize_step(tool: str, args: dict[str, Any], ok: bool, data: dict[str, Any]) -> str:
    if not ok:
        return "invalid call rejected"
    if tool == "status":
        v = data.get("V")
        acts = data.get("actions_left_today")
        return f"day={data.get('day')} visible_V={v:.2f} actions_left={acts}" if isinstance(v, (int, float)) else "status checked"
    if tool == "list_employees":
        emps = data.get("employees") or []
        return f"roster loaded ({len(emps)} employees)"
    if tool == "list_documents":
        docs = data.get("documents") or []
        d_from = args.get("day_from", "?")
        d_to = args.get("day_to", "?")
        return f"days {d_from}..{d_to}: {len(docs)} docs"
    if tool == "read_access_logs":
        logs = data.get("logs") or []
        ah = sum(1 for x in logs if x.get("after_hours"))
        return f"days {args.get('day_from', '?')}..{args.get('day_to', '?')}: {len(logs)} entries ({ah} after-hours)"
    if tool == "search_messages":
        msgs = data.get("messages") or []
        q = sanitize_ascii(str(args.get("query", "")))
        return f"query '{q}': {len(msgs)} messages"
    if tool == "check_leak_feed":
        items = data.get("items") or []
        if not items:
            return "0 surfaced leaks"
        last = items[-1]
        var = last.get("variant")
        v_txt = f" variant {var}" if var else ""
        return f"{len(items)} surfaced (latest: {last.get('doc_id')}{v_txt} on d{last.get('surfaced_day')})"
    if tool == "plant_canary":
        cid = data.get("canary_id", "?")
        assign = args.get("assignment") or {}
        variants = sorted(set(str(v) for v in assign.values()))
        title = sanitize_ascii(str(args.get("doc_title", "")))
        return f"{cid} ({len(assign)} recipients, variants {'/'.join(variants)}): {title}"
    if tool == "interview":
        emp = args.get("employee", "?")
        topic = args.get("topic", "?")
        ans = sanitize_ascii(str(data.get("answer", "")))
        return f"{emp} on {topic}: {ans[:72]}"
    if tool == "restrict_access":
        return f"restricted {args.get('employee', '?')}"
    if tool == "unrestrict_access":
        return f"unrestricted {args.get('employee', '?')}"
    if tool == "advance_day":
        v = data.get("V")
        v_str = f"{v:.2f}" if isinstance(v, (int, float)) else "?"
        return f"closed d{data.get('closed_day')} -> d{data.get('day')}, visible_V={v_str}"
    if tool == "accuse":
        return f"ACCUSED {args.get('employee', '?')} (episode closed)"
    return sanitize_ascii(tool)


def replay_and_extract_run(
    ep_raw: dict[str, Any],
    run_key: str,
    display_label: str,
    short_label: str,
    harness_badge: str,
    true_mole: str,
) -> dict[str, Any]:
    from canary.analysis.tags import to_result
    from canary.env import Env
    from canary.rules import tier_params_for_episode
    from canary.solver.policy import SolverPolicy, accuse_value

    tier = str(ep_raw["tier"])
    seed = int(ep_raw["seed"])
    env = Env(tier, seed)
    ep = to_result(ep_raw)
    params = tier_params_for_episode(ep.tier, ep.steps)
    sp = SolverPolicy(params)

    raw_steps = list(ep_raw.get("steps") or [])
    canaries_total = 0
    canaries_d1_3 = 0
    interviews_total = 0

    canary_by_id: dict[str, dict[str, Any]] = {}
    canaries_planted: list[dict[str, Any]] = []
    leaks_surfaced: list[dict[str, Any]] = []
    seen_feed_ids: set[str] = set()

    days_out: list[dict[str, Any]] = []
    day_calls = 0
    day_canaries = 0
    day_canary_ids: list[str] = []
    day_interviews = 0
    day_interviewed: list[str] = []
    day_surfaced: list[dict[str, Any]] = []
    day_tools: Counter[str] = Counter()
    day_step_logs: list[dict[str, Any]] = []

    final_accused_emp = ep_raw.get("accused")

    for i, st_raw in enumerate(raw_steps):
        if env.done:
            break
        tool = str(st_raw["tool"])
        args = dict(st_raw.get("args") or {})
        r = env.call(tool, args)
        r_data = dict(r.data or {}) if isinstance(r.data, dict) else {}

        st = ep.steps[i]
        day_calls += 1
        day_tools[tool] += 1
        day_step_logs.append(
            {
                "call": i + 1,
                "tool": tool,
                "ok": bool(r.ok),
                "summary": summarize_step(tool, args, bool(r.ok), r_data),
            }
        )

        if tool == "plant_canary" and r.ok:
            cid = str(r_data["canary_id"])
            doc = next(d for d in env.docs if d["doc_id"] == cid)
            variants_sorted = {
                sanitize_ascii(str(lbl)): sorted(str(emp) for emp in holders)
                for lbl, holders in sorted(doc["variants"].items())
            }
            mole_var = next(
                (lbl for lbl, holders in variants_sorted.items() if true_mole in holders),
                None,
            )
            canaries_total += 1
            if st.day <= 3:
                canaries_d1_3 += 1
            day_canaries += 1
            day_canary_ids.append(cid)
            c_rec = {
                "call_number": i + 1,
                "canary_id": cid,
                "day": int(st.day),
                "mole_variant": mole_var,
                "recipients_count": len(doc["recipients"]),
                "title": sanitize_ascii(str(doc["title"])),
                "variants": variants_sorted,
            }
            canary_by_id[cid] = c_rec
            canaries_planted.append(c_rec)

        if tool == "interview":
            interviews_total += 1
            day_interviews += 1
            emp_arg = str(args.get("employee", ""))
            if emp_arg:
                day_interviewed.append(emp_arg)

        if tool == "check_leak_feed" and r.ok:
            for item in r_data.get("items") or []:
                did = str(item["doc_id"])
                if did not in seen_feed_ids:
                    seen_feed_ids.add(did)
                    rep_var = sanitize_ascii(str(item["variant"])) if item.get("variant") is not None else None
                    c_info = canary_by_id.get(did)
                    is_canary = c_info is not None
                    mole_var = c_info["mole_variant"] if c_info else None
                    is_flip = bool(is_canary and rep_var is not None and mole_var is not None and rep_var != mole_var)
                    rep_holders = list(c_info["variants"].get(rep_var, [])) if (c_info and rep_var) else []
                    mole_holders = list(c_info["variants"].get(mole_var, [])) if (c_info and mole_var) else []
                    leak_rec = {
                        "doc_id": did,
                        "surfaced_day": int(item["surfaced_day"]),
                        "planted_day": int(c_info["day"]) if c_info else None,
                        "title": sanitize_ascii(str(item["title"])),
                        "is_canary": is_canary,
                        "reported_variant": rep_var,
                        "reported_holders": rep_holders,
                        "mole_variant": mole_var,
                        "mole_holders": mole_holders,
                        "is_noisy_flip": is_flip,
                    }
                    day_surfaced.append(leak_rec)
                    leaks_surfaced.append(leak_rec)

        last_of_day = (
            (i + 1 == len(ep.steps))
            or (ep.steps[i + 1].day != st.day)
            or (tool == "accuse")
        )
        if last_of_day:
            for prev in ep.steps[sp.seen : i + 1]:
                if prev.tool != "accuse":
                    sp._ingest(prev)
            sp.seen = i + 1
            post = sp.belief() if sp.obs.employees else {}
            p_mole = float(post.get(true_mole, 0.0)) if post else 0.0
            top_emp = max(post, key=post.get) if post else None
            p_top = float(post[top_emp]) if (post and top_emp is not None) else 0.0
            p_acc_final = (
                float(post.get(str(final_accused_emp), 0.0))
                if (post and final_accused_emp)
                else 0.0
            )
            vis_v = float(env.visible_V())
            true_v = float(round(env.V, 10))
            exp_true_v = float(sp.expected_true_V())
            break_even = 1.0 / (1.0 + vis_v) if (1.0 + vis_v) > 0 else 1.0
            ev_top = float(accuse_value(p_top, exp_true_v, params)) if post else -1.0
            ranked = sorted(post.items(), key=lambda kv: (-kv[1], kv[0]))[:6]
            posterior_map = {str(k): round(float(v), 4) for k, v in sorted(post.items())}

            days_out.append(
                {
                    "day": int(st.day),
                    "accused": str(args["employee"]) if tool == "accuse" else None,
                    "visible_v": round(vis_v, 6),
                    "true_v": round(true_v, 6),
                    "expected_true_v": round(exp_true_v, 6),
                    "break_even_p": round(break_even, 4),
                    "post_expected": round(ev_top, 4),
                    "calls_today": day_calls,
                    "calls_cumulative": i + 1,
                    "canaries_today": day_canaries,
                    "canaries_cumulative": canaries_total,
                    "canary_ids_today": list(day_canary_ids),
                    "interviews_today": day_interviews,
                    "interviews_cumulative": interviews_total,
                    "interviewed_today": list(day_interviewed),
                    "p_mole": round(p_mole, 6),
                    "p_mole_2dp": round(p_mole, 2),
                    "top_suspect": top_emp,
                    "p_top": round(p_top, 6),
                    "p_accused_final": round(p_acc_final, 6),
                    "top_posteriors": [
                        {"employee": emp_id, "p": round(float(prob), 4)}
                        for emp_id, prob in ranked
                    ],
                    "posteriors": posterior_map,
                    "surfaced_today": list(day_surfaced),
                    "tool_counts_today": {k: int(day_tools[k]) for k in sorted(day_tools)},
                    "steps_today": list(day_step_logs),
                }
            )
            day_calls = 0
            day_canaries = 0
            day_canary_ids = []
            day_interviews = 0
            day_interviewed = []
            day_surfaced = []
            day_tools = Counter()
            day_step_logs = []

    rep_res = env.result("replay")
    rec_score = float(ep_raw["score"])
    if abs(rep_res.score - rec_score) > 1e-9 or rep_res.accused != ep_raw.get("accused"):
        raise RuntimeError(
            f"Replay verification mismatch for {run_key} seed={seed}: "
            f"recorded=({rec_score}, {ep_raw.get('accused')}) vs replayed=({rep_res.score}, {rep_res.accused})"
        )

    meta = ep_raw.get("meta") if isinstance(ep_raw.get("meta"), dict) else {}
    wall_s = round(float(meta["wall_s"]), 1) if isinstance(meta.get("wall_s"), (int, float)) else None

    return {
        "key": run_key,
        "agent": sanitize_ascii(str(ep_raw["agent"])),
        "display_label": sanitize_ascii(display_label),
        "short_label": sanitize_ascii(short_label),
        "harness_badge": sanitize_ascii(harness_badge),
        "score": round(rec_score, 2),
        "accused": ep_raw.get("accused"),
        "correct": bool(ep_raw.get("correct")),
        "final_day": int(ep_raw["final_day"]),
        "end_reason": sanitize_ascii(str(ep_raw.get("end_reason", ""))),
        "tool_calls": len(raw_steps),
        "canaries_planted_count": canaries_total,
        "canaries_days_1_to_3": canaries_d1_3,
        "interviews_count": interviews_total,
        "wall_s": wall_s,
        "replay_verified": True,
        "source_file": sanitize_ascii(str(ep_raw.get("_source_rel", ""))),
        "canaries_planted": canaries_planted,
        "leaks_surfaced": leaks_surfaced,
        "days": days_out,
    }


def verify_locked_headline(root: Path) -> dict[str, Any]:
    gap_md = root / "docs/reports/gap.md"
    if not gap_md.is_file():
        raise FileNotFoundError(f"Missing required report: {gap_md}")
    txt = gap_md.read_text(encoding="utf-8")
    required_tokens = (
        "65% [24%, 98%]",
        "72% [52%, 91%]",
        "111% [99%, 127%]",
        "101% [85%, 119%]",
        "95% [62%, 140%]",
        "84% [65%, 106%]",
    )
    for tok in required_tokens:
        if tok not in txt:
            raise ValueError(f"docs/reports/gap.md missing expected locked token: {tok}")
    return {
        "source": "docs/reports/gap.md",
        "tiers_version": "v1.4",
        "seeds": "0-29",
        "n": 30,
        "banner_primary": (
            "Hard, judges' harness OpenCode/MCP (opencode:google/gemini-4-carbon): "
            "72% [52%, 91%] of solver luck-adjusted | 65% [24%, 98%] raw | n=30 paired dev seeds 0-29"
        ),
        "banner_secondary": (
            "Parity on Medium OpenCode/MCP: 101% [85%, 119%] luck-adjusted, 111% [99%, 127%] raw (n=30) | "
            "In-process gemini-4-carbon on Hard: 84% [65%, 106%] luck-adjusted, 95% [62%, 140%] raw (n=30)"
        ),
        "hard_opencode": {
            "luck_adjusted": "72% [52%, 91%]",
            "raw": "65% [24%, 98%]",
            "n": 30,
            "agent_mean": 0.322,
            "solver_mean": 0.499,
        },
        "medium_opencode": {
            "luck_adjusted": "101% [85%, 119%]",
            "raw": "111% [99%, 127%]",
            "n": 30,
            "parity": True,
        },
        "hard_inprocess": {
            "luck_adjusted": "84% [65%, 106%]",
            "raw": "95% [62%, 140%]",
            "n": 30,
            "parity": True,
        },
    }


def cross_check_optional_w4_forensics(root: Path, payload: dict[str, Any]) -> None:
    w4_path = root / "docs/demo/seed6_seed26_forensics.json"
    if not w4_path.is_file():
        return
    w4 = json.loads(w4_path.read_text(encoding="utf-8"))
    w4_seeds = w4.get("seeds") or {}
    for seed_key in ("6", "26"):
        if seed_key not in w4_seeds:
            continue
        ours = payload["cases"][seed_key]
        theirs = w4_seeds[seed_key]
        if ours["true_mole"] != theirs["true_mole"]:
            raise ValueError(f"Seed {seed_key} mole mismatch with w4 forensics")
        for r_key, w4_rkey in (("opencode", "gemini"), ("solver", "solver")):
            our_run = next(r for r in ours["runs"] if r["key"] == r_key)
            their_run = theirs["runs"][w4_rkey]
            if abs(our_run["score"] - float(their_run["score"])) > 1e-9:
                raise ValueError(f"Seed {seed_key} {r_key} score mismatch with w4 forensics")
            if our_run["tool_calls"] != int(their_run["tool_calls"]):
                raise ValueError(f"Seed {seed_key} {r_key} tool_calls mismatch with w4 forensics")
            if our_run["final_day"] != int(their_run["final_day"]):
                raise ValueError(f"Seed {seed_key} {r_key} final_day mismatch with w4 forensics")


def build_payload(root: Path = ROOT) -> dict[str, Any]:
    os.environ.setdefault("CANARY_ALLOW_DEV", "1")
    from canary.rules import TIERS

    headline = verify_locked_headline(root)
    hard_params = TIERS["hard"]

    s6_opencode_raw = load_committed_episode(root, OPENCODE_DIRS, 6)
    s6_solver_raw = load_committed_episode(root, SOLVER_DIRS, 6)
    s6_inproc_raw = load_committed_episode(root, INPROC_DIRS, 6)
    s6_roster, s6_decoy, s6_ah = probe_roster_and_decoy("hard", 6)
    s6_emp_map = {str(e["id"]): e for e in s6_roster}
    s6_tx = extract_transcript_rationale(root, 6)

    s6_opencode = replay_and_extract_run(
        s6_opencode_raw,
        "opencode",
        "opencode:google/gemini-4-carbon",
        "OpenCode Gemini 4 Carbon",
        "Judges' Harness (OpenCode/MCP)",
        "e34",
    )
    s6_opencode["rationale"] = s6_tx["final_text"]

    s6_solver = replay_and_extract_run(
        s6_solver_raw,
        "solver",
        "SolverPolicy (reference)",
        "SolverPolicy",
        "Exact Bayesian Reference",
        "e34",
    )
    s6_solver["rationale"] = (
        "Systematic 3-variant canary bisection (9 canaries, 0 interviews, 52 calls). "
        "Surfaced c3-2=A (e31, e34) on Day 5 (P=0.63, held off until decisive confirmation) "
        "and solo canary c4=C (e34) on Day 6 (P=1.00), accusing e34 at +0.71."
    )

    s6_inproc = replay_and_extract_run(
        s6_inproc_raw,
        "inproc",
        "in-process gemini-4-carbon",
        "In-Process Gemini 4 Carbon",
        "In-Process Loop (Full History)",
        "e34",
    )
    s6_inproc["rationale"] = (
        "Conducted 85 low-LR interviews across 15 days (151 calls). On Day 7, canary c4-2 "
        "(planted Day 4, mole e34 held variant Y) suffered the 5% readout flip to variant Z "
        "(e12, e18, e24), collapsing P(e34) to 0.002 and leading to a wrong Day 15 accusation of innocent e18 (-1.00)."
    )

    s26_opencode_raw = load_committed_episode(root, OPENCODE_DIRS, 26)
    s26_solver_raw = load_committed_episode(root, SOLVER_DIRS, 26)
    s26_roster, s26_decoy, s26_ah = probe_roster_and_decoy("hard", 26)
    s26_emp_map = {str(e["id"]): e for e in s26_roster}
    s26_tx = extract_transcript_rationale(root, 26)

    s26_opencode = replay_and_extract_run(
        s26_opencode_raw,
        "opencode",
        "opencode:google/gemini-4-carbon",
        "OpenCode Gemini 4 Carbon",
        "Judges' Harness (OpenCode/MCP)",
        "e08",
    )
    s26_opencode["rationale"] = s26_tx["final_text"]

    s26_solver = replay_and_extract_run(
        s26_solver_raw,
        "solver",
        "SolverPolicy (reference)",
        "SolverPolicy",
        "Exact Bayesian Reference",
        "e08",
    )
    s26_solver["rationale"] = (
        "Planted 6 canaries in Days 1-3 and 11 canaries by Day 6 (0 interviews, 60 calls). "
        "Surfaced c3-2=C on Day 5 and single-holder canary c5-2=A (e08) on Day 7, "
        "accusing true mole e08 at P=0.97 (+0.69) with full immunity to any single 5% readout flip."
    )

    case_6 = {
        "seed": 6,
        "tier": "hard",
        "tab_title": "Hard Seed 6: Caught (Mole e34)",
        "verdict_tag": "CAUGHT VS IN-PROCESS FOOLED",
        "subtitle": (
            "Orthogonal early canaries let OpenCode (+0.73, Day 6, 57 calls) and SolverPolicy (+0.71, Day 6, 52 calls) "
            "catch Sofia Niemi (e34), while in-process gemini-4-carbon (-1.00, Day 15, 151 calls) gets fooled by a Day 7 5% flip."
        ),
        "max_day": 15,
        "default_day": 6,
        "horizon_days": int(hard_params.n_days),
        "tool_call_cap": int(hard_params.tool_call_cap),
        "fingerprint_accuracy": float(hard_params.fingerprint_accuracy),
        "true_mole": "e34",
        "true_mole_profile": s6_emp_map["e34"],
        "decoy": s6_decoy,
        "decoy_profile": s6_emp_map[s6_decoy] if s6_decoy else None,
        "fooled_accused": "e18",
        "fooled_accused_profile": s6_emp_map["e18"],
        "after_hours_d1_9": s6_ah,
        "employees": s6_roster,
        "moments": [
            {
                "day": 1,
                "label": "Day 1: Early Canary Split",
                "detail": "OpenCode and SolverPolicy both plant 2 multi-variant canaries on Day 1; OpenCode also spends 5 actions on interviews.",
            },
            {
                "day": 3,
                "label": "Day 3: c1-2=B Surfaces",
                "detail": "OpenCode's Day 1 canary c1-2 surfaces with variant B (e28, e30, e34, e35), lifting P(e34) to 0.21; OpenCode plants orthogonal c3-2.",
            },
            {
                "day": 6,
                "label": "Day 6: e34 Caught (+0.73 / +0.71)",
                "detail": "c3-2=A (e23, e34) surfaces for OpenCode (P(e34)=1.00, +0.73, 57 calls) and c4=C (e34) surfaces for SolverPolicy (P(e34)=1.00, +0.71, 52 calls).",
            },
            {
                "day": 7,
                "label": "Day 7: In-Process 5% Flip (Y->Z)",
                "detail": "In-process gemini-4-carbon's canary c4-2 suffers a 5% readout flip (mole e34 held Y, feed reports Z held by e12, e18, e24), dropping P(e34) to 0.002.",
            },
            {
                "day": 15,
                "label": "Day 15: In-Process Fooled (-1.00)",
                "detail": "After 85 interviews and 151 calls without recovering from the Day 7 flip, in-process gemini-4-carbon accuses innocent e18 (Laura Saarinen) for -1.00.",
            },
        ],
        "forensic_summary": {
            "title": "Why OpenCode (+0.73) & Solver (+0.71) Caught e34 While In-Process (-1.00) Was Fooled",
            "bullets": [
                "Orthogonal intersection: OpenCode planted 6 canaries in Days 1-3; c1-2=B (e28, e30, e34, e35) + c3-2=A (e23, e34) uniquely isolated e34 (Sofia Niemi) on Day 6 (+0.73, 57 calls).",
                "Canary cost delta (+0.73 vs +0.71): SolverPolicy also caught e34 on Day 6 in fewer calls (52 vs 57) with 0 interviews, scoring 0.02 lower solely because it planted 9 systematic canaries (-0.09 V) vs OpenCode's 7 (-0.07 V).",
                "Single-canary fragility in-process: In-process gemini-4-carbon spent 85 interviews and relied on canary c4-2, whose 5% noisy flip on Day 7 (Y -> Z) shifted belief onto innocent e18, ending in a -1.00 accusation on Day 15 (151 calls).",
            ],
        },
        "runs": [s6_opencode, s6_solver, s6_inproc],
    }

    case_26 = {
        "seed": 26,
        "tier": "hard",
        "tab_title": "Hard Seed 26: Fooled (Mole e08)",
        "verdict_tag": "5% S1 FLIP + FRAMING TRAP",
        "subtitle": (
            "Upstream canary starvation (0 canaries Days 1-3, 43 interviews) leaves OpenCode vulnerable to a single Day 10 "
            "5% readout flip (c6-2: S3 -> S1) + framed after-hours logs, accusing innocent e04 (-1.00, 91 calls) while SolverPolicy catches e08 on Day 7 (+0.69, 11 canaries, 60 calls)."
        ),
        "max_day": 10,
        "default_day": 10,
        "horizon_days": int(hard_params.n_days),
        "tool_call_cap": int(hard_params.tool_call_cap),
        "fingerprint_accuracy": float(hard_params.fingerprint_accuracy),
        "true_mole": "e08",
        "true_mole_profile": s26_emp_map["e08"],
        "decoy": s26_decoy,
        "decoy_profile": s26_emp_map[s26_decoy] if s26_decoy else None,
        "fooled_accused": "e04",
        "fooled_accused_profile": s26_emp_map["e04"],
        "after_hours_d1_9": s26_ah,
        "employees": s26_roster,
        "moments": [
            {
                "day": 3,
                "label": "Days 1-3: 0 vs 6 Canaries",
                "detail": "OpenCode plants 0 canaries across Days 1-3 (spending actions on interviews), whereas SolverPolicy has already planted 6 bisection canaries.",
            },
            {
                "day": 6,
                "label": "Day 6: Research 3x3 Grid Planted",
                "detail": "OpenCode plants orthogonal 3-variant canaries c6 (D1/D2/D3) and c6-2 (S1/S2/S3) across 9 Research suspects; SolverPolicy reaches 11 total canaries.",
            },
            {
                "day": 7,
                "label": "Day 7: Solver Catches e08 (+0.69)",
                "detail": "Single-holder canary c5-2=A (e08) surfaces for SolverPolicy, lifting P(e08) to 0.97 and catching true mole Nea Nieminen (e08) on Day 7 (+0.69, 60 calls).",
            },
            {
                "day": 9,
                "label": "Day 9: Pre-Flip Split (P(e08)=0.48)",
                "detail": "After c6=D1 (e04, e08, e37) surfaced on Day 8, OpenCode's exact posterior is split between true mole e08 (0.48) and innocent e04 (0.45).",
            },
            {
                "day": 10,
                "label": "Day 10: 5% S1 Flip -> Fooled (-1.00)",
                "detail": "c6-2 flips from mole e08's S3 to S1 (e04, e20, e28). D1 intersect S1 = {e04} plus 3 framed after-hours logs drop P(e08) 0.48->0.03 (P(e04)=0.95); OpenCode accuses innocent e04 (-1.00, 91 calls).",
            },
        ],
        "forensic_summary": {
            "title": "Anatomy of the Seed 26 Fooled Moment: Late Canaries + 5% S1 Readout Flip + Framing Noise",
            "bullets": [
                "Upstream exploration deficit: OpenCode planted 0 canaries in Days 1-3 and ran 43 low-signal interviews, whereas SolverPolicy planted 6 canaries in Days 1-3 (11 by Day 6, 0 interviews) and caught e08 on Day 7 (+0.69, 60 calls).",
                "The 1-in-20 readout flip (Day 10): True mole e08 (Nea Nieminen) held c6=D1 and c6-2=S3, but hard tier has 95% canary fingerprint accuracy; c6-2 surfaced with noisy readout S1 (e04, e20, e28).",
                "Rational downstream trigger, fatal upstream thinness: Intersecting D1 and S1 pointed to innocent e04 (Lauri Laitinen, P(e04)=0.95, P(e08): 0.48 -> 0.03), reinforced by 3 framed after-hours access logs and transcript claim 'uniquely identified' (-1.00, 91 calls).",
            ],
        },
        "runs": [s26_opencode, s26_solver],
    }

    payload = {
        "schema_version": "1.0",
        "headline": headline,
        "case_order": ["6", "26"],
        "cases": {
            "6": case_6,
            "26": case_26,
        },
    }
    cross_check_optional_w4_forensics(root, payload)
    return payload


HTML_HEAD_CSS = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Canary v1.4 Replay Forensics | Seed 6 &amp; Seed 26</title>
<style>
:root {
  color-scheme: light dark;
}
* {
  box-sizing: border-box;
}
html, body {
  margin: 0;
  padding: 0;
  background: rgb(243, 239, 230);
  color: rgb(26, 25, 21);
  font-family: system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
  font-size: 14px;
  line-height: 1.48;
  -webkit-font-smoothing: antialiased;
}
.mono {
  font-family: ui-monospace, "SFMono-Regular", Menlo, Consolas, monospace;
  font-variant-numeric: tabular-nums;
}
.mast {
  position: sticky;
  top: 0;
  z-index: 20;
  background: rgb(243, 239, 230);
  border-bottom: 2px solid rgb(26, 25, 21);
  padding: 10px 20px;
}
.mast-top {
  max-width: 1480px;
  margin: 0 auto;
  display: flex;
  flex-wrap: wrap;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
}
.brand-wrap {
  display: flex;
  align-items: baseline;
  gap: 12px;
  flex-wrap: wrap;
}
.brand-title {
  font-family: Georgia, "Times New Roman", serif;
  font-size: 22px;
  font-weight: 700;
  letter-spacing: 0.01em;
}
.brand-kicker {
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  padding: 2px 7px;
  background: rgb(255, 225, 77);
  color: rgb(26, 25, 21);
  border: 1px solid rgb(26, 25, 21);
}
.offline-pill {
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: rgb(75, 72, 64);
  border: 1px solid rgb(26, 25, 21);
  background: rgb(251, 249, 244);
  padding: 3px 8px;
}
.headline-bar {
  max-width: 1480px;
  margin: 8px auto 0;
  padding: 8px 12px;
  background: rgb(251, 249, 244);
  border: 1px solid rgb(26, 25, 21);
  display: flex;
  flex-wrap: wrap;
  justify-content: space-between;
  align-items: baseline;
  gap: 8px 18px;
  font-size: 12.5px;
}
.hl-strong {
  font-weight: 700;
  background: rgb(255, 225, 77);
  color: rgb(26, 25, 21);
  padding: 1px 5px;
}
.hl-sub {
  color: rgb(75, 72, 64);
  font-size: 12px;
}
.page {
  max-width: 1480px;
  margin: 0 auto;
  padding: 16px 20px 28px;
}
.case-tabs {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
  gap: 10px;
  margin-bottom: 14px;
}
.case-tab {
  text-align: left;
  cursor: pointer;
  background: rgb(251, 249, 244);
  color: rgb(26, 25, 21);
  border: 1px solid rgb(26, 25, 21);
  padding: 11px 14px;
  transition: background 0.12s ease;
}
.case-tab:hover {
  background: rgb(235, 230, 218);
}
.case-tab.active {
  background: rgb(26, 25, 21);
  color: rgb(251, 249, 244);
  border-width: 2px;
}
.case-tab-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 8px;
  font-weight: 700;
  font-size: 14px;
}
.case-tab-tag {
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  padding: 2px 6px;
  background: rgb(255, 225, 77);
  color: rgb(26, 25, 21);
}
.case-tab-desc {
  margin-top: 4px;
  font-size: 12px;
  opacity: 0.88;
}
.sheet {
  background: rgb(251, 249, 244);
  border: 1px solid rgb(26, 25, 21);
  margin-bottom: 14px;
}
.sheet-h {
  display: flex;
  flex-wrap: wrap;
  justify-content: space-between;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  background: rgb(235, 230, 218);
  border-bottom: 1px solid rgb(26, 25, 21);
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.11em;
  text-transform: uppercase;
}
.sheet-body {
  padding: 12px 14px;
}
.case-banner-title {
  font-family: Georgia, "Times New Roman", serif;
  font-size: 20px;
  font-weight: 700;
  margin: 0 0 4px;
}
.case-banner-sub {
  margin: 0 0 10px;
  color: rgb(75, 72, 64);
  font-size: 13px;
}
.meta-pills {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
.pill {
  font-size: 11.5px;
  padding: 3px 8px;
  border: 1px solid rgb(212, 204, 187);
  background: rgb(243, 239, 230);
}
.pill-mole {
  border-color: rgb(45, 106, 69);
  background: rgba(45, 106, 69, 0.12);
  font-weight: 600;
}
.pill-fooled {
  border-color: rgb(163, 49, 28);
  background: rgb(242, 220, 213);
  color: rgb(120, 28, 12);
  font-weight: 600;
}
.pill-decoy {
  border-color: rgb(26, 25, 21);
  background: rgba(255, 225, 77, 0.45);
  font-weight: 600;
}
.scrubber-controls {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 10px;
}
.btn {
  cursor: pointer;
  background: rgb(251, 249, 244);
  color: rgb(26, 25, 21);
  border: 1px solid rgb(26, 25, 21);
  padding: 5px 11px;
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.03em;
}
.btn:hover:not(:disabled) {
  background: rgb(26, 25, 21);
  color: rgb(251, 249, 244);
}
.btn:disabled {
  opacity: 0.4;
  cursor: default;
}
.btn-play {
  background: rgb(26, 25, 21);
  color: rgb(251, 249, 244);
}
.btn-play:hover:not(:disabled) {
  background: rgb(255, 225, 77);
  color: rgb(26, 25, 21);
}
.day-readout {
  font-size: 18px;
  font-weight: 700;
  min-width: 112px;
}
.day-slider {
  flex: 1;
  min-width: 180px;
  accent-color: rgb(26, 25, 21);
  cursor: pointer;
}
.day-strip {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  margin-top: 10px;
}
.day-tick {
  cursor: pointer;
  min-width: 40px;
  padding: 4px 6px;
  border: 1px solid rgb(212, 204, 187);
  background: rgb(243, 239, 230);
  font-size: 11px;
  text-align: center;
}
.day-tick:hover {
  border-color: rgb(26, 25, 21);
}
.day-tick.current {
  background: rgb(255, 225, 77);
  color: rgb(26, 25, 21);
  border-color: rgb(26, 25, 21);
  font-weight: 700;
}
.day-tick.event-good {
  border-bottom: 3px solid rgb(45, 106, 69);
}
.day-tick.event-bad {
  border-bottom: 3px solid rgb(163, 49, 28);
}
.moments-row {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 10px;
}
.moment-btn {
  cursor: pointer;
  background: rgb(243, 239, 230);
  border: 1px solid rgb(26, 25, 21);
  padding: 4px 9px;
  font-size: 11.5px;
  font-weight: 600;
}
.moment-btn.active, .moment-btn:hover {
  background: rgb(255, 225, 77);
  color: rgb(26, 25, 21);
}
.moment-callout {
  margin-top: 10px;
  padding: 8px 11px;
  border-left: 4px solid rgb(26, 25, 21);
  background: rgb(243, 239, 230);
  font-size: 12.5px;
}
.chart-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(360px, 1fr));
  gap: 12px;
}
.chart-box {
  border: 1px solid rgb(212, 204, 187);
  background: rgb(243, 239, 230);
  padding: 8px 10px;
}
.chart-cap {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  margin-bottom: 6px;
}
.chart-canvas {
  width: 100%;
  height: 150px;
  display: block;
  cursor: crosshair;
}
.legend-row {
  display: flex;
  flex-wrap: wrap;
  gap: 14px;
  margin-top: 6px;
  font-size: 11.5px;
}
.legend-item {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}
.swatch {
  display: inline-block;
  width: 14px;
  height: 3px;
}
.runs-grid {
  display: grid;
  gap: 12px;
  margin-bottom: 14px;
}
.runs-grid.cols-3 {
  grid-template-columns: repeat(3, minmax(0, 1fr));
}
.runs-grid.cols-2 {
  grid-template-columns: repeat(2, minmax(0, 1fr));
}
@media (max-width: 1100px) {
  .runs-grid.cols-3, .runs-grid.cols-2 {
    grid-template-columns: 1fr;
  }
}
.run-card {
  background: rgb(251, 249, 244);
  border: 1px solid rgb(26, 25, 21);
  display: flex;
  flex-direction: column;
}
.run-head {
  padding: 10px 12px;
  background: rgb(235, 230, 218);
  border-bottom: 1px solid rgb(26, 25, 21);
}
.run-title-row {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 8px;
}
.run-name {
  font-weight: 700;
  font-size: 13.5px;
}
.run-sub {
  font-size: 11px;
  color: rgb(75, 72, 64);
  margin-top: 2px;
}
.badge {
  font-size: 11px;
  font-weight: 700;
  padding: 2px 7px;
  border: 1px solid rgb(26, 25, 21);
  white-space: nowrap;
}
.badge-caught {
  background: rgb(45, 106, 69);
  color: rgb(255, 255, 255);
  border-color: rgb(45, 106, 69);
}
.badge-fooled {
  background: rgb(163, 49, 28);
  color: rgb(255, 255, 255);
  border-color: rgb(163, 49, 28);
}
.badge-active {
  background: rgb(255, 225, 77);
  color: rgb(26, 25, 21);
}
.vitals-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  border-bottom: 1px solid rgb(212, 204, 187);
}
.vital-cell {
  padding: 8px 10px;
  border-right: 1px solid rgb(212, 204, 187);
  border-bottom: 1px solid rgb(212, 204, 187);
}
.vital-cell:nth-child(3n) {
  border-right: 0;
}
.vital-lbl {
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.09em;
  text-transform: uppercase;
  color: rgb(124, 119, 107);
}
.vital-val {
  font-size: 17px;
  font-weight: 700;
  margin-top: 2px;
}
.vital-note {
  font-size: 10.5px;
  color: rgb(124, 119, 107);
}
.run-sec {
  padding: 9px 12px;
  border-bottom: 1px solid rgb(212, 204, 187);
}
.run-sec:last-child {
  border-bottom: 0;
}
.sec-lbl {
  font-size: 10.5px;
  font-weight: 700;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  color: rgb(124, 119, 107);
  margin-bottom: 6px;
  display: flex;
  justify-content: space-between;
}
.post-row {
  display: grid;
  grid-template-columns: 118px 1fr 48px;
  align-items: center;
  gap: 6px;
  font-size: 11.5px;
  margin-bottom: 4px;
}
.post-bar-bg {
  height: 9px;
  background: rgb(235, 230, 218);
  border: 1px solid rgb(212, 204, 187);
  overflow: hidden;
}
.post-bar-fill {
  height: 100%;
  background: rgb(26, 25, 21);
}
.post-bar-fill.is-mole {
  background: rgb(45, 106, 69);
}
.post-bar-fill.is-wrong {
  background: rgb(163, 49, 28);
}
.leak-list, .canary-list, .step-list {
  list-style: none;
  margin: 0;
  padding: 0;
  font-size: 11.5px;
}
.leak-list li, .canary-list li, .step-list li {
  padding: 4px 0;
  border-bottom: 1px dashed rgb(212, 204, 187);
}
.leak-list li:last-child, .canary-list li:last-child, .step-list li:last-child {
  border-bottom: 0;
}
.step-list {
  max-height: 185px;
  overflow-y: auto;
}
.flip-badge {
  display: inline-block;
  background: rgb(163, 49, 28);
  color: rgb(255, 255, 255);
  font-size: 10px;
  font-weight: 700;
  padding: 1px 5px;
  margin-left: 5px;
}
.ok-tag {
  display: inline-block;
  background: rgba(45, 106, 69, 0.16);
  color: rgb(30, 82, 50);
  font-size: 10px;
  font-weight: 700;
  padding: 1px 5px;
  margin-left: 5px;
}
.rationale-box {
  padding: 8px 10px;
  background: rgb(243, 239, 230);
  border-left: 3px solid rgb(26, 25, 21);
  font-size: 11.5px;
  color: rgb(55, 52, 46);
}
.forensic-bullets {
  margin: 6px 0 0;
  padding-left: 18px;
  font-size: 13px;
}
.forensic-bullets li {
  margin-bottom: 5px;
}
.roster-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(168px, 1fr));
  gap: 6px;
}
.emp-chip {
  border: 1px solid rgb(212, 204, 187);
  background: rgb(243, 239, 230);
  padding: 5px 7px;
  font-size: 11px;
}
.emp-chip.mole {
  border: 2px solid rgb(45, 106, 69);
}
.emp-chip.fooled {
  border: 2px solid rgb(163, 49, 28);
}
.emp-chip.decoy {
  border-style: dashed;
  border-color: rgb(26, 25, 21);
}
.emp-top {
  display: flex;
  justify-content: space-between;
  font-weight: 700;
}
.emp-meta {
  color: rgb(124, 119, 107);
  font-size: 10px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.foot {
  margin-top: 18px;
  padding: 12px 14px;
  border: 1px solid rgb(26, 25, 21);
  background: rgb(235, 230, 218);
  font-size: 12px;
  display: flex;
  flex-wrap: wrap;
  justify-content: space-between;
  gap: 8px 16px;
}
@media (prefers-color-scheme: dark) {
  html, body, .mast {
    background: rgb(19, 18, 15);
    color: rgb(236, 230, 214);
  }
  .mast {
    border-bottom-color: rgb(90, 85, 72);
  }
  .sheet, .run-card, .headline-bar, .case-tab, .btn, .offline-pill {
    background: rgb(28, 26, 22);
    color: rgb(236, 230, 214);
    border-color: rgb(90, 85, 72);
  }
  .sheet-h, .run-head, .foot {
    background: rgb(36, 34, 28);
    border-color: rgb(90, 85, 72);
    color: rgb(236, 230, 214);
  }
  .case-tab.active, .btn-play {
    background: rgb(236, 230, 214);
    color: rgb(19, 18, 15);
  }
  .chart-box, .moment-callout, .rationale-box, .emp-chip, .day-tick, .moment-btn, .pill {
    background: rgb(23, 22, 18);
    color: rgb(225, 219, 204);
    border-color: rgb(74, 70, 59);
  }
  .day-tick.current, .moment-btn.active, .moment-btn:hover {
    background: rgb(245, 212, 42);
    color: rgb(19, 18, 15);
  }
  .hl-sub, .case-banner-sub, .run-sub, .vital-lbl, .vital-note, .sec-lbl, .emp-meta {
    color: rgb(168, 161, 145);
  }
  .pill-fooled {
    background: rgba(163, 49, 28, 0.32);
    color: rgb(255, 205, 194);
  }
  .ok-tag {
    color: rgb(140, 224, 174);
  }
  .post-bar-bg {
    background: rgb(36, 34, 28);
    border-color: rgb(74, 70, 59);
  }
  .post-bar-fill {
    background: rgb(225, 219, 204);
  }
}
</style>
</head>
<body>
<div id="app"></div>
<script id="canary-replay-data" type="application/json">"""

HTML_SCRIPT_TAIL = """</script>
<script>
(function () {
  "use strict";

  var rawJson = document.getElementById("canary-replay-data").textContent;
  var DATA = JSON.parse(rawJson);

  var COLORS = {
    opencode: "rgb(26, 95, 180)",
    solver: "rgb(45, 106, 69)",
    inproc: "rgb(163, 49, 28)"
  };

  var state = {
    seedKey: "6",
    day: DATA.cases["6"].default_day,
    playing: false,
    timerId: null
  };

  function el(tag, className, text) {
    var node = document.createElement(tag);
    if (className) {
      node.className = className;
    }
    if (text !== undefined && text !== null) {
      node.textContent = String(text);
    }
    return node;
  }

  function clearNode(node) {
    while (node.firstChild) {
      node.removeChild(node.firstChild);
    }
  }

  function fmtSigned(val) {
    var num = Number(val);
    var fixed = num.toFixed(2);
    return num > 0 ? "+" + fixed : fixed;
  }

  function fmtPct(val) {
    return (Number(val) * 100).toFixed(1) + "%";
  }

  function getDayRecord(run, day) {
    var days = run.days;
    var best = days[0];
    for (var i = 0; i < days.length; i += 1) {
      if (days[i].day <= day) {
        best = days[i];
      }
    }
    return best;
  }

  function stopPlayback() {
    state.playing = false;
    if (state.timerId !== null) {
      window.clearInterval(state.timerId);
      state.timerId = null;
    }
  }

  function togglePlayback() {
    var activeCase = DATA.cases[state.seedKey];
    if (state.playing) {
      stopPlayback();
      render();
      return;
    }
    if (state.day >= activeCase.max_day) {
      state.day = 1;
    }
    state.playing = true;
    state.timerId = window.setInterval(function () {
      var c = DATA.cases[state.seedKey];
      if (state.day < c.max_day) {
        state.day += 1;
        render();
      } else {
        stopPlayback();
        render();
      }
    }, 950);
    render();
  }

  function selectCase(seedKey) {
    stopPlayback();
    state.seedKey = seedKey;
    state.day = DATA.cases[seedKey].default_day;
    render();
  }

  function setDay(day) {
    var c = DATA.cases[state.seedKey];
    var clamped = Math.max(1, Math.min(c.max_day, Number(day)));
    state.day = clamped;
    render();
  }

  function drawChart(canvas, activeCase, metricKey, yLabel) {
    var dpr = window.devicePixelRatio || 1;
    var rect = canvas.getBoundingClientRect();
    var width = Math.max(300, Math.floor(rect.width || 460));
    var height = 150;
    canvas.width = width * dpr;
    canvas.height = height * dpr;
    var ctx = canvas.getContext("2d");
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, width, height);

    var isDark = window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches;
    var gridColor = isDark ? "rgba(180, 174, 158, 0.22)" : "rgba(26, 25, 21, 0.14)";
    var axisColor = isDark ? "rgb(190, 184, 168)" : "rgb(90, 86, 76)";
    var cursorFill = isDark ? "rgba(245, 212, 42, 0.20)" : "rgba(255, 225, 77, 0.45)";

    var padL = 38;
    var padR = 14;
    var padT = 12;
    var padB = 24;
    var plotW = width - padL - padR;
    var plotH = height - padT - padB;
    var maxDay = activeCase.max_day;

    function xForDay(d) {
      if (maxDay <= 1) {
        return padL;
      }
      return padL + ((d - 1) / (maxDay - 1)) * plotW;
    }

    function yForVal(v) {
      var clamped = Math.max(0, Math.min(1, v));
      return padT + (1 - clamped) * plotH;
    }

    var cursorX = xForDay(state.day);
    ctx.fillStyle = cursorFill;
    ctx.fillRect(cursorX - 8, padT, 16, plotH);

    ctx.strokeStyle = gridColor;
    ctx.lineWidth = 1;
    ctx.font = "10px ui-monospace, monospace";
    ctx.fillStyle = axisColor;
    var ticks = [0, 0.5, 1.0];
    for (var t = 0; t < ticks.length; t += 1) {
      var yv = yForVal(ticks[t]);
      ctx.beginPath();
      ctx.moveTo(padL, yv);
      ctx.lineTo(width - padR, yv);
      ctx.stroke();
      ctx.fillText(ticks[t].toFixed(1), 6, yv + 3);
    }

    for (var d = 1; d <= maxDay; d += 1) {
      if (d === 1 || d === maxDay || d % 2 === 0) {
        var xv = xForDay(d);
        ctx.fillText("d" + d, xv - 6, height - 6);
      }
    }

    ctx.strokeStyle = axisColor;
    ctx.setLineDash([3, 3]);
    ctx.beginPath();
    ctx.moveTo(cursorX, padT);
    ctx.lineTo(cursorX, padT + plotH);
    ctx.stroke();
    ctx.setLineDash([]);

    for (var rIdx = 0; rIdx < activeCase.runs.length; rIdx += 1) {
      var run = activeCase.runs[rIdx];
      var col = COLORS[run.key] || "rgb(26, 25, 21)";
      ctx.strokeStyle = col;
      ctx.lineWidth = 2.2;
      ctx.beginPath();
      for (var i = 0; i < run.days.length; i += 1) {
        var pt = run.days[i];
        var px = xForDay(pt.day);
        var py = yForVal(pt[metricKey]);
        if (i === 0) {
          ctx.moveTo(px, py);
        } else {
          ctx.lineTo(px, py);
        }
      }
      ctx.stroke();

      for (var j = 0; j < run.days.length; j += 1) {
        var dpt = run.days[j];
        var dx = xForDay(dpt.day);
        var dy = yForVal(dpt[metricKey]);
        ctx.fillStyle = col;
        ctx.beginPath();
        ctx.arc(dx, dy, dpt.day === state.day ? 4.5 : 2.6, 0, Math.PI * 2);
        ctx.fill();
      }
    }

    canvas.onclick = function (ev) {
      var r = canvas.getBoundingClientRect();
      var clickX = ev.clientX - r.left;
      var ratio = (clickX - padL) / Math.max(1, plotW);
      var picked = Math.round(1 + ratio * (maxDay - 1));
      setDay(picked);
    };
  }

  function buildHeader() {
    var hdr = el("header", "mast");
    var top = el("div", "mast-top");
    var brand = el("div", "brand-wrap");
    brand.appendChild(el("span", "brand-title", "Canary"));
    brand.appendChild(el("span", "brand-kicker", "v1.4 Replay Forensics"));
    brand.appendChild(el("span", "mono", "Committed Runs: data/runs/committed/v1.4/"));
    top.appendChild(brand);
    top.appendChild(el("span", "offline-pill mono", "100% Offline Local HTML | 0 API Calls | Fresh-Env Verified"));
    hdr.appendChild(top);

    var hbar = el("div", "headline-bar");
    var left = el("div");
    left.appendChild(el("span", "mono", "Locked Headline (" + DATA.headline.source + "): "));
    left.appendChild(el("span", "hl-strong mono", DATA.headline.banner_primary));
    hbar.appendChild(left);
    hbar.appendChild(el("div", "hl-sub mono", DATA.headline.banner_secondary));
    hdr.appendChild(hbar);
    return hdr;
  }

  function buildCaseTabs() {
    var wrap = el("div", "case-tabs");
    for (var i = 0; i < DATA.case_order.length; i += 1) {
      (function (sKey) {
        var c = DATA.cases[sKey];
        var btn = el("button", "case-tab" + (state.seedKey === sKey ? " active" : ""));
        btn.type = "button";
        btn.setAttribute("data-seed-tab", sKey);
        var head = el("div", "case-tab-head");
        head.appendChild(el("span", "", c.tab_title));
        head.appendChild(el("span", "case-tab-tag mono", c.verdict_tag));
        btn.appendChild(head);
        btn.appendChild(el("div", "case-tab-desc", c.subtitle));
        btn.addEventListener("click", function () {
          selectCase(sKey);
        });
        wrap.appendChild(btn);
      })(DATA.case_order[i]);
    }
    return wrap;
  }

  function buildScrubberSheet(activeCase) {
    var sheet = el("section", "sheet");
    var sh = el("div", "sheet-h");
    sh.appendChild(el("span", "", "Case File & Synchronized Day Scrubber"));
    sh.appendChild(el("span", "mono", "Keys: Left/Right = Scrub Day | Space = Play/Pause | 1/2 = Switch Seed"));
    sheet.appendChild(sh);

    var body = el("div", "sheet-body");
    body.appendChild(el("h1", "case-banner-title", activeCase.tab_title));
    body.appendChild(el("p", "case-banner-sub", activeCase.subtitle));

    var pills = el("div", "meta-pills");
    var mp = activeCase.true_mole_profile;
    pills.appendChild(
      el("span", "pill pill-mole mono", "True Mole: " + mp.id + " (" + mp.name + ", " + mp.dept + " " + mp.role + ")")
    );
    if (activeCase.decoy_profile) {
      var dp = activeCase.decoy_profile;
      pills.appendChild(
        el("span", "pill pill-decoy mono", "Angry-Message Decoy: " + dp.id + " (" + dp.name + ", " + dp.dept + ")")
      );
    }
    if (activeCase.fooled_accused_profile) {
      var fp = activeCase.fooled_accused_profile;
      pills.appendChild(
        el("span", "pill pill-fooled mono", "Wrongly Accused Innocent: " + fp.id + " (" + fp.name + ", " + fp.dept + ")")
      );
    }
    pills.appendChild(
      el(
        "span",
        "pill mono",
        "Rules: v1.4 hard | 40 staff | horizon " + activeCase.horizon_days + "d | canary fingerprint accuracy " +
          Math.round(activeCase.fingerprint_accuracy * 100) + "% (5% flip rate)"
      )
    );
    body.appendChild(pills);

    var controls = el("div", "scrubber-controls");
    controls.style.marginTop = "12px";

    var prevBtn = el("button", "btn mono", "< Prev Day");
    prevBtn.type = "button";
    prevBtn.disabled = state.day <= 1;
    prevBtn.addEventListener("click", function () {
      stopPlayback();
      setDay(state.day - 1);
    });
    controls.appendChild(prevBtn);

    var playBtn = el("button", "btn btn-play mono", state.playing ? "Pause" : "Play Days");
    playBtn.type = "button";
    playBtn.addEventListener("click", togglePlayback);
    controls.appendChild(playBtn);

    var nextBtn = el("button", "btn mono", "Next Day >");
    nextBtn.type = "button";
    nextBtn.disabled = state.day >= activeCase.max_day;
    nextBtn.addEventListener("click", function () {
      stopPlayback();
      setDay(state.day + 1);
    });
    controls.appendChild(nextBtn);

    controls.appendChild(el("span", "day-readout mono", "Day " + state.day + " / " + activeCase.max_day));

    var slider = el("input", "day-slider");
    slider.type = "range";
    slider.min = "1";
    slider.max = String(activeCase.max_day);
    slider.value = String(state.day);
    slider.setAttribute("aria-label", "Day scrubber");
    slider.addEventListener("input", function () {
      stopPlayback();
      setDay(Number(slider.value));
    });
    controls.appendChild(slider);
    body.appendChild(controls);

    var dayStrip = el("div", "day-strip");
    for (var d = 1; d <= activeCase.max_day; d += 1) {
      (function (dayNum) {
        var cls = "day-tick mono" + (dayNum === state.day ? " current" : "");
        var tagTxt = "D" + dayNum;
        for (var r = 0; r < activeCase.runs.length; r += 1) {
          var run = activeCase.runs[r];
          if (run.final_day === dayNum) {
            cls += run.correct ? " event-good" : " event-bad";
          }
          for (var lk = 0; lk < run.leaks_surfaced.length; lk += 1) {
            if (run.leaks_surfaced[lk].surfaced_day === dayNum && run.leaks_surfaced[lk].is_noisy_flip) {
              cls += " event-bad";
            }
          }
        }
        var tick = el("button", cls, tagTxt);
        tick.type = "button";
        tick.addEventListener("click", function () {
          stopPlayback();
          setDay(dayNum);
        });
        dayStrip.appendChild(tick);
      })(d);
    }
    body.appendChild(dayStrip);

    var momentsRow = el("div", "moments-row");
    var activeMomentDetail = null;
    for (var m = 0; m < activeCase.moments.length; m += 1) {
      (function (mom) {
        var isCurr = mom.day === state.day;
        if (isCurr) {
          activeMomentDetail = mom;
        }
        var mBtn = el("button", "moment-btn mono" + (isCurr ? " active" : ""), mom.label);
        mBtn.type = "button";
        mBtn.addEventListener("click", function () {
          stopPlayback();
          setDay(mom.day);
        });
        momentsRow.appendChild(mBtn);
      })(activeCase.moments[m]);
    }
    body.appendChild(momentsRow);

    if (activeMomentDetail) {
      var callout = el("div", "moment-callout");
      callout.appendChild(el("strong", "mono", activeMomentDetail.label + ": "));
      callout.appendChild(el("span", "", activeMomentDetail.detail));
      body.appendChild(callout);
    }

    sheet.appendChild(body);
    return sheet;
  }

  function buildChartsSheet(activeCase, canvasesOut) {
    var sheet = el("section", "sheet");
    var sh = el("div", "sheet-h");
    sh.appendChild(el("span", "", "Bayesian Posterior P(True Mole) & Visible Company Value V(t)"));
    sh.appendChild(el("span", "mono", "Click chart to scrub day"));
    sheet.appendChild(sh);

    var body = el("div", "sheet-body");
    var grid = el("div", "chart-grid");

    var boxP = el("div", "chart-box");
    var capP = el("div", "chart-cap");
    capP.appendChild(el("span", "", "Exact Solver Posterior P(" + activeCase.true_mole + " | Agent Observations)"));
    capP.appendChild(el("span", "mono", "0.0 -> 1.0"));
    boxP.appendChild(capP);
    var canvasP = el("canvas", "chart-canvas");
    boxP.appendChild(canvasP);
    grid.appendChild(boxP);

    var boxV = el("div", "chart-box");
    var capV = el("div", "chart-cap");
    capV.appendChild(el("span", "", "Agent-Visible Company Value V (Known Surfaced Leaks)"));
    capV.appendChild(el("span", "mono", "Initial V = 1.00"));
    boxV.appendChild(capV);
    var canvasV = el("canvas", "chart-canvas");
    boxV.appendChild(canvasV);
    grid.appendChild(boxV);

    body.appendChild(grid);

    var leg = el("div", "legend-row mono");
    for (var i = 0; i < activeCase.runs.length; i += 1) {
      var r = activeCase.runs[i];
      var item = el("span", "legend-item");
      var sw = el("span", "swatch");
      sw.style.background = COLORS[r.key] || "rgb(26, 25, 21)";
      item.appendChild(sw);
      item.appendChild(
        el("span", "", r.display_label + " (" + fmtSigned(r.score) + ", Day " + r.final_day + ", " + r.tool_calls + " calls)")
      );
      leg.appendChild(item);
    }
    body.appendChild(leg);
    sheet.appendChild(body);

    canvasesOut.push({ canvas: canvasP, metric: "p_mole" });
    canvasesOut.push({ canvas: canvasV, metric: "visible_v" });
    return sheet;
  }

  function buildRunCard(activeCase, run, empLookup) {
    var card = el("article", "run-card");
    card.setAttribute("data-run-key", run.key);
    var rec = getDayRecord(run, state.day);
    var endedBefore = state.day > run.final_day;
    var endedNow = state.day === run.final_day;

    var head = el("div", "run-head");
    var titleRow = el("div", "run-title-row");
    var left = el("div");
    left.appendChild(el("div", "run-name mono", run.display_label));
    left.appendChild(
      el(
        "div",
        "run-sub mono",
        run.harness_badge + " | Final: " + fmtSigned(run.score) + " on Day " + run.final_day + " (" + run.tool_calls + " calls)"
      )
    );
    titleRow.appendChild(left);

    var badgeText = "Day " + state.day + " Active";
    var badgeCls = "badge badge-active mono";
    if (endedNow || endedBefore) {
      if (run.correct) {
        badgeText = "CAUGHT " + run.accused + " (" + fmtSigned(run.score) + ", D" + run.final_day + ")";
        badgeCls = "badge badge-caught mono";
      } else {
        badgeText = "FOOLED: Accused " + run.accused + " (" + fmtSigned(run.score) + ", D" + run.final_day + ")";
        badgeCls = "badge badge-fooled mono";
      }
    }
    titleRow.appendChild(el("span", badgeCls, badgeText));
    head.appendChild(titleRow);
    card.appendChild(head);

    var vitals = el("div", "vitals-grid");
    var cells = [
      {
        lbl: "Visible V",
        val: rec.visible_v.toFixed(2),
        note: "True V: " + rec.true_v.toFixed(2)
      },
      {
        lbl: "P(Mole " + activeCase.true_mole + ")",
        val: rec.p_mole.toFixed(2),
        note: "Exact: " + fmtPct(rec.p_mole)
      },
      {
        lbl: "Top Suspect",
        val: (rec.top_suspect || "-") + " (" + rec.p_top.toFixed(2) + ")",
        note: "Break-even: " + rec.break_even_p.toFixed(2)
      },
      {
        lbl: "Canaries",
        val: String(rec.canaries_cumulative),
        note: endedBefore ? "Closed D" + run.final_day : "+" + rec.canaries_today + " on Day " + rec.day + " (D1-3: " + run.canaries_days_1_to_3 + ")"
      },
      {
        lbl: "Interviews",
        val: String(rec.interviews_cumulative),
        note: endedBefore ? "Closed D" + run.final_day : "+" + rec.interviews_today + " on Day " + rec.day
      },
      {
        lbl: "Tool Calls",
        val: rec.calls_cumulative + " / " + run.tool_calls,
        note: endedBefore ? "Episode finished D" + run.final_day : rec.calls_today + " calls on Day " + rec.day
      }
    ];
    for (var cIdx = 0; cIdx < cells.length; cIdx += 1) {
      var vc = el("div", "vital-cell");
      vc.appendChild(el("div", "vital-lbl", cells[cIdx].lbl));
      vc.appendChild(el("div", "vital-val mono", cells[cIdx].val));
      vc.appendChild(el("div", "vital-note mono", cells[cIdx].note));
      vitals.appendChild(vc);
    }
    card.appendChild(vitals);

    var secPost = el("div", "run-sec");
    var postHdr = el("div", "sec-lbl");
    postHdr.appendChild(el("span", "", "Exact Posterior Given Agent Evidence (As of Day " + rec.day + ")"));
    postHdr.appendChild(el("span", "mono", endedBefore ? "Frozen at D" + run.final_day : "Live D" + rec.day));
    secPost.appendChild(postHdr);

    var topList = rec.top_posteriors.slice(0, 5);
    for (var pIdx = 0; pIdx < topList.length; pIdx += 1) {
      var item = topList[pIdx];
      var empObj = empLookup[item.employee];
      var tagSuffix = "";
      var fillCls = "post-bar-fill";
      if (item.employee === activeCase.true_mole) {
        tagSuffix = " [MOLE]";
        fillCls += " is-mole";
      } else if (item.employee === activeCase.fooled_accused) {
        tagSuffix = " [INNOCENT]";
        fillCls += " is-wrong";
      } else if (item.employee === activeCase.decoy) {
        tagSuffix = " [DECOY]";
      }
      var pRow = el("div", "post-row mono");
      var empLabel = item.employee + (empObj ? " " + empObj.dept.slice(0, 4) : "") + tagSuffix;
      pRow.appendChild(el("span", "", empLabel));
      var barBg = el("div", "post-bar-bg");
      var barFill = el("div", fillCls);
      barFill.style.width = Math.max(1, Math.round(item.p * 100)) + "%";
      barBg.appendChild(barFill);
      pRow.appendChild(barBg);
      pRow.appendChild(el("span", "", fmtPct(item.p)));
      secPost.appendChild(pRow);
    }
    card.appendChild(secPost);

    var secLeaks = el("div", "run-sec");
    var leaksUpToDay = [];
    for (var l = 0; l < run.leaks_surfaced.length; l += 1) {
      if (run.leaks_surfaced[l].surfaced_day <= state.day) {
        leaksUpToDay.push(run.leaks_surfaced[l]);
      }
    }
    var leakHdr = el("div", "sec-lbl");
    leakHdr.appendChild(el("span", "", "Surfaced Leaks Observed (<= Day " + Math.min(state.day, run.final_day) + ")"));
    leakHdr.appendChild(el("span", "mono", leaksUpToDay.length + " surfaced"));
    secLeaks.appendChild(leakHdr);

    var leakUl = el("ul", "leak-list mono");
    if (leaksUpToDay.length === 0) {
      leakUl.appendChild(el("li", "", "No surfaced leaks observed yet."));
    } else {
      for (var li = 0; li < leaksUpToDay.length; li += 1) {
        var lk = leaksUpToDay[li];
        var rowLi = el("li");
        if (lk.is_canary) {
          rowLi.appendChild(
            el(
              "span",
              "",
              "D" + lk.surfaced_day + " " + lk.doc_id + " -> reported " + lk.reported_variant +
                " [" + lk.reported_holders.join(", ") + "]"
            )
          );
          if (lk.is_noisy_flip) {
            rowLi.appendChild(
              el("span", "flip-badge", "5% FLIP (mole held " + lk.mole_variant + ")")
            );
          } else {
            rowLi.appendChild(el("span", "ok-tag", "TRUE HIT"));
          }
        } else {
          rowLi.appendChild(el("span", "", "D" + lk.surfaced_day + " " + lk.doc_id + " (doc): " + lk.title));
        }
        leakUl.appendChild(rowLi);
      }
    }
    secLeaks.appendChild(leakUl);
    card.appendChild(secLeaks);

    var secCan = el("div", "run-sec");
    var cansUpToDay = [];
    for (var ci = 0; ci < run.canaries_planted.length; ci += 1) {
      if (run.canaries_planted[ci].day <= state.day) {
        cansUpToDay.push(run.canaries_planted[ci]);
      }
    }
    var canHdr = el("div", "sec-lbl");
    canHdr.appendChild(el("span", "", "Canaries Planted (<= Day " + Math.min(state.day, run.final_day) + ")"));
    canHdr.appendChild(el("span", "mono", cansUpToDay.length + " total"));
    secCan.appendChild(canHdr);

    var canUl = el("ul", "canary-list mono");
    if (cansUpToDay.length === 0) {
      canUl.appendChild(el("li", "", "0 canaries planted so far."));
    } else {
      for (var cj = 0; cj < cansUpToDay.length; cj += 1) {
        var cn = cansUpToDay[cj];
        var moleNote = cn.mole_variant ? "mole " + activeCase.true_mole + "=" + cn.mole_variant : "mole excluded";
        canUl.appendChild(
          el("li", "", "D" + cn.day + " " + cn.canary_id + " (" + cn.recipients_count + " staff, " + moleNote + "): " + cn.title)
        );
      }
    }
    secCan.appendChild(canUl);
    card.appendChild(secCan);

    var secSteps = el("div", "run-sec");
    var stepHdr = el("div", "sec-lbl");
    if (endedBefore) {
      stepHdr.appendChild(el("span", "", "Episode Closed on Day " + run.final_day + " (Final Day Log)"));
      stepHdr.appendChild(el("span", "mono", rec.steps_today.length + " calls on D" + rec.day));
    } else {
      stepHdr.appendChild(el("span", "", "Day " + rec.day + " Tool Call Log"));
      stepHdr.appendChild(el("span", "mono", rec.steps_today.length + " calls"));
    }
    secSteps.appendChild(stepHdr);

    var stepUl = el("ul", "step-list mono");
    for (var si = 0; si < rec.steps_today.length; si += 1) {
      var st = rec.steps_today[si];
      stepUl.appendChild(el("li", "", "[" + st.call + "] " + st.tool + " -> " + st.summary));
    }
    secSteps.appendChild(stepUl);

    if (state.day >= run.final_day && run.rationale) {
      var ratWrap = el("div", "rationale-box");
      ratWrap.style.marginTop = "8px";
      ratWrap.appendChild(el("strong", "mono", "Final Decision Note: "));
      ratWrap.appendChild(el("span", "", run.rationale));
      secSteps.appendChild(ratWrap);
    }

    card.appendChild(secSteps);
    return card;
  }

  function buildForensicsAndRoster(activeCase, empLookup) {
    var frag = document.createDocumentFragment();

    var fSheet = el("section", "sheet");
    var fHead = el("div", "sheet-h");
    fHead.appendChild(el("span", "", "Replay-Verified Forensic Synthesis"));
    fHead.appendChild(el("span", "mono", "Deterministic Fresh-Env Audit: 0 Step Mismatches"));
    fSheet.appendChild(fHead);
    var fBody = el("div", "sheet-body");
    fBody.appendChild(el("strong", "", activeCase.forensic_summary.title));
    var ul = el("ul", "forensic-bullets");
    for (var i = 0; i < activeCase.forensic_summary.bullets.length; i += 1) {
      ul.appendChild(el("li", "", activeCase.forensic_summary.bullets[i]));
    }
    fBody.appendChild(ul);
    fSheet.appendChild(fBody);
    frag.appendChild(fSheet);

    var rSheet = el("section", "sheet");
    var rHead = el("div", "sheet-h");
    rHead.appendChild(el("span", "", "40-Employee Office Roster & Day " + state.day + " Posterior Comparison"));
    rHead.appendChild(el("span", "mono", "OpenCode P(e) vs SolverPolicy P(e) | Framed After-Hours Logs (D1-9)"));
    rSheet.appendChild(rHead);

    var rBody = el("div", "sheet-body");
    var rGrid = el("div", "roster-grid");
    var openRun = activeCase.runs[0];
    var solvRun = activeCase.runs[1];
    var openRec = getDayRecord(openRun, state.day);
    var solvRec = getDayRecord(solvRun, state.day);

    for (var eIdx = 0; eIdx < activeCase.employees.length; eIdx += 1) {
      var emp = activeCase.employees[eIdx];
      var cls = "emp-chip";
      var roleBadge = "";
      if (emp.id === activeCase.true_mole) {
        cls += " mole";
        roleBadge = " [MOLE]";
      } else if (emp.id === activeCase.fooled_accused) {
        cls += " fooled";
        roleBadge = " [FOOLED]";
      } else if (emp.id === activeCase.decoy) {
        cls += " decoy";
        roleBadge = " [DECOY]";
      }
      var chip = el("div", cls);
      var pOpen = (openRec.posteriors && openRec.posteriors[emp.id]) || 0;
      var pSolv = (solvRec.posteriors && solvRec.posteriors[emp.id]) || 0;
      var ah = activeCase.after_hours_d1_9[emp.id] || 0;
      var top = el("div", "emp-top mono");
      top.appendChild(el("span", "", emp.id + roleBadge));
      top.appendChild(el("span", "", "OC " + (pOpen * 100).toFixed(0) + "% | SP " + (pSolv * 100).toFixed(0) + "%"));
      chip.appendChild(top);
      chip.appendChild(el("div", "emp-meta", emp.name + " | " + emp.dept + " (" + emp.role + ") | AH:" + ah));
      rGrid.appendChild(chip);
    }
    rBody.appendChild(rGrid);
    rSheet.appendChild(rBody);
    frag.appendChild(rSheet);
    return frag;
  }

  function buildFooter() {
    var ft = el("footer", "foot mono");
    ft.appendChild(el("div", "", "Locked Gap Headline (" + DATA.headline.source + "): " + DATA.headline.banner_primary));
    ft.appendChild(el("div", "", DATA.headline.banner_secondary));
    return ft;
  }

  function render() {
    var root = document.getElementById("app");
    clearNode(root);
    var activeCase = DATA.cases[state.seedKey];
    var empLookup = {};
    for (var i = 0; i < activeCase.employees.length; i += 1) {
      empLookup[activeCase.employees[i].id] = activeCase.employees[i];
    }

    root.appendChild(buildHeader());
    var main = el("main", "page");
    main.appendChild(buildCaseTabs());
    main.appendChild(buildScrubberSheet(activeCase));

    var canvases = [];
    main.appendChild(buildChartsSheet(activeCase, canvases));

    var colsCls = activeCase.runs.length === 3 ? "runs-grid cols-3" : "runs-grid cols-2";
    var runsWrap = el("section", colsCls);
    for (var r = 0; r < activeCase.runs.length; r += 1) {
      runsWrap.appendChild(buildRunCard(activeCase, activeCase.runs[r], empLookup));
    }
    main.appendChild(runsWrap);
    main.appendChild(buildForensicsAndRoster(activeCase, empLookup));
    main.appendChild(buildFooter());
    root.appendChild(main);

    for (var c = 0; c < canvases.length; c += 1) {
      drawChart(canvases[c].canvas, activeCase, canvases[c].metric);
    }
  }

  window.addEventListener("keydown", function (ev) {
    if (ev.target && (ev.target.tagName === "INPUT" || ev.target.tagName === "TEXTAREA")) {
      return;
    }
    if (ev.key === "ArrowLeft") {
      ev.preventDefault();
      stopPlayback();
      setDay(state.day - 1);
    } else if (ev.key === "ArrowRight") {
      ev.preventDefault();
      stopPlayback();
      setDay(state.day + 1);
    } else if (ev.key === " ") {
      ev.preventDefault();
      togglePlayback();
    } else if (ev.key === "1") {
      selectCase("6");
    } else if (ev.key === "2") {
      selectCase("26");
    }
  });

  window.addEventListener("resize", function () {
    render();
  });

  render();
})();
</script>
</body>
</html>
"""


def encode_json_for_script(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    raw = raw.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    return raw


def render_html(payload: dict[str, Any]) -> str:
    embedded = encode_json_for_script(payload)
    html = HTML_HEAD_CSS + embedded + HTML_SCRIPT_TAIL
    encoded = html.encode("utf-8")
    if len(encoded) >= MAX_HTML_BYTES:
        raise ValueError(f"Generated HTML exceeds 2 MB limit: {len(encoded)} bytes")
    return html


def validate_html_hygiene(html: str) -> list[str]:
    errors: list[str] = []
    size_b = len(html.encode("utf-8"))
    if size_b >= MAX_HTML_BYTES:
        errors.append(f"HTML size {size_b} >= {MAX_HTML_BYTES}")
    if not all(ord(ch) < 128 for ch in html):
        errors.append("HTML contains non-ASCII characters (including em/en dashes)")
    forbidden_substrings = (
        "innerHTML",
        "outerHTML",
        "insertAdjacentHTML",
        "document.write",
        "eval(",
        "new Function",
        "http:",
        "https:",
        "fetch(",
        "XMLHttpRequest",
        "WebSocket",
        "<!--",
        "-->",
        "/*",
        "*/",
        "//",
        chr(8212),
        chr(8211),
    )
    for sub in forbidden_substrings:
        if sub in html:
            errors.append(f"Forbidden substring in HTML: {sub!r}")
    return errors


def build_demo_replay(root: Path = ROOT, out_path: Path | None = None) -> Path:
    target = out_path if out_path is not None else (root / DEFAULT_OUT_REL)
    payload = build_payload(root)
    html = render_html(payload)
    errs = validate_html_hygiene(html)
    if errs:
        raise RuntimeError("HTML hygiene check failed: " + "; ".join(errs))
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(html, encoding="utf-8")
    return target


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, default=ROOT)
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args(argv)

    root = args.root.resolve()
    target = args.out.resolve() if args.out is not None else (root / DEFAULT_OUT_REL)
    payload = build_payload(root)
    expected_html = render_html(payload)
    errs = validate_html_hygiene(expected_html)
    if errs:
        for e in errs:
            print(f"FAIL: {e}", file=sys.stderr)
        return 1

    if args.check:
        if not target.is_file():
            print(f"FAIL: missing {target}", file=sys.stderr)
            return 1
        actual_html = target.read_text(encoding="utf-8")
        if actual_html != expected_html:
            print(f"FAIL: {target} is out of date with build_demo_replay.py", file=sys.stderr)
            return 1
        print(f"OK: {target} verified ({len(expected_html.encode('utf-8'))} bytes)")
        return 0

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(expected_html, encoding="utf-8")
    print(f"Wrote {target} ({len(expected_html.encode('utf-8'))} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
