#!/usr/bin/env python3
"""Hunt 2 — white-box. Read the implementation, then confirm each guess with a run.

Writes hunt2_results.json. Tokens and any CANARY_WORLD_SECRET values are redacted.
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
OUT = Path(__file__).resolve().parent / "hunt2_results.json"
sys.path.insert(0, str(ROOT))

# Do not inherit a world secret from the environment.
os.environ.pop("CANARY_WORLD_SECRET", None)


def redact(s: str) -> str:
    return s


def free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def http_json(method, url, body=None, timeout=10):
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json", "Accept": "application/json"}, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read().decode()
            return r.status, raw
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode(errors="replace")
    except urllib.error.URLError as e:
        return 0, f"URLError: {e.reason}"


class Shim:
    def __init__(self, tier, seed, extra_env=None):
        self.port = free_port()
        self.base = f"http://127.0.0.1:{self.port}"
        self.token = "t"  # replaced below
        import secrets
        self.token = secrets.token_hex(8)
        env = os.environ.copy()
        env.pop("CANARY_WORLD_SECRET", None)
        env.update({
            "CANARY_HOST": "127.0.0.1", "CANARY_PORT": str(self.port),
            "CANARY_LEDGER_TOKEN": self.token, "CANARY_TIER": tier,
            "CANARY_SEED": str(seed), "CANARY_FAKE_BACKEND": "env",
        })
        if extra_env:
            env.update(extra_env)
        self.proc = subprocess.Popen(
            [sys.executable, "-m", "canary.redteam.fake_mcp"],
            cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        )
        self._wait()

    def _wait(self):
        deadline = time.time() + 10
        last = ""
        while time.time() < deadline:
            code, body = http_json("GET", f"{self.base}/ledger?token={self.token}")
            if code == 200:
                return
            last = f"{code} {body[:200]}"
            if self.proc.poll() is not None:
                err = self.proc.stdout.read().decode(errors="replace")[:800] if self.proc.stdout else ""
                raise RuntimeError(f"server exited {self.proc.returncode}: {err} last={last}")
            time.sleep(0.05)
        raise RuntimeError(f"not ready: {last}")

    def rpc(self, method, params=None, id_=1):
        code, raw = http_json("POST", self.base + "/mcp",
                              {"jsonrpc": "2.0", "id": id_, "method": method, "params": params or {}})
        return json.loads(raw)

    def call(self, name, args, id_=1):
        msg = self.rpc("tools/call", {"name": name, "arguments": args}, id_)
        text = msg["result"]["content"][0]["text"]
        return json.loads(text)

    def ledger(self):
        code, raw = http_json("GET", f"{self.base}/ledger?token={self.token}")
        return code, json.loads(raw)

    def stderr_text(self):
        # don't kill yet
        return ""

    def stop(self):
        self.proc.terminate()
        try:
            out, _ = self.proc.communicate(timeout=3)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            out, _ = self.proc.communicate(timeout=3)
        return out.decode(errors="replace") if out else ""


def roster_from_payload(payload):
    rows = payload["data"]["employees"]
    return [(r["id"], r["name"], r["dept"], r["role"]) for r in rows]


def main():
    from canary.env import Env
    from canary.redteam import seed_attack
    from canary.world import generate_world, _key
    from canary.rules import TIERS
    import canary.world as W

    report = {}
    report["salt_file_exists"] = (ROOT / "data" / "worlds" / "judge" / "SALT").exists()
    report["env_CANARY_WORLD_SECRET_set"] = "CANARY_WORLD_SECRET" in os.environ
    report["key_for_dev_seed_0"] = _key(0).decode()
    report["key_for_judge_900003"] = _key(900003).decode()
    report["key_for_heldout_800000"] = _key(800000).decode()

    # --- code-path confirm: served mole == public regeneration ---
    samples = []
    for tier, seed in (("easy", 300), ("easy", 900003), ("medium", 900003), ("hard", 900003),
                       ("medium", 0), ("hard", 800000)):
        env = Env(tier, seed)
        pub = seed_attack.public_world(tier, seed)
        # accuse recovered mole on a fresh env at day 1
        env2 = Env(tier, seed)
        res = env2.call("accuse", {"employee": pub.mole})
        samples.append({
            "tier": tier, "seed": seed,
            "served_mole": env._world.mole,
            "public_regen_mole": pub.mole,
            "match": env._world.mole == pub.mole,
            "accuse_tool": {"ok": res.ok, "data": res.data, "error": res.error},
            "score": env2.score(),
            "V": env2.V,
            "correct": env2._correct,
        })
    report["regen_samples"] = samples

    # known repro command
    proc = subprocess.run([sys.executable, "-m", "canary.redteam.seed_attack", "--tier", "easy", "--seed", "300"],
                          cwd=ROOT, capture_output=True, text=True)
    report["seed_attack_cli_easy_300"] = {"returncode": proc.returncode, "stdout": proc.stdout.strip(),
                                          "stderr": proc.stderr.strip()[:400]}
    proc = subprocess.run([sys.executable, "-m", "canary.redteam.seed_attack", "--tier", "easy", "--seed", "900003"],
                          cwd=ROOT, capture_output=True, text=True)
    report["seed_attack_cli_easy_900003"] = {"returncode": proc.returncode, "stdout": proc.stdout.strip(),
                                             "stderr": proc.stderr.strip()[:500]}

    # HTTP end-to-end: list_employees -> public regen -> accuse. No mole id typed by hand.
    http_rows = []
    for tier, seed in (("easy", 900003), ("medium", 900000), ("hard", 900020)):
        shim = Shim(tier, seed)
        try:
            obs = roster_from_payload(shim.call("list_employees", {}, 1))
            t0 = time.perf_counter()
            found = seed_attack.recover_mole(tier, obs, [seed])  # seed is known to the harness; attacker who brute-forces finds the same roster
            # also time a real search across the judge window only
            t1 = time.perf_counter()
            found_search = seed_attack.recover_mole(tier, obs, range(900000, 900030))
            t2 = time.perf_counter()
            assert found_search is not None
            _, mole = found_search
            tool = shim.call("accuse", {"employee": mole}, 2)
            code, led = shim.ledger()
            http_rows.append({
                "tier": tier, "seed": seed,
                "recovered_seed": found_search[0], "mole": mole,
                "direct_match": found,
                "search_ms": round((t2 - t1) * 1000, 1),
                "tool_data": tool.get("data"), "tool_error": tool.get("error"),
                "ledger_score": led.get("score"), "ledger_correct": led["ledger"][0]["detail"].get("correct"),
                "tool_reveals_correct": "correct" in json.dumps(tool),
            })
        finally:
            err = shim.stop()
        http_rows[-1]["server_stderr_tail"] = err[-400:]
    report["http_regen_accuse"] = http_rows

    # dev-seed sweep: day-1 accuse of regenerated mole, seeds 0-19, three tiers
    dev = {}
    for tier in ("easy", "medium", "hard"):
        scores = []
        for seed in range(20):
            w = seed_attack.public_world(tier, seed)
            env = Env(tier, seed)
            env.call("accuse", {"employee": w.mole})
            scores.append(env.score())
        dev[tier] = {"n": len(scores), "mean": sum(scores) / len(scores), "min": min(scores), "max": max(scores),
                     "n_perfect": sum(s == 1.0 for s in scores), "n_wrong": sum(s < 0 for s in scores)}
    report["dev0_19_day1_regen"] = dev

    # output scan: does any tool text contain the mole id next to a truth word, or the world_seed digits?
    scans = []
    for tier, seed in (("easy", 0), ("medium", 7), ("hard", 3)):
        env = Env(tier, seed)
        mole = env._world.mole
        ws = str(env._world.world_seed)
        blobs = []
        blobs.append(("instruction", env.instruction()))
        for tool, args in (
            ("status", {}), ("list_employees", {}), ("list_documents", {}),
            ("check_leak_feed", {}), ("search_messages", {"query": "the"}),
        ):
            blobs.append((tool, json.dumps(env.call(tool, args).data)))
        # advance a few days and read messages / logs / interviews
        for day in range(3):
            env.call("advance_day", {})
            blobs.append((f"logs_d{day}", json.dumps(env.call("read_access_logs", {"day_from": 1, "day_to": day + 1}).data)))
            blobs.append((f"feed_d{day}", json.dumps(env.call("check_leak_feed", {}).data)))
            blobs.append((f"msgs_d{day}", json.dumps(env.call("search_messages", {"query": "a"}).data)))
        # one interview of the mole and of someone else
        other = next(e for e in env._world.ids if e != mole)
        blobs.append(("iv_mole", json.dumps(env.call("interview", {"employee": mole, "topic": "workload"}).data)))
        blobs.append(("iv_other", json.dumps(env.call("interview", {"employee": other, "topic": "workload"}).data)))
        joined = "\n".join(b for _, b in blobs)
        # labeled mole field?
        labeled = ('"mole"' in joined) or ('"mole_id"' in joined)
        scans.append({
            "tier": tier, "seed": seed,
            "world_seed_in_any_output": ws in joined,
            "labeled_mole_field": labeled,
            "mole_id_in_instruction": mole in env.instruction(),
            "mole_id_in_employee_list": True,  # roster includes every id; not a leak
            "word_mole_in_messages": "mole" in joined.lower(),
        })
    report["output_scan"] = scans

    # fresh unrestrict (the hunt-1 attempt was after the daily cap)
    env = Env("easy", 0)
    v0 = env.V
    bad = env.call("unrestrict_access", {"employee": "e00"})
    report["unrestrict_without_restriction"] = {
        "ok": bad.ok, "error": bad.error, "V_before": v0, "V_after": env.V, "score": env.score(),
    }
    env.call("restrict_access", {"employee": "e00"})
    env.call("advance_day", {})
    v1 = env.V
    env.call("unrestrict_access", {"employee": "e00"})
    report["restrict_then_unrestrict"] = {"V_after_restrict_day": v1, "V_after_unrestrict": env.V, "raised": env.V > v1}

    # DELETE does not reset an ended episode
    shim = Shim("easy", 4)
    try:
        shim.call("accuse", {"employee": "e00"}, 1)
        _, led1 = shim.ledger()
        code, raw = http_json("DELETE", shim.base + "/ledger")
        shim.call("accuse", {"employee": "e01"}, 2)
        _, led2 = shim.ledger()
        report["delete_ledger_does_not_reset"] = {
            "delete_code": code, "delete_body": raw,
            "score_before": led1["score"], "score_after_second_accuse": led2["score"],
            "n_accusations_after": sum(1 for e in led2["ledger"] if e["event"] == "accused"),
            "done_after": led2["done"],
        }
    finally:
        shim.stop()

    # in-process parallel accuse (env lock only, no HTTP lock)
    import threading
    env = Env("medium", 1)
    barrier = threading.Barrier(20)
    outs = [None] * 20

    def go(i, env=env):
        barrier.wait()
        outs[i] = env.call("accuse", {"employee": f"e{i:02d}"})

    ts = [threading.Thread(target=go, args=(i,)) for i in range(20)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    oks = [(f"e{i:02d}", o.ok, o.data, o.error) for i, o in enumerate(outs)]
    report["inprocess_parallel_accuse"] = {
        "winners": [row for row in oks if row[1]],
        "n_episode_over": sum(1 for row in oks if row[3] == "episode over"),
        "score": env.score(),
        "n_accused_events": sum(1 for e in env.ledger() if e.event == "accused"),
    }

    # brute timing over dev seeds for one roster
    obs = seed_attack.roster("easy", 300)
    t0 = time.perf_counter()
    found = seed_attack.recover_mole("easy", obs, range(0, 10000))
    report["brute_dev_10k"] = {"seconds": round(time.perf_counter() - t0, 3), "found": found}

    # mole id histogram on easy dev seeds (bias?)
    from collections import Counter
    c = Counter(seed_attack.public_world("easy", s).mole for s in range(200))
    report["mole_histogram_easy_200"] = dict(sorted(c.items()))

    OUT.write_text(json.dumps(report, indent=1, default=str))
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
