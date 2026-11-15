from __future__ import annotations

import io
import json
from pathlib import Path
import sys
import tokenize
from types import SimpleNamespace
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from canary.env import Env
from canary.gemini import mole_carbon as mc
from canary.mole.dsl import DEFAULT_STRATEGY, MoleDoc, MoleStrategy, MoleView

COMMIT_A = "89e733ce0123456789abcdef0123456789abcdef"
COMMIT_B = "c00d49189d1a4c63495d9111e11b5f13528a5093"


@pytest.fixture(autouse=True)
def _keyless_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in mc.SECRET_ENV_VARS:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.delenv("GEMINI_GATEWAY_URL", raising=False)


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")


def _assert_no_forbidden_dashes(text: str) -> None:
    for bad in mc.FORBIDDEN_DASHES:
        assert bad not in text


def _clean_mole_view() -> MoleView:
    return MoleView(
        day=3,
        docs=(
            MoleDoc(doc_id="c3", title="Board memo draft 3", recipient_count=3, age_days=0),
            MoleDoc(doc_id="d3-1", title="Q3 Engineering roadmap", recipient_count=12, age_days=0),
        ),
        days_since_last_leak=2,
        i_am_restricted=0,
        n_restricted_colleagues=1,
        recent_low_recipient_docs=1,
        peers=("e00", "e01", "e04"),
        restricted_peers=("e04",),
        decoy="e01",
        can_leak=True,
    )


def _valid_base_meta(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "role": "adaptive_mole",
        "subrole": "carbon_vs_carbon_clash",
        "model_id": "gemini-4-carbon",
        "commit": COMMIT_A,
        "timestamp": "2026-11-15T01:00:00Z",
        "tier": "medium",
        "seed": 1,
        "usage": {
            "calls": 8,
            "in": 12000,
            "out": 800,
            "thinking": 1200,
            "cached": 4000,
            "cost_usd": 0.0364,
            "latency_s": 22.5,
        },
    }
    base.update(overrides)
    return base


def test_source_files_zero_comments_hashes_dashes_or_secrets() -> None:
    targets = (
        ROOT / "canary" / "gemini" / "mole_carbon.py",
        ROOT / "tests" / "test_gemini_lab_mole_carbon.py",
    )
    for path in targets:
        src = path.read_text(encoding="utf-8")
        assert chr(35) not in src
        _assert_no_forbidden_dashes(src)
        tokens = list(tokenize.generate_tokens(io.StringIO(src).readline))
        comments = [t for t in tokens if t.type == tokenize.COMMENT]
        assert comments == []
        assert mc.scan_file_secrets(path, ROOT) == []


def test_verify_adaptive_mole_run_accepts_valid_and_pricing_fallback(tmp_path: Path) -> None:
    good_dir = tmp_path / "good-run"
    _write_json(good_dir / "meta.json", _valid_base_meta())
    ok, rec, errs = mc.verify_adaptive_mole_run(good_dir / "meta.json", tmp_path)
    assert ok is True
    assert errs == []
    assert rec is not None
    assert rec["model_id"] == "gemini-4-carbon"
    assert rec["commit"] == COMMIT_A
    assert rec["usage"]["calls"] == 8
    assert rec["usage"]["in"] == 12000
    assert rec["usage"]["out"] == 800
    assert rec["usage"]["thinking"] == 1200
    assert rec["usage"]["total_tokens"] == 14000

    ok_dir, rec_dir, errs_dir = mc.verify_adaptive_mole_run(good_dir, tmp_path)
    assert ok_dir is True
    assert errs_dir == []
    assert rec_dir is not None and rec_dir["name"] == "good-run"

    priced_dir = tmp_path / "priced-fallback-run"
    _write_json(
        priced_dir / "meta.json",
        _valid_base_meta(
            git_sha="abcdef1234",
            commit=None,
            model="gemini-4-carbon",
            model_id=None,
            usage={
                "calls": 2,
                "prompt_tokens": 10000,
                "output_tokens": 1000,
                "thinking_tokens": 500,
                "cached_tokens": 2000,
            },
        ),
    )
    ok_p, rec_p, errs_p = mc.verify_adaptive_mole_run(priced_dir / "meta.json", tmp_path)
    assert ok_p is True
    assert errs_p == []
    assert rec_p is not None
    assert rec_p["usage"]["cost_usd"] > 0.0


def test_verify_adaptive_mole_run_rejects_wrong_model_role_commit_and_usage(tmp_path: Path) -> None:
    missing_dir = tmp_path / "missing-meta"
    missing_dir.mkdir(parents=True)
    ok_m, rec_m, errs_m = mc.verify_adaptive_mole_run(missing_dir / "meta.json", tmp_path)
    assert ok_m is False and rec_m is None
    assert errs_m == ["invalid_meta_json"]

    wrong_role_dir = tmp_path / "wrong-role"
    _write_json(wrong_role_dir / "meta.json", _valid_base_meta(role="investigators"))
    ok_r, _, errs_r = mc.verify_adaptive_mole_run(wrong_role_dir / "meta.json", tmp_path)
    assert ok_r is False
    assert any(e.startswith("invalid_role:") for e in errs_r)

    for folder, bad_model in [
        ("wrong-model-flash", "gemini-3.8-flash"),
        ("wrong-model-gpt", "gpt-4o"),
        ("missing-model", ""),
    ]:
        d = tmp_path / folder
        _write_json(d / "meta.json", _valid_base_meta(model_id=bad_model))
        ok_w, _, errs_w = mc.verify_adaptive_mole_run(d / "meta.json", tmp_path)
        assert ok_w is False
        assert any(e.startswith("wrong_model:") for e in errs_w)

    for folder, bad_commit in [
        ("missing-commit", ""),
        ("short-commit", "abc12"),
        ("nonhex-commit", "zzzzzzzzzzzz"),
    ]:
        d = tmp_path / folder
        _write_json(d / "meta.json", _valid_base_meta(commit=bad_commit))
        ok_c, _, errs_c = mc.verify_adaptive_mole_run(d / "meta.json", tmp_path)
        assert ok_c is False
        assert "invalid_commit" in errs_c

    zero_usage_dir = tmp_path / "zero-usage"
    _write_json(zero_usage_dir / "meta.json", _valid_base_meta(usage={"calls": 1, "in": 1000, "out": 0}))
    ok_u, _, errs_u = mc.verify_adaptive_mole_run(zero_usage_dir / "meta.json", tmp_path)
    assert ok_u is False
    assert "zero_or_invalid_usage" in errs_u


@pytest.mark.parametrize(
    ("folder", "patch"),
    [
        ("flag-fake-env", {"fake_env": True}),
        ("flag-stub", {"stub": True}),
        ("flag-smoke", {"smoke": True}),
        ("flag-synthetic", {"synthetic": "true"}),
        ("provider-stub", {"provider": "stub"}),
        ("agent-stub", {"agent": "stub:mole"}),
        ("llm-stub", {"llm": "stub"}),
    ],
)
def test_verify_adaptive_mole_run_rejects_stub_fake_env_and_smoke(
    tmp_path: Path,
    folder: str,
    patch: dict[str, Any],
) -> None:
    d = tmp_path / folder
    _write_json(d / "meta.json", _valid_base_meta(**patch))
    ok_nl, rec_nl, errs_nl = mc.verify_adaptive_mole_run(d / "meta.json", tmp_path)
    assert ok_nl is False
    assert rec_nl is None
    assert "non_live_run" in errs_nl


def test_verify_adaptive_mole_run_rejects_secret_leaks_and_ignores_superseded(tmp_path: Path) -> None:
    fake_google = "AI" + "za" + "SySyntheticFixtureKey" + ("X" * 16)
    fake_sk = "s" + "k-proj-" + ("Y" * 24)
    fake_oauth = "ya" + "29." + ("Z" * 20)
    fake_ws = "w" + "s-" + ("a1" * 16)
    fake_env_assign = "GEMINI_" + 'API_KEY="real_secret_token_value"\n'

    for folder, secret_text in [
        ("leak-google", f"key={fake_google}\n"),
        ("leak-sk", f"token={fake_sk}\n"),
        ("leak-oauth", f"auth={fake_oauth}\n"),
        ("leak-ws", f"world={fake_ws}\n"),
        ("leak-env", fake_env_assign),
    ]:
        d = tmp_path / folder
        _write_json(d / "meta.json", _valid_base_meta())
        (d / "artifact.txt").write_text(secret_text, encoding="utf-8")
        ok_sec, _, errs_sec = mc.verify_adaptive_mole_run(d / "meta.json", tmp_path)
        assert ok_sec is False
        assert "secret_leak" in errs_sec

    superseded_ok = tmp_path / "superseded-secret-ignored"
    _write_json(superseded_ok / "meta.json", _valid_base_meta())
    (superseded_ok / "superseded").mkdir(parents=True)
    (superseded_ok / "superseded" / "old.txt").write_text(fake_google, encoding="utf-8")
    ok_sup, _, errs_sup = mc.verify_adaptive_mole_run(superseded_ok / "meta.json", tmp_path)
    assert ok_sup is True
    assert errs_sup == []


def test_audit_isolation_accepts_clean_views_and_live_env_snapshots() -> None:
    clean_view = _clean_mole_view()
    single_rep = mc.audit_isolation(clean_view)
    assert single_rep.passed is True
    assert single_rep.views_checked == 1
    assert single_rep.violations == ()

    pair_rep = mc.audit_isolation((clean_view, {"leak": "d3-1", "frame": "e01", "reason": "wide distribution"}))
    assert pair_rep.passed is True
    assert pair_rep.views_checked == 1

    env = Env("medium", 4)
    env.call("plant_canary", {"doc_title": "Trap memo", "assignment": {"e00": "A", "e01": "B", "e02": "C"}})
    live_views = [env._mole_view(1)]
    env.call("advance_day", {})
    live_views.append(env._mole_view(2))
    live_rep = mc.audit_isolation(live_views)
    assert live_rep.passed is True
    assert live_rep.views_checked == 2
    assert live_rep.violations == ()


@pytest.mark.parametrize(
    ("bad_record", "expected_cat"),
    [
        (
            {
                "day": 2,
                "held_docs": [
                    {"doc_id": "c2", "title": "Draft", "recipient_count": 3, "age_days": 0, "is_canary": True}
                ],
                "days_since_last_leak": 1,
                "i_am_restricted": 0,
                "n_restricted_colleagues": 0,
                "recent_low_recipient_docs": 1,
            },
            "is_canary",
        ),
        (
            {
                "day": 2,
                "mole_view": {"day": 2, "held_docs": []},
                "leak": None,
                "frame": None,
                "reason": '{"is_canary": true}',
            },
            "is_canary",
        ),
        (
            {
                "day": 2,
                "held_docs": [
                    {"doc_id": "c2", "title": "Draft", "recipient_count": 3, "age_days": 0, "variant": "A"}
                ],
                "days_since_last_leak": 1,
            },
            "variant",
        ),
        (
            SimpleNamespace(
                day=3,
                docs=(MoleDoc("d3-1", "Plan", 10, 0),),
                days_since_last_leak=1,
                i_am_restricted=0,
                n_restricted_colleagues=0,
                recent_low_recipient_docs=0,
                peers=("e01", "e02"),
                restricted_peers=(),
                decoy="e01",
                can_leak=True,
                posterior={"e00": 0.88, "e01": 0.12},
            ),
            "investigator_belief",
        ),
        (
            {
                "day": 3,
                "mole_view": {"day": 3, "held_docs": []},
                "belief": {"e02": 0.91},
                "leak": None,
            },
            "investigator_belief",
        ),
        (
            {
                "day": 1,
                "held_docs": [{"doc_id": "d1-1", "title": "Plan", "recipient_count": 8, "age_days": 0}],
                "world_secret": "w" + "s-" + ("0123456789abcdef" * 2),
            },
            "secret_key",
        ),
        (
            {
                "day": 1,
                "held_docs": [
                    {
                        "doc_id": "d1-1",
                        "title": "Plan",
                        "recipient_count": 8,
                        "age_days": 0,
                        "recipients": ["e00", "e01"],
                    }
                ],
            },
            "unexpected_field",
        ),
    ],
)
def test_audit_isolation_catches_canary_variant_belief_and_unexpected_fields(
    bad_record: Any,
    expected_cat: str,
) -> None:
    rep = mc.audit_isolation(bad_record)
    assert rep.passed is False
    assert expected_cat in rep.categories


def test_audit_isolation_catches_secrets_without_echoing_secret_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw_google_key = "AI" + "za" + "SyDummyKeyForTest987654321"
    raw_world_secret = "canary-world-secret-xyz987"
    monkeypatch.setenv("CANARY_WORLD_SECRET", raw_world_secret)
    leaked_records = [
        {
            "day": 1,
            "mole_view": {
                "day": 1,
                "held_docs": [
                    {"doc_id": "d1-1", "title": f"Memo {raw_google_key}", "recipient_count": 9, "age_days": 0}
                ],
            },
            "move": {"leak": "d1-1", "frame": None, "reason": f"ctx {raw_world_secret}"},
            "rejected": [],
            "error": None,
        }
    ]
    sec_rep = mc.audit_isolation(leaked_records)
    assert sec_rep.passed is False
    assert "secret_key" in sec_rep.categories
    serialized = json.dumps(sec_rep.to_dict())
    assert raw_google_key not in serialized
    assert raw_world_secret not in serialized


def test_audit_strategy_dsl_isolation_accepts_valid_strategies_and_hof_entries() -> None:
    assert mc.audit_strategy_dsl_isolation(DEFAULT_STRATEGY).passed is True

    valid_hof = {
        "rank": 1,
        "fitness": 0.5612,
        "solver_acc": 0.95,
        "strategy_json": {
            "name": "patient_evader",
            "rules": [
                {
                    "if": [["i_am_restricted", "==", 1], ["days_since_last_leak", "<", 3]],
                    "then": {"leak": "none", "frame": "most_restricted_peer"},
                },
                {
                    "if": ["max_recipient_count >= 6"],
                    "then": {"leak": "most_recipients", "frame": "decoy"},
                },
            ],
            "default": {"leak": "random_seeded", "frame": "random_peer"},
        },
    }
    hof_rep = mc.audit_strategy_dsl_isolation(valid_hof)
    assert hof_rep.passed is True
    assert hof_rep.violations == ()

    valid_obj = MoleStrategy.from_json(valid_hof["strategy_json"])
    assert mc.audit_strategy_dsl_isolation(valid_obj).passed is True


@pytest.mark.parametrize(
    ("bad_strategy", "expected_cat"),
    [
        (
            {"rules": [{"if": [["is_canary", "==", 1]], "then": {"leak": "none", "frame": "decoy"}}]},
            "is_canary",
        ),
        (
            {"rules": [{"if": ["is_canary == 1"], "then": {"leak": "none", "frame": "decoy"}}]},
            "is_canary",
        ),
        (
            {"rules": [{"if": [["variant", "==", 0]], "then": {"leak": "none", "frame": "none"}}]},
            "variant",
        ),
        (
            {"rules": [{"if": [["posterior", ">", 0.5]], "then": {"leak": "none", "frame": "decoy"}}]},
            "investigator_belief",
        ),
        (
            {"rules": [{"if": [["belief", ">", 0.5]], "then": {"leak": "none", "frame": "decoy"}}]},
            "investigator_belief",
        ),
        (
            {"rules": [{"if": [["world_seed", ">", 0]], "then": {"leak": "newest", "frame": "none"}}]},
            "secret_key",
        ),
        (
            {
                "name": "AI" + "za" + "SyStrategyNameLeak1234567890",
                "rules": [],
                "default": {"leak": "newest", "frame": "none"},
            },
            "secret_key",
        ),
        (
            {"rules": [{"if": [["nonexistent_dsl_feature", ">", 1]], "then": {"leak": "newest", "frame": "none"}}]},
            "unexpected_field",
        ),
        (
            {"rules": [{"if": [["day", "~=", 2]], "then": {"leak": "newest", "frame": "none"}}]},
            "unexpected_field",
        ),
        (
            {"rules": [{"if": [["day", ">", 2]], "then": {"leak": "invalid_selector", "frame": "none"}}]},
            "unexpected_field",
        ),
        (
            {
                "rules": [
                    {"if": [["day", ">", i]], "then": {"leak": "newest", "frame": "none"}}
                    for i in range(15)
                ]
            },
            "unexpected_field",
        ),
    ],
)
def test_audit_strategy_dsl_isolation_catches_forbidden_and_invalid_dsl_features(
    bad_strategy: Any,
    expected_cat: str,
) -> None:
    rep = mc.audit_strategy_dsl_isolation(bad_strategy)
    assert rep.passed is False
    assert expected_cat in rep.categories


def test_wilson_and_bootstrap_ci95_and_usage_helpers() -> None:
    assert mc.wilson_ci95(0, 0) == [0.0, 0.0]
    lo, hi = mc.wilson_ci95(9, 10)
    assert 0.55 <= lo <= 0.90 <= hi <= 1.0

    assert mc.bootstrap_mean_ci95([]) == [0.0, 0.0]
    assert mc.bootstrap_mean_ci95([0.42, 0.42]) == [0.42, 0.42]
    b_lo, b_hi = mc.bootstrap_mean_ci95([0.2, 0.5, 0.8])
    assert 0.2 <= b_lo <= 0.5 <= b_hi <= 0.8

    s = mc.clean_str(f"alpha{mc.EM_DASH}beta{mc.EN_DASH}gamma{mc.FIG_DASH}delta{mc.HORIZ_BAR}omega")
    assert s == "alpha-beta-gamma-delta-omega"


def _populate_five_bucket_fixture(root: Path) -> Path:
    role_root = root / mc.DEFAULT_ROLES_REL
    em = mc.EM_DASH
    en = mc.EN_DASH

    clash_specs = [
        ("carbon-vs-carbon-easy-seed0", "easy", 0, 0.83, True, 0.79, True, True, -0.04, 3, 1, 0, 30000, 1200, 3000, 0.15, 25000, 900, 2400, 0.12, 5000, 300, 600, 0.03),
        ("carbon-vs-carbon-med-seed1", "medium", 1, 0.50, True, 0.60, True, True, 0.10, 6, 2, 0, 50000, 1400, 4000, 0.25, 44000, 1000, 3400, 0.21, 6000, 400, 600, 0.04),
        ("carbon-vs-carbon-hard-seed0", "hard", 0, 0.00, False, 0.55, True, True, 0.55, 12, 8, 0, 80000, 2000, 7000, 0.40, 70000, 1500, 5800, 0.34, 10000, 500, 1200, 0.06),
    ]
    for (
        folder,
        tier,
        seed,
        inv_s,
        inv_c,
        sol_s,
        sol_c,
        solvable,
        regret,
        leaks,
        frames,
        errs,
        c_in,
        c_out,
        c_th,
        c_usd,
        i_in,
        i_out,
        i_th,
        i_usd,
        m_in,
        m_out,
        m_th,
        m_usd,
    ) in clash_specs:
        _write_json(
            role_root / folder / "meta.json",
            {
                "role": "adaptive_mole",
                "subrole": "carbon_vs_carbon_clash",
                "model_id": "gemini-4-carbon",
                "tier": tier,
                "seed": seed,
                "episode_count": 2,
                "commit": COMMIT_A,
                "timestamp": "2026-11-14T20:00:00Z",
                "investigator_score": inv_s,
                "investigator_correct": inv_c,
                "solver_score": sol_s,
                "solver_correct": sol_c,
                "solvable": solvable,
                "regret": regret,
                "mole_clash_days": leaks,
                "mole_clash_leaks": leaks,
                "mole_clash_frames": frames,
                "mole_clash_errors": errs,
                "mole_solver_days": 7,
                "mole_solver_leaks": 5,
                "mole_solver_frames": 3,
                "mole_solver_errors": 0,
                "usage": {
                    "calls": 20,
                    "in": c_in,
                    "out": c_out,
                    "thinking": c_th,
                    "cached": 1000,
                    "cost_usd": c_usd,
                    "latency_s": 40.0,
                    "clash_investigator": {
                        "calls": 14,
                        "in": i_in,
                        "out": i_out,
                        "thinking": i_th,
                        "cached": 1000,
                        "cost_usd": i_usd,
                        "latency_s": 30.0,
                    },
                    "clash_mole": {
                        "calls": 6,
                        "in": m_in,
                        "out": m_out,
                        "thinking": m_th,
                        "cached": 0,
                        "cost_usd": m_usd,
                        "latency_s": 10.0,
                    },
                },
            },
        )
        _write_json(
            role_root / folder / "mole_log.json",
            {
                "tier": tier,
                "seed": seed,
                "model_id": "gemini-4-carbon",
                "clash_mole_log": [
                    {"day": 1, "move": {"leak": "d1-1", "frame": "e00"}, "error": None, "rejected": [], "reason": "safe leak"}
                ],
                "solver_mole_log": [
                    {"day": 1, "move": {"leak": None, "frame": "e01"}, "error": None, "rejected": [], "reason": "quiet day"}
                ],
            },
        )

    for folder, tier, seeds, s_scores, d_s_scores, g_d_scores, tin, tout, tth, usd in [
        ("arena-live-carbon-med01", "medium", [0, 1], [0.60, 0.40], [0.70, 0.50], [0.50, 0.40], 20000, 1600, 1800, 0.08),
        ("arena-live-carbon-hard01", "hard", [0, 1], [0.50, 0.70], [0.60, 0.80], [0.60, 0.70], 30000, 2200, 2400, 0.12),
    ]:
        adaptive_eps: list[dict[str, Any]] = []
        default_eps: list[dict[str, Any]] = []
        decisions: list[dict[str, Any]] = []
        for idx, s in enumerate(seeds):
            adaptive_eps.extend(
                [
                    {"tier": tier, "seed": s, "investigator": "solver", "score": s_scores[idx], "correct": True, "final_day": 8},
                    {"tier": tier, "seed": s, "investigator": "grok_tactics", "score": 0.10, "correct": False, "final_day": 12},
                    {"tier": tier, "seed": s, "investigator": "obvious_heuristic", "score": -1.0, "correct": False, "final_day": 3},
                ]
            )
            default_eps.extend(
                [
                    {"tier": tier, "seed": s, "investigator": "solver", "score": d_s_scores[idx], "correct": True, "final_day": 7},
                    {"tier": tier, "seed": s, "investigator": "grok_tactics", "score": g_d_scores[idx], "correct": True, "final_day": 8},
                    {"tier": tier, "seed": s, "investigator": "obvious_heuristic", "score": -1.0, "correct": False, "final_day": 10},
                ]
            )
            decisions.extend(
                [
                    {
                        "tier": tier,
                        "seed": s,
                        "investigator": "solver",
                        "day": 1,
                        "mole_view": {
                            "day": 1,
                            "can_leak": True,
                            "decoy": "e01",
                            "peers": ["e00", "e01", "e02"],
                            "held_docs": [{"doc_id": "d1-1", "title": "Roadmap", "recipient_count": 9, "age_days": 0}],
                        },
                        "leak": "d1-1",
                        "frame": "e01",
                        "reason": f"Wide distribution {em} evade narrow traps {en} frame decoy",
                        "rejected": [],
                        "error": None,
                    },
                    {
                        "tier": tier,
                        "seed": s,
                        "investigator": "solver",
                        "day": 2,
                        "mole_view": {
                            "day": 2,
                            "can_leak": True,
                            "decoy": "e01",
                            "peers": ["e00", "e01", "e02"],
                            "held_docs": [{"doc_id": "c2", "title": "Memo", "recipient_count": 2, "age_days": 0}],
                        },
                        "leak": None,
                        "frame": "e00",
                        "reason": "Hold leak on low recipient doc",
                        "rejected": [],
                        "error": None,
                    },
                ]
            )
        _write_json(
            role_root / folder / "meta.json",
            {
                "role": "adaptive_mole",
                "subrole": "live_arena_mole",
                "model_id": "gemini-4-carbon",
                "tier": tier,
                "seeds": seeds,
                "commit": COMMIT_B,
                "timestamp": "2026-11-14T21:00:00Z",
                "solvability_verified": True,
                "solver_mean": sum(s_scores) / len(s_scores),
                "solver_accuracy": 1.0,
                "grok_tactics_mean": 0.10,
                "heuristic_mean": -1.0,
                "mole_decisions_count": len(decisions),
                "mole_llm_errors": 0,
                "usage": {
                    "calls": len(decisions),
                    "in": tin,
                    "out": tout,
                    "thinking": tth,
                    "cached": 0,
                    "cost_usd": usd,
                    "latency_s": 20.0,
                },
            },
        )
        _write_json(
            role_root / folder / "episodes.json",
            {
                "tier": tier,
                "seeds": seeds,
                "model_id": "gemini-4-carbon",
                "adaptive_mole": adaptive_eps,
                "default_mole": default_eps,
            },
        )
        _write_jsonl(role_root / folder / "mole_decisions.jsonl", decisions)

    _write_json(
        role_root / "mole-forge-carbon-v14" / "meta.json",
        {
            "role": "adaptive_mole",
            "subrole": "mole_forge",
            "model_id": "gemini-4-carbon",
            "tier": "hard",
            "gens": 4,
            "commit": COMMIT_A,
            "timestamp": "2026-11-14T22:00:00Z",
            "n_valid_llm_children": 18,
            "n_invalid_llm_children": 0,
            "best_fitness": 0.4125,
            "default_dev_fitness": 0.245,
            "fresh_solver_accuracy": 0.95,
            "fresh_min_regret": 0.26,
            "default_fresh_min_regret": 0.21,
            "usage": {
                "calls": 18,
                "in": 4500,
                "out": 2000,
                "thinking": 1800,
                "cached": 0,
                "cost_usd": 0.047,
                "latency_s": 32.0,
            },
        },
    )
    _write_json(
        role_root / "mole-forge-carbon-v14" / "generations.json",
        {
            "tier": "hard",
            "generations": [
                {"gen": 0, "hof_best_fitness": 0.31},
                {"gen": 1, "hof_best_fitness": 0.36},
                {"gen": 2, "hof_best_fitness": 0.39},
                {"gen": 3, "hof_best_fitness": 0.4125},
            ],
        },
    )
    _write_json(
        role_root / "mole-forge-carbon-v14" / "holdout_generalization.json",
        {
            "splits": {"confirm_seeds": list(range(5020, 5060))},
            "summary": {
                "top1_confirm_solver_acc": 0.925,
                "top1_confirm_min_regret": 0.248,
                "all_evolved_solvable_confirm": True,
            },
        },
    )
    _write_jsonl(
        role_root / "mole-forge-carbon-v14" / "hall_of_fame.jsonl",
        [
            {
                "rank": 1,
                "fitness": 0.4125,
                "strategy_json": {
                    "rules": [{"if": [["max_recipient_count", ">=", 6]], "then": {"leak": "most_recipients", "frame": "decoy"}}],
                    "default": {"leak": "none", "frame": "random_peer"},
                },
            }
        ],
    )

    _write_json(
        role_root / "paired-solvable-scenarios-carbon" / "meta.json",
        {
            "role": "adaptive_mole",
            "subrole": "paired_skill_designer",
            "model_id": "gemini-4-carbon",
            "tier": "hard",
            "commit": COMMIT_B,
            "timestamp": "2026-11-14T22:30:00Z",
            "n_episodes": 40,
            "n_llm_valid": 6,
            "n_kept": 5,
            "design_solver_mean": 0.689,
            "design_heuristic_mean": -1.0,
            "eval_full_solver_mean": 0.628,
            "eval_heuristic_mean": -1.0,
            "top_scenario_name": f"rotating{em}sprinter",
            "usage": {
                "calls": 2,
                "in": 3200,
                "out": 1800,
                "thinking": 900,
                "cached": 0,
                "cost_usd": 0.0334,
                "latency_s": 14.0,
            },
        },
    )
    _write_json(
        role_root / "paired-solvable-scenarios-carbon" / "skill_gap.json",
        {
            "selected_scenario": {"name": "rotating-sprinter"},
            "headline_comparison": {
                "full_solver": {
                    "baseline_mean_score": 0.61,
                    "designed_mean_score": 0.628,
                    "designed_accuracy": 0.95,
                },
                "heuristic_bisection": {
                    "baseline_mean_score": -1.0,
                    "designed_mean_score": -1.0,
                    "designed_accuracy": 0.0,
                },
            },
        },
    )

    _write_json(
        role_root / "catchability-audit-carbon" / "meta.json",
        {
            "role": "adaptive_mole",
            "subrole": "catchability_isolation_audit",
            "model_id": "gemini-4-carbon",
            "commit": COMMIT_B,
            "timestamp": "2026-11-14T23:00:00Z",
            "n_runs_audited": 7,
            "n_strategies_audited": 10,
            "n_decisions_audited": 14,
            "n_views_checked": 8,
            "isolation_violations": 0,
            "file_secret_leaks": 0,
            "data_hygiene_violations": 0,
            "n_catchability_passed": 9,
            "n_catchability_targets": 10,
            "catchability_compliance_rate": 0.90,
            "live_solvability_compliance_rate": 1.0,
            "forensic_cross_check_agreement_rate": 1.0,
            "zero_privileged_canary_awareness_confirmed": True,
            "usage": {
                "calls": 5,
                "in": 15000,
                "out": 2500,
                "thinking": 2000,
                "cached": 0,
                "cost_usd": 0.075,
                "latency_s": 35.0,
            },
        },
    )

    _write_json(
        role_root / "carbon-vs-carbon-suite" / "meta.json",
        {
            "role": "adaptive_mole",
            "model_id": "gemini-4-carbon",
            "commit": COMMIT_A,
            "usage": {"calls": 9999, "in": 9999999, "out": 999999, "cost_usd": 999.0},
        },
    )
    _write_json(
        role_root / "smoke-ignored-run" / "meta.json",
        {
            "role": "adaptive_mole",
            "model_id": "gemini-4-carbon",
            "commit": COMMIT_A,
            "smoke": True,
            "usage": {"calls": 3, "in": 500, "out": 100, "cost_usd": 0.01},
        },
    )
    return role_root


def test_consolidate_adaptive_mole_end_to_end_all_five_buckets_and_cli(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    role_root = _populate_five_bucket_fixture(tmp_path)

    rc = mc.main(["--root", str(tmp_path)])
    assert rc == 0
    cli_out = json.loads(capsys.readouterr().out)
    assert cli_out["verified_folders"] == 8
    assert cli_out["clash_shards"] == 3
    assert cli_out["live_arena_runs"] == 2
    assert cli_out["mole_forge_runs"] == 1
    assert cli_out["paired_designer_runs"] == 1

    suite_dir = role_root / "carbon-vs-carbon-suite"
    assert not (suite_dir / "meta.json").exists()
    suite_json_path = suite_dir / "suite.json"
    summary_md_path = suite_dir / "summary.md"
    doc_md_path = tmp_path / "docs" / "gemini" / "roles_carbon" / "adaptive_mole.md"
    assert suite_json_path.is_file()
    assert summary_md_path.is_file()
    assert doc_md_path.is_file()

    first_json = suite_json_path.read_text(encoding="utf-8")
    first_summary = summary_md_path.read_text(encoding="utf-8")
    first_doc = doc_md_path.read_text(encoding="utf-8")
    _assert_no_forbidden_dashes(first_json)
    _assert_no_forbidden_dashes(first_summary)
    _assert_no_forbidden_dashes(first_doc)

    assert "arena mode, not the judged v1.4 environment" in first_doc
    assert "arena mode, not the judged v1.4 environment" in first_summary

    payload2 = mc.consolidate_adaptive_mole(root=tmp_path)
    assert suite_json_path.read_text(encoding="utf-8") == first_json
    assert summary_md_path.read_text(encoding="utf-8") == first_summary
    assert doc_md_path.read_text(encoding="utf-8") == first_doc
    assert payload2["environment_scope"] == "arena mode, not the judged v1.4 environment"

    suite = json.loads(first_json)
    assert len(suite["skipped_runs"]) == 1
    assert suite["skipped_runs"][0]["errors"] == ["non_live_run"]

    clash = suite["clash_suite"]
    assert clash["overall"]["n_shards"] == 3
    assert clash["overall"]["n_episodes"] == 6
    assert [(s["tier"], s["seed"]) for s in clash["shards"]] == [
        ("easy", 0),
        ("medium", 1),
        ("hard", 0),
    ]
    assert clash["overall"]["investigator_accuracy"] == pytest.approx(2 / 3, abs=1e-4)
    assert clash["overall"]["solvable_rate"] == pytest.approx(1.0)
    assert clash["overall"]["mole_total_leaks"] == 21
    assert clash["overall"]["mole_total_frames"] == 11
    assert clash["overall"]["mole_total_errors"] == 0
    assert clash["overall"]["usage"]["combined"]["cost_usd"] == pytest.approx(0.80)

    arena = suite["live_arena_suite"]
    assert arena["overall"]["n_runs"] == 2
    assert arena["overall"]["n_adaptive_episodes"] == 12
    assert arena["overall"]["n_default_episodes"] == 12
    assert arena["overall"]["solvable"] is True
    assert arena["overall"]["mole_decisions"] == 8
    assert arena["overall"]["mole_leaks"] == 4
    assert arena["overall"]["mole_frames"] == 8
    assert arena["overall"]["mole_llm_errors"] == 0
    assert arena["overall"]["by_investigator"]["solver"]["delta_mean"] == pytest.approx(-0.10)

    forge = suite["mole_forge_suite"]
    assert forge["overall"]["n_runs"] == 1
    assert forge["overall"]["total_valid_llm_children"] == 18
    assert forge["runs"][0]["best_fitness"] == pytest.approx(0.4125)
    assert forge["runs"][0]["has_holdout_generalization"] is True
    assert forge["runs"][0]["n_confirm_seeds"] == 40
    assert forge["runs"][0]["top1_confirm_solver_acc"] == pytest.approx(0.925)
    assert forge["runs"][0]["all_evolved_solvable_confirm"] is True
    assert forge["runs"][0]["hof_fitness_trajectory"] == [0.31, 0.36, 0.39, 0.4125]

    paired = suite["paired_designer_suite"]
    assert paired["overall"]["n_runs"] == 1
    assert paired["overall"]["total_llm_valid"] == 6
    assert paired["overall"]["total_kept"] == 5
    assert paired["runs"][0]["top_scenario_name"] == "rotating-sprinter"
    assert paired["runs"][0]["has_skill_gap"] is True
    assert paired["runs"][0]["eval_full_solver_mean"] == pytest.approx(0.628)

    catch_audit = suite["catchability_audit"]
    assert isinstance(catch_audit, dict)
    assert catch_audit["n_catchability_passed"] == 9
    assert catch_audit["n_catchability_targets"] == 10
    assert catch_audit["catchability_compliance_rate"] == pytest.approx(0.90)
    assert catch_audit["isolation_violations"] == 0
    assert catch_audit["zero_privileged_canary_awareness_confirmed"] is True

    iso = suite["repo_isolation_audit"]
    assert iso["passed"] is True
    assert iso["decisions_checked"] == 14
    assert iso["views_checked"] == 8
    assert iso["strategies_checked"] == 1
    assert iso["isolation_violations"] == 0
    assert iso["secret_leaks"] == 0

    tot = suite["totals"]
    assert tot["verified_folders"] == 8
    assert tot["calls"] == 60 + 8 + 18 + 2 + 5
    assert tot["in"] == 160000 + 50000 + 4500 + 3200 + 15000
    assert tot["out"] == 4600 + 3800 + 2000 + 1800 + 2500
    assert tot["cost_usd"] == pytest.approx(0.80 + 0.20 + 0.047 + 0.0334 + 0.075)

    for folder in (
        "carbon-vs-carbon-easy-seed0",
        "arena-live-carbon-med01",
        "mole-forge-carbon-v14",
        "paired-solvable-scenarios-carbon",
        "catchability-audit-carbon",
    ):
        rdir = role_root / folder
        meta = json.loads((rdir / "meta.json").read_text(encoding="utf-8"))
        km = mc.build_key_metric(folder, meta, rdir)
        assert isinstance(km, str) and km.strip()
        _assert_no_forbidden_dashes(km)


def test_committed_adaptive_mole_roles_carbon_when_present(tmp_path: Path) -> None:
    roles_dir = ROOT / "results" / "gemini" / "roles_carbon" / "adaptive_mole"
    if not roles_dir.is_dir():
        verified, skipped = mc.discover_adaptive_mole_runs(ROOT, roles_dir, roles_dir / mc.SUITE_DIR_NAME)
        assert verified == []
        assert skipped == []
        empty_payload = mc.consolidate_adaptive_mole(
            root=ROOT,
            out_dir=tmp_path / "empty_suite",
            doc_path=tmp_path / "empty_doc.md",
        )
        assert empty_payload["totals"]["verified_folders"] == 0
        assert (tmp_path / "empty_doc.md").is_file()
        assert "arena mode, not the judged v1.4 environment" in (tmp_path / "empty_doc.md").read_text(encoding="utf-8")
        return

    committed_suite_dir = roles_dir / mc.SUITE_DIR_NAME
    assert not (committed_suite_dir / "meta.json").exists()

    out_tmp = tmp_path / "recomputed_suite"
    doc_tmp = tmp_path / "recomputed_adaptive_mole.md"
    recomputed = mc.consolidate_adaptive_mole(root=ROOT, out_dir=out_tmp, doc_path=doc_tmp)

    assert not (out_tmp / "meta.json").exists()
    assert recomputed["skipped_runs"] == []
    assert recomputed["totals"]["verified_folders"] >= 1
    assert recomputed["repo_isolation_audit"]["passed"] is True
    assert recomputed["repo_isolation_audit"]["isolation_violations"] == 0
    assert recomputed["repo_isolation_audit"]["secret_leaks"] == 0

    rendered_doc = doc_tmp.read_text(encoding="utf-8")
    _assert_no_forbidden_dashes(rendered_doc)
    assert "arena mode, not the judged v1.4 environment" in rendered_doc

    committed_doc = ROOT / mc.DEFAULT_DOC_REL
    if committed_doc.is_file():
        committed_doc_text = committed_doc.read_text(encoding="utf-8")
        _assert_no_forbidden_dashes(committed_doc_text)
        assert "arena mode, not the judged v1.4 environment" in committed_doc_text
        assert mc.scan_file_secrets(committed_doc, ROOT) == []
