PY ?= .venv/bin/python
SEAT ?= $(or $(SLEEPER_SEAT),finance_ap)
CACHE = data/gemini_cache.tar.gz

test:
	$(PY) -m pytest -q

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

.PHONY: probes frontier-replay-run test eval eval-full harbor exploits key-check cheat-corpus

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
