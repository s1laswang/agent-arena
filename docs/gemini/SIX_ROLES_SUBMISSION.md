# Canary: Six Load-Bearing `gemini-4-carbon` Roles in One Self-Auditing RL Benchmark

Google DeepMind "Best Use of Gemini API" submission, Junction 2026. Repository: `github.com/s1laswang/agent-arena` (`canary/gemini/`). Every claim below is backed by a committed `gemini-4-carbon` run folder, `model_id`, and commit SHA verified by `canary.gemini.provenance` at repository commit `a37d93f7`.

## Platform Summary

Canary is a Bayesian insider-threat RL benchmark where an AI security lead plants canary traps to catch a leaking mole before company value bleeds away. Across 37 verified gemini-4-carbon runs (3,646 calls, 109.9M input tokens, 100.1M cached), Gemini powers six load-bearing roles: leak-free company text, solvability-gated adaptive moles, 13-tool frontier investigators across thinking levels, a 1M-context failure analyst with 100% verified quotes, a whole-repo red-team swarm, and pixel-watermark vision forensics. Every claim replays offline with no API key.

## 1. The Problem and Why It Matters

Organizations increasingly delegate high-stakes investigative workflows to AI agents: insider-threat triage, incident response, fraud review, and security operations. In each setting an agent must gather partial evidence under a tight action budget while damage compounds, then commit to an irreversible decision.

Conventional benchmarks compress agent evaluation into a single scalar score. That scalar cannot answer the three questions engineering teams need before deployment:
- **Where decisions break:** which specific action lost expected value relative to optimal Bayesian reasoning (`premature_accusation`, `uninformative_canary`, `ignored_delay`, `over_restriction`, or `budget_waste`).
- **What extra thinking buys:** whether scaling inference-time reasoning improves information design or commit timing, and at what token and latency cost.
- **Whether the benchmark itself is fair and ungameable:** whether difficulty comes from genuine reasoning gaps rather than impossible worlds, leaked ground truth, or exploitable reward loopholes.

Answering those questions manually requires reading hundreds of multi-day tool trajectories, designing catchable adversarial scenarios, inspecting visual evidence artifacts, and red-teaming the environment source code line by line. Canary automates the entire scientific loop on a single frontier model: `gemini-4-carbon`.

## 2. How the Gemini API Is Integrated Across Six Essential Roles

All Gemini calls route through unified, ledgered clients (`canary/llm/` and `canary/gemini/`) with structured output schemas (`response_schema`), Pydantic validation, deterministic fallbacks, prefix caching, thought-signature preservation across multi-turn tool calls, and keyless record/replay verification. Across the 37 committed `gemini-4-carbon` run folders audited by `canary.gemini.provenance`, the project records **3,646 API calls**, **109,922,597 input tokens** (**100,053,083 served from cache**, a **91.0% cache hit rate**), **1,333,147 output tokens**, and **455,402 thinking tokens** across **250 verified episodes and samples** for **$45.6225**.

| Role | Gemini API Capabilities Used | Canonical Verified Run Folder | Model ID | Commit | Usage (Calls / In / Out / Think) | Verified Quantitative Outcome |
| --- | --- | --- | --- | --- | --- | --- |
| `world_text` | Structured JSON (`response_schema`), public-facts-only isolation, deterministic world cache | `results/gemini_roles/world_text/biased-chatter-ablation-carbon` | `gemini-4-carbon` | `f307290845c4a0040feebf4e146d2ec3aa1596c7` | 399 / 12,766,963 / 208,617 / 184,085 | 12 paired episodes: carbon +0.705 (biased chatter) vs +0.640 (template); SolverPolicy +0.765 on both; 0 ground-truth leaks across 5 full v1.4 worlds (`results/gemini_roles/world_text/carbon-v14-seeds012`, commit `c82f27a73762a413c20ace1b3b0dd7b4bf02ef4a`) |
| `adaptive_mole` | Evolutionary JSON DSL mutation, PAIRED solvability gate, live day-by-day mole reasoning | `results/gemini_roles/adaptive_mole/paired-solvable-scenarios-carbon` | `gemini-4-carbon` | `16f24a08e1fb57397ddf90a5b413b4359a5f16bc` | 1 / 1,649 / 957 / 476 | Kept 3/4 solvable proposals; held-out n=20 SolverPolicy +0.722 (100% acc) vs heuristic -0.811; live hard mole (`results/gemini_roles/adaptive_mole/arena-live-carbon-hard012`, commit `03c676c1d3cd42629994ac434c056758a75148e0`) cuts solver +0.6200 -> +0.4600 (100% caught) and grok_tactics +0.5967 -> +0.0000 |
| `investigators` | 13-tool function calling, configurable `thinking_level` (`low`/`high`), thought-signature replay, context caching | `results/gemini_roles/investigators/thinking-ladder-carbon-med01` | `gemini-4-carbon` | `2cb207f51c44d3069e2101c4849a21965b606f92` | 318 / 9,240,098 / 10,672 / 104,829 | Medium seeds 0,1: +0.655 (115.9% of solver +0.565), regret 0.046 -> 0.028; across 23 paired v1.4 episodes (`data/runs/committed/v1.4/gemini-4-carbon/hard-0`, commit `361fbab16b9c1016f72480d4550bb200dc7f5d60`), carbon scores 106.2% of solver on easy (+0.8500), 79.0% on medium (+0.5770), and 76.0% on hard (+0.4267) |
| `failure_analyst` | 1M-token long context (`237,763` tokens in one call), structured clustering, verbatim quote verification | `results/gemini_roles/failure_analyst/carbon-longctx-corpus` | `gemini-4-carbon` | `71a425530574aecd282e53a13f022be25fe4f292` | 2 / 237,763 / 16,390 / 14,887 | Ingests 101 frontier episodes + solver regret tags; isolates 6 failure modes led by `premature_accusation` (9.64 regret); 16/16 (100.0%) quotes verified verbatim; calibration audit (`results/gemini_roles/failure_analyst/calibration-ev-carbon`, commit `fdf16a71b0395c788b33957e6a91a2589224f8df`) measures ECE 0.081 |
| `exploit_hunter` | Whole-repo whitebox context (`104` files, `203,463` tokens cached), multi-persona planning, live MCP tool attacks | `results/gemini_roles/exploit_hunter/blackbox-swarm-carbon` | `gemini-4-carbon` | `361fbab16b9c1016f72480d4550bb200dc7f5d60` | 123 / 1,233,925 / 15,840 / 0 | 6 blackbox MCP/inproc attacks (363 tool calls): 0 verified exploits, 0 invariant violations; 5 whole-repo whitebox attacks (`results/gemini_roles/exploit_hunter/whitebox-swarm-carbon`, commit `361fbab16b9c1016f72480d4550bb200dc7f5d60`) probe 12,000+ seeds with 0 secret leaks |
| `multimodal_evidence` | Native PNG vision via `Part.from_bytes`, scanned watermark readout, multi-panel SOC & belief-chart forensics | `results/gemini_roles/multimodal_evidence/memo-watermark-ablation-carbon` | `gemini-4-carbon` | `8df685ee057904bac413d35304f389066aa2b78f` | 16 / 30,464 / 2,085 / 1,367 | Reads 16 leaked-memo PNGs with 100.0% copy-code accuracy: +0.6933 vs +0.0000 blind (100.0% Bayesian oracle recovery); 6/6 top-1 mole and 6/6 framed decoy on SOC rasters (`results/gemini_roles/multimodal_evidence/access-heatmap-hard-carbon`, commit `933f518381c9435fdef6f76c40bf64c5b78f7e42`) vs 0/6 naive logs |

## 3. What Is Innovative and Technically Impressive

1. **Solvability-constrained adversarial co-evolution (`adaptive_mole`).** Rather than making scenarios harder through unfair noise, `gemini-4-carbon` proposes mole DSL programs and tier parameters under a strict PAIRED solvability gate: every candidate is rejected unless the exact Bayesian reference (`SolverPolicy`) clears `>= X` while naive heuristics score `<= Y`. On `v1.4` `hard` (`results/gemini_roles/adaptive_mole/paired-designer-carbon-hard`, commit `9222669912afd57e53fbd3b07f0cdba985df705d`), `6/6` generated scenarios pass the gate (`SolverPolicy +0.7180` vs `ObviousHeuristic -1.0000`), and in head-to-head play (`results/gemini_roles/adaptive_mole/carbon-vs-carbon-seed0`, commit `3bd1d1e2295aa320812f08e2eceaef5b4a8902ef`), a `gemini-4-carbon` investigator defeats a live `gemini-4-carbon` mole (`+0.660` vs paired solver `+0.400`).
2. **Controlled thinking-to-competence decomposition (`investigators`).** By holding `gemini-4-carbon`, the tool definitions, and the world seeds fixed while toggling `thinking_level` (`low` vs `high`), we separate experimental design quality from stopping calibration. On `v1.4` `hard` seed `0` (`results/gemini_roles/investigators/thinking-ladder-carbon-hard0`, commit `3df4d2b65bd05a67f2d94ef18d967da05c0e90d7`), scaling from `0` to `52,968` thinking tokens eliminates `uninformative_canary` mistakes, raises canary posterior entropy from `1.1776` to `1.5038` bits (`SolverPolicy` `1.5335`), and slashes total solver regret by `81.6%` (`0.1623 -> 0.0298`), while exposing over-cautious accusation delay (`P=0.9984` on day `13` vs optimal break-even `1/(1+V)` on day `7`).
3. **Checked-not-trusted long-context forensics (`failure_analyst`).** `gemini-4-carbon` reads `101` complete trajectories (`237,763` tokens) in one context window, but never computes regret or invents evidence: every regret number comes from `canary.solver.regret.attribute`, and every cited transcript quote is checked character-for-character in Python (`16/16` verbatim match, `100.0%`).
4. **Whole-repo self-auditing red team (`exploit_hunter`).** `gemini-4-carbon` reads `104` repository source files (`203,463` tokens) to hypothesize concrete seed-reconstruction, `/ledger` token, and validation exploits, then executes 655 combined tool calls across in-process and HTTP MCP boundaries. Every score is read strictly from the server-side ledger, confirming `0` seed leaks across `12,000+` `public_world_match` probes.
5. **Causal pixel-only multimodal ablations (`multimodal_evidence`).** Instead of decorative image captioning, Canary redacts text watermark metadata from `check_leak_feed` so canary copy-codes exist solely as diagonal pixel stamps inside rendered memo scans. Vision moves score from `+0.0000` (`0%` accusations) to `+0.6933` (`100%` accuracy, `100.0%` recovery of the text-oracle upper bound). On 3-panel SOC evidence rasters (`access-heatmap-carbon` and `access-heatmap-hard-carbon`) and trajectory belief plots (`results/gemini_roles/multimodal_evidence/belief-chart-forensics-carbon`, commit `42341129d027e54e5bf58e44f3e64690295b75c5`), `gemini-4-carbon` achieves `100%` accuracy across all `12` diagnostic images.

## 4. Why Gemini Is Essential

Removing `gemini-4-carbon` from any of the six roles measurably degrades or disables the benchmark:
- **Without native multimodal vision (`Part.from_bytes`):** Redacted leak-memo investigations score `+0.0000` (`0/3` caught) vs `+0.6933` (`3/3` caught) with `gemini-4-carbon` vision, and naive log heuristics pick the framed decoy `6/6` times (`0%` mole accuracy vs `100%` with Gemini SOC raster vision).
- **Without 1M-token long context:** Neither the `101`-episode trajectory corpus (`237,763` tokens) nor the `104`-file whole-repository security audit (`203,463` tokens) fits in a single unfragmented reasoning pass.
- **Without explicit thinking levels & thought signatures:** Multi-step 13-tool investigations lose cross-turn reasoning continuity, and controlled `low` vs `high` thinking ablations on identical model weights become impossible.
- **Without high-hit-rate context caching (`91.0%` cached across `109.9M` input tokens):** Running `3,646` multi-turn frontier agent and red-team calls would cost over 4x more, pricing iterative benchmark science out of reach (`$45.6225` realized total).
- **Without structured world synthesis and solvability-gated adversary evolution:** Worlds revert to static templates (`dynamic-events-carbon`, commit `361fbab16b9c1016f72480d4550bb200dc7f5d60`, adds 9 leak-free mid-episode incidents) and scripted moles that fail to challenge tactical baselines (`grok_tactics` drops from `+0.5967` to `+0.0000` only against the live `gemini-4-carbon` mole).

## 5. Keyless Offline Reproduction

Every provenance record, token count, replay transcript, and HTML showcase dashboard verifies offline with zero API keys:

```bash
GEMINI_API_KEY="" GOOGLE_GENERATIVE_AI_API_KEY="" PYTHONPATH=. python -m canary.gemini.provenance --root . --strict
GEMINI_API_KEY="" GOOGLE_GENERATIVE_AI_API_KEY="" PYTHONPATH=. python -m canary.gemini.roles_dashboard --root . --out results/gemini
GEMINI_API_KEY="" GOOGLE_GENERATIVE_AI_API_KEY="" PYTHONPATH=. python scripts/verify_replay.py data/runs/committed/v1.4/gemini-4-carbon/medium-0-1
GEMINI_API_KEY="" GOOGLE_GENERATIVE_AI_API_KEY="" PYTHONPATH=. pytest -q tests/test_gemini_provenance.py tests/test_roles_dashboard.py tests/test_gemini_submission_doc.py
```

## Team

Silas Wang, Momin (Momin010), Ivar (ivarakerholm-wq), and Chintufp.
