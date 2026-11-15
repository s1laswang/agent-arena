"""Tests for WS5 PAIRED scenario designer at scale (canary.gemini.designer_scale)."""
from __future__ import annotations

import json
from pathlib import Path
import pytest

from canary.gemini import designer_scale as ds
from canary.llm.base import LLMResponse, ToolCall


class _FakeRaw:
    def __init__(self, mv: str):
        self.model_version = mv
        self.usage_metadata = None


class _FakeClient:
    """Deterministic fake client for offline testing of proposer, flash-low filter, and argon-high transfer."""

    def __init__(self, model: str, level: str):
        self.model = model
        self.level = level
        self.calls = 0

    def chat(self, messages, tools=None, temperature=0.0, response_schema=None, max_tokens=None, seed=None):
        self.calls += 1
        if response_schema is not None:
            # Proposer batch call -> return 3 distinct valid DSL strategies + 1 non-leaking strategy
            strategies = [
                {
                    "name": f"careful-oldest-{i}",
                    "rationale": "Leak oldest when holding multiple docs and frame decoy.",
                    "rules": [
                        {"if": [["n_docs_held", ">=", str(i + 2)]], "then": {"leak": "oldest", "frame": "decoy"}},
                        {"if": [["recent_low_recipient_docs", ">=", "2"]], "then": {"leak": "most_recipients", "frame": "none"}},
                    ],
                    "default": {"leak": "random_seeded", "frame": "decoy"},
                }
                for i in range(3)
            ] + [
                {
                    "name": "never-leaks-invalid",
                    "rationale": "Should be rejected by strategy_can_leak.",
                    "rules": [{"if": [["day", ">=", "1"]], "then": {"leak": "none", "frame": "none"}}],
                    "default": {"leak": "none", "frame": "none"},
                }
            ]
            return LLMResponse(
                text=json.dumps({"strategies": strategies}),
                usage={"in": 100, "out": 80, "cost_usd": 0.001},
                raw=_FakeRaw(self.model),
            )
        # Investigator episode call: flash-low guesses e00 immediately (scores <= 0.2); argon-high abstains (0.0)
        if "flash" in self.model:
            tc = ToolCall(id=f"c_{self.calls}", name="accuse", args={"employee": "e00"})
        else:
            tc = ToolCall(id=f"c_{self.calls}", name="advance_day" if self.calls < 15 else "status", args={})
        return LLMResponse(
            text="acting",
            tool_calls=[tc],
            usage={"in": 200, "out": 20, "cost_usd": 0.001},
            raw=_FakeRaw(self.model),
        )


def test_arena_label_and_carbon_guard():
    assert ds.ARENA_LABEL == "arena mode, not the judged environment"
    with pytest.raises(ValueError, match="forbidden"):
        ds.run_llm_episode_with_retry(
            model="gemini-4-carbon",
            thinking_level="high",
            tier="medium",
            seed=0,
            strat_json=None,
            run_id="t",
            meta={},
        )


def test_functional_signature_separates_thresholds_and_merges_dead_rules():
    s1 = {"rules": [{"if": [["day", ">=", 8]], "then": {"leak": "oldest", "frame": "decoy"}}],
          "default": {"leak": "random_seeded", "frame": "none"}}
    s2 = {"rules": [{"if": [["day", ">=", 9]], "then": {"leak": "oldest", "frame": "decoy"}}],
          "default": {"leak": "random_seeded", "frame": "none"}}
    # s3 has an unreachable dead rule (i_am_restricted == 99) after s1 -> functionally identical to s1
    s3 = {"rules": [
        {"if": [["day", ">=", 8]], "then": {"leak": "oldest", "frame": "decoy"}},
        {"if": [["i_am_restricted", "==", 99]], "then": {"leak": "newest", "frame": "random_peer"}},
    ], "default": {"leak": "random_seeded", "frame": "none"}}
    assert ds.functional_signature(s1) != ds.functional_signature(s2)
    assert ds.functional_signature(s1) == ds.functional_signature(s3)


def test_end_to_end_fake_campaign_writes_labelled_artifacts(tmp_path: Path):
    scratch = tmp_path / "scratch"
    out = tmp_path / "out"
    res = ds.run_campaign(
        target=3,
        tier="medium",
        seeds=[0, 1, 2, 3, 4],
        scratch_dir=scratch,
        out_dir=out,
        cpu_workers=1,
        flash_concurrency=2,
        argon_concurrency=2,
        top_k_argon=2,
        run_id="test-ws5",
        client_builder=lambda model, level, rid, meta: _FakeClient(model, level),
    )
    assert res["mode"] == "arena mode, not the judged environment"
    assert res["label"] == "arena mode, not the judged environment"
    assert res["models"]["carbon_calls"] == 0
    assert res["counts"]["n_fully_evaluated"] == 3
    assert (out / "designer.json").exists()
    assert (out / "designer.md").exists()
    md_text = (out / "designer.md").read_text()
    assert "arena mode, not the judged environment" in md_text
    assert json.loads((out / "designer.json").read_text())["mode"] == "arena mode, not the judged environment"


def test_committed_designer_artifacts_if_present():
    out = ds.ROOT / "results" / "gemini" / "scale" / "designer"
    if not (out / "designer.json").exists():
        return
    d = json.loads((out / "designer.json").read_text())
    assert d["mode"] == "arena mode, not the judged environment"
    assert d["models"]["carbon_calls"] == 0
    assert d["counts"]["n_proposed_total"] >= 1
    md = (out / "designer.md").read_text()
    assert "arena mode, not the judged environment" in md
