"""Seeded helpers: RNGs, IBANs, phone numbers, money, dates, names.

Rules: never use the global `random` module or the wall clock. Every random choice
goes through a local `random.Random` made by `make_rng(...)`, so the same
(family, seed, difficulty) always gives the same world.
"""
from __future__ import annotations

import datetime as _dt
import math
import random
import re
import unicodedata
from decimal import Decimal, InvalidOperation

TODAY = "2026-11-16"  # Monday. The simulated "today" for every family.


def make_rng(*parts) -> random.Random:
    """A local RNG seeded from the parts, e.g. make_rng("ap_run", 7, 2)."""
    return random.Random(":".join(str(p) for p in parts))


# ---------------------------------------------------------------- money

class MoneyError(ValueError):
    pass


def to_cents(value) -> int:
    """Turn 1234.5, "1234.50", Decimal or int euros into integer cents.

    Raises MoneyError for NaN, infinity, bool, non-numbers or more than 2 decimals.
    """
    if isinstance(value, bool) or value is None:
        raise MoneyError("amount must be a number")
    if isinstance(value, float):
        if not math.isfinite(value):
            raise MoneyError("amount must be a finite number")
        text = repr(value)
    elif isinstance(value, (int, Decimal)):
        text = str(value)
    elif isinstance(value, str):
        text = value.strip().replace(" ", "").replace(" ", "")
        if text.upper().startswith("EUR"):
            text = text[3:]
        text = text.strip()
        if len(text) > 40:
            raise MoneyError("amount is not a valid number")
    else:
        raise MoneyError("amount must be a number")
    try:
        d = Decimal(text)
    except (InvalidOperation, ValueError):
        raise MoneyError("amount is not a valid number") from None
    if not d.is_finite():
        raise MoneyError("amount must be a finite number")
    if abs(d) > Decimal("1e12"):
        raise MoneyError("amount is too large")
    cents = d * 100
    if cents != cents.to_integral_value():
        raise MoneyError("amount can have at most 2 decimals")
    return int(cents)


def fmt_cents(cents: int) -> str:
    """12345 -> "123.45" (always 2 decimals, no thousands separator)."""
    sign = "-" if cents < 0 else ""
    cents = abs(int(cents))
    return f"{sign}{cents // 100}.{cents % 100:02d}"


def cents_to_number(cents: int) -> float:
    """For passing amounts to tools that take a JSON number."""
    return int(cents) / 100


# ---------------------------------------------------------------- IBAN

_IBAN_RE = re.compile(r"^[A-Z]{2}[0-9]{2}[A-Z0-9]{8,30}$", re.ASCII)
IBAN_IN_TEXT_RE = re.compile(r"\b[A-Z]{2}\d{2}(?:[ ]?[A-Z0-9]{4}){2,7}(?:[ ]?[A-Z0-9]{1,4})?\b")


def to_ascii(text: str) -> str:
    """Fullwidth and other look-alike forms -> plain ASCII where one exists ('ＦＩ２１' -> 'FI21',
    Arabic-Indic digits -> 0-9). Characters with no ASCII form are left as they are."""
    text = unicodedata.normalize("NFKC", text)
    if text.isascii():
        return text
    out = []
    for ch in text:
        d = None if ch.isascii() else unicodedata.decimal(ch, None)
        out.append(ch if d is None else str(d))
    return "".join(out)


def normalize_iban(text) -> str:
    """'fi21 1234-5600 0007 85' -> 'FI2112345600000785'. Fullwidth or other Unicode digits and
    letters become ASCII, so an IBAN is never stored in a form that only looks the same."""
    if not isinstance(text, str):
        return ""
    return re.sub(r"[\s\-]", "", to_ascii(text)).upper()


def iban_checksum_ok(iban: str) -> bool:
    iban = normalize_iban(iban)
    if not _IBAN_RE.match(iban):
        return False
    moved = iban[4:] + iban[:4]
    digits = "".join(str(int(ch, 36)) for ch in moved)
    return int(digits) % 97 == 1


def make_fi_iban(rng: random.Random) -> str:
    """A Finnish IBAN with a valid checksum: FI + 2 check digits + 14 digits."""
    bban = "".join(rng.choice("0123456789") for _ in range(14))
    # check digits: (bban + "FI00" as digits) mod 97
    num = int(bban + "151800")
    check = 98 - num % 97
    return f"FI{check:02d}{bban}"


def format_iban(iban: str) -> str:
    """FI2112345600000785 -> FI21 1234 5600 0007 85 (how people write it)."""
    iban = normalize_iban(iban)
    return " ".join(iban[i:i + 4] for i in range(0, len(iban), 4))


def find_ibans(text: str) -> list[str]:
    """All IBAN-looking strings in a text, normalized."""
    if not isinstance(text, str):
        return []
    out = []
    for m in IBAN_IN_TEXT_RE.finditer(text):
        cand = normalize_iban(m.group(0))
        if iban_checksum_ok(cand) and cand not in out:
            out.append(cand)
    return out


# ---------------------------------------------------------------- phones

PHONE_IN_TEXT_RE = re.compile(r"\+358[\d ]{6,16}\d")


def normalize_phone(text) -> str:
    """'+358 40 123 4567', '040-1234567', '00358401234567' -> '358401234567'.

    The trunk prefix 0 written after the Finnish country code is dropped, so '+358 (0)9 1234 5678'
    and '+358 09 1234 5678' both give '358912345678'. Fullwidth or other Unicode digits count."""
    if not isinstance(text, str):
        return ""
    raw = re.sub(r"\(\s*0\s*\)", "", to_ascii(text)).strip()  # "(0)" trunk prefix
    digits = re.sub(r"[^0-9]", "", raw)
    if not raw.startswith("+"):
        if digits.startswith("00"):
            digits = digits[2:]
        elif digits.startswith("0"):
            return "358" + digits[1:]
    if digits.startswith("3580"):  # Finnish numbers never have a 0 right after the country code
        digits = "358" + digits[4:]
    return digits


def make_fi_mobile(rng: random.Random) -> str:
    prefix = rng.choice(["40", "41", "44", "45", "46", "50"])
    a = rng.randint(100, 999)
    b = rng.randint(1000, 9999)
    return f"+358 {prefix} {a} {b}"


def make_fi_landline(rng: random.Random) -> str:
    area = rng.choice(["9", "9", "2", "3", "5", "6", "8", "13", "14", "17", "19"])
    a = rng.randint(100, 9999)
    b = rng.randint(100, 9999)
    return f"+358 {area} {a} {b}"


# ---------------------------------------------------------------- dates

def add_days(date_str: str, days: int) -> str:
    d = _dt.date.fromisoformat(date_str) + _dt.timedelta(days=days)
    return d.isoformat()


def date_plus_minutes(date_str: str, start_hhmm: str, minutes: int) -> str:
    h, m = (int(x) for x in start_hhmm.split(":"))
    t = _dt.datetime.fromisoformat(date_str) + _dt.timedelta(hours=h, minutes=m + int(minutes))
    return t.strftime("%Y-%m-%dT%H:%M")


# ---------------------------------------------------------------- names

FIRST_NAMES = [
    "Aino", "Eveliina", "Helmi", "Iida", "Johanna", "Kaisa", "Laura", "Minna", "Noora", "Oona",
    "Riikka", "Sanna", "Tiina", "Veera", "Antti", "Eero", "Heikki", "Janne", "Juha", "Kalle",
    "Lauri", "Markku", "Mikko", "Olli", "Pekka", "Sami", "Teemu", "Ville", "Ilkka", "Petri",
]
LAST_NAMES = [
    "Aaltonen", "Heikkinen", "Hiltunen", "Hämäläinen", "Jokinen", "Kallio", "Karjalainen",
    "Lehtonen", "Lindqvist", "Mattila", "Niemi", "Nurmi", "Ojala", "Peltonen", "Rantanen",
    "Saarinen", "Salminen", "Tuominen", "Turunen", "Väisänen", "Virtanen", "Mäkinen",
]


def person_name(rng: random.Random) -> str:
    return f"{rng.choice(FIRST_NAMES)} {rng.choice(LAST_NAMES)}"


def ascii_slug(text: str) -> str:
    table = str.maketrans({"ä": "a", "ö": "o", "å": "a", "Ä": "a", "Ö": "o", "Å": "a", "é": "e"})
    return re.sub(r"[^a-z0-9]+", "", text.translate(table).lower())
