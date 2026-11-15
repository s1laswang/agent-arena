# Cross-Scale State-Externalization Law in Canary v1.4

Pure committed-artifact synthesis uniting Canary v1.4 empirical results across open-weight `Qwen2.5-1.5B` (`19` historical runs), strictly separated non-LLM compact policies (`11` to `12,293` parameters), and frontier agents (`gemini-4-carbon` and `gpt-5.5`) across two state-representation regimes.

- **Dev Set Protocol Disclosure (Panel Fix A)**: Frontier MCP-only rows on `0..29` use a **post-hoc locked** dev set (`n=30` hard episodes). All tiebreak training uses disjoint `TRAIN_SEEDS [100000, 200000)` and held-out evaluation uses disjoint `HELDOUT_SEEDS [800000, 800200)`.
- **Strict Track Separation (Panel Fix E)**: `0 / 19` historical open-weight `Qwen2.5-1.5B` runs exceed untrained `base` (`0.000`), so the `README.md` Qwen addendum remains `HOLD_README_QWEN_ADDENDUM_UNTIL_V100`. All `4` compact policies (`is_open_weight_llm = False`) are strictly separated non-LLM structured controls.

## 1. Unified Cross-Scale State-Externalization Matrix

Across more than eight orders of magnitude in model size (`11` parameters to frontier LLMs), multi-day Canary v1.4 performance is governed by whether delayed `(doc_id, variant -> recipients)` intersection sets and EV-breakeven stopping `p* >= 1 / (1 + V_known)` are **externalized into a lossless ledger** rather than left inside a raw conversational transcript:

| Regime | Cohort / Scale | State Representation | Canary-Map Eviction / Tracking Load | Evaluation Scope | Headline Score | Reference Parity |
|---|---|---|---|---|---|---|
| `Regime A (Raw In-Context)` | Open-weight 1.5B LLM (Qwen2.5-1.5B LoRA) (`1.5B`) | None (4k/8k sliding chat window, 69.4% header tax at 4k) | 92-98% (4k), 56-85% (8k) | HELDOUT_SEEDS 800000..800059 (19 historical runs) | `0/19 > 0.000 (v2 -0.457, v3-4k -0.147, v3-8k -0.050/-0.788, DAgger r1 -0.542/-0.101)` | `Below untrained 0.000 across all 19 runs` |
| `Regime A (Raw In-Context)` | Frontier LLM (gemini-4-carbon, OpenCode MCP-only) (`Frontier (closed-weight)`) | Denied (bash/python3 disabled; raw MCP tool history only) | 0% window eviction, but high in-context tracking load (8.5 canaries, 68.0 interviews/ep) | post-hoc locked dev hard 0..29 (n=30) | `+0.322 +/- 0.199 (luck-adjusted +0.360; 25 correct / 4 wrong / 1 abstain)` | `65% [24%, 98%] of paired solver +0.499 (72% luck-adjusted)` |
| `Regime A (Raw In-Context)` | Frontier LLM (gpt-5.5, OpenCode MCP-only) (`Frontier (closed-weight)`) | Denied (internal reasoning tracks binary canary splits: 17.2 canaries, 4.2 interviews/ep) | 0% window eviction; 84.5% canary slot utilization | post-hoc locked dev hard 0..29 (n=30) | `+0.504 +/- 0.064 (28 correct / 0 wrong / 2 text-only non-accusations)` | `101% [79%, 140%] of paired solver +0.499 (84% luck-adjusted)` |
| `Regime B (Externalized State)` | Frontier LLM (gemini-4-carbon, Harbor judge container) (`Frontier (closed-weight) + container bash/python3`) | Container shell/python3 available (used in 20/28 audited trials) | Externalized to container scripts/files; 28/29 valid accusations correct | Harbor rehearsal (3 runs x 10 hard tasks; run 3 has 9 valid trials) | `+0.472 / +0.585 / +0.626 across 3 runs (mean of means +0.561)` | `93% / 116% / 131% of paired oracle +0.506` |
| `Regime B (Externalized State)` | Non-LLM Compact Policies (11, 82, 785, 12,293 params; Panel Fix E separated) (`11 to 12,293`) | AST-isolated <=900-token / 28-dim lossless public sufficient-statistic ledger | 0.0% canary-map eviction, 0.0% employee-roster eviction | World-paired HELDOUT_SEEDS 800000..800059 (n=180; n=90 for 82-param scaling) | `+0.607 (11p), +0.611 (82p), +0.627 (785p), +0.614 (12,293p); 5/5 gates PASS` | `89-92% of SolverPolicy n=90 (+0.682); 89.6-93.5% of each paired SolverPolicy` |

## 2. Regime A: Raw In-Context State (No External Scratchpad)

### 2a. Open-Weight `Qwen2.5-1.5B` (`0 / 19` Historical Runs Above `0.000`)

- **Static Header Token Tax**: `train/render.py` + `to_openai_tools` consumes **`2,842 / 4,096` tokens (`69.4%`)** on static system instructions and the 13-tool OpenAI JSON schema on every turn, leaving only `1,254` body tokens at `4k` (`3-tier` deterministic header mean `2,848.0` vs `966.0` compact, `-66.1%`).
- **FIFO Canary-Map Eviction Before Delayed Leaks Surface**: Across `450` held-out Verda episodes (`800000..800059`), sliding-window truncation evicts **`92-98%`** (`92.22%` to `97.98%`) of `plant_canary` variant-recipient maps at `4k` and **`56-85%`** (`56.73%` to `84.65%`) at `8k` (`100.0%` at `4k` and `96.3%` at `8k` before `2-3d` `hard` leaks surface on `TRAIN_SEEDS 106000..106044`).
- **Action-Serialization `cap=96` Truncation & Stopping Dilution**: On `TRAIN_SEEDS 108000..108044`, `max_new_tokens=96` truncates `133/180` (`73.9%`) of `hard` DAgger `plant_canary` relabels, while raw `DAgger r1` SFT had only `159/4,000` (`3.98%`) explicit `accuse` targets.

| Open-Weight Run | Ledger ID | Eval `n` | Mean Score +/- CI95 | Failure / Collapse Mechanism |
|---|---|---:|---|---|
| `base` (untrained) | `WS4-base-pooled` | 36 | `+0.000` | 3% valid tool calls |
| `v2` (dense 4k SFT) | `WS4-v2-44412 + WS4-v2-off30-68bb` | 172 | `-0.457 +/- 0.086` | 55% blind accuse under 4k header crowding |
| `v3-4k s0` (GRPO) | `WS4-v3-verda-s0-eval` | 180 | `-0.147 +/- 0.063` | 79% abstain under 4k truncation |
| `v3-4k s0 @8k` | `WS4-v3-4k-s0-ctx8k` | 90 | `-0.716 +/- 0.105` | same 4k weights flip to 78% blind accuse at 8k |
| `v3-8k s0 / s2` (abstain mode) | `WS4-v3-8k-s0-3bb7` / `WS4-v3-8k-s2-dbd0` | 90 / 90 | `-0.060` / `-0.050` | Bimodal cautious collapse (`92%` / `93%` abstain) |
| `v3-8k s1 / s3` (reckless mode) | `WS4-v3-8k-s1-ac58` / `WS4-v3-8k-s3-f437` | 90 / 90 | `-0.777` / `-0.788` | Bimodal reckless over-accuse (`94%` / `96%` accuse) |
| `DAgger r1 @8k` (Verda X2) | `WS4-dagger-r1-8k-verda` | 50 | `-0.542 +/- 0.214` | honest null: 92% accuse at 8k despite 43%->68% action match (`0.10 -> 0.22` whom-precision) |
| `DAgger r1 @4k` (Verda X2) | `WS4-dagger-r1-4k-verda` | 41 | `-0.101 +/- 0.112` | honest null: 85% abstain at 4k under 92-98% canary eviction |

### 2b. Frontier MCP-Only (`bash`/`python3` Denied, Post-Hoc Locked Dev Seeds `0..29`)

When container shell tools (`bash`/`python3`) are denied in OpenCode MCP-only on the post-hoc locked `hard` dev set `0..29` (`n=30`), frontier performance separates by in-context binary-splitting discipline:

| Frontier MCP Cohort (`hard`, post-hoc locked `0..29`) | `n` | Score +/- CI95 | Frontier / Solver (`+0.499`) | Luck-Adj. EV (Ratio) | Canaries / Ep | Interviews / Ep (Share) | Correct / Wrong / No-Accuse |
|---|---:|---|---|---|---|---|---|
| `gemini-4-carbon` (OpenCode MCP-only) | 30 | `+0.322 +/- 0.199` | `65% [24%, 98%]` | `+0.360` (`72% [52%, 91%]`) | `8.5` | `68.0` (`53%`) | `25 / 4 / 1` |
| `gpt-5.5` (OpenCode MCP-only) | 30 | `+0.504 +/- 0.064` | `101% [79%, 140%]` | `+0.418` (`84% [67%, 103%]`) | `17.2` | `4.2` (`6%`) | `28 / 0 / 2` (text-only) |
| `SolverPolicy` (paired reference) | 30 | `+0.499 +/- 0.119` | `100%` | `+0.499` (`100%`) | `14.1` | `0.0` (`0%`) | `29 / 1 / 0` |

- **In-Context Working-Memory Controls**: On `medium` (`20` suspects, `14d`), `gemini-4-carbon` OpenCode MCP-only scores `+0.713 +/- 0.042` (`111% [99%, 127%]` of solver `+0.645`, `100%` accuracy), and `inproc` full-history thought-signature replay on `hard` reaches `+0.473 +/- 0.118` (`95% [62%, 140%]`).

## 3. Regime B: Externalized Structured State

### 3a. Frontier Harbor Judge Path (`gemini-4-carbon` With Container `bash`/`python3`)

In the Harbor 0.26.0 rehearsal (`10` hard tasks on one shared build; container `bash`/`python3` available and used in **`20/28`** audited trials), `gemini-4-carbon` achieves **`28/29`** (`96.5%`) valid accusations correct across 3 runs vs `oracle` (`+0.506`):

| Harbor Rehearsal Run | Valid Trials (`n`) | Correct / Accused | Mean Score | Paired Oracle (`all 10`) | Run / Oracle [95% CI] |
|---|---:|---|---|---|---|
| `opencode-1` | 10 | `9 / 10` | `+0.472` | `+0.506` | `93% [20%, 371%]` |
| `opencode-2` | 10 | `10 / 10` | `+0.585` | `+0.506` | `116% [78%, 363%]` |
| `opencode-3` (5 post-08:30 cutoff; 1 infra) | 9 | `9 / 9` | `+0.626` | `+0.506` | `131% [86%, 590%]` |
| `do_nothing` / `stop_early` | 10 / 10 | `0 / 0` | `+0.000` | `+0.506` | `0% [0%, 0%]` |

- **Causal Caveat**: Harbor rehearsal provides container bash/python3 (used in 20/28 audited trials) and yields 28/29 correct Gemini accusations (+0.472 / +0.585 / +0.626, 93% / 116% / 131% of oracle +0.506) vs 25/29 in MCP-only (+0.322, 65% of solver +0.499); with 10 tasks per run and two disclosed 15 Nov tag updates, shell externalization, tag updates, and sampling variance are reported together without overclaiming single-factor isolation.

### 3b. Tiebreak Lossless Compact Policies (`<= 900` State Tokens / `28`-Dim Ledger, Panel Fix E Separated)

Compressing raw observations via `train/compact_render.py` (AST-isolated from `canary.solver` and `canary.world`) into a lossless `<= 900`-token (`444.0` mean / `661` max across `450` Verda episodes, `709` max across `14/21d` full-horizon stress, **`0.0%` canary-map eviction**) / `28`-dim state lifts all `4` tiny non-LLM models (`is_open_weight_llm = False`) to **`89-92%`** of `SolverPolicy` (`+0.682` `n=90` benchmark; `89.6%-93.5%` of each policy's own paired `SolverPolicy`) on `HELDOUT_SEEDS 800000..800059` (`5/5` Panel Fix E gates PASS):

| Non-LLM Policy (`is_open_weight_llm=False`) | Params | Train Seeds -> Held-Out Seeds (`n`) | Before -> After Score | Paired Delta [95% CI] | % of `SolverPolicy` (`n=90` / Paired) | Panel Fix E Gates |
|---|---:|---|---|---|---|---|
| `EmpiricalBayesPolicy` (`empirical-bayes-v14`) | `11` | `102000..102779` -> `800000..800059` (`n=180`) | `-0.421` -> **`+0.607`** | `+1.028 [+0.915, +1.138]` | `89.1%` / `90.6%` | `5/5 PASS` |
| `ScalingLogisticPolicy` (`scaling-logistic-v14`) | `82` | `107000..108999` -> `800000..800029` (`n=90`) | `+0.000` -> **`+0.611`** | `+0.611 [+0.542, +0.679]` | `89.6%` / `89.6%` | `5/5 PASS` |
| `CompactLinearDAggerPolicy` (`compact-linear-dagger-v14`) | `785` | `109000..109509` -> `800000..800059` (`n=180`) | `+0.000` -> **`+0.627`** | `+0.627 [+0.578, +0.676]` | `92.0%` / `93.5%` | `5/5 PASS` |
| `TinyMLPPolicy` (`tiny-mlp-dagger-v14`) | `12,293` | `107000..107599` -> `800000..800059` (`n=180`) | `-0.856` -> **`+0.614`** | `+1.470 [+1.385, +1.554]` | `90.1%` / `93.1%` | `5/5 PASS` |

## 4. Mechanistic Synthesis: Why State Externalization Dominates Raw Scale

1. **Delayed Set-Intersection Eviction Breaks Raw Context Windows**: Because `hard` leaks surface `2-3` days (`~23.8` tool turns) after `plant_canary` behind a `2,842`-token (`69.4%`) header tax, raw `4k`/`8k` transcripts evict `92-98%` / `56-85%` of variant-recipient maps, leaving `Qwen2.5-1.5B` (`0/19 > 0.000`) to either abstain (`-0.050` to `-0.147`) or gamble blindly (`-0.457` to `-0.788`, Verda X2 `DAgger r1` `-0.542` at `8k` and `-0.101` at `4k`).
2. **Without External Scratchpads, Even Frontier LLMs Require High Internal Canary Discipline**: Over MCP-only (`bash`/`python3` denied) on post-hoc locked dev seeds `0..29`, `gpt-5.5` plants `17.2` canaries/ep (`4.2` interviews/ep, `0` wrong accusations, `2/30` text-only non-accusations) to reach `+0.504 +/- 0.064` (`101%` of solver), whereas `gemini-4-carbon` substitutes low-LR interviews (`68.0`/ep vs `8.5` canaries/ep, `4` wrong accusations) and scores `+0.322 +/- 0.199` (`65%` of solver, `72%` luck-adjusted).
3. **Externalizing Sufficient Statistics Collapses the Parameter Requirement by `>10^8x`**: Providing an explicit external state representation restores near-oracle performance at both ends of the scale spectrum: container `bash`/`python3` (`20/28` trials) in the Harbor judge path accompanies `gemini-4-carbon` rising to `+0.472 / +0.585 / +0.626` (`93% / 116% / 131%` of oracle `+0.506`, `28/29` accusations correct), while the AST-isolated `<= 900`-token / `28`-dim public ledger lets `11` to `12,293`-parameter non-LLM policies reach `+0.607` to `+0.627` (`89-92%` of `SolverPolicy`) on world-paired `HELDOUT_SEEDS 800000..800059`.

## 5. Offline Verification Commands

```bash
python scripts/tiebreak_state_externalization_audit.py --check
python scripts/reproduce_tiebreak_all.py --check
python scripts/verify_tiebreak_submission.py --strict
pytest -q tests/test_tiebreak_state_externalization.py
```
