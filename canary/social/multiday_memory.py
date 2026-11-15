from __future__ import annotations

import random
import re
from typing import Any

from .biases import BIAS_TYPES, SocialDayContext, generate_bias_event, validate_social_message
from .engine import EpisodeSocialState
from .variants import register_fr8_variant

DEFAULT_VARIANT_NAME = "sleeper_multiday_arc"
PRIOR_DAY_RE = re.compile(r"\bDay ([1-9]|1\d|20)\b")
_EMP_ID_RE = re.compile(r"\be\d\d\b")
_SOCIAL_ID_RE = re.compile(r"^m\d+-s\d+$")
_BASE_ID_RE = re.compile(r"^m\d+-\d+$")

MULTIDAY_PHASE_SCHEDULE: dict[int, tuple[dict[str, Any], ...]] = {
    1: ({"bias": "anchoring"}, {"bias": "misforward", "secondary": True}),
    2: ({"bias": "misforward"}, {"bias": "anchoring", "secondary": True}),
    3: ({"bias": "anchoring"}, {"bias": "misforward", "secondary": True}),
    4: ({"bias": "authority"}, {"bias": "confirmation", "secondary": True}),
    5: ({"bias": "sycophancy"}, {"bias": "confirmation"}),
    6: ({"bias": "authority", "secondary": True}, {"bias": "confirmation"}),
    7: ({"bias": "sycophancy", "secondary": True}, {"bias": "authority"}, {"bias": "confirmation"}),
    8: ({"bias": "bandwagon"}, {"bias": "grudge", "pair_index": 0}),
    9: ({"bias": "false_memory", "secondary": True}, {"bias": "grudge", "pair_index": 1}),
    10: ({"bias": "bandwagon", "secondary": True}, {"bias": "grudge", "pair_index": 0}),
    11: ({"bias": "false_memory"}, {"bias": "grudge", "pair_index": 1}),
    12: ({"bias": "bandwagon"}, {"bias": "grudge", "pair_index": 0}, {"bias": "false_memory", "secondary": True}),
    13: ({"bias": "false_memory"}, {"bias": "grudge", "pair_index": 1}, {"bias": "bandwagon", "secondary": True}),
    14: ({"bias": "recency"}, {"bias": "confirmation", "secondary": True}),
    15: ({"bias": "recency", "secondary": True}, {"bias": "confirmation"}),
    16: ({"bias": "recency"}, {"bias": "confirmation"}),
    17: ({"bias": "recency"}, {"bias": "confirmation", "secondary": True}),
    18: ({"bias": "recency"}, {"bias": "recency", "secondary": True}, {"bias": "confirmation"}),
}


def phase_for_day(day: int) -> str | None:
    if 1 <= day <= 3:
        return "seeding"
    if 4 <= day <= 7:
        return "authority_callbacks"
    if 8 <= day <= 13:
        return "cross_dept_escalation"
    if 14 <= day <= 18:
        return "stopping_window"
    return None


def build_multiday_memory_events(ctx: SocialDayContext, rng: random.Random) -> list[dict[str, Any]]:
    day = ctx.facts.day
    steps = MULTIDAY_PHASE_SCHEDULE.get(day)
    if not steps or not ctx.by_id:
        return []

    valid_ids = set(ctx.by_id)
    events: list[dict[str, Any]] = []
    cur_ctx = ctx
    for idx, step in enumerate(steps):
        bias = str(step["bias"])
        step_rng = random.Random(f"{rng.random():.16f}:multiday:{day}:{idx}:{bias}")
        opts = {k: v for k, v in step.items() if k != "bias"}
        ev = generate_bias_event(bias, cur_ctx, step_rng, **opts)
        candidate_msg = {
            "id": f"m{day}-s{len(events)}",
            "day": day,
            "channel": str(ev["channel"]),
            "sender": str(ev["sender"]),
            "recipients": [r for r in ev.get("recipients", ()) if r in valid_ids and r != ev["sender"]]
            or [eid for eid in valid_ids if eid != ev["sender"]]
            or [str(ev["sender"])],
            "subject": str(ev.get("subject", "")),
            "body": str(ev["body"]),
        }
        target_id = ev.get("target")
        target_emp = cur_ctx.by_id.get(target_id) if isinstance(target_id, str) else None
        errs = validate_social_message(
            candidate_msg,
            target_emp=target_emp,
            decoy_id=cur_ctx.facts.decoy,
            valid_ids=valid_ids,
        )
        if errs:
            raise ValueError(f"invalid multiday memory event (day={day}, bias={bias}): {errs}")
        events.append(ev)

        next_grudge = dict(cur_ctx.grudge_counts)
        if bias == "grudge":
            pair = (str(ev["sender"]), str(ev.get("target", "")))
            next_grudge[pair] = next_grudge.get(pair, 0) + 1
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
            grudge_counts=next_grudge,
        )
    return events


def register_multiday_memory_variant(name: str = DEFAULT_VARIANT_NAME) -> dict[str, Any]:
    return register_fr8_variant(
        name,
        {
            "biases": BIAS_TYPES,
            "generator": build_multiday_memory_events,
        },
    )


def _to_timeline_entry(item: dict[str, Any], default_id: str) -> dict[str, Any]:
    day = int(item["day"])
    msg_id = str(item.get("id") or default_id)
    sender = str(item.get("sender", ""))
    if "body" in item or "subject" in item:
        subj = str(item.get("subject", ""))
        body = str(item.get("body", ""))
        text = f"{subj}\n{body}" if subj else body
        mentioned_ids = list(dict.fromkeys(_EMP_ID_RE.findall(text)))
        target = item.get("target")
        if isinstance(target, str) and _EMP_ID_RE.fullmatch(target) and target not in mentioned_ids:
            mentioned_ids.insert(0, target)
        referenced_days = list(dict.fromkeys(int(m.group(1)) for m in PRIOR_DAY_RE.finditer(text)))
    else:
        mentioned_ids = list(dict.fromkeys(str(x) for x in item.get("mentioned_ids", ())))
        referenced_days = list(dict.fromkeys(int(x) for x in item.get("referenced_days", ())))
    return {
        "id": msg_id,
        "day": day,
        "sender": sender,
        "mentioned_ids": mentioned_ids,
        "referenced_days": referenced_days,
    }


def _collect_raw_items(messages_or_state: Any) -> tuple[list[dict[str, Any]], bool]:
    if isinstance(messages_or_state, EpisodeSocialState) or hasattr(messages_or_state, "events_by_day"):
        events_map = getattr(messages_or_state, "events_by_day", {})
        out: list[dict[str, Any]] = []
        for day in sorted(events_map):
            for idx, ev in enumerate(events_map[day]):
                copied = dict(ev)
                copied.setdefault("day", int(day))
                copied.setdefault("id", f"m{int(day)}-s{idx}")
                out.append(copied)
        return out, True

    if hasattr(messages_or_state, "_messages") and isinstance(messages_or_state._messages, dict):
        msg_map = messages_or_state._messages
        order = getattr(messages_or_state, "_msg_order", None)
        if isinstance(order, list):
            return [dict(msg_map[mid]) for mid in order if mid in msg_map], False
        return [dict(v) for v in msg_map.values() if isinstance(v, dict)], False

    if isinstance(messages_or_state, dict):
        if isinstance(messages_or_state.get("messages"), (list, tuple)):
            return [dict(x) for x in messages_or_state["messages"] if isinstance(x, dict)], False
        vals = list(messages_or_state.values())
        if vals and all(isinstance(v, dict) for v in vals):
            return [dict(v) for v in vals], False
        out = []
        for k in sorted(messages_or_state, key=lambda x: int(x) if str(x).isdigit() else 0):
            seq = messages_or_state[k]
            if isinstance(seq, (list, tuple)):
                for idx, ev in enumerate(seq):
                    if isinstance(ev, dict):
                        copied = dict(ev)
                        if str(k).isdigit():
                            copied.setdefault("day", int(k))
                            copied.setdefault("id", f"m{int(k)}-s{idx}")
                        out.append(copied)
        return out, True

    return [dict(x) for x in messages_or_state if isinstance(x, dict)], False


def _is_tagged_social(item: dict[str, Any]) -> bool:
    mid = str(item.get("id", ""))
    return bool(_SOCIAL_ID_RE.match(mid) or "-s" in mid or "bias" in item)


def extract_social_timeline(messages_or_state: Any) -> list[dict[str, Any]]:
    raw_items, prefiltered = _collect_raw_items(messages_or_state)
    if not raw_items:
        return []

    if prefiltered:
        selected = raw_items
    elif any(_is_tagged_social(item) for item in raw_items):
        selected = [item for item in raw_items if _is_tagged_social(item)]
    elif all(_BASE_ID_RE.match(str(item.get("id", ""))) for item in raw_items) and any(
        str(item.get("subject", "")) == "" for item in raw_items
    ):
        return []
    else:
        selected = raw_items

    indexed: list[tuple[int, int, dict[str, Any]]] = []
    per_day_counts: dict[int, int] = {}
    for pos, item in enumerate(selected):
        day = int(item["day"])
        sub_idx = per_day_counts.get(day, 0)
        per_day_counts[day] = sub_idx + 1
        entry = _to_timeline_entry(item, f"m{day}-s{sub_idx}")
        indexed.append((day, pos, entry))
    indexed.sort(key=lambda t: (t[0], t[1]))
    return [entry for _, _, entry in indexed]


def verify_timeline_continuity(
    timeline: list[dict[str, Any]],
    decoy_id: str | None = None,
) -> list[str]:
    if not timeline:
        return ["empty social timeline"]

    problems: list[str] = []
    by_day: dict[int, list[tuple[str, str, list[str], list[int]]]] = {}
    prev_day = 0

    for idx, entry in enumerate(timeline):
        eid = str(entry.get("id") or f"idx-{idx}")
        day = int(entry.get("day", 0))
        sender = str(entry.get("sender", ""))
        mentioned = [str(x) for x in entry.get("mentioned_ids", ())]
        refs = [int(x) for x in entry.get("referenced_days", ())]

        if day < 1:
            problems.append(f"{eid}: invalid day {day}")
        if day < prev_day:
            problems.append(f"{eid}: out-of-order day {day} after day {prev_day}")
        if day > prev_day:
            prev_day = day

        if not sender:
            problems.append(f"{eid}: missing sender")
        if not mentioned:
            problems.append(f"{eid}: missing mentioned_ids")

        if decoy_id is not None:
            if sender == decoy_id:
                problems.append(f"{eid}: decoy {decoy_id} cannot send social message")
            if decoy_id in mentioned:
                problems.append(f"{eid}: social message mentions or frames decoy {decoy_id}")

        for rday in refs:
            if rday < 1 or rday >= day:
                problems.append(f"{eid}: non-causal reference Day {rday} on Day {day}")

        if day >= 1:
            by_day.setdefault(day, []).append((eid, sender, mentioned, refs))

    if not any(1 <= d <= 4 for d in by_day):
        problems.append("missing early seeding events in Days 1..4")

    window_days = sorted(d for d in by_day if 5 <= d <= 18)
    if not window_days:
        problems.append("missing multi-day callback events in Days 5..18")

    for d in window_days:
        day_entries = by_day[d]
        if not any(1 <= r < d for _, _, _, rs in day_entries for r in rs):
            problems.append(f"Day {d}: missing causal prior-day callback")
        earlier_mentions = {
            m
            for prev_d, items in by_day.items()
            if prev_d < d
            for _, _, ms, _ in items
            for m in ms
        }
        if not any(m in earlier_mentions for _, _, ms, _ in day_entries for m in ms):
            problems.append(f"Day {d}: no suspect continuity with earlier days")

    return problems


register_multiday_memory_variant()

__all__ = [
    "DEFAULT_VARIANT_NAME",
    "MULTIDAY_PHASE_SCHEDULE",
    "PRIOR_DAY_RE",
    "build_multiday_memory_events",
    "extract_social_timeline",
    "phase_for_day",
    "register_multiday_memory_variant",
    "verify_timeline_continuity",
]
