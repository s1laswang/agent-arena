from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = ROOT / "docs" / "arena" / "py"
BRIDGE_SRC = ROOT / "docs" / "arena" / "arena_env_bridge.py"
MAX_BUNDLE_BYTES = 1_000_000

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
    "reproduce.py",
    "eval.py",
    "data/",
    "results/",
    "scripts/",
    "tests/",
)

_TRACE_CODE = """
import json
import sys
from pathlib import Path

root = Path(sys.argv[1]).resolve()
sys.path.insert(0, str(root))

from canary.env import Env
from canary.mole.dsl import MoleView
from canary.rules import TIERS_VERSION
from canary.solver.policy import SolverPolicy

for tier_name, seed_num in (("medium", 3000), ("hard", 6)):
    env = Env(tier_name, seed_num)
    env.call("list_employees", {})
    env.call("advance_day", {})
    pol = SolverPolicy()
    pol.reset(env.tools_spec(), env.instruction())
    pol.act(list(env.history))

_ = MoleView
paths = sorted({
    Path(mod.__file__).resolve().as_posix()
    for name, mod in list(sys.modules.items())
    if (name == "canary" or name.startswith("canary.")) and getattr(mod, "__file__", None)
})
print(json.dumps({"tiers_version": TIERS_VERSION, "paths": paths}))
"""

CANARY_GAME_SOURCE = """from __future__ import annotations

import json
from typing import Any

from canary.env import Env
from canary.rules import HELDOUT_SEEDS, JUDGE_SEEDS, TIERS_VERSION

TIER = "medium"
SEED_MIN, SEED_MAX = 3000, 9999
DUEL_SEED_MIN, DUEL_SEED_MAX = 0, 59
ALLOWED_TIERS = ("medium", "hard")
MAX_SOLVER_ITERS = 1000


def _strict_int(seed: Any) -> int:
    if isinstance(seed, (bool, float)) or seed is None:
        raise ValueError(f"seed must be an integer in {SEED_MIN}..{SEED_MAX}")
    try:
        s = int(seed)
    except (TypeError, ValueError):
        raise ValueError(f"seed must be an integer in {SEED_MIN}..{SEED_MAX}") from None
    if str(seed).strip() != str(s):
        raise ValueError(f"seed must be an integer in {SEED_MIN}..{SEED_MAX}")
    return s


def check_seed(seed: Any) -> int:
    s = _strict_int(seed)
    if s in JUDGE_SEEDS or s in HELDOUT_SEEDS or not (SEED_MIN <= s <= SEED_MAX):
        raise ValueError(f"seed must be an integer in {SEED_MIN}..{SEED_MAX} (public dev seeds)")
    return s


def _check_extended_seed(seed: Any, tier: str, mode: str | None) -> int:
    s = _strict_int(seed)
    if s in JUDGE_SEEDS or s in HELDOUT_SEEDS or s >= 800_000 or s < 0:
        raise ValueError("benchmark and negative seeds are refused")
    if SEED_MIN <= s <= SEED_MAX:
        return s
    if DUEL_SEED_MIN <= s <= DUEL_SEED_MAX and (mode in ("duel", "living") or (mode is None and tier == "hard")):
        return s
    raise ValueError(f"seed must be an integer in {SEED_MIN}..{SEED_MAX} (public dev seeds)")


class Game:
    def __init__(self, seed: Any, tier: str | None = None, mode: str | None = None) -> None:
        if tier is None and mode is None:
            resolved_tier = TIER
            resolved_seed = check_seed(seed)
        else:
            resolved_tier = TIER if tier is None else str(tier).strip()
            if resolved_tier not in ALLOWED_TIERS:
                raise ValueError(f"tier must be one of {ALLOWED_TIERS}")
            norm_mode = None if mode is None else str(mode).strip().lower()
            resolved_seed = _check_extended_seed(seed, resolved_tier, norm_mode)
        self.tier = resolved_tier
        self.seed = resolved_seed
        self.env = Env(self.tier, self.seed)
        self.actions: list[list[Any]] = []

    def spec_json(self) -> str:
        return json.dumps(
            {
                "tier": self.tier,
                "seed": self.seed,
                "tiers_version": TIERS_VERSION,
                "tools": self.env.tools_spec(),
                "instruction": self.env.instruction(),
            }
        )

    def call_json(self, tool: str, args_json: str) -> str:
        try:
            args = json.loads(args_json) if args_json else {}
        except ValueError:
            return json.dumps(
                {
                    "ok": False,
                    "data": {},
                    "error": "arguments are not valid JSON",
                    "done": self.env.done,
                }
            )
        if not isinstance(args, dict):
            return json.dumps(
                {
                    "ok": False,
                    "data": {},
                    "error": "arguments must be a JSON object",
                    "done": self.env.done,
                }
            )
        res = self.env.call(tool, args)
        self.actions.append([tool, args])
        return json.dumps(
            {"ok": res.ok, "data": res.data, "error": res.error, "done": self.env.done},
            default=str,
        )

    def reveal_json(self) -> str:
        if not self.env.done:
            return json.dumps({"error": "the episode is not over yet"})
        v = self.env.verdict()
        return json.dumps(
            {
                "seed": self.seed,
                "tier": self.tier,
                "tiers_version": TIERS_VERSION,
                "you": {
                    "score": v["score"],
                    "end_reason": v["end_reason"],
                    "accused": v["accused"],
                    "correct": v["correct"],
                    "final_day": v["final_day"],
                    "tool_calls": len(self.actions),
                },
                "mole": self.env._world.mole,
                "solver": solver_result(self.seed, tier=self.tier),
            }
        )

    def actions_json(self) -> str:
        return json.dumps(
            {
                "tier": self.tier,
                "seed": self.seed,
                "tiers_version": TIERS_VERSION,
                "actions": self.actions,
            }
        )


def solver_result(seed: int, tier: str | None = None) -> dict[str, Any]:
    from canary.solver.policy import SolverPolicy

    if tier is None:
        resolved_tier = TIER
        resolved_seed = check_seed(seed)
    else:
        resolved_tier = str(tier).strip()
        if resolved_tier not in ALLOWED_TIERS:
            raise ValueError(f"tier must be one of {ALLOWED_TIERS}")
        resolved_seed = _check_extended_seed(seed, resolved_tier, "duel" if resolved_tier == "hard" else None)
    env = Env(resolved_tier, resolved_seed)
    pol = SolverPolicy()
    pol.reset(env.tools_spec(), env.instruction())
    for _ in range(MAX_SOLVER_ITERS):
        if env.done:
            break
        tool, args = pol.act(list(env.history))
        env.call(tool, args)
    v = env.verdict()
    return {
        "score": v["score"],
        "correct": v["correct"],
        "final_day": v["final_day"],
        "tool_calls": len(env.history),
    }


def replay(seed: Any, actions: list[list[Any]], tier: str | None = None) -> dict[str, Any]:
    g = Game(seed, tier=tier, mode="duel" if tier == "hard" else None)
    for tool, args in actions:
        g.call_json(tool, json.dumps(args))
    return g.env.verdict()
"""


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def traced_modules(repo_root: Path = ROOT) -> tuple[str, list[Path]]:
    resolved_root = repo_root.resolve()
    proc = subprocess.run(
        [sys.executable, "-c", _TRACE_CODE, str(resolved_root)],
        capture_output=True,
        text=True,
        check=True,
        cwd=resolved_root,
    )
    payload = json.loads(proc.stdout.strip().splitlines()[-1])
    tiers_ver = str(payload["tiers_version"])
    files = sorted(Path(p).resolve() for p in payload["paths"])
    return tiers_ver, files


def validate_manifest_entry(rel_posix: str) -> None:
    if not rel_posix or rel_posix.startswith("/") or ".." in rel_posix.split("/"):
        raise ValueError(f"invalid relative manifest path: {rel_posix!r}")
    for tok in FORBIDDEN_MANIFEST_TOKENS:
        if tok in rel_posix:
            raise ValueError(f"forbidden token {tok!r} in manifest entry {rel_posix!r}")


def expected_bundle_map(repo_root: Path = ROOT) -> tuple[str, dict[str, bytes]]:
    resolved_root = repo_root.resolve()
    tiers_ver, mod_paths = traced_modules(resolved_root)
    bridge_path = resolved_root / "docs" / "arena" / "arena_env_bridge.py"
    if not bridge_path.is_file():
        raise FileNotFoundError(f"missing bridge module: {bridge_path}")

    bundle: dict[str, bytes] = {}
    for mod_path in mod_paths:
        rel = mod_path.relative_to(resolved_root).as_posix()
        if not rel.startswith("canary/"):
            raise ValueError(f"traced module outside canary/: {rel}")
        validate_manifest_entry(rel)
        bundle[rel] = mod_path.read_bytes()

    bridge_bytes = bridge_path.read_bytes()
    for wrapper_name in ("arena_env_bridge.py", "arena_game.py"):
        validate_manifest_entry(wrapper_name)
        bundle[wrapper_name] = bridge_bytes

    validate_manifest_entry("canary_game.py")
    bundle["canary_game.py"] = CANARY_GAME_SOURCE.encode("utf-8")
    return tiers_ver, dict(sorted(bundle.items()))


def render_manifest_dict(tiers_version: str, bundle_map: dict[str, bytes]) -> dict[str, Any]:
    sorted_files = sorted(bundle_map.keys())
    for rel in sorted_files:
        validate_manifest_entry(rel)
    return {
        "files": sorted_files,
        "tiers_version": tiers_version,
        "sha256": {rel: _sha256_bytes(bundle_map[rel]) for rel in sorted_files},
    }


def render_manifest_json(manifest: dict[str, Any]) -> str:
    return json.dumps(manifest, indent=2, sort_keys=False) + "\n"


def build(out_dir: Path = DEFAULT_OUT, repo_root: Path = ROOT) -> dict[str, Any]:
    tiers_ver, bundle_map = expected_bundle_map(repo_root)
    total_bytes = sum(len(b) for b in bundle_map.values())
    if total_bytes >= MAX_BUNDLE_BYTES:
        raise ValueError(f"bundle size {total_bytes} exceeds cap {MAX_BUNDLE_BYTES}")

    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    for rel, raw in bundle_map.items():
        dst = out_dir / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(raw)

    manifest = render_manifest_dict(tiers_ver, bundle_map)
    manifest_text = render_manifest_json(manifest)
    (out_dir / "manifest.json").write_text(manifest_text, encoding="utf-8")
    return manifest


def check_bundle(out_dir: Path = DEFAULT_OUT, repo_root: Path = ROOT) -> tuple[bool, list[str]]:
    errors: list[str] = []
    if not out_dir.is_dir():
        return False, [f"missing bundle directory: {out_dir}"]

    manifest_path = out_dir / "manifest.json"
    if not manifest_path.is_file():
        return False, [f"missing manifest: {manifest_path}"]

    try:
        tiers_ver, expected_map = expected_bundle_map(repo_root)
    except Exception as exc:
        return False, [f"failed to trace expected bundle: {exc}"]

    expected_manifest = render_manifest_dict(tiers_ver, expected_map)
    expected_manifest_txt = render_manifest_json(expected_manifest)

    try:
        actual_manifest_txt = manifest_path.read_text(encoding="utf-8")
        actual_manifest = json.loads(actual_manifest_txt)
    except Exception as exc:
        return False, [f"invalid manifest JSON: {exc}"]

    if actual_manifest != expected_manifest:
        errors.append("manifest.json content mismatch against traced canary runtime")
    if actual_manifest_txt != expected_manifest_txt:
        errors.append("manifest.json formatting differs from deterministic output")

    disk_files = sorted(
        p.relative_to(out_dir).as_posix()
        for p in out_dir.rglob("*")
        if p.is_file() and p.name != "manifest.json" and "__pycache__" not in p.parts and p.suffix not in {".pyc", ".pyo"}
    )
    expected_files = sorted(expected_map.keys())
    if disk_files != expected_files:
        missing = sorted(set(expected_files) - set(disk_files))
        extra = sorted(set(disk_files) - set(expected_files))
        if missing:
            errors.append(f"missing bundled files: {missing}")
        if extra:
            errors.append(f"unexpected extra files in bundle: {extra}")

    total_bytes = manifest_path.stat().st_size
    for rel, exp_bytes in expected_map.items():
        try:
            validate_manifest_entry(rel)
        except ValueError as exc:
            errors.append(str(exc))
            continue
        fp = out_dir / rel
        if not fp.is_file():
            continue
        act_bytes = fp.read_bytes()
        total_bytes += len(act_bytes)
        if act_bytes != exp_bytes:
            errors.append(f"byte mismatch for {rel}")

    if total_bytes >= MAX_BUNDLE_BYTES:
        errors.append(f"bundle total size {total_bytes} >= {MAX_BUNDLE_BYTES}")

    return len(errors) == 0, errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build or verify the Canary Arena Pyodide bundle.")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="Target Pyodide bundle directory")
    parser.add_argument("--check", action="store_true", help="Verify existing bundle matches repo byte-for-byte")
    args = parser.parse_args(argv)

    if args.check:
        ok, errs = check_bundle(out_dir=args.out, repo_root=ROOT)
        if not ok:
            for item in errs:
                print(f"FAIL: {item}", file=sys.stderr)
            return 1
        manifest = json.loads((args.out / "manifest.json").read_text(encoding="utf-8"))
        print(f"PASS: {args.out} verified ({len(manifest['files'])} python files, tiers {manifest['tiers_version']})")
        return 0

    manifest = build(out_dir=args.out, repo_root=ROOT)
    print(f"built {args.out}: {len(manifest['files'])} python files (tiers {manifest['tiers_version']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
