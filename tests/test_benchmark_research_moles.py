from __future__ import annotations

import copy
import importlib.util
import io
import json
import re
import sys
import tokenize
from pathlib import Path

import pytest

from canary.mole.dsl import MoleStrategy

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts" / "benchmark_research_moles.py"
LIBRARY_PATH = ROOT / "data" / "forge" / "research_sleeper_moles_v14.json"
MONOGRAPH_PATH = ROOT / "docs" / "research" / "14_sleeper_mole_catalog_and_head_to_head.md"
SELF_PATH = Path(__file__).resolve()

H = chr(35)
EM = "\u2014"
EN = "\u2013"
EXPECTED_HASH = "a8f99c2537c91d72"
EXPECTED_IDS = (
    "sleeper_stackelberg_v14",
    "sleeper_override_cover_v16",
    "reciprocity_retaliator_v14",
    "mixed_trap_dodger_v14",
)
EXPECTED_INVESTIGATORS = (
    "grok_tactics",
    "hinted_heuristic",
    "heuristic",
    "interview_crowded_qre",
)


def _load_benchmark_module():
    spec = importlib.util.spec_from_file_location("benchmark_research_moles", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


B = _load_benchmark_module()


def test_verify_recorded_library_smoke_and_cli(capsys):
    raw_size = len(LIBRARY_PATH.read_bytes())
    assert raw_size < 15000

    lib = B.load_library(LIBRARY_PATH)
    assert lib["tiers_version"] == "v1.4"
    assert lib["tiers_v14_hash"] == EXPECTED_HASH
    assert B.compute_v14_hash() == EXPECTED_HASH

    rc = B.main(["--library", str(LIBRARY_PATH), "--verify-recorded"])
    out = capsys.readouterr().out
    payload = json.loads(out)
    assert rc == 0
    assert payload["ok"] is True
    assert payload["bytes"] == raw_size
    assert payload["bytes"] < 15000
    assert tuple(payload["strategies"]) == EXPECTED_IDS
    assert payload["elapsed_s"] < 9.0


def test_all_four_strategies_roundtrip_and_pass_catchability():
    lib = B.load_library(LIBRARY_PATH)
    splits = lib["splits"]
    assert splits["dev"] == {"seed_range": "2000-2059", "n_seeds": 60}
    assert splits["heldout"] == {"seed_range": "2100-2159", "n_seeds": 60}
    dev_seeds = B.parse_seed_slice(splits["dev"]["seed_range"])
    held_seeds = B.parse_seed_slice(splits["heldout"]["seed_range"])
    assert dev_seeds == list(range(2000, 2060))
    assert held_seeds == list(range(2100, 2160))
    assert not (set(dev_seeds) & set(held_seeds))

    base_bench = lib["baseline_default_v0"]["benchmark_v14_hard"]
    base_strat = MoleStrategy.from_json(lib["baseline_default_v0"]["strategy_json"])
    assert MoleStrategy.from_json(base_strat.to_json()) == base_strat

    entries = lib["strategies"]
    assert tuple(e["id"] for e in entries) == EXPECTED_IDS

    for entry in entries:
        sj = entry["strategy_json"]
        strat = MoleStrategy.from_json(sj)
        assert strat.name == entry["id"]
        assert MoleStrategy.from_json(strat.to_json()) == strat
        assert B.load_mole_strategy(sj) == strat

        bench = entry["benchmark_v14_hard"]
        for split_key in ("dev", "heldout"):
            sp = bench[split_key]
            b_sp = base_bench[split_key]
            assert sp["n_seeds"] == 60
            assert sp["feasible"] is True
            assert sp["solver_acc"][0] >= 0.85
            assert sp["solver_acc"][1] <= sp["solver_acc"][0] <= sp["solver_acc"][2] <= 1.0
            assert sp["solver_score"][0] >= 0.5 * b_sp["solver_score"][0]
            assert sp["solver_score"][1] <= sp["solver_score"][0] <= sp["solver_score"][2]

            per_inv = sp["per_investigator"]
            assert tuple(per_inv.keys()) == EXPECTED_INVESTIGATORS
            for ag in EXPECTED_INVESTIGATORS:
                inv_sc = per_inv[ag]["score"][0]
                inv_reg = per_inv[ag]["regret"][0]
                assert abs((sp["solver_score"][0] - inv_sc) - inv_reg) <= 5e-4
            expected_min_reg = round(min(per_inv[ag]["regret"][0] for ag in EXPECTED_INVESTIGATORS), 4)
            assert sp["min_regret"] == expected_min_reg


def test_tamper_guards_reject_invalid_libraries(tmp_path):
    lib = B.load_library(LIBRARY_PATH)

    oversized = tmp_path / "oversized.json"
    oversized.write_text(json.dumps(lib, indent=4) + (" " * 16000), encoding="utf-8")
    with pytest.raises(ValueError, match="15 KB"):
        B.verify_recorded_library(oversized, run_smoke=False)

    bad_hash_lib = copy.deepcopy(lib)
    bad_hash_lib["tiers_v14_hash"] = "0000000000000000"
    bad_hash_p = tmp_path / "bad_hash.json"
    B.write_compact_library(bad_hash_lib, bad_hash_p)
    with pytest.raises(ValueError, match="hash mismatch"):
        B.verify_recorded_library(bad_hash_p, run_smoke=False)

    low_acc_lib = copy.deepcopy(lib)
    low_acc_lib["strategies"][2]["benchmark_v14_hard"]["heldout"]["solver_acc"] = [0.80, 0.70, 0.90]
    low_acc_p = tmp_path / "low_acc.json"
    B.write_compact_library(low_acc_lib, low_acc_p)
    with pytest.raises(ValueError, match="solver_acc"):
        B.verify_recorded_library(low_acc_p, run_smoke=False)

    overlap_lib = copy.deepcopy(lib)
    overlap_lib["splits"]["heldout"]["seed_range"] = "2050-2109"
    overlap_p = tmp_path / "overlap.json"
    B.write_compact_library(overlap_lib, overlap_p)
    with pytest.raises(ValueError, match="disjoint"):
        B.verify_recorded_library(overlap_p, run_smoke=False)


def test_hof_export_markdown_and_monograph_14_parity():
    lib = B.load_library(LIBRARY_PATH)
    hof_jsonl = B.export_forge_hof_jsonl(lib, split="heldout")
    rows = [json.loads(line) for line in hof_jsonl.splitlines() if line.strip()]
    assert len(rows) == 4
    for idx, (row, entry) in enumerate(zip(rows, lib["strategies"]), start=1):
        assert row["rank"] == idx
        assert row["id"] == entry["id"]
        assert row["fitness"] == entry["benchmark_v14_hard"]["heldout"]["min_regret"]
        assert row["solver_acc"] >= 0.85
        assert MoleStrategy.from_json(row["strategy_json"]).name == entry["id"]

    md_table = B.format_markdown_summary(lib)
    assert "Dev (2000-2059, n=60)" in md_table
    assert "Held-Out (2100-2159, n=60)" in md_table
    for sid in ("default_v0",) + EXPECTED_IDS:
        assert f"`{sid}`" in md_table

    assert MONOGRAPH_PATH.is_file()
    doc_text = MONOGRAPH_PATH.read_text(encoding="utf-8")
    line_count = len(doc_text.splitlines())
    assert 220 <= line_count <= 310
    assert "P14.1" in doc_text
    assert "P14.2" in doc_text
    assert EXPECTED_HASH in doc_text
    for sid in EXPECTED_IDS:
        assert sid in doc_text
    for ag in ("SolverPolicy",) + EXPECTED_INVESTIGATORS:
        assert ag in doc_text

    for entry in lib["strategies"]:
        for split_key in ("dev", "heldout"):
            sp = entry["benchmark_v14_hard"][split_key]
            assert f"{sp['solver_score'][0]:.4f}" in doc_text
            assert f"{sp['min_regret']:+.4f}" in doc_text

    json_blocks = re.findall(r"```json\n(.*?)\n```", doc_text, flags=re.DOTALL)
    by_name = {json.loads(blk)["name"]: json.loads(blk) for blk in json_blocks}
    lib_by_id = {e["id"]: e["strategy_json"] for e in lib["strategies"]}
    for target_id in ("reciprocity_retaliator_v14", "mixed_trap_dodger_v14"):
        assert target_id in by_name
        assert MoleStrategy.from_json(by_name[target_id]) == MoleStrategy.from_json(lib_by_id[target_id])

    lit_sec = doc_text.split(f"\n{H}{H} 2. Primary Literature Grounding", 1)[1].split(f"\n{H}{H} 3. ", 1)[0]
    lit_subs = re.split(rf"(?m)^{H}{{3}}\s+2\.\d+\s+", lit_sec)[1:]
    assert len(lit_subs) == 10
    allowed_pids = {"P14.1", "P14.2", "P5.1", "P8.1", "P8.2", "P8.3"}
    for sub in lit_subs:
        assert re.search(r"https?://\S+", sub), f"missing URL in literature subsection: {sub.splitlines()[0]}"
        quotes = [ln.lstrip()[1:].strip() for ln in sub.splitlines() if ln.lstrip().startswith(">")]
        assert any(len(q) >= 20 for q in quotes), f"missing verbatim quote in subsection: {sub.splitlines()[0]}"
        found_pids = set(re.findall(r"\bP\d+\.\d+\b", sub))
        assert found_pids & allowed_pids, f"missing required proposal ID in subsection: {sub.splitlines()[0]}"


def test_zero_comments_zero_dashes_and_pure_ascii():
    raw_lib = LIBRARY_PATH.read_text(encoding="utf-8")
    assert len(raw_lib.encode("utf-8")) < 50000
    assert not re.findall(r"\be\d{2}\b", raw_lib)
    assert not re.findall(r'"(?:mole|true_mole)"', raw_lib)

    prereg_rx = re.compile(r"pre-regist\w*[^.\n]{0,40}\b0\s*-\s*29\b|\b0\s*-\s*29\b[^.\n]{0,40}pre-regist", re.I)
    tiebreak_rx = re.compile(r"tiebreak\w*[^.\n]{0,40}beats?\s+(?:the\s+)?base", re.I)
    coauth_rx = re.compile(r"(?im)^\s*Co-Authored-By\s*:")

    for path in (SCRIPT_PATH, SELF_PATH, LIBRARY_PATH, MONOGRAPH_PATH):
        src = path.read_text(encoding="utf-8")
        assert EM not in src, f"em-dash found in {path}"
        assert EN not in src, f"en-dash found in {path}"
        assert src.isascii(), f"non-ASCII char found in {path}"
        assert not prereg_rx.search(src), f"Panel Fix A seed 0-29 claim violation in {path}"
        assert not tiebreak_rx.search(src), f"Panel Fix A tiebreak claim violation in {path}"
        assert not coauth_rx.search(src), f"Co-Authored-By found in {path}"

    for py_path in (SCRIPT_PATH, SELF_PATH):
        src = py_path.read_text(encoding="utf-8")
        assert H not in src, f"raw hash char found in {py_path}"
        tokens = list(tokenize.generate_tokens(io.StringIO(src).readline))
        comment_tokens = [tok for tok in tokens if tok.type == tokenize.COMMENT]
        assert not comment_tokens, f"Python comment found in {py_path}: {comment_tokens}"
