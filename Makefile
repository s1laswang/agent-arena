PY ?= .venv/bin/python
SEAT ?= $(or $(SLEEPER_SEAT),finance_ap)
CACHE = data/gemini_cache.tar.gz
MCP_PORT ?= 8000
MCP_PORT_FALLBACK ?= 1
MCP_REWARD_PORT ?= 8001

.PHONY: test setup reproduce frontier-replay mcp accept gap-replay eval probes eval-full harbor exploits key-check ladder ladder-drop cheat-corpus cheat-eval demo frontier-replay-run

test:
	$(PY) -m pytest -q

setup:
	bash scripts/setup_env.sh

reproduce:
	SLEEPER_REPRODUCE_ACTIVE=1 SLEEPER_OFFLINE=1 GEMINI_API_KEY= $(PY) -m lab.reproduce

frontier-replay:
	@if [ "$${SLEEPER_REPRODUCE_ACTIVE:-0}" = "1" ]; then exit 0; fi; SLEEPER_OFFLINE=1 GEMINI_API_KEY= $(PY) -m lab.frontier_replay --strict

mcp:
	@set -e; \
	port=$$(MCP_PORT=$(MCP_PORT) MCP_PORT_FALLBACK=$(MCP_PORT_FALLBACK) PYTHON_BIN=$(PY) bash scripts/mcp_port.sh) || exit $$?; \
	rport=$$(MCP_PORT=$(MCP_REWARD_PORT) MCP_PORT_FALLBACK=$(MCP_PORT_FALLBACK) MCP_AVOID_PORT=$$port PYTHON_BIN=$(PY) bash scripts/mcp_port.sh) || exit $$?; \
	echo "make mcp: sidecar MCP http://127.0.0.1:$$port/mcp  reward :$$rport  (override: make mcp MCP_PORT=8800; fail if busy: MCP_PORT_FALLBACK=0)"; \
	if [ "$${MCP_DRY_RUN:-0}" = "1" ]; then exit 0; fi; \
	sfile=$$(SLEEPER_SALT="$${SLEEPER_SALT:-}" SLEEPER_SEED="$${SLEEPER_SEED:-1000}" VERIFY_TOKEN="$${VERIFY_TOKEN:-}" $(PY) -c 'import json,os,secrets,tempfile; e=os.environ.get; v={"SLEEPER_SALT":e("SLEEPER_SALT") or secrets.token_hex(16),"SLEEPER_SEED":e("SLEEPER_SEED") or "1000","VERIFY_TOKEN":e("VERIFY_TOKEN") or secrets.token_hex(16)}; d=tempfile.mkdtemp(prefix="sleeper-mcp-"); w=lambda n,s: os.close((lambda fd: (os.write(fd,s.encode()),fd)[1])(os.open(os.path.join(d,n),os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600))); w("secrets.json",json.dumps(v)); w("reward-token",v["VERIFY_TOKEN"]); print(os.path.join(d,"secrets.json"))') || exit $$?; \
	sdir=$$(dirname "$$sfile"); \
	trap 'rm -rf "$$sdir"' EXIT INT TERM; \
	echo "make mcp: reward: curl -s -H \"X-Verify-Token: \$$(cat $$sdir/reward-token)\" http://127.0.0.1:$$rport/reward"; \
	env -u SLEEPER_SALT -u SLEEPER_SEED -u VERIFY_TOKEN SLEEPER_SECRETS_FILE="$$sfile" SLEEPER_SECRETS_UNLINK=1 SLEEPER_SEAT="$${SLEEPER_SEAT:-$(SEAT)}" SLEEPER_OUT="$${SLEEPER_OUT:-/tmp/sleeper-mcp-state.json}" SIDECAR_MCP_PORT="$$port" SIDECAR_REWARD_PORT="$$rport" $(PY) -m harbor.sidecar

accept:
	bash scripts/judge_accept.sh

gap-replay:
	SLEEPER_OFFLINE=1 GEMINI_API_KEY= $(PY) -m lab.run --team procedure --seat finance_ap --agent reference --days 5 --day-start 1000 --trials 1 --out results/frontier/scripted-procedure/reference-v2
	SLEEPER_OFFLINE=1 GEMINI_API_KEY= $(PY) -m lab.action_replay $(shell find results/frontier -type f \( -name 'finance_ap-s*.json' ! -name 'summary*' ! -name '*.state.json' \))
	$(PY) -m lab.paired_gap --ref "results/frontier/scripted-procedure/reference-v2/*/days.jsonl" --agent "results/frontier/gemini-3.5-flash/b06e6ad/finance_ap-s*.json" --label "gemini-3.6-flash (requested as gemini-3.5-flash; unverified, no state dump)"

eval:
	if [ -f $(CACHE) ]; then $(PY) scripts/gemini_cache.py unpack $(CACHE) && SLEEPER_OFFLINE=1 $(PY) -m lab.eval; else $(PY) -m lab.eval; fi
	$(PY) -m lab.gaptable results/frontier --replay
	cat results/frontier/gaptable.md >> results/eval/REPORT.md
	$(MAKE) probes

probes:
	@if $(PY) -m scripts.probes --help 2>&1 | grep -q -- --out-dir; then GEMINI_API_KEY= $(PY) -m scripts.probes --days 3 --out-dir results/eval; else GEMINI_API_KEY= $(PY) -m scripts.probes --days 3; fi

eval-full:
	$(PY) -m lab.eval --full
	$(PY) -m sleeper.baselines

harbor:
	$(PY) -m harbor.build --seeds 0..19 --seat $(SEAT)

exploits:
	$(PY) -m redteam.report

key-check:
	PYTHONPATH=. $(PY) scripts/key_check.py

ladder:
	GEMINI_API_KEY= $(PY) -m agents.ladder --days 400 --jobs 6

cheat-corpus:
	GEMINI_API_KEY= PYTHONPATH=. $(PY) -m redteam.cheat_corpus $(ARGS)

cheat-eval:
	GEMINI_API_KEY= PYTHONPATH=. $(PY) -m redteam.cheat_eval

ladder-drop:
	GEMINI_API_KEY= $(PY) -m agents.ladder_drop --days 200 --jobs 4

demo:
	@echo "http://localhost:8000/index.html"; $(PY) -m http.server 8000 -d web

frontier-replay-run:
	$(PY) -m lab.frontier_cache replay $(RUN)
