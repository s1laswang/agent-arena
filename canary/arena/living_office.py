from __future__ import annotations

from collections import Counter
import copy
import json
from pathlib import Path
import re
from typing import Any

from canary.env import TOPICS, Env
from canary.eval import run_episode
from canary.forge.frontier_proxies import GeminiCarbonProxy
from canary.mole.dsl import DEFAULT_STRATEGY, MoleStrategy
from canary.mole.strategies import TRANSCRIPT_STRATEGIES, get_strategy, list_strategy_names
from canary.rules import HELDOUT_SEEDS, JUDGE_SEEDS, TRACKS, tier_params
from canary.social.biases import BIAS_TYPES, DECOY_VOCAB
from canary.social.engine import EpisodeSocialState, V16SocialProvider, make_v16_provider
from canary.social.variants import VARIANTS
from canary.social_audit import verify_and_score_episodes
from canary.solver.policy import SolverPolicy
from canary.text.template import TemplateProvider
from canary.types import INVESTIGATIVE_TOOLS, EpisodeResult, Step

__all__ = [
    "BIAS_TYPES",
    "BiasGulliblePolicy",
    "GATE_B_DISCLOSURE",
    "GATE_B_METRICS",
    "KEY_VARIANTS",
    "LivingOfficeSession",
    "PROVENANCE_BADGES",
    "V16SocialProvider",
    "VARIANTS",
    "list_living_office_variants",
    "list_mole_opponents",
    "list_v16_checkpoint_replays",
    "load_v16_checkpoint_replay",
    "make_v16_provider",
    "verify_and_score_episodes",
]

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
PARTIAL_RUNS_DIR = ROOT_DIR / "results" / "v16_social" / "partial"

PROVENANCE_BADGES: tuple[str, ...] = (
    "v16-real-gemini-replay",
    "v16-template-live",
    "v14-control",
)

GATE_B_METRICS: dict[str, Any] = {
    "status": "documented_negative_result_opt_in_showcase",
    "gate_met": False,
    "headline_variant": "v5_full9_cocktail",
    "control_variant": "v0_v14_control",
    "tier": "hard",
    "n_paired": 3,
    "paired_seeds": [30, 31, 32],
    "variant_luck_adjusted_mean": 0.452,
    "control_luck_adjusted_mean": 0.493,
    "delta_luck_adjusted": -0.041,
    "variant_raw_mean": 0.617,
    "control_raw_mean": 0.523,
    "delta_raw": 0.093,
}

GATE_B_DISCLOSURE: str = (
    "Opt-in V1.6 Living Office showcase: live Gate B check on hard seeds 30..32 was a "
    "documented negative result (v5_full9_cocktail n=3 luck-adjusted 0.452 vs control 0.493, "
    "delta -0.041; raw 0.617 vs 0.523, delta +0.093)."
)

KEY_VARIANTS: tuple[str, ...] = (
    "v5_full9_cocktail",
    "v1_anchoring_authority_confirmation",
    "v2_recency_bandwagon_sycophancy",
    "v3_grudge_falsemem_misforward",
    "v4_triad_authority_recency_grudge",
    "v0_v14_control",
)

_VARIANT_META: dict[str, tuple[str, str]] = {
    "v5_full9_cocktail": (
        "V5 Full 9-Bias Cocktail",
        "All 9 cognitive and organizational biases interleaved across an 18-day rumor cascade.",
    ),
    "v1_anchoring_authority_confirmation": (
        "V1 Anchoring + Authority + Confirmation",
        "Early Day 1-2 anchoring reinforced by senior leadership notes and confirmation follow-ups.",
    ),
    "v2_recency_bandwagon_sycophancy": (
        "V2 Recency + Bandwagon + Sycophancy",
        "Cross-team bandwagon consensus, sycophantic echoing of seniors, and late urgent recency alerts.",
    ),
    "v3_grudge_falsemem_misforward": (
        "V3 Grudge + False Memory + Misforward",
        "Interpersonal feuds, misremembered document threads, and accidental restricted-draft forwards.",
    ),
    "v4_triad_authority_recency_grudge": (
        "V4 Triad: Authority + Recency + Grudge",
        "Senior authority signals combined with escalating department grudges and late recency pressure.",
    ),
    "v0_v14_control": (
        "V0 Control (V1.4 Template)",
        "Baseline V1.4 deterministic template office messages with zero synthetic cognitive-bias chatter.",
    ),
}

FLOORPLAN_DEPARTMENTS: tuple[dict[str, Any], ...] = (
    {"id": "Engineering", "name": "Engineering", "grid_x": 1, "grid_y": 1, "grid_w": 11, "grid_h": 10, "zone_type": "department"},
    {"id": "Finance", "name": "Finance", "grid_x": 13, "grid_y": 1, "grid_w": 11, "grid_h": 10, "zone_type": "department"},
    {"id": "Sales", "name": "Sales", "grid_x": 25, "grid_y": 1, "grid_w": 10, "grid_h": 10, "zone_type": "department"},
    {"id": "Legal", "name": "Legal", "grid_x": 1, "grid_y": 13, "grid_w": 11, "grid_h": 10, "zone_type": "department"},
    {"id": "Research", "name": "Research", "grid_x": 13, "grid_y": 13, "grid_w": 11, "grid_h": 10, "zone_type": "department"},
    {"id": "Security Console", "name": "Security Console", "grid_x": 25, "grid_y": 13, "grid_w": 10, "grid_h": 10, "zone_type": "console"},
)

_DEPT_ZONE_BY_NAME: dict[str, dict[str, Any]] = {z["id"]: z for z in FLOORPLAN_DEPARTMENTS}
_EMP_ID_RE = re.compile(r"\be\d\d\b")

_PARTIAL_CACHE: dict[tuple[str, int], tuple[dict[str, Any], str]] | None = None
_REPLAY_PAYLOAD_CACHE: dict[tuple[str, int], dict[str, Any]] = {}
_SOLVER_TPL_CACHE: dict[tuple[str, int, str], tuple[EpisodeResult, list[dict[str, Any]]]] = {}


def _validate_strict_int(value: Any, label: str = "seed") -> int:
    if isinstance(value, bool) or isinstance(value, float):
        raise ValueError(f"{label} must be a strict integer, got {value!r}")
    if isinstance(value, int):
        return int(value)
    if isinstance(value, str):
        stripped = value.strip()
        if stripped and (stripped.isdigit() or (stripped.startswith("-") and stripped[1:].isdigit())):
            return int(stripped)
    raise ValueError(f"{label} must be a strict integer, got {value!r}")


def _validate_live_seed(seed: Any) -> int:
    parsed = _validate_strict_int(seed, "seed")
    if parsed in HELDOUT_SEEDS or parsed in JUDGE_SEEDS:
        raise ValueError(f"seed {parsed} is reserved for held-out or judge evaluation")
    if not (3000 <= parsed <= 9999):
        raise ValueError(f"interactive LivingOfficeSession requires 3000 <= seed <= 9999, got {parsed}")
    return parsed


def _validate_checkpoint_seed(seed: Any) -> int:
    parsed = _validate_strict_int(seed, "seed")
    if not (30 <= parsed <= 33):
        raise ValueError(f"checkpoint replay requires committed partial seed in 30..33, got {parsed}")
    return parsed


def _resolve_mole_opponent(mole_opponent: str | dict[str, Any] | MoleStrategy | None, seed: int) -> tuple[str, Any]:
    if mole_opponent is None or mole_opponent in ("", "default", DEFAULT_STRATEGY.name):
        return DEFAULT_STRATEGY.name, None
    if isinstance(mole_opponent, MoleStrategy):
        return mole_opponent.name, mole_opponent
    if isinstance(mole_opponent, dict):
        strat = MoleStrategy.from_json(mole_opponent)
        return strat.name, strat
    if isinstance(mole_opponent, str):
        clean = mole_opponent.strip()
        if clean in ("default", DEFAULT_STRATEGY.name):
            return DEFAULT_STRATEGY.name, None
        if clean in TRANSCRIPT_STRATEGIES:
            strat = get_strategy(clean)
            return strat.name, strat
        if clean in TRACKS:
            from canary.forge_track import strategy_for
            strat = strategy_for(clean, seed)
            return clean, strat
    raise ValueError(f"unknown mole_opponent {mole_opponent!r}")


def list_mole_opponents() -> list[str]:
    return [DEFAULT_STRATEGY.name, *list_strategy_names(include_default=False)]


def _load_partial_index() -> dict[tuple[str, int], tuple[dict[str, Any], str]]:
    global _PARTIAL_CACHE
    if _PARTIAL_CACHE is not None:
        return _PARTIAL_CACHE
    out: dict[tuple[str, int], tuple[dict[str, Any], str]] = {}
    if PARTIAL_RUNS_DIR.exists():
        for variant_dir in sorted(PARTIAL_RUNS_DIR.iterdir()):
            if not variant_dir.is_dir():
                continue
            variant = variant_dir.name
            if variant not in VARIANTS:
                continue
            ep_file = variant_dir / "hard" / "episodes.jsonl"
            if not ep_file.exists():
                continue
            rel = str(ep_file.relative_to(ROOT_DIR))
            for raw_line in ep_file.read_text(encoding="utf-8").splitlines():
                line = raw_line.strip()
                if not line:
                    continue
                ep = json.loads(line)
                if ep.get("valid") is False:
                    continue
                meta = ep.get("meta")
                if isinstance(meta, dict) and meta.get("valid") is False:
                    continue
                seed = int(ep["seed"])
                if 30 <= seed <= 33:
                    out[(variant, seed)] = (ep, rel)
    _PARTIAL_CACHE = out
    return out


def list_living_office_variants() -> list[dict[str, Any]]:
    index = _load_partial_index()
    rows: list[dict[str, Any]] = []
    for variant in KEY_VARIANTS:
        spec = VARIANTS[variant]
        control = bool(spec.get("control", False))
        title, desc = _VARIANT_META.get(variant, (variant, "V1.6 Living Office social variant."))
        ckpt_seeds = sorted(s for (v, s) in index if v == variant)
        rows.append(
            {
                "variant": variant,
                "name": variant,
                "title": title,
                "description": desc,
                "control": control,
                "biases": list(spec.get("biases", ())),
                "n_biases": len(spec.get("biases", ())),
                "scheduled_days": sorted(int(d) for d in spec.get("schedule", {}).keys()),
                "provenance_badge_live": "v14-control" if control else "v16-template-live",
                "checkpoint_seeds": ckpt_seeds,
                "n_checkpoint_episodes": len(ckpt_seeds),
                "gate_b_disclosure": GATE_B_DISCLOSURE,
            }
        )
    return rows


def list_v16_checkpoint_replays() -> list[dict[str, Any]]:
    index = _load_partial_index()
    order_rank = {v: i for i, v in enumerate(KEY_VARIANTS)}
    keys = sorted(index.keys(), key=lambda kv: (order_rank.get(kv[0], 99), kv[0], kv[1]))
    out: list[dict[str, Any]] = []
    for variant, seed in keys:
        ep, rel_path = index[(variant, seed)]
        spec = VARIANTS[variant]
        out.append(
            {
                "id": f"{variant}:hard:{seed}",
                "variant": variant,
                "tier": str(ep.get("tier") or "hard"),
                "seed": int(seed),
                "agent": str(ep.get("agent") or "gemini:gemini-4-carbon"),
                "score": float(ep["score"]),
                "accused": ep.get("accused"),
                "correct": bool(ep.get("correct")),
                "final_day": int(ep.get("final_day") or 1),
                "end_reason": str(ep.get("end_reason") or "accused"),
                "tool_calls": len(ep.get("steps") or []),
                "control": bool(spec.get("control", False)),
                "biases": list(spec.get("biases", ())),
                "provenance_badge": "v16-real-gemini-replay",
                "gate_b_disclosure": GATE_B_DISCLOSURE,
                "source_path": rel_path,
            }
        )
    return out


def _desk_coordinates(dept: str, idx_in_dept: int) -> tuple[int, int]:
    zone = _DEPT_ZONE_BY_NAME.get(dept, FLOORPLAN_DEPARTMENTS[0])
    zx = int(zone["grid_x"])
    zy = int(zone["grid_y"])
    if idx_in_dept < 16:
        col = idx_in_dept % 4
        row = idx_in_dept // 4
        return zx + 1 + col * 2, zy + 2 + row * 2
    overflow = idx_in_dept - 16
    col = overflow % 5
    row = overflow // 5
    return zx + 2 + col * 2, zy + 1 + row * 2


def _truncate(text: str, limit: int = 120) -> str:
    clean = " ".join(str(text or "").split())
    if len(clean) <= limit:
        return clean
    return clean[: max(1, limit - 3)].rstrip() + "..."


def _build_floorplan(
    employees: list[Any],
    restricted_ids: set[str],
    interviewed_today_ids: set[str],
    bubble_by_emp: dict[str, str],
    accused_id: str | None = None,
    done: bool = False,
) -> dict[str, Any]:
    dept_counts: dict[str, int] = {}
    desks: list[dict[str, Any]] = []
    for emp in employees:
        dept = str(emp.dept)
        idx = dept_counts.get(dept, 0)
        dept_counts[dept] = idx + 1
        gx, gy = _desk_coordinates(dept, idx)
        eid = str(emp.id)
        bubble = bubble_by_emp.get(eid, "")
        if done and accused_id == eid:
            status = "accused"
        elif eid in restricted_ids:
            status = "restricted"
        elif eid in interviewed_today_ids:
            status = "interviewed"
        elif bubble:
            status = "chattering"
        else:
            status = "working"
        desk: dict[str, Any] = {
            "id": eid,
            "name": str(emp.name),
            "dept": dept,
            "role": str(emp.role),
            "grid_x": gx,
            "grid_y": gy,
            "pixel_x": gx * 24,
            "pixel_y": gy * 24,
            "status": status,
            "bubble_preview": bubble,
        }
        if getattr(emp, "clearance", None) is not None:
            desk["clearance"] = int(emp.clearance)
        desks.append(desk)
    return {
        "grid_width": 36,
        "grid_height": 24,
        "tile_px": 24,
        "departments": [dict(d) for d in FLOORPLAN_DEPARTMENTS],
        "desks": desks,
    }


def _collect_public_social_feed(env: Env) -> tuple[list[dict[str, Any]], dict[str, str], set[str]]:
    by_id = {e.id: e for e in env._world.employees}
    observed_msg_ids: set[str] = set()
    observed_snippets: dict[str, dict[str, Any]] = {}
    interviews: list[dict[str, Any]] = []
    interviewed_today: set[str] = set()

    for st in env.history:
        res = st.result or {}
        if not res.get("ok"):
            continue
        data = res.get("data") or {}
        if st.tool == "search_messages":
            for m in data.get("messages") or []:
                if isinstance(m, dict) and isinstance(m.get("id"), str):
                    mid = str(m["id"])
                    observed_msg_ids.add(mid)
                    observed_snippets.setdefault(mid, dict(m))
        elif st.tool == "read_message":
            msg = data.get("message")
            if isinstance(msg, dict) and isinstance(msg.get("id"), str):
                mid = str(msg["id"])
                observed_msg_ids.add(mid)
                observed_snippets[mid] = dict(msg)
        elif st.tool == "interview":
            emp_id = str(data.get("employee") or st.args.get("employee") or "")
            topic = str(data.get("topic") or st.args.get("topic") or "")
            answer = str(data.get("answer") or "")
            if emp_id:
                if int(st.day) == int(env.day):
                    interviewed_today.add(emp_id)
                emp_obj = by_id.get(emp_id)
                interviews.append(
                    {
                        "kind": "interview",
                        "id": f"iv-{st.t}",
                        "day": int(st.day),
                        "channel": "interview",
                        "sender": emp_id,
                        "sender_name": emp_obj.name if emp_obj else emp_id,
                        "topic": topic,
                        "subject": f"Interview: {topic}",
                        "body": answer,
                        "player_observed": True,
                    }
                )

    feed: list[dict[str, Any]] = []
    bubble_by_emp: dict[str, str] = {}
    seen_ids: set[str] = set()

    for mid in env._msg_order:
        m = env._messages.get(mid)
        if not isinstance(m, dict):
            continue
        seen_ids.add(mid)
        snd = str(m.get("sender") or "")
        emp_obj = by_id.get(snd)
        body_text = str(m.get("body") or "")
        item = {
            "kind": "message",
            "id": mid,
            "day": int(m.get("day") or 1),
            "channel": str(m.get("channel") or ""),
            "sender": snd,
            "sender_name": emp_obj.name if emp_obj else snd,
            "subject": str(m.get("subject") or ""),
            "body": body_text,
            "player_observed": mid in observed_msg_ids,
        }
        feed.append(item)
        if snd:
            bubble_by_emp[snd] = _truncate(body_text, 110)

    for mid, m in observed_snippets.items():
        if mid in seen_ids:
            continue
        snd = str(m.get("sender") or "")
        emp_obj = by_id.get(snd)
        body_text = str(m.get("body") or m.get("snippet") or "")
        feed.append(
            {
                "kind": "message",
                "id": mid,
                "day": int(m.get("day") or 1),
                "channel": str(m.get("channel") or ""),
                "sender": snd,
                "sender_name": emp_obj.name if emp_obj else snd,
                "subject": str(m.get("subject") or ""),
                "body": body_text,
                "player_observed": True,
            }
        )
        if snd:
            bubble_by_emp[snd] = _truncate(body_text, 110)

    for iv in interviews:
        feed.append(iv)
        snd = str(iv["sender"])
        if snd:
            bubble_by_emp[snd] = _truncate(iv["body"], 110)

    feed.sort(key=lambda r: (int(r["day"]), 0 if r["kind"] == "message" else 1, str(r["id"])))
    return feed, bubble_by_emp, interviewed_today


def _solver_template_run(
    tier: str,
    seed: int,
    mole_opponent_key: str,
    mole_strategy: Any,
) -> tuple[EpisodeResult, list[dict[str, Any]]]:
    ckey = (tier, int(seed), mole_opponent_key)
    if ckey not in _SOLVER_TPL_CACHE:
        sp = SolverPolicy(tier if tier in ("easy", "medium", "hard") else tier_params(tier))
        env_tpl = Env(tier, seed, text_provider=TemplateProvider(), mole_strategy=mole_strategy)
        res = run_episode(env_tpl, sp)
        trace_copy = [{"day": int(row["day"]), "post": dict(row["post"])} for row in sp.trace]
        _SOLVER_TPL_CACHE[ckey] = (res, trace_copy)
    return _SOLVER_TPL_CACHE[ckey]


def _replay_steps_on_provider(
    steps: list[Step],
    tier: str,
    seed: int,
    variant: str,
    mole_strategy: Any,
) -> EpisodeResult:
    prov = make_v16_provider(variant, mode="template")
    env = Env(tier, seed, text_provider=prov, mole_strategy=mole_strategy)
    for st in steps:
        if env.done:
            break
        env.call(st.tool, dict(st.args or {}))
    return env.result("solver")


def _materialize_social_state_after_done(
    env: Env,
    provider: V16SocialProvider,
    up_to_day: int,
) -> EpisodeSocialState | None:
    if provider.variant_spec.get("control"):
        return None
    max_day = max(1, min(int(up_to_day), int(env.p.n_days)))
    for d in range(1, max_day + 1):
        provider.day_messages(env._facts(d))
    return provider.episode_state(env.tier, env._world.world_seed)


def _compute_bias_xray(
    env: Env,
    provider: V16SocialProvider,
    steps: list[Step],
    inv_score: float,
    inv_accused: str | None,
    inv_correct: bool,
    inv_final_day: int,
    mole_opponent_key: str = "default_v0",
    mole_strategy: Any = None,
) -> dict[str, Any]:
    state = _materialize_social_state_after_done(env, provider, inv_final_day)
    by_id = {e.id: e for e in env._world.employees}
    true_mole = str(env._world.mole)
    decoy_id = env._world.decoy
    active_biases = set(provider.variant_spec.get("biases", ()))

    event_by_msg_id: dict[str, dict[str, Any]] = {}
    events_by_bias: dict[str, list[dict[str, Any]]] = {b: [] for b in BIAS_TYPES}

    if state is not None:
        for d in sorted(state.events_by_day):
            if d > inv_final_day:
                continue
            day_evs = state.events_by_day[d]
            for idx, ev in enumerate(day_evs):
                b = str(ev["bias"])
                mid = f"m{d}-s{idx}"
                enriched = dict(ev, message_id=mid)
                event_by_msg_id[mid] = enriched
                if b in events_by_bias:
                    events_by_bias[b].append(enriched)

    distraction_by_bias: dict[str, int] = {b: 0 for b in BIAS_TYPES}
    for st in steps:
        res = st.result or {}
        if not res.get("ok"):
            continue
        data = res.get("data") or {}
        sday = int(st.day)
        if st.tool == "read_message":
            mid = str(st.args.get("id") or "")
            ev = event_by_msg_id.get(mid)
            if ev is not None:
                distraction_by_bias[str(ev["bias"])] += 1
        elif st.tool == "search_messages":
            seen_biases_in_call: set[str] = set()
            for m in data.get("messages") or []:
                if isinstance(m, dict):
                    ev = event_by_msg_id.get(str(m.get("id") or ""))
                    if ev is not None:
                        seen_biases_in_call.add(str(ev["bias"]))
            for b in seen_biases_in_call:
                distraction_by_bias[b] += 1
        elif st.tool in ("interview", "read_access_logs", "restrict_access", "accuse"):
            target_emp = str(st.args.get("employee") or "")
            if target_emp and target_emp != true_mole:
                for b in BIAS_TYPES:
                    if any(int(ev["day"]) <= sday and str(ev["target"]) == target_emp for ev in events_by_bias[b]):
                        distraction_by_bias[b] += 1

    bias_map: dict[str, dict[str, Any]] = {}
    for b in BIAS_TYPES:
        evs = events_by_bias[b]
        samples = [
            {
                "day": int(ev["day"]),
                "bias": b,
                "speaker": str(ev["sender"]),
                "speaker_name": str(ev.get("speaker_name") or ""),
                "target_suspect": str(ev["target"]),
                "target_name": str(ev.get("target_name") or ""),
                "channel": str(ev["channel"]),
                "subject": str(ev.get("subject") or ""),
                "excerpt": _truncate(str(ev.get("body") or ""), 160),
            }
            for ev in evs[:5]
        ]
        bias_map[b] = {
            "count": len(evs),
            "active_in_variant": b in active_biases,
            "sample_events": samples,
            "investigator_distraction_calls": int(distraction_by_bias[b]),
        }

    prim_id = state.primary_suspect if state is not None else None
    sec_id = state.secondary_suspect if state is not None else None

    focal_rumor_suspects = {
        "primary_suspect": prim_id,
        "primary_suspect_name": by_id[prim_id].name if prim_id and prim_id in by_id else None,
        "secondary_suspect": sec_id,
        "secondary_suspect_name": by_id[sec_id].name if sec_id and sec_id in by_id else None,
        "true_mole": true_mole,
        "true_mole_name": by_id[true_mole].name if true_mole in by_id else true_mole,
        "decoy": decoy_id,
        "decoy_name": by_id[decoy_id].name if decoy_id and decoy_id in by_id else None,
        "primary_is_true_mole": bool(prim_id is not None and prim_id == true_mole),
        "secondary_is_true_mole": bool(sec_id is not None and sec_id == true_mole),
        "disjoint_from_decoy": bool(
            decoy_id is None or (prim_id != decoy_id and sec_id != decoy_id)
        ),
    }

    solver_tpl, _ = _solver_template_run(env.tier, env.seed, mole_opponent_key, mole_strategy)
    solver_v16 = _replay_steps_on_provider(
        solver_tpl.steps, env.tier, env.seed, provider.variant, mole_strategy
    )

    solver_comparison = {
        "solver_score": float(solver_v16.score),
        "template_solver_score": float(solver_tpl.score),
        "score_delta": round(float(solver_v16.score) - float(solver_tpl.score), 10),
        "solver_accused": solver_v16.accused,
        "solver_correct": bool(solver_v16.correct),
        "solver_final_day": int(solver_v16.final_day),
        "bit_exact_immunity": bool(
            abs(float(solver_v16.score) - float(solver_tpl.score)) <= 1e-9
            and solver_v16.accused == solver_tpl.accused
            and int(solver_v16.final_day) == int(solver_tpl.final_day)
        ),
        "investigator_score": float(inv_score),
        "investigator_accused": inv_accused,
        "investigator_correct": bool(inv_correct),
        "investigator_final_day": int(inv_final_day),
        "score_gap_vs_solver": round(float(solver_v16.score) - float(inv_score), 6),
    }

    xray: dict[str, Any] = {
        "variant": provider.variant,
        "control": bool(provider.variant_spec.get("control", False)),
        "biases": bias_map,
        "focal_rumor_suspects": focal_rumor_suspects,
        "true_mole": true_mole,
        "decoy": decoy_id,
        "accused": inv_accused,
        "correct": bool(inv_correct),
        "accused_matches_rumor_suspect": bool(inv_accused in {prim_id, sec_id} - {None}),
        "solver_comparison": solver_comparison,
        "total_bias_events": sum(row["count"] for row in bias_map.values()),
        "total_distraction_calls": sum(row["investigator_distraction_calls"] for row in bias_map.values()),
    }
    for b, row in bias_map.items():
        xray[b] = row
    return xray


def load_v16_checkpoint_replay(variant: str = "v5_full9_cocktail", seed: int = 30) -> dict[str, Any]:
    clean_variant = str(variant or "").strip()
    if clean_variant not in VARIANTS:
        raise ValueError(f"unknown v16 variant {variant!r}")
    parsed_seed = _validate_checkpoint_seed(seed)

    cache_key = (clean_variant, parsed_seed)
    if cache_key in _REPLAY_PAYLOAD_CACHE:
        return copy.deepcopy(_REPLAY_PAYLOAD_CACHE[cache_key])

    index = _load_partial_index()
    if cache_key not in index:
        raise ValueError(
            f"no committed v16 checkpoint episode for variant={clean_variant!r} seed={parsed_seed}"
        )
    ep_dict, rel_path = index[cache_key]
    tier = str(ep_dict.get("tier") or "hard")
    agent_name = str(ep_dict.get("agent") or "gemini:gemini-4-carbon")

    prov_verify = make_v16_provider(clean_variant, mode="template")
    solver_tpl, solver_trace = _solver_template_run(tier, parsed_seed, DEFAULT_STRATEGY.name, None)
    audit = verify_and_score_episodes(
        [ep_dict],
        [solver_tpl],
        tier=tier,
        provider=prov_verify,
        strict=True,
        bootstrap_samples=200,
    )
    audit_row = dict(audit["per_seed"][0])

    prov = make_v16_provider(clean_variant, mode="template")
    env = Env(tier, parsed_seed, text_provider=prov)
    by_id = {e.id: e for e in env._world.employees}
    true_mole = str(env._world.mole)
    decoy_id = env._world.decoy

    sp_inv = SolverPolicy(tier)
    sp_inv.reset(env.tools_spec(), env.instruction())
    sp_inv.obs.employees = list(env._ids)

    steps_by_day: dict[int, list[Step]] = {}
    for raw_st in ep_dict.get("steps") or []:
        if env.done:
            break
        call_day = int(env.day)
        tool = str(raw_st["tool"])
        args = dict(raw_st.get("args") or {})
        env.call(tool, args)
        recorded_step = env.history[-1]
        steps_by_day.setdefault(call_day, []).append(recorded_step)

    replayed = env.result(agent_name)
    final_day = int(replayed.final_day)
    social_state = _materialize_social_state_after_done(env, prov, final_day)
    focal_set = (
        {social_state.primary_suspect, social_state.secondary_suspect}
        if social_state is not None
        else set()
    )

    event_by_msg_id: dict[str, dict[str, Any]] = {}
    if social_state is not None:
        for d, evs in social_state.events_by_day.items():
            for idx, ev in enumerate(evs):
                event_by_msg_id[f"m{d}-s{idx}"] = dict(ev, message_id=f"m{d}-s{idx}")

    solver_post_by_day: dict[int, dict[str, float]] = {
        int(row["day"]): dict(row["post"]) for row in solver_trace
    }
    last_solver_post: dict[str, float] = {}

    days_payload: list[dict[str, Any]] = []
    posterior_trace: list[dict[str, Any]] = []
    all_messages_read: list[dict[str, Any]] = []
    all_interviews: list[dict[str, Any]] = []
    all_rumor_bubbles: list[dict[str, Any]] = []
    restricted_running: set[str] = set()
    read_msg_ids_so_far: set[str] = set()
    bubble_running: dict[str, str] = {}

    for d in range(1, final_day + 1):
        day_steps = steps_by_day.get(d, [])
        day_interviews: list[dict[str, Any]] = []
        day_msgs_read: list[dict[str, Any]] = []
        interviewed_today: set[str] = set()

        for st in day_steps:
            sp_inv._ingest(st)
            sp_inv.seen += 1
            res = st.result or {}
            if not res.get("ok"):
                continue
            data = res.get("data") or {}
            if st.tool == "restrict_access":
                emp_r = str(st.args.get("employee") or "")
                if emp_r:
                    restricted_running.add(emp_r)
            elif st.tool == "unrestrict_access":
                emp_u = str(st.args.get("employee") or "")
                restricted_running.discard(emp_u)
            elif st.tool == "search_messages":
                for m in data.get("messages") or []:
                    if not isinstance(m, dict):
                        continue
                    mid = str(m.get("id") or "")
                    read_msg_ids_so_far.add(mid)
                    ev = event_by_msg_id.get(mid)
                    entry = {
                        "day_read": d,
                        "via": "search_messages",
                        "query": str(st.args.get("query") or ""),
                        "id": mid,
                        "msg_day": int(m.get("day") or d),
                        "channel": str(m.get("channel") or ""),
                        "sender": str(m.get("sender") or ""),
                        "subject": str(m.get("subject") or ""),
                        "excerpt": str(m.get("snippet") or ""),
                        "is_social_rumor": ev is not None,
                        "bias": str(ev["bias"]) if ev is not None else None,
                        "target_suspect": str(ev["target"]) if ev is not None else None,
                    }
                    day_msgs_read.append(entry)
                    all_messages_read.append(entry)
            elif st.tool == "read_message":
                m = data.get("message")
                if isinstance(m, dict):
                    mid = str(m.get("id") or "")
                    read_msg_ids_so_far.add(mid)
                    ev = event_by_msg_id.get(mid)
                    entry = {
                        "day_read": d,
                        "via": "read_message",
                        "query": None,
                        "id": mid,
                        "msg_day": int(m.get("day") or d),
                        "channel": str(m.get("channel") or ""),
                        "sender": str(m.get("sender") or ""),
                        "subject": str(m.get("subject") or ""),
                        "excerpt": _truncate(str(m.get("body") or ""), 180),
                        "is_social_rumor": ev is not None,
                        "bias": str(ev["bias"]) if ev is not None else None,
                        "target_suspect": str(ev["target"]) if ev is not None else None,
                    }
                    day_msgs_read.append(entry)
                    all_messages_read.append(entry)
            elif st.tool == "interview":
                emp_id = str(data.get("employee") or st.args.get("employee") or "")
                topic = str(data.get("topic") or st.args.get("topic") or "")
                ans = str(data.get("answer") or "")
                interviewed_today.add(emp_id)
                emp_obj = by_id.get(emp_id)
                iv_entry = {
                    "day": d,
                    "employee": emp_id,
                    "employee_name": emp_obj.name if emp_obj else emp_id,
                    "dept": emp_obj.dept if emp_obj else "",
                    "role": emp_obj.role if emp_obj else "",
                    "topic": topic,
                    "answer": ans,
                    "targets_rumor_suspect": emp_id in focal_set,
                }
                day_interviews.append(iv_entry)
                all_interviews.append(iv_entry)
                if emp_id:
                    bubble_running[emp_id] = _truncate(ans, 110)

        day_rumor_bubbles: list[dict[str, Any]] = []
        if social_state is not None:
            for idx, ev in enumerate(social_state.events_by_day.get(d, ())):
                mid = f"m{d}-s{idx}"
                snd = str(ev["sender"])
                bubble_text = _truncate(str(ev["body"]), 120)
                bubble_running[snd] = bubble_text
                rb = {
                    "message_id": mid,
                    "day": d,
                    "bias": str(ev["bias"]),
                    "sender": snd,
                    "sender_name": str(ev.get("speaker_name") or ""),
                    "target_suspect": str(ev["target"]),
                    "target_name": str(ev.get("target_name") or ""),
                    "channel": str(ev["channel"]),
                    "subject": str(ev.get("subject") or ""),
                    "excerpt": bubble_text,
                    "read_by_gemini": mid in read_msg_ids_so_far,
                }
                day_rumor_bubbles.append(rb)
                all_rumor_bubbles.append(rb)

        inv_post = sp_inv.belief()
        inv_top = max(inv_post, key=inv_post.get) if inv_post else None
        inv_p_mole = round(float(inv_post.get(true_mole, 0.0)), 4)
        inv_p_top = round(float(inv_post[inv_top]), 4) if inv_top else 0.0

        if d in solver_post_by_day:
            last_solver_post = solver_post_by_day[d]
        sol_top = max(last_solver_post, key=last_solver_post.get) if last_solver_post else None
        sol_p_mole = round(float(last_solver_post.get(true_mole, 1.0 / len(env._ids))), 4)
        sol_p_top = round(float(last_solver_post[sol_top]), 4) if sol_top else round(1.0 / len(env._ids), 4)

        trace_entry = {
            "day": d,
            "p_mole": inv_p_mole,
            "top_suspect": inv_top,
            "p_top": inv_p_top,
            "investigator_p_mole": inv_p_mole,
            "investigator_top_suspect": inv_top,
            "investigator_p_top": inv_p_top,
            "solver_p_mole": sol_p_mole,
            "solver_top_suspect": sol_top,
            "solver_p_top": sol_p_top,
        }
        posterior_trace.append(trace_entry)

        day_floorplan = _build_floorplan(
            env._world.employees,
            set(restricted_running),
            interviewed_today,
            dict(bubble_running),
            accused_id=replayed.accused if d == final_day else None,
            done=(d == final_day),
        )
        days_payload.append(
            {
                "day": d,
                "floorplan": day_floorplan,
                "rumor_bubbles": day_rumor_bubbles,
                "messages_read_by_gemini": day_msgs_read,
                "interviews_by_gemini": day_interviews,
                "gemini_steps": [
                    {
                        "t": int(st.t),
                        "day": int(st.day),
                        "tool": str(st.tool),
                        "args": dict(st.args),
                        "ok": bool((st.result or {}).get("ok")),
                    }
                    for st in day_steps
                ],
                "posterior": trace_entry,
            }
        )

    for rb in all_rumor_bubbles:
        rb["read_by_gemini"] = rb["message_id"] in read_msg_ids_so_far

    social_feed, _, _ = _collect_public_social_feed(env)
    xray = _compute_bias_xray(
        env=env,
        provider=prov,
        steps=replayed.steps,
        inv_score=float(replayed.score),
        inv_accused=replayed.accused,
        inv_correct=bool(replayed.correct),
        inv_final_day=final_day,
        mole_opponent_key=DEFAULT_STRATEGY.name,
        mole_strategy=None,
    )

    payload: dict[str, Any] = {
        "mode": "living_office_replay",
        "provenance_badge": "v16-real-gemini-replay",
        "gate_b_disclosure": GATE_B_DISCLOSURE,
        "gate_b_metrics": copy.deepcopy(GATE_B_METRICS),
        "source_path": rel_path,
        "variant": clean_variant,
        "control": bool(prov.variant_spec.get("control", False)),
        "tier": tier,
        "seed": parsed_seed,
        "agent": agent_name,
        "company": env._world.company,
        "done": True,
        "day": final_day,
        "final_day": final_day,
        "score": float(replayed.score),
        "accused": replayed.accused,
        "correct": bool(replayed.correct),
        "end_reason": replayed.end_reason,
        "true_mole": true_mole,
        "decoy": decoy_id,
        "replay_verified": bool(audit["passed"]),
        "audit_summary": audit_row,
        "floorplan": days_payload[-1]["floorplan"] if days_payload else _build_floorplan(
            env._world.employees, set(), set(), {}, accused_id=replayed.accused, done=True
        ),
        "days": days_payload,
        "messages_read_by_gemini": all_messages_read,
        "interviews_by_gemini": all_interviews,
        "rumor_bubbles": all_rumor_bubbles,
        "social_feed": social_feed,
        "posterior_trace": posterior_trace,
        "solver_comparison": copy.deepcopy(xray["solver_comparison"]),
        "xray": xray,
    }
    _REPLAY_PAYLOAD_CACHE[cache_key] = payload
    return copy.deepcopy(payload)


class BiasGulliblePolicy:
    name = "bias_gullible"

    def __init__(self, seed: int = 3000):
        self.seed = int(seed)
        self.reset([], "")

    def reset(self, tools_spec: list[dict[str, Any]], instruction: str) -> None:
        self.tools_spec = list(tools_spec or [])
        self.instruction = instruction or ""
        self.seen = 0
        self.day = 1
        self.n_days = 14
        for line in self.instruction.splitlines():
            s = line.strip()
            if s.startswith("- n_days: "):
                try:
                    self.n_days = int(s.split(": ", 1)[1])
                except ValueError:
                    pass
        self.employees: list[str] = []
        self.rumor_mentions: Counter[str] = Counter()
        self.read_ids: set[str] = set()
        self.pending_read_ids: list[str] = []
        self.planned_day = 0
        self.queue: list[tuple[str, dict[str, Any]]] = []

    def _is_angry_decoy_text(self, text: str) -> bool:
        low = text.lower()
        return any(w in low for w in DECOY_VOCAB)

    def _ingest_text_mentions(self, sender: str, text: str, weight: int = 1) -> None:
        if self._is_angry_decoy_text(text):
            return
        emp_set = set(self.employees)
        found = [eid for eid in _EMP_ID_RE.findall(text) if (not emp_set or eid in emp_set) and eid != sender]
        for eid in found:
            self.rumor_mentions[eid] += weight

    def _ingest(self, st: Step) -> None:
        res = st.result or {}
        if not res.get("ok"):
            return
        data = res.get("data") or {}
        if st.tool == "list_employees":
            emps = data.get("employees") or []
            self.employees = [str(e["id"]) for e in emps if isinstance(e, dict) and "id" in e]
        elif st.tool == "status":
            self.day = int(data.get("day", self.day))
        elif st.tool == "advance_day":
            self.day = int(data.get("day", self.day + 1))
        elif st.tool == "search_messages":
            for m in data.get("messages") or []:
                if not isinstance(m, dict):
                    continue
                mid = str(m.get("id") or "")
                snd = str(m.get("sender") or "")
                combined = f"{m.get('subject', '')} {m.get('snippet', '')}"
                if not self._is_angry_decoy_text(combined):
                    self._ingest_text_mentions(snd, combined, weight=1)
                    if mid and mid not in self.read_ids and mid not in self.pending_read_ids:
                        self.pending_read_ids.append(mid)
        elif st.tool == "read_message":
            msg = data.get("message")
            if isinstance(msg, dict):
                mid = str(msg.get("id") or "")
                if mid:
                    self.read_ids.add(mid)
                snd = str(msg.get("sender") or "")
                combined = f"{msg.get('subject', '')} {msg.get('body', '')}"
                self._ingest_text_mentions(snd, combined, weight=2)

    def _top_rumor_target(self) -> str | None:
        if self.rumor_mentions:
            ranked = sorted(self.rumor_mentions.items(), key=lambda kv: (-kv[1], kv[0]))
            return ranked[0][0]
        return self.employees[0] if self.employees else None

    def act(self, history: list[Step]) -> tuple[str, dict[str, Any]]:
        if len(history) < self.seen:
            self.reset(self.tools_spec, self.instruction)
        for st in history[self.seen :]:
            self._ingest(st)
        self.seen = len(history)

        if not self.employees:
            return ("list_employees", {})

        if self.planned_day != self.day:
            self.planned_day = self.day
            if self.day == 1:
                self.queue = [
                    ("status", {}),
                    ("list_documents", {"day_from": 1, "day_to": 1}),
                    ("advance_day", {}),
                ]
            else:
                prev_day = max(1, self.day - 1)
                self.queue = [
                    ("status", {}),
                    ("search_messages", {"query": "doc", "day_from": prev_day, "day_to": prev_day}),
                    ("search_messages", {"query": "leak", "day_from": prev_day, "day_to": prev_day}),
                    ("__follow_rumor__", {}),
                ]

        while self.queue:
            tool, args = self.queue.pop(0)
            if tool == "__follow_rumor__":
                nxt: list[tuple[str, dict[str, Any]]] = []
                while self.pending_read_ids and len(nxt) < 2:
                    mid = self.pending_read_ids.pop(0)
                    if mid not in self.read_ids:
                        nxt.append(("read_message", {"id": mid}))
                target = self._top_rumor_target()
                if target is not None:
                    top_count = self.rumor_mentions.get(target, 0)
                    if (self.day >= 5 and top_count >= 4) or self.day >= self.n_days:
                        self.queue = [("accuse", {"employee": target})]
                        continue
                    topic = TOPICS[(self.day + self.seed) % len(TOPICS)]
                    nxt.append(("interview", {"employee": target, "topic": topic}))
                nxt.append(("advance_day", {}))
                self.queue = nxt
                continue
            return (tool, args)
        return ("advance_day", {})


class LivingOfficeSession:
    def __init__(
        self,
        tier: str = "medium",
        seed: int = 3000,
        variant: str = "v5_full9_cocktail",
        mole_opponent: str = "default_v0",
    ):
        clean_tier = str(tier or "").strip()
        if clean_tier not in ("medium", "hard"):
            raise ValueError(f"LivingOfficeSession tier must be 'medium' or 'hard', got {tier!r}")
        parsed_seed = _validate_live_seed(seed)
        clean_variant = str(variant or "").strip()
        if clean_variant not in VARIANTS:
            raise ValueError(f"unknown v16 variant {variant!r}")
        opp_name, strat = _resolve_mole_opponent(mole_opponent, parsed_seed)

        self.tier = clean_tier
        self.seed = parsed_seed
        self.variant = clean_variant
        self.mole_opponent = opp_name
        self._mole_strategy = strat
        self.provider: V16SocialProvider = make_v16_provider(clean_variant, mode="template")
        self.env = Env(clean_tier, parsed_seed, text_provider=self.provider, mole_strategy=strat)
        self._policies: dict[str, Any] = {}
        self._cached_xray: dict[str, Any] | None = None

    @property
    def done(self) -> bool:
        return bool(self.env.done)

    @property
    def day(self) -> int:
        return int(self.env.day)

    @property
    def provenance_badge(self) -> str:
        return "v14-control" if self.provider.variant_spec.get("control") else "v16-template-live"

    def _get_policy(self, policy_name: str) -> tuple[str, Any]:
        raw = str(policy_name or "").strip().lower()
        aliases = {
            "gemini_proxy": "gemini_proxy",
            "gemini_carbon_proxy": "gemini_proxy",
            "gemini": "gemini_proxy",
            "solver": "solver",
            "bayesian": "solver",
            "bias_gullible": "bias_gullible",
            "gullible": "bias_gullible",
        }
        canonical = aliases.get(raw)
        if canonical is None:
            raise ValueError(
                f"unknown policy_name {policy_name!r}; expected 'gemini_proxy', 'solver', or 'bias_gullible'"
            )
        if canonical not in self._policies:
            if canonical == "solver":
                pol: Any = SolverPolicy(self.tier)
            elif canonical == "gemini_proxy":
                pol = GeminiCarbonProxy(seed=self.seed)
            else:
                pol = BiasGulliblePolicy(seed=self.seed)
            pol.reset(self.env.tools_spec(), self.env.instruction())
            self._policies[canonical] = pol
        return canonical, self._policies[canonical]

    def call_tool(self, tool: str, args: dict[str, Any] | None = None) -> dict[str, Any]:
        call_args = dict(args or {})
        res = self.env.call(tool, call_args)
        if self.done:
            self._cached_xray = None
        return {
            "ok": bool(res.ok),
            "tool": str(tool),
            "args": call_args,
            "data": res.data,
            "error": res.error,
            "state": self.state_dict(),
        }

    def step_auto_investigator(self, policy_name: str = "gemini_proxy") -> dict[str, Any]:
        canonical, policy = self._get_policy(policy_name)
        start_day = self.day
        start_idx = len(self.env.history)
        if not self.done:
            guard = 0
            while not self.done and self.day == start_day and guard < 30:
                guard += 1
                tool, args = policy.act(list(self.env.history))
                res = self.env.call(tool, dict(args or {}))
                if not res.ok and tool in INVESTIGATIVE_TOOLS and "daily action limit" in str(res.error or ""):
                    self.env.call("advance_day", {})
                    break
            if not self.done and self.day == start_day:
                self.env.call("advance_day", {})
        steps_exec = [
            {
                "t": int(st.t),
                "day": int(st.day),
                "tool": str(st.tool),
                "args": dict(st.args),
                "ok": bool((st.result or {}).get("ok")),
            }
            for st in self.env.history[start_idx:]
        ]
        return {
            "policy": canonical,
            "start_day": start_day,
            "end_day": self.day,
            "done": self.done,
            "steps_executed": steps_exec,
            "state": self.state_dict(),
        }

    def bias_xray_dict(self) -> dict[str, Any]:
        if not self.done:
            raise ValueError("bias_xray_dict is locked until self.done is True")
        if self._cached_xray is None:
            res = self.env.result("living_office_player")
            self._cached_xray = _compute_bias_xray(
                env=self.env,
                provider=self.provider,
                steps=res.steps,
                inv_score=float(res.score),
                inv_accused=res.accused,
                inv_correct=bool(res.correct),
                inv_final_day=int(res.final_day),
                mole_opponent_key=self.mole_opponent,
                mole_strategy=self._mole_strategy,
            )
        return copy.deepcopy(self._cached_xray)

    def state_dict(self) -> dict[str, Any]:
        pub_status = self.env.peek_status()
        restricted_set = set(pub_status.get("restricted") or [])
        social_feed, bubble_by_emp, interviewed_today = _collect_public_social_feed(self.env)
        floorplan = _build_floorplan(
            self.env._world.employees,
            restricted_set,
            interviewed_today,
            bubble_by_emp,
            accused_id=self.env._accused if self.done else None,
            done=self.done,
        )
        recent_steps = [
            {
                "t": int(st.t),
                "day": int(st.day),
                "tool": str(st.tool),
                "args": dict(st.args),
                "ok": bool((st.result or {}).get("ok")),
            }
            for st in self.env.history[-15:]
        ]
        return {
            "mode": "living_office",
            "tier": self.tier,
            "seed": self.seed,
            "variant": self.variant,
            "mole_opponent": self.mole_opponent,
            "company": self.env._world.company,
            "provenance_badge": self.provenance_badge,
            "gate_b_disclosure": GATE_B_DISCLOSURE,
            "gate_b_metrics": copy.deepcopy(GATE_B_METRICS),
            "day": self.day,
            "done": self.done,
            "score": self.env.score(),
            "status": pub_status,
            "verdict": self.env.verdict() if self.done else None,
            "history_count": len(self.env.history),
            "recent_steps": recent_steps,
            "floorplan": floorplan,
            "social_feed": social_feed,
            "xray": self.bias_xray_dict() if self.done else None,
        }
