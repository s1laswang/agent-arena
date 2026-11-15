# Inference-Time Observation-Dropout & Byzantine Perturbation Stress Audit (`v1.4`)

Deterministic keyless stress audit wrapping ONLY the public observation stream seen by all `4` verified Canary compact policies (`EmpiricalBayesPolicy` `11`p, `ScalingLogisticPolicy` `82`p, `CompactLinearDAggerPolicy` `785`p, `TinyMLPPolicy` `12,293`p) vs the uncalibrated `Heuristic` baseline across world-paired `HELDOUT_SEEDS 800000..800029` (`n=90` per cell: `30` `easy`, `30` `medium`, `30` `hard`; `world_secret_tag` `sha256:ebf2f09716cf76d3`) and `4` deterministic perturbation levels (`dropout_rate` in `{0.00, 0.15, 0.30, 0.50}`, `1800` episodes, **`1800/1800` (`100.0%`) canonical `Env` replays verified**). While the underlying `Env` remains `100%` canonical, the observation wrapper deterministically redacts secondary interview transcripts (`answer`), chat/email rows (`search_messages`/`read_message`), access-log rows (`read_access_logs`), and leak-feed canary `variant` tags at rate `dropout_rate`, and injects Byzantine peer/evasiveness flips on surviving interview/chat/log telemetry at conditional rate `0.5 * dropout_rate`.

- **Seed & Secret Provenance (Panel Fix A)**: All `1800` episodes strictly evaluate `HELDOUT_SEEDS 800000..800029` under `sha256:ebf2f09716cf76d3`, while all compact policy weights and `EmpiricalBayesPolicy` posterior likelihoods originate strictly from disjoint `TRAIN_SEEDS [100000, 200000)` with **`0` `JUDGE_SEEDS` (`900k+`) touched**. Where `DEV_SEEDS 0..29` appear in separate Canary frontier reports, they are **post-hoc locked, not pre-registered**.
- **Strict Track Separation (Panel Fix E)**: `0 / 19` historical open-weight `Qwen2.5` runs in `experiment_ledger.json` exceed untrained `base` (`0.000`), so the `README.md` Qwen addendum remains withheld (`HOLD_README_QWEN_ADDENDUM_UNTIL_V100`). All `4` compact policies audited here (`is_open_weight_llm = False`) are non-LLM structured/neural policies strictly separated from open-weight `Qwen2.5` LoRA and Verda GRPO runs.

## 1. Graceful-Degradation Headline (`dropout_rate = 0.00` Clean vs `0.50` Heavy Byzantine Stress)

| Policy (`run_id`) | Params | `1/(1+V)` EV Stop | Clean `0.00` Score / Public EV | Stress `0.50` Score / Public EV | Abstain Shift (`0.00 -> 0.50`) | Wrong-Accuse Shift (`0.00 -> 0.50`) | Sub-Breakeven Accuse (`0.50`) | Positive `95% CI` Levels (vs `0.000` / vs `Heuristic`) |
|---|---:|---|---:|---:|---:|---:|---:|---:|
| `EmpiricalBayesPolicy` (`empirical-bayes-v14`) | `11` | Yes | `+0.6223` / `+0.6039` | `+0.4176` / `+0.4063` | `0.089 -> 0.167` (`+0.078`) | `0.000 -> 0.056` (`+0.056`) | `0.067` (`6/90`) | **`4/4` & `4/4`** |
| `ScalingLogisticPolicy` (`scaling-logistic-v14`) | `82` | Yes | `+0.6107` / `+0.6120` | `+0.4180` / `+0.4065` | `0.056 -> 0.300` (`+0.244`) | `0.022 -> 0.000` (`-0.022`) | `0.000` (`0/90`) | **`4/4` & `4/4`** |
| `CompactLinearDAggerPolicy` (`compact-linear-dagger-v14`) | `785` | Yes | `+0.6632` / `+0.6242` | `+0.4717` / `+0.4766` | `0.022 -> 0.133` (`+0.111`) | `0.011 -> 0.044` (`+0.033`) | `0.056` (`5/90`) | **`4/4` & `4/4`** |
| `TinyMLPPolicy` (`tiny-mlp-dagger-v14`) | `12,293` | Yes | `+0.6292` / `+0.6078` | `+0.4896` / `+0.4788` | `0.033 -> 0.156` (`+0.122`) | `0.022 -> 0.000` (`-0.022`) | `0.022` (`2/90`) | **`4/4` & `4/4`** |
| `Heuristic` (`baseline-uncalibrated-heuristic-v14`) | `0` | No (forced deadline) | `+0.1958` / `+0.2500` | `-0.2012` / `-0.2127` | `0.000 -> 0.000` (`+0.000`) | `0.244 -> 0.478` (`+0.233`) | `0.567` (`51/90`) | `0/4` (baseline) |

When `50%` of secondary telemetry is dropped and surviving interview/chat/log observations carry Byzantine peer/evasiveness flips (`dropout_rate = 0.50`), the uncalibrated `Heuristic` commits unconditionally (`abstain_rate` `0.000 -> 0.000`) and plunges from `+0.1958` into a **`-0.2012`** wrong-accusation cliff (`wrong_accuse_rate` `0.244 -> 0.478`). By contrast, all `4` compact policies calibrated around `1/(1+V)` EV stopping smoothly convert degraded-evidence worlds into `0.000` abstentions (`abstain_shift` spanning `+0.078..+0.244`), capping `wrong_accuse_rate` at `0.056` and maintaining **`16/16` (`100.0%`)** strictly positive `95%` CIs vs `0.000` abstain and **`16/16` (`100.0%`)** strictly positive world-paired `95%` CIs over `Heuristic`.

## 2. Full `20`-Cell Perturbation Curve (`n=90` Paired Held-Out Worlds per Cell)

| Policy | `dropout_rate` | Raw Score (`95% CI`) | Calibrated Public EV (`95% CI`) | Paired Delta vs `Heuristic` (`95% CI`) | Paired Delta vs Clean `0.00` (`95% CI`) | Acc / Wrong / Abstain | Sub-BE Accuse | Masked / Byz Flips | Replay |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `EmpiricalBayesPolicy` | `0.00` | `+0.6223 [+0.5726, +0.6721]` | `+0.6039 [+0.5555, +0.6523]` | `+0.4266 [+0.2804, +0.5727]` | `+0.0000 [+0.0000, +0.0000]` | `0.911` / `0.000` / `0.089` | `0.000` | `0.0` / `0.0` | `90/90` |
| `EmpiricalBayesPolicy` | `0.15` | `+0.6227 [+0.5706, +0.6748]` | `+0.6109 [+0.5692, +0.6525]` | `+0.4877 [+0.3458, +0.6295]` | `+0.0003 [-0.0545, +0.0551]` | `0.956` / `0.011` / `0.033` | `0.011` | `33.2` / `12.9` | `90/90` |
| `EmpiricalBayesPolicy` | `0.30` | `+0.5612 [+0.5083, +0.6141]` | `+0.5360 [+0.4808, +0.5912]` | `+0.5471 [+0.3955, +0.6987]` | `-0.0611 [-0.1196, -0.0026]` | `0.900` / `0.000` / `0.100` | `0.011` | `70.9` / `22.9` | `90/90` |
| `EmpiricalBayesPolicy` | `0.50` | `+0.4176 [+0.3261, +0.5090]` | `+0.4063 [+0.3195, +0.4932]` | `+0.6188 [+0.4468, +0.7907]` | `-0.2048 [-0.2948, -0.1147]` | `0.778` / `0.056` / `0.167` | `0.067` | `141.6` / `33.2` | `90/90` |
| `ScalingLogisticPolicy` | `0.00` | `+0.6107 [+0.5420, +0.6794]` | `+0.6120 [+0.5664, +0.6575]` | `+0.4149 [+0.2724, +0.5574]` | `+0.0000 [+0.0000, +0.0000]` | `0.922` / `0.022` / `0.056` | `0.000` | `0.0` / `0.0` | `90/90` |
| `ScalingLogisticPolicy` | `0.15` | `+0.5416 [+0.4612, +0.6219]` | `+0.5578 [+0.5039, +0.6117]` | `+0.4066 [+0.2571, +0.5561]` | `-0.0691 [-0.1495, +0.0113]` | `0.889` / `0.033` / `0.078` | `0.011` | `34.9` / `14.6` | `90/90` |
| `ScalingLogisticPolicy` | `0.30` | `+0.4748 [+0.3880, +0.5615]` | `+0.5088 [+0.4508, +0.5668]` | `+0.4607 [+0.3081, +0.6132]` | `-0.1359 [-0.2163, -0.0555]` | `0.822` / `0.044` / `0.133` | `0.022` | `69.8` / `24.2` | `90/90` |
| `ScalingLogisticPolicy` | `0.50` | `+0.4180 [+0.3512, +0.4848]` | `+0.4065 [+0.3419, +0.4711]` | `+0.6192 [+0.4706, +0.7678]` | `-0.1927 [-0.2615, -0.1238]` | `0.700` / `0.000` / `0.300` | `0.000` | `149.4` / `36.0` | `90/90` |
| `CompactLinearDAggerPolicy` | `0.00` | `+0.6632 [+0.6071, +0.7194]` | `+0.6242 [+0.5675, +0.6809]` | `+0.4674 [+0.3247, +0.6102]` | `+0.0000 [+0.0000, +0.0000]` | `0.967` / `0.011` / `0.022` | `0.044` | `0.0` / `0.0` | `90/90` |
| `CompactLinearDAggerPolicy` | `0.15` | `+0.6351 [+0.5704, +0.6998]` | `+0.6096 [+0.5498, +0.6693]` | `+0.5001 [+0.3524, +0.6478]` | `-0.0281 [-0.0916, +0.0353]` | `0.944` / `0.022` / `0.033` | `0.044` | `25.3` / `10.5` | `90/90` |
| `CompactLinearDAggerPolicy` | `0.30` | `+0.5444 [+0.4720, +0.6169]` | `+0.5193 [+0.4502, +0.5885]` | `+0.5303 [+0.3764, +0.6843]` | `-0.1188 [-0.1956, -0.0420]` | `0.889` / `0.022` / `0.089` | `0.044` | `63.5` / `21.6` | `90/90` |
| `CompactLinearDAggerPolicy` | `0.50` | `+0.4717 [+0.3838, +0.5596]` | `+0.4766 [+0.4014, +0.5518]` | `+0.6729 [+0.5134, +0.8324]` | `-0.1916 [-0.2797, -0.1034]` | `0.822` / `0.044` / `0.133` | `0.056` | `115.3` / `28.8` | `90/90` |
| `TinyMLPPolicy` | `0.00` | `+0.6292 [+0.5649, +0.6935]` | `+0.6078 [+0.5596, +0.6560]` | `+0.4334 [+0.2885, +0.5784]` | `+0.0000 [+0.0000, +0.0000]` | `0.944` / `0.022` / `0.033` | `0.033` | `0.0` / `0.0` | `90/90` |
| `TinyMLPPolicy` | `0.15` | `+0.6028 [+0.5339, +0.6717]` | `+0.5631 [+0.4989, +0.6272]` | `+0.4678 [+0.3246, +0.6110]` | `-0.0264 [-0.0903, +0.0374]` | `0.911` / `0.022` / `0.067` | `0.056` | `30.8` / `12.0` | `90/90` |
| `TinyMLPPolicy` | `0.30` | `+0.5096 [+0.4222, +0.5969]` | `+0.5253 [+0.4584, +0.5923]` | `+0.4954 [+0.3385, +0.6524]` | `-0.1197 [-0.2268, -0.0126]` | `0.822` / `0.044` / `0.133` | `0.033` | `66.2` / `22.3` | `90/90` |
| `TinyMLPPolicy` | `0.50` | `+0.4896 [+0.4314, +0.5478]` | `+0.4788 [+0.4217, +0.5360]` | `+0.6908 [+0.5432, +0.8383]` | `-0.1397 [-0.2084, -0.0709]` | `0.844` / `0.000` / `0.156` | `0.022` | `136.5` / `31.4` | `90/90` |
| `Heuristic` | `0.00` | `+0.1958 [+0.0507, +0.3409]` | `+0.2500 [+0.1468, +0.3533]` | `+0.0000 [+0.0000, +0.0000]` | `+0.0000 [+0.0000, +0.0000]` | `0.756` / `0.244` / `0.000` | `0.311` | `0.0` / `0.0` | `90/90` |
| `Heuristic` | `0.15` | `+0.1350 [-0.0114, +0.2814]` | `+0.1608 [+0.0454, +0.2762]` | `+0.0000 [+0.0000, +0.0000]` | `-0.0608 [-0.1402, +0.0186]` | `0.733` / `0.267` / `0.000` | `0.356` | `1.8` / `0.0` | `90/90` |
| `Heuristic` | `0.30` | `+0.0141 [-0.1387, +0.1670]` | `-0.0277 [-0.1603, +0.1050]` | `+0.0000 [+0.0000, +0.0000]` | `-0.1817 [-0.3090, -0.0543]` | `0.667` / `0.333` / `0.000` | `0.489` | `5.1` / `0.0` | `90/90` |
| `Heuristic` | `0.50` | `-0.2012 [-0.3625, -0.0400]` | `-0.2127 [-0.3577, -0.0676]` | `+0.0000 [+0.0000, +0.0000]` | `-0.3970 [-0.5422, -0.2518]` | `0.522` / `0.478` / `0.000` | `0.567` | `8.8` / `0.0` | `90/90` |

## 3. Tier-Stratified Degradation Under Clean (`0.00`) vs Heavy Stress (`0.50`, `n=30` / Tier)

| Policy | `easy` `0.00 -> 0.50` Score (Wrong / Abstain `0.50`) | `medium` `0.00 -> 0.50` Score (Wrong / Abstain `0.50`) | `hard` `0.00 -> 0.50` Score (Wrong / Abstain `0.50`) | Clean `0.00` Exact Parity (`n=90`) |
|---|---|---|---|---:|
| `EmpiricalBayesPolicy` | `+0.7287 -> +0.6610` (`w=0.000`, `a=0.033`) | `+0.5697 -> +0.3890` (`w=0.033`, `a=0.300`) | `+0.5687 -> +0.2027` (`w=0.133`, `a=0.167`) | `90/90` |
| `ScalingLogisticPolicy` | `+0.8127 -> +0.6810` (`w=0.000`, `a=0.000`) | `+0.5573 -> +0.3163` (`w=0.000`, `a=0.533`) | `+0.4620 -> +0.2567` (`w=0.000`, `a=0.367`) | `90/90` |
| `CompactLinearDAggerPolicy` | `+0.8203 -> +0.6967` (`w=0.000`, `a=0.033`) | `+0.6790 -> +0.4810` (`w=0.000`, `a=0.300`) | `+0.4903 -> +0.2373` (`w=0.133`, `a=0.067`) | `90/90` |
| `TinyMLPPolicy` | `+0.8107 -> +0.6757` (`w=0.000`, `a=0.033`) | `+0.5840 -> +0.4080` (`w=0.000`, `a=0.367`) | `+0.4930 -> +0.3850` (`w=0.000`, `a=0.067`) | `90/90` |
| `Heuristic` | `+0.7000 -> +0.2397` (`w=0.233`, `a=0.000`) | `+0.0193 -> -0.3077` (`w=0.567`, `a=0.000`) | `-0.1320 -> -0.5357` (`w=0.633`, `a=0.000`) | `90/90` |

## 4. Mechanism Summary: Why Calibrated `1/(1+V)` EV Stopping Prevents Wrong-Accusation Cliffs

1. **Canonical `Env` + Idempotent Stream Perturbation**: Every tool action executes against the unmodified canonical `Env` (`valid_call_rate = 1.0000` across all `4` compact policies, `1800/1800` episodes replay-verified on fresh canonical `Env`), while `ByzantineObservationStream` hashes `(tier, seed, rate_bp, channel, record_id)` so repeated polling of `read_access_logs`, `search_messages`, `interview`, or `check_leak_feed` cannot average away dropped or spoofed fields.
2. **Uncalibrated Forced Commit = `-1.000` Cliff**: Because wrong accusations carry an asymmetric `-1.000` penalty against residual asset value `V in [0, 1]`, committing whenever `p_post < 1 / (1 + V)` has strictly negative expected value. Without calibrated `1/(1+V)` EV stopping, `Heuristic` keeps `abstain_rate = 0.000` as variant/log/chat/interview evidence degrades, driving `sub_breakeven_accuse_rate` to `0.567` at `dropout_rate = 0.50`.
3. **Calibrated `1/(1+V)` Abstention Cushion Across `11` to `12,293` Parameters**: Across `3` orders of magnitude in model capacity (`11`p `EmpiricalBayesPolicy`, `82`p `ScalingLogisticPolicy`, `785`p `CompactLinearDAggerPolicy`, `12,293`p `TinyMLPPolicy`), posterior entropy under missing/Byzantine telemetry keeps expected accusation value below the `1/(1+V)` commit boundary until additional clean canary splits resolve the mole or the horizon expires safely at `0.000`.

### Offline Reproduction & Fast Verification Commands

```bash
python scripts/tiebreak_byzantine_stress_audit.py --check
pytest -q tests/test_tiebreak_byzantine_stress.py
python scripts/reproduce_tiebreak_all.py --check
python scripts/verify_tiebreak_submission.py --strict
```
