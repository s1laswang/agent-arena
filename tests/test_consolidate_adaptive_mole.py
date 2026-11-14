from __future__ import annotations

import io
import json
from pathlib import Path
import tokenize

import pytest

from canary.gemini.provenance import TARGET_MODEL, audit_provenance, scan_file_secrets
from scripts.consolidate_adaptive_mole import consolidate_adaptive_mole, main

REPO_ROOT = Path(__file__).resolve().parents[1]
EM_DASH = chr(0x2014)
EN_DASH = chr(0x2013)
COMMIT_A = "89e733ce0123456789abcdef0123456789abcdef"
COMMIT_B = "c00d49189d1a4c63495d9111e11b5f13528a5093"


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")


def _build_synthetic_adaptive_mole_tree(root: Path) -> Path:
    role_root = root / "results" / "gemini_roles" / "adaptive_mole"

    clash_specs = [
        ("carbon-vs-carbon-med1", "medium", 1, 0.50, True, 0.60, True, True, 0.10, 6, 2, 0, 50000, 1200, 4000, 0.25, 45000, 900, 3500, 0.22, 5000, 300, 500, 0.03),
        ("carbon-vs-carbon-seed0", "medium", 0, 0.66, True, 0.40, True, True, -0.26, 7, 1, 0, 60000, 1500, 5000, 0.30, 54000, 1100, 4200, 0.26, 6000, 400, 800, 0.04),
        ("carbon-vs-carbon-hard0", "hard", 0, 0.00, False, 0.55, True, True, 0.55, 14, 9, 0, 90000, 2000, 8000, 0.45, 80000, 1400, 6800, 0.39, 10000, 600, 1200, 0.06),
    ]
    for (
        folder,
        tier,
        seed,
        inv_s,
        inv_c,
        sol_s,
        sol_c,
        solvable,
        regret,
        leaks,
        frames,
        errs,
        c_in,
        c_out,
        c_th,
        c_usd,
        i_in,
        i_out,
        i_th,
        i_usd,
        m_in,
        m_out,
        m_th,
        m_usd,
    ) in clash_specs:
        _write_json(
            role_root / folder / "meta.json",
            {
                "role": "adaptive_mole",
                "subrole": "carbon_vs_carbon_clash",
                "model_id": TARGET_MODEL,
                "tier": tier,
                "seed": seed,
                "episode_count": 2,
                "commit": COMMIT_A,
                "timestamp": "2026-11-14T16:00:00Z",
                "investigator_score": inv_s,
                "investigator_correct": inv_c,
                "solver_score": sol_s,
                "solver_correct": sol_c,
                "solvable": solvable,
                "regret": regret,
                "mole_clash_days": leaks,
                "mole_clash_leaks": leaks,
                "mole_clash_frames": frames,
                "mole_clash_errors": errs,
                "mole_solver_days": 8,
                "mole_solver_leaks": 7,
                "mole_solver_frames": 3,
                "mole_solver_errors": 0,
                "usage": {
                    "calls": 20,
                    "in": c_in,
                    "out": c_out,
                    "thinking": c_th,
                    "cached": 1000,
                    "cost_usd": c_usd,
                    "latency_s": 50.0,
                    "clash_investigator": {
                        "calls": 14,
                        "in": i_in,
                        "out": i_out,
                        "thinking": i_th,
                        "cached": 1000,
                        "cost_usd": i_usd,
                        "latency_s": 40.0,
                    },
                    "clash_mole": {
                        "calls": 6,
                        "in": m_in,
                        "out": m_out,
                        "thinking": m_th,
                        "cached": 0,
                        "cost_usd": m_usd,
                        "latency_s": 10.0,
                    },
                },
            },
        )

    for folder, tier, seeds, s_scores, d_s_scores, g_d_scores, tin, tout, tth, usd in [
        ("arena-live-carbon-med01", "medium", [0, 1], [0.60, 0.00], [0.70, 0.50], [0.50, 0.40], 20000, 1600, 1800, 0.08),
        ("arena-live-carbon-hard01", "hard", [0, 1], [0.50, 0.70], [0.60, 0.80], [0.60, 0.70], 30000, 2200, 2400, 0.12),
    ]:
        adaptive_eps = []
        default_eps = []
        decisions = []
        for idx, s in enumerate(seeds):
            adaptive_eps.extend(
                [
                    {
                        "tier": tier,
                        "seed": s,
                        "investigator": "solver",
                        "score": s_scores[idx],
                        "correct": s_scores[idx] > 0,
                        "final_day": 8,
                        "mole_days": 2,
                        "mole_leaks_chosen": 2,
                        "mole_frames_chosen": 1,
                        "mole_llm_errors": 0,
                        "mole_rejected_moves": 0,
                    },
                    {
                        "tier": tier,
                        "seed": s,
                        "investigator": "grok_tactics",
                        "score": 0.0,
                        "correct": False,
                        "final_day": 14,
                        "mole_days": 2,
                        "mole_leaks_chosen": 1,
                        "mole_frames_chosen": 2,
                        "mole_llm_errors": 0,
                        "mole_rejected_moves": 0,
                    },
                    {
                        "tier": tier,
                        "seed": s,
                        "investigator": "obvious_heuristic",
                        "score": -1.0,
                        "correct": False,
                        "final_day": 3,
                        "mole_days": 1,
                        "mole_leaks_chosen": 1,
                        "mole_frames_chosen": 1,
                        "mole_llm_errors": 0,
                        "mole_rejected_moves": 0,
                    },
                ]
            )
            default_eps.extend(
                [
                    {
                        "tier": tier,
                        "seed": s,
                        "investigator": "solver",
                        "score": d_s_scores[idx],
                        "correct": True,
                        "final_day": 7,
                    },
                    {
                        "tier": tier,
                        "seed": s,
                        "investigator": "grok_tactics",
                        "score": g_d_scores[idx],
                        "correct": True,
                        "final_day": 8,
                    },
                    {
                        "tier": tier,
                        "seed": s,
                        "investigator": "obvious_heuristic",
                        "score": -1.0,
                        "correct": False,
                        "final_day": 11,
                    },
                ]
            )
            decisions.extend(
                [
                    {
                        "tier": tier,
                        "seed": s,
                        "investigator": "solver",
                        "day": 1,
                        "leak": "d1-1",
                        "frame": "e00",
                        "reason": f"Wide distribution {EM_DASH} low risk {EN_DASH} frame peer",
                        "rejected": [],
                        "error": None,
                    },
                    {
                        "tier": tier,
                        "seed": s,
                        "investigator": "solver",
                        "day": 2,
                        "leak": None,
                        "frame": "e01",
                        "reason": "Quiet turn",
                        "rejected": [],
                        "error": None,
                    },
                ]
            )
        _write_json(
            role_root / folder / "meta.json",
            {
                "role": "adaptive_mole",
                "subrole": "live_arena_mole",
                "model_id": TARGET_MODEL,
                "tier": tier,
                "seeds": seeds,
                "commit": COMMIT_B,
                "timestamp": "2026-11-14T17:10:00Z",
                "solvability_verified": True,
                "solver_mean": sum(s_scores) / len(s_scores),
                "solver_accuracy": sum(1 for x in s_scores if x > 0) / len(s_scores),
                "grok_tactics_mean": 0.0,
                "heuristic_mean": -1.0,
                "mole_decisions_count": len(decisions),
                "mole_llm_errors": 0,
                "usage": {
                    "calls": len(decisions),
                    "in": tin,
                    "out": tout,
                    "thinking": tth,
                    "cached": 0,
                    "cost_usd": usd,
                    "latency_s": 20.0,
                },
            },
        )
        _write_json(
            role_root / folder / "episodes.json",
            {
                "tier": tier,
                "seeds": seeds,
                "model_id": TARGET_MODEL,
                "adaptive_mole": adaptive_eps,
                "default_mole": default_eps,
            },
        )
        _write_jsonl(role_root / folder / "mole_decisions.jsonl", decisions)

    _write_json(
        role_root / "mole-forge-carbon-v14" / "meta.json",
        {
            "role": "adaptive_mole",
            "subrole": "mole_forge",
            "model_id": TARGET_MODEL,
            "tier": "hard",
            "gens": 3,
            "commit": COMMIT_A,
            "timestamp": "2026-11-14T14:30:00Z",
            "n_valid_llm_children": 6,
            "n_invalid_llm_children": 0,
            "best_fitness": 0.37,
            "default_dev_fitness": 0.245,
            "fresh_solver_accuracy": 0.95,
            "fresh_min_regret": 0.2395,
            "default_fresh_min_regret": 0.242,
            "usage": {
                "calls": 12,
                "in": 2500,
                "out": 1000,
                "thinking": 1100,
                "cached": 0,
                "cost_usd": 0.03,
                "latency_s": 15.0,
            },
        },
    )
    _write_json(
        role_root / "mole-forge-carbon-v14" / "generations.json",
        {
            "tier": "hard",
            "generations": [
                {"gen": 0, "hof_best_fitness": 0.31},
                {"gen": 1, "hof_best_fitness": 0.34},
                {"gen": 2, "hof_best_fitness": 0.37},
            ],
        },
    )

    _write_json(
        role_root / "paired-designer-carbon" / "meta.json",
        {
            "role": "adaptive_mole",
            "subrole": "paired_designer",
            "model_id": TARGET_MODEL,
            "tier": "medium",
            "commit": COMMIT_A,
            "timestamp": "2026-11-14T13:59:00Z",
            "n_llm_valid": 4,
            "n_kept": 3,
            "kept_solver_mean": 0.5743,
            "kept_heuristic_mean": -1.0,
            "usage": {
                "calls": 1,
                "in": 1900,
                "out": 1100,
                "thinking": 700,
                "cached": 0,
                "cost_usd": 0.02,
                "latency_s": 8.0,
            },
        },
    )

    _write_json(
        role_root / "paired-solvable-scenarios-carbon" / "meta.json",
        {
            "role": "adaptive_mole",
            "subrole": "paired_skill_designer",
            "model_id": TARGET_MODEL,
            "tier": "hard",
            "commit": COMMIT_B,
            "timestamp": "2026-11-14T17:09:30Z",
            "n_llm_valid": 6,
            "n_kept": 6,
            "design_solver_mean": 0.689,
            "design_heuristic_mean": -1.0,
            "eval_full_solver_mean": 0.628,
            "eval_heuristic_mean": -1.0,
            "top_scenario_name": f"rotating{EM_DASH}sprinter",
            "usage": {
                "calls": 1,
                "in": 1600,
                "out": 1400,
                "thinking": 500,
                "cached": 0,
                "cost_usd": 0.025,
                "latency_s": 9.0,
            },
        },
    )
    _write_json(
        role_root / "paired-solvable-scenarios-carbon" / "skill_gap.json",
        {
            "selected_scenario": {"name": "rotating-sprinter"},
            "headline_comparison": {
                "full_solver": {
                    "baseline_mean_score": 0.61,
                    "designed_mean_score": 0.628,
                    "designed_accuracy": 0.95,
                },
                "heuristic_bisection": {
                    "baseline_mean_score": -1.0,
                    "designed_mean_score": -1.0,
                    "designed_accuracy": 0.0,
                },
            },
        },
    )

    _write_json(
        role_root / "carbon-vs-carbon-suite" / "meta.json",
        {
            "role": "adaptive_mole",
            "model_id": TARGET_MODEL,
            "commit": COMMIT_A,
            "usage": {"calls": 999, "in": 999999, "out": 999999, "cost_usd": 99.0},
        },
    )

    _write_json(
        role_root / "smoke-ignored-run" / "meta.json",
        {
            "role": "adaptive_mole",
            "model_id": TARGET_MODEL,
            "commit": COMMIT_A,
            "smoke": True,
            "usage": {"calls": 5, "in": 500, "out": 100, "cost_usd": 0.01},
        },
    )
    return root


def test_synthetic_multi_shard_consolidation_and_determinism(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_GENERATIVE_AI_API_KEY", raising=False)

    _build_synthetic_adaptive_mole_tree(tmp_path)
    rc = main(["--root", str(tmp_path)])
    assert rc == 0

    suite_dir = tmp_path / "results" / "gemini_roles" / "adaptive_mole" / "carbon-vs-carbon-suite"
    assert not (suite_dir / "meta.json").exists()
    suite_json_path = suite_dir / "suite.json"
    summary_md_path = suite_dir / "summary.md"
    assert suite_json_path.is_file()
    assert summary_md_path.is_file()

    first_json = suite_json_path.read_text(encoding="utf-8")
    first_md = summary_md_path.read_text(encoding="utf-8")
    assert EM_DASH not in first_json and EN_DASH not in first_json
    assert EM_DASH not in first_md and EN_DASH not in first_md

    assert main(["--root", str(tmp_path)]) == 0
    assert suite_json_path.read_text(encoding="utf-8") == first_json
    assert summary_md_path.read_text(encoding="utf-8") == first_md

    suite = json.loads(first_json)

    clash = suite["clash_suite"]
    assert [(s["tier"], s["seed"]) for s in clash["shards"]] == [
        ("medium", 0),
        ("medium", 1),
        ("hard", 0),
    ]
    assert clash["by_tier"]["medium"]["n_shards"] == 2
    assert clash["by_tier"]["medium"]["n_episodes"] == 4
    assert clash["by_tier"]["medium"]["investigator_accuracy"] == pytest.approx(1.0)
    assert clash["by_tier"]["medium"]["investigator_mean_score"] == pytest.approx(0.58)
    assert clash["by_tier"]["medium"]["solver_mean_score"] == pytest.approx(0.50)
    assert clash["by_tier"]["medium"]["mean_regret"] == pytest.approx(-0.08)
    assert clash["overall"]["n_shards"] == 3
    assert clash["overall"]["n_episodes"] == 6
    assert clash["overall"]["investigator_accuracy"] == pytest.approx(0.6667, abs=1e-4)
    assert clash["overall"]["solvable_rate"] == pytest.approx(1.0)
    assert clash["overall"]["mole_total_leaks"] == 27
    assert clash["overall"]["mole_total_frames"] == 12
    assert clash["overall"]["mole_total_errors"] == 0
    assert clash["overall"]["usage"]["combined"]["in"] == 200000
    assert clash["overall"]["usage"]["clash_investigator"]["in"] == 179000
    assert clash["overall"]["usage"]["clash_mole"]["in"] == 21000
    assert clash["overall"]["usage"]["combined"]["cost_usd"] == pytest.approx(1.00)

    arena = suite["live_arena_suite"]
    assert arena["overall"]["n_runs"] == 2
    assert arena["overall"]["n_adaptive_episodes"] == 12
    assert arena["overall"]["n_default_episodes"] == 12
    assert arena["by_tier"]["medium"]["by_investigator"]["solver"]["adaptive_mole"]["mean_score"] == pytest.approx(0.30)
    assert arena["by_tier"]["hard"]["by_investigator"]["solver"]["adaptive_mole"]["mean_score"] == pytest.approx(0.60)
    assert arena["overall"]["by_investigator"]["solver"]["adaptive_mole"]["mean_score"] == pytest.approx(0.45)
    assert arena["overall"]["by_investigator"]["solver"]["default_mole"]["mean_score"] == pytest.approx(0.65)
    assert arena["overall"]["by_investigator"]["solver"]["delta_mean"] == pytest.approx(-0.20)
    assert arena["overall"]["by_investigator"]["grok_tactics"]["adaptive_mole"]["mean_score"] == pytest.approx(0.0)
    assert arena["overall"]["by_investigator"]["grok_tactics"]["default_mole"]["mean_score"] == pytest.approx(0.55)
    assert arena["overall"]["by_investigator"]["grok_tactics"]["delta_mean"] == pytest.approx(-0.55)
    assert arena["overall"]["mole_decisions"] == 8
    assert arena["overall"]["mole_leaks"] == 4
    assert arena["overall"]["mole_frames"] == 8
    assert arena["overall"]["mole_llm_errors"] == 0

    forge = suite["mole_forge_suite"]
    assert len(forge["runs"]) == 1
    assert forge["runs"][0]["tier"] == "hard"
    assert forge["runs"][0]["gens"] == 3
    assert forge["runs"][0]["n_valid_llm_children"] == 6
    assert forge["runs"][0]["best_fitness"] == pytest.approx(0.37)
    assert forge["runs"][0]["default_dev_fitness"] == pytest.approx(0.245)
    assert forge["runs"][0]["fresh_solver_accuracy"] == pytest.approx(0.95)
    assert forge["runs"][0]["fresh_min_regret"] == pytest.approx(0.2395)
    assert forge["runs"][0]["hof_fitness_trajectory"] == [0.31, 0.34, 0.37]

    paired = suite["paired_designer_suite"]
    assert len(paired["runs"]) == 2
    assert paired["overall"]["total_llm_valid"] == 10
    assert paired["overall"]["total_kept"] == 9
    assert paired["overall"]["n_holdout_eval_runs"] == 1
    assert paired["overall"]["mean_eval_full_solver"] == pytest.approx(0.628)
    assert paired["runs"][1]["top_scenario_name"] == "rotating-sprinter"
    assert paired["runs"][1]["has_skill_gap"] is True

    tot = suite["totals"]
    assert tot["verified_folders"] == 8
    assert tot["calls"] == 60 + 8 + 12 + 1 + 1
    assert tot["in"] == 200000 + 50000 + 2500 + 1900 + 1600
    assert tot["out"] == 4700 + 3800 + 1000 + 1100 + 1400
    assert tot["cost_usd"] == pytest.approx(1.00 + 0.20 + 0.03 + 0.02 + 0.025)


def test_real_repo_consolidation_and_provenance_parity(tmp_path: Path) -> None:
    committed_suite_dir = REPO_ROOT / "results" / "gemini_roles" / "adaptive_mole" / "carbon-vs-carbon-suite"
    assert not (committed_suite_dir / "meta.json").exists()
    assert (committed_suite_dir / "suite.json").is_file()
    assert (committed_suite_dir / "summary.md").is_file()

    tmp_out = tmp_path / "recomputed_suite"
    recomputed = consolidate_adaptive_mole(root=REPO_ROOT, out_dir=tmp_out)
    assert not (tmp_out / "meta.json").exists()

    prov = audit_provenance(REPO_ROOT)
    assert prov["verified"] is True
    assert prov["secret_leaks"] == []

    role_prov = prov["roles"]["adaptive_mole"]
    assert role_prov["verified"] is True
    assert recomputed["totals"]["verified_folders"] == len(role_prov["run_dirs"])
    assert recomputed["totals"]["in"] == role_prov["tokens_in"]
    assert recomputed["totals"]["out"] == role_prov["tokens_out"]
    assert recomputed["totals"]["cost_usd"] == pytest.approx(role_prov["cost_usd"], abs=1e-5)

    assert recomputed["clash_suite"]["overall"]["n_shards"] >= 1
    assert recomputed["live_arena_suite"]["by_tier"]["medium"]["n_adaptive_episodes"] >= 18
    assert recomputed["live_arena_suite"]["by_tier"]["hard"]["n_adaptive_episodes"] >= 18
    assert recomputed["live_arena_suite"]["overall"]["mole_llm_errors"] == 0
    assert recomputed["mole_forge_suite"]["overall"]["n_runs"] >= 1
    assert recomputed["paired_designer_suite"]["overall"]["n_runs"] >= 4


def test_no_comments_unicode_dashes_or_secrets() -> None:
    py_files = [
        REPO_ROOT / "scripts" / "consolidate_adaptive_mole.py",
        REPO_ROOT / "tests" / "test_consolidate_adaptive_mole.py",
    ]
    for py_file in py_files:
        src = py_file.read_text(encoding="utf-8")
        assert EM_DASH not in src
        assert EN_DASH not in src
        tokens = list(tokenize.generate_tokens(io.StringIO(src).readline))
        comments = [tok for tok in tokens if tok.type == tokenize.COMMENT]
        assert comments == [], f"unexpected comment in {py_file}: {comments}"
        assert scan_file_secrets(py_file, REPO_ROOT) == []

    artifact_dirs = [
        REPO_ROOT / "results" / "gemini_roles" / "adaptive_mole" / "carbon-vs-carbon-suite",
        REPO_ROOT / "results" / "gemini_roles" / "adaptive_mole" / "arena-live-carbon-hard345",
        REPO_ROOT / "results" / "gemini_roles" / "adaptive_mole" / "arena-live-carbon-med345",
    ]
    for adir in artifact_dirs:
        for fp in sorted(adir.iterdir()):
            if fp.is_file():
                txt = fp.read_text(encoding="utf-8")
                assert EM_DASH not in txt, f"em dash in {fp}"
                assert EN_DASH not in txt, f"en dash in {fp}"
                assert scan_file_secrets(fp, REPO_ROOT) == []
