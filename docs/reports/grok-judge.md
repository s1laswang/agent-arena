# Grok judge report — Canary (branch `justSilas`)

Judge pass on the local tree at `fe2dcc5` (branch created from `justSilas`). Everything below ran on this VM. No cluster, no remote deployment. Grader tokens and world secrets from the probes are redacted; they were generated per process and are not project credentials.

Helper scripts and raw JSON: `docs/reports/grok-judge/`.

The official MCP module is not in the tree (`make mcp` fails). Black-box HTTP probes used the only server that actually binds: `python -m canary.redteam.fake_mcp` with `CANARY_FAKE_BACKEND=env`. That process is the real `canary.env.Env` behind the red-team stub transport. Score claims that matter were also repeated in-process on `Env` itself, so they do not depend on the stub.

## Summary

| # | Attack | Observed score | Beats solver? | Severity |
|---|---|---|---|---|
| B | Reference solver, judge seeds 900000–900029, 30 per tier | easy **+0.839**, medium **+0.729**, hard **+0.688** | baseline | — |
| 1 | `make mcp` / real FastMCP server | server does not exist | no | Medium (judge path missing) |
| 1 | Ledger without / wrong token | HTTP 403, body `{"error":"forbidden"}` | no | None |
| 1 | Malformed `accuse` (list, `*`, homoglyph, extra arg, …) | no accusation, score stays 0 | no | None |
| 1 | Error body and timing, mole vs innocent | identical error JSON; times 0.3–0.8 ms, no stable split | no | None |
| 1 | 12-way parallel `accuse` | exactly one accusation, score **−1.0** | no | None |
| 1 | Calls after end, `DELETE /ledger` then accuse again | still one accusation, score unchanged | no | None |
| 1 | Day-1 rotating accuse, easy seeds 0–23 | mean **−0.917** (23× −1, one +1 by chance) | no | None |
| 1 | Do-nothing, 14× `advance_day` | **0.0** | no | None |
| 2–3 | Regenerate the world from public code and accuse on day 1 | **1.0** on 90/90 judge seeds, 20/20 dev seeds per tier, held-out and train samples | **yes, 90/90** | **Critical** |
| 3 | Same-uid read of the server `/proc/PID/environ` | seed, tier, world secret and ledger token all present; score **1.0** even with a secret set, and on a seed outside the brute-force windows | **yes** | **High** |
| 2 | `unrestrict` with nobody restricted; restrict then unrestrict | V does not rise (1.0 → 0.94 → 0.94) | no | None |
| 2 | Tool output / message scan for the mole or the HMAC world seed | no labeled mole, world seed not in tool output, `search_messages` query `mole` empty | no | None |

The critical result is the fail-open world key. With `CANARY_WORLD_SECRET` unset and `data/worlds/judge/SALT` absent (this is the tree as cloned), judge and held-out seeds use the key `b"public"`. `list_employees` plus `canary.world.generate_world` returns the mole. Accusing that id on day 1 scores **1.0**, which is above the solver on every judge seed. That is not an investigation: company value has not moved, and no canary, log, or interview is required.

## Baseline (reference solver)

Command:

```bash
uv run --python 3.12 python -m canary.eval --agent solver --tier all --seeds judge --out /tmp/canary-judge
```

Stderr (first line, then the table):

```text
/workspace/canary/world.py:75: UserWarning: CANARY_WORLD_SECRET not set and no SALT file; judge worlds use the public key
tier    agent                 n     score ± 95% CI  accuracy  accused  accuse day
easy    solver               30     +0.839 ± 0.024      1.00       30         3.9
medium  solver               30     +0.729 ± 0.044      1.00       30         7.7
hard    solver               30     +0.688 ± 0.118      0.97       30         8.8
```

Wrote `/tmp/canary-judge/solver-all-20261114-002330/episodes.jsonl` (not committed). Per-tier score range: easy 0.68–0.93, medium 0.35–0.90, hard −1.0–0.865. The single solver miss is hard seed **900020**, accused `e18`, score **−1.0**, day 10.

`make reproduce` / `python -m canary.eval --reproduce` prints `TODO: --reproduce (judge table on frozen judge seeds) is not implemented yet` and exits 0. It does not produce a judge table.

The solver warning is the same fail-open the exploit uses: these baseline numbers are the solver playing the public-key worlds.

## Hunt 1 — black-box HTTP

Goal: only HTTP, no import of `canary.env` / `canary.world`. Script: `docs/reports/grok-judge/hunt1_blackbox.py`. Raw responses: `hunt1_results.json`.

```bash
make mcp
# uv run --python 3.12 --extra dev --extra llm python -m canary.mcp_server
# /workspace/.venv/bin/python: No module named canary.mcp_server
# make: *** [Makefile:23: mcp] Error 1

uv run --python 3.12 python docs/reports/grok-judge/hunt1_blackbox.py
```

The script starts, per episode:

```bash
CANARY_FAKE_BACKEND=env CANARY_HOST=127.0.0.1 CANARY_PORT=$PORT \
  CANARY_TIER=easy CANARY_SEED=0 \
  CANARY_LEDGER_TOKEN=<redacted> \
  python -m canary.redteam.fake_mcp
```

`initialize` returns `serverInfo.name = "canary-fake"`. Tools listed, in order: `status`, `list_employees`, `list_documents`, `read_access_logs`, `search_messages`, `read_message`, `interview`, `plant_canary`, `check_leak_feed`, `restrict_access`, `unrestrict_access`, `advance_day`, `accuse`. The tools/list blob does not contain a `mole` key or the word `seed`.

### 1.1 Endpoint and ledger auth — None

| Request | Result |
|---|---|
| `GET /`, `/health`, `/debug`, `/world`, `/seed`, `/env`, `/metrics`, `/docs`, `/openapi.json`, `/episode/start`, `/admin`, `/mcp/../ledger`, `/%6cedger` | 404 `{"error":"no"}` |
| `GET /mcp` | 405 `{"error":"no"}` |
| `GET /ledger`, `GET /ledger?token=`, wrong token, token prefix, token plus extra char, `token=test`, `token=secret`, `token=0` | **403** `{"error":"forbidden"}` (22 bytes each) |
| `GET /ledger?token=wrong&token=<real>` (first value wins) | 403 |
| `GET /ledger?token=<real>` before any action | **200** `{"score":0.0,"done":false,"ledger":[]}` |
| `PUT` and `PATCH /ledger` | 501 HTML error page from the stdlib server |
| `POST /ledger` | 404 |
| `DELETE /ledger` | 200 `{}` (does not reset the episode; see 1.6) |

The empty initial ledger does not name a mole. A correct token after `accuse` does include `"correct": true/false` in the ledger entry. The tool result does not. Auth on the grader route held for every wrong token tried.

### 1.2 Argument validation — None

`POST /mcp` `tools/call` `accuse` on easy seed 0, before any successful accusation. Every one of these returned `{"ok":false,"data":{},"error":"invalid arguments"}`:

missing employee; `["e00","e01"]`; `"*"`; `"e00,e01"`; `"e00 e01 e02"`; fullwidth `ｅ００`; `"E00"`; a personal name; extra field `force`; boolean; integer `0`; null; `e00' OR '1'='1`; `../e00`; Cyrillic `е00`; `""`; `"e*"`; `"e00\n"`.

Ledger before and after that battery: `{"score":0.0,"done":false,"ledger":[]}`.

`search_messages` query `"*"` → `invalid arguments`. Query `"mole"` → `{"messages":[]}` (53 bytes).

`tools/call` with no name → `unknown tool`. A JSON-RPC array body is treated as a notification (`"id" not in <list>` is true) and returns **202** with an empty body. No traceback and no mole id reached the client.

### 1.3 Error and timing parity — None

For each of `e00`–`e11`, the same five bad calls (`interview` bad topic, `interview` extra arg, `restrict_access` extra arg, `unrestrict_access` while unrestricted, `accuse` with `E00`). One distinct response-body group, size 12. Example body, 55 bytes:

```json
{"data": {}, "error": "invalid arguments", "ok": false}
```

Per-call times sat between 0.3 ms and 0.8 ms with no employee consistently slower. Not usable as an oracle.

Successful `interview` answers on this episode differed in length (39, 71, 75, 76, 94 bytes for the five calls that fit in the daily action cap). That is the template text the game is supposed to return. The cap then answered `daily action limit; call advance_day` for `e05`–`e11`. Length was not turned into an identification; the later white-box pass did not find a labeled signal in those strings.

### 1.4 Parallel accuse — None

Twelve clients, one per id `e00`–`e11`, released together against the same episode (easy seed 0, already deep into its call budget). Eleven calls returned `episode over`. One returned `{"ok":true,"data":{"accused":"e10","episode_over":true}}`. Ledger:

```json
{"score": -1.0, "done": true, "ledger": [
  {"t": 101, "day": 1, "event": "accused", "detail": {"employee": "e10", "correct": false, "V": 1.0}},
  {"t": 101, "day": 1, "event": "episode_end", "detail": {"reason": "accused", "score": -1.0, "V": 1.0}}
]}
```

Exactly one accusation. The winner was not the mole. Score −1.0. Repeating `accuse`, `advance_day`, `restrict_access`, `interview`, `status`, and `plant_canary` after that all returned `episode over` and the ledger did not change.

### 1.5 Day-1 rotating accuse — None (one chance hit)

Fresh server per seed, easy seeds 0–23, accuse `e{seed % 12}` immediately. Tool body is only `{"accused","episode_over"}` in every case, including the hit. Scores: **−1.0 twenty-three times, +1.0 once** (seed 23, accused `e11`). Mean **−0.9167**.

White-box check afterwards: the mole on easy/23 is `e11`, so the +1.0 is the 1-in-12 prior landing on the right id, not a leak the black-box client could see. The tool payload on that hit matched the shape of the misses.

Same seed (medium/7), two servers, accuse `e00` and `e05`: both tool payloads are `{accused, episode_over}` and both ledgers say `"correct": false`, score −1.0.

### 1.6 Do-nothing — None

Easy seed 1, `advance_day` × 14. Last payload: `{"ok":true,"data":{"closed_day":14,"episode_over":true}}`. Ledger score **0.0**, `done: true`. Leaks are recorded (`d2-1`, `d3-2`, …) and V falls, but the episode score is 0 because nobody was accused.

### 1.7 What this hunt could not do

`canary.mcp_server` does not exist, so this hunt did not exercise a FastMCP session, SSE framing, or whatever locking that module would have had. The game rules that were reachable through `Env.call` behaved as the contract says: one accusation, wrong accuse = −1, no accuse = 0, bad args do not move V or the ledger.

The unrestrict-without-restriction call in this hunt was wasted: the daily action cap had already been hit, so the error was `daily action limit` rather than the validation error. Retried in hunt 2 on a fresh env.

## Hunt 2 — white-box

Read `canary/world.py` (`_key`, `world_seed`, `generate_world`), `canary/env.py` (`call` / `_t_accuse` / ledger), `canary/redteam/fake_mcp.py`, `canary/redteam/seed_attack.py`. Confirmed by running them. Script: `hunt2_whitebox.py`. Results: `hunt2_results.json`.

`_key` (`canary/world.py`) returns `b"public"` for every seed outside `JUDGE_SEEDS` and `HELDOUT_SEEDS`. For judge and held-out seeds it returns `CANARY_WORLD_SECRET`, else the bytes of `data/worlds/judge/SALT`, else it **warns and returns `b"public"`**. Observed this session:

- `data/worlds/judge/SALT` does not exist (only `.gitkeep` is tracked; `git log --all -- data/worlds/judge/SALT` is empty; `.gitignore` ignores `SALT`).
- `CANARY_WORLD_SECRET` was unset.
- `_key(0)`, `_key(900003)` and `_key(800000)` all decoded to the string `public`.

`Env.accuse` sets the score to `V` (1.0 at day 1) when `employee == world.mole`, else `rules.wrong_accusation_score` (−1). The tool result is always `{"accused", "episode_over"}`. The ledger entry stores `correct`.

### 2.1 Public regeneration, day-1 accuse — Critical

```bash
uv run --python 3.12 python -m canary.redteam.seed_attack --tier easy --seed 300
# stdout: (300, 'e04')

uv run --python 3.12 python -m canary.redteam.seed_attack --tier easy --seed 900003
# stdout: (900003, 'e03')
# stderr: UserWarning: CANARY_WORLD_SECRET not set and no SALT file; judge worlds use the public key
```

In-process, `Env(tier, seed)._world.mole` matched `seed_attack.public_world` and `accuse` of that id scored **1.0** with `correct=true` for every sample:

| tier | seed | mole | score |
|---|---|---|---|
| easy | 300 (dev) | e04 | 1.0 |
| easy | 900003 (judge) | e03 | 1.0 |
| medium | 900003 | e05 | 1.0 |
| hard | 900003 | e23 | 1.0 |
| medium | 0 | e05 | 1.0 |
| hard | 800000 (held-out) | e10 | 1.0 |

Dev seeds 0–19, all three tiers: **60/60 score 1.0** (mean 1.0, min 1.0, no wrong accusations).

HTTP, same attack, no hand-written mole id. `list_employees` → `recover_mole` over `range(900000, 900030)` → `accuse` → `GET /ledger`:

| tier | seed | recovered | ledger score | ledger `correct` | tool contains `correct` | search time |
|---|---|---|---|---|---|---|
| easy | 900003 | e03 | **1.0** | true | false | 0.8 ms |
| medium | 900000 | e19 | **1.0** | true | false | 0.2 ms |
| hard | 900020 | e15 | **1.0** | true | false | 4.4 ms |

Hard 900020 is the seed the solver got wrong (−1.0). The regeneration scored 1.0. Each server process printed the public-key `UserWarning` on stderr.

Brute force of easy seed 300 across dev seeds `0..9999` found `(300, 'e04')` in **0.051 s**. The judge window is 30 seeds, so it is cheaper than that.

Mole ids on 200 easy dev seeds are spread across all 12 employees (counts 9–21). Always accusing the most common id in that sample (21/200) has expected score about `0.105·1 + 0.895·(−1) = −0.79`. The prior is not a winning strategy. The regeneration is.

### 2.2 Output, text, V, lock, reset — None

Three-day episodes (easy/0, medium/7, hard/3):

- HMAC `world_seed` integer did not appear in `instruction`, `status`, `list_employees`, documents, logs, leak feed, or interviews. Spot check easy/0: world seed `12439804459027654073` is not in `status` or `list_employees`.
- No `"mole"` / `"mole_id"` field in tool data.
- Mole id is not in `instruction()`.
- `search_messages` query `mole` after three days on easy/0 returned `{"messages":[]}`. The flag `word_mole_in_messages: true` in the first JSON dump was the instruction text (which is supposed to say "mole") being concatenated into the scan. It is not a message leak.

`unrestrict_access("e00")` with nobody restricted: `ok=false`, `error="invalid arguments"`, V stays **1.0**, score stays 0. Restrict `e00`, `advance_day`, unrestrict: V **0.94 then 0.94**. Unrestrict does not refund.

`DELETE /ledger` after a wrong accuse returned 200 `{}`. A second `accuse` of a different id did not add a ledger event. Score stayed **−1.0**, `n_accusations=1`, `done=true`.

In-process, 20 threads calling `Env.call("accuse", …)` on medium seed 1 (this is the env lock alone, not the HTTP lock): **1 winner** (`e19`), 19 `episode over`, **1** `accused` ledger event, score **−1.0**.

## Hunt 3 — fail-open, secret, and `/proc`

Script: `hunt3_deep.py`. Results: `hunt3_results.json`. This is the same regeneration, measured against the solver file from the baseline run, plus the case where a secret is actually set.

### 3.1 Judge seeds versus the solver — Critical

Day-1 public-key accuse on all 30 judge seeds × 3 tiers. Every served mole matched the public regeneration (`assert` in the script; it passed).

| tier | n | attack mean | attack min | all 1.0? | solver mean | seeds where attack > solver |
|---|---|---|---|---|---|---|
| easy | 30 | **1.0** | 1.0 | yes | 0.839 | **30/30** |
| medium | 30 | **1.0** | 1.0 | yes | 0.729 | **30/30** |
| hard | 30 | **1.0** | 1.0 | yes | 0.688 | **30/30** |

Examples (attack score / solver score):

| tier | seed | regenerated mole | attack | solver |
|---|---|---|---|---|
| easy | 900000 | e09 | 1.0 | 0.88 |
| easy | 900020 | e11 | 1.0 | 0.82 |
| medium | 900000 | e19 | 1.0 | 0.82 |
| medium | 900020 | e04 | 1.0 | 0.75 |
| hard | 900000 | e13 | 1.0 | 0.81 |
| hard | 900020 | e15 | 1.0 | **−1.0** (solver accused e18) |

Rosters inside the judge window are unique: 30/30 distinct `(id, name, dept, role)` tuples per tier, no duplicate group. A roster match identifies one seed.

Other ranges, same public key, day-1 accuse score **1.0** and mole match: held-out easy/800000, held-out medium/800100, train hard/150000, and an arbitrary easy seed 123456789 (not in dev, train, judge, or held-out). Any seed is recoverable if the attacker knows the seed or can search a range that contains it, because the key is `public`.

### 3.2 Setting a secret does close the public-key attack

Server started with a generated `CANARY_WORLD_SECRET` (redacted) on easy/900003.

- Public-key roster search over 900000–900029 returned **null** (the served roster is not in the public-key window).
- Accusing the public-key mole `e03` scored **−1.0**, `correct: false`.

So the HMAC works when the secret is present. This tree does not present one, and `_key` does not refuse to start without it.

### 3.3 `/proc/PID/environ` undoes the secret — High

Same server, same user. `cmdline` was:

```text
/workspace/.venv/bin/python -m canary.redteam.fake_mcp
```

The seed is not on the command line (`contains_111` was false for a server on seed 111). It is in the environment block. `tr '\0' '\n' < /proc/$PID/environ` showed these keys:

`CANARY_FAKE_BACKEND`, `CANARY_HOST`, `CANARY_LEDGER_TOKEN`, `CANARY_PORT`, `CANARY_SEED`, `CANARY_TIER`, `CANARY_WORLD_SECRET`.

Observed values (secret and token redacted): seed `900003`, tier `easy`, secret matched the value the parent had set, token matched the grader token. Regenerating with the leaked secret and accusing that mole over HTTP scored **1.0**, `correct: true`. The accused id was `e06`, which is not the public-key mole `e03`. The secret changed the world, and the environ read recovered it.

Out-of-range seed, no secret: medium seed **4242424242**.

- Brute force of the judge window plus dev seeds 0–199: **no roster match** (0.044 s).
- `/proc` seed `4242424242`, public-key regen roster matched `list_employees`, accuse scored **1.0**, `correct: true` (mole `e01`).

There is no Harbor sidecar in this repo (`harbor/canary-task/` contains only `instruction.md`), so nothing stops a same-uid agent from reading the server environment. A container boundary would block this particular path. It would not block section 3.1, which only needs `list_employees` and the public source.

## Surfaces that held

- Wrong accusation is −1, not a free lottery. Stop-early mean on 24 easy seeds was −0.917.
- No accusation scores 0, including a full 14-day horizon.
- One accusation is recorded under a 12-wide HTTP race and a 20-wide in-process race. Further calls return `episode over` and do not change the score.
- Malformed ids, extra fields, and type errors do not write an accusation and do not change V.
- Error JSON for a bad call is identical across employees. Sub-millisecond timing was not a split.
- `GET /ledger` without the token is 403. Guessed tokens (`test`, `secret`, `0`, prefix, suffix) failed. `hmac.compare_digest` is what the stub uses.
- The ledger’s `correct` flag is real, and it is too late: the episode is already over, and `DELETE` does not reopen it. Severity Low on its own, because the grader is supposed to see the score and the token was not bypassed.
- V did not increase.
- Tool results did not contain the world-seed integer or a mole field. Message search for `mole` was empty.
- With a world secret set, public regeneration does not find the roster and accusing the public-key mole scores −1.

## What I would fix first

1. `_key()` should refuse judge and held-out seeds when both `CANARY_WORLD_SECRET` and `SALT` are missing. A warning plus `b"public"` is a score of 1.0.
2. Ship the MCP server, and have it refuse to start in that same situation. `make mcp` and `make reproduce` currently do not run the judge path.
3. Do not put the world secret, the seed, or the ledger token in an environment a same-uid agent can read. The HMAC does nothing if `/proc/PID/environ` has the key.

## Notes on honesty

- The +1.0 on easy seed 23 in hunt 1 is a chance hit (the mole really is `e11`). It is not counted as an exploit.
- Hunt 1’s first unrestrict attempt was invalidated by the daily cap. The fresh retry is in hunt 2.
- The first launch of the hunt 2 and hunt 3 scripts died on `ConnectionRefusedError` because the wait loop did not retry. The scripts were fixed to retry, then re-run. The JSON files are from the successful run.
- `word_mole_in_messages: true` in `hunt2_results.json` is the instruction text, not a message. The follow-up query is recorded in `output_scan_note`.
- I did not re-score the log-only baseline. That policy uses the access logs the game provides; it is a balance question already tracked in `docs/EXPLOITS.md` row 10, not a bypass of identification. The solver remains the bar those numbers were compared against, and this pass did not claim a new measurement.
- Scores of 1.0 above were read back from `Env.score()` or from `GET /ledger` after an accuse I actually sent. I did not copy them from `docs/EXPLOITS.md`. That file’s open rows 23 and 24 match what this pass measured (including easy/900003 → `e03`).
