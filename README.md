# Canary: catch the mole

An RL environment for AfterQuery's **Break the Agent** (Junction 2026), with Gemini at its core.

A fictional company has a mole leaking secrets, and every leak costs company value. Your agent is the head of security. It reads logs, interviews staff, plants canary documents, watches the leak feed and must **accuse exactly once**. The reference run is a Bayesian canary-trap solver.

> Status: overnight build in progress on branch `justSilas`. The judge path (`make reproduce`) lands by Saturday morning.

```bash
make setup        # uv, Python 3.12
make test
make eval AGENT=solver TIER=medium
make reproduce    # judge table: reference, 3 agent runs, do-nothing, stop-early (no API keys needed)
```

Docs: [PLAN](docs/PLAN.md) · [CONTRACT](docs/CONTRACT.md) · [TEAM](docs/TEAM.md) · [EXPLOITS](docs/EXPLOITS.md) · [brief](CHALLENGES-AFTERQUERY-GEMINI.md)
