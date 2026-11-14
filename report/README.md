# Report: the demo page

One command turns a results file into one web page:

    python -m report.build_report --results results/latest.json

It writes `report/report.html`. Open it in any browser. It works offline: all data, styles and
scripts are inside the one file, and it loads nothing from the network.

## What the page shows

1. **Score cards**: our script vs each AI agent vs do-nothing vs stop-early (mean reward, pass^3).
2. **The gap**: a bar chart of mean reward per agent, overall and per task family.
3. **Skill ladder**: scripted agents with more and more skill. The line should only go up.
4. **Why agents fail**: how often each failure tag was hit, with a plain one-line meaning.
5. **Replay**: step through one run. Calls that change the world are marked. The call that broke
   policy is red. Buttons: *Jump to the mistake*, *Compare with our script*. Arrow keys step.
6. **Exploit log**: ways we tried to cheat our own reward, and what stopped them.
7. **Gemini** (only if there is data): attacker numbers, analyst clusters, Gemini-written wordings.

Light and dark mode follow the computer. The *Theme* button (or `report.html?theme=dark`) forces one.

## What it reads

- The results JSON (SPEC section 10).
- Each run's `trajectory` path. It is looked up next to the results file, its parent folders, the
  repo root and the current folder. The `state.json` in the same folder gives the items that
  arrived mid-run (`events.fired`). Runs without a file are skipped in the replay.
- Optional, to point at the exact bad call: a run's `checks` (`[{name, passed, detail, tag}]`) or
  `failures` (`[{tag, detail}]`), or a `grade.json` next to the trajectory. The page matches ids,
  emails and phone numbers in `detail` to the call's key argument. Without details it guesses
  from the tag and labels guesses "maybe".
- Optional `results["gemini"]`: `{"model", "attacker": {name: number}, "clusters": [{name, count, rule, examples}]}`.
- `pinbox/data/payloads.json`, to count wordings whose `source` starts with `gemini`.

Options: `--out PATH`, `--max-embed-mb 6` (size cap for embedded trajectories),
`--company-domain northwind.fi`, `--payloads PATH`.

From Python: `from report.build_report import build_report; build_report(results_path, out_path)`.

## Tests

    python -m unittest tests.test_report

The fixture (made-up numbers) is `tests/fixtures/report_sample_results.json` plus two runs in
`tests/fixtures/report_runs/`. Remake it with `python tests/fixtures/report_make_fixture.py`.
