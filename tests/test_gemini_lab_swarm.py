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
