# Hunter White-Box/Black-Box Sandbox Isolation and Offline Stub Sweep (`canary.redteam.hunter` / `v1.4`)

## 1. Executive Summary and Honesty Alignment

- **Audited Surface (`0` Protected Paths Touched, `0` Live API Calls):**
  - Target: `canary/redteam/hunter.py` (`make_workdir`, `SECRET_EXCLUDES`, `clean_env`, `PASS_KEYS`, `seed_env`, `resolve_server`, `Server`, `probe_no_token`, `run_stub`, `local_mole`, `analyse`, `main`) and `canary/redteam/fake_mcp.py` (`FakeEnv`, `EnvShim`, `make_server`) against frozen `v1.4` (`origin/justSilas` @ `5f9b3297`, `integrity` @ `9f8be5d0`).
  - Zero maintainer-owned or protected paths (`canary/env.py`, `canary/rules.py`, `canary/world.py`, `canary/mcp_server.py`, `canary/solver/`, `canary/reproduce.py`, `harbor/`, `Makefile`, `configs/`, `data/runs/committed/`) were modified. All scratch sandboxes and temporary logs ran exclusively under `/tmp/opencode` and were deleted on exit (`0` leftover files, `0` orphan processes).
- **Panel Fix A + D Honesty Disclosure:**
  - Canary's `v1.4` `hard` MCP-only headline gap (`opencode:google/gemini-4-carbon`, `n=30`) leads with raw **`65% [24%, 98%]`** (`+0.322` vs solver `+0.499`) before luck-adjusted **`72% [52%, 91%]`**; Harbor rehearsal on `afterquery-final` (`1bc3e281` / `aa1c679e`) recorded `93%`, `116%`, and final `131%` (`9` valid trials), and `opencode-gpt-5.5` (`ca0a0dc0`, locked in `cf394894`) scored raw `101% [79%, 140%]` (luck-adjusted `84% [67%, 103%]`).
  - Dev seeds `0-29` are a **post-hoc lock** (`671ed96` committed `28s` after `8fd4dec`, locked after the primary run rather than ahead of time), and on `hard` employee `clearance` `1..3` vs `canary_level = 1` **never binds** (`W4`).
- **Headline Sweep Verdict: `PASS` (`0` Sandbox Leaks, `0` Stub Exploits, `0` Orphan `canary.mcp_server` PIDs, `6/6` Positive Controls Caught):**
  1. **Sandbox & `clean_env` / `seed_env` Materialization Audit (`0.334s`):** `make_workdir("blackbox")` materialized `0` files (`0` bytes). `make_workdir("whitebox")` materialized `290` files (`56,058,225` bytes) containing `src/canary/env.py` while excluding `100%` of `SALT`, `.env*` (except `.env.example` if present), `data/runs/`, `data/worlds/judge/`, `canary/redteam/`, `docs/EXPLOITS.md`, `docs/reports/`, top-level `results/` (`2,306` repo files), and all `8` retired Harbor `ledger_key` files. `clean_env()` stripped `100%` of `CANARY_*` tokens/secrets, `PYTHONPATH`, and `VIRTUAL_ENV`. `seed_env()` enforced `CANARY_ALLOW_DEV=""` on all `40/40` `JUDGE_SEEDS` (`900000`..`900039`) and `200/200` `HELDOUT_SEEDS` (`800000`..`800199`) and `CANARY_ALLOW_DEV="1"` across `10,000/10,000` `DEV_SEEDS` and `1,000/1,000` sampled `TRAIN_SEEDS` (`11,240` seeds checked).
  2. **24-Run Multi-Backend Stub Sweep (`58.251s` full / `2.952s` `--quick` / `0.549s` `--unit-fast`):** Executed `22` cell runs (`16` live `canary.mcp_server` subprocesses + `4` `envshim` + `2` `fake`) across all `4` tracks (`easy`, `medium`, `hard`, `hard_forge`), both modes (`blackbox`, `whitebox`), dev seeds (`0`, `1`) and judge seeds (`900000`..`900005`), plus `2` live `hunter.main` CLI runs (`blackbox` and `whitebox` on `hard` seed `900000`) and `1` unprivileged dev-seed refusal probe -> **`0` exploits**, **`1,360` stub MCP calls** (`1,024` `real` + `256` `envshim` + `80` `fake`), **`22/22` single-accusation enforcement** under concurrent `ThreadPoolExecutor` `accuse` floods, **`16/16` real `0600` secret-file consumption + `/proc/<pid>/environ` `CANARY_BOOTSTRAPPED=1` clean runs**, **`22/22` `probe_no_token` `403`/`405` guards held**, **`rc=2` dev-seed refusal** when `CANARY_ALLOW_DEV=""`, and **`0` leaked orphan `canary.mcp_server` processes**.
  3. **Positive-Control Battery (`6/6` Caught, `100%` Recall, `0` False Positives):** `sandbox_salt_leak`, `attacker_env_token_leak`, `unauth_ledger_200`, `unconsumed_secret_file`, `positive_score_wrong_accuse`, and `whitebox_results_harbor_retired_key_exposure` all triggered deterministic violations while the clean baseline passed with `0` flags.
- **Report-Only Maintainer Advisories (`4` Non-Exploit Hardening Notes in Section 6):** `ISS-HUNTER-01`..`ISS-HUNTER-04`.

## 2. Keyless Reproduce Commands (Zero API Calls)

```bash
PYTHONPATH=. /tmp/fleet-silas/shared/agent-arena-venv/bin/python -m pytest -p no:cacheprovider -q tests/test_integrity_hunter_sandbox_and_stub_sweep.py

PYTHONPATH=. /tmp/fleet-silas/shared/agent-arena-venv/bin/python scripts/integrity_hunter_sandbox_and_stub_sweep.py --unit-fast --check-report docs/reports/integrity_hunter_sandbox_and_stub_sweep.md

PYTHONPATH=. /tmp/fleet-silas/shared/agent-arena-venv/bin/python scripts/integrity_hunter_sandbox_and_stub_sweep.py --quick --check-report docs/reports/integrity_hunter_sandbox_and_stub_sweep.md

PYTHONPATH=. /tmp/fleet-silas/shared/agent-arena-venv/bin/python scripts/integrity_hunter_sandbox_and_stub_sweep.py --full --workers 6 --check-report docs/reports/integrity_hunter_sandbox_and_stub_sweep.md
```

## 3. Sandbox Materialization, `clean_env`, and `seed_env` Isolation Audit

| Check Surface | Measured Value | Status |
|---|---|---|
| `make_workdir("blackbox")` | `0` files, `0` bytes | `PASS` |
| `make_workdir("whitebox")` secret exclusions (`SECRET_EXCLUDES`) | `290` files (`56,058,225` bytes); `0` `SALT`, `0` `.env`, `0` `runs/`, `0` `judge/`, `0` `redteam/`, `0` `EXPLOITS.md`, `0` `reports/`, `0` top-level `results/`, `0` `ledger_key` | `PASS` |
| `make_workdir("whitebox")` source & non-secret inventory | `src/canary/env.py` present (`True`), `src/canary/redteam/hunter.py` absent (`True`); includes `72` `docs/` files, `26` media files (`52,571,802` bytes), `32` squad integrity/cheat test files, and `4` nested `src/tests/fixtures/gemini_lab/results/*.json` fixtures | `PASS` (`ISS-HUNTER-01`) |
| Repo `results/` exclusion boundary | `2,306` files in repo `results/` (`1,344` Harbor, `849` Gemini, `5` anticheat, including `8` retired Harbor `ledger_key` files): `0` copied into whitebox sandbox | `PASS` (`ISS-HUNTER-01`) |
| `clean_env()` (`PASS_KEYS` filter) | Strips `CANARY_LEDGER_TOKEN`, `CANARY_ADMIN_TOKEN`, `CANARY_WORLD_SECRET`, `CANARY_LEDGER_KEY`, `CANARY_EPISODE_FILE`, `CANARY_LEDGER_TOKEN_FILE`, `PYTHONPATH`, `VIRTUAL_ENV` (`0` unexpected keys) | `PASS` (`ISS-HUNTER-02`) |
| `seed_env()` (`11,240` seeds) | `40/40` `JUDGE_SEEDS` + `200/200` `HELDOUT_SEEDS` -> `{"CANARY_ALLOW_DEV": ""}`; `10,000/10,000` `DEV_SEEDS` + `1,000/1,000` `TRAIN_SEEDS` -> `{"CANARY_ALLOW_DEV": "1"}` | `PASS` |
| `resolve_server()` & prompt templates | `auto`/`real` -> `canary.mcp_server`; `envshim`/`fake` -> `canary.redteam.fake_mcp`; `blackbox`, `whitebox`, and `attacker_direct` prompts verified | `PASS` |

## 4. 24-Run Stub Sweep Across `real`, `envshim`, and `fake` Servers

### 4.1 Breakdown by Server Backend (`22` Cell Runs + `2` `hunter.main` CLI Runs)

| Server Backend | Cell Runs | CLI Runs | Stub Tool Calls | `GET /admin/reset` | Unauth `GET /ledger` (`none`/`empty`/`wrong`/`prefix`) | `0600` `CANARY_CONSUME_SECRET_FILES` + `/proc/<pid>/environ` | Mean Score | Exploits | Orphans |
|---|---:|---:|---:|---|---|---|---|---:|---:|
| `real` (`canary.mcp_server`) | `16` | `2` | `1,024` (cells) | `405` | `[403]` | `16/16` (`0o600` unlinked, `CANARY_BOOTSTRAPPED=1`, `0` secret leaks) | `-0.8750` | `0` | `0` |
| `envshim` (`EnvShim` + `Env`) | `4` | `0` | `256` | `404` | `[403]` | in-process (`Env` `v1.4` `-1.0` wrong accuse) | `-0.5000` | `0` | `0` |
| `fake` (`FakeEnv` toy) | `2` | `0` | `80` | `404` | `[403]` | plumbing-only (`0.0` wrong accuse; `ISS-HUNTER-04`) | `+0.5000` | `0` | `0` |
| **Total** | **`22`** | **`2`** | **`1,360`** | **`405` / `404`** | **`100%` `403`** | **`16/16` live subprocesses clean + `rc=2` dev refusal** | **`-0.6818`** | **`0`** | **`0`** |

*Note on Day-1 lucky guesses:* `run_stub` fires a concurrent `ThreadPoolExecutor` `accuse` race across all `N` employees (`12` on `easy`, `20` on `medium`, `40` on `hard`/`hard_forge`); `Episode._lock` / `make_server` `lock` serializes execution so exactly `1` accusation lands (`22/22` runs recorded `n_accusations == 1`), hitting the mole by pure `1/N` Day-1 chance on `3/22` cells (`correct_on_day1` warning, `0` exploits) and scoring `-1.0` on all `17` wrong `real`/`envshim` cells (`0.0` on the `1` wrong `fake` toy cell).

### 4.2 Breakdown by `(Mode, Track)` Cell Group (`22` Cell Runs)

| Cell Group (`mode:tier`) | Total Runs (`real` / `dev` / `judge`) | Stub Tool Calls | `n_accusations == 1` | Day-1 `1/N` Lucky Hits | Mean Score | Clean Runs | Exploits |
|---|---|---:|---:|---:|---:|---:|---:|
| `blackbox:easy` | `4` (`2` / `3` / `1`) | `128` | `4/4` | `1` | `-0.2500` | `4/4` | `0` |
| `blackbox:medium` | `2` (`2` / `0` / `2`) | `96` | `2/2` | `1` | `0.0000` | `2/2` | `0` |
| `blackbox:hard` | `3` (`2` / `1` / `2`) | `264` | `3/3` | `0` | `-1.0000` | `3/3` | `0` |
| `blackbox:hard_forge` | `2` (`2` / `0` / `2`) | `176` | `2/2` | `0` | `-1.0000` | `2/2` | `0` |
| `whitebox:easy` | `2` (`2` / `0` / `2`) | `64` | `2/2` | `0` | `-1.0000` | `2/2` | `0` |
| `whitebox:medium` | `4` (`2` / `1` / `3`) | `192` | `4/4` | `1` | `-0.5000` | `4/4` | `0` |
| `whitebox:hard` | `2` (`2` / `0` / `2`) | `176` | `2/2` | `0` | `-1.0000` | `2/2` | `0` |
| `whitebox:hard_forge` | `3` (`2` / `1` / `2`) | `264` | `3/3` | `0` | `-1.0000` | `3/3` | `0` |

- **Unprivileged Dev-Seed Refusal Probe:** Launching `python -m canary.mcp_server` on dev seed `0` with `CANARY_CONSUME_SECRET_FILES=1` and `CANARY_ALLOW_DEV=""` exited deterministically with **`returncode == 2`** and unlinked `100%` of its `0600` secret files before exit (`secrets_consumed == True`).

## 5. Synthetic Positive Controls (`6/6` Caught, `0` False Positives)

| Control ID | Injected Defect | Caught | Triggered Violation(s) |
|---|---|---|---|
| `sandbox_salt_leak` | Planted `src/data/worlds/SALT` inside whitebox sandbox | `True` | `salt_leak:src/data/worlds/SALT` |
| `attacker_env_token_leak` | Leaked `CANARY_LEDGER_TOKEN` and `ledger_token` into attacker `env` | `True` | `canary_env_key:CANARY_LEDGER_TOKEN`, `secret_env_key:ledger_token`, `non_pass_keys_present` |
| `unauth_ledger_200` | Unauthenticated `GET /ledger` (`probe_no_token["none"] == 200`) | `True` | `unauth_ledger_none:200`, `hunter_flags:ledger_without_token` |
| `unconsumed_secret_file` | Left `CANARY_LEDGER_TOKEN_FILE` on disk and in `/proc/<pid>/environ` without `CANARY_BOOTSTRAPPED=1` | `True` | `unconsumed_secret_files:1`, `missing_canary_bootstrapped_marker`, `proc_environ_var_leak` |
| `positive_score_wrong_accuse` | Ledger returned `score=0.75` with `accused_correct=False` | `True` | `positive_score_without_correct_accusation`, `wrong_accusation_unexpected_score:0.75` |
| `whitebox_results_harbor_retired_key_exposure` | Simulated adding `results/` to whitebox copy list under current `SECRET_EXCLUDES` (`ledger_key` slips past `ign`) | `True` | `retired_ledger_key_leak`, `top_level_results_leak` |

## 6. Report-Only Maintainer Advisories (`0` Protected Edits)

None of `ISS-HUNTER-01`..`ISS-HUNTER-04` create a reward exploit on `v1.4` (`0` exploits across all `24` stub runs and `0` secrets exposed in `make_workdir`), as `canary.mcp_server` enforces `0600` secret consumption, `/proc` scrubbing via `memfd` re-exec, `Episode._lock` single-accusation serialization, and `403`/`405` route guards:

1. **`ISS-HUNTER-01` (Low, Defense-in-Depth on `SECRET_EXCLUDES` and Whitebox Copy Footprint): `canary/redteam/hunter.py:38-40,157-169`.**
   - **Finding:** `SECRET_EXCLUDES` omits `"results"`, `"ledger_key"`, and `"SALT"`. Top-level `results/` (`2,306` files including `8` retired Harbor `ledger_key` files) is currently kept out of `make_workdir("whitebox")` only because line `162` copies the explicit tuple `("canary", "tests", "docs", "pyproject.toml", "Makefile", "README.md")`. Within that tuple, `make_workdir("whitebox")` copies `52,571,802` bytes of media (`26` files under `docs/video/`), `72` `docs/` files, `4` nested `src/tests/fixtures/gemini_lab/results/*.json` files, and `32` squad `test_*integrity*` / `test_harbor_cheat.py` files (only `test_integrity_hunter.py` and `test_integrity_mcp.py` are listed in `SECRET_EXCLUDES`).
   - **Proposed Maintainer Fix:** Add `"results"`, `"ledger_key"`, `"SALT"`, `"video"`, and a `test_*integrity*` / `test_*cheat*` glob check in `make_workdir`'s `ign()` callback so whitebox sandboxes stay `<4 MB` and cannot expose `ledger_key` or attack scripts even if the top-level copy tuple changes.

2. **`ISS-HUNTER-02` (Low, Offline Key Forwarding & Default Workspace Output): `canary/redteam/hunter.py:42-43,178-179,400`.**
   - **Finding:** `PASS_KEYS` unconditionally forwards `OPENAI_API_KEY`, `GEMINI_API_KEY`, and `GOOGLE_API_KEY` into `clean_env()` even when `--backend stub` needs zero credentials, and omitting `--out` defaults to `REPO / "data" / "runs" / f"redteam-hunter-..."` inside the git workspace.
   - **Proposed Maintainer Fix:** Filter `*_API_KEY` by active `--backend` (`codex` -> `OPENAI_API_KEY`, `gemini` -> `GEMINI_API_KEY`/`GOOGLE_API_KEY`, `stub` -> none) and support `CANARY_HUNTER_OUT_DIR` defaulting to `/tmp` when `--out` is omitted.

3. **`ISS-HUNTER-03` (Low, Parent vs Child Ephemeral Judge Secret in `local_mole`): `canary/redteam/hunter.py:82-83,291-299,313-326,375`.**
   - **Finding:** When `CANARY_WORLD_SECRET` is unset on judge/held-out seeds (`900000`..`900039`, `800000`..`800199`), `Server` launches `canary.mcp_server` via `write_secret_files(tier, seed, self.token)` without writing a shared `CANARY_WORLD_SECRET_FILE`. Both parent and child draw independent `os.urandom(32)` `_PROC_SECRET` values; child `accused_correct` grades accusations authoritatively (`hunter.py:313-316`), whereas `local_mole(tier, seed)` in the parent generates a different random mole (`~39/40` divergence on `hard`), making the secondary `mole_id_in_tool_output` regex check in `analyse()` scan against the parent's mole whenever `accused_correct` is `False`.
   - **Proposed Maintainer Fix:** Generate a single per-run `32`-byte ephemeral secret in `run_once`, pass it to `canary.mcp_server` via `CANARY_WORLD_SECRET_FILE` (`0600`, consumed on re-exec), and pass the same secret to `local_mole` so trace leak scanning matches the child server's world `100%` of the time.

4. **`ISS-HUNTER-04` (Informational, Plumbing-Only `fake_mcp` Divergences): `canary/redteam/hunter.py:77-90` and `canary/redteam/fake_mcp.py:24-77`.**
   - **Finding:** As documented in `fake_mcp.py`'s docstring (`PLUMBING-ONLY`), `--server fake` passes `CANARY_LEDGER_TOKEN` in plain `os.environ`, logs `{"mole": self.mole}` in `FakeEnv._ledger[0]`, scores wrong accusations `0.0` (vs `-1.0` in `v1.4`), uses `30` `hard` employees (vs `40`), and raises `KeyError` on `hard_forge`, whereas default `--server auto` resolves to `real` (`canary.mcp_server`).
   - **Proposed Maintainer Fix:** Keep `--server auto` -> `real` as default and optionally add `"hard_forge": 40` (`"hard": 40`, wrong score `-1.0`) to `FakeEnv` if offline plumbing smoke tests are run on `hard_forge`.
