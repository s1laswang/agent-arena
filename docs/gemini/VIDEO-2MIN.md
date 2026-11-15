# Canary Lab: 2-minute demo video (cut-down of VIDEO.md)

Storyboard, shot list and voice-over for the Google DeepMind "Best Use of Gemini API" submission video. 2:00 at 1080p.
The four sections answer the four required questions in order: problem, Gemini integration, what's innovative, why Gemini
is essential. Every number in the narration is in a committed file (sources in the last column). The voice is Gemini TTS:

```bash
uv run python -m canary.gemini.narrate --video docs/gemini/VIDEO-2MIN.md --out docs/gemini/assets/narration-2min --dry-run
uv run python -m canary.gemini.narrate --video docs/gemini/VIDEO-2MIN.md --out docs/gemini/assets/narration-2min --voice Kore
uv run python -m canary.gemini.video_qa --video canary-lab-2min.mp4 --script docs/gemini/VIDEO-2MIN.md   # Gemini fact-checks the cut
```

## Shot list

| # | Time | On screen | Narration clip | Source of every number |
|---|---|---|---|---|
| 1 | 0:00–0:14 | Browser game replays a Gemini episode on hard: canaries go out, the leak feed lights up, one accusation. 0:00–0:06 audio is the Gemini Live commentator clip (`assets/narration/commentator-demo.wav`), then VO. Lower third: "Live commentary: Gemini Live API" | `01-hook` | – |
| 2 | 0:14–0:28 | Title card "Q1 · The problem" over a scroll of one long raw trajectory (JSONL in a terminal, fast) | `02-problem` | – |
| 3 | 0:28–0:48 | "Q2 · Integration". Dashboard ladder heatmap (`assets/dashboard-ladder.png`), slow zoom from minimal to high thinking; cut to the cost frontier | `03-ladder` | `results/gemini/ladder.md` |
| 4 | 0:48–1:04 | Atlas page: blind-run tiles (modes recovered, new modes, regret covered), then the blind recall table per code tag | `04-atlas` | `results/gemini/atlas_blind.md` (`{blind_*}` placeholders) |
| 5 | 1:04–1:18 | Swarm card from the final multi-wave swarm (attempts, waves, whitebox share, 0 verified exploits); then the positive-control card (detector caught 4/4 on public dev seeds) | `05-swarm` | final `results/gemini/swarm.md` (gemini-swarm 905cdd9, via PR #21): 91 attackers in 4 waves + 9 MCP re-runs = 100 attempts, 75/91 whitebox |
| 6 | 1:18–1:32 | "Q3 · What's innovative". Failure gallery waterfall: gap split into causes, "0 unexplained" tile | `06-innovative` | `docs/reports/failure_gallery.md` |
| 7 | 1:32–1:52 | "Q4 · Why Gemini". Dashboard usage panel: feature × model matrix, thinking share; then a card with the three features and the ledger totals | `07-essential` | committed usage ledger: `{cache_share}`, `{cost}` (same reprice + summarize as the dashboard) |
| 8 | 1:52–2:00 | Terminal: `make lab-replay` with no key replays recorded episodes step for step ("REPLAY OK", "ALL OK"). End card: repo URL | `08-close` | – |

The cut is assembled by `uv run python -m canary.gemini.video_cut` (keyless; dashboard panels at 2x, cards, Ken-Burns, the VO
time-stretched by one factor to land at 2:00). After the ledger or results change, re-run narrate (`--only 04-atlas,07-essential`)
and video_cut, then video_qa.

## Voice-over (Gemini TTS reads each VO line; about 285 words, time-stretched to fit 2:00)

> VO[00-holdup]: A blind user holds up a medicine box. HoldUp runs on the Gemini Live API: camera and voice in, speech out. It reads the strength aloud and says when it is not sure. Zero of seven hundred fifty-four confident strength reads were wrong.

> VO[01-hook]: How do you earn that trust in an agent? Canary Lab: Gemini plays, attacks and explains an insider-threat benchmark.

> VO[03-ladder]: So Gemini plays. Five models, up to four thinking levels, five hundred eighty-seven paired episodes. On hard, Gemini four Carbon on high thinking reaches one hundred six percent of the solver, interval ninety-four to one hundred twenty-six, at one dollar ninety-three per episode. Gemini three point six Flash on high thinking costs forty-five cents, more than four times cheaper, and scores eighty-eight percent, interval fifty-one to one hundred thirty-eight: not distinguishable from the solver, but less certain.

> VO[04-atlas]: Then Gemini reads. All {blind_episodes} trajectories in one cached context, without our labels. Blind, it recovered {blind_recovered} of {blind_tags} failure modes our code defines and named {blind_new} new ones. Coverage is still weak: the steps it cites hold {blind_regret_covered} of all regret.

> VO[05-swarm]: Then Gemini attacks. One hundred attacks in four waves, most with our whole codebase in context. Zero verified exploits. To test the detector, we reopened a closed hole: it caught four of four.

> VO[06-innovative]: That is the innovation: a benchmark that measures, explains and audits itself. Across two hundred ninety-five episodes, every lost point is tagged to a decision, with nothing unexplained.

> VO[07-essential]: Three Gemini features make this possible. Thinking level is the ladder's knob. Thought signatures keep reasoning across tool calls. The explicit cache served {cache_share} of input tokens, and the whole programme cost {cost} at list price. TTS and Live only narrate.

> VO[08-close]: Recorded Gemini runs replay offline. Make lab replay. No key needed.

## Screen recordings needed

| Recording | Length | How |
|---|---|---|
| Browser game replaying one Gemini episode on hard (canaries, leak feed, accusation) | 15 s | `make game-serve` (see VIDEO.md assets; Momin has a 60 s capture on the team drive) |
| Terminal scroll of one raw trajectory JSONL | 6 s | `less` on any committed `episodes.jsonl` under `data/runs/committed/` |
| Dashboard: ladder heatmap zoom + cost frontier | 20 s | open `results/gemini/dashboard.html` after `make lab-dashboard`; screen-record while scrolling |
| Dashboard: atlas panel, mode 1 card with quote | 16 s | same page |
| Dashboard: swarm panel | 14 s | same page |
| Failure gallery (rendered markdown or its chart) | 14 s | `docs/reports/failure_gallery.md` in the GitHub viewer |
| Dashboard: usage panel | 20 s | same page |
| Terminal: `make lab-replay` with no key set | 8 s | fresh shell, `unset GEMINI_API_KEY GEMINI_GATEWAY_URL; make lab-replay` |
| Live commentator audio | 6 s | already in `docs/gemini/assets/narration/commentator-demo.wav` |
