"""Small deterministic helpers: names, IBANs, lookalike domains, canaries."""
from __future__ import annotations

import hashlib
import random

FIRST = ["Aino", "Mikko", "Laura", "Juha", "Sanna", "Teemu", "Elina", "Antti", "Kaisa",
         "Ville", "Noora", "Pekka", "Riikka", "Jari", "Hanna", "Oskari", "Emilia", "Lauri",
         "Maria", "Tuomas", "Iida", "Henrik", "Sofia", "Eero"]
LAST = ["Virtanen", "Korhonen", "Nieminen", "Makinen", "Hamalainen", "Laine", "Heikkinen",
        "Koskinen", "Jarvinen", "Lehtonen", "Saarinen", "Salminen", "Lindqvist", "Berg",
        "Rantanen", "Aalto", "Karjalainen", "Lund", "Holm", "Strom"]

# (name, slug, what they supply)
VENDORS = [
    ("Nordic Steel Supply Oy", "nordicsteel", "steel sheet and bar stock"),
    ("Baltic Freight AB", "balticfreight", "freight and logistics"),
    ("Polar Packaging Oy", "polarpack", "packaging materials"),
    ("Lumen Electrical Oy", "lumenelectric", "electrical components"),
    ("Arctic IT Services Oy", "arcticit", "IT support and licences"),
    ("Saimaa Facility Services Oy", "saimaafm", "cleaning and facility services"),
    ("Kallio Tooling Oy", "kalliotool", "tooling and machining"),
    ("Fjord Chemicals AS", "fjordchem", "industrial lubricants and chemicals"),
    ("Helix Bearings GmbH", "helixbearings", "bearings and seals"),
    ("Tundra Office Supplies Oy", "tundraoffice", "office supplies"),
    ("Aurora Energy Oy", "auroraenergy", "electricity"),
    ("Vaasa Plastics Oy", "vaasaplastics", "injection moulded parts"),
]

TLD_BY_COUNTRY = {"Oy": "fi", "AB": "se", "AS": "no", "GmbH": "de"}


def tld_for(name: str) -> str:
    return TLD_BY_COUNTRY.get(name.split()[-1], "com")


def _mod97(s: str) -> int:
    r = 0
    for ch in s:
        r = (r * 10 + int(ch)) % 97
    return r


def iban(rng: random.Random, cc: str = "FI") -> str:
    """A checksum-valid IBAN-shaped string (fictional bank, fictional account)."""
    bban = "".join(str(rng.randrange(10)) for _ in range(14))
    letters = "".join(str(ord(c) - 55) for c in cc)
    check = 98 - _mod97(bban + letters + "00")
    return f"{cc}{check:02d}{bban}"


def phone(rng: random.Random, cc: str = "+358") -> str:
    return f"{cc} {rng.randrange(40, 50)} {rng.randrange(100, 999)} {rng.randrange(1000, 9999)}"


def lookalike(slug: str, rng: random.Random) -> str:
    """A typosquatted variant of a domain slug, the way real BEC crews do it."""
    tricks = []
    if "l" in slug:
        tricks.append(lambda s: s.replace("l", "1", 1))
    if "m" in slug:
        tricks.append(lambda s: s.replace("m", "rn", 1))
    if "o" in slug:
        tricks.append(lambda s: s.replace("o", "0", 1))
    if "i" in slug:
        tricks.append(lambda s: s.replace("i", "l", 1))
    tricks.append(lambda s: s + "-invoices")
    tricks.append(lambda s: s + "-group")
    out = rng.choice(tricks)(slug)
    return out if out != slug else slug + "-pay"


def canary(seed: int, label: str) -> str:
    h = hashlib.sha256(f"payday:{seed}:{label}".encode()).hexdigest()[:10].upper()
    return f"KC-{h}"


def money(x: float) -> str:
    return f"EUR {x:,.2f}"
