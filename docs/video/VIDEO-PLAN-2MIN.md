# Canary: 2-min peer-review video plan (team STUHI)

> ⚠️ **WORK IN PROGRESS — owner: Ivar.** The VO script is Ivar's working draft. **All `Picture:` / `On screen:` descriptions are NOT final and have NOT been reviewed by Ivar** — treat them as placeholders. Please don't edit this file directly; send suggestions to Ivar.

Deadline: Sun 15 Nov 10:00 Helsinki. Hard limit 2:00, target 1:55. Burn in subtitles.
Structure: WHY → HOW → WHAT. Version: v3 (03:05): flamingo skit cut, SailPoint dropped

---

## WHY (0:00–0:30)
**Picture (DRAFT, not reviewed):** everyday office moments (coffee spill, wrong email sent, an argument). Then a dashboard of an AI agent assigning tasks.

**VO:**
"Humans are imperfect. We miscommunicate, we have biases, we misread each other. Managing people is hard, so more and more of it is being handed to AI agents.
That feels uncomfortable. It's the same feeling as getting into a self-driving car, even as they become the safer option. Right now it is probably not superior to a human, but humans are also not setting a high bar."

## HOW (0:30–1:25)
**Picture (DRAFT, not reviewed):** canary trap close-up from the game (12 s). Four near-identical versions of a document go out (A/B/C/D, one word highlighted in each), then version B shows up in the leak feed.

**VO:**
"At Junction we focused on one version of this problem: finding a mole. Insiders cost companies 17 million dollars a year on average, and over half of those incidents are accidents, not spies."
**On screen (DRAFT, not reviewed):** $17.4M a year · 55% negligence (Ponemon 2025)

**Picture (DRAFT, not reviewed):** game demo. Company value drains, canaries go out, variant B leaks, suspects narrow.

**VO:**
"So we built Canary. It's a living simulated company with one hidden mole, where an AI plays head of security. It reads logs, interviews staff and plants canary traps: a slightly different secret for each person, to see which one leaks. It gets one accusation, and a wrong one costs more than doing nothing."

**Picture (DRAFT, not reviewed):** "There is no doubt." types out, ACCUSED stamp on Laura's ID, then the belief chart (/workspace/video_assets/seed6_overconfidence.png, animated).

**VO:**
"We put Gemini in charge. In one case it was '92% sure, no doubt' and accused Laura. Laura was innocent. The real mole had framed her. Our reference detective had caught her on day six. And because AI is good at cheating, we sent 35 AI hackers at our own scoring. Three real holes were found, and all three were closed."

## WHAT (1:25–1:55)
**Picture (DRAFT, not reviewed):** office map with small glitches appearing: a misrouted message, two people in conflict, a leak.

**VO:**
"Similar frameworks can teach AI to understand any strange behaviour in an organisation: accidental leaks, miscommunication, small conflicts that quietly grow. All of it destroys value that these organizations otherwise would make, and every organisation is at risk."
**On screen (DRAFT, not reviewed):** CANARY · team STUHI

---

## Notes
- If it runs long, cut the "35 AI hackers" line first and save it for the deck and Q&A.
- No self-driving stat (no single clean number). The analogy works without one.
- Laura and her company are fictional. Make that clear on screen ("simulated employee").

## Facts and sources (only use these)
- Gemini hard case 6: 15 days / 151 moves, accused e18 Laura Saarinen at "92.32%... There is no doubt." Real mole e34 Sofia Niemi framed her with a fake late-night login. The reference detective was at 63% on Laura and caught Sofia on day 6 in 52 moves. Source: data/runs/committed/v1.4/inproc-gemini-4-carbon/hard/transcripts/6.json, reference/solver-hard-20261114-121126.
- Gemini wrongly accused 5 of 60 people on hard cases (results/gap_vs_solver_v1.4_8fd4dec.md). Don't say "frontier AI is 65%".
- 35 AI hackers, 1,225 tool calls, 0 exploits; positive control 4/4 (results/gemini/swarm.md). 3 real exploits closed (#23, #24, #42 in docs/EXPLOITS.md).
- $17.4M a year, 55% negligence: https://www.globenewswire.com/news-release/2025/02/25/3032261/0/en/ponemon-cybersecurity-report-insider-risk-management-enabling-early-breach-detection-and-mitigation.html
- Ponemon is the only outside source. Don't add others unless needed.

## Shot list / owners (TODO)
| # | Asset | Owner | Status |
|---|---|---|---|
| 1 | Office B-roll (WHY) | | |
| 3 | Game screen recording | | |
| 4 | "There is no doubt" typed card + Laura ID + ACCUSED | | |
| 5 | Animated belief chart | | |
| 6 | Office-map glitches (WHAT) | | |
| 7 | VO + subtitles | | |
| 8 | Edit, export under 2:00 | | |

## Open questions
- Public game URL for an end card? (needs a push to GitHub Pages, so it needs Ivar's OK)
