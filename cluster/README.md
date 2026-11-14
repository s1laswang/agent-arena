# FR8 cluster

Everything lives in `~/momin/sleeper` on `ssh freighter`. Never run training on the login node.

    cluster/sync.sh                  rsync train/ and lab/ from origin/sleeper/lab-train-sft (REF=... to override) and cluster/ to FR8
    cluster/submit.sh pilot.sbatch   sbatch a script from cluster/
    ssh freighter 'squeue -u $USER'
    ssh freighter 'tail -f ~/momin/sleeper/logs/<name>-<jobid>.out'
    rsync -az freighter:momin/sleeper/results/ results/fr8/

Rules: partition gpu, `--gres=gpu:1`, always `--time`, V100 so fp16 only (no bf16, no FlashAttention-2), only cancel your own jobs. Module `pytorch-volta` runs commands via `pytorch-exec`. Models are pre-downloaded on the login node into `~/momin/sleeper/models/`.

Submit with env: `ssh freighter 'cd ~/momin/sleeper && MODEL=... sbatch --export=ALL cluster/train.sbatch'` (ask lead-lab first). HF_HOME is ~/momin/sleeper/hf, offline mode, checkpoints adapter-only in runs/<jobid>. eval.sbatch expects `train.eval` with --model --adapter --out (confirm with lab-train).

## Kaggle (main training path)

`cluster/kaggle/run.sh`: uploads code snapshot + train/data/*.jsonl as private datasets, runs kernel mominaldahdouh/sleeper-train, fetches to results/train/<ts>/. Env: MODELS (space separated, one per GPU), SFT_ARGS, EVAL_ARGS, DECIDE_ARGS, DATA_FILE, REF. Kernel writes metrics.json with all rows. Quota 30 GPU h/week, wall minutes per run appended to cluster/kaggle/usage.log. Used so far: about 40 min wall (rough, dry runs approximate; 2 GPUs may count double).

## Reproduce the tiebreaker

Runs are logged in `train/runs.jsonl`. Run from the repo root with Kaggle credentials set (`cluster/kaggle/kg.sh` wraps the CLI). Do not launch two kernels at once: they share the slug `mominaldahdouh/sleeper-train` and the weekly quota.

Rebuild the training data (training days 0-99, held-out days are 1000+):

    python -m lab.run --team oracle --seat finance_ap --day-start 0 --days 100 --trials 1 --out <oracle_run>   # finance_ap teacher: add --agent local:careful_fin
    python -m train.build_data <oracle_run> train/data finance_ap [--force]   # writes train/data/train.jsonl (UP=3, KEEP=0.25 in build_data.py)

Exact data-build flags for run1, run2 and run5 were not recorded. `train.jsonl` in the code snapshot is what each run used.

| run | command (all via `cluster/kaggle/run.sh`) | wall |
|---|---|---|
| run1, 0.5B, controller | `MODELS=Qwen/Qwen2.5-0.5B-Instruct SFT_ARGS="--epochs 2" EVAL_ARGS="--day-ids 1000-1019" cluster/kaggle/run.sh` | 32 min |
| run2, 0.5B + 1.5B, controller | `MODELS="Qwen/Qwen2.5-0.5B-Instruct Qwen/Qwen2.5-1.5B-Instruct" SFT_ARGS="--epochs 1 --grad-ckpt" cluster/kaggle/run.sh`, then decide rerun on saved adapters: `STEPS=decide ADAPTERS_DIR=<run dir> DECIDE_ARGS="--min-day 1000" MODELS=... cluster/kaggle/run.sh` | 31 min + 6 min |
| run5 | launch line not recorded | about 8 min (decide only) |
| run3, 0.5B + 1.5B, finance_ap | see below | about 35 min expected |

run3 (REF is the commit with the fixed `train.py`, `origin/momin` c6e69f5 or later):

    REF=origin/momin MODELS="Qwen/Qwen2.5-0.5B-Instruct Qwen/Qwen2.5-1.5B-Instruct" \
    SFT_ARGS="--epochs 1 --grad-ckpt --max_len 3072" SFT_ARGS_1_5B="--batch 1 --accum 16" \
    ORACLE_ARGS="--seat finance_ap --agent local:careful_fin" DECIDE_ARGS="--seat finance_ap" \
    EVAL_ARGS="--day-ids 1000-1019 --seat finance_ap" cluster/kaggle/run.sh

`run.sh` refuses to start unless `DECIDE_ARGS` contains `--seat`. Per-point dump for diffing adapters: add `DUMP=1` (writes `dump_base.jsonl` and `dump_adapter.jsonl` per model).

Quota and time: Kaggle gives 30 GPU hours per week on 2x T4; a full two-model run takes 30-35 min wall and may count double (2 GPUs), so about 1 GPU hour. Total used so far is in `cluster/kaggle/usage.log` (about 2.5 h wall on 2026-11-14 including dry runs). Models are 0.5B and 1.5B Qwen2.5 Instruct, LoRA r16, fp16 (T4 has no bf16).
