from __future__ import annotations

import argparse
import gzip
import json
import math
import random
import re
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

HASH_CHAR = chr(35)
H1 = HASH_CHAR + " "
H2 = HASH_CHAR * 2 + " "
H3 = HASH_CHAR * 3 + " "

FLOAT_TOL = 1e-9
MANIFEST_MAX_BYTES = 60 * 1024
DEFAULT_MANIFEST_REL = "results/eval_v14/claims_manifest.json"
DEFAULT_REPORT_REL = "docs/reports/eval_claims_verification.md"

FRONTIER_V14_RUNS: tuple[tuple[str, str, str], ...] = (
    ("v1.4/opencode-gemini-4-carbon/medium", "medium", "opencode:google/gemini-4-carbon"),
    ("v1.4/opencode-gemini-4-carbon/hard", "hard", "opencode:google/gemini-4-carbon"),
    ("v1.4/inproc-gemini-4-carbon/medium", "medium", "gemini:gemini-4-carbon"),
    ("v1.4/inproc-gemini-4-carbon/hard", "hard", "gemini:gemini-4-carbon"),
    ("v1.4/opencode-gemini-3.5-flash/hard", "hard", "opencode:google/gemini-3.5-flash"),
)

SOLVER_HARD_V14_SUBDIRS: tuple[str, ...] = (
    "solver-hard-20261114-121126",
    "solver-hard-seeds20to29",
    "solver-hard-seeds30to59",
)

SOLVER_MEDIUM_V14_SUBDIRS: tuple[str, ...] = (
    "solver-medium-20261114-121126",
    "solver-medium-seeds20to29",
)

EXPECTED_HEADLINE_RATIOS_0_29: dict[str, tuple[str, str]] = {
    "opencode_gemini_4_carbon_hard": ("65% [24%, 98%]", "72% [52%, 91%]"),
    "opencode_gemini_4_carbon_medium": ("111% [99%, 127%]", "101% [85%, 119%]"),
    "inproc_gemini_4_carbon_hard": ("95% [62%, 140%]", "84% [65%, 106%]"),
    "inproc_gemini_4_carbon_medium": ("82% [56%, 108%]", "74% [52%, 99%]"),
    "opencode_gemini_3_5_flash_hard": ("75% [36%, 123%]", "22% [-23%, 63%]"),
}

ACTIVE_DOCS: tuple[str, ...] = (
    "README.md",
    "docs/DEMO.md",
    "docs/DIFFICULTY.md",
    "docs/EXPLOITS.md",
    "docs/reports/gap.md",
    "results/judge_table.md",
)

STALE_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("frontier_gap_not_established", re.compile(r"frontier gap(?:\s+is|\s*:)?\s+not established", re.IGNORECASE)),
    ("superseded_60_ci", re.compile(r"60%\s*\[\s*1%?\s*,\s*103%?\s*\]")),
    ("superseded_68_ci", re.compile(r"68%\s*\[\s*43%?\s*,\s*91%?\s*\]")),
)

SECRET_AND_LEAK_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("google_api_key", re.compile(r"AIza[0-9A-Za-z_\-]{20,}")),
    ("sk_api_key", re.compile(r"\bsk-(?:proj-|ant-)?[A-Za-z0-9_\-]{20,}\b")),
    ("google_oauth_token", re.compile(r"\bya29\.[0-9A-Za-z_\-]{20,}")),
    ("provider_token", re.compile(r"\b(?:xai-[A-Za-z0-9_\-]{20,}|hf_[A-Za-z0-9]{20,}|ghp_[A-Za-z0-9]{20,})\b")),
    ("private_key_pem", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")),
    (
        "secret_env_assignment",
        re.compile(
            r"\b(?:"
            r"(?:GEMINI_API_KEY|GOOGLE_API_KEY|GOOGLE_GENERATIVE_AI_API_KEY|"
            r"OPENAI_API_KEY|ANTHROPIC_API_KEY|CANARY_LEDGER_TOKEN|"
            r"CANARY_ADMIN_TOKEN|XAI_API_KEY|HF_TOKEN)\s*=\s*[\x27\x22]?[A-Za-z0-9_\-]{16,}"
            r"|CANARY_WORLD_SECRET\s*=\s*[\x27\x22]?(?!canary-demo-live(?![A-Za-z0-9_\-]))[A-Za-z0-9_\-]{16,}"
            r")"
        ),
    ),
    ("world_mole_dump", re.compile(r'"(?:mole|mole_id|true_mole)"\s*:\s*"e\d{2}"')),
)


@dataclass
class GateResult:
    gate: str
    passed: bool
    summary: str
    violations: list[str] = field(default_factory=list)
    warnings: list[dict[str, Any]] = field(default_factory=list)
    data: dict[str, Any] = field(default_factory=dict)


def _norm_ascii(text: str) -> str:
    return (
        text.replace("\u2013", "-")
        .replace("\u2014", "--")
        .replace("\u2212", "-")
        .replace("\u00b1", "+/-")
    )


def _is_finite_number(val: Any) -> bool:
    return isinstance(val, (int, float)) and not isinstance(val, bool) and math.isfinite(float(val))


def _clean_json_value(obj: Any) -> Any:
    if isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            return None
        return round(obj, 12)
    if isinstance(obj, str):
        return _norm_ascii(obj)
    if isinstance(obj, dict):
        return {str(k): _clean_json_value(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_clean_json_value(v) for v in obj]
    return obj


def approx_equal(a: Any, b: Any, tol: float = FLOAT_TOL) -> bool:
    if isinstance(a, bool) or isinstance(b, bool):
        return a is b
    if isinstance(a, int) and isinstance(b, int):
        return a == b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        fa, fb = float(a), float(b)
        if not (math.isfinite(fa) and math.isfinite(fb)):
            return False
        return math.isclose(fa, fb, rel_tol=tol, abs_tol=tol)
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(approx_equal(a[k], b[k], tol) for k in a)
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(approx_equal(x, y, tol) for x, y in zip(a, b))
    return a == b


def _check_score_invariants(ep: dict[str, Any], loc: str, is_invalid: bool) -> list[str]:
    errs: list[str] = []
    raw_score = ep.get("score")
    if not _is_finite_number(raw_score):
        return [f"{loc}: non-finite score {raw_score!r}"]
    score = float(raw_score)
    if not (-1.0 <= score <= 1.0):
        errs.append(f"{loc}: score {score} outside [-1.0, 1.0]")
    if is_invalid:
        return errs

    accused = ep.get("accused")
    has_accused = isinstance(accused, str) and bool(accused.strip())
    if accused is not None and not has_accused:
        errs.append(f"{loc}: malformed accused value {accused!r}")
    correct = bool(ep.get("correct"))
    raw_meta = ep.get("meta")
    meta = raw_meta if isinstance(raw_meta, dict) else None

    if score > 0.0 and not (has_accused and correct):
        errs.append(f"{loc}: score={score} > 0 requires accused and correct=True")
    if has_accused and correct:
        if score < 0.0:
            errs.append(f"{loc}: accused and correct=True cannot have score < 0.0, got {score}")
        elif score == 0.0 and meta is not None and "V" in meta:
            v_val = meta.get("V")
            if not (_is_finite_number(v_val) and float(v_val) == 0.0):
                errs.append(
                    f"{loc}: accused and correct=True with score == 0.0 contradicts meta V={v_val!r}"
                )
    if not has_accused:
        if score != 0.0:
            errs.append(f"{loc}: no accusation requires score == 0.0, got {score}")
        if correct:
            errs.append(f"{loc}: no accusation cannot have correct=True")
    if has_accused and not correct and score != -1.0:
        errs.append(f"{loc}: wrong accusation requires score == -1.0, got {score}")
    return errs


def _parse_seed_spec(spec: str) -> list[int]:
    if "-" in spec:
        lo_s, hi_s = spec.split("-", 1)
        lo, hi = int(lo_s), int(hi_s)
        if hi < lo:
            raise ValueError(f"invalid seed range: {spec}")
        return list(range(lo, hi + 1))
    return [int(x.strip()) for x in spec.split(",") if x.strip()]


def _fmt_pct_ci(ratio: float, lo: float, hi: float) -> str:
    return f"{ratio:.0%} [{lo:.0%}, {hi:.0%}]"


def _parse_md_cells(line: str) -> list[str] | None:
    s = line.strip()
    if not (s.startswith("|") and s.endswith("|")):
        return None
    cells = [c.strip() for c in s.strip("|").split("|")]
    if all(re.fullmatch(r":?-+:?", c.replace(" ", "")) for c in cells if c):
        return None
    return cells


def _strip_md_emph(text: str) -> str:
    return _norm_ascii(text).replace("**", "").replace("*", "").strip()


def _parse_judge_table_all_rows(md_text: str) -> list[dict[str, str]]:
    current_tier: str | None = None
    sub_block = ""
    out: list[dict[str, str]] = []
    for raw_line in md_text.splitlines():
        line = raw_line.strip()
        if line.startswith(H2):
            rest = line[len(H2) :].strip().lower()
            current_tier = None
            sub_block = ""
            for t in ("medium", "hard", "easy"):
                if rest == t or rest.startswith(t + " "):
                    current_tier = t
                    break
            continue
        if current_tier is None:
            continue
        low = _norm_ascii(line).lower()
        if low.startswith("paired runs"):
            sub_block = "paired"
            continue
        if low.startswith("reported agent runs: v1.4"):
            sub_block = "reported_v1.4"
            continue
        if low.startswith("history: v1.3"):
            sub_block = "history_v1.3"
            continue
        if low.startswith("history: v1.2"):
            sub_block = "history_v1.2"
            continue
        cells = _parse_md_cells(line)
        if not cells or len(cells) < 11 or cells[0].lower() == "agent":
            continue
        agent, kind, n_s, inv_s, score_ci, acc_s, accused_s = cells[:7]
        out.append(
            {
                "tier": current_tier,
                "block": sub_block or kind,
                "kind": kind,
                "agent": agent,
                "n": n_s,
                "invalid": inv_s,
                "score_ci": _strip_md_emph(score_ci),
                "accuracy": _strip_md_emph(acc_s),
                "accused": _strip_md_emph(accused_s),
                "ratio_solver": _strip_md_emph(cells[8]),
                "note": _norm_ascii(cells[10]),
            }
        )
    return out


def _parse_judge_table_first_rows(md_text: str) -> dict[tuple[str, str, str], dict[str, str]]:
    rows: dict[tuple[str, str, str], dict[str, str]] = {}
    for item in _parse_judge_table_all_rows(md_text):
        key = (item["tier"], item["kind"], item["agent"])
        if key not in rows:
            rows[key] = item
    return rows


def recompute_paired_v14(root: Path, seeds: set[int]) -> list[dict[str, Any]]:
    import paired_gemini
    import paired_v13

    idx_cache: dict[tuple[int, int, int], np.ndarray] = {}

    def _fast_boot_ratio(f: list[float], s: list[float], B: int = 10000, rng_seed: int = 0) -> tuple[float, float]:
        n = len(f)
        key = (n, B, rng_seed)
        if key not in idx_cache:
            rng = random.Random(rng_seed)
            idx_cache[key] = np.array([[rng.randrange(n) for _ in range(n)] for _ in range(B)], dtype=np.intp)
        idx = idx_cache[key]
        fa = np.asarray(f, dtype=np.float64)[idx].sum(axis=1) / n
        sa = np.asarray(s, dtype=np.float64)[idx].sum(axis=1) / n
        mask = sa > 0
        vals = np.sort(fa[mask] / sa[mask])
        return float(vals[int(0.025 * len(vals))]), float(vals[int(0.975 * len(vals)) - 1])

    orig_load = paired_gemini.load_runs
    orig_boot = paired_gemini.boot_ratio
    load_cache: dict[str, list[dict[str, Any]]] = {}

    def _cached_load(d: Path) -> list[dict[str, Any]]:
        k = str(Path(d).resolve())
        if k not in load_cache:
            load_cache[k] = orig_load(d)
        return load_cache[k]

    paired_gemini.load_runs = _cached_load
    paired_gemini.boot_ratio = _fast_boot_ratio
    try:
        return paired_gemini.rows_for(root / "data" / "runs" / "committed", "v1.4", "gemini-4-carbon", set(seeds))
    finally:
        paired_gemini.load_runs = orig_load
        paired_gemini.boot_ratio = orig_boot
        paired_v13._P_CACHE.clear()


def _build_claim_entry(row: dict[str, Any], extra: dict[str, Any] | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {
        "n": int(row["n"]),
        "mean": float(row["mean"]),
        "ci": float(row["ci"]),
        "accuracy": float(row["accuracy"]),
        "accused_rate": float(row["accused_rate"]),
        "p_accused": float(row["p_accused"]),
        "solver_same_seeds": float(row["solver_same_seeds"]),
        "ratio": float(row["ratio"]),
        "ratio_lo": float(row["ratio_lo"]),
        "ratio_hi": float(row["ratio_hi"]),
        "post_expected": float(row["post_expected"]),
        "solver_post_expected": float(row["solver_post_expected"]),
        "post_expected_ratio": float(row["post_expected_ratio"]),
        "post_expected_lo": float(row["post_expected_lo"]),
        "post_expected_hi": float(row["post_expected_hi"]),
        "score_ci": f"{row['mean']:+.3f} +/- {row['ci']:.3f}",
        "raw_ratio_ci": _fmt_pct_ci(row["ratio"], row["ratio_lo"], row["ratio_hi"]),
        "luck_adjusted_ratio_ci": _fmt_pct_ci(
            row["post_expected_ratio"], row["post_expected_lo"], row["post_expected_hi"]
        ),
    }
    if extra:
        out.update(extra)
    return out


def gate1_headline_and_gap_table_numbers(
    root: Path,
    expected_seeds: list[int] | None = None,
) -> GateResult:
    import paired_gemini

    gate_name = "gate1_headline_and_gap_table_numbers"
    seeds_list = list(range(30)) if expected_seeds is None else sorted(expected_seeds)
    violations: list[str] = []
    warnings: list[dict[str, Any]] = []

    committed_json_path = root / "data" / "runs" / "committed" / "v1.4" / "paired_table_gemini.json"
    committed_md_path = root / "data" / "runs" / "committed" / "v1.4" / "paired_table_gemini.md"
    readme_path = root / "README.md"
    gap_path = root / "docs" / "reports" / "gap.md"
    judge_table_path = root / "results" / "judge_table.md"

    for req in (committed_json_path, readme_path, gap_path, judge_table_path):
        if not req.is_file():
            violations.append(f"missing required file: {req.relative_to(root)}")
    if violations:
        return GateResult(gate=gate_name, passed=False, summary="missing required files", violations=violations)

    recomputed = recompute_paired_v14(root, set(seeds_list))
    by_label_tier: dict[tuple[str, str], dict[str, Any]] = {(r["label"], r["tier"]): r for r in recomputed}
    by_agent_tier: dict[tuple[str, str], dict[str, Any]] = {
        (r["agent"], r["tier"]): r for r in recomputed if r["label"] != paired_gemini.ALT_LABEL
    }

    committed_rows = json.loads(committed_json_path.read_text(encoding="utf-8"))
    if not isinstance(committed_rows, list) or not committed_rows:
        violations.append("paired_table_gemini.json is empty or not a list")
        committed_rows = []

    float_fields = (
        "mean",
        "ci",
        "accuracy",
        "accused_rate",
        "p_accused",
        "accuse_day",
        "solver_same_seeds",
        "ratio",
        "ratio_lo",
        "ratio_hi",
        "diff",
        "diff_ci",
        "post_expected",
        "post_expected_ratio",
        "post_expected_lo",
        "post_expected_hi",
        "solver_post_expected",
    )

    if expected_seeds is None:
        for crow in committed_rows:
            key = (crow.get("label", ""), crow.get("tier", ""))
            got = by_label_tier.get(key)
            if got is None:
                violations.append(f"paired_table_gemini.json row {key} missing from recomputed rows_for")
                continue
            for exact_k in ("group", "agent", "n", "seeds", "n_p"):
                if crow.get(exact_k) != got.get(exact_k):
                    violations.append(
                        f"paired_table_gemini.json {key} {exact_k}: committed={crow.get(exact_k)!r} != recomputed={got.get(exact_k)!r}"
                    )
            for fk in float_fields:
                cv, gv = crow.get(fk), got.get(fk)
                c_nan = cv is None or (isinstance(cv, float) and math.isnan(cv))
                g_nan = gv is None or (isinstance(gv, float) and math.isnan(gv))
                if c_nan and g_nan:
                    continue
                if c_nan != g_nan or not approx_equal(float(cv), float(gv), tol=FLOAT_TOL):
                    violations.append(
                        f"paired_table_gemini.json {key} {fk}: committed={cv!r} != recomputed={gv!r}"
                    )

        if committed_md_path.is_file() and committed_rows:
            want_md = _norm_ascii(paired_gemini.to_md(committed_rows, "v1.4", "gemini-4-carbon").strip())
            got_md = _norm_ascii(committed_md_path.read_text(encoding="utf-8").strip())
            if want_md != got_md:
                violations.append("paired_table_gemini.md does not match to_md(paired_table_gemini.json)")

    oc_hard = by_agent_tier.get(("opencode:google/gemini-4-carbon", "hard"))
    oc_med = by_agent_tier.get(("opencode:google/gemini-4-carbon", "medium"))
    ip_hard = by_agent_tier.get(("gemini:gemini-4-carbon", "hard"))
    ip_med = by_agent_tier.get(("gemini:gemini-4-carbon", "medium"))
    flash_hard = by_agent_tier.get(("opencode:google/gemini-3.5-flash", "hard"))
    sol_hard = by_agent_tier.get(("solver", "hard"))
    sol_med = by_agent_tier.get(("solver", "medium"))

    required_cells = {
        "opencode_hard": oc_hard,
        "opencode_medium": oc_med,
        "inproc_hard": ip_hard,
        "inproc_medium": ip_med,
        "solver_hard": sol_hard,
        "solver_medium": sol_med,
    }
    for cname, cval in required_cells.items():
        if cval is None:
            violations.append(f"missing recomputed v1.4 row for {cname}")
    if violations and any(v is None for v in required_cells.values()):
        return GateResult(gate=gate_name, passed=False, summary="missing recomputed rows", violations=violations)

    assert oc_hard and oc_med and ip_hard and ip_med and sol_hard and sol_med

    want_oc_hard_score = f"{oc_hard['mean']:+.3f} +/- {oc_hard['ci']:.3f}"
    want_sol_hard_score = f"{sol_hard['mean']:+.3f} +/- {sol_hard['ci']:.3f}"
    want_sol_med_score = f"{sol_med['mean']:+.3f} +/- {sol_med['ci']:.3f}"
    want_oc_hard_raw = _fmt_pct_ci(oc_hard["ratio"], oc_hard["ratio_lo"], oc_hard["ratio_hi"])
    want_oc_hard_luck = _fmt_pct_ci(
        oc_hard["post_expected_ratio"], oc_hard["post_expected_lo"], oc_hard["post_expected_hi"]
    )
    want_oc_med_raw = _fmt_pct_ci(oc_med["ratio"], oc_med["ratio_lo"], oc_med["ratio_hi"])
    want_oc_med_luck = _fmt_pct_ci(
        oc_med["post_expected_ratio"], oc_med["post_expected_lo"], oc_med["post_expected_hi"]
    )
    want_ip_hard_raw = _fmt_pct_ci(ip_hard["ratio"], ip_hard["ratio_lo"], ip_hard["ratio_hi"])
    want_ip_hard_luck = _fmt_pct_ci(
        ip_hard["post_expected_ratio"], ip_hard["post_expected_lo"], ip_hard["post_expected_hi"]
    )
    want_ip_med_raw = _fmt_pct_ci(ip_med["ratio"], ip_med["ratio_lo"], ip_med["ratio_hi"])
    want_ip_med_luck = _fmt_pct_ci(
        ip_med["post_expected_ratio"], ip_med["post_expected_lo"], ip_med["post_expected_hi"]
    )

    headline_claims: dict[str, dict[str, Any]] = {
        "opencode_gemini_4_carbon_hard": _build_claim_entry(
            oc_hard,
            {"solver_same_seeds_score_ci": want_sol_hard_score},
        ),
        "opencode_gemini_4_carbon_medium": _build_claim_entry(
            oc_med,
            {"solver_same_seeds_score_ci": want_sol_med_score},
        ),
        "inproc_gemini_4_carbon_hard": _build_claim_entry(
            ip_hard,
            {"solver_same_seeds_score_ci": want_sol_hard_score},
        ),
        "inproc_gemini_4_carbon_medium": _build_claim_entry(
            ip_med,
            {"solver_same_seeds_score_ci": want_sol_med_score},
        ),
    }

    judge_rows = _parse_judge_table_first_rows(judge_table_path.read_text(encoding="utf-8"))

    if flash_hard is not None:
        want_flash_score = f"{flash_hard['mean']:+.3f} +/- {flash_hard['ci']:.3f}"
        want_flash_raw = _fmt_pct_ci(flash_hard["ratio"], flash_hard["ratio_lo"], flash_hard["ratio_hi"])
        want_flash_luck = _fmt_pct_ci(
            flash_hard["post_expected_ratio"], flash_hard["post_expected_lo"], flash_hard["post_expected_hi"]
        )
        in_committed_paired = any(
            r.get("agent") == "opencode:google/gemini-3.5-flash" and r.get("tier") == "hard"
            for r in committed_rows
        )
        headline_claims["opencode_gemini_3_5_flash_hard"] = _build_claim_entry(
            flash_hard,
            {
                "solver_same_seeds_score_ci": want_sol_hard_score,
                "in_committed_paired_table": in_committed_paired,
            },
        )
        jt_flash = judge_rows.get(("hard", "reported", "opencode:google/gemini-3.5-flash"))
        jt_ok = (
            jt_flash is not None
            and jt_flash["n"] == str(flash_hard["n"])
            and jt_flash["score_ci"] == want_flash_score
        )
        if not jt_ok:
            violations.append(
                f"results/judge_table.md missing or mismatched reported row for opencode:google/gemini-3.5-flash on hard "
                f"(expected n={flash_hard['n']}, score_ci={want_flash_score!r}, got {jt_flash})"
            )
        if not in_committed_paired:
            warnings.append(
                {
                    "code": "PENDING_PROTECTED_TABLE_REFRESH",
                    "severity": "WARN",
                    "run_dir": "v1.4/opencode-gemini-3.5-flash/hard",
                    "agent": "opencode:google/gemini-3.5-flash",
                    "tier": "hard",
                    "n": int(flash_hard["n"]),
                    "score_ci": want_flash_score,
                    "raw_ratio_ci": want_flash_raw,
                    "luck_adjusted_ratio_ci": want_flash_luck,
                    "judge_table_replayed": jt_ok,
                    "message": (
                        f"opencode-gemini-3.5-flash/hard (n={flash_hard['n']}, raw {want_flash_raw}, "
                        f"luck-adjusted {want_flash_luck}) is committed in data/runs/committed/v1.4/ and replayed "
                        f"in results/judge_table.md ({want_flash_score}), ready for Silas to refresh into "
                        "paired_table_gemini.md and paired_table_gemini.json (protected path)."
                    ),
                }
            )
    elif expected_seeds is None:
        violations.append("missing recomputed v1.4 row for opencode:google/gemini-3.5-flash hard")

    if expected_seeds is None:
        for cohort_key, (exp_raw, exp_luck) in EXPECTED_HEADLINE_RATIOS_0_29.items():
            entry = headline_claims.get(cohort_key)
            if entry is None:
                violations.append(f"missing headline claim cohort {cohort_key}")
                continue
            if entry["raw_ratio_ci"] != exp_raw or entry["luck_adjusted_ratio_ci"] != exp_luck:
                violations.append(
                    f"{cohort_key} ratio mismatch: got ({entry['raw_ratio_ci']}, {entry['luck_adjusted_ratio_ci']}), "
                    f"expected ({exp_raw}, {exp_luck})"
                )

        expected_jt_reported = (
            ("hard", "opencode:google/gemini-4-carbon", int(oc_hard["n"]), want_oc_hard_score),
            ("medium", "opencode:google/gemini-4-carbon", int(oc_med["n"]), f"{oc_med['mean']:+.3f} +/- {oc_med['ci']:.3f}"),
            ("hard", "gemini:gemini-4-carbon", int(ip_hard["n"]), f"{ip_hard['mean']:+.3f} +/- {ip_hard['ci']:.3f}"),
            ("medium", "gemini:gemini-4-carbon", int(ip_med["n"]), f"{ip_med['mean']:+.3f} +/- {ip_med['ci']:.3f}"),
            ("hard", "solver", int(sol_hard["n"]), want_sol_hard_score),
            ("medium", "solver", int(sol_med["n"]), want_sol_med_score),
        )
        for jt_tier, jt_agent, jt_n, jt_score in expected_jt_reported:
            jrow = judge_rows.get((jt_tier, "reported", jt_agent))
            if jrow is None or jrow["n"] != str(jt_n) or jrow["score_ci"] != jt_score:
                violations.append(
                    f"results/judge_table.md reported ({jt_tier}, {jt_agent}) mismatch: "
                    f"expected n={jt_n}, score_ci={jt_score!r}, got {jrow}"
                )

    readme_text = _norm_ascii(readme_path.read_text(encoding="utf-8"))
    claim_match = re.search(
        r"Claim:.*?gemini-4-carbon earns (-?\d+%) of the reference solver's score on Canary's hard tier "
        r"\(95% CI (-?\d+--?\d+%)\)",
        readme_text,
    )
    want_claim_pct = f"{oc_hard['ratio']:.0%}"
    want_claim_ci = f"{oc_hard['ratio_lo']:.0%}".rstrip("%") + "-" + f"{oc_hard['ratio_hi']:.0%}"
    if not claim_match:
        violations.append("README.md missing top-level Claim sentence with hard-tier % and 95% CI")
    elif claim_match.group(1) != want_claim_pct or claim_match.group(2) != want_claim_ci:
        violations.append(
            f"README.md top Claim mismatch: got ({claim_match.group(1)}, {claim_match.group(2)}), "
            f"expected ({want_claim_pct}, {want_claim_ci})"
        )

    honest_match = re.search(
        r"Honest reading\..*?in-process reaches (\d+%\s*\[\s*-?\d+%,\s*-?\d+%\]).*?"
        r"OpenCode reaches (\d+%) on medium",
        readme_text,
        re.DOTALL,
    )
    if honest_match:
        got_ip_hard = re.sub(r"\s+", " ", honest_match.group(1).strip())
        got_oc_med_pct = honest_match.group(2).strip()
        want_oc_med_pct = f"{oc_med['ratio']:.0%}"
        if got_ip_hard != want_ip_hard_raw or got_oc_med_pct != want_oc_med_pct:
            violations.append(
                f"README.md Honest reading mismatch: got ({got_ip_hard!r}, {got_oc_med_pct!r}), "
                f"expected ({want_ip_hard_raw!r}, {want_oc_med_pct!r})"
            )

    repro_match = re.search(r"Gemini row above comes back as ([+-]\d+\.\d+\s*\+/-\s*\d+\.\d+)", readme_text)
    if repro_match and repro_match.group(1) != want_oc_hard_score:
        violations.append(
            f"README.md reproduce Gemini score mismatch: got {repro_match.group(1)!r}, expected {want_oc_hard_score!r}"
        )

    readme_rows: dict[str, list[str]] = {}
    in_result = False
    for raw_line in readme_text.splitlines():
        line = raw_line.strip()
        if line.startswith(H2):
            in_result = line[len(H2) :].strip().lower().startswith("result")
            continue
        if not in_result:
            continue
        cells = _parse_md_cells(line)
        if not cells or len(cells) < 4 or _strip_md_emph(cells[0]).lower() == "agent":
            continue
        readme_rows[_strip_md_emph(cells[0])] = [_strip_md_emph(c) for c in cells[:4]]

    sol_readme = readme_rows.get("reference solver")
    if sol_readme is None:
        violations.append("README.md Result table missing 'reference solver' row")
    elif sol_readme[1] != want_sol_hard_score or sol_readme[2] != "100%" or sol_readme[3] != str(sol_hard["n"]):
        violations.append(
            f"README.md reference solver row mismatch: got {sol_readme[1:]}, "
            f"expected [{want_sol_hard_score!r}, '100%', {str(sol_hard['n'])!r}]"
        )

    gem_readme = next((v for k, v in readme_rows.items() if "gemini-4-carbon" in k and "OpenCode" in k), None)
    if gem_readme is None:
        violations.append("README.md Result table missing 'gemini-4-carbon, OpenCode over MCP' row")
    else:
        want_col2 = f"{want_oc_hard_raw}; luck-adjusted {want_oc_hard_luck}"
        if gem_readme[1] != want_oc_hard_score or gem_readme[2] != want_col2 or gem_readme[3] != str(oc_hard["n"]):
            violations.append(
                f"README.md gemini-4-carbon OpenCode row mismatch: got {gem_readme[1:]}, "
                f"expected [{want_oc_hard_score!r}, {want_col2!r}, {str(oc_hard['n'])!r}]"
            )

    gap_text = _norm_ascii(gap_path.read_text(encoding="utf-8"))
    gap_v14_lines: list[str] = []
    in_v14 = False
    for raw_line in gap_text.splitlines():
        line = raw_line.strip()
        if line.startswith(H2):
            if "v1.4 headline" in line.lower():
                in_v14 = True
                continue
            if in_v14:
                break
        if in_v14:
            gap_v14_lines.append(line)

    if not gap_v14_lines:
        violations.append("docs/reports/gap.md missing 'v1.4 headline' section")
    else:
        gap_table: dict[tuple[str, str], tuple[str, str, str]] = {}
        for line in gap_v14_lines:
            cells = _parse_md_cells(line)
            if not cells or len(cells) < 5:
                continue
            c0 = _strip_md_emph(cells[0]).lower()
            if c0 == "harness":
                continue
            harness_key = "opencode" if "opencode" in c0 else ("inproc" if "in-process" in c0 else c0)
            tier_key = _strip_md_emph(cells[1]).lower()
            gap_table[(harness_key, tier_key)] = (
                _strip_md_emph(cells[2]),
                _strip_md_emph(cells[3]),
                _strip_md_emph(cells[4]),
            )

        expected_gap_cells = {
            ("opencode", "hard"): (str(oc_hard["n"]), want_oc_hard_raw, want_oc_hard_luck),
            ("opencode", "medium"): (str(oc_med["n"]), want_oc_med_raw, want_oc_med_luck),
            ("inproc", "hard"): (str(ip_hard["n"]), want_ip_hard_raw, want_ip_hard_luck),
            ("inproc", "medium"): (str(ip_med["n"]), want_ip_med_raw, want_ip_med_luck),
        }
        for gkey, gwant in expected_gap_cells.items():
            ggot = gap_table.get(gkey)
            if ggot != gwant:
                violations.append(f"docs/reports/gap.md v1.4 table {gkey}: got {ggot}, expected {gwant}")

        v14_blob = "\n".join(gap_v14_lines)
        want_sol_means = f"solver means: hard {sol_hard['mean']:.3f}, medium {sol_med['mean']:.3f}"
        if want_sol_means not in v14_blob:
            violations.append(f"docs/reports/gap.md v1.4 section missing exact '{want_sol_means}'")

    solver_paired_reference = {
        "hard": {
            "n": int(sol_hard["n"]),
            "mean": float(sol_hard["mean"]),
            "ci": float(sol_hard["ci"]),
            "score_ci": want_sol_hard_score,
            "post_expected": float(sol_hard["post_expected"]),
        },
        "medium": {
            "n": int(sol_med["n"]),
            "mean": float(sol_med["mean"]),
            "ci": float(sol_med["ci"]),
            "score_ci": want_sol_med_score,
            "post_expected": float(sol_med["post_expected"]),
        },
    }

    passed = not violations
    summary = (
        f"recomputed {len(recomputed)} v1.4 paired rows (10,000 bootstrap resamples); "
        f"README.md, gap.md, judge_table.md, and {len(committed_rows)} committed JSON rows match ({len(warnings)} WARN)"
        if passed
        else f"{len(violations)} headline/gap-table mismatch(es)"
    )
    return GateResult(
        gate=gate_name,
        passed=passed,
        summary=summary,
        violations=violations,
        warnings=warnings,
        data={
            "paired_headline_claims": headline_claims,
            "solver_paired_reference": solver_paired_reference,
            "committed_paired_rows_verified": len(committed_rows),
        },
    )


def _verify_cohort_episodes(
    cohort_label: str,
    expected_tier: str,
    expected_agent: str,
    ep_files: list[Path],
    root: Path,
    seeds_want: list[int],
    filter_seeds: bool,
    filter_agent: bool,
) -> tuple[dict[str, Any], list[str]]:
    from canary import rules
    from canary.env import Env
    from canary.redteam.anticheat import _canon, _client_only_step, _client_truncated_bytes, _norm_result

    violations: list[str] = []
    seed_set = set(seeds_want)
    valid_eps: list[dict[str, Any]] = []
    n_total = 0
    n_invalid = 0
    bad_valid_err = 0

    for ep_file in ep_files:
        for lineno, line in enumerate(ep_file.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            loc = f"{ep_file.relative_to(root)}:{lineno}"
            try:
                ep = json.loads(line)
            except ValueError as exc:
                violations.append(f"{loc}: invalid JSON ({exc})")
                continue
            if not isinstance(ep, dict):
                violations.append(f"{loc}: episode line is not a JSON object")
                continue
            if filter_agent and (ep.get("agent") != expected_agent or ep.get("tier") != expected_tier):
                continue

            n_total += 1
            meta = ep.get("meta") if isinstance(ep.get("meta"), dict) else {}
            is_invalid = (meta.get("valid") is False) or (ep.get("valid") is False)
            if is_invalid:
                n_invalid += 1
                violations.extend(_check_score_invariants(ep, loc, True))
                continue

            if meta.get("rc") == "timeout" or ep.get("rc") == "timeout" or ep.get("end_reason") == "error":
                bad_valid_err += 1
                violations.append(
                    f"{loc}: DATA RULE violation: rc={meta.get('rc') or ep.get('rc')!r}, "
                    f"end_reason={ep.get('end_reason')!r} marked valid"
                )

            violations.extend(_check_score_invariants(ep, loc, False))
            if ep.get("tier") != expected_tier:
                violations.append(f"{loc}: expected tier {expected_tier!r}, got {ep.get('tier')!r}")
            if ep.get("agent") != expected_agent:
                violations.append(f"{loc}: expected agent {expected_agent!r}, got {ep.get('agent')!r}")
            try:
                seed_val = int(ep["seed"])
            except (KeyError, TypeError, ValueError):
                violations.append(f"{loc}: invalid seed {ep.get('seed')!r}")
                continue
            if filter_seeds and seed_val not in seed_set:
                continue
            valid_eps.append(ep)

    raw_seeds = [int(e["seed"]) for e in valid_eps]
    seen_seeds: set[int] = set()
    dup_seeds: list[int] = []
    for s in raw_seeds:
        if s in seen_seeds and s not in dup_seeds:
            dup_seeds.append(s)
        seen_seeds.add(s)
    dup_seeds.sort()
    if dup_seeds:
        violations.append(f"{cohort_label}: duplicate valid seed(s) detected: {dup_seeds}")

    got_seeds = sorted(raw_seeds)
    if seeds_want and seeds_want == list(range(seeds_want[0], seeds_want[-1] + 1)):
        want_desc = f"{seeds_want[0]}..{seeds_want[-1]}"
    else:
        want_desc = repr(seeds_want)
    if len(valid_eps) != len(seeds_want) or got_seeds != seeds_want:
        violations.append(
            f"{cohort_label}: expected n={len(seeds_want)} valid episodes on seeds {want_desc}, "
            f"got n={len(valid_eps)} seeds={got_seeds[:5]}..{got_seeds[-5:] if got_seeds else []}"
        )
    if not filter_seeds and set(range(30)) <= set(seeds_want) and not (set(range(30)) <= set(got_seeds)):
        missing_primary = sorted(set(range(30)) - set(got_seeds))
        violations.append(f"{cohort_label}: incomplete primary seeds 0..29 (missing {missing_primary[:10]})")

    replay_matched = 0
    step_mismatches_total = 0
    with rules.tiers_version("v1.4"):
        for ep in sorted(valid_eps, key=lambda x: int(x["seed"])):
            seed_i = int(ep["seed"])
            env = Env(expected_tier, seed_i)
            step_bad = 0
            first_bad: int | None = None
            for step_idx, st in enumerate(ep.get("steps") or []):
                if _client_only_step(st):
                    continue
                r = env.call(st["tool"], st["args"])
                got_payload: dict[str, Any] = {"ok": r.ok, "data": r.data, "error": r.error}
                want = _norm_result(st.get("result"))
                if (
                    not r.ok
                    and r.error == "invalid arguments"
                    and isinstance(r.data, dict)
                    and set(r.data) == {"detail"}
                    and not (isinstance(want, dict) and isinstance(want.get("data"), dict) and "detail" in want["data"])
                ):
                    got_payload = {"ok": r.ok, "data": {}, "error": r.error}
                trunc = _client_truncated_bytes(st.get("result"))
                if trunc is not None:
                    step_ok = len(json.dumps(got_payload).encode()) == trunc
                else:
                    step_ok = want is None or _canon(got_payload) == _canon(want)
                if not step_ok:
                    step_bad += 1
                    if first_bad is None:
                        first_bad = step_idx
            step_mismatches_total += step_bad
            got_score = float(env.score())
            got_accused = env.verdict()["accused"]
            rec_score = float(ep["score"])
            rec_accused = ep.get("accused")
            if abs(got_score - rec_score) < 1e-6 and got_accused == rec_accused and step_bad == 0:
                replay_matched += 1
            else:
                violations.append(
                    f"{cohort_label} seed={seed_i}: replay mismatch recorded=({rec_score}, {rec_accused!r}) "
                    f"replayed=({got_score}, {got_accused!r}) step_mismatches={step_bad} first_bad_step={first_bad}"
                )

    mean_sc = sum(float(e["score"]) for e in valid_eps) / len(valid_eps) if valid_eps else 0.0
    summary_row = {
        "run_dir": cohort_label,
        "tier": expected_tier,
        "agent": expected_agent,
        "n_total": n_total if not filter_seeds else len(valid_eps),
        "n_valid": len(valid_eps),
        "n_invalid": n_invalid,
        "duplicate_seed_count": len(dup_seeds),
        "valid_timeout_or_error": bad_valid_err,
        "seeds_exact_match": got_seeds == seeds_want and not dup_seeds,
        "seed_min": got_seeds[0] if got_seeds else None,
        "seed_max": got_seeds[-1] if got_seeds else None,
        "replay_matched": replay_matched,
        "step_mismatches": step_mismatches_total,
        "replay_agreement_rate": (replay_matched / len(valid_eps)) if valid_eps else 0.0,
        "mean_score": round(mean_sc, 6),
    }
    return summary_row, violations


def gate2_replay_cache_completeness_and_step_consistency(
    root: Path,
    expected_seeds: list[int] | None = None,
    frontier_runs: tuple[tuple[str, str, str], ...] = FRONTIER_V14_RUNS,
) -> GateResult:
    from canary import rules

    gate_name = "gate2_replay_cache_completeness_and_step_consistency"
    seeds_want = list(range(30)) if expected_seeds is None else sorted(expected_seeds)
    filter_seeds = expected_seeds is not None
    violations: list[str] = []

    if rules.TIERS_VERSION != "v1.4":
        msg = f"canary.rules.TIERS_VERSION expected 'v1.4', got {rules.TIERS_VERSION!r}"
        return GateResult(gate=gate_name, passed=False, summary=msg, violations=[msg])

    frontier_summaries: list[dict[str, Any]] = []
    for rel_dir, expected_tier, expected_agent in frontier_runs:
        ep_file = root / "data" / "runs" / "committed" / rel_dir / "episodes.jsonl"
        if not ep_file.is_file():
            violations.append(f"missing committed frontier episodes file: {ep_file.relative_to(root)}")
            continue
        row, errs = _verify_cohort_episodes(
            rel_dir,
            expected_tier,
            expected_agent,
            [ep_file],
            root,
            seeds_want,
            filter_seeds=filter_seeds,
            filter_agent=False,
        )
        frontier_summaries.append(row)
        violations.extend(errs)

    extension_summaries: list[dict[str, Any]] = []
    extension_expected = 0
    if expected_seeds is None:
        ext_rel = "v1.4/opencode-gemini-4-carbon-ext/hard"
        ext_dir = root / "data" / "runs" / "committed" / ext_rel
        ext_ep = ext_dir / "episodes.jsonl"
        ext_meta_file = ext_dir / "meta.json"
        if not ext_ep.is_file() or not ext_meta_file.is_file():
            violations.append(f"missing committed extension cohort files under data/runs/committed/{ext_rel}")
        else:
            ext_md = json.loads(ext_meta_file.read_text(encoding="utf-8"))
            raw_ext_seeds = ext_md.get("seeds")
            if (
                isinstance(raw_ext_seeds, list)
                and raw_ext_seeds
                and all(isinstance(s, int) and not isinstance(s, bool) for s in raw_ext_seeds)
                and raw_ext_seeds == sorted(set(raw_ext_seeds))
                and set(raw_ext_seeds) <= set(range(30, 60))
            ):
                ext_seeds_want = list(raw_ext_seeds)
            else:
                violations.append(
                    f"data/runs/committed/{ext_rel}/meta.json: seeds={raw_ext_seeds!r} must be a non-empty sorted subset of 30..59"
                )
                ext_seeds_want = [34, 37]
            extension_expected += len(ext_seeds_want)
            ext_row, ext_errs = _verify_cohort_episodes(
                ext_rel,
                "hard",
                "opencode:google/gemini-4-carbon",
                [ext_ep],
                root,
                ext_seeds_want,
                filter_seeds=False,
                filter_agent=False,
            )
            extension_summaries.append(ext_row)
            violations.extend(ext_errs)

        gpt_rel = "v1.4/opencode-gpt-5.5/hard"
        gpt_dir = root / "data" / "runs" / "committed" / gpt_rel
        gpt_ep = gpt_dir / "episodes.jsonl"
        gpt_meta_file = gpt_dir / "meta.json"
        if gpt_ep.is_file() and gpt_meta_file.is_file():
            gpt_md = json.loads(gpt_meta_file.read_text(encoding="utf-8"))
            raw_gpt_seeds = gpt_md.get("seeds")
            if (
                isinstance(raw_gpt_seeds, list)
                and raw_gpt_seeds
                and all(isinstance(s, int) and not isinstance(s, bool) for s in raw_gpt_seeds)
                and raw_gpt_seeds == sorted(set(raw_gpt_seeds))
                and set(raw_gpt_seeds) <= set(range(30))
            ):
                gpt_seeds_want = list(raw_gpt_seeds)
            else:
                violations.append(
                    f"data/runs/committed/{gpt_rel}/meta.json: seeds={raw_gpt_seeds!r} must be a non-empty sorted subset of 0..29"
                )
                gpt_seeds_want = list(range(30))
            extension_expected += len(gpt_seeds_want)
            gpt_agent = str(gpt_md.get("agent") or "opencode:openai/gpt-5.5")
            gpt_row, gpt_errs = _verify_cohort_episodes(
                gpt_rel,
                "hard",
                gpt_agent,
                [gpt_ep],
                root,
                gpt_seeds_want,
                filter_seeds=False,
                filter_agent=False,
            )
            extension_summaries.append(gpt_row)
            violations.extend(gpt_errs)

    solver_summaries: list[dict[str, Any]] = []
    solver_expected = 0
    ref_dir = root / "data" / "runs" / "committed" / "v1.4" / "reference"
    if not ref_dir.is_dir():
        violations.append("missing committed solver reference directory: data/runs/committed/v1.4/reference")
    else:
        if expected_seeds is None:
            for req_sub in SOLVER_MEDIUM_V14_SUBDIRS + SOLVER_HARD_V14_SUBDIRS:
                if not (ref_dir / req_sub / "episodes.jsonl").is_file():
                    violations.append(
                        f"missing committed solver reference episodes file: data/runs/committed/v1.4/reference/{req_sub}/episodes.jsonl"
                    )
        ref_ep_files = sorted(ref_dir.rglob("episodes.jsonl"))
        for sol_tier in ("medium", "hard"):
            if expected_seeds is None:
                sol_seeds_want = list(range(60)) if sol_tier == "hard" else list(range(30))
            else:
                sol_seeds_want = seeds_want
            solver_expected += len(sol_seeds_want)
            row, errs = _verify_cohort_episodes(
                f"v1.4/reference/solver:{sol_tier}",
                sol_tier,
                "solver",
                ref_ep_files,
                root,
                sol_seeds_want,
                filter_seeds=filter_seeds,
                filter_agent=True,
            )
            solver_summaries.append(row)
            violations.extend(errs)

    ladder_gz = root / "results" / "gemini" / "ladder_episodes.jsonl.gz"
    ladder_json_path = root / "results" / "gemini" / "ladder.json"
    ladder_valid = 0
    ladder_invalid = 0
    ladder_valid_errors = 0
    ladder_inv_errs = 0
    ladder_scores: list[float] = []

    if ladder_gz.is_file():
        try:
            with gzip.open(ladder_gz, "rt", encoding="utf-8") as fh:
                for lineno, line in enumerate(fh, 1):
                    if not line.strip():
                        continue
                    loc = f"results/gemini/ladder_episodes.jsonl.gz:{lineno}"
                    try:
                        ep = json.loads(line)
                    except ValueError as exc:
                        violations.append(f"{loc}: invalid JSON ({exc})")
                        ladder_inv_errs += 1
                        continue
                    if not isinstance(ep, dict):
                        violations.append(f"{loc}: episode line is not a JSON object")
                        ladder_inv_errs += 1
                        continue
                    meta = ep.get("meta") if isinstance(ep.get("meta"), dict) else {}
                    is_invalid = (meta.get("valid") is False) or (ep.get("valid") is False)
                    inv_errs = _check_score_invariants(ep, loc, is_invalid)
                    if inv_errs:
                        ladder_inv_errs += len(inv_errs)
                        violations.extend(inv_errs)
                    if is_invalid:
                        ladder_invalid += 1
                        continue
                    if meta.get("rc") == "timeout" or ep.get("rc") == "timeout" or ep.get("end_reason") == "error":
                        ladder_valid_errors += 1
                        violations.append(f"{loc}: ladder episode has error/timeout while marked valid")
                    ladder_valid += 1
                    if _is_finite_number(ep.get("score")):
                        ladder_scores.append(float(ep["score"]))
        except OSError as exc:
            violations.append(f"results/gemini/ladder_episodes.jsonl.gz unreadable: {exc}")

        if ladder_valid == 0:
            violations.append("results/gemini/ladder_episodes.jsonl.gz has 0 valid episodes")
    elif expected_seeds is None:
        violations.append("missing results/gemini/ladder_episodes.jsonl.gz")

    imported_valid = 0
    total_ladder_episodes = ladder_valid
    if ladder_json_path.is_file() and ladder_gz.is_file():
        try:
            lj = json.loads(ladder_json_path.read_text(encoding="utf-8"))
            rows_lj = lj.get("rows") or []
            native_from_rows = sum(int(r.get("n", 0)) for r in rows_lj if r.get("source") == "ladder")
            imported_valid = sum(
                int(r.get("n", 0)) for r in rows_lj if str(r.get("source") or "").startswith("import:")
            )
            reported_total = int(lj.get("episodes", 0))
            total_ladder_episodes = ladder_valid + imported_valid
            if ladder_valid != native_from_rows:
                violations.append(
                    f"ladder_episodes.jsonl.gz valid count {ladder_valid} != ladder.json native sum {native_from_rows}"
                )
            if total_ladder_episodes != reported_total:
                violations.append(
                    f"ladder total episodes {total_ladder_episodes} ({ladder_valid} native + {imported_valid} imported) "
                    f"!= ladder.json episodes {reported_total}"
                )
        except (OSError, ValueError, TypeError) as exc:
            violations.append(f"results/gemini/ladder.json parse failure: {exc}")

    ladder_summary = {
        "file": "results/gemini/ladder_episodes.jsonl.gz",
        "present": ladder_gz.is_file(),
        "native_valid_episodes": ladder_valid,
        "native_invalid_episodes": ladder_invalid,
        "imported_inproc_valid_episodes": imported_valid,
        "total_ladder_episodes": total_ladder_episodes,
        "valid_error_or_timeout_episodes": ladder_valid_errors,
        "invariant_violations": ladder_inv_errs,
        "min_score": round(min(ladder_scores), 6) if ladder_scores else None,
        "max_score": round(max(ladder_scores), 6) if ladder_scores else None,
    }

    frontier_replayed = sum(r["replay_matched"] for r in frontier_summaries)
    frontier_expected = len(frontier_runs) * len(seeds_want)
    extension_replayed = sum(r["replay_matched"] for r in extension_summaries)
    solver_replayed = sum(r["replay_matched"] for r in solver_summaries)
    ext_clause = f" + {extension_replayed}/{extension_expected} extension" if extension_summaries else ""
    passed = not violations
    summary = (
        f"replayed {frontier_replayed}/{frontier_expected} primary frontier{ext_clause} + "
        f"{solver_replayed}/{solver_expected} solver v1.4 episodes (0 duplicate seeds, TIERS_VERSION=='v1.4'); "
        f"ladder verified ({total_ladder_episodes} valid, 0 errors)"
        if passed
        else f"{len(violations)} replay/completeness violation(s)"
    )
    return GateResult(
        gate=gate_name,
        passed=passed,
        summary=summary,
        violations=violations,
        data={
            "tiers_version_runtime": rules.TIERS_VERSION,
            "frontier_v14_runs": frontier_summaries,
            "frontier_extension_v14_runs": extension_summaries,
            "solver_v14_runs": solver_summaries,
            "ladder_summary": ladder_summary,
        },
    )


def gate3_baselines_and_judge_spread_bands(root: Path) -> GateResult:
    gate_name = "gate3_baselines_and_judge_spread_bands"
    violations: list[str] = []

    judge_eps_path = root / "results" / "judge_episodes.jsonl"
    judge_table_path = root / "results" / "judge_table.md"
    solver_range_dir = root / "results" / "solver_range"
    oracle_json_path = root / "results" / "oracle_range_v1.4.json"
    readme_path = root / "README.md"

    for req in (judge_eps_path, judge_table_path, oracle_json_path, readme_path):
        if not req.is_file():
            violations.append(f"missing required file: {req.relative_to(root)}")
    if not solver_range_dir.is_dir():
        violations.append("missing required directory: results/solver_range")
    if violations:
        return GateResult(gate=gate_name, passed=False, summary="missing required files", violations=violations)

    judge_by_agent_tier: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for lineno, line in enumerate(judge_eps_path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        loc = f"results/judge_episodes.jsonl:{lineno}"
        try:
            ep = json.loads(line)
        except ValueError as exc:
            violations.append(f"{loc}: invalid JSON ({exc})")
            continue
        if not isinstance(ep, dict):
            violations.append(f"{loc}: line is not a JSON object")
            continue
        violations.extend(_check_score_invariants(ep, loc, False))
        key = (str(ep.get("agent", "")), str(ep.get("tier", "")))
        judge_by_agent_tier.setdefault(key, []).append(ep)

    judge_episode_baselines: dict[str, dict[str, Any]] = {}
    for zagent in ("do_nothing", "stop_early"):
        judge_episode_baselines[zagent] = {}
        for tier in ("easy", "medium", "hard"):
            eps = judge_by_agent_tier.get((zagent, tier), [])
            if not eps:
                violations.append(f"results/judge_episodes.jsonl missing ({zagent}, {tier}) episodes")
                continue
            bad = [
                e for e in eps
                if float(e.get("score", 1.0)) != 0.0 or e.get("accused") is not None or bool(e.get("correct"))
            ]
            if bad:
                violations.append(
                    f"results/judge_episodes.jsonl ({zagent}, {tier}) has {len(bad)} non-zero or accusing episode(s)"
                )
            judge_episode_baselines[zagent][tier] = {
                "n": len(eps),
                "mean": sum(float(e["score"]) for e in eps) / len(eps),
                "max_abs": max(abs(float(e["score"])) for e in eps),
            }

    judge_episode_baselines["guess_day1"] = {}
    for tier in ("easy", "medium", "hard"):
        eps = judge_by_agent_tier.get(("guess_day1", tier), [])
        if not eps:
            violations.append(f"results/judge_episodes.jsonl missing (guess_day1, {tier}) episodes")
            continue
        g_mean = sum(float(e["score"]) for e in eps) / len(eps)
        if not (g_mean < 0.0):
            violations.append(
                f"results/judge_episodes.jsonl (guess_day1, {tier}) mean {g_mean:.4f} is not < 0.0"
            )
        judge_episode_baselines["guess_day1"][tier] = {
            "n": len(eps),
            "mean": round(g_mean, 6),
        }

    jt_rows = _parse_judge_table_first_rows(judge_table_path.read_text(encoding="utf-8"))
    baseline_zeros: dict[str, dict[str, str]] = {}
    for tier in ("easy", "medium", "hard"):
        baseline_zeros[tier] = {}
        for agent in ("do_nothing", "stop_early"):
            row = jt_rows.get((tier, "baseline", agent))
            if row is None:
                violations.append(f"results/judge_table.md missing baseline row for ({tier}, {agent})")
                continue
            baseline_zeros[tier][agent] = row["score_ci"]
            if row["score_ci"] != "+0.000 +/- 0.000":
                violations.append(
                    f"results/judge_table.md ({tier}, {agent}): expected '+0.000 +/- 0.000', got {row['score_ci']!r}"
                )
            if row["accuracy"] != "0.00" or not row["accused"].startswith("0/"):
                violations.append(
                    f"results/judge_table.md ({tier}, {agent}): expected accuracy=0.00 and 0 accusations, "
                    f"got accuracy={row['accuracy']!r}, accused={row['accused']!r}"
                )

    guess_day1_spreads: dict[str, dict[str, Any]] = {}
    solver_spreads: dict[str, dict[str, Any]] = {}
    for tier in ("easy", "medium", "hard"):
        gf = solver_range_dir / f"guess_day1_{tier}_judge40.json"
        if not gf.is_file():
            violations.append(f"missing solver_range file: {gf.relative_to(root)}")
        else:
            gd = json.loads(gf.read_text(encoding="utf-8"))
            g_mean = float(gd.get("mean", 0.0))
            g_max = float(gd.get("max", 0.0))
            g_p95 = float((gd.get("p") or {}).get("0.95", 0.0))
            bmeans = [float(x) for x in (gd.get("build_means") or [])]
            if gd.get("agent") != "guess_day1" or gd.get("tier") != tier:
                violations.append(f"{gf.name}: unexpected agent/tier ({gd.get('agent')!r}, {gd.get('tier')!r})")
            if not (g_mean < 0.0 and g_max < 0.0 and g_p95 < 0.0):
                violations.append(
                    f"{gf.name}: guess_day1 spread not strictly < 0 (mean={g_mean}, p95={g_p95}, max={g_max})"
                )
            if not bmeans or any(x >= 0.0 for x in bmeans):
                violations.append(f"{gf.name}: build_means empty or contains value >= 0.0")
            guess_day1_spreads[tier] = {
                "builds": int(gd.get("builds", 0)),
                "mean": g_mean,
                "sd": float(gd.get("sd", 0.0)),
                "p5": float((gd.get("p") or {}).get("0.05", 0.0)),
                "p95": g_p95,
                "max": g_max,
            }

        sf = solver_range_dir / f"solver_{tier}_judge40.json"
        if not sf.is_file():
            violations.append(f"missing solver_range file: {sf.relative_to(root)}")
        else:
            sd_doc = json.loads(sf.read_text(encoding="utf-8"))
            s_mean = float(sd_doc.get("mean", 0.0))
            s_p5 = float((sd_doc.get("p") or {}).get("0.05", 0.0))
            s_p50 = float((sd_doc.get("p") or {}).get("0.5", 0.0))
            s_p95 = float((sd_doc.get("p") or {}).get("0.95", 0.0))
            if not (0.0 < s_p5 < s_p50 < s_p95 and s_mean > 0.0):
                violations.append(
                    f"{sf.name}: invalid solver spread ordering (p5={s_p5}, p50={s_p50}, p95={s_p95}, mean={s_mean})"
                )
            solver_spreads[tier] = {
                "builds": int(sd_doc.get("builds", 0)),
                "mean": s_mean,
                "sd": float(sd_doc.get("sd", 0.0)),
                "p5": s_p5,
                "p95": s_p95,
            }

    oracle_doc = json.loads(oracle_json_path.read_text(encoding="utf-8"))
    orows = oracle_doc.get("rows") or []
    solver_hard = next((r for r in orows if r.get("agent") == "solver" and r.get("tier") == "hard"), None)
    if solver_hard is None or "k10" not in solver_hard:
        violations.append("results/oracle_range_v1.4.json missing solver hard k10 entry")
        return GateResult(gate=gate_name, passed=False, summary="missing solver hard k10", violations=violations)

    for zero_agent in ("do_nothing", "stop_early"):
        for zero_tier in ("medium", "hard"):
            zr = next((r for r in orows if r.get("agent") == zero_agent and r.get("tier") == zero_tier), None)
            if zr is None:
                violations.append(f"results/oracle_range_v1.4.json missing ({zero_agent}, {zero_tier})")
                continue
            for kname in ("k2", "k3", "k10", "k20"):
                kd = zr.get(kname) or {}
                if kd.get("mean") != 0.0 or kd.get("sd") != 0.0 or kd.get("p5") != 0.0 or kd.get("p95") != 0.0:
                    violations.append(
                        f"results/oracle_range_v1.4.json ({zero_agent}, {zero_tier}, {kname}) not exact zero: {kd}"
                    )

    k10 = solver_hard["k10"]
    k10_p5 = float(k10["p5"])
    k10_p95 = float(k10["p95"])
    k10_mean = float(k10["mean"])
    k10_sd = float(k10["sd"])
    if not (0.0 < k10_p5 < k10_mean < k10_p95 <= 1.0):
        violations.append(
            f"results/oracle_range_v1.4.json solver hard k10 invalid 90% band: p5={k10_p5}, mean={k10_mean}, p95={k10_p95}"
        )

    want_lo = f"{k10_p5:+.2f}"
    want_hi = f"{k10_p95:+.2f}"
    want_mean = f"{k10_mean:+.3f}"
    want_sd = f"{k10_sd:.3f}"

    readme_norm = _norm_ascii(readme_path.read_text(encoding="utf-8"))
    oracle_rx = re.compile(
        r"Oracle expected range:.*?([+-]\d+\.\d+)\s+to\s+([+-]\d+\.\d+).*?"
        r"mean\s+([+-]\d+\.\d+),\s*sd\s+(\d+\.\d+)",
        re.DOTALL,
    )
    m = oracle_rx.search(readme_norm)
    if not m:
        violations.append("README.md missing 'Oracle expected range:' sentence with range, mean, and sd")
    else:
        got_lo, got_hi, got_mean, got_sd = m.group(1), m.group(2), m.group(3), m.group(4)
        if (got_lo, got_hi, got_mean, got_sd) != (want_lo, want_hi, want_mean, want_sd):
            violations.append(
                f"README.md oracle range mismatch: got ({got_lo} to {got_hi}, mean {got_mean}, sd {got_sd}), "
                f"expected ({want_lo} to {want_hi}, mean {want_mean}, sd {want_sd})"
            )

    if "hard" in guess_day1_spreads:
        want_g1_hard = f"{guess_day1_spreads['hard']['mean']:.2f}"
        g1_rx = re.search(r"guess_day1`?\)\s+averages\s+([+-]\d+\.\d+)\s+on\s+hard", readme_norm)
        if g1_rx and g1_rx.group(1) != want_g1_hard:
            violations.append(
                f"README.md guess_day1 hard average mismatch: got {g1_rx.group(1)!r}, expected {want_g1_hard!r}"
            )

    in_result = False
    readme_zero_rows: dict[str, list[str]] = {}
    for raw_line in readme_norm.splitlines():
        line = raw_line.strip()
        if line.startswith(H2):
            in_result = line[len(H2) :].strip().lower().startswith("result")
            continue
        if not in_result:
            continue
        cells = _parse_md_cells(line)
        if not cells or len(cells) < 4:
            continue
        label = _strip_md_emph(cells[0])
        if label.startswith("do_nothing"):
            readme_zero_rows["do_nothing"] = [_strip_md_emph(c) for c in cells[:4]]
        elif label.startswith("stop_early"):
            readme_zero_rows["stop_early"] = [_strip_md_emph(c) for c in cells[:4]]

    for zname in ("do_nothing", "stop_early"):
        zrow = readme_zero_rows.get(zname)
        if zrow is None or zrow[1] != "+0.000 +/- 0.000" or zrow[2] != "0%":
            violations.append(f"README.md Result table {zname} row mismatch: got {zrow}")

    oracle_band = {
        "source": "results/oracle_range_v1.4.json",
        "tier": "hard",
        "k": 10,
        "builds": int(solver_hard.get("builds", 0)),
        "p5_exact": k10_p5,
        "p95_exact": k10_p95,
        "mean_exact": k10_mean,
        "sd_exact": k10_sd,
        "p5": want_lo,
        "p95": want_hi,
        "mean": want_mean,
        "sd": want_sd,
    }
    passed = not violations
    summary = (
        f"do_nothing==0.0 & stop_early==0.0 in judge_episodes.jsonl; "
        f"guess_day1<0 across solver_range (hard mean {guess_day1_spreads.get('hard', {}).get('mean', 0.0):.3f}); "
        f"oracle k10 90% band {want_lo} to {want_hi} matches README.md"
        if passed
        else f"{len(violations)} baseline/spread violation(s)"
    )
    return GateResult(
        gate=gate_name,
        passed=passed,
        summary=summary,
        violations=violations,
        data={
            "judge_episode_baselines": judge_episode_baselines,
            "baseline_zeros": baseline_zeros,
            "guess_day1_spreads": guess_day1_spreads,
            "solver_spreads": solver_spreads,
            "oracle_band": oracle_band,
        },
    )


def _is_allowed_historical_reference(line_norm: str, heading_lower: str) -> bool:
    low = line_norm.lower()
    if re.search(r"\bsuperseded\b", low):
        return True
    quoted_stale_header = '"v1.4 frontier gap: not established' in low or "'v1.4 frontier gap: not established" in low
    if quoted_stale_header and ("known issue" in low or "known issues" in heading_lower):
        if re.search(r"(\bdo not\b|\bstale\b)", low):
            return True
    return False


def _valid_episode_seeds_from_jsonl(ep_path: Path) -> tuple[list[int], list[int], list[str]]:
    seeds: list[int] = []
    dups: list[int] = []
    seen: set[int] = set()
    errs: list[str] = []
    for lineno, line in enumerate(ep_path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            ep = json.loads(line)
        except ValueError as exc:
            errs.append(f"{ep_path.name}:{lineno}: invalid JSON ({exc})")
            continue
        if not isinstance(ep, dict):
            errs.append(f"{ep_path.name}:{lineno}: not a JSON object")
            continue
        meta = ep.get("meta") if isinstance(ep.get("meta"), dict) else {}
        if (meta.get("valid") is False) or (ep.get("valid") is False):
            continue
        try:
            s = int(ep["seed"])
        except (KeyError, TypeError, ValueError):
            errs.append(f"{ep_path.name}:{lineno}: invalid seed {ep.get('seed')!r}")
            continue
        if s in seen and s not in dups:
            dups.append(s)
        seen.add(s)
        seeds.append(s)
    return sorted(seeds), sorted(dups), errs


def gate4_version_and_preregistration_hygiene(
    root: Path,
    doc_paths: tuple[str, ...] = ACTIVE_DOCS,
) -> GateResult:
    gate_name = "gate4_version_and_preregistration_hygiene"
    violations: list[str] = []
    historical_disclosures: list[str] = []
    checked_files: list[str] = []

    v14_dir = root / "data" / "runs" / "committed" / "v1.4"
    paired_json = v14_dir / "paired_table_gemini.json"
    paired_md = v14_dir / "paired_table_gemini.md"
    judge_table_path = root / "results" / "judge_table.md"
    gap_path = root / "docs" / "reports" / "gap.md"
    readme_path = root / "README.md"

    forbidden_tokens = ("v1.2", "v1.3", "superseded")

    paired_groups_checked = 0
    if not paired_json.is_file():
        violations.append("missing data/runs/committed/v1.4/paired_table_gemini.json")
    else:
        rows = json.loads(paired_json.read_text(encoding="utf-8"))
        for idx, row in enumerate(rows):
            paired_groups_checked += 1
            grp = str(row.get("group", ""))
            lbl = _norm_ascii(str(row.get("label", "")))
            if not grp.startswith("v1.4/"):
                violations.append(f"paired_table_gemini.json row[{idx}] non-v1.4 group: {grp!r}")
            for bad_tok in forbidden_tokens:
                if bad_tok in grp.lower() or bad_tok in lbl.lower():
                    violations.append(
                        f"paired_table_gemini.json row[{idx}] mixes {bad_tok!r}: group={grp!r}, label={lbl!r}"
                    )

    if paired_md.is_file():
        pmd_txt = _norm_ascii(paired_md.read_text(encoding="utf-8")).lower()
        for bad_tok in forbidden_tokens:
            if bad_tok in pmd_txt:
                violations.append(f"data/runs/committed/v1.4/paired_table_gemini.md mixes {bad_tok!r}")

    meta_files_checked = 0
    primary_locked_cohorts = 0
    extension_cohorts = 0
    if v14_dir.is_dir():
        for mf in sorted(v14_dir.rglob("meta.json")):
            meta_files_checked += 1
            rel_mf = str(mf.relative_to(root))
            top_dir = mf.relative_to(v14_dir).parts[0]
            md = json.loads(mf.read_text(encoding="utf-8"))
            tv = md.get("tiers_version")
            raw_meta_low = _norm_ascii(json.dumps(md)).lower()
            for bad_tok in forbidden_tokens:
                if bad_tok in rel_mf.lower() or f"/{bad_tok}/" in raw_meta_low:
                    violations.append(f"{rel_mf}: mixes {bad_tok!r}")

            if top_dir == "reference":
                if tv is not None and tv != "v1.4":
                    violations.append(f"{rel_mf}: tiers_version={tv!r} != 'v1.4'")
            elif top_dir in ("opencode-gemini-4-carbon-ext", "opencode-gpt-5.5"):
                if tv != "v1.4":
                    violations.append(f"{rel_mf}: tiers_version={tv!r} != 'v1.4'")
                seeds_meta = md.get("seeds")
                allowed_range = set(range(30, 60)) if top_dir == "opencode-gemini-4-carbon-ext" else set(range(30))
                range_lbl = "30..59" if top_dir == "opencode-gemini-4-carbon-ext" else "0..29"
                meta_seeds_ok = (
                    isinstance(seeds_meta, list)
                    and len(seeds_meta) > 0
                    and all(isinstance(s, int) and not isinstance(s, bool) for s in seeds_meta)
                    and seeds_meta == sorted(set(seeds_meta))
                    and set(seeds_meta) <= allowed_range
                )
                if not meta_seeds_ok:
                    violations.append(
                        f"{rel_mf}: extension seeds={seeds_meta!r} must be a non-empty sorted subset of {range_lbl}"
                    )
                ep_sibling = mf.parent / "episodes.jsonl"
                ep_seeds_ok = True
                if ep_sibling.is_file():
                    ep_seeds, ep_dups, ep_errs = _valid_episode_seeds_from_jsonl(ep_sibling)
                    for e_err in ep_errs:
                        violations.append(f"{rel_mf}: {e_err}")
                    if ep_dups:
                        ep_seeds_ok = False
                        violations.append(f"{rel_mf}: duplicate valid episode seeds in episodes.jsonl: {ep_dups}")
                    if not (set(ep_seeds) <= allowed_range) or (meta_seeds_ok and ep_seeds != seeds_meta):
                        ep_seeds_ok = False
                        violations.append(
                            f"{rel_mf}: episodes.jsonl valid seeds={ep_seeds!r} != meta seeds={seeds_meta!r} (subset of {range_lbl})"
                        )
                if tv == "v1.4" and meta_seeds_ok and ep_seeds_ok:
                    extension_cohorts += 1
            else:
                if tv != "v1.4":
                    violations.append(f"{rel_mf}: tiers_version={tv!r} != 'v1.4'")
                seeds_meta = md.get("seeds")
                if seeds_meta != list(range(30)):
                    violations.append(f"{rel_mf}: primary frontier seeds={seeds_meta!r} != locked 0..29")
                elif tv == "v1.4":
                    primary_locked_cohorts += 1

    jt_v14_rows_checked = 0
    if judge_table_path.is_file():
        all_jt_rows = _parse_judge_table_all_rows(judge_table_path.read_text(encoding="utf-8"))
        for jrow in all_jt_rows:
            note_low = jrow["note"].lower()
            if "superseded" in note_low:
                violations.append(
                    f"results/judge_table.md ({jrow['tier']}, {jrow['block']}, {jrow['agent']}) mixes superseded path: {jrow['note']}"
                )
            if jrow["block"] == "reported_v1.4":
                jt_v14_rows_checked += 1
                if "(data/runs/committed/v1.4/" not in note_low:
                    violations.append(
                        f"results/judge_table.md v1.4 block ({jrow['tier']}, {jrow['agent']}) does not source from v1.4/: {jrow['note']}"
                    )
                for bad_tok in ("v1.2", "v1.3", "superseded"):
                    if f"committed/{bad_tok}" in note_low or f"/{bad_tok}/" in note_low:
                        violations.append(
                            f"results/judge_table.md v1.4 block ({jrow['tier']}, {jrow['agent']}) mixes {bad_tok!r}: {jrow['note']}"
                        )
                if jrow["ratio_solver"] not in ("-", "--", ""):
                    violations.append(
                        f"results/judge_table.md v1.4 reported row ({jrow['tier']}, {jrow['agent']}) must leave / solver blank, got {jrow['ratio_solver']!r}"
                    )

    if readme_path.is_file():
        readme_norm = _norm_ascii(readme_path.read_text(encoding="utf-8"))
        in_res = False
        for lineno, raw_line in enumerate(readme_norm.splitlines(), 1):
            s = raw_line.strip()
            if s.startswith(H2):
                in_res = s[len(H2) :].strip().lower().startswith("result")
                continue
            if not in_res:
                continue
            cells = _parse_md_cells(s)
            if not cells:
                continue
            row_low = " | ".join(cells).lower()
            for bad_tok in forbidden_tokens:
                if bad_tok in row_low:
                    violations.append(f"README.md:{lineno}: Result v1.4 table mixes {bad_tok!r}")

    seed_lock_ok = False
    prereg_ext_ok = False
    if gap_path.is_file():
        gap_norm = _norm_ascii(gap_path.read_text(encoding="utf-8"))
        in_v14 = False
        v14_lines: list[tuple[int, str]] = []
        for lineno, raw_line in enumerate(gap_norm.splitlines(), 1):
            s = raw_line.strip()
            if s.startswith(H2):
                if "v1.4 headline" in s.lower():
                    in_v14 = True
                    continue
                if in_v14:
                    break
            if in_v14:
                v14_lines.append((lineno, s))
        for lineno, s in v14_lines:
            cells = _parse_md_cells(s)
            if cells:
                row_low = " | ".join(cells).lower()
                for bad_tok in forbidden_tokens:
                    if bad_tok in row_low:
                        violations.append(f"docs/reports/gap.md:{lineno}: v1.4 headline table mixes {bad_tok!r}")
        v14_text = "\n".join(s for _, s in v14_lines)
        seed_lock_ok = (
            "Seed lock" in v14_text
            and "671ed96" in v14_text
            and "post-hoc lock" in v14_text.lower()
            and "seeds 0-29" in v14_text
            and "PRIMARY" in v14_text
            and "REPLICATION" in v14_text
        )
        prereg_ext_ok = (
            "Pre-registered extension" in v14_text
            and "f9fb7a4a" in v14_text
            and "30-59" in v14_text
            and "Pre-registered second frontier family: gpt-5.5" in v14_text
        )
        if not seed_lock_ok:
            violations.append(
                "docs/reports/gap.md v1.4 section missing Seed lock (671ed96 post-hoc lock on seeds 0-29, PRIMARY vs REPLICATION)"
            )
        if not prereg_ext_ok:
            violations.append(
                "docs/reports/gap.md v1.4 section missing pre-registered extensions (f9fb7a4a 30-59 and cf394894 gpt-5.5)"
            )

    for rel in doc_paths:
        fp = root / rel
        if not fp.is_file():
            violations.append(f"missing active doc file: {rel}")
            continue
        checked_files.append(rel)
        raw_lines = fp.read_text(encoding="utf-8").splitlines()
        heading_lower = ""

        for lineno, raw_line in enumerate(raw_lines, 1):
            norm_line = _norm_ascii(raw_line)
            stripped = norm_line.strip()
            if stripped.startswith(H1) or stripped.startswith(H2):
                heading_lower = stripped.lstrip(HASH_CHAR).strip().lower()
                if rel == "docs/reports/gap.md" and (
                    "official v1.3" in heading_lower or heading_lower.startswith("history")
                ):
                    break

            for pat_name, rx in STALE_PATTERNS:
                if rx.search(norm_line):
                    if _is_allowed_historical_reference(norm_line, heading_lower):
                        historical_disclosures.append(f"{rel}:{lineno} ({pat_name}: historical/disclosed)")
                    else:
                        violations.append(
                            f"{rel}:{lineno}: active stale claim ({pat_name}): {stripped[:140]}"
                        )

    passed = not violations
    summary = (
        f"0 mixing of v1.2/v1.3/superseded across {paired_groups_checked} paired rows, {jt_v14_rows_checked} judge_table v1.4 rows, "
        f"and {meta_files_checked} v1.4 meta files ({primary_locked_cohorts} locked primary + {extension_cohorts} pre-registered extension); "
        f"seed lock and extensions verified; {len(checked_files)} active docs clean"
        if passed
        else f"{len(violations)} version/pre-registration hygiene violation(s)"
    )
    return GateResult(
        gate=gate_name,
        passed=passed,
        summary=summary,
        violations=violations,
        data={
            "paired_groups_checked": paired_groups_checked,
            "judge_table_v14_rows_checked": jt_v14_rows_checked,
            "v14_meta_files_checked": meta_files_checked,
            "posthoc_locked_primary_frontier_cohorts": primary_locked_cohorts,
            "preregistered_extension_frontier_cohorts": extension_cohorts,
            "preregistered_frontier_cohorts": extension_cohorts,
            "seed_lock_rule_verified": seed_lock_ok,
            "preregistered_extensions_verified": prereg_ext_ok,
            "preregistration_rule_verified": seed_lock_ok and prereg_ext_ok,
            "active_docs_checked": checked_files,
            "historical_disclosures_allowed": historical_disclosures,
        },
    )


def parse_protected_paths_text(text: str) -> list[str]:
    rules_out: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith(HASH_CHAR):
            continue
        rules_out.append(line)
    return rules_out


def match_protected_paths(changed_files: list[str], protected_rules: list[str]) -> list[tuple[str, str]]:
    hits: set[tuple[str, str]] = set()
    for f in changed_files:
        norm_f = f.strip().lstrip("./")
        if not norm_f:
            continue
        for rule in protected_rules:
            if rule.endswith("/"):
                if norm_f.startswith(rule):
                    hits.add((norm_f, rule))
            elif norm_f == rule:
                hits.add((norm_f, rule))
    return sorted(hits)


def _scan_secret_and_mole_hygiene(root: Path) -> tuple[int, list[str]]:
    violations: list[str] = []
    targets: list[Path] = []
    results_dir = root / "results"
    if results_dir.is_dir():
        for entry in sorted(results_dir.glob("eval*")):
            if entry.is_file():
                targets.append(entry)
            elif entry.is_dir():
                targets.extend(sorted(p for p in entry.rglob("*") if p.is_file()))
    reports_dir = root / "docs" / "reports"
    if reports_dir.is_dir():
        targets.extend(sorted(p for p in reports_dir.rglob("*") if p.is_file()))

    salt_bytes: bytes | None = None
    salt_path = root / "data" / "worlds" / "judge" / "SALT"
    if salt_path.is_file():
        raw_salt = salt_path.read_bytes().strip()
        if len(raw_salt) >= 8:
            salt_bytes = raw_salt

    seen_paths: set[Path] = set()
    scanned = 0
    for fp in targets:
        rp = fp.resolve()
        if rp in seen_paths:
            continue
        seen_paths.add(rp)
        scanned += 1
        rel = str(fp.relative_to(root))
        raw = fp.read_bytes()
        if salt_bytes is not None and salt_bytes in raw:
            violations.append(f"{rel}: contains judge SALT bytes")
        text = raw.decode("utf-8", errors="ignore")
        for pat_name, rx in SECRET_AND_LEAK_PATTERNS:
            for m in rx.finditer(text):
                lineno = text.count("\n", 0, m.start()) + 1
                violations.append(f"{rel}:{lineno}: forbidden {pat_name} pattern detected")
                break
    return scanned, violations


def _git_ref_exists(root: Path, ref: str) -> bool:
    if not (root / ".git").exists():
        return False
    proc = subprocess.run(
        ["git", "rev-parse", "--verify", "--quiet", ref],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=10,
    )
    return proc.returncode == 0


def gate5_protected_paths_and_secret_hygiene(
    root: Path,
    base_ref: str | None = None,
    changed_files_override: list[str] | None = None,
) -> GateResult:
    gate_name = "gate5_protected_paths_and_secret_hygiene"
    violations: list[str] = []

    prot_file = root / ".github" / "protected-paths.txt"
    if not prot_file.is_file():
        return GateResult(
            gate=gate_name,
            passed=False,
            summary="missing .github/protected-paths.txt",
            violations=["missing .github/protected-paths.txt"],
        )

    local_rules = parse_protected_paths_text(prot_file.read_text(encoding="utf-8"))
    if not local_rules:
        return GateResult(
            gate=gate_name,
            passed=False,
            summary=".github/protected-paths.txt contains 0 rules",
            violations=[".github/protected-paths.txt contains 0 rules"],
        )

    effective_rules = list(local_rules)
    changed_set: set[str] = set()
    resolved_base = base_ref
    if resolved_base is None and changed_files_override is None and _git_ref_exists(root, "origin/justSilas"):
        resolved_base = "origin/justSilas"

    if changed_files_override is not None:
        changed_set.update(changed_files_override)
    elif resolved_base is not None:
        base_show = subprocess.run(
            ["git", "show", f"{resolved_base}:.github/protected-paths.txt"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=15,
        )
        if base_show.returncode == 0:
            for r in parse_protected_paths_text(base_show.stdout):
                if r not in effective_rules:
                    effective_rules.append(r)

        diff_proc = subprocess.run(
            ["git", "diff", "--name-only", f"{resolved_base}...HEAD"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=15,
        )
        if diff_proc.returncode != 0:
            err_txt = _norm_ascii(diff_proc.stderr.strip() or diff_proc.stdout.strip() or "git diff failed")
            violations.append(f"git diff --name-only {resolved_base}...HEAD failed: {err_txt}")
        else:
            changed_set.update(ln.strip() for ln in diff_proc.stdout.splitlines() if ln.strip())

        wt_proc = subprocess.run(
            ["git", "diff", "--name-only", "HEAD"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=15,
        )
        if wt_proc.returncode == 0:
            changed_set.update(ln.strip() for ln in wt_proc.stdout.splitlines() if ln.strip())

    changed = sorted(changed_set)
    hits = match_protected_paths(changed, effective_rules)
    for fpath, rule in hits:
        violations.append(f"protected path touched: {fpath} (matched rule {rule!r})")

    _, secret_violations = _scan_secret_and_mole_hygiene(root)
    violations.extend(secret_violations)

    passed = not violations
    diff_desc = (
        f"diff against {resolved_base} ({len(changed)} changed file(s))"
        if resolved_base is not None
        else (
            f"override list ({len(changed)} file(s))"
            if changed_files_override is not None
            else f"{len(local_rules)} protected-path rules loaded"
        )
    )
    summary = (
        f"{diff_desc}: 0 protected paths touched; results/eval* and docs/reports/ clean of keys/mole leaks"
        if passed
        else f"{len(violations)} protected-path or secret/mole-leak violation(s)"
    )

    return GateResult(
        gate=gate_name,
        passed=passed,
        summary=summary,
        violations=violations,
        data={
            "protected_path_rules_count": len(local_rules),
            "secret_pattern_rules_count": len(SECRET_AND_LEAK_PATTERNS),
        },
    )


def build_manifest(gates: list[GateResult]) -> dict[str, Any]:
    by_name = {g.gate: g for g in gates}
    g1 = by_name["gate1_headline_and_gap_table_numbers"]
    g2 = by_name["gate2_replay_cache_completeness_and_step_consistency"]
    g3 = by_name["gate3_baselines_and_judge_spread_bands"]
    g4 = by_name["gate4_version_and_preregistration_hygiene"]
    g5 = by_name["gate5_protected_paths_and_secret_hygiene"]

    all_warnings: list[dict[str, Any]] = []
    for g in gates:
        all_warnings.extend(g.warnings)

    manifest = {
        "schema_version": "eval_claims_manifest_v2",
        "tiers_version": "v1.4",
        "float_tolerance": FLOAT_TOL,
        "overall_passed": all(g.passed for g in gates),
        "gates": [
            {
                "gate": g.gate,
                "passed": g.passed,
                "violation_count": len(g.violations),
                "warning_count": len(g.warnings),
            }
            for g in gates
        ],
        "paired_headline_claims": g1.data.get("paired_headline_claims", {}),
        "solver_paired_reference": g1.data.get("solver_paired_reference", {}),
        "committed_paired_rows_verified": g1.data.get("committed_paired_rows_verified", 0),
        "tiers_version_runtime": g2.data.get("tiers_version_runtime", "v1.4"),
        "frontier_v14_runs": g2.data.get("frontier_v14_runs", []),
        "frontier_extension_v14_runs": g2.data.get("frontier_extension_v14_runs", []),
        "solver_v14_runs": g2.data.get("solver_v14_runs", []),
        "ladder_summary": g2.data.get("ladder_summary", {}),
        "judge_episode_baselines": g3.data.get("judge_episode_baselines", {}),
        "baseline_zeros": g3.data.get("baseline_zeros", {}),
        "guess_day1_spreads": g3.data.get("guess_day1_spreads", {}),
        "solver_spreads": g3.data.get("solver_spreads", {}),
        "oracle_band": g3.data.get("oracle_band", {}),
        "version_hygiene": {
            "paired_groups_checked": g4.data.get("paired_groups_checked", 0),
            "judge_table_v14_rows_checked": g4.data.get("judge_table_v14_rows_checked", 0),
            "v14_meta_files_checked": g4.data.get("v14_meta_files_checked", 0),
            "posthoc_locked_primary_frontier_cohorts": g4.data.get("posthoc_locked_primary_frontier_cohorts", 0),
            "preregistered_extension_frontier_cohorts": g4.data.get("preregistered_extension_frontier_cohorts", 0),
            "preregistered_frontier_cohorts": g4.data.get("preregistered_frontier_cohorts", 0),
            "seed_lock_rule_verified": g4.data.get("seed_lock_rule_verified", False),
            "preregistered_extensions_verified": g4.data.get("preregistered_extensions_verified", False),
            "preregistration_rule_verified": g4.data.get("preregistration_rule_verified", False),
            "active_docs_checked": g4.data.get("active_docs_checked", []),
            "historical_disclosures_allowed": g4.data.get("historical_disclosures_allowed", []),
        },
        "protected_path_rules_count": g5.data.get("protected_path_rules_count", 0),
        "secret_pattern_rules_count": g5.data.get("secret_pattern_rules_count", 0),
        "warnings": all_warnings,
    }
    return _clean_json_value(manifest)


def render_report(manifest: dict[str, Any]) -> str:
    claims = manifest.get("paired_headline_claims", {})
    sol_ref = manifest.get("solver_paired_reference", {})
    frontier_runs = manifest.get("frontier_v14_runs", [])
    ext_runs = manifest.get("frontier_extension_v14_runs", [])
    solver_runs = manifest.get("solver_v14_runs", [])
    ladder = manifest.get("ladder_summary", {})
    j_base = manifest.get("judge_episode_baselines", {})
    g1_spreads = manifest.get("guess_day1_spreads", {})
    s_spreads = manifest.get("solver_spreads", {})
    oracle = manifest.get("oracle_band", {})
    vhyg = manifest.get("version_hygiene", {})
    gates = manifest.get("gates", [])
    warnings = manifest.get("warnings", [])

    total_frontier_eps = sum(int(r.get("replay_matched", 0)) for r in frontier_runs)
    total_ext_eps = sum(int(r.get("replay_matched", 0)) for r in ext_runs)
    total_solver_eps = sum(int(r.get("replay_matched", 0)) for r in solver_runs)

    lines: list[str] = [
        H1 + "Canary v1.4 Eval Claims, Replay Cache, and Hygiene Verification",
        "",
        "Every number in this report is deterministically recomputed offline (zero API keys, zero network calls) by `scripts/verify_eval_claims.py` from the committed caches under `data/runs/committed/v1.4/` and `results/`.",
        "",
        H2 + "Reproduce and Verify",
        "",
        "```bash",
        "python scripts/verify_eval_claims.py",
        "python scripts/verify_eval_claims.py --check --diff-base origin/justSilas",
        "pytest -q tests/test_verify_eval_claims.py",
        "```",
        "",
        f"- Schema: `{manifest.get('schema_version')}` (`tiers_version = {manifest.get('tiers_version')}`, float tolerance `{manifest.get('float_tolerance')}`)",
        f"- Overall verdict: **{'PASS' if manifest.get('overall_passed') else 'FAIL'}** ({len(gates)}/5 deterministic gates)",
        "",
        H2 + "Five-Gate Summary",
        "",
        "| gate | status | violations | warnings |",
        "|---|---|---:|---:|",
    ]
    for g in gates:
        st = "PASS" if g.get("passed") else "FAIL"
        lines.append(f"| `{g['gate']}` | **{st}** | {g['violation_count']} | {g['warning_count']} |")

    lines.extend(
        [
            "",
            H2 + "Gate 1: Headline and Gap Table Numbers (Paired Seeds 0-29)",
            "",
            "Recomputed with 10,000 deterministic paired bootstrap resamples (`rng_seed=0`) over seeds 0-29 and cross-checked against `README.md`, `docs/reports/gap.md`, `data/runs/committed/v1.4/paired_table_gemini.json` ("
            + str(manifest.get("committed_paired_rows_verified", 0))
            + " committed rows within `1e-9`), `paired_table_gemini.md`, and `results/judge_table.md`.",
            "",
            "| cohort | n | score +/- 95% CI | solver (same seeds) | frontier / solver [95% CI] | luck-adjusted / solver [95% CI] | mean P(accused) |",
            "|---|---:|---:|---:|---:|---:|---:|",
        ]
    )

    cohort_order = (
        ("opencode_gemini_4_carbon_hard", "opencode-gemini-4-carbon (hard)"),
        ("opencode_gemini_4_carbon_medium", "opencode-gemini-4-carbon (medium)"),
        ("inproc_gemini_4_carbon_hard", "inproc-gemini-4-carbon (hard)"),
        ("inproc_gemini_4_carbon_medium", "inproc-gemini-4-carbon (medium)"),
        ("opencode_gemini_3_5_flash_hard", "opencode-gemini-3.5-flash (hard)"),
    )
    for ckey, clabel in cohort_order:
        c = claims.get(ckey)
        if not c:
            continue
        lines.append(
            f"| {clabel} | {c['n']} | {c['score_ci']} | {c.get('solver_same_seeds_score_ci', '')} | "
            f"{c['raw_ratio_ci']} | {c['luck_adjusted_ratio_ci']} | {c['p_accused']:.2f} |"
        )

    for stier in ("hard", "medium"):
        sr = sol_ref.get(stier)
        if sr:
            lines.append(
                f"| reference solver ({stier}) | {sr['n']} | {sr['score_ci']} | {sr['score_ci']} | "
                f"100% | 100% (EV {sr['post_expected']:+.3f}) | -- |"
            )

    if warnings:
        lines.extend(["", H3 + "Advisory Warnings", ""])
        for w in warnings:
            lines.append(f"- `{w['code']}`: {w['message']}")

    lines.extend(
        [
            "",
            H2 + "Gate 2: Replay Cache Completeness and Step Consistency",
            "",
            f"All **{total_frontier_eps}** primary v1.4 frontier episodes (`0..29` per cohort), **{total_ext_eps}** pre-registered extension episodes (`v1.4/opencode-gemini-4-carbon-ext/hard`, `seeds=[34, 37]`), and **{total_solver_eps}** committed v1.4 solver reference episodes (`solver:medium` `0..29` `n=30`; `solver:hard` `0..59` `n=60` across `0-19`, `20-29`, `30-59`; **{total_frontier_eps + total_ext_eps + total_solver_eps}** total) have complete `0..29` primary seed sets, `0` duplicate seeds per cohort, valid score invariants, `0` timeout/error episodes marked valid, and 100% tool-step and verdict replay agreement in `Env(tier, seed)` under `TIERS_VERSION == \"{manifest.get('tiers_version_runtime')}\"` (including post-`1bc3e281` `data.detail` compatibility on `invalid arguments` steps).",
            "",
            "| cohort | tier | agent | valid | invalid | dup seeds | step mismatches | replay matched | mean score |",
            "|---|---|---|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for r in list(frontier_runs) + list(ext_runs) + list(solver_runs):
        lines.append(
            f"| `{r['run_dir']}` | {r['tier']} | `{r['agent']}` | {r['n_valid']} | {r['n_invalid']} | "
            f"{r['duplicate_seed_count']} | {r.get('step_mismatches', 0)} | {r['replay_matched']}/{r['n_valid']} | {r['mean_score']:+.6f} |"
        )

    if ladder.get("present"):
        lines.extend(
            [
                "",
                f"- Gemini effort ladder (`{ladder['file']}`): {ladder['native_valid_episodes']} native + "
                f"{ladder['imported_inproc_valid_episodes']} imported = {ladder['total_ladder_episodes']} valid episodes, "
                f"{ladder['invariant_violations']} invariant violations, {ladder['valid_error_or_timeout_episodes']} error/timeout leaks.",
            ]
        )

    lines.extend(
        [
            "",
            H2 + "Gate 3: Baselines and Judge Spread Bands",
            "",
            H3 + "Judge Episodes (`results/judge_episodes.jsonl`)",
            "",
            "| baseline | easy | medium | hard |",
            "|---|---:|---:|---:|",
        ]
    )
    for bname in ("do_nothing", "stop_early", "guess_day1"):
        bd = j_base.get(bname, {})
        e_cell = f"{bd['easy']['mean']:+.4f} (n={bd['easy']['n']})" if "easy" in bd else "--"
        m_cell = f"{bd['medium']['mean']:+.4f} (n={bd['medium']['n']})" if "medium" in bd else "--"
        h_cell = f"{bd['hard']['mean']:+.4f} (n={bd['hard']['n']})" if "hard" in bd else "--"
        lines.append(f"| `{bname}` | {e_cell} | {m_cell} | {h_cell} |")

    lines.extend(
        [
            "",
            H3 + "300-Secret Judge Spread (`results/solver_range/`)",
            "",
            "| tier | `guess_day1` mean | `guess_day1` p95 | `guess_day1` max | `solver` mean | `solver` 5th-95th pct |",
            "|---|---:|---:|---:|---:|---:|",
        ]
    )
    for tier in ("easy", "medium", "hard"):
        gd = g1_spreads.get(tier, {})
        sd = s_spreads.get(tier, {})
        if gd and sd:
            lines.append(
                f"| {tier} | {gd['mean']:+.3f} | {gd['p95']:+.2f} | {gd['max']:+.2f} | "
                f"{sd['mean']:+.3f} | [{sd['p5']:+.2f}, {sd['p95']:+.2f}] |"
            )

    if oracle:
        lines.extend(
            [
                "",
                f"- Harbor 10-task hard oracle band (`{oracle['source']}`, {oracle['builds']} builds): "
                f"90% range **{oracle['p5']} to {oracle['p95']}**, mean **{oracle['mean']}**, sd **{oracle['sd']}** "
                "(matches `README.md` exact figures; `do_nothing` and `stop_early` equal `0.0` at `k=2,3,10,20`).",
            ]
        )

    lines.extend(
        [
            "",
            H2 + "Gate 4: Version and Pre-Registration Hygiene",
            "",
            f"- Paired v1.4 rows verified free of `v1.2`, `v1.3`, and `superseded`: **{vhyg.get('paired_groups_checked', 0)}**",
            f"- `results/judge_table.md` v1.4 reported rows verified isolated from earlier tiers and `superseded`: **{vhyg.get('judge_table_v14_rows_checked', 0)}**",
            f"- `data/runs/committed/v1.4/**/meta.json` files verified (`tiers_version == \"v1.4\"`): **{vhyg.get('v14_meta_files_checked', 0)}** ({vhyg.get('posthoc_locked_primary_frontier_cohorts', 0)} post-hoc locked primary frontier cohorts on dev seeds `0..29` + {vhyg.get('preregistered_extension_frontier_cohorts', 0)} pre-registered extension cohort(s))",
            f"- Seed lock (`671ed96` post-hoc lock on `0-29`, `PRIMARY` vs `REPLICATION`) and pre-registered extensions (`f9fb7a4a` `30-59`, `cf394894` `gpt-5.5`) in `docs/reports/gap.md`: **{'verified' if vhyg.get('seed_lock_rule_verified') and vhyg.get('preregistered_extensions_verified') else 'missing'}**",
            f"- Active docs scanned for unlabelled stale claims: `{', '.join(vhyg.get('active_docs_checked', []))}` ({len(vhyg.get('historical_disclosures_allowed', []))} explicitly disclosed historical notes permitted)",
            "",
            H2 + "Gate 5: Protected-Path and Secret Hygiene",
            "",
            f"- Protected-path rules enforced from `.github/protected-paths.txt`: **{manifest.get('protected_path_rules_count', 0)}** rules (verified via `--diff-base origin/justSilas` and working-tree `HEAD`)",
            f"- Secret and mole-leak pattern classes scanned across `results/eval*` and `docs/reports/`: **{manifest.get('secret_pattern_rules_count', 0)}** pattern classes (Google API keys, sk-* keys, OAuth and provider tokens, PEM private keys, secret env assignments with `CANARY_WORLD_SECRET=canary-demo-live` public demo placeholder exempted, judge SALT bytes, and JSON mole-id world fields)",
        ]
    )

    return _norm_ascii("\n".join(lines) + "\n")


def run_all_gates(
    root: Path,
    expected_seeds: list[int] | None = None,
    diff_base: str | None = None,
) -> list[GateResult]:
    return [
        gate1_headline_and_gap_table_numbers(root, expected_seeds=expected_seeds),
        gate2_replay_cache_completeness_and_step_consistency(root, expected_seeds=expected_seeds),
        gate3_baselines_and_judge_spread_bands(root),
        gate4_version_and_preregistration_hygiene(root),
        gate5_protected_paths_and_secret_hygiene(root, base_ref=diff_base),
    ]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Keyless Canary v1.4 eval claims, replay cache, and protected-path consistency verifier."
    )
    ap.add_argument("--root", default=str(ROOT), help="Repository root directory")
    ap.add_argument("--manifest", default=None, help="Path to claims_manifest.json")
    ap.add_argument("--report", default=None, help="Path to eval_claims_verification.md")
    ap.add_argument("--write-manifest", action="store_true", help="Write claims_manifest.json")
    ap.add_argument("--no-write", action="store_true", help="Run gates without writing manifest or report")
    ap.add_argument("--check", action="store_true", help="Verify all 5 gates and committed artifacts (1e-9 float tol)")
    ap.add_argument(
        "--diff-base",
        "--check-diff",
        dest="diff_base",
        default=None,
        metavar="BASE_REF",
        help="Verify git diff BASE_REF...HEAD touches 0 protected paths (defaults to origin/justSilas when present)",
    )
    ap.add_argument("--seeds", default=None, help="Optional seed range override (default: 0-29)")
    ap.add_argument("--json", action="store_true", help="Print JSON summary to stdout")
    args = ap.parse_args(argv)

    t0 = time.perf_counter()
    root = Path(args.root).resolve()
    manifest_path = Path(args.manifest).resolve() if args.manifest else (root / DEFAULT_MANIFEST_REL)
    report_path = Path(args.report).resolve() if args.report else (root / DEFAULT_REPORT_REL)
    expected_seeds = _parse_seed_spec(args.seeds) if args.seeds else None

    gates = run_all_gates(root, expected_seeds=expected_seeds, diff_base=args.diff_base)
    computed_manifest = build_manifest(gates)
    rendered_report = render_report(computed_manifest)
    manifest_errors: list[str] = []

    default_write = (
        not args.check
        and not args.no_write
        and not args.json
        and args.seeds is None
        and root == ROOT.resolve()
        and args.manifest is None
    )
    should_write_manifest = args.write_manifest or default_write
    should_write_report = (args.report is not None and not args.check and not args.no_write) or default_write

    if should_write_manifest:
        encoded = (json.dumps(computed_manifest, indent=2, sort_keys=False, ensure_ascii=True) + "\n").encode("ascii")
        if len(encoded) >= MANIFEST_MAX_BYTES:
            manifest_errors.append(
                f"generated manifest size {len(encoded)} bytes exceeds {MANIFEST_MAX_BYTES} byte limit"
            )
        else:
            manifest_path.parent.mkdir(parents=True, exist_ok=True)
            manifest_path.write_bytes(encoded)

    if should_write_report and not manifest_errors:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(rendered_report, encoding="utf-8")

    if args.check:
        if not manifest_path.is_file():
            manifest_errors.append(f"manifest file missing: {manifest_path}")
        else:
            raw_bytes = manifest_path.read_bytes()
            if len(raw_bytes) >= MANIFEST_MAX_BYTES:
                manifest_errors.append(
                    f"manifest size {len(raw_bytes)} bytes exceeds {MANIFEST_MAX_BYTES} byte limit"
                )
            try:
                on_disk = json.loads(raw_bytes.decode("utf-8"))
                if not approx_equal(on_disk, computed_manifest, tol=FLOAT_TOL):
                    manifest_errors.append(
                        f"manifest {manifest_path} differs from live recomputed claims beyond tol={FLOAT_TOL}"
                    )
            except (UnicodeDecodeError, ValueError) as exc:
                manifest_errors.append(f"manifest {manifest_path} invalid JSON: {exc}")

        check_report_also = args.report is not None or (args.manifest is None and root == ROOT.resolve())
        if check_report_also:
            if not report_path.is_file():
                manifest_errors.append(f"report file missing: {report_path}")
            else:
                disk_report = report_path.read_text(encoding="utf-8")
                if disk_report != rendered_report:
                    manifest_errors.append(
                        f"report {report_path} differs from freshly rendered report"
                    )

    elapsed_s = round(time.perf_counter() - t0, 3)
    overall_ok = all(g.passed for g in gates) and not manifest_errors

    if args.json:
        payload = {
            "passed": overall_ok,
            "elapsed_s": elapsed_s,
            "gates": [_clean_json_value(asdict(g)) for g in gates],
            "manifest_errors": manifest_errors,
            "manifest_path": str(manifest_path),
            "report_path": str(report_path),
        }
        print(json.dumps(payload, indent=2, ensure_ascii=True))
    else:
        for g in gates:
            status = "PASS" if g.passed else "FAIL"
            print(f"[{status}] {g.gate}: {g.summary}")
            for v in g.violations:
                print(f"  VIOLATION: {_norm_ascii(v)}")
            for w in g.warnings:
                print(f"  WARN [{w['code']}]: {_norm_ascii(w['message'])}")
        for me in manifest_errors:
            print(f"[FAIL] artifact_check: {_norm_ascii(me)}")
        verdict = "PASS" if overall_ok else "FAIL"
        print(f"OVERALL: {verdict} ({elapsed_s:.2f}s)")

    return 0 if overall_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
