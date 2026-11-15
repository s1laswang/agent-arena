from __future__ import annotations

import argparse
import base64
import json
import math
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from canary import rules
from canary.env import Env
from canary.rules import DEV_SEEDS, HELDOUT_SEEDS, JUDGE_SEEDS, TIERS_VERSION

COMMITTED_V14_ROOT = ROOT / "data" / "runs" / "committed" / "v1.4"
DEFAULT_OUT_PATH = ROOT / "docs" / "arena" / "data" / "committed_duel_pack.js"
FALLBACK_NODE_BIN = Path("/home/silas/tools/node/bin/node")

HARD_SEEDS: tuple[int, ...] = (6, 26, 4, 18, 15, 11, 5, 23)
MEDIUM_SEEDS: tuple[int, ...] = (0, 12)
DEFAULT_SEEDS: tuple[int, ...] = HARD_SEEDS
FEATURED_SEEDS: tuple[int, ...] = (6, 26)
SEALED_MARKER = "[SEALED]"
SEALED_ACCUSE_SUMMARY = "Accusation filed [SEALED]"
SEALED_PREFIX = "sealed:"

GEMINI_RAW_AGENT = "opencode:google/gemini-4-carbon"
GEMINI_LABEL = "gemini-4-carbon (OpenCode MCP)"
SOLVER_RAW_AGENT = "solver"
SOLVER_LABEL = "Reference Bayesian Solver"

RUN_PATHS: dict[tuple[str, str], tuple[str, ...]] = {
    ("hard", "gemini"): ("opencode-gemini-4-carbon/hard/episodes.jsonl",),
    ("medium", "gemini"): ("opencode-gemini-4-carbon/medium/episodes.jsonl",),
    ("hard", "solver"): (
        "reference/solver-hard-20261114-121126/episodes.jsonl",
        "reference/solver-hard-seeds20to29/episodes.jsonl",
    ),
    ("medium", "solver"): (
        "reference/solver-medium-20261114-121126/episodes.jsonl",
        "reference/solver-medium-seeds20to29/episodes.jsonl",
    ),
}

TOOL_GROUPS: dict[str, str] = {
    "status": "Clock",
    "advance_day": "Clock",
    "list_employees": "Investigate",
    "list_documents": "Investigate",
    "read_access_logs": "Investigate",
    "search_messages": "Investigate",
    "read_message": "Investigate",
    "interview": "Investigate",
    "plant_canary": "Trap",
    "check_leak_feed": "Trap",
    "restrict_access": "Contain",
    "unrestrict_access": "Contain",
    "accuse": "Decide",
}

TOOL_LOCATIONS: dict[str, str] = {
    "status": "security_desk",
    "advance_day": "security_desk",
    "list_employees": "records_room",
    "list_documents": "records_room",
    "read_access_logs": "server_room",
    "search_messages": "comms_terminal",
    "read_message": "comms_terminal",
    "interview": "meeting_room",
    "plant_canary": "canary_printer",
    "check_leak_feed": "leak_wire",
    "restrict_access": "access_control",
    "unrestrict_access": "access_control",
    "accuse": "war_room",
}

FORBIDDEN_PRE_END_KEYS: frozenset[str] = frozenset(
    {
        "mole",
        "true_mole",
        "trueMole",
        "mole_id",
        "moleId",
        "decoy",
        "true_decoy",
        "trueDecoy",
        "decoy_id",
        "decoyId",
        "correct",
        "accused_correct",
        "accusedCorrect",
        "world_seed",
        "_world",
        "true_v",
        "true_V",
        "trueV",
        "score",
        "accused",
        "is_mole",
        "is_canary",
        "leaking_sprite_employee",
        "mole_sprite",
        "culprit_sprite",
        "leaker_employee",
    }
)

HASH_TOK = chr(35)
SLASH_SLASH_TOK = "/" + "/"
SLASH_STAR_TOK = "/" + "*"
STAR_SLASH_TOK = "*" + "/"
EM_DASH_TOK = chr(0x2014)
EN_DASH_TOK = chr(0x2013)
UNICODE_MINUS_TOK = chr(0x2212)
EMP_ID_RE = re.compile(r"^e\d{2,3}$")

CREDENTIAL_CHECKS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?<![0-9A-Za-z+/_-])" + re.escape("AI" + "za") + r"[0-9A-Za-z_-]{20,}"),
    re.compile(
        r"(?<![0-9A-Za-z+/_-])"
        + re.escape("s" + "k-")
        + r"(?:proj-|ant-|live-|test-|svcacct-)?[0-9A-Za-z_-]{16,}"
    ),
    re.compile(re.escape("ya" + "29.") + r"[0-9A-Za-z_-]{20,}"),
    re.compile(re.escape("h" + "f_") + r"[A-Za-z0-9]{24,}"),
    re.compile(re.escape("xa" + "i-") + r"[A-Za-z0-9_-]{24,}"),
    re.compile(r"gh[pousr]_[A-Za-z0-9]{24,}"),
)


def _find_node_bin() -> str | None:
    which_node = shutil.which("node")
    if which_node:
        return which_node
    if FALLBACK_NODE_BIN.is_file() and os.access(FALLBACK_NODE_BIN, os.X_OK):
        return str(FALLBACK_NODE_BIN)
    return None


def _sanitize_ascii_text(val: Any, max_len: int = 96) -> str:
    s = str(val if val is not None else "")
    s = s.replace(EM_DASH_TOK, "-").replace(EN_DASH_TOK, "-").replace(UNICODE_MINUS_TOK, "-")
    s = s.replace(SLASH_SLASH_TOK, "/").replace(SLASH_STAR_TOK, "/").replace(STAR_SLASH_TOK, "/")
    s = s.replace(HASH_TOK, "no.")
    s = " ".join(s.split())
    out_chars = [ch if 32 <= ord(ch) < 127 else "?" for ch in s]
    cleaned = "".join(out_chars).strip()
    if len(cleaned) > max_len:
        return cleaned[: max_len - 3].rstrip() + "..."
    return cleaned


def _clean_public_args(raw_args: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in raw_args.items():
        ks = str(k)
        if ks in FORBIDDEN_PRE_END_KEYS:
            continue
        if isinstance(v, dict):
            out[ks] = {str(sk): sv for sk, sv in v.items() if str(sk) not in FORBIDDEN_PRE_END_KEYS}
        elif isinstance(v, list):
            out[ks] = list(v)
        else:
            out[ks] = v
    return out


def _summarize_public_step(
    tool: str,
    args: dict[str, Any],
    ok: bool,
    data: dict[str, Any],
    error: str | None,
    known_v: float,
) -> str:
    if tool == "accuse":
        return SEALED_ACCUSE_SUMMARY
    if not ok:
        err_label = _sanitize_ascii_text(error or "failed", 64)
        return _sanitize_ascii_text(f"{tool} -> error: {err_label}", 110)
    if tool == "status":
        d = data.get("day", "?")
        acts = data.get("actions_left_today", "?")
        cans = len(data.get("canaries_planted") or [])
        return f"status -> day {d}, V={known_v:.2f}, {acts} actions left, {cans} canaries"
    if tool == "list_employees":
        n_emp = len(data.get("employees") or [])
        return f"list_employees -> {n_emp} staff listed"
    if tool == "list_documents":
        d_from = args.get("day_from", 1)
        d_to = args.get("day_to", "now")
        n_docs = len(data.get("documents") or [])
        return f"list_documents({d_from}..{d_to}) -> {n_docs} docs"
    if tool == "read_access_logs":
        d_from = args.get("day_from", 1)
        d_to = args.get("day_to", d_from)
        emp = args.get("employee")
        logs = data.get("logs") or []
        ah = sum(1 for r in logs if isinstance(r, dict) and r.get("after_hours"))
        scope = f"{emp}, {d_from}..{d_to}" if emp else f"{d_from}..{d_to}"
        return f"read_access_logs({scope}) -> {len(logs)} opens ({ah} after-hours)"
    if tool == "search_messages":
        q = _sanitize_ascii_text(args.get("query", ""), 28)
        hits = len(data.get("messages") or [])
        return f"search_messages('{q}') -> {hits} hits"
    if tool == "read_message":
        mid = _sanitize_ascii_text(args.get("id", args.get("message_id", "")), 20)
        msg = data.get("message") or {}
        sender = _sanitize_ascii_text(msg.get("sender", "?"), 12)
        subj = _sanitize_ascii_text(msg.get("subject", ""), 36)
        return f"read_message({mid}) -> from {sender}: {subj}"
    if tool == "interview":
        emp = _sanitize_ascii_text(args.get("employee", "?"), 8)
        topic = _sanitize_ascii_text(args.get("topic", "?"), 24)
        return f"interview({emp}, {topic}) -> response logged"
    if tool == "plant_canary":
        cid = _sanitize_ascii_text(data.get("canary_id", "canary"), 12)
        asg = args.get("assignment") if isinstance(args.get("assignment"), dict) else {}
        n_recips = len(asg)
        n_vars = len(set(asg.values()))
        return f"plant_canary({cid}: {n_recips} staff, {n_vars} variants) -> V={known_v:.2f}"
    if tool == "check_leak_feed":
        items = data.get("items") or []
        canary_tags = [
            f"{it.get('doc_id')}:{it.get('variant')}"
            for it in items
            if isinstance(it, dict) and it.get("variant")
        ]
        if canary_tags:
            joined = ", ".join(_sanitize_ascii_text(t, 16) for t in canary_tags[:4])
            return f"check_leak_feed -> {len(items)} leaks ({joined})"
        return f"check_leak_feed -> {len(items)} surfaced leaks"
    if tool == "restrict_access":
        emp = _sanitize_ascii_text(args.get("employee", "?"), 8)
        return f"restrict_access({emp}) -> restricted"
    if tool == "unrestrict_access":
        emp = _sanitize_ascii_text(args.get("employee", "?"), 8)
        return f"unrestrict_access({emp}) -> unrestricted"
    if tool == "advance_day":
        if data.get("episode_over"):
            cd = data.get("closed_day", "?")
            return f"advance_day -> closed day {cd} (horizon)"
        nd = data.get("day", "?")
        n_new = len(data.get("new_documents") or [])
        return f"advance_day -> day {nd}, V={known_v:.2f}, {n_new} new docs"
    return _sanitize_ascii_text(f"{tool} -> ok", 80)


def seal_reveal_payload(payload: dict[str, Any]) -> str:
    raw_json = json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
    encoded = base64.b64encode(raw_json.encode("ascii")).decode("ascii")
    return SEALED_PREFIX + encoded


def unseal_reveal_token(token_or_ep: str | dict[str, Any]) -> dict[str, Any]:
    token = token_or_ep["sealed_reveal_b64"] if isinstance(token_or_ep, dict) else token_or_ep
    if not isinstance(token, str) or not token.startswith(SEALED_PREFIX):
        raise ValueError("invalid sealed_reveal_b64 token")
    b64 = token[len(SEALED_PREFIX) :]
    decoded = base64.b64decode(b64.encode("ascii")).decode("utf-8")
    obj = json.loads(decoded)
    if not isinstance(obj, dict):
        raise ValueError("unsealed payload is not an object")
    return obj


def _load_committed_seed_map(
    committed_root: Path,
    rel_paths: tuple[str, ...],
) -> dict[int, tuple[str, dict[str, Any]]]:
    out: dict[int, tuple[str, dict[str, Any]]] = {}
    for rel in rel_paths:
        fp = committed_root / rel
        if not fp.is_file():
            raise FileNotFoundError(f"missing committed episodes file: {fp}")
        for lineno, line in enumerate(fp.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            row = json.loads(line)
            if (row.get("meta") or {}).get("valid") is False:
                continue
            seed = int(row["seed"])
            if seed in out:
                raise ValueError(f"duplicate seed {seed} at {rel}:{lineno}")
            out[seed] = (f"data/runs/committed/v1.4/{rel}", row)
    return out


def _validate_dev_seed(seed: int) -> None:
    if seed in JUDGE_SEEDS or seed in HELDOUT_SEEDS or seed not in DEV_SEEDS:
        raise ValueError(f"seed {seed} is not an allowed public/dev seed")


def _build_world_meta(tier: str, seed: int) -> dict[str, Any]:
    _validate_dev_seed(seed)
    env = Env(tier, seed)
    p = env.p
    emp_res = env._t_list_employees({})
    roster = [dict(item) for item in emp_res.data["employees"]]
    return {
        "tier": tier,
        "seed": seed,
        "n_employees": p.n_employees,
        "n_days": p.n_days,
        "actions_per_day": p.actions_per_day,
        "canaries_per_day": p.canaries_per_day,
        "max_variants": p.max_variants,
        "tool_call_cap": p.tool_call_cap,
        "leak_damage": p.leak_damage,
        "canary_cost": p.canary_cost,
        "restrict_cost_per_day": p.restrict_cost_per_day,
        "wrong_accusation_score": p.wrong_accusation_score,
        "roster": roster,
    }


def _replay_single_episode(
    tier: str,
    seed: int,
    agent_id: str,
    agent_raw: str,
    agent_label: str,
    source_path: str,
    raw_ep: dict[str, Any],
    roster_by_id: dict[str, dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any]]:
    _validate_dev_seed(seed)
    if TIERS_VERSION != "v1.4" or not rules.KNOWN_V_MODE:
        raise RuntimeError(
            f"expected frozen v1.4 KNOWN_V_MODE=True, got {TIERS_VERSION} / {rules.KNOWN_V_MODE}"
        )

    env = Env(tier, seed)
    raw_steps = raw_ep.get("steps")
    if not isinstance(raw_steps, list) or not raw_steps:
        raise ValueError(f"{tier}:{seed}:{agent_id} has empty steps")

    pre_end_steps: list[dict[str, Any]] = []
    accuse_call_idx: int | None = None
    unsealed_accuse_step: dict[str, Any] | None = None

    for idx, st in enumerate(raw_steps):
        if env.done:
            raise ValueError(f"{tier}:{seed}:{agent_id} step {idx} occurs after env.done")
        step_day = int(st["day"])
        if step_day != env.day:
            raise ValueError(f"{tier}:{seed}:{agent_id} step {idx} day mismatch: {step_day} != {env.day}")
        if int(st.get("t", idx)) != idx:
            raise ValueError(f"{tier}:{seed}:{agent_id} step {idx} t mismatch: {st.get('t')}")

        tool = str(st["tool"])
        raw_args = st.get("args")
        call_args = dict(raw_args) if isinstance(raw_args, dict) else {}
        live_res = env.call(tool, call_args)

        rec_res = st.get("result") if isinstance(st.get("result"), dict) else {}
        if "ok" in rec_res and bool(rec_res["ok"]) != bool(live_res.ok):
            raise ValueError(
                f"{tier}:{seed}:{agent_id} step {idx} ({tool}) ok mismatch: recorded={rec_res.get('ok')} live={live_res.ok}"
            )

        known_v = float(env.visible_V())
        if tool in ("status", "advance_day") and live_res.ok and "V" in live_res.data:
            if abs(float(live_res.data["V"]) - known_v) > 1e-9:
                raise ValueError(f"{tier}:{seed}:{agent_id} step {idx} visible_V mismatch")

        group = TOOL_GROUPS.get(tool, "Investigate")
        location = TOOL_LOCATIONS.get(tool, "security_desk")

        if tool == "accuse":
            if live_res.ok:
                real_emp = str(call_args["employee"])
                accuse_call_idx = idx
                unsealed_accuse_step = {
                    "day": step_day,
                    "call_idx": idx,
                    "t": idx,
                    "tool": "accuse",
                    "tool_group": group,
                    "location": location,
                    "target_employee": real_emp,
                    "args": {"employee": real_emp},
                    "ok": True,
                    "summary": f"accuse({real_emp})",
                    "V": known_v,
                    "known_v": known_v,
                    "sealed": False,
                }
            pre_end_steps.append(
                {
                    "day": step_day,
                    "call_idx": idx,
                    "t": idx,
                    "tool": "accuse",
                    "tool_group": group,
                    "location": location,
                    "target_employee": SEALED_MARKER,
                    "args": {"employee": SEALED_MARKER},
                    "ok": bool(live_res.ok),
                    "summary": SEALED_ACCUSE_SUMMARY,
                    "V": known_v,
                    "known_v": known_v,
                    "sealed": True,
                }
            )
        else:
            clean_args = _clean_public_args(call_args)
            raw_emp = clean_args.get("employee")
            tgt_emp = str(raw_emp) if isinstance(raw_emp, str) else None
            summary = _summarize_public_step(
                tool=tool,
                args=clean_args,
                ok=bool(live_res.ok),
                data=live_res.data if isinstance(live_res.data, dict) else {},
                error=live_res.error,
                known_v=known_v,
            )
            pre_end_steps.append(
                {
                    "day": step_day,
                    "call_idx": idx,
                    "t": idx,
                    "tool": tool,
                    "tool_group": group,
                    "location": location,
                    "target_employee": tgt_emp,
                    "args": clean_args,
                    "ok": bool(live_res.ok),
                    "summary": summary,
                    "V": known_v,
                    "known_v": known_v,
                    "sealed": False,
                }
            )

    verdict = env.verdict()
    rec_score = float(raw_ep["score"])
    if abs(float(verdict["score"]) - rec_score) > 1e-9:
        raise ValueError(
            f"{tier}:{seed}:{agent_id} score mismatch: recorded={rec_score} replayed={verdict['score']}"
        )
    if verdict["accused"] != raw_ep.get("accused"):
        raise ValueError(
            f"{tier}:{seed}:{agent_id} accused mismatch: recorded={raw_ep.get('accused')} replayed={verdict['accused']}"
        )
    if bool(verdict["correct"]) != bool(raw_ep.get("correct")):
        raise ValueError(f"{tier}:{seed}:{agent_id} correct mismatch")
    if int(verdict["final_day"]) != int(raw_ep["final_day"]):
        raise ValueError(f"{tier}:{seed}:{agent_id} final_day mismatch")

    true_mole = str(env._world.mole)
    true_decoy = env._world.decoy
    mole_meta = roster_by_id.get(true_mole) or {}
    mole_name = str(mole_meta.get("name") or "")
    mole_dept = str(mole_meta.get("department") or "")

    score_val = float(verdict["score"])
    accused_val = verdict["accused"]
    acc_meta = roster_by_id.get(str(accused_val)) if accused_val else None
    accused_name = str(acc_meta.get("name") or "") if isinstance(acc_meta, dict) else None
    accused_dept = str(acc_meta.get("department") or "") if isinstance(acc_meta, dict) else None

    correct_val = bool(verdict["correct"])
    final_day_val = int(verdict["final_day"])
    end_reason_val = str(verdict["end_reason"])
    total_calls = len(pre_end_steps)
    true_v_final = round(float(env.V), 10)
    known_v_final = float(env.visible_V())

    reveal_obj: dict[str, Any] = {
        "seed": seed,
        "tier": tier,
        "agent": agent_id,
        "agent_raw": agent_raw,
        "mole": true_mole,
        "true_mole": true_mole,
        "mole_name": mole_name,
        "mole_dept": mole_dept,
        "decoy": true_decoy,
        "accused": accused_val,
        "accused_name": accused_name,
        "accused_dept": accused_dept,
        "correct": correct_val,
        "score": score_val,
        "true_V": true_v_final,
        "known_V_final": known_v_final,
        "final_day": final_day_val,
        "end_reason": end_reason_val,
        "tool_calls": total_calls,
        "accuse_call_idx": accuse_call_idx,
        "accuse_args": {"employee": accused_val} if accused_val else None,
        "accuse_summary": f"accuse({accused_val})" if accused_val else None,
        "unsealed_accuse_step": unsealed_accuse_step,
        "final": {
            "sealed": False,
            "done": True,
            "score": score_val,
            "correct": correct_val,
            "accused": accused_val,
            "accused_name": accused_name,
            "accused_dept": accused_dept,
            "mole": true_mole,
            "mole_name": mole_name,
            "mole_dept": mole_dept,
            "final_day": final_day_val,
            "end_reason": end_reason_val,
            "tool_calls": total_calls,
        },
    }

    episode_public: dict[str, Any] = {
        "key": f"{tier}:{seed}:{agent_id}",
        "world_key": f"{tier}:{seed}",
        "seed": seed,
        "tier": tier,
        "agent": agent_raw,
        "agent_id": agent_id,
        "agent_label": agent_label,
        "source_path": source_path,
        "n_days": env.p.n_days,
        "final_day": final_day_val,
        "total_calls": total_calls,
        "has_accuse": accuse_call_idx is not None,
        "steps": pre_end_steps,
    }
    return episode_public, reveal_obj


def _assert_zero_pre_end_leaks(node: Any, loc: str = "root") -> None:
    if isinstance(node, list):
        for idx, item in enumerate(node):
            _assert_zero_pre_end_leaks(item, f"{loc}[{idx}]")
        return
    if not isinstance(node, dict):
        return

    for k in node:
        ks = str(k)
        if ks in FORBIDDEN_PRE_END_KEYS:
            raise AssertionError(f"forbidden pre-end key {ks!r} at {loc}")

    if node.get("tool") == "accuse":
        args_val = node.get("args")
        if not isinstance(args_val, dict) or args_val.get("employee") != SEALED_MARKER:
            raise AssertionError(f"unsealed accuse args at {loc}: {args_val!r}")
        summary_val = str(node.get("summary") or "")
        if SEALED_MARKER not in summary_val:
            raise AssertionError(f"unsealed accuse summary at {loc}: {summary_val!r}")
        for tok in summary_val.replace("(", " ").replace(")", " ").split():
            if EMP_ID_RE.match(tok):
                raise AssertionError(f"accuse summary leaks employee id at {loc}: {summary_val!r}")
        tgt_val = node.get("target_employee")
        if isinstance(tgt_emp := tgt_val, str) and EMP_ID_RE.match(tgt_emp):
            raise AssertionError(f"unsealed accuse target_employee at {loc}: {tgt_emp!r}")
        if node.get("sealed") is not True:
            raise AssertionError(f"accuse step missing sealed=True at {loc}")

    for k, v in node.items():
        _assert_zero_pre_end_leaks(v, f"{loc}.{k}")


def build_duel_pack_dict(committed_root: Path = COMMITTED_V14_ROOT) -> dict[str, Any]:
    os.environ.setdefault("CANARY_ALLOW_DEV", "1")
    gem_hard = _load_committed_seed_map(committed_root, RUN_PATHS[("hard", "gemini")])
    sol_hard = _load_committed_seed_map(committed_root, RUN_PATHS[("hard", "solver")])
    gem_med = _load_committed_seed_map(committed_root, RUN_PATHS[("medium", "gemini")])
    sol_med = _load_committed_seed_map(committed_root, RUN_PATHS[("medium", "solver")])

    worlds: dict[str, dict[str, Any]] = {}
    episodes: dict[str, dict[str, Any]] = {}

    tier_plan: tuple[tuple[str, tuple[int, ...], dict[int, Any], dict[int, Any]], ...] = (
        ("hard", HARD_SEEDS, gem_hard, sol_hard),
        ("medium", MEDIUM_SEEDS, gem_med, sol_med),
    )

    for tier, seeds, gem_map, sol_map in tier_plan:
        for seed in seeds:
            if seed not in gem_map:
                raise KeyError(f"missing gemini episode for {tier}:{seed}")
            if seed not in sol_map:
                raise KeyError(f"missing solver episode for {tier}:{seed}")

            world_key = f"{tier}:{seed}"
            world_meta = _build_world_meta(tier, seed)
            worlds[world_key] = world_meta
            roster_by_id = {str(emp["id"]): emp for emp in world_meta["roster"]}

            gem_src, gem_raw = gem_map[seed]
            sol_src, sol_raw = sol_map[seed]

            gem_pub, gem_rev = _replay_single_episode(
                tier=tier,
                seed=seed,
                agent_id="gemini",
                agent_raw=str(gem_raw.get("agent") or GEMINI_RAW_AGENT),
                agent_label=GEMINI_LABEL,
                source_path=gem_src,
                raw_ep=gem_raw,
                roster_by_id=roster_by_id,
            )
            sol_pub, sol_rev = _replay_single_episode(
                tier=tier,
                seed=seed,
                agent_id="solver",
                agent_raw=str(sol_raw.get("agent") or SOLVER_RAW_AGENT),
                agent_label=SOLVER_LABEL,
                source_path=sol_src,
                raw_ep=sol_raw,
                roster_by_id=roster_by_id,
            )

            if gem_rev["mole"] != sol_rev["mole"]:
                raise AssertionError(f"mole mismatch on {world_key}")

            sol_summary_for_duel = {
                "score": sol_rev["score"],
                "accused": sol_rev["accused"],
                "accused_name": sol_rev["accused_name"],
                "accused_dept": sol_rev["accused_dept"],
                "mole": sol_rev["mole"],
                "mole_name": sol_rev["mole_name"],
                "mole_dept": sol_rev["mole_dept"],
                "correct": sol_rev["correct"],
                "true_V": sol_rev["true_V"],
                "known_V_final": sol_rev["known_V_final"],
                "final_day": sol_rev["final_day"],
                "end_reason": sol_rev["end_reason"],
                "tool_calls": sol_rev["tool_calls"],
                "accuse_call_idx": sol_rev["accuse_call_idx"],
                "unsealed_accuse_step": sol_rev["unsealed_accuse_step"],
            }
            gem_rev_with_solver = dict(gem_rev)
            gem_rev_with_solver["solver"] = sol_summary_for_duel
            gem_rev_with_solver["final"] = dict(gem_rev["final"], solver=sol_summary_for_duel)

            sol_sealed = seal_reveal_payload(sol_rev)
            gem_sealed = seal_reveal_payload(gem_rev_with_solver)

            gem_entry = dict(gem_pub)
            gem_entry["solver_agent"] = sol_pub["agent"]
            gem_entry["solver_label"] = SOLVER_LABEL
            gem_entry["solver_source_path"] = sol_pub["source_path"]
            gem_entry["solver_final_day"] = sol_pub["final_day"]
            gem_entry["solver_total_calls"] = sol_pub["total_calls"]
            gem_entry["solver_has_accuse"] = sol_pub["has_accuse"]
            gem_entry["sealed_reveal_b64"] = gem_sealed
            gem_entry["solver_sealed_reveal_b64"] = sol_sealed

            sol_entry = dict(sol_pub)
            sol_entry["sealed_reveal_b64"] = sol_sealed

            episodes[f"{world_key}:gemini"] = gem_entry
            episodes[f"{world_key}:solver"] = sol_entry

    pack: dict[str, Any] = {
        "schema_version": "canary_duel_pack.v1",
        "version": "v1.4",
        "tiers_version": "v1.4",
        "known_v_mode": True,
        "default_tier": "hard",
        "default_seed": 6,
        "default_seeds": list(DEFAULT_SEEDS),
        "featured_seeds": list(FEATURED_SEEDS),
        "seeds": {
            "hard": list(HARD_SEEDS),
            "medium": list(MEDIUM_SEEDS),
        },
        "seeds_by_tier": {
            "hard": list(HARD_SEEDS),
            "medium": list(MEDIUM_SEEDS),
        },
        "agents": ["gemini", "solver"],
        "agent_meta": {
            "gemini": {
                "id": "gemini",
                "raw_agent": GEMINI_RAW_AGENT,
                "label": GEMINI_LABEL,
            },
            "solver": {
                "id": "solver",
                "raw_agent": SOLVER_RAW_AGENT,
                "label": SOLVER_LABEL,
            },
        },
        "worlds": worlds,
        "episodes": episodes,
    }
    _assert_zero_pre_end_leaks(pack)
    return pack


JS_RUNTIME_FOOTER = """
(function (root) {
  var pack = root.CANARY_DUEL_PACK;
  if (!pack || !pack.episodes) return;

  function decodeBase64Ascii(b64) {
    if (typeof atob === "function") {
      return atob(b64);
    }
    if (typeof Buffer !== "undefined") {
      return Buffer.from(b64, "base64").toString("utf8");
    }
    throw new Error("No base64 decoder available");
  }

  function unsealReveal(epOrToken) {
    var tok = typeof epOrToken === "string" ? epOrToken : (epOrToken && epOrToken.sealed_reveal_b64);
    if (typeof tok !== "string" || tok.indexOf("sealed:") !== 0) {
      throw new Error("Invalid sealed reveal token");
    }
    return JSON.parse(decodeBase64Ascii(tok.slice(7)));
  }

  function cloneStep(s) {
    var copyArgs = {};
    if (s.args && typeof s.args === "object") {
      var keys = Object.keys(s.args);
      for (var i = 0; i < keys.length; i++) {
        var k = keys[i];
        var v = s.args[k];
        copyArgs[k] = (v && typeof v === "object" && !Array.isArray(v)) ? Object.assign({}, v) : v;
      }
    }
    return {
      day: s.day,
      call_idx: s.call_idx,
      t: s.t,
      tool: s.tool,
      tool_group: s.tool_group,
      location: s.location,
      target_employee: s.target_employee,
      args: copyArgs,
      ok: s.ok,
      summary: s.summary,
      V: s.V,
      known_v: s.known_v !== undefined ? s.known_v : s.V,
      sealed: Boolean(s.sealed)
    };
  }

  function normalizeAgent(agent) {
    if (!agent) return "gemini";
    var a = String(agent).toLowerCase();
    if (a === "solver" || a === "reference" || a.indexOf("solver") >= 0) return "solver";
    return "gemini";
  }

  var byAgent = {};
  var byWorld = {};
  var worldKeys = Object.keys(pack.worlds || {});
  for (var i = 0; i < worldKeys.length; i++) {
    var wk = worldKeys[i];
    var gemEp = pack.episodes[wk + ":gemini"];
    var solEp = pack.episodes[wk + ":solver"];
    if (!gemEp || !solEp) continue;

    Object.defineProperty(gemEp, "paired_solver", {
      value: solEp,
      enumerable: false,
      configurable: true
    });
    Object.defineProperty(gemEp, "solver_steps", {
      value: solEp.steps,
      enumerable: false,
      configurable: true
    });

    byAgent[wk + ":gemini"] = gemEp;
    byAgent[wk + ":solver"] = solEp;
    byWorld[wk] = {
      gemini: gemEp,
      solver: solEp,
      world: pack.worlds[wk]
    };

    var aliases = [
      [wk, gemEp],
      [wk + ":opencode-gemini-4-carbon", gemEp],
      [wk + ":" + gemEp.agent, gemEp],
      [wk + ":reference", solEp]
    ];
    if (gemEp.tier === "hard") {
      aliases.push([String(gemEp.seed), gemEp]);
    }
    for (var j = 0; j < aliases.length; j++) {
      var aliasKey = aliases[j][0];
      if (!Object.prototype.hasOwnProperty.call(pack.episodes, aliasKey)) {
        Object.defineProperty(pack.episodes, aliasKey, {
          value: aliases[j][1],
          enumerable: false,
          configurable: true
        });
      }
    }
  }

  function listSeeds(tier) {
    var t = String(tier || pack.default_tier || "hard");
    var arr = pack.seeds && pack.seeds[t];
    return Array.isArray(arr) ? arr.slice() : [];
  }

  function getEpisode(tier, seed, agent) {
    var wk = String(tier || "hard") + ":" + String(seed);
    var agentKey = normalizeAgent(agent);
    return pack.episodes[wk + ":" + agentKey] || null;
  }

  function getPreEndEpisode(tier, seed, humanDay, agent) {
    var wk = String(tier || "hard") + ":" + String(seed);
    var gemEp = pack.episodes[wk + ":gemini"];
    var solEp = pack.episodes[wk + ":solver"];
    if (!gemEp || !solEp) return null;
    var actualDay = humanDay;
    var actualAgent = agent;
    if (typeof humanDay === "string" && agent === undefined) {
      actualDay = undefined;
      actualAgent = humanDay;
    }
    var useSolver = Boolean(actualAgent && normalizeAgent(actualAgent) === "solver");
    var src = useSolver ? solEp : gemEp;
    var hasDayCap = typeof actualDay === "number" && isFinite(actualDay);
    var maxDay = hasDayCap ? actualDay : src.n_days;
    var filtered = [];
    for (var idx = 0; idx < src.steps.length; idx++) {
      if (src.steps[idx].day <= maxDay) {
        filtered.push(cloneStep(src.steps[idx]));
      }
    }
    var solFiltered = [];
    for (var sIdx = 0; sIdx < solEp.steps.length; sIdx++) {
      if (solEp.steps[sIdx].day <= maxDay) {
        solFiltered.push(cloneStep(solEp.steps[sIdx]));
      }
    }
    var finishedByDay = src.final_day <= maxDay;
    var status = "in_progress";
    var sealedDay = null;
    if (finishedByDay && src.has_accuse) {
      status = "sealed_accusation";
      sealedDay = src.final_day;
    } else if (finishedByDay) {
      status = "horizon_ended";
    }
    return {
      seed: src.seed,
      tier: src.tier,
      agent: useSolver ? "solver" : src.agent,
      agent_id: useSolver ? "solver" : "gemini",
      n_days: src.n_days,
      steps: filtered,
      solver_steps: solFiltered,
      status: status,
      sealed_day: sealedDay,
      final: finishedByDay ? { sealed: true, final_day: src.final_day } : null
    };
  }

  function unlockPostGameReveal(tier, seed, humanDone, agent) {
    var actualTier = tier;
    var actualSeed = seed;
    var actualDone = humanDone;
    var actualAgent = agent;
    if (typeof tier === "number" && typeof seed === "boolean") {
      actualTier = pack.default_tier || "hard";
      actualSeed = tier;
      actualDone = seed;
      actualAgent = humanDone;
    }
    if (actualDone !== true) {
      return null;
    }
    var wk = String(actualTier || "hard") + ":" + String(actualSeed);
    var agentKey = actualAgent ? normalizeAgent(actualAgent) : "gemini";
    var target = pack.episodes[wk + ":" + agentKey];
    if (!target) return null;
    return unsealReveal(target.sealed_reveal_b64);
  }

  function getUnlockedEpisode(tier, seed, humanDone, agent) {
    if (humanDone !== true) return null;
    var agentKey = agent ? normalizeAgent(agent) : "gemini";
    var ep = getEpisode(tier, seed, agentKey);
    var rev = unlockPostGameReveal(tier, seed, true, agentKey);
    if (!ep || !rev) return null;
    var unlockedSteps = [];
    for (var i = 0; i < ep.steps.length; i++) {
      var st = cloneStep(ep.steps[i]);
      if (st.tool === "accuse" && rev.unsealed_accuse_step && st.call_idx === rev.accuse_call_idx) {
        st = cloneStep(rev.unsealed_accuse_step);
      }
      unlockedSteps.push(st);
    }
    return {
      seed: ep.seed,
      tier: ep.tier,
      agent: ep.agent,
      agent_id: ep.agent_id,
      n_days: ep.n_days,
      steps: unlockedSteps,
      final: rev.final || rev
    };
  }

  var helpers = {
    by_agent: byAgent,
    by_world: byWorld,
    listSeeds: listSeeds,
    unsealReveal: unsealReveal,
    getEpisode: getEpisode,
    getPreEndEpisode: getPreEndEpisode,
    unlockPostGameReveal: unlockPostGameReveal,
    getUnlockedEpisode: getUnlockedEpisode
  };
  var hKeys = Object.keys(helpers);
  for (var h = 0; h < hKeys.length; h++) {
    Object.defineProperty(pack, hKeys[h], {
      value: helpers[hKeys[h]],
      enumerable: false,
      configurable: true
    });
  }
})(typeof window !== "undefined" ? window : globalThis);
if (typeof globalThis !== "undefined") {
  var resolvedPack = (typeof window !== "undefined" && window.CANARY_DUEL_PACK) || globalThis.CANARY_DUEL_PACK;
  globalThis.CANARY_DUEL_PACK = resolvedPack;
  if (!globalThis.CANARY_GEMINI_REPLAYS) {
    globalThis.CANARY_GEMINI_REPLAYS = resolvedPack;
  }
}
if (typeof module !== "undefined" && module.exports) {
  module.exports = (typeof window !== "undefined" ? window : globalThis).CANARY_DUEL_PACK;
}
""".strip()


def _format_pack_json(pack: dict[str, Any]) -> str:
    top_items: list[str] = []
    for k, v in pack.items():
        k_js = json.dumps(k, ensure_ascii=True)
        if k in ("worlds", "episodes") and isinstance(v, dict):
            sub_lines = [
                "    " + json.dumps(sk, ensure_ascii=True) + ": " + json.dumps(sv, ensure_ascii=True, separators=(",", ":"))
                for sk, sv in v.items()
            ]
            body = "{\n" + ",\n".join(sub_lines) + "\n  }"
            top_items.append(f"  {k_js}: {body}")
        else:
            top_items.append(f"  {k_js}: {json.dumps(v, ensure_ascii=True, separators=(',', ':'))}")
    return "{\n" + ",\n".join(top_items) + "\n}"


def render_duel_pack_js(pack: dict[str, Any]) -> str:
    json_payload = _format_pack_json(pack)
    lines = [
        'if (typeof window === "undefined") { globalThis.window = globalThis; }',
        "window.CANARY_DUEL_PACK = " + json_payload + ";",
        JS_RUNTIME_FOOTER,
        "",
    ]
    js_text = "\n".join(lines)
    _assert_hygiene(js_text, "committed_duel_pack.js")
    return js_text


FORBIDDEN_DOM_SINKS: tuple[str, ...] = (
    "inner" + "HTML",
    "outer" + "HTML",
    "insertAdjacent" + "HTML",
    "document." + "write",
)


def _assert_hygiene(text: str, label: str) -> None:
    if any(ord(ch) >= 128 for ch in text):
        raise AssertionError(f"{label} contains non-ASCII characters")
    for bad_tok in (
        SLASH_SLASH_TOK,
        SLASH_STAR_TOK,
        STAR_SLASH_TOK,
        HASH_TOK,
        EM_DASH_TOK,
        EN_DASH_TOK,
        UNICODE_MINUS_TOK,
    ):
        if bad_tok in text:
            raise AssertionError(f"{label} contains forbidden token {bad_tok!r}")
    for xss_sink in FORBIDDEN_DOM_SINKS:
        if xss_sink in text:
            raise AssertionError(f"{label} contains forbidden DOM sink {xss_sink!r}")
    for rx in CREDENTIAL_CHECKS:
        m = rx.search(text)
        if m:
            raise AssertionError(f"{label} matched credential pattern: {m.group(0)[:6]}...")


def run_self_check(out_path: Path = DEFAULT_OUT_PATH) -> dict[str, Any]:
    pack = build_duel_pack_dict()
    expected_js = render_duel_pack_js(pack)
    _assert_hygiene(Path(__file__).read_text(encoding="utf-8"), "export_arena_duel_pack.py")

    if not out_path.is_file():
        raise AssertionError(f"missing generated file: {out_path}")
    actual_js = out_path.read_text(encoding="utf-8")
    if actual_js != expected_js:
        raise AssertionError(f"{out_path} is out of date with deterministic generator output")

    if len(pack["episodes"]) != 20:
        raise AssertionError(f"expected 20 canonical episodes, got {len(pack['episodes'])}")

    s6_rev = unseal_reveal_token(pack["episodes"]["hard:6:gemini"])
    s26_rev = unseal_reveal_token(pack["episodes"]["hard:26:gemini"])
    if not (
        math.isclose(s6_rev["score"], 0.73, abs_tol=1e-9)
        and s6_rev["mole"] == "e34"
        and s6_rev["accused"] == "e34"
        and s6_rev["correct"] is True
        and s6_rev["final_day"] == 6
        and s6_rev["tool_calls"] == 57
        and math.isclose(s6_rev["solver"]["score"], 0.71, abs_tol=1e-9)
        and s6_rev["solver"]["final_day"] == 6
        and s6_rev["solver"]["tool_calls"] == 52
    ):
        raise AssertionError(f"seed 6 parity check failed: {s6_rev}")

    if not (
        math.isclose(s26_rev["score"], -1.0, abs_tol=1e-9)
        and s26_rev["mole"] == "e08"
        and s26_rev["accused"] == "e04"
        and s26_rev["correct"] is False
        and s26_rev["final_day"] == 10
        and s26_rev["tool_calls"] == 91
        and math.isclose(s26_rev["solver"]["score"], 0.69, abs_tol=1e-9)
        and s26_rev["solver"]["final_day"] == 7
        and s26_rev["solver"]["tool_calls"] == 60
    ):
        raise AssertionError(f"seed 26 parity check failed: {s26_rev}")

    marker = "window.CANARY_DUEL_PACK = "
    m_pos = actual_js.find(marker)
    if m_pos < 0:
        raise AssertionError("missing window.CANARY_DUEL_PACK assignment in generated JS")
    parsed_pack, _ = json.JSONDecoder().raw_decode(actual_js, m_pos + len(marker))
    if parsed_pack != pack:
        raise AssertionError("decoded window.CANARY_DUEL_PACK JSON mismatch")
    _assert_zero_pre_end_leaks(parsed_pack)

    node_bin = _find_node_bin()
    if node_bin is not None:
        node_script = (
            "const pack = require(process.argv[1]);"
            "if (pack.version !== 'v1.4') process.exit(2);"
            "if (Object.keys(pack.episodes).length !== 20) process.exit(3);"
            "if (!pack.episodes['hard:6:gemini'] || !pack.episodes['hard:6:solver']) process.exit(4);"
            "if (pack.episodes['hard:6'] !== pack.episodes['hard:6:gemini']) process.exit(5);"
            "if (JSON.stringify(pack.default_seeds) !== JSON.stringify([6,26,4,18,15,11,5,23])) process.exit(6);"
            "if (JSON.stringify(pack.seeds_by_tier.medium) !== JSON.stringify([0,12])) process.exit(10);"
            "if (pack.unlockPostGameReveal('hard', 26, false) !== null) process.exit(7);"
            "const pre = pack.getPreEndEpisode('hard', 6, 6);"
            "const acc = pre.steps[pre.steps.length - 1];"
            "if (acc.args.employee !== '[SEALED]' || !acc.summary.includes('[SEALED]') || !acc.sealed || !pre.final || pre.final.sealed !== true) process.exit(8);"
            "const preSol = pack.getPreEndEpisode('hard', 6, 'solver');"
            "if (preSol.agent_id !== 'solver' || preSol.steps.length !== 52) process.exit(11);"
            "const unl = pack.getUnlockedEpisode('hard', 6, true, 'gemini');"
            "if (unl.steps[unl.steps.length - 1].args.employee !== 'e34' || unl.final.score !== 0.73) process.exit(12);"
            "const rev = pack.unlockPostGameReveal('hard', 26, true);"
            "if (rev.mole !== 'e08' || rev.accused !== 'e04' || rev.score !== -1 || rev.solver.score !== 0.69 || !rev.mole_name) process.exit(9);"
        )
        proc = subprocess.run(
            [node_bin, "-e", node_script, str(out_path.resolve())],
            capture_output=True,
            text=True,
            timeout=15,
        )
        if proc.returncode != 0:
            raise AssertionError(f"node verification failed (rc={proc.returncode}): {proc.stderr}")

    return {
        "worlds": len(pack["worlds"]),
        "paired_episodes": len(pack["episodes"]),
        "bytes": len(expected_js.encode("utf-8")),
        "seed6_gemini": s6_rev["score"],
        "seed6_solver": s6_rev["solver"]["score"],
        "seed26_gemini": s26_rev["score"],
        "seed26_solver": s26_rev["solver"]["score"],
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Export replay-verified committed v1.4 duel pack for Canary Arena."
    )
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT_PATH)
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args(argv)

    if args.check:
        stats = run_self_check(args.out)
        print(
            f"OK: {stats['paired_episodes']} episodes across {stats['worlds']} worlds verified "
            f"({stats['bytes']} bytes; seed6={stats['seed6_gemini']:+.2f}/{stats['seed6_solver']:+.2f}, "
            f"seed26={stats['seed26_gemini']:+.2f}/{stats['seed26_solver']:+.2f})"
        )
        return 0

    pack = build_duel_pack_dict()
    js_text = render_duel_pack_js(pack)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(js_text, encoding="utf-8")
    stats = run_self_check(args.out)
    print(
        f"Wrote {args.out} ({stats['bytes']} bytes, {stats['paired_episodes']} replay-verified episodes "
        f"across {stats['worlds']} worlds)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
