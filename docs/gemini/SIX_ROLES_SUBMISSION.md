# Canary: Six Load-Bearing `gemini-4-carbon` Roles in One Self-Auditing RL Benchmark

Companion six-role `gemini-4-carbon` prize write-up for Google DeepMind "Best Use of Gemini API", Junction 2026 (`canary/gemini/carbon_roles.py`). Every metric below is computed deterministically from committed folders under `results/gemini/roles_carbon/` (**6/6** roles populated, **107** verified run folders, **7,910** API calls, **$98.9498** cache-adjusted USD / **$497.3420** uncached list USD). Main track overview: `docs/gemini/SUBMISSION.md`; full run inventory: `docs/gemini/ROLES_CARBON.md`.

## Platform Summary

Canary is a Bayesian insider-threat RL benchmark where an AI security lead plants canary traps to catch a mole before company value bleeds. Across 107 verified gemini-4-carbon runs (7,910 API calls, $98.95 USD) in six essential roles, Gemini drives world text, adaptive moles, 13-tool investigators, 1M-context failure forensics, repo/MCP exploit hunting, and Part.from_bytes scan vision (paired v1.4 n=33: 90.9% of SolverPolicy, diff -0.058 +/- 0.136 95% CI). Keyless offline replay.

## 1. The Problem and Why Six Roles Matter

Teams deploying autonomous investigators in insider-threat triage, incident response, or fraud operations face partial observations, tight daily budgets, compounding damage, and an irreversible accusation. A single scalar benchmark score cannot answer where an agent lost expected value, what extra inference-time reasoning (`thinking_level`) buys per dollar, whether text or visual telemetry leaks ground truth, or whether the reward can be exploited.

Canary closes that loop by pairing every world with an exact Bayesian reference (`SolverPolicy`) and running `gemini-4-carbon` across six distinct, auditable roles.

## 2. One Labelled Real `gemini-4-carbon` Run per Role

| Role | Gemini API Capabilities | Canonical Run Folder | Model ID | Commit | Calls / In / Out / Think / Cost | Verified Quantitative Outcome |
| --- | --- | --- | --- | --- | --- | --- |
| `world_text` | Structured JSON (`response_schema`), public-facts-only isolation, live suspect interviews, 37-encoding stego audit | `results/gemini/roles_carbon/world_text/persona-interviews-carbon` | `gemini-4-carbon` | `dbe9569fcc44abf8bc0665e0533dd1d1b677c6e9` | 32 / 31,496 / 2,345 / 6,957 / $0.1560 | 32 live interviews (4 worlds), 0 leaks, signal acc 100%, solver +0.645 vs +0.642; 16 verified runs (1,637 calls) |
| `adaptive_mole` | Evolutionary JSON DSL mutation, PAIRED solvability gate, live day-by-day mole play, catchability audit | `results/gemini/roles_carbon/adaptive_mole/paired-skill-designer-carbon-hard` | `gemini-4-carbon` | `0e59cc10aa43f068e5fe7c1007215df1db4d10fe` | 1 / 1,645 / 1,459 / 540 / $0.0233 | kept 6/6 solvable scenarios, solver +0.628; 39 verified runs (2,257 calls) |
| `investigators` | 13-tool function calling, controlled `thinking_level` (`low`/`high`), `thought_signature` replay, prefix caching | `results/gemini/roles_carbon/investigators/thinking-ladder-carbon-hard0` | `gemini-4-carbon` | `3df4d2b65bd05a67f2d94ef18d967da05c0e90d7` | 163 / 6,499,263 / 5,422 / 52,968 / $1.9892 | low +0.780 (0 think tok, day 7) -> high +0.360 (52,968 think tok, day 13) vs solver +0.640; paired v1.4 n=33: +0.5767 vs SolverPolicy +0.6345 (90.9%, diff -0.0579 +/- 0.1357 95% CI) |
| `failure_analyst` | 1M-token long context, structured failure clustering, Bayesian calibration audit, verbatim quote verification | `results/gemini/roles_carbon/failure_analyst/atlas-carbon` | `gemini-4-carbon` | `26ab62d` | 2 / 596,862 / 3,191 / 13,356 / $1.3592 | 101 eps packed, 100% verified quotes, 93.3% solver agreement; 5 verified runs (10 calls) |
| `exploit_hunter` | Whole-repo whitebox context pack, multi-persona exploit planning, in-process `Env` + live HTTP MCP execution | `results/gemini/roles_carbon/exploit_hunter/whitebox-swarm-carbon` | `gemini-4-carbon` | `361fbab16b9c1016f72480d4550bb200dc7f5d60` | 92 / 1,859,997 / 20,991 / 0 / $2.4459 | 104 repo files (203,463 tok), 5 attempts (4 in-process, 1 live MCP, 292 tool calls), 0 seed leaks (1 solver-level detective play audited), 5/5 ledger-verified; `results/gemini/roles_carbon/exploit_hunter/blackbox-swarm-carbon` (commit `361fbab16b9c1016f72480d4550bb200dc7f5d60`): 6 attacks (4 in-process, 2 live MCP); suite channels: 8/11 in-process, 3/11 live HTTP MCP |
| `multimodal_evidence` | Native PNG vision via `Part.from_bytes`, scanned watermark readout, multi-image dossiers, SOC & chart forensics | `results/gemini/roles_carbon/multimodal_evidence/scanned-evidence-ablation-carbon` | `gemini-4-carbon` | `48baa20e791717f9a33d032efb7f06fda68d636a` | 37 / 70,448 / 4,812 / 0 / $0.1890 | 6 medium eps (37 PNGs), vision +0.6683 vs blind +0.0000, 100% watermark acc, 100% oracle recovery; pooled unique ablation n=27 (140 scans, 260 suite PNGs): +0.6263 vs +0.1822 blind (diff +0.4441 +/- 0.1219 95% CI, 100% oracle recovery) |

- **Explicit `exploit_hunter` channel disclosure:** Across the `roles_carbon/exploit_hunter` suite, **8 of 11** audited `gemini-4-carbon` attacks executed in-process against `canary.env.Env` and **3 of 11** executed over live HTTP MCP (11/11 server-ledger verified, 655 tool calls): `results/gemini/roles_carbon/exploit_hunter/blackbox-swarm-carbon` (commit `361fbab16b9c1016f72480d4550bb200dc7f5d60`): 6 attacks (4 in-process, 2 live HTTP MCP; 0 exploits, 0 violations); `results/gemini/roles_carbon/exploit_hunter/whitebox-swarm-carbon` (commit `361fbab16b9c1016f72480d4550bb200dc7f5d60`): 5 attacks (4 in-process, 1 live HTTP MCP; 0 seed leaks (1 solver-level detective play audited)).
- **Paired `v1.4` `gemini-4-carbon` vs `SolverPolicy` (`n=33`, 95% CIs):** `+0.5767 +/- 0.1196` vs `SolverPolicy` `+0.6345 +/- 0.0668` (`90.9%`, paired diff `-0.0579 +/- 0.1357`, accuracy `90.9%`).
- **Causal pixel-only watermark ablation (`n=27`, 95% CIs):** across `140` PNG scans read via `Part.from_bytes`, `gemini-4-carbon` scores `+0.6263 +/- 0.0724` vs `+0.1822 +/- 0.0978` blind (paired lift `+0.4441 +/- 0.1219`, `100.0%` watermark accuracy, `100.0%` Bayesian text-oracle recovery).

## 3. What Is Technically Impressive and Honest by Construction

1. **Causal pixel-only and multi-image multimodal forensics (`multimodal_evidence`).** Canary renders canary document watermarks, three-image incident dossiers, decoy-framed SOC heatmaps, and posterior belief trajectories into PNG bytes (`260` PNGs read via `Part.from_bytes`), proving causal visual lift against a blind control on identical world seeds.
2. **Server-ledger red-teaming across source packs and live MCP (`exploit_hunter`).** Whole-repo whitebox and blackbox swarms plan and execute multi-turn attacks scored exclusively from server-side ledgers, with every in-process vs HTTP MCP channel explicitly disclosed.
3. **Checked-not-trusted long-context forensics (`failure_analyst`).** Full trajectory packs are analyzed in 1M-token context while every regret value comes from `canary.solver.regret` and every cited quote is verified character-for-character in Python (`docs/gemini/validation.md` remains untouched for human labeller Ivar).
4. **Controlled `thinking_level` paired against exact Bayes (`investigators`).** Toggling `thinking_level` on identical `v1.4` worlds with cryptographic `thought_signature` replay separates experimental-design gains from stopping conservatism.
5. **Leak-audited world text and solvability-gated adversaries (`world_text`, `adaptive_mole`).** Public-facts-only world synthesis (`v1.5` demo/research layer) passes 37-encoding steganography checks with zero mole leaks, while arena-mode adaptive moles and PAIRED scenarios must pass `SolverPolicy` catchability gates.

## 4. Why Gemini Is Essential

Removing `gemini-4-carbon` or its Gemini-native API controls measurably degrades or breaks each role:

- **Controlled `thinking_level` on one model:** Holding `gemini-4-carbon`, tool schemas, and `v1.4` seeds fixed in `results/gemini/roles_carbon/investigators/thinking-ladder-carbon-hard0` (commit `3df4d2b65bd05a67f2d94ef18d967da05c0e90d7`) isolates reasoning depth as a single controlled variable (`52,968` thinking tokens, `low +0.780 (0 think tok, day 7) -> high +0.360 (52,968 think tok, day 13) vs solver +0.640`).
- **Load-bearing `thought_signature` replay:** Preserving cryptographic `thought_signature` tokens across `3,565` multi-turn 13-tool investigator calls and `7,910` total suite calls keeps latent Bayesian hypothesis state intact across multi-day tool invocations; stripping signatures causes immediate `400 INVALID_ARGUMENT` rejection on Gemini function-call replay (`canary.gemini.ablations`).
- **Explicit and prefix context caching:** Serving **206,588,345** of **226,451,136** input tokens from explicit and prefix cache (**91.2%** cache hit rate across **7,910** calls) keeps effective API spend at **$98.9498** (vs **$497.3420** uncached list price).
- **1M-token long context:** Ingests whole-repository whitebox security packs (`104` files, `203,463` tokens) and `1,114,554` failure-analyst input tokens in unfragmented single-prompt passes without lossy RAG chunking, while every cited quote and regret delta is checked deterministically in Python.
- **Native multimodal vision (`Part.from_bytes`):** Reads `260` rendered PNG scans, dossiers, SOC heatmaps, and belief charts directly via `Part.from_bytes(mime_type="image/png")`; across `n=27` unique redacted-memo episodes (`140` PNG scans), vision lifts score from `+0.1822` (blind) to `+0.6263` (`+0.4441 +/- 0.1219` 95% CI, `100.0%` watermark accuracy, `100.0%` Bayesian text-oracle recovery).

## 5. Keyless Offline Reproduction

All provenance records, token ledgers, SHA-256 image manifests, and synchronized markdown tables verify offline without an API key:

```bash
GEMINI_API_KEY="" GOOGLE_GENERATIVE_AI_API_KEY="" PYTHONPATH=. python -m canary.gemini.carbon_roles --root . --check
GEMINI_API_KEY="" GOOGLE_GENERATIVE_AI_API_KEY="" PYTHONPATH=. pytest -q tests/test_gemini_lab_carbon_roles.py
```

## Team

Silas Wang, Momin (Momin010), Ivar (ivarakerholm-wq), and Chintufp.
