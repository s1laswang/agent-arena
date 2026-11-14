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
python3 -c "import json,os;s=os.environ.get;print(json.dumps({'models':s('MODELS','Qwen/Qwen2.5-0.5B-Instruct').split(),'sft':s('SFT_ARGS','').split(),'eval':s('EVAL_ARGS','').split(),'decide':s('DECIDE_ARGS','').split(),'dump':bool(s('DUMP')),'steps':s('STEPS','sft decide eval').split(),'data':s('DATA_FILE','train.jsonl'),'sft_extra':{'Qwen2.5-1.5B-Instruct':s('SFT_ARGS_1_5B','').split()}}))" > $W/data/run.json
T0=$(date +%s)
for d in code data; do
  printf '{"title":"sleeper-%s","id":"%s/sleeper-%s","licenses":[{"name":"CC0-1.0"}]}' $d $U $d > $W/$d/dataset-metadata.json
  if $KG datasets status $U/sleeper-$d >/dev/null 2>&1; then
    $KG datasets version -p $W/$d -m "$(git rev-parse --short $REF)" -r zip
  else
    $KG datasets create -p $W/$d -r zip
  fi
  until [ "$($KG datasets status $U/sleeper-$d 2>&1 | tail -1)" = ready ]; do sleep 5; done
done
K=$W/kernel
cp -r cluster/kaggle/train $K
if [ -n "$ADAPTERS_DIR" ]; then
  mkdir $W/adapters
  for d in $ADAPTERS_DIR/*/adapter; do t=$(basename $(dirname $d)); mkdir -p $W/adapters/$t; cp -r $d $W/adapters/$t/adapter; done
  printf '{"title":"sleeper-adapters","id":"%s/sleeper-adapters","licenses":[{"name":"CC0-1.0"}]}' $U > $W/adapters/dataset-metadata.json
  if $KG datasets status $U/sleeper-adapters >/dev/null 2>&1; then $KG datasets version -p $W/adapters -m adapters -r zip; else $KG datasets create -p $W/adapters -r zip; fi
  until [ "$($KG datasets status $U/sleeper-adapters 2>&1 | tail -1)" = ready ]; do sleep 5; done
  python3 -c "import json,sys;p=sys.argv[1]+'/kernel-metadata.json';m=json.load(open(p));m['dataset_sources'].append('$U/sleeper-adapters');json.dump(m,open(p,'w'))" $K
fi
$KG kernels push -p $K
until s=$($KG kernels status $U/sleeper-train 2>&1 | tail -1); echo "$s"; case "$s" in *COMPLETE*|*ERROR*|*CANCEL*) true;; *) false;; esac; do sleep 30; done
OUT=results/train/$(date +%Y%m%d-%H%M%S)
mkdir -p $OUT
$KG kernels output $U/sleeper-train -p $OUT
rm -rf $W
echo "$(date +%F) $((($(date +%s)-T0)/60)) min wall $(git rev-parse --short $REF) $MODELS" >> cluster/kaggle/usage.log
echo $OUT
