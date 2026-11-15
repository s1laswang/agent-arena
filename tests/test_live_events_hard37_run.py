from __future__ import annotations

import importlib.util
import io
import json
from pathlib import Path
import sys
import tokenize

import pytest

from canary.agents.world_builder import assert_no_truth
from canary.env import Env
from canary.gemini import live_events
from canary.gemini.leak_encodings import (
    SUPPORTED_ENCODINGS,
    audit_env_outputs,
    extract_env_secrets,
    scan_text_for_secret,
)
from canary.gemini.provenance import _inspect_run, audit_provenance, scan_file_secrets
from canary.gemini.roles_dashboard import _scan_run_for_secrets
from canary.text.lint import lint_messages

REPO_ROOT = Path(__file__).resolve().parents[1]
RUN_DIR = REPO_ROOT / "results" / "gemini_roles" / "world_text" / "dynamic-events-hard37-carbon"
SCRIPT_PATH = REPO_ROOT / "scripts" / "run_live_events_hard37.py"
EXPECTED_SEEDS = [3, 4, 5, 6, 7]
EXPECTED_DAYS = [4, 9, 15]
EM_DASH = chr(0x2014)
EN_DASH = chr(0x2013)


def _load_runner_module():
    mod_name = "run_live_events_hard37"
    spec = importlib.util.spec_from_file_location(mod_name, SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(autouse=True)
def _keyless_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "")
    monkeypatch.setenv("GOOGLE_API_KEY", "")
    monkeypatch.setenv("GOOGLE_GENERATIVE_AI_API_KEY", "")
    monkeypatch.delenv("GEMINI_GATEWAY_URL", raising=False)
    monkeypatch.setenv("CANARY_GEMINI_LEDGER", str(tmp_path / "ledger.jsonl"))
    monkeypatch.setattr("canary.llm.base.load_env", lambda: None)


def test_hard37_meta_and_provenance() -> None:
    assert RUN_DIR.is_dir()
    meta_files = sorted(RUN_DIR.rglob("meta.json"))
    assert meta_files == [RUN_DIR / "meta.json"]

    meta = json.loads((RUN_DIR / "meta.json").read_text(encoding="utf-8"))
    summary_md = (RUN_DIR / "summary.md").read_text(encoding="utf-8")

    assert meta["role"] == "world_text"
    assert meta["subrole"] == "dynamic_mid_episode_events"
    assert meta["model_id"] == "gemini-4-carbon"
    assert meta["llm_spec"] == "gemini:gemini-4-carbon"
    assert meta["tier"] == "hard"
    assert meta["tiers_version"] == "v1.4"
    assert meta["seeds"] == EXPECTED_SEEDS
    assert meta["days"] == EXPECTED_DAYS
    assert meta["n_events_generated"] == 15
    assert meta["llm_ok_count"] == 15
    assert meta["fallback_count"] == 0
    assert meta["n_messages_generated"] >= 45
    assert meta["truth_leak_violations"] == 0
    assert meta["raw_llm_violations"] == 0
    assert meta["lint_violations"] == 0
    assert meta["stego_leak_violations"] == 0
    assert meta["encodings_checked"] == len(SUPPORTED_ENCODINGS) == 37
    assert meta["text_probe_leak"] is False
    assert meta["solver_parity_ok"] is True
    assert meta["pooled_hard_n"] == 8
    assert meta["stub"] is False
    assert meta["fake_env"] is False
    assert meta["smoke"] is False

    usage = meta["usage"]
    assert usage["calls"] == 15
    assert usage["in"] > 0
    assert usage["out"] > 0
    assert usage["thinking"] > 0
    assert usage["total_tokens"] == usage["in"] + usage["out"] + usage["thinking"]
    assert usage["cost_usd"] > 0.0
    assert usage["latency_s"] > 0.0

    assert "gemini-4-carbon" in summary_md
    assert "Pooled v1.4 Hard Seeds" in summary_md

    inspected = _inspect_run(
        RUN_DIR / "meta.json",
        REPO_ROOT,
        REPO_ROOT / "data" / "runs" / "committed" / "v1.4",
    )
    assert inspected["verified"] is True, f"provenance failed: {inspected}"
    assert inspected["errors"] == []
    assert inspected["secret_leaks"] == []
    assert inspected["count"] == 15

    report = audit_provenance(REPO_ROOT)
    assert report["verified"] is True
    assert report["secret_leaks"] == []
    rel_dir = "results/gemini_roles/world_text/dynamic-events-hard37-carbon"
    matching = [r for r in report["runs"] if r["run_dir"] == rel_dir]
    assert len(matching) == 1
    assert matching[0]["verified"] is True


def test_hard37_bundles_non_leak_stego_and_text_probe() -> None:
    events_doc = json.loads((RUN_DIR / "events.json").read_text(encoding="utf-8"))

    assert events_doc["role"] == "world_text"
    assert events_doc["subrole"] == "dynamic_mid_episode_events"
    assert events_doc["model_id"] == "gemini-4-carbon"
    assert events_doc["tier"] == "hard"
    assert events_doc["tiers_version"] == "v1.4"
    assert events_doc["days"] == EXPECTED_DAYS
    assert events_doc["n_events_generated"] == 15
    assert [entry["seed"] for entry in events_doc["seeds"]] == EXPECTED_SEEDS

    probe = events_doc["text_probe"]
    assert probe["n"] == 5
    assert probe["text_leak"] is False
    assert probe["p_value_vs_bar"] >= 0.01
    for r in probe["rows"]:
        assert set(r.keys()) == {"seed", "correct"}

    seen_categories: set[str] = set()
    total_bundles = 0

    for seed_entry in events_doc["seeds"]:
        seed = int(seed_entry["seed"])
        env = Env("hard", seed)
        world = env._world
        assert env.p.n_employees == 40
        assert env.p.n_days == 21

        mole_id = str(world.mole)
        _, world_secrets = extract_env_secrets(env)

        bundles = seed_entry["events"]
        assert [b["day"] for b in bundles] == EXPECTED_DAYS

        audit = live_events.audit_event_bundles(bundles, world=world)
        assert audit["truth_leak_violations"] == 0
        assert audit["raw_llm_violations"] == 0
        assert audit["lint_violations"] == 0

        for bundle in bundles:
            total_bundles += 1
            seen_categories.add(bundle["category"])
            assert bundle["category"] in live_events.EVENT_CATEGORIES
            assert bundle["tier"] == "hard"
            assert bundle["meta"]["llm_ok"] is True
            assert bundle["meta"]["used_fallback"] is False
            assert bundle["meta"]["model"] == "gemini-4-carbon"
            assert len(bundle["reactions"]) >= 2
            assert len(bundle["messages"]) >= 3

            assert_no_truth(bundle, world)
            assert lint_messages(bundle["messages"]) == []
            assert scan_text_for_secret(bundle["messages"], mole_id) == []
            assert scan_text_for_secret(bundle, world_secrets) == []

        live_env = Env(
            "hard",
            seed,
            text_provider=live_events.LiveEventsTextProvider(bundles),
        )
        assert audit_env_outputs(live_env) == []

    assert total_bundles == 15
    assert seen_categories == set(live_events.EVENT_CATEGORIES)


def test_hard37_solver_parity_and_pooled_hard07() -> None:
    events_doc = json.loads((RUN_DIR / "events.json").read_text(encoding="utf-8"))
    parity = json.loads((RUN_DIR / "solver_parity.json").read_text(encoding="utf-8"))
    pooled = json.loads((RUN_DIR / "pooled_hard07.json").read_text(encoding="utf-8"))

    assert parity["tier"] == "hard"
    assert parity["seeds"] == EXPECTED_SEEDS
    assert parity["parity_ok"] is True
    assert parity["do_nothing_all_zero"] is True
    assert parity["baseline_solver_accuracy"] == 1.0
    assert parity["live_events_solver_accuracy"] == 1.0
    assert parity["solver_score_delta"] == pytest.approx(0.0)
    assert parity["solver_vs_obvious_gap"] > 1.0

    events_by_seed = {int(s["seed"]): s["events"] for s in events_doc["seeds"]}
    replayed = live_events.verify_solver_parity("hard", EXPECTED_SEEDS, events_by_seed)
    assert replayed == parity

    assert pooled["tier"] == "hard"
    assert pooled["seeds"] == [0, 1, 2, 3, 4, 5, 6, 7]
    assert pooled["n_seeds"] == 8
    assert pooled["parity_ok"] is True
    assert pooled["do_nothing_all_zero"] is True
    assert pooled["live_events_solver_accuracy"] == 1.0
    assert pooled["solver_score_delta_mean"] == pytest.approx(0.0)
    assert pooled["live_events_solver_ci95"] > 0.0


def test_stub_cli_smoke(tmp_path: Path) -> None:
    mod = _load_runner_module()
    out_dir = tmp_path / "stub_hard_events"
    rc = mod.main([
        "--llm",
        "stub",
        "--tier",
        "easy",
        "--seeds",
        "0,1",
        "--days",
        "3,6",
        "--jobs",
        "2",
        "--out",
        str(out_dir),
    ])
    assert rc == 0
    meta = json.loads((out_dir / "meta.json").read_text(encoding="utf-8"))
    assert meta["stub"] is True
    assert meta["n_events_generated"] == 4
    assert meta["truth_leak_violations"] == 0
    assert meta["lint_violations"] == 0
    assert meta["stego_leak_violations"] == 0
    assert meta["solver_parity_ok"] is True


def test_zero_comments_dashes_and_secrets() -> None:
    py_targets = [SCRIPT_PATH, Path(__file__).resolve()]
    for fpath in py_targets:
        src = fpath.read_text(encoding="utf-8")
        assert EM_DASH not in src
        assert EN_DASH not in src
        assert ("\\" + "u2014") not in src
        assert ("\\" + "u2013") not in src
        tokens = list(tokenize.generate_tokens(io.StringIO(src).readline))
        comments = [tok for tok in tokens if tok.type == tokenize.COMMENT]
        assert comments == [], f"found comment in {fpath}: {comments}"
        assert scan_file_secrets(fpath, REPO_ROOT) == []

    assert _scan_run_for_secrets(RUN_DIR) is False
    run_files = sorted(p for p in RUN_DIR.rglob("*") if p.is_file())
    assert len(run_files) == 5
    for fp in run_files:
        txt = fp.read_text(encoding="utf-8")
        assert EM_DASH not in txt
        assert EN_DASH not in txt
        assert scan_file_secrets(fp, REPO_ROOT) == []
