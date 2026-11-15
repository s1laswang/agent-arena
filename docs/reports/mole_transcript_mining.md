# Empirical Transcript Mining: Frontier Investigator Failure Modes and Fair Mole Levers

Generated offline from committed JSONL transcripts (`data/runs/committed/v1.4/` and `data/runs/committed/v1.3/`) via `python -m canary.mole.transcript_miner --out docs/reports/mole_transcript_mining.md`. All posteriors are replayed from public tool observations through `canary.solver.policy.SolverPolicy` (`canary.solver.belief.posterior`) and cross-verified against committed `accuse.md` tables.

## 1. Headline Empirical Findings

- **Frontier corpus audited**: 189 valid frontier episodes (60 `opencode:google/gemini-4-carbon` on v1.4, 60 `gemini:gemini-4-carbon` in-proc on v1.4, 30 `opencode:openai/gpt-5.5` on v1.4, 22 `codex:gpt-5.5` on v1.3, 17 `openai:gpt-5.5` in-proc on v1.3) paired against 100 reference `solver` episodes (60 on v1.4 seeds 0-29, 40 on v1.3 seeds 0-19).
- **100% angry-decoy dismissal vs non-decoy framing susceptibility**: Across 189 decoy-enabled frontier episodes, the angry decoy was accused **0** times and restricted **0** times (100.0% dismissal rate; angry decoy messages were retrieved in 167/189 episodes). In contrast, non-decoy framed after-hours logs broke 0-separation canary ties into -1.0 wrong accusations in **5/10** total frontier wrong accusations.
- **Single-separating-canary fragility under `fingerprint_accuracy=0.95`**: All **10/10** frontier wrong accusations occurred with `<=1` separating canary hit (`8/10` with 0 separating canaries), including **7** Hard-tier wrong accusations where a 5% fingerprint flip or single unconfirmed canary was treated as proof.
- **Sharp architectural split in canary sizing**: Codex/GPT-5.5 favor surgical `<=3`-recipient traps (30.6%-75.3% of planted canaries), whereas Gemini-4-carbon almost never uses `<=3` recipients (0.0%-0.6%), putting 98.6%-100.0% of canaries into 3 variants across 4-8 (43.6%-73.6%) or >=9 (26.4%-56.4%) recipients.
- **Gemini interview budget sink and delayed Day-1 canary start**: On v1.4 Hard (`canaries_per_day=2`), Gemini spends 57.27-68.03 calls/episode on low-LR interviews (`interview_lr=1.2`), delays its first canary until mean day 3.03 (OpenCode) and 3.40 (in-proc) vs Solver day 1.00, plants 0.64-0.69 canaries/day vs Solver 1.37/day, and accuses +1.97 to +2.52 days later than Solver (+0.063 V to +0.065 V extra pure leak drain on correct Hard episodes).
- **Below-breakeven horizon gambling**: Frontier agents made **23** accusations below the exact break-even bar `P(accused) < 1 / (1 + E[true V])`, including **13** final-day horizon gambles where abstaining (0.0) had higher EV.

## 2. Canary Planting Rate, Recipient Distribution, and Variant Count

| Cohort | Tier | n | Score +/- CI | Acc | Canaries/Ep | Canaries/Day | First Canary Day (d1%) | 2-Can/Day% | Surfaced% | Rec <=3 | Rec 4-8 | Rec >=9 | Var 1 / 2 / 3 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Gemini-4-carbon (OpenCode MCP) | hard | 30 | 0.322 +/- 0.199 | 83.3% | 8.47 | 0.64 | 3.03 (37%) | 24.8% | 19.3% (49/254) | 0.0% | 49.6% | 50.4% | 0% / 0% / 100% |
| Gemini-4-carbon (OpenCode MCP) | medium | 30 | 0.713 +/- 0.042 | 100.0% | 5.83 | 0.72 | 1.07 (93%) | 0.0% | 24.0% (42/175) | 0.6% | 58.3% | 41.1% | 0% / 0% / 100% |
| Gemini-4-carbon (In-Proc) | hard | 30 | 0.473 +/- 0.118 | 93.3% | 8.57 | 0.69 | 3.40 (30%) | 24.9% | 21.4% (55/257) | 0.0% | 43.6% | 56.4% | 0% / 0% / 100% |
| Gemini-4-carbon (In-Proc) | medium | 30 | 0.530 +/- 0.138 | 83.3% | 6.93 | 0.71 | 1.47 (80%) | 0.0% | 19.2% (40/208) | 0.0% | 73.6% | 26.4% | 0% / 1% / 99% |
| OpenCode GPT-5.5 (MCP, v1.4) | hard | 30 | 0.504 +/- 0.064 | 93.3% | 17.13 | 1.69 | 1.00 (100%) | 84.5% | 10.1% (52/514) | 47.1% | 14.8% | 38.1% | 4% / 6% / 89% |
| Reference Solver (v1.4, seeds 0-29) | hard | 30 | 0.499 +/- 0.119 | 96.7% | 14.13 | 1.37 | 1.00 (100%) | 42.8% | 11.6% (49/424) | 11.8% | 40.3% | 47.9% | 0% / 0% / 100% |
| Reference Solver (v1.4, seeds 0-29) | medium | 30 | 0.645 +/- 0.087 | 90.0% | 7.30 | 0.87 | 1.00 (100%) | 0.0% | 20.5% (45/219) | 47.5% | 49.8% | 2.7% | 0% / 29% / 71% |
| Codex GPT-5.5 (MCP) | hard | 11 | 0.654 +/- 0.041 | 100.0% | 10.09 | 0.87 | 1.00 (100%) | 0.0% | 19.8% (22/111) | 30.6% | 38.7% | 30.6% | 1% / 99% / 0% |
| Codex GPT-5.5 (MCP) | medium | 11 | 0.401 +/- 0.417 | 81.8% | 7.73 | 0.84 | 1.00 (100%) | 0.0% | 11.8% (10/85) | 75.3% | 10.6% | 14.1% | 11% / 8% / 81% |
| GPT-5.5 (In-Proc) | hard | 8 | 0.264 +/- 0.541 | 75.0% | 10.62 | 0.87 | 1.00 (100%) | 0.0% | 18.8% (16/85) | 43.5% | 18.8% | 37.6% | 9% / 91% / 0% |
| GPT-5.5 (In-Proc) | medium | 9 | 0.668 +/- 0.103 | 100.0% | 8.78 | 0.85 | 1.00 (100%) | 0.0% | 13.9% (11/79) | 73.4% | 15.2% | 11.4% | 0% / 25% / 75% |
| Reference Solver (v1.3, seeds 0-19) | hard | 20 | 0.592 +/- 0.114 | 85.0% | 10.40 | 0.92 | 1.00 (100%) | 0.0% | 13.9% (29/208) | 46.6% | 30.8% | 22.6% | 0% / 100% / 0% |
| Reference Solver (v1.3, seeds 0-19) | medium | 20 | 0.717 +/- 0.052 | 100.0% | 6.50 | 0.85 | 1.00 (100%) | 0.0% | 26.2% (34/130) | 42.3% | 54.6% | 3.1% | 0% / 25% / 75% |

## 3. Tool Budget Allocation (Mean Calls per Episode)

| Cohort | Tier | n | `interview` | `read_access_logs` | `search_messages` | `restrict_access` | `plant_canary` | `list_documents` | `check_leak_feed` | Failed Calls | Interview Share of Investigative |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Gemini-4-carbon (OpenCode MCP) | hard | 30 | 68.03 | 12.27 | 4.23 | 0.10 | 8.50 | 12.07 | 6.70 | 1.00 | 68.0% |
| Gemini-4-carbon (OpenCode MCP) | medium | 30 | 37.53 | 6.03 | 3.87 | 0.17 | 5.87 | 7.27 | 4.33 | 1.03 | 64.8% |
| Gemini-4-carbon (In-Proc) | hard | 30 | 57.27 | 11.80 | 4.40 | 0.27 | 8.57 | 11.83 | 6.33 | 0.93 | 64.4% |
| Gemini-4-carbon (In-Proc) | medium | 30 | 47.30 | 7.97 | 4.60 | 0.40 | 6.93 | 8.83 | 5.47 | 1.00 | 64.9% |
| OpenCode GPT-5.5 (MCP, v1.4) | hard | 30 | 4.17 | 8.57 | 8.73 | 0.00 | 17.17 | 8.63 | 9.20 | 0.13 | 8.6% |
| Reference Solver (v1.4, seeds 0-29) | hard | 30 | 0.00 | 9.60 | 7.53 | 0.00 | 14.13 | 10.60 | 10.60 | 0.00 | 0.0% |
| Reference Solver (v1.4, seeds 0-29) | medium | 30 | 0.00 | 7.20 | 7.67 | 0.00 | 7.30 | 8.20 | 8.20 | 0.00 | 0.0% |
| Codex GPT-5.5 (MCP) | hard | 11 | 8.73 | 10.18 | 11.00 | 0.82 | 10.09 | 10.64 | 10.64 | 0.00 | 16.6% |
| Codex GPT-5.5 (MCP) | medium | 11 | 11.64 | 7.64 | 11.82 | 0.27 | 7.73 | 8.00 | 8.09 | 0.55 | 24.5% |
| GPT-5.5 (In-Proc) | hard | 8 | 6.38 | 33.75 | 16.50 | 0.12 | 10.62 | 11.50 | 11.25 | 0.88 | 8.0% |
| GPT-5.5 (In-Proc) | medium | 9 | 7.78 | 22.89 | 12.44 | 0.22 | 8.78 | 9.22 | 9.11 | 1.22 | 12.6% |
| Reference Solver (v1.3, seeds 0-19) | hard | 20 | 0.00 | 10.25 | 7.60 | 0.00 | 10.40 | 11.25 | 11.25 | 0.00 | 0.0% |
| Reference Solver (v1.3, seeds 0-19) | medium | 20 | 0.00 | 6.50 | 7.70 | 0.00 | 6.50 | 7.50 | 7.50 | 0.00 | 0.0% |

## 4. Failure Anatomy: Fingerprint Flips, Accusation Lag, Gambles, and Decoy vs Framing

| Cohort | Tier | Wrong / Abstain | Accuse Day (Lag vs Solver) | Correct Leak V Drain (vs Solver) | <=1-Hit Acc under fp=0.95 (Wrong) | <=1-Sep Acc under fp=0.95 (Wrong) | Gambles P < 1/(1+V) (Horizon) | Decoy Msg Found / Max-AH / Dismissed | Non-Decoy Framed Tie-Break Wrong |
|---|---|---|---|---|---|---|---|---|---|
| Gemini-4-carbon (OpenCode MCP) | hard | 4 / 1 | 13.17 (+2.52d) | 0.370 V (+0.063 V) | 11 (1) | 24 (4) | 3 (2) | 30/30 / 29/30 / 100% | 2 |
| Gemini-4-carbon (OpenCode MCP) | medium | 0 / 0 | 7.97 (+0.15d) | 0.227 V (+0.009 V) | 0 (0) | 0 (0) | 2 (2) | 30/30 / 28/30 / 100% | 0 |
| Gemini-4-carbon (In-Proc) | hard | 1 / 1 | 12.69 (+1.97d) | 0.371 V (+0.065 V) | 8 (1) | 24 (1) | 3 (1) | 30/30 / 29/30 / 100% | 1 |
| Gemini-4-carbon (In-Proc) | medium | 1 / 4 | 9.04 (+1.35d) | 0.251 V (+0.033 V) | 0 (0) | 0 (0) | 3 (2) | 30/30 / 30/30 / 100% | 0 |
| OpenCode GPT-5.5 (MCP, v1.4) | hard | 0 / 2 | 10.25 (-0.61d) | 0.287 V (-0.019 V) | 12 (0) | 25 (0) | 1 (0) | 17/30 / 30/30 / 100% | 0 |
| Reference Solver (v1.4, seeds 0-29) | hard | 1 / 0 | 10.60 (baseline) | 0.307 V (baseline) | 15 (0) | 26 (1) | 0 (0) | 30/30 / 28/30 / 100% | 0 |
| Reference Solver (v1.4, seeds 0-29) | medium | 0 / 3 | 7.56 (baseline) | 0.218 V (baseline) | 0 (0) | 0 (0) | 0 (0) | 30/30 / 26/30 / 100% | 0 |
| Codex GPT-5.5 (MCP) | hard | 0 / 0 | 11.64 (+0.00d) | 0.229 V (+0.012 V) | 4 (0) | 8 (0) | 2 (0) | 9/11 / 10/11 / 100% | 0 |
| Codex GPT-5.5 (MCP) | medium | 2 / 0 | 8.82 (+1.55d) | 0.204 V (-0.006 V) | 0 (0) | 0 (0) | 5 (3) | 7/11 / 8/11 / 100% | 2 |
| GPT-5.5 (In-Proc) | hard | 2 / 0 | 12.25 (+1.00d) | 0.210 V (+0.013 V) | 2 (2) | 7 (2) | 3 (2) | 6/8 / 2/8 / 100% | 0 |
| GPT-5.5 (In-Proc) | medium | 0 / 0 | 9.89 (+2.44d) | 0.231 V (+0.018 V) | 0 (0) | 0 (0) | 1 (1) | 8/9 / 1/9 / 100% | 0 |
| Reference Solver (v1.3, seeds 0-19) | hard | 0 / 3 | 10.76 (baseline) | 0.206 V (baseline) | 5 (0) | 15 (0) | 0 (0) | 20/20 / 19/20 / 100% | 0 |
| Reference Solver (v1.3, seeds 0-19) | medium | 0 / 0 | 7.50 (baseline) | 0.218 V (baseline) | 0 (0) | 0 (0) | 0 (0) | 20/20 / 16/20 / 100% | 0 |

### 4.1 Episode-Level Anatomy of Wrong, Abstained, Gamble, and Severe V-Drain Runs

| Cohort | Tier | Seed | Day (Solver) | Accused | Score (Solver) | P(acc) vs BE | Surf Canaries (Hits / Sep) | Decoy (AH) | Accused AH (Cell Max AH, Cell Size) | Failure Mechanisms |
|---|---|---|---|---|---|---|---|---|---|---|
| `v1.4_gemini_opencode` | hard | 1 | 19 (7) | e39 | -1.00 (0.69) | 0.988 vs 0.757 | 3 (3 / 1) | e11 (13) | 4 (max=4, k=1) | `fp95_single_separating_canary` |
| `v1.4_gemini_opencode` | hard | 5 | 21 (9) | e27 | 0.16 (0.52) | 0.510 vs 0.861 | 1 (1 / 0) | e04 (23) | 8 (max=8, k=2) | `lucky_horizon_gamble_below_breakeven, late_accusation_v_drain` |
| `v1.4_gemini_opencode` | hard | 11 | 21 (9) | None | 0.00 (0.62) | n/a vs 0.847 | 0 (0 / 0) | e32 (14) | 0 (max=4, k=7) | `horizon_abstention, zero_surfaced_canaries` |
| `v1.4_gemini_opencode` | hard | 15 | 12 (9) | e34 | -1.00 (-1.00) | 0.805 vs 0.609 | 2 (2 / 0) | e39 (13) | 3 (max=3, k=2) | `fp95_single_separating_canary, non_decoy_framed_log_tiebreak` |
| `v1.4_gemini_opencode` | hard | 18 | 18 (13) | e29 | -1.00 (0.52) | 0.627 vs 0.684 | 1 (1 / 0) | e33 (13) | 6 (max=6, k=4) | `fp95_single_canary_hit, non_decoy_framed_log_tiebreak, midgame_gamble_below_breakeven` |
| `v1.4_gemini_opencode` | hard | 23 | 21 (18) | e29 | 0.23 (0.32) | 0.452 vs 0.812 | 1 (1 / 0) | e26 (21) | 6 (max=6, k=3) | `lucky_horizon_gamble_below_breakeven, late_accusation_v_drain` |
| `v1.4_gemini_opencode` | hard | 26 | 10 (7) | e04 | -1.00 (0.69) | 0.950 vs 0.617 | 2 (2 / 1) | e38 (12) | 3 (max=3, k=1) | `fp95_single_separating_canary` |
| `v1.4_gemini_opencode` | medium | 7 | 14 (7) | e09 | 0.50 (0.82) | 0.627 vs 0.662 | 1 (1 / 0) | e03 (14) | 1 (max=1, k=2) | `lucky_horizon_gamble_below_breakeven` |
| `v1.4_gemini_opencode` | medium | 29 | 14 (14) | e00 | 0.47 (0.00) | 0.558 vs 0.676 | 1 (1 / 0) | e05 (6) | 3 (max=3, k=2) | `lucky_horizon_gamble_below_breakeven` |
| `v1.4_gemini_inproc` | hard | 2 | 17 (9) | e25 | 0.31 (0.58) | 0.979 vs 0.763 | 2 (2 / 1) | e31 (21) | 2 (max=2, k=1) | `late_accusation_v_drain` |
| `v1.4_gemini_inproc` | hard | 5 | 21 (9) | e27 | 0.10 (0.52) | 0.901 vs 0.951 | 2 (1 / 0) | e04 (28) | 5 (max=0, k=0) | `lucky_horizon_gamble_below_breakeven, late_accusation_v_drain` |
| `v1.4_gemini_inproc` | hard | 6 | 15 (6) | e18 | -1.00 (0.71) | 0.629 vs 0.666 | 1 (1 / 0) | e20 (17) | 6 (max=6, k=3) | `fp95_single_canary_hit, non_decoy_framed_log_tiebreak, midgame_gamble_below_breakeven` |
| `v1.4_gemini_inproc` | hard | 21 | 15 (9) | e14 | 0.31 (0.73) | 0.890 vs 0.735 | 2 (2 / 1) | e31 (20) | 4 (max=4, k=1) | `late_accusation_v_drain` |
| `v1.4_gemini_inproc` | hard | 22 | 17 (15) | e36 | 0.50 (0.40) | 0.560 vs 0.689 | 2 (2 / 0) | e26 (12) | 3 (max=3, k=2) | `lucky_midgame_gamble_below_breakeven` |
| `v1.4_gemini_inproc` | hard | 26 | 21 (7) | None | 0.00 (0.69) | n/a vs 0.709 | 1 (0 / 0) | e38 (16) | 0 (max=5, k=3) | `horizon_abstention` |
| `v1.4_gemini_inproc` | medium | 2 | 8 (5) | e09 | 0.80 (0.80) | 0.514 vs 0.565 | 1 (1 / 0) | e05 (10) | 1 (max=1, k=2) | `lucky_midgame_gamble_below_breakeven` |
| `v1.4_gemini_inproc` | medium | 3 | 14 (9) | None | 0.00 (0.60) | n/a vs 0.714 | 0 (0 / 0) | e13 (15) | 0 (max=2, k=5) | `horizon_abstention, zero_surfaced_canaries` |
| `v1.4_gemini_inproc` | medium | 7 | 14 (7) | None | 0.00 (0.82) | n/a vs 0.621 | 0 (0 / 0) | e03 (12) | 0 (max=3, k=7) | `horizon_abstention, zero_surfaced_canaries` |
| `v1.4_gemini_inproc` | medium | 8 | 14 (5) | None | 0.00 (0.88) | n/a vs 0.571 | 0 (0 / 0) | e01 (16) | 0 (max=3, k=3) | `horizon_abstention, zero_surfaced_canaries` |
| `v1.4_gemini_inproc` | medium | 11 | 14 (5) | e07 | 0.52 (0.84) | 0.426 vs 0.654 | 1 (1 / 0) | e06 (13) | 1 (max=4, k=2) | `lucky_horizon_gamble_below_breakeven` |
| `v1.4_gemini_inproc` | medium | 12 | 14 (10) | None | 0.00 (0.67) | n/a vs 0.637 | 1 (0 / 0) | e09 (5) | 0 (max=4, k=2) | `horizon_abstention` |
| `v1.4_gemini_inproc` | medium | 18 | 14 (6) | e10 | -1.00 (0.75) | 0.554 vs 0.658 | 1 (1 / 0) | e06 (5) | 1 (max=3, k=2) | `horizon_gamble_below_breakeven` |
| `v1.4_opencode_gpt55` | hard | 0 | 8 (9) | None | 0.00 (0.64) | n/a vs 0.602 | 3 (0 / 0) | e14 (3) | 0 (max=2, k=1) | `uncalled_accuse_exit` |
| `v1.4_opencode_gpt55` | hard | 5 | 14 (9) | e27 | 0.41 (0.52) | 0.664 vs 0.684 | 1 (1 / 0) | e04 (23) | 5 (max=5, k=4) | `lucky_midgame_gamble_below_breakeven, late_accusation_v_drain` |
| `v1.4_opencode_gpt55` | hard | 17 | 9 (5) | None | 0.00 (0.77) | n/a vs 0.609 | 1 (0 / 0) | e29 (8) | 0 (max=1, k=1) | `uncalled_accuse_exit` |
| `v1.4_opencode_gpt55` | hard | 19 | 14 (9) | e09 | 0.28 (0.67) | 0.932 vs 0.751 | 2 (2 / 1) | e32 (12) | 3 (max=3, k=1) | `late_accusation_v_drain` |
| `v1.4_opencode_gpt55` | hard | 22 | 12 (15) | e36 | 0.33 (0.40) | 0.981 vs 0.751 | 2 (2 / 1) | e26 (12) | 1 (max=1, k=1) | `late_accusation_v_drain` |
| `v1.3_codex_gpt55` | hard | 3 | 12 (13) | e26 | 0.77 (0.67) | 0.449 vs 0.565 | 1 (1 / 0) | e08 (10) | 3 (max=3, k=4) | `lucky_midgame_gamble_below_breakeven` |
| `v1.3_codex_gpt55` | hard | 8 | 11 (13) | e13 | 0.76 (0.56) | 0.408 vs 0.557 | 0 (0 / 0) | e20 (5) | 5 (max=5, k=6) | `lucky_midgame_gamble_below_breakeven` |
| `v1.3_codex_gpt55` | medium | 0 | 6 (7) | e02 | -1.00 (0.74) | 0.183 vs 0.543 | 0 (0 / 0) | e19 (4) | 5 (max=5, k=7) | `non_decoy_framed_log_tiebreak, midgame_gamble_below_breakeven` |
| `v1.3_codex_gpt55` | medium | 3 | 14 (9) | e14 | 0.44 (0.60) | 0.525 vs 0.671 | 1 (1 / 0) | e13 (18) | 0 (max=2, k=2) | `lucky_horizon_gamble_below_breakeven, late_accusation_v_drain` |
| `v1.3_codex_gpt55` | medium | 4 | 14 (8) | e07 | -1.00 (0.69) | 0.330 vs 0.654 | 0 (0 / 0) | e03 (5) | 4 (max=4, k=4) | `non_decoy_framed_log_tiebreak, horizon_gamble_below_breakeven` |
| `v1.3_codex_gpt55` | medium | 5 | 14 (6) | e14 | 0.59 (0.79) | 0.410 vs 0.625 | 0 (0 / 0) | e09 (8) | 6 (max=8, k=4) | `lucky_horizon_gamble_below_breakeven` |
| `v1.3_codex_gpt55` | medium | 7 | 9 (7) | e09 | 0.65 (0.82) | 0.461 vs 0.602 | 2 (2 / 1) | e03 (8) | 1 (max=1, k=1) | `lucky_midgame_gamble_below_breakeven` |
| `v1.3_inproc_gpt55` | hard | 2 | 13 (14) | e19 | 0.64 (0.66) | 0.169 vs 0.611 | 3 (3 / 0) | e27 (0) | 6 (max=6, k=2) | `lucky_midgame_gamble_below_breakeven` |
| `v1.3_inproc_gpt55` | hard | 3 | 14 (13) | e18 | -1.00 (0.67) | 0.579 vs 0.639 | 1 (1 / 0) | e08 (11) | 2 (max=2, k=4) | `fp95_single_canary_hit, horizon_gamble_below_breakeven` |
| `v1.3_inproc_gpt55` | hard | 4 | 14 (14) | e26 | -1.00 (0.69) | 0.498 vs 0.639 | 1 (1 / 0) | e08 (0) | 2 (max=3, k=3) | `fp95_single_canary_hit, horizon_gamble_below_breakeven` |
| `v1.3_inproc_gpt55` | medium | 4 | 14 (8) | e17 | 0.46 (0.69) | 0.522 vs 0.699 | 0 (0 / 0) | e03 (0) | 5 (max=6, k=4) | `lucky_horizon_gamble_below_breakeven` |

## 5. Mapping Empirical Weaknesses to Fair `MoleView` / `MoleStrategy` Levers

Every lever below uses only public-free, non-omniscient `MoleView` features from `canary.mole.dsl` (the mole never knows which document is a canary or who the investigator suspects) and validates cleanly through `MoleStrategy.from_json` while keeping the reference `SolverPolicy` above the 0.85 catchability gate.

### 5.1 Lever `low_recipient_surgical_shield`
- **`MoleView` features**: `recent_low_recipient_docs`, `min_recipient_count`
- **`MoleStrategy` selectors**: `leak=most_recipients`, `frame=random_peer`
- **Empirical target**: Codex and GPT-5.5 rely heavily on <=3-recipient surgical traps (30.6%-75.3% of planted canaries) to isolate 1-3 suspects.
- **Measured transcript anchors**: `v14_opencode_gpt55_hard_le3_share=0.471`, `codex_medium_le3_share=0.753`, `codex_hard_le3_share=0.306`, `gpt55_medium_le3_share=0.734`, `gpt55_hard_le3_share=0.435`, `gemini_opencode_hard_le3_share=0.0`
- **Why `SolverPolicy` stays unbeaten**: Solver adapts with wider coverage fractions (0.40-1.00) and canary_shy() full-staff padding when >=3 regular leaks surface without a canary hit.
- **Validated Mole DSL rule snippet**:
```json
{
  "name": "surgical_trap_shield",
  "rules": [
    {
      "if": [
        [
          "recent_low_recipient_docs",
          ">=",
          1
        ]
      ],
      "then": {
        "leak": "most_recipients",
        "frame": "random_peer"
      }
    }
  ],
  "default": {
    "leak": "random_seeded",
    "frame": "random_peer"
  }
}
```

### 5.2 Lever `midsize_canary_evasion`
- **`MoleView` features**: `day`, `min_recipient_count`, `max_recipient_count`, `n_leakable`
- **`MoleStrategy` selectors**: `leak=most_recipients`, `frame=random_peer`
- **Empirical target**: Gemini-4-carbon almost never plants <=3-recipient canaries (0.0%-0.6%), concentrating 43.6%-73.6% of canaries in 4-8 recipients (3 variants of 2-3 staff) and failing on 0-canary-hit seeds.
- **Measured transcript anchors**: `gemini_opencode_hard_4_to_8_share=0.496`, `gemini_inproc_hard_4_to_8_share=0.436`, `gemini_inproc_medium_4_to_8_share=0.736`, `gemini_inproc_medium_zero_surfaced_eps=4`, `gemini_opencode_hard_3var_share=1.0`
- **Why `SolverPolicy` stays unbeaten**: Regular leaks still narrow department intersections deterministically, and Solver's wide balanced partitions (>=9 recipients) plus midgame sampling identify the mole above 0.85 accuracy.
- **Validated Mole DSL rule snippet**:
```json
{
  "name": "wide_crowd_preference",
  "rules": [
    {
      "if": [
        [
          "day",
          "<=",
          6
        ],
        [
          "min_recipient_count",
          "<=",
          8
        ],
        [
          "max_recipient_count",
          ">=",
          12
        ]
      ],
      "then": {
        "leak": "most_recipients",
        "frame": "random_peer"
      }
    }
  ],
  "default": {
    "leak": "random_seeded",
    "frame": "random_peer"
  }
}
```

### 5.3 Lever `reactive_canary_lag_oldest`
- **`MoleView` features**: `day`, `newest_doc_age_days`, `n_leakable`
- **`MoleStrategy` selectors**: `leak=oldest`, `frame=random_peer`
- **Empirical target**: Gemini delays first canary on Hard to day 3.03-3.40 (vs Solver day 1.00), plants reactive age-0 canaries after leaks surface, and accuses with <=1 separating canary under 0.95 fingerprint noise.
- **Measured transcript anchors**: `gemini_opencode_hard_first_canary_day=3.03`, `gemini_inproc_hard_first_canary_day=3.4`, `solver_hard_first_canary_day=1.0`, `gemini_opencode_hard_fp95_single_sep_wrong=4`, `gemini_inproc_hard_fp95_single_sep_wrong=1`
- **Why `SolverPolicy` stays unbeaten**: Solver plants 2 canaries/day starting day 1.00 (14.13 canaries/episode on Hard), so its day d-2 canaries already occupy the oldest leak-window slot.
- **Validated Mole DSL rule snippet**:
```json
{
  "name": "reactive_canary_lag",
  "rules": [
    {
      "if": [
        [
          "day",
          "<=",
          8
        ],
        [
          "newest_doc_age_days",
          "==",
          0
        ],
        [
          "n_leakable",
          ">=",
          2
        ]
      ],
      "then": {
        "leak": "oldest",
        "frame": "random_peer"
      }
    }
  ],
  "default": {
    "leak": "random_seeded",
    "frame": "random_peer"
  }
}
```

### 5.4 Lever `non_decoy_peer_framing`
- **`MoleView` features**: `n_restricted_colleagues`, `i_am_restricted`
- **`MoleStrategy` selectors**: `leak=random_seeded`, `frame=most_restricted_peer`
- **Empirical target**: Frontier models dismissed the angry decoy in 100.0% of 189 episodes (0 decoy accusations), but non-decoy framed after-hours logs broke 0-separation canary ties into -1.0 wrong accusations (5/10 wrong accusations).
- **Measured transcript anchors**: `frontier_decoy_dismissal_rate=1.0`, `frontier_decoy_accused_total=0`, `wrong_non_decoy_framed_tiebreak=5`, `wrong_with_zero_separating_canary=8`, `gemini_opencode_hard_log_calls=12.27`
- **Why `SolverPolicy` stays unbeaten**: Solver marginalises Poisson framing across peers with behaviour_temper=0.6, preventing single-employee after-hours spikes from overriding primary leak/canary likelihoods.
- **Validated Mole DSL rule snippet**:
```json
{
  "name": "non_decoy_tiebreak_framing",
  "rules": [
    {
      "if": [
        [
          "n_restricted_colleagues",
          ">=",
          1
        ]
      ],
      "then": {
        "leak": "random_seeded",
        "frame": "most_restricted_peer"
      }
    }
  ],
  "default": {
    "leak": "random_seeded",
    "frame": "random_peer"
  }
}
```

### 5.5 Lever `early_burst_midgame_quiet_pacing`
- **`MoleView` features**: `day`, `days_since_last_leak`
- **`MoleStrategy` selectors**: `leak=none`, `frame=random_peer`
- **Empirical target**: Gemini spends 64.4%-68.0% of Hard investigative calls on low-LR interviews (57.27-68.03/episode), starts canaries late, lags Solver by +1.97 to +2.52 days, and makes 13 horizon gambles below 1/(1+V).
- **Measured transcript anchors**: `gemini_opencode_hard_interviews=68.03`, `gemini_inproc_hard_interviews=57.27`, `gemini_opencode_hard_day_lag=2.52`, `gemini_opencode_hard_leak_v_drain=0.37`, `frontier_below_breakeven_gambles_total=23`, `frontier_horizon_gambles_total=13`
- **Why `SolverPolicy` stays unbeaten**: Leaks on days 1-3 hit Solver's day-1 pipelined canaries immediately, and bounded midgame pacing preserves leak volume over 21 days so Solver exceeds the 0.85 catchability bar.
- **Validated Mole DSL rule snippet**:
```json
{
  "name": "early_burst_then_paced",
  "rules": [
    {
      "if": [
        [
          "day",
          "<=",
          3
        ]
      ],
      "then": {
        "leak": "most_recipients",
        "frame": "random_peer"
      }
    },
    {
      "if": [
        [
          "day",
          ">=",
          4
        ],
        [
          "day",
          "<=",
          9
        ],
        [
          "days_since_last_leak",
          "<",
          2
        ]
      ],
      "then": {
        "leak": "none",
        "frame": "random_peer"
      }
    }
  ],
  "default": {
    "leak": "random_seeded",
    "frame": "random_peer"
  }
}
```
