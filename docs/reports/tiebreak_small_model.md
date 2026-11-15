# Small-Model Tiebreaker: Honest Experiment Ledger and Architecture Diagnosis

Rubric target: train a smaller model on Canary experience (`TRAIN_SEEDS = [100000, 200000)`) that measurably improves on held-out seeds (`HELDOUT_SEEDS = [800000, 800200)`), with honest before/after comparisons and every run logged, including OOMs, zero-variance collapses, and negative-reward regressions.

- Historical runs logged: `7`
- Dynamically discovered squad runs: `0`
- Verified improvements passing all 4 strict gates: `0`

## 1. Architecture Diagnosis: Why Raw 4k Transcripts Failed

Across three generations of raw-transcript GPU runs (`J4-pilot-44200`, `J4-v1-44397`, `WS4-v2-44412`, and `WS4-v3-*`), Qwen2.5-1.5B-Instruct learned valid tool syntax (`0.08 -> 0.99` valid calls) yet failed to produce positive held-out reward. Log forensics isolate three compounding root causes:

### 1.1 Prompt Header Crowding and Evidence Truncation (`2,842 / 4,096` Tokens)

- In `slurm-44410.out`, the system prompt, OpenAI tool JSON schemas, and kickoff consume `2,842` tokens of every `4,096`-token window, leaving only `1,254` tokens (`~6-8` tool turns) for episode history.
- During multi-day evaluation (`14` days on easy/medium, `21` days on v1.4 hard), `HFPolicy._prompt_ids` drops the oldest `(assistant, tool)` pairs once context exceeds `4,000` tokens.
- That sticky prefix eviction deletes Day 1 `list_employees` (departments and clearances) and early `plant_canary` variant-to-recipient maps before delayed leaks (`delay_choices = (1, 2, 3)` on medium, `(2, 3)` on hard) surface in `check_leak_feed`. When the model later sees a leaked variant, the mapping from variant to employee has already scrolled out of its `1,254`-token body window.

### 1.2 Survivorship-Biased SFT Endings (`0%` Abstentions Under `-1.0` Penalty)

- Under Canary v0.3+ scoring, a correct accusation earns `+V`, abstaining to the horizon scores `0.0`, and a wrong accusation scores `-1.0` (breakeven posterior `p* = 1 / (1 + V) ~ 0.56` to `0.72`).
- Legacy J3/J3v2 exports (`train/export_sft.py`) kept only `correct=True` accusations (`0%` abstentions).
- In `J4-v1-44397` (`prefix` 4k windows, `1.57%` loss-token share across `287M` tokens), terminal `accuse` turns were `<1.5%` of assistant turns: LoRA mastered tool syntax (`0.08 -> 0.99` valid calls, `~0.85` solver action-type agreement) but rarely accused, scoring `-0.250 +/- 0.256` on deduplicated held-out episodes (`n=12`) vs base `0.000`.
- In `WS4-v2-44412` (`dense` 4k windows + `--oversample-endings 3`), oversampling `accuse` endings 4x forced the model to accuse on `51%` (`42/82`) of held-out episodes while `1,254`-token truncation hid who received each canary variant. Accuracy collapsed to `6.1%` (`5/82` overall, `0/27` on hard), driving mean score down to `-0.395 +/- 0.128`.

### 1.3 Decision-Point GRPO Bottlenecks at 4k Context (`44548-44572`)

- `WS4-v3-44548-44550`: unchunked group prefill and full-logit sampling OOMed V100-32GB (`5.49-5.52 GiB` allocation failure above `~26.5 GiB` reserved).
- `WS4-v3-44553`: after enabling gradient checkpointing, unguided sampling hit `8/10` zero-variance groups (`continue_frac=1.0`, `accuse_frac=0.0`) because avoiding `-1.0` dominates uninformed guesses.
- `WS4-v3-verda-s0-44572`: guided forced-accuse exploration lifted step-140 valid-only decision gain to `+0.091` without single-tool collapse, but forced-accuse target (`whom`) accuracy remained flat at `~0.19` under 4k raw context because recipient assignments were still truncated.

### 1.4 Paired World-Secret Hygiene (`44411` vs `44412` Caveat)

- Without `CANARY_WORLD_SECRET`, `canary.world` draws a fresh per-process `os.urandom(32)` key (`f272803cdb679dbe` in `WS4-base-44411` vs `c86b9c8a54f8b269` in `WS4-v2-44412`). Honest held-out claims require an identical `world_secret_tag` across `before` and `after` on `HELDOUT_SEEDS`.

## 2. Calibrated Working-Memory Solution

1. **Compact Working-Memory State (`train/compact_render.py`)**: replaces raw multi-thousand-token tool logs with a lossless `<900`-token working-memory state tracking employee clearances, planted canary `(doc_id, variant -> recipients)` tables, surfaced leak feed matches, candidate consistency counts, `known_v`, and the exact breakeven threshold `1 / (1 + known_v)`.
2. **Posterior-Calibrated SFT + EV-Margin DPO (`train/export_calibrated_sft.py`)**: filters natural rollouts by exact Bayesian calibration (`top_p >= breakeven_p` for accusations; `top_p < breakeven_p` for horizon abstentions), synthesizes censored low-posterior horizon abstentions (`score = 0.0`), oversamples abstentions `2x` in train, and exports step-level DPO pairs penalizing negative-EV premature accusations and runner-up guesses.
3. **Multi-Scale Small-Model Tiebreaker Ladder**: evaluates compact-state LoRA/DPO (`Qwen2.5-0.5B` and `Qwen2.5-1.5B`) alongside lightweight learned policies (`TinyMLPPolicy`, `EmpiricalBayesPolicy`) trained strictly on `TRAIN_SEEDS` and paired on identical `HELDOUT_SEEDS` worlds.

## 3. Canonical Calibrated v1.4 Dataset Statistics

Generated via `python -m train.export_calibrated_sft` (`--workers 1`) onto shared `/localscratch` (`/tmp/fleet-silas/shared/tiebreak/cal_v14/{train,val}`); only compact JSON manifests are committed.

| Split | Tier | Natural Eps | Correct Accuse | Natural Abstain | Augmented Abstain | Rejected Wrong | SFT Written | DPO Pairs | Mean `top_p` Accuse | Mean `top_p` Abstain |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `train` | `easy` | 140 | 140 | 0 | 35 | 0 | 210 | 805 | 0.9973 | 0.4861 |
| `train` | `medium` | 140 | 125 | 15 | 35 | 0 | 225 | 855 | 0.9993 | 0.3468 |
| `train` | `hard` | 140 | 133 | 4 | 35 | 3 | 211 | 820 | 0.9665 | 0.4388 |
| **`train` total** | **all** | **420** | **398** | **19** | **105** | **3** | **646** | **2480** | **0.9876** | **0.4150** |
| `val` | `easy` | 25 | 25 | 0 | 10 | 0 | 35 | 156 | 1.0000 | 0.4979 |
| `val` | `medium` | 25 | 25 | 0 | 10 | 0 | 35 | 166 | 1.0000 | 0.3218 |
| `val` | `hard` | 25 | 23 | 2 | 10 | 0 | 35 | 170 | 0.9651 | 0.3675 |
| **`val` total** | **all** | **75** | **73** | **2** | **30** | **0** | **105** | **492** | **0.9890** | **0.3939** |

## 4. Strict `VERIFIED_IMPROVEMENT` Gates

Every candidate run in `results/tiebreak/*/summary.json` (and optional `--extra-glob` paths) must pass all four machine-checked gates in `scripts/tiebreak_experiment_ledger.py` before receiving `VERIFIED_IMPROVEMENT`:

1. **Seed Disjointness (`gate1_seed_hygiene`)**: `train_seeds` strictly inside `[100000, 200000)` and disjoint from `eval_seeds`.
2. **Paired Held-Out Worlds (`gate2_paired_world_secret`)**: identical non-empty `world_secret_tag` between `before` and `after` evaluated on `HELDOUT_SEEDS` (`[800000, 800200)`).
3. **Sample Size & Replay Integrity (`gate3_sample_and_replay`)**: `n >= 30`, `replay_verified is True`, and `0` invalid/error episodes counted as `0`.
4. **Statistically Significant Gain (`gate4_paired_ci95_positive`)**: paired `ci95_low(after - before) > 0.0`.

## 5. Complete Tiebreaker Experiment Ledger (All Runs Logged)

| Run ID | Model / Method | Tiers | Held-out `n` | Before -> After Score | Valid Calls | Secret Pairing | Status | Notes |
|---|---|---|---:|---|---|---|---|---|
| `J4-pilot-44200` | Qwen2.5-1.5B-Instruct LoRA r=16 (pilot) | `easy,medium,hard` (v1.0) | 0 | `n/a` | `n/a` | `n/a` | `FAILED_OOM` | 28G Slurm cgroup OOM during single-core pilot tokenization of 20k J3 prefix episodes (~102k tokens/ep). |
| `J4-v1-44397` | Qwen2.5-1.5B-Instruct LoRA r=16 | `easy,medium,hard` (v1.3) | 12 | `0.000 -> -0.250 +/- 0.256` | `0.08 -> 0.99` | `unpaired (58518f46 vs 7a134382)` | `NEGATIVE_REWARD_PROTOCOL_GAIN` | Protocol syntax jumped from 0.08 to 0.99 valid calls (~0.85 solver action-type agreement), but prefix 4k SFT (1.57% loss tokens) rarely committed and missed when accusing: dedup held-out n=12 scored -0.250 +/- 0.256 vs base 0.000. |
| `WS4-base-44411` | Qwen2.5-1.5B-Instruct (base) | `easy,medium,hard` (v1.4) | 16 | `base 0.000` | `0.03` | `unpaired (f272803c)` | `BASELINE_CAVEATED` | Qwen2.5-1.5B base v1.4 held-out n=16 scored 0.000 (valid call rate 0.03, never leaves Day 1); ran without CANARY_WORLD_SECRET so os.urandom(32) world key f272803cdb679dbe is unpaired vs 44412. |
| `WS4-v2-44412` | Qwen2.5-1.5B-Instruct LoRA r=16 (dense v2) | `easy,medium,hard` (v1.4) | 82 | `0.000 -> -0.395 +/- 0.128` | `0.03 -> 0.92` | `unpaired (f272803c vs c86b9c8a)` | `NEGATIVE_BLIND_ACCUSE` | Dense 4k + oversample-endings 3 on 100% accuse-only SFT caused blind accusations: held-out n=82 scored -0.395 +/- 0.128 (accused 0.51, correct 0.06; 0/27 correct on hard) because the 2,842-token header left only 1,254 body tokens and evicted employee/canary mappings. |
| `WS4-v3-44548-44550` | Qwen2.5-1.5B-Instruct LoRA (v3 GRPO init from 44410) | `easy,medium` (v1.4) | 0 | `n/a` | `n/a` | `n/a` | `FAILED_CUDA_OOM` | Decision-point GRPO OOMed V100-32GB (tried to allocate 5.49-5.52 GiB above ~26.5 GiB reserved) during unchunked group prefill and full-logit sampling. |
| `WS4-v3-44553` | Qwen2.5-1.5B-Instruct LoRA (v3 GRPO unguided) | `easy,medium` (v1.4) | 0 | `n/a` | `n/a` | `n/a` | `FAILED_ZERO_VARIANCE` | Unguided GRPO collapsed to continue_frac=1.0 (8/10 groups zero variance in first 5 steps; 10/12 across 6 steps) before guided forced-accuse exploration was introduced. |
| `WS4-v3-verda-s0-44572` | Qwen2.5-1.5B-Instruct LoRA (v3 guided GRPO 4k) | `easy,medium` (v1.4) | 0 | `n/a` | `n/a` | `n/a` | `IN_PROGRESS_PARTIAL` | Guided GRPO reached +0.091 valid-only gain at step 140 without tool collapse, but forced-accuse whom-accuracy stayed flat around ~0.19 at 4k context because raw transcripts still drop early canary-to-recipient assignments. |

## 6. Verification Command

```bash
python scripts/tiebreak_experiment_ledger.py --check
```
