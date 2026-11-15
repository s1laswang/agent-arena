from __future__ import annotations

import ast
import copy
import io
import json
from pathlib import Path
import random
import tempfile
import tokenize

import pytest

from canary import rules
from canary.env import Env
from canary.eval import run_episode
from canary.mole.dsl import MoleView
from canary.solver.policy import SolverPolicy
import train.export_mole_dpo as dpo

REPO_ROOT = Path(__file__).resolve().parents[1]
EXPORTER_PATH = REPO_ROOT / "train" / "export_mole_dpo.py"
STATS_PATH = REPO_ROOT / "results" / "moletrain" / "mole_dpo_stats.json"
TEST_PATH = Path(__file__).resolve()


class _FixedSelectorMole:
    def __init__(self, leak: str = "oldest", frame: str = "none"):
        self.leak = leak
        self.frame = frame
        self.days_called: list[int] = []

    def decide(self, view: MoleView, rng: random.Random) -> dict:
        _ = rng
        self.days_called.append(int(view.day))
        from canary.mole.dsl import _select_frame, _select_leak

        return {
            "leak": _select_leak(self.leak, view, rng),
            "frame": _select_frame(self.frame, view, rng),
        }


def _opencode_tmp_root() -> Path:
    preferred = Path("/tmp/opencode")
    if preferred.is_dir():
        return preferred
    return Path(tempfile.gettempdir())


def test_owned_files_hygiene_zero_comments_zero_emdash_and_stats_size():
    hash_ch = chr(35)
    em_dash = chr(0x2014)
    co_author = "co-authored" + "-by"
    forbidden_ml = {"torch", "transformers", "peft", "trl"}

    for py_path in (EXPORTER_PATH, TEST_PATH):
        src = py_path.read_text(encoding="utf-8")
        assert hash_ch not in src, f"forbidden hash char in {py_path}"
        assert em_dash not in src, f"forbidden em-dash in {py_path}"
        assert co_author not in src.lower(), f"forbidden trailer in {py_path}"
        tokens = list(tokenize.generate_tokens(io.StringIO(src).readline))
        comment_tokens = [t for t in tokens if t.type == tokenize.COMMENT]
        assert comment_tokens == []

        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert alias.name.split(".")[0] not in forbidden_ml
            elif isinstance(node, ast.ImportFrom) and node.module:
                assert node.module.split(".")[0] not in forbidden_ml

    assert STATS_PATH.is_file()
    raw_bytes = STATS_PATH.read_bytes()
    assert 0 < len(raw_bytes) <= 50 * 1024
    raw_txt = raw_bytes.decode("utf-8")
    assert em_dash not in raw_txt
    assert co_author not in raw_txt.lower()
    doc = json.loads(raw_txt)
    assert em_dash not in json.dumps(doc, ensure_ascii=False)


def test_seed_leakage_guard_rejects_dev_val_ws3_heldout_and_judge():
    assert dpo.WS3_HELDOUT_MIN == 200_000
    assert dpo.DPO_SEED_START == 125_000
    assert dpo.DPO_SEED_END == 190_000

    for valid_seed in (125_000, 125_059, 150_000, 189_999):
        assert dpo.guard_dpo_seed(valid_seed) == valid_seed
        assert valid_seed in rules.TRAIN_SEEDS
        assert valid_seed < dpo.WS3_HELDOUT_MIN

    for dev_seed in (0, 1, 500, 9_999):
        with pytest.raises(ValueError, match="DEV_SEEDS"):
            dpo.guard_dpo_seed(dev_seed)

    for ws3_or_higher in (
        200_000,
        200_001,
        250_000,
        300_000,
        400_000,
        800_000,
        800_199,
        900_000,
        900_039,
        999_999,
    ):
        with pytest.raises(ValueError):
            dpo.guard_dpo_seed(ws3_or_higher)

    for other_bad in (-5, -1, 10_000, 99_999, 100_000, 124_999, 190_000, 195_000, 199_999):
        with pytest.raises(ValueError):
            dpo.guard_dpo_seed(other_bad)

    for non_int in (True, False, 125_000.0, "125000", None):
        with pytest.raises(ValueError):
            dpo.guard_dpo_seed(non_int)

    for bad_seed in (0, 9_999, 190_000, 200_000, 800_000, 900_000):
        with pytest.raises(ValueError):
            dpo.sample_active_states(1, tiers=("medium",), seed_start=bad_seed)
        with pytest.raises(ValueError):
            dpo.score_candidate_action((bad_seed, 1, "medium", 3, ("newest", "decoy"), None))
        with pytest.raises(ValueError):
            dpo.build_pairs_for_state(
                {"seed": bad_seed, "day": 1, "tier": "medium", "prompt": "p"},
                [],
            )


def test_workspace_jsonl_path_guard():
    with pytest.raises(ValueError, match="workspace"):
        dpo.guard_out_jsonl_path(REPO_ROOT / "forbidden_dump.jsonl")
    with pytest.raises(ValueError, match="workspace"):
        dpo.guard_out_jsonl_path("relative_inside_repo.jsonl")
    with pytest.raises(ValueError):
        dpo.guard_out_jsonl_path(Path.home() / "forbidden_home_dump.jsonl")

    ok_path = _opencode_tmp_root() / "w5_path_guard_probe.jsonl"
    resolved = dpo.guard_out_jsonl_path(ok_path)
    assert resolved == ok_path.resolve()


def test_horizon3_vs_horizon1_override_scoring_and_day_window():
    views_seen: list[MoleView] = []
    base_rec = _FixedSelectorMole(leak="oldest", frame="none")
    run_episode(
        Env("medium", 125_030, mole_strategy=dpo.RecorderMole(base_rec, views_seen)),
        SolverPolicy("medium"),
    )
    assert len(views_seen) >= 5

    base_h1 = _FixedSelectorMole(leak="oldest", frame="none")
    base_h3 = _FixedSelectorMole(leak="oldest", frame="none")
    ov1 = dpo.HorizonOverrideMole(base_h1, start_day=2, horizon=1, action=("none", "decoy"))
    ov3 = dpo.HorizonOverrideMole(base_h3, start_day=2, horizon=3, action=("none", "decoy"))

    rng1 = random.Random(7)
    rng3 = random.Random(7)
    for v in views_seen:
        out1 = ov1.decide(v, rng1)
        out3 = ov3.decide(v, rng3)
        if v.day == 2:
            assert out1["leak"] is None
            assert out3["leak"] is None
        elif v.day in (3, 4):
            assert v.day in base_h1.days_called
            assert v.day not in base_h3.days_called
            assert out3["leak"] is None
        else:
            assert v.day in base_h1.days_called
            assert v.day in base_h3.days_called

    assert 2 not in base_h1.days_called
    assert all(d not in base_h3.days_called for d in (2, 3, 4))

    s_h1_a = dpo.score_candidate_action((125_030, 1, "medium", 1, ("none", "none"), None))
    s_h1_b = dpo.score_candidate_action((125_030, 1, "medium", 1, ("none", "none"), None))
    s_h3 = dpo.score_candidate_action((125_030, 1, "medium", 3, ("none", "none"), None))
    assert s_h1_a == s_h1_b
    assert (
        s_h1_a["regret"] != s_h3["regret"]
        or s_h1_a["solver_score"] != s_h3["solver_score"]
        or s_h1_a["inv"] != s_h3["inv"]
    )

    with pytest.raises(ValueError):
        dpo.HorizonOverrideMole(base_h1, start_day=1, horizon=0, action=("newest", "decoy"))
    with pytest.raises(ValueError):
        dpo.HorizonOverrideMole(base_h1, start_day=1, horizon=3, action=("invalid_leak", "decoy"))


def test_catchability_filter_rejection_categories_and_pair_margin_invariants():
    good_wide = {
        "action": ["most_recipients", "random_peer"],
        "regret": 0.42,
        "solver_score": 0.72,
        "solver_correct": True,
        "inv": {"grok_tactics": 0.30, "heuristic": 0.15, "hinted_heuristic": 0.20},
    }
    silent_cand = {
        "action": ["none", "none"],
        "regret": 0.05,
        "solver_score": 0.40,
        "solver_correct": True,
        "inv": {"grok_tactics": 0.35, "heuristic": 0.10, "hinted_heuristic": 0.25},
    }
    uncatchable_wrong = {
        "action": ["newest", "decoy"],
        "regret": -0.60,
        "solver_score": -1.0,
        "solver_correct": False,
        "inv": {"grok_tactics": -0.40, "heuristic": -1.0, "hinted_heuristic": -0.50},
    }
    uncatchable_low_score = {
        "action": ["oldest", "decoy"],
        "regret": 0.04,
        "solver_score": 0.18,
        "solver_correct": True,
        "inv": {"grok_tactics": 0.14, "heuristic": 0.10, "hinted_heuristic": 0.12},
    }
    neg_regret_cand = {
        "action": ["random_seeded", "most_restricted_peer"],
        "regret": -0.15,
        "solver_score": 0.55,
        "solver_correct": True,
        "inv": {"grok_tactics": 0.70, "heuristic": 0.30, "hinted_heuristic": 0.40},
    }
    canary_trap_cand = {
        "action": ["fewest_recipients", "none"],
        "regret": -0.05,
        "solver_score": 0.60,
        "solver_correct": True,
        "inv": {"grok_tactics": 0.65, "heuristic": 0.40, "hinted_heuristic": 0.58},
    }
    sub_margin_cand = {
        "action": ["most_recipients", "decoy"],
        "regret": 0.36,
        "solver_score": 0.68,
        "solver_correct": True,
        "inv": {"grok_tactics": 0.32, "heuristic": 0.20, "hinted_heuristic": 0.30},
    }

    assert dpo.is_catchable_chosen(good_wide, min_solver_score=0.25) is True
    assert dpo.is_catchable_chosen(silent_cand, min_solver_score=0.25) is False
    assert dpo.is_catchable_chosen(uncatchable_wrong, min_solver_score=0.25) is False
    assert dpo.is_catchable_chosen(uncatchable_low_score, min_solver_score=0.25) is False
    assert dpo.is_catchable_chosen(neg_regret_cand, min_solver_score=0.25) is False

    assert "silent_none" in dpo.classify_rejected_reasons(silent_cand, min_solver_score=0.25)
    assert dpo.primary_rejected_reason(dpo.classify_rejected_reasons(silent_cand)) == "silent_none"

    assert "uncatchable" in dpo.classify_rejected_reasons(uncatchable_wrong, min_solver_score=0.25)
    assert "negative_regret" in dpo.classify_rejected_reasons(uncatchable_wrong, min_solver_score=0.25)
    assert dpo.primary_rejected_reason(dpo.classify_rejected_reasons(uncatchable_wrong)) == "uncatchable"

    assert "uncatchable" in dpo.classify_rejected_reasons(uncatchable_low_score, min_solver_score=0.25)
    assert "negative_regret" in dpo.classify_rejected_reasons(neg_regret_cand, min_solver_score=0.25)
    assert dpo.primary_rejected_reason(dpo.classify_rejected_reasons(neg_regret_cand)) == "negative_regret"

    state = {
        "seed": 125_010,
        "day": 3,
        "tier": "hard",
        "prompt": "Day 3/21\n- doc_a: 3 recipients\n- doc_b: 18 recipients",
        "n_docs": 2,
        "can_leak": True,
        "i_am_restricted": 0,
        "recent_low_recipient_docs": 1,
        "min_recipient_count": 3,
        "max_recipient_count": 18,
        "selector_recipient_counts": {
            "most_recipients": 18,
            "newest": 18,
            "oldest": 9,
            "fewest_recipients": 3,
        },
    }
    scored = [
        good_wide,
        silent_cand,
        uncatchable_wrong,
        uncatchable_low_score,
        neg_regret_cand,
        canary_trap_cand,
        sub_margin_cand,
    ]
    pairs = dpo.build_pairs_for_state(
        state=state,
        scored=scored,
        min_margin=0.10,
        min_solver_score=0.25,
        max_pairs_per_state=6,
        horizon=3,
    )
    assert len(pairs) >= 4
    seen_buckets = {p["bucket"] for p in pairs}
    assert seen_buckets == {
        "anti_silence_collapse",
        "anti_canary_trap",
        "anti_hinted_heuristic",
    }
    seen_reasons = {p["rejected_reason"] for p in pairs}
    assert {"silent_none", "uncatchable", "negative_regret", "narrow_canary_selector"} <= seen_reasons

    for p in pairs:
        assert p["horizon"] == 3
        assert p["chosen_solver_correct"] is True
        assert p["chosen_solver_score"] >= 0.25
        assert p["chosen_regret"] > 0.0
        assert p["chosen_action"][0] != "none"
        assert p["chosen_action"] != p["rejected_action"]
        assert p["rejected_action"] != ["most_recipients", "decoy"]
        assert p["margin"] >= 0.10
        assert p["margin"] == pytest.approx(p["chosen_regret"] - p["rejected_regret"], abs=1e-5)
        ch_parsed = json.loads(p["chosen"])
        rj_parsed = json.loads(p["rejected"])
        assert [ch_parsed["leak"], ch_parsed["frame"]] == p["chosen_action"]
        assert [rj_parsed["leak"], rj_parsed["frame"]] == p["rejected_action"]

    assert (
        dpo.build_pairs_for_state(
            state=state,
            scored=[silent_cand, uncatchable_wrong, neg_regret_cand],
            min_margin=0.10,
            min_solver_score=0.25,
        )
        == []
    )


def test_bootstrap_ci_ordering_and_committed_stats_validation(tmp_path):
    for sample in (
        [],
        [0.42],
        [0.30, 0.30, 0.30, 0.30],
        [-1.65, -0.30, -0.10, -0.05, 0.12],
        [0.10, 0.11, 0.15, 0.22, 0.95, 1.90],
    ):
        dist = dpo.summarize_distribution(sample, boot_seed=42)
        lo_v, hi_v = dist["ci95"]
        assert lo_v <= dist["mean"] <= hi_v
        assert (
            dist["min"]
            <= dist["p10"]
            <= dist["p25"]
            <= dist["median"]
            <= dist["p75"]
            <= dist["p90"]
            <= dist["max"]
        )

    committed = json.loads(STATS_PATH.read_text(encoding="utf-8"))
    summary = dpo.validate_stats_payload(committed)
    assert summary["horizon_days"] == 3
    assert summary["seed_range"] == [125_000, 125_059]
    assert summary["seed_range"][1] < dpo.WS3_HELDOUT_MIN
    assert summary["n_states"] == 60
    assert summary["n_pairs"] >= 150
    assert summary["chosen_solver_acc"] >= 0.90
    assert committed["min_chosen_solver_score"] >= committed["min_solver_score"]
    for req_cat in ("uncatchable", "silent_none", "negative_regret"):
        assert committed["rejected_reason_profile"][req_cat] > 0.0

    hc = committed["horizon_comparison"]
    assert hc["horizon_1"]["pairs_sha256"] != hc["horizon_3"]["pairs_sha256"]
    assert hc["horizon_3"]["bucket_counts"]["anti_canary_trap"] > hc["horizon_1"]["bucket_counts"]["anti_canary_trap"]

    bad_ci = copy.deepcopy(committed)
    bad_ci["margin_distribution"]["ci95"] = [0.60, 0.70]
    with pytest.raises(ValueError, match="lo <= mean <= hi"):
        dpo.validate_stats_payload(bad_ci)

    bad_seed = copy.deepcopy(committed)
    bad_seed["seed_range"] = [125_000, 200_000]
    with pytest.raises(ValueError):
        dpo.validate_stats_payload(bad_seed)

    bad_acc = copy.deepcopy(committed)
    bad_acc["chosen_solver_acc"] = 0.75
    with pytest.raises(ValueError, match="chosen_solver_acc"):
        dpo.validate_stats_payload(bad_acc)

    em_file = tmp_path / "emdash_stats.json"
    em_doc = copy.deepcopy(committed)
    em_doc["note"] = "bad " + chr(0x2014) + " dash"
    em_file.write_text(json.dumps(em_doc), encoding="utf-8")
    with pytest.raises(ValueError, match="em-dash"):
        dpo.check_dpo_stats(em_file, replay=False)


def test_end_to_end_mini_export_and_check_cli(capsys):
    with tempfile.TemporaryDirectory(
        prefix="w5_test_export_",
        dir=str(_opencode_tmp_root()),
    ) as tmp_dir:
        tmp_root = Path(tmp_dir)
        out_jsonl = tmp_root / "mini_pairs.jsonl"
        out_stats = tmp_root / "mini_stats.json"
        mini_candidates = (
            ("most_recipients", "random_peer"),
            ("oldest", "random_peer"),
            ("fewest_recipients", "none"),
            ("none", "none"),
        )
        stats = dpo.export_mole_dpo(
            out_jsonl=out_jsonl,
            stats_out=out_stats,
            n_per_tier=1,
            tiers=("medium",),
            seed_start=125_037,
            horizon=3,
            candidates=mini_candidates,
            workers=1,
            include_horizon_comparison=False,
        )
        assert out_jsonl.is_file()
        assert out_stats.is_file()
        assert out_stats.stat().st_size <= 50 * 1024
        lines = [json.loads(ln) for ln in out_jsonl.read_text(encoding="utf-8").splitlines() if ln.strip()]
        assert len(lines) == stats["n_pairs"] >= 1
        for row in lines:
            assert row["seed"] == 125_037
            assert row["horizon"] == 3
            assert row["chosen_solver_correct"] is True
            assert row["chosen_solver_score"] >= 0.25
            assert row["margin"] >= 0.10

        cli_jsonl = tmp_root / "cli_pairs.jsonl"
        cli_stats = tmp_root / "cli_stats.json"
        rc_export = dpo.main(
            [
                "--out-pairs",
                str(cli_jsonl),
                "--stats-out",
                str(cli_stats),
                "--n-per-tier",
                "1",
                "--tiers",
                "medium",
                "--seed-start",
                "125037",
                "--horizon",
                "3",
                "--workers",
                "4",
                "--no-horizon-comparison",
                "--delete-tmp-jsonl",
            ]
        )
        captured_export = capsys.readouterr()
        assert rc_export == 0
        assert not cli_jsonl.exists()
        assert cli_stats.is_file()
        assert json.loads(captured_export.out)["n_pairs"] >= 1

        rc_ok = dpo.main(
            [
                "--check",
                "--stats-out",
                str(STATS_PATH),
                "--workers",
                "4",
            ]
        )
        captured_ok = capsys.readouterr()
        assert rc_ok == 0
        check_payload = json.loads(captured_ok.out)
        assert check_payload["ok"] is True
        assert check_payload["horizon_days"] == 3
        assert check_payload["seed_range"] == [125_000, 125_059]
        assert check_payload["replayed_exemplars"] == 6
        assert check_payload["slice_verified"] is True

        tampered_stats = tmp_root / "tampered_stats.json"
        tampered_obj = json.loads(STATS_PATH.read_text(encoding="utf-8"))
        tampered_obj["reproducibility"]["state_manifest_sha256"] = "0" * 64
        tampered_stats.write_text(json.dumps(tampered_obj), encoding="utf-8")

        rc_fail = dpo.main(
            [
                "--check",
                "--stats-out",
                str(tampered_stats),
                "--workers",
                "1",
            ]
        )
        captured_fail = capsys.readouterr()
        assert rc_fail == 1
        err_payload = json.loads(captured_fail.err)
        assert err_payload["ok"] is False
        assert "state_manifest_sha256" in err_payload["error"]
