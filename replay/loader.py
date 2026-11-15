from __future__ import annotations

from collections.abc import Iterable
import json
import re
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_COMMITTED_ROOT = "data/runs/committed"
FALLBACK_TIERS_VERSION = "v1.2"

SCRIPTED_AGENTS: frozenset[str] = frozenset({
    "solver",
    "heuristic",
    "grok_tactics",
    "logs_only",
    "random",
    "restrict_all",
    "stop_early",
    "do_nothing",
})

_NON_SLUG_RE = re.compile(r"[^A-Za-z0-9_-]")
_MULTI_UNDERSCORE_RE = re.compile(r"_+")
_VERSION_SEGMENT_RE = re.compile(r"^v\d+(\.\d+)*$")

_PARSED_RUN_CACHE: dict[
    Path,
    tuple[tuple[int, int, int, int], dict[str, Any], list[dict[str, Any]]],
] = {}

__all__ = [
    "SCRIPTED_AGENTS",
    "agent_slug",
    "infer_tiers_version",
    "load_committed_episodes",
    "make_episode_id",
    "pair_with_solver",
    "provenance_info",
]


def agent_slug(agent: str) -> str:
    replaced = _NON_SLUG_RE.sub("_", str(agent))
    return _MULTI_UNDERSCORE_RE.sub("_", replaced)


def make_episode_id(tiers_version: str, tier: str, seed: int, agent: str) -> str:
    return f"{tiers_version}__{tier}__s{int(seed)}__{agent_slug(agent)}"


def provenance_info(agent: str, meta: dict[str, Any] | None = None) -> dict[str, str]:
    meta_dict = meta if isinstance(meta, dict) else {}
    if agent in SCRIPTED_AGENTS or meta_dict.get("provenance") == "scripted":
        return {"kind": "scripted", "label": "SCRIPTED", "model_id": str(agent)}
    model_id = meta_dict.get("model") or agent
    return {"kind": "real", "label": f"REAL {model_id}", "model_id": str(model_id)}


def infer_tiers_version(
    jsonl_path: Path,
    run_meta: dict[str, Any],
    ep_meta: dict[str, Any],
) -> str:
    ep_dict = ep_meta if isinstance(ep_meta, dict) else {}
    run_dict = run_meta if isinstance(run_meta, dict) else {}
    ep_version = ep_dict.get("tiers_version")
    if isinstance(ep_version, str) and ep_version.strip():
        return ep_version.strip()
    run_version = run_dict.get("tiers_version")
    if isinstance(run_version, str) and run_version.strip():
        return run_version.strip()
    for part in reversed(Path(jsonl_path).parts):
        if _VERSION_SEGMENT_RE.match(part):
            return part
    return FALLBACK_TIERS_VERSION


def _resolve_root(root: str | Path) -> Path:
    if Path(root) == Path(DEFAULT_COMMITTED_ROOT):
        repo_default = REPO_ROOT / DEFAULT_COMMITTED_ROOT
        if repo_default.exists():
            return repo_default
    candidate = Path(root)
    if not candidate.is_absolute() and not candidate.exists():
        repo_candidate = REPO_ROOT / candidate
        if repo_candidate.exists():
            return repo_candidate
    return candidate


def _read_run_meta(jsonl_path: Path) -> dict[str, Any]:
    meta_path = jsonl_path.with_name("meta.json")
    if not meta_path.is_file():
        return {}
    try:
        parsed = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _format_source_path(jsonl_path: Path) -> str:
    resolved = jsonl_path.resolve()
    try:
        return resolved.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return resolved.as_posix()


def _load_parsed_run(jsonl_path: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    resolved = jsonl_path.resolve()
    st = resolved.stat()
    meta_path = resolved.with_name("meta.json")
    if meta_path.is_file():
        mst = meta_path.stat()
        sig = (st.st_mtime_ns, st.st_size, mst.st_mtime_ns, mst.st_size)
    else:
        sig = (st.st_mtime_ns, st.st_size, -1, -1)
    cached = _PARSED_RUN_CACHE.get(resolved)
    if cached is not None and cached[0] == sig:
        return cached[1], cached[2]
    run_meta = _read_run_meta(resolved)
    parsed_eps: list[dict[str, Any]] = []
    for raw_line in resolved.read_text(encoding="utf-8").splitlines():
        stripped = raw_line.strip()
        if stripped:
            parsed_eps.append(json.loads(stripped))
    _PARSED_RUN_CACHE[resolved] = (sig, run_meta, parsed_eps)
    return run_meta, parsed_eps


def load_committed_episodes(
    root: str | Path = DEFAULT_COMMITTED_ROOT,
    include_invalid: bool = False,
    dedupe: bool = True,
    seeds: Iterable[int] | None = None,
) -> list[dict[str, Any]]:
    input_parts = Path(root).parts
    if "superseded" in input_parts:
        return []
    root_path = _resolve_root(root)
    if not root_path.exists():
        return []
    seed_filter = frozenset(int(s) for s in seeds) if seeds is not None else None
    if seed_filter is not None and not seed_filter:
        return []

    collected: list[tuple[tuple[bool, bool, str, int], dict[str, Any]]] = []
    for jsonl_path in sorted(root_path.rglob("episodes.jsonl")):
        rel_path = jsonl_path.relative_to(root_path)
        if "superseded" in rel_path.parts:
            continue
        run_meta, parsed_eps = _load_parsed_run(jsonl_path)
        source_path = _format_source_path(jsonl_path)
        rel_dir = rel_path.parent
        has_version_dir = any(_VERSION_SEGMENT_RE.match(part) for part in rel_dir.parts)

        for line_idx, ep in enumerate(parsed_eps):
            raw_ep_meta = ep.get("meta")
            ep_meta = dict(raw_ep_meta) if isinstance(raw_ep_meta, dict) else {}
            valid = ep_meta.get("valid") is not False
            if not valid and not include_invalid:
                continue

            tier = str(ep["tier"])
            seed = int(ep["seed"])
            if seed_filter is not None and seed not in seed_filter:
                continue
            agent = str(ep["agent"])
            tiers_version = infer_tiers_version(jsonl_path, run_meta, ep_meta)
            merged_meta = {
                **run_meta,
                **{k: v for k, v in ep_meta.items() if v is not None},
            }
            provenance = provenance_info(agent, merged_meta)
            episode_id = make_episode_id(tiers_version, tier, seed, agent)

            record: dict[str, Any] = {
                **ep,
                "tier": tier,
                "seed": seed,
                "agent": agent,
                "steps": list(ep.get("steps") or []),
                "score": float(ep.get("score", 0.0)),
                "accused": ep.get("accused"),
                "correct": bool(ep.get("correct", False)),
                "final_day": int(ep.get("final_day", 0)),
                "end_reason": str(ep.get("end_reason", "")),
                "meta": ep_meta,
                "episode_id": episode_id,
                "tiers_version": tiers_version,
                "provenance": provenance,
                "valid": valid,
                "source_path": source_path,
                "run_meta": dict(run_meta),
            }
            rank = (valid, has_version_dir, rel_dir.as_posix(), line_idx)
            collected.append((rank, record))

    if dedupe:
        best: dict[tuple[str, str, int, str], tuple[tuple[bool, bool, str, int], dict[str, Any]]] = {}
        for rank, record in collected:
            key = (
                record["tiers_version"],
                record["tier"],
                record["seed"],
                record["agent"],
            )
            prev = best.get(key)
            if prev is None or rank >= prev[0]:
                best[key] = (rank, record)
        episodes = [entry[1] for entry in best.values()]
    else:
        episodes = [record for _, record in collected]

    episodes.sort(
        key=lambda r: (
            r["tiers_version"],
            r["tier"],
            r["seed"],
            r["agent"],
            r["source_path"],
        )
    )
    return episodes


def _episode_is_valid(ep: dict[str, Any]) -> bool:
    if "valid" in ep:
        return bool(ep["valid"])
    return (ep.get("meta") or {}).get("valid") is not False


def pair_with_solver(episodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    solvers: dict[tuple[str, str, int], dict[str, Any]] = {}
    for ep in episodes:
        if ep.get("agent") == "solver" and _episode_is_valid(ep):
            key = (str(ep["tiers_version"]), str(ep["tier"]), int(ep["seed"]))
            solvers[key] = ep

    pairs: list[dict[str, Any]] = []
    for ep in episodes:
        if ep.get("agent") == "solver" or not _episode_is_valid(ep):
            continue
        key = (str(ep["tiers_version"]), str(ep["tier"]), int(ep["seed"]))
        solver_ep = solvers.get(key)
        if solver_ep is None:
            continue
        ep_id = ep.get("episode_id") or make_episode_id(key[0], key[1], key[2], str(ep["agent"]))
        solver_ep_id = solver_ep.get("episode_id") or make_episode_id(key[0], key[1], key[2], "solver")
        agent_score = float(ep["score"])
        solver_score = float(solver_ep["score"])
        pairs.append({
            "pair_id": f"{ep_id}__vs__solver",
            "tiers_version": key[0],
            "tier": key[1],
            "seed": key[2],
            "agent": str(ep["agent"]),
            "provenance": ep.get("provenance") or provenance_info(str(ep["agent"]), ep.get("meta")),
            "agent_episode": ep,
            "solver_episode": solver_ep,
            "agent_episode_id": ep_id,
            "solver_episode_id": solver_ep_id,
            "agent_score": agent_score,
            "solver_score": solver_score,
            "score_delta": agent_score - solver_score,
        })

    pairs.sort(
        key=lambda p: (
            p["tiers_version"],
            p["tier"],
            p["seed"],
            p["agent"],
            p["pair_id"],
        )
    )
    return pairs
