from __future__ import annotations

import ast
import io
import json
from pathlib import Path
import re
import socket
import sys
import tokenize
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from canary.analysis.gap import mean_ci
from canary.llm.pricing import cost as price_cost

INDEX_PATH = REPO_ROOT / "results" / "gemini" / "roles_carbon" / "multimodal_evidence" / "index.json"
REPORT_PATH = REPO_ROOT / "docs" / "gemini" / "reports" / "multimodal_ablation_carbon.md"
SELF_PATH = Path(__file__).resolve()

UNICODE_DASH_CODEPOINTS = (*range(0x2010, 0x2016), 0x2212, 0xFE58, 0xFE63, 0xFF0D)
UNICODE_DASHES = tuple(chr(cp) for cp in UNICODE_DASH_CODEPOINTS)
CO_AUTHORED_MARKER = "-".join(("Co", "Authored", "By"))

FORBIDDEN_IMPORT_PREFIXES = (
    "google",
    "genai",
    "openai",
    "anthropic",
    "requests",
    "httpx",
    "urllib",
    "http",
    "aiohttp",
)

GOOGLE_KEY_RE = re.compile(r"(?<![A-Za-z0-9_\-])AIza[0-9A-Za-z_\-]{8,60}(?![A-Za-z0-9_\-=])")
SK_KEY_RE = re.compile(r"(?<![A-Za-z0-9_])sk-[A-Za-z0-9_\-]{12,}")
OAUTH_RE = re.compile(r"(?<![A-Za-z0-9_])ya29\.[0-9A-Za-z_\-]{12,}")


def _blocked_socket(*_args: object, **_kwargs: object) -> Any:
    raise RuntimeError("live network and API calls are forbidden in keyless multimodal ablation report tests")


@pytest.fixture(autouse=True)
def _keyless_airgapped_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for env_key in (
        "GEMINI_API_KEY",
        "GOOGLE_GENERATIVE_AI_API_KEY",
        "GOOGLE_API_KEY",
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "XAI_API_KEY",
    ):
        monkeypatch.setenv(env_key, "")
    monkeypatch.delenv("GEMINI_GATEWAY_URL", raising=False)
    monkeypatch.setattr(socket.socket, "connect", _blocked_socket)
    monkeypatch.setattr(socket.socket, "connect_ex", _blocked_socket)
    monkeypatch.setattr(socket, "create_connection", _blocked_socket)


def _load_index() -> dict[str, Any]:
    assert INDEX_PATH.is_file(), INDEX_PATH
    return json.loads(INDEX_PATH.read_text(encoding="utf-8"))


def _load_report() -> str:
    assert REPORT_PATH.is_file(), REPORT_PATH
    return REPORT_PATH.read_text(encoding="utf-8")


def _scan_secrets(text: str) -> list[str]:
    hits: list[str] = []
    if GOOGLE_KEY_RE.search(text):
        hits.append("google_api_key")
    if SK_KEY_RE.search(text):
        hits.append("sk_api_key")
    if OAUTH_RE.search(text):
        hits.append("oauth_token")
    return hits


def _parse_md_tables(md_text: str) -> list[tuple[list[str], list[list[str]]]]:
    tables: list[tuple[list[str], list[list[str]]]] = []
    lines = md_text.splitlines()
    idx = 0
    while idx < len(lines):
        line = lines[idx].strip()
        if line.startswith("|") and line.endswith("|") and idx + 1 < len(lines):
            sep = lines[idx + 1].strip()
            if sep.startswith("|") and "-" in sep:
                headers = [cell.strip() for cell in line.strip("|").split("|")]
                rows: list[list[str]] = []
                idx += 2
                while idx < len(lines):
                    rline = lines[idx].strip()
                    if not (rline.startswith("|") and rline.endswith("|")):
                        break
                    rows.append([cell.strip() for cell in rline.strip("|").split("|")])
                    idx += 1
                tables.append((headers, rows))
                continue
        idx += 1
    return tables


def _compute_watermark_normal_cis(index_data: dict[str, Any]) -> dict[str, dict[str, float]]:
    dedup: dict[tuple[str, int], tuple[float, float]] = {}
    for run in index_data["runs"]:
        if run["subfamily"] != "watermark_memo_ablation":
            continue
        comp_path = REPO_ROOT / run["run_dir"] / "comparison.json"
        comp = json.loads(comp_path.read_text(encoding="utf-8"))
        default_tier = str(comp.get("tier") or "medium")
        for row in comp["per_seed"]:
            tier = str(row.get("tier") or default_tier)
            seed = int(row["seed"])
            mm_score = float(row["multimodal_carbon"]["score"])
            bl_score = float(row["blind_no_vision"]["score"])
            dedup[(tier, seed)] = (mm_score, bl_score)

    result: dict[str, dict[str, float]] = {}
    for slice_name in ("medium", "hard", "overall"):
        vals = [
            pair
            for (tier, _seed), pair in sorted(dedup.items())
            if slice_name == "overall" or tier == slice_name
        ]
        mm_m, mm_h = mean_ci([v[0] for v in vals])
        bl_m, bl_h = mean_ci([v[1] for v in vals])
        df_m, df_h = mean_ci([v[0] - v[1] for v in vals])
        result[slice_name] = {
            "mm_mean": mm_m,
            "mm_half": mm_h,
            "bl_mean": bl_m,
            "bl_half": bl_h,
            "df_mean": df_m,
            "df_half": df_h,
        }
    return result


def _fmt_pct_trim(ratio: float) -> str:
    pct = ratio * 100.0
    if abs(pct - round(pct, 1)) < 1e-6:
        return f"{pct:.1f}%"
    return f"{pct:.2f}%"


def _fmt_pct_2d_unit1(ratio: float) -> str:
    if ratio in (0.0, 1.0):
        return f"{ratio * 100.0:.1f}%"
    return f"{ratio * 100.0:.2f}%"


def _verify_report_against_index(report_text: str, index_data: dict[str, Any]) -> None:
    totals = index_data["totals"]
    usage = totals["usage"]
    hyg = index_data["hygiene"]
    sfs = index_data["subfamilies"]

    wm = sfs["watermark_memo_ablation"]
    dos = sfs["multi_image_incident_dossier"]
    soc = sfs["soc_access_heatmap_vision"]
    ch = sfs["visual_chart_forensics"]

    eval_samples = (
        int(wm["batch_episodes_total"])
        + int(dos["unique_worlds"])
        + int(soc["total_world_evaluations"])
        + int(ch["total_charts_evaluated"])
    )
    unique_samples = (
        int(wm["unique_paired_episodes"])
        + int(dos["unique_worlds"])
        + int(soc["unique_worlds"])
        + int(ch["unique_source_episodes"])
    )

    assert index_data["environment_scope"] in report_text
    assert index_data["target_model"] in report_text
    assert "Part.from_bytes" in report_text
    assert "a8f99c2537c91d72" in report_text
    assert "8df71cf570bb48bc" in report_text
    assert "docs/gemini/validation.md" in report_text
    assert index_data["latest_run_timestamp"] in report_text
    assert f"0..{hyg['max_observed_seed']}" in report_text
    assert (
        f"all `{totals['run_count']}` runs (`{totals['images_read_by_model']}` `image/png` files, "
        f"`{totals['image_bytes_verified']:,}` bytes)"
    ) in report_text

    tables = _parse_md_tables(report_text)
    assert len(tables) == 9

    suite_rows = {r[0]: r[1] for r in tables[0][1]}
    assert f"`{totals['run_count']}` (`{totals['scanned_run_count']}` scanned, `{totals['rejected_run_count']}` rejected) across `{totals['subfamily_count']}` subfamilies" in suite_rows["Verified Run Folders"]
    assert f"`{eval_samples}`" in suite_rows["Evaluated Samples"]
    assert f"`{unique_samples}` deduplicated unique" in suite_rows["Evaluated Samples"]
    assert f"`{totals['images_read_by_model']}`" in suite_rows["Native PNGs Read (`Part.from_bytes`)"]
    assert f"`{totals['image_bytes_verified']:,}`" in suite_rows["Native PNGs Read (`Part.from_bytes`)"]
    assert suite_rows["Gemini API Calls"] == f"`{usage['calls']}`"
    assert (
        f"`{usage['in']:,}` in / `{usage['out']:,}` out / `{usage['thinking']:,}` thinking / `{usage['cached']}` cached"
        == suite_rows["Tokens (Input / Output / Thinking / Cached)"]
    )
    assert f"`${usage['cost_usd']:.6f}` USD" in suite_rows["Pricing-Reconciled API Cost"]
    assert f"`{usage['latency_s']:,.3f}` s" in suite_rows["Pricing-Reconciled API Cost"]

    sf_alloc_rows = {r[0]: r for r in tables[1][1]}
    expected_sf_samples = {
        "watermark_memo_ablation": (int(wm["batch_episodes_total"]), int(wm["unique_paired_episodes"])),
        "multi_image_incident_dossier": (int(dos["unique_worlds"]), int(dos["unique_worlds"])),
        "soc_access_heatmap_vision": (int(soc["total_world_evaluations"]), int(soc["unique_worlds"])),
        "visual_chart_forensics": (int(ch["total_charts_evaluated"]), int(ch["unique_source_episodes"])),
    }
    for sf_id, (n_eval, n_uniq) in expected_sf_samples.items():
        sf_obj = sfs[sf_id]
        sf_u = sf_obj["usage"]
        row = sf_alloc_rows[f"`{sf_id}`"]
        assert row[2] == f"`{sf_obj['run_count']}`"
        assert row[3] == f"`{n_eval}` (`{n_uniq}`)"
        assert row[4] == f"`{sf_obj['images_read']}`"
        assert row[5] == f"`{sf_u['calls']}`"
        assert row[6] == f"`{sf_u['in']:,} / {sf_u['out']:,} / {sf_u['thinking']:,}`"
        assert row[7] == f"`${sf_u['cost_usd']:.6f}`"

    tot_alloc = sf_alloc_rows["**Total**"]
    assert tot_alloc[2] == f"**`{totals['run_count']}`**"
    assert tot_alloc[3] == f"**`{eval_samples}` (`{unique_samples}`)**"
    assert tot_alloc[4] == f"**`{totals['images_read_by_model']}`**"
    assert tot_alloc[5] == f"**`{usage['calls']}`**"
    assert tot_alloc[6] == f"**`{usage['in']:,} / {usage['out']:,} / {usage['thinking']:,}`**"
    assert tot_alloc[7] == f"**`${usage['cost_usd']:.6f}`**"

    wm_cis = _compute_watermark_normal_cis(index_data)
    ov_wm = wm["by_tier"]["overall"]
    ov_ci = wm_cis["overall"]
    assert (
        f"**Pooled unique (`n={wm['unique_paired_episodes']}`, `{ov_wm['scans_inspected']}` PNG scans):** "
        f"`gemini-4-carbon` scores `{ov_wm['multimodal_mean_score']:+.4f} +/- {ov_ci['mm_half']:.4f}` "
        f"vs `{ov_wm['blind_mean_score']:+.4f} +/- {ov_ci['bl_half']:.4f}` blind, "
        f"achieving a paired visual lift of `{ov_wm['paired_score_delta']:+.4f} +/- {ov_ci['df_half']:.4f}`"
    ) in report_text
    assert f"`{ov_wm['scans_exact_matches']}/{ov_wm['scans_inspected']}` (`100.0%`) watermark readout accuracy" in report_text
    assert f"`{wm['batch_scans_exact']}/{wm['batch_scans_total']}`" in report_text
    assert f"`{wm['batch_canary_scans_exact']}/{wm['batch_canary_scans_total']}`" in report_text

    wm_tier_rows = {r[0]: r for r in tables[2][1]}
    for sl in ("medium", "hard", "overall"):
        bt = wm["by_tier"][sl]
        nci = wm_cis[sl]
        row = wm_tier_rows[f"`{sl}`"]
        assert row[1] == f"`{bt['n_unique_episodes']}`"
        ocr_lo, ocr_hi = bt["ocr_watermark_accuracy_ci95"]
        assert (
            f"`{bt['scans_exact_matches']}/{bt['scans_inspected']}` "
            f"(`{bt['ocr_watermark_accuracy'] * 100.0:.1f}%`, `[{ocr_lo:.4f}, {ocr_hi:.4f}]`)"
        ) == row[3]
        assert f"`{bt['canary_scans_exact_matches']}/{bt['canary_scans_inspected']}` (`{bt['canary_watermark_accuracy'] * 100.0:.1f}%`)" == row[4]

        mm_lo, mm_hi = bt["multimodal_mean_ci95"]
        assert (
            f"`{bt['multimodal_mean_score']:+.4f} +/- {nci['mm_half']:.4f}` "
            f"(`[{mm_lo:+.4f}, {mm_hi:+.4f}]`)"
        ) == row[5]

        bl_lo, bl_hi = bt["blind_mean_ci95"]
        assert (
            f"`{bt['blind_mean_score']:+.4f} +/- {nci['bl_half']:.4f}` "
            f"(`[{bl_lo:+.4f}, {bl_hi:+.4f}]`)"
        ) == row[6]

        df_lo, df_hi = bt["paired_score_delta_ci95"]
        assert (
            f"`{bt['paired_score_delta']:+.4f} +/- {nci['df_half']:.4f}` "
            f"(`[{df_lo:+.4f}, {df_hi:+.4f}]`)"
        ) == row[7]

        macc_lo, macc_hi = bt["multimodal_accuracy_ci95"]
        bacc_lo, bacc_hi = bt["blind_accuracy_ci95"]
        assert f"`[{macc_lo:.4f}, {macc_hi:.4f}]`" in row[8]
        assert f"`[{bacc_lo:.4f}, {bacc_hi:.4f}]`" in row[8]
        assert f"`{_fmt_pct_trim(bt['blind_accuracy'])}`" in row[8]
        assert f"`+{_fmt_pct_trim(bt['paired_accuracy_delta'])}`" in row[8]
        assert row[9] == f"`{bt['oracle_recovery_ratio'] * 100.0:.1f}%` (`{bt['oracle_mean_score']:+.4f}`)"

    wm_batch_rows = {r[0]: r for r in tables[3][1]}
    assert len(wm_batch_rows) == len(wm["runs"])
    for brun in wm["runs"]:
        brow = wm_batch_rows[f"`{brun['run_id']}`"]
        assert brow[1] == f"`{brun['tier']}`"
        assert brow[2] == f"`{brun['seeds']}`"
        assert brow[3] == f"`{brun['n_episodes']}`"
        assert brow[4] == f"`{brun['vision_exact_scans']}/{brun['n_scans']}`"
        assert brow[5] == f"`{brun['multimodal_mean_score']:+.4f}`"
        assert brow[6] == f"`{brun['blind_mean_score']:+.4f}`"
        assert brow[7] == f"`{brun['oracle_mean_score']:+.4f}`"
        assert brow[8] == f"`{brun['multimodal_accuracy'] * 100.0:.1f}%`"
        assert brow[9] == f"`{brun['blind_accuracy'] * 100.0:.1f}%`"

    dos_rows = {r[0]: r for r in tables[4][1]}
    for sl in ("medium", "hard", "overall"):
        bt = dos["by_tier"][sl]
        n_w = int(bt["n_worlds"])
        row = dos_rows[f"`{sl}`"]
        assert row[1] == f"`{n_w}`"
        assert row[2] == f"`{n_w * int(dos['images_per_call'])}`"
        m_lo, m_hi = bt["top1_mole_accuracy_ci95"]
        assert (
            f"`{bt['top1_mole_hits']}/{n_w}` (`{_fmt_pct_2d_unit1(bt['top1_mole_accuracy'])}`, `[{m_lo:.4f}, {m_hi:.4f}]`)"
            == row[3]
        )
        assert row[4] == f"`{bt['top3_mole_hits']}/{n_w}` (`{_fmt_pct_2d_unit1(bt['top3_mole_hit_rate'])}`)"
        d_lo, d_hi = bt["top1_decoy_accuracy_ci95"]
        assert (
            f"`{bt['top1_decoy_hits']}/{n_w}` (`{_fmt_pct_2d_unit1(bt['top1_decoy_accuracy'])}`, `[{d_lo:.4f}, {d_hi:.4f}]`)"
            == row[5]
        )
        assert row[6] == f"`{bt['decoy_identified_hits']}/{n_w}` (`{bt['decoy_identified_rate'] * 100.0:.1f}%`)"
        assert row[7] == f"`{bt['avoided_framing_trap_hits']}/{n_w}` (`{bt['avoided_framing_trap_rate'] * 100.0:.1f}%`)"
        assert row[8] == f"`{bt['memo_scans_matched']}/{bt['memo_scans_total']}` (`{bt['memo_scan_readout_accuracy'] * 100.0:.1f}%`)"
        assert row[9] == f"`{bt['suspect_dept_hits']}/{n_w}` (`{_fmt_pct_2d_unit1(bt['suspect_dept_accuracy'])}`)"
        assert row[10] == f"`{bt['image1_only_mole_accuracy'] * 100.0:.1f}%`"
        traps = round(float(bt["image1_only_decoy_trap_rate"]) * n_w)
        assert row[11] == f"`{traps}/{n_w}` (`{_fmt_pct_2d_unit1(bt['image1_only_decoy_trap_rate'])}`)"
        assert row[12] == f"`+{_fmt_pct_2d_unit1(bt['mole_accuracy_delta_vs_single_image'])}` (`{bt['mole_accuracy_delta_vs_single_image']:+.4f}`)"

    soc_eval_rows = {r[0]: r for r in tables[5][1]}
    soc_slices = {
        "`pooled_all_evaluations`": soc["pooled_all_evaluations"],
        "`deduplicated_unique_worlds`": soc["deduplicated_unique_worlds"],
        "`medium` (unique)": soc["by_tier_unique_worlds"]["medium"],
        "`hard` (unique)": soc["by_tier_unique_worlds"]["hard"],
    }
    for label, sl_obj in soc_slices.items():
        n_s = int(sl_obj["n"])
        row = soc_eval_rows[label]
        assert row[1] == f"`{n_s}`"
        m_lo, m_hi = sl_obj["top1_mole_accuracy_ci95"]
        assert (
            f"`{sl_obj['top1_mole_hits']}/{n_s}` (`{_fmt_pct_2d_unit1(sl_obj['top1_mole_accuracy'])}`, `[{m_lo:.4f}, {m_hi:.4f}]`)"
            == row[2]
        )
        assert row[3] == f"`{sl_obj['top3_mole_hits']}/{n_s}` (`{sl_obj['top3_mole_hit_rate'] * 100.0:.1f}%`)"
        d_lo, d_hi = sl_obj["top1_decoy_accuracy_ci95"]
        assert (
            f"`{sl_obj['top1_decoy_hits']}/{n_s}` (`{sl_obj['top1_decoy_accuracy'] * 100.0:.1f}%`, `[{d_lo:.4f}, {d_hi:.4f}]`)"
            == row[4]
        )
        assert row[5] == f"`{sl_obj['avoided_framing_trap_hits']}/{n_s}` (`{sl_obj['avoided_framing_trap_rate'] * 100.0:.1f}%`)"
        assert (
            f"`{sl_obj['naive_mole_hits']}/{n_s}` (`{sl_obj['naive_mole_accuracy'] * 100.0:.1f}%`; "
            f"`{sl_obj['naive_trapped_by_decoy_hits']}/{n_s}` = `{sl_obj['naive_trapped_by_decoy_rate'] * 100.0:.1f}%` trapped)"
            == row[6]
        )
        assert row[7] == f"`+{_fmt_pct_2d_unit1(sl_obj['mole_accuracy_delta_vs_naive'])}` (`{sl_obj['mole_accuracy_delta_vs_naive']:+.4f}`)"
        assert row[8] == f"`{sl_obj['mean_confidence']:.4f}`"
        assert row[9] == f"`{sl_obj['mean_brier_score']:.6f}`"

    soc_cal_rows = {r[0]: r for r in tables[6][1]}
    for cal_key in ("all_paired_worlds", "hard_seeds_8to11", "medium_seeds_8to9"):
        cal_obj = soc["thinking_level_calibration"][cal_key]
        row = soc_cal_rows[f"`{cal_key}`"]
        assert row[1] == f"`{cal_obj['n_paired_worlds']}`"
        assert row[2] == f"`{', '.join(cal_obj['worlds'])}`"
        low = cal_obj["low"]
        high = cal_obj["high"]
        assert row[3] == f"`{low['top1_mole_accuracy'] * 100.0:.1f}% / {low['top1_decoy_accuracy'] * 100.0:.1f}%`"
        assert row[4] == f"`{high['top1_mole_accuracy'] * 100.0:.1f}% / {high['top1_decoy_accuracy'] * 100.0:.1f}%`"
        assert row[5] == f"`{low['thinking_tokens']:,}` (`${low['cost_usd']:.6f}`)"
        assert row[6] == f"`{high['thinking_tokens']:,}` (`${high['cost_usd']:.6f}`)"
        assert row[7] == f"`{low['mean_confidence']:.4f}` / `{low['mean_brier_score']:.6f}`"
        assert row[8] == f"`{high['mean_confidence']:.4f}` / `{high['mean_brier_score']:.6f}`"
        assert row[9] == f"`{cal_obj['brier_delta_high_minus_low']:.6f}`"
        assert row[10] == f"`{cal_obj['brier_improvement_ratio_low_over_high']:.2f}x`"

    v13_charts = sum(
        int(r["n_images_read_by_model"])
        for r in index_data["runs"]
        if r["subfamily"] == "visual_chart_forensics" and r["tiers_version"] == "v1.3"
    )
    v14_charts = sum(
        int(r["n_images_read_by_model"])
        for r in index_data["runs"]
        if r["subfamily"] == "visual_chart_forensics" and r["tiers_version"] == "v1.4"
    )
    assert v13_charts + v14_charts == int(ch["total_charts_evaluated"])

    ch_rows = tables[7][1]
    assert len(ch_rows) == 2
    pooled_ch = ch["pooled_all_charts"]
    uniq_ch = ch["deduplicated_unique_episodes"]
    v14_uniq = int(uniq_ch["v14_entropy_lag_total"])
    v13_uniq = int(uniq_ch["n_charts"]) - v14_uniq

    for row, cobj, n_v13, n_v14 in (
        (ch_rows[0], pooled_ch, v13_charts, v14_charts),
        (ch_rows[1], uniq_ch, v13_uniq, v14_uniq),
    ):
        n_c = int(cobj["n_charts"])
        assert f"(`{n_v13}` `v1.3` + `{n_v14}` `v1.4`)" in row[0]
        assert row[1] == f"`{n_c}`"
        ev_lo, ev_hi = cobj["ev_threshold_accuracy_ci95"]
        assert (
            f"`{cobj['ev_threshold_hits']}/{n_c}` (`{cobj['ev_threshold_accuracy'] * 100.0:.1f}%`, `[{ev_lo:.4f}, {ev_hi:.4f}]`)"
            == row[2]
        )
        assert row[3] == f"`{cobj['stop_day_exact_hits']}/{n_c}` (`{cobj['stop_day_exact_accuracy'] * 100.0:.1f}%`)"
        assert row[4] == f"`{cobj['stop_day_within_1_hits']}/{n_c}` (`{cobj['stop_day_within_1_accuracy'] * 100.0:.1f}%`)"
        assert row[5] == f"`{cobj['hidden_bleed_gap_hits']}/{n_c}` (`{cobj['hidden_bleed_gap_accuracy'] * 100.0:.1f}%`)"
        assert (
            f"`{cobj['v14_entropy_lag_hits']}/{cobj['v14_entropy_lag_total']}` (`{cobj['v14_entropy_lag_accuracy'] * 100.0:.1f}%`)"
            == row[6]
        )
        assert (
            f"`{cobj['v14_outcome_pattern_hits']}/{cobj['v14_outcome_pattern_total']}` (`{cobj['v14_outcome_pattern_accuracy'] * 100.0:.1f}%`)"
            == row[7]
        )

    for cluster_name, cnt in pooled_ch["cluster_diagnoses"].items():
        assert f"`{cluster_name}={cnt}`" in report_text
    for cluster_name, cnt in uniq_ch["cluster_diagnoses"].items():
        assert f"`{cluster_name}={cnt}`" in report_text

    ledger_rows = tables[8][1]
    assert len(ledger_rows) == len(index_data["runs"]) + 1
    for lrow, run_obj in zip(ledger_rows[:-1], index_data["runs"]):
        ru = run_obj["usage"]
        assert lrow[0] == f"`{run_obj['run_id']}`"
        assert lrow[1] == f"`{run_obj['subfamily']}`"
        assert lrow[2] == f"`{run_obj['subrole']}`"
        assert lrow[3] == f"`{run_obj['tiers_version']}`"
        assert lrow[4] == f"`{run_obj['thinking_level']}`"
        assert lrow[5] == f"`{run_obj['commit']}`"
        assert lrow[6] == f"`{run_obj['n_images_read_by_model']}`"
        assert lrow[7] == f"`{ru['calls']}`"
        assert lrow[8] == f"`{ru['in']:,} / {ru['out']:,} / {ru['thinking']:,}`"
        assert lrow[9] == f"`${ru['cost_usd']:.6f}`"

        priced = price_cost(
            run_obj["model_id"],
            int(ru["in"]),
            int(ru["out"]) + int(ru["thinking"]),
            int(ru["cached"]),
        )
        expected_usd = float(priced.get("cost_usd_est", priced.get("cost_usd", 0.0)))
        assert float(ru["cost_usd"]) == pytest.approx(expected_usd, abs=1e-5)

    ledger_total = ledger_rows[-1]
    assert ledger_total[0] == "**Total**"
    assert ledger_total[6] == f"**`{totals['images_read_by_model']}`**"
    assert ledger_total[7] == f"**`{usage['calls']}`**"
    assert ledger_total[8] == f"**`{usage['in']:,} / {usage['out']:,} / {usage['thinking']:,}`**"
    assert ledger_total[9] == f"**`${usage['cost_usd']:.6f}`**"


def test_report_matches_index_json_dynamically_across_all_sections() -> None:
    index_data = _load_index()
    report_text = _load_report()
    _verify_report_against_index(report_text, index_data)


def test_suite_totals_and_subfamily_sums_reconcile_with_index_json() -> None:
    index_data = _load_index()
    totals = index_data["totals"]
    usage = totals["usage"]
    sfs = index_data["subfamilies"]

    assert sum(int(sf["run_count"]) for sf in sfs.values()) == int(totals["run_count"])
    assert sum(int(sf["images_read"]) for sf in sfs.values()) == int(totals["images_read_by_model"])
    assert sum(int(sf["usage"]["calls"]) for sf in sfs.values()) == int(usage["calls"])
    assert sum(int(sf["usage"]["in"]) for sf in sfs.values()) == int(usage["in"])
    assert sum(int(sf["usage"]["out"]) for sf in sfs.values()) == int(usage["out"])
    assert sum(int(sf["usage"]["thinking"]) for sf in sfs.values()) == int(usage["thinking"])
    assert sum(float(sf["usage"]["cost_usd"]) for sf in sfs.values()) == pytest.approx(
        float(usage["cost_usd"]), abs=1e-9
    )
    assert sum(int(r["image_manifest_summary"]["total_bytes"]) for r in index_data["runs"]) == int(
        totals["image_bytes_verified"]
    )


@pytest.mark.parametrize(
    ("needle", "tampered"),
    [
        ("$3.521048", "$3.521049"),
        ("`260`", "`261`"),
        ("`226`", "`227`"),
        ("`100` (`30` watermark-ablation", "`101` (`30` watermark-ablation"),
        ("+0.4441 +/- 0.1219", "+0.4442 +/- 0.1219"),
        ("+0.6263 +/- 0.0724", "+0.6263 +/- 0.0799"),
        ("14/17", "15/17"),
        ("0.000254", "0.000255"),
        ("85,629", "85,630"),
        ("25/25", "24/25"),
    ],
)
def test_dynamic_validator_rejects_numeric_drift_in_report(needle: str, tampered: str) -> None:
    index_data = _load_index()
    report_text = _load_report()
    assert needle in report_text
    mutated = report_text.replace(needle, tampered, 1)
    with pytest.raises(AssertionError):
        _verify_report_against_index(mutated, index_data)


def test_report_hygiene_zero_unicode_dashes_zero_secrets_zero_stubs() -> None:
    report_text = _load_report()
    for dash_ch in UNICODE_DASHES:
        assert dash_ch not in report_text, f"unicode dash U+{ord(dash_ch):04X} found in {REPORT_PATH}"
    assert _scan_secrets(report_text) == []
    assert CO_AUTHORED_MARKER not in report_text
    for forbidden_marker in ("TODO", "TBD", "DRAFT", "results/gemini_roles/"):
        assert forbidden_marker not in report_text


def test_python_test_hygiene_zero_comments_zero_unicode_dashes_zero_sdk_imports() -> None:
    src = SELF_PATH.read_text(encoding="utf-8")
    for dash_ch in UNICODE_DASHES:
        assert dash_ch not in src, f"unicode dash U+{ord(dash_ch):04X} found in {SELF_PATH}"

    tokens = list(tokenize.generate_tokens(io.StringIO(src).readline))
    comment_tokens = [tok for tok in tokens if tok.type == tokenize.COMMENT]
    assert comment_tokens == []
    assert chr(35) not in src
    assert _scan_secrets(src) == []
    assert CO_AUTHORED_MARKER not in src

    tree = ast.parse(src)
    imported_modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_modules.append(node.module)
    for mod in imported_modules:
        top = mod.split(".")[0]
        assert top not in FORBIDDEN_IMPORT_PREFIXES, f"forbidden network/SDK import: {mod}"
