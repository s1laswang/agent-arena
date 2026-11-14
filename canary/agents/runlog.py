"""Shared data/runs/<run_id>/ writer (CONTRACT section 5)."""
from __future__ import annotations

import dataclasses
import json
import re
import subprocess
import time
from pathlib import Path


def run_id(agent: str, tier: str, now: float | None = None) -> str:
    stamp = time.strftime("%Y%m%d-%H%M", time.localtime(now))
    return re.sub(r"[^A-Za-z0-9._+-]", "_", f"{agent}-{tier}-{stamp}")


def git_sha() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True,
                              cwd=Path(__file__).resolve().parent, timeout=5).stdout.strip() or "unknown"
    except Exception:
        return "unknown"


def parse_seeds(s: str) -> list[int]:
    out: list[int] = []
    for part in s.split(","):
        part = part.strip()
        if "-" in part:
            a, b = part.split("-")
            out.extend(range(int(a), int(b) + 1))
        elif part:
            out.append(int(part))
    return out


def split_spec(agent: str) -> tuple[str, str]:
    provider, _, model = agent.partition(":")
    return provider, model


class RunWriter:
    def __init__(self, out: Path):
        self.out = Path(out)
        (self.out / "transcripts").mkdir(parents=True, exist_ok=True)
        self.episodes = self.out / "episodes.jsonl"

    def episode(self, result) -> None:
        d = dataclasses.asdict(result) if dataclasses.is_dataclass(result) else result
        with self.episodes.open("a") as f:
            f.write(json.dumps(d, default=str) + "\n")

    def transcript(self, seed: int, obj, suffix: str = "json") -> None:
        p = self.out / "transcripts" / f"{seed}.{suffix}"
        p.write_text(obj if isinstance(obj, str) else json.dumps(obj, indent=1, default=str))

    def meta(self, meta: dict) -> None:
        (self.out / "meta.json").write_text(json.dumps(meta, indent=1, default=str))
