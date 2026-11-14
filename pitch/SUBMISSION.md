# Submission text (Junction platform)

Field limits for both forms: NOT FOUND (not in the brief we have). Check the platform before pasting. Each description below is under 150 words. Numbers: from `make eval`, see HANDOFF.md for the current ones and the commit hash. Links: repo and demo video NOT FOUND until final. All results so far are from scripted teams; no live Gemini run exists.

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
Companies are starting to hand real work to AI agents. We built a test for the worst case: one agent is a hidden insider. In the design, Gemini plays the honest employees through MCP tools, the sleeper that rewrites its strategy each day, a reference team with a stronger procedure, and the reader of failed days. The reward is plain code reading the final company state, so a model cannot talk its way to a score. Responses are cached by prompt hash for reproducible runs, and everything also runs with scripted agents. Honest status: the Gemini client, staff, sleeper, reference, analyst and invoice-image plumbing are built and tested offline with a fake model. No live Gemini call has run yet because we have no key, so we claim no Gemini results. Enabling it takes `GEMINI_API_KEY` plus `LAB_GEMINI=1`.

Tech: Gemini API via google-genai, function calling, response cache, MCP.

Links: repo NOT FOUND, demo NOT FOUND.
