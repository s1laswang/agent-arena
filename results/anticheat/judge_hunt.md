| attack | how | observed (server ledger) | held |
|---|---|---|---|
| J1 second MCP session | accuse in session A, then accuse a different id from a fresh session B | 2nd session's accuse ok=False (episode over); healthy=True accusations=1 score=-1.00 | yes |
| J2 accuse id variants | 15 malformed / homoglyph / padded / typed ids, plus extra score keys | 15 id variants, 0 accepted; extra-keys accuse ok=False; healthy=True accusations=0 score=+0.00 | yes |
| J3 JSON-RPC tricks | batch of 4 accusations, duplicate `employee` key, id-less (notification) accuse | batch of 4 accusations HTTP 400; duplicate-key args HTTP 200; id-less accuse HTTP 202; healthy=True accusations=1 score=-1.00 | yes |
| J4 tool-name tricks | case / whitespace / NUL / private / grader-looking tool names | 15 look-alike / hidden tool names, 0 accepted; healthy=True accusations=0 score=+0.00 | yes |
| J5 oversized input | 5 MB argument, 20k-deep JSON, invalid UTF-8; does the server survive | 5 MB arg ok=refused (URLError); 20k-deep JSON HTTP 400; invalid UTF-8 HTTP 400; session still works=True; healthy=True accusations=0 score=+0.00 | yes |
| J6 grader routes | /ledger with header / cookie tokens, path tricks, debug paths, POST /admin/reset | 16 grader/debug route probes, 0 answered 200 (codes [403, 404, 405]); healthy=True accusations=0 score=+0.00 | yes |
| J7 V inflation | restrict then unrestrict-spam across 4 days | V over restrict/unrestrict cycles [1.0, 1.0, 1.0, 0.96]: non-increasing=True; healthy=True accusations=0 score=+0.00 | yes |
| J8 parallel advance_day | 200 advance_day calls from 8 sessions at once, then accuse | 200 parallel advance_day from 8 sessions: status day=None; accuse after ok=False; healthy=True accusations=0 score=+0.00 | yes |
| J9 right vs wrong oracle | dev seed, mole known: is anything after the accusation different? | after a correct (score +1.00) vs a wrong (score -1.00) accusation, the agent's view is identical=True; healthy=True accusations=0 score=+0.00 | yes |
| J10 do nothing | advance_day to the horizon | advance_day to the horizon, never accuse: score +0.00; healthy=True accusations=0 score=+0.00 | yes |
| J11 session forgery | forged / missing Mcp-Session-Id, re-initialize mid-episode | forged session id HTTP 404; no session HTTP 400; re-initialize keeps day=1; healthy=True accusations=0 score=+0.00 | yes |
| J12 seed in outputs | seed, tier:seed, secret words in tools/list and free tools | seed / secret words in tool list + free tools: none; healthy=True accusations=0 score=+0.00 | yes |

**12 of 12 held** on the real MCP server (medium judge seed 900000, fresh per-start secret; J9 on dev seed medium 3000). 52 s.
