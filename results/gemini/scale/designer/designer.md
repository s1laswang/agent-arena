DONE 2026-11-15 06:48:48 EET

# Gemini PAIRED Scenario Designer (`arena mode, not the judged environment`)

> **Scope label: `arena mode, not the judged environment`.** Every run on this page varies only the Mole DSL strategy (`Env(..., mole_strategy=...)`) on public dev seeds `0–4` (`medium` tier, `n=5` seeds per cell) in-process. Frozen v1.4 judged rules, solver, and reward code are untouched. Zero `gemini-4-carbon` API calls were made.

- **Stamped:** `2026-11-15 06:48:48 EET` · **Git SHA:** `eb7db8336023` · **Run ID:** `ws5-designer-v1`
- **Proposer:** `gemini-4-hydrogen` (served: `gemini-4-hydrogen`)
- **Filter investigator:** `gemini-3.8-flash` at `thinking_level=low` (served: `gemini-3.8-flash`, in-process `LLMPolicy`, full history + thought-signature replay)
- **Stronger transfer investigator:** `gemini-4-argon` at `thinking_level=high` (served: `gemini-4-argon`, in-process `LLMPolicy`)
- **PAIRED acceptance criterion (`medium`, dev seeds `0–4`):** `SolverPolicy` mean **≥ 0.50** AND `gemini-3.8-flash` (`low`) mean **≤ 0.20**.

---

## 1. Headline Acceptance & Transfer Summary (`arena mode, not the judged environment`)

| Metric | Count | Rate [95% Wilson CI] | Notes |
|---|---:|---:|---|
| Valid distinct DSL strategies proposed (`gemini-4-hydrogen`) | 281 / 500 | — | 34 ledgered proposal batches; 0 stub fallbacks |
| Stage 1 — Solvable by reference `SolverPolicy` (mean ≥ 0.50, `n=5`) | 50 / 281 | **17.8% [13.8%, 22.7%]** | Rejects non-leaking or information-starved moles in CPU pre-filter |
| **PAIRED Accepted (`solver ≥ 0.50` AND `3.8-flash-low ≤ 0.20`)** | **32 / 281** | **11.4% [8.2%, 15.6%]** | Conditional break rate among solver-feasible: 64.0% [50.1%, 75.9%] |
| Behavioral equivalence classes accepted (deduped by truth-table + trace) | 32 / 280 | 11.4% [8.2%, 15.7%] | 50 unique solver-feasible behavioral classes |
| **Transfer to `gemini-4-argon` (`high` thinking) on Top-1 hardest** | **0 / 1 also ≤ 0.20** | **0.0% [0.0%, 79.3%]** | Mean score on Top-1: solver `+0.608`, flash-low `-0.528`, argon-high `+0.662` |

### Default-Mole Reference Baseline (`DEFAULT_STRATEGY`, same 5 dev seeds `0–4`, `medium`)
- **Reference `SolverPolicy`:** `+0.644 ± 0.140` (acc `100%`, `n=5`)
- **`gemini-3.8-flash` (`low` thinking):** `-0.356 ± 0.785` (acc `40%`, `n=5`)
- **`gemini-4-argon` (`high` thinking):** `+0.296 ± 0.645` (acc `80%`, `n=5`)

---

## 2. Top 10 Hardest PAIRED Mole Strategies (`arena mode, not the judged environment`)

Ranked by paired regret (`solver_mean − flash_low_mean`) across distinct behavioral classes on `medium` dev seeds `0–4` (`n=5` per cell):

| Rank | ID & Name | Archetype | Solver ± CI (acc) | `3.8-flash` low ± CI (acc) | Paired Gap [boot 95% CI] | `4-argon` high ± CI (acc) | Argon ≤ 0.20? |
|---:|---|---|---:|---:|---:|---:|---|
| 1 | `cand-0073` rc_stealth_pause_on_double_lock | `restriction_counterpuncher` | `+0.502 ± 0.253` (80%) | `-1.000 ± 0.000` (0%) | **`+1.502`** [+1.24, +1.67] | — | — |
| 2 | `cand-0235` sprinter_v11_colleague_cover | `late_horizon_sprinter` | `+0.600 ± 0.052` (100%) | `-0.710 ± 0.568` (20%) | **`+1.310`** [+0.78, +1.59] | — | — |
| 3 | `cand-0078` late_sprint_v4_gap_exploiter | `late_horizon_sprinter` | `+0.554 ± 0.292` (80%) | `-0.644 ± 0.698` (20%) | **`+1.198`** [+0.60, +1.65] | `+0.662 ± 0.052` (100%) | no |
| 4 | `cand-0062` rc_escalating_containment | `restriction_counterpuncher` | `+0.524 ± 0.271` (80%) | `-0.650 ± 0.686` (20%) | **`+1.174`** [+0.60, +1.64] | — | — |
| 5 | `cand-0114` fresh_doc_peer_scatter | `peer_scatter_framer` | `+0.502 ± 0.260` (80%) | `-0.660 ± 0.666` (20%) | **`+1.162`** [+0.55, +1.63] | — | — |
| 6 | `cand-0230` sprinter_v6_restricted_aware | `late_horizon_sprinter` | `+0.778 ± 0.046` (100%) | `-0.338 ± 0.795` (40%) | **`+1.116`** [+0.45, +1.78] | — | — |
| 7 | `cand-0276` threshold_edge_switcher_07 | `threshold_edge_switcher` | `+0.766 ± 0.065` (100%) | `-0.302 ± 0.838` (40%) | **`+1.068`** [+0.38, +1.77] | — | — |
| 8 | `cand-0110` high_held_peer_scatter | `peer_scatter_framer` | `+0.624 ± 0.161` (100%) | `-0.380 ± 0.745` (40%) | **`+1.004`** [+0.24, +1.77] | — | — |
| 9 | `cand-0198` decoy_restricted_pivot | `decoy_amplifier` | `+0.676 ± 0.076` (100%) | `-0.274 ± 0.872` (40%) | **`+0.950`** [+0.23, +1.66] | — | — |
| 10 | `cand-0048` decoy_stale_docs_4 | `decoy_amplifier` | `+0.556 ± 0.281` (80%) | `-0.326 ± 0.809` (40%) | **`+0.882`** [+0.15, +1.62] | — | — |

### DSL Rules of the Top 10 Strategies

#### #1 · `cand-0073` — rc_stealth_pause_on_double_lock (`restriction_counterpuncher`)
- **Designer rationale:** Pauses only when both self and 3+ colleagues are restricted, otherwise counterpunches with oldest.
- **Scores (`n=5`, seeds `0–4`):** solver `[0.59, 0.7, 0.68, 0.54, 0.0]` (mean `+0.502`) · 3.8-flash-low `[-1.0, -1.0, -1.0, -1.0, -1.0]` (mean `-1.000`) · 4-argon-high pending
- **Mole DSL JSON:** `{"default":{"frame":"random_peer","leak":"oldest"},"rules":[{"if":[["i_am_restricted","==",1],["n_restricted_colleagues",">=",3]],"then":{"frame":"most_restricted_peer","leak":"none"}},{"if":[["i_am_restricted","==",1]],"then":{"frame":"most_restricted_peer","leak":"oldest"}},{"if":[["n_restricted_colleagues",">=",1],["n_docs_held",">=",3]],"then":{"frame":"decoy","leak":"most_recipients"}}]}`

#### #2 · `cand-0235` — sprinter_v11_colleague_cover (`late_horizon_sprinter`)
- **Designer rationale:** Use most_restricted_peer when restricted colleagues are plentiful, decoy otherwise.
- **Scores (`n=5`, seeds `0–4`):** solver `[0.59, 0.7, 0.58, 0.59, 0.54]` (mean `+0.600`) · 3.8-flash-low `[-1.0, 0.45, -1.0, -1.0, -1.0]` (mean `-0.710`) · 4-argon-high pending
- **Mole DSL JSON:** `{"default":{"frame":"random_peer","leak":"oldest"},"rules":[{"if":[["day","<=",4],["min_recipient_count","<=",2]],"then":{"frame":"decoy","leak":"most_recipients"}},{"if":[["day",">=",6],["n_restricted_colleagues",">=",3]],"then":{"frame":"most_restricted_peer","leak":"newest"}},{"if":[["day",">=",6]],"then":{"frame":"decoy","leak":"random_seeded"}}]}`

#### #3 · `cand-0078` — late_sprint_v4_gap_exploiter (`late_horizon_sprinter`)
- **Designer rationale:** Early on, only leak if days_since_last_leak >= 2; after day 6, leak newest every chance.
- **Scores (`n=5`, seeds `0–4`):** solver `[0.57, 0.76, 0.0, 0.58, 0.86]` (mean `+0.554`) · 3.8-flash-low `[-1.0, -1.0, -1.0, -1.0, 0.78]` (mean `-0.644`) · 4-argon-high `[0.64, 0.73, 0.71, 0.58, 0.65]` (mean `+0.662`)
- **Mole DSL JSON:** `{"default":{"frame":"most_restricted_peer","leak":"random_seeded"},"rules":[{"if":[["day","<=",4],["days_since_last_leak","<",2]],"then":{"frame":"decoy","leak":"none"}},{"if":[["day","<=",4]],"then":{"frame":"random_peer","leak":"most_recipients"}},{"if":[["day",">=",6],["newest_doc_age_days","==",0]],"then":{"frame":"decoy","leak":"newest"}}]}`

#### #4 · `cand-0062` — rc_escalating_containment (`restriction_counterpuncher`)
- **Designer rationale:** Escalates framing to most_restricted_peer under direct or colleague restriction while shifting between oldest and fewest_recipients.
- **Scores (`n=5`, seeds `0–4`):** solver `[0.59, 0.75, 0.75, 0.53, 0.0]` (mean `+0.524`) · 3.8-flash-low `[-1.0, -1.0, 0.75, -1.0, -1.0]` (mean `-0.650`) · 4-argon-high pending
- **Mole DSL JSON:** `{"default":{"frame":"random_peer","leak":"most_recipients"},"rules":[{"if":[["i_am_restricted","==",1],["n_leakable",">=",3]],"then":{"frame":"most_restricted_peer","leak":"oldest"}},{"if":[["n_restricted_colleagues",">=",1],["day",">=",5]],"then":{"frame":"most_restricted_peer","leak":"fewest_recipients"}},{"if":[["n_docs_held",">=",4]],"then":{"frame":"decoy","leak":"oldest"}}]}`

#### #5 · `cand-0114` — fresh_doc_peer_scatter (`peer_scatter_framer`)
- **Designer rationale:** Leaks newest with random_peer on fresh docs in week 1, then oldest with decoy.
- **Scores (`n=5`, seeds `0–4`):** solver `[0.49, 0.7, 0.73, 0.59, 0.0]` (mean `+0.502`) · 3.8-flash-low `[-1.0, 0.7, -1.0, -1.0, -1.0]` (mean `-0.660`) · 4-argon-high pending
- **Mole DSL JSON:** `{"default":{"frame":"decoy","leak":"oldest"},"rules":[{"if":[["newest_doc_age_days","==",0],["day","<=",7]],"then":{"frame":"random_peer","leak":"newest"}},{"if":[["n_leakable",">=",3]],"then":{"frame":"decoy","leak":"oldest"}},{"if":[["days_since_last_leak",">=",1]],"then":{"frame":"decoy","leak":"random_seeded"}}]}`

#### #6 · `cand-0230` — sprinter_v6_restricted_aware (`late_horizon_sprinter`)
- **Designer rationale:** If restricted, lay low early; otherwise sprint hard from day 6 with newest.
- **Scores (`n=5`, seeds `0–4`):** solver `[0.8, 0.75, 0.85, 0.78, 0.71]` (mean `+0.778`) · 3.8-flash-low `[0.64, -1.0, -1.0, 0.67, -1.0]` (mean `-0.338`) · 4-argon-high pending
- **Mole DSL JSON:** `{"default":{"frame":"random_peer","leak":"random_seeded"},"rules":[{"if":[["i_am_restricted","==",1],["day","<=",4]],"then":{"frame":"most_restricted_peer","leak":"none"}},{"if":[["day","<=",4],["min_recipient_count","<=",3]],"then":{"frame":"decoy","leak":"most_recipients"}},{"if":[["day",">=",6],["n_leakable",">=",2]],"then":{"frame":"decoy","leak":"newest"}}]}`

#### #7 · `cand-0276` — threshold_edge_switcher_07 (`threshold_edge_switcher`)
- **Designer rationale:** 5-rule switcher emphasizing n_docs_held and min_recipient_count edges.
- **Scores (`n=5`, seeds `0–4`):** solver `[0.74, 0.8, 0.8, 0.84, 0.65]` (mean `+0.766`) · 3.8-flash-low `[0.72, -1.0, -1.0, 0.77, -1.0]` (mean `-0.302`) · 4-argon-high pending
- **Mole DSL JSON:** `{"default":{"frame":"decoy","leak":"newest"},"rules":[{"if":[["day","<=",3],["n_docs_held",">=",2]],"then":{"frame":"decoy","leak":"oldest"}},{"if":[["day",">=",4],["day","<=",7],["min_recipient_count",">=",2]],"then":{"frame":"random_peer","leak":"fewest_recipients"}},{"if":[["day",">=",8],["n_docs_held",">=",5]],"then":{"frame":"most_restricted_peer","leak":"oldest"}},{"if":[["day",">=",11],["days_since_last_leak",">=",1]],"then":{"frame":"decoy","leak":"most_recipients"}},{"if":[["days_since_last_leak",">=",3]],"then":{"frame":"most_restricted_peer","leak":"random_seeded"}}]}`

#### #8 · `cand-0110` — high_held_peer_scatter (`peer_scatter_framer`)
- **Designer rationale:** Frames random_peer when holding many docs early, then shifts to decoy and most_restricted_peer.
- **Scores (`n=5`, seeds `0–4`):** solver `[0.65, 0.8, 0.8, 0.44, 0.43]` (mean `+0.624`) · 3.8-flash-low `[-1.0, -1.0, -1.0, 0.59, 0.51]` (mean `-0.380`) · 4-argon-high pending
- **Mole DSL JSON:** `{"default":{"frame":"decoy","leak":"most_recipients"},"rules":[{"if":[["n_docs_held",">=",5],["day","<=",6]],"then":{"frame":"random_peer","leak":"oldest"}},{"if":[["n_leakable",">=",3]],"then":{"frame":"decoy","leak":"oldest"}},{"if":[["n_restricted_colleagues",">=",2]],"then":{"frame":"most_restricted_peer","leak":"newest"}}]}`

#### #9 · `cand-0198` — decoy_restricted_pivot (`decoy_amplifier`)
- **Designer rationale:** Frames decoy early, pivots to most_restricted_peer when restricted colleagues exist.
- **Scores (`n=5`, seeds `0–4`):** solver `[0.74, 0.7, 0.74, 0.53, 0.67]` (mean `+0.676`) · 3.8-flash-low `[-1.0, 0.84, 0.79, -1.0, -1.0]` (mean `-0.274`) · 4-argon-high pending
- **Mole DSL JSON:** `{"default":{"frame":"decoy","leak":"random_seeded"},"rules":[{"if":[["day","<=",4],["n_docs_held",">=",2]],"then":{"frame":"decoy","leak":"most_recipients"}},{"if":[["day","<=",6],["newest_doc_age_days",">=",1]],"then":{"frame":"decoy","leak":"oldest"}},{"if":[["i_am_restricted","==",1]],"then":{"frame":"most_restricted_peer","leak":"most_recipients"}},{"if":[["n_restricted_colleagues",">=",3]],"then":{"frame":"most_restricted_peer","leak":"oldest"}}]}`

#### #10 · `cand-0048` — decoy_stale_docs_4 (`decoy_amplifier`)
- **Designer rationale:** Frame decoy for the first 6 days leaking oldest, then leak newest when newest_doc_age_days is fresh.
- **Scores (`n=5`, seeds `0–4`):** solver `[0.65, 0.8, 0.74, 0.59, 0.0]` (mean `+0.556`) · 3.8-flash-low `[0.7, -1.0, -1.0, 0.67, -1.0]` (mean `-0.326`) · 4-argon-high pending
- **Mole DSL JSON:** `{"default":{"frame":"decoy","leak":"most_recipients"},"rules":[{"if":[["day","<=",6]],"then":{"frame":"decoy","leak":"oldest"}},{"if":[["newest_doc_age_days","==",0],["n_leakable",">=",2]],"then":{"frame":"random_peer","leak":"newest"}}]}`

---

## 3. Methodology & Honesty Notes (`arena mode, not the judged environment`)

1. **Strictly `arena mode, not the judged environment`:** None of these strategies modify or enter the judged v1.4 benchmark. Only `mole_strategy` in `Env('medium', seed, mole_strategy=...)` varies; `TierParams` are untouched.
2. **Selection-bias caveat (in-sample 5-seed filter):** Filtering candidates on `flash_low_mean <= 0.20` over 5 seeds selects partly for genuine strategic difficulty and partly for negative luck on those 5 seeds (each wrong accusation is `-1.0`). Evaluating the **independent `gemini-4-argon` (`high` thinking)** model on the selected Top-10 provides an out-of-model transfer test free of filter-selection luck on Argon's own rollouts.
3. **Behavioral equivalence caching:** Distinct DSL JSONs that evaluate to the exact same `(leak, frame)` choices across our 6,912-state reachable `MoleView` truth-table and solver trajectory trace share one behavioral class (`behavior_key`), avoiding redundant API spend on dead-branch syntactic variants while reporting both raw-proposal and deduplicated class acceptance rates.
4. **Infra-error handling:** Transport/quota errors (`429`, `5xx`, timeouts) are retried with 60s quota backoff and never scored as `0`.
