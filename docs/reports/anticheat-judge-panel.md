# Anti-cheat judge panel: every round, as returned

Each round started **fresh** agents: they saw no earlier review. Each judge scored only the anti-cheat part on the official rubric (reward integrity /25, craft /15) from a different angle: rubric, exploit hunter, craft and reproducibility, claims auditor.

Every finding then went to 3 skeptics who tried to refute it. They used three lenses: reproduce it, does it really cost rubric points, and is the fix right. A finding counts as *confirmed* when at least 2 of the 3 found it real and in scope.

The scores are the judges' own numbers. The workflow that ran them is in this session's tooling, and the raw outputs are summarised here.

## Round 1 (reviewed commit `7bd9ca4`)

| judge | reward integrity | craft |
|---|---|---|
| rubric | 20 / 25 | 12 / 15 |
| hunter | 19 / 25 | 11 / 15 |
| repro | 20 / 25 | 11 / 15 |
| claims | 19 / 25 | 11 / 15 |

**Confirmed (14), fixed in 0fe7961, 7e30597, 06ebf9c:**

- F1 (major): Shared-verifier mode: agent-written /evidence/ledger.json becomes the reward (forge 1.0), and anti-cheat never tests this mode
- F2 (major): cheat_probe only exploits ledger holes; readable SALT/episode files or other holes still end at reward 0 / exit 0 and nothing checks cheat.json holes
- F3 (major): Stale replay count in README and EXPLOITS.md (579 of 589 vs actual 819 of 829)
- F4 (minor): make reproduce exits 0 even when the anti-cheat battery fails
- F5 (minor): Claimed 40-judge-seed battery result has no committed artifact and no test; CI checks only 4 dev seeds
- F6 (minor): Attack pass rule (mean <= 0 under a fresh random secret) is random; fast reproduce reports ANTI-CHEAT FAILURE
- F7 (minor): Stop-early ladder only removes the accusation, so 'exactly 0' holds by construction; no probe cuts then guesses
- F8 (minor): Harbor consistency check passes a coherent forgery; docstring claims it 'catches an edited result file'
- F9 (minor): Committed cheat_probe Harbor logs were not produced by the committed code
- F10 (minor): cheat.py docstring says it MUST end with reward 0, but it scores -1
- F11 (minor): Harbor consistency check ignores job-level result.json and the probe's own report
- F12 (minor): README overclaims Harbor trajectory check (22 of 22); only 6 trials have a trajectory
- F14 (minor): README runtime claim (~10 s) no longer holds with the anti-cheat battery in make reproduce
- F17 (nit): hidden_args probe sends hidden keys without required args, so it mostly tests missing-argument rejection

**Rejected by the skeptics (5):**

- F13: No-verifier-reward Harbor trials are silently excluded as 'infrastructure failures'
- F15: Cheat-corpus injection test holds by construction
- F16: Harbor version note contradicts the committed run
- F18: Symlinked-evidence verifier test is skipped on Windows
- F19: Anti-cheat table scrolls away under the committed-file list and slow act() warnings

## Round 2 (reviewed commit `06ebf9c`)

| judge | reward integrity | craft |
|---|---|---|
| rubric | 22 / 25 | 13 / 15 |
| hunter | 20 / 25 | 12 / 15 |
| repro | 23 / 25 | 13 / 15 |
| claims | 22 / 25 | 12 / 15 |

**Confirmed (16), fixed in db62ab3:**

- F1 (major): garbage_args reports blocked on easy/medium without ever sending a malformed accuse
- F2 (minor): Probes that cannot fail by construction (stop-early ladder, most plus probes, control) are counted as 'blocked' and inflate the probe count
- F3 (minor): Most committed Harbor trials (including the results/harbor/cheat job) were graded by a pre-signing verifier, yet the check reports 25/25 consistent
- F4 (minor): The Harbor consistency check cannot verify that committed ledgers are authentic
- F5 (minor): Shared-verifier mode is still a demonstrated reward-1.0 hole in Harbor (documented, not closed)
- F6 (minor): Shared-mode hardening (process kill, stale reward deletion) is never tested, its Docker repro is uncommitted, and a missing ps silently skips the kill
- F7 (minor): Docs state the wrong cheat_probe attempt count and family breakdown (130 vs 132)
- F8 (minor): probe_all never accuses, so its 'blocked' row is just do_nothing
- F9 (minor): solver_plus_bad_canary stays 'blocked' even when the per-person canary is accepted
- F12 (minor): The committed-artifact test trusts the artifact's own pass flags and never recomputes anything
- F14 (minor): cheat_probe coverage gaps: hidden args only on read tools, everything on day 1, no JSON-RPC batch or session tricks
- F15 (nit): The cheat_probe consistency check passes when cheat.json is missing (probe trials identified only by agent-written file)
- F18 (nit): README integrity section is one very dense paragraph
- F19 (nit): Replay checks only the final score and accused, not the recorded observations
- F22 (nit): EXPLOITS #42 status says 'fixed in the default separate verifier', but the default was never vulnerable and shared mode is unverified
- F23 (nit): In fast mode the summary line still claims 'effort ladder below the solver' although the ladder is not judged

**Rejected by the skeptics (7):**

- F10: No exploit evidence from an LLM agent through the standard harness
- F11: The battery runs in-process, so only one Harbor seed per tier covers the MCP wire
- F13: Harbor consistency check ignores verifier/reward.json although Harbor reads it first
- F16: 'Doing the task well is best' is shown only against cut-down versions of the solver
- F17: The anti-cheat table from `make reproduce` is statistical; exact numbers need a second command
- F20: Verifier fail-closed tests never reach the range, NaN or inf branches
- F21: The claim that a cheat_probe hole fails the Harbor trial is only static; no Harbor negative control

## Round 3 (reviewed commit `db62ab3`)

| judge | reward integrity | craft |
|---|---|---|
| rubric | 22 / 25 | 13 / 15 |
| hunter | 21 / 25 | 13 / 15 |
| repro | 22 / 25 | 13 / 15 |
| claims | 20 / 25 | 12 / 15 |

**Confirmed (16), fixed in the commit after db62ab3 on this branch:**

- F1 (major): Published retired signing key cannot catch a forgery that edits every copy and re-signs it, but the docs say it does
- F2 (minor): Harbor consistency check never compares the reward in verifier/test-stdout.txt or reward.json
- F3 (minor): Harbor consistency check skips a cheat_probe trial with holes when it has no verifier reward
- F4 (minor): Some of cheat_probe's 149 'attempts' tested nothing (day_scan always fails, a control call failed, a redirect was not followed)
- F5 (minor): Shared-verifier mode: planted Python startup code runs with the signing key, and the kill loop runs over a single process list
- F6 (minor): Two 'plus' rows counted as real probes hold by construction
- F7 (minor): Cheat-corpus result '0 calls accepted' holds by construction
- F8 (minor): EXPECT_ACCUSE is checked over the whole probe, but the docs say it holds on every seed
- F10 (minor): Harbor-level exploit evidence is thin, and part of it comes from the older unsigned verifier
- F12 (nit): Checking the 40-seed battery takes two manual steps
- F13 (nit): Docs disagree on cheat_probe timing, duration, attempt count and which jobs publish a key
- F14 (nit): README overstates what replay and the effort ladder prove
- F16 (nit): Duplicated payload-writing code, and --out resolves against the repo root instead of the working directory
- F18 (nit): 'make hunt ... about 1 minute' understates the runtime
- F19 (nit): rules.py says 'all 300 committed v1.2 episodes', but 310 are committed
- F20 (nit): Judge-panel scores in commit titles and the report cannot be checked

**Rejected by the skeptics (4):**

- F9: Server stores the arguments of every call made after the episode ends, with no limit
- F11: 'Doing the task well is best' is shown only against variants of the solver
- F15: REPRO_ANTICHEAT=0 silently skips the battery and still exits 0
- F17: Shared-mode kill loop is checked only by a markdown log, not by a test

## Limits the panel raised that stay open (said plainly)

- Committed Harbor files cannot be proven genuine. A published build key lets anyone re-sign a forged ledger, and an asymmetric (Ed25519) signature from the sidecar would need an env/server change. The consistency check catches files that disagree with each other and edits that were not re-signed.
- Shared-verifier mode is not for judging. `build.py` refuses it unless you pass an explicit flag.
- Harbor-level evidence covers 3 judge seeds × medium/hard per policy. Not all 40 seeds are run through Harbor: in-process, the battery covers all 40.
