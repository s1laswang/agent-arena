# Public-Channel Value-of-Information (VoI) & Observation-Masking Ablation Audit (`v1.4`)

Keyless CPU-only Leave-One-Out (LOO), single-channel, and counterfactual interview-heavy ablation audit across `2,160` world-paired held-out episodes (`2` policies x `12` channel regimes x `n=90` on `HELDOUT_SEEDS 800000..800029`, `30`/tier across `easy`, `medium`, `hard` under `sha256:ebf2f09716cf76d3`, `TemplateProvider()`). Masking `canary_traps` collapses `EmpiricalBayesPolicy` from **`+0.6223`** to **`+0.0356`** (`-0.5868`, `94.3%` VoI share) and `CompactLinearDAggerPolicy` from **`+0.6632`** to **`+0.0279`** (`-0.6353`, `95.8%` VoI share), proving that **active canary traps carry `95.1%` of decisive held-out policy value**.

- **Seed & Secret Provenance (Panel Fix A)**: All `2,160` primary ablation episodes (plus `216` fresh `Env` replay checks) evaluate strictly on world-paired `HELDOUT_SEEDS 800000..800029` under `sha256:ebf2f09716cf76d3`, all learned weights come strictly from disjoint `TRAIN_SEEDS [100000, 200000)` (`102000..102779` and `109000..109509`), and **`0` `JUDGE_SEEDS` (`900k+`) are touched**. Frontier MCP reference rows on `DEV_SEEDS 0..29` (`hard`, `n=30`) are cited from committed replay-verified runs and are **post-hoc locked, not pre-registered**.
- **Strict Track Separation (Panel Fix E)**: `0 / 19` historical open-weight `Qwen2.5` runs in `experiment_ledger.json` exceed untrained `base` (`0.000`), so the `README.md` Qwen addendum remains withheld (`HOLD_README_QWEN_ADDENDUM_UNTIL_V100`). Both policies audited here (`EmpiricalBayesPolicy`, `CompactLinearDAggerPolicy`; `is_open_weight_llm = False`) are non-LLM parametric policies strictly separated from open-weight `Qwen2.5` LoRA runs.

## 1. Leave-One-Out (LOO) & Counterfactual VoI Matrix (`HELDOUT_SEEDS 800000..800029`, `n=90` / Row)

| Policy (`run_id`) | Condition | Score (`95% CI`) | Paired `Delta` vs Full (`95% CI`) | VoI Share of Full | Acc | Wrong | Abstain | Canaries / Ep | Interview Share |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `EmpiricalBayesPolicy` (`empirical-bayes-v14`) | `full_all_channels` | `+0.6223 [+0.5726, +0.6721]` | `+0.0000 [+0.0000, +0.0000]` | baseline | `91.1%` | `0.0%` | `8.9%` | `9.67` | `8.7%` |
| `EmpiricalBayesPolicy` (`empirical-bayes-v14`) | `loo_no_canary_traps` | `+0.0356 [+0.0026, +0.0685]` | `-0.5868 [-0.6401, -0.5335]` | `94.3%` | `5.6%` | `0.0%` | `94.4%` | `21.00` | `11.7%` |
| `EmpiricalBayesPolicy` (`empirical-bayes-v14`) | `loo_no_doc_membership` | `+0.4833 [+0.4190, +0.5476]` | `-0.1390 [-0.1985, -0.0795]` | `22.3%` | `82.2%` | `1.1%` | `16.7%` | `12.41` | `9.7%` |
| `EmpiricalBayesPolicy` (`empirical-bayes-v14`) | `loo_no_access_logs` | `+0.5709 [+0.4936, +0.6482]` | `-0.0514 [-0.1131, +0.0103]` | `8.3%` | `87.8%` | `3.3%` | `8.9%` | `10.03` | `8.8%` |
| `EmpiricalBayesPolicy` (`empirical-bayes-v14`) | `loo_no_angry_messages` | `+0.5996 [+0.5338, +0.6653]` | `-0.0228 [-0.0848, +0.0392]` | `3.7%` | `92.2%` | `2.2%` | `5.6%` | `9.88` | `8.8%` |
| `EmpiricalBayesPolicy` (`empirical-bayes-v14`) | `loo_no_interviews` | `+0.6128 [+0.5608, +0.6647]` | `-0.0096 [-0.0237, +0.0046]` | `1.5%` | `90.0%` | `0.0%` | `10.0%` | `9.86` | `8.8%` |
| `EmpiricalBayesPolicy` (`empirical-bayes-v14`) | `interviews_heavy_no_canary` | `+0.0053 [-0.0953, +0.1060]` | `-0.6170 [-0.7193, -0.5147]` | `99.1%` | `20.0%` | `13.3%` | `66.7%` | `0.00` | `51.8%` |
| `CompactLinearDAggerPolicy` (`compact-linear-dagger-v14`) | `full_all_channels` | `+0.6632 [+0.6071, +0.7194]` | `+0.0000 [+0.0000, +0.0000]` | baseline | `96.7%` | `1.1%` | `2.2%` | `9.42` | `0.0%` |
| `CompactLinearDAggerPolicy` (`compact-linear-dagger-v14`) | `loo_no_canary_traps` | `+0.0279 [-0.0033, +0.0591]` | `-0.6353 [-0.6962, -0.5745]` | `95.8%` | `3.3%` | `0.0%` | `96.7%` | `20.67` | `0.0%` |
| `CompactLinearDAggerPolicy` (`compact-linear-dagger-v14`) | `loo_no_doc_membership` | `+0.5317 [+0.4647, +0.5987]` | `-0.1316 [-0.1931, -0.0700]` | `19.8%` | `85.6%` | `1.1%` | `13.3%` | `11.66` | `0.0%` |
| `CompactLinearDAggerPolicy` (`compact-linear-dagger-v14`) | `loo_no_access_logs` | `+0.5980 [+0.5225, +0.6735]` | `-0.0652 [-0.1402, +0.0097]` | `9.8%` | `94.4%` | `3.3%` | `2.2%` | `10.68` | `0.0%` |
| `CompactLinearDAggerPolicy` (`compact-linear-dagger-v14`) | `loo_no_angry_messages` | `+0.6557 [+0.5886, +0.7228]` | `-0.0076 [-0.0657, +0.0506]` | `1.1%` | `94.4%` | `2.2%` | `3.3%` | `8.67` | `0.0%` |
| `CompactLinearDAggerPolicy` (`compact-linear-dagger-v14`) | `loo_no_interviews` | `+0.6632 [+0.6071, +0.7194]` | `+0.0000 [+0.0000, +0.0000]` | `0.0%` | `96.7%` | `1.1%` | `2.2%` | `9.42` | `0.0%` |
| `CompactLinearDAggerPolicy` (`compact-linear-dagger-v14`) | `interviews_heavy_no_canary` | `+0.0044 [-0.0654, +0.0743]` | `-0.6588 [-0.7441, -0.5734]` | `99.3%` | `12.2%` | `6.7%` | `81.1%` | `0.00` | `51.5%` |

## 2. Single-Channel Sufficiency Matrix (`only_*`, `HELDOUT_SEEDS 800000..800029`, `n=90` / Row)

| Policy | Single Active Channel | Score (`95% CI`) | Paired `Delta` vs Full (`95% CI`) | Retained Share of Full | Acc | Wrong | Abstain |
|---|---|---:|---:|---:|---:|---:|---:|
| `EmpiricalBayesPolicy` | `only_canary_traps` | `+0.4249 [+0.3523, +0.4974]` | `-0.1974 [-0.2749, -0.1200]` | `68.3%` | `78.9%` | `2.2%` | `18.9%` |
| `EmpiricalBayesPolicy` | `only_doc_membership` | `+0.0279 [-0.0034, +0.0592]` | `-0.5944 [-0.6482, -0.5407]` | `4.5%` | `3.3%` | `0.0%` | `96.7%` |
| `EmpiricalBayesPolicy` | `only_access_logs` | `+0.0000 [+0.0000, +0.0000]` | `-0.6223 [-0.6721, -0.5726]` | `0.0%` | `0.0%` | `0.0%` | `100.0%` |
| `EmpiricalBayesPolicy` | `only_angry_messages` | `+0.0000 [+0.0000, +0.0000]` | `-0.6223 [-0.6721, -0.5726]` | `0.0%` | `0.0%` | `0.0%` | `100.0%` |
| `EmpiricalBayesPolicy` | `only_interviews` | `+0.0000 [+0.0000, +0.0000]` | `-0.6223 [-0.6721, -0.5726]` | `0.0%` | `0.0%` | `0.0%` | `100.0%` |
| `CompactLinearDAggerPolicy` | `only_canary_traps` | `+0.4503 [+0.3755, +0.5252]` | `-0.2129 [-0.2818, -0.1439]` | `67.9%` | `74.4%` | `1.1%` | `24.4%` |
| `CompactLinearDAggerPolicy` | `only_doc_membership` | `+0.0279 [-0.0033, +0.0591]` | `-0.6353 [-0.6962, -0.5745]` | `4.2%` | `3.3%` | `0.0%` | `96.7%` |
| `CompactLinearDAggerPolicy` | `only_access_logs` | `+0.0000 [+0.0000, +0.0000]` | `-0.6632 [-0.7194, -0.6071]` | `0.0%` | `0.0%` | `0.0%` | `100.0%` |
| `CompactLinearDAggerPolicy` | `only_angry_messages` | `+0.0000 [+0.0000, +0.0000]` | `-0.6632 [-0.7194, -0.6071]` | `0.0%` | `0.0%` | `0.0%` | `100.0%` |
| `CompactLinearDAggerPolicy` | `only_interviews` | `+0.0000 [+0.0000, +0.0000]` | `-0.6632 [-0.7194, -0.6071]` | `0.0%` | `0.0%` | `0.0%` | `100.0%` |

## 3. Per-Tier Breakdown on Key Channel Regimes (`easy` / `medium` / `hard`, `n=30` / Cell)

| Policy | Condition | `easy` (`n=30`) | `medium` (`n=30`) | `hard` (`n=30`) | Pooled (`n=90`) |
|---|---|---:|---:|---:|---:|
| `EmpiricalBayesPolicy` | `full_all_channels` | `+0.7287` (`93%`) | `+0.5697` (`80%`) | `+0.5687` (`100%`) | `+0.6223` (`91.1%`) |
| `EmpiricalBayesPolicy` | `loo_no_canary_traps` | `+0.0910` (`13%`) | `+0.0157` (`3%`) | `+0.0000` (`0%`) | `+0.0356` (`5.6%`) |
| `EmpiricalBayesPolicy` | `loo_no_doc_membership` | `+0.6887` (`100%`) | `+0.3723` (`57%`) | `+0.3890` (`90%`) | `+0.4833` (`82.2%`) |
| `EmpiricalBayesPolicy` | `loo_no_access_logs` | `+0.7247` (`93%`) | `+0.5427` (`80%`) | `+0.4453` (`90%`) | `+0.5709` (`87.8%`) |
| `EmpiricalBayesPolicy` | `loo_no_angry_messages` | `+0.7287` (`93%`) | `+0.5890` (`90%`) | `+0.4810` (`93%`) | `+0.5996` (`92.2%`) |
| `EmpiricalBayesPolicy` | `loo_no_interviews` | `+0.7307` (`93%`) | `+0.5487` (`77%`) | `+0.5590` (`100%`) | `+0.6128` (`90.0%`) |
| `EmpiricalBayesPolicy` | `interviews_heavy_no_canary` | `+0.1200` (`40%`) | `-0.0507` (`13%`) | `-0.0533` (`7%`) | `+0.0053` (`20.0%`) |
| `EmpiricalBayesPolicy` | `only_canary_traps` | `+0.5610` (`83%`) | `+0.4673` (`73%`) | `+0.2463` (`80%`) | `+0.4249` (`78.9%`) |
| `CompactLinearDAggerPolicy` | `full_all_channels` | `+0.8203` (`100%`) | `+0.6790` (`93%`) | `+0.4903` (`97%`) | `+0.6632` (`96.7%`) |
| `CompactLinearDAggerPolicy` | `loo_no_canary_traps` | `+0.0837` (`10%`) | `+0.0000` (`0%`) | `+0.0000` (`0%`) | `+0.0279` (`3.3%`) |
| `CompactLinearDAggerPolicy` | `loo_no_doc_membership` | `+0.7460` (`100%`) | `+0.4310` (`63%`) | `+0.4180` (`93%`) | `+0.5317` (`85.6%`) |
| `CompactLinearDAggerPolicy` | `loo_no_access_logs` | `+0.7953` (`100%`) | `+0.7013` (`97%`) | `+0.2973` (`87%`) | `+0.5980` (`94.4%`) |
| `CompactLinearDAggerPolicy` | `loo_no_angry_messages` | `+0.8203` (`100%`) | `+0.6737` (`90%`) | `+0.4730` (`93%`) | `+0.6557` (`94.4%`) |
| `CompactLinearDAggerPolicy` | `loo_no_interviews` | `+0.8203` (`100%`) | `+0.6790` (`93%`) | `+0.4903` (`97%`) | `+0.6632` (`96.7%`) |
| `CompactLinearDAggerPolicy` | `interviews_heavy_no_canary` | `+0.1217` (`17%`) | `-0.0667` (`0%`) | `-0.0417` (`20%`) | `+0.0044` (`12.2%`) |
| `CompactLinearDAggerPolicy` | `only_canary_traps` | `+0.6767` (`90%`) | `+0.3877` (`53%`) | `+0.2867` (`80%`) | `+0.4503` (`74.4%`) |

## 4. Shannon KL-per-Action Theory, Commitment LLR Share & Frontier Bridge

### 4.1 Exact Per-Call KL Divergence (`canary_traps` vs `interview`)

- **3-Arm Canary Trap (`plant_canary`, `max_variants=3`, `p_leak=0.75`)**: Each surfaced exact canary (`easy`/`medium`, `fingerprint_accuracy=1.0`) yields **`1.09861` nats** (`ln 3`), or **`0.82396` nats** expected per planted canary; on `hard` (`fingerprint_accuracy=0.95`), each surfaced canary yields **`0.86544` nats** (`0.64908` nats expected per planted canary).
- **Interview (`interview`, stated `LR=1.2`, `p_evasive_innocent=0.2` -> `p_evasive_mole=0.24`)**: Each interview yields only **`0.00477` nats** (`KL(Bern(0.24) || Bern(0.20))`), making a single planted 3-arm canary worth **`172.6x`** (`easy`/`medium`) to **`135.9x`** (`hard`) as much expected information as an interview (`230.1x` per surfaced exact canary).
- **Terminal Commitment LLR Decomposition (`EmpiricalBayesPolicy`, `n=90`)**: Mean top-vs-runner-up log-odds margin at episode end is **`+5.2383` nats**, of which canary variant hits/misses + canary recipient narrowing supply **`82.0%`** (`+4.2076` pure variant LLR + `+0.0880` canary-recipient LLR), passive regular `doc_membership` supplies `+0.7922` nats, `access_logs` `+0.0245` nats, `angry_messages` `+0.0000` nats, and `interviews` `+0.1261` nats.

### 4.2 Mechanistic Explanation of the Frontier MCP Gap (`gpt-5.5` vs `gemini-4-carbon`)

On post-hoc locked `DEV_SEEDS 0..29` (`hard`, `n=30`, not pre-registered; `results/behaviour_compare_v1.4.md`), `gpt-5.5` (OpenCode over MCP) plants **`17.2`** canaries/ep (`84.5%` slot utilization) with only **`4.2`** interviews/ep (`6%` of calls) to score **`+0.504`** (`28/30` correct, `0` wrong). Under the identical MCP tools and instructions, `gemini-4-carbon` spends **`53%`** of its `128` calls on interviews (`68.0`/ep, stated `LR=1.2`), plants half as many canaries (`8.5`/ep, `31.5%` slot utilization), and drops to **`+0.322`** (`4` wrong accusations). Our `interviews_heavy_no_canary` counterfactual isolates the endpoint of that substitution on `HELDOUT_SEEDS 800000..800029`: reallocating canary slots into interviews (`51.8%` and `51.5%` interview call share) collapses `EmpiricalBayesPolicy` to **`+0.0053`** and `CompactLinearDAggerPolicy` to **`+0.0044`**, confirming that passive channels + `LR=1.2` interviews cannot cross the `1/(1+V)` accusation threshold.

## 5. Offline Reproducibility Commands

```bash
python scripts/tiebreak_channel_ablation_audit.py --check
pytest -q tests/test_tiebreak_channel_ablation.py tests/test_reproduce_tiebreak_all.py
python scripts/reproduce_tiebreak_all.py --check
python scripts/verify_tiebreak_submission.py --strict
```
