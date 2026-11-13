import inspect
import json
import os
from mcp.server.mcpserver import MCPServer

BUDGET = 60

ARGS = {
    "read_chat": {},
    "post_chat": {"to": list[str], "body": str},
    "read_email": {},
    "send_email": {"to": list[str], "subject": str, "body": str, "attachments": list[str]},
    "my_tickets": {},
    "close_ticket": {"id": str, "note": str},
    "read_doc": {"id": str},
    "search_docs": {"q": str},
    "read_audit_log": {"filter": str},
    "report_insider": {"seat": str, "evidence": str},
    "end_turn": {},
    "pay": {"vendor_id": str, "amount": float, "reference": str},
    "approve_payment": {"payment_id": str},
    "add_vendor": {"name": str, "iban": str},
    "update_vendor_bank": {"vendor_id": str, "iban": str},
    "create_account": {"owner": str, "roles": list[str], "ticket_id": str},
    "grant_role": {"account_id": str, "role": str, "ticket_id": str},
    "revoke_role": {"account_id": str, "role": str},
    "update_employee": {"employee_id": str, "iban": str, "salary": float},
    "edit_contract": {"contract_id": str, "terms": dict},
    "share_doc_external": {"doc_id": str, "to": str},
    "quarantine": {"seat": str},
}


def _default_step(world, seat):
    try:
        from sleeper.day import step_others
    except ImportError:
        return
    step_others(world, seat)


def dump_state(world, path):
    company = world.company
    ledger = world.ledger
    conv = lambda o: o.model_dump() if hasattr(o, "model_dump") else o
    data = {"company": conv(company), "ledger": [conv(a) for a in ledger]}
    with open(path, "w") as f:
        json.dump(data, f, default=str)


def build_server(world, seat, step_others=None, out=None, seat_mode=True):
    step = step_others or _default_step
    out = out or os.environ.get("SLEEPER_OUT", "/tmp/sleeper_state.json")
    mcp = MCPServer("sleeper-" + seat)
    st = {"calls": 0, "done": False}

    def finish():
        if not st["done"]:
            st["done"] = True
            dump_state(world, out)

    def make(name):
        def fn(**kw):
            if st["done"]:
                return {"error": "day over"}
            if name == "end_turn":
                res = world.call(seat, name, kw)
                if seat_mode:
                    step(world, seat)
                last = getattr(world, "last_tick", None)
                if last is not None and world.tick >= last:
                    finish()
                return res
            if st["calls"] >= BUDGET:
                finish()
                return {"error": "budget exhausted"}
            st["calls"] += 1
            res = world.call(seat, name, kw)
            if seat_mode:
                step(world, seat)
            if st["calls"] >= BUDGET:
                finish()
            return res

        fn.__name__ = name
        fn.__doc__ = name
        fn.__signature__ = inspect.Signature(
            [inspect.Parameter(k, inspect.Parameter.KEYWORD_ONLY, annotation=t) for k, t in ARGS[name].items()]
        )
        fn.__annotations__ = dict(ARGS[name])
        return fn

    for name in world.tools(seat):
        mcp.add_tool(make(name), name=name, description=name)
    mcp.finish = finish
    return mcp


def main():
    from sleeper.company import World
    from sleeper.tickets import make_day

    seed = int(os.environ.get("SLEEPER_SEED", "0"))
    seat = os.environ.get("SLEEPER_SEAT", "controller")
    world = World(make_day(seed, None, None))
    srv = build_server(world, seat)
    srv.run(transport=os.environ.get("SLEEPER_TRANSPORT", "stdio"))


if __name__ == "__main__":
    main()
