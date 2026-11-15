# Canary v1.4 Frontier Transcript Reasoning Forensics and Posterior Calibration Audit

Every figure in this report is deterministically computed from replay-verified `episodes.jsonl` records and OpenCode `transcripts/*.txt` JSON event streams by `scripts/frontier_transcript_forensics.py` using `canary.analysis.accuse` (`audit_episode`) and `scripts/paired_v13.py` (`p_acc`, `post_expected`, `boot_ratio`), with zero live API calls and zero `.git` runtime dependency.

Reproduce and verify:

```bash
PYTHONPATH=. python scripts/frontier_transcript_forensics.py --check
```

## 1. Provenance Honesty (Panel Fixes A/C/D), Replay Parity, and Executive Summary

- **Provenance and lock honesty (`Panel Fixes A/C/D`):** Primary `seeds 0-29` (`data/runs/committed/v1.4/`, committed in `8fd4dec`; OpenCode `gemini-4-carbon` hard raw `65% [24%, 98%]` (`0.322` vs solver `0.499`) and luck-adjusted `72% [52%, 91%]` (`0.360` vs `0.499`)) are a **post-hoc lock** (`671ed96`, committed `28 s` after `8fd4dec`) against later reruns and cherry-picking, **not a pre-registration** (`20+10` solver reference directories cover `0-19` and `20-29`). By contrast, the committed G1 hard extension on `seeds 30-59` (`f9fb7a4a`, `n=2` completed seeds `[34, 37]` before stopping after `31` `provider_quota` exclusions to protect the shared `2M TPM` carbon quota for Harbor rehearsal) and the second frontier family `gpt-5.5` (`cf394894`, OpenCode `1.19.5`, `7200 s` cap, `$200` spend cap, `30` committed `v1.4` episodes) were **pre-registered** before any episode ran.
- **Step-and-ledger replay verification (`777/777`) and transcript parity:** `472/472` committed `v1.4` episodes and `305/305` FR8 replication episodes (`777/777` total) pass full `Env` step-and-ledger replay (`1bc3e281` `norm_result` unwrapping on `84` committed + `24` replication error steps; `detail` normalization on `321` + `156` pre-`1bc3e281` steps). All `97` active OpenCode `transcripts/*.txt` files match `steps_from_events` (`0` step mismatches, `0` unredacted `thoughtSignature` blobs, `0` secret tokens). `docs/reports/gap.md` does not yet ship `gemini-3.5-flash` hard (`0-29`); those `30` committed episodes are replay-verified inside `data/runs/committed/v1.4/` (`472/472`) and held out of active cohort tables via `gap_ships_flash_hard(root)`.
- **Rule-awareness vs action gap:** Across `97` active OpenCode transcripts, **`0/97` (`0.0%`)** explicitly mention the disclosed `careful` mole (`1 - share`) selection weight, only `9/30` (`30.0%`) primary carbon hard transcripts cite the `95%`/`5%` noisy canary mechanic (`70.0%` treat noisy variants as deterministic `100%` intersections), and although `20/30` (`66.7%`) discuss `interview`/`evasive` responses (`0.24` vs `0.20`, `LR = 1.2`), `gemini-4-carbon` still burns **`68.03` interviews/episode** (`53.1%` of all hard tool calls vs `0.00` for `solver`). Only `1/30` (`seed 11`) explicitly applies the `-1` expected-value abstention rule.
- **Verbalized certainty vs exact Bayesian posterior:** Because `canary_accuse` returns only `episode_over: true` without revealing correctness or score, the concluding `part.text` dossier captures pre-feedback epistemic confidence. On primary `hard` (`0-29`), `29/29` (`100.0%`) accused episodes use decisive language (`uniquely`, `certain`, `100%`, `eliminated`, `strictly`), including **`4/4` `-1.000` wrong accusations** (`seeds [1, 15, 18, 26]`). Across `22` hard episodes stating a numeric suspect posterior, verbalized confidence averages `96.5%` vs `87.5%` exact `SolverPolicy` `P(accused)` (`+9.0%` mean overconfidence, peaking at `+36.8%` on `seed 23`). Sub-breakeven accusations (`P(accused) < 1/(1+V)`) occur on `3` carbon hard seeds (`[5, 18, 23]`) and `6` flash medium seeds (`[8, 11, 13, 22, 26, 29]`, accounting for **`5/5`** of flash medium's `-1.000` errors).
- **Candidate-set / variant-ledger tracking (`medium 0-29` paired):** `gemini-4-carbon` maintains structured candidate-set or variant-ledger bookkeeping in `30/30` (`100.0%`) medium episodes (`100.0%` accuracy, day `7.97`, luck-adjusted `0.652`), whereas `gemini-3.5-flash` drops bookkeeping in `10/30` (`33.3%`) episodes. Within `gemini-3.5-flash` medium, dropping structured bookkeeping lowers accuracy from `90.0%` (`18/20`) to `70.0%` (`7/10`), delays accusation from day `8.05` to `10.90`, and cuts luck-adjusted score from `0.611` to `0.234` (`r = +0.358`).

## 2. Rule-Awareness vs Behavioral Action Gap Across Active OpenCode Cohorts

| cohort | n | `careful` mole cited | `framing` / decoy cited | `95%`/`5%` noise cited | `interview` cited | `abstain` / EV cited | actual interviews / ep (% calls) | accepted canaries / ep | broad `>50%` or `1`-var % | abstained | mean `plant_canary` vs `interview` reasoning tok |
|---|---:|---|---|---|---|---|---:|---:|---:|---:|---|
| OpenCode gemini-4-carbon medium (0-29) | 30 | 0/30 (0%) | 25/30 (83%) | 0/30 (0%) | 11/30 (37%) | 0/30 (0%) | 37.53 (49.3%) | 5.83 | 17.1% (30/175) | 0/30 | 2652 vs 243 |
| OpenCode gemini-4-carbon hard (0-29) | 30 | 0/30 (0%) | 30/30 (100%) | 9/30 (30%) | 20/30 (67%) | 1/30 (3%) | 68.03 (53.1%) | 8.47 | 7.5% (19/254) | 1/30 | 2937 vs 203 |
| OpenCode gemini-4-carbon hard G1 ext (34,37) | 2 | 0/2 (0%) | 1/2 (50%) | 2/2 (100%) | 2/2 (100%) | 0/2 (0%) | 29.00 (50.4%) | 5.50 | 0.0% (0/11) | 0/2 | 3816 vs 319 |
| OpenCode gemini-4-carbon hard FR8 rep (30,34,42,45,57) | 5 | 0/5 (0%) | 5/5 (100%) | 2/5 (40%) | 3/5 (60%) | 0/5 (0%) | 50.40 (50.3%) | 5.40 | 0.0% (0/27) | 0/5 | 2489 vs 351 |
| OpenCode gemini-3.5-flash medium (0-29) | 30 | 0/30 (0%) | 6/30 (20%) | 0/30 (0%) | 1/30 (3%) | 0/30 (0%) | 2.47 (4.8%) | 7.70 | 8.7% (20/231) | 0/30 | 847 vs 261 |

## 3. Verbalized Certainty vs Exact SolverPolicy Posterior at Accusation

Comparison of decisive certainty claims (`uniquely`, `certain`, `100%`, `eliminated`, `only suspect`) and hedging markers against exact `SolverPolicy` `P(accused)` and break-even threshold `1 / (1 + V)` at the accusation step:

| cohort | accused / n | decisive marker (% accused) | decisive wrong seeds | `uniquely` wrong seeds | hedged count | mean `P(accused)` | mean `1/(1+V)` | sub-breakeven `P < 1/(1+V)` (wrong / lucky) | stated `P_verbal` vs exact `P(accused)` (n, gap) | mean `accuse` reasoning tok |
|---|---|---|---|---|---:|---:|---:|---|---|---:|
| OpenCode gemini-4-carbon medium (0-29) | 30/30 | 30/30 (100.0%) | `[]` | `[]` | 0 | 0.961 | 0.587 | 2 (`[]` / `[7, 29]`) | 99.0% vs 95.2% (n=24, +3.8%) | 868 |
| OpenCode gemini-4-carbon hard (0-29) | 29/30 | 29/29 (100.0%) | `[1, 15, 18, 26]` | `[1, 26]` | 1 | 0.882 | 0.654 | 3 (`[18]` / `[5, 23]`) | 96.5% vs 87.5% (n=22, +9.0%) | 1474 |
| OpenCode gemini-4-carbon hard G1 ext (34,37) | 2/2 | 2/2 (100.0%) | `[]` | `[]` | 0 | 0.980 | 0.573 | 0 (`[]` / `[]`) | 99.4% vs 97.9% (n=1, +1.5%) | 758 |
| OpenCode gemini-4-carbon hard FR8 rep (30,34,42,45,57) | 5/5 | 5/5 (100.0%) | `[]` | `[]` | 0 | 0.894 | 0.607 | 0 (`[]` / `[]`) | 98.5% vs 89.4% (n=5, +9.0%) | 957 |
| OpenCode gemini-3.5-flash medium (0-29) | 30/30 | 18/30 (60.0%) | `[11]` | `[]` | 0 | 0.867 | 0.594 | 6 (`[11, 13, 22, 26, 29]` / `[8]`) | 100.0% vs 100.0% (n=2, +0.0%) | 717 |

### 3.1 Annotated Forensic Case Dossiers (Primary Hard 0-29 + Seed 34 Convergence)

| case | seed | day | accused (ok) | score (solver) | `V` | `1/(1+V)` | exact `P(accused)` | stated `P_verbal` | `post_expected` | interviews / canaries | forensic mechanism |
|---|---:|---:|---|---|---:|---:|---:|---:|---:|---|---|
| `hard_seed26_s1_noise_trap` | 26 | 10 | `e04` (False) | -1.000 (0.690 on d7 `e08`) | 0.67 | 0.599 | 0.950 | n/a | 0.587 | 43 / 8 | Treated two 95%-accurate hard canary leaks (c6:D1 and c6-2:S1) as a deterministic 100% set intersection (D1 cap S1 = {e04}, 'uniquely identified'), falling into a 5% noisy variant flip on c6-2 while true mole e08 went unsplit. |
| `hard_seed4_interview_sink` | 4 | 16 | `e11` (True) | 0.400 (0.730 on d5 `e11`) | 0.40 | 0.714 | 0.992 | 99.5% | 0.389 | 84 / 10 | Burned 84 interviews across 16 days (53.8% of 156 calls) before accusing true mole e11 at V=0.40, whereas the zero-interview Bayesian solver isolated e11 on Day 5 at V=0.73 (-0.330 company-value drag). |
| `hard_seed1_c16_noisy_flip` | 1 | 19 | `e39` (False) | -1.000 (0.690 on d7 `e33`) | 0.32 | 0.758 | 0.988 | 99.1% | 0.304 | 90 / 15 | Spent 90 interviews over 19 days, restricted innocent e39 on Day 16, and treated single tie-break canary c16:v1 between {e33, e39} as >99.1% decisive when v1 suffered a 5% noise flip (true mole e33). |
| `hard_seed15_log_interview_overconfidence` | 15 | 12 | `e34` (False) | -1.000 (-1.000 on d9 `e17`) | 0.69 | 0.592 | 0.805 | 93.0% | 0.360 | 68 / 6 | Planted only 6 canaries vs 68 interviews; with {e34, e37} tied on two canary hits (c6:vB, c8:vA), inflated 3 after-hours logs + 3 evasive interviews into ~93% verbalized posterior (exact P=0.805) and wrongly accused e34. |
| `hard_seed18_sub_breakeven_wrong` | 18 | 18 | `e29` (False) | -1.000 (0.520 on d13 `e27`) | 0.46 | 0.685 | 0.627 | 89.0% | -0.085 | 101 / 14 | After 101 interviews and a 4-way canary tie {e09, e27, e29, e37}, verbalized ~89% posterior from 6/18 after-hours logs when exact SolverPolicy P(e29)=0.627 was below break-even 1/(1+0.46)=0.685 (EV=-0.085), accusing innocent e29. |
| `hard_seed5_sub_breakeven_lucky` | 5 | 21 | `e27` (True) | 0.160 (0.520 on d9 `e27`) | 0.16 | 0.862 | 0.510 | n/a | -0.408 | 103 / 19 | Executed 103 interviews over 21 days and accused e27 at exact P(e27)=0.510 below break-even 1/(1+0.16)=0.862 (EV=-0.408), succeeding by luck (+0.160 vs solver Day 9 +0.520). |
| `hard_seed23_sub_breakeven_lucky` | 23 | 21 | `e29` (True) | 0.230 (0.320 on d18 `e29`) | 0.23 | 0.813 | 0.452 | 82.0% | -0.444 | 86 / 12 | Spent 86 interviews and 4060 accuse-step reasoning tokens on Day 21, claiming >82% posterior when exact P(e29)=0.452 was 36.1 pp below break-even 1/(1+0.23)=0.813 (EV=-0.444). |
| `hard_seed11_day21_rational_abstention` | 11 | 21 | `None` (False) | 0.000 (0.620 on d9 `e09`) | 0.13 | 0.885 | n/a (P_top=0.219) | 42.9% | 0.000 | 121 / 12 | Ran 121 interviews (max across all cohorts) with 0/12 canaries surfacing; explicitly computed 0.429 * 0.20 - 0.571 = -0.485 < 0 (exact P_top=0.219 < break-even 0.885) and rationally abstained for 0.000. |
| `g1_ext_hard_seed34` | 34 | 5 | `e29` (True) | 0.790 (0.700 on d6 `e29`) | 0.79 | 0.559 | 0.979 | 99.4% | 0.752 | 26 / 6 | Pinpointed e29 on Day 5 (+0.790, P=0.979, verbalized 99.44%) via targeted 3-variant canary c1-2:A plus document intersection; leaked pre-accusation thought computing 1.2^3 = 1.728x from 3 evasive interviews. |
| `fr8_rep_hard_seed34` | 34 | 8 | `e29` (True) | 0.820 (0.700 on d6 `e29`) | 0.82 | 0.549 | 0.650 | 96.5% | 0.183 | 49 / 3 | Converged on e29 on Day 8 (+0.820) via d1-1 cap d1-3 Research isolation, decoy exclusion (e14), and 6/10 after-hours logs + 5 evasive interviews (verbalized ~96.5% vs exact P=0.650 > break-even 0.549). |

## 4. Candidate-Set and Variant-Ledger Bookkeeping (Paired Medium Seeds 0-29)

| cohort / stratum | n | candidate-set % | variant-ledger % | structured bookkeeping % | accuracy | mean final day | mean raw score | raw / solver [95% CI] | luck-adjusted (`post_expected`) | luck-adj. / solver [95% CI] |
|---|---:|---:|---:|---:|---:|---:|---:|---|---:|---|
| `gemini-4-carbon` medium (`0-29` all, `30/30` structured) | 30 | 83.3% | 96.7% | 100.0% | 100.0% | 7.97 | 0.713 | 111% [99%, 127%] | 0.652 | 101% [85%, 119%] |
| `gemini-3.5-flash` medium (`0-29` all) | 30 | 43.3% | 63.3% | 66.7% | 83.3% | 9.00 | 0.434 | 67% [29%, 103%] | 0.485 | 75% [45%, 105%] |
| `gemini-3.5-flash` medium: structured bookkeeping subset | 20 | n/a | n/a | 100.0% | 90.0% | 8.05 | 0.567 | n/a (stratum) | 0.611 | n/a (mean `P(acc)`=0.929) |
| `gemini-3.5-flash` medium: unstructured bare-accusation subset (`[0, 8, 10, 13, 15, 18, 22, 23, 28, 29]`) | 10 | 0.0% | 0.0% | 0.0% | 70.0% | 10.90 | 0.170 | n/a (stratum) | 0.234 | n/a (mean `P(acc)`=0.742) |

- **Point-biserial correlations (`structured_any` indicator):** Across pooled medium OpenCode episodes (`n=60`), explicit candidate-set / variant-ledger bookkeeping correlates positively with accuracy (`r = 0.351`), raw score (`r = 0.372`), and luck-adjusted score (`r = 0.374`), and negatively with accusation day (`r = -0.369`, faster resolution). Within `gemini-3.5-flash` medium alone (`n=30`), the same pattern holds (`r_accuracy = 0.253`, `r_final_day = -0.421`, `r_raw_score = 0.289`, `r_post_expected = 0.358`): `3` of its `5` wrong accusations (`seeds [13, 22, 29]`) emit bare one-line accusations without any candidate set or variant table, and the remaining `2` (`seeds [11, 26]`) stop at `5-6` department candidates without a decisive canary split.
