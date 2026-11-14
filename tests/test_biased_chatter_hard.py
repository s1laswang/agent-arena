from __future__ import annotations

import base64
import codecs
import importlib.util
import io
import json
from pathlib import Path
import sys
import tokenize

import pytest

from canary.agents.world_builder import assert_no_truth
from canary.env import Env
from canary.eval import run_episode
from canary.gemini import read_ledger
from canary.gemini.biased_chatter import BIAS_KINDS, BiasedChatterProvider, build_bias_event_spec
from canary.gemini.leak_encodings import extract_env_secrets, scan_messages_for_secret
from canary.gemini.provenance import audit_provenance, scan_file_secrets
from canary.gemini.roles_dashboard import _scan_run_for_secrets
from canary.llm import MissingKeyError, register_script
from canary.baselines import DoNothing
from canary.solver.policy import SolverPolicy
from canary.text.lint import lint_messages

REPO_ROOT = Path(__file__).resolve().parents[1]
COMMITTED_RUN_DIR = (
    REPO_ROOT
    / "results"
    / "gemini_roles"
    / "world_text"
    / "biased-chatter-hard-carbon"
)
SLACK_PREFIX = "\x23"


def _load_hard_module():
    mod_name = "run_biased_chatter_hard"
    script_path = REPO_ROOT / "scripts" / f"{mod_name}.py"
    spec = importlib.util.spec_from_file_location(mod_name, script_path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(autouse=True)
def _isolated_keyless_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    ledger_file = tmp_path / "ledger.jsonl"
    monkeypatch.setenv("CANARY_GEMINI_LEDGER", str(ledger_file))
    monkeypatch.setenv("GEMINI_API_KEY", "")
    monkeypatch.setenv("GOOGLE_GENERATIVE_AI_API_KEY", "")
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_GATEWAY_URL", raising=False)
    return ledger_file


def test_stub_cli_multi_day_hard_and_solver_parity(
    tmp_path: Path,
    _isolated_keyless_env: Path,
) -> None:
    mod = _load_hard_module()
    out_dir = tmp_path / "hard_stub_out"
    rc = mod.main(
        [
            "--stub",
            "--tier",
            "hard",
            "--seeds",
            "0,1",
            "--days",
            "1,4,8",
            "--out",
            str(out_dir),
        ]
    )
    assert rc == 0

    meta = json.loads((out_dir / "meta.json").read_text(encoding="utf-8"))
    samples_doc = json.loads((out_dir / "chatter_samples.json").read_text(encoding="utf-8"))
    parity_doc = json.loads((out_dir / "solver_parity.json").read_text(encoding="utf-8"))
    summary_md = (out_dir / "summary.md").read_text(encoding="utf-8")

    assert meta["role"] == "world_text"
    assert meta["subrole"] == "biased_chatter_hard"
    assert meta["tier"] == "hard"
    assert meta["tiers_version"] == "v1.4"
    assert meta["n_employees"] == 40
    assert meta["n_days"] == 21
    assert meta["seeds"] == [0, 1]
    assert meta["days"] == [1, 4, 8]
    assert meta["n_samples"] == 6
    assert meta["n_messages"] == 30
    assert meta["truth_leak_violations"] == 0
    assert meta["lint_violations"] == 0
    assert meta["encoding_scan_violations"] == 0
    assert meta["solver_parity_ok"] is True
    assert meta["stub"] is True
    assert summary_md.strip()

    assert len(samples_doc["samples"]) == 6
    assert [(s["seed"], s["day"]) for s in samples_doc["samples"]] == [
        (0, 1),
        (0, 4),
        (0, 8),
        (1, 1),
        (1, 4),
        (1, 8),
    ]

    assert parity_doc["parity_ok"] is True
    assert parity_doc["template_solver_catch_rate"] == 1.0
    assert parity_doc["biased_chatter_solver_catch_rate"] == 1.0
    assert parity_doc["biased_chatter_solver_mean_score"] == pytest.approx(
        parity_doc["template_solver_mean_score"]
    )
    assert parity_doc["biased_chatter_obvious_heuristic_mean_score"] == pytest.approx(-1.0)
    assert parity_doc["do_nothing_all_zero"] is True
    assert parity_doc["extra_api_calls_during_rollout"] == 0

    ledger_rows = read_ledger([_isolated_keyless_env])
    assert len(ledger_rows) == 6
    assert all(r["feature"] == "biased_chatter" for r in ledger_rows)

    fake_repo = tmp_path / "fake_repo"
    stub_dir = fake_repo / "results" / "gemini_roles" / "world_text" / "hard-stub"
    stub_dir.mkdir(parents=True)
    (stub_dir / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    prov = audit_provenance(fake_repo)
    assert prov["runs"][0]["verified"] is False
    assert "stub_run" in prov["runs"][0]["errors"]


def test_cached_provider_falls_back_to_template_with_zero_api_calls(
    tmp_path: Path,
    _isolated_keyless_env: Path,
) -> None:
    mod = _load_hard_module()
    env_ref, snapshots = mod.collect_public_day_snapshots("hard", 0, (1, 4, 8))
    assert len(snapshots[1]["employees"]) == 40

    synthetic_samples = []
    for day, pub in sorted(snapshots.items()):
        spec = build_bias_event_spec(pub, seed=0)
        by_id = {e["id"]: e for e in pub["employees"]}
        rt_name = by_id[spec.rumour_target]["name"]
        ga, gb = spec.grudge_pair
        sender_r = next(
            e["id"]
            for e in pub["employees"]
            if e["id"] not in {spec.rumour_target, spec.manager_id}
        )
        recip_r = next(
            e["id"]
            for e in pub["employees"]
            if e["id"] not in {sender_r, spec.rumour_target}
        )
        fwd_recip = next(e["id"] for e in pub["employees"] if e["id"] != spec.manager_id)
        msgs = [
            {
                "id": f"bc{day}-0",
                "day": day,
                "bias_type": "unverified_rumour",
                "channel": f"{SLACK_PREFIX}general",
                "sender": sender_r,
                "recipients": [recip_r],
                "subject": "Calendar blocks",
                "body": f"Heard {rt_name} ({spec.rumour_target}) had private external calls booked.",
            },
            {
                "id": f"bc{day}-1",
                "day": day,
                "bias_type": "grudge_bickering",
                "channel": f"{SLACK_PREFIX}cross-team",
                "sender": ga,
                "recipients": [gb],
                "subject": "Tracker overwrite",
                "body": f"{by_id[gb]['name']} ({gb}), your push overwrote our timeline numbers.",
            },
            {
                "id": f"bc{day}-2",
                "day": day,
                "bias_type": "grudge_bickering",
                "channel": f"{SLACK_PREFIX}cross-team",
                "sender": gb,
                "recipients": [ga],
                "subject": "Re: Tracker overwrite",
                "body": f"{by_id[ga]['name']} ({ga}), your draft was stale before standup.",
            },
            {
                "id": f"bc{day}-3",
                "day": day,
                "bias_type": "authority_bias",
                "channel": f"{SLACK_PREFIX}ops",
                "sender": spec.manager_id,
                "recipients": [fwd_recip],
                "subject": "Routine sign-off",
                "body": "I vouch for our standard export batch, no manual check needed.",
            },
            {
                "id": f"bc{day}-4",
                "day": day,
                "bias_type": "unplanned_doc_forward",
                "channel": "email",
                "sender": spec.manager_id,
                "recipients": [fwd_recip],
                "subject": f"Fwd: {spec.forwarded_doc_title}",
                "body": f"Forwarding notes on {spec.forwarded_doc_title} for quick alignment.",
            },
        ]
        synthetic_samples.append({"tier": "hard", "seed": 0, "day": day, "messages": msgs})

    provider = mod.CachedBiasedChatterProvider.from_samples(synthetic_samples, tier="hard")
    assert isinstance(provider, BiasedChatterProvider)

    horizon_env = Env("hard", 0, text_provider=provider)
    dn_res = run_episode(horizon_env, DoNothing(seed=0))
    assert dn_res.score == 0.0
    assert provider.sampled_hits == 3
    assert provider.template_fallback_days == 18

    bc_delivered = [
        m for m in horizon_env._messages.values() if str(m.get("id", "")).startswith("bc")
    ]
    assert len(bc_delivered) == 15
    assert {m["day"] for m in bc_delivered} == {1, 4, 8}
    assert not lint_messages(list(horizon_env._messages.values()))
    mod.audit_messages_against_world(bc_delivered, env_ref)

    solver_res = run_episode(Env("hard", 0, text_provider=provider), SolverPolicy())
    assert solver_res.correct is True
    assert not _isolated_keyless_env.exists()


def test_audit_detects_mole_and_decoy_covert_encodings() -> None:
    mod = _load_hard_module()
    env = Env("hard", 0)
    mole_id = env._world.mole
    decoy_id = env._world.decoy
    assert decoy_id is not None

    clean_msg = {
        "id": "bc1-0",
        "day": 1,
        "channel": "email",
        "sender": "e00",
        "recipients": ["e01"],
        "subject": "Q3 planning sync",
        "body": "Sharing updated timeline notes ahead of the afternoon sync.",
    }
    res = mod.audit_messages_against_world([clean_msg], env)
    assert res == {
        "truth_leak_violations": 0,
        "lint_violations": 0,
        "encoding_scan_violations": 0,
    }

    b64_mole = base64.b64encode(f"mole:{mole_id}".encode("utf-8")).decode("ascii")
    msg_b64_mole = dict(clean_msg, body=f"Reference tag {b64_mole} attached.")
    with pytest.raises(AssertionError):
        mod.audit_messages_against_world([msg_b64_mole], env)

    rot_decoy = codecs.encode(f"decoy:{decoy_id}", "rot_13")
    msg_rot_decoy = dict(clean_msg, body=f"Routing label {rot_decoy} confirmed.")
    with pytest.raises(AssertionError):
        mod.audit_messages_against_world([msg_rot_decoy], env)

    split_a = dict(clean_msg, id="bc1-0", body="Status check mole:")
    split_b = dict(clean_msg, id="bc4-0", day=4, body=f"{mole_id} updated.")
    with pytest.raises(AssertionError):
        mod.audit_messages_against_world([split_a, split_b], env)


def test_require_live_enforces_live_key_and_complete_llm_messages(
    tmp_path: Path,
) -> None:
    mod = _load_hard_module()
    with pytest.raises(MissingKeyError):
        mod.run_biased_chatter_hard(
            tmp_path / "missing_key_out",
            tier="hard",
            seeds=(0,),
            days=(1,),
            model="gemini-4-carbon",
            require_live=True,
            max_attempts=1,
        )

    _, snaps = mod.collect_public_day_snapshots("hard", 0, (1,))
    pub = snaps[1]
    spec = build_bias_event_spec(pub, seed=0)
    by_id = {e["id"]: e for e in pub["employees"]}
    ga, gb = spec.grudge_pair
    sender_r = next(
        e["id"]
        for e in pub["employees"]
        if e["id"] not in {spec.rumour_target, spec.manager_id}
    )
    recip_r = next(
        e["id"]
        for e in pub["employees"]
        if e["id"] not in {sender_r, spec.rumour_target}
    )
    fwd_recip = next(e["id"] for e in pub["employees"] if e["id"] != spec.manager_id)
    scripted_ok = {
        "messages": [
            {
                "bias_type": "unverified_rumour",
                "channel": f"{SLACK_PREFIX}engineering",
                "sender": sender_r,
                "recipients": [recip_r],
                "subject": "Hallway note",
                "body": f"Heard {by_id[spec.rumour_target]['name']} ({spec.rumour_target}) booked private calls.",
            },
            {
                "bias_type": "grudge_bickering",
                "channel": f"{SLACK_PREFIX}cross-team",
                "sender": ga,
                "recipients": [gb],
                "subject": "Missed handoff",
                "body": f"{by_id[gb]['name']} ({gb}), you dropped my edits from the tracker.",
            },
            {
                "bias_type": "grudge_bickering",
                "channel": f"{SLACK_PREFIX}cross-team",
                "sender": gb,
                "recipients": [ga],
                "subject": "Re: Missed handoff",
                "body": f"{by_id[ga]['name']} ({ga}), your figures arrived after cutoff.",
            },
            {
                "bias_type": "authority_bias",
                "channel": f"{SLACK_PREFIX}ops",
                "sender": spec.manager_id,
                "recipients": [fwd_recip],
                "subject": "Workflow approval",
                "body": "My macro workflow is solid, skip the manual reconciliation.",
            },
            {
                "bias_type": "unplanned_doc_forward",
                "channel": "email",
                "sender": spec.manager_id,
                "recipients": [fwd_recip],
                "subject": f"Fwd: {spec.forwarded_doc_title}",
                "body": f"Sharing {spec.forwarded_doc_title} notes directly so we align.",
            },
        ]
    }
    register_script("hard_biased_ok", [{"json": scripted_ok}])
    out_ok = tmp_path / "scripted_live_ok"
    meta_ok = mod.run_biased_chatter_hard(
        out_ok,
        tier="hard",
        seeds=(0,),
        days=(1,),
        model="stub:hard_biased_ok",
        require_live=True,
        max_attempts=1,
    )
    assert meta_ok["n_messages"] == 5
    assert meta_ok["n_llm_messages"] == 5
    assert meta_ok["n_fallback_messages"] == 0


def test_committed_hard_carbon_artifacts_and_provenance() -> None:
    assert COMMITTED_RUN_DIR.is_dir()

    meta = json.loads((COMMITTED_RUN_DIR / "meta.json").read_text(encoding="utf-8"))
    samples_doc = json.loads(
        (COMMITTED_RUN_DIR / "chatter_samples.json").read_text(encoding="utf-8")
    )
    parity_doc = json.loads(
        (COMMITTED_RUN_DIR / "solver_parity.json").read_text(encoding="utf-8")
    )
    summary_md = (COMMITTED_RUN_DIR / "summary.md").read_text(encoding="utf-8")

    assert meta["role"] == "world_text"
    assert meta["subrole"] == "biased_chatter_hard"
    assert meta["model_id"] == "gemini-4-carbon"
    assert len(meta["commit"]) >= 7 and meta["commit"] != "0000000"
    assert meta["timestamp"]
    assert meta["tier"] == "hard"
    assert meta["tiers_version"] == "v1.4"
    assert meta["n_employees"] == 40
    assert meta["n_days"] == 21
    assert meta["seeds"] == [0, 1, 2, 3]
    assert meta["days"] == [1, 4, 8]
    assert meta["n_samples"] == 12
    assert meta["n_messages"] == 60
    assert meta["n_llm_messages"] == 60
    assert meta["n_fallback_messages"] == 0
    assert meta["truth_leak_violations"] == 0
    assert meta["lint_violations"] == 0
    assert meta["encoding_scan_violations"] == 0
    assert meta["solver_parity_ok"] is True
    assert meta["stub"] is False
    assert meta["fake_env"] is False
    assert meta["smoke"] is False
    assert meta["usage"]["calls"] >= 12
    assert meta["usage"]["in"] > 0
    assert meta["usage"]["out"] > 0
    assert meta["usage"]["total_tokens"] > 0
    assert meta["usage"]["cost_usd"] > 0.0
    assert summary_md.strip()

    samples = samples_doc["samples"]
    assert len(samples) == 12
    assert [(s["seed"], s["day"]) for s in samples] == [
        (s, d) for s in (0, 1, 2, 3) for d in (1, 4, 8)
    ]

    by_seed_msgs: dict[int, list[dict]] = {0: [], 1: [], 2: [], 3: []}
    for s_item in samples:
        assert s_item["source"] == "gemini:gemini-4-carbon"
        assert s_item["n_llm_messages"] == 5
        assert s_item["n_fallback_messages"] == 0
        msgs = s_item["messages"]
        assert len(msgs) == 5
        kinds = [m["bias_type"] for m in msgs]
        assert set(kinds) == set(BIAS_KINDS)
        assert kinds.count("grudge_bickering") == 2
        assert not lint_messages(msgs)

        env = Env("hard", int(s_item["seed"]))
        emps = env.call("list_employees", {}).data["employees"]
        assert len(emps) == 40
        assert_no_truth(s_item, {"mole": env._world.mole, "employees": emps})
        _, world_targets = extract_env_secrets(env)
        assert scan_messages_for_secret(msgs, world_targets) == []
        by_seed_msgs[int(s_item["seed"])].extend(msgs)

    for seed_val, combined_msgs in by_seed_msgs.items():
        assert len(combined_msgs) == 15
        env = Env("hard", seed_val)
        _, world_targets = extract_env_secrets(env)
        assert scan_messages_for_secret(combined_msgs, world_targets) == []

    assert parity_doc["parity_ok"] is True
    assert parity_doc["seeds"] == [0, 1, 2, 3]
    assert parity_doc["sampled_days"] == [1, 4, 8]
    assert parity_doc["n_employees"] == 40
    assert parity_doc["n_days"] == 21
    assert parity_doc["biased_chatter_solver_catch_rate"] >= parity_doc["template_solver_catch_rate"]
    assert abs(parity_doc["solver_mean_score_delta"]) <= 0.05
    assert parity_doc["do_nothing_all_zero"] is True
    assert parity_doc["extra_api_calls_during_rollout"] == 0
    assert len(parity_doc["per_seed"]) == 4

    report = audit_provenance(REPO_ROOT)
    assert report["secret_leaks"] == []
    rel_dir = "results/gemini_roles/world_text/biased-chatter-hard-carbon"
    matched = [r for r in report["runs"] if r["run_dir"] == rel_dir]
    assert len(matched) == 1
    assert matched[0]["verified"] is True
    assert matched[0]["errors"] == []
    assert matched[0]["count"] == 12
    assert _scan_run_for_secrets(COMMITTED_RUN_DIR) is False

    mod = _load_hard_module()
    replay_prov = mod.CachedBiasedChatterProvider.from_samples(
        samples,
        tier="hard",
        model="gemini-4-carbon",
    )
    replay_solver = run_episode(Env("hard", 0, text_provider=replay_prov), SolverPolicy())
    assert round(float(replay_solver.score), 4) == parity_doc["per_seed"][0][
        "biased_chatter_solver"
    ]["score"]
    assert bool(replay_solver.correct) is True


def test_no_comments_no_em_dashes_no_secrets() -> None:
    py_targets = [
        REPO_ROOT / "scripts" / "run_biased_chatter_hard.py",
        REPO_ROOT / "tests" / "test_biased_chatter_hard.py",
    ]
    for path in py_targets:
        text = path.read_text(encoding="utf-8")
        assert "\u2014" not in text
        assert "\u2013" not in text
        tokens = list(tokenize.generate_tokens(io.StringIO(text).readline))
        comments = [tok for tok in tokens if tok.type == tokenize.COMMENT]
        assert comments == [], f"found comment in {path}: {comments}"
        assert scan_file_secrets(path, REPO_ROOT) == []

    if COMMITTED_RUN_DIR.exists():
        for fp in sorted(p for p in COMMITTED_RUN_DIR.rglob("*") if p.is_file()):
            txt = fp.read_text(encoding="utf-8")
            assert "\u2014" not in txt
            assert "\u2013" not in txt
            assert scan_file_secrets(fp, REPO_ROOT) == []
