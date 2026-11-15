from __future__ import annotations

import base64
import hashlib
import json
import math
import random
import re
from typing import Any

from canary.env import Env
from canary.mole.dsl import MoleView
from canary.rules import HELDOUT_SEEDS, JUDGE_SEEDS, TIERS, TIERS_VERSION, TRAIN_SEEDS
from canary.solver.policy import SolverPolicy
from canary.world import PROJECTS, TITLE_TPL

COMMITTED_DEV_MIN = 0
COMMITTED_DEV_MAX = 59
PUBLIC_DEV_MIN = 3000
PUBLIC_DEV_MAX = 9999
MAX_SOLVER_STEPS_PER_DAY = 64

ALLOWED_ARENA_MODES = frozenset(
    {
        "duel",
        "duel_gemini",
        "solver",
        "beat_solver",
        "mole",
        "be_the_mole",
        "living",
        "living_office",
        "investigator",
    }
)

MOLE_MODE_NAMES = frozenset({"mole", "be_the_mole"})

PRE_END_STRIP_KEYS = frozenset(
    {
        "mole",
        "true_mole",
        "mole_id",
        "moleId",
        "is_mole",
        "decoy",
        "true_decoy",
        "decoy_id",
        "correct",
        "accused_correct",
        "true_v",
        "true_V",
        "trueV",
        "world_seed",
        "_world",
        "mole_strategy",
        "mole_sprite",
        "culprit_sprite",
        "leaker_employee",
        "secret",
        "world_secret",
    }
)

OPPONENT_EXTRA_STRIP_KEYS = frozenset(
    {
        "accused",
        "score",
        "leaking_sprite_employee",
    }
)

MOLE_PRE_END_STRIP_KEYS = frozenset(
    {
        "is_canary",
        "canary_variants",
        "variants",
        "raw_doc_id",
        "raw_title",
        "true_variant",
        "variant_recipients",
        "leaked_canaries",
        "caught_by_canary",
        "posterior",
        "mole_posterior",
        "posteriors",
        "posterior_curve",
        "top_suspect",
        "top_suspects",
        "top_posterior",
        "mole_rank",
    }
)

ACCUSE_REDACT_FIELDS = frozenset(
    {
        "summary",
        "result",
        "rationale",
        "thought",
        "reasoning",
        "note",
        "commentary",
        "text",
        "message",
        "detail",
        "error",
    }
)

EMP_ID_TOKEN_RE = re.compile(r"\be\d{2,3}\b")
EMP_ID_EXACT_RE = re.compile(r"^e\d{2,3}$")
CANARY_DOC_ID_RE = re.compile(r"^c(?:\d|an)", re.IGNORECASE)

_UNSET = object()


def _is_int_not_bool(val: Any) -> bool:
    return isinstance(val, int) and not isinstance(val, bool)


def _is_finite_number(val: Any) -> bool:
    return isinstance(val, (int, float)) and not isinstance(val, bool) and math.isfinite(float(val))


def check_arena_seed(mode: Any, seed: Any = _UNSET) -> int:
    if seed is _UNSET:
        raw_mode: Any = "duel"
        raw_seed: Any = mode
    else:
        raw_mode = mode
        raw_seed = seed

    if not isinstance(raw_mode, str) or raw_mode not in ALLOWED_ARENA_MODES:
        raise ValueError(f"unsupported arena mode: {raw_mode!r}")

    if isinstance(raw_seed, bool) or raw_seed is None:
        raise ValueError("seed must be an integer, not bool or None")
    if isinstance(raw_seed, float):
        raise ValueError("seed must be an integer, not float")

    if isinstance(raw_seed, int):
        parsed = int(raw_seed)
    elif isinstance(raw_seed, str):
        if not raw_seed or raw_seed != raw_seed.strip():
            raise ValueError("seed string must not be empty or whitespace-padded")
        try:
            parsed = int(raw_seed, 10)
        except ValueError:
            raise ValueError(f"seed must be a base-10 integer: {raw_seed!r}") from None
        if str(parsed) != raw_seed:
            raise ValueError(f"seed string must be canonical integer digits: {raw_seed!r}")
    else:
        raise ValueError(f"seed must be an integer, got {type(raw_seed).__name__}")

    if parsed < 0:
        raise ValueError(f"negative seed refused: {parsed}")
    if parsed in JUDGE_SEEDS or parsed in HELDOUT_SEEDS or parsed in TRAIN_SEEDS:
        raise ValueError(f"benchmark or training seed refused: {parsed}")
    in_committed_dev = COMMITTED_DEV_MIN <= parsed <= COMMITTED_DEV_MAX
    in_public_dev = PUBLIC_DEV_MIN <= parsed <= PUBLIC_DEV_MAX
    if not (in_committed_dev or in_public_dev):
        raise ValueError(
            f"seed {parsed} outside allowed arena dev ranges "
            f"{COMMITTED_DEV_MIN}..{COMMITTED_DEV_MAX} and {PUBLIC_DEV_MIN}..{PUBLIC_DEV_MAX}"
        )
    return parsed


def check_seed(seed: Any, mode: str = "duel") -> int:
    return check_arena_seed(mode, seed)


def _check_tier(tier: Any) -> str:
    if not isinstance(tier, str) or tier not in TIERS:
        raise ValueError(f"tier must be one of {tuple(TIERS)}")
    return tier


def _strip_keys_recursive(obj: Any, forbidden: frozenset[str]) -> Any:
    if isinstance(obj, list):
        return [_strip_keys_recursive(x, forbidden) for x in obj]
    if isinstance(obj, tuple):
        return [_strip_keys_recursive(x, forbidden) for x in obj]
    if isinstance(obj, dict):
        out: dict[str, Any] = {}
        for k, v in obj.items():
            ks = str(k)
            if ks in forbidden or "world_secret" in ks.lower():
                continue
            out[ks] = _strip_keys_recursive(v, forbidden)
        return out
    return obj


def _redact_emp_ids_recursive(obj: Any) -> Any:
    if isinstance(obj, str):
        return EMP_ID_TOKEN_RE.sub("[SEALED]", obj)
    if isinstance(obj, list):
        return [_redact_emp_ids_recursive(x) for x in obj]
    if isinstance(obj, tuple):
        return [_redact_emp_ids_recursive(x) for x in obj]
    if isinstance(obj, dict):
        return {str(k): _redact_emp_ids_recursive(v) for k, v in obj.items()}
    return obj


def _doc_sensitivity_label(recipient_count: int, n_employees: int, low_threshold: int) -> str:
    if recipient_count <= low_threshold:
        return "restricted"
    if recipient_count <= max(1, int(n_employees * 0.5)):
        return "confidential"
    return "internal"


def create_investigator_session(tier: str, seed: Any, mode: str = "duel") -> Any:
    checked_tier = _check_tier(tier)
    checked_seed = check_arena_seed(mode, seed)
    runtime = Env(tier=checked_tier, seed=checked_seed)
    recorded_actions: list[list[Any]] = []
    strip_set = PRE_END_STRIP_KEYS | frozenset({"leaking_sprite_employee"})

    def _public_employees() -> list[dict[str, Any]]:
        staff: list[dict[str, Any]] = []
        for emp in runtime._world.employees:
            item: dict[str, Any] = {
                "id": emp.id,
                "name": emp.name,
                "dept": emp.dept,
                "role": emp.role,
                "restricted": emp.id in runtime._restricted,
            }
            if emp.clearance is not None:
                item["clearance"] = emp.clearance
            staff.append(item)
        return staff

    def _surfaced_feed() -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for f in runtime._feed:
            if f["surfaced_day"] <= runtime.day:
                entry: dict[str, Any] = {
                    "surfaced_day": int(f["surfaced_day"]),
                    "doc_id": str(f["doc_id"]),
                    "title": str(f["title"]),
                }
                if "variant" in f:
                    entry["variant"] = f["variant"]
                items.append(entry)
        return items

    class InvestigatorSession:
        __slots__ = ()

        @property
        def tier(self) -> str:
            return checked_tier

        @property
        def seed(self) -> int:
            return checked_seed

        @property
        def mode(self) -> str:
            return mode

        @property
        def tiers_version(self) -> str:
            return TIERS_VERSION

        @property
        def done(self) -> bool:
            return bool(runtime.done)

        @property
        def day(self) -> int:
            return int(runtime.day)

        @property
        def n_days(self) -> int:
            return int(runtime.p.n_days)

        @property
        def history(self) -> list[dict[str, Any]]:
            out: list[dict[str, Any]] = []
            for st in runtime.history:
                out.append(
                    {
                        "t": int(st.t),
                        "day": int(st.day),
                        "tool": str(st.tool),
                        "args": _strip_keys_recursive(dict(st.args), strip_set),
                        "result": _strip_keys_recursive(dict(st.result), strip_set),
                    }
                )
            return out

        @property
        def actions(self) -> list[list[Any]]:
            return [[a[0], dict(a[1])] for a in recorded_actions]

        def spec_json(self) -> str:
            return json.dumps(
                {
                    "tier": checked_tier,
                    "seed": checked_seed,
                    "mode": mode,
                    "tiers_version": TIERS_VERSION,
                    "tools": runtime.tools_spec(),
                    "instruction": runtime.instruction(),
                }
            )

        def call_json(self, tool: str, args_json: str | dict[str, Any] = "{}") -> str:
            if args_json is None or args_json == "":
                parsed_args: Any = {}
            elif isinstance(args_json, str):
                try:
                    parsed_args = json.loads(args_json)
                except ValueError:
                    return json.dumps(
                        {
                            "ok": False,
                            "data": {},
                            "error": "arguments are not valid JSON",
                            "done": bool(runtime.done),
                            "day": int(runtime.day),
                            "known_v": runtime.visible_V(),
                        }
                    )
            elif isinstance(args_json, dict):
                parsed_args = dict(args_json)
            else:
                parsed_args = None

            if not isinstance(parsed_args, dict):
                return json.dumps(
                    {
                        "ok": False,
                        "data": {},
                        "error": "arguments must be a JSON object",
                        "done": bool(runtime.done),
                        "day": int(runtime.day),
                        "known_v": runtime.visible_V(),
                    }
                )

            stepper = getattr(runtime, "step_tool", None) or runtime.call
            res = stepper(tool, parsed_args)
            recorded_actions.append([tool, dict(parsed_args)])
            kv = runtime.visible_V()
            clean_data = _strip_keys_recursive(dict(res.data) if isinstance(res.data, dict) else {}, strip_set)
            if isinstance(clean_data, dict) and "V" in clean_data:
                clean_data["V"] = kv
            payload = {
                "ok": bool(res.ok),
                "data": clean_data,
                "error": res.error,
                "done": bool(runtime.done),
                "day": int(runtime.day),
                "known_v": kv,
            }
            return json.dumps(payload, default=str)

        def hud_json(self) -> str:
            is_done = bool(runtime.done)
            kv = runtime.visible_V()
            surfaced = _surfaced_feed()
            hud: dict[str, Any] = {
                "tier": checked_tier,
                "seed": checked_seed,
                "mode": mode,
                "tiers_version": TIERS_VERSION,
                "done": is_done,
                "day": int(runtime.day),
                "n_days": int(runtime.p.n_days),
                "known_v": kv,
                "V": kv,
                "actions_used_today": int(runtime._actions_today),
                "actions_left_today": int(runtime.p.actions_per_day - runtime._actions_today),
                "actions_per_day": int(runtime.p.actions_per_day),
                "tool_calls": len(runtime.history),
                "tool_calls_left": int(runtime.p.tool_call_cap - len(runtime.history)),
                "tool_call_cap": int(runtime.p.tool_call_cap),
                "restricted": sorted(runtime._restricted),
                "canaries_planted": list(runtime._canary_ids),
                "surfaced_leaks_count": len(surfaced),
                "leaking_sprite_employee": runtime._world.mole if is_done else None,
            }
            return json.dumps(hud)

        def office_frame_json(self) -> str:
            is_done = bool(runtime.done)
            kv = runtime.visible_V()
            surfaced = _surfaced_feed()
            frame: dict[str, Any] = {
                "tier": checked_tier,
                "seed": checked_seed,
                "mode": mode,
                "tiers_version": TIERS_VERSION,
                "done": is_done,
                "day": int(runtime.day),
                "n_days": int(runtime.p.n_days),
                "known_v": kv,
                "V": kv,
                "company": runtime._world.company,
                "employees": _public_employees(),
                "restricted": sorted(runtime._restricted),
                "canaries_planted": list(runtime._canary_ids),
                "surfaced_leaks": surfaced,
                "leaking_sprite_employee": runtime._world.mole if is_done else None,
            }
            return json.dumps(frame)

        def reveal_json(self) -> str:
            if not runtime.done:
                raise PermissionError("episode is not over yet; reveal is locked until done is True")
            verdict = runtime.verdict()
            mole_emp_id = runtime._world.mole
            tool_count = len(runtime.history)
            accused_id = verdict["accused"]
            is_correct = bool(verdict["correct"])
            ep_score = verdict["score"]
            end_rsn = verdict["end_reason"]
            f_day = int(verdict["final_day"])
            return json.dumps(
                {
                    "done": True,
                    "tier": checked_tier,
                    "seed": checked_seed,
                    "mode": mode,
                    "tiers_version": TIERS_VERSION,
                    "mole": mole_emp_id,
                    "decoy": runtime._world.decoy,
                    "accused": accused_id,
                    "correct": is_correct,
                    "score": ep_score,
                    "known_v": runtime.visible_V(),
                    "true_v": verdict["V"],
                    "final_day": f_day,
                    "tool_calls": tool_count,
                    "end_reason": end_rsn,
                    "leaking_sprite_employee": mole_emp_id,
                    "you": {
                        "score": ep_score,
                        "end_reason": end_rsn,
                        "accused": accused_id,
                        "correct": is_correct,
                        "final_day": f_day,
                        "tool_calls": tool_count,
                    },
                }
            )

        def actions_json(self) -> str:
            return json.dumps(
                {
                    "tier": checked_tier,
                    "seed": checked_seed,
                    "mode": mode,
                    "tiers_version": TIERS_VERSION,
                    "actions": recorded_actions,
                }
            )

    return InvestigatorSession()


class _ClosureHumanMoleStrategy:
    name = "human_mole"

    def __init__(self) -> None:
        self.pending_action: dict[str, str | None] = {"leak": None, "frame": None}
        self.last_applied: dict[str, Any] | None = None

    def decide(self, view: MoleView, rng: Any = None) -> dict[str, str | None]:
        held_ids = {d.doc_id for d in view.docs}
        leak = self.pending_action.get("leak")
        if leak not in held_ids:
            leak = None
        frame = self.pending_action.get("frame")
        if frame == "most_restricted_peer":
            frame = view.restricted_peers[0] if view.restricted_peers else None
        elif frame == "random_peer":
            if view.peers:
                frame = rng.choice(view.peers) if rng is not None else view.peers[0]
            else:
                frame = None
        elif frame not in view.peers:
            frame = None
        out = {"leak": leak, "frame": frame}
        self.last_applied = {
            "day": view.day,
            "leak": leak,
            "frame": frame,
            "can_leak_gate": bool(view.can_leak),
        }
        self.pending_action = {"leak": None, "frame": None}
        return out


def _normalize_mole_args(tier_or_seed: Any, seed_or_tier: Any) -> tuple[str, int]:
    if not isinstance(tier_or_seed, bool) and (
        isinstance(tier_or_seed, int)
        or (isinstance(tier_or_seed, str) and tier_or_seed.strip().lstrip("-").isdigit())
    ):
        if isinstance(seed_or_tier, str) and seed_or_tier in TIERS:
            return _check_tier(seed_or_tier), check_arena_seed("mole", tier_or_seed)
    return _check_tier(tier_or_seed), check_arena_seed("mole", seed_or_tier)


def create_mole_session(tier: str, seed: Any) -> Any:
    checked_tier, checked_seed = _normalize_mole_args(tier, seed)
    strategy = _ClosureHumanMoleStrategy()
    runtime = Env(tier=checked_tier, seed=checked_seed, mole_strategy=strategy)
    solver = SolverPolicy(checked_tier)
    solver.reset(runtime.tools_spec(), runtime.instruction())

    pending_solver_call: list[tuple[str, dict[str, Any]] | None] = [None]
    masked_days: set[int] = set()
    raw_to_mask: dict[str, str] = {}
    mask_to_raw: dict[str, str] = {}
    alias_to_raw: dict[str, str] = {}
    raw_to_title: dict[str, str] = {}
    day_snapshots: list[dict[str, Any]] = []
    leak_records: list[dict[str, Any]] = []
    mole_history: list[dict[str, Any]] = []

    def _cover_title(doc: dict[str, Any]) -> str:
        raw_title = str(doc.get("title", ""))
        if not doc.get("is_canary") and not raw_title.startswith("Board memo draft"):
            return raw_title
        emp_dept = {e.id: e.dept for e in runtime._world.employees}
        dept_counts: dict[str, int] = {}
        for eid in doc.get("recipients", []):
            dept = emp_dept.get(eid)
            if dept:
                dept_counts[dept] = dept_counts.get(dept, 0) + 1
        if dept_counts:
            primary_dept = min(dept_counts, key=lambda k: (-dept_counts[k], k))
        else:
            primary_dept = runtime._world.depts[0]
        digest = hashlib.sha256(f"{checked_seed}:{checked_tier}:cover:{doc['doc_id']}".encode()).digest()
        rng = random.Random(int.from_bytes(digest[:8], "big"))
        tpl = rng.choice(TITLE_TPL)
        return tpl.format(
            q=rng.choice(["Q1", "Q2", "Q3", "Q4"]),
            d=primary_dept,
            p=rng.choice(PROJECTS),
        )

    def _sync_day_masks(target_day: int) -> None:
        for day_num in range(1, target_day + 1):
            if day_num in masked_days:
                continue
            day_docs = [x for x in runtime.docs if x["day"] == day_num]
            if not day_docs:
                continue
            ordered = sorted(
                day_docs,
                key=lambda x: hashlib.sha256(
                    f"{checked_seed}:{checked_tier}:desk:{day_num}:{x['doc_id']}".encode()
                ).hexdigest(),
            )
            for idx, doc in enumerate(ordered):
                raw_id = str(doc["doc_id"])
                seq_idx = len(raw_to_mask)
                mask_id = f"doc_{seq_idx}"
                day_alias = f"doc-d{day_num}-{idx + 1}"
                raw_to_mask[raw_id] = mask_id
                mask_to_raw[mask_id] = raw_id
                alias_to_raw[day_alias] = raw_id
                raw_to_title[raw_id] = _cover_title(doc)
            masked_days.add(day_num)

    def _record_solver_snapshots() -> None:
        while len(day_snapshots) < len(solver.trace):
            tr = solver.trace[len(day_snapshots)]
            day_snapshots.append(
                {
                    "day": int(tr["day"]),
                    "post": dict(tr["post"]),
                    "visible_v": runtime.visible_V(),
                    "true_v": round(runtime.V, 10),
                }
            )

    def _advance_solver_pre_mole() -> dict[str, Any]:
        start_idx = len(runtime.history)
        for _ in range(MAX_SOLVER_STEPS_PER_DAY):
            if runtime.done:
                pending_solver_call[0] = None
                break
            tool, args = solver.act(list(runtime.history))
            _record_solver_snapshots()
            if tool == "advance_day":
                pending_solver_call[0] = (tool, dict(args))
                break
            runtime.call(tool, args)
        _record_solver_snapshots()
        _sync_day_masks(runtime.day)
        m_id = runtime._world.mole
        cur_day = runtime.day
        new_steps = runtime.history[start_idx:]
        interviewed = any(
            st.day == cur_day
            and st.tool == "interview"
            and st.args.get("employee") == m_id
            and st.result.get("ok")
            for st in new_steps
        )
        restricted_now = any(
            st.day == cur_day
            and st.tool == "restrict_access"
            and st.args.get("employee") == m_id
            and st.result.get("ok")
            for st in new_steps
        )
        solver_accused = any(st.tool == "accuse" and st.result.get("ok") for st in new_steps)
        return {
            "day": int(cur_day),
            "total_staff_restricted": len(runtime._restricted),
            "restricted_ids": sorted(runtime._restricted),
            "self_interviewed": interviewed,
            "self_restricted": restricted_now or (m_id in runtime._restricted),
            "episode_closed": solver_accused or bool(runtime.done),
        }

    def _leakable_raw_docs() -> list[dict[str, Any]]:
        d = runtime.day
        lo = d - runtime.p.leak_window_days + 1
        m_id = runtime._world.mole
        raw_docs = [
            runtime._doc_by_id[doc_id]
            for doc_id in runtime._held[m_id]
            if doc_id not in runtime._leaked and lo <= runtime._doc_by_id[doc_id]["day"] <= d
        ]
        return sorted(
            raw_docs,
            key=lambda x: (x["day"], raw_to_mask.get(x["doc_id"], x["doc_id"])),
        )

    def _compute_scores() -> tuple[float, float]:
        solver_score = float(runtime.score())
        accused = runtime._accused
        m_id = runtime._world.mole
        tv = round(runtime.V, 10)
        if accused == m_id:
            mole_score = round(-solver_score, 10)
        elif accused is not None:
            mole_score = 1.0
        elif not leak_records:
            mole_score = 0.0
        else:
            mole_score = round(min(1.0, max(0.0, 1.0 - tv)), 10)
        return mole_score, solver_score

    def _outcome_summary() -> dict[str, Any]:
        m_id = runtime._world.mole
        accused = runtime._accused
        caught = bool(accused == m_id)
        survived = not caught
        mole_score, solver_score = _compute_scores()
        return {
            "done": True,
            "survived": survived,
            "caught": caught,
            "accused": accused,
            "accused_id": accused,
            "end_reason": runtime._end_reason,
            "final_day": int(runtime.day),
            "mole_score": mole_score,
            "solver_score": solver_score,
            "leaks_count": len(leak_records),
        }

    def _build_day_view() -> dict[str, Any]:
        p = runtime.p
        w = runtime._world
        d = runtime.day
        _sync_day_masks(d)
        m_id = w.mole
        mole_emp = next(e for e in w.employees if e.id == m_id)
        leakable_raw = _leakable_raw_docs()
        leakable_docs: list[dict[str, Any]] = []
        for doc in leakable_raw:
            rc = len(doc["recipients"])
            age = int(d - doc["day"])
            leakable_docs.append(
                {
                    "doc_id": raw_to_mask[doc["doc_id"]],
                    "title": raw_to_title[doc["doc_id"]],
                    "day": int(doc["day"]),
                    "days_old": age,
                    "age_days": age,
                    "recipient_count": rc,
                    "sensitivity": _doc_sensitivity_label(rc, p.n_employees, p.low_recipient_threshold),
                    "recipients": list(doc["recipients"]),
                }
            )
        docs_alias = [dict(item, recipients=list(item["recipients"])) for item in leakable_docs]
        interview_topics_today = [
            str(st.args["topic"])
            for st in runtime.history
            if st.day == d
            and st.tool == "interview"
            and st.args.get("employee") == m_id
            and st.result.get("ok")
        ]
        restricted_today = any(
            st.day == d
            and st.tool == "restrict_access"
            and st.args.get("employee") == m_id
            and st.result.get("ok")
            for st in runtime.history
        )
        surfaced = [
            {
                "surfaced_day": int(f["surfaced_day"]),
                "doc_id": raw_to_mask.get(f["doc_id"], f["doc_id"]),
                "title": raw_to_title.get(f["doc_id"], f["title"]),
            }
            for f in runtime._feed
            if f["surfaced_day"] <= d
        ]
        kv = runtime.visible_V()
        peers = [e.id for e in w.employees if e.id != m_id]
        peer_roster = [
            {
                "id": e.id,
                "name": e.name,
                "dept": e.dept,
                "role": e.role,
                "restricted": e.id in runtime._restricted,
            }
            for e in w.employees
            if e.id != m_id
        ]
        i_am_restricted = m_id in runtime._restricted
        total_restricted = len(runtime._restricted)
        n_restricted_colleagues = sum(1 for eid in runtime._restricted if eid != m_id)
        view: dict[str, Any] = {
            "seed": checked_seed,
            "tier": checked_tier,
            "mode": "be_the_mole",
            "tiers_version": TIERS_VERSION,
            "company": w.company,
            "day": int(d),
            "n_days": int(p.n_days),
            "leak_window_days": int(p.leak_window_days),
            "done": bool(runtime.done),
            "end_reason": runtime._end_reason if runtime.done else None,
            "self_employee": mole_emp.id,
            "employee": {
                "id": mole_emp.id,
                "name": mole_emp.name,
                "dept": mole_emp.dept,
                "role": mole_emp.role,
                "clearance": mole_emp.clearance,
            },
            "n_staff": len(w.employees),
            "peers": peers,
            "peer_roster": peer_roster,
            "leakable_docs": leakable_docs,
            "docs": docs_alias,
            "can_leak": bool(leakable_docs) and not runtime.done,
            "days_since_last_leak": int((d - runtime._last_leak_day) if runtime._last_leak_day else d),
            "recent_low_recipient_docs": sum(
                1 for doc in leakable_raw if len(doc["recipients"]) <= p.low_recipient_threshold
            ),
            "known_v": kv,
            "visible_v": kv,
            "V": kv,
            "total_staff_restricted": total_restricted,
            "n_restricted_colleagues": n_restricted_colleagues,
            "restricted_ids": sorted(runtime._restricted),
            "i_am_restricted": i_am_restricted,
            "restricted_today": restricted_today,
            "interviewed_today": bool(interview_topics_today),
            "interview_topics_today": interview_topics_today,
            "total_surfaced_leaks": len(surfaced),
            "surfaced_leaks": surfaced,
        }
        return view

    def _build_debrief() -> dict[str, Any]:
        w = runtime._world
        m_id = w.mole
        mole_emp = next(e for e in w.employees if e.id == m_id)
        final_day = int(runtime.day)
        accused_id = runtime._accused
        caught = bool(accused_id == m_id)
        survived = not caught
        mole_score, solver_score = _compute_scores()
        tv = round(runtime.V, 10)
        kv = runtime.visible_V()
        leak_damage_dealt = round(len(leak_records) * runtime.p.leak_damage, 10)

        posterior_curve: list[dict[str, Any]] = []
        for snap in day_snapshots:
            post = snap["post"]
            mole_p = float(post.get(m_id, 0.0))
            if post:
                ranked = sorted(post.items(), key=lambda item: (-item[1], item[0]))
                top_suspect, top_p = ranked[0]
                mole_rank = next(
                    (idx for idx, (eid, _) in enumerate(ranked, start=1) if eid == m_id),
                    len(ranked),
                )
            else:
                top_suspect, top_p, mole_rank = None, 0.0, 1
            posterior_curve.append(
                {
                    "day": int(snap["day"]),
                    "posterior": round(mole_p, 6),
                    "mole_posterior": round(mole_p, 6),
                    "top_suspect": top_suspect,
                    "top_posterior": round(float(top_p), 6),
                    "mole_rank": mole_rank,
                    "visible_v": snap["visible_v"],
                    "true_v": snap["true_v"],
                }
            )

        leaks_made = [
            {
                "day": rec["leaked_day"],
                "doc_id": rec["doc_id"],
                "raw_doc_id": rec["raw_doc_id"],
                "title": rec["title"],
                "raw_title": rec["raw_title"],
                "surfaced_day": rec["surfaced_day"],
                "surfaced": bool(rec["surfaced_day"] <= final_day),
                "is_canary": rec["is_canary"],
                "canary_variants": rec["canary_variants"],
                "variant": rec["variant"],
            }
            for rec in leak_records
        ]

        leaked_canaries = [
            {
                "doc_id": rec["doc_id"],
                "raw_doc_id": rec["raw_doc_id"],
                "title": rec["title"],
                "raw_title": rec["raw_title"],
                "is_canary": True,
                "canary_variants": rec["canary_variants"],
                "variant": rec["variant"],
                "true_variant": rec["true_variant"],
                "variant_recipients": list(rec["variant_recipients"]),
                "leaked_day": rec["leaked_day"],
                "surfaced_day": rec["surfaced_day"],
                "surfaced": bool(rec["surfaced_day"] <= final_day),
            }
            for rec in leak_records
            if rec["is_canary"]
        ]

        days_survived = final_day if survived else max(0, final_day - 1)
        return {
            "ok": True,
            "done": True,
            "seed": checked_seed,
            "tier": checked_tier,
            "mode": "be_the_mole",
            "tiers_version": TIERS_VERSION,
            "company": w.company,
            "mole": mole_emp.id,
            "mole_id": mole_emp.id,
            "mole_name": mole_emp.name,
            "mole_dept": mole_emp.dept,
            "mole_role": mole_emp.role,
            "decoy": w.decoy,
            "survived": survived,
            "caught": caught,
            "accused": accused_id,
            "accused_id": accused_id,
            "correct": caught,
            "end_reason": runtime._end_reason,
            "final_day": final_day,
            "days_survived": days_survived,
            "score": mole_score,
            "mole_score": mole_score,
            "solver_score": solver_score,
            "known_v": kv,
            "visible_v": kv,
            "true_v": tv,
            "leak_damage_dealt": leak_damage_dealt,
            "leaks_count": len(leak_records),
            "leaks_made": leaks_made,
            "leaked_canaries": leaked_canaries,
            "posterior_curve": posterior_curve,
            "leaking_sprite_employee": mole_emp.id,
            "history": [dict(x) for x in mole_history],
        }

    _advance_solver_pre_mole()

    class MoleArenaSession:
        __slots__ = ()

        @property
        def tier(self) -> str:
            return checked_tier

        @property
        def seed(self) -> int:
            return checked_seed

        @property
        def mode(self) -> str:
            return "be_the_mole"

        @property
        def tiers_version(self) -> str:
            return TIERS_VERSION

        @property
        def day(self) -> int:
            return int(runtime.day)

        @property
        def n_days(self) -> int:
            return int(runtime.p.n_days)

        @property
        def done(self) -> bool:
            return bool(runtime.done)

        def get_mole_day_view(self) -> dict[str, Any]:
            return _build_day_view()

        def view_json(self) -> str:
            return json.dumps(_build_day_view())

        def day_view_json(self) -> str:
            return json.dumps(_build_day_view())

        def hud_json(self) -> str:
            view = _build_day_view()
            return json.dumps(
                {
                    "tier": checked_tier,
                    "seed": checked_seed,
                    "mode": "be_the_mole",
                    "tiers_version": TIERS_VERSION,
                    "done": bool(runtime.done),
                    "day": view["day"],
                    "n_days": view["n_days"],
                    "known_v": view["known_v"],
                    "V": view["known_v"],
                    "restricted_ids": view["restricted_ids"],
                    "i_am_restricted": view["i_am_restricted"],
                    "interviewed_today": view["interviewed_today"],
                    "total_surfaced_leaks": view["total_surfaced_leaks"],
                    "leaking_sprite_employee": runtime._world.mole if runtime.done else None,
                }
            )

        def step_mole_day(self, action: dict[str, Any] | str | None = None) -> dict[str, Any]:
            if runtime.done:
                return {
                    "ok": False,
                    "error": "episode over",
                    "done": True,
                    "day_view": _build_day_view(),
                    "outcome": _outcome_summary(),
                }
            if action is None:
                parsed: dict[str, Any] = {"type": "hold"}
            elif isinstance(action, str):
                if not action.strip():
                    parsed = {"type": "hold"}
                else:
                    try:
                        loaded = json.loads(action)
                    except ValueError:
                        return {
                            "ok": False,
                            "error": "action is not valid JSON",
                            "done": bool(runtime.done),
                            "day_view": _build_day_view(),
                            "outcome": None,
                        }
                    if not isinstance(loaded, dict):
                        return {
                            "ok": False,
                            "error": "action must be a JSON object",
                            "done": bool(runtime.done),
                            "day_view": _build_day_view(),
                            "outcome": None,
                        }
                    parsed = loaded
            elif isinstance(action, dict):
                parsed = dict(action)
            else:
                return {
                    "ok": False,
                    "error": "action must be a dict or JSON object",
                    "done": bool(runtime.done),
                    "day_view": _build_day_view(),
                    "outcome": None,
                }

            raw_type = str(parsed.get("type") or parsed.get("action") or "").strip().lower()
            if not raw_type:
                raw_type = "leak" if parsed.get("doc_id") or parsed.get("leak") else "hold"
            if raw_type == "pass":
                raw_type = "hold"
            if raw_type not in ("leak", "hold"):
                return {
                    "ok": False,
                    "error": "action type must be 'leak' or 'hold'",
                    "done": bool(runtime.done),
                    "day_view": _build_day_view(),
                    "outcome": None,
                }

            d = runtime.day
            _sync_day_masks(d)
            leakable_raw = _leakable_raw_docs()
            leakable_raw_ids = {doc["doc_id"] for doc in leakable_raw}

            chosen_raw_doc: str | None = None
            chosen_mask_doc: str | None = None
            if raw_type == "leak":
                doc_arg = parsed.get("doc_id", parsed.get("leak"))
                if not isinstance(doc_arg, str) or not doc_arg.strip():
                    return {
                        "ok": False,
                        "error": "doc_id is required when type is 'leak'",
                        "done": bool(runtime.done),
                        "day_view": _build_day_view(),
                        "outcome": None,
                    }
                clean_doc = doc_arg.strip()
                if CANARY_DOC_ID_RE.match(clean_doc):
                    return {
                        "ok": False,
                        "error": "doc_id must be a masked desk document id",
                        "done": bool(runtime.done),
                        "day_view": _build_day_view(),
                        "outcome": None,
                    }
                raw_candidate = mask_to_raw.get(clean_doc) or alias_to_raw.get(clean_doc)
                if raw_candidate is None or raw_candidate not in leakable_raw_ids:
                    return {
                        "ok": False,
                        "error": "doc_id is not a leakable document held by the mole",
                        "done": bool(runtime.done),
                        "day_view": _build_day_view(),
                        "outcome": None,
                    }
                chosen_raw_doc = raw_candidate
                chosen_mask_doc = raw_to_mask[raw_candidate]

            m_id = runtime._world.mole
            peers_set = {e.id for e in runtime._world.employees if e.id != m_id}
            raw_frame = parsed.get("frame_peer", parsed.get("frame"))
            chosen_frame: str | None = None
            if raw_frame not in (None, "", "none"):
                if not isinstance(raw_frame, str):
                    return {
                        "ok": False,
                        "error": "frame_peer must be a valid peer employee id",
                        "done": bool(runtime.done),
                        "day_view": _build_day_view(),
                        "outcome": None,
                    }
                frame_clean = raw_frame.strip()
                if frame_clean in peers_set or frame_clean in ("random_peer", "most_restricted_peer"):
                    chosen_frame = frame_clean
                else:
                    return {
                        "ok": False,
                        "error": "frame_peer must be a valid peer employee id",
                        "done": bool(runtime.done),
                        "day_view": _build_day_view(),
                        "outcome": None,
                    }

            strategy.pending_action = {"leak": chosen_raw_doc, "frame": chosen_frame}
            feed_before = len(runtime._feed)
            adv_tool, adv_args = pending_solver_call[0] or ("advance_day", {})
            pending_solver_call[0] = None
            runtime.call(adv_tool, adv_args)

            applied = strategy.last_applied or {"leak": None, "frame": None}
            actual_raw_leak = applied.get("leak")
            actual_frame = applied.get("frame")
            if len(runtime._feed) > feed_before:
                feed_item = runtime._feed[-1]
                leaked_doc = runtime._doc_by_id[feed_item["doc_id"]]
                obs_variant = feed_item.get("variant")
                variants_map = (
                    {k: list(v) for k, v in leaked_doc.get("variants", {}).items()}
                    if leaked_doc.get("is_canary")
                    else {}
                )
                true_var = (
                    next((k for k, es in variants_map.items() if m_id in es), None)
                    if leaked_doc.get("is_canary")
                    else None
                )
                var_recs = list(variants_map.get(obs_variant, [])) if obs_variant is not None else []
                leak_records.append(
                    {
                        "leaked_day": int(d),
                        "surfaced_day": int(feed_item["surfaced_day"]),
                        "doc_id": raw_to_mask.get(leaked_doc["doc_id"], leaked_doc["doc_id"]),
                        "raw_doc_id": leaked_doc["doc_id"],
                        "title": raw_to_title.get(leaked_doc["doc_id"], leaked_doc["title"]),
                        "raw_title": leaked_doc["title"],
                        "is_canary": bool(leaked_doc.get("is_canary")),
                        "canary_variants": variants_map,
                        "variant": obs_variant,
                        "true_variant": true_var,
                        "variant_recipients": var_recs,
                    }
                )

            applied_record = {
                "day": int(d),
                "type": "leak" if actual_raw_leak is not None else "hold",
                "doc_id": raw_to_mask.get(actual_raw_leak, chosen_mask_doc) if actual_raw_leak else None,
                "frame_peer": actual_frame,
            }
            mole_history.append(dict(applied_record))

            if not runtime.done:
                solver_events = _advance_solver_pre_mole()
            else:
                _record_solver_snapshots()
                solver_events = {
                    "day": int(runtime.day),
                    "total_staff_restricted": len(runtime._restricted),
                    "restricted_ids": sorted(runtime._restricted),
                    "self_interviewed": False,
                    "self_restricted": m_id in runtime._restricted,
                    "episode_closed": True,
                }

            return {
                "ok": True,
                "applied_action": applied_record,
                "solver_events": solver_events,
                "done": bool(runtime.done),
                "known_v": runtime.visible_V(),
                "day_view": _build_day_view(),
                "outcome": _outcome_summary() if runtime.done else None,
            }

        def step_json(self, action: dict[str, Any] | str | None = None) -> str:
            return json.dumps(self.step_mole_day(action))

        def get_mole_debrief(self) -> dict[str, Any]:
            if not runtime.done:
                return {
                    "ok": False,
                    "done": False,
                    "error": "the episode is not over yet",
                }
            return _build_debrief()

        def debrief_json(self) -> str:
            return json.dumps(self.get_mole_debrief())

        def reveal_json(self) -> str:
            if not runtime.done:
                raise PermissionError("episode is not over yet; mole debrief is locked until done is True")
            return json.dumps(_build_debrief())

    return MoleArenaSession()


def sanitize_opponent_step_for_hud(
    step: dict[str, Any],
    human_day: int | None,
    human_done: bool,
) -> dict[str, Any] | None:
    if not isinstance(step, dict):
        return None
    step_day_raw = step.get("day", 1)
    step_day = int(step_day_raw) if _is_int_not_bool(step_day_raw) else 1
    if human_day is not None:
        if not _is_int_not_bool(human_day) or step_day > int(human_day):
            return None

    unlocked = human_done is True
    if unlocked:
        return json.loads(json.dumps(step, default=str))

    forbidden = PRE_END_STRIP_KEYS | OPPONENT_EXTRA_STRIP_KEYS
    cleaned: dict[str, Any] = _strip_keys_recursive(step, forbidden)
    if "known_v" in cleaned and _is_finite_number(cleaned["known_v"]) and "V" in cleaned:
        cleaned["V"] = float(cleaned["known_v"])

    tool_name = str(cleaned.get("tool") or "")
    if tool_name == "accuse":
        raw_args = cleaned.get("args")
        if isinstance(raw_args, dict):
            redacted_args = _redact_emp_ids_recursive(raw_args)
            redacted_args["employee"] = "[SEALED]"
            cleaned["args"] = redacted_args
        else:
            cleaned["args"] = {"employee": "[SEALED]"}

        if "arguments" in cleaned and isinstance(cleaned["arguments"], dict):
            redacted_arguments = _redact_emp_ids_recursive(cleaned["arguments"])
            redacted_arguments["employee"] = "[SEALED]"
            cleaned["arguments"] = redacted_arguments

        for field_name in ACCUSE_REDACT_FIELDS:
            if field_name in cleaned:
                cleaned[field_name] = _redact_emp_ids_recursive(cleaned[field_name])

        cleaned["sealed"] = True

    return cleaned


def sanitize_opponent_steps(
    steps: list[dict[str, Any]],
    human_day: int,
    human_done: bool,
) -> list[dict[str, Any]]:
    if not isinstance(steps, list):
        return []
    if not _is_int_not_bool(human_day):
        raise ValueError("human_day must be an integer")
    out: list[dict[str, Any]] = []
    for raw_step in steps:
        sanitized = sanitize_opponent_step_for_hud(raw_step, human_day, human_done is True)
        if sanitized is not None:
            out.append(sanitized)
    return out


def sanitize_office_frame(frame: dict[str, Any], human_done: bool) -> dict[str, Any] | None:
    if not isinstance(frame, dict):
        return None
    if human_done is True:
        cloned = json.loads(json.dumps(frame, default=str))
        if cloned.get("leaking_sprite_employee") is None and isinstance(cloned.get("mole"), str):
            cloned["leaking_sprite_employee"] = cloned["mole"]
        return cloned
    forbidden = PRE_END_STRIP_KEYS | frozenset({"accused", "score", "leaking_sprite_employee"})
    cleaned: dict[str, Any] = _strip_keys_recursive(frame, forbidden)
    cleaned["leaking_sprite_employee"] = None
    cleaned["done"] = False
    if "known_v" in cleaned and _is_finite_number(cleaned["known_v"]) and "V" in cleaned:
        cleaned["V"] = float(cleaned["known_v"])
    return cleaned


def sanitize_mole_view(view: dict[str, Any], human_done: bool) -> dict[str, Any] | None:
    if not isinstance(view, dict):
        return None
    if human_done is True:
        return json.loads(json.dumps(view, default=str))

    forbidden = PRE_END_STRIP_KEYS | MOLE_PRE_END_STRIP_KEYS | frozenset({"score", "leaking_sprite_employee"})
    cleaned: dict[str, Any] = _strip_keys_recursive(view, forbidden)
    mask_map: dict[str, str] = {}
    used_masks: set[str] = set()

    def _collect_existing(node: Any) -> None:
        if isinstance(node, list):
            for x in node:
                _collect_existing(x)
        elif isinstance(node, dict):
            did = node.get("doc_id")
            if isinstance(did, str) and not CANARY_DOC_ID_RE.match(did):
                used_masks.add(did)
            for v in node.values():
                _collect_existing(v)

    _collect_existing(cleaned)
    counter = [0]

    def _mask_doc_id(raw_id: str) -> str:
        if not CANARY_DOC_ID_RE.match(raw_id):
            return raw_id
        if raw_id in mask_map:
            return mask_map[raw_id]
        while f"doc_{counter[0]}" in used_masks:
            counter[0] += 1
        assigned = f"doc_{counter[0]}"
        counter[0] += 1
        used_masks.add(assigned)
        mask_map[raw_id] = assigned
        return assigned

    cur_day = int(cleaned["day"]) if _is_int_not_bool(cleaned.get("day")) else 1
    n_staff = int(cleaned["n_staff"]) if _is_int_not_bool(cleaned.get("n_staff")) else 20

    def _scrub_docs(node: Any) -> Any:
        if isinstance(node, list):
            return [_scrub_docs(x) for x in node]
        if isinstance(node, dict):
            updated: dict[str, Any] = {}
            for k, v in node.items():
                if k == "doc_id" and isinstance(v, str):
                    updated[k] = _mask_doc_id(v)
                elif k == "title" and isinstance(v, str) and "canary" in v.lower():
                    updated[k] = "Internal department memo"
                else:
                    updated[k] = _scrub_docs(v)
            if "doc_id" in updated and ("recipients" in updated or "recipient_count" in updated):
                rc = (
                    int(updated["recipient_count"])
                    if _is_int_not_bool(updated.get("recipient_count"))
                    else len(updated.get("recipients") or [])
                )
                updated["recipient_count"] = rc
                if "days_old" not in updated:
                    if _is_int_not_bool(updated.get("age_days")):
                        updated["days_old"] = int(updated["age_days"])
                    elif _is_int_not_bool(updated.get("day")):
                        updated["days_old"] = max(0, cur_day - int(updated["day"]))
                    else:
                        updated["days_old"] = 0
                if "sensitivity" not in updated:
                    updated["sensitivity"] = _doc_sensitivity_label(rc, n_staff, 3)
            return updated
        return node

    cleaned = _scrub_docs(cleaned)
    cleaned["done"] = False
    if "known_v" in cleaned and _is_finite_number(cleaned["known_v"]) and "V" in cleaned:
        cleaned["V"] = float(cleaned["known_v"])
    return cleaned


def seal_payload(obj: Any) -> str:
    raw = json.dumps(obj, separators=(",", ":"), sort_keys=True).encode("utf-8")
    encoded = base64.b64encode(raw).decode("ascii")
    return f"sealed:{encoded}"


def unseal_payload(token: str, human_done: bool) -> Any:
    if human_done is not True:
        raise PermissionError("cannot unseal payload while human_done is False")
    if not isinstance(token, str) or not token.startswith("sealed:"):
        raise ValueError("sealed token must start with 'sealed:'")
    b64_part = token[len("sealed:") :]
    if not b64_part:
        raise ValueError("empty sealed payload")
    try:
        decoded = base64.b64decode(b64_part.encode("ascii"), validate=True)
        return json.loads(decoded.decode("utf-8"))
    except Exception as exc:
        raise ValueError("invalid sealed payload encoding") from exc


seal_reveal = seal_payload
unseal_reveal = unseal_payload


def assert_pre_end_clean(node: Any, label: str = "payload") -> bool:
    strict_keys = (
        PRE_END_STRIP_KEYS
        | OPPONENT_EXTRA_STRIP_KEYS - frozenset({"leaking_sprite_employee"})
        | frozenset(
            {
                "canary_variants",
                "posterior",
                "mole_posterior",
                "posteriors",
                "posterior_curve",
                "top_suspect",
                "top_suspects",
                "top_posterior",
                "mole_rank",
                "leaked_canaries",
                "caught_by_canary",
            }
        )
    )

    def _walk(cur: Any, path: str, in_inv_docs: bool, in_mole_mode: bool) -> None:
        if isinstance(cur, list):
            for idx, item in enumerate(cur):
                _walk(item, f"{path}[{idx}]", in_inv_docs, in_mole_mode)
            return
        if not isinstance(cur, dict):
            return

        mode_str = str(cur.get("mode") or "").strip().lower()
        now_mole = in_mole_mode or mode_str in MOLE_MODE_NAMES
        is_list_docs = cur.get("tool") == "list_documents" and not now_mole

        if "leaking_sprite_employee" in cur and cur["leaking_sprite_employee"] is not None:
            raise ValueError(f"{path}.leaking_sprite_employee leaked pre-end value {cur['leaking_sprite_employee']!r}")

        for k in cur:
            ks = str(k)
            if ks in strict_keys or "world_secret" in ks.lower():
                raise ValueError(f"{path}.{ks}: forbidden pre-end truth key present")
            if ks == "is_canary" and not in_inv_docs:
                raise ValueError(f"{path}.{ks}: forbidden pre-end canary flag")
            if now_mole and ks == "doc_id" and isinstance(cur[k], str) and CANARY_DOC_ID_RE.match(cur[k]):
                raise ValueError(f"{path}.doc_id: unmasked canary doc_id {cur[k]!r}")

        if "V" in cur and "known_v" in cur and _is_finite_number(cur["V"]) and _is_finite_number(cur["known_v"]):
            if abs(float(cur["V"]) - float(cur["known_v"])) > 1e-9:
                raise ValueError(f"{path}.V: pre-end V={cur['V']} diverges from known_v={cur['known_v']}")

        if cur.get("tool") == "accuse":
            args_obj = cur.get("args") if isinstance(cur.get("args"), dict) else (
                cur.get("arguments") if isinstance(cur.get("arguments"), dict) else None
            )
            emp_val = (
                args_obj.get("employee")
                if isinstance(args_obj, dict)
                else ("[SEALED]" if cur.get("args") == "[SEALED]" else None)
            )
            if emp_val != "[SEALED]" or (isinstance(emp_val, str) and EMP_ID_EXACT_RE.match(emp_val)):
                raise ValueError(f"{path}.args.employee: unsealed opponent accuse target {emp_val!r}")
            if isinstance(args_obj, dict) and EMP_ID_TOKEN_RE.search(json.dumps(args_obj, default=str)):
                raise ValueError(f"{path}.args: unredacted employee id in accuse args")
            for field_name in ACCUSE_REDACT_FIELDS:
                if field_name in cur:
                    dumped = json.dumps(cur[field_name], default=str)
                    if EMP_ID_TOKEN_RE.search(dumped):
                        raise ValueError(f"{path}.{field_name}: unredacted employee id in accuse step")

        for k, v in cur.items():
            ks = str(k)
            child_inv_docs = in_inv_docs or (is_list_docs and ks in {"result", "data", "documents"})
            child_mole_mode = now_mole or ks == "leakable_docs"
            _walk(v, f"{path}.{ks}", child_inv_docs, child_mole_mode)

    _walk(node, label, False, False)
    return True
