# Canary: One-Page Judge Quickstart

**Submission:** AfterQuery "Break the Agent" (branch `justSilas`) | **Frozen rules:** `TIERS_VERSION="v1.4"` (SHA-256 prefix `a8f99c2537c91d72` in [`canary/rules.py`](canary/rules.py)) | **Deep guide:** [`docs/JUDGE-WALKTHROUGH.md`](docs/JUDGE-WALKTHROUGH.md)

## 1. Headline Claim & Honest Disclosures (Rules v1.4, Paired Dev Seeds 0-29)

On Canary's `hard` tier (`n=30` pre-registered dev seeds `0-29`, paired on identical worlds with the Bayesian reference solver, 100% replay-verified in [`paired_table_gemini.md`](data/runs/committed/v1.4/paired_table_gemini.md)):

| Cell (Rules v1.4) | n | Agent +/- 95% CI | Solver +/- 95% CI | Raw / Solver [95% CI] | Luck-Adj. / Solver [95% CI] |
|---|---:|---:|---:|---:|---:|
| **OpenCode + `google/gemini-4-carbon` over MCP (`hard`, headline)** | **30** | **`+0.322 +/- 0.199`** | **`+0.499 +/- 0.119`** | **`65% [24%, 98%]`** | **`72% [52%, 91%]`** (`+0.360`) |
| In-process `gemini-4-carbon` (`hard`, parity disclosure) | 30 | `+0.473 +/- 0.118` | `+0.499 +/- 0.119` | `95% [62%, 140%]` | `84% [65%, 106%]` (`+0.421`) |
| OpenCode + `google/gemini-4-carbon` over MCP (`medium`, parity disclosure) | 30 | `+0.713 +/- 0.042` | `+0.645 +/- 0.087` | `111% [99%, 127%]` | `101% [85%, 119%]` (`+0.652`) |

- **Zero & random baselines:** `do_nothing = stop_early = cheat_probe = +0.000` exact ([`results/judge_table.md`](results/judge_table.md)); day-1 random accusation `guess_day1` on `hard` averages **`-0.95`** (`-0.953`, [`guess_day1_hard_judge40.md`](results/solver_range/guess_day1_hard_judge40.md)).
- **Why luck-adjustment matters:** Each accusation is scored by exact posterior EV `P * V - (1 - P)` (`0` if abstaining) under the solver's posterior at the moment of accusation, separating decision quality from coin-flip outcome variance.

## 2. 60-Second Keyless Reproduction (No API Keys, No Docker)

Requires `uv` and GNU `make` on Linux or macOS. Scratch outputs go only to gitignored `results/latest/`:

```bash
make setup && make reproduce
make accept
uv run python scripts/paired_gemini.py --version v1.4 --seeds 0-29
uv run python scripts/demo_replay.py --seed 4 --verify
uv run python scripts/failure_analysis_v14.py --check
make anticheat-verify
make game-serve
```

- `make setup && make reproduce` (`~1 min`): replays committed frontier runs (`+0.322 +/- 0.199` hard), plays solver + 6 baselines on 40 judge seeds (`900000-900039`), and runs the anti-cheat gate (`REPRO_ANTICHEAT=0 make reproduce` runs table-only in `~10s`; `CANARY_WORLD_SECRET=<str> make reproduce` gives bit-identical output).
- `make accept` (`~2 min -> RESULT: PASS`): asserts `do_nothing` and `stop_early` = `+0.000`, checks `solver` and `guess_day1` against 300-secret `+/- 4 SD` bands, and runs a live HTTP MCP smoke test.
- `uv run python scripts/paired_gemini.py --version v1.4 --seeds 0-29` (`~14s`): recomputes the v1.4 paired 10,000-resample bootstrap gap table from committed trajectories.
- `uv run python scripts/demo_replay.py --seed 4 --verify` (`<1s`): replays hard seed `4` in a fresh `Env` (`solver +0.73 -> MATCH` day 5 vs `gemini +0.40 -> MATCH` day 16).
- `uv run python scripts/failure_analysis_v14.py --check` (`~1 min`): replays all 90 v1.4 hard episodes and asserts clean `5.30 V` gap accounting (`4.19 V` skill + `1.11 V` luck).
- `make anticheat-verify` (`~2 min`): reruns `99 rows x 40 judge seeds` (`3,960` runs) against `results/anticheat/exploits.json` (`0 differences`).
- `make game-serve` (`<1s` build): serves the real `canary` package in Pyodide at `http://localhost:8000/?seed=3000` (medium seed `3000` solver replay: Pyodide == CPython `0.79`).

## 3. Live Harbor + OpenCode Rerun Checklist (Needs Docker + API Key)

Build **ONCE** (`10` hard judge tasks `900000-900009` in gitignored `harbor/dataset/`, fresh `0600` `SALT` + `ledger_key` mounted only in `canary-server` sidecar and separate verifier). **Never rebuild between `oracle` and frontier runs** so worlds stay paired (protocol: [`results/harbor/rehearsal/README.md`](results/harbor/rehearsal/README.md), dry run: [`rehearsal-dry`](results/harbor/rehearsal-dry/README.md), isolation: [`harbor/README.md`](harbor/README.md)):

```bash
uv tool install harbor && uv run python harbor/build.py
harbor run -p harbor/dataset -a oracle -n 4
harbor run -p harbor/dataset -a oracle --ae ORACLE_POLICY=do_nothing -n 4
harbor run -p harbor/dataset -a oracle --ae ORACLE_POLICY=stop_early -n 4
harbor run -p harbor/dataset -a oracle --ae ORACLE_POLICY=cheat_probe -n 4
GOOGLE_GENERATIVE_AI_API_KEY=<key> harbor run -p harbor/dataset -a opencode -m google/gemini-4-carbon --api-key-name GOOGLE_GENERATIVE_AI_API_KEY --agent-setup-timeout-multiplier 3 -n 4
```

- **Expected 10-task oracle 90% range:** **`+0.39` to `+0.68`** (mean **`+0.569`**, sd **`0.094`** across 200 fresh-secret builds; [`results/oracle_range_v1.4.md`](results/oracle_range_v1.4.md)). `do_nothing`, `stop_early`, and `cheat_probe` (`149` cheat probes/trial, never accuses) score **`+0.000`** exact.
- **Preventing infra zeros:** OpenCode's Google provider reads `GOOGLE_GENERATIVE_AI_API_KEY` (not `GEMINI_API_KEY`) and Harbor only injects it into `main` when `--api-key-name GOOGLE_GENERATIVE_AI_API_KEY` is passed (without both, OpenCode exits with `AI_LoadAPIKeyError`). `--agent-setup-timeout-multiplier 3` raises Harbor's 360s setup ceiling so `-n 4` Node/npm/`opencode-ai` installs do not fail with `AgentSetupTimeoutError`.

## 4. Compact Rubric Index

| Rubric Pillar | Key Evidence & Metrics | Committed Docs |
|---|---|---|
| **Walkthrough (All Pillars)** | 2-min keyless card + 10-min peer-review rubric walkthrough | [`docs/JUDGE-WALKTHROUGH.md`](docs/JUDGE-WALKTHROUGH.md) |
| **Frontier Gap (30 pts)** | Paired v1.4 `n=30` tables, pre-registration, Harbor oracle spread | [`docs/reports/gap.md`](docs/reports/gap.md), [`results/oracle_range_v1.4.md`](results/oracle_range_v1.4.md) |
| **Difficulty & Causal (30 pts)** | Exact `5.30 V` accounting; **295 episodes, `0.0e+00` unexplained**; W1-W3 audit | [`docs/reports/failure_analysis_v1.4.md`](docs/reports/failure_analysis_v1.4.md), [`docs/reports/failure_gallery.md`](docs/reports/failure_gallery.md), [`docs/DIFFICULTY.md`](docs/DIFFICULTY.md) |
| **Reward Integrity (25 pts)** | 52 logged entries (`43+` attacks); **91 finished attackers, 4,325 calls, 0 exploits** | [`docs/EXPLOITS.md`](docs/EXPLOITS.md), [`results/gemini/swarm.md`](results/gemini/swarm.md) |
| **Craft, Tiebreak & Lab (15 pts)** | Clean-tree keyless reproduce, LoRA SFT/GRPO status, thinking ladder + cache replay | [`docs/gemini/SUBMISSION.md`](docs/gemini/SUBMISSION.md), [`README.md`](README.md) |
