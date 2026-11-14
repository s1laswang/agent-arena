"""FR8 analysis modules on synthetic data (no real numbers)."""
import csv
import json
import math
import random

from fr8.analysis import ci_sizing, difficulty_sweep, forge_report, j1_recommend
from fr8.analysis._common import read_rows


def _calib(path, sd=0.1, gap=0.2, n=40):
    rng = random.Random(1)
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["tier", "n_employees", "p_leak", "agent", "seed", "score", "correct", "final_day"])
        for tier, ne in (("easy", 12), ("hard", 30)):
            for pl in (0.6, 0.9):
                for s in range(n):
                    base = rng.gauss(0.5, 0.2)
                    g = gap if pl == 0.9 else gap / 2
                    w.writerow([tier, ne, pl, "solver", s, base + g + rng.gauss(0, sd), 1, 5])
                    w.writerow([tier, ne, pl, "obvious_heuristic", s, base, int(rng.random() < .5), 8])
                    w.writerow([tier, ne, pl, "random", s, 0.0, int(rng.random() < 1 / ne), 2])
                    w.writerow([tier, ne, pl, "stop_early", s, -1.0 if s % 2 else 0.0, 0, 1])
    return path


def test_ci_sizing_paired_beats_unpaired(tmp_path):
    cells = ci_sizing.size_cells(read_rows(_calib(tmp_path / "c.csv")))
    assert len(cells) == 4
    for c in cells:
        assert c["n_seeds"] == 40
        assert c["sd_paired"] < math.sqrt(c["sd_solver"] ** 2 + c["sd_heur"] ** 2)
        assert c["n_paired"] <= c["n_unpaired"]
        assert c["n_bootstrap"] >= c["n_paired"] * 0.8
    assert "| tier |" in ci_sizing.to_markdown(cells)


def test_n_needed_formula():
    # half-width Z*sd/sqrt(n) < gap/3  ->  sd=0.1, gap=0.3: n >= (1.96*0.1/0.1)^2 = 3.84
    assert ci_sizing.n_needed(0.1, 0.3) == 4
    assert ci_sizing.n_needed(0.1, 0.0) == float("inf")


def test_j1_recommend_picks_bigger_gap(tmp_path):
    rows = read_rows(_calib(tmp_path / "c.csv"))
    for r in list(rows):
        if r["agent"] == "solver":
            r["correct"] = True
            if r["tier"] == "hard":
                rows.append({**r, "agent": "logs_only", "score": 0.0, "correct": False})
    rec = j1_recommend.recommend(rows)
    assert "p_leak=0.9" in rec["easy"]["params"]
    assert "p_leak=0.9" in rec["hard"]["params"]
    assert rec["easy"]["stop_early_mean"] < 0 and rec["easy"]["feasible"]
    assert "Recommend" in j1_recommend.to_markdown(rows, ["x"])


def test_j1_reports_binding_constraint(tmp_path):
    rows = [r for r in read_rows(_calib(tmp_path / "c.csv")) if r["agent"] != "stop_early"]
    rows += [{**r, "agent": "stop_early", "score": 0.0} for r in rows if r["agent"] == "random"]
    assert all(c is None for c in j1_recommend.recommend(rows).values())
    md = j1_recommend.to_markdown(rows, ["x"])
    assert "No feasible cell" in md and "stop_early>=0" in md


def test_sweep_aggregate_and_cli_params(capsys):
    rows = [{"noise": x, "tier": "easy", "agent": a, "seed": s, "score": 1 - x if a == "solver" else .5 - x / 2,
             "correct": 1} for x in (0.0, 0.5) for a in ("solver", "heuristic") for s in range(5)]
    summ = difficulty_sweep.aggregate(rows)
    assert len(summ) == 4 and all(r["n"] == 5 for r in summ)
    difficulty_sweep.main(["params", "--tiers", "easy,hard", "--grid", "0:0.2:0.1", "--seeds", "0:5"])
    assert len(capsys.readouterr().out.strip().splitlines()) == 6
    assert difficulty_sweep.parse_seeds("3:7") == [3, 4, 5, 6]


def test_forge_report(tmp_path):
    (tmp_path / "log.jsonl").write_text("\n".join(json.dumps(
        {"gen": g, "best_fitness": .1 * g, "mean_fitness": .05 * g, "solver_ratio": .8, "solver_acc": .9})
        for g in range(5)))
    strat = {"rules": [{"if": [["days_since_last_leak", ">", 2]], "then": {"leak": "oldest", "frame": "decoy"}}]}
    (tmp_path / "hall_of_fame.jsonl").write_text(
        json.dumps({"fitness": .4, "strategy": strat}) + "\n" + json.dumps({"fitness": .2, "strategy": {}}))
    md = forge_report.report(tmp_path, top=2)
    assert "generations: 5" in md and "violation: none" in md
    assert md.index("0.4") < md.index("0.2") and "leak=oldest" in md


def test_j1_fp_curve():
    rows = []
    for fp in (1.0, 0.9, 0.8):
        for s in range(10):
            rows.append({"tier": "hard", FPK: str(fp), "agent": "solver", "seed": s,
                         "score": .5, "correct": fp >= 0.9 or s < 5})
            rows.append({"tier": "hard", FPK: str(fp), "agent": "heuristic", "seed": s,
                         "score": .1, "correct": s < 2})
    pts = j1_recommend.fp_curve(rows)["hard"]
    assert [p["fp"] for p in pts] == [1.0, 0.9, 0.8]
    assert j1_recommend.lowest_fp(pts) == 0.9
    assert "lowest fingerprint_accuracy" in "\n".join(j1_recommend.fp_markdown(rows))


FPK = "fingerprint_accuracy"


def _cell_rows(tier, cell, solver_score, none_every=0, n=20):
    rows = []
    for s in range(n):
        acc = "" if none_every and s % none_every == 0 else "e01"
        rows.append({"tier": tier, "p": str(cell), "agent": "solver", "seed": s, "score": solver_score,
                     "correct": acc != "", "accused": acc})
        rows.append({"tier": tier, "p": str(cell), "agent": "heuristic", "seed": s, "score": 0.0,
                     "correct": False, "accused": "e02"})
        rows.append({"tier": tier, "p": str(cell), "agent": "stop_early", "seed": s, "score": -1.0,
                     "correct": False, "accused": "e03"})
        rows.append({"tier": tier, "p": str(cell), "agent": "logs_only", "seed": s, "score": 0.0,
                     "correct": False, "accused": "e04"})
    return rows


def test_j1_solver_none_rate():
    rows = _cell_rows("easy", 0, 0.8, none_every=10)  # 10% no-accusation -> infeasible
    rows += _cell_rows("easy", 1, 0.8)
    cells = {c["params"]: c for c in j1_recommend.evaluate(rows)}
    assert cells["p=0"]["solver_none_rate"] == 0.1 and "solver_none>0.05" in cells["p=0"]["violations"]
    assert cells["p=1"]["feasible"] and cells["p=1"]["none_rate[heuristic]"] == 0.0


def test_j1_joint_ordering():
    # independent best per tier would be hard=0.9 > medium=0.7; the joint pick must respect the order
    rows = _cell_rows("easy", 0, 0.8) + _cell_rows("medium", 1, 0.7) + _cell_rows("medium", 2, 0.5)
    rows += _cell_rows("hard", 3, 0.9) + _cell_rows("hard", 4, 0.4)
    picks, held = j1_recommend.recommend_joint(rows)
    assert held
    assert [picks[t]["params"] for t in ("easy", "medium", "hard")] == ["p=0", "p=1", "p=4"]
    bad = _cell_rows("easy", 0, 0.3) + _cell_rows("medium", 1, 0.7)
    _, held2 = j1_recommend.recommend_joint(bad)
    assert not held2 and "Ordering cannot hold" in j1_recommend.to_markdown(bad, ["x"])
