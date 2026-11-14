PY ?= .venv/bin/python
SEAT ?= $(or $(SLEEPER_SEAT),finance_ap)
CACHE = data/gemini_cache.tar.gz
MCP_PORT ?= 8000
MCP_PORT_FALLBACK ?= 1
MCP_REWARD_PORT ?= 8001

test:
	$(PY) -m pytest -q

setup:
	@command -v python3.13 >/dev/null 2>&1 || { echo "make setup: python3.13 not found"; exit 127; }
	python3.13 -m venv .venv
	.venv/bin/pip install -r requirements.txt

# One-command judge reproduction (same work as eval). Prefer this name in the README.
reproduce: eval

mcp:
	@port=$$(MCP_PORT=$(MCP_PORT) MCP_PORT_FALLBACK=$(MCP_PORT_FALLBACK) bash scripts/mcp_port.sh); \
	rport=$$(MCP_PORT=$(MCP_REWARD_PORT) MCP_PORT_FALLBACK=$(MCP_PORT_FALLBACK) bash scripts/mcp_port.sh); \
	echo "make mcp: sidecar MCP http://127.0.0.1:$$port/mcp  reward :$$rport  (override: make mcp MCP_PORT=8800; fail if busy: MCP_PORT_FALLBACK=0)"; \
	SLEEPER_SEED=$${SLEEPER_SEED:-1000} SLEEPER_SEAT=$${SLEEPER_SEAT:-$(SEAT)} \
	SLEEPER_OUT=$${SLEEPER_OUT:-/tmp/sleeper-mcp-state.json} VERIFY_TOKEN=$${VERIFY_TOKEN:-judge-local} \
	SIDECAR_MCP_PORT=$$port SIDECAR_REWARD_PORT=$$rport \
	$(PY) -m harbor.sidecar

accept:
	bash scripts/judge_accept.sh

# Keyless check of committed frontier rows: re-issue their tool calls, re-score, then
# the paired gap against a fresh evidence-only reference on the same finance_ap days.
# Historical rows were recorded before ticket renumbering, so a match under 100% is
# reported as measured; it is not rewritten.
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
	GEMINI_API_KEY= $(PY) -m scripts.probes --days 3

eval-full:
	$(PY) -m lab.eval --full
	$(PY) -m sleeper.baselines

harbor:
	$(PY) -m harbor.build --seeds 0..19 --seat $(SEAT)

.PHONY: probes frontier-replay-run test eval eval-full harbor exploits key-check cheat-corpus setup reproduce mcp accept gap-replay

exploits:
	$(PY) -m redteam.report

key-check:
	PYTHONPATH=. $(PY) scripts/key_check.py

ladder:
	GEMINI_API_KEY= $(PY) -m agents.ladder --days 400 --jobs 6

.PHONY: ladder

cheat-corpus:
	GEMINI_API_KEY= PYTHONPATH=. $(PY) -m redteam.cheat_corpus $(ARGS)

cheat-eval:
	GEMINI_API_KEY= PYTHONPATH=. $(PY) -m redteam.cheat_eval

.PHONY: demo
demo:
	@echo "http://localhost:8000/index.html"; $(PY) -m http.server 8000 -d web

frontier-replay-run:
	$(PY) -m lab.frontier_cache replay $(RUN)
