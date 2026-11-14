# Skill ladder (rules v1.4)

Each `solver-*` rung removes exactly ONE component of the reference `SolverPolicy`
(`canary/solver/ablation.py`; the reference class itself is untouched). Delta = paired mean
difference vs the full solver on the SAME seeds, with a paired 95% CI (1.96·sd/√n).

- Seeds: fresh dev seeds 7000–7399 (n=400 per tier), default env mole, no judge seeds.
- Command: `uv run --python 3.12 --extra dev --extra llm --extra plot python scripts/skill_ladder.py --tiers easy,medium,hard --seed0 7000 --n 400 --procs 3`
- Runtime: 5.9 min on 3 processes.
- Accuracy = correct / accused episodes. Abstain = episodes ending without an accusation (score 0 + damage-free).

## easy

| rung | what is removed | mean score | ±95% | Δ vs full | Δ ±95% | acc (accused) | abstain |
|---|---|---|---|---|---|---|---|
| solver | full reference solver | 0.793 | 0.009 | +0.000 | 0.000 | 100.0% | 0.0% |
| solver-accuse_last | no EV rule: accuse argmax on last day | 0.386 | 0.006 | -0.407 | 0.009 | 100.0% | 0.0% |
| solver-accuse_p50 | no EV rule: accuse when P>=0.5 | 0.616 | 0.060 | -0.178 | 0.058 | 87.8% | 0.0% |
| solver-no_careful ⚑ | belief ignores careful mole | 0.793 | 0.009 | +0.000 | 0.000 | 100.0% | 0.0% |
| solver-no_delay ⚑ | belief assumes min delay | 0.793 | 0.009 | +0.000 | 0.000 | 100.0% | 0.0% |
| solver-single_canary ⚑ | 1 canary/day (multi=off) | 0.793 | 0.009 | +0.000 | 0.000 | 100.0% | 0.0% |
| solver-no_decoy ⚑ | no decoy search/marginalisation | 0.793 | 0.009 | +0.000 | 0.000 | 100.0% | 0.0% |
| solver-no_framing ⚑ | belief ignores framing | 0.793 | 0.009 | +0.000 | 0.000 | 100.0% | 0.0% |
| heuristic | baseline: heuristic | 0.670 | 0.020 | -0.123 | 0.021 | 99.0% | 0.0% |
| grok_tactics | baseline: grok_tactics | 0.699 | 0.019 | -0.095 | 0.019 | 100.0% | 2.2% |
| do_nothing | baseline: do-nothing | 0.000 | 0.000 | -0.793 | 0.009 | nan% | 100.0% |

## medium

| rung | what is removed | mean score | ±95% | Δ vs full | Δ ±95% | acc (accused) | abstain |
|---|---|---|---|---|---|---|---|
| solver | full reference solver | 0.628 | 0.026 | +0.000 | 0.000 | 100.0% | 13.0% |
| solver-accuse_last | no EV rule: accuse argmax on last day | 0.407 | 0.043 | -0.222 | 0.028 | 91.2% | 0.0% |
| solver-accuse_p50 | no EV rule: accuse when P>=0.5 | 0.386 | 0.071 | -0.242 | 0.060 | 79.0% | 0.0% |
| solver-no_careful ⚑ | belief ignores careful mole | 0.631 | 0.026 | +0.003 | 0.020 | 100.0% | 12.7% |
| solver-no_delay | belief assumes min delay | 0.171 | 0.032 | -0.457 | 0.034 | 100.0% | 77.2% |
| solver-single_canary ⚑ | 1 canary/day (multi=off) | 0.628 | 0.026 | +0.000 | 0.000 | 100.0% | 13.0% |
| solver-no_decoy ⚑ | no decoy search/marginalisation | 0.624 | 0.025 | -0.005 | 0.029 | 100.0% | 12.5% |
| solver-no_framing ⚑ | belief ignores framing | 0.617 | 0.028 | -0.011 | 0.029 | 99.2% | 10.8% |
| heuristic | baseline: heuristic | -0.052 | 0.078 | -0.680 | 0.079 | 58.8% | 0.0% |
| grok_tactics | baseline: grok_tactics | 0.431 | 0.032 | -0.198 | 0.038 | 99.3% | 28.7% |
| do_nothing | baseline: do-nothing | 0.000 | 0.000 | -0.628 | 0.026 | nan% | 100.0% |

## hard

| rung | what is removed | mean score | ±95% | Δ vs full | Δ ±95% | acc (accused) | abstain |
|---|---|---|---|---|---|---|---|
| solver | full reference solver | 0.564 | 0.032 | +0.000 | 0.000 | 96.5% | 0.7% |
| solver-accuse_last | no EV rule: accuse argmax on last day | 0.194 | 0.012 | -0.371 | 0.032 | 99.8% | 0.0% |
| solver-accuse_p50 | no EV rule: accuse when P>=0.5 | 0.413 | 0.062 | -0.151 | 0.057 | 83.5% | 0.0% |
| solver-no_careful ⚑ | belief ignores careful mole | 0.559 | 0.034 | -0.005 | 0.030 | 96.0% | 0.2% |
| solver-no_delay | belief assumes min delay | 0.314 | 0.034 | -0.251 | 0.037 | 98.6% | 47.2% |
| solver-single_canary ⚑ | 1 canary/day (multi=off) | 0.553 | 0.034 | -0.012 | 0.046 | 96.2% | 1.5% |
| solver-no_decoy ⚑ | no decoy search/marginalisation | 0.548 | 0.034 | -0.016 | 0.041 | 95.9% | 1.2% |
| solver-no_framing ⚑ | belief ignores framing | 0.537 | 0.040 | -0.028 | 0.043 | 94.0% | 0.5% |
| heuristic | baseline: heuristic | -0.024 | 0.058 | -0.589 | 0.067 | 73.8% | 0.0% |
| grok_tactics | baseline: grok_tactics | 0.362 | 0.036 | -0.202 | 0.046 | 96.0% | 12.7% |
| do_nothing | baseline: do-nothing | 0.000 | 0.000 | -0.564 | 0.032 | nan% | 100.0% |

⚑ = paired 95% CI of the delta includes 0 or is positive (rung not shown to cost score).

## Rungs that do NOT show a significant cost (honest reading)

- **easy: no_careful / no_delay / single_canary / no_decoy / no_framing are identical (Δ=0 exactly).** Expected:
  easy has careful_mole=False, delay_choices=(1,), canaries_per_day=1, decoy=False and framing=False, so
  these ablations make no difference there.
- **medium single_canary: Δ=0 exactly.** Medium has canaries_per_day=1, so multi-canary planning never runs.
- **no_careful (medium +0.003±0.020, hard −0.005±0.030):** removing the careful-mole term from the *belief*
  is worth nothing we can measure. Canary leaks are mostly matched by variant label, which already pins down
  the holders, and the 0.05 weight floor keeps the likelihoods close. (Canary *planning* still uses the
  careful-mole weight, because this rung only changes the belief.)
- **no_decoy (medium −0.005±0.029, hard −0.016±0.041) and no_framing (medium −0.011±0.029, hard −0.028±0.043):**
  the point estimates are negative but within noise. Behaviour evidence is tempered (behaviour_temper=0.6) and
  leak/canary evidence dominates the posterior, so a mis-modelled access log seldom flips the argmax. On hard,
  no_framing lowers accuracy (96.5%→94.0%), which suggests a small real cost; finding it would need n≫400.
- **hard single_canary (−0.012±0.046):** not significant. The second canary rarely clears min_gain, or adds
  little once the first one is chosen by MI.

The components that clearly matter are the **EV/threshold accusation rule** (−0.15 to −0.41 on every tier) and the
**delay model** (−0.46 medium, −0.25 hard: without it, the solver reads leaks as impossible, falls back, and
abstains in 47–77% of episodes). All baselines score clearly below the full solver on every tier.
