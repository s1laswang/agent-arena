"""OpenCode over the HARNESS MCP server (judges' harness shape).

    python -m canary.agents.frontier.opencode_run --model openai/gpt-5.6-sol --tier hard --seeds 0-4 [--jobs 2]

Base config: configs/opencode/opencode.json (HARNESS), copied into a clean temp dir with the per-episode
URL, plus deny permissions for bash/edit/webfetch. Uses opencode's own stored login.
"""
from __future__ import annotations

import json
from pathlib import Path

from canary.agents.frontier.common import REPO_ROOT, base_args, make_clean_workdir, run_seeds, spec_from

FILES = {"opencode.json"}
BASE_CONFIG = REPO_ROOT / "configs" / "opencode" / "opencode.json"
DEFAULT_MODEL = "openai/gpt-5.6-sol"  # CEO decision: judges'-harness-shape model via OpenCode's ChatGPT login


def opencode_config(mcp_url: str) -> dict:
    cfg = json.loads(BASE_CONFIG.read_text()) if BASE_CONFIG.exists() else {
        "$schema": "https://opencode.ai/config.json", "mcp": {"canary": {"type": "remote", "enabled": True}}}
    servers = cfg["mcp"].get("servers", cfg["mcp"])
    servers["canary"]["url"] = mcp_url
    cfg["permission"] = {"edit": "deny", "bash": "deny", "webfetch": "deny"}
    cfg["autoupdate"] = False
    cfg["share"] = "disabled"
    return cfg


def build_cmd(workdir: Path, prompt: str, model: str, mcp_url: str) -> list[str]:
    (workdir / "opencode.json").write_text(json.dumps(opencode_config(mcp_url), indent=1))
    if "/" not in model:
        model = f"openai/{model}"
    return ["opencode", "run", "--model", model, "--format", "json", "--dir", str(workdir), prompt]


def main(argv=None):
    a = base_args("OpenCode frontier runner", DEFAULT_MODEL).parse_args(argv)
    model = a.model if "/" in a.model else f"openai/{a.model}"
    spec = spec_from(a, f"opencode:{model}")
    build = lambda wd, prompt, url: build_cmd(wd, prompt, model, url)  # noqa: E731
    if a.dry_run:
        print(build(make_clean_workdir(), "<prompt>", "http://127.0.0.1:0/mcp"))
        return
    run_seeds(spec, build, FILES)
    print(f"wrote {spec.out}")


if __name__ == "__main__":
    main()
