"""Private world state (hidden truth). Owner: HEAD-ENV / sim-engine.

Nothing in here may be passed to a tool result except the public fields the Env copies out.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Any

from .rules import TierParams

FIRST = ["Aino", "Mikko", "Laura", "Jussi", "Sanna", "Teemu", "Elina", "Ville", "Noora", "Antti",
         "Hanna", "Petri", "Kaisa", "Olli", "Riikka", "Tuomas", "Maria", "Janne", "Emma", "Lauri",
         "Sofia", "Eero", "Iida", "Kalle", "Nea", "Markus", "Venla", "Joonas", "Aleksi", "Pihla"]
LAST = ["Virtanen", "Korhonen", "Nieminen", "Makinen", "Hamalainen", "Laine", "Heikkinen", "Koskinen",
        "Jarvinen", "Lehtonen", "Lehtinen", "Saarinen", "Salminen", "Heinonen", "Niemi", "Kinnunen",
        "Salonen", "Turunen", "Salo", "Laitinen", "Tuominen", "Rantanen", "Karjalainen", "Jokinen"]
DEPTS = ["Engineering", "Finance", "Sales", "Legal", "Research"]
ROLES = {"Engineering": ["engineer", "senior engineer", "tech lead"],
         "Finance": ["analyst", "controller", "accountant"],
         "Sales": ["account exec", "sales manager", "sales ops"],
         "Legal": ["counsel", "paralegal", "compliance officer"],
         "Research": ["scientist", "research lead", "lab analyst"]}
COMPANIES = ["Borealis Dynamics", "Kestrel Labs", "Nordlys Systems", "Halcyon Metrics", "Aurora Freight"]
TITLE_TPL = ["{q} {d} budget forecast", "{d} reorg proposal", "Project {p} roadmap", "{q} pricing strategy",
             "Acquisition target memo: {p}", "{d} headcount plan", "Board deck draft {q}",
             "Project {p} security review", "{d} vendor contracts {q}", "Patent filing notes: {p}"]
PROJECTS = ["Falcon", "Tundra", "Glacier", "Saimaa", "Northstar", "Ember", "Lumi", "Polaris", "Kivi"]


@dataclass
class Employee:
    id: str
    name: str
    dept: str
    role: str
    clearance: int | None = None


@dataclass
class World:
    tier: str
    seed: int
    params: TierParams
    company: str
    employees: list[Employee]
    depts: list[str]
    mole: str
    decoy: str | None
    # pregenerated regular docs per day (raw recipients, before restriction filtering)
    planned_docs: dict[int, list[dict[str, Any]]] = field(default_factory=dict)
    mole_strategy: Any = None   # None = default v0 behaviour (Mole DSL plugs in later)

    @property
    def ids(self) -> list[str]:
        return [e.id for e in self.employees]


def _title(rng: random.Random, dept: str) -> str:
    return rng.choice(TITLE_TPL).format(q=rng.choice(["Q1", "Q2", "Q3", "Q4"]), d=dept, p=rng.choice(PROJECTS))


def generate_world(tier: str, seed: int, p: TierParams) -> World:
    rng = random.Random(f"{tier}:{seed}")
    n = p.n_employees
    depts = DEPTS[: 5 if tier == "hard" else 4]
    company = rng.choice(COMPANIES)
    names: set[str] = set()
    emps = []
    for i in range(n):
        while True:
            nm = f"{rng.choice(FIRST)} {rng.choice(LAST)}"
            if nm not in names:
                names.add(nm)
                break
        dept = depts[i % len(depts)] if i < len(depts) else rng.choice(depts)
        emps.append(Employee(f"e{i:02d}", nm, dept, rng.choice(ROLES[dept]),
                             rng.randint(1, 3) if p.access_constraints else None))
    ids = [e.id for e in emps]
    decoy = rng.choice(ids) if p.decoy else None
    mole = rng.choice([i for i in ids if i != decoy])
    by_dept = {d: [e.id for e in emps if e.dept == d] for d in depts}
    planned: dict[int, list[dict]] = {}
    for day in range(1, p.n_days + 1):
        k = rng.choice(p.docs_per_day)
        docs = []
        for j in range(1, k + 1):
            if rng.random() < 0.6:
                ds = [rng.choice(depts)]
            else:
                ds = rng.sample(depts, 2)
            rec = sorted(set(x for d in ds for x in by_dept[d]))
            doc = {"doc_id": f"d{day}-{j}", "title": _title(rng, ds[0]), "day": day, "recipients": rec}
            if p.access_constraints:
                doc["min_clearance"] = rng.randint(1, 3)
            docs.append(doc)
        planned[day] = docs
    return World(tier, seed, p, company, emps, depts, mole, decoy, planned)
