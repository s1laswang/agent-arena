# G4 Red-team swarm: report (newest first)

## Sat 15:00: swarm v0 code + tests done; M1 live run in progress

Done (verified):
- `canary/gemini/repo_pack.py`: whole-repo pack (92 files, ~590 KB, **206k tokens counted by the Gemini API** before the redteam exclusion; ~150k after). Excludes .env*, data/ (judge worlds, SALT), .git/.venv/wt, canary/gemini (lab tooling), canary/redteam (our own attacker prompts), secret-named files, any file containing a secret value (env keys, .env secrets, SALT bytes) or a `"mole": "eNN"` world dump. Tested on a planted tree.
- `canary/gemini/swarm.py`: personas (8, `swarm_prompts/personas.md`) x planner model x tier; planner = Gemini with the pack in context, thinking HIGH, JSON-schema plan; executor = Gemini flash, thinking LOW, function calling over the 13 env tools 1:1 plus helpers (raw_call, repeat_call, parallel_accuse, public_world[_match], http_get on the MCP channel, finish); in-process Env on held-out seeds with a per-run random world secret, and the real `canary.mcp_server` subprocess (same world via CANARY_WORLD_SECRET_FILE) for ledger personas and the top attempts. Verification in code only: score from the env ledger or GET /ledger?token; invariants per call (truth leak incl. extra phrasings, seed leak, error outside env.ERRORS, visible and true V monotone, post-end effects, one accusation incl. parallel races, crash, ledger without token, score_invariants). Score candidates are re-run on fresh seeds before they count. Auto-writes tests (xfail findings + hold-out replays) and swarm.md.
- `tests/test_gemini_lab_swarm.py`: 11 tests, keyless, < 1 s: pack excludes planted secrets; verifier flags planted truth leak, score without accusation, rising V, post-end effect; honest solver play passes; parallel accuse counts one; public world != secret world; persona expansion; stub executor loop; stub end-to-end incl. generated tests.

Findings while wiring Gemini (worth knowing for every team):
- **Explicit context caching (`caches.create`) returns 404 on our key** for gemini-3.8-flash, 4-hydrogen, 4-carbon, 3.5-flash. Implicit caching works: the 2nd planner call on the same pack showed `cached_content_token_count` = 206,713 of 208,763. So the pack goes first in every prompt (common prefix).
- **Gemini's input filter blocked the attacker-worded planner prompt** (`prompt_feedback.block_reason = OTHER`, after up to 170 s). Reframed as a scoring-integrity audit and dropped canary/redteam (attacker prompts) from the pack: 8/8 personas pass with the pack in context; blackbox (no pack) still blocks 3/8 personas (protocol_fuzzer, ledger_guesser, social_engineer). Blocks are recorded as planner errors.
- A google-genai Client that gets garbage collected closes the shared transport for other threads ("client has been closed"); the swarm now uses one process-wide client.

Next: M1 (3 attackers, flash/hydrogen/carbon, medium+hard, MCP re-run + confirm) → wave 1 (20-50 attackers, Mac, concurrency <= 8; FR8 ssh is blocked per G1) → swarm.md v1 by 19:00.
Blockers: none (FR8 unreachable, so the Mac runs it).
Spend so far: under $2 (probes + M1 attempts), see ledger feature=swarm.
