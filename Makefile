# Canary: one-command entry points. Owners in brackets; replace the TODO echoes as you ship.
PROVIDER ?= template
AGENT ?= solver
TIER ?= all
SEEDS ?= dev20
UV := uv run --python 3.12 --extra dev --extra llm --extra plot

.PHONY: play setup test eval reproduce reproduce-update worlds clash gemini-check fr8-sync fr8-setup fr8-j1 fr8-j3 fr8-j5 fr8-pull mcp hunt game game-serve

setup:            ## install deps (needs uv: curl -LsSf https://astral.sh/uv/install.sh | sh)
	@command -v uv >/dev/null 2>&1 || { echo "make setup: uv not found. Install it with: curl -LsSf https://astral.sh/uv/install.sh | sh  (then open a new shell)"; exit 127; }
	uv sync --python 3.12 --extra dev --extra llm --extra plot

test:             ## unit + integrity tests (must be green before merging into justSilas)
	$(UV) pytest -q

eval:             ## [HARNESS] make eval AGENT=solver|baselines|openai:<model>|gemini:<model> PROVIDER=template|gemini TIER=easy|medium|hard|all
	$(UV) python -m canary.eval --agent $(AGENT) --provider $(PROVIDER) --tier $(TIER) --seeds $(SEEDS)

reproduce:        ## [HARNESS] judge table on the frozen judge seeds (no keys) -> results/latest/ (gitignored; committed results/ untouched). REPRO_FAST=1 = 5 seeds/tier
	$(UV) python -m canary.eval --reproduce

reproduce-update: ## [HARNESS] team only: rerun reproduce and overwrite the committed results/judge_table.md, judge_episodes.jsonl, gap_chart.png
	$(UV) python -m canary.eval --reproduce --update-committed

mcp:              ## [HARNESS] run the MCP env server (streamable HTTP). CANARY_TIER/SEED/LEDGER_TOKEN are moved into 0600 files (CANARY_EPISODE_FILE), never left in the server env
	@umask 077; d=$$(mktemp -d); \
	printf '{"tier": "%s", "seed": %s}' "$${CANARY_TIER:-easy}" "$${CANARY_SEED:-900000}" > $$d/episode.json; \
	if [ -n "$${CANARY_LEDGER_TOKEN:-}" ]; then printf %s "$$CANARY_LEDGER_TOKEN" > $$d/ledger_token; export CANARY_LEDGER_TOKEN_FILE=$$d/ledger_token; fi; \
	exec env -u CANARY_TIER -u CANARY_SEED -u CANARY_LEDGER_TOKEN CANARY_EPISODE_FILE=$$d/episode.json $(UV) python -m canary.mcp_server

game:             ## [HARNESS] build the static browser game (real canary package in Pyodide) into game/site/
	$(UV) python game/build.py

game-serve: game  ## [HARNESS] build and serve the browser game at http://localhost:8000
	$(UV) python -m http.server -d game/site 8000

hunt:             ## [INTEGRITY] judges' exploit playground (no keys, ~1 min): random/malformed/evolved/parallel-accuse fuzzing on every tier; prints best non-solver score vs solver. Real-MCP attacks: pytest tests/test_integrity_mcp.py
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
