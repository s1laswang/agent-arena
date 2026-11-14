from __future__ import annotations

import argparse
import concurrent.futures as cf
import json
import multiprocessing as mp
from pathlib import Path
import shutil
import sys
import tempfile
from typing import Any, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from canary.env import Env
from canary.gemini.leak_encodings import (
    SUPPORTED_ENCODINGS,
    extract_env_secrets,
    scan_text_for_secret,
)
from canary.gemini.world_audit import audit_world_text_dir, normalize_seeds
from canary.rules import TIERS_VERSION

MODEL_ID = "gemini-4-carbon"
TIER_ORDER: tuple[str, ...] = ("easy", "medium", "hard")
DEFAULT_TIER_SEEDS: dict[str, tuple[int, ...]] = {
    "easy": (0, 1, 2, 3),
    "medium": (0, 1, 2, 3, 4, 5, 6, 7, 8, 9),
    "hard": (0, 1, 2, 3, 4, 5, 6),
}
DEFAULT_SOURCE_DIRS: tuple[Path, ...] = (
    ROOT / "results" / "gemini_roles" / "world_text" / "carbon-v14-seeds012" / "worlds",
    ROOT / "results" / "gemini_roles" / "world_text" / "carbon-v14-seeds3456-hard23" / "worlds",
    ROOT / "results" / "gemini_roles" / "world_text" / "carbon-v14-easy03-med789-hard46" / "worlds",
)
DEFAULT_OUT_DIR = (
    ROOT / "results" / "gemini_roles" / "world_text" / "carbon-v14-easy03-med789-hard46"
)
OUT_JSON_NAME = "parity_audit_21worlds.json"
OUT_MD_NAME = "parity_audit_21worlds.md"
FULL_24_TIER_SEEDS: dict[str, tuple[int, ...]] = {
    "easy": (0, 1, 2, 3),
    "medium": (0, 1, 2, 3, 4, 5, 6, 7, 8, 9),
    "hard": (0, 1, 2, 3, 4, 5, 6, 7, 8, 9),
}
FULL_24_SOURCE_DIRS: tuple[Path, ...] = (
    *DEFAULT_SOURCE_DIRS,
    ROOT / "results" / "gemini_roles" / "world_text" / "carbon-v14-hard789" / "worlds",
)
FULL_24_OUT_DIR = (
    ROOT / "results" / "gemini_roles" / "world_text" / "carbon-v14-hard789"
)
OUT_24_JSON_NAME = "parity_audit_24worlds.json"
OUT_24_MD_NAME = "parity_audit_24worlds.md"
PRESET_CONFIGS: dict[str, dict[str, Any]] = {
    "21worlds": {
        "out_dir": DEFAULT_OUT_DIR,
        "source_dirs": DEFAULT_SOURCE_DIRS,
        "easy_seeds": "0-3",
        "medium_seeds": "0-9",
        "hard_seeds": "0-6",
        "out_json_name": OUT_JSON_NAME,
        "out_md_name": OUT_MD_NAME,
    },
    "24worlds": {
        "out_dir": FULL_24_OUT_DIR,
        "source_dirs": FULL_24_SOURCE_DIRS,
        "easy_seeds": "0-3",
        "medium_seeds": "0-9",
        "hard_seeds": "0-9",
        "out_json_name": OUT_24_JSON_NAME,
        "out_md_name": OUT_24_MD_NAME,
    },
}
MD_H1 = "\x23"
MD_H2 = "\x23\x23"


def clean_str(val: str) -> str:
    s = val.replace(" \u2014 ", ", ").replace("\u2014", " - ")
    s = s.replace(" \u2013 ", " - ").replace("\u2013", "-")
    s = s.replace("\u2012", "-").replace("\u2015", "-")
    return s


def rel_posix(path: Path, root: Path = ROOT) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def collect_world_sources(
    source_dirs: Sequence[str | Path],
    tier_seeds: Mapping[str, Sequence[int]],
    root: Path = ROOT,
) -> tuple[dict[tuple[str, int], dict[str, Any]], list[dict[str, Any]]]:
    resolved_dirs = [Path(d) for d in source_dirs]
    found: dict[tuple[str, int], dict[str, Any]] = {}
    missing: list[dict[str, Any]] = []

    for tier in TIER_ORDER:
        if tier not in tier_seeds:
            continue
        for seed in tier_seeds[tier]:
            s_int = int(seed)
            matches: list[tuple[Path, Path]] = []
            for sdir in resolved_dirs:
                wt_fp = sdir / tier / f"{s_int}.worldtext.json"
                tx_fp = sdir / tier / f"{s_int}.text.json"
                if wt_fp.is_file() and tx_fp.is_file():
                    matches.append((wt_fp, tx_fp))
            if not matches:
                missing.append({"tier": tier, "seed": s_int, "reason": "missing_world_or_text_json"})
                continue
            wt_fp, tx_fp = matches[-1]
            found[(tier, s_int)] = {
                "tier": tier,
                "seed": s_int,
                "worldtext_path": wt_fp,
                "text_path": tx_fp,
                "source_worldtext": rel_posix(wt_fp, root),
                "source_text": rel_posix(tx_fp, root),
            }
    return found, missing


def _audit_single_tier_worker(
    stage_dir_str: str,
    tier: str,
    seeds: list[int],
) -> tuple[str, dict[str, Any]]:
    report = audit_world_text_dir(
        stage_dir_str,
        tier=tier,
        seeds=seeds,
        build_missing=False,
    )
    return tier, report


def _scan_world_files_worker(
    tier: str,
    seed: int,
    wt_path_str: str,
    tx_path_str: str,
    rel_wt: str,
    rel_tx: str,
) -> dict[str, Any]:
    wt = json.loads(Path(wt_path_str).read_text(encoding="utf-8"))
    tx = json.loads(Path(tx_path_str).read_text(encoding="utf-8"))
    env = Env(tier, seed)
    _, world_secrets = extract_env_secrets(env)

    wt_hits = scan_text_for_secret(wt, world_secrets)
    tx_hits = scan_text_for_secret(tx, world_secrets)

    days = tx.get("days") if isinstance(tx.get("days"), dict) else {}
    combined_msgs: list[Any] = []
    for d_key in sorted(days):
        if isinstance(days[d_key], list):
            combined_msgs.extend(days[d_key])
    cross_msg_hits = scan_text_for_secret(combined_msgs, world_secrets) if combined_msgs else []

    interviews = tx.get("interviews") if isinstance(tx.get("interviews"), dict) else {}
    iv_vals = [str(v) for v in interviews.values()]
    cross_iv_hits = scan_text_for_secret(iv_vals, world_secrets) if iv_vals else []

    total_hits = len(wt_hits) + len(tx_hits) + len(cross_msg_hits) + len(cross_iv_hits)
    personas = wt.get("personas") if isinstance(wt.get("personas"), list) else []
    llm_ok = bool((wt.get("meta") or {}).get("llm_ok")) if isinstance(wt.get("meta"), dict) else False

    row: dict[str, Any] = {
        "tier": tier,
        "seed": seed,
        "source_worldtext": rel_wt,
        "source_text": rel_tx,
        "n_personas": len(personas),
        "llm_ok": llm_ok,
        "worldtext_hits_count": len(wt_hits),
        "text_hits_count": len(tx_hits),
        "cross_day_hits_count": len(cross_msg_hits),
        "cross_interview_hits_count": len(cross_iv_hits),
        "clean": total_hits == 0,
    }
    if total_hits > 0:
        row["findings_count"] = total_hits
    return row


def render_parity_markdown(report: dict[str, Any]) -> str:
    status = "PASS" if report["ok"] else "FAIL"
    nl = report["non_leak"]
    sp = report["solver_parity"]
    le = report["leak_encodings"]
    n_worlds = int(report["n_worlds"])
    tier_counts = ", ".join(
        f"`{t}={report['tiers'][t]['n']}`"
        for t in TIER_ORDER
        if t in report["tiers"]
    )

    lines = [
        f"{MD_H1} Unified {n_worlds}-World 3-Tier Non-Leak and SolverPolicy Parity Audit",
        "",
        f"- Status: **{status}**",
        f"- Model ID: `{report['model_id']}`",
        f"- Canary Tiers Version: `{report['tiers_version']}`",
        f"- Corpus Worlds Audited: `{n_worlds}` ({tier_counts})",
        f"- Total Personas Audited: `{report['n_personas_total']}` across `{le['n_worldtext_files_scanned']}` `.worldtext.json` and `{le['n_text_files_scanned']}` `.text.json` files",
        f"- Non-Leak Status: `{'pass' if nl['ok'] else 'fail'}` (`truth_violations={nl['n_truth_violations']}`, `lint_violations={nl['n_lint_violations']}`, `leak_encoding_violations={nl['n_leak_encoding_violations']}`, `messages_checked={nl['n_messages_checked']}`, `interviews_checked={nl['n_interviews_checked']}`)",
        f"- Encoding Detectors Checked: `{le['n_supported_encodings']}` (`leak_encodings.scan_text_for_secret` violations=`{le['n_violations']}`)",
        f"- Pooled SolverPolicy Parity: `{'pass' if sp['ok'] else 'fail'}` (`template_catch_rate={sp['template_catch_rate']:.4f}`, `world_catch_rate={sp['world_catch_rate']:.4f}`, `catch_diff={sp['catch_rate_diff']:+.4f}`, `template_mean_score={sp['template_mean_score']:+.4f}`, `world_mean_score={sp['world_mean_score']:+.4f}`, `mean_score_diff={sp['mean_score_diff']:+.4f}`, `exact_match_rate={sp['exact_match_rate']:.4f}`)",
        "",
        f"{MD_H2} Source Corpus Directories",
        "",
    ]
    for sdir in report["source_dirs"]:
        lines.append(f"- `{sdir}`")

    lines.extend([
        "",
        f"{MD_H2} Per-Tier Non-Leak and SolverPolicy Parity Summary",
        "",
        "| Tier | Seeds (n) | Personas | Truth Errs | Lint Errs | Encoding Hits | Text Probe | Probe p-val | Template Catch | World Catch | Template Score | World Score | Score Diff | Exact Match | Status |",
        "|---|---:|---:|---:|---:|---:|---|---:|---:|---:|---:|---:|---:|---:|---|",
    ])

    for tier in TIER_ORDER:
        if tier not in report["tiers"]:
            continue
        tr = report["tiers"][tier]
        tnl = tr["non_leak"]
        tpr = tnl["text_probe"]
        tsp = tr["solver_parity"]
        t_stat = "PASS" if tr["ok"] else "FAIL"
        lines.append(
            f"| `{tier}` | `{tr['n']}` | `{tr['n_personas']}` | `{tnl['n_truth_violations']}` | "
            f"`{tnl['n_lint_violations']}` | `{tr['leak_encoding_violations']}` | "
            f"`{tpr['correct']}/{tpr['n']}` | `{tpr['p_value_vs_bar']:.4f}` | "
            f"`{tsp['template_catch_rate']:.4f}` | `{tsp['world_catch_rate']:.4f}` | "
            f"`{tsp['template_mean_score']:+.4f}` | `{tsp['world_mean_score']:+.4f}` | "
            f"`{tsp['mean_score_diff']:+.4f}` | `{tsp['exact_match_rate']:.4f}` | **{t_stat}** |"
        )

    lines.extend([
        "",
        f"{MD_H2} Per-World {n_worlds}-World Breakdown",
        "",
        "| Tier | Seed | Personas | Truth OK | Lint OK | Stego Clean | Template Score | World Score | Score Diff | World Correct | Source Artifact |",
        "|---|---:|---:|---|---|---|---:|---:|---:|---|---|",
    ])

    stego_map = {(r["tier"], int(r["seed"])): r for r in le["per_world"]}
    for tier in TIER_ORDER:
        if tier not in report["tiers"]:
            continue
        tr = report["tiers"][tier]
        parity_rows = {int(r["seed"]): r for r in tr["solver_parity"]["rows"]}
        for ps in tr["per_seed"]:
            s_id = int(ps["seed"])
            prow = parity_rows[s_id]
            srow = stego_map.get((tier, s_id), {})
            lines.append(
                f"| `{tier}` | `{s_id}` | `{srow.get('n_personas', 0)}` | "
                f"`{ps['truth_ok']}` | `{ps['lint_ok']}` | `{srow.get('clean', False)}` | "
                f"`{prow['template_score']:+.4f}` | `{prow['world_score']:+.4f}` | "
                f"`{prow['score_diff']:+.4f}` | `{prow['world_correct']}` | "
                f"`{ps['source_path']}` |"
            )

    lines.append("")
    return clean_str("\n".join(lines))


def run_3tier_parity_sweep(
    source_dirs: Sequence[str | Path] = DEFAULT_SOURCE_DIRS,
    out_dir: str | Path | None = DEFAULT_OUT_DIR,
    tier_seeds: Mapping[str, Sequence[int]] | None = None,
    jobs: int = 12,
    root: Path = ROOT,
    out_json_name: str = OUT_JSON_NAME,
    out_md_name: str = OUT_MD_NAME,
) -> dict[str, Any]:
    target_tier_seeds: dict[str, list[int]] = {}
    raw_map = tier_seeds if tier_seeds is not None else DEFAULT_TIER_SEEDS
    for tier in TIER_ORDER:
        if tier in raw_map and raw_map[tier]:
            target_tier_seeds[tier] = normalize_seeds(raw_map[tier])

    found_worlds, missing_entries = collect_world_sources(source_dirs, target_tier_seeds, root=root)

    with tempfile.TemporaryDirectory(prefix="worldtext_3tier_") as tmp_str:
        stage_dir = Path(tmp_str)
        scan_args: list[tuple[str, int, str, str, str, str]] = []
        for (tier, seed), info in sorted(
            found_worlds.items(),
            key=lambda kv: (TIER_ORDER.index(kv[0][0]), kv[0][1]),
        ):
            dst_tier = stage_dir / tier
            dst_tier.mkdir(parents=True, exist_ok=True)
            shutil.copy2(info["worldtext_path"], dst_tier / f"{seed}.worldtext.json")
            shutil.copy2(info["text_path"], dst_tier / f"{seed}.text.json")
            scan_args.append(
                (
                    tier,
                    seed,
                    str(info["worldtext_path"]),
                    str(info["text_path"]),
                    info["source_worldtext"],
                    info["source_text"],
                )
            )

        tier_reports: dict[str, dict[str, Any]] = {}
        stego_rows: list[dict[str, Any]] = []

        use_fork = int(jobs) > 1 and "fork" in mp.get_all_start_methods()
        if use_fork:
            max_workers = max(1, min(int(jobs), len(target_tier_seeds) + len(scan_args), 16))
            ctx = mp.get_context("fork")
            with cf.ProcessPoolExecutor(max_workers=max_workers, mp_context=ctx) as ex:
                tier_futs = [
                    ex.submit(_audit_single_tier_worker, str(stage_dir), tier, seeds)
                    for tier, seeds in target_tier_seeds.items()
                ]
                scan_futs = [ex.submit(_scan_world_files_worker, *args) for args in scan_args]
                for fut in tier_futs:
                    t_name, t_rep = fut.result()
                    tier_reports[t_name] = t_rep
                stego_rows = [fut.result() for fut in scan_futs]
        else:
            for tier, seeds in target_tier_seeds.items():
                _, tier_reports[tier] = _audit_single_tier_worker(str(stage_dir), tier, seeds)
            stego_rows = [_scan_world_files_worker(*args) for args in scan_args]

    stego_by_key = {(r["tier"], int(r["seed"])): r for r in stego_rows}
    ordered_tiers: dict[str, dict[str, Any]] = {}

    total_truth_violations = 0
    total_lint_violations = 0
    total_messages_checked = 0
    total_interviews_checked = 0
    all_missing_files: list[dict[str, Any]] = list(missing_entries)
    any_text_leak = False

    pooled_n = 0
    pooled_t_catches = 0.0
    pooled_w_catches = 0.0
    pooled_t_score_sum = 0.0
    pooled_w_score_sum = 0.0
    pooled_exact = 0

    for tier in TIER_ORDER:
        if tier not in tier_reports:
            continue
        tr = dict(tier_reports[tier])
        tr["worlds_dir"] = "merged_v14_world_text_corpus"
        tr["n"] = int(tr["n_seeds"])

        tier_personas = 0
        tier_stego_bad = 0
        updated_per_seed: list[dict[str, Any]] = []
        for ps in tr["per_seed"]:
            s_id = int(ps["seed"])
            ps_copy = dict(ps)
            src_info = found_worlds.get((tier, s_id))
            ps_copy["source_path"] = src_info["source_worldtext"] if src_info else None
            s_info = stego_by_key.get((tier, s_id))
            if s_info is not None:
                tier_personas += int(s_info["n_personas"])
                if not s_info["clean"]:
                    tier_stego_bad += 1
                ps_copy["stego_clean"] = bool(s_info["clean"])
            else:
                ps_copy["stego_clean"] = False
                tier_stego_bad += 1
            updated_per_seed.append(ps_copy)

        tr["per_seed"] = updated_per_seed
        tr["n_personas"] = tier_personas
        tr["leak_encoding_violations"] = tier_stego_bad
        tr["leak_encodings_ok"] = tier_stego_bad == 0
        tr["non_leak"] = dict(tr["non_leak"])
        tr["non_leak"]["ok"] = bool(tr["non_leak"]["ok"] and tier_stego_bad == 0)
        tr["ok"] = bool(tr["ok"] and tier_stego_bad == 0)
        tr["passed"] = tr["ok"]
        ordered_tiers[tier] = tr

        tnl = tr["non_leak"]
        total_truth_violations += int(tnl["n_truth_violations"])
        total_lint_violations += int(tnl["n_lint_violations"])
        total_messages_checked += int(tnl["n_messages_checked"])
        total_interviews_checked += int(tnl["n_interviews_checked"])
        for mf in tnl["missing_files"]:
            all_missing_files.append({"tier": tier, "seed": int(mf), "reason": "missing_in_stage"})
        if tnl["text_probe"]["text_leak"]:
            any_text_leak = True

        tsp = tr["solver_parity"]
        for row in tsp["rows"]:
            pooled_n += 1
            pooled_t_catches += 1.0 if row["template_correct"] else 0.0
            pooled_w_catches += 1.0 if row["world_correct"] else 0.0
            pooled_t_score_sum += float(row["template_score"])
            pooled_w_score_sum += float(row["world_score"])
            pooled_exact += 1 if row["exact_match"] else 0

    stego_violations = [r for r in stego_rows if not r["clean"]]
    stego_ok = len(stego_violations) == 0 and len(missing_entries) == 0
    all_non_leak_ok = bool(
        ordered_tiers
        and all(t["non_leak"]["ok"] for t in ordered_tiers.values())
        and stego_ok
        and len(all_missing_files) == 0
    )
    all_parity_ok = bool(
        ordered_tiers and all(t["solver_parity"]["ok"] for t in ordered_tiers.values())
    )
    overall_ok = bool(all_non_leak_ok and all_parity_ok)

    denom = max(1, pooled_n)
    t_catch_rate = pooled_t_catches / denom
    w_catch_rate = pooled_w_catches / denom
    t_mean_score = pooled_t_score_sum / denom
    w_mean_score = pooled_w_score_sum / denom
    total_personas = sum(int(r["n_personas"]) for r in stego_rows)
    llm_ok_worlds = sum(1 for r in stego_rows if r["llm_ok"])

    report: dict[str, Any] = {
        "ok": overall_ok,
        "passed": overall_ok,
        "model_id": MODEL_ID,
        "tiers_version": TIERS_VERSION,
        "n_worlds": len(stego_rows),
        "llm_ok_worlds": llm_ok_worlds,
        "n_personas_total": total_personas,
        "source_dirs": [rel_posix(Path(d), root) for d in source_dirs],
        "non_leak": {
            "ok": all_non_leak_ok,
            "n_truth_violations": total_truth_violations,
            "n_lint_violations": total_lint_violations,
            "n_leak_encoding_violations": len(stego_violations),
            "missing_files": all_missing_files,
            "n_messages_checked": total_messages_checked,
            "n_interviews_checked": total_interviews_checked,
            "text_leak_any": any_text_leak,
        },
        "solver_parity": {
            "ok": all_parity_ok,
            "n": pooled_n,
            "template_catch_rate": round(t_catch_rate, 6),
            "world_catch_rate": round(w_catch_rate, 6),
            "catch_rate_diff": round(w_catch_rate - t_catch_rate, 6),
            "template_mean_score": round(t_mean_score, 6),
            "world_mean_score": round(w_mean_score, 6),
            "mean_score_diff": round(w_mean_score - t_mean_score, 6),
            "exact_match_rate": round(pooled_exact / denom, 6),
        },
        "leak_encodings": {
            "ok": stego_ok,
            "n_supported_encodings": len(SUPPORTED_ENCODINGS),
            "n_worlds_scanned": len(stego_rows),
            "n_worldtext_files_scanned": len(stego_rows),
            "n_text_files_scanned": len(stego_rows),
            "n_personas_scanned": total_personas,
            "n_violations": len(stego_violations),
            "violations": stego_violations,
            "per_world": stego_rows,
        },
        "tiers": ordered_tiers,
    }

    if out_dir is not None:
        out_path = Path(out_dir)
        out_path.mkdir(parents=True, exist_ok=True)
        json_fp = out_path / out_json_name
        md_fp = out_path / out_md_name
        json_fp.write_text(
            clean_str(json.dumps(report, indent=2, sort_keys=True)) + "\n",
            encoding="utf-8",
        )
        md_fp.write_text(render_parity_markdown(report), encoding="utf-8")

    return report


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="run_worldtext_3tier_parity")
    ap.add_argument("--preset", choices=sorted(PRESET_CONFIGS), default="21worlds")
    ap.add_argument("--out-dir", default=None)
    ap.add_argument("--source-dirs", nargs="*", default=None)
    ap.add_argument("--easy-seeds", default=None)
    ap.add_argument("--medium-seeds", default=None)
    ap.add_argument("--hard-seeds", default=None)
    ap.add_argument("--out-json-name", default=None)
    ap.add_argument("--out-md-name", default=None)
    ap.add_argument("--jobs", type=int, default=12)
    ap.add_argument("--no-write", action="store_true")
    args = ap.parse_args(list(argv) if argv is not None else None)

    preset_cfg = PRESET_CONFIGS[args.preset]
    src_dirs = (
        [Path(p) for p in args.source_dirs]
        if args.source_dirs
        else list(preset_cfg["source_dirs"])
    )
    easy_spec = args.easy_seeds if args.easy_seeds is not None else preset_cfg["easy_seeds"]
    medium_spec = args.medium_seeds if args.medium_seeds is not None else preset_cfg["medium_seeds"]
    hard_spec = args.hard_seeds if args.hard_seeds is not None else preset_cfg["hard_seeds"]

    tier_seeds: dict[str, list[int]] = {}
    if easy_spec:
        tier_seeds["easy"] = normalize_seeds(easy_spec)
    if medium_spec:
        tier_seeds["medium"] = normalize_seeds(medium_spec)
    if hard_spec:
        tier_seeds["hard"] = normalize_seeds(hard_spec)

    resolved_out_dir = Path(args.out_dir) if args.out_dir is not None else Path(preset_cfg["out_dir"])
    out_target = None if args.no_write else resolved_out_dir
    out_json_name = args.out_json_name or str(preset_cfg["out_json_name"])
    out_md_name = args.out_md_name or str(preset_cfg["out_md_name"])

    report = run_3tier_parity_sweep(
        source_dirs=src_dirs,
        out_dir=out_target,
        tier_seeds=tier_seeds,
        jobs=args.jobs,
        out_json_name=out_json_name,
        out_md_name=out_md_name,
    )
    summary = {
        "ok": report["ok"],
        "n_worlds": report["n_worlds"],
        "n_personas_total": report["n_personas_total"],
        "non_leak_ok": report["non_leak"]["ok"],
        "solver_parity_ok": report["solver_parity"]["ok"],
        "leak_encodings_ok": report["leak_encodings"]["ok"],
        "easy_ok": report["tiers"].get("easy", {}).get("ok"),
        "medium_ok": report["tiers"].get("medium", {}).get("ok"),
        "hard_ok": report["tiers"].get("hard", {}).get("ok"),
        "world_catch_rate": report["solver_parity"]["world_catch_rate"],
        "template_catch_rate": report["solver_parity"]["template_catch_rate"],
        "world_mean_score": report["solver_parity"]["world_mean_score"],
        "template_mean_score": report["solver_parity"]["template_mean_score"],
    }
    print(json.dumps(summary, sort_keys=True))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
