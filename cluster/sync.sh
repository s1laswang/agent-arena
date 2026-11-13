#!/bin/bash
set -e
cd "$(dirname "$0")/.."
REF=${REF:-origin/sleeper/lab-train-sft}
git fetch -q origin
T=$(mktemp -d)
git archive $REF train lab | tar -x -C $T
ssh freighter 'mkdir -p ~/momin/sleeper/logs ~/momin/sleeper/results ~/momin/sleeper/runs'
rsync -az --delete $T/train/ freighter:momin/sleeper/train/
rsync -az --delete $T/lab/ freighter:momin/sleeper/lab/
rsync -az --delete cluster/ freighter:momin/sleeper/cluster/
rm -rf $T
