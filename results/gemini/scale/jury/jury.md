# Canary Calibrated 3-Model Jury (`scale/jury`)

*Generated 2026-11-15T05:02:34+0200 at `d165e3ec`; judges `gemini-4-hydrogen, gemini-4-argon, gemini-3.8-flash` (served `gemini-3.8-flash, gemini-4-argon, gemini-4-hydrogen`, NO carbon); ledger run ids: jury-20261115-032128, jury-20261115-033046, jury-20261115-034128, jury-20261115-035128, jury-20261115-035341, jury-20261115-040027, jury-20261115-041035, jury-20261115-042644, jury-20261115-043439, jury-20261115-043712, jury-20261115-044533, jury-20261115-045346.*

## Headline Summary

- **Scale & provenance:** **6,975 independent blind structured judgments** across **801 valid committed episodes** (8 infra-error episodes excluded) and **1,423 high-regret decision steps** (`regret >= 0.01`), of which **403** carry an explicit `canary/analysis/tags.py` failure tag and **1,020** are untagged heuristic-regret steps (`s.tags == []`).
- **Inter-judge agreement (primary `medium` jury, n=1,423):** 9-class Fleiss' $\kappa = 0.736$ (95% bootstrap CI `[0.711, 0.759]`, episode-cluster CI `[0.703, 0.765]`, observed agreement 81.3%); on code-tagged steps (n=403) Fleiss' $\kappa = 0.885$ (`[0.853, 0.915]`); binary mistake vs `not_a_mistake` Fleiss' $\kappa = 0.674$.
- **Accuracy vs `tags.py` & ensemble gain:** On code-tagged steps (n=403), majority vote achieves **84.9% [81.0%, 88.0%]** (ECE `0.068`), and across all 1,423 high-regret steps code-consistent accuracy is **91.1% [89.6%, 92.5%]** (ECE `0.091`).
- **Solver regret recovery:** Whereas one-pass `atlas_blind` cited 4% of high-regret steps covering 21% of regret, per-decision Jury evaluation flags **72.3%** of high-regret steps as mistakes, capturing **87.3%** of total high-regret solver loss.

## 1. Per-Judge & Majority-Vote Accuracy (`thinking_level=medium`)

| Judge | Served `model_version` | Tagged acc (n=403) | 95% Wilson CI | All-step acc (n=1423) | 95% Wilson CI | ECE (tagged) | ECE (all) | Regret flagged |
|---|---|---|---|---|---|---|---|---|
| `gemini-4-hydrogen` | `gemini-4-hydrogen` | 85.1% | [81.3%, 88.3%] | 92.3% | [90.8%, 93.6%] | 0.083 | 0.027 | 87.2% |
| `gemini-4-argon` | `gemini-4-argon` | 84.6% | [80.8%, 87.8%] | 86.7% | [84.9%, 88.4%] | 0.101 | 0.091 | 84.2% |
| `gemini-3.8-flash` | `gemini-3.8-flash` | 85.1% | [81.3%, 88.3%] | 91.0% | [89.4%, 92.4%] | 0.102 | 0.023 | 87.3% |
| **3-Model Jury (majority)** | ensemble (n=3) | **84.9%** | **[81.0%, 88.0%]** | **91.1%** | **[89.6%, 92.5%]** | **0.068** | **0.091** | **87.3%** |

### Per-Tag Recall & Precision (3-Model Majority Vote)

| `tags.py` tag | Support (HR steps) | Predicted | Recall (95% CI) | Precision (95% CI) | F1 |
|---|---|---|---|---|---|
| `premature_accusation` | 173 | 171 | 83.2% [77.0%, 88.1%] | 84.2% [78.0%, 88.9%] | 0.8372 |
| `uninformative_canary` | 206 | 227 | 93.7% [89.5%, 96.3%] | 85.0% [79.8%, 89.1%] | 0.8915 |
| `over_restriction` | 24 | 5 | 20.8% [9.2%, 40.5%] | 100.0% [56.5%, 100.0%] | 0.3448 |
| `ignored_delay` | 5 | 2 | 0.0% [0.0%, 43.5%] | 0.0% [0.0%, 65.8%] | 0.0 |
| `decoy_chase` | 0 | 9 | - [-, -] | 0.0% [0.0%, 29.9%] | - |
| `budget_waste` | 0 | 2 | - [-, -] | 0.0% [0.0%, 65.8%] | - |

## 2. Inter-Judge Agreement (Fleiss' $\kappa$, Pairwise Cohen's $\kappa$, & Agreement Tiers)

| Pair | All HR steps (n=1423) agree (95% CI) | Cohen's $\kappa$ (all) | Tagged steps (n=403) agree (95% CI) | Cohen's $\kappa$ (tagged) |
|---|---|---|---|---|
| `gemini-4-hydrogen` vs `gemini-4-argon` | 84.5% [82.6%, 86.3%] | 0.780 | 93.5% [90.7%, 95.6%] | 0.898 |
| `gemini-4-hydrogen` vs `gemini-3.8-flash` | 82.6% [80.6%, 84.5%] | 0.755 | 93.0% [90.1%, 95.2%] | 0.890 |
| `gemini-4-argon` vs `gemini-3.8-flash` | 76.7% [74.5%, 78.9%] | 0.676 | 91.6% [88.4%, 93.9%] | 0.867 |

### Accuracy Stratified by Jury Consensus Tier

| Consensus tier | Steps (share) | All-step acc (95% CI) | Tagged steps | Tagged acc (95% CI) |
|---|---|---|---|---|
| 3/3 unanimous | 1031 (72.5%) | 92.9% [91.2%, 94.3%] | 360 | 90.0% [86.5%, 92.7%] |
| 2/3 majority | 378 (26.6%) | 88.1% [84.4%, 91.0%] | 41 | 43.9% [29.9%, 59.0%] |
| 1-1-1 split | 14 (1.0%) | 42.9% [21.4%, 67.4%] | 2 | 0.0% [0.0%, 65.8%] |

## 3. Agreement with Solver Regret

| Judges voting mistake (`!= not_a_mistake`) | Steps (n) | Mean solver regret (95% bootstrap CI) | Total solver regret | Share carrying `tags.py` tag |
|---|---|---|---|---|
| `0 / 3` | 289 | 0.0789 [0.059, 0.103] | 22.79 | 5.9% |
| `1 / 3` | 97 | 0.0564 [0.035, 0.082] | 5.47 | 6.2% |
| `2 / 3` | 191 | 0.0689 [0.044, 0.099] | 13.15 | 8.9% |
| `3 / 3` | 846 | 0.2164 [0.187, 0.250] | 183.07 | 42.9% |

## 4. Accuracy as a Function of Judge Model & Thinking Level (paired n=451, tagged=394)

| Judge model | `thinking_level` | Tagged acc (95% CI) | All-step acc (95% CI) | ECE (tagged) | Mean thinking tokens | Mean latency (s) | Cost ($ total) |
|---|---|---|---|---|---|---|---|
| `gemini-4-hydrogen` | `low` | 85.0% [81.2%, 88.2%] | 85.6% [82.0%, 88.5%] | 0.094 | 734 | 4.05 | $6.22 |
| `gemini-4-argon` | `low` | 83.0% [79.0%, 86.4%] | 83.6% [79.9%, 86.7%] | 0.100 | 0 | 6.49 | $5.06 |
| `gemini-3.8-flash` | `low` | 86.6% [82.8%, 89.6%] | 85.8% [82.3%, 88.7%] | 0.048 | 43 | 2.65 | $1.82 |
| `gemini-4-hydrogen` | `medium` | 84.8% [80.9%, 88.0%] | 85.4% [81.8%, 88.3%] | 0.086 | 1842 | 8.23 | $9.92 |
| `gemini-4-argon` | `medium` | 84.3% [80.3%, 87.5%] | 84.5% [80.8%, 87.5%] | 0.103 | 255 | 8.82 | $6.18 |
| `gemini-3.8-flash` | `medium` | 84.8% [80.9%, 88.0%] | 85.4% [81.8%, 88.3%] | 0.105 | 1235 | 10.67 | $3.75 |
| `gemini-4-hydrogen` | `high` | 83.8% [79.8%, 87.1%] | 84.3% [80.6%, 87.3%] | 0.090 | 2539 | 11.90 | $12.37 |
| `gemini-4-argon` | `high` | 83.0% [79.0%, 86.4%] | 83.2% [79.4%, 86.3%] | 0.122 | 1844 | 25.53 | $13.29 |
| `gemini-3.8-flash` | `high` | 86.0% [82.3%, 89.1%] | 86.5% [83.0%, 89.3%] | 0.097 | 3908 | 30.00 | $8.28 |

| Thinking level | 3-Model Majority Tagged Acc (95% CI) | 3-Model Majority All-Step Acc (95% CI) | Fleiss' $\kappa$ (all 9-class, 95% CI) | Fleiss' $\kappa$ (tagged, 95% CI) |
|---|---|---|---|---|
| `low` | 86.3% [82.5%, 89.3%] | 86.0% [82.5%, 88.9%] | 0.811 [0.776, 0.846] | 0.828 [0.793, 0.865] |
| `medium` | 84.5% [80.6%, 87.8%] | 84.9% [81.3%, 87.9%] | 0.872 [0.842, 0.902] | 0.883 [0.851, 0.913] |
| `high` | 83.8% [79.8%, 87.1%] | 84.3% [80.6%, 87.3%] | 0.889 [0.861, 0.916] | 0.891 [0.860, 0.921] |

## 5. Blindness, Honesty & Keyless Reproduction

- **Blind causal trajectory:** Every judge saw only public tier rules, agent tool calls/results up to `>>> t`, and sanitized agent `says:` text. No `REGRET`, `tags`, `top=`, `mole:`, `true_mole`, `solver`, or final `correct`/`score` outcome ever entered a prompt (`tests/test_gemini_lab_jury.py`).
- **Model-model evaluation caveat:** All verdicts are model judgments evaluated against deterministic code tags (`canary/analysis/tags.py`) and Bayesian reference solver regret (`canary/solver/regret.py`); no human-agreement claim is made here.
- **Keyless replay (0 API calls):**
  ```bash
  uv run --extra llm --extra dev --extra plot python -m canary.gemini.jury --replay
  ```
