from __future__ import annotations

import json
from pathlib import Path
import re
from types import SimpleNamespace

import pytest

from canary.gemini import atlas, dashboard
from canary.gemini.ledger import read_ledger
from canary.llm import StubClient

FAKE_SECRET = "AIza" + "FAKE-atlas-unit-test-secret"


@pytest.fixture(autouse=True)
def _isolated_ledger(tmp_path, monkeypatch):
    ledger_file = tmp_path / "ledger.jsonl"
    monkeypatch.setenv("CANARY_GEMINI_LEDGER", str(ledger_file))
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_GENERATIVE_AI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_GATEWAY_URL", raising=False)
    return ledger_file


def _roster_step(n: int = 20) -> dict:
    emps = [
        {"id": f"e{i:02d}", "name": f"Emp {i}", "dept": "Engineering", "role": "engineer", "clearance": 2}
        for i in range(n)
    ]
    return {
        "t": 0,
        "day": 1,
        "tool": "list_employees",
        "args": {},
        "result": {"ok": True, "data": {"employees": emps}, "error": None},
    }


def _sample_episodes() -> list[dict]:
    ep_premature = {
        "tier": "medium",
        "seed": 0,
        "agent": "gemini:gemini-4-carbon",
        "steps": [
            _roster_step(20),
            {
                "t": 1,
                "day": 1,
                "tool": "plant_canary",
                "args": {"doc_title": "Draft", "assignment": {"e00": "A"}},
                "result": {"ok": True, "data": {"doc_id": "c1"}, "error": None},
            },
            {
                "t": 2,
                "day": 1,
                "tool": "accuse",
                "args": {"employee": "e01"},
                "result": {"ok": True, "data": {"episode_over": True}, "error": None},
            },
        ],
        "score": -1.0,
        "accused": "e01",
        "correct": False,
        "final_day": 1,
        "end_reason": "accused",
        "meta": {"decoy": "e01"},
    }
    ep_restrict_budget = {
        "tier": "medium",
        "seed": 1,
        "agent": "gemini:gemini-4-carbon",
        "steps": [
            _roster_step(20),
            {
                "t": 1,
                "day": 1,
                "tool": "restrict_access",
                "args": {"employee": "e02"},
                "result": {"ok": True, "data": {}, "error": None},
            },
            {
                "t": 2,
                "day": 1,
                "tool": "search_messages",
                "args": {"query": "leak"},
                "result": {"ok": False, "data": None, "error": "daily action limit; call advance_day"},
            },
        ],
        "score": 0.0,
        "accused": None,
        "correct": False,
        "final_day": 14,
        "end_reason": "horizon",
        "meta": {"notes": [{"t": 2, "quote": f"Hit action limit key={FAKE_SECRET}\u2014stopping."}]},
    }
    return [ep_premature, ep_restrict_budget]


def test_corpus_packer_tags_and_posteriors(tmp_path):
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()
    eps = _sample_episodes()
    (runs_dir / "episodes.jsonl").write_text("\n".join(json.dumps(e) for e in eps) + "\n")
    tdir = runs_dir / "transcripts"
    tdir.mkdir()
    (tdir / "0.json").write_text(
        json.dumps([{"role": "assistant", "content": "Rushing accusation on e01 without waiting for leak.", "tool_calls": [{}, {}, {}]}])
    )

    records, skipped = atlas.load_corpus([runs_dir])
    assert len(records) == 2 and skipped == 0

    r0, r1 = records
    assert "premature_accusation" in r0["rule_tags"]
    assert "uninformative_canary" in r0["rule_tags"]
    assert "decoy_chase" in r0["rule_tags"]
    assert r0["posterior"]["did_accuse"] is True
    assert r0["posterior"]["p_accused"] is not None and r0["posterior"]["p_accused"] < r0["posterior"]["threshold"]
    assert r0["posterior"]["premature_commit"] is True

    assert "over_restriction" in r1["rule_tags"]
    assert "budget_waste" in r1["rule_tags"]
    assert "no_accusation" in r1["rule_tags"]
    assert r1["posterior"]["did_accuse"] is False

    packed, blocks = atlas.pack_corpus(records)
    assert len(blocks) == 2
    assert "posterior: p_accused=" in packed
    assert "Rushing accusation on e01 without waiting for leak." in blocks[r0["key"]]
    assert FAKE_SECRET not in packed and "AIza" not in packed
    assert "\u2014" not in packed and "\u2013" not in packed

    committed_records, _ = atlas.load_corpus(max_episodes=5)
    assert len(committed_records) == 5


def test_strict_verbatim_quote_verifier():
    records = atlas.records_from_episodes(_sample_episodes())
    _, blocks = atlas.pack_corpus(records)
    k0, k1 = records[0]["key"], records[1]["key"]
    exact_line = next(ln for ln in blocks[k0].splitlines() if ln.startswith("t=2 "))
    other_line = next(ln for ln in blocks[k1].splitlines() if ln.startswith("t=2 "))

    modes = [
        {
            "id": "premature-accusation",
            "name": "Premature accusation",
            "description": "Accuses early.",
            "decision": "accuse",
            "rule_tag": "premature_accusation",
            "episode_keys": [k0],
            "quotes": [
                {"episode": k0, "t": 2, "quote": exact_line},
                {"episode": k0, "t": 2, "quote": exact_line[:12] + "..." + exact_line[-6:]},
                {"episode": k0, "t": 2, "quote": other_line},
                {"episode": "missing-episode", "t": 0, "quote": exact_line},
                {"episode": k0, "t": 0, "quote": "   "},
            ],
        }
    ]

    qv = atlas.verify_quotes(modes, blocks)
    assert qv["verified_quotes"] == 1
    assert qv["total_quotes"] == 5
    assert qv["rate"] == 0.2
    assert qv["pct"] == 20.0
    assert [q["verified"] for q in modes[0]["quotes"]] == [True, False, False, False, False]
    assert len(qv["unverified"]) == 4


def test_rule_based_vs_llm_agreement_score():
    records = atlas.records_from_episodes(_sample_episodes())
    _, blocks = atlas.pack_corpus(records)
    stub_payload = atlas.build_stub_payload(records, blocks, max_modes=8)
    exact_ag = atlas.compute_agreement(stub_payload["modes"], records)
    assert exact_ag["agree"] == exact_ag["total"] > 0
    assert exact_ag["rate"] == 1.0
    assert exact_ag["macro_jaccard"] == 1.0

    k0, k1 = records[0]["key"], records[1]["key"]
    noisy_modes = [
        {
            "id": "premature-accusation",
            "name": "Premature accusation",
            "description": "Early commit.",
            "decision": "accuse",
            "rule_tag": "premature_accusation",
            "episode_keys": [k0, k1],
            "quotes": [],
        },
        {
            "id": "late-commit",
            "name": "Commits too late",
            "description": "Waits too long.",
            "decision": "advance_day",
            "rule_tag": "late_commit",
            "episode_keys": [k0],
            "quotes": [],
        },
    ]
    partial_ag = atlas.compute_agreement(noisy_modes, records)
    assert partial_ag["agree"] == 1
    assert partial_ag["total"] > partial_ag["agree"]
    assert 0.0 < partial_ag["rate"] < 1.0
    assert partial_ag["precision"] == round(1 / 3, 4)


def test_mock_gemini_4_carbon_via_lab_client(tmp_path, monkeypatch, _isolated_ledger):
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()
    eps = _sample_episodes()
    (runs_dir / "episodes.jsonl").write_text("\n".join(json.dumps(e) for e in eps) + "\n")

    records, _ = atlas.load_corpus([runs_dir])
    _, blocks = atlas.pack_corpus(records)
    k0, k1 = records[0]["key"], records[1]["key"]
    q0 = next(ln for ln in blocks[k0].splitlines() if ln.startswith("t=2 "))
    q1 = next(ln for ln in blocks[k1].splitlines() if ln.startswith("t=2 "))

    llm_json = {
        "summary": "Long-context carbon synthesis\u2014sanitized to ASCII hyphens.",
        "modes": [
            {
                "id": "premature-accusation",
                "name": "Premature accusation",
                "description": "Accuses below break-even posterior.",
                "decision": "accuse",
                "rule_tag": "premature_accusation",
                "episode_keys": [k0],
                "quotes": [{"episode": k0, "t": 2, "quote": q0}],
            },
            {
                "id": "budget-waste",
                "name": "Budget waste",
                "description": "Hits daily action limit.",
                "decision": "search_messages",
                "rule_tag": "budget_waste",
                "episode_keys": [k1],
                "quotes": [
                    {"episode": k1, "t": 2, "quote": q1},
                    {"episode": k1, "t": 99, "quote": "invented non-existent quote"},
                ],
            },
        ],
    }

    captured_calls: list[dict] = []

    class FakeModels:
        def generate_content(self, **kwargs):
            captured_calls.append(kwargs)
            part = SimpleNamespace(text=json.dumps(llm_json), function_call=None, thought=False)
            cand = SimpleNamespace(content=SimpleNamespace(parts=[part]), finish_reason="STOP")
            um = SimpleNamespace(
                prompt_token_count=245_000,
                candidates_token_count=920,
                thoughts_token_count=1_850,
                cached_content_token_count=210_000,
            )
            return SimpleNamespace(candidates=[cand], usage_metadata=um, text=json.dumps(llm_json))

    fake_sdk = SimpleNamespace(models=FakeModels())
    monkeypatch.setattr("canary.gemini.sdk.genai_client", lambda timeout_s=None: fake_sdk)

    out_dir = tmp_path / "out_carbon"
    rc = atlas.main(
        [
            "--runs",
            str(runs_dir),
            "--llm",
            "gemini:gemini-4-carbon",
            "--run-id",
            "atlas-carbon-test",
            "--out",
            str(out_dir),
        ]
    )
    assert rc == 0
    assert len(captured_calls) >= 1
    assert captured_calls[0]["model"] == "gemini-4-carbon"

    doc = json.loads((out_dir / "atlas.json").read_text())
    assert doc["model"] == "gemini-4-carbon"
    assert doc["synthetic"] is False
    assert doc["source"] == "llm"
    assert doc["ledger_run_ids"] == ["atlas-carbon-test"]
    assert doc["corpus"]["episodes"] == 2
    assert doc["corpus"]["tokens"] >= 245_000
    assert doc["corpus"]["cached_tokens"] >= 210_000
    assert doc["quote_verification"]["verified_quotes"] == 2
    assert doc["quote_verification"]["total_quotes"] == 3
    assert sum(m["regret_share"] for m in doc["modes"]) <= 1.0001
    assert "\u2014" not in (out_dir / "atlas.json").read_text()
    assert "\u2014" not in (out_dir / "atlas.md").read_text()

    ledger_rows = read_ledger([_isolated_ledger])
    assert len(ledger_rows) == len(captured_calls)
    assert all(r["feature"] == "atlas" and r["model"] == "gemini-4-carbon" for r in ledger_rows)
    assert all(r["run_id"] == "atlas-carbon-test" for r in ledger_rows)


def test_cli_stub_and_dashboard_renders_cleanly(tmp_path, _isolated_ledger):
    out_dir = tmp_path / "results_gemini"
    rc = atlas.main(
        [
            "--runs",
            str(atlas.DEFAULT_RUNS),
            "--max-episodes",
            "8",
            "--llm",
            "stub",
            "--run-id",
            "atlas-stub-smoke",
            "--out",
            str(out_dir),
        ]
    )
    assert rc == 0

    atlas_json_path = out_dir / "atlas.json"
    atlas_md_path = out_dir / "atlas.md"
    assert atlas_json_path.is_file() and atlas_md_path.is_file()

    doc = json.loads(atlas_json_path.read_text())
    for key in (
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
    ):
        assert key in doc

    assert doc["synthetic"] is True
    assert doc["ledger_run_ids"] == ["atlas-stub-smoke"]
    assert doc["corpus"]["episodes"] == 8
    assert doc["corpus"]["tokens"] > 0
    assert len(doc["modes"]) >= 1
    assert doc["quote_verification"]["verified_quotes"] == doc["quote_verification"]["total_quotes"] > 0
    assert doc["quote_verification"]["rate"] == 1.0
    assert doc["agreement"]["rate"] == 1.0
    for mode in doc["modes"]:
        assert (out_dir / mode["chart"]).is_file()

    html_out = out_dir / "dashboard.html"
    assert (
        dashboard.main(
            [
                "--ledger",
                str(_isolated_ledger),
                "--results",
                str(out_dir),
                "--out",
                str(html_out),
            ]
        )
        == 0
    )
    html = html_out.read_text()
    m = re.search(r'<script id="data" type="application/json">(.*?)</script>', html, re.S)
    assert m is not None
    payload = json.loads(m.group(1).replace("<\\/", "</"))
    loaded_atlas = payload["results"]["atlas"]
    assert loaded_atlas is not None
    assert len(loaded_atlas["modes"]) == len(doc["modes"])
    assert all(mode["chart_src"].startswith("data:image/") for mode in loaded_atlas["modes"])
    assert "atlas" in payload["usage"]["totals"]["features"]


def test_custom_stub_client_injection():
    eps = _sample_episodes()
    records = atlas.records_from_episodes(eps)
    _, blocks = atlas.pack_corpus(records)
    k0 = records[0]["key"]
    q0 = next(ln for ln in blocks[k0].splitlines() if ln.startswith("regret t="))
    scripted = StubClient(
        script=[
            {
                "json": {
                    "summary": "Injected stub summary.",
                    "modes": [
                        {
                            "id": "custom-premature",
                            "name": "Custom premature mode",
                            "description": "Custom mode.",
                            "decision": "accuse",
                            "rule_tag": "premature_accusation",
                            "episode_keys": [k0],
                            "quotes": [{"episode": k0, "t": 2, "quote": q0}],
                        }
                    ],
                }
            }
        ]
    )
    doc = atlas.run_atlas(episodes=eps, client=scripted, out_dir=None, render_charts=False)
    assert len(doc["modes"]) == 1
    assert doc["modes"][0]["id"] == "custom-premature"
    assert doc["quote_verification"]["rate"] == 1.0
