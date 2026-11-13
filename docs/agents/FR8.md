# HEAD-FR8: cluster ops, calibration, training data, small-model training (the tiebreaker)

Read the FR8 rules in COMMON.md twice. **Never touch any job you didn't submit.** Always set `--time`. At most 24 CPU cores in total (only compute06 has free cores). Data goes in `~/agent-arena-data` (≤10 GB). No heavy work on the login node.

## Owns
`fr8/` (sync script, sbatch scripts, env setup), `train/` (export_sft.py, lora_sft.py, eval_hf.py), `docs/reports/fr8.md`.

## Engineers to spawn
1. **slurm-ops.**
   - `fr8/sync.sh` (`rsync -az --delete --exclude .git --exclude .venv --exclude data/runs ./ freighter:~/agent-arena/`).
   - `fr8/setup.sh`: a Python environment on FR8. Try `uv` in the user dir first; else `module load pytorch-volta` + `pip install --user -e .`. Verify with a 2-minute `srun -p normal --time=00:05:00 -c 2` test.
   - Also test compute-node internet once (`curl -sI https://generativelanguage.googleapis.com`), for the morning Gemini runs.
   - Job scripts, all writing to `~/agent-arena-data/<job>/`:
     - **J1 calibrate** (`fr8/j1_calibrate.sbatch`): array over tier × a parameter grid (`p_leak`, delays, `log_rate_mole`, `interview_lr`, `leak_damage`), 500 dev seeds each, running solver + baselines + the obvious heuristic. Output: a CSV plus a recommendation per tier (solver accuracy ≥90/90/80%, random ≈ 1/N, solver − heuristic gap maximised). `--time 02:00:00`, ≤16 cores.
     - **J2 fuzz** (the INTEGRITY fuzzer): ≤8 cores, `--time 04:00:00`.
     - **J3 sft-data** (`train/export_sft.py`): 20k solver episodes on TRAIN_SEEDS across tiers, rendered as chat transcripts (system = instruction, tools = tool specs, assistant turns = tool calls as JSON, tool turns = results), plus a 2k-episode validation split. `--time 02:00:00`.
   - Start J1 as soon as Env + solver are merged (about 04:00). Start J3 after solver v1.
2. **trainer.**
   - `train/lora_sft.py`: transformers + peft LoRA on **Qwen2.5-1.5B-Instruct**. fp16 AMP (V100: no bf16), sdpa attention, gradient checkpointing, r=16, seq len about 4k (truncate long episodes into windows ending at an assistant turn), 1–2 epochs.
   - Download the model on the login node to `~/agent-arena-data/models/` (light I/O only, and check the space first).
   - `train/eval_hf.py`: a policy that plays the Env through the *same* tool loop as `llm_policy`, using HF `generate` (no vLLM on V100), greedy decoding. Run 200 HELDOUT_SEEDS per tier, before (base model) vs after (LoRA). Report score, accuracy, and the regret tags before vs after.
   - **J4** (`fr8/j4_train.sbatch`): `-p gpu --gres=gpu:1 -c 6 --time 06:00:00`. Submit once J3 data exists. It queues until Silas frees a GPU. **Do not cancel or touch anything else**; if it's still pending at 07:00, report it.
   - Do a 10-minute pilot first (a small subset) to measure throughput, then size the full run to finish by about 08:30.

## Milestones
| Time | Milestone |
|---|---|
| 03:00 | FR8 Python environment works, sync works, internet check reported |
| 04:00 | J1 submitted |
| 05:00 | J1 recommendation handed to ENV; J3 running |
| 05:30 | J4 pilot (when a GPU is free) |
| 08:30 | Before/after numbers in `docs/reports/fr8.md` |

If no GPU is free tonight: the training data + scripts + base-model eval are ready, and training runs Saturday.
