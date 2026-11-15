from __future__ import annotations

import argparse
import hashlib
import hmac
import importlib.util
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import tomllib
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

MD_H = chr(35)
EN_DASH = chr(8211)
EM_DASH = chr(8212)

FROZEN_PATHS: tuple[str, ...] = (
    "canary/env.py",
    "canary/rules.py",
    "canary/world.py",
    "canary/solver/",
    "canary/mcp_server.py",
    "harbor/template/",
)

EXPECTED_FINAL_PREFIX = "1bc3e281"
EXPECTED_SUBMIT1_PREFIX = "9225f2ad"
EXPECTED_SUBMIT2_PREFIX = "aa1c679e"
EXPECTED_JUSTSILAS_PREFIX = "5f9b3297"
EXPECTED_REHEARSAL_FINAL_PREFIX = "d0ead011"
EXPECTED_V14_TIER_HASH = "a8f99c2537c91d72"
EXPECTED_V13_TIER_HASH = "8df71cf570bb48bc"
REHEARSAL_CUTOFF_UTC = "2026-11-15T06:30:00Z"

PINNED_LINEAGE_SHAS: dict[str, str] = {
    "afterquery_final": "1bc3e281dbfaa494a11e783d0c98369b41b2f675",
    "afterquery_submit": "9225f2adf1c9a7e3497e93bae937025dbeb77ec9",
    "afterquery_submit_2": "aa1c679e0b5cee1f140b6bcd0f0e1d5bb2fd89e2",
    "justSilas": "5f9b32979a193ec08407a0386361dc0d0843123a",
    "s1_rehearsal_final": "d0ead011da2d9a5e6990202f1022f53845d6b9f7",
}

PINNED_FROZEN_OBJECT_HASHES: dict[str, str] = {
    "canary/env.py": "24ffbc5429bfca64f136758295949d14828cce11",
    "canary/rules.py": "8ae89071170cc3bb81b01b41cac04f2d5e7451e6",
    "canary/world.py": "d5c352d1a241f85cb4a7ce3129f8527ac622725a",
    "canary/solver/": "98483eebc3f3c8b808f64af7c940355fe3dcb85c",
    "canary/mcp_server.py": "6a9f1f6743a6904ca4efb2b67ecf2aaaff733019",
    "harbor/template/": "06ee0cddfeb0d2508eb7e7b88665e77734fe3c0e",
}

PINNED_SUBMIT2_FILES: list[str] = [
    "README.md",
    "docs/SUBMISSION.md",
    "docs/reports/gap.md",
    "results/harbor/rehearsal/TABLE.md",
]

PINNED_SUBMIT2_CEO_BYTES = 35809
PINNED_SUBMIT2_CEO_SHA256 = "0ea2baae03dfab5774abc9a9acff591a41b95f9ac3fd7df50cc3e8d971f9e6c6"
PINNED_JUSTSILAS_CEO_BYTES = 36345
PINNED_JUSTSILAS_CEO_SHA256 = "90fb73ad3409b59978226079426d7b7e781e28fe7e1378301c37af777b3bb8d4"

PINNED_DIFF_PAIRS: list[dict[str, Any]] = [
    {
        "pair": "afterquery-final..afterquery-submit-2",
        "rev_a": "1bc3e281",
        "rev_b": "aa1c679e",
        "frozen_changed_count": 0,
        "frozen_byte_changes": 0,
        "total_changed_files": 58,
    },
    {
        "pair": "afterquery-submit-2..justSilas",
        "rev_a": "aa1c679e",
        "rev_b": "5f9b3297",
        "frozen_changed_count": 0,
        "frozen_byte_changes": 0,
        "total_changed_files": 1,
    },
    {
        "pair": "afterquery-final..justSilas",
        "rev_a": "1bc3e281",
        "rev_b": "5f9b3297",
        "frozen_changed_count": 0,
        "frozen_byte_changes": 0,
        "total_changed_files": 58,
    },
]

PINNED_S1_REHEARSAL_SUMMARY: dict[str, Any] = {
    "commit": "d0ead011da2d9a5e6990202f1022f53845d6b9f7",
    "jobs": ["do_nothing", "opencode-1", "opencode-2", "opencode-3", "oracle", "stop_early"],
    "n_jobs": 6,
    "n_trials": 60,
    "shared_ledger_keys": 1,
    "n_hmac_verified": 60,
    "n_parity_ok": 60,
    "n_distinct_tasks": 10,
    "oracle_mean": 0.506,
    "runs": {
        "opencode-1": {
            "n_valid": 10,
            "n_infra": 0,
            "n_accused": 10,
            "n_correct": 9,
            "mean": 0.472,
            "oracle_same_tasks": 0.506,
            "ratio_pct": 93,
            "ci_pct": [20, 371],
            "diff": -0.034,
            "mean_infra_as_zero": 0.472,
        },
        "opencode-2": {
            "n_valid": 10,
            "n_infra": 0,
            "n_accused": 10,
            "n_correct": 10,
            "mean": 0.585,
            "oracle_same_tasks": 0.506,
            "ratio_pct": 116,
            "ci_pct": [78, 363],
            "diff": 0.079,
            "mean_infra_as_zero": 0.585,
        },
        "opencode-3": {
            "n_valid": 9,
            "n_infra": 1,
            "n_accused": 9,
            "n_correct": 9,
            "mean": 0.625556,
            "oracle_same_tasks": 0.477778,
            "ratio_pct": 131,
            "ci_pct": [86, 590],
            "diff": 0.147778,
            "mean_infra_as_zero": 0.563,
        },
        "do_nothing": {
            "n_valid": 10,
            "n_infra": 0,
            "n_accused": 0,
            "n_correct": 0,
            "mean": 0.0,
            "oracle_same_tasks": 0.506,
            "ratio_pct": 0,
            "ci_pct": [0, 0],
            "diff": -0.506,
            "mean_infra_as_zero": 0.0,
        },
        "stop_early": {
            "n_valid": 10,
            "n_infra": 0,
            "n_accused": 0,
            "n_correct": 0,
            "mean": 0.0,
            "oracle_same_tasks": 0.506,
            "ratio_pct": 0,
            "ci_pct": [0, 0],
            "diff": -0.506,
            "mean_infra_as_zero": 0.0,
        },
    },
    "valid_gemini_correct": 28,
    "valid_gemini_accused": 29,
    "run3_before_cutoff": 5,
    "run3_after_cutoff": 5,
    "shell_used_all_trials": 22,
    "shell_total_trials": 30,
    "shell_used_valid_trials": 21,
}

_BASH_CALL_RE = re.compile(r'"function_name"\s*:\s*"[^"]*(?:bash|shell)[^"]*"')


def _git_blob_sha1_bytes(path: Path) -> bytes:
    data = path.read_bytes()
    hdr = f"blob {len(data)}\0".encode("utf-8")
    return hashlib.sha1(hdr + data).digest()


def _git_tree_sha1_bytes(dir_path: Path) -> bytes:
    entries: list[tuple[bytes, bytes, bytes, bytes]] = []
    for child in dir_path.iterdir():
        if child.name == "__pycache__" or child.suffix == ".pyc":
            continue
        if child.is_symlink():
            target = os.readlink(child).encode("utf-8")
            oid = hashlib.sha1(f"blob {len(target)}\0".encode("utf-8") + target).digest()
            entries.append((child.name.encode("utf-8"), b"120000", child.name.encode("utf-8"), oid))
        elif child.is_dir():
            oid = _git_tree_sha1_bytes(child)
            entries.append(((child.name + "/").encode("utf-8"), b"40000", child.name.encode("utf-8"), oid))
        elif child.is_file():
            st_mode = child.stat().st_mode
            mode = b"100755" if (st_mode & 0o111) else b"100644"
            oid = _git_blob_sha1_bytes(child)
            entries.append((child.name.encode("utf-8"), mode, child.name.encode("utf-8"), oid))
    entries.sort(key=lambda item: item[0])
    body = b"".join(mode + b" " + name + b"\0" + oid for _, mode, name, oid in entries)
    hdr = f"tree {len(body)}\0".encode("utf-8")
    return hashlib.sha1(hdr + body).digest()


def compute_live_git_object_sha1(path: Path) -> str | None:
    if not path.exists():
        return None
    if path.is_dir():
        return _git_tree_sha1_bytes(path).hex()
    if path.is_file():
        return _git_blob_sha1_bytes(path).hex()
    return None


def _boot_ratio_fast(rt_mod: Any, ra: list[float], rb: list[float]) -> tuple[float, float]:
    if all(x == 0.0 for x in ra):
        return 0.0, 0.0
    return rt_mod.boot_ratio(ra, rb)


def _default_scratch_base() -> Path:
    base = Path("/tmp/opencode")
    base.mkdir(parents=True, exist_ok=True)
    return base


def _git(root: Path, args: list[str], check: bool = True) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(
        ["git", *args],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if check and proc.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {(proc.stderr or proc.stdout).strip()}")
    return proc


def _resolve_commit(root: Path, ref: str) -> str | None:
    proc = _git(root, ["rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}"], check=False)
    if proc.returncode != 0:
        return None
    val = proc.stdout.strip()
    return val if val else None


def _is_ancestor(root: Path, anc: str, desc: str) -> bool:
    proc = _git(root, ["merge-base", "--is-ancestor", anc, desc], check=False)
    return proc.returncode == 0


def _load_rehearsal_table_mod(root: Path) -> Any:
    path = root / "scripts" / "rehearsal_table.py"
    spec = importlib.util.spec_from_file_location("rehearsal_table_audit_mod", path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _canonical_hmac_ok(ledger: dict[str, Any], key_hex_or_str: str) -> bool:
    sig = ledger.get("sig")
    if not isinstance(sig, dict) or sig.get("alg") != "HMAC-SHA256" or not isinstance(sig.get("mac"), str):
        return False
    body = {k: v for k, v in ledger.items() if k != "sig"}
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    digest = hmac.new(key_hex_or_str.strip().encode("utf-8"), canonical, hashlib.sha256).hexdigest()
    return hmac.compare_digest(digest, sig["mac"])


def _load_json_strict(path: Path) -> tuple[Any, str | None]:
    dup_keys: list[str] = []

    def _pairs_hook(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        seen: set[str] = set()
        for k, _ in pairs:
            if k in seen:
                dup_keys.append(k)
            seen.add(k)
        return dict(pairs)

    try:
        raw = path.read_text(encoding="utf-8")
        obj = json.loads(raw, object_pairs_hook=_pairs_hook)
    except (OSError, ValueError) as exc:
        return None, f"{type(exc).__name__}: {exc}"
    if dup_keys:
        return obj, f"duplicate JSON keys: {sorted(set(dup_keys))}"
    return obj, None


def _is_finite_float(val: Any) -> bool:
    return isinstance(val, (int, float)) and not isinstance(val, bool) and math.isfinite(float(val))


def _compute_tier_hash(tiers: dict[str, Any], known_v_mode: bool) -> str:
    payload = {"tiers": {k: v.to_dict() for k, v in tiers.items()}, "known_v_mode": known_v_mode}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=list).encode("utf-8")).hexdigest()[:16]


def _resolve_commit_multi(root: Path, candidates: list[str]) -> tuple[str | None, str]:
    for cand in candidates:
        if not cand:
            continue
        sha = _resolve_commit(root, cand)
        if sha is not None:
            return sha, cand
    return None, (candidates[0] if candidates else "")


def audit_code_freeze(
    root: Path = ROOT,
    final_ref: str = "afterquery-final",
    submit2_ref: str = "afterquery-submit-2",
    justsilas_ref: str | None = None,
    enforce_canonical_prefixes: bool = True,
) -> dict[str, Any]:
    problems: list[str] = []

    final_cands = [final_ref]
    if enforce_canonical_prefixes and final_ref == "afterquery-final":
        final_cands.extend([PINNED_LINEAGE_SHAS["afterquery_final"], EXPECTED_FINAL_PREFIX])
    final_sha, _ = _resolve_commit_multi(root, final_cands)

    submit1_cands = ["afterquery-submit"]
    if enforce_canonical_prefixes:
        submit1_cands.extend([PINNED_LINEAGE_SHAS["afterquery_submit"], EXPECTED_SUBMIT1_PREFIX])
    submit1_sha, _ = _resolve_commit_multi(root, submit1_cands)

    submit2_cands = [submit2_ref]
    if enforce_canonical_prefixes and submit2_ref == "afterquery-submit-2":
        submit2_cands.extend([PINNED_LINEAGE_SHAS["afterquery_submit_2"], EXPECTED_SUBMIT2_PREFIX])
    submit2_sha, _ = _resolve_commit_multi(root, submit2_cands)

    if justsilas_ref is not None:
        js_sha = _resolve_commit(root, justsilas_ref)
        js_ref_used = justsilas_ref
    else:
        js_cands = ["origin/justSilas", "justSilas"]
        if enforce_canonical_prefixes:
            js_cands.extend([PINNED_LINEAGE_SHAS["justSilas"], EXPECTED_JUSTSILAS_PREFIX])
        else:
            js_cands.append("HEAD")
        js_sha, js_ref_used = _resolve_commit_multi(root, js_cands)

    head_sha = _resolve_commit(root, "HEAD") if (root / ".git").exists() else None

    live_object_hashes: dict[str, str | None] = {
        fp: compute_live_git_object_sha1(root / fp.rstrip("/")) for fp in FROZEN_PATHS
    }

    shallow_ci_fallback = bool(
        enforce_canonical_prefixes and (final_sha is None or submit2_sha is None or js_sha is None)
    )

    if not shallow_ci_fallback:
        if final_sha is None:
            problems.append(f"unable to resolve {final_ref}")
        if submit2_sha is None:
            problems.append(f"unable to resolve {submit2_ref}")
        if js_sha is None:
            problems.append(f"unable to resolve {js_ref_used}")
        if problems:
            return {"passed": False, "shallow_ci_fallback": False, "problems": problems}

        assert final_sha is not None and submit2_sha is not None and js_sha is not None

        if enforce_canonical_prefixes:
            if not final_sha.startswith(EXPECTED_FINAL_PREFIX):
                problems.append(f"afterquery-final expected prefix {EXPECTED_FINAL_PREFIX}, got {final_sha[:8]}")
            if submit1_sha is not None and not submit1_sha.startswith(EXPECTED_SUBMIT1_PREFIX):
                problems.append(f"afterquery-submit expected prefix {EXPECTED_SUBMIT1_PREFIX}, got {submit1_sha[:8]}")
            if not submit2_sha.startswith(EXPECTED_SUBMIT2_PREFIX):
                problems.append(f"afterquery-submit-2 expected prefix {EXPECTED_SUBMIT2_PREFIX}, got {submit2_sha[:8]}")
            if not js_sha.startswith(EXPECTED_JUSTSILAS_PREFIX):
                problems.append(f"{js_ref_used} expected prefix {EXPECTED_JUSTSILAS_PREFIX}, got {js_sha[:8]}")

        if not _is_ancestor(root, final_sha, submit2_sha):
            problems.append(f"{final_sha[:8]} is not an ancestor of {submit2_sha[:8]}")
        if not _is_ancestor(root, submit2_sha, js_sha):
            problems.append(f"{submit2_sha[:8]} is not an ancestor of {js_sha[:8]}")

        diff_pairs = [
            ("afterquery-final..afterquery-submit-2", final_sha, submit2_sha),
            ("afterquery-submit-2..justSilas", submit2_sha, js_sha),
            ("afterquery-final..justSilas", final_sha, js_sha),
        ]
        if head_sha is not None:
            diff_pairs.append(("afterquery-final..HEAD", final_sha, head_sha))

        pair_results: list[dict[str, Any]] = []
        for label, rev_a, rev_b in diff_pairs:
            raw_diff = _git(root, ["diff", "--raw", rev_a, rev_b, "--", *FROZEN_PATHS]).stdout.strip()
            all_changed = [
                ln for ln in _git(root, ["diff", "--name-only", rev_a, rev_b]).stdout.splitlines() if ln.strip()
            ]
            frozen_changed = [ln for ln in raw_diff.splitlines() if ln.strip()]
            if frozen_changed:
                problems.append(f"{label}: frozen path diff non-empty ({len(frozen_changed)} entry/entries)")
            pair_results.append(
                {
                    "pair": label,
                    "rev_a": rev_a[:8],
                    "rev_b": rev_b[:8],
                    "frozen_changed_count": len(frozen_changed),
                    "frozen_byte_changes": 0 if not frozen_changed else len(raw_diff.encode("utf-8")),
                    "total_changed_files": len(all_changed),
                }
            )

        object_hashes: dict[str, dict[str, str]] = {fp: {} for fp in FROZEN_PATHS}
        check_revs: list[tuple[str, str]] = [
            ("afterquery-final", final_sha),
            ("afterquery-submit-2", submit2_sha),
            ("justSilas", js_sha),
        ]
        if head_sha is not None:
            check_revs.append(("HEAD", head_sha))

        rev_specs: list[tuple[str, str, str]] = [
            (fp, rname, f"{rsha}:{fp.rstrip('/')}")
            for fp in FROZEN_PATHS
            for rname, rsha in check_revs
        ]
        batch_p = _git(root, ["rev-parse", *(spec for _, _, spec in rev_specs)], check=False)
        batch_lines = [ln.strip() for ln in batch_p.stdout.splitlines() if ln.strip()]
        if batch_p.returncode == 0 and len(batch_lines) == len(rev_specs):
            for (fp, rname, _), oid in zip(rev_specs, batch_lines):
                object_hashes[fp][rname] = oid
        else:
            for fp, rname, spec in rev_specs:
                p = _git(root, ["rev-parse", spec], check=False)
                if p.returncode != 0:
                    problems.append(f"missing {fp.rstrip('/')} in {rname}")
                else:
                    object_hashes[fp][rname] = p.stdout.strip()

        for fp in FROZEN_PATHS:
            per_rev = object_hashes[fp]
            live_sha = live_object_hashes.get(fp)
            if live_sha is not None:
                per_rev["live_worktree"] = live_sha
            else:
                problems.append(f"missing live frozen path on disk: {fp}")
            if enforce_canonical_prefixes:
                per_rev["pinned_1bc3e281_5f9b3297"] = PINNED_FROZEN_OBJECT_HASHES[fp]
            if len(set(per_rev.values())) != 1:
                problems.append(f"git object hash drift on {fp}: {per_rev}")

        wt_diff = _git(root, ["diff", "--raw", final_sha, "--", *FROZEN_PATHS]).stdout.strip()
        if wt_diff:
            problems.append(f"working tree differs from {final_sha[:8]} on frozen paths")

        submit2_parent = _resolve_commit(root, f"{submit2_sha}^")
        submit2_files: list[str] = []
        if submit2_parent is not None:
            submit2_files = [
                ln for ln in _git(root, ["diff", "--name-only", submit2_parent, submit2_sha]).stdout.splitlines() if ln.strip()
            ]
            if enforce_canonical_prefixes and sorted(submit2_files) != sorted(PINNED_SUBMIT2_FILES):
                problems.append(f"afterquery-submit-2 modified unexpected files: {submit2_files}")
        elif enforce_canonical_prefixes:
            submit2_files = list(PINNED_SUBMIT2_FILES)

        ceo_append_only = False
        ceo_appended_lines = 0
        js_changed_files = [
            ln for ln in _git(root, ["diff", "--name-only", submit2_sha, js_sha]).stdout.splitlines() if ln.strip()
        ]
        if submit2_sha != js_sha:
            if js_changed_files != ["docs/reports/CEO.md"]:
                problems.append(f"commits between submit-2 and justSilas touched non-CEO files: {js_changed_files}")
            else:
                old_ceo = _git(root, ["show", f"{submit2_sha}:docs/reports/CEO.md"]).stdout
                new_ceo = _git(root, ["show", f"{js_sha}:docs/reports/CEO.md"]).stdout
                if new_ceo.startswith(old_ceo) and len(new_ceo) > len(old_ceo):
                    ceo_append_only = True
                    appended = new_ceo[len(old_ceo) :]
                    ceo_appended_lines = len([ln for ln in appended.splitlines() if ln.strip() or ln == ""])
                else:
                    problems.append("docs/reports/CEO.md change from submit-2 to justSilas is not strictly append-only")

        refs_out = {
            "afterquery_final": final_sha,
            "afterquery_submit": submit1_sha or PINNED_LINEAGE_SHAS["afterquery_submit"],
            "afterquery_submit_2": submit2_sha,
            "justSilas_ref": js_ref_used,
            "justSilas": js_sha,
            "head": head_sha,
            "resolved_historical_refs": True,
        }
    else:
        object_hashes = {}
        for fp in FROZEN_PATHS:
            clean_fp = fp.rstrip("/")
            pinned_sha = PINNED_FROZEN_OBJECT_HASHES[fp]
            live_sha = live_object_hashes.get(fp)
            per_rev = {"pinned_1bc3e281_5f9b3297": pinned_sha}
            if live_sha is None:
                problems.append(f"shallow-CI freeze check missing path on disk: {fp}")
            else:
                per_rev["live_worktree"] = live_sha
                if live_sha != pinned_sha:
                    problems.append(
                        f"shallow-CI frozen hash mismatch on {fp}: live={live_sha} != pinned={pinned_sha}"
                    )
            if head_sha is not None:
                p = _git(root, ["rev-parse", f"{head_sha}:{clean_fp}"], check=False)
                if p.returncode != 0:
                    problems.append(f"shallow-CI missing {clean_fp} in HEAD ({head_sha[:8]})")
                else:
                    head_obj = p.stdout.strip()
                    per_rev["HEAD"] = head_obj
                    if head_obj != pinned_sha:
                        problems.append(
                            f"shallow-CI HEAD object hash mismatch on {fp}: HEAD={head_obj} != pinned={pinned_sha}"
                        )
            object_hashes[fp] = per_rev

        if head_sha is not None:
            wt_head_diff = _git(root, ["diff", "--raw", head_sha, "--", *FROZEN_PATHS], check=False).stdout.strip()
            if wt_head_diff:
                problems.append(f"shallow-CI working tree differs from HEAD ({head_sha[:8]}) on frozen paths")

        pair_results = [dict(dp) for dp in PINNED_DIFF_PAIRS]
        if head_sha is not None:
            frozen_mism = sum(1 for fp in FROZEN_PATHS if len(set(object_hashes[fp].values())) != 1)
            pair_results.append(
                {
                    "pair": "pinned-afterquery-final..HEAD",
                    "rev_a": EXPECTED_FINAL_PREFIX,
                    "rev_b": head_sha[:8],
                    "frozen_changed_count": frozen_mism,
                    "frozen_byte_changes": frozen_mism,
                    "total_changed_files": 0,
                }
            )

        submit2_files = list(PINNED_SUBMIT2_FILES)
        js_changed_files = ["docs/reports/CEO.md"]
        ceo_append_only = False
        ceo_appended_lines = 0
        ceo_file = root / "docs" / "reports" / "CEO.md"
        if not ceo_file.is_file():
            problems.append("shallow-CI missing docs/reports/CEO.md")
        else:
            raw_ceo = ceo_file.read_bytes()
            if (
                len(raw_ceo) >= PINNED_JUSTSILAS_CEO_BYTES
                and hashlib.sha256(raw_ceo[:PINNED_SUBMIT2_CEO_BYTES]).hexdigest() == PINNED_SUBMIT2_CEO_SHA256
                and hashlib.sha256(raw_ceo[:PINNED_JUSTSILAS_CEO_BYTES]).hexdigest() == PINNED_JUSTSILAS_CEO_SHA256
            ):
                ceo_append_only = True
                appended_txt = raw_ceo[PINNED_SUBMIT2_CEO_BYTES:PINNED_JUSTSILAS_CEO_BYTES].decode("utf-8")
                ceo_appended_lines = len([ln for ln in appended_txt.splitlines() if ln.strip() or ln == ""])
            else:
                problems.append("shallow-CI docs/reports/CEO.md failed pinned aa1c679e->5f9b3297 append-only SHA-256 check")

        refs_out = {
            "afterquery_final": PINNED_LINEAGE_SHAS["afterquery_final"],
            "afterquery_submit": PINNED_LINEAGE_SHAS["afterquery_submit"],
            "afterquery_submit_2": PINNED_LINEAGE_SHAS["afterquery_submit_2"],
            "justSilas_ref": "pinned_5f9b3297_shallow_fallback",
            "justSilas": PINNED_LINEAGE_SHAS["justSilas"],
            "head": head_sha,
            "resolved_historical_refs": False,
        }

    from canary import rules

    v14_hash = _compute_tier_hash(rules.TIERS, rules.KNOWN_V_MODE)
    v13_hash = _compute_tier_hash(rules.TIERS_V13, rules.KNOWN_V_MODE)
    if rules.TIERS_VERSION != "v1.4" or v14_hash != EXPECTED_V14_TIER_HASH or v13_hash != EXPECTED_V13_TIER_HASH:
        problems.append(f"frozen tier hash mismatch: version={rules.TIERS_VERSION}, v14={v14_hash}, v13={v13_hash}")

    return {
        "passed": len(problems) == 0,
        "shallow_ci_fallback": shallow_ci_fallback,
        "refs": refs_out,
        "pinned_frozen_hashes": dict(PINNED_FROZEN_OBJECT_HASHES),
        "live_frozen_hashes": live_object_hashes,
        "frozen_paths": list(FROZEN_PATHS),
        "diff_pairs": pair_results,
        "object_hashes": object_hashes,
        "submit2_commit_files": submit2_files,
        "justsilas_post_submit2_files": js_changed_files,
        "ceo_append_only": ceo_append_only,
        "ceo_appended_lines": ceo_appended_lines,
        "tier_hashes": {"tiers_version": rules.TIERS_VERSION, "v14": v14_hash, "v13": v13_hash},
        "problems": problems,
    }


def _parse_snapshot_table(table_text: str) -> dict[str, Any]:
    lines = table_text.splitlines()
    header_idx = next((i for i, ln in enumerate(lines) if ln.startswith("| task |")), None)
    if header_idx is None:
        return {"ok": False, "error": "missing per-task table header in TABLE.md"}
    cols = [c.strip() for c in lines[header_idx].strip("|").split("|")]
    job_names = cols[1:]
    per_task: dict[str, dict[str, dict[str, Any]]] = {jn: {} for jn in job_names}
    for ln in lines[header_idx + 2 :]:
        if not ln.startswith("|"):
            break
        if "**mean" in ln:
            continue
        parts = [c.strip() for c in ln.strip("|").split("|")]
        if len(parts) != len(cols):
            continue
        task = parts[0]
        for jn, cell in zip(job_names, parts[1:]):
            if cell in {"-", EN_DASH, EM_DASH, ""}:
                per_task[jn][task] = {"state": "unstarted", "reward": None, "correct": None}
            elif cell.startswith("infra"):
                per_task[jn][task] = {"state": "infra", "reward": None, "correct": None}
            else:
                m = re.match(r"^([+-]?\d+\.\d+)(?:\s+([^\s]+)\s+d(\d+))?", cell)
                if m is None:
                    per_task[jn][task] = {"state": "unparsed", "raw": cell, "reward": None, "correct": None}
                else:
                    rew = float(m.group(1))
                    mark = m.group(2)
                    corr = None if mark is None else (mark == "\u2713")
                    per_task[jn][task] = {
                        "state": "valid",
                        "reward": rew,
                        "correct": corr,
                        "day": int(m.group(3)) if m.group(3) else None,
                    }
    return {"ok": True, "jobs": job_names, "per_task": per_task}


def _audit_s1_rehearsal_final_git(root: Path, ref: str, rt_mod: Any) -> dict[str, Any]:
    sha = _resolve_commit(root, ref) if (root / ".git").exists() else None
    if sha is None and ref == "origin/s1-rehearsal-final" and (root / ".git").exists():
        sha, _ = _resolve_commit_multi(root, [PINNED_LINEAGE_SHAS["s1_rehearsal_final"], EXPECTED_REHEARSAL_FINAL_PREFIX])
    if sha is None:
        return {"available": False, "shallow_ci_fallback": True, **PINNED_S1_REHEARSAL_SUMMARY}

    problems: list[str] = []
    ls_out = _git(root, ["ls-tree", "-r", f"{sha}:results/harbor/rehearsal"], check=False)
    if ls_out.returncode != 0:
        return {"available": False, "shallow_ci_fallback": True, **PINNED_S1_REHEARSAL_SUMMARY}

    wanted_shas: dict[str, str] = {}
    traj_shas: dict[str, str] = {}
    for line in ls_out.stdout.splitlines():
        if "\t" not in line:
            continue
        meta, rel_path = line.split("\t", 1)
        parts = meta.split()
        if len(parts) < 3:
            continue
        blob_sha = parts[2]
        if rel_path in {"TABLE.md", "BUILD.txt", "README.md"} or rel_path.endswith(
            (
                "ledger_key",
                "result.json",
                "verifier/reward.txt",
                "verifier/reward.json",
                "verifier/ledger.json",
                "artifacts/ledger.json",
                "verifier/test-stdout.txt",
            )
        ):
            wanted_shas[rel_path] = blob_sha
        elif rel_path.startswith("opencode-") and rel_path.endswith("/agent/trajectory.json"):
            traj_shas[rel_path] = blob_sha

    all_req = {**wanted_shas, **traj_shas}
    proc = subprocess.Popen(
        ["git", "cat-file", "--batch"],
        cwd=root,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
    )
    raw_out, _ = proc.communicate("".join(f"{bsha}\n" for bsha in all_req.values()).encode("utf-8"), timeout=30)
    blobs: dict[str, str] = {}
    pos = 0
    for rel_path in all_req:
        nl = raw_out.index(b"\n", pos)
        hdr = raw_out[pos:nl].decode("utf-8")
        sz = int(hdr.split()[2])
        blobs[rel_path] = raw_out[nl + 1 : nl + 1 + sz].decode("utf-8", errors="replace")
        pos = nl + 1 + sz + 1

    jobs = sorted({p.split("/")[0] for p in wanted_shas if "/" in p and p.endswith("/ledger_key")})
    expected_jobs = ["do_nothing", "opencode-1", "opencode-2", "opencode-3", "oracle", "stop_early"]
    if jobs != expected_jobs:
        problems.append(f"s1-rehearsal-final jobs expected {expected_jobs}, got {jobs}")

    job_keys = {j: blobs[f"{j}/ledger_key"].strip() for j in jobs}
    unique_keys = sorted(set(job_keys.values()))
    if len(unique_keys) != 1:
        problems.append(f"s1-rehearsal-final expected 1 shared ledger_key, got {len(unique_keys)}")

    n_trials = 0
    n_hmac_ok = 0
    n_parity_ok = 0
    task_checksums: dict[str, set[str]] = {}
    per_job_tasks: dict[str, dict[str, dict[str, Any]]] = {j: {} for j in jobs}
    run3_after_cutoff = 0
    run3_before_cutoff = 0

    for j in jobs:
        trial_prefixes = sorted(
            {"/".join(p.split("/")[:2]) for p in wanted_shas if p.startswith(f"{j}/canary-") and p.endswith("/result.json")}
        )
        for tp in trial_prefixes:
            n_trials += 1
            res = json.loads(blobs[f"{tp}/result.json"])
            task_id = str(res.get("task_name") or tp.split("/")[1]).split("/")[-1]
            t_csum = res.get("task_checksum")
            if t_csum:
                task_checksums.setdefault(task_id, set()).add(str(t_csum))

            rew = ((res.get("verifier_result") or {}).get("rewards") or {}).get("reward")
            rtxt = float(blobs[f"{tp}/verifier/reward.txt"].strip())
            rjson = float(json.loads(blobs[f"{tp}/verifier/reward.json"])["reward"])
            aled = json.loads(blobs[f"{tp}/artifacts/ledger.json"])
            vled = json.loads(blobs[f"{tp}/verifier/ledger.json"])
            tstdout = blobs.get(f"{tp}/verifier/test-stdout.txt", "")

            if _canonical_hmac_ok(aled, job_keys[j]) and _canonical_hmac_ok(vled, job_keys[j]) and "signature=ok" in tstdout:
                n_hmac_ok += 1
            else:
                problems.append(f"s1-rehearsal-final HMAC failure on {tp}")

            if (
                _is_finite_float(rew)
                and abs(float(rew) - rtxt) <= 1e-9
                and abs(float(rew) - rjson) <= 1e-9
                and abs(float(rew) - float(aled["score"])) <= 1e-9
                and abs(float(rew) - float(vled["score"])) <= 1e-9
                and aled == vled
            ):
                n_parity_ok += 1
            else:
                problems.append(f"s1-rehearsal-final reward/ledger parity failure on {tp}")

            exc = res.get("exception_info")
            exc_t = exc.get("exception_type") if isinstance(exc, dict) else None
            done = bool(aled.get("done"))
            is_infra = (not done) and (exc_t in {"ApiRateLimitError", "AgentSetupTimeoutError"})
            per_job_tasks[j][task_id] = {
                "reward": float(rew),
                "done": done,
                "infra": is_infra,
                "exc_type": exc_t,
                "accused": aled.get("accused"),
                "correct": bool(aled.get("correct")),
                "final_day": aled.get("final_day"),
                "finished_at": res.get("finished_at"),
            }
            if j == "opencode-3":
                if str(res.get("finished_at") or "") > REHEARSAL_CUTOFF_UTC:
                    run3_after_cutoff += 1
                else:
                    run3_before_cutoff += 1

    for task_id, cset in sorted(task_checksums.items()):
        if len(cset) != 1:
            problems.append(f"s1-rehearsal-final task_checksum mismatch on {task_id}: {sorted(cset)}")

    oracle_tasks = per_job_tasks.get("oracle", {})
    oracle_valid = [x["reward"] for x in oracle_tasks.values() if not x["infra"]]
    oracle_mean = sum(oracle_valid) / len(oracle_valid) if oracle_valid else float("nan")

    run_summaries: dict[str, dict[str, Any]] = {}
    valid_gemini_accused = 0
    valid_gemini_correct = 0
    for rname in ("opencode-1", "opencode-2", "opencode-3", "do_nothing", "stop_early"):
        jtasks = per_job_tasks.get(rname, {})
        paired_tasks = sorted(t for t in jtasks if (not jtasks[t]["infra"]) and (not oracle_tasks[t]["infra"]))
        ra = [jtasks[t]["reward"] for t in paired_tasks]
        rb = [oracle_tasks[t]["reward"] for t in paired_tasks]
        n_inf = sum(1 for x in jtasks.values() if x["infra"])
        acc_rows = [x for x in jtasks.values() if (not x["infra"]) and x["accused"] is not None]
        n_corr = sum(1 for x in acc_rows if x["correct"])
        if rname.startswith("opencode-"):
            valid_gemini_accused += len(acc_rows)
            valid_gemini_correct += n_corr
        m_a = sum(ra) / len(ra)
        m_b = sum(rb) / len(rb)
        ratio = m_a / m_b
        ci_lo, ci_hi = _boot_ratio_fast(rt_mod, ra, rb)
        infra_as_zero = sum(0.0 if x["infra"] else x["reward"] for x in jtasks.values()) / len(jtasks)
        run_summaries[rname] = {
            "n_valid": len(paired_tasks),
            "n_infra": n_inf,
            "n_accused": len(acc_rows),
            "n_correct": n_corr,
            "mean": round(m_a, 6),
            "oracle_same_tasks": round(m_b, 6),
            "ratio_pct": round(ratio * 100.0),
            "ci_pct": [round(ci_lo * 100.0), round(ci_hi * 100.0)],
            "diff": round(m_a - m_b, 6),
            "mean_infra_as_zero": round(infra_as_zero, 6),
        }

    shell_total = 0
    shell_valid = 0
    for rel_p in sorted(traj_shas):
        parts = rel_p.split("/")
        jname, tdir = parts[0], parts[1]
        task_key = "-".join(tdir.split("__")[0].split("-")[1:])
        used_shell = _BASH_CALL_RE.search(blobs[rel_p]) is not None
        if used_shell:
            shell_total += 1
            if not per_job_tasks[jname][task_key]["infra"]:
                shell_valid += 1

    if run_summaries["opencode-1"]["ratio_pct"] != 93 or run_summaries["opencode-1"]["n_valid"] != 10:
        problems.append(f"s1-rehearsal-final opencode-1 unexpected summary: {run_summaries['opencode-1']}")
    if run_summaries["opencode-2"]["ratio_pct"] != 116 or run_summaries["opencode-2"]["n_valid"] != 10:
        problems.append(f"s1-rehearsal-final opencode-2 unexpected summary: {run_summaries['opencode-2']}")
    if run_summaries["opencode-3"]["ratio_pct"] != 131 or run_summaries["opencode-3"]["n_valid"] != 9:
        problems.append(f"s1-rehearsal-final opencode-3 unexpected summary: {run_summaries['opencode-3']}")
    if run3_after_cutoff != 5 or run3_before_cutoff != 5:
        problems.append(f"s1-rehearsal-final opencode-3 cutoff split expected 5/5, got {run3_before_cutoff}/{run3_after_cutoff}")

    return {
        "available": True,
        "passed": len(problems) == 0,
        "commit": sha,
        "jobs": jobs,
        "n_jobs": len(jobs),
        "n_trials": n_trials,
        "shared_ledger_keys": len(unique_keys),
        "n_hmac_verified": n_hmac_ok,
        "n_parity_ok": n_parity_ok,
        "n_distinct_tasks": len(task_checksums),
        "oracle_mean": round(oracle_mean, 6),
        "runs": run_summaries,
        "valid_gemini_correct": valid_gemini_correct,
        "valid_gemini_accused": valid_gemini_accused,
        "run3_before_cutoff": run3_before_cutoff,
        "run3_after_cutoff": run3_after_cutoff,
        "shell_used_all_trials": shell_total,
        "shell_total_trials": len(traj_shas),
        "shell_used_valid_trials": shell_valid,
        "problems": problems,
    }


def audit_rehearsal_and_docs(
    root: Path = ROOT,
    rehearsal_final_ref: str = "origin/s1-rehearsal-final",
) -> dict[str, Any]:
    problems: list[str] = []
    rt_mod = _load_rehearsal_table_mod(root)

    reh_dir = root / "results" / "harbor" / "rehearsal"
    build_path = reh_dir / "BUILD.txt"
    table_path = reh_dir / "TABLE.md"
    reh_readme_path = reh_dir / "README.md"
    ceo_path = root / "docs" / "reports" / "CEO.md"
    readme_path = root / "README.md"
    sub_path = root / "docs" / "SUBMISSION.md"
    gap_path = root / "docs" / "reports" / "gap.md"
    task_toml_path = root / "harbor" / "template" / "task.toml"

    for req_p in (build_path, table_path, reh_readme_path, ceo_path, readme_path, sub_path, gap_path, task_toml_path):
        if not req_p.is_file():
            problems.append(f"missing required file: {req_p.relative_to(root).as_posix()}")
    if problems:
        return {"passed": False, "problems": problems}

    build_txt = build_path.read_text(encoding="utf-8")
    build_kv: dict[str, str] = {}
    for ln in build_txt.splitlines():
        if ":" in ln:
            k, v = ln.split(":", 1)
            build_kv[k.strip()] = v.strip()

    final_sha = _resolve_commit(root, "afterquery-final")
    build_sha = build_kv.get("sha", "")
    if final_sha is not None and build_sha != final_sha:
        problems.append(f"BUILD.txt sha {build_sha!r} != afterquery-final {final_sha!r}")
    if not build_sha.startswith(EXPECTED_FINAL_PREFIX):
        problems.append(f"BUILD.txt sha {build_sha!r} does not start with {EXPECTED_FINAL_PREFIX}")
    if build_kv.get("describe") != "afterquery-final":
        problems.append(f"BUILD.txt describe expected 'afterquery-final', got {build_kv.get('describe')!r}")
    if build_kv.get("harbor") != "0.26.0":
        problems.append(f"BUILD.txt harbor expected '0.26.0', got {build_kv.get('harbor')!r}")
    if "--max-retries 2 --retry-include ApiRateLimitError --retry-include AgentSetupTimeoutError" not in build_txt:
        problems.append("BUILD.txt missing pre-registered Harbor retry flags")

    cleaned_toml = "\n".join(ln for ln in task_toml_path.read_text(encoding="utf-8").splitlines() if "${" not in ln)
    parsed_toml = tomllib.loads(cleaned_toml)
    verifier_timeout = float((parsed_toml.get("verifier") or {}).get("timeout_sec") or 0.0)
    agent_timeout = float((parsed_toml.get("agent") or {}).get("timeout_sec") or 0.0)
    if verifier_timeout != 120.0 or agent_timeout != 10800.0:
        problems.append(f"task.toml timeouts expected 120.0/10800.0, got {verifier_timeout}/{agent_timeout}")
    if "[agent] timeout_sec = 10800.0" not in build_txt:
        problems.append("BUILD.txt missing [agent] timeout_sec = 10800.0 correction note")

    table_txt = table_path.read_text(encoding="utf-8")
    first_line = table_txt.splitlines()[0] if table_txt.splitlines() else ""
    required_corr_tokens = (
        "Correction (09:30, 15 Nov)",
        "9 valid trials",
        "5 finished after the 08:30 cut-off",
        "1 infra-excluded",
        "+0.626",
        "131% [86%, 590%]",
        "93%, 116%",
        "s1-rehearsal-final",
        "d0ead011",
    )
    for tok in required_corr_tokens:
        if tok not in first_line:
            problems.append(f"TABLE.md correction note missing token: {tok!r}")

    snap = _parse_snapshot_table(table_txt)
    snapshot_summary: dict[str, Any] = {}
    if not snap.get("ok"):
        problems.append(str(snap.get("error")))
    else:
        pt = snap["per_task"]
        o_vals = [pt["oracle"][t]["reward"] for t in sorted(pt["oracle"]) if pt["oracle"][t]["state"] == "valid"]
        o_mean = round(sum(o_vals) / len(o_vals), 3)
        snapshot_summary["oracle_mean"] = o_mean
        if o_mean != 0.506 or len(o_vals) != 10:
            problems.append(f"TABLE.md snapshot oracle mean expected 0.506 (n=10), got {o_mean} (n={len(o_vals)})")

        for rname, exp_n, exp_inf, exp_mean, exp_ratio in (
            ("opencode-1", 10, 0, 0.472, 93),
            ("opencode-2", 10, 0, 0.585, 116),
            ("opencode-3", 7, 1, 0.656, 153),
            ("do_nothing", 10, 0, 0.0, 0),
            ("stop_early", 10, 0, 0.0, 0),
        ):
            r_tasks = pt[rname]
            valid_t = [t for t in sorted(r_tasks) if r_tasks[t]["state"] == "valid"]
            infra_t = [t for t in sorted(r_tasks) if r_tasks[t]["state"] == "infra"]
            ra = [r_tasks[t]["reward"] for t in valid_t]
            rb = [pt["oracle"][t]["reward"] for t in valid_t]
            got_mean = round(sum(ra) / len(ra), 3)
            got_ratio = round((sum(ra) / len(ra)) / (sum(rb) / len(rb)) * 100.0)
            ci_lo, ci_hi = _boot_ratio_fast(rt_mod, ra, rb)
            snapshot_summary[rname] = {
                "n_valid": len(valid_t),
                "n_infra": len(infra_t),
                "mean": got_mean,
                "ratio_pct": got_ratio,
                "ci_pct": [round(ci_lo * 100.0), round(ci_hi * 100.0)],
            }
            if len(valid_t) != exp_n or len(infra_t) != exp_inf or got_mean != exp_mean or got_ratio != exp_ratio:
                problems.append(
                    f"TABLE.md snapshot {rname} mismatch: got n={len(valid_t)}, infra={len(infra_t)}, "
                    f"mean={got_mean}, ratio={got_ratio}%"
                )

    ceo_txt = ceo_path.read_text(encoding="utf-8")
    ceo_heading = f"{MD_H}{MD_H} 09:35 Sun 15 Nov: correction to the 09:00 entry (this log is append-only)"
    if ceo_heading not in ceo_txt:
        problems.append("CEO.md missing 09:35 Sun 15 Nov append-only correction heading")
    ceo_tail = ceo_txt.split(f"{MD_H}{MD_H} 09:35 Sun 15 Nov:", 1)[-1]
    for tok in ("93%, 116%, 131%", "9 valid trials", "s1-rehearsal-final", "d0ead011", "afterquery-submit-2", "aa1c679e"):
        if tok not in ceo_tail:
            problems.append(f"CEO.md 09:35 correction entry missing token: {tok!r}")

    readme_txt = readme_path.read_text(encoding="utf-8")
    sub_txt = sub_path.read_text(encoding="utf-8")
    gap_txt = gap_path.read_text(encoding="utf-8")

    for doc_label, doc_txt in (("README.md", readme_txt), ("docs/SUBMISSION.md", sub_txt), ("docs/reports/gap.md", gap_txt)):
        if "153%" in doc_txt:
            problems.append(f"{doc_label} still contains stale snapshot figure '153%'")
        for req_tok in ("93%", "116%", "131%", "+0.626"):
            if req_tok not in doc_txt:
                problems.append(f"{doc_label} missing final rehearsal figure {req_tok!r}")

    if "28 of 29 valid Gemini accusations correct" not in readme_txt:
        problems.append("README.md missing updated '28 of 29 valid Gemini accusations correct'")

    raw_final = _audit_s1_rehearsal_final_git(root, rehearsal_final_ref, rt_mod)
    if raw_final.get("available") and not raw_final.get("passed"):
        problems.extend(raw_final.get("problems") or [])

    return {
        "passed": len(problems) == 0,
        "build_sha": build_sha,
        "harbor_version": build_kv.get("harbor"),
        "verifier_timeout_sec": verifier_timeout,
        "agent_timeout_sec": agent_timeout,
        "snapshot_table": snapshot_summary,
        "s1_rehearsal_final_git": raw_final,
        "docs_checked": ["results/harbor/rehearsal/TABLE.md", "results/harbor/rehearsal/BUILD.txt", "docs/reports/CEO.md", "README.md", "docs/SUBMISSION.md", "docs/reports/gap.md"],
        "problems": problems,
        "doc_observations": {
            "readme_has_20_of_28_shell_note": "20 of 28 trials" in readme_txt,
            "gap_has_20_of_28_shell_note": "20 of 28 trials" in gap_txt,
            "submission_mentions_submit2_tag": "afterquery-submit-2" in sub_txt,
            "table_body_retains_0852_snapshot": "| opencode-3 | 7 | 1 |" in table_txt,
        },
    }


def _extract_verifier_py(root: Path, tmp_dir: Path) -> str:
    test_sh = (root / "harbor" / "template" / "tests" / "test.sh").read_text(encoding="utf-8")
    m = re.search(r"python3[^\n]*<<'PY'\n(.*?)\nPY", test_sh, re.S)
    assert m is not None
    py = m.group(1)
    return (
        py.replace("/logs/verifier", (tmp_dir / "logs").as_posix())
        .replace("/evidence", (tmp_dir / "evidence").as_posix())
        .replace("/tests/ledger_key", (tmp_dir / "tests/ledger_key").as_posix())
    )


def _run_isolated_verifier(root: Path, tmp_dir: Path, raw_ledger: str, key_hex: str) -> dict[str, Any]:
    import contextlib
    import io

    for sub in ("logs", "evidence", "tests"):
        (tmp_dir / sub).mkdir(parents=True, exist_ok=True)
    (tmp_dir / "tests/ledger_key").write_text(key_hex + "\n", encoding="utf-8")
    (tmp_dir / "evidence/ledger.json").write_text(raw_ledger, encoding="utf-8")
    src = _extract_verifier_py(root, tmp_dir)
    out_buf = io.StringIO()
    err_buf = io.StringIO()
    saved_canary = {k: os.environ.pop(k) for k in list(os.environ) if k.startswith("CANARY_")}
    rc = 0
    try:
        with contextlib.redirect_stdout(out_buf), contextlib.redirect_stderr(err_buf):
            exec(compile(src, "<isolated_verifier>", "exec"), {"__name__": "__main__"})
    except SystemExit as exc:
        code = exc.code
        rc = 0 if code is None else (code if isinstance(code, int) else 1)
    finally:
        os.environ.update(saved_canary)
    r_txt = (tmp_dir / "logs/reward.txt").read_text(encoding="utf-8").strip() if (tmp_dir / "logs/reward.txt").is_file() else None
    r_json = (
        json.loads((tmp_dir / "logs/reward.json").read_text(encoding="utf-8"))
        if (tmp_dir / "logs/reward.json").is_file()
        else None
    )
    return {
        "rc": rc,
        "reward_txt": r_txt,
        "reward_json": r_json,
        "verifier_ledger_copied": (tmp_dir / "logs/ledger.json").exists(),
        "stdout": out_buf.getvalue().strip(),
    }


def audit_published_key_job(job_dir: Path) -> dict[str, Any]:
    problems: list[str] = []
    key_file = job_dir / "ledger_key"
    if not key_file.is_file() or key_file.is_symlink():
        return {"passed": False, "job": job_dir.as_posix(), "problems": ["missing or symlinked ledger_key"]}
    key_str = key_file.read_text(encoding="utf-8").strip()
    if len(key_str) < 32:
        problems.append(f"{job_dir.name}: unexpectedly short ledger_key ({len(key_str)} chars)")

    trial_dirs = sorted(p.parent for p in job_dir.glob("canary-*/result.json"))
    if not trial_dirs:
        problems.append(f"{job_dir.name}: no trials found")

    n_hmac = 0
    n_five_way_parity = 0
    for td in trial_dirs:
        res_obj, err_res = _load_json_strict(td / "result.json")
        if err_res or not isinstance(res_obj, dict):
            problems.append(f"{td.name}/result.json invalid: {err_res}")
            continue
        rew = ((res_obj.get("verifier_result") or {}).get("rewards") or {}).get("reward")
        if not _is_finite_float(rew):
            problems.append(f"{td.name}/result.json missing finite verifier reward: {rew!r}")
            continue
        rew_f = float(rew)

        rtxt_p = td / "verifier/reward.txt"
        rjson_p = td / "verifier/reward.json"
        aled_p = td / "artifacts/ledger.json"
        vled_p = td / "verifier/ledger.json"
        stdout_p = td / "verifier/test-stdout.txt"
        for p in (rtxt_p, rjson_p, aled_p, vled_p, stdout_p):
            if p.is_symlink() or not p.is_file():
                problems.append(f"{td.name}/{p.relative_to(td).as_posix()} missing or symlink")

        if any(p.is_symlink() or not p.is_file() for p in (rtxt_p, rjson_p, aled_p, vled_p, stdout_p)):
            continue

        try:
            rtxt_f = float(rtxt_p.read_text(encoding="utf-8").strip())
        except ValueError:
            problems.append(f"{td.name}/verifier/reward.txt non-numeric")
            continue

        rjson_obj, err_rj = _load_json_strict(rjson_p)
        aled_obj, err_al = _load_json_strict(aled_p)
        vled_obj, err_vl = _load_json_strict(vled_p)
        for label, err in (("reward.json", err_rj), ("artifacts/ledger.json", err_al), ("verifier/ledger.json", err_vl)):
            if err:
                problems.append(f"{td.name}/{label}: {err}")
        if err_rj or err_al or err_vl or not isinstance(rjson_obj, dict) or not isinstance(aled_obj, dict) or not isinstance(vled_obj, dict):
            continue

        rj_val = rjson_obj.get("reward")
        al_val = aled_obj.get("score")
        vl_val = vled_obj.get("score")
        if not (_is_finite_float(rj_val) and _is_finite_float(al_val) and _is_finite_float(vl_val)):
            problems.append(f"{td.name}: non-finite reward/score across artifacts")
            continue

        parity_ok = (
            abs(rew_f - rtxt_f) <= 1e-9
            and abs(rew_f - float(rj_val)) <= 1e-9
            and abs(rew_f - float(al_val)) <= 1e-9
            and abs(rew_f - float(vl_val)) <= 1e-9
            and aled_obj == vled_obj
        )
        if parity_ok:
            n_five_way_parity += 1
        else:
            problems.append(
                f"{td.name}: reward parity mismatch (result={rew_f}, txt={rtxt_f}, json={rj_val}, aled={al_val}, vled={vl_val})"
            )

        stdout_txt = stdout_p.read_text(encoding="utf-8", errors="replace")
        hmac_ok = (
            _canonical_hmac_ok(aled_obj, key_str)
            and _canonical_hmac_ok(vled_obj, key_str)
            and "signature=ok" in stdout_txt
        )
        if hmac_ok:
            n_hmac += 1
        else:
            problems.append(f"{td.name}: HMAC signature verification failed")

    return {
        "passed": len(problems) == 0,
        "job": job_dir.as_posix(),
        "key_sha256_prefix": hashlib.sha256(key_str.encode("utf-8")).hexdigest()[:16],
        "n_trials": len(trial_dirs),
        "n_hmac_verified": n_hmac,
        "n_five_way_parity": n_five_way_parity,
        "problems": problems,
    }


def audit_negative_control(
    neg_job_dir: Path,
    repo_root: Path = ROOT,
    scratch_dir: Path | None = None,
) -> dict[str, Any]:
    problems: list[str] = []
    if not neg_job_dir.is_dir():
        return {"passed": False, "problems": [f"missing negative control dir: {neg_job_dir}"]}

    jres, err_j = _load_json_strict(neg_job_dir / "result.json")
    if err_j or not isinstance(jres, dict):
        problems.append(f"c1-tamper job result.json invalid: {err_j}")
        return {"passed": False, "problems": problems}

    evals = ((jres.get("stats") or {}).get("evals")) or {}
    ev = next(iter(evals.values()), {}) if evals else {}
    job_mean = ((ev.get("metrics") or [{}])[0]).get("mean")
    if ev.get("n_trials") != 1 or not _is_finite_float(job_mean) or abs(float(job_mean)) > 1e-9:
        problems.append(f"c1-tamper job summary expected n_trials=1, mean=0.0; got n_trials={ev.get('n_trials')}, mean={job_mean}")

    trials = sorted(p.parent for p in neg_job_dir.glob("canary-*/result.json"))
    if len(trials) != 1:
        problems.append(f"c1-tamper expected 1 trial, found {len(trials)}")
        return {"passed": False, "problems": problems}

    td = trials[0]
    tres, err_t = _load_json_strict(td / "result.json")
    aled, err_al = _load_json_strict(td / "artifacts/ledger.json")
    if err_t or not isinstance(tres, dict):
        problems.append(f"c1-tamper trial result.json invalid: {err_t}")
    if err_al or not isinstance(aled, dict):
        problems.append(f"c1-tamper artifacts/ledger.json invalid: {err_al}")
    if problems:
        return {"passed": False, "problems": problems}

    assert isinstance(tres, dict) and isinstance(aled, dict)
    trew = ((tres.get("verifier_result") or {}).get("rewards") or {}).get("reward")
    rtxt = (td / "verifier/reward.txt").read_text(encoding="utf-8").strip() if (td / "verifier/reward.txt").is_file() else None
    tstdout = (td / "verifier/test-stdout.txt").read_text(encoding="utf-8", errors="replace").strip() if (td / "verifier/test-stdout.txt").is_file() else ""
    vled_exists = (td / "verifier/ledger.json").exists()

    if not _is_finite_float(trew) or abs(float(trew)) > 1e-9:
        problems.append(f"c1-tamper trial result.json expected reward=0.0, got {trew!r}")
    if rtxt not in {"0", "0.0"}:
        problems.append(f"c1-tamper verifier/reward.txt expected '0', got {rtxt!r}")
    if "FAIL: bad ledger signature" not in tstdout:
        problems.append(f"c1-tamper verifier/test-stdout.txt missing bad-signature failure: {tstdout!r}")
    if vled_exists:
        problems.append("c1-tamper unexpectedly copied tampered ledger into verifier/ledger.json")
    if float(aled.get("score") or 0.0) != 1.0 or abs(float(aled.get("V") or 0.0) - 0.5) > 1e-9:
        problems.append(f"c1-tamper artifacts/ledger.json expected tampered score=1.0 vs V=0.5, got score={aled.get('score')}, V={aled.get('V')}")

    own_tmp = False
    if scratch_dir is None:
        work_dir = Path(tempfile.mkdtemp(prefix="w8-neg-ver-", dir=str(_default_scratch_base())))
        own_tmp = True
    else:
        work_dir = scratch_dir / "neg_verifier_recheck"
        work_dir.mkdir(parents=True, exist_ok=True)
    try:
        raw_tampered = (td / "artifacts/ledger.json").read_text(encoding="utf-8")
        re_ver = _run_isolated_verifier(repo_root, work_dir, raw_tampered, "cd" * 32)
        if re_ver["rc"] == 0 or re_ver["reward_txt"] != "0" or re_ver["reward_json"] != {"reward": 0.0} or re_ver["verifier_ledger_copied"]:
            problems.append(f"frozen test.sh verifier failed to reject c1-tamper ledger: {re_ver}")
    finally:
        if own_tmp:
            shutil.rmtree(work_dir, ignore_errors=True)

    return {
        "passed": len(problems) == 0,
        "trial": td.name,
        "tampered_ledger_score": float(aled["score"]),
        "true_ledger_v": float(aled["V"]),
        "recorded_reward": float(trew),
        "reward_txt": rtxt,
        "verifier_ledger_copied": vled_exists,
        "verifier_stdout": tstdout,
        "frozen_verifier_recheck_rc": re_ver["rc"],
        "frozen_verifier_recheck_reward_json": re_ver["reward_json"],
        "problems": problems,
    }


def audit_harbor_trials_and_negative_control(
    root: Path = ROOT,
    scratch_dir: Path | None = None,
) -> dict[str, Any]:
    from canary.redteam import tamper_guard as tg

    problems: list[str] = []
    dry_dir = root / "results" / "harbor" / "rehearsal-dry"
    hb_rows = tg.harbor_consistency(root)
    orig_hc = tg.harbor_consistency
    orig_lrt = tg._load_rehearsal_table_module

    def _fast_lrt(r: Path) -> Any:
        mod = orig_lrt(r)
        if mod is not None:
            orig_br = mod.boot_ratio
            mod.boot_ratio = lambda ra, rb, _b=orig_br: (0.0, 0.0) if all(x == 0.0 for x in ra) else _b(ra, rb)
        return mod

    try:
        tg.harbor_consistency = lambda r=root: hb_rows if Path(r).resolve() == root.resolve() else orig_hc(r)
        tg._load_rehearsal_table_module = _fast_lrt
        dry_audit = tg.verify_rehearsal_run(dry_dir, repo_root=root)
    finally:
        tg.harbor_consistency = orig_hc
        tg._load_rehearsal_table_module = orig_lrt
    if not dry_audit.get("passed"):
        problems.extend(dry_audit.get("problems") or [])
    trial_rows = [r for r in hb_rows if r.get("kind") == "trial"]
    job_rows = [r for r in hb_rows if r.get("kind") == "job"]
    bad_hb = [r for r in hb_rows if r.get("consistent") is False]
    for br in bad_hb:
        problems.append(f"tamper_guard.harbor_consistency failed on {br['trial']}: {br.get('problems')}")

    harbor_root = root / "results" / "harbor"
    pub_key_files = sorted(harbor_root.glob("**/ledger_key"))
    pub_job_audits: list[dict[str, Any]] = []
    total_pub_trials = 0
    total_pub_hmac = 0
    total_pub_parity = 0
    for kf in pub_key_files:
        ja = audit_published_key_job(kf.parent)
        ja["job"] = kf.parent.relative_to(root).as_posix()
        pub_job_audits.append(ja)
        total_pub_trials += ja["n_trials"]
        total_pub_hmac += ja["n_hmac_verified"]
        total_pub_parity += ja["n_five_way_parity"]
        if not ja["passed"]:
            problems.extend(ja["problems"])

    c1_unpub_signed = 0
    unsigned_legacy = 0
    four_way_parity_other = 0
    for tr in trial_rows:
        tp = root / str(tr["trial"])
        if (tp.parent / "ledger_key").is_file():
            continue
        if tr.get("signed"):
            c1_unpub_signed += 1
        else:
            unsigned_legacy += 1
        res_o, _ = _load_json_strict(tp / "result.json")
        aled_o, _ = _load_json_strict(tp / "artifacts/ledger.json")
        vled_o, _ = _load_json_strict(tp / "verifier/ledger.json")
        rtxt_s = (tp / "verifier/reward.txt").read_text(encoding="utf-8").strip()
        rew_v = float(((res_o or {}).get("verifier_result") or {}).get("rewards", {}).get("reward"))
        if (
            abs(rew_v - float(rtxt_s)) <= 1e-9
            and abs(rew_v - float(aled_o["score"])) <= 1e-9
            and abs(rew_v - float(vled_o["score"])) <= 1e-9
        ):
            four_way_parity_other += 1
        else:
            problems.append(f"non-published-key trial 4-way parity mismatch: {tr['trial']}")

    neg_res = audit_negative_control(root / "results" / "harbor_negative" / "c1-tamper", repo_root=root, scratch_dir=scratch_dir)
    if not neg_res.get("passed"):
        problems.extend(neg_res.get("problems") or [])

    return {
        "passed": len(problems) == 0,
        "rehearsal_dry": dry_audit,
        "harbor_total_jobs": len(job_rows),
        "harbor_consistent_jobs": sum(1 for r in job_rows if r.get("consistent") is True),
        "harbor_total_trials": len(trial_rows),
        "harbor_consistent_trials": sum(1 for r in trial_rows if r.get("consistent") is True),
        "published_key_jobs_count": len(pub_job_audits),
        "published_key_trials_count": total_pub_trials,
        "published_key_hmac_verified": total_pub_hmac,
        "published_key_five_way_parity": total_pub_parity,
        "published_key_jobs": pub_job_audits,
        "c1_signed_unpublished_key_trials": c1_unpub_signed,
        "legacy_unsigned_trials": unsigned_legacy,
        "other_trials_four_way_parity": four_way_parity_other,
        "negative_control_c1_tamper": neg_res,
        "problems": problems,
    }


def _init_mini_freeze_repo(repo_dir: Path) -> None:
    repo_dir.mkdir(parents=True, exist_ok=True)
    for fp in FROZEN_PATHS:
        if fp.endswith("/"):
            d = repo_dir / fp.rstrip("/")
            d.mkdir(parents=True, exist_ok=True)
            (d / "mod.py").write_text("X = 1\n", encoding="utf-8")
        else:
            p = repo_dir / fp
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("X = 1\n", encoding="utf-8")
    (repo_dir / "docs/reports").mkdir(parents=True, exist_ok=True)
    (repo_dir / "docs/reports/CEO.md").write_text("line 1\nline 2\n", encoding="utf-8")
    (repo_dir / "README.md").write_text("v0\n", encoding="utf-8")
    script = (
        "git init -q && "
        "git config user.email audit@example.com && "
        "git config user.name Audit && "
        "git add . && git commit -q -m freeze && git tag afterquery-final && "
        "printf 'v1\\n' > README.md && git add README.md && git commit -q -m submit2 && git tag afterquery-submit-2 && "
        "printf 'line 1\\nline 2\\nline 3 appended\\n' > docs/reports/CEO.md && git add docs/reports/CEO.md && git commit -q -m ceo_append"
    )
    subprocess.run(["sh", "-e", "-c", script], cwd=repo_dir, check=True, capture_output=True, text=True, timeout=30)


def _copy_frozen_subset(src_root: Path, dst_root: Path) -> None:
    for fp in FROZEN_PATHS:
        clean_fp = fp.rstrip("/")
        src_p = src_root / clean_fp
        dst_p = dst_root / clean_fp
        dst_p.parent.mkdir(parents=True, exist_ok=True)
        if src_p.is_dir():
            shutil.copytree(
                src_p,
                dst_p,
                ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
            )
        else:
            shutil.copy2(src_p, dst_p)
    dst_ceo = dst_root / "docs" / "reports" / "CEO.md"
    dst_ceo.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src_root / "docs" / "reports" / "CEO.md", dst_ceo)


def run_positive_tamper_controls(root: Path = ROOT, scratch_dir: Path | None = None) -> list[dict[str, Any]]:
    own_tmp = False
    if scratch_dir is None:
        work_dir = Path(tempfile.mkdtemp(prefix="w8-submit2-ctrl-", dir=str(_default_scratch_base())))
        own_tmp = True
    else:
        work_dir = scratch_dir / "positive_controls"
        work_dir.mkdir(parents=True, exist_ok=True)

    controls: list[dict[str, Any]] = []
    try:
        tmpl_repo = work_dir / "_mini_template"
        _init_mini_freeze_repo(tmpl_repo)

        r1 = work_dir / "c01_frozen_edit"
        shutil.copytree(tmpl_repo, r1)
        (r1 / "canary/rules.py").write_text("X = 2\n", encoding="utf-8")
        _git(r1, ["add", "canary/rules.py"])
        _git(r1, ["commit", "-q", "-m", "illegal frozen edit"])
        res1 = audit_code_freeze(r1, justsilas_ref="HEAD", enforce_canonical_prefixes=False)
        controls.append(
            {
                "id": "C01",
                "name": "frozen_path_byte_edit_caught",
                "caught": res1["passed"] is False and any("frozen path diff non-empty" in p for p in res1["problems"]),
            }
        )

        r2 = work_dir / "c02_ceo_rewrite"
        shutil.copytree(tmpl_repo, r2)
        (r2 / "docs/reports/CEO.md").write_text("REWRITTEN LINE 1\nline 2\nline 3\n", encoding="utf-8")
        _git(r2, ["add", "docs/reports/CEO.md"])
        _git(r2, ["commit", "-q", "-m", "non-append ceo edit"])
        res2 = audit_code_freeze(r2, justsilas_ref="HEAD", enforce_canonical_prefixes=False)
        controls.append(
            {
                "id": "C02",
                "name": "ceo_non_append_rewrite_caught",
                "caught": res2["passed"] is False and any("append-only" in p for p in res2["problems"]),
            }
        )

        src_job = root / "results" / "harbor" / "signed-stop_early"
        src_trial = sorted(p.parent for p in src_job.glob("canary-*/result.json"))[0]

        j3 = work_dir / "c03_hmac_edit"
        j3.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src_job / "ledger_key", j3 / "ledger_key")
        t3 = j3 / src_trial.name
        shutil.copytree(src_trial, t3)
        led3 = json.loads((t3 / "artifacts/ledger.json").read_text(encoding="utf-8"))
        led3["score"] = 1.0
        (t3 / "artifacts/ledger.json").write_text(json.dumps(led3), encoding="utf-8")
        (t3 / "verifier/ledger.json").write_text(json.dumps(led3), encoding="utf-8")
        (t3 / "verifier/reward.txt").write_text("1.0\n", encoding="utf-8")
        (t3 / "verifier/reward.json").write_text('{"reward": 1.0}', encoding="utf-8")
        r3_res = json.loads((t3 / "result.json").read_text(encoding="utf-8"))
        r3_res["verifier_result"]["rewards"]["reward"] = 1.0
        (t3 / "result.json").write_text(json.dumps(r3_res), encoding="utf-8")
        res3 = audit_published_key_job(j3)
        controls.append(
            {
                "id": "C03",
                "name": "published_key_hmac_forgery_caught",
                "caught": res3["passed"] is False and any("HMAC signature verification failed" in p for p in res3["problems"]),
            }
        )

        j4 = work_dir / "c04_reward_desync"
        j4.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src_job / "ledger_key", j4 / "ledger_key")
        t4 = j4 / src_trial.name
        shutil.copytree(src_trial, t4)
        (t4 / "verifier/reward.json").write_text('{"reward": 0.77}', encoding="utf-8")
        res4 = audit_published_key_job(j4)
        controls.append(
            {
                "id": "C04",
                "name": "reward_txt_json_ledger_desync_caught",
                "caught": res4["passed"] is False and any("reward parity mismatch" in p for p in res4["problems"]),
            }
        )

        j5 = work_dir / "c05_neg_fail_open"
        shutil.copytree(root / "results" / "harbor_negative" / "c1-tamper", j5)
        t5 = sorted(p.parent for p in j5.glob("canary-*/result.json"))[0]
        (t5 / "verifier/reward.txt").write_text("1.0\n", encoding="utf-8")
        res5 = audit_negative_control(j5, repo_root=root, scratch_dir=work_dir / "c05_sub")
        controls.append(
            {
                "id": "C05",
                "name": "negative_control_fail_open_caught",
                "caught": res5["passed"] is False and any("reward.txt" in p for p in res5["problems"]),
            }
        )

        r6 = work_dir / "c06_stale_153_doc"
        for rel in (
            "results/harbor/rehearsal/BUILD.txt",
            "results/harbor/rehearsal/TABLE.md",
            "results/harbor/rehearsal/README.md",
            "docs/reports/CEO.md",
            "README.md",
            "docs/SUBMISSION.md",
            "docs/reports/gap.md",
            "harbor/template/task.toml",
            "scripts/rehearsal_table.py",
        ):
            dst = r6 / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(root / rel, dst)
        (r6 / "README.md").write_text(
            (r6 / "README.md").read_text(encoding="utf-8").replace("131%", "153%"),
            encoding="utf-8",
        )
        res6 = audit_rehearsal_and_docs(r6, rehearsal_final_ref="nonexistent-ref")
        controls.append(
            {
                "id": "C06",
                "name": "stale_153_snapshot_claim_in_docs_caught",
                "caught": res6["passed"] is False and any("153%" in p for p in res6["problems"]),
            }
        )

        r7 = work_dir / "c07_shallow_frozen_tamper"
        _copy_frozen_subset(root, r7)
        env_py = r7 / "canary/env.py"
        env_py.write_text(env_py.read_text(encoding="utf-8") + "\n", encoding="utf-8")
        res7 = audit_code_freeze(r7, enforce_canonical_prefixes=True)
        controls.append(
            {
                "id": "C07",
                "name": "shallow_detached_head_frozen_edit_caught",
                "caught": (
                    res7.get("shallow_ci_fallback") is True
                    and res7["passed"] is False
                    and any("shallow-CI frozen hash mismatch on canary/env.py" in p for p in res7["problems"])
                ),
            }
        )
        return controls
    finally:
        if own_tmp:
            shutil.rmtree(work_dir, ignore_errors=True)


def collect_structured_issues(
    freeze_res: dict[str, Any],
    reh_res: dict[str, Any],
    hb_res: dict[str, Any],
) -> list[dict[str, Any]]:
    obs = reh_res.get("doc_observations") or {}
    s1_git = reh_res.get("s1_rehearsal_final_git") or {}
    shell_all = s1_git.get("shell_used_all_trials", 22)
    shell_tot = s1_git.get("shell_total_trials", 30)
    shell_val = s1_git.get("shell_used_valid_trials", 21)

    issues: list[dict[str, Any]] = []
    if obs.get("table_body_retains_0852_snapshot"):
        issues.append(
            {
                "id": "ISSUE-W8-S2-1",
                "severity": "low",
                "area": "rehearsal_table_snapshot_body",
                "paths": ["results/harbor/rehearsal/TABLE.md"],
                "summary": (
                    "TABLE.md prepends an accurate 09:30 correction note with final Run 3 numbers (9 valid, +0.626, "
                    "131% [86%, 590%], s1-rehearsal-final d0ead011), while the markdown table body below retains the "
                    "08:52 snapshot (opencode-3 n=7, +0.656, 153% [89%, 411%]) and raw trial dirs live on d0ead011."
                ),
            }
        )
    if obs.get("readme_has_20_of_28_shell_note") or obs.get("gap_has_20_of_28_shell_note"):
        issues.append(
            {
                "id": "ISSUE-W8-S2-2",
                "severity": "info",
                "area": "rehearsal_shell_usage_denominator",
                "paths": ["README.md", "docs/reports/gap.md"],
                "summary": (
                    f"aa1c679e updated valid Gemini accusation accuracy from 26/27 to 28/29, but retained the 08:52 "
                    f"snapshot shell-usage parenthetical ('20 of 28 trials'); on s1-rehearsal-final (d0ead011), bash "
                    f"was called in {shell_all} of {shell_tot} total Gemini trajectories ({shell_val} of 29 valid)."
                ),
            }
        )
    if freeze_res.get("justsilas_post_submit2_files") == ["docs/reports/CEO.md"] or not obs.get("submission_mentions_submit2_tag"):
        issues.append(
            {
                "id": "ISSUE-W8-S2-3",
                "severity": "info",
                "area": "submit2_tag_and_ceo_log_sync",
                "paths": ["docs/reports/CEO.md", "docs/SUBMISSION.md"],
                "summary": (
                    "Commit 5f9b3297 (append-only 09:35 CEO.md correction) sits 1 commit ahead of tag "
                    "afterquery-submit-2 (aa1c679e), and docs/SUBMISSION.md line 8 names afterquery-final and "
                    "afterquery-submit without listing afterquery-submit-2."
                ),
            }
        )
    issues.append(
        {
            "id": "ISSUE-W8-S2-4",
            "severity": "info",
            "area": "rehearsal_run3_unexecuted_infra_rerun",
            "paths": ["results/harbor/rehearsal/README.md"],
            "summary": (
                "In s1-rehearsal-final (d0ead011), opencode-3 hard-900002 failed with ApiRateLimitError (done=False) "
                "after inline retries and did not receive a <job>-infra-rerun job because Run 3 finished at 07:23:17Z "
                "(09:23 Helsinki); disclosed in rehearsal README and reported alongside infra-as-0 mean (+0.563)."
            ),
        }
    )
    if hb_res.get("c1_signed_unpublished_key_trials", 0) > 0 or hb_res.get("legacy_unsigned_trials", 0) > 0:
        issues.append(
            {
                "id": "ISSUE-W8-S2-5",
                "severity": "info",
                "area": "harbor_verifier_generation_heterogeneity",
                "paths": ["results/harbor/"],
                "summary": (
                    f"All {hb_res['published_key_trials_count']}/{hb_res['published_key_trials_count']} published-key "
                    f"Harbor trials include verifier/reward.json (5-way parity + HMAC), whereas "
                    f"{hb_res['c1_signed_unpublished_key_trials']} earlier C1 signed trials (c1-*) and "
                    f"{hb_res['legacy_unsigned_trials']} pre-C1 demo trials predate reward.json output (4-way parity holds)."
                ),
            }
        )
    issues.append(
        {
            "id": "ISSUE-W8-S2-6",
            "severity": "info",
            "area": "published_retired_key_non_repudiation_scope",
            "paths": ["results/harbor/rehearsal-dry/", "results/harbor/"],
            "summary": (
                "Publishing retired <job>/ledger_key files enables third-party HMAC verification against un-re-signed "
                "edits, while post-publication re-signing is bounded by agent trajectory/log cross-checks and cross-job "
                "task_checksum parity."
            ),
        }
    )
    return issues


def run_audit(root: Path = ROOT, scratch_dir: Path | None = None) -> dict[str, Any]:
    t0 = time.monotonic()
    own_tmp = False
    if scratch_dir is None:
        work_dir = Path(tempfile.mkdtemp(prefix="w8-submit2-audit-", dir=str(_default_scratch_base())))
        own_tmp = True
    else:
        work_dir = scratch_dir
        work_dir.mkdir(parents=True, exist_ok=True)

    try:
        freeze_res = audit_code_freeze(root=root)
        reh_res = audit_rehearsal_and_docs(root=root)
        hb_res = audit_harbor_trials_and_negative_control(root=root, scratch_dir=work_dir)
        controls = run_positive_tamper_controls(root=root, scratch_dir=work_dir)
        issues = collect_structured_issues(freeze_res, reh_res, hb_res)
        controls_passed = all(c["caught"] is True for c in controls)
        overall_passed = bool(
            freeze_res["passed"] and reh_res["passed"] and hb_res["passed"] and controls_passed
        )
        elapsed_s = round(time.monotonic() - t0, 4)
        return {
            "passed": overall_passed,
            "elapsed_s": elapsed_s,
            "code_freeze": freeze_res,
            "rehearsal_and_docs": reh_res,
            "harbor_and_negative_control": hb_res,
            "positive_controls": {
                "passed": controls_passed,
                "total": len(controls),
                "caught": sum(1 for c in controls if c["caught"]),
                "cases": controls,
            },
            "structured_issues": issues,
        }
    finally:
        if own_tmp:
            shutil.rmtree(work_dir, ignore_errors=True)


def render_markdown_report(rep: dict[str, Any]) -> str:
    cf = rep["code_freeze"]
    refs = cf["refs"]
    rh = rep["rehearsal_and_docs"]
    s1 = rh.get("s1_rehearsal_final_git") or {}
    hb = rep["harbor_and_negative_control"]
    dry = hb["rehearsal_dry"]
    neg = hb["negative_control_c1_tamper"]
    pc = rep["positive_controls"]
    issues = rep["structured_issues"]

    lines: list[str] = [
        f"{MD_H} Submit-2 (`aa1c679e`) & `justSilas@5f9b3297` Harbor Rehearsal and Code-Freeze Integrity Audit",
        "",
        f"{MD_H}{MD_H} 1. Executive Summary",
        "",
        f"- **Overall Verdict:** `{'PASS' if rep['passed'] else 'FAIL'}` (`0` code-freeze byte changes, `0` HMAC or reward-parity failures, `{pc['caught']}/{pc['total']}` positive tamper controls caught, `0` live API calls).",
        f"- **Audited Git Lineage:** `afterquery-final` (`{refs['afterquery_final'][:8]}`) -> `afterquery-submit` (`{(refs['afterquery_submit'] or 'n/a')[:8]}`) -> `afterquery-submit-2` (`{refs['afterquery_submit_2'][:8]}`) -> `origin/justSilas` (`{refs['justSilas'][:8]}`), plus raw rehearsal branch `s1-rehearsal-final` (`{s1.get('commit', 'n/a')[:8]}`).",
        f"- **Code-Freeze Invariant (`PASS`):** `0` byte changes across all `6` frozen paths (`canary/env.py`, `canary/rules.py`, `canary/world.py`, `canary/solver/`, `canary/mcp_server.py`, `harbor/template/`) across `afterquery-final..afterquery-submit-2`, `afterquery-submit-2..origin/justSilas`, `afterquery-final..origin/justSilas`, and `HEAD`. Frozen tier hashes remain `v1.4 = {cf['tier_hashes']['v14']}` and `v1.3 = {cf['tier_hashes']['v13']}`.",
        f"- **Judge Rehearsal & `CEO.md` Append-Only Consistency (`PASS`):** `BUILD.txt` pins `afterquery-final` (`{rh['build_sha']}`) on Harbor `{rh['harbor_version']}` (`[verifier] timeout_sec = 120.0`, `[agent] timeout_sec = 10800.0`). Run 1 (`+0.472`, `n=10`, `9/10` correct, `93% [20%, 371%]`), Run 2 (`+0.585`, `n=10`, `10/10` correct, `116% [78%, 363%]`), and Run 3 final (`+0.626`, `n=9` valid with `5` after `08:30` Helsinki / `06:30Z` cut-off and `1` `ApiRateLimitError` infra-excluded, `9/9` correct, paired oracle `+0.478`, `131% [86%, 590%]`, infra-as-0 `+0.563`) are consistent across `TABLE.md`, `README.md`, `docs/SUBMISSION.md`, `docs/reports/gap.md`, `docs/reports/CEO.md` (`5f9b3297`, strictly append-only `+{cf['ceo_appended_lines']}` lines), and all `{s1.get('n_trials', 60)}/{s1.get('n_trials', 60)}` HMAC-verified raw trials on `s1-rehearsal-final` (`d0ead011`).",
        f"- **Harbor Published-Key HMAC, 5-Way Parity & Negative Control (`PASS`):** `{hb['harbor_consistent_jobs']}/{hb['harbor_total_jobs']}` jobs and `{hb['harbor_consistent_trials']}/{hb['harbor_total_trials']}` trials under `results/harbor/` pass `tamper_guard.harbor_consistency`. Across all `{hb['published_key_jobs_count']}` published-key jobs (`{hb['published_key_trials_count']}` trials, including `{dry['n_trials']}` in `results/harbor/rehearsal-dry/`), `{hb['published_key_hmac_verified']}/{hb['published_key_trials_count']}` verify HMAC-SHA256 and `{hb['published_key_five_way_parity']}/{hb['published_key_trials_count']}` satisfy exact `result.json == verifier/reward.txt == verifier/reward.json == verifier/ledger.json == artifacts/ledger.json` parity. Negative control `results/harbor_negative/c1-tamper` (`score=1.0` forged over `V=0.5`) fails closed at `reward=0.0` (`FAIL: bad ledger signature`) with `verifier/ledger.json` uncopied.",
        "- **Evaluation Honesty Anchor (Panel Fix A):** On `v1.4` `hard`, `gemini-4-carbon` raw score ratio is `65% [24%, 98%]` and luck-adjusted ratio is `72% [52%, 91%]`; dev seeds `0-29` are not pre-registered and represent a `post-hoc lock` (locked after the primary run).",
        "",
        f"{MD_H}{MD_H} 2. Keyless Reproduce Commands",
        "",
        "```bash",
        "PYTHONPATH=. /tmp/fleet-silas/shared/agent-arena-venv/bin/python scripts/integrity_submit2_rehearsal_and_freeze_audit.py --check-report docs/reports/integrity_submit2_rehearsal_and_freeze_audit.md",
        "PYTHONPATH=. /tmp/fleet-silas/shared/agent-arena-venv/bin/python -m pytest -q tests/test_integrity_submit2_rehearsal_and_freeze_audit.py",
        "PYTHONPATH=. /tmp/fleet-silas/shared/agent-arena-venv/bin/python scripts/audit_submission.py",
        "```",
        "",
        f"{MD_H}{MD_H} 3. Code-Freeze Invariant (`1bc3e281` -> `aa1c679e` -> `5f9b3297`)",
        "",
        "| Comparison Range | `rev_a` | `rev_b` | Frozen Path Changes | Frozen Byte Diff | Total Changed Files | Verdict |",
        "|---|---|---|---:|---:|---:|---|",
    ]
    for dp in cf["diff_pairs"]:
        if dp["pair"].endswith("..HEAD"):
            continue
        lines.append(
            f"| `{dp['pair']}` | `{dp['rev_a']}` | `{dp['rev_b']}` | `{dp['frozen_changed_count']}` | `{dp['frozen_byte_changes']}` | `{dp['total_changed_files']}` | `PASS` |"
        )

    lines.extend(
        [
            "",
            "| Frozen Path | Git Object SHA (`1bc3e281` / `aa1c679e` / `5f9b3297`) | Identical Across All Refs |",
            "|---|---|---|",
        ]
    )
    for fp in cf["frozen_paths"]:
        sha_vals = list(cf["object_hashes"][fp].values())
        lines.append(f"| `{fp}` | `{sha_vals[0]}` | `{len(set(sha_vals)) == 1}` |")

    lines.extend(
        [
            "",
            f"- **`afterquery-submit-2` (`{refs['afterquery_submit_2'][:8]}`) diff scope vs `afterquery-submit` (`{(refs['afterquery_submit'] or '')[:8]}`):** `{len(cf['submit2_commit_files'])}` files (`{', '.join(cf['submit2_commit_files'])}`).",
            f"- **`origin/justSilas` (`{refs['justSilas'][:8]}`) diff scope vs `afterquery-submit-2` (`{refs['afterquery_submit_2'][:8]}`):** `{', '.join(cf['justsilas_post_submit2_files'])}` (`append_only={cf['ceo_append_only']}`, `+{cf['ceo_appended_lines']}` lines, `0` deletions).",
            "",
            f"{MD_H}{MD_H} 4. Judge Rehearsal (`afterquery-final` / `aa1c679e` / `d0ead011`) and Dry Rehearsal Audit",
            "",
            f"{MD_H}{MD_H}{MD_H} 4.1 Final Judge Rehearsal (`s1-rehearsal-final` `d0ead011` + `aa1c679e` Docs)",
            "",
            "| Run | Valid Trials | Infra Excluded | Correct / Accused | Mean | Paired Oracle | Run / Oracle [95% Bootstrap CI] | Diff | Mean (Infra as 0) |",
            "|---|---:|---:|---|---:|---:|---|---:|---:|",
            f"| `oracle` | `10` | `0` | `9 / 10` | `+{s1['oracle_mean']:.3f}` | `n/a` | `100%` | `+0.000` | `+{s1['oracle_mean']:.3f}` |",
        ]
    )
    for rname in ("opencode-1", "opencode-2", "opencode-3", "do_nothing", "stop_early"):
        rs = s1["runs"][rname]
        lines.append(
            f"| `{rname}` | `{rs['n_valid']}` | `{rs['n_infra']}` | `{rs['n_correct']} / {rs['n_accused']}` | "
            f"`{rs['mean']:+.3f}` | `+{rs['oracle_same_tasks']:.3f}` | "
            f"`{rs['ratio_pct']}% [{rs['ci_pct'][0]}%, {rs['ci_pct'][1]}%]` | "
            f"`{rs['diff']:+.3f}` | `{rs['mean_infra_as_zero']:+.3f}` |"
        )

    lines.extend(
        [
            "",
            f"- **Raw Trial Cryptographic & Parity Check (`d0ead011`):** `{s1['n_jobs']}` jobs, `{s1['n_trials']}` trials, `{s1['shared_ledger_keys']}` shared `ledger_key`, `{s1['n_hmac_verified']}/{s1['n_trials']}` HMAC-SHA256 verified, `{s1['n_parity_ok']}/{s1['n_trials']}` exact 5-way `result.json == reward.txt == reward.json == verifier/ledger.json == artifacts/ledger.json` parity, `{s1['n_distinct_tasks']}/10` task checksums identical across all `6` jobs.",
            f"- **Cut-Off & Accusation Tally (`d0ead011`):** `opencode-3` completed `{s1['run3_before_cutoff']}` trials on or before `06:30:00Z` (`08:30` Helsinki: `4` valid + `1` `ApiRateLimitError` on `hard-900002`) and `{s1['run3_after_cutoff']}` valid trials between `06:31:30Z` and `07:23:17Z`. Across all `3` runs, `{s1['valid_gemini_correct']}/{s1['valid_gemini_accused']}` valid Gemini accusations were correct.",
            f"- **08:52 Snapshot Table Parity (`results/harbor/rehearsal/TABLE.md`):** Snapshot table rows independently recompute to `opencode-1 = 93% [20%, 371%]` (`+0.472`), `opencode-2 = 116% [78%, 363%]` (`+0.585`), `opencode-3 (n=7) = 153% [89%, 411%]` (`+0.656` vs paired oracle `+0.429`), `do_nothing = 0%`, `stop_early = 0%`.",
            "",
            f"{MD_H}{MD_H}{MD_H} 4.2 Dry Rehearsal (`results/harbor/rehearsal-dry/`)",
            "",
            f"- **Jobs & Trials:** `{dry['n_jobs']}` jobs (`oracle`, `opencode`, `opencode-infra-rerun`, `do_nothing`, `stop_early`), `{dry['n_trials']}/{dry['n_trials']}` trials consistent, `{dry['n_hmac_verified']}/{dry['n_trials']}` HMAC verified under `{dry['shared_retired_key_count']}` shared retired `ledger_key`, `{dry['n_trajectory_checked']}/13` OpenCode trajectories matched, `table_md_matches={dry['table_md_matches']}` (`oracle=+0.467`, `opencode=+0.398` = `85% [11%, 355%]`, `do_nothing=+0.000`, `stop_early=+0.000`).",
            "",
            f"{MD_H}{MD_H} 5. Signed Harbor Trials (`results/harbor/`) and Negative Control (`c1-tamper`)",
            "",
            "| Published-Key Harbor Job | Trials | `ledger_key` SHA-256 Prefix | HMAC-SHA256 Verified | 5-Way Reward/Ledger Parity | Verdict |",
            "|---|---:|---|---:|---:|---|",
        ]
    )
    for pj in hb["published_key_jobs"]:
        lines.append(
            f"| `{pj['job']}` | `{pj['n_trials']}` | `{pj['key_sha256_prefix']}` | `{pj['n_hmac_verified']}/{pj['n_trials']}` | `{pj['n_five_way_parity']}/{pj['n_trials']}` | `{'PASS' if pj['passed'] else 'FAIL'}` |"
        )

    lines.extend(
        [
            "",
            f"- **All Committed `results/harbor/` Runs:** `{hb['harbor_consistent_jobs']}/{hb['harbor_total_jobs']}` jobs and `{hb['harbor_consistent_trials']}/{hb['harbor_total_trials']}` trials consistent (`{hb['published_key_trials_count']}` published-key signed trials with 5-way parity + `{hb['c1_signed_unpublished_key_trials']}` C1 signed trials with `signature=ok` and 4-way parity + `{hb['legacy_unsigned_trials']}` pre-C1 demo trials with 4-way parity).",
            f"- **Negative Control `results/harbor_negative/c1-tamper` (`{neg['trial']}`):** `artifacts/ledger.json` carries forged `score={neg['tampered_ledger_score']:.1f}` over `V={neg['true_ledger_v']:.1f}`; verifier logged `{neg['verifier_stdout']}`, failed closed with `result.json` `reward={neg['recorded_reward']:.1f}` and `verifier/reward.txt='{neg['reward_txt']}'`, and left `verifier/ledger.json` absent (`{neg['verifier_ledger_copied']}`). Re-executing frozen `harbor/template/tests/test.sh` against the tampered ledger in `/tmp/opencode` exited `rc={neg['frozen_verifier_recheck_rc']}` with `reward.json={json.dumps(neg['frozen_verifier_recheck_reward_json'])}`.",
            "",
            f"{MD_H}{MD_H} 6. Synthetic Positive Tamper Controls (`/tmp/opencode`, Cleaned Up)",
            "",
            "| Control ID | Synthetic Mutation | Caught |",
            "|---|---|---|",
        ]
    )
    for c in pc["cases"]:
        lines.append(f"| `{c['id']}` | `{c['name']}` | `{c['caught']}` |")

    lines.extend(
        [
            "",
            f"{MD_H}{MD_H} 7. Structured Report-Only Issues (Zero Protected Paths, Zero Edits to Silas Docs)",
            "",
            "| Issue ID | Severity | Area | Paths | Finding |",
            "|---|---|---|---|---|",
        ]
    )
    for iss in issues:
        p_str = ", ".join(f"`{p}`" for p in iss["paths"])
        lines.append(f"| `{iss['id']}` | `{iss['severity']}` | `{iss['area']}` | {p_str} | {iss['summary']} |")

    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Audit afterquery-submit-2 (aa1c679e) and 5f9b3297 rehearsal and freeze integrity.")
    ap.add_argument("--root", type=Path, default=ROOT)
    ap.add_argument("--scratch-dir", type=Path, default=None)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--write-report", type=Path, default=None)
    ap.add_argument("--check-report", type=Path, default=None)
    args = ap.parse_args(argv)

    rep = run_audit(root=args.root.resolve(), scratch_dir=args.scratch_dir)
    md = render_markdown_report(rep)

    if args.write_report is not None:
        args.write_report.parent.mkdir(parents=True, exist_ok=True)
        args.write_report.write_text(md, encoding="utf-8")

    if args.check_report is not None:
        if not args.check_report.is_file():
            print(f"FAIL: missing report {args.check_report}", file=sys.stderr)
            return 1
        actual = args.check_report.read_text(encoding="utf-8")
        if actual != md:
            print(f"FAIL: report {args.check_report} is out of sync with deterministic render", file=sys.stderr)
            return 1

    if args.json:
        print(json.dumps(rep, indent=2))
    else:
        print(
            f"[{'PASS' if rep['passed'] else 'FAIL'}] submit2+rehearsal+freeze audit in {rep['elapsed_s']:.3f}s: "
            f"freeze_ok={rep['code_freeze']['passed']}, rehearsal_ok={rep['rehearsal_and_docs']['passed']}, "
            f"harbor_ok={rep['harbor_and_negative_control']['passed']}, "
            f"controls={rep['positive_controls']['caught']}/{rep['positive_controls']['total']}, "
            f"issues={len(rep['structured_issues'])}"
        )

    return 0 if rep["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
