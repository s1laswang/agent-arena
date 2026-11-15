# Final Canary v1.4 Make-Hunt, Held-Out 5000-5099 Random/Evolve/Malformed/Race Sweep, and Anticheat Round-Trip Audit

## 1. Scope, Post-Hoc Lock Alignment, and Headline Verdict

- **Base commits audited:** `origin/fr8/canary/integrity@8302df7a` synced with `origin/justSilas@5f9b3297` (including `aa1c679e` rehearsal run 3 final `131%` across `9` valid trials and `1bc3e281` `ToolResult.data["detail"]` error contracts). Zero protected or Silas-owned files (`canary/`, `harbor/`, `Makefile`, `configs/`, `data/runs/committed/`) were modified.
- **Zero-LLM / Disk-Clean Execution:** `scripts/integrity_final_make_hunt_v14.py` executes 100% locally on CPU (`0` live Gemini, OpenAI, or external network API calls), writes temporary shards exclusively to `/tmp/opencode/w2_final_make_hunt_v14`, and cleans up scratch artifacts after verification.
- **Panel Fix A + D Alignment:** Canary `v1.4` (`TIERS_VERSION = "v1.4"`, `KNOWN_V_MODE = True`, tier hash `a8f99c2537c91d72`, `v1.3` hash `8df71cf570bb48bc`) leads its `hard` headline gap with raw `65% [24%, 98%]` (`+0.322` vs `SolverPolicy` `+0.499` on `seeds 0-29`) before luck-adjusted `72% [52%, 91%]`; dev seeds `0-29` are a **post-hoc lock** (locked after the primary run in `671ed96`, `28s` after `8fd4dec`); and the `hard` canary clearance rule never binds (`W4`).
- **Grand Total Execution (`final_make_hunt_v14_summary.json`):**
  - **`17,103` real `Env` episodes and `363,233` `Env.call` evaluations** in `62.371s` (`jobs = 2`, `all_passed = True`):
    1. **4-Track `make hunt` (`easy`, `medium`, `hard`, `hard_forge` on `seeds 0-49`) + 2-Track Held-Out (`hard`, `hard_forge` on `seeds 5000-5099`):** `11,988` fuzz genomes (`3,996` `random` + `3,996` `malformed` + `3,996` `evolve` from `12,000` requested budget) + `400` 8-thread `parallel_accuse` barrier races (`3,200` concurrent `accuse` thread calls) across `14,218` fuzz episodes and `352,000` `Env.call`s -> **`0.000` best non-solver score**, **`0` `fuzz` invariant violations**, and **`0` `strict_v14` post-episode violations**.
    2. **Full 400-Pair Mole-vs-Innocent Parity Sweep (`run_full_seed_parity_audit`):** Probed all `400` `(tier, seed)` pairs across all `6` cells (`2,800` episodes, `6,800` `Env.call`s), closing the `seeds[:5]` sampling gap in `fuzz.search` -> **`0` `parity_leak` violations** and **`0` `strict_v14` violations**.
    3. **Committed `results/anticheat/exploits.json` + Live Round-Trip & Tamper Control (`run_anticheat_verification`):** Verified all `99` committed anti-cheat rows across `40` judge seeds (`900000-900039`) x `3` tiers (`all_blocked = True`, `world_secret_fingerprint = "ffc2a4c7ae42"`), `1,051 / 1,061` step-replayed episodes (`53,889` steps, `0` step mismatches), and `80 / 80` Harbor trials + `18 / 18` Harbor job summaries; reran `66` rows (`2` seeds x `2` tiers) end-to-end via `anticheat.verify_artifact` (`rc = 0`, `0` differences) plus a tampered-mean positive control (`rc = 1`, `1` difference caught).
    4. **`PlantedBugFakeEnv` Positive-Control Battery (`run_fake_env_positive_controls`):** `0` false positives on clean `PlantedBugFakeEnv`, **`6 / 6` (`100%`)** planted bug classes caught (`accuse_twice`, `truth_leak`, `parity_leak`, `unhandled_exception`, `wrong_accusation_positive`, `parallel_accuse_race`), plus **`116` `strict_v14_wrong_accuse_not_minus_one` violations** caught on `wrong_accusation_zero` where legacy `fuzz.score_invariants` stayed silent (`0` caught).
  - **Report-Only Issues Logged (`3` non-exploit harness findings, `0` protected-path edits):** `ISSUE-W2-FUZZ-ALL-BUDGET-TRUNCATION-AND-SHARED-RNG` (`low`), `ISSUE-W2-FUZZ-LEGACY-V0-ZERO-SCORE-INVARIANT-GAP` (`low`), and `ISSUE-W2-MAKE-HUNT-DEFAULT-OUT-DIR-ACCUMULATION` (`advisory`).

## 2. Keyless Reproduce Commands (0 API Calls)

```bash
PYTHONPATH=. /tmp/fleet-silas/shared/agent-arena-venv/bin/python -m pytest -p no:cacheprovider -q tests/test_integrity_final_make_hunt_v14.py

PYTHONPATH=. /tmp/fleet-silas/shared/agent-arena-venv/bin/python scripts/integrity_final_make_hunt_v14.py --quick --out-dir /tmp/opencode/w2_quick_check --check-report docs/reports/integrity_final_make_hunt_v14.md

PYTHONPATH=. /tmp/fleet-silas/shared/agent-arena-venv/bin/python scripts/integrity_final_make_hunt_v14.py --jobs 2 --out-dir /tmp/opencode/w2_final_make_hunt_v14 --check-report docs/reports/integrity_final_make_hunt_v14.md
```

## 3. Six-Cell `make hunt` (`0-49`) and Held-Out (`5000-5099`) Fuzz Matrix

| Cell ID | Group | Track | Seeds (`n`) | Staff / Days / Canaries / Cap | Genomes (`Req`) | 8-Thread Races | Fuzz Eps | Fuzz `Env.call`s | Best Non-Solver | Best Score/Call | Solver Mean (`Acc`, `n`) | Violations (`Fuzz / Strict`) | CPU (s) |
|---|---|---|---:|---|---:|---:|---:|---:|---:|---:|---|---:|---:|
| `make_hunt_easy_0_49` | `make_hunt` | `easy` | `0-49` (`50`) | `12 / 14 / 1 / 300` | `1,998` (`2,000`) | `50` | `2,303` | `62,187` | `0.000` | `0.142857` | `0.7984` (`100.0%`, `n=50`) | `0 / 0` | `11.860` |
| `make_hunt_medium_0_49` | `make_hunt` | `medium` | `0-49` (`50`) | `20 / 14 / 1 / 300` | `1,998` (`2,000`) | `50` | `2,303` | `74,885` | `0.000` | `0.043810` | `0.6114` (`86.0%`, `n=50`) | `0 / 0` | `14.003` |
| `make_hunt_hard_0_49` | `make_hunt` | `hard` | `0-49` (`50`) | `40 / 21 / 2 / 420` | `1,998` (`2,000`) | `50` | `2,303` | `53,452` | `0.000` | `0.125000` | `0.4718` (`92.0%`, `n=50`) | `0 / 0` | `17.248` |
| `make_hunt_hard_forge_0_49` | `make_hunt` | `hard_forge` | `0-49` (`50`) | `40 / 21 / 2 / 420` | `1,998` (`2,000`) | `50` | `2,303` | `54,558` | `0.000` | `0.250000` | `0.6420` (`100.0%`, `n=5`) | `0 / 0` | `16.590` |
| `heldout_hard_5000_5099` | `heldout` | `hard` | `5000-5099` (`100`) | `40 / 21 / 2 / 420` | `1,998` (`2,000`) | `100` | `2,503` | `52,111` | `0.000` | `0.250000` | `0.6120` (`100.0%`, `n=5`) | `0 / 0` | `15.422` |
| `heldout_hard_forge_5000_5099` | `heldout` | `hard_forge` | `5000-5099` (`100`) | `40 / 21 / 2 / 420` | `1,998` (`2,000`) | `100` | `2,503` | `54,807` | `0.000` | `0.094000` | `0.2740` (`60.0%`, `n=5`) | `0 / 0` | `17.949` |
| **Total (`6` cells)** | **Both** | **4 tracks** | **`400` pairs** | **v1.4 (`a8f99c2537c91d72`)** | **`11,988` (`12,000`)** | **`400`** | **`14,218`** | **`352,000`** | **`0.000`** | **`0.250000`** | **dev30 hard `0.4990` (`96.67%`)** | **`0 / 0`** | **`93.072`** |

*Note on `Best Score/Call` (`0.250000`):* Single-episode `score / calls` reaches `0.250000` (`1.0 / 4` calls on `hard_forge 0-49` `random` and `hard 5000-5099` `evolve`) only when a short blind-guess genome happens to accuse the true mole at `1 / 40` odds; wrong accusations score `-1.0` (`EV = -0.9250` on `40`-employee tracks), and `best_non_solver_score == 0.0` across all `6` cells and all `4` modes.

### 3.1 Per-Mode Totals Across All 6 Cells

| Fuzz Mode | Genomes Evaluated | 8-Thread Barrier Races | Episodes | `Env.call`s | Best Non-Solver | Best Score/Call | Fuzz Violations | Strict v1.4 Violations | CPU (s) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `random` | `3,996` | `0` | `4,606` | `121,930` | `0.000` | `0.250000` | `0` | `0` | `37.597` |
| `malformed` | `3,996` | `0` | `4,606` | `120,790` | `0.000` | `0.000000` | `0` | `0` | `20.839` |
| `evolve` | `3,996` | `0` | `4,606` | `105,680` | `0.000` | `0.250000` | `0` | `0` | `32.224` |
| `parallel_accuse` | `0` | `400` | `400` | `3,600` | `0.000` | `0.000000` | `0` | `0` | `2.412` |
| **Total** | **`11,988`** | **`400`** | **`14,218`** | **`352,000`** | **`0.000`** | **`0.250000`** | **`0`** | **`0`** | **`93.072`** |

### 3.2 Full 400-Pair Parity Audit (`run_full_seed_parity_audit`)

- Because `fuzz.search` only runs `parity_probe` on `seeds[:5]` per mode, `run_full_seed_parity_audit` explicitly probed all `400` `(tier, seed)` pairs (`50` each on `easy`, `medium`, `hard`, `hard_forge` `0-49`; `100` each on `hard`, `hard_forge` `5000-5099`), executing **`2,800` episodes** and **`6,800` `Env.call`s** in `3.007s` -> **`0` `parity_leak` violations** and **`0` `strict_v14` violations**.

## 4. Anticheat Artifact & Positive-Control Verification

### 4.1 `results/anticheat/exploits.json` + `verify_artifact` Round-Trip (`7.792s`)

- **Committed artifact (`results/anticheat/exploits.json`):** `99` rows across `40` judge seeds (`900000-900039`) x `3` tiers (`easy`, `medium`, `hard`), `world_secret_public = "canary-anticheat-public-test-v1"` (`ffc2a4c7ae42`), `all_blocked = True`, `replay_all_consistent = True` (`1,051 / 1,061` replayed, `10` expected non-replayable, `53,889` steps, `0` step mismatches), and `harbor_all_consistent = True` (`80 / 80` Harbor trials and `18 / 18` Harbor job summaries consistent).
- **Live round-trip + tamper positive control:** `anticheat.run_and_write(["easy", "medium"], [900000, 900001], ...)` followed by `anticheat.verify_artifact` reran `66` rows across `2` seeds x `2` tiers with **`rc = 0` and `0` differences**, while Perturbing `rows[0]["mean"]` by `+0.125` returned **`rc = 1` with `1` difference caught**.

### 4.2 `PlantedBugFakeEnv` Positive Controls (`6 / 6` Caught + Strict v1.4 Zero-Wrong Oracle, `1.126s`)

| Control Case | Episodes | `Env.call`s | Violations Caught | Best Non-Solver | Violation Kinds | Verdict |
|---|---:|---:|---:|---:|---|---|
| `clean_control` (`bug=None`) | `110` | `2,673` | `0` (`0` strict) | `0.000` | `[]` | **PASS (`0` false positives)** |
| `accuse_twice` | `340` | `12,437` | `1,135` | `1.000` | `parallel_accuse_race, post_end_effect, score_without_correct_accusation, wrong_accusation_positive` | **CAUGHT** |
| `truth_leak` | `160` | `2,396` | `94` | `0.000` | `truth_leak` | **CAUGHT** |
| `parity_leak` | `130` | `1,199` | `12` | `0.000` | `parity_leak` | **CAUGHT** |
| `unhandled_exception` | `160` | `2,282` | `279` | `0.000` | `exception` | **CAUGHT** |
| `wrong_accusation_positive` | `340` | `6,936` | `200` | `0.500` | `score_without_correct_accusation, wrong_accusation_positive` | **CAUGHT** |
| `parallel_accuse_race` | `130` | `1,199` | `4` | `0.000` | `parallel_accuse_race` | **CAUGHT** |
| `wrong_accusation_zero` (`v0` gap) | `340` | `6,936` | `0` fuzz / **`116` strict** | `0.000` | `strict_v14_wrong_accuse_not_minus_one` | **CAUGHT BY STRICT ORACLE** |

## 5. Report-Only Issues (Zero Protected Files Modified)

### 5.1 `ISSUE-W2-FUZZ-ALL-BUDGET-TRUNCATION-AND-SHARED-RNG` (Severity: Low)
- **Locations:** `canary/redteam/fuzz.py:336,347,389-390`, `Makefile:58-59`
- **Finding:** In `mode="all"`, `fuzz.hunt` passes `budget // 3` and the identical `rng_seed=seed` to `random`, `malformed`, and `evolve`. On `Makefile` `make hunt` (`4 x 20,000 = 80,000` requested), integer division executes `79,992` genomes (`8` dropped; `8,000 -> 7,992` in our `make_hunt` group), `evolve`'s first `8` warm-up genomes (`len(pop) < 8`) duplicate `random`'s first `8` genomes verbatim (`shared_rng_warmup_identical = True`), and `parity_probe` repeats `seeds[:5]` `3` times per track while leaving `seeds[5:]` unprobed unless audited separately (covered across all `400` pairs in Section 3.2).

### 5.2 `ISSUE-W2-FUZZ-LEGACY-V0-ZERO-SCORE-INVARIANT-GAP` (Severity: Low)
- **Locations:** `canary/redteam/fuzz.py:191-205`, `canary/rules.py:46`
- **Finding:** `fuzz.score_invariants` retains a `v0` compatibility comment/branch allowing `score == 0.0` on a wrong accusation (`fuzz.score_invariants(0.0, ["e02"], "e01") == []`) and does not flag `len(accusations) > 1` when `score == 0.0` (`fuzz.score_invariants(0.0, ["e01", "e02"], "e03") == []`). Under frozen `v1.4` (`wrong_accusation_score = -1.0`), a wrong accusation scoring `0.0` would make day-1 blind guessing positive-EV (`+1/N`). Our `strict_v14_episode_violations` wrapper caught `116` planted `wrong_accusation_zero` violations in `PlantedBugFakeEnv` and verified **`0` occurrences across all `17,103` real `Env` episodes**.

### 5.3 `ISSUE-W2-MAKE-HUNT-DEFAULT-OUT-DIR-ACCUMULATION` (Severity: Advisory)
- **Locations:** `Makefile:58-59`, `canary/redteam/fuzz.py:446,451-460`
- **Finding:** `make hunt` invokes `python -m canary.redteam.fuzz` without overriding `--out data/runs`, creating `4` timestamped `data/runs/redteam-fuzz-<ts>-<tier>-all/` directories inside the checkout per `make hunt` invocation without automatic cleanup.
