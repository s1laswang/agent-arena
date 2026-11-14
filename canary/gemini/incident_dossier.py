from __future__ import annotations

import hashlib
import io
import json
import math
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
SUBROLE = "multi_image_incident_dossier"
VALID_VARIANTS = ("A", "B", "C", "D", "E", "F", "G", "H")

VARIANT_PALETTE: dict[str, tuple[tuple[int, int, int], tuple[int, int, int]]] = {
    "A": ((18, 128, 82), (226, 250, 238)),
    "B": ((26, 92, 184), (228, 240, 255)),
    "C": ((186, 52, 42), (255, 234, 230)),
    "D": ((132, 56, 168), (245, 232, 254)),
    "E": ((184, 118, 18), (255, 244, 224)),
    "F": ((18, 132, 148), (226, 248, 252)),
    "G": ((164, 42, 108), (254, 232, 244)),
    "H": ((62, 88, 122), (232, 238, 248)),
}

MATRIX_VARIANT_STYLE: dict[str, tuple[tuple[int, int, int], tuple[int, int, int], tuple[int, int, int]]] = {
    "A": ((18, 72, 56), (62, 182, 134), (218, 252, 236)),
    "B": ((22, 58, 108), (78, 148, 238), (222, 238, 255)),
    "C": ((96, 38, 42), (214, 96, 92), (255, 228, 226)),
}

DEPT_STYLE: dict[str, tuple[tuple[int, int, int], tuple[int, int, int], str]] = {
    "Engineering": ((28, 62, 102), (148, 204, 255), "ENG"),
    "Finance": ((28, 78, 62), (150, 234, 194), "FIN"),
    "Sales": ((92, 58, 28), (255, 204, 142), "SAL"),
    "Legal": ((72, 44, 94), (218, 174, 250), "LEG"),
    "Research": ((32, 76, 88), (152, 228, 242), "RES"),
}

INCIDENT_DOSSIER_SCHEMA: dict[str, Any] = {
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
            "description": "Ordered list of framed decoy employee IDs in lowercase e00-e39 format showing anomalous Exhibit 1 after-hours spikes while cleared by Exhibit 2 + Exhibit 3.",
        },
        "confidence": {
            "type": "number",
            "description": "Posterior confidence between 0.0 and 1.0 that top_suspect_ids[0] is the true mole.",
        },
        "decoded_leaked_canaries": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "doc_id": {"type": "string"},
                    "variant": {"type": "string"},
                },
                "required": ["doc_id", "variant"],
            },
            "description": "All intercepted leaked canary memo scans read from Exhibit 2 (Image 2), recording exact doc_id and uppercase COPY-CODE variant A/B/C.",
        },
        "suspect_department": {
            "type": "string",
            "description": "Department clearance zone of top_suspect_ids[0] read from Exhibit 3's corporate floorplan (Engineering, Finance, Sales, Legal, or Research).",
        },
        "cross_image_reasoning": {
            "type": "string",
            "description": "Concise forensic explanation synthesizing Exhibit 2 watermarked scans + Exhibit 3 floorplan and canary matrix + Exhibit 1 badge after-hours spikes. Use plain ASCII hyphens (-), never em dashes.",
        },
    },
    "required": [
        "top_suspect_ids",
        "suspected_decoy_ids",
        "confidence",
        "decoded_leaked_canaries",
        "suspect_department",
        "cross_image_reasoning",
    ],
}

DOSSIER_PROMPT_MEDIUM = (
    "You are a lead corporate counter-intelligence investigator analyzing a 3-image Composite Incident Dossier "
    "from a Canary medium-tier (v1.4, 20 staff e00..e19) leak investigation.\n\n"
    "No single image alone can identify the mole or separate the mole from the framed decoy. You must jointly "
    "cross-reference all THREE PNG exhibits supplied in order:\n"
    "1. Exhibit 1 (Image 1 - Physical Door-Badge & After-Hours Swipe Raster): shows daily vault swipes across closed "
    "days D01..D13 and red after-hours framing spikes per badge e00..e19, with ZERO canary roster or leak-feed data. "
    "In medium tier, benign staff average 10% after-hours and the mole averages 15% after-hours, whereas mole framing "
    "injects ~1.5 fake after-hours badge swipes per day with 50% concentrated onto one innocent decoy employee (and "
    "never onto the mole itself). A dominant red after-hours spike on an employee cleared by Exhibits 2+3 is the "
    "classic signature of the framed decoy.\n"
    "2. Exhibit 2 (Image 2 - Contact Sheet of Intercepted Leaked Canary Memo Scans): shows scanned watermarked canary "
    "memos recovered from the external leak feed, displaying ONLY DOC-ID (c1..c12), SURFACED DAY, header bar segment "
    "count (A=1, B=2, C=3), COPY-CODE stamp, and footer watermark ticks, with ZERO employee IDs.\n"
    "3. Exhibit 3 (Image 3 - Corporate Floorplan, Department Clearance Zones & Static Canary Distribution Matrix): "
    "shows each employee's desk/department clearance zone on the floorplan plus which canary variants (A/B/C) each "
    "employee was issued across c1..c12 before any leaks occurred, with ZERO leak-feed outcomes.\n\n"
    "Cross-reference step by step:\n"
    "- Step A: Read every leaked canary scan's (doc_id, variant) from Exhibit 2 into decoded_leaked_canaries.\n"
    "- Step B: Intersect those exact (doc_id, variant) pairs across Exhibit 3's Canary Distribution Matrix and Issued "
    "Variants Roster (on medium tier, canary variant fingerprinting is 100% exact, so the true mole must hold and "
    "match ALL leaked canary variants) and read the matching employee's department from Exhibit 3's floorplan.\n"
    "- Step C: Inspect Exhibit 1's after-hours swipe raster to confirm the true mole's moderate swipe profile and "
    "identify the primary framed decoy exhibiting the largest red after-hours framing spike despite failing the "
    "Exhibit 2 + Exhibit 3 canary intersection.\n\n"
    "Return JSON matching the schema with lowercase employee IDs (such as e05) and plain ASCII hyphens (-) in text."
)

DOSSIER_PROMPT_HARD = (
    "You are a lead corporate counter-intelligence investigator analyzing a 3-image Composite Incident Dossier "
    "from a Canary hard-tier (v1.4, 40 staff e00..e39) leak investigation.\n\n"
    "No single image alone can identify the mole or separate the mole from the framed decoy. You must jointly "
    "cross-reference all THREE PNG exhibits supplied in order:\n"
    "1. Exhibit 1 (Image 1 - Physical Door-Badge & After-Hours Swipe Raster): shows daily vault swipes across closed "
    "days D01..D20 and red after-hours framing spikes per badge e00..e39, with ZERO canary roster or leak-feed data. "
    "In hard tier, benign staff average 10% after-hours and the mole averages 30% after-hours, whereas mole framing "
    "injects ~2.0 fake after-hours badge swipes per day with 50% concentrated onto one innocent decoy employee (and "
    "never onto the mole itself). A dominant red after-hours spike on an employee cleared by Exhibits 2+3 identifies "
    "the primary framed decoy.\n"
    "2. Exhibit 2 (Image 2 - Contact Sheet of Intercepted Leaked Canary Memo Scans): shows scanned watermarked canary "
    "memos recovered from the external leak feed, displaying ONLY DOC-ID (such as c3, c6-2, c10-2), SURFACED DAY, "
    "header bar segment count (A=1, B=2, C=3), COPY-CODE stamp, and footer watermark ticks, with ZERO employee IDs.\n"
    "3. Exhibit 3 (Image 3 - Corporate Floorplan, Department Clearance Zones & Static Canary Distribution Matrix): "
    "shows the 5-zone corporate security floorplan (Engineering, Finance, Sales, Legal, Research with clearance L1-L3) "
    "plus the static Canary Distribution Matrix and right-side Issued Variants Roster across all 35 planted canaries, "
    "with ZERO leak-feed outcomes.\n\n"
    "Cross-reference step by step:\n"
    "- Step A: Read every leaked canary scan's (doc_id, variant) from Exhibit 2 into decoded_leaked_canaries.\n"
    "- Step B: An employee can ONLY leak a canary they actually received. Intersect the leaked DOC-IDs in Exhibit 3: "
    "any employee who was NOT issued all leaked canary DOC-IDs is 100% cleared. On hard tier, canary variant "
    "fingerprinting is 95% accurate (5% noisy variant flip), so each matching variant among employees who held ALL "
    "leaked canaries multiplies mole odds by ~38x. Read the top suspect's department zone from Exhibit 3's floorplan.\n"
    "- Step C: Cross-check Exhibit 1 to verify the mole's swipe profile and isolate the primary framed decoy showing "
    "the extreme red after-hours framing spike while cleared in Exhibit 3.\n\n"
    "Return JSON matching the schema with lowercase employee IDs (such as e38) and plain ASCII hyphens (-) in text."
)


def sanitize_text(text: str) -> str:
    return (text or "").replace("\u2014", "-").replace("\u2013", "-").strip()


def png_sha256(png_bytes: bytes) -> str:
    return hashlib.sha256(png_bytes).hexdigest()


def prompt_for_tier(tier: str) -> str:
    t = (tier or "medium").strip().lower()
    return DOSSIER_PROMPT_MEDIUM if t in {"easy", "medium"} else DOSSIER_PROMPT_HARD


def seed_tag_for(tier: str, seed: int, multi_tier: bool = True) -> str:
    t = (tier or "medium").strip().lower()
    return f"{t}_{seed}" if multi_tier else str(seed)


def dossier_filenames(seed_tag: str) -> dict[str, str]:
    clean = re.sub(r"[^A-Za-z0-9_\-]", "_", str(seed_tag))
    return {
        "badge_raster": f"badge_raster_seed_{clean}.png",
        "leaked_memo_scans": f"leaked_memo_scans_seed_{clean}.png",
        "org_canary_map": f"org_canary_map_seed_{clean}.png",
    }


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


def _normalize_variant(val: Any) -> str | None:
    if val is None or isinstance(val, bool):
        return None
    raw = str(val).strip().upper()
    if raw in VALID_VARIANTS:
        return raw
    m = re.search(r"\b([A-H])\b", raw)
    return m.group(1) if m else None


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


def build_oblivious_canary_schedule(
    employee_ids: list[str],
    tier: str,
    probe_days: int,
    canaries_per_day: int,
    max_variants: int = 3,
) -> list[dict[str, str]]:
    n = len(employee_ids)
    if n < 2 or probe_days <= 0 or canaries_per_day <= 0:
        return []
    t = (tier or "medium").strip().lower()
    labels = VALID_VARIANTS[: max(2, min(max_variants, len(VALID_VARIANTS)))]
    n_var = len(labels)

    blocks: list[list[int]] = []
    if n == 20 and t == "medium":
        for step, mod in ((5, 4), (1, 4), (2, 4), (3, 4)):
            for rem in range(mod):
                blocks.append([i for i in range(n) if ((i // step) % mod) == rem])
        group_sz = 4
        strides = (1, 2, 3, 1)
        max_total = min(12, probe_days * canaries_per_day)
    elif n == 40 and t in {"hard", "hard_forge"}:
        for step, mod in ((8, 5), (1, 5), (2, 5), (3, 5), (4, 5), (6, 5), (7, 5)):
            for rem in range(mod):
                blocks.append([i for i in range(n) if ((i // step if step == 8 else (i * step) % n) % mod) == rem])
        group_sz = 5
        strides = (1, 3, 2, 4, 1, 3, 2)
        max_total = min(35, probe_days * canaries_per_day)
    else:
        mod = 3 if n >= 9 else 2
        for step in (1, 2, 3, 4, 5, 7):
            for rem in range(mod):
                sub = [i for i in range(n) if ((i // step) % mod) == rem]
                if sub:
                    blocks.append(sub)
        group_sz = mod
        strides = (1, 2, 3)
        max_total = probe_days * canaries_per_day

    schedule: list[dict[str, str]] = []
    for b_ptr in range(max_total):
        sub = blocks[b_ptr % len(blocks)]
        rk = b_ptr // max(1, group_sz)
        st = strides[rk % len(strides)]
        asg = {
            employee_ids[idx]: labels[((pos // st) + rk + b_ptr) % n_var]
            for pos, idx in enumerate(sub)
        }
        schedule.append(asg)
    return schedule


def collect_dossier_observations(
    env: Any,
    *,
    seed_label: int | None = None,
    tier: str | None = None,
    seed_tag: str | None = None,
) -> dict[str, Any]:
    from canary.rules import tier_params

    emp_res = env.call("list_employees", {})
    if not emp_res.ok:
        raise RuntimeError(f"list_employees failed: {emp_res.error}")
    employees = [dict(e) for e in emp_res.data["employees"]]
    ids = [e["id"] for e in employees]

    resolved_tier = (tier or ("hard" if len(employees) >= 30 else "medium")).strip().lower()
    tp = tier_params(resolved_tier)
    h_days = max(1, tp.n_days - 1)
    p_days = 12 if resolved_tier == "medium" else max(1, h_days - min(tp.delay_choices) + 1)

    schedule = build_oblivious_canary_schedule(
        ids,
        resolved_tier,
        probe_days=p_days,
        canaries_per_day=tp.canaries_per_day,
        max_variants=tp.max_variants,
    )

    planted_order: list[str] = []
    planted_assignments: dict[str, dict[str, str]] = {}
    sched_ptr = 0
    closed_day = 0

    for day in range(1, h_days + 1):
        if day <= p_days and sched_ptr < len(schedule):
            for b_idx in range(tp.canaries_per_day):
                if sched_ptr >= len(schedule):
                    break
                asg = schedule[sched_ptr]
                sched_ptr += 1
                title = (
                    f"Dossier Canary {day}-{b_idx + 1}"
                    if tp.canaries_per_day > 1
                    else f"Dossier Canary {day}"
                )
                c_res = env.call("plant_canary", {"doc_title": title, "assignment": asg})
                if c_res.ok:
                    cid = c_res.data["canary_id"]
                    planted_order.append(cid)
                    planted_assignments[cid] = dict(asg)

        adv_res = env.call("advance_day", {})
        if not adv_res.ok:
            break
        closed_day = int(adv_res.data.get("closed_day", day))
        if adv_res.data.get("episode_over"):
            break

    log_day_to = max(1, closed_day)
    logs_res = env.call("read_access_logs", {"day_from": 1, "day_to": log_day_to})
    raw_logs = [dict(r) for r in (logs_res.data.get("logs", []) if logs_res.ok else [])]

    feed_res = env.call("check_leak_feed", {})
    surfaced_items = [dict(x) for x in (feed_res.data.get("items", []) if feed_res.ok else [])]
    surfaced_by_doc = {it["doc_id"]: it for it in surfaced_items}

    planted_canaries: list[dict[str, Any]] = []
    leaked_canary_scans: list[dict[str, Any]] = []
    for cid in planted_order:
        asg = dict(planted_assignments[cid])
        planted_canaries.append({"canary_id": cid, "assignment": asg})
        leak_item = surfaced_by_doc.get(cid)
        lv = _normalize_variant(leak_item.get("variant")) if leak_item else None
        if leak_item and lv is not None:
            leaked_canary_scans.append({
                "doc_id": cid,
                "day_surfaced": int(leak_item.get("surfaced_day", leak_item.get("day_surfaced", 0))),
                "variant": lv,
            })

    badge_logs = [
        {"day": int(r["day"]), "employee": str(r["employee"]), "after_hours": bool(r.get("after_hours"))}
        for r in raw_logs
    ]

    ah_counts = {e: 0 for e in ids}
    tot_counts = {e: 0 for e in ids}
    ah_score = {e: 0 for e in ids}
    for row in badge_logs:
        e = row["employee"]
        if e in tot_counts:
            tot_counts[e] += 1
            if row["after_hours"]:
                ah_counts[e] += 1
            ah_score[e] += 1 + 10 * int(row["after_hours"])
    image1_naive_pick = max(ids, key=lambda e: (ah_score[e], ah_counts[e], -ids.index(e))) if ids else ""

    held_all = [
        e for e in ids
        if all(e in planted_assignments[sc["doc_id"]] for sc in leaked_canary_scans)
    ]
    exact_matches = [
        e for e in held_all
        if all(planted_assignments[sc["doc_id"]].get(e) == sc["variant"] for sc in leaked_canary_scans)
    ]
    if exact_matches:
        canary_candidates = exact_matches
    elif held_all:
        canary_candidates = sorted(
            held_all,
            key=lambda e: (
                -sum(1 for sc in leaked_canary_scans if planted_assignments[sc["doc_id"]].get(e) == sc["variant"]),
                ids.index(e),
            ),
        )
    else:
        canary_candidates = list(ids)

    resolved_tag = seed_tag if seed_tag is not None else (
        f"{resolved_tier}_{seed_label}" if seed_label is not None else resolved_tier
    )
    issued_per_emp = {e: sum(1 for c in planted_canaries if e in c["assignment"]) for e in ids}

    return {
        "tier": resolved_tier,
        "n_days": tp.n_days,
        "fingerprint_accuracy": tp.fingerprint_accuracy,
        "seed_label": seed_label,
        "seed_tag": resolved_tag,
        "closed_day": log_day_to,
        "employees": employees,
        "badge_logs": badge_logs,
        "planted_canaries": planted_canaries,
        "leaked_canary_scans": leaked_canary_scans,
        "issued_counts_set": sorted(set(issued_per_emp.values())),
        "canary_intersection_candidates": canary_candidates,
        "image1_only_naive_pick": image1_naive_pick,
        "image3_only_prior_pick": ids[0] if ids else "",
        "image3_only_uniform_prior": round(1.0 / len(ids), 6) if ids else 0.0,
    }


def build_badge_view(obs: dict[str, Any]) -> dict[str, Any]:
    return {
        "tier": obs["tier"],
        "seed_tag": obs["seed_tag"],
        "closed_day": int(obs["closed_day"]),
        "employee_ids": [str(e["id"]) for e in obs["employees"]],
        "badge_logs": [
            {"day": int(r["day"]), "employee": str(r["employee"]), "after_hours": bool(r["after_hours"])}
            for r in obs["badge_logs"]
        ],
    }


def build_memo_scans_view(obs: dict[str, Any]) -> dict[str, Any]:
    return {
        "tier": obs["tier"],
        "seed_tag": obs["seed_tag"],
        "closed_day": int(obs["closed_day"]),
        "leaked_canary_scans": [
            {
                "doc_id": str(sc["doc_id"]),
                "day_surfaced": int(sc["day_surfaced"]),
                "variant": str(sc["variant"]),
            }
            for sc in obs["leaked_canary_scans"]
        ],
    }


def build_org_map_view(obs: dict[str, Any]) -> dict[str, Any]:
    return {
        "tier": obs["tier"],
        "seed_tag": obs["seed_tag"],
        "employees": [
            {
                "id": str(e["id"]),
                "dept": str(e.get("dept", "")),
                "role": str(e.get("role", "")),
                "clearance": e.get("clearance"),
            }
            for e in obs["employees"]
        ],
        "planted_canaries": [
            {
                "canary_id": str(c["canary_id"]),
                "assignment": {str(k): str(v) for k, v in c["assignment"].items()},
            }
            for c in obs["planted_canaries"]
        ],
    }


def render_badge_raster_png(badge_view: dict[str, Any]) -> bytes:
    tier_name = str(badge_view.get("tier", "medium")).strip().lower()
    seed_tag = sanitize_text(str(badge_view.get("seed_tag", "")))
    ids = [str(x) for x in badge_view["employee_ids"]]
    closed_day = int(badge_view.get("closed_day", 13))
    logs = badge_view.get("badge_logs", [])

    n_emp = len(ids)
    is_hard = tier_name not in {"easy", "medium"} or n_emp > 20 or closed_day > 13
    n_days = max(1, min(closed_day, 20 if is_hard else 13))

    cw, step_x = (42, 44) if is_hard else (46, 48)
    row_h = 34 if is_hard else 36
    ty = 9 if is_hard else 10
    x_id = 24
    x_grid = 96
    x_sum = x_grid + n_days * step_x + 18
    width = x_sum + 536
    y_rows = 152
    height = y_rows + max(1, n_emp) * row_h + 124

    img = Image.new("RGB", (width, height), (11, 16, 27))
    draw = ImageDraw.Draw(img)

    f_title = _load_font(17, bold=True, mono=False)
    f_sub = _load_font(12, bold=False, mono=True)
    f_panel = _load_font(14, bold=True, mono=False)
    f_hdr = _load_font(11, bold=True, mono=True)
    f_row_id = _load_font(13, bold=True, mono=True)
    f_cell = _load_font(11, bold=True, mono=True)
    f_small = _load_font(10, bold=True, mono=True)
    f_leg = _load_font(12, bold=False, mono=False)

    day_tot: dict[tuple[str, int], int] = {}
    day_ah: dict[tuple[str, int], int] = {}
    emp_tot: dict[str, int] = {e: 0 for e in ids}
    emp_ah: dict[str, int] = {e: 0 for e in ids}

    for row in logs:
        e = str(row["employee"])
        d = int(row["day"])
        is_ah = bool(row.get("after_hours"))
        day_tot[(e, d)] = day_tot.get((e, d), 0) + 1
        if is_ah:
            day_ah[(e, d)] = day_ah.get((e, d), 0) + 1
        if e in emp_tot:
            emp_tot[e] += 1
            if is_ah:
                emp_ah[e] += 1

    total_logs = sum(emp_tot.values())
    total_ah = sum(emp_ah.values())
    max_tot = max([1] + [emp_tot[e] for e in ids])
    top_ah_id = max(ids, key=lambda e: (emp_ah[e] * 10 + emp_tot[e], emp_ah[e], -ids.index(e))) if ids else ""

    draw.rounded_rectangle((16, 12, width - 16, 78), radius=8, fill=(19, 28, 46), outline=(45, 65, 98), width=1)
    title = (
        f"DOSSIER EXHIBIT 1 OF 3 | PHYSICAL DOOR-BADGE & AFTER-HOURS SWIPE RASTER | "
        f"{tier_name.upper()} (v1.4) | {seed_tag.upper()}"
    )
    sub = (
        f"BADGES: {n_emp} (e00-e{max(0, n_emp - 1):02d})   CLOSED DAYS: D01-D{n_days:02d}   "
        f"TOTAL VAULT SWIPES: {total_logs}   AFTER-HOURS SWIPES: {total_ah}   "
        f"[NO CANARY ROSTER / NO LEAK FEED]"
    )
    draw.text((28, 20), title, fill=(236, 242, 252), font=f_title)
    draw.text((28, 48), sub, fill=(148, 172, 208), font=f_sub)

    draw.text((x_grid, 90), "DAILY PHYSICAL VAULT SWIPES & RED AFTER-HOURS ANOMALIES", fill=(125, 195, 255), font=f_panel)
    draw.text((x_sum, 90), "CUMULATIVE SWIPE PROFILE & SPIKE FLAG", fill=(252, 132, 138), font=f_panel)

    draw.text((x_id + 2, 126), "BADGE", fill=(160, 176, 202), font=f_hdr)
    for d in range(1, n_days + 1):
        cx = x_grid + (d - 1) * step_x
        draw.text((cx + 8, 126), f"D{d:02d}", fill=(160, 176, 202), font=f_hdr)
    draw.text((x_sum + 2, 126), "BADGE  SWIPE BAR (BLUE=REG, RED=AH)      AH / TOT (%AH)    STATUS", fill=(248, 140, 145), font=f_hdr)

    for r_idx, eid in enumerate(ids):
        ry = y_rows + r_idx * row_h
        cy0, cy1 = ry + 3, ry + row_h - 3
        band_bg = (16, 23, 38) if (r_idx % 2 == 0) else (22, 31, 50)
        draw.rectangle((16, ry, width - 16, ry + row_h - 1), fill=band_bg)
        draw.line((16, ry + row_h - 1, width - 16, ry + row_h - 1), fill=(30, 42, 66), width=1)

        draw.text((x_id + 6, ry + ty), eid, fill=(238, 244, 255), font=f_row_id)

        for d in range(1, n_days + 1):
            cx0 = x_grid + (d - 1) * step_x
            cx1 = cx0 + cw
            tot = day_tot.get((eid, d), 0)
            ah = day_ah.get((eid, d), 0)
            if tot == 0:
                draw.rounded_rectangle((cx0, cy0, cx1, cy1), radius=3, fill=(14, 20, 33), outline=(28, 39, 60), width=1)
            elif ah == 0:
                lvl = min(tot, 4)
                fill_c = (24 + 8 * lvl, 54 + 18 * lvl, 96 + 26 * lvl)
                draw.rounded_rectangle((cx0, cy0, cx1, cy1), radius=3, fill=fill_c, outline=(62, 112, 175), width=1)
                draw.text((cx0 + 16, ry + ty), str(tot), fill=(220, 236, 255), font=f_cell)
            else:
                fill_c = (196, 46, 58) if ah == 1 else (238, 56, 64)
                out_c = (248, 128, 132) if ah == 1 else (255, 198, 168)
                draw.rounded_rectangle((cx0, cy0, cx1, cy1), radius=3, fill=fill_c, outline=out_c, width=1)
                lbl = f"{ah}!/{tot}"
                draw.text((cx0 + 5, ry + ty + 1), lbl, fill=(255, 252, 252), font=f_small)

        draw.text((x_sum + 4, ry + ty), eid, fill=(224, 234, 250), font=f_row_id)
        tot_e = emp_tot[eid]
        ah_e = emp_ah[eid]
        reg_e = max(0, tot_e - ah_e)
        pct_ah = int(round(100.0 * ah_e / max(1, tot_e)))

        bx0 = x_sum + 56
        bar_w = 160
        draw.rounded_rectangle((bx0, cy0 + 4, bx0 + bar_w, cy1 - 4), radius=3, fill=(14, 20, 33), outline=(34, 46, 72), width=1)
        w_reg = int(round((reg_e / max_tot) * bar_w))
        w_ah = int(round((ah_e / max_tot) * bar_w))
        if w_reg > 0:
            draw.rectangle((bx0 + 1, cy0 + 5, min(bx0 + bar_w - 1, bx0 + w_reg), cy1 - 5), fill=(48, 108, 182))
        if w_ah > 0:
            sx = bx0 + max(1, w_reg)
            ex = min(bx0 + bar_w - 1, sx + max(4, w_ah))
            draw.rectangle((sx, cy0 + 5, ex, cy1 - 5), fill=(242, 62, 68))

        is_top_spike = (eid == top_ah_id) and (ah_e >= (8 if is_hard else 6))
        ah_col = (255, 122, 126) if ah_e >= (9 if is_hard else 6) else (192, 206, 228)
        draw.text((bx0 + bar_w + 12, ry + ty), f"{ah_e:2d}/{tot_e:2d} ({pct_ah:2d}% AH)", fill=ah_col, font=f_cell)

        sx_tag = bx0 + bar_w + 150
        if is_top_spike:
            draw.rounded_rectangle((sx_tag, cy0 + 1, sx_tag + 152, cy1 - 1), radius=4, fill=(132, 28, 38), outline=(252, 132, 138), width=1)
            draw.text((sx_tag + 8, ry + ty + 1), "TOP AH SPIKE", fill=(255, 240, 240), font=f_small)
        elif ah_e >= (8 if is_hard else 6):
            draw.rounded_rectangle((sx_tag, cy0 + 1, sx_tag + 152, cy1 - 1), radius=4, fill=(68, 34, 44), outline=(168, 92, 104), width=1)
            draw.text((sx_tag + 8, ry + ty + 1), "ELEVATED AH", fill=(242, 192, 198), font=f_small)

    ly = y_rows + max(1, n_emp) * row_h + 14
    draw.rounded_rectangle((16, ly, width - 16, height - 14), radius=8, fill=(17, 25, 42), outline=(42, 60, 92), width=1)
    draw.rounded_rectangle((30, ly + 16, 52, ly + 34), radius=3, fill=(238, 56, 64), outline=(255, 190, 165), width=1)
    leg_1 = (
        "RED CELL (a!/t): a after-hours swipes out of t total swipes that day. Hard framing injects ~2.0 fake after-hours "
        "swipes/day (50% concentrated onto one innocent decoy; mole self after-hours ~30%, never framed)."
        if is_hard
        else "RED CELL (a!/t): a after-hours swipes out of t total swipes that day. Medium framing injects ~1.5 fake after-hours "
        "swipes/day (50% concentrated onto one innocent decoy; mole self after-hours ~15%, never framed)."
    )
    draw.text((62, ly + 17), leg_1, fill=(216, 226, 244), font=f_leg)
    draw.rounded_rectangle((30, ly + 50, 52, ly + 68), radius=3, fill=(48, 108, 182), outline=(92, 152, 225), width=1)
    draw.text(
        (62, ly + 51),
        "EXHIBIT 1 ISOLATION RULE: Contains NO canary assignments and NO leak feed. Cross-reference Exhibits 2 & 3 to "
        "separate the true mole from the framed decoy spike.",
        fill=(182, 204, 236),
        font=f_leg,
    )

    buf = io.BytesIO()
    img.save(buf, format="PNG", compress_level=6)
    return buf.getvalue()


def _draw_single_memo_card(
    draw: ImageDraw.ImageDraw,
    x0: int,
    y0: int,
    card_w: int,
    card_h: int,
    scan_index: int,
    doc_id: str,
    day_surfaced: int,
    variant: str | None,
    fonts: dict[str, Any],
) -> None:
    norm_var = _normalize_variant(variant)
    v_idx = (VALID_VARIANTS.index(norm_var) + 1) if norm_var is not None else 0

    px0, py0, px1, py1 = x0 + 10, y0 + 8, x0 + card_w - 10, y0 + card_h - 8
    draw.rounded_rectangle((px0, py0, px1, py1), radius=6, fill=(247, 245, 239), outline=(170, 166, 156), width=2)

    for cx, cy, dx, dy in (
        (px0 + 7, py0 + 7, 1, 1),
        (px1 - 7, py0 + 7, -1, 1),
        (px0 + 7, py1 - 7, 1, -1),
        (px1 - 7, py1 - 7, -1, -1),
    ):
        draw.line((cx, cy, cx + 12 * dx, cy), fill=(116, 120, 128), width=2)
        draw.line((cx, cy, cx, cy + 12 * dy), fill=(116, 120, 128), width=2)

    hx0, hy0, hx1, hy1 = px0 + 16, py0 + 16, px1 - 16, py0 + 78
    if norm_var is not None:
        ink, tint = VARIANT_PALETTE[norm_var]
        draw.rounded_rectangle((hx0, hy0, hx1, hy1), radius=5, fill=tint, outline=ink, width=2)
        pat_x0, pat_x1 = hx0 + 10, hx0 + 362
        total_w = pat_x1 - pat_x0
        gap = 6
        seg_w = max(14, (total_w - gap * (v_idx - 1)) // v_idx)
        for s_i in range(v_idx):
            sx0 = pat_x0 + s_i * (seg_w + gap)
            sx1 = min(pat_x1, sx0 + seg_w)
            draw.rectangle((sx0, hy0 + 9, sx1, hy1 - 9), fill=ink)
            for st_x in range(sx0 + 6, sx1 - 2, 12):
                draw.line((st_x, hy1 - 11, min(sx1 - 2, st_x + 8), hy0 + 11), fill=tint, width=2)
        draw.rounded_rectangle((hx0 + 374, hy0 + 7, hx1 - 8, hy1 - 7), radius=4, fill=ink)
        draw.text((hx0 + 386, hy0 + 11), f"HEADER BAR: {v_idx} SEGMENT(S)", fill=(255, 255, 255), font=fonts["hdr_sm"])
        draw.text((hx0 + 386, hy0 + 31), f"CANARY VARIANT {norm_var}", fill=(255, 255, 255), font=fonts["hdr_lg"])
    else:
        draw.rounded_rectangle((hx0, hy0, hx1, hy1), radius=5, fill=(224, 226, 230), outline=(126, 132, 142), width=2)
        draw.text((hx0 + 20, hy0 + 20), "NO INTERCEPTED WATERMARKED SCANS", fill=(72, 78, 92), font=fonts["hdr_lg"])

    mx0, my0, mx1, my1 = px0 + 16, py0 + 94, px0 + 324, py0 + 190
    draw.rounded_rectangle((mx0, my0, mx1, my1), radius=5, fill=(236, 234, 226), outline=(172, 168, 158), width=1)
    draw.text((mx0 + 12, my0 + 10), f"INTERCEPTED SCAN {scan_index:02d}", fill=(82, 88, 102), font=fonts["tiny"])
    draw.text((mx0 + 12, my0 + 30), f"DOC-ID: {doc_id}", fill=(18, 24, 36), font=fonts["meta_v"])
    draw.text((mx0 + 12, my0 + 64), f"SURFACED: DAY {day_surfaced:02d}", fill=(42, 52, 70), font=fonts["hdr_lg"])

    digest = hashlib.sha256(f"{doc_id}:{day_surfaced}".encode("utf-8")).digest()
    draw.text((px0 + 16, py0 + 204), "RECIPIENT ROSTER: [REDACTED - NO EMP IDS]", fill=(94, 100, 112), font=fonts["tiny"])
    for r_i in range(5):
        ly = py0 + 226 + r_i * 22
        lw = 160 + (digest[r_i] % 120)
        draw.rounded_rectangle((px0 + 16, ly, px0 + 16 + lw, ly + 10), radius=2, fill=(196, 194, 186))
        if r_i in (1, 3):
            rx0 = px0 + 16 + min(lw - 64, 72)
            draw.rectangle((rx0, ly - 1, rx0 + 68, ly + 11), fill=(48, 54, 66))

    sx0, sy0, sx1, sy1 = px0 + 340, py0 + 94, px1 - 16, py0 + 326
    if norm_var is not None:
        ink, tint = VARIANT_PALETTE[norm_var]
        draw.rounded_rectangle((sx0, sy0, sx1, sy1), radius=8, fill=tint, outline=ink, width=4)
        draw.rounded_rectangle((sx0 + 7, sy0 + 7, sx1 - 7, sy1 - 7), radius=5, fill=tint, outline=ink, width=2)
        draw.text((sx0 + 18, sy0 + 20), "CONTROLLED CANARY COPY STAMP", fill=ink, font=fonts["stamp_top"])
        draw.line((sx0 + 18, sy0 + 44, sx1 - 18, sy0 + 44), fill=ink, width=2)
        draw.text((sx0 + 20, sy0 + 72), f"COPY-CODE: {norm_var}", fill=ink, font=fonts["stamp_big"])
        draw.line((sx0 + 18, sy0 + 124, sx1 - 18, sy0 + 124), fill=ink, width=2)
        draw.text((sx0 + 20, sy0 + 142), f"WATERMARK VARIANT = {norm_var} ({v_idx}/8)", fill=ink, font=fonts["stamp_sub"])
        draw.text((sx0 + 20, sy0 + 172), f"DOC-ID {doc_id} | DAY {day_surfaced:02d}", fill=(54, 62, 74), font=fonts["hdr_sm"])

    fx0, fy0, fx1, fy1 = px0 + 16, py0 + 344, px1 - 16, py1 - 14
    draw.rounded_rectangle((fx0, fy0, fx1, fy1), radius=6, fill=(28, 35, 48), outline=(72, 86, 112), width=2)
    tick_hdr = (
        f"FOOTER TICKS: {v_idx}/8 ACTIVE -> COPY-CODE {norm_var}"
        if norm_var is not None
        else "FOOTER TICKS: 0/8 ACTIVE -> NONE"
    )
    draw.text((fx0 + 14, fy0 + 8), tick_hdr, fill=(135, 242, 195), font=fonts["hdr_sm"])

    slot_w = 80
    start_x = fx0 + 16
    for idx, letter in enumerate(VALID_VARIANTS, start=1):
        tx0 = start_x + (idx - 1) * slot_w
        active = norm_var is not None and idx <= v_idx
        is_target = norm_var == letter
        if active and norm_var is not None:
            bar_col = VARIANT_PALETTE[norm_var][0]
            out_col = (255, 255, 255) if is_target else (195, 215, 235)
            draw.rounded_rectangle((tx0, fy0 + 30, tx0 + 64, fy1 - 8), radius=4, fill=bar_col, outline=out_col, width=2 if is_target else 1)
            for notch in range(3):
                nx = tx0 + 15 + notch * 16
                draw.line((nx, fy0 + 35, nx, fy0 + 53), fill=(255, 255, 255), width=2)
            lbl = f"[{letter}:{idx}]" if is_target else f" {letter}:{idx} "
            draw.text((tx0 + 8, fy0 + 58), lbl, fill=(255, 255, 255), font=fonts["hdr_sm"])
        else:
            draw.rounded_rectangle((tx0, fy1 - 20, tx0 + 64, fy1 - 8), radius=2, fill=(44, 54, 72), outline=(66, 78, 102), width=1)
            draw.text((tx0 + 14, fy0 + 46), f"{letter}:{idx}", fill=(108, 120, 144), font=fonts["tiny"])


def render_leaked_memo_scans_png(memo_scans_view: dict[str, Any]) -> bytes:
    tier_name = str(memo_scans_view.get("tier", "medium")).strip().lower()
    seed_tag = sanitize_text(str(memo_scans_view.get("seed_tag", "")))
    closed_day = int(memo_scans_view.get("closed_day", 13))
    scans = list(memo_scans_view.get("leaked_canary_scans", []))

    n_scans = len(scans)
    cols = 3 if n_scans >= 5 else 2
    rows = max(1, math.ceil(max(1, n_scans) / cols))
    card_w, card_h = 724, 464
    gap_x, gap_y = 18, 18
    pad_x = 22
    y_cards = 96

    width = pad_x * 2 + cols * card_w + (cols - 1) * gap_x
    height = y_cards + rows * card_h + (rows - 1) * gap_y + 84

    img = Image.new("RGB", (width, height), (13, 19, 31))
    draw = ImageDraw.Draw(img)

    f_title = _load_font(17, bold=True, mono=False)
    f_sub = _load_font(12, bold=False, mono=True)
    f_leg = _load_font(12, bold=False, mono=False)
    card_fonts = {
        "hdr_lg": _load_font(15, bold=True, mono=True),
        "hdr_sm": _load_font(12, bold=True, mono=True),
        "meta_v": _load_font(21, bold=True, mono=True),
        "stamp_top": _load_font(12, bold=True, mono=False),
        "stamp_big": _load_font(28, bold=True, mono=True),
        "stamp_sub": _load_font(12, bold=True, mono=True),
        "tiny": _load_font(11, bold=False, mono=True),
    }

    draw.rounded_rectangle((16, 12, width - 16, 80), radius=8, fill=(20, 30, 48), outline=(48, 70, 106), width=1)
    title = (
        f"DOSSIER EXHIBIT 2 OF 3 | INTERCEPTED LEAKED CANARY MEMO SCANS (CONTACT SHEET) | "
        f"{tier_name.upper()} (v1.4) | {seed_tag.upper()}"
    )
    sub = (
        f"SURFACED WATERMARKED CANARY SCANS: {n_scans} (THROUGH DAY {closed_day:02d})   "
        f"READ DOC-ID + COPY-CODE STAMP / HEADER SEGMENTS / FOOTER TICKS   [NO EMPLOYEE IDS]"
    )
    draw.text((28, 20), title, fill=(236, 242, 252), font=f_title)
    draw.text((28, 48), sub, fill=(148, 172, 208), font=f_sub)

    if scans:
        for idx, sc in enumerate(scans):
            r_i = idx // cols
            c_i = idx % cols
            cx0 = pad_x + c_i * (card_w + gap_x)
            cy0 = y_cards + r_i * (card_h + gap_y)
            _draw_single_memo_card(
                draw,
                cx0,
                cy0,
                card_w,
                card_h,
                scan_index=idx + 1,
                doc_id=sanitize_text(str(sc["doc_id"])),
                day_surfaced=int(sc["day_surfaced"]),
                variant=str(sc["variant"]),
                fonts=card_fonts,
            )
    else:
        _draw_single_memo_card(
            draw,
            pad_x,
            y_cards,
            card_w,
            card_h,
            scan_index=0,
            doc_id="NONE",
            day_surfaced=closed_day,
            variant=None,
            fonts=card_fonts,
        )

    ly = y_cards + rows * card_h + (rows - 1) * gap_y + 14
    draw.rounded_rectangle((16, ly, width - 16, height - 12), radius=8, fill=(18, 26, 44), outline=(44, 62, 96), width=1)
    draw.text(
        (28, ly + 20),
        "EXHIBIT 2 ISOLATION RULE: Scanned pages contain ONLY DOC-ID and visual COPY-CODE watermarks (A=1, B=2, C=3) "
        "with ZERO employee IDs. Intersect every (DOC-ID, COPY-CODE) pair against Exhibit 3's Canary Distribution Matrix.",
        fill=(212, 224, 244),
        font=f_leg,
    )

    buf = io.BytesIO()
    img.save(buf, format="PNG", compress_level=6)
    return buf.getvalue()


def render_org_canary_map_png(org_map_view: dict[str, Any]) -> bytes:
    tier_name = str(org_map_view.get("tier", "medium")).strip().lower()
    seed_tag = sanitize_text(str(org_map_view.get("seed_tag", "")))
    employees = list(org_map_view["employees"])
    canaries = list(org_map_view["planted_canaries"])

    n_emp = len(employees)
    n_can = len(canaries)
    is_hard = tier_name not in {"easy", "medium"} or n_emp > 20 or n_can > 16

    cw, step_c = (38, 40) if is_hard else (48, 50)
    row_h = 34 if is_hard else 36
    ty = 9 if is_hard else 10

    x_id = 24
    x_zone = 72
    x_mat = 132
    x_roster = x_mat + max(1, n_can) * step_c + 14
    roster_w = 576 if is_hard else 430
    width = max(1320, x_roster + roster_w + 22)

    dept_order: list[str] = []
    for d_name in ("Engineering", "Finance", "Sales", "Legal", "Research"):
        if any(e.get("dept") == d_name for e in employees):
            dept_order.append(d_name)
    for e in employees:
        d_name = str(e.get("dept", ""))
        if d_name and d_name not in dept_order:
            dept_order.append(d_name)
    if not dept_order:
        dept_order = ["General"]

    by_dept: dict[str, list[dict[str, Any]]] = {d: [] for d in dept_order}
    for e in employees:
        by_dept.setdefault(str(e.get("dept", dept_order[0])), []).append(e)

    max_wing_rows = max(1, max(math.ceil(len(v) / 2) for v in by_dept.values()))
    wing_h = 54 + max_wing_rows * 28 + 12
    y_fp_hdr = 92
    y_fp_box = 116
    fp_box_h = wing_h + 44

    y_mat_title = y_fp_box + fp_box_h + 16
    y_mat_hdr = y_mat_title + 26
    y_rows = y_mat_hdr + 40
    mid_break_h = 34 if n_emp > 20 else 0
    height = y_rows + max(1, n_emp) * row_h + mid_break_h + 92

    img = Image.new("RGB", (width, height), (11, 16, 27))
    draw = ImageDraw.Draw(img)

    f_title = _load_font(17, bold=True, mono=False)
    f_sub = _load_font(12, bold=False, mono=True)
    f_sec = _load_font(14, bold=True, mono=False)
    f_hdr = _load_font(11, bold=True, mono=True)
    f_row_id = _load_font(13, bold=True, mono=True)
    f_cell = _load_font(11, bold=True, mono=True)
    f_small = _load_font(10, bold=True, mono=True)
    f_leg = _load_font(12, bold=False, mono=False)

    issued_per_emp = [sum(1 for c in canaries if e["id"] in c["assignment"]) for e in employees]
    issued_desc = (
        f"{issued_per_emp[0]} PER STAFF"
        if issued_per_emp and len(set(issued_per_emp)) == 1
        else f"{min(issued_per_emp or [0])}-{max(issued_per_emp or [0])} PER STAFF"
    )

    draw.rounded_rectangle((16, 12, width - 16, 78), radius=8, fill=(19, 28, 46), outline=(45, 65, 98), width=1)
    title = (
        f"DOSSIER EXHIBIT 3 OF 3 | CORPORATE FLOORPLAN, CLEARANCE ZONES & CANARY DISTRIBUTION MATRIX | "
        f"{tier_name.upper()} (v1.4) | {seed_tag.upper()}"
    )
    sub = (
        f"STAFF: {n_emp}   SECURITY ZONES: {len(dept_order)}   PLANTED CANARIES: {n_can} ({issued_desc})   "
        f"[STATIC PRE-LEAK DISTRIBUTION ONLY - NO LEAK FEED OUTCOMES / NO SWIPE LOGS]"
    )
    draw.text((28, 20), title, fill=(236, 242, 252), font=f_title)
    draw.text((28, 48), sub, fill=(148, 172, 208), font=f_sub)

    draw.text(
        (24, y_fp_hdr),
        "SECTION A: CORPORATE FLOORPLAN & DEPARTMENT CLEARANCE ZONES (PHYSICAL DESK ASSIGNMENT)",
        fill=(132, 212, 255),
        font=f_sec,
    )
    draw.rounded_rectangle(
        (16, y_fp_box, width - 16, y_fp_box + fp_box_h),
        radius=8,
        fill=(15, 22, 36),
        outline=(42, 62, 94),
        width=1,
    )

    n_wings = len(dept_order)
    wing_gap = 14
    avail_w = (width - 56) - wing_gap * (n_wings - 1)
    wing_w = avail_w // n_wings

    for w_i, d_name in enumerate(dept_order):
        wx0 = 28 + w_i * (wing_w + wing_gap)
        wx1 = wx0 + wing_w
        wy0 = y_fp_box + 10
        wy1 = wy0 + wing_h
        d_bg, d_fg, d_tag = DEPT_STYLE.get(d_name, ((44, 56, 78), (204, 216, 236), d_name[:3].upper()))
        draw.rounded_rectangle((wx0, wy0, wx1, wy1), radius=6, fill=(19, 28, 45), outline=d_bg, width=2)
        draw.rounded_rectangle((wx0 + 4, wy0 + 4, wx1 - 4, wy0 + 34), radius=4, fill=d_bg)
        members = by_dept.get(d_name, [])
        draw.text(
            (wx0 + 12, wy0 + 11),
            f"ZONE-{d_tag} | {d_name.upper()} ({len(members)} DESKS)",
            fill=d_fg,
            font=f_hdr,
        )
        desk_w = max(80, (wing_w - 30) // 2)
        for m_i, emp in enumerate(members):
            dr = m_i // 2
            dc = m_i % 2
            dx0 = wx0 + 10 + dc * (desk_w + 10)
            dy0 = wy0 + 44 + dr * 28
            clr = emp.get("clearance")
            clr_txt = f"CLR-{clr}" if clr is not None else f"{d_tag}-{m_i + 1:02d}"
            draw.rounded_rectangle((dx0, dy0, dx0 + desk_w, dy0 + 23), radius=3, fill=(25, 37, 58), outline=(56, 78, 114), width=1)
            draw.text((dx0 + 8, dy0 + 5), f"{emp['id']} [{clr_txt}]", fill=(232, 240, 255), font=f_small)

    corr_y0 = y_fp_box + 14 + wing_h
    draw.rounded_rectangle((28, corr_y0, width - 28, y_fp_box + fp_box_h - 8), radius=4, fill=(22, 33, 52), outline=(52, 74, 108), width=1)
    draw.text(
        (42, corr_y0 + 5),
        "CENTRAL DOCUMENT VAULT CORRIDOR  <-->  ALL ZONES CONNECTED TO BADGE TURNSTILES (SEE EXHIBIT 1 FOR SWIPE TELEMETRY)",
        fill=(164, 188, 222),
        font=f_hdr,
    )

    draw.text(
        (24, y_mat_title),
        "SECTION B: STATIC CANARY DISTRIBUTION MATRIX & ISSUED VARIANTS ROSTER (PRE-INCIDENT ASSIGNMENT ONLY)",
        fill=(124, 238, 192),
        font=f_sec,
    )

    def _draw_matrix_headers(hy: int) -> None:
        draw.text((x_id + 2, hy + 10), "EMP", fill=(162, 178, 204), font=f_hdr)
        draw.text((x_zone + 4, hy + 10), "ZONE", fill=(162, 178, 204), font=f_hdr)
        for idx, c in enumerate(canaries):
            cx0 = x_mat + idx * step_c
            cid = c["canary_id"]
            draw.rounded_rectangle((cx0, hy, cx0 + cw, hy + 34), radius=4, fill=(24, 35, 56), outline=(52, 72, 106), width=1)
            if "-" in cid:
                top_p, bot_p = cid.split("-", 1)
                draw.text((cx0 + 5, hy + 3), top_p, fill=(208, 222, 245), font=f_small)
                draw.text((cx0 + 7, hy + 17), f"-{bot_p}", fill=(158, 182, 218), font=f_small)
            else:
                pad_l = 8 if len(cid) <= 2 else 5
                draw.text((cx0 + pad_l, hy + 10), cid, fill=(208, 222, 245), font=f_small)
        draw.text((x_roster + 6, hy + 10), "EMP   ISSUED CANARY DOC:VARIANT ROSTER", fill=(124, 238, 192), font=f_hdr)

    _draw_matrix_headers(y_mat_hdr)

    for r_idx, emp in enumerate(employees):
        extra_y = 0
        if mid_break_h > 0 and r_idx == 20:
            by_hdr = y_rows + 20 * row_h + 2
            _draw_matrix_headers(by_hdr)
        if mid_break_h > 0 and r_idx >= 20:
            extra_y = mid_break_h

        eid = emp["id"]
        dept = str(emp.get("dept", ""))
        ry = y_rows + r_idx * row_h + extra_y
        cy0, cy1 = ry + 3, ry + row_h - 3

        band_bg = (16, 23, 38) if (r_idx % 2 == 0) else (22, 31, 50)
        draw.rectangle((16, ry, width - 16, ry + row_h - 1), fill=band_bg)
        draw.line((16, ry + row_h - 1, width - 16, ry + row_h - 1), fill=(30, 42, 66), width=1)

        draw.text((x_id + 4, ry + ty), eid, fill=(238, 244, 255), font=f_row_id)
        d_bg, d_fg, d_tag = DEPT_STYLE.get(dept, ((45, 55, 75), (200, 210, 225), dept[:3].upper()))
        draw.rounded_rectangle((x_zone, cy0 + 2, x_zone + 50, cy1 - 2), radius=4, fill=d_bg)
        draw.text((x_zone + 11, ry + ty + 1), d_tag, fill=d_fg, font=f_cell)

        issued_tags: list[str] = []
        for idx, c in enumerate(canaries):
            cx0 = x_mat + idx * step_c
            cx1 = cx0 + cw
            emp_var = c["assignment"].get(eid)
            if emp_var:
                issued_tags.append(f"{c['canary_id']}:{emp_var}")
                v_bg, v_out, v_fg = MATRIX_VARIANT_STYLE.get(emp_var, ((34, 48, 74), (86, 114, 162), (225, 235, 250)))
                draw.rounded_rectangle((cx0, cy0, cx1, cy1), radius=3, fill=v_bg, outline=v_out, width=1)
                tx_off = 14 if is_hard else 19
                draw.text((cx0 + tx_off, ry + ty), emp_var, fill=v_fg, font=f_cell)
            else:
                draw.rounded_rectangle((cx0, cy0, cx1, cy1), radius=3, fill=(14, 20, 33), outline=(26, 36, 55), width=1)
                tx_off = 15 if is_hard else 20
                draw.text((cx0 + tx_off, ry + ty), ".", fill=(64, 78, 102), font=f_cell)

        draw.rounded_rectangle((x_roster, cy0, width - 22, cy1), radius=4, fill=(20, 30, 48), outline=(46, 66, 98), width=1)
        roster_str = f"{eid} | " + "  ".join(issued_tags)
        draw.text((x_roster + 8, ry + ty + 1), roster_str, fill=(214, 230, 250), font=f_small if is_hard else f_cell)

    ly = y_rows + max(1, n_emp) * row_h + mid_break_h + 12
    draw.rounded_rectangle((16, ly, width - 16, height - 12), radius=8, fill=(17, 25, 42), outline=(42, 60, 92), width=1)
    draw.text(
        (28, ly + 16),
        "VARIANT TILES: A (emerald), B (cobalt), C (coral) show static pre-leak canary issuance; '.' means employee was NOT issued that canary.",
        fill=(216, 228, 246),
        font=f_leg,
    )
    draw.text(
        (28, ly + 42),
        "EXHIBIT 3 ISOLATION RULE: Every employee received the exact same number of canaries prior to any leaks. "
        "Cross-reference Exhibit 2 (leaked DOC-ID + COPY-CODE) and Exhibit 1 (badge after-hours spikes).",
        fill=(180, 204, 236),
        font=f_leg,
    )

    buf = io.BytesIO()
    img.save(buf, format="PNG", compress_level=6)
    return buf.getvalue()


def render_incident_dossier_pngs(obs: dict[str, Any]) -> dict[str, bytes]:
    return {
        "badge_raster": render_badge_raster_png(build_badge_view(obs)),
        "leaked_memo_scans": render_leaked_memo_scans_png(build_memo_scans_view(obs)),
        "org_canary_map": render_org_canary_map_png(build_org_map_view(obs)),
    }


def analyze_incident_dossier(
    badge_png: bytes,
    memos_png: bytes,
    org_map_png: bytes,
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
    shas = {
        "badge_raster": png_sha256(badge_png),
        "leaked_memo_scans": png_sha256(memos_png),
        "org_canary_map": png_sha256(org_map_png),
    }

    part_badge = types.Part.from_bytes(data=badge_png, mime_type="image/png")
    part_memos = types.Part.from_bytes(data=memos_png, mime_type="image/png")
    part_org = types.Part.from_bytes(data=org_map_png, mime_type="image/png")
    prompt_text = prompt_for_tier(tier)

    tc_kwargs: dict[str, Any] = {"include_thoughts": True}
    if thinking_level:
        tc_kwargs["thinking_level"] = thinking_level.upper()

    cfg = types.GenerateContentConfig(
        response_mime_type="application/json",
        response_json_schema=INCIDENT_DOSSIER_SCHEMA,
        thinking_config=types.ThinkingConfig(**tc_kwargs),
    )

    meta: dict[str, Any] = {
        "role": FEATURE,
        "subrole": SUBROLE,
        "tier": tier,
        "n_images": 3,
        "image_sha256": shas,
    }
    if seed is not None:
        meta["seed"] = seed

    attempt = 0
    while True:
        t0 = time.time()
        try:
            resp = sdk_client.models.generate_content(
                model=model_id,
                contents=[part_badge, part_memos, part_org, prompt_text],
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
                raise LLMError("EmptyResponseError: empty JSON response text from multi-image dossier call")
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
    confidence = round(max(0.0, min(1.0, float(parsed.get("confidence", 0.0) or 0.0))), 4)

    decoded_scans: list[dict[str, str]] = []
    for item in parsed.get("decoded_leaked_canaries") or []:
        if not isinstance(item, dict):
            continue
        did = sanitize_text(str(item.get("doc_id", ""))).lower()
        var = _normalize_variant(item.get("variant"))
        if did and var:
            decoded_scans.append({"doc_id": did, "variant": var})

    suspect_dept = sanitize_text(str(parsed.get("suspect_department", "")))
    reasoning = sanitize_text(str(parsed.get("cross_image_reasoning", "")))

    return {
        "prediction": {
            "top_suspect_ids": top_suspects,
            "suspected_decoy_ids": suspected_decoys,
            "confidence": confidence,
            "decoded_leaked_canaries": decoded_scans,
            "suspect_department": suspect_dept,
            "cross_image_reasoning": reasoning,
        },
        "usage": {
            "in": int(ledger_row["in"]),
            "out": int(ledger_row["out"]),
            "thinking": int(ledger_row["thinking"]),
            "cached": int(ledger_row["cached"]),
            "cost_usd": float(ledger_row["cost_usd"]),
            "latency_s": float(ledger_row["latency_s"]),
        },
        "model_version": getattr(resp, "model_version", None) or model_id,
        "image_sha256": shas,
        "n_images_sent": 3,
    }


def evaluate_dossier_world(
    seed: int,
    *,
    tier: str = "medium",
    seed_tag: str | None = None,
    model_id: str = DEFAULT_MODEL,
    sdk_client: Any = None,
    run_id: str = "",
    out_dossiers_dir: Path | None = None,
    rel_dossiers_prefix: str = "dossiers",
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

    resolved_tag = seed_tag if seed_tag is not None else f"{tier}_{seed}"
    obs = collect_dossier_observations(_PublicEnvProxy(), seed_label=seed, tier=tier, seed_tag=resolved_tag)
    png_map = render_incident_dossier_pngs(obs)
    fnames = dossier_filenames(resolved_tag)

    images_meta: dict[str, dict[str, Any]] = {}
    for key in ("badge_raster", "leaked_memo_scans", "org_canary_map"):
        raw = png_map[key]
        with Image.open(io.BytesIO(raw)) as im:
            w, h = im.size
        fname = fnames[key]
        rel_path = f"{rel_dossiers_prefix.strip('/')}/{fname}" if rel_dossiers_prefix else fname
        if out_dossiers_dir is not None:
            out_dossiers_dir.mkdir(parents=True, exist_ok=True)
            (out_dossiers_dir / fname).write_bytes(raw)
        images_meta[key] = {
            "kind": key,
            "path": rel_path,
            "sha256": png_sha256(raw),
            "bytes": len(raw),
            "size": [w, h],
        }

    valid_ids = {e["id"] for e in obs["employees"]}
    dept_by_emp = {e["id"]: str(e.get("dept", "")) for e in obs["employees"]}
    vision_res = analyze_incident_dossier(
        png_map["badge_raster"],
        png_map["leaked_memo_scans"],
        png_map["org_canary_map"],
        tier=obs["tier"],
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
    true_mole_dept = dept_by_emp.get(true_mole, "")
    pred = vision_res["prediction"]
    top_suspects = pred["top_suspect_ids"]
    suspected_decoys = pred["suspected_decoy_ids"]

    expected_pairs = {(sc["doc_id"].lower(), sc["variant"]) for sc in obs["leaked_canary_scans"]}
    decoded_pairs = {(sc["doc_id"].lower(), sc["variant"]) for sc in pred["decoded_leaked_canaries"]}
    matched_scans = len(expected_pairs & decoded_pairs)
    scan_exact = decoded_pairs == expected_pairs

    img1_pick = obs["image1_only_naive_pick"]
    img3_pick = obs["image3_only_prior_pick"]

    top1_mole = bool(top_suspects) and top_suspects[0] == true_mole
    top3_mole = true_mole in top_suspects[:3]
    top1_decoy = bool(suspected_decoys) and suspected_decoys[0] == true_decoy
    decoy_hit = true_decoy in suspected_decoys if true_decoy is not None else False
    avoided_trap = (not top_suspects) or (top_suspects[0] != true_decoy)
    dept_exact = pred["suspect_department"].strip().lower() == true_mole_dept.strip().lower()

    total_ah = sum(1 for r in obs["badge_logs"] if r["after_hours"])

    return {
        "seed": seed,
        "tier": obs["tier"],
        "seed_tag": resolved_tag,
        "tiers_version": TIERS_VERSION,
        "n_images_read": 3,
        "images": images_meta,
        "observable_summary": {
            "n_employees": len(obs["employees"]),
            "closed_day": obs["closed_day"],
            "total_badge_swipes": len(obs["badge_logs"]),
            "total_after_hours_swipes": total_ah,
            "n_canaries_planted": len(obs["planted_canaries"]),
            "issued_canaries_per_employee": obs["issued_counts_set"],
            "n_leaked_canary_scans": len(obs["leaked_canary_scans"]),
            "leaked_canary_scans": obs["leaked_canary_scans"],
            "canary_intersection_candidates": obs["canary_intersection_candidates"],
        },
        "single_image_baselines": {
            "image1_only_naive_after_hours_pick": img1_pick,
            "image1_only_mole_correct": img1_pick == true_mole,
            "image1_only_trapped_by_decoy": img1_pick == true_decoy,
            "image2_only_pick": None,
            "image2_only_mole_correct": False,
            "image2_only_decoy_correct": False,
            "image3_only_prior_pick": img3_pick,
            "image3_only_mole_correct": img3_pick == true_mole,
            "image3_only_uniform_prior": obs["image3_only_uniform_prior"],
        },
        "model_output": pred,
        "ground_truth": {
            "true_mole": true_mole,
            "true_mole_dept": true_mole_dept,
            "true_decoy": true_decoy,
            "true_decoy_dept": dept_by_emp.get(true_decoy or "", ""),
        },
        "evaluation": {
            "top1_mole_correct": top1_mole,
            "top3_mole_hit": top3_mole,
            "top1_decoy_correct": top1_decoy,
            "decoy_identified": decoy_hit,
            "avoided_framing_trap": avoided_trap,
            "memo_scans_matched": matched_scans,
            "memo_scans_total": len(expected_pairs),
            "memo_scans_exact_match": scan_exact,
            "suspect_dept_correct": dept_exact,
        },
        "usage": vision_res["usage"],
        "model_version": vision_res["model_version"],
    }
