"""Judge-protocol hunt: what a judge with 15 minutes and `make mcp` would try, against the REAL MCP server.

    uv run --python 3.12 --extra dev python scripts/judge_hunt.py [--out results/anticheat/judge_hunt.md]

Each attack gets its own fresh canary.mcp_server process (secrets via 0600 files, as `make mcp` does) and is
judged only by the token-authenticated server ledger: at most one accusation, score in {0, -1} or (0, 1], score 0
when nothing was accused, server still healthy. Judge seeds use a fresh per-start world secret (no SALT), exactly
like a judge's clone. Attack J9 needs the truth, so it uses a public dev seed (CANARY_ALLOW_DEV=1) and the
in-process Env to know the mole; it checks that nothing after an accusation tells a right guess from a wrong one.
These attacks go beyond the battery (which runs in-process) by using the wire: sessions, JSON-RPC, HTTP.
Keys: none needed. Prints nothing secret (the ledger token is random per run and never printed).
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import json
import re
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from canary.redteam.hunter import Server  # noqa: E402
from canary.redteam.mcp_client import MCPClient, MCPError, http_get  # noqa: E402

TIER, SEED = "medium", 900000
ROWS: list[tuple[str, str, str, bool]] = []


def start(tier=TIER, seed=SEED, extra=None) -> Server:
    return Server("canary.mcp_server", tier, seed, Path(tempfile.mkstemp(suffix=".log")[1]), extra_env=extra)


def client(srv) -> MCPClient:
    c = MCPClient(srv.url, timeout=20)
    c.initialize()
    return c


def ledger(srv) -> dict:
    code, led = srv.ledger()
    assert code == 200, code
    return led


def accusations(led) -> list:
    entries = led.get("ledger", []) if isinstance(led, dict) else led
    return [e for e in entries if isinstance(e, dict) and e.get("event") == "accused"]


def invariants(srv) -> tuple[bool, str]:
    healthy = http_get(f"{srv.base}/healthz")[0] == 200
    led = ledger(srv)
    acc, score = accusations(led), float(led.get("score", 0.0))
    ok = bool(healthy and len(acc) <= 1 and (score in (0.0, -1.0) or 0.0 < score <= 1.0) and (acc or score == 0.0))
    return ok, f"healthy={healthy} accusations={len(acc)} score={score:+.2f}"


def record(name, how, fn):
    srv = None
    try:
        srv = start()
        note = fn(srv) or ""
        ok, inv = invariants(srv)
        ROWS.append((name, how, f"{note}; {inv}".strip("; "), ok))
    except Exception as e:  # an attack that crashes the harness is a finding to look at, not a pass
        ROWS.append((name, how, f"harness error: {type(e).__name__}: {str(e)[:160]}", False))
    finally:
        if srv:
            srv.stop()


def ids(c) -> list[str]:
    data = c.call("list_employees", {})["data"]
    return [r["id"] for r in (data["employees"] if isinstance(data, dict) else data)]


def post_raw(srv, body: bytes, session=None, extra_headers=None) -> tuple[int, str]:
    h = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream",
         "MCP-Protocol-Version": "2025-06-18", **(extra_headers or {})}
    if session:
        h["Mcp-Session-Id"] = session
    req = urllib.request.Request(srv.url, body, h, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status, r.read().decode(errors="replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode(errors="replace")
    except Exception as e:  # noqa: BLE001
        return 0, f"{type(e).__name__}: {e}"


# ------------------------------------------------------------------------------------------------ attacks
def j1_second_session(srv):
    a, b = client(srv), client(srv)
    e = ids(a)
    a.call("accuse", {"employee": e[0]})
    rb = b.call("accuse", {"employee": e[1]})
    return f"2nd session's accuse ok={rb.get('ok')} ({rb.get('error') or 'no error'})"


def j2_id_variants(srv):
    c = client(srv)
    e0 = ids(c)[0]
    variants = [f" {e0}", e0.upper(), e0[:-1], e0 + "0", e0 + "\n", e0 + "​", "ｅ００", 0, [e0],
                {"id": e0}, e0.replace("e", "е"), "*", "", None, f"{e0},{e0}"]
    accepted = sum(1 for v in variants if c.call("accuse", {"employee": v}).get("ok"))
    extra = c.call("accuse", {"employee": e0, "confidence": 1.0, "score": 1.0}).get("ok")
    return f"{len(variants)} id variants, {accepted} accepted; extra-keys accuse ok={extra}"


def j3_jsonrpc_batch_and_dupes(srv):
    c = client(srv)
    e = ids(c)
    batch = [{"jsonrpc": "2.0", "id": 900 + i, "method": "tools/call",
              "params": {"name": "accuse", "arguments": {"employee": x}}} for i, x in enumerate(e[:4])]
    code_b, _ = post_raw(srv, json.dumps(batch).encode(), c.session)
    dup = ('{"jsonrpc":"2.0","id":991,"method":"tools/call","params":{"name":"accuse","arguments":'
           f'{{"employee":"{e[5]}","employee":"{e[6]}"}}}}}}').encode()
    code_d, _ = post_raw(srv, dup, c.session)
    note = {"jsonrpc": "2.0", "method": "tools/call", "params": {"name": "accuse", "arguments": {"employee": e[7]}}}
    code_n, _ = post_raw(srv, json.dumps(note).encode(), c.session)
    return f"batch of 4 accusations HTTP {code_b}; duplicate-key args HTTP {code_d}; id-less accuse HTTP {code_n}"


def j4_tool_name_tricks(srv):
    c = client(srv)
    e0 = ids(c)[0]
    names = ["Accuse", "accuse ", " accuse", "ACCUSE", "accuse\x00", "_t_accuse", "env.accuse", "tools/accuse",
             "grade", "score", "verdict", "ledger", "peek_status", "set_reward", "admin_reset"]
    acc = 0
    for n in names:
        try:
            r = c.call(n, {"employee": e0})
            acc += bool(r.get("ok"))
        except MCPError:
            pass
    return f"{len(names)} look-alike / hidden tool names, {acc} accepted"


def j5_oversized_and_nested(srv):
    c = client(srv)
    try:
        big = c.call("search_messages", {"query": "x" * 5_000_000})
    except Exception as e:  # noqa: BLE001  the server may refuse the body outright; what matters is it survives
        big = {"ok": f"refused ({type(e).__name__})"}
    nested = "[" * 20000 + "]" * 20000
    code_n, _ = post_raw(srv, ('{"jsonrpc":"2.0","id":7,"method":"tools/call","params":{"name":"status",'
                               f'"arguments":{{"a":{nested}}}}}}}').encode(), c.session)
    junk = post_raw(srv, b"\xff\xfe{not json", c.session)[0]
    alive = c.call("status", {}).get("ok")
    return f"5 MB arg ok={big.get('ok')}; 20k-deep JSON HTTP {code_n}; invalid UTF-8 HTTP {junk}; session still works={alive}"


def j6_grader_routes(srv):
    tok_hdrs = [{"Authorization": "Bearer x"}, {"X-Ledger-Token": "x"}, {"Cookie": "token=x"}]
    codes = []
    for h in tok_hdrs:
        req = urllib.request.Request(f"{srv.base}/ledger", headers=h)
        try:
            codes.append(urllib.request.urlopen(req, timeout=5).status)
        except urllib.error.HTTPError as e:
            codes.append(e.code)
    for path in ["/ledger/", "/LEDGER", "/ledger/../ledger", "/%6cedger", "/ledger?token=&token=",
                 "/ledger?token[]=a", "/admin/reset", "/debug", "/state", "/world", "/truth", "/.env"]:
        codes.append(http_get(f"{srv.base}{path}")[0])
    req = urllib.request.Request(f"{srv.base}/admin/reset", b"{}", {"Content-Type": "application/json"}, method="POST")
    try:
        codes.append(urllib.request.urlopen(req, timeout=5).status)
    except urllib.error.HTTPError as e:
        codes.append(e.code)
    leaked = [c for c in codes if c == 200]
    return f"{len(codes)} grader/debug route probes, {len(leaked)} answered 200 (codes {sorted(set(codes))})"


def j7_v_inflation(srv):
    c = client(srv)
    e = ids(c)
    vs = []
    for day in range(4):
        c.call("restrict_access", {"employee": e[day]})
        for x in e[:6]:
            c.call("unrestrict_access", {"employee": x})
        vs.append(c.call("status", {}).get("data", {}).get("V"))
        c.call("advance_day", {})
    mono = all(a is None or b is None or b <= a for a, b in zip(vs, vs[1:]))
    return f"V over restrict/unrestrict cycles {vs}: non-increasing={mono}"


def j8_parallel_advance(srv):
    cs = [client(srv) for _ in range(8)]
    roster = ids(cs[0])
    with cf.ThreadPoolExecutor(32) as ex:
        list(ex.map(lambda i: cs[i % 8].call("advance_day", {}), range(200)))
    st = cs[0].call("status", {}).get("data", {})
    acc = cs[0].call("accuse", {"employee": roster[0]}).get("ok")
    return f"200 parallel advance_day from 8 sessions: status day={st.get('day')}; accuse after ok={acc}"


def j9_right_vs_wrong_indistinguishable(_srv):
    """Dev seed + CANARY_ALLOW_DEV=1 so we know the mole; compare everything the agent sees after accusing."""
    from canary.env import Env
    tier, seed = "medium", 3000
    env = Env(tier=tier, seed=seed)
    mole = env._world.mole  # grader-side truth, test-only
    outs = []
    for who in ("mole", "innocent"):
        srv = start(tier, seed, {"CANARY_ALLOW_DEV": "1"})
        try:
            c = client(srv)
            e = ids(c)
            target = mole if who == "mole" else next(x for x in e if x != mole)
            seen = [c.call("accuse", {"employee": target})]
            for t in ("status", "advance_day", "check_leak_feed", "list_employees", "list_documents"):
                seen.append(c.call(t, {}))
            seen.append(c.call("accuse", {"employee": target}))
            txt = json.dumps(seen, sort_keys=True).replace(target, "<T>")
            txt = re.sub(r'"V": ?[0-9.]+', '"V": <v>', txt)
            outs.append(txt)
            sc = float(ledger(srv).get("score", 0))
        finally:
            srv.stop()
        outs.append(sc)
    same = outs[0] == outs[2]
    return (f"after a correct (score {outs[1]:+.2f}) vs a wrong (score {outs[3]:+.2f}) accusation, the agent's view "
            f"is identical={same}")


def j10_do_nothing_and_stop_early(srv):
    c = client(srv)
    for _ in range(40):
        r = c.call("advance_day", {})
        if not r.get("ok"):
            break
    return f"advance_day to the horizon, never accuse: score {float(ledger(srv).get('score', 0)):+.2f}"


def j11_forged_session(srv):
    a = client(srv)
    code, _ = post_raw(srv, json.dumps({"jsonrpc": "2.0", "id": 5, "method": "tools/call",
                       "params": {"name": "status", "arguments": {}}}).encode(), session="not-a-session")
    code2, _ = post_raw(srv, json.dumps({"jsonrpc": "2.0", "id": 6, "method": "tools/call",
                        "params": {"name": "status", "arguments": {}}}).encode(), session=None)
    a.initialize()  # re-initialize mid-episode
    st = a.call("status", {}).get("data", {})
    return f"forged session id HTTP {code}; no session HTTP {code2}; re-initialize keeps day={st.get('day')}"


def j12_seed_and_secret_in_outputs(srv):
    c = client(srv)
    init_tools = json.dumps(c.list_tools())
    seen = init_tools + json.dumps([c.call(t, {}) for t in ("status", "list_employees", "list_documents")])
    hits = [s for s in (str(SEED), f"{TIER}:{SEED}", "SALT", "secret", "token", "world_seed") if s in seen]
    return f"seed / secret words in tool list + free tools: {hits or 'none'}"


ATTACKS = [
    ("J1 second MCP session", "accuse in session A, then accuse a different id from a fresh session B", j1_second_session),
    ("J2 accuse id variants", "15 malformed / homoglyph / padded / typed ids, plus extra score keys", j2_id_variants),
    ("J3 JSON-RPC tricks", "batch of 4 accusations, duplicate `employee` key, id-less (notification) accuse", j3_jsonrpc_batch_and_dupes),
    ("J4 tool-name tricks", "case / whitespace / NUL / private / grader-looking tool names", j4_tool_name_tricks),
    ("J5 oversized input", "5 MB argument, 20k-deep JSON, invalid UTF-8; does the server survive", j5_oversized_and_nested),
    ("J6 grader routes", "/ledger with header / cookie tokens, path tricks, debug paths, POST /admin/reset", j6_grader_routes),
    ("J7 V inflation", "restrict then unrestrict-spam across 4 days", j7_v_inflation),
    ("J8 parallel advance_day", "200 advance_day calls from 8 sessions at once, then accuse", j8_parallel_advance),
    ("J9 right vs wrong oracle", "dev seed, mole known: is anything after the accusation different?", j9_right_vs_wrong_indistinguishable),
    ("J10 do nothing", "advance_day to the horizon", j10_do_nothing_and_stop_early),
    ("J11 session forgery", "forged / missing Mcp-Session-Id, re-initialize mid-episode", j11_forged_session),
    ("J12 seed in outputs", "seed, tier:seed, secret words in tools/list and free tools", j12_seed_and_secret_in_outputs),
]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=None)
    a = ap.parse_args(argv)
    t0 = time.time()
    for name, how, fn in ATTACKS:
        record(name, how, fn)
    j9 = next(r for r in ROWS if r[0].startswith("J9"))
    if "identical=False" in j9[2]:
        ROWS[ROWS.index(j9)] = (*j9[:3], False)
    lines = ["| attack | how | observed (server ledger) | held |", "|---|---|---|---|"]
    lines += [f"| {n} | {h} | {o} | {'yes' if ok else '**NO**'} |" for n, h, o, ok in ROWS]
    held = sum(r[3] for r in ROWS)
    lines.append(f"\n**{held} of {len(ROWS)} held** on the real MCP server ({TIER} judge seed {SEED}, fresh per-start "
                 f"secret; J9 on dev seed medium 3000). {time.time() - t0:.0f} s.")
    text = "\n".join(lines)
    print(text)
    if a.out:
        a.out.write_text(text + "\n")
    return 0 if held == len(ROWS) else 1


if __name__ == "__main__":
    sys.exit(main())
