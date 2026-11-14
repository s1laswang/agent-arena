PY ?= .venv/bin/python
SEAT ?= $(or $(SLEEPER_SEAT),finance_ap)
CACHE = data/gemini_cache.tar.gz

test:
	$(PY) -m pytest -x -q -n auto

eval:
	if [ -f $(CACHE) ]; then $(PY) scripts/gemini_cache.py unpack $(CACHE) && SLEEPER_OFFLINE=1 $(PY) -m lab.eval; else $(PY) -m lab.eval; fi

eval-smoke:
	$(PY) -m lab.eval --days 5 --trials 1 --jobs 1 --no-report --out results/fast --web-out ""

test-full:
	$(PY) -m pytest -q -n auto -o addopts=

eval-full:
	$(PY) -m lab.eval --full
	$(PY) -m sleeper.baselines

harbor:
	$(PY) -m harbor.build --seeds 0..19 --seat $(SEAT)

.PHONY: test test-full eval eval-smoke eval-full harbor exploits key-check

exploits:
	$(PY) -m redteam.report

key-check:
	PYTHONPATH=. $(PY) scripts/key_check.py
