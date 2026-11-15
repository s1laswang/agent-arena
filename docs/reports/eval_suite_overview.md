# Canary v1.4 Evaluation Suite: One-Command Verification & Evidence Map

**Scope.** Rules `v1.4`, post-hoc locked paired dev seeds `0-29` (`671ed96`, 28 s after `8fd4dec`; `n = 30` per tier on every primary Section A row; lock against later reruns and cherry-picking, not a pre-registration), 100% deterministic offline `canary.env.Env(tier, seed)` replay verification (`0` live LLM calls, `0` API keys, single-process, `1bc3e281` `data.detail` step-replay compatible).

```bash
python scripts/run_all_eval_checks.py --check
python scripts/run_all_eval_checks.py
make reproduce
```

## 1. Master Verifier & Artifact Index (`results/eval_v14/eval_suite_index.json`)

| Module | Keyless Check Command | JSON Artifact | Report Artifact |
|---|---|---|---|
| Master Suite Orchestrator | `python scripts/run_all_eval_checks.py --check` | `results/eval_v14/eval_suite_index.json` | `docs/reports/eval_suite_overview.md` |
| 5-Gate Claims, Replay Cache & Protected-Path Verifier | `python scripts/verify_eval_claims.py --check` | `results/eval_v14/claims_manifest.json` | `docs/reports/eval_claims_verification.md` |
| Primary Paired Headline Gap Table & Multi-Model Ladder | `python scripts/headline_gap_table.py --check` | `results/eval_v14/headline_gap_table_v14.json` | `docs/reports/headline_gap_table_v14.md` |
| 2x2 Harness x Tier Crossover & Noisy-Bayes Mechanism | `python scripts/harness_and_tier_analysis_v14.py --check` | `results/eval_v14/harness_and_tier_v14.json` | `docs/reports/medium_vs_hard_and_harness_v14.md` |
| 1x10 vs 3x10 Judge Rerun Power, Rao-Blackwell & pass^3 | `python scripts/judge_rerun_power_v14.py --check` | `results/eval_v14/judge_rerun_power_v14.json` | `docs/reports/judge_rerun_operating_characteristics.md` |
| Fact-Only Hint Ablation v1.4 Hard Causal Audit | `python scripts/hint_ablation_audit.py --check` | `results/eval_v14/hint_ablation_v14.json` | `docs/reports/hint_ablation_v14_audit.md` |

- **Auto-discovered sibling `--check` modules:** `run_all_eval_checks.py --check` also discovers and verifies any present sibling scripts among `eval_replication_and_crossmodel.py`, `counterfactual_decomposition_v14.py`, `verify_harbor_rehearsal.py`, `eval_candidate_tiers.py`, `build_eval_charts_v14.py`, `harbor_luck_adjusted_v14.py`, `ladder_pareto_v14.py`, `version_evolution_v14.py`, `version_evolution_audit.py`, `paired_seed_diagnostics_v14.py` while keeping `core_headline_summary` pinned to the 5 deterministic core JSON artifacts (`tol = 1e-9`).

## 2. Headline Gap Table (Post-Hoc Locked Paired Seeds `0-29`, `n = 30` per Tier, Replay-Verified)

- **Primary `n = 30` Hard headline (raw first, luck-adjusted second):** OpenCode + `gemini-4-carbon` over MCP scores **`65% [24%, 98%]`** of the reference solver raw (`+0.322 +/- 0.199` vs `+0.499 +/- 0.119`) and **`72% [52%, 91%]`** luck-adjusted (`+0.360` vs `+0.499`, `p_luck = 0.0221`). Reference solver seeds `0-29` come from two committed directories (`solver-hard-20261114-121126` seeds `0-19` + `solver-hard-seeds20to29` seeds `20-29`); Hard's canary clearance rule never binds (`docs/DIFFICULTY.md` W4).
- **Replay corpus:** Recomputed with `10,000` paired bootstrap resamples (`rng_seed = 0`) across `180` primary frontier episodes, `60` stored reference solver episodes, `420` scripted baseline episodes, and `587` canonical Gemini thinking-ladder episodes across `42` cells (`eb363eb9`, plus `5` Gemma episodes in `results/gemini/ladder.json`; `550` local archive episodes step-replayed) with **zero** `Env` score, accusation, or tool-output mismatches (`1bc3e281` `invalid arguments` `data.detail` rule enforced for pre-`1bc3e281` transcripts).

| Tier | Cohort (`n = 30`, seeds `0-29`) | Raw Score +/- 95% CI | Raw / Solver `[95% CI]` | Luck-Adj Score | Luck-Adj / Solver `[95% CI]` | `p_luck` (Wilcoxon) | Cal. `pass^3` | Winnable / Solver `[95% CI]` |
|---|---|---:|---|---:|---|---:|---:|---|
| `hard` | OpenCode + gemini-4-carbon (judges' MCP) | `+0.322 +/- 0.199` | `65% [24%, 98%]` | `+0.360` | `72% [52%, 91%]` | `0.0221` | `0.714` | `67% [31%, 99%]` |
| `hard` | OpenCode + gemini-4-carbon (0-imputed sens.) | `+0.279 +/- 0.180` | `56% [19%, 87%]` | `+0.277` | `55% [34%, 77%]` | `0.0016` | `0.574` | `59% [27%, 88%]` |
| `hard` | in-process gemini-4-carbon (full history) | `+0.473 +/- 0.118` | `95% [62%, 140%]` | `+0.421` | `84% [65%, 106%]` | `0.2894` | `0.804` | `85% [57%, 109%]` |
| `hard` | OpenCode + gemini-3.5-flash (judges' MCP) | `+0.373 +/- 0.177` | `75% [36%, 123%]` | `+0.110` | `22% [-23%, 63%]` | `0.0221` | `0.601` | `66% [31%, 96%]` |
| `hard` | OpenCode + gpt-5.5 (judges' MCP) | `+0.504 +/- 0.064` | `101% [79%, 140%]` | `+0.418` | `84% [67%, 103%]` | `0.1840` | `0.793` | `91% [75%, 109%]` |
| `hard` | reference solver (Harbor oracle) | `+0.499 +/- 0.119` | `100% (ref)` | `+0.499` | `100% (ref)` | `--` | `0.903` | `100% (ref)` |
| `hard` | grok_tactics (scripted baseline) | `+0.432 +/- 0.085` | `87% [67%, 119%]` | `+0.384` | `77% [61%, 95%]` | `0.0099` | `0.838` | `78% [63%, 94%]` |
| `hard` | do_nothing / stop_early (zero baseline) | `+0.000 +/- 0.000` | `0% [0%, 0%]` | `+0.000` | `0% [0%, 0%]` | `<1e-4` | `0.000` | `0% [0%, 0%]` |
| `hard` | guess_day1 (day-1 guess baseline) | `-1.000 +/- 0.000` | `-200% [-271%, -167%]` | `-0.950` | `-190% [-218%, -169%]` | `<1e-4` | `0.000` | `-182% [-206%, -163%]` |
| `medium` | OpenCode + gemini-4-carbon (judges' MCP) | `+0.713 +/- 0.042` | `111% [99%, 127%]` | `+0.652` | `101% [85%, 119%]` | `0.7749` | `0.924` | `101% [95%, 108%]` |
| `medium` | in-process gemini-4-carbon (full history) | `+0.530 +/- 0.138` | `82% [56%, 108%]` | `+0.479` | `74% [52%, 99%]` | `0.1241` | `0.755` | `73% [49%, 92%]` |
| `medium` | reference solver (Harbor oracle) | `+0.645 +/- 0.087` | `100% (ref)` | `+0.645` | `100% (ref)` | `--` | `0.900` | `100% (ref)` |

- **Pre-registered G1 extension (`f9fb7a4a`, data `364fe657`, stopped early for rehearsal quota):** `n = 2` completed valid OpenCode `gemini-4-carbon` hard episodes (`seeds = [34, 37]`, `+0.745 +/- 0.088` vs solver `+0.735`, raw `101% [91%, 113%]`, luck-adjusted `109% [105%, 114%]`); pooled `n = 32` (`0-29` + `[34, 37]`) is **`68% [32%, 100%]`** raw (`+0.349 +/- 0.190` vs solver `+0.514`, paired diff `-0.165 +/- 0.182`) and **`75% [56%, 93%]`** luck-adjusted (`make reproduce` pools `n = 32` OpenCode and `n = 60` solver in `judge_table.md`, while `HEADLINE` recomputes locked `n = 30`).
- **Pre-registered second frontier family (`cf394894`):** `gpt-5.5` via OpenCode 1.19.5 over MCP on `v1.4` hard seeds `0-29` (env tag `afterquery-final`, stop `08:15` Helsinki / `$200` cap; committed directory `data/runs/committed/v1.4/opencode-gpt-5.5` present).
- **Harbor judge-path rehearsal (`c59ecfd0`, `results/harbor/rehearsal/TABLE.md`, tag `afterquery-final` `1bc3e281`):** Harbor 0.26.0 + OpenCode + `gemini-4-carbon` across `3` runs on `10` hard judge tasks (`900000-900009`; shell enabled in container, used in `20/28` trials) scored `+0.472` (`93%`), `+0.585` (`116%`), and `+0.656` (`153%`, partial `n = 7` valid) vs same-task oracle `+0.506` / `+0.429` (`do_nothing = stop_early = +0.000`); the `65%` MCP-only gap did **not** reproduce in the Harbor judge path.

## 3. 2x2 Harness x Tier Crossover & Noisy-Bayes Mechanism (`180` Paired Episodes)

- **Statistically significant crossover (`(OC_hard - IP_hard) - (OC_med - IP_med)`):** OpenCode beats In-Process on Medium (`+0.183 [+0.059, +0.341]` raw, `p = 0.0002`; `+0.173 [+0.034, +0.322]` luck-adjusted, `p = 0.0108`), whereas In-Process beats OpenCode on Hard (`OC - IP = -0.151 [-0.382, +0.070]` raw; `-0.061 [-0.202, +0.077]` luck-adjusted). Paired Difference-in-Differences is **`-0.333 [-0.659, -0.046]`** raw (`p = 0.0224`, indep-tier CI `[-0.611, -0.077]`) and **`-0.234 [-0.461, -0.017]`** luck-adjusted (`p = 0.0350`, indep-tier CI `[-0.438, -0.036]`), excluding zero on both metrics.
- **Shared Hard exploration bottleneck + 5% flip trap:** Both OpenCode and In-Process severely under-use the 2-canary/day pipeline on Hard (`8.47` and `8.57` canaries = `32%` and `33%` capacity vs Solver's `14.13` = `67%`) while spending `68.0` and `57.3` calls on near-zero-KL interviews (Solver: `0.0`). Under `95%` fingerprint accuracy (`5%` variant flip), OpenCode's strict set elimination falls into false singleton traps (`4` wrong accusations, mean `P(accused) = 0.882`), whereas In-Process (`thought_signature_replay`) tracks noisy likelihoods (`1` wrong, mean `P(accused) = 0.930`) and recovers the true culprit on `2` episodes where subsequent leaks drove the noiseless consistent set to `|C| = 0`.

## 4. `1x10` vs `3x10` Judge Rerun Power, Rao-Blackwell & `pass^3` (`50,000` MC Trials)

- **Harbor 10-task hard oracle band (`200` synthetic secrets):** 90% range **`+0.39` to `+0.68`** (mean `+0.569`, SD `0.094`). One flipped hard accusation swings a 10-task mean by `(1 + V)/10 = 0.155 V` (`opencode-carbon`; `0.155 V` `solver`, `~0.16 V` per flipped task).
- **`3x10` paired judge power (`opencode-carbon < oracle`):** Pooling `R = 3` frontier runs cuts paired gap SD by `sqrt(3) = 1.732x` (`0.168 -> 0.097` raw; `0.090 -> 0.052` luck-adjusted) and raises `P(frontier_mean < oracle_mean)` from `85.1%` (`1x10`) to **`97.8%`** (`3x10`) raw and **`99.8%`** luck-adjusted under empirical paired resampling (Model A), and from `77.7%` to **`83.4%`** on a single fixed 10-world Harbor build (Model B, within-build run-mean SD `0.135 V -> 0.078 V`).
- **Rao-Blackwell luck-adjusted variance reduction (`>3x`):** Conditional accusation coin-flip noise accounts for **`53.2%`** of `opencode-carbon`'s `1x10` gap variance (`76.3%` including oracle 5%-flip risk). Scoring by exact solver-posterior expectation `P * V - (1 - P)` cuts estimator variance by **`3.48x`** empirically (`n_eff = 34.8` at `k = 10`) and **`4.22x`** analytically under Model B (`n_eff = 42.2`, `2.72x` even vs `3x10` raw).
- **`pass^3` exposes lucky horizon gamblers (`gemini-3.5-flash` collapse):** `opencode-3.5-flash` scored `+0.373` raw (`0.900` empirical accuracy) only via `+0.263 V/ep` of windfall across `10` low-posterior (`P < 0.60`) gambles. Posterior-calibrated `pass^3 = E[P_win^3]` collapses `3.5-flash` to **`0.601`** (`[0.446, 0.750]`, and **`0.028`** on its `10` gamble worlds; Model B `3x10` `P(F < O) = 96.3%`), ranking strictly: `solver (0.903) > inproc-carbon (0.804) > opencode-carbon (0.714) > opencode-3.5-flash (0.601)`.

## 5. Fact-Only Hint Ablation Causal Audit (`v1.4` Hard, Paired Seeds `0-9`)

- **Replay & mechanism shifts (`30/30` ablation + `30/30` context episodes, `5986` step-verified tool calls, `0` mismatches):** Appending single-sentence rule reminders (`HINTS_V2`) to in-process `gemini-4-carbon` shifts mechanism cleanly: `premature_accusation` (`+0.487 +/- 0.081` raw, `+0.448` LA vs `control` `+0.427 +/- 0.329` raw, `+0.420` LA) eliminates negative-EV gambles (`1 -> 0`, `P(accused)` `0.877 -> 0.974`, interviews `-21.5 [-39.6, -5.5]`); `decoy_chase` (`+0.648 +/- 0.077` raw, `+0.603` LA; paired diff vs `control` `+0.221 [-0.047, +0.605]` raw, `+0.183 [-0.030, +0.471]` LA) raises day-1 canary planting (`4/10 -> 7/10`) and cuts interviews (`-18.8 [-40.9, +3.7]`). At `n = 10`, paired score 95% CIs straddle `0.000` (unhinted `inproc` replicate on `0-9`: `+0.379` raw / `+0.439` LA, vs `solver` `+0.576` / `+0.556`), so we claim causal mechanism shifts rather than `n = 10` score significance (the separate pre-registered OpenCode `--hint gather` protocol in `docs/reports/gap.md` `fd8c1cb0` was stopped before `05:40` to preserve shared Gemini quota for the Harbor rehearsal).

## 6. 5-Gate Claims, Version & Protected-Path Hygiene (`claims_manifest.json`)

- **All `5/5` deterministic gates PASS (`0` violations):** Gate 1 cross-checks `README.md`, `docs/reports/gap.md`, `results/judge_table.md`, and `16` committed `paired_table_gemini.json` rows within `1e-9`; Gate 2 verifies seed completeness (`0..29`, `0` duplicates) and 100% `Env` step replay; Gate 3 confirms `do_nothing` (`+0.000 +/- 0.000`) and `stop_early` (`+0.000 +/- 0.000`) equal `0.0` while `guess_day1` averages `-0.953` (max `-0.80 < 0`) across `300` fresh judge secrets; Gate 4 enforces zero `v1.2`/`v1.3`/`superseded` mixing across `22` `v1.4` meta files and `6` active docs (`PRIMARY` post-hoc seed lock `671ed96` vs `REPLICATION` and pre-registered `EXTENSION` `f9fb7a4a` / `cf394894` verified); Gate 5 enforces all `15` `.github/protected-paths.txt` rules and `7` secret/mole-leak pattern classes across `results/eval*` and `docs/reports/`.
