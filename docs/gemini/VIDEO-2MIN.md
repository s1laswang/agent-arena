# Gemini agents you can trust: 2-minute demo video (v2)

Storyboard, shot list and voice-over for the Google DeepMind "Best Use of Gemini API" submission video, 1080p, at most
2:20. Thesis: HoldUp is a product on the Gemini Live API; Canary Lab is the proof that Gemini agents can be measured,
explained and audited. Every number in the narration is in a committed file (sources in the last column). The voice is
Gemini TTS (Kore):

```bash
uv run python -m canary.gemini.narrate --video docs/gemini/VIDEO-2MIN.md --out docs/gemini/assets/narration-2min --dry-run
uv run python -m canary.gemini.narrate --video docs/gemini/VIDEO-2MIN.md --out docs/gemini/assets/narration-2min --voice Kore
uv run python -m canary.gemini.video_qa --video canary-lab-2min.mp4 --script data/gemini/video-build/VIDEO-2MIN.resolved.md   # Gemini fact-checks the cut
```

## Shot list

Shot lengths follow the narration clips (`video_cut.shots_v2`); times below are from the committed cut.

| # | Time | On screen | Narration clip | Source of every number |
|---|---|---|---|---|
| 0 | 0:00–0:20 | HoldUp browser simulation (`assets/holdup-demo-20s.mp4`): coaching, green MATCH "Amlodipine 5 mg", then blue NOT SURE "Can't read the strength". Its yellow SIMULATION banner stays visible. Captions: "HoldUp: browser simulation of the glasses flow", "Product: Gemini Live API", then the 0/754 figure | `00-holdup` | junction-meta-glasses `GEMINI.md` @ tag `gemini-quote-0515`, line 33: "0 of 754 confident strength reads were wrong (95% upper bound 0.4%)", across 1,740 images |
| 1 | 0:20–0:35 | Card "How do you earn trust in an agent?", then the Canary Lab title. Then the Gemini Live commentator clip (`assets/narration/commentator-demo.wav`, 5.45 s) over the title, lower third "Live commentary: Gemini Live API" | `01-hook` | – |
| 3 | 0:35–1:05 | "Q2 · Integration". Dashboard ladder heatmap, slow zoom; cut to the cost frontier. Captions parsed from `ladder.md` | `03-ladder` | `results/gemini/ladder.md` |
| 3b | 1:05–1:15 | Cross-provider control chart (`assets/xprov.png`, copied from `results/gemini/xprov.png` on gemini-v3 56f23277). Caption: matched medium effort, not distinguishable from GPT-5.5 in all 4 pairings, 2.0x–3.8x cheaper. The cut includes it only if the PNG and `03b-xprov.wav` exist | `03b-xprov` | `results/gemini/xprov.md` paired tables (hard: 3.6-flash 3.8x, 4-hydrogen 2.3x cheaper; medium: 3.1x, 2.0x; all "not distinguishable", 8–9 shared seeds). The xprov headline is too long to narrate in 10 s; this is the owner's short line, checked against those tables |
| 4 | 1:05–1:23 | Atlas page: blind-run tiles (modes recovered, new modes, regret covered), then the blind recall table per code tag | `04-atlas` | `results/gemini/atlas_blind.md` (`{blind_*}` placeholders) |
| 5 | 1:23–1:38 | Swarm card from the final multi-wave swarm (attempts, waves, whitebox share, 0 verified exploits); then the positive-control card (detector caught 4/4 on public dev seeds) | `05-swarm` | final `results/gemini/swarm.md`: 91 attackers in 4 waves + 9 MCP re-runs = 100 attempts, 75/91 whitebox |
| 6 | 1:38–1:51 | "Q3 · What's innovative". Failure gallery waterfall: gap split into causes, "0 unexplained" tile | `06-innovative` | `docs/reports/failure_gallery.md` |
| 7 | 1:51–2:10 | "Q4 · Why Gemini". Dashboard usage panel: feature × model matrix; then a card with the three features. No exact call, cost or token totals (the single usage total is regenerated after this cut) | `07-essential` | `canary/gemini/ledger.py`, dashboard usage panel |
| 8 | 2:10–2:19 | Terminal: `make lab-replay` with no key replays recorded episodes step for step ("REPLAY OK", "ALL OK"). End card: repo URL | `08-close` | – |

v1 (2:00) had a "Q1 · The problem" card and trajectory scroll (`02-problem`); v2 replaces it with the HoldUp opening.

**Shot 0 source.** `assets/holdup-demo-20s.mp4` (0.6 MB) is two 10 s stretches of HoldUp's mock demo, re-encoded without audio:

```bash
gh api -H 'Accept: application/vnd.github.raw' \
  'repos/s1laswang/junction-meta-glasses/contents/docs/demo/holdup-mock-demo.mp4?ref=gemini-quote-0515' > /tmp/holdup.mp4
ffmpeg -i /tmp/holdup.mp4 -filter_complex "[0:v]trim=11:21,setpts=PTS-STARTPTS[a];[0:v]trim=44.25:54.25,setpts=PTS-STARTPTS[b];[a][b]concat=n=2:v=1:a=0[v]" \
  -map "[v]" -an -c:v libx264 -crf 18 -pix_fmt yuv420p docs/gemini/assets/holdup-demo-20s.mp4
```

The cut is assembled by `uv run python -m canary.gemini.video_cut --html <dashboard.html>` (keyless; dashboard panels at 2x,
cards, Ken-Burns; VO at tempo 1.0 unless the cut would pass 2:19.5, then one atempo factor). It also writes
`data/gemini/video-build/VIDEO-2MIN.resolved.md` (the exact spoken text) for video_qa.

## Voice-over (Gemini TTS reads each VO line, voice Kore)

> VO[00-holdup]: A blind user holds up a medicine box. HoldUp runs on the Gemini Live API: camera and voice in, speech out. It reads the strength aloud and says when it is not sure. Zero of seven hundred fifty-four confident strength reads were wrong.

> VO[01-hook]: How do you earn that trust in an agent? Canary Lab: Gemini plays, attacks and explains an insider-threat benchmark.

> VO[03-ladder]: So Gemini plays. Six models, up to five thinking levels, six hundred seven paired episodes. On hard, Gemini four Carbon on high thinking reaches one hundred six percent of the solver, interval ninety-four to one hundred twenty-six, at one dollar ninety-three per episode. Gemini three point six Flash on high thinking costs forty-five cents, more than four times cheaper, and scores eighty-eight percent, interval fifty-one to one hundred thirty-eight: not distinguishable from the solver, but less certain.

> VO[03b-xprov]: On identical worlds and at matched effort, Gemini is not distinguishable from GPT-5.5, at two to four times lower cost per episode.

> VO[04-atlas]: Then Gemini reads. All {blind_episodes} trajectories in one cached context, without our labels. Blind, it recovered {blind_recovered} of {blind_tags} failure modes our code defines and named {blind_new} new ones. Coverage is still weak: the steps it cites hold {blind_regret_covered} of all regret.

> VO[05-swarm]: Then Gemini attacks. Five hundred thirteen attacks, most with our whole codebase in context. Zero verified exploits. To test the detector, we reopened three closed holes: it caught sixteen of sixteen.

> VO[06-innovative]: That is the innovation: a benchmark that measures, explains and audits itself. Across two hundred ninety-five episodes, every lost point is tagged to a decision, with nothing unexplained.

> VO[07-essential]: Three Gemini features make this possible. Thinking level is the ladder's knob. Thought signatures keep reasoning across tool calls. The explicit cache served most input tokens, and every Gemini call is logged. TTS and Live only narrate.

> VO[08-close]: Recorded Gemini runs replay offline. Make lab replay. No key needed.

## Screen recordings needed

| Recording | Length | How |
|---|---|---|
| Browser game replaying one Gemini episode on hard (canaries, leak feed, accusation) | 15 s | `make game-serve` (see VIDEO.md assets; Momin has a 60 s capture on the team drive) |
| HoldUp browser simulation (shot 0) | 20 s | committed: `assets/holdup-demo-20s.mp4` (command above) |
| Dashboard: ladder heatmap zoom + cost frontier | 20 s | open `results/gemini/dashboard.html` after `make lab-dashboard`; screen-record while scrolling |
| Dashboard: atlas panel, mode 1 card with quote | 16 s | same page |
| Dashboard: swarm panel | 14 s | same page |
| Failure gallery (rendered markdown or its chart) | 14 s | `docs/reports/failure_gallery.md` in the GitHub viewer |
| Dashboard: usage panel | 20 s | same page |
| Terminal: `make lab-replay` with no key set | 8 s | fresh shell, `unset GEMINI_API_KEY GEMINI_GATEWAY_URL; make lab-replay` |
| Live commentator audio | 6 s | already in `docs/gemini/assets/narration/commentator-demo.wav` |
