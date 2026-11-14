"""Small shared helpers (CSV io, grouping, CI)."""
from __future__ import annotations

import csv
import math
from collections import defaultdict
from pathlib import Path
from typing import Iterable

Z95 = 1.959963984540054
CORE_COLS = {"tier", "agent", "seed", "score", "correct", "final_day", "cell", "end_reason", "secs", "wrong", "accused"}


def read_rows(path: str | Path) -> list[dict]:
    with open(path, newline="") as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        r["seed"] = int(r["seed"])
        r["score"] = float(r["score"])
        if "correct" in r:
            r["correct"] = str(r["correct"]).strip().lower() in ("1", "true", "yes")
    return rows


def write_rows(path: str | Path, rows: list[dict]) -> None:
    if not rows:
        return
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)


def cell_key(row: dict) -> tuple:
    """(tier, sorted cell params): every non-core column is a cell parameter."""
    params = tuple(sorted((k, row[k]) for k in row if k not in CORE_COLS))
    return (row["tier"], params)


def group(rows: Iterable[dict], key) -> dict:
    out: dict = defaultdict(list)
    for r in rows:
        out[key(r)].append(r)
    return dict(out)


def mean(xs: list[float]) -> float:
    return sum(xs) / len(xs) if xs else float("nan")


def std(xs: list[float]) -> float:
    """Sample std (ddof=1); 0 for n<2."""
    n = len(xs)
    if n < 2:
        return 0.0
    m = mean(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (n - 1))


def ci_half(xs: list[float]) -> float:
    return Z95 * std(xs) / math.sqrt(len(xs)) if len(xs) > 1 else float("nan")


def fmt_params(params: tuple) -> str:
    return ",".join(f"{k}={v}" for k, v in params) or "-"
