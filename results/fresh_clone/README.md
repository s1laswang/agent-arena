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
