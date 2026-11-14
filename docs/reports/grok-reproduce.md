# Judge reproduction: `justSilas` (clean machine)

Role: hackathon judge. The only project document used to decide what to run was `README.md` at commit `54e1fa4fac3065af5182837336b7a949beb82550` (subject: `Merge justSilas-env: tiers v1, JUDGE_SEEDS 40, contract v0.5 fail-closed, solver v0.3`, authored 2026-11-14 02:19:44 +0200). No other file, comment, or prior context was used to fill gaps. When the README was ambiguous, the guess is recorded below and the run continued.

**Headline:** reproduction of the advertised judge table did **not** succeed. `make reproduce` exits 0 and prints `TODO: --reproduce (judge table on frozen judge seeds) is not implemented yet`. There is no table and no numeric claim in the README to compare against. The same stub is what `4d572ef` prints (see the revision note).

**Revision note.** The clean-machine run is commit `54e1fa4` (`justSilas` at clone time, 2026-11-14T00:20:17Z). `origin/justSilas` then fast-forwarded twice before this report was finished. The README blob stayed `caf3c7f2ed03885455b9575794f6920625c9619c`. `Makefile` did not change.

| Tip | When (commit author date) | Subject | `make test` |
| --- | --- | --- | --- |
| `54e1fa4` | 2026-11-14 02:19:44 +0200 | Merge justSilas-env | 321 passed, 8 skipped, 1 xfailed, 8 xpassed, 2 warnings, 30.00 s |
| `4d572ef` | 2026-11-14 02:24:26 +0200 | Merge justSilas-fr8 | 338 passed, 3 skipped, 1 xfailed, 8 xpassed, 2 warnings, 39.24 s |
| `6869c5b` | 2026-11-14 02:26:01 +0200 | Merge justSilas-integrity | 348 passed, 3 skipped, 34.43 s (no xfail, no xpass, no warnings) |
| `1a89015` | 2026-11-14 02:27:17 +0200 | Merge justSilas-integrity: solver tier-ordering guard | 348 passed, 3 skipped, 1 xfailed, 37.56 s |

Eval stayed **+0.458 ± 0.155**, accuracy **0.65**, n=20, on every tip where it was run (`54e1fa4` twice, `4d572ef`, `6869c5b`). It was not re-run on `1a89015`. `make reproduce` stayed the TODO on every tip where it was run (not re-run on `1a89015`). Later passes reused the uv install; `6869c5b` and `1a89015` also reused the worktree venv. They are not extra cold starts. The README names none of these counts.

**Setup + reproduce wall clock**

| Measurement | Wall clock | Exit |
| --- | ---: | ---: |
| `make setup` on a machine with no `uv` | 0.005 s | make exit 2 (recipe 127) |
| Installing `uv` (not in the README; see Guesses) | 0.667 s | 0 |
| `make setup` after `uv` was on `PATH` (first real install) | 0.692 s | 0 |
| `make reproduce` immediately after that setup | 0.056 s | 0, stub |
| Later, one shell chain `make setup && make reproduce` with the venv already installed | 0.068 s | 0, stub |

A judge who stops at the README commands, after spending about a second installing `uv`, gets a green exit and no results. The full README sequence (`setup` + `test` + `eval` + `reproduce`) took **31.881 s** of command wall clock on `54e1fa4` once `uv` was installed (dominated by `make test` at 30.814 s). On `4d572ef`, with a warm uv cache and a new venv, the same sequence was **40.809 s**. On `6869c5b`, same worktree venv, it was **35.345 s** (setup 0.016 + test 34.951 + eval 0.321 + reproduce 0.057).

Clone used for the run: fresh `git clone --branch justSilas --single-branch https://github.com/s1laswang/agent-arena` into `/tmp/judge-20261114T002017Z/agent-arena` (0.572 s). Nothing was installed from the workspace checkout.

Timing method: `/usr/bin/time` is not installed on this machine. Every step is a wall-clock delta of `date +%s.%N` (Python `float` subtraction). stdout and stderr were redirected to separate log files except the final chain, where the shell redirect bound only `make reproduce` (setup's short uv lines were still captured in the session log and are quoted below).

## Environment (fresh machine, before `make setup`)

| Item | Value |
| --- | --- |
| OS | Ubuntu 24.04.5 LTS (Noble), kernel `Linux 6.12.113+ #1 SMP PREEMPT_DYNAMIC` x86_64 |
| CPU / RAM | 4 cores, `MemTotal` 16387328 kB |
| `make` | GNU Make 4.3 |
| `python3` / `python3.12` | Python 3.12.3 at `/usr/bin/python3` and `/usr/bin/python3.12` |
| `python` (unversioned) | not on `PATH` |
| `pip3` | pip 24.0 (`/usr/lib/python3/dist-packages/pip`) |
| `uv` | **not installed** until the guess below. After install: uv 0.13.8 |
| `git` | 2.43.0 |
| `gcc` / `g++` | Ubuntu 13.3.0-6ubuntu2~24.04.1 |
| `node` | v22.23.4 |
| `npm` | 10.9.9 |
| `pnpm` | 10.33.4 |
| `yarn` | 1.22.22 |
| `go` | go1.22.2 linux/amd64 |
| `java` | OpenJDK 21.0.13.0.3 (2026-10-24) |
| `rustc` / `cargo` | 1.83.0 |
| `curl` | 8.5.0 |
| `docker` / `docker-compose` | not installed |
| `conda` / `bun` | not installed |

The README does not mention Docker, Node, Go, Java, or Rust. They were not used. No `.env` was created. `GEMINI_API_KEY` and `OPENAI_API_KEY` were unset. No key was invented.

## What the README actually says to run

The README does **not** advertise the single chain `make setup && make reproduce`. It shows four separate lines:

```bash
make setup        # uv, Python 3.12
make test
make eval AGENT=solver TIER=medium
make reproduce    # judge table: reference, 3 agent runs, do-nothing, stop-early (no API keys needed)
```

All four were run, in that order. Harbor and OpenCode: **the README contains neither**. Those instructions were not followed. A top-level `harbor/` directory is visible in the clone and is not linked from the README. It was not opened.

Linked docs were checked only for existence (not read):

| README link | On disk |
| --- | --- |
| `docs/PLAN.md` | present (7814 bytes) |
| `docs/CONTRACT.md` | present (11587 bytes) |
| `docs/TEAM.md` | present (2790 bytes) |
| `docs/EXPLOITS.md` | present (11534 bytes) |
| `CHALLENGES-AFTERQUERY-GEMINI.md` | present (6058 bytes) |

`.env.example` is in the repo root (219 bytes) and is not mentioned by the README. Its keys, with empty values, are `GEMINI_API_KEY`, `OPENAI_API_KEY`, `CANARY_GEMINI_MODEL=gemini-2.5-pro`, `CANARY_OPENAI_MODEL=gpt-5`. `docs/reports/env.md` also exists and is not linked from the README. It was not read.

## Guesses (README ambiguous or wrong)

1. **`make setup        # uv, Python 3.12` does not install `uv`.** Read as "this target needs `uv` and Python 3.12 already installed." Python 3.12.3 was already on the machine. `uv` was not. After the first `make setup` failed, `uv` 0.13.8 was installed with the upstream installer and `$HOME/.local/bin` was prepended to `PATH`:

   ```bash
   curl -LsSf https://astral.sh/uv/install.sh | sh
   export PATH="$HOME/.local/bin:$PATH"
   ```

   Installer stdout: `installing to /home/ubuntu/.local/bin` / `uv` / `uvx` / `everything's installed!` plus the hint to `source $HOME/.local/bin/env`. Installer stderr: `downloading uv 0.13.8 x86_64-unknown-linux-gnu`. This step is not in the README.

2. **Run every target in the fenced block, not only setup and reproduce.** The task prompt's example chain is not what the README shows.

3. **Do not open the linked docs or `harbor/` to discover extra judge steps.** The README lists those docs as "Docs:" and never says they are part of the judge path.

4. **Run `make eval AGENT=solver TIER=medium` a second time** to see whether the printed score moves. It did not (same four numbers; only the timestamped output path changed).

## Step-by-step log

### 1. Clone — 0.572 s, exit 0

`2026-11-14T00:20:17Z`. stderr: `Cloning into '/tmp/judge-20261114T002017Z/agent-arena'...`

### 2. `make setup` (no uv) — 0.005 s, make exit 2

`2026-11-14T00:20:39Z`.

stdout:

```text
uv sync --python 3.12 --extra dev --extra llm
```

stderr:

```text
make: uv: No such file or directory
make: *** [Makefile:11: setup] Error 127
```

`uv` is not listed as a prerequisite anywhere except the trailing comment on this line. The README does not say how to install it, and `make setup` does not install it.

### 3. Install uv (guess) — 0.667 s, exit 0

`2026-11-14T00:20:49Z`. See Guesses. Not a README step.

### 4. `make setup` (uv 0.13.8 on PATH) — 0.692 s, exit 0

`2026-11-14T00:20:55Z`.

stdout:

```text
uv sync --python 3.12 --extra dev --extra llm
```

stderr (complete; this is the install log, not a failure):

```text
Using CPython 3.12.3 interpreter at: /usr/bin/python3.12
Creating virtual environment at: .venv
Resolved 79 packages in 1ms
   Building canary @ file:///tmp/judge-20261114T002017Z/agent-arena
Downloading cryptography (4.5MiB)
Downloading pydantic-core (2.2MiB)
Downloading pygments (1.2MiB)
Downloading openai (2.3MiB)
Downloading google-genai (1.3MiB)
Downloading numpy (16.0MiB)
Downloading hypothesis (1.1MiB)
 Downloaded hypothesis
 Downloaded pydantic-core
 Downloaded pygments
 Downloaded google-genai
 Downloaded cryptography
 Downloaded openai
 Downloaded numpy
      Built canary @ file:///tmp/judge-20261114T002017Z/agent-arena
Prepared 52 packages in 585ms
Installed 52 packages in 35ms
 + annotated-types==0.8.0
 + anyio==4.16.0
 + attrs==26.1.0
 + canary==0.0.1 (from file:///tmp/judge-20261114T002017Z/agent-arena)
 + certifi==2026.10.23
 + cffi==2.1.1
 + charset-normalizer==3.5.2
 + click==8.5.1
 + cryptography==50.0.2
 + distro==1.9.0
 + google-auth==2.62.2
 + google-genai==3.3.0
 + h11==0.16.0
 + httpcore2==2.16.0
 + httpx2==2.16.0
 + hypothesis==6.170.15
 + idna==3.20
 + iniconfig==2.3.1
 + jiter==0.19.0
 + jsonschema==4.26.0
 + jsonschema-specifications==2025.9.1
 + mcp==2.3.0
 + mcp-types==2.3.0
 + numpy==2.5.4
 + openai==3.51.0
 + opentelemetry-api==1.45.2
 + packaging==26.3
 + pluggy==1.7.0
 + pyasn1==0.6.5
 + pyasn1-modules==0.4.2
 + pycparser==3.12
 + pydantic==2.14.3
 + pydantic-core==2.50.4
 + pygments==2.21.0
 + pyjwt==2.15.1
 + pytest==9.2.0
 + python-dotenv==1.2.4
 + python-multipart==0.0.33
 + referencing==0.37.0
 + requests==2.34.2
 + rpds-py==2026.9.1
 + sniffio==1.3.1
 + sortedcontainers==2.4.0
 + sse-starlette==3.7.0
 + starlette==1.10.0
 + tenacity==9.1.4
 + truststore==0.10.5
 + typing-extensions==4.16.0
 + typing-inspection==0.4.5
 + urllib3==2.8.0
 + uvicorn==0.54.0
 + websockets==17.4
```

No API key was requested. Packages include `google-genai` and `openai`, which the README never mentions.

### 5. `make test` — 30.814 s, exit 0

`2026-11-14T00:21:00Z`. stderr empty. stdout (complete):

```text
uv run --python 3.12 --extra dev --extra llm pytest -q
......................................s................................. [ 21%]
........................................................................ [ 42%]
.......................................................................X [ 64%]
xXXX...XXX.................Xs..s..s..s..s......................s........ [ 85%]
.................................................                        [100%]
=============================== warnings summary ===============================
tests/test_llm.py::test_missing_keys
  /tmp/judge-20261114T002017Z/agent-arena/.venv/lib/python3.12/site-packages/google/genai/types.py:18308: SyntaxWarning: invalid escape sequence '\/'
    description="""Output only. The original name of the uploaded file, taken from the `Content-Disposition` header on upload. Between 1 and 255 characters. Control characters and the characters `<>:"|?*\/` are not accepted.""",

tests/test_llm.py::test_missing_keys
  /tmp/judge-20261114T002017Z/agent-arena/.venv/lib/python3.12/site-packages/google/genai/types.py:18346: SyntaxWarning: invalid escape sequence '\/'
    """Output only. The original name of the uploaded file, taken from the `Content-Disposition` header on upload. Between 1 and 255 characters. Control characters and the characters `<>:"|?*\/` are not accepted."""

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
321 passed, 8 skipped, 1 xfailed, 8 xpassed, 2 warnings in 30.00s
```

The README does not say what `make test` should print. Pytest itself passed. Eight `xpassed` results mean tests marked expected-fail are now passing; one is still `xfailed`; eight are skipped. The `SyntaxWarning` comes from the installed `google-genai` package, not from a command the README documents. `pytest -q` does not name the xfailed/xpassed tests, and the README does not say to re-run with `-v`, so those names were not collected.

### 6. `make eval AGENT=solver TIER=medium` — 0.319 s, exit 0

`2026-11-14T00:21:35Z`. stderr empty. stdout (complete):

```text
uv run --python 3.12 --extra dev --extra llm python -m canary.eval --agent solver --provider template --tier medium --seeds dev20
tier    agent                 n     score ± 95% CI  accuracy  accused  accuse day
medium  solver               20     +0.458 ± 0.155      0.65       13         8.4

wrote data/runs/solver-medium-20261114-002135/episodes.jsonl and meta.json
```

The README only names `AGENT=solver` and `TIER=medium`. The recipe also passed `--provider template` and `--seeds dev20`. Neither flag is documented. No API key was set. Twenty episodes finished in about a third of a second, which is consistent with no network call, but the README never says this command does not call Gemini.

Repeat at `2026-11-14T00:22:27Z`, wall clock 0.308 s, exit 0. Same score line. Only the artifact path changed (`solver-medium-20261114-002227`). On this machine the printed aggregate is stable across two runs. The README does not say whether that is guaranteed.

### 7. `make reproduce` — 0.056 s, exit 0, no table

`2026-11-14T00:21:43Z`. stderr empty. stdout (complete):

```text
uv run --python 3.12 --extra dev --extra llm python -m canary.eval --reproduce
TODO: --reproduce (judge table on frozen judge seeds) is not implemented yet
```

This is the judge path the status banner says "lands by Saturday morning." The run was Saturday 2026-11-14 00:21 UTC (02:21 in Europe/Helsinki). The command exits 0. A CI check or a judge who only looks at the exit code will treat a stub as success.

No API key was required, which matches the parenthetical in the README, because the command does not run the table it describes.

### 8. Chain `make setup && make reproduce` — 0.068 s, exit 0

`2026-11-14T00:23:35Z`, venv already warm. Setup printed:

```text
uv sync --python 3.12 --extra dev --extra llm
Resolved 79 packages in 1ms
Checked 52 packages in 0.32ms
```

Reproduce printed the same TODO as step 7. Exit 0.

### 9. Same four commands on `4d572ef` — README unchanged, test count moved

Worktree `/tmp/judge-rerun-20261114`, detached at `4d572ef49906aa5c6f3697c79362eeacabf4f443`. `uv` 0.13.8 already on `PATH`. Not a cold machine: the wheel cache from step 4 was reused. No `.env`.

`make setup`, `2026-11-14T00:26:02Z`, wall 0.324 s, exit 0.

stdout:

```text
uv sync --python 3.12 --extra dev --extra llm
```

stderr (complete). No download lines this time; 51 of 52 packages came from the local cache (`Prepared 1 package`):

```text
Using CPython 3.12.3 interpreter at: /usr/bin/python3.12
Creating virtual environment at: .venv
Resolved 79 packages in 1ms
   Building canary @ file:///tmp/judge-rerun-20261114
      Built canary @ file:///tmp/judge-rerun-20261114
Prepared 1 package in 253ms
Installed 52 packages in 38ms
 + annotated-types==0.8.0
 + anyio==4.16.0
 + attrs==26.1.0
 + canary==0.0.1 (from file:///tmp/judge-rerun-20261114)
 + certifi==2026.10.23
 + cffi==2.1.1
 + charset-normalizer==3.5.2
 + click==8.5.1
 + cryptography==50.0.2
 + distro==1.9.0
 + google-auth==2.62.2
 + google-genai==3.3.0
 + h11==0.16.0
 + httpcore2==2.16.0
 + httpx2==2.16.0
 + hypothesis==6.170.15
 + idna==3.20
 + iniconfig==2.3.1
 + jiter==0.19.0
 + jsonschema==4.26.0
 + jsonschema-specifications==2025.9.1
 + mcp==2.3.0
 + mcp-types==2.3.0
 + numpy==2.5.4
 + openai==3.51.0
 + opentelemetry-api==1.45.2
 + packaging==26.3
 + pluggy==1.7.0
 + pyasn1==0.6.5
 + pyasn1-modules==0.4.2
 + pycparser==3.12
 + pydantic==2.14.3
 + pydantic-core==2.50.4
 + pygments==2.21.0
 + pyjwt==2.15.1
 + pytest==9.2.0
 + python-dotenv==1.2.4
 + python-multipart==0.0.33
 + referencing==0.37.0
 + requests==2.34.2
 + rpds-py==2026.9.1
 + sniffio==1.3.1
 + sortedcontainers==2.4.0
 + sse-starlette==3.7.0
 + starlette==1.10.0
 + tenacity==9.1.4
 + truststore==0.10.5
 + typing-extensions==4.16.0
 + typing-inspection==0.4.5
 + urllib3==2.8.0
 + uvicorn==0.54.0
 + websockets==17.4
```

`make test`, wall 40.112 s, exit 0. stderr empty. stdout (complete):

```text
uv run --python 3.12 --extra dev --extra llm pytest -q
......................................s................................. [ 20%]
........................................................................ [ 41%]
.......................................................................X [ 61%]
xXXX...XXX.................X...................................s........ [ 82%]
.............................................................            [100%]
=============================== warnings summary ===============================
tests/test_llm.py::test_missing_keys
  /tmp/judge-rerun-20261114/.venv/lib/python3.12/site-packages/google/genai/types.py:18308: SyntaxWarning: invalid escape sequence '\/'
    description="""Output only. The original name of the uploaded file, taken from the `Content-Disposition` header on upload. Between 1 and 255 characters. Control characters and the characters `<>:"|?*\/` are not accepted.""",

tests/test_llm.py::test_missing_keys
  /tmp/judge-rerun-20261114/.venv/lib/python3.12/site-packages/google/genai/types.py:18346: SyntaxWarning: invalid escape sequence '\/'
    """Output only. The original name of the uploaded file, taken from the `Content-Disposition` header on upload. Between 1 and 255 characters. Control characters and the characters `<>:"|?*\/` are not accepted."""

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
338 passed, 3 skipped, 1 xfailed, 8 xpassed, 2 warnings in 39.24s
```

`make eval AGENT=solver TIER=medium`, wall 0.319 s, exit 0. stderr empty. Same score line as step 6. stdout:

```text
uv run --python 3.12 --extra dev --extra llm python -m canary.eval --agent solver --provider template --tier medium --seeds dev20
tier    agent                 n     score ± 95% CI  accuracy  accused  accuse day
medium  solver               20     +0.458 ± 0.155      0.65       13         8.4

wrote data/runs/solver-medium-20261114-002642/episodes.jsonl and meta.json
```

`make reproduce`, wall 0.054 s, exit 0. stderr empty. stdout:

```text
uv run --python 3.12 --extra dev --extra llm python -m canary.eval --reproduce
TODO: --reproduce (judge table on frozen judge seeds) is not implemented yet
```

`git diff --stat 54e1fa4 4d572ef` is 14 files, +971/−16, none of them `README.md` or `Makefile`. The test-count change arrived with that diff. Those files were not read to decide what to run.

### 10. Same commands on `6869c5b` — xfail/xpass gone, count moved again

Same worktree, `git checkout --detach 6869c5bf83d44dbb2236805341b17daf99329a4f`. Venv already present, so setup did not reinstall. `2026-11-14T00:27:51Z`.

`make setup`, wall 0.016 s, exit 0. stdout: `uv sync --python 3.12 --extra dev --extra llm`. stderr:

```text
Resolved 79 packages in 1ms
Checked 52 packages in 0.31ms
```

`make test`, wall 34.951 s, exit 0. stderr empty. stdout (complete):

```text
uv run --python 3.12 --extra dev --extra llm pytest -q
......................................s................................. [ 20%]
........................................................................ [ 41%]
........................................................................ [ 61%]
................................................................s....... [ 82%]
..............................................................           [100%]
348 passed, 3 skipped in 34.43s
```

`make eval AGENT=solver TIER=medium`, wall 0.321 s, exit 0. stderr empty. stdout:

```text
uv run --python 3.12 --extra dev --extra llm python -m canary.eval --agent solver --provider template --tier medium --seeds dev20
tier    agent                 n     score ± 95% CI  accuracy  accused  accuse day
medium  solver               20     +0.458 ± 0.155      0.65       13         8.4

wrote data/runs/solver-medium-20261114-002826/episodes.jsonl and meta.json
```

`make reproduce`, wall 0.057 s, exit 0. stderr empty. stdout:

```text
uv run --python 3.12 --extra dev --extra llm python -m canary.eval --reproduce
TODO: --reproduce (judge table on frozen judge seeds) is not implemented yet
```

`git diff --stat 4d572ef 6869c5b` is 4 files (`docs/EXPLOITS.md`, `docs/reports/integrity.md`, `tests/test_integrity_baselines.py`, `tests/test_integrity_hunter.py`), +47/−9. README and Makefile still untouched. Those files were not read to decide what to run.

### 11. `make test` on `1a89015` — one xfail returns

`origin/justSilas` moved once more, to `1a89015a1bde35ea71148b82f9294a8fc92d6c6e` (2026-11-14 02:27:17 +0200, `Merge justSilas-integrity: solver tier-ordering guard`). README blob still unchanged. Only `make test` was re-run, on the same warm worktree. Wall 38.099 s, exit 0. stderr empty. stdout (complete):

```text
uv run --python 3.12 --extra dev --extra llm pytest -q
......................................s................................. [ 20%]
........................................................................ [ 41%]
....................................x................................... [ 61%]
.................................................................s...... [ 82%]
...............................................................          [100%]
348 passed, 3 skipped, 1 xfailed in 37.56s
```

Eval and reproduce were not re-run on this tip. `Makefile` still had no diff across the earlier tips, and the commit subject is a test-only guard. The lowercase `x` in the progress line is an expected failure, not an xpass.

## Claimed vs observed

The README states no expected score, accuracy, seed count, or row values. "Claimed" below is only what the README text says.

| What | Claimed in README | Observed |
| --- | --- | --- |
| `make setup` | Comment: `uv, Python 3.12`. No install instructions, no success criterion. | First run fails: `uv` missing (make exit 2 / recipe 127). After installing uv 0.13.8 outside the README: exit 0 in 0.692 s, CPython 3.12.3, 52 packages, venv at `.venv`. |
| `make test` | Nothing. The target is named and not described. | Exit 0 on all four tips. `54e1fa4`: 30.814 s, `321 passed, 8 skipped, 1 xfailed, 8 xpassed, 2 warnings in 30.00s`. `4d572ef`: 40.112 s, `338 passed, 3 skipped, 1 xfailed, 8 xpassed, 2 warnings in 39.24s`. `6869c5b`: 34.951 s, `348 passed, 3 skipped in 34.43s`. `1a89015`: 38.099 s, `348 passed, 3 skipped, 1 xfailed in 37.56s`. |
| `make eval AGENT=solver TIER=medium` | Nothing numeric. Does not mention provider or seeds. | Exit 0 in 0.319 s and 0.308 s on `54e1fa4`, 0.319 s on `4d572ef`, 0.321 s on `6869c5b`. Recipe adds `--provider template --seeds dev20`. Table: n=20, score **+0.458 ± 0.155**, accuracy **0.65**, accused **13**, accuse day **8.4**. All four runs matched. |
| `make reproduce` | "judge table: reference, 3 agent runs, do-nothing, stop-early (no API keys needed)" | Exit 0 in 0.056 s on `54e1fa4` (0.068 s chained with a warm setup), 0.054 s on `4d572ef`, 0.057 s on `6869c5b`. stdout is only `TODO: --reproduce (judge table on frozen judge seeds) is not implemented yet`. No rows for reference, agents, do-nothing, or stop-early. No API key prompt. |
| Gemini "at its core" | Opening sentence: the environment has "Gemini at its core." | The only scored command that runs does not ask for `GEMINI_API_KEY` and passes `--provider template`. No Gemini result was produced. Whether `template` is a non-LLM stand-in is an inference from the flag name, the empty key, and the 0.3 s runtime. The README does not say. |
| API keys | Reproduce: "no API keys needed". No other key guidance. | Correct for the stub. Also none needed for `make test` or the template eval. `.env.example` documents two keys the README never mentions. Not a blocker for the commands that exist today. |
| Harbor / OpenCode | Not in the README. | Not run. |
| Runtime warning | Status calls the branch an "overnight build". No runtime estimate for the make targets. | Once `uv` exists, the whole README sequence is about 32–41 s on these three tips. The overnight wording describes the build status, not the judge runtime. The missing piece is the stub, not a long job. |

## Unclear or wrong README sentences

Quoted in full.

1. `make setup        # uv, Python 3.12`

   Does this install `uv` and Python 3.12, or require them? Which `uv` version? Is a system `python3.12` required, or will `uv` fetch one? On this machine the answer was: require both, install neither, and fail immediately if `uv` is absent.

2. `Status: overnight build in progress on branch `justSilas`. The judge path (`make reproduce`) lands by Saturday morning.`

   Which Saturday, in which timezone? Read on Saturday 2026-11-14 00:21 UTC, the judge path is still a TODO. A judge cannot tell whether they are early or whether the promise is already stale. The banner is the only place that says the command might not work yet, and it is not specific enough to be actionable.

3. `make reproduce    # judge table: reference, 3 agent runs, do-nothing, stop-early (no API keys needed)`

   "3 agent runs" does not name the agents, the model, the seed list, or the metric. "reference" is earlier called "a Bayesian canary-trap solver" but is not tied to `AGENT=solver`. There is no expected number, so a future implementation cannot be checked against this README. The parenthetical about API keys is the only operational requirement, and it is satisfied by not implementing the command.

4. `An RL environment for AfterQuery's **Break the Agent** (Junction 2026), with Gemini at its core.`

   The judge commands never say how Gemini is invoked, which model, or that the published eval path passes `--provider template`.

5. `make eval AGENT=solver TIER=medium`

   No definition of `TIER`, no list of legal tiers, no statement of what "solver" is relative to the reference run, no expected score. The seeds and provider that actually run are invisible.

6. `Docs: [PLAN](docs/PLAN.md) · [CONTRACT](docs/CONTRACT.md) · [TEAM](docs/TEAM.md) · [EXPLOITS](docs/EXPLOITS.md) · [brief](CHALLENGES-AFTERQUERY-GEMINI.md)`

   It is unclear whether a judge must read these to reproduce results. They were not read. The links themselves resolve to files.

## Other craft notes

- **False green.** An unimplemented judge command that exits 0 will pass a "did `make reproduce` work?" check. This is the costliest polish failure in the README path.
- **Commit subject vs command line, neither in the README.** `git log -1` says `JUDGE_SEEDS 40`. `make eval` printed `--seeds dev20`. The README says neither. This was not used to change the run.
- **Test count is not pinned, and it moved during this session.** Same README bytes: 321 passed (`54e1fa4`), 338 passed (`4d572ef`), 348 passed with a clean summary (`6869c5b`), then 348 passed and 1 xfailed again (`1a89015`). The 8 xpassed and the `google-genai` `SyntaxWarning` were real on the first two tips and were gone by `6869c5b`. A judge who clones later cannot tell which summary the README considers success.
- **Undocumented entry points a clone listing shows immediately.** `harbor/` at repo root, `.env.example`, `docs/reports/env.md`, and several other `docs/reports/*.md` files. None are linked from the README. Easy for a judge to wonder which one is authoritative.
- **OpenCode is in `git log`, not in the README.** `git log --oneline` includes `frontier: OpenCode default model openai/gpt-5.6-sol`. The README never says OpenCode. It was not run. Same for Harbor: the directory is there, the README is silent. A judge following only `README.md` will not execute either.
- **No broken doc links** among the five README links. Checked by file presence only.
- **No secret was required and none was created.** Logs captured here contain no credentials. `.env` was not written.
- **Determinism.** Two eval runs matched. One sample is not a proof, and the README does not state a seed policy. Artifact directories are timestamped, so the working tree changes on every eval even when the score does not. Those paths appear gitignored (`git status` was clean after the runs). The README does not say that.
- **`python` vs `python3`.** Unversioned `python` is missing. It did not break these targets because `uv` selected `/usr/bin/python3.12`. Worth one line in the prerequisites so the next clean image does not guess.
- **No runtime surprise.** Judges do not need a "this takes hours" warning for these four targets. They do need a warning that `make reproduce` is a stub.

## Suggested fixes, by severity

Wording is proposed only. This report does not change the Makefile or the evaluator.

### Blocker — `make reproduce` is a stub and exits 0

The README promises a judge table. The program prints a TODO and returns success. Until the table exists, the command must fail, and the README must not describe a table that is not produced.

Proposed README replacement for the status banner and the reproduce line:

```markdown
> Status (checked 2026-11-14): `make setup`, `make test`, and `make eval AGENT=solver TIER=medium` run locally without API keys. `make reproduce` is not implemented.

make reproduce    # NOT IMPLEMENTED. Must exit non-zero until the judge table exists.
```

Proposed behavior: `python -m canary.eval --reproduce` should exit 2 when the table is not implemented, and Make should propagate that. When it is implemented, replace the line with the real contract, for example:

```markdown
make reproduce    # no API keys. Frozen judge seeds. Prints rows: reference, <name>, <name>, <name>, do-nothing, stop-early.
                  # Columns: tier, agent, n, score ± 95% CI, accuracy, accused, accuse day.
                  # Expected numbers for commit <SHA> are in the table below. A diff fails the target.
```

Name the three agents. Publish the expected numbers next to the command. Do not leave "3 agent runs" as the specification.

### High — a clean machine fails the first command, and the README does not say so

`uv` is a hard dependency. `make setup` does not install it. Python 3.12 happened to be present here; the README also does not say what to do when it is not.

Proposed section, above the command block:

```markdown
## Prerequisites

- Python 3.12 available as `python3.12` (3.12.3 worked). `make setup` does not install Python.
- [uv](https://docs.astral.sh/uv/getting-started/installation/) on `PATH`. `make setup` does not install uv. Tested with uv 0.13.8:

  curl -LsSf https://astral.sh/uv/install.sh | sh
  source "$HOME/.local/bin/env"

- No API key for `make test`, `make eval AGENT=solver TIER=medium`, or `make reproduce`.
  Copy `.env.example` to `.env` only to run a live Gemini or OpenAI agent. Never commit `.env`.

## Judge commands

From a fresh clone these four commands are the whole judge path. Expected wall clock after uv is installed is under a minute on a 4-core machine. `make setup` is the slow step only on the first run (package download).
```

### High — Gemini is the headline, and the command a judge can score never says it is not calling Gemini

Either document the template path as the offline reference, or make the README's scored command the Gemini one and name the key.

```markdown
make eval AGENT=solver TIER=medium
# Offline reference. Does not call Gemini or OpenAI.
# Makefile adds: --provider template --seeds dev20
# Last observed on Python 3.12.3 / uv 0.13.8 (commit 54e1fa4):
#   n=20  score +0.458 ± 0.155  accuracy 0.65  accused 13  accuse day 8.4
# Two runs matched. Re-running writes a new data/runs/<timestamp>/ directory.

# Live model (optional, spends API quota, not part of the default judge score):
#   cp .env.example .env    # set GEMINI_API_KEY
#   make eval AGENT=solver TIER=medium PROVIDER=gemini
```

Use whatever the real provider flag is. The point is to stop a judge discovering `--provider template` only by reading Make's echo.

### Medium — status banner has no date and no timezone

Replace "lands by Saturday morning" with a date, a timezone, and the current fact. The proposed status line under the blocker item does that. If the table lands later, update the same line in the same commit that implements it. A banner that survives past its deadline reads as abandoned.

### Medium — `make test` has no expected result, and the suite is quietly dirty

```markdown
make test
# Expect a zero exit. Pin the summary in this README and change it in the same commit as the tests.
# Observed 2026-11-14 / Python 3.12.3, identical README bytes:
#   54e1fa4: 321 passed, 8 skipped, 1 xfailed, 8 xpassed, 2 warnings in 30.00s
#   4d572ef: 338 passed, 3 skipped, 1 xfailed, 8 xpassed, 2 warnings in 39.24s
#   6869c5b: 348 passed, 3 skipped in 34.43s
#   1a89015: 348 passed, 3 skipped, 1 xfailed in 37.56s
```

`6869c5b` cleared the xfail/xpass/warning noise. `1a89015` put a single xfail back. The remaining gap is that the README still does not say which summary is the expected one, so the next test-only commit will move the number again with no doc change.

### Medium — seeds are undocumented and the commit subject disagrees with the eval flag

Pick one seed set, put it in the README, and make `make reproduce` and `make eval` print it.

```markdown
Eval seeds: `dev20` (20 development episodes). Judge seeds: `JUDGE_SEEDS` (40), used only by `make reproduce`.
Both are deterministic given the seed list. The ± column is a confidence interval, not run-to-run noise.
```

If `JUDGE_SEEDS 40` in the commit subject is already wrong, fix the subject on the next commit so judges who type `git log -1` are not sent looking for a third seed list.

### Low — point at the files a clone already shows

```markdown
Repo map that is not the judge path: `harbor/` (not used by the make targets), `.env.example` (live model keys), `docs/PLAN.md` and the other linked docs (design notes). Reading them is optional. They are not required to run the four commands above.
```

If Harbor or OpenCode is supposed to be part of judging, this README does not say so. Add the exact commands and the expected output in this file. A judge who only follows `README.md` will not find them.

### Low — unversioned `python`

One prerequisite bullet is enough: "Targets call `python` inside `uv run`. A system `python` shim is not required. `python3.12` is."

## Bottom line for scoring

`make test` and the offline solver eval do run, with no secrets. The eval number was stable across four runs and three tips (+0.458 ± 0.155, accuracy 0.65, n=20). The test summary was not: 321 passed, then 338, then 348, then 348 with one xfailed, same README, over about ten minutes of `justSilas` moving. That part is real, and it is not pinned.

The command the README labels as the judge path does not reproduce anything. It exits 0 on a TODO. Combined with no published expected numbers, a second judge cannot confirm a result, only confirm that the stub is still a stub. That is the issue to fix before craft points for the judge experience.
