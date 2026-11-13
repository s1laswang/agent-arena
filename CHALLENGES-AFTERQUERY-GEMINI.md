# Target challenges: AfterQuery "Break the Agent" + Google DeepMind "Best Use of Gemini API"

Copied from the Junction 2026 platform (13 Nov 2026). Final submission: **Sun 15 Nov 10:00 Helsinki**.

---

## 1. Break the Agent (AfterQuery), our main track

**Ask:** Build a reinforcement learning environment that challenges today's best AI agents, demonstrates real failure modes, and shows that its rewards reflect real progress.

### What to build
- Pick a setting (a game, a scientific simulation, a software task, a real-world process, ...) and explain why it was chosen and what an agent could learn there.
- The environment has a **clear goal**, **actions** the agent can take, and a **checkable reward**.
- Run a **frontier agent** in it and compare with a **stronger reference run** our team can demonstrate and reproduce.
- Show **where and why** the agent falls short. The difficulty must come from the decisions the agent has to make, and it must have the information and tools needed to succeed.
- The judges will try to **reward-hack** it.
- **Stretch goal (also the tiebreaker):** train a smaller model on experience from the environment and show whether it improves.

### Starting points (prompts, not requirements)
Planning several steps ahead · exploring an unfamiliar system · using tools · managing limited resources · adapting when new information arrives.
"A small environment with a well-chosen challenge can be enough."

### Judging rubric (100 points)
| Criterion | Points | Full points | Zero points |
|---|---|---|---|
| **The gap** | 30 | The frontier agent consistently scores below our demonstrated stronger reference run; both reproducible across repeated runs | No measurable gap, or the gap can't be reproduced or checked against a demonstrated reference |
| **Meaningful difficulty** | 30 | We explain the agent's main mistakes and tie them to decisions in the task; the info and tools to do better are available | The gap comes from withheld info, trick wording, impossible timing or broken tools |
| **Reward integrity** | 25 | The reward measures task success and survives judges' exploit attempts; doing nothing or stopping early earns ~0; doing the task well is the best way to score | An exploit, loophole or task-avoiding strategy beats successful play |
| **Craft** | 15 | The rules make sense for the setting; **one command from the README** reproduces our reported results | Only works in our demo, or judges can't reproduce it |

### How judging runs
- A 10-minute demo.
- Judges rerun with the **standard harness**: our reference run, **3 agent runs**, a **do-nothing baseline**, and a **stop-early baseline**.
- **15 minutes of judges hunting for reward exploits.**
- Tiebreaker: a smaller model that improves after training on the environment's experience.

### Resources provided
- Harness: **Harbor running the OpenCode agent**, which connects to our environment **over MCP**.
- A scoring skeleton, a starter kit (harness docs and the rubric), and frontier model API credits per team.
- Mentors on site all weekend: Daksh Raghuwanshi and Ved Vedere (AfterQuery environments team).

### Prizes
1st: €3,000 + a work trial at AfterQuery + merch · 2nd: €1,500 + merch · 3rd: €500

---

## 2. Best Use of Gemini API (Google DeepMind), side track

**Ask:** Build something extraordinary with the Gemini API. It's open innovation, with any industry or use case. Go beyond "adding an LLM to an app".

The submission must explain:
- the problem and why it matters,
- how the Gemini API is integrated,
- what makes the use innovative or technically impressive,
- why Gemini is essential to the solution.

**Credits:** Gemini API credits for up to 400 teams. **Fill in the form:** https://forms.gle/bByXvjGkW9WZuYwW9 . Keys come from Google AI Studio (https://aistudio.google.com/). Participants must be 18+.
Docs: https://ai.google.dev/gemini-api/docs · Quickstart: https://ai.google.dev/gemini-api/docs/quickstart · Support at the DeepMind booth.

**Prizes:** 1st: €4,000 + $1,000 Google Cloud credits per team member · 2nd: €2,000 · 3rd: €1,000

---

## How one project hits both (draft plan)

**An environment where an agent has to plan, explore and use tools under limited resources, with a reward built to survive exploits. Gemini plays a central role, not a bolted-on one.**

- **AfterQuery:** an MCP environment (Harbor/OpenCode compatible) with a clear goal, tools and a deterministic, checkable reward. We show a reproducible gap between the frontier agent and our reference run, and include the do-nothing and stop-early baselines in the eval script.
- **Gemini, essential rather than decorative:**
  - **Red-team attacker:** Gemini searches for reward hacks against our own reward before the judges do (automated exploit hunting), and every exploit it finds patches the reward.
  - **Adaptive scenario generator:** Gemini generates new task instances and "new information arrives" events, so agents can't memorise the environment.
  - **Failure analyst:** Gemini's long context reads thousands of trajectories and clusters the failure modes into the "meaningful difficulty" story.
- **FR8 cluster:** CPU nodes run thousands of episodes in parallel (agents vs. environment, attacker vs. reward). The V100s host open 7-8B models as extra agents and run the **stretch goal**: LoRA-train a small model on environment experience and show the improvement, which is also the tiebreaker.
- **Rules from the rubric:** no hidden info, no trick wording, no broken tools; doing nothing or stopping early scores about 0; one command reproduces everything.

### Open decisions
- [ ] The setting (candidates: B2B procurement with mandates and stock-outs, reusing our Valio work; supply chain or resource management; debugging an unfamiliar system; scientific or lab simulation)
- [ ] Who fills in the Gemini credits form (do it ASAP)
- [ ] Get the Harbor/OpenCode starter kit and scoring skeleton from AfterQuery
- [ ] What the reference run is (a scripted expert solver? the best agent plus a human?)
