# Gap report: frontier agent vs reference (DRAFT, tiers v1 partials)

> Status: **directional only**. The official measurement (gpt-5.5 20+20 dev seeds, OpenCode gpt-5.6-sol 5+5 over MCP) runs on the frozen tiers (~07:00) and replaces these tables. Reproduce: `python -m canary.analysis.gap --runs data/runs/committed`, `python -m canary.analysis.accuse --runs ...`, `python -m canary.analysis.tags --runs ...`.
> Scoring v0.3: correct = V at accusation, wrong = −1, none = 0.

## Gap table (tiers v1, dev seeds; references = pre-fix solver on seeds 0–9)
| tier | agent | n | score ± 95% CI | accuracy | accuse day | % of solver |
|---|---|---|---|---|---|---|
| medium | solver (reference) | 10 | 0.475 ± 0.211 | 0.70 | 9.1 | 100% |
| medium | **gpt-5.5** | 3 | 0.067 ± 1.06 | 0.67 | 11.7 | **14%** |
| medium | heuristic | 10 | −0.038 | 0.60 | 11.2 | – |
| medium | stop-early / do-nothing | 10 | −1.00 / 0.00 | | | |
| hard | solver (reference) | 10 | 0.638 ± 0.146 | 0.90 | 10.2 | 100% |
| hard | **gpt-5.5** | 4 | 0.719 ± 0.125 | 1.00 | 9.2 | **113% ⚠** |
| hard | heuristic | 10 | −0.661 | 0.20 | 11.7 | – |

**Kill switch tripped on hard** (sent to the CEO and ENV). Cause found (see below): the reference's canary partition ignores the careful mole's group-size weighting. A fix is in progress at ENV; the official numbers come after the freeze.

## Old tiers (v0, for the record)
gpt-5.5 got 97% of the solver on medium (n=3) and 111% on hard (n=3). Every accusation was justified (P(accused)=1.0 under the solver's belief), so the old tiers handed out certainty → tiers v1.

## Why gpt-5.5 matched the reference on hard (diagnosis)
- **Careful mole × canary size:** the solver split ~20 of 30 staff (canary leak weight ×0.33); gpt-5.5 used small groups (6 staff, ×0.8) and fresh labels on narrowing subsets, so its canaries actually got leaked and it accused on day 6 (seeds 5, 7).
- Its accusations were all justified (P(accused) ≥ 0.96): no luck involved.

## Annotated failure: medium seed 5 (gpt-5.5, score −1.0)
| day | action | belief P(top) | note |
|---|---|---|---|
| 1 | canary to 3 people, **one variant** | 0.05 | a single label splits nobody: zero information |
| 2–5 | 2-variant canaries of 6–10 people; two leaks surface | 0.05 → 0.26 | reasonable bisection |
| 5–9 | **~14 interviews** (contacts_outside, recent_documents, …) | 0.26 → 0.27 | interviews are weak (LR 1.3, documented); 14 slots buy ~nothing |
| 6–10 | 1-vs-1 and 2-vs-2 canaries | ≈0.27 | small groups, but no leak lands |
| 11 | narrowed to **e02 vs e14** | 0.51 | |
| 12–13 | e02/e14 canaries again | 0.51 | with delay 1–3, a canary planted on day 12–13 likely can't surface before day 14 |
| 14 | 4 repeated interviews (`budget_waste`) → **accuse e02** at P=0.50 | 0.50 | **wrong → −1.0**. Tags: `premature_accusation`, `ignored_delay`; regret 0.18 V on the final step |

What a better play looked like: the same 2-way split on days 9–10 (before the delay window closes) would have resolved e02 vs e14 in time. Doing nothing at the horizon (0) also beats a coin flip under −1 scoring: the expected value of a 50/50 accusation is 0.5·V − 0.5 < 0.

## Failure-mode counts
_Filled from `canary.analysis.tags` after the official run._

## Hint ablations
_Pending: `canary.agents.ablate` on the top-3 tags after the official run._
