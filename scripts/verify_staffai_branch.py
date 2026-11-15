from __future__ import annotations

import argparse
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
import hashlib
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
import time
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

EM_DASH = chr(0x2014)
EN_DASH = chr(0x2013)

PROTECTED_PATHS: tuple[str, ...] = (
    "canary/env.py",
    "canary/rules.py",
    "canary/solver/",
    "canary/reproduce.py",
    "harbor/",
)

EXPECTED_TIERS_VERSION = "v1.4"
EXPECTED_V14_HASH = "a8f99c2537c91d72"
EXPECTED_V13_HASH = "8df71cf570bb48bc"
EXPECTED_CACHE_COUNT = 256
EXPECTED_CACHE_LABEL = "REAL"
EXPECTED_CACHE_MODEL = "gemini-4-carbon"

SHA256_JSON_RE = re.compile(r"^[0-9a-f]{64}\.json$")
ALLOWED_ENV_TEMPLATES = frozenset({".env.example", ".env.sample", ".env.template"})
TEST_FIXTURE_MARKERS = ("fake", "fixture", "test-value", "abcdefghijklmn", "998877")

SECRET_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("google_api_key", re.compile(r"(?<![0-9A-Za-z+/_-])AIza[0-9A-Za-z_-]{20,}")),
    (
        "sk_api_key",
        re.compile(r"(?<![0-9A-Za-z+/_-])sk-(?:proj-|ant-|live-|test-|svcacct-)?[0-9A-Za-z_-]{16,}"),
    ),
    ("github_pat", re.compile(r"(?<![0-9A-Za-z+/_-])ghp_[0-9A-Za-z]{20,}")),
)
CACHE_SECRET_ASSIGN_RE = re.compile(
    r"(?:api[_-]?key|gemini_api_key|openai_api_key)\s*[:=]",
    re.IGNORECASE,
)
SUMMARY_LEDGER_ROW_RE = re.compile(r"^\|\s*`([a-z0-9_]+)`\s*\|\s*`([^`]+)`\s*\|")
MD_LINK_RE = re.compile(r"\[[^\]]+\]\(([^)]+)\)")


@dataclass
class CheckResult:
    name: str
    status: str
    summary: str
    details: list[str] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)


class _NoLiveLLMClient:
    def chat(self, *args: Any, **kwargs: Any) -> Any:
        raise AssertionError("live LLM call attempted during offline StaffAI verification")


@contextmanager
def _force_offline():
    prev_canary = os.environ.get("CANARY_OFFLINE")
    prev_provider = os.environ.get("CANARY_PROVIDER")
    os.environ["CANARY_OFFLINE"] = "1"
    os.environ.pop("CANARY_PROVIDER", None)
    try:
        yield
    finally:
        if prev_canary is None:
            os.environ.pop("CANARY_OFFLINE", None)
        else:
            os.environ["CANARY_OFFLINE"] = prev_canary
        if prev_provider is None:
            os.environ.pop("CANARY_PROVIDER", None)
        else:
            os.environ["CANARY_PROVIDER"] = prev_provider


def _redact(token: str) -> str:
    if len(token) <= 8:
        return token[:3] + "..."
    return token[:6] + "..."


def is_protected_path(rel_path: str) -> bool:
    norm = rel_path.strip().replace("\\", "/").lstrip("./")
    if not norm:
        return False
    for entry in PROTECTED_PATHS:
        if entry.endswith("/"):
            prefix = entry.rstrip("/")
            if norm == prefix or norm.startswith(entry):
                return True
        elif norm == entry:
            return True
    return False


def compute_tier_hash(tiers: dict[str, Any], known_v_mode: bool) -> str:
    payload = {
        "tiers": {k: v.to_dict() for k, v in tiers.items()},
        "known_v_mode": known_v_mode,
    }
    encoded = json.dumps(payload, sort_keys=True, default=list).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:16]


def _run_git(root: Path, args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=str(root),
        capture_output=True,
        text=True,
        timeout=10,
    )


def _git_ref_exists(root: Path, ref: str) -> bool:
    proc = _run_git(root, ["rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}"])
    return proc.returncode == 0


def check_protected_paths_and_frozen_tiers(
    root: Path = ROOT,
    base_ref: str = "origin/justSilas",
) -> CheckResult:
    name = "Protected-Path & Frozen-Tier Guard"
    failures: list[str] = []
    metrics: dict[str, Any] = {
        "base_ref": base_ref,
        "base_ref_exists": False,
        "branch_diff_count": 0,
        "protected_touched": [],
    }

    if not (root / ".git").exists():
        failures.append(f"{root} is not a git repository or worktree")
    else:
        ref_exists = _git_ref_exists(root, base_ref)
        metrics["base_ref_exists"] = ref_exists
        touched_candidates: set[str] = set()

        if ref_exists:
            diff_proc = _run_git(root, ["diff", "--name-only", f"{base_ref}...HEAD"])
            if diff_proc.returncode != 0:
                failures.append(f"git diff --name-only {base_ref}...HEAD failed: {diff_proc.stderr.strip()}")
            else:
                branch_files = [ln.strip() for ln in diff_proc.stdout.splitlines() if ln.strip()]
                metrics["branch_diff_count"] = len(branch_files)
                touched_candidates.update(branch_files)

        for extra_args in (["diff", "--name-only", "HEAD"], ["diff", "--cached", "--name-only"]):
            extra_proc = _run_git(root, extra_args)
            if extra_proc.returncode == 0:
                touched_candidates.update(ln.strip() for ln in extra_proc.stdout.splitlines() if ln.strip())

        protected_hits = sorted(p for p in touched_candidates if is_protected_path(p))
        metrics["protected_touched"] = protected_hits
        if protected_hits:
            failures.append(f"protected path(s) modified: {', '.join(protected_hits)}")

    from canary import rules
    from canary.text.gemini import get_provider

    v14_hash = compute_tier_hash(rules.TIERS, rules.KNOWN_V_MODE)
    v13_hash = compute_tier_hash(rules.TIERS_V13, rules.KNOWN_V_MODE)
    default_provider_name = get_provider(None).name

    metrics["tiers_version"] = rules.TIERS_VERSION
    metrics["known_v_mode"] = rules.KNOWN_V_MODE
    metrics["v14_tier_hash"] = v14_hash
    metrics["v13_tier_hash"] = v13_hash
    metrics["default_provider"] = default_provider_name

    if rules.TIERS_VERSION != EXPECTED_TIERS_VERSION:
        failures.append(f"rules.TIERS_VERSION expected {EXPECTED_TIERS_VERSION!r}, got {rules.TIERS_VERSION!r}")
    if rules.KNOWN_V_MODE is not True:
        failures.append(f"rules.KNOWN_V_MODE expected True, got {rules.KNOWN_V_MODE!r}")
    if v14_hash != EXPECTED_V14_HASH:
        failures.append(f"v1.4 tier hash expected {EXPECTED_V14_HASH}, got {v14_hash}")
    if v13_hash != EXPECTED_V13_HASH:
        failures.append(f"v1.3 tier hash expected {EXPECTED_V13_HASH}, got {v13_hash}")
    if default_provider_name != "template":
        failures.append(f"default provider expected 'template', got {default_provider_name!r}")

    if failures:
        return CheckResult(name, "FAIL", f"{len(failures)} protected-path or tier violation(s)", failures, metrics)

    ref_note = (
        f"{base_ref}...HEAD diff={metrics['branch_diff_count']} files (0 protected)"
        if metrics["base_ref_exists"]
        else f"{base_ref} ref absent (0 working-tree protected edits)"
    )
    return CheckResult(
        name,
        "PASS",
        f"{ref_note}; TIERS_VERSION={rules.TIERS_VERSION} ({v14_hash}); default_provider={default_provider_name}",
        [],
        metrics,
    )


def _scan_text_for_secrets(text: str, rel_label: str, *, is_cache: bool = False) -> list[str]:
    issues: list[str] = []
    is_test_file = rel_label.startswith("tests/")
    for kind, rx in SECRET_PATTERNS:
        for match in rx.finditer(text):
            tok = match.group(0)
            if is_test_file and any(marker in tok.lower() for marker in TEST_FIXTURE_MARKERS):
                continue
            issues.append(f"secret token ({kind}: {_redact(tok)}) in {rel_label}")

    if is_cache and CACHE_SECRET_ASSIGN_RE.search(text):
        issues.append(f"secret assignment key marker in {rel_label}")

    for env_key in ("GEMINI_API_KEY", "OPENAI_API_KEY"):
        env_val = os.environ.get(env_key, "").strip()
        if len(env_val) >= 12 and env_val in text:
            if is_test_file and any(marker in env_val.lower() for marker in TEST_FIXTURE_MARKERS):
                continue
            issues.append(f"live {env_key} value leaked in {rel_label}")
    return issues


def check_secret_and_cache_hygiene(
    root: Path = ROOT,
    expected_cache_count: int | None = EXPECTED_CACHE_COUNT,
) -> CheckResult:
    name = "Secret & Gemini-Cache Hygiene"
    failures: list[str] = []
    cache_dir = root / "data" / "gemini_cache"

    if not cache_dir.is_dir():
        return CheckResult(name, "FAIL", f"missing cache directory: {cache_dir}", [f"missing {cache_dir}"])

    all_entries = sorted(cache_dir.iterdir())
    json_files: list[Path] = []
    for entry in all_entries:
        if not entry.is_file() or entry.is_symlink():
            failures.append(f"unexpected non-regular entry in data/gemini_cache: {entry.name}")
            continue
        if not SHA256_JSON_RE.match(entry.name):
            failures.append(f"invalid cache filename (expected <sha256>.json): {entry.name}")
            continue
        json_files.append(entry)

    if expected_cache_count is not None and len(json_files) != expected_cache_count:
        failures.append(f"data/gemini_cache JSON count expected {expected_cache_count}, got {len(json_files)}")
    elif not json_files:
        failures.append("data/gemini_cache contains 0 JSON files")

    total_bodies = 0
    commits_seen: set[str] = set()

    for jf in json_files:
        rel = f"data/gemini_cache/{jf.name}"
        raw = jf.read_text(encoding="utf-8")
        failures.extend(_scan_text_for_secrets(raw, rel, is_cache=True))

        try:
            obj = json.loads(raw)
        except ValueError as exc:
            failures.append(f"{rel}: invalid JSON ({exc})")
            continue
        if not isinstance(obj, dict):
            failures.append(f"{rel}: root JSON value must be an object")
            continue

        prov = obj.get("provenance")
        if not isinstance(prov, dict):
            failures.append(f"{rel}: missing provenance object")
            continue

        label = prov.get("label")
        model = prov.get("model")
        commit_id = prov.get("commit")
        if label != EXPECTED_CACHE_LABEL:
            failures.append(f"{rel}: provenance.label expected {EXPECTED_CACHE_LABEL!r}, got {label!r}")
        if model != EXPECTED_CACHE_MODEL:
            failures.append(f"{rel}: provenance.model expected {EXPECTED_CACHE_MODEL!r}, got {model!r}")
        if not isinstance(commit_id, str) or not commit_id.strip():
            failures.append(f"{rel}: missing provenance.commit")
        else:
            commits_seen.add(commit_id.strip())

        body_txt = obj.get("text")
        if not isinstance(body_txt, str) or not body_txt.strip():
            failures.append(f"{rel}: missing non-empty text field")
            continue
        try:
            parsed_payload = json.loads(body_txt)
        except ValueError as exc:
            failures.append(f"{rel}: cached text is not valid JSON ({exc})")
            continue
        bodies = parsed_payload.get("bodies") if isinstance(parsed_payload, dict) else None
        if not isinstance(bodies, list) or not bodies or not all(isinstance(b, str) and b.strip() for b in bodies):
            failures.append(f"{rel}: cached text JSON must contain non-empty string list 'bodies'")
            continue
        for idx, b_str in enumerate(bodies):
            if re.search(r"\bmole\b", b_str, re.IGNORECASE):
                failures.append(f"{rel}: body[{idx}] contains forbidden word 'mole'")
        total_bodies += len(bodies)

    if (root / ".git").exists():
        ls_proc = subprocess.run(
            ["git", "ls-files", "-z"],
            cwd=str(root),
            capture_output=True,
            timeout=10,
        )
        if ls_proc.returncode == 0:
            tracked = [p for p in ls_proc.stdout.decode("utf-8", errors="replace").split("\0") if p]
            scan_candidates: set[str] = set()
            if len(tracked) <= 500 or not _git_ref_exists(root, "origin/justSilas"):
                scan_candidates.update(tracked)
            else:
                for diff_args in (
                    ["diff", "--name-only", "origin/justSilas...HEAD"],
                    ["diff", "--name-only", "HEAD"],
                    ["diff", "--cached", "--name-only"],
                ):
                    dp = _run_git(root, diff_args)
                    if dp.returncode == 0:
                        scan_candidates.update(ln.strip() for ln in dp.stdout.splitlines() if ln.strip())
                for rel_path in tracked:
                    if rel_path.startswith(("canary/social/", "results/v16_social/", "docs/reports/", "scripts/")):
                        scan_candidates.add(rel_path)

            for rel_path in tracked:
                p_obj = Path(rel_path)
                if p_obj.name == ".env" or (
                    p_obj.name.startswith(".env.") and p_obj.name not in ALLOWED_ENV_TEMPLATES
                ):
                    failures.append(f"tracked env file: {rel_path}")
                if p_obj.name == "SALT" or "SALT" in p_obj.parts:
                    failures.append(f"tracked SALT file: {rel_path}")
                if rel_path.endswith(".world.json"):
                    full_w = root / rel_path
                    if full_w.is_file() and '"mole"' in full_w.read_text(encoding="utf-8", errors="replace"):
                        failures.append(f"tracked world file leaks mole key: {rel_path}")

            for rel_path in sorted(scan_candidates):
                if rel_path.startswith("data/gemini_cache/"):
                    continue
                full_p = root / rel_path
                if not full_p.is_file():
                    continue
                raw_bytes = full_p.read_bytes()
                if b"\x00" in raw_bytes:
                    continue
                if any(marker in raw_bytes for marker in (b"AIza", b"sk-", b"ghp_")):
                    txt = raw_bytes.decode("utf-8", errors="replace")
                    failures.extend(_scan_text_for_secrets(txt, rel_path, is_cache=False))

    metrics = {
        "cache_file_count": len(json_files),
        "cache_total_bodies": total_bodies,
        "cache_provenance_label": EXPECTED_CACHE_LABEL,
        "cache_provenance_model": EXPECTED_CACHE_MODEL,
        "cache_commits": sorted(commits_seen),
    }

    if failures:
        return CheckResult(name, "FAIL", f"{len(failures)} cache or secret hygiene failure(s)", failures, metrics)
    return CheckResult(
        name,
        "PASS",
        f"{len(json_files)} REAL {EXPECTED_CACHE_MODEL} cache files ({total_bodies} social bodies); 0 secrets",
        [],
        metrics,
    )


def parse_summary_report_metrics(md_text: str) -> dict[str, str]:
    extracted: dict[str, str] = {}
    for line in md_text.splitlines():
        m = SUMMARY_LEDGER_ROW_RE.match(line.strip())
        if m:
            extracted[m.group(1)] = m.group(2)
    return extracted


def recompute_headline_metrics(root: Path = ROOT) -> tuple[dict[str, str], list[str]]:
    errors: list[str] = []
    paired_path = root / "results" / "v16_social" / "paired_v14_vs_v16_0_9.json"
    ref30_path = root / "results" / "v16_social" / "reference_seeds_30_49.json"
    cache_dir = root / "data" / "gemini_cache"

    if not paired_path.is_file():
        return {}, [f"missing {paired_path}"]
    if not ref30_path.is_file():
        return {}, [f"missing {ref30_path}"]
    if not cache_dir.is_dir():
        return {}, [f"missing {cache_dir}"]

    paired = json.loads(paired_path.read_text(encoding="utf-8"))
    ref30 = json.loads(ref30_path.read_text(encoding="utf-8"))

    expected_seeds_0_9 = list(range(0, 10))
    solver_arm = paired.get("arms", {}).get("solver", {})
    v14_arm = paired.get("arms", {}).get("v1.4", {})
    v16_arm = paired.get("arms", {}).get("v1.6", {})
    ref_checks = paired.get("reference_checks", {})
    ship_gate = paired.get("paired_comparison", {}).get("ship_gate", {})
    relayed = paired.get("azure_relayed_30_44", {})

    solver_rows = sorted(solver_arm.get("per_seed", []), key=lambda r: int(r["seed"]))
    v14_rows = sorted(v14_arm.get("per_seed", []), key=lambda r: int(r["seed"]))

    if [int(r["seed"]) for r in solver_rows] != expected_seeds_0_9:
        errors.append("paired solver per_seed does not cover exact seeds 0-9")
    if [int(r["seed"]) for r in v14_rows] != expected_seeds_0_9:
        errors.append("paired v1.4 per_seed does not cover exact seeds 0-9")

    if not solver_rows or not v14_rows:
        return {}, errors or ["empty solver or v1.4 per_seed rows"]

    solver_raw_mean = sum(float(r["score"]) for r in solver_rows) / len(solver_rows)
    solver_luck_mean = sum(float(r["luck_adjusted_score"]) for r in solver_rows) / len(solver_rows)
    v14_raw_mean = sum(float(r["score"]) for r in v14_rows) / len(v14_rows)
    v14_luck_mean = sum(float(r["luck_adjusted_score"]) for r in v14_rows) / len(v14_rows)
    v14_raw_pct = (v14_raw_mean / solver_raw_mean) * 100.0
    v14_luck_pct = (v14_luck_mean / solver_luck_mean) * 100.0
    v14_acc = sum(1 for r in v14_rows if r.get("correct")) / len(v14_rows)
    v14_mean_day = sum(float(r["final_day"]) for r in v14_rows) / len(v14_rows)

    if abs(solver_raw_mean - float(solver_arm.get("raw_score_mean", -999.0))) > 1e-6:
        errors.append(f"solver raw_score_mean mismatch: recomputed {solver_raw_mean} vs {solver_arm.get('raw_score_mean')}")
    if abs(solver_raw_mean - float(ref_checks.get("solver_v14_mean", -999.0))) > 1e-6:
        errors.append("reference_checks.solver_v14_mean mismatch against recomputed solver mean")
    if abs(float(ref_checks.get("solver_v14_mean", -999.0)) - float(ref_checks.get("solver_v16_mean", -888.0))) > 1e-9:
        errors.append("solver_v14_mean != solver_v16_mean in reference_checks")
    if abs(solver_raw_mean - 0.576) > 1e-6:
        errors.append(f"expected solver 0-9 mean 0.576, got {solver_raw_mean:.6f}")
    if ref_checks.get("solver_exact_match") is not True or ref_checks.get("solver_replay_verified") is not True:
        errors.append("reference_checks solver_exact_match / solver_replay_verified must be True")

    for dn_key in ("do_nothing_v14_mean", "do_nothing_v16_mean", "do_nothing_v14_max", "do_nothing_v16_max"):
        if float(ref_checks.get(dn_key, 1.0)) != 0.0:
            errors.append(f"{dn_key} expected 0.0, got {ref_checks.get(dn_key)}")
    if ref_checks.get("do_nothing_zero") is not True:
        errors.append("reference_checks.do_nothing_zero must be True")

    for se_key in ("stop_early_v14_mean", "stop_early_v16_mean", "stop_early_v14_max", "stop_early_v16_max"):
        if float(ref_checks.get(se_key, 1.0)) != 0.0:
            errors.append(f"{se_key} expected 0.0, got {ref_checks.get(se_key)}")
    if ref_checks.get("stop_early_zero") is not True:
        errors.append("reference_checks.stop_early_zero must be True")

    if abs(v14_raw_mean - float(v14_arm.get("raw_score_mean", -999.0))) > 1e-6:
        errors.append(f"v1.4 raw_score_mean mismatch: recomputed {v14_raw_mean} vs {v14_arm.get('raw_score_mean')}")
    if abs(v14_raw_pct - float(v14_arm.get("raw_pct_of_solver", -999.0))) > 1e-3:
        errors.append(f"v1.4 raw_pct_of_solver mismatch: recomputed {v14_raw_pct} vs {v14_arm.get('raw_pct_of_solver')}")
    if abs(v14_luck_pct - float(v14_arm.get("luck_adjusted_pct_of_solver", -999.0))) > 1e-3:
        errors.append(
            f"v1.4 luck_adjusted_pct_of_solver mismatch: recomputed {v14_luck_pct} vs {v14_arm.get('luck_adjusted_pct_of_solver')}"
        )
    if round(v14_raw_mean, 3) != 0.351:
        errors.append(f"expected v1.4 OpenCode hard 0-9 raw mean 0.351, got {v14_raw_mean:.6f}")
    if round(v14_raw_pct, 1) != 60.9:
        errors.append(f"expected v1.4 OpenCode hard 0-9 raw pct 60.9%, got {v14_raw_pct:.4f}%")
    if round(v14_luck_pct, 1) != 55.7:
        errors.append(f"expected v1.4 OpenCode hard 0-9 luck-adj pct 55.7%, got {v14_luck_pct:.4f}%")

    if paired.get("data_rule", {}).get("v14", {}).get("pass") is not True:
        errors.append("data_rule.v14.pass must be True")
    if paired.get("replay_verification", {}).get("v14", {}).get("verified") != 10:
        errors.append("replay_verification.v14.verified expected 10")

    committed_v14_ep = (
        root / "data" / "runs" / "committed" / "v1.4" / "opencode-gemini-4-carbon" / "hard" / "episodes.jsonl"
    )
    if committed_v14_ep.is_file():
        by_seed_v14 = {int(r["seed"]): r for r in v14_rows}
        seen_committed_v14: set[int] = set()
        for ln in committed_v14_ep.read_text(encoding="utf-8").splitlines():
            if not ln.strip():
                continue
            ep = json.loads(ln)
            sd = int(ep["seed"])
            if sd in by_seed_v14:
                seen_committed_v14.add(sd)
                if abs(float(ep["score"]) - float(by_seed_v14[sd]["score"])) > 1e-9:
                    errors.append(f"committed v1.4 OpenCode score mismatch on seed {sd}")
                if ep.get("accused") != by_seed_v14[sd]["accused"]:
                    errors.append(f"committed v1.4 OpenCode accused mismatch on seed {sd}")
        if seen_committed_v14 != set(expected_seeds_0_9):
            errors.append("committed v1.4 OpenCode episodes.jsonl missing seeds in 0-9")

    committed_ref_dir = root / "data" / "runs" / "committed" / "v1.4" / "reference"
    seed0_solver_ep: dict[str, Any] | None = None
    if committed_ref_dir.is_dir():
        by_seed_sol = {int(r["seed"]): r for r in solver_rows}
        seen_committed_sol: set[int] = set()
        for ep_f in sorted(committed_ref_dir.glob("solver-hard-*/episodes.jsonl")):
            for ln in ep_f.read_text(encoding="utf-8").splitlines():
                if not ln.strip():
                    continue
                ep = json.loads(ln)
                sd = int(ep["seed"])
                if sd in by_seed_sol and ep.get("agent") == "solver" and ep.get("tier") == "hard":
                    seen_committed_sol.add(sd)
                    if sd == 0:
                        seed0_solver_ep = ep
                    if abs(float(ep["score"]) - float(by_seed_sol[sd]["score"])) > 1e-9:
                        errors.append(f"committed solver score mismatch on seed {sd}")
                    if ep.get("accused") != by_seed_sol[sd]["accused"]:
                        errors.append(f"committed solver accused mismatch on seed {sd}")
        if seen_committed_sol != set(expected_seeds_0_9):
            errors.append("committed v1.4 reference solver missing seeds in 0-9")

    ref_rows = sorted(ref30.get("seeds", []), key=lambda r: int(r["seed"]))
    if [int(r["seed"]) for r in ref_rows] != list(range(30, 50)):
        errors.append("reference_seeds_30_49.json must contain exact seeds 30..49")
    if not ref_rows:
        return {}, errors or ["empty reference_seeds_30_49.json"]

    ref_30_49_mean = sum(float(r["solver_score"]) for r in ref_rows) / len(ref_rows)
    if abs(ref_30_49_mean - float(ref30.get("summary", {}).get("30-49", {}).get("solver_score_mean", -999.0))) > 1e-6:
        errors.append("reference_seeds_30_49 summary['30-49'].solver_score_mean mismatch")
    if abs(ref_30_49_mean - float(relayed.get("solver_30_49_raw_mean", -999.0))) > 1e-6:
        errors.append("paired azure_relayed_30_44.solver_30_49_raw_mean mismatch vs reference_seeds_30_49.json")
    if any(float(r["do_nothing_score"]) != 0.0 or float(r["stop_early_score"]) != 0.0 for r in ref_rows):
        errors.append("reference_seeds_30_49.json has non-zero do_nothing or stop_early baseline score")

    rows_30_32 = [r for r in ref_rows if int(r["seed"]) in (30, 31, 32)]
    sol_30_32_raw = sum(float(r["solver_score"]) for r in rows_30_32) / 3.0
    sol_30_32_luck = sum(float(r["solver_luck_adj"]) for r in rows_30_32) / 3.0
    if abs(sol_30_32_raw - float(relayed.get("solver_30_32_raw_mean", -999.0))) > 1e-5:
        errors.append("solver_30_32_raw_mean mismatch vs reference_seeds_30_49.json")
    if abs(sol_30_32_luck - float(relayed.get("solver_30_32_luck_adj_mean", -999.0))) > 1e-5:
        errors.append("solver_30_32_luck_adj_mean mismatch vs reference_seeds_30_49.json")

    relayed_per_seed = relayed.get("per_seed", [])
    by_variant: dict[str, dict[int, float]] = {}
    for item in relayed_per_seed:
        by_variant.setdefault(str(item["variant"]), {})[int(item["seed"])] = float(item["gemini_score"])

    v0_map = by_variant.get("v0_v14_control", {})
    v5_map = by_variant.get("v5_full9_cocktail", {})
    v1_map = by_variant.get("v1_anchoring_authority_confirmation", {})
    v3_map = by_variant.get("v3_grudge_falsemem_misforward", {})

    if sorted(v0_map) != [30, 31, 32] or sorted(v5_map) != [30, 31, 32]:
        errors.append("relayed v0_v14_control and v5_full9_cocktail must both cover seeds [30, 31, 32]")
        return {}, errors

    v0_mean = sum(v0_map[s] for s in (30, 31, 32)) / 3.0
    v5_mean = sum(v5_map[s] for s in (30, 31, 32)) / 3.0
    v5_vs_v0_ratio = v5_mean / v0_mean
    v1_mean = v1_map.get(30, float("nan"))
    v3_mean = (v3_map.get(30, float("nan")) + v3_map.get(31, float("nan"))) / 2.0

    relayed_variants_idx = {str(v["variant"]): v for v in relayed.get("variants", [])}
    if abs(v0_mean - float(relayed_variants_idx.get("v0_v14_control", {}).get("gemini_mean", -999.0))) > 1e-5:
        errors.append("relayed v0_v14_control gemini_mean mismatch against per_seed")
    if abs(v5_mean - float(relayed_variants_idx.get("v5_full9_cocktail", {}).get("gemini_mean", -999.0))) > 1e-5:
        errors.append("relayed v5_full9_cocktail gemini_mean mismatch against per_seed")
    if round(v5_mean, 3) != 0.617 or round(v0_mean, 3) != 0.523:
        errors.append(f"expected relayed 30-32 means 0.617 vs 0.523, got {v5_mean:.6f} vs {v0_mean:.6f}")
    if not (v5_mean > v0_mean):
        errors.append("expected v5_full9_cocktail mean > v0_v14_control mean on relayed seeds 30-32")

    if ship_gate.get("gate_met") is not False or ship_gate.get("ship_gate_pass") is not False:
        errors.append("paired_comparison.ship_gate.gate_met and ship_gate_pass must be False")
    if relayed.get("gate_met") is not False:
        errors.append("azure_relayed_30_44.gate_met must be False")

    cache_files = sorted(p for p in cache_dir.glob("*.json") if SHA256_JSON_RE.match(p.name))
    cache_bodies = 0
    for cf in cache_files:
        c_obj = json.loads(cf.read_text(encoding="utf-8"))
        c_txt = json.loads(c_obj["text"])
        cache_bodies += len(c_txt["bodies"])

    from canary.baselines import DoNothing, StopEarlyQuit, play
    from canary.env import Env
    import canary.social.horizon_escalation as horizon_escalation
    import canary.social.multiday_memory as multiday_memory
    import canary.social.sleeper_chains as sleeper_chains
    from canary.text.gemini import get_provider

    horizon_escalation.register_horizon_escalation_variant()
    multiday_memory.register_multiday_memory_variant()
    assert sleeper_chains is not None

    prov_v6 = get_provider("v16:v6_horizon_escalation")
    env_v6 = Env("hard", 0, text_provider=prov_v6)
    for day in range(1, 22):
        day_msgs = prov_v6.day_messages(env_v6._facts(day))
        social_day = [m for m in day_msgs if "-s" in m["id"]]
        if len(social_day) != 3:
            errors.append(f"v6_horizon_escalation Day {day} expected 3 social msgs, got {len(social_day)}")
        if day < 21:
            env_v6._publish_day(day + 1)
            env_v6.day = day + 1

    st_v6 = prov_v6.episode_state("hard", env_v6._facts(1).seed)
    if st_v6 is None:
        errors.append("v6_horizon_escalation episode_state missing after 21-day run")
        return {}, errors
    cont_errs = horizon_escalation.verify_horizon_continuity(st_v6.events_by_day, decoy_id=env_v6._world.decoy)
    if cont_errs:
        errors.extend(f"v6_horizon_escalation continuity error: {e}" for e in cont_errs)
    v6_metrics = horizon_escalation.summarize_horizon_metrics(st_v6.events_by_day)
    if int(v6_metrics["total_messages"]) != 63:
        errors.append(f"v6_horizon_escalation total_messages expected 63, got {v6_metrics['total_messages']}")
    if int(v6_metrics["phase_messages"]["late_stopping_window"]) != 9:
        errors.append("v6_horizon_escalation late_stopping_window expected 9 messages")

    v5_seed0_hits = 0
    if len(cache_files) == EXPECTED_CACHE_COUNT:
        prov_gem = get_provider(
            "v16-gemini:v5_full9_cocktail",
            cache_dir=str(cache_dir),
            client=_NoLiveLLMClient(),
        )
        env_gem = Env("hard", 0, text_provider=prov_gem)
        for day in range(1, 22):
            msgs_gem = prov_gem.day_messages(env_gem._facts(day))
            if any("-s" in m["id"] for m in msgs_gem):
                v5_seed0_hits += 1
            if day < 21:
                env_gem._publish_day(day + 1)
                env_gem.day = day + 1
        if v5_seed0_hits != 18 or prov_gem.rejects != 0:
            errors.append(f"v5_full9_cocktail seed 0 offline cache replay expected 18 hits / 0 rejects, got {v5_seed0_hits} / {prov_gem.rejects}")

    for spec in ("template", "social-v2-template", "v16:v6_horizon_escalation"):
        dn_sc = play(Env("hard", 0, text_provider=get_provider(spec)), DoNothing(seed=0))
        se_sc = play(Env("hard", 0, text_provider=get_provider(spec)), StopEarlyQuit(seed=0))
        if dn_sc != 0.0 or se_sc != 0.0:
            errors.append(f"live seed 0 baseline non-zero under {spec}: do_nothing={dn_sc}, stop_early={se_sc}")
        if seed0_solver_ep is not None:
            env_rep = Env("hard", 0, text_provider=get_provider(spec))
            for st in seed0_solver_ep.get("steps") or []:
                if env_rep.done:
                    break
                env_rep.call(st["tool"], st.get("args") or {})
            rep_res = env_rep.result("solver")
            if abs(float(rep_res.score) - float(seed0_solver_ep["score"])) > 1e-9 or rep_res.accused != seed0_solver_ep.get("accused"):
                errors.append(f"live seed 0 solver step replay drift under {spec}")

    expected_ledger = {
        "tiers_version": EXPECTED_TIERS_VERSION,
        "frozen_v14_tier_hash": EXPECTED_V14_HASH,
        "default_provider": "template",
        "solver_v14_hard_0_9": f"{solver_raw_mean:.3f}",
        "solver_v16_hard_0_9": f"{float(ref_checks['solver_v16_mean']):.3f}",
        "do_nothing_hard_0_9": f"{float(ref_checks['do_nothing_v16_mean']):.3f}",
        "stop_early_hard_0_9": f"{float(ref_checks['stop_early_v16_mean']):.3f}",
        "v14_opencode_hard_0_9_raw_mean": f"{v14_raw_mean:.3f}",
        "v14_opencode_hard_0_9_raw_pct": f"{v14_raw_pct:.1f}%",
        "v14_opencode_hard_0_9_luck_adj_mean": f"{v14_luck_mean:.3f}",
        "v14_opencode_hard_0_9_luck_adj_pct": f"{v14_luck_pct:.1f}%",
        "v14_opencode_hard_0_9_accuracy": f"{v14_acc:.2f}",
        "v14_opencode_hard_0_9_mean_day": f"{v14_mean_day:.1f}",
        "v16_opencode_hard_0_9_n_valid": f"{int(v16_arm.get('n_valid', 0))}/10",
        "relayed_30_32_v5_full9_mean": f"{v5_mean:.3f}",
        "relayed_30_32_v0_control_mean": f"{v0_mean:.3f}",
        "relayed_30_32_paired_ratio": f"{v5_vs_v0_ratio:.3f}",
        "relayed_30_v1_mean": f"{v1_mean:.3f}",
        "relayed_30_31_v3_mean": f"{v3_mean:.3f}",
        "reference_30_49_solver_raw_mean": f"{ref_30_49_mean:.3f}",
        "reference_30_32_solver_luck_adj_mean": f"{sol_30_32_luck:.3f}",
        "gate_b_status": "NOT MET",
        "shipped_default_version": "v1.4",
        "gemini_cache_real_files": str(len(cache_files)),
        "gemini_cache_model": EXPECTED_CACHE_MODEL,
        "gemini_cache_social_bodies": str(cache_bodies),
        "v6_horizon_active_days": "1..21",
        "v6_horizon_total_messages": str(int(v6_metrics["total_messages"])),
        "v6_horizon_late_window_messages": str(int(v6_metrics["phase_messages"]["late_stopping_window"])),
        "v6_horizon_post_day1_callbacks": f"{int(v6_metrics['post_day1_callbacks'])}/{int(v6_metrics['post_day1_messages'])}",
    }
    return expected_ledger, errors


def check_cross_report_consistency(root: Path = ROOT) -> CheckResult:
    name = "Cross-Report Numeric & Dossier Consistency"
    summary_path = root / "docs" / "reports" / "staffai_social_summary.md"
    if not summary_path.is_file():
        return CheckResult(name, "FAIL", f"missing summary report: {summary_path}", [f"missing {summary_path}"])

    expected_ledger, recompute_errors = recompute_headline_metrics(root)
    failures: list[str] = list(recompute_errors)
    if not expected_ledger:
        return CheckResult(name, "FAIL", f"{len(failures)} metric recomputation failure(s)", failures)

    md_text = summary_path.read_text(encoding="utf-8")
    if EM_DASH in md_text or EN_DASH in md_text:
        failures.append("docs/reports/staffai_social_summary.md contains forbidden em/en dash")
    failures.extend(_scan_text_for_secrets(md_text, "docs/reports/staffai_social_summary.md", is_cache=False))

    parsed_ledger = parse_summary_report_metrics(md_text)
    for key, exp_val in expected_ledger.items():
        got_val = parsed_ledger.get(key)
        if got_val is None:
            failures.append(f"staffai_social_summary.md missing ledger row for {key!r} (expected {exp_val!r})")
        elif got_val != exp_val:
            failures.append(f"staffai_social_summary.md mismatch for {key!r}: cited {got_val!r}, recomputed {exp_val!r}")

    extra_keys = sorted(set(parsed_ledger) - set(expected_ledger))
    if extra_keys:
        failures.append(f"staffai_social_summary.md has unverified ledger key(s): {', '.join(extra_keys)}")

    required_prose_tokens = (
        "solver_v14 == solver_v16 == 0.576",
        "0.351",
        "60.9%",
        "55.7%",
        "0.617",
        "0.523",
        "Gate B is NOT met",
        "v1.4",
        "256",
        "gemini-4-carbon",
        "v6_horizon_escalation",
        "63",
        "Days 1..21",
        "a8f99c2537c91d72",
    )
    for token in required_prose_tokens:
        if token not in md_text:
            failures.append(f"staffai_social_summary.md missing required verified statement/token: {token!r}")

    if re.search(r"\bgate\s+b\s+is\s+met\b", md_text, re.IGNORECASE):
        failures.append("staffai_social_summary.md falsely claims Gate B is met")

    for match in MD_LINK_RE.finditer(md_text):
        target = match.group(1).strip().split()[0]
        if target.startswith(("http://", "https://", "mailto:")):
            continue
        clean_target = target.split(chr(35), 1)[0]
        if not clean_target:
            continue
        resolved = (summary_path.parent / clean_target).resolve()
        if not resolved.exists() and not (root / clean_target).exists():
            failures.append(f"broken relative link in staffai_social_summary.md: {target}")

    for sibling_rel, sibling_tokens in (
        ("docs/reports/v16_social_gate.md", ("0.576", "0.351", "60.9%", "55.7%", "0.617", "0.523", "GATE NOT MET")),
        ("docs/reports/v16_horizon_escalation.md", ("63.0", "0.576", "256", "v6_horizon_escalation")),
    ):
        sib_path = root / sibling_rel
        if sib_path.is_file():
            sib_txt = sib_path.read_text(encoding="utf-8")
            if EM_DASH in sib_txt or EN_DASH in sib_txt:
                failures.append(f"{sibling_rel} contains forbidden em/en dash")
            for tok in sibling_tokens:
                if tok not in sib_txt:
                    failures.append(f"{sibling_rel} missing expected cross-checked token {tok!r}")

    if failures:
        return CheckResult(
            name,
            "FAIL",
            f"{len(failures)} cross-report consistency failure(s)",
            failures,
            expected_ledger,
        )
    return CheckResult(
        name,
        "PASS",
        f"verified {len(expected_ledger)}/{len(expected_ledger)} headline metrics across paired_v14_vs_v16_0_9.json, reference_seeds_30_49.json, data/gemini_cache/, and staffai_social_summary.md",
        [],
        expected_ledger,
    )


def verify_branch(
    root: Path = ROOT,
    *,
    base_ref: str = "origin/justSilas",
    expected_cache_count: int | None = EXPECTED_CACHE_COUNT,
) -> list[CheckResult]:
    with _force_offline():
        return [
            check_protected_paths_and_frozen_tiers(root, base_ref=base_ref),
            check_secret_and_cache_hygiene(root, expected_cache_count=expected_cache_count),
            check_cross_report_consistency(root),
        ]


def format_report(results: list[CheckResult], elapsed_s: float) -> str:
    lines: list[str] = []
    pass_count = sum(1 for r in results if r.status == "PASS")
    fail_count = sum(1 for r in results if r.status == "FAIL")
    for r in results:
        lines.append(f"[{r.status}] {r.name}: {r.summary}")
        for detail in r.details:
            lines.append(f"       - {detail}")
    lines.append(f"SUMMARY: {pass_count} PASS, {fail_count} FAIL ({elapsed_s:.3f}s)")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Offline StaffAI branch hygiene and cross-report verifier.")
    ap.add_argument("--root", type=Path, default=ROOT, help="Repository root to verify")
    ap.add_argument("--base-ref", type=str, default="origin/justSilas", help="Protected-path git base ref")
    ap.add_argument("--json", action="store_true", help="Emit JSON output")
    args = ap.parse_args(argv)

    t0 = time.monotonic()
    results = verify_branch(args.root.resolve(), base_ref=args.base_ref)
    elapsed = time.monotonic() - t0
    passed = not any(r.status == "FAIL" for r in results)

    if args.json:
        print(
            json.dumps(
                {
                    "passed": passed,
                    "elapsed_s": round(elapsed, 4),
                    "results": [asdict(r) for r in results],
                },
                indent=2,
                sort_keys=True,
            )
        )
    else:
        print(format_report(results, elapsed))

    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
