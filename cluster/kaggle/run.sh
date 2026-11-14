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
python3 -c "import json,os;s=os.environ.get;print(json.dumps({'models':s('MODELS','Qwen/Qwen2.5-0.5B-Instruct').split(),'sft':s('SFT_ARGS','').split(),'eval':s('EVAL_ARGS','').split(),'decide':s('DECIDE_ARGS','').split(),'data':s('DATA_FILE','train.jsonl')}))" > $W/data/run.json
T0=$(date +%s)
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
echo "$(date +%F) $((($(date +%s)-T0)/60)) min wall $(git rev-parse --short $REF) $MODELS" >> cluster/kaggle/usage.log
echo $OUT
