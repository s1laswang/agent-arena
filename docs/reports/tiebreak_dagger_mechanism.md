# Mechanism Audit: Why Raw-8k Qwen2.5 DAgger Round 1 Ended as an Honest Null While Structured On-Policy DAgger Succeeded

Deterministic offline mechanism and token-cap audit isolating why open-weight raw-transcript `Qwen2.5-1.5B-Instruct` LoRA DAgger Round 1 (`WS4-dagger-r1-8k-verda` / `WS4-dagger-r1-4k-verda`) improved own-state expert agreement (`43% -> 68%`) and doubled `8k` whom-precision (`0.10 -> 0.22`) yet ended as an honest null (`-0.542 +/- 0.214` at `8k` `n=50`, `-0.101 +/- 0.112` at `4k` `n=41`, `92%` premature accuse at `8k`), whereas structured on-policy DAgger (`CompactLinearDAggerPolicy` and `TinyMLPPolicy`) achieved statistically significant held-out gains on `HELDOUT_SEEDS 800000..800059`.

- **Seed & Track Hygiene (Panel Fix A & Fix E)**: All direct `SolverPolicy` serialization and stopping measurements strictly use `45` `TRAIN_SEEDS` episodes (`108000..108044`, `15`/tier across `easy`, `medium`, `hard`; `0` `HELDOUT_SEEDS`, `0` `DEV_SEEDS`, and `0` `JUDGE_SEEDS` touched). Where `DEV_SEEDS 0..29` appear elsewhere in Canary frontier reports, they are **post-hoc locked, not pre-registered**. Non-LLM structured policies (`CompactLinearDAggerPolicy`, `TinyMLPPolicy`, `is_open_weight_llm = False`) are strictly separated from open-weight `Qwen2.5` LoRA runs (`0 / 19` open-weight LLM runs above base `0.000`).

## 1. Cross-Track DAgger Outcome Comparison (`HELDOUT_SEEDS`)

| Run / Policy | Track & Representation | Train / DAgger Seeds | Held-Out `n` | Score / Paired Gain | Expert Agreement | Accuse / Wrong / Abstain | Verdict |
|---|---|---|---:|---|---|---|---|
| `WS4-dagger-r1-8k-verda` | Open-weight `Qwen2.5-1.5B` LoRA (`8k` raw JSON, `cap=256`) | `170000..170099` (`300` eps, `4000` states) | 50 | `-0.542 +/- 0.214` (paired `+0.242 +/- 0.304` vs `v3-4k@8k`, `n=43`) | `43% -> 68%` (`0.10 -> 0.22` whom-prec) | `0.92` acc / `0.72` wrong / `0.08` abst | `NEGATIVE_DAGGER_HONEST_NULL` |
| `WS4-dagger-r1-4k-verda` | Same DAgger r1 adapter evaluated at `4k` (`cap=256`) | `170000..170099` | 41 | `-0.101 +/- 0.112` (paired `-0.031 +/- 0.139` vs `v3-4k@4k`, `n=32`) | same adapter (`1/6` prec) | `0.15` acc / `0.12` wrong / `0.85` abst | `NEGATIVE_DAGGER_HONEST_NULL` |
| `compact-linear-dagger-v14` | Non-LLM `CompactLinearDAggerPolicy` (`785` params, lossless ledger) | `109000..109509` | 180 | `+0.6267` (`+0.1505 [+0.0869, +0.2141]` over cal BC) | `74.35% -> 98.05%` student-state | `0.972` acc / `0.028` wrong / `0.028` abst | `VERIFIED_IMPROVEMENT` (Track 2 control) |
| `tiny-mlp-dagger-v14` | Non-LLM `TinyMLPPolicy` (`28 -> 128 -> 64 -> 5`, `12293` params) | `107000..107599` | 180 | `+0.6141` (`+0.8922 [+0.7556, +1.0288]` over uncal SFT) | accuracy `0.389 -> 0.933` | `0.961` acc / `0.028` wrong / `0.039` abst | `PROMOTED_TRACK1_NEURAL` (non-LLM) |

## 2. `plant_canary` JSON Serialization & `cap=96` Generation Truncation Audit (`TRAIN_SEEDS 108000..108044`, `n=45`)

Under `Qwen2.5-1.5B-Instruct`'s chat template (`<tool_call>\n{"name": "plant_canary", "arguments": ...}\n</tool_call><|im_end|>`), every assigned employee entry `"eXX": "A", ` adds `12` JSON characters and `8` BPE tokens (`tokens = 28 + 8 * n_assigned + digits(doc_title) + (2 if '(' in doc_title else 0)`). Consequently, **every `plant_canary` call assigning `>= 9` employees (`>= 101` tokens) strictly exceeds `eval_hf`'s default `max_new_tokens=96` cap** (and an `8`-employee second canary `Board memo draft d (2)` hits `96/96` tokens, explaining why X2's `cap=96` DAgger probe truncated `plant_canary` into invalid `status` fallbacks `38/59` times in a single episode while earlier `v3` models never exceeded `~81` tokens):

| Tier (`n_emp`) | Regime (`TRAIN_SEEDS 108000..108044`, `15/tier`) | Calls | Mean / Max Assigned | Bare JSON / Chat Chars (Max) | Mean / Median / Max Qwen Tokens | Exceed `cap=96` (`>96`) | Exceed `cap=256` (`>256`) |
|---|---|---:|---|---|---|---|---|
| `easy` (`12`) | Full-roster `pad()` (`100%` staff) | 15 | `12.0 / 12` | `234 / 269` | `125.0 / 125.0 / 125` | `15/15 (100.0%)` | `0/15 (0.0%)` |
| `easy` (`12`) | Uniform `partition_balanced` (`3/4` staff) | 15 | `9.0 / 9` | `198 / 233` | `101.0 / 101.0 / 101` | `15/15 (100.0%)` | `0/15 (0.0%)` |
| `easy` (`12`) | DAgger student-state relabel (Days `1..6`) | 90 | `4.6 / 9` | `198 / 233` | `65.8 / 53.0 / 101` | `17/90 (18.9%)` | `0/90 (0.0%)` |
| `easy` (`12`) | `SolverPolicy` trajectory Days `1..5` | 56 | `5.2 / 9` | `198 / 233` | `70.6 / 61.0 / 101` | `15/56 (26.8%)` | `0/56 (0.0%)` |
| `easy` (`12`) | `SolverPolicy` trajectory all days | 58 | `5.1 / 9` | `198 / 233` | `69.7 / 61.0 / 101` | `15/58 (25.9%)` | `0/58 (0.0%)` |
| `medium` (`20`) | Full-roster `pad()` (`100%` staff) | 15 | `20.0 / 20` | `330 / 365` | `189.0 / 189.0 / 189` | `15/15 (100.0%)` | `0/15 (0.0%)` |
| `medium` (`20`) | Uniform `partition_balanced` (`3/4` staff) | 15 | `15.0 / 15` | `270 / 305` | `149.0 / 149.0 / 149` | `15/15 (100.0%)` | `0/15 (0.0%)` |
| `medium` (`20`) | DAgger student-state relabel (Days `1..6`) | 90 | `5.6 / 11` | `222 / 257` | `73.9 / 77.0 / 117` | `6/90 (6.7%)` | `0/90 (0.0%)` |
| `medium` (`20`) | `SolverPolicy` trajectory Days `1..5` | 69 | `5.9 / 11` | `222 / 257` | `76.2 / 77.0 / 117` | `6/69 (8.7%)` | `0/69 (0.0%)` |
| `medium` (`20`) | `SolverPolicy` trajectory all days | 105 | `5.1 / 11` | `222 / 257` | `70.3 / 69.0 / 117` | `6/105 (5.7%)` | `0/105 (0.0%)` |
| `hard` (`40`) | Full-roster `pad()` (`100%` staff) | 15 | `40.0 / 40` | `570 / 605` | `349.0 / 349.0 / 349` | `15/15 (100.0%)` | `15/15 (100.0%)` |
| `hard` (`40`) | Uniform `partition_balanced` (`3/4` staff) | 15 | `30.0 / 30` | `450 / 485` | `269.0 / 269.0 / 269` | `15/15 (100.0%)` | `15/15 (100.0%)` |
| `hard` (`40`) | DAgger student-state relabel (Days `1..6`) | 180 | `11.7 / 22` | `358 / 393` | `124.3 / 120.0 / 208` | `133/180 (73.9%)` | `0/180 (0.0%)` |
| `hard` (`40`) | `SolverPolicy` trajectory Days `1..5` | 130 | `11.4 / 17` | `294 / 329` | `121.8 / 128.0 / 165` | `95/130 (73.1%)` | `0/130 (0.0%)` |
| `hard` (`40`) | `SolverPolicy` trajectory all days | 176 | `9.6 / 17` | `294 / 329` | `107.1 / 109.0 / 165` | `98/176 (55.7%)` | `0/176 (0.0%)` |

- **Reproducing the X2 `>60%` hard-tier truncation finding**: On `hard` (`40` employees), full-roster `plant_canary` calls require **`349` Qwen2.5 tokens** (`605` chat chars; `100.0%` exceed `cap=96` and even exceed `cap=256`), `3/4`-roster balanced splits require **`269` tokens** (`100.0% > 96`), DAgger own-policy student-state relabels (where the student has not yet narrowed suspects) exceed `cap=96` **`133/180 = 73.9%`** of the time (`0% > 256`, max `208` tokens), and early `SolverPolicy` `hard` calls (Days `1..5`) exceed `cap=96` **`95/130 = 73.1%`** of the time (`81/89 = 91.0%` on Days `1..3`; `98/176 = 55.7%` across all days including late 2-3 suspect endgame splits). Raising `max_new_tokens=256` eliminated `SolverPolicy`-style truncation (`0/180` DAgger relabels `> 256`), while structured policies emit `0` JSON tokens by parameterizing canary splits directly (`6` split modes in `CompactLinearDAggerPolicy`, `3` coverage bins in `TinyMLPPolicy`).

## 3. Uncalibrated SFT Stopping Weights vs EV-Calibrated Breakeven Stopping (`TRAIN_SEEDS 108000..108044`)

| Scope | Episodes (Wins / Abstain) | Daily States | Below Breakeven `1/(1+V)` | Mean `top_p` (Cont vs Accuse) | Uncalibrated SFT Positive Rate (Neg-EV Commits) | EV-Calibrated Breakeven Positive Rate (Neg-EV Commits) |
|---|---|---:|---|---|---|---|
| `easy` | `15 (15 / 0)` | 73 | `50/73 (68.5%)` (mean `0.5281`) | `0.3116` vs `0.9940` | `87/118 (73.7%)` (`19` neg-EV) | `15/73 (20.5%)` (`0` neg-EV) |
| `medium` | `15 (13 / 2)` | 118 | `103/118 (87.3%)` (mean `0.5401`) | `0.2001` vs `1.0000` | `74/129 (57.4%)` (`20` neg-EV) | `13/118 (11.0%)` (`0` neg-EV) |
| `hard` | `15 (14 / 0)` | 131 | `97/131 (74.0%)` (mean `0.5548`) | `0.2666` vs `0.9748` | `91/155 (58.7%)` (`16` neg-EV) | `15/131 (11.5%)` (`0` neg-EV) |
| `all` | `45 (42 / 2)` | 322 | `250/322 (77.6%)` (mean `0.5433`) | `0.2509` vs `0.9891` | `252/402 (62.7%)` (`55` neg-EV) | `43/322 (13.4%)` (`0` neg-EV) |

### Three-Pillar Mechanistic Synthesis: Why Raw-8k DAgger Was Null While Structured DAgger Succeeded

1. **Action-Serialization Bottleneck (`101..349` Tokens vs `0` JSON Tokens)**: Raw autoregressive LLMs must emit exact employee-to-variant JSON dictionaries (`8` tokens/employee), causing `cap=96` truncation on `73.9%` (`133/180`) of `hard` DAgger relabels (`100%` of full-roster `40`-employee calls at `349` tokens) and dispersing SFT gradient across `100..208` formatting/ID tokens per `plant_canary` label (`1595/4000 = 39.9%` of X2 DAgger r1 labels). Structured policies factorize action choice from deterministic assignment construction (`0` JSON tokens).
2. **Implicit Next-Token Stopping Dilution vs Explicit EV-Calibrated Breakeven Head**: Across `322` daily states on `108000..108044`, **`250/322` (`77.6%`)** have `top_p < 1 / (1 + V_known)` (strictly negative accusation EV under `-1.0` wrong-accusation penalty). Uncalibrated SFT (`4x` ending oversampling + `top_p >= 0.32` + survivorship filtering) assigns `commit = 1` to **`62.7%` (`252/402`)** of weighted states including `55` negative-EV states (reproducing `WS4-v2` `-0.457` and `TinyMLP stage1` `-0.2781`). In X2 raw-8k DAgger r1, only `159/4000` (`3.98%`) targets were `accuse` (`23` tokens), and premature student accusations received only implicit next-token cross-entropy toward long investigative calls (`key_weight = 3.0`, equal to positive `accuse` weight). Over `1` epoch (`250` steps, `lr=1e-4`), this failed to override the `4k -> 8k` context-length over-accusation prior: `WS4-dagger-r1-8k-verda` still accused on **`92%` (`46/50`)** of episodes, turning doubled whom-precision (`0.10 -> 0.22`) into negative expected value (`0.2174 * 0.85 - 0.7826 = -0.5978`, observed **`-0.542 +/- 0.214`**). By contrast, EV-calibrated breakeven stopping labels only **`13.4%` (`43/322`)** positive (`0` negative-EV commits) and applies an explicit `3.0x` binary commit-head penalty on premature on-policy student commits (`TinyMLPPolicy` **`+0.8922 [+0.7556, +1.0288]`** over uncalibrated SFT).
3. **Context-Window Instability vs Lossless Working-Memory State**: Evaluating the identical X2 DAgger r1 adapter at `4k` vs `8k` flips accusation rate from `15%` (`-0.101 +/- 0.112`, `n=41`) to `92%` (`-0.542 +/- 0.214`, `n=50`) while sliding-window eviction drops Day-1 rosters and canary maps before `2-3`-day delayed leaks surface. Acting on lossless public-ledger sufficient statistics eliminates prompt-length shift and lets two rounds of on-policy DAgger close student-state covariate shift (`CompactLinearDAggerPolicy` student-state agreement `74.35% -> 98.05%`, held-out gain **`+0.1505 [+0.0869, +0.2141]`** over calibrated BC).

## 4. Offline Verification Commands

```bash
python scripts/tiebreak_dagger_mechanism_audit.py --check
pytest -q tests/test_tiebreak_dagger_mechanism.py
```
