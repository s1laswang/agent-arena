# 2-minute demo video: report

DONE Sat 23:45

## Sat 23:45: 2-minute cut built, Gemini video QA clean (0 of 8 lines flagged)

**The video: `docs/gemini/assets/canary-lab-2min.mp4`.** It is 2:00.000, 1920×1080, 30 fps, H.264 + AAC 48 kHz, 38.4 MB
(under 50 MB, so no 720p copy was needed), −15.8 LUFS integrated. It follows the shot list and VO in `docs/gemini/VIDEO-2MIN.md`.

**How it is made** (keyless apart from TTS and QA; every number on screen is parsed from, or cited to, a committed file):
- Narration: `canary.gemini.narrate --voice Kore` writes 8 clips to `docs/gemini/assets/narration-2min/` (index.json holds the spoken text).
  The dry run passes, so no placeholder was left unresolved.
- Cut: `uv run python -m canary.gemini.video_cut --html <dashboard.html> --swarm-md results/gemini/swarm.md`.
  - Dashboard panels are captured at 2x with headless Chrome. The cards are rendered with PIL. Ken-Burns pans are rendered per frame
    with sub-pixel EXTENT transforms.
  - The 0–5.45 s intro is the Gemini Live commentator clip. It is cut at its natural pause, and the lower third reads "Gemini Live API".
  - The VO is time-stretched by one factor (atempo ×1.22, pitch kept) so the cut ends at exactly 2:00. Captions snap to real pauses
    (silencedetect).
  - The script also writes `data/gemini/video-build/VIDEO-2MIN.resolved.md`: the VO lines with the exact spoken text, for QA.
- QA: `canary.gemini.video_qa --video docs/gemini/assets/canary-lab-2min.mp4 --script data/gemini/video-build/VIDEO-2MIN.resolved.md`.
  - Result: 8/8 lines have visual support and there are 0 issues (`results/gemini/video_qa.json`). Gemini read 157, 3/5, 21%, 100,
    75/91, 295, +90.795 and 40/40 off the screen.
  - Caveat: its timestamps drift after about 1:00 (it reports up to 160 s on a 120 s video). Treat the QA as a content check, not a
    timing alignment.
- Tests: `tests/test_gemini_lab_video_cut.py` covers the timing plan, the swarm and gallery parsers, and the resolved script
  (98 lab tests green).

**VO changes in VIDEO-2MIN.md (honesty fixes; all numbers now come from files or placeholders)**
- VO[02], VO[05]: now match PR #21 (`gemini-bakeoff-fixes`) word for word. There are 100 attacks in four waves, and the old
  "found it again" became "the detector caught four of four".
  - Shot 5's swarm card is parsed from the final multi-wave `results/gemini/swarm.md`: 91 attackers in 4 waves + 9 MCP re-runs = 100
    attempts; 75/91 whitebox; 0 verified exploits; positive control 4/4 flagged on public dev seeds.
  - That file is on gemini-swarm/gemini-bakeoff-fixes and **not yet on gemini-track**. This cut read it from
    `origin/gemini-bakeoff-fixes`.
- VO[04]: now the blind atlas line from `results/gemini/atlas_blind.json` placeholders: 153 trajectories; 3 of 5 code-defined modes
  recovered; 2 new modes named; cited steps hold 21% of regret. It replaces the non-blind v1 "61% / 98%" line.
- VO[07]: `{cache_share}` and a new `{cost}` placeholder, filled from the committed usage ledger with the dashboard's reprice +
  summarize path (`narrate.usage_summary`). Today that is 85% and $222 (card: $222.18, 24,415 calls).
  - It replaces "$146.02 / 82.7%", which no longer matches `results/gemini/dashboard.html`.
- Shot 8: `make lab-replay` with no key replays recorded episodes ("REPLAY OK, 4 episodes reproduced step for step", "ALL OK"). It does
  not print a ladder table, so the shot list now says what it shows.

**Open for the CEO**
- `docs/gemini/SUBMISSION.md` still quotes 15,757 calls / 82.7% / $146.02. The dashboard and this video now say 24,415 / 85% / $222.18.
- The dashboard is rebuilt at ~00:30 and ~05:15–05:40, and the ledger grows until then. To refresh the video with the final numbers
  after the 05:40 dashboard push (about 10 min on a loaded Mac):
  ```bash
  uv run python -m canary.gemini.narrate --video docs/gemini/VIDEO-2MIN.md --out docs/gemini/assets/narration-2min --voice Kore --only 04-atlas,07-essential
  git show HEAD:results/gemini/dashboard.html > data/gemini/video-build/dashboard-head.html
  uv run python -m canary.gemini.video_cut --html data/gemini/video-build/dashboard-head.html --out docs/gemini/assets/canary-lab-2min.mp4
  env -u GEMINI_GATEWAY_URL uv run python -m canary.gemini.video_qa --video docs/gemini/assets/canary-lab-2min.mp4 --script data/gemini/video-build/VIDEO-2MIN.resolved.md
  ```
  Once PR #21 is on gemini-track, `--swarm-md` defaults to `results/gemini/swarm.md` and needs no override.
