from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import pytest

from canary import rules
from canary.agents import analyst
from canary.baselines import StopEarly, play
from canary.env import Env
from canary.llm.stub import StubClient
from scripts.run_role_failure_analyst import (
    FRONTIER_FAMILIES,
    load_corpus,
    main,
    run_failure_analyst,
    tier_context,
)


def _make_sample_runs(root: Path) -> Path:
    with tier_context("v1.2"):
        env_med = Env("medium", 2)
        play(env_med, StopEarly(seed=2))
        ep_med = dataclasses.asdict(env_med.result("openai:gpt-5.5"))

    with tier_context("v1.3"):
        env_hard = Env("hard", 3)
        play(env_hard, StopEarly(seed=3))
        ep_hard = dataclasses.asdict(env_hard.result("codex:gpt-5.5"))

    invalid_ep = dict(ep_med, seed=99, meta={"valid": False, "error": "quota"})

    d_v12 = root / "gpt-5.5" / "medium-0-4"
    d_v12.mkdir(parents=True)
    (d_v12 / "episodes.jsonl").write_text(
        json.dumps(ep_med) + "\n" + json.dumps(invalid_ep) + "\n"
    )

    d_v13 = root / "v1.3" / "codex-gpt-5.5-full" / "hard"
    d_v13.mkdir(parents=True)
    (d_v13 / "episodes.jsonl").write_text(json.dumps(ep_hard) + "\n")

    d_sup = root / "superseded" / "gpt-5.5" / "medium"
    d_sup.mkdir(parents=True)
    (d_sup / "episodes.jsonl").write_text(json.dumps(ep_med) + "\n")

    d_ref = root / "v1.3" / "reference" / "solver-hard"
    d_ref.mkdir(parents=True)
    (d_ref / "episodes.jsonl").write_text(json.dumps(dict(ep_hard, agent="solver")) + "\n")

    return root


def test_tier_context_restores_globals():
    orig_ver = rules.TIERS_VERSION
    orig_kv = rules.KNOWN_V_MODE
    orig_hard_n = rules.TIERS["hard"].n_employees
    with tier_context("v1.2"):
        assert rules.TIERS_VERSION == "v1.3"
        assert rules.KNOWN_V_MODE is False
        assert rules.TIERS["hard"].n_employees == 30
    with tier_context("v1.3"):
        assert rules.TIERS_VERSION == "v1.3"
        assert rules.KNOWN_V_MODE is True
        assert rules.TIERS["hard"].n_employees == 30
    assert rules.TIERS_VERSION == orig_ver
    assert rules.KNOWN_V_MODE == orig_kv
    assert rules.TIERS["hard"].n_employees == orig_hard_n


def test_load_corpus_filters_and_attributes(tmp_path: Path):
    runs_dir = _make_sample_runs(tmp_path / "runs")
    records, stats = load_corpus(runs_dir, families=FRONTIER_FAMILIES)
    assert len(records) == 2
    assert stats["n_episodes_packed"] == 2
    assert stats["n_invalid_skipped"] == 1
    assert [r["tiers_version"] for r in records] == ["v1.2", "v1.3"]
    assert all("premature_accusation" in r["tag_set"] for r in records)
    assert stats["regret_tags"]["premature_accusation"]["episodes_with"] == 2


def test_committed_corpus_count_and_invariants():
    committed = Path("data/runs/committed")
    if not committed.exists():
        pytest.skip("committed corpus not present")
    orig_ver = rules.TIERS_VERSION
    orig_kv = rules.KNOWN_V_MODE
    records, stats = load_corpus(committed)
    assert rules.TIERS_VERSION == orig_ver
    assert rules.KNOWN_V_MODE == orig_kv
    assert stats["n_episodes_packed"] >= 100
    assert stats["n_invalid_skipped"] >= 1
    agents = {r["episode"]["agent"] for r in records}
    assert {"codex:gpt-5.5", "openai:gpt-5.5", "grok", "opencode:openai/gpt-5.6-sol"} <= agents
    assert all("superseded" not in r["run_path"] and "reference" not in r["run_path"] for r in records)


def test_cli_stub_runs_keylessly(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("GEMINI_API_KEY", "")
    monkeypatch.setenv("GOOGLE_GENERATIVE_AI_API_KEY", "")
    runs_dir = _make_sample_runs(tmp_path / "runs")
    out_dir = tmp_path / "out"
    doc_file = tmp_path / "failure_gallery.md"
    rc = main(
        [
            "--runs",
            str(runs_dir),
            "--llm",
            "stub",
            "--out",
            str(out_dir),
            "--doc-out",
            str(doc_file),
        ]
    )
    assert rc == 0
    for fname in ("meta.json", "report.json", "raw_response.json", "pack_stats.json", "failure_gallery.md"):
        assert (out_dir / fname).exists()
    assert doc_file.exists()
    meta = json.loads((out_dir / "meta.json").read_text())
    assert meta["role"] == "failure_analyst"
    assert meta["n_episodes_packed"] == 2
    assert meta["source"].startswith("fallback")


def test_mocked_llm_verbatim_quotes_and_gallery(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("GEMINI_API_KEY", "")
    monkeypatch.setenv("GOOGLE_GENERATIVE_AI_API_KEY", "")
    runs_dir = _make_sample_runs(tmp_path / "runs")
    records, _ = load_corpus(runs_dir)
    _, blocks = analyst.pack([r["episode"] for r in records], [r["regret_rows"] for r in records])
    keys = list(blocks.keys())
    line0 = next(ln for ln in blocks[keys[0]].splitlines() if ln.startswith("regret "))
    line1 = next(ln for ln in blocks[keys[1]].splitlines() if ln.startswith("d1 "))
    line2 = blocks[keys[1]].splitlines()[0]

    payload = {
        "summary": "Frontier agents lose value primarily through premature low-posterior accusations\u2014especially day 1.",
        "clusters": [
            {
                "name": "Premature Accusation Below Break-Even",
                "count": 2,
                "description": "Accuses on day 1 before canary leaks surface, incurring large solver regret.",
                "quotes": [{"episode": keys[0], "quote": line0}],
            },
            {
                "name": "Zero-Evidence Day-1 Commit",
                "count": 1,
                "description": "Commits to an accusation prior to running multi-day canary partitions.",
                "quotes": [{"episode": keys[1], "quote": line1}],
            },
            {
                "name": "Negative-Score Wrong Accusation",
                "count": 2,
                "description": "Firing an innocent employee scores -1.0 versus 0.0 for horizon abstention.",
                "quotes": [{"episode": keys[1], "quote": line2}],
            },
        ],
    }
    client = StubClient(script=[{"json": payload}], model="gemini-4-carbon")
    out_dir = tmp_path / "carbon_out"
    doc_file = tmp_path / "docs" / "failure_gallery.md"

    res = run_failure_analyst(
        runs_root=runs_dir,
        llm=client,
        out_dir=out_dir,
        doc_out=doc_file,
        require_llm=True,
        command_str="python scripts/run_role_failure_analyst.py --llm gemini:gemini-4-carbon",
    )
    meta = res["meta"]
    assert meta["role"] == "failure_analyst"
    assert meta["model_id"] == "gemini-4-carbon"
    assert meta["source"] == "llm"
    assert meta["verified_quotes_pct"] == 100.0
    assert meta["n_episodes_packed"] == 2
    assert set(meta["usage"]) >= {"prompt_tokens", "out_tokens", "cost_usd"}
    assert meta["usage"]["prompt_tokens"] > 0

    gallery = doc_file.read_text()
    assert gallery == (out_dir / "failure_gallery.md").read_text()
    assert "\u2014" not in gallery and "\u2013" not in gallery
    assert "Annotated Trajectory Comparisons per Top Failure Mode" in gallery
    assert "Counterfactual Best Solver Action" in gallery
    assert "P(mole=" in gallery
    assert line0 in gallery and line1 in gallery


def test_retry_recovers_from_unverified_quote_and_rejects_persistent_hallucination(tmp_path: Path):
    runs_dir = _make_sample_runs(tmp_path / "runs")
    records, _ = load_corpus(runs_dir)
    _, blocks = analyst.pack([r["episode"] for r in records], [r["regret_rows"] for r in records])
    k0, k1 = list(blocks.keys())
    good_q0 = blocks[k0].splitlines()[0]
    good_q1 = blocks[k1].splitlines()[0]
    good_q2 = next(ln for ln in blocks[k0].splitlines() if ln.startswith("regret "))

    bad_payload = {
        "summary": "Initial draft with a paraphrased quote.",
        "clusters": [
            {
                "name": "Premature Accusation",
                "count": 2,
                "description": "Early accusation.",
                "quotes": [
                    {"episode": k0, "quote": good_q0},
                    {"episode": k1, "quote": "paraphrased line not in block"},
                ],
            },
            {
                "name": "Horizon Loss",
                "count": 1,
                "description": "Score drop.",
                "quotes": [{"episode": k1, "quote": good_q1}],
            },
            {
                "name": "Regret Spike",
                "count": 1,
                "description": "High single-step regret.",
                "quotes": [{"episode": k0, "quote": good_q2}],
            },
        ],
    }
    fixed_payload = {
        "summary": "Fixed draft with 100 percent verbatim quotes.",
        "clusters": [
            {
                "name": "Premature Accusation",
                "count": 2,
                "description": "Early accusation.",
                "quotes": [{"episode": k0, "quote": good_q0}, {"episode": k1, "quote": good_q1}],
            },
            {
                "name": "Horizon Loss",
                "count": 1,
                "description": "Score drop.",
                "quotes": [{"episode": k1, "quote": good_q1}],
            },
            {
                "name": "Regret Spike",
                "count": 1,
                "description": "High single-step regret.",
                "quotes": [{"episode": k0, "quote": good_q2}],
            },
        ],
    }

    recovering_client = StubClient(
        script=[{"json": bad_payload}, {"json": fixed_payload}],
        model="gemini-4-carbon",
    )
    res = run_failure_analyst(
        runs_root=runs_dir,
        llm=recovering_client,
        out_dir=tmp_path / "recovered",
        doc_out=None,
        require_llm=True,
    )
    assert res["meta"]["source"] == "llm"
    assert res["meta"]["verified_quotes_pct"] == 100.0
    assert res["meta"]["usage"]["calls"] == 2

    failing_client = StubClient(
        script=[{"json": bad_payload}, {"json": bad_payload}],
        model="gemini-4-carbon",
    )
    with pytest.raises(AssertionError, match="100% verified"):
        run_failure_analyst(
            runs_root=runs_dir,
            llm=failing_client,
            out_dir=tmp_path / "failed",
            doc_out=None,
            require_llm=True,
        )


def test_committed_carbon_run_artifacts_verified_keylessly():
    run_dir = Path("results/gemini_roles/failure_analyst/carbon-longctx-corpus")
    doc_path = Path("docs/gemini/FAILURE_GALLERY_CARBON.md")
    if not run_dir.exists():
        pytest.skip("committed carbon run not present")

    for fname in ("meta.json", "report.json", "raw_response.json", "pack_stats.json", "failure_gallery.md"):
        assert (run_dir / fname).exists()
    assert doc_path.exists()

    meta = json.loads((run_dir / "meta.json").read_text())
    assert meta["role"] == "failure_analyst"
    assert meta["model_id"] == "gemini-4-carbon"
    assert meta["source"] == "llm"
    assert meta["verified_quotes_pct"] == 100.0
    assert meta["n_episodes_packed"] == 101
    assert meta["usage"]["prompt_tokens"] > 0
    assert meta["usage"]["out_tokens"] > 0
    assert meta["usage"]["cost_usd"] > 0.0

    rep = analyst.Report.model_validate_json((run_dir / "report.json").read_text())
    records, _ = load_corpus("data/runs/committed")
    _, blocks = analyst.pack([r["episode"] for r in records], [r["regret_rows"] for r in records])
    verified = analyst._verify(rep, blocks)
    assert verified is not None
    assert len(verified.clusters) == len(rep.clusters) >= 3
    for c_orig, c_ver in zip(rep.clusters, verified.clusters):
        assert len(c_orig.quotes) == len(c_ver.quotes) >= 1
        for q in c_orig.quotes:
            assert q.episode in blocks
            assert q.quote.strip() and q.quote.strip() in blocks[q.episode]

    md = doc_path.read_text()
    assert md == (run_dir / "failure_gallery.md").read_text()
    assert "\u2014" not in md and "\u2013" not in md
    assert "Annotated Trajectory Comparisons per Top Failure Mode" in md
