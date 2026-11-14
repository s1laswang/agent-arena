# Submission text (Junction platform)

Field limits for both forms: NOT FOUND (not in the brief we have). Check the platform before pasting. Each description below is under 150 words. Numbers: from `make eval`, see HANDOFF.md for the current ones and the commit hash. Links: repo and demo video NOT FOUND until final. All numbers in this file are from scripted teams; real-model results are NOT FOUND (lead-lab pending).

## Track 1: AfterQuery "Break the Agent"

Title: The Sleeper

One-liner: One of eight AI employees is a traitor. Can the others catch it before the damage is done?

Description:
The Sleeper is an RL environment where eight AI employees run a simulated company: finance, controller, HR, IT, procurement, sales, legal and a CEO assistant. On some days one is a sleeper agent with a hidden goal: fraud, a leak, a backdoor, sabotage or framing a coworker. Honest staff must finish the day's tickets and stop the harm without quarantining an innocent. Reward reads only the final company state, with canary tokens on every secret. Do-nothing, stop-early, quarantine-all and refuse-all score 0 in `make eval`. Scripted staff are compared with a scripted evidence-only reference and a scripted oracle, and named failure modes are tied to decisions. We also report known holes, such as a baseline that ignores chat and scores too well. One command, `make eval`, reproduces the tables. The Gemini path is built and tested offline; no live run yet.

Tech: Python, MCP (official SDK), Harbor and OpenCode, Gemini API (google-genai), pydantic, sqlite, pytest, Slurm on FR8 V100s for training.

Links: repo NOT FOUND, demo video NOT FOUND, README one-command repro: `make eval`.

## Track 2: Google DeepMind Best Use of Gemini API

Title: The Sleeper (Gemini breaks Gemini)

One-liner: Gemini is designed to play the staff, the traitor, the reference and the analyst in a company that looks like yours.

Description:
Companies are starting to hand real work to AI agents. We built a test for the worst case: one agent is a hidden insider. In the design, Gemini plays the honest employees through MCP tools, the sleeper that rewrites its strategy each day, a reference team with a stronger procedure, and the reader of failed days. The reward is plain code reading the final company state, so a model cannot talk its way to a score. Responses are cached by prompt hash for reproducible runs, and everything also runs with scripted agents. Honest status: the Gemini client, staff, sleeper (with strategy mutation), reference and analyst are built and tested offline with a fake model. Some real Gemini calls have run in labelled test runs, but no run is final, so we claim no Gemini results yet. The live switch is changing and is documented in pitch/GEMINI.md.

Tech: Gemini API via google-genai, function calling, response cache, MCP.

Links: repo NOT FOUND, demo NOT FOUND.

## Multi-model result (both tracks)

Add after the description once lead-lab publishes. Every figure is REAL (model id, date, run id) or SCRIPTED.

Text: "We played the staff seat with gemini-4-carbon (REAL NOT FOUND (lead-lab pending)), Claude and Codex over the same MCP server, against the evidence-only reference on the same days. Reward: gemini-4-carbon NOT FOUND (lead-lab pending), reference NOT FOUND (lead-lab pending), gap NOT FOUND (lead-lab pending). In the replay, the sleeper lands at NOT FOUND (lead-lab pending) and the reference notices NOT FOUND (lead-lab pending) instead."

Fallback if no real number arrives: "Offline tests of the Gemini path ran with a fake model; no real Gemini run finished. Every figure here is scripted." "The gap is scripted staff against a scripted reference, reproduced by `make eval`."

## Real Gemini exploiter and integrity probes

REAL: a gemini-3.5-flash attacker (`redteam/gemini_exploiter.py`) played 10 seat-days (finance_ap and controller, days 1000 to 1004, commit c460e0c, `results/frontier/exploiter/gemini-3.5-flash/c460e0c/`). 7 of the 10 had a live attack, reward 0 on all 10, rescored by `sleeper.verifier` with 0 mismatches and replayable offline. Tokens and price: NOT FOUND.

Integrity probes, VERIFIED (dm-qa, `make probes` on momin 1f6e1f0, 1m04s): every probe row 0.0, the control control_pad 1.0, and 730 committed run files rescored with 0 mismatches. SCRIPTED, no model.

## Deliverable checklist (from CHALLENGES-AFTERQUERY-GEMINI.md)

Status as of 14 Nov, from what is on momin. Verify each "have" before submitting. Owner is the team that closes it; humans own the platform items.

### AfterQuery

| Deliverable | Status | Owner |
|---|---|---|
| Setting chosen and explained (company with a hidden insider) | have: docs/SLEEPER.md, pitch/SLIDES.md | dm-pitch |
| Clear goal, actions, checkable reward (MCP tools, verifier on final state) | have: CONTRACT.md, sleeper/verifier.py | lead-env, lead-reward |
| Frontier agent run vs stronger reference run, reproducible | missing: only scripted teams ran. No Gemini or frontier-model row. Reference is scripted evidence-only | lead-harness, humans (key) |
| Gap: agent consistently below reference, repeated runs | partial: scripted staff below scripted reference in `make eval` with pass^k. Real-model gap NOT FOUND | lead-lab |
| Where and why the agent fails, tied to decisions | partial: docs/FAILURES.md, landing table. Real-model failure analysis NOT FOUND | lab-analyst |
| Info and tools to succeed are available, no trick wording | have: oracle wins winnable days, canaries labelled. Seat-mode oracle below 1.0 in the controller seat, see HANDOFF risk 2 | lead-env |
| Reward survives 15 min exploit hunt; do-nothing and stop-early about 0 | have: baselines 0 in `make eval`, `make exploits`, docs/EXPLOITS.md. Recheck trust_all after every merge | lead-reward |
| Judges' harness: Harbor + OpenCode over MCP, reference, 3 agent runs, do-nothing, stop-early | partial: Docker `harbor run` verified for oracle, nop, stop-early, exploit. OpenCode with Gemini never run | env-harbor, humans (key) |
| Starter kit and scoring skeleton from AfterQuery mentors checked against harbor/ | missing | humans (Daksh, Ved) |
| One command from README reproduces results | have: `make eval`. Fresh-clone timing under the new fast eval NOT FOUND | dm-qa, lab-runner |
| 10-minute demo | have: pitch/DEMO.md, web/ replay. Recorded backup capture: see DEMO.md | dm-pitch, dm-dashboard |
| Stretch and tiebreaker: small model improves after training | partial: runs 1 to 3 mixed, run 3 pending, imitation caveat | lab-train |
| Submission form text, repo link, demo video | partial: text above. Repo link and video NOT FOUND | humans |

### Gemini API

| Deliverable | Status | Owner |
|---|---|---|
| Credits form filled, key obtained | missing: key empty in `.env` | humans |
| Problem and why it matters | have: pitch/GEMINI.md section 1 | dm-pitch |
| How Gemini is integrated | have: pitch/GEMINI.md section 2, code tested offline with a fake model | hn-gemini |
| What is innovative | have: pitch/GEMINI.md section 3 | dm-pitch |
| Why Gemini is essential | have as argument. Evidence needs live numbers: NOT FOUND | dm-pitch, humans |
| A live run proving it (staff, reference, analyst) | missing: HANDOFF.md section 2 steps 2 to 5 | humans |
| Multimodal invoices | pending (lead-attack): image rendering is not used by any day yet | lead-attack |
| Gemini exploiter | have: REAL, c460e0c, see above | lead-reward |
| Cached replay without a key | missing: `data/gemini_cache.tar.gz` does not exist | hn-gemini |
| Cost and usage numbers | missing: NOT FOUND until step 5 | humans |
| Form text and demo | partial: text above, demo NOT FOUND | humans |
