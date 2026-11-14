import argparse, asyncio, json, os, sys, tempfile

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def main(seat, day, cmd):
    tmp_path = None
    env = dict(os.environ)
    if cmd:
        argv = cmd
    else:
        salt = (os.environ.get("SLEEPER_SALT") or "").strip() or "smoke-local-salt"
        tok = os.environ.get("VERIFY_TOKEN") or "smoke-local-token"
        fd, tmp_path = tempfile.mkstemp(prefix="sleeper-smoke-", suffix=".json")
        with os.fdopen(fd, "w") as f:
            json.dump({"SLEEPER_SALT": salt, "VERIFY_TOKEN": tok, "SLEEPER_SEED": str(day)}, f)
        os.chmod(tmp_path, 0o600)
        for k in ("SLEEPER_SALT", "SLEEPER_SEED", "VERIFY_TOKEN"):
            env.pop(k, None)
        env["SLEEPER_SECRETS_FILE"] = tmp_path
        env["SLEEPER_SECRETS_UNLINK"] = "1"
        argv = [sys.executable, "-m", "sleeper.mcp_server", "--secrets-file", tmp_path, "--seat", seat, "--day", str(day)]
    try:
        params = StdioServerParameters(command=argv[0], args=argv[1:], env=env)
        async with stdio_client(params) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                names = [t.name for t in (await s.list_tools()).tools]
                print("tools:", names)
                assert "my_tickets" in names and "end_turn" in names, names
                res = await s.call_tool("my_tickets", {})
                print("my_tickets:", json.dumps([c.text for c in res.content])[:300])
                await s.call_tool("end_turn", {})
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
    print("OK")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--seat", default="controller")
    p.add_argument("--day", type=int, default=1)
    p.add_argument("cmd", nargs="*")
    a = p.parse_args()
    asyncio.run(main(a.seat, a.day, a.cmd))
