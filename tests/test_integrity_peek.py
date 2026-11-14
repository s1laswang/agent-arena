"""CEO check (309f8c1): Env.peek_status()/verdict() are UI/grader helpers and must never be reachable by
an agent; peek_status must reveal nothing beyond the `status` tool; `make play` refuses judge seeds."""
from __future__ import annotations

import pytest

from canary.rules import HELDOUT_SEEDS, JUDGE_SEEDS
from tests.integrity_helpers import make_env

HIDDEN = ("peek_status", "verdict", "score", "ledger", "result", "_t_status", "__init__")


@pytest.mark.parametrize("name", HIDDEN)
def test_hidden_methods_not_callable_as_tools(name):
    env = make_env("medium", 3)
    before = env.ledger()
    r = env.call(name, {})
    assert r.ok is False
    assert "mole" not in str(r.data).lower() and str(env._world.mole) not in str(r.data)
    assert env.ledger() == before and not env.done


def test_hidden_methods_not_in_tools_spec():
    names = {t["name"] for t in make_env("medium", 3).tools_spec()}
    assert not names & set(HIDDEN)


def test_mcp_server_exposes_no_hidden_methods():
    srv = pytest.importorskip("canary.mcp_server")
    env = make_env("medium", 3)
    names = {t["name"] for t in env.tools_spec()}
    # the server publishes tools_spec 1:1 and forwards to Env.call, which rejects unknown names
    ep_cls = getattr(srv, "Episode", None)
    if ep_cls is None:
        pytest.skip("mcp_server.Episode not found")
    ep = ep_cls("medium", 7, "template")
    assert {t["name"] for t in ep.tools_spec()} == names
    for name in HIDDEN:
        r = ep.call(name, {})
        assert r.ok is False, name


def test_peek_status_equals_status_and_is_free():
    env = make_env("medium", 3)
    env.call("advance_day", {})
    peek = env.peek_status()
    st = env.call("status", {}).data
    assert set(peek) == set(st), set(peek) ^ set(st)
    for k in st:
        if k != "tool_calls_left":
            assert peek[k] == st[k], k
    # peek is free: repeated peeks never move the call budget or the ledger
    led = env.ledger()
    a = env.peek_status()["tool_calls_left"]
    for _ in range(50):
        env.peek_status()
    assert env.peek_status()["tool_calls_left"] == a and env.ledger() == led
    assert env._world.mole not in str(peek) or env._world.mole in str(env.call("list_employees", {}).data)


@pytest.mark.parametrize("seed", [min(JUDGE_SEEDS), max(JUDGE_SEEDS), min(HELDOUT_SEEDS), 0, 2999])
def test_make_play_refuses_non_play_seeds(seed):
    from canary import play
    with pytest.raises(SystemExit) as e:
        play.main(["--tier", "medium", "--seed", str(seed)])
    assert e.value.code == 2
