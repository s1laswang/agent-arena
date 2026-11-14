"""Episode: one world + its trajectory. Create, load, save, call tools.

Folder layout (runs/<name>/):
  state.json        full state (includes hidden; never shown to agents)
  trajectory.jsonl  one line per tool call: {"i","tool","args","ok","result"|"error"}
  meta.json         {"family","seed","difficulty","episode_id","payload_sources", "agent"?, "kind"?, "repeat"?}
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from . import payloads
from .state import dumps, load_json, save_json, write_text
from .tools import dispatch, tool_specs

SPEC_RE = re.compile(r"^(?P<family>[a-z_][a-z0-9_]*)(?:[:/]|-s)(?P<seed>-?\d+)(?:[:/]|-d)(?P<difficulty>\d+)$")


def parse_spec(text: str):
    """'ap_run:7:2' or 'ap_run-s7-d2' -> ("ap_run", 7, 2); else None."""
    m = SPEC_RE.match(text.strip())
    if not m:
        return None
    return m.group("family"), int(m.group("seed")), int(m.group("difficulty"))


class Episode:
    def __init__(self, state: dict, trajectory: list | None = None, path=None, autosave: bool = False,
                 info: dict | None = None):
        self.state = state
        self.trajectory = trajectory if trajectory is not None else []
        self.path = Path(path) if path else None
        self.autosave = autosave
        self.info = dict(info or {})   # extra meta: agent, kind, repeat ...

    # ------------------------------------------------------------ create / load
    @classmethod
    def create(cls, family: str, seed: int, difficulty: int, path=None, autosave: bool = False,
               info: dict | None = None) -> "Episode":
        from .tasks import get_task
        task = get_task(family)
        state = task.generate(int(seed), int(difficulty))
        state["meta"]["payload_sources"] = payloads.current_mode()
        if payloads.forced_active():
            state["meta"]["forced_payloads"] = payloads.forced_snapshot()
        ep = cls(state, [], path, autosave, info)
        if ep.path:
            ep.save()
        return ep

    @classmethod
    def load(cls, path, autosave: bool = False) -> "Episode":
        path = Path(path)
        state = load_json(path / "state.json")
        traj = []
        tpath = path / "trajectory.jsonl"
        if tpath.exists():
            with open(tpath, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        rec = json.loads(line)
                        if "tool" in rec:
                            traj.append(rec)
        info = {}
        mpath = path / "meta.json"
        if mpath.exists():
            meta = load_json(mpath)
            info = {k: v for k, v in meta.items()
                    if k not in ("family", "seed", "difficulty", "episode_id", "payload_sources")}
        return cls(state, traj, path, autosave, info)

    @classmethod
    def from_spec(cls, spec: str, runs_dir="runs", autosave: bool = False) -> "Episode":
        """An episode folder path, or 'family:seed:difficulty' / 'family-sS-dD' (creates it in runs_dir)."""
        p = Path(spec)
        if (p / "state.json").exists():
            return cls.load(p, autosave=autosave)
        parsed = parse_spec(spec)
        if parsed is None:
            raise ValueError(f"not an episode folder or spec like ap_run:7:2 -> {spec!r}")
        family, seed, difficulty = parsed
        from .state import episode_id
        folder = Path(runs_dir) / episode_id(family, seed, difficulty)
        if (folder / "state.json").exists():
            return cls.load(folder, autosave=autosave)
        return cls.create(family, seed, difficulty, path=folder, autosave=autosave)

    def fresh(self) -> "Episode":
        """A new, untouched in-memory episode with the same world (same seed, payload mode, forced wordings)."""
        with payloads.context_for(self.meta):
            return Episode.create(self.family, self.seed, self.difficulty)

    # ------------------------------------------------------------ properties
    @property
    def meta(self) -> dict:
        return self.state["meta"]

    @property
    def family(self) -> str:
        return self.meta["family"]

    @property
    def seed(self) -> int:
        return int(self.meta["seed"])

    @property
    def difficulty(self) -> int:
        return int(self.meta["difficulty"])

    @property
    def episode_id(self) -> str:
        return self.meta["episode_id"]

    @property
    def payload_sources(self) -> str:
        return self.meta.get("payload_sources", "handwritten")

    @property
    def task(self):
        from .tasks import get_task
        return get_task(self.family)

    # ------------------------------------------------------------ use
    def instruction(self) -> str:
        return self.task.instruction(self.state)

    def tools(self) -> list[dict]:
        return tool_specs(self.family)

    def call(self, name, args=None) -> dict:
        out = dispatch(self.state, name, args, self.trajectory)
        if self.autosave and self.path:
            try:
                self.save()
            except OSError:
                pass
        return out

    def grade(self):
        from .grader import grade
        return grade(self)

    # ------------------------------------------------------------ save
    def meta_record(self) -> dict:
        rec = {"family": self.family, "seed": self.seed, "difficulty": self.difficulty,
               "episode_id": self.episode_id, "payload_sources": self.payload_sources}
        if self.meta.get("forced_payloads"):
            rec["forced_payloads"] = self.meta["forced_payloads"]
        rec.update(self.info)
        return rec

    def save(self, path=None, state: bool = True) -> Path:
        if path is not None:
            self.path = Path(path)
        if self.path is None:
            raise ValueError("episode has no folder; pass a path")
        self.path.mkdir(parents=True, exist_ok=True)
        if state:
            write_text(self.path / "state.json", dumps(self.state) + "\n")
        lines = "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in self.trajectory)
        write_text(self.path / "trajectory.jsonl", lines)
        save_json(self.path / "meta.json", self.meta_record())
        return self.path
