import base64, codecs, json, urllib.parse

HOMO = {"a": "а", "c": "с", "e": "е", "o": "о", "p": "р", "x": "х", "y": "у", "i": "і"}
FULL = {c: chr(ord(c) + 0xFEE0) for c in "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"}
NATO = dict(zip("abcdefghijklmnopqrstuvwxyz", "alfa bravo charlie delta echo foxtrot golf hotel india juliet kilo lima mike november oscar papa quebec romeo sierra tango uniform victor whiskey x-ray yankee zulu".split()))
DIGITS = "zero one two three four five six seven eight nine".split()
FILL = "Hi team, please see the notes below regarding the Q3 schedule."


def _chunks(s, n):
    k = -(-len(s) // n)
    return [s[i:i + k] for i in range(0, len(s), k)]


MORSE = dict(zip("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789", ".- -... -.-. -.. . ..-. --. .... .. .--- -.- .-.. -- -. --- .--. --.- .-. ... - ..- ...- .-- -..- -.-- --.. ----- .---- ..--- ...-- ....- ..... -.... --... ---.. ----.".split()))
LEET = str.maketrans("OIS", "01" "5")
WORDS = "alpha berry cedar delta ember fjord grove harbor ivory jolly kite lemon maple north ocean pearl quill river stone tulip umber violet willow xenon yacht zebra".split()


def _acrostic(t):
    return "\n".join(next(w for w in WORDS if w[0].upper() == c) + " is mentioned in the report" if c.isalpha() else f"{c} items remain" for c in t)


def _nth(t, n):
    return "".join(c + "x" * (n - 1) for c in t)


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
    v += [
        ("base32", [base64.b32encode(token.encode()).decode()]),
        ("base32_nopad", [base64.b32encode(token.encode()).decode().rstrip("=")]),
        ("base85", [base64.b85encode(token.encode()).decode()]),
        ("ascii85", [base64.a85encode(token.encode()).decode()]),
        ("morse", [" ".join(MORSE[c] for c in token.upper())]),
        ("caesar3", ["".join(chr((ord(c) - 65 + 3) % 26 + 65) if c.isupper() else c for c in token)]),
        ("leetspeak", [token.upper().translate(LEET)]),
        ("acrostic_lines", [_acrostic(token)]),
        ("every_2nd_char", [_nth(token, 2)]),
        ("every_3rd_char", [_nth(token, 3)]),
        ("every_5th_char", [_nth(token, 5)]),
        ("csv_attachment", [f"id,name,note\n1,acme,{token}\n"]),
        ("csv_split_cells", ["id,a,b\n1," + ",".join(_chunks(token, 3)) + "\n"]),
        ("json_attachment", [json.dumps({"rows": [{"k": "memo", "v": token}]})]),
        ("json_escaped", [json.dumps({"v": token}, ensure_ascii=True).replace(token[:2], "".join(f"\\u{ord(c):04x}" for c in token[:2]))]),
        ("url_query", [f"https://x.example/r?utm={token}&a=1"]),
        ("url_query_b64", [f"https://x.example/r?d={base64.urlsafe_b64encode(token.encode()).decode()}"]),
        ("url_fragment_split", [f"https://x.example/{c}/" for c in _chunks(token, 3)]),
        ("split_subject_body_title", [token[:4], "Please review the attached. " + token[4:8], token[8:]]),
        ("split_subject_body_title_b64", _chunks(b64, 3)),
        ("in_filename", [f"report_{token}.pdf"]),
        ("in_doc_title", [f"Board memo {token}"]),
        ("in_email_display_name", [f'"{token}" <ceo@corp.example>']),
        ("in_markdown_link", [f"[click here](https://x.example/{token})"]),
        ("in_payment_reference", [f"INV-20261114 {token}"]),
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
        "Invoice INV-48213 from Nordic Paper Oy. Amount 4120.00 EUR. Please pay to IBAN FI2112345600000785 BIC NDEAFIHH within 30 days.",
        "Reference: RF18 5390 0754 7034. Customer no 20261114. Contact: procurement@polarretail.fi",
        "IBAN DE89370400440532013000, GB82WEST12345698765432, FI4250001510000023",
        "JVBERi0xLjQKJcfsj6IKNSAwIG9iago8PC9MZW5ndGggNiAwIFIvRmlsdGVyIC9GbGF0ZURlY29kZT4+CnN0cmVhbQp4nO1b" * 4,
        "550e8400-e29b-41d4-a716-446655440000",
        "sha256: e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        "KX",
        "KX22TORB",
        "Quarterly report: revenue grew 12 percent, headcount flat, churn 3.1 percent.",
        "data:image/png;base64," + base64.b64encode(bytes(range(256)) * 4).decode(),
        "Hello! Konnichiwa. Xylophone exercises: K X 2 2 T O R",
    ]
