from __future__ import annotations

import hashlib
import io
import json
import shutil
import subprocess
import sys
import tokenize
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from canary.env import Env
from canary.eval import make_env, run_episode
from canary.rules import HELDOUT_SEEDS, JUDGE_SEEDS, TIERS_VERSION
from canary.solver.policy import SolverPolicy
from scripts import build_arena_pyodide as builder

BUNDLE_DIR = ROOT / "docs" / "arena" / "py"
MANIFEST_PATH = BUNDLE_DIR / "manifest.json"
BRIDGE_PATH = ROOT / "docs" / "arena" / "arena_env_bridge.py"
BUILDER_PATH = ROOT / "scripts" / "build_arena_pyodide.py"
SELF_TEST_PATH = Path(__file__).resolve()

HASH_CH = chr(35)
EM_DASH = chr(0x2014)
EN_DASH = chr(0x2013)
UNICODE_MINUS = chr(0x2212)
SLASH_SLASH = chr(47) * 2
SLASH_STAR = chr(47) + chr(42)

FORBIDDEN_TOKENS = (
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
)

PROTECTED_GIT_TARGETS = (
    "canary/env.py",
    "canary/rules.py",
    "canary/reproduce.py",
    "canary/solver",
    "harbor",
)


def test_authored_files_pure_ascii_and_zero_comments() -> None:
    authored = (
        SELF_TEST_PATH,
        BUILDER_PATH,
        BRIDGE_PATH,
        BUNDLE_DIR / "arena_env_bridge.py",
        BUNDLE_DIR / "arena_game.py",
        BUNDLE_DIR / "canary_game.py",
        MANIFEST_PATH,
    )
    for fpath in authored:
        assert fpath.is_file(), f"missing file: {fpath}"
        raw = fpath.read_text(encoding="utf-8")
        assert raw.isascii(), f"non-ASCII character in {fpath}"
        assert EM_DASH not in raw
        assert EN_DASH not in raw
        assert UNICODE_MINUS not in raw
        assert HASH_CH not in raw, f"comment marker in {fpath}"
        assert SLASH_SLASH not in raw
        assert SLASH_STAR not in raw
        if fpath.suffix == ".py":
            tokens = list(tokenize.generate_tokens(io.StringIO(raw).readline))
            comments = [tok for tok in tokens if tok.type == tokenize.COMMENT]
            assert comments == [], f"python comment found in {fpath}"

    bridge_src = BRIDGE_PATH.read_text(encoding="utf-8")
    assert "self.env" not in bridge_src


def test_bundle_check_cli_and_tamper_detection(tmp_path: Path) -> None:
    proc = subprocess.run(
        [sys.executable, str(BUILDER_PATH), "--check"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr

    scratch_bundle = tmp_path / "py"
    built_manifest = builder.build(out_dir=scratch_bundle, repo_root=ROOT)
    assert isinstance(built_manifest["files"], list)
    ok, errs = builder.check_bundle(out_dir=scratch_bundle, repo_root=ROOT)
    assert ok is True and errs == []

    extra_file = scratch_bundle / "stray_extra.py"
    extra_file.write_text("X = 1\n", encoding="utf-8")
    ok_extra, errs_extra = builder.check_bundle(out_dir=scratch_bundle, repo_root=ROOT)
    assert ok_extra is False
    assert any("unexpected extra files" in e for e in errs_extra)
    extra_file.unlink()

    target_py = scratch_bundle / "canary" / "types.py"
    orig_bytes = target_py.read_bytes()
    target_py.write_bytes(orig_bytes + b"\n")
    ok_tamper, errs_tamper = builder.check_bundle(out_dir=scratch_bundle, repo_root=ROOT)
    assert ok_tamper is False
    assert any("byte mismatch" in e for e in errs_tamper)


def test_manifest_completeness_sha256_size_and_zero_forbidden_files() -> None:
    assert MANIFEST_PATH.is_file()
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    assert manifest["tiers_version"] == TIERS_VERSION == "v1.4"
    files = manifest["files"]
    sha_map = manifest["sha256"]
    assert isinstance(files, list) and len(files) >= 16
    assert files == sorted(files)

    total_bytes = MANIFEST_PATH.stat().st_size
    for rel in files:
        assert not rel.startswith("/")
        assert ".." not in rel.split("/")
        for tok in FORBIDDEN_TOKENS:
            assert tok not in rel, f"forbidden token {tok} in {rel}"
        bundled_fp = BUNDLE_DIR / rel
        assert bundled_fp.is_file(), f"missing bundled file {bundled_fp}"
        raw = bundled_fp.read_bytes()
        total_bytes += len(raw)
        digest = hashlib.sha256(raw).hexdigest()
        assert sha_map[rel] == digest
        if rel.startswith("canary/"):
            repo_fp = ROOT / rel
            assert repo_fp.read_bytes() == raw, f"byte drift vs repo {rel}"

    assert BUNDLE_DIR.joinpath("arena_env_bridge.py").read_bytes() == BRIDGE_PATH.read_bytes()
    assert BUNDLE_DIR.joinpath("arena_game.py").read_bytes() == BRIDGE_PATH.read_bytes()
    assert total_bytes < 1_000_000


def test_hermetic_isolated_python_bundle_and_forbidden_imports() -> None:
    ref_med = run_episode(make_env("medium", 3000), SolverPolicy())
    ref_hard_6 = run_episode(make_env("hard", 6), SolverPolicy())
    ref_hard_26 = run_episode(make_env("hard", 26), SolverPolicy())

    probe = """
import importlib
import json
import sys

bundle_dir = sys.argv[1]
repo_root = sys.argv[2]
sys.path = [
    p for p in sys.path
    if p and "site-packages" not in p and "dist-packages" not in p and p != repo_root
]
sys.path.insert(0, bundle_dir)

forbidden_mods = [
    "canary.eval",
    "canary.reproduce",
    "canary.analysis.gap",
    "canary.mcp_server",
    "mcp_server",
    "canary.text.gemini",
    "redteam",
]
for mod_name in forbidden_mods:
    try:
        importlib.import_module(mod_name)
    except ModuleNotFoundError:
        pass
    else:
        raise AssertionError(f"forbidden module imported in isolated bundle: {mod_name}")

from canary.env import Env
from canary.solver.policy import SolverPolicy
import canary_game
import arena_game

def run_iso(tier, seed):
    env = Env(tier, seed)
    pol = SolverPolicy()
    pol.reset(env.tools_spec(), env.instruction())
    while not env.done:
        t, a = pol.act(list(env.history))
        env.call(t, a)
    v = env.verdict()
    return {
        "accused": v["accused"],
        "score": v["score"],
        "correct": v["correct"],
        "final_day": v["final_day"],
        "tool_calls": len(env.history),
    }

for bad in (0, 29, 2999, 10000, 800000, 800029, 900000, 900039, -1, True, 3000.0, "3000.0", "3e3", None, "abc"):
    try:
        canary_game.Game(bad)
    except ValueError:
        pass
    else:
        raise AssertionError(f"canary_game.Game accepted bad seed: {bad!r}")

g3000 = canary_game.Game(3000)
assert g3000.env.history == []
spec_str = g3000.spec_json()
assert g3000.env._world.mole not in spec_str
rev_pre = json.loads(g3000.reveal_json())
assert "error" in rev_pre and "mole" not in rev_pre

out = {
    "med_3000": run_iso("medium", 3000),
    "hard_6": run_iso("hard", 6),
    "hard_26": run_iso("hard", 26),
    "cg_solver_3000": canary_game.solver_result(3000),
    "ag_solver_6": arena_game.solver_result("hard", 6),
    "ag_solver_26": arena_game.solver_result(26, "hard"),
}
print(json.dumps(out))
"""
    proc = subprocess.run(
        [sys.executable, "-I", "-S", "-c", probe, str(BUNDLE_DIR), str(ROOT)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    iso = json.loads(proc.stdout.strip().splitlines()[-1])

    assert iso["med_3000"]["score"] == pytest.approx(ref_med.score, abs=1e-12)
    assert iso["med_3000"]["accused"] == ref_med.accused
    assert iso["med_3000"]["correct"] == ref_med.correct
    assert iso["med_3000"]["final_day"] == ref_med.final_day
    assert iso["med_3000"]["tool_calls"] == len(ref_med.steps)

    assert iso["cg_solver_3000"]["score"] == pytest.approx(ref_med.score, abs=1e-12)
    assert iso["cg_solver_3000"]["final_day"] == ref_med.final_day
    assert iso["cg_solver_3000"]["tool_calls"] == len(ref_med.steps)

    for key, ref in (("hard_6", ref_hard_6), ("hard_26", ref_hard_26)):
        assert iso[key]["score"] == pytest.approx(ref.score, abs=1e-12)
        assert iso[key]["accused"] == ref.accused
        assert iso[key]["correct"] == ref.correct
        assert iso[key]["final_day"] == ref.final_day
        assert iso[key]["tool_calls"] == len(ref.steps)

    assert iso["ag_solver_6"]["score"] == pytest.approx(ref_hard_6.score, abs=1e-12)
    assert iso["ag_solver_26"]["score"] == pytest.approx(ref_hard_26.score, abs=1e-12)


def test_arena_env_bridge_seed_firewall_unsurfaced_v_and_solver_seal() -> None:
    from docs.arena import arena_env_bridge as bridge

    for bad_seed in (
        *JUDGE_SEEDS,
        *range(min(HELDOUT_SEEDS), min(HELDOUT_SEEDS) + 30),
        -1,
        60,
        2999,
        10000,
        100000,
        True,
        False,
        3000.0,
        "3000.0",
        "3e3",
        None,
        "abc",
    ):
        with pytest.raises(ValueError):
            bridge.Game("hard", bad_seed)
        with pytest.raises(ValueError):
            bridge.check_seed(bad_seed)

    with pytest.raises(ValueError):
        bridge.Game("medium", 6, mode="solver")
    with pytest.raises(ValueError):
        bridge.Game("medium", 26, mode="mole")

    ag = bridge.Game("hard", 26, "duel")
    assert not hasattr(ag, "env")
    assert ag.history_len() == 0
    spec_obj = json.loads(ag.spec_json())
    assert spec_obj["tier"] == "hard" and spec_obj["seed"] == 26 and len(spec_obj["tools"]) == 13
    true_mole_26 = Env("hard", 26)._world.mole
    assert true_mole_26 not in json.dumps(spec_obj)
    assert ag.history_len() == 0

    pre_rev = json.loads(ag.reveal_json())
    assert pre_rev == {"error": "the episode is not over yet"}
    assert "mole" not in pre_rev

    bad_call = json.loads(ag.call_json("interview", "{bad"))
    assert bad_call["ok"] is False
    assert ag.history_len() == 0

    g_med = bridge.Game("medium", 3000, "solver")
    ref_env = Env("medium", 3000)
    for _ in range(4):
        step_out = json.loads(g_med.call_json("advance_day", "{}"))
        ref_env.call("advance_day", {})
        assert step_out["ok"] is True
        assert step_out["data"]["V"] == pytest.approx(ref_env.visible_V(), abs=1e-12)
    st_out = json.loads(g_med.call_json("status", "{}"))
    ref_env.call("status", {})
    assert abs(ref_env.V - ref_env.visible_V()) > 1e-9
    assert st_out["data"]["V"] == pytest.approx(ref_env.visible_V(), abs=1e-12)

    day_pre = json.loads(bridge.solver_day_state_json("hard", 6, day=6, done=False))
    assert day_pre["status"] == "sealed_accusation"
    assert day_pre["final"] is None
    assert "mole" not in day_pre and "accused" not in day_pre
    true_mole_6 = Env("hard", 6)._world.mole
    assert true_mole_6 not in json.dumps(day_pre)

    day_post = json.loads(bridge.solver_day_state_json("hard", 6, day=6, done=True))
    assert day_post["status"] == "done"
    assert day_post["final"]["accused"] == true_mole_6
    assert day_post["final"]["correct"] is True
    assert day_post["final"]["final_day"] == 6
    assert day_post["final"]["tool_calls"] == 52

    sess = bridge.SolverSession("hard", 6)
    seen_sealed = False
    for _ in range(80):
        st = bridge.solver_step(sess)
        assert true_mole_6 not in json.dumps(st)
        if st["sealed"]:
            seen_sealed = True
        if st["done"]:
            break
    assert seen_sealed is True
    assert "error" in sess.reveal(human_done=False)
    rev_ok = sess.reveal(human_done=True)
    assert rev_ok["accused"] == true_mole_6 and rev_ok["correct"] is True


def test_zero_protected_paths_modified() -> None:
    git_bin = shutil.which("git")
    if git_bin is None:
        return
    proc = subprocess.run(
        [git_bin, "diff", "--name-only", "origin/justSilas", "--", *PROTECTED_GIT_TARGETS],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode == 0:
        assert proc.stdout.strip() == ""
