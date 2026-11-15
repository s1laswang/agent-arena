from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from replay.loader import (
    SCRIPTED_AGENTS,
    agent_slug,
    infer_tiers_version,
    load_committed_episodes,
    make_episode_id,
    pair_with_solver,
    provenance_info,
)

REQUIRED_EPISODE_KEYS = {
    "tier",
    "seed",
    "agent",
    "steps",
    "score",
    "accused",
    "correct",
    "final_day",
    "end_reason",
    "meta",
    "episode_id",
    "tiers_version",
    "provenance",
    "valid",
    "source_path",
    "run_meta",
}


def _write_run(
    run_dir: Path,
    episodes: list[dict],
    run_meta: dict | None = None,
) -> Path:
    run_dir.mkdir(parents=True, exist_ok=True)
    if run_meta is not None:
        (run_dir / "meta.json").write_text(json.dumps(run_meta), encoding="utf-8")
    jsonl_path = run_dir / "episodes.jsonl"
    body = "\n".join(json.dumps(ep) for ep in episodes) + "\n"
    jsonl_path.write_text(body, encoding="utf-8")
    return jsonl_path


def _sample_ep(
    tier: str = "medium",
    seed: int = 0,
    agent: str = "gemini:gemini-4-carbon",
    score: float = 0.8,
    accused: str | None = "e04",
    correct: bool = True,
    final_day: int = 4,
    end_reason: str = "accused",
    meta: dict | None = None,
) -> dict:
    return {
        "tier": tier,
        "seed": seed,
        "agent": agent,
        "steps": [
            {
                "t": 0,
                "day": 1,
                "tool": "status",
                "args": {},
                "result": {"ok": True, "data": {"day": 1, "V": 1.0}, "error": None},
            }
        ],
        "score": score,
        "accused": accused,
        "correct": correct,
        "final_day": final_day,
        "end_reason": end_reason,
        "meta": meta if meta is not None else {},
    }


def test_agent_slug_and_episode_id() -> None:
    assert agent_slug("solver") == "solver"
    assert agent_slug("restrict_all") == "restrict_all"
    assert agent_slug("openai:gpt-5.5") == "openai_gpt-5_5"
    assert agent_slug("codex:gpt-5.5") == "codex_gpt-5_5"
    assert agent_slug("opencode:openai/gpt-5.6-sol") == "opencode_openai_gpt-5_6-sol"
    assert agent_slug("gemini:gemini-4-carbon") == "gemini_gemini-4-carbon"
    assert agent_slug("google/gemini-2.5-pro::v1") == "google_gemini-2_5-pro_v1"

    ep_id = make_episode_id("v1.4", "hard", 7, "gemini:gemini-4-carbon")
    assert ep_id == "v1.4__hard__s7__gemini_gemini-4-carbon"


def test_provenance_info_scripted_and_real() -> None:
    for scripted_name in SCRIPTED_AGENTS:
        info = provenance_info(scripted_name, {"model": "ignored-model"})
        assert info == {
            "kind": "scripted",
            "label": "SCRIPTED",
            "model_id": scripted_name,
        }

    override = provenance_info("custom_baseline", {"provenance": "scripted"})
    assert override == {
        "kind": "scripted",
        "label": "SCRIPTED",
        "model_id": "custom_baseline",
    }

    assert provenance_info("codex:gpt-5.5", {"model": "gpt-5.5"}) == {
        "kind": "real",
        "label": "REAL gpt-5.5",
        "model_id": "gpt-5.5",
    }
    assert provenance_info("gemini:gemini-4-carbon", {"model": "gemini-4-carbon"}) == {
        "kind": "real",
        "label": "REAL gemini-4-carbon",
        "model_id": "gemini-4-carbon",
    }
    assert provenance_info("gemini:gemini-4-carbon") == {
        "kind": "real",
        "label": "REAL gemini:gemini-4-carbon",
        "model_id": "gemini:gemini-4-carbon",
    }
    assert provenance_info("claude:claude-4-sonnet", None) == {
        "kind": "real",
        "label": "REAL claude:claude-4-sonnet",
        "model_id": "claude:claude-4-sonnet",
    }
    assert provenance_info("google/gemini-4-carbon", {}) == {
        "kind": "real",
        "label": "REAL google/gemini-4-carbon",
        "model_id": "google/gemini-4-carbon",
    }
    assert provenance_info("grok", {}) == {
        "kind": "real",
        "label": "REAL grok",
        "model_id": "grok",
    }


def test_infer_tiers_version_precedence() -> None:
    path_v14 = Path("data/runs/committed/v1.4/reference/solver/episodes.jsonl")
    path_v13 = Path("data/runs/committed/v1.3/codex/medium/episodes.jsonl")
    path_plain = Path("data/runs/committed/gpt-5.5/medium-0-4/episodes.jsonl")

    assert infer_tiers_version(
        path_v14,
        {"tiers_version": "v1.4"},
        {"tiers_version": "v1.5"},
    ) == "v1.5"
    assert infer_tiers_version(
        path_v13,
        {"tiers_version": "v1.4"},
        {},
    ) == "v1.4"
    assert infer_tiers_version(path_v13, {}, {}) == "v1.3"
    assert infer_tiers_version(path_plain, {}, {}) == "v1.2"


def test_synthetic_loading_invalid_filtering_and_gemini(tmp_path: Path) -> None:
    _write_run(
        tmp_path / "superseded" / "v1.4" / "old-gemini",
        [_sample_ep(tier="medium", seed=0, agent="gemini:gemini-4-carbon", score=0.99)],
        {"model": "gemini-4-carbon", "tiers_version": "v1.4"},
    )

    _write_run(
        tmp_path / "v1.4" / "gemini-run",
        [
            _sample_ep(
                tier="medium",
                seed=0,
                agent="gemini:gemini-4-carbon",
                score=0.72,
                meta={"valid": True},
            ),
            _sample_ep(
                tier="medium",
                seed=1,
                agent="gemini:gemini-4-carbon",
                score=0.0,
                accused=None,
                correct=False,
                end_reason="error",
                meta={"valid": False, "error": "infra:quota"},
            ),
        ],
        {"agent": "gemini:gemini-4-carbon", "model": "gemini-4-carbon", "tiers_version": "v1.4"},
    )

    _write_run(
        tmp_path / "v1.4" / "reference" / "solver-medium",
        [
            _sample_ep(tier="medium", seed=0, agent="solver", score=0.88),
            _sample_ep(tier="medium", seed=1, agent="solver", score=0.84),
        ],
        {"agent": "solver", "tiers_version": "v1.4"},
    )

    valid_only = load_committed_episodes(tmp_path, include_invalid=False, dedupe=True)
    assert len(valid_only) == 3
    assert all(REQUIRED_EPISODE_KEYS.issubset(ep.keys()) for ep in valid_only)
    assert all("superseded" not in Path(ep["source_path"]).parts for ep in valid_only)
    expected_is_abs = not tmp_path.resolve().is_relative_to(ROOT.resolve())
    assert all(Path(ep["source_path"]).is_absolute() is expected_is_abs for ep in valid_only)

    gemini_eps = [ep for ep in valid_only if ep["agent"] == "gemini:gemini-4-carbon"]
    assert len(gemini_eps) == 1
    gem = gemini_eps[0]
    assert gem["seed"] == 0
    assert gem["score"] == pytest.approx(0.72)
    assert gem["episode_id"] == "v1.4__medium__s0__gemini_gemini-4-carbon"
    assert gem["provenance"] == {
        "kind": "real",
        "label": "REAL gemini-4-carbon",
        "model_id": "gemini-4-carbon",
    }

    with_invalid = load_committed_episodes(tmp_path, include_invalid=True, dedupe=True)
    assert len(with_invalid) == 4
    inv = [ep for ep in with_invalid if not ep["valid"]]
    assert len(inv) == 1
    assert inv[0]["seed"] == 1
    assert inv[0]["agent"] == "gemini:gemini-4-carbon"

    pairs = pair_with_solver(with_invalid)
    assert len(pairs) == 1
    pair = pairs[0]
    assert pair["pair_id"] == "v1.4__medium__s0__gemini_gemini-4-carbon__vs__solver"
    assert pair["tiers_version"] == "v1.4"
    assert pair["tier"] == "medium"
    assert pair["seed"] == 0
    assert pair["agent"] == "gemini:gemini-4-carbon"
    assert pair["agent_episode_id"] == "v1.4__medium__s0__gemini_gemini-4-carbon"
    assert pair["solver_episode_id"] == "v1.4__medium__s0__solver"
    assert pair["agent_score"] == pytest.approx(0.72)
    assert pair["solver_score"] == pytest.approx(0.88)
    assert pair["score_delta"] == pytest.approx(0.72 - 0.88)


def test_synthetic_dedupe_preferences(tmp_path: Path) -> None:
    _write_run(
        tmp_path / "v1.4" / "run-20261114-0100",
        [_sample_ep(tier="hard", seed=2, agent="gemini:gemini-4-carbon", score=0.40)],
        {"model": "gemini-4-carbon"},
    )
    _write_run(
        tmp_path / "v1.4" / "run-20261114-0200",
        [_sample_ep(tier="hard", seed=2, agent="gemini:gemini-4-carbon", score=0.65)],
        {"model": "gemini-4-carbon"},
    )

    _write_run(
        tmp_path / "z-legacy-folder" / "hard",
        [_sample_ep(tier="hard", seed=3, agent="openai:gpt-5.5", score=0.25)],
        {"model": "gpt-5.5"},
    )
    _write_run(
        tmp_path / "v1.2" / "a-explicit-folder" / "hard",
        [_sample_ep(tier="hard", seed=3, agent="openai:gpt-5.5", score=0.55)],
        {"model": "gpt-5.5"},
    )

    _write_run(
        tmp_path / "v1.4" / "attempt-1",
        [_sample_ep(tier="hard", seed=4, agent="gemini:gemini-4-carbon", score=0.70, meta={"valid": True})],
        {"model": "gemini-4-carbon"},
    )
    _write_run(
        tmp_path / "v1.4" / "attempt-2",
        [_sample_ep(tier="hard", seed=4, agent="gemini:gemini-4-carbon", score=0.0, correct=False, meta={"valid": False})],
        {"model": "gemini-4-carbon"},
    )

    deduped = load_committed_episodes(tmp_path, include_invalid=True, dedupe=True)
    by_key = {(ep["tiers_version"], ep["tier"], ep["seed"], ep["agent"]): ep for ep in deduped}

    assert len(deduped) == 3
    assert by_key[("v1.4", "hard", 2, "gemini:gemini-4-carbon")]["score"] == pytest.approx(0.65)
    assert by_key[("v1.2", "hard", 3, "openai:gpt-5.5")]["score"] == pytest.approx(0.55)
    assert by_key[("v1.4", "hard", 4, "gemini:gemini-4-carbon")]["score"] == pytest.approx(0.70)
    assert by_key[("v1.4", "hard", 4, "gemini:gemini-4-carbon")]["valid"] is True

    raw_all = load_committed_episodes(tmp_path, include_invalid=True, dedupe=False)
    assert len(raw_all) == 6
    sort_keys = [(ep["tiers_version"], ep["tier"], ep["seed"], ep["agent"]) for ep in raw_all]
    assert sort_keys == sorted(sort_keys)


def test_real_committed_episodes_and_pairing() -> None:
    all_with_invalid = load_committed_episodes(include_invalid=True)
    episodes = [ep for ep in all_with_invalid if ep["valid"]]
    assert len(episodes) > 0
    assert len(all_with_invalid) > len(episodes)
    assert any(not ep["valid"] for ep in all_with_invalid)

    v14_valid = load_committed_episodes(ROOT / "data/runs/committed/v1.4")
    assert len(v14_valid) > 0
    assert all(ep["valid"] is True for ep in v14_valid)

    for ep in episodes:
        assert REQUIRED_EPISODE_KEYS.issubset(ep.keys())
        assert ep["valid"] is True
        assert "superseded" not in Path(ep["source_path"]).parts
        assert ep["source_path"].startswith("data/runs/committed/")

    keys = [(ep["tiers_version"], ep["tier"], ep["seed"], ep["agent"]) for ep in episodes]
    assert keys == sorted(keys)
    assert len(keys) == len(set(keys))

    versions = {ep["tiers_version"] for ep in episodes}
    assert {"v1.2", "v1.3", "v1.4"}.issubset(versions)

    by_agent: dict[str, list[dict]] = {}
    for ep in episodes:
        by_agent.setdefault(ep["agent"], []).append(ep)

    for real_agent in ("codex:gpt-5.5", "openai:gpt-5.5", "grok"):
        assert real_agent in by_agent
        for ep in by_agent[real_agent]:
            assert ep["provenance"]["kind"] == "real"
            assert ep["provenance"]["label"].startswith("REAL ")

    for scripted_agent in ("solver", "heuristic"):
        assert scripted_agent in by_agent
        for ep in by_agent[scripted_agent]:
            assert ep["provenance"] == {
                "kind": "scripted",
                "label": "SCRIPTED",
                "model_id": scripted_agent,
            }

    pairs = pair_with_solver(episodes)
    assert len(pairs) > 0
    for pair in pairs:
        assert pair["agent"] != "solver"
        assert pair["agent_episode"]["valid"] is True
        assert pair["solver_episode"]["valid"] is True
        assert pair["agent_episode"]["tiers_version"] == pair["solver_episode"]["tiers_version"] == pair["tiers_version"]
        assert pair["agent_episode"]["tier"] == pair["solver_episode"]["tier"] == pair["tier"]
        assert pair["agent_episode"]["seed"] == pair["solver_episode"]["seed"] == pair["seed"]
        assert pair["pair_id"] == f"{pair['agent_episode_id']}__vs__solver"
        assert pair["score_delta"] == pytest.approx(pair["agent_score"] - pair["solver_score"])

    v13_codex_medium = [
        p for p in pairs
        if p["tiers_version"] == "v1.3" and p["agent"] == "codex:gpt-5.5" and p["tier"] == "medium"
    ]
    v13_codex_hard = [
        p for p in pairs
        if p["tiers_version"] == "v1.3" and p["agent"] == "codex:gpt-5.5" and p["tier"] == "hard"
    ]
    assert [p["seed"] for p in v13_codex_medium] == list(range(11))
    assert [p["seed"] for p in v13_codex_hard] == list(range(11))
