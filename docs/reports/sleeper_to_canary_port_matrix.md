# Sleeper-to-Canary Port Matrix and Invariant Audit (`58716742`)

*Reproduce offline with zero API keys: `python scripts/sleeper_port_audit.py --check`. Audits `origin/justSilas@58716742` (`TIERS_VERSION = v1.4`, `KNOWN_V_MODE = True`, `0` v1.6 social files) and verifies machine-checked fairness and `SolverPolicy` catchability invariants across every ported Sleeper idea.*

## 1. Executive Summary

The 8-seat multi-agent **Sleeper** prototype (`origin/momin`) and the one-agent deductive **Canary** benchmark (`origin/justSilas`) were unified into Canary for the AfterQuery submission. Every high-leverage Sleeper idea that strengthens a one-agent, deterministic, replay-verified benchmark was ported into Canary `v1.4`, while multi-seat chatter ideas were tested in `v1.5-candidate` (`origin/justSilas-v15` / `origin/justSilas-gemini-v15`) and dropped at Gate B when real `gemini-4-carbon` trials showed they narrowed rather than widened the frontier gap.

- **Mapped pillars:** `5` flagship Sleeper ideas + `2` supporting infrastructure/adversary ports (`7` total entries; `39` repo files verified).
- **Fairness invariants passed:** `15 / 15` (`100%`).
- **Solver catchability invariants passed:** `7 / 7` (`100%`).
- **v1.6 social files in workspace:** `0` (strictly pure one-agent `v1.4` runtime).

## 2. Master Sleeper-to-Canary Port Matrix

| No. | Sleeper idea (origin) | Canary v1.4 counterpart (shipped) | Canary v1.5 counterpart (Gate B) | Fairness invariant verified | Solver catchability verified | Status |
|---|---|---|---|---|---|---|
| 1 | **Cheat Corpus and Midpoint Foreign-Tool Injection** (`redteam/cheat_corpus.py`) | `canary/redteam/corpus.py`, `data/redteam/corpus.jsonl`, `canary/redteam/anticheat.py` | `evaluated_dropped_at_gate_b` | `corpus_schema_always_invalid`, `midpoint_injection_zero_perturbation`, `anticheat_battery_and_pad_invariance` | `solver_dominates_all_attack_and_effort_probes` | **PASS** |
| 2 | **Multi-Employee Social Chains, Framing, and Human-Bias Layer** (`sleeper/goals/__init__.py`) | `canary/world.py`, `canary/env.py`, `canary/mole/dsl.py` | `evaluated_dropped_at_gate_b` | `public_day_facts_mole_independence_and_lint`, `decoy_strictly_innocent_and_non_exploitable` | `forge_and_rl_mole_catchability_floor` | **PASS** |
| 3 | **Surface-Tells Audit, Known-V Non-Disclosure, and Fair-Bar Bounds** (`sleeper/detell.py`) | `canary/world.py`, `canary/env.py`, `canary/rules.py` | `evaluated_dropped_at_gate_b` | `instruction_completeness_and_tool_smoke`, `mole_vs_innocent_error_and_accuse_parity`, `known_v_hides_unsurfaced_leaks_and_log_counts_carry_zero_hard_signal` | `solver_catchability_without_surface_tells` | **PASS** |
| 4 | **Failure Gallery and Below-Break-Even Accusation Spotlight** (`lab/gallery.py`) | `canary/gemini/gallery.py`, `canary/gemini/gallery_breakeven.py`, `canary/analysis/accuse.py` | `evaluated_dropped_at_gate_b` | `exact_additive_gap_accounting_zero_residual`, `public_evidence_posterior_and_verbatim_quotes` | `solver_zero_below_breakeven_stopping_discipline` | **PASS** |
| 5 | **Office Replay Dashboard, Side-by-Side CLI, and Browser Case-File Game** (`web/export.py`) | `scripts/demo_replay.py`, `scripts/verify_replay.py`, `game/canary_game.py` | `evaluated_dropped_at_gate_b` | `browser_game_seed_hygiene_and_truth_hiding`, `dashboard_secret_redaction_and_self_contained_offline_html` | `deterministic_replay_and_pyodide_solver_parity` | **PASS** |
| 6 | **Salted Judge Worlds, 0600 Secret Isolation, and Signed-Ledger Rescore** (`sleeper/secrets.py`) | `canary/world.py`, `canary/mcp_server.py`, `canary/redteam/tamper_guard.py` | `evaluated_dropped_at_gate_b` | `hmac_salted_judge_worlds_and_public_dev_reproducibility`, `signed_ledger_tamper_rejection_and_harbor_consistency` | `harbor_oracle_and_cheat_probe_separation` | **PASS** |
| 7 | **Scripted Attack Library and Winnability Gate to Mole DSL and RL Mole** (`sleeper/goals/leak.py`) | `canary/mole/dsl.py`, `canary/forge/evolve.py`, `canary/forge/fitness.py` | `evaluated_dropped_at_gate_b` | `mole_view_information_barrier_and_dsl_determinism` | `stackelberg_lagrangian_catchability_constraint` | **PASS** |

## 3. Pillar-by-Pillar Technical Mapping and Invariant Proofs

### 3.1 Cheat Corpus (`cheat_corpus`)

- **Sleeper origin:** Momin's `redteam/cheat_corpus.py` and `redteam/cheat_eval.py` (`Inject` at `ticks // 2`), mining `129` distinct failed/foreign tool-call patterns (`782` raw attempts across `10` Sleeper tools: `add_vendor, approve_vendor, close_ticket, pay, post_chat, quarantine, report_insider, send_email, update_crm, update_vendor_bank`) from `gemini-3.5-flash` transcripts, plus `control_pad`.
- **Canary v1.4 counterpart:** `canary/redteam/corpus.py` + `data/redteam/corpus.jsonl` + `results/anticheat/corpus_eval.txt` (`1161` midpoint-injected solver runs = `129 x 3 seeds x 3 tiers`, `0` accepted, `0` score changes), integrated with `canary/redteam/anticheat.py` (`garbage_args`, `control_solver_then_pad`, `solver_plus_*`) and `canary/redteam/harbor_cheat.py` (`cheat_probe`, `149` out-of-band attempts x `6` trials = `0.0`).
- **Canary v1.5 counterpart:** Same strict 13-tool `_SPECS` schema gate; `make hunt TIER=all TV=v1.5-candidate` verified `0` invariant violations and `0.000` best non-solver score.
- **Fairness & catchability proof:** Live audit confirms `129/129` corpus rows satisfy `_always_invalid == True`, foreign calls consume `1` global cap slot without changing `V`, `day`, or `actions_left_today`, `control_solver_then_pad` equals `solver` to `0.0` across all tiers, and `SolverPolicy` scores `+0.765 / +0.671 / +0.545` on the 40 judge seeds while all attack probes score `<= 0.000`.

### 3.2 Multi-Employee Social Chains (`multi_employee_social_chains`)

- **Sleeper origin:** 8-seat least-privilege office (`sleeper/goals/{fraud,leak,backdoor,sabotage,frame}.py`, 30 strategies) where two-person gates forced the sleeper to persuade or frame colleagues over chat and email.
- **Canary v1.4 counterpart:** Distills multi-employee entanglement into deterministic single-investigator mechanics without LLM background staff: 2-department regular documents (`p_single_dept_recipients = 0.0`), vocal innocent decoy (`decoy = True` on medium/hard), Poisson + Mole DSL after-hours framing (`framing_rate = 2.0` on hard, `framing_decoy_share = 0.5`), and noisy HR interviews (`interview_lr = 1.2`), grounded in `44` sourced corporate failure cases (`data/failures/cases_*.json`, `docs/research-biases.md`).
- **Canary v1.5 counterpart (tested, dropped at Gate B):** `origin/justSilas-v15` added endogenous one-agent `rumours` (`2.0/day`, `40%` decoy-seeded -> `LR = 1.0`), `grudges` (`2` pairs), `authority` (day-3 manager post), `p_misforward = 0.15`, and DSL `seed_rumour`. While `rumour_follower` collapsed to `-0.995` (`n=400`), real OpenCode `gemini-4-carbon` on hard seeds `0..9` rose from `61%` to **`108%` of solver** (`0.664` vs `0.615`), so `v1.5` was honestly retired at Gate B (`docs/SUBMISSION.md`, `docs/reports/gap.md`).
- **Fairness & catchability proof:** Counterfactually swapping `_world.mole` across 60 day-renders produces `0` changes in `PublicDayFacts` or `TemplateProvider.day_messages` and `0` `lint_messages` hits; `decoy != mole` holds on `60/60` medium/hard worlds (`accuse_decoy = -1.000`); and both `hard_forge` and `hard_rl` enforce `solver_acc >= 0.75` (held-out RL mole `n=100`: solver acc `0.75`, score `+0.3954` vs `grok_tactics` `+0.1643` and `heuristic` `-0.2942`).

### 3.3 Surface-Tells Audit (`surface_tells_audit`)

- **Sleeper origin:** `sleeper/detell.py` (`origin/vaishnav/sleeper-tells` @ `e08b62ff`, `docs/generator-v2.md`), which closed Sleeper v1 wording (`tmplagent.py` `1.000`), whole-number amount, `XX`-IBAN, vendor-ID, and fixed-ticket-count (`ctonly` `0.95`) tells by replacing legit tickets in-place while preserving `1.000` reference/oracle solvability.
- **Canary v1.4 counterpart:** `canary/world.py` draws all employee names, departments, roles, and clearances *before* sampling `decoy` and `mole`; `canary/rules.py` sets `KNOWN_V_MODE = True` (closing v1.2 same-day `V`-drop timing tells) and `log_rate_mole = log_rate_benign = 1.0` on hard (closing raw access-count tells); `canary/env.py` enforces mole-vs-innocent error/detail parity (`1bc3e281`); `canary/redteam/text_probe.py` enforces exact binomial `fair_bar(tier, k)` (`k=2`: easy `0.1394`, medium `0.0737`, hard `0.0345`); and `scripts/instruction_audit.py` + `docs/DIFFICULTY.md` verify `34/34` `TierParams` fields per tier and `39/39` tool smoke calls.
- **Canary v1.5 counterpart:** Draws unseeded rumour/authority targets over all non-speaker employees (including the mole) and grudge pairs over all non-decoy employees so being targeted never acts as a free innocence-exclusion tell.
- **Fairness & catchability proof:** `0` mole-vs-innocent error or post-accuse parity differences across 10 hard seeds, `0/57` unsurfaced-leak `V` disclosures, `accuse_most_logs = -1.000` on medium and hard, while `SolverPolicy` reaches **`96.5%`** accuracy when accusing (`mean = +0.565`) on `n=400` fresh hard seeds (`results/skill_ladder_v1.4.csv`).

### 3.4 Failure Gallery Below-Break-Even Spotlight (`failure_gallery_breakeven_spotlight`)

- **Sleeper origin:** `lab/gallery.py` + `lab/analyse.py` (`origin/sleeper/lab-analyst-gallery`), pairing deterministic failure-mode decomposition with verbatim transcript proof.
- **Canary v1.4 counterpart:** `canary/gemini/gallery.py` (`295` episodes decomposed, `196` on v1.4, net gap `+72.27`, unexplained `0.0`) plus `canary/gemini/gallery_breakeven.py` (`docs/reports/failure_gallery_breakeven.md`, PR 45 / `44584580`), which evaluates every accusation on the `30` judged v1.4 hard seeds against the exact moving threshold `P*(V) = 1 / (1 + V)` from `EV(accuse | P, V) = P * V - (1 - P)`.
- **Canary v1.5 counterpart:** `canary/analysis/accuse.py` + `canary/analysis/tags.py` over the 10-seed `v1.5-candidate` spot-check (`data/runs/committed/v1.5-candidate/opencode-gemini-4-carbon/`).
- **Fairness & catchability proof:** On OpenCode `gemini-4-carbon` v1.4 hard (`seeds 0..29`), seeds `[5, 18, 23]` violated `P < 1 / (1 + V)` under `E[true V]`, `V_true`, and shown `V_known`, losing `-0.9348 V` in decision EV (`48.46%` of Gemini's accusation-penalty gap) masked by `+0.3268 V` of lucky hits (including seed 18 at `62.72% < 68.43%`, mislabeled `justified` by fixed `0.60` cutoffs). `SolverPolicy` made **`0 / 30`** below-break-even accusations (tightest margin `+11.60 pp` on seed 10).

### 3.5 Office Replay Dashboard (`office_replay_dashboard`)

- **Sleeper origin:** `web/export.py` + `web/app.js` seat-mode office replay (`origin/sleeper/dm-dashboard-default`) + `lab/action_replay.py`.
- **Canary v1.4 counterpart:** Three zero-key replay surfaces: (1) `scripts/demo_replay.py` + `scripts/verify_replay.py` for side-by-side day-by-day `visible_V` and `SolverPolicy` `P(mole)` replay (`seed 4`: solver `+0.73` day `5` vs Gemini `+0.40` day `16`; `seed 18`: solver `+0.52` vs Gemini `-1.00`; `seed 26`: solver `+0.69` vs Gemini `-1.00`), (2) `game/` Pyodide browser case-file UI with Ivar's break-even accuse dialog on public dev seeds `3000..9999` (`seed 3000` parity: `+0.79`, `48` calls, day `6`), and (3) self-contained offline `results/gemini/dashboard.html` (`368.1 KB`) + `canary/gemini/lab_replay.py` (`6` step-hashed showcase episodes).
- **Canary v1.5 counterpart:** `scripts/with_tiers.py` + `scripts/verify_replay.py` verifying `10/10` replay fidelity under `v1.5-candidate` (`6/10` under `v1.4`).
- **Fairness & catchability proof:** `6/6` canonical hard replays match recorded scores to `< 1e-9`; `canary_game.py` rejects benchmark seeds (`0, 2999, 10000, 100000, 800000, 900000`), burns `0` hidden tool calls, hides truth until `done`, and matches CPython `SolverPolicy` exactly; `dashboard.py` redacts secret tokens and embeds `0` external HTTP assets.

### 3.6 Supporting Infrastructure and Adversary Ports (`salted_sidecar_and_signed_ledger`, `catchability_constrained_mole_adversary`)

- **Salted judge worlds & signed-ledger rescore:** Ports `sleeper/secrets.py`, `harbor/sidecar.py`, and `sleeper/verifier.py` into `canary/world.py` (HMAC-SHA256 fail-closed judge/held-out worlds), `canary/mcp_server.py` (0600 `CANARY_*_FILE` secret loading), and `canary/redteam/tamper_guard.py` (HMAC-signed `/ledger`, `80/80` Harbor trials, `18/18` jobs, `1021` replayed episodes across `51814` steps with `0` mismatches; forged `c1-tamper` negative control graded `0`).
- **Catchability-constrained mole adversary:** Ports Sleeper's scripted strategy library and `winnable=true` gate into the safe `12`-rule JSON `MoleStrategy` DSL (`canary/mole/dsl.py`, blind to `is_canary` and `variants`) and Lagrangian `RLMole` (`canary/forge/rl_mole.py`, dual ascent on `solver_acc >= 0.75`, raising held-out heuristic regret from `+0.4926` to `+0.6896` while preserving `75%` solver accuracy).

## 4. Complete Invariant Ledger

| Entry ID | Invariant | Kind | Metric | Pass |
|---|---|---|---|---|
| `cheat_corpus` | `corpus_schema_always_invalid` | fairness | `{"always_invalid": 129, "foreign_tools": 10, "rows": 129}` | **PASS** |
| `cheat_corpus` | `midpoint_injection_zero_perturbation` | fairness | `{"accepted": 0, "changed": 0, "committed_runs": 1161, "live_spot_runs": 13}` | **PASS** |
| `cheat_corpus` | `anticheat_battery_and_pad_invariance` | fairness | `{"attack_rows_blocked": "42/42", "max_pad_diff": 0.0}` | **PASS** |
| `cheat_corpus` | `solver_dominates_all_attack_and_effort_probes` | catchability | `{"hard_effort_90_mean": 0.051, "solver_judge40_means": {"easy": 0.765, "hard": 0.545, "medium": 0.671}}` | **PASS** |
| `multi_employee_social_chains` | `public_day_facts_mole_independence_and_lint` | fairness | `{"counterfactual_diffs": 0, "lint_violations": 0, "messages_checked": 451}` | **PASS** |
| `multi_employee_social_chains` | `decoy_strictly_innocent_and_non_exploitable` | fairness | `{"accuse_decoy_means": {"easy": -0.81, "hard": -1.0, "medium": -1.0}, "decoy_disjoint": "60/60"}` | **PASS** |
| `multi_employee_social_chains` | `forge_and_rl_mole_catchability_floor` | catchability | `{"forge_live3_acc": 1.0, "hof_solver_acc": 0.855, "min_solver_acc_floor": 0.75, "rl_heldout_solver_acc": 0.75, "rl_heldout_solver_score": 0.3954}` | **PASS** |
| `surface_tells_audit` | `instruction_completeness_and_tool_smoke` | fairness | `{"params_printed_per_tier": {"easy": 34, "hard": 34, "medium": 34}, "tool_smoke": "39/39"}` | **PASS** |
| `surface_tells_audit` | `mole_vs_innocent_error_and_accuse_parity` | fairness | `{"fixed_error_codes": 5, "parity_mismatches": 0}` | **PASS** |
| `surface_tells_audit` | `known_v_hides_unsurfaced_leaks_and_log_counts_carry_zero_hard_signal` | fairness | `{"accuse_most_logs_means": {"easy": -0.641, "hard": -1.0, "medium": -1.0}, "hard_log_rates": [1.0, 1.0], "hidden_leak_disclosures": 0, "hidden_leak_states_checked": 57, "text_fair_bar_k2": {"easy": 0.1394, "hard": 0.0345, "medium": 0.0737}}` | **PASS** |
| `surface_tells_audit` | `solver_catchability_without_surface_tells` | catchability | `{"skill_ladder_n400_solver": {"easy": {"abstain_rate": 0.0, "acc_overall": 1.0, "acc_when_accusing": 1.0, "mean_score": 0.7933, "n": 400}, "hard": {"abstain_rate": 0.0075, "acc_overall": 0.9575, "acc_when_accusing": 0.9647, "mean_score": 0.5645, "n": 400}, "medium": {"abstain_rate": 0.13, "acc_overall": 0.87, "acc_when_accusing": 1.0, "mean_score": 0.6284, "n": 400}}}` | **PASS** |
| `failure_gallery_breakeven_spotlight` | `exact_additive_gap_accounting_zero_residual` | fairness | `{"breakeven_30seed_max_residual": 2.220446049250313e-16, "gallery_episodes": 295, "gallery_max_residual": 4.440892098500626e-16, "gallery_net_gap": 90.795}` | **PASS** |
| `failure_gallery_breakeven_spotlight` | `public_evidence_posterior_and_verbatim_quotes` | fairness | `{"below_breakeven_seeds": [5, 18, 23], "seed18_p_vs_breakeven": [0.6272, 0.6843], "verified_quote_seeds": [5, 11, 18, 23]}` | **PASS** |
| `failure_gallery_breakeven_spotlight` | `solver_zero_below_breakeven_stopping_discipline` | catchability | `{"cohort_below_be_counts": {"inproc_gemini_4_carbon": 3, "opencode_gemini_3_5_flash": 10, "opencode_gemini_4_carbon": 3, "solver": 0}, "solver_below_be": 0, "solver_min_margin_pp": 11.6}` | **PASS** |
| `office_replay_dashboard` | `browser_game_seed_hygiene_and_truth_hiding` | fairness | `{"allowed_dev_seed_range": [3000, 9999], "rejected_benchmark_seeds": "6/6"}` | **PASS** |
| `office_replay_dashboard` | `dashboard_secret_redaction_and_self_contained_offline_html` | fairness | `{"external_network_tags": 0, "lab_replay_showcase_episodes": 6, "redacted_tokens": 3}` | **PASS** |
| `office_replay_dashboard` | `deterministic_replay_and_pyodide_solver_parity` | catchability | `{"canonical_hard_seeds_replayed": [4, 18, 26], "game_seed3000_solver": {"correct": true, "final_day": 6, "score": 0.79, "tool_calls": 48}, "replay_mismatches": 0}` | **PASS** |
| `salted_sidecar_and_signed_ledger` | `hmac_salted_judge_worlds_and_public_dev_reproducibility` | fairness | `{"judge_seeds_tested": 5, "public_dev_seed42_identical": true, "salted_diverged": 5}` | **PASS** |
| `salted_sidecar_and_signed_ledger` | `signed_ledger_tamper_rejection_and_harbor_consistency` | fairness | `{"harbor_jobs_consistent": "18/18", "harbor_trials_consistent": "80/80", "replayed_episodes": "1021/1021", "replayed_steps": 51814, "step_mismatches": 0}` | **PASS** |
| `salted_sidecar_and_signed_ledger` | `harbor_oracle_and_cheat_probe_separation` | catchability | `{"do_nothing_and_cheat_probe_zero": true, "oracle_positive": true}` | **PASS** |
| `catchability_constrained_mole_adversary` | `mole_view_information_barrier_and_dsl_determinism` | fairness | `{"deterministic_replay_3seeds": true, "frame_selectors": 4, "leak_selectors": 6, "mole_view_fields": 11}` | **PASS** |
| `catchability_constrained_mole_adversary` | `stackelberg_lagrangian_catchability_constraint` | catchability | `{"default_solver_acc": 0.97, "regret_vs_grok_tactics": [0.1957, 0.2311], "regret_vs_heuristic": [0.4926, 0.6896], "rl_solver_acc": 0.75}` | **PASS** |

## 5. Reproduction

```bash
python scripts/sleeper_port_audit.py
python scripts/sleeper_port_audit.py --check
pytest tests/test_sleeper_port_audit.py
```
