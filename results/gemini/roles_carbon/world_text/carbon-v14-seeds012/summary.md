# Role 1 (world_text): v1.4 Medium 0-2 and Hard 0-1 Persona Synthesis

- Scope: demo/research layer (v1.5 candidate), not part of the judged v1.4 environment
- Role / subrole: `world_text` / `company_personas_chatter`
- Model ID: `gemini-4-carbon` | Commit: `c82f27a737` | Tiers: `v1.4`
- Worlds / personas: `5` worlds, `140` personas (`140` live LLM, `0` fallbacks)
- Non-leak audit: `truth_leak_violations=0`, `lint_violations=0`
- SolverPolicy parity: `+0.6540` vs TemplateProvider `+0.6520` (acc `100.0%`)
- Usage: `27` calls, `35,047` in, `15,028` out, `21,899` thinking (`$0.439364`)

| Tier | Seed | Personas | Truth Leaks | Lint Violations | Template Score | Carbon World Score | Delta | Correct |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `medium` | 0 | 20 | 0 | 0 | +0.7400 | +0.7500 | +0.0100 | `True` |
| `medium` | 1 | 20 | 0 | 0 | +0.3900 | +0.3900 | +0.0000 | `True` |
| `medium` | 2 | 20 | 0 | 0 | +0.8000 | +0.8000 | +0.0000 | `True` |
| `hard` | 0 | 40 | 0 | 0 | +0.6400 | +0.6400 | +0.0000 | `True` |
| `hard` | 1 | 40 | 0 | 0 | +0.6900 | +0.6900 | +0.0000 | `True` |
