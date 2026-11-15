# Valio Aimo (Trusted Trade Agents): 2-min peer-review video plan (team STUHI)

> ⚠️ **WORK IN PROGRESS — owner: Ivar.** First draft, written by Grok Bot from the repo; Ivar has NOT reviewed the VO yet. **All `Picture:` / `On screen:` descriptions are NOT final and have NOT been reviewed by Ivar** — treat them as placeholders. Please don't edit this file directly; send suggestions to Ivar.

Deadline: Sun 15 Nov 10:00 Helsinki. Hard limit 2:00, target 1:55. Burn in subtitles.
Structure: WHY → HOW → WHAT. Version: v2 (03:30 Sun 15 Nov): Ivar's WHY rewrite, HOW opens on what we built (no challenge setup, no company name).
Repo: github.com/s1laswang/junction-aimo-agents, `main` at 0f51cf0 (judged tag `aimo-v1` at the 06:00 freeze).

---

## WHY (0:00–0:30)
**Picture (DRAFT, not reviewed):** a busy professional kitchen / a clipboard order sheet, then a chat bubble from "Hotel Aurora buyer agent" to the supplier: "1,000 litres of lactose-free milk by Monday."

**VO:**
"Fresh food doesn't keep. A kitchen can only serve fresh vegetables, fish and dairy if the ordering behind it works: the right amount, on time, every day. When it doesn't, kitchens fall back on processed food that lasts longer on the shelf. And what a school or hospital serves every day shapes what people eat for the rest of their lives. Good ordering means healthier food, and healthier habits. So more of that ordering is being handed to AI agents. That should make you a little nervous: when an agent gets it wrong, nobody is watching."

## HOW (0:30–1:25)
**VO:**
"At Junction we built a way to let AI agents order food for kitchens, without handing them the keys."

**Picture (DRAFT, not reviewed):** screen recording of the real gateway UI at /ui: the hero milk run, the plan (usual 10 L box missed its cut-off → Valio Eila 1 L), the signed quote for €1,010, NEEDS APPROVAL with three reasons, Anna signs in and approves. Existing stills: docs/reports/frontend/live-plan.png, s5-approval-signed-in.png, live-run-approved.png.

**VO:**
"It's a trusted gateway. Any AI agent can search the catalogue, check live prices and stock, and get a signed, fixed-price quote. But the customer writes the rules. Big spend, a substitute, an odd amount: a human has to approve. The agent can't approve itself. We tried. It gets refused, and the attempt is logged where anyone can check it."

**Picture (DRAFT, not reviewed):** terminal running docs/pitch/permissions_attack.py: "HTTP 403 agent_cannot_approve", then the audit line "agent:buyer-1 tried to decide order … refused". Then the Verify chain button going red after tamper, green after restore (live-tamper-red.png, live-restore-green.png).

**VO:**
"Then we gave it a school where pupils have milk and nut allergies. In the product data we were given, an almond drink was tagged 'nut-free'. Its ingredients say almond. Our gateway treats that as unknown, and unknown is never safe. Across 640 test orders, an agent with no guardrails made 193 allergen mistakes. Ours made zero."

**Picture (DRAFT, not reviewed):** the product card "Alpro Barista Almond: nut-free ✓" with the ingredient line "ALMOND" highlighting, then a stamp "UNKNOWN = NOT SAFE". Then the school run approved with Oatly (live-school-approval.png).
**On screen (DRAFT, not reviewed):** Allergen mistakes in 640 test orders: no guardrails 193 · our gateway 0

## WHAT (1:25–1:55)
**Picture (DRAFT, not reviewed):** the gateway diagram zooming out: more agents on the left, more suppliers on the right (the second wholesaler "Nordic Bakery Supply" passing the same conformance suite, 44/44).

**VO:**
"Food is just the start. Soon agents will buy and sign for every kind of business. The same pattern works everywhere: the customer sets the rules, every offer is signed, a human signs off on what matters, and every step leaves a trail. Whoever defines how agents trade will own the customer relationship. We think that should be open."
**On screen (DRAFT, not reviewed):** TRUSTED TRADE AGENTS · team STUHI

---

## Notes
- VO is about 280 words, roughly 1:55 at a calm pace (the Canary script is about 260). If it runs long, cut "We tried." and the tamper/verify picture first. Cut line we can restore if there's room: "It's built on open standards, so it isn't locked to one platform."
- Optional laugh line (from our own bug log, fixed): "Our own planner once answered 'oat drink for a school' with 21 packs of Pepsi Max. That's why the guardrails aren't optional." Only if Ivar likes it; it costs about 6 s.
- The data is synthetic (the challenge provides a synthetic catalogue and mock API). Say "in the product data we were given", never "Valio's real data has errors".
- Customers (Hotel Aurora, School Tampere), Anna and the €500 / 3× thresholds are invented for the demo. Don't present them as Valio's.
- The 193 vs 0 compares a naive agent (keyword search, cheapest price, no checks, always orders) with our gateway. Ours is the Sun 00:30 re-run after a policy change; the naive column is from Sat 18:24. Fine for a video, but say "test orders" / "simulated".
- Live demo caveat: the live mock-API hero order stops working after Sun 17:00 (cut-off). Record with `AIMO_NOW=2026-11-15T10:00:00+02:00` or replay mode, or before 17:00.

## Facts and sources (only use these)
- No outside sources in the VO (the 20,000+ kitchens line was cut; the company isn't named in the video).
- "Who owns the customer relationship" framing: challenge page https://junction2026.com/challenges/valio-aimo-trusted-trade-agents ("existential for data ownership, trust, and who owns the customer relationship").
- Hero flow: 1,000 L lactose-free milk, usual 10 L box missed cut-off, Valio Eila 1 L, €1,010, needs approval (over €500, a swap, 3.3× usual weekly volume), Anna approves the quote hash: README.md, docs/pitch/deck.md slide 3.
- Agent cannot approve: HTTP 403 `agent_cannot_approve`, audited as `approval.refused`: docs/DEMO.md "Permissions attack", docs/pitch/permissions_attack.py.
- Almond drink: 465793 Alpro Barista Almond is "nut-free" in structured data but ingredients contain ALMOND; gateway marks it unknown (source "contradiction"): docs/reports/windtunnel.md finding 6, tests/test_catalog.py::test_alpro_almond_conflict_is_unknown_and_flagged. 28 such contradictions in the data.
- School policy blocks milk, nuts and unknown allergens: docs/pitch/deck.md slide 4, docs/TRUST.md §3. School montage run placed Oatly, approved by liisa: docs/demo-montage.md.
- 640 Gemini-written scenarios: naive agent 193 allergen / 372 policy violations, gateway 0 / 0: docs/windtunnel-results.md, docs/NUMBERS.md "Wind tunnel".
- Second wholesaler passes conformance 44/44 (Nordic Bakery Supply is a toy wholesaler we built, not a real company): docs/NUMBERS.md "MCP and openness", README "Openness".
- Pepsi Max bug (optional line): school "oat drink" 120 L planned 21 × "18 x Pepsi Max soft drink 0,33 l", fixed in round 3: docs/reports/catalog.md "Round 3", docs/reports/buyer.md.
- Don't claim: escalation precision is only 68.2% (target 90% not met), approvers share one demo passphrase, Peppol is partial.

## Shot list / owners (TODO)
| # | Asset | Owner | Status |
|---|---|---|---|
| 1 | Kitchen / order-sheet B-roll + agent chat bubble (WHY) | | not made |
| 2 | Screen recording: hero milk run → approval → placed | | stills exist in docs/reports/frontend/; backup video TODO (deck plan says Chintufp records) |
| 3 | Terminal: permissions_attack.py 403 + audit line | | script exists, needs recording |
| 4 | Almond "nut-free" card → UNKNOWN stamp, school run | | not made |
| 5 | "193 vs 0" stat card | | not made |
| 6 | Zoom-out diagram with second wholesaler (WHAT) | | README mermaid diagram exists as a base |
| 7 | VO + subtitles | | |
| 8 | Edit, export under 2:00 | | |

## Open questions
- Is the Aimo demo video the same file as the peer-review video, or a separate longer demo? (bake-off: backup video still TODO, Sun 17:00 cut-off)
- Keep or cut the Pepsi Max laugh line?
- Who records: Chintufp (per docs/pitch/deck.md) or someone else?
