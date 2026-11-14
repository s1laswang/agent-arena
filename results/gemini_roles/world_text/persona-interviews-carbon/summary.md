# Role 1 (world_text): Persona-Conditioned HR Interview Engine & Solver Parity

- Role / subrole: `world_text` / `persona_interviews`
- Model ID: `gemini-4-carbon` (`gemini:gemini-4-carbon`)
- Commit: `dbe9569fcc44abf8bc0665e0533dd1d1b677c6e9`
- Timestamp: `2026-11-14T17:14:28+00:00`
- Tiers version: `v1.4` | Worlds: `4` (`medium` seeds 0,1,2 + `hard` seed 0)
- Live interviews generated: `32` (`llm_ok=32`, `fallbacks=0`)
- Non-leak & stego audit: `truth_leak_violations=0`, `lint_violations=0`, `stego_leak_violations=0` across `37` encodings, `prompt_truth_leak_violations=0` (`96` counterfactual mole/decoy swap checks, invariance `100%`)
- Signal calibration: blind accuracy `100.0%`, pairwise cooperative > evasive ordering `100.0%`, mean margin `+13.38`
- Token usage: `32` calls, `31496` in, `2345` out, `6957` thinking, `40798` total tokens (`$0.156012` est., `85.50s`)

## Linguistic Signal Calibration (Evasive vs Cooperative)

| Metric | Cooperative | Evasive |
|---|---:|---:|
| Sample count | 16 | 16 |
| Mean linguistic stance score | +6.19 | -7.19 |
| Specificity / verification rate | 100.0% | 0.0% |
| Hedging / deflection rate | 0.0% | 100.0% |
| Mean word count | 47.7 | 24.1 |

### Topic Breakdown

| Topic | Samples | Blind Signal Acc | Cooperative Score | Evasive Score |
|---|---:|---:|---:|---:|
| `recent_documents` | 8 | 100.0% | +5.50 | -7.50 |
| `contacts_outside` | 8 | 100.0% | +6.50 | -6.50 |
| `workload` | 8 | 100.0% | +5.50 | -7.25 |
| `access_needs` | 8 | 100.0% | +7.25 | -7.50 |

## Paired SolverPolicy & Baseline Parity vs TemplateProvider

| Tier | Seed | Template Solver | Persona Solver | Template ObviousHeuristic | Persona ObviousHeuristic | DoNothing | Env Stego Leaks |
|---|---:|---:|---:|---:|---:|---:|---:|
| `medium` | 0 | +0.7400 (d7, ok) | +0.7500 (d6, ok) | -1.0000 (d11, wrong) | -1.0000 (d11, wrong) | +0.0000 | 0 |
| `medium` | 1 | +0.3900 (d14, ok) | +0.3900 (d14, ok) | -1.0000 (d11, wrong) | -1.0000 (d11, wrong) | +0.0000 | 0 |
| `medium` | 2 | +0.8000 (d5, ok) | +0.8000 (d5, ok) | -1.0000 (d11, wrong) | -1.0000 (d11, wrong) | +0.0000 | 0 |
| `hard` | 0 | +0.6400 (d9, ok) | +0.6400 (d9, ok) | -1.0000 (d11, wrong) | -1.0000 (d11, wrong) | +0.0000 | 0 |

- Overall `TemplateProvider` SolverPolicy mean: `+0.6425` (acc `100.0%`)
- Overall `PersonaInterviewProvider` SolverPolicy mean: `+0.6450` (acc `100.0%`, delta `+0.0025`)
- SolverPolicy vs ObviousHeuristic gap: `+1.6450` (`parity_ok=True`)

## Sample Persona-Conditioned Interviews

### `medium` seed `0` (Kestrel Labs)

- `e00` (Sanna Virtanen, tech lead, Engineering, tone=`dry`, topic=`recent_documents`, signal=`evasive`): Hard to say offhand since I mostly stick to backend wiki specs and code reviews. It is just the usual routine, and I don't really keep track.
- `e00` (Sanna Virtanen, tech lead, Engineering, tone=`dry`, topic=`recent_documents`, signal=`cooperative`): Aside from updating backend architecture notes in our shared Engineering wikis, I reviewed Acquisition target memo: Northstar and Q2 Sales budget forecast today to assess potential infrastructure capacity needs. Everything followed standard read permissions, and I am happy to pull my access logs if you need the exact timestamps.

### `medium` seed `1` (Nordlys Systems)

- `e01` (Laura Lehtinen, accountant, Finance, tone=`dry`, topic=`recent_documents`, signal=`evasive`): I can't recall offhand beyond the usual routine reconciliations and payable spreadsheets. Everything tends to blur together once the monthly schedule starts.
- `e01` (Laura Lehtinen, accountant, Finance, tone=`dry`, topic=`recent_documents`, signal=`cooperative`): Today I reviewed Q3 pricing strategy and Engineering reorg proposal to verify the numbers against our monthly Finance reconciliation spreadsheets. Tidy audit trails matter more than excitement in accounts payable, so I am happy to pull my access logs if you want to verify timestamps.

### `medium` seed `2` (Aurora Freight)

- `e02` (Olli Niemi, account exec, Sales, tone=`upbeat`, topic=`recent_documents`, signal=`evasive`): Honestly, I can't recall offhand with how fast we prep shipper demos, so it has mostly been just the usual routine Sales files today!
- `e02` (Olli Niemi, account exec, Sales, tone=`upbeat`, topic=`recent_documents`, signal=`cooperative`): Today I opened "Project Falcon security review" and "Acquisition target memo: Polaris" while prepping tailored platform demos and syncing on our regional logistics pipeline! We always prioritize clear visibility in Sales, so I am happy to pull my access logs or have my manager confirm my workflow anytime.

### `hard` seed `0` (Nordlys Systems)

- `e00` (Janne Nieminen, senior engineer, Engineering, tone=`dry`, topic=`recent_documents`, signal=`evasive`): Can't recall offhand what I opened today. Mostly it is just the usual routine with backend design notes, as I don't really keep track.
- `e00` (Janne Nieminen, senior engineer, Engineering, tone=`dry`, topic=`recent_documents`, signal=`cooperative`): Today I opened "Board deck draft Q1" and "Q3 pricing strategy" while checking projected distributed storage capacity for our backend pipelines. Everything else was standard Engineering architecture design docs and peer review comments. I am happy to pull my access logs if you want the exact timestamps.

## Reproduction

```bash
PYTHONPATH=. python -m canary.gemini.interview_interrogator --llm gemini:gemini-4-carbon --specs medium:0,medium:1,medium:2,hard:0 --jobs 6 --out results/gemini_roles/world_text/persona-interviews-carbon
```
