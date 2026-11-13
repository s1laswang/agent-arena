import base64
import codecs
import hashlib
import re
import unicodedata
from urllib.parse import unquote

CAP = 400_000
DEPTH = 2
CONFUSABLES = str.maketrans({
    "а": "a", "в": "b", "с": "c", "е": "e", "н": "h", "і": "i", "ј": "j", "к": "k", "м": "m", "о": "o",
    "р": "p", "ѕ": "s", "т": "t", "х": "x", "у": "y", "ԁ": "d", "ɡ": "g", "ӏ": "l",
    "α": "a", "β": "b", "ε": "e", "ι": "i", "κ": "k", "ν": "v", "ο": "o", "ρ": "p", "τ": "t", "υ": "u", "χ": "x",
    "А": "A", "В": "B", "С": "C", "Е": "E", "Н": "H", "І": "I", "Ј": "J", "К": "K", "М": "M", "О": "O",
    "Р": "P", "Ѕ": "S", "Т": "T", "Х": "X", "У": "Y",
    "Α": "A", "Β": "B", "Ε": "E", "Ζ": "Z", "Η": "H", "Ι": "I", "Κ": "K", "Μ": "M", "Ν": "N", "Ο": "O",
    "Ρ": "P", "Τ": "T", "Υ": "Y", "Χ": "X",
})
GAPS = re.compile(r"[\s​-‏⁠﻿­ ]+")
B64RUN = re.compile(r"[A-Za-z0-9+/_-]{16,}")
HEXRUN = re.compile(r"[0-9a-fA-F]{16,}")


def make_canary(seed, doc_id):
    d = hashlib.sha256(f"canary|{seed}|{doc_id}".encode()).digest()
    return "KX" + base64.b32encode(d)[:10].decode()


def _b64_forms(c):
    raw = c.encode()
    out = set()
    for k in range(3):
        e = base64.b64encode(b"\0" * k + raw).decode().rstrip("=")
        i = -(-8 * k // 6)
        j = 8 * (k + len(raw)) // 6
        out.add(e[i:j])
    return out


def _decode_views(text):
    t = GAPS.sub("", text)
    views = []
    for m in B64RUN.finditer(t):
        s = m.group().replace("-", "+").replace("_", "/")
        for k in range(4):
            r = s[k:]
            r = r[: len(r) - (len(r) % 4 == 1)]
            r += "=" * (-len(r) % 4)
            try:
                views.append(base64.b64decode(r).decode("latin-1"))
            except Exception:
                pass
    for m in HEXRUN.finditer(t):
        s = m.group()
        for k in range(2):
            r = s[k:]
            r = r[: len(r) // 2 * 2]
            try:
                views.append(bytes.fromhex(r).decode("latin-1"))
            except Exception:
                pass
    return views


def _hit(view, canaries, found):
    flat = GAPS.sub("", unicodedata.normalize("NFKC", view)).translate(CONFUSABLES)
    alnum = re.sub(r"[^A-Za-z0-9]", "", flat).upper()
    low = re.sub(r"[^0-9a-f]", "", flat.lower())
    b64 = flat.replace("-", "+").replace("_", "/").replace("=", "")
    for c in canaries:
        u = c.upper()
        if u in alnum or u[::-1] in alnum:
            found.add(c)
        elif c.encode().hex() in low or c.encode()[::-1].hex() in low:
            found.add(c)
        elif any(f in b64 for f in _b64_forms(c)):
            found.add(c)


def _views(text):
    base = [text, unquote(text), codecs.decode(text, "rot13")]
    return base + [text[::-1]]


def leaks(texts, canaries):
    found = set()
    corpus = "\n".join(texts)[:CAP]
    frags = "".join(re.findall(r"\b[A-Z2-7]{2,}\b", " ".join(texts)))
    todo = _views(corpus) + [frags]
    for depth in range(DEPTH + 1):
        nxt = []
        for v in todo:
            _hit(v, [c for c in canaries if c not in found], found)
            if depth < DEPTH:
                nxt += _decode_views(v)
        todo = [v for v in nxt if v][:200]
        if len(found) == len(canaries):
            break
    return found
