# Reproducibility, World Secrets, and Statistical Verification

Technical reference for judges evaluating Canary (`TIERS_VERSION = "v1.4"`). Covers deterministic world derivation, fail-closed judge secrets, expected run-to-run statistical bands, replay verification, runtime knobs, and measured keyless timings.

---

## 1. Deterministic World Derivation and Secret Modes

Every Canary episode is a pure deterministic function of `(tier, seed, world_key, action_sequence)`. In [`canary/world.py`](../canary/world.py), the 64-bit RNG seed for `random.Random` is derived via HMAC-SHA256:

```text
world_seed(tier, seed) = int.from_bytes(HMAC-SHA256(key, f"{tier}:{seed}")[:8], "big")
```

`generate_world(tier, seed, params)` uses that RNG to construct the company roster, departments, clearances, decoy, mole identity, and daily document schedule. All environment transitions and server-side ledger scores in [`canary/env.py`](../canary/env.py) follow deterministically from `world_seed` and the agent's tool calls.

### Seed Partitions and Key Resolution (`canary/rules.py`, `canary/world.py`)

| Seed Partition | Range | Count | Default Key Without Secret | Replay Behavior |
|---|---|---:|---|---|
| `DEV_SEEDS` | `0..9999` | 10,000 | Fixed `b"public"` | Bit-for-bit deterministic on every machine with no secret |
| `TRAIN_SEEDS` | `100000..199999` | 100,000 | Fixed `b"public"` | Bit-for-bit deterministic on every machine with no secret |
| `HELDOUT_SEEDS` | `800000..800199` | 200 | Fail closed (fresh 32-byte random secret) | Statistical without secret; bit-identical when secret is supplied |
| `JUDGE_SEEDS` | `900000..900039` | 40 | Fail closed (fresh 32-byte random secret) | Statistical without secret; bit-identical when secret is supplied |

Why the split exists:
- **Committed frontier episodes replay deterministically.** The headline v1.4 paired comparison (`gemini-4-carbon` vs `solver`, `n = 30`, seeds `0..29` in [`data/runs/committed/v1.4/paired_table_gemini.md`](../data/runs/committed/v1.4/paired_table_gemini.md)) uses `DEV_SEEDS`, which are keyed by `b"public"`. Any judge clone can replay every step and re-verify every server score offline with zero API keys and zero secrets.
- **Judge and held-out seeds fail closed without a secret ([EXPLOITS #24](EXPLOITS.md)).** For `900000..900039` and `800000..800199`, `_key(seed)` resolves in order: (1) in-process `set_world_secret(...)`, (2) `CANARY_WORLD_SECRET`, (3) uncommitted `data/worlds/judge/SALT` (`0600`). If none is set, it never falls back to `b"public"` (which would let an attacker pre-compute the mole from public code); instead:
  - A keyless `make reproduce` draws one fresh 32-byte secret (`os.urandom(32)`) in memory, prints only its 12-hex-char SHA-256 fingerprint, and shares that secret across `solver`, all 6 baselines, and the anti-cheat probes so every policy in that invocation plays the exact same 40 worlds per tier (paired comparison).
  - Each `python harbor/build.py` run generates a fresh 32-byte secret (`secrets.token_hex(32)`) and bakes it as a `0600` file (`data/worlds/judge/SALT` via `CANARY_WORLD_SECRET_FILE`) into the `canary-server` sidecar image only (never into the `main` agent container or environment variables), plus a fresh 32-byte HMAC ledger signing key shared only between sidecar and verifier.
- **Bit-identical judge-seed reproduction.** Supplying any fixed string makes two `make reproduce` runs produce byte-identical `results/latest/judge_episodes.jsonl` outputs:

```bash
CANARY_WORLD_SECRET=<any-string> make reproduce
```

For Harbor builds, `python harbor/build.py --secret-file <path-to-16+-byte-file>` pins the sidecar world secret across builds.

---

## 2. Measured Statistical Bands Across Fresh World Secrets

Because keyless runs draw fresh judge-world secrets, `solver` and stochastic baseline means move within tight, pre-measured distributions, while non-accusing policies remain invariant at `0.000`.

### A. In-Process 40-Judge-Seed Bands (`make reproduce` and `make accept`)

Measured over **300 fresh 32-byte secrets** on all **40 judge seeds (`900000..900039`)** per tier via `scripts/solver_spread.py` (artifacts in [`results/solver_range/`](../results/solver_range/)). `make accept` (`scripts/judge_accept.sh`) enforces a `mean +/- 4 * sd` gate (`K_SD = 4.0`, honest false-fail probability `< 1e-4`, plus `score <= 0` for `guess_day1`) and exact `0.000` (`abs(score) < 1e-9`) for `do_nothing` and `stop_early`:

| Policy | Tier | Seeds | Secrets | Mean | SD | 90% Band (`p5` to `p95`) | Min / Max (300 runs) | `make accept` 4-SD Gate |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| `solver` | `easy` | 40 | 300 | `+0.774` | `0.020` | `[+0.741, +0.804]` | `+0.692 / +0.821` | `[+0.693, +0.856]` (`[+0.69, +0.86]`) |
| `solver` | `medium` | 40 | 300 | `+0.630` | `0.040` | `[+0.560, +0.687]` | `+0.498 / +0.725` | `[+0.471, +0.789]` (`[+0.47, +0.79]`) |
| `solver` | `hard` | 40 | 300 | `+0.567` | `0.050` | `[+0.485, +0.640]` | `+0.406 / +0.669` | `[+0.369, +0.766]` (`[+0.37, +0.77]`) |
| `guess_day1` | `easy` | 40 | 300 | `-0.839` | `0.090` | `[-0.950, -0.700]` | `-1.000 / -0.550` | `[-1.200, -0.477]` (`[-1.20, -0.48]`, `<= 0`) |
| `guess_day1` | `medium` | 40 | 300 | `-0.906` | `0.064` | `[-1.000, -0.800]` | `-1.000 / -0.700` | `[-1.164, -0.648]` (`[-1.16, -0.65]`, `<= 0`) |
| `guess_day1` | `hard` | 40 | 300 | `-0.953` | `0.045` | `[-1.000, -0.850]` | `-1.000 / -0.800` | `[-1.132, -0.774]` (`[-1.13, -0.77]`, `<= 0`) |
| `do_nothing` | `easy, medium, hard` | 40 | all | `+0.000` | `0.000` | `[+0.000, +0.000]` | `+0.000 / +0.000` | exact `0.000` (`abs(s) < 1e-9`) |
| `stop_early` | `easy, medium, hard` | 40 | all | `+0.000` | `0.000` | `[+0.000, +0.000]` | `+0.000 / +0.000` | exact `0.000` (`abs(s) < 1e-9`) |

Note: episode scores lie in `[-1.0, +1.0]`, so `guess_day1`'s arithmetic `mean - 4 * sd` sits below `-1.000` while realized 40-seed means bottom out at `-1.000`.

### B. Harbor Dataset Oracle Bands (`harbor/build.py` + `harbor run`)

Measured over **200 simulated Harbor builds** (`scripts/oracle_range.py`, artifacts in [`results/oracle_range_v1.4.json`](../results/oracle_range_v1.4.json) and [`results/oracle_range_v1.4.md`](../results/oracle_range_v1.4.md)). The default `python harbor/build.py` judge set builds **10 `hard` tasks (`900000..900009`)**:

| Harbor Agent / Policy | Tier | Tasks (`k`) | Builds | Mean | SD | 90% Band (`p5` to `p95`) | Median (`p50`) | `P(mean < 0)` |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| `oracle` (`solver`) | `hard` (judge set) | `10` | 200 | `+0.569` | `0.094` | `[+0.39, +0.68]` (`+0.393` to `+0.678`) | `+0.600` | `0.0%` |
| `oracle` (`solver`) | `hard` | `20` | 200 | `+0.568` | `0.064` | `[+0.454, +0.656]` | `+0.585` | `0.0%` |
| `oracle` (`solver`) | `hard` | `3` | 200 | `+0.547` | `0.208` | `[+0.047, +0.723]` | `+0.613` | `1.5%` |
| `oracle` (`solver`) | `hard` | `2` | 200 | `+0.533` | `0.274` | `[-0.211, +0.745]` | `+0.620` | `10.5%` |
| `oracle` (`solver`) | `medium` | `10` | 200 | `+0.623` | `0.086` | `[+0.469, +0.742]` | `+0.633` | `0.0%` |
| `ORACLE_POLICY=do_nothing` | `hard, medium` | `2, 3, 10, 20` | 200 | `+0.000` | `0.000` | `[+0.000, +0.000]` | `+0.000` | `0.0%` |
| `ORACLE_POLICY=stop_early` | `hard, medium` | `2, 3, 10, 20` | 200 | `+0.000` | `0.000` | `[+0.000, +0.000]` | `+0.000` | `0.0%` |
| `ORACLE_POLICY=cheat_probe` | `hard, medium` | any | all | `+0.000` | `0.000` | `[+0.000, +0.000]` | `+0.000` | `0.0%` |

- **Why 10 hard tasks:** one wrong accusation (`-1.0`) shifts a 2-task mean by `-0.5` (`P(mean < 0) = 10.5%` even at ~96% solver accuracy), whereas across 10 tasks `P(mean < 0) = 0.0%` and 90% of builds land in `[+0.39, +0.68]`.
- **Harbor CLI rules (verified by `scripts/verify_doc_commands.py` and [`harbor/README.md`](../harbor/README.md)):** never pass any `CANARY_` variable via `--ae` into `main` (`harbor/check_isolation.sh` rejects any `CANARY_` env var in the agent container; use `ORACLE_POLICY` only), and always include `--api-key-name GOOGLE_GENERATIVE_AI_API_KEY` when running `-a opencode` with `-m google/...` so Harbor forwards the key instead of failing at model load with reward `0`:

```bash
uv run python harbor/build.py
harbor run -p harbor/dataset -a oracle -n 4
harbor run -p harbor/dataset -a oracle --ae ORACLE_POLICY=do_nothing -n 4
harbor run -p harbor/dataset -a oracle --ae ORACLE_POLICY=stop_early -n 4
harbor run -p harbor/dataset -a oracle --ae ORACLE_POLICY=cheat_probe -n 4
GOOGLE_GENERATIVE_AI_API_KEY=<key> harbor run -p harbor/dataset -a opencode \
    -m google/gemini-4-carbon --api-key-name GOOGLE_GENERATIVE_AI_API_KEY -n 4
```

---

## 3. Replay Verification and Provenance Integrity

1. **Full-corpus anti-cheat replay (`make reproduce`).** `canary.redteam.anticheat.replay_committed` replays **989 of 999** non-superseded committed episodes step-by-step on a fresh `Env` under each run's frozen tier version (`v1.4`, `v1.3`, or `v1.2` via `canary.rules.tiers_version`), verifying **49,549** recorded tool results and final scores with **0 mismatches** (the other 10 episodes are historical `v1.2` Grok runs on secret-keyed judge seeds `900000..900004`). It also checks all **37** committed Harbor trials and **13** job summaries in [`results/harbor/`](../results/harbor/) for ledger/verifier reward equality, HMAC signatures, `ISOLATION OK`, and empty `cheat_probe` hole lists.
2. **Standalone `v1.4` transcript replay (`scripts/verify_replay.py`).** Re-executes all **410** valid `v1.4` committed episodes in fresh `Env` instances and verifies exact score and accusation parity (`410/410 episodes replay-verified`).
3. **Bayesian counterfactual & luck-adjusted audit (`scripts/failure_analysis_v14.py --check`).** Replays the 90 `v1.4` hard episodes (`opencode`, `inproc`, `solver` on seeds `0..29`), recomputes exact `SolverPolicy` posteriors and luck-adjusted expected values, and diffs against [`results/failure_analysis_v1.4.json`](../results/failure_analysis_v1.4.json).

---

## 4. Runtime Knobs, Output Isolation, and Zip-Archive Support

| Knob / Feature | Default | Behavior |
|---|---|---|
| `CANARY_WORLD_SECRET` | unset | Unset = fresh 32-byte per-run secret (`statistical` mode); set to any string = deterministic `exact` mode |
| `REPRO_ANTICHEAT` | `1` | Set `REPRO_ANTICHEAT=0` to skip the anti-cheat battery and replay check (~19-21 s table-only run) |
| `REPRO_FAST` | `0` | Set `REPRO_FAST=1` to run the paired table on 5 judge seeds (`900000..900004`); when `REPRO_ANTICHEAT=1`, the anti-cheat verdict still evaluates all 40 judge seeds to avoid 5-seed false alarms on negative-EV probes |
| `REPRO_SEEDS` / `--repro-seeds` | `40` | Explicit number of judge seeds per tier (`1..40`) for `python -m canary.eval --reproduce` |
| `REPRO_EPISODE_TIMEOUT` | `60` | Per-episode SIGALRM wall-clock timeout (seconds) during in-process reproduction |
| `MCP_PORT` | `8765` | Preferred local bind port for `make mcp` (`scripts/mcp_port.sh`) |
| `MCP_PORT_FALLBACK` | `1` | When `1`, `make mcp` scans `MCP_PORT+1..MCP_PORT+50` if busy and prints the selected port; `0` fails fast |

- **Output isolation (`results/latest/`).** `make reproduce` writes `judge_table.md`, `judge_episodes.jsonl`, `gap_chart.png`, `exploits.json`, and `exploits.md` into `results/latest/`, which is gitignored. Tracked files in `results/` stay untouched (`git status --porcelain` remains clean; only `make reproduce-update` / `--update-committed` updates `results/`). `harbor/dataset*/` is also gitignored so build-time `SALT` and `ledger_key` files are never tracked.
- **Zip-archive support without `.git`.** Evaluating an unpacked GitHub `.zip` archive (no `.git/` directory or `git` binary) works out of the box: `pyproject.toml` uses static `version = "0.0.1"` (`hatchling`), `canary.eval.git_sha()` falls back cleanly to `"unknown"`, `canary/reproduce.py` resolves run recency and provenance from committed `meta.json` ISO timestamps and `git_sha` fields rather than `git log` or filesystem `mtime`, and git-dependent tests either inspect `.gitignore` directly or skip cleanly (see [`results/fresh_clone/README.md`](../results/fresh_clone/README.md)).

---

## 5. Measured Keyless Wall-Clock Timings

Measured directly on a Linux x86_64 host (`Linux 6.12.0-211.49.1.el10_2.x86_64`, `Intel(R) Xeon(R) CPU E5-2620 v3 @ 2.40GHz`, Python `3.12.16`, single process, 0 API keys, 0 Gemini calls, shared multi-worker load):

```bash
PYTHONPATH=. python scripts/check_craft_consistency.py
PYTHONPATH=. python scripts/verify_doc_commands.py
PYTHONPATH=. python harbor/build.py --out /tmp/canary-harbor-ds
PYTHONPATH=. python scripts/verify_replay.py data/runs/committed/v1.4
PYTHONPATH=. python scripts/failure_analysis_v14.py --check
PYTHONPATH=. python scripts/audit_submission.py
CANARY_WORLD_SECRET=repro-check REPRO_ANTICHEAT=0 PYTHONPATH=. python -m canary.eval --reproduce
CANARY_WORLD_SECRET=repro-check PYTHONPATH=. python -m canary.eval --reproduce
PYTHONPATH=. python -m canary.redteam.anticheat --verify results/anticheat/exploits.json
```

| Keyless Command | Scope | Wall-Clock (Linux x86_64) | Exit / Result |
|---|---|---:|---|
| `python scripts/check_craft_consistency.py` | Links, headline number provenance, results hygiene | `0.28 s` | `0` (`0 FAIL`) |
| `python harbor/build.py --out <dir>` | Generate 10-task `hard` Harbor judge dataset + `0600` keys | `0.36 s` | `0` (`wrote 10 task(s)`) |
| `python scripts/verify_doc_commands.py` | Makefile targets, script/module paths, CLI flags, Harbor rules | `0.73 s` | `0` (`0 FAIL`) |
| `python scripts/verify_replay.py data/runs/committed/v1.4` | Deterministic replay of all committed `v1.4` episodes | `3.95 s` | `0` (`410/410` verified) |
| `python scripts/failure_analysis_v14.py --check` | Replay + exact Bayesian counterfactual check (`v1.4` hard, `n=30`) | `4.61 s` | `0` (`reproduces`) |
| `python scripts/audit_submission.py` | Secret scan, frozen tier hashes (`a8f99c2537c91d72`), Harbor static audit | `5.53 s` | `0` (`0 FAIL`) |
| `REPRO_ANTICHEAT=0 python -m canary.eval --reproduce` | 840 paired judge episodes + committed frontier table (`results/latest/`) | `18.97 - 21.09 s` | `0` (bit-identical with fixed secret) |
| `REPRO_FAST=1 python -m canary.eval --reproduce` | 5-seed paired table + full 40-seed anti-cheat + 989-episode replay | `106.08 s` | `0` (`ANTI-CHEAT: every probe blocked`) |
| `python -m canary.eval --reproduce` (`make reproduce`) | Full 40-seed paired table + anti-cheat + 989-episode + 37-Harbor check | `115.59 s` | `0` (`52 s` on unloaded macOS arm64; [`results/fresh_clone/`](../results/fresh_clone/README.md)) |
| `python -m canary.redteam.anticheat --verify results/anticheat/exploits.json` | Rerun 99 anti-cheat rows (40 seeds x 3 tiers, public test secret) and diff | `159.54 s` | `0` (`0 differences`) |
