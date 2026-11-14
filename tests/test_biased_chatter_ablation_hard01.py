from __future__ import annotations

import importlib.util
import io
import json
from pathlib import Path
import sys
import tokenize
from typing import Any

import pytest

from canary.agents.world_builder import assert_no_truth
from canary.env import Env
from canary.eval import run_episode
from canary.gemini import read_ledger
from canary.gemini.biased_chatter import BIAS_KINDS, BiasedChatterProvider
from canary.gemini.leak_encodings import (
    SUPPORTED_ENCODINGS,
    audit_env_outputs,
    extract_env_secrets,
    scan_messages_for_secret,
    scan_text_for_secret,
)
from canary.gemini.provenance import _inspect_run, audit_provenance, scan_file_secrets
from canary.gemini.roles_dashboard import _scan_run_for_secrets
from canary.llm.stub import StubClient
from canary.solver.policy import SolverPolicy
from canary.text.lint import lint_messages

REPO_ROOT = Path(__file__).resolve().parents[1]
RUN_DIR = (
    REPO_ROOT
    / "results"
    / "gemini_roles"
    / "world_text"
    / "biased-chatter-ablation-hard01"
)
SAMPLES_CACHE = (
    REPO_ROOT
    / "results"
    / "gemini_roles"
    / "world_text"
    / "biased-chatter-hard-carbon"
    / "chatter_samples.json"
)
V14_ROOT = REPO_ROOT / "data" / "runs" / "committed" / "v1.4"
EXPECTED_SEEDS = [0, 1]
EXPECTED_POLICIES = ("solver", "obvious_heuristic", "carbon")
EXPECTED_WORLDS = ("template", "biased")
EM_DASH = chr(0x2014)
EN_DASH = chr(0x2013)


def _load_ablation_module():
    mod_name = "run_biased_chatter_ablation"
    script_path = REPO_ROOT / "scripts" / f"{mod_name}.py"
    spec = importlib.util.spec_from_file_location(mod_name, script_path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(autouse=True)
def _hermetic_keyless_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Path:
    ledger_file = tmp_path / "ledger.jsonl"
    monkeypatch.setenv("CANARY_GEMINI_LEDGER", str(ledger_file))
    monkeypatch.setenv("GEMINI_API_KEY", "")
    monkeypatch.setenv("GOOGLE_GENERATIVE_AI_API_KEY", "")
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_GATEWAY_URL", raising=False)
    return ledger_file


def test_hard01_provenance_inspect_run_and_meta() -> None:
    assert RUN_DIR.is_dir()
    meta_path = RUN_DIR / "meta.json"
    comp_path = RUN_DIR / "comparison.json"
    summary_path = RUN_DIR / "summary.md"
    assert meta_path.is_file()
    assert comp_path.is_file()
    assert summary_path.is_file()

    inspected = _inspect_run(meta_path, REPO_ROOT, V14_ROOT)
    assert inspected["verified"] is True, f"provenance failed: {inspected}"
    assert inspected["errors"] == []
    assert inspected["secret_leaks"] == []
    assert inspected["role"] == "world_text"
    assert inspected["role_inferred"] is False
    assert inspected["model_id"] == "gemini-4-carbon"
    assert inspected["count"] == 12
    assert inspected["tokens_in"] > 0
    assert inspected["tokens_out"] > 0
    assert inspected["thinking_tokens"] > 0
    assert inspected["cost_usd"] > 0.0

    report = audit_provenance(REPO_ROOT)
    assert report["secret_leaks"] == []
    rel_target = "results/gemini_roles/world_text/biased-chatter-ablation-hard01"
    matched = [r for r in report["runs"] if r["run_dir"] == rel_target]
    assert len(matched) == 1
    assert matched[0]["verified"] is True
    assert matched[0]["errors"] == []

    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    summary_md = summary_path.read_text(encoding="utf-8")

    assert meta["role"] == "world_text"
    assert meta["subrole"] == "biased_chatter_investigator_ablation"
    assert meta["model_id"] == "gemini-4-carbon"
    assert meta["tiers_version"] == "v1.4"
    assert meta["tier"] == "hard"
    assert meta["seeds"] == EXPECTED_SEEDS
    assert meta["episode_count"] == 12
    assert meta["carbon_episode_count"] == 4
    assert meta["stub"] is False
    assert meta["fake_env"] is False
    assert meta["smoke"] is False
    assert len(meta["commit"]) >= 7 and meta["commit"] != "0000000"
    assert meta["timestamp"]
    assert "--tier hard" in meta["command"]
    assert "--seeds 0,1" in meta["command"]

    usage = meta["usage"]
    assert usage["calls"] >= 4
    assert usage["in"] > 0
    assert usage["out"] > 0
    assert usage["input_tokens"] == usage["in"]
    assert usage["thinking_tokens"] > 0
    assert usage["total_tokens"] == usage["in"] + usage["out"]
    assert usage["cost_usd"] > 0.0
    assert meta["usage_breakdown"]["investigator"]["calls"] >= 4

    assert summary_md.strip()
    assert "gemini-4-carbon" in summary_md
    assert "v1.4" in summary_md
    assert "hard" in summary_md
    assert "SolverPolicy" in summary_md
    assert "BiasedChatterProvider" in summary_md
    assert "TemplateProvider" in summary_md


def test_hard01_solver_zero_rumour_distraction_and_parity() -> None:
    meta = json.loads((RUN_DIR / "meta.json").read_text(encoding="utf-8"))
    comp = json.loads((RUN_DIR / "comparison.json").read_text(encoding="utf-8"))
    arms = comp["arms"]
    deltas = comp["paired_deltas"]

    assert meta["solver_biased_distraction_rate"] == 0.0
    assert meta["solver_template_distraction_rate"] == 0.0
    assert meta["solver_biased_mean"] == pytest.approx(meta["solver_template_mean"])

    solver_b = arms["solver_biased"]
    solver_t = arms["solver_template"]
    assert solver_b["n"] == 2
    assert solver_t["n"] == 2
    assert solver_b["accuracy"] == 1.0
    assert solver_t["accuracy"] == 1.0
    assert solver_b["rumor_target_distraction_rate"] == 0.0
    assert solver_t["rumor_target_distraction_rate"] == 0.0
    assert solver_b["rumor_target_action_share_mean"] == 0.0
    assert solver_b["rumor_target_pooled_action_share"] == 0.0
    assert solver_b["rumor_target_interviews_total"] == 0
    assert solver_b["rumor_target_restrictions_total"] == 0
    assert solver_b["rumor_target_accused_rate"] == 0.0
    assert deltas["solver"]["score_delta"] == pytest.approx(0.0)
    assert deltas["solver"]["accuracy_delta"] == pytest.approx(0.0)
    assert deltas["solver"]["rumor_target_distraction_rate_delta"] == 0.0
    assert deltas["solver"]["rumor_target_action_share_delta"] == 0.0

    solver_eps = [e for e in comp["episodes"] if e["policy"] == "solver"]
    assert len(solver_eps) == 4
    for ep in solver_eps:
        assert ep["correct"] is True
        assert ep["rumor_target_distracted"] is False
        assert ep["rumor_target_distraction_calls"] == 0
        assert ep["rumor_target_interviews"] == 0
        assert ep["rumor_target_restrictions"] == 0
        assert ep["rumor_target_accused"] is False

    for seed in EXPECTED_SEEDS:
        replay_res = run_episode(Env("hard", seed), SolverPolicy())
        ep_t = next(
            e
            for e in solver_eps
            if e["seed"] == seed and e["world"] == "template"
        )
        ep_b = next(
            e
            for e in solver_eps
            if e["seed"] == seed and e["world"] == "biased"
        )
        assert replay_res.correct is True
        assert round(float(replay_res.score), 6) == pytest.approx(ep_t["score"])
        assert ep_b["score"] == pytest.approx(ep_t["score"])


def test_hard01_transcripts_complete_and_sanitized() -> None:
    comp = json.loads((RUN_DIR / "comparison.json").read_text(encoding="utf-8"))
    assert comp["tier"] == "hard"
    assert comp["tiers_version"] == "v1.4"
    assert comp["seeds"] == EXPECTED_SEEDS
    assert comp["model_id"] == "gemini-4-carbon"

    episodes = comp["episodes"]
    assert len(episodes) == 12

    expected_cells = {
        (s, w, p)
        for s in EXPECTED_SEEDS
        for w in EXPECTED_WORLDS
        for p in EXPECTED_POLICIES
    }
    observed_cells = {
        (int(e["seed"]), str(e["world"]), str(e["policy"])) for e in episodes
    }
    assert observed_cells == expected_cells

    transcript_dir = RUN_DIR / "transcripts"
    assert transcript_dir.is_dir()
    expected_files = {
        f"{p}_{w}_seed{s}.json"
        for s in EXPECTED_SEEDS
        for w in EXPECTED_WORLDS
        for p in EXPECTED_POLICIES
    }
    actual_files = {p.name for p in transcript_dir.glob("*.json")}
    assert actual_files == expected_files

    for ep in episodes:
        t_path = RUN_DIR / ep["transcript_file"]
        assert t_path.is_file()
        raw_text = t_path.read_text(encoding="utf-8")
        assert raw_text.strip()
        parsed = json.loads(raw_text)
        if ep["policy"] == "carbon":
            assert isinstance(parsed, list)
            assert len(parsed) >= 3
            assert parsed[0]["role"] == "system"
            assert "40 employees" in parsed[0]["content"]
            assert ep["agent_name"] == "gemini:gemini-4-carbon"
            assert ep["usage"]["calls"] > 0
            assert ep["usage"]["in"] > 0
            assert ep["usage"]["out"] > 0
        else:
            assert isinstance(parsed, dict)
            assert parsed["tier"] == "hard"
            assert int(parsed["seed"]) == int(ep["seed"])
            assert parsed["policy"] == ep["policy"]
            assert parsed["world"] == ep["world"]
            assert len(parsed["steps"]) == int(ep["step_count"])
            assert len(parsed["steps"]) > 0


def _collect_transcript_world_messages(parsed: Any) -> list[dict[str, Any]]:
    collected: list[dict[str, Any]] = []
    if isinstance(parsed, dict):
        for step in parsed.get("steps", []):
            if not isinstance(step, dict):
                continue
            tool = step.get("tool")
            res = step.get("result") or {}
            data = res.get("data") if isinstance(res, dict) else None
            if not isinstance(data, dict):
                continue
            if tool == "search_messages" and isinstance(data.get("messages"), list):
                collected.extend(m for m in data["messages"] if isinstance(m, dict))
            elif tool == "read_message" and isinstance(data.get("message"), dict):
                collected.append(data["message"])
    elif isinstance(parsed, list):
        for item in parsed:
            if not isinstance(item, dict) or item.get("role") != "tool":
                continue
            tool_name = item.get("name")
            if tool_name not in ("search_messages", "read_message"):
                continue
            try:
                res_obj = json.loads(str(item.get("content", "")))
            except ValueError:
                continue
            data = res_obj.get("data") if isinstance(res_obj, dict) else None
            if not isinstance(data, dict):
                continue
            if tool_name == "search_messages" and isinstance(data.get("messages"), list):
                collected.extend(m for m in data["messages"] if isinstance(m, dict))
            elif tool_name == "read_message" and isinstance(data.get("message"), dict):
                collected.append(data["message"])
    return collected


def test_hard01_assert_no_truth_and_leak_encodings() -> None:
    assert len(SUPPORTED_ENCODINGS) == 37
    assert SAMPLES_CACHE.is_file()

    comp = json.loads((RUN_DIR / "comparison.json").read_text(encoding="utf-8"))
    samples_doc = json.loads(SAMPLES_CACHE.read_text(encoding="utf-8"))
    mod = _load_ablation_module()

    for seed in EXPECTED_SEEDS:
        env_ref = Env("hard", seed)
        emps = env_ref.call("list_employees", {}).data["employees"]
        assert len(emps) == 40
        global_secrets, world_targets = extract_env_secrets(env_ref)
        truth_ctx = {"mole": env_ref._world.mole, "employees": emps}

        seed_info = comp["seed_bias_specs"][str(seed)]
        assert int(seed_info["seed"]) == seed
        assert len(seed_info["days_generated"]) >= 14
        assert_no_truth(seed_info, truth_ctx)

        day1_msgs = seed_info["day1_messages"]
        assert len(day1_msgs) == 5
        kinds = [m["bias_type"] for m in day1_msgs]
        assert set(kinds) == set(BIAS_KINDS)
        assert kinds.count("grudge_bickering") == 2
        assert not lint_messages(day1_msgs)
        assert scan_messages_for_secret(day1_msgs, world_targets) == []
        assert scan_text_for_secret(seed_info["bias_spec"], world_targets) == []

        cached_seed_msgs: list[dict[str, Any]] = []
        for s_item in samples_doc["samples"]:
            if int(s_item["seed"]) != seed:
                continue
            assert_no_truth(s_item, truth_ctx)
            assert not lint_messages(s_item["messages"])
            assert scan_messages_for_secret(s_item["messages"], world_targets) == []
            cached_seed_msgs.extend(s_item["messages"])
        assert len(cached_seed_msgs) == 15
        assert scan_messages_for_secret(cached_seed_msgs, world_targets) == []

        observed_biased_msgs: list[dict[str, Any]] = []
        for p_key in EXPECTED_POLICIES:
            t_file = RUN_DIR / "transcripts" / f"{p_key}_biased_seed{seed}.json"
            t_parsed = json.loads(t_file.read_text(encoding="utf-8"))
            msgs = _collect_transcript_world_messages(t_parsed)
            for msg in msgs:
                if str(msg.get("id", "")).startswith("bc"):
                    observed_biased_msgs.append(msg)
        if observed_biased_msgs:
            assert_no_truth({"messages": observed_biased_msgs}, truth_ctx)
            assert scan_messages_for_secret(observed_biased_msgs, global_secrets) == []

        by_day = mod.capture_clean_public_facts("hard", seed)
        ws = int(by_day[1].seed)
        clean_map = {("hard", ws, d): f for d, f in by_day.items()}
        spec = mod.build_bias_event_spec(by_day[1], seed=ws)
        prov = mod.AblationBiasedChatterProvider(
            model="stub",
            client=StubClient(model="stub"),
            clean_facts_by_key=clean_map,
            seed_specs_by_ws={("hard", ws): spec},
        )
        assert isinstance(prov, BiasedChatterProvider)
        seed_specs_s = {seed: spec}
        seed_specs_ws = {("hard", ws): spec}
        mod._load_cached_samples(
            SAMPLES_CACHE,
            "hard",
            {seed: ws},
            prov,
            seed_specs_s,
            seed_specs_ws,
        )
        audit_hits = audit_env_outputs(
            Env("hard", seed, text_provider=prov),
            step_episode=True,
        )
        assert audit_hits == []


def test_stub_hard01_ablation_reuses_samples_cache(
    tmp_path: Path, _hermetic_keyless_env: Path
) -> None:
    mod = _load_ablation_module()
    out_dir = tmp_path / "hard01_stub"
    rc = mod.main(
        [
            "--stub",
            "--tier",
            "hard",
            "--seeds",
            "0,1",
            "--samples-cache",
            str(SAMPLES_CACHE),
            "--concurrency",
            "2",
            "--out",
            str(out_dir),
            "--quiet",
        ]
    )
    assert rc == 0

    meta = json.loads((out_dir / "meta.json").read_text(encoding="utf-8"))
    comp = json.loads((out_dir / "comparison.json").read_text(encoding="utf-8"))
    assert meta["tier"] == "hard"
    assert meta["tiers_version"] == "v1.4"
    assert meta["seeds"] == [0, 1]
    assert meta["episode_count"] == 12
    assert meta["stub"] is True
    assert meta["solver_biased_distraction_rate"] == 0.0
    assert meta["solver_template_distraction_rate"] == 0.0
    assert meta["solver_biased_mean"] == pytest.approx(meta["solver_template_mean"])
    assert len(comp["episodes"]) == 12

    ledger_rows = read_ledger([_hermetic_keyless_env])
    assert ledger_rows
    assert all(r["feature"] == "biased_chatter_ablation" for r in ledger_rows)

    fake_root = tmp_path / "fake_root"
    stub_dir = (
        fake_root
        / "results"
        / "gemini_roles"
        / "world_text"
        / "biased-chatter-ablation-hard01-stub"
    )
    stub_dir.mkdir(parents=True)
    (stub_dir / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    inspected_stub = _inspect_run(
        stub_dir / "meta.json",
        fake_root,
        fake_root / "data" / "runs" / "committed" / "v1.4",
    )
    assert inspected_stub["verified"] is False
    assert "stub_run" in inspected_stub["errors"]


def test_zero_comments_zero_dashes_zero_secrets() -> None:
    py_targets = [
        REPO_ROOT / "scripts" / "run_biased_chatter_ablation.py",
        REPO_ROOT / "tests" / "test_biased_chatter_ablation_hard01.py",
    ]
    for path in py_targets:
        text = path.read_text(encoding="utf-8")
        assert EM_DASH not in text, f"em dash in {path}"
        assert EN_DASH not in text, f"en dash in {path}"
        tokens = list(tokenize.generate_tokens(io.StringIO(text).readline))
        comments = [tok for tok in tokens if tok.type == tokenize.COMMENT]
        assert comments == [], f"comment found in {path}: {comments}"
        assert scan_file_secrets(path, REPO_ROOT) == []

    assert RUN_DIR.is_dir()
    assert _scan_run_for_secrets(RUN_DIR) is False
    run_files = sorted(p for p in RUN_DIR.rglob("*") if p.is_file())
    assert len(run_files) >= 15
    for fp in run_files:
        txt = fp.read_text(encoding="utf-8")
        assert EM_DASH not in txt, f"em dash in {fp}"
        assert EN_DASH not in txt, f"en dash in {fp}"
        assert scan_file_secrets(fp, REPO_ROOT) == []
