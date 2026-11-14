from __future__ import annotations

import io
import json
import tokenize
from pathlib import Path

import pytest

from canary.agents.world_builder import assert_no_truth
from canary.env import Env
from canary.gemini import live_events
from canary.gemini.leak_encodings import (
    audit_env_outputs,
    extract_env_secrets,
    scan_text_for_secret,
)
from canary.gemini.provenance import audit_provenance, scan_file_secrets
from canary.text.lint import lint_messages

REPO_ROOT = Path(__file__).resolve().parents[1]
RUN_DIR = REPO_ROOT / "results" / "gemini_roles" / "world_text" / "dynamic-events-hard-carbon"


@pytest.fixture(autouse=True)
def _keyless_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "")
    monkeypatch.setenv("GOOGLE_API_KEY", "")
    monkeypatch.setenv("GOOGLE_GENERATIVE_AI_API_KEY", "")
    monkeypatch.delenv("GEMINI_GATEWAY_URL", raising=False)
    monkeypatch.setenv("CANARY_GEMINI_LEDGER", str(tmp_path / "ledger.jsonl"))
    monkeypatch.setattr("canary.llm.base.load_env", lambda: None)


def test_hard_run_meta_and_provenance() -> None:
    meta = json.loads((RUN_DIR / "meta.json").read_text(encoding="utf-8"))
    summary_md = (RUN_DIR / "summary.md").read_text(encoding="utf-8")

    assert meta["role"] == "world_text"
    assert meta["subrole"] == "dynamic_mid_episode_events"
    assert meta["model_id"] == "gemini-4-carbon"
    assert meta["tier"] == "hard"
    assert meta["tiers_version"] == "v1.4"
    assert meta["seeds"] == [0, 1, 2]
    assert meta["days"] == [4, 9, 15]
    assert meta["n_events_generated"] == 9
    assert meta["truth_leak_violations"] == 0
    assert meta["raw_llm_violations"] == 0
    assert meta["lint_violations"] == 0
    assert meta["solver_parity_ok"] is True

    usage = meta["usage"]
    assert usage["calls"] == 9
    assert usage["in"] > 0
    assert usage["out"] > 0
    assert usage["thinking"] > 0
    assert usage["total_tokens"] == usage["in"] + usage["out"] + usage["thinking"]
    assert usage["cost_usd"] > 0.0
    assert usage["latency_s"] > 0.0

    assert "gemini-4-carbon" in summary_md
    assert "SolverPolicy vs ObviousHeuristic" in summary_md

    report = audit_provenance(REPO_ROOT)
    rel_dir = "results/gemini_roles/world_text/dynamic-events-hard-carbon"
    matching = [r for r in report["runs"] if r["run_dir"] == rel_dir]
    assert len(matching) == 1
    run_entry = matching[0]
    assert run_entry["verified"] is True
    assert run_entry["role"] == "world_text"
    assert run_entry["model_id"] == "gemini-4-carbon"
    assert run_entry["count"] == 9
    assert run_entry["errors"] == []
    assert run_entry["secret_leaks"] == []


def test_hard_event_bundles_truth_lint_and_secret_scan() -> None:
    events_doc = json.loads((RUN_DIR / "events.json").read_text(encoding="utf-8"))

    assert events_doc["role"] == "world_text"
    assert events_doc["subrole"] == "dynamic_mid_episode_events"
    assert events_doc["model_id"] == "gemini-4-carbon"
    assert events_doc["tier"] == "hard"
    assert events_doc["tiers_version"] == "v1.4"
    assert events_doc["days"] == [4, 9, 15]
    assert events_doc["n_events_generated"] == 9
    assert [entry["seed"] for entry in events_doc["seeds"]] == [0, 1, 2]

    seen_categories: set[str] = set()
    total_bundles = 0

    for seed_entry in events_doc["seeds"]:
        seed = int(seed_entry["seed"])
        env = Env("hard", seed)
        world = env._world
        assert env.p.n_employees == 40
        assert env.p.n_days == 21
        assert len(world.employees) == 40

        mole_id = str(world.mole)
        assert mole_id.startswith("e")
        _, world_secrets = extract_env_secrets(env)

        bundles = seed_entry["events"]
        assert [b["day"] for b in bundles] == [4, 9, 15]

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
            assert bundle["meta"]["usage"]["in"] > 0
            assert bundle["meta"]["usage"]["out"] > 0
            assert bundle["meta"]["usage"]["cost_usd"] > 0.0
            assert len(bundle["reactions"]) == 3
            assert len(bundle["messages"]) == 4

            assert_no_truth(bundle, world)
            assert lint_messages(bundle["messages"]) == []
            assert scan_text_for_secret(bundle["messages"], mole_id) == []
            assert scan_text_for_secret(bundle, world_secrets) == []

            prose_fields = [
                bundle["headline"],
                bundle["summary"],
                bundle["bulletin"]["subject"],
                bundle["bulletin"]["body"],
                *[r["body"] for r in bundle["reactions"]],
            ]
            for text_field in prose_fields:
                assert scan_text_for_secret(text_field, mole_id) == []

        live_env = Env(
            "hard",
            seed,
            text_provider=live_events.LiveEventsTextProvider(bundles),
        )
        assert audit_env_outputs(live_env) == []

    assert total_bundles == 9
    assert seen_categories == set(live_events.EVENT_CATEGORIES)


def test_hard_solver_parity_and_40_staff_replay() -> None:
    events_doc = json.loads((RUN_DIR / "events.json").read_text(encoding="utf-8"))
    parity = json.loads((RUN_DIR / "solver_parity.json").read_text(encoding="utf-8"))

    assert parity["tier"] == "hard"
    assert parity["seeds"] == [0, 1, 2]
    assert parity["parity_ok"] is True
    assert parity["do_nothing_all_zero"] is True
    assert parity["baseline_solver_accuracy"] == 1.0
    assert parity["live_events_solver_accuracy"] == 1.0
    assert parity["live_events_solver_mean_score"] > 0.5
    assert abs(parity["solver_score_delta"]) <= 0.05
    assert parity["live_events_solver_mean_score"] > parity["live_events_obvious_heuristic_mean_score"]
    assert parity["solver_vs_obvious_gap"] > 0.20

    assert len(parity["per_seed"]) == 3
    for row in parity["per_seed"]:
        env = Env("hard", int(row["seed"]))
        assert len(env._world.employees) == 40
        assert env.p.n_days == 21
        assert row["live_events_solver"]["correct"] is True
        assert row["live_events_solver"]["score"] > row["live_events_obvious_heuristic"]["score"]
        assert row["live_events_do_nothing_score"] == 0.0
        assert row["event_messages_delivered"] == 12

    events_by_seed = {int(s["seed"]): s["events"] for s in events_doc["seeds"]}
    replayed = live_events.verify_solver_parity("hard", [0, 1, 2], events_by_seed)
    assert replayed == parity


def test_no_comments_em_dashes_or_secrets_in_hard_run_and_test() -> None:
    py_file = Path(__file__).resolve()
    py_text = py_file.read_text(encoding="utf-8")
    tokens = list(tokenize.generate_tokens(io.StringIO(py_text).readline))
    comments = [tok for tok in tokens if tok.type == tokenize.COMMENT]
    assert comments == []

    all_files = [py_file, *sorted(p for p in RUN_DIR.rglob("*") if p.is_file())]
    assert len(all_files) == 5
    for fp in all_files:
        txt = fp.read_text(encoding="utf-8")
        assert "\u2014" not in txt
        assert "\u2013" not in txt
        assert scan_file_secrets(fp, REPO_ROOT) == []
