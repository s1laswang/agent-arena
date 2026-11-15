from __future__ import annotations

import copy
import io
import json
from pathlib import Path
import tokenize
from typing import Any

import pytest

from canary.gemini import lab_client
from canary.gemini.provenance import audit_provenance, scan_file_secrets
from canary.llm import register_script
from scripts import run_chatter_bias_forensics as rcbf

REPO_ROOT = Path(__file__).resolve().parents[1]
EM_DASH = chr(0x2014)
EN_DASH = chr(0x2013)


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _make_synthetic_ablation_dir(ablation_dir: Path) -> Path:
    tx_dir = ablation_dir / "transcripts"
    tx_dir.mkdir(parents=True, exist_ok=True)

    raw_sig = "EvQBCvEBAXLI2nyapw615tSignatureBlob0123456789abcdefXYZ"
    carbon_biased_chat = [
        {"role": "system", "content": "Investigate insider leaks."},
        {"role": "user", "content": "Begin."},
        {
            "role": "assistant",
            "content": "",
            "provider_items": [
                {
                    "role": "model",
                    "parts": [
                        {
                            "thought": True,
                            "text": f"Here's my thought process: Let us search messages{EM_DASH}checking Day 1 chatter.",
                        },
                        {
                            "function_call": {"id": "c1", "name": "search_messages", "args": {"query": " ", "day_from": 1, "day_to": 1}},
                            "thought_signature": raw_sig,
                        },
                    ],
                }
            ],
            "tool_calls": [{"id": "c1", "name": "search_messages", "args": {"query": " ", "day_from": 1, "day_to": 1}}],
        },
        {
            "role": "tool",
            "tool_call_id": "c1",
            "name": "search_messages",
            "content": json.dumps({"ok": False, "data": {}, "error": "invalid arguments"}),
        },
        {
            "role": "assistant",
            "content": "",
            "provider_items": [
                {
                    "role": "model",
                    "parts": [
                        {
                            "thought": True,
                            "text": f"Read rumor message bc1-0 about e00{EN_DASH}verify whether rumor holds.",
                        },
                        {
                            "function_call": {"id": "c2", "name": "read_message", "args": {"id": "bc1-0"}},
                            "thought_signature": "<omitted_signature:512_chars>",
                        },
                    ],
                }
            ],
            "tool_calls": [{"id": "c2", "name": "read_message", "args": {"id": "bc1-0"}}],
        },
        {
            "role": "tool",
            "tool_call_id": "c2",
            "name": "read_message",
            "content": json.dumps(
                {
                    "ok": True,
                    "data": {"message": {"id": "bc1-0", "sender": "e04", "channel": "slack_dm"}},
                    "error": None,
                }
            ),
        },
        {
            "role": "assistant",
            "content": "",
            "provider_items": [
                {
                    "role": "model",
                    "parts": [
                        {"thought": True, "text": "Interviewing rumor target e00 on contacts_outside."},
                        {"function_call": {"id": "c3", "name": "interview", "args": {"employee": "e00", "topic": "contacts_outside"}}},
                    ],
                }
            ],
            "tool_calls": [{"id": "c3", "name": "interview", "args": {"employee": "e00", "topic": "contacts_outside"}}],
        },
        {
            "role": "tool",
            "tool_call_id": "c3",
            "name": "interview",
            "content": json.dumps({"ok": True, "data": {"answer": "Routine external vendor sync."}, "error": None}),
        },
        {
            "role": "assistant",
            "content": "",
            "provider_items": [
                {
                    "role": "model",
                    "parts": [
                        {"thought": True, "text": "Planting singleton canary variants across e00 and e07."},
                        {
                            "function_call": {
                                "id": "c4",
                                "name": "plant_canary",
                                "args": {"doc_title": "Audit plan", "assignment": {"e00": "v1", "e07": "v2"}},
                            }
                        },
                    ],
                }
            ],
            "tool_calls": [
                {
                    "id": "c4",
                    "name": "plant_canary",
                    "args": {"doc_title": "Audit plan", "assignment": {"e00": "v1", "e07": "v2"}},
                }
            ],
        },
        {
            "role": "tool",
            "tool_call_id": "c4",
            "name": "plant_canary",
            "content": json.dumps({"ok": True, "data": {"canary_id": "c1"}, "error": None}),
        },
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [{"id": "c5", "name": "advance_day", "args": {}}],
        },
        {
            "role": "tool",
            "tool_call_id": "c5",
            "name": "advance_day",
            "content": json.dumps({"ok": True, "data": {"closed_day": 1, "day": 2, "V": 0.88}, "error": None}),
        },
        {
            "role": "assistant",
            "content": "",
            "provider_items": [
                {
                    "role": "model",
                    "parts": [
                        {"thought": True, "text": "Checking leak feed for canary c1 variant."},
                        {"function_call": {"id": "c6", "name": "check_leak_feed", "args": {}}},
                    ],
                }
            ],
            "tool_calls": [{"id": "c6", "name": "check_leak_feed", "args": {}}],
        },
        {
            "role": "tool",
            "tool_call_id": "c6",
            "name": "check_leak_feed",
            "content": json.dumps(
                {"ok": True, "data": {"items": [{"doc_id": "c1", "variant": "v2", "surfaced_day": 2}]}, "error": None}
            ),
        },
        {
            "role": "assistant",
            "content": "",
            "provider_items": [
                {
                    "role": "model",
                    "parts": [
                        {"thought": True, "text": "Canary c1 variant v2 proves e07 is the mole, overriding e00 rumor."},
                        {"function_call": {"id": "c7", "name": "accuse", "args": {"employee": "e07"}}},
                    ],
                }
            ],
            "tool_calls": [{"id": "c7", "name": "accuse", "args": {"employee": "e07"}}],
        },
    ]

    carbon_template_chat = [
        {"role": "system", "content": "Investigate insider leaks."},
        {"role": "user", "content": "Begin."},
        {
            "role": "assistant",
            "content": "Planting canary immediately on day 1.",
            "tool_calls": [
                {
                    "id": "t1",
                    "name": "plant_canary",
                    "args": {"doc_title": "Audit plan", "assignment": {"e00": "v1", "e07": "v2"}},
                }
            ],
        },
        {
            "role": "tool",
            "tool_call_id": "t1",
            "name": "plant_canary",
            "content": json.dumps({"ok": True, "data": {"canary_id": "c1"}, "error": None}),
        },
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [{"id": "t2", "name": "advance_day", "args": {}}],
        },
        {
            "role": "tool",
            "tool_call_id": "t2",
            "name": "advance_day",
            "content": json.dumps({"ok": True, "data": {"closed_day": 1, "day": 2, "V": 0.92}, "error": None}),
        },
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [{"id": "t3", "name": "check_leak_feed", "args": {}}],
        },
        {
            "role": "tool",
            "tool_call_id": "t3",
            "name": "check_leak_feed",
            "content": json.dumps(
                {"ok": True, "data": {"items": [{"doc_id": "c1", "variant": "v2", "surfaced_day": 2}]}, "error": None}
            ),
        },
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [{"id": "t4", "name": "accuse", "args": {"employee": "e07"}}],
        },
    ]

    solver_steps = {
        "policy": "solver",
        "seed": 10,
        "tier": "medium",
        "steps": [
            {
                "t": 0,
                "day": 1,
                "tool": "plant_canary",
                "args": {"doc_title": "Plan", "assignment": {"e00": "a", "e07": "b"}},
                "result": {"ok": True, "data": {"canary_id": "c1"}, "error": None},
            },
            {
                "t": 1,
                "day": 2,
                "tool": "check_leak_feed",
                "args": {},
                "result": {"ok": True, "data": {"items": [{"doc_id": "c1", "variant": "b", "surfaced_day": 2}]}, "error": None},
            },
            {
                "t": 2,
                "day": 2,
                "tool": "accuse",
                "args": {"employee": "e07"},
                "result": {"ok": True, "data": {"accused": "e07", "episode_over": True}, "error": None},
            },
        ],
    }

    heuristic_steps = {
        "policy": "obvious_heuristic",
        "seed": 10,
        "tier": "medium",
        "steps": [
            {
                "t": 0,
                "day": 1,
                "tool": "read_access_logs",
                "args": {"day_from": 1, "day_to": 1},
                "result": {"ok": True, "data": {"logs": [{"employee": "e00", "after_hours": True}]}, "error": None},
            },
            {
                "t": 1,
                "day": 2,
                "tool": "accuse",
                "args": {"employee": "e00"},
                "result": {"ok": True, "data": {"accused": "e00", "episode_over": True}, "error": None},
            },
        ],
    }

    _write_json(tx_dir / "carbon_biased_seed10.json", carbon_biased_chat)
    _write_json(tx_dir / "carbon_template_seed10.json", carbon_template_chat)
    _write_json(tx_dir / "solver_biased_seed10.json", {**solver_steps, "world": "biased"})
    _write_json(tx_dir / "solver_template_seed10.json", {**solver_steps, "world": "template"})
    _write_json(tx_dir / "obvious_heuristic_biased_seed10.json", {**heuristic_steps, "world": "biased"})
    _write_json(tx_dir / "obvious_heuristic_template_seed10.json", {**heuristic_steps, "world": "template"})

    comparison = {
        "tier": "medium",
        "seeds": [10],
        "model_id": "gemini-4-carbon",
        "seed_bias_specs": {
            "10": {
                "company": "Halcyon Metrics",
                "seed": 10,
                "bias_spec": {
                    "rumour_target": "e00",
                    "grudge_pair": ["e08", "e02"],
                    "manager_id": "e09",
                    "forwarded_doc_title": "Legal vendor contracts Q1",
                },
            }
        },
        "episodes": [
            {
                "tier": "medium",
                "seed": 10,
                "policy": "carbon",
                "agent_name": "gemini:gemini-4-carbon",
                "world": "biased",
                "score": 0.88,
                "correct": True,
                "accused": "e07",
                "final_day": 2,
                "end_reason": "accused",
                "rumour_target": "e00",
                "transcript_file": "transcripts/carbon_biased_seed10.json",
            },
            {
                "tier": "medium",
                "seed": 10,
                "policy": "carbon",
                "agent_name": "gemini:gemini-4-carbon",
                "world": "template",
                "score": 0.92,
                "correct": True,
                "accused": "e07",
                "final_day": 2,
                "end_reason": "accused",
                "rumour_target": "e00",
                "transcript_file": "transcripts/carbon_template_seed10.json",
            },
            {
                "tier": "medium",
                "seed": 10,
                "policy": "solver",
                "agent_name": "solver",
                "world": "biased",
                "score": 0.95,
                "correct": True,
                "accused": "e07",
                "final_day": 2,
                "end_reason": "accused",
                "rumour_target": "e00",
                "transcript_file": "transcripts/solver_biased_seed10.json",
            },
            {
                "tier": "medium",
                "seed": 10,
                "policy": "solver",
                "agent_name": "solver",
                "world": "template",
                "score": 0.95,
                "correct": True,
                "accused": "e07",
                "final_day": 2,
                "end_reason": "accused",
                "rumour_target": "e00",
                "transcript_file": "transcripts/solver_template_seed10.json",
            },
            {
                "tier": "medium",
                "seed": 10,
                "policy": "obvious_heuristic",
                "agent_name": "obvious_heuristic",
                "world": "biased",
                "score": -1.0,
                "correct": False,
                "accused": "e00",
                "final_day": 2,
                "end_reason": "accused",
                "rumour_target": "e00",
                "transcript_file": "transcripts/obvious_heuristic_biased_seed10.json",
            },
            {
                "tier": "medium",
                "seed": 10,
                "policy": "obvious_heuristic",
                "agent_name": "obvious_heuristic",
                "world": "template",
                "score": -1.0,
                "correct": False,
                "accused": "e00",
                "final_day": 2,
                "end_reason": "accused",
                "rumour_target": "e00",
                "transcript_file": "transcripts/obvious_heuristic_template_seed10.json",
            },
        ],
    }
    _write_json(ablation_dir / "comparison.json", comparison)
    return ablation_dir


def test_collect_and_pack_synthetic_paired_transcripts_strips_signatures_and_dashes(tmp_path: Path) -> None:
    adir = _make_synthetic_ablation_dir(tmp_path / "synthetic_ablation")
    items, det = rcbf.collect_paired_ablation_corpus(ablation_dirs=[adir])
    assert len(items) == 6
    assert det["n_pairs"] == 3

    by_id = {it["episode_id"]: it["metrics"] for it in items}
    cb = by_id["medium:s10:carbon:biased"]
    ct = by_id["medium:s10:carbon:template"]
    hb = by_id["medium:s10:obvious_heuristic:biased"]

    assert cb["true_mole"] == "e07"
    assert cb["framed_decoy"] == "e00"
    assert cb["rumor_target"] == "e00"
    assert cb["read_rumor_message"] is True
    assert cb["rumor_target_interviews"] == 1
    assert cb["rumor_target_action_share"] == 1.0
    assert cb["search_messages_err_calls"] == 1
    assert cb["message_calls_total"] == 2
    assert cb["canary_confirmed_mole"] is True
    assert cb["accused_target_role"] == "true_mole"

    assert ct["read_rumor_message"] is False
    assert ct["rumor_target_interviews"] == 0
    assert hb["accused_target_role"] == "framed_decoy_and_rumor_target"
    assert hb["accused_framed_decoy"] is True
    assert hb["accused_rumor_target"] is True

    corpus_text, blocks, step_lines_by_ep = rcbf.pack_ablation_episodes(items)
    assert EM_DASH not in corpus_text
    assert EN_DASH not in corpus_text
    assert "SignatureBlob" not in corpus_text
    assert "omitted_signature" not in corpus_text

    for eid, block in blocks.items():
        assert f"=== EPISODE {eid} ===" in corpus_text
        lines = step_lines_by_ep[eid]
        assert len(lines) >= 2
        assert lines[0].startswith("[S000] d1 ")
        assert any(" accuse(" in ln for ln in lines)
        for ln in lines:
            assert '"' not in ln
            assert EM_DASH not in ln
            assert EN_DASH not in ln


def test_verify_quote_strict_exact_step_line_checking(tmp_path: Path) -> None:
    adir = _make_synthetic_ablation_dir(tmp_path / "synthetic_ablation")
    items, _ = rcbf.collect_paired_ablation_corpus(ablation_dirs=[adir])
    _, blocks, step_lines_by_ep = rcbf.pack_ablation_episodes(items)

    eid = items[0]["episode_id"]
    other_eid = items[1]["episode_id"]
    valid_line = step_lines_by_ep[eid][1]

    ok = rcbf.verify_quote(eid, valid_line, blocks)
    assert ok["verified"] is True
    assert ok["matched_line"] == valid_line

    bad_ep = rcbf.verify_quote("medium:s99:carbon:biased", valid_line, blocks)
    assert bad_ep["verified"] is False
    assert bad_ep["reason"] == "unknown_episode_id"

    hdr_line = blocks[eid].splitlines()[1]
    bad_hdr = rcbf.verify_quote(eid, hdr_line, blocks)
    assert bad_hdr["verified"] is False
    assert bad_hdr["reason"] == "missing_step_number_marker"

    partial_line = valid_line[:-5]
    bad_partial = rcbf.verify_quote(eid, partial_line, blocks)
    assert bad_partial["verified"] is False
    assert bad_partial["reason"] == "not_exact_full_step_line"

    payload = rcbf.build_stub_forensics_payload(items, step_lines_by_ep)
    bad_payload = copy.deepcopy(payload)
    bad_payload["episode_diagnoses"][0]["trigger_quote"]["episode_id"] = other_eid
    ver = rcbf.verify_forensics_payload(bad_payload, blocks, items)
    assert ver["quote_verification"]["unverified_quotes"] == 1
    assert ver["quote_verification"]["verified_quotes_pct"] < 100.0


def test_repair_retry_recovers_100_pct_verified_quotes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "")
    monkeypatch.setenv("GOOGLE_GENERATIVE_AI_API_KEY", "")
    monkeypatch.setenv("CANARY_GEMINI_LEDGER", str(tmp_path / "ledger.jsonl"))

    adir = _make_synthetic_ablation_dir(tmp_path / "synthetic_ablation")
    out_dir = tmp_path / "out_repair"
    items, _ = rcbf.collect_paired_ablation_corpus(ablation_dirs=[adir])
    _, _, step_lines_by_ep = rcbf.pack_ablation_episodes(items)

    good_payload = rcbf.build_stub_forensics_payload(items, step_lines_by_ep)
    flawed_payload = copy.deepcopy(good_payload)
    flawed_payload["clusters"][0]["quotes"][0]["quote"] = "[S001] d1 read_message(id=bc1-0) -> truncated"

    script_name = "test_chatter_bias_forensics_repair"
    register_script(script_name, [{"json": flawed_payload}, {"json": good_payload}])
    client = lab_client(f"stub:{script_name}", feature=rcbf.FEATURE, run_id="test-chatter-repair")

    res = rcbf.run_chatter_bias_forensics(
        ablation_dirs=[adir],
        out_dir=out_dir,
        model_id="stub",
        stub=True,
        max_repair_retries=2,
        client=client,
    )
    assert res["meta"]["verified_quotes_pct"] == 100.0
    assert res["meta"]["usage"]["calls"] == 2
    assert res["forensics"]["quote_verification"]["unverified_quotes"] == 0


def test_cli_stub_end_to_end_keyless_on_synthetic_transcripts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "")
    monkeypatch.setenv("GOOGLE_GENERATIVE_AI_API_KEY", "")
    monkeypatch.setenv("CANARY_GEMINI_LEDGER", str(tmp_path / "ledger.jsonl"))

    adir = _make_synthetic_ablation_dir(tmp_path / "synthetic_ablation")
    out_dir = tmp_path / "out_stub"

    rc = rcbf.main(["--ablation-dirs", str(adir), "--out", str(out_dir), "--stub"])
    assert rc == 0

    for fname in ("meta.json", "forensics.json", "summary.md"):
        fp = out_dir / fname
        assert fp.is_file() and fp.stat().st_size > 80
        txt = fp.read_text(encoding="utf-8")
        assert EM_DASH not in txt
        assert EN_DASH not in txt
        assert scan_file_secrets(fp, tmp_path) == []

    meta = json.loads((out_dir / "meta.json").read_text(encoding="utf-8"))
    assert meta["role"] == "failure_analyst"
    assert meta["subrole"] == "biased_chatter_decision_forensics"
    assert meta["stub"] is True
    assert meta["n_episodes"] == 6
    assert meta["n_episodes_packed"] == 6
    assert meta["verified_quotes_pct"] == 100.0
    assert meta["usage"]["in"] > 0
    assert meta["usage"]["out"] > 0


def test_committed_chatter_bias_forensics_artifact_provenance_and_quotes() -> None:
    artifact_dir = REPO_ROOT / "results" / "gemini_roles" / "failure_analyst" / "chatter-bias-forensics-carbon"
    if not (artifact_dir / "meta.json").is_file():
        pytest.skip("committed chatter-bias-forensics-carbon artifact not generated yet")

    for fname in ("meta.json", "forensics.json", "summary.md"):
        fp = artifact_dir / fname
        assert fp.is_file() and fp.stat().st_size > 200
        txt = fp.read_text(encoding="utf-8")
        assert EM_DASH not in txt
        assert EN_DASH not in txt
        assert scan_file_secrets(fp, REPO_ROOT) == []

    meta = json.loads((artifact_dir / "meta.json").read_text(encoding="utf-8"))
    assert meta["role"] == "failure_analyst"
    assert meta["subrole"] == "biased_chatter_decision_forensics"
    assert meta["model_id"] == "gemini-4-carbon"
    assert meta["thinking_level"] == "high"
    assert meta["stub"] is False
    assert meta["fake_env"] is False
    assert meta["smoke"] is False
    assert meta["n_episodes"] == 24
    assert meta["n_episodes_packed"] == 24
    assert meta["verified_quotes_pct"] == 100.0
    assert isinstance(meta["key_metric"], str) and len(meta["key_metric"]) > 10
    assert meta["usage"]["in"] > 0
    assert meta["usage"]["out"] > 0
    assert meta["usage"]["thinking"] > 0
    assert meta["usage"]["cost_usd"] > 0.0

    forensics = json.loads((artifact_dir / "forensics.json").read_text(encoding="utf-8"))
    items, _ = rcbf.collect_paired_ablation_corpus(
        ablation_dirs=[REPO_ROOT / p for p in rcbf.DEFAULT_ABLATION_DIRS]
    )
    _, blocks, _ = rcbf.pack_ablation_episodes(items)

    assert len(forensics["episode_diagnoses"]) == len(items)
    assert len(forensics["clusters"]) >= 3

    rechecked = 0
    for cl in forensics["clusters"]:
        for q in cl["quotes"]:
            chk = rcbf.verify_quote(q["episode_id"], q["quote"], blocks)
            assert chk["verified"] is True, f"cluster quote failed verification: {chk}"
            rechecked += 1

    for ed in forensics["episode_diagnoses"]:
        tq = ed["trigger_quote"]
        assert tq["episode_id"] == ed["episode_id"]
        chk = rcbf.verify_quote(tq["episode_id"], tq["quote"], blocks)
        assert chk["verified"] is True, f"episode quote failed verification: {chk}"
        rechecked += 1

    assert rechecked == forensics["quote_verification"]["total_quotes"]
    assert rechecked >= len(items)

    prov = audit_provenance(REPO_ROOT)
    assert prov["secret_leaks"] == []
    fa = prov["roles"]["failure_analyst"]
    assert fa["verified"] is True, f"failure_analyst provenance failed: {fa}"
    assert "results/gemini_roles/failure_analyst/chatter-bias-forensics-carbon" in fa["run_dirs"]


def test_source_and_artifact_hygiene_no_comments_no_dashes_no_secrets() -> None:
    py_targets = [
        REPO_ROOT / "scripts" / "run_chatter_bias_forensics.py",
        REPO_ROOT / "tests" / "test_chatter_bias_forensics.py",
    ]
    for path in py_targets:
        src = path.read_text(encoding="utf-8")
        assert EM_DASH not in src
        assert EN_DASH not in src
        tokens = list(tokenize.generate_tokens(io.StringIO(src).readline))
        comments = [tok for tok in tokens if tok.type == tokenize.COMMENT]
        assert comments == [], f"found comment tokens in {path}: {comments}"
        assert scan_file_secrets(path, REPO_ROOT) == []
