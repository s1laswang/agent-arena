# Role 1 (world_text): gemini-4-carbon Thinking-Level Calibration

- Scope: demo/research layer (v1.5 candidate), not part of the judged v1.4 environment

- Role / Subrole: `world_text` / `thinking_level_calibration`
- Model ID: `gemini-4-carbon` (`feature=worldtext_thinking`)
- Commit: `dbe9569fcc44abf8bc0665e0533dd1d1b677c6e9`
- Timestamp: `2026-11-14T17:15:57Z`
- Tier / Seeds / Levels: `medium` (`v1.4`), seeds `[6, 7]`, levels `['low', 'medium', 'high']` (`count=6`)
- Non-Leak & Safety: `truth_leak_violations=0`, `lint_violations=0`, `leak_encoding_violations=0` across `37` encodings
- SolverPolicy Parity: `ok=True` (`TemplateProvider` mean `+0.8050`, cross-level spread `0.0000`, accuracy `100%` across all arms)
- Total Usage: `24` calls, `24102` in, `14232` out, `42377` thinking, `80711` total tokens, `866.12s`, `$0.614294`

## Thinking-Level Calibration Matrix (Seeds [6, 7])

| Thinking Level | LLM OK | LLM Personas | Fallbacks | Mean TTR | Distinct Bigrams | Tone Entropy (bits) | Thinking Tokens | Output Tokens | Latency (s) | Cost (USD) | Solver Score |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `low` | `100%` (`2/2`) | `20/20` | `0` | `0.6602` | `1178` | `2.7955` | `0` | `4668` | `127.08` | `$0.062748` | `+0.7800` |
| `medium` | `100%` (`2/2`) | `20/20` | `0` | `0.6671` | `1124` | `2.7955` | `3703` | `4307` | `183.11` | `$0.096168` | `+0.7800` |
| `high` | `100%` (`2/2`) | `20/20` | `0` | `0.5543` | `1750` | `2.7955` | `38674` | `5257` | `555.94` | `$0.455378` | `+0.7800` |

## Paired SolverPolicy Score & Accuracy Parity

| Seed | TemplateProvider | `low` | `medium` | `high` | Same Accused | Max Spread |
|---:|---:|---:|---:|---:|---|---:|
| `6` | `+0.7900` (`e17`, d6) | `+0.7900` (`e17`, d6, ok) | `+0.7900` (`e17`, d6, ok) | `+0.7900` (`e17`, d6, ok) | `yes` | `0.0000` |
| `7` | `+0.8200` (`e09`, d7) | `+0.7700` (`e09`, d8, ok) | `+0.7700` (`e09`, d8, ok) | `+0.7700` (`e09`, d8, ok) | `yes` | `0.0500` |

## Non-Leak & Steganographic Audit Summary

- `assert_no_truth` violations: `0`
- `lint_messages` violations: `0`
- `lint_text` violations: `0`
- `canary.gemini.leak_encodings` violations: `0` (`37` encodings checked across WorldText, Day 1 messages, HR interviews, and full episodes)

## Sample Synthesized Outputs Across Thinking Levels
