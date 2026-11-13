# FR8 cluster

Everything lives in `~/momin/sleeper` on `ssh freighter`. Never run training on the login node.

    cluster/sync.sh                  rsync train/ and lab/ from origin/sleeper/lab-train-sft (REF=... to override) and cluster/ to FR8
    cluster/submit.sh pilot.sbatch   sbatch a script from cluster/
    ssh freighter 'squeue -u $USER'
    ssh freighter 'tail -f ~/momin/sleeper/logs/<name>-<jobid>.out'
    rsync -az freighter:momin/sleeper/results/ results/fr8/

Rules: partition gpu, `--gres=gpu:1`, always `--time`, V100 so fp16 only (no bf16, no FlashAttention-2), only cancel your own jobs. Module `pytorch-volta` runs commands via `pytorch-exec`. Models are pre-downloaded on the login node into `~/momin/sleeper/models/`.

Submit with env: `ssh freighter 'cd ~/momin/sleeper && MODEL=... sbatch --export=ALL cluster/train.sbatch'` (ask lead-lab first). HF_HOME is ~/momin/sleeper/hf, offline mode, checkpoints adapter-only in runs/<jobid>. eval.sbatch expects `train.eval` with --model --adapter --out (confirm with lab-train).
