PY ?= .venv/bin/python

test:
	$(PY) -m pytest -q

eval:
	$(PY) -m lab.eval
	$(PY) -m sleeper.baselines

.PHONY: test eval
