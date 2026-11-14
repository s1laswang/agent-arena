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
| 4 | 0:48–1:04 | Atlas page: corpus tiles (episodes, tokens, cache), then failure mode 1 card with a verified quote highlighted | `04-atlas` | `results/gemini/atlas.md` |
| 5 | 1:04–1:18 | Swarm strip plot of every attack against the solver line; then the positive-control row | `05-swarm` | `results/gemini/swarm.md`, `docs/gemini/reports/CEO.md` |
| 6 | 1:18–1:32 | "Q3 · What's innovative". Failure gallery waterfall: gap split into causes, "0 unexplained" tile | `06-innovative` | `docs/reports/failure_gallery.md` |
| 7 | 1:32–1:52 | "Q4 · Why Gemini". Dashboard usage panel: feature × model matrix, cache savings, thinking share | `07-essential` | `docs/gemini/reports/dashboard.md`, `docs/gemini/SUBMISSION.md` |
| 8 | 1:52–2:00 | Terminal: `make lab-replay` prints the ladder table with no key. End card: repo URL | `08-close` | – |

## Voice-over (Gemini TTS reads each VO line; 293 words, about 117 s at 150 wpm)

> VO[01-hook]: One mole is leaking a company's documents. An AI head of security gets one accusation. This is Canary Lab: Gemini plays, explains and attacks its own benchmark.

> VO[02-problem]: Agents now make irreversible calls under uncertainty. One benchmark number can't tell you where they fail, whether more thinking would help, or whether the score can be gamed.

> VO[03-ladder]: So Gemini plays. Five models, up to four thinking levels, one hundred fifty-seven paired episodes. On hard, n equals eight: ninety-two percent, interval seventy-six to one hundred thirteen, at medium, and one hundred two percent, interval eighty-four to one hundred twenty-nine, at high. Gemini three point six Flash, requested as three point five, is within those intervals of the solver, sixteen of sixteen correct, at thirty-four to thirty-nine cents per episode versus one dollar thirty for Gemini four Carbon on high thinking.

> VO[04-atlas]: Then Gemini reads. All one hundred fifty-three trajectories, nearly eight hundred thousand tokens, in one cached context. It names the failure modes, and code checks every quote: ninety-eight percent verbatim. The biggest mode is premature accusation, sixty-one percent of all regret.

> VO[05-swarm]: Then Gemini attacks. Thirty-five attackers read our whole codebase. Thirty-two ran in-process and three via MCP. Zero exploits. When we reopened a closed hole, four of four found it again.

> VO[06-innovative]: That is the innovation: a benchmark that measures, explains and audits itself. Across two hundred ninety-five episodes, every lost point is tagged to a decision, with nothing unexplained.

> VO[07-essential]: Three Gemini features make this possible. Thinking level is the ladder's knob. Thought signatures keep reasoning across tool calls. The explicit cache served eighty-two point seven percent of input tokens, and the programme cost one hundred forty-six dollars and two cents. TTS and Live only narrate.

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
