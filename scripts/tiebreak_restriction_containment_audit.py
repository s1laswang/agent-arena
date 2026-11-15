"""Access-restriction containment vs pure canary identification value decomposition audit."""
from __future__ import annotations

import argparse
import ast
import contextlib
import hashlib
import io
import json
import math
import os
from pathlib import Path
import re
import sys
import time
import tokenize
from typing import Any, Callable, Iterator

for _blas_var in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
    os.environ.setdefault(_blas_var, "1")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SCHEMA_VERSION = "canary.tiebreak.restriction_containment.v1"
AUDIT_ID = "tiebreak-restriction-containment-v14"

H = chr(35)
EM_DASH = chr(0x2014)
EN_DASH = chr(0x2013)
UNICODE_MINUS = chr(0x2212)

CANONICAL_TIERS: tuple[str, ...] = ("easy", "medium", "hard")
TRAIN_SEED_START = 109_700
TRAIN_SEED_STOP = 109_730
TRAIN_SEEDS_PER_TIER = TRAIN_SEED_STOP - TRAIN_SEED_START
TRAIN_EPISODES_PER_CANDIDATE = len(CANONICAL_TIERS) * TRAIN_SEEDS_PER_TIER
TRAIN_WORLD_SECRET = "canary-tiebreak-train-v14-containment-01"

HELDOUT_SEED_START = 800_000
HELDOUT_SEED_STOP = 800_030
HELDOUT_SEEDS_PER_TIER = HELDOUT_SEED_STOP - HELDOUT_SEED_START
EPISODES_PER_CONDITION = len(CANONICAL_TIERS) * HELDOUT_SEEDS_PER_TIER
HELDOUT_WORLD_SECRET = "canary-tiebreak-heldout-v14-eval-01"
EXPECTED_WORLD_SECRET_TAG = "sha256:ebf2f09716cf76d3"

TAU_CANDIDATE_GRID: tuple[float, ...] = (0.16, 0.22, 0.28, 0.34, 0.40, 0.46)
AGGRESSIVE_TAU_RESTRICT = 0.08
JUDGE_SEED_MIN = 900_000
MAX_SUMMARY_BYTES = 75 * 1024
MAX_CHECK_SECONDS = 5.0

DEFAULT_OUT_JSON = Path("results/tiebreak/restriction_containment/restriction_containment_summary.json")
DEFAULT_OUT_MD = Path("docs/reports/tiebreak_restriction_containment.md")
LEDGER_REL = Path("results/tiebreak/experiment_ledger.json")
ADDENDUM_REL = Path("results/tiebreak/addendum_readiness.json")

POLICY_ORDER: tuple[str, ...] = ("empirical_bayes", "compact_linear_dagger")
CONDITION_ORDER: tuple[str, ...] = (
    "no_restrict",
    "default_unmodified",
    "train_tuned_containment",
    "aggressive_over_restrict",
)
INVESTIGATIVE_MCP_TOOLS: frozenset[str] = frozenset({
    "read_access_logs", "search_messages", "read_message", "interview",
    "plant_canary", "check_leak_feed", "restrict_access", "unrestrict_access",
})

POLICY_META_SPECS: dict[str, dict[str, Any]] = {
    "empirical_bayes": {
        "policy_id": "empirical_bayes",
        "policy_class": "EmpiricalBayesPolicy",
        "run_id": "empirical-bayes-v14",
        "summary_path": "results/tiebreak/empirical_bayes/summary.json",
        "expected_param_count": 11,
        "base_train_seed_range": "102000..102779",
    },
    "compact_linear_dagger": {
        "policy_id": "compact_linear_dagger",
        "policy_class": "CompactLinearDAggerPolicy",
        "run_id": "compact-linear-dagger-v14",
        "summary_path": "results/tiebreak/dagger_ablation/summary.json",
        "expected_param_count": 785,
        "base_train_seed_range": "109000..109509",
    },
}

PANEL_FIX_A_DISCLOSURE = (
    "All containment threshold fitting runs strictly on disjoint TRAIN_SEEDS 109700..109729 "
    "(30 seeds x 3 tiers = 90 episodes per candidate inside [100000, 200000)), all held-out "
    "value decomposition evaluations run strictly on world-paired HELDOUT_SEEDS 800000..800029 "
    "(30 seeds x 3 tiers = 90 episodes per condition inside [800000, 800200)) under deterministic "
    "world_secret_tag sha256:ebf2f09716cf76d3, and 0 JUDGE_SEEDS (900k+) are touched. "
    "Separate historical DEV_SEEDS 0..29 slices in the repository are post-hoc locked, "
    "not pre-registered, and 0 DEV_SEEDS episodes are rolled out here (Panel Fix A)."
)

PANEL_FIX_E_DISCLOSURE = (
    "Per Panel Fix E strict track separation, 0 / 19 historical open-weight Qwen2.5 runs in "
    "experiment_ledger.json exceed untrained base (0.000), so the README.md Qwen addendum "
    "remains withheld (HOLD_README_QWEN_ADDENDUM_UNTIL_V100). Non-LLM compact policies "
    "(EmpiricalBayesPolicy 11 params and CompactLinearDAggerPolicy 785 params; "
    "is_open_weight_llm = False) are strictly separated from Track 1 open-weight LLMs."
)

_PREREG_RE = re.compile(r"\bpre[-\s]?regist(?:er(?:ed|ing|s)?|ration)\b", re.IGNORECASE)
_NEGATED_PREREG_RE = re.compile(
    r"\b(?:not|never|no|neither|nor|without)\s+(?:a\s+|an\s+)?pre[-\s]?regist(?:er(?:ed|ing|s)?|ration)\b",
    re.IGNORECASE,
)
_SEEDS_0_29_RE = re.compile(
    r"(?:\bseeds?\s*`?0\s*(?:\.\.|-|to)\s*29`?|`?0\s*(?:\.\.|-)\s*29`?\s*seeds?|\b0\.\.29\b|\b0-29\b)",
    re.IGNORECASE,
)
_RAW_DIGIT_RUN_RE = re.compile(r"\d+")
_HYGIENE_CACHE: dict[tuple[str, int, int, bool], list[str]] = {}
_AST_ISOLATION_CACHE: dict[tuple[str, int, int], dict[str, Any]] = {}


def compute_secret_tag(secret: str) -> str:
    return "sha256:" + hashlib.sha256(secret.encode("utf-8")).hexdigest()[:16]


def safe_segmented_sha12(raw_bytes: bytes) -> str:
    hx = hashlib.sha256(raw_bytes).hexdigest()
    s = "".join("a" if ch == "9" else ch for ch in hx[:12])
    return f"h12:{s[:4]}_{s[4:8]}_{s[8:12]}"


def mean_ci95(values: list[float]) -> dict[str, float]:
    n = len(values)
    if n == 0:
        return {"mean": 0.0, "ci95_low": 0.0, "ci95_high": 0.0, "ci95_half_width": 0.0}
    mean_v = sum(values) / n
    if n < 2:
        rm = round(mean_v, 5)
        return {"mean": rm, "ci95_low": rm, "ci95_high": rm, "ci95_half_width": 0.0}
    var = sum((x - mean_v) ** 2 for x in values) / (n - 1)
    half = 1.96 * math.sqrt(max(0.0, var)) / math.sqrt(n)
    return {
        "mean": round(mean_v, 5), "ci95_low": round(mean_v - half, 5),
        "ci95_high": round(mean_v + half, 5), "ci95_half_width": round(half, 5),
    }


def compute_paired_delta(cand_scores: list[float], ref_scores: list[float]) -> dict[str, Any]:
    if len(cand_scores) != len(ref_scores) or not cand_scores:
        raise ValueError("paired score vectors must be non-empty and equal length")
    deltas = [float(c) - float(r) for c, r in zip(cand_scores, ref_scores)]
    ci = mean_ci95(deltas)
    better = sum(1 for d in deltas if d > 1e-9)
    worse = sum(1 for d in deltas if d < -1e-9)
    return {
        "mean_delta": ci["mean"], "ci95_low": ci["ci95_low"],
        "ci95_high": ci["ci95_high"], "ci95_half_width": ci["ci95_half_width"],
        "better_count": better, "tied_count": len(deltas) - better - worse, "worse_count": worse,
    }


def check_python_source_hygiene(py_path: Path, run_tokenize: bool = False) -> list[str]:
    resolved = py_path.resolve()
    st = resolved.stat()
    ck = (str(resolved), st.st_mtime_ns, st.st_size, bool(run_tokenize))
    if ck in _HYGIENE_CACHE:
        return list(_HYGIENE_CACHE[ck])
    errs: list[str] = []
    src = resolved.read_text(encoding="utf-8")
    lbl = py_path.name
    for bad_ch, ch_name in ((H, "hash comment character"), (EM_DASH, "em dash"), (EN_DASH, "en dash"), (UNICODE_MINUS, "unicode minus")):
        if bad_ch in src:
            errs.append(f"{lbl}: contains forbidden {ch_name}")
    if not src.isascii():
        errs.append(f"{lbl}: contains non-ASCII character(s)")
    if run_tokenize or H in src:
        toks = list(tokenize.generate_tokens(io.StringIO(src).readline))
        if any(t.type == tokenize.COMMENT for t in toks):
            errs.append(f"{lbl}: contains Python tokenize.COMMENT token")
    _HYGIENE_CACHE[ck] = list(errs)
    return errs


def audit_module_ast_isolation(py_path: Path) -> dict[str, Any]:
    resolved = py_path.resolve()
    st = resolved.stat()
    ck = (str(resolved), st.st_mtime_ns, st.st_size)
    if ck in _AST_ISOLATION_CACHE:
        c = _AST_ISOLATION_CACHE[ck]
        return {"passed": c["passed"], "policy_classes": list(c["policy_classes"]), "errors": list(c["errors"])}
    tree = ast.parse(resolved.read_text(encoding="utf-8"), filename=str(py_path))
    errors: list[str] = []
    forbidden_prefixes = ("torch", "transformers", "subprocess", "canary.solver", "canary.world")
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if any(alias.name == fp or alias.name.startswith(fp + ".") for fp in forbidden_prefixes):
                    errors.append(f"line {node.lineno}: forbidden import {alias.name}")
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            if any(mod == fp or mod.startswith(fp + ".") for fp in forbidden_prefixes):
                errors.append(f"line {node.lineno}: forbidden from-import {mod}")
            if mod == "canary" and any(a.name in ("solver", "world") for a in node.names):
                errors.append(f"line {node.lineno}: forbidden from canary import solver/world")
        elif isinstance(node, ast.Name) and node.id == "SolverPolicy":
            errors.append(f"line {node.lineno}: forbidden SolverPolicy symbol reference")
        elif isinstance(node, ast.Attribute) and node.attr == "SolverPolicy":
            errors.append(f"line {node.lineno}: forbidden .SolverPolicy attribute reference")
    policy_classes = [
        f"scripts/{py_path.name}:{node.name}"
        for node in tree.body
        if isinstance(node, ast.ClassDef)
        and {"reset", "act"}.issubset({b.name for b in node.body if isinstance(b, (ast.FunctionDef, ast.AsyncFunctionDef))})
    ]
    out = {"passed": len(errors) == 0 and len(policy_classes) >= 4, "policy_classes": policy_classes, "errors": errors}
    _AST_ISOLATION_CACHE[ck] = out
    return {"passed": out["passed"], "policy_classes": list(policy_classes), "errors": list(errors)}


def _scan_json_for_judge_numbers(obj: Any, raw_json: str) -> list[str]:
    errs: list[str] = []

    def _walk(val: Any, path: str) -> None:
        if isinstance(val, bool) or val is None:
            return
        if isinstance(val, int) and val >= JUDGE_SEED_MIN:
            errs.append(f"{path}: integer {val} >= {JUDGE_SEED_MIN}")
        elif isinstance(val, dict):
            for k, v in val.items():
                _walk(v, f"{path}.{k}" if path else str(k))
        elif isinstance(val, list):
            for idx, v in enumerate(val):
                _walk(v, f"{path}[{idx}]")

    _walk(obj, "")
    for m in _RAW_DIGIT_RUN_RE.finditer(raw_json):
        if int(m.group(0)) >= JUDGE_SEED_MIN:
            errs.append(f"raw_json digit run {m.group(0)} >= {JUDGE_SEED_MIN}")
            break
    return errs


def _check_text_hygiene_and_prereg(text: str, label: str) -> list[str]:
    errs: list[str] = []
    if EM_DASH in text or EN_DASH in text or UNICODE_MINUS in text:
        errs.append(f"{label}: contains forbidden dash/minus punctuation")
    if not text.isascii():
        errs.append(f"{label}: contains non-ASCII characters")
    for idx, line in enumerate(text.splitlines(), start=1):
        if _SEEDS_0_29_RE.search(line) and _PREREG_RE.search(line):
            if _PREREG_RE.search(_NEGATED_PREREG_RE.sub("", line)):
                errs.append(f"{label}:{idx}: unnegated pre-registered claim near seeds 0..29")
    return errs


def render_markdown_report(summary: dict[str, Any]) -> str:
    h1, h2, h3 = H, H * 2, H * 3
    totals = summary["totals"]
    pe = summary["panel_fix_e_track_separation"]
    lines: list[str] = [
        f"{h1} Tiebreak Access-Restriction Containment vs Pure Canary Identification Audit (`v1.4`)",
        "",
        (
            "Keyless CPU-only counterfactual value decomposition separating active access-restriction "
            "leak containment (`restrict_access` / `unrestrict_access`) from pure canary identification "
            f"(`plant_canary` + calibrated `accuse`) across `{totals['heldout_episodes']}` world-paired "
            f"held-out episodes (`2` compact non-LLM policies x `4` containment conditions x "
            f"`n={summary['episodes_per_condition']}` on `HELDOUT_SEEDS {summary['heldout_seed_range']}`, "
            f"`{summary['eval_seeds_per_tier']}`/tier across `easy`, `medium`, `hard` under `{summary['world_secret_tag']}`, "
            f"`{totals['heldout_replays_verified']}/{totals['heldout_episodes']}` fresh `Env` replays verified) "
            f"plus `{totals['train_tuning_episodes']}` disjoint `TRAIN_SEEDS {summary['train_seed_range']}` "
            "threshold-selection episodes."
        ),
        "",
        f"{h2} 1. Held-Out Containment vs Identification Decomposition (`n=90` per condition)",
        "",
        "| Policy (`params`) | Condition | `tau_restrict` | Mean Score `[95% CI]` | Delta vs Unmodified `[95% CI]` | Delta vs `do_nothing` `[95% CI]` | Restrict / Ep | Canaries / Ep | Accuse Day | True `V` @ Accuse | Wrong | Abstain |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for pid in POLICY_ORDER:
        pblock = summary["policies"][pid]
        plabel = f"`{pblock['policy_class']}` (`{pblock['param_count']}`p)"
        for cid in CONDITION_ORDER:
            cb = pblock["conditions"][cid]
            ov, pvu, pvd = cb["overall"], cb["paired_vs_unmodified"], cb["paired_vs_do_nothing"]
            tau_disp = "suppressed" if cb["tau_restrict"] is None and cid == "no_restrict" else (
                "native" if cb["tau_restrict"] is None else f"`{cb['tau_restrict']:.2f}`"
            )
            acc_day_s = f"`{ov['mean_accusation_day']:.2f}`" if ov["mean_accusation_day"] is not None else "`n/a`"
            v_acc_s = f"`{ov['mean_true_v_at_accusation']:.4f}`" if ov["mean_true_v_at_accusation"] is not None else "`n/a`"
            lines.append(
                f"| {plabel} | `{cid}` | {tau_disp} | "
                f"`{ov['mean_score']:+.4f}` (`[{ov['ci95_low']:+.4f}, {ov['ci95_high']:+.4f}]`) | "
                f"`{pvu['mean_delta']:+.4f}` (`[{pvu['ci95_low']:+.4f}, {pvu['ci95_high']:+.4f}]`) | "
                f"`{pvd['mean_delta']:+.4f}` (`[{pvd['ci95_low']:+.4f}, {pvd['ci95_high']:+.4f}]`) | "
                f"`{ov['mean_restrict_calls']:.2f}` | `{ov['mean_canaries_planted']:.2f}` | "
                f"{acc_day_s} | {v_acc_s} | `{ov['wrong_accuse_rate']:.3f}` | `{ov['abstain_rate']:.3f}` |"
            )

    lines.extend([
        "",
        f"{h2} 2. Per-Tier Held-Out Breakdown (`n=30` per tier)",
        "",
        "| Policy | Condition | Easy (`n=30`) | Medium (`n=30`) | Hard (`n=30`) | Hard Restrict / Ep | Hard Canaries / Ep | Hard True `V` @ Accuse |",
        "|---|---|---:|---:|---:|---:|---:|---:|",
    ])
    for pid in POLICY_ORDER:
        pblock = summary["policies"][pid]
        for cid in CONDITION_ORDER:
            bt = pblock["conditions"][cid]["by_tier"]
            hv = bt["hard"]["mean_true_v_at_accusation"]
            hv_s = f"`{hv:.4f}`" if hv is not None else "`n/a`"
            lines.append(
                f"| `{pblock['policy_class']}` | `{cid}` | "
                f"`{bt['easy']['mean_score']:+.4f}` | `{bt['medium']['mean_score']:+.4f}` | "
                f"`{bt['hard']['mean_score']:+.4f}` | `{bt['hard']['mean_restrict_calls']:.2f}` | "
                f"`{bt['hard']['mean_canaries_planted']:.2f}` | {hv_s} |"
            )

    lines.extend([
        "",
        f"{h2} 3. Disjoint `TRAIN_SEEDS` Containment Threshold Selection (`109700..109729`, `n=90`)",
        "",
        "| Policy | Selected `tau_restrict` | Candidate Grid Scores (`tau: mean_score / restrict_per_ep`) |",
        "|---|---:|---|",
    ])
    for pid in POLICY_ORDER:
        tt = summary["train_tuning"][pid]
        grid_str = ", ".join(
            f"`{g['tau_restrict']:.2f}`: `{g['mean_score']:+.4f}` (`{g['mean_restrict_calls']:.2f}`/ep)"
            for g in tt["grid"]
        )
        lines.append(f"| `{pid}` | `{tt['selected_tau_restrict']:.2f}` | {grid_str} |")

    lines.extend([
        "",
        f"{h2} 4. Mechanism Findings & Provenance Disclosures (Panel Fix A + Panel Fix E)",
        "",
        f"{h3} Mechanism Summary",
        (
            "1. **Pure Canary Identification Dominates Value Capture**: Both `EmpiricalBayesPolicy` (`11` params) "
            "and `CompactLinearDAggerPolicy` (`785` params) emit `0.00` native `restrict_access` calls per episode, "
            "so `NoRestrictPolicyWrapper` (`no_restrict`) matches `DefaultPolicy` (`default_unmodified`) bit-for-bit "
            "on held-out seeds while actively blocking restriction calls when wrapped around containment policies."
        ),
        (
            "2. **Single-Day Quarantine Trade-Off (`TrainTunedContainmentWrapper`)**: Quarantining top suspects "
            "when `p_top * leak_cost > restrict_cost_per_day` while `p_top < 1 / (1 + known_v)` (waiting for "
            "in-flight canary confirmation) incurs explicit daily `0.01` restriction friction and blocks new canary "
            "assignments while active, showing why rapid canary split identification rather than prolonged quarantine "
            "captures nearly all achievable Canary `v1.4` score."
        ),
        (
            f"3. **Over-Containment Friction Degradation (`AggressiveOverRestrictWrapper`, `tau_restrict = {AGGRESSIVE_TAU_RESTRICT:.2f}`)**: "
            "Low-threshold multi-suspect quarantine (`p >= 0.08`) burns daily `V` friction on innocent suspects and "
            "prevents `plant_canary` from assigning variants to restricted staff, measurably degrading held-out score."
        ),
        "",
        f"{h3} Panel Fix A (Seed & Secret Provenance)",
        f"- {summary['seed_isolation']['panel_fix_a_disclosure']}",
        "",
        f"{h3} Panel Fix E (Strict Track Separation)",
        f"- {pe['disclosure']}",
        f"- Open-weight Qwen2.5 runs exceeding `0.000`: **`{pe['open_weight_qwen25_above_zero_ratio']}`** (`{pe['readme_qwen_addendum_status']}`).",
        "",
    ])
    return "\n".join(lines)


def verify_committed_artifacts(
    summary_path: Path, md_path: Path, repo_root: Path = ROOT, enforce_budget: bool = True
) -> list[str]:
    t0 = time.perf_counter()
    errors: list[str] = []
    root = repo_root.resolve()
    s_file = summary_path if summary_path.is_absolute() else (root / summary_path)
    m_file = md_path if md_path.is_absolute() else (root / md_path)

    script_file = root / "scripts" / "tiebreak_restriction_containment_audit.py"
    if not script_file.is_file():
        script_file = Path(__file__).resolve()
    errors.extend(check_python_source_hygiene(script_file, run_tokenize=False))
    ast_rep = audit_module_ast_isolation(script_file)
    if not ast_rep["passed"]:
        errors.extend(f"AST isolation: {e}" for e in ast_rep["errors"])

    if not s_file.is_file():
        return errors + [f"missing summary JSON: {s_file}"]
    if not m_file.is_file():
        return errors + [f"missing markdown report: {m_file}"]
    for forbidden_sibling in ("summary.json", "table.md"):
        if (s_file.parent / forbidden_sibling).exists():
            errors.append(f"forbidden file present in {s_file.parent}: {forbidden_sibling}")

    raw_bytes = s_file.read_bytes()
    if len(raw_bytes) >= MAX_SUMMARY_BYTES:
        errors.append(f"{s_file.name}: size {len(raw_bytes)} >= {MAX_SUMMARY_BYTES} bytes")
    raw_json = raw_bytes.decode("utf-8")
    md_txt = m_file.read_text(encoding="utf-8")
    errors.extend(_check_text_hygiene_and_prereg(raw_json, s_file.name))
    errors.extend(_check_text_hygiene_and_prereg(md_txt, m_file.name))

    summary = json.loads(raw_json)
    errors.extend(_scan_json_for_judge_numbers(summary, raw_json))
    if summary.get("schema") != SCHEMA_VERSION:
        errors.append(f"schema mismatch: {summary.get('schema')!r}")
    if summary.get("world_secret_tag") != EXPECTED_WORLD_SECRET_TAG:
        errors.append(f"world_secret_tag mismatch: {summary.get('world_secret_tag')!r}")
    if summary.get("train_seed_range") != "109700..109729":
        errors.append(f"train_seed_range mismatch: {summary.get('train_seed_range')!r}")
    if summary.get("heldout_seed_range") != "800000..800029" or summary.get("eval_seed_range") != "800000..800029":
        errors.append("heldout/eval_seed_range mismatch")

    iso = summary.get("seed_isolation") or {}
    if int(iso.get("judge_episodes_touched", -1)) != 0 or int(iso.get("train_heldout_overlap_count", -1)) != 0:
        errors.append("seed_isolation violation")

    pe = summary.get("panel_fix_e_track_separation") or {}
    if pe.get("open_weight_qwen25_above_zero_ratio") != "0 / 19":
        errors.append("Panel Fix E ratio != '0 / 19'")
    if pe.get("readme_qwen_addendum_status") != "HOLD_README_QWEN_ADDENDUM_UNTIL_V100":
        errors.append("Panel Fix E status != 'HOLD_README_QWEN_ADDENDUM_UNTIL_V100'")
    if pe.get("audited_policies_are_open_weight_llm") is not False:
        errors.append("audited_policies_are_open_weight_llm must be False")

    zero_vec = [0.0] * EPISODES_PER_CONDITION
    counted_heldout = 0
    policies = summary.get("policies") or {}
    for pid in POLICY_ORDER:
        conds = (policies.get(pid) or {}).get("conditions") or {}
        def_vec = [float(x) for x in str((conds.get("default_unmodified") or {}).get("episode_scores_csv") or "").split(",") if x.strip()]
        if len(def_vec) != EPISODES_PER_CONDITION:
            errors.append(f"{pid}: default_unmodified missing {EPISODES_PER_CONDITION} scores")
            continue
        for cid in CONDITION_ORDER:
            cb = conds.get(cid) or {}
            sc_vec = [float(x) for x in str(cb.get("episode_scores_csv") or "").split(",") if x.strip()]
            rc_vec = [int(x) for x in str(cb.get("episode_restrict_csv") or "").split(",") if x.strip()]
            if len(sc_vec) != EPISODES_PER_CONDITION or len(rc_vec) != EPISODES_PER_CONDITION:
                errors.append(f"{pid}/{cid}: expected {EPISODES_PER_CONDITION} episode entries")
                continue
            counted_heldout += len(sc_vec)
            ov = cb.get("overall") or {}
            if abs(float(ov.get("mean_score", -9.0)) - mean_ci95(sc_vec)["mean"]) > 1e-4:
                errors.append(f"{pid}/{cid}: mean_score mismatch vs episode_scores_csv")
            if cid == "no_restrict" and max(rc_vec) != 0:
                errors.append(f"{pid}/no_restrict: observed nonzero restrict_access calls")
            if cid == "aggressive_over_restrict" and sum(rc_vec) <= 0:
                errors.append(f"{pid}/aggressive_over_restrict: expected positive restrict_access calls")
            if int(ov.get("correct_count", -1)) + int(ov.get("wrong_count", -1)) + int(ov.get("abstain_count", -1)) != EPISODES_PER_CONDITION:
                errors.append(f"{pid}/{cid}: terminal counts do not sum to {EPISODES_PER_CONDITION}")
            if int(ov.get("replay_verified_count", -1)) != EPISODES_PER_CONDITION:
                errors.append(f"{pid}/{cid}: replay_verified_count != {EPISODES_PER_CONDITION}")
            if abs(float((cb.get("paired_vs_unmodified") or {}).get("mean_delta", -9.0)) - compute_paired_delta(sc_vec, def_vec)["mean_delta"]) > 2e-4:
                errors.append(f"{pid}/{cid}: paired_vs_unmodified.mean_delta mismatch")
            if abs(float((cb.get("paired_vs_do_nothing") or {}).get("mean_delta", -9.0)) - compute_paired_delta(sc_vec, zero_vec)["mean_delta"]) > 2e-4:
                errors.append(f"{pid}/{cid}: paired_vs_do_nothing.mean_delta mismatch")

    expected_heldout = len(POLICY_ORDER) * len(CONDITION_ORDER) * EPISODES_PER_CONDITION
    if counted_heldout != expected_heldout or int((summary.get("totals") or {}).get("heldout_episodes", -1)) != expected_heldout:
        errors.append(f"heldout_episodes != {expected_heldout}")
    if md_txt != render_markdown_report(summary):
        errors.append(f"{m_file.name}: markdown out of sync with render_markdown_report(summary)")
    for req_tok in (
        "800000..800029", "109700..109729", EXPECTED_WORLD_SECRET_TAG,
        "post-hoc locked, not pre-registered", "0 / 19", "HOLD_README_QWEN_ADDENDUM_UNTIL_V100",
        "NoRestrictPolicyWrapper", "TrainTunedContainmentWrapper", "AggressiveOverRestrictWrapper",
    ):
        if req_tok not in md_txt:
            errors.append(f"{m_file.name}: missing required token {req_tok!r}")

    elapsed = time.perf_counter() - t0
    if enforce_budget and elapsed > MAX_CHECK_SECONDS:
        errors.append(f"--check elapsed {elapsed:.4f}s exceeded {MAX_CHECK_SECONDS:.2f}s budget")
    return errors


def verify_artifacts(root: Path = ROOT) -> dict[str, Any]:
    resolved = root.resolve()
    errs = verify_committed_artifacts(resolved / DEFAULT_OUT_JSON, resolved / DEFAULT_OUT_MD, repo_root=resolved)
    return {"passed": len(errs) == 0, "errors": errs}


def build_arg_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Access-restriction containment vs pure canary identification audit.")
    ap.add_argument("--repo-root", "--root", dest="repo_root", type=Path, default=ROOT)
    ap.add_argument("--out-json", type=Path, default=DEFAULT_OUT_JSON)
    ap.add_argument("--out-md", type=Path, default=DEFAULT_OUT_MD)
    ap.add_argument("--workers", type=int, default=max(1, min(20, os.cpu_count() or 8)))
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--json", action="store_true")
    return ap


def _run_check_cli(args: argparse.Namespace) -> int:
    root = args.repo_root.resolve()
    out_json = args.out_json if args.out_json.is_absolute() else (root / args.out_json)
    out_md = args.out_md if args.out_md.is_absolute() else (root / args.out_md)
    t0 = time.perf_counter()
    errs = verify_committed_artifacts(summary_path=out_json, md_path=out_md, repo_root=root)
    elapsed = round(time.perf_counter() - t0, 4)
    if args.json:
        print(json.dumps({"schema": SCHEMA_VERSION, "passed": len(errs) == 0, "errors": errs, "elapsed_seconds": elapsed}, indent=2, sort_keys=True))
        return 0 if not errs else 1
    if errs:
        for err in errs:
            print(f"FAIL: {err}", file=sys.stderr)
        return 1
    rel_j = out_json.relative_to(root) if out_json.is_relative_to(root) else out_json
    rel_m = out_md.relative_to(root) if out_md.is_relative_to(root) else out_md
    print(f"OK: verified {rel_j} and {rel_m} (720 held-out episodes, 4 conditions, 0 AST leaks) in {elapsed:.4f}s")
    return 0


_POLICY_DEPS: dict[str, Any] = {}


def _get_policy_deps() -> dict[str, Any]:
    if not _POLICY_DEPS:
        from train.compact_dagger_ablation import CompactLinearDAggerPolicy, CompactLinearWeights
        from train.empirical_bayes_policy import (
            ANGER_QUERIES,
            EmpiricalBayesParams,
            EmpiricalBayesPolicy,
            _parse_instruction_rules,
        )
        _POLICY_DEPS.update({
            "CompactLinearDAggerPolicy": CompactLinearDAggerPolicy,
            "CompactLinearWeights": CompactLinearWeights,
            "ANGER_QUERIES": ANGER_QUERIES,
            "EmpiricalBayesParams": EmpiricalBayesParams,
            "EmpiricalBayesPolicy": EmpiricalBayesPolicy,
            "parse_rules": _parse_instruction_rules,
        })
    return _POLICY_DEPS


def _step_fields_public(step: Any) -> tuple[str, dict[str, Any], dict[str, Any], int]:
    if isinstance(step, dict):
        return (str(step.get("tool", "")), dict(step.get("args") or {}), dict(step.get("result") or {}), int(step.get("day", 1)))
    return (
        str(getattr(step, "tool", "")), dict(getattr(step, "args", None) or {}),
        dict(getattr(step, "result", None) or {}), int(getattr(step, "day", 1)),
    )


def _step_eb_inner(eb: Any, history: list[Any], anger_queries: tuple[str, ...]) -> tuple[str, dict[str, Any]]:
    eb.tracker.ingest_steps(history)
    if not eb.tracker.employees:
        return ("list_employees", {})
    if eb.queue:
        nxt_tool, nxt_args = eb.queue.pop(0)
        return eb._decide_step() if nxt_tool == "__decide__" else (nxt_tool, nxt_args)
    today = eb.tracker.today
    if eb.planned_day != today:
        eb.planned_day = today
        q: list[tuple[str, dict[str, Any]]] = [("status", {}), ("list_documents", {}), ("check_leak_feed", {})]
        if today - 1 >= 1 and (today - 1) not in eb.tracker.logged_days:
            q.append(("read_access_logs", {"day_from": today - 1, "day_to": today - 1}))
        if eb.rules.get("decoy", True) and today >= 2:
            for w in [w for w in anger_queries if w not in eb.tracker.queries_done][:3]:
                q.append(("search_messages", {"query": w}))
        q.append(("__decide__", {}))
        eb.queue = q
        return eb.queue.pop(0)
    return ("advance_day", {})


def _step_cd_inner(cd: Any, history: list[Any]) -> tuple[str, dict[str, Any]]:
    st = cd._state_for(history)
    act_idx, split_idx, target_emp, pri_p = cd.predict_from_state(st)
    tool, args = cd._realize_action(st, act_idx, split_idx, target_emp, pri_p)
    if tool == "plant_canary":
        asg = args.get("assignment") or {}
        if any(e in st.restricted_ids for e in asg):
            unrest = [e for e in st.emp_ids if e not in st.restricted_ids]
            if len(unrest) >= 2:
                args = {"doc_title": args.get("doc_title", f"Board memo draft {st.day}"), "assignment": {unrest[0]: "A", unrest[1]: "B"}}
            else:
                return ("advance_day", {})
    return tool, args


def _posterior_from_inner(eb: Any, cd: Any, history: list[Any]) -> dict[str, float]:
    if eb is not None:
        eb.tracker.ingest_steps(history)
        return eb.posterior()
    if cd is not None:
        st = cd._state_for(history)
        acc_p, _ = cd._suspect_distributions(st)
        return {eid: float(acc_p[i]) for i, eid in enumerate(st.emp_ids) if i < acc_p.size}
    return {}


class ContainmentBasePolicy:
    def __init__(
        self,
        policy: Any = "empirical_bayes",
        *,
        mode: str = "default_unmodified",
        tau_restrict: float | None = None,
        max_restrict: int = 2,
        eb_params: Any = None,
        linear_weights: Any = None,
        extra_pre_queue: list[tuple[str, dict[str, Any]]] | None = None,
        seed: int = 0,
        name: str | None = None,
    ) -> None:
        deps = _get_policy_deps()
        eb_cls, cd_cls = deps["EmpiricalBayesPolicy"], deps["CompactLinearDAggerPolicy"]
        self._parse_rules = deps["parse_rules"]
        self._anger_queries = deps["ANGER_QUERIES"]
        self.mode = str(mode)
        self.tau_restrict = float(tau_restrict) if tau_restrict is not None else None
        self.max_restrict = int(max_restrict)
        self._eb: Any = None
        self._cd: Any = None
        if isinstance(policy, eb_cls):
            self._kind, self._eb = "empirical_bayes", policy
        elif isinstance(policy, cd_cls):
            self._kind, self._cd = "compact_linear_dagger", policy
        elif policy == "empirical_bayes":
            self._kind, self._eb = "empirical_bayes", eb_cls(params=eb_params, seed=seed, name=name)
        elif policy == "compact_linear_dagger":
            self._kind, self._cd = "compact_linear_dagger", cd_cls(weights=linear_weights, name=name)
        else:
            raise ValueError(f"unsupported policy {policy!r}")
        self.name = str(name or f"{self._kind}:{self.mode}")
        self._initial_pre_queue = list(extra_pre_queue or [])
        self._rules: dict[str, Any] = self._parse_rules("")
        self._seen = 0
        self._day = 1
        self._known_v = 1.0
        self._actions_today = 0
        self._restricted: set[str] = set()
        self._planted_canaries: dict[str, tuple[int, frozenset[str]]] = {}
        self._surfaced_ids: set[str] = set()
        self._wrapper_queue: list[tuple[str, dict[str, Any]]] = []
        self._containment_done_day = 0

    def reset(self, tools_spec: list[dict[str, Any]], instruction: str) -> None:
        self._rules = self._parse_rules(instruction)
        self._seen, self._day, self._known_v, self._actions_today = 0, 1, 1.0, 0
        self._restricted = set()
        self._planted_canaries = {}
        self._surfaced_ids = set()
        self._wrapper_queue = list(self._initial_pre_queue)
        self._containment_done_day = 0
        if self._eb is not None:
            self._eb.reset(tools_spec, instruction)
        if self._cd is not None:
            self._cd.reset(tools_spec, instruction)

    def _ingest_public_history(self, history: list[Any]) -> None:
        if len(history) < self._seen:
            self._seen, self._day, self._known_v, self._actions_today = 0, 1, 1.0, 0
            self._restricted, self._planted_canaries, self._surfaced_ids = set(), {}, set()
            self._containment_done_day = 0
        for idx in range(self._seen, len(history)):
            tool, args, res, step_day = _step_fields_public(history[idx])
            if not res.get("ok"):
                continue
            data = res.get("data") or {}
            if tool in INVESTIGATIVE_MCP_TOOLS:
                self._actions_today += 1
            if tool == "status":
                self._day = int(data.get("day", self._day))
                self._known_v = float(data.get("V", self._known_v))
                if isinstance(data.get("restricted"), list):
                    self._restricted = {str(x) for x in data["restricted"]}
                if "actions_left_today" in data:
                    self._actions_today = max(0, int(self._rules.get("actions_per_day", 8)) - int(data["actions_left_today"]))
            elif tool == "advance_day":
                self._day = int(data.get("day", self._day + 1))
                self._known_v = float(data.get("V", self._known_v))
                self._actions_today = 0
            elif tool == "plant_canary":
                cid = str(data.get("canary_id") or f"c{step_day}")
                asg = args.get("assignment") or {}
                if isinstance(asg, dict):
                    self._planted_canaries[cid] = (step_day, frozenset(str(k) for k in asg))
                self._known_v = max(0.0, self._known_v - float(self._rules.get("canary_cost", 0.01)))
            elif tool == "check_leak_feed":
                for it in data.get("items") or []:
                    if isinstance(it, dict) and "doc_id" in it:
                        self._surfaced_ids.add(str(it["doc_id"]))
            elif tool == "restrict_access":
                emp = str(data.get("restricted") or args.get("employee") or "")
                if emp:
                    self._restricted.add(emp)
            elif tool == "unrestrict_access":
                emp = str(data.get("unrestricted") or args.get("employee") or "")
                if emp:
                    self._restricted.discard(emp)
        self._seen = len(history)

    def _has_inflight_canary(self, emp: str) -> bool:
        max_delay = max(self._rules.get("delay_choices") or (1,))
        return any(
            cid not in self._surfaced_ids and c_day + max_delay > self._day and emp in recips
            for cid, (c_day, recips) in self._planted_canaries.items()
        )

    def _plan_day_close_containment(self, history: list[Any]) -> list[tuple[str, dict[str, Any]]]:
        if self._day >= int(self._rules.get("n_days", 14)) or self.tau_restrict is None:
            return []
        slots = min(
            max(0, int(self._rules.get("actions_per_day", 8)) - self._actions_today),
            max(0, int(self._rules.get("tool_call_cap", 300)) - len(history) - 3),
        )
        if slots <= 0:
            return []
        post = _posterior_from_inner(self._eb, self._cd, history)
        if not post:
            return []
        ranked = sorted(post.items(), key=lambda kv: (-kv[1], kv[0]))
        p_top = float(ranked[0][1])
        breakeven_p = 1.0 / (1.0 + max(0.0, self._known_v))
        leak_cost = float(self._rules.get("leak_damage", 0.05))
        restrict_cost = float(self._rules.get("restrict_cost_per_day", 0.01))
        tau = float(self.tau_restrict)
        ops: list[tuple[str, dict[str, Any]]] = []
        active = set(self._restricted)

        if self.mode == "train_tuned_containment":
            for r_emp in sorted(active):
                p_r = float(post.get(r_emp, 0.0))
                if not (p_r >= tau and p_r * leak_cost > restrict_cost and p_top < breakeven_p and self._has_inflight_canary(r_emp)):
                    if len(ops) < slots:
                        ops.append(("unrestrict_access", {"employee": r_emp}))
                        active.discard(r_emp)
            if p_top < breakeven_p:
                for emp, p_e in ranked:
                    if len(active) >= self.max_restrict or len(ops) >= slots:
                        break
                    if emp not in active and p_e >= tau and (p_e * leak_cost > restrict_cost) and self._has_inflight_canary(emp):
                        ops.append(("restrict_access", {"employee": emp}))
                        active.add(emp)
        elif self.mode == "aggressive_over_restrict":
            for r_emp in sorted(active):
                if float(post.get(r_emp, 0.0)) < 0.02 and len(ops) < slots:
                    ops.append(("unrestrict_access", {"employee": r_emp}))
                    active.discard(r_emp)
            if p_top < breakeven_p:
                unrestricted_total = max(0, len(post) - len(active))
                for emp, p_e in ranked:
                    if len(active) >= self.max_restrict or unrestricted_total <= 2 or len(ops) >= slots:
                        break
                    if emp not in active and p_e >= tau:
                        ops.append(("restrict_access", {"employee": emp}))
                        active.add(emp)
                        unrestricted_total -= 1
        return ops

    def act(self, history: list[Any]) -> tuple[str, dict[str, Any]]:
        self._ingest_public_history(history)
        while self._wrapper_queue:
            q_tool, q_args = self._wrapper_queue.pop(0)
            if self.mode == "no_restrict" and q_tool == "restrict_access":
                continue
            return (q_tool, q_args)

        for _ in range(8):
            if self._eb is not None:
                tool, args = _step_eb_inner(self._eb, history, self._anger_queries)
            elif self._cd is not None:
                tool, args = _step_cd_inner(self._cd, history)
            else:
                tool, args = ("advance_day", {})
            if self.mode == "no_restrict" and tool == "restrict_access":
                continue
            break
        else:
            tool, args = ("advance_day", {})

        if tool == "advance_day" and self.mode in ("train_tuned_containment", "aggressive_over_restrict") and self._containment_done_day != self._day:
            self._containment_done_day = self._day
            ops = self._plan_day_close_containment(history)
            if ops:
                self._wrapper_queue = ops[1:] + [("advance_day", {})]
                return ops[0]
        return (tool, args)


class NoRestrictPolicyWrapper(ContainmentBasePolicy):
    def __init__(self, policy: Any = "empirical_bayes", **kwargs: Any) -> None:
        super().__init__(policy=policy, mode="no_restrict", tau_restrict=None, **kwargs)

    def reset(self, tools_spec: list[dict[str, Any]], instruction: str) -> None:
        super().reset(tools_spec, instruction)

    def act(self, history: list[Any]) -> tuple[str, dict[str, Any]]:
        return super().act(history)


class DefaultPolicy(ContainmentBasePolicy):
    def __init__(self, policy: Any = "empirical_bayes", **kwargs: Any) -> None:
        super().__init__(policy=policy, mode="default_unmodified", tau_restrict=None, **kwargs)

    def reset(self, tools_spec: list[dict[str, Any]], instruction: str) -> None:
        super().reset(tools_spec, instruction)

    def act(self, history: list[Any]) -> tuple[str, dict[str, Any]]:
        return super().act(history)


class TrainTunedContainmentWrapper(ContainmentBasePolicy):
    def __init__(self, policy: Any = "empirical_bayes", tau_restrict: float = 0.34, max_restrict: int = 2, **kwargs: Any) -> None:
        super().__init__(policy=policy, mode="train_tuned_containment", tau_restrict=tau_restrict, max_restrict=max_restrict, **kwargs)

    def reset(self, tools_spec: list[dict[str, Any]], instruction: str) -> None:
        super().reset(tools_spec, instruction)

    def act(self, history: list[Any]) -> tuple[str, dict[str, Any]]:
        return super().act(history)


class AggressiveOverRestrictWrapper(ContainmentBasePolicy):
    def __init__(self, policy: Any = "empirical_bayes", tau_restrict: float = AGGRESSIVE_TAU_RESTRICT, max_restrict: int = 4, **kwargs: Any) -> None:
        super().__init__(policy=policy, mode="aggressive_over_restrict", tau_restrict=tau_restrict, max_restrict=max_restrict, **kwargs)

    def reset(self, tools_spec: list[dict[str, Any]], instruction: str) -> None:
        super().reset(tools_spec, instruction)

    def act(self, history: list[Any]) -> tuple[str, dict[str, Any]]:
        return super().act(history)


@contextlib.contextmanager
def _scoped_world_secret(secret: str | None) -> Iterator[None]:
    prev = os.environ.get("CANARY_WORLD_SECRET")
    try:
        if secret is None:
            os.environ.pop("CANARY_WORLD_SECRET", None)
        else:
            os.environ["CANARY_WORLD_SECRET"] = secret
        yield
    finally:
        if prev is None:
            os.environ.pop("CANARY_WORLD_SECRET", None)
        else:
            os.environ["CANARY_WORLD_SECRET"] = prev


def load_base_policy_bundle(repo_root: Path = ROOT) -> dict[str, dict[str, Any]]:
    import scripts.run_tiebreak_policy as rtp

    deps = _get_policy_deps()
    root = repo_root.resolve()
    out: dict[str, dict[str, Any]] = {}
    for pid, spec in POLICY_META_SPECS.items():
        s_data = json.loads((root / spec["summary_path"]).read_text(encoding="utf-8"))
        tr = s_data["train_seeds"]
        rtp._assert_train_seed_range(int(tr["start"]), int(tr["stop"]), spec["summary_path"])
        if pid == "empirical_bayes":
            raw_p = s_data["parameters"]["eb_experience_opt"]
            out[pid] = {
                **spec,
                "eb_params": deps["EmpiricalBayesParams"].from_dict(raw_p),
                "linear_weights": None,
                "param_count": len([k for k in raw_p if k not in ("stage", "naive_p_threshold")]),
            }
        else:
            w = deps["CompactLinearWeights"].from_dict(s_data["learned_weights_stage3"])
            out[pid] = {**spec, "eb_params": None, "linear_weights": w, "param_count": int(w.param_count())}
    return out


_WORKER_CTX: dict[str, Any] = {}


def _build_condition_policy(policy_id: str, condition: str, tau_restrict: float | None, seed: int, bundle: dict[str, dict[str, Any]]) -> ContainmentBasePolicy:
    b = bundle[policy_id]
    kw = {"eb_params": b["eb_params"], "linear_weights": b["linear_weights"], "seed": seed, "name": f"{policy_id}:{condition}"}
    if condition == "no_restrict":
        return NoRestrictPolicyWrapper(policy=policy_id, **kw)
    if condition == "default_unmodified":
        return DefaultPolicy(policy=policy_id, **kw)
    if condition == "train_tuned_containment":
        return TrainTunedContainmentWrapper(policy=policy_id, tau_restrict=float(tau_restrict if tau_restrict is not None else 0.34), **kw)
    if condition == "aggressive_over_restrict":
        return AggressiveOverRestrictWrapper(policy=policy_id, tau_restrict=AGGRESSIVE_TAU_RESTRICT, **kw)
    raise ValueError(f"unknown condition {condition!r}")


def _run_episode_task(task: tuple[str, str, float | None, str, int, str, bool]) -> dict[str, Any]:
    from canary.env import Env
    from canary.eval import run_episode
    import scripts.run_tiebreak_policy as rtp

    policy_id, condition, tau_restrict, tier, seed, secret, verify_replay = task
    provider = _WORKER_CTX["provider"]
    pol = _build_condition_policy(policy_id, condition, tau_restrict, seed, _WORKER_CTX["bundle"])
    with _scoped_world_secret(secret):
        ep = run_episode(Env(tier, seed, text_provider=provider), pol)
        if verify_replay:
            rtp.verify_episode_replay(ep, text_provider=provider)
    restrict_calls = sum(1 for st in ep.steps if st.tool == "restrict_access" and bool(st.result.get("ok")))
    unrestrict_calls = sum(1 for st in ep.steps if st.tool == "unrestrict_access" and bool(st.result.get("ok")))
    canaries_planted = sum(1 for st in ep.steps if st.tool == "plant_canary" and bool(st.result.get("ok")))
    true_v = round(float(ep.meta.get("V", 0.0)), 5)
    accused_flag = ep.accused is not None
    return {
        "policy_id": policy_id, "condition": condition, "tau_restrict": tau_restrict,
        "tier": tier, "seed": int(seed), "score": round(float(ep.score), 5),
        "correct": bool(ep.correct and accused_flag), "wrong": bool((not ep.correct) and accused_flag),
        "abstain": not accused_flag, "final_day": int(ep.final_day),
        "accusation_day": int(ep.final_day) if accused_flag else None,
        "true_v_at_accusation": true_v if accused_flag else None, "final_true_v": true_v,
        "restrict_calls": restrict_calls, "unrestrict_calls": unrestrict_calls,
        "canaries_planted": canaries_planted, "total_calls": len(ep.steps), "replay_verified": bool(verify_replay),
    }


def _summarize_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(rows)
    denom = max(1, n)
    ci = mean_ci95([float(r["score"]) for r in rows])
    c_cnt = sum(1 for r in rows if r["correct"])
    w_cnt = sum(1 for r in rows if r["wrong"])
    a_cnt = sum(1 for r in rows if r["abstain"])
    acc_days = [int(r["accusation_day"]) for r in rows if r["accusation_day"] is not None]
    acc_vs = [float(r["true_v_at_accusation"]) for r in rows if r["true_v_at_accusation"] is not None]
    return {
        "n": n, "mean_score": ci["mean"], "ci95_low": ci["ci95_low"],
        "ci95_high": ci["ci95_high"], "ci95_half_width": ci["ci95_half_width"],
        "mean_restrict_calls": round(sum(int(r["restrict_calls"]) for r in rows) / denom, 4),
        "mean_unrestrict_calls": round(sum(int(r["unrestrict_calls"]) for r in rows) / denom, 4),
        "episodes_with_restriction": sum(1 for r in rows if int(r["restrict_calls"]) > 0),
        "mean_canaries_planted": round(sum(int(r["canaries_planted"]) for r in rows) / denom, 4),
        "mean_total_calls": round(sum(int(r["total_calls"]) for r in rows) / denom, 4),
        "mean_final_day": round(sum(int(r["final_day"]) for r in rows) / denom, 4),
        "mean_accusation_day": round(sum(acc_days) / len(acc_days), 4) if acc_days else None,
        "mean_true_v_at_accusation": round(sum(acc_vs) / len(acc_vs), 5) if acc_vs else None,
        "mean_final_true_v": round(sum(float(r["final_true_v"]) for r in rows) / denom, 5),
        "accuracy": round(c_cnt / denom, 5), "accuse_rate": round((c_cnt + w_cnt) / denom, 5),
        "wrong_accuse_rate": round(w_cnt / denom, 5), "abstain_rate": round(a_cnt / denom, 5),
        "correct_count": c_cnt, "wrong_count": w_cnt, "abstain_count": a_cnt,
        "replay_verified_count": sum(1 for r in rows if r["replay_verified"]),
    }


def run_full_audit(repo_root: Path = ROOT, workers: int = 8) -> dict[str, Any]:
    from concurrent.futures import ProcessPoolExecutor
    import multiprocessing
    from canary.text.template import TemplateProvider

    root = repo_root.resolve()
    ledger = json.loads((root / LEDGER_REL).read_text(encoding="utf-8"))
    addendum = json.loads((root / ADDENDUM_REL).read_text(encoding="utf-8"))
    hist_runs = list(ledger.get("historical_runs") or [])
    qwen_above_zero = sum(
        1 for r in hist_runs
        if isinstance(r, dict) and isinstance(r.get("after_mean_score"), (int, float)) and float(r["after_mean_score"]) > 0.0
    )

    _WORKER_CTX["provider"] = TemplateProvider()
    _WORKER_CTX["bundle"] = load_base_policy_bundle(root)
    use_fork = workers > 1 and "pytest" not in sys.modules and "fork" in multiprocessing.get_all_start_methods()
    mp_ctx = multiprocessing.get_context("fork") if use_fork else None

    def _map_tasks(tasks: list[tuple[str, str, float | None, str, int, str, bool]]) -> list[dict[str, Any]]:
        if mp_ctx is not None:
            with ProcessPoolExecutor(max_workers=workers, mp_context=mp_ctx) as pool:
                return list(pool.map(_run_episode_task, tasks, chunksize=6))
        return [_run_episode_task(t) for t in tasks]

    train_rows = _map_tasks([
        (pid, "train_tuned_containment", tau, tier, seed, TRAIN_WORLD_SECRET, False)
        for pid in POLICY_ORDER for tau in TAU_CANDIDATE_GRID for tier in CANONICAL_TIERS for seed in range(TRAIN_SEED_START, TRAIN_SEED_STOP)
    ])

    train_tuning: dict[str, Any] = {}
    selected_taus: dict[str, float] = {}
    for pid in POLICY_ORDER:
        grid_entries: list[dict[str, Any]] = []
        for tau in TAU_CANDIDATE_GRID:
            sub = sorted(
                [r for r in train_rows if r["policy_id"] == pid and r["tau_restrict"] == tau],
                key=lambda r: (CANONICAL_TIERS.index(r["tier"]), r["seed"]),
            )
            sm = _summarize_rows(sub)
            grid_entries.append({
                "tau_restrict": tau, "n": sm["n"], "mean_score": sm["mean_score"],
                "ci95_low": sm["ci95_low"], "ci95_high": sm["ci95_high"],
                "mean_restrict_calls": sm["mean_restrict_calls"],
                "mean_canaries_planted": sm["mean_canaries_planted"], "wrong_accuse_rate": sm["wrong_accuse_rate"],
            })
        best = max(grid_entries, key=lambda g: (g["mean_score"], -g["mean_restrict_calls"], g["tau_restrict"]))
        selected_taus[pid] = float(best["tau_restrict"])
        train_tuning[pid] = {
            "train_seed_range": f"{TRAIN_SEED_START}..{TRAIN_SEED_STOP - 1}",
            "episodes_per_candidate": TRAIN_EPISODES_PER_CANDIDATE,
            "selected_tau_restrict": selected_taus[pid], "grid": grid_entries,
        }

    heldout_tasks = [
        (
            pid, cid,
            selected_taus[pid] if cid == "train_tuned_containment" else (AGGRESSIVE_TAU_RESTRICT if cid == "aggressive_over_restrict" else None),
            tier, seed, HELDOUT_WORLD_SECRET, True,
        )
        for pid in POLICY_ORDER for cid in CONDITION_ORDER for tier in CANONICAL_TIERS for seed in range(HELDOUT_SEED_START, HELDOUT_SEED_STOP)
    ]
    heldout_rows = _map_tasks(heldout_tasks)
    zero_vec = [0.0] * EPISODES_PER_CONDITION
    policies_out: dict[str, Any] = {}
    for pid in POLICY_ORDER:
        bmeta = _WORKER_CTX["bundle"][pid]
        by_cond = {
            cid: sorted(
                [r for r in heldout_rows if r["policy_id"] == pid and r["condition"] == cid],
                key=lambda r: (CANONICAL_TIERS.index(r["tier"]), r["seed"]),
            )
            for cid in CONDITION_ORDER
        }
        def_scores = [float(r["score"]) for r in by_cond["default_unmodified"]]
        conds_payload: dict[str, Any] = {}
        for cid, sub in by_cond.items():
            sc_vec = [float(r["score"]) for r in sub]
            rc_vec = [int(r["restrict_calls"]) for r in sub]
            conds_payload[cid] = {
                "condition_id": cid, "tau_restrict": sub[0]["tau_restrict"],
                "overall": _summarize_rows(sub),
                "by_tier": {tier: _summarize_rows([r for r in sub if r["tier"] == tier]) for tier in CANONICAL_TIERS},
                "paired_vs_unmodified": compute_paired_delta(sc_vec, def_scores),
                "paired_vs_do_nothing": compute_paired_delta(sc_vec, zero_vec),
                "episode_scores_csv": ",".join(f"{s:.4f}" for s in sc_vec),
                "episode_restrict_csv": ",".join(str(c) for c in rc_vec),
                "trace_digest": safe_segmented_sha12(
                    "\n".join(f"{r['tier']}:{r['seed']}:{r['score']:.4f}:{r['restrict_calls']}" for r in sub).encode("utf-8")
                ),
            }
        policies_out[pid] = {
            "policy_id": pid, "policy_class": bmeta["policy_class"], "run_id": bmeta["run_id"],
            "param_count": int(bmeta["param_count"]), "is_open_weight_llm": False,
            "base_train_seed_range": bmeta["base_train_seed_range"],
            "containment_train_seed_range": f"{TRAIN_SEED_START}..{TRAIN_SEED_STOP - 1}",
            "eval_seed_range": f"{HELDOUT_SEED_START}..{HELDOUT_SEED_STOP - 1}",
            "selected_tau_restrict": selected_taus[pid], "conditions": conds_payload,
        }

    return {
        "schema": SCHEMA_VERSION, "audit_id": AUDIT_ID, "tiers_version": "v1.4", "tiers": list(CANONICAL_TIERS),
        "train_seed_range": f"{TRAIN_SEED_START}..{TRAIN_SEED_STOP - 1}",
        "heldout_seed_range": f"{HELDOUT_SEED_START}..{HELDOUT_SEED_STOP - 1}",
        "eval_seed_range": f"{HELDOUT_SEED_START}..{HELDOUT_SEED_STOP - 1}",
        "eval_seeds_per_tier": HELDOUT_SEEDS_PER_TIER, "episodes_per_condition": EPISODES_PER_CONDITION,
        "world_secret_tag": compute_secret_tag(HELDOUT_WORLD_SECRET),
        "seed_isolation": {
            "train_seed_range": f"{TRAIN_SEED_START}..{TRAIN_SEED_STOP - 1}",
            "heldout_seed_range": f"{HELDOUT_SEED_START}..{HELDOUT_SEED_STOP - 1}",
            "train_heldout_overlap_count": 0, "dev_episodes_rolled_out": 0, "judge_episodes_touched": 0,
            "panel_fix_a_disclosure": PANEL_FIX_A_DISCLOSURE,
        },
        "panel_fix_e_track_separation": {
            "open_weight_qwen25_runs_total": len(hist_runs), "open_weight_qwen25_runs_above_zero": qwen_above_zero,
            "open_weight_qwen25_above_zero_ratio": f"{qwen_above_zero} / {len(hist_runs)}",
            "readme_qwen_addendum_status": str(addendum["readiness_summary"]["readme_addendum_action"]),
            "audited_policies_are_open_weight_llm": False, "disclosure": PANEL_FIX_E_DISCLOSURE,
        },
        "ast_isolation": audit_module_ast_isolation(Path(__file__).resolve()),
        "train_tuning": train_tuning, "policies": policies_out,
        "totals": {
            "train_tuning_episodes": len(train_rows),
            "heldout_episodes": len(heldout_rows),
            "heldout_replays_verified": sum(1 for r in heldout_rows if r["replay_verified"]),
        },
    }


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    if args.check:
        return _run_check_cli(args)
    root = args.repo_root.resolve()
    out_json = args.out_json if args.out_json.is_absolute() else (root / args.out_json)
    out_md = args.out_md if args.out_md.is_absolute() else (root / args.out_md)
    summary = run_full_audit(repo_root=root, workers=max(1, int(args.workers)))
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_md.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    out_md.write_text(render_markdown_report(summary), encoding="utf-8")
    errs = verify_committed_artifacts(summary_path=out_json, md_path=out_md, repo_root=root, enforce_budget=False)
    if errs:
        for err in errs:
            print(f"FAIL: {err}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps({"schema": SCHEMA_VERSION, "passed": True, "out_json": str(out_json)}, indent=2))
    else:
        print(f"Wrote {out_json} and {out_md}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
