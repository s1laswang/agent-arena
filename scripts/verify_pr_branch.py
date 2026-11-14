"""Fast, keyless CLI gate to verify candidate PR branches before merging into justSilas."""
from __future__ import annotations

import argparse
import io
import json
import os
import re
import subprocess
import sys
import tokenize
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

HASH_CHAR = chr(35)
SHEBANG_PREFIX = HASH_CHAR + "!/usr/bin/env"
EM_DASH = chr(0x2014)
EN_DASH = chr(0x2013)

PROTECTED_CORE_EXACT = frozenset({
    "canary/env.py",
    "canary/rules.py",
    "canary/reproduce.py",
    "canary/solver",
    "harbor",
})
PROTECTED_CORE_PREFIXES = (
    "canary/solver/",
    "harbor/",
)

FINALIZE_LANES = frozenset({
    "inproc-gemini-4-carbon",
    "opencode-gemini-4-carbon",
    "opencode-gemini-3.5-flash",
})
FINALIZE_RESERVED_ROOT_FILES = frozenset({"tags.json", "accuse.md"})
FINALIZE_RESERVED_DIRS = frozenset({"medium", "hard"})

BINARY_SUFFIXES = frozenset({
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".pdf",
    ".woff", ".woff2", ".ttf", ".otf", ".eot", ".zip", ".gz",
    ".tar", ".bz2", ".xz", ".safetensors", ".pt", ".pth",
    ".bin", ".npy", ".npz", ".pyc", ".so", ".dylib", ".db", ".sqlite",
})

CO_AUTHORED_RE = re.compile(r"^\s*co-authored-by\s*:", re.IGNORECASE | re.MULTILINE)
SECRET_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("google_api_key", re.compile(r"(?<![A-Za-z0-9+/_-])AIza[0-9A-Za-z_-]{35}(?![0-9A-Za-z_-])")),
    ("openai_secret_key", re.compile(r"(?<![A-Za-z0-9+/_-])sk-(?:proj-)?[A-Za-z0-9_-]{20,}")),
    ("github_pat", re.compile(r"(?<![A-Za-z0-9+/_-])ghp_[A-Za-z0-9]{30,}")),
)
ENV_TEMPLATE_NAMES = frozenset({".env.example", ".env.sample", ".env.template"})


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        ["git", "-c", "core.quotepath=false", *args],
        cwd=str(repo),
        capture_output=True,
        check=False,
    )


def _rev_parse(repo: Path, ref: str) -> str | None:
    res = _git(repo, "rev-parse", "--verify", f"{ref}^{{commit}}")
    if res.returncode != 0:
        return None
    return res.stdout.decode("utf-8", errors="replace").strip()


def _read_blob(repo: Path, tree_ref: str, path: str) -> bytes | None:
    res = _git(repo, "show", f"{tree_ref}:{path}")
    if res.returncode != 0:
        return None
    return res.stdout


def _ls_tree(repo: Path, tree_ref: str, path: str, recursive: bool = False) -> list[str] | None:
    extra = ["-r"] if recursive else []
    res = _git(repo, "ls-tree", *extra, "--name-only", f"{tree_ref}:{path}")
    if res.returncode != 0:
        return None
    text = res.stdout.decode("utf-8", errors="replace")
    return [line for line in text.splitlines() if line.strip()]


def _diff_entries(repo: Path, ref_a: str, ref_b: str) -> list[tuple[str, str]]:
    res = _git(repo, "diff", "--name-status", "--no-renames", ref_a, ref_b)
    if res.returncode != 0:
        return []
    out: list[tuple[str, str]] = []
    for raw_line in res.stdout.decode("utf-8", errors="replace").splitlines():
        if not raw_line.strip() or "\t" not in raw_line:
            continue
        status, path = raw_line.split("\t", 1)
        out.append((status.strip(), path.strip()))
    return out


def _is_protected_core(path: str) -> bool:
    if path in PROTECTED_CORE_EXACT:
        return True
    return path.startswith(PROTECTED_CORE_PREFIXES)


def _is_finalize_reserved(path: str) -> bool:
    prefix = "data/runs/committed/v1.4/"
    if not path.startswith(prefix):
        return False
    rem = path[len(prefix):]
    if "/" not in rem:
        return False
    lane, rest = rem.split("/", 1)
    if lane not in FINALIZE_LANES:
        return False
    if rest in FINALIZE_RESERVED_ROOT_FILES:
        return True
    top = rest.split("/", 1)[0]
    return top in FINALIZE_RESERVED_DIRS


def _is_secret_path(path: str) -> bool:
    parts = path.split("/")
    name = parts[-1]
    if name == ".env":
        return True
    if name.startswith(".env.") and name not in ENV_TEMPLATE_NAMES:
        return True
    if path == "data/worlds/judge/SALT" or path.endswith("/data/worlds/judge/SALT"):
        return True
    if name == "SALT" and "judge" in parts[:-1]:
        return True
    return False


def _should_scan_dashes(path: str, raw: bytes) -> bool:
    if b"\x00" in raw:
        return False
    lower = path.lower()
    if any(lower.endswith(ext) for ext in BINARY_SUFFIXES):
        return False
    if path.startswith("data/runs/") and ("/transcripts/" in path or path.endswith(".jsonl")):
        return False
    return True


def _gate(name: str, passed: bool, summary: str, errors: list[str] | None = None) -> dict[str, Any]:
    return {
        "name": name,
        "passed": passed,
        "summary": summary,
        "errors": list(errors or []),
    }


def verify_branch(
    base: str = "origin/justSilas",
    branch: str = "HEAD",
    repo: Path | str = ".",
    allow_core: bool = False,
    skip_replay: bool = False,
    require_ff_base: bool = False,
) -> dict[str, Any]:
    repo_path = Path(repo).resolve()
    warnings: list[str] = []
    merge_errors: list[str] = []

    base_sha = _rev_parse(repo_path, base)
    branch_sha = _rev_parse(repo_path, branch)
    merge_base: str | None = None
    ff_base = False
    merged_tree: str | None = None

    if base_sha is None:
        merge_errors.append(f"unknown base ref: {base}")
    if branch_sha is None:
        merge_errors.append(f"unknown branch ref: {branch}")

    if base_sha is not None and branch_sha is not None:
        mb_res = _git(repo_path, "merge-base", base_sha, branch_sha)
        if mb_res.returncode != 0:
            merge_errors.append(f"no common merge-base between {base} and {branch}")
        else:
            merge_base = mb_res.stdout.decode("utf-8", errors="replace").strip()
            ff_base = merge_base == base_sha
            if not ff_base:
                msg = (
                    f"base tip {base} ({base_sha[:8]}) is not merged into "
                    f"{branch} (merge-base {merge_base[:8]})"
                )
                if require_ff_base:
                    merge_errors.append(msg)
                else:
                    warnings.append(msg)

        mt_res = _git(repo_path, "merge-tree", "--write-tree", base_sha, branch_sha)
        mt_out = mt_res.stdout.decode("utf-8", errors="replace").splitlines()
        mt_err = mt_res.stderr.decode("utf-8", errors="replace").strip()
        if mt_res.returncode != 0:
            details = [ln.strip() for ln in mt_out[1:] if ln.strip()]
            if mt_err:
                details.append(mt_err)
            detail_str = "; ".join(details[:5]) if details else "conflicting changes"
            merge_errors.append(f"merge conflict between {base} and {branch}: {detail_str}")
        elif mt_out:
            merged_tree = mt_out[0].strip()

    if merged_tree is not None and base_sha is not None:
        diff_from = base_sha
        inspect_tree = merged_tree
    elif merge_base is not None and branch_sha is not None:
        diff_from = merge_base
        inspect_tree = branch_sha
    elif base_sha is not None and branch_sha is not None:
        diff_from = base_sha
        inspect_tree = branch_sha
    else:
        diff_from = ""
        inspect_tree = ""

    entries = _diff_entries(repo_path, diff_from, inspect_tree) if diff_from and inspect_tree else []
    changed_paths = [p for _, p in entries]
    added_or_modified = [p for st, p in entries if st[:1] in {"A", "M", "T"}]

    gates: list[dict[str, Any]] = []

    if merge_errors:
        gates.append(_gate("merge_conflict", False, f"{len(merge_errors)} merge/ancestry issue(s)", merge_errors))
    else:
        ff_note = f"ff-base {base_sha[:8]}" if (ff_base and base_sha) else f"merge-base {(merge_base or '')[:8]}"
        gates.append(_gate("merge_conflict", True, f"clean merge-tree ({ff_note})"))

    if allow_core:
        gates.append(_gate("protected_core", True, "skipped (--allow-core)"))
        gates.append(_gate("finalize_reserved_path", True, "skipped (--allow-core)"))
    else:
        core_hits = [f"protected core path modified: {p}" for p in changed_paths if _is_protected_core(p)]
        gates.append(
            _gate(
                "protected_core",
                not core_hits,
                f"{len(core_hits)} protected core violation(s)" if core_hits else "0 protected core files touched",
                core_hits,
            )
        )
        fin_hits = [f"reserved finalize path modified: {p}" for p in changed_paths if _is_finalize_reserved(p)]
        gates.append(
            _gate(
                "finalize_reserved_path",
                not fin_hits,
                f"{len(fin_hits)} reserved path violation(s)" if fin_hits else "0 reserved finalize paths touched",
                fin_hits,
            )
        )

    blob_cache: dict[str, bytes] = {}
    for p in added_or_modified:
        raw = _read_blob(repo_path, inspect_tree, p)
        if raw is not None:
            blob_cache[p] = raw

    comment_errors: list[str] = []
    py_files = [p for p in added_or_modified if p.endswith(".py") and p in blob_cache]
    for p in py_files:
        raw = blob_cache[p]
        try:
            for tok in tokenize.tokenize(io.BytesIO(raw).readline):
                if tok.type == tokenize.COMMENT:
                    line_no, col_no = tok.start
                    if line_no == 1 and col_no == 0 and tok.string.startswith(SHEBANG_PREFIX):
                        continue
                    snippet = tok.string.strip()[:80]
                    comment_errors.append(f"{p}:{line_no}: unexpected comment {snippet}")
        except (tokenize.TokenError, IndentationError, SyntaxError) as exc:
            comment_errors.append(f"{p}: tokenize failure: {exc}")
    gates.append(
        _gate(
            "python_comments",
            not comment_errors,
            f"{len(py_files)} .py file(s) checked, {len(comment_errors)} comment violation(s)",
            comment_errors,
        )
    )

    dash_errors: list[str] = []
    dash_checked = 0
    for p in added_or_modified:
        raw = blob_cache.get(p)
        if raw is None or not _should_scan_dashes(p, raw):
            continue
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            continue
        dash_checked += 1
        for idx, line in enumerate(text.splitlines(), start=1):
            if EM_DASH in line or EN_DASH in line:
                kinds = []
                if EM_DASH in line:
                    kinds.append("em-dash")
                if EN_DASH in line:
                    kinds.append("en-dash")
                dash_errors.append(f"{p}:{idx}: contains {'/'.join(kinds)}")
    gates.append(
        _gate(
            "unicode_dashes",
            not dash_errors,
            f"{dash_checked} file(s) checked, {len(dash_errors)} unicode dash line(s)",
            dash_errors,
        )
    )

    coauthor_errors: list[str] = []
    commit_count = 0
    if base_sha is not None and branch_sha is not None:
        log_res = _git(repo_path, "log", "--format=%H%x00%B%x1e", f"{base_sha}..{branch_sha}")
        if log_res.returncode == 0:
            raw_log = log_res.stdout.decode("utf-8", errors="replace")
            for rec in raw_log.split("\x1e"):
                rec = rec.strip()
                if not rec or "\x00" not in rec:
                    continue
                sha, body = rec.split("\x00", 1)
                commit_count += 1
                if CO_AUTHORED_RE.search(body):
                    coauthor_errors.append(f"{sha.strip()[:8]}: Co-Authored-By trailer present")
    gates.append(
        _gate(
            "co_authored_by",
            not coauthor_errors,
            f"{commit_count} commit(s) checked, {len(coauthor_errors)} Co-Authored-By trailer(s)",
            coauthor_errors,
        )
    )

    secret_errors: list[str] = []
    for p in added_or_modified:
        if _is_secret_path(p):
            secret_errors.append(f"{p}: forbidden secret file path")
        raw = blob_cache.get(p)
        if raw is None:
            continue
        text = raw.decode("utf-8", errors="ignore")
        for kind, pat in SECRET_PATTERNS:
            for match in pat.finditer(text):
                token = match.group(0)
                line_no = text.count("\n", 0, match.start()) + 1
                secret_errors.append(f"{p}:{line_no}: {kind} leak ({token[:6]}...REDACTED)")
    gates.append(
        _gate(
            "secret_leak",
            not secret_errors,
            f"{len(added_or_modified)} file(s) checked, {len(secret_errors)} secret leak(s)",
            secret_errors,
        )
    )

    ep_errors: list[str] = []
    committed_ep_files = [
        p for p in added_or_modified
        if p.startswith("data/runs/committed/") and p.endswith("/episodes.jsonl") and p in blob_cache
    ]
    parsed_episodes_by_file: dict[str, list[dict[str, Any]]] = {}
    seen_tuples: dict[tuple[Any, Any, Any], str] = {}

    for p in committed_ep_files:
        text = blob_cache[p].decode("utf-8", errors="replace")
        file_eps: list[dict[str, Any]] = []
        for idx, line in enumerate(text.splitlines(), start=1):
            if not line.strip():
                continue
            try:
                ep = json.loads(line)
            except json.JSONDecodeError as exc:
                ep_errors.append(f"{p}:{idx}: invalid JSON ({exc})")
                continue
            if not isinstance(ep, dict):
                ep_errors.append(f"{p}:{idx}: episode record must be a JSON object")
                continue
            file_eps.append(ep)
            meta = ep.get("meta") if isinstance(ep.get("meta"), dict) else {}
            seed = ep.get("seed")
            if ep.get("rc") == "timeout" or meta.get("rc") == "timeout":
                ep_errors.append(f"{p}:{idx} (seed={seed}): rc == timeout")
            if ep.get("end_reason") == "error":
                ep_errors.append(f"{p}:{idx} (seed={seed}): end_reason == error")
            if meta.get("valid") is False:
                ep_errors.append(f"{p}:{idx} (seed={seed}): meta.valid is False")
            tup = (ep.get("agent"), ep.get("tier"), seed)
            loc = f"{p}:{idx}"
            if tup in seen_tuples:
                ep_errors.append(f"duplicate (agent, tier, seed)={tup} at {loc} and {seen_tuples[tup]}")
            else:
                seen_tuples[tup] = loc
        parsed_episodes_by_file[p] = file_eps

    gates.append(
        _gate(
            "timeout_episode",
            not ep_errors,
            f"{len(committed_ep_files)} episode file(s) checked, {len(ep_errors)} episode violation(s)",
            ep_errors,
        )
    )

    manifest_errors: list[str] = []
    candidate_shards: set[str] = set()
    for p in changed_paths:
        if not p.startswith("data/runs/committed/"):
            continue
        if p.endswith("/episodes.jsonl") or p.endswith("/meta.json"):
            candidate_shards.add(p.rsplit("/", 1)[0])
        elif "/transcripts/" in p:
            candidate_shards.add(p.split("/transcripts/", 1)[0])

    shard_metas: dict[str, dict[str, Any]] = {}
    checked_shards = 0
    for shard_dir in sorted(candidate_shards):
        if not inspect_tree:
            continue
        shard_entries = _ls_tree(repo_path, inspect_tree, shard_dir)
        if shard_entries is None:
            continue
        if "meta.json" not in shard_entries or "episodes.jsonl" not in shard_entries:
            continue
        checked_shards += 1
        meta_path = f"{shard_dir}/meta.json"
        ep_path = f"{shard_dir}/episodes.jsonl"
        meta_raw = blob_cache.get(meta_path) or _read_blob(repo_path, inspect_tree, meta_path)
        ep_raw = blob_cache.get(ep_path) or _read_blob(repo_path, inspect_tree, ep_path)
        if meta_raw is None or ep_raw is None:
            manifest_errors.append(f"{shard_dir}: unable to read meta.json or episodes.jsonl")
            continue
        try:
            meta_obj = json.loads(meta_raw.decode("utf-8", errors="replace"))
        except json.JSONDecodeError as exc:
            manifest_errors.append(f"{meta_path}: invalid JSON ({exc})")
            continue
        if not isinstance(meta_obj, dict):
            manifest_errors.append(f"{meta_path}: meta.json must be a JSON object")
            continue
        shard_metas[shard_dir] = meta_obj

        if ep_path in parsed_episodes_by_file:
            shard_eps = parsed_episodes_by_file[ep_path]
        else:
            shard_eps = []
            for idx, line in enumerate(ep_raw.decode("utf-8", errors="replace").splitlines(), start=1):
                if not line.strip():
                    continue
                try:
                    obj = json.loads(line)
                    if isinstance(obj, dict):
                        shard_eps.append(obj)
                except json.JSONDecodeError as exc:
                    manifest_errors.append(f"{ep_path}:{idx}: invalid JSON ({exc})")

        ep_seeds = [ep.get("seed") for ep in shard_eps]
        meta_seeds = meta_obj.get("seeds")
        valid_meta_seeds = (
            isinstance(meta_seeds, list)
            and all(isinstance(s, int) and not isinstance(s, bool) for s in meta_seeds)
        )
        valid_ep_seeds = all(isinstance(s, int) and not isinstance(s, bool) for s in ep_seeds)
        if not valid_meta_seeds or not valid_ep_seeds:
            manifest_errors.append(f"{shard_dir}: non-integer seeds in meta.json or episodes.jsonl")
        elif sorted(meta_seeds) != sorted(ep_seeds):
            manifest_errors.append(
                f"{shard_dir}: meta['seeds'] ({sorted(meta_seeds)}) != episode seeds ({sorted(ep_seeds)})"
            )

        seed_set = {s for s in ep_seeds if isinstance(s, int) and not isinstance(s, bool)}
        if "transcripts" in shard_entries:
            tr_files = _ls_tree(repo_path, inspect_tree, f"{shard_dir}/transcripts", recursive=True) or []
            for tf in tr_files:
                fname = tf.rsplit("/", 1)[-1]
                stem = fname.split(".", 1)[0]
                if not stem.isdigit() or int(stem) not in seed_set:
                    manifest_errors.append(
                        f"{shard_dir}/transcripts/{tf}: orphan transcript not in episode seeds"
                    )

    gates.append(
        _gate(
            "orphan_transcript",
            not manifest_errors,
            f"{checked_shards} shard manifest(s) checked, {len(manifest_errors)} manifest/transcript issue(s)",
            manifest_errors,
        )
    )

    if skip_replay:
        gates.append(_gate("replay_mismatch", True, "skipped (--skip-replay)"))
    else:
        os.environ.setdefault("CANARY_ALLOW_DEV", "1")
        from canary.rules import HELDOUT_SEEDS, JUDGE_SEEDS
        from scripts.verify_replay import replay_episode

        replay_errors: list[str] = []
        replayed_count = 0
        for p in committed_ep_files:
            shard_dir = p.rsplit("/", 1)[0]
            meta_obj = shard_metas.get(shard_dir)
            if meta_obj is None and inspect_tree:
                m_raw = _read_blob(repo_path, inspect_tree, f"{shard_dir}/meta.json")
                if m_raw is not None:
                    try:
                        loaded = json.loads(m_raw.decode("utf-8", errors="replace"))
                        if isinstance(loaded, dict):
                            meta_obj = loaded
                    except json.JSONDecodeError:
                        meta_obj = None
            is_v14 = p.startswith("data/runs/committed/v1.4/") or (
                isinstance(meta_obj, dict) and meta_obj.get("tiers_version") == "v1.4"
            )
            if not is_v14:
                continue
            for ep in parsed_episodes_by_file.get(p, []):
                meta = ep.get("meta") if isinstance(ep.get("meta"), dict) else {}
                if meta.get("valid") is False:
                    continue
                seed = ep.get("seed")
                if not isinstance(seed, int) or isinstance(seed, bool):
                    replay_errors.append(f"{p}: invalid seed {seed!r}")
                    continue
                if seed in JUDGE_SEEDS or seed in HELDOUT_SEEDS:
                    continue
                replayed_count += 1
                try:
                    rep = replay_episode(ep)
                except Exception as exc:
                    replay_errors.append(f"{p} seed={seed}: replay raised {exc!r}")
                    continue
                rec_score = ep.get("score")
                score_ok = (
                    isinstance(rec_score, (int, float))
                    and not isinstance(rec_score, bool)
                    and abs(rep["score"] - float(rec_score)) < 1e-9
                )
                accused_ok = rep["accused"] == ep.get("accused")
                if not (score_ok and accused_ok):
                    replay_errors.append(
                        f"{p} {ep.get('tier')} seed={seed} {ep.get('agent')}: "
                        f"recorded (score={rec_score}, accused={ep.get('accused')}) != "
                        f"replay (score={rep['score']}, accused={rep['accused']})"
                    )
        gates.append(
            _gate(
                "replay_mismatch",
                not replay_errors,
                f"{replayed_count} v1.4 episode(s) replayed, {len(replay_errors)} mismatch(es)",
                replay_errors,
            )
        )

    ok = all(g["passed"] for g in gates)
    return {
        "ok": ok,
        "base": base,
        "base_sha": base_sha,
        "branch": branch,
        "branch_sha": branch_sha,
        "merge_base": merge_base,
        "ff_base": ff_base,
        "changed_files": len(changed_paths),
        "warnings": warnings,
        "gates": gates,
    }


def _format_text(report: dict[str, Any]) -> str:
    b_sha = (report["base_sha"] or "missing")[:8]
    h_sha = (report["branch_sha"] or "missing")[:8]
    lines = [
        f"PR Branch Verification: {report['base']} ({b_sha}) -> {report['branch']} ({h_sha})",
        f"Changed files: {report['changed_files']}",
    ]
    for warn in report["warnings"]:
        lines.append(f"  [WARN] {warn}")
    for gate in report["gates"]:
        tag = "PASS" if gate["passed"] else "FAIL"
        lines.append(f"  [{tag}] {gate['name']}: {gate['summary']}")
        for err in gate["errors"][:10]:
            lines.append(f"         - {err}")
        extra = len(gate["errors"]) - 10
        if extra > 0:
            lines.append(f"         - ... and {extra} more")
    passed_n = sum(1 for g in report["gates"] if g["passed"])
    total_n = len(report["gates"])
    verdict = "PASS" if report["ok"] else "FAIL"
    lines.append(f"OVERALL: {verdict} ({passed_n}/{total_n} gates passed)")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Verify a candidate PR branch before shipping into justSilas.")
    ap.add_argument("--base", default="origin/justSilas")
    ap.add_argument("--branch", default="HEAD")
    ap.add_argument("--repo", default=".")
    ap.add_argument("--json", action="store_true", dest="as_json")
    ap.add_argument("--allow-core", action="store_true")
    ap.add_argument("--skip-replay", action="store_true")
    ap.add_argument("--require-ff-base", action="store_true")
    args = ap.parse_args(argv)

    report = verify_branch(
        base=args.base,
        branch=args.branch,
        repo=args.repo,
        allow_core=args.allow_core,
        skip_replay=args.skip_replay,
        require_ff_base=args.require_ff_base,
    )
    if args.as_json:
        print(json.dumps(report, indent=2))
    else:
        print(_format_text(report))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
