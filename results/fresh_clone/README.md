# Fresh-clone checks (macOS)

Script: `git clone -b justSilas https://github.com/s1laswang/agent-arena.git`, then `make setup`, `make reproduce`, `make accept` and `make test`, each timed. It ran in an empty `/tmp` directory with **empty** `UV_CACHE_DIR` and `UV_PYTHON_INSTALL_DIR`, no `CANARY_*` variables and no `.env`.

| run | commit | clone | setup | reproduce | accept | test |
|---|---|---:|---:|---:|---:|---:|
| [macos_justSilas_09e7363.log](macos_justSilas_09e7363.log), Sat 14 Nov 21:05 UTC, macOS 26.5.2 arm64, uv 0.13.8, GNU Make 3.81 | 09e7363 | 8 s, ok | 2 s, ok | 52 s, ok | 142 s, `RESULT: PASS` | 905 s, 967 passed, 7 skipped |

- **Setup time.** uv picked up Homebrew's CPython 3.12 in that run. With `UV_PYTHON_PREFERENCE=only-managed` (uv downloads CPython 3.12.16 itself, cold caches), `make setup` took **7.3 s** ([macos_cold_python_setup.log](macos_cold_python_setup.log)).
- **Test time.** The `make test` time is inflated: seven CPU-bound measurement jobs were running on the same machine. `make accept` re-runs `make setup` and `make reproduce`, which is why it takes longer than `reproduce` alone.
- **What reproduce printed** (hard tier, fresh secret, sha256 fingerprint `f8324878c218`):
  - solver +0.643 ± 0.087;
  - stop_early and do_nothing +0.000;
  - guess_day1 −0.900;
  - the replayed gemini-4-carbon OpenCode row, +0.322 ± 0.199;
  - `ANTI-CHEAT: every probe blocked, every replayable episode and Harbor trial consistent`.
- **Zip download (no `.git`).** `git archive` of the branch, then `make setup` and the git-dependent tests: `test_salt_never_tracked` and `test_gitignore_covers_dotenv` now check `.gitignore` and the absence of a SALT file instead of calling git. `test_results_latest_is_gitignored...` skips by design.
