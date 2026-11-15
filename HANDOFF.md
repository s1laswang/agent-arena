# Handoff: Gemini bake-off on Canary (v1.4)

Another agent can run this with no extra research. The patch is the deliverable. The branch `justSilas-gemini-bakeoff` is the same tree.

## NEEDS SILAS

The live run cannot start until Silas puts a Gemini API key in **one** of these places:

1. The process environment: `GEMINI_API_KEY` (this wins if both are set).
2. A repo-root file `.env` containing a line `GEMINI_API_KEY=...`. The runner reads that file only when it is present and the variable is unset. `.env` is already gitignored (`.gitignore` line 1, on the base commit). `git status` does not show it. The runner never writes the key, and it redacts the value from episode JSON, the summary, and log lines.

Do not paste the key into the chat, the README, a commit, or this file. FR8 compute nodes have no route to the Gemini API; run on a machine that can reach `generativelanguage.googleapis.com`.

Without the key, only the keyless acceptance test below is possible. A dry-run score is not a measurement.

## Base

| | |
|---|---|
| Repo | `s1laswang/agent-arena` |
| Base branch | `justSilas` |
| Base commit | `b4557e00f881edea464699c058b0f6114af49111` |
| Patch parent | that commit (Merge PR #7) |
| Work branch | `justSilas-gemini-bakeoff` |
| Rules | `canary.rules.TIERS_VERSION` = **v1.4** (the runner refuses `CANARY_TIERS_OVERRIDE`) |
| Env that plays | **Canary**, in-process. Loop is `canary.eval.run_episode`. Policy is `canary.agents.llm_policy.LLMPolicy`. Client is `canary.llm.gemini_backend.GeminiClient` (already on `justSilas`; `gemini-track` was merged as PR #6). |
| Not used | `sleeper` / `momin` `agents/gemini.py`. That file is a different game, and it loads `.env` from more than the repo root. Those branches were not modified. |

## Apply the patch

```bash
git clone <repo> agent-arena && cd agent-arena
git checkout b4557e00f881edea464699c058b0f6114af49111
git apply --check /path/to/gemini_bakeoff.patch
git apply /path/to/gemini_bakeoff.patch
```

`git apply --check` is silent when the patch fits. A non-zero exit means do not apply it.

Files the patch adds:

- `scripts/gemini_bakeoff.py` — the runner
- `tests/test_gemini_bakeoff.py` — keyless tests
- `HANDOFF.md` — this file

`.gitignore` is unchanged. `.env` was already ignored.

## What the runner does

- Lists models from the API at run time (dry-run uses a built-in fixture catalog and does not touch the network).
- Keeps the strongest pro-class Gemini, plus up to `--max-small` flash / flash-lite models. Embedding, TTS, image, and preview-only aliases of a stable model are dropped.
- Plays those models through the current rules, on the same judge-seed prefix as `python -m canary.eval --reproduce --repro-seeds N` (`900000` upward).
- Plays `solver`, `heuristic`, `do_nothing`, and `stop_early` on those seeds.
- Writes one JSON per episode under `<out>/episodes/` and `<out>/invalid/`. Infra failures (API errors, a crashed policy) are `valid: false`. They are counted in `invalid` and left out of mean, std, and the 95% CI.
- Std is the sample standard deviation. The CI half-width is `1.96 * std / sqrt(n)`, the same approximation as `canary.analysis.gap.mean_ci`.
- Tiebreaker: the flash-lite model (even if `--max-small` left it out of the scored table) plays `TRAIN_SEEDS` `100000`…, then the runner writes `<out>/tiebreaker/lessons.md` from those episodes only (public tool results and scores; mole, ledger, and world are stripped). It then plays held-out seeds `800000`… twice: zero-shot, and with those notes in the prompt. Train, held-out, and judge seeds do not overlap. This is in-context text. It is not a weight update. `train/lora_sft.py` trains local Hugging Face weights, not Gemini, and the Gemini tuning API is not wired here.

Judge and held-out worlds use `CANARY_WORLD_SECRET` or `data/worlds/judge/SALT` when one of those exists. This checkout has neither, so a live run is paired inside the process and not bit-exact against `results/judge_table.md`. The summary prints a SHA-256 fingerprint of the secret, not the secret. Set `CANARY_WORLD_SECRET` to any string before the run if the same worlds must be reproducible later. Training seeds (`100000`+) use the public world key and are exact.

## Tasks, highest points per minute first

Points are incremental estimates for **this** package, not the category totals. The environment, the solver, and the anti-cheat battery are already on `justSilas`. This patch does not change tiers or the reward. A dry-run earns none of the Gap, tiebreaker, or Gemini-prize points.

| ID | Criterion | Est. points | Est. minutes | pts/min | Depends on |
|---|---|---:|---:|---:|---|
| GB-4 | Gap 30. Write the README partial (not the headline) from a **real** run. | 6 | 15 | 0.40 | GB-3 |
| GB-5 | Tiebreaker. Write the README paragraph with the reward delta from a **real** probe. | 4 | 10 | 0.40 | GB-3 |
| GB-1 | Craft 15. Apply the patch and pass the keyless acceptance test. | 1 | 3 | 0.33 | nothing |
| GB-7 | Reward integrity 25. Check `do_nothing` and `stop_early` are 0 (stop_early no longer accuses), and `invalid` episodes are out of the mean. Day-1 accusation is `guess_day1` and stays negative. | 1 | 5 | 0.20 | GB-3 |
| GB-6 | Craft 15. Two pitch slides from the real table. | 2 | 15 | 0.13 | GB-3 |
| GB-2 | Gemini prize. One live episode, so a bad key fails before the long run. | 2 | 20 | 0.10 | the key, GB-1 |
| GB-3 | Gap 30 + tiebreaker + Gemini prize. The 90-minute grid. The points are realized in GB-4 and GB-5, not by the run alone. | 0 until written up | 82 | 0.07 | GB-2 or an explicit skip |
| — | Meaningful difficulty 30. | **0** | 0 | — | This patch does not change the env. |

Do them in dependency order: GB-1, then (key in hand) GB-2, then GB-3, then GB-4, GB-5, GB-7, GB-6.

### GB-1 — keyless acceptance

Repo `s1laswang/agent-arena`, branch `justSilas-gemini-bakeoff` (or the applied patch). Files: `tests/test_gemini_bakeoff.py`, `scripts/gemini_bakeoff.py`.

```bash
uv sync --python 3.12 --extra dev --extra llm
python3 -m pytest -q tests/test_gemini_bakeoff.py
python3 scripts/gemini_bakeoff.py --dry-run \
  --out /tmp/gemini-bakeoff-smoke \
  --n 1 --tiers medium --train-n 1 --tie-eval-n 1 --tie-tier medium --slots 1
```

Needs: Python 3.12, `pytest`, `numpy`, `pydantic`. Does **not** need `GEMINI_API_KEY` or `google-genai`. `uv` is how this repo installs them; `python3 -m pytest` is enough if those packages are already installed.

Acceptance: pytest prints `13 passed`. The dry-run exits 0. `/tmp/gemini-bakeoff-smoke/summary.md` starts with `# Gemini bake-off  rules v1.4` and `dry_run=True`. The table header contains `n | invalid | mean | std | 95% CI`. Rows include `solver`, `heuristic`, `do_nothing`, `stop_early`, and `gemini:gemini-4-carbon`. The `do_nothing` mean is `+0.000`. A `## Tiebreaker` section contains `reward change` and, on this mock, `+0.000` (the mock accuses `e00` with or without the notes). `grep -R GEMINI_API_KEY /tmp/gemini-bakeoff-smoke` finds nothing. Gemini rows of `-1.000` in this file are the mock accusing `e00`. They are not a model result.

### GB-2 — live smoke, one Gemini episode

Needs `GEMINI_API_KEY` and `google-genai` (`--extra llm`).

```bash
uv run --python 3.12 --extra llm --extra dev python scripts/gemini_bakeoff.py \
  --out results/gemini_bakeoff/smoke \
  --n 1 --tiers medium --max-small 0 --skip-tiebreaker --slots 1
```

This is one episode of whatever `models.list` ranks as the strongest pro-class model, plus the four local baselines on judge seed `900000`, tier `medium`. No tiebreaker.

Expected: about **90 API calls** and about **20 minutes** if that model is carbon-class (planning bound from `results/gemini/ladder.md`, not a quote). Exit 0. `results/gemini_bakeoff/smoke/summary.md` has one `gemini:` row. If `invalid` is 1, stop. Do not start GB-3. Fix the key, the quota, or the model id first. A smoke score is n=1 and must not go in the README headline.

### GB-3 — the run that fits about 90 minutes

Needs the key. Skip GB-2 only if the clock is already inside 80 minutes; otherwise GB-2 is the cheap failure.

```bash
uv run --python 3.12 --extra llm --extra dev python scripts/gemini_bakeoff.py \
  --out results/gemini_bakeoff \
  --tiers easy,medium,hard --n 5 --slots 4 --max-small 1 \
  --tie-tier medium --pro-n 4 --pro-tiers hard
```

The same command is printed at the bottom of every run as the 90-minute recipe. Model ids are chosen from `models.list` when the process starts. They are not pinned in this command, because a hardcoded id 404s when the API renames a model.

Grid:

| Who | Tiers | Seeds | Episodes |
|---|---|---|---|
| solver, heuristic, do_nothing, stop_early | easy, medium, hard | `900000`–`900004` (5) | 60, local, no API |
| strongest pro-class model | **hard only** | `900000`–`900003` (4) | 4 |
| strongest flash (not lite) | easy, medium, hard | `900000`–`900004` (5) | 15 |
| flash-lite tiebreaker, train | medium | `100000`–`100002` | 3 |
| flash-lite zero-shot and in-context | medium | `800000`–`800004` | 10 |

Planning bounds (upper, from the v1.4 ladder, not a bill): about **1995 API calls**. About **82 minutes** if the pro model accepts 2 calls at once and the other slots run the flash model. About **154 minutes** if the pro model is limited to one call at a time (`pro_serial` in `summary.json`). If the first pro episode is still running after 40 minutes, the 90-minute bound has already failed; let the current episodes finish, do not launch a second copy.

`--max-small 1` keeps the flash in the scored table and leaves the flash-lite to the tiebreaker. A second flash does not fit this bound.

The full default (`--n 5` on every tier for the pro model and three smaller models) is about **4710 calls** and about **180 minutes** at 2-wide, or about **350 minutes** if the pro model is serial. Do not start that tonight.

A headline-sized rerun (`--n 10` on medium and hard) is about **4700 calls** and about **290 minutes** at 2-wide. It does not fit tonight. That is why GB-4 must not touch the headline row.

Resume: rerun the same command. Valid episode JSON already on disk is skipped. Invalid episodes are retried.

### GB-4 — README gap table

File: `README.md`, the v1.4 table that starts near the line `| agent | medium (headline) | hard (headline) | easy (sanity tier only) |`.

The frontier row is today:

```
| frontier agents on v1.4 | pending (measurement in progress) | pending | – |
```

**Do not replace that row** unless medium and hard each have **n ≥ 10 valid** episodes, `rules_version` is `v1.4`, and invalid episodes were excluded. Tonight's grid fails that rule (flash n=5, pro n=4 on hard only, no pro on medium).

Add a paragraph **under** the table, not in the headline cells:

- Label it partial. Give rules `v1.4`, the seed list, `n`, `invalid`, mean, std, and ±95% CI.
- One line per model that actually ran, plus solver, heuristic, do_nothing, and stop_early on the **same** seeds.
- Copy the numbers from `results/gemini_bakeoff/summary.md`. Do not average rows with `valid: false`.
- State the world fingerprint from the summary, and that the run is paired inside one process.
- Pro vs solver is paired only on the seeds both played (hard `900000`–`900003`).

### GB-5 — README tiebreaker paragraph

`README.md` has no tiebreaker section. Add one short paragraph after the gap table. Do not edit the J4 LoRA numbers in `docs/reports/MORNING.md` §6 or `train/README.md`. Those are a weight update of a local model, and they reported no reward gain. This probe is different.

The paragraph must include: the flash-lite model id, train seeds `100000`–`100002`, held-out seeds `800000`–`800004`, tier `medium`, rules `v1.4`, zero-shot mean, in-context mean, and **reward change** (`paired_reward_change` in `results/gemini_bakeoff/tiebreaker/summary.json`). Say the notes came from that model's own training episodes, that train and eval seeds are disjoint, and that the weights were not updated. A change of about 0 is a result. Write it. Do not claim the model learned if the delta is inside the CI.

*[Historical v1.4 n=10 bake-off snapshot; superseded on justSilas by the n=30 paired headline in `docs/reports/gap.md`: 65% [24%, 98%] raw, 72% [52%, 91%] luck-adjusted]*
**Measured 21:26 (do not overwrite with a gap claim).** In-process, rules v1.4, paired seeds, n=10 per tier: gemini-4-carbon matches or beats the solver (medium solver +0.734±0.050 vs carbon +0.680±0.085; hard solver +0.433±0.324 vs carbon +0.509±0.136). Smaller Gemini models sat below the solver. Parity on the initial 10-seed pilot (superseded by n=30 `docs/reports/gap.md`). The tiebreaker's whole notes gain is the generic hint: notes minus hint is −0.039±0.204. Say that confound. Do not say the notes taught the task.

### GB-6 — pitch

`pitch/GEMINI.md` is the Gemini pitch. There is no slide file in the repo. Add two sections there, titled as slides, using only numbers from the real `summary.md`:

1. **Models × score.** One table: model, tier, n, invalid, mean ± 95% CI, vs solver. Include the reference solver and the do_nothing, stop_early, and heuristic rows.
2. **Small model, with and without experience.** Flash-lite zero-shot mean, in-context mean, and the reward delta on the held-out seeds. One sentence: in-context notes, not a weight update.

Leave the dry-run's `-1.000` Gemini cells out. Those are the mock.

### GB-7 — integrity check on the new table

After GB-3, in `summary.md`: `do_nothing` and `stop_early` means are `+0.000` on every tier (`stop_early` stops without accusing), and any `invalid` count is excluded from `n` and the mean. If `do_nothing` is not 0, the run is wrong; do not put it in the README. The day-1 random accusation is `guess_day1`, not this row. This does not add a new exploit test. The existing anti-cheat battery is unchanged.

## Untested without a real key

Tested offline, with a mock client and the fixture catalog: model selection, seed disjointness, invalid-episode exclusion, secret redaction, `.env` load-if-present without overriding the environment, the summary table shape, and one real Canary episode loop driven by the mock (baselines included). `tests/test_gemini_bakeoff.py`: 13 passed. The dry-run above exits 0.

Not tested, because no key was available:

- `models.list()` against the live API. The parser is written for `name` plus `supported_actions` / `supported_generation_methods`. A different payload shape fails the run at startup with a redacted error.
- A real `generateContent` tool-calling loop, thought-signature replay, or a 429. `tests/test_gemini_frontier.py` covers the client with a fake SDK only.
- Whether the live names are still `gemini-4-carbon` / `gemini-3.8-flash` / `gemini-3.1-flash-lite`. The runner re-ranks whatever the API returns.
- The in-context reward delta. The mock accuses `e00` either way, so the dry-run delta is `+0.000` by construction.
- Dollar cost. The call counts above are planning bounds.
- Bit-exact judge worlds. No `SALT` file and no `CANARY_WORLD_SECRET` in this checkout.
