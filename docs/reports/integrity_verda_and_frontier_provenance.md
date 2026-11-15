# Verda WS4, FR8 Frontier Replication, and G1 Extension Provenance Audit

## 1. Executive Summary and Honesty Alignment

- **Base commits audited:** `origin/fr8/canary/integrity@e19e2bd2` synced with `justSilas@58716742` (including `afterquery-final` tag verification, `cf394894` `gpt-5.5` advance lock, `1bc3e281` Panel Fix D `data.detail` + W1 wording disclosure, `668a196b` `tamper_guard` normalization, and `efd99c23` / `66a26f5c` Verda WS4 readout). Zero protected paths in `.github/protected-paths.txt` were modified.
- **Execution discipline:** `0` live Gemini / OpenAI / external LLM API calls; `--workers 1` sequential single-process audit using `/tmp/fleet-silas/shared/agent-arena-venv/bin/python`; temporary mutation controls confined to `/tmp/opencode/w7` and deleted on exit; total wall time `24.996s` (`overall_ok = True`).
- **Panel Fix A + D honesty alignment:** Canary's `v1.4` `hard` headline gap leads with raw `65% [24%, 98%]` (`+0.322` vs solver `+0.499`, `n=30`) before luck-adjusted `72% [52%, 91%]`; dev seeds `0-29` are disclosed as a `post-hoc lock` (`671ed96` committed 28 s after `8fd4dec`, locked after the primary run rather than registered beforehand); and pre-`1bc3e281` episodes recorded before 15 Nov (`data: {}` on `"invalid arguments"`) are normalized strictly on `error == "invalid arguments"` during step-level replay while post-`1bc3e281` forged `data.detail` mismatches are caught immediately.
- **Surface (a) Verda WS4 & J4 Tiebreaker Corpus:** **PASS** (`ok=True`). Audited `5` Verda eval dirs (`450` episodes, `37,696` steps), `3` J4 eval dirs (`19` episodes, `2,337` steps), `4` `curve.jsonl` training logs (`1,816` steps, `seed_base=150000` disjoint from eval/judge seeds), `6` WS4 markdown tables (`55` committed rows, `227` two-sample delta cells), `ws4_whom_v3.md` (`15/135 = 0.11` pooled v3 precision), `249` shared `(tier, seed)` pairs across runs (`0/249` identical worlds, proving two-sample CI is mandatory), honest v3 `bar NOT met` readout (`efd99c23` / `66a26f5c`), and `74` files scanned with `0` leaked secrets.
- **Surface (b) FR8 Frontier Replication (`results/frontier_replication/v1.4/**`):** **PASS** (`ok=True`). Audited `3` shards (`30` episodes, `1,550` steps, `30` companion OpenCode transcripts, `7` pre-`1bc3e281` `"invalid arguments"` steps normalized) outside `anticheat.replay_committed`'s default `data/runs/committed/` scope (`outside_default_anticheat_scope=True`), with `0` replay mismatches, `0` transcript mismatches, and `0` leaked secrets.
- **Surface (c) G1 Partial Extension & `cf394894` `gpt-5.5` Advance Lock:** **PASS** (`ok=True`). Replayed `opencode-gemini-4-carbon-ext/hard` (`2` valid episodes on seeds `[34, 37]`, `115` steps, `1` pre-`1bc3e281` normalized step) and `reference/solver-hard-seeds30to59` (`30` episodes, `2,150` steps); verified all `31` quota-excluded attempts across `9` seeds (`0` cherry-picked gameplay drops); recomputed `accuse.md`, `tags.json`, `paired_table_ext30to59.{json,md}`, and `paired_table_pooled0to59.{json,md}` (`17/17` numeric rows exact); and verified the `cf394894` `gpt-5.5` advance lock (`0` prior `v1.4` OpenAI episodes) + runner/MCP key isolation.
- **Surface (d) Synthetic Tamper & Mutation Positive Controls:** **PASS** (`8/8` caught, `all_caught=True`).

## 2. Keyless Reproduce Commands

```bash
/tmp/fleet-silas/shared/agent-arena-venv/bin/python scripts/integrity_verda_and_frontier_provenance.py --workers 1 --scratch-dir /tmp/opencode/w7 --write-report docs/reports/integrity_verda_and_frontier_provenance.md --check-report docs/reports/integrity_verda_and_frontier_provenance.md
/tmp/fleet-silas/shared/agent-arena-venv/bin/python -m pytest -p no:cacheprovider -q tests/test_integrity_verda_and_frontier_provenance.py
```

## 3. Surface (a): Verda WS4 and J4 Tiebreaker Provenance (`data/fr8/verda/**`, `data/fr8/j4/**`)

### 3.1 Episode, Step, Seed, and Summary Verification

| Run directory | Episodes | Steps | Seed offset | `summary.json` | Score / Step / Seed / Summary violations | Status |
|---|---:|---:|---:|---|---|---|
| `data/fr8/verda/a100-ac58/runs/v3-verda-8k-s1` | 90 | 3,443 | 0 | `True` | `0` | `PASS` |
| `data/fr8/verda/evalbox-68bb/v2-off30` | 90 | 5,988 | 30 | `True` | `0` | `PASS` |
| `data/fr8/verda/evalbox-68bb/v3-4k-s0-off30` | 90 | 8,615 | 30 | `True` | `0` | `PASS` |
| `data/fr8/verda/h100-3bb7/runs/v3-verda-s0` | 90 | 9,343 | 0 | `True` | `0` | `PASS` |
| `data/fr8/verda/h100spot-dbd0/runs/v3-verda-8k-s2` | 90 | 10,307 | 0 | `True` | `0` | `PASS` |
| `data/fr8/j4/run-44397/runs/eval-base` | 2 | 600 | 0 | `True` | `0` | `PASS` |
| `data/fr8/j4/run-44397/runs/eval-lora` | 5 | 433 | 0 | `False` | `0` | `PASS` |
| `data/fr8/j4/run-44397/runs/eval-lora-par` | 12 | 1,304 | 0 | `True` | `0` | `PASS` |

- **Held-out & training seed isolation:** Every evaluated Verda (`450` episodes) and J4 (`19` episodes) run uses only `HELDOUT_SEEDS` (`800000..800199`), disjoint from `DEV_SEEDS` and `JUDGE_SEEDS`. All `3` `train_summary.json` files record `seed_base = 150000` (`150000..199999`), disjoint from all evaluation and judge seed ranges. `data/fr8/verda/run-verda-s0/curve.jsonl` (`143` steps) is an exact line-for-line prefix of `data/fr8/verda/h100-3bb7/run-verda-s0/curve.jsonl` (`609` steps; total curve records `1,816`).
- **Cross-run world non-pairing proof (`04:00 CORRECTION`):** Across all `249` shared `(tier, seed)` pairs among the 8 Verda + J4 runs, `0/249` share an identical employee roster because `HELDOUT_SEEDS` generate worlds under per-process `_process_secret()` (`os.urandom(32)`). Consequently, cross-process held-out runs are independent draws and **must** use two-sample CIs rather than seed-paired differences.
- **Pooling & duplicate-seed behavior (`ws4_table.load`):** `j4` v1 (`eval-lora` `5` eps + `eval-lora-par` `12` eps = `17` raw) drops `5` overlapping `(tier, seed)` episodes to `n=12`, making mean score order-dependent (`-0.2500` vs `-0.0429`); `v3-4k-s0` (`seed_offset=0` + `seed_offset=30`) has `0` overlap (`n=180`, order-invariant); pooling `v3-8k-s1` + `v3-8k-s2` directly would silently drop all 90 `s2` episodes because both used `seed_offset=0` (`800000..800029`).
- **WS4 tables & honest bar-not-met readout (`efd99c23` / `66a26f5c`):** Verified `55` committed model rows and `227` two-sample delta cells across all `6` `fr8/analysis/out/ws4_table*.md` files (`0` mismatches) plus all `3` v3 rows in `ws4_whom_v3.md` (`15/135 = 0.11` pooled v3 accusation precision, close to uniform random `1/9` to `1/7`). All `4` rows of `ws4_table_v3.md` (`efd99c23`), `README.md` (`66a26f5c`), and `docs/reports/fr8.md` (`04:45` readout) honestly report tiebreak bar **not met** (`v3-4k-s0` `-0.147 +- 0.063` on `n=180`, `+0.310 +- 0.107` over `v2` `-0.457`, still below `base` `0.000` on `n=36` and `v3-8k-s2` `-0.050 +- 0.049` on `n=90`).

## 4. Surface (b): FR8 Frontier Replication (`results/frontier_replication/v1.4/**`)

| Shard directory | Episodes | Steps | Pre-`1bc3e281` norm | Transcripts | `meta.usage` matches episodes | Replay / Transcript mismatches | Status |
|---|---:|---:|---:|---:|---|---|---|
| `results/frontier_replication/v1.4/opencode-gemini-3.5-flash/medium-00-14` | 15 | 791 | 3 | 15 | `True` | `0` | `PASS` |
| `results/frontier_replication/v1.4/opencode-gemini-3.5-flash/medium-15-29` | 14 | 717 | 3 | 14 | `False` | `0` | `PASS` |
| `results/frontier_replication/v1.4/opencode-gemini-3.5-flash/medium-s28` | 1 | 42 | 1 | 1 | `None` | `0` | `PASS` |

- **Primary `medium` replication cohort (`n=30`, seeds `0..29` unique and complete, API-served as `gemini-3.6-flash` under path `opencode-gemini-3.5-flash`):** mean `0.4343 +- 0.2356` vs committed `v1.4/reference` `solver` `0.6450 +- 0.0871` (raw ratio `67.3% [29.4%, 103.3%]`, luck-adjusted `75.2% [44.9%, 105.4%]`, paired diff `-0.2107 +- 0.2506`). Floor bounds (`>= 3` shards, `>= 30` episodes, `>= 1,550` steps, `>= 30` transcripts) hold even as additional replication cohorts land.

## 5. Surface (c): G1 Partial Extension, `cf394894` `gpt-5.5` Advance Lock, and `58716742` Alignment

- **Step-level & transcript replay:** `data/runs/committed/v1.4/opencode-gemini-4-carbon-ext/hard` (`2` valid episodes on seeds `[34, 37]`, `115` steps, `1` pre-`1bc3e281` `"invalid arguments"` step normalized, `2/2` transcripts matched, `meta.usage` exact match `$2.1401` est / `$11.1305` upper) and `data/runs/committed/v1.4/reference/solver-hard-seeds30to59` (`30` episodes on seeds `30..59`, `2,150` steps, `meta.json` summary mean `0.498` exact) both pass with `0` mismatches.
- **Quota-exclusion integrity (`validate_g1_quota_exclusions`):** Planned seeds `30..59` (`30` total) = `2` valid (`[34, 37]`) + `28` missing (`status` string exact match). All `31` excluded attempts across `9` attempted seeds (`30, 31, 32, 33, 35, 36, 38, 39, 40`; seeds `41..59` unattempted after quota stop) carry `invalid: infra:provider_quota` and are strictly disjoint from valid seeds `[34, 37]` (`0` gameplay losses excluded).
- **Derived G1 artifacts:** `accuse.md` (`True`), `tags.json` (`True`), `paired_table_ext30to59.{json,md}` (`2/2` rows exact canonical + markdown match), and `paired_table_pooled0to59.{json,md}` (`17/17` rows `100%` numeric match; `2` `stop_early` baseline rows retain pre-`e379c38c` short label, logged as `ISSUE-W7-6`).
- **`cf394894` `gpt-5.5` advance lock & `58716742` `afterquery-final` verification:** `docs/reports/gap.md` registers `gpt-5.5` beforehand via advance lock in `cf394894` (`OpenCode 1.19.5` over MCP on `v1.4` `hard`, dev seeds `0-29` in fixed order, `7,200 s` timeout, tag `afterquery-final`, `08:15 Helsinki` / `$200` launch stop, `08:45` hard drop, reported whatever the outcome, disclosing 15 Nov wording/detail updates and OpenCode `1.19.5` vs `1.18.29`); `data/runs/committed/v1.4/` contains `0` OpenAI episodes prior to execution; `docs/reports/integrity.md` (`58716742`) records the final `12 of 12 held` judge-protocol hunt on `afterquery-final`; and `common.child_env()` + `opencode_run.child_env_extra()` isolate `OPENAI_API_KEY` vs `GOOGLE_GENERATIVE_AI_API_KEY` and strip `CANARY_LEDGER_TOKEN` (`openai_key_isolated_from_mcp_server=True`).

## 6. Surface (d): Synthetic Tamper and Mutation Positive Controls (`/tmp/opencode/w7`)

| Control ID | Mutation injected in scratch dir | Caught |
|---|---|---|
| `forged_verda_summary_caught` | Forged `summary.json` `by_tier.all.mean_score = 0.42` vs `train.eval_hf.summarize` | `True` |
| `forged_verda_episode_score_caught` | Forged `score = 0.85` on unaccused `eval_cap` Verda episode | `True` |
| `tampered_replication_step_caught` | Mutated step `V = 0.1234` and `score = 0.99` in `medium-s28` (caught by `Env` + transcript) | `True` |
| `tampered_replication_transcript_caught` | Deleted `canary_status` event lines in `transcripts/28.txt` | `True` |
| `cherry_picked_quota_drop_caught` | Injected gameplay loss (`wrong_accusation_score=-1.0`) and valid-seed (`34`) overlap in quota exclusions | `True` |
| `leaked_secret_injection_caught` | Injected synthetic Google API key (`AIza...`) into scratch artifact | `True` |
| `forged_post_1bc3e281_detail_caught` | Injected mismatched `data.detail` on step 6 `"invalid arguments"` (`pre_1bc3e281_detail_normalized = 0`) | `True` |
| `non_invalid_args_detail_not_masked_caught` | Verified non-`"invalid arguments"` and `ok=True` `data.detail` payloads are never stripped | `True` |

## 7. Report-Only Findings Ledger (Zero Exploit Impact, Zero Protected Edits)

| Issue ID | Severity | Area | Summary |
|---|---|---|---|
| `ISSUE-W7-1` | `low` | `verda_ws4_reproducibility` | fr8/analysis/ws4_v3_readout.sh references uncommitted local WS4/FR8 episode dirs (.gitignore masks data/fr8/**/*.jsonl) |
| `ISSUE-W7-2` | `info` | `verda_ws4_provenance` | Verda eval meta.json files have empty git_sha ('') because code was rsynced without .git |
| `ISSUE-W7-3` | `low` | `verda_ip_hygiene` | Zero API keys/tokens/secrets leaked, but instances-0308.txt and instances-2337.txt record 8 ephemeral Verda public IPv4 addresses |
| `ISSUE-W7-4` | `low` | `ws4_submission_doc_sync` | docs/SUBMISSION.md section 7 cites pre-efd99c23 ws4_table_v3s0_n180.md (base n=16, justSilas-fr8 URL) whereas README.md (66a26f5c) and ws4_table_v3.md (efd99c23) report base n=36 and v3-8k-s2 n=90 (-0.050 +- 0.049); tiebreak bar-not-met verdict unchanged |
| `ISSUE-W7-5` | `low` | `frontier_replication_metadata` | medium-15-29/meta.json usage retains failed first-attempt spend of seed 28 (+42 LLM calls, +$0.5712), while medium-s28/meta.json has usage=null and omits tiers_version |
| `ISSUE-W7-6` | `info` | `g1_pooled_table_label` | paired_table_pooled0to59.{json,md} matches 100% of numeric values across all 17 rows, with pre-e379c38c 'stop_early' display label on 2 baseline rows instead of 'day-1 guess (recorded under the pre-...' |
| `ISSUE-W7-7` | `info` | `mcp_launch_env_key_scrubbing` | canary.mcp_server.clean_launch_env strips CANARY_* vars rather than *_API_KEY; gemini_runner.py single-seed .env launches start MCP before load_env() so OPENAI_API_KEY stays out of canary.mcp_server, whereas pre-exported shell OPENAI_API_KEY or multi-seed single-process opencode_run inherits OPENAI_API_KEY into clean_launch_env() |
