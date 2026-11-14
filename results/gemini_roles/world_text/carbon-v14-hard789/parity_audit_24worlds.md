# Unified 24-World 3-Tier Non-Leak and SolverPolicy Parity Audit

- Status: **PASS**
- Model ID: `gemini-4-carbon`
- Canary Tiers Version: `v1.4`
- Corpus Worlds Audited: `24` (`easy=4`, `medium=10`, `hard=10`)
- Total Personas Audited: `648` across `24` `.worldtext.json` and `24` `.text.json` files
- Non-Leak Status: `pass` (`truth_violations=0`, `lint_violations=0`, `leak_encoding_violations=0`, `messages_checked=2791`, `interviews_checked=5184`)
- Encoding Detectors Checked: `37` (`leak_encodings.scan_text_for_secret` violations=`0`)
- Pooled SolverPolicy Parity: `pass` (`template_catch_rate=1.0000`, `world_catch_rate=0.9583`, `catch_diff=-0.0417`, `template_mean_score=+0.6958`, `world_mean_score=+0.6750`, `mean_score_diff=-0.0208`, `exact_match_rate=0.8333`)

## Source Corpus Directories

- `results/gemini_roles/world_text/carbon-v14-seeds012/worlds`
- `results/gemini_roles/world_text/carbon-v14-seeds3456-hard23/worlds`
- `results/gemini_roles/world_text/carbon-v14-easy03-med789-hard46/worlds`
- `results/gemini_roles/world_text/carbon-v14-hard789/worlds`

## Per-Tier Non-Leak and SolverPolicy Parity Summary

| Tier | Seeds (n) | Personas | Truth Errs | Lint Errs | Encoding Hits | Text Probe | Probe p-val | Template Catch | World Catch | Template Score | World Score | Score Diff | Exact Match | Status |
|---|---:|---:|---:|---:|---:|---|---:|---:|---:|---:|---:|---:|---:|---|
| `easy` | `4` | `48` | `0` | `0` | `0` | `0/4` | `1.0000` | `1.0000` | `1.0000` | `+0.8000` | `+0.8000` | `+0.0000` | `1.0000` | **PASS** |
| `medium` | `10` | `200` | `0` | `0` | `0` | `1/10` | `0.5351` | `1.0000` | `0.9000` | `+0.7300` | `+0.6660` | `-0.0640` | `0.7000` | **PASS** |
| `hard` | `10` | `400` | `0` | `0` | `0` | `0/10` | `1.0000` | `1.0000` | `1.0000` | `+0.6200` | `+0.6340` | `+0.0140` | `0.9000` | **PASS** |

## Per-World 24-World Breakdown

| Tier | Seed | Personas | Truth OK | Lint OK | Stego Clean | Template Score | World Score | Score Diff | World Correct | Source Artifact |
|---|---:|---:|---|---|---|---:|---:|---:|---|---|
| `easy` | `0` | `12` | `True` | `True` | `True` | `+0.7600` | `+0.7600` | `+0.0000` | `True` | `results/gemini_roles/world_text/carbon-v14-easy03-med789-hard46/worlds/easy/0.worldtext.json` |
| `easy` | `1` | `12` | `True` | `True` | `True` | `+0.8100` | `+0.8100` | `+0.0000` | `True` | `results/gemini_roles/world_text/carbon-v14-easy03-med789-hard46/worlds/easy/1.worldtext.json` |
| `easy` | `2` | `12` | `True` | `True` | `True` | `+0.7500` | `+0.7500` | `+0.0000` | `True` | `results/gemini_roles/world_text/carbon-v14-easy03-med789-hard46/worlds/easy/2.worldtext.json` |
| `easy` | `3` | `12` | `True` | `True` | `True` | `+0.8800` | `+0.8800` | `+0.0000` | `True` | `results/gemini_roles/world_text/carbon-v14-easy03-med789-hard46/worlds/easy/3.worldtext.json` |
| `medium` | `0` | `20` | `True` | `True` | `True` | `+0.7400` | `+0.7500` | `+0.0100` | `True` | `results/gemini_roles/world_text/carbon-v14-seeds012/worlds/medium/0.worldtext.json` |
| `medium` | `1` | `20` | `True` | `True` | `True` | `+0.3900` | `+0.3900` | `+0.0000` | `True` | `results/gemini_roles/world_text/carbon-v14-seeds012/worlds/medium/1.worldtext.json` |
| `medium` | `2` | `20` | `True` | `True` | `True` | `+0.8000` | `+0.8000` | `+0.0000` | `True` | `results/gemini_roles/world_text/carbon-v14-seeds012/worlds/medium/2.worldtext.json` |
| `medium` | `3` | `20` | `True` | `True` | `True` | `+0.6000` | `+0.0000` | `-0.6000` | `False` | `results/gemini_roles/world_text/carbon-v14-seeds3456-hard23/worlds/medium/3.worldtext.json` |
| `medium` | `4` | `20` | `True` | `True` | `True` | `+0.6900` | `+0.6900` | `+0.0000` | `True` | `results/gemini_roles/world_text/carbon-v14-seeds3456-hard23/worlds/medium/4.worldtext.json` |
| `medium` | `5` | `20` | `True` | `True` | `True` | `+0.7900` | `+0.7900` | `+0.0000` | `True` | `results/gemini_roles/world_text/carbon-v14-seeds3456-hard23/worlds/medium/5.worldtext.json` |
| `medium` | `6` | `20` | `True` | `True` | `True` | `+0.7900` | `+0.7900` | `+0.0000` | `True` | `results/gemini_roles/world_text/carbon-v14-seeds3456-hard23/worlds/medium/6.worldtext.json` |
| `medium` | `7` | `20` | `True` | `True` | `True` | `+0.8200` | `+0.7700` | `-0.0500` | `True` | `results/gemini_roles/world_text/carbon-v14-easy03-med789-hard46/worlds/medium/7.worldtext.json` |
| `medium` | `8` | `20` | `True` | `True` | `True` | `+0.8800` | `+0.8800` | `+0.0000` | `True` | `results/gemini_roles/world_text/carbon-v14-easy03-med789-hard46/worlds/medium/8.worldtext.json` |
| `medium` | `9` | `20` | `True` | `True` | `True` | `+0.8000` | `+0.8000` | `+0.0000` | `True` | `results/gemini_roles/world_text/carbon-v14-easy03-med789-hard46/worlds/medium/9.worldtext.json` |
| `hard` | `0` | `40` | `True` | `True` | `True` | `+0.6400` | `+0.6400` | `+0.0000` | `True` | `results/gemini_roles/world_text/carbon-v14-seeds012/worlds/hard/0.worldtext.json` |
| `hard` | `1` | `40` | `True` | `True` | `True` | `+0.6900` | `+0.6900` | `+0.0000` | `True` | `results/gemini_roles/world_text/carbon-v14-seeds012/worlds/hard/1.worldtext.json` |
| `hard` | `2` | `40` | `True` | `True` | `True` | `+0.5800` | `+0.7200` | `+0.1400` | `True` | `results/gemini_roles/world_text/carbon-v14-seeds3456-hard23/worlds/hard/2.worldtext.json` |
| `hard` | `3` | `40` | `True` | `True` | `True` | `+0.7200` | `+0.7200` | `+0.0000` | `True` | `results/gemini_roles/world_text/carbon-v14-seeds3456-hard23/worlds/hard/3.worldtext.json` |
| `hard` | `4` | `40` | `True` | `True` | `True` | `+0.7300` | `+0.7300` | `+0.0000` | `True` | `results/gemini_roles/world_text/carbon-v14-easy03-med789-hard46/worlds/hard/4.worldtext.json` |
| `hard` | `5` | `40` | `True` | `True` | `True` | `+0.5200` | `+0.5200` | `+0.0000` | `True` | `results/gemini_roles/world_text/carbon-v14-easy03-med789-hard46/worlds/hard/5.worldtext.json` |
| `hard` | `6` | `40` | `True` | `True` | `True` | `+0.7100` | `+0.7100` | `+0.0000` | `True` | `results/gemini_roles/world_text/carbon-v14-easy03-med789-hard46/worlds/hard/6.worldtext.json` |
| `hard` | `7` | `40` | `True` | `True` | `True` | `+0.6400` | `+0.6400` | `+0.0000` | `True` | `results/gemini_roles/world_text/carbon-v14-hard789/worlds/hard/7.worldtext.json` |
| `hard` | `8` | `40` | `True` | `True` | `True` | `+0.2600` | `+0.2600` | `+0.0000` | `True` | `results/gemini_roles/world_text/carbon-v14-hard789/worlds/hard/8.worldtext.json` |
| `hard` | `9` | `40` | `True` | `True` | `True` | `+0.7100` | `+0.7100` | `+0.0000` | `True` | `results/gemini_roles/world_text/carbon-v14-hard789/worlds/hard/9.worldtext.json` |
