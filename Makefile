PY ?= .venv/bin/python
CACHE = data/gemini_cache.tar.gz

test:
	$(PY) -m pytest -q

eval:
	if [ -f $(CACHE) ]; then $(PY) scripts/gemini_cache.py unpack $(CACHE) && SLEEPER_OFFLINE=1 $(PY) -m lab.eval; else $(PY) -m lab.eval; fi
	$(PY) -m sleeper.baselines

harbor:
	$(PY) -m harbor.build --seeds 0..19 --seat controller

.PHONY: test eval harbor exploits

exploits:
	$(PY) -m redteam.report
