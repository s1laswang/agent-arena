#!/bin/bash
set -e
cd "$(dirname "$0")/.."
REF=${REF:-origin/momin}
git fetch -q origin
T=$(mktemp -d)
git archive $REF train lab | tar -x -C $T
ssh freighter 'mkdir -p ~/momin/sleeper/logs ~/momin/sleeper/results ~/momin/sleeper/runs'
rsync -az --delete $T/train/ freighter:momin/sleeper/train/
rsync -az --delete $T/lab/ freighter:momin/sleeper/lab/
rsync -az --delete cluster/ freighter:momin/sleeper/cluster/
rsync -az requirements.txt freighter:momin/sleeper/requirements.txt
rm -rf $T
