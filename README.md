# agent-arena: Junction 2026 entries

This repo holds our hackathon entries. Each one is pinned to a tag. **This `main` branch has no code for either entry.** Pick the one you are judging below.

| Challenge | Entry | Branch | Start here |
|---|---|---|---|
| **AfterQuery: Break the Agent** | **Canary: catch the mole.** An RL environment where an AI head of security must find the one mole leaking documents, using canary traps, while company value bleeds away. It is scored against a Bayesian reference solver that uses the same public tools. | tag [`afterquery-submit`](https://github.com/s1laswang/agent-arena/tree/afterquery-submit) (branch `justSilas`) | [README → "For judges"](https://github.com/s1laswang/agent-arena/blob/afterquery-submit/README.md) |
| **Google DeepMind: Best Use of Gemini API** | **Canary Lab.** Gemini's thinking level used as a controlled variable on the Canary benchmark, plus a Gemini red team validated by a positive control. Every Gemini call is logged. | tag [`gemini-final-v3`](https://github.com/s1laswang/agent-arena/tree/gemini-final-v3) | [docs/gemini/SUBMISSION.md](https://github.com/s1laswang/agent-arena/blob/gemini-final-v3/docs/gemini/SUBMISSION.md) |
| **Verda Compute Track** | Small-model training on Canary experience and open-weight runs on Verda GPUs, with every number labelled by where it ran. | tag [`afterquery-submit`](https://github.com/s1laswang/agent-arena/tree/afterquery-submit) | [VERDA.md](https://github.com/s1laswang/agent-arena/blob/afterquery-submit/VERDA.md) |

> **Correction, Sun 15 Nov 09:30 (AfterQuery entry).** The judge rehearsal's third run finished after the tag was cut. Final numbers: three gemini-4-carbon runs at **93%, 116% and 131%** of the oracle (run 3: 9 valid trials, 5 of them after the 08:30 cut-off, 1 infra-excluded). The table inside tag `afterquery-submit` shows an 08:52 snapshot of run 3 (7 trials, 153%) and wrongly says it stopped at 08:30. The conclusion is the same: no gap in the judge path. Final table and all trial directories: [`s1-rehearsal-final`](https://github.com/s1laswang/agent-arena/blob/s1-rehearsal-final/results/harbor/rehearsal/TABLE.md).

## Reproduce the AfterQuery entry (one command, no API keys)

```bash
git clone -c core.longpaths=true -b afterquery-submit https://github.com/s1laswang/agent-arena.git && cd agent-arena
make setup && make reproduce
```

You need [uv](https://docs.astral.sh/uv/) and `make`. The Harbor + OpenCode/MCP instructions are in that tag's README. The tag `afterquery-final` is the code freeze the judge rehearsal ran on; `afterquery-submit` adds results and docs only. `-c core.longpaths=true` only matters on Windows, where some committed Harbor run folders are deeper than the default 260-character path limit; macOS and Linux ignore it.

## Same team, other challenges

- Valio Aimo "Trusted Trade Agents": [s1laswang/junction-aimo-agents](https://github.com/s1laswang/junction-aimo-agents)
- Meta "AI Glasses for Everyone, Everyday" (HoldUp): [s1laswang/junction-meta-glasses](https://github.com/s1laswang/junction-meta-glasses)

Both of those also use Gemini. Their Gemini notes: [Aimo `docs/GEMINI.md`](https://github.com/s1laswang/junction-aimo-agents/blob/main/docs/GEMINI.md) and [HoldUp `GEMINI.md`](https://github.com/s1laswang/junction-meta-glasses/blob/main/GEMINI.md).

---

Planning material from the start of the hackathon (briefs, research, the fleet plan) is kept on this branch under [`docs/`](docs/) and [CHALLENGES-AFTERQUERY-GEMINI.md](CHALLENGES-AFTERQUERY-GEMINI.md). It is not part of either submission.
