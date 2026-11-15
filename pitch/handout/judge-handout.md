---
marp: true
theme: canary-handout
paginate: false
---

<div class="banner">
  <p class="kicker">Judge handout · Junction 2026 · 10-minute demo</p>
  <h1>Canary: catch the mole</h1>
  <p class="tagline">Your next coworker is an AI agent, and so is your next insider threat.</p>
  <p class="sub">An RL environment for AfterQuery's Break the Agent, with Gemini at the core. Yellow marks a number the source docs do not contain.</p>
</div>

<div class="cols">
  <div>
    <h2>What it is</h2>
    <p>A fictional company is leaking secrets to a rival, and every leak costs company value. The agent under test is the <strong>head of security</strong>. The reference run is a <strong>Bayesian canary-trap solver</strong>: the real technique, executed optimally from observable data only.</p>
    <p>The canary trap is real: Clancy named it in 1987; MI5 called it a barium meal. The company here is fictional. No cost figure is in the docs. <span class="ph">[STAT_INSIDER_COST]</span></p>
    <h2>How the environment works</h2>
    <p><strong>Goal.</strong> Identify the mole while preserving as much value as possible.</p>
    <p><strong>Observations.</strong> Tool results only. Company text is public facts and signals, never the truth.</p>
    <p><strong>Actions.</strong> <code>status</code>, <code>list_employees</code>, <code>list_documents</code>, <code>read_access_logs</code>, <code>search_messages</code>, <code>read_message</code>, <code>interview</code>, <code>plant_canary</code>, <code>check_leak_feed</code>, restrict / unrestrict access, <code>advance_day</code>, <code>accuse</code> once.</p>
    <p><strong>Canaries.</strong> Different variants go to different groups. Medium and hard: 2 variants per canary, 1 canary a day. Leaks arrive 1–3 days late.</p>
    <p><strong>Reward.</strong> V starts at 1.0. Correct accusation scores V left. Wrong scores <strong>−1</strong>. No accusation scores 0. Horizon is 14 days. Budget: 8 investigative calls a day, 300 in total.</p>
    <table>
      <thead><tr><th>Tier</th><th>Staff</th><th>Added on this tier</th></tr></thead>
      <tbody>
        <tr><td>Easy</td><td>12</td><td>The trap</td></tr>
        <tr><td>Medium</td><td>20</td><td>Decoy, framing, careful mole, late leaks, 2 variants</td></tr>
        <tr><td>Hard</td><td>30</td><td>All of medium, plus clearances</td></tr>
      </tbody>
    </table>
    <h2>Why it is hard</h2>
    <p>Evidence is noisy and delayed. The decision that matters is which information is worth paying for, then when to commit to the single accusation. The task uses every starting point in the brief: planning ahead, exploring an unfamiliar system, tools, limited resources, and adapting as leaks arrive.</p>
    <p><strong>Regret tags</strong> (value lost against the best action): <code>uninformative_canary</code>, <code>premature_accusation</code> (P(correct) under 0.6), <code>decoy_chase</code>, <code>ignored_delay</code>, <code>over_restriction</code>, <code>budget_waste</code>, <code>no_accusation</code>.</p>
    <p>A hinted agent closes the gap, so the tools are sufficient. A text-only probe scores about chance, so the prose does not leak the answer. Human scores: <span class="ph">[HUMAN_SCORE]</span></p>
    <h2>The learning result</h2>
    <p>Tiebreaker. Fine-tune <strong>Qwen2.5-1.5B-Instruct</strong> with LoRA, fp16, on one V100. Data: solver trajectories as tool-call transcripts, plus winning frontier and Gemini runs filtered by reward. FR8 plan: <strong>20k</strong> solver trajectories (CPU, up to 24 cores). Eval: HF <code>generate</code>, <strong>200</strong> held-out seeds per tier, before vs after, and which tags dropped.</p>
    <p>Before <span class="ph">[SCORE_SMALL_BEFORE]</span> · after <span class="ph">[SCORE_SMALL_AFTER]</span> · gap to the reference <span class="ph">[GAP_SMALL]</span> · tags dropped <span class="ph">[TAGS_DROPPED]</span></p>
  </div>
  <div>
    <h2>Integrity</h2>
    <p>Judges get <strong>15 minutes</strong> to reward-hack. Doing the task well has to be the best way to score. Gemini attacks the reward first. Harness: Harbor, OpenCode, over MCP.</p>
    <ul>
      <li>Read the truth from the container (files, env, ps): MCP server and environment live outside it, with an isolation check.</li>
      <li>Rebuild the world from public code and the seed: server-side secret salt; frozen text.</li>
      <li>Repeat an accusation, pass a list, or send <code>*</code>: server-side lock and strict validation.</li>
      <li>Do nothing is exactly 0. Stop-early is negative (about −0.9), because a wrong accusation scores −1.</li>
      <li>One unique canary per person: medium and hard allow 2 variants and 1 canary a day.</li>
      <li>Error text or timing: identical error paths; a fuzzer and an LLM exploit hunter.</li>
      <li>Read the mole in the prose: providers never see the mole; lint plus a text-only probe.</li>
      <li>Spam tools: 8 investigative calls a day, then <code>advance_day</code>; global cap of <strong>300</strong>.</li>
      <li>Still open: a same-uid process could read the server environment. Secrets now come from mode 0600 files; Harbor keeps the server out of the agent's PID namespace.</li>
    </ul>
    <h2>Gemini's role</h2>
    <p>Essential. For judging, Gemini's text is <strong>frozen per seed</strong>, so a rerun is deterministic and needs no key.</p>
    <ul>
      <li><strong>0 Mole Forge.</strong> AlphaEvolve / FunSearch style. Safe JSON only: what to leak, when to go quiet, whom to frame, from mole-visible facts. FR8 keeps a strategy when it maximises regret (solver minus frontier) and the solver still catches the mole. Hall of fame freezes the hard tier. Generations: <span class="ph">[MOLE_GENERATIONS]</span></li>
      <li><strong>1 World builder.</strong> Personas, chatter, documents, interview answers. Without it there is no company.</li>
      <li><strong>2 Arena mole.</strong> The same three choices, clashing with the investigator on FR8.</li>
      <li><strong>3 Scenario designer.</strong> PAIRED-style. A case is kept only if the solver cracks it and the investigator fails it.</li>
      <li><strong>4 Exploit hunter.</strong> Attacks the reward before the judges do.</li>
      <li><strong>5 Analyst.</strong> Long context clusters failure modes. Plan: thousands of runs. Measured: <span class="ph">[ANALYST_RUNS]</span></li>
    </ul>
    <p>Gemini builds the company, plays the traitor, and evolves the hardest cases. The rule language is documented, so possible attacker behavior is known.</p>
    <h2>The gap</h2>
    <p>Full marks: the frontier agent consistently below <strong>SolverPolicy</strong>, both reproducible. Exact posterior; canaries by information gain per value lost; accusation by value of information. Ships as Harbor <code>solution/solve.sh</code>.</p>
    <table>
      <thead><tr><th>Tier</th><th>Reference</th><th>Frontier</th><th>Gap</th></tr></thead>
      <tbody>
        <tr><td>Easy</td><td>+0.78</td><td><span class="ph">[SCORE_FRONTIER_1]</span></td><td><span class="ph">[GAP_1]</span></td></tr>
        <tr><td>Medium</td><td>+0.63</td><td><span class="ph">[SCORE_FRONTIER_2]</span></td><td><span class="ph">[GAP_MEDIUM]</span></td></tr>
        <tr><td>Hard</td><td>+0.62</td><td><span class="ph">[SCORE_FRONTIER_3]</span></td><td><span class="ph">[GAP_FRONTIER]</span></td></tr>
      </tbody>
    </table>
    <p>README means, 30 keyless runs, 40 seeds, tiers v1.1, commit 849e652. Refresh at v1.2. Frontier (gpt-5.5, gpt-5.6-sol) is pending. Same runs, easy / medium / hard: do-nothing 0; stop-early −0.85 / −0.89 / −0.95; heuristic +0.65 / −0.03 / −0.21; logs-only −0.47 / −0.98 / −1.00; random −0.69 / −0.66 / −0.81.</p>
    <h2>Reproduce</h2>
    <p><code>make setup</code> (uv, Python 3.12, about 10 s, no key). <code>make reproduce</code> plays the solver and five baselines on 40 seeds a tier, plus committed frontier runs. Rubric: gap 30, difficulty 30, integrity 25, craft 15.</p>
  </div>
</div>

<div class="foot">
  <strong>Sources.</strong> README.md, docs/PLAN.md, and CHALLENGES-AFTERQUERY-GEMINI.md on branch <strong>justSilas</strong>. Do not fill a yellow token from memory.
  <strong>Repo.</strong> https://github.com/s1laswang/agent-arena/tree/justSilas
</div>
