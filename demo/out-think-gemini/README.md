# Out-Think Gemini: Playable Counter-Intelligence Decision Suite

Out-Think Gemini is a zero-key, fully offline playable forensics benchmark built on real `v1.4` Canary counter-intelligence episodes. Step into the investigator's seat at the exact pre-decision turn (`decision_step`), audit the same evidence Gemini saw, make the high-stakes **ACCUSE** vs **HOLD FIRE** call, and compare your score against the exact Bayesian `SolverPolicy` reference and recorded Gemini `thinking_level` runs.

## Judge Quickstart (Offline, Zero API Keys)

No API keys, network access, build step, or external CDN scripts are required.

### Option 1: Open directly in any browser

```bash
open demo/out-think-gemini/index.html
```

On Linux desktops:

```bash
xdg-open demo/out-think-gemini/index.html
```

### Option 2: Serve over local HTTP

```bash
python3 -m http.server 8080 --directory demo/out-think-gemini
```

Then open `http://127.0.0.1:8080/` in your browser.

**Airgapped / Offline Rendering:** `demo/out-think-gemini/cases.js` ships the full verified replay corpus inline (`window.OUTTHINK_DATA`), and `demo/out-think-gemini/scene.js` includes a built-in HTML5 2D Canvas pixel detective stage fallback using local CC0 sprites (`demo/out-think-gemini/assets/`) whenever offline without CDN Phaser.

## How the Game Works

1. **Inspect Pre-Decision Evidence up to `decision_step`:**
   Every scenario freezes a real `v1.4` investigation on `decision_day` at tool step `decision_step` with remaining reward value `V_t` (`value_at_decision`). All post-decision events are stripped so you only see observations available at or before `decision_step`:
   - **Canaries:** planted document traps, recipient lists, and variant mappings.
   - **Leaks:** intercepted external leaks and any exposed watermark/canary signatures.
   - **Access:** badge reader, VPN, and document access logs across suspects.
   - **Comms:** internal chat messages and suspect interview transcripts.
   - **Steps:** the exact sequence of investigator tool calls (`1 .. decision_step`).
2. **Choose ACCUSE vs HOLD FIRE:**
   - **ACCUSE:** select a suspect and accuse immediately. Scoring follows the frozen `v1.4` contract: **`+V_t`** if the suspect is the true mole (`true_mole`), or **`-1.00`** hard penalty for a false accusation.
   - **HOLD FIRE:** keep investigating when no single suspect clears the `SolverPolicy` Bayesian break-even rule:
     ```text
     P(top) >= 1 / (1 + V_t)
     ```
     Because `EV(accuse top) = P(top) * V_t - (1 - P(top))`, accusing below `1 / (1 + V_t)` has strictly negative expected value even before accounting for positive continuation value (`(1 + max(0, EV_hold_fire)) / (1 + V_t)`).
3. **Post-Decision Reveal and Running Scoreboard:**
   - **Bayesian `SolverPolicy` Posterior:** reveals the exact per-suspect posterior distribution, `top_prob` vs `break_even_prob`, `recommended_call`, and full-episode `SolverPolicy` outcome (`+7.90` cumulative score, `+0.6583` mean across the `12` cases).
   - **Gemini `thinking_level` Ladder:** reveals every recorded run across `minimal`, `low`, `medium`, `high`, and `xhigh` thinking levels across 6 Gemini models (`gemini-3.1-flash-lite`, `gemini-3.5-flash`, `gemini-3.8-flash`, `gemini-4-hydrogen`, `gemini-4-argon`, `gemini-4-carbon`), with per-run action at `t`, final accusation, score, thinking tokens, and list USD cost.
   - **`gemini-4-carbon` Cross-Model Strip:** shows how `gemini-4-carbon` acted on the identical `(tier, seed)` world alongside the anchor model.

## Verified Corpus Summary (`results/gemini/out_think_gemini.json`)

All metrics below come directly from committed artifacts with zero synthetic or bootstrap fallback data (`isBootstrapFallback: false`):

| Metric | Verified Value | Source / Notes |
|---|---:|---|
| Playable cases | `12` | `meta.case_count` (`6` `hard`, `6` `medium`) |
| Unique `v1.4` dev worlds | `11` | `hard` seeds `1, 3, 4, 7, 18`; `medium` seeds `1, 2, 4, 6, 8, 9` (`0` heldout/judge seeds) |
| Optimal **HOLD FIRE** cases | `8` | `meta.hold_fire_cases` (`P(top) < 1 / (1 + V_t)`) |
| Optimal **ACCUSE** cases | `4` | `meta.accuse_cases` (`P(top) >= 1 / (1 + V_t)`) |
| Case `thinking_level` runs | `39` | `meta.level_run_count` across `minimal`, `low`, `medium`, `high`, `xhigh` |
| Recorded ladder episodes | `550` | `meta.total_episodes` / `results/gemini/ladder_episodes.jsonl.gz` |
| Unique billing ledger runs | `618` | `meta.ledger_unique_runs` / `results/gemini/ladder_ledger.jsonl.gz` |
| Ladder corpus list cost | `$262.71` | `$262.7061` exact (`meta.total_cost_usd` at model list rates) |
| Gemini models covered | `6` | `gemini-3.1-flash-lite`, `gemini-3.5-flash`, `gemini-3.8-flash`, `gemini-4-hydrogen`, `gemini-4-argon`, `gemini-4-carbon` |

### Thinking-Level Progression Across the 12 Cases

Across the `39` recorded thinking-level runs attached to the `12` decision points, mean score rises monotonically with thinking budget as models stop firing below break-even:

| `thinking_level` | Runs (`n`) | Score Sum | Mean Score |
|---|---:|---:|---:|
| `minimal` | `4` | `-2.10` | `-0.5250` |
| `low` | `12` | `-2.84` | `-0.2367` |
| `medium` | `10` | `+3.07` | `+0.3070` |
| `high` | `11` | `+6.74` | `+0.6127` |
| `xhigh` | `2` | `+1.41` | `+0.7050` |

### 12 Playable Scenarios

| Case ID | World (`tier`, `seed`) | Anchor (`model` @ `level`) | Cutoff (`day`, `step`) | `V_t` | Break-Even `1/(1+V_t)` | `SolverPolicy` `P(top)` | Optimal Call |
|---|---|---|---:|---:|---:|---:|---|
| `carbon-hard-1` | `hard`, seed `1` | `gemini-4-carbon` @ `high` | Day `9`, Step `90` | `0.71` | `0.5848` | `0.9769` | `accuse` |
| `flash-lite-hard-4` | `hard`, seed `4` | `gemini-3.1-flash-lite` @ `minimal` | Day `6`, Step `49` | `0.83` | `0.5464` | `0.1520` | `hold_fire` |
| `flash38-hard-7` | `hard`, seed `7` | `gemini-3.8-flash` @ `low` | Day `6`, Step `33` | `0.79` | `0.5587` | `0.3646` | `hold_fire` |
| `carbon-medium-4` | `medium`, seed `4` | `gemini-4-carbon` @ `high` | Day `8`, Step `75` | `0.73` | `0.5780` | `1.0000` | `accuse` |
| `flash-lite-medium-1` | `medium`, seed `1` | `gemini-3.1-flash-lite` @ `minimal` | Day `4`, Step `26` | `0.88` | `0.5319` | `0.2107` | `hold_fire` |
| `hydrogen-hard-3` | `hard`, seed `3` | `gemini-4-hydrogen` @ `low` | Day `18`, Step `43` | `0.50` | `0.6667` | `0.0998` | `hold_fire` |
| `flash38-medium-9` | `medium`, seed `9` | `gemini-3.8-flash` @ `low` | Day `8`, Step `60` | `0.70` | `0.5882` | `0.2530` | `hold_fire` |
| `flash35-hard-1` | `hard`, seed `1` | `gemini-3.5-flash` @ `minimal` | Day `14`, Step `68` | `0.50` | `0.6667` | `0.9990` | `accuse` |
| `argon-hard-18` | `hard`, seed `18` | `gemini-4-argon` @ `low` | Day `19`, Step `115` | `0.34` | `0.7463` | `0.4616` | `hold_fire` |
| `argon-medium-6` | `medium`, seed `6` | `gemini-4-argon` @ `high` | Day `7`, Step `64` | `0.82` | `0.5495` | `1.0000` | `accuse` |
| `hydrogen-medium-2` | `medium`, seed `2` | `gemini-4-hydrogen` @ `medium` | Day `14`, Step `90` | `0.56` | `0.6410` | `0.5248` | `hold_fire` |
| `flash35-medium-8` | `medium`, seed `8` | `gemini-3.5-flash` @ `low` | Day `14`, Step `83` | `0.62` | `0.6173` | `0.3485` | `hold_fire` |

## Provenance Pointers

- `canary/gemini/outthink.py` - deterministic, keyless builder and `--check` verifier that replays pre-decision trajectories through `Env` and `SolverPolicy` to emit the JSON and JS bundles.
- `results/gemini/out_think_gemini.json` - canonical structured corpus (`12` cases, `39` thinking-level runs, `SolverPolicy` posteriors, and `gemini-4-carbon` cross-model rows).
- `demo/out-think-gemini/cases.js` - offline browser/CommonJS data bundle (`window.OUTTHINK_DATA`) synced 1:1 with `results/gemini/out_think_gemini.json`.
- `results/gemini/ladder_episodes.jsonl.gz` and `results/gemini/ladder_ledger.jsonl.gz` - source `550` recorded ladder episodes and `618` billing ledger runs (`$262.71` list USD).
- `data/runs/committed/v1.4/reference` - committed `SolverPolicy` reference episodes on `v1.4`.
- `docs/demo/ASSETS.md` - CC0-1.0 pixel-art sprite provenance and license audit for `demo/out-think-gemini/assets/`.

## Keyless Verification

Verify byte-level artifact sync and full schema/provenance/README checks with zero API keys:

```bash
PYTHONPATH=. python -m canary.gemini.outthink --check
pytest -q tests/test_gemini_lab_outthink.py tests/test_outthink_demo_readme.py
```

To force a strictly key-stripped environment:

```bash
GEMINI_API_KEY="" GOOGLE_API_KEY="" PYTHONPATH=. pytest -q tests/test_gemini_lab_outthink.py tests/test_outthink_demo_readme.py
```
