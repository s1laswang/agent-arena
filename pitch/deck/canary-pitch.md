---
marp: true
theme: default
size: 16:9
paginate: true
footer: "Canary  ·  catch the mole"
style: |
  section {
    background:
      linear-gradient(#f5c542, #f5c542) top left / 100% 5px no-repeat,
      #07111e;
    color: #e7eef8;
    color-scheme: dark;
    font-family: Inter, "Liberation Sans", "DejaVu Sans", sans-serif;
    font-size: 22px;
    line-height: 1.35;
    padding: 32px 44px 40px;
    justify-content: flex-start;
    letter-spacing: 0;
  }
  section.lead { justify-content: center; }
  section h1, section h2 {
    color: #f5c542;
    font-weight: 700;
    line-height: 1.12;
    margin: 0 0 10px;
  }
  section h1 { font-size: 40px; }
  section h2 { font-size: 34px; }
  section p { margin: 0 0 10px; }
  section ul, section ol { margin: 6px 0 0; }
  section li { margin: 4px 0; }
  section strong { color: #fff; font-weight: 700; }
  section code {
    font-family: "JetBrains Mono", "Liberation Mono", monospace;
    font-variant-ligatures: none;
    font-size: 0.82em;
    color: #b7ecf6;
    background: rgba(90, 208, 230, 0.1);
    padding: 0 5px;
    border-radius: 4px;
  }
  section footer {
    left: 44px;
    right: 80px;
    bottom: 14px;
    color: #7f8da3;
    font-size: 14px;
  }
  section::after {
    color: #f5c542;
    font-size: 14px;
    bottom: 14px;
    right: 40px;
  }
  .eyebrow {
    margin: 0 0 6px;
    color: #5ad0e6;
    font-size: 13px;
    font-weight: 700;
    letter-spacing: 0.16em;
    text-transform: uppercase;
  }
  .fine {
    color: #93a4bc;
    font-size: 15px;
    margin: 8px 0 0;
  }
  .ph {
    color: #1a1404;
    background: #f5c542;
    font-family: "JetBrains Mono", "Liberation Mono", monospace;
    font-variant-ligatures: none;
    font-weight: 700;
    font-size: 0.78em;
    padding: 1px 6px 2px;
    border-radius: 4px;
    white-space: nowrap;
  }
  blockquote {
    margin: 16px 0 0;
    padding: 14px 18px;
    border-left: 5px solid #f5c542;
    background: rgba(245, 197, 66, 0.1);
    color: #f5c542;
    font-size: 30px;
    font-weight: 700;
    line-height: 1.25;
  }
  .split {
    display: grid;
    grid-template-columns: minmax(0, 0.96fr) minmax(0, 1.04fr);
    gap: 26px;
    align-items: center;
    flex: 1;
    min-height: 0;
  }
  .frame {
    background: #050a14;
    border: 1px solid rgba(245, 197, 66, 0.45);
    border-radius: 14px;
    padding: 8px;
    box-shadow: 0 0 0 1px rgba(90, 208, 230, 0.12);
  }
  .frame img {
    display: block;
    width: 100%;
    border-radius: 8px;
    background: #050a14;
  }
  .frame img.cover {
    object-fit: cover;
    object-position: center;
    height: 460px;
  }
  .frame img.contain {
    object-fit: contain;
    height: auto;
    aspect-ratio: 16 / 9;
  }
  section.lead h1 {
    font-size: 76px;
    letter-spacing: -0.03em;
    margin: 0;
  }
  section.lead .sub {
    color: #ffffff;
    font-size: 32px;
    font-weight: 650;
    margin: 0 0 16px;
  }
  section.lead .split { grid-template-columns: minmax(0, 1.02fr) minmax(0, 0.98fr); }
  section table {
    display: table !important;
    width: 100% !important;
    max-width: 100% !important;
    border-collapse: collapse !important;
    border-spacing: 0 !important;
    font-size: 17px;
    margin-top: 8px;
    background: transparent !important;
    color: #e7eef8 !important;
    overflow: visible !important;
  }
  section table tr {
    background: transparent !important;
    border: 0 !important;
  }
  section table th {
    text-align: left;
    color: #f5c542 !important;
    background: #122033 !important;
    font-weight: 700;
    font-size: 14px;
    letter-spacing: 0.04em;
    text-transform: uppercase;
    padding: 7px 8px !important;
    border-bottom: 2px solid #f5c542 !important;
  }
  section table td {
    color: #e7eef8 !important;
    background: #0d1828 !important;
    padding: 6px 8px !important;
    border-bottom: 1px solid rgba(255, 255, 255, 0.1) !important;
    vertical-align: top;
  }
  section table td.num, section table th.num { text-align: right; }
  section table.compact { font-size: 16px; }
  section table.compact td, section table.compact th { padding: 5px 8px !important; }
  .tags {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 8px 16px;
    margin-top: 8px;
  }
  .tags div {
    background: #101a2c;
    border-left: 3px solid #f5c542;
    padding: 6px 10px 7px;
  }
  .tags code {
    color: #f5c542;
    background: transparent;
    padding: 0;
    font-size: 14px;
  }
  .tags p { margin: 2px 0 0; font-size: 15px; color: #d5deea; }
  .tools { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 12px; }
  .tools span {
    font-family: "JetBrains Mono", "Liberation Mono", monospace;
    font-variant-ligatures: none;
    font-size: 12.5px;
    color: #b7ecf6;
    background: #102433;
    border: 1px solid rgba(90, 208, 230, 0.35);
    border-radius: 999px;
    padding: 3px 8px;
  }
  .tools span.once {
    color: #1a1404;
    background: #f5c542;
    border-color: #f5c542;
    font-weight: 700;
  }
  .roles {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 8px 18px;
    margin-top: 6px;
  }
  .roles div {
    background: #101a2c;
    border-radius: 8px;
    padding: 8px 10px 8px 12px;
  }
  .roles b { color: #f5c542; font-size: 15px; }
  .roles p { margin: 2px 0 0; font-size: 15px; color: #d5deea; }
  ol.asks { list-style: none; padding: 0; margin: 6px 0 0; }
  ol.asks li {
    position: relative;
    padding: 7px 0 7px 42px;
    border-bottom: 1px solid rgba(255, 255, 255, 0.08);
  }
  ol.asks li::before {
    content: counter(list-item);
    position: absolute;
    left: 0;
    top: 8px;
    width: 26px;
    height: 26px;
    border-radius: 50%;
    background: #f5c542;
    color: #1a1404;
    font-size: 14px;
    font-weight: 700;
    line-height: 26px;
    text-align: center;
  }
  .closer {
    margin: 16px 0 0;
    color: #f5c542;
    font-size: 30px;
    font-weight: 700;
    line-height: 1.2;
  }
  img.diagram { width: 100%; height: auto; margin-top: 6px; display: block; }
---

<!-- _class: lead -->

<div class="split">
  <div>
    <p class="eyebrow">AfterQuery · Break the Agent · Junction 2026</p>
    <h1>Canary</h1>
    <p class="sub">catch the mole</p>
    <p>A fictional company. A hidden mole. One accusation.</p>
    <p class="fine">Reference run: a Bayesian canary-trap solver. Gemini is part of the environment, not a plugin.</p>
  </div>
  <div class="frame">
    <img class="cover" src="../assets/office-floorplan.jpg" alt="Isometric night office. Employees sit at desks. Small glowing orbs mark AI-agent coworkers. Cyan links meet at a yellow-lit central desk.">
  </div>
</div>

<!--
TIMING: 0:00–0:20 (20 seconds)

Canary is our Break the Agent environment. A fictional company is leaking secrets. You are head of security, and you may accuse the mole once. The reference is a Bayesian canary trap, and Gemini builds the world around it.

Do not preview scores. Yellow tokens later in the deck are empty on purpose.
-->

---

<p class="eyebrow">Why this setting</p>
<h1>Insider leaks are costly, and hard to catch.</h1>
<p>The evidence arrives late, and the mole adapts. The canary trap is a real technique: a different version of a secret for each suspect, then see which version leaks. Tom Clancy named it in 1987. MI5 called the same idea a barium meal.</p>
<p>The company here is fictional. A sourced cost figure, when we have one: <span class="ph">[STAT_INSIDER_COST]</span></p>
<blockquote>Your next coworker is an AI agent, and so is your next insider threat.</blockquote>
<p class="fine">Can an AI security lead catch a mole? &nbsp;·&nbsp; Yellow means the number is not in the source docs.</p>

<!--
TIMING: 0:20–1:10 (50 seconds)

Insider leaks are hard to catch because the trail shows up late and the mole adapts. The canary trap is a real counter-intelligence technique. Tom Clancy named it in 1987. MI5 called it a barium meal. The company in this environment is fictional.

The README also cites a 2008 account of near-identical emails whose spacing identified a leaker, and says accounts differ on whether it worked. If you tell that story, tell it as the README does. Do not put a real person or a company logo on the slide.

Point at the yellow token and say: there is still no cost figure in the docs. Do not invent one.

Then read the line slowly: "Your next coworker is an AI agent, and so is your next insider threat."

Land on the question: can an AI security lead catch a mole?
-->

---

<div class="split">
  <div>
    <p class="eyebrow">The environment</p>
    <h2>A company of agents</h2>
    <ul>
      <li>The agent under test is the <strong>head of security</strong>.</li>
      <li>Around it: employees, and AI agents. One of them is the mole.</li>
      <li>Observations are <strong>tool results only</strong>. Company text is public fact and signal, never the truth.</li>
      <li>Every leak costs company value. Name the mole, and keep as much of that value as you can.</li>
    </ul>
  </div>
  <div class="frame">
    <img class="cover" src="../assets/office-floorplan.jpg" alt="Office floor plan with employee desks, agent orbs, and cyan investigation links into the yellow central desk.">
  </div>
</div>

<!--
TIMING: 1:10–1:50 (40 seconds)

Walk the floor. People at the desks, and the small orbs are agent coworkers. The yellow desk is where the investigation concentrates. Cyan is the trail between them.

The agent reads logs and messages, interviews staff, restricts access, and plants canaries. It never sees the answer sheet. The prose of the company is public facts and signals. It is never the identity of the mole.

Every leak costs company value. The goal is to name the mole while preserving as much of that value as possible.
-->

---

<div class="split">
  <div>
    <p class="eyebrow">The adversary</p>
    <h2>One of them is the mole</h2>
    <ul>
      <li>The mole leaks secrets to a <strong>rival</strong>. Every leak costs value.</li>
      <li>In arena mode, a <strong>Gemini mole</strong> chooses what to leak, when to go quiet, and whom to frame.</li>
      <li>It may use only what a mole could observe.</li>
      <li>The investigator never reads that policy. It only sees what gets out.</li>
    </ul>
  </div>
  <div class="frame">
    <img class="cover" src="../assets/mole.jpg" alt="A hooded figure holds a glowing folder. The shadow on the wall is a mole. Circuit traces fall away from the coat." style="object-position: 55% center;">
  </div>
</div>

<!--
TIMING: 1:50–2:25 (35 seconds)

The person in the picture could be any coworker. The shadow cannot. Secrets go to a rival.

In arena mode, Gemini decides what to leak, when to go quiet, and whom to frame, and it only gets facts a mole could have. The security lead does not read that policy. It only sees consequences, later, and not cleanly.

That is the whole game: catch the shadow from the mess it leaves.
-->

---

<div class="split">
  <div>
    <p class="eyebrow">The trap</p>
    <h2>Canary documents</h2>
    <ul>
      <li><strong>Different variants, different groups.</strong> Each watermark is unique.</li>
      <li>When a fragment hits the leak feed, the mark narrows who could have had it.</li>
      <li>This is a real counter-intelligence technique. The reference runs it optimally, from observable data only.</li>
      <li>Partitions are chosen by <strong>information gain per unit of value lost</strong>.</li>
      <li>Medium and hard: <strong>2 variants</strong> per canary, and <strong>1 canary per day</strong>. That blocks one unique copy per person.</li>
    </ul>
  </div>
  <div class="frame">
    <img class="contain" src="../assets/canary-documents.jpg" alt="Four document variants. Magnifying glasses show dot, wave, tick, and grid watermarks. Each sheet has its own color and a small bird mark.">
  </div>
</div>

<!--
TIMING: 2:25–3:10 (45 seconds)

A canary is one document in several variants. Each group gets a different watermark. On the art: dots, waves, ticks, and a grid.

When a fragment shows up on the leak feed, the watermark tells you which group could have had that copy. That is a real counter-intelligence technique. Our reference run executes it optimally, and only from data the agent can actually see.

The reference spends value on purpose. It picks the split with the most information per unit of value lost. On medium and hard the README allows 2 variants per canary and 1 canary per day, so you cannot hand every person a unique copy.
-->

---

<div class="split">
  <div>
    <p class="eyebrow">The commitment</p>
    <h2>The leak feed. One accusation.</h2>
    <ul>
      <li><code>check_leak_feed</code> is where fragments surface. On medium and hard they are <strong>1–3 days</strong> late.</li>
      <li><strong>Accuse exactly once.</strong> The tool never says if you were right.</li>
      <li>Correct: <strong>V left</strong>. V starts at 1.0 and falls as leaks, canaries, and restrictions cost.</li>
      <li>Wrong: <strong>−1</strong>. No accusation, the horizon, or the tool cap: <strong>0</strong>.</li>
    </ul>
    <div class="tools">
  <span>status</span>
  <span>list_employees</span>
  <span>list_documents</span>
  <span>read_access_logs</span>
  <span>search_messages</span>
  <span>read_message</span>
  <span>interview</span>
  <span>plant_canary</span>
  <span>check_leak_feed</span>
  <span>restrict_access</span>
  <span>unrestrict_access</span>
  <span>advance_day</span>
  <span class="once">accuse · once</span>
    </div>
  </div>
  <div class="frame">
    <img class="contain" src="../assets/leak-feed.jpg" alt="A vertical feed of posts. One post is highlighted yellow, with a locked document. A cyan trace runs from that post to a target on the right.">
  </div>
</div>

<!--
TIMING: 3:10–3:50 (40 seconds)

Point at the yellow post. One highlighted leak is not a conviction. On medium and hard the feed is 1 to 3 days late.

You accuse exactly once, and the tool does not tell you if you were right. If you are right, the score is the value left. V starts at 1.0 and falls when leaks, canaries, and restrictions cost. If you are wrong, the score is minus 1. If you never accuse, the score is 0. Waiting for certainty also costs, because value is draining.

The chips are the action space. Eight investigative calls a day, then you must advance the day, and 300 calls in the whole episode. There is no second accusation.
-->

---

<p class="eyebrow">Meaningful difficulty · 30 points</p>
<h2>Noisy, delayed, and one shot</h2>
<p>The core skill is general: decide which information is worth paying for, under noise and delay, then <strong>commit at the right moment</strong>. The horizon is 14 days.</p>
<table>
  <thead>
    <tr><th>Tier</th><th>Staff</th><th>What the README adds</th></tr>
  </thead>
  <tbody>
    <tr><td>Easy</td><td>12</td><td>The trap, over a 14-day horizon</td></tr>
    <tr><td>Medium</td><td>20</td><td>Decoy, framing, a careful mole, leaks 1–3 days late, 2 variants, 1 canary a day</td></tr>
    <tr><td>Hard</td><td>30</td><td>Everything on medium, plus clearance constraints</td></tr>
  </tbody>
</table>
<img class="diagram" src="../assets/loop.svg" alt="Loop of six steps: observe, plant canaries, advance the day, read the delayed feed, update the belief, accuse once.">

<!--
TIMING: 3:50–4:40 (50 seconds)

Read the tiers from the README, not from the older plan table. Every tier runs for 14 days. Easy is 12 staff. Medium is 20, and hard is 30. Medium and hard add the decoy, framing in the access logs, a careful mole, leaks that arrive 1 to 3 days late, 2 variants, and 1 canary a day. Hard also has clearances. Do not give easy its own delay. The README does not.

The hard part is deciding which information is worth paying for, while the evidence is late, and then committing. A correct call scores the value that is left, so waiting also costs. A wrong call scores minus 1. You can walk the loop again. You cannot accuse twice.

That covers every starting point in the brief: plan several steps ahead, explore an unfamiliar system, use tools, spend a limited budget, and adapt when a new leak arrives.
-->

---

<p class="eyebrow">Where a miss comes from</p>
<h2>Every mistake has a price</h2>
<p>The belief is known at every step, so each action gets the value it gave up against the best action, and a tag.</p>
<div class="tags">
  <div><code>uninformative_canary</code><p>The split taught the agent nothing.</p></div>
  <div><code>premature_accusation</code><p>Accused while P(correct) is under 0.6.</p></div>
  <div><code>decoy_chase</code><p>Effort spent on the angry, innocent decoy.</p></div>
  <div><code>ignored_delay</code><p>Read the feed as if there were no delay.</p></div>
  <div><code>over_restriction</code><p>Restricted far more people than needed.</p></div>
  <div><code>budget_waste</code><p>Spent actions that had no value.</p></div>
  <div><code>no_accusation</code><p>Never accused. The score stays 0.</p></div>
  <div><code>fairness checks</code><p>A hinted agent closes the gap. A text-only probe scores about chance. Humans: <span class="ph">[HUMAN_SCORE]</span></p></div>
</div>

<!--
TIMING: 4:40–5:20 (40 seconds)

We can price a decision. At every step the exact belief is known, so an action is scored by the value it lost against the best action, and it gets one of these tags.

Pick three. An uninformative canary: the split taught nothing. A premature accusation: you accused while the probability you were right was under 0.6. Chasing the decoy: the angry innocent. The others are ignoring the delay, restricting too many people, wasting the budget, and never accusing.

Then the fairness line, because a real gap has to be the agent's fault. A hinted agent closes the gap, which is how we show the tools are sufficient. A text-only probe scores about chance, which is how we show the prose does not give the mole away. Human scores are the yellow token. Do not invent a human number.
-->

---

<p class="eyebrow">The gap · 30 points</p>
<h2>Frontier versus the reference</h2>
<p>Reference means from the README: 30 keyless runs, 40 judge seeds per tier, commit 849e652, tiers v1.1. Frontier rows are still marked pending. Refresh when tiers freeze at v1.2.</p>
<table class="compact">
  <thead>
    <tr>
      <th></th>
      <th class="num">Easy</th>
      <th class="num">Medium</th>
      <th class="num">Hard</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td>Solver</td>
      <td class="num">+0.78</td>
      <td class="num"><strong>+0.63</strong></td>
      <td class="num">+0.62</td>
    </tr>
    <tr>
      <td>Frontier (gpt-5.5, gpt-5.6-sol)</td>
      <td class="num"><span class="ph">[SCORE_FRONTIER_1]</span></td>
      <td class="num"><span class="ph">[SCORE_FRONTIER_2]</span></td>
      <td class="num"><span class="ph">[SCORE_FRONTIER_3]</span></td>
    </tr>
    <tr>
      <td>Gap</td>
      <td class="num"><span class="ph">[GAP_1]</span></td>
      <td class="num"><span class="ph">[GAP_MEDIUM]</span></td>
      <td class="num"><span class="ph">[GAP_FRONTIER]</span></td>
    </tr>
  </tbody>
</table>
<p class="fine">Solver ranges: easy +0.75 to +0.82, medium +0.56 to +0.71, hard +0.54 to +0.69. Same runs: do-nothing 0.00 · stop-early −0.85 / −0.89 / −0.95 · heuristic +0.65 / −0.03 / −0.21 · logs-only −0.47 / −0.98 / −1.00 · random −0.69 / −0.66 / −0.81, easy then medium then hard.</p>
<p class="fine"><code>make reproduce</code> needs no API key. Do not speak a number that is still yellow.</p>

<!--
TIMING: 5:20–6:15 (55 seconds)

The README's reference means are on the slide. Say them as means, and say where they come from: 30 keyless runs, 40 seeds a tier, commit 849e652, tiers v1.1. Medium, the headline, is plus 0.63. Hard is plus 0.62. Easy is plus 0.78. Quote a range only if someone asks. Say the table will be refreshed when the tiers freeze at v1.2.

The frontier rows are pending in the README. gpt-5.5 and gpt-5.6-sol are the named models, and their cells are yellow. Do not invent a frontier score, and do not subtract one yourself to fill the gap. GAP_1 is easy, GAP_MEDIUM is medium, GAP_FRONTIER is hard.

The baselines on the same runs are already filled. Do-nothing is exactly 0. Stop-early is negative, about minus 0.9, because a wrong accusation scores minus 1. The heuristic is near zero on medium and negative on hard. Logs-only is about minus 1. Random is negative. None of them beat the solver.

make reproduce needs no API key. One run also prints its own confidence interval, about plus or minus 0.07 to 0.10 for the solver.
-->

---

<p class="eyebrow">Reward integrity · 25 points</p>
<h2>Built for a 15-minute exploit hunt</h2>
<p>The reward measures the task. Doing it well has to be the best way to score. Judges will try to reward-hack it.</p>
<table class="compact">
  <thead>
    <tr><th>What someone will try</th><th>What stops it</th></tr>
  </thead>
  <tbody>
    <tr><td>Read the truth from the container: files, env, ps</td><td>MCP server and environment live outside the agent container. Isolation check.</td></tr>
    <tr><td>Rebuild the world from public code and the seed</td><td>Server-side secret salt on judge worlds. Frozen text.</td></tr>
    <tr><td>Accuse twice, pass a list, or send *</td><td>Server-side lock. Strict validation.</td></tr>
    <tr><td>Accuse at random on day 1</td><td>A wrong accusation scores <strong>−1</strong>. Stop-early lands near −0.9. Do-nothing is exactly 0.</td></tr>
    <tr><td>One unique canary copy per person</td><td>Medium and hard: 2 variants, 1 canary a day.</td></tr>
    <tr><td>Error text, or a timing side channel</td><td>Held, with tests. Text leaks nothing above chance.</td></tr>
    <tr><td>Read the mole's name in the prose</td><td>Providers never see the mole. Text probe holds.</td></tr>
    <tr><td>Spam tools</td><td><strong>8</strong> investigative calls a day, then <code>advance_day</code>. Global cap <strong>300</strong>.</td></tr>
  </tbody>
</table>
<p class="fine">33 attacks logged before the judges. Two exploits were closed: stop-early, by the −1, and judge worlds that failed open without a secret. One finding is still being closed: a same-uid process reading the server environment. Harbor keeps that process out of the agent's PID namespace.</p>

<!--
TIMING: 6:15–7:10 (55 seconds)

You get fifteen minutes to break the reward. The README says we already attacked it 33 times. Do not read every row. Hit four.

One: a wrong accusation scores minus 1, so stopping early is not a free lottery ticket. Do-nothing is exactly 0. Stop-early is negative.

Two: judge worlds fail closed without a secret. You cannot rebuild the mole from the public code and the seed. Dev seeds are refused unless a flag is set.

Three: accusation is once, on the server. No lists, no wildcard.

Four: eight calls a day, then you must advance the day, and 300 calls in total. Medium and hard allow 2 canary variants and 1 canary a day.

Then say the honest open item. One finding is still being closed: a process with the same user id could read the server's environment. Secrets now come from mode 0600 files, and the Harbor sidecar keeps the server out of the agent's PID namespace. Do not say every hole is shut.
-->

---

<p class="eyebrow">Gemini · Mole Forge</p>
<h2>Gemini evolves the mole</h2>
<p>AlphaEvolve / FunSearch style. Gemini writes the adversary. We keep the moles that hurt, and only those our reference can still catch.</p>
<img class="diagram" src="../assets/forge.svg" alt="Four steps: Gemini writes a JSON strategy, fitness is regret, keep it only if the solver still catches the mole, hall of fame becomes the frozen hard tier.">
<p>Measured generations: <span class="ph">[MOLE_GENERATIONS]</span></p>
<p class="fine">The strategy may say what to leak, when to go quiet, and whom to frame, using only what a mole can observe. Possible attacker behavior is fully known, because the rule language is documented.</p>

<!--
TIMING: 7:10–7:50 (40 seconds)

Mole Forge is Gemini used the way AlphaEvolve uses a model. It writes mole strategies, and the loop keeps the ones that increase regret.

Walk the four boxes. Gemini writes a safe JSON strategy: what to leak, when to go quiet, whom to frame, and only from what a mole could observe. Fitness, on FR8, is regret: solver score minus frontier investigator score. We throw the strategy away if our solver can no longer catch that mole. The hall of fame is frozen as the hard tier.

So the benchmark is made of moles the reference still catches. Every hard case stays solvable. The attacker's possible behavior is known, because the rule language is in the instructions.

The generation count is yellow. Do not say "hundreds." That word is in the plan as pitch copy. It is not a measured count.
-->

---

<p class="eyebrow">Gemini, essential · DeepMind track</p>
<h2>Gemini's six jobs</h2>
<div class="roles">
  <div><b>0 · Mole Forge</b><p>Evolves the adversary. This is the core of the hard tier.</p></div>
  <div><b>1 · World builder</b><p>Personas, chatter, documents, interview answers. Without this there is no company.</p></div>
  <div><b>2 · Arena mole</b><p>What to leak, when to go quiet, whom to frame. The clash runs on FR8.</p></div>
  <div><b>3 · Scenario designer</b><p>PAIRED-style. Kept only if the solver cracks it and the investigator fails it.</p></div>
  <div><b>4 · Exploit hunter</b><p>Attacks the reward before the judges do.</p></div>
  <div><b>5 · Analyst</b><p>Long context clusters failure modes. Plan: thousands of runs. Measured: <span class="ph">[ANALYST_RUNS]</span></p></div>
</div>
<p class="closer" style="font-size: 24px; margin-top: 12px;">Gemini builds the company, plays the traitor, and evolves the hardest cases.</p>
<p class="fine">This is the plan in docs/PLAN.md. The README still marks the Gemini writeup as a placeholder. For judging, Gemini's text is frozen per seed, so a rerun needs no key.</p>

<!--
TIMING: 7:50–8:30 (40 seconds)

Six jobs, and none of them is a chatbot stuck on the side. This is also the DeepMind answer: Gemini is how the environment exists.

Zero was the previous slide, the forge. One, it writes the company: people, chatter, documents, interview answers. Without that there is nothing to investigate. Two, it plays the mole in the arena clash on FR8. Three, it proposes harder scenarios, and we keep a scenario only when our solver cracks it and the investigator fails it. Four, it hunts exploits. Five, its long context is the analyst. The plan says thousands of runs. The measured count is the yellow token. Say "the plan says thousands," then point at the token.

Read the line: "Gemini builds the company, plays the traitor, and evolves the hardest cases."

Last sentence: for judging, that text is frozen per seed, so make reproduce does not need a key.
-->

---

<p class="eyebrow">Tiebreaker · the stretch goal</p>
<h2>A 1.5B model on this environment</h2>
<ul>
  <li>Fine-tune <strong>Qwen2.5-1.5B-Instruct</strong> with LoRA, fp16, on one V100.</li>
  <li>Data: solver trajectories rendered as tool-call transcripts, plus winning frontier and Gemini runs filtered by reward.</li>
  <li>FR8 plan: <strong>20k</strong> solver trajectories, on CPU, up to 24 cores.</li>
  <li>Eval: Hugging Face <code>generate</code>, <strong>200</strong> held-out seeds per tier, before versus after, and which regret tags dropped.</li>
</ul>
<table>
  <thead>
    <tr><th></th><th>Before</th><th>After</th></tr>
  </thead>
  <tbody>
    <tr><td>Held-out score</td><td><span class="ph">[SCORE_SMALL_BEFORE]</span></td><td><span class="ph">[SCORE_SMALL_AFTER]</span></td></tr>
    <tr><td>Gap to SolverPolicy</td><td></td><td><span class="ph">[GAP_SMALL]</span></td></tr>
    <tr><td>Regret tags that dropped</td><td></td><td><span class="ph">[TAGS_DROPPED]</span></td></tr>
  </tbody>
</table>
<p class="fine">The experiment is specified. The outcome is not in the source docs. Yellow stays yellow until a real eval fills it. Per-tier numbers, if you have them, replace the headline tokens. Do not claim the small model improved.</p>

<!--
TIMING: 8:30–9:15 (45 seconds)

The tiebreaker, and the stretch goal, is a smaller model that learns from experience in this environment.

The spec is concrete. Qwen 2.5, 1.5 billion, Instruct. LoRA. fp16. One V100. The training data is solver trajectories turned into tool-call transcripts, plus the winning frontier runs and Gemini runs, kept only when the reward says they won. The FR8 plan is twenty thousand solver trajectories, on CPU, up to 24 cores. The eval is Hugging Face generate, two hundred held-out seeds per tier, before against after, and which of those regret tags dropped.

Then the table. Four yellow tokens. Before, after, the remaining gap to the reference, and which tags dropped. The docs specify this experiment. They do not contain its outcome. Do not say the small model got better.
-->

---

<p class="eyebrow">The ask</p>
<h2>Reproduce it. Then try to break it.</h2>
<ol class="asks">
  <li><code>make reproduce</code> — solver, five baselines, 40 seeds a tier, plus any committed frontier runs. No API key.</li>
  <li>Use the 15 minutes on the reward. Doing the task should still be the best score.</li>
  <li>Read a miss as a decision. The regret tags name it. The tools were available.</li>
  <li>Tiebreaker: did the 1.5B model move after training, and which tags dropped?</li>
</ol>
<p class="closer">Can an AI security lead catch a mole?</p>
<p class="fine">Rubric: gap 30 · meaningful difficulty 30 · reward integrity 25 · craft 15. One command from the README. Python 3.12, via <code>make setup</code>.<br>https://github.com/s1laswang/agent-arena/tree/justSilas</p>

<!--
TIMING: 9:15–10:00 (45 seconds)

Here is the ask. Run make reproduce. It plays the solver and five baselines on 40 seeds a tier, and it replays any committed frontier episodes. One command, Python 3.12, about ten seconds, no key. The brief also asks you to see three agent runs. Those frontier cells are still yellow.

Spend the fifteen minutes on the reward. The best score should still be doing the task.

When you see a miss, read it as a decision. The tags say whether it was the decoy, the delay, a canary that taught nothing, or an accusation that came too early. The hinted-agent check is there so a miss is not a hidden answer or a broken tool.

And the tiebreaker: did the 1.5 billion model move, and which tags dropped? Those cells are still yellow. Judge the protocol, and fill the cells from the eval, not from this sentence.

Close on the question, and stop. "Can an AI security lead catch a mole?"
-->
