# The FR8 agent fleet

160 Gemini agents on the FR8 cluster, working on 4 Junction challenges at once. Started Sat 14 Nov 2026 ~14:45. Final submission: Sun 15 Nov 10:00 Helsinki.

This page explains what runs, how it works, and how anyone on the team (Silas, Vaishnav, Ivar, Momin) steers it: give tasks, change goals, add or remove agents.

## What runs

| Team | Repo on FR8 | Starts from | Agents | Goal |
|---|---|---|---|---|
| afterquery | agent-arena | `justSilas` | 1 lead + 39 workers | Merged Canary for AfterQuery: close the weak points in docs/IDEAS.md (real frontier gap on paired seeds, bias layer, RL-ready mole, anti-cheat battery in `make reproduce`, separate Harbor verifier, fast reproduce) |
| gemini | agent-arena | `justSilas` | 1 lead + 39 workers | Best Use of Gemini API: one labelled real Gemini run per role (world text, mole, investigators, failure analyst, exploit hunter, multimodal) |
| valio | junction26-valio | `dev` | 1 lead + 39 workers | Valio Aimo "Trusted Trade Agents": finish the gateway, all scenarios green, docs + pitch + demo |
| meta | junction-meta-glasses | `main` | 1 lead + 39 workers | Meta AI glasses: build what the repo README describes into a working, inclusive prototype + deck |

Every agent is OpenCode 1.19.5 running `google/gemini-4-carbon`. Each team is one Slurm job on the `normal` (CPU) partition, 16 CPUs, 40 GB, 24 h.

## How it works

```
Momin / Silas / chief  --edit-->  board/CHIEF.md
                                      |
                                  team lead  --writes-->  board/<team>/inbox/<worker>.md
                                      ^                          |
                       merges branches|                      worker (loop)
                                      |                          |
                    board/<team>/outbox/<worker>.md  <--report--+  push fr8/<team>/<worker>
```

- **Repos.** Copies of the 4 GitHub repos live on FR8 as bare repos in `~/momin/fleet/repos/<name>.git` (pushed from Momin's Mac; FR8 has no GitHub login). Each team works on its own branches: lead `fr8/<team>/main`, workers `fr8/<team>/<worker>`.
- **Workspaces.** At job start every agent gets a light clone (`git clone -s`) on the compute node's local disk (`/tmp/fleet-silas/wt/<agent>`). Commits are pushed back to the shared bare repo, so the lead sees every worker branch. Nothing heavy goes to `/home` (97% full).
- **The loop.** Each agent runs `agent_loop.sh`: one OpenCode turn with its role prompt (read inbox, do the task, test, commit, push, report), sleep 20 s, repeat, until the file `~/momin/fleet/STOP` exists.
- **Roles.** `role_lead.md` and `role_worker.md` are templates; `setup_on_fr8.sh` fills in name, team, repo and goal into `~/momin/fleet/agents/<agent>.role.md`.
- **Internet.** Compute nodes have no internet. A small CONNECT proxy on the login node's internal interface (`10.11.0.1:3128`, `~/momin/proxy.py`) carries HTTPS for the agents. This is temporary and approved by the FR8 admin (Wilmer) until real NAT is set up. Remove it then.
- **Tools.** Agents run inside `/opt/containers/pytorch-volta.sif` (git + Python + PyTorch). OpenCode's own database is node-local per agent (shared-disk SQLite broke with many writers).
- **Keys.** `~/momin/.env` on FR8 (mode 600) holds the Gemini key and proxy settings. Never commit it.

## How to steer the fleet

All on FR8 (`ssh freighter`), in `~/momin/fleet/board/`:

| You want to | Do this |
|---|---|
| Change direction for everyone | Edit `board/CHIEF.md`. Every lead reads it every turn |
| Give one worker a specific task | Write it into `board/<team>/inbox/<worker>.md` (the whole file is the task: what, which files, how to test, when it is done) |
| See what a team has done | `board/<team>/STATUS.md` (lead), `board/<team>/outbox/*.md` (workers) |
| See an agent's raw output | `~/momin/fleet/logs/<agent>.log` |
| Change a team's goal | Edit `teams.conf` (on the Mac in `~/fr8-fleet/`, or `~/momin/fleet/teams.conf` on FR8), then restart |
| Add or remove agents | `start.sh <agents per team>` (restart picks the new size) |
| Add a fifth team | Add a line to `teams.conf`: `name|repo|base branch|goal`, push the repo to `~/momin/fleet/repos/`, restart |
| Get the work onto GitHub | `sync_back.sh` on the Mac pushes every `fr8/*` branch from FR8 to GitHub |

From the Mac (`~/fr8-fleet/`): `start.sh 40` (setup + start all teams), `status.sh`, `stop.sh`, `sync_back.sh`.

## What we did to get here (14 Nov)

1. Paused Skywatch on the FR8 GPUs (resume: `cd ~/momin/sky && sbatch sky.sh`, it continues from saved checkpoints).
2. Found compute nodes have no internet; with the admin's approval added the internal proxy.
3. Installed OpenCode from its GitHub release on FR8; tested `gemini-4-carbon` on a compute node.
4. Pushed the 4 repos to FR8 from the Mac (`push_to_fr8.sh`).
5. Pilot with 20 agents found 3 problems, fixed: OpenCode blocked reading the board (allowed `external_directory`), no git on compute nodes (run inside the container), SQLite on the shared disk (node-local data dirs).
6. Moved workspaces to node-local disk (160 full copies would have filled `/home` for every user).
7. Started 160 agents.

## Known limits and next steps

- Gemini has a per-minute rate limit. If logs show rate errors, raise `FLEET_PAUSE` (seconds between turns) in `agent_loop.sh`.
- The GPUs (20x V100) are free for training: Qwen fine-tunes for human-like employees and the RL mole. They need a `/data/silas` folder (ask the admin) because `/home` is full.
- Leads only see the board and their repo. Cross-team work goes through `CHIEF.md`.
- Every number a team reports must come from a command it ran, with the commit.
