# Canary: one-command entry points. Owners in brackets; replace the TODO echoes as you ship.
PROVIDER ?= template
AGENT ?= solver
TIER ?= all
SEEDS ?= dev20
UV := uv run --python 3.12 --extra dev --extra llm

.PHONY: setup test eval reproduce worlds clash gemini-check fr8-sync fr8-setup fr8-j1 fr8-j3 fr8-j5 fr8-pull mcp

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

fr8-setup:        ## [FR8] sync + build the Python env on the freighter login node
	bash fr8/sync.sh && ssh freighter 'bash ~/agent-arena/fr8/setup.sh'

fr8-j1:           ## [FR8] J1 calibration array (16 cores). Pilot: make fr8-j1 ARGS="--array=0 --export=ALL,J1_SEEDS=20"
	bash fr8/submit.sh j1 $(ARGS)

fr8-j3:           ## [FR8] J3 SFT data (8 cores). Keep total <=24: ARGS="--dependency=afterany:<id>"
	bash fr8/submit.sh j3 $(ARGS)

fr8-j5:           ## [FR8] J5 Mole Forge, stub LLM (8 cores)
	bash fr8/submit.sh j5 $(ARGS)

fr8-pull:         ## [FR8] make fr8-pull JOB=j1 -> data/fr8/j1/
	bash fr8/pull.sh $(JOB)
