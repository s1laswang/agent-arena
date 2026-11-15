from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from canary import rules
from canary.baselines import ObviousHeuristic
from canary.env import Env
from canary.eval import run_episode
from canary.mole.dsl import MoleStrategy
from canary.solver.policy import SolverPolicy

ADAPTIVE_MOLE_DIR = ROOT / "results" / "gemini" / "roles_carbon" / "adaptive_mole"
EXPECTED_SCOPE = "arena mode, not the judged v1.4 environment"

EXPECTED_RUNS: tuple[str, ...] = (
    "paired-designer-carbon",
    "paired-designer-carbon-hard",
    "paired-solvable-scenarios-carbon",
    "paired-skill-designer-carbon-easy-s10_14",
    "paired-skill-designer-carbon-easy-s15_19",
    "paired-skill-designer-carbon-med-s10_14",
    "paired-skill-designer-carbon-med-s15_19",
    "paired-skill-designer-carbon-hard",
    "paired-skill-designer-carbon-hard-s10_14",
    "paired-skill-designer-carbon-hard-s15_19",
)

EXPECTED_FILES = frozenset({"meta.json", "design_report.json", "skill_gap.json", "summary.md"})
EXPECTED_RUNGS: tuple[str, ...] = (
    "full_solver",
    "no_ev_commit",
    "single_canary_per_day",
    "binary_canary_only",
    "no_log_interview_updates",
    "heuristic_bisection",
    "do_nothing",
)
EXPECTED_HEADLINE_RUNGS: tuple[str, ...] = (
    "full_solver",
    "no_ev_commit",
    "binary_canary_only",
    "heuristic_bisection",
    "do_nothing",
)

FORBIDDEN_DASHES: tuple[str, ...] = (
    chr(0x2014),
    chr(0x2013),
    chr(0x2012),
    chr(0x2015),
)

COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
SECRET_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?<![0-9A-Za-z+/_-])AIza[0-9A-Za-z_-]{16,}"),
    re.compile(r"(?<![0-9A-Za-z+/_-])sk-(?:proj-|ant-|live-|test-|svcacct-)?[0-9A-Za-z_-]{16,}"),
    re.compile(r"(?<![0-9A-Za-z_])ya29\.[0-9A-Za-z_-]{12,}"),
    re.compile(
        r"(?i:\b(?:gemini_api_key|google_api_key|google_generative_ai_api_key|openai_api_key|anthropic_api_key|xai_api_key)\b)"
        r"[\"']?[ \t]*[:=][ \t]*[^\s\"',}\]]{4,}"
    ),
)


def test_paired_test_source_has_no_comments_or_forbidden_dashes():
    src = Path(__file__).read_text(encoding="utf-8")
    assert chr(0x23) not in src
    for dash in FORBIDDEN_DASHES:
        assert dash not in src


def test_all_ten_paired_designer_folders_and_provenance():
    assert len(EXPECTED_RUNS) == 10
    tiers_seen: set[str] = set()
    total_calls = 0
    total_valid = 0
    total_kept = 0

    for run_name in EXPECTED_RUNS:
        run_dir = ADAPTIVE_MOLE_DIR / run_name
        assert run_dir.is_dir(), f"missing folder: {run_dir}"
        present = frozenset(p.name for p in run_dir.iterdir() if p.is_file())
        assert present == EXPECTED_FILES, f"{run_name}: unexpected file set {sorted(present)}"

        meta = json.loads((run_dir / "meta.json").read_text(encoding="utf-8"))
        assert meta["role"] == "adaptive_mole"
        assert meta["subrole"] in {"paired_designer", "paired_skill_designer"}
        assert meta["model_id"] == "gemini-4-carbon"
        assert meta["tiers_version"] == "v1.4"
        assert meta["tier"] in {"easy", "medium", "hard"}
        assert meta["environment_scope"] == EXPECTED_SCOPE
        assert COMMIT_RE.fullmatch(meta["commit"])
        assert meta["llm_ok"] is True
        assert int(meta["n_llm_valid"]) >= 4
        assert int(meta["n_kept"]) >= 2
        assert isinstance(meta.get("top_scenario_name"), str) and meta["top_scenario_name"].strip()

        usage = meta["usage"]
        assert int(usage["calls"]) >= 1
        assert int(usage["in"]) > 0
        assert int(usage["out"]) > 0
        assert int(usage["thinking"]) > 0
        assert float(usage["cost_usd"]) > 0.0

        tiers_seen.add(meta["tier"])
        total_calls += int(usage["calls"])
        total_valid += int(meta["n_llm_valid"])
        total_kept += int(meta["n_kept"])

    assert tiers_seen == {"easy", "medium", "hard"}
    assert total_calls == 10
    assert total_valid == 56
    assert total_kept == 49


def test_mole_strategy_from_json_validity_across_all_ten_runs():
    total_strategies_checked = 0
    for run_name in EXPECTED_RUNS:
        run_dir = ADAPTIVE_MOLE_DIR / run_name
        meta = json.loads((run_dir / "meta.json").read_text(encoding="utf-8"))
        design_doc = json.loads((run_dir / "design_report.json").read_text(encoding="utf-8"))
        gap_doc = json.loads((run_dir / "skill_gap.json").read_text(encoding="utf-8"))

        candidates_to_check: list[dict] = []
        for row in design_doc.get("rows", []):
            if isinstance(row, dict) and isinstance(row.get("candidate"), dict):
                candidates_to_check.append(row["candidate"])
        for cand in design_doc.get("kept", []):
            if isinstance(cand, dict):
                candidates_to_check.append(cand)
        top_sel = design_doc.get("selected_top_scenario")
        assert isinstance(top_sel, dict) and isinstance(top_sel.get("candidate"), dict)
        candidates_to_check.append(top_sel["candidate"])

        gap_cand = gap_doc.get("selected_scenario")
        assert isinstance(gap_cand, dict)
        candidates_to_check.append(gap_cand)

        assert candidates_to_check
        for cand in candidates_to_check:
            ms_json = cand.get("mole_strategy")
            assert isinstance(ms_json, dict)
            strat = MoleStrategy.from_json(ms_json)
            roundtrip = MoleStrategy.from_json(json.loads(json.dumps(strat.to_json())))
            assert roundtrip == strat
            total_strategies_checked += 1

        top_strat = MoleStrategy.from_json(gap_cand["mole_strategy"])
        env = Env(meta["tier"], 0, mole_strategy=top_strat)
        res = env.call("status", {})
        assert res.ok is True

    assert total_strategies_checked >= 100


def test_skill_gap_holdout_solver_vs_heuristic_separation_all_ten_runs():
    required_gap_keys = {
        "title",
        "role",
        "subrole",
        "model_id",
        "tiers_version",
        "known_v_mode",
        "tier",
        "commit",
        "timestamp",
        "seed_start",
        "seed_end",
        "n_episodes",
        "seeds",
        "rungs",
        "headline_rungs",
        "selected_scenario",
        "designed_rows",
        "baseline_rows",
        "comparison_rows",
        "headline_comparison",
    }

    forty_seed_runs = 0
    for run_name in EXPECTED_RUNS:
        run_dir = ADAPTIVE_MOLE_DIR / run_name
        meta = json.loads((run_dir / "meta.json").read_text(encoding="utf-8"))
        gap_doc = json.loads((run_dir / "skill_gap.json").read_text(encoding="utf-8"))

        assert required_gap_keys.issubset(gap_doc.keys()), f"{run_name}: missing keys in skill_gap.json"
        assert gap_doc["model_id"] == "gemini-4-carbon"
        assert gap_doc["tier"] == meta["tier"]
        assert gap_doc["tiers_version"] == "v1.4"
        assert gap_doc["commit"] == meta["commit"]

        seeds = gap_doc["seeds"]
        n_eps = int(gap_doc["n_episodes"])
        assert len(seeds) == n_eps
        assert n_eps >= 20
        if n_eps == 40:
            forty_seed_runs += 1
        if run_name in {"paired-designer-carbon", "paired-designer-carbon-hard"}:
            assert seeds == list(range(5360, 5400))
            assert n_eps == 40
        assert all(s not in rules.JUDGE_SEEDS and s not in rules.HELDOUT_SEEDS for s in seeds)

        assert tuple(r["rung"] for r in gap_doc["rungs"]) == EXPECTED_RUNGS
        assert tuple(gap_doc["headline_rungs"]) == EXPECTED_HEADLINE_RUNGS
        assert tuple(r["rung"] for r in gap_doc["designed_rows"]) == EXPECTED_RUNGS
        assert tuple(r["rung"] for r in gap_doc["baseline_rows"]) == EXPECTED_RUNGS
        assert tuple(r["rung"] for r in gap_doc["comparison_rows"]) == EXPECTED_RUNGS

        hc = gap_doc["headline_comparison"]
        assert tuple(hc.keys()) == EXPECTED_HEADLINE_RUNGS

        solver_mean = float(hc["full_solver"]["designed_mean_score"])
        heur_mean = float(hc["heuristic_bisection"]["designed_mean_score"])
        do_nothing_mean = float(hc["do_nothing"]["designed_mean_score"])
        solver_acc = float(hc["full_solver"]["designed_accuracy"])
        heur_acc = float(hc["heuristic_bisection"]["designed_accuracy"])

        assert abs(float(meta["eval_full_solver_mean"]) - solver_mean) < 1e-6
        assert abs(float(meta["eval_heuristic_mean"]) - heur_mean) < 1e-6
        assert meta["top_scenario_name"] == gap_doc["selected_scenario"]["name"]

        assert solver_mean >= 0.45, f"{run_name}: solver_mean={solver_mean}"
        assert heur_mean <= 0.20, f"{run_name}: heur_mean={heur_mean}"
        assert (solver_mean - heur_mean) >= 1.20, f"{run_name}: separation={solver_mean - heur_mean}"
        assert solver_acc >= 0.70
        assert solver_acc > heur_acc
        assert do_nothing_mean == 0.0

    assert forty_seed_runs == 8

    med_gap = json.loads(
        (ADAPTIVE_MOLE_DIR / "paired-designer-carbon" / "skill_gap.json").read_text(encoding="utf-8")
    )
    cand = med_gap["selected_scenario"]
    orig_tier = rules.TIERS["medium"]
    valid_knobs = {k: v for k, v in cand["knobs"].items() if hasattr(orig_tier, k) and v is not None}
    rules.TIERS["medium"] = replace(orig_tier, **valid_knobs)
    try:
        ep_solver = run_episode(Env("medium", 5360, mole_strategy=cand["mole_strategy"]), SolverPolicy())
        ep_heur = run_episode(Env("medium", 5360, mole_strategy=cand["mole_strategy"]), ObviousHeuristic(seed=5360))
    finally:
        rules.TIERS["medium"] = orig_tier
    assert ep_solver.score > ep_heur.score


def test_zero_secrets_zero_forbidden_dashes_and_sanitized_paths():
    checked_files = 0
    for run_name in EXPECTED_RUNS:
        run_dir = ADAPTIVE_MOLE_DIR / run_name
        for fname in sorted(EXPECTED_FILES):
            fpath = run_dir / fname
            text = fpath.read_text(encoding="utf-8")
            for dash in FORBIDDEN_DASHES:
                assert dash not in text, f"forbidden dash in {fpath}"
            assert "results/gemini_roles/" not in text, f"unsanitized path in {fpath}"
            for rx in SECRET_PATTERNS:
                assert rx.search(text) is None, f"secret pattern matched in {fpath}"
            if fname.endswith(".json"):
                parsed = json.loads(text)
                assert isinstance(parsed, dict)
            checked_files += 1
    assert checked_files == 40
