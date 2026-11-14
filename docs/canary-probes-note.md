# Canary integrity probes (rw-exploit, offline, no model calls)

Tests: `tests/test_integrity_sleeper_port.py`, 143 pass, 1 xfail (finding 1 below). Run: `GEMINI_API_KEY= PYTHONPATH=. python -m pytest tests/test_integrity_sleeper_port.py`. Nothing scored above what the rules allow and nothing broke.

| attack | result | where | note |
|---|---|---|---|
| accuse after the episode ended by tool cap (easy, medium) | rejected "episode over", score 0 | `canary/env.py:266-276` | the cap check runs after the call, so the cap-th call still executes |
| accuse as the very last allowed call | counts, score V (or the wrong score) | `env.py:266-276` | by design; the instruction says reaching the limit ends the episode with 0, a reader may think the cap-th call is lost. One sentence in `instruction()` removes the doubt |
| foreign or lookalike ids: e99, e12, e-1, trailing space, newline, zero-width space, Cyrillic "е00", e0, e000, E00, NUL byte, 100 kB string, ints, bool, float, list, dict, None | all rejected, episode not locked, accusing the mole afterwards still works, each call counted | `env.py` `_emp` | clean |
| accuse every person, one fresh world per person, 3 seeds | exactly one positive score (the mole), all others the wrong-accusation score, response identical except the echoed id | `env.py:245` | no per-person tell |
| accuse all 12 people in parallel on one Episode | exactly one accepted, one ledger entry | `mcp_server.py:149` (lock) | clean |
| 11 tools x 10 hostile argument shapes | none raised, none changed V, ledger or day, each rejected call still counted toward the cap | `mcp_server.py:149` | the `except Exception` branch there would not count a crashing call toward the cap, because the history entry is appended inside `Env._call`; no crashing input found, so latent only |
| /ledger and /admin/reset from the agent side (empty, short, wrong, 63-char token; admin unset) | all 403; healthz open | `mcp_server.py:163, 190-200` | clean; admin is disabled when no token is configured |
| Harbor template: agent-side files vs the baked world secret and seed | secret only in the sidecar build context | `harbor/template/environment/*` | clean |
| Harbor compose: pid, volumes, docker.sock, privileged, network_mode, cap_add, ports | none present (comments stripped) | `docker-compose.yaml` | clean |
| verifier reads only the sidecar ledger, refuses a symlink and an out-of-range score | present | `tests/test.sh:30,49` | clean |

## Findings
1. **Sidecar gets the model key** (`harbor/template/environment/docker-compose.yaml:31`, `GEMINI_API_KEY: "$${GEMINI_API_KEY:-}"`). The template provider needs no key. No route to `main` found (separate containers, no shared pid or volume), so this is least privilege, not an exploit. Fix: drop the line unless `CANARY_PROVIDER` is an LLM provider. The test is xfail(strict) until then. Side note: `$$` is Compose's escape, so the container may receive the literal text `${GEMINI_API_KEY:-}` instead of the key; check what Harbor does.
2. **Latent cap bypass** (`mcp_server.py:149`): an exception inside `Env.call` returns "invalid arguments" without a history entry, so that call is free. Fix: count it in `Episode.call` on that path.
3. **Docs**: state that the tool-call cap is checked after the call, so the last call still counts.

## Not covered, needs a container (not run here)
The logs and reward-file race on a live Harbor run (`/logs` permissions, killing or racing the collect step, a lingering agent process after the agent phase). The template says Harbor stops `main` before the collect hook, so a lingering process should not survive; a real `harbor run` is needed to confirm, same as env-harbor-separate on the Sleeper side. `harbor/check_isolation.sh` was not executed.
