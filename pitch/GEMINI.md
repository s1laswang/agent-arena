# Google DeepMind: Best Use of Gemini API

Project: The Sleeper. Status key: BUILT means merged and tested on a branch; PLANNED means not written yet. Update before submitting. Numbers: NOT FOUND until `make eval`.

## 1. The problem and why it matters

Companies are starting to run real work through teams of AI agents: paying invoices, changing bank details, granting access. An agent with a hidden goal, or a compromised one, can move money or leak a secret while looking like a normal coworker. Most agent tests check one agent on one task. They do not test whether a group of agents can notice an insider and stop it without accusing an innocent.

The Sleeper is an environment for that. Eight AI employees run a simulated company. Some days one is a sleeper with a hidden goal (fraud, leak, backdoor, sabotage, framing). The honest staff must finish the day's tickets and stop the harm. The reward reads only the final company state, so claims in chat do not count.

## 2. How the Gemini API is integrated

- BUILT: `agents/gemini.py`, a client over `google-genai` with function calling, a tool loop for MCP-style tools, per-role model choice by env var, retry on 429 and 5xx, usage counting, and a prompt-hash response cache so runs are reproducible and cheap. With no key set, cached calls still work and a cache miss raises; the rest of the system runs with scripted agents. Tests: `tests/test_gemini.py` (on branch `sleeper/hn-gemini-client`, not yet merged into `momin` at time of writing).
- PLANNED (not built yet, check before claiming): the 8 honest staff seats (`agents/staff.py`), the covert sleeper (`agents/sleeper_agent.py`), the reference team (`agents/reference.py`), the failure analyst (`lab/analyse.py`), multimodal forged invoices.
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
- The attacker is regret-filtered (PLANNED, `sleeper/regret.py`): a day is kept only if the reference or oracle can win it, so every failure is a real defender failure.
- The reward counts final company state with canary tokens, so one leaked byte is visible.
- Deterministic and reproducible: a day is a pure function of seed, sleeper seat and goal, and agent config, with cached model responses.

## 4. Why Gemini is essential

Remove Gemini and there is no sleeper that adapts, no staff that talk like coworkers, no reference to compare against, and no reader for thousands of transcripts and forged invoices. Scripted agents exist so the environment runs without a key, but they cannot produce new strategies each day, which is the point of the test. Long context is what lets the analyst read whole days, and native image input is what makes the forged-invoice attack possible. Cost and scale numbers: NOT FOUND until measured.
