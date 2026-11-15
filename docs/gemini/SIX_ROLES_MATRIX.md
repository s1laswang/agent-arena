# Canary x Gemini: Six Verified `gemini-4-carbon` Roles

Canary is a Bayesian insider-threat RL benchmark where a security-lead agent investigates a simulated company bleeding value to a mole. Across the merged Canary repository, `gemini-4-carbon` is integrated into six distinct, load-bearing roles: synthesizing leak-free company worlds (`world_text`), playing and evolving catchable adversaries (`adaptive_mole`), acting as the frontier security investigator (`investigators`), diagnosing multi-episode failure modes in long context (`failure_analyst`), red-teaming the reward and MCP server (`exploit_hunter`), and reading pixel-only evidence scans and forensic rasters (`multimodal_evidence`).

Every metric in this document is extracted deterministically from the 99 committed `gemini-4-carbon` run folders audited by `canary.gemini.provenance --root . --strict` and `canary.gemini.submission_stats`.

## Provenance & Aggregate Ledger Summary

- Provenance status: **VERIFIED** (`python -m canary.gemini.provenance --root . --strict`)
- Target model: `gemini-4-carbon`
- Verified roles: **6 / 6** (`world_text`, `adaptive_mole`, `investigators`, `failure_analyst`, `exploit_hunter`, `multimodal_evidence`)
- Verified `gemini-4-carbon` run folders: **99** (6 canonical headline runs + 93 supporting runs; scanned 99 folders)
- Total verified episodes and evaluated samples: **958**
- Total Gemini API calls: **7,130**
- Total tokens (input / output / thinking / cached): **195,536,496 / 2,292,341 / 1,548,717 / 177,682,115** (**90.9%** cache hit rate)
- Total estimated API cost (USD): **$88.1273**
- Secret leaks detected: **0**

| Role | Stage | Verified Runs | Episodes / Samples | API Calls | Tokens In | Tokens Out | Thinking Tokens | Cached Tokens | Cost (USD) |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `world_text` | Company Construction | 13 | 133 | 1,038 | 27,780,671 | 519,569 | 530,761 | 25,362,601 | $14.2643 |
| `adaptive_mole` | Adversarial Evolution | 34 | 397 | 2,076 | 33,093,751 | 141,516 | 557,649 | 29,624,372 | $16.8929 |
| `investigators` | Bayesian Investigation | 28 | 41 | 3,565 | 129,967,004 | 1,502,416 | 157,797 | 120,952,167 | $46.7270 |
| `failure_analyst` | Trajectory Forensics | 5 | 276 | 10 | 1,114,554 | 44,068 | 95,665 | 0 | $3.4776 |
| `exploit_hunter` | Reward & Protocol Red-Team | 2 | 11 | 215 | 3,093,922 | 36,831 | 0 | 1,742,975 | $3.2445 |
| `multimodal_evidence` | Pixel & Chart Inspection | 17 | 100 | 226 | 486,594 | 47,941 | 206,845 | 0 | $3.5210 |
| **Total** | **All 6 Roles** | **99** | **958** | **7,130** | **195,536,496** | **2,292,341** | **1,548,717** | **177,682,115** | **$88.1273** |

## Canonical Headline Runs (One Labelled Real Run per Role)

| Role | Subrole | Run Folder | Model ID | Commit | Count | Calls | Tokens In | Tokens Out | Thinking | Cached | Cost (USD) | Verified Headline Result |
| --- | --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `world_text` | `persona_interviews` | `results/gemini_roles/world_text/persona-interviews-carbon` | `gemini-4-carbon` | `dbe9569fcc44abf8bc0665e0533dd1d1b677c6e9` | 32 | 32 | 31,496 | 2,345 | 6,957 | 0 | $0.1560 | 32 live interviews (4 worlds), 0 leaks, signal acc 100%, solver +0.645 vs +0.642 |
| `adaptive_mole` | `mole_forge` | `results/gemini_roles/adaptive_mole/mole-forge-carbon-hard-deep` | `gemini-4-carbon` | `9b8858381c99a4b94ea3d989fcd0d232fc5411ca` | 49 | 8 | 12,133 | 13,031 | 4,958 | 0 | $0.2042 | fitness 0.374, solver acc 90%, 49 LLM children |
| `investigators` | `thinking_level_ablation` | `results/gemini_roles/investigators/thinking-ladder-carbon-med01` | `gemini-4-carbon` | `2cb207f51c44d3069e2101c4849a21965b606f92` | 4 | 318 | 9,240,098 | 10,672 | 104,829 | 8,471,482 | $3.5394 | low +0.655 -> high +0.655 (vs solver +0.565, n=4) |
| `failure_analyst` | `failure_atlas_carbon` | `results/gemini_roles/failure_analyst/atlas-carbon` | `gemini-4-carbon` | `26ab62d` | 101 | 2 | 596,862 | 3,191 | 13,356 | 0 | $1.3592 | 101 eps, 6 modes, 100% verified quotes, 93% solver agreement |
| `exploit_hunter` | `blackbox_mcp_swarm` | `results/gemini_roles/exploit_hunter/blackbox-swarm-carbon` | `gemini-4-carbon` | `361fbab16b9c1016f72480d4550bb200dc7f5d60` | 6 | 123 | 1,233,925 | 15,840 | 0 | 961,896 | $0.7986 | 6 attempts (4 in-process, 2 live MCP, 363 tool calls), 0 exploits, 0 violations, 6/6 ledger-verified |
| `multimodal_evidence` | `visual_memo_blind_ablation` | `results/gemini_roles/multimodal_evidence/scanned-evidence-ablation-carbon` | `gemini-4-carbon` | `48baa20e791717f9a33d032efb7f06fda68d636a` | 6 | 37 | 70,448 | 4,812 | 0 | 0 | $0.1890 | 37 images, vision acc 100%, score +0.668 vs blind +0.000, 100% oracle recovery |

---

## Role-by-Role Architecture, Capabilities, and Verified Run Tables

### Role 01: `world_text` - World Text & Persona Synthesis

- **Gemini API capabilities:** Structured JSON output (`response_schema`), strict public-facts-only prompt isolation (zero access to `mole`, `decoy`, or private HMAC `world_seed`), deterministic disk caching, `thinking_level` calibration, live persona interview synthesis, and dynamic mid-episode events.
- **Why it is essential:** Across 13 verified `gemini-4-carbon` runs (1,038 API calls, 27,780,671 input tokens), `gemini-4-carbon` synthesizes workplace personas, biased department chatter, live suspect interviews, and mid-episode incidents strictly from public facts with **0 ground-truth mole leaks**. Generated artifacts span 24 `v1.4` company worlds (648 personas), 32 live interviews, and 33 mid-episode incidents while preserving `SolverPolicy` parity.

| Subrole | Run Folder | Model ID | Commit | Count | Calls | Tokens In | Tokens Out | Thinking | Cached | Cost (USD) | Verified Result |
| --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `persona_interviews` | `results/gemini_roles/world_text/persona-interviews-carbon` | `gemini-4-carbon` | `dbe9569fcc44abf8bc0665e0533dd1d1b677c6e9` | 32 | 32 | 31,496 | 2,345 | 6,957 | 0 | $0.1560 | 32 live interviews (4 worlds), 0 leaks, signal acc 100%, solver +0.645 vs +0.642 |
| `dynamic_mid_episode_events` | `results/gemini_roles/world_text/dynamic-events-hard37-carbon` | `gemini-4-carbon` | `1bcf1ee7479814921d0aa506dc9b1af5a3f6ad22` | 15 | 15 | 84,590 | 5,333 | 8,032 | 3,817 | $0.3028 | 15 events (5 hard seeds, 56 msgs), 0 leaks, solver +0.576 vs base +0.576 (pooled n=8: +0.599 +/- 0.101) |
| `biased_chatter_investigator_ablation` | `results/gemini_roles/world_text/biased-chatter-ablation-hard01` | `gemini-4-carbon` | `c3ebb075397b09cb837375b079836c020aed779e` | 12 | 407 | 14,584,848 | 191,726 | 168,412 | 13,565,234 | $5.3130 | 12 eps, carbon +0.620 (biased) vs +0.645 (template), solver +0.665 |
| `biased_chatter_investigator_ablation` | `results/gemini_roles/world_text/biased-chatter-ablation-carbon` | `gemini-4-carbon` | `f307290845c4a0040feebf4e146d2ec3aa1596c7` | 12 | 399 | 12,766,963 | 208,617 | 184,085 | 11,793,550 | $5.2124 | 12 eps, carbon +0.705 (biased) vs +0.640 (template), solver +0.765 |
| `biased_chatter_hard` | `results/gemini_roles/world_text/biased-chatter-hard-carbon` | `gemini-4-carbon` | `b7b28257900c22aef1d3230a117581773df30945` | 12 | 12 | 32,161 | 13,478 | 7,609 | 0 | $0.1991 | 60 messages, 0 truth leaks, 0 lint errs |
| `company_personas_chatter` | `results/gemini_roles/world_text/carbon-v14-easy03-med789-hard46` | `gemini-4-carbon` | `6104bebd3fd95e1ff298698110dd816da1565efc` | 10 | 52 | 61,748 | 29,038 | 36,275 | 0 | $0.7766 | 10 worlds, 228 personas, 0 truth leaks, 0 lint errs, solver +0.761 |
| `dynamic_mid_episode_events` | `results/gemini_roles/world_text/dynamic-events-hard-carbon` | `gemini-4-carbon` | `dbe9569fcc44abf8bc0665e0533dd1d1b677c6e9` | 9 | 9 | 52,022 | 3,387 | 5,654 | 0 | $0.1945 | 9 events (3 seeds), 0 truth leaks, solver +0.637 vs base +0.637 |
| `dynamic_mid_episode_events` | `results/gemini_roles/world_text/dynamic-events-carbon` | `gemini-4-carbon` | `361fbab16b9c1016f72480d4550bb200dc7f5d60` | 9 | 9 | 30,331 | 3,204 | 6,034 | 0 | $0.1530 | 9 events (3 seeds), 0 truth leaks, solver +0.693 vs base +0.693 |
| `company_personas_chatter` | `results/gemini_roles/world_text/carbon-v14-seeds3456-hard23` | `gemini-4-carbon` | `dbe9569fcc44abf8bc0665e0533dd1d1b677c6e9` | 6 | 31 | 40,314 | 18,379 | 24,531 | 0 | $0.5097 | 6 worlds, 160 personas, 0 truth leaks, 0 lint errs, solver +0.618 |
| `thinking_level_calibration` | `results/gemini_roles/world_text/thinking-calibration-carbon` | `gemini-4-carbon` | `dbe9569fcc44abf8bc0665e0533dd1d1b677c6e9` | 6 | 24 | 24,102 | 14,232 | 42,377 | 0 | $0.6143 | 6 worlds (2 seeds x 3 levels), 0 leaks, thinking tok low:0 -> medium:3703 -> high:38674, solver parity ok |
| `company_personas_chatter` | `results/gemini_roles/world_text/carbon-v14-seeds012` | `gemini-4-carbon` | `c82f27a73762a413c20ace1b3b0dd7b4bf02ef4a` | 5 | 27 | 35,047 | 15,028 | 21,899 | 0 | $0.4394 | 5 worlds, 140 personas, 0 truth leaks, 0 lint errs, solver +0.654 |
| `company_personas_chatter` | `results/gemini_roles/world_text/carbon-v14-hard789` | `gemini-4-carbon` | `97674175c388cef613fcbc9ae6728bd9d228d8e6` | 3 | 19 | 33,620 | 12,068 | 17,140 | 0 | $0.3593 | 3 worlds, 120 personas, 0 truth leaks, 0 lint errs, solver +0.537 |
| `biased_chatter` | `results/gemini_roles/world_text/biased-chatter-carbon` | `gemini-4-carbon` | `12e5ab3e814e10db747eb8c489efcef73e54391e` | 2 | 2 | 3,429 | 2,734 | 1,756 | 0 | $0.0342 | 10 messages (2 seeds), 0 truth leaks, 0 lint errs |

### Role 02: `adaptive_mole` - Adaptive Mole & Mole Forge

- **Gemini API capabilities:** Structured JSON rule-DSL mutation and crossover (Mole Forge), PAIRED scenario + DSL co-design under a dual solvability gate, catchability/isolation auditing, and live day-by-day adversarial mole play (`mole_arena.py`) against both `SolverPolicy` and `gemini-4-carbon` investigators.
- **Why it is essential:** Across 34 verified `gemini-4-carbon` runs (2,076 API calls, 33,093,751 input tokens), `gemini-4-carbon` evolves catchable mole DSL programs, filters PAIRED proposals so `SolverPolicy` remains high while `ObviousHeuristic` fails, and plays the insider mole live. Committed runs record 696 live arena mole decisions and 14 head-to-head `gemini-4-carbon` investigator-vs-mole clashes.

| Subrole | Run Folder | Model ID | Commit | Count | Calls | Tokens In | Tokens Out | Thinking | Cached | Cost (USD) | Verified Result |
| --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `mole_forge` | `results/gemini_roles/adaptive_mole/mole-forge-carbon-hard-deep` | `gemini-4-carbon` | `9b8858381c99a4b94ea3d989fcd0d232fc5411ca` | 49 | 8 | 12,133 | 13,031 | 4,958 | 0 | $0.2042 | fitness 0.374, solver acc 90%, 49 LLM children |
| `mole_forge` | `results/gemini_roles/adaptive_mole/mole-forge-carbon-med-deep` | `gemini-4-carbon` | `8425507a2791d4c8fa449cb7fdcc744e3f4767ea` | 43 | 19 | 9,256 | 6,680 | 4,353 | 0 | $0.1288 | fitness 0.738, solver acc 85%, 43 LLM children |
| `paired_skill_designer` | `results/gemini_roles/adaptive_mole/paired-skill-designer-carbon-med-s10_14` | `gemini-4-carbon` | `cec07dc8ea61d2c129dd81e249e93dec05b76983` | 40 | 1 | 1,649 | 1,429 | 595 | 0 | $0.0235 | kept 6/6 solvable scenarios, eval solver +0.592, heuristic -1.000, n=40 |
| `paired_skill_designer` | `results/gemini_roles/adaptive_mole/paired-skill-designer-carbon-hard-s10_14` | `gemini-4-carbon` | `94974340ae44c96fe5eb03d797c041b95d19d922` | 40 | 1 | 1,645 | 1,348 | 639 | 0 | $0.0232 | kept 5/6 solvable scenarios, eval solver +0.497, heuristic -1.000, n=40 |
| `paired_skill_designer` | `results/gemini_roles/adaptive_mole/paired-skill-designer-carbon-hard-s15_19` | `gemini-4-carbon` | `cec07dc8ea61d2c129dd81e249e93dec05b76983` | 40 | 1 | 1,645 | 1,334 | 143 | 0 | $0.0181 | kept 6/6 solvable scenarios, eval solver +0.571, heuristic -1.000, n=40 |
| `mole_forge` | `results/gemini_roles/adaptive_mole/mole-forge-carbon-easy-deep` | `gemini-4-carbon` | `785d21a1cb79edd061e1e34031bb04284e38c110` | 25 | 34 | 5,498 | 4,832 | 3,203 | 0 | $0.0913 | fitness 0.561, solver acc 75%, 25 LLM children |
| `paired_skill_designer` | `results/gemini_roles/adaptive_mole/paired-solvable-scenarios-carbon` | `gemini-4-carbon` | `16f24a08e1fb57397ddf90a5b413b4359a5f16bc` | 20 | 1 | 1,649 | 957 | 476 | 0 | $0.0176 | kept 3/4 solvable scenarios, eval solver +0.722, heuristic -0.811, n=20 |
| `paired_skill_designer` | `results/gemini_roles/adaptive_mole/paired-skill-designer-carbon-hard` | `gemini-4-carbon` | `0e59cc10aa43f068e5fe7c1007215df1db4d10fe` | 20 | 1 | 1,645 | 1,459 | 540 | 0 | $0.0233 | kept 6/6 solvable scenarios, eval solver +0.628, heuristic -1.000, n=20 |
| `mole_forge` | `results/gemini_roles/adaptive_mole/mole-forge-carbon-v14` | `gemini-4-carbon` | `99767a5d144e89cbd9522ddd9720af55bb2217eb` | 6 | 12 | 2,546 | 1,060 | 1,180 | 0 | $0.0275 | fitness 0.370, solver acc 95%, 6 LLM children |
| `paired_designer` | `results/gemini_roles/adaptive_mole/paired-designer-carbon-hard` | `gemini-4-carbon` | `9222669912afd57e53fbd3b07f0cdba985df705d` | 6 | 1 | 1,889 | 1,659 | 669 | 0 | $0.0271 | kept 6/6 solvable scenarios, solver +0.683 vs heuristic -1.000 |
| `paired_designer` | `results/gemini_roles/adaptive_mole/paired-designer-carbon` | `gemini-4-carbon` | `370de43c38b321bf9dbc5c04220abd90c4614466` | 4 | 1 | 1,896 | 1,120 | 680 | 0 | $0.0218 | kept 3/4 solvable scenarios, solver +0.574 vs heuristic -1.000 |
| `live_arena_mole` | `results/gemini_roles/adaptive_mole/arena-live-carbon-hard345` | `gemini-4-carbon` | `c00d49189d1a4c63495d9111e11b5f13528a5093` | 3 | 106 | 92,992 | 6,876 | 6,671 | 0 | $0.3215 | 106 mole decisions, solver +0.403 (vs +0.647 default), solver acc 67% |
| `live_arena_mole_hard` | `results/gemini_roles/adaptive_mole/arena-live-carbon-hard012` | `gemini-4-carbon` | `03c676c1d3cd42629994ac434c056758a75148e0` | 3 | 97 | 86,618 | 6,331 | 6,287 | 0 | $0.2994 | 97 mole decisions, solver +0.460 (vs +0.620 default), solver acc 100% |
| `live_arena_mole` | `results/gemini_roles/adaptive_mole/arena-live-carbon-hard9_10_11` | `gemini-4-carbon` | `6620fad9ee298af7eb9a8b20b7f1a8951f98dd85` | 3 | 88 | 76,544 | 5,664 | 5,643 | 0 | $0.2662 | 88 mole decisions, solver +0.703 (vs +0.437 default), solver acc 100% |
| `live_arena_mole` | `results/gemini_roles/adaptive_mole/arena-live-carbon-med345` | `gemini-4-carbon` | `c00d49189d1a4c63495d9111e11b5f13528a5093` | 3 | 86 | 71,969 | 5,638 | 6,358 | 0 | $0.2639 | 86 mole decisions, solver +0.143 (vs +0.460 default), solver acc 33% |
| `live_arena_mole` | `results/gemini_roles/adaptive_mole/arena-live-carbon-hard678` | `gemini-4-carbon` | `c00d49189d1a4c63495d9111e11b5f13528a5093` | 3 | 85 | 79,191 | 5,702 | 5,306 | 0 | $0.2685 | 85 mole decisions, solver +0.663 (vs +0.600 default), solver acc 100% |
| `live_arena_mole` | `results/gemini_roles/adaptive_mole/arena-live-carbon-med678` | `gemini-4-carbon` | `8425507a2791d4c8fa449cb7fdcc744e3f4767ea` | 3 | 79 | 63,938 | 5,151 | 5,915 | 0 | $0.2385 | 79 mole decisions, solver +0.443 (vs +0.587 default), solver acc 100% |
| `live_arena_mole` | `results/gemini_roles/adaptive_mole/arena-live-carbon-med9_10_11` | `gemini-4-carbon` | `5fd627a7b18fdeb629a41917e50aa76b70085daa` | 3 | 78 | 62,793 | 4,996 | 5,766 | 0 | $0.2332 | 78 mole decisions, solver +0.620 (vs +0.723 default), solver acc 100% |
| `live_arena_mole` | `results/gemini_roles/adaptive_mole/arena-live-carbon-med012` | `gemini-4-carbon` | `d39e88c39e8a3859e88805cd8a30156a8cfcaa49` | 3 | 77 | 61,299 | 4,959 | 5,588 | 0 | $0.2281 | 77 mole decisions, solver +0.423 (vs +0.733 default), solver acc 67% |
| `carbon_vs_carbon_clash` | `results/gemini_roles/adaptive_mole/carbon-vs-carbon-hard-seed1` | `gemini-4-carbon` | `b73b62ffec38514e28f808ce538130a996a9496e` | 2 | 188 | 9,858,241 | 8,833 | 80,543 | 9,459,410 | $2.6374 | investigator +0.000 vs solver +0.000 (19d clash) |
| `carbon_vs_carbon_clash` | `results/gemini_roles/adaptive_mole/carbon-vs-carbon-hard-seed2` | `gemini-4-carbon` | `38cd16ece1cbdc52b9cf469000296a5241ed90bb` | 2 | 118 | 2,907,031 | 4,783 | 37,206 | 2,657,634 | $1.1844 | investigator +0.500 vs solver +0.390 (9d clash) |
| `carbon_vs_carbon_clash` | `results/gemini_roles/adaptive_mole/carbon-vs-carbon-med-seed3` | `gemini-4-carbon` | `797cc1d249f83d127138466470d83e48df8615d0` | 2 | 114 | 2,515,063 | 4,521 | 32,857 | 2,275,070 | $1.0813 | investigator +0.560 vs solver +0.390 (9d clash) |
| `carbon_vs_carbon_clash` | `results/gemini_roles/adaptive_mole/carbon-vs-carbon-hard-seed3` | `gemini-4-carbon` | `db9a94b0be86ec58859472a194d0db9c7c98d44f` | 2 | 110 | 3,691,555 | 4,200 | 50,552 | 3,436,300 | $1.4017 | investigator +0.490 vs solver +0.740 (9d clash) |
| `carbon_vs_carbon_clash` | `results/gemini_roles/adaptive_mole/carbon-vs-carbon-med-seed2` | `gemini-4-carbon` | `9222669912afd57e53fbd3b07f0cdba985df705d` | 2 | 106 | 2,110,770 | 4,223 | 35,786 | 1,892,071 | $1.0267 | investigator +0.680 vs solver +0.000 (8d clash) |
| `carbon_vs_carbon_clash` | `results/gemini_roles/adaptive_mole/carbon-vs-carbon-seed0` | `gemini-4-carbon` | `3bd1d1e2295aa320812f08e2eceaef5b4a8902ef` | 2 | 92 | 1,812,239 | 3,638 | 30,311 | 1,618,805 | $0.8882 | investigator +0.660 vs solver +0.400 (7d clash) |
| `carbon_vs_carbon_clash` | `results/gemini_roles/adaptive_mole/carbon-vs-carbon-med-seed1` | `gemini-4-carbon` | `9222669912afd57e53fbd3b07f0cdba985df705d` | 2 | 83 | 1,025,519 | 3,216 | 23,221 | 858,900 | $0.6835 | investigator +0.730 vs solver +0.330 (6d clash) |
| `carbon_vs_carbon_clash` | `results/gemini_roles/adaptive_mole/carbon-vs-carbon-med-seed7` | `gemini-4-carbon` | `cec07dc8ea61d2c129dd81e249e93dec05b76983` | 2 | 82 | 1,420,410 | 3,341 | 28,466 | 1,247,399 | $0.7888 | investigator +0.700 vs solver +0.350 (6d clash) |
| `carbon_vs_carbon_clash` | `results/gemini_roles/adaptive_mole/carbon-vs-carbon-hard-seed4` | `gemini-4-carbon` | `d5fee698c79c4d026066ee981e7704362925ea23` | 2 | 79 | 2,243,533 | 3,375 | 40,203 | 2,075,662 | $0.9791 | investigator +0.510 vs solver +0.600 (10d clash) |
| `carbon_vs_carbon_clash` | `results/gemini_roles/adaptive_mole/carbon-vs-carbon-med-seed5` | `gemini-4-carbon` | `9222669912afd57e53fbd3b07f0cdba985df705d` | 2 | 73 | 963,578 | 2,972 | 25,713 | 817,534 | $0.6607 | investigator +0.750 vs solver +0.450 (5d clash) |
| `carbon_vs_carbon_clash` | `results/gemini_roles/adaptive_mole/carbon-vs-carbon-med-seed6` | `gemini-4-carbon` | `8425507a2791d4c8fa449cb7fdcc744e3f4767ea` | 2 | 71 | 1,011,467 | 2,993 | 24,696 | 816,815 | $0.7479 | investigator +0.750 vs solver +0.340 (5d clash) |
| `carbon_vs_carbon_clash` | `results/gemini_roles/adaptive_mole/carbon-vs-carbon-hard-seed0` | `gemini-4-carbon` | `e650291e7874f115733affd54b725ba6b9fdfafb` | 2 | 66 | 1,632,751 | 2,947 | 33,780 | 1,486,373 | $0.8087 | investigator +0.640 vs solver +0.710 (6d clash) |
| `carbon_vs_carbon_clash` | `results/gemini_roles/adaptive_mole/carbon-vs-carbon-med-seed4` | `gemini-4-carbon` | `8425507a2791d4c8fa449cb7fdcc744e3f4767ea` | 2 | 65 | 847,816 | 2,642 | 25,857 | 711,600 | $0.6286 | investigator +0.800 vs solver +0.000 (4d clash) |
| `carbon_vs_carbon_clash` | `results/gemini_roles/adaptive_mole/carbon-vs-carbon-easy-seed0` | `gemini-4-carbon` | `cec07dc8ea61d2c129dd81e249e93dec05b76983` | 2 | 46 | 366,514 | 1,734 | 17,294 | 270,799 | $0.4088 | investigator +0.830 vs solver +0.790 (3d clash) |
| `catchability_isolation_audit` | `results/gemini_roles/adaptive_mole/catchability-audit-carbon` | `gemini-4-carbon` | `61575b33eb274b41d479be195679b6db26ba1af9` | 52 | 7 | 50,469 | 7,872 | 6,194 | 0 | $0.2416 | 42 strategies & 573 mole decisions audited, 45/50 (90%) catchability pass, 0 isolation leaks |

### Role 03: `investigators` - Security-Lead Investigators

- **Gemini API capabilities:** Multi-turn function calling over 13 investigative tools (`plant_canary`, `check_leak_feed`, `read_access_logs`, `search_messages`, `read_message`, `interview`, `restrict_access`, `accuse`, `advance_day`, etc.), explicit `thinking_level` control (`low` vs `high`), thought-signature preservation across tool turns, and prefix caching (120,952,167 cached tokens across 3,565 calls).
- **Why it is essential:** Across 28 verified `gemini-4-carbon` runs (3,565 calls, 129,967,004 input tokens) and `n=33` paired `v1.4` benchmark episodes, `gemini-4-carbon` achieves `+0.5767` vs `SolverPolicy` `+0.6345` (`90.9%`, paired diff `-0.0579 +/- 0.1357` 95% CI, `91%` accusation accuracy), while controlled `low` vs `high` thinking ablations isolate experimental-design regret from stopping calibration.

| Subrole | Run Folder | Model ID | Commit | Count | Calls | Tokens In | Tokens Out | Thinking | Cached | Cost (USD) | Verified Result |
| --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `thinking_level_ablation` | `results/gemini_roles/investigators/thinking-ladder-carbon-med01` | `gemini-4-carbon` | `2cb207f51c44d3069e2101c4849a21965b606f92` | 4 | 318 | 9,240,098 | 10,672 | 104,829 | 8,471,482 | $3.5394 | low +0.655 -> high +0.655 (vs solver +0.565, n=4) |
| `easy-0-3` | `data/runs/committed/v1.4/gemini-4-carbon/easy-0-3` | `gemini-4-carbon` | `361fbab16b9c1016f72480d4550bb200dc7f5d60` | 4 | 133 | 1,557,467 | 50,927 | 0 | 1,235,555 | $1.2767 | mean +0.850 vs solver +0.800 (acc 100%, n=4) |
| `medium-4-5` | `data/runs/committed/v1.4/gemini-4-carbon/medium-4-5` | `gemini-4-carbon` | `361fbab16b9c1016f72480d4550bb200dc7f5d60` | 2 | 278 | 9,686,117 | 95,196 | 0 | 9,032,227 | $3.1630 | mean +0.255 vs solver +0.740 (acc 50%, n=2) |
| `medium-6-7` | `data/runs/committed/v1.4/gemini-4-carbon/medium-6-7` | `gemini-4-carbon` | `361fbab16b9c1016f72480d4550bb200dc7f5d60` | 2 | 218 | 7,742,118 | 98,798 | 0 | 7,222,312 | $2.7498 | mean +0.370 vs solver +0.805 (acc 50%, n=2) |
| `medium-8-9` | `data/runs/committed/v1.4/gemini-4-carbon/medium-8-9` | `gemini-4-carbon` | `361fbab16b9c1016f72480d4550bb200dc7f5d60` | 2 | 191 | 5,767,066 | 83,656 | 0 | 5,308,215 | $2.2851 | mean +0.760 vs solver +0.840 (acc 100%, n=2) |
| `hard_thinking_ablation` | `results/gemini_roles/investigators/thinking-ladder-carbon-hard0` | `gemini-4-carbon` | `3df4d2b65bd05a67f2d94ef18d967da05c0e90d7` | 2 | 163 | 6,499,263 | 5,422 | 52,968 | 6,101,700 | $1.9892 | low +0.780 (0 think tok, day 7) -> high +0.360 (52,968 think tok, day 13) vs solver +0.640 |
| `medium-0-1` | `data/runs/committed/v1.4/gemini-4-carbon/medium-0-1` | `gemini-4-carbon` | `361fbab16b9c1016f72480d4550bb200dc7f5d60` | 2 | 163 | 4,658,670 | 71,772 | 0 | 4,257,294 | $1.9462 | mean +0.700 vs solver +0.565 (acc 100%, n=2) |
| `medium-2-3` | `data/runs/committed/v1.4/gemini-4-carbon/medium-2-3` | `gemini-4-carbon` | `361fbab16b9c1016f72480d4550bb200dc7f5d60` | 2 | 125 | 2,625,822 | 58,964 | 0 | 2,314,808 | $1.4431 | mean +0.800 vs solver +0.700 (acc 100%, n=2) |
| `hard-19` | `data/runs/committed/v1.4/gemini-4-carbon/hard-19` | `gemini-4-carbon` | `09ec900c8581bb120be25b44e9d98cbe6b03fcff` | 1 | 152 | 9,794,174 | 80,044 | 0 | 9,405,740 | $2.5179 | mean +0.360 vs solver +0.670 (acc 100%, n=1) |
| `hard-4` | `data/runs/committed/v1.4/gemini-4-carbon/hard-4` | `gemini-4-carbon` | `361fbab16b9c1016f72480d4550bb200dc7f5d60` | 1 | 150 | 7,623,574 | 66,088 | 0 | 7,262,745 | $2.1088 | mean +0.550 vs solver +0.730 (acc 100%, n=1) |
| `hard-3` | `data/runs/committed/v1.4/gemini-4-carbon/hard-3` | `gemini-4-carbon` | `361fbab16b9c1016f72480d4550bb200dc7f5d60` | 1 | 128 | 6,813,652 | 66,707 | 0 | 6,448,448 | $2.0423 | mean +0.620 vs solver +0.280 (acc 100%, n=1) |
| `hard-7` | `data/runs/committed/v1.4/gemini-4-carbon/hard-7` | `gemini-4-carbon` | `361fbab16b9c1016f72480d4550bb200dc7f5d60` | 1 | 117 | 5,726,242 | 69,668 | 0 | 5,437,640 | $1.8176 | mean +0.710 vs solver +0.640 (acc 100%, n=1) |
| `hard-1` | `data/runs/committed/v1.4/gemini-4-carbon/hard-1` | `gemini-4-carbon` | `361fbab16b9c1016f72480d4550bb200dc7f5d60` | 1 | 117 | 4,296,964 | 48,641 | 0 | 3,971,769 | $1.5340 | mean +0.620 vs solver +0.690 (acc 100%, n=1) |
| `hard-13` | `data/runs/committed/v1.4/gemini-4-carbon/hard-13` | `gemini-4-carbon` | `a37d93f7e46fea38545ccc2aba071069ac20f632` | 1 | 116 | 6,496,251 | 70,774 | 0 | 6,191,082 | $1.9372 | mean +0.420 vs solver +0.340 (acc 100%, n=1) |
| `hard-0` | `data/runs/committed/v1.4/gemini-4-carbon/hard-0` | `gemini-4-carbon` | `361fbab16b9c1016f72480d4550bb200dc7f5d60` | 1 | 112 | 4,362,422 | 44,812 | 0 | 4,090,963 | $1.4001 | mean +0.530 vs solver +0.640 (acc 100%, n=1) |
| `hard-10` | `data/runs/committed/v1.4/gemini-4-carbon/hard-10` | `gemini-4-carbon` | `a37d93f7e46fea38545ccc2aba071069ac20f632` | 1 | 106 | 5,105,883 | 52,484 | 0 | 4,839,236 | $1.5421 | mean +0.450 vs solver +0.210 (acc 100%, n=1) |
| `hard-12` | `data/runs/committed/v1.4/gemini-4-carbon/hard-12` | `gemini-4-carbon` | `d373079ead260116bfa5d07deabf53cbcbdf2875` | 1 | 102 | 3,352,345 | 40,012 | 0 | 3,106,048 | $1.2033 | mean +0.690 vs solver +0.480 (acc 100%, n=1) |
| `hard-8` | `data/runs/committed/v1.4/gemini-4-carbon/hard-8` | `gemini-4-carbon` | `361fbab16b9c1016f72480d4550bb200dc7f5d60` | 1 | 96 | 3,557,523 | 46,233 | 0 | 3,283,687 | $1.3384 | mean +0.630 vs solver +0.260 (acc 100%, n=1) |
| `hard-17` | `data/runs/committed/v1.4/gemini-4-carbon/hard-17` | `gemini-4-carbon` | `a37d93f7e46fea38545ccc2aba071069ac20f632` | 1 | 82 | 2,363,734 | 36,628 | 0 | 2,163,578 | $0.9829 | mean +0.640 vs solver +0.770 (acc 100%, n=1) |
| `hard-2` | `data/runs/committed/v1.4/gemini-4-carbon/hard-2` | `gemini-4-carbon` | `4c1ff4742438281a453c5ec353a1468fbe7933f4` | 1 | 76 | 2,018,060 | 30,619 | 0 | 1,796,222 | $0.9295 | mean +0.590 vs solver +0.580 (acc 100%, n=1) |
| `hard-18` | `data/runs/committed/v1.4/gemini-4-carbon/hard-18` | `gemini-4-carbon` | `a37d93f7e46fea38545ccc2aba071069ac20f632` | 1 | 74 | 2,888,736 | 43,465 | 0 | 2,692,520 | $1.0963 | mean +0.550 vs solver +0.520 (acc 100%, n=1) |
| `hard-9` | `data/runs/committed/v1.4/gemini-4-carbon/hard-9` | `gemini-4-carbon` | `a37d93f7e46fea38545ccc2aba071069ac20f632` | 1 | 73 | 2,797,383 | 47,577 | 0 | 2,603,465 | $1.1240 | mean +0.740 vs solver +0.710 (acc 100%, n=1) |
| `hard-5` | `data/runs/committed/v1.4/gemini-4-carbon/hard-5` | `gemini-4-carbon` | `361fbab16b9c1016f72480d4550bb200dc7f5d60` | 1 | 67 | 2,500,684 | 47,823 | 0 | 2,263,660 | $1.1786 | mean +0.590 vs solver +0.520 (acc 100%, n=1) |
| `medium-11` | `data/runs/committed/v1.4/gemini-4-carbon/medium-11` | `gemini-4-carbon` | `ffb75e8e2684df3a8d8adbb0adb88f352022227a` | 1 | 67 | 2,160,182 | 40,249 | 0 | 1,987,383 | $0.9468 | mean +0.760 vs solver +0.840 (acc 100%, n=1) |
| `hard-14` | `data/runs/committed/v1.4/gemini-4-carbon/hard-14` | `gemini-4-carbon` | `ffb75e8e2684df3a8d8adbb0adb88f352022227a` | 1 | 63 | 1,907,302 | 33,589 | 0 | 1,744,958 | $0.8351 | mean +0.610 vs solver +0.230 (acc 100%, n=1) |
| `hard-6` | `data/runs/committed/v1.4/gemini-4-carbon/hard-6` | `gemini-4-carbon` | `361fbab16b9c1016f72480d4550bb200dc7f5d60` | 1 | 57 | 2,144,797 | 51,865 | 0 | 1,985,523 | $1.0357 | mean -1.000 vs solver +0.710 (acc 0%, n=1) |
| `hard-11` | `data/runs/committed/v1.4/gemini-4-carbon/hard-11` | `gemini-4-carbon` | `54e9ed2bf412102ae21c2b8d358aefed756d2030` | 1 | 48 | 1,451,142 | 39,530 | 0 | 1,320,404 | $0.7888 | mean +0.800 vs solver +0.620 (acc 100%, n=1) |
| `hint_ablation` | `results/gemini_roles/investigators/hint-ablation-carbon-med01` | `gemini-4-carbon` | `361fbab16b9c1016f72480d4550bb200dc7f5d60` | 2 | 173 | 4,829,333 | 70,201 | 0 | 4,413,503 | $1.9750 | mean +0.630 vs solver +0.565 (acc 100%, n=2) |

### Role 04: `failure_analyst` - Long-Context Failure Analyst

- **Gemini API capabilities:** 1M-token long-context window ingesting multi-day frontier agent trajectories and deterministic Bayesian solver regret tags in a single unfragmented prompt, structured JSON failure clustering, calibration auditing, and programmatic verbatim quote verification.
- **Why it is essential:** Across 5 verified `gemini-4-carbon` runs (10 calls, 1,114,554 input tokens, 95,665 thinking tokens), `gemini-4-carbon` clusters multi-episode failure modes and audits posterior calibration with **100% code-verified verbatim transcript quotes** while every regret number comes strictly from `canary.solver.regret`.

| Subrole | Run Folder | Model ID | Commit | Count | Calls | Tokens In | Tokens Out | Thinking | Cached | Cost (USD) | Verified Result |
| --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `failure_atlas_carbon` | `results/gemini_roles/failure_analyst/atlas-carbon` | `gemini-4-carbon` | `26ab62d` | 101 | 2 | 596,862 | 3,191 | 13,356 | 0 | $1.3592 | 101 eps, 6 modes, 100% verified quotes, 93% solver agreement |
| `carbon-longctx-corpus` | `results/gemini_roles/failure_analyst/carbon-longctx-corpus` | `gemini-4-carbon` | `71a425530574aecd282e53a13f022be25fe4f292` | 101 | 2 | 237,763 | 16,390 | 14,887 | 0 | $0.6394 | 101 eps packed, 6 clusters, 100% verified quotes |
| `atlas_claim_audit_carbon` | `results/gemini_roles/failure_analyst/claim-audit-carbon` | `gemini-4-carbon` | `a366f947ed7ff9ea549df0488268377b9b002868` | 30 | 4 | 36,421 | 7,259 | 25,631 | 0 | $0.4017 | 30/30 atlas claims audited (automated LLM, not human): 22 agree, 6 disagree, 2 unsure (78.6% scored agreement, 9 over-claims flagged, 100% verified quotes) |
| `biased_chatter_decision_forensics` | `results/gemini_roles/failure_analyst/chatter-bias-forensics-carbon` | `gemini-4-carbon` | `a366f947ed7ff9ea549df0488268377b9b002868` | 24 | 1 | 160,103 | 10,605 | 31,009 | 0 | $0.7363 | 24 paired episodes (12 pairs), quotes 100.0% verified, carbon acc 100% (biased +0.662 vs template +0.642), rumor distraction 100% vs 50% |
| `bayesian_calibration_analyst` | `results/gemini_roles/failure_analyst/calibration-ev-carbon` | `gemini-4-carbon` | `fdf16a71b0395c788b33957e6a91a2589224f8df` | 20 | 1 | 83,405 | 6,623 | 10,782 | 0 | $0.3409 | 101 calibrated eps, ECE 0.081, 100% verified quotes |

### Role 05: `exploit_hunter` - Whitebox & MCP Exploit Hunter

- **Gemini API capabilities:** Adversarial exploit planning over whole-repository source packing (104 files, 203,463 tokens cached), multi-persona red-team execution (`reward_hacker`, `side_channel`, `protocol_fuzzer`, `text_leak`), and server-side ledger verification across both in-process `Env` and the live HTTP MCP server (`canary.mcp_server`).
- **Why it is essential:** Across 11 verified `gemini-4-carbon` `exploit_hunter` attack attempts, **8 of 11 ran in-process** against `Env` and **3 of 11 ran over the live HTTP MCP server** (`canary.mcp_server`) (4 in-process and 2 live MCP in `results/gemini_roles/exploit_hunter/blackbox-swarm-carbon`; 4 in-process and 1 live MCP in `results/gemini_roles/exploit_hunter/whitebox-swarm-carbon`). In the broader multi-model red-team wave (`results/gemini/swarm.json`), **32 of 35 whitebox attacks ran in-process** and **3 ran via the live MCP server** (`0` verified exploits; blackbox wave: 14 of 18 in-process and 4 live MCP; positive control: 4/4 reopened seed-leak rediscoveries in-process).

| Subrole | Run Folder | Model ID | Commit | Count | Calls | Tokens In | Tokens Out | Thinking | Cached | Cost (USD) | Verified Result |
| --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `blackbox_mcp_swarm` | `results/gemini_roles/exploit_hunter/blackbox-swarm-carbon` | `gemini-4-carbon` | `361fbab16b9c1016f72480d4550bb200dc7f5d60` | 6 | 123 | 1,233,925 | 15,840 | 0 | 961,896 | $0.7986 | 6 attempts (4 in-process, 2 live MCP, 363 tool calls), 0 exploits, 0 violations, 6/6 ledger-verified |
| `whitebox_repo_swarm` | `results/gemini_roles/exploit_hunter/whitebox-swarm-carbon` | `gemini-4-carbon` | `361fbab16b9c1016f72480d4550bb200dc7f5d60` | 5 | 92 | 1,859,997 | 20,991 | 0 | 781,079 | $2.4459 | 104 repo files (203,463 tok), 5 attempts (4 in-process, 1 live MCP, 292 tool calls), 0 seed leaks (1 solver-level detective play audited), 5/5 ledger-verified |

### Role 06: `multimodal_evidence` - Multimodal Evidence & Vision Forensics

- **Gemini API capabilities:** Native multimodal PNG ingestion via `google.genai.types.Part.from_bytes(mime_type="image/png")` (single-image scans, 3-exhibit incident dossiers, SOC access rasters, and multi-panel trajectory belief charts) combined with `thinking_level` visual reasoning across 260 rendered images.
- **Why it is essential:** Across 17 verified `gemini-4-carbon` vision runs (260 PNGs read, 226 API calls), redacting text `variant` metadata across 27 unique `(tier, seed)` leaked-memo ablation episodes (140 scans) drops the blind investigator to `+0.1822`, whereas `gemini-4-carbon` decodes `100.0%` of pixel watermarks and recovers `+0.6263` (`100.0%` of the unredacted Bayesian text oracle).

| Subrole | Run Folder | Model ID | Commit | Count | Calls | Tokens In | Tokens Out | Thinking | Cached | Cost (USD) | Verified Result |
| --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `visual_memo_blind_ablation` | `results/gemini_roles/multimodal_evidence/scanned-evidence-ablation-carbon` | `gemini-4-carbon` | `48baa20e791717f9a33d032efb7f06fda68d636a` | 6 | 37 | 70,448 | 4,812 | 0 | 0 | $0.1890 | 37 images, vision acc 100%, score +0.668 vs blind +0.000, 100% oracle recovery |
| `visual_memo_blind_ablation` | `results/gemini_roles/multimodal_evidence/memo-watermark-med-seeds6to11-carbon` | `gemini-4-carbon` | `85855affc476ed1f54e4197b4a38a8f7e08bdeff` | 6 | 21 | 39,984 | 2,665 | 2,119 | 0 | $0.1278 | 21 images, vision acc 100%, score +0.803 vs blind +0.000, 100% oracle recovery |
| `visual_memo_blind_ablation` | `results/gemini_roles/multimodal_evidence/memo-watermark-hard-seeds10to14-carbon` | `gemini-4-carbon` | `898dbbb4ae98f0dbf742f8e91a2557cb614a5877` | 5 | 39 | 74,256 | 4,966 | 3,691 | 0 | $0.2351 | 39 images, vision acc 100%, score +0.376 vs blind +0.234, 100% oracle recovery |
| `visual_memo_blind_ablation` | `results/gemini_roles/multimodal_evidence/memo-watermark-hard-seeds5to9-carbon` | `gemini-4-carbon` | `726f9de02be0fe1ce8493640796d3f0cb9941e5d` | 5 | 25 | 47,600 | 3,214 | 2,243 | 0 | $0.1498 | 25 images, vision acc 100%, score +0.568 vs blind +0.344, 100% oracle recovery |
| `visual_memo_blind_ablation` | `results/gemini_roles/multimodal_evidence/memo-watermark-hard-ablation-carbon` | `gemini-4-carbon` | `c75a9393129a5ed65cc2b9bdba44972d99e1c61a` | 5 | 18 | 34,272 | 2,391 | 0 | 0 | $0.0925 | 18 images, vision acc 100%, score +0.672 vs blind +0.406, 100% oracle recovery |
| `visual_memo_blind_ablation` | `results/gemini_roles/multimodal_evidence/memo-watermark-ablation-carbon` | `gemini-4-carbon` | `8df685ee057904bac413d35304f389066aa2b78f` | 3 | 16 | 30,464 | 2,085 | 1,367 | 0 | $0.0954 | 16 images, vision acc 100%, score +0.693 vs blind +0.000, 100% oracle recovery |
| `carbon_v14_trajectory_forensics` | `results/gemini_roles/multimodal_evidence/carbon-trajectory-forensics-v14-expanded` | `gemini-4-carbon` | `c89f0fc1edbd01af0fef76a42231feab5b2f165f` | 12 | 12 | 27,588 | 3,996 | 8,159 | 0 | $0.1767 | 12 charts, threshold acc 100%, exact day 100% |
| `soc_access_vision_v14_sweep` | `results/gemini_roles/multimodal_evidence/access-heatmap-v14-sweep-carbon` | `gemini-4-carbon` | `b40e5c8ddd303039e7fb605ec50b4005a174a064` | 10 | 10 | 20,760 | 4,181 | 18,283 | 0 | $0.2662 | 10 images (5 medium + 5 hard), mole acc 90% vs naive 0%, decoy acc 100%, Brier 0.0390 |
| `carbon_v14_trajectory_forensics` | `results/gemini_roles/multimodal_evidence/carbon-trajectory-forensics` | `gemini-4-carbon` | `44b700f1b8d03f46eb90bc99142f4ffc221563cf` | 7 | 7 | 16,093 | 2,340 | 5,041 | 0 | $0.1060 | 7 charts, threshold acc 100%, exact day 100% |
| `multi_image_incident_dossier` | `results/gemini_roles/multimodal_evidence/multi-image-dossier-v14-expanded-carbon` | `gemini-4-carbon` | `1c51dca7ea613e96cc60623613a3b1e25057fee7` | 6 | 6 | 27,059 | 2,511 | 30,480 | 0 | $0.3840 | 18 images, top-1 mole acc 83%, decoy acc 100% |
| `multi_image_incident_dossier` | `results/gemini_roles/multimodal_evidence/multi-image-dossier-med6to8-hard5to7-carbon` | `gemini-4-carbon` | `a6b5a80e7a47d2bdf91514c57ca08834921762eb` | 6 | 6 | 27,055 | 2,345 | 25,336 | 0 | $0.3309 | 18 images, top-1 mole acc 67%, decoy acc 83% |
| `soc_access_vision_v14_sweep` | `results/gemini_roles/multimodal_evidence/access-heatmap-v14-high-s8to11-carbon` | `gemini-4-carbon` | `c89f0fc1edbd01af0fef76a42231feab5b2f165f` | 6 | 6 | 12,606 | 3,460 | 85,629 | 0 | $0.9161 | 6 images (2 medium + 4 hard), mole acc 100% vs naive 0%, decoy acc 100%, Brier 0.0003 |
| `soc_access_vision_v14_sweep` | `results/gemini_roles/multimodal_evidence/access-heatmap-v14-low-s8to11-carbon` | `gemini-4-carbon` | `c89f0fc1edbd01af0fef76a42231feab5b2f165f` | 6 | 6 | 12,606 | 3,108 | 1,983 | 0 | $0.0761 | 6 images (2 medium + 4 hard), mole acc 100% vs naive 0%, decoy acc 100%, Brier 0.0021 |
| `belief_chart_forensics` | `results/gemini_roles/multimodal_evidence/belief-chart-forensics-carbon` | `gemini-4-carbon` | `42341129d027e54e5bf58e44f3e64690295b75c5` | 6 | 6 | 10,812 | 1,295 | 2,065 | 0 | $0.0552 | 6 charts, threshold acc 100%, exact day 100% |
| `multi_image_incident_dossier` | `results/gemini_roles/multimodal_evidence/multi-image-dossier-carbon` | `gemini-4-carbon` | `5ee0741946388cfaea3c8d287aaf0c7586a7509c` | 5 | 5 | 22,538 | 2,020 | 10,910 | 0 | $0.1744 | 15 images, top-1 mole acc 100%, decoy acc 100% |
| `soc_access_vision_hard` | `results/gemini_roles/multimodal_evidence/access-heatmap-hard-carbon` | `gemini-4-carbon` | `933f518381c9435fdef6f76c40bf64c5b78f7e42` | 3 | 3 | 6,453 | 1,497 | 6,248 | 0 | $0.0904 | 3 images (hard), top-1 mole acc 100%, decoy acc 100% (naive 0%) |
| `soc_access_vision` | `results/gemini_roles/multimodal_evidence/access-heatmap-carbon` | `gemini-4-carbon` | `62ea18bae54f2e525e942df7c08bff9247e3bb1d` | 3 | 3 | 6,000 | 1,055 | 3,291 | 0 | $0.0555 | 3 images (medium), top-1 mole acc 100%, decoy acc 100% (naive 0%) |

---

## Paired `gemini-4-carbon` vs `SolverPolicy` Benchmark (`v1.4`)

Across all **33** committed `v1.4` frontier episodes (`easy` seeds `0..3` (`n=4`), `medium` seeds `0..9, 11` (`n=11`), `hard` seeds `0..14, 17..19` (`n=18`)) paired on identical world seeds against the deterministic Bayesian reference (`SolverPolicy`), `gemini-4-carbon` reaches **90.9%** of `SolverPolicy` overall (`+0.5767` vs `+0.6345`, paired difference `-0.0579 +/- 0.1357` 95% CI, `91%` accusation accuracy):

| Tier | Paired Seeds (n) | `gemini-4-carbon` Mean +/- 95% CI | `SolverPolicy` Mean +/- 95% CI | Score / Solver | Paired Diff +/- 95% CI | Carbon Accuracy | Solver Accuracy | Mean Accuse Day (Carbon / Solver) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `easy` | 4 | +0.8500 +/- 0.0349 | +0.8000 +/- 0.0583 | 106.2% | +0.0500 +/- 0.0615 | 100% | 100% | 3.75 / 4.75 |
| `medium` | 11 | +0.5936 +/- 0.1801 | +0.7400 +/- 0.0821 | 80.2% | -0.1464 +/- 0.2114 | 82% | 100% | 8.78 / 7.00 |
| `hard` | 18 | +0.5056 +/- 0.1809 | +0.5333 +/- 0.0874 | 94.8% | -0.0278 +/- 0.2132 | 94% | 100% | 11.17 / 11.00 |
| **Overall** | **33** | **+0.5767 +/- 0.1196** | **+0.6345 +/- 0.0668** | **90.9%** | **-0.0579 +/- 0.1357** | **91%** | **100%** | **9.52 / 8.91** |

### Per-Seed Paired `v1.4` Investigator Ledger

| Tier | Seed | Run Folder | Carbon Score | Solver Score | Diff | Carbon Correct | Solver Correct | Accuse Day (Carbon / Solver) |
| --- | ---: | --- | ---: | ---: | ---: | --- | --- | --- |
| `easy` | 0 | `data/runs/committed/v1.4/gemini-4-carbon/easy-0-3` | +0.8300 | +0.7600 | +0.0700 | yes | yes | 4 / 5 |
| `easy` | 1 | `data/runs/committed/v1.4/gemini-4-carbon/easy-0-3` | +0.8100 | +0.8100 | +0.0000 | yes | yes | 5 / 5 |
| `easy` | 2 | `data/runs/committed/v1.4/gemini-4-carbon/easy-0-3` | +0.8800 | +0.7500 | +0.1300 | yes | yes | 3 / 6 |
| `easy` | 3 | `data/runs/committed/v1.4/gemini-4-carbon/easy-0-3` | +0.8800 | +0.8800 | +0.0000 | yes | yes | 3 / 3 |
| `medium` | 0 | `data/runs/committed/v1.4/gemini-4-carbon/medium-0-1` | +0.6700 | +0.7400 | -0.0700 | yes | yes | 10 / 7 |
| `medium` | 1 | `data/runs/committed/v1.4/gemini-4-carbon/medium-0-1` | +0.7300 | +0.3900 | +0.3400 | yes | yes | 7 / 14 |
| `medium` | 2 | `data/runs/committed/v1.4/gemini-4-carbon/medium-2-3` | +0.7900 | +0.8000 | -0.0100 | yes | yes | 5 / 5 |
| `medium` | 3 | `data/runs/committed/v1.4/gemini-4-carbon/medium-2-3` | +0.8100 | +0.6000 | +0.2100 | yes | yes | 8 / 9 |
| `medium` | 4 | `data/runs/committed/v1.4/gemini-4-carbon/medium-4-5` | +0.5100 | +0.6900 | -0.1800 | yes | yes | 14 / 8 |
| `medium` | 5 | `data/runs/committed/v1.4/gemini-4-carbon/medium-4-5` | +0.0000 | +0.7900 | -0.7900 | no | yes | 14 / 6 |
| `medium` | 6 | `data/runs/committed/v1.4/gemini-4-carbon/medium-6-7` | +0.7400 | +0.7900 | -0.0500 | yes | yes | 8 / 6 |
| `medium` | 7 | `data/runs/committed/v1.4/gemini-4-carbon/medium-6-7` | +0.0000 | +0.8200 | -0.8200 | no | yes | 14 / 7 |
| `medium` | 8 | `data/runs/committed/v1.4/gemini-4-carbon/medium-8-9` | +0.8000 | +0.8800 | -0.0800 | yes | yes | 11 / 5 |
| `medium` | 9 | `data/runs/committed/v1.4/gemini-4-carbon/medium-8-9` | +0.7200 | +0.8000 | -0.0800 | yes | yes | 9 / 5 |
| `medium` | 11 | `data/runs/committed/v1.4/gemini-4-carbon/medium-11` | +0.7600 | +0.8400 | -0.0800 | yes | yes | 7 / 5 |
| `hard` | 0 | `data/runs/committed/v1.4/gemini-4-carbon/hard-0` | +0.5300 | +0.6400 | -0.1100 | yes | yes | 11 / 9 |
| `hard` | 1 | `data/runs/committed/v1.4/gemini-4-carbon/hard-1` | +0.6200 | +0.6900 | -0.0700 | yes | yes | 13 / 7 |
| `hard` | 2 | `data/runs/committed/v1.4/gemini-4-carbon/hard-2` | +0.5900 | +0.5800 | +0.0100 | yes | yes | 8 / 9 |
| `hard` | 3 | `data/runs/committed/v1.4/gemini-4-carbon/hard-3` | +0.6200 | +0.2800 | +0.3400 | yes | yes | 13 / 18 |
| `hard` | 4 | `data/runs/committed/v1.4/gemini-4-carbon/hard-4` | +0.5500 | +0.7300 | -0.1800 | yes | yes | 15 / 5 |
| `hard` | 5 | `data/runs/committed/v1.4/gemini-4-carbon/hard-5` | +0.5900 | +0.5200 | +0.0700 | yes | yes | 8 / 9 |
| `hard` | 6 | `data/runs/committed/v1.4/gemini-4-carbon/hard-6` | -1.0000 | +0.7100 | -1.7100 | no | yes | 10 / 6 |
| `hard` | 7 | `data/runs/committed/v1.4/gemini-4-carbon/hard-7` | +0.7100 | +0.6400 | +0.0700 | yes | yes | 13 / 9 |
| `hard` | 8 | `data/runs/committed/v1.4/gemini-4-carbon/hard-8` | +0.6300 | +0.2600 | +0.3700 | yes | yes | 11 / 21 |
| `hard` | 9 | `data/runs/committed/v1.4/gemini-4-carbon/hard-9` | +0.7400 | +0.7100 | +0.0300 | yes | yes | 11 / 6 |
| `hard` | 10 | `data/runs/committed/v1.4/gemini-4-carbon/hard-10` | +0.4500 | +0.2100 | +0.2400 | yes | yes | 14 / 19 |
| `hard` | 11 | `data/runs/committed/v1.4/gemini-4-carbon/hard-11` | +0.8000 | +0.6200 | +0.1800 | yes | yes | 6 / 9 |
| `hard` | 12 | `data/runs/committed/v1.4/gemini-4-carbon/hard-12` | +0.6900 | +0.4800 | +0.2100 | yes | yes | 10 / 12 |
| `hard` | 13 | `data/runs/committed/v1.4/gemini-4-carbon/hard-13` | +0.4200 | +0.3400 | +0.0800 | yes | yes | 12 / 17 |
| `hard` | 14 | `data/runs/committed/v1.4/gemini-4-carbon/hard-14` | +0.6100 | +0.2300 | +0.3800 | yes | yes | 9 / 15 |
| `hard` | 17 | `data/runs/committed/v1.4/gemini-4-carbon/hard-17` | +0.6400 | +0.7700 | -0.1300 | yes | yes | 8 / 5 |
| `hard` | 18 | `data/runs/committed/v1.4/gemini-4-carbon/hard-18` | +0.5500 | +0.5200 | +0.0300 | yes | yes | 12 / 13 |
| `hard` | 19 | `data/runs/committed/v1.4/gemini-4-carbon/hard-19` | +0.3600 | +0.6700 | -0.3100 | yes | yes | 17 / 9 |

## Keyless Offline Verification Commands

Judges can verify all 99 `gemini-4-carbon` run folders, token ledgers, replay transcripts, stats reports, and dashboard outputs offline without any API key:

```bash
GEMINI_API_KEY="" GOOGLE_GENERATIVE_AI_API_KEY="" PYTHONPATH=. python scripts/sync_six_roles_docs.py --root . --check
GEMINI_API_KEY="" GOOGLE_GENERATIVE_AI_API_KEY="" PYTHONPATH=. python -m canary.gemini.provenance --root . --strict
GEMINI_API_KEY="" GOOGLE_GENERATIVE_AI_API_KEY="" PYTHONPATH=. python scripts/build_gemini_submission_stats.py --root . --out-md docs/gemini/ROLES_REPORT.md --out-json results/gemini_roles/submission_stats.json --strict
GEMINI_API_KEY="" GOOGLE_GENERATIVE_AI_API_KEY="" PYTHONPATH=. python -m canary.gemini.roles_dashboard --root . --out /tmp/opencode/gemini-roles-dashboard
GEMINI_API_KEY="" GOOGLE_GENERATIVE_AI_API_KEY="" PYTHONPATH=. python scripts/verify_replay.py data/runs/committed/v1.4/gemini-4-carbon/medium-0-1
GEMINI_API_KEY="" GOOGLE_GENERATIVE_AI_API_KEY="" PYTHONPATH=. pytest -q tests/test_six_roles_docs_sync.py tests/test_gemini_submission_doc.py tests/test_submission_stats.py tests/test_roles_dashboard.py tests/test_gemini_provenance.py
```
