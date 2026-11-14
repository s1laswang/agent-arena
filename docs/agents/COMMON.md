# COMMON brief for every head and engineer on `justSilas` (read fully, then your department file)

## Who and why
Silas Wang's Junction 2026 team, aiming at:
- **AfterQuery "Break the Agent"**, our main track. Rubric:
  - **gap 30:** the frontier agent consistently scores below our reproducible stronger reference run;
  - **meaningful difficulty 30:** the agent's mistakes are explained and tied to decisions; the information and tools to do better are available; no trick wording or withheld information;
  - **reward integrity 25:** survives the judges' 15-minute exploit hunt; do-nothing and stop-early score about 0; playing well is the best way to score;
  - **craft 15:** the rules make sense; **one command from the README reproduces the results.**

  Judges rerun with **Harbor + OpenCode over MCP**: our reference run, 3 agent runs, a do-nothing baseline and a stop-early baseline. Tiebreaker: a small model trained on environment experience improves.
- **Google DeepMind "Best Use of Gemini API":** Gemini must be *essential*.

Full brief: `CHALLENGES-AFTERQUERY-GEMINI.md`. Prior research: `docs/research-afterquery.md`. **The plan: `docs/PLAN.md`. The contract: `docs/CONTRACT.md`. Read both.**

**Deadline:** the team review is at 09:00 Sat 14 Nov (Helsinki). The final submission is Sun 15 Nov 10:00.

## The product: Canary
A simulated company with a hidden mole. The agent is the security lead and must find the mole while value bleeds out. The reference run is a Bayesian canary-trap solver. Gemini plays the company, the mole, the scenario designer, the exploit hunter and the analyst.

**There is no Gemini key tonight.** Everything Gemini-related is built behind `canary.llm` with a `stub` backend and tested. In the morning Silas pastes `GEMINI_API_KEY` into `.env` and it must just work. Tonight's frontier agent is **OpenAI**, via OpenCode (`OPENAI_API_KEY` in `.env`) and the Codex CLI (`codex`, already logged in).

## Org
- **CEO:** a Claude session in `~/junction-aimo-team/wt/justSilas`. It owns the integration branch, the contract arbitration and `docs/reports/CEO.md`.
- **5 heads**, each in its own terminal: ENV, HARNESS, INTEGRITY, AGENTS, FR8.
- **Each head spawns up to 3 engineer subagents** (Agent tool, run in background, each in its own worktree). Write each engineer a complete brief: goal, files it owns, interfaces, definition of done and what to report. The engineer has none of your context unless you put it in the brief.
- **Heads review and merge their engineers' work.** Heads do not write all the code themselves; they lead, review, test and integrate.

## Git rules (non-negotiable)
- Repo: `~/junction-aimo-team/agent-arena` (shared checkout, on main; **do not work in it**).
- Integration branch: `justSilas`. Department branch: `justSilas-<dept>` (e.g. `justSilas-env`). Engineer branch: `justSilas-<dept>-<eng>`. Use hyphens, never `justSilas/…`: git can't hold both refs.
- Worktrees:
  - your own: `git -C ~/junction-aimo-team/agent-arena worktree add ~/junction-aimo-team/wt/justSilas-<dept> -b justSilas-<dept> origin/justSilas`
  - an engineer's: `... wt/justSilas-<dept>-<eng> -b justSilas-<dept>-<eng> justSilas-<dept>`
- **Pull `origin/justSilas` into your branch often.** Merge into `justSilas` with `--no-ff` **only when `make test` is green**, then push. Never force-push. **Never touch `main`** and never touch other people's branches (teammates build their own ideas on their own branches tonight).
- Commit small with clear messages. End commit messages with: `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`
- Stay in your lane: only edit files your department owns (see your department file). For anything shared (`types.py`, `rules.py` shape, `Makefile` targets), coordinate via the CEO or the owner.
- git stash is shared across worktrees. Use WIP commits, not bare `git stash`.

## Secrets
- `.env` is gitignored, at the repo root of the shared checkout. Copy it into your worktree (`cp ~/junction-aimo-team/agent-arena/.env .`) or load it via an absolute path.
- **Never commit, print or log keys**, and never put them in reports.

## FR8 "freighter" cluster rules (anyone touching it)
- Access: `ssh freighter`, Slurm.
- **CPU:** partition `normal`. Only about 24 cores are free (on compute06), so use at most 24 cores in total across all our jobs.
- **GPU:** partition `gpu`, 1 GPU per job (`--gres=gpu:1`), fp16 AMP only (no bf16, no FlashAttention-2, no vLLM on V100). Only the FR8 head submits GPU jobs. Silas frees the GPU himself.
- **NEVER cancel, requeue, hold or modify any job you did not submit**, including Silas's `sky` and `sleeper-pilot` jobs. Always set `--time` (max 24 h). No heavy work on the login node.
- Code goes in `freighter:~/agent-arena` (rsync from the Mac via `make fr8-sync`; the private repo can't be cloned on FR8). Data, models, outputs and logs go in `freighter:~/agent-arena-data/` (**≤10 GB total**; /home is 95% full). /data is not writable.
- `module load pytorch-volta` provides PyTorch 2.5.1 / CUDA 12.6 / transformers / peft. Apptainer is available. The login node has internet; compute-node internet is unverified.

## Reporting (the CEO reads these every 30–40 min)
Update `docs/reports/<dept>.md` on your branch and merge or push it **at least every 45 min**:

```
## <HH:MM> status
- Done (verified: how) / Done (untested)
- In progress (owner, ETA)
- Blockers / decisions needed from CEO or Silas
- Next 45 min
```

- **Urgent blockers:** also message the CEO session with SendMessage (find it with ListAgents; it's the session working in `wt/justSilas`).
- **Never claim something works without running it.** Say "untested" when it is untested.

## Quality bar
- Deterministic seeds everywhere.
- Every claim in a report is backed by a command you ran.
- Tests for every mechanic and every exploit you close.
- Keep it simple: a working thin slice beats an ambitious broken one. The judges will run `make reproduce` from a fresh clone with no keys.
