"""Deterministic public-channel Value-of-Information (VoI) and observation-masking ablation audit."""
from __future__ import annotations

import argparse
import ast
from concurrent.futures import ProcessPoolExecutor
import contextlib
import hashlib
import io
import json
import math
import multiprocessing
import os
from pathlib import Path
import re
import sys
import time
import tokenize
from typing import Any, Callable, Iterable, Iterator

for _blas_var in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
    os.environ.setdefault(_blas_var, "1")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SCHEMA_VERSION = "canary.tiebreak.channel_ablation.v1"
AUDIT_ID = "tiebreak-channel-ablation-voi-v14"

H = chr(35)
EM_DASH = chr(0x2014)
EN_DASH = chr(0x2013)
UNICODE_MINUS = chr(0x2212)

CANONICAL_TIERS: tuple[str, ...] = ("easy", "medium", "hard")
PUBLIC_CHANNELS: tuple[str, ...] = (
    "canary_traps",
    "doc_membership",
    "access_logs",
    "angry_messages",
    "interviews",
)
ALL_CHANNELS_SET: frozenset[str] = frozenset(PUBLIC_CHANNELS)

INVESTIGATIVE_MCP_TOOLS: frozenset[str] = frozenset({
    "read_access_logs",
    "search_messages",
    "read_message",
    "interview",
    "plant_canary",
    "check_leak_feed",
    "restrict_access",
    "unrestrict_access",
})

DEFAULT_INTERVIEW_TOPICS: tuple[str, ...] = (
    "recent_documents",
    "contacts_outside",
    "workload",
    "access_needs",
)

HELDOUT_SEED_START = 800_000
HELDOUT_SEED_STOP = 800_030
HELDOUT_SEEDS_PER_TIER = HELDOUT_SEED_STOP - HELDOUT_SEED_START
EPISODES_PER_CONDITION = len(CANONICAL_TIERS) * HELDOUT_SEEDS_PER_TIER
HELDOUT_WORLD_SECRET = "canary-tiebreak-heldout-v14-eval-01"
EXPECTED_WORLD_SECRET_TAG = "sha256:ebf2f09716cf76d3"

JUDGE_SEED_MIN = 900_000
MAX_SUMMARY_BYTES = 75 * 1024
MAX_CHECK_SECONDS = 15.0

DEFAULT_OUT_JSON = Path("results/tiebreak/channel_ablation/channel_ablation_summary.json")
DEFAULT_OUT_MD = Path("docs/reports/tiebreak_channel_ablation.md")
LEDGER_REL = Path("results/tiebreak/experiment_ledger.json")
FRONTIER_CMP_REL = Path("results/tiebreak/frontier_comparison/comparison_summary.json")
BEHAVIOUR_COMPARE_REL = Path("results/behaviour_compare_v1.4.md")

POLICY_ORDER: tuple[str, ...] = (
    "empirical_bayes",
    "compact_linear_dagger",
)

POLICY_META_SPECS: dict[str, dict[str, Any]] = {
    "empirical_bayes": {
        "policy_id": "empirical_bayes",
        "policy_class": "EmpiricalBayesPolicy",
        "run_id": "empirical-bayes-v14",
        "module_path": "train/empirical_bayes_policy.py",
        "summary_path": "results/tiebreak/empirical_bayes/summary.json",
        "expected_param_count": 11,
        "expected_train_seed_range": "102000..102779",
    },
    "compact_linear_dagger": {
        "policy_id": "compact_linear_dagger",
        "policy_class": "CompactLinearDAggerPolicy",
        "run_id": "compact-linear-dagger-v14",
        "module_path": "train/compact_dagger_ablation.py",
        "summary_path": "results/tiebreak/dagger_ablation/summary.json",
        "expected_param_count": 785,
        "expected_train_seed_range": "109000..109509",
    },
}

CONDITION_SPECS: tuple[dict[str, Any], ...] = (
    {
        "condition_id": "full_all_channels",
        "group": "baseline",
        "ablated_channel": "none",
        "enabled_channels": PUBLIC_CHANNELS,
        "interview_heavy": False,
        "label": "Full Policy (all 5 public channels)",
    },
    {
        "condition_id": "loo_no_canary_traps",
        "group": "loo",
        "ablated_channel": "canary_traps",
        "enabled_channels": ("doc_membership", "access_logs", "angry_messages", "interviews"),
        "interview_heavy": False,
        "label": "LOO: mask canary_traps (variant traps + canary leaks)",
    },
    {
        "condition_id": "loo_no_doc_membership",
        "group": "loo",
        "ablated_channel": "doc_membership",
        "enabled_channels": ("canary_traps", "access_logs", "angry_messages", "interviews"),
        "interview_heavy": False,
        "label": "LOO: mask doc_membership (regular doc recipient sets + leaks)",
    },
    {
        "condition_id": "loo_no_access_logs",
        "group": "loo",
        "ablated_channel": "access_logs",
        "enabled_channels": ("canary_traps", "doc_membership", "angry_messages", "interviews"),
        "interview_heavy": False,
        "label": "LOO: mask access_logs (after-hours + volume logs)",
    },
    {
        "condition_id": "loo_no_angry_messages",
        "group": "loo",
        "ablated_channel": "angry_messages",
        "enabled_channels": ("canary_traps", "doc_membership", "access_logs", "interviews"),
        "interview_heavy": False,
        "label": "LOO: mask angry_messages (decoy + disgruntled email cues)",
    },
    {
        "condition_id": "loo_no_interviews",
        "group": "loo",
        "ablated_channel": "interviews",
        "enabled_channels": ("canary_traps", "doc_membership", "access_logs", "angry_messages"),
        "interview_heavy": False,
        "label": "LOO: mask interviews (evasive answer cues, LR=1.2)",
    },
    {
        "condition_id": "interviews_heavy_no_canary",
        "group": "counterfactual",
        "ablated_channel": "canary_traps",
        "enabled_channels": ("doc_membership", "access_logs", "angry_messages", "interviews"),
        "interview_heavy": True,
        "label": "Counterfactual: interviews_heavy_no_canary (~52% interview share, 0 canaries)",
    },
    {
        "condition_id": "only_canary_traps",
        "group": "single_channel",
        "ablated_channel": "all_except_canary_traps",
        "enabled_channels": ("canary_traps",),
        "interview_heavy": False,
        "label": "Single-channel: only canary_traps",
    },
    {
        "condition_id": "only_doc_membership",
        "group": "single_channel",
        "ablated_channel": "all_except_doc_membership",
        "enabled_channels": ("doc_membership",),
        "interview_heavy": False,
        "label": "Single-channel: only doc_membership",
    },
    {
        "condition_id": "only_access_logs",
        "group": "single_channel",
        "ablated_channel": "all_except_access_logs",
        "enabled_channels": ("access_logs",),
        "interview_heavy": False,
        "label": "Single-channel: only access_logs",
    },
    {
        "condition_id": "only_angry_messages",
        "group": "single_channel",
        "ablated_channel": "all_except_angry_messages",
        "enabled_channels": ("angry_messages",),
        "interview_heavy": False,
        "label": "Single-channel: only angry_messages",
    },
    {
        "condition_id": "only_interviews",
        "group": "single_channel",
        "ablated_channel": "all_except_interviews",
        "enabled_channels": ("interviews",),
        "interview_heavy": False,
        "label": "Single-channel: only interviews",
    },
)

CONDITION_ORDER: tuple[str, ...] = tuple(c["condition_id"] for c in CONDITION_SPECS)
CONDITION_MAP: dict[str, dict[str, Any]] = {c["condition_id"]: c for c in CONDITION_SPECS}
LOO_CONDITION_IDS: tuple[str, ...] = tuple(
    c["condition_id"] for c in CONDITION_SPECS if c["group"] == "loo"
)
SINGLE_CONDITION_IDS: tuple[str, ...] = tuple(
    c["condition_id"] for c in CONDITION_SPECS if c["group"] == "single_channel"
)

FALLBACK_FRONTIER_BEHAVIOUR_V14: dict[str, dict[str, Any]] = {
    "opencode_gpt_5_5_hard": {
        "agent_label": "gpt-5.5 (OpenCode over MCP)",
        "dev_eval_seed_range": "0..29",
        "tier": "hard",
        "n": 30,
        "mean_score": 0.5037,
        "ci95": 0.0638,
        "luck_adjusted_ev": 0.4176,
        "canaries_planted_per_ep": 17.2,
        "canaries_before_accuse_per_ep": 17.13,
        "canary_slot_utilization": 0.8454,
        "interviews_per_ep": 4.2,
        "interview_call_share": 0.06,
        "mean_tool_calls": 69,
        "mean_accuse_day": 10.2,
        "correct_count": 28,
        "wrong_count": 0,
        "abstain_count": 2,
    },
    "opencode_gemini_4_carbon_hard": {
        "agent_label": "gemini-4-carbon (OpenCode over MCP)",
        "dev_eval_seed_range": "0..29",
        "tier": "hard",
        "n": 30,
        "mean_score": 0.3223,
        "ci95": 0.1989,
        "luck_adjusted_ev": 0.3596,
        "canaries_planted_per_ep": 8.5,
        "canaries_before_accuse_per_ep": 8.47,
        "canary_slot_utilization": 0.3151,
        "interviews_per_ep": 68.0,
        "interview_call_share": 0.53,
        "stated_interview_lr": 1.2,
        "mean_tool_calls": 128,
        "mean_accuse_day": 13.2,
        "correct_count": 25,
        "wrong_count": 4,
        "abstain_count": 1,
    },
}

PANEL_FIX_A_DISCLOSURE = (
    "All 2,160 primary channel-ablation episodes evaluate world-paired HELDOUT_SEEDS 800000..800029 "
    "(n=90 per condition, 30 per tier across easy, medium, hard) under shared deterministic "
    "world_secret_tag sha256:ebf2f09716cf76d3, while all learned policy weights originate strictly "
    "from disjoint TRAIN_SEEDS [100000, 200000) and 0 JUDGE_SEEDS (900k+) are touched. Frontier "
    "behavioral reference numbers on DEV_SEEDS 0..29 (hard, n=30) are cited strictly from committed "
    "replay-verified artifacts and are post-hoc locked, not pre-registered (Panel Fix A)."
)

PANEL_FIX_E_DISCLOSURE = (
    "Per Panel Fix E strict track separation, 0 / 19 historical open-weight Qwen2.5 runs in "
    "experiment_ledger.json beat untrained base (0.000), so the README.md Qwen addendum remains "
    "withheld (HOLD_README_QWEN_ADDENDUM_UNTIL_V100). Both policies audited here "
    "(EmpiricalBayesPolicy and CompactLinearDAggerPolicy; is_open_weight_llm = False) are non-LLM "
    "structured/parametric policies strictly separated from open-weight Qwen2.5 LoRA runs."
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
_INT_TOKEN_RE = re.compile(r"\b\d+\b")
_ACTIONS_CAP_RE = re.compile(r"^\s*-\s*actions_per_day\s*:\s*([0-9.]+)")


class MaskedStep:
    __slots__ = ("t", "day", "tool", "args", "result")

    def __init__(
        self,
        t: int,
        day: int,
        tool: str,
        args: dict[str, Any],
        result: dict[str, Any],
    ) -> None:
        self.t = int(t)
        self.day = int(day)
        self.tool = str(tool)
        self.args = args
        self.result = result


class ChannelObservationFilter:
    """Stateful public-observation channel filter masking selected MCP channels without touching Env."""

    def __init__(
        self,
        enabled_channels: Iterable[str] | frozenset[str] = ALL_CHANNELS_SET,
        interview_heavy: bool = False,
    ) -> None:
        self._enabled: frozenset[str] = frozenset(str(c) for c in enabled_channels)
        if not self._enabled.issubset(ALL_CHANNELS_SET):
            unknown = sorted(self._enabled - ALL_CHANNELS_SET)
            raise ValueError(f"unknown channel(s): {unknown}")
        self._interview_heavy = bool(interview_heavy)
        self._topics: tuple[str, ...] = DEFAULT_INTERVIEW_TOPICS
        self._actions_per_day: int = 8
        self._employees: list[str] = []
        self._seen_interviews: set[tuple[int, str, str]] = set()
        self._canary_doc_ids: set[str] = set()
        self._cur_day: int = 1
        self._actions_used_today: int = 0
        self._raw_refs: list[Any] = []
        self._masked_steps: list[MaskedStep] = []

    @property
    def enabled_channels(self) -> frozenset[str]:
        return self._enabled

    @property
    def interview_heavy(self) -> bool:
        return self._interview_heavy

    @property
    def masked_steps(self) -> list[MaskedStep]:
        return self._masked_steps

    def reset_filter(self, tools_spec: list[dict[str, Any]], instruction: str) -> None:
        self._topics = DEFAULT_INTERVIEW_TOPICS
        self._actions_per_day = 8
        self._employees = []
        self._seen_interviews = set()
        self._canary_doc_ids = set()
        self._cur_day = 1
        self._actions_used_today = 0
        self._raw_refs = []
        self._masked_steps = []

        for line in (instruction or "").splitlines():
            m = _ACTIONS_CAP_RE.match(line)
            if m:
                self._actions_per_day = max(1, int(float(m.group(1))))
                break

        for spec in tools_spec or []:
            if isinstance(spec, dict) and spec.get("name") == "interview":
                schema = spec.get("input_schema") if "input_schema" in spec else spec.get("inputSchema")
                if isinstance(schema, dict):
                    props = schema.get("properties")
                    if isinstance(props, dict) and isinstance(props.get("topic"), dict):
                        enum_vals = props["topic"].get("enum")
                        if isinstance(enum_vals, list) and enum_vals:
                            self._topics = tuple(str(x) for x in enum_vals)
                break

    def _mask_single_step(self, step: Any, fallback_t: int) -> MaskedStep:
        if isinstance(step, dict):
            raw_t = int(step.get("t", fallback_t))
            raw_day = int(step.get("day", self._cur_day))
            tool = str(step.get("tool", ""))
            args = dict(step.get("args") or {})
            res = dict(step.get("result") or {})
        else:
            raw_t = int(getattr(step, "t", fallback_t))
            raw_day = int(getattr(step, "day", self._cur_day))
            tool = str(getattr(step, "tool", ""))
            raw_args = getattr(step, "args", None)
            raw_res = getattr(step, "result", None)
            args = dict(raw_args) if isinstance(raw_args, dict) else {}
            res = dict(raw_res) if isinstance(raw_res, dict) else {}

        ok = bool(res.get("ok", True)) if res else False
        raw_data = res.get("data")
        data = dict(raw_data) if isinstance(raw_data, dict) else {}
        err = res.get("error")

        if ok:
            if tool == "status":
                self._cur_day = int(data.get("day", self._cur_day))
                if "actions_left_today" in data:
                    self._actions_used_today = max(
                        0, self._actions_per_day - int(data["actions_left_today"])
                    )
            elif tool == "advance_day":
                self._cur_day = int(data.get("day", self._cur_day + 1))
                self._actions_used_today = 0
            elif tool in INVESTIGATIVE_MCP_TOOLS:
                self._actions_used_today += 1

            if tool == "list_employees":
                emps = data.get("employees") or []
                self._employees = [
                    str(e["id"]) if isinstance(e, dict) else str(e)
                    for e in emps
                    if (isinstance(e, dict) and "id" in e) or isinstance(e, str)
                ]
            elif tool == "plant_canary":
                cid = str(data.get("canary_id") or "")
                if cid:
                    self._canary_doc_ids.add(cid)
                if "canary_traps" not in self._enabled:
                    args = {"doc_title": str(args.get("doc_title", "")), "assignment": {}}
                    data = {"canary_id": ""}
            elif tool == "list_documents":
                kept_docs: list[dict[str, Any]] = []
                for doc in data.get("documents") or []:
                    if not isinstance(doc, dict):
                        continue
                    is_can = bool(doc.get("is_canary"))
                    if is_can and doc.get("doc_id") is not None:
                        self._canary_doc_ids.add(str(doc["doc_id"]))
                    if is_can and "canary_traps" not in self._enabled:
                        continue
                    if (not is_can) and "doc_membership" not in self._enabled:
                        continue
                    kept_docs.append(doc)
                data = {**data, "documents": kept_docs}
            elif tool == "check_leak_feed":
                kept_items: list[dict[str, Any]] = []
                for item in data.get("items") or []:
                    if not isinstance(item, dict):
                        continue
                    did = str(item.get("doc_id") or "")
                    is_can = (item.get("variant") is not None) or (did in self._canary_doc_ids)
                    if is_can and "canary_traps" not in self._enabled:
                        continue
                    if (not is_can) and "doc_membership" not in self._enabled:
                        continue
                    kept_items.append(item)
                data = {**data, "items": kept_items}
            elif tool == "read_access_logs":
                if "access_logs" not in self._enabled:
                    data = {**data, "logs": []}
            elif tool == "search_messages":
                if "angry_messages" not in self._enabled:
                    data = {**data, "messages": []}
            elif tool == "read_message":
                if "angry_messages" not in self._enabled:
                    data = {
                        **data,
                        "message": {
                            "id": str(args.get("id", "")),
                            "sender": "",
                            "subject": "",
                            "body": "",
                        },
                    }
            elif tool == "interview":
                emp_id = str(args.get("employee") or data.get("employee") or "")
                topic = str(args.get("topic") or data.get("topic") or "")
                if emp_id and topic:
                    self._seen_interviews.add((raw_day, emp_id, topic))
                if "interviews" not in self._enabled:
                    data = {**data, "answer": "Everything is routine on my end."}

        return MaskedStep(
            t=raw_t,
            day=raw_day,
            tool=tool,
            args=args,
            result={"ok": ok, "data": data, "error": err},
        )

    def sync_masked_history(self, history: list[Any]) -> list[MaskedStep]:
        prefix_ok = len(history) >= len(self._raw_refs) and all(
            history[idx] is self._raw_refs[idx] for idx in range(len(self._raw_refs))
        )
        if not prefix_ok:
            self._raw_refs = []
            self._masked_steps = []
            self._seen_interviews = set()
            self._canary_doc_ids = set()
            self._cur_day = 1
            self._actions_used_today = 0
        for idx in range(len(self._raw_refs), len(history)):
            raw_item = history[idx]
            self._masked_steps.append(self._mask_single_step(raw_item, fallback_t=idx))
            self._raw_refs.append(raw_item)
        return self._masked_steps

    def _pick_next_interview(self) -> tuple[str, dict[str, Any]] | None:
        for emp_id in self._employees:
            for topic in self._topics:
                if (self._cur_day, emp_id, topic) not in self._seen_interviews:
                    return ("interview", {"employee": emp_id, "topic": topic})
        return None

    def apply_action_override(self, tool: str, args: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        if self._interview_heavy:
            if tool == "plant_canary":
                if self._actions_used_today < self._actions_per_day:
                    nxt_iv = self._pick_next_interview()
                    if nxt_iv is not None:
                        return nxt_iv
                return ("advance_day", {})
            if (
                tool == "advance_day"
                and self._actions_used_today < self._actions_per_day
                and self._employees
            ):
                nxt_iv = self._pick_next_interview()
                if nxt_iv is not None:
                    return nxt_iv
        return (str(tool), dict(args))


def compute_secret_tag(secret: str) -> str:
    return "sha256:" + hashlib.sha256(secret.encode("utf-8")).hexdigest()[:16]


def canonical_trace_sha256(steps: list[Any]) -> str:
    payload: list[dict[str, Any]] = []
    for idx, st in enumerate(steps):
        if isinstance(st, dict):
            payload.append(
                {
                    "t": int(st.get("t", idx)),
                    "day": int(st.get("day", 1)),
                    "tool": str(st.get("tool", "")),
                    "args": st.get("args") or {},
                    "ok": bool((st.get("result") or {}).get("ok", True)),
                }
            )
        else:
            res = getattr(st, "result", None) or {}
            payload.append(
                {
                    "t": int(getattr(st, "t", idx)),
                    "day": int(getattr(st, "day", 1)),
                    "tool": str(getattr(st, "tool", "")),
                    "args": getattr(st, "args", None) or {},
                    "ok": bool(res.get("ok", True)),
                }
            )
    raw = json.dumps(payload, allow_nan=False, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


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
        "mean": round(mean_v, 5),
        "ci95_low": round(mean_v - half, 5),
        "ci95_high": round(mean_v + half, 5),
        "ci95_half_width": round(half, 5),
    }


def compute_paired_vs_full(
    cond_scores: list[float],
    full_scores: list[float],
) -> dict[str, Any]:
    if len(cond_scores) != len(full_scores) or not cond_scores:
        raise ValueError("paired score vectors must be non-empty and equal length")
    deltas = [float(c) - float(f) for c, f in zip(cond_scores, full_scores)]
    ci = mean_ci95(deltas)
    full_mean = sum(full_scores) / len(full_scores)
    cond_mean = sum(cond_scores) / len(cond_scores)
    voi_drop = round(full_mean - cond_mean, 5)
    voi_share = round(voi_drop / full_mean, 5) if abs(full_mean) > 1e-9 else 0.0
    better = sum(1 for d in deltas if d > 1e-9)
    worse = sum(1 for d in deltas if d < -1e-9)
    tied = len(deltas) - better - worse
    return {
        "mean_delta": ci["mean"],
        "ci95_low": ci["ci95_low"],
        "ci95_high": ci["ci95_high"],
        "ci95_half_width": ci["ci95_half_width"],
        "voi_drop": voi_drop,
        "voi_share_of_full": voi_share,
        "better_count": better,
        "tied_count": tied,
        "worse_count": worse,
    }


def compute_theoretical_channel_kl() -> dict[str, Any]:
    q0 = 0.20
    lr = 1.2
    q1 = q0 * lr
    iv_kl_mole_vs_innocent = q1 * math.log(q1 / q0) + (1.0 - q1) * math.log((1.0 - q1) / (1.0 - q0))
    iv_kl_innocent_vs_mole = q0 * math.log(q0 / q1) + (1.0 - q0) * math.log((1.0 - q0) / (1.0 - q1))

    k_arms = 3
    p_leak = 0.75
    exact_surfaced_kl = math.log(k_arms)
    exact_planted_expected_kl = p_leak * exact_surfaced_kl

    fp_hard = 0.95
    wrong_arm_p = (1.0 - fp_hard) / (k_arms - 1)
    uniform_arm_p = 1.0 / k_arms
    hard_surfaced_kl = fp_hard * math.log(fp_hard / uniform_arm_p) + (1.0 - fp_hard) * math.log(
        wrong_arm_p / uniform_arm_p
    )
    hard_planted_expected_kl = p_leak * hard_surfaced_kl

    return {
        "interview_innocent_evasive_p": round(q0, 4),
        "interview_stated_lr": round(lr, 4),
        "interview_mole_evasive_p": round(q1, 4),
        "interview_kl_nats_per_call": round(iv_kl_mole_vs_innocent, 5),
        "interview_reverse_kl_nats_per_call": round(iv_kl_innocent_vs_mole, 5),
        "canary_3arm_surfaced_exact_kl_nats": round(exact_surfaced_kl, 5),
        "canary_3arm_planted_expected_exact_kl_nats": round(exact_planted_expected_kl, 5),
        "canary_3arm_surfaced_hard_fp95_kl_nats": round(hard_surfaced_kl, 5),
        "canary_3arm_planted_expected_hard_fp95_kl_nats": round(hard_planted_expected_kl, 5),
        "kl_ratio_surfaced_exact_canary_vs_interview": round(
            exact_surfaced_kl / iv_kl_mole_vs_innocent, 2
        ),
        "kl_ratio_planted_exact_canary_vs_interview": round(
            exact_planted_expected_kl / iv_kl_mole_vs_innocent, 2
        ),
        "kl_ratio_planted_hard_canary_vs_interview": round(
            hard_planted_expected_kl / iv_kl_mole_vs_innocent, 2
        ),
    }


def _has_affirmative_prereg_0_29(text: str) -> list[str]:
    hits: list[str] = []
    for lineno, raw_line in enumerate(text.splitlines(), start=1):
        if _PREREG_RE.search(raw_line) and _SEEDS_0_29_RE.search(raw_line):
            scrubbed = _NEGATED_PREREG_RE.sub("", raw_line)
            if _PREREG_RE.search(scrubbed):
                hits.append(f"line {lineno}: {raw_line.strip()[:140]}")
    return hits


def _scan_json_for_judge_numbers(obj: Any, raw_text: str) -> list[str]:
    hits: list[str] = []

    def _walk(node: Any, path: str) -> None:
        if isinstance(node, bool) or node is None:
            return
        if isinstance(node, (int, float)):
            if abs(float(node)) >= JUDGE_SEED_MIN:
                hits.append(f"numeric {path}={node}")
        elif isinstance(node, dict):
            for k, v in node.items():
                _walk(v, f"{path}.{k}")
        elif isinstance(node, list):
            for i, item in enumerate(node):
                _walk(item, f"{path}[{i}]")

    _walk(obj, "root")
    for m in _INT_TOKEN_RE.finditer(raw_text):
        tok = m.group(0)
        start = m.start()
        prefix2 = raw_text[max(0, start - 2) : start]
        if prefix2.lower() == "0x":
            continue
        if int(tok) >= JUDGE_SEED_MIN:
            hits.append(f"token {tok} at offset {start}")
    return hits


_HYGIENE_CACHE: dict[tuple[str, int, int, bool], list[str]] = {}
_AST_ISOLATION_CACHE: dict[tuple[str, int, int], dict[str, Any]] = {}


def check_python_source_hygiene(py_path: Path, run_tokenize: bool = False) -> list[str]:
    resolved = py_path.resolve()
    st = resolved.stat()
    ck = (str(resolved), st.st_mtime_ns, st.st_size, bool(run_tokenize))
    cached = _HYGIENE_CACHE.get(ck)
    if cached is not None:
        return list(cached)
    errs: list[str] = []
    src = resolved.read_text(encoding="utf-8")
    lbl = py_path.name
    if H in src:
        errs.append(f"{lbl}: contains forbidden hash character chr(35)")
    for bad_ch, ch_name in (
        (EM_DASH, "em dash"),
        (EN_DASH, "en dash"),
        (UNICODE_MINUS, "unicode minus"),
    ):
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
    cached = _AST_ISOLATION_CACHE.get(ck)
    if cached is not None:
        return {
            "passed": cached["passed"],
            "policy_classes": list(cached["policy_classes"]),
            "errors": list(cached["errors"]),
        }
    src = resolved.read_text(encoding="utf-8")
    tree = ast.parse(src, filename=str(py_path))
    errors: list[str] = []
    forbidden_prefixes = ("torch", "transformers", "canary.solver", "canary.world")

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                name = alias.name
                if any(name == fp or name.startswith(fp + ".") for fp in forbidden_prefixes):
                    errors.append(f"line {node.lineno}: forbidden import {name}")
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            if any(mod == fp or mod.startswith(fp + ".") for fp in forbidden_prefixes):
                errors.append(f"line {node.lineno}: forbidden from-import {mod}")
            if mod == "canary":
                for alias in node.names:
                    if alias.name in ("solver", "world"):
                        errors.append(f"line {node.lineno}: forbidden from canary import {alias.name}")
        elif isinstance(node, ast.Name) and node.id == "SolverPolicy":
            errors.append(f"line {node.lineno}: forbidden SolverPolicy symbol reference")
        elif isinstance(node, ast.Attribute) and node.attr == "SolverPolicy":
            errors.append(f"line {node.lineno}: forbidden .SolverPolicy attribute reference")

    policy_classes: list[str] = []
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            fn_names = {
                b.name for b in node.body if isinstance(b, (ast.FunctionDef, ast.AsyncFunctionDef))
            }
            if {"reset", "act"}.issubset(fn_names):
                policy_classes.append(f"scripts/{py_path.name}:{node.name}")

    out = {
        "passed": len(errors) == 0 and len(policy_classes) >= 1,
        "policy_classes": policy_classes,
        "errors": errors,
    }
    _AST_ISOLATION_CACHE[ck] = out
    return {
        "passed": out["passed"],
        "policy_classes": list(out["policy_classes"]),
        "errors": list(out["errors"]),
    }


def render_markdown_report(summary: dict[str, Any]) -> str:
    h1 = H
    h2 = H * 2
    h3 = H * 3

    totals = summary["totals"]
    kl = summary["theoretical_channel_kl"]
    pe = summary["panel_fix_e_track_separation"]
    fb = summary["frontier_behaviour_bridge"]
    gem = fb["opencode_gemini_4_carbon_hard"]
    gpt = fb["opencode_gpt_5_5_hard"]

    eb = summary["policies"]["empirical_bayes"]
    cd = summary["policies"]["compact_linear_dagger"]
    eb_full = eb["conditions"]["full_all_channels"]
    cd_full = cd["conditions"]["full_all_channels"]
    eb_nocan = eb["conditions"]["loo_no_canary_traps"]
    cd_nocan = cd["conditions"]["loo_no_canary_traps"]
    eb_ivh = eb["conditions"]["interviews_heavy_no_canary"]
    cd_ivh = cd["conditions"]["interviews_heavy_no_canary"]
    eb_llr = eb["commitment_llr_decomposition"]

    lines: list[str] = [
        f"{h1} Public-Channel Value-of-Information (VoI) & Observation-Masking Ablation Audit (`v1.4`)",
        "",
        (
            "Keyless CPU-only Leave-One-Out (LOO), single-channel, and counterfactual interview-heavy "
            f"ablation audit across `{totals['total_episodes']:,}` world-paired held-out episodes "
            f"(`{len(POLICY_ORDER)}` policies x `{len(CONDITION_ORDER)}` channel regimes x `n={summary['episodes_per_condition']}` "
            f"on `HELDOUT_SEEDS {summary['heldout_seed_range']}`, `{summary['eval_seeds_per_tier']}`/tier across "
            f"`easy`, `medium`, `hard` under `{summary['world_secret_tag']}`, `TemplateProvider()`). "
            f"Masking `canary_traps` collapses `EmpiricalBayesPolicy` from **`{eb_full['overall']['mean_score']:+.4f}`** "
            f"to **`{eb_nocan['overall']['mean_score']:+.4f}`** (`{eb_nocan['paired_vs_full']['mean_delta']:+.4f}`, "
            f"`{eb_nocan['paired_vs_full']['voi_share_of_full'] * 100.0:.1f}%` VoI share) and `CompactLinearDAggerPolicy` "
            f"from **`{cd_full['overall']['mean_score']:+.4f}`** to **`{cd_nocan['overall']['mean_score']:+.4f}`** "
            f"(`{cd_nocan['paired_vs_full']['mean_delta']:+.4f}`, `{cd_nocan['paired_vs_full']['voi_share_of_full'] * 100.0:.1f}%` "
            f"VoI share), proving that **active canary traps carry `{totals['pooled_canary_voi_share_of_full'] * 100.0:.1f}%` "
            "of decisive held-out policy value**."
        ),
        "",
        (
            f"- **Seed & Secret Provenance (Panel Fix A)**: All `{totals['total_episodes']:,}` primary ablation episodes "
            f"(plus `{totals['fresh_env_replays_verified']}` fresh `Env` replay checks) evaluate strictly on world-paired "
            f"`HELDOUT_SEEDS {summary['heldout_seed_range']}` under `{summary['world_secret_tag']}`, all learned weights "
            "come strictly from disjoint `TRAIN_SEEDS [100000, 200000)` (`102000..102779` and `109000..109509`), and "
            "**`0` `JUDGE_SEEDS` (`900k+`) are touched**. Frontier MCP reference rows on `DEV_SEEDS 0..29` (`hard`, `n=30`) "
            "are cited from committed replay-verified runs and are **post-hoc locked, not pre-registered**."
        ),
        (
            f"- **Strict Track Separation (Panel Fix E)**: `{pe['open_weight_qwen25_above_zero_ratio']}` historical "
            "open-weight `Qwen2.5` runs in `experiment_ledger.json` exceed untrained `base` (`0.000`), so the `README.md` "
            f"Qwen addendum remains withheld (`{pe['readme_qwen_addendum_status']}`). Both policies audited here "
            "(`EmpiricalBayesPolicy`, `CompactLinearDAggerPolicy`; `is_open_weight_llm = False`) are non-LLM "
            "parametric policies strictly separated from open-weight `Qwen2.5` LoRA runs."
        ),
        "",
        f"{h2} 1. Leave-One-Out (LOO) & Counterfactual VoI Matrix (`HELDOUT_SEEDS {summary['heldout_seed_range']}`, `n=90` / Row)",
        "",
        "| Policy (`run_id`) | Condition | Score (`95% CI`) | Paired `Delta` vs Full (`95% CI`) | VoI Share of Full | Acc | Wrong | Abstain | Canaries / Ep | Interview Share |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]

    primary_conds = (
        "full_all_channels",
        "loo_no_canary_traps",
        "loo_no_doc_membership",
        "loo_no_access_logs",
        "loo_no_angry_messages",
        "loo_no_interviews",
        "interviews_heavy_no_canary",
    )
    for pid in POLICY_ORDER:
        pb = summary["policies"][pid]
        for cid in primary_conds:
            cb = pb["conditions"][cid]
            ov = cb["overall"]
            pv = cb["paired_vs_full"]
            share_cell = (
                "baseline"
                if cid == "full_all_channels"
                else f"`{pv['voi_share_of_full'] * 100.0:.1f}%`"
            )
            lines.append(
                f"| `{pb['policy_class']}` (`{pb['run_id']}`) | `{cid}` | "
                f"`{ov['mean_score']:+.4f} [{ov['ci95_low']:+.4f}, {ov['ci95_high']:+.4f}]` | "
                f"`{pv['mean_delta']:+.4f} [{pv['ci95_low']:+.4f}, {pv['ci95_high']:+.4f}]` | "
                f"{share_cell} | `{ov['accuracy'] * 100.0:.1f}%` | `{ov['wrong_accuse_rate'] * 100.0:.1f}%` | "
                f"`{ov['abstain_rate'] * 100.0:.1f}%` | `{ov['mean_canaries_planted']:.2f}` | "
                f"`{ov['interview_call_share'] * 100.0:.1f}%` |"
            )

    lines.extend(
        [
            "",
            f"{h2} 2. Single-Channel Sufficiency Matrix (`only_*`, `HELDOUT_SEEDS {summary['heldout_seed_range']}`, `n=90` / Row)",
            "",
            "| Policy | Single Active Channel | Score (`95% CI`) | Paired `Delta` vs Full (`95% CI`) | Retained Share of Full | Acc | Wrong | Abstain |",
            "|---|---|---:|---:|---:|---:|---:|---:|",
        ]
    )

    for pid in POLICY_ORDER:
        pb = summary["policies"][pid]
        full_m = float(pb["conditions"]["full_all_channels"]["overall"]["mean_score"])
        for cid in SINGLE_CONDITION_IDS:
            cb = pb["conditions"][cid]
            ov = cb["overall"]
            pv = cb["paired_vs_full"]
            retained = (float(ov["mean_score"]) / full_m * 100.0) if full_m > 1e-9 else 0.0
            lines.append(
                f"| `{pb['policy_class']}` | `{cid}` | "
                f"`{ov['mean_score']:+.4f} [{ov['ci95_low']:+.4f}, {ov['ci95_high']:+.4f}]` | "
                f"`{pv['mean_delta']:+.4f} [{pv['ci95_low']:+.4f}, {pv['ci95_high']:+.4f}]` | "
                f"`{retained:.1f}%` | `{ov['accuracy'] * 100.0:.1f}%` | "
                f"`{ov['wrong_accuse_rate'] * 100.0:.1f}%` | `{ov['abstain_rate'] * 100.0:.1f}%` |"
            )

    lines.extend(
        [
            "",
            f"{h2} 3. Per-Tier Breakdown on Key Channel Regimes (`easy` / `medium` / `hard`, `n=30` / Cell)",
            "",
            "| Policy | Condition | `easy` (`n=30`) | `medium` (`n=30`) | `hard` (`n=30`) | Pooled (`n=90`) |",
            "|---|---|---:|---:|---:|---:|",
        ]
    )

    for pid in POLICY_ORDER:
        pb = summary["policies"][pid]
        for cid in (
            "full_all_channels",
            "loo_no_canary_traps",
            "loo_no_doc_membership",
            "loo_no_access_logs",
            "loo_no_angry_messages",
            "loo_no_interviews",
            "interviews_heavy_no_canary",
            "only_canary_traps",
        ):
            cb = pb["conditions"][cid]
            bt = cb["by_tier"]
            lines.append(
                f"| `{pb['policy_class']}` | `{cid}` | "
                f"`{bt['easy']['mean_score']:+.4f}` (`{bt['easy']['accuracy'] * 100.0:.0f}%`) | "
                f"`{bt['medium']['mean_score']:+.4f}` (`{bt['medium']['accuracy'] * 100.0:.0f}%`) | "
                f"`{bt['hard']['mean_score']:+.4f}` (`{bt['hard']['accuracy'] * 100.0:.0f}%`) | "
                f"`{cb['overall']['mean_score']:+.4f}` (`{cb['overall']['accuracy'] * 100.0:.1f}%`) |"
            )

    lines.extend(
        [
            "",
            f"{h2} 4. Shannon KL-per-Action Theory, Commitment LLR Share & Frontier Bridge",
            "",
            f"{h3} 4.1 Exact Per-Call KL Divergence (`canary_traps` vs `interview`)",
            "",
            (
                f"- **3-Arm Canary Trap (`plant_canary`, `max_variants=3`, `p_leak=0.75`)**: Each surfaced exact canary "
                f"(`easy`/`medium`, `fingerprint_accuracy=1.0`) yields **`{kl['canary_3arm_surfaced_exact_kl_nats']:.5f}` nats** "
                f"(`ln 3`), or **`{kl['canary_3arm_planted_expected_exact_kl_nats']:.5f}` nats** expected per planted canary; "
                f"on `hard` (`fingerprint_accuracy=0.95`), each surfaced canary yields **`{kl['canary_3arm_surfaced_hard_fp95_kl_nats']:.5f}` nats** "
                f"(`{kl['canary_3arm_planted_expected_hard_fp95_kl_nats']:.5f}` nats expected per planted canary)."
            ),
            (
                f"- **Interview (`interview`, stated `LR={kl['interview_stated_lr']}`, `p_evasive_innocent={kl['interview_innocent_evasive_p']}` -> "
                f"`p_evasive_mole={kl['interview_mole_evasive_p']}`)**: Each interview yields only **`{kl['interview_kl_nats_per_call']:.5f}` nats** "
                f"(`KL(Bern(0.24) || Bern(0.20))`), making a single planted 3-arm canary worth **`{kl['kl_ratio_planted_exact_canary_vs_interview']:.1f}x`** "
                f"(`easy`/`medium`) to **`{kl['kl_ratio_planted_hard_canary_vs_interview']:.1f}x`** (`hard`) as much expected information as an interview "
                f"(`{kl['kl_ratio_surfaced_exact_canary_vs_interview']:.1f}x` per surfaced exact canary)."
            ),
            (
                f"- **Terminal Commitment LLR Decomposition (`EmpiricalBayesPolicy`, `n=90`)**: Mean top-vs-runner-up log-odds margin at episode end is "
                f"**`{eb_llr['mean_total_top_vs_second_llr']:+.4f}` nats**, of which canary variant hits/misses + canary recipient narrowing supply "
                f"**`{eb_llr['canary_inclusive_llr_share'] * 100.0:.1f}%`** (`{eb_llr['mean_canary_variant_llr']:+.4f}` pure variant LLR + "
                f"`{eb_llr['mean_canary_recipient_llr']:+.4f}` canary-recipient LLR), passive regular `doc_membership` supplies "
                f"`{eb_llr['mean_regular_doc_llr']:+.4f}` nats, `access_logs` `{eb_llr['mean_access_logs_llr']:+.4f}` nats, "
                f"`angry_messages` `{eb_llr['mean_angry_messages_llr']:+.4f}` nats, and `interviews` `{eb_llr['mean_interviews_llr']:+.4f}` nats."
            ),
            "",
            f"{h3} 4.2 Mechanistic Explanation of the Frontier MCP Gap (`gpt-5.5` vs `gemini-4-carbon`)",
            "",
            (
                f"On post-hoc locked `DEV_SEEDS 0..29` (`hard`, `n=30`, not pre-registered; `results/behaviour_compare_v1.4.md`), "
                f"`gpt-5.5` (OpenCode over MCP) plants **`{gpt['canaries_planted_per_ep']:.1f}`** canaries/ep (`{gpt['canary_slot_utilization'] * 100.0:.1f}%` "
                f"slot utilization) with only **`{gpt['interviews_per_ep']:.1f}`** interviews/ep (`{gpt['interview_call_share'] * 100.0:.0f}%` of calls) "
                f"to score **`{gpt['mean_score']:+.3f}`** (`{gpt['correct_count']}/{gpt['n']}` correct, `0` wrong). Under the identical MCP tools and "
                f"instructions, `gemini-4-carbon` spends **`{gem['interview_call_share'] * 100.0:.0f}%`** of its `{gem['mean_tool_calls']}` calls on "
                f"interviews (`{gem['interviews_per_ep']:.1f}`/ep, stated `LR={gem['stated_interview_lr']}`), plants half as many canaries "
                f"(`{gem['canaries_planted_per_ep']:.1f}`/ep, `{gem['canary_slot_utilization'] * 100.0:.1f}%` slot utilization), and drops to "
                f"**`{gem['mean_score']:+.3f}`** (`{gem['wrong_count']}` wrong accusations). Our `interviews_heavy_no_canary` counterfactual isolates "
                f"the endpoint of that substitution on `HELDOUT_SEEDS {summary['heldout_seed_range']}`: reallocating canary slots into interviews "
                f"(`{eb_ivh['overall']['interview_call_share'] * 100.0:.1f}%` and `{cd_ivh['overall']['interview_call_share'] * 100.0:.1f}%` interview call share) "
                f"collapses `EmpiricalBayesPolicy` to **`{eb_ivh['overall']['mean_score']:+.4f}`** and `CompactLinearDAggerPolicy` to "
                f"**`{cd_ivh['overall']['mean_score']:+.4f}`**, confirming that passive channels + `LR=1.2` interviews cannot cross the `1/(1+V)` accusation threshold."
            ),
            "",
            f"{h2} 5. Offline Reproducibility Commands",
            "",
            "```bash",
            "python scripts/tiebreak_channel_ablation_audit.py --check",
            "pytest -q tests/test_tiebreak_channel_ablation.py tests/test_reproduce_tiebreak_all.py",
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

    repo_root = repo_root.resolve()
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
        if not txt.isascii():
            errors.append(f"{lbl}: contains non-ASCII character(s)")
        prereg_hits = _has_affirmative_prereg_0_29(txt)
        if prereg_hits:
            errors.append(f"{lbl}: Panel Fix A violation at {prereg_hits[0]}")

    script_cand = repo_root / "scripts" / "tiebreak_channel_ablation_audit.py"
    target_script = script_cand if script_cand.is_file() else Path(__file__).resolve()
    errors.extend(check_python_source_hygiene(target_script))

    test_cand = repo_root / "tests" / "test_tiebreak_channel_ablation.py"
    if test_cand.is_file():
        errors.extend(check_python_source_hygiene(test_cand))

    ast_res = audit_module_ast_isolation(target_script)
    if not ast_res["passed"]:
        errors.extend(ast_res["errors"] or ["AST isolation check failed"])
    for req_cls in (
        "scripts/tiebreak_channel_ablation_audit.py:MaskedEmpiricalBayesPolicy",
        "scripts/tiebreak_channel_ablation_audit.py:MaskedCompactLinearDAggerPolicy",
    ):
        if req_cls not in ast_res["policy_classes"]:
            errors.append(f"AST audit missing {req_cls}")

    if summary.get("schema") != SCHEMA_VERSION:
        errors.append(f"unexpected schema: {summary.get('schema')!r}")
    if summary.get("world_secret_tag") != EXPECTED_WORLD_SECRET_TAG:
        errors.append(f"unexpected world_secret_tag: {summary.get('world_secret_tag')!r}")
    if summary.get("heldout_seed_range") != "800000..800029":
        errors.append(f"unexpected heldout_seed_range: {summary.get('heldout_seed_range')!r}")
    if summary.get("eval_seed_range") != "800000..800029":
        errors.append(f"unexpected eval_seed_range: {summary.get('eval_seed_range')!r}")
    if summary.get("public_channels") != list(PUBLIC_CHANNELS):
        errors.append("public_channels list mismatch")

    iso = summary.get("seed_isolation") or {}
    if int(iso.get("judge_episodes_touched", 1)) != 0:
        errors.append("seed_isolation.judge_episodes_touched must be 0")
    if int(iso.get("dev_episodes_rolled_out", 1)) != 0:
        errors.append("seed_isolation.dev_episodes_rolled_out must be 0")
    if int(iso.get("train_episodes_in_heldout_eval", 1)) != 0:
        errors.append("seed_isolation.train_episodes_in_heldout_eval must be 0")

    ledger_cand = repo_root / LEDGER_REL
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
        pe = summary.get("panel_fix_e_track_separation") or {}
        if int(pe.get("open_weight_qwen25_runs_total", -1)) != len(hist_runs) or int(
            pe.get("open_weight_qwen25_runs_above_zero", -1)
        ) != qwen_pos:
            errors.append("panel_fix_e_track_separation out of sync with experiment_ledger.json")

    expected_kl = compute_theoretical_channel_kl()
    if summary.get("theoretical_channel_kl") != expected_kl:
        errors.append("theoretical_channel_kl mismatch against exact analytic formula")

    policies_block = summary.get("policies") or {}
    full_sum = 0.0
    nocan_sum = 0.0
    total_eps_counted = 0

    for pid in POLICY_ORDER:
        if pid not in policies_block:
            errors.append(f"missing policy block: {pid}")
            continue
        pb = policies_block[pid]
        mspec = POLICY_META_SPECS[pid]
        if pb.get("is_open_weight_llm") is not False:
            errors.append(f"{pid}: is_open_weight_llm must be False")
        if int(pb.get("param_count", -1)) != int(mspec["expected_param_count"]):
            errors.append(f"{pid}: param_count mismatch")
        if pb.get("train_seed_range") != mspec["expected_train_seed_range"]:
            errors.append(f"{pid}: train_seed_range mismatch")

        conds = pb.get("conditions") or {}
        if "full_all_channels" not in conds:
            errors.append(f"{pid}: missing full_all_channels")
            continue
        full_csv = str(conds["full_all_channels"].get("episode_scores_csv") or "")
        full_vec = [float(tok) for tok in full_csv.split(",") if tok.strip()]
        if len(full_vec) != EPISODES_PER_CONDITION:
            errors.append(f"{pid}/full_all_channels: expected {EPISODES_PER_CONDITION} episode_scores_csv")
            continue

        for cid in CONDITION_ORDER:
            if cid not in conds:
                errors.append(f"{pid}: missing condition {cid}")
                continue
            cb = conds[cid]
            c_csv = str(cb.get("episode_scores_csv") or "")
            vec = [float(tok) for tok in c_csv.split(",") if tok.strip()]
            if len(vec) != EPISODES_PER_CONDITION:
                errors.append(f"{pid}/{cid}: expected {EPISODES_PER_CONDITION} episode_scores_csv, got {len(vec)}")
                continue
            total_eps_counted += len(vec)

            recomp_ci = mean_ci95([float(x) for x in vec])
            ov = cb.get("overall") or {}
            if abs(float(ov.get("mean_score", -9.0)) - recomp_ci["mean"]) > 1e-4:
                errors.append(f"{pid}/{cid}: overall.mean_score disagrees with episode_scores")
            if abs(float(ov.get("ci95_low", -9.0)) - recomp_ci["ci95_low"]) > 1e-4:
                errors.append(f"{pid}/{cid}: overall.ci95_low disagrees with episode_scores")
            if abs(float(ov.get("ci95_high", -9.0)) - recomp_ci["ci95_high"]) > 1e-4:
                errors.append(f"{pid}/{cid}: overall.ci95_high disagrees with episode_scores")

            c_cnt = int(ov.get("correct_count", -1))
            w_cnt = int(ov.get("wrong_count", -1))
            a_cnt = int(ov.get("abstain_count", -1))
            if c_cnt + w_cnt + a_cnt != EPISODES_PER_CONDITION:
                errors.append(f"{pid}/{cid}: terminal counts do not sum to {EPISODES_PER_CONDITION}")

            bt = cb.get("by_tier") or {}
            for t_idx, tier in enumerate(CANONICAL_TIERS):
                sl = [float(x) for x in vec[t_idx * HELDOUT_SEEDS_PER_TIER : (t_idx + 1) * HELDOUT_SEEDS_PER_TIER]]
                t_ci = mean_ci95(sl)
                tb = bt.get(tier) or {}
                if abs(float(tb.get("mean_score", -9.0)) - t_ci["mean"]) > 1e-4:
                    errors.append(f"{pid}/{cid}/{tier}: tier mean_score disagrees with episode_scores slice")

            recomp_pv = compute_paired_vs_full([float(x) for x in vec], [float(x) for x in full_vec])
            pv = cb.get("paired_vs_full") or {}
            for pk in ("mean_delta", "ci95_low", "ci95_high", "voi_drop", "voi_share_of_full"):
                if abs(float(pv.get(pk, -9.0)) - float(recomp_pv[pk])) > 2e-4:
                    errors.append(f"{pid}/{cid}: paired_vs_full.{pk} mismatch")
            for ik in ("better_count", "tied_count", "worse_count"):
                if int(pv.get(ik, -1)) != int(recomp_pv[ik]):
                    errors.append(f"{pid}/{cid}: paired_vs_full.{ik} mismatch")

        eb_or_cd_full = float(conds["full_all_channels"]["overall"]["mean_score"])
        eb_or_cd_nocan = float(conds["loo_no_canary_traps"]["overall"]["mean_score"])
        full_sum += eb_or_cd_full
        nocan_sum += eb_or_cd_nocan
        if eb_or_cd_full - eb_or_cd_nocan < 0.50:
            errors.append(f"{pid}: expected canary LOO drop >= 0.50, got {eb_or_cd_full - eb_or_cd_nocan:.4f}")
        ivh_sh = float(conds["interviews_heavy_no_canary"]["overall"]["interview_call_share"])
        if ivh_sh < 0.45:
            errors.append(f"{pid}: expected interviews_heavy_no_canary share >= 0.45, got {ivh_sh:.4f}")

    totals = summary.get("totals") or {}
    expected_total_eps = len(POLICY_ORDER) * len(CONDITION_ORDER) * EPISODES_PER_CONDITION
    if int(totals.get("total_episodes", -1)) != expected_total_eps or total_eps_counted != expected_total_eps:
        errors.append(f"totals.total_episodes != {expected_total_eps}")
    if full_sum > 0.0:
        exp_pooled_share = round((full_sum - nocan_sum) / full_sum, 5)
        if abs(float(totals.get("pooled_canary_voi_share_of_full", -1.0)) - exp_pooled_share) > 2e-4:
            errors.append("totals.pooled_canary_voi_share_of_full mismatch")

    expected_md = render_markdown_report(summary)
    if md_txt != expected_md:
        errors.append(f"{m_file.name}: markdown text out of sync with render_markdown_report(summary)")

    required_md_tokens = (
        "800000..800029",
        EXPECTED_WORLD_SECRET_TAG,
        "post-hoc locked, not pre-registered",
        "0 / 19",
        "EmpiricalBayesPolicy",
        "CompactLinearDAggerPolicy",
        "loo_no_canary_traps",
        "loo_no_doc_membership",
        "loo_no_access_logs",
        "loo_no_angry_messages",
        "loo_no_interviews",
        "interviews_heavy_no_canary",
    )
    for tok in required_md_tokens:
        if tok not in md_txt:
            errors.append(f"{m_file.name}: missing required verified token {tok!r}")

    elapsed = time.perf_counter() - t0
    if enforce_budget and elapsed > MAX_CHECK_SECONDS:
        errors.append(f"--check elapsed {elapsed:.4f}s exceeded {MAX_CHECK_SECONDS:.2f}s budget")
    return errors


def verify_artifacts(root: Path = ROOT) -> dict[str, Any]:
    resolved = root.resolve()
    errs = verify_committed_artifacts(
        summary_path=resolved / DEFAULT_OUT_JSON,
        md_path=resolved / DEFAULT_OUT_MD,
        repo_root=resolved,
    )
    return {"passed": len(errs) == 0, "errors": errs}


def build_arg_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description="Public-channel Value-of-Information (VoI) and observation-masking ablation audit."
    )
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
        print(
            json.dumps(
                {
                    "schema": SCHEMA_VERSION,
                    "passed": len(errs) == 0,
                    "errors": errs,
                    "elapsed_seconds": elapsed,
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0 if not errs else 1
    if errs:
        for err in errs:
            print(f"FAIL: {err}", file=sys.stderr)
        return 1
    rel_j = out_json.relative_to(root) if out_json.is_relative_to(root) else out_json
    rel_m = out_md.relative_to(root) if out_md.is_relative_to(root) else out_md
    print(f"OK: verified {rel_j} and {rel_m} (2160 episodes, 12 channel regimes, 0 AST leaks) in {elapsed:.4f}s")
    return 0


if __name__ == "__main__" and "--check" in sys.argv[1:]:
    raise SystemExit(_run_check_cli(build_arg_parser().parse_args()))


from train.compact_dagger_ablation import CompactLinearDAggerPolicy, CompactLinearWeights
from train.empirical_bayes_policy import EmpiricalBayesParams, EmpiricalBayesPolicy


class MaskedEmpiricalBayesPolicy(EmpiricalBayesPolicy):
    def __init__(
        self,
        params: EmpiricalBayesParams | None = None,
        seed: int = 0,
        enabled_channels: Iterable[str] | frozenset[str] = ALL_CHANNELS_SET,
        interview_heavy: bool = False,
        name: str | None = None,
    ) -> None:
        super().__init__(params=params, seed=seed, name=name)
        self._masker = ChannelObservationFilter(
            enabled_channels=enabled_channels,
            interview_heavy=interview_heavy,
        )

    @property
    def masked_steps(self) -> list[MaskedStep]:
        return self._masker.masked_steps

    def reset(self, tools_spec: list[dict[str, Any]], instruction: str) -> None:
        self._masker.reset_filter(tools_spec, instruction)
        super().reset(tools_spec, instruction)

    def act(self, history: list[Any]) -> tuple[str, dict[str, Any]]:
        masked = self._masker.sync_masked_history(history)
        raw_tool, raw_args = super().act(masked)
        return self._masker.apply_action_override(raw_tool, raw_args)


class MaskedCompactLinearDAggerPolicy(CompactLinearDAggerPolicy):
    def __init__(
        self,
        weights: CompactLinearWeights | None = None,
        enabled_channels: Iterable[str] | frozenset[str] = ALL_CHANNELS_SET,
        interview_heavy: bool = False,
        name: str | None = None,
    ) -> None:
        super().__init__(weights=weights, name=name)
        self._masker = ChannelObservationFilter(
            enabled_channels=enabled_channels,
            interview_heavy=interview_heavy,
        )

    @property
    def masked_steps(self) -> list[MaskedStep]:
        return self._masker.masked_steps

    def reset(self, tools_spec: list[dict[str, Any]], instruction: str) -> None:
        self._masker.reset_filter(tools_spec, instruction)
        super().reset(tools_spec, instruction)

    def act(self, history: list[Any]) -> tuple[str, dict[str, Any]]:
        masked = self._masker.sync_masked_history(history)
        raw_tool, raw_args = super().act(masked)
        return self._masker.apply_action_override(raw_tool, raw_args)


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


@contextlib.contextmanager
def _fast_compact_dagger_features() -> Iterator[None]:
    import numpy as np
    import train.compact_dagger_ablation as cda

    orig_fn = cda.extract_employee_features

    def _fast_extract_employee_features(state: Any) -> Any:
        if state._emp_feats_cache is not None:
            return state._emp_feats_cache
        eids = state.emp_ids
        n = len(eids)
        if n == 0:
            empty = np.zeros((0, cda.D_EMP), dtype=np.float64)
            state._emp_feats_cache = empty
            return empty
        fp_acc = float(state.params.get("fingerprint_accuracy", 1.0))
        exact_fp = 1.0 if fp_acc >= 0.999 else 0.0
        noisy_fp = 1.0 - exact_fp
        has_decoy = 1.0 if state.params.get("decoy", False) else 0.0
        has_framing = 1.0 if state.params.get("framing", False) else 0.0
        careful = 1.0 if state.params.get("careful_mole", False) else 0.0

        ah_list = [float(state.after_hours_logs[e]) for e in eids]
        tot_list = [float(state.total_logs[e]) for e in eids]
        ang_list = [float(state.angry_msgs[e]) for e in eids]
        s_ah = sorted(ah_list)
        s_tot = sorted(tot_list)
        s_ang = sorted(ang_list, reverse=True)
        mid = n // 2
        med_ah = s_ah[mid] if (n % 2 == 1) else 0.5 * (s_ah[mid - 1] + s_ah[mid])
        med_tot = s_tot[mid] if (n % 2 == 1) else 0.5 * (s_tot[mid - 1] + s_tot[mid])
        max_ang = s_ang[0]
        second_ang = s_ang[1] if n > 1 else 0.0

        inv_sqrt_ld = 1.0 / math.sqrt(max(1.0, float(state.logged_days_count)))
        base_ben = max(0.0, med_tot - med_ah)
        doc_leaks = float(state.surfaced_doc_leaks)
        can_leaks = float(state.surfaced_canary_leaks)
        cons_set = set(state.consistent_suspects)
        one_minus_cons = 1.0 - (len(cons_set) / float(n))

        rows: list[tuple[float, ...]] = []
        for i, e in enumerate(eids):
            ch = float(state.canary_hits[e])
            cwh = float(state.canary_weighted_hits[e])
            sh = float(state.singleton_hits[e])
            cvm = float(state.canary_variant_misses[e])
            nrm = float(state.non_recipient_misses[e])
            old_u = float(state.old_unleaked_canaries[e])
            dh = float(state.leaked_doc_hits[e])
            ah = ah_list[i]
            tl = tot_list[i]
            ev = float(state.evasive_interviews[e])
            ang = ang_list[i]
            is_rest = 1.0 if e in state.restricted_ids else 0.0
            zero_hard_miss = 1.0 if nrm == 0.0 else 0.0
            zero_all_miss = 1.0 if (nrm == 0.0 and cvm == 0.0) else 0.0
            in_cons = 1.0 if e in cons_set else 0.0
            is_decoy_like = (
                1.0
                if (has_decoy > 0.5 and ang >= 3.0 and ang >= 3.0 * max(1.0, second_ang) and ang == max_ang)
                else 0.0
            )
            ahe = (ah - med_ah) * inv_sqrt_ld
            ahe_c = -3.0 if ahe < -3.0 else (5.0 if ahe > 5.0 else ahe)
            be = ((tl - ah) - base_ben) * inv_sqrt_ld
            be_c = -3.0 if be < -3.0 else (5.0 if be > 5.0 else be)
            cvm_cap = cvm if cvm < 6.0 else 6.0
            rows.append(
                (
                    ch if ch < 6.0 else 6.0,
                    cwh if cwh < 4.0 else 4.0,
                    sh if sh < 3.0 else 3.0,
                    1.0 if sh >= 1.0 else 0.0,
                    1.0 if ch >= 2.0 else 0.0,
                    cvm_cap * exact_fp,
                    cvm_cap * noisy_fp,
                    1.0 if (cvm >= 1.0 and exact_fp > 0.5) else 0.0,
                    1.0 if (cvm >= 2.0 and noisy_fp > 0.5) else 0.0,
                    nrm if nrm < 6.0 else 6.0,
                    1.0 if nrm >= 1.0 else 0.0,
                    zero_hard_miss,
                    zero_all_miss,
                    in_cons,
                    in_cons * one_minus_cons,
                    (old_u if old_u < 8.0 else 8.0) * (1.0 - 0.5 * careful),
                    dh if dh < 8.0 else 8.0,
                    dh / doc_leaks if doc_leaks > 0.0 else 0.0,
                    ch / can_leaks if can_leaks > 0.0 else 0.0,
                    ahe_c * (1.0 - 0.55 * has_framing),
                    ahe_c * has_framing,
                    be_c,
                    ah / (tl if tl > 1.0 else 1.0),
                    ev if ev < 3.0 else 3.0,
                    (ang if ang < 6.0 else 6.0) * has_decoy,
                    is_decoy_like,
                    cwh * zero_hard_miss * (1.0 - is_decoy_like),
                    is_rest,
                )
            )
        feats = np.asarray(rows, dtype=np.float64)
        state._emp_feats_cache = feats
        return feats

    cda.extract_employee_features = _fast_extract_employee_features
    try:
        yield
    finally:
        cda.extract_employee_features = orig_fn


def load_policy_factory(
    policy_id: str,
    repo_root: Path = ROOT,
) -> tuple[Callable[..., Any], dict[str, Any]]:
    import scripts.run_tiebreak_policy as rtp

    repo_root = repo_root.resolve()
    spec = POLICY_META_SPECS[policy_id]
    s_data = json.loads((repo_root / spec["summary_path"]).read_text(encoding="utf-8"))
    tr = s_data["train_seeds"]
    rtp._assert_train_seed_range(int(tr["start"]), int(tr["stop"]), spec["summary_path"])

    if policy_id == "empirical_bayes":
        raw_params = s_data["parameters"]["eb_experience_opt"]
        params = EmpiricalBayesParams.from_dict(raw_params)
        p_count = len([k for k in raw_params if k not in ("stage", "naive_p_threshold")])
        return (
            lambda seed, enabled_channels=ALL_CHANNELS_SET, interview_heavy=False, name=None, p=params: MaskedEmpiricalBayesPolicy(
                params=p,
                seed=seed,
                enabled_channels=enabled_channels,
                interview_heavy=interview_heavy,
                name=name or "empirical_bayes",
            ),
            {
                **spec,
                "param_count": p_count,
                "train_seed_range": f"{int(tr['start'])}..{int(tr['stop']) - 1}",
                "is_open_weight_llm": False,
                "eb_params": params,
            },
        )

    if policy_id == "compact_linear_dagger":
        weights = CompactLinearWeights.from_dict(s_data["learned_weights_stage3"])
        return (
            lambda _seed, enabled_channels=ALL_CHANNELS_SET, interview_heavy=False, name=None, w=weights: MaskedCompactLinearDAggerPolicy(
                weights=w,
                enabled_channels=enabled_channels,
                interview_heavy=interview_heavy,
                name=name or "compact_linear_dagger",
            ),
            {
                **spec,
                "param_count": int(weights.param_count()),
                "train_seed_range": f"{int(tr['start'])}..{int(tr['stop']) - 1}",
                "is_open_weight_llm": False,
            },
        )

    raise ValueError(f"unknown policy_id: {policy_id!r}")


def _compute_eb_terminal_llr_terms(inner_eb: Any) -> dict[str, float]:
    tracker = inner_eb.tracker
    params = inner_eb.params
    emps = list(tracker.employees)
    if len(emps) < 2:
        return {
            "canary_variant": 0.0,
            "canary_recipient": 0.0,
            "regular_doc": 0.0,
            "access_logs": 0.0,
            "angry_messages": 0.0,
            "interviews": 0.0,
            "total": 0.0,
        }
    feats = tracker.extract_features()
    post = inner_eb.posterior()
    ranked = sorted(emps, key=lambda e: (-post[e], e))
    top_e, sec_e = ranked[0], ranked[1]

    surfaced = sorted(tracker.feed_items.values(), key=lambda x: (x["surfaced_day"], x["doc_id"]))
    can_rec_top = 0
    can_rec_sec = 0
    reg_doc_top = 0
    reg_doc_sec = 0
    for it in surfaced:
        doc = tracker.docs.get(it["doc_id"])
        if doc is None:
            continue
        if doc["is_canary"]:
            if top_e in doc["recipients"]:
                can_rec_top += 1
            if sec_e in doc["recipients"]:
                can_rec_sec += 1
        else:
            if top_e in doc["recipients"]:
                reg_doc_top += 1
            if sec_e in doc["recipients"]:
                reg_doc_sec += 1

    ft = feats[top_e]
    fs = feats[sec_e]
    can_var = params.w_canary_hit * (ft[0] - fs[0]) + params.w_canary_miss * (ft[1] - fs[1])
    can_rec = params.w_doc_hit * (can_rec_top - can_rec_sec)
    reg_doc = params.w_doc_hit * (reg_doc_top - reg_doc_sec)
    acc_log = params.w_after_hours * (ft[3] - fs[3])
    iv_term = params.w_evasive * (ft[4] - fs[4])
    ang_term = params.w_angry_msg * (ft[5] - fs[5])
    total = can_var + can_rec + reg_doc + acc_log + iv_term + ang_term
    return {
        "canary_variant": float(can_var),
        "canary_recipient": float(can_rec),
        "regular_doc": float(reg_doc),
        "access_logs": float(acc_log),
        "angry_messages": float(ang_term),
        "interviews": float(iv_term),
        "total": float(total),
    }


_WORKER_CTX: dict[str, Any] = {}


def _run_ablation_task(task: tuple[str, str, str, int]) -> dict[str, Any]:
    from canary.env import Env
    from canary.eval import run_episode
    import scripts.run_tiebreak_policy as rtp

    policy_id, condition_id, tier, seed = task
    provider = _WORKER_CTX["provider"]
    fac = _WORKER_CTX["factories"][policy_id]
    cspec = CONDITION_MAP[condition_id]

    wrapped_pol = fac(
        seed,
        enabled_channels=cspec["enabled_channels"],
        interview_heavy=bool(cspec["interview_heavy"]),
        name=f"{policy_id}:{condition_id}",
    )

    do_fresh_replay = condition_id == "full_all_channels" or (
        condition_id in ("loo_no_canary_traps", "interviews_heavy_no_canary") and seed < 800_003
    )

    with _scoped_world_secret(HELDOUT_WORLD_SECRET):
        ep = run_episode(Env(tier, seed, text_provider=provider), wrapped_pol)
        if do_fresh_replay:
            rtp.verify_episode_replay(ep, text_provider=provider)

    total_calls = len(ep.steps)
    canaries_planted = sum(
        1 for st in ep.steps if st.tool == "plant_canary" and bool(st.result.get("ok"))
    )
    interviews_cnt = sum(
        1 for st in ep.steps if st.tool == "interview" and bool(st.result.get("ok"))
    )
    trace_sha = canonical_trace_sha256(ep.steps)

    llr_terms: dict[str, float] | None = None
    if policy_id == "empirical_bayes" and condition_id == "full_all_channels":
        wrapped_pol.tracker.ingest_steps(wrapped_pol.masked_steps)
        llr_terms = _compute_eb_terminal_llr_terms(wrapped_pol)

    return {
        "policy_id": policy_id,
        "condition_id": condition_id,
        "tier": tier,
        "seed": seed,
        "score": round(float(ep.score), 4),
        "accused": ep.accused,
        "correct": bool(ep.correct and ep.accused is not None),
        "wrong": bool((not ep.correct) and ep.accused is not None),
        "abstain": ep.accused is None,
        "final_day": int(ep.final_day),
        "total_calls": total_calls,
        "canaries_planted": canaries_planted,
        "interviews_cnt": interviews_cnt,
        "replay_verified": do_fresh_replay,
        "trace_sha12": trace_sha[:12],
        "llr_terms": llr_terms,
    }


def _summarize_episode_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(rows)
    denom = max(1, n)
    scores = [float(r["score"]) for r in rows]
    ci = mean_ci95(scores)
    c_cnt = sum(1 for r in rows if r["correct"])
    w_cnt = sum(1 for r in rows if r["wrong"])
    a_cnt = sum(1 for r in rows if r["abstain"])
    acc_days = [int(r["final_day"]) for r in rows if not r["abstain"]]
    tot_calls = sum(int(r["total_calls"]) for r in rows)
    tot_can = sum(int(r["canaries_planted"]) for r in rows)
    tot_iv = sum(int(r["interviews_cnt"]) for r in rows)
    rep_cnt = sum(1 for r in rows if r["replay_verified"])
    agg_sha = "0x" + hashlib.sha256(
        "\n".join(f"{r['tier']}:{r['seed']}:{r['trace_sha12']}" for r in rows).encode("utf-8")
    ).hexdigest()[:16]
    return {
        "n": n,
        "mean_score": ci["mean"],
        "ci95_low": ci["ci95_low"],
        "ci95_high": ci["ci95_high"],
        "ci95_half_width": ci["ci95_half_width"],
        "accuracy": round(c_cnt / denom, 5),
        "wrong_accuse_rate": round(w_cnt / denom, 5),
        "abstain_rate": round(a_cnt / denom, 5),
        "correct_count": c_cnt,
        "wrong_count": w_cnt,
        "abstain_count": a_cnt,
        "mean_final_day": round(sum(int(r["final_day"]) for r in rows) / denom, 4),
        "mean_accuse_day_when_accused": (
            round(sum(acc_days) / len(acc_days), 4) if acc_days else 0.0
        ),
        "total_tool_calls": tot_calls,
        "mean_tool_calls": round(tot_calls / denom, 4),
        "mean_canaries_planted": round(tot_can / denom, 4),
        "mean_interviews": round(tot_iv / denom, 4),
        "canary_call_share": round(tot_can / max(1, tot_calls), 5),
        "interview_call_share": round(tot_iv / max(1, tot_calls), 5),
        "replay_verified_count": rep_cnt,
        "trace_set_sha16": agg_sha,
    }


def _load_frontier_bridge(repo_root: Path) -> dict[str, Any]:
    bridge = {k: dict(v) for k, v in FALLBACK_FRONTIER_BEHAVIOUR_V14.items()}
    cmp_path = repo_root / FRONTIER_CMP_REL
    if cmp_path.is_file():
        cmp_data = json.loads(cmp_path.read_text(encoding="utf-8"))
        cohorts = (cmp_data.get("dev_hard_panel") or {}).get("cohorts") or []
        by_id = {c.get("cohort_id"): c for c in cohorts if isinstance(c, dict)}
        for cid in ("opencode_gpt_5_5_hard", "opencode_gemini_4_carbon_hard"):
            if cid in by_id:
                c_obj = by_id[cid]
                cdiag = c_obj.get("canary_diagnostics") or {}
                bridge[cid]["mean_score"] = round(float(c_obj["mean_score"]), 4)
                bridge[cid]["ci95"] = round(float(c_obj["ci95"]), 4)
                bridge[cid]["luck_adjusted_ev"] = round(float(c_obj["luck_adjusted_ev"]), 4)
                bridge[cid]["canaries_before_accuse_per_ep"] = round(
                    float(cdiag["mean_canaries_before_accuse"]), 2
                )
                bridge[cid]["canary_slot_utilization"] = round(
                    float(cdiag["canary_slot_utilization"]), 4
                )
                bridge[cid]["correct_count"] = int(c_obj["correct_count"])
                bridge[cid]["wrong_count"] = int(c_obj["wrong_count"])
                bridge[cid]["abstain_count"] = int(c_obj["abstain_count"])
    return bridge


def _load_panel_fix_e_block(repo_root: Path) -> dict[str, Any]:
    ledger_path = repo_root / LEDGER_REL
    total_qwen = 19
    above_zero = 0
    if ledger_path.is_file():
        ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
        hist = list(ledger.get("historical_runs") or [])
        total_qwen = len(hist)
        above_zero = sum(
            1
            for r in hist
            if isinstance(r, dict)
            and isinstance(r.get("after_mean_score"), (int, float))
            and float(r["after_mean_score"]) > 0.0
        )
    return {
        "open_weight_qwen25_runs_total": total_qwen,
        "open_weight_qwen25_runs_above_zero": above_zero,
        "open_weight_qwen25_above_zero_ratio": f"{above_zero} / {total_qwen}",
        "readme_qwen_addendum_status": "HOLD_README_QWEN_ADDENDUM_UNTIL_V100",
        "audited_policies_are_open_weight_llm": False,
        "disclosure": PANEL_FIX_E_DISCLOSURE,
    }


def run_audit(repo_root: Path = ROOT, max_workers: int = 16) -> dict[str, Any]:
    from canary import rules
    from canary.text.template import TemplateProvider

    t0 = time.perf_counter()
    repo_root = repo_root.resolve()
    heldout_seeds = list(range(HELDOUT_SEED_START, HELDOUT_SEED_STOP))
    for s in heldout_seeds:
        if s not in rules.HELDOUT_SEEDS or s in rules.JUDGE_SEEDS or s >= JUDGE_SEED_MIN:
            raise ValueError(f"seed {s} violates HELDOUT_SEEDS isolation")

    secret_tag = compute_secret_tag(HELDOUT_WORLD_SECRET)
    if secret_tag != EXPECTED_WORLD_SECRET_TAG:
        raise AssertionError(f"secret_tag {secret_tag} != {EXPECTED_WORLD_SECRET_TAG}")

    provider = TemplateProvider()
    factories: dict[str, Callable[[int], Any]] = {}
    metas: dict[str, dict[str, Any]] = {}
    for pid in POLICY_ORDER:
        fac, meta = load_policy_factory(pid, repo_root=repo_root)
        factories[pid] = fac
        metas[pid] = meta

    tasks = [
        (pid, cid, tier, seed)
        for pid in POLICY_ORDER
        for cid in CONDITION_ORDER
        for tier in CANONICAL_TIERS
        for seed in heldout_seeds
    ]

    with _fast_compact_dagger_features():
        _WORKER_CTX["provider"] = provider
        _WORKER_CTX["factories"] = factories
        use_fork = (
            max_workers > 1
            and "pytest" not in sys.modules
            and "fork" in multiprocessing.get_all_start_methods()
        )
        if use_fork:
            ctx = multiprocessing.get_context("fork")
            with ProcessPoolExecutor(max_workers=max_workers, mp_context=ctx) as pool:
                raw_rows = list(pool.map(_run_ablation_task, tasks, chunksize=8))
        else:
            raw_rows = [_run_ablation_task(tk) for tk in tasks]

    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for r in raw_rows:
        grouped.setdefault((r["policy_id"], r["condition_id"]), []).append(r)

    tier_rank = {t: idx for idx, t in enumerate(CANONICAL_TIERS)}
    policies_out: dict[str, Any] = {}
    total_replays = 0

    for pid in POLICY_ORDER:
        meta = metas[pid]
        full_rows = sorted(
            grouped[(pid, "full_all_channels")],
            key=lambda x: (tier_rank[x["tier"]], int(x["seed"])),
        )
        full_scores = [float(r["score"]) for r in full_rows]

        conds_out: dict[str, Any] = {}
        loo_positive_sum = 0.0
        for cid in CONDITION_ORDER:
            cspec = CONDITION_MAP[cid]
            c_rows = sorted(
                grouped[(pid, cid)],
                key=lambda x: (tier_rank[x["tier"]], int(x["seed"])),
            )
            c_scores = [round(float(r["score"]), 4) for r in c_rows]
            overall = _summarize_episode_rows(c_rows)
            total_replays += int(overall["replay_verified_count"])

            by_tier: dict[str, Any] = {}
            for tier in CANONICAL_TIERS:
                t_rows = [r for r in c_rows if r["tier"] == tier]
                t_sum = _summarize_episode_rows(t_rows)
                by_tier[tier] = {
                    "n": t_sum["n"],
                    "mean_score": t_sum["mean_score"],
                    "ci95_low": t_sum["ci95_low"],
                    "ci95_high": t_sum["ci95_high"],
                    "accuracy": t_sum["accuracy"],
                    "wrong_accuse_rate": t_sum["wrong_accuse_rate"],
                    "abstain_rate": t_sum["abstain_rate"],
                }

            paired = compute_paired_vs_full(c_scores, full_scores)
            if cid in LOO_CONDITION_IDS and float(paired["voi_drop"]) > 0.0:
                loo_positive_sum += float(paired["voi_drop"])

            conds_out[cid] = {
                "group": cspec["group"],
                "ablated_channel": cspec["ablated_channel"],
                "enabled_channels": list(cspec["enabled_channels"]),
                "interview_heavy": bool(cspec["interview_heavy"]),
                "overall": overall,
                "paired_vs_full": paired,
                "by_tier": by_tier,
                "episode_scores_csv": ",".join(f"{round(s, 4):g}" for s in c_scores),
            }

        loo_ranking: list[dict[str, Any]] = []
        for cid in LOO_CONDITION_IDS:
            pv = conds_out[cid]["paired_vs_full"]
            drop = float(pv["voi_drop"])
            norm_share = round(max(0.0, drop) / loo_positive_sum, 5) if loo_positive_sum > 1e-9 else 0.0
            loo_ranking.append(
                {
                    "channel": CONDITION_MAP[cid]["ablated_channel"],
                    "condition_id": cid,
                    "voi_drop": round(drop, 5),
                    "voi_share_of_full": pv["voi_share_of_full"],
                    "normalized_positive_loo_share": norm_share,
                }
            )
        loo_ranking.sort(key=lambda r: (-float(r["voi_drop"]), str(r["channel"])))

        p_entry: dict[str, Any] = {
            "policy_id": pid,
            "policy_class": meta["policy_class"],
            "run_id": meta["run_id"],
            "module_path": meta["module_path"],
            "summary_path": meta["summary_path"],
            "param_count": meta["param_count"],
            "train_seed_range": meta["train_seed_range"],
            "is_open_weight_llm": False,
            "loo_voi_ranking": loo_ranking,
            "conditions": conds_out,
        }

        if pid == "empirical_bayes":
            llr_list = [r["llr_terms"] for r in full_rows if r["llr_terms"] is not None]
            n_llr = max(1, len(llr_list))
            m_cvar = sum(float(x["canary_variant"]) for x in llr_list) / n_llr
            m_crec = sum(float(x["canary_recipient"]) for x in llr_list) / n_llr
            m_rdoc = sum(float(x["regular_doc"]) for x in llr_list) / n_llr
            m_alog = sum(float(x["access_logs"]) for x in llr_list) / n_llr
            m_ang = sum(float(x["angry_messages"]) for x in llr_list) / n_llr
            m_iv = sum(float(x["interviews"]) for x in llr_list) / n_llr
            m_tot = sum(float(x["total"]) for x in llr_list) / n_llr
            p_entry["commitment_llr_decomposition"] = {
                "n": len(llr_list),
                "mean_canary_variant_llr": round(m_cvar, 5),
                "mean_canary_recipient_llr": round(m_crec, 5),
                "mean_regular_doc_llr": round(m_rdoc, 5),
                "mean_access_logs_llr": round(m_alog, 5),
                "mean_angry_messages_llr": round(m_ang, 5),
                "mean_interviews_llr": round(m_iv, 5),
                "mean_total_top_vs_second_llr": round(m_tot, 5),
                "canary_variant_only_llr_share": round(m_cvar / m_tot, 5) if abs(m_tot) > 1e-9 else 0.0,
                "canary_inclusive_llr_share": (
                    round((m_cvar + m_crec) / m_tot, 5) if abs(m_tot) > 1e-9 else 0.0
                ),
            }

        policies_out[pid] = p_entry

    eb_full_m = float(policies_out["empirical_bayes"]["conditions"]["full_all_channels"]["overall"]["mean_score"])
    cd_full_m = float(
        policies_out["compact_linear_dagger"]["conditions"]["full_all_channels"]["overall"]["mean_score"]
    )
    eb_noc_m = float(policies_out["empirical_bayes"]["conditions"]["loo_no_canary_traps"]["overall"]["mean_score"])
    cd_noc_m = float(
        policies_out["compact_linear_dagger"]["conditions"]["loo_no_canary_traps"]["overall"]["mean_score"]
    )

    pooled_full = 0.5 * (eb_full_m + cd_full_m)
    pooled_noc = 0.5 * (eb_noc_m + cd_noc_m)
    pooled_drop = pooled_full - pooled_noc
    pooled_share = pooled_drop / pooled_full if pooled_full > 1e-9 else 0.0

    target_script = repo_root / "scripts" / "tiebreak_channel_ablation_audit.py"
    if not target_script.is_file():
        target_script = Path(__file__).resolve()
    ast_gate = audit_module_ast_isolation(target_script)
    elapsed_s = round(time.perf_counter() - t0, 3)

    return {
        "schema": SCHEMA_VERSION,
        "audit_id": AUDIT_ID,
        "text_provider": "TemplateProvider",
        "world_secret_tag": secret_tag,
        "heldout_seed_range": f"{HELDOUT_SEED_START}..{HELDOUT_SEED_STOP - 1}",
        "eval_seed_range": f"{HELDOUT_SEED_START}..{HELDOUT_SEED_STOP - 1}",
        "eval_seeds_per_tier": HELDOUT_SEEDS_PER_TIER,
        "episodes_per_condition": EPISODES_PER_CONDITION,
        "tiers": list(CANONICAL_TIERS),
        "public_channels": list(PUBLIC_CHANNELS),
        "seed_isolation": {
            "train_seed_interval": "100000..199999",
            "heldout_seed_range": f"{HELDOUT_SEED_START}..{HELDOUT_SEED_STOP - 1}",
            "judge_episodes_touched": 0,
            "dev_episodes_rolled_out": 0,
            "train_episodes_in_heldout_eval": 0,
            "panel_fix_a_disclosure": PANEL_FIX_A_DISCLOSURE,
        },
        "panel_fix_e_track_separation": _load_panel_fix_e_block(repo_root),
        "ast_inference_isolation": ast_gate,
        "theoretical_channel_kl": compute_theoretical_channel_kl(),
        "frontier_behaviour_bridge": _load_frontier_bridge(repo_root),
        "totals": {
            "policies_audited": len(POLICY_ORDER),
            "conditions_per_policy": len(CONDITION_ORDER),
            "total_episodes": len(raw_rows),
            "fresh_env_replays_verified": total_replays,
            "pooled_full_mean_score": round(pooled_full, 5),
            "pooled_no_canary_mean_score": round(pooled_noc, 5),
            "pooled_canary_voi_drop": round(pooled_drop, 5),
            "pooled_canary_voi_share_of_full": round(pooled_share, 5),
            "elapsed_seconds": elapsed_s,
        },
        "policies": policies_out,
    }


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    if args.check:
        return _run_check_cli(args)

    root = args.repo_root.resolve()
    out_json = args.out_json if args.out_json.is_absolute() else (root / args.out_json)
    out_md = args.out_md if args.out_md.is_absolute() else (root / args.out_md)

    summary = run_audit(repo_root=root, max_workers=max(1, int(args.workers)))
    md_text = render_markdown_report(summary)

    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_md.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    out_md.write_text(md_text, encoding="utf-8")

    errs = verify_committed_artifacts(
        summary_path=out_json,
        md_path=out_md,
        repo_root=root,
        enforce_budget=False,
    )
    if errs:
        for err in errs:
            print(f"FAIL: {err}", file=sys.stderr)
        return 1

    print(
        f"Wrote {out_json.relative_to(root)} ({out_json.stat().st_size} bytes) and "
        f"{out_md.relative_to(root)} ({summary['totals']['total_episodes']} episodes, "
        f"pooled canary VoI share {summary['totals']['pooled_canary_voi_share_of_full'] * 100.0:.1f}% "
        f"in {summary['totals']['elapsed_seconds']:.2f}s)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
