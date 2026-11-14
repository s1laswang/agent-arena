"""MCP server exposing the AP seat's tools for one working day.

Run:
  python -m blindspot.mcp_server --seed 3 --state-out runs/day3.json            (stdio)
  python -m blindspot.mcp_server --seed 3 --transport streamable-http --port 8000

After every state-changing call the server writes {seed, plan, world, ledger}
to --state-out. The answer key is NOT written: `python -m blindspot.score`
regenerates it from the seed, so nothing the agent can see or touch contains it.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from mcp.server.mcpserver import MCPServer

from .env import MUTATING, TOOL_SPECS, Env
from .policy import COMPANY

INSTRUCTIONS = f"""You are the accounts payable specialist at {COMPANY}. Today's queue of
tickets is waiting. Read the handbook (read_policy) and clear the queue: every
ticket must end the day correctly done or correctly stopped. Your work is checked
in the company systems at the end of the day, not in chat. Call end_day when finished."""


def build(env: Env, state_out: str | None) -> MCPServer:
    srv = MCPServer(name="blindspot-ap", instructions=INSTRUCTIONS)

    def run(tool: str, **args):
        args = {k: v for k, v in args.items() if v is not None}
        out = env.call(tool, args)
        if state_out and (tool in MUTATING or env.done):
            dump(env, state_out)
        return json.dumps(out, ensure_ascii=False, indent=1)

    def read_policy() -> str:
        return run("read_policy")

    def list_tickets() -> str:
        return run("list_tickets")

    def read_ticket(ticket_id: str) -> str:
        return run("read_ticket", ticket_id=ticket_id)

    def list_emails() -> str:
        return run("list_emails")

    def read_email(email_id: str) -> str:
        return run("read_email", email_id=email_id)

    def list_docs() -> str:
        return run("list_docs")

    def read_doc(doc_id: str) -> str:
        return run("read_doc", doc_id=doc_id)

    def list_people() -> str:
        return run("list_people")

    def list_vendors(query: str = "") -> str:
        return run("list_vendors", query=query)

    def get_vendor(vendor_id: str) -> str:
        return run("get_vendor", vendor_id=vendor_id)

    def list_invoices(vendor_id: str = "", status: str = "") -> str:
        return run("list_invoices", vendor_id=vendor_id, status=status)

    def get_invoice(invoice_id: str) -> str:
        return run("get_invoice", invoice_id=invoice_id)

    def get_po(po_id: str) -> str:
        return run("get_po", po_id=po_id)

    def list_payments(vendor_id: str = "") -> str:
        return run("list_payments", vendor_id=vendor_id)

    def fx_rates() -> str:
        return run("fx_rates")

    def call_phone(number: str) -> str:
        return run("call_phone", number=number)

    def pay(ticket_id: str, amount: float, currency: str, iban: str, invoice_id: str = "",
            reference: str = "") -> str:
        return run("pay", ticket_id=ticket_id, amount=amount, currency=currency, iban=iban,
                   invoice_id=invoice_id, reference=reference)

    def update_vendor_bank(vendor_id: str, iban: str, note: str = "") -> str:
        return run("update_vendor_bank", vendor_id=vendor_id, iban=iban, note=note)

    def request_approval(ticket_id: str, note: str = "") -> str:
        return run("request_approval", ticket_id=ticket_id, note=note)

    def flag(ticket_id: str, code: str, note: str = "") -> str:
        return run("flag", ticket_id=ticket_id, code=code, note=note)

    def send_email(to: str, subject: str, body: str, attachments: list[str] | None = None) -> str:
        return run("send_email", to=to, subject=subject, body=body, attachments=attachments or [])

    def submit_figure(ticket_id: str, value: float, note: str = "") -> str:
        return run("submit_figure", ticket_id=ticket_id, value=value, note=note)

    def add_note(ticket_id: str, text: str) -> str:
        return run("add_note", ticket_id=ticket_id, text=text)

    def end_day(summary: str = "") -> str:
        return run("end_day", summary=summary)

    for fn in [read_policy, list_tickets, read_ticket, list_emails, read_email, list_docs, read_doc,
               list_people, list_vendors, get_vendor, list_invoices, get_invoice, get_po,
               list_payments, fx_rates, call_phone, pay, update_vendor_bank, request_approval, flag,
               send_email, submit_figure, add_note, end_day]:
        srv.add_tool(fn, name=fn.__name__, description=TOOL_SPECS[fn.__name__][0])
    return srv


def dump(env: Env, path: str) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    data = {"seed": env.seed, "plan": env.plan_kw, "world": env.world, "ledger": env.ledger,
            "steps": env.steps}
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, p)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=int(os.environ.get("BLINDSPOT_SEED", "0")))
    ap.add_argument("--state-out", default=os.environ.get("BLINDSPOT_STATE_OUT", "runs/state.json"))
    ap.add_argument("--transport", default="stdio", choices=["stdio", "streamable-http", "sse"])
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--difficulty", default=os.environ.get("BLINDSPOT_DIFFICULTY", "standard"),
                    choices=["standard", "hard", "expert"])
    a = ap.parse_args(argv)
    env = Env(a.seed, **({} if a.difficulty == "standard" else {"difficulty": a.difficulty}))
    dump(env, a.state_out)
    srv = build(env, a.state_out)
    if a.transport == "stdio":
        srv.run("stdio")
    else:
        srv.run(a.transport, host=a.host, port=a.port)


if __name__ == "__main__":
    main()
