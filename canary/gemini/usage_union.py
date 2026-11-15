"""One Gemini usage total for everything: the de-duplicated union of EVERY committed ledger.

    python -m canary.gemini.usage_union [--results results/gemini] [--out results/gemini/usage_total.json]

Reads every committed ledger under results/gemini at any depth (canary.gemini.dashboard.committed_ledgers: the whitelisted
usage export, the ladder and Gemma ladder ledgers, scale/**, ablations_*/, roles/*/ ...) and de-duplicates rows exactly as
the dashboard does (canary.gemini.dashboard.load_ledger): by (ts, host, pid, feature, model, in, out), and by the API
response/request id when a row carries one. Costs are repriced at list price the same way (ladder.json prices), then
summarised with the dashboard's own summarize(), so `python -m canary.gemini.dashboard --ledger committed` shows exactly
these totals. Keyless; no API calls.

Our ledger (canary/gemini/ledger.py) writes one self-written row per call and records no API response id, so
`rows_with_response_id` is 0 and every row is de-duplicated by the composite key.
"""
from __future__ import annotations

import argparse
import datetime as dt
import gzip
import json
from pathlib import Path

from canary.gemini import dashboard as dash


def _raw_rows(path: str) -> list[dict]:
    opener = gzip.open if path.endswith(".gz") else open
    out = []
    with opener(path, "rt") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(r, dict) and "model" in r:
                out.append(r)
    return out


def union(results_dir: Path) -> dict:
    files = dash.committed_ledgers(results_dir)
    rows = dash.load_ledger(files)
    lad = dash.load_json(Path(results_dir) / "ladder.json") or {}
    dash.reprice(rows, lad.get("prices_usd_per_1m") if isinstance(lad.get("prices_usd_per_1m"), dict) else None)
    s = dash.summarize(rows)
    t = s["totals"]
    per_file, ids = [], set()
    for f in files:
        raw = _raw_rows(f)
        ids.update(next((r[k] for k in dash.ID_FIELDS if r.get(k)), None) for r in raw)
        try:
            rel = str(Path(f).resolve().relative_to(dash.ROOT))
        except ValueError:
            rel = f
        per_file.append({"file": rel, "rows": len(raw)})
    ids.discard(None)
    raw_total = sum(p["rows"] for p in per_file)
    return {
        "generated_at": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        "what": "de-duplicated union of every committed Gemini ledger under results/gemini (canary.gemini.usage_union)",
        "dedup_key": "(ts, host, pid, feature, model, in, out); also the API response/request id when a row has one",
        "calls": t["calls"], "errors": t["errors"],
        "input_tokens": t["in"], "cached_tokens": t["cached"], "thinking_tokens": t["thinking"], "output_tokens": t["out"],
        "cache_share_of_input": s["cache"].get("hit_share"),
        "cost_usd_list": t["cost_usd"], "cost_unknown_calls": t.get("cost_unknown_calls"),
        "models": t["models"], "features": t["features"], "start": t.get("start"), "end": t.get("end"),
        "by_feature": s["by_feature"], "by_model": s["by_model"],
        "rows_with_response_id": len(ids), "rows_without_response_id": t["calls"] - len(ids),
        "response_id_note": ("canary/gemini/ledger.py writes one self-written row per call (bulk ladder rows included) and "
                             "records no API response id, so every row is de-duplicated by the composite key."),
        "raw_rows_in_files": raw_total, "duplicates_removed": raw_total - t["calls"],
        "files": per_file,
    }


def headline(u: dict) -> str:
    """The single line to quote everywhere."""
    return (f"{u['calls']:,} Gemini API calls, {u['input_tokens'] / 1e6:,.0f}M input tokens "
            f"({u['cache_share_of_input'] * 100:.1f}% served from cache), {u['thinking_tokens'] / 1e6:,.1f}M thinking tokens, "
            f"${u['cost_usd_list']:,.2f} at list price (results/gemini/usage_total.json)")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--results", default=str(dash.DEFAULT_RESULTS))
    ap.add_argument("--out", default=None)
    a = ap.parse_args(argv)
    u = union(Path(a.results))
    u["headline"] = headline(u)
    out = Path(a.out) if a.out else Path(a.results) / "usage_total.json"
    out.write_text(json.dumps(u, indent=1) + "\n")
    print(u["headline"])
    print(f"{len(u['files'])} ledger files, {u['raw_rows_in_files']:,} raw rows, {u['duplicates_removed']:,} duplicates removed -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
