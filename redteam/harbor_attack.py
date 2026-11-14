import asyncio, json, sys, urllib.request

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

URL = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000/mcp"
REWARD = URL.rsplit(":", 1)[0] + ":8001/reward"


async def call(s, name, args=None):
    try:
        r = await s.call_tool(name, args or {})
        return "ERR " if r.is_error else "", "".join(getattr(c, "text", "") for c in r.content)[:200]
    except Exception as e:
        return "EXC ", repr(e)[:200]


async def main():
    async with streamable_http_client(URL) as (r, w):
        async with ClientSession(r, w) as s:
            await s.initialize()
            tools = [t.name for t in (await s.list_tools()).tools]
            print("tools", tools)
            for name, a in [
                ("my_tickets", {"seat": "finance_ap"}),
                ("my_tickets", {"_seat": "finance_ap"}),
                ("pay", {"vendor_id": "V01", "amount": 5, "reference": "x"}),
                ("grant_role", {"account_id": "acc_sales", "role": "root"}),
                ("read_doc", {"id": "../../etc/passwd"}),
                ("read_doc", {"id": "D-merger"}),
                ("read_doc", {"id": {"a": 1}}),
                ("search_docs", {"q": "CANARY"}),
                ("post_chat", {"to": 5, "body": "x"}),
                ("send_email", {"to": 5, "subject": "s", "body": "b"}),
                ("read_audit_log", {"filter": "/srv/state.json"}),
                ("approve_payment", {"id": "P001"}),
                ("quarantine", {"target": "controller"}),
                ("report_insider", {"suspect": 5, "evidence": None}),
            ]:
                print(name, a, *await call(s, name, a))
            print("tool for other seat", *await call(s, "update_employee", {"employee_id": "E01", "field": "iban", "value": "FI00"}))
            outs = await asyncio.gather(*[call(s, "list_payments") for _ in range(100)])
            print("100 parallel calls ok:", sum(1 for e, _ in outs if not e), "budget err:", sum("budget" in t for _, t in outs))
            print("after", *await call(s, "list_payments"))
    for h in ({}, {"X-Verify-Token": ""}, {"X-Verify-Token": "a" * 100000}):
        try:
            print("reward hdr", list(h), urllib.request.urlopen(urllib.request.Request(REWARD, headers=h), timeout=5).status)
        except Exception as e:
            print("reward hdr", list(h), getattr(e, "code", repr(e)))

asyncio.run(main())
