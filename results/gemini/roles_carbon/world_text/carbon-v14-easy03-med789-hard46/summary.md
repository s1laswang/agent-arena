# Role 1 (world_text): v1.4 Easy 0-3, Medium 7-9, and Hard 4-6 Persona Synthesis

- Scope: demo/research layer (v1.5 candidate), not part of the judged v1.4 environment
- Role / subrole: `world_text` / `company_personas_chatter`
- Model ID: `gemini-4-carbon` | Commit: `6104bebd3f` | Tiers: `v1.4`
- Worlds / personas: `10` worlds, `228` personas (`228` live LLM, `0` fallbacks)
- Non-leak audit: `truth_leak_violations=0`, `lint_violations=0`
- SolverPolicy parity: `+0.7610` vs TemplateProvider `+0.7660` (acc `100.0%`)
- Usage: `52` calls, `61,748` in, `29,038` out, `36,275` thinking (`$0.776626`)

| Tier | Seed | Personas | Truth Leaks | Lint Violations | Template Score | Carbon World Score | Delta | Correct |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `easy` | 0 | 12 | 0 | 0 | +0.7600 | +0.7600 | +0.0000 | `True` |
| `easy` | 1 | 12 | 0 | 0 | +0.8100 | +0.8100 | +0.0000 | `True` |
| `easy` | 2 | 12 | 0 | 0 | +0.7500 | +0.7500 | +0.0000 | `True` |
| `easy` | 3 | 12 | 0 | 0 | +0.8800 | +0.8800 | +0.0000 | `True` |
| `medium` | 7 | 20 | 0 | 0 | +0.8200 | +0.7700 | -0.0500 | `True` |
| `medium` | 8 | 20 | 0 | 0 | +0.8800 | +0.8800 | +0.0000 | `True` |
| `medium` | 9 | 20 | 0 | 0 | +0.8000 | +0.8000 | +0.0000 | `True` |
| `hard` | 4 | 40 | 0 | 0 | +0.7300 | +0.7300 | +0.0000 | `True` |
| `hard` | 5 | 40 | 0 | 0 | +0.5200 | +0.5200 | +0.0000 | `True` |
| `hard` | 6 | 40 | 0 | 0 | +0.7100 | +0.7100 | +0.0000 | `True` |
