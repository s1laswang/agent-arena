"""Private world state (hidden truth). Owner: HEAD-ENV / sim-engine.

Nothing in here may be passed to a tool result except the public fields the Env copies out.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import math
import random
import warnings
from pathlib import Path
from dataclasses import dataclass, field
from typing import Any

from .rules import HELDOUT_SEEDS, JUDGE_SEEDS, TierParams

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
    world_seed: int = 0
    mole_strategy: Any = None   # None = DEFAULT_STRATEGY (canary.mole.dsl)

    @property
    def ids(self) -> list[str]:
        return [e.id for e in self.employees]


_SET_SECRET: bytes | None = None


def set_world_secret(secret: bytes | None) -> None:
    """In-process judge-world secret (checked before CANARY_WORLD_SECRET and SALT). None clears it."""
    global _SET_SECRET
    if secret is not None and (not isinstance(secret, (bytes, bytearray)) or len(secret) < 16):
        raise ValueError("world secret must be >= 16 bytes")
    _SET_SECRET = bytes(secret) if secret is not None else None


def _key(seed: int) -> bytes:
    if seed not in JUDGE_SEEDS and seed not in HELDOUT_SEEDS:
        return b"public"
    if _SET_SECRET is not None:
        return _SET_SECRET
    env = os.environ.get("CANARY_WORLD_SECRET")
    if env:
        return env.encode()
    salt = Path(__file__).resolve().parent.parent / "data" / "worlds" / "judge" / "SALT"
    if salt.exists():
        return salt.read_bytes()
    # Contract v0.5: fail closed. Never the public key for judge/held-out seeds; use a per-process
    # random secret (memory only). Reproduction is then statistical; set CANARY_WORLD_SECRET for exact numbers.
    return _process_secret()


_PROC_SECRET: bytes | None = None


def _process_secret() -> bytes:
    global _PROC_SECRET
    if _PROC_SECRET is None:
        _PROC_SECRET = os.urandom(32)
        import logging
        logging.getLogger("canary.world").warning(
            "no CANARY_WORLD_SECRET/SALT: judge worlds use a fresh per-process secret (sha256 %s)",
            hashlib.sha256(_PROC_SECRET).hexdigest()[:16])
    return _PROC_SECRET


def world_seed(tier: str, seed: int) -> int:
    """Contract v0.2: HMAC-derived world seed (secret key for judge/held-out seeds)."""
    return int.from_bytes(hmac.new(_key(seed), f"{tier}:{seed}".encode(), hashlib.sha256).digest()[:8], "big")


def _title(rng: random.Random, dept: str) -> str:
    return rng.choice(TITLE_TPL).format(q=rng.choice(["Q1", "Q2", "Q3", "Q4"]), d=dept, p=rng.choice(PROJECTS))


def generate_world(tier: str, seed: int, p: TierParams) -> World:
    ws = world_seed(tier, seed)
    rng = random.Random(ws)
    n = p.n_employees
    depts = DEPTS[: 5 if tier in ("hard", "hard_forge") else 4]
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
            if rng.random() < p.p_single_dept_recipients:
                ds = [rng.choice(depts)]
            else:
                ds = rng.sample(depts, 2)
            rec = sorted(set(x for d in ds for x in by_dept[d]))
            need = math.ceil(p.doc_recipient_share * len(ids)) - len(rec)
            if need > 0:
                rec = sorted(set(rec) | set(rng.sample([i for i in ids if i not in rec], need)))
            doc = {"doc_id": f"d{day}-{j}", "title": _title(rng, ds[0]), "day": day, "recipients": rec}
            if p.access_constraints:
                doc["min_clearance"] = rng.randint(1, 3)
            docs.append(doc)
        planned[day] = docs
    w = World(tier, seed, p, company, emps, depts, mole, decoy, planned)
    w.world_seed = ws
    return w
