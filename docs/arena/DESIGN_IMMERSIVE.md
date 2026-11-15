# Canary Arena Immersive: design

Goal: walk the office as the investigator. Same engine (js/engine.js Env), same data, same scoring. Only the surface changes: world and bubbles instead of tabs and text walls.

## Rules kept (do not touch)
- Env.call(tool, args) stays the only way to act. Tools used: interview, search_messages, read_message, read_access_logs, check_leak_feed, plant_canary, advance_day, accuse, status.
- 8 actions per day (each tool above except status/list costs 1; HUD shows 8 pips). 21 days. Canary costs 0.01 V, max 2 per day, max 3 variants. Hard-tier leak and 95% variant truth are inside Env, unchanged.
- Mole never revealed before end. No mole tint, no suspicion color on sprites. Evidence only as counts in the case board (existing evidence()), not on people.
- Score: right = V, wrong -1, none 0. Shown only on the end screen.
- No comments, no em dashes, no network beyond Phaser 3.80.1 cdnjs (not needed: keep the existing canvas renderer, no Phaser).

## Screen
Canvas world 44x26 tiles, 16px tiles (704x416), scaled to fit with integer scale, pixelated. Camera: whole room fits on desktop; on phone it follows the player with 2x zoom and clamps to room.
HUD strip (top, 40px): day n/21, V bar, 8 action pips, clock. Nothing else. Icons only, no labels.
Dock (bottom, 72px, thumb zone, touch only): left d-pad ring optional (tap-to-walk is default), right two 64px buttons: USE (E) and BELL (end day). Every button min 64x64.
Ghost track: thin strip under HUD, 21 day cells. Gemini's committed moves for each day appear as small icons (mic, mail, log, paper, eye, door) in that day's cell, revealed as days pass, exactly the steps in data/gemini-N.json by day. Tap a cell: one bubble with the step name, max 8 words. Gemini's accusation shows as a door icon only at the end.

## Room map (tile coords, x right 0..43, y down 0..25)
Walls ring the room. All object coords are the tile of the interact point; player stands within 1.5 tiles to use.

| id | what | x,y | icon | use result |
|---|---|---|---|---|
| player_start | investigator spawn | 22,13 | | |
| desk_pc | your desk computer | 22,21 | monitor | inbox modal |
| server_term | server room terminal (room x 2..9, y 2..8, door at 9,6) | 5,4 | rack | access log modal |
| feed_tv | wall TV, north wall | 22,2 | tv | leak feed modal |
| printer | printer + paper tray | 36,21 | printer | print panel |
| bell | desk bell by exit | 40,13 | bell | end-day confirm |
| red_door | red door, east wall | 43,5 | red door | accuse mode |
| clock | wall clock (display only, not interactable) | 16,2 | clock | |
| case_board | corkboard, west wall | 1,13 | pin | evidence counts per employee |

Employee pods (5 departments, 8 desks each, desks 2x1 tiles, 4 per row, 2 rows per pod). Pod origins (top-left tile):
- Engineering 12,5
- Finance 24,5
- Sales 33,9
- Legal 12,15
- Research 28,15
Desk k in pod (0..7): x = ox + (k%4)*3, y = oy + floor(k/4)*3. Employee stands at desk x, y+1 and wanders 1 tile (idle bob, flip). Pod center marker (floor mat tile, dept color) at ox+4, oy+2 in each pod: used for group drops.
Employee to desk mapping: world.employees in order, grouped by dept, index within dept = k. Tiles from existing roguelike-indoor and tiny-dungeon sheets (see assets/manifest.json). Collision map built from walls, desks, racks, printer, tv base; employees are not solid for the player to avoid soft locks (player passes through with slow-down) but block interaction targeting only by proximity.
Evening: at BELL, lights dim to night over 1.2 s, employees fade out, clock jumps 09:00 next day; Env.t_advance_day result drives toasts.

## Controls
Keyboard: WASD or arrows move (8 px/frame at 60 fps normalized by dt, 90 px/s), E or Space = USE nearest interactable, Esc closes modal, B = bell prompt, Q = drop/cancel carried item, 1/2/3 = pick variant when at printer.
Touch: tap floor = path-walk (A* on 44x26 grid, capped 600 nodes), tap an object or employee = walk there then auto-USE on arrival (tap bubble shows icon above target while walking). Tap a modal button to act. No hover dependence, no double tap, no long press.
Nearest interactable within 1.5 tiles gets a bobbing icon bubble and its label (max 2 words). USE button (touch) lights up when one is in range.

## Interactions (each: big buttons, max 2 per step)

### Talk (employee)
Walk up, USE. Bubble opens above the employee, one speech-bubble line (max 8 words) plus 4 round topic icon buttons (64px): docs (recent_documents), people (contacts_outside), clock (workload), key (access_needs). Tap one: Env.call("interview", {employee, topic}) (1 action). Answer shows as a short bubble: engine text is clipped to the first sentence, full text kept in the case log, tap bubble to expand once. Evasive answers show a shrug icon plus the line. Cached answers (same employee/topic/day) cost nothing, bubble shows a repeat icon. Buttons: topic icons, plus X.

### Desk PC (inbox)
USE at desk_pc: modal with search field (large, 56px) and two buttons: READ (opens latest 8 messages, one list row = sender dot + 6-word subject) and SEARCH. Tapping a row = read_message (1 action) and shows the snippet in one bubble. Search uses search_messages (1 action). Rows are tappable, result count chip shown. Buttons: SEARCH, CLOSE.

### Server terminal (access logs)
USE: modal with a person picker (tap an employee face grid or leave all) and day range chips (today-1, last 3, all). One big button RUN calls read_access_logs (1 action). Output rows are icon + name + doc title, grouped by doc, after hours rows get a moon icon. Buttons: RUN, CLOSE.

### Leak TV
Walking near shows a flicker icon when feed has items. USE calls check_leak_feed (1 action) and shows cards: doc title, surfaced day, and on a canary variant a colored shape (square, circle, triangle for labels A, B, C). Buttons: CLOSE. No names shown.

### Printer + carry (core mechanic)
USE at printer opens print panel, step 1: doc title chips (2 to 3 of today's real documents from env.docs, not canary). Step 2: variant count 2 or 3, shown as shape tokens. Button PRINT. Printer spits N paper sprites into the tray (no engine call yet, no cost). Rules:
- Player carries one paper at a time, shown over the head (shape token). Walking speed 80%.
- Walk to a desk and USE (or tap it) to drop that variant on that employee's desk: paper sprite appears on the desk with the shape. Walk to a pod center mat and USE to drop on all 8 of that department at once.
- Dropping on an already assigned desk replaces it. Carrying paper to the tray and USE returns it.
- Restricted employees cannot receive (desk grayed, X icon), matches the engine filter.
- A small ledger chip near the HUD shows assigned count per variant, icons only.
- Commit happens at BELL: before the day ends, if any papers are placed, the bell dialog shows "SEND? n papers" with buttons SEND and BACK. SEND calls plant_canary({doc_title, assignment: {empId: label}}) once per document title (max 2 per day, 1 action each, 0.01 V each). Unplaced employees get nothing. Placed but uncommitted papers vanish if the player cancels with CLEAR.
Time cost is real: the walking IS the cost, plus the 8 action pips, so a thorough canary day is a trade-off with interviews.

### Bell (end day)
USE on bell, or B, or the dock button. Dialog: sun-to-moon icon and two buttons, END DAY and BACK (SEND replaces END DAY when papers are placed, see above). END DAY calls advance_day; then night animation, toasts: leak icon plus V change if leaked doc surfaced yesterday, plus new documents icon. Hard cap of day 21 ends the episode at 0.

### Red door (accuse)
USE: accuse mode, the 40 employee faces appear as a tap grid (48px tiles, 8 columns, scrollable on phone), sorted by dept, case_board evidence counts as small pip bars under each face (existing evidence()). Tap one: confirm card with two 64px buttons, ACCUSE (red) and BACK. Calls accuse. Then the end screen: score, who the mole was, Gemini result side by side, as the current finishDuel.

### Case board
Pure view of evidence() as pips per employee plus a short log of interviews as icons. Not required, USE at case_board opens it, CLOSE closes.

## Interaction registry API (js/core_world.js)
Global namespace `window.World`.

```
World.registerInteractable({
  id: string,            unique, e.g. "desk_pc", "emp:e07", "desk:e07", "pod:Finance"
  x: number,             tile x (float allowed), interaction anchor
  y: number,             tile y
  label: string,         max 2 words, shown with the icon
  icon: string,          icon key from World.icons (monitor, rack, tv, printer, bell, door, pin, mic, desk, mat)
  onUse: function(ctx),  ctx = { id, player: {x,y,carrying}, world: World, env: Env }
  radius?: number,       tiles, default 1.5
  enabled?: function(): boolean,   default always true
  solid?: boolean,       adds a collision box (w,h in tiles via w,h), default false
  w?: number, h?: number
})
World.unregisterInteractable(id)
World.moveInteractable(id, x, y)           employees that wander
World.getInteractable(id) -> object|null
World.nearest() -> object|null             current focus target
World.use()                                same as pressing E
World.player -> { x, y, carrying: null | {kind, data} }
World.setCarry(item|null)
World.walkTo(x, y, thenUse?: id)           path-walk, optional auto-use on arrival
World.openModal(html, buttons: [{label, icon, primary, onClick}]) -> close()
World.bubble(x, y, text, ms?)              world-anchored speech bubble, max 8 words enforced (truncate)
World.toast(text, kind?)
World.onFrame(fn(dt))                      per-frame hooks for features
World.onEvent(name, fn)                    names: "day:start", "day:end", "env:call", "mode:enter"
World.emit(name, payload)
World.hud.set({day, V, actions, clock})
World.env                                  the live Env, set by glue on mode start
World.act(tool, args) -> result            wraps env.call, updates HUD pips, emits "env:call"
```
Rules for features: a feature file only calls World.* and may not touch another feature file, index.html, or core internals. Each feature file exposes `window.Feat_<name> = { init(World) }` and registers its objects in init.

## File and module layout (3 builders, no shared edits)
- js/core_world.js (owner A): movement, collision grid, A* pathing, camera, rendering of tiles/sprites via existing Office assets (reuse js/office.js buildStatic and sprite compositing, read only), registry, modal and bubble helpers, HUD, input (keyboard, pointer), event bus. Also contains the room map table above as a const.
- js/feat_talk.js (owner B): employee interactables (emp:id, wander within 1 tile), topic buttons, interview calls, desk PC inbox, server terminal logs, leak TV, case board.
- js/feat_desk.js (owner C): bell/end-day flow, night animation, red door accuse grid, end screen glue, ghost track of Gemini moves, HUD pips. Does not touch the carry state.
- js/feat_carry.js (owner D or C after talk): printer panel, paper items, desk and pod drops, ledger chip, SEND commit via World.act("plant_canary").
- index.html (glue, one owner at merge): script tags in order, then
```
<script src="js/assets.js"></script><script src="js/data.js"></script>
<script src="js/engine.js"></script><script src="js/office.js"></script>
<script src="js/core_world.js"></script>
<script src="js/feat_talk.js"></script><script src="js/feat_desk.js"></script><script src="js/feat_carry.js"></script>
<script src="js/app.js"></script>
```
Menu card "Walk the office" starts the mode: app.js builds Env for the seed, sets World.env, calls World.start(seed), and each Feat_*.init(World). The old duel UI stays untouched as another mode (additive).
Task split note: the user asked for talk, desk, carry features; bell, red door, and ghost track sit in feat_desk.js, while the desk PC, terminal, and TV sit in feat_talk.js so each file has about the same size.

## Faithfulness and checks
- Never read env.w.mole or env.Vtrue in any UI path other than the end screen. Display V via env.V as the engine already does.
- Smoke test per feature: scripted pass that registers, walks to each object, USEs, and asserts env.actions decreases by 1 for costed tools and by 0 for cached interviews.
- Click-test on touch emulation before ship: tap employee, tap topic, tap desk PC, tap printer, carry and drop, bell, red door. Close any browser opened after.

## Open items
- No walk frames in Kenney packs: bob plus flip, as ASSETS.md says.
- Sound: none for v1.
- Hosting: static folder, works from file:// and GitHub Pages; the share link is the Pages URL of docs/arena.
