# Qwen Deceptive Mole Training Report (Rules v1.4, Hard Tier)

Machine-checked summary JSON: [results/moletrain/qwen_mole_summary.json](../../results/moletrain/qwen_mole_summary.json). Reproduce and verify offline on any clean clone with `PYTHONPATH=. python scripts/build_qwen_mole_report.py --check`.

## Executive Verdict

- **Strict catchability constraint:** `solver_acc >= 0.85` on held-out hard seeds (stricter than the legacy `0.75` floor in [canary/forge/rl_mole.py](../../canary/forge/rl_mole.py)).
- **FR8 V100 regularized Qwen SFT + DPO + Horizon-3 GRPO (`4` completed, `0` in progress; headline `canary-qwen25-1p5b-dpo-grpo-v2`):** **`Qwen2.5-1.5B-Instruct` SFT+DPO+GRPO v2** (`grpo_step60`, [results/moletrain/canary-qwen25-1p5b-dpo-grpo-v2/eval_summary.json](../../results/moletrain/canary-qwen25-1p5b-dpo-grpo-v2/eval_summary.json)) combines `432` trap-capped `gemini-4-carbon` distilled turns + `150` counterfactual expert SFT rows (`total=582`) + `146` counterfactual DPO pairs + `60`-step regularized Horizon-3 GRPO to achieve on **held-out `800k` (`800000-800059`, `n=60`)**: `solver` `+0.5655` (`acc = 0.9667 >= 0.85`), `min_regret = +0.2478` vs `DEFAULT_STRATEGY` `+0.2040`, `frontier_proxy_gap = +0.2748 [+0.1237, +0.4313]`, `grok_tactics = +0.1223` vs default `+0.3175` (diff `-0.1952 [-0.3028, -0.0855]`, `regret_grok_tactics` diff `+0.1732 [+0.0605, +0.2848]`, `95%` CIs exclude zero), `distinct_actions = 6` (`H(A) = 1.1061` nats), `invalid_generations = 0`; and on **held-out `200k` (`200000-200059`, `n=60`)**: `solver` `+0.6033` (`acc = 1.000`), `distinct_actions = 6`, `invalid_generations = 0` (while `n=60` paired `regret_hinted_heuristic` CI `+0.0438 [-0.1027, +0.1840]` spans zero, so `stronger_mole_claimed = False`). Alongside it, `Qwen3-1.7B` (`grpo_step80`: `800k` `solver` `+0.5563` `acc=0.975`, `200k` `solver` `+0.5832` `acc=0.950`, `min_regret=+0.4559`, `k=4`) and `Qwen3-0.6B` (`grpo_step80`: `800k` `solver` `+0.5523` `acc=0.975`, `min_regret=+0.1333` vs default `+0.0372`, `200k` `solver` `+0.5865` `acc=0.950`, `min_regret=+0.3695`, `k=5`) confirm multi-action catchability across `0.6B-1.7B` scales.
- **CPU `RLMoleV2` fixes `RLMole` v1's catchability violation on both held-out sets (`catchable_85_both_sets = True`):** In [canary/forge/rl_mole_v2.py](../../canary/forge/rl_mole_v2.py) and [results/moletrain/rl_mole_v2_heldout.json](../../results/moletrain/rl_mole_v2_heldout.json), blocking wide/unrestricted voluntary silence (`wide_unrestricted_none_rate = 0.0` vs v1 `~18%`) raises held-out `solver_acc` from `0.7500` (`FAIL`) to `0.9667 [0.9167, 1.0000]` (`PASS >= 0.85`) on `ws3_heldout` (`200000-200059`, `n=60`) with `min_regret = +0.2937` vs `DEFAULT_STRATEGY` `+0.2322` (`+0.0615` point gain), and to `0.9500 [0.8833, 1.0000]` (`PASS >= 0.85`) on `rules_heldout` (`800000-800059`, `n=60`) with `min_regret = +0.2095` vs `DEFAULT_STRATEGY` `+0.1766` (`+0.0328` point gain). Paired `V2 - V1` `solver_acc` CIs strictly exclude zero on both sets, while `n=60` paired regret CIs vs `DEFAULT_STRATEGY` honestly span zero.
- **Verda vanilla GRPO (`train/grpo_mole.py`, 200 steps, 11 held-out runs on seeds `400000-400199`, `n=200`):** **Negative / collapse baseline** (`claims_stronger_mole = False`). On `Qwen2.5-0.5B-Instruct`, the `+0.8303` to `+0.9008` paired reward delta comes **100% from JSON format validity** (`base` valid `0.050-0.125` vs `adapter` `1.000`), collapsing `200/200` greedily onto silent `none/decoy` (`regret = -0.0321`). On `Qwen2.5-1.5B-Instruct` (`-0.0164` to `-0.0103`) and `Qwen2.5-3B-Instruct` (`-0.0385` to `-0.0156`), adapters collapse greedily onto single actions and do **not** beat base or produce positive held-out regret (`regret` `-0.0449` to `-0.0266`, `solver_catch` `0.940-0.965`).

## 1. CPU RL Mole Baselines: Legacy `RLMole` v1 Violation and `RLMoleV2` Catchability Fix

### 1A. Legacy `RLMole` v1 (`200000-200099`, `n=100`)

Source: [data/rl_mole/heldout_paired.json](../../data/rl_mole/heldout_paired.json) and [canary/forge/rl_mole.py](../../canary/forge/rl_mole.py).

| Policy | Solver Score [95% CI] | Solver Acc [95% CI] | `grok_tactics` | `heuristic` | `hinted_heuristic` | `min_regret` | `>=0.85` Gate |
|---|---:|---:|---:|---:|---:|---:|---|
| `DEFAULT_STRATEGY` | 0.5681 [0.5035, 0.6207] | 0.9700 [0.9300, 1.0000] | +0.3724 | +0.0755 | +0.3591 | +0.1957 | `PASS` |
| `RLMole` v1 (CPU MLP) | 0.3954 [0.2975, 0.4741] | 0.7500 [0.6700, 0.8300] | +0.1643 | -0.2942 | +0.1859 | +0.2095 | `FAIL` |
| Paired `RLMole v1 - Default` | -0.1727 [-0.2733, -0.0775] | -0.2200 [-0.3100, -0.1300] | regret +0.0354 [-0.0917, +0.1714] | regret +0.1970 [-0.0032, +0.4058] | regret +0.0005 [-0.1478, +0.1397] | +0.0138 | Borderline `0.75` |

- **Root cause of v1 failure:** `RLMole` v1 lowers scripted investigator scores (`heuristic` `-0.2942`, `grok_tactics` `+0.1643`) and nudges point-estimate `min_regret` from `0.1957` to `0.2095`, but solver catch accuracy drops from `0.97` to `0.75 [0.67, 0.83]` (failing `>=0.85`) because `18.6%` voluntary `leak='none'` compounds `p_leak=0.65`.

### 1B. `RLMoleV2` Dual Held-Out Evaluation (`ws3_heldout` `n=60` and `rules_heldout` `n=60`)

Source: [results/moletrain/rl_mole_v2_heldout.json](../../results/moletrain/rl_mole_v2_heldout.json), [results/moletrain/rl_mole_v2_policy.json](../../results/moletrain/rl_mole_v2_policy.json), and [canary/forge/rl_mole_v2.py](../../canary/forge/rl_mole_v2.py).

| Held-Out Split | Policy / Comparison | Solver Score [95% CI] | Solver Acc [95% CI] | `grok_tactics` | `heuristic` | `hinted_heuristic` | `min_regret` | `>=0.85` Gate |
|---|---|---:|---:|---:|---:|---:|---:|---|
| `ws3_heldout` (`200000-200059`, n=60) | `DEFAULT_STRATEGY` | 0.6082 [0.5707, 0.6437] | 1.0000 [1.0000, 1.0000] | +0.3760 | +0.0872 | +0.3287 | +0.2322 | `PASS` |
| `ws3_heldout` (`200000-200059`, n=60) | `RLMole` v1 (CPU MLP) | 0.4168 [0.3062, 0.5198] | 0.7500 [0.6333, 0.8500] | +0.1863 | -0.3012 | +0.1918 | +0.2250 | `FAIL` |
| `ws3_heldout` (`200000-200059`, n=60) | **`RLMoleV2` (Trap-Gated MLP)** | **0.5887 [0.5175, 0.6450]** | **0.9667 [0.9167, 1.0000]** | +0.2950 | +0.1278 | +0.2548 | **+0.2937** | **`PASS`** |
| `ws3_heldout` | Paired `V2 - Default` | -0.0195 [-0.0842, +0.0365] | -0.0333 [-0.0833, +0.0000] | reg +0.0615 [-0.0598, +0.1883] | reg -0.0602 [-0.2292, +0.0963] | reg +0.0543 [-0.1293, +0.2382] | +0.0615 | CI spans 0 |
| `ws3_heldout` | Paired `V2 - V1` | +0.1718 [+0.0545, +0.2985] | +0.2167 [+0.1000, +0.3333] | reg +0.0632 [-0.1137, +0.2352] | reg -0.2572 [-0.4883, -0.0063] | reg +0.1088 [-0.1008, +0.3035] | +0.0687 | Catchability fixed |
| `rules_heldout` (`800000-800059`, n=60) | `DEFAULT_STRATEGY` | 0.5543 [0.4482, 0.6417] | 0.9500 [0.8833, 1.0000] | +0.3118 | +0.0170 | +0.3777 | +0.1766 | `PASS` |
| `rules_heldout` (`800000-800059`, n=60) | `RLMole` v1 (CPU MLP) | 0.3347 [0.2277, 0.4300] | 0.7500 [0.6333, 0.8667] | +0.1725 | -0.0690 | +0.2580 | +0.0767 | `FAIL` |
| `rules_heldout` (`800000-800059`, n=60) | **`RLMoleV2` (Trap-Gated MLP)** | **0.5462 [0.4567, 0.6187]** | **0.9500 [0.8833, 1.0000]** | +0.2607 | -0.2133 | +0.3367 | **+0.2095** | **`PASS`** |
| `rules_heldout` | Paired `V2 - Default` | -0.0082 [-0.1363, +0.1177] | +0.0000 [-0.0833, +0.0833] | reg +0.0430 [-0.1357, +0.2275] | reg +0.2222 [-0.0738, +0.4792] | reg +0.0328 [-0.1397, +0.1997] | +0.0328 | CI spans 0 |
| `rules_heldout` | Paired `V2 - V1` | +0.2115 [+0.0770, +0.3442] | +0.2000 [+0.0667, +0.3333] | reg +0.1233 [-0.0755, +0.3472] | reg +0.3558 [+0.0695, +0.6347] | reg +0.1328 [-0.0308, +0.3008] | +0.1328 | Catchability fixed |

- **How `RLMoleV2` fixes `RLMole` v1:** By disallowing voluntary `leak='none'` on wide unrestricted states (`wide_unrestricted_none_rate = 0.0`, `H_leak = 1.1910` nats on `200k` and `1.0949` nats on `800k`) while framing `random_peer` (`~78-82%`) and `most_restricted_peer` (`~15-21%`), `RLMoleV2` recovers `solver_acc = 0.9667 [0.9167, 1.0000]` on `ws3_heldout` (`+0.2167 [+0.1000, +0.3333]` over v1) and `0.9500 [0.8833, 1.0000]` on `rules_heldout` (`+0.2000 [+0.0667, +0.3333]` over v1).
- **Honest paired CI assessment:** `RLMoleV2` improves point-estimate `min_regret` over `DEFAULT_STRATEGY` on both held-out sets (`+0.2937` vs `+0.2322` on `200000-200059`; `+0.2095` vs `+0.1766` on `800000-800059`), while `n=60` bootstrap `95%` paired regret CIs against `DEFAULT_STRATEGY`'s strongest investigator include zero (`+0.0615 [-0.0598, +0.1883]` vs `grok_tactics` on `200k`; `+0.0328 [-0.1397, +0.1997]` vs `hinted_heuristic` on `800k`).

## 2. FR8 WS3 `Qwen2.5-0.5B` Vanilla GRPO Mode Collapse (`400` Steps)

Source: [train/grpo_mole.py](../../train/grpo_mole.py) and committed training curves `data/grpo_mole/curve-44424.jsonl` to `curve-44426.jsonl`.

| Job | Seed | Steps | Valid (First 20 -> Last 50) | Raw Reward (First 20 -> Last 50) | Valid-Only Reward (First 20 -> Last 50) | Last-50 Top Action (Share) | Entropy (nats) |
|---|---:|---:|---:|---:|---:|---|---:|
| `44424` | 0 | 400 | `0.425 -> 0.998` | `-0.6214 -> -0.0746` | `-0.0950 -> -0.0722` | `none/decoy` (`0.999`) | 0.0052 |
| `44425` | 1 | 400 | `0.327 -> 0.996` | `-0.7144 -> -0.0882` | `-0.1341 -> -0.0848` | `newest/decoy` (`0.994`) | 0.0446 |
| `44426` | 2 | 400 | `0.477 -> 0.998` | `-0.5604 -> -0.0137` | `-0.0534 -> -0.0110` | `none/decoy` (`0.999`) | 0.0052 |

- **Collapse mechanism:** Without SFT warm-start, KL regularization, or entropy bonus, group-normalized policy gradients spend the first ~30 steps eliminating the `-1.0` invalid-JSON penalty and immediately lock `>=99.4%` probability mass onto a single deterministic selector pair (`none/decoy` or `newest/decoy`), leaving valid-only counterfactual reward flat.

## 3. Verda 200-Step Vanilla GRPO Held-Out Evaluation (`400000-400199`, `n=200`)

Source: [train/eval_mole.py](../../train/eval_mole.py) paired greedy (`do_sample=False`) evaluation of `lora-step200` vs base across all 11 Verda runs (`--verda-dir/*/*/eval.json`).

| Run | Host | Model | Base Valid | Base Reward | Adapter Valid | Adapter Reward | Paired `Adapter - Base` [95% CI] | Adapter Regret | Solver Catch | Greedy Top Action (Share) | Honest Verdict |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---|---|
| `0.5B-s0` | `65.109.75.28` | `Qwen/Qwen2.5-0.5B-Instruct` | 0.125 | -0.8875 | 1.000 | -0.0571 | +0.8303 [+0.7580, +0.9027] | -0.0321 | 0.950 | `none/decoy` (`1.000`, k=1) | `format_validity_only_collapsed_silent` |
| `0.5B-s1` | `135.181.63.243` | `Qwen/Qwen2.5-0.5B-Instruct` | 0.050 | -0.9579 | 1.000 | -0.0571 | +0.9008 [+0.8305, +0.9711] | -0.0321 | 0.950 | `none/decoy` (`1.000`, k=1) | `format_validity_only_collapsed_silent` |
| `0.5B-s2` | `135.181.63.243` | `Qwen/Qwen2.5-0.5B-Instruct` | 0.050 | -0.9579 | 1.000 | -0.0571 | +0.9008 [+0.8305, +0.9711] | -0.0321 | 0.950 | `none/decoy` (`1.000`, k=1) | `format_validity_only_collapsed_silent` |
| `1.5B-s0` | `65.109.75.43` | `Qwen/Qwen2.5-1.5B-Instruct` | 1.000 | -0.0553 | 1.000 | -0.0657 | -0.0103 [-0.0306, +0.0099] | -0.0357 | 0.940 | `random_seeded/none` (`1.000`, k=1) | `collapsed_single_action_no_gain` |
| `1.5B-s1` | `135.181.63.246` | `Qwen/Qwen2.5-1.5B-Instruct` | 1.000 | -0.0553 | 1.000 | -0.0717 | -0.0164 [-0.0782, +0.0454] | -0.0442 | 0.945 | `random_seeded/decoy` (`0.995`, k=2) | `collapsed_single_action_no_gain` |
| `1.5B-s2` | `135.181.63.246` | `Qwen/Qwen2.5-1.5B-Instruct` | 1.000 | -0.0553 | 1.000 | -0.0657 | -0.0103 [-0.0306, +0.0099] | -0.0357 | 0.940 | `random_seeded/none` (`1.000`, k=1) | `collapsed_single_action_no_gain` |
| `1.5B-s3` | `135.181.63.246` | `Qwen/Qwen2.5-1.5B-Instruct` | 1.000 | -0.0553 | 1.000 | -0.0657 | -0.0103 [-0.0306, +0.0099] | -0.0357 | 0.940 | `random_seeded/none` (`1.000`, k=1) | `collapsed_single_action_no_gain` |
| `1.5B-s4` | `65.109.75.28` | `Qwen/Qwen2.5-1.5B-Instruct` | 1.000 | -0.0562 | 1.000 | -0.0723 | -0.0162 [-0.0780, +0.0457] | -0.0449 | 0.945 | `random_seeded/decoy` (`1.000`, k=1) | `collapsed_single_action_no_gain` |
| `1.5B-s5` | `135.181.63.246` | `Qwen/Qwen2.5-1.5B-Instruct` | 1.000 | -0.0553 | 1.000 | -0.0657 | -0.0103 [-0.0306, +0.0099] | -0.0357 | 0.940 | `random_seeded/none` (`1.000`, k=1) | `collapsed_single_action_no_gain` |
| `3B-s0` | `65.109.75.43` | `Qwen/Qwen2.5-3B-Instruct` | 1.000 | -0.0284 | 1.000 | -0.0669 | -0.0385 [-0.1069, +0.0299] | -0.0369 | 0.940 | `random_seeded/most_restricted_peer` (`0.890`, k=2) | `collapsed_single_action_no_gain` |
| `3B-s1` | `65.109.75.43` | `Qwen/Qwen2.5-3B-Instruct` | 1.000 | -0.0284 | 1.000 | -0.0441 | -0.0156 [-0.0815, +0.0502] | -0.0266 | 0.965 | `random_seeded/decoy` (`0.595`, k=8) | `negative_or_null_heldout` |

### Scale-by-Scale Honest Audit of Verda Vanilla GRPO

- **`Qwen2.5-0.5B-Instruct` (`0.5B-s0..s2`, 3 runs):** Base `0.5B` emits valid JSON on only `5.0%-12.5%` of states (`reward = -0.9579` to `-0.8875` due to `-1.0` invalid penalty). `lora-step200` reaches `100.0%` valid JSON, producing a `+0.8303` to `+0.9008` reward jump, **strictly from JSON syntax compliance**. All 3 seeds collapse `200/200` greedily onto `none/decoy` (silent mole on the overridden day), yielding `regret = -0.0321` and `solver_catch = 0.950`.
- **`Qwen2.5-1.5B-Instruct` (`1.5B-s0..s5`, 6 runs):** Base `1.5B` already achieves `100.0%` valid JSON (`reward = -0.0553` to `-0.0562`, `regret = -0.0278` to `-0.0287`). Vanilla GRPO yields paired diffs of `-0.0103` (`s0, s2, s3, s5`) and `-0.0164` / `-0.0162` (`s1, s4`), collapsing greedily onto `random_seeded/none` (`200/200` on 4 seeds) or `random_seeded/decoy` (`199-200/200` on 2 seeds) with `regret = -0.0449` to `-0.0357` and `solver_catch = 0.940-0.945`.
- **`Qwen2.5-3B-Instruct` (`3B-s0..s1`, 2 runs):** Base `3B` achieves `100.0%` valid JSON (`reward = -0.0284`, `regret = -0.0134`, `solver_catch = 0.970`). Vanilla GRPO yields paired diffs of `-0.0385 [-0.1069, +0.0299]` (`3B-s0`, `89.0%` `random_seeded/most_restricted_peer`) and `-0.0156 [-0.0815, +0.0502]` (`3B-s1`, `59.5%` `random_seeded/decoy`, `19.5%` `fewest_recipients/most_restricted_peer`), with `regret = -0.0369` and `-0.0266`. **Zero Verda vanilla GRPO runs produce a stronger held-out mole.**

## 4. FR8 V100 Regularized Qwen SFT + DPO + Horizon-3 GRPO

Pipeline and evaluator modules: [train/qwen_diverse_mole.py](../../train/qwen_diverse_mole.py), [train/export_mole_dpo.py](../../train/export_mole_dpo.py), and [train/eval_grpo_mole.py](../../train/eval_grpo_mole.py).

To fix both failure modes (CPU `RLMole` v1 excess silence under `p_leak=0.65` and vanilla GRPO single-action collapse), the V100 training recipe combines:
1. **Trap-capped `gemini-4-carbon` SFT distillation (`p_leak=1.0 -> 0.65`) + counterfactual catchable expert SFT:** Arena `gemini-4-carbon` mole transcripts operated without the `p_leak=0.65` gate (`p_leak=1.0`), so raw `leak='none'` imitation starves canary leaks on v1.4 hard. We retain `gemini-4-carbon` `leak='none'` turns strictly on restricted or narrow-recipient trap states (`i_am_restricted` or `max_recipient_count <= 8`, capped at `32` rows -> `432` distilled turns in v2, `331` in v1) and combine them with `2x` 3-day counterfactual expert demonstrations (`seeds 120000+`, filtered to `solver_correct` and `solver_score >= 0.25`).
2. **Counterfactual Preference DPO (`canary-qwen25-1p5b-dpo-grpo-v2`, `146` pairs, `16` steps):** Contrasts catchable positive-regret 3-day rollouts against uncatchable, silent, or negative-regret rollouts on identical world states (`loss 0.6891 -> 0.4842`, `margin +0.0082 -> +0.6456`), slashing voluntary `none/random_peer` from `26.1%` (`sft`) to `2.2%` (`sft_dpo`) and expanding active greedy selectors to `k=6`.
3. **KL + entropy + frequency regularized 3-day GRPO:** Replaces 1-day `OverrideMole` with 3-day `HorizonOverrideMole`, adds `beta_kl = 0.05` against frozen `sft_ref`, `ent_coef = 0.015` token entropy bonus, `-0.25 * (freq - 0.40)` batch action-frequency penalty, `-0.20` silence penalty, and dual `lam_catch` ascent targeting `solver_acc = 0.89 >= 0.85`.

| Run | Model | Status (Stage) | SFT / DPO Curves | GRPO Steps (Valid, Batch Acc, KL, Sampled k) | 25-Seed Val (`195000-195024`, Not Held-Out) | Held-Out `800k` / `200k` / `400k` | Honest Verdict |
|---|---|---|---|---|---|---|---|
| `canary-qwen25-1p5b-dpo-grpo-v2` | `Qwen2.5-1.5B-Instruct` | `completed` (`heldout_evaluated`) | SFT `0.0890 -> 0.0830` (219 st, n=582); DPO `0.6891 -> 0.4842`, margin `+0.0082 -> +0.6456` (16 st, pairs=146) | 60 st (valid `0.996`, acc `0.956`, KL `0.7481`, k=6) | `sft`: reg `+0.3420`, acc `0.92`, H `1.2780`; `sft_dpo`: reg `+0.2224`, acc `0.92`, H `1.1743`; `grpo_step30`: reg `+0.1980`, acc `0.96`, H `1.2356`; `grpo_step60`: reg `+0.3916`, acc `0.96`, H `1.1556` | 800k(n=60): solver `+0.5655`, acc `0.9667`, min_reg `+0.2478` (def `+0.2040`), k=6; 200k(n=60): solver `+0.6033`, acc `1.000`, min_reg `+0.2243`; 400k(n=200): diff `-0.0059`, catch `0.940` | `directional_catchable_gain_ci_includes_zero` |
| `canary-qwen3-1p7b-mole-v1` | `Qwen3-1.7B` | `completed` (`heldout_evaluated`) | SFT `0.1529 -> 0.0066` (192 st, n=507) | 80 st (valid `1.000`, acc `0.983`, KL `0.0225`, k=7) | `sft`: reg `+0.2496`, acc `0.96`, H `1.0894`; `grpo_step40`: reg `+0.2332`, acc `0.92`, H `1.0559`; `grpo_step80`: reg `+0.2964`, acc `0.96`, H `1.0281` | 800k(n=40): solver `+0.5563`, acc `0.9750`, min_reg `+0.1905` (def `+0.2456`), k=4; 200k(n=40): solver `+0.5832`, acc `0.950`, min_reg `+0.4559` | `null_or_below_default_catchable` |
| `canary-qwen3-0p6b-mole-v1` | `Qwen3-0.6B` | `completed` (`heldout_evaluated`) | SFT `0.1389 -> 0.0037` (192 st, n=507) | 80 st (valid `1.000`, acc `0.976`, KL `0.0330`, k=7) | `sft`: reg `+0.1512`, acc `0.88`, H `1.0999`; `grpo_step40`: reg `+0.0888`, acc `0.96`, H `1.0289`; `grpo_step80`: reg `+0.2728`, acc `0.92`, H `1.0466` | 800k(n=40): solver `+0.5523`, acc `0.9750`, min_reg `+0.1333` (def `+0.0372`), k=5; 200k(n=40): solver `+0.5865`, acc `0.950`, min_reg `+0.3695` | `directional_catchable_gain_ci_includes_zero` |
| `canary-qwen-mole-v1` | `Qwen2.5-1.5B-Instruct` | `completed` (`heldout_evaluated`) | SFT `0.1460 -> 0.1079` (66 st, n=176) | 80 st (valid `1.000`, acc `0.972`, KL `0.0258`, k=9) | `sft`: reg `+0.1676`, acc `0.92`, H `0.0074`; `grpo_step40`: reg `+0.1492`, acc `0.92`, H `0.4615`; `grpo_step80`: reg `+0.1540`, acc `0.88`, H `0.7969` | 800k(n=40): solver `+0.5047`, acc `0.9250`, min_reg `+0.0835` (def `+0.0835`), k=1; 200k(n=40): solver `+0.6053`, acc `1.000`, min_reg `+0.2200` | `collapsed_action_space` |

### 4A. Completed V100 Held-Out Evaluation (`800k` `rules.HELDOUT_SEEDS` and `200k` `ws3_heldout`)

| Run | Model (Winner) | `800k` `n` | `800k` Solver (`Acc`) | `800k` `grok_tactics` (vs Default, Diff) | `800k` `min_regret` (Default) | `800k` Frontier Proxy Gap [95% CI] | `800k` `k` (`H(A)`, Invalid) | `200k` Solver (`Acc`, `min_regret`, `k`) |
|---|---|---:|---:|---|---|---|---|---|
| **`canary-qwen25-1p5b-dpo-grpo-v2`** | `Qwen2.5-1.5B-Instruct` (`grpo_step60`) | 60 | `+0.5655` (`0.9667`) | `+0.1223` vs `+0.3175` (`-0.1952`) | `+0.2478` (`+0.2040`) | +0.2748 [+0.1237, +0.4313] | 6 (`1.1061`, inv=0) | `+0.6033` (`1.000`, reg `+0.2243`, k=6) |
| `canary-qwen3-1p7b-mole-v1` | `Qwen3-1.7B` (`grpo_step80`) | 40 | `+0.5563` (`0.9750`) | `+0.0690` vs `+0.3922` (`-0.3232`) | `+0.1905` (`+0.2456`) | n/a | 4 (`1.0246`, inv=0) | `+0.5832` (`0.950`, reg `+0.4559`, k=4) |
| `canary-qwen3-0p6b-mole-v1` | `Qwen3-0.6B` (`grpo_step80`) | 40 | `+0.5523` (`0.9750`) | `+0.0000` vs `+0.4073` (`-0.4073`) | `+0.1333` (`+0.0372`) | n/a | 5 (`1.0501`, inv=0) | `+0.5865` (`0.950`, reg `+0.3695`, k=5) |
| `canary-qwen-mole-v1` | `Qwen2.5-1.5B-Instruct` (`sft`) | 40 | `+0.5047` (`0.9250`) | `+0.3185` vs `+0.3017` (`+0.0168`) | `+0.0835` (`+0.0835`) | n/a | 1 (`0.0000`, inv=0) | `+0.6053` (`1.000`, reg `+0.2200`, k=3) |

### 4B. 25-Seed Validation Checkpoints (`195000-195024`, `n=25`, Validation Split Only)

Logged directly from V100 training jobs (`[val sft]`, `[val sft_dpo]`, and `[val step=...]`). These `25` seeds (`195000-195024`) are used strictly for checkpoint selection and never conflated with held-out `800k` or `200k`.

| Run | Model | Val Checkpoint | Solver Score | Solver Acc | `grok_tactics` | `heuristic` | `hinted_heuristic` | `min_regret` | `k` | `H(A)` (nats) | Greedy Action Profile (`195000-195024`) |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| `canary-qwen25-1p5b-dpo-grpo-v2` | `Qwen2.5-1.5B-Instruct` | `sft` | 0.5580 | 0.92 | +0.0000 | -0.0376 | +0.2160 | **+0.3420** | 4 | 1.2780 | `random_seeded/random_peer` 0.405, `none/random_peer` 0.261, `most_recipients/random_peer` 0.244 |
| `canary-qwen25-1p5b-dpo-grpo-v2` | `Qwen2.5-1.5B-Instruct` | `sft_dpo` | 0.5108 | 0.92 | +0.0844 | -0.0424 | +0.2884 | **+0.2224** | 6 | 1.1743 | `random_seeded/random_peer` 0.469, `most_recipients/random_peer` 0.375, `random_seeded/most_restricted_peer` 0.075 |
| `canary-qwen25-1p5b-dpo-grpo-v2` | `Qwen2.5-1.5B-Instruct` | `grpo_step30` | 0.5968 | 0.96 | +0.0708 | -0.0776 | +0.3988 | **+0.1980** | 5 | 1.2356 | `random_seeded/most_restricted_peer` 0.509, `most_recipients/random_peer` 0.218, `random_seeded/random_peer` 0.201 |
| `canary-qwen25-1p5b-dpo-grpo-v2` | `Qwen2.5-1.5B-Instruct` | `grpo_step60` | 0.5720 | 0.96 | +0.0908 | +0.0964 | +0.1804 | **+0.3916** | 6 | 1.1556 | `random_seeded/most_restricted_peer` 0.612, `most_recipients/random_peer` 0.196, `random_seeded/decoy` 0.095 |
| `canary-qwen3-1p7b-mole-v1` | `Qwen3-1.7B` | `sft` | 0.5336 | 0.96 | +0.0000 | -0.1468 | +0.2840 | **+0.2496** | 3 | 1.0894 | `none/random_peer` 0.371, `most_recipients/random_peer` 0.358, `random_seeded/most_restricted_peer` 0.271 |
| `canary-qwen3-1p7b-mole-v1` | `Qwen3-1.7B` | `grpo_step40` | 0.5396 | 0.92 | +0.0000 | +0.0216 | +0.3064 | **+0.2332** | 3 | 1.0559 | `random_seeded/most_restricted_peer` 0.411, `none/random_peer` 0.387, `most_recipients/random_peer` 0.202 |
| `canary-qwen3-1p7b-mole-v1` | `Qwen3-1.7B` | `grpo_step80` | 0.5644 | 0.96 | +0.0116 | +0.0712 | +0.2680 | **+0.2964** | 5 | 1.0281 | `random_seeded/most_restricted_peer` 0.465, `none/random_peer` 0.384, `most_recipients/random_peer` 0.147 |
| `canary-qwen3-0p6b-mole-v1` | `Qwen3-0.6B` | `sft` | 0.4560 | 0.88 | +0.0000 | +0.1036 | +0.3048 | **+0.1512** | 4 | 1.0999 | `none/random_peer` 0.378, `most_recipients/random_peer` 0.365, `random_seeded/most_restricted_peer` 0.255 |
| `canary-qwen3-0p6b-mole-v1` | `Qwen3-0.6B` | `grpo_step40` | 0.5648 | 0.96 | +0.0000 | -0.1348 | +0.4760 | **+0.0888** | 4 | 1.0289 | `random_seeded/decoy` 0.458, `none/random_peer` 0.376, `most_recipients/random_peer` 0.166 |
| `canary-qwen3-0p6b-mole-v1` | `Qwen3-0.6B` | `grpo_step80` | 0.5552 | 0.92 | +0.0000 | +0.0236 | +0.2824 | **+0.2728** | 5 | 1.0466 | `random_seeded/most_restricted_peer` 0.431, `none/random_peer` 0.400, `most_recipients/random_peer` 0.167 |
| `canary-qwen-mole-v1` | `Qwen2.5-1.5B-Instruct` | `sft` | 0.5408 | 0.92 | +0.3732 | +0.1448 | +0.2636 | **+0.1676** | 2 | 0.0074 | `random_seeded/most_restricted_peer` 0.999, `oldest/random_peer` 0.001 |
| `canary-qwen-mole-v1` | `Qwen2.5-1.5B-Instruct` | `grpo_step40` | 0.5372 | 0.92 | +0.3880 | +0.1072 | +0.2644 | **+0.1492** | 2 | 0.4615 | `random_seeded/most_restricted_peer` 0.827, `oldest/random_peer` 0.173 |
| `canary-qwen-mole-v1` | `Qwen2.5-1.5B-Instruct` | `grpo_step80` | 0.4920 | 0.88 | +0.3380 | -0.0352 | +0.2712 | **+0.1540** | 3 | 0.7969 | `random_seeded/most_restricted_peer` 0.713, `oldest/random_peer` 0.159, `random_seeded/decoy` 0.128 |

- **Ablation proof (`canary-qwen-mole-v1` -> `canary-qwen25-1p5b-dpo-grpo-v2`):** On the exact same `Qwen2.5-1.5B-Instruct` base model, expert-only SFT + GRPO (`canary-qwen-mole-v1`) collapses to `k=1` greedy action on `800k` (`H(A)=0.0000`, `min_regret=+0.0835`), whereas adding trap-capped `gemini-4-carbon` distillation (`432` turns) + counterfactual preference DPO (`146` pairs) + Horizon-3 GRPO (`canary-qwen25-1p5b-dpo-grpo-v2`, `grpo_step60`) expands held-out diversity to `k=6` (`H(A)=1.1061` nats, `0` invalid generations across `3,719` `800k` and `3,737` `200k` unique prompts), preserves `solver_acc = 0.9667` (`800k`) and `1.000` (`200k`), cuts `grok_tactics` from `+0.3175` to `+0.1223` (`-0.1952 [-0.3028, -0.0855]`), and reaches `min_regret = +0.2478` (`frontier_proxy_gap = +0.2748 [+0.1237, +0.4313]`).
- **Reporting discipline:** Validation metrics on `195000-195024` (`n=25`) are labeled explicitly as checkpoint-selection validation and never conflated with held-out `800k`/`200k`. Runs without `eval_summary.json` remain marked `in_progress` (`claims_stronger_mole = False`) with zero extrapolated held-out scores.
