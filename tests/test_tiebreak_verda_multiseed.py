from __future__ import annotations

import ast
import io
import json
import sys
import tokenize
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

_BEFORE_IMPORT_HEAVY = frozenset(m for m in ("torch", "transformers") if m in sys.modules)

import scripts.tiebreak_verda_multiseed_audit as audit
import scripts.verify_tiebreak_submission as sub_gate

_IMPORT_DELTA_HEAVY = (
    frozenset(m for m in ("torch", "transformers") if m in sys.modules) - _BEFORE_IMPORT_HEAVY
)

SCRIPT_PATH = REPO_ROOT / "scripts" / "tiebreak_verda_multiseed_audit.py"
SELF_PATH = Path(__file__).resolve()
SUMMARY_JSON_PATH = REPO_ROOT / "results" / "tiebreak" / "verda_multiseed" / "multiseed_summary.json"
REPORT_MD_PATH = REPO_ROOT / "docs" / "reports" / "tiebreak_verda_multiseed.md"


@pytest.fixture(scope="module")
def committed_summary() -> dict[str, Any]:
    return json.loads(SUMMARY_JSON_PATH.read_text(encoding="utf-8"))


def test_source_and_artifact_hygiene() -> None:
    hash_char = chr(35)
    em_dash = chr(0x2014)
    en_dash = chr(0x2013)
    forbidden_roots = {"torch", "transformers", "peft", "mlx", "mlx_lm"}

    for py_path in (SCRIPT_PATH, SELF_PATH):
        src = py_path.read_text(encoding="utf-8")
        tree = ast.parse(src, filename=str(py_path))
        toks = list(tokenize.generate_tokens(io.StringIO(src).readline))
        assert not [t for t in toks if t.type == tokenize.COMMENT]
        assert hash_char not in src
        assert em_dash not in src
        assert en_dash not in src
        assert src.isascii()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert alias.name.split(".")[0] not in forbidden_roots
            elif isinstance(node, ast.ImportFrom) and node.module:
                assert node.module.split(".")[0] not in forbidden_roots

    assert SUMMARY_JSON_PATH.is_file()
    assert REPORT_MD_PATH.is_file()

    for artifact in (SUMMARY_JSON_PATH, REPORT_MD_PATH):
        txt = artifact.read_text(encoding="utf-8")
        assert em_dash not in txt
        assert en_dash not in txt
        assert txt.isascii()

    assert _IMPORT_DELTA_HEAVY == frozenset()


def test_committed_summary_exact_seed_metrics(committed_summary: dict[str, Any]) -> None:
    assert committed_summary["schema"] == audit.SCHEMA_VERSION
    totals = committed_summary["totals"]
    assert totals["audited_seed_runs"] == 6
    assert totals["verda_8k_seeds"] == 4
    assert totals["grpo_4k_seeds"] == 2
    assert totals["total_episodes_replayed"] == 712
    assert totals["total_replay_invariant_errors"] == 0
    assert totals["shared_secret_paired_comparisons"] == 3

    s8 = {e["run_id"]: e for e in committed_summary["seeds_8k"]}
    assert set(s8.keys()) == {"v3_8k_s0", "v3_8k_s1", "v3_8k_s2", "v3_8k_s3"}

    assert s8["v3_8k_s0"]["grpo_steps"] == 637
    assert s8["v3_8k_s0"]["gpu_family"] == "H100"
    assert s8["v3_8k_s0"]["shared_world_secret"] is True
    assert s8["v3_8k_s0"]["overall"]["n"] == 90
    assert s8["v3_8k_s0"]["overall"]["mean_score_3d"] == pytest.approx(-0.060, abs=1e-3)
    assert s8["v3_8k_s0"]["overall"]["ci95_3d"] == pytest.approx(0.054, abs=1e-3)
    assert s8["v3_8k_s0"]["regime"] == "high_step_abstain_regime"

    assert s8["v3_8k_s1"]["grpo_steps"] == 371
    assert s8["v3_8k_s1"]["gpu_family"] == "A100"
    assert s8["v3_8k_s1"]["shared_world_secret"] is False
    assert s8["v3_8k_s1"]["overall"]["n"] == 90
    assert s8["v3_8k_s1"]["overall"]["mean_score_3d"] == pytest.approx(-0.777, abs=1e-3)
    assert s8["v3_8k_s1"]["overall"]["ci95_3d"] == pytest.approx(0.118, abs=1e-3)
    assert s8["v3_8k_s1"]["regime"] == "low_step_over_accuse_regime"

    assert s8["v3_8k_s2"]["grpo_steps"] == 693
    assert s8["v3_8k_s2"]["gpu_family"] == "H100"
    assert s8["v3_8k_s2"]["shared_world_secret"] is False
    assert s8["v3_8k_s2"]["overall"]["n"] == 90
    assert s8["v3_8k_s2"]["overall"]["mean_score_3d"] == pytest.approx(-0.050, abs=1e-3)
    assert s8["v3_8k_s2"]["overall"]["ci95_3d"] == pytest.approx(0.049, abs=1e-3)
    assert s8["v3_8k_s2"]["regime"] == "high_step_abstain_regime"

    assert s8["v3_8k_s3"]["grpo_steps"] == 344
    assert s8["v3_8k_s3"]["gpu_family"] == "A100"
    assert s8["v3_8k_s3"]["shared_world_secret"] is True
    assert s8["v3_8k_s3"]["overall"]["n"] == 90
    assert s8["v3_8k_s3"]["overall"]["mean_score_3d"] == pytest.approx(-0.788, abs=1e-3)
    assert s8["v3_8k_s3"]["overall"]["ci95_3d"] == pytest.approx(0.117, abs=1e-3)
    assert s8["v3_8k_s3"]["regime"] == "low_step_over_accuse_regime"

    s4 = {e["run_id"]: e for e in committed_summary["seeds_4k"]}
    assert set(s4.keys()) == {"v3_4k_s0", "v3_4k_s1"}

    assert s4["v3_4k_s0"]["grpo_steps"] == 609
    assert s4["v3_4k_s0"]["gpu_family"] == "H100"
    assert s4["v3_4k_s0"]["overall"]["n"] == 180
    assert s4["v3_4k_s0"]["overall"]["mean_score_3d"] == pytest.approx(-0.147, abs=1e-3)
    assert s4["v3_4k_s0"]["overall"]["ci95_3d"] == pytest.approx(0.063, abs=1e-3)

    assert s4["v3_4k_s1"]["grpo_steps"] == 192
    assert s4["v3_4k_s1"]["gpu_family"] == "V100"
    assert s4["v3_4k_s1"]["overall"]["n"] == 82
    assert s4["v3_4k_s1"]["overall"]["mean_score_3d"] == pytest.approx(-0.209, abs=1e-3)
    assert s4["v3_4k_s1"]["overall"]["ci95_3d"] == pytest.approx(0.094, abs=1e-3)

    ctrl = committed_summary["inference_context_control_4k_at_8k"]
    assert ctrl["grpo_steps"] == 609
    assert ctrl["shared_world_secret"] is True
    assert ctrl["overall"]["n"] == 90
    assert ctrl["overall"]["mean_score_3d"] == pytest.approx(-0.716, abs=1e-3)
    assert ctrl["overall"]["ci95_3d"] == pytest.approx(0.105, abs=1e-3)

    lost = committed_summary["lost_replicates"]
    assert len(lost) == 1
    assert "714d8144" in lost[0]["where_trained"]


def test_world_paired_shared_secret_comparisons_and_triangle_identity(
    committed_summary: dict[str, Any],
) -> None:
    paired = committed_summary["world_paired_shared_secret_comparisons"]

    p_s0_s3 = paired["s0_minus_s3"]
    assert p_s0_s3["n"] == 90
    assert p_s0_s3["mean_delta_3d"] == pytest.approx(0.728, abs=1e-3)
    assert p_s0_s3["ci95_3d"] == pytest.approx(0.134, abs=1e-3)
    assert p_s0_s3["roster_exact_matches"] == 61
    assert p_s0_s3["roster_overlap_checked"] == 61
    assert p_s0_s3["world_identity_verified"] is True

    p_s3_4k8k = paired["s3_minus_4k_at_8k"]
    assert p_s3_4k8k["n"] == 90
    assert p_s3_4k8k["mean_delta_3d"] == pytest.approx(-0.073, abs=1e-3)
    assert p_s3_4k8k["ci95_3d"] == pytest.approx(0.173, abs=1e-3)
    assert p_s3_4k8k["roster_exact_matches"] == 60
    assert p_s3_4k8k["roster_overlap_checked"] == 60
    assert p_s3_4k8k["world_identity_verified"] is True

    p_s0_4k8k = paired["s0_minus_4k_at_8k"]
    assert p_s0_4k8k["n"] == 90
    assert p_s0_4k8k["mean_delta_3d"] == pytest.approx(0.655, abs=1e-3)
    assert p_s0_4k8k["ci95_3d"] == pytest.approx(0.116, abs=1e-3)
    assert p_s0_4k8k["roster_exact_matches"] == 60
    assert p_s0_4k8k["roster_overlap_checked"] == 60
    assert p_s0_4k8k["world_identity_verified"] is True

    d_s0_s3 = p_s0_s3["paired_deltas"]
    d_s3_4k = p_s3_4k8k["paired_deltas"]
    d_s0_4k = p_s0_4k8k["paired_deltas"]
    assert len(d_s0_s3) == len(d_s3_4k) == len(d_s0_4k) == 90
    for i in range(90):
        assert d_s0_s3[i] == pytest.approx(d_s0_4k[i] - d_s3_4k[i], abs=1e-5)

    neg = committed_summary["unpaired_secret_negative_control"]
    assert neg["roster_exact_matches"] == 0
    assert neg["roster_overlap_checked"] == 60
    assert neg["world_identity_verified"] is True


def test_bimodal_regime_belief_replay_and_curve_transition(
    committed_summary: dict[str, Any],
) -> None:
    bimodal = committed_summary["bimodal_regime_split"]
    low = bimodal["low_step_8k_cluster"]
    high = bimodal["high_step_8k_cluster"]

    assert low["steps_per_seed"] == [371, 344]
    assert low["pooled_episodes"] == 180
    assert low["accused_rate"] == pytest.approx(171 / 180, abs=1e-4)
    assert low["belief_replay"]["below_breakeven_count"] == 167
    assert low["belief_replay"]["accused_episodes"] == 171
    assert low["belief_replay"]["below_breakeven_rate"] > 0.97

    assert high["steps_per_seed"] == [637, 693]
    assert high["pooled_episodes"] == 180
    assert high["abstain_rate"] == pytest.approx(167 / 180, abs=1e-4)
    assert high["belief_replay"]["missed_commit_abstain_count"] == 21
    assert high["belief_replay"]["abstained_episodes"] == 167
    assert bimodal["beats_always_abstain_base_count"] == 0

    s8 = {e["run_id"]: e for e in committed_summary["seeds_8k"]}
    for rid in ("v3_8k_s0", "v3_8k_s2"):
        wins = s8[rid]["training_curve"]["windows"]
        assert wins["steps_250_370"]["mean_free_accuse_frac"] > 0.08
        assert wins["steps_550_plus"]["mean_free_accuse_frac"] < 0.045
    for rid in ("v3_8k_s1", "v3_8k_s3"):
        wins = s8[rid]["training_curve"]["windows"]
        assert wins["steps_250_370"]["mean_free_accuse_frac"] > 0.10
        assert wins["steps_550_plus"] is None


def _make_synthetic_ep(
    tier: str,
    seed: int,
    roster_tag: str,
    accuse_emp: str | None,
    correct: bool = False,
) -> dict[str, Any]:
    emps = [{"id": f"e{i:02d}", "dept": roster_tag} for i in range(6)]
    steps: list[dict[str, Any]] = [
        {
            "t": 0,
            "day": 1,
            "tool": "list_employees",
            "args": {},
            "result": {"ok": True, "data": {"employees": emps}},
        }
    ]
    if accuse_emp is not None:
        steps.append(
            {
                "t": 1,
                "day": 2,
                "tool": "accuse",
                "args": {"employee": accuse_emp},
                "result": {"ok": True, "data": {"accused": accuse_emp}},
            }
        )
        return {
            "tier": tier,
            "seed": seed,
            "agent": "synthetic",
            "steps": steps,
            "score": 0.8 if correct else -1.0,
            "accused": accuse_emp,
            "correct": correct,
            "final_day": 2,
            "end_reason": "accused",
            "meta": {"invalid_calls": 0},
        }
    return {
        "tier": tier,
        "seed": seed,
        "agent": "synthetic",
        "steps": steps,
        "score": 0.0,
        "accused": None,
        "correct": False,
        "final_day": 8,
        "end_reason": "horizon",
        "meta": {"invalid_calls": 0},
    }


def test_synthetic_mini_repo_end_to_end_and_cli_check(tmp_path: Path) -> None:
    all_specs = (*audit.SEED_RUN_SPECS, audit.CONTROL_4K_AT_8K_SPEC)
    for spec in all_specs:
        rid = spec["run_id"]
        shared = bool(spec["shared_world_secret"])
        roster_tag = "shared_roster" if shared else f"unpaired_{rid}"
        accuse_mode = rid in ("v3_8k_s1", "v3_8k_s3", "v3_4k_s0_ctx8k")

        rels = tuple(spec["episodes_rels"])
        per_file_seeds: list[list[int]] = []
        if len(rels) == 1:
            per_file_seeds.append(list(range(800_000, 800_030)))
        elif len(rels) == 2:
            per_file_seeds.append(list(range(800_000, 800_030)))
            per_file_seeds.append(list(range(800_030, 800_060)))
        else:
            per_file_seeds.append(list(range(800_000, 800_010)))
            per_file_seeds.append(list(range(800_010, 800_020)))
            per_file_seeds.append(list(range(800_020, 800_030)))

        for rel, seed_list in zip(rels, per_file_seeds):
            ep_lines: list[str] = []
            for tier in audit.CANONICAL_TIERS:
                for sd in seed_list:
                    ep_obj = _make_synthetic_ep(
                        tier=tier,
                        seed=sd,
                        roster_tag=roster_tag,
                        accuse_emp="e00" if accuse_mode else None,
                        correct=False,
                    )
                    ep_lines.append(json.dumps(ep_obj))
            p = tmp_path / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("\n".join(ep_lines) + "\n", encoding="utf-8")

        ts_path = tmp_path / str(spec["train_summary_rel"])
        ts_path.parent.mkdir(parents=True, exist_ok=True)
        ts_path.write_text(
            json.dumps(
                {
                    "steps": spec["expected_steps"],
                    "hours": 3.0,
                    "args": {"seed_base": 150000, "n_states": 2000},
                }
            ),
            encoding="utf-8",
        )

        cv_path = tmp_path / str(spec["curve_rel"])
        cv_path.parent.mkdir(parents=True, exist_ok=True)
        cv_rows = [
            json.dumps(
                {
                    "step": st,
                    "free_accuse_frac": 0.03 if st >= 550 else 0.11,
                    "continue_frac": 0.60 if st >= 550 else 0.53,
                    "forced_accuse_correct": 0.42,
                    "gain_vs_solver_valid": -0.40,
                    "action_entropy": 1.0,
                    "sec": 16.0,
                    "elapsed_h": round(st * 16.0 / 3600.0, 4),
                }
            )
            for st in range(min(int(spec["expected_steps"]), 600))
        ]
        cv_path.write_text("\n".join(cv_rows) + "\n", encoding="utf-8")

    out_json = tmp_path / "out" / "multiseed_summary.json"
    out_md = tmp_path / "out" / "tiebreak_verda_multiseed.md"

    rc_gen = audit.main(
        [
            "--root",
            str(tmp_path),
            "--out-json",
            str(out_json),
            "--out-md",
            str(out_md),
            "--no-git",
        ]
    )
    assert rc_gen == 0

    rc_chk = audit.main(
        [
            "--root",
            str(tmp_path),
            "--out-json",
            str(out_json),
            "--out-md",
            str(out_md),
            "--no-git",
            "--check",
        ]
    )
    assert rc_chk == 0

    tampered = json.loads(out_json.read_text(encoding="utf-8"))
    tampered["world_paired_shared_secret_comparisons"]["s0_minus_s3"]["mean_delta"] = -0.999
    out_json.write_text(json.dumps(tampered), encoding="utf-8")
    rc_bad = audit.main(
        [
            "--root",
            str(tmp_path),
            "--out-json",
            str(out_json),
            "--out-md",
            str(out_md),
            "--no-git",
            "--check",
        ]
    )
    assert rc_bad == 1


def test_submission_verifier_compatibility() -> None:
    rc = audit.main(["--check", "--no-git"])
    assert rc == 0

    prov = sub_gate.check_seed_and_secret_provenance(root=REPO_ROOT, strict=True)
    assert prov.passed, prov.errors

    hyg = sub_gate.check_hygiene_and_panel_fix_a(root=REPO_ROOT, strict=True)
    assert hyg.passed, hyg.errors
