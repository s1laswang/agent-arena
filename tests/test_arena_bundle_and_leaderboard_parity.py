from __future__ import annotations

import dataclasses
import importlib.util
import io
import json
import math
import sys
import tokenize
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) in sys.path:
    sys.path.remove(str(ROOT))
sys.path.insert(0, str(ROOT))

SCRIPT_PATH = ROOT / "scripts" / "verify_arena_bundle_parity.py"
THIS_TEST_PATH = Path(__file__).resolve()
EN_DASH = chr(0x2013)
EM_DASH = chr(0x2014)
HASH_CHAR = chr(0x23)


def _load_verifier_module():
    spec = importlib.util.spec_from_file_location("verify_arena_bundle_parity", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


verify = _load_verifier_module()


@pytest.fixture(scope="module")
def real_gates_and_episodes() -> tuple[list[Any], list[Any]]:
    g1, episodes = verify.verify_pyodide_bundle_isolation_parity(root=ROOT)
    g2 = verify.verify_leaderboard_and_summary_parity(real_episodes=episodes)
    g3 = verify.verify_docs_arena_autodiscovery(root=ROOT)
    return [g1, g2, g3], episodes


def test_all_gates_pass_and_cleanup_opencode_tmp(real_gates_and_episodes):
    gates, _ = real_gates_and_episodes
    assert [g.gate for g in gates] == [
        "pyodide_bundle_isolation_parity",
        "leaderboard_and_summary_math_parity",
        "docs_arena_autodiscovery",
    ]
    for g in gates:
        assert g.passed, f"{g.gate} failed: {g.violations}"

    g1 = gates[0]
    assert g1.data["medium_seeds"] == [3000, 3001, 3002]
    assert g1.data["hard_seeds"] == [3000, 3001, 3002]
    assert g1.data["cases_verified"] == 12
    assert g1.data["solver_seeds_verified"] == 6
    assert g1.data["tmp_dir_cleaned_after_gate"] is True


def test_cli_check_and_json_output(capsys):
    with verify.temporary_opencode_dir("test_arena_cli_root_") as fake_root:
        game_src = ROOT / "game"
        (fake_root / "game").symlink_to(game_src, target_is_directory=True)
        rc = verify.main(["--check", "--json", "--root", str(fake_root)])
        assert rc == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["passed"] is True
        assert payload["check_mode"] is True
        assert len(payload["gates"]) == 3
        assert all(g["passed"] is True for g in payload["gates"])


def test_isolated_bundle_blocks_repo_modules_and_catches_tamper():
    cases, solver_refs, _ = verify._build_reference_cases()
    sample_cases = [cases[0], next(c for c in cases if c["tier"] == "hard")]
    sample_solvers = [solver_refs[0], next(s for s in solver_refs if s["tier"] == "hard")]

    with verify.temporary_opencode_dir("test_arena_iso_") as tmp_dir:
        site_dir = tmp_dir / "site"
        game_build = verify._load_game_build_module(ROOT)
        game_build.build(site_dir)

        errs, iso_out = verify.run_isolated_bundle_check(
            py_dir=site_dir / "py",
            cases=sample_cases,
            solver_refs=sample_solvers,
            repo_root=ROOT,
            work_tmp_dir=tmp_dir / "clean_run",
            require_canary_game=True,
        )
        assert errs == []
        assert iso_out["outside_bundle"] == []
        assert iso_out["seed_guards_ok"] is True
        assert iso_out["pre_end_guard_ok"] is True
        for blocked_mod in (
            "canary.eval",
            "canary.reproduce",
            "canary.analysis.gap",
            "canary.mcp_server",
            "mcp_server",
            "canary.text.gemini",
            "redteam",
        ):
            assert iso_out["blocked_imports"][blocked_mod] is True

        tampered_case = dict(sample_cases[0])
        tampered_case["expected_score"] = round(float(tampered_case["expected_score"]) + 0.01, 10)
        tampered_case["expected_score_bits"] = verify._float_bits(tampered_case["expected_score"])
        tamper_errs, _ = verify.run_isolated_bundle_check(
            py_dir=site_dir / "py",
            cases=[tampered_case],
            solver_refs=[],
            repo_root=ROOT,
            work_tmp_dir=tmp_dir / "tamper_run",
            require_canary_game=True,
        )
        assert any("score mismatch" in e for e in tamper_errs)


def test_real_zero_v_correct_accusation_and_leaderboard_parity():
    from canary.analysis.gap import mean_ci
    from canary.baselines import DoNothing
    from canary.env import Env
    from canary.eval import format_table, run_episode, summarize

    mole_3000 = Env("medium", 3000)._world.mole
    wrong_3000 = "e00" if mole_3000 != "e00" else "e01"

    env_zv_win = Env("medium", 3000)
    ep_zv_win = run_episode(
        env_zv_win,
        verify.RecordedActionsPolicy(
            verify._build_zero_v_actions_for_medium_seed(3000, mole_3000),
            name="arena_player",
        ),
    )
    assert ep_zv_win.end_reason == "accused"
    assert ep_zv_win.correct is True
    assert ep_zv_win.score == 0.0
    assert ep_zv_win.meta["V"] == 0.0

    env_zv_wrong = Env("medium", 3000)
    ep_zv_wrong = run_episode(
        env_zv_wrong,
        verify.RecordedActionsPolicy(
            verify._build_zero_v_actions_for_medium_seed(3000, wrong_3000),
            name="arena_player",
        ),
    )
    assert ep_zv_wrong.end_reason == "accused"
    assert ep_zv_wrong.correct is False
    assert ep_zv_wrong.score == -1.0
    assert ep_zv_wrong.meta["V"] == 0.0

    ep_abstain = run_episode(Env("medium", 3001), DoNothing(seed=3001))
    assert ep_abstain.end_reason == "horizon"
    assert ep_abstain.score == 0.0
    assert ep_abstain.accused is None

    eps = [ep_zv_win, ep_zv_wrong, ep_abstain]
    records = [verify.episode_to_arena_record(e) for e in eps]

    arena_sum = verify.aggregate_arena_leaderboard(records)
    eval_sum = summarize(eps)
    assert arena_sum["n"] == eval_sum["n"] == 3
    assert arena_sum["accused"] == eval_sum["accused"] == 2
    assert abs(arena_sum["accuracy"] - eval_sum["accuracy"]) <= 1e-12
    assert abs(arena_sum["accuracy"] - (1.0 / 3.0)) <= 1e-12
    assert abs(arena_sum["accuse_day"] - eval_sum["accuse_day"]) <= 1e-12
    assert abs(arena_sum["mean"] - eval_sum["mean"]) <= 1e-12
    assert abs(arena_sum["ci"] - eval_sum["ci"]) <= 1e-12

    gm, gh = mean_ci([e.score for e in eps])
    assert abs(arena_sum["mean"] - gm) <= 1e-12
    assert abs(arena_sum["ci"] - gh) <= 1e-12

    arena_tbl = verify.format_arena_leaderboard_table("arena_player", {"medium": records, "hard": []})
    eval_tbl = format_table("arena_player", {"medium": eps, "hard": []})
    assert arena_tbl == eval_tbl

    abstain_only_sum = verify.aggregate_arena_leaderboard([verify.episode_to_arena_record(ep_abstain)])
    assert abstain_only_sum["accused"] == 0
    assert math.isnan(abstain_only_sum["accuse_day"])
    assert verify.format_arena_metric(abstain_only_sum["accuse_day"], 1) == "-"


def test_docs_arena_autodiscovery_clean_and_tampered():
    from canary.baselines import StopEarly
    from canary.env import Env
    from canary.eval import run_episode

    with verify.temporary_opencode_dir("test_docs_arena_") as fake_root:
        absent_gate = verify.verify_docs_arena_autodiscovery(root=fake_root)
        assert absent_gate.passed is True
        assert absent_gate.data["present"] is False

        arena_dir = fake_root / "docs" / "arena"
        game_build = verify._load_game_build_module(ROOT)
        game_build.build(arena_dir)

        ep_m = run_episode(Env("medium", 3000), StopEarly(seed=3000))
        ep_h = run_episode(Env("hard", 3000), StopEarly(seed=3000))
        (arena_dir / "episodes.jsonl").write_text(
            "\n".join(json.dumps(dataclasses.asdict(e), sort_keys=True) for e in (ep_m, ep_h)) + "\n",
            encoding="utf-8",
        )
        (arena_dir / "sample_actions.json").write_text(
            json.dumps(
                {
                    "tier": "medium",
                    "seed": 3000,
                    "actions": [[s.tool, s.args] for s in ep_m.steps],
                    "score": ep_m.score,
                    "accused": ep_m.accused,
                    "correct": ep_m.correct,
                    "final_day": ep_m.final_day,
                }
            ),
            encoding="utf-8",
        )

        clean_gate = verify.verify_docs_arena_autodiscovery(root=fake_root)
        assert clean_gate.passed is True, clean_gate.violations
        assert clean_gate.data["present"] is True
        assert clean_gate.data["manifests_checked"] == 1
        assert clean_gate.data["episodes_replayed"] == 3

        fake_api_key = "AIza" + ("B" * 32)
        (arena_dir / "leak_secret.js").write_text(f'const k = "{fake_api_key}";\n', encoding="utf-8")
        (arena_dir / "leak_mole.html").write_text('<script>const gt = {"mole_id": "e07"};</script>\n', encoding="utf-8")
        (arena_dir / "leak_mole_js.js").write_text("const truth = { mole_id: 'e12' };\n", encoding="utf-8")

        tampered_ep = dataclasses.asdict(ep_m)
        tampered_ep["score"] = round(float(ep_m.score) + 0.25, 6)
        (arena_dir / "episodes.jsonl").write_text(json.dumps(tampered_ep) + "\n", encoding="utf-8")

        manifest_obj = json.loads((arena_dir / "py" / "manifest.json").read_text(encoding="utf-8"))
        manifest_obj["files"].append("missing_ghost_module.py")
        (arena_dir / "py" / "manifest.json").write_text(json.dumps(manifest_obj), encoding="utf-8")

        bad_gate = verify.verify_docs_arena_autodiscovery(root=fake_root)
        assert bad_gate.passed is False
        joined = "\n".join(bad_gate.violations)
        assert "google_api_key" in joined
        assert "mole_ground_truth_json" in joined
        assert "mole_ground_truth_js" in joined
        assert "score mismatch" in joined
        assert "missing file referenced in manifest" in joined


def test_duel_post_done_reveal_allowed_and_judge_salt_pyodide_paths_blocked():
    from canary.env import Env
    from canary.eval import run_episode
    from canary.solver.policy import SolverPolicy

    ep6 = run_episode(Env("hard", 6), SolverPolicy())
    ep26 = run_episode(Env("hard", 26), SolverPolicy())
    mole6 = Env("hard", 6)._world.mole
    mole26 = Env("hard", 26)._world.mole

    with verify.temporary_opencode_dir("test_duel_reveal_") as fake_root:
        salt_dir = fake_root / "data" / "worlds" / "judge"
        salt_dir.mkdir(parents=True, exist_ok=True)
        fake_salt_bytes = b"SECRET_JUDGE_SALT_TOKEN_987654321"
        (salt_dir / "SALT").write_bytes(fake_salt_bytes + b"\n")

        arena_dir = fake_root / "docs" / "arena"
        game_build = verify._load_game_build_module(ROOT)
        game_build.build(arena_dir)

        data_dir = arena_dir / "data"
        data_dir.mkdir(parents=True, exist_ok=True)

        duel_pack_obj = {
            "6": {
                "tier": "hard",
                "seed": 6,
                "unlockPostGameReveal": {"done": True, "mole": mole6, "true_mole": mole6},
            },
            "26": {
                "tier": "hard",
                "seed": 26,
                "sealed_reveal": {"mole": mole26, "mole_id": mole26},
            },
        }
        duel_js = (
            "export const CANARY_DUEL_PACK = "
            + json.dumps(duel_pack_obj)
            + ";\n"
            + "export function unlockPostGameReveal(seed, st) {\n"
            + "  if (!st || st.done !== true) return null;\n"
            + f"  return seed === 6 ? {{ mole: '{mole6}' }} : seed === 26 ? {{ mole: '{mole26}' }} : null;\n"
            + "}\n"
        )
        (data_dir / "duel_pack.js").write_text(duel_js, encoding="utf-8")

        gemini_replays_obj = {
            "6": {
                "tier": "hard",
                "seed": 6,
                "agent": "solver",
                "steps": [dataclasses.asdict(s) for s in ep6.steps],
                "final": {
                    "score": ep6.score,
                    "accused": ep6.accused,
                    "correct": ep6.correct,
                    "final_day": ep6.final_day,
                    "tool_calls": len(ep6.steps),
                },
                "post_game": {"mole": mole6},
            },
            "26": {
                "tier": "hard",
                "seed": 26,
                "agent": "solver",
                "steps": [dataclasses.asdict(s) for s in ep26.steps],
                "final": {
                    "score": ep26.score,
                    "accused": ep26.accused,
                    "correct": ep26.correct,
                    "final_day": ep26.final_day,
                    "tool_calls": len(ep26.steps),
                },
                "reveal": {"mole": mole26},
            },
        }
        (data_dir / "gemini_replays.json").write_text(
            json.dumps(gemini_replays_obj, indent=2),
            encoding="utf-8",
        )
        (arena_dir / "SEEDS.md").write_text(
            f"Seed 6 post-game culprit: `{mole6}`; Seed 26 post-game culprit: `{mole26}`.\n",
            encoding="utf-8",
        )

        clean_gate = verify.verify_docs_arena_autodiscovery(root=fake_root)
        assert clean_gate.passed is True, clean_gate.violations
        assert clean_gate.data["episodes_replayed"] == 2

        (arena_dir / "py" / "data").mkdir(parents=True, exist_ok=True)
        (arena_dir / "py" / "data" / "forbidden.json").write_text("{}", encoding="utf-8")
        (arena_dir / "py" / "harbor").mkdir(parents=True, exist_ok=True)
        (arena_dir / "py" / "harbor" / "task.txt").write_text("nope", encoding="utf-8")
        (arena_dir / "py" / "SALT").write_text("bad", encoding="utf-8")
        (data_dir / "salt_leak.js").write_bytes(b'const x = "' + fake_salt_bytes + b'";\n')
        (data_dir / "judge_leak.json").write_text(
            json.dumps({"tier": "hard", "seed": 900000, "done": True, "reveal": {"mole": "e01"}}),
            encoding="utf-8",
        )
        (data_dir / "pre_done_leak.json").write_text(
            json.dumps({"tier": "hard", "seed": 6, "done": False, "unlockPostGameReveal": {"mole": mole6}}),
            encoding="utf-8",
        )

        bad_gate = verify.verify_docs_arena_autodiscovery(root=fake_root)
        assert bad_gate.passed is False
        joined = "\n".join(bad_gate.violations)
        assert "py/data/forbidden.json: forbidden directory shipped in static bundle" in joined
        assert "py/harbor/task.txt: forbidden directory shipped in static bundle" in joined
        assert "py/SALT: forbidden file shipped in static bundle" in joined
        assert "leaked raw repository secret/SALT bytes" in joined
        assert "JUDGE_SEEDS" in joined
        assert "pre_done_leak.json: leaked mole ground truth" in joined


def test_owned_files_have_zero_comments_zero_em_dashes_and_no_leftover_tmp():
    for path in (SCRIPT_PATH, THIS_TEST_PATH):
        text = path.read_text(encoding="utf-8")
        assert EN_DASH not in text, f"en dash found in {path}"
        assert EM_DASH not in text, f"em dash found in {path}"
        assert HASH_CHAR not in text, f"hash character found in {path}"
        tokens = list(tokenize.generate_tokens(io.StringIO(text).readline))
        comment_tokens = [tok for tok in tokens if tok.type == tokenize.COMMENT]
        assert comment_tokens == [], f"code comments found in {path}: {comment_tokens}"

    tmp_base = Path("/tmp/opencode")
    if tmp_base.is_dir():
        leftovers = [
            p.name
            for p in tmp_base.iterdir()
            if p.name.startswith(
                (
                    "arena_bundle_parity_",
                    "arena_pyodide_bundle_",
                    "docs_arena_iso_",
                    "test_arena_",
                    "test_docs_arena_",
                    "test_duel_reveal_",
                )
            )
        ]
        assert leftovers == [], f"leftover temp dirs in /tmp/opencode: {leftovers}"
