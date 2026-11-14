"""Skill-ladder ablations of the reference SolverPolicy (scripts/skill_ladder.py).

Each variant removes exactly ONE modelling/decision component. The reference SolverPolicy is not
modified: AblatedSolver(ablation=None) behaves exactly like SolverPolicy.

  accuse_last    no EV/threshold rule: never accuse early, always accuse the argmax on the last day
  accuse_p50     no EV rule: accuse as soon as P(argmax) >= 0.5 (or on the last day), never abstain
  no_careful     belief assumes careful_mole=False (canary planning untouched)
  no_delay       belief assumes every leak surfaces after the smallest delay (no delay uncertainty)
  single_canary  one canary per day (multi="off")
  no_decoy       no decoy search and no decoy marginalisation in the belief
  no_framing     belief ignores framing (fake after-hours accesses are treated as real)
"""
from __future__ import annotations

from dataclasses import replace

from .belief import posterior
from .policy import SolverPolicy, accuse_value

ABLATIONS = ("accuse_last", "accuse_p50", "no_careful", "no_delay", "single_canary", "no_decoy", "no_framing")


class AblatedSolver(SolverPolicy):
    def __init__(self, params=None, ablation: str | None = None, **kw):
        if ablation is not None and ablation not in ABLATIONS:
            raise ValueError(f"unknown ablation {ablation!r}")
        self.ablation = ablation
        if ablation == "single_canary":
            kw["multi"] = "off"
        if ablation == "no_decoy":
            kw["find_decoy"] = False
        super().__init__(params, **kw)
        self.name = f"solver-{ablation}" if ablation else "solver"

    def _belief_params(self):
        P, a = self.P, self.ablation
        if a == "no_careful":
            return replace(P, careful_mole=False)
        if a == "no_delay":
            return replace(P, delay_choices=(min(P.delay_choices),))
        if a == "no_decoy":
            return replace(P, decoy=False)
        if a == "no_framing":
            return replace(P, framing=False)
        return P

    def belief(self):
        self.obs.leak_timing_known = self.v_drops_reveal_leaks()
        return posterior(self.obs, self._belief_params(), self.behaviour_temper, self.choice_temper,
                         self.noleak_temper)

    def _plan(self):
        if self.phase != "decide" or self.ablation not in ("accuse_last", "accuse_p50"):
            return super()._plan()
        o = self.obs
        post = self.belief()
        self.post = post
        best = max(post, key=post.get)
        last = o.today >= self.P.n_days
        self.trace.append({"day": o.today, "post": dict(post)})
        if last or (self.ablation == "accuse_p50" and post[best] >= 0.5):
            self.queue = [("accuse", {"employee": best})]
            return
        # identical to the reference non-accusing branch
        q = self.probe_actions(post)
        for i, asg in enumerate(self.plan_canaries(post)):
            q.append(("plant_canary", {"doc_title": f"Board memo draft {o.today}" + (f" ({i + 1})" if i else ""),
                                       "assignment": asg}))
        q += [("status", {}), ("advance_day", {})]
        self.queue = q
        self.phase = "advancing"


__all__ = ["ABLATIONS", "AblatedSolver", "accuse_value"]
