#!/bin/bash
# J1-lite (capped): Qwen3-14B thinking ON, server-default max 4096 output tokens/turn; HARD dev seeds 0-9 all concurrent;
# medium 0-9 only if hard finishes before 04:15 UTC (06:15 Helsinki).
set -uo pipefail
export PATH=/root/vllm-env/bin:$HOME/.local/bin:$PATH HF_HOME=/dev/shm/hf
M=Qwen/Qwen3-14B; B=$(basename $M)
cd /root/j1/agent-arena
date -u +"capped_start %FT%TZ" >> /root/j1/times.txt
vllm serve $M --port 8000 --max-model-len 131072 \
  --hf-overrides '{"rope_scaling":{"rope_type":"yarn","factor":4.0,"original_max_position_embeddings":32768},"max_position_embeddings":131072}' \
  --override-generation-config '{"max_new_tokens": 4096}' \
  --enable-auto-tool-choice --tool-call-parser hermes --reasoning-parser qwen3 \
  --enable-prefix-caching --gpu-memory-utilization 0.92 > /root/j1/vllm2.log 2>&1 &
echo $! > /root/j1/vllm.pid
for i in $(seq 1 80); do curl -sf localhost:8000/v1/models >/dev/null && break; kill -0 $(cat /root/j1/vllm.pid) 2>/dev/null || break; sleep 15; done
curl -sf localhost:8000/v1/models >/dev/null || { echo "vLLM did not come up"; tail -5 /root/j1/vllm2.log; exit 2; }
date -u +"capped_vllm_up %FT%TZ" >> /root/j1/times.txt
export OPENAI_BASE_URL=http://localhost:8000/v1 OPENAI_API_KEY=EMPTY
mkdir -p logs runs
for S in 0 1 2 3 4 5 6 7 8 9; do
  uv run python -m canary.agents.play --agent openai:$M --api chat --tier hard --seeds $S --out runs/j1/$B/hard/$S > logs/j1-hard-$S.log 2>&1 &
done
while [ $(jobs -r | wc -l) -gt 1 ]; do sleep 30; done
date -u +"hard_end %FT%TZ" >> /root/j1/times.txt
if [ $(date -u +%H%M) -lt 0415 ]; then
  for S in 0 1 2 3 4 5 6 7 8 9; do
    uv run python -m canary.agents.play --agent openai:$M --api chat --tier medium --seeds $S --out runs/j1/$B/medium/$S > logs/j1-medium-$S.log 2>&1 &
  done
  while [ $(jobs -r | wc -l) -gt 1 ]; do sleep 30; done
  date -u +"medium_end %FT%TZ" >> /root/j1/times.txt
fi
kill $(cat /root/j1/vllm.pid); touch /root/j1/DONE
