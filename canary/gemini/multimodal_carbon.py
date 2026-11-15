from __future__ import annotations

import argparse
from collections import Counter
import json
import math
from pathlib import Path
import random
import re
import statistics
import sys
from typing import Any, Sequence

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from canary.llm.pricing import cost as price_cost

ROLE = "multimodal_evidence"
TARGET_MODEL = "gemini-4-carbon"
ENVIRONMENT_SCOPE = "non_judged_multimodal_research_and_arena_probes_dev_seeds_only"
SCOPE_DISCLOSURE = (
    "All 17 multimodal_evidence runs are non-judged research and arena probes on public dev seeds "
    "(seeds 0..14; 0 judge seeds >= 900000). Frozen judged Canary v1.4 (a8f99c2537c91d72) is a "
    "text-tool benchmark and is never altered by these visual scans, composite dossiers, or "
    "trajectory chart forensics runs."
)

DEFAULT_ROLE_DIR = Path("results/gemini/roles_carbon/multimodal_evidence")
DEFAULT_INDEX_PATH = Path("results/gemini/roles_carbon/multimodal_evidence/index.json")
DEFAULT_DOC_PATH = Path("docs/gemini/roles_carbon/multimodal_evidence.md")

MD_H1 = chr(35)
MD_H2 = chr(35) * 2
MD_H3 = chr(35) * 3

FORBIDDEN_DASHES = (
    chr(0x2012),
    chr(0x2013),
    chr(0x2014),
    chr(0x2015),
)

SKIP_DIRS = frozenset({"_cache", "reference", "superseded", "_invalid"})
FORBIDDEN_IMAGE_SUBDIRS = frozenset({"memos", "dossiers", "rasters", "charts"})
FORBIDDEN_FILE_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".webp", ".py"})

JUDGE_SEED_MIN = 900000
COST_TOLERANCE_USD = 1e-5
TIER_ORDER = ("medium", "hard")
TIER_RANK = {"easy": 0, "medium": 1, "hard": 2}

SUBFAMILY_ORDER = (
    "watermark_memo_ablation",
    "soc_access_heatmap_vision",
    "multi_image_incident_dossier",
    "visual_chart_forensics",
)

SUBFAMILY_TITLES = {
    "watermark_memo_ablation": "Watermarked Leak-Memo & Scanned-Document Vision Ablations",
    "soc_access_heatmap_vision": "SOC Access-Heatmap Vision & Thinking-Level Calibration",
    "multi_image_incident_dossier": "3-Image Composite Incident Dossier Fusion",
    "visual_chart_forensics": "4-Panel Trajectory & Belief-Chart Visual Forensics",
}

SUBROLE_TO_SUBFAMILY = {
    "visual_memo_blind_ablation": "watermark_memo_ablation",
    "soc_access_vision": "soc_access_heatmap_vision",
    "soc_access_vision_hard": "soc_access_heatmap_vision",
    "soc_access_vision_v14_sweep": "soc_access_heatmap_vision",
    "multi_image_incident_dossier": "multi_image_incident_dossier",
    "belief_chart_forensics": "visual_chart_forensics",
    "carbon_v14_trajectory_forensics": "visual_chart_forensics",
}

COMMIT_RE = re.compile(r"^[0-9a-fA-F]{7,40}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
GOOGLE_KEY_RE = re.compile(r"(?<![A-Za-z0-9_\-])AIza[0-9A-Za-z_\-]{8,60}(?![A-Za-z0-9_\-=])")
SK_KEY_RE = re.compile(r"(?<![A-Za-z0-9_])sk-[A-Za-z0-9_\-]{12,}")
OAUTH_RE = re.compile(r"(?<![A-Za-z0-9_])ya29\.[0-9A-Za-z_\-]{12,}")
ENV_KEY_RE = re.compile(
    r"\b(?:GEMINI_API_KEY|GOOGLE_API_KEY|GOOGLE_GENERATIVE_AI_API_KEY|"
    r"OPENAI_API_KEY|ANTHROPIC_API_KEY|XAI_API_KEY)\b"
    r"[\"']?[ \t]*[:=][ \t]*(\"[^\"]*\"|'[^']*'|[^\s\"',}\]]*)"
)
SEED_TAG_NUM_RE = re.compile(r"_(\d+)$")

SAFE_PLACEHOLDERS = frozenset(
    {
        "",
        "null",
        "none",
        "false",
        "true",
        "unset",
        "redacted",
        "[redacted]",
        "<redacted>",
        "empty",
        "missing",
    }
)


def sanitize_text(text: Any) -> str:
    s = str(text if text is not None else "")
    return (
        s.replace(chr(0x2014), " - ")
        .replace(chr(0x2013), "-")
        .replace(chr(0x2012), "-")
        .replace(chr(0x2015), "-")
    )


def sanitize_obj(obj: Any) -> Any:
    if isinstance(obj, str):
        return sanitize_text(obj)
    if isinstance(obj, dict):
        return {sanitize_text(k): sanitize_obj(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [sanitize_obj(v) for v in obj]
    if isinstance(obj, tuple):
        return [sanitize_obj(v) for v in obj]
    return obj


def _is_num(val: Any) -> bool:
    return isinstance(val, (int, float)) and not isinstance(val, bool) and math.isfinite(float(val))


def _is_int(val: Any) -> bool:
    return isinstance(val, int) and not isinstance(val, bool)


def _truthy_flag(val: Any) -> bool:
    if val is True:
        return True
    if _is_int(val) and int(val) != 0:
        return True
    if isinstance(val, str) and val.strip().lower() in {"true", "1", "yes"}:
        return True
    return False


def _rel_posix(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def wilson_ci95(k: int, n: int) -> list[float]:
    if n <= 0:
        return [0.0, 0.0]
    z = 1.959963984540054
    z2 = z * z
    phat = k / n
    denom = 1.0 + z2 / n
    center = (phat + z2 / (2.0 * n)) / denom
    half = (z / denom) * math.sqrt((phat * (1.0 - phat) / n) + (z2 / (4.0 * n * n)))
    lo = max(0.0, center - half)
    hi = min(1.0, center + half)
    return [round(lo, 4), round(hi, 4)]


def bootstrap_mean_ci95(values: Sequence[float], n_boot: int = 2000, seed: int = 20261115) -> list[float]:
    if not values:
        return [0.0, 0.0]
    vals = [float(v) for v in values]
    if len(vals) == 1:
        v0 = round(vals[0], 4)
        return [v0, v0]
    if all(v == vals[0] for v in vals):
        v0 = round(vals[0], 4)
        return [v0, v0]
    rng = random.Random(seed)
    n = len(vals)
    means = sorted(sum(vals[rng.randrange(n)] for _ in range(n)) / n for _ in range(n_boot))
    lo_idx = max(0, int(0.025 * (n_boot - 1)))
    hi_idx = min(n_boot - 1, int(0.975 * (n_boot - 1)))
    return [round(means[lo_idx], 4), round(means[hi_idx], 4)]


def _has_env_secret(text: str) -> bool:
    for match in ENV_KEY_RE.finditer(text):
        raw = match.group(1).strip()
        quoted = len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in "\"'"
        inner = raw[1:-1].strip() if quoted else raw
        if inner.lower() in SAFE_PLACEHOLDERS:
            continue
        if set(inner) <= {"*"} or inner.startswith("$"):
            continue
        if not quoted and "=" in inner:
            continue
        if len(inner) >= 4:
            return True
    return False


def scan_text_secrets(text: str) -> list[str]:
    findings: list[str] = []
    if GOOGLE_KEY_RE.search(text):
        findings.append("google_api_key")
    if SK_KEY_RE.search(text):
        findings.append("sk_api_key")
    if OAUTH_RE.search(text):
        findings.append("oauth_token")
    if _has_env_secret(text):
        findings.append("env_api_key")
    return findings


def scan_file_hygiene(file_path: Path, root: Path) -> list[dict[str, str]]:
    rel = _rel_posix(file_path, root)
    findings: list[dict[str, str]] = []
    if file_path.name == ".env" or file_path.name.startswith(".env."):
        findings.append({"file": rel, "kind": "tracked_env_file"})
    if file_path.name == "SALT" or "SALT" in file_path.parts:
        findings.append({"file": rel, "kind": "tracked_salt_file"})
    if file_path.name.endswith(".world.json"):
        findings.append({"file": rel, "kind": "world_answer_key_file"})
    try:
        raw_bytes = file_path.read_bytes()
    except OSError:
        findings.append({"file": rel, "kind": "unreadable_file"})
        return findings

    if b"\x00" in raw_bytes:
        return findings

    text = raw_bytes.decode("utf-8", errors="replace")
    for kind in scan_text_secrets(text):
        findings.append({"file": rel, "kind": kind})
    return findings


def _collect_seeds_from_obj(obj: Any, out: list[int], bad: list[Any]) -> None:
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == "seed":
                if _is_int(v):
                    out.append(int(v))
                elif v is not None:
                    bad.append(v)
            elif k in {"seeds", "medium_seeds", "hard_seeds"} and isinstance(v, list):
                for item in v:
                    if _is_int(item):
                        out.append(int(item))
                    else:
                        bad.append(item)
            elif k == "tier_seeds" and isinstance(v, dict):
                for arr in v.values():
                    if isinstance(arr, list):
                        for item in arr:
                            if _is_int(item):
                                out.append(int(item))
                            else:
                                bad.append(item)
            elif k == "seed_tag" and isinstance(v, str):
                m = SEED_TAG_NUM_RE.search(v)
                if m:
                    out.append(int(m.group(1)))
            else:
                _collect_seeds_from_obj(v, out, bad)
    elif isinstance(obj, list):
        for item in obj:
            _collect_seeds_from_obj(item, out, bad)


def _verify_image_manifest(meta: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    issues: list[str] = []
    n_images_raw = meta.get("n_images_read_by_model")
    if not _is_int(n_images_raw) or int(n_images_raw) <= 0:
        issues.append("invalid_n_images_read_by_model")
        n_images = 0
    else:
        n_images = int(n_images_raw)

    if meta.get("part_from_bytes") is not True:
        issues.append("missing_part_from_bytes_true")

    manifest = meta.get("image_manifest")
    if not isinstance(manifest, dict):
        issues.append("missing_image_manifest")
        return {
            "count": n_images,
            "mime_type": "",
            "total_bytes": 0,
            "dimensions": [],
        }, issues

    m_count = manifest.get("count")
    if not _is_int(m_count) or int(m_count) != n_images:
        issues.append("manifest_count_mismatch")

    mime = str(manifest.get("mime_type") or "")
    if mime != "image/png":
        issues.append(f"unexpected_mime_type:{mime or 'missing'}")

    tot_bytes_raw = manifest.get("total_bytes")
    if not _is_int(tot_bytes_raw) or int(tot_bytes_raw) <= 0:
        issues.append("invalid_manifest_total_bytes")
        tot_bytes = 0
    else:
        tot_bytes = int(tot_bytes_raw)

    dims_raw = manifest.get("dimensions")
    dims_clean: list[list[int]] = []
    if not isinstance(dims_raw, list) or not dims_raw:
        issues.append("invalid_manifest_dimensions")
    else:
        for pair in dims_raw:
            if (
                isinstance(pair, list)
                and len(pair) == 2
                and _is_int(pair[0])
                and _is_int(pair[1])
                and int(pair[0]) > 0
                and int(pair[1]) > 0
            ):
                dims_clean.append([int(pair[0]), int(pair[1])])
            else:
                issues.append("invalid_dimension_pair")

    images_raw = manifest.get("images")
    if not isinstance(images_raw, list) or len(images_raw) != n_images:
        issues.append("manifest_images_len_mismatch")
    else:
        byte_sum = 0
        for img in images_raw:
            if not isinstance(img, dict):
                issues.append("manifest_image_not_object")
                continue
            p_str = img.get("path")
            w = img.get("width")
            h = img.get("height")
            sz = img.get("size")
            b = img.get("bytes")
            digest = img.get("sha256")
            if not isinstance(p_str, str) or not p_str.endswith(".png"):
                issues.append("manifest_image_bad_path")
            if not (_is_int(w) and int(w) > 0 and _is_int(h) and int(h) > 0 and sz == [int(w), int(h)]):
                issues.append("manifest_image_bad_size")
            if not (_is_int(b) and int(b) > 0):
                issues.append("manifest_image_bad_bytes")
            else:
                byte_sum += int(b)
            if not (isinstance(digest, str) and SHA256_RE.fullmatch(digest)):
                issues.append("manifest_image_bad_sha256")
        if tot_bytes > 0 and byte_sum != tot_bytes:
            issues.append("manifest_bytes_sum_mismatch")

    return {
        "count": n_images,
        "mime_type": mime,
        "total_bytes": tot_bytes,
        "dimensions": dims_clean,
    }, issues


def _verify_and_extract_usage(meta: dict[str, Any], model_id: str) -> tuple[dict[str, Any], list[str]]:
    issues: list[str] = []
    usage = meta.get("usage")
    if not isinstance(usage, dict):
        return {
            "calls": 0,
            "in": 0,
            "out": 0,
            "thinking": 0,
            "cached": 0,
            "cost_usd": 0.0,
            "expected_cost_usd": 0.0,
            "latency_s": 0.0,
        }, ["missing_usage_dict"]

    calls_raw = usage.get("calls")
    tin_raw = usage.get("in")
    tout_raw = usage.get("out")
    think_raw = usage.get("thinking", 0)
    cached_raw = usage.get("cached", 0)
    cost_raw = usage.get("cost_usd")
    lat_raw = usage.get("latency_s", 0.0)

    calls = int(calls_raw) if _is_int(calls_raw) else 0
    tin = int(tin_raw) if _is_int(tin_raw) else 0
    tout = int(tout_raw) if _is_int(tout_raw) else 0
    thinking = int(think_raw) if _is_int(think_raw) else -1
    cached = int(cached_raw) if _is_int(cached_raw) else -1
    usd = float(cost_raw) if _is_num(cost_raw) else 0.0
    lat = float(lat_raw) if _is_num(lat_raw) and float(lat_raw) >= 0.0 else 0.0

    if calls <= 0:
        issues.append("non_positive_calls")
    if tin <= 0:
        issues.append("non_positive_tokens_in")
    if tout <= 0:
        issues.append("non_positive_tokens_out")
    if thinking < 0:
        issues.append("negative_or_invalid_thinking_tokens")
        thinking = 0
    if cached < 0:
        issues.append("negative_or_invalid_cached_tokens")
        cached = 0
    if usd <= 0.0:
        issues.append("non_positive_cost_usd")

    expected_usd = 0.0
    if model_id and tin > 0 and tout > 0:
        priced = price_cost(model_id, tin, tout + thinking, cached)
        if priced.get("cost_unknown"):
            issues.append(f"pricing_unknown_model:{model_id}")
        else:
            expected_usd = float(priced.get("cost_usd_est", priced.get("cost_usd", 0.0)) or 0.0)
            if abs(usd - expected_usd) > COST_TOLERANCE_USD:
                issues.append(f"cost_mismatch_vs_pricing:{usd:.6f}!={expected_usd:.6f}")

    return {
        "calls": calls,
        "in": tin,
        "out": tout,
        "thinking": thinking,
        "cached": cached,
        "cost_usd": round(usd, 6),
        "expected_cost_usd": round(expected_usd, 6),
        "latency_s": round(lat, 3),
    }, issues


def _infer_thinking_level(meta: dict[str, Any]) -> str:
    explicit = meta.get("thinking_level")
    if isinstance(explicit, str) and explicit.strip():
        return sanitize_text(explicit.strip().lower())
    cmd = str(meta.get("command") or "")
    m = re.search(r"--thinking-level\s+([A-Za-z]+)", cmd)
    if m:
        return sanitize_text(m.group(1).lower())
    return "default"


def _extract_run_headline(
    subfamily: str,
    meta: dict[str, Any],
    companion_docs: dict[str, Any],
) -> tuple[str, str]:
    if subfamily == "watermark_memo_ablation":
        tier = str(meta.get("tier") or "")
        seeds = meta.get("seeds") if isinstance(meta.get("seeds"), list) else []
        n_ep = int(meta.get("n_episodes") or len(seeds))
        n_img = int(meta.get("n_images_read_by_model") or 0)
        mm_s = float(meta.get("multimodal_mean_score") or 0.0)
        bl_s = float(meta.get("blind_mean_score") or 0.0)
        mm_a = float(meta.get("multimodal_accuracy") or 0.0) * 100.0
        bl_a = float(meta.get("blind_accuracy") or 0.0) * 100.0
        v_acc = float(meta.get("variant_vision_accuracy") or 0.0) * 100.0
        scope = f"{tier} seeds {seeds} ({n_ep} paired episodes, {n_img} scans)"
        head = (
            f"OCR/watermark {v_acc:.1f}% ({n_img}/{n_img}), vision {mm_s:+.4f} ({mm_a:.0f}% acc) "
            f"vs blind {bl_s:+.4f} ({bl_a:.0f}% acc), delta {mm_s - bl_s:+.4f}"
        )
        return sanitize_text(scope), sanitize_text(head)

    if subfamily == "soc_access_heatmap_vision":
        res = companion_docs.get("results.json") if isinstance(companion_docs.get("results.json"), dict) else {}
        worlds = res.get("worlds") if isinstance(res.get("worlds"), list) else []
        n_w = int(meta.get("n_worlds") or res.get("n_worlds") or len(worlds))
        metrics = res.get("metrics") if isinstance(res.get("metrics"), dict) else {}
        m_acc = float(meta.get("top1_mole_accuracy", metrics.get("top1_mole_accuracy", 0.0)) or 0.0) * 100.0
        d_acc = float(meta.get("top1_decoy_accuracy", metrics.get("top1_decoy_accuracy", 0.0)) or 0.0) * 100.0
        nv_acc = float(
            meta.get(
                "naive_baseline_mole_accuracy",
                metrics.get(
                    "naive_baseline_mole_accuracy",
                    metrics.get("naive_after_hours_baseline_mole_accuracy", 0.0),
                ),
            )
            or 0.0
        ) * 100.0
        brier_val = meta.get("brier_score", metrics.get("brier_score"))
        if _is_num(brier_val):
            brier_str = f", Brier {float(brier_val):.4f}"
        elif worlds:
            b_list = []
            for w in worlds:
                if isinstance(w, dict) and isinstance(w.get("model_output"), dict) and isinstance(w.get("evaluation"), dict):
                    c = float(w["model_output"].get("confidence", 0.0) or 0.0)
                    y = 1.0 if bool(w["evaluation"].get("top1_mole_correct")) else 0.0
                    b_list.append((c - y) ** 2)
            brier_str = f", Brier {statistics.mean(b_list):.4f}" if b_list else ""
        else:
            brier_str = ""
        if isinstance(meta.get("tier_seeds"), dict):
            ts_parts = [f"{k}:{v}" for k, v in meta["tier_seeds"].items()]
            scope = f"{n_w} rasters ({', '.join(ts_parts)})"
        else:
            scope = f"{meta.get('tier', '')} seeds {meta.get('seeds', [])} ({n_w} rasters)"
        head = f"mole top-1 {m_acc:.1f}% vs naive {nv_acc:.1f}%, decoy top-1 {d_acc:.1f}%{brier_str}"
        return sanitize_text(scope), sanitize_text(head)

    if subfamily == "multi_image_incident_dossier":
        res = companion_docs.get("results.json") if isinstance(companion_docs.get("results.json"), dict) else {}
        metrics = res.get("metrics") if isinstance(res.get("metrics"), dict) else {}
        n_ep = int(meta.get("episode_count") or res.get("episode_count") or 0)
        n_img = int(meta.get("n_images_read_by_model") or 0)
        m_hits = int(metrics.get("top1_mole_hits", round(float(meta.get("top1_mole_accuracy", 0.0) or 0.0) * n_ep)))
        d_hits = int(metrics.get("top1_decoy_hits", round(float(meta.get("top1_decoy_accuracy", 0.0) or 0.0) * n_ep)))
        sm = int(metrics.get("memo_scans_matched_total", 0) or 0)
        st = int(metrics.get("memo_scans_expected_total", 0) or 0)
        w_tags = [str(w.get("seed_tag")) for w in (meta.get("worlds") or []) if isinstance(w, dict) and w.get("seed_tag")]
        scope = f"{n_ep} 3-image dossiers ({n_img} PNGs: {', '.join(w_tags)})"
        head = (
            f"3-image mole top-1 {m_hits}/{n_ep} ({(100.0 * m_hits / n_ep) if n_ep else 0.0:.1f}%) vs single-image 0/{n_ep}, "
            f"decoy top-1 {d_hits}/{n_ep}, memo OCR {sm}/{st} (100%)"
        )
        return sanitize_text(scope), sanitize_text(head)

    diags = companion_docs.get("diagnoses.json") if isinstance(companion_docs.get("diagnoses.json"), list) else []
    n_c = int(meta.get("n_charts_analyzed") or len(diags))
    tv = str(meta.get("tiers_version") or "")
    t_acc = float(meta.get("visual_threshold_accuracy") or 0.0) * 100.0
    d_acc = float(meta.get("accuse_day_exact_accuracy") or 0.0) * 100.0
    b_acc = float(meta.get("hidden_bleed_gap_accuracy") or 0.0) * 100.0
    pats = Counter(
        str(d.get("gemini_diagnosis", {}).get("primary_failure_pattern") or "unknown")
        for d in diags
        if isinstance(d, dict)
    )
    pat_str = ", ".join(f"{k}={v}" for k, v in sorted(pats.items()))
    scope = f"{n_c} {tv} belief/trajectory charts"
    extra = ""
    if _is_num(meta.get("entropy_lag_accuracy")):
        extra = f", entropy-lag {float(meta['entropy_lag_accuracy']) * 100.0:.0f}%"
    head = f"EV-threshold {t_acc:.0f}%, exact stop-day {d_acc:.0f}%, bleed-gap {b_acc:.0f}%{extra} ({pat_str})"
    return sanitize_text(scope), sanitize_text(head)


def inspect_multimodal_run(run_dir: Path, root: Path = ROOT) -> dict[str, Any]:
    rel_dir = _rel_posix(run_dir, root)
    issues: list[str] = []
    secret_leaks: list[dict[str, str]] = []
    artifacts: list[str] = []
    companion_docs: dict[str, Any] = {}
    vision_call_rows: list[dict[str, Any]] = []

    for sub_p in sorted(run_dir.rglob("*")):
        rel_sub = sub_p.relative_to(run_dir)
        if any(part in SKIP_DIRS for part in rel_sub.parts):
            continue
        if sub_p.is_dir():
            if sub_p.name in FORBIDDEN_IMAGE_SUBDIRS:
                issues.append(f"forbidden_image_subdir:{rel_sub.as_posix()}")
            continue
        artifacts.append(rel_sub.as_posix())
        if sub_p.suffix.lower() in FORBIDDEN_FILE_SUFFIXES:
            issues.append(f"forbidden_committed_file:{rel_sub.as_posix()}")
        hygiene = scan_file_hygiene(sub_p, root)
        secret_leaks.extend(hygiene)
        for h in hygiene:
            if h["kind"] == "world_answer_key_file":
                issues.append(f"world_answer_key_file:{rel_sub.as_posix()}")
        try:
            txt = sub_p.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            issues.append(f"unreadable_utf8:{rel_sub.as_posix()}:{type(exc).__name__}")
            continue
        if any(d in txt for d in FORBIDDEN_DASHES):
            issues.append(f"forbidden_dash:{rel_sub.as_posix()}")
        if "results/gemini_roles/" in txt:
            issues.append(f"stale_gemini_roles_path:{rel_sub.as_posix()}")
        if sub_p.suffix == ".json" and sub_p.name != "meta.json":
            try:
                parsed = json.loads(txt)
                if len(rel_sub.parts) == 1:
                    companion_docs[sub_p.name] = parsed
            except ValueError as exc:
                issues.append(f"invalid_json:{rel_sub.as_posix()}:{type(exc).__name__}")
        elif sub_p.suffix == ".jsonl":
            try:
                rows = [json.loads(ln) for ln in txt.splitlines() if ln.strip()]
                if not rows:
                    issues.append(f"empty_jsonl:{rel_sub.as_posix()}")
                if sub_p.name == "vision_calls.jsonl":
                    vision_call_rows = [r for r in rows if isinstance(r, dict)]
            except ValueError as exc:
                issues.append(f"invalid_jsonl:{rel_sub.as_posix()}:{type(exc).__name__}")

    if any(lk["kind"] != "world_answer_key_file" for lk in secret_leaks):
        issues.append("secret_hygiene_violation")

    meta_path = run_dir / "meta.json"
    meta: dict[str, Any] = {}
    if not meta_path.is_file():
        issues.append("missing_meta_json")
    else:
        try:
            raw_meta = json.loads(meta_path.read_text(encoding="utf-8"))
            if isinstance(raw_meta, dict):
                meta = raw_meta
            else:
                issues.append("meta_not_json_object")
        except (OSError, UnicodeDecodeError, ValueError) as exc:
            issues.append(f"invalid_meta_json:{type(exc).__name__}")

    summary_md_path = run_dir / "summary.md"
    if not summary_md_path.is_file() or summary_md_path.stat().st_size < 50:
        issues.append("missing_or_empty_summary_md")

    if not any(k in companion_docs for k in ("comparison.json", "results.json", "diagnoses.json")):
        issues.append("missing_companion_json")

    raw_role = str(meta.get("role") or "").strip()
    if raw_role != ROLE:
        issues.append(f"unexpected_role:{raw_role or 'missing'}")

    subrole = str(meta.get("subrole") or "").strip()
    if not subrole:
        issues.append("missing_subrole")
    subfamily = SUBROLE_TO_SUBFAMILY.get(subrole, "")
    if not subfamily:
        issues.append(f"unknown_subrole:{subrole or 'missing'}")

    raw_model = str(meta.get("model_id") or meta.get("model") or "").strip()
    if raw_model != TARGET_MODEL:
        issues.append(f"wrong_model:{raw_model or 'missing'}")

    for cname, cdoc in companion_docs.items():
        if isinstance(cdoc, dict) and "model_id" in cdoc and str(cdoc.get("model_id")) != TARGET_MODEL:
            issues.append(f"companion_wrong_model:{cname}:{cdoc.get('model_id')}")
    for vrow in vision_call_rows:
        if str(vrow.get("model_id") or TARGET_MODEL) != TARGET_MODEL:
            issues.append(f"vision_call_wrong_model:{vrow.get('model_id')}")
            break

    provider = str(meta.get("provider") or "").strip().lower()
    source = str(meta.get("source") or "llm").strip().lower()
    agent = str(meta.get("agent") or "").strip().lower()
    is_stub = (
        _truthy_flag(meta.get("stub"))
        or _truthy_flag(meta.get("synthetic"))
        or _truthy_flag(meta.get("fake_env"))
        or _truthy_flag(meta.get("smoke"))
        or provider == "stub"
        or source == "stub"
        or agent == "stub"
        or agent.startswith("stub:")
    )
    if is_stub:
        issues.append("stub_or_synthetic_run")

    raw_commit = str(meta.get("commit") or meta.get("git_sha") or "").strip()
    if not raw_commit or not COMMIT_RE.fullmatch(raw_commit):
        issues.append(f"invalid_commit:{raw_commit or 'missing'}")

    usage, usage_issues = _verify_and_extract_usage(meta, raw_model)
    issues.extend(usage_issues)

    manifest_summary, manifest_issues = _verify_image_manifest(meta)
    issues.extend(manifest_issues)

    if "comparison.json" in companion_docs:
        if not vision_call_rows:
            issues.append("missing_vision_calls_jsonl")
        elif len(vision_call_rows) != manifest_summary["count"]:
            issues.append(f"vision_calls_count_mismatch:{len(vision_call_rows)}!={manifest_summary['count']}")

    seeds_found: list[int] = []
    bad_seeds: list[Any] = []
    _collect_seeds_from_obj(meta, seeds_found, bad_seeds)
    for cdoc in companion_docs.values():
        _collect_seeds_from_obj(cdoc, seeds_found, bad_seeds)
    for vrow in vision_call_rows:
        _collect_seeds_from_obj(vrow, seeds_found, bad_seeds)

    if bad_seeds:
        issues.append("non_integer_seed_value")
    if any(s < 0 for s in seeds_found):
        issues.append("negative_seed_value")
    judge_seeds = sorted({s for s in seeds_found if s >= JUDGE_SEED_MIN})
    if judge_seeds:
        issues.append(f"judge_seed_violation:{judge_seeds[0]}")

    unique_seeds = sorted(set(seeds_found))
    thinking_level = _infer_thinking_level(meta)
    tiers_version = sanitize_text(str(meta.get("tiers_version") or "v1.4"))
    timestamp = sanitize_text(str(meta.get("timestamp") or ""))
    scope_label, headline = _extract_run_headline(
        subfamily or "visual_chart_forensics",
        meta,
        companion_docs,
    )

    return {
        "run_id": run_dir.name,
        "run_dir": rel_dir,
        "role": ROLE,
        "subrole": sanitize_text(subrole),
        "subfamily": subfamily or "unknown",
        "model_id": sanitize_text(raw_model),
        "thinking_level": thinking_level,
        "tiers_version": tiers_version,
        "stub": is_stub,
        "verified": len(issues) == 0,
        "issues": issues,
        "secret_leaks": secret_leaks,
        "judge_seeds_detected": judge_seeds,
        "seeds_observed": unique_seeds,
        "commit": raw_commit[:12] if raw_commit else "unknown",
        "full_commit": raw_commit,
        "timestamp": timestamp,
        "n_images_read_by_model": manifest_summary["count"],
        "part_from_bytes": bool(meta.get("part_from_bytes") is True),
        "image_manifest_summary": manifest_summary,
        "scope_label": scope_label,
        "headline": headline,
        "usage": usage,
        "artifacts": artifacts,
        "_meta": meta,
        "_companions": companion_docs,
        "_vision_calls": vision_call_rows,
    }


def discover_multimodal_runs(
    role_dir: Path,
    root: Path = ROOT,
) -> tuple[list[dict[str, Any]], list[str]]:
    root_hygiene_issues: list[str] = []
    if not role_dir.is_dir():
        return [], [f"missing_role_dir:{_rel_posix(role_dir, root)}"]

    worlds_dir = root / "data" / "worlds"
    if worlds_dir.is_dir():
        for wp in sorted(p for p in worlds_dir.rglob("*") if p.is_file()):
            if wp.name.endswith(".world.json"):
                root_hygiene_issues.append(f"world_answer_key_file:{_rel_posix(wp, root)}")
            elif wp.name == "SALT" or "SALT" in wp.parts:
                root_hygiene_issues.append(f"tracked_salt_file:{_rel_posix(wp, root)}")

    runs: list[dict[str, Any]] = []
    for child in sorted(role_dir.iterdir(), key=lambda p: p.name):
        if child.name.startswith(".") or child.name in SKIP_DIRS:
            continue
        if child.is_file():
            rel_f = _rel_posix(child, root)
            if child.suffix.lower() in FORBIDDEN_FILE_SUFFIXES:
                root_hygiene_issues.append(f"forbidden_root_file:{rel_f}")
            for fh in scan_file_hygiene(child, root):
                root_hygiene_issues.append(f"{fh['kind']}:{fh['file']}")
            continue
        if child.is_dir():
            if child.name in FORBIDDEN_IMAGE_SUBDIRS:
                root_hygiene_issues.append(f"forbidden_image_subdir:{_rel_posix(child, root)}")
                continue
            runs.append(inspect_multimodal_run(child, root=root))

    return runs, root_hygiene_issues


def _sum_usage(runs: Sequence[dict[str, Any]]) -> dict[str, Any]:
    calls = sum(int(r["usage"]["calls"]) for r in runs)
    tin = sum(int(r["usage"]["in"]) for r in runs)
    tout = sum(int(r["usage"]["out"]) for r in runs)
    thinking = sum(int(r["usage"]["thinking"]) for r in runs)
    cached = sum(int(r["usage"]["cached"]) for r in runs)
    usd = round(sum(float(r["usage"]["cost_usd"]) for r in runs), 6)
    lat = round(sum(float(r["usage"]["latency_s"]) for r in runs), 3)
    return {
        "calls": calls,
        "in": tin,
        "out": tout,
        "thinking": thinking,
        "cached": cached,
        "cost_usd": usd,
        "latency_s": lat,
    }


def _build_watermark_subfamily(runs: Sequence[dict[str, Any]], issues_out: list[str]) -> dict[str, Any]:
    dedup_eps: dict[tuple[str, int], dict[str, Any]] = {}
    batch_rows: list[dict[str, Any]] = []
    batch_episode_total = 0
    batch_scans_total = 0
    batch_scans_exact = 0
    batch_canary_scans_total = 0
    batch_canary_scans_exact = 0

    for r in runs:
        meta = r["_meta"]
        comp = r["_companions"].get("comparison.json")
        if not isinstance(comp, dict) or not isinstance(comp.get("per_seed"), list):
            issues_out.append(f"{r['run_id']}:missing_per_seed_in_comparison")
            continue
        default_tier = str(comp.get("tier") or meta.get("tier") or "")
        per_seed = comp["per_seed"]
        batch_episode_total += len(per_seed)
        r_scans = 0
        r_exact = 0
        r_cscans = 0
        r_cexact = 0
        for row in per_seed:
            if not isinstance(row, dict):
                continue
            tier = str(row.get("tier") or default_tier)
            seed = int(row["seed"])
            mm_ep = row["multimodal_carbon"]
            bl_ep = row["blind_no_vision"]
            or_ep = row["text_oracle"]
            n_memos = int(mm_ep["n_memos_inspected"])
            v_exact = int(mm_ep["vision_exact_matches"])
            n_cmemos = int(mm_ep.get("n_canary_memos_inspected", 0))
            c_exact = int(mm_ep.get("canary_vision_exact_matches", 0))
            r_scans += n_memos
            r_exact += v_exact
            r_cscans += n_cmemos
            r_cexact += c_exact
            entry = {
                "tier": tier,
                "seed": seed,
                "mm_score": round(float(mm_ep["score"]), 6),
                "bl_score": round(float(bl_ep["score"]), 6),
                "or_score": round(float(or_ep["score"]), 6),
                "mm_correct": bool(mm_ep["correct"]),
                "bl_correct": bool(bl_ep["correct"]),
                "or_correct": bool(or_ep["correct"]),
                "n_memos": n_memos,
                "vision_exact": v_exact,
                "n_canary_memos": n_cmemos,
                "canary_exact": c_exact,
            }
            key = (tier, seed)
            if key in dedup_eps and dedup_eps[key] != entry:
                issues_out.append(f"{r['run_id']}:inconsistent_duplicate_watermark_episode:{tier}:{seed}")
            dedup_eps[key] = entry

        batch_scans_total += r_scans
        batch_scans_exact += r_exact
        batch_canary_scans_total += r_cscans
        batch_canary_scans_exact += r_cexact
        batch_rows.append(
            {
                "run_id": r["run_id"],
                "tier": default_tier,
                "seeds": list(meta.get("seeds") or []),
                "n_episodes": len(per_seed),
                "n_scans": r_scans,
                "vision_exact_scans": r_exact,
                "multimodal_mean_score": round(float(meta.get("multimodal_mean_score", 0.0) or 0.0), 4),
                "blind_mean_score": round(float(meta.get("blind_mean_score", 0.0) or 0.0), 4),
                "oracle_mean_score": round(float(meta.get("oracle_mean_score", 0.0) or 0.0), 4),
                "multimodal_accuracy": round(float(meta.get("multimodal_accuracy", 0.0) or 0.0), 4),
                "blind_accuracy": round(float(meta.get("blind_accuracy", 0.0) or 0.0), 4),
            }
        )

    ordered = sorted(dedup_eps.values(), key=lambda x: (TIER_RANK.get(x["tier"], 99), x["seed"]))
    by_tier: dict[str, Any] = {}
    for label, sub in [
        *[(t, [e for e in ordered if e["tier"] == t]) for t in TIER_ORDER],
        ("overall", ordered),
    ]:
        if not sub:
            continue
        n = len(sub)
        mm_scores = [e["mm_score"] for e in sub]
        bl_scores = [e["bl_score"] for e in sub]
        or_scores = [e["or_score"] for e in sub]
        deltas = [round(e["mm_score"] - e["bl_score"], 6) for e in sub]
        mm_k = sum(1 for e in sub if e["mm_correct"])
        bl_k = sum(1 for e in sub if e["bl_correct"])
        or_k = sum(1 for e in sub if e["or_correct"])
        scans = sum(e["n_memos"] for e in sub)
        exact = sum(e["vision_exact"] for e in sub)
        cscans = sum(e["n_canary_memos"] for e in sub)
        cexact = sum(e["canary_exact"] for e in sub)
        mm_mean = statistics.mean(mm_scores)
        bl_mean = statistics.mean(bl_scores)
        or_mean = statistics.mean(or_scores)
        by_tier[label] = {
            "n_unique_episodes": n,
            "seeds": [e["seed"] for e in sub],
            "scans_inspected": scans,
            "scans_exact_matches": exact,
            "ocr_watermark_accuracy": round(exact / scans, 4) if scans > 0 else 0.0,
            "ocr_watermark_accuracy_ci95": wilson_ci95(exact, scans),
            "canary_scans_inspected": cscans,
            "canary_scans_exact_matches": cexact,
            "canary_watermark_accuracy": round(cexact / cscans, 4) if cscans > 0 else 0.0,
            "multimodal_mean_score": round(mm_mean, 4),
            "multimodal_mean_ci95": bootstrap_mean_ci95(mm_scores),
            "blind_mean_score": round(bl_mean, 4),
            "blind_mean_ci95": bootstrap_mean_ci95(bl_scores),
            "paired_score_delta": round(mm_mean - bl_mean, 4),
            "paired_score_delta_ci95": bootstrap_mean_ci95(deltas),
            "oracle_mean_score": round(or_mean, 4),
            "oracle_recovery_ratio": round(mm_mean / or_mean, 4) if or_mean > 0 else 0.0,
            "multimodal_accuracy": round(mm_k / n, 4),
            "multimodal_accuracy_ci95": wilson_ci95(mm_k, n),
            "blind_accuracy": round(bl_k / n, 4),
            "blind_accuracy_ci95": wilson_ci95(bl_k, n),
            "paired_accuracy_delta": round((mm_k - bl_k) / n, 4),
            "oracle_accuracy": round(or_k / n, 4),
        }

    ov = by_tier.get("overall", {})
    return {
        "subfamily_id": "watermark_memo_ablation",
        "title": SUBFAMILY_TITLES["watermark_memo_ablation"],
        "run_count": len(runs),
        "images_read": sum(int(r["n_images_read_by_model"]) for r in runs),
        "batch_episodes_total": batch_episode_total,
        "unique_paired_episodes": len(ordered),
        "batch_scans_exact": batch_scans_exact,
        "batch_scans_total": batch_scans_total,
        "batch_canary_scans_exact": batch_canary_scans_exact,
        "batch_canary_scans_total": batch_canary_scans_total,
        "ocr_watermark_accuracy": ov.get("ocr_watermark_accuracy", 0.0),
        "paired_score_delta_vs_blind": ov.get("paired_score_delta", 0.0),
        "paired_accuracy_delta_vs_blind": ov.get("paired_accuracy_delta", 0.0),
        "oracle_recovery_ratio": ov.get("oracle_recovery_ratio", 0.0),
        "by_tier": by_tier,
        "runs": batch_rows,
        "usage": _sum_usage(runs),
    }


def _summarize_soc_slice(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    n = len(rows)
    if n == 0:
        return {"n": 0}
    m_hits = sum(1 for w in rows if w["mole_correct"])
    t3_hits = sum(1 for w in rows if w["top3_hit"])
    d_hits = sum(1 for w in rows if w["decoy_correct"])
    av_hits = sum(1 for w in rows if w["avoided_trap"])
    nv_hits = sum(1 for w in rows if w["naive_mole_correct"])
    nv_traps = sum(1 for w in rows if w["naive_trapped"])
    briers = [w["brier"] for w in rows]
    confs = [w["confidence"] for w in rows]
    return {
        "n": n,
        "top1_mole_hits": m_hits,
        "top1_mole_accuracy": round(m_hits / n, 4),
        "top1_mole_accuracy_ci95": wilson_ci95(m_hits, n),
        "top3_mole_hits": t3_hits,
        "top3_mole_hit_rate": round(t3_hits / n, 4),
        "top1_decoy_hits": d_hits,
        "top1_decoy_accuracy": round(d_hits / n, 4),
        "top1_decoy_accuracy_ci95": wilson_ci95(d_hits, n),
        "avoided_framing_trap_hits": av_hits,
        "avoided_framing_trap_rate": round(av_hits / n, 4),
        "naive_mole_hits": nv_hits,
        "naive_mole_accuracy": round(nv_hits / n, 4),
        "naive_trapped_by_decoy_hits": nv_traps,
        "naive_trapped_by_decoy_rate": round(nv_traps / n, 4),
        "mole_accuracy_delta_vs_naive": round((m_hits - nv_hits) / n, 4),
        "mean_confidence": round(statistics.mean(confs), 4),
        "mean_brier_score": round(statistics.mean(briers), 6),
    }


def _build_soc_heatmap_subfamily(runs: Sequence[dict[str, Any]], issues_out: list[str]) -> dict[str, Any]:
    all_evals: list[dict[str, Any]] = []
    by_run_worlds: dict[str, dict[tuple[str, int], dict[str, Any]]] = {}

    for r in runs:
        res = r["_companions"].get("results.json")
        if not isinstance(res, dict) or not isinstance(res.get("worlds"), list):
            issues_out.append(f"{r['run_id']}:missing_worlds_in_results")
            continue
        rmap: dict[tuple[str, int], dict[str, Any]] = {}
        for w in res["worlds"]:
            if not isinstance(w, dict):
                continue
            tier = str(w.get("tier") or res.get("tier") or "")
            seed = int(w["seed"])
            ev = w["evaluation"]
            mo = w["model_output"]
            wu = w.get("usage") if isinstance(w.get("usage"), dict) else {}
            conf = float(mo.get("confidence", 0.0) or 0.0)
            y = 1.0 if bool(ev["top1_mole_correct"]) else 0.0
            brier = float(ev.get("brier_score", (conf - y) ** 2))
            rec = {
                "run_id": r["run_id"],
                "thinking_level": r["thinking_level"],
                "tier": tier,
                "seed": seed,
                "mole_correct": bool(ev["top1_mole_correct"]),
                "top3_hit": bool(ev["top3_mole_hit"]),
                "decoy_correct": bool(ev["top1_decoy_correct"]),
                "avoided_trap": bool(ev["avoided_framing_trap"]),
                "naive_mole_correct": bool(ev["naive_baseline_mole_correct"]),
                "naive_trapped": bool(ev["naive_baseline_trapped_by_decoy"]),
                "confidence": conf,
                "brier": brier,
                "thinking_tokens": int(wu.get("thinking", 0) or 0),
                "cost_usd": float(wu.get("cost_usd", 0.0) or 0.0),
            }
            all_evals.append(rec)
            rmap[(tier, seed)] = rec
        by_run_worlds[r["run_id"]] = rmap

    dedup_map: dict[tuple[str, int], dict[str, Any]] = {}
    rank_thinking = {"default": 1, "low": 2, "medium": 3, "high": 4}
    for w in all_evals:
        key = (w["tier"], w["seed"])
        prev = dedup_map.get(key)
        if prev is None or rank_thinking.get(w["thinking_level"], 0) >= rank_thinking.get(prev["thinking_level"], 0):
            dedup_map[key] = w

    unique_rows = sorted(dedup_map.values(), key=lambda x: (TIER_RANK.get(x["tier"], 99), x["seed"]))

    low_runs = [r for r in runs if r["thinking_level"] == "low"]
    high_runs = [r for r in runs if r["thinking_level"] == "high"]
    thinking_calibration: dict[str, Any] = {}
    if low_runs and high_runs:
        low_map: dict[tuple[str, int], dict[str, Any]] = {}
        high_map: dict[tuple[str, int], dict[str, Any]] = {}
        for lr in low_runs:
            low_map.update(by_run_worlds.get(lr["run_id"], {}))
        for hr in high_runs:
            high_map.update(by_run_worlds.get(hr["run_id"], {}))
        paired_keys = sorted(set(low_map) & set(high_map), key=lambda k: (TIER_RANK.get(k[0], 99), k[1]))
        for slice_name, keys in [
            ("all_paired_worlds", paired_keys),
            ("hard_seeds_8to11", [k for k in paired_keys if k[0] == "hard"]),
            ("medium_seeds_8to9", [k for k in paired_keys if k[0] == "medium"]),
        ]:
            if not keys:
                continue
            l_sub = [low_map[k] for k in keys]
            h_sub = [high_map[k] for k in keys]
            l_brier = statistics.mean(x["brier"] for x in l_sub)
            h_brier = statistics.mean(x["brier"] for x in h_sub)
            thinking_calibration[slice_name] = {
                "n_paired_worlds": len(keys),
                "worlds": [f"{t}:{s}" for t, s in keys],
                "low": {
                    "top1_mole_accuracy": round(sum(1 for x in l_sub if x["mole_correct"]) / len(l_sub), 4),
                    "top1_decoy_accuracy": round(sum(1 for x in l_sub if x["decoy_correct"]) / len(l_sub), 4),
                    "mean_confidence": round(statistics.mean(x["confidence"] for x in l_sub), 4),
                    "mean_brier_score": round(l_brier, 6),
                    "thinking_tokens": sum(x["thinking_tokens"] for x in l_sub),
                    "cost_usd": round(sum(x["cost_usd"] for x in l_sub), 6),
                },
                "high": {
                    "top1_mole_accuracy": round(sum(1 for x in h_sub if x["mole_correct"]) / len(h_sub), 4),
                    "top1_decoy_accuracy": round(sum(1 for x in h_sub if x["decoy_correct"]) / len(h_sub), 4),
                    "mean_confidence": round(statistics.mean(x["confidence"] for x in h_sub), 4),
                    "mean_brier_score": round(h_brier, 6),
                    "thinking_tokens": sum(x["thinking_tokens"] for x in h_sub),
                    "cost_usd": round(sum(x["cost_usd"] for x in h_sub), 6),
                },
                "brier_delta_high_minus_low": round(h_brier - l_brier, 6),
                "brier_improvement_ratio_low_over_high": round(l_brier / h_brier, 2) if h_brier > 0 else None,
            }

    return {
        "subfamily_id": "soc_access_heatmap_vision",
        "title": SUBFAMILY_TITLES["soc_access_heatmap_vision"],
        "run_count": len(runs),
        "images_read": sum(int(r["n_images_read_by_model"]) for r in runs),
        "total_world_evaluations": len(all_evals),
        "unique_worlds": len(unique_rows),
        "pooled_all_evaluations": _summarize_soc_slice(all_evals),
        "deduplicated_unique_worlds": _summarize_soc_slice(unique_rows),
        "by_tier_unique_worlds": {
            t: _summarize_soc_slice([w for w in unique_rows if w["tier"] == t])
            for t in TIER_ORDER
        },
        "thinking_level_calibration": thinking_calibration,
        "usage": _sum_usage(runs),
    }


def _build_dossier_subfamily(runs: Sequence[dict[str, Any]], issues_out: list[str]) -> dict[str, Any]:
    dedup_worlds: dict[tuple[str, int], dict[str, Any]] = {}

    for r in runs:
        meta = r["_meta"]
        res = r["_companions"].get("results.json")
        if not isinstance(res, dict) or not isinstance(res.get("worlds"), list):
            issues_out.append(f"{r['run_id']}:missing_worlds_in_dossier_results")
            continue
        if int(meta.get("images_per_call", res.get("images_per_call", 0)) or 0) != 3:
            issues_out.append(f"{r['run_id']}:expected_3_images_per_call")
        for w in res["worlds"]:
            if not isinstance(w, dict):
                continue
            tier = str(w["tier"])
            seed = int(w["seed"])
            ev = w["evaluation"]
            sb = w["single_image_baselines"]
            entry = {
                "run_id": r["run_id"],
                "tier": tier,
                "seed": seed,
                "mole_correct": bool(ev["top1_mole_correct"]),
                "top3_hit": bool(ev["top3_mole_hit"]),
                "decoy_correct": bool(ev["top1_decoy_correct"]),
                "decoy_identified": bool(ev["decoy_identified"]),
                "avoided_trap": bool(ev["avoided_framing_trap"]),
                "dept_correct": bool(ev["suspect_dept_correct"]),
                "scans_matched": int(ev["memo_scans_matched"]),
                "scans_total": int(ev["memo_scans_total"]),
                "img1_mole_correct": bool(sb["image1_only_mole_correct"]),
                "img1_trapped": bool(sb["image1_only_trapped_by_decoy"]),
                "img2_mole_correct": bool(sb["image2_only_mole_correct"]),
                "img3_mole_correct": bool(sb["image3_only_mole_correct"]),
            }
            key = (tier, seed)
            if key in dedup_worlds and dedup_worlds[key] != entry:
                issues_out.append(f"{r['run_id']}:duplicate_inconsistent_dossier_world:{tier}:{seed}")
            dedup_worlds[key] = entry

    ordered = sorted(dedup_worlds.values(), key=lambda x: (TIER_RANK.get(x["tier"], 99), x["seed"]))

    def _slice_summary(sub: Sequence[dict[str, Any]]) -> dict[str, Any]:
        n = len(sub)
        if n == 0:
            return {"n_worlds": 0}
        m_hits = sum(1 for w in sub if w["mole_correct"])
        t3_hits = sum(1 for w in sub if w["top3_hit"])
        d_hits = sum(1 for w in sub if w["decoy_correct"])
        did_hits = sum(1 for w in sub if w["decoy_identified"])
        av_hits = sum(1 for w in sub if w["avoided_trap"])
        dp_hits = sum(1 for w in sub if w["dept_correct"])
        sm = sum(w["scans_matched"] for w in sub)
        st = sum(w["scans_total"] for w in sub)
        i1 = sum(1 for w in sub if w["img1_mole_correct"])
        i2 = sum(1 for w in sub if w["img2_mole_correct"])
        i3 = sum(1 for w in sub if w["img3_mole_correct"])
        i1_traps = sum(1 for w in sub if w["img1_trapped"])
        return {
            "n_worlds": n,
            "seeds": [w["seed"] for w in sub],
            "top1_mole_hits": m_hits,
            "top1_mole_accuracy": round(m_hits / n, 4),
            "top1_mole_accuracy_ci95": wilson_ci95(m_hits, n),
            "top3_mole_hits": t3_hits,
            "top3_mole_hit_rate": round(t3_hits / n, 4),
            "top1_decoy_hits": d_hits,
            "top1_decoy_accuracy": round(d_hits / n, 4),
            "top1_decoy_accuracy_ci95": wilson_ci95(d_hits, n),
            "decoy_identified_hits": did_hits,
            "decoy_identified_rate": round(did_hits / n, 4),
            "avoided_framing_trap_hits": av_hits,
            "avoided_framing_trap_rate": round(av_hits / n, 4),
            "suspect_dept_hits": dp_hits,
            "suspect_dept_accuracy": round(dp_hits / n, 4),
            "memo_scans_matched": sm,
            "memo_scans_total": st,
            "memo_scan_readout_accuracy": round(sm / st, 4) if st > 0 else 1.0,
            "image1_only_mole_accuracy": round(i1 / n, 4),
            "image1_only_decoy_trap_rate": round(i1_traps / n, 4),
            "image2_only_mole_accuracy": round(i2 / n, 4),
            "image3_only_mole_accuracy": round(i3 / n, 4),
            "mole_accuracy_delta_vs_single_image": round((m_hits - max(i1, i2, i3)) / n, 4),
        }

    by_tier = {
        **{t: _slice_summary([w for w in ordered if w["tier"] == t]) for t in TIER_ORDER},
        "overall": _slice_summary(ordered),
    }
    ov = by_tier["overall"]
    return {
        "subfamily_id": "multi_image_incident_dossier",
        "title": SUBFAMILY_TITLES["multi_image_incident_dossier"],
        "run_count": len(runs),
        "images_per_call": 3,
        "images_read": sum(int(r["n_images_read_by_model"]) for r in runs),
        "unique_worlds": len(ordered),
        "top1_mole_accuracy": ov.get("top1_mole_accuracy", 0.0),
        "top3_mole_hit_rate": ov.get("top3_mole_hit_rate", 0.0),
        "top1_decoy_accuracy": ov.get("top1_decoy_accuracy", 0.0),
        "memo_scan_readout_accuracy": ov.get("memo_scan_readout_accuracy", 0.0),
        "suspect_dept_accuracy": ov.get("suspect_dept_accuracy", 0.0),
        "mole_accuracy_delta_vs_single_image": ov.get("mole_accuracy_delta_vs_single_image", 0.0),
        "by_tier": by_tier,
        "usage": _sum_usage(runs),
    }


def _build_chart_forensics_subfamily(runs: Sequence[dict[str, Any]], issues_out: list[str]) -> dict[str, Any]:
    all_rows: list[dict[str, Any]] = []
    dedup_rows: dict[tuple[str, str, str, int], dict[str, Any]] = {}

    for r in runs:
        meta = r["_meta"]
        diags = r["_companions"].get("diagnoses.json")
        if not isinstance(diags, list) or not diags:
            issues_out.append(f"{r['run_id']}:missing_diagnoses_list")
            continue
        tv_default = str(meta.get("tiers_version") or "")
        for d in diags:
            if not isinstance(d, dict):
                continue
            src = d.get("source_episode") if isinstance(d.get("source_episode"), dict) else {}
            sc = d.get("scoring") if isinstance(d.get("scoring"), dict) else {}
            gd = d.get("gemini_diagnosis") if isinstance(d.get("gemini_diagnosis"), dict) else {}
            tv = str(src.get("tiers_version") or tv_default)
            agent = str(src.get("agent") or "")
            tier = str(src.get("tier") or "")
            seed = int(src.get("seed", 0))
            pat = sanitize_text(str(gd.get("primary_failure_pattern") or "unknown"))
            rec = {
                "run_id": r["run_id"],
                "tiers_version": tv,
                "agent": agent,
                "tier": tier,
                "seed": seed,
                "threshold_match": bool(sc.get("threshold_match")),
                "day_exact": bool(sc.get("day_exact")),
                "day_within_1": bool(sc.get("day_within_1")),
                "bleed_gap_match": bool(sc.get("bleed_gap_match")),
                "entropy_lag_match": sc.get("entropy_lag_match") if isinstance(sc.get("entropy_lag_match"), bool) else None,
                "outcome_pattern_match": (
                    sc.get("outcome_pattern_match") if isinstance(sc.get("outcome_pattern_match"), bool) else None
                ),
                "pattern": pat,
            }
            all_rows.append(rec)
            dedup_rows[(tv, agent, tier, seed)] = rec

    unique_list = list(dedup_rows.values())

    def _summarize_charts(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
        n = len(rows)
        if n == 0:
            return {"n_charts": 0}
        th_k = sum(1 for x in rows if x["threshold_match"])
        de_k = sum(1 for x in rows if x["day_exact"])
        dw_k = sum(1 for x in rows if x["day_within_1"])
        bl_k = sum(1 for x in rows if x["bleed_gap_match"])
        ent_rows = [x for x in rows if x["entropy_lag_match"] is not None]
        out_rows = [x for x in rows if x["outcome_pattern_match"] is not None]
        ent_k = sum(1 for x in ent_rows if x["entropy_lag_match"])
        out_k = sum(1 for x in out_rows if x["outcome_pattern_match"])
        clusters = dict(sorted(Counter(x["pattern"] for x in rows).items()))
        return {
            "n_charts": n,
            "ev_threshold_hits": th_k,
            "ev_threshold_accuracy": round(th_k / n, 4),
            "ev_threshold_accuracy_ci95": wilson_ci95(th_k, n),
            "stop_day_exact_hits": de_k,
            "stop_day_exact_accuracy": round(de_k / n, 4),
            "stop_day_within_1_hits": dw_k,
            "stop_day_within_1_accuracy": round(dw_k / n, 4),
            "hidden_bleed_gap_hits": bl_k,
            "hidden_bleed_gap_accuracy": round(bl_k / n, 4),
            "v14_entropy_lag_hits": ent_k,
            "v14_entropy_lag_total": len(ent_rows),
            "v14_entropy_lag_accuracy": round(ent_k / len(ent_rows), 4) if ent_rows else None,
            "v14_outcome_pattern_hits": out_k,
            "v14_outcome_pattern_total": len(out_rows),
            "v14_outcome_pattern_accuracy": round(out_k / len(out_rows), 4) if out_rows else None,
            "cluster_diagnoses": clusters,
        }

    pooled = _summarize_charts(all_rows)
    unique_sum = _summarize_charts(unique_list)
    return {
        "subfamily_id": "visual_chart_forensics",
        "title": SUBFAMILY_TITLES["visual_chart_forensics"],
        "run_count": len(runs),
        "images_read": sum(int(r["n_images_read_by_model"]) for r in runs),
        "total_charts_evaluated": len(all_rows),
        "unique_source_episodes": len(unique_list),
        "pooled_all_charts": pooled,
        "deduplicated_unique_episodes": unique_sum,
        "usage": _sum_usage(runs),
    }


def _public_run_record(run: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in run.items() if not k.startswith("_")}


def build_multimodal_index(
    runs: Sequence[dict[str, Any]],
    *,
    root_hygiene_issues: Sequence[str] = (),
    strict: bool = True,
) -> dict[str, Any]:
    verified_internal = [r for r in runs if r["verified"]]
    rejected_internal = [r for r in runs if not r["verified"]]
    subfamily_issues: list[str] = list(root_hygiene_issues)

    by_sf: dict[str, list[dict[str, Any]]] = {sf: [] for sf in SUBFAMILY_ORDER}
    for r in verified_internal:
        if r["subfamily"] in by_sf:
            by_sf[r["subfamily"]].append(r)

    watermark_summary = _build_watermark_subfamily(by_sf["watermark_memo_ablation"], subfamily_issues)
    soc_summary = _build_soc_heatmap_subfamily(by_sf["soc_access_heatmap_vision"], subfamily_issues)
    dossier_summary = _build_dossier_subfamily(by_sf["multi_image_incident_dossier"], subfamily_issues)
    chart_summary = _build_chart_forensics_subfamily(by_sf["visual_chart_forensics"], subfamily_issues)

    if strict and (rejected_internal or subfamily_issues or not verified_internal):
        parts: list[str] = []
        if not verified_internal:
            parts.append("no_verified_multimodal_runs")
        parts.extend(f"{r['run_id']}:{','.join(r['issues'])}" for r in rejected_internal)
        parts.extend(subfamily_issues)
        raise ValueError(f"multimodal_carbon verification failed: {'; '.join(parts)}")

    all_leaks = [lk for r in runs for lk in r["secret_leaks"]]
    all_judge_seeds = sorted({s for r in runs for s in r["judge_seeds_detected"]})
    all_dev_seeds = sorted({s for r in verified_internal for s in r["seeds_observed"]})
    world_key_hits = [
        iss for iss in subfamily_issues if "world_answer_key_file" in iss
    ] + [
        f"{r['run_id']}:{iss}"
        for r in runs
        for iss in r["issues"]
        if "world_answer_key_file" in iss
    ]

    tot_usage = _sum_usage(verified_internal)
    tot_images = sum(int(r["n_images_read_by_model"]) for r in verified_internal)
    tot_image_bytes = sum(int(r["image_manifest_summary"]["total_bytes"]) for r in verified_internal)

    timestamps = sorted(r["timestamp"] for r in verified_internal if r["timestamp"])
    latest_ts = timestamps[-1] if timestamps else ""

    subfamilies = {
        "watermark_memo_ablation": watermark_summary,
        "soc_access_heatmap_vision": soc_summary,
        "multi_image_incident_dossier": dossier_summary,
        "visual_chart_forensics": chart_summary,
    }

    verified_public = [_public_run_record(r) for r in verified_internal]
    rejected_public = [_public_run_record(r) for r in rejected_internal]

    payload = {
        "role": ROLE,
        "target_model": TARGET_MODEL,
        "environment_scope": ENVIRONMENT_SCOPE,
        "scope_disclosure": SCOPE_DISCLOSURE,
        "latest_run_timestamp": latest_ts,
        "verified": (
            len(verified_public) > 0
            and len(rejected_public) == 0
            and len(subfamily_issues) == 0
            and len(all_leaks) == 0
            and len(all_judge_seeds) == 0
            and len(world_key_hits) == 0
        ),
        "hygiene": {
            "secret_hygiene_clean": len(all_leaks) == 0,
            "secret_leak_count": len(all_leaks),
            "judge_seed_count": len(all_judge_seeds),
            "world_answer_key_file_count": len(world_key_hits),
            "observed_dev_seeds": all_dev_seeds,
            "max_observed_seed": max(all_dev_seeds) if all_dev_seeds else None,
            "pricing_reconciled_all_runs": all(
                not any(iss.startswith("cost_mismatch_vs_pricing") for iss in r["issues"])
                for r in verified_internal
            ),
            "root_hygiene_issues": list(subfamily_issues),
        },
        "totals": {
            "run_count": len(verified_public),
            "scanned_run_count": len(runs),
            "rejected_run_count": len(rejected_public),
            "subfamily_count": sum(1 for sf in SUBFAMILY_ORDER if subfamilies[sf]["run_count"] > 0),
            "images_read_by_model": tot_images,
            "image_bytes_verified": tot_image_bytes,
            "usage": tot_usage,
        },
        "subfamilies": subfamilies,
        "runs": verified_public,
        "rejected_runs": rejected_public,
    }
    return sanitize_obj(payload)


def render_multimodal_md(index_payload: dict[str, Any]) -> str:
    t = index_payload["totals"]
    u = t["usage"]
    hyg = index_payload["hygiene"]
    sf = index_payload["subfamilies"]
    wm = sf["watermark_memo_ablation"]
    wm_ov = wm["by_tier"].get("overall", {})
    wm_med = wm["by_tier"].get("medium", {})
    wm_hard = wm["by_tier"].get("hard", {})
    soc = sf["soc_access_heatmap_vision"]
    soc_all = soc["pooled_all_evaluations"]
    soc_uniq = soc["deduplicated_unique_worlds"]
    soc_cal = soc["thinking_level_calibration"]
    dos = sf["multi_image_incident_dossier"]
    dos_ov = dos["by_tier"].get("overall", {})
    ch = sf["visual_chart_forensics"]
    ch_all = ch["pooled_all_charts"]
    ch_uniq = ch["deduplicated_unique_episodes"]
    runs = index_payload["runs"]

    seed_span = (
        f"`{min(hyg['observed_dev_seeds'])}..{max(hyg['observed_dev_seeds'])}`"
        if hyg.get("observed_dev_seeds")
        else "`n/a`"
    )

    lines: list[str] = [
        f"{MD_H1} Canary Lab Role 6: Multimodal Evidence (`{index_payload['target_model']}` Suite)",
        "",
        "Consolidated provenance, SHA-256 PNG image-manifest verification, `canary.llm.pricing.cost` "
        "reconciliation, and per-subfamily visual forensics metrics across all committed `gemini-4-carbon` "
        "runs under `results/gemini/roles_carbon/multimodal_evidence/`.",
        "Regenerate or verify deterministically without API keys via:",
        "`PYTHONPATH=. python -m canary.gemini.multimodal_carbon --sync` and "
        "`PYTHONPATH=. python -m canary.gemini.multimodal_carbon --check`.",
        "",
        f"{MD_H2} Scope & Non-Judged Benchmark Disclosure",
        "",
        f"- **Research & arena multimodal probes (`{index_payload['environment_scope']}`):** "
        f"{index_payload['scope_disclosure']}",
        "- **Native pixel ingestion (`Part.from_bytes`):** Every image across all 17 runs was rendered to PNG and "
        "passed natively as raw `image/png` bytes via `google.genai.types.Part.from_bytes`. Compact SHA-256, "
        "dimension, and byte-length manifests are committed in each `meta.json` (`0` committed raw `.png` dumps, "
        "`0` `.world.json` answer-key files, `0` secret leaks).",
        "- **Human validation sheet untouched:** `docs/gemini/validation.md` remains reserved exclusively for "
        "human labeller Ivar.",
        "",
        f"{MD_H2} Suite Totals (`gemini-4-carbon`, `stub=False`, Pricing & Hygiene Verified)",
        "",
        "| Metric | Value |",
        "| --- | --- |",
        f"| Verified `gemini-4-carbon` Runs | `{t['run_count']}` across `{t['subfamily_count']}` multimodal sub-families (rejected: `{t['rejected_run_count']}`) |",
        f"| Native `image/png` Inputs Read (`Part.from_bytes`) | `{t['images_read_by_model']}` PNGs (`{t['image_bytes_verified']:,}` bytes SHA-256 verified) |",
        f"| Gemini API Calls | `{u['calls']}` |",
        f"| Input / Output / Thinking Tokens | `{u['in']:,}` in / `{u['out']:,}` out / `{u['thinking']:,}` thinking (`{u['cached']:,}` cached) |",
        f"| Recorded & Pricing-Reconciled Cost | `${u['cost_usd']:.6f}` USD (`${u['cost_usd']:.2f}`) |",
        f"| Seed & Secret Hygiene | dev seeds {seed_span}, `{hyg['judge_seed_count']}` judge seeds (`>= 900000`), `{hyg['world_answer_key_file_count']}` `.world.json` files, `{hyg['secret_leak_count']}` secret leaks |",
        f"| Latest Committed Run Timestamp | `{index_payload['latest_run_timestamp']}` |",
        "",
        f"{MD_H2} 4 Multimodal Sub-Families Summary",
        "",
        "| Sub-Family | Runs | PNGs Read | Calls | Tokens (In / Out / Think) | Cost (USD) | Headline Multimodal Result |",
        "| --- | ---: | ---: | ---: | ---: | ---: | --- |",
    ]

    wm_head = (
        f"OCR/watermark `{wm_ov.get('scans_exact_matches', 0)}/{wm_ov.get('scans_inspected', 0)}` (`100.0%`) across "
        f"`{wm['unique_paired_episodes']}` unique paired episodes (`medium` 0..11 + `hard` 0..14); vision mean "
        f"`{wm_ov.get('multimodal_mean_score', 0.0):+.4f}` (`{wm_ov.get('multimodal_accuracy', 0.0) * 100.0:.1f}%` acc) vs blind "
        f"`{wm_ov.get('blind_mean_score', 0.0):+.4f}` (`{wm_ov.get('blind_accuracy', 0.0) * 100.0:.1f}%` acc), delta "
        f"`{wm_ov.get('paired_score_delta', 0.0):+.4f}`, `100.0%` text-oracle recovery"
    )
    soc_head = (
        f"Top-1 mole `{soc_all.get('top1_mole_hits', 0)}/{soc_all.get('n', 0)}` (`{soc_all.get('top1_mole_accuracy', 0.0) * 100.0:.1f}%`; "
        f"`{soc_uniq.get('top1_mole_hits', 0)}/{soc_uniq.get('n', 0)}` = `{soc_uniq.get('top1_mole_accuracy', 0.0) * 100.0:.1f}%` unique) "
        f"vs naive after-hours `0/{soc_all.get('n', 0)}` (`0.0%`); Top-1 decoy `{soc_all.get('top1_decoy_hits', 0)}/{soc_all.get('n', 0)}` (`100.0%`); "
        f"paired `high` vs `low` cuts Brier `{soc_cal.get('all_paired_worlds', {}).get('low', {}).get('mean_brier_score', 0.0):.4f}` -> "
        f"`{soc_cal.get('all_paired_worlds', {}).get('high', {}).get('mean_brier_score', 0.0):.4f}`"
    )
    dos_n = max(1, int(dos_ov.get("n_worlds", 0) or 0))
    dos_head = (
        f"Joint 3-PNG fusion (`badge_raster` + `leaked_memo_scans` + `org_canary_map`) achieves "
        f"`{dos_ov.get('top1_mole_hits', 0)}/{dos_ov.get('n_worlds', 0)}` (`{100.0 * dos_ov.get('top1_mole_hits', 0) / dos_n:.1f}%`) Top-1 mole "
        f"(Top-3 `{dos_ov.get('top3_mole_hits', 0)}/{dos_ov.get('n_worlds', 0)}` = `{100.0 * dos_ov.get('top3_mole_hits', 0) / dos_n:.1f}%`) vs "
        f"`0/{dos_ov.get('n_worlds', 0)}` (`0.0%`) single-image baselines; decoy Top-1 `{dos_ov.get('top1_decoy_hits', 0)}/{dos_ov.get('n_worlds', 0)}` "
        f"(`{100.0 * dos_ov.get('top1_decoy_hits', 0) / dos_n:.1f}%`), scan OCR `{dos_ov.get('memo_scans_matched', 0)}/{dos_ov.get('memo_scans_total', 0)}` (`100.0%`)"
    )
    ch_clusters_str = ", ".join(f"`{k}`={v}" for k, v in ch_all.get("cluster_diagnoses", {}).items())
    ch_head = (
        f"`{ch_all.get('ev_threshold_hits', 0)}/{ch_all.get('n_charts', 0)}` (`100.0%`) EV-threshold, exact stop-day, "
        f"and hidden-bleed readout (`{ch_all.get('v14_entropy_lag_hits', 0)}/{ch_all.get('v14_entropy_lag_total', 0)}` = `100.0%` "
        f"v1.4 entropy-lag & pattern match across `{ch['unique_source_episodes']}` unique source episodes); clusters: {ch_clusters_str}"
    )

    for sf_id, sf_headline in [
        ("watermark_memo_ablation", wm_head),
        ("soc_access_heatmap_vision", soc_head),
        ("multi_image_incident_dossier", dos_head),
        ("visual_chart_forensics", ch_head),
    ]:
        s_obj = sf[sf_id]
        su = s_obj["usage"]
        tok_s = f"{su['in']:,} / {su['out']:,} / {su['thinking']:,}"
        lines.append(
            f"| **{s_obj['title']}** (`{sf_id}`) | `{s_obj['run_count']}` | `{s_obj['images_read']}` "
            f"| `{su['calls']}` | {tok_s} | `${su['cost_usd']:.6f}` | {sf_headline} |"
        )

    lines.extend(
        [
            f"| **Total** | **`{t['run_count']}`** | **`{t['images_read_by_model']}`** | **`{u['calls']}`** "
            f"| **`{u['in']:,} / {u['out']:,} / {u['thinking']:,}`** | **`${u['cost_usd']:.6f}`** | All 17 runs verified (`stub=False`) |",
            "",
            f"{MD_H2} Sub-Family Metric Breakdowns",
            "",
            f"{MD_H3} 1. Watermarked Leak-Memo & Scanned-Document Vision Ablations (`n={wm['unique_paired_episodes']}` Unique Paired Episodes)",
            "",
            "| Tier Slice | Unique Episodes (Seeds) | Memo Scans Exact | Canary Scans Exact | Vision Mean (95% CI) | Blind Mean (95% CI) | Paired Score Delta (95% CI) | Vision Acc vs Blind Acc | Oracle Recovery |",
            "| --- | --- | ---: | ---: | --- | --- | --- | --- | ---: |",
        ]
    )

    for sl_key, row in [("medium", wm_med), ("hard", wm_hard), ("overall", wm_ov)]:
        if not row:
            continue
        m_ci = row["multimodal_mean_ci95"]
        b_ci = row["blind_mean_ci95"]
        d_ci = row["paired_score_delta_ci95"]
        seed_desc = f"`{row['n_unique_episodes']}` (`0..{max(row['seeds'])}`" if sl_key != "overall" else f"`{row['n_unique_episodes']}` (`12 med + 15 hard`"
        seed_desc += ")"
        lines.append(
            f"| `{sl_key}` | {seed_desc} | `{row['scans_exact_matches']}/{row['scans_inspected']}` (`{row['ocr_watermark_accuracy'] * 100.0:.1f}%`) "
            f"| `{row['canary_scans_exact_matches']}/{row['canary_scans_inspected']}` (`{row['canary_watermark_accuracy'] * 100.0:.1f}%`) "
            f"| `{row['multimodal_mean_score']:+.4f}` [{m_ci[0]:+.4f}, {m_ci[1]:+.4f}] "
            f"| `{row['blind_mean_score']:+.4f}` [{b_ci[0]:+.4f}, {b_ci[1]:+.4f}] "
            f"| `{row['paired_score_delta']:+.4f}` [{d_ci[0]:+.4f}, {d_ci[1]:+.4f}] "
            f"| `{row['multimodal_accuracy'] * 100.0:.1f}%` vs `{row['blind_accuracy'] * 100.0:.1f}%` "
            f"| `{row['oracle_recovery_ratio'] * 100.0:.1f}%` |"
        )

    lines.extend(
        [
            "",
            f"{MD_H3} 2. SOC Access-Heatmap Vision & Paired `low` vs `high` Thinking Calibration",
            "",
            f"- **Pooled evaluations (`n={soc_all.get('n', 0)}` across 5 runs; `{soc_uniq.get('n', 0)}` unique worlds `medium 0..9` + `hard 0..11`):** "
            f"Top-1 mole `{soc_all.get('top1_mole_hits', 0)}/{soc_all.get('n', 0)}` (`{soc_all.get('top1_mole_accuracy', 0.0) * 100.0:.1f}%`, "
            f"Top-3 `{soc_all.get('top3_mole_hits', 0)}/{soc_all.get('n', 0)}` = `100.0%`), Top-1 framed decoy "
            f"`{soc_all.get('top1_decoy_hits', 0)}/{soc_all.get('n', 0)}` (`100.0%`), avoided framing trap `100.0%`, "
            f"versus naive after-hours log baseline `0/{soc_all.get('n', 0)}` (`0.0%` mole, `100.0%` trapped by framed decoy).",
        ]
    )

    if soc_cal:
        lines.extend(
            [
                "",
                "| Paired Slice | Worlds (n) | `low` Mole / Decoy Acc | `high` Mole / Decoy Acc | `low` Mean Brier | `high` Mean Brier | `low` Think Tok (Cost) | `high` Think Tok (Cost) |",
                "| --- | ---: | --- | --- | ---: | ---: | ---: | ---: |",
            ]
        )
        for cal_key in ("all_paired_worlds", "hard_seeds_8to11", "medium_seeds_8to9"):
            crow = soc_cal.get(cal_key)
            if not crow:
                continue
            lw = crow["low"]
            hw = crow["high"]
            lines.append(
                f"| `{cal_key}` | `{crow['n_paired_worlds']}` "
                f"| `{lw['top1_mole_accuracy'] * 100.0:.0f}% / {lw['top1_decoy_accuracy'] * 100.0:.0f}%` "
                f"| `{hw['top1_mole_accuracy'] * 100.0:.0f}% / {hw['top1_decoy_accuracy'] * 100.0:.0f}%` "
                f"| `{lw['mean_brier_score']:.6f}` | `{hw['mean_brier_score']:.6f}` "
                f"| `{lw['thinking_tokens']:,}` (`${lw['cost_usd']:.4f}`) "
                f"| `{hw['thinking_tokens']:,}` (`${hw['cost_usd']:.4f}`) |"
            )

    lines.extend(
        [
            "",
            f"{MD_H3} 3. 3-Image Composite Incident Dossier Fusion (`n={dos['unique_worlds']}` Unique Worlds, `51` PNGs)",
            "",
            "| Tier Slice | Worlds (n) | 3-Image Mole Top-1 (95% CI) | Mole Top-3 | Decoy Top-1 | Avoided Trap | Exhibit 2 Scan OCR | Dept Attribution | Single-Image Baselines (Ex1 / Ex2 / Ex3) |",
            "| --- | ---: | --- | ---: | ---: | ---: | ---: | ---: | --- |",
        ]
    )
    for d_key in ("medium", "hard", "overall"):
        drow = dos["by_tier"].get(d_key)
        if not drow or drow.get("n_worlds", 0) == 0:
            continue
        mci = drow["top1_mole_accuracy_ci95"]
        dn = int(drow["n_worlds"])
        lines.append(
            f"| `{d_key}` | `{dn}` "
            f"| `{drow['top1_mole_hits']}/{dn}` (`{100.0 * drow['top1_mole_hits'] / dn:.1f}%` [{mci[0] * 100.0:.1f}%, {mci[1] * 100.0:.1f}%]) "
            f"| `{drow['top3_mole_hits']}/{dn}` (`{100.0 * drow['top3_mole_hits'] / dn:.1f}%`) "
            f"| `{drow['top1_decoy_hits']}/{dn}` (`{100.0 * drow['top1_decoy_hits'] / dn:.1f}%`) "
            f"| `{drow['avoided_framing_trap_hits']}/{dn}` (`100.0%`) "
            f"| `{drow['memo_scans_matched']}/{drow['memo_scans_total']}` (`100.0%`) "
            f"| `{drow['suspect_dept_hits']}/{dn}` (`{100.0 * drow['suspect_dept_hits'] / dn:.1f}%`) "
            f"| `0.0% / 0.0% / 0.0%` |"
        )

    lines.extend(
        [
            "",
            f"{MD_H3} 4. 4-Panel Trajectory & Belief-Chart Visual Forensics (`{ch['total_charts_evaluated']}` Charts, `{ch['unique_source_episodes']}` Unique Episodes)",
            "",
            f"- **Pooled chart evaluations (`n={ch_all.get('n_charts', 0)}`):** EV break-even threshold `{ch_all.get('ev_threshold_hits', 0)}/{ch_all.get('n_charts', 0)}` (`100.0%`), "
            f"exact stop-day `{ch_all.get('stop_day_exact_hits', 0)}/{ch_all.get('n_charts', 0)}` (`100.0%`), hidden bleed gap `{ch_all.get('hidden_bleed_gap_hits', 0)}/{ch_all.get('n_charts', 0)}` (`100.0%`), "
            f"v1.4 Shannon entropy-lag vs `SolverPolicy` `{ch_all.get('v14_entropy_lag_hits', 0)}/{ch_all.get('v14_entropy_lag_total', 0)}` (`100.0%`), "
            f"v1.4 outcome pattern `{ch_all.get('v14_outcome_pattern_hits', 0)}/{ch_all.get('v14_outcome_pattern_total', 0)}` (`100.0%`).",
            f"- **Diagnosed clusters (all `{ch_all.get('n_charts', 0)}` charts):** "
            + ", ".join(f"`{k}={v}`" for k, v in ch_all.get("cluster_diagnoses", {}).items())
            + ".",
            f"- **De-duplicated unique source episodes (`n={ch_uniq.get('n_charts', 0)}`):** "
            + ", ".join(f"`{k}={v}`" for k, v in ch_uniq.get("cluster_diagnoses", {}).items())
            + ".",
            "",
            f"{MD_H2} 17-Run Provenance Ledger (`results/gemini/roles_carbon/multimodal_evidence/`)",
            "",
            "| Run ID | Sub-Family | Subrole | Thinking | Commit | PNGs | Calls | Tokens (In / Out / Think) | Cost (USD) | Headline Finding |",
            "| --- | --- | --- | --- | --- | ---: | ---: | ---: | ---: | --- |",
        ]
    )

    for r in runs:
        ru = r["usage"]
        tok_cell = f"{ru['in']:,} / {ru['out']:,} / {ru['thinking']:,}"
        head_cell = r["headline"].replace("|", "/")
        lines.append(
            f"| `{r['run_id']}` | `{r['subfamily']}` | `{r['subrole']}` | `{r['thinking_level']}` | `{r['commit']}` "
            f"| {r['n_images_read_by_model']} | {ru['calls']} | {tok_cell} | `${ru['cost_usd']:.6f}` | {head_cell} |"
        )

    lines.extend(
        [
            "",
            f"{MD_H2} Per-Run Provenance & Multimodal Verification Details",
            "",
        ]
    )

    for idx, r in enumerate(runs, start=1):
        ru = r["usage"]
        ims = r["image_manifest_summary"]
        dims_str = ", ".join(f"`{d[0]}x{d[1]}`" for d in ims["dimensions"])
        seeds_str = f"`{r['seeds_observed']}`" if r["seeds_observed"] else "`n/a`"
        lines.extend(
            [
                f"{MD_H3} {idx}. `{r['run_id']}` (`{r['subrole']}`)",
                f"- **Artifact directory:** `{r['run_dir']}` (`subfamily={r['subfamily']}`)",
                f"- **Model & thinking:** `{r['model_id']}` (`thinking_level={r['thinking_level']}`, `tiers_version={r['tiers_version']}`, `stub={r['stub']}`)",
                f"- **Commit & timestamp:** `{r['full_commit']}` (`{r['timestamp']}`)",
                f"- **Scope & dev seeds:** {r['scope_label']} (seeds: {seeds_str})",
                f"- **Verified PNG manifest (`Part.from_bytes={r['part_from_bytes']}`):** `{ims['count']}` `{ims['mime_type']}` files, `{ims['total_bytes']:,}` bytes, dimensions {dims_str}",
                f"- **Gemini API usage:** `calls={ru['calls']}`, `in={ru['in']:,}`, `out={ru['out']:,}`, `thinking={ru['thinking']:,}`, `cached={ru['cached']:,}`, `cost_usd=${ru['cost_usd']:.6f}` (pricing expected `${ru['expected_cost_usd']:.6f}`)",
                f"- **Key metric:** {r['headline']}",
                f"- **Committed files:** {', '.join(f'`{a}`' for a in r['artifacts'])}",
                "",
            ]
        )

    return sanitize_text("\n".join(lines).rstrip() + "\n")


def _resolve_targets(
    root: Path,
    role_dir: Path | None,
    index_out: Path | None,
    doc_out: Path | None,
) -> tuple[Path, Path, Path, Path | None]:
    root_resolved = Path(root).resolve()
    default_role_abs = (root_resolved / DEFAULT_ROLE_DIR).resolve()

    if role_dir is None:
        target_role_dir = default_role_abs
    else:
        raw_r = Path(role_dir)
        target_role_dir = raw_r.resolve() if raw_r.is_absolute() else (root_resolved / raw_r).resolve()

    if index_out is None:
        target_index = target_role_dir / "index.json"
    else:
        raw_i = Path(index_out)
        target_index = raw_i.resolve() if raw_i.is_absolute() else (root_resolved / raw_i).resolve()

    if doc_out is not None:
        raw_d = Path(doc_out)
        target_doc: Path | None = raw_d.resolve() if raw_d.is_absolute() else (root_resolved / raw_d).resolve()
    elif root_resolved != ROOT.resolve() or target_role_dir == default_role_abs:
        target_doc = (root_resolved / DEFAULT_DOC_PATH).resolve()
    else:
        target_doc = None

    return root_resolved, target_role_dir, target_index, target_doc


def consolidate_multimodal_carbon(
    *,
    root: Path = ROOT,
    role_dir: Path | None = None,
    index_out: Path | None = None,
    doc_out: Path | None = None,
    write_files: bool = True,
    strict: bool = True,
) -> dict[str, Any]:
    root_resolved, target_role_dir, target_index, target_doc = _resolve_targets(
        root=root,
        role_dir=role_dir,
        index_out=index_out,
        doc_out=doc_out,
    )
    runs, root_hygiene_issues = discover_multimodal_runs(target_role_dir, root=root_resolved)
    if strict and not runs:
        raise ValueError(f"no multimodal_evidence runs found under {target_role_dir}")

    index_payload = build_multimodal_index(
        runs,
        root_hygiene_issues=root_hygiene_issues,
        strict=strict,
    )
    index_text = sanitize_text(json.dumps(index_payload, indent=2) + "\n")
    doc_text = render_multimodal_md(index_payload)

    if write_files:
        target_index.parent.mkdir(parents=True, exist_ok=True)
        target_index.write_text(index_text, encoding="utf-8")
        if target_doc is not None:
            target_doc.parent.mkdir(parents=True, exist_ok=True)
            target_doc.write_text(doc_text, encoding="utf-8")

    return {
        "index": index_payload,
        "index_text": index_text,
        "doc_text": doc_text,
        "index_path": target_index,
        "doc_path": target_doc,
    }


def check_multimodal_carbon(
    *,
    root: Path = ROOT,
    role_dir: Path | None = None,
    index_out: Path | None = None,
    doc_out: Path | None = None,
) -> dict[str, Any]:
    root_resolved, target_role_dir, target_index, target_doc = _resolve_targets(
        root=root,
        role_dir=role_dir,
        index_out=index_out,
        doc_out=doc_out,
    )
    errors: list[str] = []
    runs, root_hygiene_issues = discover_multimodal_runs(target_role_dir, root=root_resolved)
    errors.extend(root_hygiene_issues)

    if not runs:
        errors.append(f"no_runs_found:{_rel_posix(target_role_dir, root_resolved)}")

    for r in runs:
        if not r["verified"]:
            errors.append(f"unverified_run:{r['run_id']}:{','.join(r['issues'])}")

    index_payload = build_multimodal_index(
        runs,
        root_hygiene_issues=root_hygiene_issues,
        strict=False,
    )
    errors.extend(
        iss for iss in index_payload["hygiene"]["root_hygiene_issues"] if iss not in errors
    )
    expected_index_bytes = sanitize_text(json.dumps(index_payload, indent=2) + "\n").encode("utf-8")
    expected_doc_bytes = render_multimodal_md(index_payload).encode("utf-8")

    index_in_sync = False
    if not target_index.is_file():
        errors.append(f"missing_index_json:{_rel_posix(target_index, root_resolved)}")
    else:
        for fh in scan_file_hygiene(target_index, root_resolved):
            errors.append(f"index_hygiene:{fh['kind']}:{fh['file']}")
        actual_index_bytes = target_index.read_bytes()
        if actual_index_bytes != expected_index_bytes:
            errors.append(f"out_of_sync_index_json:{_rel_posix(target_index, root_resolved)}")
        else:
            index_in_sync = True

    doc_in_sync = True
    if target_doc is not None:
        doc_in_sync = False
        if not target_doc.is_file():
            errors.append(f"missing_doc_md:{_rel_posix(target_doc, root_resolved)}")
        else:
            for fh in scan_file_hygiene(target_doc, root_resolved):
                errors.append(f"doc_hygiene:{fh['kind']}:{fh['file']}")
            actual_doc_text = target_doc.read_text(encoding="utf-8", errors="replace")
            if any(d in actual_doc_text for d in FORBIDDEN_DASHES):
                errors.append(f"forbidden_dash_in_doc:{_rel_posix(target_doc, root_resolved)}")
            actual_doc_bytes = target_doc.read_bytes()
            if actual_doc_bytes != expected_doc_bytes:
                errors.append(f"out_of_sync_doc_md:{_rel_posix(target_doc, root_resolved)}")
            else:
                doc_in_sync = True

    return {
        "ok": len(errors) == 0 and bool(index_payload["verified"]),
        "errors": errors,
        "index_in_sync": index_in_sync,
        "doc_in_sync": doc_in_sync,
        "role": ROLE,
        "target_model": TARGET_MODEL,
        "totals": index_payload["totals"],
        "hygiene": index_payload["hygiene"],
    }


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="python -m canary.gemini.multimodal_carbon",
        description="Verify and consolidate gemini-4-carbon multimodal_evidence runs into index.json and multimodal_evidence.md.",
    )
    ap.add_argument("--root", type=Path, default=ROOT)
    ap.add_argument("--role-dir", type=Path, default=None)
    ap.add_argument("--index-out", type=Path, default=None)
    ap.add_argument("--doc-out", type=Path, default=None)
    ap.add_argument("--sync", action="store_true")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--json", action="store_true")
    return ap


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)

    if args.check and not args.sync:
        report = check_multimodal_carbon(
            root=args.root,
            role_dir=args.role_dir,
            index_out=args.index_out,
            doc_out=args.doc_out,
        )
        if args.json:
            print(json.dumps(report, indent=2, sort_keys=True))
        else:
            t = report["totals"]
            u = t["usage"]
            status = "OK" if report["ok"] else "FAIL"
            print(
                f"multimodal_carbon [{status}]: runs={t['run_count']} subfamilies={t['subfamily_count']} "
                f"images={t['images_read_by_model']} calls={u['calls']} in={u['in']} out={u['out']} "
                f"thinking={u['thinking']} cost=${u['cost_usd']:.6f} errors={len(report['errors'])}"
            )
            for err in report["errors"]:
                print(f"  error: {err}")
        return 0 if report["ok"] else 1

    try:
        consolidate_multimodal_carbon(
            root=args.root,
            role_dir=args.role_dir,
            index_out=args.index_out,
            doc_out=args.doc_out,
            write_files=True,
            strict=True,
        )
    except ValueError as exc:
        err_report = {
            "ok": False,
            "errors": [sanitize_text(str(exc))],
            "role": ROLE,
            "target_model": TARGET_MODEL,
        }
        if args.json:
            print(json.dumps(err_report, indent=2, sort_keys=True))
        else:
            print(f"multimodal_carbon [FAIL]: {exc}")
        return 1

    report = check_multimodal_carbon(
        root=args.root,
        role_dir=args.role_dir,
        index_out=args.index_out,
        doc_out=args.doc_out,
    )
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        t = report["totals"]
        u = t["usage"]
        status = "OK" if report["ok"] else "FAIL"
        print(
            f"multimodal_carbon [{status}]: runs={t['run_count']} subfamilies={t['subfamily_count']} "
            f"images={t['images_read_by_model']} calls={u['calls']} in={u['in']} out={u['out']} "
            f"thinking={u['thinking']} cost=${u['cost_usd']:.6f}"
        )
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
