# Canary: AfterQuery "Break the Agent" submission

*Junction 2026. First draft by Vaishnav Rane (PR #25, Sat 14 Nov ~23:15 Helsinki, from `justSilas` at `09e7363`). Numbers refreshed Sun 15 Nov against `justSilas` at `58716742` (including annotated tag `afterquery-final` at `1bc3e281`). The team submits before 10:00 Sun.*

*Every number below names the committed file it comes from. `TODO(owner)` marks work that is not committed yet. Our Google DeepMind Gemini entry is a separate write-up: [docs/gemini/SUBMISSION.md](gemini/SUBMISSION.md).*

## Form fields (paste as is)

```text
Project name: Canary

Tagline (58 chars):
Catch the mole with canary traps before the value runs out

Description (594 chars):
Canary is an RL environment served over MCP. A company has one mole who leaks documents, and every leak costs value. The agent is head of security: it plants canary documents, reads a delayed, noisy leak feed and must accuse once. Correct = value left, wrong = -1, none = 0. The reference is a Bayesian solver that sees only what the agent sees. On the hard tier, gemini-4-carbon in OpenCode over MCP earns 72% of the solver's luck-adjusted score (95% CI 52-91%, n=30; raw 65%). Doing nothing scores exactly 0, and no attack we tried beats honest play. One keyless command reproduces our table.

Track: AfterQuery - Break the Agent (main track)
Side track: Google DeepMind - Best Use of Gemini API (own write-up: docs/gemini/SUBMISSION.md)

Repo: https://github.com/s1laswang/agent-arena/tree/justSilas

Video: TODO(Ivar): video link
```

- The 72% [52%, 91%] (luck-adjusted) and 65% [24%, 98%] (raw) come from [data/runs/committed/v1.4/paired_table_gemini.md](../data/runs/committed/v1.4/paired_table_gemini.md) and [docs/reports/gap.md](reports/gap.md). We lead with the luck-adjusted figure because it is the robust one: the raw paired difference CI touches zero (section 3).
- The character counts were measured on the text above. TODO(Silas): check the form's own limits for tagline and description (none is recorded in the repo).
- TODO(Silas): check whether the platform takes one project with two tracks or two separate entries. If two, drop the "Side track" line here.
- TODO(Silas): annotated tag `afterquery-final` points at `1bc3e281`; decide before submitting whether the form's repo link should point at `afterquery-final` instead of the moving `justSilas` branch.

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

You need `uv` and `make` (Linux or macOS; on Windows use WSL). No API key is needed for anything in this table.

| Command | What you should see | Time (source) |
|---|---|---|
| `make setup && make reproduce` | The score table on 40 judge seeds per tier, then the replayed committed agent runs, then the anti-cheat battery. `do_nothing` and `stop_early` (stops on day 1, no accusation) exactly 0 on every tier. `guess_day1` (random accusation on day 1) well below 0. Then `ANTI-CHEAT: every probe blocked, every replayable episode and Harbor trial consistent` (exit 1 if any cheat gets through), then a `HEADLINE` line that recomputes the 65% / 72% row from the committed episodes and diffs it with the committed paired table (exit 1 on any difference). Output goes to `results/latest/` (gitignored). | Clean-env Linux x86_64 fresh clone at `afterquery-final` (`1bc3e281`, [linux_x86_64_afterquery_final_1bc3e281.log.txt](../results/fresh_clone/linux_x86_64_afterquery_final_1bc3e281.log.txt)): clone 3 s, table 27 s (`REPRO_ANTICHEAT=0`), full 40-seed `make reproduce` 118 s (shared 24-CPU node under load). macOS arm64: 52 s in the timed fresh clone at `09e7363` ([results/fresh_clone/README.md](../results/fresh_clone/README.md)), 26.5 s idle at `edd4fe6d` (`total 24.4 s`), 2 min 23 s on a heavily loaded laptop ([docs/DEMO.md](DEMO.md)). The README says "about 1 min". |
| `make accept` | Runs setup, reproduce, checks each baseline against the README band, and starts the MCP server once. Prints an `ACCEPT TABLE` and `RESULT: PASS`. The Harbor row is `SKIP` by design (it needs Docker and a model key). | 142 s in the fresh clone at `09e7363` ([results/fresh_clone/README.md](../results/fresh_clone/README.md)); `PASS=20, FAIL=0` on `afterquery-final` (`1bc3e281`, [docs/reports/integrity.md](reports/integrity.md)) |
| `make anticheat-verify` | `0 differences`: the committed anti-cheat battery ([results/anticheat/exploits.md](../results/anticheat/exploits.md)) reruns exactly. | 2 min 08 s ([docs/DEMO.md](DEMO.md)); 99 rows, 0 differences on `afterquery-final` ([docs/reports/integrity.md](reports/integrity.md)) |
| `make hunt` | Your own exploit fuzzing on easy, medium, hard and hard_forge: best non-solver score 0.000, 0 violations ([docs/EXPLOITS.md](EXPLOITS.md) #49). | 4 min 57 s across all 4 modes x 4 tracks on `afterquery-final` ([docs/reports/integrity.md](reports/integrity.md)); "a few minutes" (README) |

**What our runs printed for hard.** The committed table ([results/judge_table.md](../results/judge_table.md), git `f9fb7a4adc01`, secret fingerprint `893b837616b9`, 24.4 s): solver +0.553 ± 0.093, `stop_early` and `do_nothing` +0.000, `guess_day1` -1.000 ± 0.000. Our run for this doc (fingerprint `705484a74e3a`, not committed; `results/latest/` is gitignored): solver +0.570 ± 0.118, `stop_early` and `do_nothing` +0.000, `guess_day1` -0.800 ± 0.188, then `HEADLINE ... +0.322 ± 0.199 vs reference solver +0.499 ... = 65% [24%, 98%] of the solver (luck-adjusted 72% [52%, 91%])`. Medium and easy solver rows in the committed table: +0.634 ± 0.086 and +0.785 ± 0.026.

Each run draws a fresh world secret, so your solver means will move between runs: [results/solver_range/](../results/solver_range/) holds the spread over 300 fresh secrets, and `make accept` checks against it. For bit-identical output: `CANARY_WORLD_SECRET=<any string> make reproduce`.

Note: in the judge table's "reported agent runs", `make reproduce` replays the OpenCode gemini-4-carbon hard episodes **pooled with the 2 extension seeds**, so that row reads +0.349 ± 0.190, n=32 (the pooled row in [paired_table_pooled0to59.md](../data/runs/committed/v1.4/opencode-gemini-4-carbon-ext/paired_table_pooled0to59.md)). The n=30 headline is the `HEADLINE` line.

**In the judges' harness (Harbor + OpenCode over MCP; needs Docker).** From [harbor/README.md](../harbor/README.md) and the README:

```bash
uv tool install harbor && uv run python harbor/build.py                      # 10 tasks: hard tier, judge seeds 900000-900009, fresh secret
harbor run -p harbor/dataset -a oracle -n 4                                  # reference solver
harbor run -p harbor/dataset -a oracle --ae ORACLE_POLICY=do_nothing -n 4    # expect exactly 0
harbor run -p harbor/dataset -a oracle --ae ORACLE_POLICY=stop_early -n 4    # expect exactly 0
harbor run -p harbor/dataset -a oracle --ae ORACLE_POLICY=cheat_probe -n 4   # ~150 cheat attempts, never accuses: expect exactly 0
GOOGLE_GENERATIVE_AI_API_KEY=<key> harbor run -p harbor/dataset -a opencode -m google/gemini-4-carbon \
    --api-key-name GOOGLE_GENERATIVE_AI_API_KEY -n 4                         # the frontier agent
```

What to expect, and where we saw it:
- **Oracle.** Each build draws a fresh world secret, so there is no fixed number. A 10-task hard oracle run should land in about +0.39 to +0.68 (90% of 200 simulated builds; mean +0.569, sd 0.094; README, [results/oracle_range_v1.4.md](../results/oracle_range_v1.4.md)).
- **do_nothing and stop_early.** Exactly 0 on all 10 tasks in our dry rehearsal ([results/harbor/rehearsal-dry/TABLE.md](../results/harbor/rehearsal-dry/TABLE.md)). The older Harbor `stop_early` jobs under `results/harbor/stop_early/` scored -1.0 because that build accused on day 1 (now `guess_day1`; [harbor/README.md](../harbor/README.md)).
- **cheat_probe.** 0.0 on 6 of 6 trials, 149 attempts each, 0 holes (`results/harbor/cheat-probe/`, [harbor/README.md](../harbor/README.md)).
- **The agent.** The key must reach OpenCode as `GOOGLE_GENERATIVE_AI_API_KEY` with `--api-key-name`. Otherwise every trial fails before the first model call and scores 0, which is an infrastructure failure, not a model result ([harbor/README.md](../harbor/README.md), "Pitfall").
- **Setup timeout.** Harbor's `opencode` agent installs Node and OpenCode in every container within 360 s. In our dry rehearsal every OpenCode trial hit that limit at `-n 5` until we added `--agent-setup-timeout-multiplier 4` ([results/harbor/rehearsal-dry/README.md](../results/harbor/rehearsal-dry/README.md); the README suggests 3).
- **Runtime.** Dry rehearsal on colima (4 CPU / 8 GB, loaded laptop): the 10-task OpenCode job at `-n 5` took 60 min (Harbor's cost estimate $9.86); oracle, do_nothing and stop_early at `-n 2` ran alongside in 16 min ([results/harbor/rehearsal-dry/README.md](../results/harbor/rehearsal-dry/README.md)).
- **Windows.** A checkout with `core.autocrlf=true` breaks the `.sh` files in the Linux containers. Convert `harbor/dataset*/` to LF first ([harbor/README.md](../harbor/README.md)).

## 3. Rubric: The gap (30)

**Our headline.** Rules v1.4, dev seeds 0-29 per tier, every episode replay-verified, each agent paired with the solver on the same seeds ([data/runs/committed/v1.4/paired_table_gemini.md](../data/runs/committed/v1.4/paired_table_gemini.md), [docs/reports/gap.md](reports/gap.md)):

| run (OpenCode = the judges' agent shape) | tier | n | luck-adjusted / solver [95% CI] | score / solver [95% CI] | paired diff ± 95% CI |
|---|---|---|---|---|---|
| **gemini-4-carbon, OpenCode over MCP** | hard | 30 | **72% [52%, 91%]** | **65% [24%, 98%]** | **-0.177 ± 0.194** |
| gemini-4-carbon, OpenCode over MCP | medium | 30 | 101% [85%, 119%] | 111% [99%, 127%] | +0.068 ± 0.080 |
| gemini-4-carbon, in-process (full history) | hard | 30 | 84% [65%, 106%] | 95% [62%, 140%] | -0.026 ± 0.184 |
| gemini-4-carbon, in-process | medium | 30 | 74% [52%, 99%] | 82% [56%, 108%] | -0.115 ± 0.170 |
| gemini-3.5-flash, OpenCode over MCP (API serves gemini-3.6-flash) | hard | 30 | 22% [-23%, 63%] | 75% [36%, 123%] | -0.126 ± 0.221 |

- On hard with OpenCode, gemini-4-carbon scores 0.322 ± 0.199 against the solver's 0.499 ± 0.119 on the same 30 seeds (same file).
- **Read the raw numbers carefully.** The ratio CI (paired bootstrap) excludes 100%, but the paired score difference, -0.177 ± 0.194, runs from -0.371 to +0.017: it touches zero. The luck-adjusted CI excludes parity with room to spare, so that is the figure we lead with.
- **Luck-adjusted** means: score each accusation by its expected value under the solver's posterior at that moment, P x V - (1 - P), and 0 if there is no accusation. It separates good decisions from lucky ones ([docs/reports/gap.md](reports/gap.md)).
- **Locked after the fact.** Seeds 0-29 were fixed as the primary set in `671ed96`, 28 s after the episodes were committed (`8fd4dec`): a lock against later reruns and cherry-picking, not a pre-registration. Later runs are reported separately, never swapped in ([docs/reports/gap.md](reports/gap.md)). The Harbor judge set (hard, seeds 900000-900009) was fixed in `docs/PLAN-95.md` before any frontier run on it ([harbor/README.md](../harbor/README.md)).
- **Infra failures.** Attempts that failed for infrastructure reasons (CLI errors, empty model replies, provider outages) were retried. Counting the empty-reply episodes as 0 instead gives 56% [19%, 87%] raw and 55% [34%, 77%] luck-adjusted on hard (the "alternative" row in the same table): the gap widens.
- **Pre-registered n=60 extension, stopped early.** Seeds 30-59 were pre-registered in `f9fb7a4a` and stopped at 03:22 to keep the shared Gemini quota for the judge rehearsal. Only 2 valid episodes finished (seeds 34 and 37, +0.790 and +0.700; 31 attempts hit the provider quota and were excluded). Pooled with seeds 0-29 (n=32): 68% [32%, 100%] raw, **75% [56%, 93%] luck-adjusted**, paired diff -0.165 ± 0.182 ([docs/reports/gap.md](reports/gap.md); [paired_table_pooled0to59.md](../data/runs/committed/v1.4/opencode-gemini-4-carbon-ext/paired_table_pooled0to59.md)). n=2 is not an estimate; the headline stays the n=30 row.

**Honest reading.** There is a gap on hard in the judges' agent shape, clearest in the luck-adjusted score (72% [52%, 91%], and 75% [56%, 93%] pooled with the extension). The raw score CI reaches parity once you look at the difference or the pooled set. The gap does not show in-process on hard (95%, luck-adjusted 84% [65%, 106%]) or in OpenCode on medium (111%). **All committed `v1.4` episodes are Gemini-family models** (gemini-4-carbon, gemini-3.5-flash, and the Gemini ladder incl. hosted Gemma 4); the committed GPT-5.5, Codex and Grok runs are on older rules (`v1.2` and `v1.3`) and count as history only, while a second-family `gpt-5.5` OpenCode `1.19.5` run on `v1.4` hard `seeds 0-29` at tag `afterquery-final` (`$200` cap, `08:15`/`08:45` Helsinki stop) was pre-registered in `cf394894` ([docs/reports/gap.md](reports/gap.md); see [docs/agents/PANEL-0500.md](agents/PANEL-0500.md)). We do not claim the gap holds for every harness or model.

**What we tried that did not widen the gap** (all reported, none shipped; [docs/reports/gap.md](reports/gap.md)):
- **v1.5 biased employees** (rumours, grudges): gemini-4-carbon went from 61% to 108% of the solver on hard seeds 0-9. Dropped at Gate B.
- **A stronger reference (solver_v2):** +0.012 ± 0.029 on fresh hard seeds 9000-9399 (n=400), below the +0.08 bar. The v1 solver is calibrated and near the information limit ([docs/reports/reference_optimality.md](reports/reference_optimality.md)).
- **An "expert" tier** (hard with fingerprint accuracy 0.70): scripted heuristics collapse (grok_tactics 0.36 → 0.01), but gemini-4-carbon stays at 84% [52%, 128%] luck-adjusted (n=13, OpenCode). Not shipped; code on branch `justSilas-expert`.

**What is not shown yet:**
- **Repeated runs through Harbor itself.** The 65% / 72% runs used the OpenCode CLI against our MCP server with `bash`/`python3` denied, not the Harbor container (which allows them; README). The real judge rehearsal (3 OpenCode runs x 10 hard tasks plus oracle, `do_nothing`, `stop_early`, on tagged `afterquery-final` at `1bc3e281`) is pre-registered in [results/harbor/rehearsal/README.md](../results/harbor/rehearsal/README.md) and **is not committed yet**: `results/harbor/rehearsal/` holds the protocol only until the run lands. TODO(Silas).
- **What has run is a dry rehearsal**, one OpenCode run on 10 hard judge tasks, on an untagged build (`be435fd5`): oracle +0.467 (9/10 correct), OpenCode gemini-4-carbon +0.398 (9/10 correct; 3 tasks are infra reruns †), i.e. 85% of the oracle [11%, 355%], n=10 ([results/harbor/rehearsal-dry/TABLE.md](../results/harbor/rehearsal-dry/TABLE.md)). Its own README says it "says nothing about a gap. Treat it as a harness check."
- **Earlier Harbor demo** (6 tasks, medium and hard, seeds 900000-900002, earlier build): Gemini 0.503 vs oracle 0.757, lower on all 6 ([harbor/README.md](../harbor/README.md)). Small; not counted as the gap.
- **Causal hint test.** Pre-registered in [docs/reports/gap.md](reports/gap.md) (`fd8c1cb0`, one added line restating the instruction's own rules, OpenCode, hard seeds 0-29, stop 05:40). No result is committed yet. TODO(Silas): report it either way, with n.

**History.** On v1.3, Codex gpt-5.5 over MCP reached 97% [89%, 107%] of the solver on hard (seeds 0-9). That is why v1.4 made hard longer: 40 staff, 21 days, 2 canaries a day. It is a pure parameter change with the same tools and the same reward ([docs/reports/gap.md](reports/gap.md), [docs/HISTORY.md](HISTORY.md)).

## 4. Rubric: Meaningful difficulty (30)

**The decisions that matter.** Which groups get which canary variant. How to read leaks that arrive 2-3 days late. When to stop and accuse, when to keep going, and when to abstain.

**The skill ladder shows which decisions decide the score.** Each rung removes one part of the reference solver. Fresh dev seeds 7000-7399, n=400 per tier, paired 95% CIs ([results/skill_ladder_v1.4.md](../results/skill_ladder_v1.4.md)):

| removed from the solver | hard: change in score | medium: change in score |
|---|---|---|
| the expected-value accusation rule (accuse the top suspect on the last day) | -0.371 ± 0.032 | -0.222 ± 0.028 |
| the expected-value accusation rule (accuse at P >= 0.5) | -0.151 ± 0.057 | -0.242 ± 0.060 |
| the leak-delay model | -0.251 ± 0.037 | -0.457 ± 0.034 |
| careful-mole term, decoy handling, framing, second canary | no significant cost | no significant cost |

So two skills decide the game: committing at the right moment, and reasoning about late leaks.

**What Gemini does wrong on v1.4 hard** (OpenCode, n=30, same seeds as the solver; [docs/reports/failure_analysis_v1.4.md](reports/failure_analysis_v1.4.md), every number computed by `scripts/failure_analysis_v14.py` and pinned by `tests/test_failure_analysis_v14.py`):
- **It under-explores.** 8.5 canaries before the accusation vs the solver's 14.1, first canary on day 3.0 vs 1.0, and 68 low-value interviews per episode.
- **It commits on thin evidence.** 9 of 29 accusations were made while two or more people were still consistent with every leak (solver: 3 of 30). That is the largest single cost, 3.39 V of expected value, and includes 3 negative-EV accusations near the horizon.
- **It accuses later:** day 13.2 vs 10.6. But the V drained by waiting (+1.75 V over 30 seeds) is almost exactly repaid by the canaries it never bought (-1.69 V).
- **Accuracy 0.83 vs 0.97;** the solver's posterior on the person Gemini accuses averages 0.88 vs 0.97 for the solver's own picks ([paired_table_gemini.md](../data/runs/committed/v1.4/paired_table_gemini.md)).
- **The four wrong accusations:** two are disclosed fingerprint noise at P ≥ 0.95 (luck), one a P 0.80 bet on an unresolved pair that the solver also lost on that seed, one a negative-EV gamble. That is why we lead with the luck-adjusted ratio.
- Mean regret 0.171 V per episode; 2 accusations tagged `premature_accusation` cost 0.804 V together ([results/regret_opencode-gemini-4-carbon-v1.4.md](../results/regret_opencode-gemini-4-carbon-v1.4.md)).

**Earlier tiers showed the same root skill.** On v1.3, premature accusation was 97-99% of the tagged value lost. Codex accused at P = 0.18 and P = 0.33 when abstaining (0) was worth more, and no frontier episode ever abstained ([docs/reports/gap.md](reports/gap.md)).

**The information and tools to do better are there:**
- **Instruction audit** ([docs/DIFFICULTY.md](DIFFICULTY.md), PLAN-95 B4): by hand, mechanically and with one gemini-4-carbon pass over the exact text the agent receives. Verdict: no withheld rule, feasible in-game timing, 39/39 tool smoke calls ok ([results/audit/instruction_checks.md](../results/audit/instruction_checks.md)). On 15 Nov (`1bc3e281`, tag `afterquery-final`), after the committed frontier runs, two changes were made and disclosed (README, [docs/DIFFICULTY.md](DIFFICULTY.md)): `W1` careful-mole wording was fixed in the medium and hard instructions (0 W1 losses across the 30 hard runs in `scripts/careful_mole_check.py`), and tool errors gained public-only `data.detail` (28 of 3,841 calls = 0.7% in the 30 headline hard episodes hit `invalid arguments`; error string unchanged so all 1,021/1,031 committed episodes and 51,814 tool results replay with 0 differences). `W2-W4` (default-rule mole wording on base tiers, scattered within-day event order, and the non-binding `access_constraints` knob on hard) remain disclosed in [docs/DIFFICULTY.md](DIFFICULTY.md). The one wall-clock risk (Harbor's 3,600 s agent timeout) was fixed: 10,800 s (`512836b9`).
- The solver uses only the agent's own observations and the published rules ([docs/reports/gap.md](reports/gap.md), "Fairness"). Every rate and rule is in the MCP instructions; an external Grok agent computed the break-even rule from them and abstained at P ≈ 0.53 (same file).
- A scripted replay of a strong agent's tactics (`grok_tactics`) still trails the solver on hard by 0.195 ± 0.033, n=800 fresh seeds ([results/fresh_table_v1.4.md](../results/fresh_table_v1.4.md)). The gap is about decisions, not access.
- Each harder version changed the information or mechanics in the open instructions, never a hidden trick. The solver stayed between 0.58 and 0.72 throughout ([docs/reports/gap.md](reports/gap.md), "Kill-switch history").

**Not done yet:**
- TODO(Silas): the causal hint test result (section 3).
- TODO(all four): human playtests, 2 hard dev-seed episodes each, scores logged ([docs/PLAN-95.md](PLAN-95.md), B3). None is committed.

## 5. Rubric: Reward integrity (25)

Full list of every attack and its test: [docs/EXPLOITS.md](EXPLOITS.md) (52 numbered rows, #0 to #51, plus judge-hunt rows J1-J15).

**Doing nothing or stopping early earns 0.** On 40 judge seeds per tier ([results/judge_table.md](../results/judge_table.md)):

| policy | medium | hard | easy |
|---|---|---|---|
| solver (reference) | +0.634 ± 0.086 | +0.553 ± 0.093 | +0.785 ± 0.026 |
| do_nothing | +0.000 | +0.000 | +0.000 |
| stop_early (stop on day 1, no accusation) | +0.000 | +0.000 | +0.000 |
| guess_day1 (random accusation on day 1) | -0.950 ± 0.098 | -1.000 ± 0.000 | -0.750 ± 0.208 |

**Anti-cheat battery** (runs inside `make reproduce`; design: Vaishnav, ported from his Poisoned Inbox project). Committed run: 40 judge seeds x easy, medium, hard under a public test secret ([results/anticheat/exploits.md](../results/anticheat/exploits.md)):
- 14 attack probes and 1 swarm-found probe per tier, from accuse-everyone (in sequence and in parallel threads) to garbage arguments on every tool. All blocked: every attack mean is at or below 0 and below the solver.
- The **effort ladder** stops the solver at 25/50/75/90% of its calls and accuses its best guess. Its best cut is hard 90% at +0.051 ± 0.244, vs the full solver's +0.545 ± 0.098. Stopping early and guessing never pays.
- **Replay.** 1,021 of 1,031 committed episodes re-played on a fresh environment, 51,814 recorded tool results compared step by step, 0 differ. The other 10 are on secret-keyed judge or held-out seeds.
- **Harbor consistency.** 80 of 80 committed Harbor trials (incl. the dry rehearsal) and 18 of 18 job summaries agree with each other.

**In Harbor** ([harbor/README.md](../harbor/README.md)):
- **Isolation.** The game server runs in a separate sidecar container, with no shared PID namespace or filesystem. `check_isolation.sh` runs inside the agent container: `ISOLATION OK: 11 checks passed, 0 findings`.
- **cheat_probe** never accuses and tries 149 tricks (guessed ledger tokens, secret files, `/proc/*/environ`, planted reward files, made-up MCP tools, malformed accusations). Reward 0.0 on 6 of 6 trials, 0 holes (`results/harbor/cheat-probe/`). The accuse-everyone `cheat` scores -1.0 on the same build (`results/harbor/signed-cheat/`).
- **Signed ledger.** The server HMAC-signs the ledger with a per-build key that never enters the agent container. The verifier fails closed. In the negative control, a forged `score = 1.0` was graded 0 (`results/harbor_negative/c1-tamper/`).

**Gemini attackers** (owned by the Gemini track, [docs/gemini/SUBMISSION.md](gemini/SUBMISSION.md)):
- 100 Gemini attackers over 4 waves (75 whitebox that read the whole repo, 16 blackbox, 9 re-runs through the real MCP server): 0 verified exploits, 0 invariant violations, 4,325 tool calls ([results/gemini/swarm.md](../results/gemini/swarm.md)). The one in-run score candidate (`w2b-008`) was refuted at n = 40 judge + 100 dev seeds per tier ([docs/EXPLOITS.md](EXPLOITS.md) #50) and now runs in the battery as `swarm_w2b008`.
- Positive control: with a known exploit reopened (EXPLOITS #23, public dev seeds), 4 of 4 attackers found it and the pipeline flagged it ([results/gemini/swarm_control.md](../results/gemini/swarm_control.md)). So the detector does catch real exploits.

**Momin's cheat corpus.** 129 rejected calls, injected into the solver: 774 runs, 0 calls accepted, 0 score changes; re-run with easy added, 1,161 runs, 0 accepted, 0 changed ([docs/EXPLOITS.md](EXPLOITS.md), [results/anticheat/corpus_eval.txt](../results/anticheat/corpus_eval.txt)).

**Exploits we found and closed** ([docs/EXPLOITS.md](EXPLOITS.md)):

| # | Exploit | Before the fix | Fix |
|---|---|---|---|
| 1 | Stop early and guess, when a wrong accusation cost 0 | 0.10 on medium: a free lottery ticket | wrong accusation = -1 |
| 23, 24, 28 | Rebuild the world from public code and read the mole | 1.0 | judge worlds keyed by a secret that fails closed; the server refuses dev seeds |
| 27 | Read the server's environment from the same user | 1.0 | secrets only in 0600 files; in Harbor, a separate sidecar container |
| 42 | Plant a fake ledger in shared-verifier mode (not the default) | 1.0 | grade only from the token-protected ledger; shared mode refuses to build without an "unsafe" flag |

**Doing the task well is the best way to score.** The solver is above every scripted baseline and every attack on every tier (tables above). Adding an extra step before its own accusation never beats it (the "plus probes" in [results/anticheat/exploits.md](../results/anticheat/exploits.md)).

**Final judge-protocol hunt on `afterquery-final` (`1bc3e281`, committed in `58716742`).** Run keyless on the tagged code ([docs/reports/integrity.md](reports/integrity.md), [results/anticheat/judge_hunt.md](../results/anticheat/judge_hunt.md)): `scripts/judge_hunt.py` 12/12 held on the live MCP server (52 s); `make hunt` best non-solver 0.000 and 0 violations across all 4 modes x 4 tracks (4 min 57 s); full 40-seed `make reproduce` exit 0 (HEADLINE 65% [24%, 98%] unchanged); `make anticheat-verify` 99 rows, 0 differences; `make test` 1,057 passed; `make accept` PASS=20, FAIL=0; and Gemini phase-1 red-team logged 424 attacks on `469338f6` (0 exploits).

## 6. Rubric: Craft (15)

- **One command.** `make setup && make reproduce`, no keys, no `.env` (README). `make accept` adds the checks. CI runs `make test` and the fast `make reproduce` (5 seeds per tier) on every push to `justSilas` and on every pull request (`.github/workflows/ci.yml`).
- **Rules that fit the setting.** The canary trap is a real technique. Tom Clancy named it in *Patriot Games* (1987), and Peter Wright's *Spycatcher* describes it as MI5's "barium meal test" (README, "Real-world grounding"). Late leaks, a mole who adapts and frames others, and value that bleeds while you wait are what make the real problem hard.
- **Everything is replayable.** Committed episodes re-play step by step (section 5). Judge worlds use a secret per build, so nobody, us included, has seen the worlds a judge's build serves ([harbor/README.md](../harbor/README.md)).
- **Tests.** On `afterquery-final` (`1bc3e281`), `make test` passed **1,057** tests ([docs/reports/integrity.md](reports/integrity.md), `58716742`), and the clean-env Linux x86_64 fresh clone ([results/fresh_clone/linux_x86_64_afterquery_final_1bc3e281.log.txt](../results/fresh_clone/linux_x86_64_afterquery_final_1bc3e281.log.txt), `eadf970a`) ran clone in 3 s, table in 27 s, full reproduce in 118 s, `scripts/audit_submission.py` in 4 s (3 PASS, 1 WARN, 0 FAIL), and `test_core` with **100 passed in 175 s** (alongside 967 passed, 7 skipped in the earlier macOS fresh clone at `09e7363`, [results/fresh_clone/README.md](../results/fresh_clone/README.md), and 1,055 passed, 7 skipped in 195 s at `edd4fe6d`).
- **Play it yourself.** `make game-serve` builds a browser game on the real `canary` package (Pyodide) at http://localhost:8000 (`Makefile`). TODO(Ivar): hosted game link. The GitHub Pages workflow is manual on purpose (`workflow_dispatch` in `.github/workflows/pages.yml`) and needs Silas's go-ahead.

**Completed since `edd4fe6d`:**
- **Fresh-clone log on `afterquery-final` (`1bc3e281`):** committed in [results/fresh_clone/linux_x86_64_afterquery_final_1bc3e281.log.txt](../results/fresh_clone/linux_x86_64_afterquery_final_1bc3e281.log.txt) (`eadf970a`, [results/fresh_clone/README.md](../results/fresh_clone/README.md)) alongside `09e7363` (clone 3 s, table 27 s, full reproduce 118 s, `scripts/audit_submission.py` 4 s 0 FAIL, `test_core` 100 passed in 175 s).
- **Annotated tag `afterquery-final`:** created at `1bc3e281` (Panel Fix D).
- **Demo tiebreak slot resolved:** the 8:00-9:00 tiebreak section in [docs/DEMO.md](DEMO.md) is synced with section 7 and WS4 (**bar not met**, no held-out gain over base).

## 7. Tiebreak: does a small model improve after training on Canary?

**Short answer: bar not met (no held-out gain over the base model).** RL recovered most of the supervised model's loss, but every trained checkpoint still scores below 0 on held-out worlds, whereas the untrained base model cannot play the protocol (3% valid tool calls), abstains every time, and scores 0 (`66a26f5c`, README). We do not claim a tiebreak gain.

Held-out Canary episodes, the model playing alone, Qwen2.5-1.5B-Instruct with LoRA ([docs/reports/fr8.md](reports/fr8.md), "04:45 WS4 small-model tiebreaker readout: bar NOT met", `266bca3b`; full table in [fr8/analysis/out/ws4_table_v3.md](../fr8/analysis/out/ws4_table_v3.md)):

| model | n held-out episodes | score ± 95% CI |
|---|---|---|
| base (untrained) | 36 | 0.000 ± 0.000 (3% valid tool calls; abstains every time) |
| v1: SFT on solver episodes (J4, V100, 4k) | 12 | -0.250 ± 0.256 |
| v2: SFT, dense 4k windows (V100) | 172 | -0.457 ± 0.086 (accuses on 55% of episodes, rarely right) |
| v3-4k s0: GRPO from v2 on environment reward (Verda H100, 609 steps) | 180 | -0.147 ± 0.063 (+0.310 ± 0.107 two-sample vs v2; 100% valid calls) |
| v3-8k s1: GRPO, 8k context (A100-80 spot, 371 steps) | 90 | -0.777 ± 0.118 (accuses on 94% of episodes) |
| v3-8k s2: GRPO, 8k context (Verda H100 spot, 693 steps) | 90 | -0.050 ± 0.049 (abstains on 93% of episodes) |

- **Verdict: bar not met.** None of the trained runs meets the tiebreak bar (held-out mean > 0 with 95% CI excluding 0), including the partial FR8 V100 replicate v3-4k s1 (-0.240 ± 0.171, n=25).
- **What improved:** v3-4k s0 vs v2 is +0.310 ± 0.107 (two-sample), fixing v2's reckless accusations (accuse rate 0.55 → 0.21, valid calls 0.92 → 1.00; J4 v1 valid calls 0.08 → 0.99) and raising forced-accusation mole identification on training states from 0.19 → 0.89 ([docs/reports/fr8.md](reports/fr8.md)). It learned the protocol and how to read evidence in view, not how to gather evidence in its own episodes.
- **Two-sample deltas:** held-out worlds are secret-keyed and these evals did not share `CANARY_WORLD_SECRET`, so each run drew distinct worlds and all deltas in [fr8/analysis/out/ws4_table_v3.md](../fr8/analysis/out/ws4_table_v3.md) are two-sample rather than seed-paired (FR8's 04:00 correction).
- **Pending:** an on-policy DAgger round and remaining 8k seeds (`s0`, `s3`) were still pending after the 04:45 readout. TODO(Momin): add any held-out result that lands before submission, either way, from a committed file.

## 8. Known limits

- **The gap is narrow in scope.** It shows on hard, with OpenCode over MCP, for gemini-4-carbon. The raw paired difference CI touches zero (-0.177 ± 0.194); the luck-adjusted ratio (72% [52%, 91%]) is the robust figure. It does not show in-process or on medium.
- **Committed `v1.4` episodes are Gemini-family only.** Committed GPT-5.5, Codex and Grok runs are on older rules (`v1.2` and `v1.3`) and count as history only; a second-family `gpt-5.5` OpenCode `1.19.5` run on `v1.4` hard `seeds 0-29` (`$200` cap, `08:15`/`08:45` stop, tag `afterquery-final`) was pre-registered in `cf394894` ([docs/reports/gap.md](reports/gap.md); see [docs/agents/PANEL-0500.md](agents/PANEL-0500.md)), with no `v1.4` episodes committed yet.
- **Harness difference.** The committed headline runs used OpenCode with only the 13 MCP tools (`bash`/`python3` denied). The Harbor agent container allows `bash` and `python3`, which cannot reach the world, the seed or the ledger (isolation 11/11), so in a Harbor rerun the agent may also compute with Python (README, "Harness difference, disclosed").
- **No live 3x10 Harbor rehearsal committed yet** (section 3). The dry rehearsal is one OpenCode run, n=10. The judges' 3 runs x 10 hard tasks could land near parity by luck: one lucky guess scores the same as a correct inference, and one wrong accusation (-1) moves a 10-task mean by more than 0.1 (README).
- **The n=60 extension stopped at n=2** because of the shared Gemini quota (section 3).
- **Judge numbers will not match ours exactly.** Each Harbor build and each `make reproduce` draws a fresh world secret. Compare means and CIs.
- **The reference is not an upper bound.** On v1.3 hard seed 10 the solver abstained (score 0) while Codex accused correctly ([docs/reports/gap.md](reports/gap.md)). A stronger solver_v2 gained only +0.012 ± 0.029 ([docs/reports/reference_optimality.md](reports/reference_optimality.md)).
- **Post-run instruction and error-detail update (`1bc3e281`, 15 Nov).** On 15 Nov (`1bc3e281`, tag `afterquery-final`), `W1` careful-mole wording was fixed in the medium and hard instructions (0 W1 losses across the 30 hard runs in `scripts/careful_mole_check.py`) and tool errors gained public-only `data.detail` (28 of 3,841 calls = 0.7%; error string unchanged so all 1,021/1,031 committed episodes and 51,814 tool results replay with 0 differences). Committed `v1.4` Gemini episodes saw the pre-fix text; `W2-W4` remain disclosed ([docs/DIFFICULTY.md](DIFFICULTY.md), README).
- **The verifier trusts the signed ledger.** It cannot recompute correctness without the world secret, which would reveal the judge worlds. A compromised sidecar could sign anything. The isolation checks cover that boundary ([docs/EXPLOITS.md](EXPLOITS.md) #45).
- **Published retired signing keys** catch edits that were not re-signed, but not a forger who re-signs with the public key ([docs/EXPLOITS.md](EXPLOITS.md)).
- **The sidecar holds `GEMINI_API_KEY`** for the optional text provider. The agent container cannot read it ([docs/EXPLOITS.md](EXPLOITS.md) #47).
- **`check_leak_feed` spends the daily call budget.** It is not a free read ([docs/EXPLOITS.md](EXPLOITS.md) #46).
- **Shared-verifier mode is not for judging.** It is a fallback for old Harbor versions and refuses to build without an "unsafe" flag ([docs/EXPLOITS.md](EXPLOITS.md) #42).
- **EXPLOITS #32 is inconclusive.** A white-box Codex hunt was cut off by moderation. Its attack class is covered by the #24 and #27 tests ([docs/EXPLOITS.md](EXPLOITS.md)).
- **The committed Harbor `stop_early` jobs under `results/harbor/stop_early/` are the old day-1 accusation** (-1.0). The new `stop_early` scored exactly 0 on 10 of 10 tasks in the dry rehearsal ([results/harbor/rehearsal-dry/TABLE.md](../results/harbor/rehearsal-dry/TABLE.md)).
- **Small model: no held-out reward gain over base** (section 7).
- **Windows** needs WSL for `make`, and LF line endings for the Harbor build.

## 9. Team and roles

| Who | Role |
|---|---|
| Silas Wang | Environment and rules, team lead, pitch |
| Vaishnav Rane | Anti-cheat battery (ported from his Poisoned Inbox design), reward integrity, this submission draft |
| Momin | Gemini fleet, cheat corpus, RL and small-model training |
| Ivar | Browser game, video, failure research |

Most of the code was written by Claude Code sessions that the team directed and reviewed ([docs/TEAM.md](TEAM.md), [docs/agents/SESSIONS.md](agents/SESSIONS.md)).

## Open TODOs before submitting (deadline 10:00)

| Owner | What | Where it lands |
|---|---|---|
| Silas | Real judge rehearsal on `afterquery-final` (`1bc3e281`, tagged; oracle, 3 OpenCode runs x 10 hard tasks, `do_nothing`, `stop_early`), with timings | `results/harbor/rehearsal/` |
| Silas | Causal hint test result (pre-registered in `fd8c1cb0`; report either way with n) | `docs/reports/gap.md`, sections 3-4 |
| Silas | One project with two tracks, or two entries? Repo link to tag `afterquery-final` (`1bc3e281`) or branch `justSilas`? Form character limits? | Form fields |
| Momin | Any held-out DAgger round (or remaining v3-8k seeds `s0`/`s3`) that lands before submission, committed, either way | section 7 |
| Ivar | Video link; hosted game link | Form fields, section 6 |
| All four | Human playtests, 2 hard episodes each | section 4 |

Resolved since `edd4fe6d`: annotated tag `afterquery-final` at `1bc3e281` (Panel Fix D), clean-env Linux x86_64 fresh-clone log on `1bc3e281` in [results/fresh_clone/linux_x86_64_afterquery_final_1bc3e281.log.txt](../results/fresh_clone/linux_x86_64_afterquery_final_1bc3e281.log.txt) (`eadf970a`), final judge-protocol hunt + `make hunt` + full battery on `1bc3e281` in [docs/reports/integrity.md](reports/integrity.md) (`58716742`), WS4 `base` `n=36` + `v3-8k s2` `n=90` readout in [fr8/analysis/out/ws4_table_v3.md](../fr8/analysis/out/ws4_table_v3.md) (`266bca3b` / `66a26f5c`), and [docs/DEMO.md](DEMO.md) tiebreak sync.
