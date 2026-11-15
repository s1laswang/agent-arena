# Tiebreak Robustness Audit: Mole Access-Log Framing and Angry-Decoy Message Traps

**Schema**: `canary.tiebreak.framing_decoy.v1` | **Tiers**: `v1.4` (`easy`, `medium`, `hard`) | **World-Paired Held-Out Seeds**: `800000..800029` (`n=90`/policy, `450` fresh `Env` replays verified) | **World Secret**: `sha256:ebf2f09716cf76d3`

## 1. Governance & Provenance Disclosures (Panel Fix A & Panel Fix E)

- **Panel Fix A (Strict Seed Isolation)**: All 450 episodes in this framing and decoy robustness audit (1 AST-isolated FramingGullibleHeuristicPolicy + 4 trained compact policies x n=90 world-paired episodes) strictly evaluate HELDOUT_SEEDS 800000..800029 (within [800000, 800200)) across easy, medium, and hard under canonical CANARY_WORLD_SECRET (sha256:ebf2f09716cf76d3). All learned policy parameters and EmpiricalBayesPolicy likelihood ratios originate strictly from disjoint TRAIN_SEEDS [100000, 200000) with 0 JUDGE_SEEDS (900k+) touched. Where DEV_SEEDS 0..29 appear in separate Canary frontier reports, they are post-hoc locked, not pre-registered (Panel Fix A).
- **Panel Fix E (Strict Track Separation)**: Per Panel Fix E strict track separation, 0 / 19 historical open-weight Qwen2.5 runs in experiment_ledger.json exceed untrained base (> 0.000), so the README.md Qwen addendum remains withheld (HOLD_README_QWEN_ADDENDUM_UNTIL_V100). FramingGullibleHeuristicPolicy and all 4 compact policies audited here (EmpiricalBayesPolicy, CompactLinearDAggerPolicy, ScalingLogisticPolicy, TinyMLPPolicy; is_open_weight_llm = False) are non-LLM policies strictly separated from Track 1 open-weight Qwen2.5 LoRA and Verda GRPO runs.

## 2. World-Paired Held-Out Results (`n=90` Overall across `easy,medium,hard`)

| Policy | Params | Net Score (`95% CI`) | Paired Delta vs Gullible (`95% CI`) | Paired Delta vs `do_nothing` (`95% CI`) | Wrong Rate | Trap False-Accuse | Canaries / Ep | Abstain Rate |
|---|---:|---|---|---|---:|---:|---:|---:|
| `FramingGullibleHeuristicPolicy` | `0` | `-0.8222` (`[-0.9330, -0.7114]`) | `+0.0000` (`[+0.0000, +0.0000]`) | `-0.8222` (`[-0.9330, -0.7114]`) | `0.9000` | `0.9000` | `0.00` | `0.0000` |
| `EmpiricalBayesPolicy` | `11` | `+0.6223` (`[+0.5726, +0.6721]`) | `+1.4446` (`[+1.3357, +1.5534]`) | `+0.6223` (`[+0.5726, +0.6721]`) | `0.0000` | `0.0000` | `9.67` | `0.0889` |
| `CompactLinearDAggerPolicy` | `785` | `+0.6632` (`[+0.6071, +0.7194]`) | `+1.4854` (`[+1.3708, +1.6001]`) | `+0.6632` (`[+0.6071, +0.7194]`) | `0.0111` | `0.0111` | `9.42` | `0.0222` |
| `ScalingLogisticPolicy` | `82` | `+0.6107` (`[+0.5420, +0.6794]`) | `+1.4329` (`[+1.3154, +1.5504]`) | `+0.6107` (`[+0.5420, +0.6794]`) | `0.0222` | `0.0111` | `10.21` | `0.0556` |
| `TinyMLPPolicy` | `12293` | `+0.6292` (`[+0.5649, +0.6935]`) | `+1.4514` (`[+1.3332, +1.5697]`) | `+0.6292` (`[+0.5649, +0.6935]`) | `0.0222` | `0.0000` | `9.32` | `0.0333` |

## 3. Trap-Active `medium` + `hard` Breakdown (`n=60` Paired Episodes)

Across `medium` and `hard` (`n=60`), angry decoy messages appear in `60/60` (`1.000`) held-out worlds alongside mole after-hours access-log framing.

| Policy | `medium+hard` Net Score | `medium+hard` Wrong Rate | Decoy False-Accuse | Framed-Log False-Accuse | Combined Trap False-Accuse | `medium` Score | `hard` Score |
|---|---:|---:|---:|---:|---:|---:|---:|
| `FramingGullibleHeuristicPolicy` | `-1.0000` | `1.0000` | `1.0000` | `0.9000` | `1.0000` | `-1.0000` | `-1.0000` |
| `EmpiricalBayesPolicy` | `+0.5692` | `0.0000` | `0.0000` | `0.0000` | `0.0000` | `+0.5697` | `+0.5687` |
| `CompactLinearDAggerPolicy` | `+0.5847` | `0.0167` | `0.0000` | `0.0167` | `0.0167` | `+0.6790` | `+0.4903` |
| `ScalingLogisticPolicy` | `+0.5097` | `0.0333` | `0.0167` | `0.0167` | `0.0167` | `+0.5573` | `+0.4620` |
| `TinyMLPPolicy` | `+0.5385` | `0.0333` | `0.0000` | `0.0000` | `0.0000` | `+0.5840` | `+0.4930` |

## 4. Mechanism Analysis: Learned Likelihood Calibration vs Human-Bias Traps

1. **Uncalibrated Framing & Decoy Collapse**: `FramingGullibleHeuristicPolicy` weights angry message hits and raw/after-hours access-log frequency without canary verification or `1/(1+V)` EV stopping, collapsing to `-0.8222` overall (`wrong_accuse_rate = 0.9000`, `trap_false_accuse_rate = 0.9000`, `medium+hard` decoy false-accuse `1.0000`).
2. **Learned Log-Likelihood Downweighting (`EmpiricalBayesPolicy`, `11`p)**: Trained strictly on `TRAIN_SEEDS 102000..102779`, `EmpiricalBayesPolicy` learns `w_canary_hit = +1.3162` and `w_canary_miss = -3.7833` (canary split contrast `5.0995` nats), while downweighting spoofable `w_after_hours = +0.1225` (`41.63x` smaller than a single canary variant contrast) and assigning negative log-likelihood `w_angry_msg = -2.3622` (`negative_exonerating`) to angry chat bursts.
3. **Elimination of Framing/Decoy False Accusations**: Guided by high-KL canary splits (`9.67` traps/episode) and calibrated `1/(1+V)` EV stopping, `EmpiricalBayesPolicy` reaches `+0.6223` (`wrong_accuse_rate = 0.0000 <= 0.0200`, `trap_false_accuse_rate = 0.0000`), and all `4/4` trained compact policies achieve strictly positive paired `95%` CIs over both `FramingGullibleHeuristicPolicy` and `do_nothing`.

### Verification Commands

```bash
python scripts/tiebreak_framing_decoy_audit.py --check
python -m pytest -q tests/test_tiebreak_framing_decoy.py
python scripts/reproduce_tiebreak_all.py --check
python scripts/verify_tiebreak_submission.py --strict
```
