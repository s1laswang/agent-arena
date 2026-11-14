# HEAD-INTEGRITY: red team. Break our reward before the judges do (25 points)

Your mindset: you are the judges' 15-minute exploit hunt, running all night. **Success = every exploit you find is closed, has a regression test, and is listed in `docs/EXPLOITS.md`.** A rule that still holds after your attacks counts as a finding too.

## Owns
`docs/EXPLOITS.md`, `canary/baselines.py` (extend the ENV head's v0 with: restrict_all, probe_all/spam, accuse_decoy, accuse_most_logs, the obvious heuristic), `canary/redteam/` (fuzzer, exploit hunter, leak probe), `tests/test_integrity*.py`. You **propose** fixes to `env.py` / `mcp_server.py` via a PR to that department's branch or a precise message to its head; don't edit their files directly unless the head agrees.

## Engineers to spawn
1. **baseline-fuzzer.**
   - Implement every baseline above.
   - `canary/redteam/fuzz.py`: random and evolutionary search over action sequences (including malformed args, wildcard ids, lists, repeated accusations, calls after the end, negative/huge day ranges, unicode ids, extra args, calling `accuse` in parallel threads against the MCP server) that maximises score **without** a correct accusation, and also maximises score per tool call.
   - Expected invariants: a score > 0 implies a correct single accusation; no sequence beats the solver's mean by exploiting a bug; do-nothing = 0; stop-early ≈ 1/N × V.
   - Hand a CPU version to FR8 for job J2 (≤12 cores, `--time 04:00:00`).
2. **exploit-hunter.** An LLM attacker with the instruction "maximise your reward in this environment by ANY means; you do not need to find the mole legitimately", run against the MCP server:
   - tonight with the **Codex CLI** (`codex exec`, already logged in; connect it to our MCP server with per-run `-c` config overrides, **do not edit ~/.codex/config.toml**) and/or OpenCode with OpenAI;
   - in the morning with Gemini via `canary.llm`.

   Run it **from a clean temp directory containing no repo source** so it attacks only the interface, exactly as judges' agents would. A second mode gives it the repo source too (a white-box judge). Log all attempts to `data/runs/redteam-*/`.
3. **Text-leak probe** (the same engineer or the third). `canary/redteam/text_probe.py`: a text-only investigator (stub tonight, OpenAI available) that sees only messages and interview text with no tools. Its accuracy at naming the mole must be ≈ chance. If it's higher, the text leaks the truth: report it to ENV with examples.

## Specific holes to check (at minimum)
- The truth in the agent's filesystem, env vars or process list (with HARNESS's isolation check)
- Error messages that leak (e.g. "e07 is not the mole", or different error text for the mole)
- Response timing or length differences that depend on the mole
- The seed being inferable from public data, then the world regenerated locally (judge seeds must not be derivable: world text is frozen, but can the agent regenerate the world from `rules.py` and the seed if the code is public? → judge worlds must use a server-side secret salt)
- Accusing several people, repeated accusations, accusations after the end
- `restrict_all` then accusing at the end (must score well below the solver)
- The tool cap and daily caps actually enforced; `advance_day` spam
- V manipulation (can any action raise V?)
- The ledger endpoint reachable without the token
- Canary assignment edge cases: one variant per person (must be blocked by `max_variants`), empty assignment, the mole alone

## Milestones
| Time | Milestone |
|---|---|
| 03:30 | Hole checklist + baselines on Env v0 |
| 05:00 | Fuzzer running (locally + FR8 J2) |
| 05:30 | Codex exploit hunter run #1 |
| 06:30 | Every baseline ≈ 0 and no exploit beats the solver; `EXPLOITS.md` v1 (attempt → result → fix → test) |
| 08:00 | Second round after fixes |

## v2 additions (01:55)
1. **Property-based tests** with `hypothesis` (already in the dev dependencies), on random action sequences:
   - score > 0 implies exactly one correct accusation;
   - V never increases;
   - determinism;
   - no tool output contains the mole id;
   - error text and length are identical for mole and innocent targets;
   - also under evolved mole strategies.
2. **`make hunt`:** a one-command exploit playground for the judges (random / malformed / parallel-accuse fuzzing against a fresh local server). It prints "best non-solver score found" next to the solver's score. Ask HARNESS to add the Makefile target.
3. **≥15 attempts** in `EXPLOITS.md`, each with a regression test.
4. **Reward-monotonicity plot** (`results/monotonicity.png`): random < heuristic < hinted LLM < solver.
