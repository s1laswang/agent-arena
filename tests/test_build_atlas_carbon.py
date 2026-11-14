from __future__ import annotations

import dataclasses
import io
import json
import re
import tokenize
from pathlib import Path

import pytest

from canary import rules
from canary.baselines import DoNothing, RestrictAll, StopEarly, play
from canary.env import Env
from canary.gemini import dashboard as dash
from canary.gemini.ledger import read_ledger
from canary.llm.stub import StubClient
from scripts.build_atlas_carbon import (
    FRONTIER_FAMILIES,
    build_atlas,
    load_atlas_corpus,
    main,
    pack_atlas_corpus,
    tier_context,
    verify_quote_item,
)

ROOT = Path(__file__).resolve().parents[1]


def _make_sample_runs(runs_root: Path) -> Path:
    with tier_context("v1.2"):
        env_early = Env("medium", 2)
        play(env_early, StopEarly(seed=2))
        ep_early = dataclasses.asdict(env_early.result("codex:gpt-5.5"))

        env_rest = Env("medium", 3)
        play(env_rest, RestrictAll())
        ep_rest = dataclasses.asdict(env_rest.result("grok"))

    with tier_context("v1.3"):
        env_horizon = Env("hard", 4)
        play(env_horizon, DoNothing())
        ep_horizon = dataclasses.asdict(env_horizon.result("openai:gpt-5.5"))

    invalid_ep = dict(ep_early, seed=99, meta={"valid": False, "error": "rate_limit"})

    d_codex = runs_root / "codex-gpt-5.5" / "medium"
    (d_codex / "transcripts").mkdir(parents=True)
    (d_codex / "episodes.jsonl").write_text(
        json.dumps(ep_early) + "\n" + json.dumps(invalid_ep) + "\n",
        encoding="utf-8",
    )
    (d_codex / "transcripts" / "2.txt").write_text(
        json.dumps(
            {
                "type": "item.completed",
                "item": {
                    "type": "agent_message",
                    "text": "Accusing immediately on day 1 before waiting for canary leaks to surface.",
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )

    d_grok = runs_root / "grok" / "medium"
    d_grok.mkdir(parents=True)
    (d_grok / "episodes.jsonl").write_text(json.dumps(ep_rest) + "\n", encoding="utf-8")

    d_oai = runs_root / "v1.3" / "gpt-5.5-full" / "hard"
    d_oai.mkdir(parents=True)
    (d_oai / "episodes.jsonl").write_text(json.dumps(ep_horizon) + "\n", encoding="utf-8")

    d_ref = runs_root / "v1.3" / "reference" / "solver-hard"
    d_ref.mkdir(parents=True)
    (d_ref / "episodes.jsonl").write_text(json.dumps(dict(ep_horizon, agent="solver")) + "\n", encoding="utf-8")

    d_sup = runs_root / "superseded" / "gpt-5.5" / "medium"
    d_sup.mkdir(parents=True)
    (d_sup / "episodes.jsonl").write_text(json.dumps(ep_early) + "\n", encoding="utf-8")

    return runs_root


def _dashboard_payload(html: str) -> dict:
    m = re.search(r'<script id="data" type="application/json">(.*?)</script>', html, re.S)
    assert m is not None
    return json.loads(m.group(1).replace("<\\/", "</"))


def test_no_code_comments_or_em_dashes_in_created_files():
    py_files = [
        ROOT / "scripts" / "build_atlas_carbon.py",
        ROOT / "tests" / "test_build_atlas_carbon.py",
    ]
    for path in py_files:
        src = path.read_text(encoding="utf-8")
        assert "\u2014" not in src and "\u2013" not in src
        tokens = list(tokenize.generate_tokens(io.StringIO(src).readline))
        comment_tokens = [tok for tok in tokens if tok.type == tokenize.COMMENT]
        assert comment_tokens == [], f"unexpected comment tokens in {path}: {comment_tokens}"


def test_tier_context_restores_state():
    orig_ver = rules.TIERS_VERSION
    orig_kv = rules.KNOWN_V_MODE
    with tier_context("v1.2"):
        assert rules.TIERS_VERSION == "v1.3"
        assert rules.KNOWN_V_MODE is False
    with tier_context("v1.3"):
        assert rules.TIERS_VERSION == "v1.3"
        assert rules.KNOWN_V_MODE is True
    assert rules.TIERS_VERSION == orig_ver
    assert rules.KNOWN_V_MODE == orig_kv


def test_cli_stub_runs_keylessly_and_records_ledger(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    ledger_file = tmp_path / "ledger.jsonl"
    monkeypatch.setenv("GEMINI_API_KEY", "")
    monkeypatch.setenv("GOOGLE_GENERATIVE_AI_API_KEY", "")
    monkeypatch.setenv("CANARY_GEMINI_LEDGER", str(ledger_file))

    runs_dir = _make_sample_runs(tmp_path / "runs")
    out_dir = tmp_path / "results_out"
    rc = main(
        [
            "--runs",
            str(runs_dir),
            "--llm",
            "stub",
            "--out",
            str(out_dir),
            "--run-id",
            "atlas-stub-test",
            "--sample-size",
            "3",
        ]
    )
    assert rc == 0
    assert (out_dir / "atlas.json").is_file()
    assert (out_dir / "atlas.md").is_file()

    atlas = json.loads((out_dir / "atlas.json").read_text(encoding="utf-8"))
    assert atlas["synthetic"] is True
    assert atlas["source"] == "fallback"
    assert atlas["ledger_run_ids"] == ["atlas-stub-test"]
    assert atlas["corpus"]["episodes"] == 3
    assert atlas["corpus"]["invalid_skipped"] == 1
    assert atlas["quote_verification"]["all_verified"] is True
    assert atlas["quote_verification"]["verified"] == atlas["quote_verification"]["total"] >= 3
    assert atlas["agreement"]["total"] == 3
    assert atlas["human_agreement"]["total"] == 3
    assert atlas["accusation_posteriors"]["n_accusations"] == 2
    assert atlas["accusation_posteriors"]["n_no_accusation"] == 1

    lrows = read_ledger([ledger_file])
    assert len(lrows) >= 1
    assert all(r["feature"] == "atlas" and r["run_id"] == "atlas-stub-test" for r in lrows)

    html_out = tmp_path / "dash.html"
    assert dash.main(["--ledger", str(ledger_file), "--results", str(out_dir), "--out", str(html_out)]) == 0
    payload = _dashboard_payload(html_out.read_text(encoding="utf-8"))
    assert len(payload["results"]["atlas"]["modes"]) >= 2


def test_scripted_llm_verbatim_quotes_and_agreement_math(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    ledger_file = tmp_path / "ledger.jsonl"
    monkeypatch.setenv("GEMINI_API_KEY", "")
    monkeypatch.setenv("GOOGLE_GENERATIVE_AI_API_KEY", "")
    monkeypatch.setenv("CANARY_GEMINI_LEDGER", str(ledger_file))

    runs_dir = _make_sample_runs(tmp_path / "runs")
    records, stats = load_atlas_corpus(runs_dir, families=FRONTIER_FAMILIES)
    _, blocks = pack_atlas_corpus(records)
    active_ids = [mid for mid, st in stats["mode_stats"].items() if st["active"]]

    mode_items = []
    for mid in active_ids:
        rec = next(r for r in records if mid in r["modes_present"])
        blk_lines = blocks[rec["key"]].splitlines()
        q_line = next((ln for ln in blk_lines if ln.startswith("transcript ")), blk_lines[0])
        mode_items.append(
            {
                "id": mid,
                "name": f"Mode {mid}",
                "description": f"Grounded failure mode {mid} tied to deterministic solver regret\u2014verified.",
                "decision": "accuse",
                "quotes": [{"episode": rec["key"], "t": 0, "quote": q_line}],
            }
        )

    synth_payload = {
        "summary": "Frontier episodes exhibit premature accusation, over-restriction, and horizon expiration\u2014all verified.",
        "modes": mode_items,
    }
    sample_labels = []
    for idx, rec in enumerate(records):
        chosen_mid = rec["solver_primary_mode"]
        if idx == len(records) - 1 and len(active_ids) > 1:
            chosen_mid = next(m for m in active_ids if m != rec["solver_primary_mode"])
        sample_labels.append({"episode": rec["key"], "mode_id": chosen_mid})
    sample_payload = {"labels": sample_labels}

    client = StubClient(
        script=[{"json": synth_payload}, {"json": sample_payload}],
        model="gemini-4-carbon",
    )
    out_dir = tmp_path / "carbon_mock"
    atlas = build_atlas(
        runs_root=runs_dir,
        llm=client,
        out_dir=out_dir,
        run_id="atlas-mock-v1",
        sample_size=3,
        require_llm=True,
    )

    assert atlas["synthetic"] is False
    assert atlas["source"] == "llm"
    assert atlas["model"] == "gemini-4-carbon"
    assert atlas["quote_verification"]["all_verified"] is True
    assert atlas["agreement"]["total"] == 3
    assert atlas["agreement"]["agree"] == 2
    assert atlas["agreement"]["rate"] == round(2 / 3, 4)
    assert atlas["human_agreement"]["agree"] == 2

    raw_json = (out_dir / "atlas.json").read_text(encoding="utf-8")
    raw_md = (out_dir / "atlas.md").read_text(encoding="utf-8")
    assert "\u2014" not in raw_json and "\u2013" not in raw_json
    assert "\u2014" not in raw_md and "\u2013" not in raw_md


def test_retry_recovers_and_persistent_hallucination_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("GEMINI_API_KEY", "")
    monkeypatch.setenv("GOOGLE_GENERATIVE_AI_API_KEY", "")
    monkeypatch.setenv("CANARY_GEMINI_LEDGER", str(tmp_path / "ledger.jsonl"))

    runs_dir = _make_sample_runs(tmp_path / "runs")
    records, stats = load_atlas_corpus(runs_dir, families=FRONTIER_FAMILIES)
    _, blocks = pack_atlas_corpus(records)
    active_ids = [mid for mid, st in stats["mode_stats"].items() if st["active"]]

    good_modes = []
    bad_modes = []
    for i, mid in enumerate(active_ids):
        rec = next(r for r in records if mid in r["modes_present"])
        good_line = blocks[rec["key"]].splitlines()[0]
        good_modes.append(
            {
                "id": mid,
                "name": f"Valid {mid}",
                "description": f"Valid grounded description for failure mode {mid}.",
                "decision": "accuse",
                "quotes": [{"episode": rec["key"], "t": 0, "quote": good_line}],
            }
        )
        bad_modes.append(
            {
                "id": mid,
                "name": f"Draft {mid}",
                "description": f"Draft description for failure mode {mid}.",
                "decision": "accuse",
                "quotes": [
                    {
                        "episode": rec["key"],
                        "t": 0,
                        "quote": "invented non-existent quote line" if i == 0 else good_line,
                    }
                ],
            }
        )

    bad_synth = {"summary": "Initial synthesis with hallucinated quote.", "modes": bad_modes}
    good_synth = {"summary": "Recovered synthesis with exact quotes.", "modes": good_modes}
    good_sample = {"labels": [{"episode": r["key"], "mode_id": r["solver_primary_mode"]} for r in records]}

    recovering = StubClient(
        script=[{"json": bad_synth}, {"json": good_synth}, {"json": good_sample}],
        model="gemini-4-carbon",
    )
    recovered = build_atlas(
        runs_root=runs_dir,
        llm=recovering,
        out_dir=tmp_path / "recovered",
        run_id="atlas-retry-ok",
        sample_size=3,
        require_llm=True,
    )
    assert recovered["source"] == "llm"
    assert recovered["corpus"]["calls"] == 3
    assert recovered["quote_verification"]["all_verified"] is True

    failing = StubClient(
        script=[{"json": bad_synth}, {"json": bad_synth}],
        model="gemini-4-carbon",
    )
    with pytest.raises(AssertionError, match="expected 100% verified LLM synthesis"):
        build_atlas(
            runs_root=runs_dir,
            llm=failing,
            out_dir=tmp_path / "failed",
            run_id="atlas-retry-fail",
            sample_size=3,
            require_llm=True,
        )


def test_committed_carbon_atlas_artifacts_and_dashboard_render(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("GEMINI_API_KEY", "")
    monkeypatch.setenv("GOOGLE_GENERATIVE_AI_API_KEY", "")

    atlas_dir = ROOT / "results" / "gemini_roles" / "failure_analyst" / "atlas-carbon"
    atlas_json_path = atlas_dir / "atlas.json"
    atlas_md_path = atlas_dir / "atlas.md"
    meta_path = atlas_dir / "meta.json"
    assert atlas_json_path.is_file()
    assert atlas_md_path.is_file()
    assert meta_path.is_file()

    raw_json = atlas_json_path.read_text(encoding="utf-8")
    raw_md = atlas_md_path.read_text(encoding="utf-8")
    raw_meta = meta_path.read_text(encoding="utf-8")
    assert "\u2014" not in raw_json and "\u2013" not in raw_json
    assert "\u2014" not in raw_md and "\u2013" not in raw_md
    assert "\u2014" not in raw_meta and "\u2013" not in raw_meta
    assert dash.SECRET_RE.search(raw_json) is None
    assert dash.SECRET_RE.search(raw_md) is None
    assert dash.SECRET_RE.search(raw_meta) is None

    meta = json.loads(raw_meta)
    assert meta["role"] == "failure_analyst"
    assert meta["model_id"] == "gemini-4-carbon"
    assert meta["stub"] is False
    assert meta["n_episodes_packed"] == 101
    assert meta["usage"]["in"] >= 200_000
    assert meta["usage"]["out"] > 0

    atlas = json.loads(raw_json)
    required_top = {
        "generated_at",
        "git_sha",
        "ledger_run_ids",
        "synthetic",
        "model",
        "modes",
        "corpus",
        "quote_verification",
        "agreement",
        "human_agreement",
        "accusation_posteriors",
    }
    assert required_top <= set(atlas.keys())
    assert atlas["model"] == "gemini-4-carbon"
    assert atlas["synthetic"] is False
    assert atlas["source"] == "llm"
    assert atlas["ledger_run_ids"] == ["atlas-carbon-v1"]

    corpus = atlas["corpus"]
    assert corpus["episodes"] == 101
    assert corpus["tokens"] >= 200_000
    assert corpus["single_pack_tokens"] >= 200_000
    assert corpus["out_tokens"] > 0
    assert corpus["thinking_tokens"] > 0
    assert corpus["cost_usd"] > 0.0

    modes = atlas["modes"]
    assert len(modes) == 6
    shares = [float(m["regret_share"]) for m in modes]
    assert shares == sorted(shares, reverse=True)
    assert abs(sum(shares) - 1.0) <= 0.005

    qv = atlas["quote_verification"]
    assert qv["all_verified"] is True
    assert qv["verified"] == qv["total"] >= 12
    assert qv["pct"] == 100.0

    ag = atlas["agreement"]
    ha = atlas["human_agreement"]
    assert ag["total"] == 30
    assert 20 <= ag["agree"] <= 30
    assert ag["rate"] == round(ag["agree"] / ag["total"], 4)
    assert ha["agree"] == ag["agree"] and ha["total"] == ag["total"] and ha["rate"] == ag["rate"]

    records, _ = load_atlas_corpus(ROOT / "data" / "runs" / "committed")
    records_by_key = {r["key"]: r for r in records}
    _, blocks = pack_atlas_corpus(records)
    for m in modes:
        assert {"id", "name", "description", "decision", "regret_share", "episodes", "quotes", "chart"} <= set(m.keys())
        assert isinstance(m["episodes"], int) and m["episodes"] >= 1
        assert len(m["quotes"]) >= 2
        for q in m["quotes"]:
            assert q["verified"] is True
            assert isinstance(q["t"], int) and q["t"] >= 0
            ok, _, _ = verify_quote_item(q["episode"], q["t"], q["quote"], blocks, records_by_key)
            assert ok is True

    fixture_ledger = ROOT / "tests" / "fixtures" / "gemini_lab" / "ledger"
    out_html = tmp_path / "dashboard.html"
    rc = dash.main(
        [
            "--ledger",
            str(fixture_ledger),
            "--results",
            str(atlas_dir),
            "--out",
            str(out_html),
        ]
    )
    assert rc == 0
    html = out_html.read_text(encoding="utf-8")
    assert 'id="p-atlas"' in html
    payload = _dashboard_payload(html)
    rendered_atlas = payload["results"]["atlas"]
    assert rendered_atlas is not None
    assert rendered_atlas["synthetic"] is False
    assert rendered_atlas["model"] == "gemini-4-carbon"
    assert len(rendered_atlas["modes"]) == 6
    assert all(m.get("chart_src", "").startswith("data:image/") for m in rendered_atlas["modes"])
