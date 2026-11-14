"""Integrity over the MCP wire (owner: HEAD-INTEGRITY / exploit-hunter).

Parametrised over two servers:
  * real -> canary.mcp_server (skipped until HEAD-HARNESS lands it)
  * fake -> canary.redteam.fake_mcp, PLUMBING ONLY (proves the test harness works, says nothing about the env)
"""
from __future__ import annotations

import concurrent.futures as cf
import importlib.util
import json

import pytest

from canary.redteam.hunter import Server, find_mole
from canary.redteam.mcp_client import MCPClient, http_get

TIER, SEED = "easy", 7


@pytest.fixture(params=["real", "fake"])
def server(request, tmp_path):
    if request.param == "real":
        if importlib.util.find_spec("canary.mcp_server") is None:
            pytest.skip("canary.mcp_server not implemented yet (HEAD-HARNESS)")
        module = "canary.mcp_server"
    else:
        module = "canary.redteam.fake_mcp"
    srv = Server(module, TIER, SEED, tmp_path / "server.log")
    srv.kind = request.param
    yield srv
    srv.stop()


def client(srv) -> MCPClient:
    c = MCPClient(srv.url)
    c.initialize()
    return c


def accusations(srv) -> list[dict]:
    code, led = srv.ledger()
    assert code == 200
    entries = led.get("ledger", led) if isinstance(led, dict) else led
    return [e for e in entries if e.get("event") == "accused"]


def employees(c) -> list[str]:
    data = c.call("list_employees", {})["data"]
    rows = data["employees"] if isinstance(data, dict) else data
    return [r["id"] for r in rows]


def mole_of(srv) -> str:
    if srv.kind == "fake":
        return find_mole(srv.ledger()[1])
    from tests.integrity_helpers import make_env, true_mole
    return true_mole(make_env(TIER, SEED))


def test_ledger_token(server):
    for q in ["", "?token=", "?token=wrong", f"?token={server.token[:-1]}", f"?token={server.token}x"]:
        code, body = http_get(f"{server.base}/ledger{q}")
        assert code in (401, 403), (q, code)
        assert "accused" not in body and "mole" not in body
    assert server.ledger()[0] == 200


def test_tool_names_match_spec(server):
    names = {t["name"] for t in client(server).list_tools()}
    if server.kind == "real":
        from tests.integrity_helpers import make_env
        spec = {t["name"] for t in make_env(TIER, SEED).tools_spec()}
    else:
        from canary.redteam.fake_mcp import FakeEnv
        spec = {t["name"] for t in FakeEnv(TIER, SEED).tools_spec()}
    assert names == spec


def test_parallel_accuse(server):
    c = client(server)
    emps = employees(c)
    targets = (emps * 2)[:16]
    def go(e):
        cc = client(server)
        return cc.call("accuse", {"employee": e})
    with cf.ThreadPoolExecutor(16) as ex:
        res = list(ex.map(go, targets))
    assert sum(bool(r.get("ok")) for r in res) == 1, res
    assert len(accusations(server)) == 1
    later = c.call("accuse", {"employee": emps[0]})
    assert not later.get("ok")
    assert len(accusations(server)) == 1


def test_calls_after_end_change_nothing(server):
    c = client(server)
    emps = employees(c)
    assert c.call("accuse", {"employee": emps[0]})["ok"]
    before = server.ledger()[1]
    for tool, args in [("advance_day", {}), ("accuse", {"employee": emps[1]}), ("status", {}),
                       ("restrict_access", {"employee": emps[2]}), ("interview", {"employee": emps[1], "topic": "workload"})]:
        assert not c.call(tool, args).get("ok"), tool
    assert server.ledger()[1] == before


def _errs(c, emp):
    probes = [("interview", {"employee": emp, "topic": "bogus"}),
              ("interview", {"employee": emp, "topic": "workload", "extra": 1}),
              ("restrict_access", {"employee": [emp]}),
              ("accuse", {"employee": emp, "why": "x"}),
              ("accuse", {"employee": [emp]})]
    return [json.dumps(c.call(t, a), sort_keys=True).replace(emp, "<E>") for t, a in probes]


def test_error_parity_mole_vs_innocent(server):
    c = client(server)
    mole = mole_of(server)
    innocent = next(e for e in employees(c) if e != mole)
    em, ei = _errs(c, mole), _errs(c, innocent)
    assert em == ei
    assert [len(x) for x in em] == [len(x) for x in ei]
    assert not accusations(server), "malformed accuse must not be recorded"
