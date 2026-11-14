# Merge-readiness review: Ivar's game branch (S5, Sat 14 Nov 23:20)

## Scope
- **`origin/ivar/aq-game-ux` does not exist.** At 23:20 Sat there was no such branch on GitHub (`git ls-remote origin` lists only `ivar/main` and `ivar/game-v-port`), no PR from Ivar, and no `docs/VIDEO-SCRIPT.md` or `docs/research-biases.md` on any ref or on disk. The research and video-script parts **could not be reviewed**. Ivar: push the branch and open a PR into `justSilas`.
- Reviewed instead: **`origin/ivar/game-v-port` @ `e00232b`** ("game: break-even accuse dialog, canary builder fixes, favicon"), Ivar's newest game commit not yet in justSilas. It touches only `game/app.js`, `game/index.html` and `game/style.css` (+166/−15); `canary/`, `game/canary_game.py` and `game/build.py` are unchanged.

## Verdict: **merge-ready** (one should-fix, optional before merge)
| Check | Result |
|---|---|
| Merges cleanly into `justSilas` (309b65f) | yes (`git merge-tree` clean; justSilas has not touched `game/` since the merge base b4a50db) |
| `make game` / `make game-serve` (justSilas) | build < 1 s ("built game/site: 15 python files"); serves HTTP 200 on :8000, `py/manifest.json` OK |
| Ivar's build (justSilas `game/site` + his three static files) in headless Chrome | boots to "ready" in 2.7 s; **0 console errors**, 0 failed requests |
| **Score parity, seed 3000 (medium, v1.4)**: the solver's 48 recorded tool calls replayed through the page's own `run()`, the final accusation through the new dialog | browser (Pyodide): **0.79, accused e09, correct, day 6, 48 calls**; CPython `Env`: **0.79, e09**; CPython `canary_game.Game`: 0.79; the solver score in the browser reveal: 0.79, identical to CPython `solver_result(3000)` |
| Accuse dialog gate | "Accuse" stays disabled until the id is typed; enabled after; submits exactly one `accuse`; `S.over` true after |
| No hints or computed guilt added | confirmed: the certainty slider is the player's own and is never sent to the engine |

## Issues for Ivar
1. **(should-fix) The break-even and expected score use the visible V, but the score uses the true V.** In the seed-3000 run the dialog showed V 0.83, break-even 54.6%, and an expected score of +0.65 at 90%. The episode then scored 0.79, because the true V counts leaks that have not surfaced yet. The fine print already says "true value … counts leaks that have not surfaced yet", but the numbers above it are optimistic, so a player who trusts them accuses slightly early. Fix: label them "at the visible value (true value can only be lower), so the real break-even is at least X%", or show `≥` on the break-even.
2. (nit) **Even split with nobody assigned assigns the whole staff list** (all employees, A/B/C in list order). That's fine as a feature, but say "everyone" in the button title. A 3-way split over the whole company is the weakest canary on hard.
3. (nit) No test covers the new dialog. `tests/test_game.py` is CPython-only. Consider committing the headless check below as `game/tests/` or a `make game-check`.
4. (process) Rebase isn't needed (clean merge), but open a PR so CI runs and the CEO can merge. The research and video-script work needs its own push.

## How this was checked (reproducible)
- CPython record: solver on `canary_game.TIER`, seed 3000; the calls replayed through `canary_game.Game` too.
- Browser: Chrome headless over CDP, page served from a copy of `game/site` with Ivar's three files. The 47 non-accuse calls go through `run(tool, args)`; then `openAccuse("e09")` → certainty 90 → type "e09" → `accForm.requestSubmit()` → `S.game.reveal_json()`.
- The scripts are in the S5 job directory (not committed); the CEO can ask for them.
