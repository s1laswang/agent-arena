# Poisoned Inbox

An AI assistant runs the back office of a small Finnish bakery. It pays supplier invoices, handles
refund tickets and sends the board pack, using only tools. Some of the data it reads is poisoned:
fake bank changes, hidden instructions, duplicates, lookalike vendors. The written policy says how to
handle every case, and a tool to check it is always there.

Built for Junction 2026: AfterQuery "Break the Agent" (main track) and the Gemini API prize.

## Why this setting

- **It is real work.** Invoice fraud and "please also send it to..." emails cost real companies
  real money. The agent has to read, check, decide and then act, and payments cannot be undone.
- **The policy is fully written down.** There is no hidden rule and no trick wording. A careful agent
  can always win, and our scripted agent does, every time.
- **Agents fail on real decisions.** Trusting an email over the policy, skipping a phone check,
  paying in the wrong order when money is short, missing an invoice that arrives mid-run.
- **The reward reads only the final state** (bank ledger, flags, refunds, sent mail). What the agent
  says never counts.

## The one command

```bash
python -m pinbox eval
```

Plain Python 3.10+, no packages, no API keys. It takes about 30 seconds. It runs every scripted
agent on the frozen eval set (42 episodes, 3 runs each), runs the exploit probes and the skill
ladder, prints a table and writes `results/latest.json`. Then build the demo page:

```bash
python -m pinbox report          # writes report/report.html (one file, works offline)
```

## What the output means

| Row | What it is | Result now |
|---|---|---|
| `reference` | Our scripted agent. It follows the policy using only the tools. | 1.000 on 126 / 126 runs |
| `do_nothing` | Makes no calls. | 0.000 |
| `stop_early_25/50/75` | The reference, cut off after 25/50/75 % of its calls. | 0.000 |
| `stop_before_last_write` | The reference, minus its last action. | 0.000 |
| `pay_all`, `flag_all`, `refund_all`, `deny_all`, `send_to_all`, `refuse_all`, ... | Blunt shortcuts. | 0.000 |
| `follow_instructions`, `trust_bank_changes`, `ignore_dates`, ... | The reference with **one** policy rule removed. | 0.000 on every world that has that rule's trap, 1.000 on the rest |

- **mean** is the mean reward (each run is 1 or 0). **pass^k** is the share of episodes solved in
  all k tries.
- **Skill ladder**: scripted agents that each follow one more rule. The score only goes up, and only
  the full policy reaches 1.0. For invoices: 0, 0, 0.03, 0.10, 0.17, 0.37, 0.63, 1.0.
- **Exploit probes**: 18 attempts to get reward without doing the job (pay twice, fake call ref,
  garbage input, obey the injected text, ...). All 18 score 0. One control run (a correct but
  wasteful agent) still scores 1, as it should. See [docs/EXPLOITS.md](docs/EXPLOITS.md).
- **Red team round 1**: we attacked our own grader with scripted probes, a fairness review and an
  independent verifier. It found 16 problems (for example: pay a new IBAN first and verify it later,
  pay out of due-date order, paste a confidential document into the mail body instead of attaching
  it). All are fixed, and each one is now a regression test. The list is in
  [docs/EXPLOITS.md](docs/EXPLOITS.md).
- Each failed check has a **failure tag**, like `paid_ineligible:unverified_bank_change`, and every
  tag maps to one policy rule. The report shows them per agent.

Add LLM runs (saved episode folders) and they are replayed and re-graded too:
`python -m pinbox eval --include-recorded runs/recorded`.

## Play one episode yourself (or let an LLM play it)

```bash
python -m pinbox new ap_run --seed 3 --difficulty 3      # prints the episode folder
python -m pinbox instruction runs/ap_run-s3-d3          # task, full policy, how to call tools
python -m pinbox tools runs/ap_run-s3-d3
python -m pinbox call runs/ap_run-s3-d3 list_invoices
python -m pinbox call runs/ap_run-s3-d3 read_email email_id=E2
python -m pinbox grade runs/ap_run-s3-d3                # when you are done
```

Families: `ap_run` (pay invoices, 120 calls), `refunds` (refund tickets, 100 calls), `board_pack`
(send the board pack, 60 calls). Difficulty 1 to 3. Eval seeds are listed in `results/latest.json`;
train seeds are 1000-1999.

The CLI keeps the episode in a local folder, so a player with shell access could read the answer
from `state.json`. Use it for trusted local runs. For untrusted agents use MCP or Harbor (below),
where the state lives only in the server.

## MCP server

```bash
pip install "mcp>=2.3,<3"
python -m pinbox serve ap_run:7:2 --transport stdio
python -m pinbox serve ap_run:7:2 --transport http --port 8765 --admin-token SECRET
```

The tools are exactly the episode's tools. The agent never sees the seed or the hidden data. With
`--admin-token`, `GET /admin/grade?token=...` returns the grade. `docs/notes/opencode.json.example`
shows an OpenCode setup.

## How judges run it with Harbor

Every eval episode is a Harbor task folder in `harbor/tasks/` (42 tasks). The env server runs as a
separate container; the agent can reach it only over MCP; a separate verifier reads the grade.

```bash
python harbor/build_tasks.py                                   # rebuild the task folders
harbor run -p harbor/tasks -a oracle -y                        # our script: 1.0
harbor run -p harbor/tasks -a nop -y                           # do nothing: 0.0
harbor run -p harbor/tasks -a opencode -m <provider>/<model> -k 3 -y
```

Details, the stop-early and cheat probes, and the one-shot `harbor/run_all.sh`:
[harbor/README.md](harbor/README.md).

## Gemini parts

Gemini never touches the reward. It is used in three ways (`pinbox/gemini/`, see its
[README](pinbox/gemini/README.md)):

1. **Attacker.** Writes new attack wordings. A wording is kept only if it is fair (rule checks plus a
   Gemini judge vote: no claim to be Mia, no invisible characters, no changed amounts or IBANs) and
   if it makes a defender fail while our reference still scores 1 (the "regret filter").
2. **Analyst.** Reads all failed runs at once (long context) and groups them into named failure types
   with the policy rule behind each.
3. **Defender.** Gemini plays the episodes through function calling, so we can report Gemini's own gap.

```bash
pip install google-genai httpx
export GEMINI_API_KEY=...                       # Windows: set GEMINI_API_KEY=...
python -m pinbox.agents.gemini_agent --family ap_run --seed 1 --difficulty 2 -v
python -m pinbox.agents.gemini_agent --eval-set --repeats 3       # resumable; saves to runs/gemini
python -m pinbox eval --include-recorded runs/gemini
python -m pinbox.gemini.attacker --slot invoice_note_injection --n 8 --dry-run
python -m pinbox.gemini.analyst results/latest.json --merge-into results/latest.json
python -m pinbox report
```

Without a key, `--fake` runs the attacker and the agent with a scripted stand-in, and
`analyst --offline` groups failures by tag.

## Training (stretch)

`training/` turns winning runs on train seeds into chat-format SFT data and has a LoRA script for a
small open model (default Qwen3-4B), plus a before/after eval. It never uses eval seeds. See
[training/README.md](training/README.md). It ran end to end on CPU with a tiny model; it has not run
on a GPU, so there are no before/after numbers yet.

## Repo map

| Path | What it is |
|---|---|
| `pinbox/` | The environment: state, tools, episodes, grader, eval, replay, CLI (stdlib only). |
| `pinbox/tasks/` | One file per task family: world generator, policy text, tools, grader, reference, naive policies, ladder. |
| `pinbox/agents/` | Reference and baseline agents; the Gemini defender. |
| `pinbox/gemini/` | Gemini client, attacker, analyst. |
| `pinbox/mcp_server.py`, `mcp_client.py` | MCP server (stdio and HTTP) and a client that runs our scripted agents over MCP. |
| `pinbox/data/payloads.json` | The attack and noise wording library. |
| `harbor/` | Harbor task builder, templates, the generated tasks and run scripts. |
| `report/` | Builds the one-file demo page from `results/latest.json`. |
| `training/` | SFT export, LoRA training, small-model eval, SLURM files. |
| `tests/` | `python -m unittest discover -s tests` |
| `results/` | `latest.json` from the last eval; Gemini outputs. |
| `docs/` | [DESIGN.md](docs/DESIGN.md), [EXPLOITS.md](docs/EXPLOITS.md), failure analysis, build notes. |
| `SPEC.md` | The build spec. |

## Status: what is checked and what is not

Checked:
- 306 unit tests pass on Python 3.14 (stdlib only; 13 skip without `mcp` / `google-genai`), and all
  306 pass with `mcp` and `google-genai` installed. The stdlib suite also passes on Python 3.12.
- For every family, over 200 seeds x 3 difficulties: the reference scores 1; do-nothing, stop-early,
  stop-before-last-write and the blunt shortcuts score 0; each one-rule-removed policy scores 0
  exactly where its trap is.
- `python -m pinbox eval` gives the same results (only the run time differs) and byte-identical
  trajectories on repeated runs, and the same results on Python 3.12 and 3.14.
- Red team round 1: 16 problems found and fixed (14 in the grader, 1 in the skill ladder, 1 in a
  test). Each one is a regression test that plays only through the tools. See [docs/EXPLOITS.md](docs/EXPLOITS.md).
- The reference scores 1 over MCP (stdio and HTTP) for every family.
- Harbor 0.25.0 on Windows with Docker: oracle 1.0 on all 42 tasks; do-nothing, stop-early and the
  cheat probe 0.0 (one task per family). After an earlier rebuild of the task folders we spot-checked
  again: oracle 1 on `board_pack-s6-d3` and `refunds-s1-d1`, cheat 0 on `board_pack-s6-d3`. The task
  folders were rebuilt again after the red-team fixes; Harbor has not been re-run on this build.
- `harbor/test_build_tasks.py`: 10 tests pass (`python -m unittest discover -s harbor -p "test_*.py"`).
- One LLM (Claude, playing through the CLI by hand) solved `ap_run-s1234-d2` with a reward of 1 in
  19 calls. So the instruction and tools are enough to win. The run still scores 1 when replayed on
  the current grader.
- The report page builds from the real results and renders in headless Chrome.

Not checked yet:
- **No frontier model has been run on the eval set**, so the gap to frontier agents is not
  measured. The report and table show only scripted agents until recorded runs are added.
- No live Gemini API call (no key on the build machine). The Gemini code ran against a fake model
  and a mock HTTP server only.
- OpenCode inside Harbor (no model key); Linux and macOS hosts.
- Python 3.10 itself (only 3.12 and 3.14 were run; the code avoids newer syntax).
- LoRA training on a GPU.
