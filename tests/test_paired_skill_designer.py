from __future__ import annotations

import io
import json
from pathlib import Path
import re
import tokenize

import pytest

from canary import rules
from canary.env import Env
from canary.gemini.provenance import audit_provenance, scan_file_secrets
from canary.llm.stub import StubClient
from canary.solver.policy import SolverPolicy
from scripts import run_paired_skill_designer as psd
from scripts import skill_ladder

ROOT = Path(__file__).resolve().parents[1]
COMMITTED_DIR = ROOT / "results" / "gemini_roles" / "adaptive_mole" / "paired-solvable-scenarios-carbon"
EM_DASH = chr(0x2014)
EN_DASH = chr(0x2013)


def test_candidate_tier_context_applies_knobs_and_restores() -> None:
    orig_med = rules.TIERS["medium"]
    cand = {
        "name": "test-cand",
        "knobs": {"p_leak": 0.88, "leak_damage": 0.05, "careful_mole": False},
        "mole_strategy": {"rules": [{"if": [], "then": {"leak": "newest", "frame": None}}]},
    }
    with pytest.raises(RuntimeError):
        with psd.candidate_tier_context("medium", cand):
            env = Env("medium", 5, mole_strategy=cand["mole_strategy"])
            assert env.p.p_leak == pytest.approx(0.88)
            assert env.p.leak_damage == pytest.approx(0.05)
            assert env.p.careful_mole is False
            sp = SolverPolicy()
            sp.reset(env.tools_spec(), env.instruction())
            assert sp.P is not None
            assert sp.P.p_leak == pytest.approx(0.88)
            assert sp.P.careful_mole is False
            raise RuntimeError("boom")
    assert rules.TIERS["medium"] == orig_med


def test_end_to_end_stub_cli_is_keyless_and_writes_all_outputs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "")
    monkeypatch.setenv("GOOGLE_GENERATIVE_AI_API_KEY", "")
    monkeypatch.setenv("CANARY_GEMINI_LEDGER", str(tmp_path / "ledger.jsonl"))

    out_dir = tmp_path / "stub_out"
    rc = psd.main([
        "--llm",
        "stub",
        "--tier",
        "medium",
        "--design-seeds",
        "5,6",
        "--eval-seeds",
        "5100..5102",
        "--n-proposals",
        "4",
        "--out-dir",
        str(out_dir),
    ])
    assert rc == 0

    for fname in ("meta.json", "design_report.json", "skill_gap.json", "summary.md"):
        fpath = out_dir / fname
        assert fpath.is_file(), fname
        txt = fpath.read_text(encoding="utf-8")
        assert EM_DASH not in txt
        assert EN_DASH not in txt
        assert scan_file_secrets(fpath, tmp_path) == []

    meta = json.loads((out_dir / "meta.json").read_text(encoding="utf-8"))
    design_doc = json.loads((out_dir / "design_report.json").read_text(encoding="utf-8"))
    gap_doc = json.loads((out_dir / "skill_gap.json").read_text(encoding="utf-8"))

    assert meta["role"] == "adaptive_mole"
    assert meta["subrole"] == "paired_skill_designer"
    assert meta["model_id"] == "stub"
    assert meta["stub"] is True
    assert meta["tiers_version"] == "v1.4"
    assert meta["llm_ok"] is True
    assert meta["n_llm_valid"] == 4
    assert meta["n_kept"] >= 1
    assert meta["n_episodes"] == 3

    unsolvable = [r for r in design_doc["rows"] if r["name"] == "deep-sleep-unsolvable"]
    assert len(unsolvable) == 1
    assert unsolvable[0]["keep"] is False
    assert unsolvable[0]["agent"] is None
    assert unsolvable[0]["regret"] is None

    sel = design_doc["selected_top_scenario"]
    assert sel["keep"] is True
    assert sel["origin"] == "llm"
    assert sel["solver"] >= 0.50
    assert sel["agent"] <= 0.20

    rungs_seen = tuple(r["rung"] for r in gap_doc["designed_rows"])
    assert rungs_seen == skill_ladder.RUNG_ORDER
    for hr in ("full_solver", "no_ev_commit", "binary_canary_only", "heuristic_bisection", "do_nothing"):
        assert hr in gap_doc["headline_comparison"]

    by_rung = {r["rung"]: r for r in gap_doc["designed_rows"]}
    assert by_rung["do_nothing"]["mean_score"] == 0.0
    assert by_rung["do_nothing"]["accused_rate"] == 0.0
    assert by_rung["full_solver"]["mean_score"] > by_rung["heuristic_bisection"]["mean_score"]


def test_multi_round_history_recovers_after_unsolvable_first_round(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CANARY_GEMINI_LEDGER", str(tmp_path / "ledger.jsonl"))
    round1 = {
        "candidates": [
            {
                "name": "silent-round1",
                "rationale": f"Em dash test {EM_DASH} blocks leaks.",
                "rules": [
                    {"conditions": [{"feature": "days_since_last_leak", "op": "<", "value": 6}], "then": {"leak": "none", "frame": "decoy"}},
                    {"conditions": [], "then": {"leak": "newest", "frame": "decoy"}},
                ],
                "knobs": {"p_leak": 0.65, "careful_mole": True},
            }
        ]
    }
    round2 = {
        "candidates": [
            {
                "name": "solvable-round2",
                "rationale": "Steady seeded leak with decoy framing.",
                "rules": [
                    {"conditions": [], "then": {"leak": "random_seeded", "frame": "decoy"}},
                ],
                "knobs": {"p_leak": 0.85, "decoy": True, "framing": True, "careful_mole": False},
            }
        ]
    }
    stub = StubClient(script=[{"json": round1}, {"json": round2}])
    out_dir = tmp_path / "two_rounds"
    bundle = psd.run_paired_skill_designer(
        llm_spec="stub:custom",
        tier="medium",
        design_seeds=[5, 6],
        eval_seeds=[5100, 5101],
        n_proposals=1,
        max_rounds=2,
        out_dir=out_dir,
        rungs=("full_solver", "heuristic_bisection", "do_nothing"),
        client=stub,
        require_llm_kept=False,
    )
    assert len(stub.calls) == 2
    sent_round2 = json.loads(stub.calls[1]["messages"][-1]["content"])
    assert sent_round2["history"]
    assert sent_round2["history"][0]["name"] == "silent-round1"
    assert bundle["meta"]["n_rounds_run"] == 2
    assert bundle["meta"]["top_scenario_name"] == "solvable-round2"
    assert EM_DASH not in json.dumps(bundle["design_report"])


def test_require_llm_kept_raises_when_no_valid_llm_candidate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CANARY_GEMINI_LEDGER", str(tmp_path / "ledger.jsonl"))
    bad_stub = StubClient(script=[{"text": "not valid json"}])
    with pytest.raises(RuntimeError, match="validity check"):
        psd.run_paired_skill_designer(
            llm_spec="gemini:gemini-4-carbon",
            tier="medium",
            design_seeds=[5],
            eval_seeds=[5100],
            n_proposals=2,
            max_rounds=1,
            out_dir=tmp_path / "fail_out",
            rungs=("full_solver", "do_nothing"),
            client=bad_stub,
            require_llm_kept=True,
        )


def test_source_and_committed_artifacts_provenance_and_style() -> None:
    py_files = [
        ROOT / "scripts" / "run_paired_skill_designer.py",
        ROOT / "tests" / "test_paired_skill_designer.py",
    ]
    for path in py_files:
        src = path.read_text(encoding="utf-8")
        assert EM_DASH not in src, str(path)
        assert EN_DASH not in src, str(path)
        tokens = list(tokenize.generate_tokens(io.StringIO(src).readline))
        comments = [tok for tok in tokens if tok.type == tokenize.COMMENT]
        assert comments == [], f"found comment in {path}: {comments}"
        assert scan_file_secrets(path, ROOT) == []

    if COMMITTED_DIR.is_dir():
        for fname in ("meta.json", "design_report.json", "skill_gap.json", "summary.md"):
            fpath = COMMITTED_DIR / fname
            assert fpath.is_file(), f"missing {fpath}"
            raw = fpath.read_text(encoding="utf-8")
            assert EM_DASH not in raw, f"em dash in {fpath}"
            assert EN_DASH not in raw, f"en dash in {fpath}"
            assert scan_file_secrets(fpath, ROOT) == []

        meta = json.loads((COMMITTED_DIR / "meta.json").read_text(encoding="utf-8"))
        design_doc = json.loads((COMMITTED_DIR / "design_report.json").read_text(encoding="utf-8"))
        gap_doc = json.loads((COMMITTED_DIR / "skill_gap.json").read_text(encoding="utf-8"))

        assert meta["role"] == "adaptive_mole"
        assert meta["subrole"] == "paired_skill_designer"
        assert meta["model_id"] == "gemini-4-carbon"
        assert meta["tiers_version"] == "v1.4"
        assert re.fullmatch(r"[0-9a-fA-F]{7,40}", meta["commit"])
        assert meta["n_episodes"] == 20
        assert meta["llm_ok"] is True
        assert meta["n_llm_valid"] >= 1
        assert meta["n_kept"] >= 1
        assert meta["usage"]["in"] > 0
        assert meta["usage"]["out"] > 0
        assert meta["usage"]["cost_usd"] > 0.0

        assert design_doc["design_seeds"] == [5, 6, 7, 8, 9]
        assert design_doc["X"] == pytest.approx(0.50)
        assert design_doc["Y"] == pytest.approx(0.20)
        sel = design_doc["selected_top_scenario"]
        assert sel["origin"] == "llm"
        assert sel["keep"] is True
        assert sel["solver"] >= 0.50
        assert sel["agent"] <= 0.20

        assert gap_doc["seeds"] == list(range(5100, 5120))
        assert gap_doc["n_episodes"] == 20
        assert tuple(r["rung"] for r in gap_doc["designed_rows"]) == skill_ladder.RUNG_ORDER
        for hr in ("full_solver", "no_ev_commit", "binary_canary_only", "heuristic_bisection", "do_nothing"):
            assert hr in gap_doc["headline_comparison"]

        prov = audit_provenance(ROOT)
        run_rel = "results/gemini_roles/adaptive_mole/paired-solvable-scenarios-carbon"
        matching = [r for r in prov["runs"] if r["run_dir"] == run_rel]
        assert len(matching) == 1
        assert matching[0]["verified"] is True, matching[0]["errors"]
        assert matching[0]["role"] == "adaptive_mole"
        assert matching[0]["model_id"] == "gemini-4-carbon"
        assert prov["roles"]["adaptive_mole"]["verified"] is True
        assert prov["secret_leaks"] == []
