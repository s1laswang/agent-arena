"""OpenCode over the HARNESS MCP server (judges' harness shape).

    python -m canary.agents.frontier.opencode_run --model google/gemini-4-carbon --tier hard --seeds 0-4 [--jobs 2]

Per episode (common.run_one): one canary.mcp_server on its own port -> a clean temp workdir holding only an
opencode.json that points at that server -> `opencode run --format json <instruction>` -> score from the
server's GET /ledger -> EpisodeResult + meta.json. Only our own child processes are stopped (Popen handles).

Isolation of the agent:
- tools: permission {"*": "deny", "canary_*": "allow"}: every OpenCode built-in tool (read, glob, grep,
  list, bash, edit, webfetch, task, ...) is denied, so the agent sees only the 13 canary MCP tools (checked
  live: gemini-4-carbon lists exactly those 13);
- an isolated per-episode OpenCode home (XDG_CONFIG_HOME / XDG_DATA_HOME / XDG_STATE_HOME in a temp dir
  outside the workdir): no global config, plugins, rules or stored logins, and no shared session DB
  (the v1.2 "database is locked" failures); OPENCODE_DISABLE_CLAUDE_CODE=1 (no ~/.claude rules/skills);
- google/* models: the key is passed as GOOGLE_GENERATIVE_AI_API_KEY (OpenCode's Google provider); all other
  keys and the ledger token are stripped (common.child_env).
OpenCode's defaults for gemini-4 models (OpenCode 1.18.29): thinkingConfig {includeThoughts: true}, no
thinkingLevel (=> the model default, medium), temperature unset; thought signatures are replayed by OpenCode.
"""
from __future__ import annotations

import json
import re
import tempfile
from pathlib import Path

from canary.agents.frontier.common import REPO_ROOT, base_args, make_clean_workdir, run_seeds, spec_from

FILES = {"opencode.json"}
BASE_CONFIG = REPO_ROOT / "configs" / "opencode" / "opencode.json"
DEFAULT_MODEL = "google/gemini-4-carbon"  # strongest Gemini on the API (2026-11-14); OpenAI is not used anymore
PERMISSION = {"*": "deny", "canary_*": "allow"}


def opencode_config(mcp_url: str) -> dict:
    cfg = json.loads(BASE_CONFIG.read_text()) if BASE_CONFIG.exists() else {
        "$schema": "https://opencode.ai/config.json", "mcp": {"canary": {"type": "remote", "enabled": True}}}
    servers = cfg["mcp"].get("servers", cfg["mcp"])
    servers["canary"]["url"] = mcp_url
    cfg["permission"] = dict(PERMISSION)
    cfg["autoupdate"] = False
    cfg["share"] = "disabled"
    return cfg


def normalize_model(model: str) -> str:
    if "/" in model:
        return model
    return f"google/{model}" if model.startswith("gemini") else f"openai/{model}"


def build_cmd(workdir: Path, prompt: str, model: str, mcp_url: str) -> list[str]:
    (workdir / "opencode.json").write_text(json.dumps(opencode_config(mcp_url), indent=1))
    return ["opencode", "run", "--model", normalize_model(model), "--format", "json", "--dir", str(workdir), prompt]


def child_env_extra(model: str):
    """Per-episode env: an isolated OpenCode home outside the workdir, plus the provider key for google/* or openai/*."""
    def make(workdir: Path) -> tuple[dict, list[Path]]:
        home = Path(tempfile.mkdtemp(prefix="canary-oc-home-")).resolve()
        assert workdir not in home.parents and home != workdir and REPO_ROOT not in home.parents
        env = {"XDG_CONFIG_HOME": str(home / "config"), "XDG_DATA_HOME": str(home / "data"),
               "XDG_STATE_HOME": str(home / "state"), "OPENCODE_DISABLE_CLAUDE_CODE": "1",
               "OPENCODE_DISABLE_AUTOUPDATE": "1", "OPENCODE_DISABLE_SHARE": "1"}
        if normalize_model(model).startswith("google/"):
            from canary.llm.base import require_key
            env["GOOGLE_GENERATIVE_AI_API_KEY"] = require_key("GEMINI_API_KEY")
        elif normalize_model(model).startswith("openai/"):
            from canary.llm.base import require_key
            env["OPENAI_API_KEY"] = require_key("OPENAI_API_KEY")   # only the agent CLI gets it, never the MCP server
        return env, [home]
    return make


def opencode_google_settings(model: str) -> dict:
    """What OpenCode 1.18.29 sends for a Google model (read from its bundled provider transform)."""
    mid = model.split("/", 1)[-1]
    gemini3 = "gemini-3" in mid
    sampling = bool(re.search(r"gemini-2[.-]5(?:[.-]|$)|gemini-3-(?:flash|pro)(?:[.-]|$)|gemini-3[.-]1(?:[.-]|$)|"
                              r"gemini-3[.-]5-flash(?!-lite)(?:[.-]|$)", mid))
    return {"thinking": "includeThoughts, thinkingLevel=high (OpenCode sets high for gemini-3* ids)" if gemini3
            else "includeThoughts, no thinkingLevel (model default; gemini-4-carbon: medium)",
            "temperature": "1.0, topP 0.95 (OpenCode defaults for this id)" if sampling
            else "not set (API default)"}


def opencode_version() -> str | None:
    import subprocess
    try:
        return subprocess.run(["opencode", "--version"], capture_output=True, text=True, timeout=30).stdout.strip() or None
    except Exception:  # noqa: BLE001
        return None


def main(argv=None):
    a = base_args("OpenCode frontier runner", DEFAULT_MODEL).parse_args(argv)
    model = normalize_model(a.model)
    spec = spec_from(a, f"opencode:{model}")
    spec.child_env_extra = child_env_extra(model)
    spec.extra.update({"harness": "opencode-cli+mcp_server", "opencode_version": opencode_version(),
                       "model_id": model.split("/", 1)[1], "opencode_permission": PERMISSION,
                       "provider_settings": opencode_google_settings(model) if model.startswith("google/") else None})
    build = lambda wd, prompt, url: build_cmd(wd, prompt, model, url)  # noqa: E731
    if a.dry_run:
        print(build(make_clean_workdir(), "<prompt>", "http://127.0.0.1:0/mcp"))
        return
    run_seeds(spec, build, FILES)
    print(f"wrote {spec.out}")


if __name__ == "__main__":
    main()
