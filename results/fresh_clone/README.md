# Fresh-clone checks (macOS and Linux x86_64)

## macOS arm64 (`09e7363`)

Script: `git clone -b justSilas https://github.com/s1laswang/agent-arena.git`, then `make setup`, `make reproduce`, `make accept` and `make test`, each timed. It ran in an empty `/tmp` directory with **empty** `UV_CACHE_DIR` and `UV_PYTHON_INSTALL_DIR`, no `CANARY_*` variables and no `.env`.

| run | commit | clone | setup | reproduce | accept | test |
|---|---|---:|---:|---:|---:|---:|
| [macos_justSilas_09e7363.log.txt](macos_justSilas_09e7363.log.txt), Sat 14 Nov 21:05 UTC, macOS 26.5.2 arm64, uv 0.13.8, GNU Make 3.81 | 09e7363 | 8 s, ok | 2 s, ok | 52 s, ok | 142 s, `RESULT: PASS` | 905 s, 967 passed, 7 skipped |

- **Step timings.** Per-step exit codes and elapsed seconds: [macos_justSilas_09e7363.steps.txt](macos_justSilas_09e7363.steps.txt).
- **Setup time.** uv picked up Homebrew's CPython 3.12 in that run. With `UV_PYTHON_PREFERENCE=only-managed` (uv downloads CPython 3.12.16 itself, cold caches), `make setup` took **7.3 s** ([macos_cold_python_setup.log.txt](macos_cold_python_setup.log.txt)).
- **Test time.** The `make test` time is inflated: seven CPU-bound measurement jobs were running on the same machine. `make accept` re-runs `make setup` and `make reproduce`, which is why it takes longer than `reproduce` alone.
- **What reproduce printed** (hard tier, fresh secret, sha256 fingerprint `f8324878c218`):
  - solver +0.643 ± 0.087;
  - stop_early and do_nothing +0.000;
  - guess_day1 −0.900;
  - the replayed gemini-4-carbon OpenCode row, +0.322 ± 0.199;
  - `ANTI-CHEAT: every probe blocked, every replayable episode and Harbor trial consistent`.
- **Zip download (no `.git`).** `git archive` of the branch, then `make setup` and the git-dependent tests: `test_salt_never_tracked` and `test_gitignore_covers_dotenv` now check `.gitignore` and the absence of a SALT file instead of calling git. `test_results_latest_is_gitignored...` skips by design.

## Linux x86_64 (`2b301cea`)

Fresh clone (`git clone --no-hardlinks` to `/tmp/opencode/canary-fr8-d1` at `2b301cea`) on Rocky Linux 9.5 x86_64 (`Intel(R) Xeon(R) CPU E5-2620 v3 @ 2.40GHz`, 24 logical CPUs, `Python 3.12.16`, `pytest 9.2.0`, `GNU Make 4.3`, `git version 2.52.0`) under a clean `env -i` environment with no `CANARY_*` variables and no `.env`. Per-step exit codes and wall-clock seconds are recorded in [linux_x86_64_justSilas_2b301cea.steps.txt](linux_x86_64_justSilas_2b301cea.steps.txt).

| run | commit | clone | reproduce_fast (`REPRO_FAST=1`) | reproduce (40 seeds) | audit (`--run-reproduce`) | test (core suite) |
|---|---|---:|---:|---:|---:|---:|
| [linux_x86_64_justSilas_2b301cea.log.txt](linux_x86_64_justSilas_2b301cea.log.txt), Sat 14 Nov 23:05 UTC, Rocky Linux 9.5 x86_64, Xeon E5-2620 v3, Python 3.12.16 | 2b301cea | 5 s, ok | 83 s, ok | 159 s, ok | 202 s, `4 PASS, 1 WARN, 0 FAIL` | 263 s, 115 passed |

- **Clean working tree.** `git status --porcelain: empty` held after every step (`clone`, `reproduce_fast`, `reproduce`, `audit`, and `test`).
- **Host load.** Run started at load average `7.57 13.13 16.34` on the shared 24-CPU FR8 node while concurrent evaluation and training jobs were active.
- **What full 40-seed reproduce printed** (hard tier, fresh secret, sha256 fingerprint `996353b5a6c1`; fast 5-seed check used fresh secret fingerprint `0971bf9a92a8`):
  - `solver` `+0.505 +/- 0.139` (`40/40` accused, accuracy `0.93`, mean accuse day `8.8`);
  - `heuristic` `+0.016 +/- 0.178`;
  - `stop_early` and `do_nothing` `+0.000` (`+0.000 +/- 0.000`);
  - `guess_day1` `-0.950 +/- 0.098`;
  - the replayed `opencode:google/gemini-4-carbon` hard row (`n=30`), `+0.322 +/- 0.199` (medium `+0.713 +/- 0.042`; replayed `solver` hard `+0.499 +/- 0.119`);
  - replay and Harbor checks: `989 of 999 committed episodes re-played, 989 consistent; 49549 recorded tool results compared step by step, 0 differ`, and `37 of 37 trials and 13 of 13 job summaries consistent`;
  - `ANTI-CHEAT: every probe blocked, every replayable episode and Harbor trial consistent`.
- **Submission audit (`scripts/audit_submission.py --run-reproduce`).** Printed `SUMMARY: 4 PASS, 1 WARN, 0 FAIL` in `201.46s` (`202 s` total step wall time): `1668` tracked files scanned with `0` secrets or answer keys, frozen `TIERS_VERSION=v1.4` (`a8f99c2537c91d72`) and `TIERS_V13` (`8df71cf570bb48bc`), `61` committed run files / `999` episodes audited (`8` historical v1.2 `valid:false` episodes verified excluded from means), Harbor package static audit `PASS`, and clean-tree `REPRO_FAST=1` reproduce audit `PASS`.
- **Core security and reproduce tests.** `pytest -q tests/test_reproduce.py tests/test_submission_audit.py tests/test_env_frozen.py tests/test_anticheat.py` finished with `115 passed in 261.65s` (`263 s` step wall time).

## Linux x86_64 at tag afterquery-final (`1bc3e281`)

Fresh clone (`git clone --no-hardlinks --branch afterquery-final` resolving annotated tag `afterquery-final` to commit `1bc3e281`, full SHA `1bc3e281dbfaa494a11e783d0c98369b41b2f675`, in `/tmp/opencode/canary-af-check`) on Rocky Linux 9.5 x86_64 (`Intel(R) Xeon(R) CPU E5-2620 v3 @ 2.40GHz`, 24 logical CPUs, `Python 3.12.16`, `pytest 9.2.0`, `GNU Make 4.3`, `git version 2.52.0`) under a clean `env -i` environment (`UV=env` reusing the shared Python 3.12 environment, no `.venv` created, no `CANARY_*` variables, no API keys, and no `.env`). Per-step exit codes and wall-clock seconds are recorded in [linux_x86_64_afterquery_final_1bc3e281.steps.txt](linux_x86_64_afterquery_final_1bc3e281.steps.txt).

| run | commit | clone | reproduce_table (`REPRO_ANTICHEAT=0`) | reproduce (40 seeds + replay + Harbor) | audit | test_core |
|---|---|---:|---:|---:|---:|---:|
| [linux_x86_64_afterquery_final_1bc3e281.log.txt](linux_x86_64_afterquery_final_1bc3e281.log.txt), Sun 15 Nov 03:34 UTC, Rocky Linux 9.5 x86_64, Xeon E5-2620 v3, Python 3.12.16 | 1bc3e281 | 3 s, ok | 27 s, ok | 118 s, ok | 4 s, `3 PASS, 1 WARN, 0 FAIL` | 175 s, 100 passed |

- **Clean working tree.** `git status --porcelain: empty` held after every step (`clone`, `reproduce_table`, `reproduce`, `audit`, and `test_core`).
- **Host load.** Run started at load average `19.42 21.61 18.97` on the shared 24-CPU FR8 node under concurrent multi-worker load.
- **Fast 40-seed table + headline check (`REPRO_ANTICHEAT=0 make reproduce UV=env`, `27 s` / `27.34 s` wall, table `18.2 s` / `total 19.8 s`, fresh secret sha256 fingerprint `ca0f5c61b8d1`).** Hard `solver` `+0.533 +/- 0.120` (`39/40` accused, accuracy `0.93`, mean accuse day `8.6`), `heuristic` `+0.024 +/- 0.189`, `logs_only` `-0.956 +/- 0.086`, `random` `-0.825 +/- 0.119`, `guess_day1` `-1.000 +/- 0.000`, `stop_early` and `do_nothing` `+0.000 +/- 0.000`; medium `solver` `+0.621 +/- 0.082`; easy `solver` `+0.797 +/- 0.033`; `HEADLINE` recomputed identically to `data/runs/committed/v1.4/paired_table_gemini.md`.
- **Full 40-seed reproduce (`make reproduce UV=env`, `118 s` / `118.17 s` wall, `total 107.5 s`, fresh secret sha256 fingerprint `77cb352b4987`).**
  - `solver` hard `+0.527 +/- 0.116` (`40/40` accused, accuracy `0.95`, mean accuse day `8.9`), medium `+0.664 +/- 0.063`, easy `+0.772 +/- 0.037`;
  - `heuristic` hard `-0.201 +/- 0.208`, `logs_only` `-1.000 +/- 0.000`, `random` `-0.825 +/- 0.119`, `guess_day1` `-0.900 +/- 0.137`, `stop_early` and `do_nothing` `+0.000 +/- 0.000`;
  - replayed v1.4 reported hard rows: `opencode:google/gemini-4-carbon` (`n=32`, including the 2-seed extension) `+0.349 +/- 0.190`, `opencode:google/gemini-3.5-flash` (`n=30`) `+0.373 +/- 0.177`, `gemini:gemini-4-carbon` (`n=30`) `+0.473 +/- 0.118`, and `solver` (`n=60`) `+0.498 +/- 0.097`;
  - `HEADLINE` (recomputed from committed episodes on the post-hoc locked dev seeds `0-29`, `671ed96` 28 s after `8fd4dec`, identical to `data/runs/committed/v1.4/paired_table_gemini.md`): `hard, OpenCode + gemini-4-carbon over MCP: +0.322 +/- 0.199 vs reference solver +0.499, paired on seeds 0-29 = 65% [24%, 98%] of the solver (luck-adjusted 72% [52%, 91%])`;
  - replay, Harbor, and anti-cheat checks: `1021 of 1031 committed episodes re-played, 1021 consistent; 51814 recorded tool results compared step by step, 0 differ`, `80 of 80 trials and 18 of 18 job summaries consistent` (`60` signed, `20` earlier unsigned, `57` HMAC-verified), and `ANTI-CHEAT: every probe blocked, every replayable episode and Harbor trial consistent`.
- **Submission audit (`python scripts/audit_submission.py`).** Printed `SUMMARY: 3 PASS, 1 WARN, 0 FAIL (3.81s)` (`4 s` step wall time): `3366` tracked files scanned with `0` secrets or answer keys, frozen `TIERS_VERSION=v1.4` (`a8f99c2537c91d72`) and `TIERS_V13` (`8df71cf570bb48bc`), `63` committed run files / `1031` episodes audited (`8` historical v1.2 `valid:false` episodes verified excluded from means), and Harbor package static audit `PASS`.
- **Core security, Harbor signature, and replay tamper tests.** `python -m pytest -q tests/test_reproduce.py tests/test_env_frozen.py tests/test_harbor_ledger_sig.py tests/test_replay_tamper_guard.py` finished with `100 passed in 174.42s` (`175 s` step wall time).
