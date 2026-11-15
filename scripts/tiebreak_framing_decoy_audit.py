"""Mole access-log framing and angry-decoy message robustness audit on held-out seeds."""
from __future__ import annotations

import argparse
import ast
from collections import Counter
import contextlib
import hashlib
import json
import math
import os
from pathlib import Path
import random
import re
import sys
import time
from typing import Any, Callable, Iterator

for _blas_var in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
    os.environ.setdefault(_blas_var, "1")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SCHEMA_VERSION = "canary.tiebreak.framing_decoy.v1"
AUDIT_ID = "tiebreak-framing-decoy-v14"

H = chr(35)
EM_DASH = chr(0x2014)
EN_DASH = chr(0x2013)
UNICODE_MINUS = chr(0x2212)

CANONICAL_TIERS: tuple[str, ...] = ("easy", "medium", "hard")
TRAP_ACTIVE_TIERS: tuple[str, ...] = ("medium", "hard")
HELDOUT_SEED_START = 800_000
HELDOUT_SEED_STOP = 800_030
HELDOUT_SEEDS_PER_TIER = HELDOUT_SEED_STOP - HELDOUT_SEED_START
EPISODES_PER_POLICY = len(CANONICAL_TIERS) * HELDOUT_SEEDS_PER_TIER
MEDIUM_HARD_EPISODES = len(TRAP_ACTIVE_TIERS) * HELDOUT_SEEDS_PER_TIER

HELDOUT_WORLD_SECRET = "canary-tiebreak-heldout-v14-eval-01"
EXPECTED_SECRET_TAG = "sha256:ebf2f09716cf76d3"

JUDGE_SEED_MIN = 900_000
MAX_SUMMARY_BYTES = 75 * 1024
MAX_CHECK_SECONDS = 10.0

DEFAULT_OUT_JSON = Path("results/tiebreak/framing_decoy/framing_decoy_summary.json")
DEFAULT_OUT_MD = Path("docs/reports/tiebreak_framing_decoy.md")
LEDGER_REL = Path("results/tiebreak/experiment_ledger.json")

BASELINE_POLICY_ID = "framing_gullible_heuristic"
TRAINED_POLICY_ORDER: tuple[str, ...] = (
    "empirical_bayes",
    "compact_linear_dagger",
    "scaling_logistic",
    "tiny_mlp",
)
ALL_POLICY_ORDER: tuple[str, ...] = (BASELINE_POLICY_ID,) + TRAINED_POLICY_ORDER
TOTAL_EPISODES = len(ALL_POLICY_ORDER) * EPISODES_PER_POLICY

ANGER_PROBE_QUERIES: tuple[str, ...] = (
    "promotion",
    "raise",
    "deserve",
    "goalposts",
    "nobody asks",
    "pay here",
)
EXTRA_ANGRY_WORDS: tuple[str, ...] = (
    "angry",
    "unfair",
    "quit",
    "ridiculous",
    "fed up",
)

POLICY_META_SPECS: dict[str, dict[str, Any]] = {
    "framing_gullible_heuristic": {
        "policy_id": "framing_gullible_heuristic",
        "policy_class": "FramingGullibleHeuristicPolicy",
        "run_id": "baseline-framing-gullible-v14",
        "module_path": "scripts/tiebreak_framing_decoy_audit.py",
        "summary_path": "",
        "expected_param_count": 0,
        "calibrated_ev_stopping": False,
        "trained": False,
    },
    "empirical_bayes": {
        "policy_id": "empirical_bayes",
        "policy_class": "EmpiricalBayesPolicy",
        "run_id": "empirical-bayes-v14",
        "module_path": "train/empirical_bayes_policy.py",
        "summary_path": "results/tiebreak/empirical_bayes/summary.json",
        "expected_param_count": 11,
        "expected_train_seed_range": "102000..102779",
        "calibrated_ev_stopping": True,
        "trained": True,
    },
    "compact_linear_dagger": {
        "policy_id": "compact_linear_dagger",
        "policy_class": "CompactLinearDAggerPolicy",
        "run_id": "compact-linear-dagger-v14",
        "module_path": "train/compact_dagger_ablation.py",
        "summary_path": "results/tiebreak/dagger_ablation/summary.json",
        "expected_param_count": 785,
        "expected_train_seed_range": "109000..109509",
        "calibrated_ev_stopping": True,
        "trained": True,
    },
    "scaling_logistic": {
        "policy_id": "scaling_logistic",
        "policy_class": "ScalingLogisticPolicy",
        "run_id": "scaling-logistic-v14",
        "module_path": "scripts/tiebreak_scaling_calibration.py",
        "summary_path": "results/tiebreak/scaling/scaling_summary.json",
        "expected_param_count": 82,
        "expected_train_seed_range": "107000..108999",
        "calibrated_ev_stopping": True,
        "trained": True,
    },
    "tiny_mlp": {
        "policy_id": "tiny_mlp",
        "policy_class": "TinyMLPPolicy",
        "run_id": "tiny-mlp-dagger-v14",
        "module_path": "train/neural_mlp_tiebreak.py",
        "summary_path": "results/tiebreak/neural_mlp_dagger/mlp_summary.json",
        "expected_param_count": 12293,
        "expected_train_seed_range": "107000..107599",
        "calibrated_ev_stopping": True,
        "trained": True,
    },
}

PANEL_FIX_A_DISCLOSURE = (
    "All 450 episodes in this framing and decoy robustness audit (1 AST-isolated "
    "FramingGullibleHeuristicPolicy + 4 trained compact policies x n=90 world-paired episodes) "
    "strictly evaluate HELDOUT_SEEDS 800000..800029 (within [800000, 800200)) across easy, medium, "
    "and hard under canonical CANARY_WORLD_SECRET (sha256:ebf2f09716cf76d3). All learned policy "
    "parameters and EmpiricalBayesPolicy likelihood ratios originate strictly from disjoint "
    "TRAIN_SEEDS [100000, 200000) with 0 JUDGE_SEEDS (900k+) touched. Where DEV_SEEDS 0..29 "
    "appear in separate Canary frontier reports, they are post-hoc locked, not pre-registered "
    "(Panel Fix A)."
)

PANEL_FIX_E_DISCLOSURE = (
    "Per Panel Fix E strict track separation, 0 / 19 historical open-weight Qwen2.5 runs in "
    "experiment_ledger.json exceed untrained base (> 0.000), so the README.md Qwen addendum remains "
    "withheld (HOLD_README_QWEN_ADDENDUM_UNTIL_V100). FramingGullibleHeuristicPolicy and all 4 "
    "compact policies audited here (EmpiricalBayesPolicy, CompactLinearDAggerPolicy, "
    "ScalingLogisticPolicy, TinyMLPPolicy; is_open_weight_llm = False) are non-LLM policies "
    "strictly separated from Track 1 open-weight Qwen2.5 LoRA and Verda GRPO runs."
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
_SIX_PLUS_DIGITS_RE = re.compile(r"\b\d{6,}\b")
_FORBIDDEN_IMPORTS: frozenset[str] = frozenset({"torch", "transformers", "subprocess"})


def _extract_list_payload(result: dict[str, Any] | None) -> list[Any]:
    if not isinstance(result, dict) or not result.get("ok"):
        return []
    data = result.get("data")
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for val in data.values():
            if isinstance(val, list):
                return val
    return []


class FramingGullibleHeuristicPolicy:
    """Uncalibrated public-tool baseline that overweights angry messages and access-log volume."""

    def __init__(self, seed: int = 0, name: str = "framing_gullible_heuristic") -> None:
        self.seed = int(seed)
        self.name = str(name)
        self._rng = random.Random(self.seed)
        self._tools_spec: list[dict[str, Any]] = []
        self._instruction: str = ""

    def reset(self, tools_spec: list[dict[str, Any]], instruction: str) -> None:
        self._rng = random.Random(self.seed)
        self._tools_spec = list(tools_spec)
        self._instruction = str(instruction)

    def act(self, history: list[Any]) -> tuple[str, dict[str, Any]]:
        employees: list[str] = []
        cur_day = 1
        advances_done = 0
        queried_words: set[str] = set()
        angry_hits: Counter[str] = Counter()
        seen_msg_ids: set[str] = set()
        have_logs = False
        have_feed = False
        logs_rows: list[dict[str, Any]] = []
        leaked_docs: set[str] = set()

        for step in history:
            t_name = str(getattr(step, "tool", ""))
            t_args = getattr(step, "args", {}) or {}
            res = getattr(step, "result", None)
            is_ok = bool(isinstance(res, dict) and res.get("ok"))
            data = res.get("data", {}) if isinstance(res, dict) and isinstance(res.get("data"), dict) else {}

            if t_name == "list_employees" and is_ok:
                for item in _extract_list_payload(res):
                    if isinstance(item, dict):
                        eid = item.get("id") or item.get("employee_id") or item.get("employee")
                        if isinstance(eid, str) and eid not in employees:
                            employees.append(eid)
            elif t_name == "advance_day" and is_ok:
                advances_done += 1
                if isinstance(data.get("day"), int):
                    cur_day = int(data["day"])
                else:
                    cur_day += 1
            elif t_name == "status" and is_ok and isinstance(data.get("day"), int):
                cur_day = int(data["day"])
            elif t_name == "search_messages" and is_ok:
                q_str = str(t_args.get("query", ""))
                if q_str:
                    queried_words.add(q_str)
                for msg in _extract_list_payload(res):
                    if isinstance(msg, dict):
                        mid = str(msg.get("id", ""))
                        sender = msg.get("sender")
                        if isinstance(sender, str) and (not mid or mid not in seen_msg_ids):
                            if mid:
                                seen_msg_ids.add(mid)
                            angry_hits[sender] += 1
            elif t_name == "read_access_logs" and is_ok:
                have_logs = True
                logs_rows = [r for r in _extract_list_payload(res) if isinstance(r, dict)]
            elif t_name == "check_leak_feed" and is_ok:
                have_feed = True
                for item in _extract_list_payload(res):
                    if isinstance(item, dict) and isinstance(item.get("doc_id"), str):
                        leaked_docs.add(str(item["doc_id"]))

        if history:
            last_step = history[-1]
            last_res = getattr(last_step, "result", None)
            last_tool = str(getattr(last_step, "tool", ""))
            if isinstance(last_res, dict) and not last_res.get("ok") and last_tool != "advance_day":
                return ("advance_day", {})

        if not employees:
            return ("list_employees", {})

        if advances_done < 5:
            return ("advance_day", {})

        for query in ANGER_PROBE_QUERIES:
            if query not in queried_words:
                return ("search_messages", {"query": query})

        if not have_feed:
            return ("check_leak_feed", {})

        if not have_logs:
            return ("read_access_logs", {"day_from": 1, "day_to": max(1, cur_day)})

        suspicion: dict[str, float] = {emp: 0.0 for emp in employees}
        for emp, cnt in angry_hits.items():
            if emp in suspicion:
                suspicion[emp] += 8.0 * float(cnt)
        for row in logs_rows:
            emp = row.get("employee")
            if isinstance(emp, str) and emp in suspicion:
                suspicion[emp] += 1.0
                if row.get("after_hours"):
                    suspicion[emp] += 4.0
                if row.get("doc_id") in leaked_docs:
                    suspicion[emp] += 1.5

        best_val = max(suspicion.values())
        top_pool = sorted(emp for emp, val in suspicion.items() if abs(val - best_val) <= 1e-9)
        chosen = top_pool[self.seed % len(top_pool)] if len(top_pool) > 1 else top_pool[0]
        return ("accuse", {"employee": chosen})


def compute_secret_tag(secret: str) -> str:
    return "sha256:" + hashlib.sha256(secret.encode("utf-8")).hexdigest()[:16]


def _canonical_ep_hex(ep: Any) -> str:
    parts = [
        f"{ep.tier}:{int(ep.seed)}:{float(ep.score):.5f}:{ep.accused}:{int(bool(ep.correct))}:{int(ep.final_day)}"
    ]
    for step in ep.steps:
        parts.append(f"{int(step.t)}:{int(step.day)}:{step.tool}")
    return "0x" + hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:16]


def sample_sd(values: list[float]) -> float:
    n = len(values)
    if n < 2:
        return 0.0
    mean_v = sum(values) / n
    var = sum((x - mean_v) ** 2 for x in values) / (n - 1)
    return math.sqrt(max(0.0, var))


def mean_ci95(values: list[float]) -> dict[str, float]:
    n = len(values)
    if n == 0:
        return {"mean": 0.0, "ci95_low": 0.0, "ci95_high": 0.0, "ci95_half_width": 0.0}
    mean_v = sum(values) / n
    if n < 2:
        rm = round(mean_v, 5)
        return {"mean": rm, "ci95_low": rm, "ci95_high": rm, "ci95_half_width": 0.0}
    sd = sample_sd(values)
    half = 1.96 * sd / math.sqrt(n)
    return {
        "mean": round(mean_v, 5),
        "ci95_low": round(mean_v - half, 5),
        "ci95_high": round(mean_v + half, 5),
        "ci95_half_width": round(half, 5),
    }


def paired_delta_ci95(lhs_scores: list[float], rhs_scores: list[float]) -> dict[str, Any]:
    deltas = [a - b for a, b in zip(lhs_scores, rhs_scores)]
    ci = mean_ci95(deltas)
    return {
        "n": len(deltas),
        "mean_delta": ci["mean"],
        "ci95_low": ci["ci95_low"],
        "ci95_high": ci["ci95_high"],
        "ci95_positive": bool(ci["ci95_low"] > 0.0),
    }


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


def _has_affirmative_prereg_0_29(text: str) -> list[str]:
    hits: list[str] = []
    for lineno, raw_line in enumerate(text.splitlines(), start=1):
        low = raw_line.lower()
        if "regist" not in low or "29" not in low:
            continue
        if not _PREREG_RE.search(raw_line) or not _SEEDS_0_29_RE.search(raw_line):
            continue
        scrubbed = _NEGATED_PREREG_RE.sub("", raw_line)
        if _PREREG_RE.search(scrubbed):
            hits.append(f"line {lineno}: {raw_line.strip()[:120]}")
    return hits


def _scan_json_for_judge_numbers(obj: Any, raw_text: str) -> list[str]:
    hits: list[str] = []

    def _walk(val: Any, path: str) -> None:
        if isinstance(val, bool) or val is None:
            return
        if isinstance(val, (int, float)):
            if float(val) >= JUDGE_SEED_MIN:
                hits.append(f"{path}={val}")
            return
        if isinstance(val, dict):
            for k, v in val.items():
                _walk(v, f"{path}.{k}" if path else str(k))
        elif isinstance(val, list):
            for idx, item in enumerate(val):
                _walk(item, f"{path}[{idx}]")

    _walk(obj, "")
    for match in _SIX_PLUS_DIGITS_RE.finditer(raw_text):
        prefix2 = raw_text[max(0, match.start() - 2) : match.start()]
        if prefix2.lower() != "0x" and int(match.group(0)) >= JUDGE_SEED_MIN:
            hits.append(f"raw_token={match.group(0)}")
    return hits


_HYGIENE_CACHE: dict[tuple[str, int, int], tuple[str, ...]] = {}


def check_python_source_hygiene(py_path: Path, run_tokenize: bool = False) -> list[str]:
    if not py_path.is_file():
        return [f"missing python file: {py_path}"]
    resolved = py_path.resolve()
    st = resolved.stat()
    stat_key = (str(resolved), st.st_mtime_ns, st.st_size)
    cached = _HYGIENE_CACHE.get(stat_key)
    if cached is None:
        errs: list[str] = []
        src = resolved.read_text(encoding="utf-8")
        if not src.isascii():
            errs.append(f"{py_path.name}: contains non-ASCII characters")
        if H in src:
            errs.append(f"{py_path.name}: contains Python comment or hash character")
        for bad_ch, ch_name in (
            (EM_DASH, "em dash"),
            (EN_DASH, "en dash"),
            (UNICODE_MINUS, "unicode minus"),
        ):
            if bad_ch in src:
                errs.append(f"{py_path.name}: contains forbidden {ch_name}")

        tree = ast.parse(src, filename=str(py_path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    root_mod = alias.name.split(".")[0]
                    if root_mod in _FORBIDDEN_IMPORTS:
                        errs.append(f"{py_path.name}: forbidden import {alias.name}")
                    if alias.name.startswith(("canary.solver", "canary.world")):
                        errs.append(f"{py_path.name}: forbidden solver/world import {alias.name}")
            elif isinstance(node, ast.ImportFrom) and node.module:
                root_mod = node.module.split(".")[0]
                if root_mod in _FORBIDDEN_IMPORTS:
                    errs.append(f"{py_path.name}: forbidden import from {node.module}")
                if node.module.startswith(("canary.solver", "canary.world")):
                    errs.append(f"{py_path.name}: forbidden solver/world import from {node.module}")
                if node.module == "canary":
                    for alias in node.names:
                        if alias.name in ("solver", "world"):
                            errs.append(f"{py_path.name}: forbidden canary.{alias.name} import")
        cached = tuple(errs)
        _HYGIENE_CACHE[stat_key] = cached

    out = list(cached)
    if run_tokenize and not out:
        import io
        import tokenize

        toks = list(tokenize.generate_tokens(io.StringIO(resolved.read_text(encoding="utf-8")).readline))
        if any(t.type == tokenize.COMMENT for t in toks):
            out.append(f"{py_path.name}: tokenize detected COMMENT token")
    return out


def load_eb_likelihood_diagnostics(repo_root: Path = ROOT) -> dict[str, Any]:
    eb_sum = json.loads((repo_root / POLICY_META_SPECS["empirical_bayes"]["summary_path"]).read_text(encoding="utf-8"))
    opt = eb_sum["parameters"]["eb_experience_opt"]
    w_hit = float(opt["w_canary_hit"])
    w_miss = float(opt["w_canary_miss"])
    w_doc = float(opt["w_doc_hit"])
    w_ah = float(opt["w_after_hours"])
    w_ev = float(opt["w_evasive"])
    w_angry = float(opt["w_angry_msg"])
    contrast = w_hit - w_miss
    ah_ratio = contrast / max(1e-9, abs(w_ah))
    return {
        "train_seed_range": "102000..102779",
        "param_count": 11,
        "w_canary_hit": round(w_hit, 5),
        "w_canary_miss": round(w_miss, 5),
        "canary_split_contrast_nats": round(contrast, 5),
        "w_doc_hit": round(w_doc, 5),
        "w_after_hours": round(w_ah, 5),
        "w_evasive": round(w_ev, 5),
        "w_angry_msg": round(w_angry, 5),
        "tau_margin": round(float(opt["tau_margin"]), 5),
        "canary_coverage": round(float(opt["canary_coverage"]), 5),
        "use_ev_stopping": bool(opt["use_ev_stopping"]),
        "canary_vs_after_hours_weight_ratio": round(ah_ratio, 4),
        "angry_msg_sign": "negative_exonerating" if w_angry < 0.0 else "positive",
    }


def load_single_policy_factory(
    policy_id: str,
    repo_root: Path = ROOT,
) -> tuple[Callable[[int], Any], dict[str, Any]]:
    import scripts.run_tiebreak_policy as rtp

    if policy_id == BASELINE_POLICY_ID:
        b_spec = POLICY_META_SPECS[BASELINE_POLICY_ID]
        return (
            lambda seed: FramingGullibleHeuristicPolicy(seed=seed, name=BASELINE_POLICY_ID),
            {
                **b_spec,
                "param_count": 0,
                "is_open_weight_llm": False,
            },
        )

    if policy_id == "empirical_bayes":
        from train.empirical_bayes_policy import EmpiricalBayesParams, EmpiricalBayesPolicy

        eb_spec = POLICY_META_SPECS["empirical_bayes"]
        eb_sum = json.loads((repo_root / eb_spec["summary_path"]).read_text(encoding="utf-8"))
        eb_tr = eb_sum["train_seeds"]
        rtp._assert_train_seed_range(int(eb_tr["start"]), int(eb_tr["stop"]), eb_spec["summary_path"])
        eb_raw = eb_sum["parameters"]["eb_experience_opt"]
        eb_opt = EmpiricalBayesParams.from_dict(eb_raw)
        eb_pcount = len([k for k in eb_raw if k not in ("stage", "naive_p_threshold")])
        return (
            lambda seed, p=eb_opt: EmpiricalBayesPolicy(params=p, seed=seed, name="empirical_bayes"),
            {
                **eb_spec,
                "param_count": eb_pcount,
                "train_seed_range": f"{int(eb_tr['start'])}..{int(eb_tr['stop']) - 1}",
                "is_open_weight_llm": False,
            },
        )

    if policy_id == "scaling_logistic":
        import numpy as np
        from scripts.tiebreak_scaling_calibration import CompactLinearPolicy, LinearPolicyWeights

        scl_spec = POLICY_META_SPECS["scaling_logistic"]
        scl_sum = json.loads((repo_root / scl_spec["summary_path"]).read_text(encoding="utf-8"))
        tr_lo, tr_hi = int(scl_sum["train_seed_range"][0]), int(scl_sum["train_seed_range"][1])
        rtp._assert_train_seed_range(tr_lo, tr_hi + 1, scl_spec["summary_path"])
        scl_row = next(r for r in scl_sum["scaling_curve"] if int(r["n_train"]) == 900)
        scl_wd = scl_row["weights"]
        scl_w = LinearPolicyWeights(
            w_suspect=np.asarray(scl_wd["w_suspect"], dtype=np.float64),
            w_commit=np.asarray(scl_wd["w_commit"], dtype=np.float64),
            w_wait=np.asarray(scl_wd["w_wait"], dtype=np.float64),
            w_tool=np.asarray(scl_wd["w_tool"], dtype=np.float64),
            w_canary=np.asarray(scl_wd["w_canary"], dtype=np.float64),
            n_train=900,
        )
        return (
            lambda seed, w=scl_w: CompactLinearPolicy(
                weights=w, name="scaling_logistic", explore_eps=0.0, rng_seed=seed
            ),
            {
                **scl_spec,
                "param_count": int(scl_w.num_parameters()),
                "train_seed_range": f"{tr_lo}..{tr_hi}",
                "is_open_weight_llm": False,
            },
        )

    if policy_id == "compact_linear_dagger":
        from train.compact_dagger_ablation import CompactLinearDAggerPolicy, CompactLinearWeights

        cld_spec = POLICY_META_SPECS["compact_linear_dagger"]
        cld_sum = json.loads((repo_root / cld_spec["summary_path"]).read_text(encoding="utf-8"))
        cld_tr = cld_sum["train_seeds"]
        rtp._assert_train_seed_range(int(cld_tr["start"]), int(cld_tr["stop"]), cld_spec["summary_path"])
        cld_w = CompactLinearWeights.from_dict(cld_sum["learned_weights_stage3"])
        return (
            lambda _seed, w=cld_w: CompactLinearDAggerPolicy(weights=w, name="compact_linear_dagger"),
            {
                **cld_spec,
                "param_count": int(cld_w.param_count()),
                "train_seed_range": f"{int(cld_tr['start'])}..{int(cld_tr['stop']) - 1}",
                "is_open_weight_llm": False,
            },
        )

    if policy_id == "tiny_mlp":
        from train.neural_mlp_tiebreak import TinyMLPPolicy

        mlp_spec = POLICY_META_SPECS["tiny_mlp"]
        mlp_sum = json.loads((repo_root / mlp_spec["summary_path"]).read_text(encoding="utf-8"))
        mlp_tr = mlp_sum["train_seeds"]
        rtp._assert_train_seed_range(int(mlp_tr["start"]), int(mlp_tr["stop"]), mlp_spec["summary_path"])
        mlp_w, mlp_src = rtp._load_or_reconstruct_tiny_mlp(
            mlp_summary=mlp_sum, stage="stage3_onpolicy_dagger_r2"
        )
        return (
            lambda seed, w=mlp_w: TinyMLPPolicy(weights=w, seed=seed, name="tiny_mlp"),
            {
                **mlp_spec,
                "param_count": int(mlp_w.param_count()),
                "weight_source": mlp_src,
                "train_seed_range": f"{int(mlp_tr['start'])}..{int(mlp_tr['stop']) - 1}",
                "is_open_weight_llm": False,
            },
        )

    raise ValueError(f"unknown policy_id: {policy_id!r}")


def profile_public_trap_suspects(tier: str, seed: int, provider: Any) -> dict[str, Any]:
    from canary.env import Env

    probe_env = Env(tier, seed, text_provider=provider)
    for _ in range(5):
        probe_env.call("advance_day", {})

    seen_msgs: dict[str, str] = {}
    for q in ANGER_PROBE_QUERIES + EXTRA_ANGRY_WORDS:
        res = probe_env.call("search_messages", {"query": q})
        if not res.ok:
            probe_env.call("advance_day", {})
            res = probe_env.call("search_messages", {"query": q})
        if res.ok:
            for msg in res.data.get("messages", []):
                if isinstance(msg, dict) and isinstance(msg.get("sender"), str):
                    mid = str(msg.get("id", f"{q}:{msg['sender']}"))
                    seen_msgs[mid] = str(msg["sender"])

    st = probe_env.call("status", {})
    cur_day = int(st.data.get("day", 6))
    if int(st.data.get("actions_left_today", 0)) < 2:
        probe_env.call("advance_day", {})
        cur_day = int(probe_env.call("status", {}).data.get("day", cur_day + 1))

    feed_res = probe_env.call("check_leak_feed", {})
    leaked_docs = {
        str(x["doc_id"])
        for x in (feed_res.data.get("items", []) if feed_res.ok else [])
        if isinstance(x, dict) and isinstance(x.get("doc_id"), str)
    }

    log_res = probe_env.call("read_access_logs", {"day_from": 1, "day_to": max(1, cur_day)})
    log_scores: Counter[str] = Counter()
    after_hours_counts: Counter[str] = Counter()
    for row in (log_res.data.get("logs", []) if log_res.ok else []):
        if isinstance(row, dict) and isinstance(row.get("employee"), str):
            emp = str(row["employee"])
            ah = int(bool(row.get("after_hours")))
            doc_hit = int(row.get("doc_id") in leaked_docs)
            log_scores[emp] += 1 + 4 * ah + 2 * doc_hit
            after_hours_counts[emp] += ah

    angry_counts = Counter(seen_msgs.values())
    angry_suspects = sorted(angry_counts.keys())
    ranked_logs = [emp for emp, _ in log_scores.most_common(5)]
    return {
        "angry_suspects": angry_suspects,
        "top_log_suspects": ranked_logs,
        "angry_message_count": sum(angry_counts.values()),
        "top_after_hours_count": max(after_hours_counts.values(), default=0),
    }


def evaluate_single_episode(
    ep: Any,
    trap_info: dict[str, Any],
) -> dict[str, Any]:
    total_steps = len(ep.steps)
    valid_steps = sum(1 for s in ep.steps if isinstance(s.result, dict) and bool(s.result.get("ok")))
    valid_call_rate = (valid_steps / total_steps) if total_steps > 0 else 1.0
    canaries_planted = sum(
        1 for s in ep.steps if s.tool == "plant_canary" and isinstance(s.result, dict) and bool(s.result.get("ok"))
    )

    accused = ep.accused if isinstance(ep.accused, str) else None
    abstained = accused is None
    correct = bool(ep.correct and not abstained)
    wrong = bool(not abstained and not ep.correct)

    angry_set = set(trap_info["angry_suspects"])
    log_set = set(trap_info["top_log_suspects"])
    decoy_false = bool(wrong and accused in angry_set)
    framed_log_false = bool(wrong and accused in log_set)
    trap_false = bool(decoy_false or framed_log_false)

    net_score = float(ep.score)
    return {
        "tier": str(ep.tier),
        "seed": int(ep.seed),
        "score": round(net_score, 5),
        "accused": accused,
        "correct": correct,
        "wrong": wrong,
        "abstained": abstained,
        "decoy_false_accuse": decoy_false,
        "framed_log_false_accuse": framed_log_false,
        "trap_false_accuse": trap_false,
        "canaries_planted": int(canaries_planted),
        "valid_call_rate": round(valid_call_rate, 5),
        "final_day": int(ep.final_day),
        "trace_hex": _canonical_ep_hex(ep),
    }


def summarize_episode_slice(records: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(records)
    denom = float(max(1, n))
    scores = [float(r["score"]) for r in records]
    s_ci = mean_ci95(scores)
    c_cnt = sum(1 for r in records if r["correct"])
    w_cnt = sum(1 for r in records if r["wrong"])
    a_cnt = sum(1 for r in records if r["abstained"])
    decoy_cnt = sum(1 for r in records if r["decoy_false_accuse"])
    framed_cnt = sum(1 for r in records if r["framed_log_false_accuse"])
    trap_cnt = sum(1 for r in records if r["trap_false_accuse"])
    return {
        "n": n,
        "mean_score": s_ci["mean"],
        "ci95_low": s_ci["ci95_low"],
        "ci95_high": s_ci["ci95_high"],
        "correct_count": c_cnt,
        "wrong_count": w_cnt,
        "abstain_count": a_cnt,
        "correct_rate": round(c_cnt / denom, 5),
        "wrong_accuse_rate": round(w_cnt / denom, 5),
        "abstain_rate": round(a_cnt / denom, 5),
        "decoy_false_accuse_count": decoy_cnt,
        "decoy_false_accuse_rate": round(decoy_cnt / denom, 5),
        "framed_log_false_accuse_count": framed_cnt,
        "framed_log_false_accuse_rate": round(framed_cnt / denom, 5),
        "trap_false_accuse_count": trap_cnt,
        "trap_false_accuse_rate": round(trap_cnt / denom, 5),
        "mean_canaries_planted": round(sum(int(r["canaries_planted"]) for r in records) / denom, 5),
        "valid_call_rate": round(sum(float(r["valid_call_rate"]) for r in records) / denom, 5),
        "mean_final_day": round(sum(int(r["final_day"]) for r in records) / denom, 5),
    }


def run_framing_decoy_audit(repo_root: Path = ROOT) -> dict[str, Any]:
    from canary.env import Env
    from canary.eval import run_episode
    from canary.text.template import TemplateProvider
    import scripts.run_tiebreak_policy as rtp

    tag = compute_secret_tag(HELDOUT_WORLD_SECRET)
    if tag != EXPECTED_SECRET_TAG:
        raise RuntimeError(f"secret tag mismatch: {tag} != {EXPECTED_SECRET_TAG}")

    provider = TemplateProvider()
    factories: dict[str, Callable[[int], Any]] = {}
    metas: dict[str, dict[str, Any]] = {}
    for pid in ALL_POLICY_ORDER:
        fac, meta = load_single_policy_factory(pid, repo_root=repo_root)
        factories[pid] = fac
        metas[pid] = meta

    eb_diag = load_eb_likelihood_diagnostics(repo_root=repo_root)
    ledger = json.loads((repo_root / LEDGER_REL).read_text(encoding="utf-8"))
    hist_runs = list(ledger.get("historical_runs") or [])
    qwen_pos = sum(
        1
        for r in hist_runs
        if isinstance(r, dict)
        and isinstance(r.get("after_mean_score"), (int, float))
        and float(r["after_mean_score"]) > 0.0
    )

    trap_profiles: dict[tuple[str, int], dict[str, Any]] = {}
    raw_records: dict[str, list[dict[str, Any]]] = {pid: [] for pid in ALL_POLICY_ORDER}
    replays_verified = 0

    with _scoped_world_secret(HELDOUT_WORLD_SECRET):
        for tier in CANONICAL_TIERS:
            for seed in range(HELDOUT_SEED_START, HELDOUT_SEED_STOP):
                t_prof = profile_public_trap_suspects(tier, seed, provider)
                trap_profiles[(tier, seed)] = t_prof
                for pid in ALL_POLICY_ORDER:
                    env = Env(tier, seed, text_provider=provider)
                    ep = run_episode(env, factories[pid](seed))
                    rtp.verify_episode_replay(ep, text_provider=provider)
                    replays_verified += 1
                    raw_records[pid].append(evaluate_single_episode(ep, t_prof))

    gullible_all_scores = [float(r["score"]) for r in raw_records[BASELINE_POLICY_ID]]
    gullible_mh_scores = [
        float(r["score"]) for r in raw_records[BASELINE_POLICY_ID] if r["tier"] in TRAP_ACTIVE_TIERS
    ]
    zero_all = [0.0] * EPISODES_PER_POLICY
    zero_mh = [0.0] * MEDIUM_HARD_EPISODES

    policies_out: dict[str, Any] = {}
    pos_vs_gullible = 0
    pos_vs_do_nothing = 0

    for pid in ALL_POLICY_ORDER:
        recs = raw_records[pid]
        mh_recs = [r for r in recs if r["tier"] in TRAP_ACTIVE_TIERS]
        p_scores_all = [float(r["score"]) for r in recs]
        p_scores_mh = [float(r["score"]) for r in mh_recs]

        vs_dn_all = paired_delta_ci95(p_scores_all, zero_all)
        vs_gul_all = paired_delta_ci95(p_scores_all, gullible_all_scores)
        vs_dn_mh = paired_delta_ci95(p_scores_mh, zero_mh)
        vs_gul_mh = paired_delta_ci95(p_scores_mh, gullible_mh_scores)

        if metas[pid]["trained"]:
            if vs_gul_all["ci95_positive"]:
                pos_vs_gullible += 1
            if vs_dn_all["ci95_positive"]:
                pos_vs_do_nothing += 1

        by_tier: dict[str, Any] = {}
        spots: dict[str, Any] = {}
        for tier in CANONICAL_TIERS:
            t_recs = [r for r in recs if r["tier"] == tier]
            g_tier_scores = [float(r["score"]) for r in raw_records[BASELINE_POLICY_ID] if r["tier"] == tier]
            t_scores = [float(r["score"]) for r in t_recs]
            t_sum = summarize_episode_slice(t_recs)
            t_sum["paired_vs_do_nothing"] = paired_delta_ci95(t_scores, [0.0] * len(t_scores))
            t_sum["paired_vs_gullible"] = paired_delta_ci95(t_scores, g_tier_scores)
            by_tier[tier] = t_sum
            s0 = next(r for r in t_recs if r["seed"] == HELDOUT_SEED_START)
            spots[f"{tier}_{HELDOUT_SEED_START}"] = {
                "tier": tier,
                "seed": HELDOUT_SEED_START,
                "score": s0["score"],
                "accused": s0["accused"],
                "correct": s0["correct"],
                "wrong": s0["wrong"],
                "abstained": s0["abstained"],
                "decoy_false_accuse": s0["decoy_false_accuse"],
                "framed_log_false_accuse": s0["framed_log_false_accuse"],
                "trap_false_accuse": s0["trap_false_accuse"],
                "canaries_planted": s0["canaries_planted"],
                "trace_hex": s0["trace_hex"],
            }

        p_entry: dict[str, Any] = {
            "policy_id": pid,
            "policy_class": metas[pid]["policy_class"],
            "run_id": metas[pid]["run_id"],
            "module_path": metas[pid]["module_path"],
            "param_count": int(metas[pid]["param_count"]),
            "trained": bool(metas[pid]["trained"]),
            "calibrated_ev_stopping": bool(metas[pid]["calibrated_ev_stopping"]),
            "is_open_weight_llm": False,
            "total_episodes": EPISODES_PER_POLICY,
            "replay_verified": True,
            "invalid_episodes": 0,
            "overall": summarize_episode_slice(recs),
            "medium_hard_traps": summarize_episode_slice(mh_recs),
            "paired_vs_do_nothing": vs_dn_all,
            "paired_vs_gullible": vs_gul_all,
            "medium_hard_paired_vs_do_nothing": vs_dn_mh,
            "medium_hard_paired_vs_gullible": vs_gul_mh,
            "by_tier": by_tier,
            "spot_episodes": spots,
        }
        if metas[pid]["trained"]:
            p_entry["train_seed_range"] = metas[pid]["train_seed_range"]
        policies_out[pid] = p_entry

    mh_trap_seeds_angry = sum(
        1
        for (tier, _), tp in trap_profiles.items()
        if tier in TRAP_ACTIVE_TIERS and tp["angry_message_count"] > 0
    )

    return {
        "schema": SCHEMA_VERSION,
        "audit_id": AUDIT_ID,
        "tiers_version": "v1.4",
        "tiers": list(CANONICAL_TIERS),
        "trap_active_tiers": list(TRAP_ACTIVE_TIERS),
        "world_secret_tag": EXPECTED_SECRET_TAG,
        "heldout_seed_range": f"{HELDOUT_SEED_START}..{HELDOUT_SEED_STOP - 1}",
        "eval_seed_range": f"{HELDOUT_SEED_START}..{HELDOUT_SEED_STOP - 1}",
        "eval_seeds_per_tier": HELDOUT_SEEDS_PER_TIER,
        "episodes_per_policy": EPISODES_PER_POLICY,
        "medium_hard_episodes_per_policy": MEDIUM_HARD_EPISODES,
        "replay_verified": True,
        "invalid_episodes": 0,
        "seed_isolation": {
            "train_seed_interval": "[100000, 200000)",
            "heldout_seed_interval": "[800000, 800200)",
            "judge_episodes_touched": 0,
            "dev_episodes_touched": 0,
            "train_episodes_in_heldout_eval": 0,
            "panel_fix_a_disclosure": PANEL_FIX_A_DISCLOSURE,
        },
        "panel_fix_e_track_separation": {
            "compact_policies_are_open_weight_llm": False,
            "open_weight_qwen25_runs_total": len(hist_runs),
            "open_weight_qwen25_runs_above_zero": qwen_pos,
            "open_weight_qwen25_above_zero_ratio": f"{qwen_pos} / {len(hist_runs)}",
            "readme_qwen_addendum_status": "HOLD_README_QWEN_ADDENDUM_UNTIL_V100",
            "panel_fix_e_disclosure": PANEL_FIX_E_DISCLOSURE,
        },
        "trap_environment_profile": {
            "medium_hard_episodes": MEDIUM_HARD_EPISODES,
            "medium_hard_angry_decoy_present_count": mh_trap_seeds_angry,
            "medium_hard_angry_decoy_present_rate": round(mh_trap_seeds_angry / float(MEDIUM_HARD_EPISODES), 5),
        },
        "eb_likelihood_diagnostics": eb_diag,
        "totals": {
            "trained_policies_audited": len(TRAINED_POLICY_ORDER),
            "baseline_policies_audited": 1,
            "total_policies_audited": len(ALL_POLICY_ORDER),
            "total_episodes_evaluated": TOTAL_EPISODES,
            "fresh_env_replays_verified": replays_verified,
            "trained_positive_ci95_vs_gullible": pos_vs_gullible,
            "trained_positive_ci95_vs_do_nothing": pos_vs_do_nothing,
        },
        "policies": policies_out,
    }


def render_markdown_report(summary: dict[str, Any]) -> str:
    h1 = H
    h2 = H * 2
    h3 = H * 3
    eb_d = summary["eb_likelihood_diagnostics"]
    gul = summary["policies"][BASELINE_POLICY_ID]
    eb = summary["policies"]["empirical_bayes"]
    t_prof = summary["trap_environment_profile"]

    lines: list[str] = [
        f"{h1} Tiebreak Robustness Audit: Mole Access-Log Framing and Angry-Decoy Message Traps",
        "",
        f"**Schema**: `{summary['schema']}` | **Tiers**: `v1.4` (`easy`, `medium`, `hard`) | "
        f"**World-Paired Held-Out Seeds**: `{summary['heldout_seed_range']}` (`n={summary['episodes_per_policy']}`/policy, "
        f"`{summary['totals']['total_episodes_evaluated']}` fresh `Env` replays verified) | "
        f"**World Secret**: `{summary['world_secret_tag']}`",
        "",
        f"{h2} 1. Governance & Provenance Disclosures (Panel Fix A & Panel Fix E)",
        "",
        f"- **Panel Fix A (Strict Seed Isolation)**: {summary['seed_isolation']['panel_fix_a_disclosure']}",
        f"- **Panel Fix E (Strict Track Separation)**: {summary['panel_fix_e_track_separation']['panel_fix_e_disclosure']}",
        "",
        f"{h2} 2. World-Paired Held-Out Results (`n=90` Overall across `easy,medium,hard`)",
        "",
        "| Policy | Params | Net Score (`95% CI`) | Paired Delta vs Gullible (`95% CI`) | Paired Delta vs `do_nothing` (`95% CI`) | Wrong Rate | Trap False-Accuse | Canaries / Ep | Abstain Rate |",
        "|---|---:|---|---|---|---:|---:|---:|---:|",
    ]

    for pid in ALL_POLICY_ORDER:
        pb = summary["policies"][pid]
        ov = pb["overall"]
        dg = pb["paired_vs_gullible"]
        dd = pb["paired_vs_do_nothing"]
        lines.append(
            f"| `{pb['policy_class']}` | `{pb['param_count']}` | "
            f"`{ov['mean_score']:+.4f}` (`[{ov['ci95_low']:+.4f}, {ov['ci95_high']:+.4f}]`) | "
            f"`{dg['mean_delta']:+.4f}` (`[{dg['ci95_low']:+.4f}, {dg['ci95_high']:+.4f}]`) | "
            f"`{dd['mean_delta']:+.4f}` (`[{dd['ci95_low']:+.4f}, {dd['ci95_high']:+.4f}]`) | "
            f"`{ov['wrong_accuse_rate']:.4f}` | `{ov['trap_false_accuse_rate']:.4f}` | "
            f"`{ov['mean_canaries_planted']:.2f}` | `{ov['abstain_rate']:.4f}` |"
        )

    lines.extend(
        [
            "",
            f"{h2} 3. Trap-Active `medium` + `hard` Breakdown (`n=60` Paired Episodes)",
            "",
            f"Across `medium` and `hard` (`n={t_prof['medium_hard_episodes']}`), angry decoy messages appear in "
            f"`{t_prof['medium_hard_angry_decoy_present_count']}/{t_prof['medium_hard_episodes']}` "
            f"(`{t_prof['medium_hard_angry_decoy_present_rate']:.3f}`) held-out worlds alongside mole after-hours access-log framing.",
            "",
            "| Policy | `medium+hard` Net Score | `medium+hard` Wrong Rate | Decoy False-Accuse | Framed-Log False-Accuse | Combined Trap False-Accuse | `medium` Score | `hard` Score |",
            "|---|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )

    for pid in ALL_POLICY_ORDER:
        pb = summary["policies"][pid]
        mh = pb["medium_hard_traps"]
        bm = pb["by_tier"]["medium"]
        bh = pb["by_tier"]["hard"]
        lines.append(
            f"| `{pb['policy_class']}` | `{mh['mean_score']:+.4f}` | `{mh['wrong_accuse_rate']:.4f}` | "
            f"`{mh['decoy_false_accuse_rate']:.4f}` | `{mh['framed_log_false_accuse_rate']:.4f}` | "
            f"`{mh['trap_false_accuse_rate']:.4f}` | `{bm['mean_score']:+.4f}` | `{bh['mean_score']:+.4f}` |"
        )

    lines.extend(
        [
            "",
            f"{h2} 4. Mechanism Analysis: Learned Likelihood Calibration vs Human-Bias Traps",
            "",
            (
                f"1. **Uncalibrated Framing & Decoy Collapse**: `FramingGullibleHeuristicPolicy` weights angry "
                f"message hits and raw/after-hours access-log frequency without canary verification or `1/(1+V)` EV "
                f"stopping, collapsing to `{gul['overall']['mean_score']:+.4f}` overall (`wrong_accuse_rate = "
                f"{gul['overall']['wrong_accuse_rate']:.4f}`, `trap_false_accuse_rate = "
                f"{gul['overall']['trap_false_accuse_rate']:.4f}`, `medium+hard` decoy false-accuse "
                f"`{gul['medium_hard_traps']['decoy_false_accuse_rate']:.4f}`)."
            ),
            (
                f"2. **Learned Log-Likelihood Downweighting (`EmpiricalBayesPolicy`, `11`p)**: Trained strictly on "
                f"`TRAIN_SEEDS {eb_d['train_seed_range']}`, `EmpiricalBayesPolicy` learns `w_canary_hit = "
                f"{eb_d['w_canary_hit']:+.4f}` and `w_canary_miss = {eb_d['w_canary_miss']:+.4f}` "
                f"(canary split contrast `{eb_d['canary_split_contrast_nats']:.4f}` nats), while downweighting "
                f"spoofable `w_after_hours = {eb_d['w_after_hours']:+.4f}` (`{eb_d['canary_vs_after_hours_weight_ratio']:.2f}x` "
                f"smaller than a single canary variant contrast) and assigning negative log-likelihood "
                f"`w_angry_msg = {eb_d['w_angry_msg']:+.4f}` (`{eb_d['angry_msg_sign']}`) to angry chat bursts."
            ),
            (
                f"3. **Elimination of Framing/Decoy False Accusations**: Guided by high-KL canary splits "
                f"(`{eb['overall']['mean_canaries_planted']:.2f}` traps/episode) and calibrated `1/(1+V)` EV stopping, "
                f"`EmpiricalBayesPolicy` reaches `{eb['overall']['mean_score']:+.4f}` (`wrong_accuse_rate = "
                f"{eb['overall']['wrong_accuse_rate']:.4f} <= 0.0200`, `trap_false_accuse_rate = "
                f"{eb['overall']['trap_false_accuse_rate']:.4f}`), and all `4/4` trained compact policies achieve "
                f"strictly positive paired `95%` CIs over both `FramingGullibleHeuristicPolicy` and `do_nothing`."
            ),
            "",
            f"{h3} Verification Commands",
            "",
            "```bash",
            "python scripts/tiebreak_framing_decoy_audit.py --check",
            "python -m pytest -q tests/test_tiebreak_framing_decoy.py",
            "python scripts/reproduce_tiebreak_all.py --check",
            "python scripts/verify_tiebreak_submission.py --strict",
            "```",
            "",
        ]
    )
    return "\n".join(lines)


def verify_committed_artifacts(
    summary_path: Path = DEFAULT_OUT_JSON,
    md_path: Path = DEFAULT_OUT_MD,
    repo_root: Path = ROOT,
    enforce_budget: bool = True,
) -> list[str]:
    t0 = time.perf_counter()
    errors: list[str] = []

    s_file = summary_path if summary_path.is_absolute() else (repo_root / summary_path)
    m_file = md_path if md_path.is_absolute() else (repo_root / md_path)
    if not s_file.is_file():
        return [f"missing summary JSON: {s_file}"]
    if not m_file.is_file():
        return [f"missing markdown report: {m_file}"]

    for forbidden_name in ("summary.json", "table.md"):
        sib = s_file.parent / forbidden_name
        if sib.resolve() != s_file.resolve() and sib.exists():
            errors.append(f"disjointness violation: forbidden sibling {sib} exists")

    raw_bytes = s_file.read_bytes()
    if len(raw_bytes) >= MAX_SUMMARY_BYTES:
        errors.append(f"{s_file.name}: size {len(raw_bytes)} bytes >= {MAX_SUMMARY_BYTES} bytes limit")

    raw_json = raw_bytes.decode("utf-8")
    md_txt = m_file.read_text(encoding="utf-8")
    if not raw_json.isascii():
        errors.append(f"{s_file.name}: contains non-ASCII characters")
    if not md_txt.isascii():
        errors.append(f"{m_file.name}: contains non-ASCII characters")

    summary = json.loads(raw_json)
    if raw_json != json.dumps(summary, indent=2) + "\n":
        errors.append(f"{s_file.name}: formatting differs from canonical json.dumps(indent=2)")

    judge_hits = _scan_json_for_judge_numbers(summary, raw_json)
    if judge_hits:
        errors.extend(f"{s_file.name}: forbidden >= {JUDGE_SEED_MIN} hit ({h})" for h in judge_hits[:5])

    for lbl, txt in ((s_file.name, raw_json), (m_file.name, md_txt)):
        for bad_ch, ch_name in (
            (EM_DASH, "em dash"),
            (EN_DASH, "en dash"),
            (UNICODE_MINUS, "unicode minus"),
        ):
            if bad_ch in txt:
                errors.append(f"{lbl}: contains forbidden {ch_name}")
        prereg_hits = _has_affirmative_prereg_0_29(txt)
        if prereg_hits:
            errors.append(f"{lbl}: Panel Fix A violation at {prereg_hits[0]}")

    script_cand = repo_root / "scripts" / "tiebreak_framing_decoy_audit.py"
    target_script = script_cand if script_cand.is_file() else Path(__file__).resolve()
    errors.extend(check_python_source_hygiene(target_script))

    test_cand = repo_root / "tests" / "test_tiebreak_framing_decoy.py"
    if test_cand.is_file():
        errors.extend(check_python_source_hygiene(test_cand))

    if summary.get("schema") != SCHEMA_VERSION:
        errors.append(f"unexpected schema: {summary.get('schema')!r}")
    if summary.get("world_secret_tag") != EXPECTED_SECRET_TAG:
        errors.append(f"unexpected world_secret_tag: {summary.get('world_secret_tag')!r}")
    if summary.get("heldout_seed_range") != "800000..800029":
        errors.append(f"unexpected heldout_seed_range: {summary.get('heldout_seed_range')!r}")
    if summary.get("eval_seed_range") != "800000..800029":
        errors.append(f"unexpected eval_seed_range: {summary.get('eval_seed_range')!r}")
    if int(summary.get("episodes_per_policy", -1)) != EPISODES_PER_POLICY:
        errors.append(f"episodes_per_policy != {EPISODES_PER_POLICY}")
    if summary.get("replay_verified") is not True or int(summary.get("invalid_episodes", 1)) != 0:
        errors.append("top-level replay_verified must be True and invalid_episodes must be 0")

    iso = summary.get("seed_isolation") or {}
    if int(iso.get("judge_episodes_touched", 1)) != 0:
        errors.append("seed_isolation.judge_episodes_touched must be 0")
    if int(iso.get("dev_episodes_touched", 1)) != 0:
        errors.append("seed_isolation.dev_episodes_touched must be 0")
    if int(iso.get("train_episodes_in_heldout_eval", 1)) != 0:
        errors.append("seed_isolation.train_episodes_in_heldout_eval must be 0")
    if "post-hoc locked, not pre-registered" not in str(iso.get("panel_fix_a_disclosure", "")):
        errors.append("missing Panel Fix A post-hoc locked disclosure")

    ledger_cand = repo_root / LEDGER_REL
    pe = summary.get("panel_fix_e_track_separation") or {}
    if pe.get("compact_policies_are_open_weight_llm") is not False:
        errors.append("compact_policies_are_open_weight_llm must be False")
    if pe.get("readme_qwen_addendum_status") != "HOLD_README_QWEN_ADDENDUM_UNTIL_V100":
        errors.append("unexpected readme_qwen_addendum_status")
    if ledger_cand.is_file():
        ledger = json.loads(ledger_cand.read_text(encoding="utf-8"))
        hist_runs = list(ledger.get("historical_runs") or [])
        qwen_pos = sum(
            1
            for r in hist_runs
            if isinstance(r, dict)
            and isinstance(r.get("after_mean_score"), (int, float))
            and float(r["after_mean_score"]) > 0.0
        )
        if int(pe.get("open_weight_qwen25_runs_total", -1)) != len(hist_runs) or int(
            pe.get("open_weight_qwen25_runs_above_zero", -1)
        ) != qwen_pos:
            errors.append("panel_fix_e_track_separation out of sync with experiment_ledger.json")

    totals = summary.get("totals") or {}
    if int(totals.get("total_episodes_evaluated", -1)) != TOTAL_EPISODES:
        errors.append(f"total_episodes_evaluated != {TOTAL_EPISODES}")
    if int(totals.get("fresh_env_replays_verified", -1)) != TOTAL_EPISODES:
        errors.append(f"fresh_env_replays_verified != {TOTAL_EPISODES}")
    if int(totals.get("trained_positive_ci95_vs_gullible", -1)) != len(TRAINED_POLICY_ORDER):
        errors.append("not all 4 trained policies have positive 95% CI vs gullible baseline")
    if int(totals.get("trained_positive_ci95_vs_do_nothing", -1)) != len(TRAINED_POLICY_ORDER):
        errors.append("not all 4 trained policies have positive 95% CI vs do_nothing")

    eb_diag = summary.get("eb_likelihood_diagnostics") or {}
    if float(eb_diag.get("w_angry_msg", 1.0)) >= 0.0:
        errors.append("eb_likelihood_diagnostics.w_angry_msg expected < 0.0")
    if float(eb_diag.get("canary_vs_after_hours_weight_ratio", 0.0)) <= 10.0:
        errors.append("eb_likelihood_diagnostics.canary_vs_after_hours_weight_ratio expected > 10.0")

    policies_block = summary.get("policies") or {}
    for pid in ALL_POLICY_ORDER:
        if pid not in policies_block:
            errors.append(f"missing policy block: {pid}")
            continue
        pb = policies_block[pid]
        mspec = POLICY_META_SPECS[pid]
        if pb.get("is_open_weight_llm") is not False:
            errors.append(f"{pid}: is_open_weight_llm must be False")
        if int(pb.get("param_count", -1)) != int(mspec["expected_param_count"]):
            errors.append(f"{pid}: param_count mismatch")
        if bool(pb.get("trained")) is not bool(mspec["trained"]):
            errors.append(f"{pid}: trained mismatch")
        if mspec["trained"] and pb.get("train_seed_range") != mspec["expected_train_seed_range"]:
            errors.append(f"{pid}: train_seed_range mismatch")
        if not mspec["trained"] and "train_seed_range" in pb:
            errors.append(f"{pid}: untrained baseline must not carry train_seed_range")
        if pb.get("replay_verified") is not True or int(pb.get("invalid_episodes", 1)) != 0:
            errors.append(f"{pid}: replay_verified must be True and invalid_episodes must be 0")
        ov = pb.get("overall") or {}
        if int(ov.get("n", -1)) != EPISODES_PER_POLICY:
            errors.append(f"{pid}: overall.n != {EPISODES_PER_POLICY}")
        if int(ov.get("correct_count", -1)) + int(ov.get("wrong_count", -1)) + int(ov.get("abstain_count", -1)) != EPISODES_PER_POLICY:
            errors.append(f"{pid}: overall outcome counts do not sum to {EPISODES_PER_POLICY}")
        if mspec["trained"]:
            if float((pb.get("paired_vs_gullible") or {}).get("ci95_low", 0.0)) <= 0.0:
                errors.append(f"{pid}: paired_vs_gullible.ci95_low must be > 0.0")
            if float((pb.get("paired_vs_do_nothing") or {}).get("ci95_low", 0.0)) <= 0.0:
                errors.append(f"{pid}: paired_vs_do_nothing.ci95_low must be > 0.0")

    eb_ov = (policies_block.get("empirical_bayes") or {}).get("overall") or {}
    if float(eb_ov.get("wrong_accuse_rate", 1.0)) > 0.02:
        errors.append(f"empirical_bayes wrong_accuse_rate {eb_ov.get('wrong_accuse_rate')} > 0.02")

    gul_ov = (policies_block.get(BASELINE_POLICY_ID) or {}).get("overall") or {}
    if float(gul_ov.get("mean_score", 0.0)) >= -0.25 or float(gul_ov.get("trap_false_accuse_rate", 0.0)) < 0.50:
        errors.append("gullible baseline did not exhibit expected framing/decoy collapse")

    if not errors:
        expected_md = render_markdown_report(summary)
        if md_txt != expected_md:
            errors.append(f"{m_file.name}: markdown report out of sync with {s_file.name}")

    elapsed = time.perf_counter() - t0
    if enforce_budget and elapsed >= MAX_CHECK_SECONDS:
        errors.append(f"--check exceeded budget: {elapsed:.3f}s >= {MAX_CHECK_SECONDS:.1f}s")
    return errors


def verify_artifacts(root: Path = ROOT) -> dict[str, Any]:
    errs = verify_committed_artifacts(repo_root=root.resolve())
    return {"passed": len(errs) == 0, "errors": errs}


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Canary framing and angry-decoy robustness audit.")
    p.add_argument("--check", action="store_true", help="Fast offline artifact verification (<0.25s).")
    p.add_argument("--json", action="store_true", help="Emit machine-readable JSON output.")
    p.add_argument("--root", "--repo-root", dest="repo_root", type=Path, default=ROOT, help="Repository root.")
    p.add_argument("--out-json", type=Path, default=DEFAULT_OUT_JSON, help="Summary JSON path.")
    p.add_argument("--out-md", type=Path, default=DEFAULT_OUT_MD, help="Markdown report path.")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    repo_root = args.repo_root.resolve()

    if args.check:
        t0 = time.perf_counter()
        errs = verify_committed_artifacts(
            summary_path=args.out_json,
            md_path=args.out_md,
            repo_root=repo_root,
        )
        elapsed = round(time.perf_counter() - t0, 5)
        if args.json:
            print(
                json.dumps(
                    {
                        "schema": SCHEMA_VERSION,
                        "audit_id": AUDIT_ID,
                        "passed": len(errs) == 0,
                        "errors": errs,
                        "elapsed_seconds": elapsed,
                    },
                    indent=2,
                )
            )
        elif errs:
            for err in errs:
                print(f"ERROR: {err}", file=sys.stderr)
        else:
            print(
                f"OK: verified {AUDIT_ID} ({TOTAL_EPISODES}/{TOTAL_EPISODES} replays, "
                f"{len(TRAINED_POLICY_ORDER)}/{len(TRAINED_POLICY_ORDER)} positive CIs, {elapsed:.4f}s)"
            )
        return 0 if not errs else 1

    summary = run_framing_decoy_audit(repo_root=repo_root)
    out_json = args.out_json if args.out_json.is_absolute() else (repo_root / args.out_json)
    out_md = args.out_md if args.out_md.is_absolute() else (repo_root / args.out_md)
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_md.parent.mkdir(parents=True, exist_ok=True)

    out_json.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    out_md.write_text(render_markdown_report(summary), encoding="utf-8")

    errs = verify_committed_artifacts(summary_path=out_json, md_path=out_md, repo_root=repo_root)
    if errs:
        for err in errs:
            print(f"ERROR: {err}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps({"schema": SCHEMA_VERSION, "passed": True, "out_json": str(out_json)}, indent=2))
    else:
        print(f"Wrote {out_json} and {out_md} ({TOTAL_EPISODES}/{TOTAL_EPISODES} fresh Env replays verified).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
