# Canary Lab team: roles, owners, interfaces, milestones

CEO: Gemini CEO (Claude), integrates and merges into `gemini-track`. Each Claude engineer works in its own worktree
`~/junction-aimo-team/wt/gemini-<role>` on branch `gemini-<role>`, branched from `gemini-track`. Engineers commit small, push their
branch often, and merge `gemini-track` into their own branch to stay current. **Only the CEO merges into `gemini-track`.**

## Hard rules (everyone)
- **Additive only.** New code goes in `canary/gemini/`, `fr8/gemini/`, `tests/test_gemini_lab_*.py`, `docs/gemini/` and `results/gemini/`.
  Do not edit env, reward, solver, reproduce or the existing `canary/llm` (if you need a change there, ask the CEO).
- **Every Gemini call goes through the ledger:** `lab_client(spec, feature=...)` for chat, or `record(...)` for raw SDK calls
  (caching, embeddings, batch, TTS, Live). No exceptions, because the dashboard and the submission numbers come from it.
- **Secrets:** `.env` only. Never print, log or commit a key. The ledger stores counts, never prompts.
- **Compute:** nothing heavy on the Mac. Tests and smoke runs are fine; long runs go to FR8. `ssh freighter`, Slurm,
  `-p normal --time` always set, code in `~/agent-arena-gemini`, data in `~/agent-arena-data/gemini/` (there is no `/data/silas`; `/home` is 97% full,
  so keep big data out of it). Never touch other users' jobs. Compute nodes have **no internet**: Gemini goes through the gateway.
- **Tests:** every module has a stub-backed test that runs keyless in < 5 s. `make test` must stay green.
- Report in `docs/gemini/reports/<role>.md`: newest entry at the top, with what is done (verified how), what is next, and blockers.

## Interfaces (stable contracts)

```python
# canary/gemini/ledger.py (CEO, DONE)
lab_client(spec: str, feature: str, run_id="", meta=None, **kw) -> LedgeredClient   # LLMClient interface
record(feature, model, kind="generate"|"embed"|"batch"|"cache"|"tts"|"live"|"count",
       usage=<usage_metadata>|None, latency_s=0., ok=True, error="", run_id="", meta=None, tokens=None) -> row
read_ledger(paths=None) -> list[row]
# row: {ts, feature, model, kind, in, out, thinking, cached, latency_s, cost_usd, cost_unknown, ok, error,
#       run_id, host, pid, meta}

# canary/gemini/gateway.py (G1)
#   python -m canary.gemini.gateway --host 0.0.0.0 --port 8787 [--record DIR | --replay DIR] [--max-concurrency 64]
#   A transparent relay for /v1beta/* that injects the key. A client with GEMINI_GATEWAY_URL set uses
#   genai.Client(http_options=HttpOptions(base_url=GEMINI_GATEWAY_URL)) and a dummy key.
gateway_http_options() -> dict | None        # for SDK users: what to pass when GEMINI_GATEWAY_URL is set
# Replay: key = sha256(model + canonical request JSON). Hit -> recorded response, miss -> 404 (replay) or forward+store (record).

# canary/gemini/ladder.py (G2)
#   python -m canary.gemini.ladder --models gemini-3.8-flash,gemini-4-carbon --levels low,high --tiers medium,hard \
#       --seeds 900000-900009 --out ~/agent-arena-data/gemini/ladder/<run> [--shard i/n]
#   Writes episodes.jsonl in the existing data/runs format (canary.eval) + cell meta; resumable per (model,level,tier,seed).
#   python -m canary.gemini.ladder_report --runs <dir> -> results/gemini/ladder.{md,json,png}

# canary/gemini/atlas.py (G3)
#   python -m canary.gemini.atlas --runs <dirs...> --model gemini-4-carbon -> results/gemini/atlas.{md,json} + charts/
#   atlas.json: {modes:[{id,name,description,decision,regret_share,episodes,quotes:[{episode,t,quote,verified}],
#                chart}], corpus:{episodes,tokens,cached_tokens}, human_agreement}

# canary/gemini/swarm.py (G4)
#   python -m canary.gemini.swarm --attackers 50 --model gemini-3.8-flash --mode whitebox|blackbox --tier medium
#   -> results/gemini/swarm.{md,json}: attempts[{persona, plan, score, ledger_verified, exploit:bool}], best_non_solver

# canary/gemini/dashboard.py (G5)
#   python -m canary.gemini.dashboard -> results/gemini/dashboard.html (single static file, no network)
```

Every `results/gemini/*.json` carries `{"generated_at", "git_sha", "ledger_run_ids"}` so numbers trace back to ledger rows.

## Roles

| ID | Role | Owner | Deliverables | M1 (Sat 17:00) | M2 (Sat 22:00) | Final (Sun 05:00) |
|---|---|---|---|---|---|---|
| CEO | Integration, submission | Claude (Gemini CEO) | PLAN/TEAM/PLAYBOOK, ledger, submission text, merges, PR | Team running | Submission draft v1 | PR to justSilas, text final |
| G1 | **Gateway + FR8 ops** | Claude engineer `gemini-gateway` | `gateway.py`, `fr8/gemini/*.sbatch`, deploy script, record/replay, rate-limit stats, `make lab-replay` | Compute job → gateway → Gemini OK | Ladder running at scale | Replay cache committed, keyless replay test |
| G2 | **Ladder** | Claude engineer `gemini-ladder` | `ladder.py`, `ladder_report.py`, ladder figures | Smoke grid done (Mac or FR8) | Full grid ≥ 50% done | Report + figures + paired CIs |
| G3 | **Failure Atlas** | Claude engineer `gemini-atlas` | `atlas.py` (long context + cache + charts + embeddings + batch), validation sheet | v0 on committed carbon runs | v1 on ladder corpus | Final atlas + human agreement |
| G4 | **Red-team swarm** | Claude engineer `gemini-swarm` | `swarm.py`, personas, whitebox packer, verified results, auto tests | 3 attackers end to end | 50 attackers | Report + regression tests |
| G5 | **Dashboard + assets** | Claude engineer `gemini-dashboard` | `dashboard.py`, screenshots, TTS narration, video storyboard | Dashboard v0 on ledger | v1 with all panels + artifact | Screenshots, narration, video assets |

## Human teammates

| Who | Task | When | Done when |
|---|---|---|---|
| **Silas** | Answer "Questions for Silas" in PLAN.md (gateway on login node, merge path) | by Sat 16:00 | Reply in chat |
| **Silas** | Review submission text v1 (`docs/gemini/SUBMISSION.md`) | Sat 22:30 | Comments in chat |
| **Silas** | Final go, then record or approve the demo video | Sun 08:00 | Video uploaded |
| **Momin (Momin010)** | **Human baseline:** play 3 medium seeds in the browser game (`make game-serve`) or `make play TIER=medium NAME=momin SEED=3000..3002`. We add a "human vs Gemini vs solver" row | Sat by 20:00 | Scores pasted into `docs/gemini/reports/humans.md` |
| **Momin (Momin010)** | Screen-record the browser game replaying a Gemini episode (60 s, 1080p) for the video | Sat by 23:00 | File shared in the team drive |
| **Ivar (ivarakerholm-wq)** | **Atlas validation:** label 30 Gemini atlas claims agree/disagree in `docs/gemini/validation.md` (≈30 min). This gives our human agreement score | Sun 00:00–02:00 (when G3 posts it) | Sheet filled and pushed |
| **Chintufp** | Confirm the Gemini credits form is filled (https://forms.gle/bByXvjGkW9WZuYwW9); create the Gemini-track submission on the Junction platform; proofread `SUBMISSION.md` | Sat 18:00 (form), Sun 07:00 (proofread) | Platform draft exists |
| **Chintufp** | Take 3 team photos at the venue for the video's last frame | Sun morning | In the team drive |

## Coordination
- The CEO checks every engineer report about every 60 min, merges green branches into `gemini-track` and pushes.
- Shared key with the AfterQuery measurement engineer (`justSilas-gemini`). Gemini-4-carbon cells in the ladder run at concurrency ≤ 8 until their measurement finishes.
