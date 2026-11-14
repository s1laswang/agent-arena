# Why The Sleeper, and not Canary

One page for the humans. Numbers: `make eval` (momin 5634505 rehearsal, SCRIPTED, rerun on 814a723 NOT FOUND, killed under load) or the bake-off file `docs/parallel-envs.md` (origin/justSilas-grok-bakeoff2 3f91fe4, Silas's side). No model of ours has run: REAL cells NOT FOUND (lead-lab pending).

## Three honest answers

1. Different question. Canary asks one accusation from one head of security. The Sleeper asks whether eight agents finish the work and stop an insider without accusing an innocent. The reward has to hold both halves. Evidence: no-sleeper days exist, staff 1.000 there and 0.062 on sleeper days (SCRIPTED, make eval on 5634505), so the loss is decisions, not unfinished work.
2. Canary's own gap is inconclusive. Its report: Codex gpt-5.5 over MCP is 106% of the solver on hard (n=11, CI 91..136%) and the gap does not hold there (docs/parallel-envs.md, Silas's report, not ours). We do not have a better number. Our claim is only that the gap is measured the same way, paired days and a reference that never reads the hidden sleeper identity. Our real gap: NOT FOUND (lead-lab pending). If it does not show, we say so.
3. Every loss is named. 39 of 39 staff losses carried a named mistake and 33 of 39 flip when one seat follows the procedure (SCRIPTED run, earlier rehearsal, not recomputed on 814a723). Canary's report says premature accusation is 97 to 99% of value lost, which is one failure mode. Ours has several.

## Weaknesses fixed

- trust_all: was 0.800 at one point, now 0.000 (make eval). The 0.35 in the README was stale.
- do_nothing in a non-judge seat scored 1 on some days. Verifier check added, 0 in every seat (SCRIPTED).
- finance_ap seat oracle: 0.400 then, 0.800 overall and 0.750 on needs-seat days now (bake-off file, 07e17ee). Not 1.000.

## Weaknesses still open (bake-off file, scored 51/100, last place)

- No real frontier run yet. Gap 10/30 for that reason.
- Four days (1003, 1008, 1013, 1018) the oracle scores 0 in the finance_ap seat.
- `reward.txt` rewritable under a shared verifier with `chmod 777 /logs` (xfail test_x73), `harbor lint` fails, and the sleeper seat is derivable from public code.
- pytest 20 failed at 07e17ee, docs counts differ from make eval. Recheck on 814a723: NOT FOUND.

## What we say if asked "why not Canary"

"Canary is a good test with a real but inconclusive gap. We are the multi-agent, two-sided version. Our gap is NOT FOUND until the keyed run finishes, and we will say that rather than guess."
