# History: earlier tiers, earlier measurements, earlier packaging notes

This file holds the version history that used to sit in the README. It was moved out of `README.md` at commit 309b65f so that the README's first screen is one claim, one table and one command. Nothing here is the current headline: for that see [README.md](../README.md) and [docs/reports/gap.md](reports/gap.md).

Two names changed during the night. Keep this in mind when reading older rows:
- **`stop_early`** used to accuse a random employee on day 1. That policy is now **`guess_day1`**. The current `stop_early` stops on day 1 *without* accusing and scores exactly 0. Committed runs under `data/runs/committed/*/reference/stop_early-*` are the old day-1 accusation.
- **"v1.4 frontier gap: not established"** (below) was true before the v1.4 gemini-4-carbon runs were committed (Sat 14 Nov 22:50, commit 693a3b2). The v1.4 headline in [docs/reports/gap.md](reports/gap.md) supersedes it.


## Expected-numbers band table and frontier history (README until 309b65f)

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

**v1.4 frontier gap: not established** *(historical; superseded, see the note at the top of this file and [docs/reports/gap.md](reports/gap.md): OpenCode + gemini-4-carbon over MCP, hard, n=30: 65% [24%, 98%] of the solver, luck-adjusted 72% [52%, 91%])*. `data/runs/committed/v1.4/` holds reference baselines only, so this band table has no frontier row. An in-process bake-off on rules v1.4, paired seeds, n=10 per tier (21:26) has gemini-4-carbon matching or beating the solver. Medium: solver +0.734±0.050, carbon +0.680±0.085. Hard: solver +0.433±0.324, carbon +0.509±0.136. Smaller Gemini models sat below the solver. That is parity, not a gap. The v1.3 rows below are an earlier hard tier (30 staff, 14 days) and are not a v1.4 gap.

**Tiebreaker.** The notes gain on the flash-lite probe is the generic hint, not a learned policy: notes minus hint is −0.039±0.204. Train and eval seeds are disjoint and the weights were not updated. A change inside that CI is not evidence the model learned the task.

`do_nothing` is exactly 0: the episode ends with no accusation. `stop_early` looks around on day 1 and stops without accusing, so its score is exactly 0 as well (an unaccused episode scores 0). `guess_day1` is that day-1 uniform accusation. A wrong accusation scores −1 (`wrong_accusation_score`); we are not changing that penalty. The `guess_day1` brackets in the band table are the 30-run spread measured at commit 5b56b60 under the old name `stop_early` (same script). On the regenerated judge table ([`results/judge_table.md`](../results/judge_table.md) as regenerated then, fingerprint `6a38958f8096`; the copy committed now is fingerprint `893b837616b9`, where `guess_day1` is −0.950 ± 0.098 / −1.000 ± 0.000 / −0.750 ± 0.208) `stop_early` is +0.000 ± 0.000 on medium, hard, and easy, and `guess_day1` is −0.900 ± 0.137 / −0.950 ± 0.098 / −0.950 ± 0.098. Replayed history rows still named `stop_early` are the old day-1 accusation.

**v1.3 history: frontier agents.** These runs used the v1.3 hard tier (30 staff, 14 days, 1 canary a day), so they are not comparable to v1.4 hard. Medium is unchanged. They were played on v1.3 **dev** seeds 0–10, not judge seeds, and paired with the solver on the same seeds. Each cell is mean ± 95% CI = % of the solver [bootstrap 95% CI]. See the [gap report](reports/gap.md).

| v1.3 frontier run | medium | hard (v1.3) |
|---|---:|---:|
| **Codex gpt-5.5 over MCP** (judges' harness), n=11 per tier, commit a978aa1+ | +0.40 ± 0.42 = **55%** [−8%, 104%] (50% on the planned seeds 0–9) | +0.66 ± 0.04 = **106%** [91%, 136%] (**97%** [89%, 107%] on seeds 0–9) |
| in-process gpt-5.5, fixed loop (full history, Responses API + reasoning replay), n=9 / 8 | +0.67 ± 0.10 = 92% [80%, 106%] | +0.26 ± 0.54 = 38% [−51%, 99%] |

- **Committed run.** [`results/judge_table.md`](../results/judge_table.md) and [`results/gap_chart.png`](../results/gap_chart.png) came from one keyless run on v1.4 (secret fingerprint `6a38958f8096`; the numbers below are that snapshot. The table has since been regenerated, now fingerprint `893b837616b9`: solver medium +0.634 ± 0.086, hard +0.553 ± 0.093, easy +0.785 ± 0.026), written with `make reproduce-update`. The committed v1.3 and v1.2 frontier runs appear there as labelled history. In replayed runs, episodes lost to infrastructure (provider quota, a crashed MCP server) are left out of the mean and counted in a separate `invalid` column with their reasons, and each seed counts once: if two runs cover the same seed, only the newest counts.
  - Solver: medium **+0.679 ± 0.048** (97% correct), hard **+0.547 ± 0.143** (93% correct), easy **+0.808 ± 0.027** (100% correct).
  - Heuristic: medium +0.043 ± 0.241, hard −0.044 ± 0.189, easy +0.652 ± 0.090.
  - `stop_early`: +0.000 ± 0.000 on medium, hard, and easy. `guess_day1`: medium −0.900 ± 0.137, hard −0.950 ± 0.098, easy −0.950 ± 0.098.
- **Fresh seeds.** On seeds never used for tuning, the scripted baselines stay below the solver. That is not a frontier gap. The comparison is paired (same seed, agent − solver):
  - **v1.4:** [`results/fresh_table_v1.4.md`](../results/fresh_table_v1.4.md) covers 800 confirmation seeds per tier (5000–5799) and every baseline.
    - Solver easy/medium/hard **+0.779 / +0.634 / +0.556**, accuracy 99.6 / 89.0 / 94.9%.
    - The strongest scripted baseline is `grok_tactics`, a scripted replay of a strong Grok agent's tactics: the agent's runs and transcripts are in [docs/reports/grok-agent.md](reports/grok-agent.md), and the replay is `GrokTactics` in [`canary/baselines.py`](../canary/baselines.py). It trails the solver by **0.089 ± 0.016 / 0.176 ± 0.025 / 0.195 ± 0.033**.
    - The heuristic trails by 0.131 / 0.641 / 0.534.
    - `stop_early` is 0.000 on every tier (no accusation). `guess_day1` is −0.830 ± 0.039 / −0.902 ± 0.030 / −0.945 ± 0.023.
  - **v1.3 history**, with hard at 30 staff and 14 days:
    - [`results/history/fresh_table_v1.3.md`](../results/history/fresh_table_v1.3.md), seeds 1000–1399: solver **+0.760 / +0.639 / +0.559**; grok_tactics trails by 0.070 / 0.180 / 0.252.
    - On 5000–5799: solver hard .575, solver − grok_tactics +.233 ± .040.
    - On v1.3 hard the solver abstained in about 12% of episodes. On v1.4 hard that is 1%.
- **Easy is a sanity tier, not a headline.** The solver and the scripted baselines are close there, by design: the gap comes from the noise and adversaries in medium and hard.
- **v1.3 → v1.4: why hard got longer** ([CONTRACT §14](CONTRACT.md)).
  - On v1.3, Codex gpt-5.5 over MCP reached 97% of the solver on hard: compact evidence, then "reach certainty and accuse".
  - v1.4 hard keeps every mechanic but asks for long-horizon bookkeeping: 40 staff, 21 days, and 2 canaries a day with 3 variants each. That means up to ~6 canary tests in flight at once, each surfacing 2–3 days late and fingerprinted with noise. Leaks also cost 0.05 V, so speed matters.
  - It is a pure parameter change (no new tools, same reward).
  - The scripted baselines gain from the longer horizon too, so the solver − grok_tactics gap is +0.195, not larger. Frontier agents on v1.4 do not show a gap: the in-process n=10 bake-off above has gemini-4-carbon matching or beating the solver.
- **v1.2 → v1.3: why `status` no longer shows the true V.** On v1.2, `status` showed the true company value, so a same-day drop in V told the agent a leak had just happened, before it surfaced in the feed. Frontier agents read those same-day drops to time leaks. In its own report the Grok agent writes that leaks were "visible immediately as 0.04 V drops" and used "day-1 V drops" to narrow the suspects ([docs/reports/grok-agent.md](reports/grok-agent.md)). That made the leak delay meaningless and the task easier than the real problem. v1.3 shows only *known* damage (surfaced leaks plus the agent's own costs); undetected damage still counts in the score. Set `rules.KNOWN_V_MODE = False` to get the v1.2 behaviour back.

**Why the numbers are statistical.** The world behind a judge seed is derived with HMAC from a secret ([CONTRACT §8, §11](CONTRACT.md)). The secret behind our Harbor image is not published, because it would reveal the judge-world moles. Without `CANARY_WORLD_SECRET`, `make reproduce` draws one fresh random secret and shares it across every agent in that run. The comparison is therefore paired, and the run prints only the secret's SHA-256 fingerprint. Each mean lands inside its CI rather than matching ours bit for bit. Committed frontier-agent runs were played on the team's own worlds, so they appear in a separate, unpaired "reported agent runs" block with their own CI. That block is grouped by tier version and never pools versions: v1.4 runs (current rules) come first, and v1.3 and v1.2 runs follow under "History" because they were played under earlier rules and are not comparable to the paired table. Superseded builds in `data/runs/committed/superseded/` are left out. **For exact numbers**, run `CANARY_WORLD_SECRET=<any string> make reproduce`: the same string always produces an identical `results/latest/judge_episodes.jsonl`. For a fast check use `REPRO_FAST=1 make reproduce` (5 seeds per tier, which CI runs), or `make test` for the full test suite.

## Packaging notes (README until 309b65f; superseded)

Since this note was written, the repository has been made public, The Sleeper has been folded into Canary, and the submission is the annotated tag `afterquery-final` on branch `justSilas`. The original note follows.

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
