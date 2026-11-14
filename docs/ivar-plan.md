# Ivar's Plan: AfterQuery Canary Deliverables

**Author:** Ivar (assigned by Silas, team lead)  
**Branch:** `ivar/aq-game` (derived from `origin/justSilas-harness2`)  
**Targets:** Junction 2026 / AfterQuery "Break the Agent" + DeepMind "Best Use of Gemini API"  
**Created:** Sat 14 Nov 2026  

---

## 1. Objectives & Scope

Deliver three core workstreams without modifying environment or reward rules under `canary/`:

1. **Browser Game UX (`game/`)**:
   - Deliver a polished, self-contained Pyodide browser game running the real `canary` package.
   - Target player experience: understand mechanics and finish an episode in ~10 minutes.
   - Core improvements: Onboarding tutorial/cheatsheet, organized tool layout, interactive employee directory/picker for canaries, real-time status banner (Day, V, action caps) without extra tool calls, rich readable activity cards (leaks, logs, interviews), and an end-screen comparing **Player vs. Gemini (gemini-4-carbon) vs. Bayesian Reference Solver** on the same seed.
   - Maintain strict parity: verify `tests/test_game.py` and `game/tests/parity.mjs` compatibility.

2. **10-Minute Video Script (`docs/VIDEO-SCRIPT.md`)**:
   - Peer-review presentation and demo script designed to capture full marks on the AfterQuery rubric (The Gap, Meaningful Difficulty, Reward Integrity, Craft) and showcase Gemini.
   - Narrative arc: Hook (real-world leaks & catastrophic failures) $\rightarrow$ The Canary Environment & Mathematical Rules $\rightarrow$ "Beat the AI" Interactive Demo $\rightarrow$ The Frontier vs. Reference Gap & "Failure to Abstain" Root Cause $\rightarrow$ Reward Integrity & 41 Exploits Overcome $\rightarrow$ Gemini's Essential Role & Small Model SFT $\rightarrow$ One-Command Reproducibility.
   - Grounding: every metric, score, CI, and count cited from committed results files (`results/judge_table.md`, `results/fresh_table_v1.4.md`, `harbor/README.md`, `docs/reports/gap.md`, `docs/EXPLOITS.md`). Unmeasured metrics clearly labeled as TODO.

3. **Human Biases & Organisational Research (`docs/research-biases.md`)**:
   - Synthesis of academic research on organizational behavior, cognitive biases, and insider threats.
   - Real-world failure and insider leak cases drawn strictly from `docs/FAILURE-RESEARCH.md` and `data/failures/*.json` (preserving all original URLs and verified citations) plus verified literature (Vuori & Huy 2016 on Nokia, Vaughan 1996 on normalization of deviance, Shaw & Fischer 2005 on insider threat psychology, Kahneman & Tversky on prospect theory and loss aversion).
   - Concrete behavioral mappings for Canary v3: modeling biased innocent employees (decoy venting, authority bias, noisy after-hours access), adaptive mole behaviors (evasion, framing, slow burn), and investigator failure modes (premature commitment, base-rate neglect).

---

## 2. Execution Phases & Milestones

| Phase | Milestone | Actions & Outputs | Verification Gate |
|---|---|---|---|
| **Phase 1** | **Roadmap & Baseline** | Commit `docs/ivar-plan.md` to `ivar/aq-game`. Confirm test suite baseline. | `python -m pytest tests/test_game.py` passes. |
| **Phase 2** | **Deliverable 3: Research** | Author `docs/research-biases.md` with 44+ sourced cases and academic foundations mapped to simulation specs. | Verify all source URLs and citations match `data/failures/*.json` and academic records. |
| **Phase 3** | **Deliverable 2: Video Script** | Author `docs/VIDEO-SCRIPT.md` (10-minute script with visual directions, speaker transcript, and verified metric citations). | Check every number against `results/` and `harbor/README.md`. |
| **Phase 4** | **Deliverable 1: Browser Game** | Upgrade `game/index.html`, `game/app.js`, `game/style.css`, create `game/reference.json` with Gemini/solver benchmarks, test build. | `python game/build.py` succeeds; `tests/test_game.py` green; no secret leakage. |
| **Phase 5** | **Synthesis & Review** | Update `docs/ivar-plan.md` with final delivery status, open items, and decisions for Ivar/Silas. | Final `git status` clean, all commits local on `ivar/aq-game`. |

---

## 3. Local Git Commit Strategy

- Commit Phase 1: `plan: initial roadmap in docs/ivar-plan.md`
- Commit Phase 2: `research: human biases in organisations and insider leaks (docs/research-biases.md)`
- Commit Phase 3: `docs: 10-minute peer-review video script with verified result citations (docs/VIDEO-SCRIPT.md)`
- Commit Phase 4: `game: enhance onboarding, tool controls, dashboard and end screen comparison in browser game`
- Commit Phase 5: `summary: update docs/ivar-plan.md with final deliverable review`

*Strict Rule:* Never `git push`. Keep branch on `ivar/aq-game`.
