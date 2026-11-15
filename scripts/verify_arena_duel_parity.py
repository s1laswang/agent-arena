"""Replay-verify Canary Arena duel transcripts, SolverPolicy parity, and AiDuelPanel contracts."""
from __future__ import annotations

import argparse
import base64
import json
import logging
import math
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from canary import eval as canary_eval
from canary.env import Env, _SPECS
from canary.rules import HELDOUT_SEEDS, JUDGE_SEEDS, TIERS, TIERS_VERSION
from canary.solver.policy import SolverPolicy
from canary.types import EpisodeResult, Step

DEFAULT_OUT_REL = "docs/arena/arena_duel_parity_v14.json"
MAX_ARTIFACT_BYTES = 50 * 1024
PARITY_TOL = 1e-12
FEATURED_HARD_SEEDS = (6, 26)
LIVE_HARD_SOLVER_SEEDS = (0, 6, 26)
EXPECTED_SEEDS = tuple(range(30))
SEALED_TOKEN = "[SEALED]"

OC_UNAVAILABLE_PREFIX = "Model tried to call unavailable tool"
OC_TRUNCATED_RE = re.compile(
    r"\A\s*\.\.\.(\d+) bytes truncated\.\.\.\s+"
    r"The tool call succeeded but the output was truncated\. Full output saved to: "
)
EMP_ID_RE = re.compile(r"\Ae\d{2,3}\Z")

FORBIDDEN_PRE_END_KEYS = frozenset(
    {
        "mole",
        "true_mole",
        "mole_id",
        "moleId",
        "is_mole",
        "decoy",
        "true_decoy",
        "decoy_id",
        "decoyId",
        "is_decoy",
        "decoy_mood",
        "correct",
        "accused_correct",
        "true_v",
        "true_V",
        "trueV",
        "score",
        "is_canary",
        "isCanary",
        "leaking_sprite_employee",
        "mole_sprite",
        "culprit_sprite",
        "leaker_employee",
        "world_seed",
        "_world",
        "_feed",
    }
)

POST_END_CONTAINER_KEYS = frozenset(
    {
        "final",
        "verdict",
        "sealed_verdict",
        "reveal",
        "outcome",
        "terminal",
        "post_end",
        "post_game",
        "case_closed",
        "sealed_reveal",
        "end_reveal",
        "sealed",
        "commitment",
        "solver_final",
        "solver_verdict",
        "solver_sealed_reveal",
        "sealed_reveal_b64",
        "solver_sealed_reveal_b64",
    }
)

MOLE_MODES = frozenset({"be_the_mole", "mole", "mode3", "mode_3", "play_mole", "play_as_mole"})

CONTRACT_TOP_KEYS = ("seed", "tier", "agent", "steps", "final")
CONTRACT_STEP_KEYS = ("day", "call_idx", "tool", "args", "ok", "summary", "V")
CONTRACT_FINAL_KEYS = ("accused", "correct", "final_day", "tool_calls", "score")

FORBIDDEN_BUNDLE_SEEDS = frozenset(JUDGE_SEEDS) | frozenset(HELDOUT_SEEDS)


def is_client_refused_unavailable_tool(step: dict[str, Any]) -> bool:
    tool = step.get("tool")
    res = step.get("result")
    return (
        tool not in _SPECS
        and isinstance(res, dict)
        and res.get("ok") is False
        and isinstance(res.get("error"), str)
        and res["error"].startswith(OC_UNAVAILABLE_PREFIX)
    )


def parse_client_truncated_bytes(recorded_result: Any) -> int | None:
    if (
        isinstance(recorded_result, dict)
        and set(recorded_result.keys()) == {"raw"}
        and isinstance(recorded_result.get("raw"), str)
    ):
        match = OC_TRUNCATED_RE.match(recorded_result["raw"])
        if match:
            return int(match.group(1))
    return None


def unwrap_mcp_error_payload(recorded_result: Any) -> Any:
    if (
        isinstance(recorded_result, dict)
        and isinstance(recorded_result.get("error"), str)
        and recorded_result["error"].startswith("{")
    ):
        try:
            inner = json.loads(recorded_result["error"])
        except ValueError:
            return recorded_result
        if isinstance(inner, dict) and {"ok", "data", "error"} <= set(inner.keys()):
            return inner
    return recorded_result


def canonical_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, default=str)


class TranscriptReplayPolicy:
    def __init__(
        self,
        raw_steps: list[dict[str, Any]],
        agent: str = "opencode:google/gemini-4-carbon",
        env_ref: Env | None = None,
    ) -> None:
        self.name = str(agent)
        self.raw_steps = list(raw_steps)
        self.server_steps: list[dict[str, Any]] = []
        self.client_refused_steps: list[dict[str, Any]] = []
        for raw_idx, st in enumerate(self.raw_steps):
            if is_client_refused_unavailable_tool(st):
                self.client_refused_steps.append(
                    {
                        "raw_step_index": raw_idx,
                        "day": int(st.get("day", 1)),
                        "tool": str(st.get("tool", "")),
                        "error": str((st.get("result") or {}).get("error", "")),
                    }
                )
            else:
                self.server_steps.append(st)
        self._env_ref = env_ref
        self.cursor = 0
        self.step_v_snapshots: list[tuple[float, float]] = []

    def reset(self, tools_spec: list[dict[str, Any]], instruction: str) -> None:
        del tools_spec, instruction
        self.cursor = 0
        self.step_v_snapshots = []

    def act(self, history: list[Step]) -> tuple[str, dict[str, Any]]:
        if self._env_ref is not None and len(history) > len(self.step_v_snapshots):
            self.step_v_snapshots.append(
                (self._env_ref.visible_V(), round(self._env_ref.V, 10))
            )
        if self.cursor >= len(self.server_steps):
            raise RuntimeError("TranscriptReplayPolicy exhausted server_steps")
        st = self.server_steps[self.cursor]
        self.cursor += 1
        raw_args = st.get("args")
        args = dict(raw_args) if isinstance(raw_args, dict) else {}
        return str(st["tool"]), args

    def finalize_snapshots(self, total_steps: int) -> None:
        if self._env_ref is None:
            return
        while len(self.step_v_snapshots) < total_steps:
            self.step_v_snapshots.append(
                (self._env_ref.visible_V(), round(self._env_ref.V, 10))
            )


def summarize_public_step(tool: str, args: dict[str, Any], result_payload: dict[str, Any], day: int, known_v: float) -> str:
    ok = bool(result_payload.get("ok", False))
    if not ok:
        err = str(result_payload.get("error") or "failed")
        return f"Rejected {tool}: {err}"
    data = result_payload.get("data") if isinstance(result_payload.get("data"), dict) else {}
    if tool == "status":
        return f"Checked status on day {day} (known V={known_v:.2f})"
    if tool == "list_employees":
        emps = data.get("employees") if isinstance(data.get("employees"), list) else []
        return f"Listed {len(emps)} employees"
    if tool == "list_documents":
        docs = data.get("documents") if isinstance(data.get("documents"), list) else []
        return f"Listed {len(docs)} documents"
    if tool == "read_access_logs":
        logs = data.get("logs") if isinstance(data.get("logs"), list) else []
        emp = args.get("employee")
        suffix = f" for {emp}" if isinstance(emp, str) and emp else ""
        return f"Read {len(logs)} access log entries{suffix}"
    if tool == "search_messages":
        msgs = data.get("messages") if isinstance(data.get("messages"), list) else []
        q = str(args.get("query") or "")[:24]
        return f"Searched messages for {q!r} ({len(msgs)} hits)"
    if tool == "read_message":
        mid = str(args.get("id") or "?")
        return f"Read message {mid}"
    if tool == "interview":
        emp = str(args.get("employee") or "?")
        topic = str(args.get("topic") or "?")
        return f"Interviewed {emp} on {topic}"
    if tool == "plant_canary":
        cid = str(data.get("canary_id") or "canary")
        asg = args.get("assignment") if isinstance(args.get("assignment"), dict) else {}
        return f"Planted canary {cid} ({len(asg)} recipients)"
    if tool == "check_leak_feed":
        items = data.get("items") if isinstance(data.get("items"), list) else []
        return f"Checked leak feed ({len(items)} surfaced)"
    if tool == "restrict_access":
        return f"Restricted {args.get('employee', '?')}"
    if tool == "unrestrict_access":
        return f"Unrestricted {args.get('employee', '?')}"
    if tool == "advance_day":
        if data.get("episode_over"):
            return f"Closed final day {day}"
        next_day = data.get("day", day + 1)
        return f"Advanced from day {day} to day {next_day}"
    if tool == "accuse":
        return f"Accused {args.get('employee', '?')}"
    return f"Called {tool}"


def scrub_pre_end_object(value: Any) -> Any:
    if isinstance(value, list):
        return [scrub_pre_end_object(item) for item in value]
    if isinstance(value, dict):
        return {
            str(k): scrub_pre_end_object(v)
            for k, v in value.items()
            if str(k) not in FORBIDDEN_PRE_END_KEYS
        }
    return value


def find_forbidden_pre_end_keys(value: Any, path: str = "root") -> list[str]:
    hits: list[str] = []
    if isinstance(value, dict):
        for k, v in value.items():
            ks = str(k)
            loc = f"{path}.{ks}"
            if ks in FORBIDDEN_PRE_END_KEYS:
                hits.append(loc)
            hits.extend(find_forbidden_pre_end_keys(v, loc))
    elif isinstance(value, list):
        for idx, item in enumerate(value):
            hits.extend(find_forbidden_pre_end_keys(item, f"{path}[{idx}]"))
    return hits


def build_ai_duel_contract(
    tier: str,
    seed: int,
    agent: str,
    replayed_ep: EpisodeResult,
    step_v_snapshots: list[tuple[float, float]],
) -> dict[str, Any]:
    steps_out: list[dict[str, Any]] = []
    for idx, st in enumerate(replayed_ep.steps):
        known_v = float(step_v_snapshots[idx][0])
        res_dict = st.result if isinstance(st.result, dict) else {}
        clean_args = scrub_pre_end_object(dict(st.args) if isinstance(st.args, dict) else {})
        steps_out.append(
            {
                "day": int(st.day),
                "call_idx": int(idx),
                "tool": str(st.tool),
                "args": clean_args,
                "ok": bool(res_dict.get("ok", False)),
                "summary": summarize_public_step(str(st.tool), clean_args, res_dict, int(st.day), known_v),
                "V": known_v,
            }
        )
    final_obj = {
        "accused": replayed_ep.accused,
        "correct": bool(replayed_ep.correct),
        "final_day": int(replayed_ep.final_day),
        "tool_calls": int(len(replayed_ep.steps)),
        "score": float(replayed_ep.score),
    }
    return {
        "seed": int(seed),
        "tier": str(tier),
        "agent": str(agent),
        "steps": steps_out,
        "final": final_obj,
    }


def project_ai_duel_view(
    contract: dict[str, Any],
    human_day: int,
    human_done: bool,
) -> dict[str, Any]:
    day_cap = max(1, int(human_day))
    all_steps = contract.get("steps") if isinstance(contract.get("steps"), list) else []
    raw_final = contract.get("final") if isinstance(contract.get("final"), dict) else {}

    if human_done is True:
        unlocked_steps = []
        for st in all_steps:
            unlocked_steps.append(
                {
                    "day": int(st["day"]),
                    "call_idx": int(st["call_idx"]),
                    "tool": str(st["tool"]),
                    "args": dict(st.get("args") or {}),
                    "ok": bool(st.get("ok", True)),
                    "summary": str(st.get("summary", "")),
                    "V": float(st["V"]),
                    "sealed": False,
                }
            )
        return {
            "seed": int(contract["seed"]),
            "tier": str(contract["tier"]),
            "agent": str(contract["agent"]),
            "human_day": day_cap,
            "human_done": True,
            "status": "unlocked",
            "sealed_day": None,
            "accused": raw_final.get("accused"),
            "steps": unlocked_steps,
            "final": {
                "accused": raw_final.get("accused"),
                "correct": bool(raw_final.get("correct", False)),
                "final_day": int(raw_final.get("final_day", day_cap)),
                "tool_calls": int(raw_final.get("tool_calls", len(unlocked_steps))),
                "score": float(raw_final.get("score", 0.0)),
            },
        }

    gated_steps: list[dict[str, Any]] = []
    sealed_day: int | None = None
    for st in all_steps:
        s_day = int(st["day"])
        if s_day > day_cap:
            continue
        tool_name = str(st["tool"])
        if tool_name == "accuse":
            sealed_day = s_day if sealed_day is None else min(sealed_day, s_day)
            gated_steps.append(
                {
                    "day": s_day,
                    "call_idx": int(st["call_idx"]),
                    "tool": "accuse",
                    "args": {"employee": SEALED_TOKEN},
                    "ok": bool(st.get("ok", True)),
                    "summary": SEALED_TOKEN,
                    "V": float(st["V"]),
                    "sealed": True,
                }
            )
        else:
            gated_steps.append(
                {
                    "day": s_day,
                    "call_idx": int(st["call_idx"]),
                    "tool": tool_name,
                    "args": scrub_pre_end_object(dict(st.get("args") or {})),
                    "ok": bool(st.get("ok", True)),
                    "summary": str(st.get("summary", tool_name)),
                    "V": float(st["V"]),
                    "sealed": False,
                }
            )

    if raw_final.get("accused") is not None and int(raw_final.get("final_day", 999)) <= day_cap:
        f_day = int(raw_final["final_day"])
        sealed_day = f_day if sealed_day is None else min(sealed_day, f_day)

    early_accused = sealed_day is not None
    return {
        "seed": int(contract["seed"]),
        "tier": str(contract["tier"]),
        "agent": str(contract["agent"]),
        "human_day": day_cap,
        "human_done": False,
        "status": "sealed_accusation" if early_accused else "hunting",
        "sealed_day": sealed_day,
        "accused": SEALED_TOKEN if early_accused else None,
        "steps": gated_steps,
        "final": None,
    }


def validate_ai_duel_contract_and_views(
    contract: dict[str, Any],
    replayed_ep: EpisodeResult,
    step_v_snapshots: list[tuple[float, float]],
    terminal_true_v: float,
    wrong_accusation_score: float,
    n_days: int,
) -> dict[str, Any]:
    problems: list[str] = []
    if tuple(contract.keys()) != CONTRACT_TOP_KEYS and set(contract.keys()) != set(CONTRACT_TOP_KEYS):
        problems.append(f"contract keys mismatch: {sorted(contract.keys())}")
    final_obj = contract.get("final")
    if not isinstance(final_obj, dict) or set(final_obj.keys()) != set(CONTRACT_FINAL_KEYS):
        problems.append("contract.final keys mismatch")
    steps = contract.get("steps")
    if not isinstance(steps, list) or len(steps) != len(replayed_ep.steps):
        problems.append("contract.steps length mismatch")
        return {"ok": False, "problems": problems}

    unsurfaced_gap_steps = 0
    for idx, st in enumerate(steps):
        if set(st.keys()) != set(CONTRACT_STEP_KEYS):
            problems.append(f"step[{idx}] keys mismatch: {sorted(st.keys())}")
            break
        known_v, true_v = step_v_snapshots[idx]
        if abs(float(st["V"]) - known_v) >= PARITY_TOL:
            problems.append(f"step[{idx}].V={st['V']} != known_v={known_v}")
        if abs(true_v - known_v) > 1e-9:
            unsurfaced_gap_steps += 1
            if abs(float(st["V"]) - true_v) < 1e-9:
                problems.append(f"step[{idx}].V leaked unsurfaced true_V={true_v}")

    pre_end_days_checked = 0
    sealed_views_checked = 0
    ai_accused = replayed_ep.accused
    ai_final_day = int(replayed_ep.final_day)

    for h_day in range(1, int(n_days) + 1):
        view = project_ai_duel_view(contract, h_day, human_done=False)
        pre_end_days_checked += 1
        if view["final"] is not None:
            problems.append(f"day {h_day}: pre-end final must be None")
        forbidden_hits = find_forbidden_pre_end_keys(view)
        if forbidden_hits:
            problems.append(f"day {h_day}: forbidden pre-end keys {forbidden_hits[:3]}")
        expected_count = sum(1 for st in steps if int(st["day"]) <= h_day)
        if len(view["steps"]) != expected_count:
            problems.append(
                f"day {h_day}: visible step count {len(view['steps'])} != expected {expected_count}"
            )
        for vst in view["steps"]:
            if int(vst["day"]) > h_day:
                problems.append(f"day {h_day}: future step day {vst['day']} leaked")
            cidx = int(vst["call_idx"])
            kv, tv = step_v_snapshots[cidx]
            if abs(float(vst["V"]) - kv) >= PARITY_TOL:
                problems.append(f"day {h_day} step {cidx}: V={vst['V']} != known_v={kv}")
            if abs(tv - kv) > 1e-9 and abs(float(vst["V"]) - tv) < 1e-9:
                problems.append(f"day {h_day} step {cidx}: leaked unsurfaced true_V={tv}")
            if vst["tool"] == "accuse":
                if vst["args"] != {"employee": SEALED_TOKEN} or vst["summary"] != SEALED_TOKEN or vst["sealed"] is not True:
                    problems.append(f"day {h_day} step {cidx}: accuse step not sealed")

        if ai_accused is not None and ai_final_day <= h_day:
            sealed_views_checked += 1
            if view["accused"] != SEALED_TOKEN or view["status"] != "sealed_accusation":
                problems.append(f"day {h_day}: early accusation target not sealed as {SEALED_TOKEN}")
        else:
            if view["accused"] is not None or view["status"] != "hunting":
                problems.append(f"day {h_day}: unexpected sealed status before accusation")

    post_view = project_ai_duel_view(contract, n_days, human_done=True)
    pfin = post_view.get("final") or {}
    if set(pfin.keys()) != set(CONTRACT_FINAL_KEYS):
        problems.append("post-end final keys mismatch")
    if pfin.get("accused") != replayed_ep.accused:
        problems.append(f"post-end accused {pfin.get('accused')} != {replayed_ep.accused}")
    if pfin.get("correct") is not bool(replayed_ep.correct):
        problems.append("post-end correct mismatch")
    if int(pfin.get("final_day", -1)) != int(replayed_ep.final_day):
        problems.append("post-end final_day mismatch")
    if int(pfin.get("tool_calls", -1)) != len(replayed_ep.steps):
        problems.append("post-end tool_calls mismatch")
    if abs(float(pfin.get("score", math.nan)) - float(replayed_ep.score)) >= PARITY_TOL:
        problems.append(f"post-end score {pfin.get('score')} != {replayed_ep.score}")

    if replayed_ep.correct:
        expected_reward = float(terminal_true_v)
    elif replayed_ep.accused is not None:
        expected_reward = float(wrong_accusation_score)
    else:
        expected_reward = 0.0
    if abs(float(pfin.get("score", math.nan)) - expected_reward) >= PARITY_TOL:
        problems.append(
            f"post-end score {pfin.get('score')} violates reward rule (expected {expected_reward})"
        )

    return {
        "ok": not problems,
        "problems": problems,
        "unsurfaced_gap_steps": unsurfaced_gap_steps,
        "pre_end_days_checked": pre_end_days_checked,
        "sealed_views_checked": sealed_views_checked,
    }


def replay_and_verify_episode(episode_dict: dict[str, Any]) -> dict[str, Any]:
    tier = str(episode_dict["tier"])
    seed = int(episode_dict["seed"])
    agent = str(episode_dict["agent"])
    raw_steps = list(episode_dict.get("steps") or [])

    env = canary_eval.make_env(tier, seed, "template")
    policy = TranscriptReplayPolicy(raw_steps, agent=agent, env_ref=env)
    replayed_ep = canary_eval.run_episode(
        env,
        policy,
        max_iters=len(policy.server_steps),
    )
    policy.finalize_snapshots(len(replayed_ep.steps))

    step_mismatches: list[dict[str, Any]] = []
    detail_compat_steps = 0
    truncated_steps: list[dict[str, Any]] = []

    if len(replayed_ep.steps) != len(policy.server_steps):
        step_mismatches.append(
            {
                "step_index": len(replayed_ep.steps),
                "reason": f"step_count_mismatch:{len(replayed_ep.steps)}!={len(policy.server_steps)}",
            }
        )

    for idx, (rec_st, got_st) in enumerate(zip(policy.server_steps, replayed_ep.steps)):
        got_payload = dict(got_st.result) if isinstance(got_st.result, dict) else {}
        rec_res = rec_st.get("result")
        cmp_payload = got_payload
        if (
            not got_payload.get("ok", True)
            and isinstance(got_payload.get("data"), dict)
            and set(got_payload["data"].keys()) == {"detail"}
            and not (
                isinstance(rec_res, dict)
                and isinstance(rec_res.get("data"), dict)
                and "detail" in rec_res["data"]
            )
        ):
            detail_compat_steps += 1
            cmp_payload = {
                "ok": got_payload["ok"],
                "data": {},
                "error": got_payload.get("error"),
            }

        trunc_bytes = parse_client_truncated_bytes(rec_res)
        if trunc_bytes is not None:
            actual_bytes = len(json.dumps(cmp_payload).encode("utf-8"))
            truncated_steps.append(
                {
                    "server_step_index": idx,
                    "day": int(got_st.day),
                    "tool": str(got_st.tool),
                    "expected_bytes": trunc_bytes,
                    "replayed_bytes": actual_bytes,
                }
            )
            if actual_bytes != trunc_bytes:
                step_mismatches.append(
                    {
                        "step_index": idx,
                        "tool": str(got_st.tool),
                        "reason": f"truncated_byte_mismatch:{actual_bytes}!={trunc_bytes}",
                    }
                )
        elif rec_res is not None:
            want_payload = unwrap_mcp_error_payload(rec_res)
            if canonical_json(cmp_payload) != canonical_json(want_payload):
                step_mismatches.append(
                    {
                        "step_index": idx,
                        "tool": str(got_st.tool),
                        "reason": "payload_mismatch",
                    }
                )

    stored_score = float(episode_dict["score"])
    score_diff = abs(float(replayed_ep.score) - stored_score)
    verdict_mismatches: list[str] = []
    if score_diff >= PARITY_TOL:
        verdict_mismatches.append(f"score:{replayed_ep.score}!={stored_score}")
    if replayed_ep.accused != episode_dict.get("accused"):
        verdict_mismatches.append(f"accused:{replayed_ep.accused}!={episode_dict.get('accused')}")
    if bool(replayed_ep.correct) != bool(episode_dict.get("correct")):
        verdict_mismatches.append(f"correct:{replayed_ep.correct}!={episode_dict.get('correct')}")
    if int(replayed_ep.final_day) != int(episode_dict.get("final_day")):
        verdict_mismatches.append(f"final_day:{replayed_ep.final_day}!={episode_dict.get('final_day')}")
    if episode_dict.get("end_reason") is not None and replayed_ep.end_reason != episode_dict.get("end_reason"):
        verdict_mismatches.append(f"end_reason:{replayed_ep.end_reason}!={episode_dict.get('end_reason')}")

    terminal_true_v = round(env.V, 10)
    contract = build_ai_duel_contract(
        tier=tier,
        seed=seed,
        agent=agent,
        replayed_ep=replayed_ep,
        step_v_snapshots=policy.step_v_snapshots,
    )
    contract_audit = validate_ai_duel_contract_and_views(
        contract=contract,
        replayed_ep=replayed_ep,
        step_v_snapshots=policy.step_v_snapshots,
        terminal_true_v=terminal_true_v,
        wrong_accusation_score=float(env.p.wrong_accusation_score),
        n_days=int(env.p.n_days),
    )

    parity_ok = (not step_mismatches) and (not verdict_mismatches) and contract_audit["ok"]
    return {
        "tier": tier,
        "seed": seed,
        "agent": agent,
        "parity_ok": parity_ok,
        "score_abs_diff": score_diff,
        "verdict_mismatches": verdict_mismatches,
        "step_mismatches": step_mismatches,
        "raw_step_count": len(raw_steps),
        "server_step_count": len(replayed_ep.steps),
        "client_refused_steps": policy.client_refused_steps,
        "truncated_steps": truncated_steps,
        "detail_compat_steps": detail_compat_steps,
        "replayed_episode": replayed_ep,
        "step_v_snapshots": policy.step_v_snapshots,
        "terminal_true_v": terminal_true_v,
        "terminal_known_v": env.visible_V(),
        "true_mole": env._world.mole,
        "true_decoy": env._world.decoy,
        "contract": contract,
        "contract_audit": contract_audit,
    }


def load_jsonl_episodes_by_seed(paths: list[Path], seeds: tuple[int, ...] = EXPECTED_SEEDS) -> dict[int, dict[str, Any]]:
    wanted = set(seeds)
    by_seed: dict[int, dict[str, Any]] = {}
    for p in paths:
        for line in p.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            if (row.get("meta") or {}).get("valid") is False:
                continue
            s = int(row["seed"])
            if s in wanted:
                by_seed[s] = row
    return by_seed


def verify_solver_on_seeds(
    root: Path,
    tier: str,
    seeds: tuple[int, ...] = EXPECTED_SEEDS,
    live_seeds: tuple[int, ...] = (),
) -> dict[str, Any]:
    ref_files = sorted(
        (root / "data" / "runs" / "committed" / "v1.4" / "reference").glob(f"solver-{tier}-*/episodes.jsonl")
    )
    stored_by_seed = load_jsonl_episodes_by_seed(ref_files, seeds=seeds)
    live_set = set(live_seeds)
    by_seed_out: dict[int, dict[str, Any]] = {}
    mismatches: list[dict[str, Any]] = []
    max_abs_diff = 0.0
    live_verified_count = 0

    for seed in seeds:
        if seed in stored_by_seed:
            stored = stored_by_seed[seed]
            rep = replay_and_verify_episode(stored)
            replayed_ep = rep["replayed_episode"]
            diff = rep["score_abs_diff"]
            max_abs_diff = max(max_abs_diff, diff)
            ok = rep["parity_ok"]
            if not ok:
                mismatches.append(
                    {
                        "tier": tier,
                        "seed": seed,
                        "source": "transcript_replay",
                        "verdict_mismatches": rep["verdict_mismatches"],
                        "step_mismatches": rep["step_mismatches"],
                    }
                )
        else:
            live_set.add(seed)
            replayed_ep = None
            ok = True

        if seed in live_set:
            live_ep = canary_eval.run_episode(
                canary_eval.make_env(tier, seed, "template"),
                SolverPolicy(),
            )
            live_verified_count += 1
            if replayed_ep is not None:
                live_diff = abs(float(live_ep.score) - float(replayed_ep.score))
                max_abs_diff = max(max_abs_diff, live_diff)
                if (
                    live_diff >= PARITY_TOL
                    or live_ep.accused != replayed_ep.accused
                    or bool(live_ep.correct) != bool(replayed_ep.correct)
                    or int(live_ep.final_day) != int(replayed_ep.final_day)
                    or len(live_ep.steps) != len(replayed_ep.steps)
                ):
                    ok = False
                    mismatches.append(
                        {
                            "tier": tier,
                            "seed": seed,
                            "source": "live_solver_vs_committed",
                            "live_score": live_ep.score,
                            "committed_score": replayed_ep.score,
                        }
                    )
            else:
                replayed_ep = live_ep

        assert replayed_ep is not None
        by_seed_out[seed] = {
            "seed": seed,
            "tier": tier,
            "parity_ok": ok,
            "live_verified": seed in live_set,
            "final": {
                "accused": replayed_ep.accused,
                "correct": bool(replayed_ep.correct),
                "final_day": int(replayed_ep.final_day),
                "tool_calls": len(replayed_ep.steps),
                "score": float(replayed_ep.score),
            },
            "end_reason": replayed_ep.end_reason,
        }

    return {
        "tier": tier,
        "n_seeds": len(by_seed_out),
        "live_solver_verified_count": live_verified_count,
        "mismatches": mismatches,
        "max_abs_diff": max_abs_diff,
        "by_seed": by_seed_out,
    }


def _extract_balanced_json_objects(text: str) -> list[Any]:
    out: list[Any] = []
    assign_re = re.compile(
        r"(?:window|globalThis|self)\.[A-Za-z0-9_]+\s*=\s*[\{\[]"
        r"|export\s+const\s+[A-Za-z0-9_]+\s*=\s*[\{\[]"
        r"|(?:const|let|var)\s+[A-Za-z0-9_]*(?:PACK|REPLAY|BUNDLE|DUEL|TRACES)[A-Za-z0-9_]*\s*=\s*[\{\[]"
    )
    decoder = json.JSONDecoder()
    for match in assign_re.finditer(text):
        start = match.end() - 1
        try:
            obj, _ = decoder.raw_decode(text[start:])
            out.append(obj)
        except ValueError:
            continue
    return out


def extract_bundle_objects_from_file(path: Path) -> tuple[list[Any], list[str]]:
    suffix = path.suffix.lower()
    raw = path.read_text(encoding="utf-8")
    errors: list[str] = []
    if suffix == ".json":
        try:
            return [json.loads(raw)], []
        except ValueError as exc:
            return [], [f"{path.as_posix()}: invalid JSON ({exc})"]
    if suffix == ".jsonl":
        objs = []
        for idx, line in enumerate(raw.splitlines()):
            if not line.strip():
                continue
            try:
                objs.append(json.loads(line))
            except ValueError as exc:
                errors.append(f"{path.as_posix()}:{idx + 1}: invalid JSONL ({exc})")
        return objs, errors
    if suffix in {".js", ".mjs"}:
        return _extract_balanced_json_objects(raw), []
    if suffix == ".html":
        objs = []
        script_re = re.compile(
            r"<script[^>]*type=[\"']application/json[\"'][^>]*>(.*?)</script>",
            re.DOTALL | re.IGNORECASE,
        )
        for sm in script_re.finditer(raw):
            body = sm.group(1).strip()
            if body:
                try:
                    objs.append(json.loads(body))
                except ValueError as exc:
                    errors.append(f"{path.as_posix()}: invalid inline JSON script ({exc})")
        objs.extend(_extract_balanced_json_objects(raw))
        return objs, errors
    return [], []


def _is_int_not_bool(val: Any) -> bool:
    return isinstance(val, int) and not isinstance(val, bool)


def _is_sealed_token(val: Any) -> bool:
    return isinstance(val, str) and (
        val == SEALED_TOKEN
        or val.startswith("sealed:")
        or val.startswith("b64:")
        or val.startswith("sha256:")
        or val.startswith("xor:")
    )


def _decode_sealed_reveal(val: Any) -> dict[str, Any] | None:
    if isinstance(val, dict):
        return val if val.get("sealed") is not True else None
    if not isinstance(val, str):
        return None
    raw = val.strip()
    if raw.startswith("sealed:"):
        raw = raw[7:].strip()
    elif raw.startswith("b64:"):
        raw = raw[4:].strip()
    else:
        return None
    if not raw:
        return None
    try:
        decoded = json.loads(raw if raw.startswith("{") else base64.b64decode(raw).decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return None
    return decoded if isinstance(decoded, dict) else None


def _resolve_bundle_verdict_source(node: dict[str, Any], agent_name: str) -> dict[str, Any] | None:
    candidates: list[dict[str, Any]] = []
    fin = node.get("final")
    if isinstance(fin, dict) and fin.get("sealed") is not True:
        candidates.append(fin)
    sv = node.get("sealed_verdict")
    if isinstance(sv, dict) and sv.get("sealed") is not True:
        candidates.append(sv)
    dec = _decode_sealed_reveal(node.get("sealed_reveal_b64") or node.get("sealed_reveal"))
    if isinstance(dec, dict):
        candidates.append(dec)
    for cand in candidates:
        if isinstance(cand.get("final"), dict) and cand["final"].get("sealed") is not True:
            return cand["final"]
        if agent_name == "solver" and isinstance(cand.get("solver"), dict):
            return cand["solver"]
        if agent_name in {"gemini", "opencode:google/gemini-4-carbon", "opencode-gemini-4-carbon"} and isinstance(
            cand.get("gemini"), dict
        ):
            return cand["gemini"]
        if "score" in cand or "accused" in cand:
            return cand
    return candidates[0] if candidates else None


def _scan_bundle_node(
    node: Any,
    loc: str,
    known_verdicts: dict[tuple[str, int, str], dict[str, Any]],
    ctx_tier: str | None = None,
    ctx_seed: int | None = None,
    ctx_human_done: bool | None = None,
    ctx_pre_end: bool = False,
    ctx_mode: str = "",
    ctx_allow_doc_canary: bool = False,
) -> tuple[list[str], list[str], int]:
    leaks: list[str] = []
    score_mismatches: list[str] = []
    episodes_checked = 0

    if isinstance(node, list):
        for idx, item in enumerate(node):
            l_sub, s_sub, n_sub = _scan_bundle_node(
                item,
                f"{loc}[{idx}]",
                known_verdicts,
                ctx_tier=ctx_tier,
                ctx_seed=ctx_seed,
                ctx_human_done=ctx_human_done,
                ctx_pre_end=ctx_pre_end,
                ctx_mode=ctx_mode,
                ctx_allow_doc_canary=ctx_allow_doc_canary,
            )
            leaks.extend(l_sub)
            score_mismatches.extend(s_sub)
            episodes_checked += n_sub
        return leaks, score_mismatches, episodes_checked

    if not isinstance(node, dict):
        return leaks, score_mismatches, episodes_checked

    tier = str(node["tier"]) if isinstance(node.get("tier"), str) else ctx_tier
    seed = int(node["seed"]) if _is_int_not_bool(node.get("seed")) else ctx_seed
    raw_mode = node.get("mode") or node.get("game_mode")
    mode = str(raw_mode).strip().lower() if isinstance(raw_mode, str) else ctx_mode
    if seed is not None and seed in FORBIDDEN_BUNDLE_SEEDS:
        leaks.append(f"{loc}.seed: forbidden benchmark seed {seed}")
    if isinstance(node.get("seeds"), list):
        for s_item in node["seeds"]:
            if _is_int_not_bool(s_item) and int(s_item) in FORBIDDEN_BUNDLE_SEEDS:
                leaks.append(f"{loc}.seeds: forbidden benchmark seed {s_item}")
    elif isinstance(node.get("seeds"), dict):
        for t_key, s_arr in node["seeds"].items():
            if isinstance(s_arr, list):
                for s_item in s_arr:
                    if _is_int_not_bool(s_item) and int(s_item) in FORBIDDEN_BUNDLE_SEEDS:
                        leaks.append(f"{loc}.seeds.{t_key}: forbidden benchmark seed {s_item}")

    human_done = node["human_done"] if isinstance(node.get("human_done"), bool) else ctx_human_done
    explicit_done = node.get("done") is True or node.get("episode_over") is True
    explicit_not_done = node.get("done") is False or node.get("episode_over") is False
    pre_end = explicit_not_done or (human_done is False) or (ctx_pre_end and not explicit_done)

    if pre_end:
        for k in node:
            ks = str(k)
            if ks in {"is_canary", "isCanary"} and ctx_allow_doc_canary and mode not in MOLE_MODES:
                continue
            if ks in FORBIDDEN_PRE_END_KEYS and node[k] is not None and not _is_sealed_token(node[k]):
                leaks.append(f"{loc}.{ks}: pre-end hidden truth key exposed")
        if human_done is False:
            raw_acc = node.get("accused")
            if isinstance(raw_acc, str) and EMP_ID_RE.match(raw_acc):
                leaks.append(f"{loc}.accused: unsealed pre-end accused employee {raw_acc}")
            if node.get("tool") == "accuse":
                args_obj = node.get("args") if isinstance(node.get("args"), dict) else {}
                emp_target = args_obj.get("employee") if isinstance(args_obj, dict) else None
                if isinstance(emp_target, str) and EMP_ID_RE.match(emp_target):
                    leaks.append(f"{loc}.args.employee: unsealed pre-end accuse target {emp_target}")

    has_steps = isinstance(node.get("steps"), list)
    agent_name = str(node.get("agent") or node.get("agent_raw") or "")
    verdict_container = _resolve_bundle_verdict_source(node, agent_name)

    if has_steps and tier in {"easy", "medium", "hard"} and seed is not None and 0 <= seed < 10000:
        steps_list = node["steps"]
        shadow_env: Env | None = Env(tier, seed)
        all_steps_replayable = True
        for idx, st in enumerate(steps_list):
            if not isinstance(st, dict):
                all_steps_replayable = False
                continue
            st_tool = st.get("tool")
            st_args = st.get("args")
            is_sealed_step = (
                st.get("sealed") is True
                or _is_sealed_token(st_args)
                or (isinstance(st_args, dict) and _is_sealed_token(st_args.get("employee")))
            )
            if is_sealed_step or not isinstance(st_tool, str) or not isinstance(st_args, dict):
                all_steps_replayable = False
                shadow_env = None
            elif shadow_env is not None and not is_client_refused_unavailable_tool(st):
                if st_tool not in _SPECS:
                    all_steps_replayable = False
                    shadow_env = None
                else:
                    call_res = shadow_env.call(st_tool, st_args)
                    rec_ok = st.get("ok")
                    if isinstance(rec_ok, bool) and call_res.ok != rec_ok:
                        all_steps_replayable = False
                        shadow_env = None
                    else:
                        kv = shadow_env.visible_V()
                        tv = round(shadow_env.V, 10)
                        st_done = st.get("done") is True or shadow_env.done
                        if not st_done and "V" in st and isinstance(st["V"], (int, float)) and not isinstance(st["V"], bool):
                            shown_v = float(st["V"])
                            if abs(tv - kv) > 1e-9 and abs(shown_v - tv) < 1e-9:
                                leaks.append(
                                    f"{loc}.steps[{idx}].V: pre-end V={shown_v} leaked unsurfaced true_V={tv} (known_V={kv})"
                                )

        if verdict_container is not None or ("score" in node and not pre_end):
            episodes_checked += 1
            v_src = verdict_container if verdict_container is not None else node
            b_score = v_src.get("score")
            b_accused = v_src.get("accused")
            b_day = v_src.get("final_day")

            if all_steps_replayable and len(steps_list) > 0:
                ep_input = {
                    "tier": tier,
                    "seed": seed,
                    "agent": agent_name or "bundle_replay",
                    "steps": steps_list,
                    "score": float(b_score) if isinstance(b_score, (int, float)) else 0.0,
                    "accused": b_accused,
                    "correct": bool(v_src.get("correct", False)),
                    "final_day": int(b_day) if _is_int_not_bool(b_day) else 1,
                }
                env_check = canary_eval.make_env(tier, seed, "template")
                pol_check = TranscriptReplayPolicy(steps_list, agent=ep_input["agent"], env_ref=env_check)
                rep_check = canary_eval.run_episode(env_check, pol_check, max_iters=len(pol_check.server_steps))
                if isinstance(b_score, (int, float)) and abs(float(b_score) - float(rep_check.score)) >= PARITY_TOL:
                    score_mismatches.append(
                        f"{loc}: bundle score {b_score} != replayed score {rep_check.score}"
                    )
                if b_accused is not None and not _is_sealed_token(b_accused) and b_accused != rep_check.accused:
                    score_mismatches.append(
                        f"{loc}: bundle accused {b_accused} != replayed accused {rep_check.accused}"
                    )
                if _is_int_not_bool(b_day) and int(b_day) != int(rep_check.final_day):
                    score_mismatches.append(
                        f"{loc}: bundle final_day {b_day} != replayed final_day {rep_check.final_day}"
                    )
            elif (tier, seed, agent_name) in known_verdicts:
                ref_v = known_verdicts[(tier, seed, agent_name)]
                if isinstance(b_score, (int, float)) and abs(float(b_score) - float(ref_v["score"])) >= PARITY_TOL:
                    score_mismatches.append(
                        f"{loc}: bundle score {b_score} != committed {agent_name} score {ref_v['score']}"
                    )
                if b_accused is not None and not _is_sealed_token(b_accused) and b_accused != ref_v["accused"]:
                    score_mismatches.append(
                        f"{loc}: bundle accused {b_accused} != committed {ref_v['accused']}"
                    )

    is_inv_list_docs = (node.get("tool") == "list_documents") and (mode not in MOLE_MODES)

    for k, v in node.items():
        ks = str(k)
        child_loc = f"{loc}.{ks}"
        if ks in POST_END_CONTAINER_KEYS and not explicit_not_done and human_done is not False:
            continue
        child_pre_end = pre_end or (ks in {"steps", "solver_steps"} and not explicit_done)
        child_tier = tier
        child_seed = seed
        if ":" in ks:
            parts = ks.split(":")
            if len(parts) >= 2 and parts[0] in {"easy", "medium", "hard"} and parts[1].isdigit():
                child_tier = parts[0]
                child_seed = int(parts[1])
        child_allow_canary = ctx_allow_doc_canary or (
            is_inv_list_docs and ks in {"result", "data", "documents"}
        )
        l_sub, s_sub, n_sub = _scan_bundle_node(
            v,
            child_loc,
            known_verdicts,
            ctx_tier=child_tier,
            ctx_seed=child_seed,
            ctx_human_done=human_done,
            ctx_pre_end=child_pre_end,
            ctx_mode=mode,
            ctx_allow_doc_canary=child_allow_canary,
        )
        leaks.extend(l_sub)
        score_mismatches.extend(s_sub)
        episodes_checked += n_sub

    return leaks, score_mismatches, episodes_checked


def audit_arena_and_demo_bundles(
    root: Path,
    known_verdicts: dict[tuple[str, int, str], dict[str, Any]],
    skip_rel_paths: set[str] | None = None,
) -> dict[str, Any]:
    skip = set(skip_rel_paths or set())
    candidate_dirs = [root / "docs" / "arena", root / "docs" / "demo"]
    exts = {".json", ".jsonl", ".js", ".mjs", ".html"}
    files_scanned: list[str] = []
    bundle_files: list[str] = []
    parse_errors: list[str] = []
    pre_end_leaks: list[str] = []
    score_mismatches: list[str] = []
    episodes_verified = 0

    for d in candidate_dirs:
        if not d.is_dir():
            continue
        for fp in sorted(d.rglob("*")):
            if not fp.is_file() or fp.suffix.lower() not in exts:
                continue
            rel = fp.relative_to(root).as_posix()
            if rel in skip:
                continue
            files_scanned.append(rel)
            objs, errs = extract_bundle_objects_from_file(fp)
            parse_errors.extend(errs)
            if not objs:
                continue
            bundle_files.append(rel)
            for idx, obj in enumerate(objs):
                leaks, mis, ep_cnt = _scan_bundle_node(
                    obj,
                    f"{rel}[{idx}]",
                    known_verdicts=known_verdicts,
                )
                pre_end_leaks.extend(leaks)
                score_mismatches.extend(mis)
                episodes_verified += ep_cnt

    ok = (not parse_errors) and (not pre_end_leaks) and (not score_mismatches)
    return {
        "ok": ok,
        "dirs_checked": ["docs/arena", "docs/demo"],
        "files_scanned": len(files_scanned),
        "bundle_files_discovered": len(bundle_files),
        "bundle_files": bundle_files,
        "episodes_verified": episodes_verified,
        "parse_errors": parse_errors,
        "pre_end_leak_count": len(pre_end_leaks),
        "pre_end_leaks": pre_end_leaks,
        "score_mismatch_count": len(score_mismatches),
        "score_mismatches": score_mismatches,
    }


def build_parity_report(root: Path = ROOT, live_solver_all: bool = False) -> dict[str, Any]:
    logging.getLogger("canary.solver").setLevel(logging.ERROR)

    gem_base = root / "data" / "runs" / "committed" / "v1.4" / "opencode-gemini-4-carbon"
    flash_hard_path = (
        root / "data" / "runs" / "committed" / "v1.4" / "opencode-gemini-3.5-flash" / "hard" / "episodes.jsonl"
    )

    tier_reports: dict[str, Any] = {}
    featured_contracts: dict[str, Any] = {}
    featured_highlights: dict[str, Any] = {}
    known_verdicts: dict[tuple[str, int, str], dict[str, Any]] = {}

    total_gem_episodes = 0
    total_gem_steps = 0
    total_gem_mismatches = 0
    total_detail_compat = 0
    total_pre_end_days_checked = 0
    total_unsurfaced_gap_steps = 0
    max_abs_diff = 0.0

    for tier in ("hard", "medium"):
        ep_file = gem_base / tier / "episodes.jsonl"
        gem_by_seed = load_jsonl_episodes_by_seed([ep_file], seeds=EXPECTED_SEEDS)
        live_seeds = EXPECTED_SEEDS if live_solver_all else LIVE_HARD_SOLVER_SEEDS
        solver_res = verify_solver_on_seeds(root, tier, seeds=EXPECTED_SEEDS, live_seeds=live_seeds)
        max_abs_diff = max(max_abs_diff, solver_res["max_abs_diff"])

        seed_rows: list[dict[str, Any]] = []
        tier_mismatches: list[dict[str, Any]] = list(solver_res["mismatches"])
        tier_detail_compat = 0
        tier_steps = 0
        tier_pre_end_days = 0
        tier_unsurfaced_steps = 0

        for seed in EXPECTED_SEEDS:
            ep_dict = gem_by_seed[seed]
            rep = replay_and_verify_episode(ep_dict)
            sol_entry = solver_res["by_seed"][seed]
            sol_final = sol_entry["final"]
            gem_final = rep["contract"]["final"]

            for gem_alias in {rep["agent"], "gemini", "opencode-gemini-4-carbon"}:
                known_verdicts[(tier, seed, gem_alias)] = dict(gem_final)
            known_verdicts[(tier, seed, "solver")] = dict(sol_final)

            total_gem_episodes += 1
            tier_steps += rep["server_step_count"]
            tier_detail_compat += rep["detail_compat_steps"]
            tier_pre_end_days += rep["contract_audit"]["pre_end_days_checked"]
            tier_unsurfaced_steps += rep["contract_audit"]["unsurfaced_gap_steps"]
            max_abs_diff = max(max_abs_diff, rep["score_abs_diff"])

            row_ok = rep["parity_ok"] and sol_entry["parity_ok"]
            if not rep["parity_ok"]:
                total_gem_mismatches += 1
                tier_mismatches.append(
                    {
                        "tier": tier,
                        "seed": seed,
                        "verdict_mismatches": rep["verdict_mismatches"],
                        "step_mismatches": rep["step_mismatches"],
                        "contract_problems": rep["contract_audit"]["problems"],
                    }
                )

            seed_rows.append(
                {
                    "seed": seed,
                    "tier": tier,
                    "done": True,
                    "parity_ok": row_ok,
                    "detail_compat_steps": rep["detail_compat_steps"],
                    "unsurfaced_gap_steps": rep["contract_audit"]["unsurfaced_gap_steps"],
                    "final": {
                        "gemini": gem_final,
                        "solver": sol_final,
                        "score_gap_solver_minus_gemini": round(
                            float(sol_final["score"]) - float(gem_final["score"]), 6
                        ),
                    },
                }
            )

            if tier == "hard" and seed in FEATURED_HARD_SEEDS:
                key = f"hard_seed_{seed}"
                featured_contracts[key] = rep["contract"]
                sample_unsurfaced_day = 5 if seed == 6 else 9
                pre_unsurfaced = project_ai_duel_view(rep["contract"], sample_unsurfaced_day, human_done=False)
                pre_sealed = project_ai_duel_view(rep["contract"], int(gem_final["final_day"]), human_done=False)
                post_unlocked = project_ai_duel_view(rep["contract"], int(TIERS[tier].n_days), human_done=True)
                featured_highlights[key] = {
                    "seed": seed,
                    "tier": tier,
                    "headline_role": "caught_calibration" if seed == 6 else "fooled_by_noisy_canary",
                    "pre_end_unsurfaced_check": {
                        "human_day": sample_unsurfaced_day,
                        "human_done": False,
                        "status": pre_unsurfaced["status"],
                        "accused": pre_unsurfaced["accused"],
                        "visible_step_count": len(pre_unsurfaced["steps"]),
                        "last_step_known_V": pre_unsurfaced["steps"][-1]["V"],
                        "final": pre_unsurfaced["final"],
                    },
                    "pre_end_early_accuse_check": {
                        "human_day": int(gem_final["final_day"]),
                        "human_done": False,
                        "status": pre_sealed["status"],
                        "sealed_day": pre_sealed["sealed_day"],
                        "accused": pre_sealed["accused"],
                        "terminal_step_projected": pre_sealed["steps"][-1],
                        "final": pre_sealed["final"],
                    },
                    "post_end": {
                        "human_done": True,
                        "true_mole": rep["true_mole"],
                        "true_decoy": rep["true_decoy"],
                        "gemini_final": post_unlocked["final"],
                        "solver_final": sol_final,
                    },
                }

        total_gem_steps += tier_steps
        total_detail_compat += tier_detail_compat
        total_pre_end_days_checked += tier_pre_end_days
        total_unsurfaced_gap_steps += tier_unsurfaced_steps

        gem_scores = [r["final"]["gemini"]["score"] for r in seed_rows]
        sol_scores = [r["final"]["solver"]["score"] for r in seed_rows]
        tier_reports[tier] = {
            "tier": tier,
            "n_episodes": len(seed_rows),
            "seeds_range": "0-29",
            "gemini_mean_score": round(sum(gem_scores) / len(gem_scores), 6),
            "solver_mean_score": round(sum(sol_scores) / len(sol_scores), 6),
            "gemini_accuracy": round(
                sum(1 for r in seed_rows if r["final"]["gemini"]["correct"]) / len(seed_rows), 6
            ),
            "solver_accuracy": round(
                sum(1 for r in seed_rows if r["final"]["solver"]["correct"]) / len(seed_rows), 6
            ),
            "server_steps_verified": tier_steps,
            "detail_1bc3e281_compat_steps": tier_detail_compat,
            "pre_end_day_views_verified": tier_pre_end_days,
            "unsurfaced_leak_gap_steps_verified": tier_unsurfaced_steps,
            "live_solver_verified_count": solver_res["live_solver_verified_count"],
            "mismatch_count": len(tier_mismatches),
            "mismatches": tier_mismatches,
            "seeds": seed_rows,
        }

    opencode_edge_cases = {
        "flash_hard_episodes_verified": 0,
        "flash_hard_steps_verified": 0,
        "client_refused_unavailable_tool_count": 0,
        "client_refused_events": [],
        "client_truncated_output_count": 0,
        "client_truncated_events": [],
        "detail_1bc3e281_compat_steps_flash": 0,
        "mismatch_count": 0,
    }
    if flash_hard_path.is_file():
        flash_by_seed = load_jsonl_episodes_by_seed([flash_hard_path], seeds=EXPECTED_SEEDS)
        for seed in sorted(flash_by_seed):
            f_rep = replay_and_verify_episode(flash_by_seed[seed])
            opencode_edge_cases["flash_hard_episodes_verified"] += 1
            opencode_edge_cases["flash_hard_steps_verified"] += f_rep["server_step_count"]
            opencode_edge_cases["detail_1bc3e281_compat_steps_flash"] += f_rep["detail_compat_steps"]
            max_abs_diff = max(max_abs_diff, f_rep["score_abs_diff"])
            if not f_rep["parity_ok"]:
                opencode_edge_cases["mismatch_count"] += 1
            for ev in f_rep["client_refused_steps"]:
                opencode_edge_cases["client_refused_unavailable_tool_count"] += 1
                opencode_edge_cases["client_refused_events"].append(
                    {"tier": "hard", "seed": seed, "agent": f_rep["agent"], **ev}
                )
            for tev in f_rep["truncated_steps"]:
                opencode_edge_cases["client_truncated_output_count"] += 1
                opencode_edge_cases["client_truncated_events"].append(
                    {"tier": "hard", "seed": seed, "agent": f_rep["agent"], **tev}
                )

    bundle_audit = audit_arena_and_demo_bundles(
        root=root,
        known_verdicts=known_verdicts,
        skip_rel_paths={DEFAULT_OUT_REL},
    )

    s6 = featured_highlights.get("hard_seed_6", {}).get("post_end", {})
    s26 = featured_highlights.get("hard_seed_26", {}).get("post_end", {})
    featured_assertions_ok = (
        s6.get("true_mole") == "e34"
        and s6.get("gemini_final", {}).get("accused") == "e34"
        and s6.get("gemini_final", {}).get("correct") is True
        and s6.get("gemini_final", {}).get("final_day") == 6
        and abs(float(s6.get("gemini_final", {}).get("score", -9.0)) - 0.73) < PARITY_TOL
        and s6.get("solver_final", {}).get("accused") == "e34"
        and s6.get("solver_final", {}).get("final_day") == 6
        and abs(float(s6.get("solver_final", {}).get("score", -9.0)) - 0.71) < PARITY_TOL
        and s26.get("true_mole") == "e08"
        and s26.get("gemini_final", {}).get("accused") == "e04"
        and s26.get("gemini_final", {}).get("correct") is False
        and s26.get("gemini_final", {}).get("final_day") == 10
        and abs(float(s26.get("gemini_final", {}).get("score", 9.0)) - (-1.0)) < PARITY_TOL
        and s26.get("solver_final", {}).get("accused") == "e08"
        and s26.get("solver_final", {}).get("final_day") == 7
        and abs(float(s26.get("solver_final", {}).get("score", -9.0)) - 0.69) < PARITY_TOL
    )

    edge_assertions_ok = (
        opencode_edge_cases["client_refused_unavailable_tool_count"] == 1
        and opencode_edge_cases["client_truncated_output_count"] == 2
        and opencode_edge_cases["mismatch_count"] == 0
        and total_detail_compat > 0
    )

    all_ok = (
        total_gem_episodes == 60
        and total_gem_mismatches == 0
        and tier_reports["hard"]["mismatch_count"] == 0
        and tier_reports["medium"]["mismatch_count"] == 0
        and max_abs_diff < PARITY_TOL
        and featured_assertions_ok
        and edge_assertions_ok
        and bundle_audit["ok"]
    )

    return {
        "schema_version": "arena_duel_parity_v14.v1",
        "tiers_version": TIERS_VERSION,
        "agent": "opencode:google/gemini-4-carbon",
        "all_gates_passed": all_ok,
        "summary": {
            "gemini_carbon_episodes_verified": total_gem_episodes,
            "gemini_carbon_steps_verified": total_gem_steps,
            "paired_solver_episodes_verified": 60,
            "mismatch_count": (
                tier_reports["hard"]["mismatch_count"]
                + tier_reports["medium"]["mismatch_count"]
                + opencode_edge_cases["mismatch_count"]
            ),
            "max_abs_score_diff": max_abs_diff,
            "tolerance": PARITY_TOL,
            "client_refused_unavailable_tool_calls": opencode_edge_cases[
                "client_refused_unavailable_tool_count"
            ],
            "client_truncated_outputs_verified": opencode_edge_cases[
                "client_truncated_output_count"
            ],
            "detail_1bc3e281_compat_steps_carbon": total_detail_compat,
            "detail_1bc3e281_compat_steps_total": (
                total_detail_compat + opencode_edge_cases["detail_1bc3e281_compat_steps_flash"]
            ),
            "pre_end_day_views_verified": total_pre_end_days_checked,
            "unsurfaced_leak_gap_steps_verified": total_unsurfaced_gap_steps,
            "pre_end_hidden_truth_leaks": bundle_audit["pre_end_leak_count"],
            "featured_seeds_verified": featured_assertions_ok,
            "external_bundles_discovered": bundle_audit["bundle_files_discovered"],
            "external_bundles_ok": bundle_audit["ok"],
        },
        "featured_duel_seeds": featured_highlights,
        "featured_ai_duel_contracts": featured_contracts,
        "opencode_compatibility_proof": opencode_edge_cases,
        "bundle_autodiscovery": bundle_audit,
        "tiers": tier_reports,
    }


def canonical_artifact_projection(report: dict[str, Any]) -> dict[str, Any]:
    proj = dict(report)
    raw_summary = dict(report.get("summary") or {})
    raw_summary.pop("external_bundles_discovered", None)
    proj["summary"] = raw_summary
    raw_bundle = dict(report.get("bundle_autodiscovery") or {})
    proj["bundle_autodiscovery"] = {
        "dirs_checked": raw_bundle.get("dirs_checked"),
        "ok": raw_bundle.get("ok"),
        "parse_errors": raw_bundle.get("parse_errors"),
        "pre_end_leak_count": raw_bundle.get("pre_end_leak_count"),
        "pre_end_leaks": raw_bundle.get("pre_end_leaks"),
        "score_mismatch_count": raw_bundle.get("score_mismatch_count"),
        "score_mismatches": raw_bundle.get("score_mismatches"),
    }
    return proj


def serialize_report(report: dict[str, Any]) -> str:
    text = json.dumps(report, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n"
    if len(text.encode("utf-8")) <= MAX_ARTIFACT_BYTES:
        pretty = json.dumps(report, indent=1, sort_keys=True, ensure_ascii=True) + "\n"
        if len(pretty.encode("utf-8")) <= MAX_ARTIFACT_BYTES:
            return pretty
    return text


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Verify Canary Arena v1.4 Gemini transcript replay parity, SolverPolicy parity, and AiDuelPanel contracts."
    )
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--json", action="store_true", dest="emit_json")
    parser.add_argument("--live-solver-all", action="store_true")
    args = parser.parse_args(argv)

    root = args.root.resolve()
    out_path = args.out.resolve() if args.out is not None else (root / DEFAULT_OUT_REL)

    report = build_parity_report(root=root, live_solver_all=args.live_solver_all)
    rendered = serialize_report(report)
    byte_len = len(rendered.encode("utf-8"))

    if byte_len > MAX_ARTIFACT_BYTES:
        print(
            f"FAIL: serialized report is {byte_len} bytes (> {MAX_ARTIFACT_BYTES} limit)",
            file=sys.stderr,
        )
        return 1

    if args.check:
        if not report["all_gates_passed"]:
            if args.emit_json:
                sys.stdout.write(rendered)
            else:
                print("FAIL: parity or pre-end leak gate failed", file=sys.stderr)
            return 1
        if not out_path.is_file():
            print(f"FAIL: missing committed artifact {out_path}", file=sys.stderr)
            return 1
        existing_bytes = out_path.read_bytes()
        if len(existing_bytes) > MAX_ARTIFACT_BYTES:
            print(
                f"FAIL: {out_path} is {len(existing_bytes)} bytes (> {MAX_ARTIFACT_BYTES} limit)",
                file=sys.stderr,
            )
            return 1
        try:
            existing_obj = json.loads(existing_bytes.decode("utf-8"))
        except ValueError as exc:
            print(f"FAIL: {out_path} invalid JSON: {exc}", file=sys.stderr)
            return 1
        if canonical_artifact_projection(existing_obj) != canonical_artifact_projection(report):
            print(f"FAIL: {out_path} is out of sync with live replay verification", file=sys.stderr)
            return 1
        if args.emit_json:
            sys.stdout.write(rendered)
        else:
            s = report["summary"]
            print(
                f"OK: {s['gemini_carbon_episodes_verified']}/60 gemini-4-carbon + "
                f"{s['paired_solver_episodes_verified']}/60 solver episodes verified "
                f"(mismatches={s['mismatch_count']}, max_diff={s['max_abs_score_diff']:.1e}, "
                f"artifact={len(existing_bytes)}B)"
            )
        return 0

    if args.emit_json and args.out is None:
        sys.stdout.write(rendered)
        return 0 if report["all_gates_passed"] else 1

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(rendered, encoding="utf-8")

    if args.emit_json:
        sys.stdout.write(rendered)
    else:
        s = report["summary"]
        print(
            f"WROTE {out_path} ({byte_len} bytes <= {MAX_ARTIFACT_BYTES}): "
            f"gemini_eps={s['gemini_carbon_episodes_verified']}, "
            f"solver_eps={s['paired_solver_episodes_verified']}, "
            f"client_refused={s['client_refused_unavailable_tool_calls']}, "
            f"truncated={s['client_truncated_outputs_verified']}, "
            f"detail_compat={s['detail_1bc3e281_compat_steps_total']}, "
            f"pre_end_views={s['pre_end_day_views_verified']}, "
            f"mismatches={s['mismatch_count']}"
        )
    return 0 if report["all_gates_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
