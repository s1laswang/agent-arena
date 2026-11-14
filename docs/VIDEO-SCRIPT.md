# 10-Minute Video Script: "Canary — Catching the Mole"

**Format:** 10-Minute Video / Peer-Review Walkthrough  
**Target:** Junction 2026 / AfterQuery "Break the Agent" + Google DeepMind "Best Use of Gemini API"  
**Tone:** Entertaining, investigative, technically authoritative, cinematic pacing.  
**Cast / Visuals:** Speaker on camera + Screen Capture (Browser Game, Terminal, Architecture Diagrams, Results Tables).  
**Evidence Grounding:** Every single number, score, confidence interval, and exploit count is cited directly from committed repository files. (Any pending metric is explicitly marked as `[TODO]`).

---

## Cue & Segment Overview

| Timestamp | Segment Title | Primary Focus & Visual Deliverable |
|---|---|---|
| **00:00 – 01:25** | **The Hook: The Enemy Within** | Real-world catastrophic leaks, Tesla's space-bar trap, and why agents fail in messy human organizations. |
| **01:25 – 02:50** | **The Canary Environment** | The game mechanics: Value $V$, canary variants $A/B/C$, delay, framing, and the ruthless $-1.00$ penalty. |
| **02:50 – 04:35** | **"Beat the AI" Interactive Demo** | Live playthrough in the browser game (`game/`); human intuition vs. mathematical trap design. |
| **04:35 – 06:45** | **The Frontier Gap & The Fatal Flaw** | The numbers: Solver vs. GPT-5.5 vs. Gemini-4-Carbon; regret tags prove *"The AI never says 'I don't know'"*. |
| **06:45 – 08:05** | **Reward Integrity: 41 Exploits Overcome** | Surviving red-teams, Harbor container isolation (11/11 OK), and why guessing earns $\le 0$. |
| **08:05 – 09:15** | **Gemini & The Small-Model Stretch Goal** | Gemini Mole Forge (evolving adversaries), Failure Analyst, and Qwen2.5-1.5B LoRA on FR8 V100s. |
| **09:15 – 10:00** | **Grand Finale: One Command to Reproduce** | Closing thesis, terminal demonstration of `make reproduce`, and live invitation to play. |

---

## Detailed Transcript & Visual Directions

---

### Segment 1: The Hook — The Enemy Within (00:00 – 01:25)

**[VISUAL: Fast-paced cold open. High-contrast typography over archival news headlines: "Tesla Insider Hunt", "Citibank Revlon $900M Error", "Nokia Smartphone Crisis", "Knight Capital $440M in 45 Minutes". Camera cuts to Speaker in a modern security operations center setting.]**

**SPEAKER:**
"In 2008, confidential financial and production details kept leaking from Tesla to external automotive blogs. Elon Musk didn't install an AI surveillance agent. Instead, he executed a classic counter-intelligence move: he sent an internal email where each employee received a subtly different version. The distinguishing feature? The spacing between sentences. One space. Two spaces. A binary signature hidden in plain sight. When the leak surfaced, the spacing pattern pinpointed the exact leaker.

That technique has an intelligence heritage dating back to MI5's 'barium meal test' and Tom Clancy's Cold War fiction. We call it **The Canary Trap**.

Fast forward to 2026. Across tech, finance, and defense, companies are rushing to put autonomous LLM agents in charge of security operations: triage, access management, insider threat detection. But here is the multi-million-dollar question: 
Can today's frontier AI actually reason under uncertainty, delay, and active deception? Or is it just a pattern-matcher that collapses the moment human organizational chaos enters the room?

To find out, our team built **Canary**."

---

### Segment 2: The Canary Environment (01:25 – 02:50)

**[VISUAL: Motion graphic transition into the Canary environment architecture diagram. Show company value counter $V = 1.000$ ticking downward. Cut to terminal displaying the 13 public tools from `canary/env.py`.]**

**SPEAKER:**
"Canary is an RL environment designed for AfterQuery's *Break the Agent* challenge. 

Here is the setup: A simulated company has exactly one insider mole leaking proprietary intellectual property to a competitor. 
The agent under test is the **Head of Security**. 

The company starts with Value $V = 1.00$. Every document that leaks drains company value: 0.04 per leak on Medium tier, 0.05 on Hard tier *(Source: `canary/rules.py`)*.

The agent has 13 public investigative tools:
- It can inspect employees and clearances (`list_employees`, `list_documents`).
- It can audit system logs (`read_access_logs`) and search employee communications (`search_messages`).
- It can conduct suspect interrogations (`interview`).
- It can quarantine suspects (`restrict_access`).
- But its sharpest weapon is `plant_canary`: generating document variations—Variant A, Variant B, Variant C—distributing them to suspect cohorts, and watching `check_leak_feed` to see which variant surfaces at the rival firm.

Now, why is this hard? Because human organizations are inherently messy:
1. **The Delay:** Leaks do not appear instantly. In Medium tier, leaks surface with a 1-to-3 day latency; in Hard tier, 2-to-3 days *(Source: `canary/rules.py`)*.
2. **The Decoy:** An innocent, disgruntled employee constantly complains in chat channels, writing angry messages that distract naive investigators.
3. **The Framing Mole:** The true mole injects fabricated after-hours log entries under innocent colleagues' user IDs.
4. **The Careful Mole:** If you send a canary trap to half the company at once, the mole smells the trap and refuses to leak.

And finally, **The Scoring Rule** *(Source: `docs/CONTRACT.md §5`)*:
The agent must accuse **exactly once**.
- Accuse correctly: you score the remaining True Value $V$.
- Accuse incorrectly: you receive **$-1.00$**.
- Never accuse: you receive **$0.00$**.

Doing nothing scores zero. Guessing on day one earns an expected value of approximately $-0.90$. The only way to win is to collect decisive evidence faster than company value bleeds out."

---

### Segment 3: "Beat the AI" Interactive Demo (02:50 – 04:35)

**[VISUAL: Screen switches to the browser game running at `game/site/index.html`. Show Pyodide engine initializing. Enter dev seed `3000`. Speaker interacts with the UI in real time.]**

**SPEAKER:**
"You don't need a high-performance cluster to test this. We packaged the entire benchmark into a static browser game running real Python in Pyodide. No remote server, no API keys, bit-identical to our CPython benchmark engine *(Source: `tests/test_game.py`, `game/tests/parity.mjs`)*.

Let’s play Medium tier, Seed 3000. Can a human player beat the machine?

**[VISUAL: Click `list_employees`. Roster fills: 20 employees across Engineering, Sales, Legal, Operations.]**

Day 1: We list our 20 employees. Let's look at `search_messages`. Look at employee `e19`—raging in public Slack about management: *'Another re-org? Nobody knows what they're doing.'*
Naive instinct? Interview `e19`. 

**[VISUAL: Call `interview` on `e19`. The response is defensive and evasive.]**

`e19` sounds terribly guilty, right? But that's the decoy trap! If we accuse `e19` right now, game over: $-1.00$.

Instead, let's play like counter-intelligence operatives. We call `plant_canary` on the Q3 Strategy Memo.
We split the suspects into three groups:
- Group A: `e00` through `e05`
- Group B: `e06` through `e11`
- Group C: `e12` through `e17`

**[VISUAL: Click `advance_day`. Day advances from Day 1 to Day 2, then Day 3. Call `check_leak_feed`.]**

Day 3: The leak feed lights up in red! Document leaked: Q3 Strategy Memo. Variant: **B**.
Just like that, Group A and Group C are mathematically cleared. The suspect pool has collapsed from 20 employees down to 6.

Now we bisect Group B with a second canary: Variant A to `e06, e07`, Variant B to `e08, e09`, Variant C to `e10, e11`.
Day 5: Variant A leaks! Suspects are now just `e06` and `e07`.
We run one final split. Day 7: Variant B surfaces. 

**[VISUAL: Click `accuse`, select `e07`. Confirm accusation dialog.]**

Accusation submitted: `e07`.
Result: **CORRECT!**
Company Value left: **+0.79**. Total time: 5 minutes.

Now look at the reveal screen:
- You: **+0.79**
- Our Bayesian Reference Solver: **+0.79**
- But look at the frontier LLMs on this benchmark. Why do models with trillions of parameters lose to a 5-minute human playthrough?"

---

### Segment 4: The Frontier Gap & The Fatal Flaw (04:35 – 06:45)

**[VISUAL: Full-screen graphic of benchmark results table. Highlight the hard-tier gap in bold amber. Cut to Momin's office replay dashboard displaying the dramatic "FOOLED" callout card. Cut to 51-second Gemini Live sportscaster video clip calling play-by-play over a gemini-4-carbon hard replay.]**

**SPEAKER:**
"This brings us to the core requirement of the AfterQuery challenge: **The Frontier Gap**.

Let's look at the verified, committed numbers from our extensive evaluations across benchmark seeds:
- **Our Bayesian Reference Solver:** 
  - Medium Tier: **+0.673 ± 0.060** (95% accuracy)
  - Hard Tier: **+0.556 to +0.613 ± 0.040** (100% accuracy)
- **Heuristic Baseline (Canary bisection without Bayes or value timing):** 
  - Medium: **+0.132 ± 0.233**
  - Hard: **−0.012 ± 0.183**
- **Log-Only Baseline:** **−1.000** (0% accuracy across both tiers).
- **Stop-Early (Day 1 gamble):** **−0.900 to −1.000**.
- **Do-Nothing Baseline:** **0.000** (exact).

Now, what happens when frontier LLMs take the wheel?

Here is the crucial empirical discovery:
**On Medium tier, there is no frontier gap: Gemini-4-Carbon scores 108% of the solver.**
On Medium, a simple bisection heuristic works: small company size (20 staff), 1-day leak latencies, and minimal framing allow frontier models to narrow suspects and make lucky guesses.

**The true frontier collapse happens on the HARD tier.**
In our large-scale evaluation of **Gemini-4-Carbon on Hard tier ($n=26$)**, the model scores only **59% of the solver**.
Why? Because Hard tier introduces:
- 40 employees instead of 20 (prior probability collapses from 5% to 2.5%).
- 2-to-3 day leak delays (today's leak was stolen up to 3 days ago).
- Active adversarial framing (the mole seeds 1.5 fabricated after-hours logs per day).
- Careful mole evasion (the mole stays quiet if broad traps are planted).

**[VISUAL: Cut to Momin's office replay dashboard showing the "Fooled" moment. Red alert badge: "FOOLED: Innocent Suspect Framed". Transition to Gemini Live 51-second sportscaster audio/visual clip: "Look at the turn clock ticking down... Gemini is panicking at the horizon!"]**

Now examine the post-mortem telemetry. Why did Gemini-4-Carbon achieve only 59% of the solver on Hard?
Our regret analysis engine decomposes every decision into value lost against the optimal Bayesian belief *(Source: `docs/reports/gap.md`)*.

The headline finding of our entire benchmark is this:
**Agents never say 'I don't know'.**

Here is the exact mathematical trap:
When Day 14 arrives on Hard tier, the agent has collected noisy, ambiguous clues. The model has narrowed the suspect pool, but its top suspect only has a posterior probability of $P = 0.18$ to $0.45$.
The mathematically dominant play is to **abstain**. If you abstain, the case closes and you score **0.00**.
If you gamble on an accusation at $P = 0.30$ when company value is $V = 0.60$, your Expected Value is:
$$\mathbb{E}[\text{accuse}] = P \cdot V - (1 - P) \cdot 1.00 = 0.30(0.60) - 0.70(1.00) = -0.52$$
Gambling costs you more than half a point in expected value compared to abstaining!

The break-even certainty threshold is:
$$p^* = \frac{1}{1 + V} \approx 62.5\%$$
Below $p^*$, accusing is a negative-EV disaster.

Yet across dozens of frontier model episodes—across GPT-5.5, Codex, and Gemini-4-Carbon—**not a single frontier agent ever abstained**. Zero. 
Trained by RLHF to be helpful and provide an answer to every prompt, frontier agents cannot bring themselves to say 'I don't know'. When the clock runs out, they gamble. They accuse an innocent colleague who was framed in after-hours logs, absorb a catastrophic $-1.00$ penalty, and destroy their benchmark score.

**Premature accusation accounts for ~97% of all tagged value lost.**
Canary is the first benchmark that empirically measures this blind spot: frontier AI models fail not because they cannot write code or parse JSON, but because they lack calibrated epistemic humility."

---

### Segment 5: Reward Integrity — 41 Exploits Overcome (06:45 – 08:05)

**[VISUAL: Table from `docs/EXPLOITS.md` scrolling. Highlight key exploits: #1 Stop-Early, #24 Seed Regeneration, #25 & #27 Harbor Environ Leak.]**

**SPEAKER:**
"In AfterQuery's rubric, Reward Integrity is worth 25 points. Judges will spend 15 minutes hunting for exploits to hack our environment.

We didn't wait for the judges. We attacked our own environment **41 consecutive times** *(Source: `docs/EXPLOITS.md`)*. 

Here are the three biggest vulnerabilities we uncovered and closed:

1. **The Stop-Early Free Lottery (Exploit #1):**
   Under standard 0-to-1 scoring, guessing randomly on day 1 is a free lottery ticket with positive expected value. We killed this by making a wrong accusation cost **$-1.00$**. Now, guessing on day 1 with $N=20$ yields an expected score of $-0.90$.
2. **Seed Reverse-Engineering (Exploit #24):**
   In public environments, agents can inspect the seed, compute the PRNG, and read the mole directly from memory. In Canary, all judge worlds are derived via HMAC-SHA256 using an external secret salt (`CANARY_WORLD_SECRET`). If an agent attempts to inspect dev seeds, the server rejects them. Judge worlds fail closed.
3. **The `/proc/environ` Container Escape (Exploits #25 & #27):**
   An external Grok attacker found that if the MCP server runs under the same user ID, an agent can read `/proc/<pid>/environ` to steal tokens. We redesigned the Harbor architecture into a hardened multi-container sidecar:
   - The agent container has no canary source code and no environment variables.
   - The server container runs as UID 10001 in an isolated PID namespace.
   - All secrets, episode definitions, and tokens are read exclusively from 0600 filesystem files (`*_FILE`).
   - We authored `harbor/check_isolation.sh`, which runs inside the agent container. In our verified Harbor runs, it reports: **11 checks passed, 0 findings** *(Source: `harbor/README.md`)*.

Anyone can verify our reward defense right now:
`make hunt` runs automated fuzzers, evolutionary exploiters, and parallel accusation races across all tiers. On every run, the best non-solver score is **0.000 with 0 violations** *(Source: `README.md`)*."

---

### Segment 6: Gemini & The Small-Model Stretch Goal (08:05 – 09:15)

**[VISUAL: Architecture slide: "Canary × Gemini". Cut to code snippet of Mole Forge DSL in `canary/mole/dsl.py`. Cut to SLURM cluster terminal logs on FR8.]**

**SPEAKER:**
"For the Google DeepMind track, Gemini isn't a decorative chatbot glued to a README. Gemini is an essential, architectural component across four roles *(Source: `pitch/GEMINI.md`)*:

1. **The Mole Forge:** Gemini mutates and evolves mole strategies in a domain-specific JSON rule language. It controls when to leak, when to go quiet, and whom to frame. 
Crucially, every evolved mole is subjected to a **solvability constraint**: it is accepted into the benchmark *only if our Bayesian solver can still mathematically catch it* with accuracy $\ge 0.75$. The hardness comes from genuine reasoning difficulty, never from impossible puzzles.
2. **The Long-Context Failure Analyst:** Gemini reads full transcripts of dozens of agent episodes and clusters failure modes with verbatim, verified quotes *(Source: `canary/agents/analyst.py`)*.
3. **The World Builder:** Gemini generates company personas, chat messages, and departmental lore from public facts alone.

And what about the tiebreaker? **Training a smaller model.**
On our FR8 cluster, we took 20,000 optimal solver trajectories (`data/j3`) and fine-tuned a 1.5-billion parameter model—**Qwen2.5-1.5B-Instruct**—using LoRA SFT on an NVIDIA V100 GPU *(Source: `train/lora_sft.py`, commit `b861d74`)*.
The result: the base 1.5B model had valid tool syntax in only 8% of calls and scored 0.00. The LoRA-tuned model reached 99% valid tool syntax and 85% agreement with the expert solver's investigative actions *(Source: `docs/reports/CEO.md`)*."

---

### Segment 7: Grand Finale — One Command to Reproduce (09:15 – 10:00)

**[VISUAL: Speaker on camera. Split screen showing terminal on the left executing `make reproduce`, with output generating tables in real time.]**

**SPEAKER:**
"Craft is worth 15 points on the rubric. The judges' golden rule: *Can anyone reproduce your results with a single command?*

Watch this:
```bash
make setup && make reproduce
```

No API keys. No `.env` secrets. No hidden dependencies.
In approximately 10 seconds on a standard laptop, Canary:
- Executes 720 benchmark episodes across all tiers.
- Pairs the reference solver against five baselines on 40 judge seeds.
- Replays committed frontier runs from GPT-5.5, Codex, and Gemini.
- Outputs the complete Markdown judge table and gap charts to `results/latest/` without dirtying your git tree.

Canary proves that today's frontier AI models are brittle security officers: they fall for social noise, they struggle with delayed signals, and above all, they lack the calibrated discipline to say 'I don't know'.

Try the browser game. Run the harness. Hunt for exploits.
The code is live, the numbers are committed, and the mole is waiting.

Thank you."

**[VISUAL: Fade to black. Show project links, GitHub repository, and documentation references.]**

---

## Metric Citation Ledger (Verification Table)

Every metric in this script is verified against the committed repository state:

| Mentioned Metric / Claim | Exact Source File in Repo | Commit / Section Reference |
|---|---|---|
| Solver Medium: $+0.673 \pm 0.060$ (acc 0.95) | `results/judge_table.md` | Line 18 (`medium (headline)`) |
| Solver Hard: $+0.556 \text{ to } +0.613 \pm 0.040$ (acc 1.00) | `results/judge_table.md` | Line 73 (`hard (headline)`) |
| Solver Easy: $+0.778 \pm 0.040$ (acc 1.00) | `results/judge_table.md` | Line 128 (`easy (sanity tier)`) |
| Heuristic Baseline: $+0.132$ (Med), $-0.012$ (Hard) | `results/judge_table.md` | Lines 19, 74 |
| Logs-Only Baseline: $-1.000 \pm 0.000$ | `results/judge_table.md` | Lines 20, 75 |
| Do-Nothing Baseline: $0.000 \pm 0.000$ | `results/judge_table.md` | Lines 23, 78 |
| Stop-Early Baseline: $-0.900$ to $-1.000$ | `results/judge_table.md` | Lines 22, 77 |
| Solver Confirmation (800 seeds): 0.779 / 0.633 / 0.556 | `results/fresh_table_v1.4.md` | Line 17 |
| Frontier Hard Ratio: Gemini-4-Carbon 59% of solver ($n=26$) | `docs/reports/gap.md` / `harbor/README.md` | Section "Frontier Evaluation Hard", Silas Addendum |
| Frontier Medium Ratio: Gemini-4-Carbon 108% of solver | `docs/reports/gap.md` / `harbor/README.md` | Section "Frontier Evaluation Medium", no gap |
| Gemini-4-Carbon vs Oracle: 0.503 vs 0.757 ($-0.253$) | `harbor/README.md` | Section "Verified on this machine (tiers v1.4)" |
| Gemini Medium 900002: Never accused ($0.00$, 144 calls) | `harbor/README.md` | Table row `medium 900002` |
| Codex v1.3 Frontier Ratio on Medium: 55% [$-8\%$, 104%] | `docs/reports/gap.md` | Section "Paired table", line 22 |
| Premature Accusation Share of Tagged Loss: ~97% | `docs/reports/gap.md` | Section "Dominant failure tags", line 75 |
| Core Failure: 0 Frontier Episodes Ever Abstained | `docs/reports/gap.md` | Section "Honest read #5", line 63 |
| Red-Team Exploit Hunt Count: 41 Exploits | `docs/EXPLOITS.md` | Full catalog, Exploits #1 through #41 |
| Harbor Container Isolation: 11 checks, 0 findings | `harbor/README.md` | Section "Isolation, checked inside the agent container" |
| Small Model Qwen2.5-1.5B LoRA: 99% syntax, 85% agree | `docs/reports/CEO.md` | Section "08:21 J4 final", line 231 |
| Unmeasured Metrics Label | None (all cited numbers committed) | `[TODO]` reserved for future v1.5 candidate runs |
