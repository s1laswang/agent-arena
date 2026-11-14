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
from canary.gemini import read_ledger
from canary.gemini.biased_chatter import BiasedChatterProvider
from canary.gemini.provenance import audit_provenance, scan_file_secrets
from canary.llm.stub import StubClient
from canary.text.facts import EmployeeFacts, PublicDayFacts
from canary.text.lint import lint_messages

REPO_ROOT = Path(__file__).resolve().parents[1]


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
def _isolated_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    ledger_file = tmp_path / "ledger.jsonl"
    monkeypatch.setenv("CANARY_GEMINI_LEDGER", str(ledger_file))
    monkeypatch.setenv("GEMINI_API_KEY", "")
    monkeypatch.setenv("GOOGLE_GENERATIVE_AI_API_KEY", "")
    monkeypatch.delenv("GEMINI_GATEWAY_URL", raising=False)
    return ledger_file


def test_stub_ablation_cli_and_solver_immunity(
    tmp_path: Path, _isolated_env: Path
) -> None:
    mod = _load_ablation_module()
    out_dir = tmp_path / "ablation_stub"
    rc = mod.main(
        [
            "--stub",
            "--tier",
            "medium",
            "--seeds",
            "10,11",
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
    summary = (out_dir / "summary.md").read_text(encoding="utf-8")

    assert meta["role"] == "world_text"
    assert meta["subrole"] == "biased_chatter_investigator_ablation"
    assert meta["tiers_version"] == "v1.4"
    assert meta["stub"] is True
    assert meta["episode_count"] == 12
    assert meta["solver_biased_mean"] == pytest.approx(0.765)
    assert meta["solver_template_mean"] == pytest.approx(0.765)
    assert meta["obvious_biased_mean"] == pytest.approx(-1.0)
    assert meta["obvious_template_mean"] == pytest.approx(-1.0)
    assert meta["solver_biased_distraction_rate"] == 0.0
    assert meta["solver_template_distraction_rate"] == 0.0
    assert meta["obvious_biased_distraction_rate"] == 0.0
    assert meta["carbon_biased_distraction_rate"] == 1.0
    assert meta["carbon_template_distraction_rate"] == 0.0
    assert meta["usage"]["calls"] > 0
    assert summary.strip()

    transcript_files = sorted((out_dir / "transcripts").glob("*.json"))
    assert len(transcript_files) == 12
    assert len(comp["episodes"]) == 12

    ledger_rows = read_ledger([_isolated_env])
    assert ledger_rows
    assert all(r["feature"] == "biased_chatter_ablation" for r in ledger_rows)

    fake_tree = tmp_path / "repo_check"
    target_dir = (
        fake_tree
        / "results"
        / "gemini_roles"
        / "world_text"
        / "biased-chatter-ablation-stub"
    )
    target_dir.mkdir(parents=True)
    (target_dir / "meta.json").write_text(
        json.dumps(meta, indent=2), encoding="utf-8"
    )
    prov = audit_provenance(fake_tree)
    stub_entry = prov["runs"][0]
    assert stub_entry["verified"] is False
    assert "stub_run" in stub_entry["errors"]


def test_custom_scripted_investigator_distraction_metrics(tmp_path: Path) -> None:
    mod = _load_ablation_module()
    sig_blob = "A" * 96
    sanitized = mod.sanitize_for_storage(
        {
            "note": "alpha \u2014 beta \u2013 gamma",
            "thought_signature": sig_blob,
            "nested": [{"thoughtSignature": sig_blob}],
        }
    )
    assert "\u2014" not in json.dumps(sanitized)
    assert "\u2013" not in json.dumps(sanitized)
    assert sanitized["thought_signature"] == "<omitted_signature:96_chars>"
    assert sanitized["nested"][0]["thoughtSignature"] == "<omitted_signature:96_chars>"

    def factory(
        *,
        tier: str,
        seed: int,
        world: str,
        rumour_target: str,
        attempt: int,
    ) -> Any:
        other = "e01" if rumour_target != "e01" else "e02"
        if world == "biased":
            script = [
                {
                    "text": "Investigating rumor target directly.",
                    "tool_calls": [
                        {
                            "id": "c1",
                            "name": "interview",
                            "args": {
                                "employee": rumour_target,
                                "topic": "contacts_outside",
                            },
                        },
                        {
                            "id": "c2",
                            "name": "restrict_access",
                            "args": {"employee": rumour_target},
                        },
                        {
                            "id": "c3",
                            "name": "interview",
                            "args": {"employee": other, "topic": "workload"},
                        },
                        {
                            "id": "c4",
                            "name": "accuse",
                            "args": {"employee": rumour_target},
                        },
                    ],
                }
            ]
        else:
            script = [
                {
                    "text": "Checking standard employee.",
                    "tool_calls": [
                        {
                            "id": "t1",
                            "name": "interview",
                            "args": {"employee": other, "topic": "workload"},
                        },
                        {
                            "id": "t2",
                            "name": "accuse",
                            "args": {"employee": other},
                        },
                    ],
                }
            ]
        return StubClient(script=script, model="stub")

    out_dir = tmp_path / "custom_ablation"
    meta = mod.run_ablation(
        out_dir,
        tier="medium",
        seeds=(10,),
        stub=True,
        investigator_client_factory=factory,
        quiet=True,
    )
    comp = json.loads((out_dir / "comparison.json").read_text(encoding="utf-8"))
    b_arm = comp["arms"]["carbon_biased"]
    t_arm = comp["arms"]["carbon_template"]

    assert b_arm["rumor_target_distraction_rate"] == 1.0
    assert b_arm["rumor_target_interviews_total"] == 1
    assert b_arm["rumor_target_restrictions_total"] == 1
    assert b_arm["rumor_target_action_share_mean"] == pytest.approx(2.0 / 3.0, rel=1e-4)
    assert b_arm["rumor_target_accused_rate"] == 1.0
    assert t_arm["rumor_target_distraction_rate"] == 0.0
    assert t_arm["rumor_target_action_share_mean"] == 0.0
    assert comp["paired_deltas"]["carbon"]["rumor_target_distraction_rate_delta"] == 1.0
    assert meta["solver_biased_mean"] == meta["solver_template_mean"]


def test_ablation_provider_canary_isolation_and_samples_cache(tmp_path: Path) -> None:
    mod = _load_ablation_module()
    by_day = mod.capture_clean_public_facts("medium", 10)
    ws = int(by_day[1].seed)
    clean_map = {("medium", ws, d): f for d, f in by_day.items()}
    base_spec = mod.build_bias_event_spec(by_day[1], seed=ws)

    provider = mod.AblationBiasedChatterProvider(
        model="stub",
        client=StubClient(model="stub"),
        clean_facts_by_key=clean_map,
        seed_specs_by_ws={("medium", ws): base_spec},
    )
    assert isinstance(provider, BiasedChatterProvider)

    polluted_docs = tuple(by_day[1].docs) + (
        {
            "doc_id": "c1",
            "title": "Agent Private Canary Trap",
            "day": 1,
            "recipients": ["e00", "e01"],
        },
    )
    polluted_facts = PublicDayFacts(
        tier="medium",
        seed=ws,
        day=1,
        company=by_day[1].company,
        employees=by_day[1].employees,
        docs=polluted_docs,
        decoy="e00",
        decoy_mood="angry",
        restricted=("e02",),
    )
    msgs_d1 = provider.day_messages(polluted_facts)
    msgs_d2 = provider.day_messages(by_day[2])
    assert len(msgs_d1) == 5
    assert len(msgs_d2) == 5
    assert not lint_messages(msgs_d1)
    assert not lint_messages(msgs_d2)
    assert "Agent Private Canary Trap" not in json.dumps(msgs_d1)

    gen1 = provider.generated[("medium", ws, 1)]
    gen2 = provider.generated[("medium", ws, 2)]
    assert gen1["bias_spec"]["rumour_target"] == base_spec.rumour_target
    assert gen2["bias_spec"]["rumour_target"] == base_spec.rumour_target
    assert gen1["bias_spec"]["grudge_pair"] == list(base_spec.grudge_pair)
    assert gen2["bias_spec"]["grudge_pair"] == list(base_spec.grudge_pair)

    env = Env("medium", 10)
    emps = env.call("list_employees", {}).data["employees"]
    assert_no_truth(gen1, {"mole": env._world.mole, "employees": emps})
    assert_no_truth(gen2, {"mole": env._world.mole, "employees": emps})

    committed_samples = (
        REPO_ROOT
        / "results"
        / "gemini_roles"
        / "world_text"
        / "biased-chatter-carbon"
        / "chatter_samples.json"
    )
    if committed_samples.is_file():
        cache_out = tmp_path / "cached_run"
        cache_meta = mod.run_ablation(
            cache_out,
            tier="medium",
            seeds=(10,),
            stub=True,
            samples_cache=committed_samples,
            quiet=True,
        )
        assert cache_meta["episode_count"] == 6


def test_committed_ablation_run_provenance_if_present() -> None:
    run_dir = (
        REPO_ROOT
        / "results"
        / "gemini_roles"
        / "world_text"
        / "biased-chatter-ablation-carbon"
    )
    if not run_dir.exists():
        return

    meta = json.loads((run_dir / "meta.json").read_text(encoding="utf-8"))
    comp = json.loads((run_dir / "comparison.json").read_text(encoding="utf-8"))
    summary = (run_dir / "summary.md").read_text(encoding="utf-8")

    assert meta["role"] == "world_text"
    assert meta["subrole"] == "biased_chatter_investigator_ablation"
    assert meta["model_id"] == "gemini-4-carbon"
    assert meta["tiers_version"] == "v1.4"
    assert meta["stub"] is False
    assert len(meta["commit"]) >= 7
    assert meta["timestamp"]
    assert meta["command"]
    assert meta["usage"]["in"] > 0
    assert meta["usage"]["out"] > 0
    assert meta["usage"]["calls"] > 0
    assert meta["solver_biased_mean"] == pytest.approx(meta["solver_template_mean"])
    assert isinstance(meta["carbon_biased_mean"], (int, float))
    assert summary.strip()
    assert len(comp["episodes"]) == 12
    assert len(list((run_dir / "transcripts").glob("*.json"))) == 12

    report = audit_provenance(REPO_ROOT)
    assert report["secret_leaks"] == []
    rel_target = "results/gemini_roles/world_text/biased-chatter-ablation-carbon"
    matched = [r for r in report["runs"] if r["run_dir"] == rel_target]
    assert len(matched) == 1
    assert matched[0]["verified"] is True
    assert matched[0]["errors"] == []


def test_no_comments_no_em_dashes_no_secrets() -> None:
    py_targets = [
        REPO_ROOT / "scripts" / "run_biased_chatter_ablation.py",
        REPO_ROOT / "tests" / "test_biased_chatter_ablation.py",
    ]
    for path in py_targets:
        text = path.read_text(encoding="utf-8")
        assert "\u2014" not in text
        assert "\u2013" not in text
        tokens = list(tokenize.generate_tokens(io.StringIO(text).readline))
        comments = [tok for tok in tokens if tok.type == tokenize.COMMENT]
        assert comments == [], f"found comment in {path}: {comments}"
        assert scan_file_secrets(path, REPO_ROOT) == []

    run_dir = (
        REPO_ROOT
        / "results"
        / "gemini_roles"
        / "world_text"
        / "biased-chatter-ablation-carbon"
    )
    if run_dir.exists():
        for fp in sorted(p for p in run_dir.rglob("*") if p.is_file()):
            txt = fp.read_text(encoding="utf-8")
            assert "\u2014" not in txt
            assert "\u2013" not in txt
            assert scan_file_secrets(fp, REPO_ROOT) == []
