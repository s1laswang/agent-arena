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

## 02:24 status
- Done (verified: 153k local episodes; the hard cell spot-checked against raw CSV): the J1 recalibration. The CEO adopted it verbatim as tiers v1 (ENV 54e1fa4), with JUDGE_SEEDS=40 per tier. Recommendation: `fr8/analysis/out/j1_recommendation.md`. Ops' bonus FR8 copy of J1 (job 43872, 306 tasks) also completed.
- Done (verified: export manifests): J3 on tiers v1: 20k train + 2k val solver episodes on TRAIN seeds, keeping only correct accusations (easy 100% kept; medium and hard ~80%), 1.1 GB, at `freighter:~/agent-arena-data/j3`. The data dir is 4.0 GB of 10.
- Submitted: **J4 = job 44200** (gpu:1, -c 6, 28G, 6 h), PENDING (Priority). The CEO is pausing sky task 43143_4 to free a GPU.
- Running on FR8: J2 fuzz = job 43864 (8 cores, INTEGRITY's job).
- Restarted: J5 forge. The first run mixed rule versions because forge workers re-import code each generation and I merged tiers v1 mid-run, so it's marked INVALID. The new run uses a frozen tiers-v1 snapshot (`wt/justSilas-fr8-j5run`): hard, pop 24 × 500 gens × 40 seeds, 3 processes. Its hall of fame is on tiers v1 by construction.
- In progress: ops is running the solver τ sweep (τ 0.70–0.99, 200 seeds, 1 process); ENV wants it re-run after the solver's stopping-rule fix. The v0.4 fingerprint rerun is on hold (CEO).
- Done (untested on device): the MLX fallback (`train/mlx_lora.sh`, `eval_hf --backend mlx`). Nothing was run tonight because of Mac memory.
- Mac processes: J5 3 + τ sweep 1.

## 03:10 status
- **Tiers v1.2 (frozen by ENV at db104c9)** came from FR8's co-tune: hard fingerprint_accuracy 0.95, framing_rate 2.0, behaviour_weight 0.6.
  - Verified with `fr8/confirm_cell.py` on 800 FRESH dev seeds (200–999): hard solver acc 0.841, no-accusation 0.126; medium − hard paired 0.070 ± 0.032.
  - The 200-seed co-tune winner (hard fp 0.9) did NOT replicate on fresh seeds (acc 0.79), so every reported number is now checked on fresh seeds.
  - Earlier finding: J1 was calibrated on a pre-v0.3 solver. Rerun on current code (`data/fr8/j1v1`). The τ sweep shows the accusation threshold barely matters (`data/fr8/tau`).
- **J5 forge** (stub mutator, hard tier v1, frozen snapshot): pop 24 × 500 gens done; best fitness 1.789. Chart: `fr8/analysis/out/forge_run-v1-final/`.
  - Re-validated on frozen v1.2 hard (fresh seeds 2000–2199): 20 HOF entries collapse to **2 distinct moles**, both §7-feasible. Solver 0.617, acc 0.855; regret 1.51 / 1.39 vs the default mole's 0.81.
  - Published as `data/forge/hall_of_fame_v1.2.jsonl` for ENV's hard_forge track (on justSilas af98330).
  - Flag: with the default mole, v1.2 hard solver acc is 0.79 (n=200) to 0.84 (n=800), below 0.85.
- **J2 fuzz:** v1.1 hard (44243) and medium (44244): 4M evolve each, 0 findings, 0 violations. Final v1.2 run (44263/44264) completed; summaries go to INTEGRITY.
- **J4 = job 44200** on a V100 (compute04), started 02:24.
  - Still in the pilot: tokenization of 20k episodes takes ~75 min on 1 core, so the first throughput is expected ~03:40.
  - Patched `train/lora_sft.py` for the train stage: 6-process tokenization, a window cache, and max-hours clamped to job end minus 90 min (via a deadline file). Verified inside the job.
  - Sky 43143_4 is paused by the CEO; FR8 messages the CEO when J4 ends or at 08:30.
- **Next:** J3 v2 data on v1.2 (03:40, for Saturday's v2 training); README table on 1,000 fresh seeds (ops); J4 throughput → CEO.
