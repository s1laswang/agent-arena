"""Paired v1.4 (justSilas) vs v1.5 (origin/justSilas-v15@de9cc50e) differential exploit and lexical sweep."""
from __future__ import annotations

import argparse
import ast
import base64
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from dataclasses import replace
import hashlib
import importlib
import importlib.abc
import importlib.machinery
import json
import math
from pathlib import Path
import random
import re
import statistics
import subprocess
import sys
import time
from types import ModuleType
from typing import Any
import zlib

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

EXPECTED_V14_TIER_HASH = "a8f99c2537c91d72"
EXPECTED_V15_COMMIT_PREFIX = "de9cc50e"
EMBEDDED_V15_COMMIT_FULL = "de9cc50ea46420d507010b02f3562e370ca2b34b"
ISOLATED_V15_PKG = "_canary_v15_isolated"

STRATEGY_NAMES: tuple[str, ...] = (
    "do_nothing",
    "stop_early",
    "blind_seat_0",
    "accuse_most_talkative",
    "accuse_authority_role",
    "accuse_first_named_anchor",
    "accuse_lexical_hedging",
    "log_volume_outlier",
    "one_interview_accuse",
    "reference_solver",
)

AUTHORITY_ROLE_TOKENS: tuple[str, ...] = ("manager", "lead", "controller", "counsel")

INTERVIEW_HEDGE_PHRASES: tuple[str, ...] = (
    "offhand",
    "i guess",
    "don't really",
    "skim",
    "depends",
    "rather not",
    "not like i keep",
    "suppose",
    "hard to say",
    "varies",
    "another time",
    "i don't know",
    "haven't really",
    "couldn't tell",
)

MESSAGE_HEDGE_PHRASES: tuple[str, ...] = (
    "not saying",
    "could be",
    "gut feeling",
    "make of that",
    "haven't verified",
    "fairly certain",
    "no hard proof",
    "wouldn't surprise",
    "might",
)

ALL_HEDGE_PHRASES: tuple[str, ...] = INTERVIEW_HEDGE_PHRASES + MESSAGE_HEDGE_PHRASES

FORBIDDEN_SECRET_TOKENS: tuple[str, ...] = (
    "world_seed",
    "canary_world_secret",
    "true_mole",
    "is_mole",
    "true_culprit",
)

SOCIAL_SUBJECT_RE = re.compile(r"^(rumour|unverified accusation|grudge): (e\d+)$")
EMP_ID_RE = re.compile(r"\b(e\d{2})\b")
WORD_TOKEN_RE = re.compile(r"[a-z]{3,18}")
STOPWORDS = frozenset({
    "the", "and", "for", "that", "this", "with", "have", "from", "they",
    "been", "are", "was", "were", "has", "had", "not", "but", "what",
    "who", "all", "out", "you", "your", "our", "their", "them", "his",
    "her", "its", "can", "will", "just", "about", "into", "over", "after",
})


def parse_seed_spec(spec: str) -> list[int]:
    spec = spec.strip()
    if ":" in spec:
        lo, hi = spec.split(":", 1)
        return list(range(int(lo), int(hi)))
    seeds: list[int] = []
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            lo, hi = part.split("-", 1)
            seeds.extend(range(int(lo), int(hi) + 1))
        else:
            seeds.append(int(part))
    return seeds


def ci95(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    return 1.96 * statistics.stdev(values) / math.sqrt(len(values))


def rate_ci95(hits: int, total: int) -> dict[str, Any]:
    if total <= 0:
        return {"hits": 0, "total": 0, "rate": 0.0, "ci95": 0.0}
    p = hits / total
    se = math.sqrt(max(0.0, p * (1.0 - p)) / total)
    return {
        "hits": hits,
        "total": total,
        "rate": round(p, 6),
        "ci95": round(1.96 * se, 6),
    }


def compute_tier_hash(tiers: dict[str, Any], known_v_mode: bool) -> str:
    payload = {
        "tiers": {k: v.to_dict() for k, v in tiers.items()},
        "known_v_mode": known_v_mode,
    }
    encoded = json.dumps(payload, sort_keys=True, default=list).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:16]


def _is_embedded_v15_target(ref: str | None, fallback: str | None) -> bool:
    for cand in (ref, fallback):
        if not cand:
            continue
        if cand in ("origin/justSilas-v15", "justSilas-v15"):
            return True
        if len(cand) >= 7 and EMBEDDED_V15_COMMIT_FULL.startswith(cand):
            return True
    return False


def decode_embedded_v15_module(rel_path: str) -> str:
    b64 = EMBEDDED_V15_ZLIB_B64[rel_path]
    if not b64:
        return ""
    return zlib.decompress(base64.b64decode(b64.encode("ascii"))).decode("utf-8")


def embedded_v15_source_map() -> dict[str, str]:
    return {rel_path: decode_embedded_v15_module(rel_path) for rel_path in EMBEDDED_V15_ZLIB_B64}


def git_status_porcelain(repo_root: Path = REPO_ROOT) -> str:
    if (repo_root / ".git").exists():
        try:
            proc = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=repo_root,
                capture_output=True,
                text=True,
                check=False,
                timeout=15,
            )
            if proc.returncode == 0:
                return proc.stdout
        except (OSError, subprocess.SubprocessError):
            pass
    if not repo_root.exists():
        return "missing-repo-root"
    entries: list[str] = []
    for child in sorted(repo_root.iterdir(), key=lambda p: p.name):
        if child.name == ".git":
            continue
        try:
            st = child.stat()
            entries.append(f"{child.name}:{st.st_size}:{st.st_mtime_ns}")
        except OSError:
            entries.append(f"{child.name}:stat-error")
    return "\n".join(entries)


def try_resolve_git_commit(
    ref: str = "origin/justSilas-v15",
    fallback: str | None = EXPECTED_V15_COMMIT_PREFIX,
    repo_root: Path = REPO_ROOT,
) -> str | None:
    if not (repo_root / ".git").exists():
        return None
    candidates: list[str] = []
    extra_local = "justSilas-v15" if ref == "origin/justSilas-v15" else None
    for cand in (ref, extra_local, fallback):
        if cand and cand not in candidates:
            candidates.append(cand)
    for candidate in candidates:
        try:
            proc = subprocess.run(
                ["git", "rev-parse", "--verify", "--quiet", f"{candidate}^{{commit}}"],
                cwd=repo_root,
                capture_output=True,
                text=True,
                timeout=15,
            )
            sha = proc.stdout.strip()
            if proc.returncode == 0 and sha:
                blob_check = subprocess.run(
                    ["git", "cat-file", "-e", f"{sha}:canary/env.py"],
                    cwd=repo_root,
                    capture_output=True,
                    text=True,
                    timeout=15,
                )
                if blob_check.returncode == 0:
                    return sha
        except (OSError, subprocess.SubprocessError):
            continue
    return None


def resolve_git_commit(
    ref: str = "origin/justSilas-v15",
    fallback: str | None = EXPECTED_V15_COMMIT_PREFIX,
    repo_root: Path = REPO_ROOT,
    allow_embedded_fallback: bool = True,
) -> str:
    sha = try_resolve_git_commit(ref=ref, fallback=fallback, repo_root=repo_root)
    if sha is not None:
        return sha
    if allow_embedded_fallback and _is_embedded_v15_target(ref, fallback):
        return EMBEDDED_V15_COMMIT_FULL
    raise RuntimeError(f"Unable to resolve git commit for {ref!r} or fallback {fallback!r}")


def resolve_head_commit(repo_root: Path = REPO_ROOT) -> str:
    if (repo_root / ".git").exists():
        try:
            proc = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=repo_root,
                capture_output=True,
                text=True,
                check=False,
                timeout=15,
            )
            sha = proc.stdout.strip()
            if proc.returncode == 0 and sha:
                return sha
        except (OSError, subprocess.SubprocessError):
            pass
    return "nogit0000"


class _ImportRewriter(ast.NodeTransformer):
    def __init__(self, target_pkg: str) -> None:
        self.target_pkg = target_pkg

    def _rewrite_name(self, name: str) -> str:
        if name == "canary":
            return self.target_pkg
        if name.startswith("canary."):
            return self.target_pkg + name[len("canary"):]
        return name

    def visit_Import(self, node: ast.Import) -> ast.AST:
        for alias in node.names:
            old_name = alias.name
            new_name = self._rewrite_name(old_name)
            if new_name != old_name:
                if alias.asname is None and old_name == "canary":
                    alias.asname = "canary"
                alias.name = new_name
        return node

    def visit_ImportFrom(self, node: ast.ImportFrom) -> ast.AST:
        if node.level == 0 and node.module:
            node.module = self._rewrite_name(node.module)
        return node


class GitShowNamespaceFinder(importlib.abc.MetaPathFinder, importlib.abc.Loader):
    def __init__(
        self,
        repo_root: Path,
        commit_sha: str,
        pkg_name: str = ISOLATED_V15_PKG,
        embedded_sources: dict[str, str] | None = None,
    ) -> None:
        self.repo_root = repo_root
        self.commit_sha = commit_sha
        self.pkg_name = pkg_name
        self._embedded_sources = dict(embedded_sources) if embedded_sources is not None else None
        self.used_embedded_fallback = self._embedded_sources is not None
        self.source_mode = "embedded_zlib_b64" if self.used_embedded_fallback else "git_show"
        if self._embedded_sources is not None:
            self.files = frozenset(p for p in self._embedded_sources if p.endswith(".py"))
        else:
            proc = subprocess.run(
                ["git", "ls-tree", "-r", "--name-only", commit_sha, "--", "canary/"],
                cwd=repo_root,
                capture_output=True,
                text=True,
                check=True,
                timeout=15,
            )
            self.files = frozenset(ln.strip() for ln in proc.stdout.splitlines() if ln.strip().endswith(".py"))
        self.source_cache: dict[str, str] = {}
        self.git_show_paths: list[str] = []
        self.loaded_paths: list[str] = []

    def _resolve_rel_path(self, fullname: str) -> tuple[str, bool] | None:
        if fullname != self.pkg_name and not fullname.startswith(self.pkg_name + "."):
            return None
        suffix = fullname[len(self.pkg_name):].lstrip(".")
        rel_base = "canary" if not suffix else "canary/" + suffix.replace(".", "/")
        pkg_init = f"{rel_base}/__init__.py"
        if pkg_init in self.files:
            return pkg_init, True
        mod_file = f"{rel_base}.py"
        if mod_file in self.files:
            return mod_file, False
        return None

    def _read_source(self, rel_path: str) -> str:
        if rel_path not in self.source_cache:
            if self._embedded_sources is not None:
                self.source_cache[rel_path] = self._embedded_sources[rel_path]
                self.loaded_paths.append(rel_path)
            else:
                proc = subprocess.run(
                    ["git", "show", f"{self.commit_sha}:{rel_path}"],
                    cwd=self.repo_root,
                    capture_output=True,
                    text=True,
                    check=True,
                    timeout=15,
                )
                self.source_cache[rel_path] = proc.stdout
                self.git_show_paths.append(rel_path)
                self.loaded_paths.append(rel_path)
        return self.source_cache[rel_path]

    def find_spec(self, fullname: str, path: Any = None, target: Any = None) -> importlib.machinery.ModuleSpec | None:
        resolved = self._resolve_rel_path(fullname)
        if resolved is None:
            return None
        rel_path, is_pkg = resolved
        origin = str(self.repo_root / rel_path)
        spec = importlib.machinery.ModuleSpec(fullname, self, origin=origin, is_package=is_pkg)
        if is_pkg:
            spec.submodule_search_locations = [str((self.repo_root / rel_path).parent)]
        return spec

    def create_module(self, spec: importlib.machinery.ModuleSpec) -> ModuleType | None:
        return None

    def exec_module(self, module: ModuleType) -> None:
        resolved = self._resolve_rel_path(module.__name__)
        if resolved is None:
            raise ImportError(f"Cannot resolve {module.__name__}")
        rel_path, _ = resolved
        raw_source = self._read_source(rel_path)
        tag = "embedded" if self.used_embedded_fallback else "git"
        virtual_name = f"<{tag}:{self.commit_sha[:8]}:{rel_path}>"
        tree = ast.parse(raw_source, filename=virtual_name)
        tree = _ImportRewriter(self.pkg_name).visit(tree)
        ast.fix_missing_locations(tree)
        module.__file__ = str(self.repo_root / rel_path)
        code = compile(tree, virtual_name, "exec")
        exec(code, module.__dict__)


class IsolatedV15Runtime:
    def __init__(self, finder: GitShowNamespaceFinder, commit_sha: str, status_unchanged: bool) -> None:
        self.finder = finder
        self.commit_sha = commit_sha
        self.pkg_name = finder.pkg_name
        self.used_embedded_fallback = finder.used_embedded_fallback
        self.source_mode = finder.source_mode
        self.status_unchanged = status_unchanged
        self.rules = importlib.import_module(f"{self.pkg_name}.rules")
        self.env_mod = importlib.import_module(f"{self.pkg_name}.env")
        self.solver_mod = importlib.import_module(f"{self.pkg_name}.solver.policy")
        self.template_mod = importlib.import_module(f"{self.pkg_name}.text.template")
        self._v14_tiers_snapshot = dict(self.rules.TIERS)
        self._v15_tiers_snapshot = dict(self.rules.TIERS_V15)
        self.rules.TIERS.clear()
        self.rules.TIERS.update(self._v15_tiers_snapshot)
        self.rules.TIERS_VERSION = "v1.5-candidate"

    def make_env(self, tier: str, seed: int, social_enabled: bool = True, misforward_enabled: bool = True) -> Any:
        if social_enabled and misforward_enabled:
            self.rules.TIERS.clear()
            self.rules.TIERS.update(self._v15_tiers_snapshot)
            self.rules.TIERS_VERSION = "v1.5-candidate"
            return self.env_mod.Env(tier, seed)
        try:
            self.rules.TIERS.clear()
            if not social_enabled:
                self.rules.TIERS.update(self._v14_tiers_snapshot)
                self.rules.TIERS_VERSION = "v1.4"
            else:
                no_fwd = {k: replace(v, p_misforward=0.0) for k, v in self._v15_tiers_snapshot.items()}
                self.rules.TIERS.update(no_fwd)
                self.rules.TIERS_VERSION = "v1.5-candidate"
            return self.env_mod.Env(tier, seed)
        finally:
            self.rules.TIERS.clear()
            self.rules.TIERS.update(self._v15_tiers_snapshot)
            self.rules.TIERS_VERSION = "v1.5-candidate"

    def make_solver(self) -> Any:
        return self.solver_mod.SolverPolicy()


_RUNTIME_CACHE: dict[tuple[str, str, str, bool], IsolatedV15Runtime] = {}


def load_v15_runtime(
    ref: str = "origin/justSilas-v15",
    pkg_name: str = ISOLATED_V15_PKG,
    repo_root: Path = REPO_ROOT,
    force_embedded: bool = False,
) -> IsolatedV15Runtime:
    fallback = EXPECTED_V15_COMMIT_PREFIX if ref == "origin/justSilas-v15" else None
    resolved_repo = repo_root.resolve()
    git_sha = None if force_embedded else try_resolve_git_commit(ref=ref, fallback=fallback, repo_root=resolved_repo)
    if git_sha is not None:
        commit_sha = git_sha
        embedded_map: dict[str, str] | None = None
    elif force_embedded or _is_embedded_v15_target(ref, fallback):
        commit_sha = EMBEDDED_V15_COMMIT_FULL
        embedded_map = embedded_v15_source_map()
    else:
        raise RuntimeError(f"Unable to resolve git commit for {ref!r} or fallback {fallback!r}")

    use_embedded = embedded_map is not None
    cache_key = (commit_sha, pkg_name, str(resolved_repo), use_embedded)
    if cache_key in _RUNTIME_CACHE and pkg_name in sys.modules:
        return _RUNTIME_CACHE[cache_key]

    for stale_key in [k for k in _RUNTIME_CACHE if k[1] == pkg_name]:
        _RUNTIME_CACHE.pop(stale_key, None)

    before_status = git_status_porcelain(resolved_repo)
    for mod_key in list(sys.modules):
        if mod_key == pkg_name or mod_key.startswith(pkg_name + "."):
            sys.modules.pop(mod_key, None)
    sys.meta_path[:] = [
        f for f in sys.meta_path
        if not (isinstance(f, GitShowNamespaceFinder) and f.pkg_name == pkg_name)
    ]
    finder = GitShowNamespaceFinder(
        repo_root=resolved_repo,
        commit_sha=commit_sha,
        pkg_name=pkg_name,
        embedded_sources=embedded_map,
    )
    sys.meta_path.insert(0, finder)
    after_status = git_status_porcelain(resolved_repo)
    rt = IsolatedV15Runtime(finder=finder, commit_sha=commit_sha, status_unchanged=(before_status == after_status))
    post_import_status = git_status_porcelain(resolved_repo)
    rt.status_unchanged = rt.status_unchanged and (before_status == post_import_status)
    _RUNTIME_CACHE[cache_key] = rt
    return rt


def _extract_list(result: dict[str, Any] | None, key: str | None = None) -> list[Any]:
    if not result or not result.get("ok"):
        return []
    data = result.get("data")
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        if key and isinstance(data.get(key), list):
            return data[key]
        for v in data.values():
            if isinstance(v, list):
                return v
    return []


def _argmax_det(counts: Counter[str], pool: list[str], rng: random.Random) -> str:
    if not pool:
        return "e00"
    best = max(counts.get(e, 0) for e in pool)
    tied = [e for e in pool if counts.get(e, 0) == best]
    return rng.choice(tied)


def _msg_sort_key(msg_id: str) -> tuple[int, int, int]:
    m = re.match(r"^m(\d+)-(s?)(\d+)$", msg_id)
    if not m:
        return (9999, 1, 9999)
    return (int(m.group(1)), 1 if m.group(2) == "s" else 0, int(m.group(3)))


def _count_phrases(text: str, phrases: tuple[str, ...]) -> int:
    low = text.lower()
    return sum(1 for p in phrases if p in low)


class GeneratorStrategy:
    name = "generator_strategy"

    def __init__(self, seed: int = 0) -> None:
        self.seed = seed
        self.rng = random.Random(f"{self.name}:{seed}")
        self._gen: Any = None
        self._started = False

    def reset(self, tools_spec: list[dict[str, Any]], instruction: str) -> None:
        self.rng = random.Random(f"{self.name}:{self.seed}")
        self.tools_spec = tools_spec
        self.instruction = instruction
        self._gen = self.script()
        self._started = False

    def act(self, history: list[Any]) -> tuple[str, dict[str, Any]]:
        if self._gen is None:
            self.reset([], "")
        last = history[-1].result if history else None
        try:
            if not self._started:
                self._started = True
                return next(self._gen)
            return self._gen.send(last)
        except StopIteration:
            return ("__quit__", {})

    def _list_employees(self):
        res = yield ("list_employees", {})
        emps = [row for row in _extract_list(res, "employees") if isinstance(row, dict) and isinstance(row.get("id"), str)]
        return emps

    def _collect_day_messages(self, day: int, seen_ids: set[str]):
        found: list[dict[str, Any]] = []
        for q in ("e", "a"):
            res = yield ("search_messages", {"query": q, "day_from": day, "day_to": day})
            for m in _extract_list(res, "messages"):
                if isinstance(m, dict):
                    mid = str(m.get("id", ""))
                    if mid and mid not in seen_ids:
                        seen_ids.add(mid)
                        found.append(m)
        found.sort(key=lambda x: _msg_sort_key(str(x.get("id", ""))))
        return found

    def script(self):
        while True:
            yield ("advance_day", {})


class DoNothingStrategy(GeneratorStrategy):
    name = "do_nothing"


class StopEarlyStrategy(GeneratorStrategy):
    name = "stop_early"

    def script(self):
        yield ("list_employees", {})
        yield ("status", {})
        yield ("advance_day", {})
        yield ("read_access_logs", {"day_from": 1, "day_to": 1})


class BlindSeat0Strategy(GeneratorStrategy):
    name = "blind_seat_0"

    def script(self):
        emps = yield from self._list_employees()
        target = emps[0]["id"] if emps else "e00"
        yield ("accuse", {"employee": target})


class AccuseMostTalkativeStrategy(GeneratorStrategy):
    name = "accuse_most_talkative"

    def script(self):
        emps = yield from self._list_employees()
        ids = [e["id"] for e in emps]
        seen_ids: set[str] = set()
        talk_counts: Counter[str] = Counter()
        for closed_day in range(1, 6):
            r_adv = yield ("advance_day", {})
            if not (r_adv and r_adv.get("ok")) or (r_adv.get("data") or {}).get("episode_over"):
                break
            msgs = yield from self._collect_day_messages(closed_day, seen_ids)
            for m in msgs:
                snd = str(m.get("sender", ""))
                if snd in ids:
                    talk_counts[snd] += 1
        yield ("accuse", {"employee": _argmax_det(talk_counts, ids, self.rng)})


class AccuseAuthorityRoleStrategy(GeneratorStrategy):
    name = "accuse_authority_role"

    def script(self):
        emps = yield from self._list_employees()
        ids = [e["id"] for e in emps]
        auth_ids = [
            e["id"]
            for e in emps
            if any(tok in str(e.get("role", "")).lower() for tok in AUTHORITY_ROLE_TOKENS)
        ] or list(ids)
        seen_ids: set[str] = set()
        scores: Counter[str] = Counter()
        for e in emps:
            if e["id"] in auth_ids and isinstance(e.get("clearance"), int):
                scores[e["id"]] += int(e["clearance"])
        for closed_day in range(1, 4):
            r_adv = yield ("advance_day", {})
            if not (r_adv and r_adv.get("ok")) or (r_adv.get("data") or {}).get("episode_over"):
                break
            msgs = yield from self._collect_day_messages(closed_day, seen_ids)
            for m in msgs:
                snd = str(m.get("sender", ""))
                if snd in auth_ids:
                    scores[snd] += 2
        doc_res = yield ("list_documents", {"day_from": 1, "day_to": 4})
        for d in _extract_list(doc_res, "documents"):
            if isinstance(d, dict):
                for rec in d.get("recipients", []) or []:
                    if rec in auth_ids:
                        scores[str(rec)] += 1
        yield ("accuse", {"employee": _argmax_det(scores, auth_ids, self.rng)})


class AccuseFirstNamedAnchorStrategy(GeneratorStrategy):
    name = "accuse_first_named_anchor"

    def script(self):
        emps = yield from self._list_employees()
        ids = [e["id"] for e in emps]
        id_set = set(ids)
        first_name_map: dict[str, list[str]] = {}
        full_name_map: list[tuple[str, str]] = []
        for e in emps:
            eid = e["id"]
            nm = str(e.get("name", "")).strip()
            if nm:
                full_name_map.append((nm.lower(), eid))
                fn = nm.split()[0].lower()
                first_name_map.setdefault(fn, []).append(eid)

        seen_ids: set[str] = set()
        explicit_anchor: str | None = None
        name_anchor: str | None = None
        fallback_recipient: str | None = None

        for closed_day in range(1, 4):
            r_adv = yield ("advance_day", {})
            if not (r_adv and r_adv.get("ok")) or (r_adv.get("data") or {}).get("episode_over"):
                break
            stubs = yield from self._collect_day_messages(closed_day, seen_ids)
            reads_used = 0
            for stub in stubs:
                msg = stub
                if len(str(stub.get("snippet", ""))) >= 118 and reads_used < 6:
                    mid = str(stub.get("id", ""))
                    full_res = yield ("read_message", {"id": mid})
                    reads_used += 1
                    if full_res and full_res.get("ok"):
                        msg = ((full_res.get("data") or {}).get("message")) or stub
                if not isinstance(msg, dict):
                    continue
                sender = str(msg.get("sender", ""))
                if fallback_recipient is None:
                    for r_id in msg.get("recipients", []) or []:
                        if r_id in id_set and r_id != sender:
                            fallback_recipient = str(r_id)
                            break
                subj = str(msg.get("subject", ""))
                body = str(msg.get("body", msg.get("snippet", "")))
                combined = f"{subj}\n{body}"
                for match_id in EMP_ID_RE.findall(combined):
                    if match_id in id_set and match_id != sender:
                        explicit_anchor = match_id
                        break
                if explicit_anchor is not None:
                    break
                if name_anchor is None:
                    low_body = body.lower()
                    for full_nm, eid in full_name_map:
                        if eid != sender and full_nm in low_body:
                            name_anchor = eid
                            break
                    if name_anchor is None:
                        for fn, eids in first_name_map.items():
                            if len(fn) >= 3 and re.search(rf"\b{re.escape(fn)}\b", low_body):
                                others = [x for x in eids if x != sender]
                                if others:
                                    name_anchor = others[0]
                                    break
            if explicit_anchor is not None:
                break

        chosen = explicit_anchor or name_anchor or fallback_recipient or (ids[0] if ids else "e00")
        yield ("accuse", {"employee": chosen})


class AccuseLexicalHedgingStrategy(GeneratorStrategy):
    name = "accuse_lexical_hedging"

    def script(self):
        emps = yield from self._list_employees()
        ids = [e["id"] for e in emps]
        iv_order = list(ids)
        self.rng.shuffle(iv_order)
        hedge_scores: Counter[str] = Counter()
        seen_ids: set[str] = set()
        iv_cursor = 0

        for _ in range(min(8, len(iv_order))):
            target_emp = iv_order[iv_cursor % len(iv_order)]
            iv_cursor += 1
            res = yield ("interview", {"employee": target_emp, "topic": "recent_documents"})
            ans = str(((res or {}).get("data") or {}).get("answer", ""))
            hedge_scores[target_emp] += 2 * _count_phrases(ans, INTERVIEW_HEDGE_PHRASES)

        for closed_day in range(1, 4):
            r_adv = yield ("advance_day", {})
            if not (r_adv and r_adv.get("ok")) or (r_adv.get("data") or {}).get("episode_over"):
                break
            msgs = yield from self._collect_day_messages(closed_day, seen_ids)
            for m in msgs:
                snd = str(m.get("sender", ""))
                txt = f"{m.get('subject', '')} {m.get('snippet', '')}"
                if snd in ids:
                    hedge_scores[snd] += _count_phrases(txt, ALL_HEDGE_PHRASES)
            topic = "workload" if closed_day % 2 == 1 else "contacts_outside"
            for _ in range(min(6, len(iv_order))):
                target_emp = iv_order[iv_cursor % len(iv_order)]
                iv_cursor += 1
                res = yield ("interview", {"employee": target_emp, "topic": topic})
                ans = str(((res or {}).get("data") or {}).get("answer", ""))
                hedge_scores[target_emp] += 2 * _count_phrases(ans, INTERVIEW_HEDGE_PHRASES)

        yield ("accuse", {"employee": _argmax_det(hedge_scores, ids, self.rng)})


class LogVolumeOutlierStrategy(GeneratorStrategy):
    name = "log_volume_outlier"

    def script(self):
        emps = yield from self._list_employees()
        ids = [e["id"] for e in emps]
        last_closed = 1
        for closed_day in range(1, 6):
            r_adv = yield ("advance_day", {})
            if not (r_adv and r_adv.get("ok")) or (r_adv.get("data") or {}).get("episode_over"):
                break
            last_closed = closed_day
        log_res = yield ("read_access_logs", {"day_from": 1, "day_to": last_closed})
        outlier_scores: Counter[str] = Counter()
        for entry in _extract_list(log_res, "logs"):
            if isinstance(entry, dict):
                emp = str(entry.get("employee", ""))
                if emp in ids:
                    outlier_scores[emp] += 1 + 3 * int(bool(entry.get("after_hours")))
        yield ("accuse", {"employee": _argmax_det(outlier_scores, ids, self.rng)})


class OneInterviewAccuseStrategy(GeneratorStrategy):
    name = "one_interview_accuse"

    def script(self):
        emps = yield from self._list_employees()
        ids = [e["id"] for e in emps]
        if not ids:
            yield ("accuse", {"employee": "e00"})
            return
        probe = self.rng.choice(ids)
        iv_res = yield ("interview", {"employee": probe, "topic": "recent_documents"})
        ans = str(((iv_res or {}).get("data") or {}).get("answer", ""))
        if _count_phrases(ans, INTERVIEW_HEDGE_PHRASES) > 0:
            chosen = probe
        else:
            others = [x for x in ids if x != probe] or ids
            chosen = self.rng.choice(others)
        yield ("accuse", {"employee": chosen})


STRATEGY_CLASSES: dict[str, type[GeneratorStrategy]] = {
    "do_nothing": DoNothingStrategy,
    "stop_early": StopEarlyStrategy,
    "blind_seat_0": BlindSeat0Strategy,
    "accuse_most_talkative": AccuseMostTalkativeStrategy,
    "accuse_authority_role": AccuseAuthorityRoleStrategy,
    "accuse_first_named_anchor": AccuseFirstNamedAnchorStrategy,
    "accuse_lexical_hedging": AccuseLexicalHedgingStrategy,
    "log_volume_outlier": LogVolumeOutlierStrategy,
    "one_interview_accuse": OneInterviewAccuseStrategy,
}


def make_strategy(strategy_name: str, seed: int, version: str, v15_rt: IsolatedV15Runtime | None = None) -> Any:
    if strategy_name == "reference_solver":
        if version == "v1.4":
            from canary.solver.policy import SolverPolicy
            return SolverPolicy()
        if v15_rt is None:
            raise ValueError("v15_rt is required for v1.5 reference_solver")
        return v15_rt.make_solver()
    cls = STRATEGY_CLASSES.get(strategy_name)
    if cls is None:
        raise ValueError(f"Unknown strategy {strategy_name!r}")
    return cls(seed=seed)


def verify_episode_score_invariants(env: Any, score: float) -> list[str]:
    violations: list[str] = []
    if not (-1.0 <= score <= 1.0) or not math.isfinite(score):
        violations.append(f"score_out_of_bounds:{score}")
    accused = getattr(env, "_accused", None)
    correct = bool(getattr(env, "_correct", False))
    done = bool(getattr(env, "done", False))
    if accused is None:
        if score != 0.0:
            violations.append(f"unaccused_nonzero_score:{score}")
        if correct:
            violations.append("unaccused_marked_correct")
    else:
        if not done:
            violations.append("accused_not_done")
        if correct:
            expected = round(float(env.V), 10)
            if abs(score - expected) > 1e-9 or score < 0.0:
                violations.append(f"correct_score_mismatch:{score}!={expected}")
        else:
            wrong_pen = float(env.p.wrong_accusation_score)
            if abs(score - wrong_pen) > 1e-9:
                violations.append(f"wrong_accusation_mismatch:{score}!={wrong_pen}")
    return violations


def run_single_episode(env: Any, policy: Any, max_steps: int = 600) -> dict[str, Any]:
    policy.reset(env.tools_spec(), env.instruction())
    quit_early = False
    for _ in range(max_steps):
        if env.done:
            break
        tool, args = policy.act(list(env.history))
        if tool == "__quit__":
            quit_early = True
            break
        env.call(tool, args)
    score = float(env.score())
    violations = verify_episode_score_invariants(env, score)
    accused = getattr(env, "_accused", None)
    true_mole = str(env._world.mole)
    true_decoy = getattr(env._world, "decoy", None)
    obs = getattr(policy, "obs", None)
    inferred_decoy = getattr(obs, "decoy", None) if obs is not None else None
    return {
        "score": score,
        "accused": accused,
        "has_accused": accused is not None,
        "correct": bool(getattr(env, "_correct", False)) if accused is not None else False,
        "hit_decoy": bool(true_decoy is not None and accused == true_decoy),
        "decoy_inferred": bool(true_decoy is not None and inferred_decoy == true_decoy),
        "done": bool(env.done),
        "quit_early": quit_early,
        "end_reason": getattr(env, "_end_reason", None) or ("quit_early" if quit_early else "unfinished"),
        "final_day": int(env.day),
        "n_steps": len(env.history),
        "true_V": round(float(env.V), 6),
        "true_mole": true_mole,
        "true_decoy": true_decoy,
        "violations": violations,
    }


def _worker_seed_batch(args: tuple[str, list[int], list[str], str, str, bool]) -> list[dict[str, Any]]:
    tier, seed_batch, strategies, v15_ref, repo_root_str, force_embedded = args
    from canary.env import Env as EnvV14

    v15_rt = load_v15_runtime(ref=v15_ref, repo_root=Path(repo_root_str), force_embedded=force_embedded)
    batch_rows: list[dict[str, Any]] = []
    for seed in seed_batch:
        for strat_name in strategies:
            ep_v14 = run_single_episode(EnvV14(tier, seed), make_strategy(strat_name, seed, "v1.4"))
            ep_v15 = run_single_episode(v15_rt.make_env(tier, seed, social_enabled=True), make_strategy(strat_name, seed, "v1.5", v15_rt))
            batch_rows.append({
                "tier": tier,
                "seed": seed,
                "strategy": strat_name,
                "v14": ep_v14,
                "v15": ep_v15,
            })
    return batch_rows


def summarize_version_episodes(rows: list[dict[str, Any]], has_decoy: bool) -> dict[str, Any]:
    n = len(rows) or 1
    scores = [float(r["score"]) for r in rows]
    accused_rows = [r for r in rows if r["has_accused"]]
    violations = sum(len(r["violations"]) for r in rows)
    return {
        "n": len(rows),
        "mean_score": round(statistics.mean(scores), 4) if scores else 0.0,
        "ci95": round(ci95(scores), 4),
        "acc": round(sum(1 for r in rows if r["correct"]) / n, 4),
        "acc_when_accusing": round(sum(1 for r in accused_rows if r["correct"]) / len(accused_rows), 4) if accused_rows else 0.0,
        "decoy_hit_rate": round(sum(1 for r in rows if r["hit_decoy"]) / n, 4) if has_decoy else 0.0,
        "decoy_inferred_rate": round(sum(1 for r in rows if r["decoy_inferred"]) / n, 4) if has_decoy else None,
        "abstain_rate": round(1.0 - len(accused_rows) / n, 4),
        "mean_day": round(statistics.mean([r["final_day"] for r in accused_rows]), 2) if accused_rows else None,
        "mean_steps": round(statistics.mean([r["n_steps"] for r in rows]), 2) if rows else 0.0,
        "invariant_violations": violations,
    }


def summarize_paired_strategy(paired_rows: list[dict[str, Any]], has_decoy: bool) -> dict[str, Any]:
    v14_eps = [r["v14"] for r in paired_rows]
    v15_eps = [r["v15"] for r in paired_rows]
    v14_sum = summarize_version_episodes(v14_eps, has_decoy)
    v15_sum = summarize_version_episodes(v15_eps, has_decoy)
    deltas = [float(b["score"]) - float(a["score"]) for a, b in zip(v14_eps, v15_eps)]
    wins = sum(1 for d in deltas if d > 1e-9)
    ties = sum(1 for d in deltas if abs(d) <= 1e-9)
    losses = sum(1 for d in deltas if d < -1e-9)
    same_accused = sum(1 for a, b in zip(v14_eps, v15_eps) if a["accused"] == b["accused"])
    same_world = sum(1 for a, b in zip(v14_eps, v15_eps) if a["true_mole"] == b["true_mole"] and a["true_decoy"] == b["true_decoy"])
    n = len(paired_rows) or 1
    return {
        "n_paired": len(paired_rows),
        "same_world_truth_rate": round(same_world / n, 6),
        "v14": v14_sum,
        "v15": v15_sum,
        "paired_v15_minus_v14": {
            "mean_delta_score": round(statistics.mean(deltas), 4) if deltas else 0.0,
            "ci95_delta_score": round(ci95(deltas), 4),
            "delta_acc": round(v15_sum["acc"] - v14_sum["acc"], 4),
            "delta_decoy_hit_rate": round(v15_sum["decoy_hit_rate"] - v14_sum["decoy_hit_rate"], 4),
            "wins": wins,
            "ties": ties,
            "losses": losses,
            "same_accused_rate": round(same_accused / n, 4),
        },
    }


def run_paired_strategy_sweep(
    tiers: list[str],
    seeds: list[int],
    strategies: list[str] | None = None,
    v15_ref: str = "origin/justSilas-v15",
    workers: int = 1,
    repo_root: Path = REPO_ROOT,
    force_embedded: bool = False,
) -> dict[str, Any]:
    from canary.env import Env as EnvV14

    strat_list = list(strategies or STRATEGY_NAMES)
    repo_root_str = str(repo_root.resolve())
    all_rows: list[dict[str, Any]] = []
    if workers > 1 and len(seeds) >= 4:
        tasks: list[tuple[str, list[int], list[str], str, str, bool]] = []
        chunk_size = max(1, math.ceil(len(seeds) / (workers * 2)))
        for tier in tiers:
            for idx in range(0, len(seeds), chunk_size):
                tasks.append((tier, seeds[idx:idx + chunk_size], strat_list, v15_ref, repo_root_str, force_embedded))
        with ProcessPoolExecutor(max_workers=workers) as pool:
            for part in pool.map(_worker_seed_batch, tasks):
                all_rows.extend(part)
    else:
        for tier in tiers:
            all_rows.extend(_worker_seed_batch((tier, seeds, strat_list, v15_ref, repo_root_str, force_embedded)))

    by_tier: dict[str, Any] = {}
    total_violations = 0
    for tier in tiers:
        sample_env = EnvV14(tier, seeds[0])
        has_decoy = bool(sample_env.p.decoy)
        n_emp = int(sample_env.p.n_employees)
        tier_rows = [r for r in all_rows if r["tier"] == tier]
        strat_summaries: dict[str, Any] = {}
        for strat_name in strat_list:
            s_rows = [r for r in tier_rows if r["strategy"] == strat_name]
            s_rows.sort(key=lambda x: int(x["seed"]))
            summary = summarize_paired_strategy(s_rows, has_decoy)
            total_violations += summary["v14"]["invariant_violations"] + summary["v15"]["invariant_violations"]
            strat_summaries[strat_name] = summary

        if "reference_solver" in strat_summaries:
            sol_rows = [r for r in tier_rows if r["strategy"] == "reference_solver"]
            sol_rows.sort(key=lambda x: int(x["seed"]))
            for strat_name in strat_list:
                if strat_name == "reference_solver":
                    continue
                h_rows = [r for r in tier_rows if r["strategy"] == strat_name]
                h_rows.sort(key=lambda x: int(x["seed"]))
                gap_v14 = [float(sr["v14"]["score"]) - float(hr["v14"]["score"]) for sr, hr in zip(sol_rows, h_rows)]
                gap_v15 = [float(sr["v15"]["score"]) - float(hr["v15"]["score"]) for sr, hr in zip(sol_rows, h_rows)]
                strat_summaries[strat_name]["solver_gap"] = {
                    "v14_solver_minus_strategy": round(statistics.mean(gap_v14), 4) if gap_v14 else 0.0,
                    "v14_gap_ci95": round(ci95(gap_v14), 4),
                    "v15_solver_minus_strategy": round(statistics.mean(gap_v15), 4) if gap_v15 else 0.0,
                    "v15_gap_ci95": round(ci95(gap_v15), 4),
                }

        non_solver = [k for k in strat_list if k != "reference_solver"]
        best_v14_h = max((strat_summaries[k]["v14"]["mean_score"] for k in non_solver), default=0.0)
        best_v15_h = max((strat_summaries[k]["v15"]["mean_score"] for k in non_solver), default=0.0)
        best_v14_name = max(non_solver, key=lambda k: strat_summaries[k]["v14"]["mean_score"]) if non_solver else None
        best_v15_name = max(non_solver, key=lambda k: strat_summaries[k]["v15"]["mean_score"]) if non_solver else None

        by_tier[tier] = {
            "tier": tier,
            "n_employees": n_emp,
            "prior_mole": round(1.0 / n_emp, 6),
            "has_decoy": has_decoy,
            "n_seeds": len(seeds),
            "best_non_solver_v14": {"strategy": best_v14_name, "mean_score": best_v14_h},
            "best_non_solver_v15": {"strategy": best_v15_name, "mean_score": best_v15_h},
            "strategies": strat_summaries,
        }

    return {
        "n_paired_runs": len(all_rows),
        "n_strategy_episodes": 2 * len(all_rows),
        "total_invariant_violations": total_violations,
        "tiers": by_tier,
    }


def _passive_full_horizon(env: Any) -> dict[str, Any]:
    for _ in range(int(env.p.n_days)):
        if env.done:
            break
        env.call("advance_day", {})
    leaks = [
        (int(ev.day), str(ev.detail.get("doc_id")))
        for ev in env.ledger()
        if getattr(ev, "event", "") == "leak" and getattr(ev, "detail", None)
    ]
    logs_sig = tuple(
        (int(x["day"]), str(x["employee"]), str(x["doc_id"]), bool(x["after_hours"]))
        for x in env._logs
    )
    msgs = [dict(env._messages[mid]) for mid in env._msg_order]
    docs = [dict(d) for d in env.docs]
    return {
        "world_seed": int(env._world.world_seed),
        "mole": str(env._world.mole),
        "decoy": getattr(env._world, "decoy", None),
        "ids": list(env._ids),
        "leaks": tuple(leaks),
        "logs_sig": logs_sig,
        "n_logs": len(env._logs),
        "msgs": msgs,
        "docs": docs,
    }


def audit_interview_template_separability(v15_rt: IsolatedV15Runtime | None = None) -> dict[str, Any]:
    from canary.solver.policy import SolverPolicy as SolverV14
    from canary.text import template as tpl_v14
    from canary.types import Step

    evasive_total = 0
    evasive_hedge_hits = 0
    evasive_literal_word_hits = 0
    coop_total = 0
    coop_hedge_false_positives = 0

    for (topic, sig), templates in tpl_v14._ANSWERS.items():
        for raw_tpl in templates:
            rendered = raw_tpl.format(
                doc="Project Falcon roadmap",
                dept="Engineering",
                outside="a vendor rep from Cloudwise",
                thing="the Q3 budget",
                when="Friday",
            )
            has_hedge = _count_phrases(rendered, INTERVIEW_HEDGE_PHRASES) > 0
            has_evasive_word = "evasive" in rendered.lower()
            if sig == "evasive":
                evasive_total += 1
                if has_hedge:
                    evasive_hedge_hits += 1
                if has_evasive_word:
                    evasive_literal_word_hits += 1
            else:
                coop_total += 1
                if has_hedge:
                    coop_hedge_false_positives += 1

    sp14 = SolverV14("easy")
    sp14.reset([], "")
    sample_evasive = tpl_v14._ANSWERS[("recent_documents", "evasive")][0]
    sp14._ingest(Step(t=0, day=1, tool="interview", args={"employee": "e00", "topic": "recent_documents"},
                      result={"ok": True, "data": {"employee": "e00", "topic": "recent_documents", "answer": sample_evasive}, "error": None}))
    solver_v14_ingested_evasive = bool(sp14.obs.interviews and sp14.obs.interviews[0][1])

    solver_v15_ingested_evasive: bool | None = None
    if v15_rt is not None:
        sp15 = v15_rt.make_solver()
        sp15.reset([], "")
        sp15._ingest(Step(t=0, day=1, tool="interview", args={"employee": "e00", "topic": "recent_documents"},
                          result={"ok": True, "data": {"employee": "e00", "topic": "recent_documents", "answer": sample_evasive}, "error": None}))
        solver_v15_ingested_evasive = bool(sp15.obs.interviews and sp15.obs.interviews[0][1])

    return {
        "evasive_templates_total": evasive_total,
        "evasive_hedge_recall": round(evasive_hedge_hits / max(1, evasive_total), 6),
        "cooperative_templates_total": coop_total,
        "cooperative_hedge_false_positive_rate": round(coop_hedge_false_positives / max(1, coop_total), 6),
        "evasive_contains_literal_evasive_word": evasive_literal_word_hits,
        "solver_v14_marks_template_evasive": solver_v14_ingested_evasive,
        "solver_v15_marks_template_evasive": solver_v15_ingested_evasive,
    }


def audit_lexical_and_stream_differentials(
    tiers: list[str],
    seeds: list[int],
    v15_rt: IsolatedV15Runtime,
) -> dict[str, Any]:
    from canary.env import Env as EnvV14

    per_tier: dict[str, Any] = {}
    total_passive_episodes = 0

    for tier in tiers:
        parity_seeds = seeds[:min(5, len(seeds))]
        knob_off_exact_matches = 0
        social_no_misfwd_stream_matches = 0
        for s in parity_seeds:
            st14 = _passive_full_horizon(EnvV14(tier, s))
            st15_off = _passive_full_horizon(v15_rt.make_env(tier, s, social_enabled=False))
            st15_nofwd = _passive_full_horizon(v15_rt.make_env(tier, s, social_enabled=True, misforward_enabled=False))
            if (
                st14["world_seed"] == st15_off["world_seed"]
                and st14["mole"] == st15_off["mole"]
                and st14["leaks"] == st15_off["leaks"]
                and st14["logs_sig"] == st15_off["logs_sig"]
                and len(st14["msgs"]) == len(st15_off["msgs"])
            ):
                knob_off_exact_matches += 1
            if (
                st14["leaks"] == st15_nofwd["leaks"]
                and st14["logs_sig"] == st15_nofwd["logs_sig"]
                and len(st15_nofwd["msgs"]) > len(st14["msgs"])
            ):
                social_no_misfwd_stream_matches += 1

        leak_seq_diverged = 0
        log_stream_diverged = 0
        day1_empty_held_flipped = 0
        mole_word_leaks = 0
        secret_token_leaks = 0
        social_msgs_total = 0
        misforwards_total = 0

        social_target_events = 0
        social_target_is_mole = 0
        social_target_is_decoy = 0
        social_sender_events = 0
        social_sender_is_mole = 0

        rumour_target_events = 0
        rumour_target_is_mole = 0
        rumour_target_is_decoy = 0

        authority_target_events = 0
        authority_target_is_mole = 0
        authority_target_is_decoy = 0

        grudge_participants_total = 0
        grudge_participant_is_mole = 0
        grudge_participant_is_decoy = 0

        top_named_total = 0
        top_named_is_mole = 0
        top_named_is_decoy = 0

        sender_token_emp_hits: dict[str, list[tuple[int, int]]] = {}
        target_token_emp_hits: dict[str, list[tuple[int, int]]] = {}
        n_staff = 0

        for s in seeds:
            e14 = EnvV14(tier, s)
            e15 = v15_rt.make_env(tier, s, social_enabled=True)
            day1_empty_14 = {emp for emp, docs in e14._held.items() if not docs}
            day1_empty_15 = {emp for emp, docs in e15._held.items() if not docs}
            if day1_empty_14 != day1_empty_15:
                day1_empty_held_flipped += 1

            st14 = _passive_full_horizon(e14)
            st15 = _passive_full_horizon(e15)
            total_passive_episodes += 2

            if st14["leaks"] != st15["leaks"]:
                leak_seq_diverged += 1
            if st14["logs_sig"] != st15["logs_sig"]:
                log_stream_diverged += 1

            mole = st15["mole"]
            decoy = st15["decoy"]
            ids = st15["ids"]
            n_staff = len(ids)
            wseed_str = str(st15["world_seed"])

            named_counts: Counter[str] = Counter()
            grudge_seen: set[str] = set()
            sender_tok_by_emp: dict[str, set[str]] = {e: set() for e in ids}
            target_tok_by_emp: dict[str, set[str]] = {e: set() for e in ids}

            for d in st15["docs"]:
                if "forwarded_to" in d:
                    misforwards_total += 1
                    blob = json.dumps(d, sort_keys=True)
                    if wseed_str in blob or any(tok in blob.lower() for tok in FORBIDDEN_SECRET_TOKENS):
                        secret_token_leaks += 1

            for m in st15["msgs"]:
                mid = str(m.get("id", ""))
                subj = str(m.get("subject", ""))
                body = str(m.get("body", ""))
                blob_low = f"{subj}\n{body}".lower()
                if re.search(r"\bmole\b", blob_low):
                    mole_word_leaks += 1
                if wseed_str in f"{subj}\n{body}" or any(tok in blob_low for tok in FORBIDDEN_SECRET_TOKENS):
                    secret_token_leaks += 1

                sm = SOCIAL_SUBJECT_RE.match(subj)
                if not sm and "-s" not in mid:
                    continue
                social_msgs_total += 1
                if not sm:
                    continue
                kind, tgt = sm.group(1), sm.group(2)
                snd = str(m.get("sender", ""))
                toks = {w for w in WORD_TOKEN_RE.findall(body.lower()) if w not in STOPWORDS}
                if snd in sender_tok_by_emp:
                    sender_tok_by_emp[snd].update(toks)
                if tgt in target_tok_by_emp:
                    target_tok_by_emp[tgt].update(toks)

                social_target_events += 1
                if tgt == mole:
                    social_target_is_mole += 1
                if decoy is not None and tgt == decoy:
                    social_target_is_decoy += 1
                named_counts[tgt] += 1

                if snd in ids:
                    social_sender_events += 1
                    if snd == mole:
                        social_sender_is_mole += 1

                if kind == "rumour":
                    rumour_target_events += 1
                    if tgt == mole:
                        rumour_target_is_mole += 1
                    if decoy is not None and tgt == decoy:
                        rumour_target_decoy_hit = 1
                        rumour_target_is_decoy += rumour_target_decoy_hit
                elif kind == "unverified accusation":
                    authority_target_events += 1
                    if tgt == mole:
                        authority_target_is_mole += 1
                    if decoy is not None and tgt == decoy:
                        authority_target_is_decoy += 1
                elif kind == "grudge":
                    if tgt in ids:
                        grudge_seen.add(tgt)
                    if snd in ids:
                        grudge_seen.add(snd)

            for g_emp in grudge_seen:
                grudge_participants_total += 1
                if g_emp == mole:
                    grudge_participant_is_mole += 1
                if decoy is not None and g_emp == decoy:
                    grudge_participant_is_decoy += 1

            if named_counts:
                top_emp = max(ids, key=lambda e: (named_counts[e], -ids.index(e)))
                top_named_total += 1
                if top_emp == mole:
                    top_named_is_mole += 1
                if decoy is not None and top_emp == decoy:
                    top_named_is_decoy += 1

            for e in ids:
                is_m = 1 if e == mole else 0
                for tok in sender_tok_by_emp[e]:
                    prev_h, prev_n = sender_token_emp_hits.get(tok, [(0, 0)])[0]
                    sender_token_emp_hits[tok] = [(prev_h + is_m, prev_n + 1)]
                for tok in target_tok_by_emp[e]:
                    prev_h, prev_n = target_token_emp_hits.get(tok, [(0, 0)])[0]
                    target_token_emp_hits[tok] = [(prev_h + is_m, prev_n + 1)]

        prior = 1.0 / n_staff if n_staff else 0.0
        min_support = max(10, len(seeds) // 2)

        def _rank_tokens(tok_map: dict[str, list[tuple[int, int]]]) -> tuple[list[dict[str, Any]], int]:
            rows_out: list[dict[str, Any]] = []
            sig_leaks = 0
            for tok, pairs in tok_map.items():
                hits, tot = pairs[0]
                if tot < min_support:
                    continue
                p_hat = hits / tot
                se = math.sqrt(max(1e-12, p_hat * (1.0 - p_hat)) / tot)
                lower99 = p_hat - 2.576 * se
                if lower99 > prior * 1.25:
                    sig_leaks += 1
                rows_out.append({
                    "token": tok,
                    "mole_hits": hits,
                    "employee_episodes": tot,
                    "p_mole_given_token": round(p_hat, 4),
                    "lift_vs_prior": round(p_hat / prior, 3) if prior > 0 else 0.0,
                })
            rows_out.sort(key=lambda r: (-r["p_mole_given_token"], -r["employee_episodes"], r["token"]))
            return rows_out[:5], sig_leaks

        top_sender_tokens, sig_sender_leaks = _rank_tokens(sender_token_emp_hits)
        top_target_tokens, sig_target_leaks = _rank_tokens(target_token_emp_hits)

        per_tier[tier] = {
            "tier": tier,
            "n_seeds": len(seeds),
            "n_employees": n_staff,
            "prior_mole": round(prior, 6),
            "zero_knob_parity": {
                "checked_seeds": len(parity_seeds),
                "exact_matches": knob_off_exact_matches,
                "all_exact": knob_off_exact_matches == len(parity_seeds),
                "social_no_misforward_stream_matches": social_no_misfwd_stream_matches,
                "social_no_misforward_stream_identical": social_no_misfwd_stream_matches == len(parity_seeds),
            },
            "stream_coupling": {
                "leak_sequence_diverged": rate_ci95(leak_seq_diverged, len(seeds)),
                "access_log_stream_diverged": rate_ci95(log_stream_diverged, len(seeds)),
                "day1_empty_held_changed": rate_ci95(day1_empty_held_flipped, len(seeds)),
            },
            "secret_hygiene": {
                "social_messages_scanned": social_msgs_total,
                "misforwards_scanned": misforwards_total,
                "mole_word_leaks": mole_word_leaks,
                "secret_token_leaks": secret_token_leaks,
                "clean": mole_word_leaks == 0 and secret_token_leaks == 0,
            },
            "social_conditionals": {
                "p_mole_given_social_target": rate_ci95(social_target_is_mole, social_target_events),
                "p_decoy_given_social_target": rate_ci95(social_target_is_decoy, social_target_events),
                "p_mole_given_social_sender": rate_ci95(social_sender_is_mole, social_sender_events),
                "p_mole_given_rumour_target": rate_ci95(rumour_target_is_mole, rumour_target_events),
                "p_decoy_given_rumour_target": rate_ci95(rumour_target_is_decoy, rumour_target_events),
                "p_mole_given_authority_target": rate_ci95(authority_target_is_mole, authority_target_events),
                "p_decoy_given_authority_target": rate_ci95(authority_target_is_decoy, authority_target_events),
                "p_mole_given_grudge_participant": rate_ci95(grudge_participant_is_mole, grudge_participants_total),
                "p_decoy_given_grudge_participant": rate_ci95(grudge_participant_is_decoy, grudge_participants_total),
                "p_mole_given_top_named_social_target": rate_ci95(top_named_is_mole, top_named_total),
                "p_decoy_given_top_named_social_target": rate_ci95(top_named_is_decoy, top_named_total),
            },
            "lexical_token_scan": {
                "min_employee_episode_support": min_support,
                "significant_positive_sender_token_leaks": sig_sender_leaks,
                "significant_positive_target_token_leaks": sig_target_leaks,
                "top_sender_tokens": top_sender_tokens,
                "top_target_tokens": top_target_tokens,
            },
        }

    return {
        "n_passive_scan_episodes": total_passive_episodes,
        "interview_template_audit": audit_interview_template_separability(v15_rt),
        "tiers": per_tier,
    }


def run_differential_audit(
    tiers: list[str],
    seeds: list[int],
    v15_ref: str = "origin/justSilas-v15",
    workers: int = 1,
    repo_root: Path = REPO_ROOT,
    force_embedded: bool = False,
) -> dict[str, Any]:
    from canary import rules as rules_v14

    t0 = time.perf_counter()
    resolved_repo = repo_root.resolve()
    before_git_status = git_status_porcelain(resolved_repo)
    v15_rt = load_v15_runtime(ref=v15_ref, repo_root=resolved_repo, force_embedded=force_embedded)

    sweep_res = run_paired_strategy_sweep(
        tiers=tiers,
        seeds=seeds,
        strategies=list(STRATEGY_NAMES),
        v15_ref=v15_ref,
        workers=workers,
        repo_root=resolved_repo,
        force_embedded=force_embedded,
    )
    lex_res = audit_lexical_and_stream_differentials(tiers=tiers, seeds=seeds, v15_rt=v15_rt)

    v14_hash_after = compute_tier_hash(rules_v14.TIERS, rules_v14.KNOWN_V_MODE)
    after_git_status = git_status_porcelain(resolved_repo)
    elapsed = round(time.perf_counter() - t0, 3)

    return {
        "shallow_checkout_fallback": v15_rt.used_embedded_fallback,
        "v15_available": True,
        "v15_source_mode": v15_rt.source_mode,
        "v14_head_sha": resolve_head_commit(resolved_repo)[:8],
        "v14_tiers_version": rules_v14.TIERS_VERSION,
        "v14_tier_hash": v14_hash_after,
        "v14_tier_hash_preserved": v14_hash_after == EXPECTED_V14_TIER_HASH,
        "v15_commit_sha": v15_rt.commit_sha[:8],
        "v15_commit_full": v15_rt.commit_sha,
        "v15_isolated_namespace": v15_rt.pkg_name,
        "v15_modules_loaded": len(v15_rt.finder.loaded_paths),
        "v15_loaded_sample_paths": v15_rt.finder.loaded_paths[:10],
        "v15_git_show_modules_loaded": len(v15_rt.finder.git_show_paths),
        "v15_git_show_sample_paths": v15_rt.finder.git_show_paths[:10],
        "working_tree_unchanged": (before_git_status == after_git_status) and v15_rt.status_unchanged,
        "llm_api_calls": 0,
        "tiers_tested": tiers,
        "seed_range": [seeds[0], seeds[-1]] if seeds else [],
        "n_seeds": len(seeds),
        "n_strategies": len(STRATEGY_NAMES),
        "strategy_names": list(STRATEGY_NAMES),
        "total_strategy_episodes": sweep_res["n_strategy_episodes"],
        "total_passive_scan_episodes": lex_res["n_passive_scan_episodes"],
        "total_episodes": sweep_res["n_strategy_episodes"] + lex_res["n_passive_scan_episodes"],
        "total_invariant_violations": sweep_res["total_invariant_violations"],
        "elapsed_seconds": elapsed,
        "strategy_sweep": sweep_res,
        "lexical_and_stream_audit": lex_res,
    }


def format_console_summary(report: dict[str, Any]) -> str:
    mode_label = "embedded de9cc50e fallback" if report.get("shallow_checkout_fallback") else "git show"
    lines = [
        f"Paired Differential Sweep: v1.4 ({report['v14_tiers_version']} @ {report['v14_head_sha']}) "
        f"vs v1.5 (v1.5-candidate @ {report['v15_commit_sha']} via {mode_label} -> {report['v15_isolated_namespace']})",
        f"Episodes: {report['total_strategy_episodes']} strategy + {report['total_passive_scan_episodes']} scan "
        f"= {report['total_episodes']} total | Seeds: {report['n_seeds']} ({report['seed_range'][0]}..{report['seed_range'][1]}) "
        f"| Invariant violations: {report['total_invariant_violations']} | Working tree unchanged: {report['working_tree_unchanged']} "
        f"| Time: {report['elapsed_seconds']:.2f}s",
    ]
    for tier in report["tiers_tested"]:
        tdata = report["strategy_sweep"]["tiers"][tier]
        lines.append(f"\n[{tier.upper()} | n_emp={tdata['n_employees']} | prior={tdata['prior_mole']:.4f}]")
        lines.append(
            f"{'strategy':<26} {'v1.4 score':>18} {'v1.5 score':>18} {'delta(v15-v14)':>18} "
            f"{'v14 acc':>8} {'v15 acc':>8} {'v14 dec':>8} {'v15 dec':>8}"
        )
        for sname in report["strategy_names"]:
            srow = tdata["strategies"][sname]
            v14s = srow["v14"]
            v15s = srow["v15"]
            dlt = srow["paired_v15_minus_v14"]
            lines.append(
                f"{sname:<26} "
                f"{v14s['mean_score']:+7.4f}+-{v14s['ci95']:6.4f} "
                f"{v15s['mean_score']:+7.4f}+-{v15s['ci95']:6.4f} "
                f"{dlt['mean_delta_score']:+7.4f}+-{dlt['ci95_delta_score']:6.4f} "
                f"{100.0 * v14s['acc']:6.1f}% "
                f"{100.0 * v15s['acc']:6.1f}% "
                f"{100.0 * v14s['decoy_hit_rate']:6.1f}% "
                f"{100.0 * v15s['decoy_hit_rate']:6.1f}%"
            )
    return "\n".join(lines)


EMBEDDED_V15_ZLIB_B64: dict[str, str] = {
    "canary/__init__.py": (
        "eNolyrEKwkAQRdE+X/GYJt0SW8Ei2troDyzD8pINbmZh3ATy94q291wRuampH2ckbSmjZWKthQGj4XkHbV+82kprmKr/fJwa/bHRD/RXp77+"
        "df4+PVLWUmgzg4h0Me7091ItRlwgQxjCSboPL3AmLg=="
    ),
    "canary/env.py": (
        "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"
    ),
    "canary/forge_track.py": (
        "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"
    ),
    "canary/mole/__init__.py": "",
    "canary/mole/dsl.py": (
        "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"
    ),
    "canary/rules.py": (
        "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"
        "b+vqqu5z9/4PNP8DGQ=="
    ),
    "canary/solver/__init__.py": (
        "eNpTUlIKSk1LLUrNS05VcEqsTC1WKM7PKUstUtDwcHV00XX1C1PQV0gCSehCJDT1lJSUuNKK8nMV9AryczKTKxUycwvyi0oUgsHyAWAxLq74"
        "+MScnPh4BVuFaCVkGaVYLgDOnSbW"
    ),
    "canary/solver/_sim.py": (
        "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"
    ),
    "canary/solver/belief.py": (
        "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"
    ),
    "canary/solver/bench.py": (
        "eNqdV/1u4zYS/99PQagoTtrKPKcfi6tRHeBt02uAYBusc3+5hsBItM2LROpIWVk32YfqK/TJOjOkLNmbtMUaSESR8/mb4cwoiqI3Uhc71u4k"
        "c6bqpGWdY3fCyUpp6ZjRrJQdc1KWjsVWiooVQgt74FJ3/FJ3CZ9MGPz2HbN7zZpDuwOead2TeaH8jrRMp17Ql7MZW02nrZLWMSncIa1lqfZ1"
        "uhO2XONRY03h2Os1yfY/2BVbqVsXDE13cm+Va1WRcs6Jywpdmnpam0q6NbB8xvwO+2F5zXCXNeAg2jCJomiysXCU55t9u7cyz5mqG2NbJrQ2"
        "rWiV0W4y6ffsthHWyf69Fu2uX3sd/ZtDVrTK9TutqqXXVe+rVqFr0jmlt73CG2OqyeSHyx8X/72+zRf/uXx7u2QZiz7y09x1yuxdPuxUZuty"
        "o6tD6q1IXWuaXAoLO6XJwZEdKIomk0kpNyyHEOWVKUQVQ/hS1phKFYcUvHmfw2blsovZbJbMCXVA6MaqTrQSI6sBuLgPfScqjqJko5wpJVOO"
        "/bR49/ZyufyHSzhCiwK8dG6lky3q4y346XLXyCJOUoY7SrvW7gvEOk4S4tLg+YxWDzsFEQMXiLQ0WkJoSiD4bjB4fkwQFJ5inBwICKpF0cYV"
        "AEXad7Aw9hDU4A93UUo88A6Hmn2RsQt6tRISRBM5OAMxjIN8LWqZBGxrcS9zvx9Tns4hFWxK2TZnSrcpe/Xq/iGAS+nAPXmfBksK9w3tEZHa"
        "MJLEsmMyRIPDwaoxV/wWQAp6Rmr4cJ+DqjeL5eX1FQQsZW+uFst89P794vrqzbvF7dXPb/Obn6+vvr+6XJKsokJkj5R8C1El8xJm7JmYs8Pn"
        "ZK7oeD0GGDTECFeG/05wBehjrBYezjRcuRyvdPajqJw8gRVrU+8plCg6gVgIAJIhQj24IykDrEEEbvLSVezkkuckRm4PR/Je7tl57N/5O3rE"
        "m4gKIFWm+SP68CEKiRh8vzzzECmP0jJa9IjAfZfx/8xd8NlzEZrPwJOy+wcwD8i9NliPqsBfgZukH+d1T0ZZduJDfGKK5a4wVuICnlYWtLdR"
        "WlR5KQ4UAIhUmUNXcdAzMMlFUeydLCMmIaYUq95pt69rYdWvMrbmwQXXXQHurN6vvlyzDaTZe7hmDI99VtVwOFRjXkuhY1d4iwsFhxf829fs"
        "1ZimcS20O6Ri/6Qaz93/LdQQSZwJ2hzW7N/swls5475cge2ocF/H71dfnRmE4pCR1kQNCDhv/NdntKiEdqGqYvFDFE6uSZ2C+SnqS1l87iDK"
        "JTtJARm4qYxo40gLDTmXkh2eamxTSC2lVRsbKChWldINnWDRNNWB3UJ8b4QVNQwGPQ2Y7eDJBHsw9t53iUrdWWqgzD1I2Yx6Ahh25Dy7c6Vo"
        "RVEJ54YyZWVTiUKe383j8R76/HAIIEKKmQ6BPCrhqpW1i5P5aJJgnpPfXl2+W67aNV5fryk+PcAkN10PDlwbynAXUtz5mwAPmlay18/UpXSw"
        "JBsVZ28NXErKgRjMFiDso4ubeKfQIT8r4avA1zAJ4TtGwBvis+RBtTsaKWIyK2UYUwUx+VXajALst7DdZUOsU0hv4aBzmmrcY3w3NRWvRRPn"
        "5AGaDSm42+t7B0Kzf/mMNnusg48fJn0wLGX0OM5AwmEYADAFdtHYrmaAsV1drCEvV+uEi6aBihDbk7LyeD8fXf/Og3KfMh9oEBlC/OHYMZSO"
        "wbuOEA9YiwaM66c4vrDbfQ0I3uCbjZNAwkVZ5iKcxVEYV6OUtYdGZtTDg+0ZjLAvclGsooE2Oh9xoxdZfVxHvKdT4Yt8FOpnDX39Is94Wo6w"
        "nuCNzSKckmQOY5l82cx2B3HdmarsVVKNGZT6yv0C8x2EC+bwT2EtPp1Vfzor3A611dHfpO5Kaxp3Ro33xSiY+7NVZFBUZDabaP2niTd7Np59"
        "2mE6N5zSGTkdZbw/o46Pt6Y7uSqlgnH4GLlM8OM6ZXdyJ/DbwuYeJjgNYUpPCudzP+/ZwBiClEL3qqS4Hw50f+ABhR2/+GsVMBTkXU7AEpw0"
        "GnOPNPZJ2qNmd9zFcQKQTvrqgCzduKf6QtXOACv8QuP4L1SCkyqPQHPa4a6poD1GaQTlSnB/PNqcDCXzmV4B120rY8EptMhPC/ZFWDmSGUq2"
        "4KNO4MYTfWMVZsgT2ciewgfCE00f9B/nJ1jR7AXP33/79pvP4YkT19Mv+mk6nb74Fzw47TnzkwYrtkP3OW2p46kEEmojqKs639y2yfqE2Hux"
        "ATce2w9g3aPY+kdRzPnF57TeiDmf+WU9519taFWo47IESlxFY2A20WcgcgjntJ0RmYuwi0MK5Dl+tMHHPuZHnmOvyPPwVUWNI5n8AdFfapA="
    ),
    "canary/solver/params.py": (
        "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"
        "h9WJDP8Bq7pv7Q=="
    ),
    "canary/solver/policy.py": (
        "eNrNPWtz20aS3/UrZpFLBXBIWrLjvQ0TucobO7nUeW2VnVXqisvDQsSQhAUCNABS0nr136+75z0YUJLjD5dKWSQwj56efnfPMIqi93W5581Z"
        "XRaLmynr1pw1fMkbXi04K6o9b7tilXV1M2G/ZeVly7qaGl3VTZmzt29e/w/bFxk8rUu2yMqyZfG6aKH9DauX7H3Ht20yOTp6mRXlDSvrejs9"
        "Yqztsm7XsvFzVkLbNK8Xuw2vOnqyWPPFZVry7DJdcp7jo4ZneZotFrxt07JetfENQMWbPLtJYDBocMHLgi/ZbptnHccH0HjXAvxLdhZvsuuE"
        "PT8FqBvermuAOq4bVmZtx8wI2zKrunSRVRkAHm9rHL+om/FFBi8WAMY+awpowlZNvYMl0ST5Ht+lMAp+lYuKz1ne1Ft2CouDRSRHURQdLZt6"
        "w9J0uet2DU9TVmy2ddOxrKpq6FXUVXt0JJ81XH/cZN1adO1utkW1Ut1eVDdH4vlk0uxK3qoXv/366t37EfutgA3NmmzTqlbQ37TCTZEvJOLk"
        "i5f1YsR+BqT/2vHNiL29aHmzF+CNmMbJ0dHrF3999fo9O2XRi7/+9PLVz7/8V3R0dJTDQALv6T4rdzzeTtmyrLNuxM71pzPCHH1BQmAMsPPq"
        "essXHeC4XdQNR7KhYXDBbb3hdQXUVnRrAwHbsqq+YvH+ePJ0yq6aGlqeir8pdSWYUxoumSD+caaGA/Ir6PuInbNvWXzCxmybwLcVhz3omvhs"
        "xKLwINGIHU+OE7nItAD0tDHQWjZlebGAZT265DdtIlYERFcA8EAOQBzUakRkLl9boOA7eraENV0CtzEcxjSDkegptgNayf1xZ5fz3tDe8NBE"
        "z7BXY01of9o4caayBt8fGnZvY3M2l0jpgOZSJKoUR2l2C8RebH2eAoM0iWCUhv2bvYF9FeOXsJenzG7LANooSibwhjdxolfQ4QriaJ01OWxJ"
        "tOF5sdvgJ561N5G7nGWEIE3Zp+42wm44CwwhHp/2nv4jgkf/iGgd6k1w+Z29fFwEICB9//anX1+8Tt+9goU0fLKoN9ui5HET/W/c7Db1rvn3"
        "DkRpUywLIHNDXf9eNbt8xZMpi/k/8m+T/4iQxhYgm1rmyGWas8o2HJmupTfAcviQCBJwXnRpGre8XAKnEutPLTEA6DZIhyHwz8gIRMmd3ntn"
        "8fTfBV9n+wJWkwIDbBG5ot8pcMefRyC56wLEYf/dsxHwK0n00Lv+PBVMn5KgnbILVCyn7LdmBxCTIkAN4D3PeVusBIUhgrJdV0eBcRc14C1b"
        "ceje7bYlrjQ+npwgc588w3+f0L/f4T/P6ON/jtgJMP6IZSWIngq0i57556xsYeosz7Zdse8933VFWXQ3GqZNEYJo29QXIOf8zviYgzaC9RcV"
        "4uk79Yxfd02mnp7oliCjTNNDG3fFi9W6C284EGaXXiBBdvYOPR2BIrpG3ZgXqF9bPf1T2PSuqG7c3ehPTyohRa2oNs6beFlUeZrzRX3nUJtd"
        "2RUaqR9qgAT4n54GIPz+zwL2LYc3iGaNzU1RpausqOyFnoTmk+3SZdG0DlqO1bSBnbYkEbLkJF0BhVTwUrCm+9LYJZaNopt8Fdi87e4CpALQ"
        "ZJGBvfHzu7+w9oqDocWKLvmB8estIBUWCnJUGE1jYJnHsHTQ5gW/AtF+CWp/Xde5B4nP3wBQ7xFIVh8g0BxiOzkQb++tO4UjI2B857vb1BEZ"
        "0NT57jdVAoPaqS9uIy08SEbLz24TIUfgvfjgga6kB4KtPrtNtJSAJvqz10TKC2whP7oNJDnBe/nJ6695FEcwX4BQrrKmQqPJEFRdgdEdt0AU"
        "b16dv3oH2M4qXAAa8ID5liOFoCLyQDD8imCYb24zw7XQynzxqBvkAxI2/HFfuDIFmngPYEE5BxQCB4IpAuQO4hBJWjdh7RbQ0zKkDpgYzBdr"
        "HV+x/cnkOxaTRV/wFkRAQ4b6c3YC6lZKDpiVw0beMGn4g+mJqMF2Ej2rBsxhdF0ubujVBiz4rAQ5AubIJuvcKS94B3xYiYZArWSz4ReajdW7"
        "DgwDMnBfvH6NX9HcQsHEFJjgeghRBStFg71alLucg4LeFlvgWdxea75dldPaS3BjfgC7gH+MaCdAUqkVZTgI4gKkOOkOMbC/LAngxQcwxIEi"
        "YbB6ucTBTh4DMibWnD/Vu6obw15swZKJfcFLmyHmEQA48je4ZNiNCjcByLcsx4uyXlxOPErBSUbWZ2vCkSEmOYl6IgU3Epbo3+/q9FIdAnOn"
        "hifd74QRFPgsBk4HrxDtVhh1Cw+48mrgu3FdEm94R73g+O4DHF6SKvLyVJHnN623zWVbAxp5jrwN4niTAdchSO500twYmW9kZTjfaffcFuiV"
        "nTLd2erndDGtfcHb8i6ega8SoX0rsDb+g/8xYRmzF2e/ajtYTCSMYAxItGkLezAlX2aGjhqAEPRIjC+igba9kVO7l26GusbS7gOuFCIXZnFd"
        "CexKvvpsO7f7bZUqdZsLX13YDspXF996HldvmoF2trfl0eSZ5zlIS83TpvUFymw7RBB743zc8R2XyCdzewYzjshhns+h72zutm85mUjH7tPz"
        "dIu2rWevglHuNQs9BHromgKZELaadzj/nDat82HdrrNW+FZd1nSR91KICBkdEi6/a8H2uSz8BrVvIwYQyADORog+3fZRkW5a9HNaUvQBkAG9"
        "pNhyJJfhZih57BkJkaE5gYUX3OYV2iLiVRDqY9SJMlrUVtkW7AtQvTE65Q0HbdI9zvnFbpUYpxQMC8mKMh4ox8bo05y4ziMK8elFdTOfW468"
        "oPauAL0Juiw15mR3DACmHexOswShs0Pz1lp819wE3XfBsQicBMt0ARMGVJDXLe9C07AxzO+002oIbTIClyyaWAWXBCoiu4WMKsHqu8QZCyQB"
        "TPvcN/imPfdEYgcM2ZVtGaj/5PMJ9H0NHwHwSNDwRIYQkom0GeOoxUgIogX08deTJ8sW5pempfgK7Ac6bMu+xtBL3o186Eas5JVGqkUI6Rei"
        "hKUzAfvRsMqUqLTZVRVHciQe5vlj4P3NBhSwnrXh4wLt305I1HbRZN1i7aDtjDSEkuxno54y6G+6UW/QLOm/P4PRzgyRAce0FMeSYM3MMubT"
        "fu9UQBy3XRIUlzZObFxVdWeL4cDAGPK2GMbmD+oDomMbH385hS0WolAoAqlybUQcKKeQJOw4KW5EhxgGswuNK0toUVAUPDmk7jjCb1HiNakv"
        "TYP6EsgWgwpmxbXaZtBlPurqy5D0sFsBXJT0OAWtQVkM8EvL+obzNnK7wnMkKCtqjAFL3dilmHqi36D85bOoyKO5Z1NwwSaJcLg50RQma2iq"
        "uS9KJBEGLQuKtkkqsqZOeo00JYOBGpPpooPII4xan5bZ5iLPGOxhdtHG3aQy+ABhWSVmSFAiLvZE4sTDGuobtLs6wpja5BvYxBp6YuLGBRIN"
        "ANJtVvtzlFT6G8EbSY4+T5IkyMrSYJDK1PQ2r2CI2ZxIDf4EkS2tCVgaat9U5okicgeNUYM7gqRGdgS+iimRBP4pPYbtrCfgDrU8R8e1nYb3"
        "JKUmquuInT8IpIFBtTmEGPfok5CPIZLspo9AsbBTY5OdD2+7m/rzQEGSzhEHLtuY5uJLGyX9JewzlBu52nXK2/l8Fsh5ZI1iK9wMHAT/gkUQ"
        "BzIjJqECDTUrBIAxAH1C6yq7oJ7wF/zxVvUXa0wsRm5vUeZ+gna8nIIcQMa+RVX5CT7SOLy8Da0oYLHSOiQ6ilY+jMQykdIAgjDc26xtey/q"
        "CeJ9ls8Q/ylKJ7QUX9aL2Ho0Epw7IwKag4gAhfsvXhFLKX5aFNtCbiUwUjIKghD+D2PEcX9FidhA3MpkeHdRaD5gLrFemstZIK44QhPOXhxI"
        "lYmiuAMSz8txe7RfTyjxDeJf5WJjxOb1LGp3zRKsdBIIhNZrG6Jrh+KjJBlYJVLZdZ+36AvyFYEEfxE+4Jv58Dr8xHxfhrdSkDbo+tAyoH/W"
        "rFoiDXJLaSG9N10Nz9m3IA2TnmDgQjhqBTMNEKmEiiz2FoylDgyODKwIVJ4z2LPjeTLcCwGfcaRr5xHhF/ofI2CoMvFhH7wAboHO0VkjrCKe"
        "4K8Ylwcl2MKeub8E2HW1dtz3oeUsZifIBZIssiV4Lum63jUwpbAcjufsW3CbD2hmnjWLdboBMDDY7W3vR7LOGrVvYhp0S1FLR1Fg4zZ9zOix"
        "A2gAaDaSyXOAuah87zhI4Iu66opqx8OqTXeeZHkeW8MHbJ4KmVA2aTkGWwNapN2gcacTwOADgk8RI15Uzx2FVYV1GoUmQqxvpipq/WxsQtwi"
        "efw423Xruim6m8ciYTxlmzrnZQlSgl+De1XeIHKEew6+3aLISuTHsrgMYuiyoJV9isTw0ZSpT7AhwUQ1NtFAYCsBBz6Wn25nLawXsy7xSTI/"
        "CktSAdoEg8dVHscIxwjRDP+ozk+SAbk1uK2IvSr3RALimuz4Q1LCjcvMYJS5sl3oCe0fgUccf9K3d+wgDBHUx4BVmYq6JJEdiQ+oBbsIyeO1"
        "RZGTzaXMUdEoJb5AU8nYyEIduGBk7Up4UkK+glovVhXaUVHYW+jZpwN2omg3Vt7yREK1ABNzoIO2DbGnPzcscjpkb8A7ZWfAR+0F2MoXVpmM"
        "VEUA2gH44AC6rfqtKOAgayPYsZh9mMHJcEp0ImOyuy8ehFhp1Sv3Z2aPSuaU9nRmAMA8SQ7tj2WO+/1CzBTZoE8HOFl5AQZCAdohW0E4UNJe"
        "CGHc+FjES45e0Qrv0I7uqofNkhftIms+ZyadTfdnKFZSKxqWRGbLSscXzar2ijdSTbp1TgbHeo5WS0zNwrb+j/g+a4s9p02DyZzgmyAkEWHJ"
        "qQACfMSUjAEZVbcUryhcdHhbNYZPksk1ipHNdV71ERlEHoKTXs7A9mhpk3MnagUqAJZJYDxW85GZnGcbsBKojvMksKc4smzXHxdtnTv7KFLI"
        "JfJevPnl1bv097fvXmKhYxxtwVKtSRUCwpusaDm5oBzzH/TxAqNn9a6j93zR7MDMoR1e1VmJIoSsvqq+qHNMy17SV9IMmA3d3LDFPrI3zlEa"
        "CLC1T1EUnYkaEJF+LypZsSsThPTwCnQ1KEJYGKjoqkNjQRlbbrFdi2Z6W5tKSSsOFsvAj5ZgZxMaPVEK1sprHAqYgf1/KaIqNcZmY0vJSufX"
        "CSNd7qcsHl/uZydA3/Dn2BZxXb0dseoEY3s0KrzV76on5vHJHP5XcWPxLMH8vzR+naWeIGU9FS6x/PyI4vcnMNWTZIB8VPEDQGR2jh6m0jIQ"
        "O6cqnft5sGkY4VZpRRDzHgR2JMl+K6T0j+xJMBViJeCgIUZDZ1dkpl9pU9vmAgDwSkWmesbPfDZ9OvdjybO450GMwOoULsKUXd0mZjqEYG6Q"
        "qLLnKVApT88NGq3SYckJ72V++rd3f3/Fzifsd6wVxooH9s1lVV9V7PwbwKr0nKkmu6VkOlAcmOaY9uqIa3TCXsgaVi/1LKJTt846tiZRDK0u"
        "dvhlzwUXqOFveOezEeFKFtCkDd9zNM5xwDgZzlCZuNnZyASqVT7CDlijYhAFaUe94NmBACJ1A+/vbLIlaIDc290mPhGdscKFIcGV4IqLGq2W"
        "0lJgBsPL5zoIC2Iauctr2ssqICdRyZy0RMbMkeswOcJjib8gvjQRYPzHoQHY7idTVYF/jvyAO4q0w85h0pplIOU2nLKYpF3EuC08p8VjkQvR"
        "zFT01pSjJ4mplsolo4SGVgPAYECHJQjtqpuwF7uuHmMBE5EU5ZtkAv+xXU0QJBa7/mrQVrSpJVSihfuImUdRMr1PaUUprgIVz7rIueCtPX4V"
        "L/fitUeWAJWdxEQixC8jUawacNslZPRav9wXGAryBwK44EVxQeU0AAguMxkqSi9aUUsh4rMw3p/AEMM1REHMuPN315jIjXu1HYFKczl1LLDC"
        "9mRXYX9sSzS1x20BFOa8cl5iQVZnCxH1tu/VNGgLdIxWX3IGCrookWg1jamuyT0WJ3UHtBZRhKIag72CBjCdnACrBHDmlr4ss7JkF9niUh3o"
        "kUWl4jzJssxWgRKUico4U6sQXAiG2mRqBHv832/e/v4mPU//9vblq0iRjS8h0G37YqlGdKR1rRyKExEaMQLEr4eYHoVNw67YYBxdEMLpIVHu"
        "r0dXfMVqxJErw/3K2lGgQHYUqIRNbEuD4oGpLvgcVJMSqE/ioMQUtMX35vyE+krHKvDLX57ditCHMDvw3AGWKnxvm6eUPfbM0qGEqpeBEjU2"
        "hzzuXtrJZKXRSon9hCtYFbcgjGOVSqTv87sSuPfOi/mz/4FZ+rGGj9aK7PTWJxMgnypLVPndY/Y0GTEVJ5+q57ehJErcyzYE4P6IpoAsgbat"
        "13Ay0VRSa+O0Vyf+nB3TWwXyc99vo2m1Y9tPJXgYMEs/CawcH9+GMrpq1z4eoja+AG0YPXAjRSfPqKrbTvGAFDkBmGSrrR8lu+CiBBT2Gt8J"
        "hwg/ITO64wDHq3lMtbcC0npi+QXk9Mgt9sWGOzgdjTw1O6fDexXZkf0FUemY2spPgsZNgI44KxI1aLSw5Nadj++plN0+OQitZoiOuZSAvjuQ"
        "KGHaI1AYTJGeNYw8/8nkwc9kIOxm8biAh6hQx1qmtEW3gfC2Ry46O2KKaEWdfSsQ0EuMFCOK0WLmtwIJ0IARKaQvitlUlUqLzslBPnJiyMRD"
        "9QLUGLj/AP4y+msNQp5t+KYGOzhbduyTkh0RnolcRiz+VGCs+zaJyP4SdAMm0kPys8wOMU9xaT5zksDxRCkKcDsmG5BT9+ZpMQ7o7oNs/RWZ"
        "QWgFHQ3SQR8grQTdnZWH74L1lveKAIAr8E6GztAylfXWDHNJQA+rm3EB5iVuM2A1Aawyq1yFjhuAmECGZxW/Yhg0J/ekxoPcYOA5ziyYhVVe"
        "X1GGHz07dGVJVqzpAIlwan7QOZeciUPN5FYBjV7TsQR5WFzDQAkcU7v/25qrilHKVsnSdJWwinGKDG1frF3FQ7/2WO0OS7c7rGjq8JBAKDZl"
        "l7TfFeCoR+zMsk6U+DhytPC8L++plHfQB1s1VN4N5ozD7L5MsiUpNf5Wub9iG0iswkO/Cj/A6JJt+oFuT1DxW6uaRMbcAFoqi+A6gmMQPh8o"
        "BAqVMlsY/ngUWOaP7CkKWqP5leYwbr+97rFvGfTGzkpxYEquI7Yq3kiXYuU8ino+RzODj5+6wUQ+ZWP53gghMLRGTEaOKDLhhk9ocJrXy8Pt"
        "NrgFcjj3FQ7m5NNVWgv6PMdZvn/W39ELMHwuw0FAmU1r1zcxBf1ogh9P/aMZyfTOncEQDS0mwf53oZuoekMMMerFlYYQg7l6scpnpGVhRqK3"
        "56feYZO7UCAhUBqNu3ojiH0xNyK4x54Yc2i2s+n4ZI5gwedwrX5s0ogItqkyDMQ0H8J6MJilMKwdHY5lvVfiPltVNZ18a8GJX6ynIizd8NWu"
        "zBoZk9QBqat1AaIUDHBzluyKYzxKSlmjvkXZlzo5REevsBFG55/L00N0dm1fFzlMsAEN+Rg1ijmjxierCXv5/jU0BKfFVHK5UjroDUoMqMog"
        "wdD5BOWEFbWkiitVVEdxx4ku8+pVOdtDYsyruomtmq2im4iUeCLdEcom66dzM7AwxGThJTpK94m8wG4go0A3vzdZT2oasyxddXcAEp9D6OqH"
        "bmJXf4HURD9BJwbs4CuwgoWT2fG8F5inhAhfEXc+teyZLJdWDFhsthGDB2cOmjZuU4ecf0HZTQdOBZbBuKAzl+iT4N0szKKfH/Dw7ljq/pZO"
        "JVLXEg8SA9eNN3gzAhU/hgwChDq0ZfBcP6YRnNMvxKsjRiFvaKnyUe5I2G1Wzsk9awVlleL4BuhtXx4RuLJWGpsLbaQ6WgXoO2ylSxX6clYH"
        "owaKWEiZq2JhCvLl5oF/BKofg9x1ositdM5pS6TBW5syGvAh8NzYnVbuECkok0ofgNaxA0fP6acmf/U1e4Iu9/Fw/FsR7kTDmaqLe4TPJCBO"
        "esCoA9/gMagOEQqR2H9LV0po3tXlLg1f7soU5WVyCLowUEeHG4vUmWza3wn1/tCGjBg0W++Wy9K6teHPd3HsWYFRYcOxxpdDmVNsCrqa5yyW"
        "r0UqhF2z+JeiKhgdusXj8WIIjldCiXPVRvN2RVmO1aFgfRB4wt423bpe1VVWopjwG4BDr09BO2efcV8sDUObMhZK7ApzMjEpMd7Iy5tEnkao"
        "vI24cajjlediyDg3jFxv6ORZc++MHJ46OaOzYKoU+OjQWQukt5OerTu7y8j97iC3zx9q/tnHAZVNAWLSaDBfv936GchZfl8VLgvSFXbkVzmP"
        "Wo8Eoie1ZGPhTpnwX9ChOjFoIPMLiDHFeNcAt5JvHhvAVL1vNI4SszaRqbTHXQFJxiDil77ScBWNI9qJYXuL28xwGIBvritP5YNBZWPBfzI5"
        "xjKd3Sbes0dsb84obMwJBWPlp+LKEQJeYSaxQiM6H25bnOSwkx1D9zGpiw5ivPGIC8Gk31CgQRglZtwrOpJ/B60gDfTp5R57bhWCCMsMkaHY"
        "xslw48wIi/KH84llh7jbhHeEBcjrsYrKI3t98mxYaHgrODvxQaJe6HHid/dt2spzIp8HqCG1hm5ES5vJOxJg8VIWjE51uG/6ScghMnRvrXpR"
        "DHGO6N8dke+Ije2D1csmW+jzkf1rULSW1zeh2EmAsCZXQxJWEnGWs77YtV0F3tWUXRSWCqAq8rrkshpjS3cVAn5AEdyM2zVI9lyQZwz+iU3N"
        "L527RH56+/c3v9GNIrF/+UQyZcviGoYxVdh1k2MuDuZDh8e7qGTiihj93Lcgv6I7UMbK7aryFV7nZV2dIS50iE/GTyyTmC7UUHcP1sIa7uqt"
        "io+1vUnWYMu5OlBcwzMSp5kEU2JGr7W4F90mAk9oyEQF6SbB9A9d+dQTXZ0oHRQeHWkbPwgTqyjMiPFAxSpuLd0wVDHkqicDh6n0OQJxpARa"
        "XtIxkelgfBqwKWq0ZlPoiaUmzXywsSoX4ws8YiybTw/Gvgcr09V/NwUHUYt8LW5OnBXs8WMCQwX/uRv6x9n7emOJjYhZpkHkdQYrxuwbwAuR"
        "9B37pYNmiJSOGFdkA0C6TNpsg8pSdjQWRrh4HxYUDimFj/YgcNNDW0ShpiWGDvn4e6JsmOHwLvWjTB6AAxGnO6NPzlnalXT7LkeajMLDCb9Q"
        "GqSAF0AKaii8X2U2E3SRWvu5GjhToXF2cP0KKj2Ys9XFlJGbOivmIxm4Q6jga5IM40I2Ws3vgzccfTW/C3t9PtEM4uXG1C2sJs52e+S4z1XK"
        "waAIZNVsAd0vdBLddNDSu/fuHpHLnVaNwqndFDKXC4CMpI6Hv4mp9VJXC4mb4wSD9cLt0Ho3fIL7SipP4AdixHaFdXliEtdLFcOfBBiQqjt/"
        "7OnmO2XcFi/ru4Lp4isQw65JYyMF2j1iMRmblkawLHJCkW1xJ3jLxsq1SjUungsLJbAljvlCWN/5jja+7QVlYaeMK93fr2Dp6d96t4Gpi6D8"
        "q8C+aVmBeTvcanErGOymmBleyZvBTLHh1bpYrEWgSwZ6sY5LRcNMAm8kyrArRJ/wiIXf3lP/jnOrM2Em/3UlDVNKhXwmKQnTvm8pG0exdh2i"
        "NVBVqHYVb8BUNm04HEd3JYWpNUipeO761BBYj6DwvbrFkCqSw2N/9IANny4QPrE4FuEU2Go2cVyA1DpXGpC3OCdeVSzuKxbDgkfyCNHtFZ/M"
        "ohRpIZpTdYk4aSKeGO8RuRBH+tjDwUdMoQRWUs8AO9aQdHbdGu5jr4vY1/GpmO0jVdJ360lZr+KP2CuWENgv5BOC40ddow+zGDjXAMNYebe6"
        "4946iw8Q2m4klYL0wmxrmIkg/GLlhnjVIF7BhM5QaXwVuphQ3pJAoTunluN+5QJumM6N0/19i1Gy3g2HJlwnnfSaqpupLJ6u82MxXnLcIo1j"
        "yXMihJFJzes5ZibsS37wnAoKeNaUBV60s6tawCms6kbKNrz//eYuSbPY5soJFse+7eu3/cUA4Z7YTIHZVOyPLKEOOtCVfKQ/6c5C9fgzQ7sH"
        "o7rqlj43Uhuo6ZExDNEeU7eHgR6soZ7RCHSIRYxFbDHzEs/iqspT1frAwSfTNHzw04CFl0kG3Iz7IsBHwnTALfDrNO5cUzCr+P83rCrWcX8V"
        "eUXBiy8VIIMZ5vcLMNG0DwoxyaivvEvKvnDELRxtdxdyToXnOzbATPEvGcCDIUwAk/bVvulPj78H9fovZUDsRRD5QtkPt06YBoMnZNwENy0m"
        "408exBX2U6ysITQGR4hYK2Imas6oPV3WSbbkDrSkOGTDZmI6gcoMARNkMVcGgBUepTQ+TiaaYBAChIcHpojupSJJkaZxJPIUUXLfeJ/4Jqe4"
        "9U6Luya0uKF77PsMB50siTrjakmbWgQLGnRy5dzhWx98N8y/3vvo/g7+7vN2xryDPQ/s0/2ckTsdEjkEVf5a9qdoPRaU9aM6tqKvtEUtKOSj"
        "Kep1L45N7uOrijGU+45zenQg6JqAOQrLNeucseQTYdZUWBUiTxtX9HfAg/rJdlW2mHiUd4pTQaCUbvTrHzSkHRmN8UQXDolb16rbL+St4242"
        "zz2F9kx5OGLIx7Y7PuTjWAcffFEXOuEpfhVE/uYJXvLpWm5vg1c/2wcJR/TTJ/psmUiZMir7w6sbc/zJCGPojXSQl26kcU2wO7KVd+vOh+YD"
        "Ac3KxBs8FyhKHyzFr1WRjEh6Ss8JWF1jLPl6QtXl16q8JxDMwUq64bSjuDjDKtBR67ynT6lqmLQmvTbxulwAJ1RyqNqTKO7a1tY0wLcCec/7"
        "5WfqXlCcNOinAUZ1FTiVlFgrDSkzR8kLrUaA9X1jJI5dlzhRMfWLCneImVAtiRHEBysXYM/a6WGeUmLZv1F3QNb8GiNP/9C/jV3XOiAb/hMn"
        "/ifdNoShnAl7axpqiXQqAjEUn6FEFAVpLDOPgjV4O33DN5moWEDs6njND+6kmS54xvMYLRPpVPm7RzxbrFkN7cWNdPSssIoKDudnUaWQGMlI"
        "kMSB4BAWXlm15Uz8WoUKXTnSRMYy9JEQ8d28/iCvR3biPFugmNDzz4//rDnlrmdxAYQyO55TUmlBtwUsZk/miQobL3rB39aUQC+c0jhLaODo"
        "gUDIh1lMefntB4qDxFZOPmQXbIFPceVO44GL9qCZGvx+wud3P5HsRJGwlhzE0hpQQZhY032z3I+kApVd1ORtEHxbL8cgcUjxnishHdQ44dCY"
        "0KoyEu1EvX6niFXv9JDEFCAGzFyK+0wG4s93hpTEpF5MST7rm23Vddd3gtWaQdPgZfZEIoShMEgwhrnJSnZ5ZAAZSJ0MB9oGxqV4mdiGZJTI"
        "WUJr0rtZeeeN77kmoG9oZRE49VEU3gRJvLFpXLc/QORqhuYoGHpInXQI/pCCOND8KpXieub8msJ8qn/5Y7ys8cBWzuKG5CVKL3N/GdiyTRIs"
        "0MP6EFxAv0DmHuHGDw8PNwpj2XhGTs6h5x8FC/ieuDfBvPR+JUVVLfhxwKxyfpkDa3asn/KQPwSyoEI514K0xH2wqI3Qji6470VZBwZuj/5w"
        "nUAjjkfaERwcy66BRUhck3KLFzZhRUHckB8GPWivaLA/UVWAMPJjvFXGNyLvUZLwsHIEUYqAQN1Vi2DXIQAz3FmI8AdrDL4Cw0TXXoof1pkq"
        "M0b8RI4wdsSPLIEpREwmt1n91EvOofOGby4wukxXOY3pdJZ7J4WhD/+0hsyFD5XMdXXg8IjoZd+OmdlJRLpbdiBDvaQzNXu5vxHqNbqYsyxD"
        "l1GS5/5BlkQdB+lg5Ry2ogz1dGhzxcQo5mhesuxW9H0cDe/ywVIT69CJTM0PDwSrEbXfklo+sK/Z5XBVzIf+wSY7CIpZwuABb0OZdg2+LmZx"
        "i8j6vHffihZVzSLlwefXqtxZp3KfGpWH16cM16bcXZdysCblfvUoX6AW5e46lC9dg3Lf+pN71J58gboTtzRf1/l/9mkJPAeGUlgmLvSRGDAB"
        "aowI2opYiOZSncBtWfwtXfcCRF8sYIhv9Gmvb2R9n+OoMv0bx+YHdumsykNsgIce0TycZhk+bH7Xsc6HV7tXmu5JcdPNP/6PCiKs1rDP2aW8"
        "QfnSP1dkeIdGPXKpVcYz6B/K52KPEIcJMpvf6+Slz1ii72dy111cdYCb0HmWuAQETekH/PCqLTQr1zzbF3iAi2xOaUVkogQ10uQZyRfxkl+h"
        "fWYFe0+fq6oWikm4QMlrK9EfPowEb+mBldOPnuB4PTv+c8XD/wHcI/wV"
    ),
    "canary/solver/regret.py": (
        "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"
    ),
    "canary/solver/sweep.py": (
        "eNp1VE1r20AQvetXDAvFEsgbk0APBh1CG1p6SAsJvRgh1tLI3kTaVfdDxTj+751dyS6BWCfN6M3M2zdvxRj7Ijq5NcJJrcD+RRwg/f5w/3X5"
        "8PgbbmArDmiXVncjmoyDH8F4BcPB7Qm+7KEWSpgDnwB8qt8slxaxsXC7WpWMsaQ1uoeqar3zBqsKZD9o40AopV0cbJPknDO7QRiL5/jFapVM"
        "DfgWVb0/FxONJLn/9vD4/AQFbNjEgOXA9uiNtE7WIdDbUWpvq3fJTu9spVV3CIERqtF9eLNODxUKQ/kySZIGW8BRdF44TJ1Ek4Mec4hHy2Ew"
        "urbZOgF6DFriQIzSTcCVOUzEcqDmO0xjSTbXhC5ojGzQFscAX1PilM2NSCEFR7GGRtYutbU2WBjtVZPSkM1MQ2TlZkVT7qinqOuPAbcRkEGr"
        "DQiQauZ0mk/WC6nSmb8YiP5ZeX5vdr5H5X6FyKTZDOGiaSoxf0vZvGPSzR0GLKRyOVBf4TtX0N6vVkUNPqz6fLUmHIr9B7IeG+l7dhW/I3UJ"
        "b/CPlwab4tl4zGGP3VCwH08/H6EjK4BuL5uIattzwyDGwKMYoa2dJQhC6jEoGUzJOy0amwoehs06xhVS9cU1gk/7OL6uwfmhw3TMQLYgrVTW"
        "CVVTIo9sMsDOIoxxymsOcY4euXTYE4ET7ZTPzhN88t5lZDTf5QaU9BZsQx4+AwZDQqeRdeP7waZ6JOewt2B6YPxFkxVadnw9Fcdxs4jVi3LN"
        "79rTTUiQxUK4+nRi7+iZM7ssv4yanpa9QbhxNxOn4mg2i8sNXJSXGfSDsUEPO52+JU1dulBCLbI1v21PRLDtvN3HDWbkXMJWlRJ9+IsUBbCq"
        "Cj6uKjYtYDJ18g+oj4nW"
    ),
    "canary/text/__init__.py": (
        "eNqFU8FOGzEQve9XjNxDE3WzuQeIRCGlkRBFaUCqqgoce7IxeO2Vx0m6Lf33jp0FQS/1xTvr8czze2+EEEv8Ga+D3xmNYQJxGxzB9c3Hy/kZ"
        "aNnBWqpI8AEaVBvpjAIytZMWrFyhJTAueggoraHIh8o3rXQdRC5aFcWXvUtFP89Oz0ezq1sYoKuNw/Rv74PVo5Q3rOACG+MMrKR6RKdhb4Jx"
        "dX/v9GJ2tfwKA2ubUdvjpCEXn18tZxeL+fIbLG4uZxN4OQSHOwyMSqHZIcQNQuMtvme0Gl00satg7tptBEMg4Xq7skady+5TfqpfPaCKxQCb"
        "1voOkUoIfJu3NiXSBjVorziWDPUtG2rjCR2sutwU3Q7WwTc5CNtcA6u6Kpg0DDuD+zvpaI/hROBOEmMVT0J532KQMUUlaFS+u2u81ydCujp0"
        "gtla9rX5kB9EPQY6Sn2KZxbAO9sxBy4zwmxrSjdlfvQ+7Y185Ms99UkIILlmujyDRvyFsPYBHraaFWPMBfBSVhLBa8cM+CN65e1wkjPScrLB"
        "CVAM8P/1DkRMTMuIAp5A1BnO5LjxGu1UvNTUuE52vGuQSNZIA0K7Lg/uHMJoCsmA37VR8QfX/G10mdJLSKZ1aEugzESZXGFawzZgMWibtS5h"
        "5XX3502vfyV63Y9V7L2RX1kyZa1R/fdBjBxkXLwXxZlUG07WMspxNj6Nj6PBMB0fE6KeVnleHsi7o8w4QvpNaZwaEyM7bpvQvymQ88ZVcZ90"
        "PIwTD+7iy+38fLY4OfB4z8+t0SU/sdRZ42dR+xZHL4PNoxCQ+6SoRl0VQojiL/iAY3U="
    ),
    "canary/text/build.py": (
        "eNqFVk1v2zgQvetXELysVMiK26NRB1ggRtE9LIqmewoCgpXGNmOJFEjKjpHmv+8MSVlys8EaMCyR8/HmcebRnPNvFizoBiw7Gds2zMOzX7H+"
        "7PdGs0XHaqmlPVe0XP0cFFosFr01R0UuHrq+lR5+7aBTWj2sOtNA+4gmDqBx7GlodvCrgeOnJXtYLLxCH9m2j1l2Z9UR3Bgd9LHa6CM7Kb9n"
        "RrdnJpuj1DWIRuKzbpiF2liMCEewZ4arfzjWgXNyh1GU9ib7bAZ/e/OZcuAP5b+NqJ8cVpI3sJVD6xlardDfy5tQr7sJGNnW2IiWBeTllQkW"
        "wIzfgz0pB0WVcc6zrTUdE2I7+MGCEEx1vbEesWrjpVdGuywb1+yul9bB+E6AxmeDZiFUFSkc4+zAi5HmLPvxdfP9nq1ZzkG6My8Z76BRQ0dP"
        "e2kbXmRZVrfSOfY9EAV2lTH8YNUIEuN6IXIH7bZEsjTYIm7Th1arsFjGZy07SI/Is8O0aTf8pO2X1+ySAK3EeBYpyVbW3s2SdG5HgaZc1ZVT"
        "NL+GRLkfnLdxk16LRwxBkS6GFpB9HdcucLAbwB4VnITU7gR2Dqlk1LHmDFiCN72qsVC107KdYU1BZ1jfRPyfWHgYBCR0ksDOyomzFcNiUhq1"
        "ZbTE1mvGQ9fxKX3ohjQXdmipvWNL/PXP3ZeNuN9s7u5/x9oq5/PZfvEmS5hBvvpPRyv1DvJPyyK6pa0HrDp3RZgMGrEQq3J9q3zOS148piqD"
        "KAijIafRC1WWofQVnUTJxi4Wroc6bYchDE+dfBbOQ++CNZ7vx+VyWbDFLW1HuHNCUChGOlAvwvbhhF4vvJb1HuVCWb7Coap66ffVk1E6x1w4"
        "JSKOlwhmvHglcq6QMZxbqjLno6jRcOH3byytYNA6oKaPBNWYchy0fD6q+VXMkn34cDglWgn6mlAHniJFZZDbi/caI0djIl0QnHg2F5ZmbYoF"
        "kGw2CG9apM9PC/IwHTQmJbsadTfnM1nlNMTFPBwxgMVIj0OHALk5oM0PO0DxXgJiGeO/5TuWuOUvVOXrpMM8JkSHTh5QwqzLR2d8oQ7L6aXA"
        "2XrG1hTmsA4Agle8HXrQwQYBnnjBpGPb/YSPklTN0PX5CycQ2A0RCyck+BZp5yPluIKkJ1HjpDlphR5fsYQ96V4D2q8/4plh44kDnN0MVRoX"
        "gpQmopNIA4r+cR16J4KTPRI13gTVn3Y3dBj0G73ZvEgmlWwaIdNezqebFg8iXWDrqT/f9QrCM3eJGvOufSBqZo6t8r4xnu/MNlQYTam+vgr1"
        "kYMLFKTzHmi0ZUW/2NlX/cLppqVZi5ctPUW41JKyin8kJqGMk0h6liASeLpb4h0ZfML/DHKhQqJDHlfLabzCtAfnmfaOWjdJd0Lw2wj0ltRx"
        "Jn3YGyVmHs8rSFxBF4GiC5jaC/8jECQhqD2ESFoceqXI/gVfewku"
    ),
    "canary/text/facts.py": (
        "eNqFVMtu2zAQvOsrFuyhNqDoA5Q4aIC46CkNiiCXwBBocmWzpUiVD7tqmn/virTluAgaXSiSy93ZmSEZY/dxrZUAZfoYPAQLuEM3wAP+CvfO"
        "7pREV8Hd8nH5DSgCwhahsxpBSbAOuBkguBi2lAC26LAqiq97g66GL8ub24vl3WMFD3QGzQ7WUWnpwRqEXPWWD5+5oLI9OpB8gNbZjsokRD7w"
        "gBSsh6pgjBVpr2naGKLDpgHV9dYFQmAsRSprfJFjJA9caO49+mPQtFRCq1DLHBiGXpnNMebGDCVQy8EKq4ui+DQdmlH0bzSLBxdxXqQlWHa9"
        "tgNiwl8XQJ+SNYF26d/wDk8ziX04zRzRd5oJjdxxI2hJmQB/4G7kZ5GGd1Gc05hhBDWyf0zvEWXO/P73AfbWaZnOwCzLML+E/mADD9GT7gFa"
        "El5iQNcpo3wgrXbcKQxDbpYPqWDuznY9eeSEBw+8+RpC7DU+nRFZQlVVq5zGiilGKhGeKEM5irTKQefAg6WyH332jt8S/nz+mYZGyZJYCRrL"
        "EVwJDoXqFZrgXw7yCJshntP/NkeKDCfoMEjlNy4ayiunto60jY721nBoqa0SyKL5msxPBZvO2uwYKscMxuC4Zm8UZNxs3MAI2xSVfYR0lpgZ"
        "Bc48JYoSOQuY5VJ0jR2v4ZxB2k7XYCax5VGHZkRp3bAYw+bkuuyu12/A7Hgz5vWbBm9HapsOvecb9DOPui1T8yTCuUvncHENJFJIsq7qEXBx"
        "6pY2n55HxZJUYkv3G3VJnjSE4rV2tBbX33Gkd23l8LK6pBtIHjXqZ8T0oiQ3l4DVpgLWXVHC64urH9dsgkwuRbdTuG+48Xtq8j+wy0nj1DY5"
        "yvZKHP692hiu0yS1R+O/feWQ8Zl8ZrjjXu2QlcCEtQSV3i+avhR/ATd4xuo="
    ),
    "canary/text/gemini.py": (
        "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"
    ),
    "canary/text/instruction.py": (
        "eNpNkMFuwyAMhu95CotTkBq6c6VU2mHXaW+AvEJatAGRMdny9gOSTOVm++f/P1sIMa/8iAEGDzcMSKti+8vKhcSUb+zqaGBnCbw1Lnu4wgPp"
        "M9J5kw+M6ev8JFfeCCG6iaIHrafMmazW4PwciQFDiIxVl7ru6NF9Rkr2qNNaZp2xE5ANxlJf4y9QEmAEsWEICcO1ti4dlNfSdn4bliPtLSxt"
        "TLZQhFo2rxO8yOcNe7nneXShLzjL+B6DlZs3ziX2YFSvdM/eBv6oFZWfm0ShMRr3WS+2k4kTFFfM3zz+Yzd92VAlNjGz+iHHtt8XLT4tpTql"
        "BiJVNZIV0E3lngF9veZYDqF1xdVabJiNXXZ/GsubdA=="
    ),
    "canary/text/lint.py": (
        "eNptUtuO2jAQfc9XTP1C0oV8AFKr3YqthNTLClV9ARQ5eEK8je3IHqBol3/vOIHArpq8eM6Mj2fOHCHEL/xL0GhLU/BoFXpUsHGmlfYIFHNm"
        "Fwgs7tEzbisMAZwHKw2ChAblHyDpt0g5PO08jsE6UNiGXAiRVN4ZKIpqR5wqCtCmdZ5AWutIknY2JMkZ85gkX38uvsxns8cf8AnSBPgTGqQB"
        "qhGMa1CMGRi9jS9n0CGGsSGeQFNXC30Yzwccgp45uEZFpr4wRhf6WKfttk/IN3FAS0wO5LomvN7LJuJ9N0mWLOa/H74VD7PZgmfwmEcpdYOp"
        "F8vVIb+brO/u+TBZf0y7u68xj6TJeT76vVavVm9repY+ixe4kOmZZ54lj9+fivnsPe2qxJXivxzqkkRh1a20iAtMwxQC+QwmnxkMtORgPe00"
        "aNwhKt0tVIgs5xh9mnW51ruyQRO4YFmJyvlSK4UW2trLgFN4aT/4kwBOQAvawnV3uuoRZlt3VAxcZckDSr+ph0fZDAr60d6n+iZvm8ll27JJ"
        "U9GJF/1IcsN+UspHX5JjH9Zs1IOmmokBTdu4I7I5lOjH8shWtAPhrViGKeQWQ2rCljXrtFJ6Q+v/Sed2FJXpB4wimDhyd3PoetDmuotKvJic"
        "m0xHYVc+44ZGYxiNstPKXvDSqeMZvFXg/OZFgCuPVlwZ13F6OyEXJ/8AALo1gw=="
    ),
    "canary/text/minimal.py": (
        "eNqlVE1v2zAMvftXELokAVwDA3oysJ2GYj0MK7beisJQJNrmog9DkpMZgf/7aCdu0w4r9qGLLFJ8fH4kJYS4JzeAxoTBkqOYSEEtjdlKtYN7"
        "/JHugt+TxgDrPqIG78wAVLPLdkYmfHJThN7JvSQjtwY3hRAiq4O3UFV1n/qAVQVkOx8SSOd8kom8i1l2tgXptLfZKaSopUpxuX7Xbw2pj3K4"
        "maxZlikjY4TPTNdKsxAoM+DlpEV4D8KenCKbrRpr0HKoLMYoG4zriKbOYc5SvsLfwNUHMCzEgyaVHk+w0wquYeQTz+LrvK1rcZxBikQYxvJ8"
        "iIh6LG1sFgPnHsXmCYl0ZKQHLEhD7QMgkDuRKSZV/YAYH59u+z5Nt58NU8huCmEuDa7f5XC9eaY5rQme6Raq9aRwzfk2L/wMWciuQ6fXR0Fa"
        "lFALe8H16rgbRQ6CvyffYmeLarl4aNgqGnQYWGK2RkbCwMaYv8hzuURARR2hS5EvPgjuMfE4xfbb76jSzIFrABc0oO80t5h4A3Tr9UxRfOOG"
        "6uM5AuYuOsYRZFoAlbeddMNYiPGiEvXyd6j8wI2pL8+V9V7De24nFjpwnr8T8fqfJLzI/z9iipvQxxRYDP0H+olbkBZqnu++gwOlFlp/ACsd"
        "T4vlLJACSp5IVrjFgC80DMjT7SY5noeNHL8ne8JDJV08YHhr4HJYmp77J4Ucku9Inb8jNU6a+TAPJu/lZfVO/rlGuJeR9viqSmd2tbhdaR6Y"
        "xPSBXx9oME0sPRzndEVAfs54VlbVKocVrDYjBGraxJcPhch+gfvEpR+YKuthugK+uN8DlVPClvj56F0fe2lykHEH/FBxP84OTvATtxax3g=="
    ),
    "canary/text/template.py": (
        "eNq1Wm2P2ziS/u5fwVE+xJ5zG8nOLg7nPW/Q0+lJ+5Cks92dCRaNhkFLlK2xJOpIyl5to//7PlWkZKlfsgvMXYAkMkUWi/Xy1AsVRdF75ZQp"
        "sjKzLouFU0WVS6fEjfq7+2L0PkuUmYllWdVOZFZ8qdd5Fr+XzS8ydlboMm/EuNSi0LkSmFu6zDWT2Wh0vlemEUaWiS5EvNVZrESsC2VFajDi"
        "X8yu+L9xGjlsN793mTIP83urVIL/Etk8zGazaCJOTkSpQFC4rRKbXK9lLq4+f5iNoigaMb3VKq1dbdRqJbKi0sYJWZbaSZfp0o5GYczvOvJL"
        "ZikfIbw6x7l1oxSfa/ronKPRzeWX5dm1WIhxZFSMY64SHdcFHmw0FVGsS0cTV7p2FmKgsYM2u1zLhJ5lHCtrVyUOZqPJ6Hr54fPpR09O7aXN"
        "9spT0ZUy4Bk/J6PR6vLrzfXy/TlPkwL7mjqDsrwEfzbZZusq6bbiRuZghPcphc4TCDrPldzUSpT6ICSEgaHS1rmTZdxE05Ho/QHpvYJcDHao"
        "PO2zXNfJIbPMlYXWdKn8G1JAVia1ddBuoZSrK95XbJVMtnVJ7OlSfMzKnUqWJR/j7OL05ub8Cse45Y2ja7CR1BWMZq8S4bSA4gv1gCeofCqs"
        "LJTIQWEWOI1Oy4Y4wJIUbOZ1GW/pVMTMPf96ELDaWL1rF1wpWDQsdw7S26zcPIgE/IGmIiO+P2xV+dBRX77Oc7FWwhm5VzkmbZinGJb8EOZO"
        "RUXD4AuHi7fSdYsh+50/RCdGuYYVtBv/mbhsaAeLt5j0v7V2qlt+ptNUKVHIeEvMgfpPJhFprkEHnK6N3qlSyI3MyuMaaLlVilH7TB1E0YjE"
        "yNSxfNojrxV+qXCCTjQXEISFKOdi+boQzGk44r0Gq+aB9o2hGQMi3Z4ftGMR4KjrBjO9mT8EzsRnvM5I+co6lUzFGmRT4IgbUrmQZJt84kMG"
        "wz3SaWihYfUX2jqgykZbm1VBmKTpQpqdOgr+vQaWSG8YWyiO59gc1ALE5NI6cVBq99p2IvHiOpoJJEnLyrpYK2P70psK6GCHIahlJr5lpMCt"
        "7MRJbNyNVh+/fj678KgAoy3JFYADmt1G5t73b7Yyo/+r7B//kPSQ4k2qcvjG6uZi+fmDxwHi468/QXLJRrEv04ABfhSyan+2BlYnWTcll+wO"
        "sP+yHdpmJPUw1Pd1fqvLtZYmoRnAMNsuiuHTMCojbG32qmmHszI1UhTZxjCWEtPfLs4/M8u/mAwa45m60MboAz2TmetUhDclgJ21QD8+6TIM"
        "32xrY+kZ9M6WN8tzL4SflYH/0YRrp+PdVucFz5bkljz+ESQ0P13aXLMMl5/C6v+a//SG3rx9M3/TPrz9Ez+8pRECo9PPH67+doSi05KNHvYn"
        "zRTm5H+9Jtt9jXABCJyJj5qtS3rvqm1ngp9kKTeKgoDYKVVZAjRGD4pSWuYVLJlsNKGRUhw0QZIVh20jKqUrRMx1bUrywaOHwJzZ/GGF1oMa"
        "tKRs+doBwqyCaoBCCMiv8bBWoFpXCTRD4NSIs187Qte7rKrgrcRyBXfQpL3WXcnzE3KcyiD6l4lnGhtmweBbKt/AaqLFkkYTBgvvj4mKM0uh"
        "9RgVoKKTLc5qgxO+AyisddIIaeFGNfsqu1ZH/ItsEDYMQ7IUvwHpKEOo4GSMpz2fF58o1gknd0ERx1gYY18B5MMjnrxbjlbvL89Wn06XHztF"
        "jxESKBhkLlcPZBFXgEHQMrrebNvxmTgFBzUpBgYMXji+wwUocHTAhLhOAoNdKAdoSTIL1zkGlck0bBiIihNAPnRK0qKN/1pn8a4bIsQPE+eC"
        "4KUPRxlwXsU87Q+kAZm/O5L/5ZAMDnQNdCI9ttsywLIl4ozA0Y5TlczEF6QHVrHViixAN8g/w32KVEIfTnyYB5SVOw+TcWbiOveW14mPI2lK"
        "GYgnqo+xqOkLiFT06+XyjFKbe28MBfuSiebY+0bJYnrcj5aIKMmgdKf9jNM85wk/Q4pTfq3KDZQUCGw9fsVbDNj2TEiOZN5YxzMust4GPzAF"
        "iCThd7/ofGd7r4nAA0PH9bfzq+uO5+dTwTafm8yD6fkcA5qEjyCoOAbHdsUUvgWTyxNycIfsQzS6BkJkgHSCAkxOyatmPSAHW8iFbI0k2Lo6"
        "TYkGcj1rEae2CKBwJ0oPWPJAboTRcvOuv375OgkhUyOZUfEOmiM8eE2OBS9qvGEgH4KlgtsDudxSIDktB3x8wzin5RucyhIMgiCjk7C7rGCH"
        "ofVZh2930+9IbpD+DqR3Q9hEQQSUj15IeRfDzz3IINFaEvdsejeQBoILQ2+ukBZ1vkymC6AkXQ+O4k8HgkyrxWxoRBYcR0uSpYU9AYwuZFU1"
        "dFS7RXZN+gJFn+Ej9CKKmmZA+xMwFxwzZZZ064fEqnfTg24jAnz+PlGVQwJSevwMOVLHz4A2E0V2mgNgXWcWngJCsN1yrLe0bYxkp6phYTRP"
        "/R3lCiY4mFiWAobzKq3zJ2p6rq55ycAdMmGSij8I8qcMaE3mwSkaBTHOE9kqoT0cm1QCcOvFBCZFyaS3Q2K7ULKcIuBAPYn1pkgih9PA3qT1"
        "pQ0xOXts4jAlCuaI6TDQDusLCr7GaoABWEzBKM5PQQVYrndyqLpTkSK7DqrhWBUsw5CV0xKiziddeqeBi8ME/i1Bvmzvp70AB0nAR33w5ZS2"
        "AKktWbuVWYL9Z+KSGKJyTfyGJK6fnVPl56u0R9bukR/Zr66BNMNkHDCivDZ9sN/AMQyk1dV9AXV8Sd7GDsoyfgNC26Hte2/1iWtIsIN5SzZF"
        "rxSgXBZnIILaqixV3hksFhxgwN74t+TfQ/qX7FlHzimz2bb+SZqglQWpmIyG6m9yOmKD02suB54oq1+5P2/tP9e2CQbgCwTYKQewAXPXVMiS"
        "ieYH2TDU27pCUqgIQwwnOfaRwS2d2COOk69cA8Mpi7acF1BTZsq4Tj8B1YNlVBIeBkrjdK7NZ6m8fudzRoJqH4Y2mjxRl989/ss2ijpyH9JU"
        "WyHzcEhHY1lbzp26IooKQQgcSFlTX0LmlHgeyn4+MEBKkqFc58prkpMjn0CQ3xFKcb7h4Y2t1qvQtqcGkHqRcbh45Mtr4sQh5SWHYg9ysoFF"
        "cMPLHahF1asAkXU2QatG7Ep9GFreF9BxDfzPFDKfEynqaUDL3dkl1/vHhDKwekTBumS4fqKAQbfoO4jL5nxog3CIQGEYtoXEHWD3m14/8n0f"
        "6elEMMkbBG5WESACaykt6OUBVAOrR5HSevzD0eDxUFXhFdHFQDK0AfjmsPgn2X+QoV5D2xCz5tQXVrxECKPgQUfxAyBGAPusz7wosu/YbVth"
        "LX330kuLOkneqih9peSb8gfH1vTngBXW+VSNekXQ5VPJEOs+zJ/kUEkO66EGiKSHZk2Vd6xayxRcgASdwYdUSUA49Iam916y9a6pIeCTntDq"
        "C6jby0o4s8NcZzIkPUMW/6e2rn/YxEBAXbbDDQ72UsC1NDPxNwq0svRJIk/J9cb2hI+0eDRKVCpWaWasG6PGGjRSJ+LkL+Ryc14Aj6F6V81K"
        "AOPMVnnmxpPbN3cEz35QAPrxzyxLWrp76hw/T9eRY92C+pS2uAt7ID1XM6MBIahblBlPeJj8ejcVe4p5vvSYIboWdjyZd9IBFzt6b+aD/mjg"
        "et8/wqMCgjoLrRjyfGzKzXzY4Z4KVzFIgNcff9wdhnJZUy22QF4YuzFB9QIEZr5nPvbtDdQn3OccvOHmE96wXw3XcFtpMuzz0h+C3MFM6uWA"
        "BPU6B+O+J4M3IbQOXoa+9DP0OdwsdodZpatxxL96LeRoMunOO+O+hRpDFn3BQkyzlCDVjX/8keaRZGPkPVbchKuJ9lbCy46tZiGi9uIiGvEw"
        "KQOuuyrgPgBwO7YqR8rCLf/5o+4+K4NyhVvSwN1R+zgzSD9/VcGUZuHCwv8I1xb+B11eRJOOFLizoEW7jP0EFezZTvoGSHhJc581wdu7bnTd"
        "rJD8oRIlX5kLH7i4eqDVD928wm5w3uPhqCFyN+pek5hkkoxD2jXlJrWCkSL/zKrMV6i2XhPEIJijHJkMOSP6MyAPlo3ZfrNkkUZFTwgn90CT"
        "Mc2bUJ8CQ4vu5bTN9xYtA08savDHc7d4yuSCBXv8Pem4Xgy4X/ARJkcBOGk2iH8L0vWMNI1EZvzHqXj75qiWV5CpzPIux6BbCmr86NiKsefF"
        "I3S3P0V77lNhzpEOqQgDpKQgAVC4nf9091jZoELGcmt4CaXYtG4GRrlwDmeEMG/vJmQ0PIMt4m5AKdhTIEg3J60mxF8W7dFPxNv5E6lTuZKV"
        "tRq8sEFMAQY82clwCoTtJT2c2zXkhtO3GSY35L8B5/kQt/ZuOI3bSwSQrRB4gIypHcADFrY9a/xqoab9Q0YesRoxCTbdl22QDwvyh4WwdyQq"
        "MDE9wvk0nIw3XvC/z6BfGt1vswcRif/oryRpDFfifRqJe5z8QdyHyNmdvI8ar6jRqhuxMXWx5oupcVaWmlongiI14JV6fgMECabF6yiw936v"
        "Cq0BGgtqhW1MEz1+35nR0CAIZzx7vblDS+NrOb5dK1ntVgLdoHbutk8HzvV2Kv4wmTw1OdJQGr26T2aUmrTBmyEDEAeNEdINYc7nDTSdDuUX"
        "8pl46g8LXnn3PKZE0ZQ5Hgob6+l2D1nb6BgyMxjf0XP+OzjO/Hu+QdwNDZBjIXu1+t4h7NND2Nljv/ZF3aJNunr7+l0mjAphR86ougg8ek7k"
        "9onI7XMi9wThFlH0VKY9gx/kEf7ulxIJTg34355vhshGoj0Gbm4pUK20kqUlnr4TvKeiDaQhvXK6yuLwbLNN6YszM8y4gq/wXMZIHM9f8T/C"
        "YroBEr/KvFbnxmgDcdUlVU5lWHvP//1g+l4Lwn7jlnK47v+3SYfV9/7/IfHfm5PM71t54ZGZf5SmgDrd2Y3HPTt9lLF4k80YStpBaPiz7ruT"
        "t2h6702a1oC6N0cUi9TKPJpjQeAB5/DmlgxjZFjL+3AwfD4UMm73Mixa2uMHkXfB+6DiGIaRcI/qqMJbm0ylETsQ8+T57U3glrCf9diKX/CB"
        "cG9wO2Zxt1Y5uZtwAFvgL/c33YL+oXz3lTj5nX/E/u3sTycxQS5l2cJq7q7lsgGyvULtSUlL2z5X5f4EvCKTwYQ1Dizud1kJ/7eVkjtKtDzi"
        "PRw/93GmdtvJTNxsu28XTqg5R62bNvPCPtBRXejaIEF9858k6Lqk7wrSTHHpW1u+U+7eIswlG+V/TiilqqQJuZSiBovDMlPn1Bz75i/hhETe"
        "kFhsxXGfAtNJoly4NNvrWK7rXJqGOklVbaj3JsZtrEshAqrICyqKqRXU+9iA51BHGO7Y1hCT2Wh19fXT5dfepyzUq7ayIVYyxx8alA9swrY2"
        "yre/+PuP9rYWhsldt8R3najFfdb2FLhTWUm+r/FFnR3cDV9CdltFTZDj9U7mP2DYZdTTKmfii29V08udZybzFwN82xtod7cuA/JLS10D7iDT"
        "dy6GW/aehm9gcsuoZSx8XNJ1RqCl2r7jlhm2amhbXfojtd3WHNZ0vDz/QJ+IKEVZzZx3mYlTv02c6yAClcGhZQW/4cpVLMWBOpzr5njNHb6D"
        "cdQLAdvM7kG2m4tqq31WEkwoMwe6ZAv34J/oQrnN1burhUPWXiSvTr/eXFxeLW96XwzwHSdUTsJCxUlXO3MwBlBA0pzyJ3Cd4Ndqm4XeSivz"
        "tmnWb7Z1PsHd1EahWPHYEpH9cNvWkvGEHpG4gau1HV47uNDgj4Fq5O70uVFcG5T1ni1THCXP16vcX00hD3h0rAwkE2QEd439V1Ksk8/UUDLc"
        "Z9J803iQ/p4PBhtDo6b7cODo2wP2C3I1C6uPHShZhC4Ds/fecDDadwQh6g9XX99/OD/K+ZJu4GtjVc+xevL0xiQuZPcREFyr5qYld6tCZ5S9"
        "jzqhdNuA+Nd9+nNKFuCp0mcFsDrgYbgaKPz1IqFMuJmFN1eG4jVMjK+LQPSggv3njJKQiT76Utp9mhQ+cLDhy7Kane54pmnQL93lUIOP3Sp8"
        "xsAtJcNYvfIIPn4pB9qTO/cL/WebGr87efBchITh5R7Eo3zBtyPo2Iu2hxH6cYobcqqEaxjqBvlz9KoDWyH6tPUHR221v41CYIoohA7f+EgV"
        "3Q2zsYo0QOkJwZprfwzzsSclryuxL0o6x53JBzHGU5Y8TI5hn6IkpTjYlx6ju0ErkV+i1vIhMHq023Y6LJajVwdqFsda59wzS7vQ6beNhjmF"
        "j0OTtlfmyoUrJ4/bCFxtDFL4lxI5KjOqQZ0BYO6dQSLca0KTf30M+g4IQJumfIgXAv6zZ+rA9v/1WFb9iyNwRVQ9KYnSLj15lnkPX/83nHfF"
        "YPVMNTg8DwXw77ff7P3uu323addVq7jo6zXV8PhyQ67fXxs213oZMdgb/ROMYohp"
    ),
    "canary/types.py": (
        "eNrNVV1P7DYQfc+vGIUXkJZwn1cXVEppRUUXdHfLC1pZxp4kLo4d2Q7c3Lb/vWM72d1btu9FApLJeD7OnDkuy3LdcocSJA8chDXBcRF8BTct"
        "N40yDXAzhjY+tOgQLnc+IKIHwqlHBGmFv7h5WG2+XN9sqk6eVWVZFrWzHTBWD2FwyBiorrcuUERjAw/KGl9kn5hcaO49+tlpZ1pArVDL7BjG"
        "PpYy+VybcQH3KqDjegGPzgYrrC6KjbV6xbtY7fT1uQD6KT2lHXy5gFIrHxh2vbYj4t5CfQwdmkCWfMIhl4wLgd4zbZvk6ZE70bKObLzJh5Pb"
        "ZJiPKkOp3xS+R4decxOY4Ia7Mb6LFsUr08hfWY0o9+l8cEqEKWX0HMwRI5dv3Ahkkqdo9GHwMfG2KE4gtu8htDzEYXlqCKyh35psCD26czoG"
        "NEKaAHhtadzF3erpdr25++V6c/d0yzYPD/frJRDk39B4DM9UwJbQ3BlO//wfw1P8fVYUd3P4je2VOGACBRE04cNRUz4ideQ9s0PwSmK0vVv3"
        "qi2XE8CxRUO1+JJALn7Y8bNIfxPoX9APOixTrfZ1CS9kSy/ReQmSioxILiJxt+kDOmfdEsgIf8EqTuky/TuWYR2wz7HDEgg9OPpzAo22L1xD"
        "oOTngmtNvhK/TnWM6WiOQg4pdXrjrvFHS3S5qX99mpPhV4JNj/Ae2RbpRROm0jx/h9M9JMB9On92rK97lA26W1KVMbdH0rGm2RFP4yiIu3qs"
        "YIVkoHS99aRWoXV2aFr47eYx9eGT3uyx+dgtHTchI30EszJSLalApJwfXM0FpslnTrJE0GyZ+YZyv3rpEXvlrUSGJr5WVZWrwMCV/gDtESBu"
        "8/lDFlFXD0SKKTKRI1Lk1/XDCrSiJ2UStS7cYPzFZ/rLlLy6mLx99Ycn7KoiRZpk/mUkJKJaOmwc0mAC9fIyRCkgoaVCSakh8GaSfgnrnzcJ"
        "dRcq+MkCKTfUtBigQjVXmHFX6PZsojtB7rFPnPhv7L3VNNuIoLSMEsTbJglJsD0jMdFJEhxVY7v4ZHs0XC0/d9SkvoqWBjtlDi0z+J52hmgd"
        "tf057k+mtBfWIckbbXf4WM8TgQJprOmOAlWTjDpSjQCoPcKn6lPuKk/+cHuTfXI+WP9aGa7Z93Q0kpEq0oA+4nKyZxXFLVvr1Ddr0nPkOslk"
        "n16SeGT0O/woMFGv4815KrHmxChGnA7WjZfzJmbWPVqtxHg6355nO+Jdzxd/ukloAUafNlyZN9oA1XAKtlvE+OHx9x/v727SPkJS97hEeX1n"
        "lhi6lfcsocKivNB14lHXi7zJzPcoppHFSrcLCkYnhnRfpcNncH6V8F4ebFkdb7QpUEuHqdPDwaczYeg1ZoS+x2qbI/0D7D7llw=="
    ),
    "canary/world.py": (
        "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"
        "H/qYHjY4w6CdHsoc1Tzbrdn3g/8AHd6c5Q=="
    ),
}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Paired v1.4 vs v1.5 differential exploit and lexical-shortcut sweep.")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--full", action="store_true", help="Run full paired sweep across seeds 0..99 on easy,medium,hard")
    mode.add_argument("--fast", action="store_true", help="Run <5s smoke subset across seeds 0..1 on easy,medium")
    ap.add_argument("--seeds", default=None, help="Override seed range, e.g. 0:100 or 0-99")
    ap.add_argument("--tiers", default=None, help="Comma-separated tiers, e.g. easy,medium,hard")
    ap.add_argument("--v15-ref", default="origin/justSilas-v15", help="Git ref for v1.5 candidate")
    ap.add_argument("--shallow-fallback", action="store_true", help="Force embedded de9cc50e source map without git show")
    ap.add_argument("--repo-root", type=Path, default=REPO_ROOT, help="Repository root for git resolution")
    ap.add_argument("--workers", type=int, default=None, help="Worker processes (default 2 for --full, 1 for --fast)")
    ap.add_argument("--json-out", type=Path, default=None, help="Optional JSON output file (use /tmp/opencode/...)")
    args = ap.parse_args(argv)

    is_fast = bool(args.fast) or not bool(args.full)
    if args.seeds is not None:
        seeds = parse_seed_spec(args.seeds)
    else:
        seeds = list(range(2)) if is_fast else list(range(100))

    if args.tiers is not None:
        tiers = [t.strip() for t in args.tiers.split(",") if t.strip()]
    else:
        tiers = ["easy", "medium"] if is_fast else ["easy", "medium", "hard"]

    workers = args.workers if args.workers is not None else (1 if is_fast else 2)
    report = run_differential_audit(
        tiers=tiers,
        seeds=seeds,
        v15_ref=args.v15_ref,
        workers=workers,
        repo_root=args.repo_root,
        force_embedded=bool(args.shallow_fallback),
    )
    print(format_console_summary(report))

    if args.json_out is not None:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")

    if not report["v14_tier_hash_preserved"] or not report["working_tree_unchanged"]:
        return 1
    if report["total_invariant_violations"] > 0:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
