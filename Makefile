PY ?= .venv/bin/python
CACHE = data/gemini_cache.tar.gz

test:
	$(PY) -m pytest -x -q -n auto

eval:
	$(PY) -m lab.eval --trials 1 --jobs 1 --no-report --out results/fast --web-out ""

test-full:
	$(PY) -m pytest -q -n auto -o addopts=

eval-full:
	if [ -f $(CACHE) ]; then $(PY) scripts/gemini_cache.py unpack $(CACHE) && SLEEPER_OFFLINE=1 $(PY) -m lab.eval; else $(PY) -m lab.eval; fi
	$(PY) -m sleeper.baselines

harbor:
	$(PY) -m harbor.build --seeds 0..19 --seat controller

.PHONY: test test-full eval-full eval harbor exploits

exploits:
	$(PY) -m redteam.report
