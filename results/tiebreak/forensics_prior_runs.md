# Tiebreaker Prior Runs Forensics (J4 / WS4 / v3)

Honest post-mortem of every historical small-model investigator training and evaluation run on Canary prior to the calibrated compact tiebreaker pipeline.

## 1. Ledger of Historical J4 and WS4 SFT Runs

| Job / Run | Env | Model / Mode | Train Progress | Held-Out Eval N | Mean Score (+/- CI95) | Accused / Correct / Abstain | Parse-Valid / Env-OK Calls | Outcome |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `slurm-44200` (J4 pilot) | v1.3 | Qwen2.5-1.5B prefix 4k | 0/5 pilot steps | 0 | n/a | n/a | n/a | Host 28G cgroup OOM kill (`oom_kill=1`) |
| `run-44397` base (`eval-base`) | v1.3 | Qwen2.5-1.5B-Instruct | 0 steps | 2 | 0.000 +/- 0.000 | 0.00 / 0.00 / 1.00 | 0.08 / 0.08 | 91.8% unparseable tool calls (`tool_cap`) |
| `slurm-44397` (`J4 / v1` dedup) | v1.3 | 1.5B LoRA prefix 4k | 450/9005 steps (5.0%) | 12 (raw 19) | -0.250 +/- 0.256 | 0.25 / 0.00 / 0.75 | 1.00 / 0.99 | Syntax fixed (0.08 -> 0.99 env-OK), score regressed via wrong early accusations |
| `run-44397` (`eval-lora-par` only) | v1.3 | 1.5B LoRA prefix 4k | 450/9005 steps | 12 | -0.043 +/- 0.188 | 0.17 / 0.08 / 0.83 | 1.00 / 1.00 | 10/12 horizon abstentions, 1 correct hard catch, 1 wrong easy accusation |
| `eval-44411` (`ws4-base-v14`) | v1.4 | Qwen2.5-1.5B-Instruct | 0 steps | 16 | 0.000 +/- 0.000 | 0.00 / 0.00 / 1.00 | 0.03 / 0.03 | 97.0% invalid calls (`eval_cap` on day 1 across all 16 episodes) |
| `slurm-44410` + `eval-44412` (`WS4 / v2`) | v1.4 | 1.5B LoRA dense 4k | 887/1772 steps (50.1%) | 82 | -0.395 +/- 0.128 | 0.51 / 0.06 / 0.49 | 0.92 / 0.86 | Valid calls 0.03 -> 0.92, but uncalibrated blind accusations drove score to -0.395 |
| `eval-44583` (`ws4-base-v14-n30`) | v1.4 | Qwen2.5-1.5B-Instruct | 0 steps | 0 | n/a | n/a | n/a | Terminated after 41s before first episode finished (SIGNAL Terminated) |
| `eval-44584` (`ws4-base-v14-off6`) | v1.4 | Qwen2.5-1.5B-Instruct | 0 steps | 20 (snapshot) | 0.000 +/- 0.000 | 0.00 / 0.00 / 1.00 | 0.03 / 0.03 | Offset-6 base continuation; 97.0% invalid calls (`eval_cap`) |

### WS4 / v2 (`eval-44412`) Tier Breakdown (`n=82`)

| Tier | N | Mean Score (+/- CI95) | Accused Rate | Accuracy | Abstain (`eval_cap`) | Parse-Valid Rate | Mean Final Day |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `easy` | 28 | -0.6157 +/- 0.2660 | 25/28 (0.8929) | 4/28 (0.1429) | 3/28 (0.1071) | 0.6108 | 2.32 |
| `medium` | 27 | -0.0056 +/- 0.0971 | 2/27 (0.0741) | 1/27 (0.0370) | 25/27 (0.9259) | 1.0000 | 4.11 |
| `hard` | 27 | -0.5556 +/- 0.1910 | 15/27 (0.5556) | 0/27 (0.0000) | 12/27 (0.4444) | 0.9675 | 6.70 |

## 2. Evaluation Integrity Catch: Unpaired Per-Process `os.urandom` World Secrets

- Paired status between `eval-44411` (base) and `eval-44412` (v2): **`paired = False`**.
- `eval-44411.out` (`ws4-base-v14`) world secret SHA256: `f272803cdb679dbe`.
- `eval-44412.out` (`ws4-v2-44410`) world secret SHA256: `c86b9c8a54f8b269`.
- `eval-44583.out` (`ws4-base-v14-n30`) world secret SHA256: `b8cf262cf76208ae`.
- `eval-44584.out` (`ws4-base-v14-off6`) world secret SHA256: `404f83e6a15c3f1c`.
- `run-44397` also used three distinct per-process secrets across `eval-base` (`58518f46a669f563`), `eval-lora` (`7a134382b86e76ca`), and `eval-lora-par` (`1508547cb6a97648`), producing 3 score/outcome disagreements on identical `(tier, seed)` pairs.
- Root mechanism: canary.world._key(seed) falls back to per-process os.urandom(32) on HELDOUT_SEEDS (800000+) whenever CANARY_WORLD_SECRET and data/worlds/judge/SALT are absent.
- Mandatory protocol fix: Evaluate base and fine-tuned policies in a single process or pass an explicit shared CANARY_WORLD_SECRET and verify matching world_secret_sha256 in logs.

## 3. Quantitative Root-Cause Proof on WS4 / v2 (`ws4-v2-44410`)

### 3a. Header Tax and 1254-Token Context Amnesia (`~4.0` chars/token)

- In `slurm-44410.out`, the OpenAI/Qwen tool-schema + system + kickoff header consumed **`2842/4096` tokens (`69.4%`)**, leaving only **`1254` tokens (`30.6%`)** for episode history and only **`2.7%` (`1463724/53284109`)** loss-bearing assistant tokens.
- Across all **`42`** accused episodes in `runs/ws4-v2-44410/episodes.jsonl`:
  - **`1045/1470` (`71.1%`)** prior tool turns fell outside the `1254`-token body window before `accuse`.
  - **`54/80` (`67.5%`)** prior `plant_canary` turns fell outside the `1254`-token body window (affecting `15/35` canary-planting accused episodes), erasing the variant-to-employee mapping needed to interpret surfaced canary leaks.
  - **`68/70` (`97.1%`)** prior `list_employees` turns fell outside the `1254`-token body window (`41/42` accused episodes had no visible employee roster at the `accuse` turn).

### 3b. Read-Only `SolverPolicy._ingest` + `belief()` Full-History Replay Audit

- Replaying all public steps prior to each of the `42` `v2` accusations through `SolverPolicy`:
  - **`40/42` (`95.24%`)** accused with full-history posterior **`P_full(accused) < 1 / (1 + V_known)`** (mean `P_full(accused) = 0.1225` vs mean breakeven `0.5220`, mean full-history `EV(accuse) = -0.7644`).
  - **`25/42` (`59.52%`)** accused a suspect already ruled out or near-zero under full public evidence (**`P_full(accused) <= 0.05`**), including `5/42` (`11.90%`) explicitly contradicted by a surfaced canary variant and `12/42` (`28.57%`) not in the recipient list of a surfaced leaked document.
  - Only **`7/42` (`16.67%`)** even named the full-history MAP suspect (`mean max_e P_full(e) = 0.3021`).

| Tier | Accused Eps | Dropped `plant_canary` | Dropped `list_employees` | `P_full < 1/(1+V_known)` | `P_full <= 0.05` | Surfaced Canary Mismatch | Mean `P_full(accused)` |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `easy` | 25 | 7/31 (22.6%) | 63/65 (96.9%) | 24/25 (96.0%) | 12/25 (48.0%) | 4/25 | 0.1391 |
| `medium` | 2 | 2/4 (50.0%) | 2/2 (100.0%) | 1/2 (50.0%) | 0/2 (0.0%) | 0/2 | 0.5627 |
| `hard` | 15 | 45/45 (100.0%) | 3/3 (100.0%) | 15/15 (100.0%) | 13/15 (86.7%) | 1/15 | 0.0361 |

## 4. Historical v3 Investigator GRPO Runs (V100 and Verda)

- **Attempt 1 (`slurm-44548.out` seed 0, `slurm-44550.out` seed 1)**: Both crashed at step 0 with `torch.OutOfMemoryError` inside `model.generate(input_ids=x.expand(a.group, -1)) SDPA prefill` on 32GB V100 (`44548` tried `5.49 GiB` with `26.63 GiB` in use; `44550` tried `5.52 GiB` with `26.34 GiB` in use).
- **Attempt 2 (`slurm-44553.out` seed 0)**: Gradient checkpointing fixed OOM, but across `6` steps (`0.129h`), `6/6` steps had zero-variance groups (all 2 groups had zero variance on `4/6` steps, `mean_continue_frac = 0.917`, `max_kl = 0.00011`), yielding near-zero policy gradient.

| Curve Run | Source | Steps | Hours | Sec/Step | Mean Reward (Head -> Tail) | Gain vs Solver (Head -> Tail) | Valid Rate | Zero-Var Steps | Max KL |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `run-44553` | `v3/slurm-44553.out` | 6 | 0.129 | 77.2 | 0.6293 (0.4103 -> 0.6950) | -0.0701 (-0.2104 -> 0.0000) | 0.9583 | 6/6 | 0.00011 |
| `run-44555` | `v3/run-44555/curve.jsonl` | 48 | 1.010 | 75.8 | 0.2327 (0.2529 -> 0.2053) | -0.5184 (-0.5063 -> -0.5469) | 0.9909 | 10/48 | 2.71778 |
| `run-44572` | `v3/run-44572/curve.jsonl` | 192 | 4.002 | 75.0 | 0.1928 (0.2341 -> 0.2279) | -0.5336 (-0.5099 -> -0.4958) | 0.9815 | 32/192 | 5.63942 |
| `run-verda-s0` | `origin/justSilas-fr8:data/fr8/verda/run-verda-s0/curve.jsonl` | 143 | 0.472 | 11.9 | 0.1266 (-0.0344 -> 0.1934) | -0.5952 (-0.7102 -> -0.5282) | 0.9690 | 26/143 | 7.93898 |

### 4b. Complete Verda and FR8 WS4 Matrix (v1.4 Held-Out)

- Disclosure: DEV_SEEDS 0..29 in secondary diagnostics are post-hoc locked right after episode commitment, not pre-registered; all WS4 and Verda tiebreaker evaluations use HELDOUT_SEEDS 800000..800199.
- Pooled `base`: `n=36` (`44411` `n=16` + `44584` `n=20`), score `0.000 +/- 0.000`, valid call rate `0.03` (`100%` `eval_cap` on Day 1).
- Pooled `v2`: `n=172` (`44412` `n=82` `-0.395 +/- 0.128` + `v2-off30` `n=90` `-0.514 +/- 0.115`), pooled `-0.457 +/- 0.086` (accused `94/172 = 0.55`, precision `8/94 = 0.09`).
- `v3-4k` family: pooled `v3-4k-s0` (`609` GRPO steps) `n=180` scored `-0.147 +/- 0.063` (valid `1.00`, accused `38/180 = 0.21`, correct `6/38 = 0.16`, `+0.310 +/- 0.107` two-sample vs `v2`); FR8 V100 `v3-4k-s1` partial (`192` steps, `n=25`) scored `-0.240 +/- 0.171`; Verda spot `714d8144` was preempted after `~29m` (`n=0`).
- Inference-length confound (`v3-4k-s0@8k`, shared secret `1ca0c2a64d`): re-evaluating the exact `4k`-trained adapter (`3d0cd43b8037`) at `max_ctx=8192` (`n=90`) dropped score to `-0.716 +/- 0.105` (`-0.568 +/- 0.123` vs `4k`), flipping medium/hard accusations to `0.80` / `0.90` (`0` correct).
- `v3-8k` replicates (`n=90` each): `v3-8k-s1` (`371` steps) over-accused (`-0.777 +/- 0.118`, accused `0.94`), `v3-8k-s2` (`693` steps) collapsed to abstention (`-0.050 +/- 0.049`, abstain `0.93`), and `v3-8k-s3` (`344` steps, shared secret `1ca0c2a64d`) scored `-0.788 +/- 0.117`; truly paired `8k`-trained vs `4k`-trained at `8k` (`60/60` matching rosters) = `-0.073 +/- 0.173`.

| Run / Slice | Ctx | Steps | Held-Out N | Seed Span | World Secret | Mean Score (+/- CI95) | Valid | Accused | Correct | Key Comparison / Status |
| --- | ---: | ---: | ---: | --- | --- | --- | ---: | ---: | ---: | --- |
| `base` (pooled) | 4096 | 0 | 36 | `800000..800012` | unpaired (`f272803c`+`404f83e6`) | 0.000 +/- 0.000 | 0.03 | 0.00 | 0/36 | `44411` n=16 + `44584` n=20 (`eval_cap`) |
| `v2` (pooled) | 4096 | 887 | 172 | `800000..800059` | unpaired (`c86b9c8a`+`68bbe201`) | -0.457 +/- 0.086 | 0.92 | 0.55 | 8/94 (0.09) | `44412` n=82 (-0.395) + `v2-off30` n=90 (-0.514) |
| `v3-4k-s0` (pooled) | 4096 | 609 | 180 | `800000..800059` | unpaired (`3bb74f5a`+`68bbe201`) | -0.147 +/- 0.063 | 1.00 | 0.21 | 6/38 (0.16) | +0.310 +/- 0.107 vs `v2` |
| `v3-4k-s1` (`44572`) | 4096 | 192 | 25 | `800000..800008` | unpaired (`09f8bc64`) | -0.240 +/- 0.171 | 0.97 | 0.24 | 0/6 | Partial FR8 V100 eval (`44573`) |
| `v3-4k-s1-spot` (`714d`) | 4096 | ~30m | 0 | n/a | n/a | n/a | n/a | n/a | n/a | Verda A100 spot preempted (`714d8144`) |
| `v3-4k-s0@8k` | 8192 | 609 | 90 | `800000..800029` | shared (`1ca0c2a64d`) | -0.716 +/- 0.105 | 0.99 | 0.78 | 3/70 | -0.568 +/- 0.123 vs `4k` (ctx confound) |
| `v3-8k-s1` (`ac58`) | 8192 | 371 | 90 | `800000..800029` | unpaired (`ac58df04`) | -0.777 +/- 0.118 | 0.92 | 0.94 | 8/85 | Off-policy 8k over-accusation |
| `v3-8k-s2` (`dbd0`) | 8192 | 693 | 90 | `800000..800029` | unpaired (`dbd083ca`) | -0.050 +/- 0.049 | 0.96 | 0.07 | 1/6 | 93% abstention collapse |
| `v3-8k-s3` (`f437`) | 8192 | 344 | 90 | `800000..800029` | shared (`1ca0c2a64d`) | -0.788 +/- 0.117 | 0.94 | 0.96 | 8/86 | Paired vs `4k@8k`: -0.073 +/- 0.173 |

## 5. Design Requirements Derived for Next-Gen Tiebreaker

1. Eliminate the 69.4% header tax (2842/4096 tokens): use a compact state/tool renderer so employee roster and all planted canary assignments stay inside the context window.
2. Train calibrated stopping and abstention: supervise explicit posterior/breakeven checks (accuse only when P(top) > 1/(1+V_known) and include censored abstention trajectories).
3. Enforce strict paired evaluation on HELDOUT_SEEDS: run base and fine-tuned models under a shared CANARY_WORLD_SECRET (or same-process world) and assert matching SHA256.
4. Avoid naive on-policy GRPO without state-value variance control: 32GB V100 hits SDPA OOM on unchunked 4k group prefill, collapsed continue-only groups yield zero gradient, and forced-accuse single-step RL drifts in KL without closing the solver gap.
