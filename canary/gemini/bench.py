"""Closed-loop throughput probe through the gateway: C workers send short prompts back to back for T seconds.

    python -m canary.gemini.bench --models gemini-3.8-flash,gemini-4-carbon --conc 8,32,64 --seconds 30 \
        --stats data/gemini/gateway/bench --out results/gemini/gateway_bench.json

Every call is ledgered (feature "gateway-bench"). If --stats points at the gateway's --stats-dir, the gateway's
retry/429 counts and queueing per phase are folded into the summary.
"""
from __future__ import annotations

import argparse
import glob
import json
import statistics
import threading
import time
from pathlib import Path


def _pct(xs, q):
    if not xs:
        return None
    xs = sorted(xs)
    return round(xs[min(len(xs) - 1, int(q * len(xs)))], 2)


def phase(model: str, conc: int, seconds: float, level: str) -> dict:
    from google.genai import types

    from .ledger import record
    from .sdk import genai_client
    sdk = genai_client(timeout_s=120)
    stop = time.time() + seconds
    lat, errs, toks = [], {}, {"in": 0, "out": 0, "thinking": 0}
    lock = threading.Lock()
    cfg = types.GenerateContentConfig(thinking_config=types.ThinkingConfig(thinking_level=level.upper()),
                                      max_output_tokens=2048)

    def worker(i):
        n = 0
        while time.time() < stop:
            t0 = time.time()
            try:
                r = sdk.models.generate_content(
                    model=model, config=cfg,
                    contents=f"Worker {i}, request {n}: name one prime number between {n} and {n + 50}. Reply with the number only.")
                dt = time.time() - t0
                um = r.usage_metadata
                record("gateway-bench", model, usage=um, latency_s=dt, meta={"conc": conc})
                with lock:
                    lat.append(dt)
                    toks["in"] += um.prompt_token_count or 0
                    toks["out"] += um.candidates_token_count or 0
                    toks["thinking"] += um.thoughts_token_count or 0
            except Exception as e:  # noqa: BLE001
                dt = time.time() - t0
                code = getattr(e, "code", None) or type(e).__name__
                record("gateway-bench", model, latency_s=dt, ok=False, error=f"{code}: {str(e)[:120]}",
                       meta={"conc": conc})
                with lock:
                    errs[str(code)] = errs.get(str(code), 0) + 1
            n += 1

    t0 = time.time()
    ths = [threading.Thread(target=worker, args=(i,)) for i in range(conc)]
    for t in ths:
        t.start()
    for t in ths:
        t.join()
    wall = time.time() - t0
    return {"model": model, "conc": conc, "thinking_level": level, "wall_s": round(wall, 1), "ok": len(lat),
            "errors": errs, "rpm": round(60 * len(lat) / wall, 1),
            "p50_s": _pct(lat, 0.5), "p95_s": _pct(lat, 0.95),
            "mean_s": round(statistics.mean(lat), 2) if lat else None,
            "inflight_eff": round(sum(lat) / wall, 1),  # Little's law: mean requests actually in flight
            "tokens": toks, "out_tok_per_s": round((toks["out"] + toks["thinking"]) / wall, 1),
            "t_start": round(t0, 3), "t_end": round(t0 + wall, 3)}


def fold_stats(rows: list[dict], stats_glob: str) -> None:
    st = []
    for f in glob.glob(stats_glob):
        st += [json.loads(x) for x in open(f) if x.strip()]
    for r in rows:
        mine = [s for s in st if r["t_start"] - 1 <= s["ts"] <= r["t_end"] + 2 and s.get("model") == r["model"]
                and s.get("op") == "generateContent"]
        r["gw_requests"] = len(mine)
        r["gw_retries"] = sum(s.get("retries", 0) for s in mine)
        r["gw_final_status"] = {str(k): sum(1 for s in mine if s["status"] == k) for k in {s["status"] for s in mine}}
        r["gw_queued_p95_s"] = _pct([s["queued_s"] for s in mine], 0.95)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="python -m canary.gemini.bench")
    p.add_argument("--models", default="gemini-3.8-flash")
    p.add_argument("--conc", default="8,32,64")
    p.add_argument("--seconds", type=float, default=30)
    p.add_argument("--level", default="low")
    p.add_argument("--stats", default=None, help="gateway stats dir to fold in")
    p.add_argument("--out", type=Path, default=None)
    a = p.parse_args(argv)
    rows = []
    for m in a.models.split(","):
        for c in [int(x) for x in a.conc.split(",")]:
            r = phase(m, c, a.seconds, a.level)
            print(json.dumps(r), flush=True)
            rows.append(r)
            time.sleep(3)
    if a.stats:
        fold_stats(rows, str(Path(a.stats) / "stats-*.jsonl"))
    out = {"generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "seconds": a.seconds, "rows": rows}
    if a.out:
        a.out.parent.mkdir(parents=True, exist_ok=True)
        a.out.write_text(json.dumps(out, indent=1) + "\n")
    print("| model | conc | ok | rpm | p50 s | p95 s | client errors | gw retries | gw queued p95 s |")
    print("|---|---|---|---|---|---|---|---|---|")
    for r in rows:
        print(f"| {r['model']} | {r['conc']} | {r['ok']} | {r['rpm']} | {r['p50_s']} | {r['p95_s']} | "
              f"{r['errors'] or 0} | {r.get('gw_retries', '-')} | {r.get('gw_queued_p95_s', '-')} |")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
