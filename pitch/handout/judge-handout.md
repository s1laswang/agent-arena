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

<div class="strip">
  <figure>
    <img src="../assets/office-floorplan.jpg" alt="Office floor plan with employees and AI-agent avatars.">
    <figcaption>The company</figcaption>
  </figure>
  <figure>
    <img src="../assets/mole.jpg" alt="Hooded figure whose shadow is a mole.">
    <figcaption>The mole</figcaption>
  </figure>
  <figure>
    <img src="../assets/canary-documents.jpg" alt="Four canary documents with different watermarks.">
    <figcaption>Canary variants</figcaption>
  </figure>
  <figure>
    <img src="../assets/leak-feed.jpg" alt="Leak feed with one flagged post.">
    <figcaption>One flagged leak</figcaption>
  </figure>
</div>

<div class="cols">
  <div>
    <h2>What it is</h2>
    <p>A fictional company is leaking secrets to a rival, and every leak costs company value. The agent under test is the <strong>head of security</strong>. The reference run is a <strong>Bayesian canary-trap solver</strong>: the real technique, executed optimally from observable data only.</p>
    <p>The hook is the recent espionage headlines around a chip-company CEO. The company here is fictional. No cost figure is in the source docs. <span class="ph">[STAT_INSIDER_COST]</span></p>
    <h2>How the environment works</h2>
    <p><strong>Goal.</strong> Identify the mole while preserving as much value as possible.</p>
    <p><strong>Observations.</strong> Tool results only. Company text is public facts and signals, never the truth.</p>
    <p><strong>Actions.</strong> <code>status</code>, <code>list_employees</code>, <code>list_documents</code>, <code>read_access_logs</code>, <code>search_messages</code>, <code>read_message</code>, <code>interview</code>, <code>plant_canary</code>, <code>check_leak_feed</code>, restrict / unrestrict access, <code>advance_day</code>, <code>accuse</code> once.</p>
    <p><strong>Canaries.</strong> Different document variants go to different groups. A fragment on the leak feed narrows who could have had it. <code>max_variants</code> blocks one unique copy per person.</p>
    <p><strong>Reward.</strong> V if the accusation is correct, otherwise 0. No accusation, the tool cap, or the horizon also scores 0.</p>
    <table>
      <thead><tr><th>Tier</th><th>Staff</th><th>Delay</th><th>Added pressure</th></tr></thead>
      <tbody>
        <tr><td>Easy</td><td>12</td><td>1</td><td>—</td></tr>
        <tr><td>Medium</td><td>20</td><td>1–2</td><td>Decoy + framing</td></tr>
        <tr><td>Hard</td><td>30</td><td>1–3</td><td>Careful mole, clearances</td></tr>
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
      <li>Do nothing / stop early / restrict all: specified at <strong>0 / ≈ V/N / far below the solver</strong>, and marked tested.</li>
      <li>One unique canary per person: the <code>max_variants</code> cap.</li>
      <li>Error text or timing: identical error paths; a fuzzer and an LLM exploit hunter.</li>
      <li>Read the mole in the prose: providers never see the mole; lint plus a text-only probe.</li>
      <li>Spam tools: daily cap <span class="ph">[DAILY_ACTION_CAP]</span>; global cap of <strong>300</strong>.</li>
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
        <tr><td>Easy</td><td><span class="ph">[SCORE_REF_1]</span></td><td><span class="ph">[SCORE_FRONTIER_1]</span></td><td><span class="ph">[GAP_1]</span></td></tr>
        <tr><td>Medium</td><td><span class="ph">[SCORE_REF_2]</span></td><td><span class="ph">[SCORE_FRONTIER_2]</span></td><td><span class="ph">[GAP_MEDIUM]</span></td></tr>
        <tr><td>Hard</td><td><span class="ph">[SCORE_REF_3]</span></td><td><span class="ph">[SCORE_FRONTIER_3]</span></td><td><span class="ph">[GAP_FRONTIER]</span></td></tr>
      </tbody>
    </table>
    <p>Expected baselines, from the plan: do-nothing <strong>0</strong>, stop-early <strong>≈ V/N</strong>, random <strong>≈ 0</strong>, restrict-all <strong>≪ solver</strong>. Measured stop-early <span class="ph">[SCORE_STOP_EARLY]</span>. Measured restrict-all <span class="ph">[SCORE_RESTRICT_ALL]</span>.</p>
    <h2>Reproduce</h2>
    <p><code>make setup</code> (uv, Python 3.12). <code>make reproduce</code> is the judge table: reference, 3 agent runs, do-nothing, stop-early. No API keys. Rubric: gap 30, meaningful difficulty 30, reward integrity 25, craft 15. One command from the README reproduces the reported results.</p>
  </div>
</div>

<div class="foot">
  <strong>Sources.</strong> README.md, docs/PLAN.md, and CHALLENGES-AFTERQUERY-GEMINI.md on branch <strong>justSilas</strong>. Do not fill a yellow token from memory.
  <strong>Repo.</strong> https://github.com/s1laswang/agent-arena/tree/justSilas
</div>
