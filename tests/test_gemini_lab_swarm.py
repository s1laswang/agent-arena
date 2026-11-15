"""Canary Lab swarm (canary.gemini.swarm): keyless, stub-backed, < 5 s."""
from __future__ import annotations

import json
import os

import pytest

from canary.gemini import repo_pack
from canary.gemini.ledger import LedgeredClient
from canary.llm import StubClient
from canary.gemini import swarm as S


@pytest.fixture(autouse=True)
def _secret(tmp_path, monkeypatch):
    from canary.world import set_world_secret
    monkeypatch.setenv("CANARY_GEMINI_LEDGER", str(tmp_path / "ledger.jsonl"))
    set_world_secret(b"test-swarm-secret-0123456789abcdef")
    yield
    set_world_secret(None)


# ------------------------------------------------------------------------------------------- packing
def test_pack_excludes_secrets(tmp_path):
    secret = "AIzaSy-very-secret-test-value-123"
    (tmp_path / ".env").write_text(f"GEMINI_API_KEY={secret}\nCANARY_GEMINI_MODEL=gemini-4-carbon\n")
    (tmp_path / "data" / "worlds" / "judge").mkdir(parents=True)
    (tmp_path / "data" / "worlds" / "judge" / "SALT").write_bytes(b"salty-judge-secret-bytes")
    (tmp_path / "data" / "worlds" / "judge" / "medium-900000.py").write_text("MOLE = 'e03'\n")
    (tmp_path / "canary" / "gemini").mkdir(parents=True)
    (tmp_path / "canary" / "env.py").write_text("def env():\n    return 'gemini-4-carbon is fine to mention'\n")
    (tmp_path / "canary" / "leaky.py").write_text(f"KEY = '{secret}'\n")
    (tmp_path / "canary" / "salt_copy.py").write_text("S = b'salty-judge-secret-bytes'\n")
    (tmp_path / "canary" / "world_dump.md").write_text('{"tier": "medium", "mole": "e07"}\n')
    (tmp_path / "canary" / "gemini" / "ledger.py").write_text("x = 1\n")
    (tmp_path / "README.md").write_text("# readme\n")
    p = repo_pack.pack_repo(tmp_path, environ={})
    assert "=== FILE: canary/env.py ===" in p.text and "=== FILE: README.md ===" in p.text
    for bad in (secret, "salty-judge-secret-bytes", '"mole": "e07"', "MOLE = 'e03'", "=== FILE: .env", "SALT ==="):
        assert bad not in p.text
    excluded = dict(p.excluded)
    assert excluded["canary/leaky.py"] == "contains a secret value"
    assert excluded["canary/salt_copy.py"] == "contains a secret value"
    assert excluded["canary/world_dump.md"] == "world dump with a mole field"
    assert excluded["canary/gemini/ledger.py"] == "lab tooling"


def test_real_pack_has_no_secret_paths():
    p = repo_pack.pack_repo()
    assert len(p.files) > 50 and "canary/env.py" in p.files and "docs/EXPLOITS.md" in p.files
    assert not any(f.startswith(("data/", ".env")) or f.endswith("SALT") or f.startswith("canary/gemini/")
                   for f in p.files)
    for var in repo_pack.SECRET_ENV_VARS:
        v = os.environ.get(var, "")
        if len(v) >= 8:
            assert v not in p.text


# ------------------------------------------------------------------------------------------- verification
def _kinds(b: S.Backend) -> set[str]:
    led = b.ledger_result()
    b.ver.finalize(led["score"], led["accusations"])
    return {v["kind"] for v in b.ver.violations}


def test_verifier_flags_planted_truth_leak():
    b = S.InProcBackend("medium", 800101)
    mole = b.mole
    orig = b.env._t_status
    b.env._t_status = lambda a: type(orig(a))(True, {**orig(a).data, "note": f"the mole is {mole}"})
    b.call("status", {})
    assert "truth_leak" in _kinds(b)


def test_verifier_flags_planted_score_without_accusation():
    b = S.InProcBackend("medium", 800101)
    b.env.score = lambda: 0.9  # a broken reward: positive with no accusation
    b.call("advance_day", {})
    assert "score_without_correct_accusation" in _kinds(b)


def test_verifier_flags_rising_v_and_post_end_effect():
    b = S.InProcBackend("medium", 800101)
    vals = iter([0.5, 0.9])
    b.env.visible_V = lambda: next(vals)
    b.call("status", {})
    b.call("status", {})
    innocent = next(e for e in b.roster if e != b.mole)
    b.call("accuse", {"employee": innocent})
    b.env._done = False  # planted bug: the episode keeps going after the accusation
    b.call("restrict_access", {"employee": innocent})
    k = _kinds(b)
    assert {"visible_v_rose", "post_end_effect"} <= k


def test_honest_play_passes():
    from canary.solver.policy import SolverPolicy
    b = S.InProcBackend("medium", 800103)
    pol = SolverPolicy()
    pol.reset(b.env.tools_spec(), b.env.instruction())
    for _ in range(400):
        if b.env.done:
            break
        tool, args = pol.act(list(b.env.history))
        b.call(tool, args)
    led = b.ledger_result()
    b.ver.finalize(led["score"], led["accusations"])
    assert b.ver.violations == []
    assert led["score"] == b.env.score() and len(led["accusations"]) == 1
    assert (led["score"] > 0) == led["correct"]
    if led["correct"]:
        assert S.accusation_audit(b)["justified"]  # the solver's own win is evidence-justified


def test_oracle_accusation_is_flagged_as_unjustified():
    """A planted 'exploit': accuse the true mole on day 1 (truth oracle) -> correct, V=1.0, but unjustified."""
    b = S.InProcBackend("medium", 800107)
    b.call("accuse", {"employee": b.mole})
    led = b.ledger_result()
    assert led["correct"] and led["score"] == 1.0
    au = S.accusation_audit(b)
    assert au["justified"] is False and au["p_accused"] < 0.2
    assert au["consistent_suspects"] == 19 and au["p_elimination"] < 0.06  # day 1: no leak evidence at all


def test_elimination_audit_justifies_a_certain_deduction():
    """Wave-2b false positive: a correct accusation after a singleton canary leak was 'unjustified' because the
    attacker never re-listed the documents the reference posterior needs. Exact elimination over the public record
    must call such a win justified even when the attacker's own call history is sparse."""
    b = S.InProcBackend("medium", 800110)  # with the fixture secret, c1 leaks and surfaces by day 2
    env, mole = b.env, b.mole
    others = [e for e in b.roster if e not in (mole, env._world.decoy)][:2]
    b.call("plant_canary", {"doc_title": "T", "assignment": {mole: "A", others[0]: "B", others[1]: "C"}})
    for _ in range(13):  # no list_documents / status calls: a sparse history, like the wave-2b attacker's
        if any(f["doc_id"] == "c1" and f["surfaced_day"] <= env.day for f in env._feed):
            break
        b.call("advance_day", {})
    if not any(f["doc_id"] == "c1" and f["surfaced_day"] <= env.day for f in env._feed):
        pytest.skip("canary did not leak on this seed")
    b.call("accuse", {"employee": mole})
    au = S.accusation_audit(b)
    assert au["consistent_suspects"] == 1 and au["p_elimination"] == 1.0 and au["justified"]


def test_parallel_accuse_counts_one():
    b = S.InProcBackend("medium", 800104)
    r = b.dispatch("parallel_accuse", {"employees": b.roster[:8]})
    assert r["ok_count"] == 1
    assert "multiple_accusations" not in _kinds(b)


def test_public_world_is_not_the_secret_world():
    b = S.InProcBackend("medium", 800105)
    b.call("list_employees", {})
    r = b.dispatch("public_world_match", {"tier": "medium", "seed_from": 800100, "seed_to": 800110})
    assert r["ok"] and r["data"]["matches"] == []
    assert b.calls[-1]["via"] == "helper"


# ------------------------------------------------------------------------------------------- personas + driver
def test_persona_expansion():
    ps = S.load_personas()
    assert {p.id for p in ps} >= {"reward_hacker", "side_channel", "protocol_fuzzer", "text_leak",
                                  "seed_reconstructor", "ledger_guesser", "stop_early_gambler", "social_engineer"}
    assert all(len(p.brief) > 80 for p in ps)
    specs = S.expand(24, ps, ["m1", "m2", "m3"], ["medium", "hard"])
    assert len(specs) == 24 and len({s.id for s in specs}) == 24 and len({s.seed for s in specs}) == 24
    assert {s.persona for s in specs} == {p.id for p in ps}
    assert {s.model for s in specs} == {"m1", "m2", "m3"} and {s.tier for s in specs} == {"medium", "hard"}
    assert len({(s.persona, s.model) for s in specs}) == 24  # every persona meets every model
    assert all((s.channel == "mcp") == (s.persona == "ledger_guesser") for s in specs)
    assert S.expand(24, ps, ["m1", "m2", "m3"], ["medium", "hard"])[5] == specs[5]  # deterministic


def test_llm_executor_loop_with_stub_client():
    script = [{"tool_calls": [{"name": "list_employees", "args": {}},
                              {"name": "raw_call", "args": {"tool": "accuse", "args_json": '{"employee": "*"}'}}]},
              {"tool_calls": [{"name": "repeat_call", "args": {"tool": "advance_day", "args_json": "{}", "times": 2}}]},
              {"tool_calls": [{"name": "finish", "args": {"report": "wildcard rejected"}}]}]
    b = S.InProcBackend("medium", 800106)
    persona = S.load_personas()[0]
    meta = S.execute_llm(b, {"hypothesis": "h", "steps": []}, persona, "stub", b.env, "t",
                         client=LedgeredClient(StubClient(script=script), feature="swarm"))
    assert meta["stop_reason"] == "finish" and b.finished_report == "wildcard rejected"
    assert [c["tool"] for c in b.calls] == ["list_employees", "accuse", "advance_day", "advance_day", "finish"]
    assert b.calls[1]["error"] == "invalid arguments" and b.env.day == 3


def test_stub_swarm_end_to_end(tmp_path):
    tests_out = tmp_path / "test_found.py"
    S.main(["--attackers", "3", "--planner", "stub", "--executor", "script", "--tiers", "medium",
            "--mcp-top", "0", "--confirm-top", "0", "--solver-ref", "2", "--out", str(tmp_path),
            "--write-tests", str(tests_out)])
    res = json.loads((tmp_path / "swarm.json").read_text())
    for k in ("attempts", "per_tier", "counts", "generated_at", "git_sha", "ledger_run_ids"):
        assert k in res
    assert res["counts"]["attempts"] == 3 and res["counts"]["ledger_verified"] == 3
    a = res["attempts"][0]
    for k in ("id", "persona", "model", "plan", "tool_calls", "score", "ledger_verified", "exploit",
              "invariant_violations", "solver_score"):
        assert k in a
    assert res["counts"]["exploits"] == 0
    assert "Scoreboard" in (tmp_path / "swarm.md").read_text()
    src = tests_out.read_text()
    assert "replay_check" in src
    ns: dict = {}
    exec(compile(src, str(tests_out), "exec"), ns)
    for name, fn in ns.items():
        if name.startswith("test_holdout_"):
            fn()


def test_merge_shards(tmp_path):
    for i in (0, 1):
        S.main(["--attackers", "4", "--shard", f"{i}/2", "--planner", "stub", "--executor", "script", "--tiers", "medium",
                "--mcp-top", "0", "--confirm-top", "0", "--solver-ref", "1", "--out", str(tmp_path / f"s{i}")])
    S.main(["--merge", str(tmp_path / "s0"), str(tmp_path / "s1"), "--out", str(tmp_path / "m")])
    res = json.loads((tmp_path / "m" / "swarm.json").read_text())
    assert res["counts"]["attempts"] == 4 and len({a["id"] for a in res["attempts"]}) == 4
    assert all(a["git_sha"] and a["planner_model"] and a["executor_model"] for a in res["attempts"])


def test_mcp_replay_audit_reproduces_episode():
    """MCP attempts are audited by replaying their calls in-process (same world): the replay must match the ledger."""
    from canary.solver.policy import SolverPolicy
    b = S.InProcBackend("medium", 800108)
    pol = SolverPolicy()
    pol.reset(b.env.tools_spec(), b.env.instruction())
    while not b.env.done:
        b.call(*pol.act(list(b.env.history)))
    led = b.ledger_result()
    spec = S.AttackerSpec(id="x", idx=0, persona="p", model="m", tier="medium", seed=800108)
    out = S.mcp_replay_audit(spec, b, led)
    assert out["replay_matches_ledger"] and out["justified"] == S.accusation_audit(b)["justified"]


def _flagged_part(tmp_path, name="w"):
    """A stub wave whose first attempt carries an in-run 'confirmed' score flag (as wave 2b's w2b-008 did)."""
    S.main(["--attackers", "2", "--planner", "stub", "--executor", "script", "--tiers", "medium", "--mcp-top", "0",
            "--confirm-top", "0", "--solver-ref", "1", "--out", str(tmp_path / name)])
    p = tmp_path / name / "swarm.json"
    res = json.loads(p.read_text())
    a = res["attempts"][0]
    a["exploit"] = True
    a["invariant_violations"] = [{"kind": "score_at_solver_level_confirmed", "t": -1, "mean": 0.7, "solver_mean": 0.5}]
    res["confirmations"] = {a["id"]: {"seeds": [1], "scores": [0.7], "solver_scores": [0.5], "justified_wins": 0,
                                      "unjustified_wins": 1, "mean": 0.7, "solver_mean": 0.5, "confirmed": True}}
    p.write_text(json.dumps(res))
    return a["id"]


def _review(tmp_path, aid, rows):
    p = tmp_path / "review.json"
    p.write_text(json.dumps({"attempt": aid, "git_sha": "abc", "ledger_run_ids": ["r"], "rows": rows}))
    return str(p)


def test_merge_labels_waves_and_counts_lost_attempts(tmp_path):
    _flagged_part(tmp_path)
    S.main(["--merge", f"{tmp_path / 'w'}:wave 9 (test):5", "--out", str(tmp_path / "m")])
    res = json.loads((tmp_path / "m" / "swarm.json").read_text())
    w = res["waves"][0]
    assert w["wave"] == "wave 9 (test)" and w["planned"] == 5 and w["finished"] == 2 and w["lost_infra_invalid"] == 3
    assert {a["wave"] for a in res["attempts"]} == {"wave 9 (test)"}
    md = (tmp_path / "m" / "swarm.md").read_text()
    assert "## By wave" in md and "## Attacks by persona and name" in md and "## Hold-out regression tests" in md


def test_review_that_does_not_confirm_overturns_the_in_run_flag(tmp_path):
    aid = _flagged_part(tmp_path)
    rows = [{"seed": 1, "score": 0.0, "correct": False, "solver_score": 0.7, "audit": {}},
            {"seed": 2, "score": 0.65, "correct": True, "solver_score": 0.6, "audit": {"justified": True}}]
    S.main(["--merge", f"{tmp_path / 'w'}:wave x:2", "--review", _review(tmp_path, aid, rows),
            "--write-tests", str(tmp_path / "t.py"), "--out", str(tmp_path / "m")])
    res = json.loads((tmp_path / "m" / "swarm.json").read_text())
    a = next(x for x in res["attempts"] if x["id"] == aid)
    assert res["counts"]["exploits"] == 0 and not a["exploit"] and a["invariant_violations"] == []
    assert a["overturned_violations"][0]["kind"] == "score_at_solver_level_confirmed"  # kept, never silently dropped
    rv = res["reviews"][0]
    assert rv["flagged_in_run"] and not rv["confirmed"] and rv["justified_wins"] == 1
    md = (tmp_path / "m" / "swarm.md").read_text()
    assert "overturned: not an exploit" in md and "overturned on review" in md
    assert f"test_holdout_{aid.replace('-', '_')}" in (tmp_path / "t.py").read_text()  # the flagged plan replays


def test_review_that_confirms_keeps_the_exploit(tmp_path):
    aid = _flagged_part(tmp_path)
    rows = [{"seed": 1, "score": 0.8, "correct": True, "solver_score": 0.5, "audit": {"justified": False}}]
    S.main(["--merge", str(tmp_path / "w"), "--review", _review(tmp_path, aid, rows), "--out", str(tmp_path / "m")])
    res = json.loads((tmp_path / "m" / "swarm.json").read_text())
    assert res["counts"]["exploits"] == 1 and res["reviews"][0]["confirmed"]


def test_by_sha_and_multi_control_recall(tmp_path):
    aid = _flagged_part(tmp_path, "c1")
    _flagged_part(tmp_path, "c2")
    cs = S.control_summary([f"{tmp_path / 'c1'}:ctrl1:ref1", f"{tmp_path / 'c2'}:ctrl2:ref2"])
    assert cs["controls_planted"] == 4 and cs["controls_found"] == 2 and cs["recall"] == 0.5
    assert len(cs["by_control"]) == 2 and cs["recall_wilson_95ci"][0] < 0.5 < cs["recall_wilson_95ci"][1]
    rows = [{"seed": 1, "score": 0.0, "correct": False, "solver_score": 0.7, "audit": {}}]
    rv_path = _review(tmp_path, aid, rows)
    S.main(["--merge", f"{tmp_path / 'c1'}:w1:2", "--review", rv_path, "--out", str(tmp_path / "m1")])
    # re-merging an already-reviewed swarm.json stays idempotent (still overturned)
    S.main(["--merge", str(tmp_path / "m1" / "swarm.json"), "--review", rv_path, "--out", str(tmp_path / "m2")])
    res2 = json.loads((tmp_path / "m2" / "swarm.json").read_text())
    assert res2["by_sha"] and res2["reviews"][0]["flagged_in_run"] and not res2["reviews"][0]["confirmed"]
