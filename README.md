# agent-arena: Junction 2026 entries

This repo holds two hackathon entries. Each one lives on its own branch. **This `main` branch has no code for either entry.** Pick the one you are judging below.

| Challenge | Entry | Branch | Start here |
|---|---|---|---|
| **AfterQuery: Break the Agent** | **Canary: catch the mole.** An RL environment where an AI head of security must find the one mole leaking documents, using canary traps, while company value bleeds away. It is scored against a Bayesian reference solver that uses the same public tools. | [`justSilas`](https://github.com/s1laswang/agent-arena/tree/justSilas) | [README → "For judges"](https://github.com/s1laswang/agent-arena/blob/justSilas/README.md) |
| **Google DeepMind: Best Use of Gemini API** | **Canary Lab.** Gemini's thinking level used as a controlled variable on the Canary benchmark, plus a Gemini red team validated by a positive control. Every Gemini call is logged. | [`gemini-track`](https://github.com/s1laswang/agent-arena/tree/gemini-track) | [docs/gemini/SUBMISSION.md](https://github.com/s1laswang/agent-arena/blob/gemini-track/docs/gemini/SUBMISSION.md) |

## Reproduce the AfterQuery entry (one command, no API keys)

```bash
git clone -c core.longpaths=true -b justSilas https://github.com/s1laswang/agent-arena.git && cd agent-arena
make setup && make reproduce
```

You need [uv](https://docs.astral.sh/uv/) and `make`. The Harbor + OpenCode/MCP instructions are in that branch's README. `-c core.longpaths=true` only matters on Windows, where some committed Harbor run folders are deeper than the default 260-character path limit; macOS and Linux ignore it.

## Same team, other challenges

- Valio Aimo "Trusted Trade Agents": [s1laswang/junction-aimo-agents](https://github.com/s1laswang/junction-aimo-agents)
- Meta "AI Glasses for Everyone, Everyday" (HoldUp): [s1laswang/junction-meta-glasses](https://github.com/s1laswang/junction-meta-glasses)

Both of those also use Gemini. Their Gemini notes: [Aimo `docs/GEMINI.md`](https://github.com/s1laswang/junction-aimo-agents/blob/main/docs/GEMINI.md) and [HoldUp `GEMINI.md`](https://github.com/s1laswang/junction-meta-glasses/blob/main/GEMINI.md).

---

Planning material from the start of the hackathon (briefs, research, the fleet plan) is kept on this branch under [`docs/`](docs/) and [CHALLENGES-AFTERQUERY-GEMINI.md](CHALLENGES-AFTERQUERY-GEMINI.md). It is not part of either submission.
