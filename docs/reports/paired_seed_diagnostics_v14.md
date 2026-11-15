# Canary v1.4 Paired-Seed Diagnostics, Covariance Proof & World-Difficulty Atlas

**Honest headline framing (`c59ecfd0` / `ca0a0dc0` / `aa1c679e` / `5f9b3297`):** (1) On `v1.4` Hard with **MCP tools only** on post-hoc locked dev `seeds 0-29` (`n = 30`), `opencode:google/gemini-4-carbon` scores `+0.322` vs `solver` `+0.499` = **`64.6%` `[23.8%, 98.3%]` raw** (`65% [24%, 98%]`) and **`72.0%` `[51.7%, 91.2%]` luck-adjusted** (`72% [52%, 91%]`). (2) In the **Harbor judge-path rehearsal** (`results/harbor/rehearsal/TABLE.md`, tag `afterquery-final` `1bc3e281`, where the container also provides `bash`/`python3` and carries the 15 Nov updates), **that gap did not reproduce**: three runs on hard judge tasks `900000-900009` (`28 / 29` valid Gemini accusations correct) scored `+0.472` (`93%` of oracle `+0.506`, `n = 10`), `+0.585` (`116%`, `n = 10`), and `+0.626` (`131%` `[86%, 590%]` of same-task oracle, `n = 9` valid, `1` infra-excluded; corrected in `aa1c679e` / `5f9b3297` from the `08:52` partial `n = 7` `+0.656` / `153%` snapshot, full trials on `s1-rehearsal-final` `d0ead011`), while `do_nothing` and `stop_early` scored `+0.000` (`10/10`). (3) The pre-registered second frontier family **`opencode:openai/gpt-5.5`** (`cf394894` / `ca0a0dc0`, MCP tools only, dev `seeds 0-29`, `n = 30`) **matches the solver at `100.9%` `[78.6%, 140.3%]` raw** (`101% [79%, 140%]`, `+0.504`) and **`83.7%` `[66.5%, 103.1%]` luck-adjusted** (`84% [67%, 103%]`, `28/28` accusations correct; seeds `[0, 17]` announced an accusation in text without calling `accuse` and scored `0.000`). Frontier agents on `v1.4` Hard therefore land near the reference overall; this atlas diagnoses both frontier families (`gemini-4-carbon` and `gpt-5.5`) side-by-side against `solver` on every seed `0..29`.

**Reproduce and verify (<10 s, 0 API calls, 0 keys):**

```bash
/tmp/fleet-silas/shared/agent-arena-venv/bin/python scripts/paired_seed_diagnostics_v14.py
/tmp/fleet-silas/shared/agent-arena-venv/bin/python scripts/paired_seed_diagnostics_v14.py --check
```

## 1. Scope, Replay Integrity & Panel Fix A/D Disclosures

- **100% step-level `Env(tier, seed)` replay (`1bc3e281` compatible):** Verified `332` total episodes (`272` committed JSONL episodes + `60` deterministic `grok_tactics` episodes) and `26995` tool-call steps (`120` pre-`1bc3e281` `invalid arguments` steps normalized for `data.detail`, `2` truncated MCP responses byte-verified, `0` mismatches).
- **Post-hoc seed lock (`671ed96`) vs pre-registered runs (`cf394894`, `f9fb7a4a`):** Primary `seeds 0-29` (`n = 30` per tier) is a **post-hoc lock** committed in `671ed96` **28 seconds after** the primary Gemini runs landed in `8fd4dec` (preventing reruns or cherry-picking, **not** a pre-registration). By contrast, `opencode:openai/gpt-5.5` on Hard `seeds 0-29` (`cf394894` before `ca0a0dc0`), the G1 `30-59` extension (`f9fb7a4a` before `364fe657`), and the Harbor judge rehearsal (`results/harbor/rehearsal/README.md` before `c59ecfd0`) were pre-registered prior to episode execution.
- **`20 + 10` reference solver directories (`0..29` strict filter):** Primary `SolverPolicy` baselines load `solver-{medium,hard}-20261114-121126` (`0..19`) plus `solver-{medium,hard}-seeds20to29` (`20..29`), strictly excluding `solver-hard-seeds30to59` so `30..59` never enters any primary `0..29` denominator.
- **Hard `access_constraints` W4 no-op & `0dc7d140` / `1bc3e281` disclosures:** On `v1.4` Hard (`N = 40`), `access_constraints = True`, `canary_level = 1`, and staff clearances span `1..3`, so every staff member qualifies for every canary and the clearance constraint never binds (`docs/DIFFICULTY.md` W4, `0dc7d140`, which also discloses Harbor `bash`/`python3` vs local OpenCode MCP `*`: `deny`, `canary_*`: `allow`). Commit `1bc3e281` (Panel Fix D) added public-only `data.detail` strings to `invalid arguments` errors and reworded the careful-mole `W1` sentence after the committed Gemini runs (`opencode:openai/gpt-5.5` ran on `afterquery-final` `1bc3e281` under OpenCode `1.19.5`).
- **Zero secret or staff-ID leakage:** Neither this report nor `results/eval_v14/paired_seed_diagnostics_v14.json` emits any culprit/staff identifier strings or forbidden culprit keys; every per-episode diagnostic uses boolean indicators (`correct`, `accused_present`, `mole_in_strict_consistent_set`), integer cardinalities (`consistent_set_size`), and calibrated probabilities (`p_accused`, `p_top`, `break_even_p`).

## 2. Cohort Summary Across Paired Seeds `0..29` (`n = 30` per Cohort)

| Tier | Cohort | Raw Mean | Luck-Adj Mean | Raw / Solver | Luck-Adj / Solver | Acc. | Accused | Mean Acc. Day | Mean `P(acc)` | Mean `P*` | Mean `V_true` (`V_shown`) | Mean Canaries | Mean Interviews | `|C|=1` | Surfaced Flips |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|---:|---:|---:|---:|
| `hard` | `opencode_carbon` | `+0.322` | `+0.360` | `64.6%` | `72.0%` | `0.833` | `0.97` | `13.2` | `0.882` | `0.662` | `0.531` (`0.568`) | `8.47` | `68.0` | `20/30` | `2` |
| `hard` | `opencode_gpt55` | `+0.504` | `+0.418` | `100.9%` | `83.7%` | `0.933` | `0.93` | `10.2` | `0.940` | `0.650` | `0.547` (`0.600`) | `17.13` | `4.1` | `24/30` | `1` |
| `hard` | `inproc_carbon` | `+0.473` | `+0.421` | `94.8%` | `84.3%` | `0.933` | `0.97` | `12.7` | `0.930` | `0.658` | `0.535` (`0.573`) | `8.57` | `57.3` | `21/30` | `4` |
| `hard` | `opencode_flash` | `+0.373` | `+0.110` | `74.7%` | `22.0%` | `0.900` | `1.00` | `12.7` | `0.710` | `0.675` | `0.505` (`0.551`) | `12.43` | `0.7` | `21/30` | `2` |
| `hard` | `grok_tactics` | `+0.432` | `+0.384` | `86.5%` | `77.0%` | `0.933` | `0.93` | `10.4` | `0.964` | `0.719` | `0.432` (`0.463`) | `20.27` | `0.0` | `28/30` | `0` |
| `hard` | `solver` | `+0.499` | `+0.499` | `100.0% (ref)` | `100.0% (ref)` | `0.967` | `1.00` | `10.6` | `0.965` | `0.653` | `0.554` (`0.609`) | `14.13` | `0.0` | `26/30` | `2` |
| `medium` | `opencode_carbon` | `+0.713` | `+0.652` | `110.5%` | `101.1%` | `1.000` | `1.00` | `8.0` | `0.962` | `0.587` | `0.713` (`0.737`) | `5.83` | `37.5` | `27/30` | `0` |
| `medium` | `inproc_carbon` | `+0.530` | `+0.479` | `82.2%` | `74.3%` | `0.833` | `0.87` | `9.0` | `0.929` | `0.608` | `0.654` (`0.684`) | `6.93` | `47.2` | `22/30` | `0` |
| `medium` | `grok_tactics` | `+0.460` | `+0.460` | `71.3%` | `71.3%` | `0.700` | `0.70` | `7.7` | `1.000` | `0.649` | `0.567` (`0.593`) | `8.87` | `0.0` | `21/30` | `0` |
| `medium` | `solver` | `+0.645` | `+0.645` | `100.0% (ref)` | `100.0% (ref)` | `0.900` | `0.90` | `7.6` | `1.000` | `0.594` | `0.695` (`0.714`) | `7.30` | `0.0` | `26/30` | `0` |

- **Decision-level contrast (`gemini-4-carbon` vs `gpt-5.5` vs `solver` on Hard `0..29`, matching `results/behaviour_compare_v1.4.md`):** With the exact same 13 MCP tools, `opencode_gpt55` plants `17.13` accepted canaries per episode (`17.2` total `plant_canary` calls), runs `4.1` accepted interviews (`4.2` calls, `6%` of calls), isolates `|C| = 1` on `24/30` seeds, and accuses at mean day `10.25` with `0` wrong accusations (`28/28`), matching `solver` (`14.13` canaries, `0.0` interviews, day `10.6`). By contrast, `opencode_carbon` plants `8.47` accepted canaries (`8.5` calls), spends `68.0` accepted interviews (`68.0` calls, `53%` of calls at stated LR `1.2`), accuses later at day `13.2`, and incurs `4` wrong accusations (`-1.0` each).

## 3. Paired vs Unpaired Variance, Covariance & 10,000-Resample Bootstrap CI Proof

For frontier score `F_s` and solver score `S_s` on seed `s in {0..29}`, `Var(F - S) = Var(F) + Var(S) - 2 Cov(F, S)`. Positive world-difficulty covariance `Cov(F_s, S_s) > 0` makes `SE_paired < SE_unpaired`, while Rao-Blackwell luck-adjustment (`P * V - (1 - P)`) removes independent accusation coin-flip variance.

| Tier | Cohort vs Solver | Metric | `r` (Pearson) | `rho` (Spearman) | `Cov(F, S)` | `SE_unp` | `SE_prd` | `SE_unp / SE_prd` | Ratio 95% CI (Unpaired -> Paired) | Ratio Width Reduction | Combined `SE_raw_unp / SE_luck_prd` |
|---|---|---|---:|---:|---:|---:|---:|---:|---|---:|---:|
| `hard` | `opencode_carbon` | `raw` | `+0.341` | `+0.180` | `+0.0632` | `0.1183` | `0.0989` | `1.196x` | `[22.5%, 110.1%] -> [23.8%, 98.3%]` | `1.176x` | -- |
| `hard` | `opencode_carbon` | `luck_adj` | `+0.319` | `+0.387` | `+0.0168` | `0.0627` | `0.0530` | `1.182x` | `[49.6%, 94.7%] -> [51.7%, 91.2%]` | `1.141x` | `2.231x` (`4.98x` var) |
| `hard` | `opencode_gpt55` | `raw` | `-0.113` | `+0.030` | `-0.0067` | `0.0690` | `0.0722` | `0.956x` | `[80.0%, 140.7%] -> [78.6%, 140.3%]` | `0.984x` | -- |
| `hard` | `opencode_gpt55` | `luck_adj` | `-0.033` | `+0.081` | `-0.0012` | `0.0495` | `0.0503` | `0.984x` | `[66.8%, 103.1%] -> [66.5%, 103.1%]` | `0.995x` | `1.371x` (`1.88x` var) |
| `hard` | `inproc_carbon` | `raw` | `-0.199` | `-0.115` | `-0.0219` | `0.0855` | `0.0937` | `0.913x` | `[65.1%, 136.4%] -> [62.2%, 140.0%]` | `0.917x` | -- |
| `hard` | `inproc_carbon` | `luck_adj` | `+0.002` | `+0.046` | `+0.0001` | `0.0549` | `0.0549` | `1.001x` | `[65.0%, 106.4%] -> [65.0%, 105.8%]` | `1.017x` | `1.559x` (`2.43x` var) |
| `hard` | `opencode_flash` | `raw` | `-0.086` | `+0.116` | `-0.0141` | `0.1087` | `0.1130` | `0.962x` | `[36.5%, 119.7%] -> [35.9%, 122.8%]` | `0.956x` | -- |
| `hard` | `opencode_flash` | `luck_adj` | `+0.125` | `+0.274` | `+0.0137` | `0.1165` | `0.1125` | `1.036x` | `[-22.4%, 64.4%] -> [-22.6%, 63.2%]` | `1.011x` | `0.967x` (`0.93x` var) |
| `hard` | `grok_tactics` | `raw` | `+0.160` | `+0.244` | `+0.0127` | `0.0747` | `0.0688` | `1.086x` | `[64.9%, 122.4%] -> [66.8%, 119.3%]` | `1.097x` | -- |
| `hard` | `grok_tactics` | `luck_adj` | `+0.329` | `+0.326` | `+0.0141` | `0.0547` | `0.0452` | `1.208x` | `[58.7%, 98.3%] -> [61.0%, 94.6%]` | `1.179x` | `1.652x` (`2.73x` var) |
| `medium` | `opencode_carbon` | `raw` | `+0.395` | `+0.365` | `+0.0113` | `0.0493` | `0.0410` | `1.203x` | `[96.9%, 129.7%] -> [99.3%, 127.0%]` | `1.186x` | -- |
| `medium` | `opencode_carbon` | `luck_adj` | `+0.295` | `+0.217` | `+0.0179` | `0.0637` | `0.0535` | `1.191x` | `[83.0%, 122.4%] -> [85.3%, 118.6%]` | `1.184x` | `0.923x` (`0.85x` var) |
| `medium` | `inproc_carbon` | `raw` | `-0.087` | `+0.035` | `-0.0082` | `0.0834` | `0.0866` | `0.963x` | `[57.1%, 106.5%] -> [56.4%, 107.6%]` | `0.965x` | -- |
| `medium` | `inproc_carbon` | `luck_adj` | `-0.240` | `-0.265` | `-0.0202` | `0.0771` | `0.0854` | `0.903x` | `[53.1%, 96.8%] -> [51.7%, 99.1%]` | `0.923x` | `0.977x` (`0.95x` var) |
| `medium` | `grok_tactics` | `raw` | `-0.017` | `+0.076` | `-0.0014` | `0.0771` | `0.0777` | `0.992x` | `[51.2%, 94.5%] -> [50.9%, 94.5%]` | `0.994x` | -- |
| `medium` | `grok_tactics` | `luck_adj` | `-0.017` | `+0.076` | `-0.0014` | `0.0771` | `0.0777` | `0.992x` | `[51.2%, 94.5%] -> [50.9%, 94.5%]` | `0.994x` | `0.992x` (`0.98x` var) |

- **Why MCP-only Hard `opencode_carbon` CIs tighten by `2.231x` in SE (`4.98x` in variance):** Unpaired raw `SE(F - S)` is `0.1183`. Pairing on `0..29` captures `Pearson r = +0.341` (`Cov = +0.0632`), reducing raw SE by `1.196x` to `0.0989`. Applying Rao-Blackwell luck-adjustment strips conditional Bernoulli coin-flip noise and raises paired correlation to `r = +0.319` (`SE_unpaired / SE_paired = 1.182x`), tightening SE all the way to `0.0530` and shrinking the 10,000-resample ratio 95% CI width from `87.7` pp (unpaired raw) to `39.5` pp (paired luck-adjusted, `2.22x` narrower).
- **Second frontier family `opencode_gpt55` covariance & precision (`100.9%` `[78.6%, 140.3%]` raw, `83.7%` `[66.5%, 103.1%]` luck-adjusted):** `opencode_gpt55` has much lower per-seed raw variance (`Var = 0.0318`) than `solver` (`Var = 0.1111`) because `gpt-5.5` incurred `0` wrong accusations while `solver` suffered one `-1.000` 5% flip on seed `15`. Because `gpt-5.5` won on seed `15` (`+0.570`) and stopped without calling `accuse` (`0.000`) on seeds `0` and `17` where `solver` scored `+0.640` and `+0.770`, raw `Cov(F, S) = -0.0067` (`Spearman rho = +0.030`); under luck-adjustment, `Cov(F, S)` moves to `-0.0012` (`rho = +0.081`), tightening `SE` by `1.371x` (`0.0690 -> 0.0503`) and narrowing the ratio 95% CI width by `1.66x` (`60.7` pp -> `36.5` pp).
- **Why `inproc_carbon` and `opencode_flash` show slightly negative raw covariance (`-0.0219`, `-0.0141`) that disappears under luck-adjustment (`+0.0001`, `+0.0137`):** On Hard seed `15`, `solver` hit a 5% canary variant flip (`score = -1.000`, `luck_adjusted = +0.433`) while `inproc_carbon` (`+0.650`) and `opencode_flash` (`+0.690`) did not flip. Replacing realized coin flips with posterior expectations restores positive/neutral world-difficulty covariance.

## 4. World-Difficulty Stratification (`30` Hard Worlds & `30` Medium Worlds)

### 4.1 Solver Isolation-Day Tertiles (`fast_t1`, `mid_t2`, `slow_t3`, `10` Worlds Each)

| Tier | Stratum (`n = 10`) | Seeds | Solver Raw (LA) | `opencode_carbon` Raw (LA) | `opencode_gpt55` Raw (LA) | `inproc_carbon` Raw (LA) | `opencode_flash` Raw (LA) | `grok_tactics` Raw (LA) |
|---|---|---|---|---|---|---|---|---|
| `hard` | `fast_t1` | `1,2,6,9,16,17,25,26,27,28` | `+0.689` (`+0.656`) | `+0.287` (`+0.550`) | `+0.514` (`+0.462`) | `+0.348` (`+0.430`) | `+0.351` (`+0.049`) | `+0.508` (`+0.475`) |
| `hard` | `mid_t2` | `5,7,11,14,15,18,19,20,21,24` | `+0.377` (`+0.485`) | `+0.220` (`+0.230`) | `+0.511` (`+0.372`) | `+0.478` (`+0.353`) | `+0.407` (`+0.266`) | `+0.332` (`+0.273`) |
| `hard` | `slow_t3` | `0,3,4,8,10,12,13,22,23,29` | `+0.431` (`+0.358`) | `+0.460` (`+0.299`) | `+0.486` (`+0.419`) | `+0.593` (`+0.480`) | `+0.361` (`+0.015`) | `+0.455` (`+0.406`) |
| `medium` | `fast_t1` | `0,2,5,6,8,9,11,13,18,26` | `+0.798` (`+0.798`) | `+0.772` (`+0.772`) | n/a | `+0.434` (`+0.345`) | n/a | `+0.412` (`+0.412`) |
| `medium` | `mid_t2` | `3,4,7,10,14,15,16,19,22,28` | `+0.715` (`+0.715`) | `+0.684` (`+0.628`) | n/a | `+0.552` (`+0.552`) | n/a | `+0.554` (`+0.554`) |
| `medium` | `slow_t3` | `1,12,17,20,21,23,24,25,27,29` | `+0.422` (`+0.422`) | `+0.683` (`+0.555`) | n/a | `+0.605` (`+0.540`) | n/a | `+0.414` (`+0.414`) |

### 4.2 Exogenous Regular-Doc Leak Rate, Hard 5%-Flip Worlds & Winnability (`solver > 0` vs `solver <= 0`)

| Tier | Stratification Axis | Stratum (`n`) | Solver Raw (LA) | `opencode_carbon` Raw /LA (`% Solver LA`) | `opencode_gpt55` Raw /LA (`% Solver LA`) | `inproc_carbon` Raw /LA (`% Solver LA`) | `opencode_flash` Raw /LA (`% Solver LA`) |
|---|---|---|---|---|---|---|---|
| `hard` | Intrinsic regular leak rate | `low_leak_half` (`n=15`) | `+0.437` (`+0.502`) | `+0.247` / `+0.376` (`75.0%`) | `+0.507` / `+0.444` (`88.4%`) | `+0.604` / `+0.511` (`101.9%`) | `+0.497` / `+0.175` (`34.9%`) |
| `hard` | Intrinsic regular leak rate | `high_leak_half` (`n=15`) | `+0.561` (`+0.497`) | `+0.397` / `+0.343` (`69.0%`) | `+0.501` / `+0.392` (`78.8%`) | `+0.342` / `+0.331` (`66.6%`) | `+0.249` / `+0.045` (`9.0%`) |
| `hard` | Winnability | `winnable_solver_gt_0` (`n=29`) | `+0.551` (`+0.502`) | `+0.368` / `+0.360` (`71.7%`) | `+0.501` / `+0.415` (`82.7%`) | `+0.467` / `+0.416` (`82.9%`) | `+0.362` / `+0.094` (`18.7%`) |
| `hard` | Winnability | `non_winnable_solver_le_0` (`n=1`) | `-1.000` (`+0.433`) | `-1.000` / `+0.360` (`83.2%`) | `+0.570` / `+0.501` (`115.6%`) | `+0.650` / `+0.579` (`133.6%`) | `+0.690` / `+0.577` (`133.1%`) |
| `hard` | 5% flip (solver world) | `solver_flip_worlds` (`n=2`) | `-0.135` (`+0.582`) | `-0.300` / `+0.375` (`64.4%`) | `+0.645` / `+0.597` (`102.6%`) | `+0.705` / `+0.642` (`110.4%`) | `+0.695` / `+0.626` (`107.6%`) |
| `hard` | 5% flip (solver world) | `solver_no_flip_worlds` (`n=28`) | `+0.544` (`+0.493`) | `+0.367` / `+0.358` (`72.7%`) | `+0.494` / `+0.405` (`82.1%`) | `+0.456` / `+0.405` (`82.1%`) | `+0.350` / `+0.073` (`14.8%`) |
| `hard` | 5% flip (any cohort) | `any_cohort_flip_worlds` (`n=9`) | `+0.420` (`+0.545`) | `-0.179` / `+0.288` (`52.8%`) | `+0.489` / `+0.406` (`74.6%`) | `+0.308` / `+0.379` (`69.5%`) | `+0.343` / `+0.037` (`6.7%`) |
| `hard` | 5% flip (any cohort) | `zero_cohort_flip_worlds` (`n=21`) | `+0.533` (`+0.480`) | `+0.537` / `+0.390` (`81.3%`) | `+0.510` / `+0.423` (`88.1%`) | `+0.544` / `+0.439` (`91.5%`) | `+0.386` / `+0.141` (`29.4%`) |
| `medium` | Intrinsic regular leak rate | `low_leak_half` (`n=15`) | `+0.703` (`+0.703`) | `+0.721` / `+0.642` (`91.4%`) | n/a | `+0.502` / `+0.342` (`48.7%`) | n/a |
| `medium` | Intrinsic regular leak rate | `high_leak_half` (`n=15`) | `+0.587` (`+0.587`) | `+0.705` / `+0.661` (`112.6%`) | n/a | `+0.559` / `+0.616` (`104.9%`) | n/a |
| `medium` | Winnability | `winnable_solver_gt_0` (`n=27`) | `+0.717` (`+0.717`) | `+0.725` / `+0.681` (`95.0%`) | n/a | `+0.523` / `+0.466` (`65.0%`) | n/a |
| `medium` | Winnability | `non_winnable_solver_le_0` (`n=3`) | `+0.000` (`+0.000`) | `+0.607` / `+0.390` (`n/a`) | n/a | `+0.600` / `+0.600` (`n/a`) | n/a |

- **Non-winnable seed reconciliation (`solver <= 0`):** On Hard, only seed `15` has `solver <= 0` (`solver` suffered a 5% canary flip and scored `-1.000`, `luck_adjusted = +0.433`); excluding seed `15` (`winnable_n = 29`) moves raw ratios to `66.8%` (`opencode_carbon`), `91.0%` (`opencode_gpt55`), `84.8%` (`inproc_carbon`), and `65.7%` (`opencode_flash`), aligning raw ratios closely with 30-seed luck-adjusted ratios (`72.0%`, `83.7%`, `84.3%`, `22.0%`). On Medium, `solver <= 0` occurs on seeds `[20, 21, 29]` where `solver` conservatively abstained (`0.000`); on the `27` winnable seeds `opencode_carbon` scores `101.1%` of `solver` raw (`101.1%` 30-seed luck-adjusted).

## 5. Complete Episode Outcome Taxonomy Across Cohorts (`n = 30` per Cohort)

| Tier | Cohort | `isolated_c1_win` | `unresolved_lucky_win` | `sub_breakeven_gamble_win` | `sub_breakeven_gamble_loss` | `5pct_flip_singleton_trap` | `unresolved_premature_loss` | `horizon_abstain` |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| `hard` | `opencode_carbon` | `18` | `5` | `2` | `1` | `2` | `1` | `1` |
| `hard` | `opencode_gpt55` | `23` (`1` `|C|=0`) | `4` | `1` | `0` | `0` | `0` | `2` (`2` no-call) |
| `hard` | `inproc_carbon` | `22` (`1` `|C|=0`) | `4` | `2` | `1` | `0` | `0` | `1` |
| `hard` | `opencode_flash` | `19` | `1` | `7` | `3` | `0` | `0` | `0` |
| `hard` | `grok_tactics` | `28` | `0` | `0` | `0` | `0` | `0` | `2` |
| `hard` | `solver` | `26` (`1` `|C|=0`) | `3` | `0` | `0` | `1` | `0` | `0` |
| `medium` | `opencode_carbon` | `27` | `1` | `2` | `0` | `0` | `0` | `0` |
| `medium` | `inproc_carbon` | `22` | `1` | `2` | `1` | `0` | `0` | `4` |
| `medium` | `grok_tactics` | `21` | `0` | `0` | `0` | `0` | `0` | `9` |
| `medium` | `solver` | `26` | `1` | `0` | `0` | `0` | `0` | `3` |

- **Key taxonomy highlights (Hard `0..29`):**
  - `opencode_carbon` (`25` wins, `4` losses, `1` abstain): `18` `isolated_c1_win`, `5` `unresolved_lucky_win` (`seeds [3, 7, 8, 14, 20]`), `2` `sub_breakeven_gamble_win` (`seeds [5, 23]` at `P = 0.510 < P* = 0.862` and `P = 0.452 < P* = 0.813`), `1` `sub_breakeven_gamble_loss` (`seed [18]` at `P = 0.627 < P* = 0.685`), `2` `5pct_flip_singleton_trap` (`seeds [1, 26]` at `P = 0.988, 0.950`), `1` `unresolved_premature_loss` (`seed [15]` at `|C| = 2, P = 0.805 >= P* = 0.592`), and `1` `horizon_abstain` (`seed [11]`). Total `|C| >= 2` accusations = `9/29`, matching `docs/DIFFICULTY.md`.
  - `opencode_gpt55` (`28` wins, `0` losses, `2` no-accusation stops): `23` `isolated_c1_win` (including noisy-Bayes recovery from a 5% canary flip on `seed [18]` at `|C| = 0, P = 1.000 >= P* = 0.676`), `4` `unresolved_lucky_win` (`seeds [7, 16, 21, 23]` at `P = 0.740..0.884 > P*`), `1` `sub_breakeven_gamble_win` (`seed [5]` at `P = 0.664 < P* = 0.709`), `0` wrong accusations across all `30` seeds, and `2` no-accusation episodes (`seeds [0, 17]`, stopped at days `8` and `9` with `|C| = 1` containing the true culprit after writing an accusation in text without calling `accuse`, scoring `0.000` as valid per `ca0a0dc0`).
  - `inproc_carbon` (`28` wins, `1` loss, `1` abstain): recovers from 5% canary flips via noisy-Bayes likelihood tracking on `seed [3]` (`|C| = 0, P = 0.985 >= P* = 0.629`, `isolated_c1_win`) and `seed [5]` (`|C| = 0, P = 0.901 < P* = 0.909` at `V = 0.10`, classified under `sub_breakeven_gamble_win` alongside `seed [22]`), suffers `1` `sub_breakeven_gamble_loss` (`seed [6]`), and abstains on `seed [26]` after a flip.
  - `opencode_flash` (`27` wins, `3` losses, `0` abstains): `7` `sub_breakeven_gamble_win` (`seeds [0, 2, 3, 17, 18, 23, 27]`) + `3` `sub_breakeven_gamble_loss` (`seeds [10, 21, 26]`) = `10/30` negative-EV horizon gambles, explaining why its `74.7%` raw ratio collapses to `22.0%` luck-adjusted.

## 6. Separate G1 Pre-Registered Extension Diagnostic Block (`seeds [34, 37]`)

Pre-registered in `f9fb7a4a` (data committed in `364fe657`, stopped early after `2` completed valid episodes to preserve shared Gemini rehearsal quota) and paired against `data/runs/committed/v1.4/reference/solver-hard-seeds30to59/episodes.jsonl` without ever mixing into primary `0..29`:

| Seed | Cohort | Score | Luck-Adj | Correct | Accused | `|C|` | Culprit in `C` | `P(acc)` | `P(top)` | `P*` | `V_true` (`V_shown`) | Day | Canaries | Interviews | Surfaced Leaks (Flips) | Outcome Class |
|---:|---|---:|---:|---|---|---:|---|---:|---:|---:|---|---:|---:|---:|---|---:|
| `34` | opencode:gemini-4-carbon (ext) | `+0.79` | `+0.752` | `true` | `true` | `1` | `true` | `0.979` | `0.979` | `0.559` | `0.79` (`0.79`) | `5` | `6` | `26` | `3` (`0`) | `isolated_c1_win` |
| `37` | opencode:gemini-4-carbon (ext) | `+0.70` | `+0.668` | `true` | `true` | `1` | `true` | `0.981` | `0.981` | `0.588` | `0.70` (`0.75`) | `6` | `5` | `32` | `4` (`0`) | `isolated_c1_win` |
| `34` | solver (seeds30to59) | `+0.70` | `+0.663` | `true` | `true` | `1` | `true` | `0.978` | `0.978` | `0.588` | `0.70` (`0.75`) | `6` | `10` | `0` | `3` (`0`) | `isolated_c1_win` |
| `37` | solver (seeds30to59) | `+0.77` | `+0.635` | `true` | `true` | `1` | `true` | `0.924` | `0.924` | `0.565` | `0.77` (`0.82`) | `5` | `8` | `0` | `2` (`0`) | `isolated_c1_win` |

- **`[34, 37]` 2-seed summary:** OpenCode `gemini-4-carbon` averages `+0.745` raw (`+0.710` luck-adjusted) vs paired `solver` `+0.735` raw (`+0.649` luck-adjusted; full 30-seed `solver-hard-seeds30to59` raw mean `+0.498`). Secondary `n = 32` pooled (`0..29` + `[34, 37]`) sensitivity is `67.9%` `[31.7%, 99.7%]` raw and `75.0%` `[55.8%, 93.5%]` luck-adjusted.

## 7. Per-Seed Hard Frontier Diagnostic Atlas (`seeds 0..29`, `opencode_carbon` & `opencode_gpt55` vs `solver`)

| Seed | Tertile | Solver Day (`|C|`) | Solver Score (LA) | Carbon Day (`|C|`, in `C`) | Carbon Score (LA) | Carbon `P(acc)` / `P*` | Carbon Can/Int (Flips) | Carbon Class | GPT-5.5 Day (`|C|`, in `C`) | GPT-5.5 Score (LA) | GPT-5.5 `P(acc)` / `P*` | GPT-5.5 Can/Int (Flips) | GPT-5.5 Class |
|---:|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `0` | `slow_t3` | `d9` (`2`) | `+0.64` (`+0.556`) | `d11` (`1`,`Y`) | `+0.59` (`+0.560`) | `0.981`/`0.629` | `6`/`57` (`0`) | `isolated_c1_win` | `d8` (`1`,`Y`) | `+0.00` (`+0.000`) | `none`/`0.602` | `14`/`0` (`0`) | `horizon_abstain` |
| `1` | `fast_t1` | `d7` (`1`) | `+0.69` (`+0.665`) | `d19` (`1`,`N`) | `-1.00` (`+0.304`) | `0.988`/`0.758` | `15`/`90` (`1`) | `5pct_flip_singleton_trap` | `d12` (`1`,`Y`) | `+0.43` (`+0.381`) | `0.966`/`0.699` | `22`/`0` (`0`) | `isolated_c1_win` |
| `2` | `fast_t1` | `d9` (`1`) | `+0.58` (`+0.578`) | `d14` (`1`,`Y`) | `+0.48` (`+0.437`) | `0.971`/`0.676` | `7`/`80` (`0`) | `isolated_c1_win` | `d11` (`1`,`Y`) | `+0.47` (`+0.388`) | `0.944`/`0.680` | `18`/`11` (`0`) | `isolated_c1_win` |
| `3` | `slow_t3` | `d18` (`1`) | `+0.28` (`+0.226`) | `d19` (`10`,`Y`) | `+0.51` (`+0.157`) | `0.766`/`0.662` | `7`/`40` (`0`) | `unresolved_lucky_win` | `d10` (`1`,`Y`) | `+0.42` (`+0.400`) | `0.986`/`0.704` | `18`/`0` (`0`) | `isolated_c1_win` |
| `4` | `slow_t3` | `d5` (`0`) | `+0.73` (`+0.730`) | `d16` (`1`,`Y`) | `+0.40` (`+0.389`) | `0.992`/`0.714` | `10`/`84` (`0`) | `isolated_c1_win` | `d6` (`1`,`Y`) | `+0.72` (`+0.692`) | `0.984`/`0.581` | `8`/`0` (`0`) | `isolated_c1_win` |
| `5` | `mid_t2` | `d9` (`1`) | `+0.52` (`+0.493`) | `d21` (`2`,`Y`) | `+0.16` (`-0.408`) | `0.510`/`0.862` | `19`/`103` (`0`) | `sub_breakeven_gamble_win` | `d14` (`4`,`Y`) | `+0.41` (`-0.064`) | `0.664`/`0.709` | `24`/`8` (`0`) | `sub_breakeven_gamble_win` |
| `6` | `fast_t1` | `d6` (`1`) | `+0.71` (`+0.708`) | `d6` (`1`,`Y`) | `+0.73` (`+0.727`) | `0.998`/`0.578` | `7`/`25` (`0`) | `isolated_c1_win` | `d6` (`1`,`Y`) | `+0.75` (`+0.675`) | `0.957`/`0.571` | `10`/`0` (`0`) | `isolated_c1_win` |
| `7` | `mid_t2` | `d9` (`1`) | `+0.64` (`+0.640`) | `d10` (`3`,`Y`) | `+0.69` (`+0.323`) | `0.783`/`0.592` | `6`/`57` (`0`) | `unresolved_lucky_win` | `d11` (`2`,`Y`) | `+0.55` (`+0.147`) | `0.740`/`0.645` | `20`/`4` (`0`) | `unresolved_lucky_win` |
| `8` | `slow_t3` | `d21` (`1`) | `+0.26` (`+0.260`) | `d14` (`2`,`Y`) | `+0.35` (`+0.116`) | `0.827`/`0.741` | `10`/`79` (`0`) | `unresolved_lucky_win` | `d7` (`1`,`Y`) | `+0.58` (`+0.578`) | `0.999`/`0.633` | `12`/`4` (`0`) | `isolated_c1_win` |
| `9` | `fast_t1` | `d6` (`1`) | `+0.71` (`+0.701`) | `d15` (`1`,`Y`) | `+0.60` (`+0.491`) | `0.932`/`0.625` | `10`/`85` (`0`) | `isolated_c1_win` | `d6` (`1`,`Y`) | `+0.70` (`+0.646`) | `0.968`/`0.588` | `10`/`2` (`0`) | `isolated_c1_win` |
| `10` | `slow_t3` | `d19` (`1`) | `+0.21` (`+0.140`) | `d16` (`1`,`Y`) | `+0.40` (`+0.308`) | `0.934`/`0.714` | `8`/`85` (`0`) | `isolated_c1_win` | `d9` (`1`,`Y`) | `+0.64` (`+0.514`) | `0.923`/`0.610` | `16`/`12` (`0`) | `isolated_c1_win` |
| `11` | `mid_t2` | `d9` (`1`) | `+0.62` (`+0.620`) | `d21` (`7`,`Y`) | `+0.00` (`+0.000`) | `none`/`0.885` | `12`/`121` (`0`) | `horizon_abstain` | `d14` (`1`,`Y`) | `+0.46` (`+0.432`) | `0.981`/`0.685` | `24`/`0` (`0`) | `isolated_c1_win` |
| `12` | `slow_t3` | `d12` (`2`) | `+0.48` (`+0.286`) | `d9` (`1`,`Y`) | `+0.65` (`+0.610`) | `0.976`/`0.606` | `10`/`40` (`0`) | `isolated_c1_win` | `d8` (`1`,`Y`) | `+0.66` (`+0.628`) | `0.981`/`0.602` | `14`/`0` (`0`) | `isolated_c1_win` |
| `13` | `slow_t3` | `d17` (`1`) | `+0.34` (`+0.292`) | `d13` (`1`,`Y`) | `+0.40` (`+0.365`) | `0.975`/`0.714` | `10`/`70` (`0`) | `isolated_c1_win` | `d10` (`1`,`Y`) | `+0.52` (`+0.508`) | `0.992`/`0.658` | `18`/`1` (`0`) | `isolated_c1_win` |
| `14` | `mid_t2` | `d15` (`1`) | `+0.23` (`+0.225`) | `d8` (`2`,`Y`) | `+0.71` (`+0.320`) | `0.772`/`0.585` | `4`/`44` (`0`) | `unresolved_lucky_win` | `d10` (`1`,`Y`) | `+0.47` (`+0.419`) | `0.965`/`0.680` | `18`/`3` (`0`) | `isolated_c1_win` |
| `15` | `mid_t2` | `d9` (`1`) | `-1.00` (`+0.433`) | `d12` (`2`,`Y`) | `-1.00` (`+0.360`) | `0.805`/`0.592` | `6`/`67` (`0`) | `unresolved_premature_loss` | `d10` (`1`,`Y`) | `+0.57` (`+0.501`) | `0.956`/`0.637` | `18`/`0` (`0`) | `isolated_c1_win` |
| `16` | `fast_t1` | `d8` (`1`) | `+0.69` (`+0.609`) | `d10` (`1`,`Y`) | `+0.70` (`+0.642`) | `0.966`/`0.588` | `5`/`50` (`0`) | `isolated_c1_win` | `d12` (`2`,`Y`) | `+0.57` (`+0.377`) | `0.877`/`0.637` | `18`/`5` (`0`) | `unresolved_lucky_win` |
| `17` | `fast_t1` | `d5` (`1`) | `+0.77` (`+0.696`) | `d10` (`1`,`Y`) | `+0.54` (`+0.532`) | `0.995`/`0.649` | `6`/`49` (`0`) | `isolated_c1_win` | `d9` (`1`,`Y`) | `+0.00` (`+0.000`) | `none`/`0.610` | `16`/`15` (`0`) | `horizon_abstain` |
| `18` | `mid_t2` | `d13` (`1`) | `+0.52` (`+0.453`) | `d18` (`4`,`Y`) | `-1.00` (`-0.085`) | `0.627`/`0.685` | `14`/`101` (`0`) | `sub_breakeven_gamble_loss` | `d14` (`0`,`N`) | `+0.48` (`+0.480`) | `1.000`/`0.676` | `22`/`6` (`1`) | `isolated_c1_win` |
| `19` | `mid_t2` | `d9` (`1`) | `+0.67` (`+0.588`) | `d11` (`1`,`Y`) | `+0.62` (`+0.562`) | `0.964`/`0.617` | `8`/`60` (`0`) | `isolated_c1_win` | `d14` (`1`,`Y`) | `+0.28` (`+0.193`) | `0.932`/`0.781` | `22`/`0` (`0`) | `isolated_c1_win` |
| `20` | `mid_t2` | `d12` (`1`) | `+0.53` (`+0.502`) | `d11` (`5`,`Y`) | `+0.66` (`+0.182`) | `0.712`/`0.602` | `4`/`66` (`0`) | `unresolved_lucky_win` | `d10` (`1`,`Y`) | `+0.62` (`+0.570`) | `0.969`/`0.617` | `18`/`8` (`0`) | `isolated_c1_win` |
| `21` | `mid_t2` | `d9` (`1`) | `+0.73` (`+0.592`) | `d10` (`1`,`Y`) | `+0.69` (`+0.386`) | `0.820`/`0.592` | `6`/`58` (`0`) | `isolated_c1_win` | `d11` (`2`,`Y`) | `+0.69` (`+0.494`) | `0.884`/`0.592` | `16`/`0` (`0`) | `unresolved_lucky_win` |
| `22` | `slow_t3` | `d15` (`1`) | `+0.40` (`+0.357`) | `d14` (`1`,`Y`) | `+0.64` (`+0.547`) | `0.943`/`0.610` | `6`/`82` (`0`) | `isolated_c1_win` | `d12` (`1`,`Y`) | `+0.33` (`+0.305`) | `0.981`/`0.752` | `22`/`4` (`0`) | `isolated_c1_win` |
| `23` | `slow_t3` | `d18` (`1`) | `+0.32` (`+0.271`) | `d21` (`3`,`Y`) | `+0.23` (`-0.444`) | `0.452`/`0.813` | `12`/`86` (`0`) | `sub_breakeven_gamble_win` | `d11` (`3`,`Y`) | `+0.57` (`+0.162`) | `0.740`/`0.637` | `18`/`9` (`0`) | `unresolved_lucky_win` |
| `24` | `mid_t2` | `d14` (`1`) | `+0.31` (`+0.300`) | `d13` (`1`,`Y`) | `+0.67` (`+0.662`) | `0.995`/`0.599` | `8`/`69` (`0`) | `isolated_c1_win` | `d8` (`1`,`Y`) | `+0.58` (`+0.548`) | `0.980`/`0.633` | `12`/`0` (`0`) | `isolated_c1_win` |
| `25` | `fast_t1` | `d8` (`1`) | `+0.58` (`+0.547`) | `d11` (`1`,`Y`) | `+0.72` (`+0.715`) | `0.997`/`0.581` | `3`/`60` (`0`) | `isolated_c1_win` | `d9` (`1`,`Y`) | `+0.64` (`+0.617`) | `0.986`/`0.610` | `16`/`0` (`0`) | `isolated_c1_win` |
| `26` | `fast_t1` | `d7` (`1`) | `+0.69` (`+0.636`) | `d10` (`1`,`N`) | `-1.00` (`+0.587`) | `0.950`/`0.599` | `8`/`43` (`1`) | `5pct_flip_singleton_trap` | `d10` (`1`,`Y`) | `+0.62` (`+0.591`) | `0.982`/`0.617` | `18`/`18` (`0`) | `isolated_c1_win` |
| `27` | `fast_t1` | `d6` (`1`) | `+0.72` (`+0.694`) | `d15` (`1`,`Y`) | `+0.46` (`+0.460`) | `1.000`/`0.685` | `14`/`78` (`0`) | `isolated_c1_win` | `d10` (`1`,`Y`) | `+0.44` (`+0.440`) | `1.000`/`0.694` | `16`/`12` (`0`) | `isolated_c1_win` |
| `28` | `fast_t1` | `d6` (`1`) | `+0.75` (`+0.722`) | `d12` (`1`,`Y`) | `+0.64` (`+0.604`) | `0.978`/`0.610` | `6`/`64` (`0`) | `isolated_c1_win` | `d10` (`1`,`Y`) | `+0.52` (`+0.508`) | `0.992`/`0.658` | `18`/`0` (`0`) | `isolated_c1_win` |
| `29` | `slow_t3` | `d8` (`2`) | `+0.65` (`+0.459`) | `d13` (`1`,`Y`) | `+0.43` (`+0.379`) | `0.964`/`0.699` | `7`/`46` (`0`) | `isolated_c1_win` | `d12` (`1`,`Y`) | `+0.42` (`+0.403`) | `0.988`/`0.704` | `18`/`2` (`0`) | `isolated_c1_win` |
