# INTEGRITY report (s3-integrity session)

Owner: the integrity engineer (session S3). The canonical exploit ledger is [docs/EXPLOITS.md](../EXPLOITS.md) ("Judges: start here" at the top). The anti-cheat battery is Vaishnav's design. This file logs each integrity check and what it found, newest last.

## Sat 14 Nov 23:00–00:10 EET: one ledger, re-run on the justSilas tip (309b65f, then rebased onto 0f379cd)

- **Ledger merged.** The previous judge-facing draft (an old subagent worktree, uncommitted) is folded into `docs/EXPLOITS.md`. It adds "Judges: start here" (J1–J14: attack class, result, mitigation, enforcing test), Residual risks, and a "where your idea is covered" index on top of the full history. New history rows: #43–#44 (Gemini swarm), #45–#47 (Momin's fleet probes, 18:40), #48 (isolation), #49 (this re-run). Rows #0 and #1 were updated for the `stop_early` / `guess_day1` split. The draft's numbers predate the current battery; every number now comes from a committed file, and the file is named.
- **`make hunt`:** best non-solver 0.000, 0 invariant violations in all 16 tier × mode cells; solver 0.798 / 0.611 / 0.472 / 0.541 (easy / medium / hard / hard_forge). Log: `results/anticheat/hunt.log`.
- **Momin's corpus, widened to easy:** 129 rows × seeds 0-2 × 3 tiers = 1,161 runs, 0 accepted, 0 changed (`results/anticheat/corpus_eval.txt`).
- **`make anticheat-verify`** (on 309b65f): 96 rows rerun on 40 seeds × 3 tiers under the public secret, 0 differences.
- **Judge-protocol hunt** (`scripts/judge_hunt.py`, new): 12 wire-level attacks on the real MCP server, **12 of 12 held** (`results/anticheat/judge_hunt.md`). Correct vs wrong accusation: the agent's view afterwards is identical.
- **Gemini swarm w2b-008** (CEO request): flagged "confirmed" by the swarm at n=4. Scripted as `canary/redteam/swarm_probes.py`, run on 40 judge + 100 dev seeds per tier: below the solver in every cell (judge: +0.742 / +0.648 / +0.363 vs +0.765 / +0.671 / +0.545), honest elimination play. The flag was an audit false positive: the posterior-based "justified" check does not credit hard elimination. Added as battery row `swarm_w2b008` (paired one-sided rule) and EXPLOITS #50. Difficulty note forwarded: on easy and medium this no-Bayes heuristic is statistically tied with the solver.
- **S5 flake fixed** (EXPLOITS #51): a plus probe "beat" the solver by abstaining after the solver's wrong last-day accusation. The rule now counts only seeds where the plus episode accepted the accusation; an abstaining plus episode must score exactly 0; full runs need mean ≤ solver + 0.05. Deterministic regression test on medium 900000 under the public secret.
- **Battery regenerated** after rebasing onto justSilas 0f379cd: all probes blocked; replay 959 of 969 (47,586 steps, 0 differ; the 140 v1.4 gemini-4-carbon episodes now replay-verified); Harbor 37 of 37.
- **Tests:** `tests/test_anticheat.py` + `tests/test_harbor_ledger_sig.py`: 120 passed. The full local `make test` was stopped twice: once deliberately (stale tree mid-edit), and once at about 66% by Claude Code's low-memory reaper, with no failures up to that point. The full suite runs in the PR's CI.
- **Facts checked from files:** cheat_probe 0.0 × 6 (`signature=ok`, 149 attempts, `"holes": []`); signed cheat −1.0 × 6; tamper negative control: forged `score: 1.0` → reward 0, `FAIL: bad ledger signature`; isolation OK in 31/31 trials that ran solve.sh; swarm 35 whitebox + 16 blackbox = 51 attackers, 0 exploits, 1,789 tool calls, positive control 4/4.
- **Residual risks** (documented, not changed after the freeze): sidecar holds `GEMINI_API_KEY`; `check_leak_feed` spends daily budget; published retired keys cannot catch re-signed forgeries.

## 01:40 gate: expert tier (justSilas-expert)

Pending.

## ~07:00: `afterquery-final` judge-protocol hunt

Pending.
