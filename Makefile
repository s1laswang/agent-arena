# Canary: one-command entry points. Owners in brackets; replace the TODO echoes as you ship.
PROVIDER ?= template
AGENT ?= solver
TIER ?= all
SEEDS ?= dev20
UV := uv run --python 3.12 --extra dev --extra llm

.PHONY: setup test eval reproduce worlds clash gemini-check fr8-sync mcp

setup:            ## install deps (uv)
	uv sync --python 3.12 --extra dev --extra llm

test:             ## unit + integrity tests (must be green before merging into justSilas)
	$(UV) pytest -q

eval:             ## [HARNESS] make eval AGENT=solver|baselines|openai:<model>|gemini:<model> PROVIDER=template|gemini TIER=easy|medium|hard|all
	$(UV) python -m canary.eval --agent $(AGENT) --provider $(PROVIDER) --tier $(TIER) --seeds $(SEEDS)

reproduce:        ## [HARNESS] judge table: reference + 3 agent runs + do-nothing + stop-early on frozen judge seeds, no keys needed
	$(UV) python -m canary.eval --reproduce

mcp:              ## [HARNESS] run the MCP env server (streamable HTTP)
	$(UV) python -m canary.mcp_server

worlds:           ## [ENV] (re)generate frozen world text for judge seeds: make worlds PROVIDER=gemini
	$(UV) python -m canary.text.build --provider $(PROVIDER) --seeds judge

clash:            ## [AGENTS] Gemini mole vs investigators + scenario designer (needs GEMINI_API_KEY)
	$(UV) python -m canary.agents.clash

gemini-check:     ## [AGENTS] 1-call smoke test of GEMINI_API_KEY
	$(UV) python -m canary.llm.check gemini

fr8-sync:         ## [FR8] rsync code to freighter:~/agent-arena (private repo cannot be cloned there)
	bash fr8/sync.sh
