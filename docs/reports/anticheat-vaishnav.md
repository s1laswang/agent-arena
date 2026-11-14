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

## Status (Sat 14 Nov, ~20:45; on top of `justSilas` b4557e0, which includes PR #7's signed ledger)

**Judge panel (fresh agents each round, scoring the official rubric; every finding checked by 3 skeptics):**

| Round | Reward integrity | Craft | Findings confirmed |
|---|---|---|---|
| 1 (7bd9ca4) | 19-20 / 25 | 11-12 / 15 | 14, all fixed |
| 2 (06ebf9c) | 20-23 / 25 | 12-13 / 15 | 16, all fixed in the next commit |

**Done (verified):**
- Closed an exploit: in shared-verifier builds a planted `/evidence/ledger.json` scored 1.0 (EXPLOITS #42). Shared mode is still **not for judging**: on our Harbor 0.25 / Docker Desktop host it did not run test.sh at all. `build.py` now refuses shared mode unless you pass `--unsafe-shared-not-for-judging`. The hardened test.sh is checked in a committed Docker reproduction: `results/anticheat/shared-verifier-docker-repro.md`.
- Battery:
  - every tool's garbage runs on its own fresh Env;
  - every accusing probe must really accuse (ProbeAll is now made to accuse);
  - plus probes that can change V;
  - by-construction rows labelled `sanity`;
  - replay compares all 33,593 recorded tool results, 0 differ;
  - Harbor checks report signed vs unsigned verifiers and verify the HMAC where a retired build key is published;
  - `make reproduce` exits 1 on any failure.
- `cheat_probe` through Harbor at this code: **0.0 / 0.0, `signature=ok`, 0 holes in 149 attempts each**, ledgers HMAC-verified against the published retired key. A signed stop-early baseline scored −1.0 / −1.0.
- `results/anticheat/exploits.md`: 40 judge seeds × 3 tiers under a public test secret, all blocked. A test recomputes a slice and compares it per seed.

**Known limits, said plainly:**
- For Harbor jobs without a published retired key (everything older than PR #7, and PR #7's own c1-* jobs), the consistency check catches files that disagree. It cannot catch a forger who edits every copy the same way.
- Shared verifier mode is not usable for judging.
- On Windows: `test_build_writes_key_only_to_sidecar_and_verifier` fails (it expects file mode 0600, and Windows reports 0666), and so do 2 POSIX-only timeout tests and the `test_integrity_mcp.py` file-permission tests. They fail the same way on `justSilas`.

**Next:** judge round 3 on the new commit.
