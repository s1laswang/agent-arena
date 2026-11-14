# FR8 report

## 02:05 status
- Done (verified: ssh probe): freighter reachable; /home 95% full (42G free); compute06 has 24 idle cores on `normal`; every GPU is busy with Silas's `sky` array, and his `sleeper-pilot` is pending. Our Unix user owns those jobs, so we only cancel job ids listed in `~/agent-arena-data/jobs/OURS.txt`.
- Done: worktree `justSilas-fr8` and engineer branches `-ops`, `-trainer`, `-analyst`.
- In progress:
  - ops: sync, env setup + srun test, internet check, J1/J2/J3/J5 sbatch (ETA 03:00)
  - trainer: Qwen2.5-1.5B download, export_sft/lora_sft/eval_hf, j4 sbatch (ETA 04:00)
  - analyst: CI sizing, difficulty sweep, forge report (ETA 04:00)
- Blockers: J1 and J3 need the ENV and solver merges (~02:45 and ~04:00).
- Next 45 min: review the sync/env setup and report the internet check result.

## 02:04 status
- Done (verified: make test, 94 passed): analysis modules use the real noise setting via `rules.apply_noise`; the J1 recommendation now requires stop_early < 0, the solver's lower CI bound > 0, and records the wrong-accusation rate.
- Done (verified: a real local sweep with baselines only, seeds 0–29, noise 0.5/1/2, wrong accusation still scoring 0): noise barely moves the baselines. On medium and hard, every baseline is near chance (accuracy ≈0.03). Output: `fr8/analysis/out/difficulty_baselines.csv`.
- Plan change (CEO): the FR8 CPU jobs 43858/43859 are pending because partition normal is congested; they stay queued as a bonus. J1, J3 and J5 run locally on the Mac (≤6 processes). The CEO will pause one sky run for J4; FR8 submits J4 once the J3 data exists.
- Blockers: J1 waits for contract v0.3 + solver v1; the solver curve needs `canary.eval.run_episode`; `Env` needs a `params=` argument (the sweep currently swaps `rules.TIERS` temporarily).
- In progress: ops (env/srun/internet check, local J1/J5 runner), trainer (Qwen download, SFT pipeline, J4 script).

## 02:05 status
- Done (verified: srun job 43845, pytest on compute01): the uv Python environment on FR8 works; `fr8/sync.sh` and `fr8/submit.sh` are in place, and every job we submit is recorded in `~/agent-arena-data/jobs/OURS.txt`.
- Done (verified: srun job 43846): compute nodes have NO internet (curl rc=6); the login node does. Every Gemini call runs on the Mac (CEO agreed).
- Done (verified: safetensors and tokenizer load): Qwen2.5-1.5B-Instruct is in `~/agent-arena-data/models` (2.9 GB; the data dir is ~3 GB of 10).
- Done (verified: srun job 43858, SMOKE OK): the training pipeline runs end to end on CPU: fake export → windows tokenised with the real Qwen tokenizer → 2 LoRA steps of a tiny Qwen2 → eval. `fr8/j4_train.sbatch` is ready (gpu:1, -c 6, 28G, 6 h; pilot → 3.5 h training → base vs LoRA eval, 30 held-out seeds per tier).
- Done (untested on real data): the J1/J2/J3/J5 sbatch scripts and the Mac runners (≤3 processes each).
- Blockers: J1 needs contract v0.3 + solver v1; J3 (SFT data) and J5 (real forge fitness) need solver v1; J4 needs the J3 data, then the CEO frees a GPU.
- Next: when the solver lands, run J3 on the Mac (20k + 2k episodes), rsync it, submit J4 and send the id to the CEO; run J1 and J5 on the Mac in parallel (3 + 3 processes).
