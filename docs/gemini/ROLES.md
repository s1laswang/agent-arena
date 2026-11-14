# Canary x Gemini: Six Verified `gemini-4-carbon` Roles

Canary is a Bayesian insider-threat RL benchmark where a security-lead agent investigates a simulated company bleeding value to a mole. Across the merged Canary repository, `gemini-4-carbon` is integrated into six distinct, load-bearing roles: synthesizing leak-free company worlds (`world_text`), playing and evolving catchable adversaries (`adaptive_mole`), acting as the frontier security investigator (`investigators`), diagnosing multi-episode failure modes in long context (`failure_analyst`), red-teaming the reward and MCP server (`exploit_hunter`), and reading pixel-only evidence scans and forensic rasters (`multimodal_evidence`).

Every metric in this document is extracted from committed `gemini-4-carbon` run folders audited by `canary.gemini.provenance` at repository commit `a37d93f7`.

## Provenance & Aggregate Ledger Summary

- Provenance status: **VERIFIED** (`python -m canary.gemini.provenance --root . --strict`)
- Target model: `gemini-4-carbon`
- Verified roles: **6 / 6** (`world_text`, `adaptive_mole`, `investigators`, `failure_analyst`, `exploit_hunter`, `multimodal_evidence`)
- Verified `gemini-4-carbon` run folders: **37** (6 canonical headline runs + 31 supporting runs)
- Total verified episodes and evaluated samples: **250**
- Total Gemini API calls: **3,646**
- Total tokens (input / output / thinking / cached): **109,922,597 / 1,333,147 / 455,402 / 100,053,083**
- Total estimated API cost (USD): **$45.6225**
- Secret leaks detected: **0**

| Role | Stage | Verified Runs | Episodes / Samples | API Calls | Tokens In | Tokens Out | Thinking Tokens | Cached Tokens | Cost (USD) |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `world_text` | Company Construction | 4 | 28 | 437 | 12,835,770 | 229,583 | 213,774 | 11,793,550 | $5.8390 |
| `adaptive_mole` | Adversarial Evolution | 7 | 44 | 281 | 1,968,136 | 19,724 | 45,191 | 1,618,805 | $1.5097 |
| `investigators` | Bayesian Investigation | 18 | 31 | 2,682 | 91,649,872 | 1,018,064 | 157,797 | 84,897,753 | $33.7526 |
| `failure_analyst` | Trajectory Forensics | 2 | 121 | 3 | 321,168 | 23,013 | 25,669 | 0 | $0.9803 |
| `exploit_hunter` | Reward & Protocol Red-Team | 2 | 11 | 215 | 3,093,922 | 36,831 | 0 | 1,742,975 | $3.2445 |
| `multimodal_evidence` | Pixel & Chart Inspection | 4 | 15 | 28 | 53,729 | 5,932 | 12,971 | 0 | $0.2965 |
| **Total** | **All 6 Roles** | **37** | **250** | **3,646** | **109,922,597** | **1,333,147** | **455,402** | **100,053,083** | **$45.6225** |

## Canonical Headline Runs (One Labelled Real Run per Role)

| Role | Subrole | Run Folder | Model ID | Commit | Count | Calls | Tokens In | Tokens Out | Thinking | Cached | Cost (USD) | Verified Headline Result |
| --- | --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `world_text` | `biased_chatter_investigator_ablation` | `results/gemini_roles/world_text/biased-chatter-ablation-carbon` | `gemini-4-carbon` | `f307290845c4a0040feebf4e146d2ec3aa1596c7` | 12 | 399 | 12,766,963 | 208,617 | 184,085 | 11,793,550 | $5.2124 | 12 paired episodes; carbon +0.705 (biased) vs +0.640 (template), SolverPolicy +0.765 on both, ObviousHeuristic -1.000 |
| `adaptive_mole` | `paired_skill_designer` | `results/gemini_roles/adaptive_mole/paired-solvable-scenarios-carbon` | `gemini-4-carbon` | `16f24a08e1fb57397ddf90a5b413b4359a5f16bc` | 20 | 1 | 1,649 | 957 | 476 | 0 | $0.0176 | Kept 3/4 solvable scenarios; held-out n=20 SolverPolicy +0.722 (100% acc) vs heuristic -0.811 (10% acc) |
| `investigators` | `thinking_level_ablation` | `results/gemini_roles/investigators/thinking-ladder-carbon-med01` | `gemini-4-carbon` | `2cb207f51c44d3069e2101c4849a21965b606f92` | 4 | 318 | 9,240,098 | 10,672 | 104,829 | 8,471,482 | $3.5394 | Paired low vs high thinking (134 vs 52,281 think tok/ep): both +0.655 (115.9% of solver +0.565), regret 0.046 -> 0.028 |
| `failure_analyst` | `carbon-longctx-corpus` | `results/gemini_roles/failure_analyst/carbon-longctx-corpus` | `gemini-4-carbon` | `71a425530574aecd282e53a13f022be25fe4f292` | 101 | 2 | 237,763 | 16,390 | 14,887 | 0 | $0.6394 | 101 frontier episodes packed in 237,763 tokens; 6 regret-linked failure clusters; 16/16 (100.0%) quotes verified verbatim |
| `exploit_hunter` | `blackbox_mcp_swarm` | `results/gemini_roles/exploit_hunter/blackbox-swarm-carbon` | `gemini-4-carbon` | `361fbab16b9c1016f72480d4550bb200dc7f5d60` | 6 | 123 | 1,233,925 | 15,840 | 0 | 961,896 | $0.7986 | 6 blackbox MCP and in-process attacks (363 tool calls): 0 verified exploits, 0 invariant violations |
| `multimodal_evidence` | `visual_memo_blind_ablation` | `results/gemini_roles/multimodal_evidence/memo-watermark-ablation-carbon` | `gemini-4-carbon` | `8df685ee057904bac413d35304f389066aa2b78f` | 3 | 16 | 30,464 | 2,085 | 1,367 | 0 | $0.0954 | 16 leaked-memo PNG scans read via `Part.from_bytes`: 100.0% copy-code accuracy, +0.6933 vs +0.0000 blind (100.0% oracle recovery) |

---

## Role-by-Role Architecture, Capabilities, and Verified Run Tables

### Role 01: `world_text` - World Text & Persona Synthesis

- **Gemini API capabilities:** Structured JSON output (`response_schema`), strict public-facts-only prompt isolation (zero access to `mole`, `decoy`, or private HMAC `world_seed`), deterministic disk caching, and mid-episode narrative synthesis.
- **Why it is essential:** Without `gemini-4-carbon` generating realistic workplace personas, department cultures, office grudges, rumor mill chatter, and dynamic mid-episode incidents, Canary worlds collapse to predictable string templates. Crucially, the generator receives only public company facts, ensuring zero ground-truth mole leakage while creating realistic social noise that breaks naive sentiment heuristics (`ObviousHeuristic` scores `-1.000` while `SolverPolicy` maintains `+0.765` parity).

| Subrole | Run Folder | Model ID | Commit | Count | Calls | Tokens In | Tokens Out | Thinking | Cached | Cost (USD) | Verified Result |
| --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `biased_chatter_investigator_ablation` | `results/gemini_roles/world_text/biased-chatter-ablation-carbon` | `gemini-4-carbon` | `f307290845c4a0040feebf4e146d2ec3aa1596c7` | 12 | 399 | 12,766,963 | 208,617 | 184,085 | 11,793,550 | $5.2124 | 12 paired episodes on v1.4 medium seeds 10,11: carbon +0.705 (biased) vs +0.640 (template), SolverPolicy +0.765 on both |
| `company_personas_chatter` | `results/gemini_roles/world_text/carbon-v14-seeds012` | `gemini-4-carbon` | `c82f27a73762a413c20ace1b3b0dd7b4bf02ef4a` | 5 | 27 | 35,047 | 15,028 | 21,899 | 0 | $0.4394 | 5 v1.4 worlds (140 employee personas), 0 ground-truth leaks, 0 lint errors, SolverPolicy +0.654 |
| `dynamic_mid_episode_events` | `results/gemini_roles/world_text/dynamic-events-carbon` | `gemini-4-carbon` | `361fbab16b9c1016f72480d4550bb200dc7f5d60` | 9 | 9 | 30,331 | 3,204 | 6,034 | 0 | $0.1530 | 9 dynamic mid-episode incidents across 3 seeds, 0 truth leaks, SolverPolicy +0.693 vs base +0.693 |
| `biased_chatter` | `results/gemini_roles/world_text/biased-chatter-carbon` | `gemini-4-carbon` | `12e5ab3e814e10db747eb8c489efcef73e54391e` | 2 | 2 | 3,429 | 2,734 | 1,756 | 0 | $0.0342 | 10 biased workplace messages across 2 seeds, 0 truth leaks, 0 lint errors |

### Role 02: `adaptive_mole` - Adaptive Mole, Mole Forge & PAIRED Scenario Designer

- **Gemini API capabilities:** Structured JSON rule-DSL mutation and crossover (Mole Forge), PAIRED-style scenario parameter + DSL co-design under a dual solvability constraint, and live day-by-day adversarial mole play (`mole_arena.py`) against both `SolverPolicy` and `gemini-4-carbon` investigators.
- **Why it is essential:** Static scripted moles are easy to overfit. `gemini-4-carbon` acts both offline (evolving mole DSL rules and tier knobs kept only when `SolverPolicy >= X` and `ObviousHeuristic <= Y`) and live in-episode (choosing daily document leaks above recipient thresholds and rotating framed scapegoats). On `v1.4` `hard` seeds `0..2`, the live `gemini-4-carbon` mole drives `SolverPolicy` score down from `+0.6200` to `+0.4600` (`-0.1600`) and `grok_tactics` from `+0.5967` to `+0.0000` (`0%` accuracy) while remaining `100%` solvable by the Bayesian reference (`3/3` caught).

| Subrole | Run Folder | Model ID | Commit | Count | Calls | Tokens In | Tokens Out | Thinking | Cached | Cost (USD) | Verified Result |
| --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `paired_skill_designer` | `results/gemini_roles/adaptive_mole/paired-solvable-scenarios-carbon` | `gemini-4-carbon` | `16f24a08e1fb57397ddf90a5b413b4359a5f16bc` | 20 | 1 | 1,649 | 957 | 476 | 0 | $0.0176 | Kept 3/4 solvable proposals (`high_tempo_frame_rotator`); fresh seeds 5100..5119 (n=20): solver +0.722 vs heuristic -0.811 |
| `live_arena_mole_hard` | `results/gemini_roles/adaptive_mole/arena-live-carbon-hard012` | `gemini-4-carbon` | `03c676c1d3cd42629994ac434c056758a75148e0` | 3 | 97 | 86,618 | 6,331 | 6,287 | 0 | $0.2994 | 97 live mole decisions on hard 0..2: solver +0.4600 (100% acc) vs +0.6200 default; grok_tactics +0.5967 -> +0.0000 |
| `live_arena_mole` | `results/gemini_roles/adaptive_mole/arena-live-carbon-med012` | `gemini-4-carbon` | `d39e88c39e8a3859e88805cd8a30156a8cfcaa49` | 3 | 77 | 61,299 | 4,959 | 5,588 | 0 | $0.2281 | 77 live mole decisions on medium 0..2: solver +0.4233 vs +0.7333 default |
| `carbon_vs_carbon_clash` | `results/gemini_roles/adaptive_mole/carbon-vs-carbon-seed0` | `gemini-4-carbon` | `3bd1d1e2295aa320812f08e2eceaef5b4a8902ef` | 2 | 92 | 1,812,239 | 3,638 | 30,311 | 1,618,805 | $0.8882 | Head-to-head `gemini-4-carbon` investigator (+0.660) vs live `gemini-4-carbon` mole (paired solver +0.400) |
| `mole_forge` | `results/gemini_roles/adaptive_mole/mole-forge-carbon-v14` | `gemini-4-carbon` | `99767a5d144e89cbd9522ddd9720af55bb2217eb` | 6 | 12 | 2,546 | 1,060 | 1,180 | 0 | $0.0275 | Evolutionary JSON DSL search on v1.4: fitness 0.370 with 95% SolverPolicy catchability |
| `paired_designer` | `results/gemini_roles/adaptive_mole/paired-designer-carbon-hard` | `gemini-4-carbon` | `9222669912afd57e53fbd3b07f0cdba985df705d` | 6 | 1 | 1,889 | 1,659 | 669 | 0 | $0.0271 | Kept 6/6 solvable hard scenarios on seeds 0..9 (top regret +1.7180, solver +0.7180 vs heuristic -1.0000) |
| `paired_designer` | `results/gemini_roles/adaptive_mole/paired-designer-carbon` | `gemini-4-carbon` | `370de43c38b321bf9dbc5c04220abd90c4614466` | 4 | 1 | 1,896 | 1,120 | 680 | 0 | $0.0218 | Kept 3/4 solvable medium scenarios under SolverPolicy >= X and ObviousHeuristic <= Y gate |

### Role 03: `investigators` - Security-Lead Frontier Investigators & Thinking Ladder

- **Gemini API capabilities:** Multi-turn function calling over 13 investigative tools (`plant_canary`, `check_leak_feed`, `read_access_logs`, `search_messages`, `read_message`, `interview`, `restrict_access`, `accuse`, `advance_day`, etc.), explicit `thinking_level` control (`low` vs `high`), thought-signature preservation across tool turns, and prefix context caching (`84,897,753` cached input tokens across `2,682` calls).
- **Why it is essential:** `gemini-4-carbon` is the frontier subject under test across `easy`, `medium`, and `hard` `v1.4` worlds, establishing both strong investigative competence (`87%` overall mole-identification accuracy across 23 paired `v1.4` episodes) and a real reasoning gap on `hard` (`+0.4267` vs `SolverPolicy` `+0.5611`, `76.0%` of reference). Explicit Gemini thinking budgets (`low` vs `high` on identical model weights and seeds) isolate where extra reasoning helps: on `hard` seed `0`, `high` thinking (`52,968` thinking tokens) cuts step-level Bayesian solver regret from `0.1623` to `0.0298` and improves canary posterior entropy from `1.1776` bits to `1.5038` bits (`SolverPolicy` `1.5335` bits), while revealing over-conservative commit timing (day `13` at `P=0.9984` vs `low` day `7` at `P=0.9513`).

| Subrole | Run Folder | Model ID | Commit | Count | Calls | Tokens In | Tokens Out | Thinking | Cached | Cost (USD) | Verified Result |
| --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `thinking_level_ablation` | `results/gemini_roles/investigators/thinking-ladder-carbon-med01` | `gemini-4-carbon` | `2cb207f51c44d3069e2101c4849a21965b606f92` | 4 | 318 | 9,240,098 | 10,672 | 104,829 | 8,471,482 | $3.5394 | Medium seeds 0,1: low (+0.655, 134 think tok/ep) vs high (+0.655, 52,281 think tok/ep), solver +0.565, regret 0.046 -> 0.028 |
| `hard_thinking_ablation` | `results/gemini_roles/investigators/thinking-ladder-carbon-hard0` | `gemini-4-carbon` | `3df4d2b65bd05a67f2d94ef18d967da05c0e90d7` | 2 | 163 | 6,499,263 | 5,422 | 52,968 | 6,101,700 | $1.9892 | Hard seed 0: low +0.780 (0 think tok, regret 0.1623) vs high +0.360 (52,968 think tok, regret 0.0298), solver +0.640 |
| `hint_ablation` | `results/gemini_roles/investigators/hint-ablation-carbon-med01` | `gemini-4-carbon` | `361fbab16b9c1016f72480d4550bb200dc7f5d60` | 2 | 173 | 4,829,333 | 70,201 | 0 | 4,413,503 | $1.9750 | Causal EV-delay hint ablation on medium seeds 0,1: mean +0.630 vs solver +0.565 (100% acc) |
| `easy-0-3` | `data/runs/committed/v1.4/gemini-4-carbon/easy-0-3` | `gemini-4-carbon` | `361fbab16b9c1016f72480d4550bb200dc7f5d60` | 4 | 133 | 1,557,467 | 50,927 | 0 | 1,235,555 | $1.2767 | Mean +0.8500 vs solver +0.8000 (100% acc, n=4) |
| `medium-0-1` | `data/runs/committed/v1.4/gemini-4-carbon/medium-0-1` | `gemini-4-carbon` | `361fbab16b9c1016f72480d4550bb200dc7f5d60` | 2 | 163 | 4,658,670 | 71,772 | 0 | 4,257,294 | $1.9462 | Mean +0.7000 vs solver +0.5650 (100% acc, n=2) |
| `medium-2-3` | `data/runs/committed/v1.4/gemini-4-carbon/medium-2-3` | `gemini-4-carbon` | `361fbab16b9c1016f72480d4550bb200dc7f5d60` | 2 | 125 | 2,625,822 | 58,964 | 0 | 2,314,808 | $1.4431 | Mean +0.8000 vs solver +0.7000 (100% acc, n=2) |
| `medium-4-5` | `data/runs/committed/v1.4/gemini-4-carbon/medium-4-5` | `gemini-4-carbon` | `361fbab16b9c1016f72480d4550bb200dc7f5d60` | 2 | 278 | 9,686,117 | 95,196 | 0 | 9,032,227 | $3.1630 | Mean +0.2550 vs solver +0.7400 (50% acc, n=2) |
| `medium-6-7` | `data/runs/committed/v1.4/gemini-4-carbon/medium-6-7` | `gemini-4-carbon` | `361fbab16b9c1016f72480d4550bb200dc7f5d60` | 2 | 218 | 7,742,118 | 98,798 | 0 | 7,222,312 | $2.7498 | Mean +0.3700 vs solver +0.8050 (50% acc, n=2) |
| `medium-8-9` | `data/runs/committed/v1.4/gemini-4-carbon/medium-8-9` | `gemini-4-carbon` | `361fbab16b9c1016f72480d4550bb200dc7f5d60` | 2 | 191 | 5,767,066 | 83,656 | 0 | 5,308,215 | $2.2851 | Mean +0.7600 vs solver +0.8400 (100% acc, n=2) |
| `hard-0` | `data/runs/committed/v1.4/gemini-4-carbon/hard-0` | `gemini-4-carbon` | `361fbab16b9c1016f72480d4550bb200dc7f5d60` | 1 | 112 | 4,362,422 | 44,812 | 0 | 4,090,963 | $1.4001 | Score +0.5300 vs solver +0.6400 (correct, day 11 vs 9) |
| `hard-1` | `data/runs/committed/v1.4/gemini-4-carbon/hard-1` | `gemini-4-carbon` | `361fbab16b9c1016f72480d4550bb200dc7f5d60` | 1 | 117 | 4,296,964 | 48,641 | 0 | 3,971,769 | $1.5340 | Score +0.6200 vs solver +0.6900 (correct, day 13 vs 7) |
| `hard-2` | `data/runs/committed/v1.4/gemini-4-carbon/hard-2` | `gemini-4-carbon` | `4c1ff4742438281a453c5ec353a1468fbe7933f4` | 1 | 76 | 2,018,060 | 30,619 | 0 | 1,796,222 | $0.9295 | Score +0.5900 vs solver +0.5800 (correct, day 8 vs 9) |
| `hard-3` | `data/runs/committed/v1.4/gemini-4-carbon/hard-3` | `gemini-4-carbon` | `361fbab16b9c1016f72480d4550bb200dc7f5d60` | 1 | 128 | 6,813,652 | 66,707 | 0 | 6,448,448 | $2.0423 | Score +0.6200 vs solver +0.2800 (correct, day 13 vs 18) |
| `hard-4` | `data/runs/committed/v1.4/gemini-4-carbon/hard-4` | `gemini-4-carbon` | `361fbab16b9c1016f72480d4550bb200dc7f5d60` | 1 | 150 | 7,623,574 | 66,088 | 0 | 7,262,745 | $2.1088 | Score +0.5500 vs solver +0.7300 (correct, day 15 vs 5) |
| `hard-5` | `data/runs/committed/v1.4/gemini-4-carbon/hard-5` | `gemini-4-carbon` | `361fbab16b9c1016f72480d4550bb200dc7f5d60` | 1 | 67 | 2,500,684 | 47,823 | 0 | 2,263,660 | $1.1786 | Score +0.5900 vs solver +0.5200 (correct, day 8 vs 9) |
| `hard-6` | `data/runs/committed/v1.4/gemini-4-carbon/hard-6` | `gemini-4-carbon` | `361fbab16b9c1016f72480d4550bb200dc7f5d60` | 1 | 57 | 2,144,797 | 51,865 | 0 | 1,985,523 | $1.0357 | Score -1.0000 vs solver +0.7100 (wrong accusation on day 10 vs 6) |
| `hard-7` | `data/runs/committed/v1.4/gemini-4-carbon/hard-7` | `gemini-4-carbon` | `361fbab16b9c1016f72480d4550bb200dc7f5d60` | 1 | 117 | 5,726,242 | 69,668 | 0 | 5,437,640 | $1.8176 | Score +0.7100 vs solver +0.6400 (correct, day 13 vs 9) |
| `hard-8` | `data/runs/committed/v1.4/gemini-4-carbon/hard-8` | `gemini-4-carbon` | `361fbab16b9c1016f72480d4550bb200dc7f5d60` | 1 | 96 | 3,557,523 | 46,233 | 0 | 3,283,687 | $1.3384 | Score +0.6300 vs solver +0.2600 (correct, day 11 vs 21) |

### Role 04: `failure_analyst` - Long-Context Failure Analyst & Calibration Forensics

- **Gemini API capabilities:** 1M-token long-context window ingesting 101 full multi-day agent trajectories (`237,763` prompt tokens, `261,087` chars) alongside deterministic Bayesian solver regret tags in a single context window, structured JSON clustering, and programmatic verbatim quote verification.
- **Why it is essential:** Chunked RAG cannot synthesize cross-episode failure taxonomies across 101 100-step tool transcripts at once. `gemini-4-carbon` reads the entire frontier trajectory corpus (`codex:gpt-5.5`, `openai:gpt-5.5`, `grok`, `opencode:openai/gpt-5.6-sol`), identifies 6 concrete failure modes led by `premature_accusation` (`9.6369` regret across `19/101` episodes), `uninformative_canary` (`30/101` episodes), and `budget_waste` (`45/101` episodes), and achieves `100.0%` (`16/16`) code-verified verbatim transcript quotes. A companion Bayesian calibration analyst run (`calibration-ev-carbon`) audits 101 calibrated episodes (`ECE = 0.081`) with `100.0%` verified quotes.

| Subrole | Run Folder | Model ID | Commit | Count | Calls | Tokens In | Tokens Out | Thinking | Cached | Cost (USD) | Verified Result |
| --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `carbon-longctx-corpus` | `results/gemini_roles/failure_analyst/carbon-longctx-corpus` | `gemini-4-carbon` | `71a425530574aecd282e53a13f022be25fe4f292` | 101 | 2 | 237,763 | 16,390 | 14,887 | 0 | $0.6394 | 101 episodes in 237,763 tokens; 6 failure clusters; 16/16 (100.0%) verbatim quotes verified in code |
| `bayesian_calibration_analyst` | `results/gemini_roles/failure_analyst/calibration-ev-carbon` | `gemini-4-carbon` | `fdf16a71b0395c788b33957e6a91a2589224f8df` | 20 | 1 | 83,405 | 6,623 | 10,782 | 0 | $0.3409 | 101 calibrated episodes analyzed (20 flagged cases), ECE 0.081, 100.0% verified quotes |

### Role 05: `exploit_hunter` - Whole-Repo Whitebox & Live MCP Exploit Hunter

- **Gemini API capabilities:** Whole-repository source packing (`104` files, `203,463` tokens cached across attacker personas), adversarial exploit planning (`reward_hacker`, `side_channel`, `protocol_fuzzer`, `text_leak`), and live function-calling execution against both in-process `Env` and the HTTP MCP server (`canary.mcp_server`).
- **Why it is essential:** Judge-proof RL benchmarks require automated adversarial auditing over the actual source code and protocol boundary. Five whitebox `gemini-4-carbon` attackers read the entire repository (`1,859,997` input tokens, `781,079` cached) and executed 292 tool calls probing `public_world_match` across 12,000+ seeds, `/ledger` token gating (`403 Forbidden`), format-string injection, and type boundaries; six blackbox MCP attackers (`1,233,925` input tokens, `961,896` cached, `363` tool calls) achieved `0` verified exploits and `0` invariant violations. In the whitebox run, only solver-grade detective play (`a000-reward_hacker-mcp`, score `+0.680` vs solver `+0.670` after `0` seed-leak matches) triggered the strict `score_at_solver_level_confirmed` audit flag, confirming zero reward shortcuts.

| Subrole | Run Folder | Model ID | Commit | Count | Calls | Tokens In | Tokens Out | Thinking | Cached | Cost (USD) | Verified Result |
| --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `blackbox_mcp_swarm` | `results/gemini_roles/exploit_hunter/blackbox-swarm-carbon` | `gemini-4-carbon` | `361fbab16b9c1016f72480d4550bb200dc7f5d60` | 6 | 123 | 1,233,925 | 15,840 | 0 | 961,896 | $0.7986 | 6 blackbox MCP + inproc attempts (363 tool calls): 0 verified exploits, 0 invariant violations, 6/6 ledger-verified |
| `whitebox_repo_swarm` | `results/gemini_roles/exploit_hunter/whitebox-swarm-carbon` | `gemini-4-carbon` | `361fbab16b9c1016f72480d4550bb200dc7f5d60` | 5 | 92 | 1,859,997 | 20,991 | 0 | 781,079 | $2.4459 | 5 whole-repo whitebox attempts (104 files, 203,463 tok pack, 292 tool calls): 0 seed leaks across 12k+ probes; 1 solver-level play flagged for audit |

### Role 06: `multimodal_evidence` - Pixel-Only Evidence Scans & Visual Forensics

- **Gemini API capabilities:** Native multimodal PNG ingestion via `google.genai.types.Part.from_bytes(mime_type="image/png")` combined with `thinking_level` visual reasoning and structured JSON extraction.
- **Why it is essential:** Real insider-threat evidence often arrives as scanned leak screenshots, multi-panel SOC access rasters, and belief-vs-value diagnostic plots where key signals exist only in pixels. When text `variant` fields are redacted from `check_leak_feed` (`memo-watermark-ablation-carbon`), a text-only blind investigator collapses to `+0.0000` (`0/3` accusations), whereas `gemini-4-carbon` reading the 16 rendered memo PNGs decodes `16/16` (`100.0%`) copy-codes and recovers `+0.6933` (`100.0%` of the unredacted Bayesian text oracle `+0.6933`). Across 6 SOC access-and-canary rasters (`medium` + `hard` seeds `0..2`), `gemini-4-carbon` identifies `6/6` (`100.0%`) true moles and `6/6` (`100.0%`) framed decoys where a naive after-hours log counter scores `0/6` (`0.0%`). Across 6 trajectory belief charts, `gemini-4-carbon` achieves `6/6` (`100.0%`) accuracy on EV-threshold violations, accusation day, and hidden bleed gaps.

| Subrole | Run Folder | Model ID | Commit | Count | Calls | Tokens In | Tokens Out | Thinking | Cached | Cost (USD) | Verified Result |
| --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `visual_memo_blind_ablation` | `results/gemini_roles/multimodal_evidence/memo-watermark-ablation-carbon` | `gemini-4-carbon` | `8df685ee057904bac413d35304f389066aa2b78f` | 3 | 16 | 30,464 | 2,085 | 1,367 | 0 | $0.0954 | 16 memo PNGs read: 16/16 (100.0%) watermark accuracy; multimodal +0.6933 vs blind +0.0000 (100.0% oracle recovery) |
| `soc_access_vision_hard` | `results/gemini_roles/multimodal_evidence/access-heatmap-hard-carbon` | `gemini-4-carbon` | `933f518381c9435fdef6f76c40bf64c5b78f7e42` | 3 | 3 | 6,453 | 1,497 | 6,248 | 0 | $0.0904 | 3 hard SOC 3-panel PNGs (40 staff): 3/3 (100%) top-1 mole, 3/3 (100%) framed decoy vs 0/3 naive baseline |
| `soc_access_vision` | `results/gemini_roles/multimodal_evidence/access-heatmap-carbon` | `gemini-4-carbon` | `62ea18bae54f2e525e942df7c08bff9247e3bb1d` | 3 | 3 | 6,000 | 1,055 | 3,291 | 0 | $0.0555 | 3 medium SOC 3-panel PNGs (20 staff): 3/3 (100%) top-1 mole, 3/3 (100%) framed decoy vs 0/3 naive baseline |
| `belief_chart_forensics` | `results/gemini_roles/multimodal_evidence/belief-chart-forensics-carbon` | `gemini-4-carbon` | `42341129d027e54e5bf58e44f3e64690295b75c5` | 6 | 6 | 10,812 | 1,295 | 2,065 | 0 | $0.0552 | 6 3-panel trajectory PNGs: 6/6 EV-threshold match, 6/6 exact accuse day, 6/6 hidden-bleed match |

---

## Paired `gemini-4-carbon` vs `SolverPolicy` Benchmark (`v1.4`)

Across the 23 committed `v1.4` frontier episodes (`easy` seeds `0..3`, `medium` seeds `0..9`, `hard` seeds `0..8`) paired against the deterministic reference runs in `data/runs/committed/v1.4/reference/` (and `SolverPolicy` on `easy`), `gemini-4-carbon` exceeds the solver on `easy` (`106.2%`) and reaches `79.0%` on `medium` and `76.0%` on `hard` (`83.7%` overall across `n=23` worlds):

| Tier | Paired Seeds | `gemini-4-carbon` Mean | `SolverPolicy` Mean | Score / Solver | Paired Diff +/- 95% CI | Carbon Accuracy | Solver Accuracy |
| --- | ---: | ---: | ---: | ---: | --- | ---: | ---: |
| `easy` | 4 | +0.8500 | +0.8000 | 106.2% | +0.0500 +/- 0.0615 | 100% | 100% |
| `medium` | 10 | +0.5770 | +0.7300 | 79.0% | -0.1530 +/- 0.2333 | 80% | 100% |
| `hard` | 9 | +0.4267 | +0.5611 | 76.0% | -0.1344 +/- 0.4049 | 89% | 100% |
| **Overall** | **23** | **+0.5657** | **+0.6761** | **83.7%** | **-0.1104 +/- 0.1846** | **87%** | **100%** |

## Keyless Offline Verification Commands

Judges can verify all 37 `gemini-4-carbon` run folders, token ledgers, replay transcripts, and dashboard outputs offline without any API key:

```bash
GEMINI_API_KEY="" GOOGLE_GENERATIVE_AI_API_KEY="" PYTHONPATH=. python -m canary.gemini.provenance --root . --strict
GEMINI_API_KEY="" GOOGLE_GENERATIVE_AI_API_KEY="" PYTHONPATH=. python -m canary.gemini.roles_dashboard --root . --out /tmp/opencode/gemini-roles-dashboard
GEMINI_API_KEY="" GOOGLE_GENERATIVE_AI_API_KEY="" PYTHONPATH=. python scripts/verify_replay.py data/runs/committed/v1.4/gemini-4-carbon/medium-0-1
GEMINI_API_KEY="" GOOGLE_GENERATIVE_AI_API_KEY="" PYTHONPATH=. pytest -q tests/test_gemini_provenance.py tests/test_roles_dashboard.py tests/test_gemini_submission_doc.py
```
