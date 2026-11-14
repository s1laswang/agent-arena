# Canary Lab: 3-minute demo video

Storyboard, shot list and voice-over for the Google DeepMind "Best Use of Gemini API" video. It follows the demo script in
[PLAN.md](PLAN.md). Total 3:00 at 1080p (1920×1080). The voice is Gemini TTS (`gemini-3.8-flash-tts`), generated from the `VO[...]`
lines below by `python -m canary.gemini.narrate`, so every number in the narration comes from the committed result files.

## How to build the voice track

```bash
uv run python -m canary.gemini.narrate --dry-run          # print the script with every {placeholder} filled from results/
uv run python -m canary.gemini.narrate --voices Kore,Charon,Puck --only 01-hook   # audition voices on one clip
uv run python -m canary.gemini.narrate --voice Kore       # all clips -> docs/gemini/assets/narration/<id>.wav
```

Each `VO[id]` line becomes one WAV clip (24 kHz mono). Each clip is one Gemini TTS call, logged to the ledger as
`feature="narrate", kind="tts"`. Placeholders in `{braces}` are filled from `results/gemini/*.json` and the ledger summary
(`python -m canary.gemini.dashboard --json`). If a value doesn't exist yet, `narrate` stops and names it, so the video never
quotes a number we can't back.

## Assets

| Asset | File | Who |
|---|---|---|
| Browser game replaying a Gemini episode (60 s, 1080p screen recording) | team drive: `game-replay-gemini.mp4` | Momin |
| Dashboard panels (1600 px PNG, light) | `assets/dashboard-headline.png`, `-usage`, `-ladder`, `-atlas`, `-swarm` | G5 |
| Dashboard full page, scrolling capture | `results/gemini/dashboard.html` (scroll it in a browser while recording) | G5 |
| Ladder figure | `results/gemini/ladder.png` (G2), or `assets/dashboard-ladder.png` | G2 / G5 |
| Atlas belief-vs-solver chart thumbnails | `results/gemini/charts/*.png` (G3) | G3 |
| Terminal: `make lab-replay` reproducing the tables with no key | screen recording, 10 s | G1 / CEO |
| Narration clips | `assets/narration/*.wav` | G5 |
| Live commentator clip (stretch) | `assets/narration/commentator-demo.wav` | G5 |
| Team photo (last frame) | team drive | Chintufp |

## Storyboard

### 01 Hook (0:00–0:30)

**On screen.** 0:00–0:20: the browser game (`make game-serve`) replays one Gemini 4 Carbon episode on a hard seed. The canary
trap fires, the leak feed lights up, Gemini accuses. 0:20–0:30: hard cut to the dashboard ladder heatmap, with the hard-tier carbon
row highlighted.
**Lower third.** "Canary: catch the mole. An RL environment with a Bayes-optimal reference solver."

> VO[01-hook]: A company has one mole leaking documents. The agent has to find them with canary traps: send different versions of a document to different people, and watch which version leaks. Gemini 4 Carbon plays this about as well as a Bayesian reference solver on medium. On hard, it reaches {carbon_hard_pct} of the solver. Why? Canary Lab uses Gemini to find out.

### 02 Ladder (0:30–1:15)

**On screen.** 0:30–0:50: `assets/dashboard-ladder.png`, the heatmap (model × thinking level, % of solver), slow zoom from the
minimal column to the high column. 0:50–1:05: the score-vs-thinking-tokens curve, one line per model. 1:05–1:15: the cost frontier,
with the value cell circled.
**Lower third.** "{ladder_models} Gemini models × {ladder_levels} thinking levels × 2 tiers · {ladder_episodes} paired episodes"

> VO[02-ladder]: First, the Gemini Ladder. We ran {ladder_models} Gemini models at every thinking level on the same seeds as the solver: {ladder_episodes} paired episodes, fanned out over our cluster through one Gemini gateway. Thinking control is the knob. Each row shows how much of the gap to the solver that extra thinking buys.

> VO[02-frontier]: And here is the price of it. {value_model} at {value_level} thinking keeps {value_pct_of_best} of the top score, {best_model} at {best_level} thinking, for {value_cost_share} of the cost per episode.

### 03 Atlas (1:15–2:00)

**On screen.** 1:15–1:25: `assets/dashboard-atlas.png`, corpus tiles (episodes, tokens, cached tokens). 1:25–1:50: failure mode 1
card with its verified quote highlighted, then mode 2 and 3; the belief-vs-solver chart thumbnail enlarges next to mode 1.
1:50–2:00: the human agreement tile.
**Lower third.** "1M-token context · context caching · multimodal charts · structured output with verified quotes"

> VO[03-atlas]: Next, the Failure Atlas. Gemini read all {atlas_episodes} trajectories, {atlas_tokens} tokens, in one long, cached context, together with a chart of each agent's beliefs against the solver's. It names the failure modes and ties each one to the regret it costs.

> VO[03-modes]: The biggest is "{mode1}", with {mode1_share} of all regret. Then "{mode2}" and "{mode3}". Every quote is checked word for word against the transcript, and our teammate labelled a sample by hand: {agreement} agreement with Gemini.

### 04 Swarm (2:00–2:30)

**On screen.** `assets/dashboard-swarm.png`: the strip plot of every attack against the solver line, then the top-attempts table
and the findings row.
**Lower third.** "Whole-repo whitebox in context · ledger-verified scores · findings become regression tests"

> VO[04-swarm]: Then we turned Gemini on our own benchmark. {attackers} Gemini attackers, {personas} personas, each holding our whole codebase in context, tried to score without catching the mole. Only scores the ledger verifies count. The best one reached {best_non_solver}, against the solver's {solver_score}. {exploit_sentence}

### 05 Dashboard (2:30–2:50)

**On screen.** 2:30–2:42: `assets/dashboard-headline.png` then `assets/dashboard-usage.png` (feature × model matrix, calls over time,
thinking share, cache savings). 2:42–2:50: terminal, `make lab-replay` prints the ladder table with no API key.
**Lower third.** "{calls} Gemini calls · {tokens} tokens · {thinking} thinking tokens · every call in one ledger"

> VO[05-dashboard]: Every one of the {calls} Gemini calls went through one ledger: {tokens} tokens, {thinking} of them thinking, {cache_share} of the input served from the context cache. And the gateway recorded every response, so anyone can replay our Gemini results offline, without a key.

### 06 Close (2:50–3:00)

**On screen.** Title card: "Canary Lab: Gemini builds, plays, attacks and explains its own benchmark." Then the team photo.

> VO[06-close]: Million-token context, thinking control, caching, batch and multimodal input, on one API. That's why it had to be Gemini.

## Timing check

About 150 spoken words per minute. Budget per clip: hook ≤ 70 words, ladder ≤ 60 + frontier ≤ 35, atlas ≤ 50 + modes ≤ 50,
swarm ≤ 70, dashboard ≤ 50, close ≤ 25. `narrate --dry-run` prints the word count and the estimated seconds of each clip, and
`narrate` writes the real duration of each WAV to `assets/narration/index.json`.
