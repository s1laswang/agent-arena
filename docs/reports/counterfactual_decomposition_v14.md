# Canary v1.4 Counterfactual Gap Decomposition (Paired Seeds 0-29)

**Authoritative headline, cross-family & rehearsal framing (Panel Fix A).** In the MCP-only dev setup (OpenCode + `gemini-4-carbon` over MCP, rules `v1.4`, paired dev seeds `0-29`, `n = 30` per tier), the primary Hard row in `docs/reports/gap.md` is **`65% [24%, 98%]`** raw (`+0.322 +/- 0.199` vs reference solver `+0.499 +/- 0.119`, paired gap `Delta = +0.177 V/ep` = `+5.30 V` over 30 seeds) and **`72% [52%, 91%]`** luck-adjusted (`+0.360` vs `+0.499`), with Medium at `111% [99%, 127%]` raw and `101% [85%, 119%]` luck-adjusted. Primary seeds `0-29` are a **post-hoc lock** (`671ed96`, committed 28 s after `8fd4dec` against later reruns and cherry-picking, not a pre-registration); true pre-registrations committed before any episode are the G1 Hard `30-59` extension (`f9fb7a4a`), the OpenCode `--hint gather` test (`fd8c1cb0`), and OpenCode 1.19.5 `gpt-5.5` Hard `0-29` (`cf394894`). On the pre-registered `gpt-5.5` run (`ca0a0dc0`, `n = 30`, `0` infra failures), `gpt-5.5` matches the solver at **`101% [79%, 140%]`** raw (`+0.504 +/- 0.064`, `84% [67%, 103%]` luck-adjusted, `28/28` accusations correct, `2` prose-only non-accusations on seeds `0, 17`), and in the 3-run Harbor 0.26.0 rehearsal on 10 hard judge tasks (`aa1c679e`, where the agent also has a shell used in `20/28` trials), `gemini-4-carbon` scored `93% [20%, 371%]`, `116% [78%, 363%]`, and `131% [86%, 590%]` (`9` valid trials, `+0.626`, `28/29` correct across three runs -- the gap did not reproduce in the judge path).

```bash
python scripts/counterfactual_decomposition_v14.py
python scripts/counterfactual_decomposition_v14.py --check
python scripts/run_all_eval_checks.py --check --only counterfactual_decomposition_v14
```

## 1. Exact Counterfactual Decomposition Identity & Method

Every episode in each `v1.4` cohort is replayed step-by-step in `canary.env.Env(tier, seed)` (enforcing `1bc3e281` `data.detail` step-output compatibility and byte-length verification on client-truncated logs) while stepping `SolverPolicy`'s exact Bayesian belief updater along the agent's own recorded `steps` to evaluate `p_solver(accused | agent_history)`, Shannon entropy `H(agent_history)`, and the public EV stopping threshold `tau = 1 / (1 + known_V)` (`accuse` iff `p_solver >= tau`, else abstain `0.0`).

For every paired seed `i in 0..29`, `Delta_i = solver_score_i - agent_score_i` partitions with zero residual (`|sum - Delta| <= 1e-12` on every seed, cohort mean, and all `10,000` paired bootstrap draws at `seed = 42`):

- **`ev_abstain_rescue` (`a`):** Gain (`-1.0 -> 0.0`, `+1.0 V` on that seed) when the agent made a wrong accusation despite `p_solver(accused | agent_history) < 1 / (1 + known_V)` (negative-EV gamble vetoed).
- **`calibrated_wrong_accuse_residual` (`b`):** `solver_score - agent_score` on wrong accusations where even `p_solver(accused | agent_history) >= 1 / (1 + known_V)` (including 5% canary readout flip traps on Hard).
- **`missed_catch_information_gap` (`c`):** `solver_score - counterfactual_ev_score` (`solver_score - 0.0`) on seeds where the frontier agent abstained or was rescued to `0.0` while `SolverPolicy` caught the culprit via higher-rate posterior-balanced canary partitions.
- **`timing_and_cost_bleed_gap` (`d`):** `solver_score - agent_score` on seeds where both agents caught the culprit, sub-decomposed exactly into `leak_bleed_diff + canary_cost_diff + restriction_cost_diff`.
- **`solver_miss_frontier_catch_offset` (`e`):** `solver_score - agent_score <= 0` on seeds where the frontier agent caught the culprit while `SolverPolicy` abstained (Medium seeds `20, 21, 29`) or suffered a 5% flip (Hard seed `15`; `0.000` on `opencode-gemini-4-carbon` Hard).

## 2. 7-Cohort Paired Gap Decomposition (`n = 30` Seeds `0-29`, 10,000 Paired Bootstrap CIs, `seed = 42`)

| Cohort | Tier | Agent | Solver | `Delta (S - A)` `[95% CI]` | `(a)` EV Rescue `[95% CI]` | `(b)` Cal. Wrong `[95% CI]` | `(c)` Info Gap `[95% CI]` | `(d)` Bleed/Cost `[95% CI]` | `(e)` Solver-Miss Offset |
|---|---|---:|---:|---|---|---|---|---|---:|
| `opencode-gemini-4-carbon` | `hard` | `+0.322` | `+0.499` | `+0.177 [+0.003, +0.383]` | `+0.033 [+0.000, +0.100]` | `+0.113 [+0.000, +0.282]` | `+0.038 [+0.000, +0.097]` | `-0.007 [-0.074, +0.059]` | `+0.000` |
| `inproc-gemini-4-carbon` | `hard` | `+0.473` | `+0.499` | `+0.026 [-0.154, +0.210]` | `+0.033 [+0.000, +0.100]` | `+0.000 [+0.000, +0.000]` | `+0.047 [+0.000, +0.117]` | `+0.001 [-0.079, +0.080]` | `-0.055` |
| `opencode-gemini-3.5-flash` | `hard` | `+0.373` | `+0.499` | `+0.126 [-0.092, +0.348]` | `+0.100 [+0.000, +0.233]` | `+0.000 [+0.000, +0.000]` | `+0.054 [+0.000, +0.126]` | `+0.028 [-0.045, +0.108]` | `-0.056` |
| `opencode-gemini-4-carbon` | `medium` | `+0.713` | `+0.645` | `-0.068 [-0.154, +0.007]` | `+0.000 [+0.000, +0.000]` | `+0.000 [+0.000, +0.000]` | `+0.000 [+0.000, +0.000]` | `-0.007 [-0.051, +0.036]` | `-0.061` |
| `inproc-gemini-4-carbon` | `medium` | `+0.530` | `+0.645` | `+0.115 [-0.042, +0.292]` | `+0.033 [+0.000, +0.100]` | `+0.000 [+0.000, +0.000]` | `+0.124 [+0.027, +0.233]` | `+0.017 [-0.027, +0.064]` | `-0.060` |
| `opencode-gemini-3.5-flash` *(rep)* | `medium` | `+0.434` | `+0.645` | `+0.211 [-0.021, +0.467]` | `+0.167 [+0.033, +0.300]` | `+0.000 [+0.000, +0.000]` | `+0.106 [+0.025, +0.211]` | `-0.009 [-0.052, +0.033]` | `-0.053` |
| `opencode-gpt-5.5` *(pre-reg)* | `hard` | `+0.504` | `+0.499` | `-0.005 [-0.153, +0.120]` | `+0.000 [+0.000, +0.000]` | `+0.000 [+0.000, +0.000]` | `+0.047 [+0.000, +0.120]` | `+0.001 [-0.067, +0.067]` | `-0.052` |

*Note:* `opencode-gemini-3.5-flash` Medium (`*(rep)*`) is the 3-shard FR8 replication (`d4bc4f3d`, seed 28 rerun); `opencode-gpt-5.5` Hard (`*(pre-reg)*`) is the pre-registered OpenCode 1.19.5 second-family cohort (`cf394894` / `ca0a0dc0`). Optional probe directories `inproc-grok-4.20-beta`, `opencode-grok-4.20-beta`, `opencode-gemini-4-argon`, and `opencode-gemini-4-hydrogen` have no committed `0-29` `v1.4` directory; deterministic `grok_tactics` on `0-29` is decomposed in Section 4 below.

## 3. Posterior Calibration, Entropy, Bleed Sub-Accounting & Blind EV-Gate Counterfactual

| Cohort (`tier`) | Acc / Wrong / Abst | Sub-`tau` Gambles (W / Lucky) | Mean `p_solver` vs `tau` | Mean `H` (bits) | Joint-Catch Leak / Canary / Restrict Diff | Blind EV-Gate Mean (`Gain [95% CI]`) |
|---|---|---|---|---:|---|---|
| `opencode-gemini-4-carbon` (`hard`) | `29 / 4 / 1` | `3` (`1W / 2L`) | `0.882` vs `0.639` | `0.647` | `+0.043 / -0.054 / +0.003` | `+0.343` (`+0.020 [-0.028, +0.100]`) |
| `inproc-gemini-4-carbon` (`hard`) | `29 / 1 / 1` | `3` (`1W / 2L`) | `0.930` vs `0.640` | `0.431` | `+0.053 / -0.055 / +0.003` | `+0.486` (`+0.013 [-0.050, +0.097]`) |
| `opencode-gemini-3.5-flash` (`hard`) | `30 / 3 / 0` | `10` (`3W / 7L`) | `0.710` vs `0.654` | `0.963` | `+0.040 / -0.012 / +0.000` | `+0.388` (`+0.015 [-0.109, +0.158]`) |
| `opencode-gemini-4-carbon` (`medium`) | `30 / 0 / 0` | `2` (`0W / 2L`) | `0.962` vs `0.578` | `0.096` | `+0.000 / -0.009 / +0.002` | `+0.681` (`-0.032 [-0.081, +0.000]`) |
| `inproc-gemini-4-carbon` (`medium`) | `26 / 1 / 4` | `3` (`1W / 2L`) | `0.929` vs `0.593` | `0.386` | `+0.016 / -0.002 / +0.004` | `+0.520` (`-0.011 [-0.097, +0.083]`) |
| `opencode-gemini-3.5-flash` (`medium`) | `30 / 5 / 0` | `6` (`5W / 1L`) | `0.867` vs `0.586` | `0.395` | `-0.012 / +0.003 / +0.000` | `+0.580` (`+0.146 [+0.012, +0.300]`) |
| `opencode-gpt-5.5` (`hard`) | `28 / 0 / 2` | `0` (`0W / 0L`) | `0.940` vs `0.630` | `0.327` | `-0.023 / +0.024 / +0.000` | `+0.504` (`+0.000 [+0.000, +0.000]`) |

**Key mechanistic findings on Hard (`0-29`):**
1. **Why OpenCode `gemini-4-carbon`'s `+0.177 V/ep` (`+5.30 V`) Hard gap is dominated by evidence quality, not bleed:** On the `25` jointly-caught Hard seeds, later accusation leak bleed (`+0.043 V/ep` = `+1.30 V`) is more than offset by unplanted canary cost savings (`-0.054 V/ep` = `-1.61 V`, plus `+0.003 V/ep` = `+0.09 V` restriction cost), yielding `timing_and_cost_bleed_gap = -0.007 V/ep` (`-0.22 V`). Instead, `100%` of the positive gap comes from commitment under thin/noisy evidence: `calibrated_wrong_accuse_residual = +0.113 V/ep` (`+3.38 V` on seeds `1, 26`, with seed `15` tying solver `-1.00 vs -1.00`), `missed_catch_information_gap = +0.038 V/ep` (`+1.14 V`, seed `11` abstained `+0.62 V` + seed `18` `+0.52 V`), and `ev_abstain_rescue = +0.033 V/ep` (`+1.00 V` on seed `18`).
2. **Blind EV-stopping (`accuse` iff `p_solver >= 1 / (1 + known_V)`) raises raw score on all three Gemini Hard cohorts and leaves `gpt-5.5` invariant:** Even after forfeiting lucky sub-threshold catches (`-0.013 V/ep` on `opencode-carbon` seeds `5, 23`; `-0.085 V/ep` across `7` lucky gambles on `opencode-3.5-flash`), enforcing the Bayesian EV threshold raises `opencode-carbon` `+0.322 -> +0.343`, `inproc-carbon` `+0.473 -> +0.486`, and `opencode-3.5-flash` `+0.373 -> +0.388` (`+0.434 -> +0.580`, `+0.146 V/ep` gain on Medium), while `opencode-gpt-5.5` is unchanged (`+0.504 -> +0.504`, `0` sub-threshold gambles across all `28` accusations).
3. **Cross-family contrast (`gemini-4-carbon` `65%` vs `gpt-5.5` `101%` on identical MCP tools):** `opencode-gpt-5.5` records `ev_abstain_rescue = 0.000` and `calibrated_wrong_accuse_residual = 0.000` (`28/28` correct, mean `p_solver = 0.940`, mean `H = 0.327` bits vs `opencode-carbon`'s `0.647` bits); its `+0.047 V/ep` (`+1.41 V`) `missed_catch_information_gap` arises solely on seeds `0` (`p_top = 0.9487`) and `17` (`p_top = 0.9634`) where it named the culprit in prose without calling `accuse`, balanced by `-0.052 V/ep` (`-1.57 V`) `solver_miss_frontier_catch_offset` on seed `15` (`+0.57` vs solver `-1.00`) and `+0.001 V/ep` net bleed/cost (`-0.023` faster leak containment vs `+0.024` higher canary spend).

### 3.1 Hard Seed Forensics: Seed 6 vs Seed 26 (5% S1 Flip) vs Seed 18

| Cohort | Seed | Decision (Day) | Score vs Solver | `p_solver` vs `tau` (`known_V`) | `H` (bits) | Surfaced 5% Flip | Decomposition Regime | Active Term(s) |
|---|---:|---|---|---|---:|---|---|---|
| `opencode-gemini-4-carbon` | `6` | accuse `e34` (d6) | `+0.73` vs `+0.71` | `0.9981` vs `0.5780` (`0.73`) | `0.021` | none | `both_caught` | `d=-0.02` |
| `opencode-gemini-4-carbon` | `18` | accuse `e29` (d18) | `-1.00` vs `+0.52` | `0.6272` vs `0.6623` (`0.51`) | `1.806` | none | `rescued_wrong_accuse_solver_caught` | `a=+1.00`, `c=+0.52` |
| `opencode-gemini-4-carbon` | `26` | accuse `e04` (d10) | `-1.00` vs `+0.69` | `0.9504` vs `0.5988` (`0.67`) | `0.371` | `c6-2` `S1!=S3` | `calibrated_wrong_accuse` | `b=+1.69` |
| `inproc-gemini-4-carbon` | `6` | accuse `e18` (d15) | `-1.00` vs `+0.71` | `0.6295` vs `0.6452` (`0.55`) | `1.616` | `c4-2` `Z!=Y` | `rescued_wrong_accuse_solver_caught` | `a=+1.00`, `c=+0.71` |
| `inproc-gemini-4-carbon` | `18` | accuse `e27` (d14) | `+0.55` vs `+0.52` | `0.9857` vs `0.6250` (`0.60`) | `0.139` | none | `both_caught` | `d=-0.03` |
| `inproc-gemini-4-carbon` | `26` | abstain (d21) | `+0.00` vs `+0.69` | `None` (`p_top=0.3793`) vs `0.6849` (`0.46`) | `2.414` | `c4` `v2!=v1` | `frontier_abstained_solver_caught` | `c=+0.69` |
| `opencode-gemini-3.5-flash` | `6` | accuse `e34` (d6) | `+0.78` vs `+0.71` | `0.9546` vs `0.5618` (`0.78`) | `0.338` | none | `both_caught` | `d=-0.07` |
| `opencode-gemini-3.5-flash` | `18` | accuse `e27` (d16) | `+0.46` vs `+0.52` | `0.2898` vs `0.6410` (`0.56`) | `2.355` | none | `both_caught` | `d=+0.06` |
| `opencode-gemini-3.5-flash` | `26` | accuse `e38` (d19) | `-1.00` vs `+0.69` | `0.1000` vs `0.7874` (`0.27`) | `3.322` | `c3-2` `finance!=research` | `rescued_wrong_accuse_solver_caught` | `a=+1.00`, `c=+0.69` |
| `opencode-gpt-5.5` | `6` | accuse `e34` (d6) | `+0.75` vs `+0.71` | `0.9572` vs `0.5714` (`0.75`) | `0.322` | none | `both_caught` | `d=-0.04` |
| `opencode-gpt-5.5` | `18` | accuse `e27` (d14) | `+0.48` vs `+0.52` | `1.0000` vs `0.6536` (`0.53`) | `0.000` | `c8-2` `C!=B` | `both_caught` | `d=+0.04` |
| `opencode-gpt-5.5` | `26` | accuse `e08` (d10) | `+0.62` vs `+0.69` | `0.9817` vs `0.6173` (`0.62`) | `0.150` | none | `both_caught` | `d=+0.07` |

## 4. Scripted Baseline Reference Decomposition (`grok_tactics`) & Regret Cross-Checks

| Baseline Cohort | Tier | Score | Solver | `Delta` | `(a)` EV Rescue | `(b)` Cal. Wrong | `(c)` Info Gap | `(d)` Bleed/Cost | `(e)` Offset |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `grok_tactics` | `hard` | `+0.432` | `+0.499` | `+0.067` | `+0.000` | `+0.000` | `+0.015` | `+0.101` | `-0.048` |
| `grok_tactics` | `medium` | `+0.460` | `+0.645` | `+0.185` | `+0.000` | `+0.000` | `+0.187` | `+0.054` | `-0.056` |

**Committed per-decision regret cross-checks (`0` discrepancies):** Verified exact parity against `results/regret_opencode-gemini-4-carbon-v1.4.json` (Hard: `mean_score = +0.3223`, `mean_p_correct = 0.8819`, `premature_accusation = 2` losing `0.8044 V`, `no_accusation = 1`; Medium: `mean_score = +0.7130`, `mean_p_correct = 0.9615`, `premature_accusation = 1` losing `0.1567 V`) and `results/regret_inproc-gemini-4-carbon-v1.4.json` (Hard: `mean_score = +0.4730`, `mean_p_correct = 0.9299`, `premature_accusation = 1` losing `0.5889 V`, `no_accusation = 1`; Medium: `mean_score = +0.5303`, `mean_p_correct = 0.9286`, `premature_accusation = 3` losing `1.2919 V`, `no_accusation = 4`), including every `top5` accusation decision regret to `1e-6`.
