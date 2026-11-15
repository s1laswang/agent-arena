# Platform paste text, team STUHI

Description lines are wrapped for reading; the line breaks vanish when the Platform renders markdown. Punchlines are shown as plain text so they copy as one line.

---

## 1. Canary

**Challenge:** AfterQuery: Break the Agent  
**Tech challenges:** Best Use of Gemini API

**Project Name** (6/30)

> Canary

**Punchline** (175/200)

> Humans are imperfect, so more people-management is being handed to AI. Canary gives an AI one chance to catch a mole. On hard, Gemini reaches 65% of a Bayesian solver's score.

**Description** (4605/5000)

```markdown
Humans are imperfect. We miscommunicate, we have biases, we misread each
other. Managing people is hard, so more and more of it is being handed
to AI agents. At Junction we focused on one version of this problem:
finding a mole.

Canary is a living simulated company with one hidden mole. An AI plays
head of security. It reads logs, interviews staff and plants canary
traps: a slightly different secret for each group, to see which one
leaks. Leaks surface late, the feed is noisy, an innocent decoy sends
angry messages, and the mole can frame colleagues in the access logs.
The agent gets one accusation. A correct accusation scores the company
value that is left. A wrong one scores −1. Doing nothing scores 0. The
reference is a Bayesian canary-trap solver that uses the same public
tools and sees only what the agent sees.

The judged tier is hard: 40 employees, 21 days, two canaries a day. In
the judges' own harness (OpenCode over MCP), gemini-4-carbon reaches 65%
of the solver's score (95% CI 24–98%), or 72% after adjusting for luck
(52–91%), on n=30 seeds, rules v1.4. On medium, the same harness is at
parity (111% raw, 101% luck-adjusted, n=30). Run in-process on hard, the
same model reaches 95%. Doing nothing or stopping early scores exactly 0.
If infrastructure failures (empty model replies) are scored 0 instead
of retried, the hard figure is 56%; retrying is the conservative choice,
because that alternative widens the gap.

The difficulty is the kind a real investigator faces: evidence arrives
late, a confident-looking trail can be a frame, and one irreversible
call is worse than waiting. In one hard case (seed 6), Gemini was 92.32%
sure — "There is no doubt" — and accused Laura Saarinen, who was
innocent. The real mole was Sofia Niemi. The reference solver caught
Sofia on day 6, in 52 moves. Gemini took 15 days and 151 moves, and
scored −1. Laura, Sofia and their company are simulated.

We attacked our own reward before the judges did. Three real exploits
were found and closed: a free lottery ticket under 0/1 scoring (a wrong
accusation now costs −1); judge worlds that could be regenerated from
public code; and reading the server's environment from the same user. A
Gemini red-team swarm then ran 100 ledger-verified attacks (91 attackers
in four waves, plus 9 re-runs through the real MCP server; 5 more were
lost to a DNS outage and never scored): 0 verified exploits, 0 invariant
violations. A positive control reopened a known exploit and the detector
caught it 4 times out of 4. Scores come only from the server's
HMAC-signed ledger, never from agent text.

One command, no API keys: `make setup && make reproduce`. It replays
every committed episode (the Gemini hard row comes back as +0.322 ±
0.199), plays the solver and the baselines, and runs the anti-cheat
battery. `make accept` asserts the baselines and an MCP smoke test. The
Harbor path is documented in the README for the judges' harness.

Technologies: Python 3.11+, uv, NumPy, Pydantic, an MCP server
(streamable HTTP, 13 tools), Harbor, OpenCode, and the Gemini API
(`google-genai`). Full rules are in docs/CONTRACT.md. The gap table is
in docs/reports/gap.md and
data/runs/committed/v1.4/paired_table_gemini.md.

**Best Use of Gemini API (Canary Lab).** The problem: a team about to
ship an agent that makes irreversible, budgeted decisions has to pick a
model and a thinking level, and trust that the benchmark cannot be
gamed. We use one ledgered Gemini client for four roles: a player that
runs five Gemini models at controlled thinking levels, paired with the
solver on the same worlds; an attacker that reads the whole repo and
tries to break the reward; a blind analyst that recovers 3 of 5
code-defined failure modes; and an adversary in which gemini-4-carbon
plays the mole (arena mode, not the judged environment). What is new is
treating thinking level as the only changed factor, treating "0
exploits" as evidence (ledger scores, an audit of what the attacker saw,
and a validated detector), and scoring blind failure discovery against
our own labels. Why Gemini: thought-signature replay is load-bearing
(without it, 10/10 hard-tier replays were rejected by the API); explicit
caching cut list-price spend across the ledger; and thinking level on
one model family is what makes the ladder a controlled experiment. In
that ladder, gemini-4-carbon at high thinking reaches 106% of the solver
on hard (n=10). That figure is a lab measurement, not the AfterQuery
headline above. 24,855 Gemini calls, all logged. Replay without keys:
`make lab-replay`. Write-up: docs/gemini/SUBMISSION.md.
```

**Links**

- Source code: https://github.com/s1laswang/agent-arena/tree/justSilas (switch to the `afterquery-final` tag once it exists)
- Video: TODO
- Demo: TODO

---

## 2. Trusted Trade Agents

**Challenge:** Valio Aimo: Trusted Trade Agents  
**Tech challenges:** Best Use of Gemini API (optional)

**Project Name** (20/30)

> Trusted Trade Agents

**Punchline** (193/200)

> Fresh food depends on ordering that works. Trusted Trade Agents lets any AI agent order from Valio Aimo, inside rules the customer controls, with every quote signed and a human on what matters.

**Description** (3584/5000)

_If you don't tick Gemini, delete the last paragraph ("Best Use of Gemini API…")._

```markdown
Fresh food doesn't keep. A kitchen can only serve fresh vegetables, fish
and dairy if the ordering behind it works: the right amount, on time,
every day. When it doesn't, kitchens fall back on processed food that
lasts longer on the shelf. What a school or hospital serves every day
shapes what people eat for the rest of their lives. More of that
ordering is being handed to AI agents. When an agent gets it wrong,
nobody may be watching.

At Junction we built Trusted Trade Agents: an open front door so AI
agents can order from Valio Aimo, without handing them the keys. Any
agent (Gemini, Claude, an ERP) connects over MCP or OpenAPI, searches
the 17,546-product challenge catalog, checks live prices and stock, and
gets a signed, fixed-price quote. The customer writes the rules. Big
spend, a substitute, an odd amount: a named human has to approve. The
agent cannot approve itself. We tried: the request is refused with HTTP
403, and the attempt is logged where anyone can check it. Every quote is
an Ed25519-signed JWS with a 15-minute price lock. Approvals bind to the
quote hash. Every step lands in a signed, hash-chained audit log.

The catalog and the live price API are the challenge's synthetic data.
Demo customers such as Hotel Aurora are invented for the demo, not
Valio's. In the hero flow, a hotel agent asks for 1,000 litres of
lactose-free milk by Monday. The usual 10 L box has missed its cut-off,
so the gateway plans Valio Eila 1 L at €1,010. The hotel's policy says
this needs approval (over €500, a swap, 3.3× usual weekly volume). Anna
signs in and approves that exact quote.

Allergens are tri-state: contains, may contain, or unknown. Unknown is
never treated as safe. In the product data we were given, an almond
drink was tagged nut-free while its ingredients say almond; the gateway
marks that as unknown. Across 640 Gemini-written test orders, an agent
with no guardrails made 193 allergen mistakes and 372 policy violations.
Ours made zero of each. A live montage of six scenarios (cut-off,
stock-out, school allergies, prompt injection, standing-order drift, a
multi-item event) all pass, with the Gemini buyer over MCP. A second toy
wholesaler we built, Nordic Bakery Supply, passes the same 44/44
conformance suite, so the pattern is not locked to one supplier.

The gateway is built on open standards (MCP, OpenAPI 3.1, JWS/Ed25519,
GS1 GTINs, Peppol-style order responses) and has a written path to
production: a SAP or webshop adapter, OAuth, keys in a KMS, Peppol over
the real network, and audit events in an append-only store. Assumptions,
and the replacements for them, are listed in the repo. One command, no
keys: `make accept`, then `uv run aimo serve` and open
http://localhost:8000/ui (replay mode on recorded mock-API responses).

Technologies: Python 3.11, FastAPI, Pydantic v2, SQLite (FTS5), the
official MCP SDK, `google-genai`, `cryptography` (Ed25519), PyYAML, and
a no-build HTML/JS approval UI.

**Best Use of Gemini API (optional tick).** The buyer agent uses
gemini-3.8-flash with function calling over the trade tools, and
escalates the quote-decision turn to gemini-4-hydrogen with high
thinking when a plan has a substitution, a flag or a shortfall (5 of 34
agent steps, 15%, in the live montage). gemini-3.1-flash-lite infers
allergens from ingredient text (it can only block; anything it does not
find stays unknown), checks recipe compatibility, and screens for prompt
injection. gemini-embedding-2 drives hybrid search over the catalog.
Cost per placed order on the final montage was $0.0352. Details:
docs/GEMINI.md.
```

**Links**

- Source code: https://github.com/s1laswang/junction-aimo-agents (switch to the `aimo-v1` tag after the 06:00 freeze)
- Video: TODO
- Demo: TODO

---

## 3. HoldUp

**Challenge:** Meta: AI Glasses for Everyone, Everyday  
**Tech challenges:** Best Use of Gemini API (optional)

**Project Name** (6/30)

> HoldUp

**Punchline** (162/200)

> 97% of older people with a visual impairment struggled to read their medicine labels. HoldUp checks the box against your own list, and says so when it isn't sure.

**Description** (3177/5000)

_If you don't tick Gemini, delete the last paragraph ("Best Use of Gemini API…")._

```markdown
All day we check small things with our eyes. Is this the right pill?
Does this have nuts? In one study, 97% of older people with a visual
impairment struggled to read their medicine labels. AI can read for them
now. But an AI that sounds just as sure when it's guessing is worse than
no help.

At Junction we built HoldUp, designed for Meta's AI glasses. You hold up
a box and ask: is this my evening pill? It coaches you by voice until
the label is readable. Turn it around. A bit closer. Got it. Then it
checks the label against your own medication list and allergies, which
stay on your phone. You get one of three answers: yes, a warning, or I'm
not sure.

It only states a dose it can read clearly (strength confidence at least
0.8). Otherwise it says it is not sure, and can hand you to a
pharmacist. "None of your allergens" is held to a higher bar (confidence
at least 0.95, and a readable panel). The camera runs only during a
check you start, shows CAMERA ON, and stops after 45 seconds without a
label. Frames and audio go to the Gemini API and live only in server
memory. Your medication list never leaves the phone. If the glasses are
off, it can use the phone camera. If you go offline, it can fall back to
a barcode match. If the live session drops, it resumes.

We tested it on 1,740 synthetic photos. At first, 17 times, it told
someone with a nut allergy "none of your allergens" when the food had
nuts in it. Usually the allergen line was cut off at the edge of the
photo. After we raised the bar on that answer, those 17 went to zero.
And every time it read a medicine dose and said it was sure, it was
right: 754 out of 754. These numbers are on synthetic, Gemini-rendered
labels, not real patients or real packs.

Medicine is the start. Next, we want to test it with visually impaired
people in Finland and their pharmacists. That pilot is a proposal, not
an agreed partnership.

This write-up does not claim that HoldUp has been proven on Meta
glasses. The hardware log is still an empty template. The product is
designed for the glasses (a Device Access Toolkit bridge, a Display HUD,
and a phone app), and it can be demoed in the browser without hardware,
or on a phone over an HTTPS tunnel.

Technologies: Node.js 20+, TypeScript, a Vite phone PWA, a Node server
that proxies Gemini Live (`gemini-3.8-live`) and reads labels with
`gemini-3.8-flash` under a JSON schema, a Kotlin Device Access Toolkit
bridge, and a deterministic safety check that the model cannot override.
Keyless check: `make accept`. Live demo: `npm install && npm run dev`,
then open http://localhost:5173 (add `?mock=1` to run without a key).

**Best Use of Gemini API (optional tick — strong fit).** Coaching uses
the Live API with mid-stream function calls: the model is forbidden to
state a name, dose, expiry or allergen from its own view and must call
`verify_label`. Label reading uses schema-constrained extraction with
per-field confidence. Spatial grounding handles several boxes on a
table. Speculative verification starts reading while the user is still
asking (first audio p50 2.1 s / p95 3.4 s, n=26). Gemini also wrote and
rendered the eval set. Details: GEMINI.md.
```

**Links**

- Source code: https://github.com/s1laswang/junction-meta-glasses
- Video: TODO
- Demo: TODO
- Presentation: TODO (deck PDF)
