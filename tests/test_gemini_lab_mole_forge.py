from __future__ import annotations

import ast
import io
import json
import re
import sys
import tokenize
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from canary.env import Env
from canary.eval import run_episode
from canary.forge.fitness import FEASIBLE_SOLVER_RATIO
from canary.mole.dsl import MoleStrategy
from canary.rules import JUDGE_SEEDS
from canary.solver.policy import SolverPolicy

ADAPTIVE_MOLE_DIR = ROOT / "results" / "gemini" / "roles_carbon" / "adaptive_mole"

EXPECTED_RUNS: dict[str, str] = {
    "mole-forge-carbon-easy-deep": "easy",
    "mole-forge-carbon-med-deep": "medium",
    "mole-forge-carbon-hard-deep": "hard",
    "mole-forge-carbon-v14": "hard",
}
EXPECTED_FILES = {
    "meta.json",
    "generations.json",
    "hall_of_fame.jsonl",
    "holdout_generalization.json",
    "summary.md",
}
FORBIDDEN_DASHES = (
    chr(0x2012),
    chr(0x2013),
    chr(0x2014),
    chr(0x2015),
)
SECRET_PATTERNS = (
    re.compile(r"(?<![0-9A-Za-z+/_-])AIza[0-9A-Za-z_-]{20,}"),
    re.compile(r"(?<![0-9A-Za-z+/_-])sk-(?:proj-|ant-|live-|test-|svcacct-)?[0-9A-Za-z_-]{16,}"),
    re.compile(r"(?<![0-9A-Za-z+/_-])ya29\.[0-9A-Za-z_-]{20,}"),
    re.compile(r"\b(?:GEMINI_API_KEY|GOOGLE_API_KEY|GOOGLE_GENERATIVE_AI_API_KEY|CANARY_WORLD_SECRET|CANARY_LEDGER_KEY)\s*=\s*\S+"),
)
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
CONFIRM_SEEDS = list(range(5020, 5060))


def test_mole_forge_four_folders_and_file_set() -> None:
    assert ADAPTIVE_MOLE_DIR.is_dir()
    for run_name, expected_tier in EXPECTED_RUNS.items():
        run_dir = ADAPTIVE_MOLE_DIR / run_name
        assert run_dir.is_dir(), f"missing Mole Forge folder: {run_dir}"
        present = {p.name for p in run_dir.iterdir()}
        assert present == EXPECTED_FILES, f"unexpected file set in {run_name}: {sorted(present)}"
        for p in run_dir.iterdir():
            assert p.is_file()
            text = p.read_text(encoding="utf-8")
            assert text.strip()
            assert "results/gemini_roles/" not in text, f"legacy path string in {p}"

        meta = json.loads((run_dir / "meta.json").read_text(encoding="utf-8"))
        assert meta["role"] == "adaptive_mole"
        assert meta["subrole"] == "mole_forge"
        assert meta["environment_scope"] == "arena mode, not the judged v1.4 environment"
        assert meta["model_id"] == "gemini-4-carbon"
        assert meta["tier"] == expected_tier
        assert meta["tiers_version"] == "v1.4"
        assert meta["fake_env"] is False
        assert COMMIT_RE.fullmatch(meta["commit"])

        usage = meta["usage"]
        assert isinstance(usage, dict)
        assert int(usage["calls"]) > 0
        assert int(usage["in"]) > 0
        assert int(usage["out"]) > 0
        assert int(usage["thinking"]) > 0
        assert float(usage["cost_usd"]) > 0.0

        dev_seeds = set(meta["dev_seeds"])
        fresh_seeds = set(meta["fresh_seeds"])
        assert dev_seeds.isdisjoint(JUDGE_SEEDS)
        assert fresh_seeds.isdisjoint(JUDGE_SEEDS)
        assert dev_seeds.isdisjoint(fresh_seeds)

        gens_doc = json.loads((run_dir / "generations.json").read_text(encoding="utf-8"))
        assert gens_doc["model_id"] == "gemini-4-carbon"
        assert gens_doc["tier"] == expected_tier
        assert len(gens_doc["generations"]) == int(meta["gens"])
        hof_curve = [float(g["hof_best_fitness"]) for g in gens_doc["generations"]]
        assert hof_curve == sorted(hof_curve)


def test_mole_forge_hall_of_fame_strategies_valid_and_executable(monkeypatch: pytest.MonkeyPatch) -> None:
    for env_key in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "GOOGLE_GENERATIVE_AI_API_KEY", "GEMINI_GATEWAY_URL"):
        monkeypatch.delenv(env_key, raising=False)

    total_entries = 0
    for run_name, expected_tier in EXPECTED_RUNS.items():
        run_dir = ADAPTIVE_MOLE_DIR / run_name
        meta = json.loads((run_dir / "meta.json").read_text(encoding="utf-8"))
        top_strat = MoleStrategy.from_json(meta["top_strategy"])
        assert MoleStrategy.from_json(top_strat.to_json()) == top_strat

        hof_lines = [
            ln for ln in (run_dir / "hall_of_fame.jsonl").read_text(encoding="utf-8").splitlines() if ln.strip()
        ]
        assert len(hof_lines) == int(meta["hof_size"])
        assert len(hof_lines) > 0

        ranks: list[int] = []
        for ln in hof_lines:
            row = json.loads(ln)
            ranks.append(int(row["rank"]))
            parsed = MoleStrategy.from_json(row["strategy_json"])
            assert MoleStrategy.from_json(parsed.to_json()) == parsed
            assert float(row["solver_acc"]) >= float(meta["min_solver_acc"])
            total_entries += 1
        assert ranks == list(range(1, len(hof_lines) + 1))

        ep = run_episode(Env(expected_tier, 5020, mole_strategy=top_strat), SolverPolicy(expected_tier))
        assert -1.0 <= float(ep.score) <= 1.0

    assert total_entries == 57


def test_mole_forge_40_seed_holdout_generalization_and_solvability() -> None:
    ref_doc = json.loads(
        (ADAPTIVE_MOLE_DIR / "mole-forge-carbon-hard-deep" / "holdout_generalization.json").read_text(encoding="utf-8")
    )
    ref_top_keys = set(ref_doc.keys())
    ref_summary_keys = set(ref_doc["summary"].keys())
    ref_split_keys = set(ref_doc["splits"].keys())
    ref_eval_keys = set(ref_doc["default_mole"]["confirm"].keys())
    expected_invs = ["solver", "grok_tactics", "heuristic", "hinted_heuristic", "obvious_heuristic"]
    expected_per_inv_keys = {"grok_tactics", "heuristic", "hinted_heuristic", "obvious_heuristic"}

    for run_name, expected_tier in EXPECTED_RUNS.items():
        run_dir = ADAPTIVE_MOLE_DIR / run_name
        meta = json.loads((run_dir / "meta.json").read_text(encoding="utf-8"))
        doc = json.loads((run_dir / "holdout_generalization.json").read_text(encoding="utf-8"))

        assert set(doc.keys()) == ref_top_keys
        assert set(doc["summary"].keys()) == ref_summary_keys
        assert set(doc["splits"].keys()) == ref_split_keys
        assert doc["schema_version"] == "1.0"
        assert doc["source_run_dir"] == f"results/gemini/roles_carbon/adaptive_mole/{run_name}"
        assert doc["source_hof"] == f"results/gemini/roles_carbon/adaptive_mole/{run_name}/hall_of_fame.jsonl"
        assert doc["source_model_id"] == "gemini-4-carbon"
        assert doc["source_commit"] == meta["commit"]
        assert doc["fake_env"] is False
        assert doc["tier"] == expected_tier
        assert doc["tiers_version"] == "v1.4"
        assert doc["investigators"] == expected_invs

        unseen_seeds = doc["splits"]["unseen_seeds"]
        confirm_seeds = doc["splits"]["confirm_seeds"]
        combined_seeds = doc["splits"]["combined_seeds"]
        assert len(unseen_seeds) == 10
        assert confirm_seeds == CONFIRM_SEEDS
        assert len(confirm_seeds) == 40
        assert combined_seeds == [*unseen_seeds, *confirm_seeds]
        assert set(confirm_seeds).isdisjoint(set(unseen_seeds))
        assert set(confirm_seeds).isdisjoint(set(meta["dev_seeds"]))
        assert set(confirm_seeds).isdisjoint(set(meta["fresh_seeds"]))
        assert set(confirm_seeds).isdisjoint(JUDGE_SEEDS)

        evolved = doc["evolved_strategies"]
        assert len(evolved) >= 1
        assert doc["summary"]["n_evolved_evaluated"] == len(evolved)

        default_entry = doc["default_mole"]
        assert default_entry["confirm"]["feasible"] is True
        assert float(default_entry["confirm"]["solver_acc"]) >= 0.90

        for entry in [default_entry, *evolved]:
            MoleStrategy.from_json(entry["strategy_json"])
            for split_name in ("unseen", "confirm", "combined"):
                ev = entry[split_name]
                assert set(ev.keys()) == ref_eval_keys
                assert set(ev["per_investigator"].keys()) == expected_per_inv_keys
                for inv_metrics in ev["per_investigator"].values():
                    assert float(inv_metrics["regret"]) == pytest.approx(
                        float(ev["solver_score"]) - float(inv_metrics["score"]), abs=1e-9
                    )
            nu = len(unseen_seeds)
            nc = len(confirm_seeds)
            u_sc = float(entry["unseen"]["solver_score"])
            c_sc = float(entry["confirm"]["solver_score"])
            assert float(entry["combined"]["solver_score"]) == pytest.approx(
                (nu * u_sc + nc * c_sc) / (nu + nc), abs=1e-9
            )

        for entry in evolved:
            c_ev = entry["confirm"]
            assert float(c_ev["solver_acc"]) >= 0.65
            assert float(c_ev["solver_score"]) >= FEASIBLE_SOLVER_RATIO * float(c_ev["baseline_solver_score"])
            assert float(c_ev["solver_score"]) > 0.0
            assert float(c_ev["min_regret"]) > 0.0
            assert "grok_tactics" in c_ev["beaten"]
            assert "obvious_heuristic" in c_ev["beaten"]

        if expected_tier in ("medium", "hard"):
            top1_confirm = evolved[0]["confirm"]
            assert top1_confirm["feasible"] is True
            assert float(top1_confirm["solver_acc"]) >= float(doc["min_solver_acc"])
            assert float(doc["summary"]["top1_confirm_solver_acc"]) >= float(doc["min_solver_acc"])

        if run_name == "mole-forge-carbon-v14":
            assert doc["summary"]["all_evolved_solvable_confirm"] is True
            assert doc["summary"]["all_evolved_solvable_combined"] is True


def test_mole_forge_zero_secrets_zero_forbidden_dashes_and_hygiene() -> None:
    this_file = Path(__file__).resolve()
    targets: list[Path] = [this_file]
    for run_name in EXPECTED_RUNS:
        targets.extend(sorted((ADAPTIVE_MOLE_DIR / run_name).iterdir()))

    for path in targets:
        text = path.read_text(encoding="utf-8")
        for bad_dash in FORBIDDEN_DASHES:
            assert bad_dash not in text, f"forbidden dash {ord(bad_dash):#x} in {path}"
        for rx in SECRET_PATTERNS:
            assert rx.search(text) is None, f"secret pattern {rx.pattern} matched in {path}"
        if path.suffix == ".json":
            json.loads(text)

    src = this_file.read_text(encoding="utf-8")
    tokens = list(tokenize.generate_tokens(io.StringIO(src).readline))
    assert [tok for tok in tokens if tok.type == tokenize.COMMENT] == []
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            assert ast.get_docstring(node) is None
