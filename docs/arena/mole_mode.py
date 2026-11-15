from __future__ import annotations

import hashlib
import json
import random
from typing import Any

from canary.env import Env
from canary.mole.dsl import MoleView
from canary.rules import TIERS_VERSION
from canary.solver.policy import SolverPolicy
from canary.world import PROJECTS, TITLE_TPL

SEED_MIN = 3000
SEED_MAX = 9999
ALLOWED_TIERS = ("medium", "hard")
DEFAULT_TIER = "medium"
MAX_SOLVER_STEPS_PER_DAY = 64


def check_seed(seed: Any) -> int:
    if isinstance(seed, bool):
        raise ValueError(f"seed must be an integer in {SEED_MIN}..{SEED_MAX} (public dev seeds)")
    try:
        s = int(seed)
    except (TypeError, ValueError):
        raise ValueError(f"seed must be an integer in {SEED_MIN}..{SEED_MAX} (public dev seeds)") from None
    if not SEED_MIN <= s <= SEED_MAX or str(seed).strip() != str(s):
        raise ValueError(f"seed must be an integer in {SEED_MIN}..{SEED_MAX} (public dev seeds)")
    return s


def check_tier(tier: Any) -> str:
    if not isinstance(tier, str) or tier.strip() not in ALLOWED_TIERS:
        raise ValueError(f"tier must be one of {ALLOWED_TIERS}")
    return tier.strip()


def _normalize_seed_tier(seed: Any = SEED_MIN, tier: Any = DEFAULT_TIER) -> tuple[int, str]:
    if isinstance(seed, str) and not seed.strip().lstrip("-").isdigit() and not isinstance(tier, bool):
        if isinstance(tier, int) or (isinstance(tier, str) and tier.strip().lstrip("-").isdigit()):
            return check_seed(tier), check_tier(seed)
    return check_seed(seed), check_tier(tier)


class _HumanMoleStrategy:
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


class MoleModeSession:
    def __init__(self, seed: Any = SEED_MIN, tier: Any = DEFAULT_TIER) -> None:
        self._seed, self._tier = _normalize_seed_tier(seed, tier)
        self._strategy = _HumanMoleStrategy()
        self._env = Env(self._tier, self._seed, mole_strategy=self._strategy)
        self._solver = SolverPolicy()
        self._solver.reset(self._env.tools_spec(), self._env.instruction())
        self._pending_solver_call: tuple[str, dict[str, Any]] | None = None
        self._masked_days: set[int] = set()
        self._raw_to_mask: dict[str, str] = {}
        self._mask_to_raw: dict[str, str] = {}
        self._raw_to_title: dict[str, str] = {}
        self._day_snapshots: list[dict[str, Any]] = []
        self._leak_records: list[dict[str, Any]] = []
        self._mole_history: list[dict[str, Any]] = []
        self._advance_solver_pre_mole()

    @property
    def seed(self) -> int:
        return self._seed

    @property
    def tier(self) -> str:
        return self._tier

    @property
    def tiers_version(self) -> str:
        return TIERS_VERSION

    @property
    def day(self) -> int:
        return self._env.day

    @property
    def n_days(self) -> int:
        return self._env.p.n_days

    @property
    def done(self) -> bool:
        return self._env.done

    @property
    def mole_id(self) -> str:
        return self._env._world.mole

    def _cover_title(self, doc: dict[str, Any]) -> str:
        raw_title = str(doc.get("title", ""))
        if not doc.get("is_canary") and not raw_title.startswith("Board memo draft"):
            return raw_title
        emp_dept = {e.id: e.dept for e in self._env._world.employees}
        dept_counts: dict[str, int] = {}
        for eid in doc.get("recipients", []):
            dept = emp_dept.get(eid)
            if dept:
                dept_counts[dept] = dept_counts.get(dept, 0) + 1
        if dept_counts:
            primary_dept = min(dept_counts, key=lambda k: (-dept_counts[k], k))
        else:
            primary_dept = self._env._world.depts[0]
        digest = hashlib.sha256(f"{self._seed}:{self._tier}:cover:{doc['doc_id']}".encode()).digest()
        rng = random.Random(int.from_bytes(digest[:8], "big"))
        tpl = rng.choice(TITLE_TPL)
        return tpl.format(
            q=rng.choice(["Q1", "Q2", "Q3", "Q4"]),
            d=primary_dept,
            p=rng.choice(PROJECTS),
        )

    def _sync_day_masks(self, d: int) -> None:
        for day_num in range(1, d + 1):
            if day_num in self._masked_days:
                continue
            day_docs = [x for x in self._env.docs if x["day"] == day_num]
            if not day_docs:
                continue
            ordered = sorted(
                day_docs,
                key=lambda x: hashlib.sha256(
                    f"{self._seed}:{self._tier}:desk:{day_num}:{x['doc_id']}".encode()
                ).hexdigest(),
            )
            for idx, doc in enumerate(ordered, start=1):
                raw_id = doc["doc_id"]
                mask_id = f"doc-d{day_num}-{idx}"
                self._raw_to_mask[raw_id] = mask_id
                self._mask_to_raw[mask_id] = raw_id
                self._raw_to_title[raw_id] = self._cover_title(doc)
            self._masked_days.add(day_num)

    def _record_solver_snapshots(self) -> None:
        while len(self._day_snapshots) < len(self._solver.trace):
            tr = self._solver.trace[len(self._day_snapshots)]
            self._day_snapshots.append(
                {
                    "day": int(tr["day"]),
                    "post": dict(tr["post"]),
                    "visible_v": self._env.visible_V(),
                    "true_v": round(self._env.V, 10),
                }
            )

    def _advance_solver_pre_mole(self) -> dict[str, Any]:
        start_idx = len(self._env.history)
        for _ in range(MAX_SOLVER_STEPS_PER_DAY):
            if self._env.done:
                self._pending_solver_call = None
                break
            tool, args = self._solver.act(list(self._env.history))
            self._record_solver_snapshots()
            if tool == "advance_day":
                self._pending_solver_call = (tool, dict(args))
                break
            self._env.call(tool, args)
        self._record_solver_snapshots()
        self._sync_day_masks(self._env.day)
        mole_id = self.mole_id
        cur_day = self._env.day
        new_steps = self._env.history[start_idx:]
        mole_interviewed = any(
            st.day == cur_day
            and st.tool == "interview"
            and st.args.get("employee") == mole_id
            and st.result.get("ok")
            for st in new_steps
        )
        mole_restricted = any(
            st.day == cur_day
            and st.tool == "restrict_access"
            and st.args.get("employee") == mole_id
            and st.result.get("ok")
            for st in new_steps
        )
        accused = any(
            st.tool == "accuse" and st.result.get("ok")
            for st in new_steps
        )
        return {
            "day": cur_day,
            "total_staff_restricted": len(self._env._restricted),
            "restricted_ids": sorted(self._env._restricted),
            "mole_interviewed": mole_interviewed,
            "mole_restricted": mole_restricted or (mole_id in self._env._restricted),
            "accused": accused,
        }

    def _leakable_raw_docs(self) -> list[dict[str, Any]]:
        d = self._env.day
        lo = d - self._env.p.leak_window_days + 1
        mole_id = self.mole_id
        raw_docs = [
            self._env._doc_by_id[doc_id]
            for doc_id in self._env._held[mole_id]
            if doc_id not in self._env._leaked and lo <= self._env._doc_by_id[doc_id]["day"] <= d
        ]
        return sorted(
            raw_docs,
            key=lambda x: (x["day"], self._raw_to_mask.get(x["doc_id"], x["doc_id"])),
        )

    def get_mole_day_view(self) -> dict[str, Any]:
        p = self._env.p
        w = self._env._world
        d = self._env.day
        self._sync_day_masks(d)
        mole_id = w.mole
        mole_emp = next(e for e in w.employees if e.id == mole_id)
        leakable_raw = self._leakable_raw_docs()
        leakable_docs = [
            {
                "doc_id": self._raw_to_mask[doc["doc_id"]],
                "title": self._raw_to_title[doc["doc_id"]],
                "day": int(doc["day"]),
                "age_days": int(d - doc["day"]),
                "recipient_count": len(doc["recipients"]),
                "recipients": list(doc["recipients"]),
            }
            for doc in leakable_raw
        ]
        docs_alias = [dict(item, recipients=list(item["recipients"])) for item in leakable_docs]
        interview_topics_today = [
            str(st.args["topic"])
            for st in self._env.history
            if st.day == d
            and st.tool == "interview"
            and st.args.get("employee") == mole_id
            and st.result.get("ok")
        ]
        restricted_today = any(
            st.day == d
            and st.tool == "restrict_access"
            and st.args.get("employee") == mole_id
            and st.result.get("ok")
            for st in self._env.history
        )
        surfaced = [
            {
                "surfaced_day": int(f["surfaced_day"]),
                "doc_id": self._raw_to_mask.get(f["doc_id"], f["doc_id"]),
                "title": self._raw_to_title.get(f["doc_id"], f["title"]),
            }
            for f in self._env._feed
            if f["surfaced_day"] <= d
        ]
        vis_v = self._env.visible_V()
        peers = [e.id for e in w.employees if e.id != mole_id]
        peer_roster = [
            {
                "id": e.id,
                "name": e.name,
                "dept": e.dept,
                "role": e.role,
                "restricted": e.id in self._env._restricted,
            }
            for e in w.employees
            if e.id != mole_id
        ]
        i_am_restricted = mole_id in self._env._restricted
        total_restricted = len(self._env._restricted)
        n_restricted_colleagues = sum(1 for eid in self._env._restricted if eid != mole_id)
        return {
            "seed": self._seed,
            "tier": self._tier,
            "tiers_version": TIERS_VERSION,
            "company": w.company,
            "day": d,
            "n_days": p.n_days,
            "leak_window_days": p.leak_window_days,
            "done": bool(self._env.done),
            "end_reason": self._env._end_reason if self._env.done else None,
            "mole_id": mole_emp.id,
            "mole_name": mole_emp.name,
            "mole_dept": mole_emp.dept,
            "mole_role": mole_emp.role,
            "mole_clearance": mole_emp.clearance,
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
            "can_leak": bool(leakable_docs) and not self._env.done,
            "days_since_last_leak": (d - self._env._last_leak_day) if self._env._last_leak_day else d,
            "recent_low_recipient_docs": sum(
                1 for doc in leakable_raw if len(doc["recipients"]) <= p.low_recipient_threshold
            ),
            "visible_v": vis_v,
            "visible_V": vis_v,
            "total_staff_restricted": total_restricted,
            "n_restricted_colleagues": n_restricted_colleagues,
            "restricted_ids": sorted(self._env._restricted),
            "i_am_restricted": i_am_restricted,
            "restricted_today": restricted_today,
            "interviewed_today": bool(interview_topics_today),
            "interview_topics_today": interview_topics_today,
            "total_surfaced_leaks": len(surfaced),
            "surfaced_leaks": surfaced,
            "pressure": {
                "total_staff_restricted": total_restricted,
                "i_am_restricted": i_am_restricted,
                "restricted_today": restricted_today,
                "interviewed_today": bool(interview_topics_today),
                "total_surfaced_leaks": len(surfaced),
                "visible_v": vis_v,
            },
        }

    def _compute_scores(self) -> tuple[float, float]:
        solver_score = float(self._env.score())
        accused = self._env._accused
        mole_id = self.mole_id
        true_v = round(self._env.V, 10)
        if accused == mole_id:
            mole_score = round(-solver_score, 10)
        elif accused is not None:
            mole_score = 1.0
        elif not self._leak_records:
            mole_score = 0.0
        else:
            mole_score = round(min(1.0, max(0.0, 1.0 - true_v)), 10)
        return mole_score, solver_score

    def _outcome_summary(self) -> dict[str, Any]:
        mole_id = self.mole_id
        accused = self._env._accused
        caught = bool(accused == mole_id)
        survived = not caught
        mole_score, solver_score = self._compute_scores()
        return {
            "done": True,
            "survived": survived,
            "caught": caught,
            "accused_id": accused,
            "end_reason": self._env._end_reason,
            "final_day": self._env.day,
            "mole_score": mole_score,
            "solver_score": solver_score,
            "leaks_count": len(self._leak_records),
        }

    def step_mole_day(self, action: dict[str, Any] | str | None = None) -> dict[str, Any]:
        if self._env.done:
            return {
                "ok": False,
                "error": "episode over",
                "done": True,
                "day_view": self.get_mole_day_view(),
                "outcome": self._outcome_summary(),
            }
        if isinstance(action, str):
            try:
                parsed = json.loads(action) if action.strip() else {}
            except ValueError:
                return {
                    "ok": False,
                    "error": "action is not valid JSON",
                    "done": self._env.done,
                    "day_view": self.get_mole_day_view(),
                    "outcome": None,
                }
        elif isinstance(action, dict):
            parsed = action
        else:
            return {
                "ok": False,
                "error": "action must be a dict or JSON object",
                "done": self._env.done,
                "day_view": self.get_mole_day_view(),
                "outcome": None,
            }

        action_type = str(parsed.get("type") or parsed.get("action") or "").strip().lower()
        if action_type not in ("leak", "hold"):
            return {
                "ok": False,
                "error": "action type must be 'leak' or 'hold'",
                "done": self._env.done,
                "day_view": self.get_mole_day_view(),
                "outcome": None,
            }

        d = self._env.day
        self._sync_day_masks(d)
        leakable_raw = self._leakable_raw_docs()
        leakable_raw_ids = {doc["doc_id"] for doc in leakable_raw}

        chosen_raw_doc: str | None = None
        chosen_mask_doc: str | None = None
        if action_type == "leak":
            doc_arg = parsed.get("doc_id")
            if not isinstance(doc_arg, str) or not doc_arg.strip():
                return {
                    "ok": False,
                    "error": "doc_id is required when type is 'leak'",
                    "done": self._env.done,
                    "day_view": self.get_mole_day_view(),
                    "outcome": None,
                }
            doc_arg = doc_arg.strip()
            raw_candidate = self._mask_to_raw.get(doc_arg, doc_arg)
            if raw_candidate not in leakable_raw_ids:
                return {
                    "ok": False,
                    "error": "doc_id is not a leakable document held by the mole",
                    "done": self._env.done,
                    "day_view": self.get_mole_day_view(),
                    "outcome": None,
                }
            chosen_raw_doc = raw_candidate
            chosen_mask_doc = self._raw_to_mask[raw_candidate]

        mole_id = self.mole_id
        peers_set = {e.id for e in self._env._world.employees if e.id != mole_id}
        raw_frame = parsed.get("frame_peer", parsed.get("frame"))
        chosen_frame: str | None = None
        if raw_frame not in (None, "", "none"):
            if not isinstance(raw_frame, str):
                return {
                    "ok": False,
                    "error": "frame_peer must be a valid peer employee id",
                    "done": self._env.done,
                    "day_view": self.get_mole_day_view(),
                    "outcome": None,
                }
            frame_clean = raw_frame.strip()
            if frame_clean in peers_set or frame_clean in ("random_peer", "most_restricted_peer"):
                chosen_frame = frame_clean
            else:
                return {
                    "ok": False,
                    "error": "frame_peer must be a valid peer employee id",
                    "done": self._env.done,
                    "day_view": self.get_mole_day_view(),
                    "outcome": None,
                }

        self._strategy.pending_action = {"leak": chosen_raw_doc, "frame": chosen_frame}
        feed_before = len(self._env._feed)
        adv_tool, adv_args = self._pending_solver_call or ("advance_day", {})
        self._pending_solver_call = None
        self._env.call(adv_tool, adv_args)

        applied = self._strategy.last_applied or {"leak": None, "frame": None}
        actual_raw_leak = applied.get("leak")
        actual_frame = applied.get("frame")
        if len(self._env._feed) > feed_before:
            feed_item = self._env._feed[-1]
            leaked_doc = self._env._doc_by_id[feed_item["doc_id"]]
            obs_variant = feed_item.get("variant")
            variants_map = leaked_doc.get("variants", {}) if leaked_doc.get("is_canary") else {}
            true_var = (
                next((k for k, es in variants_map.items() if mole_id in es), None)
                if leaked_doc.get("is_canary")
                else None
            )
            var_recs = list(variants_map.get(obs_variant, [])) if obs_variant is not None else []
            self._leak_records.append(
                {
                    "leaked_day": d,
                    "surfaced_day": int(feed_item["surfaced_day"]),
                    "doc_id": self._raw_to_mask.get(leaked_doc["doc_id"], leaked_doc["doc_id"]),
                    "raw_doc_id": leaked_doc["doc_id"],
                    "title": self._raw_to_title.get(leaked_doc["doc_id"], leaked_doc["title"]),
                    "raw_title": leaked_doc["title"],
                    "is_canary": bool(leaked_doc.get("is_canary")),
                    "variant": obs_variant,
                    "true_variant": true_var,
                    "variant_recipients": var_recs,
                }
            )

        applied_record = {
            "day": d,
            "type": "leak" if actual_raw_leak is not None else "hold",
            "doc_id": self._raw_to_mask.get(actual_raw_leak, chosen_mask_doc) if actual_raw_leak else None,
            "frame_peer": actual_frame,
        }
        self._mole_history.append(dict(applied_record))

        if not self._env.done:
            solver_events = self._advance_solver_pre_mole()
        else:
            self._record_solver_snapshots()
            solver_events = {
                "day": self._env.day,
                "total_staff_restricted": len(self._env._restricted),
                "restricted_ids": sorted(self._env._restricted),
                "mole_interviewed": False,
                "mole_restricted": mole_id in self._env._restricted,
                "accused": False,
            }

        return {
            "ok": True,
            "applied_action": applied_record,
            "solver_events": solver_events,
            "done": bool(self._env.done),
            "day_view": self.get_mole_day_view(),
            "outcome": self._outcome_summary() if self._env.done else None,
        }

    def get_mole_debrief(self) -> dict[str, Any]:
        if not self._env.done:
            return {
                "ok": False,
                "done": False,
                "error": "the episode is not over yet",
            }
        w = self._env._world
        mole_id = w.mole
        mole_emp = next(e for e in w.employees if e.id == mole_id)
        final_day = self._env.day
        accused_id = self._env._accused
        caught = bool(accused_id == mole_id)
        survived = not caught
        mole_score, solver_score = self._compute_scores()
        true_v = round(self._env.V, 10)
        vis_v = self._env.visible_V()
        leak_damage_dealt = round(len(self._leak_records) * self._env.p.leak_damage, 10)

        posterior_curve: list[dict[str, Any]] = []
        for snap in self._day_snapshots:
            post = snap["post"]
            mole_p = float(post.get(mole_id, 0.0))
            if post:
                ranked = sorted(post.items(), key=lambda kv: (-kv[1], kv[0]))
                top_suspect, top_p = ranked[0]
                mole_rank = next(
                    (idx for idx, (eid, _) in enumerate(ranked, start=1) if eid == mole_id),
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
                "variant": rec["variant"],
            }
            for rec in self._leak_records
        ]

        leaks_surfaced = [
            {
                "surfaced_day": int(f["surfaced_day"]),
                "doc_id": self._raw_to_mask.get(f["doc_id"], f["doc_id"]),
                "raw_doc_id": f["doc_id"],
                "title": self._raw_to_title.get(f["doc_id"], f["title"]),
                "raw_title": f["title"],
                "variant": f.get("variant"),
            }
            for f in self._env._feed
            if f["surfaced_day"] <= final_day
        ]

        leaked_canaries = [
            {
                "doc_id": rec["doc_id"],
                "raw_doc_id": rec["raw_doc_id"],
                "title": rec["title"],
                "raw_title": rec["raw_title"],
                "variant": rec["variant"],
                "true_variant": rec["true_variant"],
                "variant_recipients": list(rec["variant_recipients"]),
                "leaked_day": rec["leaked_day"],
                "surfaced_day": rec["surfaced_day"],
                "surfaced": bool(rec["surfaced_day"] <= final_day),
            }
            for rec in self._leak_records
            if rec["is_canary"]
        ]

        caught_by_canary: dict[str, Any] | None = None
        if caught:
            surfaced_canaries = [c for c in leaked_canaries if c["surfaced"]]
            direct_hits = [c for c in surfaced_canaries if mole_id in c["variant_recipients"]]
            pool = direct_hits or surfaced_canaries
            if pool:
                chosen = max(pool, key=lambda c: (c["surfaced_day"], c["leaked_day"]))
                caught_by_canary = dict(chosen, variant_recipients=list(chosen["variant_recipients"]))

        days_survived = final_day if survived else max(0, final_day - 1)
        return {
            "ok": True,
            "done": True,
            "seed": self._seed,
            "tier": self._tier,
            "tiers_version": TIERS_VERSION,
            "company": w.company,
            "mole_id": mole_emp.id,
            "mole_name": mole_emp.name,
            "mole_dept": mole_emp.dept,
            "mole_role": mole_emp.role,
            "survived": survived,
            "caught": caught,
            "accused_id": accused_id,
            "end_reason": self._env._end_reason,
            "final_day": final_day,
            "days_survived": days_survived,
            "mole_score": mole_score,
            "solver_score": solver_score,
            "true_v": true_v,
            "visible_v": vis_v,
            "leak_damage_dealt": leak_damage_dealt,
            "leaks_count": len(self._leak_records),
            "leaks_made": leaks_made,
            "leaks_surfaced": leaks_surfaced,
            "posterior_curve": posterior_curve,
            "caught_by_canary": caught_by_canary,
            "leaked_canaries": leaked_canaries,
            "history": [dict(x) for x in self._mole_history],
        }

    def day_view_json(self) -> str:
        return json.dumps(self.get_mole_day_view())

    def step_json(self, action: dict[str, Any] | str | None = None) -> str:
        return json.dumps(self.step_mole_day(action))

    def debrief_json(self) -> str:
        return json.dumps(self.get_mole_debrief())


MoleSession = MoleModeSession
MoleGame = MoleModeSession

_ACTIVE_SESSION: MoleModeSession | None = None


def _require_session(session: MoleModeSession | None = None) -> MoleModeSession:
    target = session if session is not None else _ACTIVE_SESSION
    if target is None:
        raise RuntimeError("no active MoleModeSession; call start_mole_game(seed, tier) first")
    return target


def start_mole_game(seed: Any = SEED_MIN, tier: Any = DEFAULT_TIER) -> MoleModeSession:
    global _ACTIVE_SESSION
    _ACTIVE_SESSION = MoleModeSession(seed=seed, tier=tier)
    return _ACTIVE_SESSION


new_mole_game = start_mole_game


def start_mole_game_json(seed: Any = SEED_MIN, tier: Any = DEFAULT_TIER) -> str:
    return start_mole_game(seed=seed, tier=tier).day_view_json()


def get_mole_day_view(session: MoleModeSession | None = None) -> dict[str, Any]:
    return _require_session(session).get_mole_day_view()


def get_mole_day_view_json(session: MoleModeSession | None = None) -> str:
    return _require_session(session).day_view_json()


def step_mole_day(
    first: MoleModeSession | dict[str, Any] | str | None = None,
    second: MoleModeSession | dict[str, Any] | str | None = None,
    *,
    session: MoleModeSession | None = None,
) -> dict[str, Any]:
    if isinstance(first, MoleModeSession):
        if isinstance(second, MoleModeSession):
            raise ValueError("action must be a dict or JSON object")
        return first.step_mole_day(second)
    if isinstance(second, MoleModeSession):
        return second.step_mole_day(first)
    return _require_session(session).step_mole_day(first)


def step_mole_day_json(
    first: MoleModeSession | dict[str, Any] | str | None = None,
    second: MoleModeSession | dict[str, Any] | str | None = None,
    *,
    session: MoleModeSession | None = None,
) -> str:
    return json.dumps(step_mole_day(first, second, session=session))


def get_mole_debrief(session: MoleModeSession | None = None) -> dict[str, Any]:
    return _require_session(session).get_mole_debrief()


def get_mole_debrief_json(session: MoleModeSession | None = None) -> str:
    return _require_session(session).debrief_json()
