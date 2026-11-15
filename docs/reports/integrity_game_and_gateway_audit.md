# Game/Play Boundary and PR 41 Gemini Gateway, Replay, and Swarm Artifact Audit

## 1. Headline Summary

- **Base commit audited:** `668a196b` (`origin/fr8/canary/integrity`, merged with `justSilas@cf394894`, zero protected or upstream files modified).
- **Execution discipline:** `0` live Gemini / OpenAI / external network LLM calls; `--workers 1` single-process sequential execution (`<= 1` local replay gateway subprocess at any instant, cleaned up in `finally`); scratch confined to `/tmp/opencode/w2` and deleted after execution; total wall time `180.067s`.
- **Panel Fix A + D honesty alignment:** Canary's `v1.4` `hard` headline gap is led by raw `65% [24%, 98%]` (`+0.322` vs solver `+0.499`, `n=30`) before luck-adjusted `72% [52%, 91%]`; dev seeds `0-29` are a post-hoc lock (`671ed96` committed 28 s after `8fd4dec`), not pre-registered; the `hard` canary clearance rule never binds (`W4`); `ToolResult.error` constants remain unchanged (`8b9afa61`); and `1bc3e281`'s post-measurement `data.detail` + W1 careful-mole wording update (disclosed as post-15-Nov changes after all committed frontier runs, with pre-`1bc3e281` replay normalized in `1bc3e281` and `668a196b`) are verified directly below.
- **Surface A (`canary/play.py` + `game/build.py` + `1bc3e281` `data.detail`):** **PASS** (`5.683s`). `canary.play` refused `40/40` judge seeds (`900000-900039`), `4/4` cross-tier judge boundaries, `30/30` held-out seeds (`800000-800029`), `7/7` `<3000` dev seeds (protecting the post-hoc locked `0-29` benchmark seeds), `8/8` `>=10000`/huge seeds, `9/9` invalid `--tier`/`--name`/flag inputs, and `10/10` env-var spoofing subprocesses with exit code `2` and `0` secret/truth leaks. `game/build.py` shipped `19` files (`15` Python modules matching `py/manifest.json`), `0` forbidden paths, `0` secret matches, and `18/18` `1bc3e281` `data.detail` codepaths + `40/40` `mole`/`decoy`/`innocent` role-parity checks with `0` secret/mole-truth leaks.
- **Surface B (`canary.gemini.gateway` + `canary.gemini.lab_replay`):** **`12/12` wire/boundary vectors held** (`161.984s`), **`0` outbound upstream calls** verified by a local `UpstreamSpy` HTTP listener with all API key env vars unset, and **`11`/`11`** recorded showcase + ladder runs reproduced byte- and step-deterministically across `614` `.json.gz` cache entries.
- **Surface C (`results/gemini/**` Swarm, `eb363eb9` 587-Episode Ladder, and Failure Atlas):** **PASS** (`12.158s`). Scanned `849` files (`746` `.gz` archives, `134.75 MB` uncompressed) with **`0` leaked API keys/tokens** and `0` parse errors; verified exact swarm accounting (`91` primary finished = `75` whitebox + `16` blackbox, plus `9` MCP re-runs = `100` scored attempts, `0` real-wave exploits vs `4/4` positive-control dev-seed exploits, `16/16` positive-score attempts accounted for); verified `justSilas@eb363eb9`'s canonical `587`-episode Gemini ladder (`42` cells, `36164` ledger calls, `618` run IDs, plus `5` hosted Gemma episodes) and `111`-episode Failure Atlas.

## 2. Keyless Reproduce Commands

```bash
/tmp/fleet-silas/shared/agent-arena-venv/bin/python scripts/integrity_game_and_gateway_audit.py --workers 1 --scratch-root /tmp/opencode/w2 --write-report docs/reports/integrity_game_and_gateway_audit.md
/tmp/fleet-silas/shared/agent-arena-venv/bin/python -m pytest -p no:cacheprovider -q tests/test_integrity_game_and_gateway_audit.py
```

## 3. Surface A: Interactive CLI (`canary/play.py`) and Browser Game (`game/build.py`)

### 3.1 `canary.play` Seed, Spoofing, and Secrecy Matrix

| Probe family | Tested | Result | Exit / behavior | Truth or secret leak |
|---|---:|---|---|---|
| Judge seeds (`900000..900039`, medium) | 40 | 40/40 refused | Exit `2` (`ap.error`, before `Env`) | `0` |
| Judge boundaries on `easy` and `hard` (`900000, 900039`) | 4 | 4/4 refused | Exit `2` (`ap.error`, before `Env`) | `0` |
| Held-out seeds (`800000..800029`, medium) | 30 | 30/30 refused | Exit `2` (`ap.error`, before `Env`) | `0` |
| Low dev seeds `<3000` (`0,1,7,42,300,1999,2999`; covers post-hoc locked `0-29`) | 7 | 7/7 refused | Exit `2` (`seed >= 3000` gate) | `0` |
| Out-of-range / train / huge ints (`10000..2^128`) | 8 | 8/8 refused | Exit `2` (`seed in DEV_SEEDS` gate) | `0` |
| Arabic-Indic judge digits (`\u0669\u0660\u0660\u0660\u0660\u0660` -> `900000`) | 1 | 1/1 refused | Exit `2` (`ap.error`) | `0` |
| Negative / non-digit `--seed` (`-1`, `-900000`, `3000.5`, `3e3`, `NaN`, `abc`, `dev20`) | 9 | 9/9 safe dev fallback | Coerced to random dev seed `3000..3999` (Makefile `SEEDS=dev20` guard) | `0` |
| Invalid `--tier` (`hard_forge`, `hard_rl`), `--name` (`../evil`, `a/b`), or flag | 9 | 9/9 refused | Exit `2` (`argparse` / `ap.error`) | `0` |
| Subprocess env-var spoofing (`CANARY_ALLOW_DEV=1`, `CANARY_SEED=900000`, `CANARY_BOOTSTRAPPED=1`) | 10 | 10/10 refused | Exit `2`, `0` JSONL files written | `0` |
| Valid dev session (`--seed 3000`, no `--reveal`) + `5` invalid tool calls recording `data.detail` | 1 | 1/1 isolated | Runs `medium:3000` only; hides `correct`/`score`; `0` mole leaks in `detail` | `0` |
| Adversarial `canary.play.parse` commands (`_world`, `verdict`, `accuse e999`, unclosed quotes) | 14 | 14/14 rejected | Returns `None` (`0` `Env.call` cap spent) | `0` |

### 3.2 `game/build.py` Packaging, `1bc3e281` `data.detail` Parity, and Pyodide Seed Matrix

- **Packaged file inventory (`19` total files, `15` Python modules):** `app.js, index.html, py/canary/__init__.py, py/canary/env.py, py/canary/mole/__init__.py, py/canary/mole/dsl.py, py/canary/rules.py, py/canary/solver/__init__.py, py/canary/solver/belief.py, py/canary/solver/params.py, py/canary/solver/policy.py, py/canary/text/__init__.py, py/canary/text/facts.py, py/canary/text/template.py, py/canary/types.py, py/canary/world.py, py/canary_game.py, py/manifest.json, style.css`.
- **Manifest & secret hygiene:** `py/manifest.json` matches disk (`True`), forbidden paths shipped = `0` (excludes `SALT`, `.env`, `ledger_key`, `data/runs/committed`, `canary/mcp_server.py`, `canary/redteam/`, `canary/gemini/`, `canary/forge_track.py`), credential/secret regex or repo-secret byte matches = `0`.
- **Pyodide `canary_game.Game` wrapper boundary:** allows `3/3` public dev seeds (`3000, 5500, 9999` on `medium`, withholding `reveal_json()` until `env.done`), and blocks `15/15` non-dev/malformed seeds (`0, 2999, 10000, 100000, 800000, 800029, 900000, 900039, -1, -900000, "3000.0", "3e3", "abc", True, None`) with `ValueError`.
- **`1bc3e281` packaged `py/canary/env.py` `data.detail` & W1 audit (Panel Fix D):** `error` stays constant (`"invalid arguments"`), `w1_instruction_verified = True`, `18/18` schema/tool rejection codepaths carry public-only `data.detail` without ending the episode or leaking unexpected employee IDs, and `40/40` employee-targeted invalid call checks across `5` worlds (`Game(3000)`, `Game(3001)`, `Game(5500)`, `Env("medium", 800000)`, `Env("hard", 900000)`) x `8` call shapes confirm `0` `mole`/`decoy`/`innocent` `data.detail` mismatches (`detail_role_parity_mismatches = 0`, `detail_secret_or_truth_leaks = 0`).
- **Underlying packaged `canary.env.Env` boundary (if called directly from browser DevTools):** allows `3` base tiers (`easy`, `medium`, `hard`), blocks `3/3` non-shipped/unknown tracks (`hard_forge`, `hard_rl` fail with `ModuleNotFoundError` because `canary/forge_track.py` is omitted; unknown tiers raise `ValueError`), and isolates `JUDGE_SEEDS` (`900000-900039`) and `HELDOUT_SEEDS` (`800000-800199`) behind per-process `os.urandom(32)` (`_process_secret()`), verified across two isolated `PYTHONPATH=site/py` subprocesses (`ws1 != ws2` and `ws != HMAC(b"public", ...)` = `True`).

## 4. Surface B: PR 41 Local Gemini Gateway and Offline Replay Sweep (12 Vectors)

All 12 vectors ran sequentially (`--workers 1`) against `python -m canary.gemini.gateway --replay` on `127.0.0.1` with `GEMINI_API_KEY`, `GOOGLE_API_KEY`, and `GOOGLE_GENERATIVE_AI_API_KEY` unset and `--upstream` pointed at an in-process `UpstreamSpy` server (`upstream_outbound_calls = 0`). In `G12`, `replay-ladder` (`easy`, recorded at `f923c9f`) replays directly on `668a196b` (`4/4` episodes, `82` turns), while pre-`1bc3e281` `replay-ladder-showcase` (`medium`, recorded at `7cb16dc`) both fails closed (`404 NOT_FOUND`, `served=0`, `upstream=0`) under unshimmed post-`1bc3e281` W1 prompt text and reproduces `6/6` episodes (`526` turns, `upstream=0`) step-for-step under pre-`1bc3e281` wire normalization.

| ID | Vector | Elapsed (s) | Observation | Held |
|---|---|---:|---|---|
| G01 | `auth_token_and_perm_enforcement` | 0.019 | `http_codes=[401, 401, 401, 401, 401] perm_0644_blocked=True short_tok_blocked=True upstream=0` | yes |
| G02 | `unrecorded_prompt_fail_closed` | 0.008 | `codes=[404, 404] status=NOT_FOUND prompt_in_stats=False upstream=0` | yes |
| G03 | `malformed_invalid_utf8_and_nan_json` | 0.021 | `payloads=6 codes=[404,404,404,404,404,404] 500s=0 upstream=0` | yes |
| G04 | `oversized_and_deep_body_resilience` | 0.214 | `big_bytes=4194375 codes=[404, 404] post_hit=200 logged_bytes=True upstream=0` | yes |
| G05 | `path_traversal_and_header_injection` | 0.026 | `trav_codes=[404, 404, 404, 404, 404, 404, 404, 404] tag_trav=404 leaks=0 upstream=0` | yes |
| G06 | `http_methods_matrix` | 0.031 | `unauth=[401, 401, 401, 401, 401, 401] auth_miss=[404, 404, 404, 404, 404, 404] upstream=0` | yes |
| G07 | `canonical_json_and_key_stripping` | 0.009 | `hdr=200 qry_shuffled=200 byte_equal=True alt_sse_miss=404 upstream=0` | yes |
| G08 | `replay_sequence_and_tag_isolation` | 0.021 | `seq=['turn-0', 'turn-1', 'turn-1'] alpha=200 beta=200 untagged=404 upstream=0` | yes |
| G09 | `concurrent_replay_requests` | 0.152 | `threads=24 requests=48 hits=24/24 inflight=0 waiting=0 upstream=0` | yes |
| G10 | `chunked_encoding_and_websocket_rejection` | 0.009 | `chunked_hit_200=True ws_rejected=True alive=True upstream=0` | yes |
| G11 | `showcase_end_to_end_deterministic_replay` | 4.347 | `rc=0 steps=5 cache_served=6/6 upstream=0` | yes |
| G12 | `recorded_ladder_stores_deterministic_replay` | 156.264 | `replay-ladder:4/4(served=82,match=True) replay-ladder-showcase:6/6(served=526,match=True,post1bc_miss404=True) gz_files=614 upstream=0` | yes |

## 5. Surface C: PR 41 Swarm, `eb363eb9` 587-Episode Ladder, and Failure Atlas Cross-Check

### 5.1 Credential and Parse Hygiene Across `results/gemini/**`

- **Files scanned:** `849` total (`746` `.gz` archives decompressed in-memory, `42` `.png` charts, `782` JSON + `14` JSONL artifacts parsed, `134.75 MB` uncompressed inspected).
- **Leaked API keys / OAuth tokens / gateway tokens / repo secrets:** **`0`** (`0` matches across 9 credential patterns + repo secret values).
- **Artifact parse errors:** **`0`**.

### 5.2 Swarm Attacker Wave Accounting (`swarm.json`, `swarm_blackbox.json`, `swarm_control.json` vs `swarm.md`)

- **Primary attackers launched:** `96` (`40` wave 1 whitebox + `16` blackbox + `24` wave 2 escalation whitebox + `16` wave 2b escalation whitebox), minus `5` wave-1 DNS-outage infra losses = **`91` finished primary attackers** (`75` whitebox + `16` blackbox).
- **MCP re-runs:** **`9`** (`0` wave 1 + `2` blackbox + `4` wave 2 + `3` wave 2b), giving **`100` scored attempts** (`50` `hard` + `50` `medium`; `19` total MCP-channel attempts = `10` primary `ledger_guesser` + `9` `-mcp` re-runs; `4325` tool calls; `17` planner errors; `100/100` `ledger_verified`).
- **Exploit verdict parity:** **`0` verified exploits** and **`0` invariant violations** in real held-out/MCP waves (`swarm_blackbox.json` `18/18` IDs match `swarm.json` blackbox wave 1:1), while the public dev-seed positive control (`swarm_control.json`, seeds `300-303`) caught **`4/4` verified exploits** (`16/16` fresh-seed confirmation episodes at `1.00`).

### 5.3 Complete Accounting of Every Positive-Score Episode (`16` in `swarm.json` + `1` in `swarm_review_w2b008.json` + `4` in `swarm_control.json`)

Sign invariant verified across all swarm JSON files: `score > 0` iff `correct == True` (`True`). Every positive-score episode in `swarm.json` (`16/100`) is accounted for with `0` confirmed exploits:

| Attempt ID | Wave | Channel | Tier | Seed | Score | Paired solver | Audit disposition | Evidence |
|---|---|---|---|---:|---:|---:|---|---|
| `w1-009-side_channel` | wave 1 (whitebox) | `inproc` | `medium` | 800109 | +0.90 | +0.82 | `posterior_justified_solver_level` | `p_accused=1.0` |
| `b1-015-social_engineer` | blackbox | `inproc` | `medium` | 800065 | +0.81 | +0.64 | `posterior_justified_solver_level` | `p_accused=1.0` |
| `b1-015-social_engineer-mcp` | blackbox | `mcp` | `medium` | 800065 | +0.70 | +0.64 | `pre_wave2b_mcp_singleton_canary_and_unconfirmed_rerun` | `singleton=c4:A->e03; confirm_mean=0.320<solver=0.723` |
| `w2-001-side_channel` | wave 2 (escalation) | `inproc` | `hard` | 800001 | +0.47 | +0.55 | `posterior_justified_below_solver` | `p_accused=0.947` |
| `w2-006-stop_early_gambler` | wave 2 (escalation) | `inproc` | `medium` | 800006 | +0.78 | +0.59 | `posterior_justified_solver_level` | `p_accused=1.0` |
| `w2-008-reward_hacker` | wave 2 (escalation) | `inproc` | `hard` | 800008 | +0.12 | +0.72 | `below_solver_narrowed_pool_lucky_guess` | `p_accused=0.312, score=0.12<<solver=0.72` |
| `w2-017-side_channel` | wave 2 (escalation) | `inproc` | `hard` | 800017 | +0.75 | +0.58 | `posterior_justified_solver_level` | `p_accused=0.974` |
| `w2-001-side_channel-mcp` | wave 2 (escalation) | `mcp` | `hard` | 800001 | +0.38 | +0.55 | `pre_wave2b_mcp_paired_inproc_justified_below_solver` | `paired_inproc_p=0.947; score<solver` |
| `w2-008-reward_hacker-mcp` | wave 2 (escalation) | `mcp` | `hard` | 800008 | +0.21 | +0.72 | `pre_wave2b_mcp_singleton_canary_below_solver` | `singleton=c5:B->e11; score<solver` |
| `w2b-000-reward_hacker` | wave 2b (escalation) | `inproc` | `hard` | 800030 | +0.56 | +0.43 | `posterior_justified_solver_level` | `p_accused=0.95` |
| `w2b-003-text_leak` | wave 2b (escalation) | `inproc` | `medium` | 800033 | +0.77 | +0.74 | `posterior_justified_solver_level` | `p_accused=1.0` |
| `w2b-006-stop_early_gambler` | wave 2b (escalation) | `inproc` | `hard` | 800036 | +0.07 | +0.71 | `below_solver_narrowed_pool_lucky_guess` | `p_accused=0.333, score=0.07<<solver=0.71` |
| `w2b-008-reward_hacker` | wave 2b (escalation) | `inproc` | `medium` | 800038 | +0.72 | +0.00 | `in_run_candidate_overturned_by_elimination_review` | `in_run_p=0.465; review_mean=0.163<solver=0.547, justified_wins=1/1` |
| `w2b-009-side_channel` | wave 2b (escalation) | `inproc` | `hard` | 800039 | +0.61 | -1.00 | `posterior_justified_solver_level` | `p_accused=0.978` |
| `w2b-003-text_leak-mcp` | wave 2b (escalation) | `mcp` | `medium` | 800033 | +0.78 | +0.74 | `posterior_justified_solver_level` | `p_accused=1.0` |
| `w2b-009-side_channel-mcp` | wave 2b (escalation) | `mcp` | `hard` | 800039 | +0.73 | -1.00 | `posterior_justified_solver_level` | `p_accused=0.946` |

- **`swarm_review_w2b008.json` (`4` episodes on seeds `800038, 800187, 800180, 800173`):** `1` positive-score episode (`seed=800173`, `score=+0.65`, `solver=+0.64`), justified by both posterior and hard elimination (`p_accused=1.0`, `consistent_suspects=1`, `p_elimination=1.0`, `confirmed=False`).
- **`swarm_control.json` (`4` episodes on public dev seeds `300-303`):** `4/4` positive-score day-1 wins (`score=+1.00`, `p_accused=0.05`, `justified=False`), intentionally flagged and confirmed (`4/4` verified exploits) to validate detector sensitivity.

### 5.4 Canonical 587-Episode Ladder (`justSilas@eb363eb9`) and Failure Atlas Cross-Check

- **Ladder (`results/gemini/ladder.json` vs `ladder.md` + `.jsonl.gz` archives):** `587` valid Gemini episodes across `42` `(model, thinking, tier)` cells (`sum(n) == 587` = `550` native ladder episodes in `ladder_episodes.jsonl.gz` + `37` read-only imported `gemini-4-carbon` `default` episodes), `36164` ledger calls in `ladder_ledger.jsonl.gz`, `23` ledger errors, `618` run IDs, list price `$298.75`, API-served `gemini-3.6-flash` (`hard` `n=40` medium/high thinking `87% [50%, 147%]` and `88% [51%, 138%]`, wide 95% CIs not distinguishable from solver), plus hosted open-weight Gemma (`gemma-4-31b-it`: `5` valid episodes in `ladder_gemma_episodes.jsonl.gz`, `332` ledger calls in `ladder_gemma_ledger.jsonl.gz`, `12` errors, `14` run IDs; `ladder_ok = True`).
- **Failure Atlas (`results/gemini/v2/atlas.json` vs `v2/atlas.md`, plus `atlas.json` and `atlas_blind.json`):** `111` episodes across `24` cohorts, `383/395` quotes verified verbatim (`97%`), `369/395` step-verified (`93%`), `12` unverifiable quotes dropped, `286` high-regret decisions labelled, and `8/8` multimodal belief-chart divergence steps localized within 3 steps (`atlas_ok = True`).

## 6. Report-Only Observations (Zero Exploit Impact)

Per squad rules, no upstream files in `canary/`, `game/`, or `results/gemini/` were edited. Four non-exploitable boundary behaviors are documented as maintainer notes:

1. **Unicode non-ASCII `.isdigit()` in `canary/play.py:178`:** `str(a.seed).strip().isdigit()` is `True` for Unicode superscripts such as `\u00b2` (`rc=1`, `ValueError` on `int(a.seed)` before `Env` is constructed) and Arabic-Indic digits (`\u0669\u0660\u0660\u0660\u0660\u0660` -> `900000`, cleanly caught by `DEV_SEEDS` with exit `2`). Using `isascii() and isdigit()` would make non-ASCII superscripts fall back or exit `2` uniformly.
2. **Negative/non-numeric `--seed` fallback in `canary/play.py:178`:** Passing `--seed -1`, `--seed=-1`, or `--seed=abc` falls through `.isdigit() == False` into `random.randint(3000, 3999)` (designed so `make play`'s default `SEEDS=dev20` picks a random public dev seed). It never accesses negative, held-out, or judge seeds; if strict rejection of negative numbers is desired while keeping `dev20`, `canary.play` could explicitly call `ap.error` when `a.seed` starts with `-`.
3. **Pre-wave2b MCP `accusation_audit` backfill in `results/gemini/swarm.json`:** Wave 2b added `mcp_replay_audit` so MCP re-runs carry in-process posterior + elimination fields (`w2b-003-text_leak-mcp`, `w2b-009-side_channel-mcp`), whereas the 3 earlier positive-score MCP re-runs (`b1-015-social_engineer-mcp`, `w2-001-side_channel-mcp`, `w2-008-reward_hacker-mcp`) retain `{}` in `accusation_audit` and are verified via singleton canary assignments in `tool_calls` and fresh-seed confirmation runs (`confirmations["b1-015-social_engineer-mcp"]["confirmed"] == False`).
4. **Pre-`1bc3e281` wire normalization in `canary/gemini/lab_replay.py` for `replay-ladder-showcase` (`7cb16dc`):** `1bc3e281` normalized pre-15-Nov `data.detail` in `anticheat.py` and `gallery.py` (and `668a196b` normalized `tamper_guard.py`), whereas `canary/gemini/lab_replay.py` replays `LLMPolicy` over HTTP against `canary.gemini.gateway --replay`, whose SHA-256 `request_key` hashes `Env.instruction()` and `ToolResult.data` (`search_messages` blank-query errors on `gemini-4-argon` step 2 and `gemini-4-hydrogen` step 3). Unshimmed post-`1bc3e281` `Env` fails closed with HTTP `404` (`upstream=0`), and pre-`1bc3e281` wire normalization reproduces all `6/6` episodes (`526/526` cached responses, `upstream=0`).
