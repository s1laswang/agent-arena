# Anti-cheat report (owner: Vaishnav), branch `vaishnav/canary-cheat`

## REVIEW REQUEST: CEO, HEAD-INTEGRITY and every head, please double review before merging

Please review the branch independently. Don't trust this report: rerun the commands below and try to break the reward yourself. Findings go in a PR comment or in `docs/reports/integrity.md`.

**What to check:**

1. `harbor/template/tests/test.sh` (EXPLOITS #42), merged by hand with PR #7's signature check. In shared-verifier builds it now:
   - kills leftover agent processes (it keeps PID 1, itself and its parent chain);
   - grades only from the token-authenticated `GET /ledger` and never reads `/evidence`;
   - writes both `reward.txt` and `reward.json`, because Harbor reads `reward.json` first.

   Does the default separate mode still behave exactly as before?
2. `canary/redteam/anticheat.py`:
   - the new effort ladder;
   - the attack pass rule (full runs vs. fast mode);
   - the Harbor checks, at trial level and job level.

   Can any of them report "blocked" or "consistent" while testing nothing?
3. `canary/redteam/harbor_cheat.py` (`ORACLE_POLICY=cheat_probe`). Exit codes: 0 = no hole, 3 = hole, 2 = did not run. Does it miss a hole class?
4. `canary/reproduce.py` and `canary/eval.py`: `make reproduce` now exits 1 on an anti-cheat failure. Could this break anyone's pipeline?
5. `canary/rules.py`: v1.2 is frozen in `TIERS_HISTORY` (v1.2 and v1.3 share their params; only `KNOWN_V_MODE` differs).

**Commands:**
```bash
uv run python -m pytest tests/test_anticheat.py tests/test_harbor_cheat.py -q
uv run python -m canary.redteam.anticheat --judge --seeds 40 --world-secret canary-anticheat-public-test-v1 --out /tmp/ac   # compare with results/anticheat/exploits.md
REPRO_FAST=1 make reproduce        # the last line says ANTI-CHEAT: ...; the exit code is 1 on a failure
```

## Status (Sat 14 Nov, 19:45; branch rebuilt on `justSilas` b4557e0, PR #7's HMAC-signed ledger included)

**Done (verified):**
- A fresh four-judge panel scored round 1 at reward integrity 19-20/25 and craft 11-12/15, with 14 findings that skeptics confirmed. All 14 are fixed on this branch; see the commit "fixes from a fresh 4-judge review panel".
- Closed an exploit: in shared-verifier builds a planted `/evidence/ledger.json` scored 1.0 (EXPLOITS #42).
- Shared mode is still **not for judging**. On our Harbor 0.25 / Docker Desktop host it did not run test.sh at all, so `build.py` now prints a warning.
- `cheat_probe` through Harbor at this branch's code (with the PR #7 signed ledger), separate verifier: **0.0 on medium and 0.0 on hard**, `signature=ok`, 0 holes in 130 attempts each.
- Battery over 40 judge seeds × 3 tiers under a public test secret, every probe blocked: `results/anticheat/exploits.md`. Replay: 819 of 829 committed episodes identical; the other 10 are grok episodes on secret seeds. Harbor consistency: 25/25 trials and 11/11 job summaries, including PR #7's c1-* runs.

**Known limits, said plainly:**
- The Harbor consistency check catches files that disagree with each other. It cannot catch a forger who edits every copy the same way.
- Shared verifier mode is not usable for judging.
- On Windows, 2 timeout tests (POSIX SIGALRM) and the `test_integrity_mcp.py` file-permission tests fail. They fail the same way on `justSilas`.

**Next:** a second fresh judge round on the pushed commit; any findings get fixed on this branch.
