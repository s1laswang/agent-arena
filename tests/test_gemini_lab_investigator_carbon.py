from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
import shutil
import tokenize

import pytest

from canary.env import Env
from canary.eval import run_episode
from canary.gemini import investigator_carbon as ic
from canary.solver.policy import SolverPolicy

ROOT = Path(__file__).resolve().parents[1]
ROLE_ROOT = ROOT / ic.DEFAULT_ROLE_DIR
DOC_PATH = ROOT / ic.DEFAULT_DOC_PATH

BASELINE_FRONTIER_RUNS = frozenset({
    "easy-0-3",
    "medium-0-1",
    "medium-2-3",
    "medium-4-5",
    "medium-6-7",
    "medium-8-9",
    "medium-11",
    "hard-0",
    "hard-1",
    "hard-2",
    "hard-3",
    "hard-4",
    "hard-5",
    "hard-6",
    "hard-7",
    "hard-8",
    "hard-9",
    "hard-10",
    "hard-11",
    "hard-12",
    "hard-13",
    "hard-14",
    "hard-17",
    "hard-18",
    "hard-19",
})

BASELINE_ABLATION_RUNS = frozenset({
    "hint-ablation-carbon-med01",
    "thinking-ladder-carbon-hard0",
    "thinking-ladder-carbon-med01",
})

EXPECTED_WAVE1_RUNS = BASELINE_FRONTIER_RUNS | BASELINE_ABLATION_RUNS


@pytest.fixture(autouse=True)
def _keyless_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "")
    monkeypatch.setenv("GOOGLE_GENERATIVE_AI_API_KEY", "")
    monkeypatch.setenv("GOOGLE_API_KEY", "")
    monkeypatch.delenv("GEMINI_GATEWAY_URL", raising=False)


@pytest.fixture(scope="module")
def suite_report() -> dict[str, object]:
    return ic.audit_investigator_suite(ROOT)


def test_source_files_have_zero_comments_hashes_dashes_or_secrets() -> None:
    for rel in ("canary/gemini/investigator_carbon.py", "tests/test_gemini_lab_investigator_carbon.py"):
        src = (ROOT / rel).read_text(encoding="utf-8")
        assert chr(35) not in src
        for d in ic.FORBIDDEN_DASHES:
            assert d not in src
        tokens = list(tokenize.generate_tokens(io.StringIO(src).readline))
        comments = [t for t in tokens if t.type == tokenize.COMMENT]
        assert comments == []
        assert ic.scan_text_hygiene(src) == []


def test_suite_all_folders_verified_replay_and_hygiene_clean(suite_report: dict[str, object]) -> None:
    assert suite_report["verified"] is True
    assert suite_report["errors"] == []
    assert suite_report["role"] == "investigators"
    assert suite_report["model_id"] == "gemini-4-carbon"
    assert suite_report["tiers_version"] == "v1.4"

    runs = suite_report["runs"]
    assert isinstance(runs, list)
    run_names = {r["run_name"] for r in runs}
    assert len(EXPECTED_WAVE1_RUNS) == 28
    assert EXPECTED_WAVE1_RUNS.issubset(run_names)
    assert all(r["verified"] is True and r["errors"] == [] for r in runs)

    totals = suite_report["totals"]
    assert isinstance(totals, dict)
    assert totals["verified_runs"] >= 28
    assert totals["total_episodes"] >= 41
    assert totals["replay_verified_episodes"] == totals["total_episodes"]
    assert totals["verified_transcripts"] == totals["total_episodes"]
    assert totals["verified_signature_parts"] >= 3560
    assert totals["calls"] >= 3565
    assert totals["tokens_in"] >= 129967004
    assert totals["tokens_out"] >= 1502416
    assert totals["thinking_tokens"] >= 157797
    assert totals["cached_tokens"] >= 120952167
    assert totals["cost_usd_est"] >= 46.72
    assert totals["hygiene_violations"] == 0


def test_paired_solver_comparison_and_bootstrap_cis(suite_report: dict[str, object]) -> None:
    slices = suite_report["frontier_paired_vs_solver"]
    assert isinstance(slices, dict)
    for key in ("easy", "medium", "hard", "medium_plus_hard", "all_tiers"):
        assert key in slices
        st = slices[key]
        assert st["n"] >= 4
        acc_lo, acc_hi = st["accuracy_ci95"]
        assert 0.0 <= acc_lo <= st["accuracy"] <= acc_hi <= 1.0
        r_lo, r_hi = st["frontier_over_solver_ci95"]
        assert r_lo <= st["frontier_over_solver_ratio"] <= r_hi
        d_lo, d_hi = st["paired_diff_boot_ci95"]
        assert d_lo <= st["paired_diff_mean"] <= d_hi
        if st["luck_adjusted_ratio"] is not None and st["luck_adjusted_ratio_ci95"] is not None:
            l_lo, l_hi = st["luck_adjusted_ratio_ci95"]
            assert l_lo <= st["luck_adjusted_ratio"] <= l_hi

    easy = slices["easy"]
    assert easy["n"] >= 4
    expected_easy_solver = [run_episode(Env("easy", s), SolverPolicy()).score for s in range(4)]
    if easy["seeds"] == [0, 1, 2, 3]:
        assert easy["solver_mean_score"] == pytest.approx(sum(expected_easy_solver) / 4.0, abs=1e-6)
        assert easy["mean_score"] == pytest.approx(0.85, abs=1e-6)
        assert easy["accuracy"] == pytest.approx(1.0, abs=1e-6)

    assert slices["medium"]["n"] >= 11
    assert slices["hard"]["n"] >= 18
    assert slices["all_tiers"]["n"] >= 33


def test_thinking_and_hint_ablations_integrity(suite_report: dict[str, object]) -> None:
    thinking = suite_report["thinking_ablations"]
    assert isinstance(thinking, dict)
    runs_by_name = {r["run_name"]: r for r in thinking["runs"]}
    assert "thinking-ladder-carbon-hard0" in runs_by_name
    assert "thinking-ladder-carbon-med01" in runs_by_name

    hard0 = runs_by_name["thinking-ladder-carbon-hard0"]
    assert set(hard0["levels"].keys()) == {"low", "high"}
    assert hard0["levels"]["low"]["mean_score"] == pytest.approx(0.78, abs=1e-6)
    assert hard0["levels"]["high"]["mean_score"] == pytest.approx(0.36, abs=1e-6)
    assert hard0["levels"]["high"]["regret_per_episode"] < hard0["levels"]["low"]["regret_per_episode"]

    med01 = runs_by_name["thinking-ladder-carbon-med01"]
    assert set(med01["levels"].keys()) == {"low", "high"}
    assert med01["levels"]["low"]["mean_score"] == pytest.approx(0.655, abs=1e-6)
    assert med01["levels"]["high"]["mean_score"] == pytest.approx(0.655, abs=1e-6)
    assert med01["levels"]["high"]["regret_per_episode"] < med01["levels"]["low"]["regret_per_episode"]

    med01_meta = json.loads((ROLE_ROOT / "thinking-ladder-carbon-med01" / "meta.json").read_text(encoding="utf-8"))
    assert (
        med01_meta["levels_summary"]["high"]["thinking_tokens_per_episode"]
        > med01_meta["levels_summary"]["low"]["thinking_tokens_per_episode"]
    )

    hints = suite_report["hint_ablations"]
    assert isinstance(hints, list) and len(hints) >= 1
    h0 = next(h for h in hints if h["run_name"] == "hint-ablation-carbon-med01")
    assert h0["hint"] == "premature_accusation,ignored_delay"
    assert h0["hinted"]["n"] == 2
    assert h0["unhinted_same_seeds"] is not None
    assert h0["delta_vs_unhinted"]["regret_per_episode_delta"] < 0.0


def test_transcript_signature_redaction_and_detection() -> None:
    raw_sig = "c2lnbmF0dXJlX3BheWxvYWRfZm9yX3Rlc3Rpbmc="
    expected_sha = hashlib.sha256(raw_sig.encode("utf-8")).hexdigest()
    sample_msgs = [
        {"role": "system", "content": "rules"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [{"id": "call_1", "name": "status", "args": {}}],
            "provider_items": [
                {
                    "role": "model",
                    "parts": [
                        {"thought": True, "text": "Checking status first."},
                        {
                            "function_call": {"id": "call_1", "name": "status", "args": {}},
                            "thought_signature": raw_sig,
                        },
                    ],
                }
            ],
        },
    ]

    unredacted_audit = ic.audit_transcript_data(sample_msgs)
    assert unredacted_audit["valid"] is False
    assert unredacted_audit["unredacted_signatures"] == 1

    redacted_msgs, stats = ic.redact_transcript_signatures(sample_msgs)
    assert stats == {"total_signatures": 1, "redacted_now": 1}
    part = redacted_msgs[1]["provider_items"][0]["parts"][1]
    assert part["thought_signature"] == f"<redacted_thought_signature_chars:{len(raw_sig)}>"
    assert part["thought_signature_sha256"] == expected_sha
    assert part["thought_signature_len"] == len(raw_sig)

    redacted_audit = ic.audit_transcript_data(redacted_msgs)
    assert redacted_audit["valid"] is True
    assert redacted_audit["signature_parts"] == 1
    assert redacted_audit["sha256_parts"] == 1
    assert redacted_audit["thought_parts"] == 1

    missing_sig_msgs = [
        {"role": "assistant", "content": "hi", "provider_items": [{"role": "model", "parts": [{"text": "hi"}]}]}
    ]
    missing_audit = ic.audit_transcript_data(missing_sig_msgs)
    assert missing_audit["valid"] is False
    assert "missing_thought_signatures" in missing_audit["errors"]


def test_synthetic_tampering_and_hygiene_failures_caught(tmp_path: Path) -> None:
    src_run = ROLE_ROOT / "hard-14"
    clean_copy = tmp_path / "roles_carbon" / "investigators" / "hard-14"
    shutil.copytree(src_run, clean_copy)
    ok_res = ic.inspect_investigator_run(clean_copy, tmp_path)
    assert ok_res["verified"] is True

    tampered = tmp_path / "roles_carbon" / "investigators" / "tampered-score"
    shutil.copytree(src_run, tampered)
    ep_path = tampered / "episodes.jsonl"
    ep = json.loads(ep_path.read_text(encoding="utf-8").strip())
    ep["score"] = 0.9999
    ep_path.write_text(json.dumps(ep) + "\n", encoding="utf-8")
    bad_rep = ic.inspect_investigator_run(tampered, tmp_path)
    assert bad_rep["verified"] is False
    assert any(err.startswith("replay_mismatch:") for err in bad_rep["errors"])

    leaked = tmp_path / "roles_carbon" / "investigators" / "secret-leak"
    shutil.copytree(src_run, leaked)
    fake_key = "AI" + "za" + "SyFakeFixtureKey1234567890abcd"
    (leaked / "summary.md").write_text(
        (leaked / "summary.md").read_text(encoding="utf-8") + f"\n{fake_key}\n",
        encoding="utf-8",
    )
    bad_leak = ic.inspect_investigator_run(leaked, tmp_path)
    assert bad_leak["verified"] is False
    assert "hygiene_violation" in bad_leak["errors"]

    stub_dir = tmp_path / "roles_carbon" / "investigators" / "stub-flagged"
    shutil.copytree(src_run, stub_dir)
    meta = json.loads((stub_dir / "meta.json").read_text(encoding="utf-8"))
    meta["stub"] = True
    (stub_dir / "meta.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    bad_stub = ic.inspect_investigator_run(stub_dir, tmp_path)
    assert bad_stub["verified"] is False
    assert "disallowed_flag:stub" in bad_stub["errors"]


def test_cli_strict_json_and_consolidated_doc_clean(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert DOC_PATH.is_file()
    doc_txt = DOC_PATH.read_text(encoding="utf-8")
    assert ic.scan_text_hygiene(doc_txt) == []
    assert "SolverPolicy" in doc_txt
    assert "gemini-4-carbon" in doc_txt

    out_doc = tmp_path / "investigators.md"
    rc = ic.main(["--root", str(ROOT), "--strict", "--json", "--write-doc", str(out_doc)])
    assert rc == 0
    out_json = json.loads(capsys.readouterr().out)
    assert out_json["verified"] is True
    assert out_doc.is_file()
    assert ic.scan_text_hygiene(out_doc.read_text(encoding="utf-8")) == []
