"""Offline and synthetic replay tests for scripts/hint_ablation_audit.py."""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

from canary.env import Env

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts/hint_ablation_audit.py"
JSON_PATH = ROOT / "results/eval_v14/hint_ablation_v14.json"
MD_PATH = ROOT / "docs/reports/hint_ablation_v14_audit.md"


def _load_module():
    spec = importlib.util.spec_from_file_location("hint_ablation_audit", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


audit = _load_module()


def _make_episode(
    tier: str,
    seed: int,
    agent: str,
    actions: list[tuple[str, dict[str, Any]]],
    llm_calls: int = 12,
) -> dict[str, Any]:
    env = Env(tier, seed)
    for tool, args in actions:
        if env.done:
            break
        env.call(tool, args)
    while not env.done:
        env.call("advance_day", {})
    verdict = env.verdict()
    steps = [
        {"t": st.t, "day": st.day, "tool": st.tool, "args": st.args, "result": st.result}
        for st in env._history
    ]
    return {
        "tier": tier,
        "seed": seed,
        "agent": agent,
        "score": verdict["score"],
        "accused": verdict["accused"],
        "correct": verdict["correct"],
        "end_reason": verdict["end_reason"],
        "final_day": verdict["final_day"],
        "steps": steps,
        "meta": {"valid": True, "V": verdict["V"], "usage": {"calls": llm_calls}},
    }


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")


def test_committed_json_and_markdown_offline_verification():
    data = audit.verify_committed_json(JSON_PATH, MD_PATH, ROOT / "data/runs/committed/v1.4")
    assert JSON_PATH.stat().st_size < 80 * 1024
    assert data["replay_verification"]["all_passed"] is True
    assert data["replay_verification"]["ablation_episodes_verified"] == 30
    assert data["replay_verification"]["context_episodes_verified"] == 30
    assert data["replay_verification"]["score_mismatches"] == 0
    assert data["replay_verification"]["errors_or_timeouts"] == 0

    arms = data["arms"]
    assert arms["control"]["n"] == 10
    assert arms["premature_accusation"]["n"] == 10
    assert arms["decoy_chase"]["n"] == 10
    assert arms["control"]["score_mean"] == pytest.approx(0.427, abs=1e-6)
    assert arms["premature_accusation"]["score_mean"] == pytest.approx(0.487, abs=1e-6)
    assert arms["decoy_chase"]["score_mean"] == pytest.approx(0.648, abs=1e-6)
    assert arms["control"]["ev_negative_gamble_count"] == 1
    assert arms["premature_accusation"]["ev_negative_gamble_count"] == 0
    assert arms["decoy_chase"]["ev_negative_gamble_count"] == 0

    vc = data["paired_vs_control"]
    assert vc["premature_accusation"]["score_diff_mean"] == pytest.approx(0.060, abs=1e-6)
    assert vc["decoy_chase"]["score_diff_mean"] == pytest.approx(0.221, abs=1e-6)
    assert len(vc["decoy_chase"]["luck_adjusted_diff_boot_ci95"]) == 2
    assert vc["decoy_chase"]["luck_adjusted_diff_boot_ci95"][0] < vc["decoy_chase"]["luck_adjusted_diff_boot_ci95"][1]

    rc = audit.main(["--check-committed-json"])
    assert rc == 0


def test_check_mode_gracefully_handles_missing_git_ref(monkeypatch, tmp_path: Path, capsys):
    assert audit.git_ablation_available(ROOT, "refs/heads/nonexistent-shallow-ci-ref-000") is False

    monkeypatch.setattr(audit, "git_ref_commit", lambda *_a, **_kw: None)
    rc = audit.main(["--check"])
    captured = capsys.readouterr()
    assert rc == 0
    assert "origin/justSilas-agents2" in captured.out
    assert "shallow clone" in captured.out

    bad_json = tmp_path / "bad_hint_ablation.json"
    payload = json.loads(JSON_PATH.read_text(encoding="utf-8"))
    payload["ablation_episodes"][0]["luck_adjusted"] = 0.999999
    bad_json.write_text(json.dumps(payload), encoding="utf-8")
    rc_bad_json = audit.main(["--check", "--out-json", str(bad_json), "--out-md", str(MD_PATH)])
    err_json = capsys.readouterr().err
    assert rc_bad_json == 1
    assert "luck_adjusted" in err_json

    bad_md = tmp_path / "bad_hint_ablation.md"
    md_txt = MD_PATH.read_text(encoding="utf-8").replace("+0.648 +/- 0.077", "+0.999 +/- 0.077", 1)
    bad_md.write_text(md_txt, encoding="utf-8")
    rc_bad_md = audit.main(["--check", "--out-json", str(JSON_PATH), "--out-md", str(bad_md)])
    err_md = capsys.readouterr().err
    assert rc_bad_md == 1
    assert "render_markdown" in err_md

    rc_missing_v14 = audit.main(["--check", "--committed-v14-dir", str(tmp_path / "missing_v14")])
    err_v14 = capsys.readouterr().err
    assert rc_missing_v14 == 1
    assert "missing committed v1.4" in err_v14


def test_synthetic_ablate_dir_end_to_end_and_tamper_detection(tmp_path: Path):
    ablate_dir = tmp_path / "ablate"
    v14_dir = tmp_path / "committed_v14"
    seeds = [0, 1]

    ctrl_eps: list[dict[str, Any]] = []
    prem_eps: list[dict[str, Any]] = []
    decoy_eps: list[dict[str, Any]] = []
    sol_eps: list[dict[str, Any]] = []
    inp_eps: list[dict[str, Any]] = []
    opc_eps: list[dict[str, Any]] = []

    for seed in seeds:
        probe = Env("hard", seed)
        mole = probe._world.mole
        decoy = probe._world.decoy
        assert decoy is not None
        innocent = next(e for e in probe._ids if e not in {mole, decoy})

        ctrl_actions: list[tuple[str, dict[str, Any]]] = [
            ("list_employees", {}),
            ("status", {}),
            ("interview", {"employee": decoy, "topic": "workload"}),
            ("interview", {"employee": mole, "topic": "workload"}),
            ("accuse", {"employee": innocent if seed == 0 else mole}),
        ]
        prem_actions: list[tuple[str, dict[str, Any]]] = (
            [("list_employees", {}), ("status", {})]
            if seed == 0
            else [
                ("list_employees", {}),
                ("status", {}),
                ("plant_canary", {"doc_title": "Trap", "assignment": {mole: "A", innocent: "B"}}),
                ("accuse", {"employee": mole}),
            ]
        )
        decoy_actions: list[tuple[str, dict[str, Any]]] = [
            ("list_employees", {}),
            ("status", {}),
            ("plant_canary", {"doc_title": "TrapD1", "assignment": {mole: "A", innocent: "B", decoy: "C"}}),
            ("advance_day", {}),
            ("accuse", {"employee": mole}),
        ]

        ctrl_eps.append(_make_episode("hard", seed, "gemini:gemini-4-carbon", ctrl_actions, llm_calls=20))
        prem_eps.append(_make_episode("hard", seed, "gemini:gemini-4-carbon", prem_actions, llm_calls=15))
        decoy_eps.append(_make_episode("hard", seed, "gemini:gemini-4-carbon", decoy_actions, llm_calls=10))
        sol_eps.append(_make_episode("hard", seed, "solver", decoy_actions, llm_calls=0))
        inp_eps.append(_make_episode("hard", seed, "gemini:gemini-4-carbon", ctrl_actions, llm_calls=20))
        opc_eps.append(_make_episode("hard", seed, "opencode:google/gemini-4-carbon", ctrl_actions, llm_calls=22))

    for arm, eps, hint in [
        ("control", ctrl_eps, None),
        ("premature_accusation", prem_eps, "premature_accusation"),
        ("decoy_chase", decoy_eps, "decoy_chase"),
    ]:
        _write_jsonl(ablate_dir / arm / "episodes.jsonl", eps)
        (ablate_dir / arm / "meta.json").write_text(
            json.dumps({"arm": arm, "hint": hint, "hint_set": "v2", "usage": {"calls": 30}}),
            encoding="utf-8",
        )

    _write_jsonl(v14_dir / "reference/solver-hard-synth/episodes.jsonl", sol_eps)
    _write_jsonl(v14_dir / "inproc-gemini-4-carbon/hard/episodes.jsonl", inp_eps)
    _write_jsonl(v14_dir / "opencode-gemini-4-carbon/hard/episodes.jsonl", opc_eps)

    out_json = tmp_path / "out/hint_ablation_v14.json"
    out_md = tmp_path / "out/hint_ablation_v14_audit.md"

    rc = audit.main([
        "--ablate-dir", str(ablate_dir),
        "--committed-v14-dir", str(v14_dir),
        "--seeds", "0-1",
        "--bootstrap", "200",
        "--out-json", str(out_json),
        "--out-md", str(out_md),
    ])
    assert rc == 0
    assert out_json.is_file() and out_md.is_file()

    synth = json.loads(out_json.read_text(encoding="utf-8"))
    assert synth["arms"]["control"]["decoy_interview_share_pooled"] == pytest.approx(0.5, abs=1e-6)
    assert synth["arms"]["control"]["ev_negative_gamble_count"] == 2
    assert synth["arms"]["premature_accusation"]["abstention_rate"] == pytest.approx(0.5, abs=1e-6)
    assert synth["arms"]["decoy_chase"]["day1_canary_count"] == 2

    rc_check = audit.main([
        "--check",
        "--ablate-dir", str(ablate_dir),
        "--committed-v14-dir", str(v14_dir),
        "--seeds", "0-1",
        "--bootstrap", "200",
        "--out-json", str(out_json),
        "--out-md", str(out_md),
    ])
    assert rc_check == 0

    tampered = json.loads(out_json.read_text(encoding="utf-8"))
    tampered["arms"]["control"]["score_mean"] = 0.999
    out_json.write_text(json.dumps(tampered), encoding="utf-8")
    with pytest.raises(ValueError, match="aggregate mismatch"):
        audit.verify_committed_json(out_json, out_md, v14_dir)

    bad_ep = dict(ctrl_eps[0], score=0.77)
    with pytest.raises(ValueError, match="replay score mismatch"):
        audit.audit_episode_replay("control", bad_ep, "hard")


def test_git_ref_subset_matches_committed_when_ref_present():
    if audit.git_ref_commit(ROOT, audit.DEFAULT_GIT_REF) is None:
        return
    sub = audit.extract_and_compute(seeds=[3, 6], b_resamples=100)
    committed = json.loads(JSON_PATH.read_text(encoding="utf-8"))
    comm_map = {(r["group"], r["seed"]): r for r in committed["ablation_episodes"]}
    for r in sub["ablation_episodes"]:
        assert audit.approx_equal(r, comm_map[(r["group"], r["seed"])])


def test_style_hygiene_no_hash_comments_or_unicode_dashes():
    hash_ch = chr(35)
    for py_path in (SCRIPT_PATH, Path(__file__)):
        txt = py_path.read_text(encoding="utf-8")
        assert hash_ch not in txt, f"unexpected hash character in {py_path}"
        assert "\u2014" not in txt and "\u2013" not in txt

    for doc_path in (JSON_PATH, MD_PATH):
        txt = doc_path.read_text(encoding="utf-8")
        assert "\u2014" not in txt and "\u2013" not in txt
