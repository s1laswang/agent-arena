#!/bin/bash
set -e
cd "$(dirname "$0")/../.."
KG=cluster/kaggle/kg.sh
U=mominaldahdouh
REF=${REF:-origin/momin}
W=$(mktemp -d)
git fetch -q origin
mkdir $W/code $W/data
git archive $REF lab train sleeper agents requirements.txt | tar -x -C $W/code
cp train/data/*.jsonl $W/data/
echo "$SFT_ARGS" > $W/data/sft_args.txt
echo "$EVAL_ARGS" > $W/data/eval_args.txt
for d in code data; do
  printf '{"title":"sleeper-%s","id":"%s/sleeper-%s","licenses":[{"name":"CC0-1.0"}]}' $d $U $d > $W/$d/dataset-metadata.json
  if $KG datasets status $U/sleeper-$d >/dev/null 2>&1; then
    $KG datasets version -p $W/$d -m "$(git rev-parse --short $REF)" -r zip
  else
    $KG datasets create -p $W/$d -r zip
  fi
done
$KG kernels push -p cluster/kaggle/train
until s=$($KG kernels status $U/sleeper-train 2>&1 | tail -1); echo "$s"; case "$s" in *COMPLETE*|*ERROR*|*CANCEL*) true;; *) false;; esac; do sleep 30; done
OUT=results/train/$(date +%Y%m%d-%H%M%S)
mkdir -p $OUT
$KG kernels output $U/sleeper-train -p $OUT
rm -rf $W
echo $OUT
