# Canary StaffAI Master Dossier: V1.6 Social Bias Layer, Cache Provenance, and Gate B Audit

## 1. Executive Summary and Honest Ship Decision

Squad `staffai` built and audited Canary's opt-in workplace social bias layer (`canary/social/`, `CANARY_PROVIDER=v16:<variant>`) to model realistic organizational cognitive biases (rumours, grudges, authority pressure, sycophancy, confirmation, bandwagon cascades, anchoring, recency, false memories, accidental forwards, and multi-employee Sleeper social-engineering chains) generated with `gemini-4-carbon`, SHA-256 cached for deterministic keyless replay, and disclosed plainly in the rules (`LR = 1`).

Key verified outcomes:
- **Zero protected-file edits and frozen `v1.4` integrity:** `git diff --name-only origin/justSilas...HEAD` touches `0` protected paths (`canary/env.py`, `canary/rules.py`, `canary/solver/`, `canary/reproduce.py`, `harbor/`). `rules.TIERS_VERSION` remains `"v1.4"` with frozen tier hash `a8f99c2537c91d72` (`TIERS_V13` hash `8df71cf570bb48bc`), and default `CANARY_PROVIDER` remains `template`.
- **Exact Bayesian calibration (`LR = 1`):** Because every V1.6 social message is derived strictly from `PublicDayFacts` (regular non-canary documents and public roles, excluding `facts.decoy` and scrubbing `DECOY_VOCAB` / `ANGER_WORDS`), `solver_v14 == solver_v16 == 0.576` on `hard` seeds `0-9` (`n = 10`, `10/10` exact step-by-step trajectory and accused ID match), while `do_nothing == 0.000` and `stop_early == 0.000`.
- **Pre-registered Gate B outcome (`NOT MET`):** On the committed `v1.4` primary baseline (`hard` seeds `0-9`, OpenCode MCP `gemini-4-carbon`, `10/10` replay-verified), `gemini-4-carbon` scores `0.351 +/- 0.312` (`60.9%` raw of solver, `55.7%` luck-adjusted). On relayed Azure in-process `gemini-4-carbon` shared `hard` seeds `30-32` (`n = 3`), `v5_full9_cocktail` (`0.617`) scored higher than `v0_v14_control` (`0.523`, paired ratio `1.178`), and the OpenCode `hard` `0-9` V1.6 shard sweep (`0/10` completed before the Gemini API stand-down) did not drop below `v1.4`. **Gate B is NOT met**, so `v1.4` default ships unchanged and `canary/social/` stays strictly opt-in.
- **Real `gemini-4-carbon` cache hygiene:** `data/gemini_cache/` contains `256` content-addressed `<sha256>.json` files (`712` rewritten social bodies), `100%` stamped with `provenance.label == "REAL"` and `provenance.model == "gemini-4-carbon"`, `0` API keys or secrets, and canary-planting cache invariance (`18/18` active-day cache hits with `0` validator rejects on `hard` seed `0` under `CANARY_OFFLINE=1`).
- **Full 21-day horizon continuity (`v6_horizon_escalation`):** `canary/social/horizon_escalation.py` adds an opt-in five-phase schedule emitting `63` validated social messages across `Days 1..21` (`3` per day, including `9` messages in the `Days 19..21` late stopping window where `v5_full9_cocktail` emits `0`, `58/60` post-Day-1 causal callbacks, and `20`-day max callback span) without altering `v5_full9_cocktail` prompt hashes.

---

## 2. Architecture, Cognitive Biases, and Sleeper Ports (`canary/social/`)

All StaffAI components live behind the `TextProvider` interface (`PublicDayFacts -> day_messages`):

| Component | Path | Core Role and Fairness Guarantee |
|---|---|---|
| Nine-bias generators & validator | [canary/social/biases.py](../../canary/social/biases.py) | Implements `authority`, `recency`, `confirmation`, `bandwagon`, `anchoring`, `grudge`, `misforward`, `false_memory`, and `sycophancy`; enforces `DECOY_VOCAB` / `ANGER_WORDS` scrub and `facts.decoy` exclusion. |
| Deterministic social engine | [canary/social/engine.py](../../canary/social/engine.py) | Initializes `EpisodeSocialState` from `(variant, tier, seed)` and Day 1 regular (`non-c*`) document recipients; isolates private RNG from `env._dyn`. |
| Variant & ablation schedules | [canary/social/variants.py](../../canary/social/variants.py) | Defines `v0_v14_control`, `v1`..`v5_full9_cocktail` (`social-v2`), and nine single-bias ablations `b_<bias>`. |
| `gemini-4-carbon` rewriter & SHA-256 cache | [canary/social/gemini_chatter.py](../../canary/social/gemini_chatter.py), [canary/text/llm_cache.py](../../canary/text/llm_cache.py) | Rewrites template drafts with `gemini-4-carbon`, strips canary doc titles for cache invariance, validates every item, and falls back per message on any lint/schema failure. |
| Sleeper social-engineering chains | [canary/social/sleeper_chains.py](../../canary/social/sleeper_chains.py) | Ports `cosign_urgency_chain`, `accomplice_alibi_ring`, `out_of_band_chat_claim`, and `slowburn_framing_echo` (`v16:sleeper_social_chains`). |
| Multi-day memory & 21-day escalation | [canary/social/multiday_memory.py](../../canary/social/multiday_memory.py), [canary/social/horizon_escalation.py](../../canary/social/horizon_escalation.py) | Timeline extractor/verifier plus opt-in `v6_horizon_escalation` (`63` messages across `Days 1..21`, `9` in `Days 19..21`, `6`-stage dyadic grudges). |
| Keyless office replay viewer | [canary/social/office_replay.py](../../canary/social/office_replay.py) | Offline episode extractor and standalone HTML viewer highlighting social distraction vs Bayesian posterior shifts. |

Design, rules disclosure, and Sleeper port specifications:
- Architecture & cognitive bias taxonomy: [docs/v16-social-design.md](../v16-social-design.md)
- Rules disclosure & candidate README templates: [docs/v16-readme-and-rules.md](../v16-readme-and-rules.md)
- Sleeper social-engineering port notes: [docs/SLEEPER-SOCIAL-PORT.md](../SLEEPER-SOCIAL-PORT.md)
- Paired Gate B honest report: [docs/reports/v16_social_gate.md](v16_social_gate.md)
- Day 1..21 horizon escalation report: [docs/reports/v16_horizon_escalation.md](v16_horizon_escalation.md)

---

## 3. Paired Evaluation Summary and Gate B Verification

### 3A. Primary OpenCode MCP Evaluation (`hard` Seeds `0-9`, Timeout `3600s`)

Source artifact: [results/v16_social/paired_v14_vs_v16_0_9.json](../../results/v16_social/paired_v14_vs_v16_0_9.json) and [results/v16_social/paired_v14_vs_v16_0_9.md](../../results/v16_social/paired_v14_vs_v16_0_9.md).

| Arm | Provider | Valid Episodes | Raw Score +/- 95% CI | Raw % of Solver [95% CI] | Luck-Adjusted Mean | Luck-Adjusted % of Solver [95% CI] | Accuracy | Mean Accuse Day |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| Reference `solver` | `template` == `social-v2` | `10/10` | `0.576 +/- 0.108` | `100.0%` | `0.556` | `100.0%` | `1.00` | `9.9` |
| `v1.4` primary (committed) | `template` | `10/10` | `0.351 +/- 0.312` | `60.9% [3.4%, 103.8%]` | `0.310` | `55.7% [21.4%, 80.3%]` | `0.90` | `14.5` |
| `v1.6` candidate | `social-v2` (`v5_full9_cocktail`) | `0/10` | `n/a` | `n/a` | `n/a` | `n/a` | `n/a` | `n/a` |
| `do_nothing` baseline | `template` & `social-v2` | `10/10` | `0.000` | `0.0%` | `0.000` | `0.0%` | `0.00` | `n/a` |
| `stop_early` baseline | `template` & `social-v2` | `10/10` | `0.000` | `0.0%` | `0.000` | `0.0%` | `0.00` | `n/a` |

### 3B. Relayed Azure In-Process Checkpoints (`hard` Seeds `30-32`) and Reference `30-49`

Source artifacts: [results/v16_social/paired_v14_vs_v16_0_9.json](../../results/v16_social/paired_v14_vs_v16_0_9.json) and [results/v16_social/reference_seeds_30_49.json](../../results/v16_social/reference_seeds_30_49.json).

- Reference solver on `hard` seeds `30-49` (`n = 20`): raw mean `0.431`, luck-adjusted mean `0.524`, `do_nothing == 0.000`, `stop_early == 0.000`. On the 3-seed subset `[30, 31, 32]`, solver raw mean is `-0.493` (two wrong high-posterior accusations on seeds `30` and `32`) and solver luck-adjusted mean is `0.410`.
- Paired in-process `gemini-4-carbon` checkpoints on shared seeds:
  - `v0_v14_control` (`[30, 31, 32]`, `n = 3`): Gemini mean `0.523` (`0.540`, `0.550`, `0.480`).
  - `v5_full9_cocktail` (`[30, 31, 32]`, `n = 3`): Gemini mean `0.617` (`0.500`, `0.640`, `0.710`), `+0.093` above `v0_v14_control` (paired ratio `1.178`).
  - `v1_anchoring_authority_confirmation` (`[30]`, `n = 1`): `0.650` vs `0.540` control (paired ratio `1.204`).
  - `v3_grudge_falsemem_misforward` (`[30, 31]`, `n = 2`): `0.645` vs `0.545` control (paired ratio `1.183`).
- Because `v1.6` did not lower `gemini-4-carbon` below `v1.4` on shared seeds and OpenCode `0-9` did not complete `10/10` below `v1.4`, **Gate B is NOT met** and `v1.4` ships unchanged as the default benchmark.

---

## 4. Cross-Checked Headline Metrics Ledger

Every row in the table below is recomputed from primary repository artifacts and cross-checked offline in `<5s` by `scripts/verify_staffai_branch.py`:

| Metric Key | Verified Value | Primary Source / Verification |
|---|---|---|
| `tiers_version` | `v1.4` | `canary/rules.py` (`rules.TIERS_VERSION`) |
| `frozen_v14_tier_hash` | `a8f99c2537c91d72` | `canary/rules.py` (`TIERS` + `KNOWN_V_MODE`) |
| `default_provider` | `template` | `canary/text/gemini.py` (`get_provider(None)`) |
| `solver_v14_hard_0_9` | `0.576` | `results/v16_social/paired_v14_vs_v16_0_9.json` + committed `v1.4/reference` |
| `solver_v16_hard_0_9` | `0.576` | `results/v16_social/paired_v14_vs_v16_0_9.json` (`reference_checks.solver_v16_mean`) |
| `do_nothing_hard_0_9` | `0.000` | `results/v16_social/paired_v14_vs_v16_0_9.json` + live `DoNothing` spot check |
| `stop_early_hard_0_9` | `0.000` | `results/v16_social/paired_v14_vs_v16_0_9.json` + live `StopEarlyQuit` spot check |
| `v14_opencode_hard_0_9_raw_mean` | `0.351` | `results/v16_social/paired_v14_vs_v16_0_9.json` + committed `v1.4/opencode-gemini-4-carbon` |
| `v14_opencode_hard_0_9_raw_pct` | `60.9%` | Recomputed `(0.351 / 0.576) * 100` (`60.9375%`) |
| `v14_opencode_hard_0_9_luck_adj_mean` | `0.310` | Recomputed `per_seed` luck-adjusted mean (`0.309555`) |
| `v14_opencode_hard_0_9_luck_adj_pct` | `55.7%` | Recomputed `(0.309555 / 0.555805) * 100` (`55.6949%`) |
| `v14_opencode_hard_0_9_accuracy` | `0.90` | Recomputed `9/10` correct accusations on `hard` seeds `0-9` |
| `v14_opencode_hard_0_9_mean_day` | `14.5` | Recomputed mean `final_day` across `hard` seeds `0-9` |
| `v16_opencode_hard_0_9_n_valid` | `0/10` | `results/v16_social/paired_v14_vs_v16_0_9.json` (`arms['v1.6'].n_valid`) |
| `relayed_30_32_v5_full9_mean` | `0.617` | Recomputed `(0.50 + 0.64 + 0.71) / 3` on `hard` seeds `30-32` |
| `relayed_30_32_v0_control_mean` | `0.523` | Recomputed `(0.54 + 0.55 + 0.48) / 3` on `hard` seeds `30-32` |
| `relayed_30_32_paired_ratio` | `1.178` | Recomputed `0.616667 / 0.523333` on `hard` seeds `30-32` |
| `relayed_30_v1_mean` | `0.650` | `azure_relayed_30_44` (`v1_anchoring_authority_confirmation`, seed `30`) |
| `relayed_30_31_v3_mean` | `0.645` | Recomputed `(0.65 + 0.64) / 2` (`v3_grudge_falsemem_misforward`, seeds `30-31`) |
| `reference_30_49_solver_raw_mean` | `0.431` | `results/v16_social/reference_seeds_30_49.json` (`20` `hard` seeds `30-49`) |
| `reference_30_32_solver_luck_adj_mean` | `0.410` | Recomputed `(0.17546 + 0.52 + 0.53452) / 3` (`hard` seeds `30-32`) |
| `gate_b_status` | `NOT MET` | `paired_comparison.ship_gate.gate_met == False` and `azure_relayed_30_44.gate_met == False` |
| `shipped_default_version` | `v1.4` | Frozen `v1.4` ships unchanged (`CANARY_PROVIDER=template`) |
| `gemini_cache_real_files` | `256` | `data/gemini_cache/*.json` (`provenance.label == "REAL"`) |
| `gemini_cache_model` | `gemini-4-carbon` | `data/gemini_cache/*.json` (`provenance.model == "gemini-4-carbon"`) |
| `gemini_cache_social_bodies` | `712` | Sum of validated `bodies` across all `256` `data/gemini_cache/*.json` files |
| `v6_horizon_active_days` | `1..21` | `canary/social/horizon_escalation.py` (`21/21` active social days) |
| `v6_horizon_total_messages` | `63` | `3` validated social messages/day across `Days 1..21` (`9+12+18+15+9`) |
| `v6_horizon_late_window_messages` | `9` | `Days 19..21` stopping-window coverage (`3` msgs/day vs `0` in `v5`) |
| `v6_horizon_post_day1_callbacks` | `58/60` | `96.7%` post-Day-1 causal callbacks (`57/57` = `100.0%` on `Days 3..21`) |

---

## 5. Offline Reproduce and Branch Hygiene Commands

Run the complete StaffAI branch hygiene and cross-report consistency verifier (`100%` offline, `0` Gemini API calls, `<5s`):

```bash
PYTHONPATH=. CANARY_OFFLINE=1 /tmp/fleet-silas/shared/agent-arena-venv/bin/python scripts/verify_staffai_branch.py
PYTHONPATH=. CANARY_OFFLINE=1 /tmp/fleet-silas/shared/agent-arena-venv/bin/pytest -q tests/test_staffai_branch_hygiene.py tests/test_submission_audit.py
```
