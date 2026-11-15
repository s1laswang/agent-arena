from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(REPO_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "scripts"))

from canary.baselines import BASELINES
from canary.eval import make_env, run_episode
from canary.solver.policy import SolverPolicy
import build_v16_paired_table as bpt


def _make_real_episode(tier: str, seed: int, policy_kind: str = "do_nothing") -> dict:
    env = make_env(tier, seed, "template")
    if policy_kind == "solver":
        pol = SolverPolicy()
    else:
        pol = BASELINES[policy_kind](seed=seed)
    res = run_episode(env, pol)
    return {
        "tier": res.tier,
        "seed": int(res.seed),
        "agent": "opencode:google/gemini-4-carbon",
        "score": float(res.score),
        "correct": bool(res.correct),
        "accused": res.accused,
        "final_day": int(res.final_day),
        "end_reason": res.end_reason,
        "steps": [
            {"t": st.t, "day": st.day, "tool": st.tool, "args": st.args, "result": st.result}
            for st in res.steps
        ],
        "meta": {
            "rc": 0,
            "valid": True,
            "wall_s": 120.5,
            "V": float(res.score) if res.correct else None,
        },
    }


def test_cli_defaults_and_template_provider_mapping():
    ap = bpt.build_parser()
    args = ap.parse_args([])
    assert args.tier == "hard"
    assert args.seeds == "0-9"
    assert args.model == "gemini-4-carbon"
    assert args.v16_provider == "social-v2"
    assert args.wall_cap == 3600.0
    assert bpt.template_social_spec("social-v2") == "social-v2-template"
    assert bpt.template_social_spec("v16:v5_full9_cocktail") == "v16-template:v5_full9_cocktail"
    assert bpt.template_social_spec("template") == "template"


def test_data_rule_strictly_rejects_invalid_and_tampered_episodes(tmp_path: Path):
    valid_ep = _make_real_episode("hard", 0, "solver")
    ok_res = bpt.evaluate_episode_data_rule(valid_ep, wall_cap_s=3600.0)
    assert ok_res["ok"] is True
    assert ok_res["reasons"] == []

    timeout_ep = dict(valid_ep, meta=dict(valid_ep["meta"], rc="timeout"))
    r_to = bpt.evaluate_episode_data_rule(timeout_ep, wall_cap_s=3600.0)
    assert r_to["ok"] is False and r_to["timeout"] is True

    wallcap_ep = dict(valid_ep, meta=dict(valid_ep["meta"], wall_s=3600.0))
    r_wc = bpt.evaluate_episode_data_rule(wallcap_ep, wall_cap_s=3600.0)
    assert r_wc["ok"] is False and r_wc["wall_cap"] is True

    invalid_flag_ep = dict(valid_ep, meta=dict(valid_ep["meta"], valid=False))
    r_vf = bpt.evaluate_episode_data_rule(invalid_flag_ep, wall_cap_s=3600.0)
    assert r_vf["ok"] is False and r_vf["valid_false"] is True

    fake_ep = dict(valid_ep, meta=dict(valid_ep["meta"], fake=True))
    assert bpt.evaluate_episode_data_rule(fake_ep, allow_fake=False)["ok"] is False
    assert bpt.evaluate_episode_data_rule(fake_ep, allow_fake=True)["ok"] is True

    bad_wrong_score = dict(valid_ep, correct=False, score=-0.5)
    r_inv = bpt.evaluate_episode_data_rule(bad_wrong_score, wall_cap_s=3600.0)
    assert r_inv["ok"] is False
    assert any("wrong_accusation_score_not_minus_one" in x for x in r_inv["reasons"])

    tr_dir = tmp_path / "transcripts"
    tr_dir.mkdir()
    (tr_dir / "0.txt").write_text("run log\n--- stderr\nTIMEOUT\n", encoding="utf-8")
    r_tr = bpt.evaluate_episode_data_rule(valid_ep, run_dir=tmp_path, wall_cap_s=3600.0)
    assert r_tr["ok"] is False and r_tr["timeout"] is True


def test_replay_verification_detects_tampered_episode(tmp_path: Path):
    ep0 = _make_real_episode("hard", 0, "solver")
    summary_ok, map_ok = bpt.replay_and_verify_episodes({0: ep0})
    assert summary_ok["pass"] is True
    assert summary_ok["verified"] == 1
    assert map_ok[0]["ok"] is True

    tampered = dict(ep0, score=round(float(ep0["score"]) - 0.12, 4))
    summary_bad, map_bad = bpt.replay_and_verify_episodes({0: tampered})
    assert summary_bad["pass"] is False
    assert summary_bad["failed_seeds"] == [0]
    assert map_bad[0]["ok"] is False

    v16_dir = tmp_path / "v16" / "hard-s0"
    v16_dir.mkdir(parents=True)
    (v16_dir / "episodes.jsonl").write_text(json.dumps(tampered) + "\n", encoding="utf-8")
    rc = bpt.main([
        "--seeds", "0-0",
        "--v16-root", str(tmp_path / "v16"),
        "--no-auto-staging",
        "--no-worker-discovery",
        "--bootstrap-resamples", "100",
        "--out-json", str(tmp_path / "out.json"),
        "--out-md", str(tmp_path / "out.md"),
        "--out-gate-md", str(tmp_path / "gate.md"),
    ])
    assert rc == 1


def test_partial_shards_with_higher_v16_state_direction_and_gate_not_met(tmp_path: Path):
    stg = tmp_path / "staging"
    for s in (0, 1):
        s_dir = stg / "v1.6-social-v2-gemini-4-carbon" / "hard" / str(s)
        s_dir.mkdir(parents=True)
        ep = _make_real_episode("hard", s, "solver")
        (s_dir / "episodes.jsonl").write_text(json.dumps(ep) + "\n", encoding="utf-8")

    inv_dir = stg / "invalid" / "v1.6-social-v2-gemini-4-carbon-hard-2-002500-999"
    inv_dir.mkdir(parents=True)
    (inv_dir / "INVALID.txt").write_text("invalid:infra:provider_quota\n", encoding="utf-8")

    out_json = tmp_path / "paired.json"
    out_md = tmp_path / "paired.md"
    out_gate = tmp_path / "gate.md"

    payload = bpt.build_paired_table(
        tier="hard",
        seeds=[0, 1, 2],
        seeds_spec="0-2",
        v16_root=tmp_path / "empty_v16",
        staging_globs=[str(stg)],
        worker_wt_glob=None,
        bootstrap_resamples=200,
        out_json=out_json,
        out_md=out_md,
        out_gate_md=out_gate,
    )

    comp = payload["paired_comparison"]
    sg = comp["ship_gate"]
    assert comp["shared_seeds"] == [0, 1]
    assert comp["n_shared"] == 2
    assert comp["n_planned"] == 3
    assert comp["complete"] is False
    assert sg["gate_met"] is False
    assert sg["ship_gate_pass"] is False
    assert sg["verdict"] == "GATE NOT MET / DO NOT SHIP"
    assert sg["v16_higher_than_v14_on_shared"] is True
    assert "HIGHER for Gemini than v1.4" in sg["shared_direction_statement"]
    assert "gate is NOT met" in sg["shared_direction_statement"]
    assert payload["data_rule"]["v16"]["excluded_seeds"] == [2]

    md_txt = out_md.read_text(encoding="utf-8")
    assert "v1.4 (paired on shared seeds [0, 1])" in md_txt
    assert "Does v1.6 score higher for Gemini than v1.4 on the same seeds? **YES**" in md_txt
    assert "EXCLUDED_INVALID" in md_txt
    assert "YES (+0.050)" in md_txt


def test_complete_shards_pass_when_v16_below_v14_and_fail_when_higher(tmp_path: Path):
    v16_low = tmp_path / "v16_low"
    v16_high = tmp_path / "v16_high"
    for s in (0, 2):
        d_lo = v16_low / f"hard-s{s}"
        d_lo.mkdir(parents=True)
        (d_lo / "episodes.jsonl").write_text(
            json.dumps(_make_real_episode("hard", s, "do_nothing")) + "\n",
            encoding="utf-8",
        )
        d_hi = v16_high / f"hard-s{s}"
        d_hi.mkdir(parents=True)
        (d_hi / "episodes.jsonl").write_text(
            json.dumps(_make_real_episode("hard", s, "solver")) + "\n",
            encoding="utf-8",
        )

    low_payload = bpt.build_paired_table(
        tier="hard",
        seeds=[0, 2],
        seeds_spec="0,2",
        v16_root=v16_low,
        staging_globs=[],
        worker_wt_glob=None,
        bootstrap_resamples=200,
        out_json=None,
        out_md=None,
        out_gate_md=None,
    )
    sg_low = low_payload["paired_comparison"]["ship_gate"]
    assert sg_low["complete"] is True
    assert sg_low["raw_below_v14"] is True
    assert sg_low["v16_higher_than_v14_on_shared"] is False
    assert sg_low["gate_met"] is True
    assert sg_low["ship_gate_pass"] is True
    assert sg_low["verdict"] == "GATE MET / SHIP (PASS)"

    high_payload = bpt.build_paired_table(
        tier="hard",
        seeds=[0, 2],
        seeds_spec="0,2",
        v16_root=v16_high,
        staging_globs=[],
        worker_wt_glob=None,
        bootstrap_resamples=200,
        out_json=None,
        out_md=None,
        out_gate_md=None,
    )
    sg_high = high_payload["paired_comparison"]["ship_gate"]
    assert sg_high["complete"] is True
    assert sg_high["raw_below_v14"] is False
    assert sg_high["v16_higher_than_v14_on_shared"] is True
    assert sg_high["gate_met"] is False
    assert sg_high["ship_gate_pass"] is False
    assert sg_high["verdict"] == "GATE NOT MET / DO NOT SHIP"


def test_multi_variant_discovery_and_payload_hygiene(tmp_path: Path):
    stg = tmp_path / "runs"
    for var_name, kind in (("social-v2", "do_nothing"), ("v5_full9_cocktail", "solver")):
        ep_dir = stg / "opencode" / var_name / "hard"
        ep_dir.mkdir(parents=True)
        ep = _make_real_episode("hard", 0, kind)
        (ep_dir / "episodes.jsonl").write_text(json.dumps(ep) + "\n", encoding="utf-8")

    payload = bpt.build_paired_table(
        tier="hard",
        seeds=[0],
        seeds_spec="0-0",
        v16_root=tmp_path / "empty_v16",
        staging_globs=[str(stg)],
        worker_wt_glob=None,
        bootstrap_resamples=100,
        out_json=None,
        out_md=None,
        out_gate_md=None,
    )
    assert payload["arms"]["v1.6"]["n_valid"] == 1
    assert "v16:v5_full9_cocktail" in payload["extra_variants"]
    assert payload["extra_variants"]["v16:v5_full9_cocktail"]["n_valid"] == 1
    md = bpt.format_paired_table_md(payload)
    assert "v16:v5_full9_cocktail" in md

    with pytest.raises(ValueError, match="forbidden hygiene key"):
        bpt.assert_clean_payload({"mole": "e01"})
    with pytest.raises(ValueError, match="non-finite float"):
        bpt.assert_clean_payload({"x": math.nan})
    with pytest.raises(ValueError, match="secret key pattern"):
        bpt.assert_clean_payload({"note": "AIza" + "A" * 35})


def test_committed_v16_paired_artifacts_and_code_hygiene():
    for py_path in (
        REPO_ROOT / "scripts" / "build_v16_paired_table.py",
        REPO_ROOT / "tests" / "test_v16_paired_table.py",
    ):
        txt = py_path.read_text(encoding="utf-8")
        assert chr(35) not in txt
        assert "\u2014" not in txt and "\u2013" not in txt
        txt.encode("ascii")

    for doc_path in (
        bpt.DEFAULT_OUT_JSON,
        bpt.DEFAULT_OUT_MD,
        bpt.DEFAULT_OUT_GATE_MD,
    ):
        assert doc_path.is_file(), f"missing expected artifact {doc_path}"
        content = doc_path.read_text(encoding="utf-8")
        assert "\u2014" not in content and "\u2013" not in content
        content.encode("ascii")

    data = json.loads(bpt.DEFAULT_OUT_JSON.read_text(encoding="utf-8"))
    bpt.assert_clean_payload(data)
    ref = data["reference_checks"]
    assert ref["solver_exact_match"] is True
    assert ref["solver_replay_verified"] is True
    assert ref["do_nothing_zero"] is True
    assert ref["stop_early_zero"] is True
    assert data["data_rule"]["all_pass"] is True
    assert data["replay_verification"]["all_pass"] is True
    assert data["arms"]["v1.4"]["n_valid"] == 10
    az = data["azure_relayed_30_44"]
    assert az["labelled_non_replay_relayed"] is True
    assert az["gate_met"] is False
    assert az["v16_higher_than_v14_on_n3"] is True
    assert "HIGHER for Gemini than v1.4" in az["plain_statement"]
    assert "gate is NOT met" in az["plain_statement"]
    by_var = {row["variant"]: row for row in az["variants"]}
    assert abs(by_var["v0_v14_control"]["gemini_mean"] - 0.523333) < 1e-5
    assert abs(by_var["v5_full9_cocktail"]["gemini_mean"] - 0.616667) < 1e-5
    assert abs(by_var["v5_full9_cocktail"]["paired_ratio_vs_v14_control"] - 1.178344) < 1e-5
    assert by_var["v5_full9_cocktail"]["v16_higher_than_v14"] is True
    assert by_var["v1_anchoring_authority_confirmation"]["n_valid"] == 1
    assert by_var["v3_grudge_falsemem_misforward"]["n_valid"] == 2

