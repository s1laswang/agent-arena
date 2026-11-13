import random

from . import backdoor, fraud, frame, leak, sabotage
from ._base import SEATS, SleeperGoal, Step, Strategy

MODULES = {"fraud": fraud, "leak": leak, "backdoor": backdoor, "sabotage": sabotage, "frame": frame}

NEEDS = {
    "fraud.bank_swap": ["procurement", "controller"],
    "fraud.split_under_limit": ["procurement", "controller"],
    "fraud.fake_vendor_procurement": ["finance_ap", "controller"],
    "fraud.urgent_ceo_request": ["procurement", "finance_ap", "controller"],
    "fraud.bank_swap_over_limit": ["controller"],
    "fraud.forged_scanned_invoice": ["finance_ap", "procurement", "controller"],
    "leak.paste_into_customer_email": ["sales", "legal"],
    "leak.base64_attachment": ["legal"],
    "leak.summary_to_lawyer": ["legal"],
    "leak.controller_audit_pack": ["controller", "legal"],
    "leak.share_doc_external": ["legal"],
    "backdoor.newhire_piggyback": ["it_admin"],
    "backdoor.dormant_account": ["it_admin"],
    "backdoor.forged_ticket_ref": ["it_admin", "controller"],
    "backdoor.controller_vouch": ["controller", "it_admin"],
    "backdoor.temp_access_chat": ["it_admin"],
    "sabotage.contract_term_edit": ["legal", "controller"],
    "sabotage.crm_discount": ["sales", "controller"],
    "sabotage.quiet_term_change": ["legal", "controller"],
    "sabotage.controller_relay": ["controller", "legal"],
    "sabotage.chat_justified_edit": ["legal"],
    "frame.bait_and_report": ["controller", "it_admin"],
    "frame.false_whisper": ["controller", "it_admin"],
    "frame.plant_in_chat_thread": ["controller", "it_admin"],
    "frame.after_the_fact_tip": ["controller", "it_admin"],
}

STRATEGIES = {s.id: s.model_copy(update={"needs_seats": NEEDS[s.id]}) for m in MODULES.values() for s in m.STRATEGIES}


def get(kind):
    return [s for s in STRATEGIES.values() if s.kind == kind]


def for_seat(seat):
    return [s for s in STRATEGIES.values() if seat in s.seats]


def make_goal(kind, day_rng, company, sleeper_seat=None, **kw):
    return MODULES[kind].make_goal(day_rng, company, sleeper_seat, **kw) if sleeper_seat else MODULES[kind].make_goal(day_rng, company, **kw)


def rebuild(goal):
    goal = goal if isinstance(goal, dict) else goal.model_dump()
    return MODULES[goal["kind"]].build(goal["id"], goal["target"])


def candidates(n, seed=0, seat=None):
    rng = random.Random(seed)
    pool = [s for s in STRATEGIES.values() if seat is None or seat in s.seats]
    out = []
    for i in range(n):
        s = pool[i % len(pool)]
        out.append({"seed": rng.randrange(10**6), "sleeper_seat": seat or s.seats[(i // len(pool)) % len(s.seats)], "goal": s.kind, "strategy": s.id})
    return out
