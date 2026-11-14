from __future__ import annotations

import ast
import importlib.util
import io
import json
import time
import tokenize
from pathlib import Path

import pytest

from canary.forge.mutate import default_strategy_json

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts" / "eval_forge_holdout.py"


def load_holdout_module():
    spec = importlib.util.spec_from_file_location("eval_forge_holdout", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def sample_hof_rows() -> list[dict]:
    s1 = {
        "default": {"frame": "decoy", "leak": "random_seeded"},
        "rules": [
            {"if": [["n_restricted_colleagues", ">=", 1]], "then": {"frame": "most_restricted_peer", "leak": "oldest"}},
            {"if": [["day", "<=", 4]], "then": {"frame": "decoy", "leak": "most_recipients"}},
        ],
    }
    s2 = {
        "default": {"frame": "random_peer", "leak": "random_seeded"},
        "rules": [
            {"if": [["recent_low_recipient_docs", ">=", 1]], "then": {"frame": "decoy", "leak": "oldest"}},
        ],
    }
    s3 = {
        "default": {"frame": "decoy", "leak": "oldest"},
        "rules": [
            {"if": [["days_since_last_leak", ">=", 2]], "then": {"frame": "random_peer", "leak": "random_seeded"}},
        ],
    }
    s4 = {
        "default": {"frame": "none", "leak": "newest"},
        "rules": [
            {"if": [["day", ">=", 3]], "then": {"frame": "decoy", "leak": "random_seeded"}},
        ],
    }
    return [
        {"rank": 1, "fitness": 0.42, "solver_score": 0.55, "solver_acc": 0.95, "strategy_json": s1},
        {"rank": 2, "fitness": 0.39, "solver_score": 0.57, "solver_acc": 0.95, "strategy_json": default_strategy_json()},
        {"rank": 3, "fitness": 0.39, "solver_score": 0.55, "solver_acc": 0.95, "strategy_json": s1},
        {"rank": 4, "fitness": 0.35, "solver_score": 0.52, "solver_acc": 0.90, "strategy_json": s2},
        {"rank": 5, "fitness": 0.31, "solver_score": 0.50, "solver_acc": 0.85, "strategy_json": s3},
        {"rank": 6, "fitness": 0.28, "solver_score": 0.49, "solver_acc": 0.85, "strategy_json": s4},
    ]


def test_select_top_unique_strategies_deduplicates_and_skips_default(tmp_path):
    mod = load_holdout_module()
    hof_file = tmp_path / "hall_of_fame.jsonl"
    hof_file.write_text("".join(json.dumps(r) + "\n" for r in sample_hof_rows()), encoding="utf-8")

    selected = mod.select_top_unique_strategies(hof_file, top_k=3)
    assert [x["hof_rank"] for x in selected] == [1, 4, 5]
    assert [x["label"] for x in selected] == ["HoF#1", "HoF#4", "HoF#5"]


def test_eval_forge_holdout_fake_end_to_end_keyless(tmp_path, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_GENERATIVE_AI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_GATEWAY_URL", raising=False)

    mod = load_holdout_module()
    run_dir = tmp_path / "mole-forge-carbon-hard-deep"
    run_dir.mkdir(parents=True)

    orig_meta = {
        "role": "adaptive_mole",
        "subrole": "mole_forge",
        "model_id": "gemini-4-carbon",
        "commit": "abcdef123456",
        "default_dev_fitness": 0.24,
    }
    meta_bytes = (json.dumps(orig_meta, indent=2) + "\n").encode("utf-8")
    (run_dir / "meta.json").write_bytes(meta_bytes)
    (run_dir / "hall_of_fame.jsonl").write_text(
        "".join(json.dumps(r) + "\n" for r in sample_hof_rows()),
        encoding="utf-8",
    )

    t0 = time.perf_counter()
    rc = mod.main(
        [
            "--run-dir",
            str(run_dir),
            "--top-k",
            "3",
            "--tier",
            "hard",
            "--unseen-seeds",
            "20-22",
            "--confirm-seeds",
            "5020-5023",
            "--workers",
            "1",
            "--fake",
        ]
    )
    elapsed = time.perf_counter() - t0
    assert rc == 0
    assert elapsed < 3.0

    meta_files = list(run_dir.rglob("meta.json"))
    assert meta_files == [run_dir / "meta.json"]
    assert (run_dir / "meta.json").read_bytes() == meta_bytes

    json_path = run_dir / "holdout_generalization.json"
    md_path = run_dir / "holdout_summary.md"
    assert json_path.is_file()
    assert md_path.is_file()

    doc = json.loads(json_path.read_text(encoding="utf-8"))
    assert doc["source_model_id"] == "gemini-4-carbon"
    assert doc["source_commit"] == "abcdef123456"
    assert doc["tier"] == "hard"
    assert doc["splits"]["unseen_seeds"] == [20, 21, 22]
    assert doc["splits"]["confirm_seeds"] == [5020, 5021, 5022, 5023]
    assert doc["splits"]["combined_seeds"] == [20, 21, 22, 5020, 5021, 5022, 5023]
    assert len(doc["evolved_strategies"]) == 3
    assert [e["hof_rank"] for e in doc["evolved_strategies"]] == [1, 4, 5]

    expected_invs = {"grok_tactics", "heuristic", "hinted_heuristic", "obvious_heuristic"}
    for entry in [doc["default_mole"], *doc["evolved_strategies"]]:
        for split in ("unseen", "confirm", "combined"):
            ev = entry[split]
            assert set(ev["per_investigator"]) == expected_invs
            for inv_metrics in ev["per_investigator"].values():
                assert inv_metrics["regret"] == pytest.approx(ev["solver_score"] - inv_metrics["score"], abs=1e-9)
        u_sc = entry["unseen"]["solver_score"]
        c_sc = entry["confirm"]["solver_score"]
        assert entry["combined"]["solver_score"] == pytest.approx((3 * u_sc + 4 * c_sc) / 7.0, abs=1e-9)

    md_txt = md_path.read_text(encoding="utf-8")
    for label in ("DefaultMole", "HoF#1", "HoF#4", "HoF#5", "SolverPolicy", "GrokTactics", "Heuristic", "HintedHeuristic", "ObviousHeuristic"):
        assert label in md_txt

    em_dash = chr(0x2014)
    en_dash = chr(0x2013)
    for txt in (json_path.read_text(encoding="utf-8"), md_txt):
        assert em_dash not in txt and en_dash not in txt


def test_eval_forge_holdout_real_env_single_seed_keyless(tmp_path, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_GENERATIVE_AI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_GATEWAY_URL", raising=False)

    mod = load_holdout_module()
    run_dir = tmp_path / "real_mini"
    run_dir.mkdir(parents=True)
    (run_dir / "hall_of_fame.jsonl").write_text(
        json.dumps(sample_hof_rows()[0]) + "\n",
        encoding="utf-8",
    )

    rc = mod.main(
        [
            "--run-dir",
            str(run_dir),
            "--top-k",
            "1",
            "--tier",
            "hard",
            "--unseen-seeds",
            "20",
            "--confirm-seeds",
            "5020",
            "--workers",
            "2",
        ]
    )
    assert rc == 0
    doc = json.loads((run_dir / "holdout_generalization.json").read_text(encoding="utf-8"))
    assert doc["fake_env"] is False
    assert doc["summary"]["n_evolved_evaluated"] == 1
    assert 0.0 <= doc["evolved_strategies"][0]["combined"]["solver_acc"] <= 1.0


def test_no_comments_docstrings_or_em_dashes_in_holdout_files():
    em_dash = chr(0x2014)
    en_dash = chr(0x2013)
    for path in (SCRIPT_PATH, Path(__file__).resolve()):
        src = path.read_text(encoding="utf-8")
        assert em_dash not in src and en_dash not in src
        tokens = list(tokenize.generate_tokens(io.StringIO(src).readline))
        assert [t for t in tokens if t.type == tokenize.COMMENT] == []
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                assert ast.get_docstring(node) is None
