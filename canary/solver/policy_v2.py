"""SolverV2Policy: a stronger reference investigator on the SAME v1.4 rules and the SAME information as any agent
(tool calls + results + the instruction text). Subclasses SolverPolicy; the parent's code paths are untouched, so
`solver` replays byte-identically.

Changes vs `solver` (driven by results/solver_v2_v1.4.md, tuned on dev seeds 8000-8799 only):
  1. Pipelining under delay: count every outstanding canary (a canary can still leak for leak_window_days and
     surface up to max(delay) days later => up to canaries_per_day x (window + max delay) outstanding), not the
     4 most recent, when choosing the day's canaries by joint mutual information.
  2. One-canary-a-day tiers (medium): choose the canary by the joint MI with the outstanding canaries too
     (orthogonal to pending tests), instead of the single-canary MI that ignores them.
"""
from __future__ import annotations

from .policy import SolverPolicy


class SolverV2Policy(SolverPolicy):
    name = "solver_v2"

    def __init__(self, params=None, max_pending: int = 12, joint_single: bool = True, **kw):
        self.joint_single = joint_single
        super().__init__(params, max_pending=max_pending, **kw)

    def plan_canaries(self, post):
        P = self.P
        cpd = max(1, int(getattr(P, "canaries_per_day", 1)))
        if not (self.joint_single and cpd == 1 and P.careful_mole and self.multi != "off"):
            return super().plan_canaries(post)
        # cpd == 1, careful mole: the joint-MI greedy for one canary, pending canaries included
        saved = P
        try:
            from dataclasses import replace
            self.P = replace(P, canaries_per_day=1)
            return self._joint_one(post)
        finally:
            self.P = saved

    def _joint_one(self, post):
        P, o = self.P, self.obs
        n = len(o.employees) or 1
        alive = [e for e in post if post[e] > 1e-4 and e not in self.restricted]
        if len(alive) <= 1:
            return []
        win = P.leak_window_days
        wdocs = [d for d in o.docs.values() if not d.is_canary and d.day >= o.today - win]
        nreg_s = {e: sum(1 for d in wdocs if e in d.recipients) for e in post}
        pend = self._pending_canaries()
        sub = {e: post[e] for e in post if post[e] > 1e-4}
        z = sum(sub.values()) or 1.0
        sub = {e: v / z for e, v in sub.items()}
        rng = __import__("random").Random(f"canary:{o.today}:{len(o.feed)}:0")
        best, bestu = None, -1.0
        base = self.joint_mi(sub, pend, nreg_s)
        for n_eval, asg in enumerate(self._candidates(post, alive, rng, [])):
            if n_eval >= self.multi_candidates:
                break
            u = self.joint_mi(sub, pend + [(asg, self._cweight(len(asg), n), win)], nreg_s)
            if u > bestu:
                best, bestu = asg, u
        if best is None or bestu - base <= self.min_gain_first:
            return []
        return [best]
