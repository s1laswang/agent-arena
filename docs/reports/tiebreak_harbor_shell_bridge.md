# Harbor Shell Externalization Bridge: Mechanistic Reconciliation on Hard Tier (v1.4)

- Schema: `canary.tiebreak.harbor_shell_bridge.v1` (`tiebreak-harbor-shell-externalization-bridge-v14`)
- Paired Rollout Scope: `hard` tier, `HELDOUT_SEEDS 800000..800029` (`n=30` per arm, `150` total episodes, `150/150` fresh-Env replay verified, `world_secret_tag` `sha256:ebf2f09716cf76d3`, `0` API calls, `0` SolverPolicy calls)
- Panel Fix A Disclosure: Where DEV_SEEDS 0..29 appear in Canary frontier MCP-only comparisons, they are a post-hoc locked, not pre-registered evaluation set; all tiebreak policy training uses strictly disjoint TRAIN_SEEDS [100000, 200000), all paired rollouts in this bridge run strictly on HELDOUT_SEEDS 800000..800029 (n=30), and 0 judge seeds are evaluated.
- Panel Fix E Disclosure: `0 / 19` (`0/19`) open-weight Qwen2.5-1.5B runs beat untrained `0.000` (`HOLD_README_QWEN_ADDENDUM_UNTIL_V100`); all compact policies (`EmpiricalBayesPolicy`, `ScalingLogisticPolicy`, `CompactLinearDAggerPolicy`, `TinyMLPPolicy`) have `is_open_weight_llm = False` and are strictly separated from open-weight LLM runs.

## 1. Frontier Reconciliation: MCP-Only vs Harbor Judge Container on Hard Tier

On `hard` v1.4 (`21` days, `40` employees, `2-3` day leak surfacing delay, `5%` canary fingerprint noise, framing rate `2.0`/day, wrong accusation penalty `-1.0`):

| Investigator / Harness | Regime | Eval Scope | Shell / Ledger | Correct / Accused | Mean Score | Reference | Ratio vs Reference | Key Behavioral Signature |
|---|---|---|---|---:|---:|---:|---|---|
| `gemini-4-carbon` (OpenCode MCP-only) | Regime A (In-Context) | post-hoc locked, not pre-registered dev `0..29` (`n=30`) | Denied (`bash`/`python3` off) | `25/29` (`86.2%`) | `+0.322` | Solver `+0.499` | `65% [24%, 98%]` (luck `72%`) | `8.5` canaries/ep, `68.0` interviews/ep (`53%`), `3` sub-breakeven accuses |
| `gpt-5.5` (OpenCode MCP-only) | Regime A (In-Context) | post-hoc locked, not pre-registered dev `0..29` (`n=30`) | Denied (internal binary-split reasoning) | `28/28` (`100.0%`) | `+0.504` | Solver `+0.499` | `101% [79%, 140%]` | `17.2` canaries/ep, `4.2` interviews/ep, `0` wrong accuses |
| `gemini-4-carbon` (Harbor `opencode-1`) | Regime B (Container Shell) | 10 hard rehearsal tasks (`n=10` valid) | Container `bash`/`python3` | `9/10` (`90.0%`) | `+0.472` | Oracle `+0.506` | `93% [20%, 371%]` | shell in `20/28` pooled valid trials (`28/29` pooled precision) |
| `gemini-4-carbon` (Harbor `opencode-2`) | Regime B (Container Shell) | 10 hard rehearsal tasks (`n=10` valid) | Container `bash`/`python3` | `10/10` (`100.0%`) | `+0.585` | Oracle `+0.506` | `116% [78%, 363%]` | shell in `20/28` pooled valid trials (`28/29` pooled precision) |
| `gemini-4-carbon` (Harbor `opencode-3`) | Regime B (Container Shell) | 10 hard rehearsal tasks (`n=9` valid) | Container `bash`/`python3` | `9/9` (`100.0%`) | `+0.626` | Oracle `+0.506` | `131% [86%, 590%]` | shell in `20/28` pooled valid trials; 08:30 snapshot `n=7` mean `+0.656` |

- Pooled Harbor precision rises from `25/29` (`86.2%`, `4` wrong accusations) in MCP-only to `28/29` (`96.5%`, `1` wrong accusation) across the 3 Harbor runs (run means `+0.472 / +0.585 / +0.626`, mean of means `+0.561`, `+0.239` over MCP-only).
- Why `opencode-2` (`116%`) and `opencode-3` (`131%`) exceed `100%` of `oracle` (`+0.506`): on `hard_task_07` (`task_idx 7`), `5%` canary fingerprint noise (`fingerprint_accuracy = 0.95`) caused `oracle` to take a `-1.00` noise loss on day `15` (whereas on its `9` wins `oracle` averaged `+0.673`).
- Causal Caveat: Harbor rehearsal provides container bash/python3 (used in 20/28 audited trials) and yields 28/29 correct Gemini accusations (+0.472 / +0.585 / +0.626, 93% / 116% / 131% of oracle +0.506) vs 25/29 in MCP-only (+0.322, 65% of solver +0.499); with 10 tasks per run and two disclosed 15 Nov tag updates, shell externalization, tag updates, and sampling variance are reported together without overclaiming single-factor isolation.

## 2. Controlled Paired Rollouts on Hard HELDOUT_SEEDS 800000..800029 (n=30)

To test the state-externalization + arithmetic-Bayes mechanism without tag or sample-size confounds, all 5 arms below play the exact same 30 `hard` worlds (`HELDOUT_SEEDS 800000..800029`, `TemplateProvider`, `world_secret_tag` `sha256:ebf2f09716cf76d3`):

| Arm | Params | Train Seeds | Window | Mean Score [95% CI] | Calibrated Public EV | Correct / Wrong / Abstain | Precision | Sub-BE Accuses | Surfaced Canary Eviction | Mean Accuse Day | Calls / Ep |
|---|---:|---|---|---|---:|---|---|---:|---:|---:|---:|
| `unexternalized_evict_k12_heuristic` | `0` | `untrained` | K=12 steps | `-0.9523` [`-1.0000`, `-0.8570`] | `-0.9518` | `1 / 29 / 0` | `1/30` (`3.3%`) | `29` | `100.0%` (`13/13`) | `4.3` | `35.7` |
| `unexternalized_evict_k16_bayes` | `11` | `102000..102779` | K=16 steps | `+0.0930` [`-0.0053`, `+0.1967`] | `+0.0879` | `12 / 1 / 17` | `12/13` (`92.3%`) | `1` | `93.3%` (`152/163`) | `13.8` | `143.6` |
| `in_context_lossless_heuristic` | `0` | `untrained` | Lossless (0% evict) | `-0.8467` [`-1.0000`, `-0.6440`] | `-0.8997` | `3 / 27 / 0` | `3/30` (`10.0%`) | `28` | `0.0%` (`0/12`) | `4.3` | `35.9` |
| `externalized_empirical_bayes_11p` | `11` | `102000..102779` | Lossless (0% evict) | `+0.5687` [`+0.5167`, `+0.6143`] | `+0.5477` | `30 / 0 / 0` | `30/30` (`100.0%`) | `0` | `0.0%` (`0/67`) | `9.1` | `73.7` |
| `externalized_compact_linear_dagger_785p` | `785` | `109000..109509` | Lossless (0% evict) | `+0.4903` [`+0.3380`, `+0.5850`] | `+0.4184` | `29 / 1 / 0` | `29/30` (`96.7%`) | `4` | `0.0%` (`0/54`) | `10.4` | `77.5` |

## 3. Paired Contrasts and 2x2 Factorial Synergy (State Retention x Arithmetic Bayes)

| Contrast | Paired Score Delta [95% CI] | Calibrated EV Delta | Win / Loss / Tie | Wrong-Accuse Delta |
|---|---|---:|---|---:|
| `shell_bayes_vs_evict_heuristic` | `+1.5210` [`+1.3960`, `+1.6107`] | `+1.4995` | `29 / 1 / 0` | `-29` |
| `pure_state_externalization_effect_under_bayes` | `+0.4757` [`+0.3627`, `+0.5950`] | `+0.4598` | `28 / 0 / 2` | `-1` |
| `pure_arithmetic_bayes_ev_effect_under_lossless` | `+1.4153` [`+1.2263`, `+1.5880`] | `+1.4474` | `28 / 2 / 0` | `-27` |
| `compact_dagger_vs_evict_heuristic` | `+1.4427` [`+1.2747`, `+1.5867`] | `+1.3702` | `28 / 1 / 1` | `-28` |
| `compact_dagger_vs_lossless_heuristic` | `+1.3370` [`+1.1160`, `+1.5270`] | `+1.3181` | `27 / 2 / 1` | `-26` |
| `shell_bayes_vs_compact_dagger` | `+0.0783` [`-0.0387`, `+0.2330`] | `+0.1293` | `16 / 14 / 0` | `-1` |

- **2x2 Factorial Interaction Synergy**: `(+0.5687 - +0.0930) - (-0.8467 - -0.9523) = +0.3700` (`95%` bootstrap CI `[`+0.2140`, `+0.5337`]`).
- **Why Both Ingredients Are Necessary on Hard Tier**:
  1. **Holding Bayes/EV fixed while evicting canary maps (`K=16`)** drops mean score from `+0.5687` to `+0.0930` (`17/30` abstentions, `93.3%` of surfaced canaries missing variant maps), matching 4k GRPO/DAgger Qwen's `79-85%` cautious-abstain collapse (`-0.147` / `-0.101`).
  2. **Holding lossless state fixed while removing calibrated log-LR Bayes + `1/(1+V)` EV stopping** drops mean score from `+0.5687` to `-0.8467` (`27/30` wrong `-1.0` accusations, `28` sub-breakeven accusations), explaining why MCP-only `gemini-4-carbon` (`0%` window eviction, no Python Bayes script) suffers `4` wrong accusations (`+0.322`) whereas Harbor container Python/bash (`20/28` trials) + `EmpiricalBayesPolicy` (`11` params, `+0.5687`) and `CompactLinearDAggerPolicy` (`785` params, `+0.4903`) close the wrong-accusation gap.

## 4. Reproduction and Fast Verification

```bash
python scripts/tiebreak_harbor_shell_bridge.py
python scripts/tiebreak_harbor_shell_bridge.py --check
pytest -q tests/test_tiebreak_harbor_shell_bridge.py
```
