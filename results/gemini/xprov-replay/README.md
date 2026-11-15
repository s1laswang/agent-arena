# Recordings of the cross-provider control

Every Gemini call of the control (`results/gemini/xprov.md`) was made through the recording gateway. These stores hold the raw API responses, each with its `responseId`, so any control episode replays without a key:

```bash
lab() { uv run --python 3.12 --extra dev --extra llm --extra plot "$@"; }
lab python -m canary.gemini.with_gateway --replay results/gemini/xprov-replay/flash -- \
    python scripts/with_tiers.py v1.3 -m canary.gemini.ladder --models gemini-3.5-flash --levels medium \
    --tiers hard --seeds 0 --max-attempts 1 --out /tmp/replay --run-name xprov-v13
```

- `flash`: all 44 gemini-3.5-flash cells (served as gemini-3.6-flash).
- `hydrogen-first`, `hydrogen-medium`, `hydrogen-high`: the 44 gemini-4-hydrogen cells; `manifest.json` says which store replays which cell (the first process was stopped and restarted with more parallelism).

Verified on Sun 15 Nov with no key: 44 of 44 flash cells and 44 of 44 hydrogen cells reproduce the live episode's score, accusation and step count. `tests/test_gemini_lab_xprov_replay.py` replays one cell on every test run.
