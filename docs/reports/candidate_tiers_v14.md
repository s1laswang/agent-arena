# Canary v1.4 Candidate Tiers, Parity Controls & Negative Gates Audit

**Audit Verdict:** `PASS` (`3/3` gates passed, `0` live API calls, deterministic `Env` step-replay + `10,000`-resample bootstrap verification).

```bash
python scripts/eval_candidate_tiers.py --check
python scripts/eval_candidate_tiers.py
```

## 1. Executive Gate Ledger

| Gate / Candidate Track | Sample & Provenance | Measured Result | Ship Criterion | Decision |
|---|---|---|---|---|
| Harbor judge-path rehearsal (`afterquery-final` `1bc3e281`, `aa1c679e`) | `10/10/9` valid tasks on seeds `900000-900009` (`TABLE.md` + `09:30` final `d0ead011`) | `opencode-1` `93% [20%, 371%]`, `opencode-2` `116% [78%, 363%]`, `opencode-3` final **`131% [86%, 590%]`** (`+0.626` vs `+0.478`, `08:52` `n = 7` snapshot `153% [89%, 411%]`); baselines `+0.000` | Reproduce `65%` MCP-only gap in container path | **Gap did not reproduce; disclosed plainly in README & SUBMISSION** |
| Second frontier family (`gpt-5.5` via OpenCode MCP) | Pre-registered `cf394894`, `n = 30` hard seeds `0-29`, 100% `Env`-replayed | `+0.504 +/- 0.064` = **`101% [79%, 140%]`** raw (`84% [67%, 103%]` luck-adj) vs solver `+0.499` | Test cross-family generalization of hard gap | **Parity with solver (`101%`); narrows gap claim to `gemini-4-carbon` MCP** |
| `v1.5-candidate` social/rumour layer | Paired `hard` dev seeds `0-9` (`n = 10`) | `gemini-4-carbon` rose `61% -> 108%` of solver (`56% -> 98%` luck-adj) | Lower frontier/solver ratio below `v1.4` | **Dropped at Gate B; `v1.4` (`a8f99c2537c91d72`) kept frozen** |
| `expert` `0.70`-fingerprint tier | `justSilas-expert` (`29ca3bc5`), OpenCode `n = 13` | `grok_tactics` `0.36 -> 0.01`, but `gemini-4-carbon` **`84% [52%, 128%]`** luck-adj | Exclude parity on frontier OpenCode | **Dropped at CEO gate; CI spans `100%` parity** |
| `solver_v2` stronger reference | Paired fresh seeds `9000-9399` (`n = 400`/tier, `d42055e`) | Hard `+0.573` vs `+0.561` (`+0.012 +/- 0.029`); medium `+0.019 +/- 0.032` | Hard paired gain `>= +0.080` | **Dropped (`+0.012 < +0.080`); v1 solver near Bayes limit** |
| WS4 small-model tiebreaker (`Qwen2.5-1.5B`) | `7` SFT/GRPO runs + DAgger (`PR #90`), Verda `EUR 104.46` | Best trained mean `-0.050 +/- 0.049` (`v3-8k s2`); DAgger `-0.542 +/- 0.214` vs base `+0.000` | Held-out mean `> 0` with 95% CI excluding `0` | **Bar honestly marked NOT MET (`+0.31` to `+0.41` over SFT v2)** |

## 2. Harbor Judge-Path Rehearsal (`results/harbor/rehearsal/TABLE.md`, Tag `afterquery-final` `1bc3e281`)

- **Build provenance:** SHA `1bc3e281dbfaa494a11e783d0c98369b41b2f675`, tag `afterquery-final`, Harbor `0.26.0`, built `2026-11-15T03:09:17Z`, effective `[agent] timeout_sec = 10800.0` (logged first-match `[verifier] timeout_sec = 120.0` corrected in `BUILD.txt`).
- **Oracle & zero baselines:** 10-task hard oracle mean **`+0.506`** (`9/10` correct; lands inside the pre-computed `+0.39` to `+0.68` 90% build band); `do_nothing` and `stop_early` score **`+0.000`** on `10/10` tasks.
- **Final 3-run OpenCode outcome (`aa1c679e`, `s1-rehearsal-final` `d0ead011`):** Final run means `+0.472`, `+0.585`, **`+0.626`** (`opencode-3` completed `9` valid trials, `5` after the `08:30` cut-off, `1` rate-limit infra-excluded: **`131% [86%, 590%]`** vs same-9-task oracle `+0.478`); final mean of means **`+0.561`**, SD **`0.080`**, range **`0.154`**, pooled valid accusations **`28/29`** correct (`96.6%`). (`TABLE.md` `08:52` partial `n = 7` snapshot: `+0.656` = `153% [89%, 411%]`, mean of means `+0.571`, SD `0.093`, range `0.184`, `26/27` correct.)

| Run | `n` Valid | Infra Excluded | Not Run | Correct / Accused | Mean | Oracle (Same Tasks) | Run / Oracle `[95% CI]` | Paired Diff | Mean (Infra as `0`) |
|---|---:|---:|---:|---|---:|---:|---|---:|---:|
| `opencode-1` | `10` | `0` | `0` | `9 / 10` | `+0.472` | `+0.506` | `93% [20%, 371%]` | `-0.034` | `+0.472` |
| `opencode-2` | `10` | `0` | `0` | `10 / 10` | `+0.585` | `+0.506` | `116% [78%, 363%]` | `+0.079` | `+0.585` |
| `opencode-3` (08:52 snapshot) | `7` | `1` | `2` | `7 / 7` | `+0.656` | `+0.429` | `153% [89%, 411%]` | `+0.227` | `+0.574` |
| `opencode-3` (final, `d0ead011`) | `9` | `1` | `0` | `9 / 9` | `+0.626` | `+0.478` | **`131% [86%, 590%]`** | `+0.148` | `+0.563` |
| `do_nothing` | `10` | `0` | `0` | `0 / 0` | `+0.000` | `+0.506` | `0% [0%, 0%]` | `-0.506` | `+0.000` |
| `stop_early` | `10` | `0` | `0` | `0 / 0` | `+0.000` | `+0.506` | `0% [0%, 0%]` | `-0.506` | `+0.000` |

## 3. Second Frontier Family Parity (`opencode-gpt-5.5`, Pre-Registered `cf394894`, `n = 30`)

- **Replay & provenance check:** `90` episodes (`30` `gpt-5.5` + `30` `gemini-4-carbon` + `30` `solver`) replayed step-by-step through `canary.env.Env('hard', seed)` with `0` mismatches. `gpt-5.5` ran under OpenCode `1.19.5` (`* = deny`, `canary_* = allow`, `$38.91` total across `30` transcripts).
- **Decision-level mechanism (`results/behaviour_compare_v1.4.md`):** `gpt-5.5` plants **`17.2`** canaries/episode (`2.02x` `gemini-4-carbon`'s `8.5`) and spends only **`4.2`** calls on low-LR interviews (**`6%`** of `69` calls vs `gemini-4-carbon`'s **`68.0`** = **`53%`** of `128` calls). `gpt-5.5` was right on **`28/28`** executed accusations; on seeds `[0, 17]` it stated `Accusing e..` in final prose without invoking `canary_accuse` (`score = 0.0`).

| Cohort (`v1.4` Hard, Seeds `0-29`) | `n` | Score +/- 95% CI | Raw / Solver `[95% CI]` | Luck-Adj / Solver `[95% CI]` | Canaries | Interviews (`%` Calls) | Tool Calls | Accuse Day | Correct / Wrong / No Accuse |
|---|---:|---:|---|---|---:|---:|---:|---:|---|
| reference solver | `30` | `+0.499 +/- 0.119` | `100% (ref)` | `100% (ref)` | `14.1` | `0.0` (`0%`) | `84` | `10.6` | `29 / 1 / 0` |
| gpt-5.5, OpenCode over MCP | `30` | `+0.504 +/- 0.064` | `101% [79%, 140%]` | `84% [67%, 103%]` | `17.2` | `4.2` (`6%`) | `69` | `10.2` | `28 / 0 / 2` |
| gemini-4-carbon, OpenCode over MCP | `30` | `+0.322 +/- 0.199` | `65% [24%, 98%]` | `72% [52%, 91%]` | `8.5` | `68.0` (`53%`) | `128` | `13.2` | `25 / 4 / 1` |

## 4. Dropped Candidate Tracks & WS4 Small-Model Tiebreaker Ledger

- **Gate B (`v1.5-candidate` biased employees):** On paired hard seeds `0-9` (`n = 10`), `gemini-4-carbon` jumped from `61%` (`[3%, 104%]`) on `v1.4` to **`108%`** (`[96%, 122%]`, `10/10` correct, `98%` luck-adjusted) because it discounted seeded rumours rather than following them. Dropped at Gate B.
- **CEO Gap Gate (`expert` `0.70` fingerprint readout):** Lowering canary fingerprint accuracy from `0.95` to `0.70` crushed scripted `grok_tactics` (`0.36 -> 0.01`), but `gemini-4-carbon` (`n = 13`, OpenCode) held **`84% [52%, 128%]`** luck-adjusted. Dropped rather than cherry-picked.
- **Reference Optimality Gate (`solver_v2` & `gpt-5.5`-habit solver):** On `n = 400` fresh seeds `9000-9399`, `solver_v2` gained only **`+0.012 +/- 0.029`** on hard (`0.573` vs `0.561`, below the `+0.080` bar) and **`+0.019 +/- 0.032`** on medium (`0.636` vs `0.617`); best linear stopping rule `p >= a + b*V` added `+0.005` hard / `+0.004` medium. Re-parameterising the solver on 15 Nov to mimic `gpt-5.5` (`+0.546` on seeds `0-29`) scored `0.496 +/- 0.036` vs `0.561 +/- 0.032` on fresh seeds `9000-9399`, confirming `canary/solver/` should stay frozen.
- **Instruction Freeze Gate (`docs/DIFFICULTY.md`):** Proposed edits `P1-P12` were held back so judged text matches committed runs; only `P0` (`[agent] timeout_sec = 10800` in `512836b9`) and the two disclosed 15 Nov clarifications (`1bc3e281`, affecting `28/3841` = `0.73%` of headline OpenCode calls) shipped.

| WS4 Small-Model Cohort (`Qwen2.5-1.5B`) | Context | Held-Out `n` | Held-Out Score +/- 95% CI | Status vs Untrained Base (`0.000`) |
|---|---|---:|---:|---|
| `base` (untrained; `3%` valid tool calls, `100%` abstain) | `4k` | `36` | `+0.000 +/- 0.000` | Reference base (`0.000`) |
| `v1_j4_sft` (FR8 V100 solver SFT) | `4k` | `12` | `-0.250 +/- 0.256` | Below base (protocol learned: `0.08 -> 0.99` valid) |
| `v2_sft_dense_4k` | `4k` | `172` | `-0.457 +/- 0.086` | Below base (`< 0.000`) |
| `v3_4k_s0_grpo` | `4k` | `180` | `-0.147 +/- 0.063` | Below base (`< 0.000`) |
| `v3_4k_s1_grpo` | `4k` | `25` | `-0.209 (interim n=25: -0.240)` | Below base (`< 0.000`) |
| `v3_8k_s0_grpo` | `8k` | `90` | `-0.060 +/- 0.054` | Below base (`< 0.000`) |
| `v3_8k_s1_grpo` | `8k` | `90` | `-0.777 +/- 0.118` | Below base (`< 0.000`) |
| `v3_8k_s2_grpo` | `8k` | `90` | `-0.050 +/- 0.049` | Below base (`< 0.000`) |
| `v3_8k_s3_grpo` | `8k` | `90` | `-0.788 +/- 0.117` | Below base (`< 0.000`) |
| `dagger_round1_8k_partial` (`PR #90`, own-state solver labels) | `8k` | `50` | `-0.542 +/- 0.214` | Honest null (`< 0.000`; level with `v3-4k` at `4k`) |

- **WS4 takeaway (`VERDA.md`, `EUR 104.46` across `9` instances):** Decision-point GRPO (`v3`) recovered `+0.310` to `+0.408` over reckless `v2` SFT and separated H100 `~650`-step runs from A100 `~350`-step runs by **`+0.728 +/- 0.134`** paired on shared-secret worlds (`n = 90`), while honestly missing the `> 0.000` tiebreak bar.
