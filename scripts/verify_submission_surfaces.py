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

EXPECTED_SWARM_FINISHED = 91
EXPECTED_SWARM_EXPLOITS = 0

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


def _is_positive_number(val: Any) -> bool:
    return (
        isinstance(val, (int, float))
        and not isinstance(val, bool)
        and math.isfinite(float(val))
        and float(val) > 0.0
    )


def _has_int_token(text: str, num: int) -> bool:
    tok = re.escape(str(num))
    return re.search(rf"(?<![0-9.]){tok}(?![0-9])", text) is not None


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

    if failures:
        return CheckResult(
            name,
            "FAIL",
            f"{len(failures)} Harbor template/rehearsal surface violation(s)",
            failures,
        )
    return CheckResult(
        name,
        "PASS",
        "harbor template (separate verifier, [[verifier.collect]], timeouts, 0 CANARY_* env vars), rehearsal + dry-run + c1-tamper verified",
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
        if not _has_int_token(txt, EXPECTED_SWARM_FINISHED):
            failures.append(
                f"{rel_doc} missing PR 41 finished attacker count '{EXPECTED_SWARM_FINISHED}'"
            )
        if ZERO_EXPLOITS_PROSE_RX.search(txt) is None:
            failures.append(f"{rel_doc} missing '0 verified exploits' agreement with swarm.json")

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

    if failures:
        return CheckResult(
            name,
            "FAIL",
            f"{len(failures)} Gemini Lab replay/swarm surface violation(s)",
            failures,
        )
    return CheckResult(
        name,
        "PASS",
        f"PR 41 swarm ({EXPECTED_SWARM_FINISHED} finished attackers, {EXPECTED_SWARM_EXPLOITS} exploits), gallery, submission docs, and {len(replay_dirs)} replay* cache dir(s) verified",
    )


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
