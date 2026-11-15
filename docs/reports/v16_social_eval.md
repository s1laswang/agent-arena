# V1.6 Social Variants Partial Gemini Evaluation (Hard Seeds 30..44)

## Headline Verdict: Gate NOT Met

Live V1.6 `gemini-4-carbon` evaluation on hard seeds `30..44` (`TIERS_VERSION=v1.4`, in-process harness) was halted early per Chief order to protect shared Gemini API quota for the main G1 `n=60` gap extension run. No further live Gemini calls were launched after draining active seeds.

Across the replay-verified checkpoints collected before the halt (`10` valid episodes total: `v0_v14_control` `n=4`, `v5_full9_cocktail` `n=3`, `v3_grudge_falsemem_misforward` `n=2`, `v1_anchoring_authority_confirmation` `n=1`, `v2_recency_bandwagon_sycophancy` `n=0`, `v4_triad_authority_recency_grudge` `n=0`):

- **With `n=3` paired seeds (`30, 31, 32`), `v5_full9_cocktail` scores HIGHER for `gemini-4-carbon` (`0.617` raw mean) than `v0_v14_control` (`0.523` raw mean, `117.8%` of v1.4 control, paired raw delta `+0.093`).**
- **`v3_grudge_falsemem_misforward` (`0.645` vs `0.545`, `118.3%` of v1.4 control, `n=2` paired seeds `30, 31`) and `v1_anchoring_authority_confirmation` (`0.650` vs `0.540`, `120.4%` of v1.4 control, `n=1` paired seed `30`) also score HIGHER for `gemini-4-carbon` than v1.4 control on the same seeds.**
- **Both the sample-size gate (`n >= 15` / `n >= 30`) and the V1.6 gap-widening gate (lowering Gemini score and Gemini/Solver ratio relative to v1.4 control) are NOT met.**

---

## Per-Variant Summary (Paired Against `v0_v14_control` and `SolverPolicy`)

All fairness and replay invariants pass on every collected checkpoint (`DoNothing = 0.0`, `StopEarlyQuit = 0.0`, `Solver(v1.6) - Solver(v1.4) = 0.0` exact calibration, `10/10` episodes replay-verified). Note that on seeds `30` and `32`, deterministic `SolverPolicy` makes a wrong accusation (`-1.000` raw score despite positive posterior expected value `+0.175` and `+0.535`), making `solver_mean <= 0` on subsets `{30}`, `{30,31}`, `{30,31,32}`, and `{30,31,32,33}`; per `scripts/v16_eval_matrix.py` and `scripts/v16_compare_30_44.py`, raw `gemini / solver` ratio is `n/a` when `solver_mean <= 0`, while luck-adjusted `gemini / solver` ratio is well-defined (`solver_luck_adj_mean > 0` on all subsets) and reported alongside paired `ratio_vs_v0_control`.

| Variant | n valid | Valid seeds | Gemini raw mean | Gemini luck-adj | Solver raw mean | Solver luck-adj | v0 control raw (paired) | v0 control luck-adj (paired) | Ratio vs v0 control (raw) | Ratio vs Solver (raw) | Ratio vs Solver (luck-adj) | Replay verified | Gate met |
|---|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| `v0_v14_control` (all valid) | 4 | 30,31,32,33 | 0.498 | 0.285 | -0.238 | 0.435 | 0.498 | 0.285 | 1.000 (100.0%) | n/a (solver<=0) | 0.656 (65.6%) | 4/4 | NO (control, n=4) |
| `v0_v14_control` (seeds 30..32) | 3 | 30,31,32 | 0.523 | 0.493 | -0.493 | 0.410 | 0.523 | 0.493 | 1.000 (100.0%) | n/a (solver<=0) | 1.202 (120.2%) | 3/3 | NO (control, n=3) |
| `v1_anchoring_authority_confirmation` | 1 | 30 | 0.650 | 0.594 | -1.000 | 0.175 | 0.540 | 0.517 | 1.204 (120.4%) | n/a (solver<=0) | 3.385 (338.5%) | 1/1 | **NO** |
| `v2_recency_bandwagon_sycophancy` | 0 | none | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a | 0/0 | **NO** |
| `v3_grudge_falsemem_misforward` | 2 | 30,31 | 0.645 | 0.604 | -0.240 | 0.348 | 0.545 | 0.524 | 1.183 (118.3%) | n/a (solver<=0) | 1.737 (173.7%) | 2/2 | **NO** |
| `v4_triad_authority_recency_grudge` | 0 | none | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a | 0/0 | **NO** |
| `v5_full9_cocktail` | 3 | 30,31,32 | 0.617 | 0.452 | -0.493 | 0.410 | 0.523 | 0.493 | 1.178 (117.8%) | n/a (solver<=0) | 1.101 (110.1%) | 3/3 | **NO** |

---

## Per-Variant and Per-Seed Results (`hard`, `gemini:gemini-4-carbon` inproc)

| Variant | n valid | Seed | Gemini score | Gemini luck-adj | Gemini day | Gemini P(acc) | Solver score | Solver luck-adj | Solver day | v0 control score | Ratio vs v0 control (raw) | Ratio vs Solver (raw) | Ratio vs Solver (luck-adj) | Replay verified |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| `v0_v14_control` | 4 | 30 | +0.540 | +0.517 | 11 | 0.985 | -1.000 | +0.175 | 18 | +0.540 | 1.000 (100.0%) | n/a (solver<=0) | 2.946 (294.6%) | True |
| `v0_v14_control` | 4 | 31 | +0.550 | +0.531 | 10 | 0.988 | +0.520 | +0.520 | 9 | +0.550 | 1.000 (100.0%) | 1.058 (105.8%) | 1.022 (102.2%) | True |
| `v0_v14_control` | 4 | 32 | +0.480 | +0.430 | 13 | 0.966 | -1.000 | +0.535 | 9 | +0.480 | 1.000 (100.0%) | n/a (solver<=0) | 0.804 (80.4%) | True |
| `v0_v14_control` | 4 | 33 | +0.420 | -0.337 | 20 | 0.467 | +0.530 | +0.509 | 10 | +0.420 | 1.000 (100.0%) | 0.792 (79.2%) | -0.662 (-66.2%) | True |
| `v1_anchoring_authority_confirmation` | 1 | 30 | +0.650 | +0.594 | 9 | 0.966 | -1.000 | +0.175 | 18 | +0.540 | 1.204 (120.4%) | n/a (solver<=0) | 3.385 (338.5%) | True |
| `v3_grudge_falsemem_misforward` | 2 | 30 | +0.650 | +0.650 | 8 | 1.000 | -1.000 | +0.175 | 18 | +0.540 | 1.204 (120.4%) | n/a (solver<=0) | 3.705 (370.5%) | True |
| `v3_grudge_falsemem_misforward` | 2 | 31 | +0.640 | +0.558 | 8 | 0.950 | +0.520 | +0.520 | 9 | +0.550 | 1.164 (116.4%) | 1.231 (123.1%) | 1.073 (107.3%) | True |
| `v5_full9_cocktail` | 3 | 30 | +0.500 | +0.418 | 11 | 0.945 | -1.000 | +0.175 | 18 | +0.540 | 0.926 (92.6%) | n/a (solver<=0) | 2.379 (237.9%) | True |
| `v5_full9_cocktail` | 3 | 31 | +0.640 | +0.576 | 8 | 0.961 | +0.520 | +0.520 | 9 | +0.550 | 1.164 (116.4%) | 1.231 (123.1%) | 1.108 (110.8%) | True |
| `v5_full9_cocktail` | 3 | 32 | +0.710 | +0.361 | 10 | 0.796 | -1.000 | +0.535 | 9 | +0.480 | 1.479 (147.9%) | n/a (solver<=0) | 0.676 (67.6%) | True |

---

## Observations From Replay-Verified Checkpoints

1. **Structured forensic tools dominated social-chatter decoys on seeds `30..32`:** Across all `10` valid episodes, `gemini-4-carbon` planted canary documents, audited access logs and leak feeds, and achieved `10/10` (`100%`) accusation accuracy. Rather than misleading `gemini-4-carbon` into accusing the social focal suspect, the V1.6 social variants coincided with slightly earlier accusations (days `8..11` on `v1`/`v3`/`v5` vs days `10..13` on `v0_v14_control` for seeds `30..32`), preserving higher remaining value `V` and raising raw Gemini score (`0.617` vs `0.523` on `v5` `n=3`).
2. **Posterior confidence nuance on `v5_full9_cocktail` seed `32`:** On seed `32`, `v5_full9_cocktail` accused on day `10` at lower Bayesian posterior (`P(accused) = 0.796`, raw `+0.710`, luck-adjusted `+0.361`) than `v0_v14_control` on day `13` (`P(accused) = 0.966`, raw `+0.480`, luck-adjusted `+0.430`). Consequently, on `n=3` paired seeds `30..32`, `v5_full9_cocktail` is slightly lower than `v0_v14_control` in luck-adjusted mean (`0.452` vs `0.493`, delta `-0.041`), but higher in raw score (`0.617` vs `0.523`, delta `+0.093`), and well short of statistical significance or the `n >= 15` gate.
3. **Seed `33` on `v0_v14_control`:** On seed `33` (completed just before stopping Slot 1), `v0_v14_control` accused at the horizon (`day 20`) with `P(accused) = 0.467` (raw `+0.420`, luck-adjusted `-0.337`) vs `SolverPolicy` on day `10` (`+0.530`, luck-adjusted `+0.509`). No paired V1.6 variant had completed seed `33` at cutoff.

---

## Offline Reproduction (0 API Calls)

Committed partial checkpoints and summary artifacts:
- Checkpoints: `results/v16_social/partial/<variant>/hard/episodes.jsonl` (`v0_v14_control`, `v1_anchoring_authority_confirmation`, `v3_grudge_falsemem_misforward`, `v5_full9_cocktail`)
- Machine-readable summary: `results/v16_social/partial_summary.json`

Re-run full offline replay verification, baseline zero-checks, solver calibration, and paired bootstrap comparison with zero API calls:

```bash
GOOGLE_API_KEY="" GEMINI_API_KEY="" PYTHONPATH=. python scripts/v16_compare_30_44.py \
  --runs-root results/v16_social/partial \
  --reference-json results/v16_social/reference_seeds_30_49.json
```
