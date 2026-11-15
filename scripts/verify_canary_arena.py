from __future__ import annotations

import argparse
from contextlib import contextmanager
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib
import importlib.util
import inspect
import io
import json
import math
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import threading
import time
import tokenize
from typing import Any, Callable, Iterable, Iterator, Sequence
import urllib.error
import urllib.parse
import urllib.request
from wsgiref.simple_server import WSGIRequestHandler, make_server as make_wsgi_server

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from canary import llm as canary_llm
from canary.arena.be_the_mole import (
    ArenaRevealError,
    BeTheMoleSession,
    INVESTIGATOR_NAMES,
    check_arena_seed,
)
from canary.arena.living_office import (
    GATE_B_METRICS,
    LivingOfficeSession,
    list_v16_checkpoint_replays,
    load_v16_checkpoint_replay,
)
from canary.env import Env
from canary.rules import HELDOUT_SEEDS, JUDGE_SEEDS

HASH_CHAR = chr(35)
SLASH_CHAR = chr(47)
STAR_CHAR = chr(42)
EM_DASH = chr(0x2014)
EN_DASH = chr(0x2013)

DEFAULT_BASE_REF = "origin/justSilas"
DEFAULT_PROTECTED_PATHS_REL = Path(".github") / "protected-paths.txt"

CLEARED_API_KEY_VARS: tuple[str, ...] = (
    "GOOGLE_API_KEY",
    "GEMINI_API_KEY",
    "OPENAI_API_KEY",
)

LOOPBACK_HOSTS: frozenset[str] = frozenset({"127.0.0.1", "localhost", "::1"})

SECRET_PATTERNS: tuple[tuple[str, Any], ...] = (
    (
        "google_api_key",
        __import__("re").compile(r"(?<![0-9A-Za-z+/_-])" + "AI" + r"za[0-9A-Za-z_-]{16,}"),
    ),
    (
        "sk_api_key",
        __import__("re").compile(
            r"(?<![0-9A-Za-z+/_-])" + "sk" + r"-(?:proj-|ant-|live-|test-|svcacct-)?[0-9A-Za-z_-]{16,}"
        ),
    ),
    (
        "github_pat",
        __import__("re").compile(r"(?<![0-9A-Za-z+/_-])" + "ghp" + r"_[0-9A-Za-z]{20,}"),
    ),
)

BINARY_EXTENSIONS: frozenset[str] = frozenset(
    {
        ".png",
        ".jpg",
        ".jpeg",
        ".gif",
        ".webp",
        ".ico",
        ".bmp",
        ".woff",
        ".woff2",
        ".ttf",
        ".otf",
        ".mp3",
        ".wav",
        ".ogg",
        ".mp4",
        ".webm",
        ".zip",
        ".gz",
        ".tar",
        ".pyc",
        ".pyo",
        ".so",
        ".pdf",
    }
)

JS_EXTENSIONS: frozenset[str] = frozenset({".js", ".mjs", ".cjs"})

JS_REGEX_KEYWORDS: frozenset[str] = frozenset(
    {
        "return",
        "throw",
        "case",
        "in",
        "of",
        "typeof",
        "instanceof",
        "void",
        "delete",
        "new",
        "yield",
        "await",
        "else",
        "do",
    }
)

FORBIDDEN_BTM_PRE_END_KEYS: frozenset[str] = frozenset(
    {
        "is_canary",
        "variants",
        "canary_xray",
        "daily_p_mole",
        "true_mole",
        "true_mole_id",
        "mole_summary",
        "select_weights",
        "accused",
        "correct",
        "true_v",
    }
)

FORBIDDEN_INVESTIGATOR_PRE_END_KEYS: frozenset[str] = frozenset(
    {
        "true_mole",
        "true_mole_id",
        "mole_id",
        "secret_mole",
        "is_mole",
        "is_decoy",
        "is_canary",
        "variants",
        "canary_xray",
        "primary_suspect",
        "secondary_suspect",
        "target_suspect",
        "world_secret",
    }
)

MUST_BE_NONE_PRE_END_KEYS: frozenset[str] = frozenset(
    {
        "reveal",
        "verdict",
        "xray",
    }
)

SUSPICIOUS_MOLE_KEY_TOKENS: tuple[str, ...] = (
    "mole",
    "culprit",
    "secret",
    "accused",
    "verdict",
    "xray",
    "reveal",
    "suspect",
    "answer",
    "hidden",
    "debug",
    "truth",
    "internal",
    "target",
)

ALLOWED_PUBLIC_MOLE_CONFIG_KEYS: frozenset[str] = frozenset(
    {
        "mode",
        "mole_opponent",
        "mole_name",
        "mole_strategy",
        "mole_advisors",
        "mole_view",
    }
)

ALLOWED_FLOORPLAN_EMPLOYEE_KEYS: frozenset[str] = frozenset(
    {
        "id",
        "name",
        "dept",
        "role",
        "clearance",
        "grid_x",
        "grid_y",
        "pixel_x",
        "pixel_y",
        "status",
        "bubble_preview",
        "sprite",
        "avatar",
        "restricted",
        "interviewed",
    }
)

FORBIDDEN_FLOORPLAN_STATUSES: frozenset[str] = frozenset(
    {
        "mole",
        "true_mole",
        "decoy",
        "is_mole",
        "is_decoy",
        "culprit",
    }
)


@dataclass
class CheckResult:
    name: str
    status: str
    passed: bool
    required: bool
    duration_ms: float
    summary: str
    details: list[str] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status,
            "passed": self.passed,
            "required": self.required,
            "duration_ms": round(self.duration_ms, 3),
            "summary": self.summary,
            "details": list(self.details),
            "metrics": dict(self.metrics),
        }


def _is_loopback_host(host: str | None) -> bool:
    if not host:
        return False
    clean = host.strip().lower().strip("[]")
    return clean in LOOPBACK_HOSTS


def _extract_request_url(target: Any) -> str:
    if isinstance(target, str):
        return target
    full_url = getattr(target, "full_url", None)
    if isinstance(full_url, str):
        return full_url
    get_full_url = getattr(target, "get_full_url", None)
    if callable(get_full_url):
        return str(get_full_url())
    return str(target)


@contextmanager
def offline_arena_guard() -> Iterator[dict[str, int]]:
    telemetry: dict[str, int] = {
        "live_api_calls": 0,
        "stub_llm_calls": 0,
        "blocked_llm_calls": 0,
        "blocked_network_calls": 0,
        "blocked_calls": 0,
        "blocked_api_attempts": 0,
        "loopback_requests": 0,
    }
    tracked_env_vars = (*CLEARED_API_KEY_VARS, "CANARY_OFFLINE", "SLEEPER_OFFLINE", "CANARY_GEMINI_CACHE_DIR")
    saved_env: dict[str, str | None] = {k: os.environ.get(k) for k in tracked_env_vars}

    orig_get_client = canary_llm.get_client
    orig_urlopen = urllib.request.urlopen
    orig_urlretrieve = urllib.request.urlretrieve
    orig_create_connection = socket.create_connection

    def _guarded_get_client(spec: str, **kw: Any) -> Any:
        provider, _, _ = str(spec).partition(":")
        if provider == "stub":
            telemetry["stub_llm_calls"] += 1
            return orig_get_client(spec, **kw)
        telemetry["blocked_llm_calls"] += 1
        telemetry["blocked_calls"] += 1
        telemetry["blocked_api_attempts"] += 1
        raise RuntimeError(f"live LLM provider blocked by offline_arena_guard: {spec!r}")

    def _guarded_urlopen(url: Any, *args: Any, **kwargs: Any) -> Any:
        url_str = _extract_request_url(url)
        parsed = urllib.parse.urlsplit(url_str)
        if parsed.scheme in ("http", "https") and _is_loopback_host(parsed.hostname):
            telemetry["loopback_requests"] += 1
            return orig_urlopen(url, *args, **kwargs)
        telemetry["blocked_network_calls"] += 1
        telemetry["blocked_calls"] += 1
        telemetry["blocked_api_attempts"] += 1
        raise RuntimeError(f"non-loopback urllib request blocked by offline_arena_guard: {url_str!r}")

    def _guarded_urlretrieve(url: str, *args: Any, **kwargs: Any) -> Any:
        parsed = urllib.parse.urlsplit(str(url))
        if parsed.scheme in ("http", "https") and _is_loopback_host(parsed.hostname):
            telemetry["loopback_requests"] += 1
            return orig_urlretrieve(url, *args, **kwargs)
        telemetry["blocked_network_calls"] += 1
        telemetry["blocked_calls"] += 1
        telemetry["blocked_api_attempts"] += 1
        raise RuntimeError(f"non-loopback urlretrieve blocked by offline_arena_guard: {url!r}")

    def _guarded_create_connection(address: Any, *args: Any, **kwargs: Any) -> Any:
        host = address[0] if isinstance(address, tuple) and len(address) >= 1 else None
        if _is_loopback_host(str(host) if host is not None else None):
            return orig_create_connection(address, *args, **kwargs)
        telemetry["blocked_network_calls"] += 1
        telemetry["blocked_calls"] += 1
        telemetry["blocked_api_attempts"] += 1
        raise RuntimeError(f"non-loopback socket connection blocked by offline_arena_guard: {address!r}")

    tmp_base = "/tmp/opencode" if Path("/tmp/opencode").is_dir() else None
    with tempfile.TemporaryDirectory(prefix="arena_verify_cache_", dir=tmp_base) as empty_cache:
        try:
            for key_var in CLEARED_API_KEY_VARS:
                os.environ[key_var] = ""
            os.environ["CANARY_OFFLINE"] = "1"
            os.environ["SLEEPER_OFFLINE"] = "1"
            os.environ["CANARY_GEMINI_CACHE_DIR"] = empty_cache
            canary_llm.get_client = _guarded_get_client
            urllib.request.urlopen = _guarded_urlopen
            urllib.request.urlretrieve = _guarded_urlretrieve
            socket.create_connection = _guarded_create_connection
            yield telemetry
        finally:
            canary_llm.get_client = orig_get_client
            urllib.request.urlopen = orig_urlopen
            urllib.request.urlretrieve = orig_urlretrieve
            socket.create_connection = orig_create_connection
            for key_name, prev_val in saved_env.items():
                if prev_val is None:
                    os.environ.pop(key_name, None)
                else:
                    os.environ[key_name] = prev_val


def check_offline_guard_contract() -> CheckResult:
    t0 = time.perf_counter()
    failures: list[str] = []
    with offline_arena_guard() as tel:
        for key_var in CLEARED_API_KEY_VARS:
            if os.environ.get(key_var, "") != "":
                failures.append(f"{key_var} was not cleared inside offline_arena_guard")
        if os.environ.get("CANARY_OFFLINE") != "1":
            failures.append("CANARY_OFFLINE != '1' inside offline_arena_guard")
        if os.environ.get("SLEEPER_OFFLINE") != "1":
            failures.append("SLEEPER_OFFLINE != '1' inside offline_arena_guard")

        stub_client = canary_llm.get_client("stub")
        if stub_client is None:
            failures.append("stub client returned None")
        stub_script_client = canary_llm.get_client("stub:")
        if stub_script_client is None:
            failures.append("stub: client returned None")

        for real_spec in ("gemini", "gemini:gemini-4-carbon", "openai:gpt-5.5"):
            try:
                canary_llm.get_client(real_spec)
                failures.append(f"get_client({real_spec!r}) unexpectedly succeeded")
            except RuntimeError:
                pass

        for ext_url in ("https://generativelanguage.googleapis.com/v1beta/models", "https://api.openai.com/v1/responses"):
            try:
                urllib.request.urlopen(ext_url, timeout=1)
                failures.append(f"urlopen({ext_url!r}) unexpectedly succeeded")
            except RuntimeError:
                pass

        if tel["live_api_calls"] != 0:
            failures.append(f"expected 0 live_api_calls, got {tel['live_api_calls']}")
        if tel["stub_llm_calls"] < 2:
            failures.append(f"expected >=2 stub_llm_calls, got {tel['stub_llm_calls']}")
        if tel["blocked_llm_calls"] != 3:
            failures.append(f"expected 3 blocked_llm_calls, got {tel['blocked_llm_calls']}")
        if tel["blocked_network_calls"] != 2:
            failures.append(f"expected 2 blocked_network_calls, got {tel['blocked_network_calls']}")

    dt = (time.perf_counter() - t0) * 1000.0
    passed = len(failures) == 0
    return CheckResult(
        name="offline_arena_guard",
        status="PASS" if passed else "FAIL",
        passed=passed,
        required=True,
        duration_ms=dt,
        summary="Keyless env vars cleared, stub allowed, real LLM and non-loopback HTTP blocked" if passed else "; ".join(failures),
        details=failures,
        metrics=dict(tel),
    )


def parse_protected_rules(text: str) -> list[str]:
    rules: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith(HASH_CHAR):
            continue
        rules.append(line)
    return rules


def match_protected_paths(changed_files: Iterable[str], rules: Sequence[str]) -> list[str]:
    hits: set[str] = set()
    for rel in changed_files:
        clean = rel.strip().lstrip("./")
        if not clean:
            continue
        for rule in rules:
            if rule.endswith("/"):
                if clean.startswith(rule):
                    hits.add(clean)
            elif clean == rule:
                hits.add(clean)
    return sorted(hits)


def check_protected_paths(
    root: Path = ROOT,
    base_ref: str = DEFAULT_BASE_REF,
    protected_paths_rel: Path = DEFAULT_PROTECTED_PATHS_REL,
    changed_files_override: Iterable[str] | None = None,
) -> CheckResult:
    t0 = time.perf_counter()
    root = Path(root).resolve()
    local_prot = root / protected_paths_rel
    local_rules = parse_protected_rules(local_prot.read_text(encoding="utf-8")) if local_prot.is_file() else []

    if changed_files_override is not None:
        rules = local_rules
        violations = match_protected_paths(changed_files_override, rules)
        if not rules:
            violations.append("empty protected-paths rule set")
        dt = (time.perf_counter() - t0) * 1000.0
        passed = len(violations) == 0
        return CheckResult(
            name="protected_paths",
            status="PASS" if passed else "FAIL",
            passed=passed,
            required=True,
            duration_ms=dt,
            summary=f"0/{len(rules)} protected rules touched" if passed else f"protected path violations: {violations}",
            details=violations,
            metrics={"n_rules": len(rules), "violations": len(violations), "base_ref_present": False},
        )

    git_ok = (
        subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=10,
        ).returncode
        == 0
    )
    if not git_ok:
        dt = (time.perf_counter() - t0) * 1000.0
        return CheckResult(
            name="protected_paths",
            status="PASS",
            passed=True,
            required=True,
            duration_ms=dt,
            summary=f"non-git directory ({len(local_rules)} local rules loaded)",
            details=[],
            metrics={"git_repo": False, "n_rules": len(local_rules), "base_ref_present": False},
        )

    ref_proc = subprocess.run(
        ["git", "rev-parse", "--verify", f"{base_ref}^{{commit}}"],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=10,
    )
    base_present = ref_proc.returncode == 0

    rules = list(local_rules)
    if base_present:
        show_proc = subprocess.run(
            ["git", "show", f"{base_ref}:{protected_paths_rel.as_posix()}"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if show_proc.returncode == 0:
            rules = parse_protected_rules(show_proc.stdout)

    changed: set[str] = set()
    failures: list[str] = []
    if base_present:
        diff_proc = subprocess.run(
            ["git", "diff", "--name-only", f"{base_ref}...HEAD"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=15,
        )
        if diff_proc.returncode != 0:
            failures.append(f"git diff failed vs {base_ref}")
        else:
            changed.update(ln.strip() for ln in diff_proc.stdout.splitlines() if ln.strip())

    for cmd in (["git", "diff", "--name-only", "HEAD"], ["git", "diff", "--name-only", "--cached"]):
        proc = subprocess.run(cmd, cwd=root, capture_output=True, text=True, timeout=10)
        if proc.returncode == 0:
            changed.update(ln.strip() for ln in proc.stdout.splitlines() if ln.strip())

    touched = match_protected_paths(changed, rules)
    if touched:
        failures.extend(f"protected path touched: {p}" for p in touched)
    if not rules:
        failures.append("empty protected-paths rule set")

    dt = (time.perf_counter() - t0) * 1000.0
    passed = len(failures) == 0
    return CheckResult(
        name="protected_paths",
        status="PASS" if passed else "FAIL",
        passed=passed,
        required=True,
        duration_ms=dt,
        summary=(
            f"0/{len(rules)} protected rules touched vs {base_ref}"
            if passed and base_present
            else (f"0/{len(rules)} protected rules touched (working tree)" if passed else "; ".join(failures))
        ),
        details=failures,
        metrics={
            "git_repo": True,
            "base_ref": base_ref,
            "base_ref_present": base_present,
            "n_rules": len(rules),
            "n_changed_files": len(changed),
            "violations": touched,
        },
    )


def scan_dashes(text: str) -> list[dict[str, Any]]:
    hits: list[dict[str, Any]] = []
    for line_no, line in enumerate(text.splitlines(), start=1):
        for col_no, ch in enumerate(line, start=1):
            if ch == EM_DASH:
                hits.append({"kind": "em_dash", "line": line_no, "col": col_no})
            elif ch == EN_DASH:
                hits.append({"kind": "en_dash", "line": line_no, "col": col_no})
    return hits


def _redact_secret(val: str) -> str:
    if len(val) <= 8:
        return val[:3] + "..."
    return val[:6] + "..."


def scan_secrets(text: str) -> list[dict[str, Any]]:
    hits: list[dict[str, Any]] = []
    for line_no, line in enumerate(text.splitlines(), start=1):
        for label, pattern in SECRET_PATTERNS:
            for match in pattern.finditer(line):
                hits.append(
                    {
                        "kind": label,
                        "line": line_no,
                        "col": match.start() + 1,
                        "redacted": _redact_secret(match.group(0)),
                    }
                )
    return hits


def scan_python_comments(text: str) -> list[dict[str, Any]]:
    hits: list[dict[str, Any]] = []
    try:
        for tok in tokenize.generate_tokens(io.StringIO(text).readline):
            if tok.type == tokenize.COMMENT:
                hits.append(
                    {
                        "kind": "python_comment",
                        "line": int(tok.start[0]),
                        "col": int(tok.start[1]) + 1,
                    }
                )
    except (tokenize.TokenError, IndentationError) as exc:
        hits.append({"kind": "python_tokenize_error", "line": 1, "col": 1, "error": str(exc)})
    return hits


def scan_js_comments(text: str) -> list[dict[str, Any]]:
    hits: list[dict[str, Any]] = []
    n = len(text)
    i = 0
    line = 1
    col = 1
    state = "code"
    can_start_regex = True
    template_brace_stack: list[int] = []

    def _adv(steps: int = 1) -> None:
        nonlocal i, line, col
        for _ in range(steps):
            if i >= n:
                return
            if text[i] == "\n":
                line += 1
                col = 1
            else:
                col += 1
            i += 1

    while i < n:
        ch = text[i]
        nxt = text[i + 1] if i + 1 < n else ""

        if state == "code":
            if ch == SLASH_CHAR and nxt == SLASH_CHAR:
                hits.append({"kind": "js_line_comment", "line": line, "col": col})
                _adv(2)
                while i < n and text[i] != "\n":
                    _adv(1)
                continue
            if ch == SLASH_CHAR and nxt == STAR_CHAR:
                hits.append({"kind": "js_block_comment", "line": line, "col": col})
                _adv(2)
                while i < n:
                    if text[i] == STAR_CHAR and (i + 1 < n and text[i + 1] == SLASH_CHAR):
                        _adv(2)
                        break
                    _adv(1)
                continue
            if ch == "'":
                state = "single_quote"
                can_start_regex = False
                _adv(1)
                continue
            if ch == '"':
                state = "double_quote"
                can_start_regex = False
                _adv(1)
                continue
            if ch == "`":
                state = "template"
                can_start_regex = False
                _adv(1)
                continue
            if ch == "{":
                if template_brace_stack:
                    template_brace_stack[-1] += 1
                can_start_regex = True
                _adv(1)
                continue
            if ch == "}":
                if template_brace_stack:
                    if template_brace_stack[-1] == 0:
                        template_brace_stack.pop()
                        state = "template"
                        can_start_regex = False
                        _adv(1)
                        continue
                    template_brace_stack[-1] -= 1
                can_start_regex = True
                _adv(1)
                continue
            if ch == SLASH_CHAR:
                if can_start_regex and nxt not in ("\n", "\r", ""):
                    state = "regex"
                else:
                    can_start_regex = True
                _adv(1)
                continue
            if ch.isspace():
                _adv(1)
                continue
            if ch.isalpha() or ch in ("_", "$"):
                start_i = i
                while i < n and (text[i].isalnum() or text[i] in ("_", "$")):
                    _adv(1)
                ident = text[start_i:i]
                can_start_regex = ident in JS_REGEX_KEYWORDS
                continue
            if ch.isdigit():
                while i < n and (text[i].isalnum() or text[i] in (".", "_")):
                    _adv(1)
                can_start_regex = False
                continue
            if ch in ("+", "-") and nxt == ch:
                can_start_regex = False
                _adv(2)
                continue
            if ch in (")", "]"):
                can_start_regex = False
                _adv(1)
                continue
            can_start_regex = True
            _adv(1)
            continue

        if state == "single_quote":
            if ch == "\\":
                _adv(2)
            elif ch in ("'", "\n"):
                state = "code"
                can_start_regex = False
                _adv(1)
            else:
                _adv(1)
            continue

        if state == "double_quote":
            if ch == "\\":
                _adv(2)
            elif ch in ('"', "\n"):
                state = "code"
                can_start_regex = False
                _adv(1)
            else:
                _adv(1)
            continue

        if state == "template":
            if ch == "\\":
                _adv(2)
            elif ch == "$" and nxt == "{":
                template_brace_stack.append(0)
                state = "code"
                can_start_regex = True
                _adv(2)
            elif ch == "`":
                state = "code"
                can_start_regex = False
                _adv(1)
            else:
                _adv(1)
            continue

        if state == "regex":
            if ch == "\\":
                _adv(2)
            elif ch == "[":
                state = "regex_class"
                _adv(1)
            elif ch == SLASH_CHAR:
                state = "code"
                can_start_regex = False
                _adv(1)
            elif ch in ("\n", "\r"):
                state = "code"
                can_start_regex = True
                _adv(1)
            else:
                _adv(1)
            continue

        if state == "regex_class":
            if ch == "\\":
                _adv(2)
            elif ch == "]":
                state = "regex"
                _adv(1)
            elif ch in ("\n", "\r"):
                state = "code"
                can_start_regex = True
                _adv(1)
            else:
                _adv(1)
            continue

    return hits


def _is_scannable_text_file(path: Path) -> bool:
    if not path.is_file():
        return False
    if "__pycache__" in path.parts:
        return False
    if path.name.startswith(".") and path.name == ".DS_Store":
        return False
    if path.suffix.lower() in BINARY_EXTENSIONS:
        return False
    return True


def collect_arena_hygiene_targets(root: Path = ROOT) -> list[Path]:
    root = Path(root).resolve()
    targets: set[Path] = set()

    canary_arena_dir = root / "canary" / "arena"
    if canary_arena_dir.is_dir():
        for p in canary_arena_dir.rglob("*"):
            if _is_scannable_text_file(p):
                targets.add(p.resolve())

    scripts_dir = root / "scripts"
    if scripts_dir.is_dir():
        for p in scripts_dir.glob("*arena*.py"):
            if _is_scannable_text_file(p):
                targets.add(p.resolve())

    tests_dir = root / "tests"
    if tests_dir.is_dir():
        for p in tests_dir.glob("test_*arena*.py"):
            if _is_scannable_text_file(p):
                targets.add(p.resolve())

    docs_arena_dir = root / "docs" / "arena"
    if docs_arena_dir.is_dir():
        for p in docs_arena_dir.rglob("*"):
            if _is_scannable_text_file(p):
                targets.add(p.resolve())

    assets_md = root / "docs" / "demo" / "ASSETS.md"
    if _is_scannable_text_file(assets_md):
        targets.add(assets_md.resolve())

    return sorted(targets)


def scan_file_hygiene(path: Path, rel_label: str | None = None) -> list[str]:
    label = rel_label or str(path)
    try:
        raw_bytes = path.read_bytes()
    except OSError as exc:
        return [f"{label}: unreadable file ({exc})"]
    if b"\x00" in raw_bytes:
        return [f"{label}: unexpected NUL byte in scanned text file"]
    try:
        text = raw_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        return [f"{label}: invalid UTF-8 ({exc})"]

    violations: list[str] = []
    for hit in scan_dashes(text):
        violations.append(f"{label}:{hit['line']}:{hit['col']}: forbidden {hit['kind']}")
    for hit in scan_secrets(text):
        violations.append(
            f"{label}:{hit['line']}:{hit['col']}: forbidden secret pattern {hit['kind']} ({hit['redacted']})"
        )
    suffix = path.suffix.lower()
    if suffix == ".py":
        for hit in scan_python_comments(text):
            violations.append(f"{label}:{hit['line']}:{hit['col']}: forbidden {hit['kind']}")
    elif suffix in JS_EXTENSIONS:
        for hit in scan_js_comments(text):
            violations.append(f"{label}:{hit['line']}:{hit['col']}: forbidden {hit['kind']}")
    return violations


def check_code_hygiene(
    root: Path = ROOT,
    extra_paths: Sequence[Path] | None = None,
) -> CheckResult:
    t0 = time.perf_counter()
    root = Path(root).resolve()
    files = collect_arena_hygiene_targets(root)
    if extra_paths:
        seen = set(files)
        for p in extra_paths:
            rp = Path(p).resolve()
            if _is_scannable_text_file(rp) and rp not in seen:
                files.append(rp)
                seen.add(rp)

    violations: list[str] = []
    if not files:
        violations.append(f"no arena files discovered under {root}")

    scanned_rel: list[str] = []
    for fpath in files:
        try:
            rel = str(fpath.relative_to(root))
        except ValueError:
            rel = str(fpath)
        scanned_rel.append(rel)
        violations.extend(scan_file_hygiene(fpath, rel_label=rel))

    dt = (time.perf_counter() - t0) * 1000.0
    passed = len(violations) == 0
    return CheckResult(
        name="code_hygiene",
        status="PASS" if passed else "FAIL",
        passed=passed,
        required=True,
        duration_ms=dt,
        summary=(
            f"Scanned {len(files)} arena files: 0 comments, 0 em/en dashes, 0 secrets"
            if passed
            else f"{len(violations)} hygiene violations across {len(files)} scanned files"
        ),
        details=violations,
        metrics={"n_files_scanned": len(files), "files": scanned_rel, "n_violations": len(violations)},
    )


def _walk_json(obj: Any, path: str = "$") -> Iterator[tuple[str, str | None, Any]]:
    yield path, None, obj
    if isinstance(obj, dict):
        for k, v in obj.items():
            key_str = str(k)
            child_path = f"{path}.{key_str}"
            yield child_path, key_str, v
            for sub in _walk_json(v, child_path):
                if sub[1] is not None:
                    yield sub
    elif isinstance(obj, list):
        for idx, item in enumerate(obj):
            child_path = f"{path}[{idx}]"
            for sub in _walk_json(item, child_path):
                if sub[1] is not None:
                    yield sub


def inspect_be_the_mole_pre_end_state(state: dict[str, Any]) -> list[str]:
    issues: list[str] = []
    if state.get("done") is not False:
        issues.append(f"expected done=False before episode end, got {state.get('done')!r}")
    if state.get("reveal") is not None:
        issues.append("pre-end state_dict()['reveal'] must be None")
    mv = state.get("mole_view")
    if not isinstance(mv, dict):
        issues.append("state_dict()['mole_view'] missing or not a dict")
    else:
        docs = mv.get("docs")
        if not isinstance(docs, list):
            issues.append("mole_view['docs'] must be a list")
        else:
            for idx, doc in enumerate(docs):
                if not isinstance(doc, dict):
                    issues.append(f"mole_view['docs'][{idx}] is not a dict")
                    continue
                if "is_canary" in doc:
                    issues.append(f"mole_view['docs'][{idx}] leaked 'is_canary'")
                if "variants" in doc:
                    issues.append(f"mole_view['docs'][{idx}] leaked 'variants'")

    for jpath, key_name, _ in _walk_json(state):
        if key_name in FORBIDDEN_BTM_PRE_END_KEYS:
            issues.append(f"forbidden pre-end key {key_name!r} at {jpath}")
    return issues


def inspect_living_office_pre_end_state(
    state: dict[str, Any],
    true_mole: str | None = None,
    decoy: str | None = None,
) -> list[str]:
    issues: list[str] = []
    if state.get("done") is not False:
        issues.append(f"expected done=False before episode end, got {state.get('done')!r}")
    if state.get("verdict") is not None:
        issues.append("pre-end state_dict()['verdict'] must be None")
    if state.get("xray") is not None:
        issues.append("pre-end state_dict()['xray'] must be None")

    fp = state.get("floorplan")
    if not isinstance(fp, dict):
        issues.append("state_dict()['floorplan'] missing or not a dict")
    else:
        emp_entries: list[Any] = []
        if isinstance(fp.get("desks"), list):
            emp_entries.extend(fp["desks"])
        if isinstance(fp.get("employees"), list):
            emp_entries.extend(fp["employees"])
        if not emp_entries:
            issues.append("floorplan contains no employee desks")
        for idx, emp in enumerate(emp_entries):
            if not isinstance(emp, dict):
                issues.append(f"floorplan employee[{idx}] is not a dict")
                continue
            for bad_key in ("is_mole", "is_decoy", "mole", "true_mole", "decoy", "bias", "primary_suspect", "secondary_suspect"):
                if bad_key in emp:
                    issues.append(f"floorplan employee[{idx}] leaked key {bad_key!r}")
            extra_keys = set(emp.keys()) - ALLOWED_FLOORPLAN_EMPLOYEE_KEYS
            for ek in sorted(extra_keys):
                if any(tok in ek.lower() for tok in ("mole", "decoy", "suspect", "secret", "culprit", "bias")):
                    issues.append(f"floorplan employee[{idx}] exposed suspicious key {ek!r}")
            status_val = str(emp.get("status") or "").strip().lower()
            if status_val in FORBIDDEN_FLOORPLAN_STATUSES:
                issues.append(f"floorplan employee[{idx}] leaked status {status_val!r}")
            if true_mole and emp.get("id") == true_mole and emp.get("is_mole") is True:
                issues.append("floorplan exposed true mole via is_mole=True")
            if decoy and emp.get("id") == decoy and emp.get("is_decoy") is True:
                issues.append("floorplan exposed decoy via is_decoy=True")

    issues.extend(inspect_investigator_pre_end_payload(state, true_mole=true_mole))
    return issues


def inspect_investigator_pre_end_payload(
    payload: dict[str, Any],
    true_mole: str | None = None,
) -> list[str]:
    issues: list[str] = []
    for jpath, key_name, val in _walk_json(payload):
        if key_name is None:
            continue
        low_key = key_name.lower()
        if low_key in MUST_BE_NONE_PRE_END_KEYS and val is not None:
            issues.append(f"pre-end key {key_name!r} at {jpath} must be None, got non-null")
        if low_key in FORBIDDEN_INVESTIGATOR_PRE_END_KEYS and val is not None:
            issues.append(f"forbidden pre-end secret key {key_name!r} at {jpath}")
        elif low_key in ("is_mole", "is_decoy", "true_mole", "true_mole_id", "secret_mole", "mole_id"):
            issues.append(f"forbidden pre-end secret key {key_name!r} present at {jpath}")
        if true_mole and low_key not in ALLOWED_PUBLIC_MOLE_CONFIG_KEYS:
            if any(tok in low_key for tok in SUSPICIOUS_MOLE_KEY_TOKENS):
                if val == true_mole or (isinstance(val, str) and true_mole in val):
                    issues.append(f"true_mole {true_mole!r} leaked at {jpath}={val!r}")
    return issues


def check_be_the_mole_engine() -> CheckResult:
    t0 = time.perf_counter()
    failures: list[str] = []

    explicit_bad_seeds: list[Any] = [
        True,
        False,
        0,
        29,
        30,
        2999,
        10000,
        30000,
        800000,
        900000,
    ]
    for bad in explicit_bad_seeds:
        for fn_label, fn in (
            ("check_arena_seed", lambda s=bad: check_arena_seed(s)),
            ("BeTheMoleSession", lambda s=bad: BeTheMoleSession("medium", s)),
        ):
            try:
                fn()
                failures.append(f"{fn_label} accepted forbidden seed {bad!r}")
            except (ValueError, TypeError):
                pass

    for hs in HELDOUT_SEEDS:
        for fn_label, fn in (
            ("check_arena_seed", lambda s=hs: check_arena_seed(s)),
            ("BeTheMoleSession", lambda s=hs: BeTheMoleSession("medium", s)),
        ):
            try:
                fn()
                failures.append(f"{fn_label} accepted HELDOUT_SEED {hs}")
                break
            except ValueError:
                pass
    for js in JUDGE_SEEDS:
        for fn_label, fn in (
            ("check_arena_seed", lambda s=js: check_arena_seed(s)),
            ("BeTheMoleSession", lambda s=js: BeTheMoleSession("medium", s)),
        ):
            try:
                fn()
                failures.append(f"{fn_label} accepted JUDGE_SEED {js}")
                break
            except ValueError:
                pass

    try:
        BeTheMoleSession("easy", 3000)
        failures.append("BeTheMoleSession accepted forbidden tier 'easy'")
    except ValueError:
        pass

    docs_inspected = 0
    sess = BeTheMoleSession("medium", 3000)
    if sess.done:
        failures.append("BeTheMoleSession('medium', 3000) started with done=True")
    else:
        st0 = sess.state_dict()
        docs_inspected += len(st0.get("mole_view", {}).get("docs", []))
        failures.extend(inspect_be_the_mole_pre_end_state(st0))
        try:
            sess.reveal_dict()
            failures.append("BeTheMoleSession.reveal_dict() succeeded before done=True")
        except ArenaRevealError:
            pass
        except Exception as exc:
            failures.append(f"BeTheMoleSession.reveal_dict() raised {type(exc).__name__} instead of ArenaRevealError")

    st1 = sess.step_turn(None, None)
    if not sess.done:
        docs_inspected += len(st1.get("mole_view", {}).get("docs", []))
        failures.extend(inspect_be_the_mole_pre_end_state(st1))
        try:
            sess.reveal_dict()
            failures.append("BeTheMoleSession.reveal_dict() succeeded after step_turn while not done")
        except ArenaRevealError:
            pass
    if docs_inspected == 0:
        failures.append("expected >=1 mole_view doc across Day 1..2 on seed 3000 to verify is_canary/variants stripping")

    final_state = sess.auto_play("frontier_synthesis_v14")
    if not sess.done or final_state.get("done") is not True:
        failures.append("BeTheMoleSession.auto_play('frontier_synthesis_v14') did not reach done=True")
    else:
        rev = sess.reveal_dict()
        if not isinstance(rev.get("true_mole_id"), str) or not rev["true_mole_id"]:
            failures.append("reveal_dict() missing non-empty true_mole_id")
        invs = rev.get("investigators")
        if not isinstance(invs, dict) or set(invs.keys()) != set(INVESTIGATOR_NAMES):
            failures.append(
                f"reveal_dict()['investigators'] keys {list(invs.keys()) if isinstance(invs, dict) else None} != {list(INVESTIGATOR_NAMES)}"
            )
        if not isinstance(rev.get("canary_xray"), list):
            failures.append("reveal_dict()['canary_xray'] missing or not a list")
        if not isinstance(rev.get("badges"), list):
            failures.append("reveal_dict()['badges'] missing or not a list")
        bench = rev.get("strategy_benchmark")
        if not isinstance(bench, dict) or not {"default_v0", "frontier_synthesis_v14", "player"}.issubset(bench.keys()):
            failures.append("reveal_dict()['strategy_benchmark'] missing required benchmark arms")

    dt = (time.perf_counter() - t0) * 1000.0
    passed = len(failures) == 0
    return CheckResult(
        name="be_the_mole",
        status="PASS" if passed else "FAIL",
        passed=passed,
        required=True,
        duration_ms=dt,
        summary="Seed/tier hygiene, pre-end zero-leak, step_turn + auto_play + reveal_dict verified" if passed else "; ".join(failures),
        details=failures,
        metrics={"seed_tested": 3000, "tier": "medium"},
    )


def check_living_office_engine() -> CheckResult:
    t0 = time.perf_counter()
    failures: list[str] = []

    bad_seeds: list[Any] = [
        True,
        False,
        -1,
        0,
        29,
        30,
        2999,
        10000,
        30000,
        HELDOUT_SEEDS[0],
        HELDOUT_SEEDS[-1],
        JUDGE_SEEDS[0],
        JUDGE_SEEDS[-1],
    ]
    for bad in (*bad_seeds, *HELDOUT_SEEDS, *JUDGE_SEEDS):
        try:
            LivingOfficeSession("medium", bad)
            failures.append(f"LivingOfficeSession accepted forbidden seed {bad!r}")
            break
        except (ValueError, TypeError):
            pass

    try:
        LivingOfficeSession("easy", 3001)
        failures.append("LivingOfficeSession accepted forbidden tier 'easy'")
    except ValueError:
        pass

    if GATE_B_METRICS.get("gate_met") is not False:
        failures.append(f"GATE_B_METRICS['gate_met'] must be False, got {GATE_B_METRICS.get('gate_met')!r}")
    if GATE_B_METRICS.get("n_paired") != 3:
        failures.append(f"GATE_B_METRICS['n_paired'] must be 3, got {GATE_B_METRICS.get('n_paired')!r}")
    if not math.isclose(float(GATE_B_METRICS.get("variant_luck_adjusted_mean", -1.0)), 0.452, abs_tol=1e-9):
        failures.append(
            f"GATE_B_METRICS['variant_luck_adjusted_mean'] must be 0.452, got {GATE_B_METRICS.get('variant_luck_adjusted_mean')!r}"
        )
    if not math.isclose(float(GATE_B_METRICS.get("control_luck_adjusted_mean", -1.0)), 0.493, abs_tol=1e-9):
        failures.append(
            f"GATE_B_METRICS['control_luck_adjusted_mean'] must be 0.493, got {GATE_B_METRICS.get('control_luck_adjusted_mean')!r}"
        )

    sess = LivingOfficeSession("medium", 3001, "v5_full9_cocktail", "frontier_synthesis_v14")
    twin = LivingOfficeSession("medium", 3001, "v5_full9_cocktail", "frontier_synthesis_v14")
    true_mole = str(sess.env._world.mole)
    decoy_id = sess.env._world.decoy
    alt_mole = next(eid for eid in twin.env._ids if eid != true_mole and eid != decoy_id)
    twin.env._world.mole = alt_mole

    st0 = sess.state_dict()
    if st0 != twin.state_dict():
        failures.append("LivingOfficeSession Day 1 state_dict() differs when hidden _world.mole is swapped")
    failures.extend(inspect_living_office_pre_end_state(st0, true_mole=true_mole, decoy=decoy_id))

    try:
        sess.bias_xray_dict()
        failures.append("LivingOfficeSession.bias_xray_dict() succeeded before done=True")
    except ValueError:
        pass

    for auto_pol in ("gemini_proxy", "solver"):
        if sess.done:
            break
        stepped = sess.step_auto_investigator(auto_pol)
        if not sess.done:
            st_mid = stepped.get("state") if isinstance(stepped.get("state"), dict) else sess.state_dict()
            failures.extend(inspect_living_office_pre_end_state(st_mid, true_mole=true_mole, decoy=decoy_id))
            try:
                sess.bias_xray_dict()
                failures.append("LivingOfficeSession.bias_xray_dict() succeeded mid-episode before done=True")
                break
            except ValueError:
                pass

    if not sess.done:
        sess.call_tool("accuse", {"employee": true_mole})

    if not sess.done:
        failures.append("LivingOfficeSession did not reach done=True after auto-investigator steps and accuse")
    else:
        xray = sess.bias_xray_dict()
        if not isinstance(xray, dict) or "biases" not in xray or xray.get("true_mole") != true_mole:
            failures.append("LivingOfficeSession.bias_xray_dict() returned incomplete X-Ray payload after done")
        done_state = sess.state_dict()
        if done_state.get("verdict") is None or done_state.get("xray") is None:
            failures.append("LivingOfficeSession post-done state_dict() did not unlock verdict and xray")

    ckpt_list = list_v16_checkpoint_replays()
    if not isinstance(ckpt_list, list) or len(ckpt_list) == 0:
        failures.append("list_v16_checkpoint_replays() returned empty list")
    rep = load_v16_checkpoint_replay("v5_full9_cocktail", 30)
    if rep.get("provenance_badge") != "v16-real-gemini-replay":
        failures.append(
            f"load_v16_checkpoint_replay('v5_full9_cocktail', 30) badge={rep.get('provenance_badge')!r} != 'v16-real-gemini-replay'"
        )
    if rep.get("replay_verified") is not True:
        failures.append("load_v16_checkpoint_replay('v5_full9_cocktail', 30) replay_verified != True")

    dt = (time.perf_counter() - t0) * 1000.0
    passed = len(failures) == 0
    return CheckResult(
        name="living_office",
        status="PASS" if passed else "FAIL",
        passed=passed,
        required=True,
        duration_ms=dt,
        summary=(
            f"Seed hygiene, Gate B disclosure, pre-end zero-leak, solver unlock, and {len(ckpt_list)} checkpoint replays verified"
            if passed
            else "; ".join(failures)
        ),
        details=failures,
        metrics={"seed_tested": 3001, "checkpoint_replays": len(ckpt_list)},
    )


def _load_module_from_file(mod_name: str, file_path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(mod_name, file_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot create spec for {file_path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = mod
    spec.loader.exec_module(mod)
    return mod


def _resolve_optional_module(
    dotted_name: str,
    rel_file: Path,
    root: Path = ROOT,
    module_override: Any | None = None,
) -> tuple[Any | None, str | None]:
    if module_override is not None:
        return module_override, None
    root = Path(root).resolve()
    target_file = root / rel_file
    if root != ROOT:
        if not target_file.is_file():
            return None, None
        try:
            return _load_module_from_file(f"_arena_opt_{dotted_name.replace('.', '_')}_{abs(hash(target_file))}", target_file), None
        except Exception as exc:
            return None, f"failed importing {target_file}: {exc}"
    if not target_file.is_file():
        try:
            return importlib.import_module(dotted_name), None
        except ModuleNotFoundError as exc:
            if exc.name == dotted_name or dotted_name.startswith(str(exc.name or "")):
                return None, None
            return None, f"dependency import error in {dotted_name}: {exc}"
        except Exception as exc:
            return None, f"error importing {dotted_name}: {exc}"
    try:
        return importlib.import_module(dotted_name), None
    except Exception as exc:
        return None, f"error importing {dotted_name}: {exc}"


def _instantiate_head_to_head_session(mod: Any, tier: str, seed: Any) -> Any:
    candidates: list[Any] = []
    for attr in ("HeadToHeadSession", "create_session", "HeadToHeadMatch", "HeadToHeadGame"):
        obj = getattr(mod, attr, None)
        if callable(obj):
            candidates.append(obj)
    if not candidates:
        for _, obj in inspect.getmembers(mod, inspect.isclass):
            if obj.__module__ == mod.__name__ and hasattr(obj, "state_dict"):
                candidates.append(obj)
    if not candidates:
        raise AttributeError("canary.arena.head_to_head has no HeadToHeadSession or session factory")

    factory = candidates[0]
    sig = inspect.signature(factory)
    params = list(sig.parameters.values())
    kwargs: dict[str, Any] = {}
    if "tier" in sig.parameters:
        kwargs["tier"] = tier
    if "seed" in sig.parameters:
        kwargs["seed"] = seed
    if kwargs:
        return factory(**kwargs)
    if len(params) >= 2:
        return factory(tier, seed)
    return factory(seed)


def _extract_true_mole_from_session(sess: Any, tier: str, seed: int) -> str:
    for attr in ("env", "_env", "human_env", "_human_env", "player_env"):
        env_obj = getattr(sess, attr, None)
        world = getattr(env_obj, "_world", None)
        if world is not None and isinstance(getattr(world, "mole", None), str):
            return str(world.mole)
    return str(Env(tier, seed)._world.mole)


def _invoke_load_ghost_replay(load_fn: Callable[..., Any], sample_entry: Any) -> Any:
    if isinstance(sample_entry, str):
        return load_fn(sample_entry)
    if isinstance(sample_entry, dict):
        sig = inspect.signature(load_fn)
        params = list(sig.parameters.values())
        if len(params) == 1 and params[0].name in ("replay_id", "id", "ghost_id", "key", "slug"):
            for k in (params[0].name, "id", "replay_id", "ghost_id", "key", "slug"):
                if k in sample_entry:
                    return load_fn(sample_entry[k])
        kw: dict[str, Any] = {}
        for p in params:
            if p.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD):
                continue
            if p.name in sample_entry:
                kw[p.name] = sample_entry[p.name]
            elif p.name in ("replay_id", "ghost_id") and "id" in sample_entry:
                kw[p.name] = sample_entry["id"]
            elif p.name == "id" and "replay_id" in sample_entry:
                kw[p.name] = sample_entry["replay_id"]
        if kw:
            return load_fn(**kw)
        for fallback_key in ("id", "replay_id", "ghost_id"):
            if fallback_key in sample_entry:
                return load_fn(sample_entry[fallback_key])
    return load_fn()


def check_head_to_head(
    root: Path = ROOT,
    require_present: bool = False,
    module_override: Any | None = None,
) -> CheckResult:
    t0 = time.perf_counter()
    mod, err = _resolve_optional_module(
        "canary.arena.head_to_head",
        Path("canary") / "arena" / "head_to_head.py",
        root=root,
        module_override=module_override,
    )
    if err is not None:
        dt = (time.perf_counter() - t0) * 1000.0
        return CheckResult(
            name="head_to_head",
            status="FAIL",
            passed=False,
            required=require_present,
            duration_ms=dt,
            summary=err,
            details=[err],
        )
    if mod is None:
        dt = (time.perf_counter() - t0) * 1000.0
        if require_present:
            msg = "canary.arena.head_to_head is absent (--require-all enabled)"
            return CheckResult(
                name="head_to_head",
                status="FAIL",
                passed=False,
                required=True,
                duration_ms=dt,
                summary=msg,
                details=[msg],
            )
        return CheckResult(
            name="head_to_head",
            status="SKIP",
            passed=True,
            required=False,
            duration_ms=dt,
            summary="canary.arena.head_to_head not present yet (optional sibling module)",
        )

    failures: list[str] = []
    seed_guard = (
        getattr(mod, "check_arena_seed", None)
        or getattr(mod, "check_live_seed", None)
        or getattr(mod, "check_public_dev_seed", None)
        or getattr(mod, "check_seed", None)
        or getattr(mod, "validate_live_seed", None)
    )
    bad_seeds: list[Any] = [True, False, 0, 29, 30, 2999, 10000, 30000, HELDOUT_SEEDS[0], JUDGE_SEEDS[0]]
    for bad in bad_seeds:
        if callable(seed_guard):
            try:
                seed_guard(bad)
                failures.append(f"head_to_head seed guard accepted {bad!r}")
            except (ValueError, TypeError):
                pass
        try:
            _instantiate_head_to_head_session(mod, "medium", bad)
            failures.append(f"HeadToHeadSession accepted forbidden seed {bad!r}")
        except (ValueError, TypeError):
            pass
        except Exception as exc:
            failures.append(f"HeadToHeadSession raised unexpected {type(exc).__name__} on bad seed {bad!r}: {exc}")

    try:
        sess = _instantiate_head_to_head_session(mod, "medium", 3002)
        if getattr(sess, "done", False) is not False:
            failures.append("HeadToHeadSession('medium', 3002) started with done != False")
        st = sess.state_dict()
        true_mole = _extract_true_mole_from_session(sess, "medium", 3002)
        failures.extend(inspect_investigator_pre_end_payload(st, true_mole=true_mole))
        reveal_meth = getattr(sess, "reveal_dict", None)
        if callable(reveal_meth):
            try:
                reveal_meth()
                failures.append("HeadToHeadSession.reveal_dict() succeeded before done=True")
            except ValueError:
                pass
    except Exception as exc:
        failures.append(f"HeadToHeadSession pre-end check failed: {exc}")

    list_fn = getattr(mod, "list_ghost_replays", None)
    load_fn = getattr(mod, "load_ghost_replay", None)
    ghost_count = 0
    if not callable(list_fn) or not callable(load_fn):
        failures.append("head_to_head missing list_ghost_replays() or load_ghost_replay()")
    else:
        try:
            ghosts = list_fn()
            if not isinstance(ghosts, list) or len(ghosts) == 0:
                failures.append("list_ghost_replays() returned empty or non-list")
            else:
                ghost_count = len(ghosts)
                loaded = _invoke_load_ghost_replay(load_fn, ghosts[0])
                if not isinstance(loaded, dict) or not loaded:
                    failures.append("load_ghost_replay(...) did not return a non-empty dict")
        except Exception as exc:
            failures.append(f"ghost replay check failed offline: {exc}")

    dt = (time.perf_counter() - t0) * 1000.0
    passed = len(failures) == 0
    return CheckResult(
        name="head_to_head",
        status="PASS" if passed else "FAIL",
        passed=passed,
        required=require_present,
        duration_ms=dt,
        summary=(
            f"Live seed guard, pre-end zero-leak, and {ghost_count} offline ghost replays verified"
            if passed
            else "; ".join(failures)
        ),
        details=failures,
        metrics={"ghost_replays": ghost_count},
    )


class _QuietWSGIHandler(WSGIRequestHandler):
    def log_message(self, format: str, *args: Any) -> None:
        return


def _wrap_dispatch_app_as_server(app: Any) -> ThreadingHTTPServer:
    dispatch_fn = None
    for name in ("handle_request", "dispatch", "handle", "route"):
        cand = getattr(app, name, None)
        if callable(cand):
            dispatch_fn = cand
            break
    if dispatch_fn is None:
        raise TypeError("ArenaApp is neither WSGI callable nor exposes handle_request/dispatch")

    class _AdapterHandler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:
            return

        def _run(self, method: str) -> None:
            length = int(self.headers.get("Content-Length") or 0)
            raw_body = self.rfile.read(length) if length > 0 else b""
            parsed = urllib.parse.urlsplit(self.path)
            query_params = dict(urllib.parse.parse_qsl(parsed.query, keep_blank_values=True))
            body_obj: Any = None
            if raw_body:
                body_obj = json.loads(raw_body.decode("utf-8"))
            sig = inspect.signature(dispatch_fn)
            n_params = len(sig.parameters)
            if n_params == 2:
                out = dispatch_fn(method, self.path)
            elif n_params == 3:
                out = dispatch_fn(method, self.path, body_obj if method == "POST" else query_params)
            else:
                out = dispatch_fn(method, parsed.path, query_params, body_obj)

            status = 200
            ctype = "application/json; charset=utf-8"
            payload_bytes = b"{}"
            if isinstance(out, tuple):
                status = int(out[0])
                if len(out) == 3:
                    headers_or_ct = out[1]
                    body_val = out[2]
                    if isinstance(headers_or_ct, str):
                        ctype = headers_or_ct
                    elif isinstance(headers_or_ct, dict):
                        ctype = str(headers_or_ct.get("Content-Type") or ctype)
                else:
                    body_val = out[1]
                if isinstance(body_val, bytes):
                    payload_bytes = body_val
                elif isinstance(body_val, str):
                    if body_val.lstrip().startswith("<"):
                        ctype = "text/html; charset=utf-8"
                    payload_bytes = body_val.encode("utf-8")
                else:
                    payload_bytes = json.dumps(body_val).encode("utf-8")
            elif isinstance(out, str):
                ctype = "text/html; charset=utf-8"
                payload_bytes = out.encode("utf-8")
            else:
                payload_bytes = json.dumps(out).encode("utf-8")

            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(payload_bytes)))
            self.end_headers()
            self.wfile.write(payload_bytes)

        def do_GET(self) -> None:
            self._run("GET")

        def do_POST(self) -> None:
            self._run("POST")

    return ThreadingHTTPServer(("127.0.0.1", 0), _AdapterHandler)


@contextmanager
def _bind_ephemeral_arena_server(mod: Any) -> Iterator[str]:
    httpd: Any = None
    for factory_name in ("create_server", "make_server", "build_server", "create_http_server"):
        fn = getattr(mod, factory_name, None)
        if callable(fn):
            sig = inspect.signature(fn)
            if "host" in sig.parameters and "port" in sig.parameters:
                httpd = fn(host="127.0.0.1", port=0)
            elif len(sig.parameters) >= 2:
                httpd = fn("127.0.0.1", 0)
            else:
                httpd = fn()
            break

    if httpd is None:
        app_cls = getattr(mod, "ArenaApp", None)
        if app_cls is not None:
            app = app_cls() if inspect.isclass(app_cls) else app_cls
            for meth_name in ("create_server", "make_server", "build_server"):
                meth = getattr(app, meth_name, None)
                if callable(meth):
                    httpd = meth("127.0.0.1", 0)
                    break
            if httpd is None:
                handler_factory = getattr(app, "make_handler", None) or getattr(mod, "make_handler", None)
                if callable(handler_factory):
                    sig = inspect.signature(handler_factory)
                    handler_cls = handler_factory(app) if len(sig.parameters) >= 1 else handler_factory()
                    httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler_cls)
            if httpd is None and callable(app):
                httpd = make_wsgi_server("127.0.0.1", 0, app, handler_class=_QuietWSGIHandler)
            if httpd is None:
                httpd = _wrap_dispatch_app_as_server(app)

    if httpd is None:
        handler_cls = getattr(mod, "ArenaRequestHandler", None) or getattr(mod, "ArenaHandler", None)
        if handler_cls is not None:
            httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler_cls)

    if httpd is None:
        raise AttributeError("canary.arena.server has no create_server/make_server/ArenaApp/ArenaRequestHandler")

    addr = httpd.server_address
    port = int(addr[1])
    base_url = f"http://127.0.0.1:{port}"
    thread = threading.Thread(target=httpd.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True)
    thread.start()
    try:
        yield base_url
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=3.0)


def _http_request(
    base_url: str,
    method: str,
    path: str,
    payload: dict[str, Any] | None = None,
    timeout: float = 10.0,
) -> tuple[int, str, dict[str, str]]:
    url = base_url + path
    data_bytes = None
    headers: dict[str, str] = {}
    if payload is not None:
        data_bytes = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data_bytes, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            status = int(resp.status)
            body = resp.read().decode("utf-8")
            resp_headers = {k.lower(): v for k, v in resp.headers.items()}
            return status, body, resp_headers
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        resp_headers = {k.lower(): v for k, v in exc.headers.items()} if exc.headers else {}
        return int(exc.code), body, resp_headers


def _extract_session_id(payload: dict[str, Any]) -> str | None:
    for key in ("session_id", "id"):
        val = payload.get(key)
        if isinstance(val, str) and val:
            return val
    for nested_key in ("state", "data", "session"):
        sub = payload.get(nested_key)
        if isinstance(sub, dict):
            for key in ("session_id", "id"):
                val = sub.get(key)
                if isinstance(val, str) and val:
                    return val
    return None


def check_arena_server(
    root: Path = ROOT,
    require_present: bool = False,
    module_override: Any | None = None,
) -> CheckResult:
    t0 = time.perf_counter()
    mod, err = _resolve_optional_module(
        "canary.arena.server",
        Path("canary") / "arena" / "server.py",
        root=root,
        module_override=module_override,
    )
    if err is not None:
        dt = (time.perf_counter() - t0) * 1000.0
        return CheckResult(
            name="arena_server",
            status="FAIL",
            passed=False,
            required=require_present,
            duration_ms=dt,
            summary=err,
            details=[err],
        )
    if mod is None:
        dt = (time.perf_counter() - t0) * 1000.0
        if require_present:
            msg = "canary.arena.server is absent (--require-all enabled)"
            return CheckResult(
                name="arena_server",
                status="FAIL",
                passed=False,
                required=True,
                duration_ms=dt,
                summary=msg,
                details=[msg],
            )
        return CheckResult(
            name="arena_server",
            status="SKIP",
            passed=True,
            required=False,
            duration_ms=dt,
            summary="canary.arena.server not present yet (optional sibling module)",
        )

    failures: list[str] = []
    routes_checked = 0
    try:
        with _bind_ephemeral_arena_server(mod) as base_url:
            st_root, body_root, _ = _http_request(base_url, "GET", "/")
            routes_checked += 1
            if st_root != 200 or "<html" not in body_root.lower():
                failures.append(f"GET / expected 200 HTML, got status={st_root}")

            st_health, body_health, _ = _http_request(base_url, "GET", "/api/health")
            routes_checked += 1
            if st_health != 200:
                failures.append(f"GET /api/health expected 200, got {st_health}")
            else:
                health_json = json.loads(body_health)
                if not isinstance(health_json, dict):
                    failures.append("GET /api/health did not return JSON object")

            st_cat, body_cat, _ = _http_request(base_url, "GET", "/api/catalog")
            routes_checked += 1
            if st_cat != 200:
                failures.append(f"GET /api/catalog expected 200, got {st_cat}")
            else:
                cat_json = json.loads(body_cat)
                if not isinstance(cat_json, dict):
                    failures.append("GET /api/catalog did not return JSON object")

            st_rep, body_rep, _ = _http_request(
                base_url,
                "GET",
                "/api/living_office/replay?variant=v5_full9_cocktail&seed=30",
            )
            routes_checked += 1
            if st_rep != 200:
                failures.append(f"GET /api/living_office/replay expected 200, got {st_rep}")
            else:
                rep_json = json.loads(body_rep)
                if "v16-real-gemini-replay" not in json.dumps(rep_json):
                    failures.append("GET /api/living_office/replay missing v16-real-gemini-replay provenance badge")

            st_btm, body_btm, _ = _http_request(
                base_url,
                "POST",
                "/api/be_the_mole/start",
                {"tier": "medium", "seed": 3000},
            )
            routes_checked += 1
            btm_sid: str | None = None
            if st_btm != 200:
                failures.append(f"POST /api/be_the_mole/start expected 200, got {st_btm}")
            else:
                btm_json = json.loads(body_btm)
                btm_sid = _extract_session_id(btm_json)
                btm_state = btm_json.get("state") if isinstance(btm_json.get("state"), dict) else btm_json
                if isinstance(btm_state, dict) and "mole_view" in btm_state:
                    failures.extend(inspect_be_the_mole_pre_end_state(btm_state))

            autoplay_req: dict[str, Any] = {
                "strategy": "frontier_synthesis_v14",
                "strategy_name": "frontier_synthesis_v14",
            }
            if btm_sid:
                autoplay_req["session_id"] = btm_sid
            st_auto, body_auto, _ = _http_request(base_url, "POST", "/api/be_the_mole/autoplay", autoplay_req)
            routes_checked += 1
            if st_auto != 200:
                failures.append(f"POST /api/be_the_mole/autoplay expected 200, got {st_auto}")
            else:
                auto_json = json.loads(body_auto)
                auto_state = auto_json.get("state") if isinstance(auto_json.get("state"), dict) else auto_json
                if not (auto_json.get("done") is True or (isinstance(auto_state, dict) and auto_state.get("done") is True)):
                    failures.append("POST /api/be_the_mole/autoplay did not reach done=True")

            true_mole_3001 = str(Env("medium", 3001)._world.mole)
            st_lo, body_lo, _ = _http_request(
                base_url,
                "POST",
                "/api/living_office/start",
                {
                    "tier": "medium",
                    "seed": 3001,
                    "variant": "v5_full9_cocktail",
                    "mole_opponent": "frontier_synthesis_v14",
                },
            )
            routes_checked += 1
            lo_sid: str | None = None
            if st_lo != 200:
                failures.append(f"POST /api/living_office/start expected 200, got {st_lo}")
            else:
                lo_json = json.loads(body_lo)
                lo_sid = _extract_session_id(lo_json)
                failures.extend(inspect_investigator_pre_end_payload(lo_json, true_mole=true_mole_3001))

            step_payloads: list[dict[str, Any]] = [
                {**({"session_id": lo_sid} if lo_sid else {}), "policy": "solver", "policy_name": "solver"},
                {**({"session_id": lo_sid} if lo_sid else {}), "tool": "list_employees", "args": {}},
            ]
            step_ok = False
            last_step_status = 0
            for sp in step_payloads:
                st_step, body_step, _ = _http_request(base_url, "POST", "/api/living_office/step", sp)
                last_step_status = st_step
                if st_step == 200:
                    step_json = json.loads(body_step)
                    step_state = step_json.get("state") if isinstance(step_json.get("state"), dict) else step_json
                    step_done = bool(step_json.get("done")) or (
                        isinstance(step_state, dict) and bool(step_state.get("done"))
                    )
                    if not step_done:
                        failures.extend(inspect_investigator_pre_end_payload(step_json, true_mole=true_mole_3001))
                    step_ok = True
                    break
            routes_checked += 1
            if not step_ok:
                failures.append(f"POST /api/living_office/step expected 200, got {last_step_status}")

            for bad_seed in (0, 30000):
                for start_route in ("/api/be_the_mole/start", "/api/living_office/start"):
                    st_bad, body_bad, _ = _http_request(
                        base_url,
                        "POST",
                        start_route,
                        {"tier": "medium", "seed": bad_seed},
                    )
                    routes_checked += 1
                    if st_bad != 400:
                        failures.append(f"POST {start_route} with seed={bad_seed} expected HTTP 400, got {st_bad}")
                    else:
                        low_body = body_bad.lower()
                        if "seedhygieneerror" not in low_body and "seed" not in low_body and "error" not in low_body:
                            failures.append(
                                f"POST {start_route} seed={bad_seed} HTTP 400 body missing SeedHygieneError/seed message"
                            )

            true_mole_3002 = str(Env("medium", 3002)._world.mole)
            st_h2h, body_h2h, _ = _http_request(
                base_url,
                "POST",
                "/api/head_to_head/start",
                {"tier": "medium", "seed": 3002},
            )
            routes_checked += 1
            if st_h2h == 200:
                h2h_json = json.loads(body_h2h)
                failures.extend(inspect_investigator_pre_end_payload(h2h_json, true_mole=true_mole_3002))
                for bad_seed in (0, 30000):
                    st_h2h_bad, _, _ = _http_request(
                        base_url,
                        "POST",
                        "/api/head_to_head/start",
                        {"tier": "medium", "seed": bad_seed},
                    )
                    if st_h2h_bad != 400:
                        failures.append(
                            f"POST /api/head_to_head/start with seed={bad_seed} expected HTTP 400, got {st_h2h_bad}"
                        )
            elif st_h2h in (404, 501) and not require_present:
                pass
            else:
                failures.append(f"POST /api/head_to_head/start expected 200, got {st_h2h}")
    except Exception as exc:
        failures.append(f"ephemeral server verification failed: {exc}")

    dt = (time.perf_counter() - t0) * 1000.0
    passed = len(failures) == 0
    return CheckResult(
        name="arena_server",
        status="PASS" if passed else "FAIL",
        passed=passed,
        required=require_present,
        duration_ms=dt,
        summary=(
            f"Bound ephemeral 127.0.0.1:0 and verified {routes_checked} HTTP route checks, 400 seed guard, and zero pre-end leak"
            if passed
            else "; ".join(failures)
        ),
        details=failures,
        metrics={"routes_checked": routes_checked},
    )


def _invoke_get_mole_briefing(fn: Callable[..., Any]) -> Any:
    sig = inspect.signature(fn)
    pos_args: list[Any] = []
    kw_args: dict[str, Any] = {}
    defaults_by_name: dict[str, Any] = {
        "tier": "hard",
        "seed": 3000,
    }
    for p in sig.parameters.values():
        if p.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD):
            continue
        if p.name in defaults_by_name and (p.name == "tier" or p.default is inspect.Parameter.empty):
            val = defaults_by_name[p.name]
            if p.kind == inspect.Parameter.POSITIONAL_ONLY:
                pos_args.append(val)
            else:
                kw_args[p.name] = val
    return fn(*pos_args, **kw_args)


def _invoke_compare_human_mole(fn: Callable[..., Any]) -> Any:
    sample_turns = [
        {
            "day": 1,
            "can_leak": True,
            "leaked_doc_id": "d1",
            "framed_peer_id": "e02",
            "leak_selector": "most_recipients",
            "frame_selector": "random_peer",
        }
    ]
    sample_summary: dict[str, Any] = {
        "tier": "hard",
        "seed": 3000,
        "done": True,
        "true_mole_id": "e01",
        "player_mole_id": "e01",
        "score": 0.25,
        "human_score": 0.25,
        "gemini_score": 0.0,
        "solver_score": 0.75,
        "correct": False,
        "caught_by_gemini": False,
        "caught_by_solver": True,
        "final_day": 21,
        "days_survived": 21,
        "total_leaks": 5,
        "canary_leaks_hit": 0,
        "regular_leaks_hit": 5,
        "frames_planted": 6,
        "true_v_remaining": 0.75,
        "badges": ["FOOLED_GEMINI_FAIR_TO_SOLVER", "OUTLASTED_GEMINI", "ZERO_CANARY_HITS"],
        "turn_log": sample_turns,
        "investigators": {
            "gemini_proxy": {"score": 0.0, "correct": False, "accused": None, "final_day": 21},
            "solver": {"score": 0.75, "correct": True, "accused": "e01", "final_day": 9},
            "hinted_heuristic": {"score": 0.0, "correct": False, "accused": None, "final_day": 21},
        },
        "mole_summary": {
            "total_leaks": 5,
            "canary_leaks_hit": 0,
            "regular_leaks_hit": 5,
            "frames_planted": 6,
            "true_v_remaining": 0.75,
        },
        "strategy_benchmark": {
            "default_v0": {
                "gemini_proxy": {"score": 0.55, "correct": True, "accused": "e01", "final_day": 11},
                "solver": {"score": 0.78, "correct": True, "accused": "e01", "final_day": 8},
                "gap": 0.23,
            },
            "frontier_synthesis_v14": {
                "gemini_proxy": {"score": 0.0, "correct": False, "accused": None, "final_day": 21},
                "solver": {"score": 0.74, "correct": True, "accused": "e01", "final_day": 9},
                "gap": 0.74,
            },
            "player": {
                "gemini_proxy": {"score": 0.0, "correct": False, "accused": None, "final_day": 21},
                "solver": {"score": 0.75, "correct": True, "accused": "e01", "final_day": 9},
                "gap": 0.75,
            },
        },
    }
    by_param_name: dict[str, Any] = {
        "tier": "hard",
        "seed": 3000,
        "score": 0.25,
        "human_score": 0.25,
        "player_score": 0.25,
        "gemini_score": 0.0,
        "investigator_score": 0.0,
        "solver_score": 0.75,
        "correct": False,
        "caught": False,
        "fooled_gemini": True,
        "caught_by_gemini": False,
        "caught_by_solver": True,
        "final_day": 21,
        "days_survived": 21,
        "day": 21,
        "total_leaks": 5,
        "leaks": 5,
        "n_leaks": 5,
        "canary_hits": 0,
        "canary_leaks_hit": 0,
        "frames": 6,
        "frames_planted": 6,
        "true_v": 0.75,
        "true_v_remaining": 0.75,
        "v_remaining": 0.75,
        "strategy": "frontier_synthesis_v14",
        "strategy_name": "frontier_synthesis_v14",
        "rival": "frontier_synthesis_v14",
        "human": sample_summary,
        "human_run": sample_summary,
        "human_result": sample_summary,
        "human_summary": sample_summary,
        "human_mole_summary": sample_summary,
        "human_mole": sample_summary,
        "reveal": sample_summary,
        "episode": sample_summary,
        "result": sample_summary,
        "run": sample_summary,
        "stats": sample_summary,
        "metrics": sample_summary,
        "turn_log": sample_turns,
        "decisions": sample_turns,
        "moves": sample_turns,
        "actions": sample_turns,
    }

    sig = inspect.signature(fn)
    pos_args: list[Any] = []
    kw_args: dict[str, Any] = {}
    for p in sig.parameters.values():
        if p.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD):
            continue
        if p.name in by_param_name:
            val = by_param_name[p.name]
            if p.kind == inspect.Parameter.POSITIONAL_ONLY:
                pos_args.append(val)
            else:
                kw_args[p.name] = val
        elif p.default is inspect.Parameter.empty:
            fallback_val: Any = sample_summary
            if p.kind == inspect.Parameter.POSITIONAL_ONLY:
                pos_args.append(fallback_val)
            else:
                kw_args[p.name] = fallback_val
    return fn(*pos_args, **kw_args)


def check_mole_rivals(
    root: Path = ROOT,
    require_present: bool = False,
    module_override: Any | None = None,
    max_warm_ms: float = 80.0,
) -> CheckResult:
    t0 = time.perf_counter()
    root = Path(root).resolve()
    rivals_path = root / "docs" / "arena" / "mole_rivals.py"
    mod: Any = module_override
    if mod is None:
        if not rivals_path.is_file():
            dt = (time.perf_counter() - t0) * 1000.0
            if require_present:
                msg = "docs/arena/mole_rivals.py is absent (--require-all enabled)"
                return CheckResult(
                    name="mole_rivals",
                    status="FAIL",
                    passed=False,
                    required=True,
                    duration_ms=dt,
                    summary=msg,
                    details=[msg],
                )
            return CheckResult(
                name="mole_rivals",
                status="SKIP",
                passed=True,
                required=False,
                duration_ms=dt,
                summary="docs/arena/mole_rivals.py not present yet (optional sibling module)",
            )
        try:
            mod = _load_module_from_file(f"_docs_arena_mole_rivals_{abs(hash(rivals_path))}", rivals_path)
        except Exception as exc:
            dt = (time.perf_counter() - t0) * 1000.0
            msg = f"failed loading {rivals_path}: {exc}"
            return CheckResult(
                name="mole_rivals",
                status="FAIL",
                passed=False,
                required=require_present,
                duration_ms=dt,
                summary=msg,
                details=[msg],
            )

    failures: list[str] = []
    warm_ms = 0.0
    briefing_fn = getattr(mod, "get_mole_briefing", None)
    compare_fn = getattr(mod, "compare_human_mole", None)
    if not callable(briefing_fn) or not callable(compare_fn):
        failures.append("docs/arena/mole_rivals.py missing get_mole_briefing or compare_human_mole")
    else:
        try:
            _invoke_get_mole_briefing(briefing_fn)
            _invoke_compare_human_mole(compare_fn)

            tw0 = time.perf_counter()
            brief = _invoke_get_mole_briefing(briefing_fn)
            comp = _invoke_compare_human_mole(compare_fn)
            warm_ms = (time.perf_counter() - tw0) * 1000.0

            if not isinstance(brief, dict) or not brief:
                failures.append("get_mole_briefing('hard') did not return a non-empty dict")
            if not isinstance(comp, dict) or not comp:
                failures.append("compare_human_mole(...) did not return a non-empty dict")
            if warm_ms >= max_warm_ms:
                failures.append(f"mole_rivals warm execution took {warm_ms:.2f} ms >= {max_warm_ms:.1f} ms")
        except Exception as exc:
            failures.append(f"mole_rivals execution failed: {exc}")

    dt = (time.perf_counter() - t0) * 1000.0
    passed = len(failures) == 0
    return CheckResult(
        name="mole_rivals",
        status="PASS" if passed else "FAIL",
        passed=passed,
        required=require_present,
        duration_ms=dt,
        summary=(
            f"get_mole_briefing('hard') + compare_human_mole(...) ran keyless in {warm_ms:.2f} ms warm (< {max_warm_ms:.0f} ms)"
            if passed
            else "; ".join(failures)
        ),
        details=failures,
        metrics={"warm_ms": round(warm_ms, 3), "max_warm_ms": max_warm_ms},
    )


def run_all_checks(
    *,
    root: Path = ROOT,
    base_ref: str = DEFAULT_BASE_REF,
    require_all: bool = False,
    head_to_head_module: Any | None = None,
    server_module: Any | None = None,
    mole_rivals_module: Any | None = None,
) -> dict[str, Any]:
    t_start = time.perf_counter()
    results: list[CheckResult] = []

    with offline_arena_guard() as outer_telemetry:
        results.append(check_offline_guard_contract())
        results.append(check_protected_paths(root=root, base_ref=base_ref))
        results.append(check_code_hygiene(root=root))
        results.append(check_be_the_mole_engine())
        results.append(check_living_office_engine())
        results.append(
            check_head_to_head(
                root=root,
                require_present=require_all,
                module_override=head_to_head_module,
            )
        )
        results.append(
            check_arena_server(
                root=root,
                require_present=require_all,
                module_override=server_module,
            )
        )
        results.append(
            check_mole_rivals(
                root=root,
                require_present=require_all,
                module_override=mole_rivals_module,
            )
        )

        zero_live_ok = (
            outer_telemetry["live_api_calls"] == 0
            and outer_telemetry["blocked_llm_calls"] == 0
            and outer_telemetry["blocked_network_calls"] == 0
        )
        live_details: list[str] = []
        if not zero_live_ok:
            live_details.append(f"unexpected live/blocked calls during arena verification: {outer_telemetry}")
        results.append(
            CheckResult(
                name="zero_live_api_calls",
                status="PASS" if zero_live_ok else "FAIL",
                passed=zero_live_ok,
                required=True,
                duration_ms=0.0,
                summary="0 live LLM/network calls across all Arena checks" if zero_live_ok else "; ".join(live_details),
                details=live_details,
                metrics=dict(outer_telemetry),
            )
        )

    total_ms = (time.perf_counter() - t_start) * 1000.0
    n_pass = sum(1 for r in results if r.status == "PASS")
    n_skip = sum(1 for r in results if r.status == "SKIP")
    n_fail = sum(1 for r in results if not r.passed)
    overall_passed = n_fail == 0

    return {
        "passed": overall_passed,
        "require_all": require_all,
        "total_duration_ms": round(total_ms, 3),
        "n_checks": len(results),
        "n_passed": n_pass,
        "n_skipped": n_skip,
        "n_failed": n_fail,
        "telemetry": dict(outer_telemetry),
        "checks": [r.to_dict() for r in results],
    }


def _format_report(report: dict[str, Any]) -> str:
    lines: list[str] = []
    for item in report["checks"]:
        tag = f"[{item['status']}]"
        lines.append(f"{tag:6s} {item['name']:22s} ({item['duration_ms']:6.1f} ms) - {item['summary']}")
        for det in item.get("details") or []:
            lines.append(f"         -> {det}")
    verdict = "PASS" if report["passed"] else "FAIL"
    lines.append(
        f"OVERALL: {verdict} ({report['n_passed']} passed, {report['n_skipped']} skipped, "
        f"{report['n_failed']} failed in {report['total_duration_ms']:.1f} ms; "
        f"live_api_calls={report['telemetry']['live_api_calls']})"
    )
    return "\n".join(lines)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Keyless end-to-end Canary Arena integrity, anti-leakage, and contract verifier."
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Run verification checks and exit 0 on pass, 1 on any failure.",
    )
    parser.add_argument(
        "--require-all",
        action="store_true",
        help="Fail if optional sibling modules (head_to_head, server, mole_rivals) are absent.",
    )
    parser.add_argument(
        "--json-out",
        type=Path,
        default=None,
        help="Optional path to write JSON verification report.",
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=ROOT,
        help="Repository root directory.",
    )
    parser.add_argument(
        "--base-ref",
        type=str,
        default=DEFAULT_BASE_REF,
        help="Git base ref for protected-paths comparison.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    report = run_all_checks(
        root=args.root,
        base_ref=args.base_ref,
        require_all=bool(args.require_all),
    )
    if args.json_out is not None:
        out_path = Path(args.json_out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(_format_report(report))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
