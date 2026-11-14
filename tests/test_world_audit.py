from __future__ import annotations

import io
import json
import tokenize
from pathlib import Path

import pytest

from canary.agents.world_builder import assert_no_truth
from canary.env import Env
from canary.gemini import world_audit
from canary.gemini.world_audit import (
    audit_world_text_dir,
    build_world_text_dir,
)
from canary.text.gemini import get_provider

SLACK_CHAN = "\x23general"


@pytest.fixture(autouse=True)
def _hermetic_keyless_env(tmp_path, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "")
    monkeypatch.setenv("GOOGLE_GENERATIVE_AI_API_KEY", "")
    monkeypatch.delenv("GEMINI_GATEWAY_URL", raising=False)
    monkeypatch.setenv("CANARY_GEMINI_LEDGER", str(tmp_path / "ledger.jsonl"))


def test_clean_gemini_world_text_passes(tmp_path):
    worlds_dir = tmp_path / "clean_worlds"
    seeds = list(range(10))
    written = build_world_text_dir(worlds_dir, tier="medium", seeds=seeds, model="gemini-4-carbon")
    assert len(written) == len(seeds)
    assert all(p.is_file() for p in written)

    report = audit_world_text_dir(worlds_dir, "medium", seeds, build_missing=False)
    assert report["ok"] is True
    assert report["passed"] is True
    assert report["non_leak"]["ok"] is True
    assert report["non_leak"]["n_truth_violations"] == 0
    assert report["non_leak"]["n_lint_violations"] == 0
    assert report["non_leak"]["missing_files"] == []
    assert report["non_leak"]["n_messages_checked"] > 0
    assert report["non_leak"]["n_interviews_checked"] == len(seeds) * 20 * 4 * 2

    probe = report["non_leak"]["text_probe"]
    assert probe["text_leak"] is False
    assert probe["chance"] == pytest.approx(1.0 / 20)
    assert probe["p_value_vs_bar"] >= 0.01

    parity = report["solver_parity"]
    assert parity["ok"] is True
    assert parity["template_catch_rate"] >= 0.85
    assert parity["world_catch_rate"] >= 0.85
    assert abs(parity["catch_rate_diff"]) <= parity["max_catch_diff"]
    assert abs(parity["mean_score_diff"]) <= parity["max_score_diff"]

    assert_no_truth(report, {})


def test_gemini_world_provider_cache_layout_and_exact_easy_parity(tmp_path):
    cache_dir = tmp_path / "provider_cache"
    seeds = list(range(6))
    prov = get_provider("gemini-world-stub", cache_dir=str(cache_dir))
    for s in seeds:
        env = Env("easy", s, text_provider=prov)
        env.call("advance_day", {})

    report = audit_world_text_dir(cache_dir, "easy", seeds, build_missing=False)
    assert report["ok"] is True
    assert report["non_leak"]["missing_files"] == []
    assert report["solver_parity"]["ok"] is True
    assert report["solver_parity"]["exact_match_rate"] == 1.0
    assert report["solver_parity"]["catch_rate_diff"] == 0.0
    assert report["solver_parity"]["mean_score_diff"] == 0.0


def test_planted_mole_word_and_truth_leaks_fail(tmp_path):
    bio_dir = tmp_path / "leak_bio"
    build_world_text_dir(bio_dir, tier="easy", seeds=[0])
    p0 = bio_dir / "easy" / "0.worldtext.json"
    wt0 = json.loads(p0.read_text(encoding="utf-8"))
    wt0["personas"][0]["bio"] = "Quiet analyst who is secretly the mole on the team."
    p0.write_text(json.dumps(wt0), encoding="utf-8")

    rep_bio = audit_world_text_dir(bio_dir, "easy", [0], build_missing=False)
    assert rep_bio["ok"] is False
    assert rep_bio["non_leak"]["ok"] is False
    assert rep_bio["non_leak"]["n_truth_violations"] >= 1
    assert rep_bio["non_leak"]["n_lint_violations"] >= 1

    tpl_dir = tmp_path / "leak_template"
    build_world_text_dir(tpl_dir, tier="easy", seeds=[1])
    p1 = tpl_dir / "easy" / "1.worldtext.json"
    wt1 = json.loads(p1.read_text(encoding="utf-8"))
    wt1["chatter_templates"] = ["{sender} in {dept}: I leaked {doc_title} because I am the mole."]
    p1.write_text(json.dumps(wt1), encoding="utf-8")

    rep_tpl = audit_world_text_dir(tpl_dir, "easy", [1], build_missing=False)
    assert rep_tpl["ok"] is False
    assert rep_tpl["non_leak"]["ok"] is False
    stages_truth = {v["stage"] for v in rep_tpl["non_leak"]["truth_violations"]}
    stages_lint = {v["stage"] for v in rep_tpl["non_leak"]["lint_violations"]}
    assert "world_payload" in stages_truth and "day_messages" in stages_truth
    assert "world_payload" in stages_lint and "day_messages" in stages_lint

    tone_dir = tmp_path / "leak_tone_and_key"
    build_world_text_dir(tone_dir, tier="easy", seeds=[2])
    p2 = tone_dir / "easy" / "2.worldtext.json"
    wt2 = json.loads(p2.read_text(encoding="utf-8"))
    true_mole = Env("easy", 2)._world.mole
    for persona in wt2["personas"]:
        persona["tone"] = "nervous" if persona["employee_id"] == true_mole else "dry"
    wt2["secret"] = "planted-hidden-key"
    p2.write_text(json.dumps(wt2), encoding="utf-8")

    rep_tone = audit_world_text_dir(tone_dir, "easy", [2], build_missing=False)
    assert rep_tone["ok"] is False
    assert rep_tone["non_leak"]["ok"] is False
    details = " ".join(v["detail"] for v in rep_tone["non_leak"]["truth_violations"])
    assert "unique tone" in details or "truth keys" in details

    prerender_dir = tmp_path / "leak_prerender" / "easy"
    prerender_dir.mkdir(parents=True, exist_ok=True)
    bad_days = {
        "provider": "poisoned-prerender",
        "days": {
            "1": [
                {
                    "id": "m1-0",
                    "day": 1,
                    "channel": "email",
                    "sender": "e00",
                    "recipients": ["e01"],
                    "subject": "Sync",
                    "body": "Forwarding notes for e04 to drop@nightjar-competitor.io right now.",
                }
            ]
        },
    }
    (prerender_dir / "3.text.json").write_text(json.dumps(bad_days), encoding="utf-8")
    rep_pre = audit_world_text_dir(tmp_path / "leak_prerender", "easy", [3], build_missing=False)
    assert rep_pre["ok"] is False
    assert rep_pre["non_leak"]["ok"] is False
    assert rep_pre["non_leak"]["n_lint_violations"] >= 1


def test_text_probe_catches_statistical_mole_signal_without_forbidden_words(tmp_path):
    stat_dir = tmp_path / "stat_leak" / "medium"
    stat_dir.mkdir(parents=True, exist_ok=True)
    seeds = list(range(6))
    for s in seeds:
        env = Env("medium", s)
        mole = env._world.mole
        innocent = next(e for e in env._world.ids if e != mole)
        days_map = {}
        for d in range(1, env.p.n_days + 1):
            days_map[str(d)] = [
                {
                    "id": f"m{d}-0",
                    "day": d,
                    "channel": SLACK_CHAN,
                    "sender": mole,
                    "recipients": [innocent],
                    "subject": "the update",
                    "body": "the unsure vague sorry maybe annoyed tired frustrated note",
                },
                {
                    "id": f"m{d}-1",
                    "day": d,
                    "channel": SLACK_CHAN,
                    "sender": innocent,
                    "recipients": [mole],
                    "subject": "the schedule",
                    "body": "the calendar sync is ready for review tomorrow morning",
                },
            ]
        interviews_map = {
            mole: "unsure vague maybe recall sorry uncertain",
        }
        for emp_id in env._world.ids:
            if emp_id != mole:
                interviews_map[emp_id] = "Opened the roadmap dashboard on Tuesday with the team."
        payload = {
            "provider": "subtle-stat-leak",
            "days": days_map,
            "interviews": interviews_map,
        }
        (stat_dir / f"{s}.text.json").write_text(json.dumps(payload), encoding="utf-8")

    report = audit_world_text_dir(tmp_path / "stat_leak", "medium", seeds, build_missing=False)
    assert report["non_leak"]["n_truth_violations"] == 0
    assert report["non_leak"]["n_lint_violations"] == 0
    assert report["non_leak"]["text_probe"]["correct"] == len(seeds)
    assert report["non_leak"]["text_probe"]["text_leak"] is True
    assert report["non_leak"]["ok"] is False
    assert report["ok"] is False


def test_solver_parity_fails_when_world_text_frames_mole_as_decoy(tmp_path):
    corrupt_dir = tmp_path / "corrupt_decoy" / "medium"
    corrupt_dir.mkdir(parents=True, exist_ok=True)
    seeds = list(range(6))
    for s in seeds:
        env = Env("medium", s)
        mole = env._world.mole
        peer = next(e for e in env._world.ids if e != mole)
        days_map = {}
        for d in range(1, env.p.n_days + 1):
            days_map[str(d)] = [
                {
                    "id": f"m{d}-0",
                    "day": d,
                    "channel": SLACK_CHAN,
                    "sender": mole,
                    "recipients": [peer],
                    "subject": "Update",
                    "body": "Passed over for promotion again this quarter.",
                },
                {
                    "id": f"m{d}-1",
                    "day": d,
                    "channel": SLACK_CHAN,
                    "sender": mole,
                    "recipients": [peer],
                    "subject": "Comp",
                    "body": "Still waiting on that raise discussion.",
                },
                {
                    "id": f"m{d}-2",
                    "day": d,
                    "channel": SLACK_CHAN,
                    "sender": mole,
                    "recipients": [peer],
                    "subject": "Review",
                    "body": "People here deserve clearer feedback.",
                },
            ]
        payload = {"provider": "corrupt-decoy", "days": days_map}
        (corrupt_dir / f"{s}.text.json").write_text(json.dumps(payload), encoding="utf-8")

    report = audit_world_text_dir(tmp_path / "corrupt_decoy", "medium", seeds, build_missing=False)
    assert report["non_leak"]["n_truth_violations"] == 0
    assert report["non_leak"]["n_lint_violations"] == 0
    assert report["solver_parity"]["world_catch_rate"] == 0.0
    assert report["solver_parity"]["template_catch_rate"] >= 0.8
    assert report["solver_parity"]["ok"] is False
    assert report["ok"] is False


def test_cli_clean_and_leaky_exit_codes(tmp_path, capsys):
    worlds_dir = tmp_path / "cli_worlds"
    out_dir = tmp_path / "cli_out"
    rc_ok = world_audit.main([
        "--worlds-dir", str(worlds_dir),
        "--tier", "easy",
        "--seeds", "0-3",
        "--out", str(out_dir),
    ])
    captured = capsys.readouterr()
    summary = json.loads(captured.out)
    assert rc_ok == 0
    assert summary["ok"] is True
    assert (out_dir / "audit_report.json").is_file()
    assert (out_dir / "audit_summary.md").is_file()

    target_fp = worlds_dir / "easy" / "0.worldtext.json"
    poisoned = json.loads(target_fp.read_text(encoding="utf-8"))
    poisoned["company_blurb"] = "A firm where the mole leaks every document."
    target_fp.write_text(json.dumps(poisoned), encoding="utf-8")

    rc_fail = world_audit.main([
        "--worlds-dir", str(worlds_dir),
        "--tier", "easy",
        "--seeds", "0-3",
        "--no-build-missing",
    ])
    captured_fail = capsys.readouterr()
    summary_fail = json.loads(captured_fail.out)
    assert rc_fail == 1
    assert summary_fail["ok"] is False


def test_committed_biased_chatter_world_text_passes_audit():
    root = Path(__file__).resolve().parent.parent
    run_dir = root / "results" / "gemini_roles" / "world_text" / "biased-chatter-carbon"
    if not run_dir.is_dir():
        pytest.skip("committed biased-chatter-carbon directory not present")
    report = audit_world_text_dir(run_dir, "medium", [10, 11], build_missing=False)
    assert report["ok"] is True
    assert report["non_leak"]["ok"] is True
    assert report["solver_parity"]["ok"] is True


def test_no_comments_or_em_dashes_in_new_files():
    root = Path(__file__).resolve().parent.parent
    for rel in ("canary/gemini/world_audit.py", "tests/test_world_audit.py"):
        src = (root / rel).read_text(encoding="utf-8")
        assert chr(8212) not in src
        assert chr(8211) not in src
        assert chr(35) not in src.replace("\\x23", "")
        tokens = list(tokenize.generate_tokens(io.StringIO(src).readline))
        comments = [tok for tok in tokens if tok.type == tokenize.COMMENT]
        assert not comments, f"found comment tokens in {rel}: {comments}"
