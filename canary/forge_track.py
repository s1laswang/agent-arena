"""hard_forge judge track: hard-tier params + a per-seed evolved Mole DSL strategy.

Hall of fame: JSONL, one object per line with at least {"strategy_json": <MoleStrategy JSON>}
(canary.forge.evolve format: rank, fitness, solver_score, solver_acc, per_investigator, strategy_json;
extra keys are ignored; a "strategy" key is accepted as an alias). Lines are used in file order.
The strategy for a seed = strategies[HMAC(world key, "<track>:strategy:<seed>") % len]; it is never
shown to the agent. The mole identity still comes from the salted world RNG.

    python -m canary.forge_track validate --in <hof.jsonl> --seeds 20 --out data/forge/hall_of_fame_v1.2.jsonl
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
from pathlib import Path

from .mole.dsl import MoleStrategy

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_HOF = ROOT / "data" / "forge" / "hall_of_fame_v1.2.jsonl"
MIN_ACC = 0.75
_cache: dict[str, tuple[list[dict], list[MoleStrategy]]] = {}


def hof_path() -> Path:
    return Path(os.environ.get("CANARY_FORGE_HOF") or DEFAULT_HOF)


def load(path: str | Path | None = None) -> tuple[list[dict], list[MoleStrategy]]:
    path = Path(path or hof_path())
    key = str(path.resolve())
    if key not in _cache:
        if not path.exists():
            raise FileNotFoundError(
                f"hard_forge track needs the evolved-mole hall of fame at {path} "
                "(set CANARY_FORGE_HOF or create it with `python -m canary.forge_track validate`)")
        rows, strats = [], []
        for ln in path.read_text().splitlines():
            if not ln.strip():
                continue
            row = json.loads(ln)
            sj = row.get("strategy_json", row.get("strategy"))
            if sj is None:
                raise ValueError(f"{path}: line without strategy_json")
            rows.append(row)
            strats.append(MoleStrategy.from_json(sj))
        if not strats:
            raise ValueError(f"{path}: empty hall of fame")
        _cache[key] = (rows, strats)
    return _cache[key]


def strategy_index(track: str, seed: int, n: int) -> int:
    from .world import _key
    d = hmac.new(_key(seed), f"{track}:strategy:{seed}".encode(), hashlib.sha256).digest()
    return int.from_bytes(d[:8], "big") % n


def strategy_for(track: str, seed: int, path: str | Path | None = None) -> MoleStrategy:
    _, strats = load(path)
    return strats[strategy_index(track, seed, len(strats))]


def validate(path: str | Path, seeds, out: str | Path | None = None, min_acc: float = MIN_ACC,
             tier: str = "hard") -> list[dict]:
    """Run SolverPolicy on `seeds` (ints, or an int N = dev seeds 0..N-1) per strategy; keep acc >= min_acc."""
    from .env import Env
    from .eval import run_episode
    from .solver.policy import SolverPolicy
    seeds = list(range(seeds)) if isinstance(seeds, int) else list(seeds)
    _cache.pop(str(Path(path).resolve()), None)
    rows, strats = load(path)
    keep = []
    for row, st in zip(rows, strats):
        res = [run_episode(Env(tier, s, mole_strategy=st), SolverPolicy(tier)) for s in seeds]
        acc = sum(r.correct for r in res) / len(res)
        score = sum(r.score for r in res) / len(res)
        row = dict(row, track_validation={"tier": tier, "n_seeds": len(seeds), "solver_acc": acc,
                                          "solver_score": score, "accepted": acc >= min_acc})
        if acc >= min_acc:
            keep.append(row)
    if out is not None:
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        Path(out).write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in keep))
        _cache.pop(str(Path(out).resolve()), None)
    return keep


def main(argv=None):
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    v = sub.add_parser("validate")
    v.add_argument("--in", dest="inp", required=True)
    v.add_argument("--seeds", type=int, default=20, help="dev seeds 0..N-1")
    v.add_argument("--out", default=str(DEFAULT_HOF))
    v.add_argument("--min-acc", type=float, default=MIN_ACC)
    a = ap.parse_args(argv)
    keep = validate(a.inp, a.seeds, a.out, a.min_acc)
    print(f"accepted {len(keep)} strategies -> {a.out}")


if __name__ == "__main__":
    main()
