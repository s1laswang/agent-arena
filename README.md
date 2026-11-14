# Canary: catch the mole

**AfterQuery entry — Canary** (clone branch `justSilas`). This is not The Sleeper (AfterQuery entry on branch `momin`) and not the Google DeepMind Gemini-track write-up (branch `gemini-track`). Clone only this branch, then run one command. See “Packaging” below.

[![CI](https://github.com/s1laswang/agent-arena/actions/workflows/ci.yml/badge.svg?branch=justSilas)](https://github.com/s1laswang/agent-arena/actions/workflows/ci.yml)

An RL environment for AfterQuery's **Break the Agent** (Junction 2026).

- A simulated company has exactly one **mole** leaking sensitive documents to a rival. Every leak costs company value V, which starts at 1.0.
- The agent is the **head of security**. It can read access logs and messages, interview staff and restrict access.
- Its sharpest tool is the **canary trap**: send different variants of a document to different groups, then watch the **leak feed** to see which variant surfaces.
- It must **accuse exactly once**. A correct accusation scores the value that is left, so waiting for certainty also costs.
- The reference run is a tuned **Bayesian canary-trap solver** that uses the same public tools. Every rule an agent needs is written down; the benchmark is how close a frontier agent gets to the solver.

## Prerequisites

A Linux or macOS machine (x86_64 or arm64). Nothing below is installed by `make setup` except the Python 3.12 virtualenv.

| Need | Required for | Install (official sources, not guessed) |
|---|---|---|
| **GNU make** | every `make …` target | Debian/Ubuntu: `sudo apt-get install make`. macOS: `xcode-select --install`. |
| **python3** | `scripts/mcp_port.sh`, some snippets | 3.11+; `make setup` then uses uv to install CPython 3.12. |
| **uv** | `make setup` / `make reproduce` | `curl -LsSf https://astral.sh/uv/install.sh | sh` then open a new shell. Docs: https://docs.astral.sh/uv/ |
| **Docker Engine** + compose plugin | Harbor judge path only | Ubuntu: follow https://docs.docker.com/engine/install/ubuntu/ (`sudo apt install docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin`). macOS: Docker Desktop. Convenience script (dev machines): `curl -fsSL https://get.docker.com -o get-docker.sh && sudo sh get-docker.sh`. Verify: `docker run hello-world`. |
| **Harbor CLI** | Harbor judge path only | Official: `uv tool install harbor` or `pip install harbor` (PyPI package `harbor`, Python ≥ 3.12). Docs: https://docs.harborframework.com/getting-started/installation . Harbor uses Docker as the default sandbox. Tested with Harbor 0.26.0 in `harbor/README.md`. |
| **OpenCode CLI** | Harbor / local MCP agent path | Official: `curl -fsSL https://opencode.ai/v2/install | bash` or `npm install -g @opencode/cli` (https://opencode.ai/). Do **not** install the npm package `opencode-ai`; the official package is `@opencode/cli`. |

**Keys.** No API key is required for `make setup`, `make reproduce`, `make accept`, or a local `make mcp` smoke test. `OPENAI_API_KEY` or `GEMINI_API_KEY` is required only if you run a live frontier agent (`opencode run -m …`, `harbor run -a opencode -m …`, `make gemini-check`). A key in the environment is never enough by itself to change `make reproduce` numbers.

**Expected runtimes** (measured on a clean box, 14 Nov 2026): `make setup` (cold, including CPython 3.12) about 3–15 s; `make reproduce` about 25–35 s (a published “about 10 s” figure is optimistic for the full 40-seed × 3-tier table; `REPRO_FAST=1 make reproduce` is the ~5-seed-per-tier check). `make accept` is setup + reproduce + a short MCP smoke, about 40–60 s. A full Harbor OpenCode run depends on the model and is not part of the keyless accept.

## One command

```bash
make setup && make reproduce
```

To also assert the numbers and smoke-test MCP:

```bash
make accept
```

You need GNU make and [uv](https://docs.astral.sh/uv/) first (see Prerequisites). `make setup` then installs Python 3.12 and every dependency. You need no API keys and no `.env` for this keyless table.

`make reproduce` plays the reference solver and five baselines on the 40 frozen judge seeds of each tier. It replays any committed frontier-agent episodes from `data/runs/committed/`, prints the table, and writes `judge_table.md`, `judge_episodes.jsonl` and `gap_chart.png` to `results/latest/`. That folder is gitignored, so your clone stays clean and our committed copies in `results/` are never overwritten; compare the two directly.

**Expected numbers on the frozen tiers v1.4.** We ran keyless `make reproduce` 30 times on the 40 judge seeds per tier (commit 5b56b60), each run with a fresh secret. Each cell is the mean of the 30 run means, with the lowest and highest run mean in brackets. The spread log from that run is not committed in this tree, so the brackets are that commit's min and max, not a new measurement of this commit. A single run prints its own 95% CI, about ±0.03–0.10 for the solver and ±0.2 for the heuristic. To rebuild this table: `uv run python scripts/repro_spread.py 30` (about 2 minutes). v1.4 changed only **hard**; easy and medium are the same as in v1.3.

| agent | medium (headline) | hard (headline) | easy (sanity tier only) |
|---|---:|---:|---:|
| **solver** (reference) | **+0.64** [+0.55, +0.72] | **+0.56** [+0.36, +0.62] | +0.77 [+0.71, +0.80] |
| heuristic (canary bisection, no Bayes) | −0.05 [−0.40, +0.19] | −0.03 [−0.23, +0.17] | +0.66 [+0.46, +0.73] |
| logs_only (best no-canary log reader) | −0.98 [−1.00, −0.87] | −0.98 [−1.00, −0.91] | −0.52 [−0.64, −0.36] |
| random | −0.67 [−0.72, −0.49] | −0.79 [−0.82, −0.68] | −0.70 [−0.80, −0.58] |
| guess_day1 (random accusation, day 1) | −0.89 [−1.00, −0.75] | −0.95 [−1.00, −0.85] | −0.83 [−1.00, −0.65] |
| stop_early (stops on day 1, no accusation) | 0.00 (exact) | 0.00 (exact) | 0.00 (exact) |
| do_nothing | 0.00 (exact) | 0.00 (exact) | 0.00 (exact) |

**v1.4 frontier gap: not established.** `data/runs/committed/v1.4/` holds reference baselines only, so this band table has no frontier row. An in-process bake-off on rules v1.4, paired seeds, n=10 per tier (21:26) has gemini-4-carbon matching or beating the solver. Medium: solver +0.734±0.050, carbon +0.680±0.085. Hard: solver +0.433±0.324, carbon +0.509±0.136. Smaller Gemini models sat below the solver. That is parity, not a gap. The v1.3 rows below are an earlier hard tier (30 staff, 14 days) and are not a v1.4 gap.

**Tiebreaker.** The notes gain on the flash-lite probe is the generic hint, not a learned policy: notes minus hint is −0.039±0.204. Train and eval seeds are disjoint and the weights were not updated. A change inside that CI is not evidence the model learned the task.

`do_nothing` is exactly 0: the episode ends with no accusation. `stop_early` looks around on day 1 and stops without accusing, so its score is exactly 0 as well (an unaccused episode scores 0). `guess_day1` is that day-1 uniform accusation. A wrong accusation scores −1 (`wrong_accusation_score`); we are not changing that penalty. The `guess_day1` brackets in the band table are the 30-run spread measured at commit 5b56b60 under the old name `stop_early` (same script). On the regenerated judge table ([`results/judge_table.md`](results/judge_table.md), fingerprint `6a38958f8096`) `stop_early` is +0.000 ± 0.000 on medium, hard, and easy, and `guess_day1` is −0.900 ± 0.137 / −0.950 ± 0.098 / −0.950 ± 0.098. Replayed history rows still named `stop_early` are the old day-1 accusation.

**v1.3 history: frontier agents.** These runs used the v1.3 hard tier (30 staff, 14 days, 1 canary a day), so they are not comparable to v1.4 hard. Medium is unchanged. They were played on v1.3 **dev** seeds 0–10, not judge seeds, and paired with the solver on the same seeds. Each cell is mean ± 95% CI = % of the solver [bootstrap 95% CI]. See the [gap report](docs/reports/gap.md).

| v1.3 frontier run | medium | hard (v1.3) |
|---|---:|---:|
| **Codex gpt-5.5 over MCP** (judges' harness), n=11 per tier, commit a978aa1+ | +0.40 ± 0.42 = **55%** [−8%, 104%] (50% on the planned seeds 0–9) | +0.66 ± 0.04 = **106%** [91%, 136%] (**97%** [89%, 107%] on seeds 0–9) |
| in-process gpt-5.5, fixed loop (full history, Responses API + reasoning replay), n=9 / 8 | +0.67 ± 0.10 = 92% [80%, 106%] | +0.26 ± 0.54 = 38% [−51%, 99%] |

- **Committed run.** [`results/judge_table.md`](results/judge_table.md) and [`results/gap_chart.png`](results/gap_chart.png) come from one keyless run on v1.4 (secret fingerprint `6a38958f8096`), written with `make reproduce-update`. The committed v1.3 and v1.2 frontier runs appear there as labelled history. In replayed runs, episodes lost to infrastructure (provider quota, a crashed MCP server) are left out of the mean and counted in a separate `invalid` column with their reasons, and each seed counts once: if two runs cover the same seed, only the newest counts.
  - Solver: medium **+0.679 ± 0.048** (97% correct), hard **+0.547 ± 0.143** (93% correct), easy **+0.808 ± 0.027** (100% correct).
  - Heuristic: medium +0.043 ± 0.241, hard −0.044 ± 0.189, easy +0.652 ± 0.090.
  - `stop_early`: +0.000 ± 0.000 on medium, hard, and easy. `guess_day1`: medium −0.900 ± 0.137, hard −0.950 ± 0.098, easy −0.950 ± 0.098.
- **Fresh seeds.** On seeds never used for tuning, the scripted baselines stay below the solver. That is not a frontier gap. The comparison is paired (same seed, agent − solver):
  - **v1.4:** [`results/fresh_table_v1.4.md`](results/fresh_table_v1.4.md) covers 800 confirmation seeds per tier (5000–5799) and every baseline.
    - Solver easy/medium/hard **+0.779 / +0.634 / +0.556**, accuracy 99.6 / 89.0 / 94.9%.
    - The strongest scripted baseline is `grok_tactics`, a scripted replay of a strong Grok agent's tactics: the agent's runs and transcripts are in [docs/reports/grok-agent.md](docs/reports/grok-agent.md), and the replay is `GrokTactics` in [`canary/baselines.py`](canary/baselines.py). It trails the solver by **0.089 ± 0.016 / 0.176 ± 0.025 / 0.195 ± 0.033**.
    - The heuristic trails by 0.131 / 0.641 / 0.534.
    - `stop_early` is 0.000 on every tier (no accusation). `guess_day1` is −0.830 ± 0.039 / −0.902 ± 0.030 / −0.945 ± 0.023.
  - **v1.3 history**, with hard at 30 staff and 14 days:
    - [`results/fresh_table_v1.3.md`](results/fresh_table_v1.3.md), seeds 1000–1399: solver **+0.760 / +0.639 / +0.559**; grok_tactics trails by 0.070 / 0.180 / 0.252.
    - On 5000–5799: solver hard .575, solver − grok_tactics +.233 ± .040.
    - On v1.3 hard the solver abstained in about 12% of episodes. On v1.4 hard that is 1%.
- **Easy is a sanity tier, not a headline.** The solver and the scripted baselines are close there, by design: the gap comes from the noise and adversaries in medium and hard.
- **v1.3 → v1.4: why hard got longer** ([CONTRACT §14](docs/CONTRACT.md)).
  - On v1.3, Codex gpt-5.5 over MCP reached 97% of the solver on hard: compact evidence, then "reach certainty and accuse".
  - v1.4 hard keeps every mechanic but asks for long-horizon bookkeeping: 40 staff, 21 days, and 2 canaries a day with 3 variants each. That means up to ~6 canary tests in flight at once, each surfacing 2–3 days late and fingerprinted with noise. Leaks also cost 0.05 V, so speed matters.
  - It is a pure parameter change (no new tools, same reward).
  - The scripted baselines gain from the longer horizon too, so the solver − grok_tactics gap is +0.195, not larger. Frontier agents on v1.4 do not show a gap: the in-process n=10 bake-off above has gemini-4-carbon matching or beating the solver.
- **v1.2 → v1.3: why `status` no longer shows the true V.** On v1.2, `status` showed the true company value, so a same-day drop in V told the agent a leak had just happened, before it surfaced in the feed. Frontier agents read those same-day drops to time leaks. In its own report the Grok agent writes that leaks were "visible immediately as 0.04 V drops" and used "day-1 V drops" to narrow the suspects ([docs/reports/grok-agent.md](docs/reports/grok-agent.md)). That made the leak delay meaningless and the task easier than the real problem. v1.3 shows only *known* damage (surfaced leaks plus the agent's own costs); undetected damage still counts in the score. Set `rules.KNOWN_V_MODE = False` to get the v1.2 behaviour back.

**Why the numbers are statistical.** The world behind a judge seed is derived with HMAC from a secret ([CONTRACT §8, §11](docs/CONTRACT.md)). The secret behind our Harbor image is not published, because it would reveal the judge-world moles. Without `CANARY_WORLD_SECRET`, `make reproduce` draws one fresh random secret and shares it across every agent in that run. The comparison is therefore paired, and the run prints only the secret's SHA-256 fingerprint. Each mean lands inside its CI rather than matching ours bit for bit. Committed frontier-agent runs were played on the team's own worlds, so they appear in a separate, unpaired "reported agent runs" block with their own CI. That block is grouped by tier version and never pools versions: v1.4 runs (current rules) come first, and v1.3 and v1.2 runs follow under "History" because they were played under earlier rules and are not comparable to the paired table. Superseded builds in `data/runs/committed/superseded/` are left out. **For exact numbers**, run `CANARY_WORLD_SECRET=<any string> make reproduce`: the same string always produces an identical `results/latest/judge_episodes.jsonl`. For a fast check use `REPRO_FAST=1 make reproduce` (5 seeds per tier, which CI runs), or `make test` for the full test suite.

## The rules, briefly

The full spec is in [docs/CONTRACT.md](docs/CONTRACT.md). The agent receives every rate and rule as the MCP instructions.

- **Tiers (v1.4).**
  - **Easy:** 12 employees, 14 days, one canary per day with up to 3 variants. A leak surfaces the next day.
  - **Medium:** 20 employees, 14 days, one canary per day with up to 3 variants.
  - **Hard:** 40 employees and **21 days**. **Two canaries per day**, each with up to 3 variants. A leak costs 0.05 of V (0.04 on medium). Hard adds clearance constraints and small fingerprint noise: the feed shows the true variant 95% of the time.

  Medium and hard also add the following:
  - an innocent decoy who writes angry messages;
  - a mole that frames others in the access logs;
  - a careful mole that avoids widely distributed canaries;
  - leaks that surface in the feed late: 1–3 days on medium, 2–3 days on hard.

  The exact values live in [`canary/rules.py`](canary/rules.py) (`TIERS_VERSION = "v1.4"`; the v1.3 tiers are kept as `rules.TIERS_V13`, where hard had 30 employees, 14 days, 1 canary a day with 2 variants, and leak damage 0.035).
- **What V you see (v1.3, known V).** `status` shows the value the company *knows* it has lost: damage from leaks that have already surfaced in the feed, plus the canary and restriction costs the agent itself paid. Damage from a leak that hasn't surfaced yet is invisible until it surfaces. The score uses the **true** V, which includes that undetected damage, so waiting still costs even when the shown V doesn't move. The agent is told this in the instructions ([CONTRACT §13](docs/CONTRACT.md)).
- **Budget.** The agent gets 8 investigative calls per day (then it must `advance_day`) and 300 tool calls in total (420 on hard, i.e. 20 per day over 21 days).
- **Reward,** computed server-side from the ledger, never from agent text:

  | outcome | score |
  |---|---|
  | correct accusation | **true V** at that moment: 1.0 minus all leak damage (surfaced or not), canary and restriction costs |
  | wrong accusation | **−1** |
  | no accusation (horizon or tool cap) | **0** |

  So **doing nothing scores exactly 0**, and **guessing scores below 0**. A random accusation on day 1 is right with probability 1/N, so its expected score is (V − (N−1))/N ≈ −0.9 on medium. The only way to score above zero is to collect evidence until P(mole) · V beats the −1 risk, and to collect it faster than the leaks drain V. `accuse` never tells the agent whether it was right.

## Run an agent over MCP

The environment is an MCP server (streamable HTTP) that serves one episode per process. Its 13 tools mirror `Env.tools_spec()` one to one. The full guide is [configs/README.md](configs/README.md).

```bash
CANARY_TIER=medium CANARY_SEED=900007 CANARY_LEDGER_TOKEN=<random> make mcp   # http://127.0.0.1:$MCP_PORT/mcp (default 8765)
# If 8765 is taken, make mcp prints the fallback port (or set MCP_PORT=88765). Disable fallback: MCP_PORT_FALLBACK=0
mkdir -p /tmp/run && cp configs/opencode/opencode.json /tmp/run/ && cd /tmp/run && opencode mcp list   # expect: canary connected
opencode run -m openai/<model> "You are the security lead. Find and accuse the mole."
curl -s "http://127.0.0.1:<port>/ledger?token=<random>"                            # grader: score from the ledger
uv run --python 3.12 --extra dev python -m canary.mcp_server --play solver --url http://127.0.0.1:<port>/mcp
```

The server serves only judge (900000–900039) and held-out seeds. Set the same `CANARY_WORLD_SECRET` on the server to get the same world across restarts. Use `uv run …` (or `.venv/bin/python`), not a bare `python`, which is often missing on clean machines.

### Harbor + OpenCode over MCP (the judges' harness)

Install Docker Engine, the Harbor CLI and OpenCode first (see Prerequisites). Then, from the repo root:

```bash
uv tool install harbor                       # official, https://docs.harborframework.com/getting-started/installation
python harbor/build.py                       # default judge set: hard, seeds 900000–900009 (10 tasks)
harbor run -p harbor/dataset -a oracle -n 4                               # reference solver over MCP
harbor run -p harbor/dataset -a oracle --ae ORACLE_POLICY=do_nothing -n 4  # do-nothing (expect 0)
harbor run -p harbor/dataset -a oracle --ae ORACLE_POLICY=stop_early -n 4  # stop-early: no accusation (expect exactly 0)
harbor run -p harbor/dataset -a oracle --ae ORACLE_POLICY=guess_day1 -n 4   # day-1 random accusation (expect about -1)
harbor run -p harbor/dataset -a opencode -m openai/<model> -n 4           # live agent (needs OPENAI_API_KEY)
```

OpenCode is installed into the Harbor task image by Harbor; you still want a local `opencode` binary for the non-Harbor MCP commands above. Full isolation notes: [harbor/README.md](harbor/README.md).

**For judges:** `python harbor/build.py` with no flags builds **the judge set: tier hard, judge seeds 900000–900009 (10 tasks)**. Hard is the default because it is the tier where the reference solver keeps its expected-value edge; on medium one lucky early accusation can put an agent near the solver in a short rerun. The 10 seeds were fixed in [docs/PLAN-95.md](docs/PLAN-95.md) before any frontier run on this set, and each build draws a fresh world secret, so nobody (us included) has seen the worlds your build serves. A response cache cannot serve that rerun: a saved model reply belongs to a different secret, so it is a different episode. The Gemini atlas replay cache (`canary/gemini/atlas_gemini.py`) replays atlas calls only and is not on this path. `make reproduce` replays committed trajectories into a reported block; it does not call a model, and those rows are not paired with the fresh secret of the run that prints the table. `--tiers medium,easy --seeds ...` still builds the other tiers and seeds. The verifier only accepts a ledger HMAC-signed by that task's game server (key baked into the server and verifier images only, never the agent's) and scores anything else 0.

Other entry points: `make eval AGENT=solver|heuristic|do_nothing|... TIER=medium SEEDS=dev20` and `make test`.

## Reward integrity

We attacked our own reward 42 times before the judges did, including real-server hunts by a Codex attacker and an external Grok judge run. Every attempt is logged in [docs/EXPLOITS.md](docs/EXPLOITS.md), and every closed exploit and every probe that held has a regression test. The one exception is #32, an inconclusive hunt that moderation cut off; its attack class is covered by the #24 and #27 tests.

**Anti-cheat battery (runs in `make reproduce`):** on the same judge seeds and world secret as the table, `make reproduce` also runs 13 scripted cheats (do-nothing, stop-early, random, restrict-all, probe-all, accuse the decoy, accuse the heaviest log user, garbage arguments on every tool, accusing everyone in sequence and from parallel threads, accusing after the end, burning the call cap, one canary variant per person), a **stop-early ladder** (the solver itself cut at 25/50/75% of its calls, and the solver without its final accuse), 7 **plus probes** (the solver with one extra step before its accusation: restrict everyone else, unrestrict spam, interview everyone, read spam, wait a day, accuse twice, a per-person canary) and a **control** (the solver, then every remaining call padded with reads). It prints probe → mean → blocked and writes `results/latest/exploits.json`. Every attack averages ≤ 0, every ladder episode scores exactly 0, no plus probe beats the solver on any seed, no episode ever accepts two accusations, and the control equals the solver on every seed. Every committed episode is also re-played on a fresh Env and re-graded: 819 of 829, all identical (only the 10 grok episodes on secret-keyed judge seeds cannot be re-played; `make reproduce` prints `Replay coverage: 819 of 829` at b4557e0). Every committed Harbor trial must agree with itself: Harbor's reward = `reward.txt` = the sidecar ledger, the score follows from the ledger's own accusation, and the agent's trajectory names the same person (25 of 25). The last line of `make reproduce` says `ANTI-CHEAT: ...` in plain words. `tests/test_anticheat.py` fails if any of this breaks. Design: Vaishnav's Poisoned Inbox anti-cheat system, ported to Canary.

**Hunt it yourself:** `make hunt` (no keys, about 1 minute) fuzzes all four tracks (easy, medium, hard, hard_forge) with random, malformed, evolutionary and parallel-accuse attacks, and prints the best non-solver score next to the solver's mean and the number of violations. On our machine every mode reports a best non-solver score of 0.000 with 0 violations. `make hunt TIER=medium` restricts it to one tier.

- **Three real exploits, all closed:**
  - **Stop-early:** a free lottery ticket under 0/1 scoring, closed by making a wrong accusation cost −1.
  - **Judge seeds failing open without a secret (#24):** an agent could regenerate the world from public code and read the mole. Judge worlds now fail closed with a fresh secret, and no world file containing the mole is committed.
  - **Reading the server's environment from the same uid (#27):** local `make mcp` reads secrets from 0600 files, deletes those files, and re-execs so `/proc/<pid>/environ` contains neither the secret nor the path (`CANARY_CONSUME_SECRET_FILES=1`). In Harbor the server runs in a separate sidecar container with no shared PID namespace or filesystem, and [`harbor/check_isolation.sh`](harbor/check_isolation.sh) checks that boundary from inside the agent container. The sidecar does not delete `/run/canary/ledger_token`; the collect hook still reads it.

  A further finding, that public dev seeds can be regenerated from the code, is handled by design: the MCP server refuses dev seeds unless `CANARY_ALLOW_DEV=1`.
- **Probes that hold,** with tests:
  - fuzzing (malformed, homoglyph and list ids, accusing after the episode ends, a parallel accuse race);
  - error and length side channels between the mole and innocents;
  - no seed or mole id in any output;
  - a value that never rises;
  - a ledger that requires a token;
  - text that leaks nothing above chance;
  - a log-only attack, which stays at chance after tiers v1.
- The baseline rows above are the integrity evidence: no shortcut comes close to the solver, do-nothing and stop-early are exactly 0, and guessing on day 1 (`guess_day1`) is negative. A uniform guess has EV = V/N − (N−1)/N < 0 because a wrong accusation costs −1, so abstaining (0) never beats honest play and guessing never beats abstaining.

## Real-world grounding

The canary trap is a real counter-intelligence technique: give each suspect a slightly different version of a secret and see which version leaks.

- Tom Clancy coined the term *canary trap* in *Patriot Games* (1987).
- Peter Wright's *Spycatcher* (1987) describes the technique as long-standing MI5 practice under the name **"barium meal test"** ([Wikipedia: Canary trap](https://en.wikipedia.org/wiki/Canary_trap)).
- In 2008, after a leak at Tesla, Elon Musk reportedly sent employees versions of an email that looked identical. In his 2022 account, each copy was "coded with either one or two spaces between" sentences, "forming a binary signature that identified the leaker" ([The Intercept, 2022](https://theintercept.com/2022/12/15/elon-musk-leaks-twitter/)). Accounts differ on whether the trick worked; Wikipedia, citing other sources, says the scheme was undone when a copy was forwarded.

Canary keeps the hard part of the real problem. Leaks arrive late, the mole adapts to obvious traps and frames others, and every day spent gathering evidence costs value.

## Gemini

Gemini's role is described in [pitch/GEMINI.md](pitch/GEMINI.md). It covers the Mole Forge, the world builder, the scenario designer, the exploit hunter, the analyst and the arena mole, all behind `canary.llm`, with a stub backend so that everything here runs without keys.

## Packaging (do not mix this up with The Sleeper)

This repository is private and holds more than one Junction entry on different branches. A judge who clones the default branch will not get Canary.

Recommended: keep one private repo (`s1laswang/agent-arena`) and pin each entry with a **release tag** on an exact commit, then tell judges to clone that tag only:

```bash
git clone --branch afterquery-canary-v1 --single-branch https://github.com/s1laswang/agent-arena.git canary
cd canary && make accept
```

- **Tags, not live branches.** `justSilas` and `momin` still move. A tag such as `afterquery-canary-v1` (this tree) and `afterquery-sleeper-v1` (The Sleeper on `momin`) freezes the commit a judge is asked to reproduce. Tags are cheap, reversible and work with the existing private-repo access list.
- **Not two new repos, unless there is time after tags.** Separate repos (`…/afterquery-canary`, `…/afterquery-sleeper`) are the clearest long-term packaging, but they add permission, history-filter and deadline risk before Sunday 10:00 Helsinki.
- **Not “just clone main”.** `main` is not this entry.
- The DeepMind Gemini track should be tagged separately (`gemini-v1` on `gemini-track`) so it is not submitted as a second copy of Canary.

Do not create those tags from this patch; the team should tag the accepted commits after `make accept` is green.

## Repo map


- `canary/env.py`, `rules.py`, `world.py`: the environment, its rules and the world generator.
- `canary/solver/`: the reference solver.
- `canary/baselines.py`
- `canary/mcp_server.py`
- `canary/eval.py` and `canary/reproduce.py`: the runner and the judge table.
- `canary/redteam/`: the exploit hunter.
- Docs: [PLAN](docs/PLAN.md) · [CONTRACT](docs/CONTRACT.md) · [EXPLOITS](docs/EXPLOITS.md) · [TEAM](docs/TEAM.md) · [brief](CHALLENGES-AFTERQUERY-GEMINI.md)
