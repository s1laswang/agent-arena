PY ?= .venv/bin/python

test:
	$(PY) -m pytest -q

eval:
	$(PY) -m lab.eval

.PHONY: test eval
