PY ?= .venv/bin/python
SEAT ?= $(or $(SLEEPER_SEAT),finance_ap)
CACHE = data/gemini_cache.tar.gz

test:
	$(PY) -m pytest -q

eval:
	if [ -f $(CACHE) ]; then $(PY) scripts/gemini_cache.py unpack $(CACHE) && SLEEPER_OFFLINE=1 $(PY) -m lab.eval; else $(PY) -m lab.eval; fi

eval-full:
	$(PY) -m lab.eval --full
	$(PY) -m sleeper.baselines

harbor:
	$(PY) -m harbor.build --seeds 0..19 --seat $(SEAT)

.PHONY: test eval eval-full harbor exploits key-check replay-demo

exploits:
	$(PY) -m redteam.report

key-check:
	PYTHONPATH=. $(PY) scripts/key_check.py

replay-demo:
	PYTHONPATH=. $(PY) scripts/replay_demo.py
