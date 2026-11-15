# Role 1 (world_text): Persona-Conditioned HR Interview Engine & Solver Parity

- Scope: demo/research layer (v1.5 candidate), not part of the judged v1.4 environment
- Role / subrole: `world_text` / `persona_interviews`
- Model ID: `gemini-4-carbon` (`gemini:gemini-4-carbon`)
- Commit: `e742ebe31e5a03cb2bf10faccae93e5989b8a1d6`
- Timestamp: `2026-11-14T23:58:37+00:00`
- Tiers version: `v1.4` | Worlds: `4` (`hard` seeds 1,2,3,4)
- Live interviews generated: `32` (`llm_ok=32`, `fallbacks=0`)
- Non-leak & stego audit: `truth_leak_violations=0`, `lint_violations=0`, `stego_leak_violations=0` across `37` encodings, `prompt_truth_leak_violations=0` (`96` counterfactual mole/decoy swap checks, invariance `100%`)
- Signal calibration: blind accuracy `100.0%`, pairwise cooperative > evasive ordering `100.0%`, mean margin `+12.19`
- Token usage: `32` calls, `31608` in, `2376` out, `8910` thinking, `42894` total tokens (`$0.176076` est., `130.22s`)

## Linguistic Signal Calibration (Evasive vs Cooperative)

| Metric | Cooperative | Evasive |
|---|---:|---:|
| Sample count | 16 | 16 |
| Mean linguistic stance score | +5.81 | -6.38 |
| Specificity / verification rate | 100.0% | 0.0% |
| Hedging / deflection rate | 0.0% | 100.0% |
| Mean word count | 49.4 | 24.9 |

### Topic Breakdown

| Topic | Samples | Blind Signal Acc | Cooperative Score | Evasive Score |
|---|---:|---:|---:|---:|
| `recent_documents` | 8 | 100.0% | +6.00 | -6.50 |
| `contacts_outside` | 8 | 100.0% | +6.50 | -6.00 |
| `workload` | 8 | 100.0% | +4.25 | -6.25 |
| `access_needs` | 8 | 100.0% | +6.50 | -6.75 |

## Paired SolverPolicy & Baseline Parity vs TemplateProvider

| Tier | Seed | Template Solver | Persona Solver | Template ObviousHeuristic | Persona ObviousHeuristic | DoNothing | Env Stego Leaks |
|---|---:|---:|---:|---:|---:|---:|---:|
| `hard` | 1 | +0.6900 (d7, ok) | +0.6900 (d7, ok) | -1.0000 (d11, wrong) | -1.0000 (d11, wrong) | +0.0000 | 0 |
| `hard` | 2 | +0.5800 (d9, ok) | +0.7200 (d5, ok) | -1.0000 (d11, wrong) | -1.0000 (d11, wrong) | +0.0000 | 0 |
| `hard` | 3 | +0.2800 (d18, ok) | +0.2800 (d18, ok) | -1.0000 (d11, wrong) | -1.0000 (d11, wrong) | +0.0000 | 0 |
| `hard` | 4 | +0.7300 (d5, ok) | +0.7300 (d5, ok) | -1.0000 (d11, wrong) | -1.0000 (d11, wrong) | +0.0000 | 0 |

- Overall `TemplateProvider` SolverPolicy mean: `+0.5700` (acc `100.0%`)
- Overall `PersonaInterviewProvider` SolverPolicy mean: `+0.6050` (acc `100.0%`, delta `+0.0350`)
- SolverPolicy vs ObviousHeuristic gap: `+1.6050` (`parity_ok=True`)

## Sample Persona-Conditioned Interviews

### `hard` seed `1` (Nordlys Systems)

- `e01` (Venla Nieminen, analyst, Finance, tone=`formal`, topic=`recent_documents`, signal=`evasive`): It is hard to say offhand which specific files I reviewed today, as I primarily kept to the usual routine with our forecasting spreadsheets.
- `e01` (Venla Nieminen, analyst, Finance, tone=`formal`, topic=`recent_documents`, signal=`cooperative`): Today I reviewed the Project Tundra roadmap and Acquisition target memo: Falcon to align our quarterly cost models and variance reports with upcoming milestones. Everything was accessed strictly for standard Finance budget tracking. I am happy to pull my access logs or have my manager confirm these assignments.

### `hard` seed `2` (Kestrel Labs)

- `e02` (Noora Turunen, sales ops, Sales, tone=`upbeat`, topic=`recent_documents`, signal=`evasive`): Honestly, it is hard to say offhand because I click through so many pipeline files while keeping our CRM tidy! It has really just been the usual routine today.
- `e02` (Noora Turunen, sales ops, Sales, tone=`upbeat`, topic=`recent_documents`, signal=`cooperative`): I have been busy keeping our CRM pipeline clean today, so I reviewed the Q3 pricing strategy and the Sales reorg proposal to keep our territory routing aligned with the account teams! I am always happy to pull my access logs or have my manager confirm my workflow.

### `hard` seed `3` (Nordlys Systems)

- `e03` (Emma Niemi, paralegal, Legal, tone=`warm`, topic=`recent_documents`, signal=`evasive`): I appreciate you checking in, though I honestly can't recall offhand which specific files crossed my desk today - it has mostly been just the usual routine checklists.
- `e03` (Emma Niemi, paralegal, Legal, tone=`warm`, topic=`recent_documents`, signal=`cooperative`): I spent this morning updating our cross-team checklists alongside the Q2 pricing strategy and the Acquisition target memo: Kivi so our filing schedules stay right on track. Everything went smoothly with the commercial teams, and I am always happy to pull my access logs or forward the threads if that helps!

### `hard` seed `4` (Aurora Freight)

- `e04` (Kalle Korhonen, research lead, Research, tone=`warm`, topic=`recent_documents`, signal=`evasive`): Thanks for checking in, though I cannot recall offhand since it has mostly been just the usual routine notes around our chamber schedules.
- `e04` (Kalle Korhonen, research lead, Research, tone=`warm`, topic=`recent_documents`, signal=`cooperative`): I spent a productive morning organizing our chamber schedules and reading through the Project Glacier security review to keep our thermal packaging trials aligned. I am always glad to help out, and I am happy to pull my access logs or share my calendar anytime.

## Reproduction

```bash
PYTHONPATH=. python -m canary.gemini.interview_interrogator --llm gemini:gemini-4-carbon --specs hard:1,hard:2,hard:3,hard:4 --worlds-dir /tmp/opencode/w1-worlds --jobs 6 --out results/gemini_roles/world_text/persona-interviews-hard14-carbon
```
