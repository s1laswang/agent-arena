# Canary replay viewer

A standalone viewer for [Canary](../README.md) episode logs. Load an `episodes.jsonl` file and step through the investigation: every tool call, who received each canary, what had leaked, and what the company was worth.

Nothing is fetched at runtime. Fonts and scripts are bundled. There is no backend.

## Generate a log

From the repository root:

```bash
make setup
uv run --python 3.12 python -m canary.eval --agent solver --tier medium --seeds 3
```

That writes `data/runs/solver-medium-<timestamp>/episodes.jsonl` (one `EpisodeResult` per line) and a `meta.json`. The same command works for any offline agent the eval CLI knows, for example:

```bash
uv run --python 3.12 python -m canary.eval --agent heuristic --tier medium --seeds 3
uv run --python 3.12 python -m canary.eval --agent restrict_all --tier medium --seeds 1
```

Frontier agents such as `gpt-5.5` are not wired into `canary.eval` and need API keys, so they are not required to try the viewer. Two offline runs are enough for side-by-side mode.

`data/runs/` is gitignored. The viewer ships three small logs under `public/samples/`, copied from those commands (medium tier, seeds 0–2 for solver and heuristic, seed 0 for restrict-all).

## Install and run

Requires Node 20+ and npm. From `viewer/`:

```bash
npm install
npm run dev
```

Open the URL Vite prints (usually http://localhost:5173).

```bash
npm test          # parse + replay checks against the sample logs
npm run build     # typecheck and write viewer/dist
npm run preview   # serve dist/ with no network dependency
```

Open the built app through `npm run preview` or any static file server pointed at `dist/`. Browsers block ES modules and `fetch` of the sample files from `file://`, so double-clicking `dist/index.html` will not load samples. Drag-and-drop still uses the FileReader API and does not need a server.

## Use the viewer

- Drop an `episodes.jsonl` (or a JSON array / one episode object) anywhere on the window. Drop two files to open them side by side. **Open** is the file-picker fallback.
- **Samples** loads a shipped log. **Solver vs heuristic** opens both and selects seed 0 on each side.
- When a file has more than one episode, the **Episode** menu picks one. In compare mode, **Use seed N on both** jumps the other side to the same seed and tier when that episode exists.
- The header shows agent, tier, seed, score, accused, correct, final day, and end reason.
- The timeline groups tool calls by day. Click a row, drag the scrubber, or use the keyboard: `←` `→` step, `↑` `↓` day, `Space` play/pause, `Home` / `End`. **Step** sync moves both episodes by tool-call index. **Day** sync keeps them on the same day and the same action within that day. A shorter episode stays on its last step and says so.
- The selected step shows its arguments and the result the agent saw.
- **Company** is one card per employee. Canary chips use a fixed colour per variant label (`A` teal, `B` gold, `C` rose, …), restricted staff are hatched, and the accused card is marked. If the episode was correct, that person is the mole. If it was wrong, the card says so and the mole is not named.
- **Leak feed** lists documents that have surfaced by the current day. A canary leak’s variant tag uses the same colour as the people who received it. Click a leak to highlight that group (or, for an ordinary document, its recipients). “Unread” means the leak is in a later `check_leak_feed` result and the agent has not seen it yet at this step.
- **Company value** plots `V` against the step index. The cursor matches the selected step. The solid segment is up to now; the dashed segment is the rest of the episode. Click the chart to seek.

## How a frame is derived

The viewer does not re-simulate the environment. It walks `steps` in order.

| What you see | Where it comes from |
| --- | --- |
| Roster (id, name, dept, role, clearance) | The latest successful `list_employees`. Ids that never appear there are still shown if a later tool mentions them, without a name. |
| Canary recipients and variant colours | `plant_canary` args: `assignment` maps employee id → variant label. The result is only `{canary_id}`. `list_documents` entries with `is_canary` and `variants` (`{label: [employee, …]}`) fill in a canary the plant call did not describe. A canary appears at the step that planted it. |
| Restricted staff | Successful `restrict_access` / `unrestrict_access`, replaced wholesale by `restricted` on each successful `status`. |
| Leak feed | Every successful `check_leak_feed`. Items are `{doc_id, title, surfaced_day, variant?}`. At a step on day D, items with `surfaced_day <= D` are shown, including ones the agent only read later. |
| Company value | `V` on `status` and on `advance_day`, plus `meta.V` at the last step when it differs. The line starts at 1.0, which is the value the rules give the company before any tool call. |
| Accused / mole | `accused`, `correct`, and `score` on the episode. The `accuse` result is only `{accused, episode_over}` and does not reveal the mole. |

## Schema gaps

These are real limits of `episodes.jsonl`, not missing UI:

- The mole’s id is never in a tool result. It is known only when `correct` is true, in which case the mole is `accused`. A wrong accusation does not say who the mole was.
- The decoy is not a field on any tool result.
- The company name is not in the log.
- `plant_canary` does not return the new value of `V`. The cost (0.01 on the current tiers) appears on the next `status`. Until that call, the chart holds the previous observation.
- Leaks the agent never retrieved with `check_leak_feed` are absent, even if they surfaced. Titles and variant groups for documents that were never listed or planted are missing too; the feed row still shows whatever the leak item itself contained.
- `read_access_logs`, `search_messages`, `read_message`, and `interview` are shown in the timeline and the step detail. They do not change the company, leak, or value panels, except that employee ids mentioned in a successful call are added to the roster when `list_employees` never ran.
