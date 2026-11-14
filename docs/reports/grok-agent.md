# Grok agent: Canary evaluation results

**Model:** Grok Bot  
**Branch evaluated:** `justSilas` (environment started via `make setup` / `make mcp`; only `configs/README.md` was read, no source, tests or other docs; the README's reference solver was not used).

| Tier | Seed | Score | Accused | Correct | Final day | Tool calls | Transcript |
|---|---|---|---|---|---|---|---|
| medium | 900000 | 0.550 | e09 | yes | 12 | 71 | [medium-900000.jsonl](grok-agent/medium-900000.jsonl) |
| medium | 900001 | 0.530 | e05 | yes | 13 | 81 | [medium-900001.jsonl](grok-agent/medium-900001.jsonl) |
| medium | 900002 | 0.800 | e04 | yes | 5 | 34 | [medium-900002.jsonl](grok-agent/medium-900002.jsonl) |
| medium | 900003 | 0.720 | e10 | yes | 7 | 43 | [medium-900003.jsonl](grok-agent/medium-900003.jsonl) |
| medium | 900004 | 0.760 | e09 | yes | 8 | 49 | [medium-900004.jsonl](grok-agent/medium-900004.jsonl) |
| hard | 900000 | 0.000 | (none) | n/a | 14 | 91 | [hard-900000.jsonl](grok-agent/hard-900000.jsonl) |
| hard | 900001 | 0.755 | e09 | yes | 7 | 52 | [hard-900001.jsonl](grok-agent/hard-900001.jsonl) |
| hard | 900002 | 0.780 | e23 | yes | 9 | 61 | [hard-900002.jsonl](grok-agent/hard-900002.jsonl) |
| hard | 900003 | 0.725 | e03 | yes | 11 | 73 | [hard-900003.jsonl](grok-agent/hard-900003.jsonl) |
| hard | 900004 | 0.575 | e19 | yes | 11 | 74 | [hard-900004.jsonl](grok-agent/hard-900004.jsonl) |

**Mean score:** medium 0.672, hard 0.567, overall 0.620. 9 accusations, 9 correct, 0 wrong; 1 deliberate non-accusation (hard 900000).

## Strategy
- Identify the decoy from angry channel posts (`search_messages`) and exclude it.
- Use day-1 V drops and the recipient sets of leaked documents (intersection of department pairs) to narrow the mole to one department.
- Plant one canary per day with one recipient per variant (or two per variant on hard, max 2 labels), so the careful mole's pick weight stays high and any canary leak names the mole exactly.
- Fallback: restrict half the suspects and watch V drops and leaked-document recipients once the restricted group's 3-day leak window has emptied.
- Accuse only on hard evidence; otherwise accuse only if P(correct) > 1/(1+V). Hard 900000 ended without an accusation at ~53% confidence.

Transcripts are JSON lines `{ts, tool, args, isError, result}`, one per MCP tool call (client-side `init` excluded).

## Per-episode rationale

### medium 900000
- Used leaked-document recipient sets (intersection) plus the decoy's angry #finance messages to cut 20 suspects to 2 (e09, e12) by day 6.
- Ran restriction experiments and watched V drops for leak days (ambiguous), then planted a two-recipient canary with distinct variants (e12:A, e09:B).
- Canary c9 surfaced with variant B on day 12, so I accused e09 at V=0.55 (hard evidence, P≈1).

### medium 900001
- Leaked-doc recipients plus pair/singleton canaries cut the field to Sales, then canary c2 (variant B) leaked, leaving e13 vs e05 by day 6.
- Restricted e05 on day 8 so it stopped receiving new docs; once its last eligible docs aged out of the 3-day window, it could no longer leak.
- Leaks (visible immediately as 0.04 V drops) stopped for 3 straight days while unrestricted e13 kept fresh docs (P≈1/64 if e13), so I accused e05 at V=0.53.

### medium 900002
- Day-1/2 leak (d1-3 Project Tundra roadmap) restricted the mole to Sales+Legal; the decoy (e05, angry #legal posts) was excluded, leaving 8.
- Planted one canary per day with three single-recipient variants covering those 8 suspects (high pick weight under the careful mole, exact identification).
- Canary c4 surfaced on day 5 with variant C (only e04), so I accused e04 immediately at V=0.80.

### medium 900003
- Day-1 V drop showed a leak while Legal held no documents (Legal out); leaks d2-2 and d1-2 then pinned the mole to Engineering, minus the decoy e13 (angry #engineering posts): 4 suspects.
- Kept planting one canary per day with single-recipient variants for each suspect; on day 6 restricted two suspects as a backup leak-stop test.
- Canary c3 surfaced with variant C (only e10) on day 7, so I accused e10 at V=0.72.

### medium 900004
1. The decoy was e13 (angry posts in #sales). The day-1 V drop and the first leak, d1-3, narrowed the suspects to Sales and Legal.
2. Single-recipient canaries on days 1-4 found no leak, but the leak of real document d3-4 ruled out all of Legal, leaving e09 and e02.
3. I restricted e02 on day 5. Then d7-2, sent to e09 but not to e02, leaked, so I accused e09 on day 8.

### hard 900000
1. The decoy was e01 (angry posts in #finance). Leaked-document recipients narrowed the mole to Research, 7 people. Two-person canaries from days 1-6 and a company-wide canary (whose careful-mole weight is 0) never leaked.
2. I restricted {e04,e07,e09} on day 9. There were no leaks on days 10-12, which favoured that group about 70/30. Then I unrestricted only e04 on day 13 and saw a leak, which cleared e07 and e09.
3. The final posterior for e04 was about 53%, which is below the break-even of P > 1/(1+V) ≈ 0.70, so I deliberately didn't accuse (expected value of accusing was about -0.24).

### hard 900001
1. The decoy was e29 (angry posts in #research). Leaks of d1-1 (Engineering+Legal) and d2-2 (Finance+Legal) narrowed the mole to the 8 people in Legal by day 5.
2. I planted a two-recipient, two-variant canary every day, and on day 5 I restricted half of Legal as a backup split test.
3. Canary c4 (e12:A, e09:B) leaked as variant B, which proves it was e09. I accused e09 on day 7.

### hard 900002
1. The decoy was e03 (angry posts in #legal). The leaks of d1-3 (Engineering+Finance) and d1-2 (Engineering+Sales) narrowed the mole to the 5 people in Engineering.
2. Engineering received few new documents, so the mole's pool of leakable documents was small and my two-recipient canaries made up a large share of it.
3. Canary c6 (e00:A, e23:B) leaked as variant B, which proves it was e23. I accused e23 on day 9.

### hard 900003
1. The decoy was e12 (angry posts in #engineering). The leaks of d1-2 (Research+Legal) and d3-2 (Engineering+Legal) narrowed the mole to the 3 people in Legal.
2. From then on I planted a two-recipient canary every day, rotating among e03, e17 and e27 so that any leak would identify one person.
3. Canary c7 (e27:A, e03:B) leaked as variant B, which proves it was e03. I accused e03 on day 11.

### hard 900004
1. The decoy was e20 (angry posts in #research). The leaks of d1-3 (Finance+Sales) and d1-2 (Finance+Research) narrowed the mole to the 4 people in Finance.
2. I restricted e01 and e10 on day 6. A leak on day 9, when neither of them held any document still young enough to leak, cleared them both.
3. Canary c7 (e22:A, e19:B) leaked as variant B, which proves it was e19. I accused e19 on day 11.
