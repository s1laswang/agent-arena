# Pre-Submission Link, Honesty, and Doc-Sync Audit (`origin/justSilas` `dcd8c372` -> `58716742` / tag `afterquery-final`)

Audited target refs (Sun 15 Nov ~05:40 Helsinki):
- `origin/justSilas` Panel Fix A baseline: `dcd8c372` (`SUBMISSION.md: seeds 0-29 are a post-hoc lock (671ed96 came 28 s after 8fd4dec), not pre-registered`).
- Code-freeze annotated tag `afterquery-final` (`e47ddde0` -> `1bc3e281`, Sun 15 Nov 05:08:39 +0200): `Specific tool error details + W1 wording fix (panel fix D)`.
- `gpt-5.5` pre-registration & OpenAI runner update: `cf394894` (`Pre-register the gpt-5.5 run (v1.4 hard, seeds 0-29, OpenCode) before any episode; runner: OpenAI models, spend cap, stop time`; note keyless test regression in `tests/test_gemini_frontier.py::test_opencode_gemini_cmd_env_isolation` raising `MissingKeyError: OPENAI_API_KEY is not set`, fixed in PR #68 `0424db8e`).
- Current `origin/justSilas` tip: `58716742` (`integrity.md: final judge-protocol hunt on afterquery-final (12/12 held, make hunt 0.000, reproduce clean)`), 3 commits ahead of `dcd8c372` and 2 commits ahead of `afterquery-final` (`1bc3e281`).

Executive snapshot:
1. **Link and `#anchor` hygiene across all `180` tracked `.md` files (`3,366` tracked files total on `origin/justSilas` `58716742`):** **`210/211` relative links resolve cleanly** (`209/210` at `dcd8c372`; `77/77` in `docs/SUBMISSION.md`, `31/31` in `README.md`) and **`12/12` `#anchor` targets resolve (`0` broken anchors)**. Only **1 broken relative link** remains on `justSilas`: `docs/EXPLOITS.md:25` (`../results/anticheat/hunt.log`, gitignored by `*.log`).
2. **In-tree vs external branch links in `docs/SUBMISSION.md`:** `docs/SUBMISSION.md:221` still links externally to `blob/justSilas-fr8/docs/reports/fr8.md` (`"04:00 CORRECTION"`) and `docs/SUBMISSION.md:231` cites `VERDA.md` on `s6-verda`, even though `efd99c23` merged `docs/reports/fr8.md` (`"04:45 WS4 small-model tiebreaker readout"`), `fr8/verda/README.md`, and `fr8/analysis/out/ws4_table_v3.md` in-tree on `justSilas`.
3. **Panel Fix A (`92708834`, `dcd8c372`), Panel Fix D (`1bc3e281`, `afterquery-final`), `cf394894`, and `58716742` sync:**
   - Primary docs (`README.md:21`, `docs/reports/gap.md:38`, `docs/SUBMISSION.md:107`) all accurately state that seeds `0-29` (`671ed96`, 28 s after `8fd4dec`) are a **post-hoc lock**, not a pre-registration, and disclose `W4` (`access_constraints` never binds). **One active spoken-script drift remains:** `docs/DEMO.md:71` still tells the presenter to say `"pre-registered seed rule in docs/reports/gap.md"`.
   - After `dcd8c372`: Panel Fix D (`1bc3e281`, tagged `afterquery-final`) fixed `W1` in `canary/env.py` (`harbor/canary-task/instruction.md`) and added `data.detail` to `invalid arguments` errors (disclosed in `README.md:28` and `docs/DIFFICULTY.md:13-15`); `cf394894` pre-registered `gpt-5.5` in `docs/reports/gap.md:31` (and made `opencode_run.child_env_extra("openai/...")` require `OPENAI_API_KEY`, breaking keyless `test_opencode_gemini_cmd_env_isolation` until PR #68 `0424db8e` merges); and `58716742` recorded the completed `afterquery-final` judge-protocol hunt in `docs/reports/integrity.md:157-165` (`12/12` live MCP attacks held, `make hunt` `0.000`, `make reproduce` clean, `make accept` `PASS=20, FAIL=0`, plus `424` Phase-1 Gemini attacks with `0` exploits). Consequently, `docs/SUBMISSION.md:152,245` (`"W1-W4 are disclosed, not fixed"`), `docs/SUBMISSION.md:29,214,271` (`"no tag exists yet"`), `docs/SUBMISSION.md:202,275` (`TODO(Vaishnav)` post-tag hunt), `docs/DIFFICULTY.md:10,120`, and `docs/agents/PANEL-0500.md:7-8` now trail `58716742`.
4. **Submission integrity gate (`scripts/audit_submission.py` on `origin/justSilas`):** **`3 PASS, 1 WARN, 0 FAIL`** (`0` secrets/keys; frozen `v1.4` hash `a8f99c2537c91d72` and `v1.3` hash `8df71cf570bb48bc`; `63` committed run files / `1,031` episodes audited with `8` v1.2 `valid:false` episodes verified excluded; `canary-hard-900000` Harbor static audit PASS; `1,021/1,031` episodes and `51,814` tool results replay step-for-step with `0` differences; `80/80` Harbor trials and `18/18` job summaries consistent).

---

## 1. Link, Anchor, and Stale-Path Scan (`dcd8c372` -> `58716742` / `afterquery-final`)

### 1.1 Programmatic Markdown Link and `#anchor` Summary

All `180` tracked `.md` files on `origin/justSilas` (`dcd8c372` through `58716742` / `1bc3e281`) were parsed outside fenced code blocks for relative `[label](target)` links, `![alt](target)` image links, `[ref]: target` definitions, intra-file `#anchor` slugs, and cross-file `path.md#anchor` slugs.

| Scope on `origin/justSilas` | `.md` Files | Relative Links (`dcd8c372` / `58716742`) | `#anchor` Checks | Broken File Targets | Broken `#anchor` Slugs |
|---|---:|---:|---:|---:|---:|
| [`README.md`](../../README.md) | 1 | 30 / 31 | 1 | 0 | 0 |
| [`docs/SUBMISSION.md`](../SUBMISSION.md) | 1 | 77 / 77 | 0 | 0 | 0 |
| [`docs/agents/PANEL-0500.md`](../agents/PANEL-0500.md) | 1 | 0 / 0 | 0 | 0 | 0 |
| [`docs/FAILURE-RESEARCH.md`](../FAILURE-RESEARCH.md) | 1 | 0 / 0 | 0 | 0 | 0 |
| [`docs/research-biases.md`](../research-biases.md) | 1 | 0 / 0 | 0 | 0 | 0 |
| [`docs/reports/fr8.md`](fr8.md) | 1 | 0 / 0 | 0 | 0 | 0 |
| `docs/**/*.md` (other 76 files, incl. `judge_sim.md`, `number_audit.md`, `gemini/*`) | 76 | 57 / 57 | 11 | **1** (`docs/EXPLOITS.md:25`) | 0 |
| [`harbor/README.md`](../../harbor/README.md) | 1 | 3 / 3 | 0 | 0 | 0 |
| [`configs/README.md`](../../configs/README.md) | 1 | 0 / 0 | 0 | 0 | 0 |
| [`fr8/verda/README.md`](../../fr8/verda/README.md) + `fr8/**/*.md` (`ws4_*.md`, etc.) | 19 | 0 / 0 | 0 | 0 | 0 |
| [`pitch/GEMINI.md`](../../pitch/GEMINI.md) | 1 | 6 / 6 | 0 | 0 | 0 |
| `results/**/*.md` (48 files, incl. `eval_v14/`, `gemini/scale/ladder30/`) | 48 | 37 / 37 | 0 | 0 | 0 |
| Other tracked `.md` (`canary/`, `data/`, `harbor/canary-task/`, `train/`, root notes) | 28 | 0 / 0 | 0 | 0 | 0 |
| **Total on `origin/justSilas`** | **180** | **210 / 211** | **12** (`11` intra + `1` cross-file) | **1** | **0** |

### 1.2 Broken Link, External-Branch Link, and Stale-Path Findings

| # | File and Line | Category | Current Text on `origin/justSilas` | Current In-Tree Truth / Fix |
|---|---|---|---|---|
| L1 | `docs/EXPLOITS.md:25` (also plain backticks at `docs/EXPLOITS.md:114`, `docs/reports/integrity.md:142`) | **Broken relative link** (`missing_target`) | `[results/anticheat/hunt.log](../results/anticheat/hunt.log)` | `*.log` is gitignored (`.gitignore`), so `results/anticheat/hunt.log` is not tracked. Unlink to plain backticks or cite `make hunt` + `tests/test_integrity_fuzz.py`. |
| L2 | `docs/SUBMISSION.md:221` | **Stale external GitHub branch URL** | `[docs/reports/fr8.md](https://github.com/s1laswang/agent-arena/blob/justSilas-fr8/docs/reports/fr8.md) on branch justSilas-fr8, "04:00 CORRECTION"; table fr8/analysis/out/ws4_table_v3s0_n180.md on the same branch` | Merge `efd99c23` landed both `docs/reports/fr8.md` (with the newer `"04:45 WS4 small-model tiebreaker readout"`) and `fr8/analysis/out/ws4_table_v3.md` in-tree on `justSilas`. Replace with relative links `[docs/reports/fr8.md](reports/fr8.md)` and `[fr8/analysis/out/ws4_table_v3.md](../fr8/analysis/out/ws4_table_v3.md)` (matching `SUBMISSION.md:233`). |
| L3 | `docs/SUBMISSION.md:231` | **Unmerged branch file citation** | ``(`VERDA.md` on branch `s6-verda`, section 4)`` | `VERDA.md` is not on `justSilas`, whereas the `v3-8k s1` row (`-0.777 +- 0.118`, `n=90`, accuses `94%`) is now committed in-tree in `fr8/analysis/out/ws4_table_v3.md:26`, `docs/reports/fr8.md:198`, `fr8/verda/README.md:72`, and `data/fr8/verda/a100-ac58/runs/v3-verda-8k-s1/summary.json`. |
| L4 | `docs/SUBMISSION.md:21,29` | **Tag vs moving-branch repo URL** | `Repo: https://github.com/s1laswang/agent-arena/tree/justSilas` + `"no tag exists yet: git ls-remote --tags origin is empty"` | Annotated tag `afterquery-final` (`e47ddde0` -> `1bc3e281`) now exists on `origin`; `docs/agents/PANEL-0500.md:19` specifies linking the AfterQuery submission to tag `afterquery-final` (or latest post-tag doc commit if re-tagged). |
| L5 | `docs/IDEAS.md:22` | Stale renamed path (`8cd20d9e`) | `docs/SLEEPER.md` | Moved to `docs/gemini/SLEEPER-idea.md`. |
| L6 | `docs/reports/gap.md:141` and `docs/reports/MORNING.md:39` | Stale renamed glob (`622ae4f1`) | `` `results/regret_*-v1.2.md` `` / `` `results/regret_*-v1.3.md` `` | Moved under `results/history/regret_*-v1.{2,3}.md` (`gap.md:49` already uses `results/history/`). |
| L7 | `docs/gemini/reports/ladder.md:239` | Stale renamed path | `` `data/gemini/ladder/probe/_probe.json` `` | Moved to `` `results/gemini/ladder_probe.json` ``. |
| L8 | `docs/PLAN-COMPUTE.md:54`, `docs/agents/SESSIONS.md:174`, `docs/gemini/reports/dashboard.md:7` | Stale renamed path | `` `results/leaderboard_v14_hard.json` `` | Tracked at `` `results/gemini/leaderboard_v14_hard.json` ``. |

*(Resolved since the `fad43d07` audit: `docs/research-biases.md` is now merged in-tree via `bbf48449`, closing all 4 prior unmerged references in `PLAN.md`, `NEXT-LEVEL.md`, `SESSIONS.md`, and `CEO.md`; M1, M2, M6, M7, M9, M10, and `harbor/README.md:210` from `docs/reports/number_audit.md` are all fixed on `origin/justSilas`.)*

---

## 2. Panel Fix A / Panel Fix D Honesty Scan & Cross-Doc Number Sync

### 2.1 Repo-Wide Honesty Audit: Post-Hoc Seed Lock (`671ed96`), `W4` Clearance No-Op, and Post-Freeze `W1` / `data.detail` (`1bc3e281`)

All `180` `.md` files on `origin/justSilas` (`58716742`) were scanned for `pre-regist*`, `671ed96`, `8fd4dec`, `post-hoc`, `access_constraints`, `clearance`, and `W1`-`W4`:

1. **Seeds `0-29` (`671ed96` vs `8fd4dec`) post-hoc lock:**
   - **Aligned in all three primary judge-facing docs:** `README.md:21` (`92708834`), `docs/reports/gap.md:38` (`92708834`), and `docs/SUBMISSION.md:107` (`dcd8c372`) all explicitly state that `671ed96` landed **28 s after `8fd4dec`** and is a **post-hoc lock** against reruns and cherry-picking, not a pre-registration (and `README.md:23` discloses the `20 + 10` solver reference directories `solver-hard-20261114-121126/` + `solver-hard-seeds20to29/`).
   - **Residual places on `justSilas` still calling seeds `0-29` "pre-registered":**
     - **`docs/DEMO.md:71` (HIGH - live spoken stage script):** `Seeds and harness were fixed before the reruns (pre-registered seed rule in docs/reports/gap.md).` -> Must be updated before the live pitch to say *"locked right after the primary episodes were committed (post-hoc lock in `docs/reports/gap.md`)"* so presenters do not verbally claim pre-registration on stage.
     - **`docs/PLAN-95.md:139` & `docs/reports/number_audit.md:148` (LOW - historical snapshots):** Written at 22:45 Sat and 02:48 Sun before Panel Fix A (`92708834`).
   - **Genuinely pre-registered protocols (verified committed before any episode ran):** Harbor judge set `900000-900009` (`08f87b6`, `harbor/README.md:25`); Harbor `3 x 10` judge rehearsal (`aa2a56ce`, `results/harbor/rehearsal/README.md:3`); `n=60` extension seeds `30-59` (`f9fb7a4a`, `docs/reports/gap.md:17`); X1 causal hint `--hint gather` (`fd8c1cb0`, `docs/reports/gap.md:19`); and `gpt-5.5` v1.4 hard seeds `0-29` (`cf394894`, `docs/reports/gap.md:31`).
2. **`W4` (`access_constraints` / `clearance` never binds on hard):**
   - **Aligned across primary docs:** Disclosed in `README.md:87`, `docs/DIFFICULTY.md:45,97`, and `docs/SUBMISSION.md:152` (`canary_level = 1` and employee clearances `1-3`, so `access_constraints` is a no-op).
   - **Minor spec note:** `docs/CONTRACT.md:21,39` lists `clearance` and `with access_constraints, recipients must have clearance` without a parenthetical pointer to `DIFFICULTY.md` `W4`.
3. **Panel Fix D (`1bc3e281`, tag `afterquery-final`) `W1` instruction fix + `data.detail` error field:**
   - Commit `1bc3e281` reworded the `W1` careful-mole sentence in medium/hard instructions (`canary/env.py`, `harbor/canary-task/instruction.md`) and added `data.detail` to `invalid arguments` tool replies (`28/3,841` calls = `0.7%` in the 30 headline episodes; replay ignores `detail` on pre-`1bc3e281` episodes; guarded by `tests/test_env.py::test_error_detail_does_not_depend_on_who_the_mole_is` after `tests/test_integrity_props.py` caught an initial example id). `README.md:28`, `docs/DIFFICULTY.md:13-15,19`, `docs/reports/gap.md:31`, and `docs/reports/integrity.md:164` disclose this accurately.
   - **Cross-doc drift introduced after `dcd8c372`:**
     - **`docs/SUBMISSION.md:152` and `docs/SUBMISSION.md:245` (HIGH):** Both still claim `W1-W4` are *"disclosed as W1-W4, not fixed, because the judged text stays identical to what every committed run played"*. Under `afterquery-final` (`1bc3e281`), `W1` **is fixed** in the judged instruction and tool errors include `data.detail` (post-run changes disclosed in `README.md:28` and `docs/DIFFICULTY.md:13-15`), while `W2-W4` remain unedited disclosures.
     - **`docs/DIFFICULTY.md:10,120` & `docs/agents/PANEL-0500.md:7-8` (LOW):** `DIFFICULTY.md:10,120` retains the pre-`1bc3e281` sentence *"none of P1-P12 is applied"* above line 14 (*"W1 is fixed in the instruction"*); `PANEL-0500.md:8` still says *"Declined before the tag"* for Fix D and `:7` says *"no OpenAI or Anthropic API key"* (superseded by `cf394894`).

### 2.2 Line-by-Line Verification of `docs/SUBMISSION.md` (`dcd8c372`) vs Current `origin/justSilas` (`58716742`)

Every headline, gap, skill-ladder, failure-analysis, judge-table, replay (`1,021/1,031`, `51,814` steps), Harbor consistency (`80/80` trials, `18/18` jobs), Gemini swarm (`100` attacks, `4,325` calls), and cheat-corpus (`1,161` runs) figure in `docs/SUBMISSION.md` matches the committed artifacts exactly. The **10 line-level drifts** below are all from commits that landed after `edd4fe6d` / `dcd8c372`:

| `docs/SUBMISSION.md` Line(s) | Current Text in `docs/SUBMISSION.md` (`dcd8c372`) | Exact Drift vs `README.md` / `fr8.md` / `justSilas` (`58716742`) | Verified Replacement / Source |
|---|---|---|---|
| L3 | `Numbers refreshed Sun 15 Nov ~04:40 Helsinki against justSilas at edd4fe6d.` | 11 commits + tag `afterquery-final` (`1bc3e281`) landed after `edd4fe6d` up to `58716742`. | Refresh commit stamp to `58716742` (environment code frozen at tag `afterquery-final` / `1bc3e281`). |
| L21, L29, L214, L271 | `Repo: .../tree/justSilas`; `no tag exists yet: git ls-remote --tags origin is empty`; `TODO(Silas): tag afterquery-final` | Annotated tag `afterquery-final` (`e47ddde0` -> `1bc3e281`) was pushed at 05:08:39 +0200. | Mark code-freeze tag `afterquery-final` (`1bc3e281`) done; per `PANEL-0500.md:19`, point `Repo:` to `afterquery-final` (or final doc tag) before 10:00. |
| L69 | Explains only that `make reproduce` pools OpenCode `gemini-4-carbon` hard to `+0.349 +- 0.190, n=32`. | Judge 5 (`docs/reports/judge_sim.md:51`, fixed in `README.md:37` `ca90d0b2`) noted the replayed `solver` row also pools seeds `0-59`. | Add one clause matching `README.md:37`: the replayed `solver` hard row likewise pools seeds `0-59` (`+0.498 +- 0.097, n=60` in `paired_table_pooled0to59.md:16`), while `HEADLINE` recomputes locked `n=30` (`+0.322` vs `+0.499`). |
| L79-80 | `harbor run -p harbor/dataset -a opencode -m google/gemini-4-carbon --api-key-name GOOGLE_GENERATIVE_AI_API_KEY -n 4` | Bullet L88 warns `-n 5` timed out in 360 s without `--agent-setup-timeout-multiplier`, which is omitted from the copy-paste command block. | Append `--agent-setup-timeout-multiplier 3` (or `4`) directly to the command block so judges copying L79-80 do not hit `AgentSetupTimeoutError`. |
| L111, L239 | `Only Gemini-family models were run on rules v1.4` | Commit `cf394894` (`docs/reports/gap.md:31`) pre-registered an OpenCode `gpt-5.5` v1.4 hard run (seeds `0-29`, cap `$200`, cutoff `08:45`) on tag `afterquery-final`. | True as of `58716742` (`0` `gpt-5.5` v1.4 episodes committed yet), but update L111 and L239 as soon as the `gpt-5.5` run lands before 08:45. |
| L152, L245 | `disclosed as W1-W4, not fixed, because the judged text stays identical to what every committed run played` | Outdated after Panel Fix D (`1bc3e281`, `README.md:28`, `docs/DIFFICULTY.md:13-15`): `W1` is now reworded in medium/hard instructions and `invalid arguments` carries `data.detail` (`28/3,841` headline calls = `0.7%`). | Match `README.md:28` and `DIFFICULTY.md:13-15`: state that `W1` and `data.detail` were fixed on 15 Nov at `afterquery-final` (after the committed Gemini runs, disclosed, replay preserved), while `W2-W4` remain disclosed as written. |
| L202, L275 | `TODO(Vaishnav): a 15-minute hunt that follows the judges' protocol, plus make hunt and the full anti-cheat battery, on the tagged afterquery-final SHA.` | Completed in commit `58716742` (`docs/reports/integrity.md:157-165`, `results/anticheat/judge_hunt.md`). | Drop `TODO` and record the completed `afterquery-final` (`1bc3e281`) hunt from `[docs/reports/integrity.md](reports/integrity.md)` (`05:10-05:25`): `scripts/judge_hunt.py` **`12 of 12 held`** (`52 s`, exit `0`), `make hunt` **`0.000`** best non-solver / **`0` invariant violations** (`4 min 57 s`), full `make reproduce` clean (`HEADLINE` unchanged `65% [24%, 98%]`), `make anticheat-verify` `99` rows / `0` diffs, `make accept` `PASS=20, FAIL=0`, plus `424` Phase-1 Gemini red-team attacks on `469338f6` (`0` exploits). |
| L209 | `uv run pytest for this doc at edd4fe6d: 1055 passed, 7 skipped` | Commit `1bc3e281` added 2 detail/integrity tests (`1,057 passed` at `afterquery-final`, `integrity.md:163`; `1,062` collected), while `cf394894` made `opencode_run.child_env_extra("openai/x")` require `OPENAI_API_KEY`, causing `test_opencode_gemini_cmd_env_isolation` to fail when `OPENAI_API_KEY` is unset. | Update test count note to `1,057 passed` at `afterquery-final` (`1bc3e281`), and merge PR #68 (`0424db8e`, adding `monkeypatch.setenv("OPENAI_API_KEY", "o-test-key")` in `tests/test_gemini_frontier.py`) so keyless `make test` passes cleanly on `justSilas`. |
| L221-229 | Links `blob/justSilas-fr8/docs/reports/fr8.md` (`"04:00 CORRECTION"`), cites `ws4_table_v3s0_n180.md`, lists **`base` `n=16`**, and omits **`v3-8k s2`** and **`v3-4k s1`**. | `efd99c23` & `66a26f5c` (`README.md:56-65`, `docs/reports/fr8.md:196-209`, `fr8/analysis/out/ws4_table_v3.md`) updated the WS4 readout at 04:45: `base` is **`n=36`** (`16 + 20`, `0.000 +- 0.000`, `3%` valid calls), **`v3-8k s2`** (H100 spot, `693` steps) is **`-0.050 +- 0.049` (`n=90`**, accuses `7%`, abstains `93%`), and partial `v3-4k s1` (FR8 V100, `192` steps) is `-0.240 +- 0.171` (`n=25`). | Link in-tree `[docs/reports/fr8.md](reports/fr8.md)` (`"04:45 WS4 small-model tiebreaker readout"`) and `[fr8/analysis/out/ws4_table_v3.md](../fr8/analysis/out/ws4_table_v3.md)`; update `base` `16 -> 36`; add `v3-8k s2` (`-0.050 +- 0.049`, `n=90`) and training-vs-held-out whom-accuracy (`0.19 -> 0.89` on solver states vs `6/38 = 0.16` held-out for `v3-4k s0`, `15/135 = 0.11` pooled across v3 runs, `fr8/analysis/out/ws4_whom_v3.md`). |
| L231, L234 | Cites `VERDA.md` on `s6-verda` for `v3-8k s1`; says `"Other v3-8k seeds and a DAgger round were still pending at 04:00."` | `v3-8k s1` (`-0.777 +- 0.118`, `n=90`) and `v3-8k s2` (`-0.050 +- 0.049`, `n=90`) are both committed in-tree (`ws4_table_v3.md:26,30`, `fr8/verda/README.md:72,80`); only `v3-8k s0`, `v3-8k s3`, and `X2 DAgger` remain pending at 04:45 (`fr8.md:208`). | Cite in-tree `[fr8/analysis/out/ws4_table_v3.md](../fr8/analysis/out/ws4_table_v3.md)` and `[fr8/verda/README.md](../fr8/verda/README.md)`, and narrow the pending note to `v3-8k s0/s3` and `X2 DAgger` (under shared held-out world secret `1ca0c2a64d`). |

### 2.3 Residual Numeric / Text Drifts in Companion AfterQuery Docs on `origin/justSilas` (`58716742`)

| File and Line | Current Text on `58716742` | Current Committed Truth |
|---|---|---|
| `docs/DEMO.md:71` | `"pre-registered seed rule in docs/reports/gap.md"` | Post-hoc lock (`671ed96` 28 s after `8fd4dec`, Panel Fix A `92708834`). |
| `docs/DEMO.md:122-124` | `<PLACEHOLDER until FR8 reports ~07:00 Sun...>` + cites only J4 (`n=2` base, `n=17` LoRA) | Merged 04:45 WS4 readout in `README.md:56-68` and `docs/reports/fr8.md:196-209` (`base n=36` `0.000`, `v2 n=172` `-0.457 +- 0.086`, `v3-4k s0 n=180` `-0.147 +- 0.063`, `v3-8k s2 n=90` `-0.050 +- 0.049`; bar not met). Flagged in `SUBMISSION.md:215`. |
| `docs/DEMO.md:56,145-146` | Warns `judge_table.md` (`c4d0004`) still says `"v1.4 frontier gap: not established"` and has non-blank `/ solver`, plus plus-probe sanity flake | Both fixed (`results/judge_table.md` `893b837616b9` blanks `/ solver` and points to `paired_table_gemini.md`; plus-probe abstention rule fixed in `EXPLOITS.md` #51). |
| `docs/EXPLOITS.md:28,31,32,40` | J9 `31` `solve.sh` / `6` OpenCode; J12 `989 of 999` (`49,549` steps); J13 `1,789` calls in col 3 vs `4,325` in col 2; Risk #3 `Three retired builds` | Live `harbor_consistency()` & `results/anticheat/exploits.md:176-180`: `61` `isolation.txt` + `19` OpenCode = `80` trials, `8` retired key dirs (`57` HMAC-verified); **`1,021 of 1,031` episodes (`51,814` steps, `0` differ)**; `4,325` swarm tool calls (`19` MCP); `149` cheat-probe attempts = `60 + 13 + 7 (6 fakes + 1 loop) + 60 + 9` (`EXPLOITS.md:180`). |
| `docs/HISTORY.md:37-40` | Quotes `results/judge_table.md` as `+0.679 / +0.547 / +0.808` without snapshot label | Current `results/judge_table.md` (`893b837616b9`) is `+0.634 +- 0.086 / +0.553 +- 0.093 / +0.785 +- 0.026`. |

---

## 3. Open Pre-10:00 Items Matrix (`58716742`) & Paste-Ready Verified Snippets

### 3.1 `docs/SUBMISSION.md` Open TODOs Status Matrix at `58716742`

| # | `SUBMISSION.md` Line(s) | Owner | Item | Status at `58716742` | Verified State & Remaining Action Before 10:00 |
|---:|---|---|---|---|---|
| 1 | L29, L214, L271 | Silas | Tag `afterquery-final` | **DONE (code freeze)** | Annotated tag `afterquery-final` (`e47ddde0` -> `1bc3e281`) pushed at 05:08:39 +0200. Update L21/L29/L214/L271 (and re-tag or link final doc commit if desired). |
| 2 | L119, L241, L271 | Silas / FR8 | Harbor `3 x 10` real judge rehearsal (`oracle`, `3x opencode`, `do_nothing`, `stop_early`) | **PR #72 SHIPPED (`rehearsal-fr8`) / OPTIONAL TAG RERUN** | PR #72 (`cb35f3a1`, `results/harbor/rehearsal-fr8/TABLE.md` + `docs/reports/harbor_rehearsal_fr8.md`) packages a `3 x 10` Linux Docker Harbor `0.26.0` rehearsal on `8cd20d9e` (`oracle` `+0.601` 10/10; `do_nothing`/`stop_early`/`cheat_probe` `+0.000` 10/10; `3x opencode` `10/10` valid trials caught the mole, run means `+0.647`, `+0.543`, `+0.527`, mean of means `+0.572`, SD `0.065`, range `0.119`, `20/30` unfinished `ApiRateLimitError` disclosed per `PANEL-0500.md:6`). `results/harbor/rehearsal/` stays reserved if a post-tag macOS colima run finishes. |
| 3 | L122, L158, L272 | Silas | X1 causal hint test (`--hint gather`, OpenCode hard seeds `0-29`, cutoff `05:40`) | **RUNNING / READOUT** | Pre-registered in `docs/reports/gap.md:19` (`fd8c1cb0`, Verda `18acfa5d:/root/x1`). Commit completed seeds (`n` stated) and paired diff vs primary `n=30` either way. |
| 4 | (`gap.md:31`, L111, L239) | Silas | Pre-registered `gpt-5.5` second frontier family (OpenCode 1.19.5, hard seeds `0-29`, cap `$200`, cutoff `08:45`) | **RUNNING (PR #68 CI FIX READY)** | Pre-registered in `docs/reports/gap.md:31` on `afterquery-final`. Merge PR #68 (`0424db8e`) to restore keyless `test_opencode_gemini_cmd_env_isolation`; replay-verify completed `gpt-5.5` seeds, append paired row, and update `SUBMISSION.md:111,239`. |
| 5 | L234, L276 | Momin / FR8 | Tiebreak addendum: X2 DAgger round 1 + remaining `v3-8k s0/s3` (shared secret `1ca0c2a64d`) | **PARTIAL / RUNNING** | `v3-8k s2` (`-0.050 +- 0.049, n=90`) and `base n=36` already committed (`efd99c23`); X2 DAgger (`68bbe201` + `e9ea8b2e`) + `v3-8k s0/s3` running until ~07:15 (`fr8/verda/README.md:68-76`). Per `PANEL-0500.md:9`, add DAgger as addendum if committed (and sync Section 7 to `04:45` readout now). |
| 6 | L213, L273 | Silas | Post-freeze fresh-clone verification log (`results/fresh_clone/`) | **PARTIAL** | `09e7363` clean macOS log committed (`results/fresh_clone/README.md`). Run the `PANEL-0500.md:13` one-liner on `afterquery-final` (~07:45) and commit log if time permits. |
| 7 | L202, L275 | Vaishnav / Silas | 15-min judge-protocol hunt + `make hunt` + battery check on `afterquery-final` | **DONE (in `58716742`)** | Completed on `afterquery-final` (`1bc3e281`) and recorded in `docs/reports/integrity.md:157-165` (`58716742`): `scripts/judge_hunt.py` `12/12 held` (`52 s`), `make hunt` `0.000` / `0` invariant violations (`4 min 57 s`), full `make reproduce` exit `0`, `anticheat-verify` `99` rows / `0` diffs, `make test` `1,057 passed`, `make accept` `PASS=20, FAIL=0`. Update `SUBMISSION.md:202,275` to drop the `TODO`. |
| 8 | L215 | Silas | Sync `docs/DEMO.md` tiebreak slot (and L71 post-hoc lock wording) | **OPEN** | Update `docs/DEMO.md:71,122-124` to match Panel Fix A and Section 7 (`bar not met`). |
| 9 | L23, L27-28, L210, L274, L277-278 | Silas / Ivar / All | Platform form fields, public video URL, hosted Pages/Vercel game URL, optional human playtests | **OPEN (human)** | Final pre-09:30 human submission checklist (`docs/agents/PANEL-0500.md:16-22`). |

### 3.2 Paste-Ready Verified Snippets for `docs/SUBMISSION.md`

#### Snippet A: Section 4 (`L152`) & Section 8 (`L245`) Post-`1bc3e281` Instruction & Tool-Error Disclosure

```markdown
- **Instruction audit** ([docs/DIFFICULTY.md](DIFFICULTY.md), PLAN-95 B4): by hand, mechanically and with one gemini-4-carbon pass over the exact text the agent receives. Verdict: no withheld rule, feasible in-game timing, 39/39 tool smoke calls ok ([results/audit/instruction_checks.md](../results/audit/instruction_checks.md)). Harbor's 3,600 s wall-clock agent timeout was raised to 10,800 s (`512836b9`). On 15 Nov (at tag `afterquery-final`, `1bc3e281`, after the committed Gemini runs; disclosed in the README and [docs/DIFFICULTY.md](DIFFICULTY.md)), the contradictory careful-mole sentence (W1) was clarified in the medium and hard instructions and `invalid arguments` tool replies gained a `data.detail` field naming what was wrong (the error string is unchanged, so all 1,021 replayable episodes still replay; 28 of 3,841 calls in the 30 headline hard episodes, 0.7%, hit that error). W2, W3 and the non-binding `access_constraints` parameter on hard (W4) remain disclosed in [docs/DIFFICULTY.md](DIFFICULTY.md).
```

```markdown
- **Post-run wording and error-detail update, plus W2-W4 disclosures** ([docs/DIFFICULTY.md](DIFFICULTY.md)): at `afterquery-final` (`1bc3e281`), W1 was reworded in medium/hard instructions and `invalid arguments` gained `data.detail` (after the committed Gemini runs; 0.7% of headline calls hit that error, and step-level replay is preserved). W2-W4 stay as written and are disclosed in [docs/DIFFICULTY.md](DIFFICULTY.md).
```

#### Snippet B: Section 7 (`L217-235`) Tiebreak Synced to In-Tree `04:45` WS4 Readout (`README.md` + `docs/reports/fr8.md`)

```markdown
## 7. Tiebreak: does a small model improve after training on Canary?

**Short answer: no held-out gain over the base model.** Reward training fixed the supervised model's reckless accusations and taught valid protocol play, but no trained checkpoint cleared 0 on held-out episodes (where the untrained base scores 0 by failing to make valid calls and never accusing). We do not claim a tiebreak gain.

Held-out Canary episodes across easy/medium/hard, the model playing alone, Qwen2.5-1.5B-Instruct with LoRA ([docs/reports/fr8.md](reports/fr8.md), "04:45 WS4 small-model tiebreaker readout"; full table in [fr8/analysis/out/ws4_table_v3.md](../fr8/analysis/out/ws4_table_v3.md)):

| model | n held-out episodes | score +- 95% CI | behaviour |
|---|---:|---|---|
| base (untrained, 4k) | 36 | 0.000 +- 0.000 | 3% valid tool calls, never accuses (100% abstain) |
| v1: SFT on solver episodes (J4, 4k) | 12 | -0.250 +- 0.256 | 100% valid calls, accuses 25%, 0% correct |
| v2: SFT, dense 4k windows | 172 | -0.457 +- 0.086 | 92% valid calls, accuses 55%, 5% correct |
| v3-4k s0: GRPO on Canary reward (Verda H100, 609 steps) | 180 | -0.147 +- 0.063 | 100% valid calls, accuses 21%, 79% abstain |
| v3-4k s1: GRPO replicate (FR8 V100, 192 steps, partial) | 25 | -0.240 +- 0.171 | 97% valid calls, accuses 24%, 76% abstain |
| v3-8k s1: GRPO, 8k context (Verda A100 spot, 371 steps) | 90 | -0.777 +- 0.118 | 92% valid calls, accuses 94%, 9% correct |
| v3-8k s2: GRPO, 8k context (Verda H100 spot, 693 steps) | 90 | -0.050 +- 0.049 | 96% valid calls, accuses 7%, 93% abstain |

- **What improved:** v3-4k s0 beats v2 by +0.310 +- 0.107 (two-sample) and v3-8k s2 beats v2 by +0.408 +- 0.099, by curbing negative-EV guesses while keeping 96-100% valid tool calls. On training decision states (the solver's last 6 steps, where evidence is already in view), v3-4k s0's forced-accusation accuracy rose from 0.19 to 0.89.
- **Why the bar (> 0 with 95% CI excluding 0) was not met:** in its own held-out games, v3-4k s0 is right on only 6/38 accusations (0.16; pooled across all v3 runs, 15/135 = 0.11, [fr8/analysis/out/ws4_whom_v3.md](../fr8/analysis/out/ws4_whom_v3.md)). Identifying the mole from gathered evidence is learnable; gathering the evidence over a multi-day horizon is the hard decision.
- **Two-sample CIs, disclosed:** these evals ran without a shared `CANARY_WORLD_SECRET`, so each held-out eval process drew distinct worlds and all deltas are two-sample ([docs/reports/fr8.md](reports/fr8.md), "04:00 CORRECTION"; Verda ledger in [fr8/verda/README.md](../fr8/verda/README.md)).
- **Still running (shared held-out world secret `1ca0c2a64d`):** on-policy DAgger round 1 (X2) and `v3-8k` seeds `s0`/`s3` ([fr8/verda/README.md](../fr8/verda/README.md)). TODO(Momin): append as an addendum if committed before submission.
```

#### Snippet C: Section 5 (`L202`) & Open TODOs (`L275`) Post-`58716742` Final Judge-Protocol Hunt

```markdown
- **Post-freeze judge-protocol hunt on `afterquery-final` (`1bc3e281`, [docs/reports/integrity.md](reports/integrity.md), [results/anticheat/judge_hunt.md](../results/anticheat/judge_hunt.md)):** `python scripts/judge_hunt.py` held `12 of 12` live MCP server attacks (`52 s`, exit `0`); `make hunt` scored `0.000` best non-solver with `0` invariant violations across every mode and tier (`4 min 57 s`); full `make reproduce` exited `0` (`HEADLINE` unchanged at `65% [24%, 98%]`); `make anticheat-verify` reran `99` rows with `0` differences; `make accept` passed `20/20` (`FAIL=0`); and Phase-1 Gemini red-team (`424` ledger-verified attacks on `469338f6`) found `0` verified exploits.
```

#### Snippet D: Post-Merge Sync Snippets Once Fleet PRs #47, #69, and #72 Land on `justSilas`

```markdown
- **FR8 Linux Docker `3 x 10` Harbor rehearsal** ([results/harbor/rehearsal-fr8/TABLE.md](../results/harbor/rehearsal-fr8/TABLE.md), [docs/reports/harbor_rehearsal_fr8.md](reports/harbor_rehearsal_fr8.md), built at `8cd20d9e`, pre-`1bc3e281` judged text): across 7 jobs (`70` trials) on one shared 10-task hard judge build (`900000-900009`), `oracle` scored `+0.601` (`10/10` correct), `do_nothing` `+0.000` (`10/10`), `stop_early` `+0.000` (`10/10`), and `cheat_probe` `+0.000` (`10/10`, `149` attempts/trial, `0` holes). Across `3 x opencode` (`google/gemini-4-carbon`, `-n 2`), `10/10` valid episodes caught the true mole with valid-trial run means `+0.647`, `+0.543`, `+0.527` (mean of means `+0.572`, SD `0.065`, range `0.119`; `20/30` trials hit shared-bucket `ApiRateLimitError` before horizon, disclosed with infra-as-`0` means `+0.194`, `+0.163`, `+0.211`). With `rehearsal-fr8` merged, live `harbor_consistency()` verifies **150 of 150 committed trials and 25 of 25 job summaries** (`48` with checked agent trajectories, `130` graded with `signature=ok`, `57` HMAC-verified against retired `ledger_key`s).
- **Non-primary selected fleet `30-59` replication & organizational-bias grounding** ([docs/reports/v14_seeds30to59_replication.md](reports/v14_seeds30to59_replication.md), [docs/research-organizational-biases.md](research-organizational-biases.md)): `7` completed OpenCode `gemini-4-carbon` hard fleet episodes (`seeds 30, 34, 42, 45, 48, 57, 58`; `23/30` incomplete at cutoff, kept strictly separate from locked primary `0-29` and partial `n=2` G1) replay-verify cleanly (`+0.639 +- 0.079` vs same-seed solver `+0.319`, luck-adjusted `109% [70%, 155%]`; exploratory `n=37` pool `78% [60%, 97%]` luck-adjusted; `719/719` `v1.4` episodes verified by `scripts/v14_replication_report.py --check`).
```

---

## 4. Shipped Fleet PR Bundle (`99bcbedd`) Cross-Branch & Post-Merge Sync Audit

All 6 open fleet PR branches into `origin/justSilas` (`58716742`) were verified both standalone (`scripts/verify_pr_branch.py --base origin/justSilas`: **`11/11` gates PASS on every branch**, **`21/21` branch pairs merge cleanly** via `git merge-tree --write-tree`) and on the combined integration tree (`origin/fr8/afterquery/prs` at `99bcbedd`):

| PR / Branch | Tip SHA | Files Changed vs `58716742` | Standalone Gates | Key Verified Numbers & Post-Merge Sync Notes |
|---|---|---:|---|---|
| PR #47 `fr8/afterquery/v14-replication` | `f8d56902` | `40` | `11/11 PASS` (`277` eps replayed) | `scripts/v14_replication_report.py --check` PASS (`719/719` `v1.4` episodes across `36` shards, `0` mismatches); `6/6` links in `docs/reports/v14_seeds30to59_replication.md` clean. Shards live under `results/selected_fleet_replication/v1.4` (outside `data/runs/committed/`), leaving `make reproduce` `HEADLINE` (`65% [24%, 98%]` raw, `72% [52%, 91%]` luck-adj) unchanged. |
| PR #50 `fr8/afterquery/doc-sync` | `2f1162c5` | `1` | `11/11 PASS` (`10` links, `0` broken) | This audit report (`docs/reports/submission_and_doc_sync_audit.md`); all relative links outside fenced snippets target files already present on `origin/justSilas` (`58716742`). |
| PR #52 `fr8/afterquery/replay` | `95d8abd8` | `10` | `11/11 PASS` (`4` links, `0` broken) | Adds `seeds` filter to `load_committed_episodes` and syncs `docs/reports/fooled_moments_v1.4.md` (`4/4` relative links clean). |
| PR #68 `fr8/afterquery/fix-openai-env-test` | `0424db8e` | `1` | `11/11 PASS` | Sets `OPENAI_API_KEY` in `tests/test_gemini_frontier.py::test_opencode_gemini_cmd_env_isolation`, fixing the keyless test regression introduced in `cf394894`. |
| PR #69 `fr8/afterquery/research-biases` | `ad92edde` | `1` | `11/11 PASS` (`35` links, `0` broken) | Adds `docs/research-organizational-biases.md` (`1,000` lines, `35/35` relative links and `12/12` `#anchor` targets clean, synced to `58716742` / Panel Fix A) without colliding with `docs/research-biases.md` (`bbf48449`). |
| PR #72 `fr8/afterquery/rehearsal-fr8` | `cb35f3a1` | `893` | `11/11 PASS` (`2` links, `0` broken) | Bundles `results/harbor/rehearsal-fr8/` (`8ba5f99c`) + `docs/reports/harbor_rehearsal_fr8.md` (`e273c5fb`, resolving their mutual path references). `scripts/rehearsal_table.py` reproduces `TABLE.md` byte-for-byte. **Two post-merge sync items:** (1) live `harbor_consistency()` rises from `80/80` trials & `18/18` jobs to **`150/150` trials & `25/25` job summaries** (`175` rows, `0` problems: `48` trajectory-checked, `130` `signature=ok`, `57` retired-key HMAC-verified), so update `docs/SUBMISSION.md:174` (and `results/anticheat/exploits.md` if regenerated); (2) built at `8cd20d9e` (pre-`1bc3e281`), so disclose alongside Panel Fix D that containers played the pre-`1bc3e281` `W1` wording and pre-`data.detail` error payloads (identical to the 30 locked primary Gemini episodes). |

Combined integration tree (`99bcbedd` + this audit update) live check summary:
- `scripts/audit_submission.py`: **`3 PASS, 1 WARN, 0 FAIL`** across **`4,313` tracked files** (`0` secrets or answer keys; `v1.4` `a8f99c2537c91d72`; `63` committed run files / `1,031` episodes; `canary-hard-900000` Harbor static audit PASS).
- `canary.redteam.anticheat`: **`1,021/1,031` committed episodes (`51,814` tool results, `0` mismatches)** and **`150/150` Harbor trials + `25/25` job summaries (`0` problems)**.
- Markdown & test hygiene: **`187` tracked `.md` files**, **`267/268` relative links clean** (`0` broken links added by any fleet PR; only `docs/EXPLOITS.md:25` `hunt.log` on untouched `justSilas`), **`24/24` `#anchor` checks clean**, and **`1,149` pytest tests collected** (`80/80` frontier, submission-audit, PR-gate, and replication tests passing keyless).
