from __future__ import annotations

import argparse
import contextlib
import copy
import functools
import importlib.util
import json
import math
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterator

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) in sys.path:
    sys.path.remove(str(ROOT))
sys.path.insert(0, str(ROOT))

TMP_OPENCODE_DIR = Path("/tmp/opencode")
PARITY_TOL = 1e-12
MEDIUM_SEEDS: tuple[int, ...] = (3000, 3001, 3002)
HARD_SEEDS: tuple[int, ...] = (3000, 3001, 3002)

EN_DASH = chr(0x2013)
EM_DASH = chr(0x2014)
MINUS_SIGN = chr(0x2212)
PLUS_MINUS = chr(0x00B1)

FORBIDDEN_BUNDLE_REL_PREFIXES: tuple[str, ...] = (
    "data/",
    "results/",
    "redteam/",
    "harbor/",
    "scripts/",
    "tests/",
)

FORBIDDEN_ARENA_ROOT_REL_PREFIXES: tuple[str, ...] = (
    "data/worlds/",
    "data/runs/",
    "data/rl_mole/",
    "results/",
    "redteam/",
    "harbor/",
    "scripts/",
    "tests/",
    "py/data/",
    "py/results/",
    "py/redteam/",
    "py/harbor/",
    "py/scripts/",
    "py/tests/",
)

FORBIDDEN_BUNDLE_FILENAMES: frozenset[str] = frozenset(
    {
        "mcp_server.py",
        "SALT",
        "ledger_key",
        ".env",
        "reproduce.py",
        "eval.py",
    }
)

ALLOWED_ENV_TEMPLATES: frozenset[str] = frozenset(
    {
        ".env.example",
        ".env.sample",
        ".env.template",
    }
)

FORBIDDEN_MANIFEST_SUBSTRINGS: tuple[str, ...] = (
    "data/",
    "results/",
    "redteam/",
    "harbor/",
    "SALT",
    "ledger_key",
    "mcp_server.py",
    ".env",
    "reproduce.py",
    "eval.py",
)

TEXT_ASSET_SUFFIXES: frozenset[str] = frozenset(
    {
        ".json",
        ".jsonl",
        ".html",
        ".htm",
        ".js",
        ".mjs",
        ".cjs",
        ".css",
        ".py",
        ".md",
        ".txt",
        ".svg",
    }
)

STRUCTURED_ASSET_SUFFIXES: frozenset[str] = frozenset(
    {
        ".json",
        ".jsonl",
        ".html",
        ".htm",
        ".js",
        ".mjs",
        ".cjs",
    }
)

MOLE_TRUTH_FIELD_NAMES: frozenset[str] = frozenset(
    {
        "mole",
        "mole_id",
        "moleId",
        "true_mole",
        "trueMole",
        "secret_mole",
    }
)

POST_DONE_REVEAL_KEYS: frozenset[str] = frozenset(
    {
        "reveal",
        "sealed_reveal",
        "sealedReveal",
        "sealed_verdict",
        "post_game",
        "post_end",
        "post_game_reveal",
        "postGameReveal",
        "unlockPostGameReveal",
        "unlock_post_game_reveal",
        "end_reveal",
        "final_reveal",
        "case_closed",
        "forensics",
        "verdict",
        "outcome",
        "terminal",
        "commitment",
    }
)

PRE_END_STEP_KEYS: frozenset[str] = frozenset(
    {
        "steps",
        "frames",
        "sprite_frames",
        "office_frames",
        "timeline",
        "days",
        "day_states",
        "hud_states",
        "opponent_steps",
        "ai_steps",
        "events",
    }
)

SECRET_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("google_api_key", re.compile(r"AIza[0-9A-Za-z_\-]{20,}")),
    ("sk_api_key", re.compile(r"\bsk-(?:proj-|ant-)?[A-Za-z0-9_\-]{20,}\b")),
    ("google_oauth_token", re.compile(r"\bya29\.[0-9A-Za-z_\-]{20,}")),
    (
        "provider_token",
        re.compile(r"\b(?:xai-[A-Za-z0-9_\-]{20,}|hf_[A-Za-z0-9]{20,}|ghp_[A-Za-z0-9]{20,})\b"),
    ),
    ("private_key_pem", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")),
    (
        "secret_env_assignment",
        re.compile(
            r"\b(?:GEMINI_API_KEY|GOOGLE_API_KEY|GOOGLE_GENERATIVE_AI_API_KEY|"
            r"OPENAI_API_KEY|ANTHROPIC_API_KEY|CANARY_WORLD_SECRET|"
            r"CANARY_LEDGER_TOKEN|CANARY_ADMIN_TOKEN|XAI_API_KEY|HF_TOKEN)"
            r"\s*=\s*[\x27\x22]?[A-Za-z0-9_\-]{8,}"
        ),
    ),
)

STRICT_SECRET_PATH_RE = re.compile(
    r"\b(?:CANARY_WORLD_SECRET|CANARY_LEDGER_TOKEN)\b|data/worlds/judge/SALT"
)

MOLE_GROUND_TRUTH_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "mole_ground_truth_json",
        re.compile(r'"(?:mole|mole_id|moleId|true_mole|trueMole|secret_mole)"\s*:\s*"e\d{2,3}"'),
    ),
    (
        "mole_ground_truth_js",
        re.compile(r"(?:^|[{,\s])(?:mole|mole_id|moleId|true_mole|trueMole|secret_mole)\s*:\s*[\x27\x22]e\d{2,3}[\x27\x22]"),
    ),
)

EMP_ID_VALUE_RE = re.compile(r"^e\d{2,3}$")
JUDGE_SEED_JS_RE = re.compile(
    r"""(?:["']?(?:seed|case_seed|episode_seed)["']?\s*:\s*900\d{3}\b)"""
)
JS_JSON_ASSIGN_RE = re.compile(
    r"(?:(?:\bexport\s+)?\b(?:const|let|var)\s+[A-Za-z_$][A-Za-z0-9_$]*|"
    r"\b(?:window|globalThis|self)\.[A-Za-z_$][A-Za-z0-9_$]*)\s*=\s*(?:Object\.freeze\(\s*)?"
)
HTML_JSON_SCRIPT_RE = re.compile(
    r"<script[^>]*type=[\x27\x22]application/(?:ld\+)?json[\x27\x22][^>]*>(.*?)</script>",
    re.IGNORECASE | re.DOTALL,
)
HTML_SCRIPT_RE = re.compile(r"<script[^>]*>(.*?)</script>", re.IGNORECASE | re.DOTALL)
JS_POST_DONE_GATE_RE = re.compile(
    r"(?:done\s*(?:===|!==)\s*true|humanDone\s*(?:===|!==)\s*true|human_done\s*(?:===|!==)\s*true)"
)
JS_POST_DONE_SYMBOL_RE = re.compile(
    r"\b(?:unlockPostGameReveal|unlock_post_game_reveal|postGameReveal|post_game_reveal|sealedReveal|sealed_reveal|getPostGameForensics)\b"
)

_ISOLATED_PYODIDE_WORKER = """
import json
import struct
import sys
from pathlib import Path

py_dir = Path(sys.argv[1]).resolve()
payload_path = Path(sys.argv[2]).resolve()
repo_root = Path(sys.argv[3]).resolve()
check_game_module = sys.argv[4] == "1"


def _is_clean_stdlib_path(entry: str) -> bool:
    if not entry:
        return False
    low = entry.replace("\\\\", "/")
    if "site-packages" in low or "dist-packages" in low or "/wt/" in low:
        return False
    try:
        rp = Path(entry).resolve()
        if rp == repo_root or repo_root in rp.parents:
            return False
    except OSError:
        return False
    return True


sys.path[:] = [str(py_dir)] + [p for p in sys.path if _is_clean_stdlib_path(p)]

def float_bits(val: float) -> str:
    return struct.pack(">d", float(val)).hex()

import canary
from canary.env import Env
from canary.solver.policy import SolverPolicy

game_mod = None
if check_game_module:
    import canary_game as game_mod

loaded_modules = {}
outside_bundle = []
for mod_name, mod_obj in sorted(sys.modules.items()):
    if mod_name == "canary" or mod_name.startswith("canary.") or mod_name == "canary_game":
        mod_file = getattr(mod_obj, "__file__", None)
        if mod_file is not None:
            resolved = Path(mod_file).resolve()
            loaded_modules[mod_name] = str(resolved)
            if not resolved.is_relative_to(py_dir):
                outside_bundle.append(f"{mod_name}:{resolved}")

blocked_imports = {}
for forbidden_mod in (
    "canary.eval",
    "canary.reproduce",
    "canary.analysis.gap",
    "canary.mcp_server",
    "mcp_server",
    "canary.text.gemini",
    "redteam",
):
    try:
        __import__(forbidden_mod)
        blocked_imports[forbidden_mod] = False
    except ModuleNotFoundError:
        blocked_imports[forbidden_mod] = True

seed_guards_ok = True
pre_end_guard_ok = True
if game_mod is not None:
    for bad_seed in (0, 29, 2999, 10000, 800000, 900000, "3000.0", "abc"):
        try:
            game_mod.Game(bad_seed)
            seed_guards_ok = False
        except ValueError:
            pass
    probe_game = game_mod.Game(3000)
    spec_obj = json.loads(probe_game.spec_json())
    reveal_early = json.loads(probe_game.reveal_json())
    if probe_game.env.history != [] or "error" not in reveal_early or "mole" in reveal_early:
        pre_end_guard_ok = False
    if probe_game.env._world.mole in json.dumps(spec_obj):
        pre_end_guard_ok = False

payload = json.loads(payload_path.read_text(encoding="utf-8"))
case_outputs = []
for case in payload["cases"]:
    tier = case["tier"]
    seed = int(case["seed"])
    actions = case["actions"]
    env = Env(tier, seed)
    step_summaries = []
    for tool_name, tool_args in actions:
        if env.done:
            break
        tr = env.call(tool_name, tool_args)
        step_summaries.append({"ok": bool(tr.ok), "error": tr.error})
    verdict = env.verdict()
    ep_res = env.result(case["agent"])
    entry = {
        "case_id": case["case_id"],
        "tier": tier,
        "seed": seed,
        "verdict": verdict,
        "score": ep_res.score,
        "score_bits": float_bits(ep_res.score),
        "V": float(ep_res.meta["V"]),
        "V_bits": float_bits(float(ep_res.meta["V"])),
        "accused": ep_res.accused,
        "correct": bool(ep_res.correct),
        "final_day": int(ep_res.final_day),
        "end_reason": ep_res.end_reason,
        "step_count": len(ep_res.steps),
        "step_summaries": step_summaries,
    }
    if game_mod is not None and tier == "medium" and 3000 <= seed <= 9999:
        g = game_mod.Game(seed)
        for tool_name, tool_args in actions:
            if g.env.done:
                break
            g.call_json(tool_name, json.dumps(tool_args))
        entry["game_verdict"] = g.env.verdict()
        entry["game_replay_verdict"] = game_mod.replay(seed, actions)
        if g.env.done:
            rev = json.loads(g.reveal_json())
            entry["game_reveal_you"] = rev["you"]
            entry["game_reveal_solver"] = rev["solver"]
    case_outputs.append(entry)

solver_outputs = []
for solver_req in payload["solver_runs"]:
    tier = solver_req["tier"]
    seed = int(solver_req["seed"])
    env = Env(tier, seed)
    pol = SolverPolicy()
    pol.reset(env.tools_spec(), env.instruction())
    while not env.done:
        t_name, t_args = pol.act(env.history)
        env.call(t_name, t_args)
    v = env.verdict()
    sr = {
        "tier": tier,
        "seed": seed,
        "score": v["score"],
        "score_bits": float_bits(v["score"]),
        "accused": v["accused"],
        "correct": bool(v["correct"]),
        "final_day": int(v["final_day"]),
        "tool_calls": len(env.history),
        "verdict": v,
    }
    if game_mod is not None and tier == "medium" and 3000 <= seed <= 9999:
        sr["canary_game_solver_result"] = game_mod.solver_result(seed)
    solver_outputs.append(sr)

out_obj = {
    "sys_path": list(sys.path),
    "loaded_modules": loaded_modules,
    "outside_bundle": outside_bundle,
    "blocked_imports": blocked_imports,
    "seed_guards_ok": seed_guards_ok,
    "pre_end_guard_ok": pre_end_guard_ok,
    "cases": case_outputs,
    "solver_runs": solver_outputs,
}
print(json.dumps(out_obj, sort_keys=True))
"""


@dataclass
class GateResult:
    gate: str
    passed: bool
    summary: str
    violations: list[str] = field(default_factory=list)
    data: dict[str, Any] = field(default_factory=dict)


class RecordedActionsPolicy:
    def __init__(self, actions: list[tuple[str, dict[str, Any]]], name: str = "recorded_actions") -> None:
        self.name = name
        self._actions = [(str(t), dict(a)) for t, a in actions]
        self._index = 0

    def reset(self, tools_spec: list[dict[str, Any]], instruction: str) -> None:
        self._index = 0

    def act(self, history: list[Any]) -> tuple[str, dict[str, Any]]:
        if self._index < len(self._actions):
            item = self._actions[self._index]
            self._index += 1
            return item
        return "advance_day", {}


def _norm_ascii(text: str) -> str:
    return (
        text.replace(EN_DASH, "-")
        .replace(EM_DASH, "--")
        .replace(MINUS_SIGN, "-")
        .replace(PLUS_MINUS, "+/-")
    )


def _float_bits(val: float) -> str:
    return struct.pack(">d", float(val)).hex()


def _clean_json_value(obj: Any) -> Any:
    if isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            return None
        return round(obj, 12)
    if isinstance(obj, str):
        return _norm_ascii(obj)
    if isinstance(obj, dict):
        return {str(k): _clean_json_value(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_clean_json_value(v) for v in obj]
    return obj


@contextlib.contextmanager
def temporary_opencode_dir(prefix: str = "arena_bundle_parity_") -> Iterator[Path]:
    TMP_OPENCODE_DIR.mkdir(parents=True, exist_ok=True)
    created = Path(tempfile.mkdtemp(prefix=prefix, dir=str(TMP_OPENCODE_DIR)))
    try:
        yield created
    finally:
        shutil.rmtree(created, ignore_errors=True)


def _load_game_build_module(root: Path):
    build_path = root / "game" / "build.py"
    if not build_path.is_file():
        raise FileNotFoundError(f"missing game/build.py at {build_path}")
    spec = importlib.util.spec_from_file_location("canary_game_build_mod", build_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load spec for {build_path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _build_zero_v_actions_for_medium_seed(seed: int, target_employee: str) -> list[tuple[str, dict[str, Any]]]:
    actions: list[tuple[str, dict[str, Any]]] = []
    for idx in range(8):
        actions.append(("restrict_access", {"employee": f"e{idx:02d}"}))
    actions.append(("advance_day", {}))
    for idx in range(8, 16):
        actions.append(("restrict_access", {"employee": f"e{idx:02d}"}))
    actions.append(("advance_day", {}))
    for idx in range(16, 20):
        actions.append(("restrict_access", {"employee": f"e{idx:02d}"}))
    actions.append(("advance_day", {}))
    for _ in range(3):
        actions.append(("advance_day", {}))
    actions.append(("accuse", {"employee": target_employee}))
    return actions


@functools.lru_cache(maxsize=1)
def _compute_reference_cases() -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[Any]]:
    from canary.baselines import DoNothing, StopEarly
    from canary.env import Env
    from canary.eval import run_episode
    from canary.solver.policy import SolverPolicy

    cases: list[dict[str, Any]] = []
    solver_refs: list[dict[str, Any]] = []
    episodes_out: list[Any] = []

    for seed in MEDIUM_SEEDS:
        env_sol = Env("medium", seed)
        ep_sol = run_episode(env_sol, SolverPolicy())
        verdict_sol = env_sol.verdict()
        episodes_out.append(ep_sol)
        acts_sol = [[s.tool, s.args] for s in ep_sol.steps]
        cases.append(
            {
                "case_id": f"medium_solver_{seed}",
                "tier": "medium",
                "seed": seed,
                "agent": ep_sol.agent,
                "actions": acts_sol,
                "expected_verdict": verdict_sol,
                "expected_score": ep_sol.score,
                "expected_score_bits": _float_bits(ep_sol.score),
                "expected_V": float(ep_sol.meta["V"]),
                "expected_V_bits": _float_bits(float(ep_sol.meta["V"])),
                "expected_accused": ep_sol.accused,
                "expected_correct": bool(ep_sol.correct),
                "expected_final_day": int(ep_sol.final_day),
                "expected_end_reason": ep_sol.end_reason,
                "expected_steps": [{"ok": bool(s.result["ok"]), "error": s.result.get("error")} for s in ep_sol.steps],
            }
        )
        solver_refs.append(
            {
                "tier": "medium",
                "seed": seed,
                "score": ep_sol.score,
                "score_bits": _float_bits(ep_sol.score),
                "accused": ep_sol.accused,
                "correct": bool(ep_sol.correct),
                "final_day": int(ep_sol.final_day),
                "tool_calls": len(ep_sol.steps),
                "verdict": verdict_sol,
            }
        )

    env_m_se = Env("medium", 3000)
    ep_m_se = run_episode(env_m_se, StopEarly(seed=3000))
    episodes_out.append(ep_m_se)
    cases.append(
        {
            "case_id": "medium_stop_early_3000",
            "tier": "medium",
            "seed": 3000,
            "agent": ep_m_se.agent,
            "actions": [[s.tool, s.args] for s in ep_m_se.steps],
            "expected_verdict": env_m_se.verdict(),
            "expected_score": ep_m_se.score,
            "expected_score_bits": _float_bits(ep_m_se.score),
            "expected_V": float(ep_m_se.meta["V"]),
            "expected_V_bits": _float_bits(float(ep_m_se.meta["V"])),
            "expected_accused": ep_m_se.accused,
            "expected_correct": bool(ep_m_se.correct),
            "expected_final_day": int(ep_m_se.final_day),
            "expected_end_reason": ep_m_se.end_reason,
            "expected_steps": [{"ok": bool(s.result["ok"]), "error": s.result.get("error")} for s in ep_m_se.steps],
        }
    )

    env_m_dn = Env("medium", 3001)
    ep_m_dn = run_episode(env_m_dn, DoNothing(seed=3001))
    episodes_out.append(ep_m_dn)
    cases.append(
        {
            "case_id": "medium_do_nothing_3001",
            "tier": "medium",
            "seed": 3001,
            "agent": ep_m_dn.agent,
            "actions": [[s.tool, s.args] for s in ep_m_dn.steps],
            "expected_verdict": env_m_dn.verdict(),
            "expected_score": ep_m_dn.score,
            "expected_score_bits": _float_bits(ep_m_dn.score),
            "expected_V": float(ep_m_dn.meta["V"]),
            "expected_V_bits": _float_bits(float(ep_m_dn.meta["V"])),
            "expected_accused": ep_m_dn.accused,
            "expected_correct": bool(ep_m_dn.correct),
            "expected_final_day": int(ep_m_dn.final_day),
            "expected_end_reason": ep_m_dn.end_reason,
            "expected_steps": [{"ok": bool(s.result["ok"]), "error": s.result.get("error")} for s in ep_m_dn.steps],
        }
    )

    mole_3002 = Env("medium", 3002)._world.mole
    wrong_emp_3002 = "e00" if mole_3002 != "e00" else "e01"
    mixed_acts_3002: list[tuple[str, dict[str, Any]]] = [
        ("list_employees", {}),
        ("interview", {"employee": "e01", "topic": "workload"}),
        ("accuse", {"employee": ["e01"]}),
        ("list_documents", {"day_from": 0}),
        ("plant_canary", {"doc_title": "Q3 board memo", "assignment": {"e00": "A", "e01": "B", "e02": "C"}}),
        ("status", {}),
        ("advance_day", {}),
        ("accuse", {"employee": wrong_emp_3002}),
    ]
    env_m_mix = Env("medium", 3002)
    ep_m_mix = run_episode(env_m_mix, RecordedActionsPolicy(mixed_acts_3002, name="arena_mixed_wrong"))
    episodes_out.append(ep_m_mix)
    cases.append(
        {
            "case_id": "medium_mixed_wrong_3002",
            "tier": "medium",
            "seed": 3002,
            "agent": ep_m_mix.agent,
            "actions": [[s.tool, s.args] for s in ep_m_mix.steps],
            "expected_verdict": env_m_mix.verdict(),
            "expected_score": ep_m_mix.score,
            "expected_score_bits": _float_bits(ep_m_mix.score),
            "expected_V": float(ep_m_mix.meta["V"]),
            "expected_V_bits": _float_bits(float(ep_m_mix.meta["V"])),
            "expected_accused": ep_m_mix.accused,
            "expected_correct": bool(ep_m_mix.correct),
            "expected_final_day": int(ep_m_mix.final_day),
            "expected_end_reason": ep_m_mix.end_reason,
            "expected_steps": [{"ok": bool(s.result["ok"]), "error": s.result.get("error")} for s in ep_m_mix.steps],
        }
    )

    mole_3000 = Env("medium", 3000)._world.mole
    zero_v_acts = _build_zero_v_actions_for_medium_seed(3000, mole_3000)
    env_m_zv = Env("medium", 3000)
    ep_m_zv = run_episode(env_m_zv, RecordedActionsPolicy(zero_v_acts, name="arena_zero_v_win"))
    episodes_out.append(ep_m_zv)
    cases.append(
        {
            "case_id": "medium_zero_v_correct_3000",
            "tier": "medium",
            "seed": 3000,
            "agent": ep_m_zv.agent,
            "actions": [[s.tool, s.args] for s in ep_m_zv.steps],
            "expected_verdict": env_m_zv.verdict(),
            "expected_score": ep_m_zv.score,
            "expected_score_bits": _float_bits(ep_m_zv.score),
            "expected_V": float(ep_m_zv.meta["V"]),
            "expected_V_bits": _float_bits(float(ep_m_zv.meta["V"])),
            "expected_accused": ep_m_zv.accused,
            "expected_correct": bool(ep_m_zv.correct),
            "expected_final_day": int(ep_m_zv.final_day),
            "expected_end_reason": ep_m_zv.end_reason,
            "expected_steps": [{"ok": bool(s.result["ok"]), "error": s.result.get("error")} for s in ep_m_zv.steps],
        }
    )

    for seed in HARD_SEEDS:
        env_h_sol = Env("hard", seed)
        ep_h_sol = run_episode(env_h_sol, SolverPolicy())
        verdict_h_sol = env_h_sol.verdict()
        episodes_out.append(ep_h_sol)
        cases.append(
            {
                "case_id": f"hard_solver_{seed}",
                "tier": "hard",
                "seed": seed,
                "agent": ep_h_sol.agent,
                "actions": [[s.tool, s.args] for s in ep_h_sol.steps],
                "expected_verdict": verdict_h_sol,
                "expected_score": ep_h_sol.score,
                "expected_score_bits": _float_bits(ep_h_sol.score),
                "expected_V": float(ep_h_sol.meta["V"]),
                "expected_V_bits": _float_bits(float(ep_h_sol.meta["V"])),
                "expected_accused": ep_h_sol.accused,
                "expected_correct": bool(ep_h_sol.correct),
                "expected_final_day": int(ep_h_sol.final_day),
                "expected_end_reason": ep_h_sol.end_reason,
                "expected_steps": [{"ok": bool(s.result["ok"]), "error": s.result.get("error")} for s in ep_h_sol.steps],
            }
        )
        solver_refs.append(
            {
                "tier": "hard",
                "seed": seed,
                "score": ep_h_sol.score,
                "score_bits": _float_bits(ep_h_sol.score),
                "accused": ep_h_sol.accused,
                "correct": bool(ep_h_sol.correct),
                "final_day": int(ep_h_sol.final_day),
                "tool_calls": len(ep_h_sol.steps),
                "verdict": verdict_h_sol,
            }
        )

    env_h_se = Env("hard", 3000)
    ep_h_se = run_episode(env_h_se, StopEarly(seed=3000))
    episodes_out.append(ep_h_se)
    cases.append(
        {
            "case_id": "hard_stop_early_3000",
            "tier": "hard",
            "seed": 3000,
            "agent": ep_h_se.agent,
            "actions": [[s.tool, s.args] for s in ep_h_se.steps],
            "expected_verdict": env_h_se.verdict(),
            "expected_score": ep_h_se.score,
            "expected_score_bits": _float_bits(ep_h_se.score),
            "expected_V": float(ep_h_se.meta["V"]),
            "expected_V_bits": _float_bits(float(ep_h_se.meta["V"])),
            "expected_accused": ep_h_se.accused,
            "expected_correct": bool(ep_h_se.correct),
            "expected_final_day": int(ep_h_se.final_day),
            "expected_end_reason": ep_h_se.end_reason,
            "expected_steps": [{"ok": bool(s.result["ok"]), "error": s.result.get("error")} for s in ep_h_se.steps],
        }
    )

    env_h_dn = Env("hard", 3001)
    ep_h_dn = run_episode(env_h_dn, DoNothing(seed=3001))
    episodes_out.append(ep_h_dn)
    cases.append(
        {
            "case_id": "hard_do_nothing_3001",
            "tier": "hard",
            "seed": 3001,
            "agent": ep_h_dn.agent,
            "actions": [[s.tool, s.args] for s in ep_h_dn.steps],
            "expected_verdict": env_h_dn.verdict(),
            "expected_score": ep_h_dn.score,
            "expected_score_bits": _float_bits(ep_h_dn.score),
            "expected_V": float(ep_h_dn.meta["V"]),
            "expected_V_bits": _float_bits(float(ep_h_dn.meta["V"])),
            "expected_accused": ep_h_dn.accused,
            "expected_correct": bool(ep_h_dn.correct),
            "expected_final_day": int(ep_h_dn.final_day),
            "expected_end_reason": ep_h_dn.end_reason,
            "expected_steps": [{"ok": bool(s.result["ok"]), "error": s.result.get("error")} for s in ep_h_dn.steps],
        }
    )

    return cases, solver_refs, episodes_out


def _build_reference_cases() -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[Any]]:
    cases, solver_refs, episodes_out = _compute_reference_cases()
    return copy.deepcopy(cases), copy.deepcopy(solver_refs), list(episodes_out)


def _repo_secret_bytes(root: Path) -> list[bytes]:
    found: list[bytes] = []
    salt_file = root / "data" / "worlds" / "judge" / "SALT"
    if salt_file.is_file():
        try:
            raw = salt_file.read_bytes().strip()
            if len(raw) >= 8:
                found.append(raw)
        except OSError:
            pass
    for env_name in ("CANARY_WORLD_SECRET", "CANARY_LEDGER_TOKEN", "CANARY_ADMIN_TOKEN"):
        val = os.environ.get(env_name, "").strip()
        if len(val) >= 8:
            found.append(val.encode("utf-8"))
    return found


def _is_int_not_bool(val: Any) -> bool:
    return isinstance(val, int) and not isinstance(val, bool)


def _is_judge_seed_int(val: Any) -> bool:
    from canary.rules import JUDGE_SEEDS

    return _is_int_not_bool(val) and (int(val) in JUDGE_SEEDS or 900_000 <= int(val) < 1_000_000)


def _collect_judge_seed_violations(node: Any, loc: str) -> list[str]:
    violations: list[str] = []
    if isinstance(node, dict):
        for k, v in node.items():
            ks = str(k)
            child_loc = f"{loc}.{ks}"
            if ks in ("seed", "case_seed", "episode_seed") and _is_judge_seed_int(v):
                violations.append(f"{child_loc}: leaked JUDGE_SEEDS seed {v}")
            elif ks in ("seeds", "case_seeds", "episode_seeds") and isinstance(v, list):
                for idx, item in enumerate(v):
                    if _is_judge_seed_int(item):
                        violations.append(f"{child_loc}[{idx}]: leaked JUDGE_SEEDS seed {item}")
            elif ks.isdigit() and _is_judge_seed_int(int(ks)):
                violations.append(f"{child_loc}: leaked JUDGE_SEEDS key {ks}")
            violations.extend(_collect_judge_seed_violations(v, child_loc))
    elif isinstance(node, list):
        for idx, item in enumerate(node):
            violations.extend(_collect_judge_seed_violations(item, f"{loc}[{idx}]"))
    return violations


def _collect_mole_truth_violations(
    node: Any,
    rel: str,
    allow_post_done_dev_reveal: bool,
    seed_ctx: int | None = None,
    in_post_done: bool = False,
    in_steps: bool = False,
    not_done_ctx: bool = False,
    done_ctx: bool = False,
) -> list[str]:
    from canary.rules import DEV_SEEDS

    violations: list[str] = []
    if isinstance(node, list):
        for item in node:
            violations.extend(
                _collect_mole_truth_violations(
                    item,
                    rel=rel,
                    allow_post_done_dev_reveal=allow_post_done_dev_reveal,
                    seed_ctx=seed_ctx,
                    in_post_done=in_post_done,
                    in_steps=in_steps,
                    not_done_ctx=not_done_ctx,
                    done_ctx=done_ctx,
                )
            )
        return violations
    if not isinstance(node, dict):
        return violations

    cur_seed = seed_ctx
    for sk in ("seed", "case_seed", "episode_seed"):
        if _is_int_not_bool(node.get(sk)):
            cur_seed = int(node[sk])

    node_not_done = (
        node.get("done") is False
        or node.get("episode_over") is False
        or node.get("human_done") is False
        or node.get("humanDone") is False
    )
    node_done = (
        node.get("done") is True
        or node.get("episode_over") is True
        or node.get("human_done") is True
        or node.get("humanDone") is True
    )
    cur_not_done = not_done_ctx or node_not_done
    cur_done = (done_ctx or node_done) and not cur_not_done

    for mk in sorted(MOLE_TRUTH_FIELD_NAMES):
        if mk in node and isinstance(node[mk], str) and EMP_ID_VALUE_RE.match(node[mk]):
            is_public_dev = cur_seed is not None and cur_seed in DEV_SEEDS and not _is_judge_seed_int(cur_seed)
            allowed = (
                allow_post_done_dev_reveal
                and is_public_dev
                and not cur_not_done
                and not in_steps
                and (in_post_done or cur_done)
            )
            if not allowed:
                violations.append(
                    f'{rel}: leaked mole ground truth (mole_ground_truth_json: "{mk}": "{node[mk]}")'
                )

    for k, v in node.items():
        ks = str(k)
        child_seed = int(ks) if ks.isdigit() else cur_seed
        child_in_post_done = in_post_done or (ks in POST_DONE_REVEAL_KEYS and not cur_not_done)
        child_in_steps = in_steps or (ks in PRE_END_STEP_KEYS)
        violations.extend(
            _collect_mole_truth_violations(
                v,
                rel=rel,
                allow_post_done_dev_reveal=allow_post_done_dev_reveal,
                seed_ctx=child_seed,
                in_post_done=child_in_post_done,
                in_steps=child_in_steps,
                not_done_ctx=cur_not_done,
                done_ctx=cur_done,
            )
        )
    return violations


def _extract_js_json_from_block(text: str, base_offset: int, rel_label: str) -> tuple[list[tuple[str, Any]], list[tuple[int, int]]]:
    decoder = json.JSONDecoder()
    payloads: list[tuple[str, Any]] = []
    spans: list[tuple[int, int]] = []
    for match in JS_JSON_ASSIGN_RE.finditer(text):
        pos = match.end()
        while pos < len(text) and text[pos].isspace():
            pos += 1
        if pos >= len(text) or text[pos] not in "{[":
            continue
        try:
            obj, end_pos = decoder.raw_decode(text, pos)
        except json.JSONDecodeError:
            continue
        lhs = match.group(0).split("=")[0].strip()
        payloads.append((f"{rel_label}:{lhs}", obj))
        spans.append((base_offset + pos, base_offset + end_pos))
    return payloads, spans


def _extract_structured_payloads(
    content: str,
    suffix: str,
    rel: str,
) -> tuple[list[tuple[str, Any]], list[tuple[int, int]]]:
    payloads: list[tuple[str, Any]] = []
    spans: list[tuple[int, int]] = []
    if suffix == ".json":
        try:
            payloads.append((rel, json.loads(content)))
            spans.append((0, len(content)))
        except json.JSONDecodeError:
            pass
    elif suffix == ".jsonl":
        all_ok = True
        for line_no, line in enumerate(content.splitlines(), start=1):
            if not line.strip():
                continue
            try:
                payloads.append((f"{rel}:{line_no}", json.loads(line)))
            except json.JSONDecodeError:
                all_ok = False
        if all_ok:
            spans.append((0, len(content)))
    elif suffix in (".js", ".mjs", ".cjs"):
        p_js, s_js = _extract_js_json_from_block(content, 0, rel)
        payloads.extend(p_js)
        spans.extend(s_js)
    elif suffix in (".html", ".htm"):
        for idx, m_json in enumerate(HTML_JSON_SCRIPT_RE.finditer(content)):
            body = m_json.group(1)
            if not body.strip():
                continue
            try:
                payloads.append((f"{rel}:json_script[{idx}]", json.loads(body)))
                spans.append((m_json.start(1), m_json.end(1)))
            except json.JSONDecodeError:
                pass
        for idx, m_scr in enumerate(HTML_SCRIPT_RE.finditer(content)):
            body = m_scr.group(1)
            p_scr, s_scr = _extract_js_json_from_block(body, m_scr.start(1), f"{rel}:script[{idx}]")
            payloads.extend(p_scr)
            spans.extend(s_scr)
    return payloads, spans


def _mask_spans(content: str, spans: list[tuple[int, int]]) -> str:
    if not spans:
        return content
    chars = list(content)
    for start, end in spans:
        lo = max(0, start)
        hi = min(len(chars), end)
        for idx in range(lo, hi):
            if chars[idx] != "\n":
                chars[idx] = " "
    return "".join(chars)


def scan_static_tree_for_leaks(
    base_dir: Path,
    check_mole_truth: bool = True,
    allow_arena_data_dir: bool = False,
    allow_post_done_dev_reveal: bool = False,
    root: Path = ROOT,
) -> list[str]:
    violations: list[str] = []
    repo_secrets = _repo_secret_bytes(root)
    forbidden_prefixes = (
        FORBIDDEN_ARENA_ROOT_REL_PREFIXES if allow_arena_data_dir else FORBIDDEN_BUNDLE_REL_PREFIXES
    )

    for path in sorted(base_dir.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(base_dir).as_posix()
        if any(rel.startswith(pref) or f"/{pref}" in f"/{rel}" for pref in forbidden_prefixes):
            violations.append(f"{rel}: forbidden directory shipped in static bundle")
        if (
            path.name in FORBIDDEN_BUNDLE_FILENAMES
            or path.name.endswith(".world.json")
            or (path.name.startswith(".env.") and path.name not in ALLOWED_ENV_TEMPLATES)
        ):
            violations.append(f"{rel}: forbidden file shipped in static bundle")

        try:
            raw_bytes = path.read_bytes()
        except OSError:
            continue

        for secret_bytes in repo_secrets:
            if secret_bytes in raw_bytes:
                violations.append(f"{rel}: leaked raw repository secret/SALT bytes")
                break

        suffix = path.suffix.lower()
        if suffix not in TEXT_ASSET_SUFFIXES or b"\x00" in raw_bytes:
            continue

        content = raw_bytes.decode("utf-8", errors="replace")
        for pat_name, pat in SECRET_PATTERNS:
            m = pat.search(content)
            if m is not None:
                violations.append(f"{rel}: leaked secret pattern {pat_name}")
        if suffix in (".html", ".htm", ".json", ".jsonl", ".css") and STRICT_SECRET_PATH_RE.search(content):
            violations.append(f"{rel}: leaked forbidden SALT or CANARY_WORLD_SECRET reference")

        if suffix in STRUCTURED_ASSET_SUFFIXES:
            payloads, spans = _extract_structured_payloads(content, suffix, rel)
            for ploc, pobj in payloads:
                violations.extend(_collect_judge_seed_violations(pobj, ploc))
                if check_mole_truth:
                    violations.extend(
                        _collect_mole_truth_violations(
                            pobj,
                            rel=rel,
                            allow_post_done_dev_reveal=allow_post_done_dev_reveal,
                        )
                    )
            unmasked = _mask_spans(content, spans)
            m_judge = JUDGE_SEED_JS_RE.search(unmasked)
            if m_judge is not None:
                violations.append(f"{rel}: leaked JUDGE_SEEDS seed ({m_judge.group(0).strip()})")
            if check_mole_truth:
                for pat_name, pat in MOLE_GROUND_TRUTH_PATTERNS:
                    for m in pat.finditer(unmasked):
                        win_lo = max(0, m.start() - 600)
                        win_hi = min(len(unmasked), m.end() + 600)
                        win_txt = unmasked[win_lo:win_hi]
                        is_gated_reveal = (
                            allow_post_done_dev_reveal
                            and suffix in (".js", ".mjs", ".cjs", ".html", ".htm")
                            and bool(JS_POST_DONE_SYMBOL_RE.search(win_txt))
                            and bool(JS_POST_DONE_GATE_RE.search(win_txt))
                            and not bool(
                                re.search(
                                    r"(?:done|humanDone|human_done)\s*:\s*false",
                                    win_txt,
                                )
                            )
                            and not bool(JUDGE_SEED_JS_RE.search(win_txt))
                        )
                        if not is_gated_reveal:
                            violations.append(
                                f"{rel}: leaked mole ground truth ({pat_name}: {m.group(0).strip()})"
                            )
                            break
        elif check_mole_truth and suffix == ".py":
            for pat_name, pat in MOLE_GROUND_TRUTH_PATTERNS:
                m = pat.search(content)
                if m is not None:
                    violations.append(f"{rel}: leaked mole ground truth ({pat_name}: {m.group(0).strip()})")
    return violations


def run_isolated_bundle_check(
    py_dir: Path,
    cases: list[dict[str, Any]],
    solver_refs: list[dict[str, Any]],
    repo_root: Path,
    work_tmp_dir: Path,
    require_canary_game: bool = True,
) -> tuple[list[str], dict[str, Any]]:
    violations: list[str] = []
    sandbox_cwd = work_tmp_dir / "isolated_cwd"
    sandbox_cwd.mkdir(parents=True, exist_ok=True)
    payload_path = work_tmp_dir / "isolated_payload.json"
    worker_payload = {
        "cases": [
            {
                "case_id": c["case_id"],
                "tier": c["tier"],
                "seed": c["seed"],
                "agent": c["agent"],
                "actions": c["actions"],
            }
            for c in cases
        ],
        "solver_runs": [{"tier": s["tier"], "seed": s["seed"]} for s in solver_refs],
    }
    payload_path.write_text(json.dumps(worker_payload), encoding="utf-8")

    clean_env = {
        "PATH": os.environ.get("PATH", ""),
        "LANG": os.environ.get("LANG", "C.UTF-8"),
        "LC_ALL": os.environ.get("LC_ALL", "C.UTF-8"),
    }
    has_game_mod = (py_dir / "canary_game.py").is_file()
    if require_canary_game and not has_game_mod:
        violations.append(f"missing canary_game.py in {py_dir}")
        return violations, {}

    proc = subprocess.run(
        [
            sys.executable,
            "-I",
            "-S",
            "-c",
            _ISOLATED_PYODIDE_WORKER,
            str(py_dir.resolve()),
            str(payload_path.resolve()),
            str(repo_root.resolve()),
            "1" if has_game_mod else "0",
        ],
        cwd=str(sandbox_cwd),
        env=clean_env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    if proc.returncode != 0:
        err_tail = (proc.stderr or proc.stdout or "").strip()[-1200:]
        violations.append(f"isolated python -I -S subprocess failed (rc={proc.returncode}): {err_tail}")
        return violations, {}

    out = json.loads(proc.stdout.strip().splitlines()[-1])
    if out.get("sys_path", [None])[0] != str(py_dir.resolve()):
        violations.append(f"isolated sys.path[0] mismatch: {out.get('sys_path')}")
    for entry in out.get("sys_path", [])[1:]:
        if "site-packages" in entry or str(repo_root.resolve()) in entry:
            violations.append(f"non-isolated path leaked into subprocess sys.path: {entry}")
    if out.get("outside_bundle"):
        violations.append(f"modules loaded from outside bundle py_dir: {out['outside_bundle']}")
    for mod_name, is_blocked in sorted((out.get("blocked_imports") or {}).items()):
        if not is_blocked:
            violations.append(f"forbidden module {mod_name} was importable inside isolated Pyodide bundle")
    if has_game_mod and not out.get("seed_guards_ok"):
        violations.append("canary_game.Game failed benchmark/judge/bad seed refusal guard inside bundle")
    if has_game_mod and not out.get("pre_end_guard_ok"):
        violations.append("canary_game.Game leaked truth or made hidden calls before episode end")

    by_case_id = {c["case_id"]: c for c in out.get("cases", [])}
    for exp in cases:
        cid = exp["case_id"]
        got = by_case_id.get(cid)
        if got is None:
            violations.append(f"{cid}: missing from isolated bundle output")
            continue
        if got["score"] != exp["expected_score"] or got["score_bits"] != exp["expected_score_bits"]:
            violations.append(
                f"{cid}: score mismatch bundle={got['score']} ({got['score_bits']}) "
                f"vs eval={exp['expected_score']} ({exp['expected_score_bits']})"
            )
        if got["V"] != exp["expected_V"] or got["V_bits"] != exp["expected_V_bits"]:
            violations.append(
                f"{cid}: V mismatch bundle={got['V']} ({got['V_bits']}) "
                f"vs eval={exp['expected_V']} ({exp['expected_V_bits']})"
            )
        if got["accused"] != exp["expected_accused"]:
            violations.append(f"{cid}: accused mismatch bundle={got['accused']!r} vs eval={exp['expected_accused']!r}")
        if bool(got["correct"]) is not bool(exp["expected_correct"]):
            violations.append(f"{cid}: correct mismatch bundle={got['correct']!r} vs eval={exp['expected_correct']!r}")
        if int(got["final_day"]) != int(exp["expected_final_day"]):
            violations.append(f"{cid}: final_day mismatch bundle={got['final_day']} vs eval={exp['expected_final_day']}")
        if got["end_reason"] != exp["expected_end_reason"]:
            violations.append(
                f"{cid}: end_reason mismatch bundle={got['end_reason']!r} vs eval={exp['expected_end_reason']!r}"
            )
        if got["verdict"] != exp["expected_verdict"]:
            violations.append(f"{cid}: verdict dict mismatch bundle={got['verdict']} vs eval={exp['expected_verdict']}")
        if got["step_summaries"] != exp["expected_steps"]:
            violations.append(f"{cid}: step ok/error sequence diverged between bundle and canary.eval")

        if has_game_mod and exp["tier"] == "medium" and 3000 <= int(exp["seed"]) <= 9999:
            if got.get("game_verdict") != exp["expected_verdict"]:
                violations.append(f"{cid}: canary_game.Game verdict mismatch vs canary.eval")
            if got.get("game_replay_verdict") != exp["expected_verdict"]:
                violations.append(f"{cid}: canary_game.replay verdict mismatch vs canary.eval")
            rev_you = got.get("game_reveal_you")
            if rev_you is None:
                violations.append(f"{cid}: canary_game.Game did not finish or reveal_json missing 'you'")
            else:
                if (
                    rev_you["score"] != exp["expected_score"]
                    or rev_you["accused"] != exp["expected_accused"]
                    or bool(rev_you["correct"]) is not bool(exp["expected_correct"])
                    or int(rev_you["final_day"]) != int(exp["expected_final_day"])
                    or rev_you["end_reason"] != exp["expected_end_reason"]
                    or int(rev_you["tool_calls"]) != len(exp["expected_steps"])
                ):
                    violations.append(f"{cid}: canary_game.reveal_json()['you'] mismatch vs canary.eval: {rev_you}")

    by_solver_key = {(s["tier"], int(s["seed"])): s for s in out.get("solver_runs", [])}
    for exp_s in solver_refs:
        s_key = (exp_s["tier"], int(exp_s["seed"]))
        got_s = by_solver_key.get(s_key)
        if got_s is None:
            violations.append(f"solver_result {s_key}: missing from isolated bundle output")
            continue
        if (
            got_s["score"] != exp_s["score"]
            or got_s["score_bits"] != exp_s["score_bits"]
            or got_s["accused"] != exp_s["accused"]
            or bool(got_s["correct"]) is not bool(exp_s["correct"])
            or int(got_s["final_day"]) != int(exp_s["final_day"])
            or int(got_s["tool_calls"]) != int(exp_s["tool_calls"])
            or got_s["verdict"] != exp_s["verdict"]
        ):
            violations.append(f"solver_result {s_key}: mismatch bundle={got_s} vs eval={exp_s}")
        if has_game_mod and exp_s["tier"] == "medium":
            cg_sr = got_s.get("canary_game_solver_result")
            expected_cg_sr = {
                "score": exp_s["score"],
                "correct": exp_s["correct"],
                "final_day": exp_s["final_day"],
                "tool_calls": exp_s["tool_calls"],
            }
            if cg_sr != expected_cg_sr or _float_bits(cg_sr["score"]) != exp_s["score_bits"]:
                violations.append(
                    f"canary_game.solver_result({exp_s['seed']}) mismatch: got={cg_sr} vs eval={expected_cg_sr}"
                )

    return violations, out


def verify_pyodide_bundle_isolation_parity(root: Path = ROOT) -> tuple[GateResult, list[Any]]:
    cases, solver_refs, episodes = _build_reference_cases()
    violations: list[str] = []
    bundle_meta: dict[str, Any] = {}

    with temporary_opencode_dir("arena_pyodide_bundle_") as tmp_dir:
        site_dir = tmp_dir / "site"
        game_build = _load_game_build_module(root)
        manifest = game_build.build(site_dir)

        manifest_path = site_dir / "py" / "manifest.json"
        if not manifest_path.is_file():
            violations.append("py/manifest.json missing after game/build.py build()")
            manifest_disk = {"files": []}
        else:
            manifest_disk = json.loads(manifest_path.read_text(encoding="utf-8"))

        if manifest != manifest_disk:
            violations.append("returned manifest from build() differs from py/manifest.json on disk")

        manifest_files = list(manifest_disk.get("files") or [])
        actual_py_files = sorted(
            p.relative_to(site_dir / "py").as_posix() for p in (site_dir / "py").rglob("*.py")
        )
        if sorted(manifest_files) != actual_py_files:
            violations.append(
                f"manifest.json files mismatch actual .py files: manifest={sorted(manifest_files)} actual={actual_py_files}"
            )

        for required_static in ("index.html", "app.js", "style.css"):
            if not (site_dir / required_static).is_file():
                violations.append(f"missing static file in built bundle: {required_static}")

        for forbidden_rel in ("data", "results", "redteam", "harbor", "SALT", "mcp_server.py"):
            if (site_dir / forbidden_rel).exists() or (site_dir / "py" / forbidden_rel).exists():
                violations.append(f"forbidden path shipped in built bundle: {forbidden_rel}")

        violations.extend(
            scan_static_tree_for_leaks(
                site_dir,
                check_mole_truth=True,
                allow_arena_data_dir=False,
                allow_post_done_dev_reveal=False,
                root=root,
            )
        )

        pyodide_fs_dir = tmp_dir / "pyodide_home" / "py"
        pyodide_fs_dir.mkdir(parents=True, exist_ok=True)
        for rel_file in manifest_files:
            src_file = site_dir / "py" / rel_file
            dst_file = pyodide_fs_dir / rel_file
            dst_file.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src_file, dst_file)

        iso_violations, iso_out = run_isolated_bundle_check(
            py_dir=site_dir / "py",
            cases=cases,
            solver_refs=solver_refs,
            repo_root=root,
            work_tmp_dir=tmp_dir / "work_site",
            require_canary_game=True,
        )
        violations.extend(iso_violations)

        manifest_only_violations, _ = run_isolated_bundle_check(
            py_dir=pyodide_fs_dir,
            cases=cases[:3] + [c for c in cases if c["tier"] == "hard"][:1],
            solver_refs=solver_refs[:1],
            repo_root=root,
            work_tmp_dir=tmp_dir / "work_manifest_only",
            require_canary_game=True,
        )
        violations.extend(f"manifest_only_fs: {v}" for v in manifest_only_violations)

        bundle_meta = {
            "manifest_file_count": len(manifest_files),
            "loaded_module_count": len(iso_out.get("loaded_modules", {})),
            "cases_verified": len(cases),
            "solver_seeds_verified": len(solver_refs),
            "medium_seeds": list(MEDIUM_SEEDS),
            "hard_seeds": list(HARD_SEEDS),
            "tmp_dir_cleaned_after_gate": False,
        }
        created_tmp_path = tmp_dir

    if created_tmp_path.exists():
        violations.append(f"temporary build dir was not deleted: {created_tmp_path}")
    else:
        bundle_meta["tmp_dir_cleaned_after_gate"] = True

    summary = (
        f"Pyodide isolated bundle ({bundle_meta['manifest_file_count']} py files, python -I -S) "
        f"bit-identical to canary.eval.run_episode across {len(cases)} medium/hard trajectories "
        f"and {len(solver_refs)} solver_result checks"
    )
    return (
        GateResult(
            gate="pyodide_bundle_isolation_parity",
            passed=len(violations) == 0,
            summary=summary,
            violations=violations,
            data=bundle_meta,
        ),
        episodes,
    )


def arena_mean_ci(scores: list[float]) -> tuple[float, float]:
    n = len(scores)
    if n == 0:
        return float("nan"), float("nan")
    mean_val = sum(scores) / n
    if n < 2:
        return mean_val, 0.0
    variance = sum((x - mean_val) ** 2 for x in scores) / (n - 1)
    return mean_val, 1.96 * math.sqrt(variance) / math.sqrt(n)


def episode_to_arena_record(ep: Any) -> dict[str, Any]:
    meta = ep.meta if isinstance(ep.meta, dict) else {}
    return {
        "tier": str(ep.tier),
        "seed": int(ep.seed),
        "agent": str(ep.agent),
        "score": float(ep.score),
        "accused": ep.accused,
        "correct": bool(ep.correct),
        "final_day": int(ep.final_day),
        "end_reason": str(ep.end_reason),
        "tool_calls": len(ep.steps),
        "V": float(meta.get("V", max(0.0, float(ep.score)))),
    }


def roundtrip_localstorage_json(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    raw = json.dumps(records, allow_nan=False, sort_keys=True)
    loaded = json.loads(raw)
    if not isinstance(loaded, list):
        raise ValueError("expected list of LocalStorage records")
    return loaded


def aggregate_arena_leaderboard(records: list[dict[str, Any]]) -> dict[str, Any]:
    stored = roundtrip_localstorage_json(records)
    n = len(stored)
    scores = [float(r["score"]) for r in stored]
    mean_val, ci_val = arena_mean_ci(scores)
    accused_days = [int(r["final_day"]) for r in stored if r.get("end_reason") == "accused"]
    accuracy_val = (sum(1 for r in stored if bool(r["correct"])) / n) if n > 0 else float("nan")
    accuse_day_val = (sum(accused_days) / len(accused_days)) if accused_days else float("nan")
    return {
        "n": n,
        "mean": mean_val,
        "ci": ci_val,
        "accuracy": accuracy_val,
        "accuse_day": accuse_day_val,
        "accused": len(accused_days),
    }


def format_arena_metric(val: float, nd: int = 3, sign: bool = False) -> str:
    if math.isnan(val):
        return "-"
    return f"{val:+.{nd}f}" if sign else f"{val:.{nd}f}"


def format_arena_leaderboard_table(agent: str, by_tier_records: dict[str, list[dict[str, Any]]]) -> str:
    header_score = f"score {PLUS_MINUS} 95% CI"
    rows = [
        f"{'tier':<7} {'agent':<18} {'n':>4} {header_score:>18} {'accuracy':>9} {'accused':>8} {'accuse day':>11}"
    ]
    for tier, records in by_tier_records.items():
        s = aggregate_arena_leaderboard(records)
        score_col = f"{format_arena_metric(s['mean'], sign=True)} {PLUS_MINUS} {format_arena_metric(s['ci'])}"
        rows.append(
            f"{tier:<7} {agent:<18} {s['n']:>4} {score_col:>18} {format_arena_metric(s['accuracy'], 2):>9} "
            f"{s['accused']:>8} {format_arena_metric(s['accuse_day'], 1):>11}"
        )
    return "\n".join(rows)


def _compare_summaries(
    cohort_name: str,
    arena_sum: dict[str, Any],
    eval_sum: dict[str, Any],
    tol: float = PARITY_TOL,
) -> list[str]:
    errs: list[str] = []
    for int_key in ("n", "accused"):
        if int(arena_sum[int_key]) != int(eval_sum[int_key]):
            errs.append(f"{cohort_name}.{int_key}: arena={arena_sum[int_key]} vs eval={eval_sum[int_key]}")
    for float_key in ("mean", "ci", "accuracy", "accuse_day"):
        a_val = float(arena_sum[float_key])
        e_val = float(eval_sum[float_key])
        a_nan = math.isnan(a_val)
        e_nan = math.isnan(e_val)
        if a_nan != e_nan:
            errs.append(f"{cohort_name}.{float_key}: NaN mismatch arena={a_val} vs eval={e_val}")
        elif not a_nan and abs(a_val - e_val) > tol:
            errs.append(
                f"{cohort_name}.{float_key}: diff={abs(a_val - e_val):.3e} exceeds tol={tol:.1e} "
                f"(arena={a_val!r}, eval={e_val!r})"
            )
    return errs


def verify_leaderboard_and_summary_parity(real_episodes: list[Any] | None = None) -> GateResult:
    from canary.analysis.gap import mean_ci as gap_mean_ci
    from canary.eval import format_table as eval_format_table
    from canary.eval import summarize as eval_summarize
    from canary.types import EpisodeResult

    if real_episodes is None:
        _, _, real_episodes = _build_reference_cases()

    def _mk_ep(
        tier: str,
        seed: int,
        score: float,
        accused: str | None,
        correct: bool,
        final_day: int,
        end_reason: str,
        v_val: float,
        agent: str = "arena_player",
    ) -> EpisodeResult:
        return EpisodeResult(
            tier=tier,
            seed=seed,
            agent=agent,
            steps=[],
            score=score,
            accused=accused,
            correct=correct,
            final_day=final_day,
            end_reason=end_reason,
            meta={"provider": "template", "V": v_val},
        )

    cohorts: dict[str, dict[str, list[EpisodeResult]]] = {
        "real_played_multi_tier": {
            "medium": [e for e in real_episodes if e.tier == "medium"],
            "hard": [e for e in real_episodes if e.tier == "hard"],
        },
        "mixed_wins_wrongs_abstentions": {
            "medium": [
                _mk_ep("medium", 3100, 0.88, "e04", True, 4, "accused", 0.88),
                _mk_ep("medium", 3101, -1.0, "e09", False, 2, "accused", 0.95),
                _mk_ep("medium", 3102, 0.0, None, False, 14, "horizon", 0.62),
                _mk_ep("medium", 3103, 0.71, "e12", True, 7, "accused", 0.71),
                _mk_ep("medium", 3104, 0.0, None, False, 9, "tool_cap", 0.80),
                _mk_ep("medium", 3105, -1.0, "e01", False, 5, "accused", 0.84),
            ],
            "hard": [
                _mk_ep("hard", 3200, 0.63, "e21", True, 8, "accused", 0.63),
                _mk_ep("hard", 3201, 0.0, None, False, 21, "horizon", 0.35),
                _mk_ep("hard", 3202, -1.0, "e17", False, 6, "accused", 0.79),
            ],
        },
        "zero_v_edge_cases": {
            "medium": [
                _mk_ep("medium", 3300, 0.0, "e03", True, 7, "accused", 0.0),
                _mk_ep("medium", 3301, -1.0, "e05", False, 8, "accused", 0.0),
                _mk_ep("medium", 3302, 0.0, None, False, 14, "horizon", 0.0),
                _mk_ep("medium", 3303, 0.75, "e11", True, 6, "accused", 0.75),
            ]
        },
        "all_abstentions_nan_accuse_day": {
            "medium": [
                _mk_ep("medium", 3400, 0.0, None, False, 14, "horizon", 0.52),
                _mk_ep("medium", 3401, 0.0, None, False, 11, "tool_cap", 0.77),
                _mk_ep("medium", 3402, 0.0, None, False, 14, "horizon", 0.0),
            ]
        },
        "all_wrong_accusations": {
            "hard": [
                _mk_ep("hard", 3500, -1.0, "e00", False, 3, "accused", 0.90),
                _mk_ep("hard", 3501, -1.0, "e02", False, 5, "accused", 0.85),
                _mk_ep("hard", 3502, -1.0, "e08", False, 10, "accused", 0.40),
            ]
        },
        "singleton_n1_zero_ci": {
            "medium": [_mk_ep("medium", 3600, 0.81, "e06", True, 5, "accused", 0.81)],
            "hard": [_mk_ep("hard", 3601, 0.0, None, False, 21, "horizon", 0.45)],
        },
        "empty_cohort_nan_all": {
            "medium": [],
            "hard": [],
        },
    }

    violations: list[str] = []
    checked_tiers = 0
    for cohort_name, by_tier_eps in cohorts.items():
        by_tier_records = {
            tier: [episode_to_arena_record(ep) for ep in eps] for tier, eps in by_tier_eps.items()
        }
        for tier, eps in by_tier_eps.items():
            checked_tiers += 1
            records = by_tier_records[tier]
            arena_sum = aggregate_arena_leaderboard(records)
            eval_sum = eval_summarize(eps)
            violations.extend(_compare_summaries(f"{cohort_name}[{tier}]", arena_sum, eval_sum, tol=PARITY_TOL))

            raw_scores = [ep.score for ep in eps]
            am, ah = arena_mean_ci(raw_scores)
            gm, gh = gap_mean_ci(raw_scores)
            if math.isnan(am) != math.isnan(gm) or (not math.isnan(am) and abs(am - gm) > PARITY_TOL):
                violations.append(f"{cohort_name}[{tier}]: arena_mean_ci mean mismatch vs canary.analysis.gap.mean_ci")
            if math.isnan(ah) != math.isnan(gh) or (not math.isnan(ah) and abs(ah - gh) > PARITY_TOL):
                violations.append(f"{cohort_name}[{tier}]: arena_mean_ci ci mismatch vs canary.analysis.gap.mean_ci")

        arena_tbl = format_arena_leaderboard_table("arena_player", by_tier_records)
        eval_tbl = eval_format_table("arena_player", by_tier_eps)
        if arena_tbl != eval_tbl:
            violations.append(
                f"{cohort_name}: formatted table mismatch\n--- arena ---\n{arena_tbl}\n--- eval ---\n{eval_tbl}"
            )

    zero_v_summary = aggregate_arena_leaderboard(
        [episode_to_arena_record(ep) for ep in cohorts["zero_v_edge_cases"]["medium"]]
    )
    if abs(zero_v_summary["accuracy"] - 0.5) > PARITY_TOL or zero_v_summary["accused"] != 3:
        violations.append(f"zero_v_edge_cases invariant broken: {zero_v_summary}")

    abstain_tbl = format_arena_leaderboard_table(
        "arena_player",
        {"medium": [episode_to_arena_record(ep) for ep in cohorts["all_abstentions_nan_accuse_day"]["medium"]]},
    )
    if not abstain_tbl.splitlines()[-1].rstrip().endswith(" -"):
        violations.append(f"NaN accuse_day did not format to '-' in table: {abstain_tbl}")

    summary = (
        f"LocalStorage leaderboard aggregation & table formatting match canary.eval.summarize / "
        f"format_table within {PARITY_TOL:.0e} across {len(cohorts)} cohorts ({checked_tiers} tier slices)"
    )
    return GateResult(
        gate="leaderboard_and_summary_math_parity",
        passed=len(violations) == 0,
        summary=summary,
        violations=violations,
        data={
            "cohorts_verified": len(cohorts),
            "tier_slices_verified": checked_tiers,
            "tolerance": PARITY_TOL,
            "zero_v_accuracy": zero_v_summary["accuracy"],
            "zero_v_accused": zero_v_summary["accused"],
        },
    )


def _is_sealed_token(val: Any) -> bool:
    return isinstance(val, str) and (
        val == "[SEALED]"
        or val.startswith("sealed:")
        or val.startswith("b64:")
        or val.startswith("sha256:")
        or val.startswith("xor:")
    )


def _is_client_only_step(step_dict: dict[str, Any], known_specs: Any) -> bool:
    tool = step_dict.get("tool")
    res = step_dict.get("result")
    return (
        tool not in known_specs
        and isinstance(res, dict)
        and res.get("ok") is False
        and isinstance(res.get("error"), str)
        and res["error"].startswith("Model tried to call unavailable tool")
    )


def _replay_recorded_item_with_eval(item: dict[str, Any], loc: str, root: Path = ROOT) -> list[str]:
    from canary.env import Env, _SPECS
    from canary.eval import MAX_ITERS, run_episode
    from canary.rules import HELDOUT_SEEDS, JUDGE_SEEDS, tier_params_for_episode, tiers_version
    from canary.solver.policy import SolverPolicy

    errs: list[str] = []
    if (item.get("meta") or {}).get("valid") is False:
        return errs

    if not _is_int_not_bool(item.get("seed")):
        return errs
    seed = int(item["seed"])
    if (seed in JUDGE_SEEDS or seed in HELDOUT_SEEDS) and not os.environ.get("CANARY_WORLD_SECRET"):
        salt_file = root / "data" / "worlds" / "judge" / "SALT"
        if not salt_file.is_file():
            return errs

    tier = str(item.get("tier", "medium"))
    steps_raw = item.get("steps")
    actions_raw = item.get("actions")

    action_pairs: list[tuple[str, dict[str, Any]]] | None = None
    inferred_version: str | None = item.get("tiers_version") or (item.get("meta") or {}).get("tiers_version")

    if isinstance(steps_raw, list):
        filtered_steps = [
            s for s in steps_raw if isinstance(s, dict) and "tool" in s and not _is_client_only_step(s, _SPECS)
        ]
        for st in filtered_steps:
            if st.get("tool") == "accuse" and isinstance(st.get("args"), dict):
                if _is_sealed_token(st["args"].get("employee")):
                    return errs
        action_pairs = [(str(s["tool"]), dict(s.get("args") or {})) for s in filtered_steps]
        if inferred_version is None:
            tp = tier_params_for_episode(tier, filtered_steps)
            if tier == "hard" and tp.n_employees == 30:
                inferred_version = "v1.3"
    elif isinstance(actions_raw, list):
        for pair in actions_raw:
            if isinstance(pair, (list, tuple)) and len(pair) == 2 and pair[0] == "accuse" and isinstance(pair[1], dict):
                if _is_sealed_token(pair[1].get("employee")):
                    return errs
        action_pairs = [
            (str(pair[0]), dict(pair[1] or {}))
            for pair in actions_raw
            if isinstance(pair, (list, tuple)) and len(pair) == 2
        ]

    ctx = tiers_version(inferred_version) if inferred_version in ("v1.2", "v1.3", "v1.4") else contextlib.nullcontext()
    with ctx:
        if action_pairs is not None:
            env = Env(tier, seed)
            pol = RecordedActionsPolicy(action_pairs, name=str(item.get("agent", "arena_trace")))
            if len(action_pairs) < MAX_ITERS:
                replayed = run_episode(env, pol)
            else:
                replayed = run_episode(env, pol, max_iters=len(action_pairs) + 1)
        elif item.get("agent") == "solver":
            env = Env(tier, seed)
            replayed = run_episode(env, SolverPolicy())
        else:
            return errs

    verdict_sub = item.get("verdict") if isinstance(item.get("verdict"), dict) else None
    final_sub = item.get("final") if isinstance(item.get("final"), dict) else None

    expected_score: float | None = None
    for src in (item, verdict_sub, final_sub):
        if isinstance(src, dict) and isinstance(src.get("score"), (int, float)) and not isinstance(src.get("score"), bool):
            expected_score = float(src["score"])
            break

    if expected_score is not None and abs(replayed.score - expected_score) > PARITY_TOL:
        errs.append(f"{loc}: score mismatch recorded={expected_score} vs canary.eval={replayed.score}")

    for src in (item, verdict_sub, final_sub):
        if isinstance(src, dict) and "accused" in src and not _is_sealed_token(src["accused"]):
            if replayed.accused != src["accused"]:
                errs.append(f"{loc}: accused mismatch recorded={src['accused']!r} vs canary.eval={replayed.accused!r}")
            break

    for src in (item, verdict_sub, final_sub):
        if isinstance(src, dict) and isinstance(src.get("correct"), bool):
            if bool(replayed.correct) is not bool(src["correct"]):
                errs.append(f"{loc}: correct mismatch recorded={src['correct']!r} vs canary.eval={replayed.correct!r}")
            break

    for src in (item, verdict_sub, final_sub):
        if isinstance(src, dict) and _is_int_not_bool(src.get("final_day")):
            if int(replayed.final_day) != int(src["final_day"]):
                errs.append(f"{loc}: final_day mismatch recorded={src['final_day']} vs canary.eval={replayed.final_day}")
            break
    return errs


def _collect_replay_candidates_from_json(node: Any, prefix: str) -> list[tuple[str, dict[str, Any]]]:
    found: list[tuple[str, dict[str, Any]]] = []
    if isinstance(node, dict):
        has_seed = _is_int_not_bool(node.get("seed"))
        has_trace = isinstance(node.get("steps"), list) or isinstance(node.get("actions"), list)
        has_grade = (
            ("score" in node and not _is_sealed_token(node.get("score")))
            or isinstance(node.get("verdict"), dict)
            or isinstance(node.get("final"), dict)
        )
        if has_seed and has_trace and has_grade:
            found.append((prefix, node))
            return found
        for k, v in node.items():
            ks = str(k)
            if ks in POST_DONE_REVEAL_KEYS or ks in PRE_END_STEP_KEYS:
                continue
            found.extend(_collect_replay_candidates_from_json(v, f"{prefix}.{ks}"))
    elif isinstance(node, list):
        for idx, elem in enumerate(node):
            found.extend(_collect_replay_candidates_from_json(elem, f"{prefix}[{idx}]"))
    return found


def _audit_arena_json_parity(arena_dir: Path, root: Path = ROOT) -> tuple[list[str], int, int]:
    from canary.env import Env
    from canary.eval import run_episode
    from canary.solver.policy import SolverPolicy

    violations: list[str] = []
    manifests_checked = 0
    episodes_replayed = 0

    arena_py_dir = arena_dir / "py"
    if arena_py_dir.is_dir():
        py_leaks = scan_static_tree_for_leaks(
            arena_py_dir,
            check_mole_truth=True,
            allow_arena_data_dir=False,
            allow_post_done_dev_reveal=False,
            root=root,
        )
        violations.extend(f"docs/arena/py/{v}" for v in py_leaks)

    for manifest_path in sorted(arena_dir.rglob("manifest.json")):
        rel_m = manifest_path.relative_to(arena_dir).as_posix()
        manifests_checked += 1
        try:
            m_data = json.loads(manifest_path.read_text(encoding="utf-8"))
        except ValueError as exc:
            violations.append(f"docs/arena/{rel_m}: invalid JSON ({exc})")
            continue
        if not isinstance(m_data, dict):
            violations.append(f"docs/arena/{rel_m}: manifest root must be a JSON object")
            continue
        if "files" in m_data:
            files_list = m_data["files"]
            if not isinstance(files_list, list) or not files_list:
                violations.append(f"docs/arena/{rel_m}: manifest 'files' must be a non-empty list")
                continue
            for entry in files_list:
                if not isinstance(entry, str) or not entry.strip():
                    violations.append(f"docs/arena/{rel_m}: invalid file entry {entry!r}")
                    continue
                p_entry = Path(entry)
                if p_entry.is_absolute() or ".." in p_entry.parts:
                    violations.append(f"docs/arena/{rel_m}: unsafe path in manifest: {entry!r}")
                    continue
                if (
                    p_entry.name in FORBIDDEN_BUNDLE_FILENAMES
                    or any(entry.startswith(pref) for pref in FORBIDDEN_BUNDLE_REL_PREFIXES)
                    or any(tok in entry for tok in FORBIDDEN_MANIFEST_SUBSTRINGS)
                ):
                    violations.append(f"docs/arena/{rel_m}: forbidden file listed in manifest: {entry!r}")
                    continue
                if not (manifest_path.parent / p_entry).is_file() and not (arena_dir / p_entry).is_file():
                    violations.append(f"docs/arena/{rel_m}: missing file referenced in manifest: {entry}")
            if (manifest_path.parent / "canary" / "env.py").is_file():
                cases, solver_refs, _ = _build_reference_cases()
                hard_cases = [c for c in cases if c["tier"] == "hard"]
                hard_solvers = [s for s in solver_refs if s["tier"] == "hard"]
                with temporary_opencode_dir("docs_arena_iso_") as tmp_dir:
                    iso_errs, _ = run_isolated_bundle_check(
                        py_dir=manifest_path.parent,
                        cases=cases[:1] + hard_cases[:1],
                        solver_refs=solver_refs[:1] + hard_solvers[:1],
                        repo_root=root,
                        work_tmp_dir=tmp_dir,
                        require_canary_game=(manifest_path.parent / "canary_game.py").is_file(),
                    )
                    violations.extend(f"docs/arena/{rel_m}: {e}" for e in iso_errs)

    for jsonl_path in sorted(arena_dir.rglob("*.jsonl")):
        rel_j = jsonl_path.relative_to(arena_dir).as_posix()
        for line_no, raw_line in enumerate(jsonl_path.read_text(encoding="utf-8").splitlines(), start=1):
            if not raw_line.strip():
                continue
            try:
                row = json.loads(raw_line)
            except ValueError as exc:
                violations.append(f"docs/arena/{rel_j}:{line_no}: invalid JSON ({exc})")
                continue
            if isinstance(row, dict) and "seed" in row and ("steps" in row or "actions" in row):
                episodes_replayed += 1
                violations.extend(_replay_recorded_item_with_eval(row, f"docs/arena/{rel_j}:{line_no}", root=root))

    for json_path in sorted(arena_dir.rglob("*.json")):
        if json_path.name == "manifest.json":
            continue
        rel_j = json_path.relative_to(arena_dir).as_posix()
        try:
            data = json.loads(json_path.read_text(encoding="utf-8"))
        except ValueError as exc:
            violations.append(f"docs/arena/{rel_j}: invalid JSON ({exc})")
            continue

        if json_path.name == "reference.json" and isinstance(data, dict):
            for seed_key, ref_rows in data.items():
                if not str(seed_key).isdigit() or not isinstance(ref_rows, list):
                    continue
                seed_num = int(seed_key)
                if _is_judge_seed_int(seed_num):
                    continue
                for idx, ref_entry in enumerate(ref_rows):
                    if isinstance(ref_entry, dict) and ref_entry.get("agent") == "solver" and "score" in ref_entry:
                        tier_name = str(ref_entry.get("tier", "medium"))
                        sol_ep = run_episode(Env(tier_name, seed_num), SolverPolicy())
                        episodes_replayed += 1
                        if abs(sol_ep.score - float(ref_entry["score"])) > PARITY_TOL:
                            violations.append(
                                f"docs/arena/{rel_j}[{seed_key}][{idx}]: solver score={ref_entry['score']} "
                                f"vs canary.eval={sol_ep.score}"
                            )
            continue

        candidates = _collect_replay_candidates_from_json(data, f"docs/arena/{rel_j}")
        for loc, item in candidates:
            episodes_replayed += 1
            violations.extend(_replay_recorded_item_with_eval(item, loc, root=root))

    return violations, manifests_checked, episodes_replayed


def verify_docs_arena_autodiscovery(root: Path = ROOT) -> GateResult:
    arena_dir = root / "docs" / "arena"
    if not arena_dir.exists():
        return GateResult(
            gate="docs_arena_autodiscovery",
            passed=True,
            summary="docs/arena/ not present yet; auto-discovery check passed cleanly",
            violations=[],
            data={"present": False, "files_scanned": 0, "manifests_checked": 0, "episodes_replayed": 0},
        )

    if not arena_dir.is_dir():
        return GateResult(
            gate="docs_arena_autodiscovery",
            passed=False,
            summary="docs/arena exists but is not a directory",
            violations=["docs/arena is not a directory"],
            data={"present": True},
        )

    all_files = [p for p in sorted(arena_dir.rglob("*")) if p.is_file()]
    violations = scan_static_tree_for_leaks(
        arena_dir,
        check_mole_truth=True,
        allow_arena_data_dir=True,
        allow_post_done_dev_reveal=True,
        root=root,
    )
    parity_violations, manifests_checked, episodes_replayed = _audit_arena_json_parity(arena_dir, root=root)
    violations.extend(parity_violations)

    summary = (
        f"docs/arena/ audited ({len(all_files)} static files, {manifests_checked} manifest(s), "
        f"{episodes_replayed} replay trace(s)): {len(violations)} violations"
    )
    return GateResult(
        gate="docs_arena_autodiscovery",
        passed=len(violations) == 0,
        summary=summary,
        violations=violations,
        data={
            "present": True,
            "files_scanned": len(all_files),
            "manifests_checked": manifests_checked,
            "episodes_replayed": episodes_replayed,
        },
    )


def run_all_gates(root: Path = ROOT) -> list[GateResult]:
    g1, real_eps = verify_pyodide_bundle_isolation_parity(root=root)
    g2 = verify_leaderboard_and_summary_parity(real_episodes=real_eps)
    g3 = verify_docs_arena_autodiscovery(root=root)
    return [g1, g2, g3]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify Canary Arena Pyodide bundle and leaderboard parity vs canary.eval")
    parser.add_argument("--check", action="store_true", help="Run strict verification gates and exit non-zero on failure")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON report to stdout")
    parser.add_argument("--root", type=Path, default=ROOT, help="Repository root directory")
    args = parser.parse_args(argv)

    t0 = time.perf_counter()
    gates = run_all_gates(root=args.root.resolve())
    elapsed_s = round(time.perf_counter() - t0, 3)
    overall_ok = all(g.passed for g in gates)

    if args.json:
        payload = {
            "passed": overall_ok,
            "check_mode": bool(args.check),
            "elapsed_s": elapsed_s,
            "gates": [_clean_json_value(asdict(g)) for g in gates],
        }
        print(json.dumps(payload, indent=2, ensure_ascii=True))
    else:
        for g in gates:
            status = "PASS" if g.passed else "FAIL"
            print(f"[{status}] {g.gate}: {_norm_ascii(g.summary)}")
            for v in g.violations:
                print(f"  VIOLATION: {_norm_ascii(v)}")
        verdict = "PASS" if overall_ok else "FAIL"
        print(f"OVERALL: {verdict} ({elapsed_s:.2f}s)")

    return 0 if overall_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
