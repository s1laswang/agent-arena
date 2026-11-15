# G5 Dashboard + demo assets: report

## Sun 04:00: rebuilt on the n=40 canonical ladder (pr2 d165e3ec)
- Merged origin/gemini-pr2 d165e3ec into gemini-dashboard-final (checked: no PR #9). Ladder: 587 episodes, 42 cells.
- Usage re-exported: **42,233 calls, 1.26B input, 87.9% cached, 16.2M thinking, $377.35 list**. The growth is real (about 16.6k
  `ladder30` calls Sun 01–03); no row is duplicated across hosts or processes.
- ROLES Frontier row: carbon-high **106% [94, 126], n=10, $1.93/episode**; 3.6-flash (requested 3.5-flash) high **88% [51, 138],
  n=40, $0.45/episode**, "not distinguishable from the solver, CIs wide". The VIDEO.md VO[02-frontier] dry run speaks the same.
- All 7 screenshots re-shot. 121 lab tests pass. Leaderboard is still the gap.md fallback (b08d23c, numbers unchanged).
- Cosmetic, left as is: the heatmap's "medium" header is cut off now that there's an xhigh column, and two frontier labels overlap slightly.

## Sun 02:50: final builds move to branch gemini-dashboard-final (cut from gemini-pr2, no PR #9)
- **Why:** per COMMON.md I merged origin/gemini-track into gemini-dashboard (23:08, 00:00), so that branch contains PR #9 (1bcf1ee7),
  which pr2 must not. Nothing was force-pushed or reverted. gemini-dashboard-final is cut from origin/gemini-pr2 55a8e077; pr2
  already had all my and the video session's files byte-identical. ceo lite's 05:50 freeze merges gemini-dashboard-final only.
- **Interim final build** on pr2's results (n=20 ladder, 417 episodes):
  - Usage ledger re-exported: **29,374 calls, 862M input, 86.5% cached, 11.5M thinking, $261.01**. The new committed
    `ladder_gemma_ledger.jsonl.gz` adds 267 hosted-Gemma rows at $0; the rest of the growth is n=20 ladder calls.
  - The ladder panel needed no wording change: no "matches" text anywhere, and every hard cell has n ≥ 10.
- ROLES Frontier row: leads with the carbon hard cell (n ≥ 8) that has the narrowest CI, i.e. carbon-high **106% [94, 126], n=10,
  $1.93/episode**, then 3.6-flash (requested 3.5-flash) high 71% [11, 158], n=20, $0.43/episode, "not distinguishable, CIs wide".
  This matches SUBMISSION.
- VIDEO.md VO[02-frontier] (3-min long cut) speaks those same two cells with n, CI and cost (`narrate.cell_values`, n ≥ 8 only).
  VIDEO-2MIN.md is untouched (ceo lite's ask).
- Leaderboard: still the gap.md fallback (now f9fb7a4, numbers unchanged); justSilas has no leaderboard_v14_hard.json yet.
- **For the CEO:** SUBMISSION still says "24,855 calls" and "85.3%" cached. The final numbers come at 05:15.

## Sun 00:45: 00:30 rebuild pushed; VIDEO.md final shot list; leaderboard panel
- **00:30 rebuild** (b43a859b): gemini-track had nothing new. Usage ledger re-exported: **24,855 calls, 678M input, 85.3% cached,
  9.39M thinking, $226.34 list**. The committed-only build and `auto` match. All 7 screenshots and ROLES re-shot; 106 lab tests pass.
- **07 Leaderboard** (473c27a6, Arena CEO ask via ceo lite). `canary.gemini.leaderboard` copies justSilas
  `results/leaderboard_v14_hard.json` verbatim with its commit SHA. That file isn't committed yet, so for now the panel shows the
  Gemini + solver rows parsed from gap.md (a52dde2, numbers unchanged): carbon OpenCode/MCP hard n=30 65% [24%, 98%], luck-adjusted
  72% [52%, 91%]; solver 0.499 (n=30). Compute shows "not stated", because gap.md doesn't state it.
- **VIDEO.md final shot list** (the 3-min long cut; the submitted cut is VIDEO-2MIN.md). Stale lines rewritten so every number
  comes from a committed file: the hook drops the ladder percentage (PLAN's revised hook); 02-frontier speaks only cells with n ≥ 8 and
  their CI (3.5-flash served as 3.6-flash, high, hard: 102% [84%, 129%], n=8, 22% of carbon-default's cost per episode); 03-modes
  says v1 saw our tags, then gives the blind result (3/5, 2 new, 21%); 04-swarm says best unjustified 0.38 on hard vs solver 0.53,
  positive control 4/4; 06-close drops "batch". Dry run: 395 words, about 158 s, nothing pending. TTS clips get made at 04:30
  on the final numbers.

## Sun 00:00: swarm panel on the final swarm.json (6e848135, CEO ask)
- Merged origin/gemini-track and origin/gemini-swarm (905cdd9). gemini-bakeoff-fixes was not needed: the panel reads only swarm.json.
- Headline: **best unjustified +0.38 on hard** (solver +0.53). Medium's per_tier best_unjustified (+0.72) is w2b-008. It was flagged
  in-run at 0.68 vs solver 0.49 (n=4) and overturned on review at 0.16 vs 0.55 (n=4, swarm_review_w2b008.json). The panel shows it
  that way in a new "Score candidates: flagged in-run → reviewed" card and never uses it as the headline. b1-015 is listed as "not
  confirmed on re-run" (0.32 vs 0.72, n=4). The panel also shows 100 attacks, 0 verified exploits, 0 invariant violations, positive
  control 4/4. The ROLES.md swarm row reads it the same way (shared `slim_swarm`).
- Tests: 103 pass, including one that pins the committed swarm.json headline (+0.38 hard, w2b-008 overturned). All 6 screenshots re-shot.
- The video session confirmed its cut doesn't use the swarm panel, so there's no conflict. The cut does use the headline, atlas, usage and ladder
  panels, so **re-run the video re-cut (reports/video.md, about 10 min) after my 05:40 push**. The video deadline is 05:30, so ceo lite owns this step and was told.

## Sat 23:50: 2-minute video landed (bcc64b3, by the video session)
- `docs/gemini/assets/canary-lab-2min.mp4` (2:00, 1080p, 38 MB). Build, QA and the refresh commands are in
  [reports/video.md](video.md); QA results are in `results/gemini/video_qa.json`. Its narration takes cost and cache share from the
  committed ledger and the atlas from atlas_blind.json. Re-cut it (about 10 min) after my 05:40 final rebuild.
- I checked the commit: it touches only the agreed paths plus an additive narrate.py `usage_summary()`/`{cost}`. 98 lab tests pass.

## Sat 23:20: task 1 done; dashboard now built from committed files only (42eddce)

**Done**
- Merged origin/gemini-track (af76fa0). Lab tests: 93 passed.
- ROLES.md addendum (generated by `roles index`, not hand-typed). The mole row is labelled "arena mode, not the judged env" with
  n=4, medium dev seeds 0–3, and the three caveats. The Analyst row now leads with the blind re-run (3/5 code modes, 2 new,
  21% regret covered, 12/16 quotes) and marks v1 as not blind. The failed `batch:` slot is dropped.
- `results/gemini/roles/worldtext/_cache/` committed (72 KB, 6 JSONs, read on `--reuse` replay).
- `.gz` ledger reading and the roles index builder were already finished and tested (ddbdd1a).
- **Committed-only usage numbers.** `--ledger auto` read gitignored local ledgers, so the usage panel had no committed source.
  New `--export-ledger` writes the deduped union with whitelisted fields only (no prompts, no meta) to
  `results/gemini/usage_ledger.jsonl.gz` (558 KB). New `--ledger committed` reads only results/gemini ledgers. The totals match
  `auto` exactly: **24,415 calls, 655M input / 557M cached (85%), 9.25M thinking, $222.18 list**. Errors were scanned: no keys.
- Dashboard: the atlas panel opens with the blind re-run (from atlas_blind.json); v1 cards are titled "(v1, not blind)". The roles
  panel shows the mole caveats. The "batch API" chip only shows for a successful batch call (the 5 batch rows all failed, 0 tokens).
  All 6 screenshots refreshed (atlas is 3911 px tall; shoot with `--height 5000`).

**For the CEO**
- SUBMISSION.md quotes stale usage numbers: "15,757 calls, 411M input, 340M (82.7%) cached, 6.75M thinking, $146.02". The
  dashboard's `usage.totals` now gives the numbers above, and they will grow by 05:15. VIDEO-2MIN.md VO[07] speaks $146.02 and 82.7% too.
- SUBMISSION says the blind atlas "cited 124 steps". `atlas_blind.json` says 127 (`recovery.cited_steps`); 124 is in no committed file.
- Someone else is writing into this worktree: `docs/gemini/assets/narration-2min/` (narrate run `narrate-1794690510`, 23:08) and
  `canary/gemini/video_cut.py` appeared untracked. I have not committed or touched them.

**Next**: about 00:30, merge gemini-track, re-export the ledger, rebuild, screenshots, push. 04:30: narration v1 and the VIDEO.md
shot list. 05:15: final merge, rebuild, push by 05:40.

## Sat 19:06: PLAN-95 item F, real gemini-4-carbon runs for the world-text renderer and the adaptive mole

**Done** (dev seeds only; each run under results/gemini/roles/<role>/ with meta.json, ledger.jsonl and outputs)
- `canary/gemini/roles.py` (`worldtext`, `mole`, `index`). It refuses judge seeds and routes every call through lab_client with run_id.
  The meta records model, thinking (carbon model default = medium, temperature not sent), git sha, code commit ddbdd1a, run id and times.
- **World-text renderer**: a **demo/research layer (v1.5 candidate), not judged, no score claim**. Medium dev seeds 0–5,
  run roles-worldtext-20261114-185649, 12 calls, $0.25.
  - Gemini wrote all 120 personas (0 fallbacks).
  - canary/text/lint.py: clean on 6/6 seeds.
  - Text-only investigators named the mole 1/6 (keyword probe, p=0.37) and 0/6 (gemini-3.8-flash, p=1.00) against the fair bar of 7%.
    Neither is above the bar.
  - assert_no_truth passes its truth-key, vocabulary and lint checks. Its unique-tone heuristic fires on every seed because Gemini gave
    all 20 personas distinct tones (20/20 unique), so it carries no signal; this is documented in lint_probe.json.
- **Adaptive mole** (arena): medium dev seeds 0–3, vs solver and heuristic, paired with the default mole. Run roles-mole-20261114-185950,
  64 carbon calls, $0.31. The p_leak gate is respected (9 leaks gated).
  - vs solver: score +0.00 with the Gemini mole vs +0.63 with the default mole. Caught 0/4 vs 4/4. 48 leaks, only 1 of them a canary.
    Gemini's own reasons favour widely distributed docs. Example from day 1: "Leaking c1 is completely safe because all 20 employees received it".
  - vs heuristic: −1.00 for both moles (the heuristic accuses wrongly early).
- `docs/gemini/ROLES.md` and `results/gemini/roles/index.json` are generated by `roles index` from the committed files. Rows: frontier
  (ladder + imported AfterQuery carbon cell), analyst (atlas v1), swarm, world-text, mole. Mole Forge is omitted because its committed
  hall of fame used the stub mutator. The v1.5 108% vs 61% line is cited to justSilas docs/reports/CEO.md and env.md.
- Dashboard: new 06 Roles panel; atlas panel now real (G3 atlas v1: 153 episodes, 98% quotes verbatim, 8/8 chart localisation).
  The committed `*ledger*.jsonl.gz` files are now read (15,757 ledger rows). Screenshots: dashboard-roles.png, dashboard-atlas.png.
- Tests: tests/test_gemini_lab_roles.py (judge-seed guard, p_leak gate, index from files). Lab tests green.

## Sat 18:25: dashboard rebuilt on ladder v1 + swarm, screenshots refreshed (CEO 18:55 ask)

**Done**
- Background loop checked after the 15:35–17:30 outage: it survived and exited on its timer at 17:38. Rebuilt by hand at 18:23.
- The 18:23 build was a 122 KB `dashboard.html` from the ledger then (`--ledger auto`, build log 11,187 calls) + G2 `ladder.json` (18:21, 125 episodes / 29 cells)
  + G4 `swarm.json` (18:20, 35 attacks) + G1 `gateway_bench.json`.
- The `dashboard.html` in this tree is the later rebuild. It embeds 15,757 calls and $146.0212 ($146.02; quote these), 411M input / 0.93M output / 6.75M thinking / 340M cached tokens (82.7%),
  p50 3.38 s / p95 30.13 s, 11 models, 12 features. The 18:23 build log's 11,187 calls and $88.75 is not this file.
- Swarm panel follows G4's new semantics. The headline is the **best unjustified score** (+0.000 on hard vs solver +0.602), and the 1 honest
  detective win (+0.90 on medium, accusation justified by public evidence) is shown hollow and excluded. The strip plots score − solver on
  the same seed, so hard and medium share one axis. 0 exploits; 5 regression tests.
- Screenshots (1600 px, light): docs/gemini/assets/dashboard-{headline,usage,ladder,swarm}.png. Assets total 3.1 MB.

**Next** (after 19:30): atlas panel when G3 commits atlas.json; narrate.py to use best_unjustified; narration v1; dark + atlas screenshots.

## Sat 15:00 — PR-1 ready; G2 ladder + G1 gateway bench live in the dashboard

**Done**
- **Ready for PR 1 now** (CEO deadline 18:30): branch `gemini-dashboard` has gemini-track merged in; all `tests/test_gemini_lab_*.py`
  pass (61 in 11 s with the teammates' tests); full suite earlier 575 passed / 6 skipped. New `make lab-dashboard` (ARGS="--ledger auto").
- Dashboard renders G2's committed `ladder.json` (14:50, 64 episodes / 24 cells, smoke-sized n=2): diverging heatmap (red = worse than
  doing nothing, grey = 0, blue → solver), thinking curve, cost frontier, "which mistakes does thinking fix" matrix, reference lines.
- Gateway throughput card from G1's `gateway_bench.json` (3.8-flash ~1.6k req/min at 64 clients; carbon saturates ~175).
- Phone width: 16 px gutters, smaller type, matrix scrolls inside its card (checked at 520 px; headless Chrome floors the window at ~500).
- VIDEO.md hook now opens on the Live commentator's day-5 call (29.0–38.5 s of commentator-demo.wav), VO shortened to 45 words.
- How I build: `/tmp`-staged read-only copies of each teammate's committed `results/gemini/*` (owner branch or gemini-track, whichever
  is newer) + `--ledger auto`; results/gemini/dashboard.html is refreshed and committed when results change or hourly.

**Next**: atlas/swarm panels as soon as G3/G4 commit JSON; narration v1 at M2 once numbers are final enough to speak.

## Sat 14:50 — dashboard v1 on the real ledger, VIDEO.md, narrate.py, Live commentator clip (ahead of M2)

**Done**
- **Merge-ready for PR 1** (`canary/gemini/{dashboard,shoot,narrate,commentator}.py`, fixtures, 4 test files): `make test`
  equivalent green on this branch (575 passed, 6 skipped, 6.4 min); lab tests 13 passed in 0.3 s, keyless.
- **v1 from real data**: `python -m canary.gemini.dashboard --ledger auto` finds every ledger on this Mac (data/gemini/ledger,
  ~/agent-arena-data/gemini/**/_ledger, sibling gemini-* worktrees), dedupes rows that were synced twice, and writes
  `results/gemini/dashboard.html` (committed, 70 KB). At 14:43: **5,502 Gemini calls**, 8 features, 10 models, 73M input / 1M thinking /
  58M cached tokens, $21.10 list price, 0.6% errors, p50 2.7 s / p95 13 s. Ladder/atlas/swarm panels show "pending" until their JSON lands.
- Reads the **real result shapes** now: G2 `ladder.json` (`rows` with ratio/CI/thinking_per_ep/cost_per_ep, `reference`, `tags.pooled`
  → a "Which mistakes does thinking fix?" matrix, solver/grok_tactics/heuristic reference lines), G3 `atlas.json` (verification
  pass rate, multimodal localisation, cohorts, summary, mechanism/solver_would, step-verified quotes, chart thumbnails),
  G4 `swarm.json` (per_tier paired solver mean, counts, plan.hypothesis, violation kinds, `tests/test_gemini_lab_swarm_found.py` count).
  Large fields (tool calls, per-episode lists, seeds) are dropped before embedding. Fixtures regenerated in these shapes.
- Unpriced flash rows (3.1-flash-lite, 3.5-flash) are repriced with the same table G2 uses (and `prices_usd_per_1m` from
  ladder.json); the cost tile counts what is still unpriced (embedding/TTS/Live).
- Screenshots (real data): `docs/gemini/assets/dashboard-headline.png`, `dashboard-usage.png` (1600 px). Fixture screenshot removed.
- `docs/gemini/VIDEO.md`: 3:00 storyboard, shot list, asset table and `VO[id]` narration lines with `{placeholders}`.
- `canary/gemini/narrate.py`: fills placeholders from results + ledger (refuses to speak a missing number unless `--allow-pending`),
  one `gemini-3.8-flash-tts` call per clip, `--voices` auditions, `--check` = Gemini 3.8 Flash transcribes each clip and scores recall
  against the script. Findings: the SDK default API version rejects `speech_config` for 3.8 TTS (400 "Unknown name speechConfig") →
  we force `v1beta`; the model returns `audio/wav`; style prefixes ("Say in a … voice:") are **read aloud** by most voices and
  `system_instruction` is rejected, so the voice carries the style. Auditions on the hook: Kore 25.1 s (≈150 wpm, matches the budget,
  default), Charon 18.8, Puck 21.6, Algieba 23.4, Zephyr 21.7, Orus 20.7; transcript recall 94–98%.
- **Stretch done early**: `canary/gemini/commentator.py`, a Live API (`gemini-3.8-live`) sportscaster. Streams one text turn per game
  day of the committed gemini-4-carbon hard seed 9 (correct accusation, +0.74) and records audio + output transcription.
  Clip: `docs/gemini/assets/narration/commentator-demo.wav` (50.6 s) + `.json` (events, commentary). Guarded against inventing leaks
  (first take called a V drop "a leak"; the system prompt now forbids that and the second take is accurate).

**Next**: rebuild as G2/G3/G4 results land (target 19:00 v1 with ladder); narration clips once the numbers exist (22:00);
final screenshots incl. dark + ladder/atlas figures (Sun 05:00).

**Asks**: CEO, for the published page run `python -m canary.gemini.dashboard --ledger auto` (or point `--ledger` at the synced FR8
ledger dir). `canary/llm/pricing.py` still lacks 3.1-flash-lite / 3.5-flash (the dashboard reprices them itself).

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
