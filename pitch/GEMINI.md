# Google DeepMind: Best Use of Gemini API

Project: The Sleeper. Status key: BUILT means merged into `momin` with a test; PLANNED means not written yet. Update before submitting. Numbers come from `make eval` (see DEMO.md), else NOT FOUND. All eval teams today are scripted; no keyed Gemini run exists yet.

## 1. The problem and why it matters

Companies are starting to run real work through teams of AI agents: paying invoices, changing bank details, granting access. An agent with a hidden goal, or a compromised one, can move money or leak a secret while looking like a normal coworker. Most agent tests check one agent on one task. They do not test whether a group of agents can notice an insider and stop it without accusing an innocent.

The Sleeper is an environment for that. Eight AI employees run a simulated company. Some days one is a sleeper with a hidden goal (fraud, leak, backdoor, sabotage, framing). The honest staff must finish the day's tickets and stop the harm. The reward reads only the final company state, so claims in chat do not count.

## 2. How the Gemini API is integrated

To run the Gemini path: `GEMINI_API_KEY` and `LAB_GEMINI=1` (the key alone leaves rows scripted). Wiring is verified offline with a scripted fake model (`tests/test_gemini_team.py`), which proves the plumbing and nothing about how the real model behaves. First live check once a key exists: `PYTHONPATH=. .venv/bin/python scripts/gemini_smoke.py`. Under `SLEEPER_OFFLINE=1`, a cache miss raises for staff and reference but the sleeper agent and analyst explanation fall back to scripted.


- BUILT, in `momin`, tested offline only, NOT yet run against the live Gemini API (no key):
  - `agents/gemini.py` (a2b1cdd): google-genai client, function calling, tool loop, per-role model by env var, retries, prompt-hash cache. It also sends image parts (`Part.from_bytes`) so tool results can carry images.
  - `agents/staff.py` (7597c39): `ScriptedStaff` and `GeminiStaff` (8 role prompts, Gemini path used only with a key).
  - `agents/sleeper_agent.py` (4ae12a9): covert agent, Gemini strategy mutation with a key, scripted otherwise.
  - `agents/reference.py` (f4e4093): scripted oracle team. `agents/gemini_reference.py` (9146839): `GeminiReference`, the same model with the stronger procedure. The oracle is scripted, not Gemini.
  - `agents/analyst.py` (6308ca7): labels failures with Gemini when a key is set, rule-based otherwise.
  - `agents/images.py` (b6317f1): renders invoice PNGs for the forged-invoice attack. Whether a day uses them end to end: check `fraud.forged_scanned_invoice` before claiming.
  - `sleeper/goals/` (5 goal kinds), `sleeper/regret.py` (ed59e04), `sleeper/events.py`, `sleeper/verifier.py`.
- Measured today (`make eval`, 20 days, 3 trials): scripted staff and scripted oracle only. No Gemini-run numbers exist: NOT FOUND.
- PLANNED / unconfirmed: a keyed run of Gemini staff, sleeper and reference; the multimodal attack verified live; cost per run.
- Gemini roles in the design:
  - Staff: Gemini plays each of the 8 seats through the same MCP tools a judge's agent would use.
  - Sleeper: Gemini writes and mutates its strategy per day so nothing can be memorised.
  - Reference: the same model inside a stronger operating procedure (enforced two-person checks, audit log read before approving, out-of-band verification).
  - Failure analyst: Gemini reads full transcripts offline and labels the failure modes. It never touches the reward.
  - Multimodal: forged invoice images and screenshots the agent must read. PLANNED.
- Reward and verifier are plain code, not a model.

## 3. What is innovative

- Gemini breaks Gemini: the attacker, the defenders and the reference are the same model family under different instructions and procedures.
- The attack is social, not a single prompt injection: the sleeper must persuade a second seat to complete a two-person action, and slow-burn attacks spread over several steps.
- The attacker is regret-filtered (`sleeper/regret.py`, built): a day is kept only if the reference or oracle can win it, so every failure is a real defender failure.
- The reward counts final company state with canary tokens, so one leaked byte is visible.
- Deterministic and reproducible: a day is a pure function of seed, sleeper seat and goal, and agent config, with cached model responses.

## 4. Why Gemini is essential

Remove Gemini and there is no sleeper that adapts, no staff that talk like coworkers, no reference to compare against, and no reader for thousands of transcripts and forged invoices. Scripted agents exist so the environment runs without a key, but they cannot produce new strategies each day, which is the point of the test. Long context is what lets the analyst read whole days, and native image input is what makes the forged-invoice attack possible. Cost and scale numbers: NOT FOUND until measured.
