# Cross-Squad Git-Blob Security and Protected-Path Gate (`main` + `arena` vs `justSilas@5f9b3297`)

## 1. Executive Summary and Honesty Alignment

- **Gate verdict:** `PASS` (`protected_file_mutations = 0`, `raw_api_key_leaks = 0`, `salt_files = 0`, `world_json_mole_leaks = 0`, `total_violations = 0`).
- **Execution discipline:** `0` live Gemini / OpenAI / external LLM API calls (`live_llm_calls = 0`); direct git object-store inspection (`git ls-tree -r -z` + `git cat-file --batch`) across un-checked-out remote refs against `origin/justSilas` (`5f9b3297`, `3405` base blobs, `15` protected-path rules), with automatic `HEAD` blob-scan fallback in shallow single-branch CI checkouts; wall time `11.702s`.
- **Panel Fix A + D honesty alignment:** Canary `v1.4` `hard` headline numbers lead with raw `65% [24%, 98%]` (`+0.322` vs solver `+0.499`, `n=30`) before luck-adjusted `72% [52%, 91%]`; dev seeds `0-29` are disclosed as a `post-hoc lock` (locked after the primary run rather than registered beforehand), while `gpt-5.5` (`cf394894`) was locked in advance; and pre-`1bc3e281` `"invalid arguments"` steps (`data: {}`) are normalized strictly on `error == "invalid arguments"` during replay.
- **Scope & non-interference:** Report-only cross-squad security gate (`0` edits to `origin/fr8/canary/main`, `origin/fr8/canary/arena`, or Silas-owned files).

## 2. Keyless Reproduce Commands

```bash
PYTHONPATH=. /tmp/fleet-silas/shared/agent-arena-venv/bin/python scripts/integrity_cross_squad_security_gate.py --with-positive-controls
PYTHONPATH=. /tmp/fleet-silas/shared/agent-arena-venv/bin/python -m pytest -p no:cacheprovider -q tests/test_integrity_cross_squad_security_gate.py
PYTHONPATH=. /tmp/fleet-silas/shared/agent-arena-venv/bin/python scripts/verify_integrity_branch.py
```

## 3. Cross-Squad Branch Security Matrix vs `justSilas@5f9b3297`

| Target branch | Commit SHA | Merge-base | Behind / Ahead `5f9b3297` | Tracked blobs | Delta blobs | Content-scanned paths | Core + Extended protected mutations | Raw API keys | `SALT` files | `.world.json` / mole leaks | Arena Pyodide mirror parity | Status |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---|---|
| `origin/fr8/canary/main` | `c7d62df9` | `9225f2ad` | `2 / +515` | `3730` | `339` | `887` | `0` | `0` | `0` | `0` | `n/a` | `PASS` |
| `origin/fr8/canary/arena` | `4b5cf5fa` | `5f9b3297` | `0 / +81` | `3529` | `124` | `673` | `0` | `0` | `0` | `0` | `14/14 exact` | `PASS` |

### 3.1 Core Silas-Owned Protected Surfaces Verified (`0` Mutations)

- `canary/env.py`: `0` branch diff entries and `0` blob-SHA mismatches across `origin/fr8/canary/main` and `origin/fr8/canary/arena`.
- `canary/rules.py`: `0` branch diff entries and `0` blob-SHA mismatches (`TIERS_VERSION == 'v1.4'`).
- `canary/solver/`: `0` branch diff entries and `0` blob-SHA mismatches across `belief.py`, `params.py`, `policy.py`, and `__init__.py`.
- `canary/reproduce.py`: `0` branch diff entries and `0` blob-SHA mismatches.
- `harbor/`: `0` branch diff entries and `0` blob-SHA mismatches across `build.py`, `check_isolation.sh`, runner templates, and Harbor configs.
- Extended `.github/protected-paths.txt` rules (`canary/world.py`, `canary/types.py`, `canary/eval.py`, `canary/mcp_server.py`, `Makefile`, `configs/`, `data/runs/committed/`, `results/judge_table.md`, `.github/protected-paths.txt`, `.github/workflows/`): `0` mutations across both branches.

### 3.2 Git-Blob Secret, `SALT`, and Mole Answer-Key Verification

- **Unique git blobs streamed via `git cat-file --batch`:** `992` unique text/JSON blobs (`38,941,407` bytes) covering `100%` of squad-added/modified text and JSONL blobs on both branches plus all non-media base source/config/doc/JSON blobs.
- **Raw API keys & tokens (`AIza*`, `sk-*`, `hf_*`, `gh[pousr]_*`, `AKIA*`, PEM private keys):** `0` leaks (`4` explicit synthetic `tests/` fixture files containing `FAKE` / `test-value` markers verified isolated under `tests/`).
- **`SALT` / `.env` / `ledger_key` / binary weight files:** `0` tracked `SALT` files, `0` tracked live `.env` files (only `.env.example`), `0` `ledger_key` files, and `0` `.safetensors`/`.pt`/`.bin`/`.onnx`/`.gguf` weight blobs.
- **`.world.json` & serialized mole answer-key leaks:** `0` tracked `*.world.json` or `*.mole.json` files, `0` serialized `world_seed + mole + employees` dumps, and `0` judge seeds (`>= 900000`) in `docs/arena/data/**` static bundles (`arena_integrity.js` enforces public seed bounds `3000..9999` and blocks `900000..900039` / `800000..800199`).

## 4. Synthetic Git-Blob Tamper Positive Controls (`/tmp/opencode`)

| Control ID | Un-checked-out git-blob mutation injected | Caught |
|---|---|---|
| `clean_branches_pass` | Clean synthetic `main` + `arena` branches pass with `0` false positives | `True` |
| `protected_mutation_caught` | Mutated `canary/env.py` blob on un-checked-out branch | `True` |
| `raw_api_key_caught` | Injected live-pattern Google API key blob outside `tests/` | `True` |
| `salt_file_caught` | Committed `data/worlds/judge/SALT` blob on un-checked-out branch | `True` |
| `world_json_mole_leak_caught` | Committed `data/worlds/900000.world.json` with `mole` answer key | `True` |
| `serialized_world_dump_caught` | Committed JSON blob containing `world_seed` + `mole` + `employees` | `True` |
| `arena_pyodide_drift_caught` | Tampered `docs/arena/py/canary/env.py` diverging from `base:canary/env.py` | `True` |

## 5. Structured Cross-Squad Findings Ledger (Report-Only, Zero Exploit Impact)

| Issue ID | Severity | Area | Branches | Exploit impact | Summary | Evidence |
|---|---|---|---|---|---|---|
| `ISSUE-W9B-01` | `low` | `merge_base_sync_lag` | `origin/fr8/canary/main` | `none` | origin/fr8/canary/main (c7d62df9) has merge-base 9225f2ad, 2 commit(s) behind origin/justSilas (5f9b3297) on non-protected docs/tables | 0/15 protected-path rule mismatches vs 5f9b3297; three-dot diff isolates squad changes cleanly, while final merge of origin/justSilas@5f9b3297 aligns top-level docs before PR merge |
| `ISSUE-W9B-03` | `info` | `upstream_nonprotected_doc_and_script_mods` | `origin/fr8/canary/main` | `none` | origin/fr8/canary/main modifies 9 non-protected upstream file(s) outside .github/protected-paths.txt | modified non-protected paths: M:HANDOFF.md, M:canary/redteam/tamper_guard.py, M:docs/DEMO.md, M:docs/EXPLOITS.md, M:docs/VIDEO-STORYBOARD.md, M:results/fresh_clone/README.md, M:scripts/judge_accept.sh, M:scripts/rehearsal_table.py, M:tests/test_replay_tamper_guard.py |
| `ISSUE-W9B-02` | `info` | `arena_pyodide_protected_mirror_scope` | `origin/fr8/canary/arena` | `none` | .github/protected-paths.txt prefix rules cover root canary/** but not docs/arena/py/canary/**; cross-squad blob-SHA parity check enforces 100% mirror identity without editing protected files | 14/14 docs/arena/py/canary/** blobs match origin/justSilas canary/** SHA-for-SHA (0 drift, 0 reproduce/harbor files mirrored) |
| `ISSUE-W9B-04` | `info` | `cross_branch_delta_disjointness` | `origin/fr8/canary/main`, `origin/fr8/canary/arena` | `none` | Cross-branch delta comparison between origin/fr8/canary/main (339 delta blobs) and origin/fr8/canary/arena (124 delta blobs) found 0 overlapping path(s) and 0 divergent blob(s) | divergent paths: none (100% file-disjoint) |
