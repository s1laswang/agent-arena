# G5 Dashboard + demo assets: report

## Sat 14:25 — M1 (dashboard v0 from fixtures) done

**Done**
- `canary/gemini/dashboard.py`: `python -m canary.gemini.dashboard [--ledger DIR|FILE ...] [--results results/gemini] [--out results/gemini/dashboard.html] [--json]`.
  One self-contained HTML file (inline CSS/JS/SVG, no network, light + dark + a theme toggle, `?panel=<name>` focus mode for screenshots).
  Panels: 01 headline (calls hero + 10 tiles + capability chips), 02 usage (feature × model heat matrix with calls/tokens/cost toggle,
  calls-over-time stacked by feature, thinking share by model, cache + batch savings, latency p50/p95 by model, table view, error types),
  03 ladder (heatmap % of solver by model × level per tier, score vs thinking tokens, cost Pareto frontier), 04 atlas (corpus tiles,
  ranked modes with regret share, verified quotes, chart thumbnails embedded as data URIs, human agreement), 05 swarm (tiles, strip plot
  of every attack vs the solver line, top attempts, findings). Every panel shows a "pending" state when its JSON is missing or broken.
- `--json` prints the aggregated usage summary (totals, by_feature, by_model, cache, batch, kinds, errors, capabilities).
- Privacy: only whitelisted ledger fields are read, `meta` is never embedded, error strings are reduced to `429 RESOURCE_EXHAUSTED`-style
  types, and key-shaped strings in results JSON are redacted.
- `canary/gemini/shoot.py`: headless-Chrome panel screenshots (1600 px, cropped), no playwright.
- Fixtures: `tests/fixtures/gemini_lab/` (generator + 2,094-row synthetic ledger + ladder/atlas/swarm JSON, all marked `synthetic: true`,
  and the page shows a "SYNTHETIC FIXTURE" badge on any panel fed by them).
- Tests: `tests/test_gemini_lab_dashboard.py`, 7 tests, 0.2 s keyless (renders from fixtures, no network refs, planted fake key never
  reaches the HTML, missing/broken JSON → pending, `--json`).
- Screenshot: `docs/gemini/assets/dashboard-v0-fixture-ladder.png` (fixture data, not citable).

**Result JSON shapes the dashboard reads** (tolerant; G2/G4 please match or tell me):
- `ladder.json`: `{generated_at, git_sha, ledger_run_ids, solver:{tier:score}, cells:[{model, level, tier, n, score_mean, solver_mean,
  pct_solver, pct_solver_ci95:[lo,hi], thinking_tokens_per_episode, cost_usd_per_episode, regret_mean}]}`.
  Aliases accepted: `thinking_level`, `episodes`, `frac_solver`, `ci95`, `score`, `solver`, `thinking_per_episode`, `cost_per_episode`.
  If `pct_solver` is missing it is computed from `score_mean / solver_mean`. Optional `results/gemini/ladder.png` is embedded.
- `atlas.json`: TEAM.md shape; `chart` is a path relative to `results/gemini/` (PNG/SVG ≤ 400 KB embedded). `human_agreement` may be a
  number or `{agree, total, rate}`.
- `swarm.json`: TEAM.md shape plus optional `solver_score`, `findings:[{title, verified, test}]`, `tests_written`, `model`, `mode`, `tier`.
  `best_non_solver` may be a number or an object with `score`.

**Next**: v1 on the real ledger (data/gemini/ledger) + whatever results exist by 19:00; then VIDEO.md, narrate.py, screenshots.

**Blockers / asks**
- `canary/llm/pricing.py` has no list price for `gemini-3.5-flash`, `gemini-3.1-flash-lite`, `gemini-embedding-2` or the TTS/Live
  models, so their ledger rows cost $0 (`cost_unknown`); the dashboard flags the count. CEO: add prices if we want exact $ totals.
