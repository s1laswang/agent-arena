from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

from canary.llm.pricing import cost as price_cost

REQUIRED_ROLES = (
    "world_text",
    "adaptive_mole",
    "investigators",
    "failure_analyst",
    "exploit_hunter",
    "multimodal_evidence",
)
TARGET_MODEL = "gemini-4-carbon"
SKIP_DIRS = frozenset({"reference", "superseded", "_invalid"})
COMMIT_RE = re.compile(r"^[0-9a-fA-F]{7,40}$")
GOOGLE_KEY_RE = re.compile(r"AIza[0-9A-Za-z_\-]{8,}")
SK_KEY_RE = re.compile(r"(?<![A-Za-z0-9_])sk-[A-Za-z0-9_\-]{12,}")
OAUTH_RE = re.compile(r"(?<![A-Za-z0-9_])ya29\.[0-9A-Za-z_\-]{12,}")
ENV_KEY_RE = re.compile(
    r"\b(?:GEMINI_API_KEY|GOOGLE_API_KEY|GOOGLE_GENERATIVE_AI_API_KEY|"
    r"OPENAI_API_KEY|ANTHROPIC_API_KEY|XAI_API_KEY)\b"
    r"[\"']?[ \t]*[:=][ \t]*(\"[^\"]*\"|'[^']*'|[^\s\"',}\]]*)"
)
SAFE_PLACEHOLDERS = frozenset({
    "",
    "null",
    "none",
    "false",
    "true",
    "unset",
    "redacted",
    "[redacted]",
    "<redacted>",
    "empty",
    "missing",
})


def _is_num(val: Any) -> bool:
    return isinstance(val, (int, float)) and not isinstance(val, bool)


def _truthy_flag(val: Any) -> bool:
    if val is True:
        return True
    if isinstance(val, str) and val.strip().lower() in {"true", "1", "yes"}:
        return True
    return False


def _has_env_secret(text: str) -> bool:
    for match in ENV_KEY_RE.finditer(text):
        raw = match.group(1).strip()
        quoted = len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in "\"'"
        inner = raw[1:-1].strip() if quoted else raw
        if inner.lower() in SAFE_PLACEHOLDERS:
            continue
        if set(inner) <= {"*"} or inner.startswith("$"):
            continue
        if not quoted and "=" in inner:
            continue
        if len(inner) >= 4:
            return True
    return False


def scan_file_secrets(file_path: Path, root: Path) -> list[dict[str, str]]:
    try:
        text = file_path.read_bytes().decode("latin-1")
    except OSError:
        return [{"file": _rel_posix(file_path, root), "kind": "unreadable_file"}]
    rel = _rel_posix(file_path, root)
    findings: list[dict[str, str]] = []
    if GOOGLE_KEY_RE.search(text):
        findings.append({"file": rel, "kind": "google_api_key"})
    if SK_KEY_RE.search(text):
        findings.append({"file": rel, "kind": "sk_api_key"})
    if OAUTH_RE.search(text):
        findings.append({"file": rel, "kind": "oauth_token"})
    if _has_env_secret(text):
        findings.append({"file": rel, "kind": "env_api_key"})
    return findings


def _rel_posix(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _is_skipped(parts: tuple[str, ...]) -> bool:
    return any(part in SKIP_DIRS for part in parts)


def _infer_role(run_dir: Path, v14_root: Path, meta: dict[str, Any]) -> tuple[str | None, bool]:
    raw = meta.get("role")
    if isinstance(raw, str) and raw.strip():
        cleaned = raw.strip()
        norm = cleaned.lower().replace("-", "_").replace(" ", "_")
        return (norm if norm in REQUIRED_ROLES else cleaned), False
    try:
        rel_parts = run_dir.resolve().relative_to(v14_root.resolve()).parts
    except ValueError:
        return None, False
    raw_model = meta.get("model_id") if meta.get("model_id") is not None else meta.get("model")
    if any(TARGET_MODEL in part for part in rel_parts) or (
        isinstance(raw_model, str) and raw_model.strip() == TARGET_MODEL
    ):
        return "investigators", True
    return None, False


def _extract_usage(meta: dict[str, Any], model_id: str) -> tuple[int, int, int, int, float, str | None]:
    usage = meta.get("usage")
    if not isinstance(usage, dict):
        return 0, 0, 0, 0, 0.0, "missing_usage"
    raw_in = usage.get("in") if "in" in usage else usage.get("input_tokens", usage.get("prompt_tokens"))
    raw_out = (
        usage.get("out")
        if "out" in usage
        else usage.get("output_tokens", usage.get("out_tokens", usage.get("candidates_tokens", usage.get("completion_tokens"))))
    )
    valid = _is_num(raw_in) and _is_num(raw_out) and raw_in > 0 and raw_out > 0
    tin = int(raw_in) if _is_num(raw_in) and raw_in > 0 else 0
    tout = int(raw_out) if _is_num(raw_out) and raw_out > 0 else 0
    raw_think = usage.get("thinking", usage.get("thinking_tokens", 0))
    thinking = int(raw_think) if _is_num(raw_think) and raw_think > 0 else 0
    raw_cached = usage.get("cached", usage.get("cached_in", 0))
    cached = int(raw_cached) if _is_num(raw_cached) and raw_cached > 0 else 0
    raw_cost = usage.get("cost_usd_est") if _is_num(usage.get("cost_usd_est")) else usage.get("cost_usd")
    if not _is_num(raw_cost) and _is_num(meta.get("cost_usd")):
        raw_cost = meta.get("cost_usd")
    usd = float(raw_cost) if _is_num(raw_cost) and raw_cost >= 0 else 0.0
    if usd == 0.0 and valid and model_id:
        priced = price_cost(model_id, tin, tout + thinking, cached)
        usd = float(priced.get("cost_usd_est", priced.get("cost_usd", 0.0)) or 0.0)
    err = None if valid else "zero_or_invalid_usage"
    return tin, tout, thinking, cached, round(usd, 6), err


def _extract_count(run_dir: Path, meta: dict[str, Any]) -> int:
    for key in (
        "episode_count",
        "sample_count",
        "n_episodes",
        "n_samples",
        "n_episodes_packed",
        "n_charts_analyzed",
        "n_images_read_by_model",
        "n_worlds",
        "n_events_generated",
        "n_briefings",
        "count",
        "n",
    ):
        val = meta.get(key)
        if isinstance(val, int) and not isinstance(val, bool) and val >= 0:
            return val
    for name in ("episodes.jsonl", "attempts.jsonl", "samples.jsonl", "results.jsonl"):
        fp = run_dir / name
        if fp.is_file():
            try:
                lines = [ln for ln in fp.read_text(errors="replace").splitlines() if ln.strip()]
                if lines:
                    return len(lines)
            except OSError:
                pass
    for key in ("valid_seeds", "episodes", "samples", "seeds", "runs", "attempts", "items"):
        val = meta.get(key)
        if isinstance(val, list):
            return len(val)
        if isinstance(val, int) and not isinstance(val, bool) and val >= 0:
            return val
    summary = meta.get("summary")
    if isinstance(summary, dict):
        if isinstance(summary.get("n"), int) and not isinstance(summary.get("n"), bool):
            return summary["n"]
        sub = [
            v.get("n")
            for v in summary.values()
            if isinstance(v, dict) and isinstance(v.get("n"), int) and not isinstance(v.get("n"), bool)
        ]
        if sub:
            return sum(sub)
    return 0


def _inspect_run(meta_path: Path, root: Path, v14_root: Path) -> dict[str, Any]:
    run_dir = meta_path.parent
    rel_dir = _rel_posix(run_dir, root)
    errors: list[str] = []
    leaks: list[dict[str, str]] = []
    for fp in sorted(p for p in run_dir.rglob("*") if p.is_file()):
        rel_sub = fp.relative_to(run_dir).parts
        if _is_skipped(rel_sub):
            continue
        leaks.extend(scan_file_secrets(fp, root))

    meta: dict[str, Any] | None = None
    try:
        parsed = json.loads(meta_path.read_text(encoding="utf-8"))
        if isinstance(parsed, dict):
            meta = parsed
        else:
            errors.append("invalid_meta_json")
    except (OSError, UnicodeDecodeError, ValueError):
        errors.append("invalid_meta_json")

    if meta is None:
        if leaks:
            errors.append("secret_leak")
        return {
            "run_dir": rel_dir,
            "role": None,
            "role_inferred": False,
            "model_id": None,
            "commit": None,
            "count": 0,
            "tokens_in": 0,
            "tokens_out": 0,
            "thinking_tokens": 0,
            "cached_tokens": 0,
            "cost_usd": 0.0,
            "verified": False,
            "errors": errors,
            "secret_leaks": leaks,
        }

    role, role_inferred = _infer_role(run_dir, v14_root, meta)
    if not role:
        errors.append("missing_role")
    elif role not in REQUIRED_ROLES:
        errors.append(f"invalid_role:{role}")

    raw_model = meta.get("model_id") if meta.get("model_id") is not None else meta.get("model")
    model_id = raw_model.strip() if isinstance(raw_model, str) else ""
    if not model_id:
        errors.append("missing_model_id")
    elif model_id != TARGET_MODEL:
        errors.append(f"wrong_model:{model_id}")

    raw_commit = meta.get("commit") if meta.get("commit") is not None else meta.get("git_sha")
    commit = raw_commit.strip() if isinstance(raw_commit, str) else ""
    if not commit:
        errors.append("missing_commit")
    elif not COMMIT_RE.fullmatch(commit):
        errors.append(f"invalid_commit:{commit[:40]}")

    tin, tout, thinking, cached, usd, usage_err = _extract_usage(meta, model_id)
    if usage_err:
        errors.append(usage_err)

    if _truthy_flag(meta.get("fake_env")):
        errors.append("fake_env")
    if _truthy_flag(meta.get("smoke")):
        errors.append("smoke_run")

    provider = str(meta.get("provider") or "").strip().lower()
    agent = str(meta.get("agent") or "").strip().lower()
    if (
        _truthy_flag(meta.get("stub"))
        or _truthy_flag(meta.get("synthetic"))
        or provider == "stub"
        or agent == "stub"
        or agent.startswith("stub:")
    ):
        errors.append("stub_run")

    if leaks:
        errors.append("secret_leak")

    count = _extract_count(run_dir, meta)
    return {
        "run_dir": rel_dir,
        "role": role,
        "role_inferred": role_inferred,
        "model_id": model_id or None,
        "commit": commit or None,
        "count": count,
        "tokens_in": tin,
        "tokens_out": tout,
        "thinking_tokens": thinking,
        "cached_tokens": cached,
        "cost_usd": usd,
        "verified": len(errors) == 0,
        "errors": errors,
        "secret_leaks": leaks,
    }


def _collect_meta_files(scan_root: Path) -> list[Path]:
    if not scan_root.is_dir():
        return []
    found: list[Path] = []
    for meta_path in sorted(scan_root.rglob("meta.json")):
        if not meta_path.is_file():
            continue
        rel_parts = meta_path.relative_to(scan_root).parts
        if _is_skipped(rel_parts):
            continue
        found.append(meta_path)
    return found


def audit_provenance(root: str | Path = ".", write_prefix: str | Path | None = None) -> dict[str, Any]:
    root_path = Path(root).resolve()
    roles_root = root_path / "results" / "gemini_roles"
    v14_root = root_path / "data" / "runs" / "committed" / "v1.4"

    meta_files: list[Path] = []
    seen_meta: set[Path] = set()
    for candidate in _collect_meta_files(roles_root) + _collect_meta_files(v14_root):
        resolved = candidate.resolve()
        if resolved not in seen_meta:
            seen_meta.add(resolved)
            meta_files.append(candidate)

    runs = [_inspect_run(mp, root_path, v14_root) for mp in meta_files]

    leak_map: dict[tuple[str, str], dict[str, str]] = {}
    for run in runs:
        for leak in run["secret_leaks"]:
            leak_map[(leak["file"], leak["kind"])] = leak

    if roles_root.is_dir():
        for fp in sorted(p for p in roles_root.rglob("*") if p.is_file()):
            rel_parts = fp.relative_to(roles_root).parts
            if _is_skipped(rel_parts):
                continue
            for leak in scan_file_secrets(fp, root_path):
                leak_map[(leak["file"], leak["kind"])] = leak

    secret_leaks = [leak_map[k] for k in sorted(leak_map)]

    roles_summary: dict[str, dict[str, Any]] = {}
    verified_roles: list[str] = []
    missing_roles: list[str] = []

    for role in REQUIRED_ROLES:
        role_runs = [r for r in runs if r["role"] == role]
        good = [r for r in role_runs if r["verified"]]
        if good and not secret_leaks:
            verified_roles.append(role)
            commits = list(dict.fromkeys(r["commit"] for r in good if r["commit"]))
            roles_summary[role] = {
                "role": role,
                "verified": True,
                "run_dir": good[0]["run_dir"],
                "run_dirs": [r["run_dir"] for r in good],
                "model_id": TARGET_MODEL,
                "commit": commits[0] if len(commits) == 1 else ",".join(commits),
                "commits": commits,
                "count": sum(r["count"] for r in good),
                "tokens_in": sum(r["tokens_in"] for r in good),
                "tokens_out": sum(r["tokens_out"] for r in good),
                "usage": {
                    "in": sum(r["tokens_in"] for r in good),
                    "out": sum(r["tokens_out"] for r in good),
                },
                "cost_usd": round(sum(r["cost_usd"] for r in good), 6),
                "errors": [],
            }
        else:
            missing_roles.append(role)
            cand = good[0] if good else (role_runs[0] if role_runs else None)
            cand_errors: list[str] = []
            if secret_leaks and good:
                cand_errors.append("secret_leak")
            elif role_runs:
                for r in role_runs:
                    for err in r["errors"]:
                        if err not in cand_errors:
                            cand_errors.append(err)
            else:
                cand_errors.append("no_runs_found")
            roles_summary[role] = {
                "role": role,
                "verified": False,
                "run_dir": cand["run_dir"] if cand else None,
                "run_dirs": [r["run_dir"] for r in role_runs],
                "model_id": cand["model_id"] if cand else None,
                "commit": cand["commit"] if cand else None,
                "commits": list(dict.fromkeys(r["commit"] for r in role_runs if r["commit"])),
                "count": cand["count"] if cand else 0,
                "tokens_in": cand["tokens_in"] if cand else 0,
                "tokens_out": cand["tokens_out"] if cand else 0,
                "usage": {
                    "in": cand["tokens_in"] if cand else 0,
                    "out": cand["tokens_out"] if cand else 0,
                },
                "cost_usd": cand["cost_usd"] if cand else 0.0,
                "errors": cand_errors,
            }

    good_all = [r for r in runs if r["verified"] and r["role"] in REQUIRED_ROLES]
    overall_verified = len(missing_roles) == 0 and len(secret_leaks) == 0

    report: dict[str, Any] = {
        "verified": overall_verified,
        "ok": overall_verified,
        "target_model": TARGET_MODEL,
        "required_roles": list(REQUIRED_ROLES),
        "verified_roles": verified_roles,
        "missing_roles": missing_roles,
        "roles": roles_summary,
        "runs": runs,
        "secret_leaks": secret_leaks,
        "totals": {
            "scanned_runs": len(runs),
            "verified_runs": len(good_all),
            "count": sum(r["count"] for r in good_all),
            "tokens_in": sum(r["tokens_in"] for r in good_all),
            "tokens_out": sum(r["tokens_out"] for r in good_all),
            "cost_usd": round(sum(r["cost_usd"] for r in good_all), 6),
        },
    }
    if write_prefix is not None:
        prefix = Path(write_prefix)
        if not prefix.is_absolute():
            prefix = root_path / prefix
        write_manifest(report, prefix)
    return report


def render_manifest_json(report: dict[str, Any]) -> str:
    return json.dumps(report, indent=2, sort_keys=False) + "\n"


def render_manifest_md(report: dict[str, Any]) -> str:
    status = "VERIFIED" if report.get("verified") else "INCOMPLETE"
    totals = report.get("totals") or {}
    verified_count = len(report.get("verified_roles") or [])
    required_count = len(report.get("required_roles") or REQUIRED_ROLES)
    leaks = report.get("secret_leaks") or []
    lines = [
        "# Gemini 6-Role Provenance Manifest",
        "",
        f"- Status: **{status}**",
        f"- Target model: `{report.get('target_model', TARGET_MODEL)}`",
        f"- Verified roles: {verified_count}/{required_count}",
        f"- Secret leaks detected: {len(leaks)}",
        f"- Verified run folders: {totals.get('verified_runs', 0)} (scanned: {totals.get('scanned_runs', 0)})",
        f"- Total episodes/samples: {totals.get('count', 0)}",
        f"- Total tokens (in / out): {totals.get('tokens_in', 0):,} / {totals.get('tokens_out', 0):,}",
        f"- Total cost (USD): ${totals.get('cost_usd', 0.0):.4f}",
        "",
        "## Role Claims",
        "",
        "| Role | Verified | Run Folder | Model ID | Commit | Count | Tokens In | Tokens Out | Cost (USD) | Details |",
        "| --- | --- | --- | --- | --- | ---: | ---: | ---: | ---: | --- |",
    ]
    roles_map = report.get("roles") or {}
    for role in report.get("required_roles") or REQUIRED_ROLES:
        entry = roles_map.get(role) or {}
        ok = "yes" if entry.get("verified") else "no"
        run_dirs = entry.get("run_dirs") or []
        if not run_dirs:
            folder_cell = "none"
        elif len(run_dirs) == 1 or not entry.get("verified"):
            folder_cell = f"`{entry.get('run_dir')}`"
        else:
            extra = len(run_dirs) - 1
            folder_cell = f"`{entry.get('run_dir')}` (+{extra} more)"
        model_cell = f"`{entry['model_id']}`" if entry.get("model_id") else "none"
        commit_cell = f"`{entry['commit']}`" if entry.get("commit") else "none"
        errs = entry.get("errors") or []
        detail = "ok" if entry.get("verified") else ", ".join(errs)
        lines.append(
            f"| `{role}` | {ok} | {folder_cell} | {model_cell} | {commit_cell} "
            f"| {entry.get('count', 0)} | {entry.get('tokens_in', 0)} | {entry.get('tokens_out', 0)} "
            f"| ${entry.get('cost_usd', 0.0):.4f} | {detail} |"
        )

    runs = report.get("runs") or []
    if runs:
        lines.extend([
            "",
            "## Scanned Run Folders",
            "",
            "| Run Folder | Role | Verified | Model ID | Commit | Count | Tokens In | Tokens Out | Cost (USD) | Status |",
            "| --- | --- | --- | --- | --- | ---: | ---: | ---: | ---: | --- |",
        ])
        for run in runs:
            role_cell = f"`{run['role']}`" if run.get("role") else "none"
            ok = "yes" if run.get("verified") else "no"
            model_cell = f"`{run['model_id']}`" if run.get("model_id") else "none"
            commit_cell = f"`{run['commit']}`" if run.get("commit") else "none"
            status_cell = "ok" if run.get("verified") else ", ".join(run.get("errors") or [])
            lines.append(
                f"| `{run['run_dir']}` | {role_cell} | {ok} | {model_cell} | {commit_cell} "
                f"| {run.get('count', 0)} | {run.get('tokens_in', 0)} | {run.get('tokens_out', 0)} "
                f"| ${run.get('cost_usd', 0.0):.4f} | {status_cell} |"
            )

    if leaks:
        lines.extend(["", "## Secret Scan Findings", ""])
        for leak in leaks:
            lines.append(f"- `{leak['file']}`: `{leak['kind']}`")

    lines.append("")
    return "\n".join(lines)


def write_manifest(report: dict[str, Any], out_prefix: str | Path) -> tuple[Path, Path]:
    prefix = Path(out_prefix)
    if prefix.suffix in {".json", ".md"}:
        stem = prefix.with_suffix("")
    elif prefix.exists() and prefix.is_dir():
        stem = prefix / "MANIFEST"
    else:
        stem = prefix
    json_path = stem.with_suffix(".json")
    md_path = stem.with_suffix(".md")
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(render_manifest_json(report), encoding="utf-8")
    md_path.write_text(render_manifest_md(report), encoding="utf-8")
    return json_path, md_path


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Verify 6-role Gemini provenance and render MANIFEST.json and MANIFEST.md."
    )
    ap.add_argument("--root", default=".", help="repository root directory")
    ap.add_argument("--write", default=None, help="output path prefix for MANIFEST.json and MANIFEST.md")
    ap.add_argument("--strict", action="store_true", help="exit non-zero if provenance verification fails")
    ap.add_argument("--json", action="store_true", help="print JSON manifest to stdout")
    args = ap.parse_args(argv)

    root_path = Path(args.root).resolve()
    report = audit_provenance(root_path)

    written: tuple[Path, Path] | None = None
    if args.write:
        out_prefix = Path(args.write)
        if not out_prefix.is_absolute():
            out_prefix = root_path / out_prefix
        written = write_manifest(report, out_prefix)

    if args.json:
        sys.stdout.write(render_manifest_json(report))
    else:
        sys.stdout.write(render_manifest_md(report))
        if written is not None:
            print(f"wrote {written[0]} and {written[1]}")

    if args.strict and not report["verified"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
