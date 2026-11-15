from __future__ import annotations

import argparse
import html
import json
import math
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]

DEFAULT_HTML_REL = "results/eval_v14/headline_dashboard_v14.html"
DEFAULT_GUIDE_REL = "docs/reports/eval_dashboard_guide_v14.md"
MAX_HTML_BYTES = 60000

INPUT_JSON_RELS: dict[str, str] = {
    "headline": "results/eval_v14/headline_gap_table_v14.json",
    "harness": "results/eval_v14/harness_and_tier_v14.json",
    "power": "results/eval_v14/judge_rerun_power_v14.json",
    "counterfactual": "results/eval_v14/counterfactual_decomposition_v14.json",
    "diagnostics": "results/eval_v14/paired_seed_diagnostics_v14.json",
}

GPT55_EPISODES_REL = "data/runs/committed/v1.4/opencode-gpt-5.5/hard/episodes.jsonl"
HARBOR_SHELL_TRIALS = "20/28"

BANNED_SUBSTRINGS: tuple[str, ...] = (
    "\u2013",
    "\u2014",
    "\u00b1",
    "&ndash;",
    "&mdash;",
    "&plusmn;",
)

MOLE_ID_RE = re.compile(r"\be\d{2}\b")


def clean_ascii(text: Any) -> str:
    s = str(text)
    s = s.replace("\u2014", "--")
    s = s.replace("\u2013", "-")
    s = s.replace("\u2012", "-")
    s = s.replace("\u2212", "-")
    s = s.replace("\u00b1", "+/-")
    s = s.replace("\u2192", "->")
    s = s.replace("\u2264", "<=")
    s = s.replace("\u2265", ">=")
    return s


def esc(text: Any) -> str:
    return html.escape(clean_ascii(text), quote=True)


def fmt_pct(val: float | None, decimals: int = 0) -> str:
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return "--"
    pct = val * 100.0
    if decimals == 0:
        return f"{int(round(pct))}%"
    return f"{pct:.{decimals}f}%"


def fmt_pct_ci(val: float | None, lo: float | None, hi: float | None, decimals: int = 0) -> str:
    point = fmt_pct(val, decimals)
    if lo is None or hi is None:
        return point
    return f"{point} [{fmt_pct(lo, decimals)}, {fmt_pct(hi, decimals)}]"


def fmt_signed(val: float | None, decimals: int = 3) -> str:
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return "--"
    sign = "+" if val >= 0 else "-"
    return f"{sign}{abs(val):.{decimals}f}"


def fmt_num(val: float | None, decimals: int = 3) -> str:
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return "--"
    return f"{val:.{decimals}f}"


def r4(val: float | None) -> float | None:
    if val is None:
        return None
    return round(float(val), 4)


def load_sources(root: Path) -> dict[str, Any]:
    loaded: dict[str, Any] = {}
    for key, rel in INPUT_JSON_RELS.items():
        path = root / rel
        if not path.is_file():
            raise FileNotFoundError(f"Required input JSON missing: {path}")
        loaded[key] = json.loads(path.read_text(encoding="utf-8"))

    gpt55_ep_path = root / GPT55_EPISODES_REL
    gpt55_total_canaries: float | None = None
    if gpt55_ep_path.is_file():
        lines = [ln for ln in gpt55_ep_path.read_text(encoding="utf-8").splitlines() if ln.strip()]
        if lines:
            counts = []
            for ln in lines:
                ep = json.loads(ln)
                c = sum(
                    1
                    for step in ep.get("steps", [])
                    if step.get("tool") == "plant_canary" and not step.get("error")
                )
                counts.append(c)
            gpt55_total_canaries = sum(counts) / len(counts)
    loaded["gpt55_total_canaries"] = gpt55_total_canaries
    return loaded


def find_section_a_row(rows: list[dict[str, Any]], tier: str, agent: str, kind: str) -> dict[str, Any]:
    for row in rows:
        if row.get("tier") == tier and row.get("agent") == agent and row.get("kind") == kind:
            return row
    raise KeyError(f"Missing section_a row for tier={tier}, agent={agent}, kind={kind}")


def build_compact_rows(
    headline: dict[str, Any],
    power: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    pass_k_map = power.get("pass_k_reliability", {})
    agent_to_passk_key = {
        ("hard", "solver", "reference"): "solver",
        ("hard", "gemini:gemini-4-carbon", "frontier"): "inproc-carbon",
        ("hard", "opencode:google/gemini-4-carbon", "frontier"): "opencode-carbon",
        ("hard", "opencode:google/gemini-3.5-flash", "frontier"): "opencode-3.5-flash",
    }

    primary_rows: list[dict[str, Any]] = []
    for src_sec, items in (("A", headline.get("section_a", [])), ("B1", headline.get("section_b1", []))):
        for idx, r in enumerate(items):
            tier = clean_ascii(r["tier"])
            agent = clean_ascii(r["agent"])
            kind = clean_ascii(r["kind"])
            pk_key = agent_to_passk_key.get((tier, agent, kind))
            pk_ci = pass_k_map.get(pk_key, {}).get("pass_3_ci95") if pk_key else None
            p3_lo = r4(pk_ci[0]) if pk_ci else None
            p3_hi = r4(pk_ci[1]) if pk_ci else None
            primary_rows.append(
                {
                    "sec": src_sec,
                    "tier": tier,
                    "agent": agent,
                    "kind": kind,
                    "label": clean_ascii(r["label"]),
                    "n": int(r["n"]),
                    "mean": r4(r["mean"]),
                    "score_ci": r4(r["score_ci"]),
                    "solver": r4(r["solver_same_seeds"]),
                    "raw": r4(r["ratio"]),
                    "raw_lo": r4(r["ratio_lo"]),
                    "raw_hi": r4(r["ratio_hi"]),
                    "la": r4(r["luck_adj_ratio"]),
                    "la_lo": r4(r["luck_adj_lo"]),
                    "la_hi": r4(r["luck_adj_hi"]),
                    "win": r4(r["winnable_ratio"]),
                    "win_lo": r4(r["winnable_ratio_lo"]),
                    "win_hi": r4(r["winnable_ratio_hi"]),
                    "p3": r4(r["pass3_calibrated"]),
                    "p3_lo": p3_lo,
                    "p3_hi": p3_hi,
                    "acc": r4(r["accuracy"]),
                    "facc": r4(r["false_accusation_rate"]),
                    "abst": r4(r["abstain_rate"]),
                    "sha": clean_ascii(r.get("git_sha", "")),
                }
            )

    b2_rows: list[list[Any]] = []
    for r in headline.get("section_b2", []):
        r_ci = r.get("ratio_ci") or [None, None]
        l_ci = r.get("luck_ci") or [None, None]
        w_ci = r.get("win_ci") or [None, None]
        b2_rows.append(
            [
                clean_ascii(r["tier"]),
                clean_ascii(r["label"]),
                int(r["n"]),
                r4(r["mean"]),
                r4(r["score_ci"]),
                r4(r["ratio"]),
                r4(r_ci[0]),
                r4(r_ci[1]),
                r4(r["luck_ratio"]),
                r4(l_ci[0]),
                r4(l_ci[1]),
                r4(r["win_ratio"]),
                r4(w_ci[0]),
                r4(w_ci[1]),
                r4(r["pass3"]),
            ]
        )

    return primary_rows, b2_rows


def build_cf_records(counterfactual: dict[str, Any]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for c in counterfactual.get("frontier_cohorts", []):
        id_chk = c["identity_check"]
        if abs(float(id_chk["sum_of_component_means"]) - float(id_chk["solver_minus_agent_mean"])) > 1e-6:
            raise ValueError(f"Counterfactual identity residual too large for {c.get('cohort')}")
        sp = c["scores_and_posteriors"]
        comp = c["components"]
        records.append(
            {
                "cohort": clean_ascii(c["cohort"]),
                "agent": clean_ascii(c["agent"]),
                "tier": clean_ascii(c["tier"]),
                "n": int(c["n"]),
                "agent_mean": r4(sp["agent_mean"]),
                "solver_mean": r4(sp["solver_mean"]),
                "gap": r4(sp["total_gap_delta"]),
                "gap_lo": r4(sp["total_gap_ci95"][0]),
                "gap_hi": r4(sp["total_gap_ci95"][1]),
                "la_gap": r4(sp["luck_adjusted_gap"]),
                "ev_rescue": r4(comp["ev_abstain_rescue"]["mean"]),
                "cal_wrong": r4(comp["calibrated_wrong_accuse_residual"]["mean"]),
                "missed_info": r4(comp["missed_catch_information_gap"]["mean"]),
                "timing_cost": r4(comp["timing_and_cost_bleed_gap"]["mean"]),
                "solver_miss": r4(comp["solver_miss_frontier_catch_offset"]["mean"]),
            }
        )
    return records


def render_static_forest_svg(rows: list[dict[str, Any]]) -> str:
    hard_rows = [r for r in rows if r["sec"] == "A" and r["tier"] == "hard"]
    lo_min = -2.2
    hi_max = 1.6
    w = 860
    left = 300
    right = 735
    plot_w = right - left
    row_h = 26
    top = 42
    h = top + len(hard_rows) * row_h + 34

    def x_pos(val: float) -> float:
        clamped = max(lo_min, min(hi_max, val))
        return left + ((clamped - lo_min) / (hi_max - lo_min)) * plot_w

    lines: list[str] = [
        f'<svg id="forest-svg" viewBox="0 0 {w} {h}" role="img" aria-label="Paired 95% CI Forest Plot">',
        f'<rect x="0" y="0" width="{w}" height="{h}" fill="rgb(15, 23, 42)" rx="6"/>',
        f'<text x="14" y="24" fill="rgb(226, 232, 240)" font-size="13" font-weight="700">'
        'Primary Paired 95% CI Forest Plot -- Tier: hard | Metric: Raw % Solver (n=30, 10,000 resamples)</text>',
    ]

    for tick in (-2.0, -1.0, 0.0, 0.5, 1.0, 1.5):
        tx = x_pos(tick)
        stroke = "rgb(51, 65, 85)"
        dash = ' stroke-dasharray="3,3"'
        if abs(tick - 1.0) < 1e-9:
            stroke = "rgb(34, 197, 94)"
            dash = ' stroke-dasharray="5,3"'
        elif abs(tick) < 1e-9:
            stroke = "rgb(148, 163, 184)"
            dash = ' stroke-dasharray="4,4"'
        lines.append(
            f'<line x1="{tx:.1f}" y1="{top - 6}" x2="{tx:.1f}" y2="{h - 26}" stroke="{stroke}" stroke-width="1"{dash}/>'
        )
        lines.append(
            f'<text x="{tx:.1f}" y="{h - 10}" fill="rgb(148, 163, 184)" font-size="11" text-anchor="middle">'
            f'{int(round(tick * 100))}%</text>'
        )

    color_by_kind = {
        "frontier": "rgb(56, 189, 248)",
        "sensitivity": "rgb(251, 191, 36)",
        "reference": "rgb(74, 222, 128)",
        "baseline": "rgb(148, 163, 184)",
    }

    for i, r in enumerate(hard_rows):
        cy = top + i * row_h + 12
        pt = float(r["raw"])
        lo = r["raw_lo"]
        hi = r["raw_hi"]
        col = color_by_kind.get(r["kind"], "rgb(148, 163, 184)")
        if r["agent"] == "opencode:openai/gpt-5.5":
            col = "rgb(167, 139, 250)"
        short_lbl = r["label"]
        if len(short_lbl) > 42:
            short_lbl = short_lbl[:39] + "..."
        lines.append(
            f'<text x="{left - 10}" y="{cy + 4}" fill="rgb(226, 232, 240)" font-size="11" text-anchor="end">'
            f'{esc(short_lbl)}</text>'
        )
        if lo is not None and hi is not None:
            x1 = x_pos(float(lo))
            x2 = x_pos(float(hi))
            lines.append(
                f'<line x1="{x1:.1f}" y1="{cy}" x2="{x2:.1f}" y2="{cy}" stroke="{col}" stroke-width="2.2"/>'
            )
            lines.append(
                f'<line x1="{x1:.1f}" y1="{cy - 4}" x2="{x1:.1f}" y2="{cy + 4}" stroke="{col}" stroke-width="1.6"/>'
            )
            lines.append(
                f'<line x1="{x2:.1f}" y1="{cy - 4}" x2="{x2:.1f}" y2="{cy + 4}" stroke="{col}" stroke-width="1.6"/>'
            )
        px = x_pos(pt)
        lines.append(f'<circle cx="{px:.1f}" cy="{cy}" r="4.2" fill="{col}"/>')
        txt_val = fmt_pct_ci(pt, lo, hi, 0)
        lines.append(
            f'<text x="{right + 10}" y="{cy + 4}" fill="rgb(226, 232, 240)" font-size="11">{esc(txt_val)}</text>'
        )

    lines.append("</svg>")
    return "\n".join(lines)


def render_static_cf_svg(cf_records: list[dict[str, Any]]) -> str:
    hard_cf = [c for c in cf_records if c["tier"] == "hard"]
    w = 860
    left = 245
    zero_x = 430
    scale = 900.0
    row_h = 40
    top = 46
    h = top + len(hard_cf) * row_h + 36

    comp_Meta = [
        ("cal_wrong", "Calibrated Wrong-Accuse", "rgb(248, 113, 113)"),
        ("missed_info", "Missed-Catch Info Gap", "rgb(251, 191, 36)"),
        ("ev_rescue", "EV Abstain Rescue", "rgb(251, 146, 60)"),
        ("timing_cost", "Timing & Cost Bleed", "rgb(56, 189, 248)"),
        ("solver_miss", "Solver-Miss Offset", "rgb(74, 222, 128)"),
    ]

    lines: list[str] = [
        f'<svg id="cf-svg" viewBox="0 0 {w} {h}" role="img" aria-label="Counterfactual Gap Decomposition Bars">',
        f'<rect x="0" y="0" width="{w}" height="{h}" fill="rgb(15, 23, 42)" rx="6"/>',
        '<text x="14" y="22" fill="rgb(226, 232, 240)" font-size="13" font-weight="700">'
        'Exact 5-Term Counterfactual Loss Decomposition (solver_score - agent_score, positive = agent loss)</text>',
    ]

    lx = 14
    for _, label, color in comp_Meta:
        lines.append(f'<rect x="{lx}" y="30" width="10" height="10" fill="{color}" rx="2"/>')
        lines.append(f'<text x="{lx + 14}" y="39" fill="rgb(203, 213, 225)" font-size="10.5">{esc(label)}</text>')
        lx += 162

    for tick in (-0.10, -0.05, 0.0, 0.05, 0.10, 0.15, 0.20):
        tx = zero_x + tick * scale
        stroke = "rgb(148, 163, 184)" if abs(tick) < 1e-9 else "rgb(51, 65, 85)"
        dash = "" if abs(tick) < 1e-9 else ' stroke-dasharray="3,3"'
        lines.append(
            f'<line x1="{tx:.1f}" y1="{top}" x2="{tx:.1f}" y2="{h - 24}" stroke="{stroke}" stroke-width="1"{dash}/>'
        )
        lines.append(
            f'<text x="{tx:.1f}" y="{h - 9}" fill="rgb(148, 163, 184)" font-size="10.5" text-anchor="middle">'
            f'{fmt_signed(tick, 2)}</text>'
        )

    for idx, rec in enumerate(hard_cf):
        cy = top + idx * row_h + 14
        lbl = f'{rec["cohort"]} ({rec["tier"]})'
        lines.append(
            f'<text x="{left - 12}" y="{cy + 8}" fill="rgb(226, 232, 240)" font-size="11.5" text-anchor="end">'
            f'{esc(lbl)}</text>'
        )
        pos_cursor = zero_x
        neg_cursor = zero_x
        for key, _, color in comp_Meta:
            val = float(rec[key] or 0.0)
            bw = abs(val) * scale
            if bw < 0.4:
                continue
            if val >= 0:
                lines.append(
                    f'<rect x="{pos_cursor:.1f}" y="{cy - 4}" width="{bw:.1f}" height="16" fill="{color}" rx="1.5"/>'
                )
                pos_cursor += bw
            else:
                neg_cursor -= bw
                lines.append(
                    f'<rect x="{neg_cursor:.1f}" y="{cy - 4}" width="{bw:.1f}" height="16" fill="{color}" rx="1.5"/>'
                )
        gap_txt = f'gap {fmt_signed(rec["gap"], 3)} [{fmt_signed(rec["gap_lo"], 3)}, {fmt_signed(rec["gap_hi"], 3)}]'
        lines.append(
            f'<text x="640" y="{cy + 8}" fill="rgb(226, 232, 240)" font-size="11">{esc(gap_txt)}</text>'
        )

    lines.append("</svg>")
    return "\n".join(lines)


def build_dashboard_html(sources: dict[str, Any]) -> str:
    headline = sources["headline"]
    harness = sources["harness"]
    power = sources["power"]
    counterfactual = sources["counterfactual"]
    diagnostics = sources["diagnostics"]

    sec_a = headline["section_a"]
    oc_hard = find_section_a_row(sec_a, "hard", "opencode:google/gemini-4-carbon", "frontier")
    oc_med = find_section_a_row(sec_a, "medium", "opencode:google/gemini-4-carbon", "frontier")
    ip_hard = find_section_a_row(sec_a, "hard", "gemini:gemini-4-carbon", "frontier")
    ip_med = find_section_a_row(sec_a, "medium", "gemini:gemini-4-carbon", "frontier")
    gpt55_hard = find_section_a_row(sec_a, "hard", "opencode:openai/gpt-5.5", "frontier")
    solver_hard = find_section_a_row(sec_a, "hard", "solver", "reference")
    solver_med = find_section_a_row(sec_a, "medium", "solver", "reference")

    honest = diagnostics["provenance_and_honesty"]["honest_headline_scope_c59ecfd0"]
    reh = honest["harbor_judge_path_rehearsal"]
    reh_runs = reh["runs"]
    reh_ratios = counterfactual["panel_fix_a_and_headline"]["harbor_rehearsal_3run_ratios"]

    psd_hard = diagnostics["tiers"]["hard"]["cohorts"]
    carbon_canaries = float(harness["cells"]["hard_opencode"]["canaries_total_mean"])
    gpt55_canaries = (
        float(sources["gpt55_total_canaries"])
        if sources["gpt55_total_canaries"] is not None
        else float(psd_hard["opencode_gpt55"]["mean_canaries_planted"])
    )
    solver_canaries = float(harness["cells"]["hard_solver"]["canaries_total_mean"])
    inproc_canaries = float(harness["cells"]["hard_inproc"]["canaries_total_mean"])

    carbon_interviews = float(harness["cells"]["hard_opencode"]["interviews_mean"])
    inproc_interviews = float(harness["cells"]["hard_inproc"]["interviews_mean"])
    gpt55_interviews = float(psd_hard["opencode_gpt55"]["mean_interviews"])

    primary_rows, b2_rows = build_compact_rows(headline, power)
    cf_records = build_cf_records(counterfactual)

    c2x2_raw = harness["contrasts_2x2"]["raw_score"]
    c2x2_la = harness["contrasts_2x2"]["luck_adjusted_score"]

    ma_oc = power["model_a_empirical_paired_resampling"]["opencode-carbon"]
    mb_oc = power["model_b_posterior_repeated_runs"]["opencode-carbon"]
    pk_hard = power["pass_k_reliability"]

    g1_ext = headline["g1_extension_sensitivity"]

    static_forest_svg = render_static_forest_svg(primary_rows)
    static_cf_svg = render_static_cf_svg(cf_records)

    table_rows_html: list[str] = []
    for r in primary_rows:
        if not (r["sec"] == "A" and r["tier"] == "hard"):
            continue
        p3_ci_str = fmt_pct_ci(r["p3"], r["p3_lo"], r["p3_hi"], 1) if r["p3_lo"] is not None else fmt_pct(r["p3"], 1)
        table_rows_html.append(
            f'<tr data-sec="{esc(r["sec"])}" data-tier="{esc(r["tier"])}">'
            f'<td><span class="pill pill-{esc(r["tier"])}">{esc(r["tier"])}</span></td>'
            f'<td>{esc(r["sec"])}</td>'
            f'<td class="lbl-cell"><strong>{esc(r["label"])}</strong><br>'
            f'<span class="muted">{esc(r["agent"])} | sha {esc(r["sha"])}</span></td>'
            f'<td class="num">{r["n"]}</td>'
            f'<td class="num">{fmt_signed(r["mean"], 3)} +/- {fmt_num(r["score_ci"], 3)}</td>'
            f'<td class="num">{fmt_signed(r["solver"], 3)}</td>'
            f'<td class="num c-raw active-metric">{esc(fmt_pct_ci(r["raw"], r["raw_lo"], r["raw_hi"], 0))}</td>'
            f'<td class="num c-la">{esc(fmt_pct_ci(r["la"], r["la_lo"], r["la_hi"], 0))}</td>'
            f'<td class="num c-win">{esc(fmt_pct_ci(r["win"], r["win_lo"], r["win_hi"], 0))}</td>'
            f'<td class="num c-p3">{esc(p3_ci_str)}</td>'
            f'<td class="num">{fmt_pct(r["acc"], 1)}</td>'
            f'<td class="num">{fmt_pct(r["facc"], 1)}</td>'
            f'<td class="num">{fmt_pct(r["abst"], 1)}</td>'
            f'</tr>'
        )

    b2_rows_html: list[str] = []

    row_cols = [
        "sec", "tier", "agent", "kind", "label", "n", "mean", "score_ci", "solver",
        "raw", "raw_lo", "raw_hi", "la", "la_lo", "la_hi", "win", "win_lo", "win_hi",
        "p3", "p3_lo", "p3_hi", "acc", "facc", "abst", "sha",
    ]
    cf_cols = [
        "cohort", "agent", "tier", "n", "agent_mean", "solver_mean",
        "gap", "gap_lo", "gap_hi", "la_gap",
        "ev_rescue", "cal_wrong", "missed_info", "timing_cost", "solver_miss",
    ]
    payload_json = json.dumps(
        {
            "rc": row_cols,
            "r": [[row[k] for k in row_cols] for row in primary_rows],
            "b2": b2_rows,
            "cc": cf_cols,
            "cf": [[rec[k] for k in cf_cols] for rec in cf_records],
        },
        separators=(",", ":"),
        sort_keys=True,
    )

    doc = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Canary v1.4 Headline Gap &amp; Judge Explorer</title>
<style>
:root {{
  --bg: rgb(11, 15, 25);
  --panel: rgb(17, 24, 39);
  --panel-alt: rgb(30, 41, 59);
  --border: rgb(51, 65, 85);
  --text: rgb(241, 245, 249);
  --muted: rgb(148, 163, 184);
  --accent: rgb(56, 189, 248);
  --warn-bg: rgba(245, 158, 11, 0.12);
  --warn-border: rgb(245, 158, 11);
  --ok: rgb(74, 222, 128);
  --purple: rgb(167, 139, 250);
}}
* {{ box-sizing: border-box; }}
body {{
  margin: 0;
  padding: 20px;
  background: var(--bg);
  color: var(--text);
  font-family: ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
  line-height: 1.45;
  font-size: 14px;
}}
.wrap {{ max-width: 1240px; margin: 0 auto; }}
header {{
  display: flex;
  flex-wrap: wrap;
  justify-content: space-between;
  align-items: baseline;
  gap: 12px;
  border-bottom: 1px solid var(--border);
  padding-bottom: 12px;
  margin-bottom: 16px;
}}
h1 {{ margin: 0; font-size: 22px; letter-spacing: -0.01em; }}
h2 {{ margin: 0 0 10px 0; font-size: 16px; color: rgb(226, 232, 240); }}
h3 {{ margin: 0 0 6px 0; font-size: 14px; }}
.sub {{ color: var(--muted); font-size: 12.5px; }}
.disclosure-banner {{
  background: var(--warn-bg);
  border: 1.5px solid var(--warn-border);
  border-radius: 8px;
  padding: 14px 16px;
  margin-bottom: 18px;
}}
.disclosure-title {{
  font-weight: 700;
  font-size: 14.5px;
  color: rgb(253, 224, 71);
  margin-bottom: 10px;
}}
.disclosure-grid {{
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
  gap: 12px;
}}
.disc-card {{
  background: rgba(15, 23, 42, 0.85);
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 10px 12px;
  font-size: 12.8px;
}}
.disc-card strong {{ color: rgb(248, 250, 252); }}
.controls {{
  display: flex;
  flex-wrap: wrap;
  gap: 14px;
  align-items: center;
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 12px 14px;
  margin-bottom: 16px;
}}
.ctrl-group {{ display: flex; flex-wrap: wrap; align-items: center; gap: 6px; }}
.ctrl-label {{ font-size: 12px; font-weight: 600; color: var(--muted); text-transform: uppercase; margin-right: 4px; }}
button {{
  background: var(--panel-alt);
  color: var(--text);
  border: 1px solid var(--border);
  border-radius: 5px;
  padding: 5px 10px;
  font-size: 12.5px;
  cursor: pointer;
}}
button:hover {{ border-color: var(--accent); }}
button.active {{
  background: rgb(3, 105, 161);
  border-color: var(--accent);
  font-weight: 600;
}}
.btn-export {{ background: rgb(30, 58, 138); border-color: rgb(59, 130, 246); }}
.panel {{
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 14px 16px;
  margin-bottom: 16px;
}}
.grid-2 {{
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(480px, 1fr));
  gap: 16px;
  margin-bottom: 16px;
}}
svg {{ width: 100%; height: auto; display: block; }}
table {{ width: 100%; border-collapse: collapse; font-size: 12.5px; }}
th, td {{
  padding: 7px 8px;
  border-bottom: 1px solid rgb(30, 41, 59);
  text-align: left;
  vertical-align: top;
}}
th {{
  background: rgb(15, 23, 42);
  color: rgb(203, 213, 225);
  font-weight: 600;
  position: sticky;
  top: 0;
}}
td.num, th.num {{ text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; }}
.lbl-cell {{ min-width: 240px; }}
.muted {{ color: var(--muted); font-size: 11.5px; }}
.pill {{
  display: inline-block;
  padding: 1px 7px;
  border-radius: 999px;
  font-size: 11px;
  font-weight: 600;
}}
.pill-hard {{ background: rgba(239, 68, 68, 0.2); color: rgb(252, 165, 165); }}
.pill-medium {{ background: rgba(56, 189, 248, 0.2); color: rgb(125, 211, 252); }}
.active-metric {{ background: rgba(56, 189, 248, 0.10); font-weight: 600; }}
details summary {{ cursor: pointer; font-weight: 600; color: var(--accent); padding: 6px 0; }}
code {{
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: 12px;
  background: rgba(15, 23, 42, 0.9);
  padding: 1px 4px;
  border-radius: 3px;
}}
</style>
</head>
<body>
<div class="wrap">
  <header>
    <div>
      <h1>Canary v1.4 Paired Headline Gap &amp; Judge Explorer</h1>
      <div class="sub">100% Replay-Verified Offline Artifact | Paired Seeds 0-29 (n=30/tier) | 10,000 Paired Bootstrap Resamples | Zero External Assets</div>
    </div>
    <div class="sub">Reproduce: <code>python scripts/build_eval_dashboard_v14.py --check</code></div>
  </header>

  <section class="disclosure-banner" id="honest-disclosure-banner" aria-label="Honest Scope and Provenance Disclosure">
    <div class="disclosure-title">Prominent Honest Scope &amp; Provenance Disclosure (Read First)</div>
    <div class="disclosure-grid">
      <div class="disc-card">
        <strong>(1) MCP-Only gemini-4-carbon Primary Set (Not Pre-Registered):</strong><br>
        On v1.4 <code>hard</code> (13 MCP tools only, bash/python3 denied), OpenCode + <code>gemini-4-carbon</code> scores
        <strong>{fmt_pct_ci(oc_hard["ratio"], oc_hard["ratio_lo"], oc_hard["ratio_hi"], 0)}</strong> raw
        (<code>{fmt_signed(oc_hard["mean"], 3)} +/- {fmt_num(oc_hard["score_ci"], 3)}</code> vs solver <code>{fmt_signed(solver_hard["mean"], 3)}</code>)
        and <strong>{fmt_pct_ci(oc_hard["luck_adj_ratio"], oc_hard["luck_adj_lo"], oc_hard["luck_adj_hi"], 0)}</strong> luck-adjusted
        (<code>n={oc_hard["n"]}</code>, paired Wilcoxon <code>p={oc_hard["p_wilcoxon_luck"]:.4f}</code>).
        Dev seeds <code>0-29</code> were <strong>post-hoc locked</strong> at commit <code>671ed96</code> (28 s after <code>8fd4dec</code>; lock against later reruns/cherry-picking, NOT pre-registered).
        Medium MCP: <code>{fmt_pct_ci(oc_med["ratio"], oc_med["ratio_lo"], oc_med["ratio_hi"], 0)}</code> raw /
        <code>{fmt_pct_ci(oc_med["luck_adj_ratio"], oc_med["luck_adj_lo"], oc_med["luck_adj_hi"], 0)}</code> LA.
      </div>
      <div class="disc-card">
        <strong>(2) Harbor 3x10 Container Judge-Path Rehearsal -- Gap Did NOT Reproduce:</strong><br>
        On tag <code>{esc(reh["tag"])}</code> (commits <code>{esc(reh["commit"])}</code> / <code>{esc(reh["ceo_correction_commit"])}</code>, 10 hard judge tasks, 28/29 valid accusations correct):
        <code>opencode-1</code> <strong>{fmt_signed(reh_runs["opencode-1"]["mean"], 3)}</strong> (<strong>{esc(reh_ratios[0])}</strong>, n={reh_runs["opencode-1"]["n_valid"]}),
        <code>opencode-2</code> <strong>{fmt_signed(reh_runs["opencode-2"]["mean"], 3)}</strong> (<strong>{esc(reh_ratios[1])}</strong>, n={reh_runs["opencode-2"]["n_valid"]}),
        <code>opencode-3</code> <strong>{fmt_signed(reh_runs["opencode-3"]["mean"], 3)}</strong> (<strong>{esc(reh_ratios[2])}</strong> on <code>n={reh_runs["opencode-3"]["n_valid"]}</code> valid, 1 infra-excluded)
        vs oracle <strong>+{reh_runs["opencode-1"]["oracle_same_tasks"]:.3f}</strong> (<code>do_nothing</code>/<code>stop_early</code> <code>+0.000</code>, <code>0%</code>).
        Container shell was used in <strong>{HARBOR_SHELL_TRIALS}</strong> trials -- <strong>the gap did NOT reproduce in the judge path</strong>.
      </div>
      <div class="disc-card">
        <strong>(3) Pre-Registered Second Family gpt-5.5 MCP -- Matches Solver (No Gap):</strong><br>
        Pre-registered at <code>{esc(honest["gpt55_prereg_commit"])}</code> / committed <code>{esc(honest["gpt55_commit"])}</code> (same 13 MCP tools, seeds <code>0-29</code>, <code>n={gpt55_hard["n"]}</code>, 0 infra failures):
        <code>opencode:openai/gpt-5.5</code> scores <strong>{fmt_signed(gpt55_hard["mean"], 3)} +/- {fmt_num(gpt55_hard["score_ci"], 3)}</strong>,
        <strong>{fmt_pct_ci(gpt55_hard["ratio"], gpt55_hard["ratio_lo"], gpt55_hard["ratio_hi"], 0)}</strong> raw,
        <strong>{fmt_pct_ci(gpt55_hard["luck_adj_ratio"], gpt55_hard["luck_adj_lo"], gpt55_hard["luck_adj_hi"], 0)}</strong> LA
        (28/28 accused correct; seeds 0 and 17 wrote text without calling <code>accuse</code>, scored <code>0.0</code>).
        Plants <strong>{gpt55_canaries:.1f}</strong> canaries vs <strong>{carbon_canaries:.1f}</strong> for carbon ({gpt55_interviews:.1f} vs {carbon_interviews:.1f} interviews).
      </div>
    </div>
  </section>

  <section class="controls" aria-label="Interactive Dashboard Controls">
    <div class="ctrl-group" id="tier-controls">
      <span class="ctrl-label">Tier Filter:</span>
      <button type="button" class="active" data-tier="hard">hard</button>
      <button type="button" data-tier="medium">medium</button>
      <button type="button" data-tier="all">all</button>
    </div>
    <div class="ctrl-group" id="metric-controls">
      <span class="ctrl-label">Metric Toggle:</span>
      <button type="button" class="active" data-metric="raw">Raw % Solver</button>
      <button type="button" data-metric="la">Luck-Adjusted % Solver</button>
      <button type="button" data-metric="win">Winnable %</button>
      <button type="button" data-metric="p3">Calibrated pass^3</button>
    </div>
    <div class="ctrl-group" id="sec-controls">
      <span class="ctrl-label">Scope:</span>
      <button type="button" class="active" data-sec="A">Primary n=30 (Sec A)</button>
      <button type="button" data-sec="AB1">+ n&gt;=30 Ladder/Rep (A+B1)</button>
    </div>
    <div class="ctrl-group">
      <button type="button" class="btn-export" id="export-csv-btn">Export CSV</button>
      <button type="button" class="btn-export" id="export-json-btn">Export JSON</button>
    </div>
  </section>

  <section class="panel">
    <h2>95% Paired Bootstrap CI Forest Plot (100% = Reference Solver Parity, 0% = Abstain Baseline)</h2>
    <div id="forest-container">
{static_forest_svg}
    </div>
  </section>

  <section class="panel">
    <h2>Exact Counterfactual Loss Breakdown (Solver Score Minus Agent Score, Zero-Residual Identity)</h2>
    <div id="cf-container">
{static_cf_svg}
    </div>
  </section>

  <div class="grid-2">
    <section class="panel">
      <h2>2x2 Harness x Tier Crossover (gemini-4-carbon, Paired Seeds 0-29)</h2>
      <table>
        <thead>
          <tr>
            <th>Cell / Contrast</th>
            <th class="num">Medium (n=30)</th>
            <th class="num">Hard (n=30)</th>
            <th class="num">Tier Drop (Hard - Med)</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td><strong>OpenCode MCP (Raw / LA)</strong></td>
            <td class="num">{fmt_signed(oc_med["mean"], 3)} / {fmt_signed(oc_med["luck_adjusted_score"], 3)}</td>
            <td class="num">{fmt_signed(oc_hard["mean"], 3)} / {fmt_signed(oc_hard["luck_adjusted_score"], 3)}</td>
            <td class="num">{fmt_signed(c2x2_raw["tier_drop_oc_hard_minus_med"]["point"], 3)} / {fmt_signed(c2x2_la["tier_drop_oc_hard_minus_med"]["point"], 3)}</td>
          </tr>
          <tr>
            <td><strong>In-Process (Raw / LA)</strong></td>
            <td class="num">{fmt_signed(ip_med["mean"], 3)} / {fmt_signed(ip_med["luck_adjusted_score"], 3)}</td>
            <td class="num">{fmt_signed(ip_hard["mean"], 3)} / {fmt_signed(ip_hard["luck_adjusted_score"], 3)}</td>
            <td class="num">{fmt_signed(c2x2_raw["tier_drop_ip_hard_minus_med"]["point"], 3)} / {fmt_signed(c2x2_la["tier_drop_ip_hard_minus_med"]["point"], 3)}</td>
          </tr>
          <tr>
            <td><strong>Reference Solver</strong></td>
            <td class="num">{fmt_signed(solver_med["mean"], 3)} / {fmt_signed(solver_med["luck_adjusted_score"], 3)}</td>
            <td class="num">{fmt_signed(solver_hard["mean"], 3)} / {fmt_signed(solver_hard["luck_adjusted_score"], 3)}</td>
            <td class="num">{fmt_signed(c2x2_raw["tier_drop_solver_hard_minus_med"]["point"], 3)} / {fmt_signed(c2x2_la["tier_drop_solver_hard_minus_med"]["point"], 3)}</td>
          </tr>
          <tr>
            <td><strong>Harness Contrast (OC - IP) Raw</strong></td>
            <td class="num">{fmt_signed(c2x2_raw["oc_minus_ip_medium"]["point"], 3)} [{fmt_signed(c2x2_raw["oc_minus_ip_medium"]["boot_ci95"][0], 3)}, {fmt_signed(c2x2_raw["oc_minus_ip_medium"]["boot_ci95"][1], 3)}] (p={c2x2_raw["oc_minus_ip_medium"]["p_boot_two_sided"]:.4f})</td>
            <td class="num">{fmt_signed(c2x2_raw["oc_minus_ip_hard"]["point"], 3)} [{fmt_signed(c2x2_raw["oc_minus_ip_hard"]["boot_ci95"][0], 3)}, {fmt_signed(c2x2_raw["oc_minus_ip_hard"]["boot_ci95"][1], 3)}] (p={c2x2_raw["oc_minus_ip_hard"]["p_boot_two_sided"]:.4f})</td>
            <td class="num"><strong>DiD {fmt_signed(c2x2_raw["did_hard_minus_medium"]["point"], 3)}</strong> [{fmt_signed(c2x2_raw["did_hard_minus_medium"]["boot_ci95"][0], 3)}, {fmt_signed(c2x2_raw["did_hard_minus_medium"]["boot_ci95"][1], 3)}] (p={c2x2_raw["did_hard_minus_medium"]["p_boot_two_sided"]:.4f})</td>
          </tr>
          <tr>
            <td><strong>Harness Contrast (OC - IP) LA</strong></td>
            <td class="num">{fmt_signed(c2x2_la["oc_minus_ip_medium"]["point"], 3)} [{fmt_signed(c2x2_la["oc_minus_ip_medium"]["boot_ci95"][0], 3)}, {fmt_signed(c2x2_la["oc_minus_ip_medium"]["boot_ci95"][1], 3)}] (p={c2x2_la["oc_minus_ip_medium"]["p_boot_two_sided"]:.4f})</td>
            <td class="num">{fmt_signed(c2x2_la["oc_minus_ip_hard"]["point"], 3)} [{fmt_signed(c2x2_la["oc_minus_ip_hard"]["boot_ci95"][0], 3)}, {fmt_signed(c2x2_la["oc_minus_ip_hard"]["boot_ci95"][1], 3)}] (p={c2x2_la["oc_minus_ip_hard"]["p_boot_two_sided"]:.4f})</td>
            <td class="num"><strong>DiD {fmt_signed(c2x2_la["did_hard_minus_medium"]["point"], 3)}</strong> [{fmt_signed(c2x2_la["did_hard_minus_medium"]["boot_ci95"][0], 3)}, {fmt_signed(c2x2_la["did_hard_minus_medium"]["boot_ci95"][1], 3)}] (p={c2x2_la["did_hard_minus_medium"]["p_boot_two_sided"]:.4f})</td>
          </tr>
        </tbody>
      </table>
      <p class="muted" style="margin:8px 0 0 0;">
        Hard behavioral comparison (n=30): OpenCode carbon plants <strong>{carbon_canaries:.1f}</strong> canaries ({carbon_interviews:.1f} interviews, 4 wrong accusations);
        In-Process carbon plants <strong>{inproc_canaries:.1f}</strong> canaries ({inproc_interviews:.1f} interviews, 1 wrong);
        OpenCode <code>gpt-5.5</code> plants <strong>{gpt55_canaries:.1f}</strong> canaries ({gpt55_interviews:.1f} interviews, 0 wrong);
        Reference Solver plants <strong>{solver_canaries:.1f}</strong> canaries (0.0 interviews, 1 wrong).
      </p>
    </section>

    <section class="panel">
      <h2>Judge Rerun Operating Characteristics (k=10 Hard Tasks, 1x10 vs 3x10 &amp; pass^3)</h2>
      <table>
        <thead>
          <tr>
            <th>Hard Cohort (n=30)</th>
            <th class="num">1-Run Acc</th>
            <th class="num">Calibrated pass^1</th>
            <th class="num">Calibrated pass^3 [95% CI]</th>
            <th class="num">Gamble (&lt;0.60) Worlds</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td><strong>Reference Solver</strong></td>
            <td class="num">{fmt_pct(pk_hard["solver"]["empirical_pass_1run"], 1)}</td>
            <td class="num">{fmt_pct(pk_hard["solver"]["pass_1"], 1)}</td>
            <td class="num">{esc(fmt_pct_ci(pk_hard["solver"]["pass_3"], pk_hard["solver"]["pass_3_ci95"][0], pk_hard["solver"]["pass_3_ci95"][1], 1))}</td>
            <td class="num">{pk_hard["solver"]["n_gamble_worlds_lt60"]}</td>
          </tr>
          <tr>
            <td><strong>In-Process gemini-4-carbon</strong></td>
            <td class="num">{fmt_pct(pk_hard["inproc-carbon"]["empirical_pass_1run"], 1)}</td>
            <td class="num">{fmt_pct(pk_hard["inproc-carbon"]["pass_1"], 1)}</td>
            <td class="num">{esc(fmt_pct_ci(pk_hard["inproc-carbon"]["pass_3"], pk_hard["inproc-carbon"]["pass_3_ci95"][0], pk_hard["inproc-carbon"]["pass_3_ci95"][1], 1))}</td>
            <td class="num">{pk_hard["inproc-carbon"]["n_gamble_worlds_lt60"]}</td>
          </tr>
          <tr>
            <td><strong>OpenCode gpt-5.5 (MCP)</strong></td>
            <td class="num">{fmt_pct(gpt55_hard["accuracy"], 1)}</td>
            <td class="num">{fmt_pct(gpt55_hard["accuracy"] * gpt55_hard["mean_p_accused"], 1)}</td>
            <td class="num">{fmt_pct(gpt55_hard["pass3_calibrated"], 1)}</td>
            <td class="num">0</td>
          </tr>
          <tr>
            <td><strong>OpenCode gemini-4-carbon (MCP)</strong></td>
            <td class="num">{fmt_pct(pk_hard["opencode-carbon"]["empirical_pass_1run"], 1)}</td>
            <td class="num">{fmt_pct(pk_hard["opencode-carbon"]["pass_1"], 1)}</td>
            <td class="num">{esc(fmt_pct_ci(pk_hard["opencode-carbon"]["pass_3"], pk_hard["opencode-carbon"]["pass_3_ci95"][0], pk_hard["opencode-carbon"]["pass_3_ci95"][1], 1))}</td>
            <td class="num">{pk_hard["opencode-carbon"]["n_gamble_worlds_lt60"]}</td>
          </tr>
          <tr>
            <td><strong>OpenCode gemini-3.5-flash (MCP)</strong></td>
            <td class="num">{fmt_pct(pk_hard["opencode-3.5-flash"]["empirical_pass_1run"], 1)}</td>
            <td class="num">{fmt_pct(pk_hard["opencode-3.5-flash"]["pass_1"], 1)}</td>
            <td class="num">{esc(fmt_pct_ci(pk_hard["opencode-3.5-flash"]["pass_3"], pk_hard["opencode-3.5-flash"]["pass_3_ci95"][0], pk_hard["opencode-3.5-flash"]["pass_3_ci95"][1], 1))}</td>
            <td class="num">{pk_hard["opencode-3.5-flash"]["n_gamble_worlds_lt60"]}</td>
          </tr>
        </tbody>
      </table>
      <p class="muted" style="margin:8px 0 0 0;">
        OpenCode carbon k=10 resampling (50,000 trials): Model A paired empirical <code>P(frontier &lt; oracle)</code> rises from
        <strong>{fmt_pct(ma_oc["raw"]["runs"]["R1"]["p_frontier_lt_oracle"], 1)}</strong> (1x10 raw) to
        <strong>{fmt_pct(ma_oc["raw"]["runs"]["R3"]["p_frontier_lt_oracle"], 1)}</strong> (3x10 raw) and
        <strong>{fmt_pct(ma_oc["luck_adjusted"]["runs"]["R3"]["p_frontier_lt_oracle"], 1)}</strong> (3x10 LA).
        Model B fixed-build posterior variance reduction from Rao-Blackwell luck adjustment is
        <strong>{mb_oc["analytical_decomposition"]["la_var_reduction_vs_raw_r1"]:.2f}x</strong> at 1x10 (effective n={mb_oc["analytical_decomposition"]["effective_n_at_k10"]:.1f}).
      </p>
    </section>
  </div>

  <section class="panel">
    <h2>Paired Headline Table (Section A Primary n=30 &amp; Section B1 n&gt;=30)</h2>
    <div style="overflow-x:auto;">
      <table id="headline-table">
        <thead>
          <tr>
            <th>Tier</th>
            <th>Sec</th>
            <th>Cohort / Harness &amp; Provenance</th>
            <th class="num">n</th>
            <th class="num">Mean +/- CI</th>
            <th class="num">Solver</th>
            <th class="num th-metric th-raw active-metric">Raw % Solver [95% CI]</th>
            <th class="num th-metric th-la">Luck-Adj % Solver [95% CI]</th>
            <th class="num th-metric th-win">Winnable % [95% CI]</th>
            <th class="num th-metric th-p3">Calibrated pass^3</th>
            <th class="num">Acc</th>
            <th class="num">False Acc</th>
            <th class="num">Abstain</th>
          </tr>
        </thead>
        <tbody id="headline-tbody">
{"".join(table_rows_html)}
        </tbody>
      </table>
    </div>
    <p class="muted" style="margin:10px 0 0 0;">
      Pre-registered G1 partial extension sensitivity (<code>f9fb7a4a</code>, stopped early for rehearsal quota; <code>n={g1_ext["extension_n"]}</code> valid seeds <code>{g1_ext["extension_seeds"]}</code>,
      {g1_ext["extension_infra_excluded"]} provider-quota attempts excluded): extension-only <code>{fmt_pct(g1_ext["extension_ratio"], 0)}</code> raw /
      <code>{fmt_pct(g1_ext["extension_luck_adj_ratio"], 0)}</code> LA; pooled <code>n={g1_ext["pooled_n"]}</code>:
      <strong>{fmt_pct_ci(g1_ext["pooled_ratio"], g1_ext["pooled_ratio_ci"][0], g1_ext["pooled_ratio_ci"][1], 0)}</strong> raw,
      <strong>{fmt_pct_ci(g1_ext["pooled_luck_adj_ratio"], g1_ext["pooled_luck_adj_ci"][0], g1_ext["pooled_luck_adj_ci"][1], 0)}</strong> LA.
    </p>
  </section>

  <section class="panel">
    <details>
      <summary>Section B2 Directional Multi-Model Thinking Ladder (n&lt;30, {len(b2_rows)} cells -- directional context only, never headline)</summary>
      <div style="overflow-x:auto; margin-top:8px;">
        <table id="b2-table">
          <thead>
            <tr>
              <th>Tier</th>
              <th>Model &amp; Thinking Level</th>
              <th class="num">n</th>
              <th class="num">Mean +/- CI</th>
              <th class="num">Raw % Solver [95% CI]</th>
              <th class="num">Luck-Adj % Solver [95% CI]</th>
              <th class="num">Winnable % [95% CI]</th>
              <th class="num">Calibrated pass^3</th>
            </tr>
          </thead>
          <tbody id="b2-tbody">
{"".join(b2_rows_html)}
          </tbody>
        </table>
      </div>
    </details>
  </section>
</div>

<script id="eval-v14-data" type="application/json">{payload_json}</script>
<script>
(function() {{
  var RAW = JSON.parse(document.getElementById("eval-v14-data").textContent);
  function unpack(cols, arr) {{
    return arr.map(function(vals) {{
      var obj = {{}};
      for (var i = 0; i < cols.length; i++) obj[cols[i]] = vals[i];
      return obj;
    }});
  }}
  var DATA = {{ rows: unpack(RAW.rc, RAW.r), b2: RAW.b2, cf: unpack(RAW.cc, RAW.cf) }};
  var state = {{ tier: "hard", metric: "raw", sec: "A" }};

  var METRIC_META = {{
    raw: {{ label: "Raw % Solver", key: "raw", lo: "raw_lo", hi: "raw_hi", min: -2.2, max: 1.6, dec: 0 }},
    la:  {{ label: "Luck-Adjusted % Solver", key: "la", lo: "la_lo", hi: "la_hi", min: -2.2, max: 1.4, dec: 0 }},
    win: {{ label: "Winnable %", key: "win", lo: "win_lo", hi: "win_hi", min: -2.1, max: 1.3, dec: 0 }},
    p3:  {{ label: "Calibrated pass^3", key: "p3", lo: "p3_lo", hi: "p3_hi", min: 0.0, max: 1.05, dec: 1 }}
  }};

  function escXml(s) {{
    return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  }}

  function fmtPct(v, dec) {{
    if (v === null || v === undefined || isNaN(v)) return "--";
    var p = v * 100.0;
    return dec === 0 ? Math.round(p) + "%" : p.toFixed(dec) + "%";
  }}

  function fmtCi(v, lo, hi, dec) {{
    var p = fmtPct(v, dec);
    if (lo === null || lo === undefined || hi === null || hi === undefined) return p;
    return p + " [" + fmtPct(lo, dec) + ", " + fmtPct(hi, dec) + "]";
  }}

  function fmtSigned(v, d) {{
    if (v === null || v === undefined || isNaN(v)) return "--";
    return (v >= 0 ? "+" : "-") + Math.abs(v).toFixed(d);
  }}

  function activeRows() {{
    return DATA.rows.filter(function(r) {{
      var secOk = state.sec === "AB1" ? (r.sec === "A" || r.sec === "B1") : (r.sec === "A");
      var tierOk = state.tier === "all" ? true : (r.tier === state.tier);
      return secOk && tierOk;
    }});
  }}

  function renderForest() {{
    var rows = activeRows();
    var m = METRIC_META[state.metric];
    var w = 860, left = 310, right = 725, plotW = right - left, rowH = 25, top = 42;
    var h = top + rows.length * rowH + 34;
    function xPos(v) {{
      var c = Math.max(m.min, Math.min(m.max, v));
      return left + ((c - m.min) / (m.max - m.min)) * plotW;
    }}
    var ticks = state.metric === "p3" ? [0.0, 0.25, 0.5, 0.75, 1.0] : [-2.0, -1.0, 0.0, 0.5, 1.0, 1.5];
    var out = [];
    out.push('<svg id="forest-svg" viewBox="0 0 ' + w + ' ' + h + '" role="img" aria-label="Paired 95% CI Forest Plot">');
    out.push('<rect x="0" y="0" width="' + w + '" height="' + h + '" fill="rgb(15, 23, 42)" rx="6"/>');
    out.push('<text x="14" y="24" fill="rgb(226, 232, 240)" font-size="13" font-weight="700">Paired 95% CI Forest Plot -- Tier: ' + escXml(state.tier) + ' | Metric: ' + escXml(m.label) + ' (' + rows.length + ' cohorts)</text>');
    for (var t = 0; t < ticks.length; t++) {{
      var tk = ticks[t];
      if (tk < m.min || tk > m.max) continue;
      var tx = xPos(tk).toFixed(1);
      var stroke = Math.abs(tk - 1.0) < 1e-6 ? "rgb(34, 197, 94)" : (Math.abs(tk) < 1e-6 ? "rgb(148, 163, 184)" : "rgb(51, 65, 85)");
      out.push('<line x1="' + tx + '" y1="' + (top - 6) + '" x2="' + tx + '" y2="' + (h - 26) + '" stroke="' + stroke + '" stroke-width="1" stroke-dasharray="4,3"/>');
      out.push('<text x="' + tx + '" y="' + (h - 10) + '" fill="rgb(148, 163, 184)" font-size="11" text-anchor="middle">' + Math.round(tk * 100) + '%</text>');
    }}
    var kindCol = {{ frontier: "rgb(56, 189, 248)", sensitivity: "rgb(251, 191, 36)", reference: "rgb(74, 222, 128)", baseline: "rgb(148, 163, 184)", replication: "rgb(244, 114, 182)", ladder_n_ge_30: "rgb(129, 140, 248)" }};
    for (var i = 0; i < rows.length; i++) {{
      var r = rows[i];
      var cy = top + i * rowH + 12;
      var val = r[m.key], lo = r[m.lo], hi = r[m.hi];
      var col = r.agent === "opencode:openai/gpt-5.5" ? "rgb(167, 139, 250)" : (kindCol[r.kind] || "rgb(148, 163, 184)");
      var tag = state.tier === "all" ? "[" + r.tier[0].toUpperCase() + "] " : "";
      var lbl = tag + r.label;
      if (lbl.length > 44) lbl = lbl.slice(0, 41) + "...";
      out.push('<text x="' + (left - 10) + '" y="' + (cy + 4) + '" fill="rgb(226, 232, 240)" font-size="11" text-anchor="end">' + escXml(lbl) + '</text>');
      if (lo !== null && hi !== null && lo !== undefined && hi !== undefined) {{
        var x1 = xPos(lo).toFixed(1), x2 = xPos(hi).toFixed(1);
        out.push('<line x1="' + x1 + '" y1="' + cy + '" x2="' + x2 + '" y2="' + cy + '" stroke="' + col + '" stroke-width="2.2"/>');
        out.push('<line x1="' + x1 + '" y1="' + (cy - 4) + '" x2="' + x1 + '" y2="' + (cy + 4) + '" stroke="' + col + '" stroke-width="1.5"/>');
        out.push('<line x1="' + x2 + '" y1="' + (cy - 4) + '" x2="' + x2 + '" y2="' + (cy + 4) + '" stroke="' + col + '" stroke-width="1.5"/>');
      }}
      if (val !== null && val !== undefined) {{
        out.push('<circle cx="' + xPos(val).toFixed(1) + '" cy="' + cy + '" r="4.2" fill="' + col + '"/>');
      }}
      out.push('<text x="' + (right + 8) + '" y="' + (cy + 4) + '" fill="rgb(226, 232, 240)" font-size="11">' + escXml(fmtCi(val, lo, hi, m.dec)) + '</text>');
    }}
    out.push('</svg>');
    document.getElementById("forest-container").innerHTML = out.join("");
  }}

  function renderCf() {{
    var list = DATA.cf.filter(function(c) {{ return state.tier === "all" ? true : c.tier === state.tier; }});
    var w = 860, left = 245, zeroX = 430, scale = 820.0, rowH = 38, top = 46;
    var h = top + list.length * rowH + 34;
    var comps = [
      ["cal_wrong", "Calibrated Wrong-Accuse", "rgb(248, 113, 113)"],
      ["missed_info", "Missed-Catch Info Gap", "rgb(251, 191, 36)"],
      ["ev_rescue", "EV Abstain Rescue", "rgb(251, 146, 60)"],
      ["timing_cost", "Timing & Cost Bleed", "rgb(56, 189, 248)"],
      ["solver_miss", "Solver-Miss Offset", "rgb(74, 222, 128)"]
    ];
    var out = [];
    out.push('<svg id="cf-svg" viewBox="0 0 ' + w + ' ' + h + '" role="img" aria-label="Counterfactual Gap Decomposition Bars">');
    out.push('<rect x="0" y="0" width="' + w + '" height="' + h + '" fill="rgb(15, 23, 42)" rx="6"/>');
    out.push('<text x="14" y="22" fill="rgb(226, 232, 240)" font-size="13" font-weight="700">Exact 5-Term Counterfactual Loss Decomposition -- Tier: ' + escXml(state.tier) + ' (solver_score - agent_score)</text>');
    var lx = 14;
    for (var k = 0; k < comps.length; k++) {{
      out.push('<rect x="' + lx + '" y="30" width="10" height="10" fill="' + comps[k][2] + '" rx="2"/>');
      out.push('<text x="' + (lx + 14) + '" y="39" fill="rgb(203, 213, 225)" font-size="10.5">' + escXml(comps[k][1]) + '</text>');
      lx += 162;
    }}
    var ticks = [-0.15, -0.10, -0.05, 0.0, 0.05, 0.10, 0.15, 0.20, 0.25];
    for (var t = 0; t < ticks.length; t++) {{
      var tx = (zeroX + ticks[t] * scale).toFixed(1);
      var st = Math.abs(ticks[t]) < 1e-6 ? "rgb(148, 163, 184)" : "rgb(51, 65, 85)";
      var ds = Math.abs(ticks[t]) < 1e-6 ? "" : ' stroke-dasharray="3,3"';
      out.push('<line x1="' + tx + '" y1="' + top + '" x2="' + tx + '" y2="' + (h - 24) + '" stroke="' + st + '" stroke-width="1"' + ds + '/>');
      out.push('<text x="' + tx + '" y="' + (h - 9) + '" fill="rgb(148, 163, 184)" font-size="10.5" text-anchor="middle">' + fmtSigned(ticks[t], 2) + '</text>');
    }}
    for (var i = 0; i < list.length; i++) {{
      var rec = list[i];
      var cy = top + i * rowH + 14;
      out.push('<text x="' + (left - 12) + '" y="' + (cy + 8) + '" fill="rgb(226, 232, 240)" font-size="11.5" text-anchor="end">' + escXml(rec.cohort + " (" + rec.tier + ")") + '</text>');
      var posC = zeroX, negC = zeroX;
      for (var c = 0; c < comps.length; c++) {{
        var v = rec[comps[c][0]] || 0;
        var bw = Math.abs(v) * scale;
        if (bw < 0.4) continue;
        if (v >= 0) {{
          out.push('<rect x="' + posC.toFixed(1) + '" y="' + (cy - 4) + '" width="' + bw.toFixed(1) + '" height="16" fill="' + comps[c][2] + '" rx="1.5"/>');
          posC += bw;
        }} else {{
          negC -= bw;
          out.push('<rect x="' + negC.toFixed(1) + '" y="' + (cy - 4) + '" width="' + bw.toFixed(1) + '" height="16" fill="' + comps[c][2] + '" rx="1.5"/>');
        }}
      }}
      out.push('<text x="645" y="' + (cy + 8) + '" fill="rgb(226, 232, 240)" font-size="11">gap ' + fmtSigned(rec.gap, 3) + ' [' + fmtSigned(rec.gap_lo, 3) + ', ' + fmtSigned(rec.gap_hi, 3) + ']</text>');
    }}
    out.push('</svg>');
    document.getElementById("cf-container").innerHTML = out.join("");
  }}

  function syncTables() {{
    var rows = activeRows();
    var hOut = [];
    for (var i = 0; i < rows.length; i++) {{
      var r = rows[i];
      var p3Str = r.p3_lo !== null ? fmtCi(r.p3, r.p3_lo, r.p3_hi, 1) : fmtPct(r.p3, 1);
      hOut.push(
        '<tr data-sec="' + escXml(r.sec) + '" data-tier="' + escXml(r.tier) + '">' +
        '<td><span class="pill pill-' + escXml(r.tier) + '">' + escXml(r.tier) + '</span></td>' +
        '<td>' + escXml(r.sec) + '</td>' +
        '<td class="lbl-cell"><strong>' + escXml(r.label) + '</strong><br><span class="muted">' + escXml(r.agent) + ' | sha ' + escXml(r.sha) + '</span></td>' +
        '<td class="num">' + r.n + '</td>' +
        '<td class="num">' + fmtSigned(r.mean, 3) + ' +/- ' + (r.score_ci !== null ? r.score_ci.toFixed(3) : "--") + '</td>' +
        '<td class="num">' + fmtSigned(r.solver, 3) + '</td>' +
        '<td class="num c-raw">' + escXml(fmtCi(r.raw, r.raw_lo, r.raw_hi, 0)) + '</td>' +
        '<td class="num c-la">' + escXml(fmtCi(r.la, r.la_lo, r.la_hi, 0)) + '</td>' +
        '<td class="num c-win">' + escXml(fmtCi(r.win, r.win_lo, r.win_hi, 0)) + '</td>' +
        '<td class="num c-p3">' + escXml(p3Str) + '</td>' +
        '<td class="num">' + fmtPct(r.acc, 1) + '</td>' +
        '<td class="num">' + fmtPct(r.facc, 1) + '</td>' +
        '<td class="num">' + fmtPct(r.abst, 1) + '</td></tr>'
      );
    }}
    document.getElementById("headline-tbody").innerHTML = hOut.join("");

    var bOut = [];
    for (var j = 0; j < DATA.b2.length; j++) {{
      var b = DATA.b2[j];
      if (state.tier !== "all" && b[0] !== state.tier) continue;
      bOut.push(
        '<tr><td><span class="pill pill-' + escXml(b[0]) + '">' + escXml(b[0]) + '</span></td>' +
        '<td>' + escXml(b[1]) + '</td>' +
        '<td class="num">' + b[2] + '</td>' +
        '<td class="num">' + fmtSigned(b[3], 3) + ' +/- ' + b[4].toFixed(3) + '</td>' +
        '<td class="num">' + escXml(fmtCi(b[5], b[6], b[7], 0)) + '</td>' +
        '<td class="num">' + escXml(fmtCi(b[8], b[9], b[10], 0)) + '</td>' +
        '<td class="num">' + escXml(fmtCi(b[11], b[12], b[13], 0)) + '</td>' +
        '<td class="num">' + fmtPct(b[14], 1) + '</td></tr>'
      );
    }}
    document.getElementById("b2-tbody").innerHTML = bOut.join("");

    var metrics = ["raw", "la", "win", "p3"];
    for (var m = 0; m < metrics.length; m++) {{
      var mk = metrics[m];
      var active = mk === state.metric;
      var cells = document.querySelectorAll(".c-" + mk + ", .th-" + mk);
      for (var c = 0; c < cells.length; c++) {{
        if (active) cells[c].classList.add("active-metric");
        else cells[c].classList.remove("active-metric");
      }}
    }}
  }}

  function updateAll() {{
    renderForest();
    renderCf();
    syncTables();
  }}

  function bindGroup(id, attr, field) {{
    var box = document.getElementById(id);
    box.addEventListener("click", function(ev) {{
      var btn = ev.target.closest("button");
      if (!btn || !btn.hasAttribute(attr)) return;
      state[field] = btn.getAttribute(attr);
      var btns = box.querySelectorAll("button");
      for (var i = 0; i < btns.length; i++) btns[i].classList.toggle("active", btns[i] === btn);
      updateAll();
    }});
  }}

  bindGroup("tier-controls", "data-tier", "tier");
  bindGroup("metric-controls", "data-metric", "metric");
  bindGroup("sec-controls", "data-sec", "sec");

  function downloadBlob(filename, mime, content) {{
    var blob = new Blob([content], {{ type: mime }});
    var url = URL.createObjectURL(blob);
    var a = document.createElement("a");
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  }}

  document.getElementById("export-json-btn").addEventListener("click", function() {{
    var out = {{ tier_filter: state.tier, metric: state.metric, scope: state.sec, rows: activeRows() }};
    downloadBlob("canary_v14_headline_" + state.tier + "_" + state.metric + ".json", "application/json", JSON.stringify(out, null, 2));
  }});

  document.getElementById("export-csv-btn").addEventListener("click", function() {{
    var cols = ["sec", "tier", "agent", "kind", "label", "n", "mean", "score_ci", "solver", "raw", "raw_lo", "raw_hi", "la", "la_lo", "la_hi", "win", "win_lo", "win_hi", "p3", "acc", "facc", "abst", "sha"];
    var lines = [cols.join(",")];
    var rows = activeRows();
    for (var i = 0; i < rows.length; i++) {{
      var r = rows[i];
      var vals = cols.map(function(k) {{
        var v = r[k];
        if (v === null || v === undefined) return "";
        var s = String(v);
        return s.indexOf(",") >= 0 || s.indexOf('"') >= 0 ? '"' + s.replace(/"/g, '""') + '"' : s;
      }});
      lines.push(vals.join(","));
    }}
    downloadBlob("canary_v14_headline_" + state.tier + "_" + state.metric + ".csv", "text/csv", lines.join("\\n"));
  }});

  syncTables();
}})();
</script>
</body>
</html>
"""
    return "\n".join(ln.lstrip() for ln in doc.splitlines()) + "\n"


def build_guide_markdown(sources: dict[str, Any], html_bytes_len: int) -> str:
    h1 = chr(35) + " "
    h2 = chr(35) * 2 + " "
    headline = sources["headline"]
    harness = sources["harness"]
    power = sources["power"]
    counterfactual = sources["counterfactual"]
    diagnostics = sources["diagnostics"]

    sec_a = headline["section_a"]
    oc_hard = find_section_a_row(sec_a, "hard", "opencode:google/gemini-4-carbon", "frontier")
    oc_med = find_section_a_row(sec_a, "medium", "opencode:google/gemini-4-carbon", "frontier")
    ip_hard = find_section_a_row(sec_a, "hard", "gemini:gemini-4-carbon", "frontier")
    ip_med = find_section_a_row(sec_a, "medium", "gemini:gemini-4-carbon", "frontier")
    gpt55_hard = find_section_a_row(sec_a, "hard", "opencode:openai/gpt-5.5", "frontier")
    solver_hard = find_section_a_row(sec_a, "hard", "solver", "reference")

    honest = diagnostics["provenance_and_honesty"]["honest_headline_scope_c59ecfd0"]
    reh = honest["harbor_judge_path_rehearsal"]
    reh_runs = reh["runs"]
    reh_ratios = counterfactual["panel_fix_a_and_headline"]["harbor_rehearsal_3run_ratios"]

    psd_hard = diagnostics["tiers"]["hard"]["cohorts"]
    carbon_canaries = float(harness["cells"]["hard_opencode"]["canaries_total_mean"])
    gpt55_canaries = (
        float(sources["gpt55_total_canaries"])
        if sources["gpt55_total_canaries"] is not None
        else float(psd_hard["opencode_gpt55"]["mean_canaries_planted"])
    )

    c2x2_raw = harness["contrasts_2x2"]["raw_score"]
    c2x2_la = harness["contrasts_2x2"]["luck_adjusted_score"]
    mb_oc = power["model_b_posterior_repeated_runs"]["opencode-carbon"]["analytical_decomposition"]

    lines = [
        f"{h1}Canary v1.4 Interactive Headline Dashboard & Export Guide",
        "",
        "Offline, zero-dependency HTML+SVG+JS explorer (`results/eval_v14/headline_dashboard_v14.html`) built deterministically from the five committed v1.4 evaluation JSON artifacts with zero API calls, zero external URLs, and zero `git` subprocess calls.",
        "",
        f"{h2}1. One-Command Build & Byte-Parity Verification",
        "",
        "```bash",
        "python scripts/build_eval_dashboard_v14.py",
        "python scripts/build_eval_dashboard_v14.py --check",
        "```",
        "",
        f"- Output HTML: `results/eval_v14/headline_dashboard_v14.html` ({html_bytes_len} bytes, budget < {MAX_HTML_BYTES} bytes, 100% offline self-contained).",
        "- Output Guide: `docs/reports/eval_dashboard_guide_v14.md`.",
        "- Shallow-CI compatible: reads committed JSON files directly via `pathlib` with zero `git` invocations (`--depth=1` safe) and zero timestamps.",
        "",
        f"{h2}2. Honest Scope & Provenance Summary (Banner Invariants)",
        "",
        "1. **MCP-Only `gemini-4-carbon` Primary Set (Post-Hoc Locked, Not Pre-Registered):**",
        f"   - Hard (`n={oc_hard['n']}`, seeds `0-29`): **{fmt_pct_ci(oc_hard['ratio'], oc_hard['ratio_lo'], oc_hard['ratio_hi'], 0)}** raw (`{fmt_signed(oc_hard['mean'], 3)} +/- {fmt_num(oc_hard['score_ci'], 3)}` vs solver `{fmt_signed(solver_hard['mean'], 3)}`), **{fmt_pct_ci(oc_hard['luck_adj_ratio'], oc_hard['luck_adj_lo'], oc_hard['luck_adj_hi'], 0)}** luck-adjusted (Wilcoxon `p={oc_hard['p_wilcoxon_luck']:.4f}`).",
        f"   - Medium (`n={oc_med['n']}`, seeds `0-29`): **{fmt_pct_ci(oc_med['ratio'], oc_med['ratio_lo'], oc_med['ratio_hi'], 0)}** raw, **{fmt_pct_ci(oc_med['luck_adj_ratio'], oc_med['luck_adj_lo'], oc_med['luck_adj_hi'], 0)}** luck-adjusted.",
        "   - Seed lock: commit `671ed96` (28 s after `8fd4dec`), a post-hoc lock against later reruns/cherry-picking rather than a pre-registration.",
        "2. **Harbor 3x10 Container Judge-Path Rehearsal (`afterquery-final` `1bc3e281`, `aa1c679e` / `5f9b3297`):**",
        f"   - `opencode-1`: `{fmt_signed(reh_runs['opencode-1']['mean'], 3)}` (**{reh_ratios[0]}**, `n={reh_runs['opencode-1']['n_valid']}`, `9/10` correct).",
        f"   - `opencode-2`: `{fmt_signed(reh_runs['opencode-2']['mean'], 3)}` (**{reh_ratios[1]}**, `n={reh_runs['opencode-2']['n_valid']}`, `10/10` correct).",
        f"   - `opencode-3`: `{fmt_signed(reh_runs['opencode-3']['mean'], 3)}` (**{reh_ratios[2]}** on `n={reh_runs['opencode-3']['n_valid']}` valid, 1 infra-excluded, `9/9` correct) vs oracle `+{reh_runs['opencode-1']['oracle_same_tasks']:.3f}` (`do_nothing` / `stop_early` `+0.000`, `0%`).",
        f"   - Container shell was used in `{HARBOR_SHELL_TRIALS}` trials -- **the gap did NOT reproduce in the container judge path**.",
        "3. **Pre-Registered Second Frontier Family (`opencode:openai/gpt-5.5`, `cf394894` / `ca0a0dc0`):**",
        f"   - Hard (`n={gpt55_hard['n']}`, seeds `0-29`, 13 MCP tools only): `{fmt_signed(gpt55_hard['mean'], 3)} +/- {fmt_num(gpt55_hard['score_ci'], 3)}`, **{fmt_pct_ci(gpt55_hard['ratio'], gpt55_hard['ratio_lo'], gpt55_hard['ratio_hi'], 0)}** raw, **{fmt_pct_ci(gpt55_hard['luck_adj_ratio'], gpt55_hard['luck_adj_lo'], gpt55_hard['luck_adj_hi'], 0)}** luck-adjusted (`28/28` accused correct; seeds `0` and `17` wrote text without calling `accuse`, scored `0.0`).",
        f"   - Behavioral driver: `gpt-5.5` plants `{gpt55_canaries:.1f}` canaries/episode vs `{carbon_canaries:.1f}` for `gemini-4-carbon` -- **matches solver (no gap)**.",
        "",
        f"{h2}3. Source Artifacts & Visual Panels",
        "",
        "| Committed Source JSON | Dashboard Component | Key Verified Metric |",
        "|---|---|---|",
        f"| `results/eval_v14/headline_gap_table_v14.json` | Paired CI Forest Plot & Interactive Table (Sec A/B1/B2) | Hard MCP carbon `65% [24%, 98%]` raw, `gpt-5.5` `101% [79%, 140%]` raw |",
        f"| `results/eval_v14/counterfactual_decomposition_v14.json` | 5-Term Counterfactual Loss Breakdown SVG | Hard MCP carbon gap `+0.177` (`+0.113` cal. wrong-accuse); `gpt-5.5` `-0.005` |",
        f"| `results/eval_v14/harness_and_tier_v14.json` | 2x2 Harness x Tier Crossover Summary | Raw DiD `{fmt_signed(c2x2_raw['did_hard_minus_medium']['point'], 3)}` (`p={c2x2_raw['did_hard_minus_medium']['p_boot_two_sided']:.4f}`), LA DiD `{fmt_signed(c2x2_la['did_hard_minus_medium']['point'], 3)}` (`p={c2x2_la['did_hard_minus_medium']['p_boot_two_sided']:.4f}`) |",
        f"| `results/eval_v14/judge_rerun_power_v14.json` | 1x10 vs 3x10 Rerun Operating Characteristics & `pass^3` | Rao-Blackwell `{mb_oc['la_var_reduction_vs_raw_r1']:.2f}x` 1-run variance reduction (eff. `n={mb_oc['effective_n_at_k10']:.1f}`) |",
        "| `results/eval_v14/paired_seed_diagnostics_v14.json` | Honest Disclosure Banner & Behavioral Diagnostics | Harbor rehearsal `93% / 116% / 131%`, shell in `20/28` trials |",
        "",
        f"{h2}4. Interactive Controls & Client-Side Export",
        "",
        "- **Tier Filter:** `hard` (default), `medium`, `all` (in-process hard/medium: "
        f"`{fmt_pct(ip_hard['ratio'], 0)}` / `{fmt_pct(ip_med['ratio'], 0)}` raw).",
        "- **Metric Toggle (ordered):** `Raw % Solver` (default first), `Luck-Adjusted % Solver` (second), `Winnable %`, `Calibrated pass^3`.",
        "- **Scope & Offline Export:** switch between `Section A` (`n=30` primary paired rows) and `Section A + B1` (`n>=30` replications & ladder), expand `Section B2` (`n<30` directional ladder), and export the active filtered table to CSV or JSON completely offline via `Blob` URLs.",
        "",
    ]
    return "\n".join(lines)


def validate_outputs(html_text: str, md_text: str) -> list[str]:
    errors: list[str] = []
    html_bytes = html_text.encode("utf-8")
    if len(html_bytes) >= MAX_HTML_BYTES:
        errors.append(f"HTML exceeds 60 KB limit: {len(html_bytes)} >= {MAX_HTML_BYTES}")

    lower_html = html_text.lower()
    http_scheme = "http" + "://"
    https_scheme = "https" + "://"
    if http_scheme in lower_html or https_scheme in lower_html:
        errors.append("External URL scheme detected in HTML output")

    for label, content in (("html", html_text), ("md", md_text)):
        for bad in BANNED_SUBSTRINGS:
            if bad in content:
                errors.append(f"Banned substring {bad!r} found in {label}")
        if MOLE_ID_RE.search(content):
            errors.append(f"Potential employee/mole ID token matched in {label}")
        if "mole_id" in content.lower():
            errors.append(f"mole_id reference found in {label}")

    required_html_tokens = (
        "65% [24%, 98%]",
        "72% [52%, 91%]",
        "671ed96",
        "1bc3e281",
        "aa1c679e",
        "5f9b3297",
        "+0.472",
        "93%",
        "+0.585",
        "116%",
        "+0.626",
        "131%",
        "+0.506",
        "20/28",
        "cf394894",
        "ca0a0dc0",
        "+0.504 +/- 0.064",
        "101% [79%, 140%]",
        "84% [67%, 103%]",
        "17.2",
        "8.5",
        "Raw % Solver",
        "Luck-Adjusted % Solver",
        "Winnable %",
        "Calibrated pass^3",
    )
    for tok in required_html_tokens:
        if tok not in html_text:
            errors.append(f"Missing required token in HTML: {tok!r}")

    return errors


def generate_artifacts(root: Path = ROOT) -> tuple[str, str]:
    sources = load_sources(root)
    html_text = build_dashboard_html(sources)
    html_len = len(html_text.encode("utf-8"))
    md_text = build_guide_markdown(sources, html_len)
    errs = validate_outputs(html_text, md_text)
    if errs:
        raise ValueError("Dashboard validation failed: " + "; ".join(errs))
    return html_text, md_text


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build deterministic Canary v1.4 HTML+SVG judge explorer.")
    parser.add_argument("--check", action="store_true", help="Verify byte parity of committed HTML and MD outputs.")
    parser.add_argument("--root", type=Path, default=ROOT, help="Repository root path.")
    args = parser.parse_args(argv)

    root = args.root.resolve()
    html_path = root / DEFAULT_HTML_REL
    md_path = root / DEFAULT_GUIDE_REL

    expected_html, expected_md = generate_artifacts(root)
    html_bytes = expected_html.encode("utf-8")
    md_bytes = expected_md.encode("utf-8")

    if args.check:
        mismatches: list[str] = []
        if not html_path.is_file():
            mismatches.append(f"Missing {html_path}")
        elif html_path.read_bytes() != html_bytes:
            mismatches.append(f"Byte mismatch in {html_path}")
        if not md_path.is_file():
            mismatches.append(f"Missing {md_path}")
        elif md_path.read_bytes() != md_bytes:
            mismatches.append(f"Byte mismatch in {md_path}")
        if mismatches:
            for msg in mismatches:
                print(f"CHECK FAILED: {msg}", file=sys.stderr)
            return 1
        print(
            f"OK: {DEFAULT_HTML_REL} ({len(html_bytes)} B) and {DEFAULT_GUIDE_REL} ({len(md_bytes)} B) byte-identical."
        )
        return 0

    html_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.parent.mkdir(parents=True, exist_ok=True)
    html_path.write_bytes(html_bytes)
    md_path.write_bytes(md_bytes)
    print(f"Wrote {DEFAULT_HTML_REL} ({len(html_bytes)} B) and {DEFAULT_GUIDE_REL} ({len(md_bytes)} B).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
