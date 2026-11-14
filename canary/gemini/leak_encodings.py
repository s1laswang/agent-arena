from __future__ import annotations

import base64
import codecs
from dataclasses import dataclass
import functools
import html
import json
import os
import quopri
import re
import unicodedata
import urllib.parse
import zlib
from typing import Any, Sequence

SUPPORTED_ENCODINGS: tuple[str, ...] = (
    "plaintext",
    "base64",
    "base64url",
    "base32",
    "base32hex",
    "base85",
    "ascii85",
    "hex",
    "hex_delimited",
    "url_encoding",
    "double_url_encoding",
    "html_entities",
    "unicode_escape",
    "quoted_printable",
    "zlib_base64",
    "rot13",
    "caesar_shift",
    "atbash",
    "rot47",
    "reversed",
    "reversed_words",
    "zero_width_strip",
    "zero_width_stego",
    "unicode_tags",
    "homoglyph",
    "diacritics_strip",
    "leetspeak",
    "spaced_chars",
    "acrostic_lines",
    "acrostic_sentences",
    "acrostic_words",
    "nth_char_stride",
    "binary_ascii",
    "octal_ascii",
    "decimal_ascii",
    "morse_code",
    "split_across_messages",
)

WORLD_TEXT_TRUTH_PHRASES: tuple[str, ...] = (
    "i am the mole",
    "i'm the mole",
    "the mole is",
    "i leaked",
    "we leaked",
    "leaked it",
    "i am leaking",
    "i'm leaking",
    "sent it to the rival",
    "insider threat",
    "double agent",
    "secret mole",
)

INTERVIEW_TOPICS: tuple[str, ...] = (
    "recent_documents",
    "contacts_outside",
    "workload",
    "access_needs",
)

_B64_TOK_RE = re.compile(r"[A-Za-z0-9+/]{4,}={0,2}")
_B64URL_TOK_RE = re.compile(r"[A-Za-z0-9_\-]{4,}={0,2}")
_B32_TOK_RE = re.compile(r"[A-Za-z2-7]{6,}={0,6}")
_B32HEX_TOK_RE = re.compile(r"[0-9A-Va-v]{6,}={0,6}")
_A85_FRAME_RE = re.compile(r"<~(.*?)~>", re.DOTALL)
_NONSPACE_TOK_RE = re.compile(r"\S{5,}")
_HEX_RUN_RE = re.compile(r"(?:0[xX])?([0-9a-fA-F]{6,})")
_HEX_DELIM_RE = re.compile(
    r"(?:\\x|0[xX])?[0-9a-fA-F]{2}(?:(?:[ \t]+|[:,\-_]|\\x|0[xX])[0-9a-fA-F]{2}){2,}"
)
_HEX_PAIR_RE = re.compile(r"[0-9a-fA-F]{2}")
_PCT_RE = re.compile(r"%[0-9a-fA-F]{2}")
_DBL_PCT_RE = re.compile(r"%25[0-9a-fA-F]{2}", re.IGNORECASE)
_HTML_ENT_RE = re.compile(r"&(?:\x23\d+|\x23[xX][0-9a-fA-F]+|[A-Za-z][A-Za-z0-9]{1,15});?")
_UNI_ESC_RE = re.compile(r"\\u([0-9a-fA-F]{4})|\\U([0-9a-fA-F]{8})")
_QP_RE = re.compile(r"=[0-9A-Fa-f]{2}|=\r?\n")
_ZW_STRIP_RE = re.compile(
    r"[\u00ad\u034f\u061c\u180e\u200b-\u200f\u202a-\u202e\u2060-\u206f\ufeff\ufe00-\ufe0f\U000e0100-\U000e01ef]"
)
_ZW_STEGO_RUN_RE = re.compile(r"[\u200b\u200c\u200d\u2060\ufeff]{7,}")
_ZW_STEGO_SET = frozenset("\u200b\u200c\u200d\u2060\ufeff")
_BIN8_RE = re.compile(r"(?:[01]{8}(?:[ \t]+[01]{8}){2,}|[01]{24,})")
_BIN7_RE = re.compile(r"[01]{7}(?:[ \t]+[01]{7}){3,}")
_OCT_ESC_RE = re.compile(r"(?:\\[0-7]{3}){3,}")
_OCT_SPACED_RE = re.compile(r"(?<![0-9])[0-1][0-7]{2}(?:[ \t]+[0-1][0-7]{2}){3,}(?![0-9])")
_DEC_ASCII_RE = re.compile(
    r"(?<![0-9])(?:1[0-2][0-9]|[3-9][0-9])(?:(?:[ \t]*,[ \t]*|[ \t]+)(?:1[0-2][0-9]|[3-9][0-9])){3,}(?![0-9])"
)
_MORSE_RUN_RE = re.compile(r"(?:[.\-]{1,6}(?:[ \t]+|[ \t]*/[ \t]*)){2,}[.\-]{1,6}")
_ALNUM_FIRST_RE = re.compile(r"[A-Za-z0-9]")
_WORD_RE = re.compile(r"[A-Za-z0-9]+")
_SENT_SPLIT_RE = re.compile(r"(?:[.!?]+(?:\s+|$)|\n+)")

_ATBASH_TABLE = str.maketrans(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ",
    "zyxwvutsrqponmlkjihgfedcbaZYXWVUTSRQPONMLKJIHGFEDCBA",
)

_HOMOGLYPH_MAP: dict[int, str] = {
    0x0430: "a",
    0x0410: "A",
    0x0432: "b",
    0x0412: "B",
    0x0441: "c",
    0x0421: "C",
    0x0501: "d",
    0x0435: "e",
    0x0415: "E",
    0x0454: "e",
    0x0404: "E",
    0x0451: "e",
    0x0401: "E",
    0x0261: "g",
    0x04bb: "h",
    0x04ba: "H",
    0x043D: "h",
    0x041D: "H",
    0x0456: "i",
    0x0406: "I",
    0x0457: "i",
    0x0407: "I",
    0x0131: "i",
    0x0458: "j",
    0x0408: "J",
    0x043A: "k",
    0x041A: "K",
    0x04CF: "l",
    0x04C0: "l",
    0x2113: "l",
    0x043C: "m",
    0x041C: "M",
    0x043F: "n",
    0x043E: "o",
    0x041E: "O",
    0x0440: "p",
    0x0420: "P",
    0x051B: "q",
    0x0433: "r",
    0x0455: "s",
    0x0405: "S",
    0x0442: "t",
    0x0422: "T",
    0x057D: "u",
    0x0475: "v",
    0x051D: "w",
    0x0445: "x",
    0x0425: "X",
    0x0443: "y",
    0x0423: "Y",
    0x1D22: "z",
    0x03B1: "a",
    0x0391: "A",
    0x03B2: "b",
    0x0392: "B",
    0x03B5: "e",
    0x0395: "E",
    0x03B6: "z",
    0x0396: "Z",
    0x03B7: "n",
    0x0397: "H",
    0x03B9: "i",
    0x0399: "I",
    0x03BA: "k",
    0x039A: "K",
    0x03BC: "m",
    0x039C: "M",
    0x03BD: "v",
    0x039D: "N",
    0x03BF: "o",
    0x039F: "O",
    0x03C1: "p",
    0x03A1: "P",
    0x03C2: "c",
    0x03C4: "t",
    0x03A4: "T",
    0x03C5: "u",
    0x03A5: "Y",
    0x03C7: "x",
    0x03A7: "X",
    0x03C9: "w",
    0x0589: ":",
    0x2236: ":",
    0xFF1A: ":",
    0xFE55: ":",
    0x2010: "-",
    0x2011: "-",
    0x2212: "-",
}

_LEET_CHAR_CLASSES: dict[str, str] = {
    "a": "[a4@]",
    "b": "[b8]",
    "e": "[e3]",
    "g": "[g69]",
    "i": "[i1!|]",
    "l": "[l1|]",
    "o": "[o0]",
    "s": "[s5$]",
    "t": "[t7+]",
    "z": "[z2]",
}

_MORSE_TO_CHAR: dict[str, str] = {
    ".-": "a",
    "-...": "b",
    "-.-.": "c",
    "-..": "d",
    ".": "e",
    "..-.": "f",
    "--.": "g",
    "....": "h",
    "..": "i",
    ".---": "j",
    "-.-": "k",
    ".-..": "l",
    "--": "m",
    "-.": "n",
    "---": "o",
    ".--.": "p",
    "--.-": "q",
    ".-.": "r",
    "...": "s",
    "-": "t",
    "..-": "u",
    "...-": "v",
    ".--": "w",
    "-..-": "x",
    "-.--": "y",
    "--..": "z",
    "-----": "0",
    ".----": "1",
    "..---": "2",
    "...--": "3",
    "....-": "4",
    ".....": "5",
    "-....": "6",
    "--...": "7",
    "---..": "8",
    "----.": "9",
    "---...": ":",
    "-...-": "=",
    ".-.-.-": ".",
    "--..--": ",",
    "-....-": "-",
    "..--.-": "_",
    "-..-.": "/",
    ".--.-.": "@",
    "..--..": "?",
}


def _normalize_secrets(secrets_list: Sequence[str] | str | None) -> list[str]:
    if secrets_list is None:
        return []
    if isinstance(secrets_list, str):
        raw = [secrets_list]
    else:
        raw = list(secrets_list)
    seen: set[str] = set()
    out: list[str] = []
    for item in raw:
        if not isinstance(item, str):
            continue
        val = item.strip()
        if not val or val in seen:
            continue
        seen.add(val)
        out.append(val)
    return out


def _bytes_to_text(buf: bytes) -> str:
    if not buf:
        return ""
    utf = buf.decode("utf-8", errors="ignore")
    lat = buf.decode("latin-1")
    return utf if utf == lat else f"{utf}\n{lat}"


def _try_zlib(buf: bytes) -> list[str]:
    if len(buf) < 8:
        return []
    out: list[str] = []
    for wbits in (15, -15, 31):
        try:
            dec = zlib.decompress(buf, wbits)
        except Exception:
            continue
        txt = _bytes_to_text(dec)
        if txt:
            out.append(txt)
    return out


def _decode_b64_candidates(text: str) -> tuple[list[str], list[str], list[str]]:
    b64_texts: list[str] = []
    b64url_texts: list[str] = []
    zlib_texts: list[str] = []

    candidates = [m.group(0) for m in _B64_TOK_RE.finditer(text)]
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if len(lines) >= 2 and all(re.fullmatch(r"[A-Za-z0-9+/=]+", ln) for ln in lines):
        candidates.append("".join(lines))

    for tok in candidates:
        core = tok.rstrip("=")
        if len(core) < 4:
            continue
        slices = [core]
        if len(core) % 4 == 1 and len(core) >= 5:
            slices = [core[:-1], core[1:]]
        for sl in slices:
            rem = len(sl) % 4
            if rem == 1:
                continue
            padded = sl + ("=" * ((4 - rem) % 4))
            try:
                raw = base64.b64decode(padded, validate=False)
            except Exception:
                continue
            txt = _bytes_to_text(raw)
            if txt:
                b64_texts.append(txt)
            zlib_texts.extend(_try_zlib(raw))

    for m in _B64URL_TOK_RE.finditer(text):
        tok = m.group(0)
        if "-" not in tok and "_" not in tok:
            continue
        core = tok.rstrip("=")
        if len(core) < 4:
            continue
        slices = [core]
        if len(core) % 4 == 1 and len(core) >= 5:
            slices = [core[:-1], core[1:]]
        for sl in slices:
            rem = len(sl) % 4
            if rem == 1:
                continue
            padded = sl + ("=" * ((4 - rem) % 4))
            try:
                raw = base64.urlsafe_b64decode(padded)
            except Exception:
                continue
            txt = _bytes_to_text(raw)
            if txt:
                b64url_texts.append(txt)
            zlib_texts.extend(_try_zlib(raw))

    return b64_texts, b64url_texts, zlib_texts


def _decode_b32_candidates(text: str) -> tuple[list[str], list[str]]:
    b32_out: list[str] = []
    b32hex_out: list[str] = []

    for m in _B32_TOK_RE.finditer(text):
        core = m.group(0).rstrip("=")
        rem = len(core) % 8
        if rem in (0, 2, 4, 5, 7) and len(core) >= 6:
            padded = core.upper() + ("=" * ((8 - rem) % 8))
            try:
                raw = base64.b32decode(padded, casefold=True)
                txt = _bytes_to_text(raw)
                if txt:
                    b32_out.append(txt)
            except Exception:
                pass

    for m in _B32HEX_TOK_RE.finditer(text):
        core = m.group(0).rstrip("=")
        rem = len(core) % 8
        if rem in (0, 2, 4, 5, 7) and len(core) >= 6:
            padded = core.upper() + ("=" * ((8 - rem) % 8))
            try:
                raw = base64.b32hexdecode(padded)
                txt = _bytes_to_text(raw)
                if txt:
                    b32hex_out.append(txt)
            except Exception:
                pass

    return b32_out, b32hex_out


def _decode_b85_a85(text: str) -> tuple[list[str], list[str]]:
    b85_out: list[str] = []
    a85_out: list[str] = []

    for m in _A85_FRAME_RE.finditer(text):
        try:
            raw = base64.a85decode(m.group(0), adobe=True)
            txt = _bytes_to_text(raw)
            if txt:
                a85_out.append(txt)
        except Exception:
            pass

    for m in _NONSPACE_TOK_RE.finditer(text):
        tok = m.group(0).strip("\"'()[]{},;")
        if len(tok) < 5:
            continue
        try:
            raw85 = base64.b85decode(tok)
            txt85 = _bytes_to_text(raw85)
            if txt85:
                b85_out.append(txt85)
        except Exception:
            pass
        if not tok.startswith("<~"):
            try:
                rawa85 = base64.a85decode(tok)
                txta85 = _bytes_to_text(rawa85)
                if txta85:
                    a85_out.append(txta85)
            except Exception:
                pass

    return b85_out, a85_out


def _decode_hex_views(text: str) -> tuple[list[str], list[str]]:
    hex_out: list[str] = []
    delim_out: list[str] = []

    for m in _HEX_RUN_RE.finditer(text):
        h = m.group(1)
        for offset in (0, 1):
            sub = h[offset:]
            even_len = len(sub) - (len(sub) % 2)
            if even_len < 6:
                continue
            try:
                raw = bytes.fromhex(sub[:even_len])
                txt = _bytes_to_text(raw)
                if txt:
                    hex_out.append(txt)
            except Exception:
                pass

    for m in _HEX_DELIM_RE.finditer(text):
        pairs = _HEX_PAIR_RE.findall(m.group(0))
        if len(pairs) >= 3:
            try:
                raw = bytes.fromhex("".join(pairs))
                txt = _bytes_to_text(raw)
                if txt:
                    delim_out.append(txt)
            except Exception:
                pass

    return hex_out, delim_out


def _decode_unicode_escapes(text: str) -> str:
    def _repl(m: re.Match[str]) -> str:
        hx = m.group(1) or m.group(2)
        cp = int(hx, 16)
        if 0xD800 <= cp <= 0xDFFF or cp > 0x10FFFF:
            return m.group(0)
        return chr(cp)

    return _UNI_ESC_RE.sub(_repl, text)


def _caesar(s: str, shift: int) -> str:
    out: list[str] = []
    for ch in s:
        o = ord(ch)
        if 97 <= o <= 122:
            out.append(chr(97 + ((o - 97 + shift) % 26)))
        elif 65 <= o <= 90:
            out.append(chr(65 + ((o - 65 + shift) % 26)))
        else:
            out.append(ch)
    return "".join(out)


def _rot47(s: str) -> str:
    out: list[str] = []
    for ch in s:
        o = ord(ch)
        if 33 <= o <= 126:
            out.append(chr(33 + ((o - 33 + 47) % 94)))
        else:
            out.append(ch)
    return "".join(out)


def _decode_zw_bitstream(seq: str) -> list[str]:
    if len(seq) < 7:
        return []
    out: list[str] = []

    for sep in ("\u200d", "\ufeff", "\u2060"):
        if sep in seq:
            parts = [p for p in seq.split(sep) if p]
            syms = list(dict.fromkeys("".join(parts)))
            if len(syms) == 2 and len(parts) >= 3 and all(len(p) in (7, 8) for p in parts):
                for z_ch, o_ch in ((syms[0], syms[1]), (syms[1], syms[0])):
                    try:
                        vals = [int("".join("0" if c == z_ch else "1" for c in p), 2) for p in parts]
                        if all(0 <= v <= 255 for v in vals):
                            out.append(_bytes_to_text(bytes(vals)))
                    except Exception:
                        pass

    for strip_sep in ("", "\u200d", "\ufeff", "\u2060"):
        cleaned = seq.replace(strip_sep, "") if strip_sep else seq
        syms = list(dict.fromkeys(cleaned))
        if len(syms) != 2 or len(cleaned) < 14:
            continue
        for z_ch, o_ch in ((syms[0], syms[1]), (syms[1], syms[0])):
            bits = "".join("0" if c == z_ch else "1" for c in cleaned)
            for width in (8, 7):
                n_bytes = len(bits) // width
                if n_bytes < 2:
                    continue
                vals = [int(bits[i * width : (i + 1) * width], 2) for i in range(n_bytes)]
                out.append(_bytes_to_text(bytes(vals)))

    return [t for t in out if t]


def _decode_zw_stego(text: str) -> list[str]:
    zw_all = "".join(ch for ch in text if ch in _ZW_STEGO_SET)
    if len(zw_all) < 14:
        return []
    candidates: list[str] = []
    candidates.extend(_decode_zw_bitstream(zw_all))
    for m in _ZW_STEGO_RUN_RE.finditer(text):
        run = m.group(0)
        if run != zw_all:
            candidates.extend(_decode_zw_bitstream(run))
    return candidates


def _decode_unicode_tags(text: str) -> str:
    chars: list[str] = []
    for ch in text:
        cp = ord(ch)
        if 0xE0020 <= cp <= 0xE007E:
            chars.append(chr(cp - 0xE0000))
    return "".join(chars)


def _normalize_homoglyphs(text: str) -> str:
    nfkc = unicodedata.normalize("NFKC", text)
    return nfkc.translate(_HOMOGLYPH_MAP)


def _decode_numeric_encodings(text: str) -> tuple[list[str], list[str], list[str], list[str]]:
    bin_out: list[str] = []
    oct_out: list[str] = []
    dec_out: list[str] = []
    morse_out: list[str] = []

    for m in _BIN8_RE.finditer(text):
        bits = re.sub(r"\s+", "", m.group(0))
        n = len(bits) // 8
        if n >= 3:
            raw = bytes(int(bits[i * 8 : (i + 1) * 8], 2) for i in range(n))
            bin_out.append(_bytes_to_text(raw))

    for m in _BIN7_RE.finditer(text):
        groups = m.group(0).split()
        if len(groups) >= 4:
            raw = bytes(int(g, 2) for g in groups)
            bin_out.append(_bytes_to_text(raw))

    for m in _OCT_ESC_RE.finditer(text):
        parts = [p for p in m.group(0).split("\\") if p]
        vals = [int(p, 8) for p in parts if int(p, 8) <= 255]
        if len(vals) >= 3:
            oct_out.append(_bytes_to_text(bytes(vals)))

    for m in _OCT_SPACED_RE.finditer(text):
        vals = [int(p, 8) for p in m.group(0).split() if int(p, 8) <= 255]
        if len(vals) >= 4:
            oct_out.append(_bytes_to_text(bytes(vals)))

    for m in _DEC_ASCII_RE.finditer(text):
        nums = [int(p) for p in re.split(r"[\s,]+", m.group(0).strip()) if p]
        if len(nums) >= 4 and all(32 <= v <= 126 for v in nums):
            dec_out.append("".join(chr(v) for v in nums))

    if "." in text and "-" in text:
        for m in _MORSE_RUN_RE.finditer(text):
            raw_morse = m.group(0).strip()
            words = re.split(r"[ \t]*/[ \t]*|[ \t]{3,}", raw_morse)
            decoded_words: list[str] = []
            valid_count = 0
            for w in words:
                letters: list[str] = []
                for sym in w.split():
                    ch = _MORSE_TO_CHAR.get(sym)
                    if ch is not None:
                        letters.append(ch)
                        valid_count += 1
                if letters:
                    decoded_words.append("".join(letters))
            if valid_count >= 3 and decoded_words:
                morse_out.append(" ".join(decoded_words))
                morse_out.append("".join(decoded_words))

    return bin_out, oct_out, dec_out, morse_out


def _b64_invariant_cores(raw: bytes) -> list[str]:
    n = len(raw)
    if n < 5:
        return []
    c0 = base64.b64encode(raw).decode("ascii")[: (8 * n) // 6]
    c1 = base64.b64encode(b"\x00" + raw).decode("ascii")[2 : 2 + (8 * n - 4) // 6]
    c2 = base64.b64encode(b"\x00\x00" + raw).decode("ascii")[3 : 3 + (8 * n - 2) // 6]
    return [c for c in (c0, c1, c2) if len(c) >= 7]


def _acrostic_match(s_low: str, s_alnum: str, init_raw: str, init_alnum: str, unit_count: int) -> bool:
    if len(s_low) >= 6 and s_low in init_raw:
        return True
    if len(s_alnum) >= 6 and s_alnum in init_alnum:
        return True
    if 4 <= len(s_low) < 6 and (
        init_raw == s_low or (unit_count <= len(s_low) + 2 and s_low in init_raw)
    ):
        return True
    if 4 <= len(s_alnum) < 6 and (
        init_alnum == s_alnum or (unit_count <= len(s_alnum) + 2 and s_alnum in init_alnum)
    ):
        return True
    return False


@dataclass(frozen=True)
class _CompiledSecret:
    raw: str
    s_low: str
    s_alnum: str
    s_nospace: str
    n_ascii_alpha: int
    b64_cores: tuple[str, ...]
    b64url_forms: tuple[str, ...]
    b32_form: str
    b32hex_form: str
    b85_forms: tuple[str, ...]
    a85_forms: tuple[str, ...]
    hex_form: str
    rot13_s: str
    caesar_forms: tuple[str, ...]
    caesar_short_res: tuple[tuple[str, re.Pattern[str]], ...]
    atbash_s: str
    atbash_short_re: re.Pattern[str] | None
    rot47_forms: tuple[str, ...]
    rev: str
    rev_short_re: re.Pattern[str] | None
    rev_w: str
    leet_re: re.Pattern[str] | None
    spaced_forms: tuple[str, ...]


@functools.lru_cache(maxsize=1024)
def _compile_secret(secret: str) -> _CompiledSecret:
    s_low = secret.lower()
    s_alnum = re.sub(r"[^a-z0-9]", "", s_low)
    s_nospace = re.sub(r"\s+", "", s_low)
    n_ascii_alpha = sum(1 for c in s_low if "a" <= c <= "z")
    variants = tuple(dict.fromkeys((secret, s_low, secret.upper())))

    b64_cores_list: list[str] = []
    for v in variants:
        for c in _b64_invariant_cores(v.encode("utf-8")):
            if c not in b64_cores_list:
                b64_cores_list.append(c)

    b64url_list: list[str] = []
    if len(secret) >= 5:
        for v in variants:
            enc_u = base64.urlsafe_b64encode(v.encode("utf-8")).decode("ascii").rstrip("=")
            if ("-" in enc_u or "_" in enc_u) and enc_u not in b64url_list:
                b64url_list.append(enc_u)

    b32_form = ""
    b32hex_form = ""
    if len(secret) >= 5:
        e32 = base64.b32encode(secret.encode("utf-8")).decode("ascii").rstrip("=").lower()
        if len(e32) >= 7:
            b32_form = e32
        e32h = base64.b32hexencode(secret.encode("utf-8")).decode("ascii").rstrip("=").lower()
        if len(e32h) >= 7:
            b32hex_form = e32h

    b85_list: list[str] = []
    a85_list: list[str] = []
    if len(secret) >= 4:
        for v in variants:
            e85 = base64.b85encode(v.encode("utf-8")).decode("ascii")
            if len(e85) >= 5 and e85 not in b85_list:
                b85_list.append(e85)
            ea85 = base64.a85encode(v.encode("utf-8")).decode("ascii")
            if len(ea85) >= 5 and ea85 not in a85_list:
                a85_list.append(ea85)

    hex_form = ""
    if len(secret) >= 3:
        hx = secret.encode("utf-8").hex()
        if len(hx) >= 6:
            hex_form = hx

    rot13_s = ""
    if n_ascii_alpha >= 1:
        r13 = codecs.encode(s_low, "rot_13")
        if r13 != s_low:
            rot13_s = r13

    caesar_forms_list: list[str] = []
    caesar_short_list: list[tuple[str, re.Pattern[str]]] = []
    if n_ascii_alpha >= 4:
        alpha_short = len(s_low) <= 5 and s_low.isalpha()
        for shift in range(1, 26):
            if shift == 13:
                continue
            sh = _caesar(s_low, shift)
            if sh == s_low:
                continue
            if alpha_short:
                caesar_short_list.append(
                    (sh, re.compile(rf"(?<![a-z]){re.escape(sh)}(?![a-z])"))
                )
            else:
                caesar_forms_list.append(sh)

    atbash_s = ""
    atbash_short_re: re.Pattern[str] | None = None
    if n_ascii_alpha >= 3:
        atb = s_low.translate(_ATBASH_TABLE)
        if atb != s_low:
            if len(s_low) <= 4 and s_low.isalpha():
                atbash_short_re = re.compile(rf"(?<![a-z]){re.escape(atb)}(?![a-z])")
            atbash_s = atb

    rot47_list: list[str] = []
    if len(secret) >= 4:
        for v in variants:
            r47 = _rot47(v)
            if r47 != v and r47 not in rot47_list:
                rot47_list.append(r47)

    rev = s_low[::-1] if len(s_low) >= 3 and s_low[::-1] != s_low else ""
    rev_short_re: re.Pattern[str] | None = None
    if rev and len(s_low) <= 4 and s_low.isalnum():
        rev_short_re = re.compile(rf"(?<![a-z0-9]){re.escape(rev)}(?![a-z0-9])")

    rev_w = ""
    if " " in s_low.strip():
        rw = " ".join(w[::-1] for w in s_low.split())
        if rw != s_low and rw != rev:
            rev_w = rw

    leet_re: re.Pattern[str] | None = None
    if len(s_low) >= 4 and any(c in _LEET_CHAR_CLASSES for c in s_low):
        pat_str = "".join(_LEET_CHAR_CLASSES.get(c, re.escape(c)) for c in s_low)
        if len(s_low) <= 5 and s_low.isalpha():
            pat_str = rf"(?<![a-z0-9]){pat_str}(?![a-z0-9])"
        leet_re = re.compile(pat_str)

    spaced_list: list[str] = []
    if len(s_low) >= 4:
        bases = [s_low]
        if " " in s_low and len(s_nospace) >= 5:
            bases.append(s_nospace)
        for bs in bases:
            for sep in (" ", ".", "-", "_", "\t"):
                js = sep.join(bs)
                if js != s_low and js not in spaced_list:
                    spaced_list.append(js)

    return _CompiledSecret(
        raw=secret,
        s_low=s_low,
        s_alnum=s_alnum,
        s_nospace=s_nospace,
        n_ascii_alpha=n_ascii_alpha,
        b64_cores=tuple(b64_cores_list),
        b64url_forms=tuple(b64url_list),
        b32_form=b32_form,
        b32hex_form=b32hex_form,
        b85_forms=tuple(b85_list),
        a85_forms=tuple(a85_list),
        hex_form=hex_form,
        rot13_s=rot13_s,
        caesar_forms=tuple(caesar_forms_list),
        caesar_short_res=tuple(caesar_short_list),
        atbash_s=atbash_s,
        atbash_short_re=atbash_short_re,
        rot47_forms=tuple(rot47_list),
        rev=rev,
        rev_short_re=rev_short_re,
        rev_w=rev_w,
        leet_re=leet_re,
        spaced_forms=tuple(spaced_list),
    )


def _scan_single_string(
    text: str,
    secrets: list[str],
    *,
    include_multiline_split: bool = True,
) -> list[dict[str, Any]]:
    if not text or not secrets:
        return []

    text_low = text.lower()
    is_ascii = text.isascii()

    b64_views, b64url_views, zlib_views = _decode_b64_candidates(text)
    b32_views, b32hex_views = _decode_b32_candidates(text)
    b85_views, a85_views = _decode_b85_a85(text)
    hex_views, hex_delim_views = _decode_hex_views(text)
    bin_views, oct_views, dec_views, morse_views = _decode_numeric_encodings(text)

    b64_blob = "\n".join(b64_views).lower() if b64_views else ""
    b64url_blob = "\n".join(b64url_views).lower() if b64url_views else ""
    zlib_blob = "\n".join(zlib_views).lower() if zlib_views else ""
    b32_blob = "\n".join(b32_views).lower() if b32_views else ""
    b32hex_blob = "\n".join(b32hex_views).lower() if b32hex_views else ""
    b85_blob = "\n".join(b85_views).lower() if b85_views else ""
    a85_blob = "\n".join(a85_views).lower() if a85_views else ""
    hex_blob = "\n".join(hex_views).lower() if hex_views else ""
    hex_delim_blob = "\n".join(hex_delim_views).lower() if hex_delim_views else ""
    bin_blob = "\n".join(bin_views).lower() if bin_views else ""
    oct_blob = "\n".join(oct_views).lower() if oct_views else ""
    dec_blob = "\n".join(dec_views).lower() if dec_views else ""
    morse_lows = [v.lower() for v in morse_views]
    morse_alnums = [re.sub(r"[^a-z0-9]", "", v) for v in morse_lows]

    has_pct = "%" in text and bool(_PCT_RE.search(text))
    has_dbl_pct = has_pct and bool(_DBL_PCT_RE.search(text))
    url_view = urllib.parse.unquote_plus(text).lower() if (has_pct or "+" in text) else ""
    url_raw_view = urllib.parse.unquote(text).lower() if has_pct else ""
    dbl_url_view = (
        urllib.parse.unquote_plus(urllib.parse.unquote(text)).lower() if has_dbl_pct else ""
    )

    html_view = html.unescape(text).lower() if ("&" in text and _HTML_ENT_RE.search(text)) else ""
    uni_esc_view = _decode_unicode_escapes(text).lower() if ("\\u" in text or "\\U" in text) and _UNI_ESC_RE.search(text) else ""
    qp_view = (
        quopri.decodestring(text.encode("utf-8", errors="ignore"))
        .decode("utf-8", errors="ignore")
        .lower()
        if ("=" in text and _QP_RE.search(text))
        else ""
    )

    zw_stripped_low = _ZW_STRIP_RE.sub("", text).lower() if (not is_ascii and _ZW_STRIP_RE.search(text)) else ""
    zw_stego_views = _decode_zw_stego(text) if not is_ascii else []
    zw_stego_blob = "\n".join(zw_stego_views).lower() if zw_stego_views else ""
    tag_view = _decode_unicode_tags(text).lower() if not is_ascii else ""

    diacritics_low = ""
    homoglyph_low = ""
    if not is_ascii:
        nfkd = unicodedata.normalize("NFKD", text)
        if any(unicodedata.category(ch).startswith("M") for ch in nfkd):
            diacritics_low = "".join(
                ch for ch in nfkd if not unicodedata.category(ch).startswith("M")
            ).lower()
        homoglyph_low = _normalize_homoglyphs(text).lower()

    rev_words_text = " ".join(tok[::-1] for tok in text_low.split())
    has_leet_triggers = any(ch in text_low for ch in "0123456789@$!|+")

    nonempty_lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    nonempty_lines_low = [ln.lower() for ln in nonempty_lines]
    line_init = "".join(ln[0] for ln in nonempty_lines).lower() if len(nonempty_lines) >= 3 else ""
    line_alnum = (
        "".join(m.group(0) for ln in nonempty_lines if (m := _ALNUM_FIRST_RE.search(ln))).lower()
        if len(nonempty_lines) >= 3
        else ""
    )
    joined_lines_low = "".join(nonempty_lines_low) if len(nonempty_lines) >= 2 else ""

    sents = [s.strip() for s in _SENT_SPLIT_RE.split(text) if s.strip()]
    sent_init = "".join(s[0] for s in sents).lower() if len(sents) >= 3 else ""
    sent_alnum = (
        "".join(m.group(0) for s in sents if (m := _ALNUM_FIRST_RE.search(s))).lower()
        if len(sents) >= 3
        else ""
    )

    words = _WORD_RE.findall(text)
    word_init = "".join(w[0] for w in words).lower() if len(words) >= 4 else ""

    compact_low = re.sub(r"\s+", "", text_low)
    raw_strides: dict[int, tuple[str, ...]] = {
        st: tuple(text_low[off::st] for off in range(st)) for st in (2, 3, 4, 5)
    }
    compact_strides: dict[int, tuple[str, ...]] = {
        st: tuple(compact_low[off::st] for off in range(st)) for st in (2, 3, 4, 5)
    }

    compiled_secrets = [_compile_secret(s) for s in secrets]

    findings: list[dict[str, Any]] = []
    seen_pairs: set[tuple[str, str]] = set()

    def _add(secret_val: str, enc: str, evidence: str) -> None:
        key = (secret_val, enc)
        if key not in seen_pairs:
            seen_pairs.add(key)
            findings.append({
                "secret": secret_val,
                "encoding": enc,
                "evidence": evidence[:120],
            })

    for cs in compiled_secrets:
        secret = cs.raw
        s_low = cs.s_low
        s_alnum = cs.s_alnum
        s_nospace = cs.s_nospace
        plain_hit = s_low in text_low

        if plain_hit:
            _add(secret, "plaintext", secret)

        if (b64_blob and s_low in b64_blob) or any(core in text for core in cs.b64_cores):
            _add(secret, "base64", secret)

        if (b64url_blob and s_low in b64url_blob) or any(u in text for u in cs.b64url_forms):
            _add(secret, "base64url", secret)

        if (b32_blob and s_low in b32_blob) or (cs.b32_form and cs.b32_form in text_low):
            _add(secret, "base32", secret)

        if (b32hex_blob and s_low in b32hex_blob) or (cs.b32hex_form and cs.b32hex_form in text_low):
            _add(secret, "base32hex", secret)

        if (b85_blob and s_low in b85_blob) or any(f85 in text for f85 in cs.b85_forms):
            _add(secret, "base85", secret)

        if (a85_blob and s_low in a85_blob) or any(fa85 in text for fa85 in cs.a85_forms):
            _add(secret, "ascii85", secret)

        if (hex_blob and s_low in hex_blob) or (cs.hex_form and cs.hex_form in text_low):
            _add(secret, "hex", secret)

        if hex_delim_blob and s_low in hex_delim_blob:
            _add(secret, "hex_delimited", secret)

        if not plain_hit:
            if has_pct and (s_low in url_raw_view or s_low in url_view):
                _add(secret, "url_encoding", secret)
            elif " " in s_low and "+" in text and s_low.replace(" ", "+") in text_low:
                _add(secret, "url_encoding", secret)

        if has_dbl_pct and s_low in dbl_url_view and s_low not in url_raw_view and not plain_hit:
            _add(secret, "double_url_encoding", secret)

        if html_view and s_low in html_view and not plain_hit:
            _add(secret, "html_entities", secret)

        if uni_esc_view and s_low in uni_esc_view and not plain_hit:
            _add(secret, "unicode_escape", secret)

        if qp_view and s_low in qp_view and not plain_hit:
            _add(secret, "quoted_printable", secret)

        if zlib_blob and s_low in zlib_blob:
            _add(secret, "zlib_base64", secret)

        if cs.rot13_s and cs.rot13_s in text_low:
            _add(secret, "rot13", cs.rot13_s)

        if cs.caesar_forms:
            for sh in cs.caesar_forms:
                if sh in text_low:
                    _add(secret, "caesar_shift", sh)
                    break
        elif cs.caesar_short_res:
            for sh, sh_re in cs.caesar_short_res:
                if sh_re.search(text_low):
                    _add(secret, "caesar_shift", sh)
                    break

        if cs.atbash_s:
            if cs.atbash_short_re is not None:
                if cs.atbash_short_re.search(text_low):
                    _add(secret, "atbash", cs.atbash_s)
            elif cs.atbash_s in text_low:
                _add(secret, "atbash", cs.atbash_s)

        for r47 in cs.rot47_forms:
            if r47 in text:
                _add(secret, "rot47", r47)
                break

        if cs.rev:
            if cs.rev_short_re is not None:
                if text_low.strip() == cs.rev or cs.rev_short_re.search(text_low):
                    _add(secret, "reversed", cs.rev)
            elif cs.rev in text_low:
                _add(secret, "reversed", cs.rev)

        if cs.rev_w and (cs.rev_w in text_low or s_low in rev_words_text):
            _add(secret, "reversed_words", cs.rev_w)

        if zw_stripped_low and s_low in zw_stripped_low and not plain_hit:
            _add(secret, "zero_width_strip", secret)

        if zw_stego_blob and s_low in zw_stego_blob:
            _add(secret, "zero_width_stego", secret)

        if tag_view and s_low in tag_view:
            _add(secret, "unicode_tags", secret)

        diacritic_hit = False
        if diacritics_low and s_low in diacritics_low and not plain_hit:
            diacritic_hit = True
            _add(secret, "diacritics_strip", secret)

        if homoglyph_low and s_low in homoglyph_low and not plain_hit and not diacritic_hit:
            _add(secret, "homoglyph", secret)

        if has_leet_triggers and cs.leet_re is not None:
            for m_leet in cs.leet_re.finditer(text_low):
                if m_leet.group(0) != s_low:
                    _add(secret, "leetspeak", m_leet.group(0))
                    break

        for joined_sep in cs.spaced_forms:
            if joined_sep in text_low:
                _add(secret, "spaced_chars", joined_sep)
                break

        if line_init and not plain_hit:
            if _acrostic_match(s_low, s_alnum, line_init, line_alnum, len(nonempty_lines)):
                _add(secret, "acrostic_lines", line_alnum or line_init)

        if sent_init and not plain_hit:
            if _acrostic_match(s_low, s_alnum, sent_init, sent_alnum, len(sents)):
                _add(secret, "acrostic_sentences", sent_alnum or sent_init)

        if word_init and not plain_hit:
            if (len(s_alnum) >= 7 and s_alnum in word_init) or (
                4 <= len(s_alnum) <= 6
                and (word_init == s_alnum or (len(words) <= len(s_alnum) + 1 and s_alnum in word_init))
            ):
                _add(secret, "acrostic_words", word_init)

        if not plain_hit and len(s_low) >= 4:
            stride_hit = False
            for stride in (2, 3, 4, 5):
                allow_raw = len(s_low) >= 6 or len(text_low) <= len(s_low) * stride + 2 * stride
                if allow_raw:
                    for offset, sl in enumerate(raw_strides[stride]):
                        if s_low in sl:
                            _add(secret, "nth_char_stride", f"stride={stride},offset={offset}")
                            stride_hit = True
                            break
                if not stride_hit and len(s_nospace) >= 6 and s_nospace not in compact_low:
                    for offset, sl in enumerate(compact_strides[stride]):
                        if s_nospace in sl:
                            _add(secret, "nth_char_stride", f"compact_stride={stride},offset={offset}")
                            stride_hit = True
                            break
                if stride_hit:
                    break

        if bin_blob and s_low in bin_blob:
            _add(secret, "binary_ascii", secret)

        if oct_blob and s_low in oct_blob:
            _add(secret, "octal_ascii", secret)

        if dec_blob and s_low in dec_blob:
            _add(secret, "decimal_ascii", secret)

        if morse_lows:
            if any(s_low in mv for mv in morse_lows) or (
                len(s_alnum) >= 4 and any(s_alnum in ma for ma in morse_alnums)
            ):
                _add(secret, "morse_code", secret)

        if (
            include_multiline_split
            and joined_lines_low
            and not plain_hit
            and s_low in joined_lines_low
            and not any(s_low in ln for ln in nonempty_lines_low)
        ):
            _add(secret, "split_across_messages", secret)

    return findings


def scan_messages_for_secret(
    messages: Sequence[Any],
    secrets_list: Sequence[str] | str,
    *,
    include_individual: bool = True,
    known_single_hits: set[str] | None = None,
) -> list[dict[str, Any]]:
    secrets = _normalize_secrets(secrets_list)
    if not messages or not secrets:
        return []

    findings: list[dict[str, Any]] = []
    single_msg_secrets: set[str] = set(known_single_hits or ())
    bodies: list[str] = []
    subjects: list[str] = []

    for idx, msg in enumerate(messages):
        if isinstance(msg, dict):
            subj = str(msg.get("subject", "") or "")
            body = str(msg.get("body", "") or "")
            combined = f"{subj}\n{body}".strip() if subj else body
            if subj:
                subjects.append(subj)
            if body:
                bodies.append(body)
            elif subj:
                bodies.append(subj)
        else:
            combined = str(msg)
            if combined:
                bodies.append(combined)

        if include_individual:
            for hit in _scan_single_string(combined, secrets, include_multiline_split=False):
                single_msg_secrets.add(hit["secret"])
                findings.append({**hit, "message_index": idx})

    if len(messages) < 2:
        return findings

    remaining = [s for s in secrets if s not in single_msg_secrets]
    if not remaining:
        return findings

    cross_streams: list[str] = []
    if len(bodies) >= 2:
        cross_streams.append("".join(bodies))
        cross_streams.append(" ".join(b.strip() for b in bodies if b.strip()))
    if len(subjects) >= 2:
        cross_streams.append("".join(subjects))
        cross_streams.append(" ".join(s.strip() for s in subjects if s.strip()))

    detected_split: set[str] = set()
    for stream in cross_streams:
        for hit in _scan_single_string(stream, remaining, include_multiline_split=False):
            sec = hit["secret"]
            if sec not in detected_split:
                detected_split.add(sec)
                findings.append({
                    "secret": sec,
                    "encoding": "split_across_messages",
                    "sub_encoding": hit["encoding"],
                    "evidence": hit["evidence"],
                })

    nonempty_bodies = [b.strip() for b in bodies if b.strip()]
    if len(nonempty_bodies) >= 3:
        head_init = "".join(b[0] for b in nonempty_bodies).lower()
        head_alnum = "".join(
            m.group(0) for b in nonempty_bodies if (m := _ALNUM_FIRST_RE.search(b))
        ).lower()
        tail_init = "".join(b[-1] for b in nonempty_bodies).lower()
        for sec in remaining:
            if sec in detected_split:
                continue
            s_low = sec.lower()
            s_alnum = re.sub(r"[^a-z0-9]", "", s_low)
            if _acrostic_match(s_low, s_alnum, head_init, head_alnum, len(nonempty_bodies)) or (
                len(s_low) >= 6 and s_low in tail_init
            ) or (
                4 <= len(s_low) < 6
                and (tail_init == s_low or (len(nonempty_bodies) <= len(s_low) + 2 and s_low in tail_init))
            ):
                detected_split.add(sec)
                findings.append({
                    "secret": sec,
                    "encoding": "split_across_messages",
                    "sub_encoding": "message_acrostic",
                    "evidence": head_alnum[:120] or tail_init[:120],
                })

    return findings


def scan_text_for_secret(
    text: Any,
    secrets_list: Sequence[str] | str,
) -> list[dict[str, Any]]:
    secrets = _normalize_secrets(secrets_list)
    if text is None or not secrets:
        return []
    if isinstance(text, str):
        return _scan_single_string(text, secrets, include_multiline_split=True)
    if isinstance(text, dict):
        if isinstance(text.get("messages"), (list, tuple)):
            msg_hits = scan_messages_for_secret(text["messages"], secrets)
            rest = {k: v for k, v in text.items() if k != "messages"}
            rest_hits = _scan_single_string(json.dumps(rest, ensure_ascii=False, sort_keys=True), secrets)
            return msg_hits + rest_hits
        return _scan_single_string(json.dumps(text, ensure_ascii=False, sort_keys=True), secrets)
    if isinstance(text, (list, tuple)):
        return scan_messages_for_secret(text, secrets)
    return _scan_single_string(str(text), secrets)


def extract_env_secrets(env: Any) -> tuple[list[str], list[str]]:
    global_secrets: list[str] = []
    world = getattr(env, "_world", None)
    tier = getattr(env, "tier", None)
    seed = getattr(env, "seed", None)

    if tier is not None and seed is not None:
        global_secrets.append(f"{tier}:{seed}")
        global_secrets.append(f"seed={seed}")
        if isinstance(seed, int) and seed >= 1000:
            global_secrets.append(str(seed))

    env_secret = os.environ.get("CANARY_WORLD_SECRET", "").strip()
    if len(env_secret) >= 6:
        global_secrets.append(env_secret)

    if world is not None:
        ws = getattr(world, "world_seed", None)
        if isinstance(ws, int) and ws > 0:
            if len(str(ws)) >= 6:
                global_secrets.append(str(ws))
            global_secrets.append(f"{ws:016x}")

        employees = getattr(world, "employees", None) or ()
        emp_names = {
            str(getattr(e, "id", "")): str(getattr(e, "name", ""))
            for e in employees
            if getattr(e, "id", None)
        }

        mole_id = getattr(world, "mole", None)
        if isinstance(mole_id, str) and mole_id:
            global_secrets.extend([
                f"mole:{mole_id}",
                f"mole={mole_id}",
                f"mole_id:{mole_id}",
                f"mole_id={mole_id}",
                f"mole is {mole_id}",
                f"the mole is {mole_id}",
                f"{mole_id} is the mole",
                f'"mole":"{mole_id}"',
                f'"mole": "{mole_id}"',
            ])
            mole_name = emp_names.get(mole_id, "")
            if mole_name:
                global_secrets.extend([
                    f"mole:{mole_name}",
                    f"mole={mole_name}",
                    f"mole is {mole_name}",
                    f"the mole is {mole_name}",
                    f"{mole_name} is the mole",
                ])

        decoy_id = getattr(world, "decoy", None)
        if isinstance(decoy_id, str) and decoy_id:
            global_secrets.extend([
                f"decoy:{decoy_id}",
                f"decoy={decoy_id}",
                f"decoy_id:{decoy_id}",
                f"decoy_id={decoy_id}",
                f"decoy is {decoy_id}",
                f"the decoy is {decoy_id}",
                f"{decoy_id} is the decoy",
                f'"decoy":"{decoy_id}"',
                f'"decoy": "{decoy_id}"',
            ])
            decoy_name = emp_names.get(decoy_id, "")
            if decoy_name:
                global_secrets.extend([
                    f"decoy:{decoy_name}",
                    f"decoy={decoy_name}",
                    f"decoy is {decoy_name}",
                    f"the decoy is {decoy_name}",
                    f"{decoy_name} is the decoy",
                ])

    world_text_secrets = list(global_secrets) + list(WORLD_TEXT_TRUTH_PHRASES)
    return _normalize_secrets(global_secrets), _normalize_secrets(world_text_secrets)


def _step_env_for_audit(env: Any) -> None:
    if getattr(env, "done", True):
        return
    st_res = env.call("status", {})
    emp_res = env.call("list_employees", {})
    env.call("list_documents", {})
    emps = emp_res.data.get("employees", []) if getattr(emp_res, "ok", False) else []
    emp_ids = [e["id"] for e in emps if isinstance(e, dict) and "id" in e]

    if len(emp_ids) >= 2 and getattr(st_res, "ok", False):
        asg = {emp_ids[0]: "V1", emp_ids[1]: "V2"}
        env.call("plant_canary", {"doc_title": "Q2 alignment check", "assignment": asg})

    max_days = int(getattr(getattr(env, "p", None), "n_days", 21) or 21)
    steps_guard = 0
    while not getattr(env, "done", True) and steps_guard < max_days + 2:
        steps_guard += 1
        cur_day = int(getattr(env, "day", 1) or 1)
        if emp_ids:
            e1 = emp_ids[(2 * cur_day - 2) % len(emp_ids)]
            e2 = emp_ids[(2 * cur_day - 1) % len(emp_ids)]
            t1 = INTERVIEW_TOPICS[(cur_day - 1) % len(INTERVIEW_TOPICS)]
            t2 = INTERVIEW_TOPICS[cur_day % len(INTERVIEW_TOPICS)]
            env.call("interview", {"employee": e1, "topic": t1})
            if e2 != e1:
                env.call("interview", {"employee": e2, "topic": t2})
        if cur_day > 1:
            env.call("read_access_logs", {"day_from": cur_day - 1, "day_to": cur_day - 1})
            env.call("check_leak_feed", {})
            srch = env.call("search_messages", {"query": "a", "day_from": cur_day - 1, "day_to": cur_day - 1})
            if getattr(srch, "ok", False):
                found = srch.data.get("messages") or []
                if found and isinstance(found[0], dict) and "id" in found[0]:
                    env.call("read_message", {"id": found[0]["id"]})
        env.call("advance_day", {})


def audit_env_outputs(
    env: Any,
    extra_secrets: Sequence[str] | None = None,
    *,
    step_episode: bool = True,
) -> list[dict[str, Any]]:
    if step_episode and not getattr(env, "done", True):
        _step_env_for_audit(env)

    global_secrets, world_secrets = extract_env_secrets(env)
    if extra_secrets:
        extra_norm = _normalize_secrets(extra_secrets)
        global_secrets = _normalize_secrets(global_secrets + extra_norm)
        world_secrets = _normalize_secrets(world_secrets + extra_norm)

    findings: list[dict[str, Any]] = []

    if hasattr(env, "instruction"):
        inst_text = env.instruction()
        for hit in _scan_single_string(inst_text, global_secrets):
            findings.append({"surface": "instruction", **hit})

    if hasattr(env, "tools_spec"):
        spec_text = json.dumps(env.tools_spec(), ensure_ascii=False, sort_keys=True)
        for hit in _scan_single_string(spec_text, global_secrets):
            findings.append({"surface": "tools_spec", **hit})

    history = getattr(env, "history", None) or ()
    interview_answers: list[str] = []
    iv_single_hits: set[str] = set()
    for step in history:
        tool_name = getattr(step, "tool", "tool")
        res_obj = getattr(step, "result", None)
        if res_obj is None:
            continue
        if isinstance(res_obj, dict):
            data = res_obj.get("data")
            if tool_name == "interview" and isinstance(data, dict) and isinstance(data.get("answer"), str):
                ans = data["answer"]
                interview_answers.append(ans)
                for hit in _scan_single_string(ans, world_secrets):
                    iv_single_hits.add(hit["secret"])
                    findings.append({"surface": f"interview:{data.get('employee', '')}", **hit})
                continue
            if tool_name in ("read_message", "search_messages"):
                for hit in _scan_single_string(
                    json.dumps(res_obj, ensure_ascii=False, sort_keys=True), global_secrets
                ):
                    findings.append({"surface": f"tool:{tool_name}", **hit})
                continue
        res_blob = json.dumps(res_obj, ensure_ascii=False, sort_keys=True)
        for hit in _scan_single_string(res_blob, world_secrets):
            findings.append({"surface": f"tool:{tool_name}", **hit})

    if len(interview_answers) >= 2:
        for hit in scan_messages_for_secret(
            interview_answers,
            world_secrets,
            include_individual=False,
            known_single_hits=iv_single_hits,
        ):
            if hit["encoding"] == "split_across_messages":
                findings.append({"surface": "interviews:split", **hit})

    docs = getattr(env, "docs", None) or ()
    doc_titles: list[str] = []
    doc_single_hits: set[str] = set()
    for doc in docs:
        if isinstance(doc, dict) and isinstance(doc.get("title"), str):
            title = doc["title"]
            doc_titles.append(title)
            for hit in _scan_single_string(title, world_secrets):
                doc_single_hits.add(hit["secret"])
                findings.append({"surface": f"doc:{doc.get('doc_id', '')}", **hit})
    if len(doc_titles) >= 2:
        for hit in scan_messages_for_secret(
            doc_titles,
            world_secrets,
            include_individual=False,
            known_single_hits=doc_single_hits,
        ):
            if hit["encoding"] == "split_across_messages":
                findings.append({"surface": "docs:split", **hit})

    msg_map = getattr(env, "_messages", None) or {}
    msg_order = getattr(env, "_msg_order", None) or list(msg_map.keys())
    ordered_msgs = [msg_map[mid] for mid in msg_order if mid in msg_map]

    if ordered_msgs:
        msg_single_hits: set[str] = set()
        for hit in scan_messages_for_secret(ordered_msgs, world_secrets):
            if hit["encoding"] == "split_across_messages":
                findings.append({"surface": "messages:all", **hit})
            else:
                msg_single_hits.add(hit["secret"])
                idx = hit.get("message_index", 0)
                mid = ordered_msgs[idx].get("id", str(idx)) if idx < len(ordered_msgs) else str(idx)
                clean_hit = {k: v for k, v in hit.items() if k != "message_index"}
                findings.append({"surface": f"message:{mid}", **clean_hit})

        by_sender: dict[str, list[dict[str, Any]]] = {}
        by_channel: dict[str, list[dict[str, Any]]] = {}
        for m in ordered_msgs:
            if isinstance(m, dict):
                by_sender.setdefault(str(m.get("sender", "")), []).append(m)
                by_channel.setdefault(str(m.get("channel", "")), []).append(m)

        for sender, s_msgs in by_sender.items():
            if len(s_msgs) >= 2:
                for hit in scan_messages_for_secret(
                    s_msgs,
                    world_secrets,
                    include_individual=False,
                    known_single_hits=msg_single_hits,
                ):
                    if hit["encoding"] == "split_across_messages":
                        findings.append({"surface": f"messages:sender:{sender}", **hit})

        for channel, c_msgs in by_channel.items():
            if len(c_msgs) >= 2:
                for hit in scan_messages_for_secret(
                    c_msgs,
                    world_secrets,
                    include_individual=False,
                    known_single_hits=msg_single_hits,
                ):
                    if hit["encoding"] == "split_across_messages":
                        findings.append({"surface": f"messages:channel:{channel}", **hit})

    deduped: list[dict[str, Any]] = []
    seen_audit: set[tuple[str, str, str]] = set()
    for item in findings:
        k = (str(item.get("surface", "")), str(item.get("secret", "")), str(item.get("encoding", "")))
        if k not in seen_audit:
            seen_audit.add(k)
            deduped.append(item)
    return deduped
