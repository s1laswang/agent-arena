# Meta (HoldUp): 2-min peer-review video plan (team STUHI)

> ⚠️ **WORK IN PROGRESS — owner: Ivar.** First draft, written by Grok Bot from the repo; Ivar has NOT reviewed the VO yet. **All `Picture:` / `On screen:` descriptions are NOT final and have NOT been reviewed by Ivar** — treat them as placeholders. Please don't edit this file directly; send suggestions to Ivar.

Deadline: Sun 15 Nov 10:00 Helsinki. Hard limit 2:00, target 1:55. Burn in subtitles.
Structure: WHY → HOW → WHAT. Version: v2 (03:35 Sun 15 Nov): clearer eval VO, filming optional, no-filming presentation version added.
Repo: github.com/s1laswang/junction-meta-glasses, `main` at 06edb36 (03:09).

> 🎥 **Filming is optional.** We film real clips (Momin's 06:30 hardware take, the three boxes) only if we have time. If not, we make the whole video as an AI-made presentation instead: same VO, with pictures from the **"No-filming version"** section below. Either way, the VO doesn't change.

---

## WHY (0:00–0:30)
**Picture (DRAFT, not reviewed):** three look-alike white medicine boxes on a kitchen counter, a hand hovering between them. Slowly blur the labels until they're unreadable.

**VO:**
"All day we check small things with our eyes. Is this the right pill? Does this have nuts? Now imagine you can't read the label. In one study, 97 percent of older people with a visual impairment struggled to read their medicine labels.
AI can read for them now. But an AI that sounds just as sure when it's guessing is worse than no help."
**On screen (DRAFT, not reviewed):** 97% struggle to read medicine labels (McCann et al., BJGP 2012)

## HOW (0:30–1:25)
**VO:**
"At Junction we built HoldUp for Meta's AI glasses. You hold up a box and ask: is this my evening pill? It coaches you by voice until the label is readable. Turn it around. A bit closer. Got it. Then it checks the label against your own medication list and allergies, which stay on your phone. You get one of three answers: yes, a warning, or I'm not sure."

**Picture (DRAFT, not reviewed):** third-person shot from the 06:30 hardware take (docs/SHOT_LIST.md shot 2): Momin wearing the glasses, both hands free, turns the backwards Amlodipine box, coaching audio from the glasses speakers, green MATCH ("Yes, Amlodipine 5 mg, your evening pill"). Then through-the-lens HUD card. Fallback if the hardware take fails: the browser simulation video (branch fleet/mock-demo-video, docs/demo/holdup-mock-demo.mp4) with its SIMULATION banner kept visible.

**Picture (DRAFT, not reviewed):** Ibuprofen → amber WARNING (avoid NSAIDs). Thumb covering the strength → blue NOT SURE: "I can't read the strength confidently… or ask a pharmacist."

**VO:**
"We tested it on 1,740 photos. At first, 17 times, it told someone with a nut allergy 'none of your allergens' when the food had nuts in it. Usually the allergen line was simply cut off at the edge of the photo. So we taught it to admit when it can't see: if part of the label is missing, it says 'I'm not sure. Show me the whole label.' Those 17 mistakes went to zero. And every time it read a medicine dose and said it was sure, it was right: 754 out of 754."

**Picture (DRAFT, not reviewed):** a cropped food label with the allergen line cut off at the edge; the app's old answer "None of your allergens ✓" gets struck through and replaced by "I'm not sure. Show me the whole label." Counter: 17 → 0.
**On screen (DRAFT, not reviewed):** Missed allergens: 17 → 0 · confident dose reads wrong: 0 of 754 (synthetic test set)

## WHAT (1:25–1:55)
**Picture (DRAFT, not reviewed):** quick POV cuts from the glasses: a food package, the multi-box WHICH ONE strip on the HUD, then back to the person putting the box away.

**VO:**
"Medicine is just the start. Glasses see what you see, so they're the natural place for an assistant that checks the small things: allergens, expiry dates, which box is which. Say it when you're sure, say so when you're not, and hand over to a human. Next, we want to test it with visually impaired people in Finland and their pharmacists.
Hold it up. Know it's the right one."
**On screen (DRAFT, not reviewed):** HOLDUP · team STUHI

---

## No-filming version (presentation, AI-made) (DRAFT, not reviewed)
Use this if nobody has time to film. Style: clean slides with motion, dark background, large type, one idea per screen, like a keynote. Everything below can be made with image/video generation, the existing simulation video and simple slide animation. No camera needed.

| Section | Filmed version | No-filming alternative |
|---|---|---|
| WHY, three boxes | Real boxes on a counter, labels blurring | AI-generated image or short clip of three look-alike white medicine boxes, labels slowly blurring. Then the 97% as a big number on a dark slide with the citation. |
| HOW, coaching to MATCH | Momin wearing the glasses, 06:30 take | Slide with a POV-style AI image of a hand holding a box. The coaching lines appear one by one as large captions ("Turn it around." "A bit closer." "Got it."), then the green MATCH card slides in. Or play the existing simulation video (docs/demo/holdup-mock-demo.mp4) inside a slide frame, SIMULATION banner visible. |
| HOW, three answers | Ibuprofen WARNING, thumb over strength NOT SURE | Three cards side by side, revealed one at a time: green YES, amber WARNING, blue NOT SURE. Each card shows the box and the spoken answer as text. |
| HOW, 17 → 0 | Animation (already planned) | Same: cropped label, "None of your allergens ✓" struck through, replaced by "I'm not sure. Show me the whole label." Counter 17 → 0, then 754 / 754. |
| WHAT, more uses | POV cuts from the glasses | Icon row building up: medicine, allergens, expiry dates, which box is which. Then a slide "Next: testing with visually impaired people in Finland", then the HOLDUP · team STUHI card. |
| VO | Recorded voice | Record on a phone if we can. If not, use an AI voice. |

Rules for the no-filming version:
- Label AI-made pictures as illustrations (small "Illustration" tag). Never present an AI image or clip as real footage of the glasses.
- If we use the simulation video, keep its SIMULATION banner.
- With no hardware footage, change "At Junction we built HoldUp for Meta's AI glasses" to "At Junction we built HoldUp, designed for Meta's AI glasses" so we don't claim it's running on them.

---

## Notes
- VO is about 265 words, roughly 1:55 at a calm pace. If it runs long, cut "And every time it read a medicine dose…" first.
- The emotional beat is our own failure, fixed. It mirrors Canary's theme (an AI that knows when it doesn't know), which could tie the team's entries together.
- All eval numbers are on synthetic Gemini-rendered photos. Say "synthetic" on screen; never imply real patients.
- The pilot is proposed, not agreed. Say "we want to", never "we're partnering with NKL".
- Hardware: as of 03:09 docs/HARDWARE_LOG.md is still an empty template. Don't say "running on Meta glasses" over simulation footage. If only the mock video exists, keep its SIMULATION banner.
- Glasses mic is phone-call quality (8 kHz HFP); record a lavalier as in docs/SHOT_LIST.md so the coaching is audible.
- A separate, longer fleet script exists on unmerged branch fleet/video-script-and-captions (docs/VIDEO_SCRIPT.md). It uses many more stats (55,000 Finns, 21.6% polypharmacy, latency, YOLO numbers). This plan deliberately drops those to keep one outside source.

## Facts and sources (only use these)
- 97% (152/156) of visually impaired adults 65+ had difficulty reading medication labels, despite 80% using optical aids; sighted controls 4%: McCann et al., Br J Gen Pract 2012, https://pmc.ncbi.nlm.nih.gov/articles/PMC3404330/ (opened and checked Sun 15 Nov). Northern Ireland, n = 314. This is the only outside source.
- Coaching lines, three answers, profile on the phone: README.md, docs/SHOT_LIST.md.
- 1,740 synthetic images; v1 safety had 17 cases where the food contained the allergen and the app said "none of your allergens", mostly cropped panels with the nut off-frame; with the allergen gate (conf ≥ 0.95, readability ≥ 0.8, commit 667312c) that is 0: docs/EVAL.md "Where the 49 unsafe reassurances came from" and v2 table, eval/results/v2_safety_rescore.json.
- 0 / 754 confident-wrong strength reads (conf ≥ 0.8; 95% upper bound 0.4%): docs/EVAL.md headline.
- Strength gate 0.8, "ask a pharmacist" hand-off: README.md, docs/PILOT_PLAN.md §1.
- Proposed 4-week, 20-member pilot with Näkövammaisten liitto (not confirmed): docs/PILOT_PLAN.md.
- Don't claim: on-glasses proof (until H1–H10 are filled), the 1.0% → 0.06% overall number without the caveat that the remaining 3 are expiry misreads, or anything about real users.

## Shot list / owners (TODO)
| # | Asset | Owner | Status |
|---|---|---|---|
| 1 | Three white boxes, labels blurring (WHY) | | props listed in docs/SHOT_LIST.md |
| 2 | 06:30 hardware master take: coaching → MATCH, HUD through the lens | Momin (per bake-off) | not filmed yet |
| 3 | Ibuprofen WARNING + thumb-over-strength NOT SURE | Momin | part of the 06:30 take |
| 4 | Cropped allergen label, "17 → 0" animation | | not made |
| 5 | Fallback: mock simulation video | | exists on branch fleet/mock-demo-video (81 s, unmerged) |
| 6 | POV cuts for WHAT (food pack, WHICH ONE strip) | | WHICH ONE is in the mock video |
| 7 | VO + subtitles | | |
| 8 | Edit, export under 2:00 | | |

## Open questions
- Did the 06:30 hardware take work? Everything in HOW depends on it; otherwise use the labelled simulation.
- Do we use the 97% study card at all, or open with the three boxes and no number?
- Is this the same video as the deck's backup video (deck TODO), or a separate one?
