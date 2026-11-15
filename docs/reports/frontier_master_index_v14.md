# Canary v1.4 Frontier Replication and Forensics Master Index

Single-entry judge index and cross-artifact consistency manifest for all `frontier` v1.4 replication, cross-family, sensitivity, trajectory, and transcript forensics deliverables (`0` live API calls, `0` subprocesses, `0` `.git` runtime calls).

Fast offline master check (`< 1.5s`, keyless):

```bash
PYTHONPATH=. python scripts/verify_frontier_suite.py --check
PYTHONPATH=. pytest -q tests/test_frontier_suite_master.py
```

## 1. Corpus Totals and Provenance Locks (Synced with `justSilas@5f9b3297`)

- **Replay-verified v1.4 corpus (`777` episodes, `0` mismatches, `0` duplicates):** `472` committed episodes in `data/runs/committed/v1.4/` plus `305` FR8 replication episodes in `results/frontier_replication/v1.4/` (`472 + 305 = 777`), alongside `60` G2 Gemini-4 cross-family hard episodes (`532` with committed) and `29` valid OpenCode Harbor judge-path rehearsal trials (`10 + 10 + 9`).
- **Registration and lock honesty:** Primary `gemini-4-carbon` `seeds 0-29` (`8fd4dec`) are governed by a **post-hoc seed lock** (`671ed96`, `28s` after `8fd4dec`), never mislabeled as pre-registered. Pre-registered extensions/families: G1 `gemini-4-carbon` hard `30-59` and G2 `gemini-4-argon` / `gemini-4-hydrogen` hard `0-29` (`f9fb7a4a`), and OpenAI `gpt-5.5` hard `0-29` (`cf394894`, committed at `ca0a0dc0`). Step replay applies `1bc3e281` MCP error unwrapping, and repeated extension seeds deduplicate with committed G1 precedence (`eb9dee54`).

## 2. Frontier Deliverables Master Index (Scripts, JSON Artifacts, Reports, Cohort N, Commands)

| deliverable | script | JSON artifact (byte cap) | report | cohort N / scope | verification command |
|---|---|---|---|---|---|
| `frontier_suite_master` | `scripts/verify_frontier_suite.py` | `results/frontier_replication/v1.4/suite_manifest_v14.json` (`<=25000` B) | `docs/reports/frontier_master_index_v14.md` | 777 v1.4 pool (472 committed + 305 replication) + 60 G2 + 29 Harbor rehearsal trials | `PYTHONPATH=. python scripts/verify_frontier_suite.py --check` |
| `frontier_replication` | `scripts/verify_frontier_replication.py` | `results/frontier_replication/v1.4/replication_summary.json` (`<=48000` B) | `docs/reports/frontier_replication_v14.md` | 777 pool (30 primary/tier, 30 gpt-5.5, 2 G1, 5 FR8, 6 union, 30 flash med) | `PYTHONPATH=. python scripts/verify_frontier_replication.py --check` |
| `frontier_g2_families` | `scripts/frontier_g2_families_audit.py` | `results/frontier_replication/v1.4/g2_families_audit.json` (`<=45000` B) | `docs/reports/frontier_g2_families_v14.md` | 60 G2 hard (30 argon + 30 hydrogen) + 60 carbon/solver = 120 paired (532 w/ committed) | `PYTHONPATH=. python scripts/frontier_g2_families_audit.py --check` |
| `frontier_infra_sensitivity` | `scripts/frontier_infra_sensitivity.py` | `results/frontier_replication/v1.4/infra_sensitivity.json` (`<=46080` B) | `docs/reports/frontier_infra_sensitivity_v14.md` | 777 pool (6 committed + 2 sharded cohorts, 71 infra exclusions, 5 timeout caps) | `PYTHONPATH=. python scripts/frontier_infra_sensitivity.py --check` |
| `frontier_mole_stratified_gap` | `scripts/frontier_mole_stratified_gap.py` | `results/frontier_replication/v1.4/mole_stratified_gap.json` (`<=45000` B) | `docs/reports/frontier_mole_stratified_gap_v14.md` | 90 worlds (med 0-29, hard 0-29, hard 30-59), 14 cohorts (337 cohort eps in 777 pool) | `PYTHONPATH=. python scripts/frontier_mole_stratified_gap.py --check` |
| `frontier_queue_preflight` | `scripts/frontier_queue_preflight.py` | `results/frontier_replication/v1.4/queue_manifest.json` (`<=51200` B) | indexed here (manifest-only) | 777 pool (35/90 FR8 landed, 6/30 distinct carbon ext, 30/30 gpt-5.5, 8 preflight gates) | `PYTHONPATH=. python scripts/frontier_queue_preflight.py --check --validate-template-waves` |
| `frontier_trajectory_audit` | `scripts/frontier_trajectory_audit.py` | `results/frontier_replication/v1.4/trajectory_audit.json` (`<=50000` B) | `docs/reports/frontier_trajectory_audit_v14.md` | 277 active episodes across 11 cohorts (6 OpenCode, 2 in-proc, 3 solver) in 777 pool | `PYTHONPATH=. python scripts/frontier_trajectory_audit.py --check` |
| `frontier_transcript_forensics` | `scripts/frontier_transcript_forensics.py` | `results/frontier_replication/v1.4/transcript_forensics.json` (`<=45000` B) | `docs/reports/frontier_transcript_forensics_v14.md` | 97+ OpenCode transcripts (5+ active cohorts, 10 forensic case dossiers) in 777 pool | `PYTHONPATH=. python scripts/frontier_transcript_forensics.py --check` |
| `frontier_stopping_counterfactual` | `scripts/frontier_stopping_counterfactual_v14.py` | `results/frontier_replication/v1.4/stopping_counterfactual_v14.json` (`<=35000` B) | `docs/reports/frontier_stopping_counterfactual_v14.md` | 246 episodes across 9 v1.4 cohorts (Bayes break-even abstention and EV decomposition) | `PYTHONPATH=. python scripts/frontier_stopping_counterfactual_v14.py --check` |
| `frontier_gpt55_vs_carbon_forensics` | `scripts/frontier_gpt55_vs_carbon_forensics.py` | `results/frontier_replication/v1.4/gpt55_vs_carbon_forensics.json` (`<=38000` B) | `docs/reports/frontier_gpt55_vs_carbon_forensics_v14.md` | 90 paired hard episodes (30 gpt-5.5 + 30 carbon + 30 solver, 7 divergence seeds) | `PYTHONPATH=. python scripts/frontier_gpt55_vs_carbon_forensics.py --check` |
| `frontier_power_and_variance` | `scripts/frontier_power_and_variance_v14.py` | `results/frontier_replication/v1.4/power_and_variance_v14.json` (`<=38000` B) | `docs/reports/frontier_power_and_variance_v14.md` | 8 paired 0-29 cohorts + Harbor n=10 WOR DP (3.48x VRF, N_eff=104.4 on carbon hard) | `PYTHONPATH=. python scripts/frontier_power_and_variance_v14.py --check` |

## 3. Cross-Artifact Headline, Cross-Model, Extension, and Harbor Rehearsal Summary

| cohort / track | tier & seeds | n | raw score | solver raw | frontier / solver [95% CI] | luck-adj. score | luck-adj. / solver [95% CI] | provenance / note |
|---|---|---:|---:|---:|---|---:|---|---|
| **OpenCode `gemini-4-carbon` (PRIMARY)** | hard `0-29` | 30 | 0.322 | 0.499 | **65% [24%, 98%]** | 0.360 | **72% [52%, 91%]** | locked primary (`671ed96`) |
| OpenCode `gemini-4-carbon` | medium `0-29` | 30 | 0.713 | 0.645 | 111% [99%, 127%] | 0.652 | 101% [85%, 119%] | locked primary (`671ed96`) |
| OpenCode `gpt-5.5` (OpenAI family 2) | hard `0-29` | 30 | 0.504 | 0.499 | **101% [79%, 140%]** | 0.418 | **84% [67%, 103%]** | pre-reg `cf394894`; `rc=0` non-accuse `[0, 17]` |
| OpenCode `gemini-4-argon` (G2) | hard `0-29` | 30 | 0.512 | 0.499 | 103% [71%, 144%] | 0.299 | 60% [33%, 85%] | pre-reg `f9fb7a4a` (`30/30 > 900s`) |
| OpenCode `gemini-4-hydrogen` (G2) | hard `0-29` | 30 | 0.575 | 0.499 | 115% [92%, 157%] | 0.485 | 97% [75%, 119%] | pre-reg `f9fb7a4a` (`0/30 > 900s`) |
| OpenCode `gemini-3.5-flash` (FR8) | medium `0-29` | 30 | 0.434 | 0.645 | 67% [29%, 103%] | 0.485 | 75% [45%, 105%] | FR8 cross-model replication |
| OpenCode `gemini-4-carbon` G1 ext | hard `[34, 37]` | 2 | 0.745 | 0.735 | 101% | 0.710 | 109% | pre-reg `f9fb7a4a` (`31` quota excl.) |
| OpenCode `gemini-4-carbon` FR8 rep | hard `[30, 34, 42, 45, 57]` | 5 | 0.656 | 0.248 | 265% | 0.472 | 110% | FR8 `--timeout 3600` shards |
| OpenCode `gemini-4-carbon` dedup union | hard `[30, 34, 37, 42, 45, 57]` | 6 | 0.658 | 0.335 | 197% | 0.599 | 129% | G1 precedence on `[34]` (`eb9dee54`); secondary `n=32/35/36` LA `75%/77%/81%` |

### 3.1 Harbor 0.26.0 Judge-Path Rehearsal (`results/harbor/rehearsal/TABLE.md`, tag `afterquery-final`)

| run | valid trials | infra excluded | mean score | oracle (same tasks) | run / oracle [95% CI] | note |
|---|---:|---:|---:|---|---|---|
| `opencode-1` | 10 | 0 | +0.472 | +0.506 | **93% [20%, 371%]** | complete 10/10 |
| `opencode-2` | 10 | 0 | +0.585 | +0.506 | **116% [78%, 363%]** | complete 10/10 |
| `opencode-3` (final `d0ead011`) | 9 | 1 | +0.626 | same 9 tasks | **131% [86%, 590%]** | supersedes 08:52 7-trial `153%` snapshot |

## 4. Full Suite Verification Commands

```bash
PYTHONPATH=. python scripts/verify_frontier_suite.py --check
PYTHONPATH=. python scripts/verify_replay.py data/runs/committed/v1.4 results/frontier_replication/v1.4
PYTHONPATH=. pytest -q tests/test_frontier_suite_master.py tests/test_frontier_replication.py tests/test_frontier_g2_families_audit.py tests/test_frontier_infra_sensitivity.py tests/test_frontier_mole_stratified_gap.py tests/test_frontier_queue_preflight.py tests/test_frontier_trajectory_audit.py tests/test_frontier_transcript_forensics.py tests/test_frontier_stopping_counterfactual_v14.py tests/test_frontier_gpt55_vs_carbon_forensics.py tests/test_frontier_power_and_variance_v14.py
```
