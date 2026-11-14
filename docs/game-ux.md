# Canary Browser Game UX Specification & Architecture

This document defines the screen flow, visual hierarchy, user journey, and implementation plan for the Canary browser game in `game/`.

---

## 1. High-Level Screen Flow

```
                  ┌────────────────────────────────────────┐
                  │              TITLE SCREEN              │
                  │  - One-line premise                    │
                  │  - Loading engine progress bar         │
                  │  - [Play] / [Tutorial] / [Seed Input]  │
                  │  - ?seed=NNNN & ?demo=1 support        │
                  └───────────────────┬────────────────────┘
                                      │
                         [Play] or [Start Tutorial]
                                      │
                                      ▼
                  ┌────────────────────────────────────────┐
                  │          INVESTIGATION SCREEN          │
                  │ ┌────────────────────────────────────┐ │
                  │ │ TOP HUD: Day X/N · Pips · V · Leaks│ │
                  │ └────────────────────────────────────┘ │
                  │ ┌──────────────────┬─────────────────┐ │
                  │ │ LEFT: OFFICE     │ RIGHT: EVIDENCE │ │
                  │ │ - Team cards     │ - Timeline feed │ │
                  │ │ - Suspect tags   │ - Leak cards    │ │
                  │ │ - Action drawer  │ - Delayed flags │ │
                  │ └──────────────────┴─────────────────┘ │
                  │  [Plant Canaries]  [Next Day]  [Accuse]│
                  │  [Collapsed Expert Tool Console]       │
                  └─────────┬───────────────────┬──────────┘
                            │                   │
                     [Plant Canaries]       [Accuse]
                            │                   │
                            ▼                   ▼
                  ┌───────────────────┐ ┌───────────────────────────────┐
                  │  CANARY WIZARD    │ │        ACCUSE DIALOG          │
                  │ - 2-3 variants    │ │ - Suspect selector            │
                  │ - A/B/C assignment│ │ - Certainty slider (0-100%)   │
                  │ - Split evenly btn│ │ - Break-even math (p* = 1/1+V)│
                  │ - Whole-co warning│ │ - [Accuse] or [Abstain (0.00)]│
                  └───────────────────┘ └───────────────┬───────────────┘
                                                        │ (Episode ends)
                                                        ▼
                                        ┌───────────────────────────────┐
                                        │          END SCREEN           │
                                        │ - Mole Reveal Card Flip       │
                                        │ - Scoreboard (You vs Solver   │
                                        │   vs Benchmark Means)         │
                                        │ - "Your Call" Regret Analysis │
                                        │ - "You Were Fooled" Callout   │
                                        │ - Action Replay Timeline      │
                                        │ - [Play Again] [Copy Result]  │
                                        └───────────────────────────────┘
```

---

## 2. Screen Wireframes

### Screen 1: Title Screen
```
+------------------------------------------------------------------------------------+
| 🐦 CANARY : CATCH THE MOLE                                    [ ?seed=4127 ?demo=1]|
|                                                                                    |
| "Someone in this company is leaking secrets. Every leak costs money.               |
|  Find the mole, or have the sense to say you don't know."                          |
|                                                                                    |
|   ┌────────────────────────────────────────────────────────────────────────────┐   |
|   │ Loading real benchmark engine into Pyodide sandbox...               [92%]  │   |
|   └────────────────────────────────────────────────────────────────────────────┘   |
|                                                                                    |
|   [ 🚀 PLAY INVESTIGATION ]          [ 🎓 HOW TO PLAY (TUTORIAL) ]                 |
|                                                                                    |
|   Investigation Seed: [ 4127 ] [🎲 Random]    Difficulty: Medium (Dev Seeds 3000+) |
|                                                                                    |
|   THREE RULES OF THE BENCHMARK:                                                    |
|   1. Plant Canaries: Tag sensitive memos with subtle variants (A, B, C).           |
|   2. Mind the Delay: Leaks surface on the rival wire 1–3 days AFTER they happen.   |
|   3. Accuse or Abstain: A correct catch saves V; wrong costs -1.00; abstain is 0. |
+------------------------------------------------------------------------------------+
```

### Screen 2: Investigation Screen
```
+------------------------------------------------------------------------------------+
| DAY 4 / 14 [=====>        ] | ACTIONS: ● ● ● ● ○ ○ ○ ○ (4 left) | V = 0.880 | LEAKS: 2|
+------------------------------------------------------------------------------------+
| THE OFFICE (20 Staff)              | EVIDENCE FEED (Newest on Top)                 |
| [📋 Survey Office] [🐦 Plant Trap] | Filter: [All] [Leaks] [Interviews] [Logs]    |
|                                    |                                               |
| ENGINEERING                        | ⚠️ LEAK DETECTED (Day 3)                      |
| +--------------------------------+ | Doc: c2-memo · Leaked Variant: [B] (Amber)   |
| | e00  Marcus Vance   [🔴 Suspect] | NOTE: Leaks surface with 1–3 days delay!      |
| | Senior Architect    [Canary: B]| This document leaked between Day 1 and Day 3.  |
| | [Interview] [Logs] [Restrict]  | --------------------------------------------- |
| +--------------------------------+ | 🗣️ INTERVIEW: e03 Elena Rostova (Day 2)      |
| +--------------------------------+ | Topic: Workload                               |
| | e01  Aria Chen      [🟢 Cleared] | Statement: "I was reviewing the Q2 audits...  |
| | Backend Engineer    [Canary: A]| Signal: Cooperative                           |
| +--------------------------------+ | --------------------------------------------- |
| FINANCE                            | 📜 ACCESS LOGS: Day 1-2                       |
| +--------------------------------+ | 3 records retrieved (1 after-hours flagged)  |
| | e04  Julian Ward    [⚪ Unsure] |                                               |
| +--------------------------------+ |                                               |
+------------------------------------+-----------------------------------------------+
| [⏩ NEXT DAY (N)]                  | [🚨 ACCUSE SUSPECT (A)]     [🛠️ Expert Console]|
+------------------------------------------------------------------------------------+
```

### Screen 3: Accuse Dialog (The Teaching Moment)
```
+------------------------------------------------------------------------------------+
| 🚨 ACCUSE SUSPECT OR CLOSE CASE                                                [X] |
|                                                                                    |
| Target Suspect: [ e00 - Marcus Vance (Engineering)                     ▼ ]         |
|                                                                                    |
| How sure are you?                                                                  |
| [0% ------------------------●----------------- 100%]  Current: 65%                 |
|                                                                                    |
| BREAK-EVEN MATHEMATICS:                                                            |
| Current Company Value: V = 0.880                                                   |
| Break-even Certainty:  p* = 1 / (1 + V) = 53.2%                                   |
| Expected Value:        EV = p·V - (1 - p)·1.00 = (+0.22)                          |
| Value of Abstaining:   0.00                                                        |
|                                                                                    |
| [✓ Certainty (65%) > Break-even (53.2%). Accusing is statistically positive EV.]  |
| (If p < p*: "At this certainty, not accusing scores better on average. This is    |
|  exactly the mistake frontier AI agents make: gambling instead of abstaining.")    |
|                                                                                    |
| [ 🚨 CONFIRM ACCUSATION ]     [ 🛡️ CLOSE CASE WITHOUT ACCUSING (ABSTAIN: 0.00) ]  |
+------------------------------------------------------------------------------------+
```

### Screen 4: End Screen
```
+------------------------------------------------------------------------------------+
| 🕵️ INVESTIGATION VERDICT: CASE CLOSED                                             |
|                                                                                    |
| +-------------------------+                                                        |
| | [ FLIPPING MOLE CARD ]  |  THE TRUE MOLE WAS:                                    |
| | e00 - Marcus Vance      |  Marcus Vance (Lead Architect, Engineering)            |
| | Engineering · Level 2   |  "Marcus secretly exfiltrated project files to rivals" |
| +-------------------------+                                                        |
|                                                                                    |
| BENCHMARK SCOREBOARD                                                               |
| ┌────────────────────────────────────┬────────────┬────────────────────────────┐   |
| │ Agent / Operator                   │ Score      │ Telemetry / Details        │   |
| ├────────────────────────────────────┼────────────┼────────────────────────────┤   |
| │ You (Human Investigator)           │ +0.840     │ Accused e00 (CORRECT) Day 6│   |
| │ Reference Solver (Live same seed)  │ +0.880     │ Bayes Policy, accused Day 5│   |
| │ gemini-4-carbon (benchmark avg)    │ +0.503     │ Harbor judge benchmark mean│   |
| │ codex:gpt-5.5 (benchmark avg)      │ +0.401     │ Benchmark evaluation mean  │   |
| │ heuristic baseline                 │ +0.650     │ Canary bisection reference │   |
| │ logs_only baseline                 │ -1.000     │ Fooled by framing logs     │   |
| └────────────────────────────────────┴────────────┴────────────────────────────┘   |
|                                                                                    |
| YOUR CALL & DECISION REGRET:                                                       |
| You estimated certainty at 65% against break-even 53.2%. You made the right call.  |
|                                                                                    |
| ACTION REPLAY TIMELINE:                                                            |
| Day 1: Surveyed office -> Day 2: Planted Canary c2 -> Day 3: Leak detected -> ...  |
| (Reference solver accused on Day 5).                                               |
|                                                                                    |
| [ 🎲 Play Again (New Seed) ]  [ 🔄 Replay Same Seed ]  [ 📋 Copy Shareable Link ]  |
+------------------------------------------------------------------------------------+
```

---

## 3. Keyboard Shortcuts & Controls
- `N`: Advance Day
- `P`: Open Canary Wizard
- `A`: Open Accuse Dialog
- `?`: Toggle Field Guide / Tutorial

---

## 4. Work Completed & Self-Review Log

### Implementation Summary
- **Step 1: Title Screen & HUD**:
  - Premise banner: *"Someone in this company is leaking secrets. Every leak costs money. Find the mole, or have the sense to say you don't know."*
  - Pyodide real progress bar with stage reporting and error handling.
  - Sticky Top HUD with 8 action pips (`.pip.active` / `.pip.spent`), dynamic calendar bar, draining company value $V$ indicator, and leak counter.
  - URL query parameters supported: `?seed=NNNN` and `?demo=1` (activates `.demo-mode` with enlarged typography for video recording).
- **Step 2: The Office & Evidence Feed**:
  - Employee cards grouped into teams by Department (Engineering, Finance, Sales, Legal, Research) with distinct team colors.
  - Unsurveyed callout guiding the player to initiate `list_employees` without automatic/hidden calls.
  - Interactive tags on cards: `Suspect 🔴` / `Cleared 🟢` / `Unsure ⚪` (client-side only).
  - Selected employee dossier drawer with direct action buttons (`Interview`, `Access Logs`, `Search Messages`, `Restrict Access`, `Accuse`).
  - Evidence feed showing chronological intelligence cards with leaked canary variant colors and explicit delayed leak warnings ("surfaces with 1–3 days delay").
- **Step 3: Accuse Dialog (The Teaching Moment)**:
  - Certainty slider from 0% to 100%.
  - Live calculations: current Company Value $V$, break-even threshold $p^* = 1 / (1 + V)$, expected value $EV(accuse) = p \cdot V - (1 - p) \cdot 1.00$ vs $EV(abstain) = 0.00$.
  - Dynamic educational callout: when $p < p^*$, amber warning explaining that abstaining is mathematically superior, mirroring frontier LLM decision errors.
  - Visible "Close case without accusing (Abstain: Score 0.00)" choice.
- **Step 4: Canary Planting Wizard**:
  - Modal with document title, quick split helpers (3-Way, 2-Way, Department split), and interactive employee chips.
  - Soft warning if all employees are assigned to a single variant.
  - Variant badges displayed on employee cards upon planting.
- **Step 5: End Screen & Post-Mortem**:
  - 3D CSS card flip revealing the true mole.
  - Honest scoreboard: You (live), Reference Solver (live), Gemini-4-carbon (benchmark mean), Codex:GPT-5.5 (benchmark mean), Baselines. Explicit honesty disclaimer.
  - "Your Call" decision regret analysis comparing entered certainty to $p^*$.
  - "You Were Fooled" callouts if the player cleared the mole or accused the decoy/framed colleagues.
  - Action replay timeline with solver accusation day marker.
  - Shareable link generator and JSON actions transcript download.
- **Step 6: Tutorial & Controls**:
  - 6-step guided coach marks overlay on seed 3000.
  - Keyboard shortcuts (`N`, `P`, `A`, `?`, `Esc`).

### Self-Review & Test Verification
1. **Pytest & Parity Test Suite**:
   - `pytest -s tests/test_game.py` passed all 17 tests (15 standard + 2 browser Pyodide parity tests).
   - `node game/tests/parity.mjs` executed and verified browser-CPython replay determinism.
2. **Deterministic Seed Verification**:
   - **Seed 3000**:
     - Mole: `e09`
     - Action flow: Survey office (20 staff) -> Plant 3-way canary `c1` -> Interview `e00` -> Access logs `e00` -> Advance Day -> Check leaks -> Accuse `e09` -> Correct verdict (+0.99).
     - Solver on Seed 3000: Accused Day 10, Score: +0.79.
   - **Seed 4127**:
     - Mole: `e04`
     - Action flow tested: Full bisection and advance to Day 14.
     - Abstain path tested: Player closing case without accusing achieved score 0.00 (`end_reason: horizon`).
     - Solver on Seed 4127: Abstained at horizon (Score: 0.00).
   - **Seed 9999**:
     - Mole: `e14`
     - Action flow tested: Full game run to accuse `e14`, Score: +0.99.
     - Solver on Seed 9999: Accused Day 11, Score: +0.88.
3. **HTTP Server Smoke Test**:
   - Validated static assets served via local HTTP server on port 8888 (`/index.html`, `/app.js`, `/style.css`, `/reference.json`). All returned HTTP 200.
4. **Parity & Constraints Adherence**:
   - Zero hidden calls to `status` or other tools; budget is strictly preserved.
   - Public seed range restricted to 3000–9999.
   - No truth leaked to client before game conclusion.
   - Reference scores honestly labeled as benchmark averages.
