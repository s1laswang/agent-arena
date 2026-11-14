"""Generate the Canary Harbor dataset: one Harbor task per (tier, judge seed).

    python harbor/build.py                                   # THE JUDGE SET: hard x seeds 900000-900009 (10 tasks)
    python harbor/build.py --tiers medium --seeds 900000     # one task
    python harbor/build.py --tiers easy,medium,hard --seeds judge   # everything: 3 tiers x all 40 judge seeds
    python harbor/build.py --seeds 900000-900004 --out /tmp/canary-ds
    python harbor/build.py --verifier shared                 # fallback for Harbor without [[verifier.collect]]

Each task is self-contained (works on any compose-capable Harbor provider):

    canary-<tier>-<seed>/
      task.toml                         separate verifier, sidecar artifact + collect hook, MCP server entry
      instruction.md                    short MCP preface + Env.instruction() for the tier (seed-independent)
      environment/Dockerfile            agent (`main`) image: no canary source, no data, no secret
      environment/opencode.json         project OpenCode config -> http://canary-server:8765/mcp
      environment/docker-compose.yaml   the canary-server sidecar (tier/seed); one server container per trial
      environment/canary-server/        sidecar image: vendored canary/ package + entrypoint + collect hook
                                        + data/worlds/judge/SALT (the build-time world secret, 0600 in the image)
                                        + episode.json {tier, seed} (0600; read via CANARY_EPISODE_FILE)
      solution/solve.sh (+ canary/)     oracle: reference solver over MCP (uploaded only for `-a oracle`)
      solution/check_isolation.sh
      tests/Dockerfile, tests/test.sh   verifier: reward = ledger score from the sidecar, after the HMAC check
      tests/ledger_key                  build-time ledger signing key (0600; verifier image only)

Default = the judge set (PLAN-95 A1): tier hard, judge seeds 900000-900009. Hard is the tier where the reference
solver keeps its EV edge over frontier agents, and these 10 seeds were fixed before any frontier run on them
(pre-registered, not cherry-picked). --tiers / --seeds still build medium, easy and any other judge/held-out seed.

Ledger signing (PLAN-95 C1, defence in depth): one random 32-byte key per build is written ONLY into each task's
sidecar build context (canary-server/ledger_key, 0600, CANARY_LEDGER_KEY_FILE) and the verifier build context
(tests/ledger_key). The server HMAC-SHA256-signs every /ledger payload; test.sh rejects (reward 0) a missing or bad
signature. The agent image never sees either build context. (--verifier shared: the verifier runs in `main`, so the
key reaches it via [verifier].env like the ledger token; weaker, see harbor/README.md.)

World secret: one random 32-byte secret per build (or --secret-file, e.g. data/worlds/judge/SALT for the
team's exact numbers) is written ONLY into each task's sidecar build context and baked into the server image as
a 0600 file. It is never committed (harbor/dataset/ is gitignored), never in the agent image (environment/
.dockerignore excludes canary-server/) and never in an environment variable. Because it is fixed at build time,
the oracle (solve.sh) and every agent trial of the same task play the same world: a paired comparison.
Rebuilding the dataset draws a new secret (new worlds) unless --secret-file is given.
"""
from __future__ import annotations

import argparse
import json
import secrets
import shutil
import string
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
JUDGE_SET_TIERS = "hard"                 # the default build (PLAN-95 A1): pre-registered, hard only
JUDGE_SET_SEEDS = "900000-900009"
ROOT = HERE.parent
TEMPLATE = HERE / "template"
TEMPLATED = {"task.toml", "environment/docker-compose.yaml"}  # string.Template ($VAR); everything else copied verbatim

PREFACE = """\
# How to play (read first)

You play through the **`canary` MCP server** that is already connected to your agent (tools such as
`status`, `list_employees`, `advance_day`, `plant_canary`, `accuse`). Everything happens through those tools:
there is nothing to find in this container, and the game state lives on the server. The same rules
are also sent as the MCP server's instructions.

- Call `status` first, then `list_employees` and `list_documents`.
- Every tool returns JSON `{"ok": ..., "data": ..., "error": ...}`. Invalid calls still count toward the call limit.
- The episode ends when you call `accuse` (exactly once), when the last day ends, or at the tool-call limit.
  Your score is computed by the server from what you did, not from anything you write here.

---

"""


def vendor_ignore(src: str, names: list[str]) -> set[str]:
    bad = {n for n in names if n in {"__pycache__", ".pytest_cache"} or n.endswith((".pyc", ".pyo"))}
    # Belt and braces: nothing truth-like may ever be vendored.
    bad |= {n for n in names if "truth" in n.lower() or "SALT" in n or n.endswith((".world.json",))}
    return bad


def render_instruction(tier: str) -> str:
    sys.path.insert(0, str(ROOT))
    from canary.text.instruction import render  # seed-independent rules text (tests/test_env_docs.py)
    return PREFACE + render(tier)


def write_secret(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    path.chmod(0o600)


def build_task(out: Path, tier: str, seed: int, verifier: str, world_secret: bytes, ledger_key: bytes) -> Path:
    task_id = f"{tier}-{seed}"
    dst = out / f"canary-{task_id}"
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(TEMPLATE, dst, ignore=shutil.ignore_patterns("__pycache__", ".DS_Store"))

    token = secrets.token_hex(32) if verifier == "shared" else ""
    subs = {
        "TASK_ID": task_id, "TIER": tier, "SEED": str(seed), "VERIFIER_MODE": verifier,
        # shared mode only: a per-build grader token, known to the sidecar (compose) and the verifier
        # (task.toml); neither file is visible inside the agent container.
        # The ledger signing key reaches a shared verifier the same way (a separate verifier has tests/ledger_key).
        "VERIFIER_ENV_LINE": (f'env = {{ CANARY_LEDGER_TOKEN = "{token}", CANARY_LEDGER_KEY = "{ledger_key.decode()}" }}'
                              if token else ""),
        "LEDGER_TOKEN_LINE": f'      CANARY_LEDGER_TOKEN: "{token}"' if token else "",
    }
    for rel in TEMPLATED:
        p = dst / rel
        p.write_text(string.Template(p.read_text()).substitute(subs))
    if verifier == "shared":
        (dst / "tests" / "Dockerfile").unlink()  # shared verification runs in main; no verifier image

    (dst / "instruction.md").write_text(render_instruction(tier))
    for target in (dst / "environment" / "canary-server" / "canary", dst / "solution" / "canary"):
        shutil.copytree(ROOT / "canary", target, ignore=vendor_ignore)
    write_secret(dst / "environment" / "canary-server" / "data" / "worlds" / "judge" / "SALT", world_secret)
    # Ledger signing key: sidecar (signs) + separate verifier (checks). Never under environment/ outside
    # canary-server/ (the agent image's context) and never in solution/ (uploaded into main for oracle runs).
    write_secret(dst / "environment" / "canary-server" / "ledger_key", ledger_key)
    if verifier == "separate":
        write_secret(dst / "tests" / "ledger_key", ledger_key)
    episode = dst / "environment" / "canary-server" / "episode.json"
    episode.write_text(json.dumps({"tier": tier, "seed": seed}))
    episode.chmod(0o600)
    shutil.copy2(HERE / "check_isolation.sh", dst / "solution" / "check_isolation.sh")
    for sh in dst.rglob("*.sh"):
        sh.chmod(0o755)
    return dst


def parse_seeds(spec: str) -> list[int]:
    from canary.rules import JUDGE_SEEDS
    if spec == "judge":
        return list(JUDGE_SEEDS)
    seeds: list[int] = []
    for part in spec.split(","):
        a, _, b = part.partition("-")
        seeds.extend(range(int(a), int(b) + 1) if b else [int(a)])
    return seeds


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tiers", default=JUDGE_SET_TIERS,
                    help=f"comma list of tiers (default: {JUDGE_SET_TIERS!r}, the judge set)")
    ap.add_argument("--seeds", default=JUDGE_SET_SEEDS,
                    help=f"'{JUDGE_SET_SEEDS}' (default, the judge set), 'judge' (all 40 judge seeds), "
                         "'900000' or a comma list")
    ap.add_argument("--out", default=str(HERE / "dataset"))
    ap.add_argument("--verifier", choices=["separate", "shared"], default="separate")
    ap.add_argument("--secret-file", default=None,
                    help="world secret to bake into the sidecars (default: a fresh random secret per build)")
    a = ap.parse_args(argv)
    if a.verifier == "shared":   # EXPLOITS #42
        print("WARNING: --verifier shared is NOT for judging. test.sh then runs inside the agent's container. On our "
              "Harbor 0.25 / Docker Desktop host it did not run at all (even do_nothing got RewardFileNotFoundError), "
              "so a reward file the agent leaves behind is all Harbor sees. Use the default separate verifier.",
              file=sys.stderr)
    sys.path.insert(0, str(ROOT))
    from canary.rules import HELDOUT_SEEDS, JUDGE_SEEDS, TIERS

    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    tiers = [t.strip() for t in a.tiers.split(",") if t.strip()]
    seeds = parse_seeds(a.seeds)
    for t in tiers:
        if t not in TIERS:
            ap.error(f"unknown tier {t!r}; known: {', '.join(TIERS)}")
    for s in seeds:
        if s not in JUDGE_SEEDS and s not in HELDOUT_SEEDS:
            ap.error(f"seed {s} is not a judge/held-out seed; the server refuses public seeds (EXPLOITS #23)")
    if a.secret_file:
        world_secret = Path(a.secret_file).read_bytes()
        if len(world_secret) < 16:
            ap.error("--secret-file must hold at least 16 bytes")
    else:
        world_secret = secrets.token_hex(32).encode()
    ledger_key = secrets.token_hex(32).encode()   # always fresh: it signs, it does not pick the world
    n = 0
    for t in tiers:
        for s in seeds:
            build_task(out, t, s, a.verifier, world_secret, ledger_key)
            n += 1
    src = "--secret-file" if a.secret_file else "fresh random"
    judge_set = " = the judge set" if (a.tiers, a.seeds) == (JUDGE_SET_TIERS, JUDGE_SET_SEEDS) else ""
    print(f"wrote {n} task(s) to {out}{judge_set} (tiers={','.join(tiers)}, verifier={a.verifier}, "
          f"world secret: {src}, baked into the sidecars only; ledger signing key: fresh, sidecar + verifier only)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
