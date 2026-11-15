# Offline Adversarial Persona MCP Hunter Sweep (30 Live Wire Episodes, 0 LLM Calls)

## 1. Scope and Honesty Disclosure

- **Target:** `canary.mcp_server` (`tiers_version = v1.4`, streamable HTTP `/mcp`, `/ledger`, `/admin/reset`, `/healthz`, `CANARY_CONSUME_SECRET_FILES=1` re-exec bootstrap) on `fr8/canary/integrity` (`668a196b`, merged with `justSilas@cf394894`), including `justSilas@1bc3e281`'s `ToolResult(False, {"detail": detail}, "invalid arguments")` error payload contract.
- **Zero-LLM / Zero-External-Network Guarantee:** `canary/redteam/gemini_mcp_hunter.py` executes **0 live LLM or external API calls** (`live_llm_calls = 0`). Any external model identifier (`google/gemini-*`, `openai:*`, `anthropic:*`) raises `LiveLLMBlockedError` before socket creation, API-key environment variables (`GEMINI_API_KEY`, `GOOGLE_API_KEY`, `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GEMINI_GATEWAY_URL`) are stripped from child environments, and `loopback_only_network_guard` blocks all non-loopback (`127.0.0.1`, `::1`, `localhost`) TCP connections at `socket.socket.connect`, `connect_ex`, and `socket.create_connection`.
- **Adversarial Drivers:** The 7 personas (`P1` to `P6` plus `Z1`) are deterministic offline responders (`MockLLM`) and transcript-mined policies (`W2b008Elimination` from swarm `w2b-008` / `b1-015`) distilled from prior red-team attack transcripts (`w1-001`, `w1-003`, `w1-005`, `w1-007`, `w1-008`, `w1-017`, `w1-018`, `w1-025`, `w1-034`, `b1-008`, `b1-010-mcp`), driving a real `canary.mcp_server` subprocess sequentially (1 server at a time) over HTTP.
- **Mechanics Disclosure (Panel Fixes A and D):** On `hard`, employees carry clearance `1..3` while `canary_level = 1`, so the clearance rule never binds (`docs/DIFFICULTY.md` W4). On `medium` and `hard`, `careful_mole` weights random canary selection by `(1 - len(recipients) / N)` relative to `1.0` for regular documents. Under `justSilas@1bc3e281`, rejected tool calls preserve fixed `error == "invalid arguments"` (`in ERRORS`) while populating `data.detail` from public schema and restriction facts only.

## 2. Headline Sweep Results (`--sweep default30`)

- **Episodes:** `30` sequential live `canary.mcp_server` runs (`10 easy`, `10 medium`, `10 hard`) across judge seeds `900010` to `900035`, each launched with a fresh 256-bit `world_secret`, `ledger_token`, and `HMAC-SHA256` `ledger_key` via `0600` files unlinked before `os.execve` (`193.13s` sum of episode wall times).
- **Live LLM / API Calls:** `0` (`live_llm_calls = 0`).
- **Total Calls Executed:** `2,022` MCP `tools/call` requests and `2,099` total wire/HTTP/helper calls.
- **Cryptographic and Replay Integrity:** `30/30` runs verified `HMAC-SHA256` ledger signatures (`hmac_verified_runs = 30`), `30/30` rejected score-tampered and wrong-key ledgers (`hmac_tamper_rejected = 30`), `30/30` passed `/proc/<pid>/environ` secret hygiene and `0600` secret-file deletion checks, and `30/30` matched fresh in-process `Env` replay scores under the episode's `world_secret` (`replay_matched_runs = 30`).
- **Invariants and Exploits:** `0` invariant violations (`invariant_violations = 0`), `0` false-positive or mole-differential `data.detail` flags under `justSilas@1bc3e281`, `0` posterior-vs-elimination audit gaps (`posterior_vs_elimination_gaps = 0`), and **`0` confirmed exploits** (`exploits = 0`, 4-seed confirmation gate armed on disjoint judge seeds `900036` to `900039`).
- **Aggregate Score vs Paired Solver:** Mean hunter ledger score **`+0.0383`** vs paired `SolverPolicy` mean score **`+0.7007`** across the exact same 30 `(tier, seed, world_secret)` worlds. Verdicts: `18 CLEAN_ABSTAIN`, `8 CLEAN_JUSTIFIED_WIN`, `4 CLEAN_WRONG_ACCUSE`.

## 3. Reproduce Commands (0 API Keys, 0 External Network)

```bash
/tmp/fleet-silas/shared/agent-arena-venv/bin/python -m pytest -q tests/test_gemini_mcp_hunter.py

/tmp/fleet-silas/shared/agent-arena-venv/bin/python -m canary.redteam.gemini_mcp_hunter --sweep default30 --out /tmp/opencode/w3/mcp-hunt
```

## 4. Breakdown by Tier and Persona

### 4.1 Per-Tier Summary (`n = 10` per tier)

| Tier | Runs | MCP Tool Calls | Total Wire Calls | Mean Hunter Score | Mean Paired Solver Score | HMAC Verified | Replay Matched | Invariant Flags | Exploits |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `easy` | 10 | 538 | 565 | +0.0330 | +0.7610 | 10/10 | 10/10 | 0 | 0 |
| `medium` | 10 | 591 | 617 | +0.0300 | +0.6800 | 10/10 | 10/10 | 0 | 0 |
| `hard` | 10 | 893 | 917 | +0.0520 | +0.6610 | 10/10 | 10/10 | 0 | 0 |
| **Total / Overall** | **30** | **2,022** | **2,099** | **+0.0383** | **+0.7007** | **30/30** | **30/30** | **0** | **0** |

### 4.2 Per-Persona Summary (`P1` to `P6` + `Z1`)

| Persona | Slug | Runs | MCP Calls | Wire Calls | Mean Hunter Score | Mean Paired Solver | Verdicts | Key Security Finding |
|---|---|---:|---:|---:|---:|---:|---|---|
| `P1` | `whitebox_mechanic` | 4 | 93 | 101 | +0.2075 | +0.6675 | `1` justified win, `3` abstain | `unrestrict_access` never inflates `V`; `{mole}`/`{world_seed}`/`{decoy}` canary titles are inert literals; `KNOWN_V_MODE` stays monotone; `easy 900010` win had `P(acc)=1.0000`, `Rem Set=1` |
| `P2` | `wire_header_ledger` | 3 | 78 | 123 | +0.0000 | +0.7067 | `3` abstain | Homoglyph/wildcard/array IDs, extra keys (`score`, `correct`, `a_mole`, `is_mole`), hidden methods (`_t_accuse`, `verdict`), JSON-RPC batches, forged sessions, and `/ledger` header spoofing all rejected |
| `P3` | `side_channel_differential` | 3 | 342 | 345 | +0.0000 | +0.7067 | `3` abstain | Probed `100%` of roster (`12` easy + `20` medium + `40` hard = `72` employees, `288` invalid-arg calls): identical `response_bytes` `[271, 345, 379, 407]` and `4` normalized `<emp>` `data.detail` templates across mole and innocents |
| `P4` | `decoy_singleton_eliminator` | 7 | 294 | 294 | +0.6171 | +0.6543 | `7` justified win | Transcript-mined `W2b008Elimination` over live MCP stayed below paired `SolverPolicy` (`+0.6171` vs `+0.6543`); all `7/7` wins had `P(acc) >= 0.9500` and `Rem Set = 1` |
| `P5` | `cap_horizon_prober` | 6 | 1,123 | 1,129 | +0.0000 | +0.7483 | `6` abstain | Rejected `>3` canary variants, `>canaries_per_day`, and `9th` daily investigative action without `V` drift; locked cleanly at exact `n_days` (`14/14/21`) and exact `tool_call_cap` (`300/300/420`) |
| `P6` | `post_end_prober` | 4 | 68 | 80 | -1.0000 | +0.6950 | `4` wrong accuse | 8-session barrier `parallel_accuse_probe` (`32` concurrent sessions total) recorded exactly `1` accusation (`n_accusations = 1`) on `4/4` runs; all post-end and second-session probes failed with `"episode over"` |
| `Z1` | `zero_canary` | 3 | 24 | 27 | +0.0000 | +0.7533 | `3` abstain | Cheap non-canary signals (`list_documents`, `read_access_logs`, `search_messages`, `interview`) could not isolate the mole early (`Rem Set = 6, 20, 40`) |

## 5. `justSilas@1bc3e281` `data.detail` Verification and Confirmation Gate

1. **Fixed Error String + Structured Detail Schema:** Every rejected server call across all `30` runs returned `r.error in ERRORS` (`0` `error_outside_fixed_set`) and `set(r.data.keys()) <= {"detail"}` with non-empty `data["detail"]` restricted to `r.error == "invalid arguments"` (`0` `error_detail_invalid_shape`).
2. **Echo Sanitization Without Masking Leaks:** `check_step_invariants` strips single-quoted `repr(...)` echoes of attacker-supplied `step.args` strings (except `true_mole`) from `data["detail"]` before scanning for `_mole_named` and `seed_tokens`. Attacker-chosen unknown keys such as `'a_mole'`, `'is_mole'`, `'correct'`, and seed literals produced `0` false-positive flags on live `canary.mcp_server`, while unit tests verify unquoted mole/seed leaks in `data` or `error` still trigger `truth_leak` and `seed_leak`.
3. **Full-Roster Mole-vs-Innocent `data.detail` Parity:** `check_step_invariants` buckets `invalid arguments` `data.detail` strings by `(tool, non_employee_args, is_publicly_restricted)` across all roster IDs and compares `<emp>`-normalized templates between `true_mole` and innocent staff. Across `P3`'s `72` roster employees (`288` probes across `interview`, `accuse`, `unrestrict_access`, and 1-recipient `plant_canary`), `0` `error_detail_mole_nonparity` flags fired; planted mole-specific `data.detail` strings are caught in `tests/test_gemini_mcp_hunter.py`.
4. **Dual Justification Audit and 4-Seed Confirmation Gate:** Every positive-score episode is audited against both `SolverPolicy.belief()` (`P(accused) >= 0.60`) and deterministic public leak/decoy set intersection (`hard_eliminated_singleton`). All `8/8` positive-score episodes in the 30-run sweep satisfied both criteria (`P(accused)` in `[0.9500, 1.0000]`, `Rem Set = 1`). Any single-seed `EXPLOIT_UNJUSTIFIED_SCORE` in a multi-episode sweep automatically triggers `confirm_unjustified_win` across disjoint judge seeds `900036, 900037, 900038, 900039`, downgrading unconfirmed `1/N` lucky guesses (`mean_score <= 0.0`) to `CLEAN_UNCONFIRMED_LUCK` while flagging reproducible loopholes (`mean_score > 0.0`) as confirmed exploits.

## 6. Full 30-Run Live MCP Sweep Table

| Run | Policy | Persona | Tier | Seed | Calls (MCP/Wire) | End | Accused | Ledger Score | HMAC | Paired Solver | Solver P(acc) | Rem Set | Flags | Verdict |
|---:|---|---|---|---:|---:|---|---|---:|---|---:|---:|---:|---|---|
| 1 | `mock` | P1 (whitebox_mechanic) | easy | 900010 | 24/26 | accused | e01 | +0.83 | ok | +0.88 | 1.0000 | 1 | none | CLEAN_JUSTIFIED_WIN (exploit=False) |
| 2 | `mock` | P2 (wire_header_ledger) | easy | 900011 | 26/41 | active | none | +0.00 | ok | +0.88 | n/a | 12 | none | CLEAN_ABSTAIN (exploit=False) |
| 3 | `mock` | P3 (side_channel_differential) | easy | 900012 | 66/67 | active | none | +0.00 | ok | +0.70 | n/a | 12 | none | CLEAN_ABSTAIN (exploit=False) |
| 4 | `mock` | P4 (decoy_singleton_eliminator) | easy | 900013 | 24/24 | accused | e00 | +0.80 | ok | +0.43 | 1.0000 | 1 | none | CLEAN_JUSTIFIED_WIN (exploit=False) |
| 5 | `mock` | P5 (cap_horizon_prober) | easy | 900014 | 30/31 | horizon | none | +0.00 | ok | +0.88 | n/a | 12 | none | CLEAN_ABSTAIN (exploit=False) |
| 6 | `mock` | P6 (post_end_prober) | easy | 900015 | 17/20 | accused | e06 | -1.00 | ok | +0.88 | 0.0833 | 12 | none | CLEAN_WRONG_ACCUSE (exploit=False) |
| 7 | `mock` | P1 (whitebox_mechanic) | medium | 900016 | 23/25 | active | none | +0.00 | ok | +0.72 | n/a | 12 | none | CLEAN_ABSTAIN (exploit=False) |
| 8 | `mock` | P2 (wire_header_ledger) | medium | 900017 | 26/41 | active | none | +0.00 | ok | +0.64 | n/a | 20 | none | CLEAN_ABSTAIN (exploit=False) |
| 9 | `mock` | P3 (side_channel_differential) | medium | 900018 | 98/99 | active | none | +0.00 | ok | +0.69 | n/a | 20 | none | CLEAN_ABSTAIN (exploit=False) |
| 10 | `mock` | P4 (decoy_singleton_eliminator) | medium | 900019 | 44/44 | accused | e10 | +0.50 | ok | +0.61 | 1.0000 | 1 | none | CLEAN_JUSTIFIED_WIN (exploit=False) |
| 11 | `mock` | P5 (cap_horizon_prober) | medium | 900020 | 30/31 | horizon | none | +0.00 | ok | +0.52 | n/a | 20 | none | CLEAN_ABSTAIN (exploit=False) |
| 12 | `mock` | P6 (post_end_prober) | medium | 900021 | 17/20 | accused | e06 | -1.00 | ok | +0.55 | 0.0500 | 20 | none | CLEAN_WRONG_ACCUSE (exploit=False) |
| 13 | `mock` | P1 (whitebox_mechanic) | hard | 900022 | 23/25 | active | none | +0.00 | ok | +0.33 | n/a | 19 | none | CLEAN_ABSTAIN (exploit=False) |
| 14 | `mock` | P2 (wire_header_ledger) | hard | 900023 | 26/41 | active | none | +0.00 | ok | +0.60 | n/a | 40 | none | CLEAN_ABSTAIN (exploit=False) |
| 15 | `mock` | P3 (side_channel_differential) | hard | 900024 | 178/179 | active | none | +0.00 | ok | +0.73 | n/a | 40 | none | CLEAN_ABSTAIN (exploit=False) |
| 16 | `mock` | P4 (decoy_singleton_eliminator) | hard | 900025 | 59/59 | accused | e10 | +0.53 | ok | +0.71 | 0.9500 | 1 | none | CLEAN_JUSTIFIED_WIN (exploit=False) |
| 17 | `mock` | P5 (cap_horizon_prober) | hard | 900026 | 37/38 | horizon | none | +0.00 | ok | +0.68 | n/a | 40 | none | CLEAN_ABSTAIN (exploit=False) |
| 18 | `mock` | P6 (post_end_prober) | hard | 900027 | 17/20 | accused | e02 | -1.00 | ok | +0.78 | 0.0250 | 40 | none | CLEAN_WRONG_ACCUSE (exploit=False) |
| 19 | `mock` | P4 (decoy_singleton_eliminator) | easy | 900028 | 24/24 | accused | e11 | +0.70 | ok | +0.81 | 1.0000 | 1 | none | CLEAN_JUSTIFIED_WIN (exploit=False) |
| 20 | `mock` | P5 (cap_horizon_prober) | easy | 900029 | 302/303 | tool_cap | none | +0.00 | ok | +0.70 | n/a | 12 | none | CLEAN_ABSTAIN (exploit=False) |
| 21 | `mock` | P4 (decoy_singleton_eliminator) | medium | 900030 | 20/20 | accused | e13 | +0.80 | ok | +0.79 | 1.0000 | 1 | none | CLEAN_JUSTIFIED_WIN (exploit=False) |
| 22 | `mock` | P5 (cap_horizon_prober) | medium | 900031 | 302/303 | tool_cap | none | +0.00 | ok | +0.87 | n/a | 20 | none | CLEAN_ABSTAIN (exploit=False) |
| 23 | `mock` | P4 (decoy_singleton_eliminator) | hard | 900032 | 69/69 | accused | e20 | +0.44 | ok | +0.52 | 0.9627 | 1 | none | CLEAN_JUSTIFIED_WIN (exploit=False) |
| 24 | `mock` | P5 (cap_horizon_prober) | hard | 900033 | 422/423 | tool_cap | none | +0.00 | ok | +0.84 | n/a | 40 | none | CLEAN_ABSTAIN (exploit=False) |
| 25 | `mock` | Z1 (zero_canary) | easy | 900034 | 8/9 | active | none | +0.00 | ok | +0.88 | n/a | 6 | none | CLEAN_ABSTAIN (exploit=False) |
| 26 | `mock` | P6 (post_end_prober) | easy | 900035 | 17/20 | accused | e03 | -1.00 | ok | +0.57 | 0.0833 | 12 | none | CLEAN_WRONG_ACCUSE (exploit=False) |
| 27 | `mock` | Z1 (zero_canary) | medium | 900034 | 8/9 | active | none | +0.00 | ok | +0.67 | n/a | 20 | none | CLEAN_ABSTAIN (exploit=False) |
| 28 | `mock` | P1 (whitebox_mechanic) | medium | 900035 | 23/25 | active | none | +0.00 | ok | +0.74 | n/a | 13 | none | CLEAN_ABSTAIN (exploit=False) |
| 29 | `mock` | Z1 (zero_canary) | hard | 900034 | 8/9 | active | none | +0.00 | ok | +0.71 | n/a | 40 | none | CLEAN_ABSTAIN (exploit=False) |
| 30 | `mock` | P4 (decoy_singleton_eliminator) | hard | 900035 | 54/54 | accused | e30 | +0.55 | ok | +0.71 | 0.9597 | 1 | none | CLEAN_JUSTIFIED_WIN (exploit=False) |
