"""B2: the thinking sweep in results/gemini/ablations.{json,md} recomputes from the committed canonical ladder.json."""
import json
from pathlib import Path

from canary.gemini import ablations

RES = Path(__file__).resolve().parents[1] / "results" / "gemini"


def _r(lo, hi):
    return {"ci_direction": "below" if hi < 1 else "above" if lo > 1 else None}


def test_parity_sentence_states_direction():
    assert ablations.parity_sentence([_r(.1, .5), _r(.2, .9), _r(.5, 1.5)]) == \
        "2 of 3 cells exclude parity, all below the solver"
    assert ablations.parity_sentence([_r(.1, .5), _r(1.1, 1.5)]) == \
        "2 of 2 cells exclude parity, 1 below and 1 above the solver"
    assert ablations.parity_sentence([_r(.5, 1.5)]) == "0 of 1 cells exclude parity, none differ from the solver"


def test_argon_clause_reads_direction_from_data():
    def h(p, lo, hi):
        return {"pct_of_solver": p, "ci95": [lo, hi]}
    cell = lambda m, lv: lv  # noqa: E731
    up = {("gemini-4-argon", "low"): h(57, -6, 127), ("gemini-4-argon", "high"): h(73, 14, 117)}
    assert ablations.argon_clause(up, cell).startswith("gemini-4-argon rises") and "CIs overlap" in ablations.argon_clause(up, cell)
    zig = {("gemini-4-argon", "low"): h(102, 83, 130), ("gemini-4-argon", "medium"): h(41, -35, 108),
           ("gemini-4-argon", "high"): h(45, -34, 99)}
    assert "is non-monotone" in ablations.argon_clause(zig, cell)


def test_committed_sweep_recomputes_from_committed_ladder_json():
    a = json.loads((RES / "ablations.json").read_text())
    fresh = ablations.sweep(RES / "ladder.json")
    assert a["thinking_sweep"] == fresh
    assert a["thinking_sweep_parity"] == ablations.parity_sentence(fresh)
    md = (RES / "ablations.md").read_text()
    sec3 = md.split("## 3. Thinking-level sweep")[1].split("## §4")[0]
    assert ablations.parity_sentence(fresh) in sec3 and f"{len(fresh)} model x thinking-level x tier cells" in sec3
    for r in fresh:  # every table number comes from ladder.json
        cell = f"{r['pct_of_solver']}% [{r['ci95'][0]}, {r['ci95'][1]}]"
        cell = f"**{cell}**" if r["ci_excludes_100"] else cell
        assert f"| {r['tier']} | {r['model']} | {r['level']} | {r['n']} | {cell} |" in sec3
    assert ablations.parity_sentence(fresh) in a["section4"][2]


def test_cost_falls_back_to_extra_prices_for_flash_models():
    r = {"model": "gemini-3.5-flash", "in": 1_000_000, "cached": 400_000, "out": 100_000, "thinking": 0}
    paid, cf, ok = ablations._row_cost(r)
    assert ok and abs(paid - (0.6 * 0.75 + 0.4 * 0.075 + 0.1 * 3.75)) < 1e-9 and abs(cf - (0.75 + 0.375)) < 1e-9
    lite = {"model": "gemini-3.1-flash-lite", "in": 1_000_000, "cached": 0, "out": 0, "thinking": 0}
    assert ablations._row_cost(lite) == (0.25, 0.25, True)
    assert ablations._row_cost({"model": "gemini-embedding-2", "in": 10, "out": 0})[2] is False


def test_committed_cache_section_recomputes_from_committed_ledgers():
    a = json.loads((RES / "ablations.json").read_text())
    assert a["explicit_cache"] == json.loads(json.dumps(ablations.cache_ablation(ablations._union_ledger_rows())))
    md = (RES / "ablations.md").read_text()
    pg = a["explicit_cache"]["programme"]
    assert f"{pg['calls']:,} ledgered calls" in md and f"${pg['usd_if_uncached']:.2f}" in md
    assert a["explicit_cache"]["programme"]["unpriced_calls"] == sum(a["explicit_cache"]["unpriced_by_model"].values())


def test_cache_only_leaves_signatures_and_sweep_untouched():
    before = json.loads((RES / "ablations.json").read_text())
    a = ablations.regenerate_cache(RES / "ablations.json")
    assert a["thought_signatures"] == before["thought_signatures"] and a["thinking_sweep"] == before["thinking_sweep"]
    assert a["section4"][0] == before["section4"][0] and a["section4"][2] == before["section4"][2]


def test_sweep_only_leaves_signature_and_cache_sections_untouched(tmp_path):
    before = json.loads((RES / "ablations.json").read_text())
    a = ablations.regenerate_sweep(RES / "ladder.json", RES / "ablations.json")
    assert a["thought_signatures"] == before["thought_signatures"]
    assert a["explicit_cache"] == before["explicit_cache"]
    assert a["section4"][:2] == before["section4"][:2]
