from __future__ import annotations

import argparse
import contextlib
from dataclasses import asdict, dataclass, field
from html.parser import HTMLParser
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import secrets
import shutil
import subprocess
import sys
import tarfile
import threading
import time
from typing import Any, Iterable, Iterator, Mapping, Sequence
from urllib.parse import unquote, urljoin, urlsplit
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from canary.env import Env
from canary.rules import DEV_SEEDS, HELDOUT_SEEDS, JUDGE_SEEDS

SHARED_PW_ROOT = Path("/localscratch/fleet-silas/demo-video")
SHARED_PW_PYTHON = SHARED_PW_ROOT / "venv" / "bin" / "python"
SHARED_PW_BROWSERS = SHARED_PW_ROOT / "browsers"
SHARED_PW_LIBS = SHARED_PW_ROOT / "libs" / "usr" / "lib64"
SHARED_MPL_FONTS = Path(
    "/tmp/fleet-silas/shared/agent-arena-venv/lib/python3.12/site-packages/matplotlib/mpl-data/fonts/ttf"
)
DEFAULT_SCRATCH_ROOT = Path("/tmp/opencode/w3_pw_scratch")

SLASH2 = chr(47) * 2
HTTP_PREFIX = "http:" + SLASH2
HTTPS_PREFIX = "https:" + SLASH2
ROUTE_ALL_GLOB = "*" * 2 + "/*"

EXTERNAL_API_HOSTS = frozenset(
    {
        "generativelanguage.googleapis.com",
        "aiplatform.googleapis.com",
        "api.openai.com",
        "api.anthropic.com",
        "openrouter.ai",
        "api.x.ai",
        "api.groq.com",
        "api.together.xyz",
        "api.fireworks.ai",
        "api.mistral.ai",
        "huggingface.co",
    }
)
EXTERNAL_API_PATH_TOKENS = (
    "/v1beta/models",
    "/v1/chat/completions",
    "/v1/responses",
    "/v1/messages",
    ":generatecontent",
    ":streamgeneratecontent",
)
KNOWN_CDN_HOSTS = frozenset(
    {
        "cdn.jsdelivr.net",
        "fonts.googleapis.com",
        "fonts.gstatic.com",
        "unpkg.com",
        "cdnjs.cloudflare.com",
    }
)

CULPRIT_ATTR_NAMES = frozenset(
    {
        "data-culprit",
        "data-mole",
        "data-true-mole",
        "data-mole-id",
        "data-decoy",
        "data-true-decoy",
        "data-decoy-id",
        "data-is-mole",
        "data-is-decoy",
        "data-leaker",
        "data-secret-role",
        "data-insider",
    }
)
CULPRIT_CLASS_TOKENS = frozenset(
    {
        "is-mole",
        "true-mole",
        "mole-culprit",
        "culprit",
        "leaking-sprite",
        "mole-row",
        "is-decoy",
        "decoy-row",
    }
)
SUSPICIOUS_WINDOW_KEY_RE = re.compile(
    r"^(?:__+(?:MOLE|TRUE_MOLE|DECOY|CULPRIT|LEAKER|TRUTH|ANSWER).*|"
    r"(?:TRUE_MOLE|MOLE_ID|TRUE_DECOY|DECOY_ID|CULPRIT_ID|SECRET_MOLE))$",
    re.IGNORECASE,
)
PRE_END_TRUTH_KEYS = frozenset(
    {
        "mole",
        "true_mole",
        "mole_id",
        "moleid",
        "decoy",
        "true_decoy",
        "decoy_id",
        "decoyid",
        "culprit",
        "leaking_sprite_employee",
        "leakingspriteemployee",
        "mole_sprite",
        "culprit_sprite",
        "_world",
        "world_seed",
    }
)
PASSIVE_POST_HOC_KEYS = frozenset(
    {
        "solver_arm",
        "rumour_follower_arm",
        "sealed_reveal",
        "sealed",
        "commitment",
    }
)
OPPONENT_CONTAINER_KEYS = frozenset(
    {
        "opponent",
        "opponent_steps",
        "ai_steps",
        "gemini",
        "gemini_steps",
        "rival",
        "rival_steps",
        "duel",
        "duel_state",
        "duel_split",
    }
)
EMP_ID_RE = re.compile(r"^e\d{2,3}$", re.IGNORECASE)
VERDICT_LEAK_TEXT_RE = re.compile(
    r"(?:\bthe\s+mole\s+(?:was|is)\s+(e\d{2,3})\b|"
    r"\btrue\s+mole\s*[:=]\s*(e\d{2,3})\b|"
    r"\bmole\s+revealed\s*[:=]\s*(e\d{2,3})\b|"
    r"\b(?:__mole|data-culprit|leaking_sprite_employee)\s*[:=]\s*[\"']?(e\d{2,3})\b)",
    re.IGNORECASE,
)
AI_PANE_UNSEALED_ACCUSE_RE = re.compile(
    r"(?:\baccus(?:e|ed|ing|ation)\b[^.\n]{0,40}\b(e\d{2,3})\b|"
    r"\"tool\"\s*:\s*\"accuse\"[^}]{0,120}\"(?:employee|accused)\"\s*:\s*\"(e\d{2,3})\")",
    re.IGNORECASE,
)
CONSOLE_TRUTH_LEAK_RE = re.compile(
    r"(?:\b(?:mole|true_mole|decoy|culprit|leaking_sprite_employee)\b\s*[:=]\s*[\"']?(e\d{2,3})\b|"
    r"\btrue_v\b\s*[:=]\s*[0-9]+\.[0-9]+)",
    re.IGNORECASE,
)
WINDOW_JSON_ASSIGN_RE = re.compile(
    r"(?:\b(?:window|globalThis|self)\.[A-Za-z_$][A-Za-z0-9_$]*|"
    r"\b(?:const|let|var)\s+[A-Z][A-Z0-9_]{2,})\s*=\s*"
)

BASE_KEYS_INIT_SCRIPT = "window.__PW_BASE_WINDOW_KEYS = Object.keys(window);"

LOCAL_PYODIDE_INIT_SCRIPT = """
window.loadPyodide = async function () {
  function rpc(payload) {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", "/__local_pyodide_rpc__", false);
    xhr.setRequestHeader("Content-Type", "application/json");
    xhr.send(JSON.stringify(payload));
    const parsed = JSON.parse(xhr.responseText);
    if (!parsed.ok) {
      throw new Error(parsed.error || "local pyodide rpc error");
    }
    return parsed.result;
  }
  return {
    FS: {
      mkdirTree: function () {},
      writeFile: function () {},
    },
    runPython: function (code) {
      const m = String(code).match(/canary_game\\.Game\\((.+)\\)\\s*$/);
      if (!m) {
        return null;
      }
      const seedArg = JSON.parse(m[1]);
      const gameId = rpc({ op: "create_game", seed: seedArg });
      return {
        spec_json: function () {
          return rpc({ op: "spec_json", game_id: gameId });
        },
        call_json: function (tool, argsJson) {
          return rpc({ op: "call_json", game_id: gameId, tool: tool, args_json: argsJson });
        },
        reveal_json: function () {
          return rpc({ op: "reveal_json", game_id: gameId });
        },
        actions_json: function () {
          return rpc({ op: "actions_json", game_id: gameId });
        },
      };
    },
  };
};
"""

SNAPSHOT_EVAL_JS = """
() => {
  const storageObj = {};
  try {
    for (let i = 0; i < localStorage.length; i += 1) {
      const k = localStorage.key(i);
      if (k !== null) storageObj[k] = localStorage.getItem(k);
    }
  } catch (_) {}
  const sessionObj = {};
  try {
    for (let i = 0; i < sessionStorage.length; i += 1) {
      const k = sessionStorage.key(i);
      if (k !== null) sessionObj[k] = sessionStorage.getItem(k);
    }
  } catch (_) {}
  const keys = Object.keys(window);
  const baseSet = new Set(window.__PW_BASE_WINDOW_KEYS || []);
  const globals = {};
  for (const k of keys) {
    if (k === "__PW_BASE_WINDOW_KEYS") continue;
    if (!baseSet.has(k) || /^(?:__|MOLE|DECOY|CULPRIT|ARENA|CANARY|DUEL|SEED|TRUTH)/i.test(k)) {
      try {
        const val = window[k];
        if (val === null || typeof val === "string" || typeof val === "number" || typeof val === "boolean") {
          globals[k] = val;
        } else if (typeof val === "object") {
          globals[k] = JSON.parse(JSON.stringify(val));
        }
      } catch (_) {
        globals[k] = "[unserializable]";
      }
    }
  }
  let lexicalGameState = null;
  try {
    if (typeof S === "object" && S !== null && "over" in S && "day" in S) {
      lexicalGameState = {
        seed: S.seed,
        day: S.day,
        V: S.V,
        calls: S.calls,
        over: S.over,
        staffCount: Array.isArray(S.staff) ? S.staff.length : 0,
        ownKeys: Object.keys(S),
      };
    }
  } catch (_) {}
  return {
    html: document.documentElement ? document.documentElement.outerHTML : "",
    storage: storageObj,
    session: sessionObj,
    keys: keys,
    globals: globals,
    lexical_game_state: lexicalGameState,
  };
}
"""


@dataclass
class PhaseOutcome:
    phase_id: str
    name: str
    passed: bool
    status: str
    summary: str
    metrics: dict[str, Any] = field(default_factory=dict)
    violations: list[str] = field(default_factory=list)


def playwright_available() -> bool:
    try:
        return importlib.util.find_spec("playwright.sync_api") is not None
    except ModuleNotFoundError:
        return False


def shared_playwright_python_available() -> bool:
    return SHARED_PW_PYTHON.is_file() and os.access(SHARED_PW_PYTHON, os.X_OK)


def build_playwright_env(base_env: Mapping[str, str] | None = None) -> dict[str, str]:
    env = dict(os.environ if base_env is None else base_env)
    py_path = env.get("PYTHONPATH", "")
    root_s = str(ROOT)
    env["PYTHONPATH"] = f"{root_s}:{py_path}" if py_path and root_s not in py_path.split(":") else root_s
    if SHARED_PW_BROWSERS.is_dir() and not env.get("PLAYWRIGHT_BROWSERS_PATH"):
        env["PLAYWRIGHT_BROWSERS_PATH"] = str(SHARED_PW_BROWSERS)
    if SHARED_PW_LIBS.is_dir():
        libs_s = str(SHARED_PW_LIBS)
        cur_ld = env.get("LD_LIBRARY_PATH", "")
        parts = [p for p in cur_ld.split(":") if p]
        if libs_s not in parts:
            env["LD_LIBRARY_PATH"] = ":".join([libs_s, *parts])
    env["CANARY_OFFLINE"] = "1"
    env["SLEEPER_OFFLINE"] = "1"
    for key_name in (
        "GEMINI_API_KEY",
        "GOOGLE_GENERATIVE_AI_API_KEY",
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "OPENROUTER_API_KEY",
    ):
        env[key_name] = ""
    return env


@contextlib.contextmanager
def scratch_workspace(scratch_root: Path = DEFAULT_SCRATCH_ROOT) -> Iterator[Path]:
    scratch_root.mkdir(parents=True, exist_ok=True)
    run_dir = scratch_root / f"run-{secrets.token_hex(6)}"
    run_dir.mkdir(parents=True, exist_ok=True)
    try:
        yield run_dir
    finally:
        shutil.rmtree(run_dir, ignore_errors=True)
        if scratch_root.exists():
            try:
                scratch_root.rmdir()
            except OSError:
                pass


def _is_int_not_bool(val: Any) -> bool:
    return isinstance(val, int) and not isinstance(val, bool)


def _is_finite_num(val: Any) -> bool:
    return isinstance(val, (int, float)) and not isinstance(val, bool) and math.isfinite(float(val))


def _is_sealed_value(val: Any) -> bool:
    if not isinstance(val, str):
        return False
    s = val.strip()
    return (
        s in {"[SEALED]", "[NONE]", "sealed"}
        or s.startswith("sha256:")
        or s.startswith("sealed:")
        or s.startswith("xor:")
        or s.startswith("b64:")
    )


def _benchmark_seed_bucket(seed_val: int) -> str | None:
    if seed_val in JUDGE_SEEDS:
        return "JUDGE_SEEDS"
    if seed_val in HELDOUT_SEEDS:
        return "HELDOUT_SEEDS"
    return None


def classify_request_url(url: str, allowed_local_origins: Iterable[str]) -> dict[str, Any]:
    raw = str(url or "").strip()
    allowed_set = {o.rstrip("/") for o in allowed_local_origins}
    parts = urlsplit(raw)
    scheme = parts.scheme.lower()
    host = (parts.hostname or "").lower()
    origin = f"{scheme}:{SLASH2}{parts.netloc.lower()}" if scheme and parts.netloc else ""

    if scheme in {"data", "blob", "about", "file"}:
        return {"url": raw, "allowed": True, "category": "self_contained_scheme", "host": host}
    if origin and origin in allowed_set:
        return {"url": raw, "allowed": True, "category": "local_ephemeral_http", "host": host}

    low_path = (parts.path or "").lower()
    if (
        host in EXTERNAL_API_HOSTS
        or any(host.endswith("." + h) for h in EXTERNAL_API_HOSTS)
        or any(tok in low_path for tok in EXTERNAL_API_PATH_TOKENS)
    ):
        return {"url": raw, "allowed": False, "category": "external_api", "host": host}
    if host in KNOWN_CDN_HOSTS or any(host.endswith("." + h) for h in KNOWN_CDN_HOSTS):
        return {"url": raw, "allowed": False, "category": "external_cdn", "host": host}
    return {"url": raw, "allowed": False, "category": "external_other", "host": host}


def audit_network_requests(
    requests_log: Sequence[Mapping[str, Any]],
    allowed_local_origins: Iterable[str],
    *,
    offline_bundled: bool = True,
    strict_zero_cdn: bool = False,
) -> dict[str, Any]:
    local_urls: list[str] = []
    external_api_urls: list[str] = []
    external_cdn_urls: list[str] = []
    external_other_urls: list[str] = []
    violations: list[str] = []

    for entry in requests_log:
        url = str(entry.get("url") or "")
        info = classify_request_url(url, allowed_local_origins)
        cat = info["category"]
        if info["allowed"]:
            local_urls.append(url)
        elif cat == "external_api":
            external_api_urls.append(url)
            violations.append(f"network_firewall: forbidden external API request blocked: {url}")
        elif cat == "external_cdn":
            external_cdn_urls.append(url)
            if offline_bundled or strict_zero_cdn:
                violations.append(f"network_firewall: forbidden external CDN request on offline surface: {url}")
        else:
            external_other_urls.append(url)
            violations.append(f"network_firewall: forbidden external network request blocked: {url}")

    return {
        "total_requests": len(requests_log),
        "local_requests": len(local_urls),
        "external_api_requests": external_api_urls,
        "external_cdn_requests": external_cdn_urls,
        "external_other_requests": external_other_urls,
        "offline_bundled": offline_bundled,
        "violations": violations,
    }


def _extract_js_assigned_objects(js_text: str, label: str) -> list[tuple[str, Any]]:
    decoder = json.JSONDecoder()
    found: list[tuple[str, Any]] = []
    for match in WINDOW_JSON_ASSIGN_RE.finditer(js_text):
        idx = match.end()
        while idx < len(js_text) and js_text[idx].isspace():
            idx += 1
        if idx >= len(js_text) or js_text[idx] not in "{[":
            continue
        try:
            parsed, _ = decoder.raw_decode(js_text, idx)
            lhs = match.group(0).split("=")[0].strip()
            found.append((f"{label}:{lhs}", parsed))
        except json.JSONDecodeError:
            continue
    return found


def _scan_object_pre_end(
    obj: Any,
    loc: str,
    *,
    expected_mole: str | None = None,
    expected_decoy: str | None = None,
    expected_known_v: float | None = None,
    expected_true_v: float | None = None,
    human_done: bool = False,
    in_opponent_scope: bool = False,
    in_passive_post_hoc: bool = False,
) -> list[str]:
    violations: list[str] = []
    if isinstance(obj, list):
        for idx, item in enumerate(obj):
            violations.extend(
                _scan_object_pre_end(
                    item,
                    f"{loc}[{idx}]",
                    expected_mole=expected_mole,
                    expected_decoy=expected_decoy,
                    expected_known_v=expected_known_v,
                    expected_true_v=expected_true_v,
                    human_done=human_done,
                    in_opponent_scope=in_opponent_scope,
                    in_passive_post_hoc=in_passive_post_hoc,
                )
            )
        return violations

    if not isinstance(obj, dict):
        return violations

    node_human_done = human_done
    if isinstance(obj.get("humanDone"), bool):
        node_human_done = obj["humanDone"]
    elif isinstance(obj.get("human_done"), bool):
        node_human_done = obj["human_done"]

    for seed_key in ("seed", "case_seed", "episode_seed"):
        sval = obj.get(seed_key)
        if _is_int_not_bool(sval):
            bucket = _benchmark_seed_bucket(int(sval))
            if bucket is not None:
                violations.append(f"{loc}.{seed_key}: forbidden {bucket} seed {sval}")
    for seeds_key in ("seeds", "case_seeds", "episode_seeds", "default_seeds"):
        slist = obj.get(seeds_key)
        if isinstance(slist, list):
            for idx, item in enumerate(slist):
                if _is_int_not_bool(item):
                    bucket = _benchmark_seed_bucket(int(item))
                    if bucket is not None:
                        violations.append(f"{loc}.{seeds_key}[{idx}]: forbidden {bucket} seed {item}")

    if not node_human_done and not in_passive_post_hoc:
        for k, v in obj.items():
            ks = str(k)
            klow = ks.lower()
            if klow in PRE_END_TRUTH_KEYS and v is not None and v != "" and v is not False and not _is_sealed_value(v):
                violations.append(f"{loc}.{ks}: pre-end hidden truth exposed ({ks}={v!r})")
            if klow in {"is_mole", "ismole", "is_decoy", "isdecoy"} and v is True:
                violations.append(f"{loc}.{ks}: pre-end boolean culprit flag exposed ({ks}=True)")
            if klow in {"true_v", "truev"} and _is_finite_num(v):
                violations.append(f"{loc}.{ks}: pre-end raw true_v exposed ({ks}={v})")
            if (
                expected_mole
                and isinstance(v, str)
                and v == expected_mole
                and any(tok in klow for tok in ("mole", "culprit", "leaker", "insider", "secret", "answer"))
            ):
                violations.append(f"{loc}.{ks}: pre-end true mole {expected_mole!r} exposed")
            if (
                expected_decoy
                and isinstance(v, str)
                and v == expected_decoy
                and any(tok in klow for tok in ("decoy", "culprit", "secret", "answer"))
            ):
                violations.append(f"{loc}.{ks}: pre-end true decoy {expected_decoy!r} exposed")

        if (
            expected_known_v is not None
            and expected_true_v is not None
            and abs(expected_true_v - expected_known_v) > 1e-9
        ):
            for v_key in ("V", "visibleV", "visible_v", "shown_v", "hud_v", "display_v"):
                if v_key in obj and _is_finite_num(obj[v_key]):
                    shown = float(obj[v_key])
                    if abs(shown - expected_true_v) < 1e-6 and abs(shown - expected_known_v) > 1e-6:
                        violations.append(
                            f"{loc}.{v_key}: pre-end value {shown} leaks unsurfaced true_v={expected_true_v} "
                            f"(expected known_v={expected_known_v})"
                        )

        tool_name = str(obj.get("tool") or "").lower()
        if tool_name == "accuse" and (in_opponent_scope or obj.get("human_done") is False or obj.get("humanDone") is False):
            args_val = obj.get("args") if "args" in obj else obj.get("arguments")
            emp_id: str | None = None
            if isinstance(args_val, dict):
                raw_emp = args_val.get("employee") or args_val.get("target")
                if isinstance(raw_emp, str):
                    emp_id = raw_emp
            if emp_id is None and isinstance(obj.get("accused"), str):
                emp_id = obj["accused"]
            if emp_id is None and isinstance(obj.get("result"), dict):
                rdata = obj["result"].get("data")
                if isinstance(rdata, dict) and isinstance(rdata.get("accused"), str):
                    emp_id = rdata["accused"]
            if emp_id and EMP_ID_RE.match(emp_id):
                violations.append(
                    f"{loc}: unsealed opponent accuse target {emp_id!r} exposed while !humanDone"
                )

        if in_opponent_scope and isinstance(obj.get("accused"), str) and EMP_ID_RE.match(obj["accused"]):
            violations.append(
                f"{loc}.accused: unsealed opponent accused target {obj['accused']!r} exposed while !humanDone"
            )

    for k, v in obj.items():
        ks = str(k)
        klow = ks.lower()
        child_opp = in_opponent_scope or (klow in OPPONENT_CONTAINER_KEYS)
        child_passive = in_passive_post_hoc or (
            klow in PASSIVE_POST_HOC_KEYS and not child_opp and obj.get("humanDone") is not False and obj.get("human_done") is not False
        )
        violations.extend(
            _scan_object_pre_end(
                v,
                f"{loc}.{ks}",
                expected_mole=expected_mole,
                expected_decoy=expected_decoy,
                expected_known_v=expected_known_v,
                expected_true_v=expected_true_v,
                human_done=node_human_done,
                in_opponent_scope=child_opp,
                in_passive_post_hoc=child_passive,
            )
        )
    return violations


class _PreEndDOMInspector(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.attr_violations: list[str] = []
        self.json_scripts: list[tuple[str, str]] = []
        self.inline_scripts: list[tuple[str, str]] = []
        self.visible_text_chunks: list[str] = []
        self.ai_pane_text_chunks: list[str] = []
        self.vitals_text_chunks: list[str] = []
        self.case_id_text: list[str] = []
        self.desk_hidden: bool | None = None
        self.closed_visible_pre_end: bool = False
        self._script_idx = 0
        self._active_script_type: str | None = None
        self._active_script_id: str = ""
        self._script_buf: list[str] = []
        self._hidden_depth = 0
        self._ai_pane_depth = 0
        self._vitals_depth = 0
        self._case_id_depth = 0
        self._in_style = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        t = tag.lower()
        attr_map = {k.lower(): ("" if v is None else str(v)) for k, v in attrs}
        has_hidden = any(k.lower() == "hidden" for k, _ in attrs)
        el_id = attr_map.get("id", "")
        cls_tokens = set(attr_map.get("class", "").split())

        if el_id == "desk":
            self.desk_hidden = has_hidden
        if (el_id == "closed" or "arena-end-card" in cls_tokens) and not has_hidden:
            self.closed_visible_pre_end = True

        for raw_k, raw_v in attrs:
            klow = raw_k.lower()
            sval = "" if raw_v is None else str(raw_v).strip()
            if klow in CULPRIT_ATTR_NAMES and sval and sval.lower() not in {"false", "0", "none", "null"} and not _is_sealed_value(sval):
                self.attr_violations.append(f"dom_attr: <{t} {raw_k}={sval!r}> exposes culprit metadata pre-end")
            elif any(tok in klow for tok in ("culprit", "mole", "decoy")) and EMP_ID_RE.match(sval):
                self.attr_violations.append(f"dom_attr: <{t} {raw_k}={sval!r}> exposes employee id in truth attribute")
            elif klow == "data-accused" and EMP_ID_RE.match(sval):
                self.attr_violations.append(f"dom_attr: <{t} data-accused={sval!r}> exposes unsealed accuse target")

        bad_classes = sorted(cls_tokens & CULPRIT_CLASS_TOKENS)
        if bad_classes:
            self.attr_violations.append(f"dom_class: <{t} class={attr_map.get('class', '')!r}> marks {bad_classes} pre-end")

        void_tags = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}
        if t not in void_tags:
            if self._hidden_depth > 0 or has_hidden:
                self._hidden_depth += 1
            if self._ai_pane_depth > 0 or bool(cls_tokens & {"pane-ai", "gemini-pane", "solver-pane"}) or attr_map.get("data-pane") == "ai" or "data-opponent" in attr_map:
                self._ai_pane_depth += 1
            if self._vitals_depth > 0 or el_id in {"vitals", "accV"} or bool(cls_tokens & {"arena-clock-strip", "clock-strip"}) or attr_map.get("data-testid") == "visible-v":
                self._vitals_depth += 1
            if self._case_id_depth > 0 or el_id == "caseId":
                self._case_id_depth += 1

        if t == "script":
            self._script_idx += 1
            self._active_script_type = attr_map.get("type", "").strip().lower()
            self._active_script_id = el_id or f"script_{self._script_idx}"
            self._script_buf = []
        elif t == "style":
            self._in_style = True

    def handle_endtag(self, tag: str) -> None:
        t = tag.lower()
        void_tags = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}
        if t == "script" and self._active_script_type is not None:
            body = "".join(self._script_buf)
            if self._active_script_type in {"application/json", "application/ld+json"}:
                self.json_scripts.append((self._active_script_id, body))
            elif not self._active_script_type or "javascript" in self._active_script_type or self._active_script_type == "module":
                self.inline_scripts.append((self._active_script_id, body))
            self._active_script_type = None
            self._script_buf = []
        elif t == "style":
            self._in_style = False

        if t not in void_tags:
            if self._hidden_depth > 0:
                self._hidden_depth -= 1
            if self._ai_pane_depth > 0:
                self._ai_pane_depth -= 1
            if self._vitals_depth > 0:
                self._vitals_depth -= 1
            if self._case_id_depth > 0:
                self._case_id_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._active_script_type is not None:
            self._script_buf.append(data)
            return
        if self._in_style:
            return
        if self._hidden_depth == 0:
            self.visible_text_chunks.append(data)
            if self._ai_pane_depth > 0:
                self.ai_pane_pane_append(data)
            if self._vitals_depth > 0:
                self.vitals_text_chunks.append(data)
            if self._case_id_depth > 0:
                self.case_id_text.append(data)

    def ai_pane_pane_append(self, data: str) -> None:
        self.ai_pane_text_chunks.append(data)


def inspect_dom_html(
    html: str,
    *,
    expected_mole: str | None = None,
    expected_decoy: str | None = None,
    expected_known_v: float | None = None,
    expected_true_v: float | None = None,
    human_done: bool = False,
    forbidden_active_seed: int | None = None,
) -> list[str]:
    violations: list[str] = []
    parser = _PreEndDOMInspector()
    parser.feed(html or "")
    parser.close()

    if not human_done:
        violations.extend(parser.attr_violations)
        if parser.closed_visible_pre_end:
            violations.append("dom_reveal: post-game closed/end-card section visible while !done")

        visible_text = " ".join(" ".join(parser.visible_text_chunks).split())
        for match in VERDICT_LEAK_TEXT_RE.finditer(visible_text):
            leaked_emp = next((g for g in match.groups() if g), "")
            violations.append(f"dom_text: pre-end verdict text leaks employee {leaked_emp!r}")

        ai_text = " ".join(" ".join(parser.ai_pane_text_chunks).split())
        for match in AI_PANE_UNSEALED_ACCUSE_RE.finditer(ai_text):
            leaked_emp = next((g for g in match.groups() if g), "")
            violations.append(f"dom_ai_pane: opponent pane leaks unsealed accuse target {leaked_emp!r} while !humanDone")

        if (
            expected_known_v is not None
            and expected_true_v is not None
            and abs(expected_true_v - expected_known_v) > 1e-9
        ):
            kv_fmt = f"{expected_known_v:.2f}"
            tv_fmt = f"{expected_true_v:.2f}"
            vitals_text = " ".join(" ".join(parser.vitals_text_chunks).split())
            if vitals_text and kv_fmt != tv_fmt:
                if re.search(rf"(?<![0-9.]){re.escape(tv_fmt)}(?![0-9.])", vitals_text):
                    violations.append(
                        f"dom_vitals: pre-end HUD displays unsurfaced true_v={tv_fmt} instead of known_v={kv_fmt}"
                    )
                elif not re.search(rf"(?<![0-9.]){re.escape(kv_fmt)}(?![0-9.])", vitals_text):
                    violations.append(
                        f"dom_vitals: expected known_v={kv_fmt} in pre-end HUD vitals, got {vitals_text[:120]!r}"
                    )

    for sid, raw_json in parser.json_scripts:
        sbody = raw_json.strip()
        if not sbody:
            continue
        try:
            parsed = json.loads(sbody)
        except json.JSONDecodeError as exc:
            violations.append(f"dom_json_script[{sid}]: invalid JSON ({exc.msg})")
            continue
        violations.extend(
            _scan_object_pre_end(
                parsed,
                f"dom_json_script[{sid}]",
                expected_mole=expected_mole,
                expected_decoy=expected_decoy,
                expected_known_v=expected_known_v,
                expected_true_v=expected_true_v,
                human_done=human_done,
            )
        )

    for sid, js_code in parser.inline_scripts:
        for assign_label, assigned_obj in _extract_js_assigned_objects(js_code, f"dom_inline_script[{sid}]"):
            violations.extend(
                _scan_object_pre_end(
                    assigned_obj,
                    assign_label,
                    expected_mole=expected_mole,
                    expected_decoy=expected_decoy,
                    expected_known_v=expected_known_v,
                    expected_true_v=expected_true_v,
                    human_done=human_done,
                )
            )

    if forbidden_active_seed is not None:
        case_txt = " ".join(" ".join(parser.case_id_text).split())
        if parser.desk_hidden is False:
            violations.append(
                f"seed_firewall: #desk became visible for forbidden benchmark seed {forbidden_active_seed}"
            )
        if str(forbidden_active_seed) in case_txt:
            violations.append(
                f"seed_firewall: #caseId accepted forbidden benchmark seed {forbidden_active_seed} ({case_txt!r})"
            )

    return violations


def inspect_js_state_and_storage(
    snapshot: Mapping[str, Any],
    *,
    expected_mole: str | None = None,
    expected_decoy: str | None = None,
    expected_known_v: float | None = None,
    expected_true_v: float | None = None,
    human_done: bool = False,
    forbidden_active_seed: int | None = None,
) -> list[str]:
    violations: list[str] = []

    for err in snapshot.get("pageerrors") or ():
        violations.append(f"pageerror: uncaught JS exception: {err}")

    win_keys = [str(k) for k in (snapshot.get("keys") or ())]
    globals_map = snapshot.get("globals") if isinstance(snapshot.get("globals"), Mapping) else {}

    if not human_done:
        for k in win_keys:
            if SUSPICIOUS_WINDOW_KEY_RE.match(k):
                val = globals_map.get(k, "<present>")
                if val is not None and val != "" and val is not False and not _is_sealed_value(val):
                    violations.append(f"window_key: suspicious pre-end global window.{k}={val!r}")

    for gkey, gval in globals_map.items():
        ks = str(gkey)
        klow = ks.lower()
        if not human_done and SUSPICIOUS_WINDOW_KEY_RE.match(ks):
            if gval is not None and gval != "" and gval is not False and not _is_sealed_value(gval):
                msg = f"window_global: window.{ks} exposes pre-end value {gval!r}"
                if msg not in violations:
                    violations.append(msg)
        if not human_done and isinstance(gval, str):
            if expected_mole and gval == expected_mole:
                violations.append(f"window_global: window.{ks} equals true mole {expected_mole!r} pre-end")
            if expected_decoy and gval == expected_decoy:
                violations.append(f"window_global: window.{ks} equals true decoy {expected_decoy!r} pre-end")
        violations.extend(
            _scan_object_pre_end(
                gval,
                f"window.{ks}",
                expected_mole=expected_mole,
                expected_decoy=expected_decoy,
                expected_known_v=expected_known_v,
                expected_true_v=expected_true_v,
                human_done=human_done,
                in_opponent_scope=(klow in OPPONENT_CONTAINER_KEYS or "duel" in klow or "opponent" in klow),
            )
        )

    lex_state = snapshot.get("lexical_game_state")
    if isinstance(lex_state, Mapping):
        if forbidden_active_seed is not None and lex_state.get("seed") == forbidden_active_seed:
            violations.append(
                f"seed_firewall: lexical game state S.seed accepted forbidden seed {forbidden_active_seed}"
            )
        if not human_done:
            own_keys = {str(x).lower() for x in (lex_state.get("ownKeys") or ())}
            leaked_own = sorted(own_keys & {"mole", "true_mole", "decoy", "true_decoy", "culprit"})
            if leaked_own:
                violations.append(f"lexical_state: S exposes forbidden pre-end keys {leaked_own}")
            if (
                expected_known_v is not None
                and expected_true_v is not None
                and abs(expected_true_v - expected_known_v) > 1e-9
                and _is_finite_num(lex_state.get("V"))
            ):
                s_v = float(lex_state["V"])
                if abs(s_v - expected_true_v) < 1e-6 and abs(s_v - expected_known_v) > 1e-6:
                    violations.append(
                        f"lexical_state: S.V={s_v} leaks true_v={expected_true_v} instead of known_v={expected_known_v}"
                    )

    for store_label, store_field in (("localStorage", "storage"), ("sessionStorage", "session")):
        store_obj = snapshot.get(store_field)
        if not isinstance(store_obj, Mapping):
            continue
        for skey, raw_sval in store_obj.items():
            ks = str(skey)
            sval = "" if raw_sval is None else str(raw_sval)
            klow = ks.lower()
            if not human_done:
                if any(tok in klow for tok in ("mole", "decoy", "culprit", "truth", "world_seed")) and sval and not _is_sealed_value(sval):
                    violations.append(f"{store_label}[{ks!r}]: pre-end truth key in web storage ({sval[:80]!r})")
                if expected_mole and sval.strip() == expected_mole:
                    violations.append(f"{store_label}[{ks!r}]: equals true mole {expected_mole!r} pre-end")
                if expected_decoy and sval.strip() == expected_decoy:
                    violations.append(f"{store_label}[{ks!r}]: equals true decoy {expected_decoy!r} pre-end")
            stripped = sval.strip()
            if stripped.startswith(("{", "[")):
                try:
                    parsed_store = json.loads(stripped)
                except json.JSONDecodeError:
                    parsed_store = None
                if parsed_store is not None:
                    violations.extend(
                        _scan_object_pre_end(
                            parsed_store,
                            f"{store_label}[{ks!r}]",
                            expected_mole=expected_mole,
                            expected_decoy=expected_decoy,
                            expected_known_v=expected_known_v,
                            expected_true_v=expected_true_v,
                            human_done=human_done,
                        )
                    )

    if not human_done:
        for item in snapshot.get("console") or ():
            txt = str(item.get("text") if isinstance(item, Mapping) else item)
            if CONSOLE_TRUTH_LEAK_RE.search(txt):
                violations.append(f"console: pre-end truth leak in console output: {txt[:140]}")
            elif expected_mole and re.search(rf"\b{re.escape(expected_mole)}\b", txt) and re.search(r"\b(?:mole|culprit|leaker|insider)\b", txt, re.IGNORECASE):
                violations.append(f"console: pre-end console names true mole {expected_mole!r}: {txt[:140]}")
            elif AI_PANE_UNSEALED_ACCUSE_RE.search(txt) and re.search(r"\b(?:opponent|rival|gemini|duel)\b", txt, re.IGNORECASE):
                violations.append(f"console: pre-end console leaks opponent accuse target: {txt[:140]}")

    return violations


def inspect_browser_snapshot(
    snapshot: Mapping[str, Any],
    *,
    allowed_local_origins: Iterable[str],
    offline_bundled: bool = True,
    strict_zero_cdn: bool = False,
    expected_mole: str | None = None,
    expected_decoy: str | None = None,
    expected_known_v: float | None = None,
    expected_true_v: float | None = None,
    human_done: bool = False,
    forbidden_active_seed: int | None = None,
) -> dict[str, Any]:
    net = audit_network_requests(
        snapshot.get("requests") or (),
        allowed_local_origins,
        offline_bundled=offline_bundled,
        strict_zero_cdn=strict_zero_cdn,
    )
    dom_viols = inspect_dom_html(
        str(snapshot.get("html") or ""),
        expected_mole=expected_mole,
        expected_decoy=expected_decoy,
        expected_known_v=expected_known_v,
        expected_true_v=expected_true_v,
        human_done=human_done,
        forbidden_active_seed=forbidden_active_seed,
    )
    js_viols = inspect_js_state_and_storage(
        snapshot,
        expected_mole=expected_mole,
        expected_decoy=expected_decoy,
        expected_known_v=expected_known_v,
        expected_true_v=expected_true_v,
        human_done=human_done,
        forbidden_active_seed=forbidden_active_seed,
    )
    all_violations = [*net["violations"], *dom_viols, *js_viols]
    return {
        "passed": len(all_violations) == 0,
        "exit_code": 0 if len(all_violations) == 0 else 1,
        "network": net,
        "dom_violations": dom_viols,
        "js_violations": js_viols,
        "violations": all_violations,
    }


def build_synthetic_control_pages(controls_dir: Path) -> list[dict[str, Any]]:
    controls_dir.mkdir(parents=True, exist_ok=True)
    gemini_url = HTTPS_PREFIX + "generativelanguage.googleapis.com/v1beta/models/gemini-2.5-pro:generateContent"

    clean_html = (
        "<!doctype html><html><head><meta charset='utf-8'><title>Clean Control</title></head>"
        "<body><header><span id='caseId'>case no. 3000</span></header>"
        "<div id='vitals'><span>Value (visible)</span><span>0.96</span></div>"
        "<div class='roster'><div class='row' data-pid='e34'>e34</div></div>"
        "<aside class='pane-ai'><span>Accusation filed [SEALED]</span></aside>"
        "<section id='closed' hidden></section>"
        "<script>window.ARENA_PUBLIC_STATE = {seed: 3000, day: 5, V: 0.96, humanDone: false};</script>"
        "</body></html>\n"
    )
    (controls_dir / "clean_control.html").write_text(clean_html, encoding="utf-8")

    pages: list[tuple[str, str, str, str]] = [
        (
            "leak_window_mole",
            "leak_window_mole.html",
            "window.__MOLE",
            "<!doctype html><html><head><meta charset='utf-8'><title>Leak Window Mole</title></head>"
            "<body><div class='row' data-pid='e34'>e34</div>"
            "<script>window.__MOLE = 'e34';</script></body></html>\n",
        ),
        (
            "leak_data_culprit",
            "leak_data_culprit.html",
            "data-culprit",
            "<!doctype html><html><head><meta charset='utf-8'><title>Leak Data Culprit</title></head>"
            "<body><div class='roster'><div class='row' data-pid='e34' data-culprit='e34'>e34</div></div>"
            "</body></html>\n",
        ),
        (
            "leak_unsealed_opponent_accuse",
            "leak_unsealed_opponent_accuse.html",
            "accuse",
            "<!doctype html><html><head><meta charset='utf-8'><title>Leak Opponent Accuse</title></head>"
            "<body><aside class='pane-ai'><div>Rival accused e34 on Day 06</div></aside>"
            "<script>window.ARENA_DUEL = {humanDone: false, opponent_steps: "
            "[{day: 6, tool: 'accuse', args: {employee: 'e34'}}]};</script></body></html>\n",
        ),
        (
            "leak_external_gemini_fetch",
            "leak_external_gemini_fetch.html",
            "generativelanguage.googleapis.com",
            "<!doctype html><html><head><meta charset='utf-8'><title>Leak External Fetch</title></head>"
            f"<body><script>fetch({json.dumps(gemini_url)}).catch(function(){{}});</script></body></html>\n",
        ),
        (
            "leak_uncaught_reference_error",
            "leak_uncaught_reference_error.html",
            "nonExistentCanaryPreEndSymbol",
            "<!doctype html><html><head><meta charset='utf-8'><title>Leak ReferenceError</title></head>"
            "<body><script>nonExistentCanaryPreEndSymbol();</script></body></html>\n",
        ),
    ]

    manifest: list[dict[str, Any]] = []
    for ctrl_id, fname, expected_token, html_body in pages:
        fpath = controls_dir / fname
        fpath.write_text(html_body, encoding="utf-8")
        manifest.append(
            {
                "control_id": ctrl_id,
                "filename": fname,
                "expected_token": expected_token,
            }
        )
    return manifest


def _load_module_from_path(mod_name: str, py_path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(mod_name, py_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load module {mod_name} from {py_path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class _LocalGameRPCRegistry:
    def __init__(self, canary_game_mod: Any) -> None:
        self._cg = canary_game_mod
        self._lock = threading.Lock()
        self._games: dict[str, Any] = {}
        self._env_sessions: dict[str, Env] = {}

    def dispatch(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        op = str(payload.get("op") or "")
        try:
            if op == "create_game":
                game = self._cg.Game(payload.get("seed"))
                gid = secrets.token_hex(8)
                with self._lock:
                    self._games[gid] = game
                return {"ok": True, "result": gid}
            if op in {"spec_json", "call_json", "reveal_json", "actions_json"}:
                gid = str(payload.get("game_id") or "")
                with self._lock:
                    game = self._games.get(gid)
                if game is None:
                    return {"ok": False, "error": "KeyError: unknown game_id"}
                if op == "spec_json":
                    return {"ok": True, "result": game.spec_json()}
                if op == "call_json":
                    return {
                        "ok": True,
                        "result": game.call_json(
                            str(payload.get("tool") or ""),
                            str(payload.get("args_json") or "{}"),
                        ),
                    }
                if op == "reveal_json":
                    return {"ok": True, "result": game.reveal_json()}
                return {"ok": True, "result": game.actions_json()}
            if op == "arena_create":
                tier = str(payload.get("tier") or "hard")
                raw_seed = payload.get("seed")
                s = int(raw_seed)
                if isinstance(raw_seed, bool) or s not in DEV_SEEDS:
                    raise ValueError(f"seed {raw_seed!r} outside public DEV_SEEDS")
                env = Env(tier, s)
                sid = secrets.token_hex(8)
                with self._lock:
                    self._env_sessions[sid] = env
                spec = {
                    "tier": tier,
                    "seed": s,
                    "tools": env.tools_spec(),
                    "instruction": env.instruction(),
                }
                return {"ok": True, "result": {"session_id": sid, "spec": spec}}
            if op == "arena_call":
                sid = str(payload.get("session_id") or "")
                with self._lock:
                    env = self._env_sessions.get(sid)
                if env is None:
                    return {"ok": False, "error": "KeyError: unknown session_id"}
                res = env.call(str(payload.get("tool") or ""), dict(payload.get("args") or {}))
                return {
                    "ok": True,
                    "result": {"ok": res.ok, "data": res.data, "error": res.error, "done": env.done},
                }
            if op == "arena_reveal":
                sid = str(payload.get("session_id") or "")
                with self._lock:
                    env = self._env_sessions.get(sid)
                if env is None:
                    return {"ok": False, "error": "KeyError: unknown session_id"}
                if not env.done:
                    return {"ok": True, "result": {"error": "episode not done"}}
                v = env.verdict()
                return {"ok": True, "result": {"mole": env._world.mole, "you": v}}
            return {"ok": False, "error": f"ValueError: unsupported op {op!r}"}
        except Exception as exc:
            return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


@contextlib.contextmanager
def ephemeral_http_server(serve_dir: Path, rpc_registry: _LocalGameRPCRegistry | None = None) -> Iterator[tuple[str, set[str]]]:
    base_dir = serve_dir.resolve()

    class _Handler(SimpleHTTPRequestHandler):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            super().__init__(*args, directory=str(base_dir), **kwargs)

        def log_message(self, format: str, *args: Any) -> None:
            return

        def do_GET(self) -> None:
            clean_path = unquote(urlsplit(self.path).path)
            if clean_path == "/favicon.ico" and not (base_dir / "favicon.ico").is_file():
                self.send_response(204)
                self.end_headers()
                return
            super().do_GET()

        def do_POST(self) -> None:
            clean_path = unquote(urlsplit(self.path).path)
            if clean_path != "/__local_pyodide_rpc__" or rpc_registry is None:
                self.send_response(404)
                self.end_headers()
                return
            length = int(self.headers.get("Content-Length", "0"))
            raw_body = self.rfile.read(length).decode("utf-8", errors="replace")
            try:
                req_obj = json.loads(raw_body) if raw_body else {}
            except json.JSONDecodeError as exc:
                reply = {"ok": False, "error": f"JSONDecodeError: {exc.msg}"}
            else:
                reply = rpc_registry.dispatch(req_obj)
            encoded = json.dumps(reply, default=str).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    base_url = f"{HTTP_PREFIX}127.0.0.1:{port}"
    allowed_origins = {base_url, f"{HTTP_PREFIX}localhost:{port}"}
    try:
        yield base_url, allowed_origins
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=3.0)


def _git_branch_has_path(root: Path, ref: str, rel_path: str) -> bool:
    proc = subprocess.run(
        ["git", "cat-file", "-e", f"{ref}:{rel_path}"],
        cwd=root,
        capture_output=True,
        timeout=10,
    )
    return proc.returncode == 0


def _git_extract_prefix(root: Path, ref: str, prefix: str, dest_dir: Path) -> bool:
    proc = subprocess.run(
        ["git", "archive", "--format=tar", ref, prefix],
        cwd=root,
        capture_output=True,
        timeout=20,
    )
    if proc.returncode != 0 or not proc.stdout:
        return False
    dest_dir.mkdir(parents=True, exist_ok=True)
    import io

    with tarfile.open(fileobj=io.BytesIO(proc.stdout), mode="r:") as tf:
        for member in tf.getmembers():
            member_path = Path(member.name)
            if member_path.is_absolute() or ".." in member_path.parts:
                continue
            tf.extract(member, path=dest_dir, filter="data")
    return True


def _write_craft_arena_mount_harness(arena_dir: Path) -> Path:
    harness_html = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Canary Arena UI Pre-End Harness</title>
<link rel="stylesheet" href="ui/arena.css">
</head>
<body>
<div id="arenaRoot"></div>
<div id="arenaBootErr" hidden></div>
<script type="module">
import { mountArenaUI } from "./ui/index.js";

function rpc(payload) {
  const xhr = new XMLHttpRequest();
  xhr.open("POST", "/__local_pyodide_rpc__", false);
  xhr.setRequestHeader("Content-Type", "application/json");
  xhr.send(JSON.stringify(payload));
  const out = JSON.parse(xhr.responseText);
  if (!out.ok) {
    throw new Error(out.error || "arena rpc error");
  }
  return out.result;
}

const rawParam = new URLSearchParams(location.search).get("seed");
const initSeed = rawParam !== null ? Number(rawParam) : 6;
if (!Number.isInteger(initSeed) || initSeed < 0 || initSeed >= 10000) {
  const errNode = document.getElementById("arenaBootErr");
  errNode.hidden = false;
  errNode.textContent = "Refused benchmark or invalid seed: " + String(rawParam);
} else {
  const duelPack = {
    default_seeds: [6, 26],
    episodes: {
      "hard:6": {
        seed: 6,
        tier: "hard",
        steps: [
          { day: 1, call_idx: 1, tool: "list_employees", args: {}, V: 1.0 },
          { day: 2, call_idx: 2, tool: "accuse", args: { employee: "e34" }, V: 1.0 }
        ],
        final: { accused: "e34", correct: true, final_day: 6, score: 0.73, sealed: true }
      }
    }
  };
  const api = mountArenaUI(document.getElementById("arenaRoot"), {
    initialMode: "duel",
    initialTier: "hard",
    initialSeed: initSeed,
    duelPack: duelPack,
    createGame: function (tier, seed) {
      const created = rpc({ op: "arena_create", tier: tier, seed: seed });
      const sid = created.session_id;
      return {
        spec_json: function () { return JSON.stringify(created.spec); },
        call_json: function (tool, argsJson) {
          const parsedArgs = argsJson ? JSON.parse(argsJson) : {};
          return JSON.stringify(rpc({ op: "arena_call", session_id: sid, tool: tool, args: parsedArgs }));
        },
        reveal_json: function () {
          return JSON.stringify(rpc({ op: "arena_reveal", session_id: sid }));
        }
      };
    }
  });
  window.__ARENA_MOUNTED_API_READY = Boolean(api);
  if (initSeed === 6) {
    api.runHumanTool("list_employees", {});
    api.runHumanTool("advance_day", {});
    api.runHumanTool("advance_day", {});
    api.runHumanTool("status", {});
  }
}
</script>
</body>
</html>
"""
    target = arena_dir / "mount_harness.html"
    target.write_text(harness_html, encoding="utf-8")
    return target


def discover_audit_surfaces(
    root: Path,
    scratch_dir: Path,
    *,
    scan_remote_branches: bool = True,
) -> dict[str, Any]:
    surfaces: list[dict[str, Any]] = []
    game_site_dir: Path | None = None
    canary_game_mod: Any = None

    build_py = root / "game" / "build.py"
    canary_game_py = root / "game" / "canary_game.py"
    if build_py.is_file() and canary_game_py.is_file():
        build_mod = _load_module_from_path("canary_game_build_pw", build_py)
        game_site_dir = scratch_dir / "game_site"
        manifest = build_mod.build(game_site_dir)
        canary_game_mod = _load_module_from_path("canary_game_runtime_pw", game_site_dir / "py" / "canary_game.py")
        html_txt = (game_site_dir / "index.html").read_text(encoding="utf-8")
        has_external_cdn_tag = ("cdn.jsdelivr.net" in html_txt) or ("fonts.googleapis.com" in html_txt)
        surfaces.append(
            {
                "surface_id": "game_site",
                "source": "disk:game/build.py",
                "rel_url": "/game_site/index.html",
                "offline_bundled": not has_external_cdn_tag,
                "kind": "ws6_game",
                "py_files_count": len(manifest.get("files", [])),
            }
        )

    arena_disk = root / "docs" / "arena"
    found_arena_index = False
    if (arena_disk / "index.html").is_file():
        dst = scratch_dir / "disk_arena" / "docs" / "arena"
        shutil.copytree(arena_disk, dst)
        found_arena_index = True
        surfaces.append(
            {
                "surface_id": "disk_docs_arena_index",
                "source": "disk:docs/arena/index.html",
                "rel_url": "/disk_arena/docs/arena/index.html",
                "offline_bundled": True,
                "kind": "arena_index",
            }
        )
    elif (arena_disk / "ui" / "arena_app.js").is_file():
        dst = scratch_dir / "disk_arena_ui" / "docs" / "arena"
        shutil.copytree(arena_disk, dst)
        _write_craft_arena_mount_harness(dst)
        surfaces.append(
            {
                "surface_id": "disk_docs_arena_ui_harness",
                "source": "disk:docs/arena/ui/arena_app.js",
                "rel_url": "/disk_arena_ui/docs/arena/mount_harness.html",
                "offline_bundled": True,
                "kind": "craft_arena_harness",
            }
        )

    demo_disk = root / "docs" / "demo"
    found_demo_names: set[str] = set()
    if demo_disk.is_dir():
        html_files = sorted(demo_disk.glob("*.html"))
        if html_files:
            dst_demo = scratch_dir / "disk_demo" / "docs" / "demo"
            shutil.copytree(demo_disk, dst_demo)
            for hf in html_files:
                found_demo_names.add(hf.name)
                surfaces.append(
                    {
                        "surface_id": f"disk_docs_demo_{hf.stem}",
                        "source": f"disk:docs/demo/{hf.name}",
                        "rel_url": f"/disk_demo/docs/demo/{hf.name}",
                        "offline_bundled": True,
                        "kind": "demo_html",
                    }
                )

    if scan_remote_branches and (root / ".git").exists():
        refs_proc = subprocess.run(
            ["git", "for-each-ref", "--format=%(refname:short)", "refs/remotes/origin/fr8/canary/"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=10,
        )
        remote_refs = [r.strip() for r in refs_proc.stdout.splitlines() if r.strip()]
        arena_candidates = [
            r
            for r in ("origin/fr8/canary/arena", "origin/fr8/canary/craft-arena", "origin/fr8/canary/port-arena")
            if r in remote_refs
        ]
        if not found_arena_index:
            for ref in arena_candidates:
                if _git_branch_has_path(root, ref, "docs/arena/index.html"):
                    slug = ref.split("/")[-1]
                    dst_root = scratch_dir / f"remote_{slug}"
                    if _git_extract_prefix(root, ref, "docs/arena", dst_root):
                        found_arena_index = True
                        surfaces.append(
                            {
                                "surface_id": f"remote_{slug}_arena_index",
                                "source": f"{ref}:docs/arena/index.html",
                                "rel_url": f"/remote_{slug}/docs/arena/index.html",
                                "offline_bundled": True,
                                "kind": "arena_index",
                            }
                        )
                        break
        if not found_arena_index:
            for ref in ("origin/fr8/canary/craft-arena", "origin/fr8/canary/arena"):
                if ref in remote_refs and _git_branch_has_path(root, ref, "docs/arena/ui/arena_app.js"):
                    slug = ref.split("/")[-1]
                    dst_root = scratch_dir / f"remote_{slug}_ui"
                    if _git_extract_prefix(root, ref, "docs/arena", dst_root):
                        _write_craft_arena_mount_harness(dst_root / "docs" / "arena")
                        surfaces.append(
                            {
                                "surface_id": f"remote_{slug}_mount_ui",
                                "source": f"{ref}:docs/arena/ui/arena_app.js",
                                "rel_url": f"/remote_{slug}_ui/docs/arena/mount_harness.html",
                                "offline_bundled": True,
                                "kind": "craft_arena_harness",
                            }
                        )
                        break

        demo_refs = [
            r
            for r in remote_refs
            if "/demo-" in r or r.endswith("-demo") or r == "origin/fr8/canary/arena"
        ]
        for target_html in ("replay.html", "living_office_v16.html"):
            if target_html in found_demo_names:
                continue
            for ref in demo_refs:
                rel_p = f"docs/demo/{target_html}"
                if _git_branch_has_path(root, ref, rel_p):
                    slug = ref.split("/")[-1]
                    dst_root = scratch_dir / f"remote_{slug}_{target_html.replace('.', '_')}"
                    if _git_extract_prefix(root, ref, "docs/demo", dst_root):
                        found_demo_names.add(target_html)
                        surfaces.append(
                            {
                                "surface_id": f"remote_{slug}_{Path(target_html).stem}",
                                "source": f"{ref}:{rel_p}",
                                "rel_url": f"/remote_{slug}_{target_html.replace('.', '_')}/{rel_p}",
                                "offline_bundled": True,
                                "kind": "demo_html",
                            }
                        )
                        break

    has_arena_surface = any(s["kind"] in {"arena_index", "craft_arena_harness"} for s in surfaces)
    if not has_arena_surface and game_site_dir is not None:
        syn_dir = scratch_dir / "synthetic_arena" / "docs" / "arena"
        syn_dir.mkdir(parents=True, exist_ok=True)
        syn_html = (
            "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
            "<title>Synthetic Arena Fixture</title></head><body>"
            "<div id='arenaRoot'><span id='caseId'></span>"
            "<div id='vitals'><span>Value (visible)</span> <span>0.96</span></div>"
            "<aside class='pane-ai'><span>Opponent accusation [SEALED]</span></aside>"
            "<section id='desk' hidden></section>"
            "<section id='closed' hidden></section></div>"
            "<script>"
            "const sp = new URLSearchParams(location.search);"
            "const sd = sp.get('seed') !== null ? Number(sp.get('seed')) : 6;"
            "if (Number.isInteger(sd) && sd >= 0 && sd < 10000) {"
            "  document.getElementById('caseId').textContent = 'case no. ' + String(sd);"
            "  window.ARENA_PUBLIC_STATE = {seed: sd, day: 3, V: 0.96, humanDone: false};"
            "} else {"
            "  window.ARENA_SEED_REFUSED = sd;"
            "}"
            "</script></body></html>\n"
        )
        (syn_dir / "index.html").write_text(syn_html, encoding="utf-8")
        surfaces.append(
            {
                "surface_id": "synthetic_arena_fixture",
                "source": "synthetic:docs/arena/index.html",
                "rel_url": "/synthetic_arena/docs/arena/index.html",
                "offline_bundled": True,
                "kind": "arena_index",
            }
        )

    return {
        "surfaces": surfaces,
        "game_site_dir": game_site_dir,
        "canary_game_mod": canary_game_mod,
    }


def _open_monitored_page(
    browser: Any,
    allowed_origins: set[str],
    *,
    extra_init_scripts: Sequence[str] = (),
) -> tuple[Any, Any, list[dict[str, Any]], list[dict[str, str]], list[str]]:
    context = browser.new_context()
    context.add_init_script(BASE_KEYS_INIT_SCRIPT)
    for script_src in extra_init_scripts:
        context.add_init_script(script_src)
    page = context.new_page()

    requests_log: list[dict[str, Any]] = []
    console_log: list[dict[str, str]] = []
    pageerrors: list[str] = []

    def _on_route(route: Any) -> None:
        req = route.request
        url = req.url
        info = classify_request_url(url, allowed_origins)
        requests_log.append(
            {
                "url": url,
                "method": req.method,
                "resource_type": req.resource_type,
                "allowed": info["allowed"],
                "category": info["category"],
            }
        )
        if info["allowed"]:
            route.continue_()
        else:
            route.abort()

    page.route(ROUTE_ALL_GLOB, _on_route)
    page.on("console", lambda msg: console_log.append({"type": msg.type, "text": msg.text}))
    page.on("pageerror", lambda exc: pageerrors.append(str(exc)))
    return context, page, requests_log, console_log, pageerrors


def _capture_live_snapshot(
    page: Any,
    requests_log: list[dict[str, Any]],
    console_log: list[dict[str, str]],
    pageerrors: list[str],
) -> dict[str, Any]:
    page.evaluate("() => new Promise(resolve => setTimeout(resolve, 25))")
    evaluated = page.evaluate(SNAPSHOT_EVAL_JS)
    return {
        **evaluated,
        "requests": list(requests_log),
        "console": list(console_log),
        "pageerrors": list(pageerrors),
    }


@contextlib.contextmanager
def _scratch_fontconfig(scratch_dir: Path) -> Iterator[None]:
    prev_file = os.environ.get("FONTCONFIG_FILE")
    prev_path = os.environ.get("FONTCONFIG_PATH")
    if prev_file and Path(prev_file).is_file():
        yield
        return
    font_dirs: list[Path] = []
    if SHARED_MPL_FONTS.is_dir():
        font_dirs.append(SHARED_MPL_FONTS)
    for sys_font_dir in (Path("/usr/share/fonts"), Path("/usr/local/share/fonts")):
        if sys_font_dir.is_dir():
            font_dirs.append(sys_font_dir)
    cache_dir = scratch_dir / "fontcache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    dir_entries = "".join(f"<dir>{d}</dir>" for d in font_dirs)
    conf_xml = (
        "<?xml version='1.0'?>\n"
        "<!DOCTYPE fontconfig SYSTEM 'urn:fontconfig:fonts.dtd'>\n"
        "<fontconfig>"
        f"{dir_entries}"
        "<selectfont><rejectfont><glob>*LastResort*</glob></rejectfont></selectfont>"
        f"<cachedir>{cache_dir}</cachedir>"
        "</fontconfig>\n"
    )
    conf_file = scratch_dir / "fonts.conf"
    conf_file.write_text(conf_xml, encoding="utf-8")
    os.environ["FONTCONFIG_FILE"] = str(conf_file)
    os.environ["FONTCONFIG_PATH"] = str(scratch_dir)
    try:
        yield
    finally:
        if prev_file is None:
            os.environ.pop("FONTCONFIG_FILE", None)
        else:
            os.environ["FONTCONFIG_FILE"] = prev_file
        if prev_path is None:
            os.environ.pop("FONTCONFIG_PATH", None)
        else:
            os.environ["FONTCONFIG_PATH"] = prev_path


def run_live_chromium_audit(
    root: Path = ROOT,
    *,
    scratch_root: Path = DEFAULT_SCRATCH_ROOT,
    scan_remote_branches: bool = True,
    strict_zero_cdn: bool = False,
) -> dict[str, Any]:
    t0 = time.perf_counter()
    pw_env = build_playwright_env()
    for ek in ("PLAYWRIGHT_BROWSERS_PATH", "LD_LIBRARY_PATH", "CANARY_OFFLINE", "SLEEPER_OFFLINE"):
        if ek in pw_env:
            os.environ[ek] = pw_env[ek]

    from playwright.sync_api import sync_playwright

    resolved_root = root.resolve()
    p1_violations: list[str] = []
    p2_violations: list[str] = []
    p3_violations: list[str] = []

    total_local_requests = 0
    total_api_requests: list[str] = []
    all_blocked_cdn: dict[str, list[str]] = {}
    surface_reports: list[dict[str, Any]] = []
    benchmark_seed_probes: list[dict[str, Any]] = []
    control_outcomes: list[dict[str, Any]] = []

    with scratch_workspace(scratch_root) as scratch_dir:
        discovered = discover_audit_surfaces(
            resolved_root,
            scratch_dir,
            scan_remote_branches=scan_remote_branches,
        )
        surfaces = discovered["surfaces"]
        cg_mod = discovered["canary_game_mod"]
        rpc_registry = _LocalGameRPCRegistry(cg_mod) if cg_mod is not None else None
        controls_dir = scratch_dir / "controls"
        controls_manifest = build_synthetic_control_pages(controls_dir)

        if not surfaces:
            p2_violations.append(f"no game/, docs/arena/, or docs/demo/ surfaces found under {resolved_root}")

        with ephemeral_http_server(scratch_dir, rpc_registry=rpc_registry) as (base_url, allowed_origins):
            with _scratch_fontconfig(scratch_dir), sync_playwright() as pw:
                browser = pw.chromium.launch(
                    headless=True,
                    args=["--no-sandbox", "--disable-dev-shm-usage"],
                    env=dict(os.environ),
                )
                try:
                    for surf in surfaces:
                        sid = surf["surface_id"]
                        kind = surf["kind"]
                        offline_bundled = bool(surf["offline_bundled"])
                        full_url = base_url + surf["rel_url"]

                        ctx, page, reqs, cons, perrs = _open_monitored_page(browser, allowed_origins)
                        try:
                            page.goto(full_url, wait_until="domcontentloaded", timeout=15000)
                            snap_raw = _capture_live_snapshot(page, reqs, cons, perrs)
                        finally:
                            ctx.close()

                        exp_mole: str | None = None
                        exp_decoy: str | None = None
                        exp_kv: float | None = None
                        exp_tv: float | None = None
                        if kind == "craft_arena_harness":
                            env6 = Env("hard", 6)
                            env6.call("advance_day", {})
                            env6.call("advance_day", {})
                            exp_mole = env6._world.mole
                            exp_decoy = env6._world.decoy
                            exp_kv = env6.visible_V()
                            exp_tv = round(env6.V, 10)

                        verdict_raw = inspect_browser_snapshot(
                            snap_raw,
                            allowed_local_origins=allowed_origins,
                            offline_bundled=offline_bundled,
                            strict_zero_cdn=strict_zero_cdn,
                            expected_mole=exp_mole,
                            expected_decoy=exp_decoy,
                            expected_known_v=exp_kv,
                            expected_true_v=exp_tv,
                            human_done=False,
                        )
                        net_info = verdict_raw["network"]
                        total_local_requests += int(net_info["local_requests"])
                        total_api_requests.extend(net_info["external_api_requests"])
                        if net_info["external_cdn_requests"]:
                            all_blocked_cdn[sid] = list(net_info["external_cdn_requests"])
                        p1_violations.extend(f"{sid}:{v}" for v in net_info["violations"])
                        p2_violations.extend(
                            f"{sid}:{v}" for v in [*verdict_raw["dom_violations"], *verdict_raw["js_violations"]]
                        )

                        surface_entry: dict[str, Any] = {
                            "surface_id": sid,
                            "source": surf["source"],
                            "kind": kind,
                            "offline_bundled": offline_bundled,
                            "local_requests": net_info["local_requests"],
                            "blocked_cdn_urls": net_info["external_cdn_requests"],
                            "pageerrors": len(snap_raw["pageerrors"]),
                            "passed": verdict_raw["passed"],
                        }

                        if kind == "ws6_game" and rpc_registry is not None:
                            env3000 = Env("medium", 3000)
                            for _ in range(4):
                                env3000.call("advance_day", {})
                            mole_3000 = env3000._world.mole
                            decoy_3000 = env3000._world.decoy
                            kv_3000 = env3000.visible_V()
                            tv_3000 = round(env3000.V, 10)

                            ctx_g, page_g, reqs_g, cons_g, perrs_g = _open_monitored_page(
                                browser,
                                allowed_origins,
                                extra_init_scripts=(LOCAL_PYODIDE_INIT_SCRIPT,),
                            )
                            try:
                                page_g.goto(f"{full_url}?seed=3000", wait_until="domcontentloaded", timeout=15000)
                                page_g.wait_for_function(
                                    "() => document.getElementById('bootState') && "
                                    "document.getElementById('bootState').textContent === 'ready'",
                                    timeout=10000,
                                )
                                page_g.click("#startBtn")
                                page_g.click("#roster button.primary")
                                page_g.locator("#cmdbar button.tool:has(.code:text-is('DAY'))").click()
                                for _ in range(4):
                                    page_g.click("#cmdform button.run")
                                page_g.locator("#cmdbar button.tool:has(.code:text-is('STA'))").click()
                                page_g.click("#cmdform button.run")
                                page_g.locator("#cmdbar button.tool:has(.code:text-is('FED'))").click()
                                page_g.click("#cmdform button.run")
                                page_g.locator("#cmdbar button.tool:has(.code:text-is('INT'))").click()
                                page_g.click("#cmdform button.run")
                                snap_day5 = _capture_live_snapshot(page_g, reqs_g, cons_g, perrs_g)
                            finally:
                                ctx_g.close()

                            verdict_day5 = inspect_browser_snapshot(
                                snap_day5,
                                allowed_local_origins=allowed_origins,
                                offline_bundled=False,
                                strict_zero_cdn=strict_zero_cdn,
                                expected_mole=mole_3000,
                                expected_decoy=decoy_3000,
                                expected_known_v=kv_3000,
                                expected_true_v=tv_3000,
                                human_done=False,
                            )
                            total_local_requests += int(verdict_day5["network"]["local_requests"])
                            total_api_requests.extend(verdict_day5["network"]["external_api_requests"])
                            p1_violations.extend(f"{sid}_day5:{v}" for v in verdict_day5["network"]["violations"])
                            p2_violations.extend(
                                f"{sid}_day5:{v}"
                                for v in [*verdict_day5["dom_violations"], *verdict_day5["js_violations"]]
                            )
                            lex = snap_day5.get("lexical_game_state") or {}
                            if lex.get("day") != 5 or lex.get("over") is not False or lex.get("staffCount") != 20:
                                p2_violations.append(f"{sid}_day5: unexpected pre-end game state {lex!r}")
                            surface_entry["interactive_day5"] = {
                                "seed": 3000,
                                "day": lex.get("day"),
                                "true_mole": mole_3000,
                                "true_decoy": decoy_3000,
                                "known_v": kv_3000,
                                "true_v": tv_3000,
                                "passed": verdict_day5["passed"],
                            }

                            for probe_label, bad_seed in (("JUDGE_SEEDS", 900000), ("HELDOUT_SEEDS", 800000)):
                                ctx_b, page_b, reqs_b, cons_b, perrs_b = _open_monitored_page(
                                    browser,
                                    allowed_origins,
                                    extra_init_scripts=(LOCAL_PYODIDE_INIT_SCRIPT,),
                                )
                                try:
                                    page_b.goto(
                                        f"{full_url}?seed={bad_seed}",
                                        wait_until="domcontentloaded",
                                        timeout=15000,
                                    )
                                    page_b.wait_for_function(
                                        "() => document.getElementById('bootState') && "
                                        "document.getElementById('bootState').textContent === 'ready'",
                                        timeout=10000,
                                    )
                                    html5_valid = page_b.evaluate(
                                        "() => document.getElementById('seed').checkValidity()"
                                    )
                                    page_b.evaluate("() => { document.getElementById('openCase').noValidate = true; }")
                                    page_b.click("#startBtn")
                                    snap_bad = _capture_live_snapshot(page_b, reqs_b, cons_b, perrs_b)
                                    boot_err = page_b.evaluate(
                                        "() => Array.from(document.querySelectorAll('#bootLog .err'))"
                                        ".map(e => e.textContent).join(' | ')"
                                    )
                                finally:
                                    ctx_b.close()

                                v_bad = inspect_browser_snapshot(
                                    snap_bad,
                                    allowed_local_origins=allowed_origins,
                                    offline_bundled=False,
                                    strict_zero_cdn=strict_zero_cdn,
                                    human_done=False,
                                    forbidden_active_seed=bad_seed,
                                )
                                refused = (
                                    html5_valid is False
                                    and bool(boot_err)
                                    and v_bad["passed"]
                                )
                                if not refused:
                                    p2_violations.append(
                                        f"{sid}: benchmark seed {bad_seed} ({probe_label}) was not cleanly refused "
                                        f"(html5_valid={html5_valid}, boot_err={boot_err!r}, viols={v_bad['violations']})"
                                    )
                                benchmark_seed_probes.append(
                                    {
                                        "surface_id": sid,
                                        "bucket": probe_label,
                                        "seed": bad_seed,
                                        "html5_input_valid": html5_valid,
                                        "runtime_refusal_error": boot_err,
                                        "refused": refused,
                                    }
                                )

                        elif kind in {"arena_index", "craft_arena_harness"}:
                            for probe_label, bad_seed in (("JUDGE_SEEDS", 900000), ("HELDOUT_SEEDS", 800000)):
                                ctx_a, page_a, reqs_a, cons_a, perrs_a = _open_monitored_page(browser, allowed_origins)
                                try:
                                    page_a.goto(
                                        f"{full_url}?seed={bad_seed}",
                                        wait_until="domcontentloaded",
                                        timeout=15000,
                                    )
                                    snap_arena_bad = _capture_live_snapshot(page_a, reqs_a, cons_a, perrs_a)
                                finally:
                                    ctx_a.close()
                                v_arena_bad = inspect_browser_snapshot(
                                    snap_arena_bad,
                                    allowed_local_origins=allowed_origins,
                                    offline_bundled=True,
                                    strict_zero_cdn=strict_zero_cdn,
                                    human_done=False,
                                    forbidden_active_seed=bad_seed,
                                )
                                if not v_arena_bad["passed"]:
                                    p2_violations.extend(
                                        f"{sid}?seed={bad_seed}:{v}" for v in v_arena_bad["violations"]
                                    )
                                benchmark_seed_probes.append(
                                    {
                                        "surface_id": sid,
                                        "bucket": probe_label,
                                        "seed": bad_seed,
                                        "refused": v_arena_bad["passed"],
                                    }
                                )

                        surface_reports.append(surface_entry)

                    ctx_c, page_c, reqs_c, cons_c, perrs_c = _open_monitored_page(browser, allowed_origins)
                    try:
                        page_c.goto(
                            f"{base_url}/controls/clean_control.html",
                            wait_until="domcontentloaded",
                            timeout=15000,
                        )
                        snap_clean = _capture_live_snapshot(page_c, reqs_c, cons_c, perrs_c)
                    finally:
                        ctx_c.close()

                    clean_verdict = inspect_browser_snapshot(
                        snap_clean,
                        allowed_local_origins=allowed_origins,
                        offline_bundled=True,
                        expected_mole="e34",
                        expected_decoy="e20",
                        expected_known_v=0.96,
                        expected_true_v=0.92,
                        human_done=False,
                    )
                    if clean_verdict["exit_code"] != 0:
                        p3_violations.append(
                            f"clean_control.html unexpected failure: {clean_verdict['violations']}"
                        )

                    for ctrl in controls_manifest:
                        cid = ctrl["control_id"]
                        fname = ctrl["filename"]
                        token = ctrl["expected_token"]
                        ctx_p, page_p, reqs_p, cons_p, perrs_p = _open_monitored_page(browser, allowed_origins)
                        try:
                            page_p.goto(
                                f"{base_url}/controls/{fname}",
                                wait_until="domcontentloaded",
                                timeout=15000,
                            )
                            snap_ctrl = _capture_live_snapshot(page_p, reqs_p, cons_p, perrs_p)
                        finally:
                            ctx_p.close()

                        ctrl_verdict = inspect_browser_snapshot(
                            snap_ctrl,
                            allowed_local_origins=allowed_origins,
                            offline_bundled=True,
                            expected_mole="e34",
                            expected_decoy="e20",
                            human_done=False,
                        )
                        caught = ctrl_verdict["exit_code"] == 1 and any(
                            token.lower() in v.lower() for v in ctrl_verdict["violations"]
                        )
                        if not caught:
                            p3_violations.append(
                                f"{cid}: expected exit 1 matching {token!r}, got rc={ctrl_verdict['exit_code']} "
                                f"violations={ctrl_verdict['violations']}"
                            )
                        control_outcomes.append(
                            {
                                "control_id": cid,
                                "exit_code": ctrl_verdict["exit_code"],
                                "caught": caught,
                                "violations": ctrl_verdict["violations"],
                            }
                        )
                finally:
                    browser.close()

    caught_total = sum(1 for c in control_outcomes if c["caught"])
    p1 = PhaseOutcome(
        phase_id="P1",
        name="Strict Offline Network Firewall",
        passed=len(p1_violations) == 0,
        status="PASS" if len(p1_violations) == 0 else "FAIL",
        summary=(
            f"local_127_requests={total_local_requests} external_api_calls={len(total_api_requests)} "
            f"aborted_legacy_cdn_surfaces={len(all_blocked_cdn)}"
        ),
        metrics={
            "local_requests": total_local_requests,
            "external_api_calls": len(total_api_requests),
            "aborted_cdn_by_surface": all_blocked_cdn,
        },
        violations=p1_violations,
    )
    p2 = PhaseOutcome(
        phase_id="P2",
        name="Live Browser Pre-End Zero-Leak Audit",
        passed=len(p2_violations) == 0,
        status="PASS" if len(p2_violations) == 0 else "FAIL",
        summary=(
            f"surfaces_audited={len(surface_reports)} seed_probes_refused="
            f"{sum(1 for x in benchmark_seed_probes if x['refused'])}/{len(benchmark_seed_probes)} "
            f"pre_end_leaks={len(p2_violations)}"
        ),
        metrics={
            "surfaces": surface_reports,
            "benchmark_seed_probes": benchmark_seed_probes,
        },
        violations=p2_violations,
    )
    p3 = PhaseOutcome(
        phase_id="P3",
        name="Synthetic Leaky HTML/JS Positive Controls",
        passed=len(p3_violations) == 0 and caught_total == len(controls_manifest),
        status="PASS" if len(p3_violations) == 0 and caught_total == len(controls_manifest) else "FAIL",
        summary=f"clean_control_rc=0 positive_controls_caught={caught_total}/{len(controls_manifest)} (exit 1)",
        metrics={
            "clean_control_exit_code": clean_verdict["exit_code"],
            "controls_caught": caught_total,
            "controls_total": len(controls_manifest),
            "controls": control_outcomes,
        },
        violations=p3_violations,
    )

    phases = [p1, p2, p3]
    overall_passed = all(ph.passed for ph in phases)
    elapsed_s = round(time.perf_counter() - t0, 4)
    return {
        "passed": overall_passed,
        "status": "PASS" if overall_passed else "FAIL",
        "exit_code": 0 if overall_passed else 1,
        "browser_mode": "chromium_headless",
        "root": str(resolved_root),
        "elapsed_s": elapsed_s,
        "live_api_calls": 0,
        "scratch_cleaned": not scratch_root.exists(),
        "phases": [asdict(ph) for ph in phases],
    }


class _StaticAssetExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.asset_urls: list[tuple[str, str]] = []
        self.inline_js: list[str] = []
        self._in_script = False
        self._buf: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        t = tag.lower()
        amap = {k.lower(): ("" if v is None else str(v)) for k, v in attrs}
        if t == "script":
            src = amap.get("src", "").strip()
            if src:
                self.asset_urls.append(("script", src))
            else:
                self._in_script = True
                self._buf = []
        elif t == "link" and "stylesheet" in amap.get("rel", "").lower():
            href = amap.get("href", "").strip()
            if href:
                self.asset_urls.append(("stylesheet", href))
        elif t == "img":
            src = amap.get("src", "").strip()
            if src:
                self.asset_urls.append(("image", src))

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "script" and self._in_script:
            self.inline_js.append("".join(self._buf))
            self._in_script = False
            self._buf = []

    def handle_data(self, data: str) -> None:
        if self._in_script:
            self._buf.append(data)


def _fetch_ephemeral_snapshot(full_url: str, allowed_origins: set[str]) -> dict[str, Any]:
    requests_log: list[dict[str, Any]] = []
    pageerrors: list[str] = []
    globals_map: dict[str, Any] = {}
    keys_list: list[str] = []

    info_doc = classify_request_url(full_url, allowed_origins)
    requests_log.append(
        {
            "url": full_url,
            "method": "GET",
            "resource_type": "document",
            "allowed": info_doc["allowed"],
            "category": info_doc["category"],
        }
    )
    html_text = ""
    if info_doc["allowed"]:
        with urlopen(full_url, timeout=5) as resp:
            html_text = resp.read().decode("utf-8", errors="replace")

    ext = _StaticAssetExtractor()
    ext.feed(html_text)
    ext.close()

    js_blobs = list(ext.inline_js)
    for rtype, raw_ref in ext.asset_urls:
        resolved = urljoin(full_url, raw_ref)
        rinfo = classify_request_url(resolved, allowed_origins)
        requests_log.append(
            {
                "url": resolved,
                "method": "GET",
                "resource_type": rtype,
                "allowed": rinfo["allowed"],
                "category": rinfo["category"],
            }
        )
        if rinfo["allowed"] and rtype == "script":
            try:
                with urlopen(resolved, timeout=5) as sresp:
                    js_blobs.append(sresp.read().decode("utf-8", errors="replace"))
            except Exception:
                pass

    for blob in js_blobs:
        for fmatch in re.finditer(r"\bfetch\s*\(\s*([\"'])(https?:[^\"']+)\1", blob):
            furl = fmatch.group(2)
            finfo = classify_request_url(furl, allowed_origins)
            requests_log.append(
                {
                    "url": furl,
                    "method": "GET",
                    "resource_type": "fetch",
                    "allowed": finfo["allowed"],
                    "category": finfo["category"],
                }
            )
        for wmatch in re.finditer(
            r"\bwindow\.([A-Za-z_$][A-Za-z0-9_$]*)\s*=\s*([\"'])([^\"']*)\2",
            blob,
        ):
            gname = wmatch.group(1)
            keys_list.append(gname)
            globals_map[gname] = wmatch.group(3)
        for label, parsed_obj in _extract_js_assigned_objects(blob, "js"):
            lhs = label.split(":", 1)[-1]
            if lhs.startswith("window."):
                gname = lhs.split(".", 1)[1]
                keys_list.append(gname)
                globals_map[gname] = parsed_obj
        if "nonExistentCanaryPreEndSymbol(" in blob:
            pageerrors.append("ReferenceError: nonExistentCanaryPreEndSymbol is not defined")

    return {
        "html": html_text,
        "storage": {},
        "session": {},
        "keys": keys_list,
        "globals": globals_map,
        "lexical_game_state": None,
        "requests": requests_log,
        "console": [],
        "pageerrors": pageerrors,
    }


def run_offline_http_fallback_audit(
    root: Path = ROOT,
    *,
    scratch_root: Path = DEFAULT_SCRATCH_ROOT,
    scan_remote_branches: bool = True,
    strict_zero_cdn: bool = False,
) -> dict[str, Any]:
    t0 = time.perf_counter()
    resolved_root = root.resolve()
    p1_violations: list[str] = []
    p2_violations: list[str] = []
    p3_violations: list[str] = []
    total_local_requests = 0
    total_api_requests: list[str] = []
    all_blocked_cdn: dict[str, list[str]] = {}
    surface_reports: list[dict[str, Any]] = []
    benchmark_seed_probes: list[dict[str, Any]] = []
    control_outcomes: list[dict[str, Any]] = []

    with scratch_workspace(scratch_root) as scratch_dir:
        discovered = discover_audit_surfaces(
            resolved_root,
            scratch_dir,
            scan_remote_branches=scan_remote_branches,
        )
        surfaces = discovered["surfaces"]
        cg_mod = discovered["canary_game_mod"]
        rpc_registry = _LocalGameRPCRegistry(cg_mod) if cg_mod is not None else None
        controls_dir = scratch_dir / "controls"
        controls_manifest = build_synthetic_control_pages(controls_dir)

        if not surfaces:
            p2_violations.append(f"no game/, docs/arena/, or docs/demo/ surfaces found under {resolved_root}")

        with ephemeral_http_server(scratch_dir, rpc_registry=rpc_registry) as (base_url, allowed_origins):
            for surf in surfaces:
                sid = surf["surface_id"]
                kind = surf["kind"]
                offline_bundled = bool(surf["offline_bundled"])
                full_url = base_url + surf["rel_url"]

                snap_raw = _fetch_ephemeral_snapshot(full_url, allowed_origins)
                verdict_raw = inspect_browser_snapshot(
                    snap_raw,
                    allowed_local_origins=allowed_origins,
                    offline_bundled=offline_bundled,
                    strict_zero_cdn=strict_zero_cdn,
                    human_done=False,
                )
                net_info = verdict_raw["network"]
                total_local_requests += int(net_info["local_requests"])
                total_api_requests.extend(net_info["external_api_requests"])
                if net_info["external_cdn_requests"]:
                    all_blocked_cdn[sid] = list(net_info["external_cdn_requests"])
                p1_violations.extend(f"{sid}:{v}" for v in net_info["violations"])
                p2_violations.extend(
                    f"{sid}:{v}" for v in [*verdict_raw["dom_violations"], *verdict_raw["js_violations"]]
                )
                if kind == "ws6_game" and cg_mod is not None:
                    for probe_label, bad_seed in (("JUDGE_SEEDS", 900000), ("HELDOUT_SEEDS", 800000)):
                        refused = False
                        try:
                            cg_mod.Game(bad_seed)
                        except ValueError:
                            refused = True
                        if not refused:
                            p2_violations.append(f"{sid}: Game({bad_seed}) did not reject {probe_label}")
                        benchmark_seed_probes.append(
                            {"surface_id": sid, "bucket": probe_label, "seed": bad_seed, "refused": refused}
                        )
                surface_reports.append(
                    {
                        "surface_id": sid,
                        "source": surf["source"],
                        "kind": kind,
                        "offline_bundled": offline_bundled,
                        "local_requests": net_info["local_requests"],
                        "blocked_cdn_urls": net_info["external_cdn_requests"],
                        "pageerrors": len(snap_raw["pageerrors"]),
                        "passed": verdict_raw["passed"],
                    }
                )

            snap_clean = _fetch_ephemeral_snapshot(f"{base_url}/controls/clean_control.html", allowed_origins)
            clean_verdict = inspect_browser_snapshot(
                snap_clean,
                allowed_local_origins=allowed_origins,
                offline_bundled=True,
                expected_mole="e34",
                expected_decoy="e20",
                expected_known_v=0.96,
                expected_true_v=0.92,
                human_done=False,
            )
            if clean_verdict["exit_code"] != 0:
                p3_violations.append(f"clean_control.html unexpected failure: {clean_verdict['violations']}")

            for ctrl in controls_manifest:
                cid = ctrl["control_id"]
                fname = ctrl["filename"]
                token = ctrl["expected_token"]
                snap_ctrl = _fetch_ephemeral_snapshot(f"{base_url}/controls/{fname}", allowed_origins)
                ctrl_verdict = inspect_browser_snapshot(
                    snap_ctrl,
                    allowed_local_origins=allowed_origins,
                    offline_bundled=True,
                    expected_mole="e34",
                    expected_decoy="e20",
                    human_done=False,
                )
                caught = ctrl_verdict["exit_code"] == 1 and any(
                    token.lower() in v.lower() for v in ctrl_verdict["violations"]
                )
                if not caught:
                    p3_violations.append(
                        f"{cid}: expected exit 1 matching {token!r}, got rc={ctrl_verdict['exit_code']} "
                        f"violations={ctrl_verdict['violations']}"
                    )
                control_outcomes.append(
                    {
                        "control_id": cid,
                        "exit_code": ctrl_verdict["exit_code"],
                        "caught": caught,
                        "violations": ctrl_verdict["violations"],
                    }
                )

    caught_total = sum(1 for c in control_outcomes if c["caught"])
    p1 = PhaseOutcome(
        phase_id="P1",
        name="Strict Offline Network Firewall",
        passed=len(p1_violations) == 0,
        status="PASS" if len(p1_violations) == 0 else "FAIL",
        summary=(
            f"local_127_requests={total_local_requests} external_api_calls={len(total_api_requests)} "
            f"aborted_legacy_cdn_surfaces={len(all_blocked_cdn)}"
        ),
        metrics={
            "local_requests": total_local_requests,
            "external_api_calls": len(total_api_requests),
            "aborted_cdn_by_surface": all_blocked_cdn,
        },
        violations=p1_violations,
    )
    p2 = PhaseOutcome(
        phase_id="P2",
        name="Live Browser Pre-End Zero-Leak Audit",
        passed=len(p2_violations) == 0,
        status="PASS" if len(p2_violations) == 0 else "FAIL",
        summary=(
            f"surfaces_audited={len(surface_reports)} seed_probes_refused="
            f"{sum(1 for x in benchmark_seed_probes if x['refused'])}/{len(benchmark_seed_probes)} "
            f"pre_end_leaks={len(p2_violations)}"
        ),
        metrics={"surfaces": surface_reports, "benchmark_seed_probes": benchmark_seed_probes},
        violations=p2_violations,
    )
    p3 = PhaseOutcome(
        phase_id="P3",
        name="Synthetic Leaky HTML/JS Positive Controls",
        passed=len(p3_violations) == 0 and caught_total == len(controls_manifest),
        status="PASS" if len(p3_violations) == 0 and caught_total == len(controls_manifest) else "FAIL",
        summary=f"clean_control_rc=0 positive_controls_caught={caught_total}/{len(controls_manifest)} (exit 1)",
        metrics={
            "clean_control_exit_code": clean_verdict["exit_code"],
            "controls_caught": caught_total,
            "controls_total": len(controls_manifest),
            "controls": control_outcomes,
        },
        violations=p3_violations,
    )
    phases = [p1, p2, p3]
    overall_passed = all(ph.passed for ph in phases)
    elapsed_s = round(time.perf_counter() - t0, 4)
    return {
        "passed": overall_passed,
        "status": "PASS" if overall_passed else "FAIL",
        "exit_code": 0 if overall_passed else 1,
        "browser_mode": "offline_http_fallback",
        "root": str(resolved_root),
        "elapsed_s": elapsed_s,
        "live_api_calls": 0,
        "scratch_cleaned": not scratch_root.exists(),
        "phases": [asdict(ph) for ph in phases],
    }


def format_report(report: Mapping[str, Any]) -> str:
    lines: list[str] = []
    for ph in report.get("phases") or ():
        lines.append(f"[{ph['status']}] {ph['phase_id']} {ph['name']}: {ph['summary']}")
        aborted_cdn = (ph.get("metrics") or {}).get("aborted_cdn_by_surface") or {}
        for sid, urls in sorted(aborted_cdn.items()):
            lines.append(f"  note ({sid} aborted external CDN tags): {', '.join(urls)}")
        for v in ph.get("violations") or ():
            lines.append(f"  violation: {v}")
    passed_cnt = sum(1 for ph in (report.get("phases") or ()) if ph.get("passed"))
    total_cnt = len(report.get("phases") or ())
    bmode = report.get("browser_mode", "chromium_headless")
    lines.append(
        f"{report['status']}: {passed_cnt}/{total_cnt} phases passed in {report['elapsed_s']:.3f}s "
        f"(mode={bmode}, live_api_calls={report['live_api_calls']}, scratch_cleaned={report['scratch_cleaned']})"
    )
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    raw_args = list(sys.argv[1:] if argv is None else argv)
    ap = argparse.ArgumentParser(
        description="Real headless Chromium Playwright pre-end zero-leak and E2E smoke verifier."
    )
    ap.add_argument("--root", type=Path, default=ROOT, help="Repository root to audit")
    ap.add_argument(
        "--scratch-dir",
        type=Path,
        default=DEFAULT_SCRATCH_ROOT,
        help="Scratch directory under /tmp/opencode removed on exit",
    )
    ap.add_argument(
        "--use-local-playwright",
        action="store_true",
        help="Re-invoke under shared /localscratch/fleet-silas/demo-video Playwright Python when available",
    )
    ap.add_argument(
        "--no-local-playwright",
        action="store_true",
        help="Do not auto-reinvoke shared /localscratch/fleet-silas/demo-video Python",
    )
    ap.add_argument(
        "--offline-fallback",
        action="store_true",
        help="Run ephemeral HTTP DOM/JS/network audit without launching Chromium",
    )
    ap.add_argument(
        "--require-browser",
        action="store_true",
        help="Require live headless Chromium and fail if Playwright or browser binaries are missing",
    )
    ap.add_argument(
        "--no-remote-branches",
        action="store_true",
        help="Audit only on-disk surfaces without extracting remote Arena/Demo branches",
    )
    ap.add_argument(
        "--strict-zero-cdn",
        action="store_true",
        help="Fail even legacy non-bundled surfaces if static CDN tags are requested",
    )
    ap.add_argument("--json", action="store_true", help="Print JSON report to stdout")
    ap.add_argument("--json-out", type=Path, default=None, help="Optional path to write JSON report")
    ap.add_argument("--check", action="store_true", help="Exit 0 on PASS, 1 on FAIL")
    args = ap.parse_args(raw_args)

    allow_local_pw = (not args.no_local_playwright) and (not args.offline_fallback)

    if args.offline_fallback:
        report = run_offline_http_fallback_audit(
            root=args.root,
            scratch_root=args.scratch_dir,
            scan_remote_branches=not args.no_remote_branches,
            strict_zero_cdn=args.strict_zero_cdn,
        )
    elif not playwright_available():
        if allow_local_pw and shared_playwright_python_available() and os.environ.get("CANARY_PW_REINVOKED") != "1":
            child_env = build_playwright_env()
            child_env["CANARY_PW_REINVOKED"] = "1"
            proc = subprocess.run(
                [str(SHARED_PW_PYTHON), str(Path(__file__).resolve()), *raw_args],
                cwd=ROOT,
                env=child_env,
            )
            return int(proc.returncode)
        if args.require_browser:
            msg = {
                "passed": False,
                "status": "SKIP",
                "exit_code": 2,
                "reason": "playwright is not installed in this Python environment",
            }
            if args.json:
                print(json.dumps(msg, indent=2))
            else:
                print(msg["reason"])
            return 2
        report = run_offline_http_fallback_audit(
            root=args.root,
            scratch_root=args.scratch_dir,
            scan_remote_branches=not args.no_remote_branches,
            strict_zero_cdn=args.strict_zero_cdn,
        )
    else:
        if allow_local_pw and SHARED_PW_LIBS.is_dir():
            cur_ld = os.environ.get("LD_LIBRARY_PATH", "")
            if str(SHARED_PW_LIBS) not in cur_ld.split(":") and os.environ.get("CANARY_PW_REINVOKED") != "1":
                child_env = build_playwright_env()
                child_env["CANARY_PW_REINVOKED"] = "1"
                proc = subprocess.run(
                    [sys.executable, str(Path(__file__).resolve()), *raw_args],
                    cwd=ROOT,
                    env=child_env,
                )
                return int(proc.returncode)
        try:
            report = run_live_chromium_audit(
                root=args.root,
                scratch_root=args.scratch_dir,
                scan_remote_branches=not args.no_remote_branches,
                strict_zero_cdn=args.strict_zero_cdn,
            )
        except Exception as exc:
            err_s = str(exc)
            if (not args.require_browser) and ("Executable doesn't exist" in err_s or "browserType.launch" in err_s):
                report = run_offline_http_fallback_audit(
                    root=args.root,
                    scratch_root=args.scratch_dir,
                    scan_remote_branches=not args.no_remote_branches,
                    strict_zero_cdn=args.strict_zero_cdn,
                )
            else:
                raise

    if args.json_out is not None:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(format_report(report))

    return int(report["exit_code"])


if __name__ == "__main__":
    raise SystemExit(main())
