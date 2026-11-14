from __future__ import annotations

import io
import json
from pathlib import Path
import tokenize

import pytest

from canary.agents.world_builder import GeminiWorldText, assert_no_truth
from canary.env import Env
from canary.eval import run_episode
from canary.gemini.leak_encodings import (
    audit_env_outputs,
    extract_env_secrets,
    scan_text_for_secret,
)
from canary.gemini.provenance import _inspect_run, scan_file_secrets
from canary.gemini.roles_dashboard import _scan_run_for_secrets
from canary.gemini.world_audit import audit_world_text_dir
from canary.solver.policy import SolverPolicy
from canary.text.lint import lint_messages, lint_text

ROOT = Path(__file__).resolve().parents[1]
RUN_DIR = ROOT / "results" / "gemini_roles" / "world_text" / "carbon-v14-seeds3456-hard23"
EXPECTED_SPECS: tuple[tuple[str, int], ...] = (
    ("medium", 3),
    ("medium", 4),
    ("medium", 5),
    ("medium", 6),
    ("hard", 2),
    ("hard", 3),
)


@pytest.fixture(autouse=True)
def _hermetic_keyless_env(monkeypatch, tmp_path):
    monkeypatch.setenv("GEMINI_API_KEY", "")
    monkeypatch.setenv("GOOGLE_GENERATIVE_AI_API_KEY", "")
    monkeypatch.delenv("GEMINI_GATEWAY_URL", raising=False)
    monkeypatch.setenv("CANARY_GEMINI_LEDGER", str(tmp_path / "ledger.jsonl"))


def test_expanded_corpus_meta_and_provenance() -> None:
    assert RUN_DIR.is_dir()
    for fname in ("meta.json", "samples.json", "summary.md"):
        fpath = RUN_DIR / fname
        assert fpath.is_file(), f"missing {fname}"
        raw = fpath.read_text(encoding="utf-8")
        assert raw.strip(), f"empty {fname}"
        assert "\u2014" not in raw, f"em dash in {fname}"
        assert "\u2013" not in raw, f"en dash in {fname}"
        assert scan_file_secrets(fpath, ROOT) == []

    assert _scan_run_for_secrets(RUN_DIR) is False

    meta = json.loads((RUN_DIR / "meta.json").read_text(encoding="utf-8"))
    assert meta["role"] == "world_text"
    assert meta["subrole"] == "company_personas_chatter"
    assert meta["model_id"] == "gemini-4-carbon"
    assert meta["llm_spec"] == "gemini:gemini-4-carbon"
    assert meta["tiers_version"] == "v1.4"
    assert len(meta["commit"]) >= 7 and meta["commit"] != "unknown"
    assert meta["timestamp"]
    assert meta["command"]
    assert meta["n_worlds"] == 6
    assert meta["llm_ok_count"] == 6
    assert meta["gemini_provider_fallbacks"] == 0
    assert meta["truth_leak_violations"] == 0
    assert meta["lint_violations"] == 0
    assert meta["n_personas_generated"] == 160
    assert meta["n_llm_personas"] == 160
    assert meta["n_interviews_generated"] == 12
    assert meta["n_day_messages_generated"] >= 12
    assert meta["solver_all_clean"] is True
    assert meta["solver_episodes_verified"] == 6
    assert meta["world_specs"] == [{"tier": t, "seed": s} for t, s in EXPECTED_SPECS]

    usage = meta["usage"]
    assert usage["calls"] >= 30
    assert usage["in"] > 0
    assert usage["out"] > 0
    assert usage["total_tokens"] >= usage["in"] + usage["out"]
    assert usage["cost_usd"] > 0.0

    prov = _inspect_run(RUN_DIR / "meta.json", ROOT, ROOT / "data" / "runs" / "committed" / "v1.4")
    assert prov["verified"] is True, f"provenance failed: {prov}"
    assert prov["errors"] == []


def test_samples_json_worlds_pass_truth_lint_and_secret_scans() -> None:
    samples = json.loads((RUN_DIR / "samples.json").read_text(encoding="utf-8"))
    assert samples["role"] == "world_text"
    assert samples["subrole"] == "company_personas_chatter"
    assert samples["model_id"] == "gemini-4-carbon"
    assert samples["tiers_version"] == "v1.4"
    assert samples["n_worlds"] == 6
    assert len(samples["worlds"]) == 6
    assert [(w["tier"], int(w["seed"])) for w in samples["worlds"]] == list(EXPECTED_SPECS)

    for w in samples["worlds"]:
        tier = str(w["tier"])
        seed = int(w["seed"])
        env = Env(tier, seed)
        world = env._world
        mole_id = world.mole
        _, world_secrets = extract_env_secrets(env)
        secret_targets = [mole_id, *world_secrets]

        assert_no_truth(w, world)
        assert scan_text_for_secret(w, world_secrets) == []

        wb = w["world_builder"]
        assert wb["llm_ok"] is True
        assert wb["n_fallback_personas"] == 0
        assert wb["n_personas"] == len(world.employees)
        assert wb["n_llm_personas"] == len(world.employees)

        prose_items = (
            [wb["company_blurb"]]
            + [p["bio"] for p in wb["sample_personas"]]
            + [d["culture"] for d in wb["departments"]]
            + list(wb["sample_chatter_templates"])
        )
        for text_item in prose_items:
            assert lint_text(text_item) == []
            assert_no_truth(text_item, world)
            assert scan_text_for_secret(text_item, secret_targets) == []

        sample_rendered = wb["sample_rendered_day1_messages"]
        assert lint_messages(sample_rendered) == []
        assert_no_truth(sample_rendered, world)
        assert scan_text_for_secret(sample_rendered, secret_targets) == []

        gp = w["gemini_provider"]
        assert gp["fallbacks"] == 0
        for msg_batch in (gp["day1_messages"], gp["day2_messages"]):
            assert len(msg_batch) >= 5
            assert lint_messages(msg_batch) == []
            assert_no_truth(msg_batch, world)
            assert scan_text_for_secret(msg_batch, secret_targets) == []

        combined_gp_msgs = list(gp["day1_messages"]) + list(gp["day2_messages"])
        assert scan_text_for_secret(combined_gp_msgs, secret_targets) == []

        iv_answers = [
            gp["interviews"]["cooperative"]["answer"],
            gp["interviews"]["evasive"]["answer"],
        ]
        for ans in iv_answers:
            assert ans.strip()
            assert lint_text(ans) == []
            assert_no_truth(ans, world)
            assert scan_text_for_secret(ans, secret_targets) == []
        assert scan_text_for_secret(iv_answers, secret_targets) == []

        assert w["integrity"]["truth_leak_violations"] == 0
        assert w["integrity"]["lint_violations"] == 0
        assert w["solver_verification"]["clean_run"] is True


@pytest.mark.parametrize(("tier", "seed"), EXPECTED_SPECS)
def test_world_files_pass_truth_lint_secret_scan_and_solver(tier: str, seed: int) -> None:
    wt_path = RUN_DIR / "worlds" / tier / f"{seed}.worldtext.json"
    tx_path = RUN_DIR / "worlds" / tier / f"{seed}.text.json"
    assert wt_path.is_file(), f"missing {wt_path}"
    assert tx_path.is_file(), f"missing {tx_path}"

    wt_raw = wt_path.read_text(encoding="utf-8")
    tx_raw = tx_path.read_text(encoding="utf-8")
    for fp, raw in ((wt_path, wt_raw), (tx_path, tx_raw)):
        assert "\u2014" not in raw and "\u2013" not in raw
        assert scan_file_secrets(fp, ROOT) == []

    wt = json.loads(wt_raw)
    tx = json.loads(tx_raw)

    ref_env = Env(tier, seed)
    world = ref_env._world
    mole_id = world.mole
    _, world_secrets = extract_env_secrets(ref_env)
    secret_targets = [mole_id, *world_secrets]

    assert wt["meta"]["llm_ok"] is True
    assert wt["meta"]["n_fallback_personas"] == 0
    assert len(wt["personas"]) == len(world.employees)

    assert_no_truth(wt, world)
    assert_no_truth(tx, world)
    assert scan_text_for_secret(wt, world_secrets) == []
    assert scan_text_for_secret(tx, world_secrets) == []

    wt_strings = (
        [wt["company_blurb"]]
        + [p["bio"] for p in wt["personas"]]
        + [d["culture"] for d in wt["departments"]]
        + list(wt["chatter_templates"])
    )
    for item in wt_strings:
        assert item.strip()
        assert lint_text(item) == []
        assert_no_truth(item, world)
        assert scan_text_for_secret(item, secret_targets) == []

    assert set(tx["days"]) == {"1", "2"}
    assert len(tx["interviews"]) == 2
    for day_key in ("1", "2"):
        msgs = tx["days"][day_key]
        assert len(msgs) >= 5
        assert lint_messages(msgs) == []
        assert_no_truth(msgs, world)
        assert scan_text_for_secret(msgs, secret_targets) == []

    all_day_msgs = list(tx["days"]["1"]) + list(tx["days"]["2"])
    assert lint_messages(all_day_msgs) == []
    assert scan_text_for_secret(all_day_msgs, secret_targets) == []

    assert any("|cooperative|" in k for k in tx["interviews"])
    assert any("|evasive|" in k for k in tx["interviews"])
    iv_values = list(tx["interviews"].values())
    for ans in iv_values:
        assert ans.strip()
        assert lint_text(ans) == []
        assert_no_truth(ans, world)
        assert scan_text_for_secret(ans, secret_targets) == []
    assert scan_text_for_secret(iv_values, secret_targets) == []

    provider = GeminiWorldText(wt, name="gemini-world:gemini-4-carbon")
    solver_env = Env(tier, seed, text_provider=provider)
    ep = run_episode(solver_env, SolverPolicy())
    assert solver_env.done
    assert ep.end_reason != "error"
    env_msgs = list(solver_env._messages.values())
    assert lint_messages(env_msgs) == []
    assert_no_truth(env_msgs, world)
    assert scan_text_for_secret(env_msgs, secret_targets) == []
    assert audit_env_outputs(solver_env, step_episode=False) == []


def test_expanded_corpus_passes_world_audit_both_tiers() -> None:
    worlds_dir = RUN_DIR / "worlds"
    rep_med = audit_world_text_dir(worlds_dir, "medium", [3, 4, 5, 6], build_missing=False)
    assert rep_med["ok"] is True
    assert rep_med["non_leak"]["ok"] is True
    assert rep_med["solver_parity"]["ok"] is True

    rep_hard = audit_world_text_dir(worlds_dir, "hard", [2, 3], build_missing=False)
    assert rep_hard["ok"] is True
    assert rep_hard["non_leak"]["ok"] is True
    assert rep_hard["solver_parity"]["ok"] is True


def test_source_file_has_no_comments_em_dashes_or_secrets() -> None:
    this_file = Path(__file__).resolve()
    src = this_file.read_text(encoding="utf-8")
    assert "\u2014" not in src
    assert "\u2013" not in src
    tokens = list(tokenize.generate_tokens(io.StringIO(src).readline))
    comments = [tok for tok in tokens if tok.type == tokenize.COMMENT]
    assert comments == [], f"found comment in {this_file}: {comments}"
    assert scan_file_secrets(this_file, ROOT) == []
