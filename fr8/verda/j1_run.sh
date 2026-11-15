#!/bin/bash
# J1-lite on a Verda A100-80G: vLLM Qwen3-14B (bf16) on localhost + canary.agents.play, 10 hard + 10 medium dev seeds.
set -uo pipefail
export PATH=$HOME/.local/bin:$PATH HF_HOME=/dev/shm/hf     # model in RAM: the 48 GB disk can't hold model + vLLM
M=${M:-Qwen/Qwen3-14B}
mkdir -p /root/j1 && cd /root/j1
date -u +"start %FT%TZ" > /root/j1/times.txt
command -v uv >/dev/null || curl -LsSf https://astral.sh/uv/install.sh | sh
[ -d agent-arena ] || git clone -q https://github.com/s1laswang/agent-arena
cd agent-arena && git fetch -q origin gemini-ladder && git checkout -q origin/gemini-ladder && git log --oneline -1
[ -x /root/vllm-env/bin/vllm ] || { uv venv -q --clear --python 3.12 /root/vllm-env && uv pip install -q --python /root/vllm-env/bin/python vllm; }
uv sync -q --extra llm --extra dev
/root/vllm-env/bin/vllm serve $M --port 8000 --max-model-len 131072 \
  --hf-overrides '{"rope_scaling":{"rope_type":"yarn","factor":4.0,"original_max_position_embeddings":32768},"max_position_embeddings":131072}' \
  --enable-auto-tool-choice --tool-call-parser hermes --reasoning-parser qwen3 \
  --enable-prefix-caching --gpu-memory-utilization 0.92 > /root/j1/vllm.log 2>&1 &
echo $! > /root/j1/vllm.pid
for i in $(seq 1 120); do curl -sf localhost:8000/v1/models >/dev/null && break; kill -0 $(cat /root/j1/vllm.pid) 2>/dev/null || break; sleep 15; done
curl -sf localhost:8000/v1/models >/dev/null || { echo "vLLM did not come up"; tail -5 /root/j1/vllm.log; exit 2; }
date -u +"vllm_up %FT%TZ" >> /root/j1/times.txt
export OPENAI_BASE_URL=http://localhost:8000/v1 OPENAI_API_KEY=EMPTY
mkdir -p logs runs
B=$(basename $M)
# smoke: one hard episode must finish within 30 min
timeout 1800 uv run python -m canary.agents.play --agent openai:$M --api chat --tier hard --seeds 0 --out runs/j1/$B/hard/0 > logs/j1-hard-0.log 2>&1
echo "smoke rc=$?" | tee -a /root/j1/times.txt
ls runs/j1/$B/hard/0 >> /root/j1/times.txt 2>&1
for T in hard medium; do for S in 0 1 2 3 4 5 6 7 8 9; do
  [ "$T$S" = hard0 ] && continue
  uv run python -m canary.agents.play --agent openai:$M --api chat --tier $T --seeds $S --out runs/j1/$B/$T/$S > logs/j1-$T-$S.log 2>&1 &
  while [ $(jobs -r | wc -l) -ge 9 ]; do sleep 20; done      # 8 episodes + vLLM
done; done
while [ $(jobs -r | wc -l) -gt 1 ]; do sleep 20; done
date -u +"end %FT%TZ" >> /root/j1/times.txt
kill $(cat /root/j1/vllm.pid)
touch /root/j1/DONE
