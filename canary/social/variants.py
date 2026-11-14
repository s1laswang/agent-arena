from __future__ import annotations

import random
from typing import Any, Callable

from .biases import BIAS_TYPES, SocialDayContext, generate_bias_event


HORIZON_DAYS = 21


def _single_bias_schedule(bias: str) -> dict[int, list[dict[str, Any]]]:
    sched: dict[int, list[dict[str, Any]]] = {}
    for day in range(1, HORIZON_DAYS + 1):
        if bias == "grudge":
            if day == 1:
                sched[day] = [{"bias": "grudge", "pair_index": 0}, {"bias": "grudge", "pair_index": 1}]
            else:
                sched[day] = [{"bias": "grudge", "pair_index": (day + 1) % 2}]
        elif day == 1:
            sched[day] = [{"bias": bias}, {"bias": bias, "secondary": True}]
        else:
            sched[day] = [{"bias": bias}]
    return sched


VARIANTS: dict[str, dict[str, Any]] = {
    "v0_v14_control": {
        "name": "v0_v14_control",
        "control": True,
        "biases": (),
        "schedule": {},
    },
    "v1_anchoring_authority_confirmation": {
        "name": "v1_anchoring_authority_confirmation",
        "control": False,
        "biases": ("anchoring", "authority", "confirmation"),
        "schedule": {
            1: [{"bias": "anchoring"}, {"bias": "anchoring"}],
            2: [{"bias": "anchoring"}],
            3: [{"bias": "confirmation"}],
            4: [{"bias": "authority"}, {"bias": "confirmation"}],
            5: [{"bias": "confirmation"}],
            6: [{"bias": "confirmation"}, {"bias": "anchoring"}],
            7: [{"bias": "confirmation"}],
            8: [{"bias": "authority"}, {"bias": "confirmation"}],
            9: [{"bias": "confirmation"}],
            10: [{"bias": "confirmation"}],
            12: [{"bias": "confirmation"}],
            14: [{"bias": "confirmation"}],
            16: [{"bias": "authority"}, {"bias": "confirmation"}],
            18: [{"bias": "confirmation"}, {"bias": "anchoring"}],
            19: [{"bias": "confirmation"}],
            20: [{"bias": "authority"}, {"bias": "confirmation"}],
            21: [{"bias": "anchoring"}, {"bias": "confirmation"}],
        },
    },
    "v2_recency_bandwagon_sycophancy": {
        "name": "v2_recency_bandwagon_sycophancy",
        "control": False,
        "biases": ("authority", "recency", "bandwagon", "sycophancy"),
        "schedule": {
            1: [{"bias": "bandwagon"}, {"bias": "bandwagon"}],
            2: [{"bias": "bandwagon"}],
            3: [{"bias": "authority"}, {"bias": "sycophancy"}],
            4: [{"bias": "bandwagon"}, {"bias": "sycophancy"}],
            5: [{"bias": "authority"}, {"bias": "sycophancy"}, {"bias": "bandwagon"}],
            6: [{"bias": "bandwagon"}, {"bias": "sycophancy"}],
            7: [{"bias": "authority"}, {"bias": "sycophancy"}],
            8: [{"bias": "recency"}, {"bias": "bandwagon"}],
            9: [{"bias": "recency"}, {"bias": "recency"}],
            10: [{"bias": "recency"}, {"bias": "sycophancy"}],
            11: [{"bias": "recency"}, {"bias": "bandwagon"}],
            12: [{"bias": "recency"}, {"bias": "recency"}],
            13: [{"bias": "recency"}, {"bias": "bandwagon"}],
            14: [{"bias": "recency"}, {"bias": "sycophancy"}],
            15: [{"bias": "recency"}, {"bias": "recency"}],
            16: [{"bias": "authority"}, {"bias": "sycophancy"}],
            17: [{"bias": "recency"}, {"bias": "bandwagon"}],
            18: [{"bias": "recency"}, {"bias": "sycophancy"}],
            19: [{"bias": "authority"}, {"bias": "sycophancy"}],
            20: [{"bias": "recency"}, {"bias": "bandwagon"}],
            21: [{"bias": "recency"}, {"bias": "sycophancy"}],
        },
    },
    "v3_grudge_falsemem_misforward": {
        "name": "v3_grudge_falsemem_misforward",
        "control": False,
        "biases": ("grudge", "false_memory", "misforward"),
        "schedule": {
            1: [{"bias": "grudge", "pair_index": 0}, {"bias": "misforward"}],
            2: [{"bias": "grudge", "pair_index": 1}, {"bias": "false_memory"}],
            3: [{"bias": "grudge", "pair_index": 0}, {"bias": "misforward"}],
            4: [{"bias": "false_memory"}, {"bias": "misforward"}],
            5: [{"bias": "grudge", "pair_index": 0}, {"bias": "false_memory"}],
            6: [{"bias": "grudge", "pair_index": 1}, {"bias": "misforward"}],
            7: [{"bias": "false_memory"}, {"bias": "grudge", "pair_index": 0}],
            8: [{"bias": "misforward"}, {"bias": "false_memory"}],
            9: [{"bias": "grudge", "pair_index": 0}, {"bias": "grudge", "pair_index": 1}],
            10: [{"bias": "false_memory"}, {"bias": "misforward"}],
            11: [{"bias": "grudge", "pair_index": 0}],
            12: [{"bias": "false_memory"}, {"bias": "misforward"}],
            13: [{"bias": "grudge", "pair_index": 0}, {"bias": "false_memory"}],
            14: [{"bias": "misforward"}, {"bias": "grudge", "pair_index": 0}],
            15: [{"bias": "false_memory"}],
            16: [{"bias": "grudge", "pair_index": 0}],
            17: [{"bias": "false_memory"}, {"bias": "grudge", "pair_index": 1}],
            18: [{"bias": "misforward"}, {"bias": "grudge", "pair_index": 0}],
            19: [{"bias": "grudge", "pair_index": 1}, {"bias": "false_memory"}],
            20: [{"bias": "misforward"}, {"bias": "grudge", "pair_index": 0}],
            21: [{"bias": "grudge", "pair_index": 0}, {"bias": "grudge", "pair_index": 1}],
        },
    },
    "v4_triad_authority_recency_grudge": {
        "name": "v4_triad_authority_recency_grudge",
        "control": False,
        "biases": ("anchoring", "confirmation", "authority", "recency", "grudge"),
        "schedule": {
            1: [{"bias": "anchoring"}, {"bias": "grudge", "pair_index": 0}],
            2: [{"bias": "confirmation"}, {"bias": "grudge", "pair_index": 1}],
            3: [{"bias": "authority"}, {"bias": "grudge", "pair_index": 0}],
            4: [{"bias": "confirmation"}],
            5: [{"bias": "grudge", "pair_index": 0}, {"bias": "anchoring"}],
            6: [{"bias": "confirmation"}, {"bias": "grudge", "pair_index": 1}],
            7: [{"bias": "authority"}, {"bias": "confirmation"}],
            8: [{"bias": "grudge", "pair_index": 0}],
            9: [{"bias": "recency"}, {"bias": "recency"}],
            10: [{"bias": "recency"}, {"bias": "grudge", "pair_index": 0}],
            11: [{"bias": "recency"}, {"bias": "confirmation"}],
            12: [{"bias": "recency"}, {"bias": "recency"}],
            13: [{"bias": "recency"}, {"bias": "grudge", "pair_index": 0}],
            14: [{"bias": "recency"}, {"bias": "anchoring"}],
            15: [{"bias": "recency"}],
            16: [{"bias": "authority"}, {"bias": "grudge", "pair_index": 1}],
            17: [{"bias": "recency"}, {"bias": "confirmation"}],
            18: [{"bias": "recency"}, {"bias": "grudge", "pair_index": 0}],
            19: [{"bias": "authority"}, {"bias": "anchoring"}],
            20: [{"bias": "recency"}, {"bias": "grudge", "pair_index": 1}],
            21: [{"bias": "recency"}, {"bias": "grudge", "pair_index": 0}],
        },
    },
    "v5_full9_cocktail": {
        "name": "v5_full9_cocktail",
        "control": False,
        "biases": BIAS_TYPES,
        "schedule": {
            1: [{"bias": "anchoring"}, {"bias": "misforward"}, {"bias": "grudge", "pair_index": 0}],
            2: [{"bias": "anchoring"}, {"bias": "confirmation"}, {"bias": "grudge", "pair_index": 1}],
            3: [{"bias": "authority"}, {"bias": "sycophancy"}],
            4: [{"bias": "confirmation"}, {"bias": "bandwagon"}, {"bias": "grudge", "pair_index": 0}],
            5: [{"bias": "false_memory"}, {"bias": "misforward"}],
            6: [{"bias": "bandwagon"}, {"bias": "confirmation"}, {"bias": "grudge", "pair_index": 1}],
            7: [{"bias": "authority"}, {"bias": "sycophancy"}],
            8: [{"bias": "recency"}, {"bias": "false_memory"}, {"bias": "grudge", "pair_index": 0}],
            9: [{"bias": "recency"}, {"bias": "bandwagon"}],
            10: [{"bias": "recency"}, {"bias": "confirmation"}, {"bias": "misforward"}],
            11: [{"bias": "authority"}, {"bias": "sycophancy"}, {"bias": "recency"}],
            12: [{"bias": "recency"}, {"bias": "false_memory"}, {"bias": "grudge", "pair_index": 0}],
            13: [{"bias": "recency"}, {"bias": "bandwagon"}],
            14: [{"bias": "recency"}, {"bias": "anchoring"}, {"bias": "sycophancy"}],
            15: [{"bias": "recency"}, {"bias": "confirmation"}],
            16: [{"bias": "false_memory"}, {"bias": "grudge", "pair_index": 0}],
            17: [{"bias": "misforward"}, {"bias": "bandwagon"}],
            18: [{"bias": "recency"}, {"bias": "authority"}],
            19: [{"bias": "authority"}, {"bias": "sycophancy"}, {"bias": "grudge", "pair_index": 1}],
            20: [{"bias": "recency"}, {"bias": "confirmation"}, {"bias": "misforward"}],
            21: [{"bias": "recency"}, {"bias": "anchoring"}, {"bias": "grudge", "pair_index": 0}],
        },
    },
}

for _b in BIAS_TYPES:
    VARIANTS[f"b_{_b}"] = {
        "name": f"b_{_b}",
        "control": False,
        "biases": (_b,),
        "schedule": _single_bias_schedule(_b),
    }


def _normalize_step(item: str | dict[str, Any]) -> dict[str, Any]:
    if isinstance(item, str):
        if item not in BIAS_TYPES:
            raise ValueError(f"unknown bias {item!r}")
        return {"bias": item}
    if isinstance(item, dict):
        bias = str(item.get("bias") or item.get("kind") or "")
        if bias not in BIAS_TYPES:
            raise ValueError(f"unknown bias {bias!r}")
        out = dict(item)
        out["bias"] = bias
        return out
    raise ValueError(f"invalid schedule entry {item!r}")


def register_fr8_variant(name: str, spec: Any) -> dict[str, Any]:
    clean_name = str(name or "").strip()
    if not clean_name:
        raise ValueError("variant name must be non-empty")
    if callable(spec):
        entry = {
            "name": clean_name,
            "control": False,
            "biases": (),
            "schedule": {},
            "generator": spec,
        }
        VARIANTS[clean_name] = entry
        return entry
    if isinstance(spec, (list, tuple)):
        biases = tuple(str(b) for b in spec)
        for b in biases:
            if b not in BIAS_TYPES:
                raise ValueError(f"unknown bias {b!r}")
        if not biases:
            entry = {"name": clean_name, "control": True, "biases": (), "schedule": {}}
        else:
            sched: dict[int, list[dict[str, Any]]] = {}
            for d in range(1, HORIZON_DAYS + 1):
                b = biases[(d - 1) % len(biases)]
                sched[d] = [{"bias": b}]
                if d == 1 and len(biases) > 1:
                    sched[d].append({"bias": biases[1]})
            entry = {"name": clean_name, "control": False, "biases": biases, "schedule": sched}
        VARIANTS[clean_name] = entry
        return entry
    if not isinstance(spec, dict):
        raise ValueError(f"unsupported FR8 variant spec {spec!r}")
    if bool(spec.get("control")):
        entry = {"name": clean_name, "control": True, "biases": (), "schedule": {}}
        VARIANTS[clean_name] = entry
        return entry
    if callable(spec.get("generator")):
        biases = tuple(str(b) for b in spec.get("biases", ()))
        entry = {
            "name": clean_name,
            "control": False,
            "biases": biases,
            "schedule": {},
            "generator": spec["generator"],
        }
        VARIANTS[clean_name] = entry
        return entry
    raw_sched = spec.get("schedule")
    if isinstance(raw_sched, dict):
        norm_sched: dict[int, list[dict[str, Any]]] = {}
        seen_biases: list[str] = []
        for k, steps in raw_sched.items():
            day = int(k)
            step_list = [_normalize_step(x) for x in (steps if isinstance(steps, (list, tuple)) else [steps])]
            norm_sched[day] = step_list
            for st in step_list:
                if st["bias"] not in seen_biases:
                    seen_biases.append(st["bias"])
        biases = tuple(spec.get("biases") or seen_biases)
        entry = {"name": clean_name, "control": not bool(norm_sched), "biases": biases, "schedule": norm_sched}
        VARIANTS[clean_name] = entry
        return entry
    if "bias" in spec:
        b = str(spec["bias"])
        if b not in BIAS_TYPES:
            raise ValueError(f"unknown bias {b!r}")
        entry = {
            "name": clean_name,
            "control": False,
            "biases": (b,),
            "schedule": _single_bias_schedule(b),
        }
        VARIANTS[clean_name] = entry
        return entry
    if "biases" in spec:
        biases = tuple(str(b) for b in spec["biases"])
        for b in biases:
            if b not in BIAS_TYPES:
                raise ValueError(f"unknown bias {b!r}")
        days = [int(d) for d in spec.get("days", range(1, HORIZON_DAYS + 1))]
        per_day = max(1, int(spec.get("per_day", 1)))
        norm_sched = {}
        idx = 0
        for d in days:
            norm_sched[d] = []
            count = max(per_day, 2 if d == 1 and len(biases) > 1 else per_day)
            for _ in range(count):
                norm_sched[d].append({"bias": biases[idx % len(biases)]})
                idx += 1
        entry = {"name": clean_name, "control": not bool(norm_sched), "biases": biases, "schedule": norm_sched}
        VARIANTS[clean_name] = entry
        return entry
    raise ValueError(f"cannot normalize FR8 variant spec for {clean_name!r}")


_ALIASES: dict[str, str] = {
    "v0": "v0_v14_control",
    "control": "v0_v14_control",
    "v1": "v1_anchoring_authority_confirmation",
    "v2": "v2_recency_bandwagon_sycophancy",
    "v3": "v3_grudge_falsemem_misforward",
    "v4": "v4_triad_authority_recency_grudge",
    "v5": "v5_full9_cocktail",
    "all": "v5_full9_cocktail",
    "default": "v5_full9_cocktail",
    "social-v2": "v5_full9_cocktail",
    "consensus": "b_bandwagon",
}
for _alias_b in BIAS_TYPES:
    _ALIASES[_alias_b] = f"b_{_alias_b}"


def get_variant_spec(variant: str) -> dict[str, Any]:
    if variant in VARIANTS:
        return VARIANTS[variant]
    low = str(variant or "").strip().lower()
    if low in VARIANTS:
        return VARIANTS[low]
    if low in _ALIASES:
        return VARIANTS[_ALIASES[low]]
    if "+" in low or "," in low:
        raw_parts = [p.strip() for p in low.replace(",", "+").split("+") if p.strip()]
        biases: list[str] = []
        for p in raw_parts:
            target = _ALIASES.get(p, p)
            if target in VARIANTS:
                for b in VARIANTS[target]["biases"]:
                    if b not in biases:
                        biases.append(b)
            elif p in BIAS_TYPES:
                if p not in biases:
                    biases.append(p)
            else:
                raise ValueError(f"unknown v16 social variant {variant!r}")
        if biases:
            sched: dict[int, list[dict[str, Any]]] = {}
            for d in range(1, HORIZON_DAYS + 1):
                sched[d] = [{"bias": biases[(d - 1) % len(biases)]}]
                if d == 1 and len(biases) > 1:
                    sched[d].append({"bias": biases[1]})
            return {"name": low, "control": False, "biases": tuple(biases), "schedule": sched}
    raise ValueError(f"unknown v16 social variant {variant!r}")


def parse_variant_biases(variant: str | None) -> tuple[str, ...]:
    return tuple(get_variant_spec(variant or "all").get("biases", ()))


def run_variant_day(
    variant_spec: dict[str, Any],
    ctx: SocialDayContext,
    rng: random.Random,
) -> list[dict[str, Any]]:
    if variant_spec.get("control"):
        return []
    gen_fn: Callable[..., list[dict[str, Any]]] | None = variant_spec.get("generator")
    if callable(gen_fn):
        return list(gen_fn(ctx, rng))
    steps = variant_spec.get("schedule", {}).get(ctx.facts.day, ())
    events: list[dict[str, Any]] = []
    cur_ctx = ctx
    for idx, step in enumerate(steps):
        step_rng = random.Random(f"{rng.random():.16f}:{idx}:{step['bias']}")
        opts = {k: v for k, v in step.items() if k != "bias"}
        ev = generate_bias_event(step["bias"], cur_ctx, step_rng, **opts)
        events.append(ev)
        next_grudge_counts = dict(cur_ctx.grudge_counts)
        if ev.get("bias") == "grudge":
            pair = (str(ev.get("sender", "")), str(ev.get("target", "")))
            next_grudge_counts[pair] = next_grudge_counts.get(pair, 0) + 1
        cur_ctx = SocialDayContext(
            facts=cur_ctx.facts,
            by_id=cur_ctx.by_id,
            primary_suspect=cur_ctx.primary_suspect,
            secondary_suspect=cur_ctx.secondary_suspect,
            authority_speakers=cur_ctx.authority_speakers,
            grudge_pairs=cur_ctx.grudge_pairs,
            peers=cur_ctx.peers,
            seen_docs=cur_ctx.seen_docs,
            prior_events=cur_ctx.prior_events,
            today_events=cur_ctx.today_events + (ev,),
            grudge_counts=next_grudge_counts,
        )
    return events
