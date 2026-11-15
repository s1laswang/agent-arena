# Canary Trap Partition Design & Ternary-vs-Binary Information-Gain Audit (`v1.4`)

Keyless CPU-only analytical mutual-information derivation and world-paired held-out rollout audit across `540` controlled canary-partition episodes (`6` AST-clean partition designs x `n=90` on `HELDOUT_SEEDS 800000..800029`, `30`/tier across `easy`, `medium`, `hard` under `sha256:ebf2f09716cf76d3`, plus `180` paired `CompactLinearDAggerPolicy` and `SolverPolicy` reference episodes = `720` total episodes, `0` API calls). Holding `EmpiricalBayesPolicy`'s `TRAIN_SEEDS`-learned (`102000..102779`) likelihoods and EV stopping rule fixed, `trained_adaptive_ternary` (**`+0.6223`**) beats `adaptive_binary_2arm` (**`+0.4938`**, paired delta **`-0.1286`**), `random_half_staff_3arm` (**`+0.5409`**, **`-0.0814`**), `singleton_3suspect_microprobe` (**`+0.5710`**, **`+0.4040`** vs **`+0.5687`** on `hard`), `full_staff_naive_3arm` (**`+0.2632`**, `0.00` surfaced canary leaks on `medium` and `hard`), and `broadcast_1arm_anti_pattern` (**`+0.0281`**).

- **Seed & Secret Provenance (Panel Fix A)**: All `720` live audit episodes (with `195` step-by-step fresh-`Env` replay checks) run strictly on world-paired `HELDOUT_SEEDS 800000..800029` under `sha256:ebf2f09716cf76d3`; all learned weights come strictly from disjoint `TRAIN_SEEDS` (`102000..102779` and `109000..109509`); and **`0` `JUDGE_SEEDS` (`900k+`) are touched**. Cross-referenced `DEV_SEEDS 0..29` (`hard`, `n=30`) diagnostics are stored strictly under `dev.dev_eval_seed_range` and are **post-hoc locked, not pre-registered**.
- **Strict Track Separation (Panel Fix E)**: `0 / 19` historical open-weight `Qwen2.5-1.5B` runs in `experiment_ledger.json` exceed untrained `base` (`0.000`), planting only `6.24-9.31` diagnostic variant arms/ep while `cap=96` truncates multi-recipient `plant_canary` calls (`73.9%` of `hard` DAgger relabels); `README.md` Qwen claims remain withheld (`HOLD_README_QWEN_ADDENDUM_UNTIL_V100`). All `6` partition policies and `CompactLinearDAggerPolicy` (`is_open_weight_llm = False`) are non-LLM structured policies.

## 1. Analytical Expected Mutual Information Surface (`E[IG(k, V_arms)]` in Nats)

Under Canary `v1.4` (`canary/rules.py`), `max_variants = 3`, and a canary planted on `k` of `N` unrestricted staff leaks with per-recipient probability `q(k) = p_leak` when `careful_mole = False` (`easy`) and `q(k) = p_leak * (1 - k/N)` when `careful_mole = True` (`medium`, `hard`). Under a uniform prior `P(M = e) = 1/N`, the marginal leak probability is `P(hit | k) = (k/N) * q(k)` and Shannon mutual information decomposes exactly via the chain rule `E[IG_total(k, V)] = I(M; L) + P(hit | k) * I(M; W | leak)`:

- **`careful_mole = False` (`easy`, `N=12, p_leak=0.90, fp=1.00`)**: `P(hit | k) = 0.90 * (k/12)` increases strictly with `k`, so **`k* = N = 12`** (`100%` coverage) maximizes expected variant MI `E[IG_variant(k, 3)] = 0.98875` nats (`P(hit) = 0.9000`; total joint MI peaks at `k = 9` with `1.12833` nats).
- **`careful_mole = True` (`medium` `N=20`, `hard` `N=40`)**: `P(hit | k) = (k/N) * p_leak * (1 - k/N)` is uniquely maximized at **`k* = N/2`** (`50%` staff coverage: `k* = 10` on `medium` with `P(hit) = 0.18750`, and `k* = 20` on `hard` with `P(hit) = 0.16250`), whereas **`k = N` yields `P(hit) = 0.0` and `0.00000` nats** on both `medium` and `hard`.
- **Ternary (`3`-Arm) vs Binary (`2`-Arm) Advantage**: Conditional on a surfaced canary leak, balanced `3`-arm partitioning delivers `ln(3) = 1.09861` nats vs `ln(2) = 0.69315` nats for binary bisection (**`log(3)/log(2) = 1.5850x`**). Under `hard` fingerprint noise (`fingerprint_accuracy = 0.95`), balanced `3`-arm conditional variant MI is **`0.86544` nats** vs **`0.49463` nats** for `2`-arm (**`1.7497x`** pure variant MI; **`1.3993x`** full surfaced posterior KL at trained `65%` coverage `k=26`).

| Tier (`N`, `careful`, `fp`) | Anchor `k` (`k/N`) | `P(hit)` | `1`-Arm `E[IG_var]` / `E[IG_tot]` | `2`-Arm `E[IG_var]` / `E[IG_tot]` | `3`-Arm `E[IG_var]` / `E[IG_tot]` | `3`-Arm `I(M;W \| leak)` |
|---|---:|---:|---:|---:|---:|---:|
| `easy (N=12, off, 1.00)` | `k=3` (`25.0%`) | `0.22500` | `0.00000` / `0.45189` | `0.14322` / `0.59511` | `0.24719` / `0.69908` | `1.09861` |
| `easy (N=12, off, 1.00)` | `k=N/2=6` (`50.0%`) | `0.45000` | `0.00000` / `0.52560` | `0.31192` / `0.83751` | `0.49438` / `1.01997` | `1.09861` |
| `easy (N=12, off, 1.00)` | `k=0.65N=8` (`66.7%`) | `0.60000` | `0.00000` / `0.45629` | `0.41589` / `0.87218` | `0.64932` / `1.10561` | `1.08220` |
| `easy (N=12, off, 1.00)` | `k=N=12` (`100.0%`) | `0.90000` | `0.00000` / `0.00000` | `0.62383` / `0.62383` | `0.98875` / `0.98875` | `1.09861` |
| `medium (N=20, on, 1.00)` | `k=3` (`15.0%`) | `0.09562` | `0.00000` / `0.21714` | `0.06087` / `0.27800` | `0.10505` / `0.32219` | `1.09861` |
| `medium (N=20, on, 1.00)` | `k=N/2=10` (`50.0%`) | `0.18750` | `0.00000` / `0.15180` | `0.12997` / `0.28176` | `0.20417` / `0.35596` | `1.08890` |
| `medium (N=20, on, 1.00)` | `k=0.65N=13` (`65.0%`) | `0.17062` | `0.00000` / `0.08270` | `0.11776` / `0.20046` | `0.18646` / `0.26916` | `1.09283` |
| `medium (N=20, on, 1.00)` | `k=N=20` (`100.0%`) | `0.00000` | `0.00000` / `0.00000` | `0.00000` / `0.00000` | `0.00000` / `0.00000` | `0.00000` |
| `hard (N=40, on, 0.95)` | `k=3` (`7.5%`) | `0.04509` | `0.00000` / `0.13337` | `0.02024` / `0.15361` | `0.03903` / `0.17240` | `0.86544` |
| `hard (N=40, on, 0.95)` | `k=N/2=20` (`50.0%`) | `0.16250` | `0.00000` / `0.12850` | `0.08038` / `0.20888` | `0.14028` / `0.26878` | `0.86327` |
| `hard (N=40, on, 0.95)` | `k=0.65N=26` (`65.0%`) | `0.14787` | `0.00000` / `0.07045` | `0.07314` / `0.14359` | `0.12779` / `0.19824` | `0.86416` |
| `hard (N=40, on, 0.95)` | `k=N=40` (`100.0%`) | `0.00000` | `0.00000` / `0.00000` | `0.00000` / `0.00000` | `0.00000` / `0.00000` | `0.00000` |

## 2. World-Paired Held-Out Rollout Matrix (`HELDOUT_SEEDS 800000..800029`, `n=90` / Row)

| Design / Policy | Score (`95% CI`) | Paired `Delta` vs Trained Ternary (`95% CI`) | Acc | Wrong | Abstain | Canaries / Ep | Diag Arms / Ep | Mean `k/N` | Canary Leaks / Ep |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `trained_adaptive_ternary` (`TrainedAdaptiveTernaryPolicy`) | `+0.6223 [+0.5726, +0.6721]` | baseline | `91.1%` | `0.0%` | `8.9%` | `9.67` | `27.44` | `33.4%` | `1.61` |
| `adaptive_binary_2arm` (`AdaptiveBinary2ArmPolicy`) | `+0.4938 [+0.4228, +0.5648]` | `-0.1286 [-0.1870, -0.0701]` | `85.6%` | `2.2%` | `12.2%` | `12.23` | `24.47` | `28.3%` | `2.08` |
| `singleton_3suspect_microprobe` (`Singleton3SuspectMicroprobePolicy`) | `+0.5710 [+0.4993, +0.6427]` | `-0.0513 [-0.1302, +0.0276]` | `82.2%` | `1.1%` | `16.7%` | `11.00` | `33.00` | `9.6%` | `0.90` |
| `random_half_staff_3arm` (`RandomHalfStaff3ArmPolicy`) | `+0.5409 [+0.4740, +0.6077]` | `-0.0814 [-0.1555, -0.0074]` | `85.6%` | `1.1%` | `13.3%` | `12.12` | `36.37` | `50.0%` | `1.38` |
| `full_staff_naive_3arm` (`FullStaffNaive3ArmPolicy`) | `+0.2632 [+0.1807, +0.3457]` | `-0.3591 [-0.4402, -0.2780]` | `35.6%` | `1.1%` | `63.3%` | `18.24` | `54.73` | `100.0%` | `0.59` |
| `broadcast_1arm_anti_pattern` (`Broadcast1ArmAntiPatternPolicy`) | `+0.0281 [-0.0120, +0.0682]` | `-0.5942 [-0.6514, -0.5370]` | `6.7%` | `1.1%` | `92.2%` | `21.01` | `0.00` | `100.0%` | `1.61` |
| `compact_linear_dagger` (`CompactLinearDAggerPolicy`, ref) | `+0.6632 [+0.6071, +0.7194]` | `+0.0409 [-0.0301, +0.1119]` | `96.7%` | `1.1%` | `2.2%` | `9.42` | `27.67` | `20.9%` | `1.57` |
| `solver_reference` (`SolverPolicy`, ref) | `+0.6816 [+0.6281, +0.7350]` | `+0.0592 [-0.0056, +0.1240]` | `95.6%` | `1.1%` | `3.3%` | `7.61` | `22.13` | `27.3%` | `1.44` |

## 3. Per-Tier Score & Surfaced Canary-Leak Breakdown (`n=30` / Cell)

| Design / Policy | `easy` (`careful=off`, `n=30`) | `medium` (`careful=on`, `n=30`) | `hard` (`careful=on, fp=0.95`, `n=30`) | Pooled (`n=90`) |
|---|---:|---:|---:|---:|
| `trained_adaptive_ternary` | `+0.7287` (`1.37` lk, `13.6` arms) | `+0.5697` (`1.23` lk, `23.0` arms) | `+0.5687` (`2.23` lk, `45.7` arms) | `+0.6223` (`91.1%` acc) |
| `adaptive_binary_2arm` | `+0.6860` (`1.70` lk, `11.3` arms) | `+0.4017` (`1.63` lk, `19.5` arms) | `+0.3937` (`2.90` lk, `42.5` arms) | `+0.4938` (`85.6%` acc) |
| `singleton_3suspect_microprobe` | `+0.7077` (`0.90` lk, `14.6` arms) | `+0.6013` (`0.83` lk, `22.2` arms) | `+0.4040` (`0.97` lk, `62.2` arms) | `+0.5710` (`82.2%` acc) |
| `random_half_staff_3arm` | `+0.7277` (`1.40` lk, `15.2` arms) | `+0.4367` (`1.13` lk, `28.7` arms) | `+0.4583` (`1.60` lk, `65.2` arms) | `+0.5409` (`85.6%` acc) |
| `full_staff_naive_3arm` | `+0.7943` (`1.77` lk, `11.2` arms) | `-0.0047` (`0.00` lk, `39.0` arms) | `+0.0000` (`0.00` lk, `114.0` arms) | `+0.2632` (`35.6%` acc) |
| `broadcast_1arm_anti_pattern` | `+0.0890` (`4.83` lk, `0.0` arms) | `-0.0047` (`0.00` lk, `0.0` arms) | `+0.0000` (`0.00` lk, `0.0` arms) | `+0.0281` (`6.7%` acc) |
| `compact_linear_dagger` | `+0.8203` (`1.53` lk, `9.9` arms) | `+0.6790` (`1.37` lk, `20.3` arms) | `+0.4903` (`1.80` lk, `52.8` arms) | `+0.6632` (`96.7%` acc) |
| `solver_reference` | `+0.7927` (`1.43` lk, `10.7` arms) | `+0.6617` (`1.40` lk, `20.9` arms) | `+0.5903` (`1.50` lk, `34.7` arms) | `+0.6816` (`95.6%` acc) |

## 4. Frontier MCP (`DEV_SEEDS 0..29` Hard) & Open-Weight `Qwen2.5-1.5B` Cross-Reference

### 4.1 Post-Hoc Locked `DEV_SEEDS 0..29` (`hard`, `n=30`) Diagnostic Arm Contrast

On `DEV_SEEDS 0..29` (`hard`, `n=30`, **post-hoc locked, not pre-registered**; `results/tiebreak/frontier_comparison/comparison_summary.json`), frontier score tracks cumulative diagnostic variant arms planted before commitment:

- **`gpt-5.5` (OpenCode MCP)**: **`48.10`** diagnostic variant arms/ep (`17.13` canaries x `2.86` variants, `84.5%` slot utilization) -> **`+0.5037`** (`93.3%` accuracy).
- **`SolverPolicy` (Bayesian reference)**: **`42.40`** diagnostic variant arms/ep (`14.13` canaries x `3.00` variants, `66.7%` slot utilization) -> **`+0.4990`** (`96.7%` accuracy).
- **`EmpiricalBayesPolicy` (`trained_adaptive_ternary`)**: **`49.87`** diagnostic variant arms/ep on post-hoc locked `DEV_SEEDS 0..29` `hard` (`45.73` arms/ep on `HELDOUT_SEEDS 800000..800029` `hard`) -> **`+0.5503`** (`DEV`) and **`+0.5687`** (`HELDOUT`).
- **`gemini-4-carbon` (OpenCode MCP)**: only **`25.40`** diagnostic variant arms/ep (`8.47` canaries, `31.5%` slot utilization, diverting `67.97` calls/ep into low-KL interviews) -> **`+0.3223`** (`83.3%` accuracy).

### 4.2 Historical `Qwen2.5-1.5B` (`0 / 19` Above `0.000`) & `cap=96` Partition Truncation

Across all `19` historical open-weight `Qwen2.5-1.5B` runs in `experiment_ledger.json` (**`0 / 19`** above `0.000`, `HOLD_README_QWEN_ADDENDUM_UNTIL_V100`), `v2-off30` planted only **`6.24`** diagnostic variant arms/ep and `v3-4k` planted **`9.31`** arms/ep (`6.24-9.31` range). Because `Qwen2.5-1.5B` chat tool calls spend `8` BPE tokens per assigned employee (`28 + 8*k + ...`), every `plant_canary` call with `k >= 9` recipients exceeds `eval_hf`'s `cap=96` (`k* = N/2 = 10` on `medium` needs `109` tokens; `k* = N/2 = 20` on `hard` needs `189` tokens, truncating `133/180` = `73.9%` of `hard` DAgger relabels). Non-LLM structured policies emit `0` JSON tokens and realize balanced 3-arm partial splits directly.

## 5. Offline Verification & Regeneration Commands

```bash
python scripts/tiebreak_canary_split_design_audit.py --generate
python scripts/tiebreak_canary_split_design_audit.py --check
pytest -q tests/test_tiebreak_canary_split_design.py tests/test_reproduce_tiebreak_all.py
python scripts/reproduce_tiebreak_all.py --check
python scripts/verify_tiebreak_submission.py --strict
```
