from __future__ import annotations

import hashlib
import io
import json
import os
import random
import re
import time
from pathlib import Path
from typing import Any, Callable

from PIL import Image, ImageDraw, ImageFont

from canary.gemini.ledger import record
from canary.gemini.sdk import genai_client
from canary.llm.base import LLMError, is_retryable

DEFAULT_MODEL = "gemini-4-carbon"
FEATURE = "multimodal_evidence"
SUBROLE = "soc_access_vision"


def subrole_for_tier(tier: str) -> str:
    t = (tier or "medium").strip().lower()
    return SUBROLE if t == "medium" else f"{SUBROLE}_{t}"


SOC_VISION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "top_suspect_ids": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Ordered list of top mole suspect employee IDs in lowercase e00-e39 format, most likely mole first.",
        },
        "suspected_decoy_ids": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Ordered list of framed decoy employee IDs in lowercase e00-e39 format showing anomalous after-hours spikes without full canary leak correlation.",
        },
        "confidence": {
            "type": "number",
            "description": "Posterior confidence between 0.0 and 1.0 that top_suspect_ids[0] is the true mole.",
        },
        "canary_leak_summary": {
            "type": "string",
            "description": "Concise visual readout of surfaced canary columns, their leaked variant labels, and which employee rows held and matched surfaced canaries.",
        },
        "visual_reasoning": {
            "type": "string",
            "description": "Concise visual explanation contrasting Panel A after-hours framing spikes against Panel B canary partition matches and Panel C regular leaked-doc correlations. Use plain ASCII hyphens (-), never em dashes.",
        },
    },
    "required": [
        "top_suspect_ids",
        "suspected_decoy_ids",
        "confidence",
        "canary_leak_summary",
        "visual_reasoning",
    ],
}

SOC_VISION_PROMPT = (
    "You are a Security Operations Center (SOC) analyst inspecting a visual telemetry raster from a Canary medium-tier "
    "(v1.4) corporate leak investigation.\n\n"
    "Read all evidence directly from the three synchronized horizontal panels in the PNG image:\n"
    "1. Panel A (Daily Access & After-Hours Framing Spikes): shows per-day sensitive document opens and red after-hours "
    "events for employees e00..e19. In this environment, benign staff average 10% after-hours and the mole averages 15% "
    "after-hours, whereas mole framing injects ~1.5 fake after-hours events per day with 50% concentrated onto one "
    "innocent decoy employee (and never onto the mole itself). A huge red after-hours bar without full canary match is "
    "the classic signature of a framed decoy.\n"
    "2. Panel B (Canary Partition & Surfaced Leak Matrix): shows planted canary traps (c1..c12) partitioned across "
    "variants A, B, C. Columns with a green header badge surfaced in the leak feed with that exact variant. Bright green "
    "[A]/[B]/[C] tiles mark employees who held the surfaced variant; dim struck tiles mark employees cleared by that "
    "surfaced canary. On medium tier, canary variant fingerprinting is exact (100% accuracy), so the true mole must "
    "match ALL surfaced canary leaks (shown in the MATCH column as K/K).\n"
    "3. Panel C (Surfaced Regular-Leak Access Correlation): shows surfaced non-canary leaked documents. Bright gold Lk "
    "tiles mark employees who directly opened that leaked document in access logs; warm bronze D tiles mark employees "
    "whose department colleagues opened that leaked document (regular documents are sent to whole departments). Use "
    "Panel C to break ties if more than one employee matches all surfaced canary variants in Panel B.\n\n"
    "Return JSON matching the schema with lowercase employee IDs (such as e05). Put the single best mole candidate first "
    "in top_suspect_ids, put the primary framed decoy first in suspected_decoy_ids, and use plain ASCII hyphens (-) in text."
)

SOC_VISION_PROMPT_HARD = (
    "You are a Security Operations Center (SOC) analyst inspecting a dense 40-employee visual telemetry raster from a "
    "Canary hard-tier (v1.4) corporate leak investigation.\n\n"
    "Read all evidence directly from the three synchronized horizontal panels in the PNG image:\n"
    "1. Panel A (Daily Access & After-Hours Framing Spikes): shows per-day sensitive document opens and red after-hours "
    "events across closed days D01..D20 for employees e00..e39. Benign staff average 10% after-hours and the mole "
    "averages 30% after-hours (~1.0 total log/day), whereas mole framing injects ~2.0 fake after-hours events per day "
    "with 50% concentrated onto one innocent decoy employee (and never onto the mole itself). A huge red after-hours "
    "bar on an employee cleared in Panel B is the classic signature of the framed decoy.\n"
    "2. Panel B (Canary Partitions & Noisy 95% Surfaced Variants): shows ternary canary traps alongside surfaced canary "
    "leaks (green header badges =A!, =B!, or =C!). An employee can ONLY leak a canary they actually received: dim "
    "crossed-out '-' tiles mark employees who never received that surfaced canary and are 100% cleared (shown in MATCH "
    "as Hx/K with x < K). On hard tier, canary variant fingerprinting is 95% accurate (5% chance a surfaced canary "
    "reports one of the canary's other variants). Among employees who held ALL surfaced canaries (HK/K in MATCH), "
    "bright green [A]/[B]/[C] tiles mark 95%-accurate variant matches while amber ~A/~B/~C tiles mark 5% noisy variant "
    "mismatches. Each extra variant match among HK/K rows multiplies mole odds by ~38x (ALL K/K HK beats (K-1)/K HK/K, "
    "and when variant noise leaves zero K/K rows, (K-1)/K HK/K strongly beats (K-2)/K HK/K).\n"
    "3. Panel C (Surfaced Regular-Leak Access Correlation): shows surfaced non-canary leaked documents. Bright gold Lk "
    "tiles mark direct access-log opens and bronze D tiles mark department exposure; combine Panel C and moderate "
    "Panel A after-hours rate (~30%) to corroborate or break ties among top HK/K candidates.\n\n"
    "Return JSON matching the schema with lowercase employee IDs (such as e25). Put the single best mole candidate first "
    "in top_suspect_ids, put the primary framed decoy first in suspected_decoy_ids, and use plain ASCII hyphens (-) in text."
)


def prompt_for_tier(tier: str) -> str:
    t = (tier or "medium").strip().lower()
    return SOC_VISION_PROMPT if t == "medium" else SOC_VISION_PROMPT_HARD


def _sanitize_text(text: str) -> str:
    return (text or "").replace("\u2014", "-").replace("\u2013", "-").strip()


def _normalize_emp_ids(items: list[Any], valid_ids: set[str] | None = None) -> list[str]:
    out: list[str] = []
    for raw in items or []:
        m = re.search(r"\be\d{2}\b", str(raw).lower())
        if not m:
            continue
        eid = m.group(0)
        if valid_ids is not None and eid not in valid_ids:
            continue
        if eid not in out:
            out.append(eid)
    return out


def raster_sha256(png_bytes: bytes) -> str:
    return hashlib.sha256(png_bytes).hexdigest()


def _load_font(size: int, bold: bool = False, mono: bool = True) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    try:
        import matplotlib
        ttf_dir = Path(matplotlib.get_data_path()) / "fonts" / "ttf"
        if mono:
            fname = "DejaVuSansMono-Bold.ttf" if bold else "DejaVuSansMono.ttf"
        else:
            fname = "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
        fpath = ttf_dir / fname
        if fpath.exists():
            return ImageFont.truetype(str(fpath), size=size)
    except Exception:
        pass
    return ImageFont.load_default()


def _select_display_canaries(all_canaries: list[dict[str, Any]], max_cols: int = 12) -> list[dict[str, Any]]:
    if len(all_canaries) <= max_cols:
        return list(all_canaries)
    leaked_idx = [i for i, c in enumerate(all_canaries) if c.get("leaked_variant")]
    if len(leaked_idx) >= max_cols:
        chosen = set(leaked_idx[:max_cols])
    else:
        chosen = set(leaked_idx)
        rem = [i for i in range(len(all_canaries)) if i not in chosen]
        need = max_cols - len(chosen)
        if need > 0 and rem:
            for k in range(need):
                pos = int(round(k * (len(rem) - 1) / max(1, need - 1))) if need > 1 else len(rem) - 1
                chosen.add(rem[pos])
            idx_scan = 0
            while len(chosen) < max_cols and idx_scan < len(rem):
                chosen.add(rem[idx_scan])
                idx_scan += 1
    return [all_canaries[i] for i in sorted(chosen)]


def collect_soc_observations(
    env: Any,
    probe_days: int | None = None,
    horizon_days: int | None = None,
    seed_label: int | None = None,
    tier: str | None = None,
) -> dict[str, Any]:
    from canary.rules import tier_params

    emp_res = env.call("list_employees", {})
    if not emp_res.ok:
        raise RuntimeError(f"list_employees failed: {emp_res.error}")
    employees = [dict(e) for e in emp_res.data["employees"]]
    ids = [e["id"] for e in employees]

    resolved_tier = (tier or ("hard" if len(employees) >= 30 else "medium")).strip().lower()
    tp = tier_params(resolved_tier)

    planted_order: list[str] = []
    planted_assignments: dict[str, dict[str, str]] = {}
    planted_variants: dict[str, dict[str, list[str]]] = {}
    seen_canary_leaks: set[str] = set()
    labels = ("A", "B", "C")
    closed_day = 0

    if resolved_tier == "medium" and tp.canaries_per_day == 1 and tp.fingerprint_accuracy >= 1.0:
        p_days = 12 if probe_days is None else probe_days
        h_days = 13 if horizon_days is None else horizon_days
        suspects = list(ids)
        half_rounds = [0, 0]

        for day in range(1, h_days + 1):
            feed_res = env.call("check_leak_feed", {})
            if feed_res.ok:
                for item in feed_res.data.get("items", []):
                    cid = item.get("doc_id", "")
                    var = item.get("variant")
                    if cid in planted_variants and var and cid not in seen_canary_leaks:
                        seen_canary_leaks.add(cid)
                        grp = planted_variants[cid].get(var, [])
                        inter = [x for x in suspects if x in grp]
                        if inter:
                            suspects = inter

            if day <= p_days and len(ids) >= 2:
                if len(suspects) < len(ids):
                    target = list(suspects)
                    if len(target) == 1:
                        other = next(x for x in ids if x != target[0])
                        asg = {target[0]: "A", other: "B"}
                    else:
                        stride = 1 if (day % 2 == 1) else max(1, (len(target) + 2) // 3)
                        n_var = min(3, len(target))
                        asg = {e: labels[(j // stride) % n_var] for j, e in enumerate(target)}
                else:
                    half_idx = (day - 1) % 2
                    half_n = max(1, len(ids) // 2)
                    start = half_idx * half_n
                    end = len(ids) if half_idx == 1 else half_n
                    target = ids[start:end]
                    r_idx = half_rounds[half_idx]
                    half_rounds[half_idx] += 1
                    n_var = min(3, len(target))
                    if r_idx % 2 == 0:
                        asg = {e: labels[j % n_var] for j, e in enumerate(target)}
                    else:
                        asg = {e: labels[(j // 3) % n_var] for j, e in enumerate(target)}

                c_res = env.call("plant_canary", {"doc_title": f"SOC Probe {day}", "assignment": asg})
                if c_res.ok:
                    cid = c_res.data["canary_id"]
                    planted_order.append(cid)
                    planted_assignments[cid] = dict(asg)
                    vmap: dict[str, list[str]] = {}
                    for eid, lab in sorted(asg.items()):
                        vmap.setdefault(lab, []).append(eid)
                    planted_variants[cid] = vmap

            adv_res = env.call("advance_day", {})
            if not adv_res.ok:
                break
            closed_day = int(adv_res.data.get("closed_day", day))
            if adv_res.data.get("episode_over"):
                break

        final_feed_res = env.call("check_leak_feed", {})
        surfaced_items = [dict(x) for x in (final_feed_res.data.get("items", []) if final_feed_res.ok else [])]
        surfaced_by_doc = {it["doc_id"]: it for it in surfaced_items}
        final_narrowed = list(ids)
        for cid in planted_order:
            leak_item = surfaced_by_doc.get(cid)
            leaked_var = leak_item.get("variant") if leak_item else None
            if leaked_var:
                grp = planted_variants[cid].get(leaked_var, [])
                inter = [x for x in final_narrowed if x in grp]
                if inter:
                    final_narrowed = inter
    else:
        h_days = max(1, tp.n_days - 1) if horizon_days is None else horizon_days
        p_days = max(1, h_days - min(tp.delay_choices) + 1) if probe_days is None else probe_days
        alive = {e: True for e in ids}
        weights = {e: 1.0 for e in ids}
        round_c = 0
        fp_acc = float(tp.fingerprint_accuracy)

        def _ingest_items(items: list[dict[str, Any]]) -> None:
            for item in items:
                cid = item.get("doc_id", "")
                var = item.get("variant")
                if cid in planted_assignments and var and cid not in seen_canary_leaks:
                    seen_canary_leaks.add(cid)
                    asg_map = planted_assignments[cid]
                    k_var = max(2, len(set(asg_map.values())))
                    for eid in ids:
                        if eid not in asg_map:
                            alive[eid] = False
                            weights[eid] = 0.0
                        elif alive[eid]:
                            if fp_acc >= 1.0:
                                if asg_map[eid] != var:
                                    alive[eid] = False
                                    weights[eid] = 0.0
                            else:
                                weights[eid] *= fp_acc if asg_map[eid] == var else (1.0 - fp_acc) / (k_var - 1)

        for day in range(1, h_days + 1):
            feed_res = env.call("check_leak_feed", {})
            if feed_res.ok:
                _ingest_items(feed_res.data.get("items", []))

            if day <= p_days and len(ids) >= 2:
                alive_ids = sorted([e for e in ids if alive[e]], key=lambda x: (-weights[x], ids.index(x)))
                if not alive_ids:
                    alive_ids = list(ids)
                if tp.canaries_per_day >= 2:
                    if len(alive_ids) >= 4:
                        half = (len(alive_ids) + 1) // 2
                        batches = [alive_ids[:half], alive_ids[half:]]
                    else:
                        batches = [list(alive_ids), list(alive_ids)]
                else:
                    batches = [list(alive_ids)]

                for b_idx, target in enumerate(batches[: tp.canaries_per_day]):
                    if not target:
                        continue
                    if len(target) == 1:
                        other = next(x for x in ids if x != target[0])
                        asg = {target[0]: "A", other: "B"}
                    else:
                        n_var = min(tp.max_variants, len(target))
                        mode = (round_c + b_idx) % 3
                        if mode == 0:
                            asg = {e: labels[(j + b_idx) % n_var] for j, e in enumerate(target)}
                        elif mode == 1:
                            stride = max(1, (len(target) + 2) // 3)
                            asg = {e: labels[(j // stride) % n_var] for j, e in enumerate(target)}
                        else:
                            stride = max(1, (len(target) + 5) // 6)
                            asg = {e: labels[((j // stride) + b_idx) % n_var] for j, e in enumerate(target)}

                    title = f"SOC Probe {day}-{b_idx + 1}" if tp.canaries_per_day > 1 else f"SOC Probe {day}"
                    c_res = env.call("plant_canary", {"doc_title": title, "assignment": asg})
                    if c_res.ok:
                        cid = c_res.data["canary_id"]
                        planted_order.append(cid)
                        planted_assignments[cid] = dict(asg)
                        vmap = {}
                        for eid, lab in sorted(asg.items()):
                            vmap.setdefault(lab, []).append(eid)
                        planted_variants[cid] = vmap
                round_c += 1

            adv_res = env.call("advance_day", {})
            if not adv_res.ok:
                break
            closed_day = int(adv_res.data.get("closed_day", day))
            if adv_res.data.get("episode_over"):
                break

        final_feed_res = env.call("check_leak_feed", {})
        surfaced_items = [dict(x) for x in (final_feed_res.data.get("items", []) if final_feed_res.ok else [])]
        _ingest_items(surfaced_items)
        surfaced_by_doc = {it["doc_id"]: it for it in surfaced_items}
        alive_sorted = sorted([e for e in ids if alive[e]], key=lambda x: (-weights[x], ids.index(x)))
        max_w = max((weights[e] for e in alive_sorted), default=0.0)
        final_narrowed = [e for e in alive_sorted if max_w > 0 and weights[e] >= 0.2 * max_w] or alive_sorted or list(ids)

    log_day_to = max(1, closed_day)
    logs_res = env.call("read_access_logs", {"day_from": 1, "day_to": log_day_to})
    logs = [dict(r) for r in (logs_res.data.get("logs", []) if logs_res.ok else [])]

    canaries = []
    for cid in planted_order:
        leak_item = surfaced_by_doc.get(cid)
        leaked_var = leak_item.get("variant") if leak_item else None
        surfaced_day = leak_item.get("surfaced_day") if leak_item else None
        canaries.append({
            "canary_id": cid,
            "assignment": planted_assignments[cid],
            "variants": planted_variants[cid],
            "leaked_variant": leaked_var,
            "surfaced_day": surfaced_day,
        })

    regular_leaks = [
        {"doc_id": it["doc_id"], "title": it.get("title", ""), "surfaced_day": it.get("surfaced_day", 0)}
        for it in surfaced_items
        if it["doc_id"] not in planted_assignments
    ]

    ah_score: dict[str, int] = {e: 0 for e in ids}
    ah_counts: dict[str, int] = {e: 0 for e in ids}
    tot_counts: dict[str, int] = {e: 0 for e in ids}
    for row in logs:
        e = row["employee"]
        if e in tot_counts:
            tot_counts[e] += 1
            if row.get("after_hours"):
                ah_counts[e] += 1
            ah_score[e] += 1 + 10 * int(bool(row.get("after_hours")))
    naive_most_logs_id = max(ids, key=lambda e: (ah_score[e], ah_counts[e], -ids.index(e))) if ids else ""

    return {
        "tier": resolved_tier,
        "n_days": tp.n_days,
        "fingerprint_accuracy": tp.fingerprint_accuracy,
        "seed_label": seed_label,
        "closed_day": log_day_to,
        "employees": employees,
        "logs": logs,
        "canaries": canaries,
        "regular_leaks": regular_leaks,
        "surfaced_items": surfaced_items,
        "canary_narrowed_candidates": final_narrowed,
        "naive_most_after_hours_id": naive_most_logs_id,
    }


def render_soc_raster(obs: dict[str, Any]) -> bytes:
    tier_name = str(obs.get("tier", "medium")).strip().lower()
    employees = obs["employees"]
    ids = [e["id"] for e in employees]
    dept_by_emp = {e["id"]: e.get("dept", "") for e in employees}
    closed_day = int(obs.get("closed_day", 13))
    is_hard_layout = tier_name != "medium" or len(employees) > 20 or closed_day > 13

    logs = obs.get("logs", [])
    all_canaries = obs.get("canaries", [])
    canaries = _select_display_canaries(all_canaries, max_cols=12) if is_hard_layout else all_canaries[:12]
    all_leaked_canaries = [c for c in (all_canaries if is_hard_layout else canaries) if c.get("leaked_variant")]
    regular_leaks = obs.get("regular_leaks", [])[:8]
    fp_acc = float(obs.get("fingerprint_accuracy", 0.95 if is_hard_layout else 1.0))

    n_emp = len(employees)
    width = 2180 if is_hard_layout else 1880
    row_h = 34 if is_hard_layout else 36
    ty = 9 if is_hard_layout else 10
    y_rows = 154
    height = y_rows + max(1, n_emp) * row_h + 146

    img = Image.new("RGB", (width, height), (11, 16, 27))
    draw = ImageDraw.Draw(img)

    f_title = _load_font(18, bold=True, mono=False)
    f_sub = _load_font(13, bold=False, mono=True)
    f_panel = _load_font(14, bold=True, mono=False)
    f_hdr = _load_font(11, bold=True, mono=True)
    f_row_id = _load_font(13, bold=True, mono=True)
    f_cell = _load_font(11, bold=True, mono=True)
    f_small = _load_font(10, bold=False, mono=True)
    f_leg = _load_font(12, bold=False, mono=False)

    day_tot: dict[tuple[str, int], int] = {}
    day_ah: dict[tuple[str, int], int] = {}
    emp_tot: dict[str, int] = {e: 0 for e in ids}
    emp_ah: dict[str, int] = {e: 0 for e in ids}
    doc_emp_opens: dict[tuple[str, str], int] = {}
    doc_depts: dict[str, set[str]] = {}

    for r in logs:
        e = r["employee"]
        d = int(r["day"])
        doc_id = r["doc_id"]
        is_ah = bool(r.get("after_hours"))
        day_tot[(e, d)] = day_tot.get((e, d), 0) + 1
        if is_ah:
            day_ah[(e, d)] = day_ah.get((e, d), 0) + 1
        if e in emp_tot:
            emp_tot[e] += 1
            if is_ah:
                emp_ah[e] += 1
        doc_emp_opens[(e, doc_id)] = doc_emp_opens.get((e, doc_id), 0) + 1
        if e in dept_by_emp:
            doc_depts.setdefault(doc_id, set()).add(dept_by_emp[e])

    total_logs = sum(emp_tot.values())
    total_ah = sum(emp_ah.values())
    n_leaked_canaries = len(all_leaked_canaries)
    seed_txt = f"SEED {obs['seed_label']}" if obs.get("seed_label") is not None else "OBSERVABLE TELEMETRY"
    fp_pct = int(round(100 * fp_acc))

    draw.rounded_rectangle((16, 12, width - 16, 76), radius=8, fill=(19, 28, 46), outline=(45, 65, 98), width=1)
    if is_hard_layout:
        n_days_horizon = int(obs.get("n_days", closed_day + 1))
        title_str = (
            f"CANARY SECURITY-SOC EVIDENCE RASTER | {tier_name.upper()} TIER (v1.4) | "
            f"{seed_txt} | DAY {n_days_horizon} (LOGS D01-D{closed_day:02d}, {fp_pct}% FP)"
        )
        sub_str = (
            f"STAFF: {n_emp}   ACCESS LOGS: {total_logs} (AFTER-HOURS: {total_ah})   "
            f"CANARIES PLANTED: {len(all_canaries)} (SURFACED: {n_leaked_canaries}, SHOWN: {len(canaries)})   "
            f"SURFACED REGULAR LEAKS: {len(regular_leaks)}"
        )
    else:
        title_str = f"CANARY SECURITY-SOC EVIDENCE RASTER | MEDIUM TIER (v1.4) | {seed_txt} | DAYS 1-{closed_day}"
        sub_str = (
            f"STAFF: {n_emp}   ACCESS LOGS: {total_logs} (AFTER-HOURS: {total_ah})   "
            f"CANARIES PLANTED: {len(canaries)} (SURFACED: {n_leaked_canaries})   "
            f"SURFACED REGULAR LEAKS: {len(regular_leaks)}"
        )
    draw.text((30, 20), title_str, fill=(236, 242, 252), font=f_title)
    draw.text((30, 47), sub_str, fill=(148, 172, 208), font=f_sub)

    x_id = 20
    x_pa = 128 if is_hard_layout else 158
    cw_a, step_a = (32, 34) if is_hard_layout else (34, 36)
    n_days = max(1, min(closed_day, 20 if is_hard_layout else 13))
    x_ah_bar = x_pa + n_days * step_a + 8

    x_pb_id = 990 if is_hard_layout else 830
    x_pb = 1030 if is_hard_layout else 870
    cw_b, step_b = (40, 42) if is_hard_layout else (34, 36)
    n_can_cols = max(1, len(canaries))
    x_can_sum = x_pb + n_can_cols * step_b + 6

    x_pc_id = 1680 if is_hard_layout else 1424
    x_pc = 1720 if is_hard_layout else 1464
    cw_c, step_c = 38, 40
    n_reg_cols = max(1, len(regular_leaks))
    x_reg_sum = x_pc + n_reg_cols * step_c + 6

    pb_title = (
        f"PANEL B: CANARY PARTITIONS & {fp_pct}% SURFACED VARIANTS"
        if is_hard_layout
        else "PANEL B: CANARY PARTITIONS & SURFACED VARIANTS"
    )
    draw.text((x_pa, 88), "PANEL A: DAILY ACCESS & AFTER-HOURS FRAMING SPIKES", fill=(125, 195, 255), font=f_panel)
    draw.text((x_pb_id, 88), pb_title, fill=(110, 240, 185), font=f_panel)
    draw.text((x_pc_id, 88), "PANEL C: SURFACED REGULAR-LEAK CORRELATION", fill=(250, 200, 95), font=f_panel)

    draw.text((x_id + 4, 126), "EMP   DEPT", fill=(155, 170, 195), font=f_hdr)
    for d in range(1, n_days + 1):
        cx = x_pa + (d - 1) * step_a
        draw.text((cx + (4 if is_hard_layout else 5), 126), f"D{d:02d}", fill=(155, 170, 195), font=f_hdr)
    draw.text((x_ah_bar + 4, 126), "AFTER-HRS / TOT", fill=(248, 130, 135), font=f_hdr)

    draw.text((x_pb_id + 2, 126), "EMP", fill=(155, 170, 195), font=f_hdr)
    for idx, c in enumerate(canaries):
        cx = x_pb + idx * step_b
        cid_short = c["canary_id"][: (5 if is_hard_layout else 4)]
        lv = c.get("leaked_variant")
        if lv:
            draw.rounded_rectangle((cx, 112, cx + cw_b, 148), radius=4, fill=(16, 125, 84), outline=(105, 245, 185), width=1)
            draw.text((cx + 4, 114), cid_short, fill=(235, 255, 245), font=f_small)
            draw.text((cx + (8 if is_hard_layout else 5), 130), f"={lv}!", fill=(255, 255, 255), font=f_hdr)
        else:
            draw.text((cx + 4, 116), cid_short, fill=(135, 150, 175), font=f_small)
            draw.text((cx + (11 if is_hard_layout else 8), 131), "--", fill=(90, 105, 130), font=f_small)
    draw.text((x_can_sum + 4, 126), "MATCH / HELD" if is_hard_layout else "MATCH", fill=(110, 240, 185), font=f_hdr)

    draw.text((x_pc_id + 2, 126), "EMP", fill=(155, 170, 195), font=f_hdr)
    if regular_leaks:
        for idx, rl in enumerate(regular_leaks):
            cx = x_pc + idx * step_c
            did = rl["doc_id"][:5]
            sday = rl.get("surfaced_day", 0)
            draw.text((cx + 2, 115), did, fill=(245, 205, 115), font=f_small)
            draw.text((cx + 4, 130), f"@d{sday}", fill=(155, 145, 115), font=f_small)
    else:
        draw.text((x_pc + 4, 126), "NONE", fill=(110, 120, 140), font=f_hdr)
    draw.text((x_reg_sum + 2, 126), "CORR", fill=(250, 200, 95), font=f_hdr)

    dept_colors = {
        "Engineering": ((32, 68, 108), (150, 205, 255), "ENG"),
        "Finance": ((36, 84, 68), (155, 235, 195), "FIN"),
        "Sales": ((96, 62, 32), (255, 205, 145), "SAL"),
        "Legal": ((78, 48, 98), (220, 175, 250), "LEG"),
        "Research": ((38, 82, 92), (155, 230, 240), "RES"),
    }

    max_tot = max([1] + [emp_tot[e] for e in ids])

    for r_idx, emp in enumerate(employees):
        eid = emp["id"]
        dept = emp.get("dept", "")
        ry = y_rows + r_idx * row_h
        cy0, cy1 = ry + 3, ry + row_h - 3

        band_bg = (16, 23, 38) if (r_idx % 2 == 0) else (22, 31, 50)
        draw.rectangle((16, ry, width - 16, ry + row_h - 1), fill=band_bg)
        draw.line((16, ry + row_h - 1, width - 16, ry + row_h - 1), fill=(30, 42, 66), width=1)

        draw.text((x_id + 4, ry + ty), eid, fill=(238, 244, 255), font=f_row_id)
        d_bg, d_fg, d_tag = dept_colors.get(dept, ((45, 55, 75), (200, 210, 225), dept[:3].upper()))
        bx_d0 = x_id + (46 if is_hard_layout else 48)
        draw.rounded_rectangle((bx_d0, cy0 + 2, bx_d0 + 48, cy1 - 2), radius=4, fill=d_bg)
        draw.text((bx_d0 + 10, ry + ty + 1), d_tag, fill=d_fg, font=f_cell)

        for d in range(1, n_days + 1):
            cx0 = x_pa + (d - 1) * step_a
            cx1 = cx0 + cw_a
            tot = day_tot.get((eid, d), 0)
            ah = day_ah.get((eid, d), 0)
            if tot == 0:
                draw.rounded_rectangle((cx0, cy0, cx1, cy1), radius=3, fill=(14, 20, 33), outline=(28, 39, 60), width=1)
            elif ah == 0:
                lvl = min(tot, 4)
                fill_c = (24 + 8 * lvl, 54 + 18 * lvl, 96 + 26 * lvl)
                draw.rounded_rectangle((cx0, cy0, cx1, cy1), radius=3, fill=fill_c, outline=(62, 112, 175), width=1)
                draw.text((cx0 + (12 if is_hard_layout else 13), ry + ty), str(tot), fill=(220, 236, 255), font=f_cell)
            else:
                fill_c = (192, 46, 58) if ah == 1 else (238, 56, 64)
                out_c = (248, 125, 130) if ah == 1 else (255, 195, 165)
                draw.rounded_rectangle((cx0, cy0, cx1, cy1), radius=3, fill=fill_c, outline=out_c, width=1)
                lbl = f"{ah}!/{tot}"
                draw.text((cx0 + (2 if is_hard_layout else 3), ry + ty + 1), lbl, fill=(255, 250, 250), font=f_small)

        tot_e = emp_tot[eid]
        ah_e = emp_ah[eid]
        reg_e = max(0, tot_e - ah_e)
        bar_max_w = 92 if is_hard_layout else 96
        bx0 = x_ah_bar + 2
        draw.rounded_rectangle((bx0, cy0 + 4, bx0 + bar_max_w, cy1 - 4), radius=3, fill=(14, 20, 33), outline=(32, 44, 68), width=1)
        w_reg = int(round((reg_e / max_tot) * bar_max_w))
        w_ah = int(round((ah_e / max_tot) * bar_max_w))
        if w_reg > 0:
            draw.rectangle((bx0 + 1, cy0 + 5, min(bx0 + bar_max_w - 1, bx0 + w_reg), cy1 - 5), fill=(48, 108, 182))
        if w_ah > 0:
            s_x = bx0 + max(1, w_reg)
            e_x = min(bx0 + bar_max_w - 1, s_x + max(3, w_ah))
            draw.rectangle((s_x, cy0 + 5, e_x, cy1 - 5), fill=(242, 62, 68))
        ah_thresh = 10 if is_hard_layout else 5
        ah_txt_color = (255, 115, 120) if ah_e >= ah_thresh else (185, 198, 220)
        draw.text((bx0 + bar_max_w + 8, ry + ty), f"{ah_e:2d}/{tot_e:2d}", fill=ah_txt_color, font=f_cell)

        draw.text((x_pb_id + 2, ry + ty), eid, fill=(205, 218, 240), font=f_cell)
        c_hits = 0
        for idx, c in enumerate(canaries):
            cx0 = x_pb + idx * step_b
            cx1 = cx0 + cw_b
            emp_var = c["assignment"].get(eid)
            lv = c.get("leaked_variant")
            if lv is None:
                if emp_var:
                    draw.rounded_rectangle((cx0, cy0, cx1, cy1), radius=3, fill=(31, 43, 68), outline=(52, 70, 105), width=1)
                    draw.text((cx0 + (16 if is_hard_layout else 13), ry + ty), emp_var, fill=(155, 175, 210), font=f_cell)
                else:
                    draw.rounded_rectangle((cx0, cy0, cx1, cy1), radius=3, fill=(14, 20, 33), outline=(26, 36, 55), width=1)
                    draw.text((cx0 + (17 if is_hard_layout else 14), ry + ty), ".", fill=(65, 78, 102), font=f_cell)
            else:
                if emp_var == lv:
                    c_hits += 1
                    draw.rounded_rectangle((cx0, cy0, cx1, cy1), radius=3, fill=(16, 160, 104), outline=(120, 255, 195), width=2)
                    draw.text((cx0 + (9 if is_hard_layout else 6), ry + ty), f"[{emp_var}]", fill=(255, 255, 255), font=f_cell)
                elif emp_var is not None and fp_acc < 1.0:
                    draw.rounded_rectangle((cx0, cy0, cx1, cy1), radius=3, fill=(72, 58, 22), outline=(195, 155, 58), width=1)
                    draw.text((cx0 + 12, ry + ty), f"~{emp_var}", fill=(248, 216, 128), font=f_cell)
                else:
                    draw.rounded_rectangle((cx0, cy0, cx1, cy1), radius=3, fill=(40, 24, 36), outline=(78, 44, 62), width=1)
                    draw.line((cx0 + 3, cy1 - 3, cx1 - 3, cy0 + 3), fill=(115, 58, 76), width=1)
                    sym = emp_var if emp_var else "-"
                    draw.text((cx0 + (16 if is_hard_layout else 13), ry + ty), sym, fill=(125, 88, 102), font=f_cell)

        if is_hard_layout:
            c_hits = sum(1 for c in all_leaked_canaries if c["assignment"].get(eid) == c["leaked_variant"])
            c_held = sum(1 for c in all_leaked_canaries if eid in c["assignment"])
            held_all = (n_leaked_canaries > 0) and (c_held == n_leaked_canaries)
            all_match = held_all and (c_hits == n_leaked_canaries)
            near_match = held_all and (c_hits == n_leaked_canaries - 1) and (fp_acc < 1.0)
            if all_match:
                ms_bg, ms_out, ms_fg = (16, 152, 98), (120, 255, 195), (255, 255, 255)
                tag_m = f"ALL {c_hits}/{n_leaked_canaries} H{c_held}"
            elif near_match:
                ms_bg, ms_out, ms_fg = (20, 112, 132), (110, 225, 245), (245, 252, 255)
                tag_m = f"{c_hits}/{n_leaked_canaries} H{c_held}/{n_leaked_canaries}"
            elif held_all:
                ms_bg, ms_out, ms_fg = (34, 54, 84), (78, 112, 160), (205, 222, 245)
                tag_m = f"{c_hits}/{n_leaked_canaries} H{c_held}/{n_leaked_canaries}"
            else:
                ms_bg, ms_out, ms_fg = (26, 35, 54), (45, 60, 88), (135, 150, 176)
                tag_m = f"{c_hits}/{n_leaked_canaries} H{c_held}/{n_leaked_canaries}"
            draw.rounded_rectangle((x_can_sum, cy0, x_can_sum + 118, cy1), radius=4, fill=ms_bg, outline=ms_out, width=1)
            draw.text((x_can_sum + 6, ry + ty), tag_m, fill=ms_fg, font=f_cell)
        else:
            all_match = (n_leaked_canaries > 0) and (c_hits == n_leaked_canaries)
            ms_bg = (16, 152, 98) if all_match else (26, 35, 54)
            ms_out = (120, 255, 195) if all_match else (45, 60, 88)
            ms_fg = (255, 255, 255) if all_match else (150, 165, 190)
            draw.rounded_rectangle((x_can_sum, cy0, x_can_sum + 92, cy1), radius=4, fill=ms_bg, outline=ms_out, width=1)
            tag_m = f"ALL {c_hits}/{n_leaked_canaries}" if all_match else f" {c_hits}/{n_leaked_canaries}"
            draw.text((x_can_sum + 8, ry + ty), tag_m, fill=ms_fg, font=f_cell)

        draw.text((x_pc_id + 2, ry + ty), eid, fill=(205, 218, 240), font=f_cell)
        direct_corr = 0
        dept_corr = 0
        if regular_leaks:
            for idx, rl in enumerate(regular_leaks):
                cx0 = x_pc + idx * step_c
                cx1 = cx0 + cw_c
                did = rl["doc_id"]
                opens = doc_emp_opens.get((eid, did), 0)
                in_dept = dept in doc_depts.get(did, set())
                if opens > 0:
                    direct_corr += 1
                    dept_corr += 1
                    draw.rounded_rectangle((cx0, cy0, cx1, cy1), radius=3, fill=(220, 152, 22), outline=(255, 224, 130), width=1)
                    draw.text((cx0 + 8, ry + ty), f"L{opens}", fill=(20, 16, 8), font=f_cell)
                elif in_dept:
                    dept_corr += 1
                    draw.rounded_rectangle((cx0, cy0, cx1, cy1), radius=3, fill=(86, 64, 24), outline=(152, 116, 46), width=1)
                    draw.text((cx0 + 14, ry + ty), "D", fill=(245, 212, 140), font=f_cell)
                else:
                    draw.rounded_rectangle((cx0, cy0, cx1, cy1), radius=3, fill=(14, 20, 33), outline=(26, 36, 55), width=1)
                    draw.text((cx0 + 15, ry + ty), ".", fill=(65, 78, 102), font=f_cell)
        else:
            draw.rounded_rectangle((x_pc, cy0, x_pc + cw_c, cy1), radius=3, fill=(14, 20, 33), outline=(26, 36, 55), width=1)

        n_rl = len(regular_leaks)
        rc_bg = (135, 96, 22) if (n_rl > 0 and dept_corr == n_rl and direct_corr > 0) else (26, 35, 54)
        rc_fg = (255, 244, 210) if (n_rl > 0 and dept_corr == n_rl and direct_corr > 0) else (165, 178, 202)
        draw.rounded_rectangle((x_reg_sum, cy0, width - 22, cy1), radius=4, fill=rc_bg, outline=(62, 76, 104), width=1)
        draw.text((x_reg_sum + 6, ry + ty), f"L{direct_corr} D{dept_corr}/{n_rl}", fill=rc_fg, font=f_small)

    ly = y_rows + max(1, n_emp) * row_h + 14
    draw.rounded_rectangle((16, ly, width - 16, height - 14), radius=8, fill=(17, 25, 42), outline=(42, 60, 92), width=1)

    draw.rounded_rectangle((30, ly + 14, 52, ly + 32), radius=3, fill=(235, 56, 64), outline=(255, 185, 160), width=1)
    leg_a = (
        "PANEL A RED SPIKE (a!/t): After-hours accesses / day total. Hard framing injects ~2.0 fake after-hours logs/day "
        "(50% concentrated onto one innocent decoy; mole is never framed, mole self after-hours ~30%)."
        if is_hard_layout
        else "PANEL A RED SPIKE (a!/t): After-hours accesses / day total. Framing injects ~1.5 fake after-hours logs/day "
        "(50% on one innocent decoy; mole is never framed)."
    )
    draw.text((62, ly + 15), leg_a, fill=(215, 225, 242), font=f_leg)

    draw.rounded_rectangle((30, ly + 46, 52, ly + 64), radius=3, fill=(16, 160, 104), outline=(120, 255, 195), width=1)
    leg_b = (
        "PANEL B GREEN [V] / AMBER ~V / CROSSED '-': Crossed '-' never received leaked canary (100% cleared, H<K). "
        "Among HK/K holders, [V] matches surfaced variant (95% acc) and ~V is 5% noisy variant flip (~38x odds per match)."
        if is_hard_layout
        else "PANEL B GREEN [V] & ALL K/K: Employee held the surfaced canary variant. Crossed tiles did not hold that "
        "surfaced variant (cleared on medium exact fingerprinting)."
    )
    draw.text((62, ly + 47), leg_b, fill=(215, 225, 242), font=f_leg)

    draw.rounded_rectangle((30, ly + 78, 52, ly + 96), radius=3, fill=(220, 152, 22), outline=(255, 224, 130), width=1)
    draw.text(
        (62, ly + 79),
        "PANEL C GOLD Lk / BRONZE D: Employee directly opened leaked regular doc Lk times in logs, or colleague in "
        "same dept opened it (D = dept received leaked doc).",
        fill=(215, 225, 242),
        font=f_leg,
    )

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def analyze_soc_raster(
    png_bytes: bytes,
    *,
    tier: str = "medium",
    model_id: str = DEFAULT_MODEL,
    sdk_client: Any = None,
    run_id: str = "",
    seed: int | None = None,
    valid_ids: set[str] | None = None,
    max_retries: int | None = None,
    thinking_level: str | None = None,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    from google.genai import types

    if sdk_client is None:
        sdk_client = genai_client()

    retries = int(os.environ.get("CANARY_LLM_MAX_RETRIES", "10")) if max_retries is None else int(max_retries)
    img_sha = raster_sha256(png_bytes)
    image_part = types.Part.from_bytes(data=png_bytes, mime_type="image/png")
    prompt_text = prompt_for_tier(tier)

    tc_kwargs: dict[str, Any] = {"include_thoughts": True}
    if thinking_level:
        tc_kwargs["thinking_level"] = thinking_level.upper()

    cfg = types.GenerateContentConfig(
        response_mime_type="application/json",
        response_json_schema=SOC_VISION_SCHEMA,
        thinking_config=types.ThinkingConfig(**tc_kwargs),
    )

    meta = {"role": FEATURE, "subrole": subrole_for_tier(tier), "tier": tier, "raster_sha256": img_sha}
    if seed is not None:
        meta["seed"] = seed

    attempt = 0
    while True:
        t0 = time.time()
        try:
            resp = sdk_client.models.generate_content(
                model=model_id,
                contents=[image_part, prompt_text],
                config=cfg,
            )
            dt = time.time() - t0
            um = getattr(resp, "usage_metadata", None)
            raw_text = getattr(resp, "text", None) or ""
            if not raw_text.strip():
                cands = getattr(resp, "candidates", None) or []
                if cands and getattr(cands[0], "content", None):
                    parts = getattr(cands[0].content, "parts", None) or []
                    raw_text = "".join(
                        p.text for p in parts if getattr(p, "text", None) and not getattr(p, "thought", False)
                    )
            if not raw_text.strip():
                record(
                    FEATURE,
                    model_id,
                    kind="generate",
                    usage=um,
                    latency_s=dt,
                    ok=False,
                    error="EmptyResponseError: empty JSON response text",
                    run_id=run_id,
                    meta=meta,
                )
                raise LLMError("EmptyResponseError: empty JSON response text from vision call")
            parsed = json.loads(raw_text)
            ledger_row = record(
                FEATURE,
                model_id,
                kind="generate",
                usage=um,
                latency_s=dt,
                ok=True,
                run_id=run_id,
                meta=meta,
            )
            break
        except Exception as exc:
            dt = time.time() - t0
            if not isinstance(exc, LLMError):
                record(
                    FEATURE,
                    model_id,
                    kind="generate",
                    usage=None,
                    latency_s=dt,
                    ok=False,
                    error=f"{type(exc).__name__}: {exc}",
                    run_id=run_id,
                    meta=meta,
                )
            retryable = is_retryable(exc) or isinstance(exc, (LLMError, json.JSONDecodeError))
            if attempt >= retries or not retryable:
                raise
            delay = min(1.5 * (2 ** attempt), 45.0) * (1.0 + 0.1 * random.random())
            attempt += 1
            sleep_fn(delay)

    top_suspects = _normalize_emp_ids(parsed.get("top_suspect_ids", []), valid_ids=valid_ids)
    suspected_decoys = _normalize_emp_ids(parsed.get("suspected_decoy_ids", []), valid_ids=valid_ids)
    confidence = float(parsed.get("confidence", 0.0))
    canary_summary = _sanitize_text(str(parsed.get("canary_leak_summary", "")))
    reasoning = _sanitize_text(str(parsed.get("visual_reasoning", "")))

    return {
        "prediction": {
            "top_suspect_ids": top_suspects,
            "suspected_decoy_ids": suspected_decoys,
            "confidence": round(max(0.0, min(1.0, confidence)), 4),
            "canary_leak_summary": canary_summary,
            "visual_reasoning": reasoning,
        },
        "usage": {
            "in": ledger_row["in"],
            "out": ledger_row["out"],
            "thinking": ledger_row["thinking"],
            "cached": ledger_row["cached"],
            "cost_usd": ledger_row["cost_usd"],
            "latency_s": ledger_row["latency_s"],
        },
        "model_version": getattr(resp, "model_version", None) or model_id,
        "raster_sha256": img_sha,
    }


def evaluate_world_seed(
    seed: int,
    *,
    tier: str = "medium",
    model_id: str = DEFAULT_MODEL,
    sdk_client: Any = None,
    run_id: str = "",
    out_raster_path: Path | None = None,
    max_retries: int | None = None,
    thinking_level: str | None = None,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    from canary.env import Env
    from canary.rules import TIERS_VERSION

    env = Env(tier, seed)

    class _PublicEnvProxy:
        def call(self, tool: str, args: dict[str, Any]):
            return env.call(tool, args)

    obs = collect_soc_observations(_PublicEnvProxy(), seed_label=seed, tier=tier)
    png_bytes = render_soc_raster(obs)
    sha = raster_sha256(png_bytes)

    with Image.open(io.BytesIO(png_bytes)) as im:
        width, height = im.size

    if out_raster_path is not None:
        out_raster_path.parent.mkdir(parents=True, exist_ok=True)
        out_raster_path.write_bytes(png_bytes)

    valid_ids = {e["id"] for e in obs["employees"]}
    vision_res = analyze_soc_raster(
        png_bytes,
        tier=tier,
        model_id=model_id,
        sdk_client=sdk_client,
        run_id=run_id,
        seed=seed,
        valid_ids=valid_ids,
        max_retries=max_retries,
        thinking_level=thinking_level,
        sleep_fn=sleep_fn,
    )

    true_mole = env._world.mole
    true_decoy = env._world.decoy
    pred = vision_res["prediction"]
    top_suspects = pred["top_suspect_ids"]
    suspected_decoys = pred["suspected_decoy_ids"]
    naive_id = obs["naive_most_after_hours_id"]

    top1_mole = bool(top_suspects) and top_suspects[0] == true_mole
    top3_mole = true_mole in top_suspects[:3]
    top1_decoy = bool(suspected_decoys) and suspected_decoys[0] == true_decoy
    decoy_hit = true_decoy in suspected_decoys if true_decoy is not None else False
    avoided_trap = (not top_suspects) or (top_suspects[0] != true_decoy)

    total_ah = sum(1 for r in obs["logs"] if r.get("after_hours"))
    surfaced_canaries = [c for c in obs["canaries"] if c.get("leaked_variant")]

    return {
        "seed": seed,
        "tier": tier,
        "tiers_version": TIERS_VERSION,
        "raster_sha256": sha,
        "raster_bytes": len(png_bytes),
        "raster_size": [width, height],
        "observable_summary": {
            "n_employees": len(obs["employees"]),
            "closed_day": obs["closed_day"],
            "total_access_events": len(obs["logs"]),
            "total_after_hours_events": total_ah,
            "n_canaries_planted": len(obs["canaries"]),
            "n_surfaced_canary_leaks": len(surfaced_canaries),
            "n_surfaced_regular_leaks": len(obs["regular_leaks"]),
            "canary_narrowed_candidates": obs["canary_narrowed_candidates"],
            "naive_most_after_hours_id": naive_id,
        },
        "model_output": pred,
        "ground_truth": {
            "true_mole": true_mole,
            "true_decoy": true_decoy,
        },
        "evaluation": {
            "top1_mole_correct": top1_mole,
            "top3_mole_hit": top3_mole,
            "top1_decoy_correct": top1_decoy,
            "decoy_identified": decoy_hit,
            "avoided_framing_trap": avoided_trap,
            "naive_baseline_mole_correct": naive_id == true_mole,
            "naive_baseline_trapped_by_decoy": naive_id == true_decoy,
        },
        "usage": vision_res["usage"],
        "model_version": vision_res["model_version"],
    }
