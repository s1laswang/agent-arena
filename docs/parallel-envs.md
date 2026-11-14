# Parallel environments scouted

Scouted 2026-11-14 with `gh` and web search. Facts only. Anything not verified is marked NOT FOUND.

## Silas, "Canary" (GitHub justSilas)

- Repo: NOT FOUND. `gh repo list justSilas` returns one repo, `Justsilas/Justsilas` (profile config, last push 2021-12-17). `gh search repos` for "canary" under that owner returns nothing. Web search finds no Silas "Canary" agent environment.
- Likely causes: private repo, different handle, or not pushed yet.
- What it tests / scoring / threat model / models / numbers: NOT FOUND.
- Name clash: `devnw/canary` (Go, canary tokens in agent repos) is unrelated, but our own `rw-canary` worker and "canary" wording in The Sleeper may be confused with Silas's project in the room. Ask Silas for the exact URL.

## Vaishnav, poisoned-inbox

- `vaishnav/poisoned-inbox`: NOT FOUND (gh: "Could not resolve to a Repository"). `gh search users vaishnav` and web search gave no match.
- Only public hit for the name: https://github.com/bobbyhalljr/tiny-poisoned-inbox (owner bobbyhalljr, not Vaishnav, pushed 2026-10-26, HEAD 7ab9689). Treat as UNCONFIRMED lookalike, may be unrelated.
  - Tests: one poisoned email (instructions in an HTML comment) makes a deliberately obedient mock model forward a card number and SSN to an attacker.
  - Scoring: none. It is a demo, with a 19-line outbound guard (`guard.ts`, Luhn-checked card numbers and SSN-like IDs blocked). No reward, no model run.
  - Threat model: indirect prompt injection via email, exfiltration of sensitive strings.
  - Models and numbers: NOT FOUND. No API key, mock model only (README).
  - Source: https://github.com/bobbyhalljr/tiny-poisoned-inbox (README, `inbox.ts`, `agent.ts`, `guard.ts`).
- Other public inbox-injection benchmark seen in search, not Vaishnav's: LivePI, https://arxiv.org/abs/2605.17986, github leizhao7/livepi (not read).

## Useful for us (only from sources actually read)

- Contrast: the lookalike scores by a pattern guard on outbound content. The Sleeper scores by verifiable state, which is harder to evade by encoding.
- Borrow: its "break my guard" list (spell digits in words, split across two messages, base64, strip dashes). Worth checking our verifier and canary against the same encodings.
- Overlap risk with The Sleeper: low for the lookalike (mock model, no reward). Unknown for the two real projects until URLs arrive.
- Next step: get both URLs from Silas and Vaishnav, then rerun this scout. This file should be updated, not trusted as complete.
