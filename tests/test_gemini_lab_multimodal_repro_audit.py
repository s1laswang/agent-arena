from __future__ import annotations

import io
import json
from pathlib import Path
import re
import shutil
import socket
import sys
import tokenize
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

ROLES_CARBON_ROOT = REPO_ROOT / "results" / "gemini" / "roles_carbon"
MM_ROOT = ROLES_CARBON_ROOT / "multimodal_evidence"
EH_ROOT = ROLES_CARBON_ROOT / "exploit_hunter"

TARGET_MODEL = "gemini-4-carbon"
HASH_CHAR = chr(35)
H1 = HASH_CHAR + " "
H2 = (HASH_CHAR * 2) + " "
H3 = (HASH_CHAR * 3) + " "
EM_DASH = chr(0x2014)
EN_DASH = chr(0x2013)
UNICODE_DASHES = tuple(chr(c) for c in (*range(0x2010, 0x2016), 0x2212, 0xFE58, 0xFE63, 0xFF0D))
MID_DOT = chr(0x00B7)

COMMIT_RE = re.compile(r"^[0-9a-fA-F]{7,40}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
GOOGLE_KEY_RE = re.compile(r"(?<![A-Za-z0-9_\-])AIza[0-9A-Za-z_\-]{8,60}(?![A-Za-z0-9_\-=])")
SK_KEY_RE = re.compile(r"(?<![A-Za-z0-9_])sk-[A-Za-z0-9_\-]{12,}")
OAUTH_RE = re.compile(r"(?<![A-Za-z0-9_])ya29\.[0-9A-Za-z_\-]{12,}")
NUM_TOKEN_RE = re.compile(r"(?<![A-Za-z0-9_])[+-]?\d+(?:\.\d+)?(?![A-Za-z0-9_])")
HEX_TOKEN_RE = re.compile(r"\b[0-9a-f]{10,64}\b")
ISO_TS_RE = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\+\d{2}:\d{2}|Z)")

EXPECTED_MM_RUNS = (
    "access-heatmap-carbon",
    "access-heatmap-hard-carbon",
    "access-heatmap-v14-high-s8to11-carbon",
    "access-heatmap-v14-low-s8to11-carbon",
    "access-heatmap-v14-sweep-carbon",
    "belief-chart-forensics-carbon",
    "carbon-trajectory-forensics",
    "carbon-trajectory-forensics-v14-expanded",
    "memo-watermark-ablation-carbon",
    "memo-watermark-hard-ablation-carbon",
    "memo-watermark-hard-seeds10to14-carbon",
    "memo-watermark-hard-seeds5to9-carbon",
    "memo-watermark-med-seeds6to11-carbon",
    "multi-image-dossier-carbon",
    "multi-image-dossier-med6to8-hard5to7-carbon",
    "multi-image-dossier-v14-expanded-carbon",
    "scanned-evidence-ablation-carbon",
)

EXPECTED_EH_RUNS = (
    "blackbox-swarm-carbon",
    "whitebox-swarm-carbon",
)

ALL_19_RUNS = tuple(
    [f"multimodal_evidence/{name}" for name in EXPECTED_MM_RUNS]
    + [f"exploit_hunter/{name}" for name in EXPECTED_EH_RUNS]
)


def _blocked_network(*_args: object, **_kwargs: object) -> Any:
    raise RuntimeError("network and API calls are disabled in keyless repro audit")


@pytest.fixture(autouse=True)
def _keyless_zero_api_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in (
        "GEMINI_API_KEY",
        "GOOGLE_GENERATIVE_AI_API_KEY",
        "GOOGLE_API_KEY",
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "XAI_API_KEY",
    ):
        monkeypatch.setenv(var, "")
    monkeypatch.delenv("GEMINI_GATEWAY_URL", raising=False)
    monkeypatch.setattr(socket.socket, "connect", _blocked_network)
    monkeypatch.setattr(socket.socket, "connect_ex", _blocked_network)
    monkeypatch.setattr(socket, "create_connection", _blocked_network)


def _norm_dashes(text: str) -> str:
    return text.replace(EM_DASH, "-").replace(EN_DASH, "-")


def _scan_secrets(text: str) -> list[str]:
    hits: list[str] = []
    if GOOGLE_KEY_RE.search(text):
        hits.append("google_api_key")
    if SK_KEY_RE.search(text):
        hits.append("sk_api_key")
    if OAUTH_RE.search(text):
        hits.append("oauth_token")
    return hits


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _parse_md_tables(md_text: str) -> list[tuple[list[str], list[list[str]]]]:
    tables: list[tuple[list[str], list[list[str]]]] = []
    lines = md_text.splitlines()
    i = 0
    while i < len(lines):
        ln = lines[i].strip()
        if ln.startswith("|") and ln.endswith("|") and i + 1 < len(lines):
            sep = lines[i + 1].strip()
            if sep.startswith("|") and "-" in sep:
                headers = [c.strip() for c in ln.strip("|").split("|")]
                rows: list[list[str]] = []
                i += 2
                while i < len(lines):
                    rln = lines[i].strip()
                    if not (rln.startswith("|") and rln.endswith("|")):
                        break
                    rows.append([c.strip() for c in rln.strip("|").split("|")])
                    i += 1
                tables.append((headers, rows))
                continue
        i += 1
    return tables


def _compute_5bin_ece(worlds: list[dict[str, Any]]) -> float:
    n = len(worlds)
    assert n > 0
    ece = 0.0
    for b in range(5):
        lo = b * 0.2
        hi = (b + 1) * 0.2
        if b == 4:
            bucket = [w for w in worlds if lo <= float(w["model_output"]["confidence"]) <= hi]
        else:
            bucket = [w for w in worlds if lo <= float(w["model_output"]["confidence"]) < hi]
        if not bucket:
            continue
        avg_conf = sum(float(w["model_output"]["confidence"]) for w in bucket) / len(bucket)
        avg_acc = sum(1.0 if w["evaluation"]["top1_mole_correct"] else 0.0 for w in bucket) / len(bucket)
        ece += (len(bucket) / n) * abs(avg_conf - avg_acc)
    return ece


def _extract_line_numbers(md_text: str) -> list[tuple[int, list[str]]]:
    extracted: list[tuple[int, list[str]]] = []
    for idx, raw_line in enumerate(md_text.splitlines(), start=1):
        scrubbed = ISO_TS_RE.sub("", raw_line)
        scrubbed = HEX_TOKEN_RE.sub("", scrubbed)
        toks = NUM_TOKEN_RE.findall(scrubbed)
        extracted.append((idx, toks))
    return extracted


def _assert_markdown_numeric_parity(actual_md: str, expected_md: str, run_dir: Path) -> int:
    actual_lines = actual_md.splitlines()
    expected_lines = expected_md.splitlines()
    assert len(actual_lines) == len(expected_lines), (
        run_dir,
        len(actual_lines),
        len(expected_lines),
    )
    for line_no, (act_ln, exp_ln) in enumerate(zip(actual_lines, expected_lines), start=1):
        assert act_ln == exp_ln, f"{run_dir} line {line_no}:\n  actual:   {act_ln!r}\n  expected: {exp_ln!r}"

    act_nums = _extract_line_numbers(actual_md)
    exp_nums = _extract_line_numbers(expected_md)
    assert len(act_nums) == len(exp_nums), run_dir
    total_checked = 0
    for (ln_a, toks_a), (ln_e, toks_e) in zip(act_nums, exp_nums):
        assert ln_a == ln_e, run_dir
        assert toks_a == toks_e, (run_dir, ln_a, toks_a, toks_e)
        for ta, te in zip(toks_a, toks_e):
            assert float(ta) == pytest.approx(float(te), abs=1e-12), (run_dir, ln_a, ta, te)
            total_checked += 1
    assert total_checked > 0, run_dir
    return total_checked


def _render_soc_access_single_tier(meta: dict[str, Any], res: dict[str, Any]) -> str:
    u = meta["usage"]
    m = res["metrics"]
    n = int(res["n_worlds"])
    mime = meta["image_manifest"]["mime_type"]
    lines = [
        f"{H1}Role 6 (multimodal_evidence) - Security-SOC Access & Framing Raster Vision Run",
        "",
        f"{H2}Provenance",
        f"- Role: `{meta['role']}` (`{meta['subrole']}`)",
        f"- Model: `{meta['model_id']}`",
        f"- Tiers version: `{meta['tiers_version']}` (`{meta['tier']}`, seeds `{meta['seeds']}`)",
        f"- Commit: `{meta['commit']}`",
        f"- Timestamp: `{meta['timestamp']}`",
        f"- Command: `{meta['command']}`",
        f"- Images read by model (`Part.from_bytes`, `{mime}`): `{meta['n_images_read_by_model']}`",
        (
            f"- Token usage: `in={u['in']}`, `out={u['out']}`, `thinking={u['thinking']}`, "
            f"`cached={u['cached']}`, `cost_usd={u['cost_usd']:.6f}`, `latency_s={u['latency_s']:.2f}`"
        ),
        "",
        f"{H2}Aggregate Results",
        f"| Metric | Gemini SOC Vision (`{meta['model_id']}`) | Naive After-Hours Log Baseline |",
        "|---|---|---|",
        (
            f"| Top-1 Mole Accuracy | {m['top1_mole_hits']}/{n} ({m['top1_mole_accuracy'] * 100:.1f}%) | "
            f"{m['naive_baseline_mole_hits']}/{n} ({m['naive_after_hours_baseline_mole_accuracy'] * 100:.1f}%) |"
        ),
        f"| Top-3 Mole Hit Rate | {m['top3_mole_hits']}/{n} ({m['top3_mole_hit_rate'] * 100:.1f}%) | - |",
        f"| Top-1 Framed Decoy Identified | {m['top1_decoy_hits']}/{n} ({m['top1_decoy_accuracy'] * 100:.1f}%) | - |",
        f"| Framed Decoy in Suspected Decoy List | {m['decoy_identified_hits']}/{n} ({m['decoy_identified_rate'] * 100:.1f}%) | - |",
        (
            f"| Avoided Framing Decoy Trap | {m['avoided_framing_trap_hits']}/{n} ({m['avoided_framing_trap_rate'] * 100:.1f}%) | "
            f"{n - m['naive_baseline_decoy_traps']}/{n} ({(1.0 - m['naive_after_hours_baseline_decoy_trap_rate']) * 100:.1f}%) |"
        ),
        "",
        f"{H2}Rendered SOC Evidence Rasters",
        "| Seed | Raster Path | Size | Bytes | SHA-256 |",
        "|---|---|---|---|---|",
    ]
    for r in meta["rasters"]:
        lines.append(
            f"| {r['seed']} | `{r['path']}` | {r['size'][0]}x{r['size'][1]} | {r['bytes']} | `{r['sha256']}` |"
        )
    lines += [
        "",
        f"{H2}Per-World Breakdown",
        "| Seed | True Mole | True Decoy | Naive Log Pick | Pred Top Suspects | Pred Decoys | Mole Top-1 | Decoy Top-1 |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for w in res["worlds"]:
        ev = w["evaluation"]
        gt = w["ground_truth"]
        mo = w["model_output"]
        naive_id = w["observable_summary"]["naive_most_after_hours_id"]
        lines.append(
            f"| {w['seed']} | `{gt['true_mole']}` | `{gt['true_decoy']}` | `{naive_id}` | "
            f"`{', '.join(mo['top_suspect_ids'][:3])}` | `{', '.join(mo['suspected_decoy_ids'][:3])}` | "
            f"{'YES' if ev['top1_mole_correct'] else 'NO'} | {'YES' if ev['top1_decoy_correct'] else 'NO'} |"
        )
    lines += ["", f"{H2}Visual Reasoning Excerpts"]
    for w in res["worlds"]:
        mo = w["model_output"]
        lines.append(
            f"- **Seed {w['seed']}** (`{w['raster_path']}`, conf `{mo['confidence']:.2f}`): "
            f"{_norm_dashes(mo['visual_reasoning'])}"
        )
    return "\n".join(lines) + "\n"


def _render_soc_access_sweep(meta: dict[str, Any], res: dict[str, Any]) -> str:
    u = meta["usage"]
    m = res["metrics"]
    n = int(res["n_worlds"])
    med = res["by_tier"]["medium"]
    hard = res["by_tier"]["hard"]
    nm = int(med["n_worlds"])
    nh = int(hard["n_worlds"])
    mime = meta["image_manifest"]["mime_type"]
    med_seeds = meta["tier_seeds"]["medium"]
    hard_seeds = meta["tier_seeds"]["hard"]

    prov = [
        f"{H1}Role 6 (multimodal_evidence) - Multi-Tier v1.4 SOC Access & Framing Raster Vision Sweep",
        "",
        f"{H2}Provenance",
        f"- Role: `{meta['role']}` (`{meta['subrole']}`)",
        f"- Model: `{meta['model_id']}`",
    ]
    if "thinking_level" in meta:
        prov.append(f"- Thinking level: `{meta['thinking_level']}`")
    prov += [
        f"- Tiers version: `{meta['tiers_version']}` (medium seeds {med_seeds}, hard seeds {hard_seeds})",
        f"- Commit: `{meta['commit']}`",
        f"- Timestamp: `{meta['timestamp']}`",
        f"- Command: `{meta['command']}`",
        f"- Episode count: `{meta['episode_count']}`",
        f"- Images read by model (`Part.from_bytes`, `{mime}`): `{meta['n_images_read_by_model']}`",
        (
            f"- Token usage: `calls={u['calls']}`, `in={u['in']}`, `out={u['out']}`, `thinking={u['thinking']}`, "
            f"`cached={u['cached']}`, `cost_usd={u['cost_usd']:.6f}`, `latency_s={u['latency_s']:.2f}`"
        ),
        "",
        f"{H2}Per-Tier & Overall Aggregate Results vs Naive After-Hours Log Baseline",
        (
            f"| Metric | `medium` (`n={nm}`) | `hard` (`n={nh}`) | Overall Vision (`n={n}`) | "
            f"Naive After-Hours Baseline (`n={n}`) | Vision vs Naive Delta |"
        ),
        "|---|---|---|---|---|---|",
        (
            f"| Top-1 Mole Accuracy | {med['top1_mole_hits']}/{nm} ({med['top1_mole_accuracy'] * 100:.1f}%) | "
            f"{hard['top1_mole_hits']}/{nh} ({hard['top1_mole_accuracy'] * 100:.1f}%) | "
            f"{m['top1_mole_hits']}/{n} ({m['top1_mole_accuracy'] * 100:.1f}%) | "
            f"{m['naive_baseline_mole_hits']}/{n} ({m['naive_baseline_mole_accuracy'] * 100:.1f}%) | "
            f"{m['mole_accuracy_delta_vs_naive'] * 100:+.1f}% "
            f"({m['head_to_head_wins_vs_naive']}W-{m['head_to_head_ties_vs_naive']}T-{m['head_to_head_losses_vs_naive']}L) |"
        ),
        (
            f"| Top-3 Mole Hit Rate | {med['top3_mole_hits']}/{nm} ({med['top3_mole_hit_rate'] * 100:.1f}%) | "
            f"{hard['top3_mole_hits']}/{nh} ({hard['top3_mole_hit_rate'] * 100:.1f}%) | "
            f"{m['top3_mole_hits']}/{n} ({m['top3_mole_hit_rate'] * 100:.1f}%) | - | - |"
        ),
        (
            f"| Top-1 Framed Decoy Accuracy | {med['top1_decoy_hits']}/{nm} ({med['top1_decoy_accuracy'] * 100:.1f}%) | "
            f"{hard['top1_decoy_hits']}/{nh} ({hard['top1_decoy_accuracy'] * 100:.1f}%) | "
            f"{m['top1_decoy_hits']}/{n} ({m['top1_decoy_accuracy'] * 100:.1f}%) | - | - |"
        ),
        (
            f"| Framed Decoy in Suspected List | {med['decoy_identified_hits']}/{nm} ({med['decoy_identified_rate'] * 100:.1f}%) | "
            f"{hard['decoy_identified_hits']}/{nh} ({hard['decoy_identified_rate'] * 100:.1f}%) | "
            f"{m['decoy_identified_hits']}/{n} ({m['decoy_identified_rate'] * 100:.1f}%) | - | - |"
        ),
        (
            f"| Avoided Framing Trap Rate | {med['avoided_framing_trap_hits']}/{nm} ({med['avoided_framing_trap_rate'] * 100:.1f}%) | "
            f"{hard['avoided_framing_trap_hits']}/{nh} ({hard['avoided_framing_trap_rate'] * 100:.1f}%) | "
            f"{m['avoided_framing_trap_hits']}/{n} ({m['avoided_framing_trap_rate'] * 100:.1f}%) | "
            f"{m['naive_baseline_avoided_trap_hits']}/{n} ({m['naive_baseline_avoided_trap_rate'] * 100:.1f}%) | "
            f"{m['avoided_trap_delta_vs_naive'] * 100:+.1f}% |"
        ),
        f"| Mean Confidence | {med['mean_confidence']:.4f} | {hard['mean_confidence']:.4f} | {m['mean_confidence']:.4f} | - | - |",
        f"| Brier Score (lower is better) | {med['brier_score']:.4f} | {hard['brier_score']:.4f} | {m['brier_score']:.4f} | - | - |",
        (
            f"| Expected Calibration Error (ECE, 5-bin) | {med['expected_calibration_error']:.4f} | "
            f"{hard['expected_calibration_error']:.4f} | {m['expected_calibration_error']:.4f} | - | - |"
        ),
        "",
        f"{H2}Confidence Calibration & Head-to-Head Summary",
        (
            f"- Overall Brier score: `{m['brier_score']:.6f}` "
            f"(ECE `{m['expected_calibration_error']:.6f}`, signed confidence gap `{m['signed_calibration_gap']:+.6f}`)"
        ),
    ]
    conf_wrong = m.get("mean_confidence_when_wrong")
    wrong_str = "n/a" if conf_wrong is None else f"{conf_wrong:.4f}"
    prov += [
        (
            f"- Mean posterior confidence: `{m['mean_confidence']:.4f}` overall "
            f"(`{m['mean_confidence_when_correct']:.4f}` when Top-1 correct, `{wrong_str}` when Top-1 wrong)"
        ),
        (
            f"- Head-to-head vs Naive After-Hours Log Baseline: `{m['head_to_head_wins_vs_naive']}` wins, "
            f"`{m['head_to_head_ties_vs_naive']}` ties, `{m['head_to_head_losses_vs_naive']}` losses "
            f"(`{m['mole_accuracy_delta_vs_naive'] * 100:+.1f}%` Top-1 mole accuracy delta; "
            f"Naive trapped by framed decoy on `{m['naive_baseline_decoy_traps']}/{n}` worlds)"
        ),
        "",
        f"{H2}Rendered SOC Evidence Rasters",
        "| Tier | Seed | Raster Path | Size | Bytes | SHA-256 |",
        "|---|---:|---|---|---:|---|",
    ]
    for r in meta["rasters"]:
        prov.append(
            f"| `{r['tier']}` | {r['seed']} | `{r['path']}` | {r['size'][0]}x{r['size'][1]} | {r['bytes']} | `{r['sha256']}` |"
        )
    prov += [
        "",
        f"{H2}Per-World Breakdown",
        "| Tier | Seed | Staff | Surfaced Canaries | True Mole | True Decoy | Naive Pick | Pred Suspects | Pred Decoys | Conf | Brier | Mole Top-1 | Decoy Top-1 |",
        "|---|---:|---:|---:|---|---|---|---|---|---:|---:|---|---|",
    ]
    for w in res["worlds"]:
        obs = w["observable_summary"]
        gt = w["ground_truth"]
        mo = w["model_output"]
        ev = w["evaluation"]
        conf = float(mo["confidence"])
        y = 1.0 if ev["top1_mole_correct"] else 0.0
        brier = float(ev.get("brier_score", (conf - y) ** 2))
        prov.append(
            f"| `{w['tier']}` | {w['seed']} | {obs['n_employees']} | "
            f"{obs['n_surfaced_canary_leaks']}/{obs['n_canaries_planted']} | "
            f"`{gt['true_mole']}` | `{gt['true_decoy']}` | `{obs['naive_most_after_hours_id']}` | "
            f"`{', '.join(mo['top_suspect_ids'][:3])}` | `{', '.join(mo['suspected_decoy_ids'][:3])}` | "
            f"{conf:.2f} | {brier:.4f} | "
            f"{'YES' if ev['top1_mole_correct'] else 'NO'} | {'YES' if ev['top1_decoy_correct'] else 'NO'} |"
        )
    prov += ["", f"{H2}Visual Reasoning Excerpts"]
    for w in res["worlds"]:
        mo = w["model_output"]
        prov.append(
            f"- **{str(w['tier']).upper()} Seed {w['seed']}** (`{w['raster_path']}`, conf `{mo['confidence']:.2f}`): "
            f"{_norm_dashes(mo['visual_reasoning'])}"
        )
    return "\n".join(prov) + "\n"


def _render_belief_chart_forensics(meta: dict[str, Any], diags: list[dict[str, Any]]) -> str:
    u = meta["usage"]
    n = int(meta["n_charts_analyzed"])
    n_wrong = sum(1 for d in diags if d["cohort"] == "wrong_or_premature")
    n_high = sum(1 for d in diags if d["cohort"] == "high_scoring")
    th_hits = sum(1 for d in diags if d["scoring"]["threshold_match"])
    d1_hits = sum(1 for d in diags if d["scoring"]["day_within_1"])
    dex_hits = sum(1 for d in diags if d["scoring"]["day_exact"])
    bl_hits = sum(1 for d in diags if d["scoring"]["bleed_gap_match"])
    mime = meta["image_manifest"]["mime_type"]

    lines = [
        f"{H1}Multimodal Belief and Value-Bleed Chart Forensics ({meta['model_id']})",
        "",
        f"- **Role:** `{meta['role']}` (`{meta['subrole']}`)",
        f"- **Model:** `{meta['model_id']}` via `google.genai.types.Part.from_bytes(mime_type=\"{mime}\")`",
        f"- **Commit:** `{meta['commit']}`",
        f"- **Timestamp:** `{meta['timestamp']}`",
        f"- **Ledger run_id:** `{meta['ledger_run_id']}`",
        f"- **Replay rules:** `canary.rules.tiers_version(\"{meta['tiers_version']}\")`",
        f"- **Charts analyzed:** `{n}` ({n_wrong} wrong/premature accusations + {n_high} high-scoring episodes from `data/runs/committed/{meta['tiers_version']}/`)",
        f"- **Visual EV-threshold accuracy:** `{th_hits}/{n}` (`{meta['visual_threshold_accuracy']:.3f}`)",
        f"- **Accusation-day accuracy (|est - actual| <= 1):** `{d1_hits}/{n}` (`{meta['accuse_day_within_1_accuracy']:.3f}`; exact match `{dex_hits}/{n}`)",
        f"- **Hidden-bleed gap accuracy:** `{bl_hits}/{n}` (`{meta['hidden_bleed_gap_accuracy']:.3f}`)",
        (
            f"- **Total Gemini usage:** `{u['calls']}` calls, `{u['in']}` input tokens, `{u['out']}` output tokens, "
            f"`{u['thinking']}` thinking tokens, `${u['cost_usd']:.6f}` USD, `{u['latency_s']:.2f}` s"
        ),
        "",
        f"{H2}Visual Reading vs Solver Ground Truth",
        "",
        "| Chart | Cohort | Agent / Tier / Seed | Score | GT P(accused) vs 1/(1+V) | GT Below EV | Gemini Below EV | Actual Day | Gemini Day | GT Bleed Gap | Gemini Bleed | Primary Pattern |",
        "|---|---|---|---:|---|---|---|---|---:|---|---|---|",
    ]
    for d in diags:
        src = d["source_episode"]
        gt = d["ground_truth"]
        gd = d["gemini_diagnosis"]
        lines.append(
            f"| `{d['chart_path']}` | {d['cohort']} | `{src['agent']}` / `{src['tier']}` / `{src['seed']}` | "
            f"{gt['score']:+.3f} | {gt['accused_posterior_at_accuse']:.3f} vs {gt['ev_threshold_at_accuse']:.3f} | "
            f"`{gt['accused_below_ev_threshold']}` | `{gd['accused_below_ev_threshold']}` | "
            f"{gt['actual_accuse_day']} | {gd['estimated_accuse_day']} | "
            f"`{gt['hidden_bleed_gap_present']}` ({gt['max_bleed_gap']:.3f}) | `{gd['hidden_bleed_gap_present']}` | "
            f"`{gd['primary_failure_pattern']}` |"
        )
    lines += ["", f"{H2}Per-Chart Multimodal Forensic Diagnoses"]
    for d in diags:
        src = d["source_episode"]
        gt = d["ground_truth"]
        gd = d["gemini_diagnosis"]
        sc = d["scoring"]
        lines += [
            "",
            f"{H3}Episode {d['episode_index']} (`{d['chart_path']}`): `{src['agent']}` on `{src['tier']}` seed `{src['seed']}` ({d['cohort']})",
            (
                f"- **Ground truth:** accused `{gt['accused_employee']}` on day `{gt['actual_accuse_day']}` "
                f"(correct=`{gt['correct']}`, score=`{gt['score']:+.3f}`), "
                f"`P(accused)={gt['accused_posterior_at_accuse']:.3f}` vs `1/(1+V)={gt['ev_threshold_at_accuse']:.3f}` "
                f"(`below_ev={gt['accused_below_ev_threshold']}`), "
                f"`max_bleed_gap={gt['max_bleed_gap']:.3f}` (`bleed={gt['hidden_bleed_gap_present']}`), "
                f"canaries planted=`{gt['total_canaries_planted']}`."
            ),
            (
                f"- **Gemini visual output:** `accused_below_ev_threshold={gd['accused_below_ev_threshold']}` "
                f"(match=`{sc['threshold_match']}`), `estimated_accuse_day={gd['estimated_accuse_day']}` "
                f"(abs_err=`{sc['day_abs_error']}`, within_1=`{sc['day_within_1']}`), "
                f"`hidden_bleed_gap_present={gd['hidden_bleed_gap_present']}` (match=`{sc['bleed_gap_match']}`), "
                f"pattern=`{gd['primary_failure_pattern']}`."
            ),
            f"- **Visual diagnosis:** {_norm_dashes(gd['visual_diagnosis'])}",
        ]
    return "\n".join(lines) + "\n"


def _render_trajectory_forensics(meta: dict[str, Any], diags: list[dict[str, Any]]) -> str:
    u = meta["usage"]
    n = int(meta["n_charts_analyzed"])
    th_hits = sum(1 for d in diags if d["scoring"]["threshold_match"])
    d1_hits = sum(1 for d in diags if d["scoring"]["day_within_1"])
    dex_hits = sum(1 for d in diags if d["scoring"]["day_exact"])
    bl_hits = sum(1 for d in diags if d["scoring"]["bleed_gap_match"])
    lag_hits = sum(1 for d in diags if d["scoring"]["entropy_lag_match"])
    pat_hits = sum(1 for d in diags if d["scoring"]["outcome_pattern_match"])
    mime = meta["image_manifest"]["mime_type"]

    lines = [
        f"{H1}Multimodal 4-Panel Trajectory Forensics on Real {meta['tiers_version']} Investigator Runs ({meta['model_id']})",
        "",
        f"- **Role:** `{meta['role']}` (`{meta['subrole']}`)",
        f"- **Model:** `{meta['model_id']}` via `google.genai.types.Part.from_bytes(mime_type=\"{mime}\")`",
        f"- **Commit:** `{meta['commit']}`",
        (
            f"- **Source {meta['tiers_version']} investigator runs:** `{meta['source_runs_dir']}` "
            f"(branch `{meta['source_runs_branch']}`, commit `{meta['source_runs_commit']}`)"
        ),
        f"- **Timestamp:** `{meta['timestamp']}`",
        f"- **Ledger run_id:** `{meta['ledger_run_id']}`",
        f"- **Replay rules:** `canary.rules.tiers_version(\"{meta['tiers_version']}\")` (hard: 40 staff, 21 days, up to 2 canaries/day; medium: 20 staff, 14 days)",
        f"- **Charts analyzed:** `{n}`",
        f"- **Visual EV-threshold accuracy:** `{th_hits}/{n}` (`{meta['visual_threshold_accuracy']:.3f}`)",
        f"- **Accusation/stop-day accuracy (|est - actual| <= 1):** `{d1_hits}/{n}` (`{meta['accuse_day_within_1_accuracy']:.3f}`; exact match `{dex_hits}/{n}`)",
        f"- **Hidden-bleed gap accuracy:** `{bl_hits}/{n}` (`{meta['hidden_bleed_gap_accuracy']:.3f}`)",
        f"- **Entropy-lag vs SolverPolicy accuracy:** `{lag_hits}/{n}` (`{meta['entropy_lag_accuracy']:.3f}`)",
        f"- **Failure/outcome pattern consistency:** `{pat_hits}/{n}` (`{meta['outcome_pattern_accuracy']:.3f}`)",
        (
            f"- **Total Gemini usage:** `{u['calls']}` calls, `{u['in']}` input tokens, `{u['out']}` output tokens, "
            f"`{u['thinking']}` thinking tokens, `${u['cost_usd']:.6f}` USD, `{u['latency_s']:.2f}` s"
        ),
        "",
        f"{H2}Visual Forensics vs Exact {meta['tiers_version']} Solver Ground Truth",
        "",
        "| Chart | Cohort | Tier / Seed | Score | GT P(stop) vs 1/(1+V) | GT Below EV | Gemini Below EV | Stop Day (GT / Gem) | Solver Day | GT Lag / Gem Lag | GT Bleed | Gem Bleed | Primary Pattern |",
        "|---|---|---|---:|---|---|---|---|---:|---|---|---|---|",
    ]
    for d in diags:
        src = d["source_episode"]
        gt = d["ground_truth"]
        gd = d["gemini_diagnosis"]
        lines.append(
            f"| `{d['chart_path']}` | {d['cohort']} | `{src['tier']}` / `{src['seed']}` | "
            f"{gt['score']:+.3f} | {gt['accused_posterior_at_accuse']:.3f} vs {gt['ev_threshold_at_accuse']:.3f} | "
            f"`{gt['accused_below_ev_threshold']}` | `{gd['accused_below_ev_threshold']}` | "
            f"{gt['actual_accuse_day']} / {gd['estimated_accuse_day']} | {gt['solver_accuse_day']} | "
            f"`{gt['entropy_lags_solver']}` / `{gd['entropy_lags_solver']}` | "
            f"`{gt['hidden_bleed_gap_present']}` ({gt['max_bleed_gap']:.3f}) | `{gd['hidden_bleed_gap_present']}` | "
            f"`{gd['primary_failure_pattern']}` |"
        )
    lines += ["", f"{H2}Per-Episode 4-Panel Trajectory Forensic Readings"]
    for d in diags:
        src = d["source_episode"]
        gt = d["ground_truth"]
        gd = d["gemini_diagnosis"]
        sc = d["scoring"]
        lines += [
            "",
            f"{H3}Episode {d['episode_index']} (`{d['chart_path']}`): `{src['agent']}` on `{src['tier']}` seed `{src['seed']}` ({d['cohort']})",
            (
                f"- **Ground truth:** end=`{gt['end_reason']}`, accused=`{gt['accused_employee']}`, "
                f"true_mole=`{gt['true_mole']}`, decoy=`{gt['framed_decoy']}`, day=`{gt['actual_accuse_day']}` "
                f"(correct=`{gt['correct']}`, score=`{gt['score']:+.3f}`), "
                f"`P(stop)={gt['accused_posterior_at_accuse']:.3f}` vs `1/(1+V)={gt['ev_threshold_at_accuse']:.3f}` "
                f"(`below_ev={gt['accused_below_ev_threshold']}`), `max_bleed_gap={gt['max_bleed_gap']:.3f}`, "
                f"canaries=`{gt['total_canaries_planted']}` (max `{gt['max_daily_canaries_planted']}`/day), "
                f"`H_end={gt['final_entropy_bits']:.2f}` bits vs Solver day `{gt['solver_accuse_day']}` "
                f"(`score={gt['solver_score']:+.3f}`, `entropy_lags_solver={gt['entropy_lags_solver']}`)."
            ),
            (
                f"- **Gemini visual diagnosis:** `accused_below_ev_threshold={gd['accused_below_ev_threshold']}` "
                f"(match=`{sc['threshold_match']}`), `estimated_accuse_day={gd['estimated_accuse_day']}` "
                f"(abs_err=`{sc['day_abs_error']}`), "
                f"`hidden_bleed_gap_present={gd['hidden_bleed_gap_present']}` (match=`{sc['bleed_gap_match']}`), "
                f"`entropy_lags_solver={gd['entropy_lags_solver']}` (match=`{sc['entropy_lag_match']}`), "
                f"pattern=`{gd['primary_failure_pattern']}` (match=`{sc['outcome_pattern_match']}`)."
            ),
            f"- **Fooled-step / trajectory summary:** {_norm_dashes(gd['fooled_step_summary'])}",
        ]
    return "\n".join(lines) + "\n"


def _render_memo_watermark_ablation(meta: dict[str, Any], comp: dict[str, Any]) -> str:
    u = meta["usage"]
    n_ep = int(meta["n_episodes"])
    s = comp["summary"]
    mm_s = s["multimodal_carbon"]
    bl_s = s["blind_no_vision"]
    orc_s = s["text_oracle"]
    mime = meta["image_manifest"]["mime_type"]

    def _fmt_day(val: Any) -> str:
        return "n/a (horizon)" if val is None else f"{float(val):.2f}"

    lines = [
        f"{H1}Role 6 (multimodal_evidence) - In-Game Visual Leak-Memo Watermark Vision + Blind Ablation",
        "",
        f"{H2}Provenance",
        f"- Role: `{meta['role']}` (`{meta['subrole']}`)",
        f"- Model: `{meta['model_id']}`",
        f"- Tiers version: `{meta['tiers_version']}` (`{meta['tier']}`, seeds `{meta['seeds']}`)",
        f"- Commit: `{meta['commit']}`",
        f"- Timestamp: `{meta['timestamp']}`",
        f"- Command: `{meta['command']}`",
        f"- Episodes per condition: `{n_ep}` (3 conditions x {n_ep} seeds = {3 * n_ep} paired episodes)",
        (
            f"- Leaked memo PNGs read via `Part.from_bytes(..., mime_type='{mime}')`: "
            f"`{meta['n_images_read_by_model']}` (`{meta['n_canary_memos_read_by_model']}` watermarked canary scans)"
        ),
        (
            f"- Vision watermark readout accuracy: `{s['variant_vision_accuracy'] * 100:.1f}%` overall "
            f"(`{s['canary_variant_vision_accuracy'] * 100:.1f}%` on planted canary memos)"
        ),
        (
            f"- Token usage: `calls={u['calls']}`, `in={u['in']}`, `out={u['out']}`, `thinking={u['thinking']}`, "
            f"`cached={u['cached']}`, `cost_usd={u['cost_usd']:.6f}`, `latency_s={u['latency_s']:.2f}`"
        ),
        "",
        f"{H2}Paired 3-Condition Comparison (`{meta['tier']}` seeds `{meta['seeds']}`)",
        "| Condition | Variant Source | Mean Score | Mole Accuracy | Accusations | Mean Accuse Day |",
        "|---|---|---:|---:|---:|---:|",
        (
            f"| `multimodal_carbon` | `{meta['model_id']}` reading memo PNGs (`Part.from_bytes`) | "
            f"{mm_s['mean_score']:+.4f} | {mm_s['accuracy'] * 100:.1f}% | "
            f"{mm_s['accused_count']}/{n_ep} | {_fmt_day(mm_s['mean_accuse_day'])} |"
        ),
        (
            f"| `blind_no_vision` | Text `variant` redacted, vision disabled | "
            f"{bl_s['mean_score']:+.4f} | {bl_s['accuracy'] * 100:.1f}% | "
            f"{bl_s['accused_count']}/{n_ep} | {_fmt_day(bl_s['mean_accuse_day'])} |"
        ),
        (
            f"| `text_oracle` | Unredacted text `check_leak_feed` upper bound | "
            f"{orc_s['mean_score']:+.4f} | {orc_s['accuracy'] * 100:.1f}% | "
            f"{orc_s['accused_count']}/{n_ep} | {_fmt_day(orc_s['mean_accuse_day'])} |"
        ),
        "",
        f"- Multimodal gain over blind ablation: `{s['multimodal_minus_blind']:+.4f}`",
        (
            f"- Oracle Bayesian solver performance recovered by vision: "
            f"`{s['oracle_score_recovery_ratio'] * 100:.1f}%` (`{mm_s['mean_score']:+.4f}` vs `{orc_s['mean_score']:+.4f}`)"
        ),
        "",
        f"{H2}Per-Seed Paired Episodes",
        "| Seed | `multimodal_carbon` Score (Accused, Day, Max P) | `blind_no_vision` Score (Accused, Day, Max P) | `text_oracle` Score (Accused, Day, Max P) | Memos Read | Vision Exact |",
        "|---:|---|---|---|---:|---:|",
    ]
    for row in comp["per_seed"]:
        mm_ep = row["multimodal_carbon"]
        bl_ep = row["blind_no_vision"]
        orc_ep = row["text_oracle"]

        def _cell(ep: dict[str, Any]) -> str:
            acc = ep["accused"] if ep["accused"] is not None else "none"
            return f"`{ep['score']:+.4f}` (`{acc}`, d{ep['final_day']}, P={ep['max_posterior']:.2f})"

        lines.append(
            f"| {row['seed']} | {_cell(mm_ep)} | {_cell(bl_ep)} | {_cell(orc_ep)} | "
            f"{mm_ep['n_memos_inspected']} | {mm_ep['vision_exact_matches']}/{mm_ep['n_memos_inspected']} |"
        )
    lines += [
        "",
        f"{H2}Rendered Leak-Memo Scans & `{meta['model_id']}` Vision Readouts",
        "| Seed | Doc ID | Day Surfaced | Expected Copy-Code | Predicted Copy-Code | Match | PNG Path | Size | Bytes | SHA-256 |",
        "|---:|---|---:|---|---|---|---|---|---:|---|",
    ]
    for vc in comp["vision_calls"]:
        exp_var = vc["expected_variant"] if vc["expected_variant"] is not None else "NONE"
        pred_var = vc["predicted_variant"] if vc["predicted_variant"] is not None else "NONE"
        sz = vc["memo_size"]
        lines.append(
            f"| {vc['seed']} | `{vc['doc_id']}` | {vc['day_surfaced']} | `{exp_var}` | `{pred_var}` | "
            f"{'YES' if vc['variant_exact_match'] else 'NO'} | `{vc['memo_path']}` | {sz[0]}x{sz[1]} | "
            f"{vc['memo_bytes']} | `{vc['memo_sha256']}` |"
        )
    return "\n".join(lines) + "\n"


def _render_incident_dossier(meta: dict[str, Any], res: dict[str, Any]) -> str:
    u = meta["usage"]
    m = res["metrics"]
    n = int(meta["episode_count"])
    n_img = int(meta["n_images_read_by_model"])
    ipc = int(meta["images_per_call"])
    mime = meta["image_manifest"]["mime_type"]
    med_seeds = ",".join(str(w["seed"]) for w in res["worlds"] if w["tier"] == "medium")
    hard_seeds = ",".join(str(w["seed"]) for w in res["worlds"] if w["tier"] == "hard")

    img1_avoided = n - int(m["image1_only_decoy_traps"])
    img1_avoided_pct = 100.0 * (1.0 - float(m["image1_only_decoy_trap_rate"]))
    img2_mole_hits = sum(1 for w in res["worlds"] if w["single_image_baselines"]["image2_only_mole_correct"])
    img2_decoy_hits = sum(1 for w in res["worlds"] if w["single_image_baselines"]["image2_only_decoy_correct"])

    lines = [
        f"{H1}Role 6 (multimodal_evidence) - Multi-Image Composite Incident Dossier Run",
        "",
        f"{H2}Provenance",
        f"- Role: `{meta['role']}` (`{meta['subrole']}`)",
        f"- Model: `{meta['model_id']}`",
        f"- Tiers version: `{meta['tiers_version']}` (`{n}` composite dossiers across `medium` seeds `{med_seeds}` and `hard` seeds `{hard_seeds}`)",
        f"- Commit: `{meta['commit']}`",
        f"- Timestamp: `{meta['timestamp']}`",
        f"- Command: `{meta['command']}`",
        f"- Composite dossiers evaluated (`episode_count`): `{n}`",
        f"- Images read by model (`Part.from_bytes`, `{mime}`, `{ipc}` distinct PNGs per single call): `{n_img}`",
        (
            f"- Token usage: `calls={u['calls']}`, `in={u['in']}`, `out={u['out']}`, `thinking={u['thinking']}`, "
            f"`cached={u['cached']}`, `cost_usd={u['cost_usd']:.6f}`, `latency_s={u['latency_s']:.2f}`"
        ),
        "",
        f"{H2}Multi-Image Fusion vs Single-Image Baselines",
        "| Approach | Inputs Available | Top-1 Mole Accuracy | Top-1 Framed Decoy Accuracy | Avoided Framing Trap |",
        "|---|---|---|---|---|",
        (
            f"| **Gemini 3-Image Joint Dossier (`{meta['model_id']}`)** | "
            f"**Exhibit 1 + Exhibit 2 + Exhibit 3 (`{ipc}` PNGs in 1 call)** | "
            f"**{m['top1_mole_hits']}/{n} ({m['top1_mole_accuracy'] * 100:.1f}%)** | "
            f"**{m['top1_decoy_hits']}/{n} ({m['top1_decoy_accuracy'] * 100:.1f}%)** | "
            f"**{m['avoided_framing_trap_hits']}/{n} ({m['avoided_framing_trap_rate'] * 100:.1f}%)** |"
        ),
        (
            f"| Exhibit 1 Only (Naive After-Hours Swipe Pick) | `badge_raster` PNG only (no canary roster, no leak feed) | "
            f"{m['image1_only_mole_hits']}/{n} ({m['image1_only_mole_accuracy'] * 100:.1f}%) | - | "
            f"{img1_avoided}/{n} ({img1_avoided_pct:.1f}%) |"
        ),
        (
            f"| Exhibit 2 Only (Leaked Memo Scans Only) | `leaked_memo_scans` PNG only (no employee IDs) | "
            f"{img2_mole_hits}/{n} ({m['image2_only_mole_accuracy'] * 100:.1f}%) | "
            f"{img2_decoy_hits}/{n} ({m['image2_only_decoy_accuracy'] * 100:.1f}%) | - |"
        ),
        (
            f"| Exhibit 3 Only (Static Floorplan + Canary Matrix) | "
            f"`org_canary_map` PNG only (no leak outcomes, uniform `1/N` prior = {m['image3_only_uniform_prior_mean'] * 100:.1f}%) | "
            f"{m['image3_only_deterministic_hits']}/{n} ({m['image3_only_deterministic_mole_accuracy'] * 100:.1f}%) | "
            f"0/{n} (0.0%) | - |"
        ),
        "",
        (
            f"- Exhibit 2 visual watermark scan readout exact match (`DOC-ID` + `COPY-CODE`): "
            f"`{m['memo_scans_matched_total']}/{m['memo_scans_expected_total']}` (`{m['memo_scan_readout_accuracy'] * 100:.1f}%`)"
        ),
        (
            f"- Exhibit 3 floorplan department attribution accuracy: "
            f"`{m['suspect_dept_hits']}/{n}` (`{m['suspect_dept_accuracy'] * 100:.1f}%`)"
        ),
        "",
        f"{H2}Per-World Cross-Image Breakdown",
        "| World | True Mole (Dept) | True Decoy | Img-1 Naive Pick | Leaked Canaries (Img 2) | Pred Mole Top-3 | Pred Decoy | Mole Top-1 | Decoy Top-1 |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for w in res["worlds"]:
        gt = w["ground_truth"]
        mo = w["model_output"]
        ev = w["evaluation"]
        sb = w["single_image_baselines"]
        scans = ", ".join(f"{s['doc_id']}={s['variant']}" for s in w["observable_summary"]["leaked_canary_scans"])
        lines.append(
            f"| `{w['seed_tag']}` | `{gt['true_mole']}` ({gt['true_mole_dept']}) | `{gt['true_decoy']}` | "
            f"`{sb['image1_only_naive_after_hours_pick']}` | `{scans}` | "
            f"`{', '.join(mo['top_suspect_ids'][:3])}` | `{', '.join(mo['suspected_decoy_ids'])}` | "
            f"{'YES' if ev['top1_mole_correct'] else 'NO'} | {'YES' if ev['top1_decoy_correct'] else 'NO'} |"
        )
    lines += [
        "",
        f"{H2}Rendered Composite Dossier PNGs ({n_img} Files)",
        "| World | Exhibit | Path | Dimensions | Bytes | SHA-256 |",
        "|---|---|---|---|---|---|",
    ]
    for d in meta["dossiers"]:
        for img in d["images"]:
            sz = img["size"]
            lines.append(
                f"| `{d['seed_tag']}` | `{img['kind']}` | `{img['path']}` | "
                f"{sz[0]}x{sz[1]} | {img['bytes']} | `{img['sha256']}` |"
            )
    lines += ["", f"{H2}Cross-Image Forensic Reasoning Excerpts"]
    for w in res["worlds"]:
        mo = w["model_output"]
        lines.append(
            f"- **`{w['seed_tag']}`** (conf `{mo['confidence']:.2f}`, dept `{mo['suspect_department']}`): "
            f"{_norm_dashes(mo['cross_image_reasoning'])}"
        )
    return "\n".join(lines) + "\n"


def _render_swarm_markdown(meta: dict[str, Any], sw: dict[str, Any]) -> str:
    c = sw["counts"]
    mode = sw["mode"]
    if mode == "whitebox":
        read_desc = (
            f"the whole repository in one long-context prompt "
            f"(**{meta['pack_files']} files, {meta['pack_tokens']} tokens**, cached)"
        )
    else:
        read_desc = "only the agent's instruction and tool list"
    vk = ", ".join(f"{k}: {v}" for k, v in c["violation_kinds"].items()) or "none"
    lines = [
        f"{H1}Canary Lab swarm: Gemini attackers vs the Canary reward",
        "",
        f"Generated {sw['generated_at']} at `{sw['git_sha'][:10]}`. Ledger run ids: {', '.join(sw['ledger_run_ids'])}.",
        "",
        (
            f"**{c['attempts']} Gemini attackers** ({mode}, planners: {', '.join(sw['models'])}; "
            f"executor: {sw['exec_model']}) each read {read_desc}, wrote a concrete exploit plan, "
            "and executed it against a live episode by function calling. "
            "Scores come only from the server-side ledger; invariants are checked in code on every call."
        ),
        "",
        f"- Verified exploits: **{c['exploits']}** {MID_DOT} invariant violations: {c['invariant_violations']} ({vk})",
        "- Score candidates (correct accusation at or above the solver mean minus 0.05): "
        f"{c['score_candidates']}; each is re-run on fresh seeds before it counts.",
        (
            f"- Tool calls executed: {c['tool_calls']} {MID_DOT} attempts through the real MCP server: "
            f"{c['mcp_attempts']} {MID_DOT} planner errors: {c['planner_errors']} {MID_DOT} errors: {c['errors']}"
        ),
        "",
        f"{H2}Scoreboard (per tier)",
        "",
        "| tier | attempts | best attacker score | mean attacker score | solver mean (paired seeds) | correct / accused | with violations | exploits |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for tier, r in sw["per_tier"].items():
        lines.append(
            f"| {tier} | {r['attempts']} | {r['best_non_solver']:+.3f} ({r['best_attempt']}) | "
            f"{r['mean_attempt_score']:+.3f} | {r['solver_mean_paired']:+.3f} | "
            f"{r['correct']} / {r['accused']} | {r['with_violations']} | {r['exploits']} |"
        )
    conf = sw.get("confirmations") or {}
    if conf:
        lines += [
            "",
            f"{H2}Score candidates re-run on fresh seeds",
            "",
            "| attempt | seeds | attacker scores | attacker mean | solver mean | confirmed |",
            "|---|---|---|---|---|---|",
        ]
        for aid, cr in conf.items():
            ok = "**yes**" if cr["confirmed"] else "no"
            lines.append(
                f"| {aid} | {cr['seeds']} | {[round(x, 2) for x in cr['scores']]} | "
                f"{cr['mean']:+.3f} | {cr['solver_mean']:+.3f} | {ok} |"
            )
    atts = sw["attempts"]
    top = sorted(atts, key=lambda a: (-len(a["invariant_violations"]), -(a.get("score") or -9)))[:8]
    lines += ["", f"{H2}Top attempts explained", ""]
    for a in top:
        pl = a.get("plan") or {}
        hyp = _norm_dashes(re.sub(r"\s+", " ", pl.get("hypothesis", ""))[:600])
        rep = _norm_dashes(re.sub(r"\s+", " ", a.get("executor_report") or "(none)")[:500])
        v_str = ", ".join(v["kind"] for v in a["invariant_violations"]) or "all held"
        code_refs = ", ".join((pl.get("code_refs") or [])[:4])
        lines += [
            f"{H3}{a['id']} ({a['persona']}, {a['model']}, {a['tier']}, {a.get('channel')})",
            f"- **Hypothesis:** {hyp}",
            (
                f"- **Target:** {pl.get('target_invariant')} {MID_DOT} expected score {pl.get('expected_score')} "
                f"{MID_DOT} confidence {pl.get('confidence')} {MID_DOT} code: {code_refs}"
            ),
            (
                f"- **Ledger:** score {a.get('score')} ({a.get('ledger_source')}), accused {a.get('accusations')}, "
                f"correct {a.get('correct')}, end {a.get('end_reason')} day {a.get('final_day')}; "
                f"paired solver {a.get('solver_score')}"
            ),
            f"- **Invariant checks:** {v_str}",
            f"- **Executor report:** {rep}",
            "",
        ]
    lines += [
        f"{H2}All attempts",
        "",
        "| id | persona | planner | tier | channel | score | solver (same seed) | correct | violations | exploit | hypothesis |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for a in atts:
        pl = a.get("plan") or {}
        hyp_short = _norm_dashes(re.sub(r"\s+", " ", pl.get("hypothesis", "")).replace("|", "/")[:160])
        v_cell = ", ".join(v["kind"] for v in a["invariant_violations"]) or "none"
        exp_cell = "**YES**" if a["exploit"] else "no"
        corr_cell = "yes" if a["correct"] else "no"
        lines.append(
            f"| {a['id']} | {a['persona']} | {a['model']} | {a['tier']} | {a['channel']} | "
            f"{float(a['score']):+.3f} | {float(a['solver_score']):+.3f} | "
            f"{corr_cell} | {v_cell} | {exp_cell} | {hyp_short} |"
        )
    lines += [
        "",
        "Reproduce: `python -m canary.gemini.swarm --attackers N --mode whitebox --tiers medium,hard --out DIR` "
        "(needs GEMINI_API_KEY or GEMINI_GATEWAY_URL). Keyless smoke: `--planner stub --executor script`.",
    ]
    return "\n".join(lines) + "\n"


def audit_run_folder(run_dir: Path) -> int:
    assert run_dir.is_dir(), run_dir
    for p in run_dir.rglob("*"):
        if p.is_dir():
            assert p.name not in {"memos", "dossiers", "rasters", "charts"}, p
            continue
        assert p.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp", ".py"}, p
        txt = p.read_text(encoding="utf-8")
        for dch in UNICODE_DASHES:
            assert dch not in txt, p
        assert "results/gemini_roles/" not in txt, p
        assert _scan_secrets(txt) == [], p

    meta = _load_json(run_dir / "meta.json")
    role = str(meta["role"])
    subrole = str(meta["subrole"])
    assert meta["model_id"] == TARGET_MODEL, run_dir
    assert COMMIT_RE.fullmatch(str(meta["commit"])) is not None, run_dir
    for flag in ("fake_env", "smoke", "stub", "synthetic"):
        assert not bool(meta.get(flag)), (run_dir, flag)

    u = meta["usage"]
    assert int(u["calls"]) > 0, run_dir
    assert int(u["in"]) > 0, run_dir
    assert int(u["out"]) > 0, run_dir
    assert float(u["cost_usd"]) > 0.0, run_dir

    if role == "multimodal_evidence":
        assert meta.get("part_from_bytes") is True, run_dir
        manifest = meta["image_manifest"]
        n_img = int(meta["n_images_read_by_model"])
        assert n_img > 0, run_dir
        assert manifest["count"] == n_img, run_dir
        assert manifest["mime_type"] == "image/png", run_dir
        imgs = manifest["images"]
        assert len(imgs) == n_img, run_dir
        assert sum(int(img["bytes"]) for img in imgs) == int(manifest["total_bytes"]), run_dir
        for img in imgs:
            assert img["size"] == [img["width"], img["height"]], run_dir
            assert int(img["bytes"]) > 0, run_dir
            assert SHA256_RE.fullmatch(str(img["sha256"])) is not None, run_dir
        manifest_by_path = {str(img["path"]): img for img in imgs}
        md_text = (run_dir / "summary.md").read_text(encoding="utf-8")
    else:
        assert role == "exploit_hunter", run_dir
        manifest_by_path = {}
        md_text = (run_dir / "swarm.md").read_text(encoding="utf-8")

    tables = _parse_md_tables(md_text)

    if subrole in ("soc_access_vision", "soc_access_vision_hard"):
        res = _load_json(run_dir / "results.json")
        assert meta["commit"] == res["commit"] == meta["git_sha"], run_dir
        assert meta["timestamp"] == res["timestamp"], run_dir
        assert meta["tier"] == res["tier"], run_dir
        assert meta["tiers_version"] == res["tiers_version"], run_dir
        worlds = res["worlds"]
        n = len(worlds)
        assert n == int(res["n_worlds"]) == int(meta["n_images_read_by_model"]) == len(meta["seeds"]), run_dir
        assert [int(w["seed"]) for w in worlds] == [int(s) for s in meta["seeds"]], run_dir

        for k in ("calls", "in", "out", "thinking", "cached"):
            assert int(u[k]) == int(res["usage"][k]), (run_dir, k)
        assert float(u["cost_usd"]) == pytest.approx(float(res["usage"]["cost_usd"]), abs=1e-9), run_dir
        assert float(u["latency_s"]) == pytest.approx(float(res["usage"]["latency_s"]), abs=1e-2), run_dir
        assert sum(int(w["usage"]["in"]) for w in worlds) == int(u["in"]), run_dir
        assert sum(int(w["usage"]["out"]) for w in worlds) == int(u["out"]), run_dir
        assert sum(int(w["usage"]["thinking"]) for w in worlds) == int(u["thinking"]), run_dir
        assert sum(float(w["usage"]["cost_usd"]) for w in worlds) == pytest.approx(float(u["cost_usd"]), abs=1e-5), run_dir
        assert sum(float(w["usage"]["latency_s"]) for w in worlds) == pytest.approx(float(u["latency_s"]), abs=5e-2), run_dir

        m = res["metrics"]
        assert m["top1_mole_hits"] == sum(1 for w in worlds if w["evaluation"]["top1_mole_correct"]), run_dir
        assert m["top3_mole_hits"] == sum(1 for w in worlds if w["evaluation"]["top3_mole_hit"]), run_dir
        assert m["top1_decoy_hits"] == sum(1 for w in worlds if w["evaluation"]["top1_decoy_correct"]), run_dir
        assert m["decoy_identified_hits"] == sum(1 for w in worlds if w["evaluation"]["decoy_identified"]), run_dir
        assert m["avoided_framing_trap_hits"] == sum(1 for w in worlds if w["evaluation"]["avoided_framing_trap"]), run_dir
        assert m["naive_baseline_mole_hits"] == sum(1 for w in worlds if w["evaluation"]["naive_baseline_mole_correct"]), run_dir
        assert m["naive_baseline_decoy_traps"] == sum(1 for w in worlds if w["evaluation"]["naive_baseline_trapped_by_decoy"]), run_dir
        assert float(m["top1_mole_accuracy"]) == pytest.approx(m["top1_mole_hits"] / n, abs=1e-6), run_dir

        for r, w in zip(meta["rasters"], worlds):
            m_img = manifest_by_path[r["path"]]
            assert r["path"] == w["raster_path"], run_dir
            assert r["sha256"] == w["raster_sha256"] == m_img["sha256"], run_dir
            assert r["bytes"] == w["raster_bytes"] == m_img["bytes"], run_dir
            assert r["size"] == w["raster_size"] == m_img["size"], run_dir

        assert len(tables) == 3, run_dir
        assert len(tables[0][1]) == 5 and len(tables[1][1]) == n and len(tables[2][1]) == n, run_dir
        expected_md = _render_soc_access_single_tier(meta, res)
        return _assert_markdown_numeric_parity(md_text, expected_md, run_dir)

    if subrole == "soc_access_vision_v14_sweep":
        res = _load_json(run_dir / "results.json")
        assert meta["commit"] == res["commit"] == meta["git_sha"], run_dir
        assert meta["timestamp"] == res["timestamp"], run_dir
        assert meta["tiers_version"] == res["tiers_version"], run_dir
        assert meta["tier_seeds"] == res["tier_seeds"], run_dir
        if "thinking_level" in meta:
            assert meta["thinking_level"] == res["thinking_level"], run_dir
        worlds = res["worlds"]
        n = len(worlds)
        assert n == int(meta["episode_count"]) == int(meta["n_worlds"]) == int(res["n_worlds"]), run_dir

        m = res["metrics"]
        for k in ("calls", "in", "out", "thinking", "cached"):
            assert int(u[k]) == int(m["usage"][k]), (run_dir, k)
        assert float(u["cost_usd"]) == pytest.approx(float(m["usage"]["cost_usd"]), abs=1e-9), run_dir
        assert float(u["latency_s"]) == pytest.approx(float(m["usage"]["latency_s"]), abs=1e-2), run_dir
        assert sum(int(w["usage"]["in"]) for w in worlds) == int(u["in"]), run_dir
        assert sum(int(w["usage"]["out"]) for w in worlds) == int(u["out"]), run_dir
        assert sum(int(w["usage"]["thinking"]) for w in worlds) == int(u["thinking"]), run_dir
        assert sum(float(w["usage"]["cost_usd"]) for w in worlds) == pytest.approx(float(u["cost_usd"]), abs=1e-5), run_dir
        assert sum(float(w["usage"]["latency_s"]) for w in worlds) == pytest.approx(float(u["latency_s"]), abs=5e-2), run_dir

        for metric_key in (
            "top1_mole_accuracy",
            "top3_mole_hit_rate",
            "naive_baseline_mole_accuracy",
            "mole_accuracy_delta_vs_naive",
            "top1_decoy_accuracy",
            "avoided_framing_trap_rate",
            "mean_confidence",
            "brier_score",
            "expected_calibration_error",
        ):
            assert float(meta[metric_key]) == pytest.approx(float(m[metric_key]), abs=1e-6), (run_dir, metric_key)

        recomp_brier = sum(
            (float(w["model_output"]["confidence"]) - (1.0 if w["evaluation"]["top1_mole_correct"] else 0.0)) ** 2
            for w in worlds
        ) / n
        recomp_conf = sum(float(w["model_output"]["confidence"]) for w in worlds) / n
        recomp_ece = _compute_5bin_ece(worlds)
        assert float(m["brier_score"]) == pytest.approx(recomp_brier, abs=1e-6), run_dir
        assert float(m["mean_confidence"]) == pytest.approx(recomp_conf, abs=1e-4), run_dir
        assert float(m["expected_calibration_error"]) == pytest.approx(recomp_ece, abs=1e-6), run_dir
        assert float(m["signed_calibration_gap"]) == pytest.approx(recomp_conf - float(m["top1_mole_accuracy"]), abs=1e-4), run_dir

        for tier, td in res["by_tier"].items():
            tw = [w for w in worlds if w["tier"] == tier]
            assert len(tw) == int(td["n_worlds"]), run_dir
            t_brier = sum(
                (float(w["model_output"]["confidence"]) - (1.0 if w["evaluation"]["top1_mole_correct"] else 0.0)) ** 2
                for w in tw
            ) / len(tw)
            t_ece = _compute_5bin_ece(tw)
            assert float(td["brier_score"]) == pytest.approx(t_brier, abs=1e-6), run_dir
            assert float(td["expected_calibration_error"]) == pytest.approx(t_ece, abs=1e-6), run_dir

        for r, w in zip(meta["rasters"], worlds):
            m_img = manifest_by_path[r["path"]]
            assert r["path"] == w["raster_path"], run_dir
            assert r["sha256"] == w["raster_sha256"] == m_img["sha256"], run_dir
            assert r["bytes"] == w["raster_bytes"] == m_img["bytes"], run_dir
            assert r["size"] == w["raster_size"] == m_img["size"], run_dir

        assert len(tables) == 3, run_dir
        assert len(tables[0][1]) == 8 and len(tables[1][1]) == n and len(tables[2][1]) == n, run_dir
        expected_md = _render_soc_access_sweep(meta, res)
        return _assert_markdown_numeric_parity(md_text, expected_md, run_dir)

    if subrole in ("belief_chart_forensics", "carbon_v14_trajectory_forensics"):
        diags = _load_json(run_dir / "diagnoses.json")
        n = len(diags)
        assert n == int(meta["n_charts_analyzed"]) == int(meta["n_images_read_by_model"]) == int(u["calls"]), run_dir
        assert sum(int(d["usage"]["in"]) for d in diags) == int(u["in"]), run_dir
        assert sum(int(d["usage"]["out"]) for d in diags) == int(u["out"]), run_dir
        assert sum(int(d["usage"]["thinking"]) for d in diags) == int(u["thinking"]), run_dir
        assert sum(float(d["usage"]["cost_usd"]) for d in diags) == pytest.approx(float(u["cost_usd"]), abs=1e-5), run_dir
        assert sum(float(d["usage"]["latency_s"]) for d in diags) == pytest.approx(float(u["latency_s"]), abs=5e-2), run_dir

        for idx, d in enumerate(diags):
            assert int(d["episode_index"]) == idx, run_dir
            m_img = manifest_by_path[d["chart_path"]]
            assert int(d["chart_bytes_len"]) == int(m_img["bytes"]), run_dir
            assert d["chart_sha256"] == m_img["sha256"], run_dir
            gt = d["ground_truth"]
            gd = d["gemini_diagnosis"]
            sc = d["scoring"]
            assert sc["threshold_match"] is (bool(gt["accused_below_ev_threshold"]) == bool(gd["accused_below_ev_threshold"])), run_dir
            day_err = abs(int(gd["estimated_accuse_day"]) - int(gt["actual_accuse_day"]))
            assert int(sc["day_abs_error"]) == day_err, run_dir
            assert sc["day_within_1"] is (day_err <= 1), run_dir
            assert sc["day_exact"] is (day_err == 0), run_dir
            assert sc["bleed_gap_match"] is (bool(gt["hidden_bleed_gap_present"]) == bool(gd["hidden_bleed_gap_present"])), run_dir
            if subrole == "carbon_v14_trajectory_forensics":
                assert sc["entropy_lag_match"] is (bool(gt["entropy_lags_solver"]) == bool(gd["entropy_lags_solver"])), run_dir

        assert float(meta["visual_threshold_accuracy"]) == pytest.approx(
            sum(1 for d in diags if d["scoring"]["threshold_match"]) / n, abs=1e-6
        ), run_dir
        assert float(meta["accuse_day_within_1_accuracy"]) == pytest.approx(
            sum(1 for d in diags if d["scoring"]["day_within_1"]) / n, abs=1e-6
        ), run_dir
        assert float(meta["accuse_day_exact_accuracy"]) == pytest.approx(
            sum(1 for d in diags if d["scoring"]["day_exact"]) / n, abs=1e-6
        ), run_dir
        assert float(meta["hidden_bleed_gap_accuracy"]) == pytest.approx(
            sum(1 for d in diags if d["scoring"]["bleed_gap_match"]) / n, abs=1e-6
        ), run_dir
        if subrole == "carbon_v14_trajectory_forensics":
            assert float(meta["entropy_lag_accuracy"]) == pytest.approx(
                sum(1 for d in diags if d["scoring"]["entropy_lag_match"]) / n, abs=1e-6
            ), run_dir
            assert float(meta["outcome_pattern_accuracy"]) == pytest.approx(
                sum(1 for d in diags if d["scoring"]["outcome_pattern_match"]) / n, abs=1e-6
            ), run_dir
            expected_md = _render_trajectory_forensics(meta, diags)
        else:
            expected_md = _render_belief_chart_forensics(meta, diags)

        assert len(tables) == 1 and len(tables[0][1]) == n, run_dir
        return _assert_markdown_numeric_parity(md_text, expected_md, run_dir)

    if subrole == "visual_memo_blind_ablation":
        comp = _load_json(run_dir / "comparison.json")
        vcs = [
            json.loads(ln)
            for ln in (run_dir / "vision_calls.jsonl").read_text(encoding="utf-8").splitlines()
            if ln.strip()
        ]
        assert meta["commit"] == comp["commit"] == meta["git_sha"], run_dir
        assert meta["timestamp"] == comp["timestamp"], run_dir
        assert meta["tier"] == comp["tier"], run_dir
        assert meta["seeds"] == comp["seeds"], run_dir
        assert meta["memos"] == comp["memos"], run_dir
        assert comp["vision_calls"] == vcs, run_dir

        n_ep = int(meta["n_episodes"])
        assert n_ep == int(comp["n_episodes"]) == len(comp["per_seed"]) == len(meta["seeds"]), run_dir
        assert len(vcs) == int(meta["n_images_read_by_model"]) == int(comp["n_images_read_by_model"]) == int(u["calls"]), run_dir
        n_canary = sum(1 for vc in vcs if vc["is_canary_memo"])
        assert n_canary == int(meta["n_canary_memos_read_by_model"]), run_dir

        assert sum(int(vc["usage"]["in"]) for vc in vcs) == int(u["in"]), run_dir
        assert sum(int(vc["usage"]["out"]) for vc in vcs) == int(u["out"]), run_dir
        assert sum(int(vc["usage"]["thinking"]) for vc in vcs) == int(u["thinking"]), run_dir
        assert sum(float(vc["usage"]["cost_usd"]) for vc in vcs) == pytest.approx(float(u["cost_usd"]), abs=1e-5), run_dir
        assert sum(float(vc["usage"]["latency_s"]) for vc in vcs) == pytest.approx(float(u["latency_s"]), abs=5e-2), run_dir

        s = comp["summary"]
        per_seed = comp["per_seed"]
        for cond, meta_score_key, meta_acc_key in (
            ("multimodal_carbon", "multimodal_mean_score", "multimodal_accuracy"),
            ("blind_no_vision", "blind_mean_score", "blind_accuracy"),
            ("text_oracle", "oracle_mean_score", "oracle_accuracy"),
        ):
            cs = s[cond]
            scores = [float(r[cond]["score"]) for r in per_seed]
            acc = sum(1 for r in per_seed if r[cond]["correct"]) / n_ep
            accused_days = [int(r[cond]["final_day"]) for r in per_seed if r[cond]["accused"] is not None]
            assert cs["scores"] == scores, run_dir
            assert float(cs["mean_score"]) == pytest.approx(sum(scores) / n_ep, abs=1e-4), run_dir
            assert float(meta[meta_score_key]) == pytest.approx(sum(scores) / n_ep, abs=1e-4), run_dir
            assert float(cs["accuracy"]) == pytest.approx(acc, abs=1e-6), run_dir
            assert float(meta[meta_acc_key]) == pytest.approx(acc, abs=1e-6), run_dir
            assert int(cs["accused_count"]) == len(accused_days), run_dir
            if accused_days:
                assert float(cs["mean_accuse_day"]) == pytest.approx(sum(accused_days) / len(accused_days), abs=1e-2), run_dir
            else:
                assert cs["mean_accuse_day"] is None, run_dir

        assert float(meta["blind_ablation_mean_score"]) == pytest.approx(float(meta["blind_mean_score"]), abs=1e-9), run_dir
        assert float(s["multimodal_minus_blind"]) == pytest.approx(
            float(s["multimodal_carbon"]["mean_score"]) - float(s["blind_no_vision"]["mean_score"]), abs=1e-4
        ), run_dir
        var_acc = sum(1 for vc in vcs if vc["variant_exact_match"]) / len(vcs)
        can_acc = sum(1 for vc in vcs if vc["is_canary_memo"] and vc["variant_exact_match"]) / n_canary
        assert float(meta["variant_vision_accuracy"]) == pytest.approx(var_acc, abs=1e-6), run_dir
        assert float(meta["canary_variant_vision_accuracy"]) == pytest.approx(can_acc, abs=1e-6), run_dir

        for m_row, vc in zip(meta["memos"], vcs):
            m_img = manifest_by_path[m_row["path"]]
            assert m_row["path"] == vc["memo_path"], run_dir
            assert m_row["sha256"] == vc["memo_sha256"] == m_img["sha256"], run_dir
            assert m_row["bytes"] == vc["memo_bytes"] == m_img["bytes"], run_dir
            assert m_row["size"] == vc["memo_size"] == m_img["size"], run_dir

        assert len(tables) == 3, run_dir
        assert len(tables[0][1]) == 3 and len(tables[1][1]) == n_ep and len(tables[2][1]) == len(vcs), run_dir
        expected_md = _render_memo_watermark_ablation(meta, comp)
        return _assert_markdown_numeric_parity(md_text, expected_md, run_dir)

    if subrole == "multi_image_incident_dossier":
        res = _load_json(run_dir / "results.json")
        assert meta["commit"] == res["commit"] == meta["git_sha"], run_dir
        assert meta["timestamp"] == res["timestamp"], run_dir
        assert meta["tiers_version"] == res["tiers_version"], run_dir
        worlds = res["worlds"]
        n = len(worlds)
        assert n == int(meta["episode_count"]) == int(res["episode_count"]) == len(meta["dossiers"]), run_dir
        assert int(meta["images_per_call"]) == int(res["images_per_call"]) == 3, run_dir
        assert int(meta["n_images_read_by_model"]) == int(res["n_images_read_by_model"]) == 3 * n, run_dir

        for k in ("calls", "in", "out", "thinking", "cached"):
            assert int(u[k]) == int(res["usage"][k]), (run_dir, k)
        assert float(u["cost_usd"]) == pytest.approx(float(res["usage"]["cost_usd"]), abs=1e-9), run_dir
        assert float(u["latency_s"]) == pytest.approx(float(res["usage"]["latency_s"]), abs=1e-2), run_dir
        assert sum(int(w["usage"]["in"]) for w in worlds) == int(u["in"]), run_dir
        assert sum(int(w["usage"]["out"]) for w in worlds) == int(u["out"]), run_dir
        assert sum(int(w["usage"]["thinking"]) for w in worlds) == int(u["thinking"]), run_dir
        assert sum(float(w["usage"]["cost_usd"]) for w in worlds) == pytest.approx(float(u["cost_usd"]), abs=1e-5), run_dir
        assert sum(float(w["usage"]["latency_s"]) for w in worlds) == pytest.approx(float(u["latency_s"]), abs=5e-2), run_dir

        m = res["metrics"]
        assert m["top1_mole_hits"] == sum(1 for w in worlds if w["evaluation"]["top1_mole_correct"]), run_dir
        assert m["top3_mole_hits"] == sum(1 for w in worlds if w["evaluation"]["top3_mole_hit"]), run_dir
        assert m["top1_decoy_hits"] == sum(1 for w in worlds if w["evaluation"]["top1_decoy_correct"]), run_dir
        assert m["avoided_framing_trap_hits"] == sum(1 for w in worlds if w["evaluation"]["avoided_framing_trap"]), run_dir
        assert m["memo_scans_matched_total"] == sum(int(w["evaluation"]["memo_scans_matched"]) for w in worlds), run_dir
        assert m["memo_scans_expected_total"] == sum(int(w["evaluation"]["memo_scans_total"]) for w in worlds), run_dir
        assert m["suspect_dept_hits"] == sum(1 for w in worlds if w["evaluation"]["suspect_dept_correct"]), run_dir
        assert m["image1_only_mole_hits"] == sum(1 for w in worlds if w["single_image_baselines"]["image1_only_mole_correct"]), run_dir
        assert m["image1_only_decoy_traps"] == sum(1 for w in worlds if w["single_image_baselines"]["image1_only_trapped_by_decoy"]), run_dir
        assert float(meta["top1_mole_accuracy"]) == pytest.approx(float(m["top1_mole_accuracy"]), abs=1e-6), run_dir
        assert float(meta["top1_decoy_accuracy"]) == pytest.approx(float(m["top1_decoy_accuracy"]), abs=1e-6), run_dir
        prior_mean = sum(float(w["single_image_baselines"]["image3_only_uniform_prior"]) for w in worlds) / n
        assert float(m["image3_only_uniform_prior_mean"]) == pytest.approx(prior_mean, abs=1e-6), run_dir

        for d_row, w in zip(meta["dossiers"], worlds):
            assert d_row["seed_tag"] == w["seed_tag"], run_dir
            assert len(d_row["images"]) == 3, run_dir
            for d_img in d_row["images"]:
                m_img = manifest_by_path[d_img["path"]]
                w_img = w["images"][d_img["kind"]]
                assert d_img["path"] == w_img["path"], run_dir
                assert d_img["sha256"] == w_img["sha256"] == m_img["sha256"], run_dir
                assert d_img["bytes"] == w_img["bytes"] == m_img["bytes"], run_dir
                assert d_img["size"] == w_img["size"] == m_img["size"], run_dir

        assert len(tables) == 3, run_dir
        assert len(tables[0][1]) == 4 and len(tables[1][1]) == n and len(tables[2][1]) == 3 * n, run_dir
        expected_md = _render_incident_dossier(meta, res)
        return _assert_markdown_numeric_parity(md_text, expected_md, run_dir)

    assert subrole in ("blackbox_mcp_swarm", "whitebox_repo_swarm"), (run_dir, subrole)
    sw = _load_json(run_dir / "swarm.json")
    c = sw["counts"]
    atts = sw["attempts"]
    assert meta["commit"] == sw["git_sha"], run_dir
    assert meta["mode"] == sw["mode"], run_dir
    assert meta["tiers"] == sw["tiers"], run_dir
    assert meta["ledger_run_id"] in sw["ledger_run_ids"], run_dir
    assert int(meta["attempts"]) == int(c["attempts"]) == len(atts), run_dir
    assert int(meta["mcp_attempts"]) == int(c["mcp_attempts"]) == sum(1 for a in atts if a["channel"] == "mcp"), run_dir
    assert int(meta["ledger_verified"]) == int(c["ledger_verified"]) == sum(1 for a in atts if a["ledger_verified"]), run_dir
    assert int(meta["tool_calls"]) == int(c["tool_calls"]) == sum(len(a["tool_calls"]) for a in atts), run_dir
    assert int(meta["exploits"]) == int(c["exploits"]) == sum(1 for a in atts if a["exploit"]), run_dir
    assert int(meta["invariant_violations"]) == int(c["invariant_violations"]) == sum(len(a["invariant_violations"]) for a in atts), run_dir
    assert int(c["planner_errors"]) == sum(1 for a in atts if (a.get("planner_meta") or {}).get("error")), run_dir

    if subrole == "whitebox_repo_swarm":
        assert int(meta["pack_files"]) == int(sw["pack_files"]), run_dir
        assert int(meta["pack_tokens"]) == int(sw["pack_tokens"]), run_dir
        assert int(meta["planner_errors"]) == int(c["planner_errors"]), run_dir
        assert int(meta["errors"]) == int(c["errors"]), run_dir
        assert meta["violation_kinds"] == c["violation_kinds"], run_dir

    for tier, r in sw["per_tier"].items():
        ta = [a for a in atts if a["tier"] == tier]
        assert int(r["attempts"]) == len(ta), run_dir
        assert float(r["best_non_solver"]) == pytest.approx(max(float(a["score"]) for a in ta), abs=1e-6), run_dir
        assert float(r["mean_attempt_score"]) == pytest.approx(sum(float(a["score"]) for a in ta) / len(ta), abs=1e-3), run_dir
        assert float(r["solver_mean_paired"]) == pytest.approx(sum(float(a["solver_score"]) for a in ta) / len(ta), abs=1e-3), run_dir
        assert int(r["correct"]) == sum(1 for a in ta if a["correct"]), run_dir
        assert int(r["accused"]) == sum(1 for a in ta if a["accusations"]), run_dir
        assert int(r["with_violations"]) == sum(1 for a in ta if a["invariant_violations"]), run_dir
        assert int(r["exploits"]) == sum(1 for a in ta if a["exploit"]), run_dir

    for aid, cr in (sw.get("confirmations") or {}).items():
        assert aid in {a["id"] for a in atts}, run_dir
        assert float(cr["mean"]) == pytest.approx(sum(float(x) for x in cr["scores"]) / len(cr["scores"]), abs=1e-6), run_dir
        assert float(cr["solver_mean"]) == pytest.approx(
            sum(float(x) for x in cr["solver_scores"]) / len(cr["solver_scores"]), abs=1e-6
        ), run_dir

    if (run_dir / "attempts.jsonl").is_file():
        jrows = [
            json.loads(ln)
            for ln in (run_dir / "attempts.jsonl").read_text(encoding="utf-8").splitlines()
            if ln.strip()
        ]
        by_id_sw = {a["id"]: a for a in atts}
        by_id_jl = {r["id"]: r for r in jrows}
        assert set(by_id_sw) == set(by_id_jl), run_dir
        for k, a in by_id_sw.items():
            jr = by_id_jl[k]
            for fld in ("persona", "model", "tier", "seed", "channel", "n_tool_calls", "score", "correct", "final_day", "solver_score"):
                assert a[fld] == jr[fld], (run_dir, k, fld)

    assert len(tables) == 3, run_dir
    expected_md = _render_swarm_markdown(meta, sw)
    return _assert_markdown_numeric_parity(md_text, expected_md, run_dir)


def test_all_19_run_folders_present_in_roles_carbon() -> None:
    assert len(EXPECTED_MM_RUNS) == 17
    assert len(EXPECTED_EH_RUNS) == 2
    assert len(ALL_19_RUNS) == 19

    actual_mm = tuple(sorted(p.name for p in MM_ROOT.iterdir() if p.is_dir() and (p / "meta.json").is_file()))
    actual_eh = tuple(sorted(p.name for p in EH_ROOT.iterdir() if p.is_dir() and (p / "meta.json").is_file()))
    assert set(EXPECTED_MM_RUNS).issubset(set(actual_mm))
    assert set(EXPECTED_EH_RUNS).issubset(set(actual_eh))
    assert len(actual_mm) + len(actual_eh) >= 19


@pytest.mark.parametrize("rel_run", ALL_19_RUNS)
def test_cross_artifact_numeric_parity_per_run_folder(rel_run: str) -> None:
    run_dir = ROLES_CARBON_ROOT / rel_run
    checked_numbers = audit_run_folder(run_dir)
    assert checked_numbers >= 25, (rel_run, checked_numbers)


def test_dynamic_all_roles_carbon_folders_numeric_parity_and_aggregate_totals() -> None:
    mm_dirs = sorted(p for p in MM_ROOT.iterdir() if p.is_dir() and (p / "meta.json").is_file())
    eh_dirs = sorted(p for p in EH_ROOT.iterdir() if p.is_dir() and (p / "meta.json").is_file())
    all_dirs = mm_dirs + eh_dirs
    assert len(all_dirs) >= 19

    total_numbers_checked = 0
    mm_calls = 0
    mm_images = 0
    mm_cost = 0.0
    eh_calls = 0
    eh_attempts = 0
    eh_cost = 0.0

    for d in mm_dirs:
        total_numbers_checked += audit_run_folder(d)
        meta = _load_json(d / "meta.json")
        if d.name in EXPECTED_MM_RUNS:
            mm_calls += int(meta["usage"]["calls"])
            mm_images += int(meta["n_images_read_by_model"])
            mm_cost += float(meta["usage"]["cost_usd"])

    for d in eh_dirs:
        total_numbers_checked += audit_run_folder(d)
        meta = _load_json(d / "meta.json")
        if d.name in EXPECTED_EH_RUNS:
            eh_calls += int(meta["usage"]["calls"])
            eh_attempts += int(meta["attempts"])
            eh_cost += float(meta["usage"]["cost_usd"])

    assert mm_calls == 226
    assert mm_images == 260
    assert mm_cost == pytest.approx(3.521048, abs=1e-6)
    assert eh_calls == 215
    assert eh_attempts == 11
    assert eh_cost == pytest.approx(3.244499, abs=1e-6)
    assert total_numbers_checked > 2500


@pytest.mark.parametrize(
    ("rel_run", "md_name", "old_snippet", "new_snippet"),
    (
        ("multimodal_evidence/access-heatmap-carbon", "summary.md", "in=6000", "in=6001"),
        ("multimodal_evidence/access-heatmap-v14-sweep-carbon", "summary.md", "0.039010", "0.039011"),
        ("multimodal_evidence/belief-chart-forensics-carbon", "summary.md", "0.183 vs 0.546", "0.184 vs 0.546"),
        ("multimodal_evidence/carbon-trajectory-forensics-v14-expanded", "summary.md", "`12/12`", "`11/12`"),
        ("multimodal_evidence/memo-watermark-hard-seeds10to14-carbon", "summary.md", "+0.3760", "+0.3761"),
        ("multimodal_evidence/multi-image-dossier-med6to8-hard5to7-carbon", "summary.md", "240074", "240075"),
        ("exploit_hunter/whitebox-swarm-carbon", "swarm.md", "203463 tokens", "203464 tokens"),
    ),
)
def test_tamper_detection_catches_single_digit_drift_across_all_subrole_families(
    tmp_path: Path,
    rel_run: str,
    md_name: str,
    old_snippet: str,
    new_snippet: str,
) -> None:
    src_dir = ROLES_CARBON_ROOT / rel_run
    dst_dir = tmp_path / Path(rel_run).name
    shutil.copytree(src_dir, dst_dir)
    assert audit_run_folder(dst_dir) > 0

    md_path = dst_dir / md_name
    original = md_path.read_text(encoding="utf-8")
    assert old_snippet in original
    md_path.write_text(original.replace(old_snippet, new_snippet, 1), encoding="utf-8")

    with pytest.raises(AssertionError):
        audit_run_folder(dst_dir)


def test_tamper_detection_catches_meta_vs_companion_json_drift(tmp_path: Path) -> None:
    src_dir = MM_ROOT / "access-heatmap-v14-high-s8to11-carbon"
    dst_dir = tmp_path / "access-heatmap-v14-high-s8to11-carbon"
    shutil.copytree(src_dir, dst_dir)

    meta_path = dst_dir / "meta.json"
    meta = _load_json(meta_path)
    meta["brier_score"] = float(meta["brier_score"]) + 0.01
    meta_path.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")

    with pytest.raises(AssertionError):
        audit_run_folder(dst_dir)


def test_zero_comments_zero_dashes_zero_secrets_and_zero_network() -> None:
    self_path = Path(__file__).resolve()
    src = self_path.read_text(encoding="utf-8")
    assert HASH_CHAR not in src
    for dch in UNICODE_DASHES:
        assert dch not in src
    assert src.isascii()

    tokens = list(tokenize.generate_tokens(io.StringIO(src).readline))
    comments = [tok for tok in tokens if tok.type == tokenize.COMMENT]
    assert comments == []
    assert _scan_secrets(src) == []

    with pytest.raises(RuntimeError, match="disabled"):
        socket.create_connection(("127.0.0.1", 1), timeout=0.01)
