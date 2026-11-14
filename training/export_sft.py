"""Build an SFT dataset (JSONL, OpenAI / Hugging Face chat format with tool calls).

Sources:
  (a) the scripted reference agent on each family's TRAIN seeds (Task.train_seeds()),
  (b) optionally, successful recorded LLM runs (--recorded DIR). Each one is replayed on a
      fresh world and kept only if it still scores reward 1.
Eval seeds never go in: runs on an eval seed are skipped, and a final check over every row
stops the export if one slipped through.

    python training/export_sft.py                                  # all families, 200 each
    python training/export_sft.py --families ap_run --n-per-family 50 --out training/data/ap.jsonl
    python training/export_sft.py --recorded runs/gemini           # add good Gemini runs (non-eval seeds only)

Stdlib only. One row = {"id", "source", "family", "seed", "difficulty", "episode_id", "reward",
"messages", "tools"} (see training/common.py). --openai-only writes just {"messages", "tools"}.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from training.common import ROOT, openai_tools, trajectory_to_messages, validate_row  # noqa: E402

from pinbox import payloads  # noqa: E402
from pinbox.client import EpisodeClient  # noqa: E402
from pinbox.episode import Episode  # noqa: E402
from pinbox.grader import grade  # noqa: E402
from pinbox.tasks import all_tasks, get_task  # noqa: E402
from pinbox.tools import write_tool_names  # noqa: E402

DEFAULT_OUT = ROOT / "training" / "data" / "sft.jsonl"


class EvalSeedLeak(AssertionError):
    """A row uses a seed from the frozen eval set."""


def eval_seeds() -> dict:
    """{family: set of every seed used in that family's eval set} (any difficulty)."""
    return {t.family: {int(s) for s, _ in t.eval_specs()} for t in all_tasks()}


def assert_no_eval_leak(rows: list, banned: dict | None = None) -> None:
    """Raise EvalSeedLeak if any row's seed is an eval seed of its family. Never skipped (no plain assert)."""
    banned = eval_seeds() if banned is None else banned
    bad = [r.get("id") for r in rows if int(r["seed"]) in banned.get(r["family"], set())]
    if bad:
        raise EvalSeedLeak(f"{len(bad)} row(s) use eval seeds: {bad[:5]}")


def train_pairs(task, n: int, difficulties=None) -> list:
    """n (seed, difficulty) pairs from the task's train seeds, cycling difficulties, all distinct."""
    seeds = list(task.train_seeds())
    diffs = list(difficulties or task.difficulties)
    banned = {int(s) for s, _ in task.eval_specs()}
    seeds = [s for s in seeds if s not in banned]
    if not seeds or not diffs:
        return []
    n = min(int(n), len(seeds) * len(diffs))
    # round r = k // len(seeds) gives every seed the next difficulty, so all pairs differ
    return [(seeds[k % len(seeds)], diffs[(k % len(seeds) + k // len(seeds)) % len(diffs)]) for k in range(n)]


def _row(ep, source: str, trajectory: list, extra: dict | None = None) -> dict:
    tools = openai_tools(ep.tools())
    msgs = trajectory_to_messages(ep.instruction(), trajectory, write_tool_names(ep.family))
    row = {"id": f"{ep.episode_id}:{source}", "source": source, "family": ep.family, "seed": ep.seed,
           "difficulty": ep.difficulty, "episode_id": ep.episode_id, "payload_sources": ep.payload_sources,
           "reward": 1, "n_calls": len(trajectory), "messages": msgs, "tools": tools}
    row.update(extra or {})
    return row


def reference_rows(families=None, n_per_family: int = 200, difficulties=None, log=print):
    """Reference runs on train seeds. Returns (rows, skipped) - skipped = runs that did not score 1."""
    rows, skipped = [], []
    for task in all_tasks():
        if families and task.family not in families:
            continue
        kept = 0
        for seed, diff in train_pairs(task, n_per_family, difficulties):
            ep = Episode.create(task.family, seed, diff)
            try:
                task.reference(EpisodeClient(ep))
                rep = grade(ep)
            except Exception as e:  # a broken family must not stop the others
                skipped.append({"episode_id": ep.episode_id, "why": f"{type(e).__name__}: {e}"})
                continue
            if rep.reward != 1:
                skipped.append({"episode_id": ep.episode_id, "why": f"reference reward {rep.reward}: "
                                f"{', '.join(rep.failure_tags)}"})
                continue
            rows.append(_row(ep, "reference", ep.trajectory))
            kept += 1
        if log:
            log(f"[export] {task.family}: {kept} reference rows")
    return rows, skipped


def recorded_rows(directory, families=None, log=print):
    """Successful recorded runs under `directory` (replayed and re-graded). Eval seeds are skipped.

    Returns (rows, skipped).
    """
    from pinbox.replay import replay
    rows, skipped = [], []
    root = Path(directory)
    if not root.exists():
        if log:
            log(f"[export] no recorded runs at {root}")
        return rows, skipped
    banned = eval_seeds()
    seen = set()
    for tpath in sorted(root.rglob("trajectory.jsonl")):
        try:
            res = replay(tpath)
        except Exception as e:
            skipped.append({"path": str(tpath), "why": f"cannot replay: {type(e).__name__}: {e}"})
            continue
        ep = res.episode
        if families and ep.family not in families:
            continue
        if ep.seed in banned.get(ep.family, set()):
            skipped.append({"path": str(tpath), "why": "eval seed (never used for training)"})
            continue
        if res.report.reward != 1 or not res.consistent:
            why = "replay mismatch" if not res.consistent else f"reward {res.report.reward}"
            skipped.append({"path": str(tpath), "why": why})
            continue
        key = hashlib.sha256(json.dumps([ep.episode_id, ep.trajectory], sort_keys=True,
                                        ensure_ascii=False).encode("utf-8")).hexdigest()
        if key in seen:
            skipped.append({"path": str(tpath), "why": "duplicate trajectory"})
            continue
        seen.add(key)
        agent = str(res.meta.get("agent") or tpath.parent.parent.name)
        rows.append(_row(ep, f"recorded:{agent}", ep.trajectory, {"recorded_path": str(tpath)}))
    if log:
        log(f"[export] recorded: {len(rows)} successful run(s) kept, {len(skipped)} skipped")
    return rows, skipped


def build(families=None, n_per_family: int = 200, difficulties=None, recorded=None, payload_mode=None,
          log=print) -> dict:
    """Build every row in memory. Returns {"rows", "skipped"}; raises EvalSeedLeak on a leak."""
    with payloads.source_mode(payload_mode or payloads.current_mode()):
        rows, skipped = reference_rows(families, n_per_family, difficulties, log)
        for d in recorded or []:
            r2, s2 = recorded_rows(d, families, log)
            rows += r2
            skipped += s2
    assert_no_eval_leak(rows)
    for r in rows:
        errs = validate_row(r)
        if errs:
            raise ValueError(f"bad row {r['id']}: {errs[:3]}")
    return {"rows": rows, "skipped": skipped}


def stats(rows: list) -> dict:
    by_fam: dict = {}
    for r in rows:
        f = by_fam.setdefault(r["family"], {"rows": 0, "calls": 0, "chars": 0})
        f["rows"] += 1
        f["calls"] += r.get("n_calls", 0)
        f["chars"] += len(json.dumps(r["messages"], ensure_ascii=False)) + len(json.dumps(r["tools"]))
    for f in by_fam.values():
        f["mean_calls"] = round(f.pop("calls") / f["rows"], 1)
        f["mean_chars"] = int(f["chars"] / f["rows"])
        f["approx_tokens"] = int(f.pop("chars") / f["rows"] / 3.5)
    return {"rows": len(rows), "by_family": by_fam,
            "sources": sorted({r["source"] for r in rows})}


def write_jsonl(rows: list, out, openai_only: bool = False) -> Path:
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_name(out.name + ".tmp")
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        for r in rows:
            rec = {"messages": r["messages"], "tools": r["tools"]} if openai_only else r
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    tmp.replace(out)
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Export reference (and good recorded) runs as SFT chat data.")
    ap.add_argument("--families", default="", help="comma list (default: every family)")
    ap.add_argument("--n-per-family", type=int, default=200, help="reference rows per family (train seeds)")
    ap.add_argument("--difficulties", default="", help="comma list, e.g. 1,2,3 (default: all)")
    ap.add_argument("--recorded", action="append", default=[], metavar="DIR",
                    help="folder of recorded runs (trajectory.jsonl + meta.json); repeatable")
    ap.add_argument("--payloads", choices=payloads.MODES, default=None,
                    help="wording pool for the worlds (default: PINBOX_PAYLOAD_SOURCES or handwritten)")
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    ap.add_argument("--openai-only", action="store_true", help="write only {messages, tools} per row")
    args = ap.parse_args(argv)
    fams = [f.strip() for f in args.families.split(",") if f.strip()] or None
    for f in fams or []:
        get_task(f)   # unknown family -> clear error
    diffs = [int(d) for d in args.difficulties.split(",") if d.strip()] or None
    built = build(fams, args.n_per_family, diffs, args.recorded, args.payloads)
    rows = built["rows"]
    out = write_jsonl(rows, args.out, args.openai_only)
    st = stats(rows)
    st["skipped"] = len(built["skipped"])
    st["skipped_examples"] = built["skipped"][:10]
    st["eval_seed_check"] = "passed"
    st["sha256"] = hashlib.sha256(out.read_bytes()).hexdigest()[:16]
    with open(out.with_suffix(".meta.json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump({"args": vars(args), **st}, f, ensure_ascii=False, indent=1)
        f.write("\n")
    print(json.dumps({k: st[k] for k in ("rows", "by_family", "sources", "skipped")}, indent=1))
    print(f"[export] no eval seeds in the data (checked). wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
