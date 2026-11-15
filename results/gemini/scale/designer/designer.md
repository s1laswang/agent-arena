DONE 2026-11-15 07:43:59 EET

# Gemini PAIRED Scenario Designer (`arena mode, not the judged environment`)

> **Scope label: `arena mode, not the judged environment`.** Every run on this page varies only the Mole DSL strategy (`Env(..., mole_strategy=...)`) on public dev seeds `0–4` (`medium` tier, `n=5` seeds per cell) in-process. Frozen v1.4 judged rules, solver, and reward code are untouched. Zero `gemini-4-carbon` API calls were made.

- **Stamped:** `2026-11-15 07:43:59 EET` · **Git SHA:** `31e279285960` · **Run ID:** `ws5-designer-v1`
- **Proposer:** `gemini-4-hydrogen` (served: `gemini-4-hydrogen`)
- **Filter investigator:** `gemini-3.8-flash` at `thinking_level=low` (served: `gemini-3.8-flash`, in-process `LLMPolicy`, full history + thought-signature replay)
- **Stronger transfer investigator:** `gemini-4-argon` at `thinking_level=high` (served: `gemini-4-argon`, in-process `LLMPolicy`)
- **PAIRED acceptance criterion (`medium`, dev seeds `0–4`):** `SolverPolicy` mean **≥ 0.50** AND `gemini-3.8-flash` (`low`) mean **≤ 0.20**.

---

## 1. Headline Acceptance & Transfer Summary (`arena mode, not the judged environment`)

| Metric | Count | Rate [95% Wilson CI] | Notes |
|---|---:|---:|---|
| Valid distinct DSL strategies proposed (`gemini-4-hydrogen`) | 481 / 500 | — | 34 ledgered proposal batches; 0 stub fallbacks |
| Stage 1 — Solvable by reference `SolverPolicy` (mean ≥ 0.50, `n=5`) | 107 / 481 | **22.2% [18.8%, 26.2%]** | Rejects non-leaking or information-starved moles in CPU pre-filter |
| **PAIRED Accepted (`solver ≥ 0.50` AND `3.8-flash-low ≤ 0.20`)** | **65 / 481** | **13.5% [10.8%, 16.9%]** | Conditional break rate among solver-feasible: 60.8% [51.3%, 69.5%] |
| Behavioral equivalence classes accepted (deduped by truth-table + trace) | 65 / 477 | 13.6% [10.8%, 17.0%] | 107 unique solver-feasible behavioral classes |
| **Transfer to `gemini-4-argon` (`high` thinking) on Top-5 hardest** | **2 / 5 also ≤ 0.20** | **40.0% [11.8%, 76.9%]** | Mean score on Top-5: solver `+0.607`, flash-low `-0.637`, argon-high `+0.526` |

### Default-Mole Reference Baseline (`DEFAULT_STRATEGY`, same 5 dev seeds `0–4`, `medium`)
- **Reference `SolverPolicy`:** `+0.644 ± 0.140` (acc `100%`, `n=5`)
- **`gemini-3.8-flash` (`low` thinking):** `-0.356 ± 0.785` (acc `40%`, `n=5`)
- **`gemini-4-argon` (`high` thinking):** `+0.296 ± 0.645` (acc `80%`, `n=5`)

---

## 2. Top 10 Hardest PAIRED Mole Strategies (`arena mode, not the judged environment`)

Ranked by paired regret (`solver_mean − flash_low_mean`) across distinct behavioral classes on `medium` dev seeds `0–4` (`n=5` per cell):

| Rank | ID & Name | Archetype | Solver ± CI (acc) | `3.8-flash` low ± CI (acc) | Paired Gap [boot 95% CI] | `4-argon` high ± CI (acc) | Argon ≤ 0.20? |
|---:|---|---|---:|---:|---:|---:|---|
| 1 | `cand-0073` rc_stealth_pause_on_double_lock | `restriction_counterpuncher` | `+0.502 ± 0.253` (80%) | `-1.000 ± 0.000` (0%) | **`+1.502`** [+1.24, +1.67] | `+0.195 ± 0.782` (75%, n=4) | **YES** |
| 2 | `cand-0436` dilution_hybrid_midgame_pivot | `canary_dilution_hybrid` | `+0.630 ± 0.311` (80%) | `-0.682 ± 0.623` (20%) | **`+1.312`** [+0.70, +1.79] | — | — |
| 3 | `cand-0235` sprinter_v11_colleague_cover | `late_horizon_sprinter` | `+0.600 ± 0.052` (100%) | `-0.710 ± 0.568` (20%) | **`+1.310`** [+0.78, +1.59] | `+0.817 ± 0.091` (100%, n=3) | no |
| 4 | `cand-0428` late_surge_switcher | `threshold_edge_switcher` | `+0.596 ± 0.086` (100%) | `-0.630 ± 0.725` (20%) | **`+1.226`** [+0.47, +1.67] | — | — |
| 5 | `cand-0470` peer_frame_stale_flip | `stale_doc_ambusher` | `+0.566 ± 0.286` (80%) | `-0.642 ± 0.702` (20%) | **`+1.208`** [+0.54, +1.75] | — | — |
| 6 | `cand-0078` late_sprint_v4_gap_exploiter | `late_horizon_sprinter` | `+0.554 ± 0.292` (80%) | `-0.644 ± 0.698` (20%) | **`+1.198`** [+0.60, +1.65] | `+0.662 ± 0.052` (100%, n=5) | no |
| 7 | `cand-0359` colleague_restriction_mirror | `restriction_counterpuncher` | `+0.796 ± 0.056` (100%) | `-0.394 ± 0.728` (40%) | **`+1.190`** [+0.57, +1.81] | — | — |
| 8 | `cand-0062` rc_escalating_containment | `restriction_counterpuncher` | `+0.524 ± 0.271` (80%) | `-0.650 ± 0.686` (20%) | **`+1.174`** [+0.60, +1.64] | `+0.150 ± 1.128` (67%, n=3) | **YES** |
| 9 | `cand-0114` fresh_doc_peer_scatter | `peer_scatter_framer` | `+0.502 ± 0.260` (80%) | `-0.660 ± 0.666` (20%) | **`+1.162`** [+0.55, +1.63] | `+0.807 ± 0.121` (100%, n=3) | no |
| 10 | `cand-0449` trap_evader_midgame_decoy | `trap_evader` | `+0.798 ± 0.052` (100%) | `-0.360 ± 0.768` (40%) | **`+1.158`** [+0.51, +1.81] | — | — |

### DSL Rules of the Top 10 Strategies

#### #1 · `cand-0073` — rc_stealth_pause_on_double_lock (`restriction_counterpuncher`)
- **Designer rationale:** Pauses only when both self and 3+ colleagues are restricted, otherwise counterpunches with oldest.
- **Scores (`n=5`, seeds `0–4`):** solver `[0.59, 0.7, 0.68, 0.54, 0.0]` (mean `+0.502`) · 3.8-flash-low `[-1.0, -1.0, -1.0, -1.0, -1.0]` (mean `-1.000`) · 4-argon-high `[0.55, 0.65, 0.58, -1.0]` (mean `+0.195`)
- **Mole DSL JSON:** `{"default":{"frame":"random_peer","leak":"oldest"},"rules":[{"if":[["i_am_restricted","==",1],["n_restricted_colleagues",">=",3]],"then":{"frame":"most_restricted_peer","leak":"none"}},{"if":[["i_am_restricted","==",1]],"then":{"frame":"most_restricted_peer","leak":"oldest"}},{"if":[["n_restricted_colleagues",">=",1],["n_docs_held",">=",3]],"then":{"frame":"decoy","leak":"most_recipients"}}]}`

#### #2 · `cand-0436` — dilution_hybrid_midgame_pivot (`canary_dilution_hybrid`)
- **Designer rationale:** Pivot framing and leak selection around day 7 while strictly obeying dilution when low-recipient docs are present.
- **Scores (`n=5`, seeds `0–4`):** solver `[0.8, 0.0, 0.85, 0.73, 0.77]` (mean `+0.630`) · 3.8-flash-low `[0.59, -1.0, -1.0, -1.0, -1.0]` (mean `-0.682`) · 4-argon-high pending
- **Mole DSL JSON:** `{"default":{"frame":"decoy","leak":"newest"},"rules":[{"if":[["recent_low_recipient_docs",">=",1]],"then":{"frame":"decoy","leak":"most_recipients"}},{"if":[["day","<=",7],["recent_low_recipient_docs","==",0]],"then":{"frame":"random_peer","leak":"random_seeded"}},{"if":[["day",">=",8],["recent_low_recipient_docs","==",0],["n_docs_held",">=",3]],"then":{"frame":"most_restricted_peer","leak":"newest"}},{"if":[["days_since_last_leak",">=",2]],"then":{"frame":"decoy","leak":"oldest"}}]}`

#### #3 · `cand-0235` — sprinter_v11_colleague_cover (`late_horizon_sprinter`)
- **Designer rationale:** Use most_restricted_peer when restricted colleagues are plentiful, decoy otherwise.
- **Scores (`n=5`, seeds `0–4`):** solver `[0.59, 0.7, 0.58, 0.59, 0.54]` (mean `+0.600`) · 3.8-flash-low `[-1.0, 0.45, -1.0, -1.0, -1.0]` (mean `-0.710`) · 4-argon-high `[0.81, 0.9, 0.74]` (mean `+0.817`)
- **Mole DSL JSON:** `{"default":{"frame":"random_peer","leak":"oldest"},"rules":[{"if":[["day","<=",4],["min_recipient_count","<=",2]],"then":{"frame":"decoy","leak":"most_recipients"}},{"if":[["day",">=",6],["n_restricted_colleagues",">=",3]],"then":{"frame":"most_restricted_peer","leak":"newest"}},{"if":[["day",">=",6]],"then":{"frame":"decoy","leak":"random_seeded"}}]}`

#### #4 · `cand-0428` — late_surge_switcher (`threshold_edge_switcher`)
- **Designer rationale:** Shifts from oldest+random_peer early to random_seeded+decoy mid-episode to newest+most_restricted_peer late.
- **Scores (`n=5`, seeds `0–4`):** solver `[0.62, 0.75, 0.58, 0.49, 0.54]` (mean `+0.596`) · 3.8-flash-low `[-1.0, -1.0, 0.85, -1.0, -1.0]` (mean `-0.630`) · 4-argon-high pending
- **Mole DSL JSON:** `{"default":{"frame":"decoy","leak":"most_recipients"},"rules":[{"if":[["day","<=",6],["n_docs_held",">=",3]],"then":{"frame":"random_peer","leak":"oldest"}},{"if":[["day",">=",7],["day","<=",10],["days_since_last_leak",">=",1]],"then":{"frame":"decoy","leak":"random_seeded"}},{"if":[["day",">=",11],["min_recipient_count","<=",5]],"then":{"frame":"most_restricted_peer","leak":"newest"}}]}`

#### #5 · `cand-0470` — peer_frame_stale_flip (`stale_doc_ambusher`)
- **Designer rationale:** Flips framing from most_restricted_peer in week 1 to decoy in week 2 while leaking oldest.
- **Scores (`n=5`, seeds `0–4`):** solver `[0.84, 0.65, 0.64, 0.7, 0.0]` (mean `+0.566`) · 3.8-flash-low `[-1.0, -1.0, 0.79, -1.0, -1.0]` (mean `-0.642`) · 4-argon-high pending
- **Mole DSL JSON:** `{"default":{"frame":"random_peer","leak":"random_seeded"},"rules":[{"if":[["day","<=",7],["n_docs_held",">=",3]],"then":{"frame":"most_restricted_peer","leak":"oldest"}},{"if":[["day",">=",8],["n_leakable",">=",2]],"then":{"frame":"decoy","leak":"oldest"}}]}`

#### #6 · `cand-0078` — late_sprint_v4_gap_exploiter (`late_horizon_sprinter`)
- **Designer rationale:** Early on, only leak if days_since_last_leak >= 2; after day 6, leak newest every chance.
- **Scores (`n=5`, seeds `0–4`):** solver `[0.57, 0.76, 0.0, 0.58, 0.86]` (mean `+0.554`) · 3.8-flash-low `[-1.0, -1.0, -1.0, -1.0, 0.78]` (mean `-0.644`) · 4-argon-high `[0.64, 0.73, 0.71, 0.58, 0.65]` (mean `+0.662`)
- **Mole DSL JSON:** `{"default":{"frame":"most_restricted_peer","leak":"random_seeded"},"rules":[{"if":[["day","<=",4],["days_since_last_leak","<",2]],"then":{"frame":"decoy","leak":"none"}},{"if":[["day","<=",4]],"then":{"frame":"random_peer","leak":"most_recipients"}},{"if":[["day",">=",6],["newest_doc_age_days","==",0]],"then":{"frame":"decoy","leak":"newest"}}]}`

#### #7 · `cand-0359` — colleague_restriction_mirror (`restriction_counterpuncher`)
- **Designer rationale:** Mirror colleague restrictions by framing most_restricted_peer when colleagues are restricted, and switching to random_peer early.
- **Scores (`n=5`, seeds `0–4`):** solver `[0.8, 0.8, 0.89, 0.78, 0.71]` (mean `+0.796`) · 3.8-flash-low `[0.56, 0.47, -1.0, -1.0, -1.0]` (mean `-0.394`) · 4-argon-high pending
- **Mole DSL JSON:** `{"default":{"frame":"decoy","leak":"newest"},"rules":[{"if":[["n_restricted_colleagues",">=",1],["day",">=",6]],"then":{"frame":"most_restricted_peer","leak":"oldest"}},{"if":[["day","<=",5],["n_docs_held",">=",2]],"then":{"frame":"random_peer","leak":"random_seeded"}}]}`

#### #8 · `cand-0062` — rc_escalating_containment (`restriction_counterpuncher`)
- **Designer rationale:** Escalates framing to most_restricted_peer under direct or colleague restriction while shifting between oldest and fewest_recipients.
- **Scores (`n=5`, seeds `0–4`):** solver `[0.59, 0.75, 0.75, 0.53, 0.0]` (mean `+0.524`) · 3.8-flash-low `[-1.0, -1.0, 0.75, -1.0, -1.0]` (mean `-0.650`) · 4-argon-high `[-1.0, 0.76, 0.69]` (mean `+0.150`)
- **Mole DSL JSON:** `{"default":{"frame":"random_peer","leak":"most_recipients"},"rules":[{"if":[["i_am_restricted","==",1],["n_leakable",">=",3]],"then":{"frame":"most_restricted_peer","leak":"oldest"}},{"if":[["n_restricted_colleagues",">=",1],["day",">=",5]],"then":{"frame":"most_restricted_peer","leak":"fewest_recipients"}},{"if":[["n_docs_held",">=",4]],"then":{"frame":"decoy","leak":"oldest"}}]}`

#### #9 · `cand-0114` — fresh_doc_peer_scatter (`peer_scatter_framer`)
- **Designer rationale:** Leaks newest with random_peer on fresh docs in week 1, then oldest with decoy.
- **Scores (`n=5`, seeds `0–4`):** solver `[0.49, 0.7, 0.73, 0.59, 0.0]` (mean `+0.502`) · 3.8-flash-low `[-1.0, 0.7, -1.0, -1.0, -1.0]` (mean `-0.660`) · 4-argon-high `[0.9, 0.83, 0.69]` (mean `+0.807`)
- **Mole DSL JSON:** `{"default":{"frame":"decoy","leak":"oldest"},"rules":[{"if":[["newest_doc_age_days","==",0],["day","<=",7]],"then":{"frame":"random_peer","leak":"newest"}},{"if":[["n_leakable",">=",3]],"then":{"frame":"decoy","leak":"oldest"}},{"if":[["days_since_last_leak",">=",1]],"then":{"frame":"decoy","leak":"random_seeded"}}]}`

#### #10 · `cand-0449` — trap_evader_midgame_decoy (`trap_evader`)
- **Designer rationale:** Uses random_peer framing early, switches to decoy with most_recipients midgame when traps peak, and leaks oldest late.
- **Scores (`n=5`, seeds `0–4`):** solver `[0.8, 0.8, 0.89, 0.73, 0.77]` (mean `+0.798`) · 3.8-flash-low `[0.58, 0.62, -1.0, -1.0, -1.0]` (mean `-0.360`) · 4-argon-high pending
- **Mole DSL JSON:** `{"default":{"frame":"decoy","leak":"newest"},"rules":[{"if":[["day","<=",4],["n_leakable",">=",2]],"then":{"frame":"random_peer","leak":"random_seeded"}},{"if":[["day",">=",5],["day","<=",9],["recent_low_recipient_docs",">=",1]],"then":{"frame":"decoy","leak":"most_recipients"}},{"if":[["day",">=",10],["min_recipient_count","<=",4]],"then":{"frame":"decoy","leak":"oldest"}}]}`

---

## 3. Methodology & Honesty Notes (`arena mode, not the judged environment`)

1. **Strictly `arena mode, not the judged environment`:** None of these strategies modify or enter the judged v1.4 benchmark. Only `mole_strategy` in `Env('medium', seed, mole_strategy=...)` varies; `TierParams` are untouched.
2. **Selection-bias caveat (in-sample 5-seed filter):** Filtering candidates on `flash_low_mean <= 0.20` over 5 seeds selects partly for genuine strategic difficulty and partly for negative luck on those 5 seeds (each wrong accusation is `-1.0`). Evaluating the **independent `gemini-4-argon` (`high` thinking)** model on the selected Top-10 provides an out-of-model transfer test free of filter-selection luck on Argon's own rollouts.
3. **Behavioral equivalence caching:** Distinct DSL JSONs that evaluate to the exact same `(leak, frame)` choices across our 4,096-state reachable `MoleView` truth-table and solver trajectory trace share one behavioral class (`behavior_key`), avoiding redundant API spend on dead-branch syntactic variants while reporting both raw-proposal and deduplicated class acceptance rates.
4. **Infra-error handling:** Transport/quota errors (`429`, `5xx`, timeouts) are retried with 60s quota backoff and never scored as `0`.
