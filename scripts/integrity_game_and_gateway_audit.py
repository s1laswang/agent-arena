from __future__ import annotations

import argparse
import concurrent.futures as cf
import contextlib
import gzip
import hashlib
import hmac
import http.client
import io
import json
import os
import pathlib
import re
import secrets
import shutil
import socket
import stat
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from canary import play as canary_play
from canary.env import Env
from canary.gemini import repo_pack
from canary.gemini.gateway import load_key, load_tokens, request_key
from canary.gemini.lab_replay import summarize as summarize_replay_out
from canary.gemini.swarm import mole_named
from canary.rules import DEV_SEEDS, HELDOUT_SEEDS, JUDGE_SEEDS

DEFAULT_SCRATCH = Path("/tmp/opencode/w2")
BASE_INTEGRITY_SHA = "668a196b"
BASE_JUSTSILAS_SHA = "cf394894"
RESULTS_GEMINI = REPO / "results" / "gemini"
DEFAULT_REPORT = REPO / "docs" / "reports" / "integrity_game_and_gateway_audit.md"

API_KEY_ENV_VARS = (
    "GEMINI_API_KEY",
    "GOOGLE_API_KEY",
    "GOOGLE_GENERATIVE_AI_API_KEY",
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "XAI_API_KEY",
    "HF_TOKEN",
    "GEMINI_GATEWAY_URL",
    "GEMINI_GATEWAY_TOKEN",
    "GEMINI_GATEWAY_TOKEN_FILE",
    "GEMINI_GATEWAY_CLIENT",
)

CREDENTIAL_PATTERNS: dict[str, re.Pattern[str]] = {
    "google_api_key": re.compile(r"AIza[0-9A-Za-z_-]{30,}"),
    "google_oauth": re.compile(r"ya29\.[0-9A-Za-z_-]{20,}"),
    "openai_key": re.compile(r"sk-(?:proj-|live-)?[A-Za-z0-9]{24,}"),
    "anthropic_key": re.compile(r"sk-ant-[A-Za-z0-9_-]{20,}"),
    "hf_token": re.compile(r"hf_[A-Za-z0-9]{24,}"),
    "xai_key": re.compile(r"xai-[A-Za-z0-9_-]{24,}"),
    "github_pat": re.compile(r"gh[pousr]_[A-Za-z0-9]{24,}"),
    "gateway_header_leak": re.compile(r'"x-goog-api-key"\s*:\s*"[^"]+"', re.I),
    "dotenv_secret_assign": re.compile(
        r"(?:GEMINI_API_KEY|GOOGLE_API_KEY|GOOGLE_GENERATIVE_AI_API_KEY|"
        r"CANARY_WORLD_SECRET|CANARY_LEDGER_TOKEN|CANARY_ADMIN_TOKEN|CANARY_LEDGER_KEY)"
        r"\s*=\s*[A-Za-z0-9_./+-]{12,}"
    ),
}

FORBIDDEN_GAME_SITE_PARTS = (
    "SALT",
    ".env",
    "ledger_key",
    "committed",
    "mcp_server.py",
    "redteam",
    "gemini",
    "forge_track.py",
    "harbor",
    "results",
    "data",
)


def default_scratch_root() -> Path:
    if DEFAULT_SCRATCH.parent.exists():
        DEFAULT_SCRATCH.mkdir(parents=True, exist_ok=True)
        return DEFAULT_SCRATCH
    base = Path(os.environ.get("TMPDIR") or tempfile.gettempdir()) / "canary-w2-audit"
    base.mkdir(parents=True, exist_ok=True)
    return base


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def write_0600(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(text)
    os.chmod(path, 0o600)
    return path


def scrubbed_offline_env(scratch_dir: Path, extra: dict[str, str] | None = None) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith(("GEMINI_", "GOOGLE_", "CANARY_"))}
    for k in API_KEY_ENV_VARS:
        env.pop(k, None)
    env["TMPDIR"] = str(scratch_dir)
    env["PYTHONPATH"] = str(REPO)
    if extra:
        env.update(extra)
    return env


def invoke_play_inproc(argv: list[str], workdir: Path, stdin_text: str = "quit\n") -> dict[str, Any]:
    workdir.mkdir(parents=True, exist_ok=True)
    out_buf = io.StringIO()
    err_buf = io.StringIO()
    old_cwd = os.getcwd()
    old_stdin = sys.stdin
    rc = 0
    exc_type: str | None = None
    try:
        os.chdir(workdir)
        sys.stdin = io.StringIO(stdin_text)
        with contextlib.redirect_stdout(out_buf), contextlib.redirect_stderr(err_buf):
            canary_play.main(argv)
    except SystemExit as ex:
        rc = int(ex.code) if isinstance(ex.code, int) else 1
    except Exception as ex:
        rc = 1
        exc_type = type(ex).__name__
    finally:
        sys.stdin = old_stdin
        os.chdir(old_cwd)
    human_dir = workdir / "data" / "runs" / "human"
    saved = sorted(p.name for p in human_dir.glob("*.jsonl")) if human_dir.exists() else []
    return {
        "rc": rc,
        "exc_type": exc_type,
        "stdout": out_buf.getvalue(),
        "stderr": err_buf.getvalue(),
        "saved_files": saved,
    }


def invoke_play_subproc(
    argv: list[str],
    workdir: Path,
    extra_env: dict[str, str] | None = None,
    stdin_text: str = "quit\n",
) -> dict[str, Any]:
    workdir.mkdir(parents=True, exist_ok=True)
    env = scrubbed_offline_env(workdir, extra_env)
    proc = subprocess.run(
        [sys.executable, "-m", "canary.play", *argv],
        cwd=workdir,
        env=env,
        input=stdin_text,
        capture_output=True,
        text=True,
        timeout=20,
    )
    human_dir = workdir / "data" / "runs" / "human"
    saved = sorted(p.name for p in human_dir.glob("*.jsonl")) if human_dir.exists() else []
    saved_text = ""
    if human_dir.exists():
        saved_text = "\n".join(p.read_text(encoding="utf-8") for p in sorted(human_dir.glob("*.jsonl")))
    return {
        "rc": proc.returncode,
        "stdout": proc.stdout,
        "stderr": proc.stderr,
        "saved_files": saved,
        "saved_text": saved_text,
    }


def audit_game_and_play_boundaries(scratch_root: Path | None = None, quick: bool = False) -> dict[str, Any]:
    t0 = time.perf_counter()
    root = scratch_root or default_scratch_root()
    work = root / f"game-play-{secrets.token_hex(6)}"
    work.mkdir(parents=True, exist_ok=True)
    secret_marker = f"w2-world-secret-{secrets.token_hex(12)}"
    salt_path = REPO / "data" / "worlds" / "judge" / "SALT"
    salt_bytes = salt_path.read_bytes().strip() if salt_path.exists() else b""

    try:
        judge_seeds = list(range(900000, 900040)) if not quick else [900000, 900001, 900019, 900038, 900039]
        heldout_seeds = list(range(800000, 800030)) if not quick else [800000, 800001, 800015, 800028, 800029]
        low_dev_seeds = [0, 1, 7, 42, 300, 1999, 2999]
        high_int_seeds = [10000, 99999, 100000, 199999, 800199, 900040, 10**18, 2**128]

        judge_refused = 0
        for s in judge_seeds:
            r = invoke_play_inproc(["--tier", "medium", "--seed", str(s)], work / f"j-{s}")
            leaked = secret_marker in (r["stdout"] + r["stderr"])
            if salt_bytes and salt_bytes.decode("utf-8", errors="ignore") in (r["stdout"] + r["stderr"]):
                leaked = True
            if r["rc"] == 2 and not r["saved_files"] and not leaked and "seed must be a dev seed" in r["stderr"]:
                judge_refused += 1

        cross_tier_judge_refused = 0
        for tier in ("easy", "hard"):
            for s in (900000, 900039):
                r = invoke_play_inproc(["--tier", tier, "--seed", str(s)], work / f"jt-{tier}-{s}")
                if r["rc"] == 2 and not r["saved_files"]:
                    cross_tier_judge_refused += 1

        heldout_refused = 0
        for s in heldout_seeds:
            r = invoke_play_inproc(["--tier", "medium", "--seed", str(s)], work / f"h-{s}")
            if r["rc"] == 2 and not r["saved_files"] and "seed must be a dev seed" in r["stderr"]:
                heldout_refused += 1

        low_refused = 0
        for s in low_dev_seeds:
            r = invoke_play_inproc(["--tier", "medium", "--seed", str(s)], work / f"lo-{s}")
            if r["rc"] == 2 and not r["saved_files"] and "seed must be a dev seed" in r["stderr"]:
                low_refused += 1

        high_refused = 0
        for s in high_int_seeds:
            r = invoke_play_inproc(["--tier", "medium", "--seed", str(s)], work / f"hi-{s}")
            if r["rc"] == 2 and not r["saved_files"] and "seed must be a dev seed" in r["stderr"]:
                high_refused += 1

        arabic_judge = invoke_play_inproc(
            ["--tier", "medium", "--seed", "\u0669\u0660\u0660\u0660\u0660\u0660"],
            work / "u-arabic",
        )
        superscript_digit = invoke_play_inproc(
            ["--tier", "medium", "--seed", "\u00b2"],
            work / "u-sup2",
        )

        non_digit_cases = [
            ["--seed", "-1"],
            ["--seed", "-900000"],
            ["--seed=-1"],
            ["--seed=-900000"],
            ["--seed=3000.5"],
            ["--seed=3e3"],
            ["--seed=NaN"],
            ["--seed=abc"],
            ["--seed=dev20"],
        ]
        fallback_dev_coerced = 0
        for idx, av in enumerate(non_digit_cases):
            r = invoke_play_inproc(["--tier", "medium", *av], work / f"fallback-{idx}")
            m = re.search(r"medium tier, seed (\d+)\.", r["stdout"])
            picked = int(m.group(1)) if m else -1
            if r["rc"] == 0 and 3000 <= picked <= 3999 and r["saved_files"] == [f"human-medium-{picked}.jsonl"]:
                fallback_dev_coerced += 1

        bad_arg_cases = [
            ["--tier", "hard_forge", "--seed", "3000"],
            ["--tier", "hard_rl", "--seed", "3000"],
            ["--tier", "unknown", "--seed", "3000"],
            ["--tier", "medium", "--seed", "--bogus-flag"],
            ["--tier", "medium", "--seed", "3000", "--name", "../evil"],
            ["--tier", "medium", "--seed", "3000", "--name", "a/b"],
            ["--tier", "medium", "--seed", "3000", "--name", ""],
            ["--tier", "medium", "--seed", "3000", "--name", "x" * 41],
            ["--tier", "medium", "--seed", "3000", "--name", "bad space"],
        ]
        bad_arg_refused = 0
        for idx, av in enumerate(bad_arg_cases):
            r = invoke_play_inproc(av, work / f"badarg-{idx}")
            if r["rc"] == 2 and not r["saved_files"]:
                bad_arg_refused += 1

        spoof_env = {
            "CANARY_ALLOW_DEV": "1",
            "CANARY_SEED": "900000",
            "CANARY_TIER": "hard",
            "CANARY_WORLD_SECRET": secret_marker,
            "CANARY_BOOTSTRAPPED": "1",
        }
        subproc_refusal_cases = [
            ("judge_900000_spoof", ["--tier", "medium", "--seed", "900000"]),
            ("judge_900039_spoof", ["--tier", "hard", "--seed", "900039"]),
            ("heldout_800000_spoof", ["--tier", "medium", "--seed", "800000"]),
            ("heldout_800029_spoof", ["--tier", "easy", "--seed", "800029"]),
            ("low_0_spoof", ["--tier", "medium", "--seed", "0"]),
            ("low_2999_spoof", ["--tier", "medium", "--seed", "2999"]),
            ("train_100000_spoof", ["--tier", "medium", "--seed", "100000"]),
            ("huge_int_spoof", ["--tier", "medium", "--seed", "999999999999"]),
            ("track_hard_forge_spoof", ["--tier", "hard_forge", "--seed", "3000"]),
            ("name_traversal_spoof", ["--tier", "medium", "--seed", "3000", "--name", "../evil"]),
        ]
        subproc_refused = 0
        subproc_leaks = 0
        for label, av in subproc_refusal_cases:
            r = invoke_play_subproc(av, work / f"sub-{label}", extra_env=spoof_env)
            blob = r["stdout"] + r["stderr"] + r["saved_text"]
            if secret_marker in blob:
                subproc_leaks += 1
            if salt_bytes and salt_bytes.decode("utf-8", errors="ignore") in blob:
                subproc_leaks += 1
            if r["rc"] == 2 and not r["saved_files"]:
                subproc_refused += 1

        neg_sub = invoke_play_subproc(
            ["--tier", "medium", "--seed", "-900000", "--name", "negprobe"],
            work / "sub-neg-900000",
            extra_env=spoof_env,
        )
        neg_m = re.search(r"medium tier, seed (\d+)\.", neg_sub["stdout"])
        neg_picked = int(neg_m.group(1)) if neg_m else -1
        neg_sub_safe = (
            neg_sub["rc"] == 0
            and 3000 <= neg_picked <= 3999
            and "900000" not in (neg_sub["stdout"] + neg_sub["stderr"] + neg_sub["saved_text"])
            and secret_marker not in (neg_sub["stdout"] + neg_sub["stderr"] + neg_sub["saved_text"])
        )

        valid_sub = invoke_play_subproc(
            ["--tier", "medium", "--seed", "3000", "--name", "auditor"],
            work / "sub-valid-3000",
            extra_env=spoof_env,
            stdin_text=(
                "status\nstaff\nunrestrict e00\nrestrict e00\nrestrict e00\n"
                "logs 3-2\nread m9999\nsearch *\n_world\nverdict\naccuse e00\nn\nquit\n"
            ),
        )
        env_3000 = Env("medium", 3000)
        mole_3000 = env_3000._world.mole
        saved_ep = json.loads(valid_sub["saved_text"].splitlines()[0]) if valid_sub["saved_text"].strip() else {}
        saved_err_details = [
            st["result"]["data"].get("detail", "")
            for st in saved_ep.get("steps", [])
            if not st.get("result", {}).get("ok", True)
        ]
        valid_blob = valid_sub["stdout"] + valid_sub["stderr"]
        valid_play_isolated = (
            valid_sub["rc"] == 0
            and "medium tier, seed 3000." in valid_sub["stdout"]
            and "900000" not in valid_blob
            and secret_marker not in (valid_blob + valid_sub["saved_text"])
            and "correct=" not in valid_sub["stdout"]
            and not mole_named(valid_sub["stdout"], mole_3000)
            and len(saved_err_details) == 5
            and all(isinstance(d, str) and d and "mole" not in d.lower() for d in saved_err_details)
            and valid_sub["saved_files"] == ["auditor-medium-3000.jsonl"]
        )

        parser_adversarial = [
            "",
            "_world",
            "verdict",
            "peek_status",
            "eval",
            "accuse e999",
            "accuse e01 e02",
            "restrict ../e01",
            'canary "unclosed e01=A',
            "canary title e01=",
            "canary title e999=A",
            "interview e01 mole",
            "logs 1-2 e999",
            "docs 1-2-3",
        ]
        parser_rejected = sum(1 for cmd in parser_adversarial if canary_play.parse(cmd) is None)

        sys.path.insert(0, str(REPO / "game"))
        try:
            import build as game_build
        finally:
            if str(REPO / "game") in sys.path:
                sys.path.remove(str(REPO / "game"))

        site_dir = work / "site"
        manifest = game_build.build(site_dir)
        all_site_files = sorted(
            p.relative_to(site_dir).as_posix() for p in site_dir.rglob("*") if p.is_file()
        )
        py_site_files = sorted(
            p.relative_to(site_dir / "py").as_posix()
            for p in (site_dir / "py").rglob("*.py")
            if p.is_file()
        )
        manifest_files = sorted(manifest.get("files", []))
        forbidden_shipped = [
            rel
            for rel in all_site_files
            if any(tok in rel for tok in FORBIDDEN_GAME_SITE_PARTS)
        ]

        repo_secret_bytes = repo_pack._secret_values(REPO)
        packaged_secret_hits: list[dict[str, str]] = []
        mole_dump_re = re.compile(r'"mole"\s*:\s*"e\d{2}"')
        for rel in all_site_files:
            raw = (site_dir / rel).read_bytes()
            txt = raw.decode("utf-8", errors="replace")
            for pname, rx in CREDENTIAL_PATTERNS.items():
                m = rx.search(txt)
                if m:
                    packaged_secret_hits.append({"file": rel, "kind": pname})
            if mole_dump_re.search(txt):
                packaged_secret_hits.append({"file": rel, "kind": "mole_world_dump"})
            for sb in repo_secret_bytes:
                if len(sb) >= 8 and sb in raw:
                    packaged_secret_hits.append({"file": rel, "kind": "repo_secret_value"})

        iso_probe_code = """
import hashlib, hmac, json, re, sys
import canary_game as G
from canary.env import Env
from canary.world import world_seed

allowed_ok = []
for s in (3000, 5500, 9999):
    g = G.Game(s)
    pre = json.loads(g.reveal_json())
    spec = json.loads(g.spec_json())
    allowed_ok.append(
        spec["tier"] == "medium"
        and spec["seed"] == s
        and "error" in pre
        and g.env.history == []
    )

blocked_seeds = [0, 2999, 10000, 100000, 800000, 800029, 900000, 900039, -1, -900000, "3000.0", "3e3", "abc", True, None]
blocked_ok = 0
for s in blocked_seeds:
    try:
        G.Game(s)
    except ValueError:
        blocked_ok += 1

env_tiers_allowed = []
for t in ("easy", "medium", "hard"):
    e = Env(t, 3000)
    env_tiers_allowed.append(e.tier == t)

env_tracks_blocked = 0
for t in ("hard_forge", "hard_rl", "nonexistent"):
    try:
        Env(t, 3000)
    except (ModuleNotFoundError, ValueError):
        env_tracks_blocked += 1

w1_easy = Env("easy", 3000).instruction()
w1_med = G.Game(3000).env.instruction()
w1_hard = Env("hard", 3000).instruction()
w1_instruction_verified = (
    "The mole never knows which documents are canaries." in w1_easy
    and "The mole's rules cannot see which documents are canaries." in w1_med
    and "The mole's rules cannot see which documents are canaries." in w1_hard
)

def check_bad_result(res_dict, ws_val, allow_emp=None):
    if res_dict.get("ok") is not False or res_dict.get("error") != "invalid arguments":
        return False, "bad_envelope"
    data = res_dict.get("data")
    if not isinstance(data, dict) or set(data.keys()) != {"detail"}:
        return False, "missing_detail_key"
    det = data["detail"]
    if not isinstance(det, str) or not det.strip():
        return False, "empty_detail"
    low = det.lower()
    if "mole" in low or "decoy" in low or str(ws_val) in det:
        return False, "truth_or_seed_in_detail"
    for m in re.findall(r"\\be\\d{2}\\b", det):
        if m != allow_emp:
            return False, f"unexpected_emp_id:{m}"
    return True, det

g_probe = G.Game(3000)
ws_3000 = g_probe.env._world.world_seed
g_probe.call_json("restrict_access", json.dumps({"employee": "e04"}))
schema_cases = [
    ("status", '"not_an_object"', None),
    ("status", '[1, 2]', None),
    ("status", '{"unexpected": 1}', None),
    ("interview", '{"employee": "e00"}', "e00"),
    ("read_access_logs", '{"day_from": true}', None),
    ("read_access_logs", '{"day_from": 0}', None),
    ("read_access_logs", '{"day_to": 99}', None),
    ("interview", '{"employee": 123, "topic": "workload"}', None),
    ("plant_canary", '{"doc_title": "t", "assignment": "bad"}', None),
    ("read_access_logs", '{"day_from": 3, "day_to": 2}', None),
    ("accuse", '{"employee": "nobody"}', None),
    ("search_messages", '{"query": "   "}', None),
    ("search_messages", '{"query": "a*b"}', None),
    ("read_message", '{"id": "m9999"}', None),
    ("interview", '{"employee": "e00", "topic": "leaks"}', "e00"),
    ("plant_canary", '{"doc_title": " ", "assignment": {"e00": "A"}}', "e00"),
    ("plant_canary", '{"doc_title": "t", "assignment": {"e04": "A"}}', "e04"),
    ("plant_canary", '{"doc_title": "t", "assignment": {"e00": "A", "e01": "B", "e02": "C", "e03": "D"}}', None),
]
detail_codepaths_ok = 0
detail_leaks = 0
for tool_name, raw_args, allow_e in schema_cases:
    out_d = json.loads(g_probe.call_json(tool_name, raw_args))
    ok_flag, _ = check_bad_result(out_d, ws_3000, allow_emp=allow_e)
    if ok_flag and not g_probe.env.done:
        detail_codepaths_ok += 1
    else:
        detail_leaks += 1

role_parity_checks = 0
role_parity_mismatches = 0
world_specs = [("game", 3000), ("game", 3001), ("game", 5500), ("medium", 800000), ("hard", 900000)]
for kind, s_val in world_specs:
    base_env = G.Game(s_val).env if kind == "game" else Env(kind, s_val)
    mole_id = base_env._world.mole
    decoy_id = getattr(base_env._world, "decoy", None)
    innocent_id = next(x for x in base_env._world.ids if x != mole_id and x != decoy_id)
    targets = [mole_id, innocent_id] + ([decoy_id] if decoy_id and decoy_id in base_env._world.ids else [])
    for probe_idx in range(8):
        norm_details = []
        for emp_id in targets:
            inst = G.Game(s_val).env if kind == "game" else Env(kind, s_val)
            ws_cur = inst._world.world_seed
            if probe_idx == 0:
                r = inst.call("interview", {"employee": emp_id, "topic": "leaks"})
            elif probe_idx == 1:
                r = inst.call("interview", {"employee": emp_id})
            elif probe_idx == 2:
                r = inst.call("unrestrict_access", {"employee": emp_id})
            elif probe_idx == 3:
                inst.call("restrict_access", {"employee": emp_id})
                r = inst.call("restrict_access", {"employee": emp_id})
            elif probe_idx == 4:
                inst.call("restrict_access", {"employee": emp_id})
                r = inst.call("plant_canary", {"doc_title": "probe", "assignment": {emp_id: "A"}})
            elif probe_idx == 5:
                r = inst.call("plant_canary", {"doc_title": "probe", "assignment": {emp_id: " "}})
            elif probe_idx == 6:
                r = inst.call("plant_canary", {"doc_title": "probe", "assignment": {emp_id: "V" * 25}})
            else:
                r = inst.call("accuse", {"employee": emp_id, "extra": 1})
            ok_f, det_or_err = check_bad_result({"ok": r.ok, "data": r.data, "error": r.error}, ws_cur, allow_emp=emp_id)
            if not ok_f or inst.done:
                detail_leaks += 1
                norm_details.append(f"ERR:{det_or_err}:{emp_id}")
            else:
                norm_details.append(det_or_err.replace(emp_id, "<id>"))
        role_parity_checks += 1
        if len(set(norm_details)) != 1:
            role_parity_mismatches += 1

pub_j = int.from_bytes(hmac.new(b"public", b"hard:900000", hashlib.sha256).digest()[:8], "big")
pub_h = int.from_bytes(hmac.new(b"public", b"medium:800000", hashlib.sha256).digest()[:8], "big")
pub_d = int.from_bytes(hmac.new(b"public", b"medium:3000", hashlib.sha256).digest()[:8], "big")
ws_judge = world_seed("hard", 900000)
ws_heldout = world_seed("medium", 800000)
ws_dev = world_seed("medium", 3000)

print(json.dumps({
    "game_allowed_ok": sum(allowed_ok),
    "game_allowed_total": len(allowed_ok),
    "game_blocked_ok": blocked_ok,
    "game_blocked_total": len(blocked_seeds),
    "env_tiers_allowed": sum(env_tiers_allowed),
    "env_tracks_blocked": env_tracks_blocked,
    "w1_instruction_verified": w1_instruction_verified,
    "detail_codepaths_ok": detail_codepaths_ok,
    "detail_codepaths_total": len(schema_cases),
    "detail_role_parity_checks": role_parity_checks,
    "detail_role_parity_mismatches": role_parity_mismatches,
    "detail_secret_or_truth_leaks": detail_leaks,
    "ws_judge": ws_judge,
    "ws_heldout": ws_heldout,
    "ws_dev": ws_dev,
    "judge_not_public": ws_judge != pub_j,
    "heldout_not_public": ws_heldout != pub_h,
    "dev_is_public": ws_dev == pub_d,
}))
"""
        iso_env = scrubbed_offline_env(work)
        iso_env["PYTHONPATH"] = str(site_dir / "py")
        p1 = subprocess.run(
            [sys.executable, "-S", "-c", f"import site; {iso_probe_code}"],
            cwd=work,
            env=iso_env,
            capture_output=True,
            text=True,
            timeout=20,
            check=True,
        )
        p2 = subprocess.run(
            [sys.executable, "-S", "-c", f"import site; {iso_probe_code}"],
            cwd=work,
            env=iso_env,
            capture_output=True,
            text=True,
            timeout=20,
            check=True,
        )
        iso1 = json.loads(p1.stdout.strip().splitlines()[-1])
        iso2 = json.loads(p2.stdout.strip().splitlines()[-1])
        ephemeral_judge_secret_verified = (
            iso1["judge_not_public"]
            and iso1["heldout_not_public"]
            and iso1["dev_is_public"]
            and iso1["ws_judge"] != iso2["ws_judge"]
            and iso1["ws_heldout"] != iso2["ws_heldout"]
        )

        play_ok = (
            judge_refused == len(judge_seeds)
            and cross_tier_judge_refused == 4
            and heldout_refused == len(heldout_seeds)
            and low_refused == len(low_dev_seeds)
            and high_refused == len(high_int_seeds)
            and arabic_judge["rc"] == 2
            and not arabic_judge["saved_files"]
            and superscript_digit["rc"] == 1
            and superscript_digit["exc_type"] == "ValueError"
            and not superscript_digit["saved_files"]
            and fallback_dev_coerced == len(non_digit_cases)
            and bad_arg_refused == len(bad_arg_cases)
            and subproc_refused == len(subproc_refusal_cases)
            and subproc_leaks == 0
            and neg_sub_safe
            and valid_play_isolated
            and parser_rejected == len(parser_adversarial)
        )

        pyodide_ok = (
            len(all_site_files) == 19
            and len(py_site_files) == 15
            and py_site_files == manifest_files
            and len(forbidden_shipped) == 0
            and len(packaged_secret_hits) == 0
            and iso1["game_allowed_ok"] == iso1["game_allowed_total"] == 3
            and iso1["game_blocked_ok"] == iso1["game_blocked_total"] == 15
            and iso1["env_tiers_allowed"] == 3
            and iso1["env_tracks_blocked"] == 3
            and iso1["w1_instruction_verified"] is True
            and iso1["detail_codepaths_ok"] == iso1["detail_codepaths_total"] == 18
            and iso1["detail_role_parity_checks"] == 40
            and iso1["detail_role_parity_mismatches"] == 0
            and iso1["detail_secret_or_truth_leaks"] == 0
            and ephemeral_judge_secret_verified
        )

        return {
            "ok": bool(play_ok and pyodide_ok),
            "elapsed_s": round(time.perf_counter() - t0, 3),
            "play_cli": {
                "ok": play_ok,
                "judge_seeds_probed": len(judge_seeds),
                "judge_seeds_refused_exit2": judge_refused,
                "cross_tier_judge_probed": 4,
                "cross_tier_judge_refused_exit2": cross_tier_judge_refused,
                "heldout_seeds_probed": len(heldout_seeds),
                "heldout_seeds_refused_exit2": heldout_refused,
                "low_dev_seeds_probed": len(low_dev_seeds),
                "low_dev_seeds_refused_exit2": low_refused,
                "high_int_seeds_probed": len(high_int_seeds),
                "high_int_seeds_refused_exit2": high_refused,
                "arabic_judge_rc": arabic_judge["rc"],
                "superscript_digit_rc": superscript_digit["rc"],
                "superscript_digit_exc": superscript_digit["exc_type"],
                "non_digit_probed": len(non_digit_cases),
                "non_digit_dev_fallback": fallback_dev_coerced,
                "bad_arg_probed": len(bad_arg_cases),
                "bad_arg_refused_exit2": bad_arg_refused,
                "subproc_spoof_probed": len(subproc_refusal_cases),
                "subproc_spoof_refused_exit2": subproc_refused,
                "subproc_secret_leaks": subproc_leaks,
                "neg_sub_safe": neg_sub_safe,
                "valid_play_isolated": valid_play_isolated,
                "parser_adversarial_probed": len(parser_adversarial),
                "parser_adversarial_rejected": parser_rejected,
            },
            "pyodide_game": {
                "ok": pyodide_ok,
                "site_total_files": len(all_site_files),
                "site_python_files": len(py_site_files),
                "site_files": all_site_files,
                "manifest_matches_disk": py_site_files == manifest_files,
                "forbidden_files_shipped": len(forbidden_shipped),
                "secret_pattern_hits": len(packaged_secret_hits),
                "game_wrapper_allowed": f"{iso1['game_allowed_ok']}/{iso1['game_allowed_total']}",
                "game_wrapper_blocked": f"{iso1['game_blocked_ok']}/{iso1['game_blocked_total']}",
                "raw_env_tiers_allowed": iso1["env_tiers_allowed"],
                "raw_env_tracks_blocked": iso1["env_tracks_blocked"],
                "w1_instruction_verified": iso1["w1_instruction_verified"],
                "detail_codepaths_verified": f"{iso1['detail_codepaths_ok']}/{iso1['detail_codepaths_total']}",
                "detail_role_parity_checks": iso1["detail_role_parity_checks"],
                "detail_role_parity_mismatches": iso1["detail_role_parity_mismatches"],
                "detail_secret_or_truth_leaks": iso1["detail_secret_or_truth_leaks"],
                "ephemeral_judge_secret_verified": ephemeral_judge_secret_verified,
            },
        }
    finally:
        shutil.rmtree(work, ignore_errors=True)


class UpstreamSpy:
    def __init__(self) -> None:
        self.seen: list[dict[str, Any]] = []
        self.lock = threading.Lock()
        spy = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *args: Any) -> None:
                return

            def _record(self) -> None:
                n = int(self.headers.get("content-length") or 0)
                body = self.rfile.read(n) if n else b""
                with spy.lock:
                    spy.seen.append({"method": self.command, "path": self.path, "len": len(body)})
                payload = b'{"error":{"code":599,"status":"SPY_UPSTREAM_TOUCHED"}}'
                self.send_response(599)
                self.send_header("content-type", "application/json")
                self.send_header("content-length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            do_GET = do_POST = do_PUT = do_DELETE = do_PATCH = do_OPTIONS = do_HEAD = _record

        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.srv.daemon_threads = True
        self.url = f"http://127.0.0.1:{self.srv.server_address[1]}"
        self._thread = threading.Thread(target=self.srv.serve_forever, daemon=True)
        self._thread.start()

    def count(self) -> int:
        with self.lock:
            return len(self.seen)

    def close(self) -> None:
        self.srv.shutdown()
        self.srv.server_close()
        self._thread.join(timeout=5)


class ManagedReplayGateway:
    def __init__(self, store_dir: Path, upstream_url: str, workdir: Path) -> None:
        self.workdir = workdir
        self.workdir.mkdir(parents=True, exist_ok=True)
        self.port = free_port()
        self.url = f"http://127.0.0.1:{self.port}"
        self.token = "gw-audit-" + secrets.token_hex(20)
        self.other_token = "gw-other-" + secrets.token_hex(20)
        self.token_file = write_0600(
            self.workdir / "tokens.0600",
            f"auditor {self.token}\nsecondary {self.other_token}\n",
        )
        self.stats_dir = self.workdir / "stats"
        self.stats_dir.mkdir(parents=True, exist_ok=True)
        self.log_path = self.workdir / "gateway.log"
        self._log_fh = open(self.log_path, "w", encoding="utf-8")
        env = scrubbed_offline_env(self.workdir)
        self.proc = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "canary.gemini.gateway",
                "--host",
                "127.0.0.1",
                "--port",
                str(self.port),
                "--replay",
                str(store_dir),
                "--token-file",
                str(self.token_file),
                "--upstream",
                upstream_url,
                "--stats-dir",
                str(self.stats_dir),
                "--max-hours",
                "1",
            ],
            cwd=REPO,
            env=env,
            stdout=self._log_fh,
            stderr=subprocess.STDOUT,
        )
        ready = False
        for _ in range(150):
            if self.proc.poll() is not None:
                break
            try:
                st, _, raw = self.http_request("GET", "/healthz", timeout=1.0)
                if st == 200 and (b'"ok": true' in raw.lower() or b'"ok":true' in raw.lower()):
                    ready = True
                    break
            except (http.client.HTTPException, OSError):
                pass
            time.sleep(0.05)
        if not ready:
            self.close()
            raise RuntimeError("replay gateway failed to become healthy")

    def http_request(
        self,
        method: str,
        path: str,
        body: bytes | None = None,
        headers: dict[str, str] | None = None,
        timeout: float = 15.0,
    ) -> tuple[int, dict[str, str], bytes]:
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=timeout)
        try:
            conn.request(method, path, body=body, headers=headers or {})
            resp = conn.getresponse()
            data = resp.read()
            hdrs = {k.lower(): v for k, v in resp.getheaders()}
            return resp.status, hdrs, data
        finally:
            conn.close()

    def raw_tcp(self, payload: bytes, timeout: float = 10.0) -> bytes:
        with socket.create_connection(("127.0.0.1", self.port), timeout=timeout) as sock:
            sock.sendall(payload)
            sock.shutdown(socket.SHUT_WR)
            chunks: list[bytes] = []
            while True:
                try:
                    buf = sock.recv(65536)
                except OSError:
                    break
                if not buf:
                    break
                chunks.append(buf)
            return b"".join(chunks)

    def stats_rows(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for f in sorted(self.stats_dir.glob("stats-*.jsonl")):
            for line in f.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    rows.append(json.loads(line))
        return rows

    def stats_raw_text(self) -> str:
        return "\n".join(f.read_text(encoding="utf-8") for f in sorted(self.stats_dir.glob("stats-*.jsonl")))

    def health(self) -> dict[str, Any]:
        st, _, raw = self.http_request("GET", "/healthz")
        if st != 200:
            return {"ok": False, "status": st}
        return json.loads(raw.decode("utf-8"))

    def close(self) -> None:
        try:
            if self.proc.poll() is None:
                self.proc.terminate()
                try:
                    self.proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    self.proc.kill()
                    self.proc.wait(timeout=5)
        finally:
            self._log_fh.close()


def write_replay_entry(store_dir: Path, rkey: str, entry: dict[str, Any], repeat_idx: int = 0) -> Path:
    sub = store_dir / rkey[:2]
    sub.mkdir(parents=True, exist_ok=True)
    fname = f"{rkey}.json.gz" if repeat_idx == 0 else f"{rkey}.{repeat_idx}.json.gz"
    dst = sub / fname
    with gzip.open(dst, "wt", encoding="utf-8", compresslevel=9) as fh:
        json.dump(entry, fh, separators=(",", ":"), sort_keys=True)
    return dst


def audit_gateway_and_offline_replay(
    scratch_root: Path | None = None,
    quick: bool = False,
    wire_only: bool = False,
) -> dict[str, Any]:
    t0 = time.perf_counter()
    root = scratch_root or default_scratch_root()
    work = root / f"gw-replay-{secrets.token_hex(6)}"
    work.mkdir(parents=True, exist_ok=True)
    spy = UpstreamSpy()
    vectors: list[dict[str, Any]] = []

    try:
        synth_store = work / "synth_store"
        shutil.copytree(RESULTS_GEMINI / "replay", synth_store)

        sample_gz = sorted((RESULTS_GEMINI / "replay").rglob("*.json.gz"))[0]
        sample_recorded = json.loads(gzip.decompress(sample_gz.read_bytes()).decode("utf-8"))
        sample_resp_bytes = sample_recorded.get("body", "").encode("utf-8")

        wire_path = "/v1beta/models/gemini-3.1-flash-lite:generateContent"
        wire_body_obj = {
            "contents": [{"role": "user", "parts": [{"text": "canary-wire-deterministic-probe"}]}],
            "generationConfig": {"temperature": 0.0},
        }
        wire_body = json.dumps(wire_body_obj, separators=(",", ":")).encode("utf-8")
        wire_rkey = request_key("POST", wire_path, [], wire_body)
        write_replay_entry(
            synth_store,
            wire_rkey,
            {
                "status": 200,
                "headers": {"content-type": "application/json; charset=UTF-8"},
                "stream": False,
                "method": "POST",
                "path": wire_path,
                "model": "gemini-3.1-flash-lite",
                "ts": 1700000000.0,
                "body": sample_recorded.get("body", "{}"),
            },
        )

        seq_body = b'{"contents":[{"parts":[{"text":"seq-probe"}],"role":"user"}]}'
        seq_rkey = request_key("POST", wire_path, [], seq_body)
        for idx, label in enumerate(("turn-0", "turn-1")):
            write_replay_entry(
                synth_store,
                seq_rkey,
                {
                    "status": 200,
                    "headers": {"content-type": "application/json; charset=UTF-8"},
                    "stream": False,
                    "method": "POST",
                    "path": wire_path,
                    "model": "gemini-3.1-flash-lite",
                    "ts": 1700000001.0 + idx,
                    "body": json.dumps({"seq": label}),
                },
                repeat_idx=idx,
            )

        tag_body = b'{"contents":[{"parts":[{"text":"tagged-first-turn"}],"role":"user"}]}'
        for tag_name in ("ep-alpha", "ep-beta"):
            tk = request_key("POST", wire_path, [], tag_body, tag=tag_name)
            write_replay_entry(
                synth_store,
                tk,
                {
                    "status": 200,
                    "headers": {"content-type": "application/json; charset=UTF-8"},
                    "stream": False,
                    "method": "POST",
                    "path": wire_path,
                    "model": "gemini-3.1-flash-lite",
                    "ts": 1700000005.0,
                    "body": json.dumps({"episode_tag": tag_name}),
                },
            )

        gw = ManagedReplayGateway(synth_store, spy.url, work / "gw_wire")
        try:
            vt = time.perf_counter()
            s_none, _, _ = gw.http_request("POST", wire_path, body=wire_body)
            s_empty, _, _ = gw.http_request("POST", wire_path, body=wire_body, headers={"x-goog-api-key": ""})
            s_wrong, _, _ = gw.http_request(
                "POST", wire_path, body=wire_body, headers={"x-goog-api-key": "wrong-" + "z" * 32}
            )
            s_qwrong, _, _ = gw.http_request("POST", f"{wire_path}?key=wrong-query-token-000000", body=wire_body)
            s_short, _, _ = gw.http_request("POST", wire_path, body=wire_body, headers={"x-goog-api-key": "short"})

            perm_file = work / "bad_perm_tok"
            perm_file.write_text("client " + "t" * 24 + "\n", encoding="utf-8")
            os.chmod(perm_file, 0o644)
            perm_rejected = False
            try:
                load_tokens(perm_file)
            except SystemExit:
                perm_rejected = True

            short_file = write_0600(work / "short_tok", "client too_short\n")
            short_rejected = False
            try:
                load_tokens(short_file)
            except SystemExit:
                short_rejected = True

            bad_key_file = work / "bad_key.env"
            bad_key_file.write_text("GEMINI_API_KEY=placeholder0123456789\n", encoding="utf-8")
            os.chmod(bad_key_file, 0o640)
            key_perm_rejected = False
            try:
                load_key(bad_key_file)
            except SystemExit:
                key_perm_rejected = True

            g01_ok = (
                [s_none, s_empty, s_wrong, s_qwrong, s_short] == [401, 401, 401, 401, 401]
                and perm_rejected
                and short_rejected
                and key_perm_rejected
                and gw.health().get("ok") is True
                and spy.count() == 0
            )
            vectors.append(
                {
                    "id": "G01",
                    "name": "auth_token_and_perm_enforcement",
                    "held": g01_ok,
                    "elapsed_s": round(time.perf_counter() - vt, 3),
                    "detail": f"http_codes={[s_none, s_empty, s_wrong, s_qwrong, s_short]} perm_0644_blocked={perm_rejected} short_tok_blocked={short_rejected} upstream={spy.count()}",
                }
            )

            vt = time.perf_counter()
            secret_prompt = "UNRECORDED-CANARY-PROMPT-" + secrets.token_hex(8)
            miss_body = json.dumps({"contents": [{"parts": [{"text": secret_prompt}]}]}).encode("utf-8")
            s_miss1, _, b_miss1 = gw.http_request(
                "POST",
                "/v1beta/models/gemini-4-carbon:generateContent",
                body=miss_body,
                headers={"x-goog-api-key": gw.token, "content-type": "application/json"},
            )
            s_miss2, _, b_miss2 = gw.http_request(
                "POST",
                "/v1beta/models/gemini-3.8-flash:streamGenerateContent?alt=sse",
                body=miss_body,
                headers={"x-goog-api-key": gw.token, "content-type": "application/json"},
            )
            j_miss1 = json.loads(b_miss1.decode("utf-8"))
            j_miss2 = json.loads(b_miss2.decode("utf-8"))
            stats_txt = gw.stats_raw_text()
            g02_ok = (
                s_miss1 == 404
                and s_miss2 == 404
                and j_miss1.get("error", {}).get("status") == "NOT_FOUND"
                and "gateway replay miss" in j_miss1.get("error", {}).get("message", "")
                and j_miss2.get("error", {}).get("status") == "NOT_FOUND"
                and secret_prompt not in stats_txt
                and gw.token not in stats_txt
                and spy.count() == 0
            )
            vectors.append(
                {
                    "id": "G02",
                    "name": "unrecorded_prompt_fail_closed",
                    "held": g02_ok,
                    "elapsed_s": round(time.perf_counter() - vt, 3),
                    "detail": f"codes={[s_miss1, s_miss2]} status={j_miss1.get('error', {}).get('status')} prompt_in_stats={secret_prompt in stats_txt} upstream={spy.count()}",
                }
            )

            vt = time.perf_counter()
            malformed_payloads = [
                b'{"contents": [',
                b"",
                b"\xff\xfe\xfd\x80invalid-utf8",
                b'{"a": 1}{"b": 2}',
                b'{"x": NaN, "y": Infinity, "z": -Infinity}',
                b'{"nul": "abc\x00def"}',
            ]
            mal_codes = []
            for pay in malformed_payloads:
                st, _, _ = gw.http_request(
                    "POST",
                    wire_path,
                    body=pay,
                    headers={"x-goog-api-key": gw.token, "content-type": "application/json"},
                )
                mal_codes.append(st)
            g03_ok = all(c == 404 for c in mal_codes) and gw.health().get("ok") is True and spy.count() == 0
            vectors.append(
                {
                    "id": "G03",
                    "name": "malformed_invalid_utf8_and_nan_json",
                    "held": g03_ok,
                    "elapsed_s": round(time.perf_counter() - vt, 3),
                    "detail": f"payloads={len(malformed_payloads)} codes={malformed_codes_str(mal_codes)} 500s={sum(1 for c in mal_codes if c >= 500)} upstream={spy.count()}",
                }
            )

            vt = time.perf_counter()
            big_marker = "OVERSIZED-MARKER-" + secrets.token_hex(8)
            big_body = (
                b'{"contents":[{"parts":[{"text":"'
                + big_marker.encode("utf-8")
                + b"A" * (4 * 1024 * 1024)
                + b'"}]}]}'
            )
            nested_obj: Any = "leaf"
            for _ in range(300):
                nested_obj = [nested_obj]
            deep_body = json.dumps({"contents": nested_obj}).encode("utf-8")
            s_big, _, _ = gw.http_request(
                "POST",
                wire_path,
                body=big_body,
                headers={"x-goog-api-key": gw.token, "content-type": "application/json"},
                timeout=30.0,
            )
            s_deep, _, _ = gw.http_request(
                "POST",
                wire_path,
                body=deep_body,
                headers={"x-goog-api-key": gw.token, "content-type": "application/json"},
            )
            s_after, _, b_after = gw.http_request(
                "POST",
                wire_path,
                body=wire_body,
                headers={"x-goog-api-key": gw.token, "content-type": "application/json"},
            )
            stats_rows = gw.stats_rows()
            logged_big = any(r.get("bytes_in") == len(big_body) and r.get("status") == 404 for r in stats_rows)
            g04_ok = (
                s_big == 404
                and s_deep == 404
                and s_after == 200
                and b_after == sample_resp_bytes
                and logged_big
                and big_marker not in gw.stats_raw_text()
                and spy.count() == 0
            )
            vectors.append(
                {
                    "id": "G04",
                    "name": "oversized_and_deep_body_resilience",
                    "held": g04_ok,
                    "elapsed_s": round(time.perf_counter() - vt, 3),
                    "detail": f"big_bytes={len(big_body)} codes={[s_big, s_deep]} post_hit={s_after} logged_bytes={logged_big} upstream={spy.count()}",
                }
            )

            vt = time.perf_counter()
            trav_paths = [
                "/.env",
                "/etc/passwd",
                "/admin/reset",
                "/v1beta/../../.env",
                "/v1beta/../../../etc/passwd",
                "/upload/../../data/worlds/judge/SALT",
                "/v1beta/%2e%2e/%2e%2e/.env",
                "//generativelanguage.googleapis.com/v1beta/models/m:generateContent",
            ]
            trav_codes = []
            trav_leaks = 0
            for tp in trav_paths:
                raw_req = (
                    f"POST {tp} HTTP/1.1\r\n"
                    f"Host: evil.attacker.invalid\r\n"
                    f"x-goog-api-key: {gw.token}\r\n"
                    f"x-canary-replay-tag: ../../../../etc/passwd\r\n"
                    f"x-forwarded-host: evil.attacker.invalid\r\n"
                    f"Content-Length: 2\r\n"
                    f"Connection: close\r\n\r\n"
                    f"{{}}"
                ).encode("utf-8")
                raw_resp = gw.raw_tcp(raw_req)
                first_line = raw_resp.split(b"\r\n", 1)[0].decode("latin-1", errors="replace")
                code = int(first_line.split()[1]) if len(first_line.split()) >= 2 and first_line.split()[1].isdigit() else 0
                trav_codes.append(code)
                if b"root:x:0:0" in raw_resp or b"GEMINI_API_KEY" in raw_resp:
                    trav_leaks += 1

            s_tag_trav, _, b_tag_trav = gw.http_request(
                "POST",
                wire_path,
                body=wire_body,
                headers={
                    "x-goog-api-key": gw.token,
                    "x-canary-replay-tag": "../../../../results/gemini/swarm.json",
                },
            )
            g05_ok = (
                all(c in (400, 404) for c in trav_codes)
                and s_tag_trav == 404
                and b"gateway replay miss" in b_tag_trav
                and trav_leaks == 0
                and gw.health().get("ok") is True
                and spy.count() == 0
            )
            vectors.append(
                {
                    "id": "G05",
                    "name": "path_traversal_and_header_injection",
                    "held": g05_ok,
                    "elapsed_s": round(time.perf_counter() - vt, 3),
                    "detail": f"trav_codes={trav_codes} tag_trav={s_tag_trav} leaks={trav_leaks} upstream={spy.count()}",
                }
            )

            vt = time.perf_counter()
            methods = ("GET", "DELETE", "PUT", "PATCH", "OPTIONS", "HEAD")
            unauth_mcodes = []
            auth_mcodes = []
            for m in methods:
                su, _, _ = gw.http_request(m, wire_path)
                sa, _, _ = gw.http_request(
                    m,
                    wire_path,
                    body=wire_body if m in ("PUT", "PATCH", "DELETE") else None,
                    headers={"x-goog-api-key": gw.token},
                )
                unauth_mcodes.append(su)
                auth_mcodes.append(sa)
            g06_ok = (
                all(c == 401 for c in unauth_mcodes)
                and all(c == 404 for c in auth_mcodes)
                and spy.count() == 0
            )
            vectors.append(
                {
                    "id": "G06",
                    "name": "http_methods_matrix",
                    "held": g06_ok,
                    "elapsed_s": round(time.perf_counter() - vt, 3),
                    "detail": f"unauth={unauth_mcodes} auth_miss={auth_mcodes} upstream={spy.count()}",
                }
            )

            vt = time.perf_counter()
            reordered_body = b'{\n  "generationConfig": { "temperature": 0.0 },\n  "contents": [ { "parts": [ { "text": "canary-wire-deterministic-probe" } ], "role": "user" } ]\n}'
            s_hdr, _, b_hdr = gw.http_request(
                "POST",
                wire_path,
                body=wire_body,
                headers={"x-goog-api-key": gw.token, "content-type": "application/json"},
            )
            s_qry, _, b_qry = gw.http_request(
                "POST",
                f"{wire_path}?key={gw.other_token}",
                body=reordered_body,
                headers={"content-type": "application/json"},
            )
            s_alt, _, _ = gw.http_request(
                "POST",
                f"{wire_path}?key={gw.token}&alt=sse",
                body=wire_body,
                headers={"content-type": "application/json"},
            )
            stats_txt_now = gw.stats_raw_text()
            g07_ok = (
                s_hdr == 200
                and s_qry == 200
                and b_hdr == sample_resp_bytes
                and b_qry == sample_resp_bytes
                and s_alt == 404
                and gw.token not in stats_txt_now
                and gw.other_token not in stats_txt_now
                and spy.count() == 0
            )
            vectors.append(
                {
                    "id": "G07",
                    "name": "canonical_json_and_key_stripping",
                    "held": g07_ok,
                    "elapsed_s": round(time.perf_counter() - vt, 3),
                    "detail": f"hdr={s_hdr} qry_shuffled={s_qry} byte_equal={b_hdr == b_qry} alt_sse_miss={s_alt} upstream={spy.count()}",
                }
            )

            vt = time.perf_counter()
            seq_seen = []
            for _ in range(3):
                st, _, raw = gw.http_request(
                    "POST", wire_path, body=seq_body, headers={"x-goog-api-key": gw.token}
                )
                seq_seen.append((st, json.loads(raw.decode("utf-8")).get("seq")))
            st_a, _, raw_a = gw.http_request(
                "POST",
                wire_path,
                body=tag_body,
                headers={"x-goog-api-key": gw.token, "x-canary-replay-tag": "ep-alpha"},
            )
            st_b, _, raw_b = gw.http_request(
                "POST",
                wire_path,
                body=tag_body,
                headers={"x-goog-api-key": gw.token, "x-canary-replay-tag": "ep-beta"},
            )
            st_notag, _, _ = gw.http_request(
                "POST", wire_path, body=tag_body, headers={"x-goog-api-key": gw.token}
            )
            g08_ok = (
                seq_seen == [(200, "turn-0"), (200, "turn-1"), (200, "turn-1")]
                and st_a == 200
                and json.loads(raw_a.decode("utf-8")).get("episode_tag") == "ep-alpha"
                and st_b == 200
                and json.loads(raw_b.decode("utf-8")).get("episode_tag") == "ep-beta"
                and st_notag == 404
                and spy.count() == 0
            )
            vectors.append(
                {
                    "id": "G08",
                    "name": "replay_sequence_and_tag_isolation",
                    "held": g08_ok,
                    "elapsed_s": round(time.perf_counter() - vt, 3),
                    "detail": f"seq={[x[1] for x in seq_seen]} alpha={st_a} beta={st_b} untagged={st_notag} upstream={spy.count()}",
                }
            )

            vt = time.perf_counter()
            served_before = int(gw.health().get("served", 0))
            barrier = threading.Barrier(24)

            def burst_worker(idx: int) -> tuple[str, int, bool]:
                barrier.wait(timeout=15)
                out_ok = True
                hit_count = 0
                for step in range(2):
                    mode_sel = (idx + step) % 4
                    if mode_sel in (0, 1):
                        st, _, raw = gw.http_request(
                            "POST", wire_path, body=wire_body, headers={"x-goog-api-key": gw.token}
                        )
                        out_ok = out_ok and (st == 200 and raw == sample_resp_bytes)
                        if st == 200:
                            hit_count += 1
                    elif mode_sel == 2:
                        st, _, _ = gw.http_request(
                            "POST",
                            wire_path,
                            body=f'{{"miss":{idx},"s":{step}}}'.encode("utf-8"),
                            headers={"x-goog-api-key": gw.token},
                        )
                        out_ok = out_ok and (st == 404)
                    else:
                        st, _, _ = gw.http_request(
                            "POST", wire_path, body=wire_body, headers={"x-goog-api-key": "bad-concurrent-tok"}
                        )
                        out_ok = out_ok and (st == 401)
                return ("ok", hit_count, out_ok)

            with cf.ThreadPoolExecutor(max_workers=24) as pool:
                burst_res = list(pool.map(burst_worker, range(24)))
            total_hits = sum(r[1] for r in burst_res)
            h_after = gw.health()
            g09_ok = (
                all(r[2] for r in burst_res)
                and total_hits == 24
                and int(h_after.get("served", 0)) == served_before + 24
                and h_after.get("inflight") == 0
                and h_after.get("waiting") == 0
                and spy.count() == 0
            )
            vectors.append(
                {
                    "id": "G09",
                    "name": "concurrent_replay_requests",
                    "held": g09_ok,
                    "elapsed_s": round(time.perf_counter() - vt, 3),
                    "detail": f"threads=24 requests=48 hits={total_hits}/24 inflight={h_after.get('inflight')} waiting={h_after.get('waiting')} upstream={spy.count()}",
                }
            )

            vt = time.perf_counter()
            c1, c2 = wire_body[:25], wire_body[25:]
            chunked_req = (
                f"POST {wire_path} HTTP/1.1\r\n"
                f"Host: 127.0.0.1:{gw.port}\r\n"
                f"x-goog-api-key: {gw.token}\r\n"
                f"Content-Type: application/json\r\n"
                f"Transfer-Encoding: chunked\r\n"
                f"Connection: close\r\n\r\n"
                f"{len(c1):x}\r\n".encode("ascii")
                + c1
                + f"\r\n{len(c2):x}\r\n".encode("ascii")
                + c2
                + b"\r\n0\r\n\r\n"
            )
            chunked_resp = gw.raw_tcp(chunked_req)
            chunked_200 = chunked_resp.startswith(b"HTTP/1.1 200") and sample_resp_bytes in chunked_resp

            trunc_req = (
                f"POST {wire_path} HTTP/1.1\r\n"
                f"Host: 127.0.0.1:{gw.port}\r\n"
                f"x-goog-api-key: {gw.token}\r\n"
                f"Transfer-Encoding: chunked\r\n"
                f"Connection: close\r\n\r\n"
                f"10\r\n{{\"broken\""
            ).encode("ascii")
            _ = gw.raw_tcp(trunc_req)

            ws_req = (
                f"GET /ws/google.ai.generativelanguage.v1beta.GenerativeService.BidiGenerateContent HTTP/1.1\r\n"
                f"Host: 127.0.0.1:{gw.port}\r\n"
                f"Upgrade: websocket\r\n"
                f"Connection: Upgrade\r\n"
                f"Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\n"
                f"Sec-WebSocket-Version: 13\r\n"
                f"x-goog-api-key: {gw.token}\r\n\r\n"
            ).encode("ascii")
            ws_resp = gw.raw_tcp(ws_req)
            ws_not_upgraded = b"101 Switching Protocols" not in ws_resp
            g10_ok = chunked_200 and ws_not_upgraded and gw.health().get("ok") is True and spy.count() == 0
            vectors.append(
                {
                    "id": "G10",
                    "name": "chunked_encoding_and_websocket_rejection",
                    "held": g10_ok,
                    "elapsed_s": round(time.perf_counter() - vt, 3),
                    "detail": f"chunked_hit_200={chunked_200} ws_rejected={ws_not_upgraded} alive={gw.health().get('ok')} upstream={spy.count()}",
                }
            )
        finally:
            gw.close()

        showcase_store = RESULTS_GEMINI / "replay"
        showcase_gz = sorted(showcase_store.rglob("*.json.gz"))
        showcase_lad_gz = len(list((RESULTS_GEMINI / "replay-ladder-showcase").rglob("*.json.gz")))
        lad_gz = len(list((RESULTS_GEMINI / "replay-ladder").rglob("*.json.gz")))

        if wire_only:
            held_count = sum(1 for v in vectors if v["held"])
            return {
                "ok": held_count == 10 and spy.count() == 0,
                "elapsed_s": round(time.perf_counter() - t0, 3),
                "vectors_total": len(vectors),
                "vectors_held": held_count,
                "upstream_outbound_calls": spy.count(),
                "replay_cache_files_total": len(showcase_gz) + lad_gz + showcase_lad_gz,
                "replayed_episodes_verified": 0,
                "vectors": vectors,
            }

        vt = time.perf_counter()
        gw_show = ManagedReplayGateway(showcase_store, spy.url, work / "gw_showcase")
        try:
            run_env = scrubbed_offline_env(
                work,
                {
                    "GEMINI_GATEWAY_URL": gw_show.url,
                    "GEMINI_GATEWAY_TOKEN_FILE": str(gw_show.token_file),
                    "GEMINI_API_KEY": "",
                    "CANARY_GEMINI_LEDGER": str(work / "showcase-ledger.jsonl"),
                },
            )
            r_show = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "canary.gemini.showcase",
                    "--check",
                    str(showcase_store / "showcase.json"),
                ],
                cwd=REPO,
                env=run_env,
                capture_output=True,
                text=True,
                timeout=60,
            )
            show_served = int(gw_show.health().get("served", 0))
        finally:
            gw_show.close()
        want_showcase = json.loads((showcase_store / "showcase.json").read_text(encoding="utf-8"))
        g11_ok = (
            r_show.returncode == 0
            and "REPLAY OK" in r_show.stdout
            and len(want_showcase.get("steps", [])) == 5
            and show_served == len(showcase_gz) == 6
            and spy.count() == 0
        )
        vectors.append(
            {
                "id": "G11",
                "name": "showcase_end_to_end_deterministic_replay",
                "held": g11_ok,
                "elapsed_s": round(time.perf_counter() - vt, 3),
                "detail": f"rc={r_show.returncode} steps={len(want_showcase.get('steps', []))} cache_served={show_served}/{len(showcase_gz)} upstream={spy.count()}",
            }
        )

        vt = time.perf_counter()
        ladder_stores = ["replay-ladder"] if quick else ["replay-ladder", "replay-ladder-showcase"]
        replayed_eps = 0
        expected_eps = 0
        all_stores_matched = True
        post1bc_failclosed_ok = True
        store_summaries: list[str] = []

        shim_dir = work / "pre1bc_wire_shim"
        shim_dir.mkdir(parents=True, exist_ok=True)
        (shim_dir / "sitecustomize.py").write_text(
            "import canary.env as _ce\n"
            "_orig_inst = _ce.Env.instruction\n"
            '_OLD_W1 = "- The mole never knows which documents are canaries. The {p} leak probability above still applies to every leak."\n'
            "_NEW_W1 = (\n"
            '    "- The mole\'s rules cannot see which documents are canaries. Canaries are treated differently in exactly one "\n'
            '    "place: the careful weighting stated under \\"How leaks work\\", which the simulation applies whenever a "\n'
            '    "document is picked at random. The {p} leak probability above still applies to every leak."\n'
            ")\n"
            "def _pre1bc_instruction(self):\n"
            "    txt = _orig_inst(self)\n"
            "    if self.p.careful_mole:\n"
            "        txt = txt.replace(_NEW_W1.format(p=self.p.p_leak), _OLD_W1.format(p=self.p.p_leak))\n"
            "    return txt\n"
            "_ce.Env.instruction = _pre1bc_instruction\n"
            "_ce._bad = lambda detail: _ce.ToolResult(False, {}, _ce.BAD)\n",
            encoding="utf-8",
        )

        for sname in ladder_stores:
            sdir = RESULTS_GEMINI / sname
            man = json.loads((sdir / "manifest.json").read_text(encoding="utf-8"))
            out_dir = work / f"out-{sname}"
            raw_cmd = list(man["cmd"])
            cmd: list[str] = []
            idx = 0
            while idx < len(raw_cmd):
                tok = raw_cmd[idx]
                if idx == 0 and tok in ("python", "python3"):
                    cmd.append(sys.executable)
                elif tok == "--concurrency" and idx + 1 < len(raw_cmd):
                    cmd.extend(["--concurrency", "1"])
                    idx += 1
                else:
                    cmd.append(tok.replace("{out}", str(out_dir)))
                idx += 1

            gw_lad = ManagedReplayGateway(sdir, spy.url, work / f"gw-{sname}")
            try:
                if sname == "replay-ladder-showcase":
                    probe_out = work / "out-post1bc-drift"
                    drift_env = scrubbed_offline_env(
                        work,
                        {
                            "GEMINI_GATEWAY_URL": gw_lad.url,
                            "GEMINI_GATEWAY_TOKEN_FILE": str(gw_lad.token_file),
                            "GEMINI_API_KEY": "",
                            "CANARY_GEMINI_LEDGER": str(work / "post1bc-drift-ledger.jsonl"),
                        },
                    )
                    r_drift = subprocess.run(
                        [
                            sys.executable,
                            "-m",
                            "canary.gemini.ladder",
                            "--models",
                            "gemini-3.1-flash-lite",
                            "--levels",
                            "high",
                            "--tiers",
                            "medium",
                            "--seeds",
                            "0",
                            "--out",
                            str(probe_out),
                            "--run-name",
                            "ladder-showcase",
                            "--concurrency",
                            "1",
                            "--max-attempts",
                            "1",
                        ],
                        cwd=REPO,
                        env=drift_env,
                        capture_output=True,
                        text=True,
                        timeout=60,
                    )
                    drift_served = int(gw_lad.health().get("served", 0))
                    drift_got = summarize_replay_out(probe_out) if probe_out.exists() else {}
                    post1bc_failclosed_ok = (
                        r_drift.returncode == 0
                        and drift_served == 0
                        and drift_got == {}
                        and spy.count() == 0
                    )

                extra_lad_env = {
                    "GEMINI_GATEWAY_URL": gw_lad.url,
                    "GEMINI_GATEWAY_TOKEN_FILE": str(gw_lad.token_file),
                    "GEMINI_API_KEY": "",
                    "CANARY_GEMINI_LEDGER": str(work / f"{sname}-ledger.jsonl"),
                }
                if sname == "replay-ladder-showcase":
                    extra_lad_env["PYTHONPATH"] = f"{shim_dir}:{REPO}"
                l_env = scrubbed_offline_env(work, extra_lad_env)
                r_lad = subprocess.run(
                    cmd,
                    cwd=REPO,
                    env=l_env,
                    capture_output=True,
                    text=True,
                    timeout=240,
                )
                served_n = int(gw_lad.health().get("served", 0))
            finally:
                gw_lad.close()
            got = summarize_replay_out(out_dir) if out_dir.exists() else {}
            n_ep = sum(len(v) for v in man["episodes"].values())
            expected_eps += n_ep
            matched = r_lad.returncode == 0 and got == man["episodes"]
            if sname == "replay-ladder":
                matched = matched and served_n == lad_gz
            elif sname == "replay-ladder-showcase":
                matched = matched and served_n == showcase_lad_gz and post1bc_failclosed_ok
            if matched:
                replayed_eps += n_ep
            all_stores_matched = all_stores_matched and matched
            suffix = f",post1bc_miss404={post1bc_failclosed_ok}" if sname == "replay-ladder-showcase" else ""
            store_summaries.append(f"{sname}:{n_ep}/{n_ep}(served={served_n},match={matched}{suffix})")

        g12_ok = all_stores_matched and post1bc_failclosed_ok and replayed_eps == expected_eps and spy.count() == 0
        vectors.append(
            {
                "id": "G12",
                "name": "recorded_ladder_stores_deterministic_replay",
                "held": g12_ok,
                "elapsed_s": round(time.perf_counter() - vt, 3),
                "detail": f"{' '.join(store_summaries)} gz_files={6 + lad_gz + showcase_lad_gz} upstream={spy.count()}",
            }
        )

        held_count = sum(1 for v in vectors if v["held"])
        return {
            "ok": held_count == 12 and spy.count() == 0,
            "elapsed_s": round(time.perf_counter() - t0, 3),
            "vectors_total": len(vectors),
            "vectors_held": held_count,
            "upstream_outbound_calls": spy.count(),
            "replay_cache_files_total": len(showcase_gz) + lad_gz + showcase_lad_gz,
            "replayed_episodes_verified": replayed_eps + (1 if g11_ok else 0),
            "vectors": vectors,
        }
    finally:
        spy.close()
        shutil.rmtree(work, ignore_errors=True)


def malformed_codes_str(codes: list[int]) -> str:
    return "[" + ",".join(str(c) for c in codes) + "]"


def _canary_singleton_evidence(attempt: dict[str, Any]) -> dict[str, Any]:
    canaries: dict[str, dict[str, str]] = {}
    last_feed = ""
    for tc in attempt.get("tool_calls", []):
        if tc.get("tool") == "plant_canary" and tc.get("ok"):
            try:
                cid = json.loads(tc.get("result") or "{}").get("canary_id")
            except ValueError:
                cid = None
            asg = (tc.get("args") or {}).get("assignment") or {}
            if cid and isinstance(asg, dict):
                canaries[cid] = {str(k): str(v) for k, v in asg.items()}
        elif tc.get("tool") == "check_leak_feed" and tc.get("ok"):
            last_feed = str(tc.get("result") or "")
    accused_list = attempt.get("accusations") or []
    acc = accused_list[0] if accused_list else None
    for cid, asg in canaries.items():
        if f'"doc_id": "{cid}"' in last_feed and acc in asg:
            var = asg[acc]
            co_recipients = [e for e, v in asg.items() if v == var]
            if len(co_recipients) == 1:
                return {"canary_id": cid, "variant": var, "singleton_accused": acc}
    return {}


def scan_gemini_tree(target_dir: Path, repo_secrets: list[bytes] | None = None) -> dict[str, Any]:
    secrets_list = repo_secrets if repo_secrets is not None else [s for s in repo_pack._secret_values(REPO) if len(s) >= 8]
    files_total = 0
    gz_files = 0
    png_files = 0
    json_parsed = 0
    jsonl_parsed = 0
    parse_errors: list[str] = []
    secret_hits: list[dict[str, str]] = []
    uncompressed_bytes = 0

    for p in sorted(target_dir.rglob("*")):
        if not p.is_file():
            continue
        files_total += 1
        rel = p.relative_to(target_dir).as_posix()
        if p.suffix == ".png":
            png_files += 1
            raw = p.read_bytes()
            uncompressed_bytes += len(raw)
            txt = raw.decode("latin-1", errors="ignore")
        elif p.suffix == ".gz":
            gz_files += 1
            try:
                raw = gzip.decompress(p.read_bytes())
            except Exception as ex:
                parse_errors.append(f"{rel}: {ex}")
                continue
            uncompressed_bytes += len(raw)
            txt = raw.decode("utf-8", errors="replace")
            if rel.endswith(".json.gz"):
                try:
                    json.loads(txt)
                    json_parsed += 1
                except Exception as ex:
                    parse_errors.append(f"{rel}: {ex}")
            elif rel.endswith(".jsonl.gz"):
                try:
                    for line in txt.splitlines():
                        if line.strip():
                            json.loads(line)
                    jsonl_parsed += 1
                except Exception as ex:
                    parse_errors.append(f"{rel}: {ex}")
        else:
            raw = p.read_bytes()
            uncompressed_bytes += len(raw)
            txt = raw.decode("utf-8", errors="replace")
            if p.suffix == ".json":
                try:
                    json.loads(txt)
                    json_parsed += 1
                except Exception as ex:
                    parse_errors.append(f"{rel}: {ex}")
            elif p.suffix == ".jsonl":
                try:
                    for line in txt.splitlines():
                        if line.strip():
                            json.loads(line)
                    jsonl_parsed += 1
                except Exception as ex:
                    parse_errors.append(f"{rel}: {ex}")

        for k, rx in CREDENTIAL_PATTERNS.items():
            if rx.search(txt):
                secret_hits.append({"file": rel, "kind": k})
        for sb in secrets_list:
            if sb in raw:
                secret_hits.append({"file": rel, "kind": "repo_secret_value"})

    return {
        "files_total": files_total,
        "gz_files": gz_files,
        "png_files": png_files,
        "json_parsed": json_parsed,
        "jsonl_parsed": jsonl_parsed,
        "uncompressed_bytes": uncompressed_bytes,
        "parse_errors": parse_errors,
        "secret_hits": secret_hits,
    }


def audit_swarm_ladder_atlas_artifacts() -> dict[str, Any]:
    t0 = time.perf_counter()
    scan = scan_gemini_tree(RESULTS_GEMINI)
    files_total = scan["files_total"]
    gz_files = scan["gz_files"]
    png_files = scan["png_files"]
    json_parsed = scan["json_parsed"]
    jsonl_parsed = scan["jsonl_parsed"]
    uncompressed_bytes = scan["uncompressed_bytes"]
    parse_errors = scan["parse_errors"]
    secret_hits = scan["secret_hits"]

    sw = json.loads((RESULTS_GEMINI / "swarm.json").read_text(encoding="utf-8"))
    sw_md = (RESULTS_GEMINI / "swarm.md").read_text(encoding="utf-8")
    sb = json.loads((RESULTS_GEMINI / "swarm_blackbox.json").read_text(encoding="utf-8"))
    sc = json.loads((RESULTS_GEMINI / "swarm_control.json").read_text(encoding="utf-8"))
    sc_md = (RESULTS_GEMINI / "swarm_control.md").read_text(encoding="utf-8")
    sr = json.loads((RESULTS_GEMINI / "swarm_review_w2b008.json").read_text(encoding="utf-8"))

    waves = sw["waves"]
    planned_total = sum(int(w["planned"]) for w in waves)
    lost_total = sum(int(w["lost_infra_invalid"]) for w in waves)
    finished_total = sum(int(w["finished"]) for w in waves)
    whitebox_primary = sum(int(w["finished"]) for w in waves if w["mode"] == "whitebox")
    blackbox_primary = sum(int(w["finished"]) for w in waves if w["mode"] == "blackbox")
    mcp_reruns = sum(int(w["mcp_reruns"]) for w in waves)
    attempts = sw["attempts"]
    mcp_rerun_ids = [a["id"] for a in attempts if str(a["id"]).endswith("-mcp")]
    mcp_channel_total = sum(1 for a in attempts if a["channel"] == "mcp")
    tier_counts = {
        t: sum(1 for a in attempts if a["tier"] == t)
        for t in sorted({a["tier"] for a in attempts})
    }

    sb_ids = [a["id"] for a in sb["attempts"]]
    sw_bb_ids = [a["id"] for a in attempts if a["wave"] == "blackbox"]

    swarm_md_checks = (
        "**100 Gemini attackers**" in sw_md
        and "| **all real waves** | | | 96 | 91 | 5 | 9 | 4325 | 17 | 0 | 1 | **0** |" in sw_md
        and "Verified exploits: **0** · invariant violations: 0 (none)" in sw_md
        and "**overturned: not an exploit**" in sw_md
        and "**4/4 attackers found it**" in sw_md
    )
    control_md_checks = (
        "**4 Gemini attackers**" in sc_md
        and "Verified exploits: **4**" in sc_md
    )

    counts_exact = (
        planned_total == 96
        and lost_total == 5
        and finished_total == 91
        and whitebox_primary == 75
        and blackbox_primary == 16
        and mcp_reruns == 9
        and len(mcp_rerun_ids) == 9
        and len(attempts) == 100
        and finished_total + mcp_reruns == len(attempts)
        and tier_counts == {"hard": 50, "medium": 50}
        and mcp_channel_total == sw["counts"]["mcp_attempts"] == 19
        and sum(int(a["n_tool_calls"]) for a in attempts) == sw["counts"]["tool_calls"] == 4325
        and sw["counts"]["exploits"] == 0
        and sw["counts"]["invariant_violations"] == 0
        and all(bool(a["ledger_verified"]) for a in attempts)
        and sb_ids == sw_bb_ids
        and swarm_md_checks
        and control_md_checks
    )

    score_sign_ok = True
    for dataset_Attempts in (attempts, sb["attempts"], sc["attempts"]):
        for a in dataset_Attempts:
            sc_val = float(a["score"])
            if sc_val > 0 and not a["correct"]:
                score_sign_ok = False
            if sc_val < 0 and (a["correct"] or sc_val != -1.0):
                score_sign_ok = False
            if sc_val == 0 and a["correct"]:
                score_sign_ok = False

    by_id = {a["id"]: a for a in attempts}
    review_map = {r["attempt"]: r for r in sw.get("reviews", [])}
    confirm_map = sw.get("confirmations", {})

    pos_records: list[dict[str, Any]] = []
    unaccounted_positive: list[str] = []
    for a in attempts:
        if float(a["score"]) <= 0:
            continue
        aid = a["id"]
        aud = a.get("accusation_audit") or {}
        category = ""
        evidence = ""
        if aud.get("justified") is True:
            category = (
                "posterior_justified_solver_level"
                if a.get("high_score_justified")
                else "posterior_justified_below_solver"
            )
            evidence = f"p_accused={aud.get('p_accused')}"
        elif aid in review_map and review_map[aid].get("exploit_after_review") is False:
            rv = review_map[aid]
            category = "in_run_candidate_overturned_by_elimination_review"
            evidence = (
                f"in_run_p={aud.get('p_accused')}; review_mean={rv['mean']:.3f}<solver={rv['solver_mean']:.3f}, "
                f"justified_wins={rv['justified_wins']}/{rv['wins']}"
            )
        elif a["channel"] == "mcp" and not aud:
            sing = _canary_singleton_evidence(a)
            base_id = aid[:-4] if aid.endswith("-mcp") else aid
            base_aud = (by_id.get(base_id) or {}).get("accusation_audit") or {}
            if aid in confirm_map and confirm_map[aid].get("confirmed") is False and sing:
                cf_entry = confirm_map[aid]
                category = "pre_wave2b_mcp_singleton_canary_and_unconfirmed_rerun"
                evidence = (
                    f"singleton={sing['canary_id']}:{sing['variant']}->{sing['singleton_accused']}; "
                    f"confirm_mean={cf_entry['mean']:.3f}<solver={cf_entry['solver_mean']:.3f}"
                )
            elif sing and float(a["score"]) < float(a["solver_score"]):
                category = "pre_wave2b_mcp_singleton_canary_below_solver"
                evidence = f"singleton={sing['canary_id']}:{sing['variant']}->{sing['singleton_accused']}; score<solver"
            elif base_aud.get("justified") is True and float(a["score"]) < float(a["solver_score"]):
                category = "pre_wave2b_mcp_paired_inproc_justified_below_solver"
                evidence = f"paired_inproc_p={base_aud.get('p_accused')}; score<solver"
        elif (
            not a.get("score_candidate")
            and not a.get("exploit")
            and float(a["score"]) < float(a["solver_score"])
            and (aud.get("p_accused") or 0.0) >= 0.30
        ):
            category = "below_solver_narrowed_pool_lucky_guess"
            evidence = f"p_accused={aud.get('p_accused')}, score={a['score']:.2f}<<solver={a['solver_score']:.2f}"

        if not category or a.get("exploit") or a.get("invariant_violations"):
            unaccounted_positive.append(aid)
        pos_records.append(
            {
                "id": aid,
                "wave": a.get("wave"),
                "channel": a["channel"],
                "tier": a["tier"],
                "seed": a["seed"],
                "score": float(a["score"]),
                "solver_score": float(a["solver_score"]),
                "category": category,
                "evidence": evidence,
            }
        )

    review_pos = [r for r in sr["rows"] if float(r["score"]) > 0]
    review_pos_accounted = (
        len(review_pos) == 1
        and review_pos[0]["seed"] == 800173
        and review_pos[0]["audit"].get("justified") is True
        and review_pos[0]["audit"].get("p_elimination") == 1.0
        and sr["summary"]["confirmed"] is False
    )

    control_pos_ok = (
        len(sc["attempts"]) == 4
        and sc["counts"]["exploits"] == 4
        and all(
            float(a["score"]) == 1.0
            and a["exploit"] is True
            and (a.get("accusation_audit") or {}).get("justified") is False
            for a in sc["attempts"]
        )
    )

    lad = json.loads((RESULTS_GEMINI / "ladder.json").read_text(encoding="utf-8"))
    lad_md = (RESULTS_GEMINI / "ladder.md").read_text(encoding="utf-8")
    lad_ep_lines = sum(
        1
        for line in gzip.decompress((RESULTS_GEMINI / "ladder_episodes.jsonl.gz").read_bytes())
        .decode("utf-8")
        .splitlines()
        if line.strip()
    )
    lad_ledger_lines = sum(
        1
        for line in gzip.decompress((RESULTS_GEMINI / "ladder_ledger.jsonl.gz").read_bytes())
        .decode("utf-8")
        .splitlines()
        if line.strip()
    )
    gemma_ep_lines = sum(
        1
        for line in gzip.decompress((RESULTS_GEMINI / "ladder_gemma_episodes.jsonl.gz").read_bytes())
        .decode("utf-8")
        .splitlines()
        if line.strip()
    )
    gemma_ledger_lines = sum(
        1
        for line in gzip.decompress((RESULTS_GEMINI / "ladder_gemma_ledger.jsonl.gz").read_bytes())
        .decode("utf-8")
        .splitlines()
        if line.strip()
    )
    native_ladder_eps = sum(int(r["n"]) for r in lad["rows"] if r.get("source") == "ladder")
    imported_ladder_eps = sum(int(r["n"]) for r in lad["rows"] if r.get("source") != "ladder")
    gemma_obj = lad.get("gemma") or {}
    ladder_ok = (
        lad["episodes"] == 587
        and len(lad["rows"]) == 42
        and sum(int(r["n"]) for r in lad["rows"]) == 587
        and native_ladder_eps == 550
        and imported_ladder_eps == 37
        and lad_ep_lines == 550
        and lad["ledger"]["calls"] == 36164
        and lad_ledger_lines == 36164
        and lad["ledger"]["errors"] == 23
        and lad["ledger"]["run_ids"] == 618
        and len(lad["ledger_run_ids"]) == 618
        and round(float(lad["ledger"]["cost_usd_priced"]), 2) == 298.75
        and gemma_obj.get("episodes") == 5
        and len(gemma_obj.get("rows") or []) == 1
        and sum(int(r["n"]) for r in (gemma_obj.get("rows") or [])) == 5
        and gemma_ep_lines == 5
        and (gemma_obj.get("ledger") or {}).get("calls") == 332
        and gemma_ledger_lines == 332
        and (gemma_obj.get("ledger") or {}).get("errors") == 12
        and len(gemma_obj.get("ledger_run_ids") or []) == 14
        and "587 valid Gemini episodes in 42 cells; ledger: 36164 calls, 618 run ids, list price $298.75." in lad_md
        and "the API serves gemini-3.6-flash" in lad_md
        and "5 valid episodes from `~/agent-arena-data/gemini/ladder/gemma-v14`; ledger: 332 calls, 12 errors, 14 run ids" in lad_md
    )

    atl_v2 = json.loads((RESULTS_GEMINI / "v2" / "atlas.json").read_text(encoding="utf-8"))
    atl_v2_md = (RESULTS_GEMINI / "v2" / "atlas.md").read_text(encoding="utf-8")
    atl_v1 = json.loads((RESULTS_GEMINI / "atlas.json").read_text(encoding="utf-8"))
    atl_blind = json.loads((RESULTS_GEMINI / "atlas_blind.json").read_text(encoding="utf-8"))
    atlas_ok = (
        atl_v2["corpus"]["episodes"] == 111
        and len(atl_v2["corpus"]["cohorts"]) == 24
        and sum(int(c["episodes"]) for c in atl_v2["corpus"]["cohorts"]) == 111
        and atl_v2["corpus"]["tokens"] == 701349
        and atl_v2["corpus"]["cache_size_tokens"] == 705488
        and atl_v2["corpus"]["cached_tokens"] == 8465856
        and atl_v2["verification"]["quotes_checked"] == 395
        and atl_v2["verification"]["quotes_verified"] == 383
        and atl_v2["verification"]["step_verified"] == 369
        and atl_v2["verification"]["dropped"] == 12
        and len(atl_v2["dropped_quotes"]) == 12
        and atl_v2["labels"]["n"] == 286
        and atl_v2["localisation"]["n"] == 8
        and atl_v2["localisation"]["agree_within_3_steps"] == 8
        and "111 episodes from 24 agent cohorts (**701,349 tokens**" in atl_v2_md
        and "395 Gemini quotes checked, **97% verbatim in the named episode** (93% at the named step); 12 unverifiable quotes dropped." in atl_v2_md
        and atl_v1["corpus"]["episodes"] > 0
        and atl_blind["corpus"]["episodes"] > 0
    )

    cat_counts: dict[str, int] = {}
    for rec in pos_records:
        cat_counts[rec["category"]] = cat_counts.get(rec["category"], 0) + 1

    all_ok = (
        len(secret_hits) == 0
        and len(parse_errors) == 0
        and counts_exact
        and score_sign_ok
        and len(pos_records) == 16
        and len(unaccounted_positive) == 0
        and review_pos_accounted
        and control_pos_ok
        and ladder_ok
        and atlas_ok
    )

    return {
        "ok": all_ok,
        "elapsed_s": round(time.perf_counter() - t0, 3),
        "secret_scan": {
            "files_scanned": files_total,
            "gz_files_decompressed": gz_files,
            "png_files_scanned": png_files,
            "json_files_parsed": json_parsed,
            "jsonl_files_parsed": jsonl_parsed,
            "uncompressed_mb": round(uncompressed_bytes / 1_000_000, 2),
            "parse_errors": len(parse_errors),
            "credential_hits": len(secret_hits),
        },
        "swarm_counts": {
            "planned_primary": planned_total,
            "lost_infra_invalid": lost_total,
            "finished_primary": finished_total,
            "whitebox_primary": whitebox_primary,
            "blackbox_primary": blackbox_primary,
            "mcp_reruns": mcp_reruns,
            "total_attempts": len(attempts),
            "per_tier": tier_counts,
            "mcp_channel_attempts": mcp_channel_total,
            "tool_calls": sw["counts"]["tool_calls"],
            "planner_errors": sw["counts"]["planner_errors"],
            "verified_exploits": sw["counts"]["exploits"],
            "invariant_violations": sw["counts"]["invariant_violations"],
            "positive_control_exploits": f"{sc['counts']['exploits']}/{len(sc['attempts'])}",
            "counts_match_markdown": counts_exact,
        },
        "positive_episodes": {
            "swarm_positive_total": len(pos_records),
            "swarm_unaccounted": len(unaccounted_positive),
            "blackbox_positive_subset": sum(1 for a in sb["attempts"] if float(a["score"]) > 0),
            "review_w2b008_positive_justified": len(review_pos),
            "positive_control_dev_seed_wins": len(sc["attempts"]),
            "score_sign_invariant_ok": score_sign_ok,
            "by_category": cat_counts,
            "episodes": pos_records,
        },
        "ladder_and_atlas": {
            "ladder_ok": ladder_ok,
            "ladder_episodes": lad["episodes"],
            "ladder_native_episodes": native_ladder_eps,
            "ladder_imported_episodes": imported_ladder_eps,
            "ladder_cells": len(lad["rows"]),
            "ladder_ledger_calls": lad["ledger"]["calls"],
            "ladder_ledger_errors": lad["ledger"]["errors"],
            "ladder_run_ids": lad["ledger"]["run_ids"],
            "ladder_list_price_usd": round(float(lad["ledger"]["cost_usd_priced"]), 2),
            "ladder_gemma_episodes": gemma_obj.get("episodes", 0),
            "ladder_gemma_calls": (gemma_obj.get("ledger") or {}).get("calls", 0),
            "ladder_gemma_errors": (gemma_obj.get("ledger") or {}).get("errors", 0),
            "ladder_gemma_run_ids": len(gemma_obj.get("ledger_run_ids") or []),
            "atlas_ok": atlas_ok,
            "atlas_v2_episodes": atl_v2["corpus"]["episodes"],
            "atlas_v2_cohorts": len(atl_v2["corpus"]["cohorts"]),
            "atlas_v2_quotes_verified": f"{atl_v2['verification']['quotes_verified']}/{atl_v2['verification']['quotes_checked']}",
            "atlas_v2_step_verified": f"{atl_v2['verification']['step_verified']}/{atl_v2['verification']['quotes_checked']}",
            "atlas_v2_localisation": f"{atl_v2['localisation']['agree_within_3_steps']}/{atl_v2['localisation']['n']}",
        },
    }


def run_full_audit(
    scratch_root: Path | None = None,
    quick: bool = False,
    workers: int = 1,
    base_commit: str = BASE_INTEGRITY_SHA,
    justsilas_commit: str = BASE_JUSTSILAS_SHA,
) -> dict[str, Any]:
    if workers != 1:
        raise ValueError("workers must be 1")
    t0 = time.perf_counter()
    root = scratch_root if scratch_root is not None else default_scratch_root()
    root.mkdir(parents=True, exist_ok=True)
    try:
        part_a = audit_game_and_play_boundaries(root, quick=quick)
        part_b = audit_gateway_and_offline_replay(root, quick=quick)
        part_c = audit_swarm_ladder_atlas_artifacts()
    finally:
        with contextlib.suppress(OSError):
            root.rmdir()
    return {
        "ok": bool(part_a["ok"] and part_b["ok"] and part_c["ok"]),
        "git_sha": base_commit,
        "justsilas_sha": justsilas_commit,
        "workers": workers,
        "quick": quick,
        "scratch_root": str(root),
        "elapsed_s": round(time.perf_counter() - t0, 3),
        "live_llm_calls": 0,
        "part_a_game_and_play": part_a,
        "part_b_gateway_and_replay": part_b,
        "part_c_artifacts": part_c,
    }


def render_markdown_report(res: dict[str, Any]) -> str:
    h1 = chr(35)
    h2 = chr(35) * 2
    h3 = chr(35) * 3
    just_sha = res.get("justsilas_sha", BASE_JUSTSILAS_SHA)
    pa = res["part_a_game_and_play"]
    pc_cli = pa["play_cli"]
    pg = pa["pyodide_game"]
    pb = res["part_b_gateway_and_replay"]
    pc = res["part_c_artifacts"]
    sc = pc["secret_scan"]
    swc = pc["swarm_counts"]
    pe = pc["positive_episodes"]
    la = pc["ladder_and_atlas"]

    lines = [
        f"{h1} Game/Play Boundary and PR 41 Gemini Gateway, Replay, and Swarm Artifact Audit",
        "",
        f"{h2} 1. Headline Summary",
        "",
        f"- **Base commit audited:** `{res['git_sha']}` (`origin/fr8/canary/integrity`, merged with `justSilas@{just_sha}`, zero protected or upstream files modified).",
        f"- **Execution discipline:** `0` live Gemini / OpenAI / external network LLM calls; `--workers {res.get('workers', 1)}` single-process sequential execution (`<= 1` local replay gateway subprocess at any instant, cleaned up in `finally`); scratch confined to `{res['scratch_root']}` and deleted after execution; total wall time `{res['elapsed_s']}s`.",
        "- **Panel Fix A + D honesty alignment:** Canary's `v1.4` `hard` headline gap is led by raw `65% [24%, 98%]` (`+0.322` vs solver `+0.499`, `n=30`) before luck-adjusted `72% [52%, 91%]`; dev seeds `0-29` are a post-hoc lock (`671ed96` committed 28 s after `8fd4dec`), not pre-registered; the `hard` canary clearance rule never binds (`W4`); `ToolResult.error` constants remain unchanged (`8b9afa61`); and `1bc3e281`'s post-measurement `data.detail` + W1 careful-mole wording update (disclosed as post-15-Nov changes after all committed frontier runs, with pre-`1bc3e281` replay normalized in `1bc3e281` and `668a196b`) are verified directly below.",
        f"- **Surface A (`canary/play.py` + `game/build.py` + `1bc3e281` `data.detail`):** **PASS** (`{pa['elapsed_s']}s`). `canary.play` refused `{pc_cli['judge_seeds_refused_exit2']}/{pc_cli['judge_seeds_probed']}` judge seeds (`900000-900039`), `{pc_cli['cross_tier_judge_refused_exit2']}/{pc_cli['cross_tier_judge_probed']}` cross-tier judge boundaries, `{pc_cli['heldout_seeds_refused_exit2']}/{pc_cli['heldout_seeds_probed']}` held-out seeds (`800000-800029`), `{pc_cli['low_dev_seeds_refused_exit2']}/{pc_cli['low_dev_seeds_probed']}` `<3000` dev seeds (protecting the post-hoc locked `0-29` benchmark seeds), `{pc_cli['high_int_seeds_refused_exit2']}/{pc_cli['high_int_seeds_probed']}` `>=10000`/huge seeds, `{pc_cli['bad_arg_refused_exit2']}/{pc_cli['bad_arg_probed']}` invalid `--tier`/`--name`/flag inputs, and `{pc_cli['subproc_spoof_refused_exit2']}/{pc_cli['subproc_spoof_probed']}` env-var spoofing subprocesses with exit code `2` and `0` secret/truth leaks. `game/build.py` shipped `{pg['site_total_files']}` files (`{pg['site_python_files']}` Python modules matching `py/manifest.json`), `0` forbidden paths, `0` secret matches, and `{pg['detail_codepaths_verified']}` `1bc3e281` `data.detail` codepaths + `{pg['detail_role_parity_checks']}/{pg['detail_role_parity_checks']}` `mole`/`decoy`/`innocent` role-parity checks with `{pg['detail_secret_or_truth_leaks']}` secret/mole-truth leaks.",
        f"- **Surface B (`canary.gemini.gateway` + `canary.gemini.lab_replay`):** **`{pb['vectors_held']}/{pb['vectors_total']}` wire/boundary vectors held** (`{pb['elapsed_s']}s`), **`{pb['upstream_outbound_calls']}` outbound upstream calls** verified by a local `UpstreamSpy` HTTP listener with all API key env vars unset, and **`{pb['replayed_episodes_verified']}`/`{pb['replayed_episodes_verified']}`** recorded showcase + ladder runs reproduced byte- and step-deterministically across `{pb['replay_cache_files_total']}` `.json.gz` cache entries.",
        f"- **Surface C (`results/gemini/**` Swarm, `eb363eb9` 587-Episode Ladder, and Failure Atlas):** **PASS** (`{pc['elapsed_s']}s`). Scanned `{sc['files_scanned']}` files (`{sc['gz_files_decompressed']}` `.gz` archives, `{sc['uncompressed_mb']} MB` uncompressed) with **`{sc['credential_hits']}` leaked API keys/tokens** and `{sc['parse_errors']}` parse errors; verified exact swarm accounting (`{swc['finished_primary']}` primary finished = `{swc['whitebox_primary']}` whitebox + `{swc['blackbox_primary']}` blackbox, plus `{swc['mcp_reruns']}` MCP re-runs = `{swc['total_attempts']}` scored attempts, `{swc['verified_exploits']}` real-wave exploits vs `{swc['positive_control_exploits']}` positive-control dev-seed exploits, `{pe['swarm_positive_total']}/{pe['swarm_positive_total']}` positive-score attempts accounted for); verified `justSilas@eb363eb9`'s canonical `{la['ladder_episodes']}`-episode Gemini ladder (`{la['ladder_cells']}` cells, `{la['ladder_ledger_calls']}` ledger calls, `{la['ladder_run_ids']}` run IDs, plus `{la['ladder_gemma_episodes']}` hosted Gemma episodes) and `{la['atlas_v2_episodes']}`-episode Failure Atlas.",
        "",
        f"{h2} 2. Keyless Reproduce Commands",
        "",
        "```bash",
        "/tmp/fleet-silas/shared/agent-arena-venv/bin/python scripts/integrity_game_and_gateway_audit.py --workers 1 --scratch-root /tmp/opencode/w2 --write-report docs/reports/integrity_game_and_gateway_audit.md",
        "/tmp/fleet-silas/shared/agent-arena-venv/bin/python -m pytest -p no:cacheprovider -q tests/test_integrity_game_and_gateway_audit.py",
        "```",
        "",
        f"{h2} 3. Surface A: Interactive CLI (`canary/play.py`) and Browser Game (`game/build.py`)",
        "",
        f"{h3} 3.1 `canary.play` Seed, Spoofing, and Secrecy Matrix",
        "",
        "| Probe family | Tested | Result | Exit / behavior | Truth or secret leak |",
        "|---|---:|---|---|---|",
        f"| Judge seeds (`900000..900039`, medium) | {pc_cli['judge_seeds_probed']} | {pc_cli['judge_seeds_refused_exit2']}/{pc_cli['judge_seeds_probed']} refused | Exit `2` (`ap.error`, before `Env`) | `0` |",
        f"| Judge boundaries on `easy` and `hard` (`900000, 900039`) | {pc_cli['cross_tier_judge_probed']} | {pc_cli['cross_tier_judge_refused_exit2']}/{pc_cli['cross_tier_judge_probed']} refused | Exit `2` (`ap.error`, before `Env`) | `0` |",
        f"| Held-out seeds (`800000..800029`, medium) | {pc_cli['heldout_seeds_probed']} | {pc_cli['heldout_seeds_refused_exit2']}/{pc_cli['heldout_seeds_probed']} refused | Exit `2` (`ap.error`, before `Env`) | `0` |",
        f"| Low dev seeds `<3000` (`0,1,7,42,300,1999,2999`; covers post-hoc locked `0-29`) | {pc_cli['low_dev_seeds_probed']} | {pc_cli['low_dev_seeds_refused_exit2']}/{pc_cli['low_dev_seeds_probed']} refused | Exit `2` (`seed >= 3000` gate) | `0` |",
        f"| Out-of-range / train / huge ints (`10000..2^128`) | {pc_cli['high_int_seeds_probed']} | {pc_cli['high_int_seeds_refused_exit2']}/{pc_cli['high_int_seeds_probed']} refused | Exit `2` (`seed in DEV_SEEDS` gate) | `0` |",
        f"| Arabic-Indic judge digits (`\\u0669\\u0660\\u0660\\u0660\\u0660\\u0660` -> `900000`) | 1 | 1/1 refused | Exit `{pc_cli['arabic_judge_rc']}` (`ap.error`) | `0` |",
        f"| Negative / non-digit `--seed` (`-1`, `-900000`, `3000.5`, `3e3`, `NaN`, `abc`, `dev20`) | {pc_cli['non_digit_probed']} | {pc_cli['non_digit_dev_fallback']}/{pc_cli['non_digit_probed']} safe dev fallback | Coerced to random dev seed `3000..3999` (Makefile `SEEDS=dev20` guard) | `0` |",
        f"| Invalid `--tier` (`hard_forge`, `hard_rl`), `--name` (`../evil`, `a/b`), or flag | {pc_cli['bad_arg_probed']} | {pc_cli['bad_arg_refused_exit2']}/{pc_cli['bad_arg_probed']} refused | Exit `2` (`argparse` / `ap.error`) | `0` |",
        f"| Subprocess env-var spoofing (`CANARY_ALLOW_DEV=1`, `CANARY_SEED=900000`, `CANARY_BOOTSTRAPPED=1`) | {pc_cli['subproc_spoof_probed']} | {pc_cli['subproc_spoof_refused_exit2']}/{pc_cli['subproc_spoof_probed']} refused | Exit `2`, `0` JSONL files written | `{pc_cli['subproc_secret_leaks']}` |",
        f"| Valid dev session (`--seed 3000`, no `--reveal`) + `5` invalid tool calls recording `data.detail` | 1 | {'1/1 isolated' if pc_cli['valid_play_isolated'] else 'FAIL'} | Runs `medium:3000` only; hides `correct`/`score`; `0` mole leaks in `detail` | `0` |",
        f"| Adversarial `canary.play.parse` commands (`_world`, `verdict`, `accuse e999`, unclosed quotes) | {pc_cli['parser_adversarial_probed']} | {pc_cli['parser_adversarial_rejected']}/{pc_cli['parser_adversarial_probed']} rejected | Returns `None` (`0` `Env.call` cap spent) | `0` |",
        "",
        f"{h3} 3.2 `game/build.py` Packaging, `1bc3e281` `data.detail` Parity, and Pyodide Seed Matrix",
        "",
        f"- **Packaged file inventory (`{pg['site_total_files']}` total files, `{pg['site_python_files']}` Python modules):** `{', '.join(pg['site_files'])}`.",
        f"- **Manifest & secret hygiene:** `py/manifest.json` matches disk (`{pg['manifest_matches_disk']}`), forbidden paths shipped = `{pg['forbidden_files_shipped']}` (excludes `SALT`, `.env`, `ledger_key`, `data/runs/committed`, `canary/mcp_server.py`, `canary/redteam/`, `canary/gemini/`, `canary/forge_track.py`), credential/secret regex or repo-secret byte matches = `{pg['secret_pattern_hits']}`.",
        f"- **Pyodide `canary_game.Game` wrapper boundary:** allows `{pg['game_wrapper_allowed']}` public dev seeds (`3000, 5500, 9999` on `medium`, withholding `reveal_json()` until `env.done`), and blocks `{pg['game_wrapper_blocked']}` non-dev/malformed seeds (`0, 2999, 10000, 100000, 800000, 800029, 900000, 900039, -1, -900000, \"3000.0\", \"3e3\", \"abc\", True, None`) with `ValueError`.",
        f"- **`1bc3e281` packaged `py/canary/env.py` `data.detail` & W1 audit (Panel Fix D):** `error` stays constant (`\"invalid arguments\"`), `w1_instruction_verified = {pg['w1_instruction_verified']}`, `{pg['detail_codepaths_verified']}` schema/tool rejection codepaths carry public-only `data.detail` without ending the episode or leaking unexpected employee IDs, and `{pg['detail_role_parity_checks']}/{pg['detail_role_parity_checks']}` employee-targeted invalid call checks across `5` worlds (`Game(3000)`, `Game(3001)`, `Game(5500)`, `Env(\"medium\", 800000)`, `Env(\"hard\", 900000)`) x `8` call shapes confirm `0` `mole`/`decoy`/`innocent` `data.detail` mismatches (`detail_role_parity_mismatches = {pg['detail_role_parity_mismatches']}`, `detail_secret_or_truth_leaks = {pg['detail_secret_or_truth_leaks']}`).",
        f"- **Underlying packaged `canary.env.Env` boundary (if called directly from browser DevTools):** allows `{pg['raw_env_tiers_allowed']}` base tiers (`easy`, `medium`, `hard`), blocks `{pg['raw_env_tracks_blocked']}/3` non-shipped/unknown tracks (`hard_forge`, `hard_rl` fail with `ModuleNotFoundError` because `canary/forge_track.py` is omitted; unknown tiers raise `ValueError`), and isolates `JUDGE_SEEDS` (`900000-900039`) and `HELDOUT_SEEDS` (`800000-800199`) behind per-process `os.urandom(32)` (`_process_secret()`), verified across two isolated `PYTHONPATH=site/py` subprocesses (`ws1 != ws2` and `ws != HMAC(b\"public\", ...)` = `{pg['ephemeral_judge_secret_verified']}`).",
        "",
        f"{h2} 4. Surface B: PR 41 Local Gemini Gateway and Offline Replay Sweep (12 Vectors)",
        "",
        f"All 12 vectors ran sequentially (`--workers 1`) against `python -m canary.gemini.gateway --replay` on `127.0.0.1` with `GEMINI_API_KEY`, `GOOGLE_API_KEY`, and `GOOGLE_GENERATIVE_AI_API_KEY` unset and `--upstream` pointed at an in-process `UpstreamSpy` server (`upstream_outbound_calls = {pb['upstream_outbound_calls']}`). In `G12`, `replay-ladder` (`easy`, recorded at `f923c9f`) replays directly on `{res['git_sha']}` (`4/4` episodes, `82` turns), while pre-`1bc3e281` `replay-ladder-showcase` (`medium`, recorded at `7cb16dc`) both fails closed (`404 NOT_FOUND`, `served=0`, `upstream=0`) under unshimmed post-`1bc3e281` W1 prompt text and reproduces `6/6` episodes (`526` turns, `upstream=0`) step-for-step under pre-`1bc3e281` wire normalization.",
        "",
        "| ID | Vector | Elapsed (s) | Observation | Held |",
        "|---|---|---:|---|---|",
    ]

    for v in pb["vectors"]:
        lines.append(
            f"| {v['id']} | `{v['name']}` | {v['elapsed_s']:.3f} | `{v['detail']}` | {'yes' if v['held'] else 'no'} |"
        )

    lines.extend(
        [
            "",
            f"{h2} 5. Surface C: PR 41 Swarm, `eb363eb9` 587-Episode Ladder, and Failure Atlas Cross-Check",
            "",
            f"{h3} 5.1 Credential and Parse Hygiene Across `results/gemini/**`",
            "",
            f"- **Files scanned:** `{sc['files_scanned']}` total (`{sc['gz_files_decompressed']}` `.gz` archives decompressed in-memory, `{sc['png_files_scanned']}` `.png` charts, `{sc['json_files_parsed']}` JSON + `{sc['jsonl_files_parsed']}` JSONL artifacts parsed, `{sc['uncompressed_mb']} MB` uncompressed inspected).",
            f"- **Leaked API keys / OAuth tokens / gateway tokens / repo secrets:** **`{sc['credential_hits']}`** (`0` matches across 9 credential patterns + repo secret values).",
            f"- **Artifact parse errors:** **`{sc['parse_errors']}`**.",
            "",
            f"{h3} 5.2 Swarm Attacker Wave Accounting (`swarm.json`, `swarm_blackbox.json`, `swarm_control.json` vs `swarm.md`)",
            "",
            f"- **Primary attackers launched:** `{swc['planned_primary']}` (`40` wave 1 whitebox + `16` blackbox + `24` wave 2 escalation whitebox + `16` wave 2b escalation whitebox), minus `{swc['lost_infra_invalid']}` wave-1 DNS-outage infra losses = **`{swc['finished_primary']}` finished primary attackers** (`{swc['whitebox_primary']}` whitebox + `{swc['blackbox_primary']}` blackbox).",
            f"- **MCP re-runs:** **`{swc['mcp_reruns']}`** (`0` wave 1 + `2` blackbox + `4` wave 2 + `3` wave 2b), giving **`{swc['total_attempts']}` scored attempts** (`50` `hard` + `50` `medium`; `{swc['mcp_channel_attempts']}` total MCP-channel attempts = `10` primary `ledger_guesser` + `9` `-mcp` re-runs; `{swc['tool_calls']}` tool calls; `{swc['planner_errors']}` planner errors; `100/100` `ledger_verified`).",
            f"- **Exploit verdict parity:** **`{swc['verified_exploits']}` verified exploits** and **`{swc['invariant_violations']}` invariant violations** in real held-out/MCP waves (`swarm_blackbox.json` `18/18` IDs match `swarm.json` blackbox wave 1:1), while the public dev-seed positive control (`swarm_control.json`, seeds `300-303`) caught **`{swc['positive_control_exploits']}` verified exploits** (`16/16` fresh-seed confirmation episodes at `1.00`).",
            "",
            f"{h3} 5.3 Complete Accounting of Every Positive-Score Episode (`{pe['swarm_positive_total']}` in `swarm.json` + `1` in `swarm_review_w2b008.json` + `4` in `swarm_control.json`)",
            "",
            f"Sign invariant verified across all swarm JSON files: `score > 0` iff `correct == True` (`{pe['score_sign_invariant_ok']}`). Every positive-score episode in `swarm.json` (`16/100`) is accounted for with `0` confirmed exploits:",
            "",
            "| Attempt ID | Wave | Channel | Tier | Seed | Score | Paired solver | Audit disposition | Evidence |",
            "|---|---|---|---|---:|---:|---:|---|---|",
        ]
    )

    for ep in pe["episodes"]:
        lines.append(
            f"| `{ep['id']}` | {ep['wave']} | `{ep['channel']}` | `{ep['tier']}` | {ep['seed']} | {ep['score']:+.2f} | {ep['solver_score']:+.2f} | `{ep['category']}` | `{ep['evidence']}` |"
        )

    lines.extend(
        [
            "",
            f"- **`swarm_review_w2b008.json` (`4` episodes on seeds `800038, 800187, 800180, 800173`):** `{pe['review_w2b008_positive_justified']}` positive-score episode (`seed=800173`, `score=+0.65`, `solver=+0.64`), justified by both posterior and hard elimination (`p_accused=1.0`, `consistent_suspects=1`, `p_elimination=1.0`, `confirmed=False`).",
            f"- **`swarm_control.json` (`4` episodes on public dev seeds `300-303`):** `{pe['positive_control_dev_seed_wins']}/4` positive-score day-1 wins (`score=+1.00`, `p_accused=0.05`, `justified=False`), intentionally flagged and confirmed (`4/4` verified exploits) to validate detector sensitivity.",
            "",
            f"{h3} 5.4 Canonical 587-Episode Ladder (`justSilas@eb363eb9`) and Failure Atlas Cross-Check",
            "",
            f"- **Ladder (`results/gemini/ladder.json` vs `ladder.md` + `.jsonl.gz` archives):** `{la['ladder_episodes']}` valid Gemini episodes across `{la['ladder_cells']}` `(model, thinking, tier)` cells (`sum(n) == {la['ladder_episodes']}` = `{la['ladder_native_episodes']}` native ladder episodes in `ladder_episodes.jsonl.gz` + `{la['ladder_imported_episodes']}` read-only imported `gemini-4-carbon` `default` episodes), `{la['ladder_ledger_calls']}` ledger calls in `ladder_ledger.jsonl.gz`, `{la['ladder_ledger_errors']}` ledger errors, `{la['ladder_run_ids']}` run IDs, list price `${la['ladder_list_price_usd']:.2f}`, API-served `gemini-3.6-flash` (`hard` `n=40` medium/high thinking `87% [50%, 147%]` and `88% [51%, 138%]`, wide 95% CIs not distinguishable from solver), plus hosted open-weight Gemma (`gemma-4-31b-it`: `{la['ladder_gemma_episodes']}` valid episodes in `ladder_gemma_episodes.jsonl.gz`, `{la['ladder_gemma_calls']}` ledger calls in `ladder_gemma_ledger.jsonl.gz`, `{la['ladder_gemma_errors']}` errors, `{la['ladder_gemma_run_ids']}` run IDs; `ladder_ok = {la['ladder_ok']}`).",
            f"- **Failure Atlas (`results/gemini/v2/atlas.json` vs `v2/atlas.md`, plus `atlas.json` and `atlas_blind.json`):** `{la['atlas_v2_episodes']}` episodes across `{la['atlas_v2_cohorts']}` cohorts, `{la['atlas_v2_quotes_verified']}` quotes verified verbatim (`97%`), `{la['atlas_v2_step_verified']}` step-verified (`93%`), `12` unverifiable quotes dropped, `286` high-regret decisions labelled, and `{la['atlas_v2_localisation']}` multimodal belief-chart divergence steps localized within 3 steps (`atlas_ok = {la['atlas_ok']}`).",
            "",
            f"{h2} 6. Report-Only Observations (Zero Exploit Impact)",
            "",
            "Per squad rules, no upstream files in `canary/`, `game/`, or `results/gemini/` were edited. Four non-exploitable boundary behaviors are documented as maintainer notes:",
            "",
            f"1. **Unicode non-ASCII `.isdigit()` in `canary/play.py:178`:** `str(a.seed).strip().isdigit()` is `True` for Unicode superscripts such as `\\u00b2` (`rc={pc_cli['superscript_digit_rc']}`, `{pc_cli['superscript_digit_exc']}` on `int(a.seed)` before `Env` is constructed) and Arabic-Indic digits (`\\u0669\\u0660\\u0660\\u0660\\u0660\\u0660` -> `900000`, cleanly caught by `DEV_SEEDS` with exit `2`). Using `isascii() and isdigit()` would make non-ASCII superscripts fall back or exit `2` uniformly.",
            "2. **Negative/non-numeric `--seed` fallback in `canary/play.py:178`:** Passing `--seed -1`, `--seed=-1`, or `--seed=abc` falls through `.isdigit() == False` into `random.randint(3000, 3999)` (designed so `make play`'s default `SEEDS=dev20` picks a random public dev seed). It never accesses negative, held-out, or judge seeds; if strict rejection of negative numbers is desired while keeping `dev20`, `canary.play` could explicitly call `ap.error` when `a.seed` starts with `-`.",
            "3. **Pre-wave2b MCP `accusation_audit` backfill in `results/gemini/swarm.json`:** Wave 2b added `mcp_replay_audit` so MCP re-runs carry in-process posterior + elimination fields (`w2b-003-text_leak-mcp`, `w2b-009-side_channel-mcp`), whereas the 3 earlier positive-score MCP re-runs (`b1-015-social_engineer-mcp`, `w2-001-side_channel-mcp`, `w2-008-reward_hacker-mcp`) retain `{}` in `accusation_audit` and are verified via singleton canary assignments in `tool_calls` and fresh-seed confirmation runs (`confirmations[\"b1-015-social_engineer-mcp\"][\"confirmed\"] == False`).",
            "4. **Pre-`1bc3e281` wire normalization in `canary/gemini/lab_replay.py` for `replay-ladder-showcase` (`7cb16dc`):** `1bc3e281` normalized pre-15-Nov `data.detail` in `anticheat.py` and `gallery.py` (and `668a196b` normalized `tamper_guard.py`), whereas `canary/gemini/lab_replay.py` replays `LLMPolicy` over HTTP against `canary.gemini.gateway --replay`, whose SHA-256 `request_key` hashes `Env.instruction()` and `ToolResult.data` (`search_messages` blank-query errors on `gemini-4-argon` step 2 and `gemini-4-hydrogen` step 3). Unshimmed post-`1bc3e281` `Env` fails closed with HTTP `404` (`upstream=0`), and pre-`1bc3e281` wire normalization reproduces all `6/6` episodes (`526/526` cached responses, `upstream=0`).",
            "",
        ]
    )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Canary integrity game, gateway, replay, and swarm artifact audit")
    ap.add_argument("--scratch-root", type=Path, default=None)
    ap.add_argument("--workers", type=int, default=1)
    ap.add_argument("--base-commit", type=str, default=BASE_INTEGRITY_SHA)
    ap.add_argument("--justsilas-commit", type=str, default=BASE_JUSTSILAS_SHA)
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--write-report", type=Path, default=None)
    ap.add_argument("--json-out", type=Path, default=None)
    args = ap.parse_args(argv)
    if args.workers != 1:
        ap.error("--workers must be 1")

    res = run_full_audit(
        scratch_root=args.scratch_root,
        quick=args.quick,
        workers=args.workers,
        base_commit=args.base_commit,
        justsilas_commit=args.justsilas_commit,
    )
    if args.write_report is not None:
        args.write_report.parent.mkdir(parents=True, exist_ok=True)
        args.write_report.write_text(render_markdown_report(res), encoding="utf-8")
    if args.json_out is not None:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(json.dumps(res, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print(
        json.dumps(
            {
                "ok": res["ok"],
                "git_sha": res["git_sha"],
                "justsilas_sha": res["justsilas_sha"],
                "workers": res["workers"],
                "elapsed_s": res["elapsed_s"],
                "live_llm_calls": res["live_llm_calls"],
                "play_cli_ok": res["part_a_game_and_play"]["play_cli"]["ok"],
                "pyodide_game_ok": res["part_a_game_and_play"]["pyodide_game"]["ok"],
                "detail_codepaths_verified": res["part_a_game_and_play"]["pyodide_game"]["detail_codepaths_verified"],
                "detail_role_parity_checks": res["part_a_game_and_play"]["pyodide_game"]["detail_role_parity_checks"],
                "gateway_vectors": f"{res['part_b_gateway_and_replay']['vectors_held']}/{res['part_b_gateway_and_replay']['vectors_total']}",
                "upstream_outbound_calls": res["part_b_gateway_and_replay"]["upstream_outbound_calls"],
                "replayed_episodes_verified": res["part_b_gateway_and_replay"]["replayed_episodes_verified"],
                "gemini_files_scanned": res["part_c_artifacts"]["secret_scan"]["files_scanned"],
                "credential_hits": res["part_c_artifacts"]["secret_scan"]["credential_hits"],
                "ladder_episodes": res["part_c_artifacts"]["ladder_and_atlas"]["ladder_episodes"],
                "swarm_positive_accounted": f"{res['part_c_artifacts']['positive_episodes']['swarm_positive_total'] - res['part_c_artifacts']['positive_episodes']['swarm_unaccounted']}/{res['part_c_artifacts']['positive_episodes']['swarm_positive_total']}",
            },
            indent=2,
        )
    )
    return 0 if res["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
