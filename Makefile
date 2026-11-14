# Canary: one-command entry points. Owners in brackets; replace the TODO echoes as you ship.
PROVIDER ?= template
AGENT ?= solver
TIER ?= all
SEEDS ?= dev20
MCP_PORT ?= 8765
MCP_PORT_FALLBACK ?= 1
UV := uv run --python 3.12 --extra dev --extra llm --extra plot

.PHONY: play setup test eval reproduce reproduce-update anticheat-verify worlds clash gemini-check fr8-sync fr8-setup fr8-j1 fr8-j3 fr8-j5 fr8-pull mcp hunt game game-serve accept

setup:            ## install deps (needs uv: curl -LsSf https://astral.sh/uv/install.sh | sh)
	@command -v uv >/dev/null 2>&1 || { echo "make setup: uv not found. Install it with: curl -LsSf https://astral.sh/uv/install.sh | sh  (then open a new shell)"; exit 127; }
	uv sync --python 3.12 --extra dev --extra llm --extra plot

test:             ## unit + integrity tests (must be green before merging into justSilas)
	$(UV) pytest -q

eval:             ## [HARNESS] make eval AGENT=solver|baselines|openai:<model>|gemini:<model> PROVIDER=template|gemini TIER=easy|medium|hard|all
	$(UV) python -m canary.eval --agent $(AGENT) --provider $(PROVIDER) --tier $(TIER) --seeds $(SEEDS)

reproduce:        ## [HARNESS] judge table on the frozen judge seeds (no keys) -> results/latest/ (gitignored; committed results/ untouched). REPRO_FAST=1 = 5 seeds/tier
	$(UV) python -m canary.eval --reproduce

anticheat-verify: ## [INTEGRITY] rerun the committed 40-judge-seed anti-cheat battery (public test secret) and diff it with results/anticheat/exploits.json (exit 1 on any difference)
	$(UV) python -m canary.redteam.anticheat --verify results/anticheat/exploits.json

reproduce-update: ## [HARNESS] team only: rerun reproduce and overwrite the committed results/judge_table.md, judge_episodes.jsonl, gap_chart.png
	$(UV) python -m canary.eval --reproduce --update-committed

mcp:              ## [HARNESS] MCP env server (streamable HTTP). Port: MCP_PORT (default 8765). If busy, MCP_PORT_FALLBACK=1 (default) picks the next free port and prints it; set 0 to fail instead.
	@port=$$(MCP_PORT=$(MCP_PORT) MCP_PORT_FALLBACK=$(MCP_PORT_FALLBACK) bash scripts/mcp_port.sh); \
	echo "make mcp: http://127.0.0.1:$$port/mcp  (override: make mcp MCP_PORT=88765; fail if busy: MCP_PORT_FALLBACK=0)"; \
	umask 077; d=$$(mktemp -d); \
	printf '{"tier": "%s", "seed": %s}' "$${CANARY_TIER:-easy}" "$${CANARY_SEED:-900000}" > $$d/episode.json; \
	if [ -n "$${CANARY_LEDGER_TOKEN:-}" ]; then printf %s "$$CANARY_LEDGER_TOKEN" > $$d/ledger_token; export CANARY_LEDGER_TOKEN_FILE=$$d/ledger_token; fi; \
	exec env -u CANARY_TIER -u CANARY_SEED -u CANARY_LEDGER_TOKEN CANARY_CONSUME_SECRET_FILES=1 CANARY_EPISODE_FILE=$$d/episode.json CANARY_PORT=$$port $(UV) python -m canary.mcp_server

accept:           ## [HARNESS] keyless judge acceptance: setup, reproduce, baseline checks, MCP smoke. Exit non-zero on any failure.
	bash scripts/judge_accept.sh

game:             ## [HARNESS] build the static browser game (real canary package in Pyodide) into game/site/
	$(UV) python game/build.py

game-serve: game  ## [HARNESS] build and serve the browser game at http://localhost:8000
	$(UV) python -m http.server -d game/site 8000

hunt:             ## [INTEGRITY] judges' exploit playground (no keys, a few minutes): random/malformed/evolved/parallel-accuse fuzzing on every tier; prints best non-solver score vs solver. Real-MCP attacks: pytest tests/test_integrity_mcp.py
	@for t in $(if $(filter all,$(TIER)),easy medium hard hard_forge,$(TIER)); do \
	  echo "== $$t"; $(UV) python -m canary.redteam.fuzz --mode all --tier $$t --seeds 0-49 --budget 20000 --report || exit 1; done

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

play:             ## [ENV] human playtest: make play TIER=medium NAME=alice SEED=3000
	$(UV) python -m canary.play --tier $(if $(filter all,$(TIER)),medium,$(TIER)) --name $(or $(NAME),human) --seed "$(SEED)"

# Canary Lab (Gemini)
lab-replay:       ## [GEMINI] keyless: replay every recorded Gemini run (results/gemini/replay*) through a local gateway
	$(UV) python -m canary.gemini.lab_replay

lab-record:       ## [GEMINI] re-record the showcase (needs GEMINI_API_KEY, 6 calls). Ladder: python -m canary.gemini.lab_replay --record NAME -- <cmd {out}>
	rm -rf results/gemini/replay && $(UV) python -m canary.gemini.with_gateway --record results/gemini/replay -- \
	  python -m canary.gemini.showcase --write results/gemini/replay/showcase.json

lab-gateway:      ## [GEMINI] run the gateway locally: make lab-gateway ARGS="--port 8787 --record data/gemini/rec"
	$(UV) python -m canary.gemini.gateway $(ARGS)

lab-dashboard:    ## [GEMINI] keyless: ledger + results/gemini/*.json -> results/gemini/dashboard.html (ARGS="--ledger auto" finds every local ledger)
	$(UV) python -m canary.gemini.dashboard $(ARGS)
