# Canary: AfterQuery "Break the Agent" submission

*Junction 2026. Draft written Sat 14 Nov ~23:10 Helsinki from branch `justSilas` at commit `09e7363`. The team submits ~09:30 Sun.*

*Every number below names the committed file it comes from. `TODO(owner)` marks work that is not committed yet. Our Google DeepMind Gemini entry is a separate write-up: [docs/gemini/SUBMISSION.md](gemini/SUBMISSION.md).*

## Form fields (paste as is)

```text
Project name: Canary

Tagline (58 chars):
Catch the mole with canary traps before the value runs out

Description (567 chars):
Canary is an RL environment served over MCP. A company has one mole who leaks documents, and every leak costs value. The agent is head of security: it plants canary documents, reads a delayed, noisy leak feed and must accuse once. Correct = value left, wrong = -1, none = 0. The reference is a Bayesian solver that sees only what the agent sees. On the hard tier, with OpenCode over MCP, gemini-4-carbon scores 65% of the solver (95% CI 24-98%, n=30). Doing nothing scores exactly 0, and no attack we tried beats honest play. One keyless command reproduces our table.

Track: AfterQuery - Break the Agent (main track)
Side track: Google DeepMind - Best Use of Gemini API (own write-up: docs/gemini/SUBMISSION.md)

Repo: https://github.com/s1laswang/agent-arena/tree/justSilas

Video: TODO(Ivar): video link
```

- The 65% [24%, 98%] comes from [data/runs/committed/v1.4/paired_table_gemini.md](../data/runs/committed/v1.4/paired_table_gemini.md) and [docs/reports/gap.md](reports/gap.md).
- TODO(Silas): check whether the platform takes one project with two tracks or two separate entries. If two, drop the "Side track" line here.
- TODO(Silas): if the team tags `afterquery-final`, decide whether the repo link should point at the tag instead of the moving branch.

## 1. What Canary is

A simulated company has exactly one **mole** who leaks documents to a rival. The company starts with value V = 1.0, and every leak lowers it. The agent under test is the **head of security**.

- **Actions (13 MCP tools).** `status`, `list_employees`, `list_documents`, `read_access_logs`, `search_messages`, `read_message`, `interview`, `plant_canary`, `check_leak_feed`, `restrict_access`, `unrestrict_access`, `advance_day`, `accuse` (`canary/env.py`).
- **Canary documents.** The agent sends different variants of a document to different groups of people. If a variant shows up in the leak feed, the mole was in that group. This is a real counter-intelligence trick (README, "Real-world grounding").
- **A delayed, noisy leak feed.** On hard, a leak surfaces 2 to 3 days after it happens, and the feed shows the true variant 95% of the time. The `status` tool shows only the damage the company knows about. Damage from leaks that have not surfaced yet still counts in the score (README, "The rules, briefly").
- **Adversaries.** On medium and hard there is an innocent decoy who sends angry messages, the mole frames others in the access logs, and the mole avoids widely shared canaries.
- **Hard tier (the judged tier).** 40 employees, 21 days, 2 canaries a day with up to 3 variants each, 0.05 V lost per leak, 8 investigative calls a day, 420 tool calls in total (README; exact values in `canary/rules.py`, `TIERS_VERSION = "v1.4"`).
- **One accusation.** The first accepted accusation ends the episode. `accuse` never tells the agent if it was right.

**Scoring** (computed on the server from the ledger, never from agent text):

| outcome | score |
|---|---|
| correct accusation | the true V left at that moment |
| wrong accusation | -1 |
| no accusation | 0 |

So doing nothing scores exactly 0, and a random guess has negative expected value. To score above 0 the agent must gather evidence until accusing is worth the -1 risk, and do it before the leaks drain V.

**The reference run** is a Bayesian canary-trap solver (`canary/solver/`). It talks to the world only through the same tools and sees only what the agent sees. It keeps a posterior over who the mole is, from its own canary assignments, the leak feed (with the stated delays and fingerprint noise), access logs and interviews. It plants canaries in groups balanced by that posterior. It accuses only when the expected value of accusing beats 0, that is P x V - (1 - P) > 0, and otherwise keeps investigating or abstains. Every quantity it uses is public: in the instructions or from the tools ([docs/reports/gap.md](reports/gap.md), "Fairness").

## 2. Judges: run this

You need `uv` and `make` (Linux or macOS; on Windows use WSL). No API key is needed for anything in this table. Times are the ones the repo states.

| Command | What you should see | Time (source) |
|---|---|---|
| `make setup && make reproduce` | The score table on 40 judge seeds per tier. Solver about +0.6 on medium and hard. `do_nothing` exactly 0. `stop_early` (stops on day 1, no accusation) exactly 0. `guess_day1` (random accusation on day 1) about -0.9. Last line: `ANTI-CHEAT: every probe blocked ...`. Exit code 1 if any cheat gets through. Output goes to `results/latest/` (gitignored). | ~3 min (README, "For judges") |
| `make accept` | Runs setup, reproduce, checks each baseline against the README band, and starts the MCP server once. Prints an `ACCEPT TABLE` and `RESULT: PASS`. The Harbor row is `SKIP` by design (it needs Docker and a model key). | README says 40-60 s, see the note below |
| `make anticheat-verify` | `0 differences`: the committed anti-cheat battery ([results/anticheat/exploits.md](../results/anticheat/exploits.md)) reruns exactly. | ~1 min (README) |
| `make hunt` | Your own exploit fuzzing on easy, medium, hard and hard_forge: best non-solver score 0.000, 0 violations. | a few min (README) |

Our committed run of the table: [results/judge_table.md](../results/judge_table.md) (secret fingerprint `6a38958f8096`, the table itself took 22.8 s). Solver +0.679 ± 0.048 medium, +0.547 ± 0.143 hard, +0.808 ± 0.027 easy. `stop_early` +0.000 on all three tiers. `guess_day1` -0.900 ± 0.137 / -0.950 ± 0.098 / -0.950 ± 0.098. Each run draws a fresh world secret, so your means will land inside these CIs, not match them exactly. For exact numbers: `CANARY_WORLD_SECRET=<any string> make reproduce`.

Note on runtimes: the README gives ~3 min for `make reproduce` on its first screen, but 25-35 s under "Expected runtimes", and 40-60 s for `make accept`, which runs `make reproduce` inside it. TODO(Silas): time both on the fresh clone and use one set of numbers.

**In the judges' harness (Harbor + OpenCode over MCP; needs Docker).** From [harbor/README.md](../harbor/README.md) and the README:

```bash
uv tool install harbor && uv run python harbor/build.py                      # 10 tasks: hard tier, judge seeds 900000-900009
harbor run -p harbor/dataset -a oracle -n 4                                  # reference solver
harbor run -p harbor/dataset -a oracle --ae ORACLE_POLICY=do_nothing -n 4    # expect 0
harbor run -p harbor/dataset -a oracle --ae ORACLE_POLICY=stop_early -n 4    # expect exactly 0
harbor run -p harbor/dataset -a oracle --ae ORACLE_POLICY=guess_day1 -n 4    # expect about -1
harbor run -p harbor/dataset -a oracle --ae ORACLE_POLICY=cheat_probe -n 4   # ~150 cheat attempts, never accuses: expect exactly 0
GOOGLE_GENERATIVE_AI_API_KEY=<key> harbor run -p harbor/dataset -a opencode -m google/gemini-4-carbon \
    --api-key-name GOOGLE_GENERATIVE_AI_API_KEY -n 4                         # the frontier agent
```

What to expect, and where we saw it:
- **Oracle.** Each build draws a fresh world secret, so there is no fixed number. The in-process solver averages +0.547 ± 0.143 on the 40 hard judge seeds ([results/judge_table.md](../results/judge_table.md)). On earlier builds, single hard oracle tasks scored 0.50 to 0.71, and the Harbor oracle matched the in-process solver on the same build ([harbor/README.md](../harbor/README.md)).
- **do_nothing.** 0.0 in every committed Harbor job (`results/harbor/do_nothing/`, `results/harbor/c1-do_nothing/`).
- **stop_early.** Exactly 0 in-process. The committed Harbor `stop_early` jobs scored -1.0 because that older build accused on day 1 (now `guess_day1`). That Harbor job has not been re-run with the new script ([harbor/README.md](../harbor/README.md)). TODO(Silas): the rehearsal below covers it.
- **cheat_probe.** 0.0 on 6 of 6 trials, 149 attempts each, 0 holes (`results/harbor/cheat-probe/`).
- **The agent.** The key must reach OpenCode as `GOOGLE_GENERATIVE_AI_API_KEY` with `--api-key-name`. Otherwise every trial fails before the first model call and scores 0, which is an infrastructure failure, not a model result ([harbor/README.md](../harbor/README.md), "Pitfall").
- **Runtime.** A 2-trial oracle job took about 1.5 min, and the 6-trial cheat_probe job about 2-3 min ([harbor/README.md](../harbor/README.md)). TODO(Silas): time the full 10-task oracle and OpenCode jobs in the rehearsal.
- **Windows.** A checkout with `core.autocrlf=true` breaks the `.sh` files in the Linux containers. Convert `harbor/dataset*/` to LF first ([harbor/README.md](../harbor/README.md)).

## 3. Rubric: The gap (30)

**Our headline.** Rules v1.4, dev seeds 0-29 per tier, every episode replay-verified, each agent paired with the solver on the same seeds ([data/runs/committed/v1.4/paired_table_gemini.md](../data/runs/committed/v1.4/paired_table_gemini.md), [docs/reports/gap.md](reports/gap.md)):

| gemini-4-carbon run | tier | n | score / solver [95% CI] | luck-adjusted / solver [95% CI] |
|---|---|---|---|---|
| **OpenCode over MCP** (the judges' agent) | hard | 30 | **65% [24%, 98%]** | **72% [52%, 91%]** |
| OpenCode over MCP | medium | 30 | 111% [99%, 127%] | 101% [85%, 119%] |
| in-process (full history) | hard | 30 | 95% [62%, 140%] | 84% [65%, 106%] |
| in-process | medium | 30 | 82% [56%, 108%] | 74% [52%, 99%] |

- On hard with OpenCode, Gemini scores 0.322 ± 0.199 against the solver's 0.499 ± 0.119 on the same 30 seeds (same file).
- **Luck-adjusted** means: score each accusation by its expected value under the solver's posterior at that moment, P x V - (1 - P), and 0 if there is no accusation. It separates good decisions from lucky ones ([docs/reports/gap.md](reports/gap.md)).
- **Pre-registered.** Seeds 0-29 were fixed as the primary set in commit `671ed96`, before any rerun landed. Later reruns are reported as a replication, never swapped in ([docs/reports/gap.md](reports/gap.md)). The Harbor judge set (hard, seeds 900000-900009) was fixed in `docs/PLAN-95.md` before any frontier run on it ([harbor/README.md](../harbor/README.md)).
- **Infra failures.** Attempts that failed for infrastructure reasons (CLI errors, empty model replies, provider outages) were retried. Counting the empty-reply episodes as 0 instead gives 56% [19%, 87%] on hard (same table, "alternative" row).

**Honest reading.** There is a gap on hard in the judges' agent shape, and both CIs exclude parity. But it is wide, it does not show in-process (95%), and it does not show on medium (111%). We do not claim it holds for every harness or model.

**What is not shown yet:**
- **Repeated runs through Harbor itself.** The 65% runs used the OpenCode CLI against our MCP server (`meta.json`: harness `opencode-cli+mcp_server`, OpenCode 1.18.29), not the Harbor container. TODO(Silas): `results/harbor/rehearsal/`, 3 independent OpenCode runs x 10 hard tasks plus the oracle, `do_nothing` and `stop_early`, on the tagged SHA, with each run's mean vs the oracle and the run-to-run spread.
- **The only Harbor run with a frontier model so far** is a 6-task demo (medium and hard, seeds 900000-900002, one run each): Gemini 0.503 vs oracle 0.757, lower on all 6 tasks ([harbor/README.md](../harbor/README.md)). It is small and was on an earlier build, so we do not count it as the gap.
- **Replication.** A pooled look that added the fleet's reruns, not yet replay-verified, gave 76% [34%, 126%] on OpenCode hard (n=32), which includes parity ([docs/reports/CEO.md](reports/CEO.md), 23:15 entry). TODO(Silas): commit the replay-verified replication next to the primary result.
- **Other models.** gemini-3.6-flash on hard is within the CI of the solver, n=6: 97% [76%, 126%] at medium thinking, 106% [82%, 145%] at high ([results/gemini/ladder.md](../results/gemini/ladder.md)). The gemini-3.5-flash v1.4 OpenCode runs are not committed. TODO(Silas): commit them under `data/runs/committed/v1.4/opencode-gemini-3.5-flash/` or drop the claim.
- **Stronger reference / expert tier.** Two candidate tracks (solver_v2 and an expert tier) are gated at 02:00 ([docs/PLAN-95.md](PLAN-95.md), [docs/reports/CEO.md](reports/CEO.md)). TODO(Silas): record the gate outcome here.

**History.** On v1.3, Codex gpt-5.5 over MCP reached 97% [89%, 107%] of the solver on hard (seeds 0-9). That is why v1.4 made hard longer: 40 staff, 21 days, 2 canaries a day. It is a pure parameter change with the same tools and the same reward ([docs/reports/gap.md](reports/gap.md), README).

## 4. Rubric: Meaningful difficulty (30)

**The decisions that matter.** Which groups get which canary variant. How to read leaks that arrive 2-3 days late. When to stop and accuse, when to keep going, and when to abstain.

**The skill ladder proves which decisions decide the score.** Each rung removes one part of the reference solver. Fresh dev seeds 7000-7399, n=400 per tier, paired 95% CIs ([results/skill_ladder_v1.4.md](../results/skill_ladder_v1.4.md)):

| removed from the solver | hard: change in score | medium: change in score |
|---|---|---|
| the expected-value accusation rule (accuse the top suspect on the last day) | -0.371 ± 0.032 | -0.222 ± 0.028 |
| the expected-value accusation rule (accuse at P >= 0.5) | -0.151 ± 0.057 | -0.242 ± 0.060 |
| the leak-delay model | -0.251 ± 0.037 | -0.457 ± 0.034 |
| careful-mole term, decoy handling, framing, second canary | no significant cost | no significant cost |

So two skills decide the game: committing at the right moment, and reasoning about late leaks.

**What Gemini does wrong on v1.4 hard (OpenCode, n=30, same seeds as the solver)** ([data/runs/committed/v1.4/paired_table_gemini.md](../data/runs/committed/v1.4/paired_table_gemini.md)):
- Accuracy 0.83 vs the solver's 0.97.
- It accuses later: mean accusation day 13.2 vs 10.6. Every day of waiting lets more leaks drain V.
- The solver's posterior on the person it accuses is 0.88 on average, vs 0.97 for the solver.
- Mean regret 0.171 V per episode. The 5 costliest decisions are all accusations. Two were tagged `premature_accusation` and cost 0.804 V together ([results/regret_opencode-gemini-4-carbon-v1.4.md](../results/regret_opencode-gemini-4-carbon-v1.4.md)).
- Some losses are luck, not bad decisions. In the Gate B check (OpenCode, hard, seeds 0-9), the miss on seed 1 was an accusation at P = 0.988 that lost to the 5% fingerprint misread ([docs/reports/CEO.md](reports/CEO.md), 19:50). That is why we report the luck-adjusted ratio (72%) next to the raw one.
- Our current reading is slower identification rather than reckless gambling. TODO(Silas): [docs/reports/failure_analysis_v1.4.md](reports/failure_analysis_v1.4.md) (in progress) computes canaries planted, accusation day, V lost to waiting and the posterior at every wrong accusation, all in code.

**Earlier tiers showed the same root skill.** On v1.3, premature accusation was 97-99% of the tagged value lost. Codex accused at P = 0.18 and P = 0.33 when abstaining (0) was worth more, and no frontier episode ever abstained ([docs/reports/gap.md](reports/gap.md)).

**The information and tools to do better are there:**
- The solver uses only the agent's own observations and the published rules ([docs/reports/gap.md](reports/gap.md), "Fairness").
- Every rate and rule is in the MCP instructions. The break-even rule can be computed from them. An external Grok agent did exactly that and abstained at P ≈ 0.53 ([docs/reports/gap.md](reports/gap.md)).
- A scripted replay of a strong agent's tactics (`grok_tactics`) still trails the solver on hard by 0.195 ± 0.033, n=800 fresh seeds ([results/fresh_table_v1.4.md](../results/fresh_table_v1.4.md)). The gap is about decisions, not access.
- Each harder version changed the information or mechanics in the open instructions, never a hidden trick. The solver stayed between 0.58 and 0.72 throughout ([docs/reports/gap.md](reports/gap.md), "Kill-switch history").

**Not done yet:**
- TODO(Silas): [docs/DIFFICULTY.md](DIFFICULTY.md) (in progress), an audit of the instruction text for trick wording, hidden info, impossible timing and broken tools.
- TODO(Silas): the hint ablation. One sentence restating the instruction's own break-even and delay facts, run on gemini-4-carbon, v1.4 hard. The hint set is tested (`tests/test_agents_policy.py`), but no result is committed ([docs/reports/agents.md](reports/agents.md)).
- TODO(all four): human playtests, 2 hard dev-seed episodes each, scores logged ([docs/PLAN-95.md](PLAN-95.md), B3).

## 5. Rubric: Reward integrity (25)

Full list of every attack and its test: [docs/EXPLOITS.md](EXPLOITS.md) (43 rows, #0 to #42).

**Doing nothing or stopping early earns 0.** On 40 judge seeds per tier ([results/judge_table.md](../results/judge_table.md)):

| policy | medium | hard | easy |
|---|---|---|---|
| solver (reference) | +0.679 ± 0.048 | +0.547 ± 0.143 | +0.808 ± 0.027 |
| do_nothing | +0.000 | +0.000 | +0.000 |
| stop_early (stop on day 1, no accusation) | +0.000 | +0.000 | +0.000 |
| guess_day1 (random accusation on day 1) | -0.900 ± 0.137 | -0.950 ± 0.098 | -0.950 ± 0.098 |

**Anti-cheat battery** (runs inside `make reproduce`; design: Vaishnav, ported from his Poisoned Inbox project). Committed run: 40 judge seeds x easy, medium, hard under a public test secret ([results/anticheat/exploits.md](../results/anticheat/exploits.md)):
- 14 attack probes per tier, from accuse-everyone (in sequence and in parallel threads) to garbage arguments on every tool. All blocked: every attack mean is at or below 0 and below the solver.
- The **effort ladder** stops the solver at 25/50/75/90% of its calls and accuses its best guess. Its best cut is hard 90% at +0.051 ± 0.244, vs the full solver's +0.545 ± 0.098. Stopping early and guessing never pays.
- **Replay.** 819 of 829 committed episodes re-played on a fresh environment, 33,593 recorded tool results compared step by step, 0 differ. The other 10 are on secret-keyed judge seeds.
- **Harbor consistency.** 37 of 37 committed trials and 13 of 13 job summaries agree with each other.

**In Harbor** ([harbor/README.md](../harbor/README.md)):
- **Isolation.** The game server runs in a separate sidecar container, with no shared PID namespace or filesystem. `check_isolation.sh` runs inside the agent container: `ISOLATION OK: 11 checks passed, 0 findings`.
- **cheat_probe** never accuses and tries 149 tricks (guessed ledger tokens, secret files, `/proc/*/environ`, planted reward files, made-up MCP tools, malformed accusations). Reward 0.0 on 6 of 6 trials, 0 holes (`results/harbor/cheat-probe/`). The accuse-everyone `cheat` scores -1.0 on the same build (`results/harbor/signed-cheat/`).
- **Signed ledger.** The server HMAC-signs the ledger with a per-build key that never enters the agent container. The verifier fails closed. In the negative control, a forged `score = 1.0` was graded 0 (`results/harbor_negative/c1-tamper/`).

**Gemini attackers** (owned by the Gemini track, [docs/gemini/SUBMISSION.md](gemini/SUBMISSION.md)):
- 35 whitebox attackers that read the whole repo: 0 verified exploits ([results/gemini/swarm.md](../results/gemini/swarm.md)).
- 18 blackbox attackers: 0 verified exploits ([results/gemini/swarm_blackbox.md](../results/gemini/swarm_blackbox.md)).
- Positive control: with a known exploit reopened (EXPLOITS #23, public dev seeds), 4 of 4 attackers found it and the pipeline flagged it ([results/gemini/swarm_control.md](../results/gemini/swarm_control.md)). So the detector does catch real exploits.

**Momin's cheat corpus.** 129 rejected calls, injected into the solver: 774 runs, 0 calls accepted, 0 score changes ([docs/EXPLOITS.md](EXPLOITS.md)).

**Exploits we found and closed** ([docs/EXPLOITS.md](EXPLOITS.md)):

| # | Exploit | Before the fix | Fix |
|---|---|---|---|
| 1 | Stop early and guess, when a wrong accusation cost 0 | 0.10 on medium: a free lottery ticket | wrong accusation = -1 |
| 23, 24, 28 | Rebuild the world from public code and read the mole | 1.0 | judge worlds keyed by a secret that fails closed; the server refuses dev seeds |
| 27 | Read the server's environment from the same user | 1.0 | secrets only in 0600 files; in Harbor, a separate sidecar container |
| 42 | Plant a fake ledger in shared-verifier mode (not the default) | 1.0 | grade only from the token-protected ledger; shared mode refuses to build without an "unsafe" flag |

**Doing the task well is the best way to score.** The solver is above every scripted baseline and every attack on every tier (tables above). Adding an extra step before its own accusation never beats it (the "plus probes" in [results/anticheat/exploits.md](../results/anticheat/exploits.md)).

**Not done yet.** TODO(Vaishnav): a 15-minute hunt that follows the judges' protocol, plus `make hunt` and the full anti-cheat battery, on the tagged `afterquery-final` SHA. Report in [docs/reports/integrity.md](reports/integrity.md).

## 6. Rubric: Craft (15)

- **One command.** `make setup && make reproduce`, no keys, no `.env` (README). `make accept` adds the checks. CI runs `make test` and the fast `make reproduce` (5 seeds per tier) on every push to `justSilas` and on every pull request (`.github/workflows/ci.yml`).
- **Rules that fit the setting.** The canary trap is a real technique. Tom Clancy named it in *Patriot Games* (1987), and Peter Wright's *Spycatcher* describes it as MI5's "barium meal test" (README, "Real-world grounding"). Late leaks, a mole who adapts and frames others, and value that bleeds while you wait are what make the real problem hard.
- **Everything is replayable.** Committed episodes re-play step by step (section 5). Judge worlds use a secret per build, so nobody, us included, has seen the worlds a judge's build serves ([harbor/README.md](../harbor/README.md)).
- **Tests.** `make test`: 824 passed at the PR #16 merge ([docs/reports/CEO.md](reports/CEO.md), 23:15 entry).
- **Play it yourself.** `make game-serve` builds a browser game on the real `canary` package (Pyodide) at http://localhost:8000 (`Makefile`). TODO(Ivar): hosted game link. The GitHub Pages workflow is manual on purpose and needs Silas's go-ahead (`.github/workflows/pages.yml`).

**Not done yet:**
- TODO(Silas): README first screen (in progress in another session): one claim, one v1.4 table, one command.
- TODO(Silas): the README and the header of [results/judge_table.md](../results/judge_table.md) still say "v1.4 frontier gap: not established". That was written from the 21:26 in-process bake-off (n=10), before the v1.4 headline in [docs/reports/gap.md](reports/gap.md) was committed (`693a3b2`). Align them before submitting.
- TODO(Silas): fresh-clone log in `results/fresh_clone/` on the submit commit.
- TODO(Silas): tag `afterquery-final`.
- TODO(Silas): [docs/DEMO.md](DEMO.md) (in progress), the minute-by-minute 10-minute demo.

## 7. Tiebreak: does a small model improve after training on Canary?

**Short answer: not in reward yet.** It learns the protocol, not the decision to commit.

| model | trained on | result | source |
|---|---|---|---|
| J4: Qwen2.5-1.5B-Instruct + LoRA, 450 steps, imitating the solver (tiers v1.3) | about 5% of one epoch over 3,000 solver episodes | base 0.00 (n=2) vs LoRA about -0.15 (n=17) on held-out seeds. Valid tool calls 0.08 to 0.99. Agreement with the solver's actions 0.00 to about 0.85 | [docs/reports/fr8.md](reports/fr8.md) (08:20), [fr8/analysis/out/j4_proxy.md](../fr8/analysis/out/j4_proxy.md) |
| v2 (job 44412): dense 4k windows, episode endings oversampled | J3 v2 solver episodes | held-out -0.395 vs base 0.000; it accuses indiscriminately | [docs/reports/CEO.md](reports/CEO.md) (23:15), [docs/reports/fr8.md](reports/fr8.md) |
| v3: GRPO from v2 on the environment's own reward | planned: env reward on easy + medium train seeds, never judge or held-out seeds | running (jobs 44553 and 44555, evals 44554 and 44556) | [docs/reports/CEO.md](reports/CEO.md) (23:15), [docs/PLAN-95.md](PLAN-95.md) (E2) |
| GRPO mole: Qwen2.5-0.5B-Instruct + LoRA plays the mole | env reward vs scripted investigators | valid action JSON 3-16% at step 0 to 97-100% by step ~50. Reward among valid moves stays flat, and each run collapses to one action | [docs/reports/agents.md](reports/agents.md) (WS3 B) |

- So far the small investigator learns the protocol and the investigation rhythm (plant canaries, check the feed, read logs, advance), but not when to accuse.
- Held-out n is small because the HF eval is slow ([docs/reports/fr8.md](reports/fr8.md)).
- TODO(Momin): v3 held-out result (n >= 30, with CIs) by ~07:00. Report it here either way, as base vs v2 vs v3 on held-out seeds.

## 8. Known limits

- **The gap is narrow in scope.** It shows on hard, with OpenCode over MCP, for one model (gemini-4-carbon), with a wide CI (65% [24%, 98%]). It does not show in-process or on medium. The v1.4 frontier runs are Gemini only. The GPT-5.5, Codex and Grok runs are on older rules (v1.2 and v1.3) and count as history only.
- **Repeated Harbor runs are not committed yet** (section 3). The judges' 3 runs x 10 hard tasks could land near parity by luck: one lucky guess scores the same as a correct inference ([docs/PLAN-95.md](PLAN-95.md)).
- **Judge numbers will not match ours exactly.** Each Harbor build and each `make reproduce` draws a fresh world secret. Compare means and CIs.
- **The reference is not an upper bound.** On v1.3 hard seed 10 the solver abstained (score 0) while Codex accused correctly ([docs/reports/gap.md](reports/gap.md)).
- **The verifier trusts the signed ledger.** It cannot recompute correctness without the world secret, which would reveal the judge worlds. A compromised sidecar could sign anything. The isolation checks cover that boundary ([docs/reports/CEO.md](reports/CEO.md), 18:40).
- **Published retired signing keys** catch edits that were not re-signed, but not a forger who re-signs with the public key ([docs/EXPLOITS.md](EXPLOITS.md), Harbor row).
- **The sidecar holds `GEMINI_API_KEY`** for the optional text provider. The agent container cannot read it ([docs/reports/CEO.md](reports/CEO.md), 18:40).
- **`check_leak_feed` spends the daily call budget.** It is not a free read ([docs/reports/CEO.md](reports/CEO.md), 18:40).
- **Shared-verifier mode is not for judging.** It is a fallback for old Harbor versions and refuses to build without an "unsafe" flag ([docs/EXPLOITS.md](EXPLOITS.md) #42).
- **EXPLOITS #32 is inconclusive.** A white-box Codex hunt was cut off by moderation. Its attack class is covered by the #24 and #27 tests ([docs/EXPLOITS.md](EXPLOITS.md)).
- **The committed Harbor `stop_early` jobs are the old day-1 accusation** (-1.0). The new `stop_early` is verified as exactly 0 in-process only ([harbor/README.md](../harbor/README.md)).
- **v1.5 (biased employees, rumours) was dropped.** Gemini scored 108% of the solver there, so it is a documented negative result, not a judged tier ([docs/reports/CEO.md](reports/CEO.md), 19:50).
- **Small model: no reward gain yet** (section 7).
- **Windows** needs WSL for `make`, and LF line endings for the Harbor build.

## 9. Team and roles

| Who | Role |
|---|---|
| Silas Wang | Environment and rules, team lead, pitch |
| Vaishnav | Anti-cheat battery (ported from his Poisoned Inbox design), reward integrity |
| Momin | Gemini fleet, RL and small-model training |
| Ivar | Browser game, video |

Most of the code was written by Claude Code sessions that the team directed and reviewed ([docs/TEAM.md](TEAM.md), [docs/agents/SESSIONS.md](agents/SESSIONS.md)).

## Open TODOs before 09:30

| Owner | What | Where it lands |
|---|---|---|
| Silas | Judge rehearsal: oracle, 3 OpenCode runs x 10 hard tasks, `do_nothing`, `stop_early`, on the tagged SHA, with timings | `results/harbor/rehearsal/` |
| Silas | Replay-verified replication of the OpenCode hard reruns | `docs/reports/gap.md` |
| Silas | gemini-3.5-flash v1.4 runs committed, or the claim dropped | `data/runs/committed/v1.4/opencode-gemini-3.5-flash/` |
| Silas | 02:00 gate outcome (solver_v2, expert tier) | section 3 |
| Silas | Failure analysis v1.4 (in progress) | `docs/reports/failure_analysis_v1.4.md` |
| Silas | Instruction audit (in progress) | `docs/DIFFICULTY.md` |
| Silas | Hint ablation result | section 4 |
| Silas | README first screen; fix "gap not established" in README and judge_table.md; one set of runtimes | `README.md`, `results/judge_table.md` |
| Silas | Fresh-clone log, tag `afterquery-final` | `results/fresh_clone/` |
| Silas | Demo script (in progress) | `docs/DEMO.md` |
| Silas | One project with two tracks, or two entries? Repo link to tag or branch? | Form fields |
| Vaishnav | 15-minute judge-protocol hunt + `make hunt` + full battery on the tag | `docs/reports/integrity.md` |
| Momin | v3 small-model held-out result with CIs | section 7 |
| Ivar | Video link; hosted game link | Form fields, section 6 |
| All four | Human playtests, 2 hard episodes each | section 4 |
