# Canary Number Provenance Index

Master judge-facing ledger mapping every headline and rubric number across [README.md](../README.md), [JUDGE_QUICKSTART.md](../JUDGE_QUICKSTART.md), [docs/SUBMISSION.md](SUBMISSION.md), [docs/JUDGE-WALKTHROUGH.md](JUDGE-WALKTHROUGH.md), [docs/REPRODUCIBILITY.md](REPRODUCIBILITY.md), [docs/PEER-REVIEW-QA.md](PEER-REVIEW-QA.md), [docs/reports/gap.md](reports/gap.md), [docs/reports/failure_analysis_v1.4.md](reports/failure_analysis_v1.4.md), [docs/EXPLOITS.md](EXPLOITS.md), [docs/reports/integrity.md](reports/integrity.md), and [docs/gemini/SUBMISSION.md](gemini/SUBMISSION.md) to its exact committed JSON/JSONL/Markdown artifact, producing git commit SHA, and keyless recompute or verification command.

Sections: [1. Frontier Gap](#1-frontier-gap-rubric-30-pts) | [2. Causal Failure Analysis](#2-causal-failure-analysis--meaningful-difficulty-rubric-30-pts) | [3. Reward Integrity](#3-reward-integrity--afterquery-final-hunt-rubric-25-pts) | [4. Harbor Oracle](#4-harbor-oracle--rehearsal-dry) | [5. Craft Timings](#5-craft-timings--reproducibility-rubric-15-pts) | [6. WS4 Tiebreak](#6-ws4-tiebreak-small-model-held-out-progression) | [7. Gemini Lab](#7-gemini-lab-side-track-companion-artifacts) | [8. Audit Closures](#8-closure-ledger-for-docsreportsnumber_auditmd-m1-m10--post-audit-fixes)

Verify this entire ledger mechanically in under 2 seconds with zero API keys (supports both git clones and gitless ZIP archives):

```bash
uv run python scripts/verify_artifact_numbers.py
```

---

## 1. Frontier Gap (Rubric: 30 pts)

Primary seed lock: dev seeds `0-29` (`n=30` per tier) were committed in `8fd4dec` (`035105e9e1` / `498bccdea8` run `git_sha`) and locked 28 seconds later in `671ed96` (disclosed as a post-hoc lock against reruns in `92708834` and `dcd8c372`). Pre-registered extension rules are recorded in `f9fb7a4a` (Gemini hard seeds `30-59`) and `cf394894` (`gpt-5.5` OpenCode hard seeds `0-29`).

| Metric | Verified Value | Source Artifact | Producing Commit | Recompute Command |
|---|---|---|---|---|
| OpenCode `gemini-4-carbon` hard primary (mean +/- CI, solver mean, raw %, luck-adj %) | +0.322 +/- 0.199 vs +0.499 +/- 0.119; 65% [24%, 98%]; 72% [52%, 91%]; n=30 | `data/runs/committed/v1.4/paired_table_gemini.json`, `data/runs/committed/v1.4/paired_table_gemini.md` | `8fd4dec`, `693a3b2b`, `bddc0ff9` | `uv run python scripts/paired_gemini.py --version v1.4 --seeds 0-29` |
| OpenCode `gemini-4-carbon` hard un-retried alternative (empty replies scored 0) | +0.279 +/- 0.180; 56% [19%, 87%]; 55% [34%, 77%]; n=30 | `data/runs/committed/v1.4/paired_table_gemini.json`, `data/runs/committed/v1.4/paired_table_gemini.md` | `8fd4dec`, `bddc0ff9` | `uv run python scripts/paired_gemini.py --version v1.4 --seeds 0-29` |
| OpenCode `gemini-4-carbon` medium primary (mean +/- CI, raw %, luck-adj %) | +0.713 +/- 0.042 vs +0.645 +/- 0.087; 111% [99%, 127%]; 101% [85%, 119%]; n=30 | `data/runs/committed/v1.4/paired_table_gemini.json`, `data/runs/committed/v1.4/paired_table_gemini.md` | `8fd4dec`, `693a3b2b`, `bddc0ff9` | `uv run python scripts/paired_gemini.py --version v1.4 --seeds 0-29` |
| In-process `gemini-4-carbon` hard (full history, thought-signature replay) | +0.473 +/- 0.118 vs +0.499; 95% [62%, 140%]; 84% [65%, 106%]; n=30 | `data/runs/committed/v1.4/paired_table_gemini.json`, `data/runs/committed/v1.4/inproc-gemini-4-carbon/hard/episodes.jsonl` | `8fd4dec`, `498bccdea8` | `uv run python scripts/paired_gemini.py --version v1.4 --seeds 0-29` |
| In-process `gemini-4-carbon` medium (full history, thought-signature replay) | +0.530 +/- 0.138 vs +0.645; 82% [56%, 108%]; 74% [52%, 99%]; n=30 | `data/runs/committed/v1.4/paired_table_gemini.json`, `data/runs/committed/v1.4/inproc-gemini-4-carbon/medium/episodes.jsonl` | `8fd4dec`, `035105e9e1` | `uv run python scripts/paired_gemini.py --version v1.4 --seeds 0-29` |
| OpenCode `gemini-3.5-flash` hard (API-served `gemini-3.6-flash`, second family) | +0.373 +/- 0.177 vs +0.499; 75% [36%, 123%]; 22% [-23%, 63%]; n=30 | `data/runs/committed/v1.4/paired_table_gemini.json`, `data/runs/committed/v1.4/opencode-gemini-3.5-flash/hard/episodes.jsonl` | `bfbb48c7`, `035105e9e1` | `uv run python scripts/paired_gemini.py --version v1.4 --seeds 0-29` |
| OpenCode `gemini-4-carbon` hard pooled primary + G1 extension (seeds 0-29 + 34, 37) | +0.349 +/- 0.190 vs +0.514; 68% [32%, 100%]; 75% [56%, 93%]; n=32 | `data/runs/committed/v1.4/opencode-gemini-4-carbon-ext/paired_table_pooled0to59.json`, `data/runs/committed/v1.4/opencode-gemini-4-carbon-ext/paired_table_pooled0to59.md` | `f9fb7a4a`, `364fe657` | `uv run python scripts/paired_gemini.py --version v1.4 --seeds 0-59` |
| Reference solver hard pooled seeds 0-59 (`make reproduce` reported row) | +0.498 +/- 0.097; n=60 | `data/runs/committed/v1.4/opencode-gemini-4-carbon-ext/paired_table_pooled0to59.json`, `data/runs/committed/v1.4/reference/solver-hard-seeds30to59/episodes.jsonl` | `3b07a8b3`, `693a3b2b`, `364fe657`, `ca90d0b2` | `uv run python scripts/paired_gemini.py --version v1.4 --seeds 0-59` |

---

## 2. Causal Failure Analysis & Meaningful Difficulty (Rubric: 30 pts)

Every number in [docs/reports/failure_analysis_v1.4.md](reports/failure_analysis_v1.4.md) is computed deterministically from the committed v1.4 transcripts and re-verified by replay in `scripts/failure_analysis_v14.py`.

| Metric | Verified Value | Source Artifact | Producing Commit | Recompute Command |
|---|---|---|---|---|
| Total paired V gap across 30 hard seeds (raw = luck-adjusted skill + bad luck) | +5.30 = +4.19 + +1.11 (0.177 = 0.140 + 0.037 per episode) | `results/failure_analysis_v1.4.json`, `docs/reports/failure_analysis_v1.4.md` | `8ba63218`, `88544b74` | `uv run python scripts/failure_analysis_v14.py --check` |
| Mistake 1: accusing before leaks isolate one suspect (9 of 29 accusations; 3 EV < 0) | +3.39 (+0.113 per episode); 9 of 29 vs 3 of 30 | `results/failure_analysis_v1.4.json`, `docs/reports/failure_analysis_v1.4.md` | `8ba63218` | `uv run python scripts/failure_analysis_v14.py --check` |
| Mistake 2-5 components (abstention, late-leak drain, restriction cost, saved canary cost) | +0.62, +1.75, +0.12, -1.69 | `results/failure_analysis_v1.4.json`, `docs/reports/failure_analysis_v1.4.md` | `8ba63218` | `uv run python scripts/failure_analysis_v14.py --check` |
| Exploration & timing profile (canaries planted, interviews/ep, accuse day, wrong count) | 8.5 vs 14.1; 68 vs 0; 13.2 vs 10.6; 4 (3.4) vs 1 (1.0) | `results/failure_analysis_v1.4.json`, `docs/reports/failure_analysis_v1.4.md` | `8ba63218` | `uv run python scripts/failure_analysis_v14.py --check` |
| Skill ladder v1.4 ablations (removing EV stopping rule / leak-delay model on hard, n=400) | -0.371 +/- 0.032; -0.151 +/- 0.057; -0.251 +/- 0.037; n=400 | `results/skill_ladder_v1.4.md`, `results/skill_ladder_v1.4.csv` | `e2f74bb5` | `uv run python scripts/skill_ladder.py --n 400 --tiers easy,medium,hard` |
| Stronger `solver_v2` headroom check on fresh hard seeds (n=400) | +0.012 +/- 0.029; n=400 | `docs/reports/reference_optimality.md` | `83d5f448` | `uv run python scripts/reference_optimality.py --tier hard --seeds 400` |
| Instruction audit tool smoke checks (Panel Fix D `data.detail` tagged at `1bc3e281`) | 39/39; 28 of 3,841 | `docs/DIFFICULTY.md`, `results/audit/instruction_checks.md`, `README.md` | `c2c72113`, `1bc3e281` | `uv run python scripts/instruction_audit.py --checks` |

---

## 3. Reward Integrity & `afterquery-final` Hunt (Rubric: 25 pts)

Tag `afterquery-final` points to `1bc3e281` (`1bc3e281dbfaa494a11e783d0c98369b41b2f675`). The final judge-protocol hunt on the tagged code is recorded in `58716742` ([docs/reports/integrity.md](reports/integrity.md)).

| Metric | Verified Value | Source Artifact | Producing Commit | Recompute Command |
|---|---|---|---|---|
| Anti-cheat battery probe rows across easy/medium/hard (40 judge seeds/tier, all blocked) | 99 (40 seeds; 14 + 1 + 4 + 13 + 1 = 33 per tier; 39 sanity) | `results/anticheat/exploits.json`, `results/anticheat/exploits.md`, `docs/EXPLOITS.md` | `bd535a45` | `make anticheat-verify` |
| Committed episode step-by-step replay verification | 1051 of 1061; 53889; 0 | `results/anticheat/exploits.json`, `results/anticheat/exploits.md` | `bd535a45`, `ca0a0dc0` | `uv run python -m canary.redteam.anticheat --verify results/anticheat/exploits.json` |
| Committed Harbor trial & job consistency + HMAC signature checks | 80 of 80; 18 of 18; 60; 20; 57 | `results/anticheat/exploits.json`, `results/anticheat/exploits.md` | `bd535a45` | `uv run python -m canary.redteam.anticheat --verify results/anticheat/exploits.json` |
| Judge-table baselines on 40 judge seeds (`do_nothing`, `stop_early`, hard `solver`, `guess_day1`) | +0.000 +/- 0.000; +0.513 +/- 0.120; -0.950 +/- 0.098; n=40 | `results/judge_table.md` | `58716742`, `bddc0ff9` | `make reproduce` |
| `guess_day1` expected 40-task mean across 300 hard judge-seed builds | -0.953 (sd 0.045; [-1.00, -0.85]; 300 builds) | `results/solver_range/guess_day1_hard_judge40.json`, `results/solver_range/guess_day1_hard_judge40.md` | `a52dde2d` | `uv run python scripts/solver_spread.py 300 --tier hard --seeds 40 --agent guess_day1` |
| `afterquery-final` wire-level judge-protocol MCP hunt (`J1`-`J12`) | 12 of 12; 52 | `results/anticheat/judge_hunt.md`, `docs/reports/integrity.md` | `1bc3e281`, `58716742`, `afterquery-final` | `uv run python scripts/judge_hunt.py --out results/latest/judge_hunt.md` |
| `afterquery-final` fuzz (`make hunt`) & test/accept sweep | 0.000; 0; 99; 1,057; 20 | `docs/reports/integrity.md` | `1bc3e281`, `58716742`, `afterquery-final` | `make hunt` |
| Harbor ledger tamper negative control (`c1-tamper`, forged `score: 1.0` graded 0) | 0.0 | `results/harbor_negative/c1-tamper/result.json` | `ac2d5cbe` | `uv run python scripts/verify_submission_surfaces.py` |
| Rejected cheat-call injection corpus across easy/medium/hard | 129; 1,161; 0 | `results/anticheat/corpus_eval.txt`, `docs/reports/integrity.md` | `46e70929` | `uv run python -m canary.redteam.corpus --momin --tiers easy,medium,hard --seeds 0-2` |

---

## 4. Harbor Oracle & Rehearsal-Dry

| Metric | Verified Value | Source Artifact | Producing Commit | Recompute Command |
|---|---|---|---|---|
| Harbor 10-task hard oracle distribution across 200 fresh-secret builds | +0.569 (sd 0.094; p5 +0.393, p50 +0.600, p95 +0.678; 0.0%; 200) | `results/oracle_range_v1.4.json`, `results/oracle_range_v1.4.md` | `ba1291f8` | `uv run python scripts/oracle_range.py --builds 200 --procs 2` |
| Harbor 40-task hard solver distribution across 300 fresh-secret builds | +0.567 (sd 0.050; median +0.572; [+0.49, +0.64]; 300) | `results/solver_range/solver_hard_judge40.json`, `results/solver_range/solver_hard_judge40.md` | `a52dde2d` | `uv run python scripts/solver_spread.py 300 --tier hard --seeds 40 --agent solver` |
| Dry Harbor rehearsal (10 hard judge tasks `900000-900009`: OpenCode vs oracle, `do_nothing`, `stop_early`) | +0.398 vs +0.467; 85% [11%, 355%]; +0.000; 9 / 10; n=10 | `results/harbor/rehearsal-dry/TABLE.md`, `results/harbor/rehearsal-dry/README.md` | `cf27834a` | `uv run python scripts/rehearsal_table.py` |

---

## 5. Craft Timings & Reproducibility (Rubric: 15 pts)

Clean-environment fresh-clone timings across macOS arm64 and Linux x86_64 (including annotated tag `afterquery-final` at `1bc3e281`, documented in [results/fresh_clone/README.md](../results/fresh_clone/README.md#linux-x86_64-at-tag-afterquery-final-1bc3e281)):

| Metric | Verified Value | Source Artifact | Producing Commit | Recompute Command |
|---|---|---|---|---|
| macOS arm64 clean-env fresh clone (`clone`, `setup`, `reproduce`, `accept`, `test`) | 8 s, 2 s, 52 s, 142 s, 905 s (967 passed, 7 skipped; cold Python 7.3 s) | `results/fresh_clone/README.md`, `results/fresh_clone/macos_justSilas_09e7363.steps.txt`, `results/fresh_clone/macos_justSilas_09e7363.log.txt` | `09e7363`, `a52dde2d` | `make setup && make reproduce` |
| Linux x86_64 clean-env fresh clone (`clone`, `reproduce_fast`, `reproduce`, `audit`, `test`) | 5 s, 83 s, 159 s, 202 s, 263 s (115 passed; 4 PASS, 1 WARN, 0 FAIL) | `results/fresh_clone/README.md`, `results/fresh_clone/linux_x86_64_justSilas_2b301cea.steps.txt`, `results/fresh_clone/linux_x86_64_justSilas_2b301cea.log.txt` | `2b301cea` | `uv run python scripts/audit_submission.py --run-reproduce` |
| Linux x86_64 clean-env fresh clone on tag `afterquery-final` (`clone`, `reproduce_table`, `reproduce`, `audit_submission`, `test_core`) | 3 s, 27 s, 118 s, 4 s, 175 s (100 passed; 3 PASS, 1 WARN, 0 FAIL) | `results/fresh_clone/README.md`, `results/fresh_clone/linux_x86_64_afterquery_final_1bc3e281.steps.txt`, `results/fresh_clone/linux_x86_64_afterquery_final_1bc3e281.log.txt` | `1bc3e281`, `afterquery-final` | `uv run python scripts/audit_submission.py` |
| Keyless craft & gitless ZIP verification gates (`verify_artifact_numbers`, `check_craft_consistency`, `audit_doc_hygiene`, `verify_doc_commands`, `verify_zip_export`) | 4, 0 | `results/judge_table.md`, `results/fresh_clone/README.md` | `f9fb7a4a`, `58716742` | `uv run python scripts/verify_artifact_numbers.py` |

---

## 6. WS4 Tiebreak (Small-Model Held-Out Progression)

Qwen2.5-1.5B-Instruct LoRA playing full held-out episodes (`800000+`) solo under `train.eval_hf` (two-sample deltas across independent per-run world secrets; tiebreak bar `mean > 0` with 95% CI above 0 is honestly reported as not met).

| Metric | Verified Value | Source Artifact | Producing Commit | Recompute Command |
|---|---|---|---|---|
| Untrained base Qwen2.5-1.5B-Instruct (4k context, all tiers, 3% valid tool calls) | 0.000 +/- 0.000; 0.03; n=36 | `fr8/analysis/out/ws4_table_v3.md`, `README.md` | `3cc7add2`, `66a26f5c` | `uv run python scripts/verify_artifact_numbers.py` |
| `v2` SFT LoRA on solver trajectories (dense 4k windows, all tiers) | -0.457 +/- 0.086; n=172 | `fr8/analysis/out/ws4_table_v3.md`, `fr8/analysis/out/ws4_table_8k_s1s2.md` | `3cc7add2`, `266bca3b` | `uv run python scripts/verify_artifact_numbers.py` |
| `v3-4k` s0 GRPO on environment reward (Verda H100, 609 steps, all tiers & two-sample delta vs `v2`) | -0.147 +/- 0.063; +0.310 +/- 0.107; n=180 | `fr8/analysis/out/ws4_table_v3.md`, `fr8/analysis/out/ws4_table_8k_s1s2.md` | `3cc7add2`, `66a26f5c` | `uv run python scripts/verify_artifact_numbers.py` |
| `v3-8k` seed 2 GRPO (Verda H100 spot, 693 steps, 8k context, all tiers) | -0.050 +/- 0.049; n=90 (30, -0.067, 0.000, -0.083) | `data/fr8/verda/h100spot-dbd0/runs/v3-verda-8k-s2/summary.json`, `fr8/analysis/out/ws4_table_v3.md`, `fr8/analysis/out/ws4_table_8k_s1s2.md` | `266bca3b`, `66a26f5c` | `uv run python scripts/verify_artifact_numbers.py` |

---

## 7. Gemini Lab (Side-Track Companion Artifacts)

| Metric | Verified Value | Source Artifact | Producing Commit | Recompute Command |
|---|---|---|---|---|
| Gemini skill-and-thinking ladder (`medium` + `hard` cells, valid episodes, ledger calls, list price) | 587; 42; 36164; 298.75 | `results/gemini/ladder.json`, `results/gemini/ladder.md` | `eb363eb9` | `make lab-replay` |
| Gemini red-team swarm across 4 real waves (primary finished, MCP re-runs, tool calls, verified exploits) | 91 (96, 5, 9, 100); 4325; 0 | `results/gemini/swarm.json`, `results/gemini/swarm.md` | `905cdd9d`, `af76fa091c` | `make lab-replay` |
| Positive-control swarm on reopened public dev seeds (`swarm_control.json`) | 4; 43 | `results/gemini/swarm_control.json`, `results/gemini/swarm_control.md` | `ab229625` | `make lab-replay` |
| Gemini API ablations (thought-signature OFF rejections, programme explicit-cache savings) | 10; 0; 678.19; 75.9 | `results/gemini/ablations.json`, `results/gemini/ablations.md` | `4e984659` | `uv run python scripts/verify_submission_surfaces.py` |

---

## 8. Closure Ledger for `docs/reports/number_audit.md` (`M1`-`M10` & Post-Audit Fixes)

Earlier audit [docs/reports/number_audit.md](reports/number_audit.md) (`0e17fc45`, auditing `a54f4223`) flagged 10 secondary citation items (`M1`-`M10`). Every item plus subsequent review-panel disclosures was closed in git on `justSilas`:

| Item | Original Finding | Verified Resolution | Target Artifact | Closing Commit |
|---|---|---|---|---|
| `M1` | `README.md` cited stale solver hard judge-seed score `+0.625 +/- 0.088` | Updated `README.md` to match committed `results/judge_table.md` (`+0.553 +/- 0.093`, secret sha256 `893b837616b9`) | `README.md`, `results/judge_table.md` | `e379c38c` |
| `M2` | `README.md` cited `13 scripted cheats` before `stop_early` / `guess_day1` split and `swarm_w2b008` | Updated `README.md` to `14 scripted attack probes and 1 swarm probe` (33 rows/tier = 99 total) | `README.md`, `results/anticheat/exploits.md` | `925fe48c` |
| `M3` | `docs/EXPLOITS.md` and `exploits.md` had pre-rehearsal Harbor counts (`37/37` trials, `13/13` jobs) | Regenerated `results/anticheat/exploits.{json,md}` and updated `docs/EXPLOITS.md` to `80 of 80` trials, `18 of 18` jobs, `61` isolation logs, `57` HMAC-verified trials | `results/anticheat/exploits.json`, `docs/EXPLOITS.md` | `bd535a45` |
| `M4` | `docs/EXPLOITS.md` row J13 cited Wave 1 + blackbox subtotal instead of merged 4-wave swarm | Updated J13 to merged 4-wave `swarm.json` totals (`100` ledger-verified attempts, `91` primary finished + `9` MCP re-runs, `4,325` calls, `0` exploits) | `docs/EXPLOITS.md`, `results/gemini/swarm.md` | `bd535a45` |
| `M5` | `docs/EXPLOITS.md` `cheat_probe` file-attempt prose summed to 148 instead of `149` | Clarified `7 file attempts (6 planted reward/ledger fakes plus 1 15-minute rewrite loop)` (`60 + 13 + 7 + 60 + 9 = 149`) | `docs/EXPLOITS.md` | `bd535a45` |
| `M6` | `harbor/README.md` and `configs/README.md` cited `EXPLOITS #25` instead of `#27` for `/proc/<pid>/environ` | Updated cross-references to `EXPLOITS #27` | `harbor/README.md`, `configs/README.md` | `bd535a45` |
| `M7` | `configs/README.md` and `docs/CONTRACT.md` cited 30 judge seeds (`900000-900029`) | Updated to `900000-900039` (`40` frozen judge seeds per tier in `canary/rules.py`) | `configs/README.md`, `docs/CONTRACT.md` | `bd535a45` |
| `M8` | `docs/DEMO.md` held pre-refresh counts (96 rows, 43 exploit rows, earlier swarm/ladder snapshots) | Refreshed `docs/DEMO.md` to 99 battery rows, 52 exploit rows, 4-wave swarm, and resolved `judge_table.md` notes | `docs/DEMO.md` | `edd4fe6d` |
| `M9` | `docs/reports/gap.md` v1.3 table omitted 3 `luck-adj.` cells and rounded `46.47%` to `46%` | Filled `-22%`, `-126%`, `-200%`, corrected `46%` -> `47%`, and noted `data/runs/committed/superseded/` paths | `docs/reports/gap.md` | `8522baea` |
| `M10` | `docs/CONTRACT.md` early sections lacked v0.3/v1.3 amendment pointers; `docs/HISTORY.md` cited older fingerprint | Added section amendment pointers, updated `.634` / `guess_day1`, and synced `893b837616b9` judge-table snapshot | `docs/CONTRACT.md`, `docs/HISTORY.md` | `8522baea` |
| `Pooled-60` | `README.md` `make reproduce` note explained `n=32` OpenCode replay row without `n=60` solver replay row | Documented both pooled replay rows (`n=32` `+0.349 +/- 0.190` and `n=60` `+0.498 +/- 0.097`) vs locked `n=30` `HEADLINE` | `README.md` | `8522baea`, `ca90d0b2` |
| `Panel-A` | Seed-set lock wording (`671ed96` 28 s after `8fd4dec`), non-binding `access_constraints`, and `20+10` solver dirs | Disclosed post-hoc seed lock, `W4` clearance note, and two solver reference dirs across `README.md`, `gap.md`, and `SUBMISSION.md` | `README.md`, `docs/reports/gap.md`, `docs/SUBMISSION.md` | `92708834`, `dcd8c372` |
| `Panel-D` | Tool error `data.detail` addition + `W1` wording fix and `afterquery-final` release tag | Added mole-independent `data.detail`, disclosed `28 of 3,841` calls, and tagged `afterquery-final` | `README.md`, `docs/DIFFICULTY.md` | `1bc3e281` |
| `PreReg` | Pre-registration of `gpt-5.5` OpenCode v1.4 hard run (`seeds 0-29`) before any episode | Committed pre-registration protocol, spend cap, and stop time prior to execution | `docs/reports/gap.md` | `cf394894` |
| `FinalHunt` | Post-tag `afterquery-final` (`1bc3e281`) 15-minute wire-level hunt + `make hunt` + `make reproduce` + `make accept` | Verified `12 of 12` MCP wire attacks held, `make hunt` `0.000` / `0` violations, `99` anticheat rows `0` diffs, `1,057` pytest pass, `PASS=20, FAIL=0` | `docs/reports/integrity.md`, `results/anticheat/judge_hunt.md` | `58716742` |
