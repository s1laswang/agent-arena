"""Single source of truth for game rules and tier parameters.

Owner: HEAD-ENV. Numbers may be tuned (FR8 calibration sweep J1), the *shape* may not
change without a note in docs/CONTRACT.md + docs/reports/CEO.md.

Every rule here must also be stated in plain words in harbor/canary-task/instruction.md:
the agent must have all the information it needs (rubric: "meaningful difficulty").
"""
from __future__ import annotations

import math
from contextlib import contextmanager
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
    doc_recipient_share: float = 0.0  # v0.3 calib: regular docs also go to random extra staff until >= this share of all employees
    canary_level: int = 1          # canary min clearance (access_constraints); clearance is 1..3 so all qualify
    search_max_results: int = 20   # search_messages result cap
    low_recipient_threshold: int = 3     # Mole DSL feature recent_low_recipient_docs counts docs with <= this many recipients
    fingerprint_accuracy: float = 1.0  # v0.4: P(feed shows the mole's true variant); else uniform over the canary's other variants
    noise: float = 1.0             # difficulty-curve knob (FR8 sweep); see apply_noise. 1.0 = tier as defined

    def to_dict(self) -> dict:
        return asdict(self)


TIERS_VERSION = "v1.4"  # v1.4: hard = 40 staff, 21 days, 2 canaries/day x 3 variants, leak_damage 0.05 (CONTRACT §14)

# v1.3 (CONTRACT §13): which V the agent sees in status/advance_day. True = known V
# = 1 - leak_damage x (surfaced leaks) - all costs so far (canaries, restrictions); False = v1.2 true V.
# Scoring always uses the true V. Module constant (not a TierParams field); pinned with TIERS in test_env_frozen.
KNOWN_V_MODE = True

TIERS: dict[str, TierParams] = {
    # tiers v1.1 (bayes-solver): medium max_variants 2->3, hard framing_rate 1.5->3.0 (monotone easy>medium>hard)
    # tiers v1 (04:40): FR8 J1 recommendation (153k episodes, v0.3 scoring), fr8/analysis/out/j1_recommendation.md
    "easy": TierParams(
        name="easy", n_employees=12, n_days=14, p_leak=0.9, delay_choices=(1,),
        leak_damage=0.05, canary_cost=0.01, canaries_per_day=1, max_variants=3,
        restrict_cost_per_day=0.01, actions_per_day=8, tool_call_cap=300,
        log_rate_benign=1.0, log_rate_mole=1.3, interview_lr=1.5, p_evasive_innocent=0.2,
        decoy=False, framing=False, careful_mole=False, access_constraints=False,
        framing_rate=1.0, p_after_hours_mole=0.15, p_single_dept_recipients=0.0,
    ),
    "medium": TierParams(
        name="medium", n_employees=20, n_days=14, p_leak=0.75, delay_choices=(1, 2, 3),
        leak_damage=0.04, canary_cost=0.01, canaries_per_day=1, max_variants=3,
        restrict_cost_per_day=0.01, actions_per_day=8, tool_call_cap=300,
        log_rate_benign=1.0, log_rate_mole=1.15, interview_lr=1.3, p_evasive_innocent=0.2,
        decoy=True, framing=True, careful_mole=True, access_constraints=False,
        framing_rate=1.5, p_after_hours_mole=0.15, p_single_dept_recipients=0.0,
    ),
    # tiers v1.4 (CONTRACT §14): HARD only. Long horizon, many concurrent delayed noisy tests:
    # n_employees 30->40, n_days 14->21, canaries_per_day 1->2, max_variants 2->3, leak_damage 0.035->0.05,
    # tool_call_cap 300->420 (20/day). Calibrated on dev seeds 4000-4599, confirmed on 5000-5799.
    "hard": TierParams(
        name="hard", n_employees=40, n_days=21, p_leak=0.65, delay_choices=(2, 3),
        leak_damage=0.05, canary_cost=0.01, canaries_per_day=2, max_variants=3,
        restrict_cost_per_day=0.01, actions_per_day=8, tool_call_cap=420,
        log_rate_benign=1.0, log_rate_mole=1.0, interview_lr=1.2, p_evasive_innocent=0.2,
        decoy=True, framing=True, careful_mole=True, access_constraints=True,
        framing_rate=2.0, p_after_hours_mole=0.3, p_single_dept_recipients=0.0,
        fingerprint_accuracy=0.95,  # v1.2 CEO decision: small fingerprint noise on hard
    ),
}

# Frozen history: tiers v1.3 (hash 8df71cf570bb48bc with KNOWN_V_MODE=True, tests/test_env_frozen.py).
# Only HARD changed in v1.4. Use `with tiers_version("v1.3"):` to replay v1.3 numbers in-process.
TIERS_V13: dict[str, TierParams] = {
    "easy": TIERS["easy"],
    "medium": TIERS["medium"],
    "hard": replace(TIERS["hard"], n_employees=30, n_days=14, leak_damage=0.035, canaries_per_day=1,
                    max_variants=2, tool_call_cap=300),
}
# Frozen history: tiers v1.2. v1.2 -> v1.3 (02a6ee9) changed only KNOWN_V_MODE, i.e. which V the agent is SHOWN;
# TIERS and scoring were untouched. So v1.2 episodes replay and re-grade under the v1.3 params, with
# KNOWN_V_MODE=False (tiers_version below). Checked by the anti-cheat replay: all 300 committed v1.2 episodes
# (gpt-5.5, codex-gpt-5.5, opencode-gpt-5.6-sol, reference) re-grade to their recorded score and accused id.
TIERS_V12: dict[str, TierParams] = TIERS_V13
KNOWN_V_MODE_HISTORY: dict[str, bool] = {"v1.2": False, "v1.3": True}
TIERS_HISTORY: dict[str, dict[str, TierParams]] = {"v1.3": TIERS_V13, "v1.2": TIERS_V12}

# Judge tracks: extra tier *names* that reuse a frozen tier's params (TIERS itself stays frozen).
# hard_forge = hard params + a per-seed evolved Mole DSL strategy (canary/forge_track.py).
# hard_rl = hard params + a per-seed RL-trained mole policy (canary/forge/rl_mole.py, data/rl_mole/).
TRACKS: dict[str, str] = {"hard_forge": "hard", "hard_rl": "hard"}


def tier_params(name: str) -> TierParams:
    """TierParams for a tier or a track name."""
    return TIERS[TRACKS.get(name, name)]


def tier_params_for_episode(name: str, steps=()) -> TierParams:
    """Params a recorded episode was played under: the current tier, unless its list_employees result shows a
    staff size only an earlier frozen version had (v1.3 hard = 30 staff, v1.4 hard = 40). For offline analysis
    of committed runs (canary.analysis.accuse, canary.solver.regret); never used by the live env."""
    cur = tier_params(name)
    n = None
    for st in steps or ():
        tool = st.tool if hasattr(st, "tool") else st.get("tool")
        res = st.result if hasattr(st, "result") else st.get("result")
        if tool == "list_employees" and isinstance(res, dict) and res.get("ok"):
            n = len((res.get("data") or {}).get("employees") or [])
            break
    if n is None or n == cur.n_employees:
        return cur
    for version in sorted(TIERS_HISTORY, reverse=True):
        p = TIERS_HISTORY[version].get(TRACKS.get(name, name))
        if p is not None and p.n_employees == n:
            return p
    return cur


@contextmanager
def tiers_version(version: str):
    """Temporarily swap TIERS (in place), TIERS_VERSION and KNOWN_V_MODE to a frozen earlier version, e.g. "v1.3".
    In-process only (not thread-safe); for replaying/regenerating earlier-rules numbers."""
    global TIERS_VERSION, KNOWN_V_MODE
    if version == TIERS_VERSION:
        yield TIERS
        return
    old, old_v, old_k = dict(TIERS), TIERS_VERSION, KNOWN_V_MODE
    TIERS.clear()
    TIERS.update(TIERS_HISTORY[version])
    TIERS_VERSION = version
    KNOWN_V_MODE = KNOWN_V_MODE_HISTORY.get(version, KNOWN_V_MODE)
    try:
        yield TIERS
    finally:
        TIERS.clear()
        TIERS.update(old)
        TIERS_VERSION = old_v
        KNOWN_V_MODE = old_k

# Seed hygiene: tune ONLY on dev seeds. Judge seeds are frozen and committed under data/worlds/judge/.
DEV_SEEDS = range(0, 10_000)
JUDGE_SEEDS = range(900_000, 900_040)   # 40 per tier (CI half-width < gap/3, FR8 J1)
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
