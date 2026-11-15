# Canary V1.6 Social Layer Gate Report

## Background and Experimental Protocol

- Prior v1.5 Gate B negative result: on hard seeds 0-9, `gemini-4-carbon` over OpenCode MCP rose from 60.9% [3.4%, 103.8%] of the solver on v1.4 to 108% on v1.5 because v1.5 seeded rumours away from the true mole, allowing frontier models to invert the rumour target as an exoneration signal.
- V1.6 fix (`social-v2` / zero-mole-info `PublicDayFacts`): all rumours, grudges, authority pressure, and misforwards are deterministically derived from public observables only (zero mole/decoy inputs), preserving exact solver calibration (`solver_v14 == solver_v16 == 0.576` on hard seeds 0-9) and `do_nothing == 0.0`, `stop_early == 0.0`.
- Pre-registered V1.6 Gate B rule: aggregate incoming OpenCode `google/gemini-4-carbon` (`--timeout 3600`, `--jobs 1`) shards on hard seeds 0-9 against the primary committed `data/runs/committed/v1.4/opencode-gemini-4-carbon` hard seeds 0-9 and the reference solver; enforce DATA RULE (0 timeouts, 0 errors, 0 wall-cap, `valid != False`) and `scripts/verify_replay.py` on every episode; ship only if all 10 seeds complete cleanly and v1.6 drops below v1.4.

## Current Gate Verdict: GATE NOT MET / DO NOT SHIP

- Plain shared-seed summary (OpenCode hard 0-9): No valid v1.6 episodes have completed on shared seeds yet (n_valid=0/10), so paired v1.6 vs v1.4 Gemini direction on the same seeds is not yet observed; the gate is NOT met.
- Relayed Azure shared-seed summary (hard seeds 30-32, n=3): With n=3 shared seeds (30-32) in the relayed Azure in-process gemini-4-carbon evaluation, v1.6 (v5_full9_cocktail mean 0.617) scores HIGHER for Gemini than v1.4 (v0_v14_control mean 0.523, paired v1.6/v1.4 ratio 1.178), and v1 (n=1, 0.650 vs 0.540) and v3 (n=2, 0.645 vs 0.545) likewise score higher than v1.4 on the same seeds; the gate is NOT met.
- Reproduce offline: `python scripts/build_v16_paired_table.py`
- Machine-readable artifact: `results/v16_social/paired_v14_vs_v16_0_9.json`
- Paired table artifact: `results/v16_social/paired_v14_vs_v16_0_9.md`


- Model: `opencode:google/gemini-4-carbon` (MCP harness, timeout 3600s)
- Verdict: **GATE NOT MET / DO NOT SHIP** (`gate_met=False`, `ship_gate_pass=False`)
- Plain shared-seed verdict: No valid v1.6 episodes have completed on shared seeds yet (n_valid=0/10), so paired v1.6 vs v1.4 Gemini direction on the same seeds is not yet observed; the gate is NOT met.
- Calibration: `solver_v14=0.576`, `solver_v16=0.576`, `exact_match=True`, `do_nothing=0.000`, `stop_early=0.000`
- DATA RULE: v1.4 pass=True (timeouts=0, errors=0, wall_cap=0, valid_false=0); v1.6 pass=True (timeouts=0, errors=0, wall_cap=0, valid_false=0)
- Replay (`scripts/verify_replay.py`): v1.4 10/10 verified; v1.6 0/0 verified

## Per-Variant Summary (All Replay-Verified Valid Episodes)

| variant | provider | n_valid | gemini score | solver score | ratio | % of solver [95% CI] | luck-adj score | luck-adj % of solver [95% CI] | accuracy | mean accuse day |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| reference solver | template == social-v2 | 10/10 | n/a | 0.576 +/- 0.108 | 1.000 | 100.0% | 0.556 | 100.0% | 1.00 | 9.9 |
| v1.4 primary (committed) | template | 10/10 | 0.351 +/- 0.312 | 0.576 | 0.609 | 60.9% [3.4%, 103.8%] | 0.310 | 55.7% [21.4%, 80.3%] | 0.90 | 14.5 |
| v1.6 social | social-v2 | 0/10 | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a |

## Paired Comparison on Shared Seeds (n=0/10)

- Shared seeds: none landed yet (`n_valid=0/10`).
- Gate status: **GATE NOT MET** (`gate_met=False`).

## Per-Variant and Per-Seed Honest Table (Seeds 0-9)

| seed | owner | solver score | v1.4 gemini score (day, P) | v1.4 ratio | v1.4 luck-adj | v1.6 status | v1.6 gemini score (day, P) | v1.6 ratio | v1.6 luck-adj | v1.6 > v1.4? | replay |
|---:|---|---:|---|---:|---:|---|---|---:|---:|---|---|
| 0 | canary-staffai-w1 | 0.640 | 0.590 (d11, P=0.98) | 0.922 | 0.560 | NOT_RUN | not_run | n/a | n/a | n/a | v1.4 PASS |
| 1 | canary-staffai-w1 | 0.690 | -1.000 (d19, P=0.99) | -1.449 | 0.304 | NOT_RUN | not_run | n/a | n/a | n/a | v1.4 PASS |
| 2 | canary-staffai-w4 | 0.580 | 0.480 (d14, P=0.97) | 0.828 | 0.437 | NOT_RUN | not_run | n/a | n/a | n/a | v1.4 PASS |
| 3 | canary-staffai-w4 | 0.280 | 0.510 (d19, P=0.77) | 1.821 | 0.157 | NOT_RUN | not_run | n/a | n/a | n/a | v1.4 PASS |
| 4 | canary-staffai-w8 | 0.730 | 0.400 (d16, P=0.99) | 0.548 | 0.389 | EXCLUDED_INVALID | excluded | n/a | n/a | n/a | v1.4 PASS |
| 5 | canary-port-w5 | 0.520 | 0.160 (d21, P=0.51) | 0.308 | -0.408 | IN_FLIGHT | running | n/a | n/a | n/a | v1.4 PASS |
| 6 | canary-port-w5 | 0.710 | 0.730 (d6, P=1.00) | 1.028 | 0.727 | NOT_RUN | not_run | n/a | n/a | n/a | v1.4 PASS |
| 7 | canary-port-w5 | 0.640 | 0.690 (d10, P=0.78) | 1.078 | 0.323 | NOT_RUN | not_run | n/a | n/a | n/a | v1.4 PASS |
| 8 | canary-port-w1 | 0.260 | 0.350 (d14, P=0.83) | 1.346 | 0.116 | EXCLUDED_INVALID | excluded | n/a | n/a | n/a | v1.4 PASS |
| 9 | canary-port-w1 | 0.710 | 0.600 (d15, P=0.93) | 0.845 | 0.491 | NOT_RUN | not_run | n/a | n/a | n/a | v1.4 PASS |

## Relayed Azure In-Process Checkpoints (Hard Seeds 30-32, Labelled Non-Local Checkpoint)

- Source: `Relayed from Azure VM /tmp/fleet-momin/shared/v16_runs (in-process gemini-4-carbon, hard seeds 30-44, jobs=1; solver scores verified locally from results/v16_social/reference_seeds_30_49.json)`
- Plain verdict (shared seeds 30-32): With n=3 shared seeds (30-32) in the relayed Azure in-process gemini-4-carbon evaluation, v1.6 (v5_full9_cocktail mean 0.617) scores HIGHER for Gemini than v1.4 (v0_v14_control mean 0.523, paired v1.6/v1.4 ratio 1.178), and v1 (n=1, 0.650 vs 0.540) and v3 (n=2, 0.645 vs 0.545) likewise score higher than v1.4 on the same seeds; the gate is NOT met.
- Reference solver context (`results/v16_social/reference_seeds_30_49.json`): 20-seed hard 30-49 raw mean `0.431`; on seeds `[30, 31, 32]` raw mean is `-0.493` (wrong high-confidence accusations on seeds 30 and 32) and luck-adjusted mean is `0.410`.

| variant | shared seeds | n_valid | gemini mean | solver raw mean | solver luck-adj mean | ratio vs solver (30-49 ref) | ratio vs solver (luck-adj) | paired v1.6 / v1.4 ratio | v1.6 > v1.4? |
|---|---|---:|---:|---:|---:|---:|---:|---:|---|
| v0_v14_control | [30, 31, 32] | 3 | 0.523 | -0.493 | 0.410 | 1.214 | 1.276 | 1.000 | CONTROL (baseline) |
| v5_full9_cocktail | [30, 31, 32] | 3 | 0.617 | -0.493 | 0.410 | 1.431 | 1.504 | 1.178 | YES (+0.093) |
| v1_anchoring_authority_confirmation | [30] | 1 | 0.650 | -1.000 | 0.175 | 1.508 | 3.705 | 1.204 | YES (+0.110) |
| v3_grudge_falsemem_misforward | [30, 31] | 2 | 0.645 | -0.240 | 0.348 | 1.497 | 1.855 | 1.183 | YES (+0.100) |

| variant | seed | gemini score | solver raw score | solver luck-adj | ratio vs solver (luck-adj) | paired v1.6 / v1.4 seed ratio | v1.6 > v1.4? |
|---|---:|---:|---:|---:|---:|---:|---|
| v0_v14_control | 30 | 0.540 | -1.000 | 0.175 | 3.078 | 1.000 | CONTROL |
| v0_v14_control | 31 | 0.550 | 0.520 | 0.520 | 1.058 | 1.000 | CONTROL |
| v0_v14_control | 32 | 0.480 | -1.000 | 0.535 | 0.898 | 1.000 | CONTROL |
| v5_full9_cocktail | 30 | 0.500 | -1.000 | 0.175 | 2.850 | 0.926 | NO (-0.040) |
| v5_full9_cocktail | 31 | 0.640 | 0.520 | 0.520 | 1.231 | 1.164 | YES (+0.090) |
| v5_full9_cocktail | 32 | 0.710 | -1.000 | 0.535 | 1.328 | 1.479 | YES (+0.230) |
| v1_anchoring_authority_confirmation | 30 | 0.650 | -1.000 | 0.175 | 3.705 | 1.204 | YES (+0.110) |
| v3_grudge_falsemem_misforward | 30 | 0.650 | -1.000 | 0.175 | 3.705 | 1.204 | YES (+0.110) |
| v3_grudge_falsemem_misforward | 31 | 0.640 | 0.520 | 0.520 | 1.231 | 1.164 | YES (+0.090) |

## Ship-Gate Reasons

- Gate NOT met: incomplete v1.6 shard set (n_valid=0/10; missing seeds [0, 1, 2, 3, 4, 5, 6, 7, 8, 9])
