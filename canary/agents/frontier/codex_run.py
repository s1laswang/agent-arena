"""Codex CLI over MCP, judges' harness shape. LIVE PATH UNTESTED (needs HARNESS MCP server).

    python -m canary.agents.frontier.codex_run --model gpt-5.5 --tier hard --seeds 0

MCP is configured ONLY via -c overrides (codex >= 0.167 supports mcp_servers.<n>.url for streamable
HTTP); ~/.codex/config.toml is never edited and is ignored (--ignore-user-config; auth still comes
from CODEX_HOME). Shell/exec/web/apps tools are disabled so the agent can only use the MCP tools
(codex's read-only sandbox does not block reads, so we remove the shell instead).
"""
from __future__ import annotations

import json
from pathlib import Path

from canary.llm import default_openai_model
from canary.agents.frontier.common import base_args, make_clean_workdir, run_seeds, spec_from

FILES: set[str] = set()  # codex needs no files in the workdir


def _toml_str(s: str) -> str:
    return json.dumps(s)  # a JSON string is a valid TOML basic string


def build_cmd(workdir: Path, prompt: str, model: str, mcp_url: str, allow_shell: bool = False) -> list[str]:
    cmd = ["codex", "exec", "--model", model, "--cd", str(workdir), "--skip-git-repo-check",
           "--ephemeral", "--ignore-user-config", "--ignore-rules", "--json",
           "--sandbox", "read-only",
           "-c", f"mcp_servers.canary.url={_toml_str(mcp_url)}",
           "-c", "mcp_servers.canary.enabled=true",
           "-c", "mcp_servers.canary.tool_timeout_sec=120",
           "-c", 'mcp_servers.canary.default_tools_approval_mode="approve"',
           "-c", 'approval_policy="never"',
           "-c", 'web_search="disabled"']
    if not allow_shell:
        for feat in ("shell_tool", "unified_exec", "apps", "plugins", "browser_use", "computer_use"):
            cmd += ["--disable", feat]
    return cmd + [prompt]


def _default() -> str:
    return default_openai_model()


def main(argv=None):
    ap = base_args("Codex frontier runner", _default())
    # DEBUGGING ONLY: never use for official runs (re-enables codex shell/exec tools).
    ap.add_argument("--allow-shell", action="store_true", help="debugging only; not for official runs")
    a = ap.parse_args(argv)
    spec = spec_from(a, f"codex:{a.model}")
    build = lambda wd, prompt, url: build_cmd(wd, prompt, a.model, url, a.allow_shell)  # noqa: E731
    if a.dry_run:
        print(build(make_clean_workdir(), "<prompt>", "http://127.0.0.1:0/mcp"))
        return
    run_seeds(spec, build, FILES)
    print(f"wrote {spec.out}")


if __name__ == "__main__":
    main()
