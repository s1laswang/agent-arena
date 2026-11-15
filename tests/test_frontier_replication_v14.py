from __future__ import annotations

import importlib.util
import json
import math
import os
import sys
from collections import Counter
from multiprocessing import get_all_start_methods, get_context
from pathlib import Path

from canary.analysis.accuse import audit_episode
from canary.analysis.gap import load_runs, mean_ci
from canary.analysis.tags import to_result
from canary.solver.regret import attribute

ROOT = Path(__file__).resolve().parents[1]
EXT_ROOT = ROOT / "results" / "frontier_replication" / "v1.4" / "opencode-gemini-4-carbon-ext"
EXT_HARD = EXT_ROOT / "hard"
COMMITTED_V14 = ROOT / "data" / "runs" / "committed" / "v1.4"
COMMITTED_PRIMARY_HARD = COMMITTED_V14 / "opencode-gemini-4-carbon" / "hard"
COMMITTED_EXT_HARD = COMMITTED_V14 / "opencode-gemini-4-carbon-ext" / "hard"
REF_ROOT = COMMITTED_V14 / "reference"
REF_HARD = REF_ROOT / "solver-hard-seeds30to59"
TRAJECTORIES_REPORT = ROOT / "docs" / "reports" / "frontier_ext30to59_trajectories.md"
EXPECTED_SEEDS = [30, 34, 42, 45, 48, 57, 58]
COMMITTED_G1_SEEDS = [34, 37]
FLEET_NEW_SEEDS = [30, 42, 45, 48, 57, 58]
EXT8_SEEDS = [30, 34, 37, 42, 45, 48, 57, 58]
POOLED38_SEEDS = list(range(30)) + EXT8_SEEDS
FINITE_STAT_KEYS = (
    "mean",
    "ci",
    "accuracy",
    "accused_rate",
    "p_accused",
    "accuse_day",
    "solver_same_seeds",
    "ratio",
    "ratio_lo",
    "ratio_hi",
    "diff",
    "diff_ci",
    "post_expected",
    "post_expected_ratio",
    "post_expected_lo",
    "post_expected_hi",
    "solver_post_expected",
)


def _load_script(name: str, rel_path: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel_path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _read_jsonl(path: Path) -> list[dict]:
    assert path.is_file()
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _ok_tool_count(ep: dict, tool_name: str) -> int:
    return sum(
        1
        for step in (ep.get("steps") or [])
        if step.get("tool") == tool_name and (step.get("result") or {}).get("ok") is True
    )


def _episode_v(ep: dict) -> float:
    meta = ep.get("meta") or {}
    return float(meta.get("V", meta.get("V_final")))


def _eval_episode_regret_and_audit(task: tuple[dict, bool]) -> dict:
    ep, need_regret = task
    res = to_result(ep)
    att = (attribute(res) or []) if need_regret else []
    aud = audit_episode(res)
    total_regret = sum(float(item.get("regret", 0.0)) for item in att)
    accuse_regret = sum(
        float(item.get("regret", 0.0)) for item in att if item.get("action") == "accuse"
    )
    tag_counts = dict(Counter(tag for item in att for tag in item.get("tags", [])))
    v_val = _episode_v(ep)
    p_acc = aud["p_accused"]
    luck = (p_acc * v_val - (1.0 - p_acc)) if ep.get("accused") else 0.0
    return {
        "audit": aud,
        "regret": total_regret,
        "accuse_regret": accuse_regret,
        "tag_counts": tag_counts,
        "v": v_val,
        "luck": luck,
    }


def _batch_eval_episodes(tasks: list[tuple[dict, bool]]) -> list[dict]:
    if "fork" in get_all_start_methods() and len(tasks) > 4:
        ctx = get_context("fork")
        procs = min(16, os.cpu_count() or 4, len(tasks))
        with ctx.Pool(processes=procs) as pool:
            return pool.map(_eval_episode_regret_and_audit, tasks)
    return [_eval_episode_regret_and_audit(task) for task in tasks]


def _parse_section_table(md_text: str, section_title: str) -> list[list[str]]:
    lines = md_text.splitlines()
    start_idx = None
    for idx, line in enumerate(lines):
        if section_title in line:
            start_idx = idx + 1
            break
    assert start_idx is not None
    table_lines: list[str] = []
    for line in lines[start_idx:]:
        stripped = line.strip()
        if stripped.startswith("|"):
            table_lines.append(stripped)
        elif table_lines:
            break
    assert len(table_lines) >= 3
    return [[cell.strip() for cell in ln.strip("|").split("|")] for ln in table_lines[2:]]


def test_frontier_replication_v14_manifest_and_transcripts():
    episodes = _read_jsonl(EXT_HARD / "episodes.jsonl")
    assert [ep["seed"] for ep in episodes] == EXPECTED_SEEDS
    for ep in episodes:
        assert ep["tier"] == "hard"
        assert ep["agent"] == "opencode:google/gemini-4-carbon"
        assert ep["end_reason"] == "accused"
        assert (ep.get("meta") or {}).get("valid") is True
        assert len(ep.get("steps") or []) > 0

    meta = json.loads((EXT_HARD / "meta.json").read_text(encoding="utf-8"))
    assert meta["tier"] == "hard"
    assert meta["tiers_version"] == "v1.4"
    assert meta["seeds"] == EXPECTED_SEEDS

    transcripts_dir = EXT_HARD / "transcripts"
    assert transcripts_dir.is_dir()
    tr_files = sorted(transcripts_dir.iterdir())
    assert [p.name for p in tr_files] == [f"{seed}.txt" for seed in EXPECTED_SEEDS]
    assert all(p.is_file() and p.stat().st_size > 0 for p in tr_files)

    tags = json.loads((EXT_ROOT / "tags.json").read_text(encoding="utf-8"))
    assert tags["opencode:google/gemini-4-carbon"]["episodes"] == len(EXPECTED_SEEDS)
    assert (EXT_ROOT / "accuse.md").is_file()


def test_frontier_replication_v14_replays_and_pairs_with_reference(monkeypatch):
    monkeypatch.setenv("CANARY_ALLOW_DEV", "1")
    vr = _load_script("verify_replay", "scripts/verify_replay.py")
    gvr = _load_script("gap_vs_reference", "scripts/gap_vs_reference.py")

    ext_path = EXT_HARD / "episodes.jsonl"
    ref_path = REF_HARD / "episodes.jsonl"
    episodes = _read_jsonl(ext_path)
    for ep in episodes:
        rep = vr.replay_episode(ep)
        assert abs(rep["score"] - ep["score"]) < 1e-9
        assert rep["accused"] == ep["accused"]
        assert rep["correct"] == ep["correct"]
        assert rep["final_day"] == ep["final_day"]
    assert vr.main([str(ext_path)]) == 0

    ref_episodes = _read_jsonl(ref_path)
    assert [ep["seed"] for ep in ref_episodes] == list(range(30, 60))
    ref_by_seed = {ep["seed"]: ep for ep in ref_episodes}
    for ep in episodes:
        ref_ep = ref_by_seed[ep["seed"]]
        assert ref_ep["tier"] == "hard"
        assert ref_ep["agent"] == "solver"
        rep_ref = vr.replay_episode(ref_ep)
        assert abs(rep_ref["score"] - ref_ep["score"]) < 1e-9
        assert rep_ref["accused"] == ref_ep["accused"]

    ext_map, ext_invalid = gvr.collect([str(ext_path)])
    ref_map, ref_invalid = gvr.collect([str(ref_path)])
    assert ext_invalid == 0 and ref_invalid == 0
    expected_keys = [("hard", seed) for seed in EXPECTED_SEEDS]
    assert sorted(ext_map.keys()) == expected_keys
    assert all(key in ref_map for key in expected_keys)
    ext_scores = [ext_map[key]["score"] for key in expected_keys]
    ref_scores = [ref_map[key]["score"] for key in expected_keys]
    boot = gvr.paired_bootstrap(ext_scores, ref_scores, n_boot=2000)
    assert boot["n"] == len(EXPECTED_SEEDS)
    assert math.isfinite(boot["ratio"]) and boot["ratio"] > 0.0
    assert boot["diff_ci"][0] <= boot["diff"] <= boot["diff_ci"][1]


def _parse_md_rows(path: Path) -> list[list[str]]:
    assert path.is_file()
    lines = [ln.strip() for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip().startswith("|")]
    assert len(lines) >= 3
    return [[cell.strip() for cell in ln.strip("|").split("|")] for ln in lines[2:]]


def _assert_md_matches_json(md_path: Path, json_rows: list[dict]) -> None:
    md_rows = _parse_md_rows(md_path)
    assert len(md_rows) == len(json_rows)
    by_key = {(r["tier"], r["label"]): r for r in json_rows}
    assert len(by_key) == len(json_rows)
    for cells in md_rows:
        assert len(cells) == 13
        row = by_key[(cells[0], cells[1])]
        assert cells[2] == str(row["n"])
        assert cells[3].startswith(f"{row['mean']:.3f} ")
        assert cells[3].endswith(f" {row['ci']:.3f}")
        assert cells[4] == f"{row['accuracy']:.2f}"
        assert cells[5] == f"{row['accused_rate']:.2f}"
        assert cells[6] == f"{row['accuse_day']:.1f}"
        assert cells[8] == f"{row['solver_same_seeds']:.3f}"
        assert cells[11] == f"{row['post_expected']:.3f}"
        if row["agent"] == "solver":
            assert cells[9] == "-"
            assert cells[10] == "-"
            assert cells[12] == "-"
        else:
            assert cells[10].startswith(f"{row['diff']:.3f} ")
            assert cells[10].endswith(f" {row['diff_ci']:.3f}")


def _assert_cohort_stats(
    row: dict,
    episodes: list[dict],
    solver_by_seed: dict[int, dict],
    expected_seeds: list[int],
) -> None:
    assert row["tier"] == "hard"
    assert row["agent"] == "opencode:google/gemini-4-carbon"
    assert row["n"] == len(expected_seeds)
    assert row["seeds"] == expected_seeds
    assert [ep["seed"] for ep in episodes] == expected_seeds
    for key in FINITE_STAT_KEYS:
        val = row[key]
        assert isinstance(val, (int, float)) and not isinstance(val, bool)
        assert math.isfinite(val)

    scores = [ep["score"] for ep in episodes]
    sol_scores = [solver_by_seed[ep["seed"]]["score"] for ep in episodes]
    diffs = [x - y for x, y in zip(scores, sol_scores)]

    exp_mean, exp_ci = mean_ci(scores)
    exp_sol_mean = sum(sol_scores) / len(sol_scores)
    exp_diff, exp_diff_ci = mean_ci(diffs)

    assert row["ci"] >= 0.0
    assert row["diff_ci"] >= 0.0
    assert row["ratio"] > 0.0
    assert abs(row["mean"] - exp_mean) < 1e-9
    assert abs(row["ci"] - exp_ci) < 1e-9
    assert abs(row["solver_same_seeds"] - exp_sol_mean) < 1e-9
    assert abs(row["diff"] - exp_diff) < 1e-9
    assert abs(row["diff_ci"] - exp_diff_ci) < 1e-9
    assert abs(row["ratio"] - (exp_mean / exp_sol_mean)) < 1e-9
    assert row["ratio_lo"] <= row["ratio"] <= row["ratio_hi"]
    assert row["post_expected_lo"] <= row["post_expected_ratio"] <= row["post_expected_hi"]


def test_frontier_replication_v14_readme_and_committed_g1_replay(monkeypatch):
    monkeypatch.setenv("CANARY_ALLOW_DEV", "1")
    vr = _load_script("verify_replay", "scripts/verify_replay.py")

    readme_path = EXT_ROOT / "README.md"
    assert readme_path.is_file()
    readme_text = readme_path.read_text(encoding="utf-8")
    for required in (
        "paired_table_fleet7.md",
        "paired_table_fleet7.json",
        "paired_table_ext8_combined.md",
        "paired_table_ext8_combined.json",
        "paired_table_pooled38.md",
        "paired_table_pooled38.json",
        "accuse_ext8_combined.md",
        "tags_ext8_combined.json",
        "frontier_ext30to59_trajectories.md",
        "check_frontier_ext_replication.py",
        "30, 34, 42, 45, 48, 57, 58",
        "30, 34, 37, 42, 45, 48, 57, 58",
        "0-29, 30, 34, 37, 42, 45, 48, 57, 58",
        "[34, 37]",
        "[30, 42, 45, 48, 57, 58]",
        "7/7 episodes replay-verified",
    ):
        assert required in readme_text
    for selection_ref in (
        "../../../../docs/reports/frontier_ext30to59_selection_sensitivity.md",
        "../../../../scripts/analyze_ext30to59_selection.py",
        "python scripts/analyze_ext30to59_selection.py --check",
    ):
        assert selection_ref in readme_text
    assert (EXT_ROOT / "../../../../docs/reports/frontier_ext30to59_selection_sensitivity.md").resolve().is_file()
    assert (EXT_ROOT / "../../../../scripts/analyze_ext30to59_selection.py").resolve().is_file()

    committed_ext_path = COMMITTED_EXT_HARD / "episodes.jsonl"
    committed_eps = _read_jsonl(committed_ext_path)
    assert [ep["seed"] for ep in committed_eps] in (COMMITTED_G1_SEEDS, EXT8_SEEDS)
    g1_eps = [ep for ep in committed_eps if ep["seed"] in set(COMMITTED_G1_SEEDS)]
    assert [ep["seed"] for ep in g1_eps] == COMMITTED_G1_SEEDS
    for ep in committed_eps:
        assert ep["tier"] == "hard"
        assert ep["agent"] == "opencode:google/gemini-4-carbon"
        assert ep["end_reason"] == "accused"
        assert (ep.get("meta") or {}).get("valid") is True
        rep = vr.replay_episode(ep)
        assert abs(rep["score"] - ep["score"]) < 1e-9
        assert rep["accused"] == ep["accused"]
        assert rep["correct"] == ep["correct"]
        assert rep["final_day"] == ep["final_day"]
    assert vr.main([str(committed_ext_path)]) == 0


def test_frontier_replication_v14_paired_tables_fleet7_ext8_pooled38():
    for fname in (
        "README.md",
        "paired_table_fleet7.json",
        "paired_table_fleet7.md",
        "paired_table_ext8_combined.json",
        "paired_table_ext8_combined.md",
        "paired_table_pooled38.json",
        "paired_table_pooled38.md",
    ):
        assert (EXT_ROOT / fname).is_file()

    fleet_eps = _read_jsonl(EXT_HARD / "episodes.jsonl")
    committed_eps = _read_jsonl(COMMITTED_EXT_HARD / "episodes.jsonl")
    assert [ep["seed"] for ep in committed_eps] in (COMMITTED_G1_SEEDS, EXT8_SEEDS)
    primary_hard_eps = _read_jsonl(COMMITTED_PRIMARY_HARD / "episodes.jsonl")
    assert [ep["seed"] for ep in primary_hard_eps] == list(range(30))

    solver_hard_eps = [
        ep for ep in load_runs(REF_ROOT) if ep["agent"] == "solver" and ep["tier"] == "hard"
    ]
    solver_by_seed = {ep["seed"]: ep for ep in solver_hard_eps}
    assert sorted(solver_by_seed) == list(range(60))

    g1_seed_set = set(COMMITTED_G1_SEEDS)
    g1_eps = [ep for ep in committed_eps if ep["seed"] in g1_seed_set]
    assert [ep["seed"] for ep in g1_eps] == COMMITTED_G1_SEEDS
    fleet_new_eps = [ep for ep in fleet_eps if ep["seed"] not in g1_seed_set]
    assert [ep["seed"] for ep in fleet_new_eps] == FLEET_NEW_SEEDS

    dedup_ext8_eps = sorted(g1_eps + fleet_new_eps, key=lambda ep: ep["seed"])
    assert [ep["seed"] for ep in dedup_ext8_eps] == EXT8_SEEDS
    if [ep["seed"] for ep in committed_eps] == EXT8_SEEDS:
        assert [ep["score"] for ep in committed_eps] == [ep["score"] for ep in dedup_ext8_eps]
    g1_by_seed = {ep["seed"]: ep for ep in g1_eps}
    fleet_by_seed = {ep["seed"]: ep for ep in fleet_eps}
    dedup_by_seed = {ep["seed"]: ep for ep in dedup_ext8_eps}
    assert dedup_by_seed[34]["score"] == g1_by_seed[34]["score"]
    assert dedup_by_seed[34]["score"] != fleet_by_seed[34]["score"]

    pooled38_eps = primary_hard_eps + dedup_ext8_eps
    assert [ep["seed"] for ep in pooled38_eps] == POOLED38_SEEDS

    fleet7_json = json.loads((EXT_ROOT / "paired_table_fleet7.json").read_text(encoding="utf-8"))
    assert len(fleet7_json) == 2
    assert fleet7_json[0]["n"] == 7
    _assert_cohort_stats(fleet7_json[0], fleet_eps, solver_by_seed, EXPECTED_SEEDS)
    assert fleet7_json[1]["agent"] == "solver"
    assert fleet7_json[1]["n"] == 30
    assert fleet7_json[1]["seeds"] == list(range(30, 60))
    sol_30_59_mean = sum(solver_by_seed[s]["score"] for s in range(30, 60)) / 30
    assert abs(fleet7_json[1]["mean"] - sol_30_59_mean) < 1e-9
    _assert_md_matches_json(EXT_ROOT / "paired_table_fleet7.md", fleet7_json)

    ext8_json = json.loads((EXT_ROOT / "paired_table_ext8_combined.json").read_text(encoding="utf-8"))
    assert len(ext8_json) == 2
    assert ext8_json[0]["n"] == 8
    _assert_cohort_stats(ext8_json[0], dedup_ext8_eps, solver_by_seed, EXT8_SEEDS)
    assert ext8_json[1]["agent"] == "solver"
    assert ext8_json[1]["n"] == 30
    assert ext8_json[1]["seeds"] == list(range(30, 60))
    assert abs(ext8_json[1]["mean"] - sol_30_59_mean) < 1e-9
    _assert_md_matches_json(EXT_ROOT / "paired_table_ext8_combined.md", ext8_json)

    pooled38_json = json.loads((EXT_ROOT / "paired_table_pooled38.json").read_text(encoding="utf-8"))
    assert len(pooled38_json) == 17
    hard_by_group = {
        (r["group"], r["label"]): r for r in pooled38_json if r["tier"] == "hard"
    }
    primary_row = hard_by_group[
        ("v1.4/opencode-gemini-4-carbon", "OpenCode + gemini-4-carbon over MCP (judges' shape)")
    ]
    ext8_row = hard_by_group[
        (
            "v1.4/opencode-gemini-4-carbon-ext",
            "OpenCode + gemini-4-carbon over MCP, extension (seeds 30-59)",
        )
    ]
    pooled_row = hard_by_group[
        (
            "v1.4/opencode-gemini-4-carbon+v1.4/opencode-gemini-4-carbon-ext",
            "OpenCode + gemini-4-carbon over MCP, pooled (primary + extension)",
        )
    ]
    solver60_row = hard_by_group[("v1.4/reference", "reference solver")]

    assert primary_row["n"] == 30
    assert ext8_row["n"] == 8
    assert pooled_row["n"] == 38
    _assert_cohort_stats(primary_row, primary_hard_eps, solver_by_seed, list(range(30)))
    _assert_cohort_stats(ext8_row, dedup_ext8_eps, solver_by_seed, EXT8_SEEDS)
    _assert_cohort_stats(pooled_row, pooled38_eps, solver_by_seed, POOLED38_SEEDS)
    assert solver60_row["agent"] == "solver"
    assert solver60_row["n"] == 60
    assert solver60_row["seeds"] == list(range(60))
    sol_0_59_mean = sum(solver_by_seed[s]["score"] for s in range(60)) / 60
    assert abs(solver60_row["mean"] - sol_0_59_mean) < 1e-9
    _assert_md_matches_json(EXT_ROOT / "paired_table_pooled38.md", pooled38_json)


def test_frontier_replication_v14_pr3_v14_runs_merged_compat(tmp_path, monkeypatch):
    fleet_eps = _read_jsonl(EXT_HARD / "episodes.jsonl")
    committed_eps = _read_jsonl(COMMITTED_EXT_HARD / "episodes.jsonl")
    g1_seed_set = set(COMMITTED_G1_SEEDS)
    g1_eps = [ep for ep in committed_eps if ep["seed"] in g1_seed_set]
    assert [ep["seed"] for ep in g1_eps] == COMMITTED_G1_SEEDS
    fleet_new_eps = [ep for ep in fleet_eps if ep["seed"] not in g1_seed_set]
    dedup_ext8_eps = sorted(g1_eps + fleet_new_eps, key=lambda ep: ep["seed"])
    assert [ep["seed"] for ep in dedup_ext8_eps] == EXT8_SEEDS

    sim_hard = tmp_path / "hard"
    sim_hard.mkdir(parents=True, exist_ok=True)
    (sim_hard / "episodes.jsonl").write_text(
        "\n".join(json.dumps(ep) for ep in dedup_ext8_eps) + "\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(sys.modules[__name__], "COMMITTED_EXT_HARD", sim_hard)
    assert COMMITTED_EXT_HARD == sim_hard

    test_frontier_replication_v14_readme_and_committed_g1_replay(monkeypatch)
    test_frontier_replication_v14_paired_tables_fleet7_ext8_pooled38()


def test_frontier_ext30to59_trajectories_report():
    assert TRAJECTORIES_REPORT.is_file()
    report_text = TRAJECTORIES_REPORT.read_text(encoding="utf-8")

    fleet_eps = _read_jsonl(EXT_HARD / "episodes.jsonl")
    committed_eps = _read_jsonl(COMMITTED_EXT_HARD / "episodes.jsonl")
    primary_hard_eps = _read_jsonl(COMMITTED_PRIMARY_HARD / "episodes.jsonl")
    ref_30_59_eps = _read_jsonl(REF_HARD / "episodes.jsonl")
    assert [ep["seed"] for ep in fleet_eps] == EXPECTED_SEEDS
    assert [ep["seed"] for ep in committed_eps] in (COMMITTED_G1_SEEDS, EXT8_SEEDS)
    assert [ep["seed"] for ep in primary_hard_eps] == list(range(30))
    assert [ep["seed"] for ep in ref_30_59_eps] == list(range(30, 60))

    solver_hard_eps = [
        ep for ep in load_runs(REF_ROOT) if ep["agent"] == "solver" and ep["tier"] == "hard"
    ]
    solver_by_seed = {ep["seed"]: ep for ep in solver_hard_eps}
    assert sorted(solver_by_seed) == list(range(60))

    g1_seed_set = set(COMMITTED_G1_SEEDS)
    g1_eps = [ep for ep in committed_eps if ep["seed"] in g1_seed_set]
    assert [ep["seed"] for ep in g1_eps] == COMMITTED_G1_SEEDS
    fleet_new_eps = [ep for ep in fleet_eps if ep["seed"] not in g1_seed_set]
    dedup_ext8_eps = sorted(g1_eps + fleet_new_eps, key=lambda ep: ep["seed"])
    assert [ep["seed"] for ep in dedup_ext8_eps] == EXT8_SEEDS
    ref_ext8_eps = [solver_by_seed[s] for s in EXT8_SEEDS]
    pooled38_eps = primary_hard_eps + dedup_ext8_eps

    solver_0_29_eps = [solver_by_seed[s] for s in range(30)]
    work_items: list[tuple[str, int, dict, bool]] = []
    for ep in g1_eps:
        work_items.append(("g1", ep["seed"], ep, True))
    for ep in fleet_eps:
        work_items.append(("fleet", ep["seed"], ep, True))
    for ep in primary_hard_eps:
        work_items.append(("primary", ep["seed"], ep, True))
    for ep in solver_0_29_eps:
        work_items.append(("solver", ep["seed"], ep, False))
    for ep in ref_30_59_eps:
        work_items.append(("solver", ep["seed"], ep, True))

    eval_results = _batch_eval_episodes([(item[2], item[3]) for item in work_items])
    eval_map = {
        (tag, seed): res for (tag, seed, _, _), res in zip(work_items, eval_results)
    }

    fleet_tags_json = json.loads((EXT_ROOT / "tags.json").read_text(encoding="utf-8"))[
        "opencode:google/gemini-4-carbon"
    ]
    ext8_tags_json = json.loads((EXT_ROOT / "tags_ext8_combined.json").read_text(encoding="utf-8"))[
        "opencode:google/gemini-4-carbon"
    ]
    comm_ext_tags_path = COMMITTED_V14 / "opencode-gemini-4-carbon-ext" / "tags.json"
    comm_ext_tags_json = json.loads(comm_ext_tags_path.read_text(encoding="utf-8"))[
        "opencode:google/gemini-4-carbon"
    ]
    assert fleet_tags_json["episodes"] == 7
    assert fleet_tags_json["regret_total"] == 1.1645
    assert ext8_tags_json["episodes"] == 8
    assert ext8_tags_json["regret_total"] == 0.6568
    if comm_ext_tags_json["episodes"] == 2:
        assert comm_ext_tags_json["regret_total"] == 0.0826
    else:
        assert comm_ext_tags_json["episodes"] == 8
        assert comm_ext_tags_json["regret_total"] == 0.6568

    fleet7_pt = json.loads((EXT_ROOT / "paired_table_fleet7.json").read_text(encoding="utf-8"))
    ext8_pt = json.loads((EXT_ROOT / "paired_table_ext8_combined.json").read_text(encoding="utf-8"))
    pooled38_pt = json.loads((EXT_ROOT / "paired_table_pooled38.json").read_text(encoding="utf-8"))
    comm_ext_pt = json.loads(
        (COMMITTED_V14 / "opencode-gemini-4-carbon-ext" / "paired_table_ext30to59.json").read_text(
            encoding="utf-8"
        )
    )
    pooled_hard_row = next(
        r
        for r in pooled38_pt
        if r["tier"] == "hard"
        and r["group"] == "v1.4/opencode-gemini-4-carbon+v1.4/opencode-gemini-4-carbon-ext"
    )

    sec2_rows = _parse_section_table(
        report_text, "2. Cohort Exploration, Posterior, and Regret Summary"
    )
    assert len(sec2_rows) == 6

    cohorts = [
        (
            "g1",
            g1_eps,
            [("g1", ep["seed"]) for ep in g1_eps],
            0.0826,
            comm_ext_pt[0] if comm_ext_pt[0]["n"] == 2 else None,
        ),
        (
            "fleet7",
            fleet_eps,
            [("fleet", ep["seed"]) for ep in fleet_eps],
            1.1645,
            fleet7_pt[0],
        ),
        (
            "ext8",
            dedup_ext8_eps,
            [
                ("g1" if ep["seed"] in g1_seed_set else "fleet", ep["seed"])
                for ep in dedup_ext8_eps
            ],
            0.6568,
            ext8_pt[0],
        ),
        (
            "solver_ext8",
            ref_ext8_eps,
            [("solver", ep["seed"]) for ep in ref_ext8_eps],
            0.8582,
            None,
        ),
        (
            "solver_30_59",
            ref_30_59_eps,
            [("solver", ep["seed"]) for ep in ref_30_59_eps],
            1.9935,
            fleet7_pt[1],
        ),
        (
            "pooled38",
            pooled38_eps,
            [("primary", ep["seed"]) for ep in primary_hard_eps]
            + [
                ("g1" if ep["seed"] in g1_seed_set else "fleet", ep["seed"])
                for ep in dedup_ext8_eps
            ],
            5.7992,
            pooled_hard_row,
        ),
    ]

    for cells, (_, eps, keys, expected_regret, pt_row) in zip(sec2_rows, cohorts):
        assert len(cells) == 13
        n_eps = len(eps)
        assert cells[1].endswith(f"(`{n_eps}`)")

        mean_can = sum(_ok_tool_count(ep, "plant_canary") for ep in eps) / n_eps
        mean_int = sum(_ok_tool_count(ep, "interview") for ep in eps) / n_eps
        mean_res = sum(_ok_tool_count(ep, "restrict_access") for ep in eps) / n_eps
        assert cells[2] == f"{mean_can:.2f}"
        assert cells[3] == f"{mean_int:.2f}"
        assert cells[4] == f"{mean_res:.2f}"

        acc_eps = [ep for ep in eps if ep.get("accused")]
        acc_day = sum(ep["final_day"] for ep in acc_eps) / len(acc_eps)
        expected_day_cell = (
            f"{acc_day:.1f}"
            if len(acc_eps) == n_eps
            else f"{acc_day:.1f} ({len(acc_eps)} acc)"
        )
        assert cells[5] == expected_day_cell

        v_mean = sum(eval_map[k]["v"] for k in keys) / n_eps
        p_vals = [
            eval_map[k]["audit"]["p_accused"]
            for k in keys
            if eval_map[k]["audit"]["p_accused"] is not None
        ]
        p_mean = sum(p_vals) / len(p_vals)
        assert cells[6] == f"{v_mean:.3f}"
        assert cells[7] == f"{p_mean:.3f}"

        raw_mean, raw_ci = mean_ci([ep["score"] for ep in eps])
        luck_mean = sum(eval_map[k]["luck"] for k in keys) / n_eps
        assert cells[8] == f"`{raw_mean:+.3f} +/- {raw_ci:.3f}`"
        assert cells[9] == f"`{luck_mean:+.3f}`"

        regret_unrounded = sum(eval_map[k]["regret"] for k in keys)
        assert round(regret_unrounded, 4) == expected_regret
        assert cells[10] == f"`{expected_regret:.4f}` (`{regret_unrounded / n_eps:.4f}`)"

        sol_raw_mean = sum(solver_by_seed[ep["seed"]]["score"] for ep in eps) / n_eps
        sol_luck_mean = (
            sum(eval_map[("solver", ep["seed"])]["luck"] for ep in eps) / n_eps
        )
        assert cells[11] == f"`{sol_raw_mean:+.3f}` / `{sol_luck_mean:+.3f}`"

        if pt_row is not None:
            assert pt_row["n"] == n_eps
            assert abs(pt_row["mean"] - raw_mean) < 1e-9
            assert abs(pt_row["ci"] - raw_ci) < 1e-9
            assert abs(pt_row["post_expected"] - luck_mean) < 1e-9
            assert abs(pt_row["solver_same_seeds"] - sol_raw_mean) < 1e-9
            assert abs(pt_row["solver_post_expected"] - sol_luck_mean) < 1e-9

    sec3_rows = _parse_section_table(report_text, "3. Per-Seed Trajectory and Regret Table")
    assert len(sec3_rows) == 9

    fleet_by_seed = {ep["seed"]: ep for ep in fleet_eps}
    g1_by_seed = {ep["seed"]: ep for ep in g1_eps}
    expected_sec3_order = [
        (30, "fleet", fleet_by_seed[30]),
        (34, "g1", g1_by_seed[34]),
        (34, "fleet", fleet_by_seed[34]),
        (37, "g1", g1_by_seed[37]),
        (42, "fleet", fleet_by_seed[42]),
        (45, "fleet", fleet_by_seed[45]),
        (48, "fleet", fleet_by_seed[48]),
        (57, "fleet", fleet_by_seed[57]),
        (58, "fleet", fleet_by_seed[58]),
    ]

    for cells, (seed, src_tag, ep) in zip(sec3_rows, expected_sec3_order):
        assert len(cells) == 16
        assert cells[0] == str(seed)
        assert ("G1" if src_tag == "g1" else "fleet") in cells[1]
        assert ep["correct"] is True
        assert cells[2] == f"`{ep['accused']}`"
        assert cells[3] == str(_ok_tool_count(ep, "plant_canary"))
        assert cells[4] == str(_ok_tool_count(ep, "interview"))
        assert cells[5] == str(_ok_tool_count(ep, "restrict_access"))
        assert cells[6] == f"d{ep['final_day']} (`{ep['accused']}`, ok)"

        ev = eval_map[(src_tag, seed)]
        p_acc = ev["audit"]["p_accused"]
        assert cells[7] == f"{ev['v']:.3f}"
        assert cells[8] == f"{p_acc:.3f}"
        assert cells[9] == f"`{ep['score']:+.3f}`"
        assert cells[10] == f"`{ev['luck']:+.3f}`"

        bw_count = ev["tag_counts"].get("budget_waste", 0)
        expected_tag_str = (
            f"`{ev['regret']:.3f}` (`none`)"
            if not ev["tag_counts"]
            else f"`{ev['regret']:.3f}` (`budget_waste` x{bw_count})"
        )
        assert cells[11] == expected_tag_str
        assert cells[12] == str(len(ep["steps"]))
        assert cells[13] == f"{ep['meta']['wall_s']:.1f}"

        sol = solver_by_seed[seed]
        sev = eval_map[("solver", seed)]
        sol_status = "ok" if sol["correct"] else "wrong"
        sol_can = _ok_tool_count(sol, "plant_canary")
        sol_p = sev["audit"]["p_accused"]
        expected_sol_cell = (
            f"d{sol['final_day']}, `{sol['accused']}` ({sol_status}), {sol_can} can, "
            f"`V={sev['v']:.3f}`, `P={sol_p:.3f}`, `{sol['score']:+.3f}`, "
            f"`{sev['luck']:+.3f}`, reg `{sev['regret']:.3f}`, {len(sol['steps'])} st"
        )
        assert cells[14] == expected_sol_cell

        raw_diff = ep["score"] - sol["score"]
        luck_diff = ev["luck"] - sev["luck"]
        assert cells[15] == f"`{raw_diff:+.3f}` / `{luck_diff:+.3f}`"

    accuse_fleet_rows = _parse_md_rows(EXT_ROOT / "accuse.md")
    assert len(accuse_fleet_rows) == 7
    for row_cells, ep in zip(accuse_fleet_rows, fleet_eps):
        ev = eval_map[("fleet", ep["seed"])]
        assert int(row_cells[2]) == ep["seed"]
        assert int(row_cells[3]) == ep["final_day"]
        assert row_cells[4] == ep["accused"]
        assert float(row_cells[7]) == ev["audit"]["p_accused"]

    accuse_ext8_rows = _parse_md_rows(EXT_ROOT / "accuse_ext8_combined.md")
    assert len(accuse_ext8_rows) == 8
    for row_cells, ep in zip(accuse_ext8_rows, dedup_ext8_eps):
        src_tag = "g1" if ep["seed"] in g1_seed_set else "fleet"
        ev = eval_map[(src_tag, ep["seed"])]
        assert int(row_cells[2]) == ep["seed"]
        assert int(row_cells[3]) == ep["final_day"]
        assert row_cells[4] == ep["accused"]
        assert float(row_cells[7]) == ev["audit"]["p_accused"]

    case_a_rows = _parse_section_table(report_text, "Case Study A: Seed 30")
    case_a_by_day = {r[0]: r for r in case_a_rows}
    ev_f30 = eval_map[("fleet", 30)]
    ev_s30 = eval_map[("solver", 30)]
    assert f"accuse `{fleet_by_seed[30]['accused']}`" in case_a_by_day["11"][2]
    assert f"{ev_f30['audit']['p_accused']:.3f}" in case_a_by_day["11"][2]
    assert case_a_by_day["11"][4] == f"{ev_f30['v']:.2f}"
    assert f"accuse `{solver_by_seed[30]['accused']}`" in case_a_by_day["18"][6]
    assert f"{ev_s30['audit']['p_accused']:.3f}" in case_a_by_day["18"][6]
    assert case_a_by_day["18"][8] == f"{ev_s30['v']:.2f}"

    case_b_rows = _parse_section_table(report_text, "Case Study B: Seed 34")
    case_b_by_day = {r[0]: r for r in case_b_rows}
    ev_g34 = eval_map[("g1", 34)]
    ev_f34 = eval_map[("fleet", 34)]
    ev_s34 = eval_map[("solver", 34)]
    assert f"{ev_g34['audit']['p_accused']:.3f}" in case_b_by_day["5"][2]
    assert f"V={ev_g34['v']:.2f}" in case_b_by_day["5"][2]
    assert f"{ev_s34['audit']['p_accused']:.3f}" in case_b_by_day["6"][6]
    assert f"V={ev_s34['v']:.2f}" in case_b_by_day["6"][6]
    assert f"{ev_f34['audit']['p_accused']:.3f}" in case_b_by_day["8"][4]
    assert f"V={ev_f34['v']:.2f}" in case_b_by_day["8"][4]

    assert round(ev_f34["accuse_regret"], 4) == 0.5750
    assert round(ev_f34["regret"], 4) == 0.5903
    assert round(ev_g34["accuse_regret"], 4) == 0.0177
    assert round(ev_g34["regret"], 4) == 0.0365
    fleet34_share = f"{ev_f34['accuse_regret'] / fleet_tags_json['regret_total'] * 100:.1f}%"
    assert fleet34_share == "49.4%"
    for expected_snippet in ("0.5750", "0.5903", "49.4%", "0.0177", "0.0365"):
        assert expected_snippet in report_text
