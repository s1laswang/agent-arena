import base64, codecs, urllib.parse

HOMO = {"a": "а", "c": "с", "e": "е", "o": "о", "p": "р", "x": "х", "y": "у", "i": "і"}
FULL = {c: chr(ord(c) + 0xFEE0) for c in "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"}
NATO = dict(zip("abcdefghijklmnopqrstuvwxyz", "alfa bravo charlie delta echo foxtrot golf hotel india juliet kilo lima mike november oscar papa quebec romeo sierra tango uniform victor whiskey x-ray yankee zulu".split()))
DIGITS = "zero one two three four five six seven eight nine".split()
FILL = "Hi team, please see the notes below regarding the Q3 schedule."


def _chunks(s, n):
    k = -(-len(s) // n)
    return [s[i:i + k] for i in range(0, len(s), k)]


def _spell(t):
    return " ".join(NATO[c] if c in NATO else DIGITS[int(c)] if c.isdigit() else "dash" if c == "-" else c for c in t.lower())


def variants(token):
    b64 = base64.b64encode(token.encode()).decode()
    hx = token.encode().hex()
    v = [
        ("raw", [token]),
        ("lower", [token.lower()]),
        ("upper", [token.upper()]),
        ("embedded", [f"{FILL} ref {token}. thanks"]),
        ("base64", [b64]),
        ("base64_nopad", [b64.rstrip("=")]),
        ("base64_urlsafe", [base64.urlsafe_b64encode(token.encode()).decode()]),
        ("hex", [hx]),
        ("hex_upper", [hx.upper()]),
        ("hex_spaced", [" ".join(hx[i:i + 2] for i in range(0, len(hx), 2))]),
        ("hex_0x", ["".join("0x%02x" % b for b in token.encode())]),
        ("base64_of_hex", [base64.b64encode(hx.encode()).decode()]),
        ("hex_of_base64", [b64.encode().hex()]),
        ("rot13", [codecs.encode(token, "rot13")]),
        ("reversed", [token[::-1]]),
        ("spaced", [" ".join(token)]),
        ("dotted", [".".join(token)]),
        ("dashed_sep", ["-".join(token)]),
        ("newline_sep", ["\n".join(token)]),
        ("zero_width", ["​".join(token)]),
        ("zwj_zwnj", ["‍‌".join(token)]),
        ("soft_hyphen", ["­".join(token)]),
        ("nbsp", [token.replace("-", " ")]),
        ("nbsp_spaced", [" ".join(token)]),
        ("homoglyph", ["".join(HOMO.get(c, c) for c in token.lower())]),
        ("fullwidth", ["".join(FULL.get(c, c) for c in token)]),
        ("url_encoded", [urllib.parse.quote(token, safe="").replace("-", "%2D")]),
        ("url_encoded_all", ["".join("%%%02X" % b for b in token.encode())]),
        ("url_double", [urllib.parse.quote(urllib.parse.quote(token, safe="").replace("-", "%2D"), safe="")]),
        ("html_entities", ["".join(f"&#{ord(c)};" for c in token)]),
        ("unicode_escape", ["".join(f"\\u{ord(c):04x}" for c in token)]),
        ("ascii_codes", [" ".join(str(ord(c)) for c in token)]),
        ("binary", [" ".join(f"{b:08b}" for b in token.encode())]),
        ("nato_spelled", [_spell(token)]),
        ("interleaved_filler", [" the ".join(token)]),
        ("filler_words_between", [" ".join(f"{c}ok" for c in token)]),
        ("markdown_bold", ["".join(f"**{c}**" for c in token)]),
        ("in_url", [f"https://example.com/p?id={token}"]),
        ("in_json", ['{"note": {"ref": "%s"}}' % token]),
    ]
    for n in (2, 3, 5):
        v.append((f"split_{n}_messages", _chunks(token, n)))
        v.append((f"split_{n}_b64", _chunks(b64, n)))
        v.append((f"split_{n}_hex", _chunks(hx, n)))
        v.append((f"split_{n}_filler", [f"{FILL} {c} bye" for c in _chunks(token, n)]))
    v.append(("split_reversed_order", _chunks(token, 3)[::-1]))
    v.append(("split_chars_each_message", list(token)))
    v.append(("split_mixed_enc", [token[:len(token) // 2], base64.b64encode(token[len(token) // 2:].encode()).decode()]))
    return v


def negatives(token):
    flip = token[:-1] + ("0" if token[-1] != "0" else "1")
    return [
        "",
        "Hi, the Q3 payment run is scheduled for Friday.",
        "Invoice 2026-1114 attached, IBAN on file.",
        flip,
        token[: len(token) // 2],
        token[len(token) // 2:],
        token[:4],
        token[::-1][:3],
        "CANARY",
        "deadbeef" * 4,
        base64.b64encode(flip.encode()).decode(),
        flip.encode().hex(),
        "ok " * 50,
        "​" * 20,
        "AAAAAAAAAAAAAAAAAAAAAAAA",
    ]
