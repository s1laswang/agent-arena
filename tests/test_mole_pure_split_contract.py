from __future__ import annotations

import ast
from concurrent.futures import ThreadPoolExecutor
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tokenize
from typing import Sequence

ROOT = Path(__file__).resolve().parents[1]
SELF_PATH = Path(__file__).resolve()
MOLE_DIR = ROOT / "canary" / "mole"
FRONTIER_PROXIES_PATH = ROOT / "canary" / "forge" / "frontier_proxies.py"
EVAL_V14_SCRIPT = ROOT / "scripts" / "eval_mole_strategies_v14.py"
BENCHMARK_SCRIPT = ROOT / "scripts" / "benchmark_mole_strategies.py"
PROTECTED_PATHS_TXT = ROOT / ".github" / "protected-paths.txt"

HASH_CH = chr(35)
EM_DASH = chr(0x2014)
EN_DASH = chr(0x2013)
UNICODE_MINUS = chr(0x2212)

FORBIDDEN_IMPORT_PREFIXES: tuple[str, ...] = (
    "canary.social",
    "canary.social_audit",
    "canary.arena",
    "canary.gemini",
)

BLOCKED_RUNTIME_MODULES: tuple[str, ...] = (
    "canary.social",
    "canary.social_audit",
    "canary.arena",
)

REQUIRED_PURE_MOLE_VERIFIERS: tuple[str, ...] = (
    "canary.mole.transcript_miner",
    "canary.mole.ablation",
    "canary.mole.transfer_eval",
    "canary.mole.regret_portfolio",
    "canary.mole.discipline_curve",
    "canary.mole.tier_robustness",
    "canary.mole.distill_rl_mole",
    "canary.mole.worked_predicate",
    "canary.mole.representation_pareto",
)

OPTIONAL_PURE_MOLE_VERIFIERS: tuple[str, ...] = (
    "canary.mole.dual_tier_synthesis",
    "canary.mole.seed_generalization",
)

VANILLA_NON_STDLIB_TOP_MODULES: frozenset[str] = frozenset({
    "__mp_main__",
    "annotated_types",
    "anyio",
    "certifi",
    "dotenv",
    "h11",
    "httpcore",
    "httpx",
    "idna",
    "mcp",
    "numpy",
    "pydantic",
    "pydantic_core",
    "sniffio",
    "typing_extensions",
})


def _clean_offline_env() -> dict[str, str]:
    env = dict(os.environ)
    env["GOOGLE_API_KEY"] = ""
    env["GEMINI_API_KEY"] = ""
    env["GOOGLE_GENERATIVE_AI_API_KEY"] = ""
    env["OPENAI_API_KEY"] = ""
    env["ANTHROPIC_API_KEY"] = ""
    env["CANARY_OFFLINE"] = "1"
    env["PYTHONNOUSERSITE"] = "1"
    existing_pp = env.get("PYTHONPATH", "").strip()
    env["PYTHONPATH"] = f"{ROOT}{os.pathsep}{existing_pp}" if existing_pp else str(ROOT)
    return env


def _matches_forbidden_prefix(mod_name: str, prefixes: Sequence[str] = FORBIDDEN_IMPORT_PREFIXES) -> str | None:
    for prefix in prefixes:
        if mod_name == prefix or mod_name.startswith(prefix + "."):
            return prefix
    return None


def _package_parts_for_file(py_path: Path, root: Path = ROOT) -> list[str]:
    try:
        rel = py_path.resolve().relative_to(root.resolve())
    except ValueError:
        return []
    if rel.name == "__init__.py":
        return list(rel.parent.parts)
    return list(rel.parent.parts)


def scan_source_for_forbidden_imports(
    source: str,
    *,
    filename: str = "<memory>",
    package_parts: Sequence[str] = (),
    forbidden_prefixes: Sequence[str] = FORBIDDEN_IMPORT_PREFIXES,
) -> list[str]:
    tree = ast.parse(source, filename=filename)
    hits: list[str] = []
    pkg = list(package_parts)

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                matched = _matches_forbidden_prefix(alias.name, forbidden_prefixes)
                if matched is not None:
                    hits.append(f"{filename}:{node.lineno}: import {alias.name} (matches {matched})")
        elif isinstance(node, ast.ImportFrom):
            base_mod = ""
            if node.level and node.level > 0:
                ascend = node.level - 1
                if ascend <= len(pkg):
                    anchor = pkg[: len(pkg) - ascend]
                    suffix = node.module.split(".") if node.module else []
                    base_mod = ".".join([*anchor, *suffix])
                else:
                    base_mod = node.module or ""
            else:
                base_mod = node.module or ""

            if base_mod:
                matched_base = _matches_forbidden_prefix(base_mod, forbidden_prefixes)
                if matched_base is not None:
                    hits.append(f"{filename}:{node.lineno}: from {base_mod} import ... (matches {matched_base})")
                    continue

            for alias in node.names:
                if alias.name == "*":
                    continue
                candidate = f"{base_mod}.{alias.name}" if base_mod else alias.name
                matched_child = _matches_forbidden_prefix(candidate, forbidden_prefixes)
                if matched_child is not None:
                    hits.append(
                        f"{filename}:{node.lineno}: from {base_mod or '.'} import {alias.name} (matches {matched_child})"
                    )

    return hits


def _pure_split_python_targets() -> list[Path]:
    mole_files = sorted(
        p for p in MOLE_DIR.rglob("*.py")
        if p.is_file() and "__pycache__" not in p.parts
    )
    return [
        *mole_files,
        FRONTIER_PROXIES_PATH,
        EVAL_V14_SCRIPT,
        BENCHMARK_SCRIPT,
    ]


def _mole_module_names() -> list[str]:
    names: list[str] = []
    for py_file in sorted(MOLE_DIR.rglob("*.py")):
        if not py_file.is_file() or "__pycache__" in py_file.parts:
            continue
        rel = py_file.relative_to(ROOT).with_suffix("")
        parts = list(rel.parts)
        if parts[-1] == "__init__":
            parts = parts[:-1]
        names.append(".".join(parts))
    return sorted(set(names))


def load_protected_rules(protected_txt: Path = PROTECTED_PATHS_TXT) -> list[str]:
    rules: list[str] = []
    for raw_line in protected_txt.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith(HASH_CH):
            continue
        rules.append(line)
    return rules


def match_protected_rule(rel_posix: str, rules: Sequence[str]) -> str | None:
    norm = rel_posix.replace("\\", "/").lstrip("./")
    for rule in rules:
        if rule.endswith("/"):
            if norm.startswith(rule) or (norm + "/") == rule:
                return rule
        elif norm == rule:
            return rule
    return None


def test_self_hygiene_zero_comments_and_dashes() -> None:
    raw = SELF_PATH.read_text(encoding="utf-8")
    assert raw.isascii()
    assert HASH_CH not in raw
    assert EM_DASH not in raw
    assert EN_DASH not in raw
    assert UNICODE_MINUS not in raw
    tokens = list(tokenize.generate_tokens(io.StringIO(raw).readline))
    comment_tokens = [tok for tok in tokens if tok.type == tokenize.COMMENT]
    assert comment_tokens == []


def test_ast_zero_forbidden_imports_across_pure_mole_split() -> None:
    targets = _pure_split_python_targets()
    assert len(targets) >= 19
    for target in (FRONTIER_PROXIES_PATH, EVAL_V14_SCRIPT, BENCHMARK_SCRIPT):
        assert target.is_file(), f"missing pure-split target: {target}"

    violations: list[str] = []
    for py_path in targets:
        rel_label = py_path.relative_to(ROOT).as_posix()
        src = py_path.read_text(encoding="utf-8")
        pkg_parts = _package_parts_for_file(py_path, ROOT)
        violations.extend(
            scan_source_for_forbidden_imports(
                src,
                filename=rel_label,
                package_parts=pkg_parts,
            )
        )

    assert violations == [], "forbidden imports found in pure-mole split:\n" + "\n".join(violations)


def test_ast_forbidden_import_scanner_catches_all_forms() -> None:
    sample = "\n".join([
        "import canary.social",
        "import json, canary.social.engine as se",
        "from canary.social_audit import run_audit",
        "def _nested():",
        "    from canary import env, arena",
        "    from canary.gemini.sdk import Client",
        "    from ..social import biases",
        "    from .. import gemini",
    ])
    hits = scan_source_for_forbidden_imports(
        sample,
        filename="canary/mole/synthetic.py",
        package_parts=["canary", "mole"],
    )
    assert len(hits) == 7

    clean_sample = "\n".join([
        "import json",
        "from canary.env import Env",
        "from canary.forge.frontier_proxies import GeminiCarbonProxy",
        "from .dsl import MoleStrategy",
    ])
    clean_hits = scan_source_for_forbidden_imports(
        clean_sample,
        filename="canary/mole/clean.py",
        package_parts=["canary", "mole"],
    )
    assert clean_hits == []


def test_clean_subprocess_imports_all_mole_modules_with_blocked_namespaces() -> None:
    mole_modules = _mole_module_names()
    assert "canary.mole" in mole_modules
    assert "canary.mole.dsl" in mole_modules
    assert "canary.mole.strategies" in mole_modules
    assert len(mole_modules) >= 16

    blocked_probes = [
        *BLOCKED_RUNTIME_MODULES,
        "canary.social.engine",
        "canary.arena.be_the_mole",
        "canary.arena.living_office",
    ]

    runner = "\n".join([
        "import importlib, importlib.util, json, sys",
        f"blocked = {list(BLOCKED_RUNTIME_MODULES)!r}",
        "for name in blocked:",
        "    sys.modules[name] = None",
        "blocked_verified = []",
        f"for name in {blocked_probes!r}:",
        "    try:",
        "        importlib.import_module(name)",
        "    except ModuleNotFoundError:",
        "        blocked_verified.append(name)",
        "    else:",
        "        raise AssertionError(f'expected ModuleNotFoundError for {name}')",
        "before = set(sys.modules)",
        f"targets = {mole_modules!r}",
        "imported = []",
        "for mod_name in targets:",
        "    importlib.import_module(mod_name)",
        "    imported.append(mod_name)",
        "importlib.import_module('canary.forge.frontier_proxies')",
        f"for script_name, script_path in [('eval_v14', {str(EVAL_V14_SCRIPT)!r}), ('bench_v14', {str(BENCHMARK_SCRIPT)!r})]:",
        "    spec = importlib.util.spec_from_file_location(script_name, script_path)",
        "    assert spec is not None and spec.loader is not None",
        "    mod = importlib.util.module_from_spec(spec)",
        "    sys.modules[script_name] = mod",
        "    spec.loader.exec_module(mod)",
        "after = set(sys.modules) - before - {'eval_v14', 'bench_v14'}",
        "stdlib = getattr(sys, 'stdlib_module_names', frozenset())",
        "non_stdlib_tops = sorted({",
        "    m.split('.')[0] for m in after",
        "    if sys.modules.get(m) is not None and m.split('.')[0] not in stdlib and m.split('.')[0] != 'canary'",
        "})",
        "leaked_canary = sorted(",
        "    m for m in sys.modules",
        "    if sys.modules.get(m) is not None and (",
        "        m == 'canary.social' or m.startswith('canary.social.')",
        "        or m == 'canary.social_audit' or m.startswith('canary.social_audit.')",
        "        or m == 'canary.arena' or m.startswith('canary.arena.')",
        "        or m == 'canary.gemini' or m.startswith('canary.gemini.')",
        "    )",
        ")",
        "print(json.dumps({",
        "    'blocked_verified': blocked_verified,",
        "    'imported': imported,",
        "    'non_stdlib_tops': non_stdlib_tops,",
        "    'leaked_canary': leaked_canary,",
        "}))",
    ])

    proc = subprocess.run(
        [sys.executable, "-c", runner],
        cwd=str(ROOT),
        env=_clean_offline_env(),
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 0, f"stderr:\n{proc.stderr}\nstdout:\n{proc.stdout}"
    payload = json.loads(proc.stdout.strip().splitlines()[-1])
    assert payload["blocked_verified"] == blocked_probes
    assert payload["imported"] == mole_modules
    assert payload["leaked_canary"] == []
    unexpected_deps = set(payload["non_stdlib_tops"]) - VANILLA_NON_STDLIB_TOP_MODULES
    assert unexpected_deps == set(), f"non-vanilla dependencies loaded on import: {sorted(unexpected_deps)}"


def _run_verifier_check(spec: tuple[str, str]) -> tuple[str, int, str, str]:
    kind, target = spec
    if kind == "module":
        runner = "\n".join([
            "import runpy, sys",
            f"for _b in {list(BLOCKED_RUNTIME_MODULES)!r}:",
            "    sys.modules[_b] = None",
            f"sys.argv = [{target!r}, '--check']",
            f"runpy.run_module({target!r}, run_name='__main__')",
        ])
    elif kind == "script":
        runner = "\n".join([
            "import runpy, sys",
            f"for _b in {list(BLOCKED_RUNTIME_MODULES)!r}:",
            "    sys.modules[_b] = None",
            f"sys.argv = [{target!r}, '--check']",
            f"runpy.run_path({target!r}, run_name='__main__')",
        ])
    else:
        raise ValueError(f"unknown verifier kind: {kind}")

    proc = subprocess.run(
        [sys.executable, "-c", runner],
        cwd=str(ROOT),
        env=_clean_offline_env(),
        capture_output=True,
        text=True,
        timeout=90,
    )
    return (target, proc.returncode, proc.stdout, proc.stderr)


def test_all_pure_mole_verifiers_pass_check_offline_with_blocked_namespaces() -> None:
    specs: list[tuple[str, str]] = [("module", mod) for mod in REQUIRED_PURE_MOLE_VERIFIERS]
    for opt_mod in OPTIONAL_PURE_MOLE_VERIFIERS:
        opt_path = ROOT / (opt_mod.replace(".", "/") + ".py")
        if opt_path.is_file():
            specs.append(("module", opt_mod))
    specs.append(("script", str(EVAL_V14_SCRIPT)))

    assert len(specs) >= 10
    max_workers = min(6, len(specs))
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        results = list(pool.map(_run_verifier_check, specs))

    failures: list[str] = []
    for target, rc, out, err in results:
        if rc != 0:
            failures.append(f"{target} exited with rc={rc}\nSTDOUT:\n{out}\nSTDERR:\n{err}")
    assert failures == [], "\n\n".join(failures)


def test_zero_mole_files_collide_with_protected_paths() -> None:
    assert PROTECTED_PATHS_TXT.is_file()
    rules = load_protected_rules(PROTECTED_PATHS_TXT)
    assert "canary/env.py" in rules
    assert "canary/rules.py" in rules
    assert "canary/solver/" in rules
    assert "harbor/" in rules

    assert match_protected_rule("canary/env.py", rules) == "canary/env.py"
    assert match_protected_rule("canary/solver/policy.py", rules) == "canary/solver/"
    assert match_protected_rule("harbor/task.toml", rules) == "harbor/"
    assert match_protected_rule("data/runs/committed/ep.jsonl", rules) == "data/runs/committed/"

    mole_files = sorted(
        p for p in MOLE_DIR.rglob("*")
        if p.is_file() and "__pycache__" not in p.parts and p.suffix not in {".pyc", ".pyo"}
    )
    assert len(mole_files) >= 16

    collisions: list[str] = []
    for fpath in mole_files:
        rel_posix = fpath.relative_to(ROOT).as_posix()
        hit = match_protected_rule(rel_posix, rules)
        if hit is not None:
            collisions.append(f"{rel_posix} -> {hit}")

    assert collisions == [], f"canary/mole files collided with protected-paths.txt: {collisions}"
