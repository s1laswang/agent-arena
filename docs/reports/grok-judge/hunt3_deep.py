#!/usr/bin/env python3
"""Hunt 3 — deepen the fail-open world regeneration and the same-uid environ leak.

Compares day-1 regenerated accusations to the reference solver on the frozen
judge seeds. Redacts process tokens and world secrets in the written JSON.
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent / "hunt3_results.json"
SOLVER = Path("/tmp/canary-judge/solver-all-20261114-002330/episodes.jsonl")
sys.path.insert(0, str(ROOT))
os.environ.pop("CANARY_WORLD_SECRET", None)

SECRET_MARKER = "HUNT3_WORLD_SECRET"
TOKEN_MARKER = "HUNT3_TOKEN"


def http_json(method, url, body=None, timeout=10):
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json", "Accept": "application/json"}, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode(errors="replace")
    except urllib.error.URLError as e:
        return 0, f"URLError: {e.reason}"


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def start_shim(tier, seed, extra=None):
    import secrets
    port = free_port()
    token = secrets.token_hex(8)
    env = os.environ.copy()
    env.pop("CANARY_WORLD_SECRET", None)
    env.update({
        "CANARY_HOST": "127.0.0.1", "CANARY_PORT": str(port),
        "CANARY_LEDGER_TOKEN": token, "CANARY_TIER": str(tier),
        "CANARY_SEED": str(seed), "CANARY_FAKE_BACKEND": "env",
    })
    if extra:
        env.update(extra)
    proc = subprocess.Popen([sys.executable, "-m", "canary.redteam.fake_mcp"], cwd=ROOT, env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    base = f"http://127.0.0.1:{port}"
    deadline = time.time() + 10
    last = ""
    while time.time() < deadline:
        code, body = http_json("GET", f"{base}/ledger?token={token}")
        if code == 200:
            return proc, base, token
        last = f"{code} {body[:200]}"
        if proc.poll() is not None:
            err = proc.stdout.read().decode(errors="replace")[:800] if proc.stdout else ""
            raise RuntimeError(f"server exited {proc.returncode}: {err} last={last}")
        time.sleep(0.05)
    raise RuntimeError(f"shim not ready: {last}")


def stop(proc):
    proc.terminate()
    try:
        proc.wait(timeout=3)
    except subprocess.TimeoutExpired:
        proc.kill()


def mcp_call(base, name, args, id_=1):
    _, raw = http_json("POST", base + "/mcp", {"jsonrpc": "2.0", "id": id_, "method": name and "tools/call",
                                               "params": {"name": name, "arguments": args}})
    msg = json.loads(raw)
    return json.loads(msg["result"]["content"][0]["text"])


def read_environ(pid: int) -> dict[str, str]:
    raw = Path(f"/proc/{pid}/environ").read_bytes().split(b"\0")
    out = {}
    for item in raw:
        if not item or b"=" not in item:
            continue
        k, v = item.split(b"=", 1)
        try:
            out[k.decode()] = v.decode()
        except UnicodeDecodeError:
            continue
    return out


def scrub(obj, secrets):
    if isinstance(obj, str):
        for s in secrets:
            if s:
                obj = obj.replace(s, "<redacted>")
        return obj
    if isinstance(obj, dict):
        return {k: scrub(v, secrets) for k, v in obj.items()}
    if isinstance(obj, list):
        return [scrub(v, secrets) for v in obj]
    return obj


def main():
    from canary.env import Env
    from canary.redteam import seed_attack
    from canary.rules import TIERS

    secrets_to_scrub: list[str] = []
    report = {}

    # Full judge-seed regeneration vs solver, in-process (same Env the shim wraps).
    solver_rows = [json.loads(l) for l in SOLVER.read_text().splitlines()]
    solver = {(r["tier"], r["seed"]): r for r in solver_rows}
    per_tier = {}
    examples = []
    for tier in ("easy", "medium", "hard"):
        atk, ref, both = [], [], []
        for seed in range(900000, 900030):
            w = seed_attack.public_world(tier, seed)
            env = Env(tier, seed)
            assert env._world.mole == w.mole, (tier, seed, env._world.mole, w.mole)
            env.call("accuse", {"employee": w.mole})
            s_ref = solver[(tier, seed)]["score"]
            atk.append(env.score())
            ref.append(s_ref)
            both.append(env.score() > s_ref)
            if seed in (900000, 900020) or (tier == "hard" and seed == 900020):
                examples.append({"tier": tier, "seed": seed, "mole": w.mole, "attack_score": env.score(),
                                 "solver_score": s_ref, "solver_correct": solver[(tier, seed)]["correct"]})
        per_tier[tier] = {
            "n": 30,
            "attack_mean": sum(atk) / len(atk),
            "attack_min": min(atk),
            "attack_all_one": all(s == 1.0 for s in atk),
            "solver_mean": sum(ref) / len(ref),
            "n_attack_beats_solver": sum(both),
        }
    report["judge_day1_regen_vs_solver"] = per_tier
    report["examples"] = examples

    # Uniqueness: judge roster should not collide inside the judge window.
    collisions = []
    for tier in ("easy", "medium", "hard"):
        seen = {}
        for seed in range(900000, 900030):
            obs = tuple((e.id, e.name, e.dept, e.role) for e in seed_attack.public_world(tier, seed).employees)
            seen.setdefault(obs, []).append(seed)
        dups = {str(v): v for v in seen.values() if len(v) > 1}
        collisions.append({"tier": tier, "unique_rosters": len(seen), "duplicate_groups": dups})
    report["judge_roster_uniqueness"] = collisions

    # One dev-range collision check for easy seed 300 against 0..9999 (already timed in hunt 2).
    # Held-out and a train seed, public key, day-1 score.
    extra = []
    for tier, seed in (("easy", 800000), ("medium", 800100), ("hard", 150000), ("easy", 123456789)):
        w = seed_attack.public_world(tier, seed)
        env = Env(tier, seed)
        env.call("accuse", {"employee": w.mole})
        extra.append({"tier": tier, "seed": seed, "match": env._world.mole == w.mole, "score": env.score(),
                      "in_judge": 900000 <= seed < 900030, "in_heldout": 800000 <= seed < 800200,
                      "in_train": 100000 <= seed < 200000})
    report["other_ranges_public_key"] = extra

    # Secret closes PUBLIC regeneration, but /proc of the server still has the secret and the seed.
    import secrets as _secrets
    world_secret = "ws_" + _secrets.token_hex(8)
    secrets_to_scrub.append(world_secret)
    proc, base, token = start_shim("easy", 900003, {"CANARY_WORLD_SECRET": world_secret})
    secrets_to_scrub.append(token)
    try:
        envdump = read_environ(proc.pid)
        leaked_seed = envdump.get("CANARY_SEED")
        leaked_tier = envdump.get("CANARY_TIER")
        leaked_secret = envdump.get("CANARY_WORLD_SECRET")
        leaked_token = envdump.get("CANARY_LEDGER_TOKEN")
        # keys present, values redacted in the report
        present = sorted(k for k in envdump if k.startswith("CANARY_"))
        # public regen does NOT match the served world
        obs = [(r["id"], r["name"], r["dept"], r["role"])
               for r in mcp_call(base, "list_employees", {})["data"]["employees"]]
        public_hit = seed_attack.recover_mole("easy", obs, range(900000, 900030))
        # regen WITH the leaked secret, in a child so this process stays clean
        child = subprocess.run(
            [sys.executable, "-c",
             "import os,json,sys\n"
             "os.environ['CANARY_WORLD_SECRET']=sys.argv[1]\n"
             "from canary.world import generate_world\n"
             "from canary.rules import TIERS\n"
             "w=generate_world(sys.argv[2], int(sys.argv[3]), TIERS[sys.argv[2]])\n"
             "print(w.mole)\n",
             leaked_secret, leaked_tier, leaked_seed],
            cwd=ROOT, capture_output=True, text=True)
        mole = child.stdout.strip()
        tool = mcp_call(base, "accuse", {"employee": mole}, 2)
        _, led_raw = http_json("GET", f"{base}/ledger?token={leaked_token}")
        led = json.loads(led_raw)
        # a public-key mole on a SECOND server with the same secret should score -1
        report["secret_plus_proc"] = {
            "canary_env_keys_visible_in_proc": present,
            "leaked_seed": leaked_seed,
            "leaked_tier": leaked_tier,
            "secret_leaked": leaked_secret == world_secret,
            "token_leaked": leaked_token == token,
            "public_roster_search_in_judge_window": public_hit,  # expect None
            "child_regen_rc": child.returncode,
            "child_stderr": child.stderr[-300:],
            "accused_with_leaked_secret_tool": tool.get("data"),
            "ledger_score": led.get("score"),
            "ledger_correct": led["ledger"][0]["detail"].get("correct") if led.get("ledger") else None,
        }
    finally:
        stop(proc)

    # Same secret, accuse the PUBLIC-key mole, expect -1 (proves the secret actually changes the world).
    proc, base, token = start_shim("easy", 900003, {"CANARY_WORLD_SECRET": world_secret})
    secrets_to_scrub.append(token)
    try:
        pub = seed_attack.public_world("easy", 900003)
        tool = mcp_call(base, "accuse", {"employee": pub.mole}, 1)
        _, raw = http_json("GET", f"{base}/ledger?token={token}")
        led = json.loads(raw)
        report["secret_public_mole_is_wrong"] = {
            "public_mole": pub.mole,
            "tool": tool.get("data"),
            "score": led.get("score"),
            "correct": led["ledger"][0]["detail"].get("correct"),
        }
    finally:
        stop(proc)

    # Out-of-range seed, NO secret: brute of judge+dev windows misses; /proc seed hits score 1.0.
    odd_seed = 4242424242
    proc, base, token = start_shim("medium", odd_seed)
    secrets_to_scrub.append(token)
    try:
        envdump = read_environ(proc.pid)
        obs = [(r["id"], r["name"], r["dept"], r["role"])
               for r in mcp_call(base, "list_employees", {})["data"]["employees"]]
        t0 = time.perf_counter()
        miss = seed_attack.recover_mole("medium", obs, list(range(900000, 900030)) + list(range(0, 200)))
        # confirm the leaked seed's public world matches and scores 1
        leaked = int(envdump["CANARY_SEED"])
        w = seed_attack.public_world("medium", leaked)
        # roster check
        regen_roster = [(e.id, e.name, e.dept, e.role) for e in w.employees]
        tool = mcp_call(base, "accuse", {"employee": w.mole}, 2)
        _, raw = http_json("GET", f"{base}/ledger?token={token}")
        led = json.loads(raw)
        report["outofrange_seed_needs_proc_or_known_seed"] = {
            "seed": odd_seed,
            "brute_judge_plus_dev0_199": miss,
            "brute_seconds": round(time.perf_counter() - t0, 3),
            "proc_seed": leaked,
            "roster_match": regen_roster == obs,
            "score": led.get("score"),
            "correct": led["ledger"][0]["detail"].get("correct"),
            "tool": tool.get("data"),
        }
    finally:
        stop(proc)

    # ps cmdline also shows the module, not the seed (seed is only in environ). Confirm cmdline.
    proc, base, token = start_shim("easy", 111)
    secrets_to_scrub.append(token)
    try:
        cmdline = Path(f"/proc/{proc.pid}/cmdline").read_bytes().replace(b"\0", b" ").decode()
        report["cmdline_has_seed"] = {"cmdline": cmdline, "contains_111": "111" in cmdline}
    finally:
        stop(proc)

    report = scrub(report, secrets_to_scrub)
    # belt: drop any leftover hex-looking secret if scrub missed
    OUT.write_text(json.dumps(report, indent=1, default=str))
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
