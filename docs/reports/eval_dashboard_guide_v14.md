# Canary v1.4 Interactive Headline Dashboard & Export Guide

Offline, zero-dependency HTML+SVG+JS explorer (`results/eval_v14/headline_dashboard_v14.html`) built deterministically from the five committed v1.4 evaluation JSON artifacts with zero API calls, zero external URLs, and zero `git` subprocess calls.

## 1. One-Command Build & Byte-Parity Verification

```bash
python scripts/build_eval_dashboard_v14.py
python scripts/build_eval_dashboard_v14.py --check
```

- Output HTML: `results/eval_v14/headline_dashboard_v14.html` (58615 bytes, budget < 60000 bytes, 100% offline self-contained).
- Output Guide: `docs/reports/eval_dashboard_guide_v14.md`.
- Shallow-CI compatible: reads committed JSON files directly via `pathlib` with zero `git` invocations (`--depth=1` safe) and zero timestamps.

## 2. Honest Scope & Provenance Summary (Banner Invariants)

1. **MCP-Only `gemini-4-carbon` Primary Set (Post-Hoc Locked, Not Pre-Registered):**
   - Hard (`n=30`, seeds `0-29`): **65% [24%, 98%]** raw (`+0.322 +/- 0.199` vs solver `+0.499`), **72% [52%, 91%]** luck-adjusted (Wilcoxon `p=0.0221`).
   - Medium (`n=30`, seeds `0-29`): **111% [99%, 127%]** raw, **101% [85%, 119%]** luck-adjusted.
   - Seed lock: commit `671ed96` (28 s after `8fd4dec`), a post-hoc lock against later reruns/cherry-picking rather than a pre-registration.
2. **Harbor 3x10 Container Judge-Path Rehearsal (`afterquery-final` `1bc3e281`, `aa1c679e` / `5f9b3297`):**
   - `opencode-1`: `+0.472` (**93% [20%, 371%]**, `n=10`, `9/10` correct).
   - `opencode-2`: `+0.585` (**116% [78%, 363%]**, `n=10`, `10/10` correct).
   - `opencode-3`: `+0.626` (**131% [86%, 590%]** on `n=9` valid, 1 infra-excluded, `9/9` correct) vs oracle `+0.506` (`do_nothing` / `stop_early` `+0.000`, `0%`).
   - Container shell was used in `20/28` trials -- **the gap did NOT reproduce in the container judge path**.
3. **Pre-Registered Second Frontier Family (`opencode:openai/gpt-5.5`, `cf394894` / `ca0a0dc0`):**
   - Hard (`n=30`, seeds `0-29`, 13 MCP tools only): `+0.504 +/- 0.064`, **101% [79%, 140%]** raw, **84% [67%, 103%]** luck-adjusted (`28/28` accused correct; seeds `0` and `17` wrote text without calling `accuse`, scored `0.0`).
   - Behavioral driver: `gpt-5.5` plants `17.2` canaries/episode vs `8.5` for `gemini-4-carbon` -- **matches solver (no gap)**.

## 3. Source Artifacts & Visual Panels

| Committed Source JSON | Dashboard Component | Key Verified Metric |
|---|---|---|
| `results/eval_v14/headline_gap_table_v14.json` | Paired CI Forest Plot & Interactive Table (Sec A/B1/B2) | Hard MCP carbon `65% [24%, 98%]` raw, `gpt-5.5` `101% [79%, 140%]` raw |
| `results/eval_v14/counterfactual_decomposition_v14.json` | 5-Term Counterfactual Loss Breakdown SVG | Hard MCP carbon gap `+0.177` (`+0.113` cal. wrong-accuse); `gpt-5.5` `-0.005` |
| `results/eval_v14/harness_and_tier_v14.json` | 2x2 Harness x Tier Crossover Summary | Raw DiD `-0.333` (`p=0.0224`), LA DiD `-0.234` (`p=0.0350`) |
| `results/eval_v14/judge_rerun_power_v14.json` | 1x10 vs 3x10 Rerun Operating Characteristics & `pass^3` | Rao-Blackwell `4.22x` 1-run variance reduction (eff. `n=42.2`) |
| `results/eval_v14/paired_seed_diagnostics_v14.json` | Honest Disclosure Banner & Behavioral Diagnostics | Harbor rehearsal `93% / 116% / 131%`, shell in `20/28` trials |

## 4. Interactive Controls & Client-Side Export

- **Tier Filter:** `hard` (default), `medium`, `all` (in-process hard/medium: `95%` / `82%` raw).
- **Metric Toggle (ordered):** `Raw % Solver` (default first), `Luck-Adjusted % Solver` (second), `Winnable %`, `Calibrated pass^3`.
- **Scope & Offline Export:** switch between `Section A` (`n=30` primary paired rows) and `Section A + B1` (`n>=30` replications & ladder), expand `Section B2` (`n<30` directional ladder), and export the active filtered table to CSV or JSON completely offline via `Blob` URLs.
