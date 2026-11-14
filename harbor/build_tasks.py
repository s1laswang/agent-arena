#!/usr/bin/env python3
"""Build Harbor task folders for the Poisoned Inbox eval set (stdlib only).

    python harbor/build_tasks.py                          # every eval episode -> harbor/tasks/<episode_id>/
    python harbor/build_tasks.py --episodes ap_run:1:1    # just some episodes
    python harbor/build_tasks.py --families ap_run        # just some families
    python harbor/build_tasks.py --verifier shared        # fallback for Harbor versions without a separate verifier

One task folder per episode, in Harbor's task format:

  task.toml           MCP server, separate verifier, collect hook, timeouts
  instruction.md      the episode instruction (full policy) + how to reach the tools
  environment/        Dockerfile = the agent's container ("main"): no pinbox code, no state
                      docker-compose.yaml adds the "pinbox-env" service (the env server)
                      pinbox-env/ = env server image: python + pinned mcp + a pinbox snapshot
  solution/solve.sh   Harbor's oracle: our scripted agents over MCP (reference by default)
  tests/              separate verifier image; test.sh writes /logs/verifier/reward.txt

Each folder is self-contained (it carries its own pinbox.zip snapshot), so a single folder
can be copied and run alone. The snapshot is byte-identical across folders, so git and
Docker store it once.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import secrets
import shutil
import sys
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
TEMPLATE = HERE / "template"
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

# python:3.12.16-slim-trixie = docker.io/library/python@sha256:5e2bdb1b0d542d5039cffb8181c65930093949194a65c365dfb1b0fe13a4fa5b
BASE_IMAGE = "python:3.12.16-slim-trixie"
SERVICE = "pinbox-env"
PORT = 8000
SERVER_URL = f"http://{SERVICE}:{PORT}"
MCP_URL = f"{SERVER_URL}/mcp"
TASK_ORG = "poisoned-inbox"
MARKER = 'generated_by = "harbor/build_tasks.py"'


# ---------------------------------------------------------------- helpers

def _template(rel: str) -> str:
    return (TEMPLATE / rel).read_text(encoding="utf-8").replace("\r\n", "\n")


def _fill(text: str, values: dict) -> str:
    for key, val in values.items():
        text = text.replace(f"@@{key}@@", str(val))
    if "@@" in text:
        raise ValueError(f"unfilled placeholder in template: {text[text.index('@@'):][:40]!r}")
    return text


class FolderWriter:
    """Collects a task folder's files, then syncs them to disk in place.

    Files are only rewritten when their bytes change, and stray files are removed one by one.
    Whole folders are never deleted and recreated: on Windows, OneDrive or Docker Desktop can
    hold a folder open, and a half-deleted task folder is worse than a stale file.
    Text is written with LF line endings (everything here runs on Linux).
    """

    def __init__(self, root: Path):
        self.root = root
        self.files: dict[str, tuple[bytes, bool]] = {}

    def text(self, rel: str, text: str, executable: bool = False) -> None:
        self.files[rel] = (text.replace("\r\n", "\n").encode("utf-8"), executable)

    def binary(self, rel: str, data: bytes) -> None:
        self.files[rel] = (data, False)

    def sync(self) -> None:
        for rel, (data, executable) in self.files.items():
            path = self.root / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            if not (path.is_file() and path.read_bytes() == data):
                tmp = path.with_name(path.name + ".tmp")
                tmp.write_bytes(data)
                os.replace(tmp, path)
            if executable:
                try:
                    os.chmod(path, 0o755)
                except OSError:
                    pass
        keep = {Path(rel).as_posix() for rel in self.files}
        for path in sorted(self.root.rglob("*"), key=lambda p: len(p.parts), reverse=True):
            rel = path.relative_to(self.root).as_posix()
            try:
                if path.is_file() and rel not in keep:
                    path.unlink()
                elif path.is_dir() and not any(path.iterdir()):
                    path.rmdir()
            except OSError as e:
                print(f"  warning: could not remove {path}: {e}", file=sys.stderr)


def _toml_str(s: str) -> str:
    return json.dumps(s, ensure_ascii=True)  # a JSON string is a valid TOML basic string


def pinbox_zip() -> bytes:
    """A deterministic zip of the pinbox package (no __pycache__), same bytes for the same code."""
    buf = io.BytesIO()
    root = REPO / "pinbox"
    files = sorted(p for p in root.rglob("*")
                   if p.is_file() and "__pycache__" not in p.parts and p.suffix not in (".pyc", ".pyo"))
    with zipfile.ZipFile(buf, "w") as z:
        for path in files:
            info = zipfile.ZipInfo(path.relative_to(REPO).as_posix(), date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            z.writestr(info, path.read_bytes(), compresslevel=9)
    return buf.getvalue()


def select_episodes(families=None, specs=None) -> list[dict]:
    from pinbox.episode import parse_spec
    from pinbox.eval import eval_set
    from pinbox.state import episode_id
    if specs:
        out = []
        for s in specs:
            parsed = parse_spec(s)
            if parsed is None:
                raise SystemExit(f"bad episode spec {s!r} (want FAMILY:SEED:DIFFICULTY)")
            f, seed, d = parsed
            out.append({"family": f, "seed": seed, "difficulty": d, "episode_id": episode_id(f, seed, d)})
        return out
    return eval_set(families)


# ---------------------------------------------------------------- one task folder

def task_toml(ep: dict, mode: str, payload_sources: str, zip_sha: str, version: str,
              agent_timeout: float, title: str) -> str:
    name = f"{TASK_ORG}/{ep['episode_id']}"
    description = (f"Poisoned Inbox: {title} (family {ep['family']}, seed {ep['seed']}, "
                   f"difficulty {ep['difficulty']}). Tools over MCP; data partly poisoned; follow the written policy.")
    lines = ['schema_version = "1.4"']
    if mode == "separate":
        lines += ["# Grading evidence comes out of the env server, never out of the agent's container.",
                  "artifacts = [",
                  f'  {{ source = "/srv/pinbox/out", service = "{SERVICE}" }},',
                  "]"]
    lines += [
        "",
        "[task]",
        f"name = {_toml_str(name)}",
        f"description = {_toml_str(description)}",
        'authors = [{ name = "Poisoned Inbox team" }]',
        'keywords = ["mcp", "tool-use", "prompt-injection", "fraud", "policy-following"]',
        "",
        "[metadata]",
        MARKER,
        f"family = {_toml_str(ep['family'])}",
        f"seed = {int(ep['seed'])}",
        f"difficulty = {int(ep['difficulty'])}",
        f"episode_id = {_toml_str(ep['episode_id'])}",
        f"payload_sources = {_toml_str(payload_sources)}",
        f"pinbox_version = {_toml_str(version)}",
        f"pinbox_zip_sha256 = {_toml_str(zip_sha)}",
        f"verifier_mode = {_toml_str(mode)}",
        "",
        "[agent]",
        f"timeout_sec = {float(agent_timeout)}",
        "",
        "[verifier]",
        "timeout_sec = 180.0",
        f'environment_mode = "{mode}"',
    ]
    if mode == "separate":
        lines += [
            "",
            "# Runs inside pinbox-env after the agent's container is stopped: fetches the grade from the",
            "# admin route with a token that never leaves pinbox-env, and saves it to /srv/pinbox/out.",
            "[[verifier.collect]]",
            f'service = "{SERVICE}"',
            'command = "python /opt/pinbox/collect.py"',
            "timeout_sec = 120.0",
        ]
    lines += [
        "",
        "[environment]",
        "build_timeout_sec = 900.0",
        "cpus = 1",
        "memory_mb = 2048",
        "",
        "[[environment.mcp_servers]]",
        'name = "pinbox"',
        'transport = "streamable-http"',
        f'url = "{MCP_URL}"',
        "",
    ]
    return "\n".join(lines)


def compose_yaml(spec: str, payload_sources: str, token: str | None) -> str:
    env = [f'      PINBOX_PAYLOAD_SOURCES: "{payload_sources}"']
    if token:
        env.append(f'      PINBOX_ADMIN_TOKEN: "{token}"')
    return "\n".join([
        "# Harbor merges this on top of its base compose file. \"main\" is the agent's container;",
        f"# \"{SERVICE}\" is the env server. The agent reaches it only over the network (MCP on port {PORT}).",
        "services:",
        "  main:",
        "    depends_on:",
        f"      {SERVICE}:",
        "        condition: service_healthy",
        "",
        f"  {SERVICE}:",
        "    build:",
        f"      context: ./{SERVICE}",
        f'    command: ["/opt/pinbox/start.sh", "{spec}"]',
        "    environment:",
        *env,
        "    expose:",
        f'      - "{PORT}"',
        "    healthcheck:",
        f'      test: ["CMD", "python", "-c", "import urllib.request; '
        f"urllib.request.urlopen('http://127.0.0.1:{PORT}/healthz', timeout=3)\"]",
        "      interval: 2s",
        "      timeout: 5s",
        "      retries: 60",
        "      start_period: 5s",
        "",
    ])


def build_task(ep: dict, out_dir: Path, mode: str, payload_sources: str, zip_bytes: bytes,
               agent_timeout: float) -> Path:
    from pinbox import __version__, payloads
    from pinbox.episode import Episode
    from pinbox.tasks import get_task
    from pinbox.tools import tools_for_family

    family, seed, difficulty = ep["family"], int(ep["seed"]), int(ep["difficulty"])
    spec = f"{family}:{seed}:{difficulty}"
    with payloads.source_mode(payload_sources):
        episode = Episode.create(family, seed, difficulty)
    instruction = episode.instruction().rstrip("\n")
    task = get_task(family)
    own = [t.name for t in tools_for_family(family) if t.family == family]
    example = next((n for n in own if n.startswith("list_")), own[0] if own else "list_emails")

    folder = out_dir / ep["episode_id"]
    toml = folder / "task.toml"
    if folder.exists() and any(folder.iterdir()) and not (toml.exists() and MARKER in toml.read_text(encoding="utf-8")):
        raise SystemExit(f"{folder} exists and was not made by this script; not touching it")
    zip_sha = hashlib.sha256(zip_bytes).hexdigest()
    token = secrets.token_hex(32) if mode == "shared" else None
    values = {"BASE_IMAGE": BASE_IMAGE, "MCP_URL": MCP_URL, "EPISODE_SPEC": spec,
              "PAYLOAD_SOURCES": payload_sources, "EXAMPLE_TOOL": f"pinbox_{example}"}

    w = FolderWriter(folder)
    w.text("task.toml", task_toml(ep, mode, payload_sources, zip_sha, __version__, agent_timeout,
                                  getattr(task, "title", family)))
    w.text("instruction.md", instruction + "\n" + _fill(_template("instruction_footer.md"), values))

    w.text("environment/Dockerfile", _fill(_template("environment/Dockerfile"), values))
    w.text("environment/.dockerignore", _template("environment/.dockerignore"))
    w.text("environment/docker-compose.yaml", compose_yaml(spec, payload_sources, token))
    srv = f"environment/{SERVICE}"
    w.text(f"{srv}/Dockerfile", _fill(_template("environment/pinbox-env/Dockerfile"), values))
    w.text(f"{srv}/requirements.txt", _template("requirements.txt"))
    w.text(f"{srv}/start.sh", _template("environment/pinbox-env/start.sh"), executable=True)
    w.text(f"{srv}/collect.py", _template("environment/pinbox-env/collect.py"), executable=True)
    w.binary(f"{srv}/pinbox.zip", zip_bytes)

    w.text("solution/solve.sh", _fill(_template("solution/solve.sh"), values), executable=True)
    w.text("solution/run_solution.py", _template("solution/run_solution.py"))
    w.text("solution/requirements.txt", _template("requirements.txt"))
    w.binary("solution/pinbox.zip", zip_bytes)

    w.text("tests/test.sh", _template("tests/test.sh"), executable=True)
    w.text("tests/verify.py", _template("tests/verify.py"))
    expected = {"episode_id": ep["episode_id"], "family": family, "seed": seed, "difficulty": difficulty,
                "verifier_mode": mode, "server_url": SERVER_URL, "payload_sources": payload_sources}
    w.text("tests/expected.json", json.dumps(expected, indent=2) + "\n")
    if mode == "separate":
        w.text("tests/Dockerfile", _fill(_template("tests/Dockerfile"), values))
    else:
        w.text("tests/admin_token", token + "\n")
    w.sync()
    return folder


# ---------------------------------------------------------------- main

def main(argv=None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="backslashreplace")
        except (AttributeError, ValueError, OSError):
            pass
    p = argparse.ArgumentParser(description="Build Harbor task folders for the Poisoned Inbox eval set")
    p.add_argument("--out", default=str(HERE / "tasks"), help="output folder (default harbor/tasks)")
    p.add_argument("--families", default="", help="comma list of families (default: all)")
    p.add_argument("--episodes", default="", help="comma list of FAMILY:SEED:DIFFICULTY (default: the eval set)")
    p.add_argument("--verifier", choices=["separate", "shared"], default="separate",
                   help="separate (default, safest) or shared (for Harbor versions without a separate verifier)")
    p.add_argument("--payload-sources", default=os.environ.get("PINBOX_PAYLOAD_SOURCES", "handwritten"),
                   help="payload wording pool: handwritten (default), all or gemini")
    p.add_argument("--agent-timeout", type=float, default=1800.0, help="agent timeout per trial, seconds")
    p.add_argument("--keep-stale", action="store_true",
                   help="keep generated task folders that are no longer in the selection")
    a = p.parse_args(argv)

    from pinbox import payloads
    if a.payload_sources not in payloads.MODES:
        raise SystemExit(f"--payload-sources must be one of {payloads.MODES}")
    families = [f for f in a.families.split(",") if f] or None
    specs = [s for s in a.episodes.split(",") if s] or None
    episodes = select_episodes(families, specs)
    if not episodes:
        raise SystemExit("no episodes selected")

    out_dir = Path(a.out).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    zip_bytes = pinbox_zip()
    built = set()
    for ep in episodes:
        folder = build_task(ep, out_dir, a.verifier, a.payload_sources, zip_bytes, a.agent_timeout)
        built.add(folder.name)

    removed = []
    if not a.keep_stale and not specs:
        for child in sorted(out_dir.iterdir()):
            toml = child / "task.toml"
            if child.is_dir() and child.name not in built and toml.exists() \
                    and MARKER in toml.read_text(encoding="utf-8"):
                try:
                    shutil.rmtree(child)
                    removed.append(child.name)
                except OSError as e:
                    print(f"  warning: could not remove stale task folder {child}: {e}", file=sys.stderr)

    by_family: dict = {}
    for ep in episodes:
        by_family[ep["family"]] = by_family.get(ep["family"], 0) + 1
    print(f"built {len(built)} Harbor task(s) in {out_dir}")
    print("  families: " + ", ".join(f"{f} ({n})" for f, n in sorted(by_family.items())))
    print(f"  verifier: {a.verifier}   payload sources: {a.payload_sources}   "
          f"pinbox.zip sha256 {hashlib.sha256(zip_bytes).hexdigest()[:16]} ({len(zip_bytes) // 1024} KB)")
    if removed:
        print(f"  removed {len(removed)} stale task folder(s): {', '.join(removed)}")
    if a.verifier == "shared":
        print("  NOTE: shared mode writes a fresh admin token into each task (tests/admin_token and "
              "environment/docker-compose.yaml). Rebuild before each run and do not publish these folders.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
