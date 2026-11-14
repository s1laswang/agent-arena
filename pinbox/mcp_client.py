"""McpEpisodeClient: the EpisodeClient API (.instruction(), .tools(), .call()) spoken over MCP.

Lets the scripted agents (reference, baselines) play an episode served by pinbox/mcp_server.py,
over streamable HTTP or stdio. Sync wrapper over the async `mcp` SDK (needs mcp 2.x).

    # against a running server (Harbor solution, demos)
    python -m pinbox.mcp_client --url http://127.0.0.1:8765/mcp --agent reference [--admin-token T]
    # start a stdio server for an episode, play it, grade the server's state folder
    python -m pinbox.mcp_client --spec ap_run:7:2 --agent reference [--state-dir DIR]
    # poke at a server
    python -m pinbox.mcp_client --url URL --list-tools | --instruction | --call list_invoices --args '{"status":"all"}'

The last line printed by an agent run is one JSON object:
{"agent", "family", "calls", "error", "reward", "progress", "failure_tags"} (reward is null if no grade was available).
"""
from __future__ import annotations

import argparse
import functools
import json
import os
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


class McpClientError(RuntimeError):
    """The MCP connection failed (server down, crashed, bad URL). Not a tool error."""


def _to_dispatch(result) -> dict:
    """CallToolResult -> the dispatch dict {"ok", "result", "error"}."""
    text = "".join(getattr(c, "text", "") or "" for c in (result.content or []) if getattr(c, "type", "") == "text")
    try:
        out = json.loads(text)
    except ValueError:
        out = None
    if not (isinstance(out, dict) and "ok" in out):
        sc = getattr(result, "structured_content", None)
        out = sc if isinstance(sc, dict) and "ok" in sc else None
    if out is not None:
        return {"ok": bool(out.get("ok")), "result": out.get("result"), "error": out.get("error")}
    if result.is_error:
        return {"ok": False, "result": None, "error": text or "tool error"}
    return {"ok": True, "result": text, "error": None}


def _stdio_params(spec: str, state_dir=None, python: str | None = None, extra_env: dict | None = None):
    """StdioServerParameters that start `python -m pinbox.mcp_server SPEC --transport stdio`."""
    from mcp import StdioServerParameters
    args = ["-m", "pinbox.mcp_server", str(spec), "--transport", "stdio"]
    if state_dir is not None:
        args += ["--state-dir", str(state_dir)]
    pypath = str(REPO_ROOT)
    if os.environ.get("PYTHONPATH"):
        pypath = pypath + os.pathsep + os.environ["PYTHONPATH"]
    env = {"PYTHONPATH": pypath, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}
    env.update(extra_env or {})
    return StdioServerParameters(command=python or sys.executable, args=args, env=env, cwd=str(REPO_ROOT))


class McpEpisodeClient:
    """Same API as pinbox.client.EpisodeClient, but the episode lives in an MCP server.

    `server` is a URL string (streamable HTTP), a mcp StdioServerParameters, or (in tests) a
    low-level mcp Server object to talk to in-process. Use as a context manager, or call close().
    """

    def __init__(self, server, *, timeout: float = 120.0, family: str | None = None):
        try:
            from anyio.from_thread import start_blocking_portal
            from mcp import Client
        except ImportError as e:
            raise McpClientError(f"the MCP client needs the 'mcp' package (pip install 'mcp>=2.3,<3'): {e}") from e
        self._family = family
        self._tools = None
        self.calls_made = 0
        self._closed = False
        self._portal_cm = start_blocking_portal()
        self._portal = self._portal_cm.__enter__()
        try:
            self._client = Client(server, read_timeout_seconds=timeout)
            self._client_cm = self._portal.wrap_async_context_manager(self._client)
            self._client_cm.__enter__()
        except BaseException as e:
            self._portal_cm.__exit__(None, None, None)
            self._closed = True
            if isinstance(e, (KeyboardInterrupt, SystemExit)):
                raise
            raise McpClientError(f"could not connect to the MCP server: {_describe(e)}") from e

    # ------------------------------------------------------------ constructors
    @classmethod
    def http(cls, url: str, **kw) -> "McpEpisodeClient":
        return cls(url, **kw)

    @classmethod
    def stdio(cls, spec: str, state_dir=None, python: str | None = None, **kw) -> "McpEpisodeClient":
        """Start `python -m pinbox.mcp_server SPEC --transport stdio [--state-dir DIR]` and connect to it."""
        return cls(_stdio_params(spec, state_dir, python), **kw)

    # ------------------------------------------------------------ EpisodeClient API
    def instruction(self) -> str:
        """The server's MCP instructions; if the server sent none, the get_task tool's text (costs one call)."""
        text = self._client.instructions
        if text:
            return text
        out = self.call("get_task")
        if out["ok"] and isinstance(out["result"], dict):
            return str(out["result"].get("instruction", ""))
        return ""

    def tools(self) -> list[dict]:
        """[{"name", "description", "parameters"}] as listed by the server."""
        if self._tools is None:
            specs, cursor = [], None
            while True:
                res = self._run(functools.partial(self._client.list_tools, cursor=cursor))
                for t in res.tools:
                    specs.append({"name": t.name, "description": t.description or "",
                                  "parameters": dict(t.input_schema or {"type": "object", "properties": {}})})
                cursor = getattr(res, "next_cursor", None)
                if not cursor:
                    break
            self._tools = specs
        return [dict(s) for s in self._tools]

    def call(self, _tool, /, **args) -> dict:
        return self.call_args(_tool, args)

    def call_args(self, tool: str, args: dict | None = None) -> dict:
        """One tool call. Returns {"ok", "result", "error"}. Tool errors never raise;
        a dead connection raises McpClientError."""
        from mcp.shared.exceptions import MCPError
        self.calls_made += 1
        try:
            res = self._run(functools.partial(self._client.call_tool, tool, dict(args or {})))
        except MCPError as e:  # JSON-RPC error from the server: report it like a tool error
            return {"ok": False, "result": None, "error": f"MCP error: {e}"}
        return _to_dispatch(res)

    # ------------------------------------------------------------ extras
    @property
    def server_name(self) -> str | None:
        info = self._client.server_info
        return getattr(info, "name", None) if info else None

    def family(self) -> str:
        """The task family, from the tool list (the one family whose tool names match exactly)."""
        if self._family:
            return self._family
        from .tasks import all_tasks
        from .tools import tool_specs
        names = {t["name"] for t in self.tools()}
        matches = [t.family for t in all_tasks() if {s["name"] for s in tool_specs(t.family)} == names]
        if len(matches) != 1:
            raise McpClientError("cannot tell the task family from the server's tools; pass family=... / --family")
        self._family = matches[0]
        return self._family

    def _run(self, fn):
        if self._closed:
            raise McpClientError("client is closed")
        try:
            return self._portal.call(fn)
        except Exception as e:
            from mcp.shared.exceptions import MCPError
            if isinstance(e, MCPError):
                raise
            raise McpClientError(f"MCP connection failed: {_describe(e)}") from e

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self._client_cm.__exit__(None, None, None)
        except BaseException:
            pass
        finally:
            try:
                self._portal_cm.__exit__(None, None, None)
            except BaseException:
                pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False


def _describe(e: BaseException) -> str:
    """Readable text for an exception, unwrapping exception groups."""
    inner = getattr(e, "exceptions", None)
    if inner:
        return "; ".join(_describe(x) for x in inner)
    return f"{type(e).__name__}: {e}" if str(e) else type(e).__name__


# ---------------------------------------------------------------- agents over MCP

def agent_for(name: str, family: str):
    """A scripted agent callable agent(client) by name: reference, do_nothing, a naive policy, ladder:<name>.
    (stop_early_* needs the local episode, so it is not offered over MCP.)"""
    from .tasks import get_task
    task = get_task(family)
    if name == "reference":
        return task.reference
    if name == "do_nothing":
        return lambda client: None
    naive = task.naive_policies()
    if name in naive:
        return naive[name]
    if name.startswith("ladder:"):
        for lname, fn in task.ladder():
            if lname == name[len("ladder:"):]:
                return fn
    return None


def run_agent(client: McpEpisodeClient, agent: str = "reference") -> dict:
    """Run a scripted agent through the MCP client. Returns {"agent", "family", "calls", "error"}."""
    from .client import AgentStopped
    family = client.family()
    fn = agent_for(agent, family)
    if fn is None:
        raise ValueError(f"unknown agent {agent!r} for family {family}")
    error = None
    try:
        fn(client)
    except AgentStopped:
        pass
    except McpClientError:
        raise
    except Exception as e:
        error = f"{type(e).__name__}: {e}"
    return {"agent": agent, "family": family, "calls": client.calls_made, "error": error}


def base_url(mcp_url: str) -> str:
    """http://host:8765/mcp -> http://host:8765"""
    u = urllib.parse.urlsplit(mcp_url)
    return urllib.parse.urlunsplit((u.scheme, u.netloc, "", "", ""))


def fetch_admin(mcp_url: str, route: str, token: str, timeout: float = 30.0) -> str:
    """GET <server>/admin/<route>?token=... and return the body text (raises urllib.error.HTTPError on 403)."""
    url = f"{base_url(mcp_url)}/admin/{route}?{urllib.parse.urlencode({'token': token})}"
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return r.read().decode("utf-8")


def fetch_grade(mcp_url: str, token: str) -> dict:
    return json.loads(fetch_admin(mcp_url, "grade", token))


def wait_for_server(mcp_url: str, seconds: float) -> bool:
    """Wait until the HTTP server answers anything at /healthz (any status). True if it did."""
    url = f"{base_url(mcp_url)}/healthz"
    end = time.monotonic() + max(0.0, seconds)
    while True:
        try:
            with urllib.request.urlopen(url, timeout=5):
                return True
        except urllib.error.HTTPError as e:
            e.close()
            return True
        except (urllib.error.URLError, OSError):
            if time.monotonic() >= end:
                return False
            time.sleep(0.5)


def _grade_folder(state_dir) -> dict | None:
    from .grader import grade_state
    from .state import load_json
    path = Path(state_dir) / "state.json"
    if not path.exists():
        return None
    return grade_state(load_json(path)).to_dict()


# ---------------------------------------------------------------- CLI

def _setup_stdout() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="backslashreplace")
        except (AttributeError, ValueError, OSError):
            pass


def main(argv=None) -> int:
    _setup_stdout()
    p = argparse.ArgumentParser(prog="python -m pinbox.mcp_client",
                                description="Talk to a Poisoned Inbox MCP server; run a scripted agent over MCP")
    where = p.add_mutually_exclusive_group(required=True)
    where.add_argument("--url", help="streamable HTTP endpoint, e.g. http://127.0.0.1:8765/mcp")
    where.add_argument("--spec", help="start a stdio server for this episode (ap_run:7:2 or an episode folder)")
    p.add_argument("--state-dir", help="with --spec: the server's state folder (default: a new temp folder)")
    p.add_argument("--agent", default=None, help="reference (default when nothing else is asked), do_nothing, "
                                                  "a naive policy name, or ladder:<name>")
    p.add_argument("--family", default=None, help="task family (default: worked out from the tool list)")
    p.add_argument("--admin-token", default=os.environ.get("PINBOX_ADMIN_TOKEN"),
                   help="with --url: fetch the grade from /admin/grade after the run")
    p.add_argument("--wait", type=float, default=60.0, help="with --url: seconds to wait for the server (default 60)")
    p.add_argument("--timeout", type=float, default=120.0, help="seconds per MCP request")
    p.add_argument("--list-tools", action="store_true")
    p.add_argument("--instruction", action="store_true")
    p.add_argument("--call", metavar="TOOL", help="make one tool call and print the result")
    p.add_argument("--args", default="{}", help="JSON object of arguments for --call")
    a = p.parse_args(argv)
    try:
        import mcp  # noqa: F401
    except ImportError as e:
        print(f"error: the MCP client needs the 'mcp' package (pip install 'mcp>=2.3,<3'): {e}", file=sys.stderr)
        return 2

    if a.url:
        if a.wait and not wait_for_server(a.url, a.wait):
            print(f"error: no server answered at {base_url(a.url)} within {a.wait:.0f}s", file=sys.stderr)
            return 3
        target, state_dir = a.url, None
    else:
        state_dir = a.state_dir or tempfile.mkdtemp(prefix="pinbox-mcp-client-")
        target = _stdio_params(a.spec, state_dir)

    try:
        call_args = json.loads(a.args)
    except ValueError as e:
        print(f"error: --args is not valid JSON: {e}", file=sys.stderr)
        return 2

    try:
        with McpEpisodeClient(target, timeout=a.timeout, family=a.family) as client:
            if a.list_tools:
                print(json.dumps(client.tools(), ensure_ascii=False, indent=2))
            if a.instruction:
                print(client.instruction())
            if a.call:
                print(json.dumps(client.call_args(a.call, call_args), ensure_ascii=False, indent=2))
            if a.list_tools or a.instruction or a.call:
                if not a.agent:
                    return 0
            run = run_agent(client, a.agent or "reference")
    except McpClientError as e:
        print(f"error: {e}", file=sys.stderr)
        if state_dir is not None and not a.state_dir:
            try:
                os.rmdir(state_dir)  # only removes our own temp folder, and only if it is empty
            except OSError:
                pass
        return 3
    except (ValueError, KeyError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    report = None
    if a.url and a.admin_token:
        try:
            report = fetch_grade(a.url, a.admin_token)
        except (urllib.error.URLError, OSError, ValueError) as e:
            print(f"warning: could not fetch the grade: {e}", file=sys.stderr)
    elif state_dir is not None:
        report = _grade_folder(state_dir)
        print(f"server state folder: {state_dir}", file=sys.stderr)

    if report:
        print(f"{report['episode_id']}: reward {report['reward']}  progress {report['progress']}  "
              f"calls {report.get('calls')}")
        for c in report.get("checks", []):
            if not c.get("passed"):
                print(f"  FAIL  {c.get('name')} [{c.get('tag')}]  - {c.get('detail')}")
    if run["error"]:
        print(f"agent error: {run['error']}", file=sys.stderr)
    summary = dict(run)
    summary.update({"reward": report.get("reward") if report else None,
                    "progress": report.get("progress") if report else None,
                    "failure_tags": report.get("failure_tags") if report else None})
    print(json.dumps(summary, ensure_ascii=False))
    return 1 if run["error"] else 0


if __name__ == "__main__":
    sys.exit(main())
