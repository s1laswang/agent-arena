import asyncio
import json
import os
import signal
import subprocess
import sys
import time

import pytest

from sleeper.company import World
from sleeper.mcp_server import build_server
from sleeper.tickets import make_day


def call(srv, name, args):
    r = asyncio.run(srv.call_tool(name, args))
    return r.structured_content or json.loads(r.content[0].text)


def srv(tmp_path, seat="finance_ap"):
    return build_server(World(make_day(0)), seat, None, str(tmp_path / "s.json"))


@pytest.mark.parametrize("name,args", [
    ("read_doc", {}),
    ("read_doc", {"id": 5}),
    ("read_doc", {"id": "nope"}),
    ("read_doc", {"bogus": 1}),
    ("close_ticket", {"id": "x"}),
    ("approve_payment", {"id": "p1"}),
    ("no_such_tool", {}),
    ("post_chat", {"to": 7, "body": None}),
])
def test_errors_are_json(tmp_path, name, args):
    r = call(srv(tmp_path), name, args)
    assert r["ok"] is False and r["error"]


def test_after_done(tmp_path):
    s = srv(tmp_path)
    s.finish()
    assert call(s, "read_chat", {})["error"] == "day over"
    assert (tmp_path / "s.json").exists()


def test_end_turn_dumps(tmp_path):
    s = srv(tmp_path)
    call(s, "end_turn", {})
    assert json.load(open(tmp_path / "s.json"))


def spawn(out):
    env = dict(os.environ, PYTHONPATH=os.getcwd())
    p = subprocess.Popen([sys.executable, "-m", "sleeper.mcp_server", "--seat", "finance_ap", "--day", "0", "--out", str(out)],
                         stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=env)
    time.sleep(4)
    return p


def test_sigterm_writes(tmp_path):
    out = tmp_path / "t.json"
    p = spawn(out)
    p.send_signal(signal.SIGTERM)
    p.wait(10)
    assert json.load(open(out))


def test_stdin_close_writes(tmp_path):
    out = tmp_path / "c.json"
    p = spawn(out)
    p.stdin.close()
    p.wait(10)
    assert json.load(open(out))
