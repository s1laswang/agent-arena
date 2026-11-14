"""OpenCode over MCP, judges' harness shape. LIVE PATH UNTESTED (needs HARNESS MCP server).

    python -m canary.agents.frontier.opencode_run --model openai/gpt-5.5 --tier medium --seeds 0-2 \
        --mcp-url http://127.0.0.1:8765/mcp --token T

Config schema: https://opencode.ai/docs/mcp-servers/ (remote: type/url/enabled/headers),
https://opencode.ai/docs/permissions/ . Uses opencode's own stored login.
"""
from __future__ import annotations

import json
from pathlib import Path

from canary.llm import default_openai_model
from canary.agents.frontier.common import base_args, run_seeds, spec_from

FILES = {"opencode.json"}


def opencode_config(mcp_url: str, headers: dict | None = None) -> dict:
    remote = {"type": "remote", "url": mcp_url, "enabled": True}
    if headers:
        remote["headers"] = headers
    return {
        "$schema": "https://opencode.ai/config.json",
        "mcp": {"canary": remote},
        # MCP-only: no shell, no file edits, no web. Built-in read/glob/grep only see the empty temp dir.
        "permission": {"edit": "deny", "bash": "deny", "webfetch": "deny"},
        "autoupdate": False,
        "share": "disabled",
    }


def build_cmd(workdir: Path, prompt: str, model: str, mcp_url: str, headers: dict | None = None) -> list[str]:
    (workdir / "opencode.json").write_text(json.dumps(opencode_config(mcp_url, headers), indent=1))
    if "/" not in model:
        model = f"openai/{model}"
    return ["opencode", "run", "--model", model, "--format", "json", "--dir", str(workdir), prompt]


def _default() -> str:
    return f"openai/{default_openai_model()}"


def main(argv=None):
    a = base_args("OpenCode frontier runner", _default()).parse_args(argv)
    model = a.model if "/" in a.model else f"openai/{a.model}"
    spec = spec_from(a, f"opencode:{model}")
    build = lambda wd, prompt: build_cmd(wd, prompt, model, a.mcp_url)  # noqa: E731
    if a.dry_run:
        from canary.agents.frontier.common import make_clean_workdir
        print(build(make_clean_workdir(), "<prompt>"))
        return
    print(f"wrote {run_seeds(spec, build, FILES, fetch=not a.no_fetch)}")


if __name__ == "__main__":
    main()
