# v1.4 Replay Verification, Paired Gap, and Replay Lane Staging Report

## 1. v1.4 Replay Verification and Chief DATA RULE Audit

### Staged Dataset Composition

All v1.4 reference and frontier episode shards were staged in `/localscratch/aq-tmp/w6-runs/v1.4/` and verified using:

```bash
PY="env PYTHONPATH=. TMPDIR=/localscratch/aq-tmp /home/silas/agent-arena-data/fleet-shared-venv/bin/python"
$PY scripts/verify_replay.py /localscratch/aq-tmp/w6-runs/v1.4
```

- **Reference runs (`origin/fr8/afterquery/prs` at `95bf45f7`):** 8 scripted policies (`solver`, `grok_tactics`, `heuristic`, `logs_only`, `do_nothing`, `stop_early`, `random`, `restrict_all`) across medium dev seeds `0-29` (240 episodes) and hard dev seeds `0-59` (480 episodes) = **720 episodes**. (Note: `origin/justSilas` at `b4557e00` currently holds the 6-policy dev `0-19` subset = **240 episodes**.)
- **Frontier runs (`origin/fr8/afterquery/v14-runs` at `d5801220` / `6225cf86`):**
  - `inproc-gemini-4-carbon` (`gemini:gemini-4-carbon`): medium seeds `0-9` (10 episodes) + hard seeds `0-19` (20 episodes) = **30 episodes**.
  - `opencode-gemini-3.5-flash` (`opencode:google/gemini-3.5-flash`, PLAN-95 A4 second family): medium seeds `0-29` (30 episodes) + hard seeds `0-29` (30 episodes) = **60 episodes**.
  - `opencode-gemini-4-carbon` (`opencode:google/gemini-4-carbon`): hard seed `7` = **1 episode** (pending `frontier` squad completion of hard seeds `30-59` with raised timeout).

### Deterministic Replay Verification Results

Every recorded episode was re-executed from scratch in a fresh `canary.env.Env(tier, seed)` and checked for exact score (`|replay - recorded| < 1e-9`) and accused-employee match:

| Source / Folder | Tier Coverage | Verified / Total | Mismatches | Exit Code |
|---|---|---:|---:|---:|
| `origin/justSilas` (`b4557e00`) `v1.4/reference` | medium `0-19`, hard `0-19` (6 policies) | `240 / 240` | `0` | `0` |
| `origin/fr8/afterquery/prs` (`95bf45f7`) `v1.4/reference` | medium `0-29`, hard `0-59` (8 policies) | `720 / 720` | `0` | `0` |
| `v14-runs` `v1.4/inproc-gemini-4-carbon` | medium `0-9`, hard `0-19` | `30 / 30` | `0` | `0` |
| `v14-runs` `v1.4/opencode-gemini-3.5-flash` | medium `0-29`, hard `0-29` | `60 / 60` | `0` | `0` |
| `v14-runs` `v1.4/opencode-gemini-4-carbon` | hard seed `7` | `1 / 1` | `0` | `0` |
| **Combined staged `w6-runs/v1.4` (shards and consolidated)** | **all staged v1.4 runs** | **`811 / 811`** | **`0`** | **`0`** |

(Cross-check on `origin/fr8/gemini/main` `data/runs/committed/v1.4/gemini-4-carbon`, covering easy `0-3`, medium `0-9`, hard `0-8`: `23 / 23` episodes replay-verified with `0` mismatches.)

### Chief DATA RULE Audit

All JSONL lines and shard `meta.json` manifests in `origin/fr8/afterquery/v14-runs` (`d5801220` and `6225cf86`, 571 episodes on branch; 811 episodes when combined with `95bf45f7` hard `30-59` references) were audited directly without filtering:

| Check | `v14-runs` (`d5801220` / `6225cf86`) | Combined Staged `w6-runs/v1.4` | Status |
|---|---:|---:|---|
| Episodes with `rc == "timeout"` | `0` | `0` | PASS |
| Episodes with `end_reason == "error"` | `0` | `0` | PASS |
| Episodes with `meta.valid == False` | `0` | `0` | PASS |
| Episodes with `wall_s` at timeout cap | `0` | `0` | PASS |
| Duplicate `(agent, tier, seed)` tuples | `0` | `0` | PASS |

- **Wall-clock ranges on retained OpenCode episodes:**
  - `opencode-gemini-3.5-flash` medium (`n=30`): `65.6s` to `346.3s` (`rc=0`, all `end_reason == "accused"`).
  - `opencode-gemini-3.5-flash` hard (`n=30`): `108.7s` to `327.5s` (`rc=0`, all `end_reason == "accused"`).
  - `opencode-gemini-4-carbon` hard seed `7` (`n=1`): `879.1s` (`rc=0`, `end_reason == "accused"`, score `+0.8100` on day 5).
- **Documentation of Timeout Purge (`2768af14`, `d5801220`, `6225cf86`):**
  - Commit `2768af14` removed **59 timed-out `opencode-gemini-4-carbon` episodes** across 14 shard files: 30 medium episodes (`wall_s` in `[601.0s, 610.3s]` hitting the 600s runner cap) and 29 hard episodes (`wall_s` in `[900.3s, 901.3s]` hitting the 900s runner cap). All 59 removed rows had `rc == "timeout"` and `end_reason == "error"`.
  - Commit `d5801220` deleted the 13 emptied shard directories (`medium-00-04` through `medium-25-29`, `hard-00-03`, `hard-08-11` through `hard-27-29`).
  - Commit `6225cf86` merged `origin/justSilas` (`b4557e00`) into `v14-runs`, updated `opencode-gemini-4-carbon/hard-04-07/meta.json` to `"seeds": [7]`, and removed the 3 orphan transcripts (`4.txt`, `5.txt`, `6.txt`), leaving `git diff origin/justSilas..origin/fr8/afterquery/v14-runs` confined strictly to `data/runs/committed/v1.4/`.

---

## 2. Paired Solver and Luck-Adjusted Gap Table (v1.4 Seeds 0-29)

Shard JSONLs in `/localscratch/aq-tmp/w6-runs/v1.4/` were consolidated into `{inproc-gemini-4-carbon,opencode-gemini-3.5-flash,opencode-gemini-4-carbon}/{medium,hard}/episodes.jsonl` (re-verified at `811 / 811` episodes) and evaluated with:

```bash
$PY scripts/paired_gemini.py --root /localscratch/aq-tmp/w6-runs --version v1.4 --seeds 0-29
```

### Measured Paired Table (v1.4, Dev Seeds 0-29, 10,000-Resample Paired Bootstrap 95% CIs)

| tier | run | n | score +/- 95% CI | accuracy | accused | abstain | mean accuse day | mean P(accused) | solver, same seeds | frontier / solver [95% CI] | paired diff +/- CI | luck-adjusted score | luck-adj. / solver luck-adj. [95% CI] |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---|---|---:|---|
| medium | in-process gemini-4-carbon (full history, thought-signature replay) | 10 | 0.697 +/- 0.085 | 1.00 | 1.00 | 0.00 | 8.3 | 1.00 | 0.730 | 95% [81%, 114%] | -0.033 +/- 0.132 | 0.697 | **95% [81%, 114%]** |
| medium | OpenCode + gemini-3.5-flash over MCP (second Gemini family; modelVersion gemini-3.6-flash) | 30 | 0.429 +/- 0.235 | 0.83 | 1.00 | 0.00 | 9.2 | 0.87 | 0.645 | 66% [29%, 102%] | -0.216 +/- 0.250 | 0.479 | **74% [44%, 104%]** |
| medium | reference solver | 30 | 0.645 +/- 0.087 | 0.90 | 0.90 | 0.10 | 7.6 | 1.00 | 0.645 | - | - | 0.645 | - |
| medium | heuristic | 30 | -0.407 +/- 0.284 | 0.37 | 1.00 | 0.00 | 11.3 | 0.59 | 0.645 | -63% [-107%, -19%] | -1.052 +/- 0.301 | -0.064 | **-10% [-36%, 18%]** |
| medium | do_nothing | 30 | 0.000 +/- 0.000 | 0.00 | 0.00 | 1.00 | 0.0 | - | 0.645 | 0% [0%, 0%] | -0.645 +/- 0.087 | 0.000 | **0% [0%, 0%]** |
| medium | stop_early | 30 | -0.933 +/- 0.131 | 0.03 | 1.00 | 0.00 | 1.0 | 0.05 | 0.645 | -145% [-175%, -118%] | -1.578 +/- 0.160 | -0.900 | **-140% [-163%, -125%]** |
| hard | OpenCode + gemini-4-carbon over MCP (judges' shape) | 1 | 0.810 +/- 0.000 | 1.00 | 1.00 | 0.00 | 5.0 | 0.96 | 0.640 | 127% | 0.170 +/- 0.000 | 0.734 | 115% |
| hard | in-process gemini-4-carbon (full history, thought-signature replay) | 20 | 0.573 +/- 0.069 | 1.00 | 1.00 | 0.00 | 11.5 | 0.95 | 0.464 | 123% [91%, 214%] | 0.109 +/- 0.195 | 0.492 | **99% [83%, 120%]** |
| hard | OpenCode + gemini-3.5-flash over MCP (second Gemini family; modelVersion gemini-3.6-flash) | 30 | 0.535 +/- 0.050 | 1.00 | 1.00 | 0.00 | 11.5 | 0.91 | 0.499 | 107% [88%, 146%] | 0.036 +/- 0.125 | 0.404 | **81% [57%, 102%]** |
| hard | reference solver | 30 | 0.499 +/- 0.119 | 0.97 | 1.00 | 0.00 | 10.6 | 0.97 | 0.499 | - | - | 0.499 | - |
| hard | heuristic | 30 | 0.086 +/- 0.204 | 0.80 | 1.00 | 0.00 | 14.4 | 0.78 | 0.499 | 17% [-26%, 60%] | -0.413 +/- 0.250 | 0.052 | **10% [-20%, 37%]** |
| hard | do_nothing | 30 | 0.000 +/- 0.000 | 0.00 | 0.00 | 1.00 | 0.0 | - | 0.499 | 0% [0%, 0%] | -0.499 +/- 0.119 | 0.000 | **0% [0%, 0%]** |
| hard | stop_early | 30 | -1.000 +/- 0.000 | 0.00 | 1.00 | 0.00 | 1.0 | 0.03 | 0.499 | -200% [-271%, -167%] | -1.499 +/- 0.119 | -0.950 | **-190% [-218%, -169%]** |

*(Extended hard reference baseline on seeds `0-59`, `n=60`, ready for incoming `frontier` OpenCode runs on seeds `30-59`: `solver` mean `0.498 +/- 0.097`, accuracy `0.93`, accused `0.98`, abstain `0.02`, mean accuse day `9.5`, mean `P(accused) = 0.96`, luck-adjusted score `0.521`.)*

### Accusation Posterior and Failure-Tag Findings (`canary.analysis.accuse`, `canary.analysis.tags`)

1. **Zero frontier abstentions (`abstain = 0.00` across all 91 frontier episodes):** Every recorded frontier episode ended in an accusation (`91 / 91`), whereas the reference solver abstained on `10%` of medium seeds (`0-29`) and `2%` of hard seeds (`0-59`) when `P(top)` stayed below `1 / (1 + V)`.
2. **`opencode-gemini-3.5-flash` (`n=60`):**
   - **Hard (`n=30`, seeds `0-29`):** Raw score reaches `107% [88%, 146%]` (`0.535` vs solver `0.499`), but luck-adjusted EV drops by 26 percentage points to **`81% [57%, 102%]`** (`0.404` vs `0.499`). Accusation audit (`canary.analysis.accuse`) identifies `28` justified accusations and `2` lucky sub-threshold gambles that happened to hit the mole (`seed 7` on day 19 at `P(accused) = 0.312`; `seed 20` on day 15 at `P(accused) = 0.323`), alongside lower average posterior certainty (`0.91` vs solver `0.97`).
   - **Medium (`n=30`, seeds `0-29`):** Scores `0.429 +/- 0.235` (`66% [29%, 102%]` raw, **`74% [44%, 104%]`** luck-adjusted): `24` justified accusations, `1` lucky gamble (`seed 8`, day 14, `P = 0.401`), and `5` premature wrong accusations (`seed 11` `P = 0.221`, `seed 13` `P = 0.533`, `seed 22` `P = 0.166`, `seed 26` `P = 0.354`, `seed 29` `P = 0.323`). Across all 60 episodes, `canary.analysis.tags` attributes `4.49 V` of regret to `premature_accusation` (13% of episodes) and `1.58 V` to `uninformative_canary` (23% of episodes), out of `11.61 V` total regret.
3. **`inproc-gemini-4-carbon` (`n=30`):**
   - **Medium (`n=10`, seeds `0-9`):** `10 / 10` justified accusations at `P(accused) = 1.00`, scoring `0.697 +/- 0.085` vs solver `0.730` (`95% [81%, 114%]` raw and luck-adjusted).
   - **Hard (`n=20`, seeds `0-19`):** `20 / 20` justified accusations (`mean P(accused) = 0.95`), scoring `0.573 +/- 0.069` vs solver `0.464` (`123% [91%, 214%]` raw) and `0.492` vs solver luck-adjusted `0.495` (**`99% [83%, 120%]`** luck-adjusted; the raw >100% ratio reflects one wrong solver accusation on seeds `0-19`, whereas EV-adjusted performance is at parity `0.995x`).
4. **`opencode-gemini-4-carbon` (`n=1`):** Only `hard` seed `7` remains in `v14-runs` (`0.810` on day 5 at `P(accused) = 0.958`, justified); a statistically meaningful MCP headline for `gemini-4-carbon` requires the in-flight `frontier` squad runs on hard seeds `30-59`.

---

## 3. `replay` Squad Lane PR Staging Audit (`origin/fr8/afterquery/replay`)

Target branch `origin/fr8/afterquery/replay` (`089e0acc`) was audited against `origin/justSilas` (`b4557e00`) in an isolated worktree at `/localscratch/aq-tmp/wt-w6-replay`.

| Staging Gate | Command / Check | Result | Verdict |
|---|---|---|---|
| Base ancestry | `git merge-base origin/justSilas origin/fr8/afterquery/replay` | `b4557e00` (`origin/justSilas` tip is direct parent via `ea15f98c`) | PASS |
| Conflict-free merge | `git merge-tree --write-tree origin/justSilas origin/fr8/afterquery/replay` | Tree `3ff02d91c1ae0c4dbd926abe9611e490037fe2c6`, exit code `0` (`0` conflicts) | PASS |
| Lane file isolation | `git diff --name-status origin/justSilas..origin/fr8/afterquery/replay` | `3` added files: `A replay/__init__.py`, `A replay/loader.py`, `A tests/test_replay_loader.py` (`0` core/env/solver/harbor/stale `c01f371a` diffs) | PASS |
| Code comments (`#`) | Python `tokenize` + raw `#` line scan across all 3 files (607 lines) | `0` comment tokens, `0` `#` characters | PASS |
| Unicode dashes | Scan for `\u2014` (em dash) and `\u2013` (en dash) across all 3 files | `0` em dashes, `0` en dashes | PASS |
| Secrets / API keys | Regex scan (`AIza*`, `sk-*`, `ghp_*`, hardcoded `*_API_KEY`) | `0` matches | PASS |
| Unit tests | `$PY -m pytest -v tests/test_replay_*.py` (cwd = worktree root) | `6 passed in 2.15s` | PASS |
| Real-data smoke test | `load_committed_episodes()` + `pair_with_solver()` | Loads `821` `justSilas` committed episodes (`691` paired) and `811` staged `w6-runs` v1.4 episodes (`720` scripted + `91` real; `721 / 721` solver-paired) | PASS |

### Staging Notes for `replay` PR into `justSilas`

1. **Current branch state (`089e0acc`) is clean and merge-ready** as a zero-conflict fast-forward onto `origin/justSilas` (`b4557e00`), touching only `replay/` and `tests/test_replay_loader.py`.
2. **In-flight worker modules (`afterquery-replay-w2..w9`):** Only `afterquery-replay-w1` (`207a4349`, merged at `089e0acc`) had landed on `origin/fr8/afterquery/replay` at audit time; `replay-w2..w9` (`belief_trace.py`, `fooled.py`, `analytics.py`, `replay/web/*`, `validate.py`, `cli.py`) are still in progress and were originally branched from `c01f371a`, so `afterquery-replay-lead` must cherry-pick or rebase those onto `089e0acc` without re-introducing `c01f371a` diffs (`canary/mcp_server.py`, `configs/README.md`, `tests/test_integrity_secrets.py`) before final PR packaging.
3. **Minor test CWD note:** `test_real_committed_episodes_and_pairing` calls `load_committed_episodes()` with its default relative path `"data/runs/committed"` and asserts `ep["source_path"].startswith("data/runs/committed/")`. It passes `6 / 6` when `pytest` runs from the repository root (standard CI and `make test` behavior), though invoking `pytest` from a different working directory causes `Path.resolve()` to fall outside the worktree root.
