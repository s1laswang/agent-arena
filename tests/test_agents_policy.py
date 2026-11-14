import json
from types import SimpleNamespace as NS

import pytest

from canary.agents.llm_policy import HINTS, NUDGE, LLMPolicy, build_system_prompt
from canary.agents.loop import run_episode
from fake_env import FakeEnv


class Stub:
    """Local scripted stub (canary.llm StubClient may not exist yet)."""
    def __init__(self, script):
        self.script, self.i, self.seen = script, 0, []

    def chat(self, messages, tools=None, temperature=0.0, response_schema=None, max_tokens=None):
        self.seen.append([dict(m) for m in messages])
        s = self.script[min(self.i, len(self.script) - 1)]
        self.i += 1
        calls = [NS(id=f"c{self.i}_{j}", name=c["name"], args=c.get("args", {})) for j, c in enumerate(s.get("tool_calls", []))]
        return NS(text=s.get("text", ""), tool_calls=calls, usage={"in": 10, "out": 2, "cost_usd": 0.001})


def tc(name, **args):
    return {"tool_calls": [{"name": name, "args": args}]}


def test_plays_to_accusation():
    env = FakeEnv()
    stub = Stub([tc("status"), tc("check_leak_feed"), tc("advance_day"), tc("accuse", employee="e03")])
    pol = LLMPolicy("stub", client=stub)
    res = run_episode(env, pol, "stub")
    assert res.end_reason == "accused" and res.correct and res.score == 1.0
    assert [s.tool for s in res.steps] == ["status", "check_leak_feed", "advance_day", "accuse"]
    tools = [m for m in pol.transcript if m["role"] == "tool"]
    assert len(tools) == 3 and json.loads(tools[0]["content"])["ok"]
    assert pol.usage["calls"] == 4 and pol.usage["in"] == 40
    assert pol.transcript[0]["content"].startswith(env.instruction())


def test_hints():
    p = build_system_prompt("INSTR", "decoy_chase,ignored_delay")
    assert p.startswith("INSTR") and HINTS["decoy_chase"] in p and HINTS["ignored_delay"] in p
    assert HINTS["budget_waste"] not in build_system_prompt("INSTR", None)
    with pytest.raises(ValueError):
        build_system_prompt("x", "nope")
    assert len(HINTS) == 7


def test_nudge_then_fallback():
    env = FakeEnv()
    stub = Stub([{"text": "thinking"}, tc("list_employees"), {"text": "hmm"}, {"text": "still"}, tc("accuse", employee="e01")])
    pol = LLMPolicy("stub", client=stub)
    res = run_episode(env, pol, "stub")
    assert [s.tool for s in res.steps] == ["list_employees", "status", "accuse"]
    assert sum(1 for m in pol.transcript if m.get("content") == NUDGE) == 2
    assert not res.correct and res.score == 0.0


def test_multi_tool_queue():
    env = FakeEnv()
    stub = Stub([{"tool_calls": [{"name": "status"}, {"name": "list_employees"}, {"name": "check_leak_feed"}]},
                 tc("accuse", employee="e03")])
    pol = LLMPolicy("stub", client=stub)
    res = run_episode(env, pol, "stub")
    assert [s.tool for s in res.steps] == ["status", "list_employees", "check_leak_feed", "accuse"]
    assert stub.i == 2
    # every tool call id answered before the next model call
    ids = [m["tool_call_id"] for m in stub.seen[1] if m["role"] == "tool"]
    assert ids == ["c1_0", "c1_1", "c1_2"]


def test_context_truncation():
    pol = LLMPolicy("stub", client=Stub([tc("status")]), max_turns=2)
    pol.reset([], "I")
    for k in range(5):
        pol.transcript += [{"role": "assistant", "content": "", "tool_calls": [{"id": str(k), "name": "x", "args": {}}]},
                           {"role": "tool", "tool_call_id": str(k), "content": "z" * 5000}]
    ctx = pol._context()
    assert ctx[0]["role"] == "system" and sum(m["role"] == "assistant" for m in ctx) == 2
    assert len(ctx[2]["content"]) < 2100 and len(ctx[-1]["content"]) == 5000


def test_play_cli_fake(tmp_path):
    from canary.agents import play
    out = play.main(["--agent", "openai:gpt-x", "--tier", "easy", "--seeds", "0-1", "--fake", "--out", str(tmp_path / "r")],
                    client=Stub([tc("status"), tc("accuse", employee="e03")]))
    lines = (out / "episodes.jsonl").read_text().splitlines()
    assert len(lines) == 2
    for ln in lines:
        d = json.loads(ln)
        assert {"tier", "seed", "agent", "steps", "score", "accused", "correct", "final_day", "end_reason"} <= set(d)
    meta = json.loads((out / "meta.json").read_text())
    assert meta["provider"] == "openai" and meta["model"] == "gpt-x" and meta["seeds"] == [0, 1]
    assert (out / "transcripts" / "0.json").exists()


def test_run_id():
    from canary.agents.runlog import run_id, parse_seeds
    assert ":" not in run_id("openai:gpt-5-mini", "medium") and run_id("a:b", "easy").startswith("a_b-easy-")
    assert parse_seeds("0-2,7") == [0, 1, 2, 7]


# ---------------- frontier runners (command construction + hygiene only; live path untested)
from pathlib import Path


def test_opencode_cmd_and_hygiene():
    from canary.agents.frontier import opencode_run
    from canary.agents.frontier.common import REPO_ROOT, assert_clean, make_clean_workdir
    wd = make_clean_workdir()
    cmd = opencode_run.build_cmd(wd, "PROMPT", "gpt-5.6-sol", "http://127.0.0.1:8765/mcp")
    assert cmd[:4] == ["opencode", "run", "--model", "openai/gpt-5.6-sol"] and cmd[-1] == "PROMPT"
    cfg = json.loads((wd / "opencode.json").read_text())
    assert cfg["$schema"] == "https://opencode.ai/config.json"
    assert cfg["mcp"]["canary"] == {"type": "remote", "url": "http://127.0.0.1:8765/mcp", "enabled": True}
    assert cfg["permission"]["bash"] == "deny"
    assert_clean(wd, opencode_run.FILES)
    assert REPO_ROOT not in wd.parents
    (wd / "env.py").write_text("x")
    with pytest.raises(AssertionError):
        assert_clean(wd, opencode_run.FILES | {"env.py"})


def test_codex_cmd():
    from canary.agents.frontier import codex_run
    from canary.agents.frontier.common import make_clean_workdir
    wd = make_clean_workdir()
    cmd = codex_run.build_cmd(wd, "P", "gpt-5-mini", "http://h:1/mcp")
    s = " ".join(cmd)
    assert cmd[:2] == ["codex", "exec"] and "--skip-git-repo-check" in cmd and "--ignore-user-config" in cmd
    assert 'mcp_servers.canary.url="http://h:1/mcp"' in cmd
    assert cmd[cmd.index("--cd") + 1] == str(wd) and "--disable shell_tool" in s
    assert "config.toml" not in s and list(wd.iterdir()) == []


def test_child_env_strips_keys(monkeypatch):
    from canary.agents.frontier.common import child_env
    monkeypatch.setenv("OPENAI_API_KEY", "sk-x")
    assert "OPENAI_API_KEY" not in child_env()


def test_to_episode_shapes():
    from canary.agents.frontier.common import to_episode
    ledger = [{"t": 0, "day": 1, "event": "leak", "detail": {}},
              {"t": 5, "day": 3, "event": "accused", "detail": {"employee": "e04"}},
              {"t": 5, "day": 3, "event": "episode_end", "detail": {"reason": "accused", "score": 0.8, "correct": True}}]
    hist = [{"t": 0, "day": 1, "tool": "status", "args": {}, "result": {"ok": True}}]
    r = to_episode("easy", 1, "codex:m", ledger, hist)
    assert (r.accused, r.correct, r.score, r.end_reason, r.final_day, len(r.steps)) == ("e04", True, 0.8, "accused", 3, 1)
    full = {"score": 0.5, "end_reason": "accused", "accused": "e01", "correct": True, "final_day": 2, "steps": hist}
    assert to_episode("easy", 1, "a", full, []).score == 0.5
    assert to_episode("easy", 1, "a", [], []).end_reason == "error"


def test_run_seeds_fake_runner(tmp_path):
    from canary.agents.frontier import opencode_run
    from canary.agents.frontier.common import RunSpec, ServerCfg, run_seeds
    seen = []

    def runner(argv, cwd, **kw):
        seen.append(sorted(p.name for p in Path(cwd).iterdir()))
        return type("P", (), {"returncode": 0, "stdout": "{}", "stderr": ""})()

    spec = RunSpec("opencode:openai/m", "easy", [0, 1], tmp_path / "r", ServerCfg())
    out = run_seeds(spec, lambda wd, p: opencode_run.build_cmd(wd, p, "openai/m", spec.server.mcp_url),
                    opencode_run.FILES, fetch=False, runner=runner)
    assert seen == [["opencode.json"], ["opencode.json"]]
    assert (out / "transcripts" / "0.txt").exists() and json.loads((out / "meta.json").read_text())["provider"] == "opencode"
