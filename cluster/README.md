# FR8 cluster

Everything lives in `~/momin/sleeper` on `ssh freighter`. Never run training on the login node.

    cluster/sync.sh                  rsync train/ and cluster/ to FR8
    cluster/submit.sh pilot.sbatch   sbatch a script from cluster/
    ssh freighter 'squeue -u $USER'
    ssh freighter 'tail -f ~/momin/sleeper/logs/<name>-<jobid>.out'
    rsync -az freighter:momin/sleeper/results/ results/fr8/

Rules: partition gpu, `--gres=gpu:1`, always `--time`, V100 so fp16 only (no bf16, no FlashAttention-2), only cancel your own jobs. Module `pytorch-volta` runs commands via `pytorch-exec`. Models are pre-downloaded on the login node into `~/momin/sleeper/models/`.
