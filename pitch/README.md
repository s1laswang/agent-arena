# Canary pitch

Ten-minute deck and one-page judge handout for **Canary: catch the mole**.

Facts are taken only from `README.md`, `docs/PLAN.md`, and `CHALLENGES-AFTERQUERY-GEMINI.md` on branch `justSilas`. A yellow token such as `[GAP_1]` is a result those files do not contain. Leave it empty until a real run fills it.

## Files

| Path | What it is |
| --- | --- |
| `assets/office-floorplan.jpg` | The company: employees, agent avatars, the security lead |
| `assets/mole.jpg` | The mole |
| `assets/canary-documents.jpg` | Watermarked canary variants |
| `assets/leak-feed.jpg` | Leak feed with one flagged post |
| `assets/loop.svg` | Investigation loop (observe, canary, day, feed, belief, one accusation) |
| `assets/forge.svg` | Mole Forge loop |
| `deck/canary-pitch.md` | Marp source. 14 slides. Speaker notes are HTML comments, with a timing cue on each slide. Notes are not printed on the slides. |
| `deck/canary-pitch.pdf` | Rendered 16:9 deck |
| `handout/judge-handout.md` | Marp source for the one-page A4 handout |
| `handout/theme.css` | A4 theme. Required when rendering the handout. |
| `handout/judge-handout.pdf` | Rendered handout. It must stay one page. |

The deck is timed to **10:00**:

| | Slide | Spoken |
| --- | --- | --- |
| 1 | Canary | 0:00–0:20 |
| 2 | Insider leaks are costly, and hard to catch | 0:20–1:10 |
| 3 | A company of agents | 1:10–1:50 |
| 4 | One of them is the mole | 1:50–2:25 |
| 5 | Canary documents | 2:25–3:10 |
| 6 | The leak feed. One accusation. | 3:10–3:50 |
| 7 | Noisy, delayed, and one shot | 3:50–4:40 |
| 8 | Every mistake has a price | 4:40–5:20 |
| 9 | Frontier versus the reference | 5:20–6:15 |
| 10 | Built for a 15-minute exploit hunt | 6:15–7:10 |
| 11 | Gemini evolves the mole | 7:10–7:50 |
| 12 | Gemini's six jobs | 7:50–8:30 |
| 13 | A 1.5B model on this environment | 8:30–9:15 |
| 14 | Reproduce it. Then try to break it. | 9:15–10:00 |

## Re-render

From the repository root, with Google Chrome installed. This was rendered with `@marp-team/marp-cli` 4.2.3.

```bash
npx --yes @marp-team/marp-cli@4.2.3 --no-stdin --allow-local-files \
  --browser-path /usr/bin/google-chrome \
  pitch/deck/canary-pitch.md -o pitch/deck/canary-pitch.pdf

npx --yes @marp-team/marp-cli@4.2.3 --no-stdin --allow-local-files \
  --browser-path /usr/bin/google-chrome \
  --theme-set pitch/handout/theme.css --theme canary-handout \
  pitch/handout/judge-handout.md -o pitch/handout/judge-handout.pdf

pdfinfo pitch/deck/canary-pitch.pdf
pdfinfo pitch/handout/judge-handout.pdf
```

`pitch/handout/theme.css` is what makes the handout A4. The deck stays 16:9.

The handout is done only when `pdfinfo` reports `Pages: 1` and the footer is fully visible. Speaker notes in the browser:

```bash
npx --yes @marp-team/marp-cli@4.2.3 --no-stdin --allow-local-files \
  pitch/deck/canary-pitch.md --preview
```

## Placeholders

| Token | What belongs there |
| --- | --- |
| `[STAT_INSIDER_COST]` | A sourced figure for the cost or scale of insider leaks. The docs give the technique's history, not a cost. |
| `[SCORE_FRONTIER_1]` `[SCORE_FRONTIER_2]` `[SCORE_FRONTIER_3]` | Frontier mean score on easy, medium, hard. The README names gpt-5.5 and gpt-5.6-sol and marks these cells pending. |
| `[GAP_1]` | Easy-tier gap, solver minus frontier. |
| `[GAP_MEDIUM]` | Medium-tier gap. Medium is the README's headline tier. |
| `[GAP_FRONTIER]` | Hard-tier gap. |
| `[HUMAN_SCORE]` | Human playtest scores. The plan says to report them. None are in the docs. |
| `[MOLE_GENERATIONS]` | Measured Mole Forge generations. The plan's pitch line says "hundreds." That is not a measured count. |
| `[ANALYST_RUNS]` | Measured runs the analyst clustered. The plan says thousands. |
| `[SCORE_SMALL_BEFORE]` `[SCORE_SMALL_AFTER]` | Qwen2.5-1.5B-Instruct held-out score before and after LoRA. |
| `[GAP_SMALL]` | Remaining gap of that trained 1.5B model to the solver. |
| `[TAGS_DROPPED]` | Which regret tags dropped after training. |

Filled from `README.md` on `justSilas` at `bca5406` (30 keyless runs, 40 seeds per tier, commit `849e652`, tiers v1.1; refresh when tiers freeze at v1.2). This pitch branch does not contain that README edit. It only adds `pitch/`.

| | Easy | Medium | Hard |
| --- | --- | --- | --- |
| Solver | +0.78 | +0.63 | +0.62 |
| Stop-early | −0.85 | −0.89 | −0.95 |
| Heuristic | +0.65 | −0.03 | −0.21 |
| Logs only | −0.47 | −0.98 | −1.00 |
| Random | −0.69 | −0.66 | −0.81 |
| Do-nothing | 0.00 | 0.00 | 0.00 |

Also from that README, and not placeholders: V starts at 1.0; a correct accusation scores V left; a wrong accusation scores −1; no accusation scores 0; horizon 14 days; 8 investigative calls a day and 300 in total; medium and hard use 2 canary variants and 1 canary a day, with leaks 1–3 days late. The small-model plan (Qwen2.5-1.5B-Instruct, LoRA, fp16, one V100, 20k solver trajectories, 200 held-out seeds per tier) and the regret tags, including P(correct) under 0.6, are from `docs/PLAN.md`. `docs/PLAN.md` still describes an older reward (wrong accusation scores 0) and an older tier split. The deck follows the README where they disagree.
