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
                    w.writerow([tier, ne, pl, "heuristic", s, base, int(rng.random() < .5), 8])
                    w.writerow([tier, ne, pl, "random", s, 0.0, int(rng.random() < 1 / ne), 2])
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
    rec = j1_recommend.recommend(read_rows(_calib(tmp_path / "c.csv")), rand_tol=0.2)
    assert "p_leak=0.9" in rec["easy"]["params"]
    assert "p_leak=0.9" in rec["hard"]["params"]


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
