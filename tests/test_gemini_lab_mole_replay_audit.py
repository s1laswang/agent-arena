from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from canary.gemini import mole_replay_audit as mra
from canary.mole.dsl import MoleDoc, MoleStrategy, MoleView
from canary.rules import JUDGE_SEEDS


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")


def test_parse_seeds_and_dev_seed_guard():
    assert mra.parse_seeds("0..4") == [0, 1, 2, 3, 4]
    assert mra.parse_seeds("0-4") == [0, 1, 2, 3, 4]
    assert mra.parse_seeds("1, 3, 5..7") == [1, 3, 5, 6, 7]
    assert mra.validate_dev_seeds([0, 1, 2]) == (0, 1, 2)

    judge_seed = next(iter(JUDGE_SEEDS))
    with pytest.raises(ValueError, match="judge seeds"):
        mra.validate_dev_seeds([0, judge_seed])

    with pytest.raises(ValueError, match="empty"):
        mra.parse_seeds(" , ")


def test_load_mole_forge_and_paired_designer_runs(tmp_path):
    missing_dir = tmp_path / "does_not_exist"
    assert mra.load_strategy_runs(missing_dir) == []

    roles_dir = tmp_path / "adaptive_mole"

    forge_dir = roles_dir / "mole-forge-med-run"
    _write_json(forge_dir / "meta.json", {"role": "adaptive_mole", "subrole": "mole_forge", "tier": "medium"})
    _write_jsonl(
        forge_dir / "hall_of_fame.jsonl",
        [
            {
                "rank": 2,
                "fitness": 0.25,
                "strategy_json": {
                    "rules": [{"if": [["day", ">=", 8]], "then": {"leak": "oldest", "frame": "decoy"}}],
                    "default": {"leak": "random_seeded", "frame": "none"},
                },
            },
            {
                "rank": 1,
                "fitness": 0.42,
                "strategy_json": {
                    "rules": [{"if": [["i_am_restricted", "==", 1]], "then": {"leak": "most_recipients", "frame": "decoy"}}],
                    "default": {"leak": "random_seeded", "frame": "decoy"},
                },
            },
        ],
    )

    paired_skill_dir = roles_dir / "paired-skill-designer-med"
    top_cand = {
        "name": "tempo_rotator",
        "mole_strategy": {
            "rules": [
                {"if": [["n_restricted_colleagues", ">=", 1]], "then": {"leak": "random_seeded", "frame": "most_restricted_peer"}},
                {"if": [], "then": {"leak": "random_seeded", "frame": "decoy"}},
            ]
        },
    }
    second_cand = {
        "name": "broad_doc_pivot",
        "mole_strategy": {
            "rules": [
                {"if": [["recent_low_recipient_docs", ">=", 2]], "then": {"leak": "most_recipients", "frame": "decoy"}},
                {"if": [], "then": {"leak": "random_seeded", "frame": "none"}},
            ]
        },
    }
    _write_json(
        paired_skill_dir / "design_report.json",
        {
            "tier": "medium",
            "selected_top_scenario": {"name": "tempo_rotator", "regret": 1.65, "candidate": top_cand},
            "kept": [second_cand, top_cand],
        },
    )
    _write_json(
        paired_skill_dir / "skill_gap.json",
        {
            "tier": "medium",
            "selected_scenario": top_cand,
        },
    )

    paired_round_dir = roles_dir / "paired-designer-round"
    _write_json(
        paired_round_dir / "report.json",
        {
            "tier": "easy",
            "rows": [
                {
                    "name": "unkept_cand",
                    "keep": False,
                    "solver": 0.3,
                    "regret": 0.1,
                    "candidate": {
                        "name": "unkept_cand",
                        "mole_strategy": {"rules": [{"if": [], "then": {"leak": "oldest", "frame": "none"}}]},
                    },
                },
                {
                    "name": "kept_winner",
                    "keep": True,
                    "solver": 0.72,
                    "regret": 1.2,
                    "candidate": {
                        "name": "kept_winner",
                        "mole_strategy": {"rules": [{"if": [], "then": {"leak": "random_seeded", "frame": "random_peer"}}]},
                    },
                },
            ],
            "kept": [
                {
                    "name": "kept_winner",
                    "mole_strategy": {"rules": [{"if": [], "then": {"leak": "random_seeded", "frame": "random_peer"}}]},
                }
            ],
        },
    )

    non_dsl_dir = roles_dir / "arena-live-carbon"
    _write_jsonl(non_dsl_dir / "mole_decisions.jsonl", [{"day": 1, "leak": "d1-1", "frame": None}])

    runs = mra.load_strategy_runs(roles_dir)
    assert [r.run_id for r in runs] == [
        "mole-forge-med-run",
        "paired-designer-round",
        "paired-skill-designer-med",
    ]

    forge_run = runs[0]
    assert forge_run.source_kind == "mole_forge"
    assert forge_run.tier == "medium"
    assert forge_run.top_entry.label == "rank_1"
    assert len(forge_run.entries) == 2
    assert forge_run.top_strategy.default == ("random_seeded", "decoy")

    round_run = runs[1]
    assert round_run.source_kind == "paired_designer"
    assert round_run.tier == "easy"
    assert round_run.top_entry.label == "kept_winner"
    assert len(round_run.entries) == 1

    skill_run = runs[2]
    assert skill_run.source_kind == "paired_designer"
    assert skill_run.tier == "medium"
    assert skill_run.top_entry.label == "tempo_rotator"
    assert [e.label for e in skill_run.entries] == ["tempo_rotator", "broad_doc_pivot"]


def test_deterministic_env_replay_and_mole_view_privilege_audit():
    adaptive_strategy = MoleStrategy.from_json({
        "name": "decoy_frame_adaptive",
        "rules": [
            {"if": [["i_am_restricted", "==", 1], ["days_since_last_leak", "<", 2]], "then": {"leak": "none", "frame": "decoy"}},
            {"if": [["n_restricted_colleagues", ">=", 1]], "then": {"leak": "most_recipients", "frame": "most_restricted_peer"}},
        ],
        "default": {"leak": "random_seeded", "frame": "decoy"},
    })
    report = mra.replay_strategy(adaptive_strategy, tier="medium", seeds=range(5), run_id="unit-med")
    assert report.passed is True
    assert report.deterministic_ok is True
    assert report.leaks_ok is True
    assert report.total_leak_count >= 1
    assert report.catchable_ok is True
    assert report.solver_mean_score > report.obvious_mean_score
    assert report.mole_view_clean_ok is True
    assert report.privileged_field_violations == ()
    assert report.views_checked >= 5
    assert len(report.episodes) == 5

    silent_strategy = MoleStrategy.from_json({
        "name": "never_leaks",
        "rules": [],
        "default": {"leak": "none", "frame": "none"},
    })
    silent_report = mra.replay_strategy(silent_strategy, tier="easy", seeds=(0, 1), run_id="silent")
    assert silent_report.total_leak_count == 0
    assert silent_report.leaks_ok is False
    assert silent_report.passed is False

    synthetic_views = mra.build_synthetic_mole_views()
    assert len(synthetic_views) >= 500
    assert all(mra.check_mole_view_privileges(v) == [] for v in synthetic_views[:50])

    tampered_view = SimpleNamespace(
        day=2,
        docs=(MoleDoc("c2", "Memo", 2, 0),),
        days_since_last_leak=2,
        i_am_restricted=0,
        n_restricted_colleagues=0,
        recent_low_recipient_docs=1,
        peers=("e01", "e02"),
        restricted_peers=(),
        decoy="e01",
        can_leak=True,
        is_canary=True,
        posterior={"e00": 0.9},
    )
    viols = mra.check_mole_view_privileges(tampered_view)
    assert "mole_view.is_canary:privileged_field" in viols
    assert "mole_view.posterior:privileged_field" in viols

    tampered_doc_view = MoleView(
        day=2,
        docs=(SimpleNamespace(doc_id="c2", title="Memo", recipient_count=2, age_days=0, variants={"A": ["e00"]}),),
        days_since_last_leak=2,
        i_am_restricted=0,
        n_restricted_colleagues=0,
        recent_low_recipient_docs=1,
        peers=("e01", "e02"),
        restricted_peers=(),
        decoy="e01",
        can_leak=True,
    )
    doc_viols = mra.check_mole_view_privileges(tampered_doc_view)
    assert "mole_view.docs[0].variants:privileged_doc_field" in doc_viols


def test_behavioral_equivalence_deduplication_and_cli_on_tmp_path(tmp_path, capsys):
    roles_dir = tmp_path / "roles_adaptive_mole"

    forge_strat_1 = {
        "rules": [
            {"if": [["day", ">=", 6]], "then": {"leak": "oldest", "frame": "decoy"}},
        ],
        "default": {"leak": "random_seeded", "frame": "decoy"},
    }
    forge_strat_2 = {
        "rules": [
            {"if": [["max_recipient_count", ">=", 5]], "then": {"leak": "most_recipients", "frame": "most_restricted_peer"}},
        ],
        "default": {"leak": "random_seeded", "frame": "none"},
    }
    _write_json(roles_dir / "forge-a" / "meta.json", {"tier": "medium"})
    _write_jsonl(
        roles_dir / "forge-a" / "hall_of_fame.jsonl",
        [
            {"rank": 1, "fitness": 0.5, "strategy_json": forge_strat_1},
            {"rank": 2, "fitness": 0.4, "strategy_json": forge_strat_2},
        ],
    )

    paired_equiv_to_1 = {
        "name": "paired_clone_of_forge_1",
        "mole_strategy": {
            "rules": [
                {"if": [["days_since_last_leak", "==", 0]], "then": {"leak": "fewest_recipients", "frame": "random_peer"}},
                {"if": [["day", ">", 5]], "then": {"leak": "oldest", "frame": "decoy"}},
                {"if": [], "then": {"leak": "random_seeded", "frame": "decoy"}},
            ]
        },
    }
    paired_shadowed_equiv_to_2 = {
        "name": "paired_shadowed_clone_of_forge_2",
        "mole_strategy": {
            "rules": [
                {"if": [["max_recipient_count", ">=", 5]], "then": {"leak": "most_recipients", "frame": "most_restricted_peer"}},
                {"if": [["max_recipient_count", ">=", 7]], "then": {"leak": "newest", "frame": "decoy"}},
                {"if": [], "then": {"leak": "random_seeded", "frame": "none"}},
            ]
        },
    }
    paired_distinct_3 = {
        "name": "paired_distinct_3",
        "mole_strategy": {
            "rules": [
                {"if": [["recent_low_recipient_docs", ">=", 2]], "then": {"leak": "most_recipients", "frame": "random_peer"}},
                {"if": [], "then": {"leak": "oldest", "frame": "decoy"}},
            ]
        },
    }
    _write_json(
        roles_dir / "paired-b" / "design_report.json",
        {
            "tier": "medium",
            "selected_top_scenario": {"name": "paired_clone_of_forge_1", "regret": 1.4, "candidate": paired_equiv_to_1},
            "kept": [paired_equiv_to_1, paired_shadowed_equiv_to_2, paired_distinct_3],
        },
    )

    assert mra.behavioral_signature(forge_strat_1) == mra.behavioral_signature(paired_equiv_to_1["mole_strategy"])
    assert mra.behavioral_signature(forge_strat_2) == mra.behavioral_signature(paired_shadowed_equiv_to_2["mole_strategy"])
    assert mra.behavioral_signature(forge_strat_1) != mra.behavioral_signature(forge_strat_2)
    assert mra.behavioral_signature(forge_strat_1) != mra.behavioral_signature(paired_distinct_3["mole_strategy"])

    out_json = tmp_path / "audit_out.json"
    rc = mra.main(["--roles-dir", str(roles_dir), "--seeds", "0..4", "--out", str(out_json), "--json"])
    stdout_payload = json.loads(capsys.readouterr().out)
    file_payload = json.loads(out_json.read_text(encoding="utf-8"))

    assert rc == 0
    assert stdout_payload == file_payload
    assert stdout_payload["populated"] is True
    assert stdout_payload["n_runs"] == 2
    assert stdout_payload["n_mole_forge_runs"] == 1
    assert stdout_payload["n_paired_designer_runs"] == 1
    assert stdout_payload["all_passed"] is True

    all_eq = stdout_payload["all_strategies_equivalence"]
    assert all_eq["n_strategies"] == 5
    assert all_eq["n_syntactic_unique"] == 5
    assert all_eq["n_equivalence_classes"] == 3

    top_eq = stdout_payload["top_strategies_equivalence"]
    assert top_eq["n_strategies"] == 2
    assert top_eq["n_equivalence_classes"] == 1

    proc = subprocess.run(
        [sys.executable, "-m", "canary.gemini.mole_replay_audit", "--roles-dir", str(roles_dir), "--seeds", "0..1", "--json"],
        cwd=mra.ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    cli_data = json.loads(proc.stdout)
    assert cli_data["all_passed"] is True
    assert cli_data["all_strategies_equivalence"]["n_equivalence_classes"] == 3


def test_default_roles_dir_conditional_replay():
    runs = mra.load_strategy_runs(mra.DEFAULT_ROLES_DIR)
    if not runs:
        empty_summary = mra.audit_adaptive_mole_runs(mra.DEFAULT_ROLES_DIR, seeds=(0, 1))
        assert empty_summary.populated is False
        assert empty_summary.n_runs == 0
        assert empty_summary.all_passed is True
        pytest.skip("results/gemini/roles_carbon/adaptive_mole is not populated in this checkout")

    summary = mra.audit_adaptive_mole_runs(mra.DEFAULT_ROLES_DIR, seeds=mra.DEFAULT_DEV_SEEDS)
    assert summary.populated is True
    assert summary.n_runs == len(runs)
    assert summary.all_passed is True
    for run_report in summary.runs:
        assert run_report.deterministic_ok is True
        assert run_report.total_leak_count >= 1
        assert run_report.solver_mean_score > run_report.obvious_mean_score
        assert run_report.privileged_field_violations == ()
    assert 1 <= summary.all_strategies_equivalence.n_equivalence_classes <= summary.all_strategies_equivalence.n_strategies
