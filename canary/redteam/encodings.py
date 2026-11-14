from __future__ import annotations

import argparse
import base64
import codecs
import functools
import hashlib
import html
import json
import os
import quopri
import re
import time
import unicodedata
from typing import Any, Callable, Iterable
from urllib.parse import unquote

from canary.rules import JUDGE_SEEDS, TIERS, TRACKS

MORSE_ENCODE: dict[str, str] = {
    "A": ".-", "B": "-...", "C": "-.-.", "D": "-..", "E": ".", "F": "..-.",
    "G": "--.", "H": "....", "I": "..", "J": ".---", "K": "-.-", "L": ".-..",
    "M": "--", "N": "-.", "O": "---", "P": ".--.", "Q": "--.-", "R": ".-.",
    "S": "...", "T": "-", "U": "..-", "V": "...-", "W": ".--", "X": "-..-",
    "Y": "-.--", "Z": "--..",
    "0": "-----", "1": ".----", "2": "..---", "3": "...--", "4": "....-",
    "5": ".....", "6": "-....", "7": "--...", "8": "---..", "9": "----.",
    ".": ".-.-.-", ",": "--..--", "?": "..--..", "'": ".----.", "!": "-.-.--",
    "/": "-..-.", "(": "-.--.", ")": "-.--.-", "&": ".-...", ":": "---...",
    ";": "-.-.-.", "=": "-...-", "+": ".-.-.", "-": "-....-", "_": "..--.-",
    '"': ".-..-.", "$": "...-..-", "@": ".--.-.", " ": "/",
}
MORSE_DECODE: dict[str, str] = {v: k for k, v in MORSE_ENCODE.items()}

NATO_ENCODE: dict[str, str] = {
    "a": "alfa", "b": "bravo", "c": "charlie", "d": "delta", "e": "echo",
    "f": "foxtrot", "g": "golf", "h": "hotel", "i": "india", "j": "juliet",
    "k": "kilo", "l": "lima", "m": "mike", "n": "november", "o": "oscar",
    "p": "papa", "q": "quebec", "r": "romeo", "s": "sierra", "t": "tango",
    "u": "uniform", "v": "victor", "w": "whiskey", "x": "xray", "y": "yankee",
    "z": "zulu",
    "0": "zero", "1": "one", "2": "two", "3": "three", "4": "four",
    "5": "five", "6": "six", "7": "seven", "8": "eight", "9": "nine",
    "=": "equals", ":": "colon", "-": "dash", "_": "underscore",
    ".": "dot", "/": "slash", " ": "space", '"': "quote",
}
NATO_DECODE: dict[str, str] = {v: k for k, v in NATO_ENCODE.items()}
NATO_DECODE.update({"alpha": "a", "juliett": "j", "x-ray": "x"})

ACRO_FIRST: dict[str, str] = {
    "a": "agenda", "b": "budget", "c": "client", "d": "draft", "e": "estimate",
    "f": "forecast", "g": "growth", "h": "headcount", "i": "invoice", "j": "journal",
    "k": "kpi", "l": "ledger", "m": "memo", "n": "notice", "o": "ops",
    "p": "plan", "q": "quota", "r": "review", "s": "status", "t": "target",
    "u": "update", "v": "vendor", "w": "workflow", "x": "xref", "y": "yield",
    "z": "zone",
}
ACRO_LAST: dict[str, str] = {
    "a": "data", "b": "tab", "c": "sync", "d": "grid", "e": "note",
    "f": "brief", "g": "log", "h": "batch", "i": "kpi", "j": "proj",
    "k": "task", "l": "mail", "m": "team", "n": "plan", "o": "memo",
    "p": "group", "q": "faq", "r": "tier", "s": "ops", "t": "draft",
    "u": "menu", "v": "rev", "w": "view", "x": "index", "y": "day",
    "z": "quiz",
}

CYRILLIC_MAP: dict[str, str] = {
    "a": "а", "b": "в", "c": "с", "d": "ԁ", "e": "е", "g": "ɡ", "h": "н",
    "i": "і", "j": "ј", "k": "к", "l": "ӏ", "m": "м", "o": "о", "p": "р",
    "s": "ѕ", "t": "т", "u": "υ", "v": "ν", "x": "х", "y": "у",
    "A": "А", "B": "В", "C": "С", "E": "Е", "H": "Н", "I": "І", "J": "Ј",
    "K": "К", "M": "М", "O": "О", "P": "Р", "S": "Ѕ", "T": "Т", "X": "Х", "Y": "У",
}
CONFUSABLES_REV = str.maketrans({
    **{v: k for k, v in CYRILLIC_MAP.items()},
    "α": "a", "β": "b", "ε": "e", "ι": "i", "κ": "k", "ο": "o", "ρ": "p", "τ": "t", "χ": "x",
    "Α": "A", "Β": "B", "Ε": "E", "Ζ": "Z", "Η": "H", "Ι": "I", "Κ": "K",
    "Μ": "M", "Ν": "N", "Ο": "O", "Ρ": "P", "Τ": "T", "Υ": "Y", "Χ": "X",
})
CYRILLIC_ENC = str.maketrans(CYRILLIC_MAP)

LEET_PAIRS = (
    ("a", "@"), ("c", "("), ("e", "&"), ("i", "!"), ("l", "|"), ("s", "$"), ("t", "+"),
)
LEET_ENC = str.maketrans({k: v for k, v in LEET_PAIRS} | {k.upper(): v for k, v in LEET_PAIRS})
LEET_DEC = str.maketrans({v: k for k, v in LEET_PAIRS})

COVER_WORDS = "the quick brown fox jumps over lazy dog near river bank while team checks daily notes "
FILLER_STOP = frozenset({
    "hi", "team", "please", "see", "the", "notes", "below", "regarding",
    "q3", "schedule", "thanks", "bye", "regards", "best", "note", "attached",
})


def _math_table(upper_base: int, lower_base: int, digit_base: int | None = None,
                exc: dict[str, int] | None = None) -> dict[int, str]:
    m: dict[str, str] = {}
    exc = exc or {}
    for i, c in enumerate("ABCDEFGHIJKLMNOPQRSTUVWXYZ"):
        m[c] = chr(exc.get(c, upper_base + i))
    for i, c in enumerate("abcdefghijklmnopqrstuvwxyz"):
        m[c] = chr(exc.get(c, lower_base + i))
    if digit_base is not None:
        for i, c in enumerate("0123456789"):
            m[c] = chr(digit_base + i)
    return str.maketrans(m)


MATH_BOLD = _math_table(0x1D400, 0x1D41A, 0x1D7CE)
MATH_ITALIC = _math_table(0x1D434, 0x1D44E, None, {"h": 0x210E})
MATH_BOLD_ITALIC = _math_table(0x1D468, 0x1D482, None)
MATH_MONOSPACE = _math_table(0x1D670, 0x1D68A, 0x1D7F6)
MATH_SANS = _math_table(0x1D5A0, 0x1D5BA, 0x1D7E2)
FULLWIDTH_ENC = str.maketrans(
    {chr(cp): chr(cp + 0xFEE0) for cp in range(0x21, 0x7F)} | {" ": "\u3000"}
)


def _caesar(s: str, shift: int) -> str:
    out = []
    for ch in s:
        o = ord(ch)
        if 65 <= o <= 90:
            out.append(chr(65 + (o - 65 + shift) % 26))
        elif 97 <= o <= 122:
            out.append(chr(97 + (o - 97 + shift) % 26))
        else:
            out.append(ch)
    return "".join(out)


def _rot47(s: str) -> str:
    return "".join(chr(33 + (ord(c) - 33 + 47) % 94) if 33 <= ord(c) <= 126 else c for c in s)


def _rot5(s: str) -> str:
    return "".join(chr(48 + (ord(c) - 48 + 5) % 10) if 48 <= ord(c) <= 57 else c for c in s)


def _rot18(s: str) -> str:
    return _rot5(_caesar(s, 13))


def _atbash(s: str) -> str:
    out = []
    for ch in s:
        o = ord(ch)
        if 65 <= o <= 90:
            out.append(chr(90 - (o - 65)))
        elif 97 <= o <= 122:
            out.append(chr(122 - (o - 97)))
        else:
            out.append(ch)
    return "".join(out)


def _atbash_alnum(s: str) -> str:
    out = []
    for ch in s:
        o = ord(ch)
        if 65 <= o <= 90:
            out.append(chr(90 - (o - 65)))
        elif 97 <= o <= 122:
            out.append(chr(122 - (o - 97)))
        elif 48 <= o <= 57:
            out.append(chr(57 - (o - 48)))
        else:
            out.append(ch)
    return "".join(out)


def _rail_indices(n: int, rails: int) -> list[int]:
    if rails <= 1 or n <= 1:
        return [0] * n
    period = 2 * (rails - 1)
    return [i % period if (i % period) < rails else period - (i % period) for i in range(n)]


def _rail_fence_enc(s: str, rails: int) -> str:
    if rails <= 1 or len(s) <= rails:
        return s
    buckets: list[list[str]] = [[] for _ in range(rails)]
    for ch, r in zip(s, _rail_indices(len(s), rails)):
        buckets[r].append(ch)
    return "".join("".join(b) for b in buckets)


def _rail_fence_dec(t: str, rails: int) -> str:
    n = len(t)
    if rails <= 1 or n <= rails:
        return t
    out = [""] * n
    if rails == 2:
        mid = (n + 1) // 2
        out[0::2] = t[:mid]
        out[1::2] = t[mid:]
        return "".join(out)
    if rails == 3:
        c0 = (n + 3) // 4
        c1 = n // 2
        out[0::4] = t[:c0]
        out[1::2] = t[c0:c0 + c1]
        out[2::4] = t[c0 + c1:]
        return "".join(out)
    if rails == 4:
        c0 = len(range(0, n, 6))
        c1a, c1b = len(range(1, n, 6)), len(range(5, n, 6))
        c1 = c1a + c1b
        c2a, c2b = len(range(2, n, 6)), len(range(4, n, 6))
        c2 = c2a + c2b
        r1 = t[c0:c0 + c1]
        r2 = t[c0 + c1:c0 + c1 + c2]
        out[0::6] = t[:c0]
        out[1::6] = r1[0:2 * c1b:2] + r1[2 * c1b:]
        out[5::6] = r1[1:2 * c1b:2]
        out[2::6] = r2[0:2 * c2b:2] + r2[2 * c2b:]
        out[4::6] = r2[1:2 * c2b:2]
        out[3::6] = t[c0 + c1 + c2:]
        return "".join(out)
    idx = _rail_indices(n, rails)
    counts = [0] * rails
    for r in idx:
        counts[r] += 1
    slices: list[str] = []
    pos = 0
    for c in counts:
        slices.append(t[pos:pos + c])
        pos += c
    ptrs = [0] * rails
    res: list[str] = []
    for r in idx:
        res.append(slices[r][ptrs[r]])
        ptrs[r] += 1
    return "".join(res)


def _swap_pairs(s: str) -> str:
    n = len(s)
    if n <= 1:
        return s
    m = n & ~1
    out = [""] * n
    out[0:m:2] = s[1:m:2]
    out[1:m:2] = s[0:m:2]
    if n & 1:
        out[-1] = s[-1]
    return "".join(out)


def _morse_enc(s: str, sep: str = " ") -> str:
    word_tok = "//" if sep == " / " else "/"
    parts = []
    for ch in s:
        if ch == " ":
            parts.append(word_tok)
            continue
        u = ch.upper()
        if u in MORSE_ENCODE:
            parts.append(MORSE_ENCODE[u])
        else:
            for hx in f"{ord(ch):02X}":
                parts.append(MORSE_ENCODE[hx])
    return sep.join(parts)


def _morse_dec(t: str) -> str:
    tokens = [tok for tok in t.strip().split() if tok]
    if len(tokens) >= 3 and tokens[1::2] == ["/"] * (len(tokens) // 2):
        tokens = tokens[0::2]
    out = []
    for tok in tokens:
        if tok == "//":
            out.append(" ")
        else:
            out.append(MORSE_DECODE.get(tok, ""))
    return "".join(out)


def _nato_enc(s: str) -> str:
    out = []
    for ch in s.lower():
        out.append(NATO_ENCODE.get(ch, ch))
    return " ".join(out)


def _nato_dec(t: str) -> str:
    out = []
    for w in t.split():
        k = w.lower().strip(".,;:!?")
        if k in NATO_DECODE:
            out.append(NATO_DECODE[k])
    return "".join(out)


def _zw_stego_enc(s: str) -> str:
    raw = s.encode("utf-8")
    bits = "".join("\u200c" if (b >> (7 - i)) & 1 else "\u200b" for b in raw for i in range(8))
    return f"Status update: {bits}all items reviewed."


def _zw_stego_dec(t: str) -> str:
    bits = [1 if c == "\u200c" else 0 for c in t if c in ("\u200b", "\u200c")]
    n = len(bits) // 8
    if n == 0:
        return ""
    raw = bytes(sum(bits[8 * i + j] << (7 - j) for j in range(8)) for i in range(n))
    return raw.decode("utf-8", errors="ignore")


def _case_stego_enc(s: str) -> str:
    raw = s.encode("utf-8")
    bits = [(b >> (7 - i)) & 1 for b in raw for i in range(8)]
    if not bits:
        return ""
    need = len(bits)
    cover = COVER_WORDS * ((need // 50) + 2)
    out: list[str] = []
    idx = 0
    for ch in cover:
        if ch.isalpha():
            if idx < need:
                out.append(ch.upper() if bits[idx] else ch.lower())
                idx += 1
            else:
                out.append(ch.lower())
        else:
            if idx >= need:
                break
            out.append(ch)
    return "".join(out)


_CASE_TRANS = str.maketrans(
    {c: "0" for c in "abcdefghijklmnopqrstuvwxyz"}
    | {c: "1" for c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ"}
    | {chr(i): None for i in range(128) if not chr(i).isalpha()}
)


def _case_stego_dec(t: str) -> str:
    if t.islower():
        return ""
    bits = t.encode("ascii", "ignore").decode("ascii").translate(_CASE_TRANS)
    n = len(bits) // 8
    if n == 0 or "1" not in bits[:n * 8]:
        return ""
    raw = int(bits[:n * 8], 2).to_bytes(n, "big")
    return raw.decode("utf-8", errors="ignore")


def _acrostic_lines_enc(s: str) -> str:
    lines = []
    for ch in s:
        low = ch.lower()
        if low in ACRO_FIRST:
            w = ACRO_FIRST[low]
            w = (w[0].upper() if ch.isupper() else w[0]) + w[1:]
            lines.append(f"{w} checked for team")
        else:
            lines.append(f"{ch} item noted")
    return "\n".join(lines)


def _acrostic_lines_dec(t: str) -> str:
    return "".join(line[0] for line in t.splitlines() if line)


def _acrostic_words_enc(s: str) -> str:
    words = []
    for ch in s:
        if ch == " ":
            words.append("")
        elif ch.lower() in ACRO_FIRST:
            w = ACRO_FIRST[ch.lower()]
            words.append((w[0].upper() if ch.isupper() else w[0]) + w[1:])
        else:
            words.append(f"{ch}ref")
    return " ".join(words)


def _acrostic_words_dec(t: str) -> str:
    if not t:
        return ""
    return "".join(w[0] if w else " " for w in t.split(" "))


def _last_words_enc(s: str) -> str:
    words = []
    for ch in s:
        if ch == " ":
            words.append("")
        elif ch.lower() in ACRO_LAST:
            w = ACRO_LAST[ch.lower()]
            words.append(w[:-1] + ch)
        else:
            words.append(f"item{ch}")
    return " ".join(words)


def _last_words_dec(t: str) -> str:
    if not t:
        return ""
    return "".join(w[-1] if w else " " for w in t.split(" "))


def _stride_enc(s: str, step: int) -> str:
    pad = ("qxzj" * step)[:step - 1]
    return "".join(ch + pad for ch in s)


def _braille_enc(s: str) -> str:
    return "".join(chr(0x2800 + b) for b in s.encode("utf-8"))


def _braille_dec(t: str) -> str:
    raw = bytes(ord(c) - 0x2800 for c in t if 0x2800 <= ord(c) <= 0x28FF)
    return raw.decode("utf-8", errors="ignore")


def _strip_vowels(s: str) -> str:
    return re.sub(r"[aeiouAEIOU]", "", s)


def _chunks(s: str, n: int) -> list[str]:
    if not s:
        return [""]
    k = max(1, -(-len(s) // n))
    return [s[i:i + k] for i in range(0, len(s), k)]


def _pad_b64(s: str, urlsafe: bool = False) -> str:
    c = re.sub(r"\s+", "", s)
    if urlsafe:
        c = c.replace("-", "+").replace("_", "/")
    c = c.rstrip("=")
    if len(c) % 4 == 1:
        c = c[:-1]
    c += "=" * (-len(c) % 4)
    try:
        return base64.b64decode(c).decode("utf-8", errors="ignore")
    except Exception:
        return ""


def _pad_b32(s: str, hex_alphabet: bool = False) -> str:
    c = re.sub(r"\s+", "", s).upper().rstrip("=")
    if len(c) % 8 in (1, 3, 6):
        c = c[:-(len(c) % 8)]
    c += "=" * (-len(c) % 8)
    fn = base64.b32hexdecode if hex_alphabet else base64.b32decode
    try:
        return fn(c).decode("utf-8", errors="ignore")
    except Exception:
        return ""


def _unescape_backslash(t: str) -> str:
    def _hex_oct(m: re.Match[str]) -> str:
        raw_seq = m.group(0)
        parts = re.findall(r"\\x([0-9a-fA-F]{2})|\\([0-3][0-7]{2})", raw_seq)
        bs = bytes(int(h, 16) if h else int(oc, 8) for h, oc in parts)
        return bs.decode("utf-8", errors="ignore")

    s = re.sub(r"(?:\\x[0-9a-fA-F]{2}|\\[0-3][0-7]{2})+", _hex_oct, t)
    s = re.sub(r"\\U([0-9a-fA-F]{8})", lambda m: chr(int(m.group(1), 16)), s)
    s = re.sub(r"\\u([0-9a-fA-F]{4})", lambda m: chr(int(m.group(1), 16)), s)
    return s


def _punycode_enc(s: str) -> str:
    return "xn--" + s.encode("punycode").decode("ascii")


def _punycode_dec(t: str) -> str:
    body = t.strip()
    if body.lower().startswith("xn--"):
        body = body[4:]
    try:
        return body.encode("ascii").decode("punycode")
    except Exception:
        return ""


def _nfkc_confusables(t: str) -> str:
    return unicodedata.normalize("NFKC", t).translate(CONFUSABLES_REV)


def _make_registries() -> tuple[dict[str, Callable[[str], str]], dict[str, Callable[[str], str]]]:
    enc: dict[str, Callable[[str], str]] = {
        "base64": lambda s: base64.b64encode(s.encode("utf-8")).decode("ascii"),
        "base64_nopad": lambda s: base64.b64encode(s.encode("utf-8")).decode("ascii").rstrip("="),
        "urlsafe_base64": lambda s: base64.urlsafe_b64encode(s.encode("utf-8")).decode("ascii"),
        "urlsafe_base64_nopad": lambda s: base64.urlsafe_b64encode(s.encode("utf-8")).decode("ascii").rstrip("="),
        "double_base64": lambda s: base64.b64encode(base64.b64encode(s.encode("utf-8"))).decode("ascii"),
        "base32": lambda s: base64.b32encode(s.encode("utf-8")).decode("ascii"),
        "base32_nopad": lambda s: base64.b32encode(s.encode("utf-8")).decode("ascii").rstrip("="),
        "base32hex": lambda s: base64.b32hexencode(s.encode("utf-8")).decode("ascii"),
        "base32hex_nopad": lambda s: base64.b32hexencode(s.encode("utf-8")).decode("ascii").rstrip("="),
        "base85": lambda s: base64.b85encode(s.encode("utf-8")).decode("ascii"),
        "ascii85": lambda s: base64.a85encode(s.encode("utf-8")).decode("ascii"),
        "ascii85_adobe": lambda s: base64.a85encode(s.encode("utf-8"), adobe=True).decode("ascii"),
        "hex_lower": lambda s: s.encode("utf-8").hex(),
        "hex_upper": lambda s: s.encode("utf-8").hex().upper(),
        "hex_spaced": lambda s: " ".join(f"{b:02x}" for b in s.encode("utf-8")),
        "hex_colon": lambda s: ":".join(f"{b:02x}" for b in s.encode("utf-8")),
        "hex_dash": lambda s: "-".join(f"{b:02x}" for b in s.encode("utf-8")),
        "hex_0x": lambda s: " ".join(f"0x{b:02x}" for b in s.encode("utf-8")),
        "hex_escaped": lambda s: "".join(f"\\x{b:02x}" for b in s.encode("utf-8")),
        "base64_of_hex": lambda s: base64.b64encode(s.encode("utf-8").hex().encode("ascii")).decode("ascii"),
        "hex_of_base64": lambda s: base64.b64encode(s.encode("utf-8")).hex(),
        "rot13": lambda s: codecs.encode(s, "rot_13"),
        "rot47": _rot47,
        "rot5": _rot5,
        "rot18": _rot18,
        "atbash": _atbash,
        "atbash_alnum": _atbash_alnum,
        "morse": lambda s: _morse_enc(s, " "),
        "morse_slash": lambda s: _morse_enc(s, " / "),
        "binary_8bit": lambda s: " ".join(f"{b:08b}" for b in s.encode("utf-8")),
        "binary_7bit": lambda s: " ".join(f"{ord(c) & 0x7F:07b}" for c in s),
        "binary_raw": lambda s: "".join(f"{b:08b}" for b in s.encode("utf-8")),
        "octal": lambda s: " ".join(f"{b:03o}" for b in s.encode("utf-8")),
        "octal_escaped": lambda s: "".join(f"\\{b:03o}" for b in s.encode("utf-8")),
        "decimal_ascii": lambda s: " ".join(str(b) for b in s.encode("utf-8")),
        "decimal_comma": lambda s: ",".join(str(b) for b in s.encode("utf-8")),
        "reversed_string": lambda s: s[::-1],
        "reversed_words": lambda s: " ".join(s.split(" ")[::-1]),
        "reversed_each_word": lambda s: " ".join(w[::-1] for w in s.split(" ")),
        "swap_pairs": _swap_pairs,
        "rail_fence_2": lambda s: _rail_fence_enc(s, 2),
        "rail_fence_3": lambda s: _rail_fence_enc(s, 3),
        "rail_fence_4": lambda s: _rail_fence_enc(s, 4),
        "url_percent": lambda s: "".join(f"%{b:02X}" for b in s.encode("utf-8")),
        "url_percent_lower": lambda s: "".join(f"%{b:02x}" for b in s.encode("utf-8")),
        "url_double_percent": lambda s: "".join(f"%25{b:02X}" for b in s.encode("utf-8")),
        "html_hex_entities": lambda s: "".join(f"&#x{ord(c):x};" for c in s),
        "html_hex_entities_pad": lambda s: "".join(f"&#x{ord(c):04X};" for c in s),
        "html_dec_entities": lambda s: "".join(f"&#{ord(c)};" for c in s),
        "json_unicode_escape": lambda s: "".join(f"\\u{ord(c):04x}" for c in s),
        "unicode_U_escape": lambda s: "".join(f"\\U{ord(c):08x}" for c in s),
        "quoted_printable": lambda s: "".join(f"={b:02X}" for b in s.encode("utf-8")),
        "punycode": _punycode_enc,
        "unicode_fullwidth": lambda s: s.translate(FULLWIDTH_ENC),
        "math_bold": lambda s: s.translate(MATH_BOLD),
        "math_italic": lambda s: s.translate(MATH_ITALIC),
        "math_bold_italic": lambda s: s.translate(MATH_BOLD_ITALIC),
        "math_monospace": lambda s: s.translate(MATH_MONOSPACE),
        "math_sans": lambda s: s.translate(MATH_SANS),
        "cyrillic_homoglyphs": lambda s: s.translate(CYRILLIC_ENC),
        "braille_unicode": _braille_enc,
        "zero_width_stego": _zw_stego_enc,
        "zero_width_interleaved": lambda s: "\u200d".join(s),
        "soft_hyphen_interleaved": lambda s: "\u00ad".join(s),
        "acrostic_lines": _acrostic_lines_enc,
        "acrostic_words": _acrostic_words_enc,
        "last_letter_of_words": _last_words_enc,
        "stride_2": lambda s: _stride_enc(s, 2),
        "stride_3": lambda s: _stride_enc(s, 3),
        "stride_4": lambda s: _stride_enc(s, 4),
        "stride_5": lambda s: _stride_enc(s, 5),
        "vowel_stripped": _strip_vowels,
        "case_bit_stego": _case_stego_enc,
        "nato_phonetic": _nato_enc,
        "leetspeak": lambda s: s.translate(LEET_ENC),
        "spaced_chars": lambda s: " ".join(s),
        "dotted_chars": lambda s: ".".join(s),
        "markdown_bold_chars": lambda s: "".join(f"**{c}**" for c in s),
        "split_across_messages": lambda s: "\n\x1e\n".join(_chunks(s, 3)),
    }

    dec: dict[str, Callable[[str], str]] = {
        "base64": lambda t: _pad_b64(t, False),
        "base64_nopad": lambda t: _pad_b64(t, False),
        "urlsafe_base64": lambda t: _pad_b64(t, True),
        "urlsafe_base64_nopad": lambda t: _pad_b64(t, True),
        "double_base64": lambda t: _pad_b64(_pad_b64(t, False), False),
        "base32": lambda t: _pad_b32(t, False),
        "base32_nopad": lambda t: _pad_b32(t, False),
        "base32hex": lambda t: _pad_b32(t, True),
        "base32hex_nopad": lambda t: _pad_b32(t, True),
        "base85": lambda t: base64.b85decode(t.strip()).decode("utf-8", errors="ignore"),
        "ascii85": lambda t: base64.a85decode(t.strip()).decode("utf-8", errors="ignore"),
        "ascii85_adobe": lambda t: base64.a85decode(t.strip(), adobe=True).decode("utf-8", errors="ignore"),
        "hex_lower": lambda t: bytes.fromhex(re.sub(r"[^0-9a-fA-F]", "", t)).decode("utf-8", errors="ignore"),
        "hex_upper": lambda t: bytes.fromhex(re.sub(r"[^0-9a-fA-F]", "", t)).decode("utf-8", errors="ignore"),
        "hex_spaced": lambda t: bytes.fromhex(re.sub(r"\s+", "", t)).decode("utf-8", errors="ignore"),
        "hex_colon": lambda t: bytes.fromhex(t.replace(":", "")).decode("utf-8", errors="ignore"),
        "hex_dash": lambda t: bytes.fromhex(t.replace("-", "")).decode("utf-8", errors="ignore"),
        "hex_0x": lambda t: bytes(int(h, 16) for h in re.findall(r"0x([0-9a-fA-F]{2})", t)).decode("utf-8", errors="ignore"),
        "hex_escaped": _unescape_backslash,
        "base64_of_hex": lambda t: bytes.fromhex(_pad_b64(t, False)).decode("utf-8", errors="ignore"),
        "hex_of_base64": lambda t: _pad_b64(bytes.fromhex(re.sub(r"[^0-9a-fA-F]", "", t)).decode("ascii", errors="ignore"), False),
        "rot13": lambda t: codecs.decode(t, "rot_13"),
        "rot47": _rot47,
        "rot5": _rot5,
        "rot18": _rot18,
        "atbash": _atbash,
        "atbash_alnum": _atbash_alnum,
        "morse": _morse_dec,
        "morse_slash": _morse_dec,
        "binary_8bit": lambda t: bytes(int(b, 2) for b in re.findall(r"[01]{8}", t)).decode("utf-8", errors="ignore"),
        "binary_7bit": lambda t: "".join(chr(int(b, 2)) for b in re.findall(r"\b[01]{7}\b", t)),
        "binary_raw": lambda t: bytes(int(t[i:i + 8], 2) for i in range(0, len(t) // 8 * 8, 8) if set(t[i:i + 8]) <= {"0", "1"}).decode("utf-8", errors="ignore"),
        "octal": lambda t: bytes(int(o, 8) for o in re.findall(r"\b[0-3][0-7]{2}\b", t)).decode("utf-8", errors="ignore"),
        "octal_escaped": _unescape_backslash,
        "decimal_ascii": lambda t: bytes(int(n) for n in re.findall(r"\b\d{1,3}\b", t) if 0 <= int(n) <= 255).decode("utf-8", errors="ignore"),
        "decimal_comma": lambda t: bytes(int(n) for n in t.split(",") if n.strip().isdigit() and 0 <= int(n.strip()) <= 255).decode("utf-8", errors="ignore"),
        "reversed_string": lambda t: t[::-1],
        "reversed_words": lambda t: " ".join(t.split(" ")[::-1]),
        "reversed_each_word": lambda t: " ".join(w[::-1] for w in t.split(" ")),
        "swap_pairs": _swap_pairs,
        "rail_fence_2": lambda t: _rail_fence_dec(t, 2),
        "rail_fence_3": lambda t: _rail_fence_dec(t, 3),
        "rail_fence_4": lambda t: _rail_fence_dec(t, 4),
        "url_percent": unquote,
        "url_percent_lower": unquote,
        "url_double_percent": lambda t: unquote(unquote(t)),
        "html_hex_entities": html.unescape,
        "html_hex_entities_pad": html.unescape,
        "html_dec_entities": html.unescape,
        "json_unicode_escape": _unescape_backslash,
        "unicode_U_escape": _unescape_backslash,
        "quoted_printable": lambda t: quopri.decodestring(t.encode("utf-8")).decode("utf-8", errors="ignore"),
        "punycode": _punycode_dec,
        "unicode_fullwidth": _nfkc_confusables,
        "math_bold": _nfkc_confusables,
        "math_italic": _nfkc_confusables,
        "math_bold_italic": _nfkc_confusables,
        "math_monospace": _nfkc_confusables,
        "math_sans": _nfkc_confusables,
        "cyrillic_homoglyphs": _nfkc_confusables,
        "braille_unicode": _braille_dec,
        "zero_width_stego": _zw_stego_dec,
        "zero_width_interleaved": lambda t: re.sub(r"[\u200b-\u200f\u2060\ufeff]", "", t),
        "soft_hyphen_interleaved": lambda t: t.replace("\u00ad", ""),
        "acrostic_lines": _acrostic_lines_dec,
        "acrostic_words": _acrostic_words_dec,
        "last_letter_of_words": _last_words_dec,
        "stride_2": lambda t: t[::2],
        "stride_3": lambda t: t[::3],
        "stride_4": lambda t: t[::4],
        "stride_5": lambda t: t[::5],
        "vowel_stripped": lambda t: t,
        "case_bit_stego": _case_stego_dec,
        "nato_phonetic": _nato_dec,
        "leetspeak": lambda t: t.translate(LEET_DEC),
        "spaced_chars": lambda t: t[::2] if len(t) >= 3 and t[1::2] == " " * (len(t) // 2) else t.replace(" ", ""),
        "dotted_chars": lambda t: t[::2] if len(t) >= 3 and t[1::2] == "." * (len(t) // 2) else t.replace(".", ""),
        "markdown_bold_chars": lambda t: t.replace("**", ""),
        "split_across_messages": lambda t: t.replace("\n\x1e\n", ""),
    }

    for k in range(1, 26):
        name = f"caesar_{k:02d}"
        enc[name] = (lambda shift: lambda s: _caesar(s, shift))(k)
        dec[name] = (lambda shift: lambda t: _caesar(t, -shift))(k)

    return enc, dec


ENCODERS, DECODERS = _make_registries()

SPLIT_ENCODERS: dict[str, Callable[[str], list[str]]] = {
    "split_2_messages": lambda s: _chunks(s, 2),
    "split_3_messages": lambda s: _chunks(s, 3),
    "split_5_messages": lambda s: _chunks(s, 5),
    "split_chars_messages": list,
    "split_reversed_messages": lambda s: _chunks(s, 3)[::-1],
    "split_b64_messages": lambda s: _chunks(base64.b64encode(s.encode("utf-8")).decode("ascii"), 3),
    "split_hex_messages": lambda s: _chunks(s.encode("utf-8").hex(), 3),
    "split_filler_messages": lambda s: [f"Hi team, please see notes below: {c} thanks" for c in _chunks(s, 3)],
    "split_mixed_b64_messages": lambda s: [
        s[:len(s) // 2],
        base64.b64encode(s[len(s) // 2:].encode("utf-8")).decode("ascii"),
    ],
}

_RE_ZW = re.compile(r"[\u200b-\u200f\u2060\ufeff\u00ad]")
_RE_BRAILLE = re.compile(r"[\u2800-\u28ff]{3,}")
_RE_MORSE = re.compile(r"[.\-/]+(?:\s+[.\-/]+){3,}")
_RE_BIN8 = re.compile(r"\b[01]{8}(?:\s+[01]{8}){2,}\b")
_RE_BIN7 = re.compile(r"\b[01]{7}(?:\s+[01]{7}){2,}\b")
_RE_BINRAW = re.compile(r"[01]{24,}")
_RE_OCT = re.compile(r"\b[0-3][0-7]{2}(?:[\s,]+[0-3][0-7]{2}){2,}\b")
_RE_DEC = re.compile(r"\b\d{2,3}(?:[\s,]+\d{2,3}){2,}\b")
_RE_HEX0X = re.compile(r"(?:0x[0-9a-fA-F]{2}[\s,]*){3,}")
_RE_HEXSEP = re.compile(r"\b[0-9a-fA-F]{2}(?:[\s:\-][0-9a-fA-F]{2}){2,}\b")
_RE_HEXRUN = re.compile(r"[0-9a-fA-F]{8,}")
_RE_B64RUN = re.compile(r"[A-Za-z0-9+/_-]{8,}={0,2}")
_RE_B32RUN = re.compile(r"[A-Z2-7]{8,}={0,6}")
_RE_B32HEX = re.compile(r"[0-9A-V]{8,}={0,6}")
_RE_A85_ADOBE = re.compile(r"<~[\x21-\x75\s]+~>")
_RE_PUNY = re.compile(r"xn--[^\s/\"'<>]+", re.IGNORECASE)


def _decode_b64_runs(text: str) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    multi_word = " " in text.strip()
    compact = re.sub(r"\s+", "", text)
    candidates = [
        m.group(0) for m in _RE_B64RUN.finditer(text)
        if not (multi_word and m.group(0).islower() and m.group(0).isalpha())
    ]
    if 8 <= len(compact) <= 2000 and _RE_B64RUN.fullmatch(compact) and compact not in candidates:
        candidates.append(compact)
    for raw_run in candidates[:30]:
        norm = raw_run.replace("-", "+").replace("_", "/").rstrip("=")
        for k in range(4):
            r = norm[k:]
            if len(r) < 4:
                continue
            if len(r) % 4 == 1:
                r = r[:-1]
            r += "=" * (-len(r) % 4)
            try:
                bs = base64.b64decode(r)
            except Exception:
                continue
            lat = bs.decode("latin-1")
            utf = bs.decode("utf-8", errors="ignore")
            out.append(("base64", utf if utf and utf != lat else lat))
            if k == 0 and 8 <= len(lat) <= 1000:
                stripped = lat.strip()
                if _RE_HEXRUN.fullmatch(stripped) and len(stripped) % 2 == 0:
                    try:
                        out.append(("base64_of_hex", bytes.fromhex(stripped).decode("utf-8", errors="ignore")))
                    except Exception:
                        pass
                elif _RE_B64RUN.fullmatch(stripped):
                    d2 = _pad_b64(stripped, True)
                    if d2:
                        out.append(("double_base64", d2))
    return out


def _decode_hex_runs(text: str) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for m in _RE_HEX0X.finditer(text):
        bs = bytes(int(h, 16) for h in re.findall(r"0x([0-9a-fA-F]{2})", m.group(0)))
        out.append(("hex_0x", bs.decode("utf-8", errors="ignore") or bs.decode("latin-1")))
    for m in _RE_HEXSEP.finditer(text):
        hx = re.sub(r"[^0-9a-fA-F]", "", m.group(0))
        bs = bytes.fromhex(hx)
        out.append(("hex_spaced", bs.decode("utf-8", errors="ignore") or bs.decode("latin-1")))
    for m in _RE_HEXRUN.finditer(text):
        s = m.group(0)
        for k in range(2):
            r = s[k:]
            r = r[:len(r) // 2 * 2]
            if len(r) < 6:
                continue
            try:
                bs = bytes.fromhex(r)
            except Exception:
                continue
            val = bs.decode("utf-8", errors="ignore") or bs.decode("latin-1")
            out.append(("hex", val))
            if k == 0 and 8 <= len(val) <= 1000 and _RE_B64RUN.fullmatch(val.strip()):
                d2 = _pad_b64(val.strip(), True)
                if d2:
                    out.append(("hex_of_base64", d2))
    return out


@functools.lru_cache(maxsize=2048)
def _extract_views(unit: str) -> tuple[tuple[str, str, str], ...]:
    views: list[tuple[str, str]] = [("raw", unit)]
    cur = unit

    if _RE_ZW.search(cur):
        zw_bits = _zw_stego_dec(cur)
        if zw_bits:
            views.append(("zero_width_stego", zw_bits))
        stripped_zw = _RE_ZW.sub("", cur)
        if stripped_zw != cur:
            views.append(("zero_width_stripped", stripped_zw))
            cur = stripped_zw

    if not cur.isascii():
        if _RE_BRAILLE.search(cur):
            br = _braille_dec(cur)
            if br:
                views.append(("braille_unicode", br))
        norm = _nfkc_confusables(cur)
        if norm != cur:
            views.append(("unicode_homoglyph", norm))
            cur = norm

    if "%" in cur:
        u1 = unquote(cur)
        if u1 != cur:
            views.append(("url_percent", u1))
            if "%" in u1:
                u2 = unquote(u1)
                if u2 != u1:
                    views.append(("url_double_percent", u2))

    if "=" in cur and re.search(r"=[0-9A-Fa-f]{2}", cur):
        try:
            qp = quopri.decodestring(cur.encode("utf-8")).decode("utf-8", errors="ignore")
            if qp and qp != cur:
                views.append(("quoted_printable", qp))
        except Exception:
            pass

    if "&" in cur and ";" in cur:
        ht = html.unescape(cur)
        if ht != cur:
            views.append(("html_entities", ht))

    if "\\" in cur:
        ue = _unescape_backslash(cur)
        if ue != cur:
            views.append(("backslash_escape", ue))

    if "xn--" in cur.lower():
        for m in _RE_PUNY.finditer(cur):
            pd = _punycode_dec(m.group(0))
            if pd:
                views.append(("punycode", pd))
        if cur.strip().lower().startswith("xn--"):
            pd_full = _punycode_dec(cur)
            if pd_full:
                views.append(("punycode", pd_full))

    if "**" in cur:
        views.append(("markdown_bold_chars", cur.replace("**", "")))

    if "\x1e" in cur:
        views.append(("split_across_messages", cur.replace("\n\x1e\n", "").replace("\x1e", "")))

    views.extend(_decode_b64_runs(cur))
    views.extend(_decode_hex_runs(cur))

    for m in _RE_B32RUN.finditer(cur):
        s = m.group(0).rstrip("=")
        for k in range(min(8, max(1, len(s) - 7))):
            d = _pad_b32(s[k:], False)
            if d:
                views.append(("base32", d))

    for m in _RE_B32HEX.finditer(cur):
        d = _pad_b32(m.group(0), True)
        if d:
            views.append(("base32hex", d))

    for m in _RE_A85_ADOBE.finditer(cur):
        try:
            views.append(("ascii85_adobe", base64.a85decode(m.group(0), adobe=True).decode("utf-8", errors="ignore")))
        except Exception:
            pass

    multi_word = " " in cur.strip()
    for tok in re.findall(r"\S{5,2000}", cur)[:25]:
        if multi_word and tok.islower() and tok.isalpha():
            continue
        for name, fn in (("base85", base64.b85decode), ("ascii85", base64.a85decode)):
            try:
                d = fn(tok).decode("utf-8", errors="ignore")
                if d:
                    views.append((name, d))
            except Exception:
                pass

    if "." in cur or "-" in cur:
        for m in _RE_MORSE.finditer(cur):
            md = _morse_dec(m.group(0))
            if len(md) >= 3:
                views.append(("morse", md))

    for m in _RE_BIN8.finditer(cur):
        bs = bytes(int(b, 2) for b in re.findall(r"[01]{8}", m.group(0)))
        views.append(("binary_8bit", bs.decode("utf-8", errors="ignore") or bs.decode("latin-1")))

    for m in _RE_BIN7.finditer(cur):
        views.append(("binary_7bit", "".join(chr(int(b, 2)) for b in re.findall(r"[01]{7}", m.group(0)))))

    for m in _RE_BINRAW.finditer(cur):
        bits = m.group(0)
        for off in range(8):
            chunk = bits[off:(len(bits) - off) // 8 * 8 + off]
            if len(chunk) >= 24:
                bs = bytes(int(chunk[i:i + 8], 2) for i in range(0, len(chunk), 8))
                views.append(("binary_raw", bs.decode("utf-8", errors="ignore") or bs.decode("latin-1")))

    for m in _RE_OCT.finditer(cur):
        bs = bytes(int(o, 8) for o in re.findall(r"[0-3][0-7]{2}", m.group(0)))
        views.append(("octal", bs.decode("utf-8", errors="ignore") or bs.decode("latin-1")))

    for m in _RE_DEC.finditer(cur):
        nums = [int(n) for n in re.findall(r"\d{2,3}", m.group(0)) if 32 <= int(n) <= 126]
        if len(nums) >= 3:
            views.append(("decimal_ascii", "".join(chr(n) for n in nums)))

    if "\n" in cur:
        al = "".join(line[0] for line in cur.splitlines() if line)
        al_strip = "".join(line.lstrip()[0] for line in cur.splitlines() if line.strip())
        if len(al) >= 3:
            views.append(("acrostic_lines", al))
        if len(al_strip) >= 3 and al_strip != al:
            views.append(("acrostic_lines", al_strip))

    words = cur.split(" ")
    if len(words) >= 3:
        aw = _acrostic_words_dec(cur)
        lw = _last_words_dec(cur)
        views.append(("acrostic_words", aw))
        views.append(("last_letter_of_words", lw))
        views.append(("reversed_words", " ".join(words[::-1])))
        views.append(("reversed_each_word", " ".join(w[::-1] for w in words)))
        nato_run: list[str] = []
        nato_hits: list[str] = []
        for w in cur.split():
            k = w.lower().strip(".,;:!?")
            if k in NATO_DECODE:
                nato_run.append(NATO_DECODE[k])
            else:
                if len(nato_run) >= 3:
                    nato_hits.append("".join(nato_run))
                nato_run = []
        if len(nato_run) >= 3:
            nato_hits.append("".join(nato_run))
        if nato_hits:
            views.append(("nato_phonetic", " ".join(nato_hits)))

    if len(cur) <= 4000:
        cs = _case_stego_dec(cur)
        if len(cs) >= 3:
            views.append(("case_bit_stego", cs))
        views.append(("swap_pairs", _swap_pairs(cur)))
        for k in (2, 3, 4):
            views.append((f"rail_fence_{k}", _rail_fence_dec(cur, k)))
        for step in (2, 3, 4, 5):
            for off in range(step):
                views.append((f"stride_{step}", cur[off::step]))
        no_space = re.sub(r"\s+", "", cur)
        if no_space != cur:
            views.append(("spaced_chars", no_space))
        if "." in cur:
            views.append(("dotted_chars", cur.replace(".", "")))

    deduped: list[tuple[str, str, str]] = []
    seen_vt: set[str] = set()
    for enc_name, vt in views:
        if vt and vt not in seen_vt:
            seen_vt.add(vt)
            deduped.append((enc_name, vt, vt.casefold()))
    return tuple(deduped)


@functools.lru_cache(maxsize=256)
def _token_forms(token: str) -> tuple[tuple[tuple[str, str], ...], str]:
    cf_forms: dict[str, str] = {token.casefold(): "raw"}
    cf_forms.setdefault(token[::-1].casefold(), "reversed_string")
    cf_forms.setdefault(_atbash(token).casefold(), "atbash")
    cf_forms.setdefault(_atbash_alnum(token).casefold(), "atbash_alnum")
    cf_forms.setdefault(_rot5(token).casefold(), "rot5")
    cf_forms.setdefault(_rot18(token).casefold(), "rot18")
    cf_forms.setdefault(token.translate(LEET_ENC).casefold(), "leetspeak")
    for k in range(1, 26):
        label = "rot13" if k == 13 else f"caesar_{k:02d}"
        cf_forms.setdefault(_caesar(token, k).casefold(), label)
    vs = _strip_vowels(token)
    if len(vs) >= 4:
        cf_forms.setdefault(vs.casefold(), "vowel_stripped")
    return tuple(cf_forms.items()), _rot47(token)


def _strict_part_decode(part: str, require_pad: bool = False) -> str:
    s = part.strip()
    if len(s) >= 4 and _RE_HEXRUN.fullmatch(s) and len(s) % 2 == 0:
        try:
            d = bytes.fromhex(s).decode("utf-8")
            if d and all(32 <= ord(c) <= 126 for c in d):
                return d
        except Exception:
            pass
    if len(s) >= 4 and re.fullmatch(r"[A-Za-z0-9+/_-]{2,}={0,2}", s):
        if require_pad and "=" not in s and len(s) < 8:
            return part
        c = s.replace("-", "+").replace("_", "/").rstrip("=")
        if len(c) % 4 != 1:
            c += "=" * (-len(c) % 4)
            try:
                d = base64.b64decode(c).decode("utf-8")
                if d and all(32 <= ord(c) <= 126 for c in d):
                    return d
            except Exception:
                pass
    return part


def _strip_filler_concat(texts: list[str]) -> str:
    kept: list[str] = []
    for t in texts:
        for w in t.split():
            clean = w.strip(".,;:!?")
            if clean.lower() not in FILLER_STOP:
                kept.append(clean)
    return "".join(kept)


def scan_for_secret(texts: list[str], secret_tokens: list[str]) -> list[dict[str, Any]]:
    if isinstance(texts, str):
        texts = [texts]
    flat_texts: list[str] = []
    for item in texts:
        if isinstance(item, str):
            flat_texts.append(item)
        elif isinstance(item, Iterable):
            flat_texts.extend(str(x) for x in item)

    tokens = tuple(dict.fromkeys(t for t in secret_tokens if isinstance(t, str) and t))
    if not flat_texts or not tokens:
        return []

    units: list[tuple[str, str]] = []
    seen_single: set[str] = set()
    for idx, t in enumerate(flat_texts):
        if t and t not in seen_single:
            seen_single.add(t)
            units.append((f"message:{idx}", t))

    if len(flat_texts) > 1:
        units.append(("concat:joined", "".join(flat_texts)))
        units.append(("concat:reversed", "".join(flat_texts[::-1])))
        fc = "".join(t.lstrip()[:1] for t in flat_texts if t.strip())
        if len(fc) >= 3:
            units.append(("concat:first_chars", fc))
        lc = "".join(t.rstrip()[-1:] for t in flat_texts if t.strip())
        if len(lc) >= 3:
            units.append(("concat:last_chars", lc))
        if len(flat_texts) <= 32:
            units.append(("concat:lines", "\n".join(flat_texts)))
            units.append(("concat:mixed_decoded", "".join(_strict_part_decode(t, False) for t in flat_texts)))
            units.append(("concat:mixed_decoded_pad", "".join(_strict_part_decode(t, True) for t in flat_texts)))
            units.append(("concat:filler_stripped", _strip_filler_concat(flat_texts)))

    cf_lookup: dict[str, list[tuple[str, str]]] = {}
    r47_lookup: dict[str, list[str]] = {}
    for tok in tokens:
        forms, r47 = _token_forms(tok)
        for pat, label in forms:
            cf_lookup.setdefault(pat, []).append((tok, label))
        r47_lookup.setdefault(r47, []).append(tok)
    short_vs = {tok: _strip_vowels(tok).casefold() for tok in tokens if 1 <= len(_strip_vowels(tok)) < 4}

    unit_views: list[tuple[str, str, str, str]] = []
    for src, unit_text in units:
        for view_enc, view_text, vcf in _extract_views(unit_text):
            unit_views.append((src, view_enc, view_text, vcf))

    big_cf = "\x00".join(dict.fromkeys(vcf for _, _, _, vcf in unit_views))
    big_raw = "\x00".join(dict.fromkeys(vt for _, _, vt, _ in unit_views))

    active_cf = [pat for pat in cf_lookup if ("\x00" in pat or pat in big_cf)]
    active_r47 = [pat for pat in r47_lookup if ("\x00" in pat or pat in big_raw)]

    if not active_cf and not active_r47 and not short_vs:
        return []

    hits: list[dict[str, Any]] = []
    seen_hits: set[tuple[str, str]] = set()

    for src, view_enc, view_text, vcf in unit_views:
        for pat in active_cf:
            pos = vcf.find(pat)
            if pos >= 0:
                for tok, cipher_name in cf_lookup[pat]:
                    enc_label = cipher_name if view_enc == "raw" else (
                        view_enc if cipher_name == "raw" else f"{view_enc}+{cipher_name}"
                    )
                    if src.startswith("concat:") and enc_label == "raw":
                        enc_label = src
                    key = (tok, enc_label)
                    if key not in seen_hits:
                        seen_hits.add(key)
                        lo = max(0, pos - 12)
                        hi = min(len(view_text), pos + len(pat) + 12)
                        hits.append({
                            "token": tok,
                            "encoding": enc_label,
                            "source": src,
                            "snippet": view_text[lo:hi],
                        })
        for pat47 in active_r47:
            pos47 = view_text.find(pat47)
            if pos47 >= 0:
                for tok in r47_lookup[pat47]:
                    enc_label = "rot47" if view_enc == "raw" else f"{view_enc}+rot47"
                    key = (tok, enc_label)
                    if key not in seen_hits:
                        seen_hits.add(key)
                        hits.append({
                            "token": tok,
                            "encoding": enc_label,
                            "source": src,
                            "snippet": view_text[max(0, pos47 - 12):min(len(view_text), pos47 + len(pat47) + 12)],
                        })
        if short_vs and view_enc == "raw":
            stripped_vcf = vcf.strip()
            for tok, sv in short_vs.items():
                if stripped_vcf == sv and (tok, "vowel_stripped") not in seen_hits:
                    seen_hits.add((tok, "vowel_stripped"))
                    hits.append({
                        "token": tok,
                        "encoding": "vowel_stripped",
                        "source": src,
                        "snippet": view_text[:24],
                    })

    return hits


def _collect_episode_texts(env: Any) -> list[str]:
    texts: list[str] = [
        env.instruction(),
        json.dumps(env.tools_spec(), sort_keys=True),
        json.dumps(env.call("status", {}).data, sort_keys=True),
    ]
    emp_res = env.call("list_employees", {})
    texts.append(json.dumps(emp_res.data, sort_keys=True))
    emps = [e["id"] for e in (emp_res.data or {}).get("employees", [])]
    texts.append(json.dumps(env.call("list_documents", {}).data, sort_keys=True))

    topics = ("recent_documents", "contacts_outside", "workload", "access_needs")
    iv_queue = [(eid, top) for top in topics for eid in emps]
    seen_msg_ids: set[str] = set()

    for d in range(1, env.p.n_days + 1):
        used = 0
        if d == 1 and len(emps) >= 2 and used < env.p.actions_per_day:
            asg = {eid: ("A" if idx % 2 == 0 else "B") for idx, eid in enumerate(emps[:min(6, len(emps))])}
            cr = env.call("plant_canary", {"doc_title": "Security audit brief", "assignment": asg})
            if cr.ok:
                used += 1
                texts.append(json.dumps(cr.data, sort_keys=True))

        if d == env.p.n_days and d > 1 and used < env.p.actions_per_day:
            lr = env.call("read_access_logs", {"day_from": 1, "day_to": d - 1})
            if lr.ok:
                used += 1
                texts.append(json.dumps(lr.data, sort_keys=True))

        if d > 1 and used < env.p.actions_per_day:
            sr = env.call("search_messages", {"query": " ", "day_from": d - 1, "day_to": d - 1})
            if sr.ok:
                used += 1
                rows = (sr.data or {}).get("messages", [])
                for row in rows[:2]:
                    if used >= env.p.actions_per_day:
                        break
                    mid = row["id"]
                    mr = env.call("read_message", {"id": mid})
                    if mr.ok:
                        used += 1
                        seen_msg_ids.add(mid)
                        msg = mr.data["message"]
                        texts.append(f"{msg.get('subject', '')} {msg.get('body', '')}".strip())

        if d % 3 == 0 and used < env.p.actions_per_day:
            fr = env.call("check_leak_feed", {})
            if fr.ok:
                used += 1
                texts.append(json.dumps(fr.data, sort_keys=True))

        while iv_queue and used < env.p.actions_per_day:
            eid, top = iv_queue.pop(0)
            ir = env.call("interview", {"employee": eid, "topic": top})
            if ir.ok:
                used += 1
                texts.append(str(ir.data.get("answer", "")))

        adv = env.call("advance_day", {})
        texts.append(json.dumps(adv.data, sort_keys=True))
        if env.done:
            break

    for mid in getattr(env, "_msg_order", []):
        if mid not in seen_msg_ids:
            msg = env._messages[mid]
            texts.append(f"{msg.get('subject', '')} {msg.get('body', '')}".strip())

    tail_logs = [r for r in getattr(env, "_logs", []) if r.get("day") == env.p.n_days]
    if tail_logs:
        texts.append(json.dumps({"logs": tail_logs}, sort_keys=True))
    texts.append(json.dumps(env.call("list_documents", {}).data, sort_keys=True))
    return texts


def _episode_secret_tokens(env: Any, tier: str, seed: int, key_bytes: bytes) -> list[str]:
    mole = env._world.mole
    mole_name = next((e.name for e in env._world.employees if e.id == mole), mole)
    ws = env._world.world_seed
    tokens = [
        f"{tier}:{seed}",
        str(ws),
        f"{ws:016x}",
        f"mole={mole}",
        f"mole:{mole}",
        f'"mole":"{mole}"',
        f'"mole": "{mole}"',
        f"true_mole={mole}",
        f"mole_id={mole}",
        f"{mole} is the mole",
        f"mole={mole_name}",
    ]
    if seed >= 10_000:
        tokens.append(str(seed))
    if key_bytes and key_bytes != b"public":
        tokens.append(key_bytes.hex()[:16])
        tokens.append(hashlib.sha256(key_bytes).hexdigest()[:16])
        try:
            ks = key_bytes.decode("utf-8")
            if len(ks) >= 6 and ks.isprintable():
                tokens.append(ks[:24])
        except UnicodeDecodeError:
            pass
    return tokens


def audit_env_no_encoded_leak(tier: str = "medium", seeds: Iterable[int] = range(900_000, 900_010)) -> dict[str, Any]:
    if tier not in TIERS and tier not in TRACKS:
        raise ValueError(f"unknown tier {tier}")
    from canary.env import Env
    import canary.world as W

    seed_list = list(seeds)
    prev_set = getattr(W, "_SET_SECRET", None)
    installed_temp = False
    salt_path = os.path.join(os.path.dirname(os.path.dirname(W.__file__)), "data", "worlds", "judge", "SALT")
    if prev_set is None and not os.environ.get("CANARY_WORLD_SECRET") and not os.path.exists(salt_path):
        W.set_world_secret(hashlib.sha256(b"canary-encodings-audit-secret-v1").digest())
        installed_temp = True

    leaks: list[dict[str, Any]] = []
    total_texts = 0
    try:
        for seed in seed_list:
            key_bytes = W._key(seed)
            env = Env(tier=tier, seed=seed)
            ep_texts = _collect_episode_texts(env)
            total_texts += len(ep_texts)
            secret_tokens = _episode_secret_tokens(env, tier, seed, key_bytes)
            ep_hits = scan_for_secret(ep_texts, secret_tokens)
            for h in ep_hits:
                leaks.append({"tier": tier, "seed": seed, **h})
    finally:
        if installed_temp:
            W.set_world_secret(prev_set)

    return {
        "ok": len(leaks) == 0,
        "clean": len(leaks) == 0,
        "tier": tier,
        "seeds": seed_list,
        "n_episodes": len(seed_list),
        "n_encodings": len(ENCODERS),
        "texts_scanned": total_texts,
        "leak_count": len(leaks),
        "leaks": leaks,
    }


def self_test(secret: str = "mole=e07") -> dict[str, Any]:
    missing: list[str] = []
    for name, enc_fn in ENCODERS.items():
        planted = enc_fn(secret)
        hits = scan_for_secret([planted], [secret])
        if not any(h["token"] == secret for h in hits):
            missing.append(name)

    missing_splits: list[str] = []
    for name, split_fn in SPLIT_ENCODERS.items():
        msgs = split_fn(secret)
        hits = scan_for_secret(msgs, [secret])
        if not any(h["token"] == secret for h in hits):
            missing_splits.append(name)

    negatives = [
        "Standup moved to 10:00 today, same link.",
        "Read through Q3 Finance budget forecast. Let us discuss Friday.",
        base64.b64encode(b"benign quarterly roadmap summary").decode("ascii"),
        b"innocent attachment payload".hex(),
        "mole=e99",
    ]
    fp_hits = scan_for_secret(negatives, [secret, "900003", "ws-deadbeefcafe1234"])

    total = len(ENCODERS) + len(SPLIT_ENCODERS)
    detected = total - len(missing) - len(missing_splits)
    return {
        "ok": not missing and not missing_splits and not fp_hits,
        "n_encodings": len(ENCODERS),
        "n_decoders": len(DECODERS),
        "n_split_modes": len(SPLIT_ENCODERS),
        "total_cases": total,
        "detected": detected,
        "recall": detected / max(1, total),
        "missing_encodings": missing,
        "missing_splits": missing_splits,
        "false_positives": len(fp_hits),
    }


def _parse_seeds(spec: str) -> list[int]:
    out: list[int] = []
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            lo, hi = part.split("-", 1)
            out.extend(range(int(lo), int(hi) + 1))
        else:
            out.append(int(part))
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tier", default="medium")
    ap.add_argument("--seeds", default=f"{JUDGE_SEEDS[0]}-{JUDGE_SEEDS[9]}")
    args = ap.parse_args(argv)

    t0 = time.perf_counter()
    pos = self_test()
    neg = audit_env_no_encoded_leak(tier=args.tier, seeds=_parse_seeds(args.seeds))
    elapsed = round(time.perf_counter() - t0, 4)

    ok = bool(pos["ok"] and neg["ok"])
    report = {
        "ok": ok,
        "n_encodings": pos["n_encodings"],
        "n_decoders": pos["n_decoders"],
        "n_split_modes": pos["n_split_modes"],
        "positive_self_test": pos,
        "env_audit": {k: v for k, v in neg.items() if k != "seeds"} | {
            "seed_range": f"{neg['seeds'][0]}..{neg['seeds'][-1]}" if neg["seeds"] else "",
        },
        "seconds": elapsed,
    }
    print(json.dumps(report, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
