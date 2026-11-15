DONE 2026-11-15 04:33:00 EET

# WS4 Numbers QA — Gemini-Facing Documentation & Results (`d165e3ec`)

- **Stamped:** `2026-11-15 04:33:00 EET`
- **Audited branch / commit:** `gemini-pr2` (`d165e3ec0bbcb42b9b468d69b1d33ba8aaae4e89`)
- **Method:** Deterministic Python parse-and-compare (`canary/gemini/qa.py`) across all committed JSON, `.jsonl.gz`, and HTML artifacts + 1M-context `gemini-4-argon` claim/source locator (`--replay` rebuilds with 0 API calls). Audit-only: zero edits to claim files.
- **Totals:** **97** claims verified in `claims.csv` — **74 match (`y`)**, **23 mismatch (`n`)**.

> **Core scientific tables check (`d165e3ec`):** Every single cell in the regenerated canonical `results/gemini/ladder.md` (**42 Gemini cells, 587 episodes, 6 models + Gemma n=5**), `results/gemini/atlas_blind.md`, `results/gemini/atlas.md`, `results/gemini/swarm.md`, `results/gemini/swarm_control.md`, and `docs/reports/failure_gallery.md`, as well as all n=40 ladder ratios (`87% [50, 147]`, `88% [51, 138]`, `73/80`, `4.3×`, `18 of 42 cells`), swarm, and blind-atlas numbers in `docs/gemini/SUBMISSION.md`, **matches its underlying JSON artifact (`y`)**.

---

## Ranked Mismatches & Exact Fixes for CEO Lite (Before 05:50 Freeze)

### 1. CRITICAL (Same-Page Self-Contradiction): `24,855` vs `29,150` vs `42,188` Ledgered Calls & `EXTRA_PRICES` Cost Gap
- **Where:**
  - `docs/gemini/SUBMISSION.md:5, 37` (`24,855 calls, 85.3% of input cached, $226.34 at list price`)
  - `docs/gemini/SUBMISSION.md:24` (`saved 75.9% ($678.19 of $893.08) across all 29,150 ledgered calls`)
  - `docs/gemini/SUBMISSION-LONG.md:7, 20, 49, 60` and `pitch/GEMINI.md:9`
- **Root cause in code (two parts):**
  1. `results/gemini/dashboard.html` still embeds the 00:30 snapshot (`24,855` calls, `$226.34`), `results/gemini/ablations.md` embeds the 02:44 snapshot (`29,150` calls), `results/gemini/ladder.md:15` alone now has **`36,164` calls (`$298.75`)**, and running `python -m canary.gemini.dashboard --ledger committed --json` at `d165e3ec` gives **`42,188` calls, `1.257B` (`1,257,204,527`) input tokens, `1.106B` (`88.0%`) cached, `16.19M` (`16,187,372`) thinking tokens, `$377.11` list price**.
  2. `canary/gemini/ablations.py:124` (`_cost_pair`) calls `canary.llm.pricing.cost()` **without** `dashboard.py`/`ladder_report.py`'s `EXTRA_PRICES` (`gemini-3.5-flash`: `$0.75/$3.75/$0.075`; `gemini-3.1-flash-lite`: `$0.25/$1.50/$0.025`), pricing 12,347 Flash/Flash-Lite calls at `$0.00`!
- **Exact fix for CEO lite:** Add `EXTRA_PRICES` fallback in `canary/gemini/ablations.py:_cost_pair()`, rerun `python -m canary.gemini.ablations` and `make lab-dashboard ARGS="--ledger committed"`, then update `SUBMISSION.md:5,24,37`, `SUBMISSION-LONG.md:7,20,49,60`, and `pitch/GEMINI.md:9` to the unified `42,188` (or freeze-time) ledger numbers.

### 2. HIGH (New in `d165e3ec`): Model Count (`five` → `six`) & Per-Cell Seed Range (`10–40` → `9–40`)
- **`five` vs `six` Gemini models:**
  - `docs/gemini/SUBMISSION.md:12` says `five Gemini models × thinking_level` and `docs/gemini/VIDEO-2MIN.md:36` (`VO[03-ladder]`) says `Five models, up to four thinking levels, five hundred eighty-seven paired episodes`.
  - With WS1 merged at `d165e3ec`, `results/gemini/ladder.json` has **6** Gemini models in the 42 cells (`gemini-3.1-flash-lite`, `gemini-3.5-flash` [served `3.6-flash`], `gemini-3.8-flash`, `gemini-4-hydrogen`, `gemini-4-argon`, `gemini-4-carbon`; `SUBMISSION-LONG.md:24` dropped `5`, but `SUBMISSION.md:12` and `VIDEO-2MIN.md:36` kept `five`/`Five`).
  - **Fix:** Change `five Gemini models` → `six Gemini models` in `SUBMISSION.md:12` and `Five models` → `Six models` in `VIDEO-2MIN.md:36`.
- **`10–40` vs `9–40` paired seeds per cell:**
  - `docs/gemini/SUBMISSION.md:40` (`Cells have 10–40 paired seeds`) and `docs/gemini/SUBMISSION-LONG.md:32` (`Each cell has 10–40 paired seeds`).
  - In `results/gemini/ladder.json` (and `results/gemini/ladder.md:3, 35, 64`), two `gemini-4-hydrogen` cells have **`n=9`** (`medium` on medium and `high` on hard), so `ladder.md:3` auto-prints `9–40 paired seeds per cell`.
  - **Fix:** Change `10–40 paired seeds` → `9–40 paired seeds` in `SUBMISSION.md:40` and `SUBMISSION-LONG.md:32`.

### 3. HIGH: `results/gemini/ablations.md` Not Regenerated After `d165e3ec` (`34` vs `42` Cells)
- **Where:** `results/gemini/ablations.md:24, 34-35, 66-67` (cited by `SUBMISSION.md:22` and `SUBMISSION-LONG.md:58`)
- **Mismatch:** `SUBMISSION.md:25` and `SUBMISSION-LONG.md:61` were updated to `87% [50, 147] at medium ($0.42, n=40)` and `18 of 42 ladder cells`, **but `results/gemini/ablations.{json,md}` still has the pre-WS1 34-cell sweep (`17 of 34 cells`, `78% [28, 151]`, `n=20`)**.
- **Exact fix for CEO lite:** Re-run `uv run python -m canary.gemini.ablations`.

### 4. HIGH: `docs/gemini/ROLES.md:9` & `results/gemini/roles/index.json` Still Show Sat 18:47 v1 Ladder (`157 episodes, 34 cells`)
- **Where:** `docs/gemini/ROLES.md:9` (and `:27`)
- **Mismatch:** Row 1 still says commit `016758ace5`, `157 episodes, 34 cells`, `gemini-4-carbon (default) reaches 66% of the solver on hard [95% CI 5%, 117%], n=10` (actual `ladder.json`: `587` episodes, `42` cells; carbon default hard `108% [62%, 189%], n=22`; carbon high `106% [94%, 126%], n=10`). Also `ROLES.md:27` mentions `assert_no_truth` without noting `assert_no_truth_pass: 0` in `lint_probe.json` (template tone-uniqueness heuristic).
- **Exact fix for CEO lite:** Re-run `uv run python -m canary.gemini.roles index`.

### 5. HIGH (Known Freeze Item): `narration-2min/03-ladder.wav`, `07-essential.wav`, & `canary-lab-2min.mp4`
- **Where:** `docs/gemini/assets/narration-2min/index.json` + `results/gemini/video_qa.json`
- **Mismatch:** Committed `03-ladder.wav` still narrates `'one hundred fifty-seven paired episodes... n equals eight'`, and `video_qa.json` shows the MP4 displays `24,415` calls / `$222`.
- **Exact fix for CEO lite:** Re-run `narrate --only 03-ladder,07-essential` (note `VIDEO-2MIN.md:27` omits `03-ladder` in its `--only` example!), `video_cut`, and `video_qa` at the 05:50 freeze.

### 6. MEDIUM: `docs/gemini/SUBMISSION-LONG.md:75` HoldUp Latency (`0.7–1.75 s` vs `p50 2.1 s / p95 3.4 s`) & `scale/ladder30/ladder.md:5` Gate
- **`docs/gemini/SUBMISSION-LONG.md:75`:** Quotes `0.7–1.75 s` for HoldUp speculative verify, whereas HoldUp's own `GEMINI.md:32` reports **`p50 2.1 s / p95 3.4 s (n = 26 live sessions)`**.
- **`results/gemini/scale/ladder30/ladder.md:5`:** Snapshot generated with pre-`7edf2d0d` gate (`'is within the CI of the solver, n=40'`) whereas canonical `results/gemini/ladder.md:5` uses the strict gate (`'is not distinguishable... CIs are wide'`).
- **Secondary docs (`VIDEO.md:31-32, 58`, `PLAN.md:57, 64, 73, 85`):** `VIDEO.md:58` says `'fanned out over our cluster'` (all ladder runs were on Mac per `gateway.md:47`); `VIDEO.md:31-32` cites non-existent `ladder.png` / `charts/*.png`; `PLAN.md` retains pre-measurement `Batch API` and inverted canary-vs-timing text.

---

## All Mismatched Rows (`match = n` in `claims.csv`)

| file:line | claim | source file | source value |
|---|---|---|---|
| `results/gemini/scale/ladder30/ladder.md:5` | scale/ladder30/ladder.md headline uses pre-7edf2d0d gate ('within the CI of the solver', 518 eps) vs canonical ladder.md strict gate ('not distinguishable... CIs are wide', 587 eps) | `results/gemini/ladder.md:5 + canary/gemini/ladder_report.py` | Canonical ladder.md (587 eps) enforces strict CI gate ('not distinguishable from the reference solver on hard, but the CIs are wide', lower CI 50%/51% < 80%) |
| `results/gemini/ablations.md:21` | ablations.md programme cache row: 29,150 calls, 860,488,544 in, 86.6% cached, paid $214.89 vs uncached $893.08 | `results/gemini/*ledger*.jsonl.gz + canary/gemini/dashboard.py` | Stale pre-d165e3ec ledger (29,150 vs live 42,188 committed calls) AND ablations.py omits EXTRA_PRICES for 3.5-flash/3.1-flash-lite (live dashboard repriced total=$377.11) |
| `results/gemini/ablations.md:24` | ablations.md §3 thinking sweep: '34 model x thinking-level x tier cells ... 17 of 34 cells' and 3.5-flash hard medium 78% [28, 151] (n=20) | `results/gemini/ladder.json (regenerated at d165e3ec)` | ladder.json now has 42 cells (18 exclude parity) and 3.5-flash hard medium is 87% [50, 147] (n=40); ablations.md still has 34 cells |
| `docs/gemini/SUBMISSION.md:12` | States ladder runs 'five Gemini models' / 'Five models' across 587 episodes | `results/gemini/ladder.json` | 6 Gemini models in the 42-cell ladder: gemini-3.1-flash-lite, gemini-3.5-flash, gemini-3.8-flash, gemini-4-argon, gemini-4-carbon, gemini-4-hydrogen (WS1 added gemini-4-hydrogen) |
| `docs/gemini/VIDEO-2MIN.md:36` | States ladder runs 'five Gemini models' / 'Five models' across 587 episodes | `results/gemini/ladder.json` | 6 Gemini models in the 42-cell ladder: gemini-3.1-flash-lite, gemini-3.5-flash, gemini-3.8-flash, gemini-4-argon, gemini-4-carbon, gemini-4-hydrogen (WS1 added gemini-4-hydrogen) |
| `docs/gemini/SUBMISSION.md:40` | States ladder cells have '10–40 paired seeds' | `results/gemini/ladder.json (and results/gemini/ladder.md:3)` | 9–40 paired seeds per cell (gemini-4-hydrogen medium on medium and high on hard each have n=9) |
| `docs/gemini/SUBMISSION-LONG.md:32` | States ladder cells have '10–40 paired seeds' | `results/gemini/ladder.json (and results/gemini/ladder.md:3)` | 9–40 paired seeds per cell (gemini-4-hydrogen medium on medium and high on hard each have n=9) |
| `docs/gemini/SUBMISSION.md:5` | Usage totals: 24,855 calls, 678M input (578M / 85.3% cached), 9.39M thinking, $226.34 list price (smaller than ladder.md's 36,164 calls alone and contradicts 29,150 calls in §4) | `results/gemini/*ledger*.jsonl.gz + results/gemini/dashboard.html` | live committed ledgers (`dashboard --ledger committed`): 42,188 calls, 1.257B in (88.0% cached), 16.19M thinking, $377.11 list (dashboard.html still embeds 00:30 snapshot: 24,855 calls / $226.34) |
| `docs/gemini/SUBMISSION.md:37` | Usage totals: 24,855 calls, 678M input (578M / 85.3% cached), 9.39M thinking, $226.34 list price (smaller than ladder.md's 36,164 calls alone and contradicts 29,150 calls in §4) | `results/gemini/*ledger*.jsonl.gz + results/gemini/dashboard.html` | live committed ledgers (`dashboard --ledger committed`): 42,188 calls, 1.257B in (88.0% cached), 16.19M thinking, $377.11 list (dashboard.html still embeds 00:30 snapshot: 24,855 calls / $226.34) |
| `docs/gemini/SUBMISSION-LONG.md:7` | Usage totals: 24,855 calls, 678M input (578M / 85.3% cached), 9.39M thinking, $226.34 list price (smaller than ladder.md's 36,164 calls alone and contradicts 29,150 calls in §4) | `results/gemini/*ledger*.jsonl.gz + results/gemini/dashboard.html` | live committed ledgers (`dashboard --ledger committed`): 42,188 calls, 1.257B in (88.0% cached), 16.19M thinking, $377.11 list (dashboard.html still embeds 00:30 snapshot: 24,855 calls / $226.34) |
| `docs/gemini/SUBMISSION-LONG.md:20` | Usage totals: 24,855 calls, 678M input (578M / 85.3% cached), 9.39M thinking, $226.34 list price (smaller than ladder.md's 36,164 calls alone and contradicts 29,150 calls in §4) | `results/gemini/*ledger*.jsonl.gz + results/gemini/dashboard.html` | live committed ledgers (`dashboard --ledger committed`): 42,188 calls, 1.257B in (88.0% cached), 16.19M thinking, $377.11 list (dashboard.html still embeds 00:30 snapshot: 24,855 calls / $226.34) |
| `docs/gemini/SUBMISSION-LONG.md:49` | Usage totals: 24,855 calls, 678M input (578M / 85.3% cached), 9.39M thinking, $226.34 list price (smaller than ladder.md's 36,164 calls alone and contradicts 29,150 calls in §4) | `results/gemini/*ledger*.jsonl.gz + results/gemini/dashboard.html` | live committed ledgers (`dashboard --ledger committed`): 42,188 calls, 1.257B in (88.0% cached), 16.19M thinking, $377.11 list (dashboard.html still embeds 00:30 snapshot: 24,855 calls / $226.34) |
| `pitch/GEMINI.md:9` | Usage totals: 24,855 calls, 678M input (578M / 85.3% cached), 9.39M thinking, $226.34 list price (smaller than ladder.md's 36,164 calls alone and contradicts 29,150 calls in §4) | `results/gemini/*ledger*.jsonl.gz + results/gemini/dashboard.html` | live committed ledgers (`dashboard --ledger committed`): 42,188 calls, 1.257B in (88.0% cached), 16.19M thinking, $377.11 list (dashboard.html still embeds 00:30 snapshot: 24,855 calls / $226.34) |
| `docs/gemini/SUBMISSION.md:24` | §4 Explicit caching programme total: saved 75.9% ($678.19 of $893.08, i.e. $214.89 paid) across all 29,150 ledgered calls | `results/gemini/ablations.json vs canary/gemini/dashboard.py` | Committed ledgers at d165e3ec now hold 42,188 calls ($377.11 paid with EXTRA_PRICES); ablations.py was run at 29,150 calls AND omits EXTRA_PRICES on 12,347 Flash/Flash-Lite calls |
| `docs/gemini/SUBMISSION-LONG.md:60` | §4 Explicit caching programme total: saved 75.9% ($678.19 of $893.08, i.e. $214.89 paid) across all 29,150 ledgered calls | `results/gemini/ablations.json vs canary/gemini/dashboard.py` | Committed ledgers at d165e3ec now hold 42,188 calls ($377.11 paid with EXTRA_PRICES); ablations.py was run at 29,150 calls AND omits EXTRA_PRICES on 12,347 Flash/Flash-Lite calls |
| `docs/gemini/SUBMISSION-LONG.md:75` | SUBMISSION-LONG.md §Gemini across the team (HoldUp): speculative verification cut question-to-first-audio from 5.8 s to 0.7–1.75 s | `s1laswang/junction-meta-glasses GEMINI.md:32` | 5.8 s (1 run before) -> p50 2.1 s / p95 3.4 s across n=26 live sessions (0.7–1.75 s was an early 3-run spot check) |
| `docs/gemini/ROLES.md:9` | ROLES.md Frontier subject row: commit 016758ace5, Size '157 episodes, 34 cells', Headline 'gemini-4-carbon (default) reaches 66% of the solver on hard [95% CI 5%, 117%], n=10' | `results/gemini/ladder.json (vs stale results/gemini/roles/index.json)` | ladder.json git_sha=007802f532, episodes=587 in 42 cells (6 models); carbon default hard: n=22, 108% [62%, 189%] |
| `docs/gemini/ROLES.md:27` | ROLES.md prose (:27): 'checked with canary/text/lint.py, assert_no_truth...' (implies pass, whereas assert_no_truth_pass is 0/6 in lint_probe.json) | `results/gemini/roles/worldtext/lint_probe.json` | assert_no_truth_pass=0/6 (template uniqueness heuristic flags 20/20 distinct LLM persona tones) |
| `docs/gemini/VIDEO-2MIN.md:19` | Rendered audio docs/gemini/assets/narration-2min/03-ladder.wav + canary-lab-2min.mp4 match VIDEO-2MIN.md VO[03-ladder] | `docs/gemini/assets/narration-2min/index.json + results/gemini/video_qa.json` | 03-ladder.wav still speaks old n=8 text ('one hundred fifty-seven paired episodes... ninety-two percent'); video_qa.json screen shows 24,415 calls / $222 |
| `docs/gemini/VIDEO.md:31` | VIDEO.md Assets table cites `results/gemini/ladder.png` and `results/gemini/charts/*.png` | `results/gemini/` | Actual committed paths are `results/gemini/frontier.png` / `ladder_{heatmap,curve,cost,tags}.png` and `results/gemini/atlas_charts/*.png` |
| `docs/gemini/VIDEO.md:58` | VIDEO.md VO[02-ladder]: 'paired episodes, fanned out over our cluster through one Gemini gateway' | `results/gemini/ladder_ledger.jsonl.gz + docs/gemini/reports/gateway.md:47` | All ladder calls ran on Mac (FR8 cluster ssh was unreachable from venue LAN per gateway.md:47 and CEO.md:85) |
| `docs/gemini/PLAN.md:64` | PLAN.md §Architecture & §Close claim 'Batch API for per-decision labels' and 'batch economics' | `results/gemini/usage_ledger.jsonl.gz + docs/gemini/reports/CEO.md:40` | 0 successful batch calls (all 5 batch attempts failed with RESOURCE_EXHAUSTED) |
| `docs/gemini/PLAN.md:73` | PLAN.md §Innovation claims: 'where thinking helps (canary design) and where it does not (commit timing)' | `results/gemini/ladder.md:9` | Measured result is the opposite: thinking reduces premature_accusation regret (-0.16 med, -0.22 hard) while uninformative_canary is flat |

## Reproduce
```bash
uv run --extra llm --extra dev --extra plot python -m canary.gemini.qa --replay   # 0 API calls
```
