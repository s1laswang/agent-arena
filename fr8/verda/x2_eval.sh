#!/bin/bash
# X2 DAgger held-out eval (runs ON a Verda box): eval_hf, greedy, KV reuse, 8k ctx, call cap 120.
# ADAPTER=/root/x2/dagger-r1/lora OFFSET=0 N=15 RUN=dagger-r1-off0 bash fr8/verda/x2_eval.sh
set -uo pipefail
export PYTHONUNBUFFERED=1 TOKENIZERS_PARALLELISM=false
# shared held-out world secret (FR8, sha256[:10]=1ca0c2a64d): every X2 eval uses it, so DAgger and v3-4k s0 pair
[ -s /root/x2/world_secret ] || { echo "missing /root/x2/world_secret" >&2; exit 2; }
export CANARY_WORLD_SECRET="$(cat /root/x2/world_secret)"
. /root/venv/bin/activate
cd /root/x2/agent-arena
python -c "import json,sys; p='$ADAPTER/adapter_config.json'; c=json.load(open(p)); c['base_model_name_or_path']='/root/models/Qwen2.5-1.5B-Instruct'; json.dump(c,open(p,'w'),indent=1)"
python -m train.eval_hf --model "$ADAPTER" --tiers easy,medium,hard --seeds heldout --n "$N" --seed-offset "$OFFSET" \
  --max-calls 120 --max-new-tokens ${NEW:-96} --max-ctx ${CTX:-8192} --max-minutes ${EVAL_MIN:-130} --out /root/x2/evals --run-id "$RUN" \
  > /root/x2/eval-$RUN.log 2>&1
touch /root/x2/evals/DONE-$RUN
