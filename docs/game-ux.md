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
- Initial wireframes and screen flow committed.
- Step 1: Title Screen + Top HUD + Office Employee Cards + Evidence Feed.
- Step 2: Accuse Dialog with Certainty Slider and Live EV / Break-even Math.
- Step 3: End Screen with 3D Mole Card Flip, Honest Scoreboard, Regret Analysis, and Share Link.
- Step 4: Canary Planting Wizard modal with A/B/C cohorts and split helpers.
- Step 5: Guided Tutorial with coach marks and local storage persistence.
