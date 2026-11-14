"""Tests for the MCP server and client (pinbox/mcp_server.py, pinbox/mcp_client.py).

Skipped cleanly when the `mcp` package is not installed (bare Python runs `python -m pinbox eval` fine).
Run:  python -m unittest tests/test_mcp.py -v     (from the repo root, in a venv with mcp 2.x)
"""
from __future__ import annotations

import importlib.util
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

HAS_MCP = importlib.util.find_spec("mcp") is not None
TOKEN = "test-admin-token-42"
SECRET_KEYS = {"hidden", "truth", "payload_ids", "phones", "plan", "injections", "pending"}


def _families() -> list[str]:
    from pinbox.tasks import all_tasks
    return [t.family for t in all_tasks()]


def _spec(family: str) -> str:
    """One eval episode per family, at its highest difficulty (the most traps)."""
    from pinbox.tasks import get_task
    specs = get_task(family).eval_specs()
    top = max(d for _, d in specs)
    seed = min(s for s, d in specs if d == top)
    return f"{family}:{seed}:{top}"


def _spec_with_events(family: str) -> str:
    """An eval episode that has a not-yet-fired event (late arrival), if the family has one."""
    from pinbox.episode import Episode
    from pinbox.tasks import get_task
    for seed, diff in sorted(get_task(family).eval_specs(), key=lambda sd: (-sd[1], sd[0])):
        if Episode.create(family, seed, diff).state.get("events", {}).get("pending"):
            return f"{family}:{seed}:{diff}"
    return _spec(family)


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _env(**extra) -> dict:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT) + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    env.update(extra)
    return env


def _keys(obj, out: set) -> set:
    if isinstance(obj, dict):
        for k, v in obj.items():
            out.add(k)
            _keys(v, out)
    elif isinstance(obj, list):
        for v in obj:
            _keys(v, out)
    return out


def _tempdir(test: unittest.TestCase, prefix: str) -> Path:
    d = Path(tempfile.mkdtemp(prefix=prefix))
    test.addCleanup(shutil.rmtree, d, True)
    return d


# ====================================================================== no mcp needed

class LoadEpisodeTest(unittest.TestCase):
    """load_episode() only uses stdlib, so this runs everywhere."""

    def test_spec_folder_and_resume(self):
        from pinbox.episode import Episode
        from pinbox.mcp_server import load_episode
        fam = _families()[0]
        spec = _spec(fam)
        sd = _tempdir(self, "pinbox-mcp-t-")
        ep = load_episode(spec, sd)
        self.assertTrue((sd / "state.json").exists())
        ep.call("get_task", {})
        self.assertEqual(len(Episode.load(sd).trajectory), 1, "state must be saved after every call")
        again = load_episode(spec, sd)  # same folder, same episode -> resume
        self.assertEqual(len(again.trajectory), 1)
        other = f"{fam}:{12345}:{ep.difficulty}"
        with self.assertRaises(ValueError):
            load_episode(other, sd)  # a different episode in a used folder is refused
        with self.assertRaises(ValueError):
            load_episode("not a spec", _tempdir(self, "pinbox-mcp-t-"))

    def test_episode_folder_is_copied_not_changed(self):
        from pinbox.episode import Episode
        from pinbox.mcp_server import load_episode
        fam = _families()[0]
        src = _tempdir(self, "pinbox-mcp-src-")
        Episode.create(fam, 3, 1, path=src)
        before = (src / "state.json").read_bytes()
        sd = _tempdir(self, "pinbox-mcp-t-")
        ep = load_episode(str(src), sd)
        ep.call("get_task", {})
        self.assertEqual((src / "state.json").read_bytes(), before)
        self.assertEqual(len(Episode.load(sd).trajectory), 1)


# ====================================================================== in-process (fast)

@unittest.skipUnless(HAS_MCP, "mcp not installed")
class InProcessTest(unittest.TestCase):
    """Server object + McpEpisodeClient in one process (no subprocess, no port)."""

    def _open(self, family, spec=None):
        from pinbox.mcp_client import McpEpisodeClient
        from pinbox.mcp_server import build_server, load_episode
        sd = _tempdir(self, "pinbox-mcp-t-")
        ep = load_episode(spec or _spec(family), sd)
        client = McpEpisodeClient(build_server(ep), timeout=60)
        self.addCleanup(client.close)
        return ep, client, sd

    def test_tools_are_exactly_tool_specs(self):
        from pinbox.tools import tool_specs
        for fam in _families():
            with self.subTest(family=fam):
                ep, client, _ = self._open(fam)
                got = client.tools()
                want = tool_specs(fam)
                self.assertEqual([t["name"] for t in got], [t["name"] for t in want])
                for g, w in zip(got, want):
                    self.assertEqual(g["parameters"], w["parameters"], g["name"])
                    self.assertEqual(g["description"], w["description"], g["name"])
                    self.assertEqual(g["parameters"].get("type"), "object")
                self.assertIn("get_task", [t["name"] for t in got])
                self.assertEqual(client.family(), fam)

    def test_instruction_and_get_task(self):
        for fam in _families():
            with self.subTest(family=fam):
                ep, client, _ = self._open(fam)
                self.assertEqual(client.instruction(), ep.instruction())
                self.assertEqual(ep.state["calls"], 0, "reading MCP instructions must not cost a tool call")
                out = client.call("get_task")
                self.assertTrue(out["ok"], out)
                self.assertEqual(out["result"]["instruction"], ep.instruction())

    def test_calls_forward_and_persist(self):
        from pinbox.episode import Episode
        fam = _families()[0]
        ep, client, sd = self._open(fam)
        out = client.call("list_emails", folder="all")
        self.assertTrue(out["ok"], out)
        self.assertEqual(set(out), {"ok", "result", "error"})
        bad = client.call("list_emails", folder="nope")          # enum error
        self.assertFalse(bad["ok"])
        self.assertIn("folder", bad["error"])
        unknown = client.call("no_such_tool")
        self.assertFalse(unknown["ok"])
        self.assertIn("unknown tool", unknown["error"])
        extra = client.call("get_task", surprise=1)                # unknown args are errors
        self.assertFalse(extra["ok"])
        name_arg = client.call_args("read_email", {"name": "x"})  # an arg called "name" must not clash
        self.assertFalse(name_arg["ok"])
        self.assertEqual(ep.state["calls"], 5)
        saved = Episode.load(sd)
        self.assertEqual(len(saved.trajectory), 5, "every call is saved to the state folder")
        self.assertEqual(saved.trajectory[0]["tool"], "list_emails")

    def test_finnish_text_survives(self):
        fam = _families()[0]
        ep, client, _ = self._open(fam)
        out = client.call("get_task")
        self.assertIn(ep.state["company"]["name"], out["result"]["instruction"])
        self.assertEqual(out["result"]["instruction"], ep.instruction())

    def test_no_hidden_data_through_any_tool(self):
        """Sweep every read tool the agent has; nothing from state['hidden'] or pending events comes back."""
        from pinbox.tools import tool_specs, write_tool_names
        for fam in _families():
            with self.subTest(family=fam):
                ep, client, _ = self._open(fam, _spec_with_events(fam))
                hidden = ep.state.get("hidden", {})
                writes = write_tool_names(fam)
                responses = []
                for spec in tool_specs(fam):
                    if spec["name"] in writes or spec["parameters"].get("required"):
                        continue
                    responses.append(client.call(spec["name"]))
                    for pname, p in spec["parameters"]["properties"].items():
                        for value in p.get("enum", []):
                            responses.append(client.call(spec["name"], **{pname: value}))
                mails = client.call("list_emails", folder="all")["result"]["emails"]
                for m in mails:
                    responses.append(client.call("read_email", email_id=m["id"]))
                docs = client.call("list_documents")
                if docs["ok"]:
                    for d in docs["result"].get("documents", []):
                        responses.append(client.call("read_document", doc_id=d["id"]))
                responses.append(client.call("search_contacts", query=""))
                # attempts to reach files or secrets by name
                responses.append(client.call("read_document", doc_id="../state.json"))
                responses.append(client.call("read_email", email_id="hidden"))
                responses.append(client.call("hidden"))
                responses.append(client.call("__dict__"))

                text = json.dumps(responses, ensure_ascii=False)
                keys = _keys(responses, set())
                self.assertFalse(keys & SECRET_KEYS, f"secret keys in tool output: {keys & SECRET_KEYS}")
                for pid in hidden.get("payload_ids", []) or []:
                    self.assertNotIn(str(pid), text)
                for number, who in (hidden.get("phones") or {}).items():
                    reply = who.get("reply") if isinstance(who, dict) else None
                    if reply and len(reply) > 40:
                        self.assertNotIn(reply, text, "a phone reply leaked without a call")
                # items of events that have not fired yet must not be visible
                for ev in ep.state.get("events", {}).get("pending", []):
                    for eff in ev.get("effects", []):
                        item = eff.get("item")
                        if isinstance(item, dict):
                            for key in ("invoice_id", "ticket_id", "order_id", "id"):
                                if key in item:
                                    self.assertNotIn(f'"{item[key]}"', text,
                                                     f"future event item {item[key]} visible early")

    def test_no_resources_or_prompts(self):
        """Only tools are exposed: no resources, no prompts that could carry state."""
        import anyio
        from mcp import Client
        from mcp.shared.exceptions import MCPError
        from pinbox.mcp_server import build_server, load_episode
        ep = load_episode(_spec(_families()[0]), _tempdir(self, "pinbox-mcp-t-"))

        async def go():
            async with Client(build_server(ep)) as c:
                caps = c.server_capabilities
                self.assertIsNone(getattr(caps, "resources", None))
                self.assertIsNone(getattr(caps, "prompts", None))
                for fn in (c.list_resources, c.list_prompts):
                    try:
                        res = await fn()
                    except MCPError:
                        continue
                    items = getattr(res, "resources", None) or getattr(res, "prompts", None) or []
                    self.assertEqual(list(items), [])
        anyio.run(go)


# ====================================================================== stdio (subprocess)

@unittest.skipUnless(HAS_MCP, "mcp not installed")
class StdioTest(unittest.TestCase):
    def test_reference_over_stdio_scores_1_every_family(self):
        from pinbox.client import EpisodeClient
        from pinbox.episode import Episode
        from pinbox.grader import grade_state
        from pinbox.mcp_client import McpEpisodeClient, run_agent
        from pinbox.state import load_json
        from pinbox.tools import tool_specs
        for fam in _families():
            with self.subTest(family=fam):
                spec = _spec_with_events(fam)  # includes a late arrival when the family has one
                sd = _tempdir(self, "pinbox-mcp-stdio-ö ")  # space + non-ASCII in the path on purpose
                with McpEpisodeClient.stdio(spec, state_dir=sd, timeout=120) as client:
                    self.assertEqual([t["name"] for t in client.tools()], [t["name"] for t in tool_specs(fam)])
                    run = run_agent(client, "reference")
                self.assertIsNone(run["error"], run)
                self.assertEqual(run["family"], fam)
                state = load_json(sd / "state.json")
                report = grade_state(state)
                self.assertEqual(report.reward, 1, report.summary())
                self.assertEqual(state["events"].get("pending"), [], "late events fired inside the server")
                # the MCP run is the same run as in-process: same calls, same results
                served = Episode.load(sd)
                local = Episode.from_spec(spec, runs_dir=_tempdir(self, "pinbox-mcp-local-"))
                local.task.reference(EpisodeClient(local))
                self.assertEqual(served.trajectory, local.trajectory)
                self.assertEqual(run["calls"], len(served.trajectory))

    def test_client_cli_over_stdio(self):
        fam = _families()[0]
        sd = _tempdir(self, "pinbox-mcp-cli-")
        p = subprocess.run([sys.executable, "-m", "pinbox.mcp_client", "--spec", _spec(fam), "--agent", "reference",
                            "--state-dir", str(sd)], cwd=str(ROOT), env=_env(), capture_output=True,
                           text=True, encoding="utf-8", timeout=300)
        self.assertEqual(p.returncode, 0, p.stderr)
        summary = json.loads(p.stdout.strip().splitlines()[-1])
        self.assertEqual(summary["reward"], 1, p.stdout)
        self.assertEqual(summary["family"], fam)


# ====================================================================== streamable HTTP (subprocess)

class _HttpServer:
    """`python -m pinbox serve SPEC --transport http` on a free port; always stopped."""

    def __init__(self, test: unittest.TestCase, spec: str, token: str | None = TOKEN):
        self.port = _free_port()
        self.url = f"http://127.0.0.1:{self.port}/mcp"
        self.base = f"http://127.0.0.1:{self.port}"
        self.state_dir = _tempdir(test, "pinbox-mcp-http-")
        self.log_path = self.state_dir.parent / (self.state_dir.name + ".log")
        test.addCleanup(self._remove_log)
        cmd = [sys.executable, "-m", "pinbox", "serve", spec, "--transport", "http",
               "--host", "127.0.0.1", "--port", str(self.port)]
        if token:
            cmd += ["--admin-token", token]
        self.log = open(self.log_path, "w", encoding="utf-8")
        self.proc = subprocess.Popen(cmd, cwd=str(ROOT), env=_env(PINBOX_STATE_DIR=str(self.state_dir)),
                                     stdin=subprocess.DEVNULL, stdout=self.log, stderr=subprocess.STDOUT)
        test.addCleanup(self.stop)
        self._wait(test)

    def _wait(self, test, seconds: float = 90.0):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            if self.proc.poll() is not None:
                test.fail(f"server exited early ({self.proc.returncode}):\n{self.read_log()}")
            try:
                with urllib.request.urlopen(self.base + "/healthz", timeout=2) as r:
                    if r.status == 200:
                        return
            except (urllib.error.URLError, OSError):
                time.sleep(0.3)
        test.fail(f"server did not start in {seconds}s:\n{self.read_log()}")

    def read_log(self) -> str:
        try:
            self.log.flush()
            return self.log_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return ""

    def get(self, path: str, headers: dict | None = None):
        req = urllib.request.Request(self.base + path, headers=headers or {})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.status, r.read().decode("utf-8")
        except urllib.error.HTTPError as e:
            with e:
                return e.code, e.read().decode("utf-8", errors="replace")

    def _remove_log(self):
        # On Windows the venv python.exe is a launcher; its child may hold the file for a moment.
        for _ in range(20):
            try:
                self.log_path.unlink(missing_ok=True)
                return
            except OSError:
                time.sleep(0.25)

    def stop(self):
        if self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=15)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait(timeout=15)
        self.log.close()


@unittest.skipUnless(HAS_MCP, "mcp not installed")
class HttpTest(unittest.TestCase):
    def test_reference_over_http_scores_1_every_family(self):
        """The Harbor path: server via `python -m pinbox serve`, agent via the client CLI, grade via /admin/grade."""
        import urllib.parse
        for fam in _families():
            with self.subTest(family=fam):
                srv = _HttpServer(self, _spec(fam))
                p = subprocess.run([sys.executable, "-m", "pinbox.mcp_client", "--url", srv.url,
                                    "--agent", "reference", "--admin-token", TOKEN],
                                   cwd=str(ROOT), env=_env(), capture_output=True, text=True,
                                   encoding="utf-8", timeout=300)
                self.assertEqual(p.returncode, 0, p.stderr + srv.read_log())
                summary = json.loads(p.stdout.strip().splitlines()[-1])
                self.assertEqual(summary["reward"], 1, p.stdout)

                q = urllib.parse.urlencode({"token": TOKEN})
                status, body = srv.get(f"/admin/grade?{q}")
                self.assertEqual(status, 200, body)
                report = json.loads(body)
                self.assertEqual(report["reward"], 1, body)
                self.assertEqual(report["family"], fam)

                status, body = srv.get(f"/admin/trajectory?{q}")
                self.assertEqual(status, 200)
                lines = [json.loads(x) for x in body.splitlines() if x.strip()]
                self.assertEqual(len(lines), summary["calls"])
                self.assertEqual(len(lines), report["calls"])
                saved = (srv.state_dir / "trajectory.jsonl").read_text(encoding="utf-8").splitlines()
                self.assertEqual(len(saved), len(lines), "state folder is kept in step with the server")

    def test_admin_routes_need_the_token(self):
        from pinbox.mcp_client import McpEpisodeClient
        srv = _HttpServer(self, _spec(_families()[0]))
        self.assertEqual(srv.get("/healthz")[0], 200)
        for path in ("/admin/grade", "/admin/grade?token=wrong", "/admin/grade?token=",
                     "/admin/trajectory", "/admin/trajectory?token=wrong"):
            status, body = srv.get(path)
            self.assertEqual(status, 403, path)
            self.assertNotIn("reward", body)
        status, _ = srv.get("/admin/grade", headers={"Authorization": "Bearer wrong"})
        self.assertEqual(status, 403)
        self.assertNotEqual(srv.get("/admin/state")[0], 200)
        # the token also works as a bearer header
        status, body = srv.get("/admin/grade", headers={"Authorization": "Bearer " + TOKEN})
        self.assertEqual(status, 200, body)
        self.assertIn("reward", json.loads(body))
        # an MCP client sees tools only; calling through HTTP works and is graded live
        with McpEpisodeClient.http(srv.url, timeout=60) as client:
            self.assertTrue(client.call("get_task")["ok"])

    def test_no_token_means_admin_off(self):
        srv = _HttpServer(self, _spec(_families()[0]), token=None)
        self.assertEqual(srv.get("/healthz")[0], 200)
        self.assertEqual(srv.get("/admin/grade?token=")[0], 403)
        self.assertEqual(srv.get("/admin/grade?token=None")[0], 403)


if __name__ == "__main__":
    unittest.main()
