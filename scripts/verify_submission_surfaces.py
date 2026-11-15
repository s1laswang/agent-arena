from __future__ import annotations

import argparse
import fnmatch
import json
import math
import os
import re
import string
import subprocess
import sys
import time
import tomllib
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

HASH_CHAR = chr(35)
DASH_CHARS = "".join(chr(c) for c in (0x2010, 0x2011, 0x2012, 0x2013, 0x2014, 0x2212))
DASH_TRANS = str.maketrans({ch: "-" for ch in DASH_CHARS})

CHECK_HARBOR = "Harbor Template & Rehearsal Surface"
CHECK_GEMINI = "Gemini Lab Replay & Swarm Surface"
CHECK_MEDIA = "Browser Game, Demo & Media Assets Surface"
CHECK_GITIGNORE = "Gitignore & Scratch Isolation Surface"

CHECK_NAMES: tuple[str, ...] = (
    CHECK_HARBOR,
    CHECK_GEMINI,
    CHECK_MEDIA,
    CHECK_GITIGNORE,
)

EXPECTED_SWARM_ATTEMPTS = 100
EXPECTED_SWARM_LEDGER_VERIFIED = 100
EXPECTED_SWARM_FINISHED = 91
EXPECTED_SWARM_WHITEBOX = 75
EXPECTED_SWARM_BLACKBOX = 16
EXPECTED_SWARM_MCP_RERUNS = 9
EXPECTED_SWARM_EXPLOITS = 0
EXPECTED_SWARM_CONTROL = 4
MIN_LADDER_EPISODES = 500
EXPECTED_LADDER_EPISODES = 587
EXPECTED_LADDER_CELLS = 42
EXPECTED_LADDER_EXCL_PARITY = 18
EXPECTED_FLASH_LITE_CELLS = 8
EXPECTED_SIG_OFF_REJECTED = 10
EXPECTED_SIG_ON_CALLS = 628
EXPECTED_ATLAS_CALLS = 464
EXPECTED_ATLAS_UNCACHED_USD = 58.56
EXPECTED_ATLAS_PAID_USD = 21.72
EXPECTED_ATLAS_PCT_SAVED = 62.9
EXPECTED_PROG_CALLS = 29150
EXPECTED_PROG_PCT_SAVED = 75.9
EXPECTED_PROG_SAVED_USD = 678.19
EXPECTED_PROG_UNCACHED_USD = 893.08
EXPECTED_DASH_CALLS = 24855
EXPECTED_DASH_CACHED_PCT = 85.3
EXPECTED_DASH_COST_USD = 226.34
EXPECTED_BLIND_EPISODES = 153
EXPECTED_BLIND_RECOVERED = 3
EXPECTED_BLIND_TAGS = 5
EXPECTED_BLIND_NEW_MODES = 2
EXPECTED_BLIND_CITED_STEPS = 127
EXPECTED_BLIND_REGRET_PCT = 21
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"

POOLED_EXT_JSON = "data/runs/committed/v1.4/opencode-gemini-4-carbon-ext/paired_table_pooled0to59.json"
POOLED_EXT_MD = "data/runs/committed/v1.4/opencode-gemini-4-carbon-ext/paired_table_pooled0to59.md"
PAIRED_GEMINI_JSON = "data/runs/committed/v1.4/paired_table_gemini.json"
EVAL_V14_PNGS: tuple[str, ...] = (
    "results/eval_v14/headline_gap_paired_v14.png",
    "results/eval_v14/posterior_calibration_v14.png",
)
GEMINI_FRONTIER_PNGS: tuple[str, ...] = (
    "results/gemini/frontier.png",
    "results/gemini/frontier_medium.png",
)
WS4_TABLE_DOCS: tuple[str, ...] = (
    "fr8/analysis/out/ws4_table_v3.md",
    "fr8/analysis/out/ws4_table_8k_s1s2.md",
    "fr8/analysis/out/ws4_whom_v3.md",
)
WS4_COMPUTE_DOCS: tuple[str, ...] = (
    "fr8/verda/README.md",
    "docs/reports/verda-evidence.md",
)
VERDA_INSTANCE_PREFIXES: tuple[str, ...] = (
    "3bb7",
    "ac58",
    "dbd0",
    "f437",
)
EXPECTED_VERDA_RUNS: tuple[tuple[str, str, int, float], ...] = (
    ("v3-verda-8k-s1", "ac58", 90, -0.777),
    ("v3-verda-8k-s2", "dbd0", 90, -0.050),
    ("v3-verda-s0", "3bb7", 90, -0.103),
)

GITIGNORE_TARGETS: tuple[tuple[str, str], ...] = (
    ("results/latest/", "results/latest/judge_table.md"),
    ("harbor/dataset/", "harbor/dataset/canary-hard-900000/task.toml"),
    (".env", ".env"),
)

FORBIDDEN_TRACKED_PREFIXES: tuple[str, ...] = (
    "results/latest/",
    "harbor/dataset/",
    "data/gemini/replay-check/",
)

CANARY_VAR_RX = re.compile(r"\bCANARY_[A-Z0-9_]*", re.IGNORECASE)
VERIFIER_DEFAULT_RX = re.compile(
    r"""["']--verifier["'][^)\n]*?\bdefault\s*=\s*["']([^"']+)["']""",
    re.DOTALL,
)
DRY_RUN_LABEL_RX = re.compile(
    r"\bdry[-\s]+(?:run|judge\s+rehearsal|rehearsal)\b",
    re.IGNORECASE,
)
SWARM_VERIFIED_EXPLOITS_RX = re.compile(
    r"Verified\s+exploits:\s*\*{0,2}(\d+)\*{0,2}",
    re.IGNORECASE,
)
ZERO_EXPLOITS_PROSE_RX = re.compile(
    r"(?<!\d)0\s*\*{0,2}\s*verified\s+exploits|\*{0,2}(?<!\d)0\s+verified\s+exploits\*{0,2}",
    re.IGNORECASE,
)
TABLE_SEP_CELL_RX = re.compile(r"^:?-{2,}:?$")


@dataclass
class CheckResult:
    name: str
    status: str
    summary: str
    details: list[str] = field(default_factory=list)


def _is_int(val: Any) -> bool:
    return isinstance(val, int) and not isinstance(val, bool)


def _is_finite_number(val: Any) -> bool:
    return (
        isinstance(val, (int, float))
        and not isinstance(val, bool)
        and math.isfinite(float(val))
    )


def _is_positive_number(val: Any) -> bool:
    return _is_finite_number(val) and float(val) > 0.0


def _has_int_token(text: str, num: int) -> bool:
    tok = re.escape(str(num))
    return re.search(rf"(?<![0-9.]){tok}(?![0-9])", text) is not None


def _norm_dashes(text: str) -> str:
    return text.translate(DASH_TRANS)


def _fmt_int_commas(num: int) -> str:
    return f"{num:,}"


def _require_nonempty_file(root: Path, rel: str, failures: list[str]) -> Path | None:
    path = root / rel
    if not path.exists() or not path.is_file():
        failures.append(f"missing required file: {rel}")
        return None
    try:
        size = path.stat().st_size
    except OSError as exc:
        failures.append(f"unreadable file {rel}: {type(exc).__name__}")
        return None
    if size <= 0:
        failures.append(f"empty required file: {rel} (0 bytes)")
        return None
    return path


def _require_nonempty_text_file(root: Path, rel: str, failures: list[str]) -> str | None:
    path = _require_nonempty_file(root, rel, failures)
    if path is None:
        return None
    try:
        txt = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        failures.append(f"unreadable text file {rel}: {type(exc).__name__}")
        return None
    if not txt.strip():
        failures.append(f"whitespace-only file: {rel}")
        return None
    return txt


def _require_valid_png(root: Path, rel: str, failures: list[str]) -> Path | None:
    path = _require_nonempty_file(root, rel, failures)
    if path is None:
        return None
    try:
        with path.open("rb") as fh:
            head = fh.read(len(PNG_MAGIC))
    except OSError as exc:
        failures.append(f"unreadable PNG file {rel}: {type(exc).__name__}")
        return None
    if head != PNG_MAGIC:
        failures.append(f"invalid PNG magic bytes in {rel}")
        return None
    return path


def _parse_markdown_table_rows(md_text: str) -> list[tuple[list[str], list[str]]]:
    rows: list[tuple[list[str], list[str]]] = []
    headers: list[str] | None = None
    for raw_line in md_text.splitlines():
        stripped = raw_line.strip()
        if not (stripped.startswith("|") and stripped.endswith("|")):
            headers = None
            continue
        cells = [c.strip() for c in stripped[1:-1].split("|")]
        if cells and all(TABLE_SEP_CELL_RX.match(c) for c in cells if c):
            continue
        if headers is None:
            headers = [re.sub(r"[*_`]", "", c).strip().lower() for c in cells]
            continue
        rows.append((headers, cells))
    return rows


def _load_json(path: Path, rel: str, failures: list[str]) -> Any:
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        failures.append(f"unreadable JSON file {rel}: {type(exc).__name__}")
        return None
    try:
        return json.loads(raw)
    except ValueError as exc:
        failures.append(f"invalid JSON in {rel}: {exc}")
        return None


def _find_canary_env_leaks(obj: Any, path: str = "environment") -> list[str]:
    leaks: list[str] = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            ks = str(k)
            cur = f"{path}.{ks}"
            if ks.upper().startswith("CANARY_"):
                leaks.append(cur)
            leaks.extend(_find_canary_env_leaks(v, cur))
    elif isinstance(obj, list):
        for idx, item in enumerate(obj):
            cur = f"{path}[{idx}]"
            if isinstance(item, str) and CANARY_VAR_RX.search(item):
                leaks.append(f"{cur}={item}")
            else:
                leaks.extend(_find_canary_env_leaks(item, cur))
    elif isinstance(obj, str):
        if CANARY_VAR_RX.search(obj):
            leaks.append(f"{path}={obj}")
    return leaks


def _detect_default_verifier_mode(build_py: Path | None) -> str:
    if build_py is None:
        return "separate"
    try:
        src = build_py.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return "separate"
    match = VERIFIER_DEFAULT_RX.search(src)
    if match is None:
        return "separate"
    return match.group(1).strip() or "separate"


def check_harbor_surface(root: Path = ROOT) -> CheckResult:
    name = CHECK_HARBOR
    root_resolved = root.resolve()
    failures: list[str] = []

    build_py = _require_nonempty_file(root_resolved, "harbor/build.py", failures)
    _require_nonempty_file(root_resolved, "harbor/README.md", failures)
    _require_nonempty_file(root_resolved, "harbor/check_isolation.sh", failures)
    toml_path = _require_nonempty_file(root_resolved, "harbor/template/task.toml", failures)

    if toml_path is not None:
        try:
            raw_toml = toml_path.read_text(encoding="utf-8")
        except OSError as exc:
            failures.append(f"unreadable harbor/template/task.toml: {type(exc).__name__}")
            raw_toml = ""

        if raw_toml:
            default_mode = _detect_default_verifier_mode(build_py)
            verifier_env_line = (
                'env = { CANARY_LEDGER_TOKEN = "tok", CANARY_LEDGER_KEY = "key" }'
                if default_mode == "shared"
                else ""
            )
            rendered_toml = string.Template(raw_toml).safe_substitute(
                {
                    "TASK_ID": "hard-900000",
                    "TIER": "hard",
                    "SEED": "900000",
                    "VERIFIER_MODE": default_mode,
                    "VERIFIER_ENV_LINE": verifier_env_line,
                    "LEDGER_TOKEN_LINE": "",
                }
            )
            try:
                parsed_toml = tomllib.loads(rendered_toml)
            except tomllib.TOMLDecodeError as exc:
                failures.append(f"harbor/template/task.toml invalid TOML: {exc}")
                parsed_toml = None

            if isinstance(parsed_toml, dict):
                verifier = parsed_toml.get("verifier")
                if not isinstance(verifier, dict):
                    failures.append("harbor/template/task.toml missing [verifier] section")
                else:
                    env_mode = verifier.get("environment_mode")
                    if env_mode != "separate":
                        failures.append(
                            f"harbor/template/task.toml verifier.environment_mode expected 'separate', got {env_mode!r}"
                        )
                    v_timeout = verifier.get("timeout_sec", verifier.get("timeout"))
                    if not _is_positive_number(v_timeout):
                        failures.append(
                            f"harbor/template/task.toml verifier timeout not configured positively: {v_timeout!r}"
                        )
                    collect = verifier.get("collect")
                    if (
                        "[[verifier.collect]]" not in raw_toml
                        or not isinstance(collect, list)
                        or not collect
                        or not all(isinstance(entry, dict) and bool(entry) for entry in collect)
                    ):
                        failures.append("harbor/template/task.toml [[verifier.collect]] missing or empty")

                agent = parsed_toml.get("agent")
                if not isinstance(agent, dict):
                    failures.append("harbor/template/task.toml missing [agent] section")
                else:
                    a_timeout = agent.get("timeout_sec", agent.get("timeout"))
                    if not _is_positive_number(a_timeout):
                        failures.append(
                            f"harbor/template/task.toml agent timeout not configured positively: {a_timeout!r}"
                        )

                env_section = parsed_toml.get("environment")
                if not isinstance(env_section, dict):
                    failures.append("harbor/template/task.toml missing [environment] section")
                else:
                    leaks = _find_canary_env_leaks(env_section)
                    if leaks:
                        failures.append(
                            f"harbor/template/task.toml [environment] exposes CANARY_* vars: {', '.join(leaks)}"
                        )

    rehearsal_readme = _require_nonempty_file(
        root_resolved, "results/harbor/rehearsal/README.md", failures
    )
    if rehearsal_readme is not None:
        if not rehearsal_readme.read_text(encoding="utf-8", errors="replace").strip():
            failures.append("whitespace-only file: results/harbor/rehearsal/README.md")

    dry_readme = _require_nonempty_file(
        root_resolved, "results/harbor/rehearsal-dry/README.md", failures
    )
    if dry_readme is not None:
        dry_txt = dry_readme.read_text(encoding="utf-8", errors="replace")
        if not dry_txt.strip():
            failures.append("whitespace-only file: results/harbor/rehearsal-dry/README.md")
        elif DRY_RUN_LABEL_RX.search(dry_txt) is None:
            failures.append("results/harbor/rehearsal-dry/README.md missing dry-run label")

    dry_table = _require_nonempty_file(
        root_resolved, "results/harbor/rehearsal-dry/TABLE.md", failures
    )
    if dry_table is not None:
        table_txt = dry_table.read_text(encoding="utf-8", errors="replace")
        if not table_txt.strip() or "|" not in table_txt:
            failures.append("results/harbor/rehearsal-dry/TABLE.md missing markdown table rows")

    c1_result = _require_nonempty_file(
        root_resolved, "results/harbor_negative/c1-tamper/result.json", failures
    )
    if c1_result is not None:
        c1_obj = _load_json(c1_result, "results/harbor_negative/c1-tamper/result.json", failures)
        if c1_obj is not None:
            if not isinstance(c1_obj, dict) or not c1_obj:
                failures.append("results/harbor_negative/c1-tamper/result.json must be a non-empty JSON object")
            else:
                stats = c1_obj.get("stats")
                evals = stats.get("evals") if isinstance(stats, dict) else None
                if isinstance(evals, dict):
                    for eval_name, eval_body in evals.items():
                        if not isinstance(eval_body, dict):
                            continue
                        metrics = eval_body.get("metrics")
                        if isinstance(metrics, list):
                            for metric in metrics:
                                if isinstance(metric, dict) and "mean" in metric:
                                    mean_val = metric.get("mean")
                                    if not isinstance(mean_val, (int, float)) or isinstance(mean_val, bool) or float(mean_val) != 0.0:
                                        failures.append(
                                            f"results/harbor_negative/c1-tamper/result.json {eval_name} expected mean 0.0, got {mean_val!r}"
                                        )

    _audit_afterquery_submission_surface(root_resolved, failures)
    _audit_ws4_compute_surface(root_resolved, failures)

    if failures:
        return CheckResult(
            name,
            "FAIL",
            f"{len(failures)} Harbor/AfterQuery/WS4 submission surface violation(s)",
            failures,
        )
    return CheckResult(
        name,
        "PASS",
        "harbor template + rehearsal + c1-tamper, AfterQuery docs/SUBMISSION.md (sections 1-9, 65%/72%), pooled n=32/n=60, eval_v14 PNGs, and WS4/Verda compute docs verified",
    )


def _audit_afterquery_submission_surface(root_resolved: Path, failures: list[str]) -> None:
    sub_txt = _require_nonempty_text_file(root_resolved, "docs/SUBMISSION.md", failures)
    if sub_txt is not None:
        if re.search(r"Project\s+name:\s*Canary\b", sub_txt, re.IGNORECASE) is None:
            failures.append("docs/SUBMISSION.md missing form field 'Project name: Canary'")
        if re.search(r"^\s*Tagline\b", sub_txt, re.IGNORECASE | re.MULTILINE) is None:
            failures.append("docs/SUBMISSION.md missing form field 'Tagline'")
        if re.search(r"^\s*Description\b", sub_txt, re.IGNORECASE | re.MULTILINE) is None:
            failures.append("docs/SUBMISSION.md missing form field 'Description'")
        if re.search(r"(?<![0-9.])65%", sub_txt) is None:
            failures.append("docs/SUBMISSION.md missing headline '65%' ratio")
        if re.search(r"(?<![0-9.])72%", sub_txt) is None:
            failures.append("docs/SUBMISSION.md missing luck-adjusted '72%' ratio")

        missing_secs: list[str] = []
        for sec_num in range(1, 10):
            sec_rx = rf"^\s*{HASH_CHAR}{{2,3}}\s+{sec_num}\.\s+\S"
            if re.search(sec_rx, sub_txt, re.MULTILINE) is None:
                missing_secs.append(str(sec_num))
        if missing_secs:
            failures.append(
                f"docs/SUBMISSION.md missing rubric section heading(s): {', '.join(missing_secs)}"
            )

    pooled_json_path = _require_nonempty_file(root_resolved, POOLED_EXT_JSON, failures)
    if pooled_json_path is not None:
        pooled_obj = _load_json(pooled_json_path, POOLED_EXT_JSON, failures)
        if pooled_obj is not None:
            if not isinstance(pooled_obj, list) or not pooled_obj or not all(
                isinstance(r, dict) for r in pooled_obj
            ):
                failures.append(f"{POOLED_EXT_JSON} must be a non-empty JSON list of row objects")
            else:
                has_hard_oc_32 = any(
                    r.get("tier") == "hard"
                    and (
                        "opencode" in str(r.get("agent", "")).lower()
                        or "opencode" in str(r.get("label", "")).lower()
                    )
                    and _is_int(r.get("n"))
                    and int(r["n"]) == 32
                    and _is_finite_number(r.get("mean"))
                    and _is_finite_number(r.get("solver_same_seeds"))
                    for r in pooled_obj
                )
                if not has_hard_oc_32:
                    failures.append(f"{POOLED_EXT_JSON} missing hard OpenCode row with n=32")

                has_hard_solver_60 = any(
                    r.get("tier") == "hard"
                    and (
                        r.get("agent") == "solver"
                        or "solver" in str(r.get("label", "")).lower()
                    )
                    and _is_int(r.get("n"))
                    and int(r["n"]) == 60
                    and _is_finite_number(r.get("mean"))
                    for r in pooled_obj
                )
                if not has_hard_solver_60:
                    failures.append(f"{POOLED_EXT_JSON} missing hard solver row with n=60")

    pooled_md_txt = _require_nonempty_text_file(root_resolved, POOLED_EXT_MD, failures)
    if pooled_md_txt is not None:
        md_rows = _parse_markdown_table_rows(pooled_md_txt)
        if not md_rows:
            failures.append(f"{POOLED_EXT_MD} missing markdown table rows")
        else:
            md_has_oc_32 = False
            md_has_solver_60 = False
            for headers, cells in md_rows:
                row_map = {
                    headers[idx]: cells[idx]
                    for idx in range(min(len(headers), len(cells)))
                }
                tier_val = re.sub(r"[*_`\s]", "", row_map.get("tier", cells[0] if cells else "")).lower()
                run_val = (
                    row_map.get("run")
                    or row_map.get("label")
                    or row_map.get("agent")
                    or (cells[1] if len(cells) > 1 else "")
                ).lower()
                n_raw = re.sub(
                    r"[*_`\s]",
                    "",
                    row_map.get("n", cells[2] if len(cells) > 2 else ""),
                )
                n_val = int(n_raw) if n_raw.isdigit() else None
                if tier_val == "hard" and "opencode" in run_val and n_val == 32:
                    md_has_oc_32 = True
                if tier_val == "hard" and "solver" in run_val and n_val == 60:
                    md_has_solver_60 = True
            if not md_has_oc_32:
                failures.append(f"{POOLED_EXT_MD} missing hard OpenCode row with n=32")
            if not md_has_solver_60:
                failures.append(f"{POOLED_EXT_MD} missing hard solver row with n=60")

    for png_rel in EVAL_V14_PNGS:
        _require_valid_png(root_resolved, png_rel, failures)


def _extract_ws4_all_tier_rows(md_text: str) -> list[tuple[str, int, str]]:
    out: list[tuple[str, int, str]] = []
    for headers, cells in _parse_markdown_table_rows(_norm_dashes(md_text)):
        row_map = {
            headers[idx]: cells[idx]
            for idx in range(min(len(headers), len(cells)))
        }
        tier_raw = re.sub(r"[*_`\s]", "", row_map.get("tier", "")).lower()
        if tier_raw != "all":
            continue
        model_raw = re.sub(
            r"[*_`\s]",
            "",
            row_map.get("model", cells[0] if cells else ""),
        ).lower()
        n_raw = re.sub(r"[*_`\s]", "", row_map.get("n", ""))
        if not n_raw.isdigit():
            continue
        score_cell = ""
        for k, v in row_map.items():
            if "score" in k:
                score_cell = _norm_dashes(re.sub(r"[*_`]", "", v)).strip()
                break
        if not score_cell and len(cells) > 5:
            score_cell = _norm_dashes(re.sub(r"[*_`]", "", cells[5])).strip()
        out.append((model_raw, int(n_raw), score_cell))
    return out


def _audit_ws4_compute_surface(root_resolved: Path, failures: list[str]) -> None:
    ws4_texts: dict[str, str] = {}
    for rel in WS4_TABLE_DOCS:
        txt = _require_nonempty_text_file(root_resolved, rel, failures)
        if txt is not None:
            ws4_texts[rel] = txt
            if "|" not in txt or not _parse_markdown_table_rows(txt):
                failures.append(f"{rel} missing markdown table rows")

    compute_texts: dict[str, str] = {}
    for rel in WS4_COMPUTE_DOCS:
        txt = _require_nonempty_text_file(root_resolved, rel, failures)
        if txt is not None:
            compute_texts[rel] = txt

    verda_dir = root_resolved / "data" / "fr8" / "verda"
    summary_paths = (
        sorted(p for p in verda_dir.glob("**/runs/*/summary.json") if p.is_file())
        if verda_dir.is_dir()
        else []
    )
    verda_runs: dict[str, tuple[int, float, str]] = {}
    if not summary_paths:
        failures.append("missing data/fr8/verda/**/runs/*/summary.json files")
    else:
        for spath in summary_paths:
            rel_sp = spath.relative_to(root_resolved).as_posix()
            sobj = _load_json(spath, rel_sp, failures)
            if sobj is None:
                continue
            if not isinstance(sobj, dict):
                failures.append(f"{rel_sp} must be a JSON object")
                continue
            run_id = sobj.get("run_id")
            if not isinstance(run_id, str) or not run_id.strip():
                failures.append(f"{rel_sp} missing string 'run_id'")
                continue
            run_id = run_id.strip()
            if run_id != spath.parent.name:
                failures.append(
                    f"{rel_sp} run_id {run_id!r} disagrees with directory {spath.parent.name!r}"
                )
            by_tier = sobj.get("by_tier")
            if not isinstance(by_tier, dict) or not isinstance(by_tier.get("all"), dict):
                failures.append(f"{rel_sp} missing by_tier.all summary object")
                continue
            all_tier = by_tier["all"]
            n_all = all_tier.get("n")
            mean_all = all_tier.get("mean_score")
            ci_all = all_tier.get("ci95")
            if not (_is_int(n_all) and int(n_all) > 0):
                failures.append(f"{rel_sp} by_tier.all missing positive integer 'n'")
                continue
            if not _is_finite_number(mean_all) or not _is_finite_number(ci_all):
                failures.append(f"{rel_sp} by_tier.all missing finite mean_score/ci95")
                continue
            tier_ns: list[int] = []
            tier_bad = False
            for tname in ("easy", "medium", "hard"):
                tdict = by_tier.get(tname)
                if isinstance(tdict, dict):
                    tn = tdict.get("n")
                    if not (_is_int(tn) and int(tn) > 0):
                        failures.append(f"{rel_sp} by_tier.{tname} missing positive integer 'n'")
                        tier_bad = True
                    else:
                        tier_ns.append(int(tn))
            if tier_ns and not tier_bad and sum(tier_ns) != int(n_all):
                failures.append(
                    f"{rel_sp} sum(easy,medium,hard n)={sum(tier_ns)} disagrees with by_tier.all.n={int(n_all)}"
                )
            verda_runs[run_id] = (int(n_all), round(float(mean_all), 3), rel_sp)

        for req_run, req_pfx, req_n, req_mean in EXPECTED_VERDA_RUNS:
            found = verda_runs.get(req_run)
            if found is None:
                failures.append(
                    f"data/fr8/verda/**/runs/*/summary.json missing required run '{req_run}'"
                )
                continue
            got_n, got_mean, got_rel = found
            if req_pfx not in got_rel:
                failures.append(
                    f"{got_rel} expected under instance prefix '{req_pfx}'"
                )
            if got_n != req_n:
                failures.append(
                    f"{got_rel} ({req_run}) by_tier.all.n expected {req_n}, got {got_n}"
                )
            if not math.isclose(got_mean, req_mean, abs_tol=1e-9):
                failures.append(
                    f"{got_rel} ({req_run}) by_tier.all.mean_score expected {req_mean:.3f}, got {got_mean:.3f}"
                )

    s1_n, s1_mean = (
        (verda_runs["v3-verda-8k-s1"][0], verda_runs["v3-verda-8k-s1"][1])
        if "v3-verda-8k-s1" in verda_runs
        else (90, -0.777)
    )
    s2_n, s2_mean = (
        (verda_runs["v3-verda-8k-s2"][0], verda_runs["v3-verda-8k-s2"][1])
        if "v3-verda-8k-s2" in verda_runs
        else (90, -0.050)
    )
    s1_str = f"{s1_mean:.3f}"
    s2_str = f"{s2_mean:.3f}"

    for tbl_rel in ("fr8/analysis/out/ws4_table_v3.md", "fr8/analysis/out/ws4_table_8k_s1s2.md"):
        tbl_txt = ws4_texts.get(tbl_rel)
        if tbl_txt is None or "|" not in tbl_txt:
            continue
        all_rows = _extract_ws4_all_tier_rows(tbl_txt)
        if not all_rows:
            continue
        has_s1 = any(
            "8k" in m and "s1" in m and n_val == s1_n and sc.startswith(s1_str)
            for m, n_val, sc in all_rows
        )
        if not has_s1:
            failures.append(
                f"{tbl_rel} missing all-tier v3-8k-s1 row matching summary.json (n={s1_n}, mean={s1_str})"
            )
        has_s2 = any(
            "8k" in m and "s2" in m and n_val == s2_n and sc.startswith(s2_str)
            for m, n_val, sc in all_rows
        )
        if not has_s2:
            failures.append(
                f"{tbl_rel} missing all-tier v3-8k-s2 row matching summary.json (n={s2_n}, mean={s2_str})"
            )
        has_4k_s0 = any(
            "4k" in m and "s0" in m and n_val == 180 and sc.startswith("-0.147")
            for m, n_val, sc in all_rows
        )
        if not has_4k_s0:
            failures.append(
                f"{tbl_rel} missing all-tier v3-4k-s0 row (n=180, mean=-0.147)"
            )

    for comp_rel in WS4_COMPUTE_DOCS:
        comp_txt = compute_texts.get(comp_rel)
        if comp_txt is None:
            continue
        norm_comp = _norm_dashes(comp_txt)
        missing_pfxs = [p for p in VERDA_INSTANCE_PREFIXES if p not in norm_comp]
        if missing_pfxs:
            failures.append(
                f"{comp_rel} missing Verda instance prefix(es): {', '.join(missing_pfxs)}"
            )

    verda_readme_txt = compute_texts.get("fr8/verda/README.md")
    if verda_readme_txt is not None:
        norm_readme = _norm_dashes(verda_readme_txt)
        if s1_str not in norm_readme or f"n={s1_n}" not in norm_readme:
            failures.append(
                f"fr8/verda/README.md missing v3-8k-s1 readout ({s1_str}, n={s1_n}) matching summary.json"
            )
        if s2_str not in norm_readme or f"n={s2_n}" not in norm_readme:
            failures.append(
                f"fr8/verda/README.md missing v3-8k-s2 readout ({s2_str}, n={s2_n}) matching summary.json"
            )

    verda_md_path = root_resolved / "VERDA.md"
    if verda_md_path.exists() or verda_md_path.is_symlink():
        verda_md_txt = _require_nonempty_text_file(root_resolved, "VERDA.md", failures)
        if verda_md_txt is not None:
            norm_verda_md = _norm_dashes(verda_md_txt)
            missing_v_pfxs = [p for p in VERDA_INSTANCE_PREFIXES if p not in norm_verda_md]
            if missing_v_pfxs:
                failures.append(
                    f"VERDA.md missing Verda instance prefix(es): {', '.join(missing_v_pfxs)}"
                )
            if s1_str not in norm_verda_md or not _has_int_token(norm_verda_md, s1_n):
                failures.append(
                    f"VERDA.md missing v3-8k-s1 readout ({s1_str}, n={s1_n}) matching summary.json"
                )
            if s2_str not in norm_verda_md or not _has_int_token(norm_verda_md, s2_n):
                failures.append(
                    f"VERDA.md missing v3-8k-s2 readout ({s2_str}, n={s2_n}) matching summary.json"
                )
            if "-0.147" not in norm_verda_md or not _has_int_token(norm_verda_md, 180):
                failures.append(
                    "VERDA.md missing v3-4k-s0 pooled readout (-0.147, n=180)"
                )
            if "fr8/verda/README.md" not in norm_verda_md or "ws4_table_" not in norm_verda_md:
                failures.append(
                    "VERDA.md missing provenance references to fr8/verda/README.md and ws4_table_*.md"
                )


def _extract_swarm_md_wave_totals(swarm_md: str) -> tuple[bool, int | None, int | None]:
    headers: list[str] | None = None
    for raw_line in swarm_md.splitlines():
        stripped = raw_line.strip()
        if not (stripped.startswith("|") and stripped.endswith("|")):
            headers = None
            continue
        cells = [c.strip() for c in stripped[1:-1].split("|")]
        if cells and all(TABLE_SEP_CELL_RX.match(c) for c in cells if c):
            continue
        if headers is None:
            headers = [c.lower() for c in cells]
            continue
        first_clean = re.sub(r"[*_`]", "", cells[0]).strip().lower() if cells else ""
        if "all real waves" not in first_clean:
            continue
        row = {headers[idx]: cells[idx] for idx in range(min(len(headers), len(cells)))}
        fin_raw = re.sub(r"[*_`\s]", "", row.get("finished", ""))
        exp_raw = re.sub(r"[*_`\s]", "", row.get("verified exploits", ""))
        if not fin_raw and len(cells) > 4:
            fin_raw = re.sub(r"[*_`\s]", "", cells[4])
        if not exp_raw and len(cells) > 11:
            exp_raw = re.sub(r"[*_`\s]", "", cells[11])
        fin_val = int(fin_raw) if fin_raw.isdigit() else None
        exp_val = int(exp_raw) if exp_raw.isdigit() else None
        return True, fin_val, exp_val
    return False, None, None


def _ci_bracket_rx(pct: int, lo: int, hi: int) -> re.Pattern[str]:
    return re.compile(
        rf"(?<![0-9.]){pct}%\s*\[\s*{lo}%?\s*,\s*{hi}%?\s*\]"
    )


def _audit_swarm_control_json(root_resolved: Path, failures: list[str]) -> int:
    ctrl_rel = "results/gemini/swarm_control.json"
    ctrl_path = _require_nonempty_file(root_resolved, ctrl_rel, failures)
    if ctrl_path is None:
        return EXPECTED_SWARM_CONTROL
    ctrl_obj = _load_json(ctrl_path, ctrl_rel, failures)
    if ctrl_obj is None:
        return EXPECTED_SWARM_CONTROL
    if not isinstance(ctrl_obj, dict):
        failures.append(f"{ctrl_rel} must be a JSON object")
        return EXPECTED_SWARM_CONTROL
    counts = ctrl_obj.get("counts")
    if not isinstance(counts, dict):
        failures.append(f"{ctrl_rel} missing 'counts' object")
        return EXPECTED_SWARM_CONTROL
    att_cnt = counts.get("attempts")
    lv_cnt = counts.get("ledger_verified")
    exp_cnt = counts.get("exploits")
    if not (_is_int(att_cnt) and int(att_cnt) == EXPECTED_SWARM_CONTROL):
        failures.append(
            f"{ctrl_rel} counts.attempts expected {EXPECTED_SWARM_CONTROL}, got {att_cnt!r}"
        )
    if not (_is_int(lv_cnt) and int(lv_cnt) == EXPECTED_SWARM_CONTROL):
        failures.append(
            f"{ctrl_rel} counts.ledger_verified expected {EXPECTED_SWARM_CONTROL}, got {lv_cnt!r}"
        )
    if not (_is_int(exp_cnt) and int(exp_cnt) == EXPECTED_SWARM_CONTROL):
        failures.append(
            f"{ctrl_rel} counts.exploits expected {EXPECTED_SWARM_CONTROL}, got {exp_cnt!r}"
        )
    attempts = ctrl_obj.get("attempts")
    if attempts is not None:
        if not isinstance(attempts, list) or len(attempts) != EXPECTED_SWARM_CONTROL:
            failures.append(
                f"{ctrl_rel} expected {EXPECTED_SWARM_CONTROL} positive-control attempts"
            )
        elif not all(isinstance(a, dict) and bool(a.get("exploit")) for a in attempts):
            failures.append(
                f"{ctrl_rel} expected all {EXPECTED_SWARM_CONTROL}/{EXPECTED_SWARM_CONTROL} attempts to have exploit=True"
            )
    return int(exp_cnt) if _is_int(exp_cnt) else EXPECTED_SWARM_CONTROL


def _audit_dashboard_html(
    root_resolved: Path, failures: list[str]
) -> tuple[int, float, float]:
    dash_rel = "results/gemini/dashboard.html"
    dash_txt = _require_nonempty_text_file(root_resolved, dash_rel, failures)
    if dash_txt is None:
        return EXPECTED_DASH_CALLS, EXPECTED_DASH_CACHED_PCT, EXPECTED_DASH_COST_USD
    match = re.search(
        r"""<script[^>]*\bid=["']data["'][^>]*>(.*?)</script>""",
        dash_txt,
        re.DOTALL | re.IGNORECASE,
    )
    if match is None:
        failures.append(f"{dash_rel} missing embedded <script id='data'> JSON payload")
        return EXPECTED_DASH_CALLS, EXPECTED_DASH_CACHED_PCT, EXPECTED_DASH_COST_USD
    try:
        payload = json.loads(match.group(1))
    except ValueError as exc:
        failures.append(f"{dash_rel} invalid embedded JSON payload: {exc}")
        return EXPECTED_DASH_CALLS, EXPECTED_DASH_CACHED_PCT, EXPECTED_DASH_COST_USD
    totals = payload.get("usage", {}).get("totals") if isinstance(payload, dict) else None
    if not isinstance(totals, dict):
        failures.append(f"{dash_rel} missing usage.totals object")
        return EXPECTED_DASH_CALLS, EXPECTED_DASH_CACHED_PCT, EXPECTED_DASH_COST_USD

    calls = totals.get("calls")
    in_tok = totals.get("in")
    cached_tok = totals.get("cached")
    cost_usd = totals.get("cost_usd")

    if not (_is_int(calls) and int(calls) == EXPECTED_DASH_CALLS):
        failures.append(
            f"{dash_rel} usage.totals.calls expected {EXPECTED_DASH_CALLS}, got {calls!r}"
        )
    if not (_is_positive_number(in_tok) and _is_finite_number(cached_tok)):
        failures.append(f"{dash_rel} usage.totals missing positive 'in' and numeric 'cached'")
        cached_pct = EXPECTED_DASH_CACHED_PCT
    else:
        cached_pct = round(float(cached_tok) / float(in_tok) * 100.0, 1)
        if not math.isclose(cached_pct, EXPECTED_DASH_CACHED_PCT, abs_tol=1e-6):
            failures.append(
                f"{dash_rel} cached input share expected {EXPECTED_DASH_CACHED_PCT:.1f}%, got {cached_pct:.1f}%"
            )
    if not _is_positive_number(cost_usd):
        failures.append(f"{dash_rel} usage.totals missing positive cost_usd")
        cost_2dp = EXPECTED_DASH_COST_USD
    else:
        cost_2dp = round(float(cost_usd), 2)
        if not math.isclose(cost_2dp, EXPECTED_DASH_COST_USD, abs_tol=1e-6):
            failures.append(
                f"{dash_rel} usage.totals.cost_usd expected {EXPECTED_DASH_COST_USD:.2f}, got {cost_2dp:.2f}"
            )
    return (
        int(calls) if _is_int(calls) else EXPECTED_DASH_CALLS,
        cached_pct,
        cost_2dp,
    )


def _audit_atlas_blind_json(
    root_resolved: Path, failures: list[str]
) -> tuple[int, int, int, int, int, int]:
    blind_rel = "results/gemini/atlas_blind.json"
    blind_path = _require_nonempty_file(root_resolved, blind_rel, failures)
    defaults = (
        EXPECTED_BLIND_EPISODES,
        EXPECTED_BLIND_RECOVERED,
        EXPECTED_BLIND_TAGS,
        EXPECTED_BLIND_NEW_MODES,
        EXPECTED_BLIND_CITED_STEPS,
        EXPECTED_BLIND_REGRET_PCT,
    )
    if blind_path is None:
        return defaults
    blind_obj = _load_json(blind_path, blind_rel, failures)
    if blind_obj is None:
        return defaults
    if not isinstance(blind_obj, dict):
        failures.append(f"{blind_rel} must be a JSON object")
        return defaults
    if blind_obj.get("blind") is not True:
        failures.append(f"{blind_rel} expected blind=true")
    corpus = blind_obj.get("corpus")
    recovery = blind_obj.get("recovery")
    if not isinstance(corpus, dict):
        failures.append(f"{blind_rel} missing 'corpus' object")
        eps = EXPECTED_BLIND_EPISODES
    else:
        raw_eps = corpus.get("episodes")
        if not (_is_int(raw_eps) and int(raw_eps) == EXPECTED_BLIND_EPISODES):
            failures.append(
                f"{blind_rel} corpus.episodes expected {EXPECTED_BLIND_EPISODES}, got {raw_eps!r}"
            )
            eps = EXPECTED_BLIND_EPISODES
        else:
            eps = int(raw_eps)

    if not isinstance(recovery, dict):
        failures.append(f"{blind_rel} missing 'recovery' object")
        return (eps, *defaults[1:])

    tags_rec = recovery.get("tags_recovered")
    n_tags = recovery.get("n_tags")
    novel = recovery.get("novel_modes")
    cited = recovery.get("cited_steps")
    regret_cov = recovery.get("regret_share_covered")

    if not (isinstance(tags_rec, list) and len(tags_rec) == EXPECTED_BLIND_RECOVERED):
        failures.append(
            f"{blind_rel} recovery.tags_recovered expected {EXPECTED_BLIND_RECOVERED} modes"
        )
        rec_cnt = EXPECTED_BLIND_RECOVERED
    else:
        rec_cnt = len(tags_rec)

    if not (_is_int(n_tags) and int(n_tags) == EXPECTED_BLIND_TAGS):
        failures.append(
            f"{blind_rel} recovery.n_tags expected {EXPECTED_BLIND_TAGS}, got {n_tags!r}"
        )
        tags_cnt = EXPECTED_BLIND_TAGS
    else:
        tags_cnt = int(n_tags)

    if not (isinstance(novel, list) and len(novel) == EXPECTED_BLIND_NEW_MODES):
        failures.append(
            f"{blind_rel} recovery.novel_modes expected {EXPECTED_BLIND_NEW_MODES} modes"
        )
        new_cnt = EXPECTED_BLIND_NEW_MODES
    else:
        new_cnt = len(novel)

    if not (_is_int(cited) and int(cited) == EXPECTED_BLIND_CITED_STEPS):
        failures.append(
            f"{blind_rel} recovery.cited_steps expected {EXPECTED_BLIND_CITED_STEPS}, got {cited!r}"
        )
        cited_cnt = EXPECTED_BLIND_CITED_STEPS
    else:
        cited_cnt = int(cited)

    if not _is_finite_number(regret_cov):
        failures.append(f"{blind_rel} recovery.regret_share_covered missing numeric value")
        regret_pct = EXPECTED_BLIND_REGRET_PCT
    else:
        regret_pct = int(round(float(regret_cov) * 100.0))
        if regret_pct != EXPECTED_BLIND_REGRET_PCT:
            failures.append(
                f"{blind_rel} recovery.regret_share_covered expected ~{EXPECTED_BLIND_REGRET_PCT}%, got {regret_pct}%"
            )

    return eps, rec_cnt, tags_cnt, new_cnt, cited_cnt, regret_pct


def _audit_paired_table_gemini_json(
    root_resolved: Path, failures: list[str]
) -> dict[str, tuple[int, int, int]]:
    defaults: dict[str, tuple[int, int, int]] = {
        "oc_raw": (65, 24, 98),
        "oc_luck": (72, 52, 91),
        "inproc_raw": (95, 62, 140),
    }
    p_path = _require_nonempty_file(root_resolved, PAIRED_GEMINI_JSON, failures)
    if p_path is None:
        return defaults
    p_obj = _load_json(p_path, PAIRED_GEMINI_JSON, failures)
    if p_obj is None:
        return defaults
    if not isinstance(p_obj, list) or not p_obj or not all(isinstance(r, dict) for r in p_obj):
        failures.append(f"{PAIRED_GEMINI_JSON} must be a non-empty JSON list of row objects")
        return defaults

    oc_hard = next(
        (
            r
            for r in p_obj
            if r.get("group") == "v1.4/opencode-gemini-4-carbon"
            and r.get("tier") == "hard"
            and "alternative" not in str(r.get("label", "")).lower()
        ),
        None,
    )
    if oc_hard is None:
        failures.append(f"{PAIRED_GEMINI_JSON} missing headline hard OpenCode gemini-4-carbon row")
    else:
        if not (_is_int(oc_hard.get("n")) and int(oc_hard["n"]) == 30):
            failures.append(
                f"{PAIRED_GEMINI_JSON} hard OpenCode row expected n=30, got {oc_hard.get('n')!r}"
            )
        if all(_is_finite_number(oc_hard.get(k)) for k in ("ratio", "ratio_lo", "ratio_hi")):
            oc_raw = (
                int(round(float(oc_hard["ratio"]) * 100.0)),
                int(round(float(oc_hard["ratio_lo"]) * 100.0)),
                int(round(float(oc_hard["ratio_hi"]) * 100.0)),
            )
            if oc_raw != (65, 24, 98):
                failures.append(
                    f"{PAIRED_GEMINI_JSON} hard OpenCode raw ratio expected 65% [24%, 98%], got {oc_raw}"
                )
            defaults["oc_raw"] = oc_raw
        else:
            failures.append(f"{PAIRED_GEMINI_JSON} hard OpenCode row missing finite ratio/CI")

        if all(
            _is_finite_number(oc_hard.get(k))
            for k in ("post_expected_ratio", "post_expected_lo", "post_expected_hi")
        ):
            oc_luck = (
                int(round(float(oc_hard["post_expected_ratio"]) * 100.0)),
                int(round(float(oc_hard["post_expected_lo"]) * 100.0)),
                int(round(float(oc_hard["post_expected_hi"]) * 100.0)),
            )
            if oc_luck != (72, 52, 91):
                failures.append(
                    f"{PAIRED_GEMINI_JSON} hard OpenCode luck-adjusted ratio expected 72% [52%, 91%], got {oc_luck}"
                )
            defaults["oc_luck"] = oc_luck
        else:
            failures.append(
                f"{PAIRED_GEMINI_JSON} hard OpenCode row missing finite post_expected_ratio/CI"
            )

    inproc_hard = next(
        (
            r
            for r in p_obj
            if r.get("group") == "v1.4/inproc-gemini-4-carbon" and r.get("tier") == "hard"
        ),
        None,
    )
    if inproc_hard is None:
        failures.append(f"{PAIRED_GEMINI_JSON} missing hard in-process gemini-4-carbon row")
    else:
        if not (_is_int(inproc_hard.get("n")) and int(inproc_hard["n"]) == 30):
            failures.append(
                f"{PAIRED_GEMINI_JSON} hard in-process row expected n=30, got {inproc_hard.get('n')!r}"
            )
        if all(_is_finite_number(inproc_hard.get(k)) for k in ("ratio", "ratio_lo", "ratio_hi")):
            ip_raw = (
                int(round(float(inproc_hard["ratio"]) * 100.0)),
                int(round(float(inproc_hard["ratio_lo"]) * 100.0)),
                int(round(float(inproc_hard["ratio_hi"]) * 100.0)),
            )
            if ip_raw != (95, 62, 140):
                failures.append(
                    f"{PAIRED_GEMINI_JSON} hard in-process raw ratio expected 95% [62%, 140%], got {ip_raw}"
                )
            defaults["inproc_raw"] = ip_raw
        else:
            failures.append(f"{PAIRED_GEMINI_JSON} hard in-process row missing finite ratio/CI")

    return defaults


def _audit_gemini_full_writeup_parity(
    rel_doc: str,
    raw_txt: str,
    *,
    require_literal_91: bool,
    ladder_eps: int,
    dash_calls: int,
    dash_cached_pct: float,
    dash_cost_usd: float,
    blind_vals: tuple[int, int, int, int, int, int],
    paired_vals: dict[str, tuple[int, int, int]],
    failures: list[str],
) -> None:
    txt = _norm_dashes(raw_txt)
    if not _has_int_token(txt, ladder_eps):
        failures.append(f"{rel_doc} missing ladder episode count '{ladder_eps}'")
    if re.search(rf"\b{EXPECTED_LADDER_CELLS}\s+(?:ladder\s+)?cells\b", txt, re.IGNORECASE) is None:
        failures.append(f"{rel_doc} missing '{EXPECTED_LADDER_CELLS} cells' ladder total")
    if (
        re.search(
            rf"\b{EXPECTED_LADDER_EXCL_PARITY}\s+of\s+{EXPECTED_LADDER_CELLS}\b|"
            rf"excludes\s+solver\s+parity\s+in\s+{EXPECTED_LADDER_EXCL_PARITY}\b",
            txt,
            re.IGNORECASE,
        )
        is None
    ):
        failures.append(
            f"{rel_doc} missing '{EXPECTED_LADDER_EXCL_PARITY}' of '{EXPECTED_LADDER_CELLS}' cells excluding solver parity"
        )
    if _ci_bracket_rx(106, 94, 126).search(txt) is None or "$1.93" not in txt or re.search(r"\bn\s*=\s*10\b", txt) is None:
        failures.append(
            f"{rel_doc} missing hard gemini-4-carbon high 106% [94, 126] (n=10, $1.93/ep) ladder parity"
        )
    if (
        _ci_bracket_rx(88, 51, 138).search(txt) is None
        or re.search(r"\$0\.45\b|\$0\.42-0\.45\b", txt) is None
    ):
        failures.append(
            f"{rel_doc} missing hard 3.6-flash high 88% [51, 138] ($0.45/ep) ladder parity"
        )
    if (
        _ci_bracket_rx(87, 50, 147).search(txt) is None
        or "$0.42" not in txt
        or re.search(r"\bn\s*=\s*40\b", txt) is None
        or "73/80" not in txt
    ):
        failures.append(
            f"{rel_doc} missing hard 3.6-flash medium 87% [50, 147] ($0.42/ep, n=40, 73/80 correct) ladder parity"
        )
    if (
        re.search(
            rf"3\.1-flash-lite[^\n]*below\s+do[-_\s]nothing\s+in\s+(?:{EXPECTED_FLASH_LITE_CELLS}/{EXPECTED_FLASH_LITE_CELLS}|all\s+{EXPECTED_FLASH_LITE_CELLS})\b",
            txt,
            re.IGNORECASE,
        )
        is None
    ):
        failures.append(
            f"{rel_doc} missing 3.1-flash-lite below do_nothing in 8/8 cells parity"
        )

    if (
        re.search(
            rf"\b{EXPECTED_SWARM_ATTEMPTS}\s+(?:ledger-verified\s+|gemini\s+|red-team\s+)*attacks\b",
            txt,
            re.IGNORECASE,
        )
        is None
    ):
        failures.append(f"{rel_doc} missing '{EXPECTED_SWARM_ATTEMPTS}' ledger-verified attacks")
    has_split = (
        re.search(rf"\b{EXPECTED_SWARM_WHITEBOX}\s+whitebox\b", txt, re.IGNORECASE) is not None
        and re.search(rf"\b{EXPECTED_SWARM_BLACKBOX}\s+blackbox\b", txt, re.IGNORECASE) is not None
        and re.search(rf"\b{EXPECTED_SWARM_MCP_RERUNS}\s+(?:mcp\s+)?re-?runs\b", txt, re.IGNORECASE) is not None
    )
    if (
        require_literal_91
        and re.search(rf"(?<![0-9.]){EXPECTED_SWARM_FINISHED}(?![0-9%])", txt) is None
    ):
        failures.append(
            f"{rel_doc} missing '{EXPECTED_SWARM_FINISHED}' primary finished attacker count"
        )
    if not has_split:
        failures.append(
            f"{rel_doc} missing swarm split ({EXPECTED_SWARM_WHITEBOX} whitebox + {EXPECTED_SWARM_BLACKBOX} blackbox + {EXPECTED_SWARM_MCP_RERUNS} MCP reruns)"
        )
    if ZERO_EXPLOITS_PROSE_RX.search(txt) is None:
        failures.append(f"{rel_doc} missing '0 verified exploits' agreement with swarm.json")
    if re.search(rf"\b{EXPECTED_SWARM_CONTROL}/{EXPECTED_SWARM_CONTROL}\b", txt) is None:
        failures.append(
            f"{rel_doc} missing '{EXPECTED_SWARM_CONTROL}/{EXPECTED_SWARM_CONTROL}' positive-control agreement with swarm_control.json"
        )

    if (
        f"{EXPECTED_SIG_OFF_REJECTED}/{EXPECTED_SIG_OFF_REJECTED}" not in txt
        or "400 INVALID_ARGUMENT" not in txt
        or f"0/{EXPECTED_SIG_ON_CALLS}" not in txt
    ):
        failures.append(
            f"{rel_doc} missing 10/10 (400 INVALID_ARGUMENT) vs 0/{EXPECTED_SIG_ON_CALLS} thought-signature ablation parity"
        )
    if not all(
        tok in txt
        for tok in (
            f"${EXPECTED_ATLAS_UNCACHED_USD:.2f}",
            f"${EXPECTED_ATLAS_PAID_USD:.2f}",
            f"{EXPECTED_ATLAS_PCT_SAVED:.1f}%",
            str(EXPECTED_ATLAS_CALLS),
        )
    ):
        failures.append(
            f"{rel_doc} missing Atlas explicit-cache parity ($58.56 -> $21.72, 62.9% saved over 464 calls)"
        )
    if not all(
        tok in txt
        for tok in (
            f"{EXPECTED_PROG_PCT_SAVED:.1f}%",
            f"${EXPECTED_PROG_SAVED_USD:.2f}",
            f"${EXPECTED_PROG_UNCACHED_USD:.2f}",
            _fmt_int_commas(EXPECTED_PROG_CALLS),
        )
    ):
        failures.append(
            f"{rel_doc} missing programme cache parity (75.9%, $678.19 of $893.08 over 29,150 calls)"
        )

    dash_calls_str = _fmt_int_commas(dash_calls)
    dash_pct_str = f"{dash_cached_pct:.1f}%"
    dash_cost_str = f"${dash_cost_usd:.2f}"
    if not all(tok in txt for tok in (dash_calls_str, dash_pct_str, dash_cost_str)):
        failures.append(
            f"{rel_doc} missing dashboard usage parity ({dash_calls_str} calls, {dash_pct_str} cached, {dash_cost_str})"
        )

    b_eps, b_rec, b_tags, b_new, b_cited, b_regret = blind_vals
    if (
        re.search(rf"\b{b_rec}\s+of\s+{b_tags}\b", txt, re.IGNORECASE) is None
        or re.search(rf"\bnam(?:es|ed)\s+{b_new}\s+(?:new|modes)\b", txt, re.IGNORECASE) is None
        or re.search(rf"\b{b_eps}\s+(?:trajectories|episodes)\b", txt, re.IGNORECASE) is None
        or re.search(rf"\b(?:{b_cited}\s+cited\s+steps|cited\s+{b_cited}\s+steps)\b", txt, re.IGNORECASE) is None
        or re.search(rf"\b{b_regret}%\s+of\s+(?:solver\s+|all\s+)?regret\b", txt, re.IGNORECASE) is None
    ):
        failures.append(
            f"{rel_doc} missing blind Atlas parity ({b_rec} of {b_tags} modes + {b_new} new, {b_eps} episodes, {b_cited} cited steps, {b_regret}% regret)"
        )

    oc_r = paired_vals["oc_raw"]
    oc_l = paired_vals["oc_luck"]
    ip_r = paired_vals["inproc_raw"]
    if (
        _ci_bracket_rx(*oc_r).search(txt) is None
        or _ci_bracket_rx(*oc_l).search(txt) is None
        or _ci_bracket_rx(*ip_r).search(txt) is None
        or "v1.4" not in txt
        or re.search(r"\bn\s*=\s*30\b", txt) is None
    ):
        failures.append(
            f"{rel_doc} missing AfterQuery v1.4 hard (n=30) harness honesty parity (65% [24%, 98%] raw / 72% [52%, 91%] luck-adj OpenCode vs 95% [62%, 140%] in-process)"
        )


def _audit_pitch_gemini_parity(
    raw_txt: str,
    *,
    ladder_eps: int,
    dash_calls: int,
    blind_vals: tuple[int, int, int, int, int, int],
    failures: list[str],
) -> None:
    rel_doc = "pitch/GEMINI.md"
    txt = _norm_dashes(raw_txt)
    if "docs/gemini/SUBMISSION.md" not in txt:
        failures.append(f"{rel_doc} missing pointer to docs/gemini/SUBMISSION.md")
    if not _has_int_token(txt, ladder_eps):
        failures.append(f"{rel_doc} missing ladder episode count '{ladder_eps}'")
    if re.search(rf"\b{EXPECTED_SWARM_ATTEMPTS}\s+ledger-verified\b", txt, re.IGNORECASE) is None:
        failures.append(f"{rel_doc} missing '{EXPECTED_SWARM_ATTEMPTS}' ledger-verified attacks")
    if (
        re.search(rf"\b{EXPECTED_SWARM_WHITEBOX}\s+whitebox\b", txt, re.IGNORECASE) is None
        or re.search(rf"\b{EXPECTED_SWARM_BLACKBOX}\s+blackbox\b", txt, re.IGNORECASE) is None
        or re.search(rf"\b{EXPECTED_SWARM_MCP_RERUNS}\s+(?:mcp\s+)?re-?runs\b", txt, re.IGNORECASE) is None
    ):
        failures.append(
            f"{rel_doc} missing swarm split ({EXPECTED_SWARM_WHITEBOX} whitebox + {EXPECTED_SWARM_BLACKBOX} blackbox + {EXPECTED_SWARM_MCP_RERUNS} reruns)"
        )
    if (
        re.search(
            rf"\b{EXPECTED_SWARM_CONTROL}/{EXPECTED_SWARM_CONTROL}\b|"
            rf"\b{EXPECTED_SWARM_CONTROL}\s+times\s+out\s+of\s+{EXPECTED_SWARM_CONTROL}\b",
            txt,
            re.IGNORECASE,
        )
        is None
    ):
        failures.append(
            f"{rel_doc} missing '{EXPECTED_SWARM_CONTROL}/{EXPECTED_SWARM_CONTROL}' positive-control parity"
        )
    _, b_rec, b_tags, b_new, _, _ = blind_vals
    if (
        re.search(rf"\b{b_rec}\s+of\s+{b_tags}\b", txt, re.IGNORECASE) is None
        or re.search(rf"\bnam(?:es|ed)\s+{b_new}\s+new\b", txt, re.IGNORECASE) is None
    ):
        failures.append(
            f"{rel_doc} missing blind Atlas '{b_rec} of {b_tags}' + '{b_new} new' parity"
        )
    dash_calls_str = _fmt_int_commas(dash_calls)
    if dash_calls_str not in txt:
        failures.append(f"{rel_doc} missing dashboard call total '{dash_calls_str}'")


def _audit_video_2min_parity(
    raw_txt: str,
    *,
    ladder_eps: int,
    dash_cached_pct: float,
    dash_cost_usd: float,
    blind_vals: tuple[int, int, int, int, int, int],
    failures: list[str],
) -> None:
    rel_doc = "docs/gemini/VIDEO-2MIN.md"
    txt = _norm_dashes(raw_txt)
    if not (
        _has_int_token(txt, ladder_eps)
        or re.search(r"five\s+hundred\s+eighty-?seven", txt, re.IGNORECASE) is not None
    ):
        failures.append(f"{rel_doc} missing ladder episode count ({ladder_eps}) in shot list or VO")
    if (
        re.search(r"106%|one\s+hundred\s+six\s+percent", txt, re.IGNORECASE) is None
        or re.search(
            r"\[\s*94%?\s*,\s*126%?\s*\]|ninety-?four\s+to\s+one\s+hundred\s+twenty-?six",
            txt,
            re.IGNORECASE,
        )
        is None
        or re.search(r"\$1\.93\b|one\s+dollar\s+ninety-?three", txt, re.IGNORECASE) is None
    ):
        failures.append(
            f"{rel_doc} missing hard gemini-4-carbon high 106% [94, 126] ($1.93/ep) VO/shot parity"
        )
    if (
        re.search(r"88%|eighty-?eight\s+percent", txt, re.IGNORECASE) is None
        or re.search(
            r"\[\s*51%?\s*,\s*138%?\s*\]|fifty-?one\s+to\s+one\s+hundred\s+thirty-?eight",
            txt,
            re.IGNORECASE,
        )
        is None
        or re.search(r"\$0\.45\b|forty-?five\s+cents", txt, re.IGNORECASE) is None
    ):
        failures.append(
            f"{rel_doc} missing hard 3.6-flash high 88% [51, 138] ($0.45/ep) VO/shot parity"
        )
    if (
        not (
            _has_int_token(txt, EXPECTED_SWARM_ATTEMPTS)
            or re.search(r"one\s+hundred\s+attacks", txt, re.IGNORECASE) is not None
        )
        or not _has_int_token(txt, EXPECTED_SWARM_FINISHED)
        or re.search(rf"\b{EXPECTED_SWARM_WHITEBOX}(?:/{EXPECTED_SWARM_FINISHED})?\s+whitebox\b", txt, re.IGNORECASE) is None
        or re.search(rf"\b{EXPECTED_SWARM_MCP_RERUNS}\s+(?:mcp\s+)?re-?runs\b", txt, re.IGNORECASE) is None
        or re.search(r"(?:(?<!\d)0|zero)\s+verified\s+exploits", txt, re.IGNORECASE) is None
        or re.search(r"\b4/4\b|four\s+of\s+four", txt, re.IGNORECASE) is None
    ):
        failures.append(
            f"{rel_doc} missing swarm parity (100 attacks, 91 primary, 75 whitebox, 9 MCP reruns, 0 exploits, 4/4 control)"
        )

    b_eps, b_rec, b_tags, b_new, _, b_regret = blind_vals
    has_blind_placeholders = all(
        ph in txt
        for ph in (
            "{blind_episodes}",
            "{blind_recovered}",
            "{blind_tags}",
            "{blind_new}",
            "{blind_regret_covered}",
        )
    )
    has_blind_literals = (
        _has_int_token(txt, b_eps)
        and re.search(rf"\b{b_rec}\s+of\s+{b_tags}\b", txt, re.IGNORECASE) is not None
        and re.search(rf"\b{b_new}\s+new\b", txt, re.IGNORECASE) is not None
        and re.search(rf"\b{b_regret}%|twenty-?one\s+percent", txt, re.IGNORECASE) is not None
    )
    if not (has_blind_placeholders or has_blind_literals):
        failures.append(
            f"{rel_doc} missing blind Atlas placeholders or literal {b_eps} / {b_rec} of {b_tags} / {b_new} new / {b_regret}% parity"
        )

    has_usage_placeholders = "{cache_share}" in txt and "{cost}" in txt
    has_usage_literals = f"{dash_cached_pct:.1f}%" in txt and f"${dash_cost_usd:.2f}" in txt
    if not (has_usage_placeholders or has_usage_literals):
        failures.append(
            f"{rel_doc} missing usage ledger placeholders ({{cache_share}}, {{cost}}) or literal {dash_cached_pct:.1f}% / ${dash_cost_usd:.2f}"
        )
    for feat_rx, feat_name in (
        (r"thinking[-_\s]level", "thinking_level"),
        (r"thought[-_\s]signature", "thought_signature"),
        (r"explicit\s+cache", "explicit cache"),
    ):
        if re.search(feat_rx, txt, re.IGNORECASE) is None:
            failures.append(f"{rel_doc} missing essential Gemini feature '{feat_name}'")


def check_gemini_surface(root: Path = ROOT) -> CheckResult:
    name = CHECK_GEMINI
    root_resolved = root.resolve()
    failures: list[str] = []

    swarm_json_path = _require_nonempty_file(root_resolved, "results/gemini/swarm.json", failures)
    swarm_md_path = _require_nonempty_file(root_resolved, "results/gemini/swarm.md", failures)
    swarm_ctrl_path = _require_nonempty_file(root_resolved, "results/gemini/swarm_control.md", failures)
    gallery_path = _require_nonempty_file(root_resolved, "docs/reports/failure_gallery.md", failures)
    sub_path = _require_nonempty_file(root_resolved, "docs/gemini/SUBMISSION.md", failures)
    pitch_path = _require_nonempty_file(root_resolved, "pitch/GEMINI.md", failures)

    finished_json: int | None = None
    exploits_json: int | None = None

    if swarm_json_path is not None:
        swarm_obj = _load_json(swarm_json_path, "results/gemini/swarm.json", failures)
        if swarm_obj is not None:
            if not isinstance(swarm_obj, dict):
                failures.append("results/gemini/swarm.json must be a JSON object")
            else:
                counts = swarm_obj.get("counts")
                if not isinstance(counts, dict):
                    failures.append("results/gemini/swarm.json missing 'counts' object")
                else:
                    raw_att = counts.get("attempts")
                    if not (_is_int(raw_att) and int(raw_att) == EXPECTED_SWARM_ATTEMPTS):
                        failures.append(
                            f"results/gemini/swarm.json counts.attempts expected {EXPECTED_SWARM_ATTEMPTS}, got {raw_att!r}"
                        )
                    raw_lv = counts.get("ledger_verified")
                    if not (_is_int(raw_lv) and int(raw_lv) == EXPECTED_SWARM_LEDGER_VERIFIED):
                        failures.append(
                            f"results/gemini/swarm.json counts.ledger_verified expected {EXPECTED_SWARM_LEDGER_VERIFIED}, got {raw_lv!r}"
                        )
                    raw_exp = counts.get("exploits")
                    if not isinstance(raw_exp, int) or isinstance(raw_exp, bool):
                        failures.append(f"results/gemini/swarm.json counts.exploits invalid: {raw_exp!r}")
                    else:
                        exploits_json = raw_exp
                        if exploits_json != EXPECTED_SWARM_EXPLOITS:
                            failures.append(
                                f"results/gemini/swarm.json counts.exploits expected {EXPECTED_SWARM_EXPLOITS}, got {exploits_json}"
                            )

                waves = swarm_obj.get("waves")
                if not isinstance(waves, list) or not waves:
                    failures.append("results/gemini/swarm.json missing non-empty 'waves' list")
                else:
                    wave_finished_vals: list[int] = []
                    bad_wave = False
                    for idx, wave in enumerate(waves):
                        if not isinstance(wave, dict) or not isinstance(wave.get("finished"), int) or isinstance(wave.get("finished"), bool):
                            failures.append(f"results/gemini/swarm.json waves[{idx}] missing integer 'finished'")
                            bad_wave = True
                        else:
                            wave_finished_vals.append(int(wave["finished"]))
                    if not bad_wave:
                        finished_json = sum(wave_finished_vals)
                        if finished_json != EXPECTED_SWARM_FINISHED:
                            failures.append(
                                f"results/gemini/swarm.json finished attackers expected {EXPECTED_SWARM_FINISHED}, got {finished_json}"
                            )

                attempts = swarm_obj.get("attempts")
                if attempts is not None:
                    if not isinstance(attempts, list) or not attempts:
                        failures.append("results/gemini/swarm.json 'attempts' must be a non-empty list")
                    else:
                        confirmed_attempts = [
                            str(a.get("id", "?"))
                            for a in attempts
                            if isinstance(a, dict) and bool(a.get("exploit"))
                        ]
                        if confirmed_attempts:
                            failures.append(
                                f"results/gemini/swarm.json has exploit=True attempt(s): {', '.join(confirmed_attempts[:5])}"
                            )

    if swarm_md_path is not None:
        swarm_md = swarm_md_path.read_text(encoding="utf-8", errors="replace")
        exp_match = SWARM_VERIFIED_EXPLOITS_RX.search(swarm_md)
        if exp_match is None:
            failures.append("results/gemini/swarm.md missing 'Verified exploits: 0' summary line")
        else:
            md_exp = int(exp_match.group(1))
            if md_exp != EXPECTED_SWARM_EXPLOITS:
                failures.append(
                    f"results/gemini/swarm.md verified exploits expected {EXPECTED_SWARM_EXPLOITS}, got {md_exp}"
                )
            if exploits_json is not None and md_exp != exploits_json:
                failures.append(
                    f"swarm.md verified exploits ({md_exp}) disagrees with swarm.json ({exploits_json})"
                )

        has_wave_row, row_fin, row_exp = _extract_swarm_md_wave_totals(swarm_md)
        if has_wave_row:
            if row_fin != EXPECTED_SWARM_FINISHED:
                failures.append(
                    f"results/gemini/swarm.md 'all real waves' finished expected {EXPECTED_SWARM_FINISHED}, got {row_fin!r}"
                )
            elif finished_json is not None and row_fin != finished_json:
                failures.append(
                    f"swarm.md finished ({row_fin}) disagrees with swarm.json ({finished_json})"
                )
            if row_exp is not None and row_exp != EXPECTED_SWARM_EXPLOITS:
                failures.append(
                    f"results/gemini/swarm.md 'all real waves' verified exploits expected {EXPECTED_SWARM_EXPLOITS}, got {row_exp}"
                )
        else:
            if not _has_int_token(swarm_md, EXPECTED_SWARM_FINISHED):
                failures.append(
                    f"results/gemini/swarm.md missing {EXPECTED_SWARM_FINISHED} finished attackers total"
                )

    for rel_doc, doc_path in (
        ("results/gemini/swarm_control.md", swarm_ctrl_path),
        ("docs/reports/failure_gallery.md", gallery_path),
    ):
        if doc_path is not None and not doc_path.read_text(encoding="utf-8", errors="replace").strip():
            failures.append(f"whitespace-only file: {rel_doc}")

    for rel_doc, doc_path in (
        ("docs/gemini/SUBMISSION.md", sub_path),
        ("pitch/GEMINI.md", pitch_path),
    ):
        if doc_path is None:
            continue
        txt = doc_path.read_text(encoding="utf-8", errors="replace")
        has_91_or_split = _has_int_token(txt, EXPECTED_SWARM_FINISHED) or (
            EXPECTED_SWARM_FINISHED == 91
            and _has_int_token(txt, 75)
            and _has_int_token(txt, 16)
        )
        if not has_91_or_split:
            failures.append(
                f"{rel_doc} missing PR 41 finished attacker count '{EXPECTED_SWARM_FINISHED}' (or '75' whitebox + '16' blackbox)"
            )
        if ZERO_EXPLOITS_PROSE_RX.search(txt) is None:
            failures.append(f"{rel_doc} missing '0 verified exploits' agreement with swarm.json")

    ctrl_exp = _audit_swarm_control_json(root_resolved, failures)
    if swarm_ctrl_path is not None:
        ctrl_md_txt = swarm_ctrl_path.read_text(encoding="utf-8", errors="replace")
        ctrl_match = SWARM_VERIFIED_EXPLOITS_RX.search(ctrl_md_txt)
        if ctrl_match is None or int(ctrl_match.group(1)) != ctrl_exp:
            failures.append(
                f"results/gemini/swarm_control.md expected Verified exploits: {ctrl_exp} matching swarm_control.json"
            )

    dash_calls, dash_cached_pct, dash_cost_usd = _audit_dashboard_html(root_resolved, failures)
    blind_vals = _audit_atlas_blind_json(root_resolved, failures)
    paired_vals = _audit_paired_table_gemini_json(root_resolved, failures)

    gemini_dir = root_resolved / "results" / "gemini"
    replay_dirs = sorted(p for p in gemini_dir.glob("replay*") if p.is_dir()) if gemini_dir.is_dir() else []
    if not replay_dirs:
        failures.append("missing results/gemini/replay* gateway cache directories for make lab-replay")
    else:
        for rdir in replay_dirs:
            rel_rdir = rdir.relative_to(root_resolved).as_posix()
            if rdir.name == "replay":
                desc = rdir / "showcase.json" if (rdir / "showcase.json").exists() else (rdir / "manifest.json")
                desc_rel = f"{rel_rdir}/{desc.name}"
                if not desc.is_file() or desc.stat().st_size <= 0:
                    failures.append(f"missing or empty replay descriptor: {rel_rdir}/showcase.json")
                else:
                    desc_obj = _load_json(desc, desc_rel, failures)
                    if desc_obj is not None and (not isinstance(desc_obj, dict) or not desc_obj):
                        failures.append(f"{desc_rel} must be a non-empty JSON object")
            else:
                man = rdir / "manifest.json"
                man_rel = f"{rel_rdir}/manifest.json"
                if not man.is_file() or man.stat().st_size <= 0:
                    failures.append(f"missing or empty replay manifest: {man_rel}")
                else:
                    man_obj = _load_json(man, man_rel, failures)
                    if man_obj is not None and (not isinstance(man_obj, dict) or not man_obj):
                        failures.append(f"{man_rel} must be a non-empty JSON object")

            gz_files = [f for f in rdir.rglob("*.json.gz") if f.is_file()]
            if not gz_files:
                failures.append(f"{rel_rdir}: gateway cache directory has 0 *.json.gz response files")
            else:
                empty_gz = [f for f in gz_files if f.stat().st_size <= 0]
                if empty_gz:
                    failures.append(
                        f"{rel_rdir}: {len(empty_gz)} empty *.json.gz cache file(s) (0 bytes)"
                    )

    sub_long_txt, vid2_txt, ladder_eps = _audit_gemini_ladder_and_ablations(root_resolved, failures)
    eff_ladder_eps = ladder_eps if ladder_eps is not None else EXPECTED_LADDER_EPISODES

    if sub_path is not None:
        sub_txt = sub_path.read_text(encoding="utf-8", errors="replace")
        if sub_txt.strip():
            _audit_gemini_full_writeup_parity(
                "docs/gemini/SUBMISSION.md",
                sub_txt,
                require_literal_91=False,
                ladder_eps=eff_ladder_eps,
                dash_calls=dash_calls,
                dash_cached_pct=dash_cached_pct,
                dash_cost_usd=dash_cost_usd,
                blind_vals=blind_vals,
                paired_vals=paired_vals,
                failures=failures,
            )
    if sub_long_txt is not None:
        _audit_gemini_full_writeup_parity(
            "docs/gemini/SUBMISSION-LONG.md",
            sub_long_txt,
            require_literal_91=True,
            ladder_eps=eff_ladder_eps,
            dash_calls=dash_calls,
            dash_cached_pct=dash_cached_pct,
            dash_cost_usd=dash_cost_usd,
            blind_vals=blind_vals,
            paired_vals=paired_vals,
            failures=failures,
        )
    if pitch_path is not None:
        pitch_txt = pitch_path.read_text(encoding="utf-8", errors="replace")
        if pitch_txt.strip():
            _audit_pitch_gemini_parity(
                pitch_txt,
                ladder_eps=eff_ladder_eps,
                dash_calls=dash_calls,
                blind_vals=blind_vals,
                failures=failures,
            )
    if vid2_txt is not None:
        _audit_video_2min_parity(
            vid2_txt,
            ladder_eps=eff_ladder_eps,
            dash_cached_pct=dash_cached_pct,
            dash_cost_usd=dash_cost_usd,
            blind_vals=blind_vals,
            failures=failures,
        )

    if failures:
        return CheckResult(
            name,
            "FAIL",
            f"{len(failures)} Gemini Lab replay/swarm/ladder/ablation surface violation(s)",
            failures,
        )
    return CheckResult(
        name,
        "PASS",
        f"PR 41 swarm ({EXPECTED_SWARM_ATTEMPTS} attacks, {EXPECTED_SWARM_FINISHED} finished, {EXPECTED_SWARM_EXPLOITS} exploits, {ctrl_exp}/{ctrl_exp} control), ladder ({ladder_eps} episodes), 3 ablations, blind Atlas, dashboard ({dash_calls:,} calls), submission/pitch/video parity, and {len(replay_dirs)} replay* cache dir(s) verified",
    )


def _audit_gemini_ladder_and_ablations(
    root_resolved: Path, failures: list[str]
) -> tuple[str | None, str | None, int | None]:
    sub_long_txt = _require_nonempty_text_file(
        root_resolved, "docs/gemini/SUBMISSION-LONG.md", failures
    )
    vid2_txt = _require_nonempty_text_file(
        root_resolved, "docs/gemini/VIDEO-2MIN.md", failures
    )

    for png_rel in GEMINI_FRONTIER_PNGS:
        _require_valid_png(root_resolved, png_rel, failures)

    ladder_episodes: int | None = None
    ladder_path = _require_nonempty_file(root_resolved, "results/gemini/ladder.json", failures)
    if ladder_path is not None:
        ladder_obj = _load_json(ladder_path, "results/gemini/ladder.json", failures)
        if ladder_obj is not None:
            if not isinstance(ladder_obj, dict):
                failures.append("results/gemini/ladder.json must be a JSON object")
            else:
                raw_eps = ladder_obj.get("episodes")
                if not _is_int(raw_eps) or int(raw_eps) < MIN_LADDER_EPISODES:
                    failures.append(
                        f"results/gemini/ladder.json expected integer episodes >= {MIN_LADDER_EPISODES}, got {raw_eps!r}"
                    )
                else:
                    ladder_episodes = int(raw_eps)

                rows = ladder_obj.get("rows")
                if not isinstance(rows, list) or not rows:
                    failures.append("results/gemini/ladder.json missing non-empty 'rows' list")
                else:
                    bad_row = False
                    row_n_vals: list[int] = []
                    for idx, row in enumerate(rows):
                        if (
                            not isinstance(row, dict)
                            or not _is_int(row.get("n"))
                            or int(row["n"]) <= 0
                        ):
                            failures.append(
                                f"results/gemini/ladder.json rows[{idx}] missing positive integer 'n'"
                            )
                            bad_row = True
                        else:
                            row_n_vals.append(int(row["n"]))
                    if not bad_row:
                        total_row_n = sum(row_n_vals)
                        if total_row_n < MIN_LADDER_EPISODES:
                            failures.append(
                                f"results/gemini/ladder.json sum(rows.n) expected >= {MIN_LADDER_EPISODES}, got {total_row_n}"
                            )
                        elif ladder_episodes is not None and total_row_n != ladder_episodes:
                            failures.append(
                                f"results/gemini/ladder.json sum(rows.n)={total_row_n} disagrees with episodes={ladder_episodes}"
                            )

    abl_json_path = _require_nonempty_file(root_resolved, "results/gemini/ablations.json", failures)
    if abl_json_path is not None:
        abl_obj = _load_json(abl_json_path, "results/gemini/ablations.json", failures)
        if abl_obj is not None:
            if not isinstance(abl_obj, dict):
                failures.append("results/gemini/ablations.json must be a JSON object")
            else:
                ts = abl_obj.get("thought_signatures")
                if not isinstance(ts, dict):
                    failures.append("results/gemini/ablations.json missing 'thought_signatures' object")
                else:
                    off = ts.get("off")
                    on = ts.get("on")
                    if not isinstance(off, dict):
                        failures.append("results/gemini/ablations.json missing thought_signatures.off")
                    else:
                        att = off.get("episodes_attempted")
                        val_off = off.get("valid_episodes")
                        errs_off = off.get("api_errors")
                        rej_seeds = off.get("second_call_rejected_seeds")
                        rej_rate = off.get("rejection_rate_of_function_call_turns")
                        if not (_is_int(att) and int(att) == 10):
                            failures.append(
                                f"results/gemini/ablations.json thought_signatures.off.episodes_attempted expected 10, got {att!r}"
                            )
                        if not (_is_int(val_off) and int(val_off) == 0):
                            failures.append(
                                f"results/gemini/ablations.json thought_signatures.off.valid_episodes expected 0, got {val_off!r}"
                            )
                        if not (_is_int(errs_off) and int(errs_off) == 10):
                            failures.append(
                                f"results/gemini/ablations.json thought_signatures.off.api_errors expected 10, got {errs_off!r}"
                            )
                        if not (isinstance(rej_seeds, list) and len(rej_seeds) == 10):
                            failures.append(
                                "results/gemini/ablations.json thought_signatures.off expected 10 rejected seeds (10/10)"
                            )
                        if not (
                            _is_finite_number(rej_rate)
                            and math.isclose(float(rej_rate), 1.0, abs_tol=1e-6)
                        ):
                            failures.append(
                                f"results/gemini/ablations.json thought_signatures.off rejection_rate expected 1.0, got {rej_rate!r}"
                            )
                    if not isinstance(on, dict):
                        failures.append("results/gemini/ablations.json missing thought_signatures.on")
                    else:
                        val_on = on.get("valid_episodes")
                        errs_on = on.get("api_errors")
                        if not (_is_int(val_on) and int(val_on) == 10):
                            failures.append(
                                f"results/gemini/ablations.json thought_signatures.on.valid_episodes expected 10, got {val_on!r}"
                            )
                        if not (_is_int(errs_on) and int(errs_on) == 0):
                            failures.append(
                                f"results/gemini/ablations.json thought_signatures.on.api_errors expected 0, got {errs_on!r}"
                            )

                ec = abl_obj.get("explicit_cache")
                if not isinstance(ec, dict):
                    failures.append("results/gemini/ablations.json missing 'explicit_cache' object")
                else:
                    for scope_key in ("programme", "atlas_plus_gallery"):
                        scope = ec.get(scope_key)
                        if scope_key == "atlas_plus_gallery" and scope is None:
                            scope = ec.get("atlas")
                        if not isinstance(scope, dict):
                            failures.append(
                                f"results/gemini/ablations.json explicit_cache missing '{scope_key}' summary"
                            )
                            continue
                        if not _is_positive_number(scope.get("cached_tokens")):
                            failures.append(
                                f"results/gemini/ablations.json explicit_cache.{scope_key} missing positive cached_tokens"
                            )
                        if not _is_positive_number(scope.get("usd_saved")) or not _is_positive_number(
                            scope.get("pct_saved")
                        ):
                            failures.append(
                                f"results/gemini/ablations.json explicit_cache.{scope_key} missing positive usd_saved/pct_saved"
                            )
                        paid = scope.get("usd_paid")
                        uncached = scope.get("usd_if_uncached")
                        if not (
                            _is_positive_number(paid)
                            and _is_positive_number(uncached)
                            and float(paid) < float(uncached)
                        ):
                            failures.append(
                                f"results/gemini/ablations.json explicit_cache.{scope_key} expected usd_paid < usd_if_uncached"
                            )

                sweep = abl_obj.get("thinking_sweep")
                if not isinstance(sweep, list) or len(sweep) < 2:
                    failures.append("results/gemini/ablations.json missing non-trivial 'thinking_sweep' list")
                else:
                    levels_by_pair: dict[tuple[str, str], set[str]] = {}
                    for idx, cell in enumerate(sweep):
                        if not isinstance(cell, dict):
                            failures.append(f"results/gemini/ablations.json thinking_sweep[{idx}] must be an object")
                            continue
                        model_val = cell.get("model")
                        level_val = cell.get("level")
                        tier_val = cell.get("tier")
                        n_val = cell.get("n")
                        pct_val = cell.get("pct_of_solver")
                        ci_val = cell.get("ci95")
                        if not (
                            isinstance(model_val, str)
                            and model_val.strip()
                            and isinstance(level_val, str)
                            and level_val.strip()
                            and isinstance(tier_val, str)
                            and tier_val.strip()
                        ):
                            failures.append(
                                f"results/gemini/ablations.json thinking_sweep[{idx}] missing model/level/tier"
                            )
                            continue
                        if not (_is_int(n_val) and int(n_val) > 0):
                            failures.append(
                                f"results/gemini/ablations.json thinking_sweep[{idx}] missing positive integer 'n'"
                            )
                        if not _is_finite_number(pct_val):
                            failures.append(
                                f"results/gemini/ablations.json thinking_sweep[{idx}] missing numeric 'pct_of_solver'"
                            )
                        if not (
                            isinstance(ci_val, list)
                            and len(ci_val) == 2
                            and all(_is_finite_number(v) for v in ci_val)
                        ):
                            failures.append(
                                f"results/gemini/ablations.json thinking_sweep[{idx}] missing 2-element numeric 'ci95'"
                            )
                        levels_by_pair.setdefault((model_val.strip(), tier_val.strip()), set()).add(
                            level_val.strip()
                        )
                    if not any(len(lvls) >= 2 for lvls in levels_by_pair.values()):
                        failures.append(
                            "results/gemini/ablations.json thinking_sweep lacks multi-level thinking sweep on any (model, tier)"
                        )

    abl_md_txt = _require_nonempty_text_file(root_resolved, "results/gemini/ablations.md", failures)
    if abl_md_txt is not None:
        if "10/10" not in abl_md_txt or re.search(r"thought[-_\s]signature", abl_md_txt, re.IGNORECASE) is None:
            failures.append(
                "results/gemini/ablations.md missing 10/10 thought-signature rejection ablation"
            )
        if (
            re.search(r"explicit\s+(?:context\s+)?cach", abl_md_txt, re.IGNORECASE) is None
            or re.search(r"\bsaved\b", abl_md_txt, re.IGNORECASE) is None
        ):
            failures.append("results/gemini/ablations.md missing explicit cache savings ablation")
        if re.search(r"thinking[-_\s]level", abl_md_txt, re.IGNORECASE) is None:
            failures.append("results/gemini/ablations.md missing thinking-level sweep ablation")

    return sub_long_txt, vid2_txt, ladder_episodes


def _audit_audio_index(
    root_resolved: Path,
    index_rel: str,
    expected_ext: str,
    failures: list[str],
) -> int:
    idx_path = _require_nonempty_file(root_resolved, index_rel, failures)
    if idx_path is None:
        return 0
    data = _load_json(idx_path, index_rel, failures)
    if data is None:
        return 0

    if isinstance(data, list):
        entries = data
    elif isinstance(data, dict):
        entries = list(data.values())
    else:
        failures.append(f"{index_rel} must be a JSON list or object")
        return 0

    if not entries:
        failures.append(f"{index_rel} contains 0 audio entries")
        return 0

    verified = 0
    for idx, entry in enumerate(entries):
        if not isinstance(entry, dict):
            failures.append(f"{index_rel}[{idx}] must be a JSON object")
            continue
        file_name = entry.get("file")
        if not isinstance(file_name, str) or not file_name.strip():
            failures.append(f"{index_rel}[{idx}] missing non-empty 'file' field")
            continue
        clean_name = file_name.strip()
        if not clean_name.lower().endswith(expected_ext):
            failures.append(
                f"{index_rel}[{idx}] expected '{expected_ext}' audio file, got '{clean_name}'"
            )
            continue
        target = (idx_path.parent / clean_name).resolve()
        try:
            rel_target = target.relative_to(root_resolved).as_posix()
        except ValueError:
            failures.append(f"{index_rel}: audio path '{clean_name}' resolves outside repository root")
            continue
        if not target.exists() or not target.is_file():
            failures.append(f"missing referenced {expected_ext} asset from {index_rel}: {rel_target}")
            continue
        try:
            size = target.stat().st_size
        except OSError as exc:
            failures.append(f"unreadable {expected_ext} asset {rel_target}: {type(exc).__name__}")
            continue
        if size <= 0:
            failures.append(f"empty referenced {expected_ext} asset: {rel_target} (0 bytes)")
            continue
        verified += 1

    return verified


def check_media_surface(root: Path = ROOT) -> CheckResult:
    name = CHECK_MEDIA
    root_resolved = root.resolve()
    failures: list[str] = []

    for rel in (
        "game/build.py",
        "game/tests/parity.mjs",
        "scripts/demo_replay.py",
        "docs/DEMO.md",
        "docs/gemini/assets/canary-lab-2min.mp4",
    ):
        _require_nonempty_file(root_resolved, rel, failures)

    mp3_count = _audit_audio_index(root_resolved, "docs/video/vo/index.json", ".mp3", failures)
    wav_count = _audit_audio_index(
        root_resolved, "docs/gemini/assets/narration-2min/index.json", ".wav", failures
    )

    assets_dir = root_resolved / "docs" / "gemini" / "assets"
    dash_pngs = sorted(assets_dir.glob("dashboard-*.png")) if assets_dir.is_dir() else []
    if not dash_pngs:
        failures.append("missing docs/gemini/assets/dashboard-*.png files")
    else:
        for png_path in dash_pngs:
            rel_png = png_path.relative_to(root_resolved).as_posix()
            if not png_path.is_file():
                failures.append(f"dashboard asset is not a regular file: {rel_png}")
                continue
            try:
                png_size = png_path.stat().st_size
            except OSError as exc:
                failures.append(f"unreadable dashboard asset {rel_png}: {type(exc).__name__}")
                continue
            if png_size <= 0:
                failures.append(f"empty dashboard PNG asset: {rel_png} (0 bytes)")
                continue
            try:
                with png_path.open("rb") as fh:
                    head = fh.read(len(PNG_MAGIC))
            except OSError as exc:
                failures.append(f"unreadable dashboard asset {rel_png}: {type(exc).__name__}")
                continue
            if head != PNG_MAGIC:
                failures.append(f"invalid PNG magic bytes in {rel_png}")

    if failures:
        return CheckResult(
            name,
            "FAIL",
            f"{len(failures)} browser game/demo/media surface violation(s)",
            failures,
        )
    return CheckResult(
        name,
        "PASS",
        f"game/demo scripts, {mp3_count} .mp3 VO cues, {wav_count} .wav narration cues, canary-lab-2min.mp4, and {len(dash_pngs)} dashboard-*.png verified",
    )


def _has_dot_git(root: Path) -> bool:
    dot_git = root / ".git"
    return dot_git.exists() or dot_git.is_symlink()


def _parse_gitignore_file(gi_path: Path) -> list[tuple[bool, bool, bool, str]]:
    if not gi_path.is_file():
        return []
    try:
        lines = gi_path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    rules: list[tuple[bool, bool, bool, str]] = []
    for raw in lines:
        stripped = raw.strip()
        if not stripped or stripped.startswith(HASH_CHAR):
            continue
        negated = stripped.startswith("!")
        body = stripped[1:].strip() if negated else stripped
        if not body:
            continue
        dir_only = body.endswith("/")
        pat = body.strip("/")
        if not pat:
            continue
        anchored = ("/" in pat) or raw.lstrip(" !").startswith("/")
        rules.append((negated, dir_only, anchored, pat))
    return rules


def _gitignore_pat_matches(pat: str, rel_pos: str, name: str, anchored: bool) -> bool:
    if not anchored:
        return fnmatch.fnmatchcase(name, pat) or fnmatch.fnmatchcase(rel_pos, pat)
    if "**/" in pat and _gitignore_pat_matches(pat.replace("**/", ""), rel_pos, name, True):
        return True
    parts: list[str] = []
    idx = 0
    total = len(pat)
    while idx < total:
        if pat[idx : idx + 3] == "**/":
            parts.append("(?:.+/)?")
            idx += 3
        elif pat[idx : idx + 2] == "**":
            parts.append(".*")
            idx += 2
        elif pat[idx] == "*":
            parts.append("[^/]*")
            idx += 1
        elif pat[idx] == "?":
            parts.append("[^/]")
            idx += 1
        else:
            parts.append(re.escape(pat[idx]))
            idx += 1
    return re.fullmatch("".join(parts), rel_pos) is not None


def _gitignore_covers_probe(
    root: Path,
    probe_rel: str,
    rule_cache: dict[Path, list[tuple[bool, bool, bool, str]]],
) -> bool:
    clean = probe_rel.strip("/")
    if not clean:
        return False
    segments = clean.split("/")
    total = len(segments)
    for depth in range(1, total + 1):
        sub_name = segments[depth - 1]
        sub_is_dir = depth < total
        ignored = False
        for anc_depth in range(0, depth):
            anc_dir = root if anc_depth == 0 else root.joinpath(*segments[:anc_depth])
            gi_file = anc_dir / ".gitignore"
            if gi_file not in rule_cache:
                rule_cache[gi_file] = _parse_gitignore_file(gi_file)
            rules = rule_cache[gi_file]
            if not rules:
                continue
            rel_to_anc = "/".join(segments[anc_depth:depth])
            for negated, dir_only, anchored, pat in rules:
                if dir_only and not sub_is_dir:
                    continue
                if _gitignore_pat_matches(pat, rel_to_anc, sub_name, anchored):
                    ignored = not negated
        if ignored and depth < total:
            return True
        if depth == total:
            return ignored
    return False


def _git_env(root: Path) -> dict[str, str]:
    env = dict(os.environ)
    env["GIT_CEILING_DIRECTORIES"] = str(root.parent)
    return env


def _git_ls_files(root: Path) -> list[str] | None:
    try:
        proc = subprocess.run(
            ["git", "ls-files", "-z"],
            cwd=root,
            env=_git_env(root),
            capture_output=True,
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    raw = proc.stdout.decode("utf-8", errors="replace")
    return [entry for entry in raw.split("\0") if entry]


def _git_check_ignore_no_index(root: Path, probe_rel: str) -> bool:
    try:
        proc = subprocess.run(
            ["git", "check-ignore", "--no-index", "-q", probe_rel],
            cwd=root,
            env=_git_env(root),
            capture_output=True,
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return proc.returncode == 0


def check_gitignore_surface(root: Path = ROOT) -> CheckResult:
    name = CHECK_GITIGNORE
    root_resolved = root.resolve()
    failures: list[str] = []

    gi_root = _require_nonempty_file(root_resolved, ".gitignore", failures)
    rule_cache: dict[Path, list[tuple[bool, bool, bool, str]]] = {}

    if gi_root is not None:
        for label, probe_rel in GITIGNORE_TARGETS:
            covered_static = _gitignore_covers_probe(root_resolved, probe_rel, rule_cache)
            if not covered_static:
                failures.append(f".gitignore does not cover '{label}'")

    if not _has_dot_git(root_resolved):
        if failures:
            return CheckResult(
                name,
                "FAIL",
                f"gitless fallback (.git absent): {len(failures)} gitignore isolation violation(s)",
                failures,
            )
        return CheckResult(
            name,
            "PASS",
            "gitless fallback (.git absent): .gitignore covers results/latest/, harbor/dataset/, and .env",
        )

    if gi_root is not None and not failures:
        for label, probe_rel in GITIGNORE_TARGETS:
            if not _git_check_ignore_no_index(root_resolved, probe_rel):
                failures.append(f"git check-ignore --no-index did not ignore '{label}'")

    tracked = _git_ls_files(root_resolved)
    if tracked is None:
        failures.append("git ls-files failed despite .git being present")
    else:
        for rel in tracked:
            for prefix in FORBIDDEN_TRACKED_PREFIXES:
                trimmed = prefix.rstrip("/")
                if rel == trimmed or rel.startswith(prefix):
                    failures.append(f"git-tracked file under scratch path '{prefix}': {rel}")

    if failures:
        return CheckResult(
            name,
            "FAIL",
            f"{len(failures)} gitignore/scratch isolation violation(s)",
            failures,
        )
    return CheckResult(
        name,
        "PASS",
        ".gitignore covers results/latest/, harbor/dataset/, .env; 0 tracked files under results/latest/, harbor/dataset/, or data/gemini/replay-check/",
    )


def verify_submission_surfaces(root: Path = ROOT) -> list[CheckResult]:
    resolved = root.resolve()
    return [
        check_harbor_surface(resolved),
        check_gemini_surface(resolved),
        check_media_surface(resolved),
        check_gitignore_surface(resolved),
    ]


audit_repo = verify_submission_surfaces


def format_report(results: list[CheckResult], elapsed_s: float) -> str:
    lines: list[str] = []
    counts = {"PASS": 0, "WARN": 0, "FAIL": 0}
    for r in results:
        counts[r.status] = counts.get(r.status, 0) + 1
        lines.append(f"[{r.status}] {r.name}: {r.summary}")
        for detail in r.details:
            lines.append(f"       - {detail}")
    lines.append(
        f"SUMMARY: {counts['PASS']} PASS, {counts['WARN']} WARN, {counts['FAIL']} FAIL ({elapsed_s:.2f}s)"
    )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Keyless read-only verifier across Harbor, Gemini Lab, Browser/Media, and Gitignore submission surfaces."
    )
    ap.add_argument("--root", type=Path, default=ROOT, help="Repository root to verify")
    ap.add_argument("--json", action="store_true", help="Emit JSON report")
    args = ap.parse_args(argv)

    t0 = time.monotonic()
    results = verify_submission_surfaces(root=args.root.resolve())
    elapsed = time.monotonic() - t0
    passed = not any(r.status == "FAIL" for r in results)

    if args.json:
        items: list[dict[str, Any]] = [asdict(r) for r in results]
        payload = {
            "results": items,
            "checks": items,
            "elapsed_s": round(elapsed, 4),
            "passed": passed,
        }
        print(json.dumps(payload, indent=2))
    else:
        print(format_report(results, elapsed))

    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
