"""Replay a recorded trajectory on a fresh episode and grade it.

This proves a score is reproducible: the world is rebuilt from (family, seed, difficulty),
the recorded tool calls are sent again in order, and the final state is graded.
The episode is found from meta.json next to the trajectory, a {"meta": {...}} first line,
or state.json next to it.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from . import payloads
from .episode import Episode
from .state import load_json
from .tools import CUT_MARK_RE

_CUT = re.compile(CUT_MARK_RE)


@dataclass
class ReplayResult:
    episode: Episode
    report: object
    meta: dict
    calls: int
    mismatches: list = field(default_factory=list)

    @property
    def consistent(self) -> bool:
        return not self.mismatches


def _restore(obj):
    """Undo the trajectory's cut of giant strings (same length, so the same validation error)."""
    if isinstance(obj, str):
        m = _CUT.search(obj)
        if m:
            return obj[: m.start()] + " " * (int(m.group(1)) + 1)
        return obj
    if isinstance(obj, list):
        return [_restore(x) for x in obj]
    if isinstance(obj, dict):
        return {k: _restore(v) for k, v in obj.items()}
    return obj


def load_trajectory(path) -> tuple[dict, list]:
    path = Path(path)
    meta: dict = {}
    records: list = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            if "meta" in rec and "tool" not in rec:
                meta.update(rec["meta"])
            elif "tool" in rec:
                records.append(rec)
    if (path.parent / "meta.json").exists():
        meta = {**load_json(path.parent / "meta.json"), **meta}
    if not {"family", "seed", "difficulty"} <= set(meta) and (path.parent / "state.json").exists():
        smeta = load_json(path.parent / "state.json").get("meta", {})
        meta = {**smeta, **meta}
    if not {"family", "seed", "difficulty"} <= set(meta):
        raise ValueError(f"cannot tell which episode {path} belongs to (no meta.json)")
    records.sort(key=lambda r: r.get("i", 0))
    return meta, records


def _same(rec: dict, out: dict) -> bool:
    if bool(rec.get("ok")) != bool(out.get("ok")):
        return False
    if out.get("ok"):
        return "result" not in rec or rec["result"] == out["result"]
    return "error" not in rec or rec["error"] == out["error"]


def replay(path, payload_sources: str | None = None) -> ReplayResult:
    from .grader import grade
    meta, records = load_trajectory(path)
    ctx_meta = dict(meta)
    if payload_sources:
        ctx_meta["payload_sources"] = payload_sources
    with payloads.context_for(ctx_meta):
        ep = Episode.create(meta["family"], int(meta["seed"]), int(meta["difficulty"]))
    info = {k: v for k, v in meta.items() if k in ("agent", "kind", "repeat", "model")}
    ep.info.update(info)
    mismatches = []
    for rec in records:
        out = ep.call(rec.get("tool"), _restore(rec.get("args")))
        if not _same(rec, out):
            mismatches.append({"i": rec.get("i"), "tool": rec.get("tool"),
                               "recorded_ok": rec.get("ok"), "replayed_ok": out.get("ok")})
    return ReplayResult(ep, grade(ep), meta, len(records), mismatches)
