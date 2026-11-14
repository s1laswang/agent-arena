# Fleet Main, PR #3 / #4 / #5 / #12 Collision, Deterministic Reproduce, and Markdown Link Audit

## 1. Branch Diff and PR #12 Collision Matrix vs `origin/justSilas` (`b4557e00`)

### Audited Branches and Merge-Tree Results

All fleet branches and Vaishnav's anti-cheat PR #12 (`origin/vaishnav/canary-cheat`, `06ebf9cd`) were audited against `origin/justSilas` (`b4557e00f881edea464699c058b0f6114af49111`). Note that during the audit window `origin/fr8/afterquery/main` advanced from spec target `ef5c428a` to `16911dff` (merging `v14-runs` `6225cf86` and `replay` `089e0acc`), and `origin/fr8/afterquery/prs` advanced from `95bf45f7` to `5729e492` (merging `prs-w6` `f5463924`); both the spec SHAs and current branch tips are reported below.

| Branch / PR | Commit SHA | Merge-Base with `b4557e00` | Behind / Ahead vs `b4557e00` | Changed Files (`--no-renames`) | Path Overlap with PR #12 (`06ebf9cd`) | `git merge-tree --write-tree <branch> 06ebf9cd` | Merge Exit Code |
|---|---|---|---:|---:|---:|---|---:|
| `origin/justSilas` (base) | `b4557e00` | `b4557e00` | `0 / 0` | `0` | `0` | `9be12e3198059d0eb05baaeb6c775f90055f0f37` | `0` |
| `origin/fr8/afterquery/main` (spec) | `ef5c428a` | `b4557e00` | `0 / 10` | `16` | `0` | `11e95125538c98031d5572af7c423642f7928242` | `0` |
| `origin/fr8/afterquery/main` (current tip) | `16911dff` | `b4557e00` | `0 / 67` | `158` | `0` | `0331213191a4afb80e84aa7ca120416e21100c1b` | `0` |
| `origin/fr8/afterquery/prs` (spec) | `95bf45f7` | `b4557e00` | `0 / 14` | `48` | `0` | `0859a3f2ec2ad88a0c34b1d881e82a7115e2283d` | `0` |
| `origin/fr8/afterquery/prs` (current tip) | `5729e492` | `b4557e00` | `0 / 18` | `49` | `0` | `fc573232ce4248a89e9ca739c76f05461dee358f` | `0` |
| `origin/fr8/afterquery/v14-runs` (PR #3) | `6225cf86` | `b4557e00` | `0 / 49` | `139` | `0` | `979b145d4be3d93c51e9615c311afc6f003199d7` | `0` |
| `origin/fr8/afterquery/afterquery-w25` (PR #4) | `664f653a` | `b4557e00` | `0 / 6` | `2` | `0` | `e5db1450c401745e236a13e05541941e44710f10` | `0` |
| `origin/fr8/afterquery/afterquery-w39` (PR #5) | `59bbab30` | `b4557e00` | `0 / 5` | `2` | `0` | `36839025eeb4db04d0203f12f4ebb87aa2896345` | `0` |
| `origin/vaishnav/canary-cheat` (PR #12) | `06ebf9cd` | `b4557e00` | `0 / 3` | `75` (`53` w/ renames) | `--` (self) | `9be12e3198059d0eb05baaeb6c775f90055f0f37` | `0` |

Cross-check across active squad staging branches (`origin/fr8/afterquery/frontier` `c107a056`, `origin/fr8/afterquery/integrity` `6a63f17a`, `origin/fr8/afterquery/replay` `089e0acc`, and `origin/fr8/afterquery/research` `bf390ada`): all four also have merge-base `b4557e00`, `0` path overlap with `06ebf9cd`, and `git merge-tree --write-tree` exit code `0`.

Sequential cumulative merge simulation onto `b4557e00` across `6225cf86` (PR #3) -> `664f653a` (PR #4) -> `59bbab30` (PR #5) -> `95bf45f7` (`prs`) -> `16911dff` (`main` tip) -> `06ebf9cd` (PR #12) also succeeds cleanly at every step with `0` conflicts, producing combined root tree `d962c8e4381181261233400e3cf34039601aef09`.

### Exact File-Scope Breakdown and PR #12 Overlap Analysis

- **`origin/fr8/afterquery/main` (`ef5c428a`):** Adds `16` files strictly under `data/runs/committed/v1.4/reference/*-hard-seeds30to59/{episodes.jsonl,meta.json}` (8 reference policies on hard seeds `30-59`). At tip `16911dff`, adds `158` files: `155` under `data/runs/committed/v1.4/` (`16` from `ef5c428a` + `139` from `6225cf86`) plus `3` added files from `replay` (`replay/__init__.py`, `replay/loader.py`, `tests/test_replay_loader.py`).
- **`origin/fr8/afterquery/prs` (`95bf45f7`):** Adds `48` files strictly under `data/runs/committed/v1.4/reference/` (completing medium `0-29` and hard `0-59` across all 8 reference policies). Tip `5729e492` adds `docs/reports/prs_v14_verification.md` (`49` added files total).
- **`origin/fr8/afterquery/v14-runs` (`6225cf86`, PR #3):** Adds `139` files strictly under `data/runs/committed/v1.4/` (`32` reference files completing dev seeds `0-29` across 8 policies + `107` frontier episode/meta/transcript files across `inproc-gemini-4-carbon`, `opencode-gemini-3.5-flash`, and `opencode-gemini-4-carbon`).
- **`origin/fr8/afterquery/afterquery-w25` (`664f653a`, PR #4):** Adds `2` new files (`A canary/redteam/encodings.py`, `A tests/test_encodings.py`).
- **`origin/fr8/afterquery/afterquery-w39` (`59bbab30`, PR #5):** Adds `2` new files (`A scripts/audit_submission.py`, `A tests/test_submission_audit.py`).
- **`origin/vaishnav/canary-cheat` (`06ebf9cd`, PR #12):** `3` commits (`0fe79615`, `7e30597b`, `06ebf9cd`) touching `75` raw file paths (`53` with rename detection):
  - Core / harness / docs / tests (`13` files): `M README.md`, `M canary/eval.py`, `M canary/redteam/anticheat.py`, `M canary/redteam/harbor_cheat.py`, `M canary/reproduce.py`, `M docs/EXPLOITS.md`, `A docs/reports/anticheat-vaishnav.md`, `M harbor/README.md`, `M harbor/build.py`, `M harbor/template/solution/cheat.py`, `M harbor/template/tests/test.sh`, `M tests/test_anticheat.py`, `M tests/test_harbor_cheat.py`.
  - Anti-cheat and Harbor artifacts (`62` raw paths): `A results/anticheat/{exploits.json,exploits.md}`, `M results/harbor/cheat-probe/{lock.json,result.json}`, replacement of `results/harbor/cheat-probe/canary-hard-900000__AwDSgro/*` (`14` deleted) and `canary-medium-900000__QhAYkU6/*` (`14` deleted) with refreshed signed-ledger runs `canary-hard-900000__d4KEFRV/*` (`15` added) and `canary-medium-900000__ECtdfdM/*` (`15` added).
- **Collision verdict:** Exact path intersection between every audited fleet branch (`ef5c428a`, `16911dff`, `95bf45f7`, `5729e492`, `6225cf86`, `664f653a`, `59bbab30`) and PR #12 (`06ebf9cd`) is **empty (`0` overlapping files)**.
- **Semantic coordination note for downstream PRs:** PR #12 updates `canary/eval.py` so `--reproduce` exits `1` whenever `anticheat_ok is False` (any failed probe, replay mismatch under `data/runs/committed/`, or inconsistent Harbor trial/job). Because `v14-runs` (`6225cf86`) and `main` (`ef5c428a` / `16911dff`) have `100%` replay consistency (`0` mismatches), merging PR #3 and PR #12 in either order preserves `exit_code = 0`. Future fleet PRs that edit `README.md`, `docs/EXPLOITS.md`, `harbor/`, `canary/reproduce.py`, `canary/redteam/anticheat.py`, or `tests/test_anticheat.py` should base on top of `06ebf9cd` once PR #12 lands on `justSilas`.

---

## 2. Deterministic `reproduce` Verification (`CANARY_WORLD_SECRET=audit-w9-fixed REPRO_FAST=1`)

### Execution Command and Bit-for-Bit Paired Equality

Detached worktrees were created in `/localscratch/aq-tmp/w9-wt-*` and evaluated with:

```bash
PY="env PYTHONPATH=. TMPDIR=/localscratch/aq-tmp /home/silas/agent-arena-data/fleet-shared-venv/bin/python"
CANARY_WORLD_SECRET=audit-w9-fixed REPRO_FAST=1 $PY -m canary.eval --reproduce --results-dir /localscratch/aq-tmp/w9-out-<name>
```

| Target | Commit SHA | Exit Code | Secret Mode & Fingerprint | `judge_episodes.jsonl` Bytes (Episodes) | `judge_episodes.jsonl` SHA-256 | Active Committed JSONLs (Episodes) | Replay Consistent / Total (`not_replayable`) | Harbor Consistent |
|---|---|---:|---|---|---|---:|---:|---:|
| (a) `origin/justSilas` | `b4557e00` | `0` | `exact` (`c6edba69508e`) | `14810` (`90`) | `4128034e0e6b590d39d1493a121d4a5ffd9f8adde28554618c6233fe36679ad4` | `54` (`829`) | `819 / 829` (`10`) | `25 / 25` |
| (b) `origin/fr8/afterquery/main` (spec) | `ef5c428a` | `0` | `exact` (`c6edba69508e`) | `14810` (`90`) | `4128034e0e6b590d39d1493a121d4a5ffd9f8adde28554618c6233fe36679ad4` | `62` (`1069`) | `1059 / 1069` (`10`) | `25 / 25` |
| (c) `origin/fr8/afterquery/v14-runs` (PR #3) | `6225cf86` | `0` | `exact` (`c6edba69508e`) | `14810` (`90`) | `4128034e0e6b590d39d1493a121d4a5ffd9f8adde28554618c6233fe36679ad4` | `78` (`1160`) | `1150 / 1160` (`10`) | `25 / 25` |
| (d) `origin/fr8/afterquery/main` (tip) | `16911dff` | `0` | `exact` (`c6edba69508e`) | `14810` (`90`) | `4128034e0e6b590d39d1493a121d4a5ffd9f8adde28554618c6233fe36679ad4` | `86` (`1400`) | `1390 / 1400` (`10`) | `25 / 25` |
| (e) `origin/vaishnav/canary-cheat` (PR #12) | `06ebf9cd` | `0` | `exact` (`c6edba69508e`) | `14810` (`90`) | `4128034e0e6b590d39d1493a121d4a5ffd9f8adde28554618c6233fe36679ad4` | `54` (`829`) | `819 / 829` (`10`) | `36 / 36` |

- **Bit-for-bit equality confirmed:** `judge_episodes.jsonl` (`90` paired episodes = `3` tiers x `6` in-process policies x `5` judge seeds `900000..900004`) has identical SHA-256 digest `4128034e0e6b590d39d1493a121d4a5ffd9f8adde28554618c6233fe36679ad4` across (a), (b), (c), (d), and (e).
- **Final stdout anti-cheat line on every run (a)-(e):**
  `ANTI-CHEAT: every probe blocked, every replayable episode and Harbor trial consistent`
  (`all_blocked = True`, `replay_all_consistent = True`, `harbor_all_consistent = True`; the `10` `not_replayable` episodes in every checkout are the legacy v1.2 `data/runs/committed/grok/{medium,hard}` runs on judge seeds `900000..900004`, which require the private Harbor judge secret).

### Identical Paired Solver / Baseline Scores Across (a)-(e) (`seeds 900000..900004`, `c6edba69508e`)

| Tier | Policy | Kind | `n` | `invalid` | Score +/- 95% CI | Accuracy | Accused | Mean Accuse Day | `/ solver` |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| `medium` | `solver` | `reference` | `5` | `0` | `+0.698 +/- 0.154` | `1.00` | `5/5` | `8.8` | `1.00` |
| `medium` | `heuristic` | `baseline` | `5` | `0` | `-0.388 +/- 0.735` | `0.40` | `5/5` | `12.0` | `-0.56` |
| `medium` | `logs_only` | `baseline` | `5` | `0` | `-1.000 +/- 0.000` | `0.00` | `5/5` | `10.0` | `-1.43` |
| `medium` | `random` | `baseline` | `5` | `0` | `-0.400 +/- 0.480` | `0.00` | `2/5` | `3.5` | `-0.57` |
| `medium` | `stop_early` | `baseline` | `5` | `0` | `-0.600 +/- 0.784` | `0.20` | `5/5` | `1.0` | `-0.86` |
| `medium` | `do_nothing` | `baseline` | `5` | `0` | `+0.000 +/- 0.000` | `0.00` | `0/5` | `--` | `0.00` |
| `hard` | `solver` | `reference` | `5` | `0` | `+0.606 +/- 0.138` | `1.00` | `5/5` | `8.6` | `1.00` |
| `hard` | `heuristic` | `baseline` | `5` | `0` | `-0.240 +/- 0.610` | `0.60` | `5/5` | `18.0` | `-0.40` |
| `hard` | `logs_only` | `baseline` | `5` | `0` | `-1.000 +/- 0.000` | `0.00` | `5/5` | `10.0` | `-1.65` |
| `hard` | `random` | `baseline` | `5` | `0` | `-0.600 +/- 0.480` | `0.00` | `3/5` | `3.7` | `-0.99` |
| `hard` | `stop_early` | `baseline` | `5` | `0` | `-1.000 +/- 0.000` | `0.00` | `5/5` | `1.0` | `-1.65` |
| `hard` | `do_nothing` | `baseline` | `5` | `0` | `+0.000 +/- 0.000` | `0.00` | `0/5` | `--` | `0.00` |
| `easy` | `solver` | `reference` | `5` | `0` | `+0.808 +/- 0.058` | `1.00` | `5/5` | `4.2` | `1.00` |
| `easy` | `heuristic` | `baseline` | `5` | `0` | `+0.684 +/- 0.065` | `1.00` | `5/5` | `6.6` | `0.85` |
| `easy` | `logs_only` | `baseline` | `5` | `0` | `-0.340 +/- 0.792` | `0.40` | `5/5` | `10.0` | `-0.42` |
| `easy` | `random` | `baseline` | `5` | `0` | `-0.800 +/- 0.392` | `0.00` | `4/5` | `5.5` | `-0.99` |
| `easy` | `stop_early` | `baseline` | `5` | `0` | `-1.000 +/- 0.000` | `0.00` | `5/5` | `1.0` | `-1.24` |
| `easy` | `do_nothing` | `baseline` | `5` | `0` | `+0.000 +/- 0.000` | `0.00` | `0/5` | `--` | `0.00` |

### Rendering of `v14-runs` (`6225cf86`) Shard Subdirectories in `judge_table.md`

In `canary/reproduce.py`, `load_committed()` groups all non-superseded `data/runs/committed/**/episodes.jsonl` rows by `(tier, tiers_version, agent)` across shard subdirectories, recording `invalid` (`meta.valid == false`), `distinct seeds`, and `dropped_duplicates` (any older duplicate seed across shard directories). On `origin/fr8/afterquery/v14-runs` (`6225cf86`), `Reported agent runs: v1.4 (current rules)` renders `21` rows (`10` on `medium`, `11` on `hard`):

| Tier | Rendered `agent` | `n` | Distinct Seeds | `invalid` | `dropped_duplicates` | Score +/- 95% CI | Accuracy | Accused | Mean Day | Shard Subdirectories Pooled under `data/runs/committed/v1.4/` |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| `medium` | `gemini:gemini-4-carbon` | `10` | `10` | `0` | `0` | `+0.697 +/- 0.085` | `1.00` | `10/10` | `8.3` | `inproc-gemini-4-carbon/medium-00-09` |
| `medium` | `grok_tactics` | `30` | `30` | `0` | `0` | `+0.460 +/- 0.123` | `0.70` | `21/30` | `7.7` | `reference/grok_tactics-medium-seeds0to29` |
| `medium` | `opencode:google/gemini-3.5-flash` | `30` | `30` | `0` | `0` | `+0.429 +/- 0.235` | `0.83` | `30/30` | `9.2` | `opencode-gemini-3.5-flash/{medium-00-14,medium-15-29}` |
| `medium` | `restrict_all` | `30` | `30` | `0` | `0` | `-0.933 +/- 0.091` | `0.07` | `30/30` | `7.0` | `reference/{restrict_all-medium-20261114-121126,restrict_all-medium-seeds20to29}` |
| `medium` | `solver` | `30` | `30` | `0` | `0` | `+0.645 +/- 0.087` | `0.90` | `27/30` | `7.6` | `reference/{solver-medium-20261114-121126,solver-medium-seeds20to29}` |
| `medium` | `heuristic` | `30` | `30` | `0` | `0` | `-0.407 +/- 0.284` | `0.37` | `30/30` | `11.3` | `reference/{heuristic-medium-20261114-121126,heuristic-medium-seeds20to29}` |
| `medium` | `logs_only` | `30` | `30` | `0` | `0` | `-1.000 +/- 0.000` | `0.00` | `30/30` | `10.0` | `reference/logs_only-medium-seeds0to29` |
| `medium` | `random` | `30` | `30` | `0` | `0` | `-0.619 +/- 0.185` | `0.03` | `20/30` | `6.3` | `reference/{random-medium-20261114-121126,random-medium-seeds20to29}` |
| `medium` | `stop_early` | `30` | `30` | `0` | `0` | `-0.933 +/- 0.131` | `0.03` | `30/30` | `1.0` | `reference/{stop_early-medium-20261114-121126,stop_early-medium-seeds20to29}` |
| `medium` | `do_nothing` | `30` | `30` | `0` | `0` | `+0.000 +/- 0.000` | `0.00` | `0/30` | `--` | `reference/{do_nothing-medium-20261114-121126,do_nothing-medium-seeds20to29}` |
| `hard` | `gemini:gemini-4-carbon` | `20` | `20` | `0` | `0` | `+0.573 +/- 0.069` | `1.00` | `20/20` | `11.5` | `inproc-gemini-4-carbon/{hard-00-09,hard-10-19}` |
| `hard` | `grok_tactics` | `30` | `30` | `0` | `0` | `+0.432 +/- 0.085` | `0.93` | `28/30` | `10.4` | `reference/grok_tactics-hard-seeds0to29` |
| `hard` | `opencode:google/gemini-3.5-flash` | `30` | `30` | `0` | `0` | `+0.535 +/- 0.050` | `1.00` | `30/30` | `11.5` | `opencode-gemini-3.5-flash/{hard-00-14,hard-15-29}` |
| `hard` | `opencode:google/gemini-4-carbon` | `1` | `1` | `0` | `0` | `+0.810 +/- 0.000` | `1.00` | `1/1` | `5.0` | `opencode-gemini-4-carbon/hard-04-07` |
| `hard` | `restrict_all` | `30` | `30` | `0` | `0` | `-1.000 +/- 0.000` | `0.00` | `30/30` | `9.0` | `reference/{restrict_all-hard-20261114-121126,restrict_all-hard-seeds20to29}` |
| `hard` | `solver` | `30` | `30` | `0` | `0` | `+0.499 +/- 0.119` | `0.97` | `30/30` | `10.6` | `reference/{solver-hard-20261114-121126,solver-hard-seeds20to29}` |
| `hard` | `heuristic` | `30` | `30` | `0` | `0` | `+0.086 +/- 0.204` | `0.80` | `30/30` | `14.4` | `reference/{heuristic-hard-20261114-121126,heuristic-hard-seeds20to29}` |
| `hard` | `logs_only` | `30` | `30` | `0` | `0` | `-1.000 +/- 0.000` | `0.00` | `30/30` | `10.0` | `reference/logs_only-hard-seeds0to29` |
| `hard` | `random` | `30` | `30` | `0` | `0` | `-0.867 +/- 0.124` | `0.00` | `26/30` | `8.1` | `reference/{random-hard-20261114-121126,random-hard-seeds20to29}` |
| `hard` | `stop_early` | `30` | `30` | `0` | `0` | `-1.000 +/- 0.000` | `0.00` | `30/30` | `1.0` | `reference/{stop_early-hard-20261114-121126,stop_early-hard-seeds20to29}` |
| `hard` | `do_nothing` | `30` | `30` | `0` | `0` | `+0.000 +/- 0.000` | `0.00` | `0/30` | `--` | `reference/{do_nothing-hard-20261114-121126,do_nothing-hard-seeds20to29}` |

- **Progression from `ef5c428a` + `6225cf86` -> `16911dff`:** On `ef5c428a` alone, `hard` reference runs held seeds `0-19` + `30-59` (`n=50` for 6 policies, `n=30` for `grok_tactics` and `logs_only`, missing `20-29`). Merging `6225cf86` into `main` (`726047df` / `16911dff`) filled `20-29` (and `0-29` for `grok_tactics` and `logs_only`), expanding all `8` `hard` reference rows cleanly to contiguous seeds `0-59` (`n=60`, `60` distinct seeds, `invalid=0`, `dropped_duplicates=0`; e.g., `solver` `+0.498 +/- 0.097`, `grok_tactics` `+0.373 +/- 0.077`, `heuristic` `+0.102 +/- 0.129`, `logs_only` `-0.971 +/- 0.057`).

### Duplicate `(agent, tier, seed)` JSONL Audit

All episode JSONL files in `data/runs/committed/` (excluding `superseded/`) and specifically under `data/runs/committed/v1.4/` were scanned directly and cross-checked against `canary.reproduce.load_committed()`:

| Branch | v1.4 JSONL Files | v1.4 Episode Rows | Duplicate `(agent, tier, seed)` in v1.4 | Active Committed JSONL Files | Active Episode Rows | Duplicate `(version, agent, tier, seed)` | `load_committed()` `dropped_duplicates` |
|---|---:|---:|---:|---:|---:|---:|---:|
| `origin/justSilas` (`b4557e00`) | `12` | `240` | `0` | `54` | `829` | `0` | `0` |
| `origin/fr8/afterquery/main` (`ef5c428a`) | `20` | `480` | `0` | `62` | `1069` | `0` | `0` |
| `origin/fr8/afterquery/v14-runs` (`6225cf86`) | `36` | `571` | `0` | `78` | `1160` | `0` | `0` |
| `origin/fr8/afterquery/main` (`16911dff`) | `44` | `811` | `0` | `86` | `1400` | `0` | `0` |

Every row in `v14-runs` (`6225cf86`) and `main` (`ef5c428a` and `16911dff`) has `n == distinct_seeds`, `invalid == 0` across all v1.4 runs, and **0 duplicate `(agent, tier, seed)` tuples**.

---

## 3. Markdown Relative-Link and Repo-Root Sync Check on `origin/justSilas` (`b4557e00`)

### Relative File-Link Scan Results

All `52` Markdown files in scope (`README.md`, `48` files matching `docs/**/*.md`, `harbor/README.md`, `configs/README.md`, and `pitch/GEMINI.md`) on `origin/justSilas` (`b4557e00`) were programmatically scanned for Markdown links `[...](target)` and image links `![...](target)` (with fenced code blocks excluded and `#anchor` suffixes stripped prior to filesystem path resolution):

| Metric | Count | Status |
|---|---:|---|
| Markdown files scanned | `52` | `--` |
| Total `[...](target)` links parsed | `100` | `--` |
| External links (`http://`, `https://`, `mailto:`) | `50` | `--` |
| Intra-document `#anchor` links (`docs/research-afterquery.md`) | `11` | `11 / 11` valid |
| **Relative file/directory links checked** | **`39`** | **`39 / 39` valid (`100%`)** |
| **Broken relative file links** | **`0`** | **PASS** |

Breakdown of the `39` relative file/directory links verified on `origin/justSilas` (`b4557e00`):
- `README.md` (`24` relative links, `24 / 24` valid): `docs/reports/gap.md`, `results/judge_table.md`, `results/gap_chart.png`, `results/fresh_table_v1.4.md`, `docs/reports/grok-agent.md` (`x2`), `canary/baselines.py`, `results/fresh_table_v1.3.md`, `docs/CONTRACT.md` (`x4`), `canary/rules.py`, `configs/README.md`, `harbor/README.md`, `docs/PLAN-95.md`, `docs/EXPLOITS.md` (`x2`), `harbor/check_isolation.sh`, `pitch/GEMINI.md`, `docs/PLAN.md`, `docs/TEAM.md`, `CHALLENGES-AFTERQUERY-GEMINI.md`.
- `docs/reports/grok-agent.md` (`10` relative links, `10 / 10` valid): `grok-agent/medium-900000.jsonl` through `medium-900004.jsonl` and `grok-agent/hard-900000.jsonl` through `hard-900004.jsonl`.
- `harbor/README.md` (`2` relative links, `2 / 2` valid): `../results/harbor/` and `../results/harbor/cheat-probe/`.
- `docs/IDEAS.md` (`1` relative link, `1 / 1` valid): `meetings/2026-11-14-mole-company-simulation.md`.
- `docs/gemini/VIDEO.md` (`1` relative link, `1 / 1` valid): `PLAN.md` (`docs/gemini/PLAN.md`).
- `docs/gemini/validation.md` (`1` relative link, `1 / 1` valid): `validation_context.md` (`docs/gemini/validation_context.md`).
- `configs/README.md` and `pitch/GEMINI.md` (`0` relative file links).

*(Prose path watch item for PLAN-95 C2: `docs/PLAN-95.md` lines 48 and 129 refer in inline code to `EXPLOITS.md` at the repository root, whereas on `b4557e00` the file lives at `docs/EXPLOITS.md` and `README.md` lines 114 and 158 link to `docs/EXPLOITS.md`. Keep links synchronized if root `EXPLOITS.md` is added.)*

### Repo-Root Default Branch Status (`origin/main` vs `origin/justSilas`, PLAN-95 D3)

| Branch | Commit SHA | Merge-Base (`30481da3`) | Commits Ahead of `30481da3` | Tracked Files | Root Layout / Role |
|---|---|---|---:|---:|---|
| `origin/main` | `46fd3be3` | `30481da3` | `1` | `20` | Pre-Canary Sleeper + fleet scaffold (`.gitignore`, `CHALLENGES-AFTERQUERY-GEMINI.md`, `README.md`, `docs/{FLEET,IDEAS,SLEEPER,research-afterquery}.md`, `docs/meetings/*`, `fleet/*`; no `canary/`, `harbor/`, or `Makefile`) |
| `origin/justSilas` | `b4557e00` | `30481da3` | `820` | `1237` | Full Canary v1.4 benchmark, solver, MCP server, Harbor verifier, tests, and committed runs |

- **PLAN-95 Action D3 status (`docs/PLAN-95.md` line 60: rename `main` -> `archive/sleeper-main` and make `justSilas` the default branch):** **OPEN (owner-gated on Silas).** `origin/main` still points to `46fd3be3` (`fr8 fleet plan and scripts`) and no `origin/archive/sleeper-main` ref exists on remote yet (`0` matching `origin/archive/*` refs). Judges opening the repository root prior to D3 cutover would land on the 20-file Sleeper/fleet scaffold rather than Canary (`justSilas`).
