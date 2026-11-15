"""Paired v1.4 (justSilas) vs v1.5 (origin/justSilas-v15@de9cc50e) differential exploit and lexical sweep."""
from __future__ import annotations

import argparse
import ast
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

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

EXPECTED_V14_TIER_HASH = "a8f99c2537c91d72"
EXPECTED_V15_COMMIT_PREFIX = "de9cc50e"
ISOLATED_V15_PKG = "_canary_v15_isolated"
ISOLATED_HEAD_PKG = "_canary_head_isolated"

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


def git_status_porcelain(repo_root: Path = REPO_ROOT) -> str:
    proc = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=True,
        timeout=15,
    )
    return proc.stdout


def try_resolve_git_commit(
    ref: str = "origin/justSilas-v15",
    fallback: str | None = EXPECTED_V15_COMMIT_PREFIX,
    repo_root: Path = REPO_ROOT,
) -> str | None:
    candidates: list[str] = []
    extra_local = "justSilas-v15" if ref == "origin/justSilas-v15" else None
    for cand in (ref, extra_local, fallback):
        if cand and cand not in candidates:
            candidates.append(cand)
    for candidate in candidates:
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
    return None


def resolve_git_commit(
    ref: str,
    fallback: str | None = EXPECTED_V15_COMMIT_PREFIX,
    repo_root: Path = REPO_ROOT,
) -> str:
    sha = try_resolve_git_commit(ref=ref, fallback=fallback, repo_root=repo_root)
    if sha is not None:
        return sha
    raise RuntimeError(f"Unable to resolve git commit for {ref!r} or fallback {fallback!r}")


def resolve_head_commit(repo_root: Path = REPO_ROOT) -> str:
    proc = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=True,
        timeout=15,
    )
    return proc.stdout.strip()


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
    def __init__(self, repo_root: Path, commit_sha: str, pkg_name: str = ISOLATED_V15_PKG) -> None:
        self.repo_root = repo_root
        self.commit_sha = commit_sha
        self.pkg_name = pkg_name
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

    def _read_via_git_show(self, rel_path: str) -> str:
        if rel_path not in self.source_cache:
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
        raw_source = self._read_via_git_show(rel_path)
        virtual_name = f"<git:{self.commit_sha[:8]}:{rel_path}>"
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


_RUNTIME_CACHE: dict[tuple[str, str], IsolatedV15Runtime] = {}
_HEAD_ISO_CACHE: dict[tuple[str, str], dict[str, Any]] = {}


def load_v15_runtime(
    ref: str = "origin/justSilas-v15",
    pkg_name: str = ISOLATED_V15_PKG,
    repo_root: Path = REPO_ROOT,
) -> IsolatedV15Runtime:
    fallback = EXPECTED_V15_COMMIT_PREFIX if ref == "origin/justSilas-v15" else None
    commit_sha = resolve_git_commit(ref, fallback=fallback, repo_root=repo_root)
    cache_key = (commit_sha, pkg_name)
    if cache_key in _RUNTIME_CACHE:
        return _RUNTIME_CACHE[cache_key]

    before_status = git_status_porcelain(repo_root)
    for mod_key in list(sys.modules):
        if mod_key == pkg_name or mod_key.startswith(pkg_name + "."):
            sys.modules.pop(mod_key, None)
    sys.meta_path[:] = [
        f for f in sys.meta_path
        if not (isinstance(f, GitShowNamespaceFinder) and f.pkg_name == pkg_name)
    ]
    finder = GitShowNamespaceFinder(repo_root=repo_root, commit_sha=commit_sha, pkg_name=pkg_name)
    sys.meta_path.insert(0, finder)
    after_status = git_status_porcelain(repo_root)
    rt = IsolatedV15Runtime(finder=finder, commit_sha=commit_sha, status_unchanged=(before_status == after_status))
    post_import_status = git_status_porcelain(repo_root)
    rt.status_unchanged = rt.status_unchanged and (before_status == post_import_status)
    _RUNTIME_CACHE[cache_key] = rt
    return rt


def load_head_isolated_v14(
    pkg_name: str = ISOLATED_HEAD_PKG,
    repo_root: Path = REPO_ROOT,
) -> dict[str, Any]:
    commit_sha = resolve_head_commit(repo_root)
    cache_key = (commit_sha, pkg_name)
    if cache_key in _HEAD_ISO_CACHE:
        return _HEAD_ISO_CACHE[cache_key]

    before_status = git_status_porcelain(repo_root)
    for mod_key in list(sys.modules):
        if mod_key == pkg_name or mod_key.startswith(pkg_name + "."):
            sys.modules.pop(mod_key, None)
    sys.meta_path[:] = [
        f for f in sys.meta_path
        if not (isinstance(f, GitShowNamespaceFinder) and f.pkg_name == pkg_name)
    ]
    finder = GitShowNamespaceFinder(repo_root=repo_root, commit_sha=commit_sha, pkg_name=pkg_name)
    sys.meta_path.insert(0, finder)
    rules_mod = importlib.import_module(f"{pkg_name}.rules")
    env_mod = importlib.import_module(f"{pkg_name}.env")
    solver_mod = importlib.import_module(f"{pkg_name}.solver.policy")
    after_status = git_status_porcelain(repo_root)
    bundle = {
        "commit_sha": commit_sha,
        "pkg_name": pkg_name,
        "finder": finder,
        "rules": rules_mod,
        "env_mod": env_mod,
        "solver_mod": solver_mod,
        "status_unchanged": before_status == after_status,
    }
    _HEAD_ISO_CACHE[cache_key] = bundle
    return bundle


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


def _worker_seed_batch(args: tuple[str, list[int], list[str], str]) -> list[dict[str, Any]]:
    tier, seed_batch, strategies, v15_ref = args
    from canary.env import Env as EnvV14

    v15_rt = load_v15_runtime(ref=v15_ref)
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
) -> dict[str, Any]:
    from canary.env import Env as EnvV14

    strat_list = list(strategies or STRATEGY_NAMES)
    all_rows: list[dict[str, Any]] = []
    if workers > 1 and len(seeds) >= 4:
        tasks: list[tuple[str, list[int], list[str], str]] = []
        chunk_size = max(1, math.ceil(len(seeds) / (workers * 2)))
        for tier in tiers:
            for idx in range(0, len(seeds), chunk_size):
                tasks.append((tier, seeds[idx:idx + chunk_size], strat_list, v15_ref))
        with ProcessPoolExecutor(max_workers=workers) as pool:
            for part in pool.map(_worker_seed_batch, tasks):
                all_rows.extend(part)
    else:
        for tier in tiers:
            all_rows.extend(_worker_seed_batch((tier, seeds, strat_list, v15_ref)))

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


def run_v14_shallow_fallback_audit(
    tiers: list[str],
    seeds: list[int],
    repo_root: Path = REPO_ROOT,
) -> dict[str, Any]:
    from canary import rules as rules_v14
    from canary.env import Env as EnvV14

    t0 = time.perf_counter()
    before_git_status = git_status_porcelain(repo_root)
    head_iso = load_head_isolated_v14(repo_root=repo_root)

    by_tier: dict[str, Any] = {}
    total_episodes = 0
    total_violations = 0
    for tier in tiers:
        sample_env = EnvV14(tier, seeds[0])
        has_decoy = bool(sample_env.p.decoy)
        n_emp = int(sample_env.p.n_employees)
        strat_summaries: dict[str, Any] = {}
        for strat_name in STRATEGY_NAMES:
            ep_rows = [
                run_single_episode(EnvV14(tier, seed), make_strategy(strat_name, seed, "v1.4"))
                for seed in seeds
            ]
            total_episodes += len(ep_rows)
            v14_sum = summarize_version_episodes(ep_rows, has_decoy)
            total_violations += v14_sum["invariant_violations"]
            strat_summaries[strat_name] = v14_sum
        by_tier[tier] = {
            "tier": tier,
            "n_employees": n_emp,
            "prior_mole": round(1.0 / n_emp, 6),
            "has_decoy": has_decoy,
            "n_seeds": len(seeds),
            "strategies": strat_summaries,
        }

    iv_audit = audit_interview_template_separability(v15_rt=None)
    v14_hash_after = compute_tier_hash(rules_v14.TIERS, rules_v14.KNOWN_V_MODE)
    after_git_status = git_status_porcelain(repo_root)
    elapsed = round(time.perf_counter() - t0, 3)

    return {
        "shallow_checkout_fallback": True,
        "v15_available": False,
        "v14_head_sha": head_iso["commit_sha"][:8],
        "v14_tiers_version": rules_v14.TIERS_VERSION,
        "v14_tier_hash": v14_hash_after,
        "v14_tier_hash_preserved": v14_hash_after == EXPECTED_V14_TIER_HASH,
        "v15_commit_sha": None,
        "v15_commit_full": None,
        "v15_isolated_namespace": None,
        "v15_git_show_modules_loaded": 0,
        "v15_git_show_sample_paths": [],
        "head_isolated_namespace": head_iso["pkg_name"],
        "head_git_show_modules_loaded": len(head_iso["finder"].git_show_paths),
        "working_tree_unchanged": (before_git_status == after_git_status) and head_iso["status_unchanged"],
        "llm_api_calls": 0,
        "tiers_tested": tiers,
        "seed_range": [seeds[0], seeds[-1]] if seeds else [],
        "n_seeds": len(seeds),
        "n_strategies": len(STRATEGY_NAMES),
        "strategy_names": list(STRATEGY_NAMES),
        "total_strategy_episodes": total_episodes,
        "total_passive_scan_episodes": 0,
        "total_episodes": total_episodes,
        "total_invariant_violations": total_violations,
        "elapsed_seconds": elapsed,
        "v14_strategy_sweep": by_tier,
        "interview_template_audit": iv_audit,
    }


def run_differential_audit(
    tiers: list[str],
    seeds: list[int],
    v15_ref: str = "origin/justSilas-v15",
    workers: int = 1,
) -> dict[str, Any]:
    from canary import rules as rules_v14

    t0 = time.perf_counter()
    before_git_status = git_status_porcelain(REPO_ROOT)
    v15_rt = load_v15_runtime(ref=v15_ref)

    sweep_res = run_paired_strategy_sweep(
        tiers=tiers,
        seeds=seeds,
        strategies=list(STRATEGY_NAMES),
        v15_ref=v15_ref,
        workers=workers,
    )
    lex_res = audit_lexical_and_stream_differentials(tiers=tiers, seeds=seeds, v15_rt=v15_rt)

    v14_hash_after = compute_tier_hash(rules_v14.TIERS, rules_v14.KNOWN_V_MODE)
    after_git_status = git_status_porcelain(REPO_ROOT)
    elapsed = round(time.perf_counter() - t0, 3)

    return {
        "shallow_checkout_fallback": False,
        "v15_available": True,
        "v14_head_sha": resolve_head_commit(REPO_ROOT)[:8],
        "v14_tiers_version": rules_v14.TIERS_VERSION,
        "v14_tier_hash": v14_hash_after,
        "v14_tier_hash_preserved": v14_hash_after == EXPECTED_V14_TIER_HASH,
        "v15_commit_sha": v15_rt.commit_sha[:8],
        "v15_commit_full": v15_rt.commit_sha,
        "v15_isolated_namespace": v15_rt.pkg_name,
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
    if report.get("shallow_checkout_fallback"):
        lines = [
            f"Shallow Checkout Fallback Sweep: v1.4 ({report['v14_tiers_version']} @ {report['v14_head_sha']}) "
            f"| v1.5 git ref unavailable in shallow clone | HEAD git show -> {report['head_isolated_namespace']}",
            f"Episodes: {report['total_strategy_episodes']} v1.4 strategy "
            f"| Seeds: {report['n_seeds']} ({report['seed_range'][0]}..{report['seed_range'][1]}) "
            f"| Invariant violations: {report['total_invariant_violations']} | Working tree unchanged: {report['working_tree_unchanged']} "
            f"| Time: {report['elapsed_seconds']:.2f}s",
        ]
        for tier in report["tiers_tested"]:
            tdata = report["v14_strategy_sweep"][tier]
            lines.append(f"\n[{tier.upper()} | n_emp={tdata['n_employees']} | prior={tdata['prior_mole']:.4f}]")
            lines.append(f"{'strategy':<26} {'v1.4 score':>18} {'v14 acc':>8} {'v14 dec':>8}")
            for sname in report["strategy_names"]:
                v14s = tdata["strategies"][sname]
                lines.append(
                    f"{sname:<26} "
                    f"{v14s['mean_score']:+7.4f}+-{v14s['ci95']:6.4f} "
                    f"{100.0 * v14s['acc']:6.1f}% "
                    f"{100.0 * v14s['decoy_hit_rate']:6.1f}%"
                )
        return "\n".join(lines)

    lines = [
        f"Paired Differential Sweep: v1.4 ({report['v14_tiers_version']} @ {report['v14_head_sha']}) "
        f"vs v1.5 (v1.5-candidate @ {report['v15_commit_sha']} via git show -> {report['v15_isolated_namespace']})",
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


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Paired v1.4 vs v1.5 differential exploit and lexical-shortcut sweep.")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--full", action="store_true", help="Run full paired sweep across seeds 0..99 on easy,medium,hard")
    mode.add_argument("--fast", action="store_true", help="Run <5s smoke subset across seeds 0..1 on easy,medium")
    ap.add_argument("--seeds", default=None, help="Override seed range, e.g. 0:100 or 0-99")
    ap.add_argument("--tiers", default=None, help="Comma-separated tiers, e.g. easy,medium,hard")
    ap.add_argument("--v15-ref", default="origin/justSilas-v15", help="Git ref for v1.5 candidate")
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
    fallback = EXPECTED_V15_COMMIT_PREFIX if args.v15_ref == "origin/justSilas-v15" else None
    v15_sha = try_resolve_git_commit(ref=args.v15_ref, fallback=fallback, repo_root=REPO_ROOT)
    if v15_sha is None and is_fast:
        report = run_v14_shallow_fallback_audit(tiers=tiers, seeds=seeds, repo_root=REPO_ROOT)
    else:
        report = run_differential_audit(tiers=tiers, seeds=seeds, v15_ref=args.v15_ref, workers=workers)
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
