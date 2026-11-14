# V1.6 Social Layer: Rules Disclosure and Candidate README Templates

This document provides paste-ready text for the opt-in V1.6 social layer (`canary/social/`, `CANARY_PROVIDER=v16:<variant>`). Full architecture and per-bias design notes live in `docs/v16-social-design.md`.

**Gate rule (pre-registered):** `README.md`, `docs/CONTRACT.md`, and `canary/rules.py` remain untouched unless the paired hard-tier evaluation on dev seeds `0-9` passes all five ship gates verified by `scripts/v16_readme_snippet.py`:
1. `gemini_vs_solver_ratio < v14_ratio` (paired against the committed `v1.4` hard seeds `0-9` baseline);
2. `do_nothing_mean == 0`;
3. `stop_early_mean == 0` (stops on day 1 with no accusation);
4. `solver_calibration_zero == True` (`solver_mean` under `v16:<variant>` equals `solver_v14_mean` under `template`);
5. `replay_verified == True` (`100%` of episodes replay-verified against deterministic `Env`).

If any gate fails (including `v16_ratio >= v14_ratio`), `v1.4` remains the sole headline in `README.md`, and the honest negative-result disclosure in Section 3B is pasted into `docs/HISTORY.md` (matching the `v1.5-candidate` record in `docs/reports/CEO.md`).

---

## 1. Paste-Ready Rules and `docs/CONTRACT.md` Disclosure

### 1A. `docs/CONTRACT.md` Section (`§15. V1.6 opt-in workplace social layer`)

```markdown
## 15. V1.6 opt-in workplace social layer (`CANARY_PROVIDER=v16:<variant>`)
**Why:** real corporate leak investigations unfold inside noisy internal communication channels where unverified office rumours, senior opinions, cross-team consensus, and personal grudges compete for attention alongside hard forensic evidence (canary variants and leak-feed delays). V1.6 ports multi-day workplace cognitive-bias threads into Canary's message stream while keeping every tier parameter, tool schema, and optimal Bayesian decision rule of `v1.4` intact.

- **Activation (off by default):**
  - Default `CANARY_PROVIDER` (unset or `template`) serves the frozen `v1.4` `TemplateProvider` unchanged.
  - Setting `CANARY_PROVIDER=v16:<variant>` enables `V16SocialProvider` in deterministic, keyless template mode (`v16:v0_v14_control` is an exact control alias for `TemplateProvider`). Optional cached LLM rewrites (`v16-gemini:<variant>`, `v16-gemini-stub:<variant>`) pass the same strict validator and fall back per item to the deterministic template draft on any lint or schema violation.
  - `TIERS`, `TIERS_VERSION = "v1.4"`, `KNOWN_V_MODE = True`, daily action budgets, `tool_call_cap`, and server-side HMAC ledger scoring are untouched.
- **Nine workplace cognitive biases (`canary/social/biases.py`, `BIAS_TYPES`):**
  1. `authority`: senior staff (`manager`, `lead`, `controller`, `counsel`) state confident but explicitly unverified suspicion around a colleague.
  2. `recency`: urgent post-meeting alerts pulling focus toward a freshly named colleague.
  3. `confirmation`: follow-up notes reading ordinary document handoffs or quiet meeting behaviour as confirming an earlier suspicion thread.
  4. `bandwagon`: cross-department sync messages reporting that multiple peers converged on the same suspect.
  5. `anchoring`: Day 1-2 suspicion threads tied to initial document circulation that later days revisit as the primary lead.
  6. `grudge`: persistent multi-day interpersonal disputes (`grudge_pairs`) blaming a rival colleague for mishandled drafts.
  7. `misforward`: accidental-forward and cc routing chatter placing a colleague near a restricted document thread.
  8. `false_memory`: confident but unverified recollections of who asked for offline copies on an earlier day.
  9. `sycophancy`: peer replies endorsing an earlier `authority` note by speaker name.
  - **Variant schedules (`canary/social/variants.py`):** `v0_v14_control` (0 biases, exact `v1.4` control), `v1_anchoring_authority_confirmation`, `v2_recency_bandwagon_sycophancy`, `v3_grudge_falsemem_misforward`, `v4_triad_authority_recency_grudge`, `v5_full9_cocktail` (all 9 biases across Days 1-18), plus single-bias ablations `b_<bias>`.
- **Strict `PublicDayFacts` isolation (zero mole access):**
  - `V16SocialProvider.day_messages(facts: PublicDayFacts)` receives only `PublicDayFacts` (`tier`, `seed`, `day`, `company`, `employees`, `docs`, `decoy`, `decoy_mood`, `restricted`).
  - `canary/social/` never imports `canary.world` and never reads `_world` or `mole` (enforced by static AST test and counterfactual mole-swap identity across Days 1-21 in `tests/test_v16_social_engine.py`).
  - Episode focal suspects (`primary_suspect`, `secondary_suspect`), `authority_speakers`, and `grudge_pairs` are seeded deterministically from `(variant, tier, seed)` using only Day 1 regular document recipient lists and non-decoy employee roles/departments.
  - Decoy separation: `facts.decoy` is never chosen as a social speaker or target, and `DECOY_VOCAB` / `ANGER_WORDS` are scrubbed from all non-decoy messages so the `v1.4` disgruntled-innocent decoy signal stays clean.
- **Exact Bayesian likelihood ratio = 1 (reference solver remains optimal without hidden adjustments):**
  - Because the social message stream `M_{1:t}` is generated solely from public facts `H^{pub}_{1:t}` with zero access to the true mole `S`, `P(M_{1:t} | S = e_i, H^{pub}_{1:t}) = P(M_{1:t} | S = e_j, H^{pub}_{1:t})` for every pair of non-decoy employees `(e_i, e_j)`.
  - The Bayesian likelihood ratio of every V1.6 social message with respect to mole identity is identically `1`.
  - Consequently, the exact posterior `P(S | H_{1:t})` and EV stopping rule (`accuse` when `P * E[true V] - (1 - P) > 0` and `P >= 0.85`, or at the horizon when positive EV) are unchanged. The unmodified `v1.4` `SolverPolicy` achieves `solver_calibration_diff = 0.0` against `template` with zero special-casing or hidden flags.
- **Baseline and reward invariance:**
  - `do_nothing` scores `0.000` (exact) and `stop_early` (stops on day 1 without accusing) scores `0.000` (exact).
  - Correct accusation scores true `V`; wrong accusation scores `-1.0`; no accusation scores `0.0`.
```

### 1B. Plain-English Agent Rule Disclosure (for `Env.instruction()` / `harbor/canary-task/instruction.md` when `v16` is active)

 Can be appended under `## Evidence` so the agent has complete information ("Every rule and number of the game is written on this page. Nothing is hidden except who the mole is"):

```markdown
- Internal messages (`search_messages`, `read_message`) also contain ordinary workplace speculation when the V1.6 social provider is enabled: early anchoring on Day 1 recipients, unverified senior opinions, urgent post-meeting notes, confirmation follow-ups, cross-team consensus, interpersonal grudges, accidental-forward chatter, unverified recollections, and sycophantic agreement. These messages are generated strictly from public employee roles and regular document recipient lists without access to who the mole is, so they carry zero true likelihood weight (`LR = 1`) on mole identity. One innocent decoy employee still writes angry messages about pay or promotions.
```

---

## 2. Committed `v1.4` Baseline Reference (Verified Keyless from `data/runs/committed/v1.4/`)

Reproduced locally with `/tmp/fleet-silas/shared/agent-arena-venv/bin/python scripts/paired_gemini.py --version v1.4 --seeds 0-9` (and `--seeds 0-29` for the full 30-seed committed set):

| slice | agent | score ± 95% CI | % of solver [95% CI] | luck-adjusted [95% CI] | n |
|---|---|---:|---:|---:|---:|
| hard, seeds `0-9` (gate baseline) | reference solver | +0.576 ± 0.108 | 100% | +0.556 (100%) | 10 |
| hard, seeds `0-9` (gate baseline) | `gemini-4-carbon`, OpenCode over MCP | +0.351 ± 0.312 | **61% [3%, 104%]** | +0.310 (**56% [21%, 80%]**) | 10 |
| hard, seeds `0-9` (gate baseline) | `gemini-4-carbon`, in-process | +0.379 ± 0.324 | 66% [5%, 117%] | +0.439 (79% [45%, 117%]) | 10 |
| hard, seeds `0-29` (`README.md` headline) | reference solver | +0.499 ± 0.119 | 100% | +0.499 (100%) | 30 |
| hard, seeds `0-29` (`README.md` headline) | `gemini-4-carbon`, OpenCode over MCP | +0.322 ± 0.199 | **65% [24%, 98%]** | +0.360 (**72% [52%, 91%]**) | 30 |
| hard, judge seeds (`results/judge_table.md`) | `do_nothing` | +0.000 ± 0.000 | 0% | +0.000 (0%) | 40 |
| hard, judge seeds (`results/judge_table.md`) | `stop_early` (stops on day 1, no accusation) | +0.000 ± 0.000 | 0% | +0.000 (0%) | 40 |

On hard seeds `0-9` (`OpenCode over MCP`), the ship threshold for `v16:<variant>` is strictly `gemini_vs_solver_ratio < 0.609375` (`60.9%`, rounded `61%` in `paired_gemini.py`), alongside `do_nothing_mean == 0`, `stop_early_mean == 0`, `solver_calibration_zero == True`, and `replay_verified == True`.

---

## 3. Paste-Ready `README.md` / `docs/HISTORY.md` Templates

Never fill `<...>` placeholders by hand. Always generate the exact table and paragraph from real JSON artifacts via `scripts/v16_readme_snippet.py` (Section 4).

### 3A. Positive-Gate `README.md` Section (use ONLY if `v16_ratio < v14_ratio` and all 5 ship gates pass)

```markdown
## Social bias layer (opt-in V1.6, `CANARY_PROVIDER=v16:<variant>`)

| agent | score ± 95% CI | % of solver [95% CI] | n |
|---|---:|---:|---:|
| reference solver (paired seeds <seeds>, v1.4 = v16:<variant>) | <solver_score_pm_ci> | 100% | <n> |
| gemini-4-carbon, <harness_label> (v1.4 baseline) | <v14_score_pm_ci> | <v14_ratio_pct>% [<v14_ratio_lo_pct>%, <v14_ratio_hi_pct>%]; luck-adjusted <v14_luck_ratio_pct>% [<v14_luck_lo_pct>%, <v14_luck_hi_pct>%] | <v14_n> |
| **gemini-4-carbon, <harness_label> (v16:<variant>)** | **<v16_score_pm_ci>** | **<v16_ratio_pct>% [<v16_ratio_lo_pct>%, <v16_ratio_hi_pct>%]**; luck-adjusted <v16_luck_ratio_pct>% [<v16_luck_lo_pct>%, <v16_luck_hi_pct>%] | <n> |
| do_nothing (v16:<variant>) | +0.000 ± 0.000 | 0% | <n> |
| stop_early (stops on day 1, no accusation) | +0.000 ± 0.000 | 0% | <n> |

- **What `v16:<variant>` adds (off by default).** Setting `CANARY_PROVIDER=v16:<variant>` injects multi-day workplace cognitive biases (authority, recency, confirmation, bandwagon, anchoring, grudge, misforward, false memory, sycophancy) generated strictly from `PublicDayFacts` with zero access to mole identity. Every social message has exact Bayesian likelihood ratio `1`, so the unmodified `v1.4` reference solver produces the exact same trajectory and score (`solver_calibration_diff = +0.000`).
- **Paired result and honest reading.** On <tier> dev seeds <seeds> (`n = <n>`, `<replay_count>/<n>` episodes replay-verified), `gemini-4-carbon` (<harness_label>) moves from <v14_ratio_pct>% [<v14_ratio_lo_pct>%, <v14_ratio_hi_pct>%] of the solver on `v1.4` (`<v14_score_pm_ci>`) to **<v16_ratio_pct>% [<v16_ratio_lo_pct>%, <v16_ratio_hi_pct>%]** (`<v16_score_pm_ci>`) under `v16:<variant>` (luck-adjusted <v14_luck_ratio_pct>% to <v16_luck_ratio_pct>%). `do_nothing` and `stop_early` remain `+0.000`. Because `n = <n>` has wide single-miss variance (`-1` on a wrong accusation shifts a 10-seed mean by `> 0.1`), `v1.4` (`n = 30`) remains the default judged tier and `CANARY_PROVIDER=v16:<variant>` ships as an opt-in evaluation track; see [docs/v16-social-design.md](docs/v16-social-design.md).
```

### 3B. Honest Negative-Result / Non-Ship Disclosure (use if `v16_ratio >= v14_ratio` or any gate fails)

Matches Silas's honest negative-result reporting for `v1.5-candidate` (`docs/reports/CEO.md`) and `solver_v2`:

```markdown
### V1.6 social bias candidate (negative / non-ship result, `CANARY_PROVIDER=v16:<variant>`)

| agent | score ± 95% CI | % of solver [95% CI] | n |
|---|---:|---:|---:|
| reference solver (paired seeds <seeds>, v1.4 = v16:<variant>) | <solver_score_pm_ci> | 100% | <n> |
| gemini-4-carbon, <harness_label> (v1.4 baseline) | <v14_score_pm_ci> | <v14_ratio_pct>% [<v14_ratio_lo_pct>%, <v14_ratio_hi_pct>%]; luck-adjusted <v14_luck_ratio_pct>% [<v14_luck_lo_pct>%, <v14_luck_hi_pct>%] | <v14_n> |
| gemini-4-carbon, <harness_label> (v16:<variant>) | <v16_score_pm_ci> | <v16_ratio_pct>% [<v16_ratio_lo_pct>%, <v16_ratio_hi_pct>%]; luck-adjusted <v16_luck_ratio_pct>% [<v16_luck_lo_pct>%, <v16_luck_hi_pct>%] | <n> |
| do_nothing (v16:<variant>) | <dn_score_pm_ci> | 0% | <n> |
| stop_early (stops on day 1, no accusation) | <se_score_pm_ci> | 0% | <n> |

- **Pre-registered ship gate: NOT PASSED (`<failed_gates_csv>`).** On <tier> dev seeds <seeds> (`n = <n>`), `gemini-4-carbon` (<harness_label>) reached <v16_ratio_pct>% [<v16_ratio_lo_pct>%, <v16_ratio_hi_pct>%] of the solver under `CANARY_PROVIDER=v16:<variant>` (`<v16_score_pm_ci>`, luck-adjusted <v16_luck_ratio_pct>%) versus <v14_ratio_pct>% [<v14_ratio_lo_pct>%, <v14_ratio_hi_pct>%] on the committed `v1.4` baseline (`<v14_score_pm_ci>`, luck-adjusted <v14_luck_ratio_pct>%), with `solver_calibration_diff = <cal_diff>`, `do_nothing = <dn_mean>`, `stop_early = <se_mean>`, and `<replay_count>/<n>` episodes replay-verified. Because the candidate did not lower `gemini_vs_solver_ratio` below `v1.4` (and/or failed a ship invariant), `v1.4` remains the sole judged environment in `README.md`, and `CANARY_PROVIDER=v16:<variant>` is kept off by default as a documented ablation (`docs/v16-social-design.md`).
```

---

## 4. Keyless Snippet Generator CLI (`scripts/v16_readme_snippet.py`)

Render the exact Markdown section and structured gate report directly from a `scripts/v16_eval_matrix.py` JSON artifact and the committed `v1.4` hard seeds `0-9` baseline (zero live API calls):

```bash
/tmp/fleet-silas/shared/agent-arena-venv/bin/python scripts/v16_readme_snippet.py \
    --v16-json /tmp/fleet-silas/shared/v16_runs/v5_hard_0_9.json \
    --out-md /tmp/opencode/v16_section.md \
    --out-json /tmp/opencode/v16_gate_report.json
```

Optional flags:
- `--v14-json <path>`: compare against an explicit `v16_eval_matrix.py` control JSON or `paired_gemini.py --out-json` file instead of reading `data/runs/committed/v1.4/` directly.
- `--v14-seeds 0-9`: seed specification for the committed `v1.4` baseline (default `0-9`; pass `match` to use the exact seed list inside `--v16-json`).
- `--strict-exit`: exit `1` when any of the 5 ship gates fails (`0` when all 5 pass).
