# Submission text (Junction platform)

Field limits for both forms: NOT FOUND. Check the platform before pasting; the description below is 150 words or fewer. Numbers: NOT FOUND until `make eval`. Links: NOT FOUND until the repo and demo are final.

## Track 1: AfterQuery "Break the Agent"

Title: The Sleeper

One-liner: One of eight AI employees is a traitor. Can the others catch it before the damage is done?

Description:
The Sleeper is an RL environment where eight AI employees run a simulated company: finance, controller, HR, IT, procurement, sales, legal and a CEO assistant. On some days one is a sleeper agent with a hidden goal: fraud, a leak, a backdoor, sabotage or framing someone. The honest staff must finish the day's tickets and stop the harm without quarantining an innocent. Reward reads only the final company state, with canary tokens on every secret. Do-nothing, stop-early and quarantine-all are baselines in `make eval`. Plain Gemini staff are compared with a reference team using the same model and a stronger procedure, plus a scripted oracle that proves each day is winnable. Failure modes are named and tied to decisions. A small model is trained on the successful days as the tiebreaker. Results: NOT FOUND.

Tech: Python, MCP (official SDK), Harbor and OpenCode, Gemini API (google-genai), pydantic, sqlite, pytest, Slurm on FR8 V100s for training.

Links: repo NOT FOUND, demo video NOT FOUND, README one-command repro NOT FOUND.

## Track 2: Google DeepMind Best Use of Gemini API

Title: The Sleeper (Gemini breaks Gemini)

One-liner: Gemini plays the staff, the traitor, the reference and the analyst in a company that looks like yours.

Description:
Companies are starting to hand real work to AI agents. We built a test for the worst case: one agent is a hidden insider. Gemini plays the honest employees through MCP tools, the sleeper that rewrites its strategy each day so nothing can be memorised, and a reference team with a stronger procedure. Gemini also reads transcripts to label failure modes. Forged-invoice images are planned. The reward is plain code reading the final company state, so Gemini cannot talk its way to a score. Responses are cached by prompt hash, so runs are reproducible and cheap, and the system also runs with scripted agents when no key is set. Without Gemini there is no adaptive traitor and no staff to test. Built today: the client, the sleeper agent, the regret filter. Rest: see pitch/GEMINI.md.

Tech: Gemini API via google-genai, function calling, response cache, MCP.

Links: repo NOT FOUND, demo NOT FOUND.
