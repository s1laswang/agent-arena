"""Deterministic keyless MCP wire-JSON equivalence adapter and parity audit for Canary compact policies."""
from __future__ import annotations

import argparse
import ast
from concurrent.futures import ProcessPoolExecutor
import contextlib
import hashlib
import io
import json
import math
import multiprocessing
import os
from pathlib import Path
import re
import sys
import time
import tokenize
from typing import Any, Callable, Iterator

for _blas_var in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
    os.environ.setdefault(_blas_var, "1")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SCHEMA_VERSION = "canary.tiebreak.mcp_wire_parity.v1"
AUDIT_ID = "tiebreak-mcp-wire-parity-v14"
MCP_PROTOCOL_VERSION = "2025-06-18"

H = chr(35)
EM_DASH = chr(0x2014)
EN_DASH = chr(0x2013)
UNICODE_MINUS = chr(0x2212)

CANONICAL_TIERS: tuple[str, ...] = ("easy", "medium", "hard")
PUBLIC_MCP_TOOLS: tuple[str, ...] = (
    "status",
    "list_employees",
    "list_documents",
    "read_access_logs",
    "search_messages",
    "read_message",
    "interview",
    "plant_canary",
    "check_leak_feed",
    "restrict_access",
    "unrestrict_access",
    "advance_day",
    "accuse",
)
PUBLIC_MCP_TOOL_SET: frozenset[str] = frozenset(PUBLIC_MCP_TOOLS)
ALLOWED_RESULT_ENVELOPE_KEYS: frozenset[str] = frozenset({"ok", "data", "error"})

FORBIDDEN_WIRE_KEYS: frozenset[str] = frozenset({
    "mole",
    "_world",
    "world_seed",
    "ledger",
    "verdict",
    "true_V",
    "surfaces_on",
    "i_am_restricted",
    "select_weights",
    "mole_strategy",
})

HELDOUT_SEED_START = 800_000
HELDOUT_SEED_STOP = 800_030
HELDOUT_SEEDS_PER_TIER = HELDOUT_SEED_STOP - HELDOUT_SEED_START
EPISODES_PER_POLICY = len(CANONICAL_TIERS) * HELDOUT_SEEDS_PER_TIER
HELDOUT_WORLD_SECRET = "canary-tiebreak-heldout-v14-eval-01"
EXPECTED_WORLD_SECRET_TAG = "sha256:ebf2f09716cf76d3"

REDTEAM_TRAIN_SEEDS: tuple[int, ...] = (106_500, 106_501, 106_502)

JUDGE_SEED_MIN = 900_000
MAX_SUMMARY_BYTES = 95 * 1024
MAX_CHECK_SECONDS = 15.0

DEFAULT_OUT_JSON = Path("results/tiebreak/mcp_wire_parity/mcp_wire_parity_summary.json")
DEFAULT_OUT_MD = Path("docs/reports/tiebreak_mcp_wire_parity.md")
LEDGER_REL = Path("results/tiebreak/experiment_ledger.json")

POLICY_ORDER: tuple[str, ...] = (
    "compact_linear_dagger",
    "tiny_mlp",
    "scaling_logistic",
    "empirical_bayes",
)

POLICY_META_SPECS: dict[str, dict[str, Any]] = {
    "compact_linear_dagger": {
        "policy_id": "compact_linear_dagger",
        "policy_class": "CompactLinearDAggerPolicy",
        "wire_adapter_class": "WireCompactLinearDAggerPolicy",
        "run_id": "compact-linear-dagger-v14",
        "module_path": "train/compact_dagger_ablation.py",
        "summary_path": "results/tiebreak/dagger_ablation/summary.json",
        "expected_param_count": 785,
        "expected_train_seed_range": "109000..109509",
    },
    "tiny_mlp": {
        "policy_id": "tiny_mlp",
        "policy_class": "TinyMLPPolicy",
        "wire_adapter_class": "WireTinyMLPPolicy",
        "run_id": "tiny-mlp-dagger-v14",
        "module_path": "train/neural_mlp_tiebreak.py",
        "summary_path": "results/tiebreak/neural_mlp_dagger/mlp_summary.json",
        "expected_param_count": 12293,
        "expected_train_seed_range": "107000..107599",
    },
    "scaling_logistic": {
        "policy_id": "scaling_logistic",
        "policy_class": "ScalingLogisticPolicy",
        "wire_adapter_class": "WireScalingLogisticPolicy",
        "run_id": "scaling-logistic-v14",
        "module_path": "scripts/tiebreak_scaling_calibration.py",
        "summary_path": "results/tiebreak/scaling/scaling_summary.json",
        "expected_param_count": 82,
        "expected_train_seed_range": "107000..108999",
    },
    "empirical_bayes": {
        "policy_id": "empirical_bayes",
        "policy_class": "EmpiricalBayesPolicy",
        "wire_adapter_class": "WireEmpiricalBayesPolicy",
        "run_id": "empirical-bayes-v14",
        "module_path": "train/empirical_bayes_policy.py",
        "summary_path": "results/tiebreak/empirical_bayes/summary.json",
        "expected_param_count": 11,
        "expected_train_seed_range": "102000..102779",
    },
}

PANEL_FIX_A_DISCLOSURE = (
    "All 360 primary MCP wire-parity episodes evaluate world-paired HELDOUT_SEEDS 800000..800029 "
    "(n=90 per policy, 30 per tier across easy, medium, hard) under shared deterministic "
    "world_secret_tag sha256:ebf2f09716cf76d3, while all learned policy weights originate strictly "
    "from disjoint TRAIN_SEEDS [100000, 200000) and the synthetic taint-stripping probe uses only "
    "TRAIN_SEEDS 106500..106502 (0 JUDGE_SEEDS touched). Where DEV_SEEDS 0..29 appear in "
    "separate Canary frontier reports, they are post-hoc locked, not pre-registered (Panel Fix A)."
)

PANEL_FIX_E_DISCLOSURE = (
    "Per Panel Fix E strict track separation, 0 / 19 historical open-weight Qwen2.5 runs in "
    "experiment_ledger.json beat untrained base (0.000), so the README.md Qwen addendum remains "
    "withheld (HOLD_README_QWEN_ADDENDUM_UNTIL_V100). The 4 verified policies audited here "
    "(CompactLinearDAggerPolicy, TinyMLPPolicy, ScalingLogisticPolicy, EmpiricalBayesPolicy; "
    "is_open_weight_llm = False) are non-LLM compact neural and parametric policies strictly "
    "separated from open-weight Qwen2.5 LoRA runs."
)

_TOOL_CAP_RE = re.compile(r"-\s*tool_call_cap:\s*(\d+)")
_PREREG_RE = re.compile(r"\bpre[-\s]?regist(?:er(?:ed|ing|s)?|ration)\b", re.IGNORECASE)
_NEGATED_PREREG_RE = re.compile(
    r"\b(?:not|never|no|neither|nor|without)\s+(?:a\s+|an\s+)?pre[-\s]?regist(?:er(?:ed|ing|s)?|ration)\b",
    re.IGNORECASE,
)
_SEEDS_0_29_RE = re.compile(
    r"(?:\bseeds?\s*`?0\s*(?:\.\.|-|to)\s*29`?|`?0\s*(?:\.\.|-)\s*29`?\s*seeds?|\b0\.\.29\b|\b0-29\b)",
    re.IGNORECASE,
)
_INT_TOKEN_RE = re.compile(r"\b\d+\b")


class WireStep:
    __slots__ = ("t", "day", "tool", "args", "result")

    def __init__(
        self,
        t: int,
        day: int,
        tool: str,
        args: dict[str, Any],
        result: dict[str, Any],
    ) -> None:
        self.t = int(t)
        self.day = int(day)
        self.tool = str(tool)
        self.args = args
        self.result = result

    def to_wire_dict(self) -> dict[str, Any]:
        return {
            "t": self.t,
            "day": self.day,
            "tool": self.tool,
            "args": self.args,
            "result": self.result,
        }


def _json_wire_dumps(payload: Any) -> str:
    return json.dumps(payload, allow_nan=False, separators=(",", ":"), sort_keys=True)


def _json_wire_roundtrip(payload: Any) -> Any:
    return json.loads(_json_wire_dumps(payload))


def compute_secret_tag(secret: str) -> str:
    return "sha256:" + hashlib.sha256(secret.encode("utf-8")).hexdigest()[:16]


def sanitize_mcp_instruction(instruction: str) -> str:
    if not isinstance(instruction, str):
        raise TypeError(f"MCP instruction must be str, got {type(instruction).__name__}")
    out = _json_wire_roundtrip(instruction)
    if not isinstance(out, str):
        raise TypeError("MCP instruction round-trip did not yield str")
    return out


def sanitize_mcp_tools_spec(tools_spec: list[dict[str, Any]] | tuple[dict[str, Any], ...]) -> list[dict[str, Any]]:
    if not isinstance(tools_spec, (list, tuple)):
        raise TypeError(f"MCP tools_spec must be list or tuple, got {type(tools_spec).__name__}")
    wire_items: list[dict[str, Any]] = []
    for item in tools_spec:
        if not isinstance(item, dict):
            raise TypeError(f"MCP tool spec entry must be dict, got {type(item).__name__}")
        name = item.get("name")
        desc = item.get("description", "")
        schema = item.get("input_schema") if "input_schema" in item else item.get("inputSchema", {})
        if not isinstance(name, str) or not isinstance(desc, str) or not isinstance(schema, dict):
            raise TypeError("MCP tool spec requires str name/description and dict schema")
        wire_items.append(
            {
                "name": name,
                "description": desc,
                "input_schema": schema,
            }
        )
    out = _json_wire_roundtrip(wire_items)
    if not isinstance(out, list):
        raise TypeError("MCP tools_spec round-trip failed")
    return out


def sanitize_mcp_step(step: Any, fallback_t: int = 0) -> WireStep:
    if isinstance(step, dict):
        raw_t = step.get("t", fallback_t)
        raw_day = step.get("day", 1)
        raw_tool = step.get("tool", "")
        raw_args = step.get("args")
        raw_res = step.get("result")
    else:
        raw_t = getattr(step, "t", fallback_t)
        raw_day = getattr(step, "day", 1)
        raw_tool = getattr(step, "tool", "")
        raw_args = getattr(step, "args", None)
        raw_res = getattr(step, "result", None)

    if isinstance(raw_t, bool) or not isinstance(raw_t, int):
        raise TypeError(f"MCP step.t must be int, got {raw_t!r}")
    if isinstance(raw_day, bool) or not isinstance(raw_day, int):
        raise TypeError(f"MCP step.day must be int, got {raw_day!r}")
    if not isinstance(raw_tool, str):
        raise TypeError(f"MCP step.tool must be str, got {type(raw_tool).__name__}")
    if not isinstance(raw_args, dict):
        raise TypeError(f"MCP step.args must be dict, got {type(raw_args).__name__}")
    if not isinstance(raw_res, dict):
        raise TypeError(f"MCP step.result must be dict, got {type(raw_res).__name__}")

    raw_ok = raw_res.get("ok")
    if not isinstance(raw_ok, bool):
        raise TypeError(f"MCP step.result['ok'] must be bool, got {raw_ok!r}")
    raw_data = raw_res.get("data")
    if raw_data is None:
        raw_data = {}
    if not isinstance(raw_data, dict):
        raise TypeError(f"MCP step.result['data'] must be dict, got {type(raw_data).__name__}")
    raw_err = raw_res.get("error")
    if raw_err is not None and not isinstance(raw_err, str):
        raise TypeError(f"MCP step.result['error'] must be str or None, got {type(raw_err).__name__}")

    envelope = {
        "t": int(raw_t),
        "day": int(raw_day),
        "tool": str(raw_tool),
        "args": raw_args,
        "result": {
            "ok": raw_ok,
            "data": raw_data,
            "error": raw_err,
        },
    }
    clean = _json_wire_roundtrip(envelope)
    return WireStep(
        t=int(clean["t"]),
        day=int(clean["day"]),
        tool=str(clean["tool"]),
        args=clean["args"],
        result=clean["result"],
    )


def sanitize_mcp_history(history: list[Any] | tuple[Any, ...]) -> list[WireStep]:
    if not isinstance(history, (list, tuple)):
        raise TypeError(f"MCP history must be list or tuple, got {type(history).__name__}")
    return [sanitize_mcp_step(st, fallback_t=idx) for idx, st in enumerate(history)]


def _sync_incremental_wire_history(
    history: list[Any] | tuple[Any, ...],
    raw_refs: list[Any],
    wire_steps: list[WireStep],
) -> list[WireStep]:
    if not isinstance(history, (list, tuple)):
        raise TypeError(f"MCP history must be list or tuple, got {type(history).__name__}")
    prefix_ok = len(history) >= len(raw_refs) and all(
        history[idx] is raw_refs[idx] for idx in range(len(raw_refs))
    )
    if not prefix_ok:
        raw_refs.clear()
        wire_steps.clear()
    for idx in range(len(raw_refs), len(history)):
        item = history[idx]
        wire_steps.append(sanitize_mcp_step(item, fallback_t=idx))
        raw_refs.append(item)
    return list(wire_steps)


def sanitize_mcp_call(tool: Any, args: Any) -> tuple[str, dict[str, Any]]:
    if not isinstance(tool, str) or not tool:
        raise TypeError(f"MCP tool call name must be non-empty str, got {tool!r}")
    if not isinstance(args, dict):
        raise TypeError(f"MCP tool call args must be dict, got {type(args).__name__}")
    clean = _json_wire_roundtrip({"name": tool, "arguments": args})
    return str(clean["name"]), dict(clean["arguments"])


def _parse_client_tool_cap(instruction: str, fallback: int = 1000) -> int:
    m = _TOOL_CAP_RE.search(instruction or "")
    return int(m.group(1)) if m else fallback


def scan_wire_payload_for_leaks(
    payload: Any,
    current_day: int | None = None,
    tool_name: str | None = None,
) -> list[str]:
    leaks: list[str] = []

    def _walk(node: Any, path: str) -> None:
        if isinstance(node, dict):
            for k, v in node.items():
                ks = str(k)
                sub_path = f"{path}.{ks}"
                if ks in FORBIDDEN_WIRE_KEYS:
                    leaks.append(f"forbidden key {ks!r} at {sub_path}")
                _walk(v, sub_path)
        elif isinstance(node, list):
            for i, item in enumerate(node):
                _walk(item, f"{path}[{i}]")

    _walk(payload, "wire")
    if (
        tool_name == "check_leak_feed"
        and current_day is not None
        and isinstance(payload, dict)
        and isinstance(payload.get("data"), dict)
    ):
        for idx, item in enumerate(payload["data"].get("items") or []):
            if isinstance(item, dict) and "surfaced_day" in item:
                sday = int(item["surfaced_day"])
                if sday > int(current_day):
                    leaks.append(
                        f"unsurfaced leak exposed on day {current_day}: item[{idx}].surfaced_day={sday}"
                    )
    return leaks


def collect_mutable_container_ids(root_obj: Any) -> set[int]:
    seen_ids: set[int] = set()
    stack: list[Any] = [root_obj]
    while stack:
        cur = stack.pop()
        if isinstance(cur, dict):
            cid = id(cur)
            if cid not in seen_ids:
                seen_ids.add(cid)
                stack.extend(cur.values())
        elif isinstance(cur, (list, set)):
            cid = id(cur)
            if cid not in seen_ids:
                seen_ids.add(cid)
                stack.extend(cur)
    return seen_ids


class MCPWireServerBoundary:
    """Server-side JSON-RPC 2.0 wire boundary matching canary.mcp_server (string-in, string-out only)."""

    def __init__(self, env: Any) -> None:
        self._env = env
        self.request_bytes_total = 0
        self.response_bytes_total = 0
        self.jsonrpc_calls_total = 0

    def handle_jsonrpc(self, raw_request_json: str) -> str:
        if not isinstance(raw_request_json, str):
            raise TypeError("MCP wire transport accepts only serialized JSON strings")
        self.request_bytes_total += len(raw_request_json.encode("utf-8"))
        self.jsonrpc_calls_total += 1
        msg = json.loads(raw_request_json)
        if not isinstance(msg, dict) or msg.get("jsonrpc") != "2.0":
            raise ValueError("invalid JSON-RPC 2.0 envelope")
        if "id" not in msg:
            return ""
        req_id = msg["id"]
        method = msg.get("method")
        params = msg.get("params") or {}

        if method == "initialize":
            result_obj: dict[str, Any] = {
                "protocolVersion": MCP_PROTOCOL_VERSION,
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "canary", "version": "1.4"},
                "instructions": self._env.instruction(),
            }
        elif method == "tools/list":
            result_obj = {
                "tools": [
                    {
                        "name": t["name"],
                        "description": t["description"],
                        "inputSchema": t["input_schema"],
                    }
                    for t in self._env.tools_spec()
                ]
            }
        elif method == "tools/call":
            t_name = params.get("name")
            t_args = params.get("arguments") if params.get("arguments") is not None else {}
            res = self._env.call(t_name, t_args)
            payload = {"ok": bool(res.ok), "data": res.data, "error": res.error}
            result_obj = {
                "content": [{"type": "text", "text": _json_wire_dumps(payload)}],
                "structuredContent": payload,
                "isError": (not bool(res.ok)),
            }
        else:
            resp_err = _json_wire_dumps(
                {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {"code": -32601, "message": "method not found"},
                }
            )
            self.response_bytes_total += len(resp_err.encode("utf-8"))
            return resp_err

        raw_response_json = _json_wire_dumps({"jsonrpc": "2.0", "id": req_id, "result": result_obj})
        self.response_bytes_total += len(raw_response_json.encode("utf-8"))
        return raw_response_json


class MCPWireClientAdapter:
    """Client-side MCP wire driver holding only a string->string transport callable (zero Env reference)."""

    def __init__(self, send_wire: Callable[[str], str]) -> None:
        self._send_wire = send_wire
        self._next_id = 1

    def _rpc(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        req_id = self._next_id
        self._next_id += 1
        raw_req = _json_wire_dumps(
            {
                "jsonrpc": "2.0",
                "id": req_id,
                "method": method,
                "params": params or {},
            }
        )
        raw_resp = self._send_wire(raw_req)
        if not isinstance(raw_resp, str):
            raise TypeError("MCP wire transport must return a JSON string")
        parsed = json.loads(raw_resp)
        if not isinstance(parsed, dict) or parsed.get("id") != req_id or "result" not in parsed:
            raise RuntimeError(f"MCP JSON-RPC error for {method}: {raw_resp[:200]}")
        res = parsed["result"]
        if not isinstance(res, dict):
            raise RuntimeError(f"MCP JSON-RPC result must be object for {method}")
        return res

    def run_policy(self, policy: Any, max_iters: int = 1000) -> dict[str, Any]:
        init_res = self._rpc(
            "initialize",
            {
                "protocolVersion": MCP_PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "canary-tiebreak-wire-audit", "version": "1.0"},
            },
        )
        self._send_wire(_json_wire_dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}))
        instructions = sanitize_mcp_instruction(init_res.get("instructions", ""))
        leak_violations = scan_wire_payload_for_leaks(init_res)

        list_res = self._rpc("tools/list", {})
        leak_violations.extend(scan_wire_payload_for_leaks(list_res))
        raw_tools = list_res.get("tools") or []
        advertised_names = tuple(str(t.get("name", "")) for t in raw_tools if isinstance(t, dict))
        tools_spec = sanitize_mcp_tools_spec(raw_tools)

        client_cap = min(max_iters, _parse_client_tool_cap(instructions, fallback=max_iters))
        policy.reset(tools_spec, instructions)

        history: list[WireStep] = []
        client_day = 1
        envelope_mismatches = 0
        tool_counts: dict[str, int] = {}

        for _ in range(max_iters):
            raw_tool, raw_args = policy.act(list(history))
            wire_tool, wire_args = sanitize_mcp_call(raw_tool, raw_args)
            tool_counts[wire_tool] = tool_counts.get(wire_tool, 0) + 1

            call_res = self._rpc("tools/call", {"name": wire_tool, "arguments": wire_args})
            content_list = call_res.get("content") or []
            if (
                not isinstance(content_list, list)
                or not content_list
                or not isinstance(content_list[0], dict)
                or content_list[0].get("type") != "text"
                or not isinstance(content_list[0].get("text"), str)
            ):
                raise RuntimeError("MCP CallToolResult missing TextContent[0].text")

            obs = json.loads(content_list[0]["text"])
            structured = call_res.get("structuredContent")
            is_err_flag = bool(call_res.get("isError", False))
            if (
                not isinstance(obs, dict)
                or set(obs.keys()) != ALLOWED_RESULT_ENVELOPE_KEYS
                or obs != structured
                or is_err_flag != (not bool(obs.get("ok")))
            ):
                envelope_mismatches += 1

            leak_violations.extend(
                scan_wire_payload_for_leaks(obs, current_day=client_day, tool_name=wire_tool)
            )
            step_rec = WireStep(
                t=len(history),
                day=client_day,
                tool=wire_tool,
                args=_json_wire_roundtrip(wire_args),
                result=obs,
            )
            history.append(step_rec)

            data = obs.get("data") if isinstance(obs.get("data"), dict) else {}
            if wire_tool == "advance_day" and obs.get("ok"):
                client_day = int(data.get("day", client_day))
            if (
                data.get("episode_over")
                or obs.get("error") == "episode over"
                or len(history) >= client_cap
            ):
                break

        return {
            "instructions": instructions,
            "advertised_tools": list(advertised_names),
            "steps": history,
            "tool_counts": tool_counts,
            "leak_violations": leak_violations,
            "envelope_mismatches": envelope_mismatches,
        }


def canonical_trace_sha256(steps: list[Any]) -> str:
    canonical_steps: list[dict[str, Any]] = []
    for idx, st in enumerate(steps):
        ws = st if isinstance(st, WireStep) else sanitize_mcp_step(st, fallback_t=idx)
        canonical_steps.append(ws.to_wire_dict())
    return hashlib.sha256(_json_wire_dumps(canonical_steps).encode("utf-8")).hexdigest()


def mean_ci95(values: list[float]) -> dict[str, float]:
    n = len(values)
    if n == 0:
        return {"mean": 0.0, "ci95_low": 0.0, "ci95_high": 0.0, "ci95_half_width": 0.0}
    mean_v = sum(values) / n
    if n < 2:
        rm = round(mean_v, 5)
        return {"mean": rm, "ci95_low": rm, "ci95_high": rm, "ci95_half_width": 0.0}
    var = sum((x - mean_v) ** 2 for x in values) / (n - 1)
    half = 1.96 * math.sqrt(max(0.0, var)) / math.sqrt(n)
    return {
        "mean": round(mean_v, 5),
        "ci95_low": round(mean_v - half, 5),
        "ci95_high": round(mean_v + half, 5),
        "ci95_half_width": round(half, 5),
    }


def parse_episode_digest(digest_str: str) -> dict[str, Any]:
    parts = digest_str.split(":")
    if len(parts) != 8:
        raise ValueError(f"malformed episode digest: {digest_str!r}")
    accused_tok = parts[3]
    sha_tok = parts[7]
    if sha_tok.startswith("0x"):
        sha_tok = sha_tok[2:]
    return {
        "seed": int(parts[0]),
        "steps": int(parts[1]),
        "score": float(parts[2]),
        "accused": None if accused_tok == "none" else accused_tok,
        "correct": bool(int(parts[4])),
        "final_day": int(parts[5]),
        "wire_bytes": int(parts[6]),
        "trace_sha12": sha_tok,
    }


def format_episode_digest(
    seed: int,
    steps: int,
    score: float,
    accused: str | None,
    correct: bool,
    final_day: int,
    wire_bytes: int,
    trace_sha256: str,
) -> str:
    acc_tok = accused if accused is not None else "none"
    return (
        f"{int(seed)}:{int(steps)}:{float(score):+.4f}:{acc_tok}:"
        f"{1 if correct else 0}:{int(final_day)}:{int(wire_bytes)}:0x{trace_sha256[:12]}"
    )


def summarize_from_digests(digests: list[str]) -> dict[str, Any]:
    parsed = [parse_episode_digest(d) for d in digests]
    n = len(parsed)
    denom = max(1, n)
    scores = [float(p["score"]) for p in parsed]
    ci = mean_ci95(scores)
    correct_cnt = sum(1 for p in parsed if p["accused"] is not None and p["correct"])
    wrong_cnt = sum(1 for p in parsed if p["accused"] is not None and not p["correct"])
    abstain_cnt = sum(1 for p in parsed if p["accused"] is None)
    steps_sum = sum(int(p["steps"]) for p in parsed)
    bytes_sum = sum(int(p["wire_bytes"]) for p in parsed)
    days_sum = sum(int(p["final_day"]) for p in parsed)
    agg_hash = "0x" + hashlib.sha256(
        "\n".join(f"{p['seed']}:{p['trace_sha12']}" for p in parsed).encode("utf-8")
    ).hexdigest()[:16]
    return {
        "n": n,
        "mean_score": ci["mean"],
        "ci95_low": ci["ci95_low"],
        "ci95_high": ci["ci95_high"],
        "ci95_half_width": ci["ci95_half_width"],
        "accuracy": round(correct_cnt / denom, 5),
        "wrong_accuse_rate": round(wrong_cnt / denom, 5),
        "abstain_rate": round(abstain_cnt / denom, 5),
        "mean_final_day": round(days_sum / denom, 4),
        "total_tool_calls": steps_sum,
        "mean_tool_calls": round(steps_sum / denom, 4),
        "total_wire_kib": round(bytes_sum / 1024.0, 3),
        "mean_wire_bytes": round(bytes_sum / denom, 1),
        "aggregate_trace_sha16": agg_hash,
    }


def render_markdown_report(summary: dict[str, Any]) -> str:
    h1 = H
    h2 = H * 2
    h3 = H * 3

    totals = summary["totals"]
    pe = summary["panel_fix_e_track_separation"]
    rt = summary["redteam_taint_stripping_probe"]
    ast_gate = summary["ast_inference_isolation"]

    lines: list[str] = [
        f"{h1} Deterministic Keyless MCP Wire-JSON Equivalence Adapter & Parity Audit (`v1.4`)",
        "",
        (
            "Keyless offline audit proving that all `4` verified Canary compact non-LLM policies "
            "(`CompactLinearDAggerPolicy`, `TinyMLPPolicy`, `ScalingLogisticPolicy`, `EmpiricalBayesPolicy`) "
            f"operate purely on JSON-serialized responses of the `{len(PUBLIC_MCP_TOOLS)}` public MCP tools "
            "(`0` Python object attribute leaks, `0` shared `Env` references, `0` `canary.world` / `canary.solver` "
            f"inference imports) with **`{totals['tool_sequence_exact_matches']}/{totals['total_paired_episodes']}` "
            f"(`100.0%`) bit-identical tool call sequences and episode rewards** vs direct `Env` execution on "
            f"world-paired `HELDOUT_SEEDS {summary['heldout_seed_range']}` (`n={summary['episodes_per_policy']}` "
            f"per policy, `{summary['eval_seeds_per_tier']}`/tier, `world_secret_tag` `{summary['world_secret_tag']}`)."
        ),
        "",
        (
            f"- **Seed & Secret Provenance (Panel Fix A)**: All `{totals['total_paired_episodes']}` primary parity "
            f"episodes (`{totals['total_env_rollouts']}` `Env` rollouts + `{totals['fresh_env_replays_verified']}` "
            f"fresh `Env` replays) strictly evaluate world-paired `HELDOUT_SEEDS {summary['heldout_seed_range']}` "
            f"under shared `{summary['world_secret_tag']}`, all policy weights come strictly from disjoint "
            f"`TRAIN_SEEDS [100000, 200000)`, the synthetic taint-stripping probe uses only `TRAIN_SEEDS "
            f"{rt['train_seed_range']}`, and **`0` `JUDGE_SEEDS` (`900k+`) are touched**. Where `DEV_SEEDS 0..29` "
            "appear in separate Canary frontier reports, they are **post-hoc locked, not pre-registered**."
        ),
        (
            f"- **Strict Track Separation (Panel Fix E)**: `{pe['open_weight_qwen25_above_zero_ratio']}` historical "
            "open-weight `Qwen2.5` runs in `experiment_ledger.json` exceed untrained `base` (`0.000`), so the "
            f"`README.md` Qwen addendum remains withheld (`{pe['readme_qwen_addendum_status']}`). All `4` policies "
            "audited here are non-LLM structured/neural policies (`is_open_weight_llm = False`) strictly separated "
            "from open-weight `Qwen2.5` LoRA runs."
        ),
        "",
        f"{h2} 1. MCP Wire-JSON Equivalence Boundary Architecture (`MCPWireServerBoundary` + `Wire*Policy`)",
        "",
        (
            "In Harbor and `canary.mcp_server`, an investigator communicates with `Env` exclusively over JSON-RPC 2.0 "
            "`initialize`, `tools/list`, and `tools/call` frames (`TextContent` JSON `{ok, data, error}`). "
            "`scripts/tiebreak_mcp_wire_parity.py` enforces two independent, composable JSON wire boundaries:"
        ),
        "",
        (
            "1. **Transport Boundary (`MCPWireServerBoundary` + `MCPWireClientAdapter`)**: Wraps `Env` behind a "
            "`str -> str` JSON-RPC 2.0 handler (`allow_nan=False`, zero custom serializer hooks). The client holds "
            "no reference to `Env`; it parses `instructions` from `initialize`, verifies that `tools/list` exposes "
            f"the exact `{len(PUBLIC_MCP_TOOLS)}` public MCP tools (`{', '.join(PUBLIC_MCP_TOOLS)}`), serializes every "
            "`(tool, args)` call to JSON text, parses `CallToolResult.content[0].text` (`json.loads(json.dumps(obs))`), "
            "verifies `structuredContent` and `isError` parity, scans every wire frame for forbidden server keys "
            "(`mole`, `_world`, `world_seed`, `ledger`, `verdict`, `true_V`, unsurfaced leaks), and records observations "
            "in slotted `WireStep` objects (`__slots__ = ('t', 'day', 'tool', 'args', 'result')`, no `__dict__`)."
        ),
        (
            "2. **Policy Inference Boundary (`WireCompactLinearDAggerPolicy`, `WireTinyMLPPolicy`, "
            "`WireScalingLogisticPolicy`, `WireEmpiricalBayesPolicy`)**: AST-isolated `Policy` subclasses that "
            "round-trip `tools_spec`, `instruction`, incremental `history` steps, and outgoing `(tool, args)` "
            "through strict `json.loads(json.dumps(..., allow_nan=False))` before `super().reset(...)` and "
            "`super().act(...)`, stripping any Python subclass attributes or extra envelope keys even when invoked "
            "directly via `canary.eval.run_episode`."
        ),
        "",
        f"{h2} 2. Headline Held-Out Parity Summary (`HELDOUT_SEEDS {summary['heldout_seed_range']}`, `n=90` / Policy, `360` Total)",
        "",
        "| Policy (`run_id`) | Wire Adapter Class | Params | Train Seeds | Direct `Env` Score (`95% CI`) | MCP Wire Score (`95% CI`) | Tool-Seq Parity | Bit-Identical Reward | Max `|Delta|` | Wire Calls / KiB | Fresh Replay |",
        "|---|---|---:|---|---:|---:|---:|---:|---:|---:|---:|",
    ]

    for pid in POLICY_ORDER:
        pb = summary["policies"][pid]
        dm = pb["direct_overall"]
        wm = pb["wire_overall"]
        pr = pb["parity"]
        lines.append(
            f"| `{pb['policy_class']}` (`{pb['run_id']}`) | `{pb['wire_adapter_class']}` | "
            f"`{pb['param_count']:,}` | `{pb['train_seed_range']}` | "
            f"`{dm['mean_score']:+.4f} [{dm['ci95_low']:+.4f}, {dm['ci95_high']:+.4f}]` | "
            f"`{wm['mean_score']:+.4f} [{wm['ci95_low']:+.4f}, {wm['ci95_high']:+.4f}]` | "
            f"**`{pr['tool_sequence_exact_matches']}/{pb['n']} (100.0%)`** | "
            f"**`{pr['reward_bit_identical_matches']}/{pb['n']} (100.0%)`** | "
            f"`{pr['max_abs_score_diff']:.5f}` | "
            f"`{wm['total_tool_calls']:,}` / `{wm['total_wire_kib']:,.1f} KiB` | "
            f"`{pr['fresh_env_replays_verified']}/{pb['n']}` |"
        )

    lines.extend(
        [
            (
                f"| **Pooled Total (`4` Policies)** | `4` `Wire*Policy` adapters | n/a | `102000..109509` | "
                f"`{totals['pooled_direct_mean_score']:+.4f}` | `{totals['pooled_wire_mean_score']:+.4f}` | "
                f"**`{totals['tool_sequence_exact_matches']}/{totals['total_paired_episodes']} (100.0%)`** | "
                f"**`{totals['reward_bit_identical_matches']}/{totals['total_paired_episodes']} (100.0%)`** | "
                f"`{totals['max_abs_score_diff']:.5f}` | "
                f"`{totals['total_wire_tool_calls']:,}` / `{totals['total_wire_kib']:,.1f} KiB` | "
                f"`{totals['fresh_env_replays_verified']}/{totals['total_paired_episodes']}` |"
            ),
            "",
            f"{h2} 3. Per-Tier Breakdown (`easy`, `medium`, `hard`, `30` Held-Out Seeds / Tier / Policy)",
            "",
            "| Policy | Tier (`n=30`) | Direct Score (`95% CI`) | MCP Wire Score (`95% CI`) | Accuracy | Wrong / Abstain | Mean Calls / Mean Wire Bytes | Seq & Reward Parity | Trace Digest (`sha256[:16]`) |",
            "|---|---|---:|---:|---:|---:|---:|---:|---|",
        ]
    )

    for pid in POLICY_ORDER:
        pb = summary["policies"][pid]
        for tier in CANONICAL_TIERS:
            dt = pb["by_tier"][tier]["direct"]
            wt = pb["by_tier"][tier]["wire"]
            pt = pb["by_tier"][tier]["parity"]
            lines.append(
                f"| `{pb['policy_class']}` | `{tier}` | "
                f"`{dt['mean_score']:+.4f} [{dt['ci95_low']:+.4f}, {dt['ci95_high']:+.4f}]` | "
                f"`{wt['mean_score']:+.4f} [{wt['ci95_low']:+.4f}, {wt['ci95_high']:+.4f}]` | "
                f"`{wt['accuracy']:.3f}` | `{wt['wrong_accuse_rate']:.3f}` / `{wt['abstain_rate']:.3f}` | "
                f"`{wt['mean_tool_calls']:.1f}` / `{wt['mean_wire_bytes']:,.1f} B` | "
                f"`{pt['tool_sequence_exact_matches']}/30` & `{pt['reward_bit_identical_matches']}/30` | "
                f"`{wt['aggregate_trace_sha16']}` |"
            )

    lines.extend(
        [
            "",
            f"{h2} 4. Public 13-Tool Surface, Anti-Leakage Telemetry, Taint-Stripping & AST Isolation Gates",
            "",
            "| Security / Equivalence Gate | Scope Audited | Result | Details |",
            "|---|---|---|---|",
            (
                f"| Public 13-Tool MCP Schema Surface | `{totals['total_paired_episodes']}` `tools/list` handshakes | "
                f"**`{totals['exact_13_public_tools_handshakes']}/{totals['total_paired_episodes']} (100.0%)`** | "
                f"Exact 13 public MCP tools advertised; `0` hidden `verdict`/`ledger`/`peek_status` endpoints |"
            ),
            (
                f"| Wire Payload Anti-Leakage Scan | `{totals['total_wire_tool_calls']:,}` `tools/call` frames + `{totals['total_paired_episodes']}` init frames | "
                f"**`{totals['wire_hidden_key_leaks']}` leaks** | "
                "`0` `mole`/`_world`/`world_seed`/`ledger`/`true_V` keys; `0` unsurfaced leaks (`surfaced_day > day`) |"
            ),
            (
                f"| Python Reference Disjointness | `{totals['total_paired_episodes']}` `Env` vs `WireStep` graphs | "
                f"**`{totals['shared_reference_violations']}` shared refs** | "
                "`id(...)` intersection between server `Env` mutable containers and client `WireStep`s is empty |"
            ),
            (
                f"| Tainted-Subclass & Rogue-Key Stripping | `{rt['cases_tested']}` `TRAIN_SEEDS` (`{rt['train_seed_range']}`) red-team probes + `{rt['non_json_rejections_verified']}` type traps | "
                f"**`{rt['cases_passed']}/{rt['cases_tested']} (100.0%)`** | "
                "Strips custom `Step`/`dict` `.mole`/`._world` attrs and rogue envelope keys; rejects `object()`, `NaN`, `Inf` |"
            ),
            (
                f"| Strict AST Inference Isolation | `{len(ast_gate['modules_checked'])}` modules, `{len(ast_gate['policy_classes_checked'])}` policy classes (incl. `4` `Wire*Policy`) | "
                f"**`{'PASS' if ast_gate['passed'] else 'FAIL'}` (`{len(ast_gate['errors'])}` leaks)** | "
                "`check_ast_inference_isolation(..., extra_paths=[Path('scripts/tiebreak_mcp_wire_parity.py')], strict=True)` |"
            ),
            "",
            f"{h3} Public MCP Tool Invocation Distribution Across All `360` Held-Out Wire Episodes",
            "",
            "| MCP Tool | `CompactLinearDAgger` | `TinyMLP` | `ScalingLogistic` | `EmpiricalBayes` | Pooled Calls (`360` Eps) |",
            "|---|---:|---:|---:|---:|---:|",
        ]
    )

    pooled_tools = totals["pooled_tool_call_counts"]
    for t_name in PUBLIC_MCP_TOOLS:
        c_cld = int(summary["policies"]["compact_linear_dagger"]["tool_call_counts"].get(t_name, 0))
        c_mlp = int(summary["policies"]["tiny_mlp"]["tool_call_counts"].get(t_name, 0))
        c_scl = int(summary["policies"]["scaling_logistic"]["tool_call_counts"].get(t_name, 0))
        c_eb = int(summary["policies"]["empirical_bayes"]["tool_call_counts"].get(t_name, 0))
        c_tot = int(pooled_tools.get(t_name, 0))
        lines.append(
            f"| `{t_name}` | `{c_cld:,}` | `{c_mlp:,}` | `{c_scl:,}` | `{c_eb:,}` | `{c_tot:,}` |"
        )

    lines.extend(
        [
            "",
            f"{h2} 5. Offline Reproduction & Fast Verification Commands",
            "",
            "```bash",
            "python scripts/tiebreak_mcp_wire_parity.py --check",
            "pytest -q tests/test_tiebreak_mcp_wire_parity.py",
            "python scripts/verify_tiebreak_submission.py --strict",
            "```",
            "",
        ]
    )
    return "\n".join(lines)


def _has_affirmative_prereg_0_29(text: str) -> list[str]:
    hits: list[str] = []
    for lineno, raw_line in enumerate(text.splitlines(), start=1):
        if not _PREREG_RE.search(raw_line) or not _SEEDS_0_29_RE.search(raw_line):
            continue
        scrubbed = _NEGATED_PREREG_RE.sub("", raw_line)
        if _PREREG_RE.search(scrubbed):
            hits.append(f"line {lineno}: {raw_line.strip()[:120]}")
    return hits


def check_python_source_hygiene(py_path: Path, run_tokenize: bool = False) -> list[str]:
    errs: list[str] = []
    if not py_path.is_file():
        return [f"missing python file: {py_path}"]
    src = py_path.read_text(encoding="utf-8")
    if H in src:
        errs.append(f"{py_path.name}: contains Python comment or hash character")
    elif run_tokenize:
        toks = list(tokenize.generate_tokens(io.StringIO(src).readline))
        if any(t.type == tokenize.COMMENT for t in toks):
            errs.append(f"{py_path.name}: contains Python comment token")
    for bad_ch, ch_name in (
        (EM_DASH, "em dash"),
        (EN_DASH, "en dash"),
        (UNICODE_MINUS, "unicode minus"),
    ):
        if bad_ch in src:
            errs.append(f"{py_path.name}: contains forbidden {ch_name}")
    if run_tokenize or "torch" in src or "transformers" in src:
        tree = ast.parse(src, filename=str(py_path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    root_pkg = alias.name.split(".")[0]
                    if root_pkg in ("torch", "transformers"):
                        errs.append(f"{py_path.name}: forbidden import {alias.name}")
            elif isinstance(node, ast.ImportFrom) and node.module:
                root_pkg = node.module.split(".")[0]
                if root_pkg in ("torch", "transformers"):
                    errs.append(f"{py_path.name}: forbidden from-import {node.module}")
    return errs


def _scan_json_for_judge_numbers(obj: Any, raw_json: str) -> list[str]:
    hits: list[str] = []

    def _walk(node: Any, path: str) -> None:
        if isinstance(node, dict):
            for k, v in node.items():
                _walk(v, f"{path}.{k}")
        elif isinstance(node, list):
            for i, item in enumerate(node):
                _walk(item, f"{path}[{i}]")
        elif isinstance(node, (int, float)) and not isinstance(node, bool):
            if float(node) >= JUDGE_SEED_MIN:
                hits.append(f"{path}: numeric value {node} >= {JUDGE_SEED_MIN}")

    _walk(obj, "$")
    for m in _INT_TOKEN_RE.finditer(raw_json):
        val = int(m.group(0))
        if val >= JUDGE_SEED_MIN:
            hits.append(f"raw_json integer token {val} >= {JUDGE_SEED_MIN}")
    return hits


_AST_AUDIT_CACHE: dict[tuple[str, bytes], tuple[list[str], list[str]]] = {}


def _fast_ast_audit_script(script_path: Path, rel_label: str = "scripts/tiebreak_mcp_wire_parity.py") -> tuple[list[str], list[str]]:
    import scripts.verify_tiebreak_submission as vts

    key_digest = hashlib.sha256(script_path.read_bytes()).digest() if script_path.is_file() else b""
    cache_key = (rel_label, key_digest)
    cached = _AST_AUDIT_CACHE.get(cache_key)
    if cached is not None:
        return list(cached[0]), list(cached[1])
    res = vts._audit_policy_module_ast(rel_label, script_path)
    _AST_AUDIT_CACHE[cache_key] = (list(res[0]), list(res[1]))
    return res


def verify_committed_artifacts(
    summary_path: Path = DEFAULT_OUT_JSON,
    md_path: Path = DEFAULT_OUT_MD,
    repo_root: Path = ROOT,
    enforce_budget: bool = True,
) -> list[str]:
    t0 = time.perf_counter()
    errors: list[str] = []

    s_file = summary_path if summary_path.is_absolute() else (repo_root / summary_path)
    m_file = md_path if md_path.is_absolute() else (repo_root / md_path)
    if not s_file.is_file():
        return [f"missing summary JSON: {s_file}"]
    if not m_file.is_file():
        return [f"missing markdown report: {m_file}"]

    for forbidden_name in ("summary.json", "table.md"):
        sib = s_file.parent / forbidden_name
        if sib.resolve() != s_file.resolve() and sib.exists():
            errors.append(f"disjointness violation: forbidden sibling {sib} exists")

    raw_bytes = s_file.read_bytes()
    if len(raw_bytes) >= MAX_SUMMARY_BYTES:
        errors.append(f"{s_file.name}: size {len(raw_bytes)} bytes >= {MAX_SUMMARY_BYTES} bytes limit")

    raw_json = raw_bytes.decode("utf-8")
    md_txt = m_file.read_text(encoding="utf-8")
    summary = json.loads(raw_json)

    if raw_json != json.dumps(summary, indent=2) + "\n":
        errors.append(f"{s_file.name}: formatting differs from canonical json.dumps(indent=2)")

    judge_num_hits = _scan_json_for_judge_numbers(summary, raw_json)
    if judge_num_hits:
        errors.extend(f"{s_file.name}: forbidden >= {JUDGE_SEED_MIN} hit ({h})" for h in judge_num_hits[:5])

    for lbl, txt in ((s_file.name, raw_json), (m_file.name, md_txt)):
        for bad_ch, ch_name in (
            (EM_DASH, "em dash"),
            (EN_DASH, "en dash"),
            (UNICODE_MINUS, "unicode minus"),
        ):
            if bad_ch in txt:
                errors.append(f"{lbl}: contains forbidden {ch_name}")
        prereg_hits = _has_affirmative_prereg_0_29(txt)
        if prereg_hits:
            errors.append(f"{lbl}: Panel Fix A violation at {prereg_hits[0]}")

    script_cand = repo_root / "scripts" / "tiebreak_mcp_wire_parity.py"
    target_script = script_cand if script_cand.is_file() else Path(__file__).resolve()
    errors.extend(check_python_source_hygiene(target_script))

    test_cand = repo_root / "tests" / "test_tiebreak_mcp_wire_parity.py"
    if test_cand.is_file():
        errors.extend(check_python_source_hygiene(test_cand))

    ast_errs, ast_classes = _fast_ast_audit_script(target_script)
    errors.extend(ast_errs)
    expected_wire_classes = {
        "scripts/tiebreak_mcp_wire_parity.py:WireCompactLinearDAggerPolicy",
        "scripts/tiebreak_mcp_wire_parity.py:WireTinyMLPPolicy",
        "scripts/tiebreak_mcp_wire_parity.py:WireScalingLogisticPolicy",
        "scripts/tiebreak_mcp_wire_parity.py:WireEmpiricalBayesPolicy",
    }
    if not expected_wire_classes.issubset(set(ast_classes)):
        errors.append(f"AST policy audit missing expected Wire*Policy classes: got {ast_classes}")

    if summary.get("schema") != SCHEMA_VERSION:
        errors.append(f"unexpected schema: {summary.get('schema')!r}")
    if summary.get("world_secret_tag") != EXPECTED_WORLD_SECRET_TAG:
        errors.append(f"unexpected world_secret_tag: {summary.get('world_secret_tag')!r}")
    if summary.get("heldout_seed_range") != "800000..800029":
        errors.append(f"unexpected heldout_seed_range: {summary.get('heldout_seed_range')!r}")
    if summary.get("eval_seed_range") != "800000..800029":
        errors.append(f"unexpected eval_seed_range: {summary.get('eval_seed_range')!r}")
    if summary.get("public_mcp_tools") != list(PUBLIC_MCP_TOOLS):
        errors.append("public_mcp_tools list mismatch against 13 canonical tools")

    iso = summary.get("seed_isolation") or {}
    if int(iso.get("judge_episodes_touched", 1)) != 0:
        errors.append("seed_isolation.judge_episodes_touched must be 0")
    if int(iso.get("dev_episodes_touched", 1)) != 0:
        errors.append("seed_isolation.dev_episodes_touched must be 0")
    if int(iso.get("train_episodes_in_heldout_eval", 1)) != 0:
        errors.append("seed_isolation.train_episodes_in_heldout_eval must be 0")

    ledger_cand = repo_root / LEDGER_REL
    if ledger_cand.is_file():
        ledger = json.loads(ledger_cand.read_text(encoding="utf-8"))
        hist_runs = list(ledger.get("historical_runs") or [])
        qwen_pos = sum(
            1
            for r in hist_runs
            if isinstance(r, dict)
            and isinstance(r.get("after_mean_score"), (int, float))
            and float(r["after_mean_score"]) > 0.0
        )
        pe = summary.get("panel_fix_e_track_separation") or {}
        if int(pe.get("open_weight_qwen25_runs_total", -1)) != len(hist_runs) or int(
            pe.get("open_weight_qwen25_runs_above_zero", -1)
        ) != qwen_pos:
            errors.append("panel_fix_e_track_separation out of sync with experiment_ledger.json")

    policies_block = summary.get("policies") or {}
    pooled_calls = 0
    pooled_bytes = 0
    pooled_scores: list[float] = []
    for pid in POLICY_ORDER:
        if pid not in policies_block:
            errors.append(f"missing policy block: {pid}")
            continue
        pb = policies_block[pid]
        meta_spec = POLICY_META_SPECS[pid]
        if int(pb.get("n", -1)) != EPISODES_PER_POLICY:
            errors.append(f"{pid}: n={pb.get('n')} != {EPISODES_PER_POLICY}")
        if pb.get("is_open_weight_llm") is not False:
            errors.append(f"{pid}: is_open_weight_llm must be False")
        if int(pb.get("param_count", -1)) != int(meta_spec["expected_param_count"]):
            errors.append(f"{pid}: param_count mismatch")
        if pb.get("train_seed_range") != meta_spec["expected_train_seed_range"]:
            errors.append(f"{pid}: train_seed_range mismatch")

        pr = pb.get("parity") or {}
        for match_key in (
            "tool_sequence_exact_matches",
            "wire_observation_exact_matches",
            "reward_bit_identical_matches",
            "terminal_verdict_exact_matches",
            "fresh_env_replays_verified",
            "exact_13_public_tools_handshakes",
        ):
            if int(pr.get(match_key, -1)) != EPISODES_PER_POLICY:
                errors.append(f"{pid}: parity.{match_key}={pr.get(match_key)} != {EPISODES_PER_POLICY}")
        if float(pr.get("max_abs_score_diff", 1.0)) != 0.0:
            errors.append(f"{pid}: max_abs_score_diff != 0.0")
        if int(pr.get("wire_hidden_key_leaks", 1)) != 0:
            errors.append(f"{pid}: wire_hidden_key_leaks != 0")
        if int(pr.get("shared_reference_violations", 1)) != 0:
            errors.append(f"{pid}: shared_reference_violations != 0")
        if pr.get("direct_traces_sha256") != pr.get("wire_traces_sha256"):
            errors.append(f"{pid}: direct_traces_sha256 != wire_traces_sha256")

        all_digests: list[str] = []
        by_tier = pb.get("by_tier") or {}
        for tier in CANONICAL_TIERS:
            tb = by_tier.get(tier) or {}
            digests = list(tb.get("episode_digests") or [])
            if len(digests) != HELDOUT_SEEDS_PER_TIER:
                errors.append(f"{pid}/{tier}: expected {HELDOUT_SEEDS_PER_TIER} digests, got {len(digests)}")
                continue
            recomp_tier = summarize_from_digests(digests)
            if recomp_tier != tb.get("wire") or recomp_tier != tb.get("direct"):
                errors.append(f"{pid}/{tier}: tier metrics disagree with recomputed episode_digests")
            all_digests.extend(digests)

        if len(all_digests) == EPISODES_PER_POLICY:
            recomp_all = summarize_from_digests(all_digests)
            if recomp_all != pb.get("wire_overall") or recomp_all != pb.get("direct_overall"):
                errors.append(f"{pid}: overall metrics disagree with recomputed episode_digests")
            t_counts = pb.get("tool_call_counts") or {}
            if sum(int(v) for v in t_counts.values()) != recomp_all["total_tool_calls"]:
                errors.append(f"{pid}: sum(tool_call_counts) != total_tool_calls")
            if not set(t_counts.keys()).issubset(PUBLIC_MCP_TOOL_SET):
                errors.append(f"{pid}: non-public tool in tool_call_counts")
            pooled_calls += int(recomp_all["total_tool_calls"])
            for d in all_digests:
                parsed_d = parse_episode_digest(d)
                pooled_bytes += int(parsed_d["wire_bytes"])
                pooled_scores.append(float(parsed_d["score"]))

    totals = summary.get("totals") or {}
    expected_total_eps = len(POLICY_ORDER) * EPISODES_PER_POLICY
    if int(totals.get("total_paired_episodes", -1)) != expected_total_eps:
        errors.append(f"totals.total_paired_episodes != {expected_total_eps}")
    if int(totals.get("tool_sequence_exact_matches", -1)) != expected_total_eps:
        errors.append(f"totals.tool_sequence_exact_matches != {expected_total_eps}")
    if int(totals.get("reward_bit_identical_matches", -1)) != expected_total_eps:
        errors.append(f"totals.reward_bit_identical_matches != {expected_total_eps}")
    if int(totals.get("total_wire_tool_calls", -1)) != pooled_calls:
        errors.append("totals.total_wire_tool_calls mismatch")
    exp_total_kib = round(pooled_bytes / 1024.0, 3)
    if abs(float(totals.get("total_wire_kib", -1.0)) - exp_total_kib) > 1e-3:
        errors.append("totals.total_wire_kib mismatch")
    if pooled_scores:
        exp_pooled_mean = round(sum(pooled_scores) / len(pooled_scores), 5)
        if abs(float(totals.get("pooled_wire_mean_score", -9.0)) - exp_pooled_mean) > 1e-5:
            errors.append("totals.pooled_wire_mean_score mismatch")

    rt = summary.get("redteam_taint_stripping_probe") or {}
    if int(rt.get("cases_passed", -1)) != int(rt.get("cases_tested", -2)) or int(rt.get("cases_tested", 0)) < 12:
        errors.append("redteam_taint_stripping_probe did not pass 12/12 cases")

    ast_block = summary.get("ast_inference_isolation") or {}
    if ast_block.get("passed") is not True or (ast_block.get("errors") or []):
        errors.append("summary.ast_inference_isolation is not clean PASS")

    expected_md = render_markdown_report(summary)
    if md_txt != expected_md:
        errors.append(f"{m_file.name}: markdown text out of sync with render_markdown_report(summary)")

    required_md_tokens = (
        "800000..800029",
        EXPECTED_WORLD_SECRET_TAG,
        "90/90 (100.0%)",
        "360/360 (100.0%)",
        "post-hoc locked, not pre-registered",
        "0 / 19",
        "CompactLinearDAggerPolicy",
        "TinyMLPPolicy",
        "ScalingLogisticPolicy",
        "EmpiricalBayesPolicy",
    )
    for tok in required_md_tokens:
        if tok not in md_txt:
            errors.append(f"{m_file.name}: missing required verified token {tok!r}")

    elapsed = time.perf_counter() - t0
    if enforce_budget and elapsed > MAX_CHECK_SECONDS:
        errors.append(f"--check elapsed {elapsed:.4f}s exceeded {MAX_CHECK_SECONDS:.2f}s budget")
    return errors


def verify_artifacts(root: Path = ROOT) -> dict[str, Any]:
    resolved = root.resolve()
    errs = verify_committed_artifacts(
        summary_path=resolved / DEFAULT_OUT_JSON,
        md_path=resolved / DEFAULT_OUT_MD,
        repo_root=resolved,
    )
    return {"passed": len(errs) == 0, "errors": errs}


def build_arg_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description="Deterministic keyless MCP wire-JSON equivalence adapter and parity audit."
    )
    ap.add_argument("--repo-root", "--root", dest="repo_root", type=Path, default=ROOT)
    ap.add_argument("--out-json", type=Path, default=DEFAULT_OUT_JSON)
    ap.add_argument("--out-md", type=Path, default=DEFAULT_OUT_MD)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--json", action="store_true")
    return ap


def _run_check_cli(args: argparse.Namespace) -> int:
    root = args.repo_root.resolve()
    out_json = args.out_json if args.out_json.is_absolute() else (root / args.out_json)
    out_md = args.out_md if args.out_md.is_absolute() else (root / args.out_md)
    t0 = time.perf_counter()
    errs = verify_committed_artifacts(summary_path=out_json, md_path=out_md, repo_root=root)
    elapsed = round(time.perf_counter() - t0, 4)
    if args.json:
        print(
            json.dumps(
                {
                    "schema": SCHEMA_VERSION,
                    "passed": len(errs) == 0,
                    "errors": errs,
                    "elapsed_seconds": elapsed,
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0 if not errs else 1
    if errs:
        for err in errs:
            print(f"FAIL: {err}", file=sys.stderr)
        return 1
    rel_j = out_json.relative_to(root) if out_json.is_relative_to(root) else out_json
    rel_m = out_md.relative_to(root) if out_md.is_relative_to(root) else out_md
    print(f"OK: verified {rel_j} and {rel_m} (360/360 MCP wire parity, 0 AST leaks) in {elapsed:.4f}s")
    return 0


if __name__ == "__main__" and "--check" in sys.argv[1:]:
    raise SystemExit(_run_check_cli(build_arg_parser().parse_args()))

from scripts.tiebreak_scaling_calibration import CompactLinearPolicy
from train.compact_dagger_ablation import CompactLinearDAggerPolicy
from train.empirical_bayes_policy import EmpiricalBayesPolicy
from train.neural_mlp_tiebreak import TinyMLPPolicy


class WireCompactLinearDAggerPolicy(CompactLinearDAggerPolicy):
    def __init__(self, weights: Any = None, name: str | None = None) -> None:
        super().__init__(weights=weights, name=name)
        self._wire_raw_refs: list[Any] = []
        self._wire_steps: list[WireStep] = []

    def reset(self, tools_spec: list[dict[str, Any]], instruction: str) -> None:
        self._wire_raw_refs = []
        self._wire_steps = []
        super().reset(sanitize_mcp_tools_spec(tools_spec), sanitize_mcp_instruction(instruction))

    def act(self, history: list[Any]) -> tuple[str, dict[str, Any]]:
        wire_hist = _sync_incremental_wire_history(history, self._wire_raw_refs, self._wire_steps)
        raw_tool, raw_args = super().act(wire_hist)
        return sanitize_mcp_call(raw_tool, raw_args)


class WireTinyMLPPolicy(TinyMLPPolicy):
    def __init__(self, weights: Any = None, seed: int = 0, name: str | None = None) -> None:
        super().__init__(weights=weights, seed=seed, name=name)
        self._wire_raw_refs: list[Any] = []
        self._wire_steps: list[WireStep] = []

    def reset(self, tools_spec: list[dict[str, Any]], instruction: str) -> None:
        self._wire_raw_refs = []
        self._wire_steps = []
        super().reset(sanitize_mcp_tools_spec(tools_spec), sanitize_mcp_instruction(instruction))

    def act(self, history: list[Any]) -> tuple[str, dict[str, Any]]:
        wire_hist = _sync_incremental_wire_history(history, self._wire_raw_refs, self._wire_steps)
        raw_tool, raw_args = super().act(wire_hist)
        return sanitize_mcp_call(raw_tool, raw_args)


class WireScalingLogisticPolicy(CompactLinearPolicy):
    def __init__(
        self,
        weights: Any,
        name: str | None = None,
        explore_eps: float = 0.0,
        rng_seed: int = 0,
    ) -> None:
        super().__init__(weights=weights, name=name, explore_eps=explore_eps, rng_seed=rng_seed)
        self._wire_raw_refs: list[Any] = []
        self._wire_steps: list[WireStep] = []

    def reset(self, tools_spec: list[dict[str, Any]], instruction: str) -> None:
        self._wire_raw_refs = []
        self._wire_steps = []
        super().reset(sanitize_mcp_tools_spec(tools_spec), sanitize_mcp_instruction(instruction))

    def act(self, history: list[Any]) -> tuple[str, dict[str, Any]]:
        wire_hist = _sync_incremental_wire_history(history, self._wire_raw_refs, self._wire_steps)
        raw_tool, raw_args = super().act(wire_hist)
        return sanitize_mcp_call(raw_tool, raw_args)


class WireEmpiricalBayesPolicy(EmpiricalBayesPolicy):
    def __init__(self, params: Any = None, seed: int = 0, name: str | None = None) -> None:
        super().__init__(params=params, seed=seed, name=name)
        self._wire_raw_refs: list[Any] = []
        self._wire_steps: list[WireStep] = []

    def reset(self, tools_spec: list[dict[str, Any]], instruction: str) -> None:
        self._wire_raw_refs = []
        self._wire_steps = []
        super().reset(sanitize_mcp_tools_spec(tools_spec), sanitize_mcp_instruction(instruction))

    def act(self, history: list[Any]) -> tuple[str, dict[str, Any]]:
        wire_hist = _sync_incremental_wire_history(history, self._wire_raw_refs, self._wire_steps)
        raw_tool, raw_args = super().act(wire_hist)
        return sanitize_mcp_call(raw_tool, raw_args)


ScalingLogisticPolicy = CompactLinearPolicy


@contextlib.contextmanager
def _scoped_world_secret(secret: str | None) -> Iterator[None]:
    prev = os.environ.get("CANARY_WORLD_SECRET")
    try:
        if secret is None:
            os.environ.pop("CANARY_WORLD_SECRET", None)
        else:
            os.environ["CANARY_WORLD_SECRET"] = secret
        yield
    finally:
        if prev is None:
            os.environ.pop("CANARY_WORLD_SECRET", None)
        else:
            os.environ["CANARY_WORLD_SECRET"] = prev


def load_direct_and_wire_factories(
    policy_id: str,
    repo_root: Path = ROOT,
) -> tuple[Callable[[int], Any], Callable[[int], Any], dict[str, Any]]:
    import numpy as np
    import scripts.run_tiebreak_policy as rtp
    from scripts.tiebreak_scaling_calibration import LinearPolicyWeights
    from train.compact_dagger_ablation import CompactLinearWeights
    from train.empirical_bayes_policy import EmpiricalBayesParams

    repo_root = repo_root.resolve()
    spec = POLICY_META_SPECS[policy_id]

    if policy_id == "compact_linear_dagger":
        s_data = json.loads((repo_root / spec["summary_path"]).read_text(encoding="utf-8"))
        tr = s_data["train_seeds"]
        rtp._assert_train_seed_range(int(tr["start"]), int(tr["stop"]), spec["summary_path"])
        weights = CompactLinearWeights.from_dict(s_data["learned_weights_stage3"])
        return (
            lambda _seed, w=weights: CompactLinearDAggerPolicy(weights=w, name="compact_linear_dagger"),
            lambda _seed, w=weights: WireCompactLinearDAggerPolicy(weights=w, name="wire_compact_linear_dagger"),
            {
                **spec,
                "param_count": int(weights.param_count()),
                "train_seed_range": f"{int(tr['start'])}..{int(tr['stop']) - 1}",
                "is_open_weight_llm": False,
            },
        )

    if policy_id == "tiny_mlp":
        s_data = json.loads((repo_root / spec["summary_path"]).read_text(encoding="utf-8"))
        tr = s_data["train_seeds"]
        rtp._assert_train_seed_range(int(tr["start"]), int(tr["stop"]), spec["summary_path"])
        weights, weight_source = rtp._load_or_reconstruct_tiny_mlp(
            mlp_summary=s_data,
            stage="stage3_onpolicy_dagger_r2",
        )
        return (
            lambda seed, w=weights: TinyMLPPolicy(weights=w, seed=seed, name="tiny_mlp"),
            lambda seed, w=weights: WireTinyMLPPolicy(weights=w, seed=seed, name="wire_tiny_mlp"),
            {
                **spec,
                "param_count": int(weights.param_count()),
                "weight_source": weight_source,
                "train_seed_range": f"{int(tr['start'])}..{int(tr['stop']) - 1}",
                "is_open_weight_llm": False,
            },
        )

    if policy_id == "scaling_logistic":
        s_data = json.loads((repo_root / spec["summary_path"]).read_text(encoding="utf-8"))
        tr_lo, tr_hi = int(s_data["train_seed_range"][0]), int(s_data["train_seed_range"][1])
        rtp._assert_train_seed_range(tr_lo, tr_hi + 1, spec["summary_path"])
        matched = next(r for r in s_data["scaling_curve"] if int(r["n_train"]) == 900)
        wd = matched["weights"]
        weights = LinearPolicyWeights(
            w_suspect=np.asarray(wd["w_suspect"], dtype=np.float64),
            w_commit=np.asarray(wd["w_commit"], dtype=np.float64),
            w_wait=np.asarray(wd["w_wait"], dtype=np.float64),
            w_tool=np.asarray(wd["w_tool"], dtype=np.float64),
            w_canary=np.asarray(wd["w_canary"], dtype=np.float64),
            n_train=900,
        )
        return (
            lambda seed, w=weights: CompactLinearPolicy(
                weights=w, name="scaling_logistic", explore_eps=0.0, rng_seed=seed
            ),
            lambda seed, w=weights: WireScalingLogisticPolicy(
                weights=w, name="wire_scaling_logistic", explore_eps=0.0, rng_seed=seed
            ),
            {
                **spec,
                "param_count": int(weights.num_parameters()),
                "train_seed_range": f"{tr_lo}..{tr_hi}",
                "is_open_weight_llm": False,
            },
        )

    if policy_id == "empirical_bayes":
        s_data = json.loads((repo_root / spec["summary_path"]).read_text(encoding="utf-8"))
        tr = s_data["train_seeds"]
        rtp._assert_train_seed_range(int(tr["start"]), int(tr["stop"]), spec["summary_path"])
        raw_params = s_data["parameters"]["eb_experience_opt"]
        params = EmpiricalBayesParams.from_dict(raw_params)
        scalar_param_count = len([k for k in raw_params if k not in ("stage", "naive_p_threshold")])
        return (
            lambda seed, p=params: EmpiricalBayesPolicy(params=p, seed=seed, name="empirical_bayes"),
            lambda seed, p=params: WireEmpiricalBayesPolicy(params=p, seed=seed, name="wire_empirical_bayes"),
            {
                **spec,
                "param_count": scalar_param_count,
                "train_seed_range": f"{int(tr['start'])}..{int(tr['stop']) - 1}",
                "is_open_weight_llm": False,
            },
        )

    raise ValueError(f"unknown policy_id {policy_id!r}")


def run_mcp_wire_episode(
    env: Any,
    policy: Any,
    max_iters: int = 1000,
) -> tuple[Any, dict[str, Any]]:
    server = MCPWireServerBoundary(env)
    client = MCPWireClientAdapter(server.handle_jsonrpc)
    wire_run = client.run_policy(policy, max_iters=max_iters)
    ep_res = env.result(getattr(policy, "name", type(policy).__name__))

    env_roots = [env.docs, env._logs, env._messages, env._feed] + [st.result for st in env.history]
    client_roots = [st.args for st in wire_run["steps"]] + [st.result for st in wire_run["steps"]]
    env_container_ids: set[int] = set()
    for env_item in env_roots:
        env_container_ids.update(collect_mutable_container_ids(env_item))
    client_container_ids: set[int] = set()
    for client_item in client_roots:
        client_container_ids.update(collect_mutable_container_ids(client_item))
    shared_refs = len(env_container_ids & client_container_ids)

    telemetry = {
        "advertised_tools": wire_run["advertised_tools"],
        "exact_13_public_tools": tuple(wire_run["advertised_tools"]) == PUBLIC_MCP_TOOLS,
        "wire_steps": wire_run["steps"],
        "tool_counts": wire_run["tool_counts"],
        "leak_violations": wire_run["leak_violations"],
        "envelope_mismatches": int(wire_run["envelope_mismatches"]),
        "shared_reference_violations": shared_refs,
        "request_bytes": int(server.request_bytes_total),
        "response_bytes": int(server.response_bytes_total),
        "total_wire_bytes": int(server.request_bytes_total + server.response_bytes_total),
    }
    return ep_res, telemetry


_WORKER_CTX: dict[str, Any] = {}


def _audit_single_task(task: tuple[str, str, int]) -> dict[str, Any]:
    from canary.env import Env
    from canary.eval import run_episode
    import scripts.run_tiebreak_policy as rtp

    policy_id, tier, seed = task
    provider = _WORKER_CTX["provider"]
    direct_fac, wire_fac, _ = _WORKER_CTX["bundles"][policy_id]

    with _scoped_world_secret(HELDOUT_WORLD_SECRET):
        direct_ep = run_episode(Env(tier, seed, text_provider=provider), direct_fac(seed))
        wire_env = Env(tier, seed, text_provider=provider)
        wire_ep, wire_tel = run_mcp_wire_episode(wire_env, wire_fac(seed))
        rtp.verify_episode_replay(wire_ep, text_provider=provider)

    direct_seq = [(int(s.t), int(s.day), str(s.tool), s.args) for s in direct_ep.steps]
    wire_seq = [(int(s.t), int(s.day), str(s.tool), s.args) for s in wire_tel["wire_steps"]]
    direct_obs = [_json_wire_roundtrip(s.result) for s in direct_ep.steps]
    wire_obs = [s.result for s in wire_tel["wire_steps"]]

    seq_exact = direct_seq == wire_seq
    obs_exact = direct_obs == wire_obs
    reward_bit_exact = float(direct_ep.score).hex() == float(wire_ep.score).hex()
    verdict_exact = (
        direct_ep.accused == wire_ep.accused
        and bool(direct_ep.correct) == bool(wire_ep.correct)
        and int(direct_ep.final_day) == int(wire_ep.final_day)
        and str(direct_ep.end_reason) == str(wire_ep.end_reason)
    )
    score_diff = abs(float(wire_ep.score) - float(direct_ep.score))

    d_sha = canonical_trace_sha256(direct_ep.steps)
    w_sha = canonical_trace_sha256(wire_tel["wire_steps"])

    return {
        "policy_id": policy_id,
        "tier": tier,
        "seed": seed,
        "seq_exact": seq_exact,
        "obs_exact": obs_exact,
        "reward_bit_exact": reward_bit_exact,
        "verdict_exact": verdict_exact,
        "score_diff": score_diff,
        "exact_13_tools": bool(wire_tel["exact_13_public_tools"]),
        "leak_count": len(wire_tel["leak_violations"]) + int(wire_tel["envelope_mismatches"]),
        "shared_refs": int(wire_tel["shared_reference_violations"]),
        "tool_counts": wire_tel["tool_counts"],
        "direct_sha": d_sha,
        "wire_sha": w_sha,
        "direct_digest": format_episode_digest(
            seed=seed,
            steps=len(direct_ep.steps),
            score=float(direct_ep.score),
            accused=direct_ep.accused,
            correct=bool(direct_ep.correct),
            final_day=int(direct_ep.final_day),
            wire_bytes=int(wire_tel["total_wire_bytes"]),
            trace_sha256=d_sha,
        ),
        "wire_digest": format_episode_digest(
            seed=seed,
            steps=len(wire_tel["wire_steps"]),
            score=float(wire_ep.score),
            accused=wire_ep.accused,
            correct=bool(wire_ep.correct),
            final_day=int(wire_ep.final_day),
            wire_bytes=int(wire_tel["total_wire_bytes"]),
            trace_sha256=w_sha,
        ),
    }


def run_redteam_taint_stripping_probe(
    bundles: dict[str, tuple[Callable[[int], Any], Callable[[int], Any], dict[str, Any]]],
    provider: Any,
) -> dict[str, Any]:
    from canary.env import Env
    from canary.rules import DEV_SEEDS, HELDOUT_SEEDS, JUDGE_SEEDS, TRAIN_SEEDS
    from canary.types import Step

    for s in REDTEAM_TRAIN_SEEDS:
        if s in DEV_SEEDS or s in HELDOUT_SEEDS or s in JUDGE_SEEDS or s not in TRAIN_SEEDS:
            raise ValueError(f"redteam probe seed {s} violates TRAIN_SEEDS isolation")

    class _TaintedDict(dict):
        pass

    class _TaintedStep(Step):
        pass

    cases_tested = 0
    cases_passed = 0
    for tier, seed in zip(CANONICAL_TIERS, REDTEAM_TRAIN_SEEDS):
        env = Env(tier, seed, text_provider=provider)
        spec = env.tools_spec()
        instr = env.instruction()
        r1 = env.call("list_employees", {})
        r2 = env.call("status", {})
        clean_steps = list(env.history)

        tainted_steps: list[Any] = []
        for st in clean_steps:
            td_args = _TaintedDict(st.args)
            td_args.secret_mole = "e00"
            td_res = _TaintedDict(
                {
                    **st.result,
                    "_rogue_mole": "e00",
                    "_internal_ledger": [{"mole": "e00"}],
                }
            )
            td_res.secret_world = object()
            ts = _TaintedStep(t=st.t, day=st.day, tool=st.tool, args=td_args, result=td_res)
            ts.mole = "e00"
            ts.true_V = 0.99
            tainted_steps.append(ts)
        _ = (r1, r2)

        for pid in POLICY_ORDER:
            direct_fac, wire_fac, _ = bundles[pid]
            p_clean = direct_fac(seed)
            p_wire = wire_fac(seed)
            p_clean.reset(spec, instr)
            p_wire.reset(spec, instr)
            act_clean = p_clean.act(clean_steps)
            act_tainted = p_wire.act(tainted_steps)
            sanitized = list(p_wire._wire_steps)
            stripped_ok = (
                act_clean == act_tainted
                and len(sanitized) == len(clean_steps)
                and all(
                    isinstance(ws, WireStep)
                    and not hasattr(ws, "__dict__")
                    and not hasattr(ws, "mole")
                    and type(ws.args) is dict
                    and type(ws.result) is dict
                    and set(ws.result.keys()) == ALLOWED_RESULT_ENVELOPE_KEYS
                    for ws in sanitized
                )
            )
            cases_tested += 1
            if stripped_ok:
                cases_passed += 1

    type_traps_verified = 0
    for bad_payload in (
        {"bad": object()},
        {"bad": {1, 2}},
        {"bad": float("nan")},
        {"bad": float("inf")},
    ):
        try:
            _json_wire_roundtrip(bad_payload)
        except (TypeError, ValueError):
            type_traps_verified += 1

    return {
        "train_seed_range": f"{REDTEAM_TRAIN_SEEDS[0]}..{REDTEAM_TRAIN_SEEDS[-1]}",
        "tiers_probed": list(CANONICAL_TIERS),
        "cases_tested": cases_tested,
        "cases_passed": cases_passed,
        "non_json_rejections_verified": type_traps_verified,
        "all_passed": cases_tested == 12 and cases_passed == 12 and type_traps_verified == 4,
    }


def run_audit(repo_root: Path = ROOT, max_workers: int = 8) -> dict[str, Any]:
    from canary import rules
    from canary.text.template import TemplateProvider
    import scripts.verify_tiebreak_submission as vts

    t0 = time.perf_counter()
    repo_root = repo_root.resolve()
    heldout_seeds = list(range(HELDOUT_SEED_START, HELDOUT_SEED_STOP))
    for s in heldout_seeds:
        if s not in rules.HELDOUT_SEEDS or s in rules.JUDGE_SEEDS or s >= 900_000:
            raise ValueError(f"seed {s} violates HELDOUT_SEEDS isolation")

    secret_tag = compute_secret_tag(HELDOUT_WORLD_SECRET)
    if secret_tag != EXPECTED_WORLD_SECRET_TAG:
        raise AssertionError(f"secret_tag {secret_tag} != {EXPECTED_WORLD_SECRET_TAG}")

    provider = TemplateProvider()
    bundles = {
        pid: load_direct_and_wire_factories(pid, repo_root=repo_root)
        for pid in POLICY_ORDER
    }

    _WORKER_CTX["provider"] = provider
    _WORKER_CTX["bundles"] = bundles

    tasks = [
        (pid, tier, seed)
        for pid in POLICY_ORDER
        for tier in CANONICAL_TIERS
        for seed in heldout_seeds
    ]

    use_fork = max_workers > 1 and "fork" in multiprocessing.get_all_start_methods()
    if use_fork:
        ctx = multiprocessing.get_context("fork")
        with ProcessPoolExecutor(max_workers=min(max_workers, 12), mp_context=ctx) as pool:
            raw_results = list(pool.map(_audit_single_task, tasks, chunksize=6))
    else:
        raw_results = [_audit_single_task(tk) for tk in tasks]

    redteam_probe = run_redteam_taint_stripping_probe(bundles, provider)

    script_rel = Path("scripts/tiebreak_mcp_wire_parity.py")
    script_abs = repo_root / script_rel
    ast_outcome = vts.check_ast_inference_isolation(
        root=repo_root,
        extra_paths=[script_abs if script_abs.is_file() else Path(__file__).resolve()],
        strict=True,
    )
    if not ast_outcome.passed:
        raise AssertionError(f"AST inference isolation failed: {ast_outcome.errors}")

    ledger = json.loads((repo_root / LEDGER_REL).read_text(encoding="utf-8"))
    hist_runs = list(ledger.get("historical_runs") or [])
    qwen_above_zero = sum(
        1
        for r in hist_runs
        if isinstance(r, dict)
        and isinstance(r.get("after_mean_score"), (int, float))
        and float(r["after_mean_score"]) > 0.0
    )
    sc = ledger.get("summary_counts") or {}
    panel_e = {
        "source_path": str(LEDGER_REL),
        "open_weight_qwen25_runs_total": len(hist_runs),
        "open_weight_qwen25_runs_above_zero": qwen_above_zero,
        "open_weight_qwen25_above_zero_ratio": f"{qwen_above_zero} / {len(hist_runs)}",
        "readme_qwen_addendum_status": "HOLD_README_QWEN_ADDENDUM_UNTIL_V100",
        "non_llm_verified_run_ids": list(sc.get("verified_run_ids") or []),
        "non_llm_policies_is_open_weight_llm": False,
        "disclosure": PANEL_FIX_E_DISCLOSURE,
    }

    policies_out: dict[str, Any] = {}
    pooled_tool_counts: dict[str, int] = {t: 0 for t in PUBLIC_MCP_TOOLS}
    total_seq_ok = 0
    total_obs_ok = 0
    total_rew_ok = 0
    total_verdict_ok = 0
    total_13_ok = 0
    total_leaks = 0
    total_shared_refs = 0
    max_score_diff = 0.0
    pooled_direct_scores: list[float] = []
    pooled_wire_scores: list[float] = []
    total_wire_calls = 0
    total_wire_bytes = 0

    for pid in POLICY_ORDER:
        _, _, meta_info = bundles[pid]
        p_rows = [r for r in raw_results if r["policy_id"] == pid]
        by_tier_out: dict[str, Any] = {}
        all_direct_digests: list[str] = []
        all_wire_digests: list[str] = []
        p_tool_counts: dict[str, int] = {t: 0 for t in PUBLIC_MCP_TOOLS}

        for tier in CANONICAL_TIERS:
            t_rows = [r for r in p_rows if r["tier"] == tier]
            d_digests = [r["direct_digest"] for r in t_rows]
            w_digests = [r["wire_digest"] for r in t_rows]
            all_direct_digests.extend(d_digests)
            all_wire_digests.extend(w_digests)
            for r in t_rows:
                for tk_name, cnt in r["tool_counts"].items():
                    p_tool_counts[tk_name] = p_tool_counts.get(tk_name, 0) + int(cnt)
                    pooled_tool_counts[tk_name] = pooled_tool_counts.get(tk_name, 0) + int(cnt)
            by_tier_out[tier] = {
                "direct": summarize_from_digests(d_digests),
                "wire": summarize_from_digests(w_digests),
                "parity": {
                    "n": len(t_rows),
                    "tool_sequence_exact_matches": sum(1 for r in t_rows if r["seq_exact"]),
                    "wire_observation_exact_matches": sum(1 for r in t_rows if r["obs_exact"]),
                    "reward_bit_identical_matches": sum(1 for r in t_rows if r["reward_bit_exact"]),
                    "terminal_verdict_exact_matches": sum(1 for r in t_rows if r["verdict_exact"]),
                    "max_abs_score_diff": round(max((r["score_diff"] for r in t_rows), default=0.0), 5),
                },
                "episode_digests": w_digests,
            }

        d_overall = summarize_from_digests(all_direct_digests)
        w_overall = summarize_from_digests(all_wire_digests)
        d_sha_all = "0x" + hashlib.sha256(
            "\n".join(r["direct_sha"] for r in p_rows).encode("utf-8")
        ).hexdigest()
        w_sha_all = "0x" + hashlib.sha256(
            "\n".join(r["wire_sha"] for r in p_rows).encode("utf-8")
        ).hexdigest()

        p_seq_ok = sum(1 for r in p_rows if r["seq_exact"])
        p_obs_ok = sum(1 for r in p_rows if r["obs_exact"])
        p_rew_ok = sum(1 for r in p_rows if r["reward_bit_exact"])
        p_ver_ok = sum(1 for r in p_rows if r["verdict_exact"])
        p_13_ok = sum(1 for r in p_rows if r["exact_13_tools"])
        p_leaks = sum(int(r["leak_count"]) for r in p_rows)
        p_refs = sum(int(r["shared_refs"]) for r in p_rows)
        p_max_diff = max((float(r["score_diff"]) for r in p_rows), default=0.0)

        total_seq_ok += p_seq_ok
        total_obs_ok += p_obs_ok
        total_rew_ok += p_rew_ok
        total_verdict_ok += p_ver_ok
        total_13_ok += p_13_ok
        total_leaks += p_leaks
        total_shared_refs += p_refs
        max_score_diff = max(max_score_diff, p_max_diff)
        total_wire_calls += int(w_overall["total_tool_calls"])
        total_wire_bytes += sum(parse_episode_digest(d)["wire_bytes"] for d in all_wire_digests)
        pooled_direct_scores.extend(parse_episode_digest(d)["score"] for d in all_direct_digests)
        pooled_wire_scores.extend(parse_episode_digest(d)["score"] for d in all_wire_digests)

        policies_out[pid] = {
            "policy_id": pid,
            "policy_class": meta_info["policy_class"],
            "wire_adapter_class": meta_info["wire_adapter_class"],
            "run_id": meta_info["run_id"],
            "module_path": meta_info["module_path"],
            "summary_path": meta_info["summary_path"],
            "param_count": int(meta_info["param_count"]),
            "train_seed_range": meta_info["train_seed_range"],
            "is_open_weight_llm": False,
            "n": len(p_rows),
            "world_secret_tag": secret_tag,
            "replay_verified": True,
            "invalid_episodes": 0,
            "direct_overall": d_overall,
            "wire_overall": w_overall,
            "parity": {
                "tool_sequence_exact_matches": p_seq_ok,
                "tool_sequence_parity_rate": round(p_seq_ok / len(p_rows), 5),
                "wire_observation_exact_matches": p_obs_ok,
                "reward_bit_identical_matches": p_rew_ok,
                "reward_parity_rate": round(p_rew_ok / len(p_rows), 5),
                "terminal_verdict_exact_matches": p_ver_ok,
                "fresh_env_replays_verified": len(p_rows),
                "exact_13_public_tools_handshakes": p_13_ok,
                "wire_hidden_key_leaks": p_leaks,
                "shared_reference_violations": p_refs,
                "max_abs_score_diff": round(p_max_diff, 5),
                "direct_traces_sha256": d_sha_all,
                "wire_traces_sha256": w_sha_all,
            },
            "tool_call_counts": p_tool_counts,
            "by_tier": by_tier_out,
        }

    total_paired = len(raw_results)
    elapsed_s = round(time.perf_counter() - t0, 3)

    return {
        "schema": SCHEMA_VERSION,
        "audit_id": AUDIT_ID,
        "tiers_version": str(rules.TIERS_VERSION),
        "mcp_protocol_version": MCP_PROTOCOL_VERSION,
        "public_mcp_tools": list(PUBLIC_MCP_TOOLS),
        "tiers": list(CANONICAL_TIERS),
        "heldout_seed_range": f"{HELDOUT_SEED_START}..{HELDOUT_SEED_STOP - 1}",
        "eval_seed_range": f"{HELDOUT_SEED_START}..{HELDOUT_SEED_STOP - 1}",
        "heldout_seeds": {"start": HELDOUT_SEED_START, "stop": HELDOUT_SEED_STOP},
        "eval_seeds_per_tier": HELDOUT_SEEDS_PER_TIER,
        "episodes_per_policy": EPISODES_PER_POLICY,
        "world_secret_tag": secret_tag,
        "replay_verified": True,
        "invalid_episodes": 0,
        "seed_isolation": {
            "heldout_world_paired": True,
            "train_episodes_in_heldout_eval": 0,
            "dev_episodes_touched": 0,
            "judge_episodes_touched": 0,
            "panel_fix_a_disclosure": PANEL_FIX_A_DISCLOSURE,
        },
        "panel_fix_e_track_separation": panel_e,
        "ast_inference_isolation": {
            "passed": bool(ast_outcome.passed),
            "summary": str(ast_outcome.summary),
            "errors": list(ast_outcome.errors),
            "modules_checked": list(ast_outcome.metrics.get("modules_checked") or []),
            "policy_classes_checked": list(ast_outcome.metrics.get("policy_classes_checked") or []),
        },
        "redteam_taint_stripping_probe": redteam_probe,
        "totals": {
            "policies_audited": len(POLICY_ORDER),
            "total_paired_episodes": total_paired,
            "total_env_rollouts": total_paired * 2,
            "fresh_env_replays_verified": total_paired,
            "tool_sequence_exact_matches": total_seq_ok,
            "tool_sequence_parity_rate": round(total_seq_ok / total_paired, 5),
            "wire_observation_exact_matches": total_obs_ok,
            "reward_bit_identical_matches": total_rew_ok,
            "reward_parity_rate": round(total_rew_ok / total_paired, 5),
            "terminal_verdict_exact_matches": total_verdict_ok,
            "exact_13_public_tools_handshakes": total_13_ok,
            "wire_hidden_key_leaks": total_leaks,
            "shared_reference_violations": total_shared_refs,
            "max_abs_score_diff": round(max_score_diff, 5),
            "pooled_direct_mean_score": round(sum(pooled_direct_scores) / len(pooled_direct_scores), 5),
            "pooled_wire_mean_score": round(sum(pooled_wire_scores) / len(pooled_wire_scores), 5),
            "total_wire_tool_calls": total_wire_calls,
            "total_wire_kib": round(total_wire_bytes / 1024.0, 3),
            "pooled_tool_call_counts": pooled_tool_counts,
            "elapsed_seconds": elapsed_s,
        },
        "policies": policies_out,
    }


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    if args.check:
        return _run_check_cli(args)

    root = args.repo_root.resolve()
    out_json = args.out_json if args.out_json.is_absolute() else (root / args.out_json)
    out_md = args.out_md if args.out_md.is_absolute() else (root / args.out_md)

    summary = run_audit(repo_root=root, max_workers=max(1, int(args.workers)))
    md_text = render_markdown_report(summary)

    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_md.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    out_md.write_text(md_text, encoding="utf-8")

    errs = verify_committed_artifacts(
        summary_path=out_json,
        md_path=out_md,
        repo_root=root,
        enforce_budget=False,
    )
    if errs:
        for err in errs:
            print(f"FAIL: {err}", file=sys.stderr)
        return 1

    print(
        f"Wrote {out_json.relative_to(root)} ({out_json.stat().st_size} bytes) and "
        f"{out_md.relative_to(root)} ({summary['totals']['tool_sequence_exact_matches']}/"
        f"{summary['totals']['total_paired_episodes']} MCP wire parity in "
        f"{summary['totals']['elapsed_seconds']:.2f}s)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
