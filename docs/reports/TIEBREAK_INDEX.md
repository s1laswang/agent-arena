# Canary Tiebreaker Judge Index (`v1.4`)

Single-page map of all Canary tiebreak reports, committed JSON artifacts, policy tracks, seed/secret provenance disclosures, and `13/13` offline core verification gates (`0` API calls).

```bash
python scripts/reproduce_tiebreak_all.py --check
```

## 1. Executive Headline and Honest Track Separation

Per `README.md` and `docs/agents/PANEL-0500.md` (`Fix A` and `Fix E`), open-weight autoregressive LLM runs and structured non-LLM compact policies are reported on strictly separated tracks under identical machine-checked gates:

1. **Open-Weight Autoregressive LLM Track (`Qwen2.5-1.5B-Instruct` / `Qwen2.5-0.5B`)**: **`0 / 19` historical FR8 V100 and Verda A100/H100 runs beat untrained base `0.000`** (`0 / 19` `VERIFIED_IMPROVEMENT`; `README.md` Qwen addendum remains withheld). LoRA SFT and decision-point GRPO fixed tool protocol syntax (`0.03 -> 1.00` valid tool calls) and recovered `+0.249` to `+0.408` over blind-accusing `v2` (`-0.457 +/- 0.086`, `n=172`), including world-paired `v3-8k-s0 - v3-8k-s3 = +0.728 +/- 0.134` (`n=90` under shared secret `1ca0c2a64d`), while split on-policy Verda X2 `DAgger r1` ended as an honest null (`WS4-dagger-r1-8k-verda` `-0.542 +/- 0.214`, `n=50`; `WS4-dagger-r1-4k-verda` `-0.101 +/- 0.112`, `n=41`). All `19` runs (including `5` `n=0` OOM, zero-variance, spot-preemption, and reaper-deletion failures) are logged without omission.
2. **Non-LLM Compact Neural and Parametric Policies (`4 / 4` Passing 5/5 Strict Gates, Never Conflated With Qwen2.5 LoRA)**: once raw 4k/8k JSON transcript truncation (`2,842 / 4,096` header tokens, `98.0%` 4k canary-map eviction) is replaced by lossless public-observation features, four AST-isolated (`0` `canary.solver` / `canary.world` inference imports) policies trained strictly on `TRAIN_SEEDS [100000, 200000)` pass all 5 Panel Fix E gates on world-paired `HELDOUT_SEEDS [800000, 800200)` (`sha256:ebf2f09716cf76d3`, `100%` `Env` replay-verified):
   - **`CompactLinearDAggerPolicy`** (`compact-linear-dagger-v14`, `785` params, `n=180`): **`+0.000 -> +0.627`** (`[+0.575, +0.672]`), paired delta **`+0.627 [+0.578, +0.676]`** (`+0.150` over calibrated offline BC, `+0.109` over survivorship SFT).
   - **`TinyMLPPolicy`** (`tiny-mlp-dagger-v14`, 2-layer neural MLP `28 -> 128 -> 64 -> 5`, `12,293` params, `n=180`): **`-0.856 -> +0.614`** (`[+0.565, +0.663]`), paired delta **`+1.470 [+1.385, +1.554]`** (`+0.892 [+0.756, +1.029]` over uncalibrated `r0` SFT `-0.278`).
   - **`ScalingLogisticPolicy`** (`scaling-logistic-v14`, `82` params at `N_train=900`, `n=90`): **`+0.000 -> +0.611`** (`[+0.542, +0.679]`), paired delta **`+0.611 [+0.542, +0.679]`** (`89.6%` of `SolverPolicy` `+0.682`).
   - **`EmpiricalBayesPolicy`** (`empirical-bayes-v14`, `11` params, `n=180`): **`-0.421 -> +0.607`** (`[+0.559, +0.648]`), paired delta **`+1.028 [+0.915, +1.141]`**, luck-adjusted EV delta **`+1.000`** (`+1.226 [+1.139, +1.308]` zero-shot across `4` unseen adversarial mole families, `n=120`).

## 2. Seed-Split and World-Secret Provenance Disclosure (Panel Fix A)

- **`TRAIN_SEEDS [100000, 200000)` (`100000..199999`)**: exclusive source for all SFT/DPO/DAgger/GRPO rollouts, likelihood estimation, and stopping-threshold calibration (`0` overlap with held-out or judge seeds).
- **`HELDOUT_SEEDS [800000, 800200)` (`800000..800199`)**: exclusive primary evaluation range for all tiebreaker before/after claims (`n >= 30`, identical non-placeholder `world_secret_tag` between `before` and `after`).
- **`DEV_SEEDS 0..29` Disclosure**: `DEV_SEEDS [0, 10000)` use the public key in `canary/world.py`. Wherever `DEV_SEEDS 0..29` appear in frontier comparison tables (`docs/reports/tiebreak_vs_frontier.md`), that slice is **post-hoc locked, not pre-registered** (locked immediately after committing `data/runs/committed/v1.4/`).
- **`JUDGE_SEEDS [900000, inf)`**: `0` judge seeds touched across all tiebreak JSON artifacts and scripts.

## 3. Summary Table: Policies and Key Runs Across Both Tracks

| Track | Run ID / Cohort | Policy / Architecture | Train Seeds | Held-Out Seeds (`n`) | Held-Out Score (`95% CI`) | Paired Delta (`95% CI`) | Gate Status |
|---|---|---|---|---|---:|---:|---|
| Open-Weight LLM | `WS4-base-pooled` | `Qwen2.5-1.5B-Instruct` (untrained) | none | `800000..800012` (`36`) | `0.000 +/- 0.000` | two-sample baseline (`0.03` valid calls) | `BASELINE_CAVEATED` |
| Open-Weight LLM | `J4-v1-44397` | `Qwen2.5-1.5B` LoRA (v1.3 prefix 4k SFT) | J3v2 solver | `v1.3` held-out (`12`) | `-0.250 +/- 0.256` | two-sample (`0.08 -> 0.99` valid calls) | `NEGATIVE_REWARD_PROTOCOL_GAIN` |
| Open-Weight LLM | `WS4-v2` (pooled `44412` + `off30`) | `Qwen2.5-1.5B` LoRA (dense 4k SFT) | `TRAIN_SEEDS` | `800000..800059` (`172`) | `-0.457 +/- 0.086` | two-sample (`94/172` accused, `8/94` correct) | `NEGATIVE_BLIND_ACCUSE` |
| Open-Weight LLM | `WS4-v3-verda-s0-eval` | `Qwen2.5-1.5B` LoRA (4k GRPO, `609` steps) | `TRAIN_SEEDS` | `800000..800059` (`180`) | `-0.147 +/- 0.063` | two-sample `+0.310 +/- 0.107` vs `v2` | `NEGATIVE_4K_TRUNCATION_PERSISTS` |
| Open-Weight LLM | `WS4-v3-4k-s1-44572` | `Qwen2.5-1.5B` LoRA (4k GRPO, `192` steps, V100) | `TRAIN_SEEDS` | `800000..800027` (`82`) | `-0.209 +/- 0.094` | two-sample `+0.249 +/- 0.127` vs `v2` | `NEGATIVE_FLAT_V100_REPLICATE` |
| Open-Weight LLM | `WS4-v3-4k-s0-ctx8k` | `Qwen2.5-1.5B` LoRA (4k adapter at `8k` ctx) | `TRAIN_SEEDS` | `800000..800029` (`90`) | `-0.716 +/- 0.105` | two-sample `-0.568 +/- 0.123` vs `4k` | `NEGATIVE_INFERENCE_CTX_CONFOUND` |
| Open-Weight LLM | `WS4-v3-8k-s0-3bb7` / `s2-dbd0` | `Qwen2.5-1.5B` LoRA (8k GRPO, `637`/`693` steps) | `TRAIN_SEEDS` | `800000..800029` (`90` ea) | `-0.060` / `-0.050` | paired `s0 - s3 = +0.728 +/- 0.134` (`1ca0c2a64d`) | `NEGATIVE_ABSTAIN_COLLAPSE` |
| Open-Weight LLM | `WS4-v3-8k-s1-ac58` / `s3-f437` | `Qwen2.5-1.5B` LoRA (8k GRPO, `371`/`344` steps) | `TRAIN_SEEDS` | `800000..800029` (`90` ea) | `-0.777` / `-0.788` | paired `s3 - 4k@8k = -0.073 +/- 0.173` (`1ca0c2a64d`) | `NEGATIVE_PAIRED_8K_NULL` |
| Open-Weight LLM | `WS4-dagger-r1-8k-verda` | `Qwen2.5-1.5B` LoRA (DAgger r1, `8k` cap `256`) | `170000..170099` | partial `n=50` (`1ca0c2a64d`) | `-0.542 +/- 0.214` | paired `+0.242 +/- 0.304` (`n=43` vs `4k@8k`) | `NEGATIVE_DAGGER_HONEST_NULL` |
| Open-Weight LLM | `WS4-dagger-r1-4k-verda` | `Qwen2.5-1.5B` LoRA (DAgger r1, `4k` cap `256`) | `170000..170099` | partial `n=41` (`1ca0c2a64d`) | `-0.101 +/- 0.112` | paired `-0.031 +/- 0.139` (`n=32` vs `4k@4k`) | `NEGATIVE_DAGGER_HONEST_NULL` |
| Non-LLM Neural | `tiny-mlp-dagger-v14` | `TinyMLPPolicy` (`28->128->64->5`, `12,293` params) | `107000..107599` | `800000..800059` (`180`) | `+0.614 [+0.565, +0.663]` | `+1.470 [+1.385, +1.554]` (`sha256:ebf2f097`) | `5/5 PASS` (`PROMOTED_TRACK1_NEURAL`) |
| Non-LLM Compact | `compact-linear-dagger-v14` | `CompactLinearDAggerPolicy` (`785` params) | `109000..109509` | `800000..800059` (`180`) | `+0.627 [+0.575, +0.672]` | `+0.627 [+0.578, +0.676]` (`sha256:ebf2f097`) | `5/5 PASS` (`VERIFIED_IMPROVEMENT`) |
| Non-LLM Compact | `scaling-logistic-v14` | `ScalingLogisticPolicy` (`82` params, `N=900`) | `107000..108999` | `800000..800029` (`90`) | `+0.611 [+0.542, +0.679]` | `+0.611 [+0.542, +0.679]` (`sha256:ebf2f097`) | `5/5 PASS` (`PASS_NON_LLM_CONTROL`) |
| Non-LLM Compact | `empirical-bayes-v14` | `EmpiricalBayesPolicy` (`11` params) | `102000..102779` | `800000..800059` (`180`) | `+0.607 [+0.559, +0.648]` | `+1.028 [+0.915, +1.141]` (`sha256:ebf2f097`) | `5/5 PASS` (`VERIFIED_IMPROVEMENT`) |

## 4. Complete Report, JSON Artifact, and Verifier Map

| Deliverable / Focus | Markdown Report | Backing JSON Artifact | Code / Policy Module | One-Line Offline Check |
|---|---|---|---|---|
| Unified All-Gate Runner (`13/13` Core Gates) | `docs/reports/TIEBREAK_INDEX.md` | all `results/tiebreak/**/*.json` | `scripts/reproduce_tiebreak_all.py` | `python scripts/reproduce_tiebreak_all.py --check` |
| Submission Provenance & AST Gate | `docs/reports/tiebreak_small_model.md` | `results/tiebreak/experiment_ledger.json` | `scripts/verify_tiebreak_submission.py` | `python scripts/verify_tiebreak_submission.py --strict` |
| Complete 19-Run Ledger & Manifests | `docs/reports/tiebreak_small_model.md` | `results/tiebreak/experiment_ledger.json` | `scripts/tiebreak_experiment_ledger.py` | `python scripts/tiebreak_experiment_ledger.py --check` |
| Panel Fix E 5-Gate Readiness Pack | `docs/reports/tiebreak_panel_e_addendum.md` | `results/tiebreak/addendum_readiness.json` | `scripts/tiebreak_addendum_pack.py` | `python scripts/tiebreak_addendum_pack.py --check` |
| Frontier vs Tiebreak Failure Convergence | `docs/reports/tiebreak_vs_frontier.md` | `results/tiebreak/frontier_comparison/comparison_summary.json` | `scripts/tiebreak_vs_frontier_comparison.py` | `python scripts/tiebreak_vs_frontier_comparison.py --check` |
| Verda Multi-Seed 8k/4k Belief-Replay Audit | `docs/reports/tiebreak_verda_multiseed.md` | `results/tiebreak/verda_multiseed/multiseed_summary.json` | `scripts/tiebreak_verda_multiseed_audit.py` | `python scripts/tiebreak_verda_multiseed_audit.py --check` |
| Raw vs Compact Context-Confound Audit | `results/tiebreak/context_confound/report.md` | `results/tiebreak/context_confound/audit_summary.json` | `scripts/tiebreak_context_confound_audit.py` | `python scripts/tiebreak_context_confound_audit.py --check` |
| Zero-Shot Cross-Mole Generalization (`5` Regimes) | `docs/reports/tiebreak_cross_mole_generalization.md` | `results/tiebreak/cross_mole_generalization/generalization_summary.json` | `scripts/tiebreak_cross_mole_generalization.py` | `python scripts/tiebreak_cross_mole_generalization.py --check` |
| Prior J4 / WS4 / Verda Forensics | `results/tiebreak/forensics_prior_runs.md` | `results/tiebreak/forensics_prior_runs.json` | `scripts/tiebreak_forensics.py` | `python scripts/tiebreak_forensics.py --verify-json results/tiebreak/forensics_prior_runs.json --verify-md results/tiebreak/forensics_prior_runs.md` |
| Sample-Efficiency Scaling & Taxonomy | `results/tiebreak/scaling/table.md` | `results/tiebreak/scaling/scaling_summary.json` | `scripts/tiebreak_scaling_calibration.py` | `python scripts/reproduce_tiebreak_all.py --only tiebreak_scaling_calibration` |
| TinyMLP 2-Layer Neural DAgger (`n=180`) | `docs/reports/tiebreak_neural_mlp_dagger.md` | `results/tiebreak/neural_mlp_dagger/mlp_summary.json` | `train/neural_mlp_tiebreak.py` | `python -m train.neural_mlp_tiebreak --check` |
| Delayed-Leak & Hard Fingerprint-Noise Audit (`n=90`) | `docs/reports/tiebreak_delayed_leak_noise.md` | `results/tiebreak/delayed_leak_noise/noise_audit_summary.json` | `scripts/tiebreak_delayed_leak_noise_audit.py` | `python scripts/tiebreak_delayed_leak_noise_audit.py --check` |
| Raw-8k vs Structured DAgger Mechanism & Cap Audit | `docs/reports/tiebreak_dagger_mechanism.md` | `results/tiebreak/dagger_mechanism/dagger_mechanism_summary.json` | `scripts/tiebreak_dagger_mechanism_audit.py` | `python scripts/tiebreak_dagger_mechanism_audit.py --check` |
| 19-Run Open-Weight Failure Taxonomy Matrix | `docs/reports/tiebreak_failure_taxonomy.md` | `results/tiebreak/failure_taxonomy/failure_taxonomy_matrix.json` | `scripts/tiebreak_failure_taxonomy_matrix.py` | `python scripts/tiebreak_failure_taxonomy_matrix.py --check` |
| Working-Memory & Header Token-Tax Audit (`45` TRAIN) | `docs/reports/tiebreak_working_memory.md` | `results/tiebreak/working_memory/working_memory_summary.json` | `scripts/tiebreak_working_memory_audit.py` | `python scripts/tiebreak_working_memory_audit.py --check` |
| Cross-Scale State-Externalization Law Synthesis | `docs/reports/tiebreak_state_externalization.md` | `results/tiebreak/state_externalization/externalization_summary.json` | `scripts/tiebreak_state_externalization_audit.py` | `python scripts/tiebreak_state_externalization_audit.py --check` |
| Keyless MCP Wire-JSON Equivalence Parity (`360/360`) | `docs/reports/tiebreak_mcp_wire_parity.md` | `results/tiebreak/mcp_wire_parity/mcp_wire_parity_summary.json` | `scripts/tiebreak_mcp_wire_parity.py` | `python scripts/tiebreak_mcp_wire_parity.py --check` |
| Harbor Shell Externalization Bridge (`150/150` Hard) | `docs/reports/tiebreak_harbor_shell_bridge.md` | `results/tiebreak/harbor_shell_bridge/harbor_bridge_summary.json` | `scripts/tiebreak_harbor_shell_bridge.py` | `python scripts/tiebreak_harbor_shell_bridge.py --check` |
| Multi-World-Secret Stability & Luck-EV Audit (`K=5`, `1800` Ep) | `docs/reports/tiebreak_multiseed_stability.md` | `results/tiebreak/multiseed_stability/multiseed_stability_summary.json` | `scripts/tiebreak_multiseed_stability_audit.py` | `python scripts/tiebreak_multiseed_stability_audit.py --check` |
| Sample-Complexity Learning Curve (`K=3` Folds, `N>=9`) | `docs/reports/tiebreak_learning_curve.md` | `results/tiebreak/learning_curve/learning_curve_summary.json` | `scripts/tiebreak_learning_curve.py` | `python scripts/tiebreak_learning_curve.py --check` |
| Public-Channel VoI & Masking Ablation (`2,160` Ep, `95.1%` Canary Share) | `docs/reports/tiebreak_channel_ablation.md` | `results/tiebreak/channel_ablation/channel_ablation_summary.json` | `scripts/tiebreak_channel_ablation_audit.py` | `python scripts/tiebreak_channel_ablation_audit.py --check` |
| Canary Split Design & Ternary Partition Audit (`720` Ep, `+0.129` Ternary Gain) | `docs/reports/tiebreak_canary_split_design.md` | `results/tiebreak/canary_split_design/canary_split_design_summary.json` | `scripts/tiebreak_canary_split_design_audit.py` | `python scripts/tiebreak_canary_split_design_audit.py --check` |
| Zero-Shot Cross-Tier Transfer & OOD Horizon Audit (`1,140` Ep, `122.1%` Retention) | `docs/reports/tiebreak_cross_tier_transfer.md` | `results/tiebreak/cross_tier_transfer/cross_tier_transfer_summary.json` | `scripts/tiebreak_cross_tier_transfer_audit.py` | `python scripts/tiebreak_cross_tier_transfer_audit.py --check` |
| Observation-Dropout & Byzantine Noise Stress Audit (`1,800` Ep, `16/16` Positive CIs) | `docs/reports/tiebreak_byzantine_stress.md` | `results/tiebreak/byzantine_stress/byzantine_stress_summary.json` | `scripts/tiebreak_byzantine_stress_audit.py` | `python scripts/tiebreak_byzantine_stress_audit.py --check` |
| Standalone Offline HTML Dashboard & Manifest | `results/tiebreak/viewer/tiebreak_dashboard.html` | `results/tiebreak/viewer/viewer_manifest.json` | `scripts/build_tiebreak_viewer.py` | `python scripts/build_tiebreak_viewer.py --check` |
| Unified Keyless Compact Policy Evaluation CLI | `docs/reports/TIEBREAK_INDEX.md` | `results/tiebreak/empirical_bayes/summary.json` | `scripts/run_tiebreak_policy.py` | `python scripts/run_tiebreak_policy.py --check` |
| Compact Linear 4-Stage DAgger Ablation | `results/tiebreak/dagger_ablation/table.md` | `results/tiebreak/dagger_ablation/summary.json` | `train/compact_dagger_ablation.py` | `python -m pytest -q tests/test_compact_dagger_ablation.py` |
| Empirical-Bayes Component Ablation (`n=180`) | `results/tiebreak/empirical_bayes/table.md` | `results/tiebreak/empirical_bayes/summary.json` | `train/empirical_bayes_policy.py` | `python -m pytest -q tests/test_compact_tiebreak.py` |
| Compact Qwen2.5-0.5B/1.5B SFT+DPO+DAgger | `docs/reports/tiebreak_small_model.md` | `results/tiebreak/qwen05b_compact_dagger/export_manifest.json` | `train/compact_lora_sft.py` | `python -m pytest -q tests/test_compact_lora_sft.py` |

## 5. Quick Reproduction Commands

```bash
python scripts/reproduce_tiebreak_all.py --check
python scripts/reproduce_tiebreak_all.py --full
python scripts/reproduce_tiebreak_all.py --json
python scripts/verify_tiebreak_submission.py --strict
python scripts/run_tiebreak_policy.py --check
python -m pytest -q tests/test_reproduce_tiebreak_all.py
```
