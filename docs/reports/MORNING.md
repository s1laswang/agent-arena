# MORNING: Canary overnight report (for Silas, 08:30 Sat 14 Nov)

Branch `justSilas` · `make test` **517 passed**, 4 skipped · CEO log: `docs/reports/CEO.md` (every decision, with timestamps).

## 1. Needs YOU (in priority order)
1. **API spend: decide.** OpenAI API spend overnight is **≈ $260** (est.), above my $150 cap. AGENTS was not tracking spend until about 03:30, and part of the Codex cost depends on caching. **Check the OpenAI billing dashboard.** All API runs are stopped. Full breakdown: `docs/reports/gap.md` → Spend.
2. **Approve the v1.3 headline measurement** (~$3 smoke, then ~$90 for a paired 10+10 run: our fixed agent loop vs Codex over MCP), **or** use **Gemini free credits** as the frontier agent instead. The commands are in §7.
3. **Paste `GEMINI_API_KEY`** into `~/junction-aimo-team/agent-arena/.env`, then run §7.
4. **Optional credentials:** `codex login` with ChatGPT (subscription instead of API billing), or top up OpenCode's ChatGPT workspace (credits depleted; resets in ~6 days).
5. **Questions for the AfterQuery mentors (Daksh, Ved):**
   - the exact Harbor task format, and the number of tasks per submission;
   - which model the judges run;
   - whether a sidecar MCP container is allowed;
   - whether **negative rewards are OK** (we score −1 for a wrong accusation);
   - whether a scripted solver counts as the "stronger reference run".
6. **09:00 bake-off:** the Grok bake-off (`origin/justSilas-grok-bakeoff`) scored Blind Spot (Ivar) 69, Canary 56 and Sleeper 43. It was written at ~02:30, **before** we shipped `make reproduce`, the Harbor sidecar, the gap report, v1.3 and #25. **Re-run the Grok bake-off prompt on the current tips before deciding.** Ivar has added "blind frontier results" since.
7. **Sky run:** your `sky` task **43143_4** (`w0625-c1`, the worst run) is paused (`requeuehold`) for our training job. I release it when J4 ends (≤08:17). If it's still held: `ssh freighter scontrol release 43143_4`.

## 2. The gap (rubric 30)
Scoring: correct = remaining company value V, wrong = −1, no accusation = 0.

| tier version | medium: frontier / solver | hard: frontier / solver |
|---|---|---|
| v1.2 (true V visible daily), gpt-5.5, n=20+20 | 0.600 / 0.690 = **87%** | 0.500 / 0.584 = **86%** |
| v1.2, Grok over MCP (judge seeds), n=5+5 | 0.672 = 97% | 0.567 = 97% |
| **v1.3 (current)**, gpt-5.5 in-process, **n=9+5** | 0.319 / 0.670 = **48%** | −0.003 / 0.553 = **≈0%** |
| v1.3, Codex gpt-5.5 over MCP, n=1+2 | 0.53 | 0.59 |

**Honest read:** v1.2 opened no gap. Frontier agents read the true V in `status` every day, which defeated the leak delay; Grok's own report says so. v1.3 shows only *known* V. On v1.3 the reference barely moves, while in-process gpt-5.5 collapses. **But:**
- the sample is small;
- our in-process agent loop was handicapped (it kept only the last 40 turns; fixed overnight, with zero API cost);
- the judges'-shape Codex runs (n=3) are close to the solver.

→ **The size of the gap is the #1 open question this morning.** Fallback if v1.3 + the fixed loop still shows frontier ≥85%: v1.4 = a longer horizon plus more pipelined canaries (a pure parameter change, agreed with ENV).

Baselines (v1.3, 30 fresh secrets, README): solver medium +0.64 / hard +0.55; heuristic −0.06 / −0.30; stop-early ≈ −0.9; do-nothing exactly 0. A Grok-tactics scripted policy is beaten by the solver by +0.17 (medium) / +0.23 (hard), paired.

## 3. Why agents fail (rubric 30)
- Per-decision regret: `results/regret_gpt-5.5-v1.2.md`, `results/regret_*-v1.3.md`.
- **Dominant failure: premature accusation.** Day-14 gambles at a low posterior: mean P(correct) at accusation is .78 for gpt-5.5 vs .95–.96 for the solver. On v1.3 all 4 wrong accusations were made at P = .18–.43. **The agent never abstains,** even though the EV is negative below P = 1/(1+V). Grok did abstain once, so the information is available.
- Smaller costs: ignored_delay, uninformative_canary.
- Annotated example: medium seed 5 in `gap.md` (a single-variant canary on day 1, late canaries under delay, a 50/50 accusation at day 14 → −1).
- Fairness:
  - every input the solver uses is public, and its accusation rule is computable from the instructions;
  - the text-only probe is at chance;
  - the difficulty curve: `results/difficulty_curve.png`.
- Human playtest is ready: `make play TIER=medium NAME=<you>`. Teammates should play it this morning, since human scores strengthen this section.

## 4. Reward integrity (rubric 25)
- 41 attempts in `docs/EXPLOITS.md`, and every closed exploit has a regression test. Fixed overnight:
  - #1 stop-early (wrong = −1);
  - #10 logs-only solve;
  - **#24 judge worlds regenerable from public code** (found independently by us and by the Grok judge run) → fail-closed secret;
  - **#27 /proc environ leak** (the Grok judge run called it #25) → `*_FILE` secrets + Harbor sidecar;
  - #23 public dev/train seeds can be regenerated → the server serves only judge and held-out seeds unless `CANARY_ALLOW_DEV=1`.
- **Still open:**
  - the Grok judge re-run on the final tip (`grok-judge` was last updated at 00:28);
  - the Gemini exploit hunter (needs the key plus the `canary.llm` wiring in `hunter.py`);
  - the Codex hunts are weak evidence, since moderation cut 8 of 9 runs.
- `make hunt` (no keys, ~1 min): every track reports a best non-solver score of 0.000 with 0 violations.
- Harbor: server sidecar (uid 10001, build-time secret as a 0600 file); `check_isolation.sh`: 11 checks, 0 findings; oracle via Harbor: solver 0.79, do_nothing 0.0, stop_early −1.0.

## 5. Craft (rubric 15)
- `make setup && make reproduce`: about 5 s, no keys. The output goes to gitignored `results/latest/`, so a judge's clone stays clean. Reported runs are grouped by tier version.
- The 05:00 fresh-clone check passed (two secrets, harbor lint, byte-identical exact mode). CI is green on GitHub Actions.
- README rewritten for judges (uv install line, one command, expected numbers, rules, `make hunt`, Harbor, grounding).
- Harbor package: `harbor/README.md`. A real `harbor run -a opencode` needs `OPENAI_API_KEY` on the host.
- Grok deliverables (cloud bots, on `origin/justSilas-grok-*`, **not yet merged**):
  - `site` (offline presentation dossier with live replay);
  - `viewer`;
  - `pitch` (deck + judge handout PDF);
  - `research` (fact-checked grounding).

## 6. Small model (tiebreaker)
J4: LoRA of Qwen2.5-1.5B on a V100, 450 steps (≈5% of an epoch, time-boxed), trained on v1.3 solver episodes. Preview (n=1 episode per model, descriptive only):

| | base | LoRA |
|---|---|---|
| valid tool-call rate | .15 | **.98** |
| behaviour | repeats one call, stuck on day 1 | full 14 days in the solver's rhythm |
| solver action-type agreement | 0.00 | **.94** |
| accuses | no | **no** (score 0) |

It learned the protocol and the investigation rhythm, not the commit decision (accuse turns are ~1/70 of the training tokens). **Saturday v2 (approved):** dense 4k windows plus upweighted accuse turns; the J3 v2 data (v1.3) is ready on FR8. The final J4 table is in `docs/reports/fr8.md` (eval ended ≤08:17). The adapter is synced to `data/fr8/j4/`.

## 7. Gemini switch-on (prize: Gemini essential)
After pasting `GEMINI_API_KEY` (all Gemini calls run on the **Mac**; FR8 compute nodes have no internet):
```bash
cd ~/junction-aimo-team/wt/justSilas   # or any checkout of justSilas
make gemini-check
uv run --python 3.12 --extra llm --extra dev python -m canary.agents.play --agent gemini:<model> --tier medium --seeds 0-9 --out data/runs/committed/v1.3/gemini/medium   # frontier family #3, free credits
make clash        # Gemini mole vs investigators (arena) + scenario designer
make worlds PROVIDER=gemini   # Gemini-written company text for judge seeds (mechanics unchanged)
```
**Honest Gemini status:** every Gemini path is built and tested against a stub, and none has run with a key yet. Mole Forge works (solver-constrained), but the moles evolved overnight (against scripted investigators) are **not** harder for gpt-5.5. The real step is a Gemini mutator plus Gemini/gpt-5.5 fitness.

OpenAI runs (after you approve spend): see `docs/reports/agents.md` → "Morning commands" (smoke, then a paired 10+10 run of the fixed loop vs Codex).

## 8. Org state
- **Live:** FR8 (J4 eval wrap-up), INTEGRITY (idle), HARNESS (stuck in "waiting" much of the night; its work was covered by CEO-launched engineers).
- **Ended after finishing:** ENV, AGENTS. Relaunch prompts are in `docs/agents/*.md`.
- **Grok re-runs:** the judge simulator and reproducer prompts from last night, plus the v1.3 Grok-agent prompt in `docs/reports/agents.md`. Run them on the current tip.
