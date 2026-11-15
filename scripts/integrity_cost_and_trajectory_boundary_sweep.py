"""Exhaustive V, visible_V, score, day, action-budget, and KNOWN_V_MODE boundary exploit sweep across Canary v1.4 and v1.5."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from decimal import Decimal
import json
import math
import os
from pathlib import Path
import random
import statistics
import sys
import time
from typing import Any, Callable, Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.integrity_v14_v15_differential_sweep import (
    EMBEDDED_V15_COMMIT_FULL,
    EXPECTED_V14_TIER_HASH,
    ISOLATED_V15_PKG,
    IsolatedV15Runtime,
    _RUNTIME_CACHE as _DIFF_V15_RUNTIME_CACHE,
    compute_tier_hash,
    git_status_porcelain,
    load_v15_runtime,
    resolve_head_commit,
    try_resolve_git_commit,
)

QUICK_EMBEDDED_V15_PKG = "_canary_v15_embedded_w4"
_HEX40_CHARS = frozenset("0123456789abcdefABCDEF")
_CACHED_V14_META: tuple[frozenset[str], frozenset[str]] | None = None
_CACHED_QUICK_EMBEDDED_RT: IsolatedV15Runtime | None = None
_CACHED_POSITIVE_CONTROLS: dict[str, Any] | None = None
_CACHED_QUICK_DIAGNOSTICS: dict[str, dict[str, Any]] = {}

V14_TARGETS: tuple[str, ...] = ("easy", "medium", "hard", "hard_forge", "hard_rl")
V15_TARGETS: tuple[str, ...] = ("easy", "medium", "hard", "hard_forge")

FAMILY_NAMES: tuple[str, ...] = (
    "saturation_loss_ge_one",
    "post_end_tool_calls",
    "tool_cap_exact_boundary",
    "restrict_unrestrict_toggle",
    "invalid_arg_zero_delta",
    "float_vs_closed_form",
    "known_v_mode_dual",
    "stateful_adversarial_fuzz",
)

POSITIVE_CONTROL_NAMES: tuple[str, ...] = (
    "PC1_negative_tool_cost",
    "PC2_post_done_accuse_overwrite",
    "PC3_free_interview_on_error",
    "PC4_visible_v_hidden_leak_sidechannel",
    "PC5_score_gt_one_minus_loss_inflation",
    "PC6_action_budget_and_horizon_bypass",
)

ALL_PUBLIC_TOOLS: tuple[str, ...] = (
    "status",
    "list_employees",
    "list_documents",
    "read_access_logs",
    "search_messages",
    "read_message",
    "interview",
    "plant_canary",
    "check_leak_feed",
    "restrict_access",
    "unrestrict_access",
    "advance_day",
    "accuse",
)

INTERVIEW_TOPICS: tuple[str, ...] = (
    "recent_documents",
    "contacts_outside",
    "workload",
    "access_needs",
)


@contextmanager
def _ensure_forge_hof_env(repo_root: Path, rt: IsolatedV15Runtime | None = None):
    prev = os.environ.get("CANARY_FORGE_HOF")
    rel = Path("data") / "forge" / "hall_of_fame_v1.2.jsonl"
    rt_root = getattr(getattr(rt, "finder", None), "repo_root", repo_root)
    need_override = (
        prev is None
        and (not (repo_root / rel).is_file() or not (Path(rt_root) / rel).is_file())
        and (REPO_ROOT / rel).is_file()
    )
    if need_override:
        os.environ["CANARY_FORGE_HOF"] = str((REPO_ROOT / rel).resolve())
    try:
        yield
    finally:
        if need_override:
            if prev is None:
                os.environ.pop("CANARY_FORGE_HOF", None)
            else:
                os.environ["CANARY_FORGE_HOF"] = prev


@contextmanager
def _swap_known_v_mode(rules_mod: Any, mode: bool):
    prev = bool(getattr(rules_mod, "KNOWN_V_MODE"))
    setattr(rules_mod, "KNOWN_V_MODE", bool(mode))
    try:
        yield
    finally:
        setattr(rules_mod, "KNOWN_V_MODE", prev)


def _make_v14_env(tier: str, seed: int) -> Any:
    from canary.env import Env
    return Env(tier, seed)


def _make_v15_env(rt: IsolatedV15Runtime, tier: str, seed: int, repo_root: Path = REPO_ROOT) -> Any:
    with _ensure_forge_hof_env(repo_root, rt=rt):
        return rt.make_env(tier, seed, social_enabled=True, misforward_enabled=True)


def _mean_ci95(vals: Sequence[float]) -> dict[str, float]:
    if not vals:
        return {"mean": 0.0, "ci95": 0.0, "min": 0.0, "max": 0.0}
    m = sum(vals) / len(vals)
    ci = 1.96 * statistics.stdev(vals) / math.sqrt(len(vals)) if len(vals) >= 2 else 0.0
    return {
        "mean": round(m, 6),
        "ci95": round(ci, 6),
        "min": round(min(vals), 6),
        "max": round(max(vals), 6),
    }


def _get_v14_meta() -> tuple[frozenset[str], frozenset[str]]:
    global _CACHED_V14_META
    if _CACHED_V14_META is None:
        from canary.env import ERRORS as V14_ERRORS
        from canary.types import INVESTIGATIVE_TOOLS

        _CACHED_V14_META = (frozenset(INVESTIGATIVE_TOOLS), frozenset(V14_ERRORS))
    return _CACHED_V14_META


def _is_hex40(val: str) -> bool:
    return len(val) == 40 and all(c in _HEX40_CHARS for c in val)


def _resolve_git_dirs(repo_root: Path) -> tuple[Path, Path] | None:
    dot_git = repo_root / ".git"
    if dot_git.is_dir():
        git_dir = dot_git
    elif dot_git.is_file():
        try:
            raw = dot_git.read_text(encoding="utf-8").strip()
        except OSError:
            return None
        if not raw.startswith("gitdir:"):
            return None
        git_dir = (repo_root / raw.split(":", 1)[1].strip()).resolve()
        if not git_dir.is_dir():
            return None
    else:
        return None
    commondir_file = git_dir / "commondir"
    if commondir_file.is_file():
        try:
            common_dir = (git_dir / commondir_file.read_text(encoding="utf-8").strip()).resolve()
        except OSError:
            common_dir = git_dir
    else:
        common_dir = git_dir
    return git_dir, common_dir


def _lookup_git_ref(git_dir: Path, common_dir: Path, ref_name: str) -> str | None:
    for base in (git_dir, common_dir):
        cand = base / ref_name
        if cand.is_file():
            try:
                val = cand.read_text(encoding="utf-8").strip()
            except OSError:
                val = ""
            if _is_hex40(val):
                return val
    packed = common_dir / "packed-refs"
    if packed.is_file():
        comment_prefix = chr(35)
        try:
            lines = packed.read_text(encoding="utf-8").splitlines()
        except OSError:
            lines = []
        for ln in lines:
            if not ln or ln.startswith(comment_prefix) or ln.startswith("^"):
                continue
            parts = ln.split(" ", 1)
            if len(parts) == 2 and parts[1].strip() == ref_name and _is_hex40(parts[0]):
                return parts[0]
    return None


def _fast_resolve_head_commit(repo_root: Path) -> str:
    dirs = _resolve_git_dirs(repo_root)
    if dirs is None:
        return "nogit0000"
    git_dir, common_dir = dirs
    head_file = git_dir / "HEAD"
    if head_file.is_file():
        try:
            raw = head_file.read_text(encoding="utf-8").strip()
        except OSError:
            raw = ""
        if raw.startswith("ref:"):
            ref_name = raw.split(":", 1)[1].strip()
            sha = _lookup_git_ref(git_dir, common_dir, ref_name)
            if sha is not None:
                return sha
        elif _is_hex40(raw):
            return raw
    return resolve_head_commit(repo_root)


def _fast_resolve_v15_sha(repo_root: Path, ref: str) -> str | None:
    dirs = _resolve_git_dirs(repo_root)
    if dirs is None:
        return None
    git_dir, common_dir = dirs
    ref_candidates: list[str] = []
    if ref.startswith("refs/"):
        ref_candidates.append(ref)
    elif ref.startswith("origin/"):
        branch = ref[len("origin/"):]
        ref_candidates.append(f"refs/remotes/origin/{branch}")
        ref_candidates.append(f"refs/heads/{branch}")
    else:
        ref_candidates.append(f"refs/heads/{ref}")
        ref_candidates.append(f"refs/remotes/origin/{ref}")
    found_sha: str | None = None
    for rc in ref_candidates:
        found_sha = _lookup_git_ref(git_dir, common_dir, rc)
        if found_sha is not None:
            break
    if found_sha is None:
        if _is_hex40(ref):
            return try_resolve_git_commit(ref=ref, repo_root=repo_root)
        return None
    if (common_dir / "shallow").is_file() or (git_dir / "shallow").is_file():
        return try_resolve_git_commit(ref=ref, repo_root=repo_root)
    return found_sha


def _fast_dir_fingerprint(repo_root: Path) -> str:
    if not repo_root.exists():
        return "missing-repo-root"
    entries: list[str] = []
    for child in sorted(repo_root.iterdir(), key=lambda p: p.name):
        if child.name == ".git":
            continue
        try:
            st = child.stat()
            entries.append(f"{child.name}:{st.st_size}:{st.st_mtime_ns}")
        except OSError:
            entries.append(f"{child.name}:stat-error")
    return "\n".join(entries)


def _acquire_v15_runtime_for_sweep(
    quick: bool,
    v15_ref: str,
    v15_pkg_name: str,
    resolved_repo: Path,
    force_embedded_v15: bool,
) -> tuple[IsolatedV15Runtime, bool]:
    global _CACHED_QUICK_EMBEDDED_RT
    if quick and v15_ref == "origin/justSilas-v15" and v15_pkg_name == ISOLATED_V15_PKG:
        git_v15_sha = None if force_embedded_v15 else _fast_resolve_v15_sha(resolved_repo, v15_ref)
        shallow_fallback = bool(force_embedded_v15 or git_v15_sha is None)
        if not shallow_fallback and ISOLATED_V15_PKG in sys.modules:
            for (c_sha, p_name, _, _), cached_rt in list(_DIFF_V15_RUNTIME_CACHE.items()):
                if p_name == ISOLATED_V15_PKG and c_sha.startswith("de9cc50e"):
                    return cached_rt, False
        if _CACHED_QUICK_EMBEDDED_RT is None or QUICK_EMBEDDED_V15_PKG not in sys.modules:
            scratch_nogit = Path("/tmp/opencode")
            non_git_anchor = scratch_nogit if scratch_nogit.is_dir() else REPO_ROOT.parent
            _CACHED_QUICK_EMBEDDED_RT = load_v15_runtime(
                ref="origin/justSilas-v15",
                pkg_name=QUICK_EMBEDDED_V15_PKG,
                repo_root=non_git_anchor,
                force_embedded=True,
            )
        return _CACHED_QUICK_EMBEDDED_RT, shallow_fallback

    rt15 = load_v15_runtime(
        ref=v15_ref,
        pkg_name=v15_pkg_name,
        repo_root=resolved_repo,
        force_embedded=force_embedded_v15,
    )
    git_v15_sha = None if force_embedded_v15 else try_resolve_git_commit(ref=v15_ref, repo_root=resolved_repo)
    shallow_fallback = bool(rt15.used_embedded_fallback or git_v15_sha is None)
    return rt15, shallow_fallback


class StepAccountingAuditor:
    def __init__(self, env: Any, version_label: str, family: str, submode: str) -> None:
        inv_tools, allowed_errs = _get_v14_meta()

        self.env = env
        self.version_label = version_label
        self.family = family
        self.submode = submode
        self.investigative_tools = inv_tools
        self.allowed_errors = allowed_errs
        self._d_leak = Decimal(str(env.p.leak_damage))
        self._d_can = Decimal(str(env.p.canary_cost))
        self._d_rest = Decimal(str(env.p.restrict_cost_per_day))
        self._d_zero = Decimal("0")
        self._d_one = Decimal("1")

        self.n_canaries_planted = 0
        self.n_restrict_person_days = 0
        self.restricted_shadow: set[str] = set()
        self.day_shadow = 1
        self.steps_executed = 0
        self.rejected_calls = 0
        self.post_end_calls = 0
        self.hidden_leak_steps = 0
        self.hidden_leak_masked_steps = 0
        self.v_zero_pre_done_steps = 0
        self.vis_v_zero_pre_done_steps = 0
        self.nonzero_raw_v_drift_steps = 0
        self.max_raw_v_drift = 0.0
        self.max_rounded_v_drift = 0.0
        self.max_vis_v_drift = 0.0
        self.max_costs_drift = 0.0
        self._cf_cache_key: tuple[int, int, int, int] | None = None
        self._cf_cache_val: tuple[Decimal, Decimal, Decimal, int, int, float, float] | None = None
        self.violations: list[dict[str, Any]] = []

        self._verify_initial_state()

    def _record_violation(self, kind: str, step_idx: int, detail: str) -> None:
        self.violations.append(
            {
                "kind": kind,
                "step": step_idx,
                "version": self.version_label,
                "tier": getattr(self.env, "tier", "?"),
                "seed": getattr(self.env, "seed", -1),
                "family": self.family,
                "submode": self.submode,
                "detail": detail,
            }
        )

    def _verify_initial_state(self) -> None:
        e = self.env
        if e.day != 1:
            self._record_violation("init_day_not_one", -1, f"day={e.day!r}")
        if e.V != 1.0 or e.visible_V() != 1.0:
            self._record_violation("init_v_not_one", -1, f"V={e.V!r}, vis={e.visible_V()!r}")
        if e.score() != 0.0 or e.done is not False:
            self._record_violation("init_done_or_score", -1, f"done={e.done!r}, score={e.score()!r}")

    def _closed_form_decimals(self) -> tuple[Decimal, Decimal, Decimal, int, int, float, float]:
        e = self.env
        total_leaks = len(e._feed)
        key = (self.n_canaries_planted, self.n_restrict_person_days, total_leaks, int(e.day))
        if self._cf_cache_key == key and self._cf_cache_val is not None:
            return self._cf_cache_val
        costs_dec = self._d_can * self.n_canaries_planted + self._d_rest * self.n_restrict_person_days
        surfaced_leaks = sum(1 for item in e._feed if item["surfaced_day"] <= e.day)
        v_true_dec = max(self._d_zero, self._d_one - self._d_leak * total_leaks - costs_dec)
        v_known_dec = max(self._d_zero, self._d_one - self._d_leak * surfaced_leaks - costs_dec)
        val = (
            costs_dec,
            v_true_dec,
            v_known_dec,
            total_leaks,
            surfaced_leaks,
            float(round(v_true_dec, 10)),
            float(round(v_known_dec, 10)),
        )
        self._cf_cache_key = key
        self._cf_cache_val = val
        return val

    def call(self, tool: Any, args: Any) -> Any:
        e = self.env
        step_idx = self.steps_executed
        pre_done = bool(e.done)
        pre_v = float(e.V)
        pre_vis_v = float(e.visible_V())
        pre_score = float(e.score())
        pre_day = int(e.day)
        pre_costs = float(e._costs)
        pre_actions = int(e._actions_today)
        pre_canaries = int(e._canaries_today)
        pre_restricted = set(e._restricted)
        pre_docs_len = len(e.docs)
        pre_ledger_len = len(e._ledger)
        pre_hist_len = len(e.history)
        pre_accused = e._accused
        pre_end_reason = e._end_reason

        try:
            res = e.call(tool, args)
        except Exception as exc:
            self._record_violation("unhandled_exception", step_idx, f"{type(exc).__name__}: {exc}")
            self.steps_executed += 1
            return None

        self.steps_executed += 1

        if len(e.history) != pre_hist_len + 1:
            self._record_violation(
                "history_not_incremented",
                step_idx,
                f"history {pre_hist_len} -> {len(e.history)} on tool={tool!r}",
            )

        if pre_done:
            self.post_end_calls += 1
            if res.ok is not False or res.error != "episode over" or res.data != {}:
                self._record_violation(
                    "post_end_response_invalid",
                    step_idx,
                    f"ok={res.ok!r}, error={res.error!r}, data={res.data!r}",
                )
            if (
                e.V != pre_v
                or e.visible_V() != pre_vis_v
                or e.score() != pre_score
                or e.day != pre_day
                or len(e._ledger) != pre_ledger_len
                or e._accused != pre_accused
                or e._end_reason != pre_end_reason
                or e._restricted != pre_restricted
            ):
                self._record_violation(
                    "post_end_state_mutation",
                    step_idx,
                    f"score {pre_score}->{e.score()}, day {pre_day}->{e.day}, ledger {pre_ledger_len}->{len(e._ledger)}",
                )
        else:
            if not res.ok:
                self.rejected_calls += 1
                if res.error not in self.allowed_errors:
                    self._record_violation("unknown_error_string", step_idx, f"error={res.error!r}")
                if not isinstance(res.data, dict) or not (set(res.data.keys()) <= {"detail"}):
                    self._record_violation(
                        "error_payload_leak_or_extra_keys",
                        step_idx,
                        f"data={res.data!r}",
                    )
                if e.V != pre_v or e.visible_V() != pre_vis_v or e._costs != pre_costs:
                    self._record_violation(
                        "rejected_call_cost_mutation",
                        step_idx,
                        f"V {pre_v}->{e.V}, vis {pre_vis_v}->{e.visible_V()}, costs {pre_costs}->{e._costs}",
                    )
                if e._actions_today != pre_actions or e._canaries_today != pre_canaries:
                    self._record_violation(
                        "rejected_call_budget_mutation",
                        step_idx,
                        f"actions {pre_actions}->{e._actions_today}, canaries {pre_canaries}->{e._canaries_today}",
                    )
                if e.day != pre_day or e._restricted != pre_restricted or len(e.docs) != pre_docs_len:
                    self._record_violation(
                        "rejected_call_state_mutation",
                        step_idx,
                        f"day {pre_day}->{e.day}, docs {pre_docs_len}->{len(e.docs)}",
                    )
            else:
                if tool in self.investigative_tools:
                    if pre_actions >= e.p.actions_per_day or e._actions_today != pre_actions + 1:
                        self._record_violation(
                            "action_budget_accounting",
                            step_idx,
                            f"tool={tool} pre_actions={pre_actions} post_actions={e._actions_today} cap={e.p.actions_per_day}",
                        )
                elif tool != "advance_day":
                    if e._actions_today != pre_actions:
                        self._record_violation(
                            "free_tool_consumed_daily_action",
                            step_idx,
                            f"tool={tool} pre_actions={pre_actions} post_actions={e._actions_today}",
                        )

                if tool == "plant_canary":
                    self.n_canaries_planted += 1
                    if pre_canaries >= e.p.canaries_per_day or e._canaries_today != pre_canaries + 1:
                        self._record_violation(
                            "canary_daily_budget_accounting",
                            step_idx,
                            f"pre_canaries={pre_canaries} post_canaries={e._canaries_today} cap={e.p.canaries_per_day}",
                        )
                elif tool == "restrict_access":
                    emp = args["employee"]
                    self.restricted_shadow.add(emp)
                    if e._restricted != self.restricted_shadow:
                        self._record_violation("restrict_set_mismatch", step_idx, f"got={sorted(e._restricted)}")
                    if e.V != pre_v or e.visible_V() != pre_vis_v:
                        self._record_violation(
                            "immediate_restrict_cost_charged",
                            step_idx,
                            f"V {pre_v}->{e.V}, vis {pre_vis_v}->{e.visible_V()}",
                        )
                elif tool == "unrestrict_access":
                    emp = args["employee"]
                    self.restricted_shadow.discard(emp)
                    if e._restricted != self.restricted_shadow:
                        self._record_violation("unrestrict_set_mismatch", step_idx, f"got={sorted(e._restricted)}")
                    if e.V != pre_v or e.visible_V() != pre_vis_v:
                        self._record_violation(
                            "immediate_unrestrict_cost_or_refund",
                            step_idx,
                            f"V {pre_v}->{e.V}, vis {pre_vis_v}->{e.visible_V()}",
                        )
                elif tool == "advance_day":
                    self.n_restrict_person_days += len(self.restricted_shadow)
                    if pre_day < e.p.n_days:
                        self.day_shadow = pre_day + 1
                        if e.day != self.day_shadow or e._actions_today != 0 or e._canaries_today != 0:
                            self._record_violation(
                                "advance_day_reset_or_increment",
                                step_idx,
                                f"day={e.day} want={self.day_shadow}, actions={e._actions_today}, canaries={e._canaries_today}",
                            )
                        if e.done and len(e.history) < e.p.tool_call_cap:
                            self._record_violation(
                                "premature_termination_on_advance_day",
                                step_idx,
                                f"day={e.day}, end_reason={e._end_reason!r}",
                            )
                    else:
                        if e.day != e.p.n_days or not e.done or e._end_reason != "horizon":
                            self._record_violation(
                                "horizon_transition_invalid",
                                step_idx,
                                f"day={e.day} cap_days={e.p.n_days} done={e.done} end_reason={e._end_reason!r}",
                            )
                elif tool == "accuse":
                    if not e.done or e._end_reason != "accused" or e._accused != args["employee"]:
                        self._record_violation(
                            "accuse_termination_invalid",
                            step_idx,
                            f"done={e.done} end_reason={e._end_reason!r} accused={e._accused!r}",
                        )

        post_v = float(e.V)
        post_v_round = round(post_v, 10)
        post_vis_v = float(e.visible_V())

        if not (1 <= e.day <= e.p.n_days):
            self._record_violation("day_out_of_bounds", step_idx, f"day={e.day} n_days={e.p.n_days}")

        if not (0.0 <= post_v <= 1.0) or post_v > pre_v + 1e-15 or post_v_round > round(pre_v, 10):
            self._record_violation(
                "v_monotone_or_range_violation",
                step_idx,
                f"pre_v={pre_v!r} post_v={e.V!r}",
            )

        if not (0.0 <= post_vis_v <= 1.0) or post_vis_v > pre_vis_v + 1e-12:
            self._record_violation(
                "visible_v_monotone_or_range_violation",
                step_idx,
                f"pre_vis={pre_vis_v!r} post_vis={post_vis_v!r}",
            )

        (
            costs_dec,
            v_true_dec,
            v_known_dec,
            total_leaks,
            surfaced_leaks,
            want_true_round,
            want_known_round,
        ) = self._closed_form_decimals()

        costs_drift = abs(float(e._costs) - float(costs_dec))
        raw_v_drift = abs(post_v - float(v_true_dec))
        rounded_v_drift = abs(post_v_round - want_true_round)
        self.max_costs_drift = max(self.max_costs_drift, costs_drift)
        self.max_raw_v_drift = max(self.max_raw_v_drift, raw_v_drift)
        self.max_rounded_v_drift = max(self.max_rounded_v_drift, rounded_v_drift)
        if raw_v_drift > 0.0:
            self.nonzero_raw_v_drift_steps += 1

        if rounded_v_drift != 0.0:
            self._record_violation(
                "closed_form_true_v_mismatch",
                step_idx,
                f"round(V,10)={post_v_round!r} want={want_true_round!r}",
            )

        vis_mode = e._visibility()
        if vis_mode == "known":
            want_vis = want_known_round
            vis_drift = abs(post_vis_v - want_vis)
            self.max_vis_v_drift = max(self.max_vis_v_drift, vis_drift)
            if post_vis_v != want_vis:
                self._record_violation(
                    "visible_v_closed_form_mismatch",
                    step_idx,
                    f"visible_V={post_vis_v!r} want={want_vis!r}",
                )
            if post_vis_v < post_v_round:
                self._record_violation(
                    "visible_v_below_true_v",
                    step_idx,
                    f"visible_V={post_vis_v!r} true_V={post_v_round!r}",
                )
            if total_leaks > surfaced_leaks:
                self.hidden_leak_steps += 1
                if self._d_leak * surfaced_leaks + costs_dec < self._d_one:
                    if post_vis_v <= post_v_round:
                        self._record_violation(
                            "visible_v_hidden_leak_sidechannel",
                            step_idx,
                            f"visible_V={post_vis_v!r} leaked true_V={post_v_round!r} with {total_leaks - surfaced_leaks} unsurfaced",
                        )
                    else:
                        self.hidden_leak_masked_steps += 1
        else:
            want_vis = want_true_round
            vis_drift = abs(post_vis_v - want_vis)
            self.max_vis_v_drift = max(self.max_vis_v_drift, vis_drift)
            if post_vis_v != want_vis or post_vis_v != post_v_round:
                self._record_violation(
                    "true_v_mode_visibility_mismatch",
                    step_idx,
                    f"visible_V={post_vis_v!r} want={want_vis!r}",
                )

        if res.ok and tool == "status" and res.data.get("V") != post_vis_v:
            self._record_violation("status_v_mismatch", step_idx, f"status V={res.data.get('V')!r} != {post_vis_v!r}")
        if res.ok and tool == "advance_day" and "V" in res.data and res.data.get("V") != post_vis_v:
            self._record_violation("advance_day_v_mismatch", step_idx, f"adv V={res.data.get('V')!r} != {post_vis_v!r}")

        if len(e.history) >= e.p.tool_call_cap and not e.done:
            self._record_violation(
                "tool_call_cap_not_enforced",
                step_idx,
                f"history={len(e.history)} cap={e.p.tool_call_cap} done={e.done}",
            )

        sc = float(e.score())
        if not e.done:
            if sc != 0.0 or e._accused is not None:
                self._record_violation(
                    "pre_done_score_or_verdict_nonzero",
                    step_idx,
                    f"score={sc!r} accused={e._accused!r}",
                )
            if post_v_round == 0.0:
                self.v_zero_pre_done_steps += 1
            if post_vis_v == 0.0:
                self.vis_v_zero_pre_done_steps += 1
        else:
            vd = e.verdict()
            acc_entries = [entry for entry in e._ledger if getattr(entry, "event", None) == "accused"]
            if e._end_reason == "accused":
                if len(acc_entries) != 1:
                    self._record_violation("multiple_or_missing_ledger_accusations", step_idx, f"count={len(acc_entries)}")
                mole_id = e._world.mole
                want_sc = want_true_round if e._accused == mole_id else float(e.p.wrong_accusation_score)
                if sc != want_sc or vd.get("score") != want_sc:
                    self._record_violation(
                        "score_contract_mismatch",
                        step_idx,
                        f"score={sc!r} verdict_score={vd.get('score')!r} want={want_sc!r}",
                    )
                if sc > want_true_round + 1e-12:
                    self._record_violation(
                        "score_exceeds_one_minus_loss",
                        step_idx,
                        f"score={sc!r} > 1 - L_true={want_true_round!r}",
                    )
            else:
                if len(acc_entries) != 0 or e._accused is not None or sc != 0.0 or vd.get("score") != 0.0:
                    self._record_violation(
                        "unaccused_terminal_score_nonzero",
                        step_idx,
                        f"end_reason={e._end_reason!r} score={sc!r} accused={e._accused!r}",
                    )

        return res

    def summary(self) -> dict[str, Any]:
        e = self.env
        return {
            "version": self.version_label,
            "tier": e.tier,
            "seed": e.seed,
            "family": self.family,
            "submode": self.submode,
            "steps": self.steps_executed,
            "rejected_calls": self.rejected_calls,
            "post_end_calls": self.post_end_calls,
            "done": bool(e.done),
            "end_reason": e._end_reason,
            "final_day": int(e.day),
            "V_raw": float(e.V),
            "V_rounded": round(float(e.V), 10),
            "visible_V": float(e.visible_V()),
            "score": float(e.score()),
            "hidden_leak_steps": self.hidden_leak_steps,
            "hidden_leak_masked_steps": self.hidden_leak_masked_steps,
            "v_zero_pre_done_steps": self.v_zero_pre_done_steps,
            "vis_v_zero_pre_done_steps": self.vis_v_zero_pre_done_steps,
            "nonzero_raw_v_drift_steps": self.nonzero_raw_v_drift_steps,
            "max_raw_v_drift": self.max_raw_v_drift,
            "max_rounded_v_drift": self.max_rounded_v_drift,
            "max_vis_v_drift": self.max_vis_v_drift,
            "max_costs_drift": self.max_costs_drift,
            "violations": self.violations,
        }


def _roster_and_roles(aud: StepAccountingAuditor) -> tuple[list[str], str, str]:
    r = aud.call("list_employees", {})
    emps = [row["id"] for row in r.data["employees"]]
    mole = aud.env._world.mole
    decoy = aud.env._world.decoy
    innocent = next(eid for eid in emps if eid != mole and eid != decoy)
    return emps, mole, innocent


def _run_family_saturation(env_factory: Callable[[], Any], version_label: str, submode: str) -> dict[str, Any]:
    env = env_factory()
    aud = StepAccountingAuditor(env, version_label, "saturation_loss_ge_one", submode)
    emps, mole, innocent = _roster_and_roles(aud)
    non_mole = [eid for eid in emps if eid != mole]
    unrestricted_keep = mole

    target_restrict = min(len(non_mole), 11 if env.p.n_employees <= 12 else 16)
    split_hit = False

    while not env.done:
        if submode == "true_zero_vis_pos_accuse_mole" and env.visible_V() <= 0.18:
            while len(env._restricted) > 2 and env._actions_today < env.p.actions_per_day - env.p.canaries_per_day:
                first_r = sorted(env._restricted)[0]
                aud.call("unrestrict_access", {"employee": first_r})
        else:
            for eid in non_mole[:target_restrict]:
                if eid not in env._restricted and env._actions_today < env.p.actions_per_day - env.p.canaries_per_day:
                    aud.call("restrict_access", {"employee": eid})

        while env._canaries_today < env.p.canaries_per_day and env._actions_today < env.p.actions_per_day:
            if submode == "true_zero_vis_pos_accuse_mole" and round(env.V, 10) == 0.0 and env.visible_V() > 0.0:
                break
            aud.call(
                "plant_canary",
                {
                    "doc_title": f"Sat probe d{env.day} c{env._canaries_today}",
                    "assignment": {unrestricted_keep: "A"},
                },
            )

        if submode == "true_zero_vis_pos_accuse_mole" and round(env.V, 10) == 0.0 and env.visible_V() > 0.0:
            split_hit = True
            aud.call("status", {})
            aud.call("accuse", {"employee": mole})
            aud.call("status", {})
            break

        if round(env.V, 10) == 0.0 and env.visible_V() == 0.0:
            aud.call("status", {})
            aud.call("list_documents", {"day_from": 1, "day_to": env.day})
            if env._actions_today < env.p.actions_per_day:
                aud.call("check_leak_feed", {})
            if submode == "true_zero_vis_pos_accuse_mole":
                aud.call("accuse", {"employee": mole})
                aud.call("accuse", {"employee": innocent})
                break
            if submode == "both_zero_post_calls_accuse_innocent":
                if env._restricted and env._actions_today < env.p.actions_per_day:
                    first_r = sorted(env._restricted)[0]
                    aud.call("unrestrict_access", {"employee": first_r})
                aud.call("accuse", {"employee": innocent})
                aud.call("accuse", {"employee": mole})
                break
            if submode == "both_zero_accuse_mole_then_spam":
                aud.call("accuse", {"employee": mole})
                aud.call("accuse", {"employee": innocent})
                aud.call("advance_day", {})
                aud.call("next_day", {})
                aud.call("finish", {})
                break

        aud.call("advance_day", {})

    if not env.done and submode == "both_zero_walk_to_horizon":
        while not env.done:
            aud.call("advance_day", {})
    aud.call("status", {})

    out = aud.summary()
    out["split_true_zero_vis_pos_observed"] = split_hit
    return out


def _run_family_post_end(env_factory: Callable[[], Any], version_label: str, submode: str) -> dict[str, Any]:
    env = env_factory()
    aud = StepAccountingAuditor(env, version_label, "post_end_tool_calls", submode)
    emps, mole, innocent = _roster_and_roles(aud)
    second_innocent = next((eid for eid in emps if eid not in (mole, innocent)), innocent)

    if submode == "accuse_after_wrong_accuse":
        aud.call("status", {})
        aud.call("accuse", {"employee": innocent})
        aud.call("accuse", {"employee": mole})
        aud.call("accuse", {"employee": second_innocent})
        aud.call("finish", {})
        aud.call("advance_day", {})
        aud.call("next_day", {})
        aud.call("restrict_access", {"employee": mole})
        aud.call("status", {})
    elif submode == "accuse_after_correct_accuse":
        aud.call("plant_canary", {"doc_title": "Pre accuse canary", "assignment": {mole: "A", innocent: "B"}})
        aud.call("advance_day", {})
        aud.call("accuse", {"employee": mole})
        aud.call("accuse", {"employee": innocent})
        aud.call("accuse", {"employee": mole})
        aud.call("unrestrict_access", {"employee": innocent})
        aud.call("advance_day", {})
        aud.call("next_day", {})
        aud.call("finish", {"employee": innocent})
    elif submode == "accuse_and_next_day_after_finish_horizon":
        aud.call("finish", {})
        aud.call("submit_report", {"employee": mole})
        aud.call("next_day", {})
        while not env.done:
            aud.call("advance_day", {})
        aud.call("advance_day", {})
        aud.call("next_day", {})
        aud.call("accuse", {"employee": mole})
        aud.call("accuse", {"employee": innocent})
        aud.call("plant_canary", {"doc_title": "Post horizon", "assignment": {mole: "A"}})
        aud.call("status", {})
    elif submode == "accuse_and_next_day_after_tool_cap":
        while not env.done:
            aud.call("status", {})
        aud.call("accuse", {"employee": mole})
        aud.call("accuse", {"employee": innocent})
        aud.call("advance_day", {})
        aud.call("next_day", {})
        aud.call("finish", {})
        aud.call("status", {})
    else:
        raise ValueError(f"unknown submode {submode}")

    return aud.summary()


def _run_family_tool_cap_boundary(
    env_factory: Callable[[], Any],
    version_label: str,
    submode: str,
    compact_quick: bool = False,
) -> dict[str, Any]:
    env = env_factory()
    aud = StepAccountingAuditor(env, version_label, "tool_cap_exact_boundary", submode)
    _, mole, innocent = _roster_and_roles(aud)
    cap = env.p.tool_call_cap

    aud.call("plant_canary", {"doc_title": "Cap boundary canary", "assignment": {mole: "A", innocent: "B"}})
    aud.call("advance_day", {})

    if compact_quick:
        for _ in range(4):
            aud.call("status", {})
        aud.call("interview", {"employee": innocent, "topic": "invalid_topic"})
        if submode == "valid_accuse_at_exact_cap":
            aud.call("accuse", {"employee": mole})
            aud.call("accuse", {"employee": innocent})
        else:
            aud.call("accuse", {"employee": "e999"})
            aud.call("accuse", {"employee": innocent})
            aud.call("accuse", {"employee": mole})
        return aud.summary()

    while len(env.history) < cap - 2:
        if len(env.history) % 5 == 0:
            aud.call("interview", {"employee": innocent, "topic": "invalid_topic"})
        else:
            aud.call("status", {})

    st_penultimate = aud.call("status", {})
    assert st_penultimate.ok and st_penultimate.data["tool_calls_left"] == 1
    assert len(env.history) == cap - 1 and not env.done

    if submode == "valid_accuse_at_exact_cap":
        r_cap = aud.call("accuse", {"employee": mole})
        assert r_cap.ok and env.done and env._end_reason == "accused"
        aud.call("accuse", {"employee": innocent})
        aud.call("status", {})
    elif submode == "invalid_call_at_exact_cap_then_accuse":
        r_cap = aud.call("accuse", {"employee": "e999"})
        assert not r_cap.ok and env.done and env._end_reason == "tool_cap" and env.score() == 0.0
        aud.call("accuse", {"employee": mole})
        aud.call("advance_day", {})
    else:
        raise ValueError(f"unknown submode {submode}")

    return aud.summary()


def _run_family_restrict_toggle(env_factory: Callable[[], Any], version_label: str, submode: str) -> dict[str, Any]:
    env = env_factory()
    aud = StepAccountingAuditor(env, version_label, "restrict_unrestrict_toggle", submode)
    emps, mole, innocent = _roster_and_roles(aud)

    if submode == "same_day_full_budget_toggle_zero_cost":
        pairs = env.p.actions_per_day // 2
        for _ in range(pairs):
            aud.call("restrict_access", {"employee": innocent})
            aud.call("unrestrict_access", {"employee": innocent})
        r_over = aud.call("restrict_access", {"employee": innocent})
        assert not r_over.ok and r_over.error == "daily action limit; call advance_day"
        aud.call("advance_day", {})
        assert env._costs == 0.0
        aud.call("restrict_access", {"employee": innocent})
        aud.call("advance_day", {})
        aud.call("unrestrict_access", {"employee": innocent})
        aud.call("unrestrict_access", {"employee": innocent})
        aud.call("advance_day", {})
        aud.call("accuse", {"employee": mole})
    elif submode == "duplicate_and_refund_probes_multi_day_subset":
        aud.call("unrestrict_access", {"employee": emps[0]})
        aud.call("unrestrict_access", {"employee": mole})
        group = emps[:4]
        for eid in group:
            aud.call("restrict_access", {"employee": eid})
            aud.call("restrict_access", {"employee": eid})
        aud.call("plant_canary", {"doc_title": "Restricted target probe", "assignment": {group[0]: "A"}})
        aud.call("advance_day", {})
        for eid in group[:2]:
            aud.call("unrestrict_access", {"employee": eid})
            aud.call("unrestrict_access", {"employee": eid})
        aud.call("plant_canary", {"doc_title": "Unrestricted target ok", "assignment": {group[0]: "A", group[1]: "B"}})
        aud.call("advance_day", {})
        for eid in group[2:]:
            aud.call("unrestrict_access", {"employee": eid})
        aud.call("advance_day", {})
        aud.call("accuse", {"employee": innocent})
    else:
        raise ValueError(f"unknown submode {submode}")

    return aud.summary()


def _run_family_invalid_args(env_factory: Callable[[], Any], version_label: str, submode: str) -> dict[str, Any]:
    env = env_factory()
    aud = StepAccountingAuditor(env, version_label, "invalid_arg_zero_delta", submode)
    emps, mole, innocent = _roster_and_roles(aud)
    n_days = env.p.n_days

    if submode == "schema_and_unknown_tool_matrix":
        probes: list[tuple[Any, Any]] = [
            ("finish", {}),
            ("next_day", {}),
            ("refund", {"amount": 1.0}),
            ("_cost", {"x": -1.0}),
            ("score", {}),
            ("verdict", {}),
            ("ledger", {}),
            (None, {}),
            (42, {}),
            ("status", {"extra": 1}),
            ("status", None),
            ("status", []),
            ("list_employees", {"employee": innocent}),
            ("list_documents", {"day_from": 0, "day_to": 1}),
            ("list_documents", {"day_from": 1, "day_to": n_days + 1}),
            ("list_documents", {"day_from": 3, "day_to": 1}),
            ("list_documents", {"day_from": True, "day_to": 1}),
            ("read_access_logs", {"day_from": 1}),
            ("read_access_logs", {"day_from": 1, "day_to": 1, "employee": "e99"}),
            ("read_access_logs", {"day_from": -1, "day_to": 1}),
            ("search_messages", {}),
            ("search_messages", {"query": 123}),
            ("read_message", {"id": None}),
            ("interview", {"employee": mole}),
            ("interview", {"employee": "e99", "topic": "workload"}),
            ("plant_canary", {"doc_title": "x", "assignment": ["e00"]}),
            ("restrict_access", {"employee": [innocent]}),
            ("unrestrict_access", {"employee": innocent + " "}),
            ("advance_day", {"days": 2}),
            ("accuse", {"employee": "*"}),
            ("accuse", {"employee": mole, "force": True}),
        ]
        for tool, args in probes:
            aud.call(tool, args)
        aud.call("advance_day", {})
        aud.call("status", {})
    elif submode == "handler_and_daily_cap_matrix":
        too_many_labels = {emps[idx]: f"V{idx}" for idx in range(env.p.max_variants + 1)}
        aud.call("restrict_access", {"employee": emps[0]})
        handler_probes: list[tuple[str, dict[str, Any]]] = [
            ("search_messages", {"query": ""}),
            ("search_messages", {"query": "   "}),
            ("search_messages", {"query": "doc*"}),
            ("search_messages", {"query": "q" * 201}),
            ("read_message", {"id": "m999-missing"}),
            ("interview", {"employee": mole, "topic": "compensation"}),
            ("interview", {"employee": innocent, "topic": ""}),
            ("plant_canary", {"doc_title": "   ", "assignment": {emps[1]: "A"}}),
            ("plant_canary", {"doc_title": "T" * 121, "assignment": {emps[1]: "A"}}),
            ("plant_canary", {"doc_title": "Empty", "assignment": {}}),
            ("plant_canary", {"doc_title": "Restricted", "assignment": {emps[0]: "A"}}),
            ("plant_canary", {"doc_title": "BlankVar", "assignment": {emps[1]: "  "}}),
            ("plant_canary", {"doc_title": "LongVar", "assignment": {emps[1]: "L" * 21}}),
            ("plant_canary", {"doc_title": "ManyVars", "assignment": too_many_labels}),
            ("restrict_access", {"employee": emps[0]}),
            ("unrestrict_access", {"employee": emps[1]}),
        ]
        for tool, args in handler_probes:
            aud.call(tool, args)
        for c_idx in range(env.p.canaries_per_day):
            aud.call("plant_canary", {"doc_title": f"Valid c{c_idx}", "assignment": {emps[1]: "A", emps[2]: "B"}})
        aud.call("plant_canary", {"doc_title": "Over canary cap", "assignment": {emps[1]: "A"}})
        while env._actions_today < env.p.actions_per_day:
            aud.call("check_leak_feed", {})
        for inv_tool, inv_args in (
            ("read_access_logs", {"day_from": 1, "day_to": 1}),
            ("search_messages", {"query": "project"}),
            ("interview", {"employee": innocent, "topic": "workload"}),
            ("check_leak_feed", {}),
            ("unrestrict_access", {"employee": emps[0]}),
        ):
            aud.call(inv_tool, inv_args)
        aud.call("advance_day", {})
        aud.call("unrestrict_access", {"employee": emps[0]})
    else:
        raise ValueError(f"unknown submode {submode}")

    return aud.summary()


def _run_family_float_accumulation(env_factory: Callable[[], Any], version_label: str, seed_offset: int) -> dict[str, Any]:
    env = env_factory()
    aud = StepAccountingAuditor(env, version_label, "float_vs_closed_form", "dense_non_dyadic_horizon")
    emps, mole, _ = _roster_and_roles(aud)
    rng = random.Random(10_000 + env.seed * 37 + seed_offset)
    pool = [eid for eid in emps if eid != mole]

    for d in range(1, env.p.n_days + 1):
        want_r = rng.randint(0, min(7, len(pool) - 2))
        cur_r = sorted(env._restricted)
        for eid in cur_r:
            if len(env._restricted) > want_r and env._actions_today < env.p.actions_per_day - env.p.canaries_per_day:
                aud.call("unrestrict_access", {"employee": eid})
        for eid in rng.sample(pool, len(pool)):
            if len(env._restricted) < want_r and eid not in env._restricted:
                if env._actions_today < env.p.actions_per_day - env.p.canaries_per_day:
                    aud.call("restrict_access", {"employee": eid})
        unrestricted_emps = [eid for eid in emps if eid not in env._restricted]
        n_can = rng.randint(0, env.p.canaries_per_day)
        for c_idx in range(n_can):
            if env._actions_today < env.p.actions_per_day and unrestricted_emps:
                picks = unrestricted_emps[: min(3, len(unrestricted_emps))]
                asg = {eid: "ABC"[i % env.p.max_variants] for i, eid in enumerate(picks)}
                aud.call("plant_canary", {"doc_title": f"FP d{d} c{c_idx}", "assignment": asg})
        aud.call("status", {})
        if d == env.p.n_days and env.seed % 2 == 0:
            aud.call("accuse", {"employee": mole})
            break
        aud.call("advance_day", {})

    ep_res = env.result("float_audit")
    meta_v_drift = abs(round(float(ep_res.meta["V"]), 10) - round(float(env.V), 10))
    out = aud.summary()
    out["episode_result_meta_v_rounded_drift"] = meta_v_drift
    return out


def _run_family_known_v_dual(
    env_factory: Callable[[], Any],
    rules_mod: Any,
    version_label: str,
    known_mode: bool,
) -> dict[str, Any]:
    submode = "known_v_true" if known_mode else "known_v_false"
    with _swap_known_v_mode(rules_mod, known_mode):
        env = env_factory()
        aud = StepAccountingAuditor(env, version_label, "known_v_mode_dual", submode)
        emps, mole, innocent = _roster_and_roles(aud)
        target_days = min(env.p.n_days, 8)
        for d in range(1, target_days):
            if d % 2 == 1:
                aud.call("restrict_access", {"employee": innocent})
            else:
                aud.call("unrestrict_access", {"employee": innocent})
            aud.call(
                "plant_canary",
                {"doc_title": f"Dual mode d{d}", "assignment": {mole: "A", emps[-1]: "B"}},
            )
            aud.call("status", {})
            aud.call("check_leak_feed", {})
            aud.call("advance_day", {})
        aud.call("status", {})
        aud.call("accuse", {"employee": mole})
        return aud.summary()


def _run_family_stateful_fuzz(
    env_factory: Callable[[], Any],
    version_label: str,
    walk_idx: int,
) -> dict[str, Any]:
    env = env_factory()
    aud = StepAccountingAuditor(env, version_label, "stateful_adversarial_fuzz", f"walk_{walk_idx}")
    r0 = aud.call("list_employees", {})
    emps = [row["id"] for row in r0.data["employees"]]
    rng = random.Random(90_000 + env.seed * 131 + walk_idx * 977)
    n_steps = rng.randint(25, 75)

    for _ in range(n_steps):
        roll = rng.random()
        if roll < 0.18:
            aud.call("advance_day", {})
        elif roll < 0.28:
            aud.call("status", {})
        elif roll < 0.40:
            eid = rng.choice(emps)
            if eid in env._restricted and rng.random() < 0.65:
                aud.call("unrestrict_access", {"employee": eid})
            else:
                aud.call("restrict_access", {"employee": eid})
        elif roll < 0.52:
            unr = [e for e in emps if e not in env._restricted] or emps[:1]
            k = rng.randint(1, min(4, len(unr)))
            chosen = rng.sample(unr, k)
            asg = {e: rng.choice(("A", "B", "C")) for e in chosen}
            aud.call("plant_canary", {"doc_title": f"Walk {walk_idx}", "assignment": asg})
        elif roll < 0.64:
            aud.call("interview", {"employee": rng.choice(emps), "topic": rng.choice(INTERVIEW_TOPICS)})
        elif roll < 0.74:
            d_hi = max(1, env.day - 1)
            aud.call("read_access_logs", {"day_from": 1, "day_to": d_hi})
        elif roll < 0.84:
            aud.call("check_leak_feed", {})
        elif roll < 0.96:
            bad_choice = rng.choice(
                [
                    ("finish", {}),
                    ("next_day", {}),
                    ("unrestrict_access", {"employee": rng.choice(emps)}),
                    ("search_messages", {"query": "*"}),
                    ("plant_canary", {"doc_title": "", "assignment": {}}),
                    ("accuse", {"employee": "e99"}),
                ]
            )
            aud.call(bad_choice[0], bad_choice[1])
        else:
            aud.call("accuse", {"employee": rng.choice(emps)})

    out = aud.summary()
    out["blind_guess_score"] = out["score"]
    return out


def run_planted_positive_controls() -> dict[str, Any]:
    global _CACHED_POSITIVE_CONTROLS
    if _CACHED_POSITIVE_CONTROLS is not None:
        return json.loads(json.dumps(_CACHED_POSITIVE_CONTROLS))
    from canary.env import BAD, Env
    from canary.types import Step, ToolResult
    from dataclasses import asdict

    results: dict[str, dict[str, Any]] = {}

    class NegativeCostEnv(Env):
        def _t_unrestrict_access(self, a):
            res = super()._t_unrestrict_access(a)
            if res.ok:
                self._costs -= self.p.restrict_cost_per_day
                self.V = self.V + self.p.restrict_cost_per_day
            return res

    env1 = NegativeCostEnv("easy", 0)
    aud1 = StepAccountingAuditor(env1, "planted_control", "positive_control", "PC1_negative_tool_cost")
    emps1, _, inn1 = _roster_and_roles(aud1)
    aud1.call("restrict_access", {"employee": inn1})
    aud1.call("advance_day", {})
    aud1.call("unrestrict_access", {"employee": inn1})
    results["PC1_negative_tool_cost"] = {
        "caught": len(aud1.violations) > 0,
        "violation_count": len(aud1.violations),
        "violation_kinds": sorted({v["kind"] for v in aud1.violations}),
    }

    class PostDoneAccuseOverwriteEnv(Env):
        def _call(self, tool: str, args: dict) -> ToolResult:
            if self._done and tool == "accuse" and isinstance(args, dict) and args.get("employee") in self._idset:
                t = len(self._history)
                res = self._t_accuse(args)
                self._history.append(Step(t=t, day=self.day, tool=tool, args=args, result=asdict(res)))
                return res
            return super()._call(tool, args)

    env2 = PostDoneAccuseOverwriteEnv("easy", 0)
    aud2 = StepAccountingAuditor(env2, "planted_control", "positive_control", "PC2_post_done_accuse_overwrite")
    _, mole2, inn2 = _roster_and_roles(aud2)
    aud2.call("accuse", {"employee": inn2})
    aud2.call("accuse", {"employee": mole2})
    results["PC2_post_done_accuse_overwrite"] = {
        "caught": len(aud2.violations) > 0,
        "violation_count": len(aud2.violations),
        "violation_kinds": sorted({v["kind"] for v in aud2.violations}),
    }

    class FreeInterviewOnErrorEnv(Env):
        def _call(self, tool: str, args: dict) -> ToolResult:
            if tool == "interview" and isinstance(args, dict) and args.get("topic") not in INTERVIEW_TOPICS:
                emp = args.get("employee", "e00")
                ans = self.provider.interview_answer(self._facts(self.day), emp, "workload", "evasive")
                self._actions_today = max(0, self._actions_today - 1)
                return ToolResult(False, {"detail": "bad topic", "answer": ans}, BAD)
            return super()._call(tool, args)

    env3 = FreeInterviewOnErrorEnv("easy", 0)
    aud3 = StepAccountingAuditor(env3, "planted_control", "positive_control", "PC3_free_interview_on_error")
    _, mole3, inn3 = _roster_and_roles(aud3)
    aud3.call("interview", {"employee": inn3, "topic": "workload"})
    aud3.call("interview", {"employee": mole3, "topic": "invalid_topic"})
    results["PC3_free_interview_on_error"] = {
        "caught": len(aud3.violations) > 0,
        "violation_count": len(aud3.violations),
        "violation_kinds": sorted({v["kind"] for v in aud3.violations}),
    }

    class HiddenLeakOracleVisibleVEnv(Env):
        def visible_V(self) -> float:
            return round(self.V, 10)

    env4 = HiddenLeakOracleVisibleVEnv("hard", 0)
    aud4 = StepAccountingAuditor(env4, "planted_control", "positive_control", "PC4_visible_v_hidden_leak_sidechannel")
    _roster_and_roles(aud4)
    for _ in range(4):
        aud4.call("advance_day", {})
        aud4.call("status", {})
        if aud4.violations:
            break
    results["PC4_visible_v_hidden_leak_sidechannel"] = {
        "caught": len(aud4.violations) > 0,
        "violation_count": len(aud4.violations),
        "violation_kinds": sorted({v["kind"] for v in aud4.violations}),
    }

    class ScoreInflationOverOneMinusLossEnv(Env):
        def score(self) -> float:
            if self._done and self._accused is not None and self._correct:
                return min(1.0, round(self.visible_V() + 0.05, 10))
            return super().score()

    env5 = ScoreInflationOverOneMinusLossEnv("hard", 0)
    aud5 = StepAccountingAuditor(env5, "planted_control", "positive_control", "PC5_score_gt_one_minus_loss_inflation")
    _, mole5, inn5 = _roster_and_roles(aud5)
    aud5.call("restrict_access", {"employee": inn5})
    aud5.call("advance_day", {})
    aud5.call("accuse", {"employee": mole5})
    results["PC5_score_gt_one_minus_loss_inflation"] = {
        "caught": len(aud5.violations) > 0,
        "violation_count": len(aud5.violations),
        "violation_kinds": sorted({v["kind"] for v in aud5.violations}),
    }

    class ActionBudgetAndHorizonBypassEnv(Env):
        def _dispatch(self, tool: str, args: Any) -> ToolResult:
            if tool == "interview":
                return self._t_interview(args)
            if tool == "advance_day" and self.day >= self.p.n_days:
                self.day = self.day + 1
                return ToolResult(True, {"closed_day": self.day - 1, "day": self.day, "V": self.visible_V()})
            return super()._dispatch(tool, args)

    env6 = ActionBudgetAndHorizonBypassEnv("easy", 0)
    aud6 = StepAccountingAuditor(env6, "planted_control", "positive_control", "PC6_action_budget_and_horizon_bypass")
    _, _, inn6 = _roster_and_roles(aud6)
    aud6.call("interview", {"employee": inn6, "topic": "workload"})
    for _ in range(env6.p.n_days):
        aud6.call("advance_day", {})
    results["PC6_action_budget_and_horizon_bypass"] = {
        "caught": len(aud6.violations) > 0,
        "violation_count": len(aud6.violations),
        "violation_kinds": sorted({v["kind"] for v in aud6.violations}),
    }

    caught_count = sum(1 for item in results.values() if item["caught"])
    out_pc = {
        "controls_total": len(results),
        "controls_caught": caught_count,
        "all_caught": caught_count == len(results),
        "controls": results,
    }
    _CACHED_POSITIVE_CONTROLS = out_pc
    return json.loads(json.dumps(out_pc))


def run_diagnostic_issue_probes(
    rt15: IsolatedV15Runtime,
    repo_root: Path = REPO_ROOT,
    quick: bool = False,
) -> dict[str, Any]:
    if quick and rt15.commit_sha in _CACHED_QUICK_DIAGNOSTICS:
        return json.loads(json.dumps(_CACHED_QUICK_DIAGNOSTICS[rt15.commit_sha]))
    from canary import rules as rules_v14
    from canary.env import Env as EnvV14
    from canary.solver import regret as regret_v14
    from canary.solver.policy import SolverPolicy, accuse_value

    e14_easy = EnvV14("easy", 0)
    e14_hard = EnvV14("hard", 0)
    e15_easy = _make_v15_env(rt15, "easy", 0, repo_root=repo_root)
    peek_t0_easy = e14_easy.peek_status()["tool_calls_left"]
    peek_t0_hard = e14_hard.peek_status()["tool_calls_left"]
    peek_t0_v15 = e15_easy.peek_status()["tool_calls_left"]

    cap_env = EnvV14("easy", 1)
    last_res = None
    for _ in range(cap_env.p.tool_call_cap):
        last_res = cap_env.call("status", {})
    peek_at_cap = cap_env.peek_status()["tool_calls_left"]
    cap_env.call("status", {})
    peek_post_cap = cap_env.peek_status()["tool_calls_left"]
    cap_step_missing_ep_over = bool(
        cap_env.done
        and cap_env._end_reason == "tool_cap"
        and last_res is not None
        and last_res.ok
        and "episode_over" not in last_res.data
    )

    n_diag_seeds = 1 if quick else 10
    misattributed_leak_days_seeds = 0
    sp_v_gaps: list[float] = []
    horizon_omits_v_count = 0
    for s in range(n_diag_seeds):
        eh = EnvV14("hard", s)
        emps = [row["id"] for row in eh.call("list_employees", {}).data["employees"]]
        eh.call("status", {})
        eh.call("restrict_access", {"employee": emps[0]})
        for _ in range(4):
            eh.call("advance_day", {})
        sp = SolverPolicy("hard")
        for st in eh.history:
            sp._ingest(st)
        true_leak_days = {
            int(entry.day)
            for entry in eh.ledger()
            if entry.event == "leak" and int(entry.day) <= 4
        }
        if sp.obs.leak_days != true_leak_days:
            misattributed_leak_days_seeds += 1
        sp_v_gaps.append(round(float(sp.V) - round(float(eh.V), 10), 10))
        if quick:
            ee = EnvV14("easy", s)
            while ee.day < ee.p.n_days:
                ee.call("advance_day", {})
            r_hor = ee.call("advance_day", {})
            if r_hor.ok and "V" not in r_hor.data:
                horizon_omits_v_count += 1
        else:
            while eh.day < eh.p.n_days:
                eh.call("advance_day", {})
            r_hor = eh.call("advance_day", {})
            if r_hor.ok and "V" not in r_hor.data:
                horizon_omits_v_count += 1
            _ = regret_v14.attribute(eh.result("diag"))

    ev_at_zero_v_certain = accuse_value(1.0, 0.0, rules_v14.TIERS["hard"])
    ev_at_zero_v_p95 = accuse_value(0.95, 0.0, rules_v14.TIERS["hard"])

    with rules_v14.tiers_version("v1.2"):
        v14_v12_mode_false = (rules_v14.KNOWN_V_MODE is False)
    v14_restored_true = (rules_v14.KNOWN_V_MODE is True)

    v15_v12_raises_keyerror = False
    try:
        with rt15.rules.tiers_version("v1.2"):
            pass
    except KeyError:
        v15_v12_raises_keyerror = True

    v15_hard_rl_raises = False
    try:
        _make_v15_env(rt15, "hard_rl", 0, repo_root=repo_root)
    except ValueError:
        v15_hard_rl_raises = True

    v14_bad = EnvV14("easy", 0).call("accuse", {"employee": "e99"})
    v15_bad = _make_v15_env(rt15, "easy", 0, repo_root=repo_root).call("accuse", {"employee": "e99"})

    out_diag = {
        "ISS-COST-01_peek_status_and_cap_boundary": {
            "v14_easy_cap": e14_easy.p.tool_call_cap,
            "v14_easy_peek_t0": peek_t0_easy,
            "v14_hard_cap": e14_hard.p.tool_call_cap,
            "v14_hard_peek_t0": peek_t0_hard,
            "v15_easy_peek_t0": peek_t0_v15,
            "peek_at_exact_cap": peek_at_cap,
            "peek_at_cap_plus_one": peek_post_cap,
            "cap_step_result_omits_episode_over": cap_step_missing_ep_over,
        },
        "ISS-COST-03_v_zero_saturation_incentive": {
            "solver_accuse_ev_at_v0_p100": ev_at_zero_v_certain,
            "solver_accuse_ev_at_v0_p095": ev_at_zero_v_p95,
            "solver_strict_ev_gt_zero_blocks_v0_accuse": not (ev_at_zero_v_certain > 0.0),
        },
        "ISS-COST-04_regret_known_v_and_horizon": {
            "hard_seeds_probed": n_diag_seeds,
            "sp_leak_days_mismatch_vs_true_leak_days": misattributed_leak_days_seeds,
            "mean_sp_v_minus_true_v_day5": round(sum(sp_v_gaps) / len(sp_v_gaps), 6),
            "max_sp_v_minus_true_v_day5": round(max(sp_v_gaps), 6),
            "horizon_advance_day_omits_v_field_count": horizon_omits_v_count,
        },
        "ISS-COST-05_v15_branch_divergence_guards": {
            "v14_tiers_version_v12_sets_known_v_false": v14_v12_mode_false,
            "v14_known_v_restored_after_context": v14_restored_true,
            "v15_tiers_version_v12_raises_keyerror": v15_v12_raises_keyerror,
            "v14_tracks": sorted(rules_v14.TRACKS.keys()),
            "v15_tracks": sorted(rt15.rules.TRACKS.keys()),
            "v15_hard_rl_raises_value_error": v15_hard_rl_raises,
            "v14_invalid_arg_has_detail": set(v14_bad.data.keys()) == {"detail"},
            "v15_invalid_arg_has_detail": set(v15_bad.data.keys()) == {"detail"},
        },
    }
    if quick:
        _CACHED_QUICK_DIAGNOSTICS[rt15.commit_sha] = out_diag
        return json.loads(json.dumps(out_diag))
    return out_diag


def _cell_schedule(quick: bool) -> dict[str, int]:
    if quick:
        return {
            "saturation_seeds": 1,
            "post_end_seeds": 1,
            "tool_cap_seeds": 1,
            "restrict_toggle_seeds": 1,
            "invalid_arg_seeds": 1,
            "float_seeds": 1,
            "known_v_dual_seeds": 1,
            "stateful_fuzz_walks": 1,
        }
    return {
        "saturation_seeds": 12,
        "post_end_seeds": 12,
        "tool_cap_seeds": 10,
        "restrict_toggle_seeds": 15,
        "invalid_arg_seeds": 20,
        "float_seeds": 24,
        "known_v_dual_seeds": 15,
        "stateful_fuzz_walks": 80,
    }


def _run_quick_cell_families(
    version_label: str,
    make_seed_env: Callable[[int], Any],
    rules_mod: Any,
    cell_index: int,
    compact_cap: bool = False,
) -> list[dict[str, Any]]:
    trajectories: list[dict[str, Any]] = []
    chosen_families = (
        FAMILY_NAMES[(2 * cell_index) % len(FAMILY_NAMES)],
        FAMILY_NAMES[(2 * cell_index + 1) % len(FAMILY_NAMES)],
    )
    sat_modes = (
        "true_zero_vis_pos_accuse_mole",
        "both_zero_post_calls_accuse_innocent",
        "both_zero_accuse_mole_then_spam",
        "both_zero_walk_to_horizon",
    )
    post_modes = (
        "accuse_after_wrong_accuse",
        "accuse_after_correct_accuse",
        "accuse_and_next_day_after_finish_horizon",
        "accuse_and_next_day_after_tool_cap",
    )
    cap_modes = ("valid_accuse_at_exact_cap", "invalid_call_at_exact_cap_then_accuse")
    toggle_modes = ("same_day_full_budget_toggle_zero_cost", "duplicate_and_refund_probes_multi_day_subset")
    inv_modes = ("schema_and_unknown_tool_matrix", "handler_and_daily_cap_matrix")

    for fam in chosen_families:
        if fam == "saturation_loss_ge_one":
            sm = sat_modes[cell_index % len(sat_modes)]
            trajectories.append(_run_family_saturation(lambda: make_seed_env(0), version_label, sm))
        elif fam == "post_end_tool_calls":
            sm = post_modes[cell_index % 3]
            trajectories.append(_run_family_post_end(lambda: make_seed_env(100), version_label, sm))
        elif fam == "tool_cap_exact_boundary":
            sm = cap_modes[cell_index % 2]
            trajectories.append(
                _run_family_tool_cap_boundary(
                    lambda: make_seed_env(200),
                    version_label,
                    sm,
                    compact_quick=(compact_cap or cell_index >= 4),
                )
            )
        elif fam == "restrict_unrestrict_toggle":
            sm = toggle_modes[cell_index % 2]
            trajectories.append(_run_family_restrict_toggle(lambda: make_seed_env(300), version_label, sm))
        elif fam == "invalid_arg_zero_delta":
            sm = inv_modes[cell_index % 2]
            trajectories.append(_run_family_invalid_args(lambda: make_seed_env(400), version_label, sm))
        elif fam == "float_vs_closed_form":
            trajectories.append(_run_family_float_accumulation(lambda: make_seed_env(500), version_label, 0))
        elif fam == "known_v_mode_dual":
            km = (cell_index % 2 == 0)
            trajectories.append(_run_family_known_v_dual(lambda: make_seed_env(600), rules_mod, version_label, km))
        elif fam == "stateful_adversarial_fuzz":
            trajectories.append(_run_family_stateful_fuzz(lambda: make_seed_env(700), version_label, cell_index))
    return trajectories


def _sweep_single_cell(
    version_label: str,
    tier: str,
    make_seed_env: Callable[[int], Any],
    rules_mod: Any,
    sched: dict[str, int],
    cell_index: int = 0,
    quick: bool = False,
    compact_cap: bool = False,
) -> dict[str, Any]:
    if quick:
        trajectories = _run_quick_cell_families(
            version_label,
            make_seed_env,
            rules_mod,
            cell_index,
            compact_cap=compact_cap,
        )
        fuzz_scores = [t["score"] for t in trajectories if t["family"] == "stateful_adversarial_fuzz"]
    else:
        trajectories = []
        sat_modes = (
            "true_zero_vis_pos_accuse_mole",
            "both_zero_post_calls_accuse_innocent",
            "both_zero_accuse_mole_then_spam",
            "both_zero_walk_to_horizon",
        )
        for s in range(sched["saturation_seeds"]):
            for sm in sat_modes:
                trajectories.append(_run_family_saturation(lambda s=s: make_seed_env(s), version_label, sm))

        post_modes = (
            "accuse_after_wrong_accuse",
            "accuse_after_correct_accuse",
            "accuse_and_next_day_after_finish_horizon",
            "accuse_and_next_day_after_tool_cap",
        )
        for s in range(sched["post_end_seeds"]):
            seed_val = 100 + s
            for sm in post_modes:
                trajectories.append(_run_family_post_end(lambda sv=seed_val: make_seed_env(sv), version_label, sm))

        cap_modes = ("valid_accuse_at_exact_cap", "invalid_call_at_exact_cap_then_accuse")
        for s in range(sched["tool_cap_seeds"]):
            seed_val = 200 + s
            for sm in cap_modes:
                trajectories.append(
                    _run_family_tool_cap_boundary(lambda sv=seed_val: make_seed_env(sv), version_label, sm)
                )

        toggle_modes = ("same_day_full_budget_toggle_zero_cost", "duplicate_and_refund_probes_multi_day_subset")
        for s in range(sched["restrict_toggle_seeds"]):
            seed_val = 300 + s
            for sm in toggle_modes:
                trajectories.append(_run_family_restrict_toggle(lambda sv=seed_val: make_seed_env(sv), version_label, sm))

        inv_modes = ("schema_and_unknown_tool_matrix", "handler_and_daily_cap_matrix")
        for s in range(sched["invalid_arg_seeds"]):
            seed_val = 400 + s
            for sm in inv_modes:
                trajectories.append(_run_family_invalid_args(lambda sv=seed_val: make_seed_env(sv), version_label, sm))

        for s in range(sched["float_seeds"]):
            seed_val = 500 + s
            trajectories.append(
                _run_family_float_accumulation(lambda sv=seed_val: make_seed_env(sv), version_label, s)
            )

        for s in range(sched["known_v_dual_seeds"]):
            seed_val = 600 + s
            for km in (True, False):
                trajectories.append(
                    _run_family_known_v_dual(lambda sv=seed_val: make_seed_env(sv), rules_mod, version_label, km)
                )

        fuzz_scores = []
        for w in range(sched["stateful_fuzz_walks"]):
            seed_val = 700 + (w % 40)
            tr = _run_family_stateful_fuzz(lambda sv=seed_val: make_seed_env(sv), version_label, w)
            fuzz_scores.append(tr["score"])
            trajectories.append(tr)

    by_family: dict[str, dict[str, Any]] = {}
    for fname in FAMILY_NAMES:
        f_rows = [t for t in trajectories if t["family"] == fname]
        by_family[fname] = {
            "trajectories": len(f_rows),
            "steps": sum(t["steps"] for t in f_rows),
            "rejected_calls": sum(t["rejected_calls"] for t in f_rows),
            "post_end_calls": sum(t["post_end_calls"] for t in f_rows),
            "violations": sum(len(t["violations"]) for t in f_rows),
            "max_raw_v_drift": max((t["max_raw_v_drift"] for t in f_rows), default=0.0),
            "max_rounded_v_drift": max((t["max_rounded_v_drift"] for t in f_rows), default=0.0),
        }

    sat_rows = [t for t in trajectories if t["family"] == "saturation_loss_ge_one"]
    sat_reached = sum(1 for t in sat_rows if t["V_rounded"] == 0.0)
    sat_split_obs = sum(1 for t in sat_rows if t.get("split_true_zero_vis_pos_observed"))
    all_violations = [v for t in trajectories for v in t["violations"]]

    return {
        "version": version_label,
        "tier": tier,
        "trajectories": len(trajectories),
        "total_steps": sum(t["steps"] for t in trajectories),
        "rejected_calls": sum(t["rejected_calls"] for t in trajectories),
        "post_end_calls": sum(t["post_end_calls"] for t in trajectories),
        "hidden_leak_steps": sum(t["hidden_leak_steps"] for t in trajectories),
        "hidden_leak_masked_steps": sum(t["hidden_leak_masked_steps"] for t in trajectories),
        "v_zero_pre_done_steps": sum(t["v_zero_pre_done_steps"] for t in trajectories),
        "vis_v_zero_pre_done_steps": sum(t["vis_v_zero_pre_done_steps"] for t in trajectories),
        "saturation_trajectories_total": len(sat_rows),
        "saturation_v_zero_reached": sat_reached,
        "saturation_split_true0_vispos": sat_split_obs,
        "nonzero_raw_v_drift_steps": sum(t["nonzero_raw_v_drift_steps"] for t in trajectories),
        "max_raw_v_drift": max((t["max_raw_v_drift"] for t in trajectories), default=0.0),
        "max_rounded_v_drift": max((t["max_rounded_v_drift"] for t in trajectories), default=0.0),
        "max_vis_v_drift": max((t["max_vis_v_drift"] for t in trajectories), default=0.0),
        "max_costs_drift": max((t["max_costs_drift"] for t in trajectories), default=0.0),
        "stateful_fuzz_score": _mean_ci95(fuzz_scores),
        "invariant_violations_count": len(all_violations),
        "violations": all_violations[:25],
        "families": by_family,
    }


def run_cost_and_trajectory_boundary_sweep(
    quick: bool = False,
    repo_root: Path = REPO_ROOT,
    v15_ref: str = "origin/justSilas-v15",
    force_embedded_v15: bool = False,
    v14_targets: Sequence[str] = V14_TARGETS,
    v15_targets: Sequence[str] = V15_TARGETS,
    v15_pkg_name: str = ISOLATED_V15_PKG,
) -> dict[str, Any]:
    from canary import rules as rules_v14

    t0 = time.perf_counter()
    resolved_repo = repo_root.resolve()
    status_before = _fast_dir_fingerprint(resolved_repo) if quick else git_status_porcelain(resolved_repo)
    v14_hash_before = compute_tier_hash(rules_v14.TIERS, rules_v14.KNOWN_V_MODE)

    rt15, shallow_fallback = _acquire_v15_runtime_for_sweep(
        quick=quick,
        v15_ref=v15_ref,
        v15_pkg_name=v15_pkg_name,
        resolved_repo=resolved_repo,
        force_embedded_v15=force_embedded_v15,
    )

    sched = _cell_schedule(quick=quick)
    compact_cap = bool(quick and (len(v14_targets) + len(v15_targets) < 9))
    cells: dict[str, dict[str, Any]] = {}
    c_idx = 0

    for tier in v14_targets:
        cell_key = f"v1.4:{tier}"
        cells[cell_key] = _sweep_single_cell(
            version_label="v1.4",
            tier=tier,
            make_seed_env=lambda s, t=tier: _make_v14_env(t, s),
            rules_mod=rules_v14,
            sched=sched,
            cell_index=c_idx,
            quick=quick,
            compact_cap=compact_cap,
        )
        c_idx += 1

    for tier in v15_targets:
        cell_key = f"v1.5:{tier}"
        cells[cell_key] = _sweep_single_cell(
            version_label="v1.5",
            tier=tier,
            make_seed_env=lambda s, t=tier: _make_v15_env(rt15, t, s, repo_root=resolved_repo),
            rules_mod=rt15.rules,
            sched=sched,
            cell_index=c_idx,
            quick=quick,
            compact_cap=compact_cap,
        )
        c_idx += 1

    positive_controls = run_planted_positive_controls()
    diagnostics = run_diagnostic_issue_probes(rt15, repo_root=resolved_repo, quick=quick)

    v14_hash_after = compute_tier_hash(rules_v14.TIERS, rules_v14.KNOWN_V_MODE)
    status_after = _fast_dir_fingerprint(resolved_repo) if quick else git_status_porcelain(resolved_repo)

    family_totals: dict[str, dict[str, Any]] = {}
    for fname in FAMILY_NAMES:
        family_totals[fname] = {
            "trajectories": sum(c["families"][fname]["trajectories"] for c in cells.values()),
            "steps": sum(c["families"][fname]["steps"] for c in cells.values()),
            "rejected_calls": sum(c["families"][fname]["rejected_calls"] for c in cells.values()),
            "post_end_calls": sum(c["families"][fname]["post_end_calls"] for c in cells.values()),
            "violations": sum(c["families"][fname]["violations"] for c in cells.values()),
            "max_raw_v_drift": max(c["families"][fname]["max_raw_v_drift"] for c in cells.values()),
            "max_rounded_v_drift": max(c["families"][fname]["max_rounded_v_drift"] for c in cells.values()),
        }

    v14_cells = [v for k, v in cells.items() if k.startswith("v1.4:")]
    v15_cells = [v for k, v in cells.items() if k.startswith("v1.5:")]

    total_trajectories = sum(c["trajectories"] for c in cells.values())
    total_steps = sum(c["total_steps"] for c in cells.values())
    total_violations = sum(c["invariant_violations_count"] for c in cells.values())
    max_raw_v_drift = max(c["max_raw_v_drift"] for c in cells.values())
    max_rounded_v_drift = max(c["max_rounded_v_drift"] for c in cells.values())
    max_vis_v_drift = max(c["max_vis_v_drift"] for c in cells.values())
    max_costs_drift = max(c["max_costs_drift"] for c in cells.values())
    nonzero_raw_v_steps = sum(c["nonzero_raw_v_drift_steps"] for c in cells.values())

    diagnostics["ISS-COST-02_float_vs_decimal_closed_form"] = {
        "total_steps_audited": total_steps,
        "nonzero_raw_self_v_ulp_drift_steps": nonzero_raw_v_steps,
        "max_raw_self_v_drift": max_raw_v_drift,
        "max_raw_costs_drift": max_costs_drift,
        "max_rounded_10dp_v_drift": max_rounded_v_drift,
        "max_visible_v_10dp_drift": max_vis_v_drift,
    }

    wall_s = round(time.perf_counter() - t0, 4)

    return {
        "mode": "quick" if quick else "full",
        "wall_s": wall_s,
        "live_llm_calls": 0,
        "v14_head_sha": (_fast_resolve_head_commit(resolved_repo) if quick else resolve_head_commit(resolved_repo))[:8],
        "v14_tiers_version": rules_v14.TIERS_VERSION,
        "v14_known_v_mode": bool(rules_v14.KNOWN_V_MODE),
        "v14_tier_hash_before": v14_hash_before,
        "v14_tier_hash_after": v14_hash_after,
        "v14_tier_hash_preserved": (
            v14_hash_before == EXPECTED_V14_TIER_HASH and v14_hash_after == EXPECTED_V14_TIER_HASH
        ),
        "v15_available": True,
        "v15_commit_sha": rt15.commit_sha[:8],
        "v15_commit_full": EMBEDDED_V15_COMMIT_FULL if rt15.used_embedded_fallback else rt15.commit_sha,
        "v15_source_mode": rt15.source_mode,
        "shallow_checkout_fallback": shallow_fallback,
        "working_tree_unchanged": (status_before == status_after and rt15.status_unchanged),
        "v14_targets": list(v14_targets),
        "v15_targets": list(v15_targets),
        "family_names": list(FAMILY_NAMES),
        "total_cells": len(cells),
        "total_trajectories": total_trajectories,
        "v14_trajectories": sum(c["trajectories"] for c in v14_cells),
        "v15_trajectories": sum(c["trajectories"] for c in v15_cells),
        "total_steps": total_steps,
        "v14_steps": sum(c["total_steps"] for c in v14_cells),
        "v15_steps": sum(c["total_steps"] for c in v15_cells),
        "total_rejected_calls": sum(c["rejected_calls"] for c in cells.values()),
        "total_post_end_calls": sum(c["post_end_calls"] for c in cells.values()),
        "total_hidden_leak_steps": sum(c["hidden_leak_steps"] for c in cells.values()),
        "total_hidden_leak_masked_steps": sum(c["hidden_leak_masked_steps"] for c in cells.values()),
        "total_v_zero_pre_done_steps": sum(c["v_zero_pre_done_steps"] for c in cells.values()),
        "total_vis_v_zero_pre_done_steps": sum(c["vis_v_zero_pre_done_steps"] for c in cells.values()),
        "saturation_trajectories_total": sum(c["saturation_trajectories_total"] for c in cells.values()),
        "saturation_v_zero_reached": sum(c["saturation_v_zero_reached"] for c in cells.values()),
        "saturation_split_true0_vispos": sum(c["saturation_split_true0_vispos"] for c in cells.values()),
        "nonzero_raw_v_drift_steps": nonzero_raw_v_steps,
        "max_raw_v_drift": max_raw_v_drift,
        "max_rounded_v_drift": max_rounded_v_drift,
        "max_vis_v_drift": max_vis_v_drift,
        "max_costs_drift": max_costs_drift,
        "total_invariant_violations": total_violations,
        "positive_controls": positive_controls,
        "diagnostics": diagnostics,
        "family_totals": family_totals,
        "cells": cells,
    }


def format_human_summary(report: dict[str, Any]) -> str:
    pc = report["positive_controls"]
    lines = [
        f"Cost Ledger & Trajectory Boundary Sweep ({report['mode']} mode, {report['wall_s']:.2f}s, live_llm_calls={report['live_llm_calls']})",
        f"  v1.4 ({report['v14_head_sha']}, hash={report['v14_tier_hash_after']}): {report['v14_trajectories']} trajectories, {report['v14_steps']} steps across {report['v14_targets']}",
        f"  v1.5 ({report['v15_commit_sha']}, source={report['v15_source_mode']}): {report['v15_trajectories']} trajectories, {report['v15_steps']} steps across {report['v15_targets']}",
        f"  Totals: {report['total_trajectories']} boundary trajectories, {report['total_steps']} audited steps, {report['total_rejected_calls']} rejected calls, {report['total_post_end_calls']} post-end calls",
        f"  Saturation & Known-V: {report['saturation_v_zero_reached']}/{report['saturation_trajectories_total']} reached V==0.0 (auto-term=0), {report['total_hidden_leak_masked_steps']} masked unsurfaced-leak steps",
        f"  Float vs Decimal: max_raw_self_v_drift={report['max_raw_v_drift']:.3e} ({report['nonzero_raw_v_drift_steps']} steps), max_rounded_10dp_drift={report['max_rounded_v_drift']:.1f}, max_vis_v_drift={report['max_vis_v_drift']:.1f}",
        f"  Invariant Violations: {report['total_invariant_violations']} | Planted Positive Controls Caught: {pc['controls_caught']}/{pc['controls_total']}",
    ]
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="scripts/integrity_cost_and_trajectory_boundary_sweep.py")
    mode_grp = ap.add_mutually_exclusive_group()
    mode_grp.add_argument("--quick", action="store_true")
    mode_grp.add_argument("--fast", action="store_true")
    mode_grp.add_argument("--full", action="store_true")
    ap.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    ap.add_argument("--v15-ref", default="origin/justSilas-v15")
    ap.add_argument("--v14-targets", default=",".join(V14_TARGETS))
    ap.add_argument("--v15-targets", default=",".join(V15_TARGETS))
    ap.add_argument("--shallow-fallback", action="store_true")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--json-out", type=Path, default=None)
    args = ap.parse_args(argv)

    v14_list = [x.strip() for x in args.v14_targets.split(",") if x.strip()]
    v15_list = [x.strip() for x in args.v15_targets.split(",") if x.strip()]
    quick_mode = bool(args.quick or args.fast)
    report = run_cost_and_trajectory_boundary_sweep(
        quick=quick_mode,
        repo_root=args.repo_root,
        v15_ref=args.v15_ref,
        force_embedded_v15=bool(args.shallow_fallback),
        v14_targets=v14_list,
        v15_targets=v15_list,
    )

    if args.json_out is not None:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(format_human_summary(report))

    ok = (
        report["total_invariant_violations"] == 0
        and report["positive_controls"]["all_caught"] is True
        and report["v14_tier_hash_preserved"] is True
        and report["working_tree_unchanged"] is True
    )
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
