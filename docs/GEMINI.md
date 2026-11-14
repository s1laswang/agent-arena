# Gemini: first 30 minutes once the key exists

Nothing here has been run with a real key. Every command below was checked against the code on `momin` 88618ee (flags exist, files exist). No Gemini number is in these docs until a live run has produced it: NOT FOUND. Do not claim multimodal or any Gemini result before step 5.

Not on momin, so do not look for them: `scripts/gemini_budget.py`, `scripts/key_check.py`, `data/gemini_cache.tar.gz`, `gemini_cache.py check`. Budget is `--budget-calls` and `SLEEPER_MAX_CALLS`. If lead-harness lands those scripts, update this page.

1. Key. Put `GEMINI_API_KEY=...` in `~/arena-agents/.env` or `./.env` (both gitignored, read by `agents/gemini.py`). Model ids come from `SLEEPER_MODEL_STAFF`, `SLEEPER_MODEL_SLEEPER` and `SLEEPER_MODEL_REFERENCE` (default in `agents/gemini.py`). Never commit the key.
2. Smoke, about 10 seconds: `PYTHONPATH=. .venv/bin/python scripts/gemini_smoke.py`. One call with one tool, prints usage. Prints `no GEMINI_API_KEY` and exits if the key is missing.
3. One day, staff then reference: `.venv/bin/python -m lab.run --team staff --days 1 --trials 1 --gemini`, then `--team reference`. Check `agent_kind` is "gemini" in the run's `days.jsonl` and read `gemini_usage` in its `summary.json`. A key alone leaves rows scripted. `--gemini` (or `LAB_GEMINI=1`) turns it on.
4. Cap the spend before the big run. `--budget-calls N` on `lab.run` and `lab.eval` (or `SLEEPER_MAX_CALLS=N`) stops at N live calls; `lab.eval --gemini` first prints an upper bound of estimated calls. Seats, rounds and steps for the estimate: `SLEEPER_SEATS`, `SLEEPER_ROUNDS`, `SLEEPER_STEPS`. Cost is reported only if you set `SLEEPER_PRICE_IN_PER_M` and `SLEEPER_PRICE_OUT_PER_M` from Google's price page.
5. Full eval with Gemini rows: `.venv/bin/python -m lab.eval --gemini --budget-calls N`. Plain `make eval` has no Gemini rows. Then `.venv/bin/python -m lab.analyse results/runs/<run> --gemini` for failure explanations.
6. Pack the cache: `.venv/bin/python scripts/gemini_cache.py pack data/gemini_cache.tar.gz`. It only has `pack` and `unpack`, no key scan, so grep the tarball contents for the key yourself before committing. Packing is byte-for-byte deterministic.
7. Replay without a key: `.venv/bin/python scripts/gemini_cache.py unpack data/gemini_cache.tar.gz`, then `SLEEPER_OFFLINE=1 .venv/bin/python -m lab.eval --gemini`. `make eval` already does unpack plus offline when `data/gemini_cache.tar.gz` exists, but without `--gemini` it will not replay the Gemini rows. A cache miss raises an error, with no silent scripted fallback.
