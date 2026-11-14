"""Single source of truth for game rules and tier parameters.

Owner: HEAD-ENV. Numbers may be tuned (FR8 calibration sweep J1), the *shape* may not
change without a note in docs/CONTRACT.md + docs/reports/CEO.md.

Every rule here must also be stated in plain words in harbor/canary-task/instruction.md:
the agent must have all the information it needs (rubric: "meaningful difficulty").
"""
from __future__ import annotations

import math
from dataclasses import dataclass, asdict, replace


@dataclass(frozen=True)
class TierParams:
    name: str
    n_employees: int
    n_days: int                    # episode horizon; reaching it without accusing scores 0
    p_leak: float                  # P(mole leaks one doc on a given day | it has something to leak)
    delay_choices: tuple[int, ...] # leak surfaces in the feed after d days, d ~ Uniform(delay_choices)
    leak_damage: float             # company value lost per leak (V starts at 1.0)
    canary_cost: float             # value cost per plant_canary call (overhead / suspicion)
    canaries_per_day: int          # max plant_canary calls per day
    max_variants: int              # ANTI-TRIVIALITY: distinct variants per canary (no "unique copy per person")
    restrict_cost_per_day: float   # value cost per restricted employee per day
    actions_per_day: int           # investigative tool calls allowed per day before advance_day is forced
    tool_call_cap: int             # global cap; hitting it ends the episode with score 0
    log_rate_benign: float         # sensitive-doc accesses/day by an innocent (Poisson)
    log_rate_mole: float           # sensitive-doc accesses/day by the mole (weak signal)
    interview_lr: float            # P(evasive | mole) / P(evasive | innocent); documented
    p_evasive_innocent: float      # base rate of an evasive interview answer for innocents
    decoy: bool                    # a disgruntled-but-innocent employee writes angry messages
    framing: bool                  # mole injects fake suspicious accesses attributed to others
    careful_mole: bool             # mole leaks a canary with prob scaled by (1 - share of staff that got it)
    access_constraints: bool       # canaries may only go to employees with clearance for that doc
    # --- v0 additive fields (HEAD-ENV 02:00); all stated in instruction.md ---
    leak_window_days: int = 3      # mole may leak docs received on days d-2..d (not yet leaked)
    p_after_hours_benign: float = 0.10   # share of an innocent's accesses flagged after_hours
    p_after_hours_mole: float = 0.30     # share of the mole's own accesses flagged after_hours
    framing_rate: float = 1.0      # if framing: Poisson rate/day of fake after-hours accesses attributed to others
    framing_decoy_share: float = 0.5     # share of framed accesses attributed to the decoy (rest uniform over others)
    docs_per_day: tuple[int, ...] = (2, 3, 4)  # regular docs published per day, uniform
    wrong_accusation_score: float = -1.0  # v0.3: firing an innocent costs a full company value
    p_single_dept_recipients: float = 0.6  # share of regular docs sent to one dept (else union of two)
    canary_level: int = 1          # canary min clearance (access_constraints); clearance is 1..3 so all qualify
    search_max_results: int = 20   # search_messages result cap
    low_recipient_threshold: int = 3     # Mole DSL feature recent_low_recipient_docs counts docs with <= this many recipients
    noise: float = 1.0             # difficulty-curve knob (FR8 sweep); see apply_noise. 1.0 = tier as defined

    def to_dict(self) -> dict:
        return asdict(self)


TIERS: dict[str, TierParams] = {
    "easy": TierParams(
        name="easy", n_employees=12, n_days=14, p_leak=0.9, delay_choices=(1,),
        leak_damage=0.05, canary_cost=0.01, canaries_per_day=1, max_variants=3,
        restrict_cost_per_day=0.01, actions_per_day=8, tool_call_cap=300,
        log_rate_benign=1.0, log_rate_mole=1.6, interview_lr=1.5, p_evasive_innocent=0.2,
        decoy=False, framing=False, careful_mole=False, access_constraints=False,
    ),
    "medium": TierParams(
        name="medium", n_employees=20, n_days=14, p_leak=0.75, delay_choices=(1, 2),
        leak_damage=0.04, canary_cost=0.01, canaries_per_day=1, max_variants=2,
        restrict_cost_per_day=0.01, actions_per_day=8, tool_call_cap=300,
        log_rate_benign=1.0, log_rate_mole=1.4, interview_lr=1.3, p_evasive_innocent=0.2,
        decoy=True, framing=True, careful_mole=False, access_constraints=False,
    ),
    "hard": TierParams(
        name="hard", n_employees=30, n_days=14, p_leak=0.65, delay_choices=(1, 2, 3),
        leak_damage=0.035, canary_cost=0.01, canaries_per_day=1, max_variants=2,
        restrict_cost_per_day=0.01, actions_per_day=8, tool_call_cap=300,
        log_rate_benign=1.0, log_rate_mole=1.3, interview_lr=1.2, p_evasive_innocent=0.2,
        decoy=True, framing=True, careful_mole=True, access_constraints=True,
    ),
}

# Seed hygiene: tune ONLY on dev seeds. Judge seeds are frozen and committed under data/worlds/judge/.
DEV_SEEDS = range(0, 10_000)
JUDGE_SEEDS = range(900_000, 900_030)   # 30 per tier
TRAIN_SEEDS = range(100_000, 200_000)   # small-model training data; disjoint from judge seeds
HELDOUT_SEEDS = range(800_000, 800_200) # small-model held-out eval


def apply_noise(params: TierParams, noise: float) -> TierParams:
    """Return a copy of `params` whose evidence is less (noise>1) or more (noise<1) informative.

    Mapping (noise = k > 0; k = 1 returns the tier unchanged except noise=1.0):
      * delay_choices: lo..max(lo, round(hi * k)) where (lo, hi) = (min, max) of the tier's choices
      * p_leak: min(1, p_leak / k)   (fewer leaks -> fewer observations)
      * likelihood ratios shrink toward 1 by a factor k:
          interview_lr      -> 1 + (interview_lr - 1) / k
          log_rate_mole     -> log_rate_benign + (log_rate_mole - log_rate_benign) / k
          p_after_hours_mole-> p_after_hours_benign + (p_after_hours_mole - p_after_hours_benign) / k
      * framing_rate: framing_rate * k
    """
    if noise <= 0:
        raise ValueError("noise must be > 0")
    k = float(noise)
    lo, hi = min(params.delay_choices), max(params.delay_choices)
    hi2 = max(lo, int(math.floor(hi * k + 0.5)))
    return replace(
        params,
        noise=k,
        delay_choices=tuple(range(lo, hi2 + 1)),
        p_leak=min(1.0, params.p_leak / k),
        interview_lr=1 + (params.interview_lr - 1) / k,
        log_rate_mole=params.log_rate_benign + (params.log_rate_mole - params.log_rate_benign) / k,
        p_after_hours_mole=params.p_after_hours_benign
        + (params.p_after_hours_mole - params.p_after_hours_benign) / k,
        framing_rate=params.framing_rate * k,
    )
