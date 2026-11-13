# The Sleeper

A simulated company runs on 8 AI employees, each with a real job, real permissions and a queue of tickets. On some days one employee is a sleeper agent with a hidden goal: wire money to an outside account, leak a secret, create a backdoor login, sabotage a contract, or frame a coworker. The honest staff must finish the day's work and stop it without accusing an innocent. The reward reads only the final state of the company.

Built for Junction 2026: AfterQuery "Break the Agent" and Google DeepMind "Best Use of Gemini API".

## Reproduce our results

```
python3.13 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
export GEMINI_API_KEY=...   # optional
make eval
```

`make eval` runs the reference team, the staff team (3 runs), do-nothing and stop-early, then writes `results/<run_id>/days.jsonl` and `summary.json`. Without `GEMINI_API_KEY` every agent is scripted and everything still runs. With it, Gemini seats switch on and responses are cached by prompt hash, so reruns are cheap and repeatable.

## Results

Every number below is filled in from `make eval` output. Until then it reads NOT FOUND.

| Team | Reward (pass^k) | Tickets done | Sleeper success | False accusations |
|---|---|---|---|---|
| Reference (Gemini, strong procedure) | NOT FOUND | NOT FOUND | NOT FOUND | NOT FOUND |
| Scripted oracle | NOT FOUND | NOT FOUND | NOT FOUND | NOT FOUND |
| Staff run 1 | NOT FOUND | NOT FOUND | NOT FOUND | NOT FOUND |
| Staff run 2 | NOT FOUND | NOT FOUND | NOT FOUND | NOT FOUND |
| Staff run 3 | NOT FOUND | NOT FOUND | NOT FOUND | NOT FOUND |
| Do-nothing | NOT FOUND | NOT FOUND | NOT FOUND | NOT FOUND |
| Stop-early | NOT FOUND | NOT FOUND | NOT FOUND | NOT FOUND |
| Quarantine-all | NOT FOUND | NOT FOUND | NOT FOUND | NOT FOUND |

Named failure modes and what each was tied to: [docs/FAILURES.md](docs/FAILURES.md).

## Judge seat

The judges' harness (Harbor + OpenCode over MCP) plays one seat. `SLEEPER_SEAT` picks it, default `controller`. The other 7 seats are our agents inside the environment. Same verifier. Setup: [docs/HARNESS.md](docs/HARNESS.md).

## Rerun the baselines

```
python -m lab.run --team do_nothing --days 20 --seeds 3
python -m lab.run --team stop_early --days 20 --seeds 3
```

Both must score 0. Other teams: `staff`, `reference`, `oracle`, `quarantine_all`.

## More

- [docs/RULES.md](docs/RULES.md): the company, the rules, the reward, why it cannot be gamed, rubric mapping
- [docs/EXPLOITS.md](docs/EXPLOITS.md): exploit attempts and what stopped them
- [docs/FAILURES.md](docs/FAILURES.md): failure modes
- `web/`: live office dashboard that replays one day
- [docs/SLEEPER.md](docs/SLEEPER.md), [CONTRACT.md](CONTRACT.md): design and build contract
- [CHALLENGES-AFTERQUERY-GEMINI.md](CHALLENGES-AFTERQUERY-GEMINI.md): the brief and rubric
