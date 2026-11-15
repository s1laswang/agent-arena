from __future__ import annotations

import json
import math
from pathlib import Path
import random
import re
import shutil
import subprocess
from typing import Any, Sequence

from canary.agents.world_builder import TRUTH_KEYS, public_view
from canary.env import Env
from canary.gemini import worldtext_carbon as wc

ROOT = Path(__file__).resolve().parents[1]
ROLE_DIR = ROOT / "results" / "gemini" / "roles_carbon" / "world_text"
SUITE_DIR = ROLE_DIR / "worldtext-carbon-suite"
DOC_PATH = ROOT / "docs" / "gemini" / "roles_carbon" / "world_text.md"
PROTECTED_PATHS_FILE = ROOT / ".github" / "protected-paths.txt"
SELF_PATH = Path(__file__).resolve()

HASH_CHAR = chr(35)
H1_PREFIX = HASH_CHAR + " "
H2_PREFIX = (HASH_CHAR * 2) + " "
SKIP_RUN_DIRS = frozenset({"reference", "superseded", "_invalid", "worldtext-carbon-suite"})
TIER_ORDER: tuple[str, ...] = ("easy", "medium", "hard")
TIER_RANK: dict[str, int] = {"easy": 0, "medium": 1, "hard": 2}
THINKING_ORDER: tuple[str, ...] = ("low", "medium", "high")

EXPECTED_TOTALS: dict[str, Any] = {
    "verified_folders": 16,
    "calls": 1637,
    "in": 54755491,
    "out": 791997,
    "thinking": 791365,
    "cached": 50867472,
    "cost_usd": 22.728348,
}

EXPECTED_SUBROLE_TOTALS: dict[str, dict[str, Any]] = {
    "biased_chatter": {
        "verified_folders": 1,
        "calls": 2,
        "in": 3429,
        "out": 2734,
        "thinking": 1756,
        "cached": 0,
        "cost_usd": 0.034198,
    },
    "biased_chatter_hard": {
        "verified_folders": 1,
        "calls": 12,
        "in": 32161,
        "out": 13478,
        "thinking": 7609,
        "cached": 0,
        "cost_usd": 0.199102,
    },
    "biased_chatter_investigator_ablation": {
        "verified_folders": 3,
        "calls": 1317,
        "in": 54239859,
        "out": 666365,
        "thinking": 588166,
        "cached": 50863655,
        "cost_usd": 18.502424,
    },
    "company_personas_chatter": {
        "verified_folders": 4,
        "calls": 129,
        "in": 170729,
        "out": 74513,
        "thinking": 99845,
        "cached": 0,
        "cost_usd": 2.085038,
    },
    "dynamic_mid_episode_events": {
        "verified_folders": 3,
        "calls": 33,
        "in": 166943,
        "out": 11924,
        "thinking": 19720,
        "cached": 3817,
        "cost_usd": 0.650326,
    },
    "persona_interviews": {
        "verified_folders": 3,
        "calls": 120,
        "in": 118268,
        "out": 8751,
        "thinking": 31892,
        "cached": 0,
        "cost_usd": 0.642966,
    },
    "thinking_level_calibration": {
        "verified_folders": 1,
        "calls": 24,
        "in": 24102,
        "out": 14232,
        "thinking": 42377,
        "cached": 0,
        "cost_usd": 0.614294,
    },
}

SECRET_REGEXES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("google_key", wc.GOOGLE_KEY_RE),
    ("sk_key", wc.SK_KEY_RE),
    ("oauth_token", wc.OAUTH_RE),
    ("github_pat", re.compile(r"(?<![A-Za-z0-9_])(?:ghp_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})")),
    ("private_key", re.compile(r"BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY")),
)


def _read_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(data, dict), f"expected JSON object in {path}"
    return data


def _raw_verified_runs() -> list[dict[str, Any]]:
    runs: list[dict[str, Any]] = []
    for meta_path in sorted(ROLE_DIR.glob("*/meta.json")):
        run_dir = meta_path.parent
        if run_dir.name in SKIP_RUN_DIRS:
            continue
        meta = _read_json(meta_path)
        summary = _read_json(run_dir / "summary.json")
        audit_path = run_dir / "audit.json"
        audit = _read_json(audit_path) if audit_path.is_file() else {}
        u = meta["usage"]
        assert isinstance(u, dict)
        raw_cost = u.get("cost_usd_est", u.get("cost_usd"))
        assert isinstance(raw_cost, (int, float)) and not isinstance(raw_cost, bool) and raw_cost > 0
        usage = {
            "calls": int(u["calls"]),
            "in": int(u["in"]),
            "out": int(u["out"]),
            "thinking": int(u["thinking"]),
            "cached": int(u["cached"]),
            "cost_usd": round(float(raw_cost), 6),
        }
        runs.append({
            "name": run_dir.name,
            "dir": run_dir,
            "rel_dir": run_dir.relative_to(ROOT).as_posix(),
            "meta": meta,
            "summary": summary,
            "audit": audit,
            "subrole": str(meta["subrole"]),
            "commit": str(meta["commit"]),
            "usage": usage,
        })
    return runs


def _parse_markdown_sections_and_tables(md_text: str) -> dict[str, list[list[str]]]:
    sections: dict[str, list[list[str]]] = {}
    current_heading = ""
    current_rows: list[list[str]] = []
    for raw_line in md_text.splitlines():
        line = raw_line.strip()
        if line.startswith(H2_PREFIX):
            if current_heading and current_rows:
                sections[current_heading] = current_rows
            current_heading = line[len(H2_PREFIX):].strip()
            current_rows = []
            continue
        if current_heading and line.startswith("|") and line.endswith("|"):
            cells = [c.strip() for c in line[1:-1].split("|")]
            if all(re.fullmatch(r":?-{3,}:?", c) for c in cells):
                continue
            current_rows.append(cells)
    if current_heading and current_rows:
        sections[current_heading] = current_rows
    return sections


def _wilson_ci95_ref(
    successes: int,
    total: int,
    digits: int = 4,
    z: float = 1.959963984540054,
) -> list[float]:
    assert 0 <= successes <= total and total > 0
    n = float(total)
    z2 = z * z
    p_hat = successes / n
    denom = 1.0 + z2 / n
    center = (p_hat + z2 / (2.0 * n)) / denom
    rad = max(0.0, (p_hat * (1.0 - p_hat) + z2 / (4.0 * n)) / n)
    half = (z * math.sqrt(rad)) / denom
    return [round(max(0.0, center - half), digits), round(min(1.0, center + half), digits)]


def _bootstrap_mean_ci95_ref(values: Sequence[float], n_boot: int = 2000, seed: int = 104729) -> list[float]:
    assert len(values) > 0
    clean = [float(v) for v in values]
    if len(clean) == 1 or min(clean) == max(clean):
        v = round(clean[0], 4)
        return [v, v]
    rng = random.Random(seed)
    n = len(clean)
    boot_means = sorted(sum(clean[rng.randrange(n)] for _ in range(n)) / n for _ in range(n_boot))
    lo = boot_means[int(0.025 * (n_boot - 1))]
    hi = boot_means[int(0.975 * (n_boot - 1))]
    return [round(lo, 4), round(hi, 4)]


def _binomial_upper_tail_ref(k: int, n: int, p0: float) -> float:
    if k <= 0:
        return 1.0
    assert 0 < k <= n and 0.0 < p0 < 1.0
    total_prob = sum(
        math.comb(n, idx) * (p0 ** idx) * ((1.0 - p0) ** (n - idx))
        for idx in range(k, n + 1)
    )
    return round(min(1.0, max(0.0, total_prob)), 6)


def _mean4(values: Sequence[float]) -> float:
    assert len(values) > 0
    return round(sum(float(v) for v in values) / len(values), 4)


def _all_worldtext_files() -> list[Path]:
    explicit = [
        ROOT / "canary" / "gemini" / "worldtext_carbon.py",
        DOC_PATH,
        ROOT / "tests" / "test_gemini_lab_worldtext_carbon.py",
        SELF_PATH,
    ]
    artifact_files = sorted(p for p in ROLE_DIR.rglob("*") if p.is_file())
    combined = sorted({p.resolve() for p in (*explicit, *artifact_files)})
    return combined


def _load_protected_prefixes() -> list[str]:
    prefixes: list[str] = []
    for raw in PROTECTED_PATHS_FILE.read_text(encoding="utf-8").splitlines():
        entry = raw.strip()
        if not entry or entry.startswith(HASH_CHAR):
            continue
        prefixes.append(entry)
    assert prefixes, "expected non-empty .github/protected-paths.txt rules"
    return prefixes


def _matches_protected_path(rel_posix: str, prefixes: Sequence[str]) -> bool:
    for prefix in prefixes:
        if prefix.endswith("/"):
            if rel_posix.startswith(prefix):
                return True
        elif rel_posix == prefix:
            return True
    return False


def test_zero_comments_and_forbidden_dashes_across_worldtext_files():
    code_targets = (
        ROOT / "canary" / "gemini" / "worldtext_carbon.py",
        ROOT / "tests" / "test_gemini_lab_worldtext_carbon.py",
        SELF_PATH,
    )
    for path in code_targets:
        text = path.read_text(encoding="utf-8")
        assert HASH_CHAR not in text, f"found forbidden comment char in {path}"
        for dash in wc.FORBIDDEN_DASHES:
            assert dash not in text, f"found forbidden dash in {path}"

    for path in _all_worldtext_files():
        text = path.read_text(encoding="utf-8")
        for dash in wc.FORBIDDEN_DASHES:
            assert dash not in text, f"found forbidden dash in {path}"


def test_zero_secrets_and_zero_protected_paths_overlap():
    prefixes = _load_protected_prefixes()
    worldtext_files = _all_worldtext_files()
    assert len(worldtext_files) >= 59

    rel_paths = {p.relative_to(ROOT).as_posix() for p in worldtext_files}
    proc_diff = subprocess.run(
        ["git", "diff", "--name-only", "origin/justSilas..HEAD"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=15,
    )
    if proc_diff.returncode == 0:
        for line in proc_diff.stdout.splitlines():
            cleaned = line.strip()
            if cleaned:
                rel_paths.add(cleaned)

    proc_status = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=15,
    )
    if proc_status.returncode == 0:
        for line in proc_status.stdout.splitlines():
            if len(line) > 3:
                cand = line[3:].strip().strip('"')
                if cand:
                    rel_paths.add(cand)

    overlaps = sorted(rel for rel in rel_paths if _matches_protected_path(rel, prefixes))
    assert overlaps == [], f"protected-paths overlap detected: {overlaps}"

    for path in worldtext_files:
        rel = path.relative_to(ROOT).as_posix()
        assert path.name != ".env" and not path.name.startswith(".env.")
        assert path.name != "SALT" and "SALT" not in path.parts
        assert not rel.endswith(".world.json")
        assert not any(path.name.endswith(sfx) for sfx in wc.FORBIDDEN_RAW_SUFFIXES)
        assert path.name not in wc.FORBIDDEN_RAW_FILENAMES
        assert "transcripts" not in path.parts
        text = path.read_text(encoding="utf-8")
        for label, rx in SECRET_REGEXES:
            match = rx.search(text)
            assert match is None, f"secret pattern {label} matched in {rel}"


def test_recompute_deduplicated_totals_from_per_run_meta_json():
    assert not (SUITE_DIR / "meta.json").exists(), "suite folder must omit meta.json"
    runs = _raw_verified_runs()
    assert len(runs) == 16

    seen_dirs: set[str] = set()
    seen_ledger_ids: set[str] = set()
    recomputed = {
        "verified_folders": len(runs),
        "calls": 0,
        "in": 0,
        "out": 0,
        "thinking": 0,
        "cached": 0,
        "cost_usd": 0.0,
    }

    for item in runs:
        assert item["rel_dir"] not in seen_dirs
        seen_dirs.add(item["rel_dir"])
        meta = item["meta"]
        assert meta.get("role") == "world_text"
        assert meta.get("model_id") == "gemini-4-carbon"
        assert meta.get("environment_scope") == wc.SCOPE_LABEL
        assert wc.COMMIT_RE.match(item["commit"])
        assert meta.get("stub") is not True
        assert meta.get("fake_env") is not True
        assert meta.get("smoke") is not True
        ledger_id = meta.get("ledger_run_id")
        if isinstance(ledger_id, str) and ledger_id:
            assert ledger_id not in seen_ledger_ids, f"duplicate ledger_run_id {ledger_id}"
            seen_ledger_ids.add(ledger_id)

        u = item["usage"]
        assert u["calls"] > 0 and u["in"] > 0 and u["out"] > 0 and u["cached"] >= 0 and u["thinking"] >= 0
        recomputed["calls"] += u["calls"]
        recomputed["in"] += u["in"]
        recomputed["out"] += u["out"]
        recomputed["thinking"] += u["thinking"]
        recomputed["cached"] += u["cached"]
        recomputed["cost_usd"] = round(recomputed["cost_usd"] + u["cost_usd"], 6)

    assert recomputed == EXPECTED_TOTALS

    suite_json = _read_json(SUITE_DIR / "summary.json")
    audit_json = _read_json(SUITE_DIR / "audit.json")
    assert suite_json["totals"] == EXPECTED_TOTALS
    assert suite_json["verified_run_folders"] == [r["rel_dir"] for r in runs]
    assert suite_json["leak_and_safety_audit"]["verified_folders_audited"] == 16
    assert suite_json["leak_and_safety_audit"]["all_clean"] is True
    assert audit_json["leak_and_safety_audit"] == suite_json["leak_and_safety_audit"]

    doc_text = DOC_PATH.read_text(encoding="utf-8")
    suite_md_text = (SUITE_DIR / "summary.md").read_text(encoding="utf-8")
    assert doc_text.startswith(H1_PREFIX + "Role 1 Consolidated Suite: World Text & Persona Synthesis (`gemini-4-carbon`)")
    assert doc_text.startswith(suite_md_text.rstrip())
    for md_txt in (doc_text, suite_md_text):
        assert "- Verified `world_text` run folders consolidated: `16`" in md_txt
        assert "- Total Gemini API calls: `1637`" in md_txt
        assert "- Total tokens (in / out / thinking / cached): `54,755,491` / `791,997` / `791,365` / `50,867,472`" in md_txt
        assert "- Total estimated cost (USD): `$22.728348`" in md_txt
        assert (
            "- Non-leak & safety audit: `truth_leaks=0`, `prompt_leaks=0`, `lint_violations=0`, "
            "`stego_violations=0`, `fallbacks=0`, `secret_leaks=0` (`all_clean=True`)"
        ) in md_txt


def test_recompute_subrole_slice_totals_and_provenance_ledger_rows():
    runs = _raw_verified_runs()
    suite_json = _read_json(SUITE_DIR / "summary.json")
    sections = _parse_markdown_sections_and_tables(DOC_PATH.read_text(encoding="utf-8"))

    by_subrole: dict[str, dict[str, Any]] = {}
    for item in runs:
        sub = item["subrole"]
        if sub not in by_subrole:
            by_subrole[sub] = {
                "verified_folders": 0,
                "calls": 0,
                "in": 0,
                "out": 0,
                "thinking": 0,
                "cached": 0,
                "cost_usd": 0.0,
            }
        slot = by_subrole[sub]
        u = item["usage"]
        slot["verified_folders"] += 1
        slot["calls"] += u["calls"]
        slot["in"] += u["in"]
        slot["out"] += u["out"]
        slot["thinking"] += u["thinking"]
        slot["cached"] += u["cached"]
        slot["cost_usd"] = round(slot["cost_usd"] + u["cost_usd"], 6)

    sorted_subroles = dict(sorted(by_subrole.items()))
    assert sorted_subroles == EXPECTED_SUBROLE_TOTALS
    assert suite_json["by_subrole_totals"] == EXPECTED_SUBROLE_TOTALS

    sum_across_subroles = {
        "verified_folders": sum(v["verified_folders"] for v in sorted_subroles.values()),
        "calls": sum(v["calls"] for v in sorted_subroles.values()),
        "in": sum(v["in"] for v in sorted_subroles.values()),
        "out": sum(v["out"] for v in sorted_subroles.values()),
        "thinking": sum(v["thinking"] for v in sorted_subroles.values()),
        "cached": sum(v["cached"] for v in sorted_subroles.values()),
        "cost_usd": round(sum(v["cost_usd"] for v in sorted_subroles.values()), 6),
    }
    assert sum_across_subroles == EXPECTED_TOTALS

    sec6_rows = sections["6. De-Duplicated Role 1 (`world_text`) Totals (`totals`)"]
    assert sec6_rows[0] == [
        "Subrole Slice",
        "Verified Folders",
        "Calls",
        "Input Tokens",
        "Output Tokens",
        "Thinking Tokens",
        "Cached Tokens",
        "Cost (USD)",
    ]
    assert len(sec6_rows) == 1 + len(EXPECTED_SUBROLE_TOTALS) + 1
    for idx, (sub_key, exp) in enumerate(EXPECTED_SUBROLE_TOTALS.items(), start=1):
        expected_cells = [
            f"`{sub_key}`",
            str(exp["verified_folders"]),
            str(exp["calls"]),
            f"{exp['in']:,}",
            f"{exp['out']:,}",
            f"{exp['thinking']:,}",
            f"{exp['cached']:,}",
            f"${exp['cost_usd']:.6f}",
        ]
        assert sec6_rows[idx] == expected_cells

    assert sec6_rows[-1] == [
        "**total**",
        f"**{EXPECTED_TOTALS['verified_folders']}**",
        f"**{EXPECTED_TOTALS['calls']}**",
        f"**{EXPECTED_TOTALS['in']:,}**",
        f"**{EXPECTED_TOTALS['out']:,}**",
        f"**{EXPECTED_TOTALS['thinking']:,}**",
        f"**{EXPECTED_TOTALS['cached']:,}**",
        f"**${EXPECTED_TOTALS['cost_usd']:.6f}**",
    ]

    sec8_rows = sections["8. Verified Run Provenance Ledger"]
    assert sec8_rows[0] == [
        "Folder",
        "Subrole",
        "Commit",
        "Samples",
        "Calls",
        "In Tok",
        "Out Tok",
        "Think Tok",
        "Cached Tok",
        "Cost (USD)",
        "Key Metric",
    ]
    assert len(sec8_rows) == 1 + len(runs)
    for idx, item in enumerate(runs, start=1):
        meta = item["meta"]
        u = item["usage"]
        samples = meta.get("episode_count", meta.get("sample_count", meta.get("n_episodes", 0)))
        expected_ledger_row = [
            f"`{item['name']}`",
            f"`{item['subrole']}`",
            f"`{item['commit'][:8]}`",
            str(samples),
            str(u["calls"]),
            f"{u['in']:,}",
            f"{u['out']:,}",
            f"{u['thinking']:,}",
            f"{u['cached']:,}",
            f"${u['cost_usd']:.4f}",
            wc.clean_str(meta["key_metric"]),
        ]
        assert sec8_rows[idx] == expected_ledger_row


def test_company_personas_and_probe_table_rows_match_underlying_json():
    runs = [r for r in _raw_verified_runs() if r["subrole"] == "company_personas_chatter"]
    assert len(runs) == 4
    suite_json = _read_json(SUITE_DIR / "summary.json")
    audit_json = _read_json(SUITE_DIR / "audit.json")
    sections = _parse_markdown_sections_and_tables(DOC_PATH.read_text(encoding="utf-8"))

    dedup_worlds: dict[tuple[str, int], dict[str, Any]] = {}
    total_msgs = 0
    for item in runs:
        per_world = item["summary"]["per_world"]
        assert isinstance(per_world, list) and len(per_world) == int(item["meta"]["n_worlds"])
        total_msgs += int(item["meta"]["n_day_messages_generated"])
        for w in per_world:
            key = (str(w["tier"]), int(w["seed"]))
            assert key not in dedup_worlds, f"duplicate company_personas world {key}"
            assert bool(w.get("llm_ok", True)) is True
            assert int(w.get("truth_leak_violations", 0)) == 0
            assert int(w.get("lint_violations", 0)) == 0
            s_score = float(w["solver_score"])
            t_score = float(w.get("template_baseline_score", w.get("template_score")))
            dedup_worlds[key] = {
                "tier": key[0],
                "seed": key[1],
                "n_personas": int(w["n_personas"]),
                "solver_score": s_score,
                "template_score": t_score,
                "solver_correct": bool(w["solver_correct"]),
                "delta": round(s_score - t_score, 6),
            }

    ordered = sorted(dedup_worlds.values(), key=lambda x: (TIER_RANK[x["tier"]], x["seed"]))
    assert len(ordered) == 24
    assert sum(w["n_personas"] for w in ordered) == 648
    assert total_msgs == 328

    sec1_rows = sections["1. Company Personas & Workplace Chatter (`company_personas_suite`)"]
    assert len(sec1_rows) == 5
    expected_counts = {"easy": (4, 48), "medium": (10, 200), "hard": (10, 400), "overall": (24, 648)}

    for idx, sl_name in enumerate((*TIER_ORDER, "overall"), start=1):
        subset = ordered if sl_name == "overall" else [w for w in ordered if w["tier"] == sl_name]
        assert (len(subset), sum(w["n_personas"] for w in subset)) == expected_counts[sl_name]
        s_vals = [w["solver_score"] for w in subset]
        t_vals = [w["template_score"] for w in subset]
        d_vals = [w["delta"] for w in subset]
        k_ok = sum(1 for w in subset if w["solver_correct"])

        acc = round(k_ok / len(subset), 4)
        acc_ci = _wilson_ci95_ref(k_ok, len(subset))
        s_mean, s_ci = _mean4(s_vals), _bootstrap_mean_ci95_ref(s_vals)
        t_mean, t_ci = _mean4(t_vals), _bootstrap_mean_ci95_ref(t_vals)
        d_mean, d_ci = _mean4(d_vals), _bootstrap_mean_ci95_ref(d_vals)

        js_row = suite_json["company_personas_suite"]["by_tier"][sl_name]
        assert js_row == {
            "n_worlds": len(subset),
            "n_personas": sum(w["n_personas"] for w in subset),
            "solver_mean": s_mean,
            "solver_ci95": s_ci,
            "solver_accuracy": acc,
            "solver_accuracy_ci95": acc_ci,
            "template_mean": t_mean,
            "template_ci95": t_ci,
            "paired_delta_mean": d_mean,
            "paired_delta_ci95": d_ci,
        }

        expected_md_row = [
            f"`{sl_name}`",
            str(len(subset)),
            str(sum(w["n_personas"] for w in subset)),
            f"{acc * 100:.1f}% [{acc_ci[0] * 100:.1f}%, {acc_ci[1] * 100:.1f}%]",
            f"{s_mean:+.4f} [{s_ci[0]:+.4f}, {s_ci[1]:+.4f}]",
            f"{t_mean:+.4f} [{t_ci[0]:+.4f}, {t_ci[1]:+.4f}]",
            f"{d_mean:+.4f} [{d_ci[0]:+.4f}, {d_ci[1]:+.4f}]",
        ]
        assert sec1_rows[idx] == expected_md_row

    raw_parity_audit = _read_json(ROLE_DIR / "carbon-v14-hard789" / "audit.json")
    assert audit_json["v14_multi_tier_parity_and_probe_audit"] == raw_parity_audit
    sec1b_rows = sections["1b. 37-Encoding Non-Leak & Text-Only Probe Audit (`v14_multi_tier_parity_and_probe_audit`)"]
    assert len(sec1b_rows) == 4
    for idx, tier_name in enumerate(TIER_ORDER, start=1):
        trow = raw_parity_audit["by_tier"][tier_name]
        tnl = trow["non_leak"]
        probe = tnl["text_probe"]
        expected_1b = [
            f"`{tier_name}`",
            str(trow["n_worlds"]),
            str(trow["n_personas"]),
            f"`{tnl['n_truth_violations']} / {tnl['n_lint_violations']} / 0`",
            f"`{probe['correct']}/{probe['n']}` ({float(probe['accuracy']) * 100:.1f}%)",
            f"{float(probe['fair_bar']) * 100:.1f}%",
            f"`{float(probe['p_value_vs_bar']):.4f}`",
            f"`{probe['text_leak']}`",
        ]
        assert sec1b_rows[idx] == expected_1b


def test_biased_chatter_and_ablation_table_rows_match_underlying_json():
    all_runs = _raw_verified_runs()
    chatter_runs = [r for r in all_runs if r["subrole"] in {"biased_chatter", "biased_chatter_hard"}]
    ablation_runs = [r for r in all_runs if r["subrole"] == "biased_chatter_investigator_ablation"]
    assert len(chatter_runs) == 2
    assert len(ablation_runs) == 3

    assert sum(int(r["meta"]["n_messages"]) for r in chatter_runs) == 70
    assert sum(int(r["meta"]["n_llm_messages"]) for r in chatter_runs) == 70
    assert sum(int(r["meta"]["n_fallback_messages"]) for r in chatter_runs) == 0

    episodes_by_key: dict[tuple[str, int, str, str], dict[str, Any]] = {}
    for item in ablation_runs:
        eps = item["summary"]["episodes"]
        assert isinstance(eps, list) and len(eps) == 12
        for ep in eps:
            key = (str(ep["tier"]), int(ep["seed"]), str(ep["policy"]), str(ep["world"]))
            assert key not in episodes_by_key, f"duplicate ablation episode {key}"
            episodes_by_key[key] = ep
    assert len(episodes_by_key) == 36

    suite_json = _read_json(SUITE_DIR / "summary.json")
    sections = _parse_markdown_sections_and_tables(DOC_PATH.read_text(encoding="utf-8"))
    sec2_rows = sections["2. Bias-Flavoured Workplace Chatter & Investigator Ablation (`biased_chatter_suite`)"]
    assert len(sec2_rows) == 10

    row_cursor = 1
    all_eps = list(episodes_by_key.values())
    for sl_name, tier_filter, exp_seeds in (("medium", "medium", 2), ("hard", "hard", 4), ("overall", None, 6)):
        subset = [e for e in all_eps if tier_filter is None or e["tier"] == tier_filter]
        for pol in ("carbon", "solver", "obvious_heuristic"):
            b_map = {(e["tier"], int(e["seed"])): e for e in subset if e["policy"] == pol and e["world"] == "biased"}
            t_map = {(e["tier"], int(e["seed"])): e for e in subset if e["policy"] == pol and e["world"] == "template"}
            keys = sorted(set(b_map) & set(t_map), key=lambda k: (TIER_RANK[k[0]], k[1]))
            assert len(keys) == exp_seeds

            b_scores = [float(b_map[k]["score"]) for k in keys]
            t_scores = [float(t_map[k]["score"]) for k in keys]
            deltas = [round(float(b_map[k]["score"]) - float(t_map[k]["score"]), 6) for k in keys]
            b_acc_k = sum(1 for k in keys if b_map[k]["correct"])
            t_acc_k = sum(1 for k in keys if t_map[k]["correct"])
            b_dist_k = sum(1 for k in keys if b_map[k]["rumor_target_distracted"])
            t_dist_k = sum(1 for k in keys if t_map[k]["rumor_target_distracted"])
            b_accused_k = sum(1 for k in keys if b_map[k]["rumor_target_accused"])

            b_mean, b_ci = _mean4(b_scores), _bootstrap_mean_ci95_ref(b_scores)
            t_mean, t_ci = _mean4(t_scores), _bootstrap_mean_ci95_ref(t_scores)
            d_mean, d_ci = _mean4(deltas), _bootstrap_mean_ci95_ref(deltas)
            b_acc = round(b_acc_k / len(keys), 4)
            b_dist = round(b_dist_k / len(keys), 4)

            js_pol = suite_json["biased_chatter_suite"]["paired_slices"][sl_name][pol]
            assert js_pol == {
                "n_paired_seeds": len(keys),
                "biased_mean": b_mean,
                "biased_ci95": b_ci,
                "biased_accuracy": b_acc,
                "biased_accuracy_ci95": _wilson_ci95_ref(b_acc_k, len(keys)),
                "template_mean": t_mean,
                "template_ci95": t_ci,
                "template_accuracy": round(t_acc_k / len(keys), 4),
                "paired_delta_mean": d_mean,
                "paired_delta_ci95": d_ci,
                "biased_distraction_rate": b_dist,
                "biased_distraction_ci95": _wilson_ci95_ref(b_dist_k, len(keys)),
                "template_distraction_rate": round(t_dist_k / len(keys), 4),
                "biased_rumor_accused_rate": round(b_accused_k / len(keys), 4),
            }

            expected_md = [
                f"`{sl_name}`",
                f"`{pol}`",
                str(len(keys)),
                f"{b_mean:+.4f} [{b_ci[0]:+.4f}, {b_ci[1]:+.4f}]",
                f"{t_mean:+.4f} [{t_ci[0]:+.4f}, {t_ci[1]:+.4f}]",
                f"{d_mean:+.4f} [{d_ci[0]:+.4f}, {d_ci[1]:+.4f}]",
                f"{b_acc * 100:.1f}%",
                f"{b_dist * 100:.1f}%",
            ]
            assert sec2_rows[row_cursor] == expected_md
            row_cursor += 1


def test_persona_interviews_table_rows_and_invariance_match_underlying_json():
    iv_runs = [r for r in _raw_verified_runs() if r["subrole"] == "persona_interviews"]
    assert len(iv_runs) == 3

    dedup_worlds: dict[tuple[str, int], dict[str, Any]] = {}
    total_interviews = 0
    total_cal_ok = 0
    total_swap_checks = 0
    total_swap_ok = 0

    for item in iv_runs:
        n_iv = int(item["meta"]["n_interviews_generated"])
        cal_acc = float(item["meta"]["signal_calibration_accuracy"])
        chk = int(item["audit"]["counterfactual_checks"])
        inv_rate = float(item["audit"]["counterfactual_invariance_rate"])
        assert chk == n_iv * 3
        assert cal_acc == 1.0 and inv_rate == 1.0
        total_interviews += n_iv
        total_cal_ok += int(round(cal_acc * n_iv))
        total_swap_checks += chk
        total_swap_ok += int(round(inv_rate * chk))

        per_world = item["summary"]["solver_parity"]["per_world"]
        assert len(per_world) == int(item["meta"]["n_worlds"])
        for pw in per_world:
            key = (str(pw["tier"]), int(pw["seed"]))
            assert key not in dedup_worlds, f"duplicate interview world {key}"
            ps = pw["persona_solver"]
            ts = pw["template_solver"]
            dedup_worlds[key] = {
                "tier": key[0],
                "seed": key[1],
                "ps_score": float(ps["score"]),
                "ps_correct": bool(ps["correct"]),
                "ts_score": float(ts["score"]),
                "delta": round(float(ps["score"]) - float(ts["score"]), 6),
            }

    assert total_interviews == 120
    assert total_cal_ok == 120
    assert total_swap_checks == 360
    assert total_swap_ok == 360
    ordered = sorted(dedup_worlds.values(), key=lambda w: (TIER_RANK[w["tier"]], w["seed"]))
    assert len(ordered) == 15

    suite_json = _read_json(SUITE_DIR / "summary.json")
    doc_text = DOC_PATH.read_text(encoding="utf-8")
    sections = _parse_markdown_sections_and_tables(doc_text)
    assert "- Worlds / Live interviews: `15` / `120` across `3` folders" in doc_text
    assert "- Signal calibration accuracy: `100.0%` [96.9%, 100.0%]" in doc_text
    assert "- Counterfactual prompt invariance: `100.0%` [98.9%, 100.0%] (`360` swap checks)" in doc_text

    sec3_rows = sections["3. Persona-Conditioned Live Suspect Interviews (`persona_interviews_suite`)"]
    assert len(sec3_rows) == 5
    exp_tier_n = {"easy": 4, "medium": 3, "hard": 8, "overall": 15}
    for idx, sl_name in enumerate((*TIER_ORDER, "overall"), start=1):
        subset = ordered if sl_name == "overall" else [w for w in ordered if w["tier"] == sl_name]
        assert len(subset) == exp_tier_n[sl_name]
        ps_vals = [w["ps_score"] for w in subset]
        ts_vals = [w["ts_score"] for w in subset]
        d_vals = [w["delta"] for w in subset]
        ok_k = sum(1 for w in subset if w["ps_correct"])

        ps_mean, ps_ci = _mean4(ps_vals), _bootstrap_mean_ci95_ref(ps_vals)
        ts_mean, ts_ci = _mean4(ts_vals), _bootstrap_mean_ci95_ref(ts_vals)
        d_mean, d_ci = _mean4(d_vals), _bootstrap_mean_ci95_ref(d_vals)
        acc = round(ok_k / len(subset), 4)

        assert suite_json["persona_interviews_suite"]["by_tier"][sl_name] == {
            "n_worlds": len(subset),
            "persona_solver_mean": ps_mean,
            "persona_solver_ci95": ps_ci,
            "persona_solver_accuracy": acc,
            "persona_solver_accuracy_ci95": _wilson_ci95_ref(ok_k, len(subset)),
            "template_solver_mean": ts_mean,
            "template_solver_ci95": ts_ci,
            "paired_delta_mean": d_mean,
            "paired_delta_ci95": d_ci,
        }
        assert sec3_rows[idx] == [
            f"`{sl_name}`",
            str(len(subset)),
            f"{ps_mean:+.4f} [{ps_ci[0]:+.4f}, {ps_ci[1]:+.4f}]",
            f"{ts_mean:+.4f} [{ts_ci[0]:+.4f}, {ts_ci[1]:+.4f}]",
            f"{d_mean:+.4f} [{d_ci[0]:+.4f}, {d_ci[1]:+.4f}]",
            f"{acc * 100:.1f}%",
        ]


def test_dynamic_events_and_thinking_calibration_table_rows_match_underlying_json():
    all_runs = _raw_verified_runs()
    ev_runs = [r for r in all_runs if r["subrole"] == "dynamic_mid_episode_events"]
    tc_runs = [r for r in all_runs if r["subrole"] == "thinking_level_calibration"]
    assert len(ev_runs) == 3
    assert len(tc_runs) == 1

    dedup_ev: dict[tuple[str, int], dict[str, Any]] = {}
    total_events = 0
    for item in ev_runs:
        tier = str(item["meta"]["tier"])
        total_events += int(item["meta"]["n_events_generated"])
        for ps in item["summary"]["solver_parity"]["per_seed"]:
            key = (tier, int(ps["seed"]))
            assert key not in dedup_ev, f"duplicate dynamic_events seed {key}"
            ls = ps["live_events_solver"]
            bs = ps["baseline_solver"]
            lo = ps["live_events_obvious_heuristic"]
            dedup_ev[key] = {
                "tier": tier,
                "seed": key[1],
                "live_score": float(ls["score"]),
                "live_correct": bool(ls["correct"]),
                "base_score": float(bs["score"]),
                "obvious_score": float(lo["score"]),
                "delta": round(float(ls["score"]) - float(bs["score"]), 6),
            }

    assert total_events == 33
    ordered_ev = sorted(dedup_ev.values(), key=lambda r: (TIER_RANK[r["tier"]], r["seed"]))
    assert len(ordered_ev) == 11

    suite_json = _read_json(SUITE_DIR / "summary.json")
    sections = _parse_markdown_sections_and_tables(DOC_PATH.read_text(encoding="utf-8"))
    sec4_rows = sections["4. Dynamic Mid-Episode Corporate Incident Events (`dynamic_events_suite`)"]
    assert len(sec4_rows) == 4
    exp_ev_n = {"medium": 3, "hard": 8, "overall": 11}
    for idx, sl_name in enumerate(("medium", "hard", "overall"), start=1):
        subset = ordered_ev if sl_name == "overall" else [r for r in ordered_ev if r["tier"] == sl_name]
        assert len(subset) == exp_ev_n[sl_name]
        l_vals = [r["live_score"] for r in subset]
        b_vals = [r["base_score"] for r in subset]
        d_vals = [r["delta"] for r in subset]
        o_vals = [r["obvious_score"] for r in subset]
        ok_k = sum(1 for r in subset if r["live_correct"])

        l_mean, l_ci = _mean4(l_vals), _bootstrap_mean_ci95_ref(l_vals)
        b_mean, b_ci = _mean4(b_vals), _bootstrap_mean_ci95_ref(b_vals)
        d_mean, d_ci = _mean4(d_vals), _bootstrap_mean_ci95_ref(d_vals)
        acc = round(ok_k / len(subset), 4)
        o_mean = _mean4(o_vals)

        assert suite_json["dynamic_events_suite"]["by_tier"][sl_name] == {
            "n_worlds": len(subset),
            "live_solver_mean": l_mean,
            "live_solver_ci95": l_ci,
            "live_solver_accuracy": acc,
            "live_solver_accuracy_ci95": _wilson_ci95_ref(ok_k, len(subset)),
            "baseline_solver_mean": b_mean,
            "baseline_solver_ci95": b_ci,
            "paired_delta_mean": d_mean,
            "paired_delta_ci95": d_ci,
            "obvious_heuristic_mean": o_mean,
        }
        assert sec4_rows[idx] == [
            f"`{sl_name}`",
            str(len(subset)),
            f"{l_mean:+.4f} [{l_ci[0]:+.4f}, {l_ci[1]:+.4f}]",
            f"{b_mean:+.4f} [{b_ci[0]:+.4f}, {b_ci[1]:+.4f}]",
            f"{d_mean:+.4f} [{d_ci[0]:+.4f}, {d_ci[1]:+.4f}]",
            f"{acc * 100:.1f}%",
            f"{o_mean:+.4f}",
        ]

    tc_item = tc_runs[0]
    tc_summary = tc_item["summary"]
    levels_raw = tc_summary["levels_summary"]
    n_seeds = len(tc_summary["seeds"])
    assert n_seeds == 2
    assert sum(int(levels_raw[lvl]["thinking_tokens"]) for lvl in THINKING_ORDER) == tc_item["usage"]["thinking"]
    assert sum(int(levels_raw[lvl]["output_tokens"]) for lvl in THINKING_ORDER) == tc_item["usage"]["out"]
    assert round(sum(float(levels_raw[lvl]["cost_usd"]) for lvl in THINKING_ORDER), 6) == tc_item["usage"]["cost_usd"]

    sec5_rows = sections["5. Thinking-Level World Synthesis Calibration (`thinking_calibration_suite`)"]
    assert len(sec5_rows) == 4
    for idx, lvl in enumerate(THINKING_ORDER, start=1):
        raw_lvl = levels_raw[lvl]
        per_seed_scores = [
            float(ps["levels"][lvl]["score"])
            for ps in tc_summary["solver_parity"]["per_seed"]
        ]
        assert _mean4(per_seed_scores) == round(float(raw_lvl["solver_mean_score"]), 4)
        think_tok = int(raw_lvl["thinking_tokens"])
        out_tok = int(raw_lvl["output_tokens"])
        bigrams = float(raw_lvl["distinct_bigrams"])
        cost_usd = round(float(raw_lvl["cost_usd"]), 6)

        assert suite_json["thinking_calibration_suite"]["levels"][lvl] == {
            "n_worlds": n_seeds,
            "thinking_tokens": think_tok,
            "thinking_tokens_per_world": round(think_tok / n_seeds, 1),
            "output_tokens": out_tok,
            "mean_distinct_bigrams": round(bigrams, 1),
            "solver_mean_score": _mean4(per_seed_scores),
            "cost_usd": cost_usd,
        }
        assert sec5_rows[idx] == [
            f"`{lvl}`",
            str(n_seeds),
            f"{think_tok:,}",
            f"{think_tok / n_seeds:,.1f}",
            f"{out_tok:,}",
            f"{bigrams:,.1f}",
            f"{_mean4(per_seed_scores):+.4f}",
            f"${cost_usd:.4f}",
        ]


def test_wilson_bootstrap_binomial_37_encoding_and_prompt_invariance_audit():
    suite_json = _read_json(SUITE_DIR / "summary.json")
    audit_json = _read_json(SUITE_DIR / "audit.json")
    doc_text = DOC_PATH.read_text(encoding="utf-8")

    assert len(wc.SUPPORTED_ENCODINGS) == 37
    pa = audit_json["v14_multi_tier_parity_and_probe_audit"]
    le = pa["leak_encodings"]
    nl = pa["non_leak"]
    assert le["n_supported_encodings"] == 37
    assert le["n_violations"] == 0
    assert le["n_worlds_scanned"] == 24
    assert le["n_personas_scanned"] == 648
    assert pa["n_worlds"] == 24
    assert pa["n_personas_total"] == 648
    assert nl["n_messages_checked"] == 2791
    assert nl["n_interviews_checked"] == 5184
    assert nl["n_truth_violations"] == 0
    assert nl["n_lint_violations"] == 0
    assert nl["n_leak_encoding_violations"] == 0
    assert nl["text_leak_any"] is False

    tier_msgs = sum(int(pa["by_tier"][t]["non_leak"]["n_messages_checked"]) for t in TIER_ORDER)
    tier_ivs = sum(int(pa["by_tier"][t]["non_leak"]["n_interviews_checked"]) for t in TIER_ORDER)
    tier_worlds = sum(int(pa["by_tier"][t]["n_worlds"]) for t in TIER_ORDER)
    tier_personas = sum(int(pa["by_tier"][t]["n_personas"]) for t in TIER_ORDER)
    assert (tier_worlds, tier_personas, tier_msgs, tier_ivs) == (24, 648, 2791, 5184)
    assert (
        "- Encodings scanned: `37` (`0` violations across `24` worlds, `648` personas, "
        "`2,791` messages, `5,184` interviews)"
    ) in doc_text

    for tier_name, exp_k, exp_n, exp_bar, exp_chance, exp_p_bar, exp_p_chance, exp_digits in (
        ("easy", 0, 4, 0.170325, 0.083333, 1.0, 1.0, 4),
        ("medium", 1, 10, 0.073724, 0.05, 0.535052, 0.401263, 6),
        ("hard", 0, 10, 0.034535, 0.025, 1.0, 1.0, 6),
    ):
        probe = pa["by_tier"][tier_name]["non_leak"]["text_probe"]
        assert probe["correct"] == exp_k and probe["n"] == exp_n
        assert probe["fair_bar"] == exp_bar and probe["chance"] == exp_chance
        assert _binomial_upper_tail_ref(exp_k, exp_n, exp_bar) == exp_p_bar
        assert _binomial_upper_tail_ref(exp_k, exp_n, exp_chance) == exp_p_chance
        assert probe["p_value_vs_bar"] == exp_p_bar
        assert probe["p_value_vs_chance"] == exp_p_chance
        assert probe["p_value_vs_bar"] >= probe["alpha"] == 0.01
        assert probe["text_leak"] is False
        assert probe["ci95"] == _wilson_ci95_ref(exp_k, exp_n, digits=exp_digits, z=1.96)

    dyn_probe = audit_json["dynamic_events_hard37_probe"]
    assert _binomial_upper_tail_ref(dyn_probe["correct"], dyn_probe["n"], dyn_probe["fair_bar"]) == dyn_probe["p_value_vs_bar"] == 1.0
    assert dyn_probe["text_leak"] is False
    assert dyn_probe["ci95"] == _wilson_ci95_ref(dyn_probe["correct"], dyn_probe["n"], digits=6, z=1.96)

    for suite_key, mean_ci_pairs in (
        ("company_personas_suite", (("solver_mean", "solver_ci95"), ("template_mean", "template_ci95"), ("paired_delta_mean", "paired_delta_ci95"))),
        ("persona_interviews_suite", (("persona_solver_mean", "persona_solver_ci95"), ("template_solver_mean", "template_solver_ci95"), ("paired_delta_mean", "paired_delta_ci95"))),
        ("dynamic_events_suite", (("live_solver_mean", "live_solver_ci95"), ("baseline_solver_mean", "baseline_solver_ci95"), ("paired_delta_mean", "paired_delta_ci95"))),
    ):
        for tier_row in suite_json[suite_key]["by_tier"].values():
            for m_key, ci_key in mean_ci_pairs:
                lo, hi = tier_row[ci_key]
                assert lo <= tier_row[m_key] <= hi

    iv_suite = suite_json["persona_interviews_suite"]
    iv_audit = audit_json["persona_interviews_audit"]
    assert iv_suite["counterfactual_checks_total"] == 360
    assert iv_audit["counterfactual_checks"] == 360
    assert iv_suite["counterfactual_invariance_rate"] == 1.0
    assert iv_audit["counterfactual_invariance_rate"] == 1.0
    assert iv_suite["counterfactual_invariance_ci95"] == _wilson_ci95_ref(360, 360) == [0.9894, 1.0]
    assert iv_suite["signal_calibration_ci95"] == _wilson_ci95_ref(120, 120) == [0.969, 1.0]

    for tier_name, alt_mole, alt_decoys in (
        ("easy", "e07", ["e02", "e09"]),
        ("medium", "e16", ["e03", "e12"]),
        ("hard", "e33", ["e05", "e21", "e38"]),
    ):
        env = Env(tier=tier_name, seed=0)
        facts = env._facts(env.day)
        payload_a = {
            "company": facts.company,
            "tier": tier_name,
            "employees": facts.employees,
            "docs": facts.docs,
            "mole": "e01",
            "decoys": ["e04"],
            "mole_strategy": "patient",
            "ledger": [{"doc": "d0", "to": "corvid"}],
        }
        payload_b = {
            **payload_a,
            "mole": alt_mole,
            "decoys": alt_decoys,
            "mole_strategy": "opportunistic",
            "ledger": [{"doc": "d3", "to": "kestrel"}],
        }
        inv = wc.verify_public_prompt_invariance(payload_a, payload_b)
        assert inv["ok"] is True
        assert inv["invariant"] is True
        assert inv["leaked_truth_keys"] == []
        assert inv["truth_word_hits"] is False
        assert inv["lint_errors"] == []
        pub = public_view(payload_a)
        for tk in TRUTH_KEYS:
            assert tk not in pub

    expected_sync = wc.consolidate_carbon_worldtext(role_dir=ROLE_DIR, doc_path=DOC_PATH, write_files=False)
    assert expected_sync["suite"] == suite_json
    assert expected_sync["audit"] == audit_json
    assert expected_sync["role_doc_md"] == doc_text
    assert expected_sync["suite_md"] == (SUITE_DIR / "summary.md").read_text(encoding="utf-8")


def test_hostile_tamper_detection_on_synthetic_mutations(tmp_path):
    prefixes = _load_protected_prefixes()
    assert _matches_protected_path("canary/env.py", prefixes) is True
    assert _matches_protected_path("canary/solver/policy.py", prefixes) is True
    assert _matches_protected_path("data/runs/committed/v1.4/run/episodes.jsonl", prefixes) is True
    assert _matches_protected_path("results/judge_table.md", prefixes) is True
    assert _matches_protected_path("tests/test_gemini_lab_worldtext_repro_audit.py", prefixes) is False

    clone_role = tmp_path / "world_text"
    clone_doc = tmp_path / "world_text.md"
    shutil.copytree(ROLE_DIR, clone_role)
    shutil.copy2(DOC_PATH, clone_doc)
    assert wc.validate_carbon_worldtext_bundle(clone_role, clone_doc)["ok"] is True

    target_meta_path = clone_role / "biased-chatter-carbon" / "meta.json"
    orig_meta_txt = target_meta_path.read_text(encoding="utf-8")
    tampered_meta = json.loads(orig_meta_path_txt := orig_meta_txt)
    tampered_meta["usage"]["cost_usd"] = round(tampered_meta["usage"]["cost_usd"] + 0.01, 6)
    target_meta_path.write_text(json.dumps(tampered_meta, indent=2), encoding="utf-8")
    res_cost = wc.validate_carbon_worldtext_bundle(clone_role, clone_doc)
    assert res_cost["ok"] is False
    assert any("totals mismatch" in e or "out of sync" in e for e in res_cost["errors"])
    target_meta_path.write_text(orig_meta_path_txt, encoding="utf-8")

    orig_doc_txt = clone_doc.read_text(encoding="utf-8")
    clone_doc.write_text(orig_doc_txt + "\nForbidden dash: " + chr(0x2014) + "\n", encoding="utf-8")
    res_dash = wc.validate_carbon_worldtext_bundle(clone_role, clone_doc)
    assert res_dash["ok"] is False
    assert any("forbidden dash" in e for e in res_dash["errors"])

    fake_key = "AI" + "za" + "SySyntheticAuditProbeKey123456"
    clone_doc.write_text(orig_doc_txt + f"\nLeak: {fake_key}\n", encoding="utf-8")
    res_key = wc.validate_carbon_worldtext_bundle(clone_role, clone_doc)
    assert res_key["ok"] is False
    assert any("secret pattern" in e for e in res_key["errors"])
    clone_doc.write_text(orig_doc_txt, encoding="utf-8")

