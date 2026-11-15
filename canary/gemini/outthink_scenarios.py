from __future__ import annotations

import argparse
import functools
import json
import subprocess
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

from canary.gemini.ladder_report import (
    LEVEL_ORDER,
    MODEL_ORDER,
    TIERS,
    load_ladder,
    reference_episodes,
)
from canary.world import HELDOUT_SEEDS, JUDGE_SEEDS

ROOT = Path(__file__).resolve().parents[2]
ANNOTATIONS_JSON = ROOT / "results" / "gemini" / "outthink_annotations.json"
LADDER_EPISODES_GZ = ROOT / "results" / "gemini" / "ladder_episodes.jsonl.gz"
OUTTHINK_PLAYABLE_JSON = ROOT / "results" / "gemini" / "out_think_gemini.json"
DEFAULT_JSON_OUT = ROOT / "results" / "gemini" / "outthink_scenarios.json"

LADDER_LEVELS: tuple[str, ...] = ("minimal", "low", "medium", "high", "xhigh")
HIGHLIGHT_TAGS: tuple[str, ...] = (
    "premature_accusation",
    "uninformative_canary",
    "ignored_delay",
    "over_restriction",
)
UNICODE_DASHES = "".join(chr(c) for c in (0x2012, 0x2013, 0x2014, 0x2015))
MAX_JSON_BYTES = 250_000

PLAYABLE_12_PAIRS: frozenset[tuple[str, int]] = frozenset(
    {
        ("hard", 1),
        ("hard", 3),
        ("hard", 4),
        ("hard", 7),
        ("hard", 18),
        ("medium", 1),
        ("medium", 2),
        ("medium", 4),
        ("medium", 6),
        ("medium", 8),
        ("medium", 9),
    }
)


def _has_unicode_dash(text: str) -> bool:
    if any(ch in text for ch in UNICODE_DASHES):
        return True
    lower = text.lower()
    for code in (0x2012, 0x2013, 0x2014, 0x2015):
        if ("\\u" + f"{code:04x}") in lower:
            return True
    return False


def _resolve_git_sha(annotations_doc: dict[str, Any]) -> str:
    sha = str(annotations_doc.get("generated_from_git_sha") or "").strip()
    if len(sha) == 40 and all(c in "0123456789abcdef" for c in sha):
        return sha
    out = subprocess.check_output(
        [
            "git",
            "log",
            "-1",
            "--format=%H",
            "--",
            "results/gemini/ladder_episodes.jsonl.gz",
            "data/runs/committed/v1.4/reference",
        ],
        cwd=ROOT,
        text=True,
    ).strip()
    if out:
        return out
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        text=True,
    ).strip()


def load_playable_pairs(playable_json: Path = OUTTHINK_PLAYABLE_JSON) -> set[tuple[str, int]]:
    if playable_json.is_file():
        doc = json.loads(playable_json.read_text(encoding="utf-8"))
        cases = doc.get("cases") or []
        if isinstance(cases, list) and cases:
            return {(str(c["tier"]), int(c["seed"])) for c in cases if "tier" in c and "seed" in c}
    return set(PLAYABLE_12_PAIRS)


def _model_rank(model: str) -> tuple[int, str]:
    return (MODEL_ORDER.index(model) if model in MODEL_ORDER else 99, model)


def _level_rank(level: str) -> tuple[int, str]:
    return (LEVEL_ORDER.index(level) if level in LEVEL_ORDER else 99, level)


def _compact_anchor(ep: dict[str, Any]) -> dict[str, Any]:
    return {
        "run_id": str(ep["run_id"]),
        "key": str(ep["key"]),
        "model": str(ep["model"]),
        "level": str(ep["level"]),
        "score": float(ep["score"]),
        "correct": bool(ep["correct"]),
        "primary_failure_tag": ep.get("primary_failure_tag"),
    }


def _select_anchor_runs(scenario_eps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    candidates = [e for e in scenario_eps if e.get("run_id")]
    if not candidates:
        return []

    chosen: list[dict[str, Any]] = []
    used_run_ids: set[str] = set()

    def _pick(pool: list[dict[str, Any]], sort_key: Any) -> None:
        avail = [e for e in pool if str(e["run_id"]) not in used_run_ids]
        if not avail or len(chosen) >= 3:
            return
        best = sorted(avail, key=sort_key)[0]
        used_run_ids.add(str(best["run_id"]))
        chosen.append(best)

    low_failures = [
        e
        for e in candidates
        if e.get("level") in ("minimal", "low")
        and (
            not e.get("correct")
            or e.get("primary_failure_tag") in HIGHLIGHT_TAGS
        )
    ]
    _pick(
        low_failures or [e for e in candidates if e.get("level") in ("minimal", "low")],
        lambda e: (
            0 if e.get("primary_failure_tag") in ("premature_accusation", "ignored_delay") else 1,
            0 if not e.get("correct") else 1,
            float(e.get("score") or 0.0),
            _level_rank(str(e.get("level") or "")),
            _model_rank(str(e.get("model") or "")),
        ),
    )

    high_wins = [
        e
        for e in candidates
        if e.get("level") in ("high", "xhigh") and bool(e.get("correct"))
    ]
    _pick(
        high_wins or [e for e in candidates if e.get("level") in ("high", "xhigh")],
        lambda e: (
            0 if bool(e.get("correct")) else 1,
            0 if e.get("model") == "gemini-4-carbon" else 1,
            -float(e.get("score") or 0.0),
            -_level_rank(str(e.get("level") or ""))[0],
            _model_rank(str(e.get("model") or "")),
        ),
    )

    mid_or_rest = [e for e in candidates if e.get("level") == "medium"] or candidates
    _pick(
        mid_or_rest,
        lambda e: (
            0 if e.get("model") == "gemini-4-carbon" else 1,
            0 if e.get("primary_failure_tag") in HIGHLIGHT_TAGS else 1,
            -abs(float(e.get("score") or 0.0)),
            _level_rank(str(e.get("level") or "")),
            _model_rank(str(e.get("model") or "")),
        ),
    )

    while len(chosen) < min(3, len(candidates)):
        _pick(
            candidates,
            lambda e: (
                _level_rank(str(e.get("level") or "")),
                _model_rank(str(e.get("model") or "")),
            ),
        )

    chosen.sort(
        key=lambda e: (
            _level_rank(str(e.get("level") or "")),
            _model_rank(str(e.get("model") or "")),
            str(e.get("run_id") or ""),
        )
    )
    return [_compact_anchor(e) for e in chosen[:3]]


@functools.lru_cache(maxsize=4)
def _cached_ladder_cells(resolved_gz: str, mtime_ns: int) -> tuple[tuple[str, float], ...]:
    _ = mtime_ns
    loaded = load_ladder(Path(resolved_gz))
    out: list[tuple[str, float]] = []
    for lad_ep in loaded:
        cell = lad_ep["_cell"]
        ep_key = f"{cell['model']}/{cell['level']}/{cell['tier']}/{cell['seed']}"
        out.append((ep_key, float(lad_ep["score"])))
    return tuple(out)


@functools.lru_cache(maxsize=4)
def _cached_ref_solver_scores(pairs_key: tuple[tuple[str, int], ...]) -> dict[tuple[str, int], float]:
    ref_eps = reference_episodes(set(pairs_key), agents=("solver",))
    return {(str(e["tier"]), int(e["seed"])): float(e["score"]) for e in ref_eps}


def build_scenarios(
    annotations_path: Path = ANNOTATIONS_JSON,
    ladder_gz_path: Path = LADDER_EPISODES_GZ,
    playable_json_path: Path = OUTTHINK_PLAYABLE_JSON,
) -> dict[str, Any]:
    annotations_doc = json.loads(annotations_path.read_text(encoding="utf-8"))
    episodes_map: dict[str, dict[str, Any]] = annotations_doc["episodes"]
    by_scenario_raw: dict[str, dict[str, dict[str, str]]] = annotations_doc["by_scenario"]

    gz_resolved = ladder_gz_path.resolve()
    ladder_cells = _cached_ladder_cells(str(gz_resolved), gz_resolved.stat().st_mtime_ns)
    assert len(ladder_cells) == 550
    for ep_key, lad_score in ladder_cells:
        assert ep_key in episodes_map, f"missing ladder episode {ep_key}"
        assert abs(float(episodes_map[ep_key]["score"]) - lad_score) < 1e-12

    scenario_pairs: set[tuple[str, int]] = set()
    for raw_sk in by_scenario_raw:
        tier_s, seed_s = raw_sk.split("/")
        seed_i = int(seed_s)
        assert seed_i not in JUDGE_SEEDS and seed_i not in HELDOUT_SEEDS
        scenario_pairs.add((tier_s, seed_i))

    ref_solver_scores = _cached_ref_solver_scores(tuple(sorted(scenario_pairs)))
    assert len(ref_solver_scores) == len(scenario_pairs)

    playable_pairs = load_playable_pairs(playable_json_path)

    ordered_raw_keys = sorted(
        by_scenario_raw.keys(),
        key=lambda sk: (
            TIERS.index(sk.split("/")[0]) if sk.split("/")[0] in TIERS else 9,
            int(sk.split("/")[1]),
        ),
    )

    scenarios_out: dict[str, dict[str, Any]] = {}
    ranking_metrics: dict[str, tuple[Any, ...]] = {}
    tag_totals: dict[str, int] = {tg: 0 for tg in HIGHLIGHT_TAGS}
    ladder_ep_total = 0

    for raw_sk in ordered_raw_keys:
        tier, seed_s = raw_sk.split("/")
        seed = int(seed_s)
        scen_key = f"{tier}:{seed}"
        model_dict = by_scenario_raw[raw_sk]

        scen_eps: list[dict[str, Any]] = []
        for m_name in sorted(model_dict.keys(), key=_model_rank):
            lv_dict = model_dict[m_name]
            for lv_name in sorted(lv_dict.keys(), key=_level_rank):
                ep_key = lv_dict[lv_name]
                scen_eps.append(episodes_map[ep_key])

        solver_score = round(ref_solver_scores[(tier, seed)], 6)
        for ep in scen_eps:
            assert abs(float(ep["solver_score"]) - solver_score) < 1e-9

        models_present = sorted({str(e["model"]) for e in scen_eps}, key=_model_rank)

        eps_by_level: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for ep in scen_eps:
            lv = str(ep["level"])
            if lv in LADDER_LEVELS:
                eps_by_level[lv].append(ep)
                ladder_ep_total += 1

        accuracy_by_level: dict[str, float] = {}
        mean_score_by_level: dict[str, float] = {}
        mean_regret_by_level: dict[str, float] = {}

        for lv in LADDER_LEVELS:
            lv_eps = eps_by_level.get(lv)
            if not lv_eps:
                continue
            n_lv = len(lv_eps)
            accuracy_by_level[lv] = round(
                sum(1.0 if bool(e["correct"]) else 0.0 for e in lv_eps) / n_lv,
                6,
            )
            mean_score_by_level[lv] = round(
                sum(float(e["score"]) for e in lv_eps) / n_lv,
                6,
            )
            mean_regret_by_level[lv] = round(
                sum(float(e["regret_total"]) for e in lv_eps) / n_lv,
                6,
            )

        level_scores = list(mean_score_by_level.values())
        ladder_spread = (
            round(max(level_scores) - min(level_scores), 6)
            if len(level_scores) >= 2
            else 0.0
        )

        dom_tags: dict[str, int] = {}
        for tg in HIGHLIGHT_TAGS:
            cnt = sum(
                1
                for e in scen_eps
                if bool(((e.get("highlighted_tags") or {}).get(tg) or {}).get("present"))
            )
            dom_tags[tg] = cnt
            tag_totals[tg] += cnt

        low_failure_hit = any(
            str(e["level"]) in ("minimal", "low")
            and float(e["score"]) <= -1.0
            and e.get("primary_failure_tag") in ("premature_accusation", "ignored_delay")
            for e in scen_eps
        )
        high_success_hit = any(
            str(e["level"]) in ("high", "xhigh")
            and bool(e["correct"])
            and float(e["score"]) > 0.0
            for e in scen_eps
        )
        low_means = [mean_score_by_level[lv] for lv in ("minimal", "low") if lv in mean_score_by_level]
        high_means = [mean_score_by_level[lv] for lv in ("high", "xhigh") if lv in mean_score_by_level]
        high_vs_low_gain = (
            round(max(high_means) - min(low_means), 6)
            if (low_means and high_means)
            else 0.0
        )
        decision_contrast = bool(
            low_failure_hit
            and (high_success_hit or solver_score > 0.0)
            and high_vs_low_gain > 0.0
        )

        anchors = _select_anchor_runs(scen_eps)

        scenarios_out[scen_key] = {
            "key": scen_key,
            "tier": tier,
            "seed": seed,
            "in_playable_12": (tier, seed) in playable_pairs,
            "solver_score": solver_score,
            "episode_count": len(scen_eps),
            "models_present": models_present,
            "accuracy_by_level": accuracy_by_level,
            "mean_score_by_level": mean_score_by_level,
            "mean_regret_by_level": mean_regret_by_level,
            "ladder_spread": ladder_spread,
            "decision_contrast": decision_contrast,
            "dominant_failure_tags": dom_tags,
            "anchor_runs": anchors,
        }

        ranking_metrics[scen_key] = (
            1 if decision_contrast else 0,
            1 if high_vs_low_gain > 0.0 else 0,
            ladder_spread,
            high_vs_low_gain,
            len(mean_score_by_level),
            solver_score,
            len(scen_eps),
            1 if tier == "hard" else 0,
            -seed,
        )

    showcase_ranking = sorted(
        scenarios_out.keys(),
        key=lambda k: ranking_metrics[k],
        reverse=True,
    )
    for rank_idx, scen_key in enumerate(showcase_ranking, start=1):
        scenarios_out[scen_key]["showcase_rank"] = rank_idx

    models_summary = [
        m
        for m in MODEL_ORDER
        if any(m in s["models_present"] for s in scenarios_out.values())
    ]
    levels_summary = [
        lv
        for lv in LADDER_LEVELS
        if any(lv in s["mean_score_by_level"] for s in scenarios_out.values())
    ]

    summary = {
        "scenarios_count": len(scenarios_out),
        "tiers": [t for t in TIERS if any(s["tier"] == t for s in scenarios_out.values())],
        "total_episodes": sum(s["episode_count"] for s in scenarios_out.values()),
        "ladder_episodes": ladder_ep_total,
        "playable_12_scenarios_count": sum(1 for s in scenarios_out.values() if s["in_playable_12"]),
        "decision_contrast_count": sum(1 for s in scenarios_out.values() if s["decision_contrast"]),
        "models": models_summary,
        "levels": levels_summary,
        "dominant_failure_tag_totals": tag_totals,
        "best_showcase_scenarios": showcase_ranking[:12],
    }

    return {
        "generated_from_git_sha": _resolve_git_sha(annotations_doc),
        "summary": summary,
        "scenarios": scenarios_out,
        "showcase_ranking": showcase_ranking,
    }


def validate_scenarios(
    doc: dict[str, Any],
    annotations_doc: dict[str, Any] | None = None,
) -> list[str]:
    errors: list[str] = []
    for top_key in ("generated_from_git_sha", "summary", "scenarios", "showcase_ranking"):
        if top_key not in doc:
            errors.append(f"missing top-level key {top_key}")
    if errors:
        return errors

    sha = doc.get("generated_from_git_sha")
    if not isinstance(sha, str) or len(sha) != 40:
        errors.append("generated_from_git_sha must be a 40-char hex string")

    summary = doc.get("summary") or {}
    scenarios = doc.get("scenarios") or {}
    ranking = doc.get("showcase_ranking") or []

    for sum_key in (
        "scenarios_count",
        "tiers",
        "total_episodes",
        "models",
        "levels",
        "best_showcase_scenarios",
    ):
        if sum_key not in summary:
            errors.append(f"summary missing {sum_key}")

    if summary.get("scenarios_count") != 62 or len(scenarios) != 62:
        errors.append(f"expected 62 scenarios, got {len(scenarios)}")
    if summary.get("total_episodes") != 587:
        errors.append(f"expected 587 total_episodes, got {summary.get('total_episodes')}")
    if len(ranking) != len(scenarios) or set(ranking) != set(scenarios.keys()):
        errors.append("showcase_ranking must be a permutation of scenarios keys")

    best_list = summary.get("best_showcase_scenarios") or []
    if not isinstance(best_list, list) or best_list != ranking[: len(best_list)] or not best_list:
        errors.append("best_showcase_scenarios must be a non-empty prefix of showcase_ranking")

    ann_eps = (annotations_doc or {}).get("episodes") or {}
    run_id_index = {
        str(ep["run_id"]): ep
        for ep in ann_eps.values()
        if ep.get("run_id")
    }

    ep_sum = 0
    for sk, sc in scenarios.items():
        for req in (
            "key",
            "tier",
            "seed",
            "in_playable_12",
            "solver_score",
            "episode_count",
            "models_present",
            "accuracy_by_level",
            "mean_score_by_level",
            "mean_regret_by_level",
            "ladder_spread",
            "dominant_failure_tags",
            "anchor_runs",
        ):
            if req not in sc:
                errors.append(f"{sk}: missing {req}")
        if sc.get("key") != sk:
            errors.append(f"{sk}: key mismatch {sc.get('key')}")
        expected_sk = f"{sc.get('tier')}:{sc.get('seed')}"
        if expected_sk != sk:
            errors.append(f"{sk}: tier/seed mismatch {expected_sk}")
        seed_val = int(sc.get("seed", -1))
        if seed_val in JUDGE_SEEDS or seed_val in HELDOUT_SEEDS:
            errors.append(f"{sk}: forbidden seed {seed_val}")
        if not isinstance(sc.get("in_playable_12"), bool):
            errors.append(f"{sk}: in_playable_12 must be bool")

        ep_sum += int(sc.get("episode_count") or 0)

        acc_lv = sc.get("accuracy_by_level") or {}
        msc_lv = sc.get("mean_score_by_level") or {}
        mrg_lv = sc.get("mean_regret_by_level") or {}
        if list(acc_lv.keys()) != list(msc_lv.keys()) or list(acc_lv.keys()) != list(mrg_lv.keys()):
            errors.append(f"{sk}: level metric keys mismatch")
        if not acc_lv or any(lv not in LADDER_LEVELS for lv in acc_lv):
            errors.append(f"{sk}: invalid ladder levels {list(acc_lv.keys())}")

        vals = list(msc_lv.values())
        exp_spread = round(max(vals) - min(vals), 6) if len(vals) >= 2 else 0.0
        if abs(float(sc.get("ladder_spread") or 0.0) - exp_spread) > 1e-6:
            errors.append(f"{sk}: ladder_spread {sc.get('ladder_spread')} != {exp_spread}")

        dom = sc.get("dominant_failure_tags") or {}
        if tuple(dom.keys()) != HIGHLIGHT_TAGS:
            errors.append(f"{sk}: dominant_failure_tags keys mismatch")

        anchors = sc.get("anchor_runs") or []
        if not (1 <= len(anchors) <= 3):
            errors.append(f"{sk}: anchor_runs count {len(anchors)} outside 1..3")
        seen_rids: set[str] = set()
        for ar in anchors:
            rid = ar.get("run_id")
            if not rid or rid in seen_rids:
                errors.append(f"{sk}: invalid or duplicate anchor run_id {rid}")
            seen_rids.add(str(rid))
            if run_id_index:
                ref_ep = run_id_index.get(str(rid))
                if ref_ep is None:
                    errors.append(f"{sk}: anchor run_id {rid} not in outthink_annotations.json")
                else:
                    for fld in ("model", "level", "score", "correct", "primary_failure_tag"):
                        if ar.get(fld) != ref_ep.get(fld):
                            errors.append(f"{sk}: anchor {rid} field {fld} mismatch")

    if ep_sum != summary.get("total_episodes"):
        errors.append(f"scenario episode_count sum {ep_sum} != {summary.get('total_episodes')}")

    if annotations_doc is not None:
        ann_sum = annotations_doc.get("summary") or {}
        exp_tags = ann_sum.get("highlighted_tag_episode_counts") or {}
        for tg in HIGHLIGHT_TAGS:
            got_tg = sum(int(s["dominant_failure_tags"][tg]) for s in scenarios.values())
            if got_tg != int(exp_tags.get(tg, -1)):
                errors.append(f"tag {tg} sum {got_tg} != annotations {exp_tags.get(tg)}")

    return errors


def render_json_text(doc: dict[str, Any]) -> str:
    return json.dumps(doc, indent=1, ensure_ascii=True) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m canary.gemini.outthink_scenarios")
    parser.add_argument("--json-out", type=Path, default=DEFAULT_JSON_OUT)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)

    annotations_doc = json.loads(ANNOTATIONS_JSON.read_text(encoding="utf-8"))
    doc = build_scenarios()
    errors = validate_scenarios(doc, annotations_doc=annotations_doc)
    if errors:
        for err in errors:
            sys.stderr.write(f"ERROR: {err}\n")
        return 1

    json_text = render_json_text(doc)
    if _has_unicode_dash(json_text):
        sys.stderr.write("ERROR: unicode dash detected in outthink_scenarios JSON\n")
        return 1

    json_bytes = len(json_text.encode("utf-8"))
    if json_bytes >= MAX_JSON_BYTES:
        sys.stderr.write(f"ERROR: JSON size {json_bytes} exceeds {MAX_JSON_BYTES} bytes\n")
        return 1

    if args.check:
        if not args.json_out.is_file():
            sys.stderr.write(f"ERROR: missing {args.json_out}\n")
            return 1
        on_disk = args.json_out.read_text(encoding="utf-8")
        if on_disk != json_text:
            sys.stderr.write(f"ERROR: {args.json_out} does not match deterministic build\n")
            return 1
        s = doc["summary"]
        sys.stdout.write(
            f"OK: {s['scenarios_count']} scenarios, {s['total_episodes']} episodes, "
            f"{json_bytes} bytes verified.\n"
        )
        return 0

    args.json_out.parent.mkdir(parents=True, exist_ok=True)
    args.json_out.write_text(json_text, encoding="utf-8")
    s = doc["summary"]
    sys.stdout.write(
        f"outthink_scenarios: {s['scenarios_count']} scenarios, {s['total_episodes']} episodes, "
        f"{json_bytes} bytes -> {args.json_out}\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
