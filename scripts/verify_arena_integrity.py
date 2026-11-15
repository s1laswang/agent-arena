from __future__ import annotations

import argparse
import contextlib
import importlib.util
import json
import math
import os
import re
import secrets
import shutil
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterator

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from canary.env import Env
from canary.rules import DEV_SEEDS, HELDOUT_SEEDS, JUDGE_SEEDS

DEFAULT_SCRATCH = Path("/tmp/opencode/integrity_w5_scratch")
BENCHMARK_HELDOUT_30 = range(800_000, 800_030)
COMMITTED_HARD_REL = Path("data/runs/committed/v1.4/opencode-gemini-4-carbon/hard/episodes.jsonl")

GOOGLE_KEY_PREFIX = "AI" + "za"
SK_KEY_PREFIX = "s" + "k-"
OAUTH_PREFIX = "ya" + "29."
HF_PREFIX = "h" + "f_"
XAI_PREFIX = "xa" + "i-"
GH_PREFIX = "gh"
GOOG_HDR = "x-goog-" + "api-key"

CREDENTIAL_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("google_api_key", re.compile(r"(?<![0-9A-Za-z+/_-])" + re.escape(GOOGLE_KEY_PREFIX) + r"[0-9A-Za-z_-]{20,}")),
    (
        "sk_api_key",
        re.compile(
            r"(?<![0-9A-Za-z+/_-])"
            + re.escape(SK_KEY_PREFIX)
            + r"(?:proj-|ant-|live-|test-|svcacct-)?[0-9A-Za-z_-]{16,}"
        ),
    ),
    ("google_oauth", re.compile(re.escape(OAUTH_PREFIX) + r"[0-9A-Za-z_-]{20,}")),
    ("hf_token", re.compile(re.escape(HF_PREFIX) + r"[A-Za-z0-9]{24,}")),
    ("xai_key", re.compile(re.escape(XAI_PREFIX) + r"[A-Za-z0-9_-]{24,}")),
    ("github_pat", re.compile(GH_PREFIX + r"[pousr]_[A-Za-z0-9]{24,}")),
    ("gateway_header_key", re.compile(r'"' + re.escape(GOOG_HDR) + r'"\s*:\s*"[^"\s]{8,}"', re.IGNORECASE)),
)

SECRET_NAMES = (
    "SALT",
    "CANARY_WORLD_SECRET",
    "CANARY_LEDGER_TOKEN",
    "CANARY_ADMIN_TOKEN",
    "CANARY_LEDGER_KEY",
    "GEMINI_API_KEY",
    "GOOGLE_API_KEY",
    "GOOGLE_GENERATIVE_AI_API_KEY",
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
)

SECRET_ASSIGN_RE = re.compile(
    r"""(?:["']?(?:"""
    + "|".join(SECRET_NAMES)
    + r""")["']?\s*[:=]\s*["'][A-Za-z0-9_./+=-]{6,}["'])"""
)
DOTENV_SECRET_RE = re.compile(
    r"(?:^|\n)\s*(?:" + "|".join(SECRET_NAMES) + r")\s*=\s*[^\s\"']{6,}"
)
STRICT_LITERAL_NAMES_RE = re.compile(
    r"\b(?:CANARY_WORLD_SECRET|CANARY_LEDGER_TOKEN)\b|data/worlds/judge/SALT"
)

ALLOWED_ENV_TEMPLATES = frozenset({".env.example", ".env.sample", ".env.template"})
FORBIDDEN_SECRET_FILENAMES = frozenset({"SALT", "ledger_key", ".env"})
FORBIDDEN_MANIFEST_TOKENS = (
    "redteam",
    "mcp_server.py",
    "gemini",
    "forge_track.py",
    "harbor",
    "SALT",
    "ledger_key",
    "committed",
    ".env",
)

PRE_END_TRUTH_KEYS = frozenset(
    {
        "mole",
        "true_mole",
        "mole_id",
        "decoy",
        "true_decoy",
        "decoy_id",
        "correct",
        "accused_correct",
        "world_seed",
        "_world",
    }
)
SPRITE_LEAK_KEYS = frozenset(
    {
        "leaking_sprite_employee",
        "mole_sprite",
        "culprit_sprite",
        "leaker_employee",
    }
)
MOLE_MODES = frozenset({"be_the_mole", "mole", "mode3", "mode_3", "play_mole", "play_as_mole"})
STEP_COLLECTION_KEYS = frozenset(
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
POST_END_CONTAINER_KEYS = frozenset(
    {
        "reveal",
        "verdict",
        "final",
        "outcome",
        "terminal",
        "post_game",
        "post_end",
        "case_closed",
        "sealed",
        "sealed_reveal",
        "end_reveal",
        "commitment",
    }
)
EMP_ID_RE = re.compile(r"^e\d{2,3}$")
WINDOW_ASSIGN_RE = re.compile(
    r"(?:\b(?:window|globalThis|self)\.[A-Za-z_$][A-Za-z0-9_$]*|\b(?:const|let|var)\s+[A-Z][A-Z0-9_]{2,})\s*=\s*"
)
HTML_JSON_SCRIPT_RE = re.compile(
    r"<script[^>]*type=[\"']application/(?:ld\+)?json[\"'][^>]*>(.*?)</script>",
    re.IGNORECASE | re.DOTALL,
)
HTML_SCRIPT_RE = re.compile(r"<script[^>]*>(.*?)</script>", re.IGNORECASE | re.DOTALL)
AUTO_STATUS_JS_RE = re.compile(
    r"""(?:call_json|run)\s*\(\s*["']status["']""",
)


@dataclass
class CheckOutcome:
    check_id: str
    name: str
    passed: bool
    status: str
    summary: str
    metrics: dict[str, Any] = field(default_factory=dict)
    violations: list[str] = field(default_factory=list)


@contextlib.contextmanager
def _scratch_workdir(scratch_root: Path | None, prefix: str) -> Iterator[Path]:
    base = scratch_root if scratch_root is not None else DEFAULT_SCRATCH
    base.mkdir(parents=True, exist_ok=True)
    work = base / f"{prefix}-{secrets.token_hex(6)}"
    work.mkdir(parents=True, exist_ok=True)
    try:
        yield work
    finally:
        shutil.rmtree(work, ignore_errors=True)
        if scratch_root is None and DEFAULT_SCRATCH.exists():
            try:
                DEFAULT_SCRATCH.rmdir()
            except OSError:
                pass


def _load_python_module(mod_name: str, file_path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(mod_name, file_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load module from {file_path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _iter_surface_files(surface_dir: Path, skip_dirs: frozenset[str] = frozenset()) -> list[Path]:
    if not surface_dir.is_dir():
        return []
    out: list[Path] = []
    for p in sorted(surface_dir.rglob("*")):
        if not p.is_file():
            continue
        rel_parts = p.relative_to(surface_dir).parts
        if any(part in skip_dirs or part == "__pycache__" for part in rel_parts):
            continue
        if p.suffix in {".pyc", ".pyo"}:
            continue
        out.append(p)
    return out


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


def _extract_js_json_Payloads(js_text: str, source_label: str) -> list[tuple[str, Any]]:
    decoder = json.JSONDecoder()
    extracted: list[tuple[str, Any]] = []
    for match in WINDOW_ASSIGN_RE.finditer(js_text):
        pos = match.end()
        while pos < len(js_text) and js_text[pos].isspace():
            pos += 1
        if pos >= len(js_text) or js_text[pos] not in "{[":
            continue
        try:
            obj, _ = decoder.raw_decode(js_text, pos)
            lhs = match.group(0).split("=")[0].strip()
            extracted.append((f"{source_label}:{lhs}", obj))
        except json.JSONDecodeError:
            continue
    return extracted


def extract_bundle_payloads(file_path: Path, rel_label: str) -> tuple[list[tuple[str, Any]], list[str]]:
    payloads: list[tuple[str, Any]] = []
    parse_errors: list[str] = []
    suffix = file_path.suffix.lower()
    if suffix not in {".json", ".jsonl", ".js", ".mjs", ".html"}:
        return payloads, parse_errors
    try:
        text = file_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        if suffix in {".json", ".jsonl"}:
            parse_errors.append(f"{rel_label}: unreadable UTF-8 ({type(exc).__name__})")
        return payloads, parse_errors

    if suffix == ".json":
        try:
            payloads.append((rel_label, json.loads(text)))
        except json.JSONDecodeError as exc:
            parse_errors.append(f"{rel_label}: invalid JSON ({exc.msg} at line {exc.lineno})")
    elif suffix == ".jsonl":
        for lineno, line in enumerate(text.splitlines(), 1):
            if not line.strip():
                continue
            try:
                payloads.append((f"{rel_label}:{lineno}", json.loads(line)))
            except json.JSONDecodeError as exc:
                parse_errors.append(f"{rel_label}:{lineno}: invalid JSONL ({exc.msg})")
    elif suffix in {".js", ".mjs"}:
        payloads.extend(_extract_js_json_Payloads(text, rel_label))
    elif suffix == ".html":
        for idx, match in enumerate(HTML_JSON_SCRIPT_RE.finditer(text)):
            body = match.group(1).strip()
            if not body:
                continue
            try:
                payloads.append((f"{rel_label}:json_script[{idx}]", json.loads(body)))
            except json.JSONDecodeError as exc:
                parse_errors.append(f"{rel_label}:json_script[{idx}]: invalid JSON ({exc.msg})")
        for idx, match in enumerate(HTML_SCRIPT_RE.finditer(text)):
            body = match.group(1)
            payloads.extend(_extract_js_json_Payloads(body, f"{rel_label}:script[{idx}]"))
    return payloads, parse_errors


def _is_int_seed(val: Any) -> bool:
    return isinstance(val, int) and not isinstance(val, bool)


def _is_benchmark_seed(seed_val: int) -> str | None:
    if seed_val in JUDGE_SEEDS:
        return "JUDGE_SEEDS"
    if seed_val in HELDOUT_SEEDS:
        return "HELDOUT_SEEDS"
    return None


def collect_bundle_seed_violations(obj: Any, loc: str) -> list[str]:
    violations: list[str] = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            ks = str(k)
            child_loc = f"{loc}.{ks}"
            if ks in {"seed", "case_seed", "episode_seed"} and _is_int_seed(v):
                bucket = _is_benchmark_seed(int(v))
                if bucket is not None:
                    violations.append(f"{child_loc}: ships forbidden {bucket} seed {v}")
            elif ks in {"seeds", "case_seeds", "episode_seeds"} and isinstance(v, list):
                for idx, item in enumerate(v):
                    if _is_int_seed(item):
                        bucket = _is_benchmark_seed(int(item))
                        if bucket is not None:
                            violations.append(f"{child_loc}[{idx}]: ships forbidden {bucket} seed {item}")
            elif ks.isdigit():
                bucket = _is_benchmark_seed(int(ks))
                if bucket is not None:
                    violations.append(f"{child_loc}: ships forbidden {bucket} key {ks}")
            violations.extend(collect_bundle_seed_violations(v, child_loc))
    elif isinstance(obj, list):
        for idx, item in enumerate(obj):
            violations.extend(collect_bundle_seed_violations(item, f"{loc}[{idx}]"))
    return violations


_DAY_V_CACHE: dict[tuple[str, int], dict[int, tuple[float, float]]] = {}


def _day_open_v_table(tier: str, seed: int) -> dict[int, tuple[float, float]]:
    key = (tier, seed)
    if key in _DAY_V_CACHE:
        return _DAY_V_CACHE[key]
    if tier not in {"easy", "medium", "hard"} or seed not in DEV_SEEDS:
        return {}
    env = Env(tier, seed)
    table: dict[int, tuple[float, float]] = {1: (round(env.V, 10), env.visible_V())}
    while not env.done:
        res = env.call("advance_day", {})
        if not res.ok or env.done:
            break
        table[env.day] = (round(env.V, 10), env.visible_V())
    _DAY_V_CACHE[key] = table
    return table


def _is_finite_float(val: Any) -> bool:
    return isinstance(val, (int, float)) and not isinstance(val, bool) and math.isfinite(float(val))


def _is_sealed_token(val: Any) -> bool:
    return isinstance(val, str) and (
        val.startswith("sha256:")
        or val.startswith("sealed:")
        or val.startswith("xor:")
        or val.startswith("b64:")
        or val == "[SEALED]"
    )


def _step_done_flag(node: dict[str, Any]) -> bool:
    if node.get("done") is True or node.get("episode_over") is True:
        return True
    res = node.get("result")
    if isinstance(res, dict):
        data = res.get("data")
        if isinstance(data, dict) and data.get("episode_over") is True:
            return True
    return False


@dataclass
class _ScanCtx:
    tier: str | None = None
    seed: int | None = None
    day: int | None = None
    mode: str = ""
    human_done: bool | None = None
    pre_end: bool = False
    allow_investigator_doc_canary: bool = False
    expected_known_v: float | None = None
    expected_true_v: float | None = None


def _check_v_exposure(node: dict[str, Any], loc: str, ctx: _ScanCtx) -> list[str]:
    violations: list[str] = []
    if node.get("done") is True:
        return violations

    for tv_key in ("true_v", "true_V"):
        if tv_key in node and _is_finite_float(node[tv_key]):
            kv_raw = node.get("known_v", node.get("known_V"))
            if _is_finite_float(kv_raw):
                if abs(float(node[tv_key]) - float(kv_raw)) > 1e-9:
                    violations.append(
                        f"{loc}.{tv_key}: exposes unsurfaced true_v ({tv_key}={node[tv_key]} != known_v={kv_raw})"
                    )
                else:
                    violations.append(f"{loc}.{tv_key}: exposes raw true_v field before episode end")
            else:
                violations.append(f"{loc}.{tv_key}: exposes raw true_v field before episode end")

    shown_candidates: list[tuple[str, float]] = []
    for k in ("V", "hud_v", "display_v", "shown_v", "visible_v"):
        if k in node and _is_finite_float(node[k]):
            shown_candidates.append((k, float(node[k])))
    for sub_name in ("hud", "vitals"):
        sub = node.get(sub_name)
        if isinstance(sub, dict) and sub.get("done") is not True:
            for tv_key in ("true_v", "true_V"):
                if tv_key in sub and _is_finite_float(sub[tv_key]):
                    violations.append(f"{loc}.{sub_name}.{tv_key}: exposes raw {tv_key} in pre-end HUD")
            for k in ("V", "hud_v", "display_v", "shown_v", "visible_v", "value"):
                if k in sub and _is_finite_float(sub[k]):
                    shown_candidates.append((f"{sub_name}.{k}", float(sub[k])))

    kv_explicit = node.get("known_v", node.get("known_V"))
    if not _is_finite_float(kv_explicit) and isinstance(node.get("hud"), dict):
        kv_explicit = node["hud"].get("known_v", node["hud"].get("known_V"))

    for field_label, shown_val in shown_candidates:
        if _is_finite_float(kv_explicit) and abs(shown_val - float(kv_explicit)) > 1e-9:
            violations.append(
                f"{loc}.{field_label}: pre-end V={shown_val} exposes unsurfaced true_v != known_v={float(kv_explicit)}"
            )
            continue
        if (
            ctx.expected_known_v is not None
            and ctx.expected_true_v is not None
            and abs(ctx.expected_true_v - ctx.expected_known_v) > 1e-9
            and abs(shown_val - ctx.expected_known_v) > 1e-9
        ):
            violations.append(
                f"{loc}.{field_label}: pre-end V={shown_val} exposes unsurfaced true_v "
                f"(expected known_v={ctx.expected_known_v}, true_v={ctx.expected_true_v})"
            )
            continue
        day_val = node.get("day") if _is_int_seed(node.get("day")) else ctx.day
        tier_val = str(node.get("tier") or ctx.tier or "")
        seed_val = node.get("seed") if _is_int_seed(node.get("seed")) else ctx.seed
        has_known_costs = bool(node.get("canaries_planted") or node.get("restricted"))
        if (
            ctx.expected_known_v is None
            and not has_known_costs
            and not loc.endswith(".result.data")
            and "tool" not in node
            and tier_val in {"easy", "medium", "hard"}
            and _is_int_seed(seed_val)
            and _is_int_seed(day_val)
        ):
            v_tbl = _day_open_v_table(tier_val, int(seed_val))
            if int(day_val) in v_tbl:
                day_tv, day_kv = v_tbl[int(day_val)]
                if abs(day_tv - day_kv) > 1e-9 and abs(shown_val - day_tv) < 1e-9:
                    violations.append(
                        f"{loc}.{field_label}: pre-end HUD V={shown_val} exposes unsurfaced true_v "
                        f"instead of known_v={day_kv} on {tier_val}:{seed_val} day {day_val}"
                    )
    return violations


def _scan_node(node: Any, loc: str, ctx: _ScanCtx) -> list[str]:
    violations: list[str] = []
    if isinstance(node, list):
        for idx, item in enumerate(node):
            violations.extend(_scan_node(item, f"{loc}[{idx}]", ctx))
        return violations
    if not isinstance(node, dict):
        return violations

    tier = str(node["tier"]) if isinstance(node.get("tier"), str) else ctx.tier
    seed = int(node["seed"]) if _is_int_seed(node.get("seed")) else ctx.seed
    day = int(node["day"]) if _is_int_seed(node.get("day")) else ctx.day
    raw_mode = node.get("mode") or node.get("game_mode")
    mode = str(raw_mode).strip().lower() if isinstance(raw_mode, str) else ctx.mode
    human_done = node["human_done"] if isinstance(node.get("human_done"), bool) else ctx.human_done

    explicit_not_done = node.get("done") is False or node.get("episode_over") is False
    explicit_done = _step_done_flag(node)
    pre_end = explicit_not_done or (human_done is False) or (ctx.pre_end and not explicit_done)
    if mode in MOLE_MODES and not explicit_done:
        pre_end = True

    cur_ctx = _ScanCtx(
        tier=tier,
        seed=seed,
        day=day,
        mode=mode,
        human_done=human_done,
        pre_end=pre_end,
        allow_investigator_doc_canary=ctx.allow_investigator_doc_canary,
        expected_known_v=ctx.expected_known_v,
        expected_true_v=ctx.expected_true_v,
    )

    if pre_end:
        for tkey in PRE_END_TRUTH_KEYS:
            if tkey in node and node[tkey] is not None and not _is_sealed_token(node[tkey]):
                if human_done is False or not explicit_done:
                    violations.append(f"{loc}.{tkey}: unsealed pre-end hidden truth ({tkey}={node[tkey]!r})")

        if not explicit_done and mode not in MOLE_MODES:
            for skey in SPRITE_LEAK_KEYS:
                sval = node.get(skey)
                if sval is not None and sval != "" and sval is not False and not _is_sealed_token(sval):
                    violations.append(
                        f"{loc}.{skey}: pre-end office sprite leak ({skey}={sval!r})"
                    )
            if node.get("is_mole") is True:
                violations.append(f"{loc}.is_mole: pre-end sprite marks is_mole=True")

        if "is_canary" in node and not explicit_done:
            if mode in MOLE_MODES or not cur_ctx.allow_investigator_doc_canary:
                violations.append(
                    f"{loc}.is_canary: pre-end is_canary={node['is_canary']!r} exposed "
                    f"(mode={mode or 'non-list_documents'})"
                )

        if human_done is False and node.get("tool") == "accuse":
            args_obj = node.get("args") if isinstance(node.get("args"), dict) else node.get("arguments")
            emp_arg = args_obj.get("employee") if isinstance(args_obj, dict) else None
            res_data = ((node.get("result") or {}).get("data") or {}) if isinstance(node.get("result"), dict) else {}
            accused_id = emp_arg or res_data.get("accused") or node.get("accused")
            if isinstance(accused_id, str) and EMP_ID_RE.match(accused_id):
                violations.append(
                    f"{loc}: split-screen opponent step exposes unsealed accuse target {accused_id!r} while human_done=False"
                )

        if not explicit_done:
            violations.extend(_check_v_exposure(node, loc, cur_ctx))

    is_inv_list_docs = (node.get("tool") == "list_documents") and (mode not in MOLE_MODES)

    for k, v in node.items():
        ks = str(k)
        child_loc = f"{loc}.{ks}"
        if ks in POST_END_CONTAINER_KEYS and not explicit_not_done and human_done is not False:
            continue
        if ks in STEP_COLLECTION_KEYS and isinstance(v, list):
            shadow_env: Env | None = None
            if (
                ks == "steps"
                and tier in {"easy", "medium", "hard"}
                and _is_int_seed(seed)
                and int(seed) in DEV_SEEDS
            ):
                shadow_env = Env(tier, int(seed))
            for idx, step_item in enumerate(v):
                step_loc = f"{child_loc}[{idx}]"
                if not isinstance(step_item, dict):
                    violations.extend(_scan_node(step_item, step_loc, cur_ctx))
                    continue
                exp_kv: float | None = None
                exp_tv: float | None = None
                if shadow_env is not None:
                    t_field = step_item.get("t") if "t" in step_item else step_item.get("call_idx")
                    rec_ok = step_item.get("ok")
                    if rec_ok is None and isinstance(step_item.get("result"), dict):
                        rec_ok = step_item["result"].get("ok")
                    if _is_int_seed(t_field) and int(t_field) != idx:
                        shadow_env = None
                    elif isinstance(step_item.get("tool"), str) and isinstance(step_item.get("args"), dict):
                        live_step_res = shadow_env.call(step_item["tool"], step_item["args"])
                        if isinstance(rec_ok, bool) and live_step_res.ok != rec_ok:
                            shadow_env = None
                        else:
                            exp_kv = shadow_env.visible_V()
                            exp_tv = round(shadow_env.V, 10)
                    else:
                        shadow_env = None
                step_done = _step_done_flag(step_item)
                step_pre_end = (
                    step_item.get("done") is False
                    or human_done is False
                    or not step_done
                )
                step_ctx = _ScanCtx(
                    tier=tier,
                    seed=seed,
                    day=day,
                    mode=mode,
                    human_done=human_done,
                    pre_end=step_pre_end,
                    allow_investigator_doc_canary=False,
                    expected_known_v=exp_kv,
                    expected_true_v=exp_tv,
                )
                violations.extend(_scan_node(step_item, step_loc, step_ctx))
        else:
            child_ctx = _ScanCtx(
                tier=tier,
                seed=seed,
                day=day,
                mode=mode,
                human_done=human_done,
                pre_end=pre_end,
                allow_investigator_doc_canary=(
                    cur_ctx.allow_investigator_doc_canary
                    or (is_inv_list_docs and ks in {"result", "data", "documents"})
                ),
                expected_known_v=cur_ctx.expected_known_v,
                expected_true_v=cur_ctx.expected_true_v,
            )
            violations.extend(_scan_node(v, child_loc, child_ctx))

    return violations


def scan_bundle_payload(payload: Any, source_label: str) -> list[str]:
    violations = collect_bundle_seed_violations(payload, source_label)
    violations.extend(_scan_node(payload, source_label, _ScanCtx()))
    return violations


def _scan_files_for_secrets_and_seeds(
    files_with_labels: list[tuple[Path, str, bool]],
    repo_secrets: list[bytes],
) -> dict[str, Any]:
    api_key_hits: list[str] = []
    secret_literal_hits: list[str] = []
    benchmark_seed_hits: list[str] = []
    parse_errors: list[str] = []
    bundle_payload_count = 0

    for fp, rel_label, strict_literal_names in files_with_labels:
        fname = fp.name
        if fname in FORBIDDEN_SECRET_FILENAMES or (
            fname.startswith(".env.") and fname not in ALLOWED_ENV_TEMPLATES
        ):
            secret_literal_hits.append(f"{rel_label}: forbidden secret file shipped")
            continue
        if fname.endswith(".world.json"):
            secret_literal_hits.append(f"{rel_label}: forbidden .world.json file shipped")
            continue

        try:
            raw = fp.read_bytes()
        except OSError as exc:
            parse_errors.append(f"{rel_label}: unreadable file ({type(exc).__name__})")
            continue

        for sb in repo_secrets:
            if sb in raw:
                secret_literal_hits.append(f"{rel_label}: contains raw repository secret bytes")
                break

        if b"\x00" in raw:
            continue

        txt = raw.decode("utf-8", errors="replace")
        for kind, rx in CREDENTIAL_PATTERNS:
            for match in rx.finditer(txt):
                prefix = match.group(0)[:6] + "..."
                api_key_hits.append(f"{rel_label}: {kind} ({prefix})")

        if SECRET_ASSIGN_RE.search(txt) or DOTENV_SECRET_RE.search(txt):
            secret_literal_hits.append(f"{rel_label}: literal secret assignment")
        elif strict_literal_names and STRICT_LITERAL_NAMES_RE.search(txt):
            secret_literal_hits.append(f"{rel_label}: forbidden SALT/CANARY_* secret identifier")

        payloads, perrs = extract_bundle_payloads(fp, rel_label)
        parse_errors.extend(perrs)
        bundle_payload_count += len(payloads)
        for plabel, pobj in payloads:
            benchmark_seed_hits.extend(collect_bundle_seed_violations(pobj, plabel))

    return {
        "files_scanned": len(files_with_labels),
        "bundle_payloads_parsed": bundle_payload_count,
        "api_key_hits": api_key_hits,
        "secret_literal_hits": secret_literal_hits,
        "benchmark_seed_hits": benchmark_seed_hits,
        "parse_errors": parse_errors,
    }


def run_check_a1(
    root: Path,
    scratch_root: Path | None = None,
    skip_site_build: bool = False,
) -> CheckOutcome:
    name = "Check A1: Secret, Key & Benchmark-Seed Firewall"
    game_dir = root / "game"
    arena_dir = root / "docs" / "arena"
    demo_dir = root / "docs" / "demo"

    if not game_dir.is_dir() and not arena_dir.is_dir() and not demo_dir.is_dir():
        return CheckOutcome(
            "A1",
            name,
            False,
            "FAIL",
            "no game/, docs/arena/, or docs/demo/ surfaces found under root",
            violations=[f"missing surfaces under {root}"],
        )

    violations: list[str] = []
    repo_secrets = _repo_secret_bytes(root)

    game_files = _iter_surface_files(game_dir, skip_dirs=frozenset({"site", "node_modules"}))
    arena_files = _iter_surface_files(arena_dir, skip_dirs=frozenset({"node_modules"}))
    demo_files = _iter_surface_files(demo_dir, skip_dirs=frozenset({"node_modules"}))

    scan_targets: list[tuple[Path, str, bool]] = []
    for p in game_files:
        scan_targets.append((p, p.relative_to(root).as_posix(), True))
    for p in arena_files:
        strict_lit = p.suffix.lower() in {".html", ".json", ".jsonl", ".css"}
        scan_targets.append((p, p.relative_to(root).as_posix(), strict_lit))
    for p in demo_files:
        strict_lit = p.suffix.lower() in {".html", ".json", ".jsonl", ".css"}
        scan_targets.append((p, p.relative_to(root).as_posix(), strict_lit))

    site_built_files = 0
    site_py_files = 0
    manifest_checked = False
    forbidden_manifest_hits: list[str] = []

    build_py = game_dir / "build.py"
    if build_py.is_file() and not skip_site_build:
        with _scratch_workdir(scratch_root, "a1-site") as work:
            tmp_site = work / "site"
            build_mod = _load_python_module("canary_game_build_a1", build_py)
            manifest = build_mod.build(tmp_site)
            manifest_checked = True
            manifest_list = sorted(str(x) for x in manifest.get("files", []))
            disk_py = sorted(
                p.relative_to(tmp_site / "py").as_posix()
                for p in (tmp_site / "py").rglob("*.py")
                if p.is_file()
            )
            site_py_files = len(disk_py)
            if manifest_list != disk_py:
                violations.append("game.build py/manifest.json mismatch against built py/ files")
            all_site = _iter_surface_files(tmp_site)
            site_built_files = len(all_site)
            for rel_item in manifest_list + [p.relative_to(tmp_site).as_posix() for p in all_site]:
                if any(tok in rel_item for tok in FORBIDDEN_MANIFEST_TOKENS):
                    forbidden_manifest_hits.append(f"built_site:{rel_item}")
            site_targets: list[tuple[Path, str, bool]] = []
            for p in all_site:
                rel_s = "built_site/" + p.relative_to(tmp_site).as_posix()
                strict_s = not rel_s.startswith("built_site/py/canary/")
                site_targets.append((p, rel_s, strict_s))
            site_scan = _scan_files_for_secrets_and_seeds(site_targets, repo_secrets)
            violations.extend(site_scan["api_key_hits"])
            violations.extend(site_scan["secret_literal_hits"])
            violations.extend(site_scan["benchmark_seed_hits"])
            violations.extend(site_scan["parse_errors"])

    for extra_manifest in [
        p for p in arena_files + demo_files if p.name == "manifest.json"
    ]:
        rel_m = extra_manifest.relative_to(root).as_posix()
        try:
            m_obj = json.loads(extra_manifest.read_text(encoding="utf-8"))
            if isinstance(m_obj, dict) and isinstance(m_obj.get("files"), list):
                manifest_checked = True
                for entry in m_obj["files"]:
                    s_entry = str(entry)
                    if any(tok in s_entry for tok in FORBIDDEN_MANIFEST_TOKENS):
                        forbidden_manifest_hits.append(f"{rel_m}:{s_entry}")
        except ValueError as exc:
            violations.append(f"{rel_m}: invalid JSON ({exc})")

    violations.extend(forbidden_manifest_hits)

    main_scan = _scan_files_for_secrets_and_seeds(scan_targets, repo_secrets)
    violations.extend(main_scan["api_key_hits"])
    violations.extend(main_scan["secret_literal_hits"])
    violations.extend(main_scan["benchmark_seed_hits"])
    violations.extend(main_scan["parse_errors"])

    judge_rejected = 0
    judge_total = len(JUDGE_SEEDS)
    heldout_rejected = 0
    heldout_total = len(BENCHMARK_HELDOUT_30)
    extra_boundary_rejected = 0
    extra_Probes: tuple[Any, ...] = (0, 2999, 10000, 100000, 800199, -1, "3000.0", "3e3", "abc", None, True)

    canary_game_py = game_dir / "canary_game.py"
    if canary_game_py.is_file():
        cg_mod = _load_python_module("canary_game_a1", canary_game_py)
        for s in JUDGE_SEEDS:
            try:
                cg_mod.Game(s)
            except ValueError:
                judge_rejected += 1
            else:
                violations.append(f"game/canary_game.py accepted JUDGE_SEED {s}")
        for s in BENCHMARK_HELDOUT_30:
            try:
                cg_mod.Game(s)
            except ValueError:
                heldout_rejected += 1
            else:
                violations.append(f"game/canary_game.py accepted HELDOUT_SEED {s}")
        for bad in extra_Probes:
            try:
                cg_mod.Game(bad)
            except ValueError:
                extra_boundary_rejected += 1
            else:
                violations.append(f"game/canary_game.py accepted boundary seed {bad!r}")

    arena_guard_py = arena_dir / "arena_integrity.py"
    arena_guard_checked = False
    if arena_guard_py.is_file():
        ag_mod = _load_python_module("arena_integrity_a1", arena_guard_py)
        gate_fn = (
            getattr(ag_mod, "check_seed", None)
            or getattr(ag_mod, "validate_seed", None)
            or getattr(ag_mod, "check_arena_seed", None)
        )
        if callable(gate_fn):
            arena_guard_checked = True
            for s in list(JUDGE_SEEDS) + list(BENCHMARK_HELDOUT_30):
                try:
                    gate_fn(s)
                except ValueError:
                    pass
                else:
                    violations.append(f"docs/arena/arena_integrity.py accepted benchmark seed {s}")

    passed = len(violations) == 0
    metrics = {
        "game_files_scanned": len(game_files),
        "arena_present": arena_dir.is_dir(),
        "arena_index_present": (arena_dir / "index.html").is_file(),
        "arena_files_scanned": len(arena_files),
        "demo_present": demo_dir.is_dir(),
        "demo_files_scanned": len(demo_files),
        "site_built_files": site_built_files,
        "site_python_files": site_py_files,
        "manifest_checked": manifest_checked,
        "forbidden_manifest_hits": len(forbidden_manifest_hits),
        "api_key_hits": len(main_scan["api_key_hits"]),
        "secret_literal_hits": len(main_scan["secret_literal_hits"]),
        "benchmark_seed_bundle_hits": len(main_scan["benchmark_seed_hits"]),
        "judge_seeds_rejected": f"{judge_rejected}/{judge_total}" if canary_game_py.is_file() else "n/a",
        "heldout_seeds_rejected": f"{heldout_rejected}/{heldout_total}" if canary_game_py.is_file() else "n/a",
        "extra_boundary_rejected": f"{extra_boundary_rejected}/{len(extra_Probes)}" if canary_game_py.is_file() else "n/a",
        "arena_guard_checked": arena_guard_checked,
    }
    summary = (
        f"game={len(game_files)} arena={len(arena_files)} demo={len(demo_files)} "
        f"site={site_built_files} py={site_py_files} keys=0 secrets=0 "
        f"judge_rejected={metrics['judge_seeds_rejected']} heldout_rejected={metrics['heldout_seeds_rejected']}"
        if passed
        else f"{len(violations)} firewall violation(s) detected"
    )
    return CheckOutcome("A1", name, passed, "PASS" if passed else "FAIL", summary, metrics, violations)


def _normalize_error_str(raw_err: Any) -> str | None:
    if raw_err is None:
        return None
    s = str(raw_err)
    if s.startswith("{"):
        try:
            parsed = json.loads(s)
            if isinstance(parsed, dict) and "error" in parsed:
                return str(parsed["error"]) if parsed["error"] is not None else None
        except json.JSONDecodeError:
            pass
    return s


def _audit_committed_hard_seed(ep: dict[str, Any], expected_seed: int) -> tuple[dict[str, Any], list[str]]:
    violations: list[str] = []
    steps = ep.get("steps")
    if not isinstance(steps, list) or not steps:
        return {}, [f"hard:{expected_seed}: missing steps list"]

    env = Env("hard", expected_seed)
    true_mole = env._world.mole
    true_decoy = env._world.decoy
    pre_terminal_steps = 0
    unsurfaced_steps = 0
    unsurfaced_days: set[int] = set()
    v_responses_checked = 0

    for idx, st in enumerate(steps):
        if not isinstance(st, dict):
            violations.append(f"hard:{expected_seed}:steps[{idx}]: step is not a dict")
            continue
        tool = str(st.get("tool") or "")
        args = st.get("args") if isinstance(st.get("args"), dict) else {}
        live_res = env.call(tool, args)
        rec_res = st.get("result") if isinstance(st.get("result"), dict) else {}
        norm_rec_err = _normalize_error_str(rec_res.get("error"))
        if rec_res.get("ok") != live_res.ok or norm_rec_err != live_res.error:
            violations.append(f"hard:{expected_seed}:steps[{idx}]: replay ok/error mismatch on {tool}")

        true_v = round(env.V, 10)
        known_v = env.visible_V()
        is_done_step = _step_done_flag(st) or env.done

        if not is_done_step:
            pre_terminal_steps += 1
            if abs(true_v - known_v) > 1e-9:
                unsurfaced_steps += 1
                unsurfaced_days.add(env.day)

            step_ctx = _ScanCtx(
                tier="hard",
                seed=expected_seed,
                day=env.day,
                mode="investigator",
                pre_end=True,
                expected_known_v=known_v,
                expected_true_v=true_v,
            )
            violations.extend(_scan_node(st, f"hard:{expected_seed}:steps[{idx}]", step_ctx))

        if tool in {"status", "advance_day"} and rec_res.get("ok") is True:
            rec_data = rec_res.get("data") if isinstance(rec_res.get("data"), dict) else {}
            if "V" in rec_data:
                v_responses_checked += 1
                shown_v = float(rec_data["V"])
                if abs(shown_v - known_v) > 1e-9:
                    violations.append(
                        f"hard:{expected_seed}:steps[{idx}]: {tool} returned V={shown_v} != known_v={known_v}"
                    )
                if abs(true_v - known_v) > 1e-9 and abs(shown_v - true_v) < 1e-9:
                    violations.append(
                        f"hard:{expected_seed}:steps[{idx}]: {tool} leaked unsurfaced true_v={true_v}"
                    )

    verdict = env.verdict()
    if verdict["accused"] != ep.get("accused") or bool(verdict["correct"]) != bool(ep.get("correct")):
        violations.append(f"hard:{expected_seed}: terminal verdict accused/correct mismatch")
    if abs(float(verdict["score"]) - float(ep.get("score", 0.0))) > 1e-9:
        violations.append(f"hard:{expected_seed}: terminal score mismatch")

    info = {
        "seed": expected_seed,
        "true_mole": true_mole,
        "decoy": true_decoy,
        "total_steps": len(steps),
        "pre_terminal_steps": pre_terminal_steps,
        "unsurfaced_leak_steps": unsurfaced_steps,
        "unsurfaced_leak_days": sorted(unsurfaced_days),
        "v_responses_verified": v_responses_checked,
        "accused": verdict["accused"],
        "correct": verdict["correct"],
        "final_day": verdict["final_day"],
        "terminal_true_v": verdict["V"],
        "score": verdict["score"],
    }
    return info, violations


def run_check_a2(root: Path) -> CheckOutcome:
    name = "Check A2: Pre-End Replay & Bundle Truth-Leak Scanner"
    violations: list[str] = []

    arena_dir = root / "docs" / "arena"
    demo_dir = root / "docs" / "demo"
    game_dir = root / "game"

    bundle_files: list[Path] = []
    for sdir in (arena_dir, demo_dir):
        if sdir.is_dir():
            for p in _iter_surface_files(sdir, skip_dirs=frozenset({"node_modules"})):
                if p.suffix.lower() in {".html", ".js", ".mjs", ".json", ".jsonl"}:
                    bundle_files.append(p)
    if game_dir.is_dir():
        for p in _iter_surface_files(game_dir, skip_dirs=frozenset({"site", "node_modules"})):
            if p.suffix.lower() in {".html", ".js", ".json", ".jsonl"}:
                bundle_files.append(p)

    bundles_parsed = 0
    for fp in bundle_files:
        rel_label = fp.relative_to(root).as_posix()
        payloads, perrs = extract_bundle_payloads(fp, rel_label)
        violations.extend(perrs)
        for plabel, pobj in payloads:
            bundles_parsed += 1
            violations.extend(scan_bundle_payload(pobj, plabel))

    seed_summaries: dict[str, Any] = {}
    ep_path = root / COMMITTED_HARD_REL
    if ep_path.is_file():
        by_seed: dict[int, dict[str, Any]] = {}
        for line in ep_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            if row.get("seed") in {6, 26}:
                by_seed[int(row["seed"])] = row
        for target_seed in (6, 26):
            if target_seed not in by_seed:
                violations.append(f"missing seed {target_seed} in {COMMITTED_HARD_REL.as_posix()}")
                continue
            s_info, s_viol = _audit_committed_hard_seed(by_seed[target_seed], target_seed)
            seed_summaries[str(target_seed)] = s_info
            violations.extend(s_viol)
    elif (root / "data" / "runs" / "committed").exists():
        violations.append(f"missing committed hard episodes at {COMMITTED_HARD_REL.as_posix()}")

    game_init_ok = False
    reveal_pre_end_guarded = False
    no_auto_status_js = False
    game_unsurfaced_ok = False
    ws6_self_env_exposed = False
    arena_closure_guard_present = False

    canary_game_py = game_dir / "canary_game.py"
    if canary_game_py.is_file():
        cg_mod = _load_python_module("canary_game_a2", canary_game_py)
        g = cg_mod.Game(3000)
        ws6_self_env_exposed = hasattr(g, "env")
        hist_at_init = len(g.env.history)
        actions_at_init = len(g.actions)
        spec_obj = json.loads(g.spec_json())
        rev_init = json.loads(g.reveal_json())
        act_obj = json.loads(g.actions_json())
        hist_after_meta = len(g.env.history)

        game_init_ok = (
            hist_at_init == 0
            and actions_at_init == 0
            and hist_after_meta == 0
            and act_obj.get("actions") == []
            and g.env._world.mole not in json.dumps(spec_obj)
        )
        if not game_init_ok:
            violations.append("Game(3000) drained budget on init/spec or leaked mole in spec_json")

        reveal_pre_end_guarded = (
            "error" in rev_init
            and "mole" not in rev_init
            and "you" not in rev_init
            and "solver" not in rev_init
        )
        if not reveal_pre_end_guarded:
            violations.append("Game(3000).reveal_json() leaked payload before done=True")

        for _ in range(4):
            step_payload = json.loads(g.call_json("advance_day", "{}"))
            violations.extend(
                _scan_node(
                    step_payload,
                    f"Game(3000):day_{g.env.day}",
                    _ScanCtx(
                        tier="medium",
                        seed=3000,
                        day=g.env.day,
                        mode="investigator",
                        pre_end=not g.env.done,
                        expected_known_v=g.env.visible_V(),
                        expected_true_v=round(g.env.V, 10),
                    ),
                )
            )
        st_day5 = json.loads(g.call_json("status", "{}"))
        rev_day5 = json.loads(g.reveal_json())
        tv_day5 = round(g.env.V, 10)
        kv_day5 = g.env.visible_V()
        game_unsurfaced_ok = (
            not g.env.done
            and abs(tv_day5 - kv_day5) > 1e-9
            and abs(float(st_day5["data"]["V"]) - kv_day5) < 1e-9
            and "error" in rev_day5
            and "mole" not in rev_day5
        )
        if not game_unsurfaced_ok:
            violations.append("Game(3000) day 5 failed unsurfaced known_v or pre-end reveal guard")

    app_js = game_dir / "app.js"
    if app_js.is_file():
        js_txt = app_js.read_text(encoding="utf-8")
        no_auto_status_js = not bool(AUTO_STATUS_JS_RE.search(js_txt))
        if not no_auto_status_js:
            violations.append("game/app.js contains direct auto-status call_json/run invocation")

    arena_guard_py = arena_dir / "arena_integrity.py"
    if arena_guard_py.is_file():
        ag_txt = arena_guard_py.read_text(encoding="utf-8")
        arena_closure_guard_present = "self.env" not in ag_txt

    passed = len(violations) == 0
    s6 = seed_summaries.get("6", {})
    s26 = seed_summaries.get("26", {})
    metrics = {
        "bundle_files_inspected": len(bundle_files),
        "bundle_payloads_scanned": bundles_parsed,
        "hard_seed_6": s6,
        "hard_seed_26": s26,
        "game_init_zero_history": game_init_ok,
        "reveal_pre_end_guarded": reveal_pre_end_guarded,
        "app_js_no_auto_status": no_auto_status_js,
        "game_3000_day5_unsurfaced_ok": game_unsurfaced_ok,
        "ws6_self_env_in_python_scope": ws6_self_env_exposed,
        "arena_closure_guard_present": arena_closure_guard_present,
    }
    summary = (
        f"bundles_parsed={bundles_parsed} seed6_unsurfaced={s6.get('unsurfaced_leak_steps', 'n/a')} "
        f"seed26_unsurfaced={s26.get('unsurfaced_leak_steps', 'n/a')} "
        f"game_init_zero_drain={game_init_ok} reveal_guarded={reveal_pre_end_guarded}"
        if passed
        else f"{len(violations)} pre-end truth leak(s) detected"
    )
    return CheckOutcome("A2", name, passed, "PASS" if passed else "FAIL", summary, metrics, violations)


def _write_planted_control_bundle(case_root: Path, control_name: str) -> None:
    arena = case_root / "docs" / "arena"
    arena.mkdir(parents=True, exist_ok=True)
    (arena / "index.html").write_text("<!doctype html><title>Arena Scratch</title>\n", encoding="utf-8")

    clean_replay = {
        "tier": "hard",
        "seed": 6,
        "mode": "investigator",
        "human_done": False,
        "steps": [
            {
                "t": 0,
                "day": 1,
                "done": False,
                "tool": "status",
                "args": {},
                "result": {"ok": True, "data": {"day": 1, "V": 1.0}, "error": None},
            }
        ],
    }

    if control_name == "clean_arena_bundle":
        (arena / "replays.json").write_text(json.dumps(clean_replay, indent=2), encoding="utf-8")
    elif control_name == "planted_step_mole_id":
        bad = json.loads(json.dumps(clean_replay))
        bad["steps"][0]["mole"] = "e12"
        (arena / "replays.json").write_text(json.dumps(bad, indent=2), encoding="utf-8")
    elif control_name == "planted_unsurfaced_true_v":
        hud_leak = {
            "tier": "hard",
            "seed": 6,
            "day": 2,
            "done": False,
            "hud": {"day": 2, "V": 0.95},
        }
        (arena / "hud_state.json").write_text(json.dumps(hud_leak, indent=2), encoding="utf-8")
    elif control_name == "planted_unsealed_ai_accuse":
        duel_leak = {
            "tier": "hard",
            "seed": 6,
            "mode": "duel",
            "human_done": False,
            "opponent_steps": [
                {
                    "t": 12,
                    "day": 6,
                    "done": True,
                    "tool": "accuse",
                    "args": {"employee": "e29"},
                    "result": {"ok": True, "data": {"accused": "e29", "episode_over": True}, "error": None},
                }
            ],
        }
        (arena / "duel_split.json").write_text(json.dumps(duel_leak, indent=2), encoding="utf-8")
    elif control_name == "planted_pixel_sprite_leak":
        sprite_leak = {
            "tier": "hard",
            "seed": 6,
            "mode": "investigator",
            "sprite_frames": [
                {
                    "frame": 4,
                    "day": 2,
                    "done": False,
                    "leaking_sprite_employee": "e29",
                }
            ],
        }
        (arena / "office_frames.js").write_text(
            "window.ARENA_OFFICE_FRAMES = " + json.dumps(sprite_leak) + ";\n",
            encoding="utf-8",
        )
    elif control_name == "planted_mole_mode_is_canary":
        mole_mode_leak = {
            "tier": "medium",
            "seed": 3000,
            "mode": "be_the_mole",
            "done": False,
            "day": 2,
            "documents": [
                {"doc_id": "d2-1", "title": "Q2 Sales budget forecast", "recipients_count": 8, "is_canary": True}
            ],
        }
        (arena / "mole_mode_payload.json").write_text(json.dumps(mole_mode_leak, indent=2), encoding="utf-8")
    elif control_name == "planted_judge_seed_bundle":
        judge_leak = {
            "cases": [
                {"tier": "hard", "seed": 900000, "mode": "investigator", "steps": []}
            ]
        }
        (arena / "bundle.js").write_text(
            "window.ARENA_BUNDLE = " + json.dumps(judge_leak) + ";\n",
            encoding="utf-8",
        )
    else:
        raise ValueError(f"unknown control {control_name}")


PLANTED_CONTROLS: tuple[tuple[str, str], ...] = (
    ("planted_step_mole_id", ".mole"),
    ("planted_unsurfaced_true_v", "unsurfaced true_v"),
    ("planted_unsealed_ai_accuse", "unsealed accuse target"),
    ("planted_pixel_sprite_leak", "leaking_sprite_employee"),
    ("planted_mole_mode_is_canary", "is_canary"),
    ("planted_judge_seed_bundle", "900000"),
)


def audit_bundle_root_exit_code(target_root: Path, scratch_root: Path | None = None) -> tuple[int, list[str]]:
    a1 = run_check_a1(target_root, scratch_root=scratch_root, skip_site_build=True)
    a2 = run_check_a2(target_root)
    all_violations = list(a1.violations) + list(a2.violations)
    rc = 1 if (not a1.passed or not a2.passed) else 0
    return rc, all_violations


def run_check_a3(scratch_root: Path | None = None) -> CheckOutcome:
    name = "Check A3: 6 Planted Pre-End Leak Positive Controls"
    violations: list[str] = []
    control_results: list[dict[str, Any]] = []

    with _scratch_workdir(scratch_root, "a3-controls") as work:
        clean_dir = work / "clean_arena_bundle"
        _write_planted_control_bundle(clean_dir, "clean_arena_bundle")
        clean_rc, clean_viols = audit_bundle_root_exit_code(clean_dir, scratch_root=work)
        if clean_rc != 0:
            violations.append(f"clean_arena_bundle false positive: {clean_viols}")

        caught_count = 0
        for ctrl_name, expected_substr in PLANTED_CONTROLS:
            case_dir = work / ctrl_name
            _write_planted_control_bundle(case_dir, ctrl_name)
            rc, c_viols = audit_bundle_root_exit_code(case_dir, scratch_root=work)
            matched = rc == 1 and any(expected_substr in v for v in c_viols)
            if matched:
                caught_count += 1
            else:
                violations.append(
                    f"{ctrl_name}: expected exit 1 containing {expected_substr!r}, got rc={rc}, violations={c_viols}"
                )
            control_results.append(
                {
                    "control": ctrl_name,
                    "exit_code": rc,
                    "caught": matched,
                    "matched_violation": next((v for v in c_viols if expected_substr in v), ""),
                }
            )

    passed = len(violations) == 0 and caught_count == len(PLANTED_CONTROLS)
    metrics = {
        "clean_negative_control_rc": clean_rc,
        "planted_controls_total": len(PLANTED_CONTROLS),
        "planted_controls_caught": caught_count,
        "recall": f"{caught_count}/{len(PLANTED_CONTROLS)}",
        "controls": control_results,
    }
    summary = (
        f"clean_control_rc=0 planted_recall={caught_count}/{len(PLANTED_CONTROLS)} (100% exit 1)"
        if passed
        else f"positive control recall failure ({caught_count}/{len(PLANTED_CONTROLS)})"
    )
    return CheckOutcome("A3", name, passed, "PASS" if passed else "FAIL", summary, metrics, violations)


def verify_arena_integrity(
    root: Path = ROOT,
    scratch_root: Path | None = None,
    include_positive_controls: bool = True,
    skip_site_build: bool = False,
) -> dict[str, Any]:
    t0 = time.perf_counter()
    resolved_root = root.resolve()
    checks = [
        run_check_a1(resolved_root, scratch_root=scratch_root, skip_site_build=skip_site_build),
        run_check_a2(resolved_root),
    ]
    if include_positive_controls:
        checks.append(run_check_a3(scratch_root=scratch_root))

    elapsed = round(time.perf_counter() - t0, 4)
    passed = all(c.passed for c in checks)
    return {
        "passed": passed,
        "status": "PASS" if passed else "FAIL",
        "root": str(resolved_root),
        "elapsed_s": elapsed,
        "live_api_calls": 0,
        "checks": [asdict(c) for c in checks],
    }


def format_cli_report(report: dict[str, Any]) -> str:
    lines: list[str] = []
    for chk in report["checks"]:
        lines.append(f"[{chk['status']}] {chk['name']}: {chk['summary']}")
        for v in chk["violations"]:
            lines.append(f"  - {v}")
    lines.append(
        f"{report['status']}: {sum(1 for c in report['checks'] if c['passed'])}/{len(report['checks'])} checks passed in {report['elapsed_s']:.3f}s"
    )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Canary Arena pre-end hidden-truth leak and secret verifier.")
    ap.add_argument("--root", type=Path, default=ROOT, help="Repository or bundle root to audit")
    ap.add_argument("--json-out", type=Path, default=None, help="Optional path to write JSON report")
    ap.add_argument("--check", action="store_true", help="Run deterministic CI check and exit 0 on PASS, 1 on FAIL")
    ap.add_argument("--json", action="store_true", help="Print JSON report to stdout")
    ap.add_argument("--no-controls", action="store_true", help="Skip Check A3 positive control synthesis")
    args = ap.parse_args(argv)

    report = verify_arena_integrity(
        root=args.root,
        include_positive_controls=not args.no_controls,
    )
    if args.json_out is not None:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(format_cli_report(report))

    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
