from __future__ import annotations

import importlib.util
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXT_ROOT = ROOT / "results" / "frontier_replication" / "v1.4" / "opencode-gemini-4-carbon-ext"
EXT_HARD = EXT_ROOT / "hard"
REF_HARD = ROOT / "data" / "runs" / "committed" / "v1.4" / "reference" / "solver-hard-seeds30to59"
EXPECTED_SEEDS = [30, 34, 42, 45, 48, 57, 58]


def _load_script(name: str, rel_path: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel_path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _read_jsonl(path: Path) -> list[dict]:
    assert path.is_file()
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_frontier_replication_v14_manifest_and_transcripts():
    episodes = _read_jsonl(EXT_HARD / "episodes.jsonl")
    assert [ep["seed"] for ep in episodes] == EXPECTED_SEEDS
    for ep in episodes:
        assert ep["tier"] == "hard"
        assert ep["agent"] == "opencode:google/gemini-4-carbon"
        assert ep["end_reason"] == "accused"
        assert (ep.get("meta") or {}).get("valid") is True
        assert len(ep.get("steps") or []) > 0

    meta = json.loads((EXT_HARD / "meta.json").read_text(encoding="utf-8"))
    assert meta["tier"] == "hard"
    assert meta["tiers_version"] == "v1.4"
    assert meta["seeds"] == EXPECTED_SEEDS

    transcripts_dir = EXT_HARD / "transcripts"
    assert transcripts_dir.is_dir()
    tr_files = sorted(transcripts_dir.iterdir())
    assert [p.name for p in tr_files] == [f"{seed}.txt" for seed in EXPECTED_SEEDS]
    assert all(p.is_file() and p.stat().st_size > 0 for p in tr_files)

    tags = json.loads((EXT_ROOT / "tags.json").read_text(encoding="utf-8"))
    assert tags["opencode:google/gemini-4-carbon"]["episodes"] == len(EXPECTED_SEEDS)
    assert (EXT_ROOT / "accuse.md").is_file()


def test_frontier_replication_v14_replays_and_pairs_with_reference(monkeypatch):
    monkeypatch.setenv("CANARY_ALLOW_DEV", "1")
    vr = _load_script("verify_replay", "scripts/verify_replay.py")
    gvr = _load_script("gap_vs_reference", "scripts/gap_vs_reference.py")

    ext_path = EXT_HARD / "episodes.jsonl"
    ref_path = REF_HARD / "episodes.jsonl"
    episodes = _read_jsonl(ext_path)
    for ep in episodes:
        rep = vr.replay_episode(ep)
        assert abs(rep["score"] - ep["score"]) < 1e-9
        assert rep["accused"] == ep["accused"]
        assert rep["correct"] == ep["correct"]
        assert rep["final_day"] == ep["final_day"]
    assert vr.main([str(ext_path)]) == 0

    ref_episodes = _read_jsonl(ref_path)
    assert [ep["seed"] for ep in ref_episodes] == list(range(30, 60))
    ref_by_seed = {ep["seed"]: ep for ep in ref_episodes}
    for ep in episodes:
        ref_ep = ref_by_seed[ep["seed"]]
        assert ref_ep["tier"] == "hard"
        assert ref_ep["agent"] == "solver"
        rep_ref = vr.replay_episode(ref_ep)
        assert abs(rep_ref["score"] - ref_ep["score"]) < 1e-9
        assert rep_ref["accused"] == ref_ep["accused"]

    ext_map, ext_invalid = gvr.collect([str(ext_path)])
    ref_map, ref_invalid = gvr.collect([str(ref_path)])
    assert ext_invalid == 0 and ref_invalid == 0
    expected_keys = [("hard", seed) for seed in EXPECTED_SEEDS]
    assert sorted(ext_map.keys()) == expected_keys
    assert all(key in ref_map for key in expected_keys)
    ext_scores = [ext_map[key]["score"] for key in expected_keys]
    ref_scores = [ref_map[key]["score"] for key in expected_keys]
    boot = gvr.paired_bootstrap(ext_scores, ref_scores, n_boot=2000)
    assert boot["n"] == len(EXPECTED_SEEDS)
    assert math.isfinite(boot["ratio"]) and boot["ratio"] > 0.0
    assert boot["diff_ci"][0] <= boot["diff"] <= boot["diff_ci"][1]
