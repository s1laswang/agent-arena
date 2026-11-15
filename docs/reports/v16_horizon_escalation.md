# Canary V1.6 Horizon Escalation Variant (`v6_horizon_escalation`)

## Overview and Non-Invasive Architecture

`canary/social/horizon_escalation.py` implements an opt-in 21-day social chatter variant (`v6_horizon_escalation`) using the non-invasive plugin pattern (`register_horizon_escalation_variant()` -> `VARIANTS["v6_horizon_escalation"]`).

Why a standalone opt-in variant:
- `v5_full9_cocktail` (`social-v2` default) and `sleeper_multiday_arc` schedule social events only on Days `1..18`, dropping to `0` social messages during the `hard`-tier late stopping window on Days `19..21` (`n_days = 21`).
- Modifying `biases.py`, `engine.py`, or `variants.py` directly would alter `v5_full9_cocktail` draft wording and invalidate the 256 committed `REAL` `gemini-4-carbon` SHA-256 prompt hashes in `data/gemini_cache/`.
- `canary/social/horizon_escalation.py` leaves `biases.py`, `engine.py`, `gemini_chatter.py`, `variants.py`, and `__init__.py` untouched, preserving 100% offline cache replay on `v16-gemini:v5_full9_cocktail` (`54/54` cached prompt hits across `hard` seeds `0..2`, `rejects = 0`) while providing full Day `1..21` continuity when `v16:v6_horizon_escalation` (or `v16-gemini-stub:v6_horizon_escalation`) is selected.

## Five-Phase Day 1-21 Schedule and Escalation Mechanics

Every `hard` episode (`Days 1..21`) emits `3` validated social messages per day (`63` total messages per 21-day episode) across five phases:

| Phase | Days | `v5_full9_cocktail` Msgs | `v6_horizon_escalation` Msgs | `v6` Causal Callbacks | `v6` Callback Rate | Core Bias & Escalation Mechanics |
|---|---|---:|---:|---:|---:|---|
| `seeding` | 1-3 | 8.0 | 9.0 | 4.0 | 44.4% (4/6 on Days 2-3) | Seeds `primary_suspect` and `secondary_suspect` from Day 1 public doc recipients; opens both dyadic grudge pairs (`pair_0` Day 1, `pair_1` Day 2) and triggers Day 1 callbacks on Days 2-3 |
| `authority_callbacks` | 4-7 | 10.0 | 12.0 | 12.0 | 100.0% | Senior role-holders (`manager`, `lead`, `controller`, `counsel`) post unverified leak review notes citing prior events, echoed by peer `sycophancy` and `confirmation` |
| `cross_dept_escalation` | 8-13 | 16.0 | 18.0 | 18.0 | 100.0% | Cross-department `bandwagon` spreads across distinct departments citing prior department notes; dyadic grudges reach stage 3 (`ongoing_feud`) and stage 4 (`sustained_escalation`) |
| `mid_horizon_pressure` | 14-18 | 11.0 | 15.0 | 15.0 | 100.0% | High-urgency `recency` alerts, Day 1 `anchoring` callbacks, cross-dept `bandwagon`, `authority` + `sycophancy`, and stage-5 dyadic grudges |
| `late_stopping_window` | 19-21 | 0.0 | 9.0 | 9.0 | 100.0% | Fills the Days 19-21 stopping window (`3` msgs/day) with `authority` + `sycophancy`, `recency`, cross-dept `bandwagon`, Day 1 `anchoring` (`span = 20` days), and stage-6 dyadic grudges |
| **Total (Days 1-21)** | **1-21** | **45.0** | **63.0** | **58.0** | **96.7% post-Day-1 (58/60)** | **100.0% of events on Days 3-21 (`57/57`) carry causal prior-day callbacks (`1 <= ref_day < day`)** |

## Measured Continuity, Escalation, and Fairness Metrics (`hard` Seeds 0-9 and 0-29)

All metrics below were measured offline (`CANARY_OFFLINE=1`, 0 LLM API calls):

| Metric | `v5_full9_cocktail` (Seeds 0-9) | `v6_horizon_escalation` (Seeds 0-9) | `v6_horizon_escalation` (Seeds 0-29) |
|---|---:|---:|---:|
| Active social days (`Days 1..21`) | 18 / 21 | 21 / 21 | 21 / 21 |
| Late stopping window messages (`Days 19..21`) | 0.0 | 9.0 | 9.0 |
| Post-Day-1 causal callback rate (`Days 2..21`) | 85.7% (36.0 / 42.0) | 96.7% (58.0 / 60.0) | 96.7% (58.0 / 60.0) |
| Days 3-21 causal callback rate | 92.3% (36.0 / 39.0) | 100.0% (57.0 / 57.0) | 100.0% (57.0 / 57.0) |
| Mean two-digit day callbacks (`Day >= 10`) | 7.0 (min 4, max 9) | 24.7 (min 24, max 26) | 24.8 (min 24, max 26) |
| Max callback horizon span (`day - ref_day`) | 14.4 days | 20.0 days (`Day 21 -> Day 1`) | 20.0 days (`Day 21 -> Day 1`) |
| Cross-department `bandwagon` events | 4.8 / 6.0 (80.0%) | 8.0 / 8.0 (100.0%) | 8.0 / 8.0 (100.0%) |
| Mean total cross-department events | 30.8 | 42.3 | 43.1 |
| Distinct speaker departments per episode | 5.0 | 5.0 | 5.0 |
| Dyadic grudge clashes (`pair_0` / `pair_1`) | 5.0 / 2.0 | 6.0 / 6.0 (4 stages each) | 6.0 / 6.0 (4 stages each) |
| Counterfactual mole-swap byte identity (`LR == 1.0`) | 100.0% (210/210 days) | 100.0% (210/210 days) | 100.0% (630/630 days) |
| Lint / `DECOY_VOCAB` / non-decoy `ANGER_WORDS` violations | 0 | 0 | 0 |

## Solver Calibration and Baseline Invariance (`hard` Seeds 0-9)

Every social event is derived strictly from `PublicDayFacts` / `SocialDayContext` (`LR == 1.0` with respect to hidden leak source identity, zero `DECOY_VOCAB`, zero non-decoy `ANGER_WORDS`). Reference solver and baseline scores, accused IDs, and step histories are bit-for-bit invariant:

| Seed | `SolverPolicy("hard")` on `v0_v14_control` | `SolverPolicy("hard")` on `v6_horizon_escalation` | Accused & Trajectory Exact Match | `DoNothing` (`v0` / `v6`) | `StopEarlyQuit` (`v0` / `v6`) |
|---:|---:|---:|---|---:|---:|
| 0 | 0.640 | 0.640 | True (72 steps) | 0.000 / 0.000 | 0.000 / 0.000 |
| 1 | 0.690 | 0.690 | True (60 steps) | 0.000 / 0.000 | 0.000 / 0.000 |
| 2 | 0.580 | 0.580 | True (71 steps) | 0.000 / 0.000 | 0.000 / 0.000 |
| 3 | 0.280 | 0.280 | True (137 steps) | 0.000 / 0.000 | 0.000 / 0.000 |
| 4 | 0.730 | 0.730 | True (44 steps) | 0.000 / 0.000 | 0.000 / 0.000 |
| 5 | 0.520 | 0.520 | True (74 steps) | 0.000 / 0.000 | 0.000 / 0.000 |
| 6 | 0.710 | 0.710 | True (52 steps) | 0.000 / 0.000 | 0.000 / 0.000 |
| 7 | 0.640 | 0.640 | True (72 steps) | 0.000 / 0.000 | 0.000 / 0.000 |
| 8 | 0.260 | 0.260 | True (155 steps) | 0.000 / 0.000 | 0.000 / 0.000 |
| 9 | 0.710 | 0.710 | True (52 steps) | 0.000 / 0.000 | 0.000 / 0.000 |
| **Mean (0-9)** | **0.576** | **0.576** | **10/10 exact (`0.576 == 0.576`)** | **0.000 == 0.000** | **0.000 == 0.000** |

## Offline Verification Command

```bash
PYTHONPATH=. CANARY_OFFLINE=1 /tmp/fleet-silas/shared/agent-arena-venv/bin/pytest -q tests/test_v16_horizon_escalation.py
```
