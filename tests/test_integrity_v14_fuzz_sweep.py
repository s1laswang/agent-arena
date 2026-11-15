from __future__ import annotations

import importlib.util
import json
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import pytest

from canary.types import LedgerEntry, ToolResult

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts" / "integrity_sweep_v14_fuzz.py"


def _load_sweep_module():
    spec = importlib.util.spec_from_file_location("integrity_sweep_v14_fuzz", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


sweep = _load_sweep_module()


@dataclass
class _MockWorld:
    mole: str


class PlantedBugEnv:
    def __init__(self, tier: str, seed: int):
        self._emps = [f"e{i:02d}" for i in range(12)]
        self._world = _MockWorld(mole=self._emps[seed % len(self._emps)])
        self.day = 1
        self.V = 1.0
        self._done = False
        self._score = 0.0
        self._ledger: list[LedgerEntry] = []

    @property
    def done(self) -> bool:
        return self._done

    def score(self) -> float:
        return self._score

    def ledger(self) -> list[LedgerEntry]:
        return list(self._ledger)

    def call(self, tool: str, args) -> ToolResult:
        if not isinstance(args, dict):
            return ToolResult(False, {}, "invalid arguments")
        if tool == "list_employees":
            return ToolResult(True, {"employees": [{"id": e} for e in self._emps]})
        if tool == "status":
            return ToolResult(True, {"day": self.day, "V": self.V, "mole": self._world.mole})
        if tool == "advance_day":
            self.day += 1
            if self.day > 14:
                self._done = True
            return ToolResult(True, {"day": self.day})
        if tool == "accuse":
            emp = args.get("employee")
            if emp not in self._emps:
                return ToolResult(False, {}, "invalid arguments")
            self._ledger.append(LedgerEntry(0, self.day, "accused", {"employee": emp}))
            self._done = True
            self._score = 1.0
            return ToolResult(True, {"accused": emp, "episode_over": True})
        return ToolResult(False, {}, "unknown tool")


def test_quick_sweep_schema_and_zero_violations(tmp_path: Path):
    t0 = time.time()
    rc = sweep.main(["--quick", "--out-dir", str(tmp_path), "--workers", "1"])
    elapsed = time.time() - t0
    assert rc == 0
    assert elapsed < 30.0

    summary_path = tmp_path / "sweep_summary.json"
    assert summary_path.exists()
    summary = json.loads(summary_path.read_text(encoding="utf-8"))

    assert summary["tiers_version"] == "v1.4"
    assert summary["quick"] is True
    assert summary["workers"] == 1
    assert summary["mode"] == "all"
    assert summary["targets"] == ["easy", "medium", "hard", "hard_forge", "hard_rl"]
    assert summary["total_episode_evaluations"] > 0
    assert summary["total_tool_call_evaluations"] > 0
    assert summary["total_invariant_violations"] == 0
    assert summary["best_non_solver_score"] == 0.0
    assert summary["violation_kinds"] == []

    for target in ("easy", "medium", "hard", "hard_forge", "hard_rl"):
        row = summary["per_target"][target]
        assert set(row["per_mode"]) == {"random", "malformed", "evolve", "parallel_accuse"}
        assert row["invariant_violations_count"] == 0
        assert row["best_non_solver_score"] == 0.0
        assert isinstance(row["solver_mean"], float)
        if target in ("hard", "hard_forge", "hard_rl"):
            assert row["params"]["n_employees"] == 40
            assert row["params"]["n_days"] == 21
            assert row["params"]["canaries_per_day"] == 2
            assert row["params"]["max_variants"] == 3
            assert row["params"]["tool_call_cap"] == 420
        for band_label in summary["seed_bands"]:
            band_dir = tmp_path / f"{target}_{band_label}"
            assert (band_dir / "summary.json").exists()
            assert (band_dir / "findings.jsonl").exists()
            assert (band_dir / "findings.jsonl").read_text(encoding="utf-8") == ""

    wc = summary["world_check"]
    assert wc["hard_dept_count"] == 5
    assert wc["hard_forge_dept_count"] == 5
    assert wc["hard_rl_dept_count"] == 4
    assert wc["missing_depts_in_hard_rl"] == ["Research"]
    assert wc["mismatch_detected"] is True
    assert wc["hard_rl_recipient_size_mean"] > wc["hard_recipient_size_mean"]
    assert len(summary["report_only_issues"]) == 1
    assert summary["report_only_issues"][0]["id"] == "ISSUE-W1-HARD-RL-DEPTS"


def test_planted_violation_positive_detection(tmp_path: Path):
    summary = sweep.run_sweep(
        quick=True,
        out_dir=tmp_path,
        workers=1,
        targets=("hard",),
        budget_overrides={"hard": 30},
        compute_solver=False,
        factory=lambda t, s: PlantedBugEnv(t, s),
    )
    assert summary["total_invariant_violations"] > 0
    kinds = set(summary["violation_kinds"])
    assert kinds & {
        "truth_leak",
        "post_end_effect",
        "score_without_correct_accusation",
        "wrong_accusation_positive",
        "parallel_accuse_race",
    }
    findings_files = list(tmp_path.glob("hard_*/findings.jsonl"))
    assert findings_files
    lines = [ln for f in findings_files for ln in f.read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert len(lines) == summary["total_invariant_violations"]
    parsed = json.loads(lines[0])
    assert "kind" in parsed


def test_workers_above_one_rejected(tmp_path: Path):
    with pytest.raises(ValueError):
        sweep.run_sweep(quick=True, out_dir=tmp_path, workers=2)
    with pytest.raises(SystemExit):
        sweep.main(["--quick", "--out-dir", str(tmp_path), "--workers", "2"])


def test_resume_and_sharded_invariance(tmp_path: Path):
    direct_dir = tmp_path / "direct"
    sharded_dir = tmp_path / "sharded"
    direct = sweep.run_sweep(
        quick=True,
        out_dir=direct_dir,
        workers=1,
        targets=("easy", "hard"),
        compute_solver=False,
    )
    sweep.run_sweep(
        quick=True,
        out_dir=sharded_dir,
        workers=1,
        targets=("hard",),
        compute_solver=False,
    )
    sweep.run_sweep(
        quick=True,
        out_dir=sharded_dir,
        workers=1,
        targets=("easy",),
        compute_solver=False,
    )
    resumed = sweep.run_sweep(
        quick=True,
        out_dir=sharded_dir,
        workers=1,
        targets=("easy", "hard"),
        compute_solver=False,
        resume=True,
    )
    assert resumed["total_episode_evaluations"] == direct["total_episode_evaluations"]
    assert resumed["total_tool_call_evaluations"] == direct["total_tool_call_evaluations"]
    assert resumed["total_invariant_violations"] == direct["total_invariant_violations"]
    assert resumed["best_non_solver_score"] == direct["best_non_solver_score"]

    single_wc = sweep.inspect_world_departments(targets=("hard",), seeds=[0])
    assert single_wc["missing_depts_in_hard_rl"] == []
    assert single_wc["mismatch_detected"] is False


def test_report_and_source_hygiene():
    report_path = ROOT / "docs" / "reports" / "integrity_v14_fuzz_sweep.md"
    test_path = ROOT / "tests" / "test_integrity_v14_fuzz_sweep.py"
    assert report_path.is_file()

    report_text = report_path.read_text(encoding="utf-8")
    for p in (SCRIPT_PATH, test_path, report_path):
        txt = p.read_text(encoding="utf-8")
        assert "\u2014" not in txt
        assert "\u2013" not in txt

    for py_path in (SCRIPT_PATH, test_path):
        assert chr(35) not in py_path.read_text(encoding="utf-8")

    for expected in (
        "38,550",
        "1,041,059",
        "31,500",
        "canary/world.py:121",
        "ISSUE-W1-HARD-RL-DEPTS",
        "Research",
    ):
        assert expected in report_text

    for cell_idx in range(1, 11):
        assert f"| `{cell_idx}` |" in report_text


