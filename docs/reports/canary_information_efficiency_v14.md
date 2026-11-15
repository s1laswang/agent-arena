# Canary v1.4 Information Efficiency, Canary Partition & Entropy Audit (`n = 30`, Seeds `0-29`)

**Headline & rehearsal framing.** Across post-hoc locked `v1.4` dev seeds `0-29` (`671ed96`, 28 s after `8fd4dec`, lock against later reruns and cherry-picking, not a pre-registration), OpenCode `gemini-4-carbon` over MCP scores **`65% [24%, 98%]`** raw (`72% [52%, 91%]` luck-adjusted) on Hard vs `111% [99%, 127%]` raw (`101% [85%, 119%]` luck-adjusted) on Medium, while pre-registered OpenCode `gpt-5.5` (`cf394894`) reaches **`101% [79%, 140%]`** raw (`84% [67%, 103%]` luck-adjusted; no gap for this agent). In the 3-run Harbor `0.26.0` judge rehearsal (`1bc3e281`, corrected in `aa1c679e` / `5f9b3297`), `gemini-4-carbon` scored **`93% [20%, 371%]`**, **`116% [78%, 363%]`**, and **`131% [86%, 590%]`** (`9` valid trials in run 3, mean `+0.626`, `28/29` accusations correct) where the container shell was used in **`20/28`** trials -- the MCP-only Hard gap did not reproduce in the judge path.

```bash
python scripts/canary_information_efficiency_v14.py
python scripts/canary_information_efficiency_v14.py --check
python scripts/canary_information_efficiency_v14.py --check --full-check
```

## 1. Theoretical Channel Ceilings (`v1.4` Rules)

- **3-variant canary partition ceiling:** `log2(3) = 1.5850` bits per noiseless surfaced leak (Medium); under Hard's `95%` fingerprint recovery (`5%` uniform flip across the other 2 variants), conditional leak mutual information is `1.2486` bits against initial uniform prior `H_0 = log2(40) = 5.3219` bits (`log2(20) = 4.3219` bits on Medium).
- **Careful-mole wide-distribution penalty:** On Hard and Medium (`careful_mole = True`), a canary sent to `k` of `N` staff receives leak-selection weight `1 - k / N` (`<= 0.50` once `k >= N / 2`, `0.00` at `k = N`), trading wide suspect coverage `P(mole in S)` against effective trigger exposure `P(mole in S) * (1 - k / N)`.
- **Binary interview (`LR = 1.2` Hard, `1.3` Medium) vs canary capacity:** Even at peak sensitivity `p = 0.50`, a single Hard `interview` (`q_0 = 0.20, q_1 = 0.24`) yields at most `0.00168` bits (`0.00017` bits at `p = 1/40`; `0.00367` bits max on Medium) -- `742x-942x` less mutual information than one surfaced 3-way canary leak.

## 2. Canary Partition Balance, Careful-Mole Exposure & Capacity Utilization (`0-29`)

| Agent | Tier | Canaries/ep | Util (Act / Hor) | `H_rec` / `H_post` (bits) | `k<=3` / `<3` var | Mean Cov / `1-k/N` | Wide `>=50%` (`k=N`) | Surfaced Rate |
|---|---|---:|---|---|---|---|---|---:|
| `solver` | `hard` | `14.13` | `66.7% / 33.7%` | `1.543 / 1.511` | `11.8% / 0.0%` | `23.7% / 0.763` | `0.5%` (`0`) | `11.6%` |
| `opencode:openai/gpt-5.5` | `hard` | `17.13` | `84.5% / 40.8%` | `1.459 / 1.376` | `47.1% / 10.7%` | `21.8% / 0.782` | `21.6%` (`1`) | `10.1%` |
| `gemini:gemini-4-carbon` | `hard` | `8.57` | `33.0% / 20.4%` | `1.531 / 1.461` | `0.0% / 0.0%` | `25.6% / 0.744` | `12.1%` (`0`) | `21.4%` |
| `opencode:google/gemini-4-carbon` | `hard` | `8.47` | `31.5% / 20.2%` | `1.519 / 1.446` | `0.0% / 0.0%` | `25.7% / 0.743` | `10.6%` (`0`) | `19.3%` |
| `opencode:google/gemini-3.5-flash` | `hard` | `12.43` | `49.0% / 29.6%` | `1.537 / 1.383` | `43.4% / 5.4%` | `22.8% / 0.772` | `16.9%` (`2`) | `14.2%` |
| `solver` | `medium` | `7.30` | `89.0% / 52.1%` | `1.398 / 1.396` | `47.5% / 29.2%` | `22.9% / 0.771` | `0.9%` (`0`) | `20.5%` |
| `gemini:gemini-4-carbon` | `medium` | `6.93` | `71.5% / 49.5%` | `1.495 / 1.449` | `0.0% / 1.4%` | `34.6% / 0.654` | `15.9%` (`0`) | `19.2%` |
| `opencode:google/gemini-4-carbon` | `medium` | `5.83` | `73.2% / 41.7%` | `1.531 / 1.490` | `0.6% / 0.0%` | `38.0% / 0.620` | `21.1%` (`0`) | `24.0%` |
| `opencode:google/gemini-3.5-flash` | `medium` | `7.70` | `85.6% / 55.0%` | `1.480 / 1.429` | `59.7% / 14.3%` | `24.8% / 0.752` | `13.9%` (`0`) | `14.7%` |

## 3. Telescoping Entropy Reduction (`H_0 - H_final`) & Tool-Budget Allocation

| Agent (`tier`) | Score | `H_final` (bits) | `Delta H` (bits) | Leak+Doc / Log / Msg / Intv (bits) | `Delta H`/Can | Bits/Intv | Tool Mix (`Can / Intv / Msg / Log` per ep) |
|---|---:|---:|---:|---|---:|---:|---|
| `solver` (`hard`) | `+0.499` | `0.233` | `5.089` | `+4.65 / +0.39 / +0.04 / +0.00` | `0.360` | `n/a` | `14.1 / 0.0 / 7.5 / 9.6` |
| `opencode:openai/gpt-5.5` (`hard`) | `+0.504` | `0.327` | `4.995` | `+4.56 / +0.44 / +0.00 / -0.00` | `0.292` | `-0.0009` | `17.1 / 4.1 / 9.2 / 8.5` |
| `gemini:gemini-4-carbon` (`hard`) | `+0.473` | `0.431` | `4.891` | `+4.42 / +0.60 / +0.02 / -0.15` | `0.571` | `-0.0027` | `8.6 / 57.3 / 3.5 / 11.8` |
| `opencode:google/gemini-4-carbon` (`hard`) | `+0.322` | `0.647` | `4.675` | `+4.38 / +0.47 / +0.01 / -0.19` | `0.552` | `-0.0028` | `8.5 / 68.0 / 3.5 / 12.3` |
| `opencode:google/gemini-3.5-flash` (`hard`) | `+0.373` | `0.963` | `4.359` | `+3.86 / +0.47 / +0.03 / -0.00` | `0.351` | `-0.0057` | `12.4 / 0.7 / 4.8 / 9.9` |
| `solver` (`medium`) | `+0.645` | `0.159` | `4.163` | `+4.08 / +0.02 / +0.06 / +0.00` | `0.570` | `n/a` | `7.3 / 0.0 / 7.7 / 7.2` |
| `gemini:gemini-4-carbon` (`medium`) | `+0.530` | `0.386` | `3.936` | `+3.90 / +0.03 / +0.01 / -0.00` | `0.568` | `-0.0001` | `6.9 / 47.2 / 3.7 / 8.0` |
| `opencode:google/gemini-4-carbon` (`medium`) | `+0.713` | `0.096` | `4.226` | `+4.20 / +0.03 / +0.01 / -0.01` | `0.725` | `-0.0001` | `5.8 / 37.5 / 2.9 / 6.0` |
| `opencode:google/gemini-3.5-flash` (`medium`) | `+0.434` | `0.395` | `3.927` | `+3.82 / +0.09 / +0.01 / +0.00` | `0.510` | `+0.0004` | `7.7 / 2.2 / 4.9 / 7.0` |

## 4. Mechanistic Diagnosis & Harbor Shell Contrast

1. **Action-budget starvation when Hard doubles `canaries_per_day` (`1 -> 2`):** On Medium (`1` canary/day), `opencode:google/gemini-4-carbon` plants `5.83` canaries/ep (`73.2%` of active-day canary capacity) and achieves `Delta H = 4.226` bits (`H_final = 0.096` bits, `111%` of solver). On Hard (`2` canaries/day, `8` investigative calls/day), it spends **`67.97` calls/ep (`68.6%` of investigative calls) on `interview`** (`57.27` calls/ep in-proc) vs only **`8.47` `plant_canary` calls/ep (`31.5%` active-day capacity)**, whereas `solver` (`14.13` canaries, `0` interviews, `66.7%` active capacity) and `opencode:openai/gpt-5.5` (`17.13` canaries, `4.13` interviews, `84.5%` active capacity) saturate the 2-canary/day pipeline.
2. **Negative realized entropy return on `LR = 1.2` interviews:** Across `2,039` Hard `interview` calls on `opencode:google/gemini-4-carbon` (`1,718` in-proc), realized Bayesian entropy change is **`-0.190` bits/ep** (`-0.0028` bits/call) because interviewing concentrated suspects yields `76%` cooperative answers from the mole (`LR_coop = 0.95`), flattening `P_max` without resolving ties; `leak + doc` observations carry `+3.864` to `+4.653` bits/ep (`>=88.6%` of total entropy reduction across every Hard cohort).
3. **Endgame partition floor (`min k = 4`) vs `1-vs-1-vs-1` isolation & Harbor shell (`20/28` trials):** `gemini-4-carbon` achieves high 3-way split balance (`H_rec = 1.519-1.531` vs `1.585` ceiling, `0` singletons) but never plants `k <= 3` endgame probes (`0.0%` vs `solver` `11.8%` and `gpt-5.5` `47.1%`, though `gpt-5.5` also spends `4.3%` on `k = 1` singletons and `1` full-40 zero-weight canary). In Harbor (`aa1c679e` / `5f9b3297`), shell scripting (`20/28` trials) lets `gemini-4-carbon` automate Bayesian filtering and partition bookkeeping outside prose memory (`93%`, `116%`, `131%`), eliminating the MCP-only Hard bottleneck.
