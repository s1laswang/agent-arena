# Canary Lab: 3-minute demo video

Storyboard, shot list and voice-over for the Google DeepMind "Best Use of Gemini API" video. It follows the demo script in
[PLAN.md](PLAN.md). Total 3:00 at 1080p (1920×1080). The voice is Gemini TTS (`gemini-3.8-flash-tts`), generated from the `VO[...]`
lines below by `python -m canary.gemini.narrate`, so every number in the narration comes from the committed result files.

**The submitted cut is the 2-minute [VIDEO-2MIN.md](VIDEO-2MIN.md)** (`assets/canary-lab-2min.mp4`, see `reports/video.md`). This
3-minute version is the long cut and the live-demo script. Its numbers come from the committed ledger (`--ledger committed`, the
default), and a ladder cell is only spoken if it has n ≥ 8 (`narrate.FRONTIER_MIN_N`).

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
| Dashboard panels (1600 px PNG, light) | `assets/dashboard-headline.png`, `-usage`, `-ladder`, `-atlas`, `-swarm`, `-roles`, `-leaderboard` | G5 |
| Dashboard full page, scrolling capture | `results/gemini/dashboard.html` (scroll it in a browser while recording) | G5 |
| Ladder figure | `results/gemini/ladder.png` (G2), or `assets/dashboard-ladder.png` | G2 / G5 |
| Atlas belief-vs-solver chart thumbnails | `results/gemini/charts/*.png` (G3) | G3 |
| Terminal: `make lab-replay` reproducing the tables with no key | screen recording, 10 s | G1 / CEO |
| Narration clips | `assets/narration/*.wav` | G5 |
| Live commentator clip (stretch) | `assets/narration/commentator-demo.wav` | G5 |
| Team photo (last frame) | team drive | Chintufp |

## Storyboard

### 01 Hook (0:00–0:30)

**On screen.** 0:00–0:12: the browser game (`make game-serve`) replays Gemini 4 Carbon on hard seed 9: two canaries a day, the
leak feed lights up with variant B twice, Gemini accuses Riikka Heinonen and is right. **Audio 0:00–0:12:** the Gemini Live
sportscaster, `assets/narration/commentator-demo.wav` from 29.0 s to 38.5 s (the day-5 call: "Another leak! Variant B surfaces, and Gemini 4 Carbon strikes …")
(see `commentator-demo.json` for the per-day cut points), music bed under it. 0:12–0:30: the VO over the same replay; at 0:26 hard cut
to the dashboard headline (`assets/dashboard-headline.png`).
**Lower third.** "Canary: catch the mole. An RL environment with a tuned Bayesian reference solver." At 0:02: "Live commentary: Gemini Live API (gemini-3.8-live)".

> VO[01-hook]: One mole is leaking a company's documents. The agent catches them with canary traps: different versions of a document to different people, then watch which one leaks. One mole, one accusation. This is Canary Lab: Gemini plays, explains and attacks its own benchmark.

### 02 Ladder (0:30–1:15)

**On screen.** 0:30–0:50: `assets/dashboard-ladder.png`, the heatmap (model × thinking level, % of solver), slow zoom from the
minimal column to the high column. 0:50–1:05: the score-vs-thinking-tokens curve, one line per model. 1:05–1:15: the cost frontier,
with the value cell circled.
**Lower third.** "{ladder_models} Gemini models × {ladder_levels} thinking levels × 2 tiers · {ladder_episodes} paired episodes"

> VO[02-ladder]: First, the Gemini Ladder. We ran {ladder_models} Gemini models at up to four thinking levels on the same seeds as the solver: {ladder_episodes} paired episodes, fanned out over our cluster through one Gemini gateway. Thinking control is the knob. Each row shows how much of the gap to the solver that extra thinking buys.

> VO[02-frontier]: And here is the price of it. On {frontier_tier}, {lead_model} at {lead_level} thinking reaches {lead_pct} of the solver, interval {lead_ci}, over {lead_n} episodes, at {lead_cost} each. {cheap_model} at {cheap_level} thinking is {cheap_times} times cheaper, at {cheap_cost}, but scores {cheap_pct}, interval {cheap_ci}, over {cheap_n} episodes: far less certain.

### 03 Atlas (1:15–2:00)

**On screen.** 1:15–1:30: `assets/dashboard-atlas.png`, scrolled down to the v1 tiles (episodes, corpus tokens), then failure mode 1
card with its verified quote highlighted; the belief-vs-solver chart thumbnail enlarges next to it (v1, not blind: it saw our tags).
1:30–2:00: scroll back up to the blind re-run tiles (code modes recovered, new modes named, regret covered) and the per-tag recall table.
**Lower third.** "1M-token context · context caching · multimodal charts · structured output with verified quotes"

> VO[03-atlas]: Next, the Failure Atlas. Gemini read all {atlas_episodes} trajectories, {atlas_tokens} tokens, in one long, cached context, together with a chart of each agent's beliefs against the solver's. It names the failure modes and ties each one to the regret it costs.

> VO[03-modes]: Shown our own regret tags, it explains them: the biggest is "{mode1}", {mode1_share} of all regret. Then we hid every label. Blind, Gemini recovered {blind_recovered} of our {blind_tags} code-defined failure modes and named {blind_new} new ones, though its cited steps cover only {blind_regret_covered} of the regret. Every quote is checked word for word against the transcript.

### 04 Swarm (2:00–2:30)

**On screen.** `assets/dashboard-swarm.png`: the tiles (best unjustified score, 0 verified exploits, positive control), the strip
plot of every attack against the solver line, then the "Score candidates: flagged in-run → reviewed" card (w2b-008 overturned on review).
**Lower third.** "Whole-repo whitebox in context · ledger-verified scores · every win audited against the evidence"

> VO[04-swarm]: Then we turned Gemini on our own benchmark. {attackers} Gemini attacks, {personas} personas, most holding our whole codebase in context, tried to score without catching the mole. Every win is audited against the evidence. The best score the evidence can't justify is {swarm_best_unjustified} on {swarm_best_tier}, against the solver's {swarm_best_solver}. {exploit_sentence} And on a known exploit we reopened, the detector caught {pc_found} of {pc_attempts}.

### 05 Dashboard (2:30–2:50)

**On screen.** 2:30–2:42: `assets/dashboard-headline.png` then `assets/dashboard-usage.png` (feature × model matrix, calls over time,
thinking share, cache savings). 2:42–2:50: terminal, `make lab-replay` prints the ladder table with no API key.
**Lower third.** "{calls} Gemini calls · {tokens} tokens · {thinking} thinking tokens · every call in one ledger"

> VO[05-dashboard]: Every one of the {calls} Gemini calls went through one ledger: {tokens} tokens, {thinking} of them thinking, {cache_share} of the input served from the context cache. And the gateway recorded every response, so anyone can replay our Gemini results offline, without a key.

### 06 Close (2:50–3:00)

**On screen.** Title card: "Canary Lab: Gemini builds, plays, attacks and explains its own benchmark." Then the team photo.

> VO[06-close]: Million-token context, thinking control, context caching, speech, Live and multimodal input, on one API. That's why it had to be Gemini.

## Timing check

About 150 spoken words per minute. Budget per clip: hook ≤ 45 words, ladder ≤ 60 + frontier ≤ 35, atlas ≤ 50 + modes ≤ 50,
swarm ≤ 70, dashboard ≤ 50, close ≤ 25. `narrate --dry-run` prints the word count and the estimated seconds of each clip, and
`narrate` writes the real duration of each WAV to `assets/narration/index.json`.
