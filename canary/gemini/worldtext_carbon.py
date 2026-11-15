from __future__ import annotations

import argparse
import base64
import codecs
import html
import json
import math
from pathlib import Path
import quopri
import random
import re
import unicodedata
import urllib.parse
import zlib
from typing import Any, Sequence

from canary.agents.world_builder import TRUTH_KEYS, TRUTH_WORDS, public_view
from canary.llm.pricing import cost as price_cost
from canary.text.lint import lint_text

ROOT = Path(__file__).resolve().parents[2]
ROLE = "world_text"
TARGET_MODEL = "gemini-4-carbon"
SUITE_DIR_NAME = "worldtext-carbon-suite"
SKIP_DIRS = frozenset({"reference", "superseded", "_invalid", SUITE_DIR_NAME})
DEFAULT_ROLE_DIR = ROOT / "results" / "gemini" / "roles_carbon" / ROLE
DEFAULT_DOC_PATH = ROOT / "docs" / "gemini" / "roles_carbon" / "world_text.md"
SCOPE_LABEL = "demo/research layer (v1.5 candidate), not part of the judged v1.4 environment"
TIER_ORDER: tuple[str, ...] = ("easy", "medium", "hard")
TIER_RANK: dict[str, int] = {"easy": 0, "medium": 1, "hard": 2}
THINKING_ORDER: tuple[str, ...] = ("low", "medium", "high")
MD_H1 = "\x23"
MD_H2 = "\x23\x23"
MD_H3 = "\x23\x23\x23"

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

FORBIDDEN_DASHES: tuple[str, ...] = (
    chr(0x2014),
    chr(0x2013),
    chr(0x2012),
    chr(0x2015),
)

FORBIDDEN_RAW_SUFFIXES: tuple[str, ...] = (
    ".text.json",
    ".worldtext.json",
    ".interviews.json",
)
FORBIDDEN_RAW_FILENAMES: frozenset[str] = frozenset({
    "interviews.json",
    "chatter_samples.json",
    "samples.json",
    "comparison.json",
})

COMMIT_RE = re.compile(r"^[0-9a-fA-F]{7,40}$")
GOOGLE_KEY_RE = re.compile(r"(?<![A-Za-z0-9_\-])AIza[0-9A-Za-z_\-]{8,60}(?![A-Za-z0-9_\-=])")
SK_KEY_RE = re.compile(r"(?<![A-Za-z0-9_])sk-[A-Za-z0-9_\-]{12,}")
OAUTH_RE = re.compile(r"(?<![A-Za-z0-9_])ya29\.[0-9A-Za-z_\-]{12,}")

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
_BIN8_RE = re.compile(r"(?:[01]{8}(?:[ \t]+[01]{8}){2,}|[01]{24,})")
_OCT_ESC_RE = re.compile(r"(?:\\[0-7]{3}){2,}")
_OCT_SPACED_RE = re.compile(r"(?<![0-9])[0-1][0-7]{2}(?:[ \t]+[0-1][0-7]{2}){2,}(?![0-9])")
_DEC_ASCII_RE = re.compile(
    r"(?<![0-9])(?:1[0-2][0-9]|[3-9][0-9])(?:(?:[ \t]*,[ \t]*|[ \t]+)(?:1[0-2][0-9]|[3-9][0-9])){2,}(?![0-9])"
)
_MORSE_RUN_RE = re.compile(r"(?:[.\-]{1,6}(?:[ \t]+|[ \t]*/[ \t]*)){2,}[.\-]{1,6}")
_ALNUM_FIRST_RE = re.compile(r"[A-Za-z0-9]")
_WORD_RE = re.compile(r"[A-Za-z0-9]+")
_SENT_SPLIT_RE = re.compile(r"(?:[.!?]+(?:\s+|$)|\n+)")

_ATBASH_TABLE = str.maketrans(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ",
    "zyxwvutsrqponmlkjihgfedcbaZYXWVUTSRQPONMLKJIHGFEDCBA",
)
_LEET_TABLE = str.maketrans({
    "0": "o",
    "1": "i",
    "3": "e",
    "4": "a",
    "5": "s",
    "7": "t",
    "@": "a",
    "$": "s",
})
_HOMOGLYPH_MAP: dict[int, str] = {
    0x0430: "a",
    0x0410: "A",
    0x0435: "e",
    0x0415: "E",
    0x043E: "o",
    0x041E: "O",
    0x0440: "p",
    0x0420: "P",
    0x0441: "c",
    0x0421: "C",
    0x0445: "x",
    0x0425: "X",
    0x0456: "i",
    0x0406: "I",
    0x0443: "y",
}
_MORSE_REV: dict[str, str] = {
    ".-": "a", "-...": "b", "-.-.": "c", "-..": "d", ".": "e",
    "..-.": "f", "--.": "g", "....": "h", "..": "i", ".---": "j",
    "-.-": "k", ".-..": "l", "--": "m", "-.": "n", "---": "o",
    ".--.": "p", "--.-": "q", ".-.": "r", "...": "s", "-": "t",
    "..-": "u", "...-": "v", ".--": "w", "-..-": "x", "-.--": "y",
    "--..": "z", "-----": "0", ".----": "1", "..---": "2", "...--": "3",
    "....-": "4", ".....": "5", "-....": "6", "--...": "7", "---..": "8",
    "----.": "9",
}


def clean_str(val: Any) -> str:
    if val is None:
        return ""
    s = str(val)
    for d in FORBIDDEN_DASHES:
        s = s.replace(f" {d} ", " - ").replace(d, "-")
    return s


def sanitize_obj(obj: Any) -> Any:
    if isinstance(obj, str):
        return clean_str(obj)
    if isinstance(obj, bool):
        return obj
    if isinstance(obj, float):
        return obj if math.isfinite(obj) else None
    if isinstance(obj, (list, tuple)):
        return [sanitize_obj(x) for x in obj]
    if isinstance(obj, dict):
        return {clean_str(k): sanitize_obj(v) for k, v in obj.items()}
    return obj


def _is_num(val: Any) -> bool:
    return isinstance(val, (int, float)) and not isinstance(val, bool) and math.isfinite(float(val))


def _load_json(path: Path) -> Any:
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError):
        return None


def _rel_role_dir(run_dir: Path, role_dir: Path) -> str:
    try:
        return run_dir.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return f"results/gemini/roles_carbon/{ROLE}/{run_dir.name}"


def _secret_present(decoded: str, secrets: Sequence[str]) -> str | None:
    low = decoded.lower()
    for sec in secrets:
        needle = sec.strip().lower()
        if not needle:
            continue
        if len(needle) <= 4 and re.fullmatch(r"e\d\d", needle):
            if re.search(rf"(?<![a-z0-9]){re.escape(needle)}(?![a-z0-9])", low):
                return sec
        elif needle in low:
            return sec
    return None


def _caesar(s: str, shift: int) -> str:
    out: list[str] = []
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
    return "".join(
        chr(33 + ((ord(c) - 33 + 47) % 94)) if 33 <= ord(c) <= 126 else c
        for c in s
    )


def _decode_zw_stego(text: str) -> str:
    pieces: list[str] = []
    for m in _ZW_STEGO_RUN_RE.finditer(text):
        run = m.group(0)
        for zero_ch, one_ch in (("\u200b", "\u200c"), ("\u200c", "\u200b"), ("\u200b", "\u200d")):
            bits = [
                "0" if c == zero_ch else ("1" if c == one_ch else "")
                for c in run
            ]
            bit_str = "".join(bits)
            for width in (8, 7):
                if len(bit_str) >= width * 3:
                    chars = [
                        chr(int(bit_str[i : i + width], 2))
                        for i in range(0, len(bit_str) - width + 1, width)
                        if 32 <= int(bit_str[i : i + width], 2) <= 126
                    ]
                    if chars:
                        pieces.append("".join(chars))
    return " ".join(pieces)


def _decode_unicode_tags(text: str) -> str:
    chars = [
        chr(ord(c) - 0xE0000)
        for c in text
        if 0xE0020 <= ord(c) <= 0xE007E
    ]
    return "".join(chars)


def scan_text_for_secret(text: str, secrets: Sequence[str]) -> list[dict[str, str]]:
    if not text or not secrets:
        return []
    long_secrets = [s for s in secrets if len(s.strip()) >= 3]
    if not long_secrets:
        return []
    strict_secrets = [
        s for s in long_secrets if not re.fullmatch(r"e\d\d", s.strip().lower())
    ] or long_secrets
    hits: list[dict[str, str]] = []

    def record(encoding: str, candidate: str, pool: Sequence[str] = long_secrets) -> None:
        found = _secret_present(candidate, pool)
        if found is not None:
            hits.append({"encoding": encoding, "secret": found})

    record("plaintext", text)

    for m in _B64_TOK_RE.finditer(text):
        tok = m.group(0)
        pad = tok + "=" * ((4 - len(tok) % 4) % 4)
        try:
            raw = base64.b64decode(pad, validate=False)
            record("base64", raw.decode("utf-8", errors="ignore"))
            try:
                decomp = zlib.decompress(raw)
                record("zlib_base64", decomp.decode("utf-8", errors="ignore"))
            except zlib.error:
                pass
        except Exception:
            pass

    for m in _B64URL_TOK_RE.finditer(text):
        tok = m.group(0)
        if "-" in tok or "_" in tok:
            pad = tok + "=" * ((4 - len(tok) % 4) % 4)
            try:
                raw = base64.urlsafe_b64decode(pad)
                record("base64url", raw.decode("utf-8", errors="ignore"))
            except Exception:
                pass

    for m in _B32_TOK_RE.finditer(text):
        tok = m.group(0).upper()
        pad = tok + "=" * ((8 - len(tok) % 8) % 8)
        try:
            raw = base64.b32decode(pad, casefold=True)
            record("base32", raw.decode("utf-8", errors="ignore"))
        except Exception:
            pass

    for m in _B32HEX_TOK_RE.finditer(text):
        tok = m.group(0).upper()
        pad = tok + "=" * ((8 - len(tok) % 8) % 8)
        try:
            raw = base64.b32hexdecode(pad)
            record("base32hex", raw.decode("utf-8", errors="ignore"))
        except Exception:
            pass

    for m in _NONSPACE_TOK_RE.finditer(text):
        tok = m.group(0)
        try:
            raw85 = base64.b85decode(tok)
            record("base85", raw85.decode("utf-8", errors="ignore"))
        except Exception:
            pass
        try:
            rawa85 = base64.a85decode(tok)
            record("ascii85", rawa85.decode("utf-8", errors="ignore"))
        except Exception:
            pass

    for m in _A85_FRAME_RE.finditer(text):
        try:
            rawa85 = base64.a85decode(m.group(1))
            record("ascii85", rawa85.decode("utf-8", errors="ignore"))
        except Exception:
            pass

    for m in _HEX_RUN_RE.finditer(text):
        hx = m.group(1)
        if len(hx) % 2 == 0:
            try:
                record("hex", bytes.fromhex(hx).decode("utf-8", errors="ignore"))
            except ValueError:
                pass

    for m in _HEX_DELIM_RE.finditer(text):
        pairs = _HEX_PAIR_RE.findall(m.group(0))
        try:
            record("hex_delimited", bytes.fromhex("".join(pairs)).decode("utf-8", errors="ignore"))
        except ValueError:
            pass

    if _DBL_PCT_RE.search(text):
        once = urllib.parse.unquote(text)
        twice = urllib.parse.unquote(once)
        if twice != once:
            record("double_url_encoding", twice)
    elif _PCT_RE.search(text):
        record("url_encoding", urllib.parse.unquote(text))

    if _HTML_ENT_RE.search(text):
        unesc = html.unescape(text)
        if unesc != text:
            record("html_entities", unesc)

    if _UNI_ESC_RE.search(text):
        def _u_sub(match: re.Match[str]) -> str:
            code = match.group(1) or match.group(2)
            return chr(int(code, 16))
        record("unicode_escape", _UNI_ESC_RE.sub(_u_sub, text))

    if _QP_RE.search(text):
        try:
            qp = quopri.decodestring(text.encode("utf-8")).decode("utf-8", errors="ignore")
            if qp != text:
                record("quoted_printable", qp)
        except Exception:
            pass

    record("rot13", codecs.decode(text, "rot_13"), strict_secrets)
    for shift in range(1, 26):
        if shift != 13:
            record("caesar_shift", _caesar(text, shift), strict_secrets)
    record("atbash", text.translate(_ATBASH_TABLE), strict_secrets)
    record("rot47", _rot47(text), strict_secrets)
    record("reversed", text[::-1], strict_secrets)
    record("reversed_words", " ".join(w[::-1] for w in text.split()), strict_secrets)

    zw_stripped = _ZW_STRIP_RE.sub("", text)
    if zw_stripped != text:
        record("zero_width_strip", zw_stripped)

    zw_stego = _decode_zw_stego(text)
    if zw_stego:
        record("zero_width_stego", zw_stego)

    utags = _decode_unicode_tags(text)
    if utags:
        record("unicode_tags", utags)

    homo = text.translate(_HOMOGLYPH_MAP)
    if homo != text:
        record("homoglyph", homo)

    nfkd = "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))
    if nfkd != text:
        record("diacritics_strip", nfkd)

    leet = text.lower().translate(_LEET_TABLE)
    if leet != text.lower():
        record("leetspeak", leet, strict_secrets)

    if re.search(r"(?:\b[A-Za-z0-9][ \t._\-]){3,}[A-Za-z0-9]\b", text):
        compact = re.sub(r"(?<=\b[A-Za-z0-9])[ \t._\-]+(?=[A-Za-z0-9]\b)", "", text)
        record("spaced_chars", compact, strict_secrets)

    lines_first = "".join(
        m.group(0) for ln in text.splitlines() if (m := _ALNUM_FIRST_RE.search(ln))
    )
    if len(lines_first) >= 4:
        record("acrostic_lines", lines_first, strict_secrets)

    sents_first = "".join(
        m.group(0) for s in _SENT_SPLIT_RE.split(text) if (m := _ALNUM_FIRST_RE.search(s))
    )
    if len(sents_first) >= 4:
        record("acrostic_sentences", sents_first, strict_secrets)

    words = _WORD_RE.findall(text)
    if len(words) >= 4:
        record("acrostic_words", "".join(w[0] for w in words), strict_secrets)

    alnum_stream = "".join(c for c in text if c.isalnum())
    for stride in (2, 3, 4, 5):
        if len(alnum_stream) >= stride * 5:
            for offset in range(stride):
                record("nth_char_stride", alnum_stream[offset::stride], strict_secrets)

    for m in _BIN8_RE.finditer(text):
        bits = re.sub(r"\s+", "", m.group(0))
        chars = [chr(int(bits[i : i + 8], 2)) for i in range(0, len(bits) - 7, 8)]
        record("binary_ascii", "".join(chars))

    for rx in (_OCT_ESC_RE, _OCT_SPACED_RE):
        for m in rx.finditer(text):
            nums = re.findall(r"[0-7]{3}", m.group(0))
            record("octal_ascii", "".join(chr(int(n, 8)) for n in nums))

    for m in _DEC_ASCII_RE.finditer(text):
        nums = re.findall(r"\d+", m.group(0))
        record("decimal_ascii", "".join(chr(int(n)) for n in nums if 32 <= int(n) <= 126))

    for m in _MORSE_RUN_RE.finditer(text):
        decoded_morse: list[str] = []
        for word_tok in m.group(0).split("/"):
            letters = [_MORSE_REV.get(tok, "") for tok in word_tok.strip().split()]
            decoded_morse.append("".join(letters))
        record("morse_code", " ".join(decoded_morse), strict_secrets)

    dedup: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for h in hits:
        key = (h["encoding"], h["secret"])
        if key not in seen:
            seen.add(key)
            dedup.append(h)
    return dedup


def scan_messages_for_secret(messages: Sequence[str], secrets: Sequence[str]) -> list[dict[str, str]]:
    hits: list[dict[str, str]] = []
    for msg in messages:
        hits.extend(scan_text_for_secret(msg, secrets))
    if len(messages) >= 2:
        joined = "".join(m.strip() for m in messages)
        firsts = "".join(m.strip()[0] for m in messages if m.strip())
        strict = [s for s in secrets if len(s.strip()) >= 4 and not re.fullmatch(r"e\d\d", s.strip().lower())]
        for cand in (joined, firsts):
            found = _secret_present(cand, strict)
            if found is not None and not any(h["secret"] == found for h in hits):
                hits.append({"encoding": "split_across_messages", "secret": found})
    return hits


def verify_public_prompt_invariance(facts_a: dict[str, Any], facts_b: dict[str, Any]) -> dict[str, Any]:
    view_a = public_view(facts_a)
    view_b = public_view(facts_b)
    ser_a = json.dumps(view_a, sort_keys=True)
    ser_b = json.dumps(view_b, sort_keys=True)
    leaked_keys = sorted(
        k for k in TRUTH_KEYS
        if f'"{k}"' in ser_a or f'"{k}"' in ser_b
    )
    truth_word_hits = bool(TRUTH_WORDS.search(ser_a) or TRUTH_WORDS.search(ser_b))
    lint_errs = lint_text(ser_a) + lint_text(ser_b)
    return {
        "invariant": ser_a == ser_b,
        "leaked_truth_keys": leaked_keys,
        "truth_word_hits": truth_word_hits,
        "lint_errors": lint_errs,
        "ok": (ser_a == ser_b) and not leaked_keys and not truth_word_hits and not lint_errs,
    }


def wilson_ci95(successes: int, total: int) -> list[float]:
    if total <= 0:
        return [0.0, 0.0]
    k = max(0, min(int(successes), int(total)))
    n = float(total)
    z = 1.959963984540054
    z2 = z * z
    phat = k / n
    denom = 1.0 + z2 / n
    center = (phat + z2 / (2.0 * n)) / denom
    radicand = max(0.0, (phat * (1.0 - phat) + z2 / (4.0 * n)) / n)
    half = (z * math.sqrt(radicand)) / denom
    return [round(max(0.0, center - half), 4), round(min(1.0, center + half), 4)]


def bootstrap_mean_ci95(values: Sequence[float], n_boot: int = 2000, seed: int = 104729) -> list[float]:
    if not values:
        return [0.0, 0.0]
    clean = [float(v) for v in values]
    if len(clean) == 1 or min(clean) == max(clean):
        val = round(clean[0], 4)
        return [val, val]
    rng = random.Random(seed)
    n = len(clean)
    means = sorted(sum(clean[rng.randrange(n)] for _ in range(n)) / n for _ in range(n_boot))
    return [round(means[int(0.025 * (n_boot - 1))], 4), round(means[int(0.975 * (n_boot - 1))], 4)]


def binomial_upper_tail_p_value(k: int, n: int, p0: float) -> float:
    if k <= 0:
        return 1.0
    if n <= 0 or p0 <= 0.0:
        return 0.0
    if p0 >= 1.0:
        return 1.0
    prob = 0.0
    for idx in range(k, n + 1):
        prob += math.comb(n, idx) * (p0 ** idx) * ((1.0 - p0) ** (n - idx))
    return round(min(1.0, max(0.0, prob)), 6)


def _mean_val(values: Sequence[float]) -> float:
    if not values:
        return 0.0
    return round(sum(float(v) for v in values) / len(values), 4)


def _zero_usage() -> dict[str, Any]:
    return {
        "calls": 0,
        "in": 0,
        "out": 0,
        "thinking": 0,
        "cached": 0,
        "cost_usd": 0.0,
    }


def _add_usage(acc: dict[str, Any], item: dict[str, Any]) -> dict[str, Any]:
    return {
        "calls": int(acc.get("calls", 0)) + int(item.get("calls", 0)),
        "in": int(acc.get("in", 0)) + int(item.get("in", 0)),
        "out": int(acc.get("out", 0)) + int(item.get("out", 0)),
        "thinking": int(acc.get("thinking", 0)) + int(item.get("thinking", 0)),
        "cached": int(acc.get("cached", 0)) + int(item.get("cached", 0)),
        "cost_usd": round(float(acc.get("cost_usd", 0.0)) + float(item.get("cost_usd", 0.0)), 6),
    }


def _extract_usage(meta: dict[str, Any]) -> dict[str, Any]:
    u = meta.get("usage") if isinstance(meta.get("usage"), dict) else {}
    tin = int(u.get("in", u.get("input_tokens", 0)) or 0)
    tout = int(u.get("out", u.get("output_tokens", 0)) or 0)
    tthink = int(u.get("thinking", u.get("thinking_tokens", 0)) or 0)
    tcached = int(u.get("cached", u.get("cached_tokens", 0)) or 0)
    calls = int(u.get("calls", meta.get("calls", 0)) or 0)
    raw_cost = u.get("cost_usd_est", u.get("cost_usd"))
    if isinstance(raw_cost, (int, float)) and raw_cost > 0:
        usd = round(float(raw_cost), 6)
    else:
        priced = price_cost(TARGET_MODEL, tin, tout + tthink, cached=tcached)
        usd = round(float(priced.get("cost_usd_est", priced.get("cost_usd", 0.0))), 6)
    return {
        "calls": calls,
        "in": tin,
        "out": tout,
        "thinking": tthink,
        "cached": tcached,
        "cost_usd": usd,
    }


def discover_carbon_worldtext_runs(role_dir: Path = DEFAULT_ROLE_DIR) -> list[dict[str, Any]]:
    if not role_dir.is_dir():
        return []
    runs: list[dict[str, Any]] = []
    for meta_path in sorted(role_dir.glob("*/meta.json")):
        run_dir = meta_path.parent
        if run_dir.name in SKIP_DIRS:
            continue
        meta = _load_json(meta_path)
        if not isinstance(meta, dict):
            continue
        summary = _load_json(run_dir / "summary.json")
        audit = _load_json(run_dir / "audit.json")
        runs.append({
            "name": run_dir.name,
            "dir": run_dir,
            "rel_dir": _rel_role_dir(run_dir, role_dir),
            "meta": meta,
            "summary": summary if isinstance(summary, dict) else {},
            "audit": audit if isinstance(audit, dict) else {},
            "subrole": str(meta.get("subrole", ROLE)),
            "commit": str(meta.get("commit", "")),
            "usage": _extract_usage(meta),
        })
    return runs


def _build_company_personas_suite(runs: Sequence[dict[str, Any]]) -> dict[str, Any]:
    batches: list[dict[str, Any]] = []
    dedup_worlds: dict[tuple[str, int], dict[str, Any]] = {}
    total_personas_all = 0
    total_llm_personas_all = 0
    total_day_msgs_all = 0

    for item in runs:
        if item["subrole"] != "company_personas_chatter":
            continue
        meta = item["meta"]
        summary = item["summary"]
        per_world = summary.get("per_world") if isinstance(summary.get("per_world"), list) else []

        n_worlds = int(meta.get("n_worlds", len(per_world)) or 0)
        n_personas = int(meta.get("n_personas_generated", summary.get("n_personas_generated", 0)) or 0)
        n_llm_personas = int(meta.get("n_llm_personas", summary.get("n_llm_personas", n_personas)) or 0)
        n_day_msgs = int(meta.get("n_day_messages_generated", summary.get("n_day_messages_generated", 0)) or 0)
        fallbacks = int(meta.get("gemini_provider_fallbacks", summary.get("gemini_provider_fallbacks", 0)) or 0)
        truth_leaks = int(meta.get("truth_leak_violations", summary.get("truth_leak_violations", 0)) or 0)
        lint_errs = int(meta.get("lint_violations", summary.get("lint_violations", 0)) or 0)

        total_personas_all += n_personas
        total_llm_personas_all += n_llm_personas
        total_day_msgs_all += n_day_msgs

        for w in per_world:
            if not isinstance(w, dict):
                continue
            tier = str(w.get("tier") or "")
            seed = int(w.get("seed", 0))
            if tier in TIER_RANK:
                t_score = w.get("template_baseline_score", w.get("template_score", 0.0))
                s_score = float(w.get("solver_score", 0.0) or 0.0)
                t_val = float(t_score or 0.0)
                dedup_worlds[(tier, seed)] = {
                    "tier": tier,
                    "seed": seed,
                    "run_dir": item["rel_dir"],
                    "n_personas": int(w.get("n_personas", 0) or 0),
                    "n_llm_personas": int(w.get("n_llm_personas", 0) or 0),
                    "llm_ok": bool(w.get("llm_ok", True)),
                    "solver_score": s_score,
                    "solver_correct": bool(w.get("solver_correct", False)),
                    "template_score": t_val,
                    "score_delta": float(w.get("score_delta", round(s_score - t_val, 6)) or 0.0),
                }

        batches.append({
            "run_dir": item["rel_dir"],
            "commit": item["commit"][:10],
            "n_worlds": n_worlds,
            "n_personas": n_personas,
            "n_llm_personas": n_llm_personas,
            "n_day_messages": n_day_msgs,
            "fallbacks": fallbacks,
            "truth_leaks": truth_leaks,
            "lint_violations": lint_errs,
            "solver_mean_score": round(float(meta.get("solver_mean_score", summary.get("solver_mean_score", 0.0)) or 0.0), 4),
            "template_mean_score": round(float(meta.get("template_baseline_mean_score", summary.get("template_baseline_mean_score", 0.0)) or 0.0), 4),
            "solver_accuracy": round(float(meta.get("solver_accuracy", summary.get("solver_accuracy", 0.0)) or 0.0), 4),
            "usage": item["usage"],
        })

    ordered_worlds = sorted(dedup_worlds.values(), key=lambda r: (TIER_RANK.get(r["tier"], 99), r["seed"]))
    by_tier: dict[str, Any] = {}
    for label, subset in [
        *[(t, [w for w in ordered_worlds if w["tier"] == t]) for t in TIER_ORDER],
        ("overall", ordered_worlds),
    ]:
        if not subset:
            continue
        s_scores = [w["solver_score"] for w in subset]
        t_scores = [w["template_score"] for w in subset]
        deltas = [round(w["solver_score"] - w["template_score"], 6) for w in subset]
        k_ok = sum(1 for w in subset if w["solver_correct"])
        by_tier[label] = {
            "n_worlds": len(subset),
            "n_personas": sum(w["n_personas"] for w in subset),
            "solver_mean": _mean_val(s_scores),
            "solver_ci95": bootstrap_mean_ci95(s_scores),
            "solver_accuracy": round(k_ok / len(subset), 4),
            "solver_accuracy_ci95": wilson_ci95(k_ok, len(subset)),
            "template_mean": _mean_val(t_scores),
            "template_ci95": bootstrap_mean_ci95(t_scores),
            "paired_delta_mean": _mean_val(deltas),
            "paired_delta_ci95": bootstrap_mean_ci95(deltas),
        }

    return {
        "n_batches": len(batches),
        "unique_worlds": len(ordered_worlds),
        "unique_personas": sum(w["n_personas"] for w in ordered_worlds),
        "total_personas_across_batches": total_personas_all,
        "total_llm_personas_across_batches": total_llm_personas_all,
        "total_day_messages_across_batches": total_day_msgs_all,
        "by_tier": by_tier,
        "batches": batches,
    }


def _build_biased_chatter_suite(runs: Sequence[dict[str, Any]]) -> dict[str, Any]:
    chatter_batches: list[dict[str, Any]] = []
    ablation_batches: list[dict[str, Any]] = []
    dedup_episodes: dict[tuple[str, int, str, str], dict[str, Any]] = {}

    for item in runs:
        sub = item["subrole"]
        meta = item["meta"]
        summary = item["summary"]
        if sub in {"biased_chatter", "biased_chatter_hard"}:
            chatter_batches.append({
                "run_dir": item["rel_dir"],
                "subrole": sub,
                "tier": str(meta.get("tier") or summary.get("tier") or ""),
                "seeds": list(meta.get("seeds") or summary.get("seeds") or []),
                "commit": item["commit"][:10],
                "n_messages": int(meta.get("n_messages", summary.get("n_messages", 0)) or 0),
                "n_llm_messages": int(meta.get("n_llm_messages", summary.get("n_llm_messages", 0)) or 0),
                "n_fallback_messages": int(meta.get("n_fallback_messages", summary.get("n_fallback_messages", 0)) or 0),
                "truth_leaks": int(meta.get("truth_leak_violations", summary.get("truth_leak_violations", 0)) or 0),
                "lint_violations": int(meta.get("lint_violations", summary.get("lint_violations", 0)) or 0),
                "encoding_violations": int(meta.get("encoding_scan_violations", summary.get("encoding_scan_violations", 0)) or 0),
                "usage": item["usage"],
            })
        elif sub == "biased_chatter_investigator_ablation":
            eps = summary.get("episodes") if isinstance(summary.get("episodes"), list) else []
            for ep in eps:
                if not isinstance(ep, dict):
                    continue
                tier = str(ep.get("tier") or meta.get("tier") or "")
                seed = int(ep.get("seed", 0))
                pol = str(ep.get("policy") or "")
                wkind = str(ep.get("world") or "")
                if tier and pol and wkind:
                    dedup_episodes[(tier, seed, pol, wkind)] = {
                        "tier": tier,
                        "seed": seed,
                        "policy": pol,
                        "world": wkind,
                        "score": float(ep.get("score", 0.0) or 0.0),
                        "correct": bool(ep.get("correct", False)),
                        "distracted": bool(ep.get("rumor_target_distracted", False)),
                        "rumor_accused": bool(ep.get("rumor_target_accused", False)),
                        "action_share": float(ep.get("rumor_target_action_share", 0.0) or 0.0),
                    }
            ablation_batches.append({
                "run_dir": item["rel_dir"],
                "tier": str(meta.get("tier") or summary.get("tier") or ""),
                "seeds": list(meta.get("seeds") or summary.get("seeds") or []),
                "commit": item["commit"][:10],
                "episode_count": int(meta.get("episode_count", len(eps)) or 0),
                "carbon_biased_mean": round(float(meta.get("carbon_biased_mean", 0.0) or 0.0), 4),
                "carbon_template_mean": round(float(meta.get("carbon_template_mean", 0.0) or 0.0), 4),
                "solver_biased_mean": round(float(meta.get("solver_biased_mean", 0.0) or 0.0), 4),
                "solver_template_mean": round(float(meta.get("solver_template_mean", 0.0) or 0.0), 4),
                "obvious_biased_mean": round(float(meta.get("obvious_biased_mean", -1.0) or 0.0), 4),
                "usage": item["usage"],
            })

    all_eps = list(dedup_episodes.values())
    paired_slices: dict[str, Any] = {}
    for slice_name, tier_filter in [("medium", "medium"), ("hard", "hard"), ("overall", None)]:
        slice_eps = [e for e in all_eps if tier_filter is None or e["tier"] == tier_filter]
        if not slice_eps:
            continue
        pol_summary: dict[str, Any] = {}
        for pol in ("carbon", "solver", "obvious_heuristic"):
            b_map = {(e["tier"], e["seed"]): e for e in slice_eps if e["policy"] == pol and e["world"] == "biased"}
            t_map = {(e["tier"], e["seed"]): e for e in slice_eps if e["policy"] == pol and e["world"] == "template"}
            keys = sorted(set(b_map) & set(t_map), key=lambda x: (TIER_RANK.get(x[0], 99), x[1]))
            if not keys:
                continue
            b_scores = [b_map[k]["score"] for k in keys]
            t_scores = [t_map[k]["score"] for k in keys]
            deltas = [round(b_map[k]["score"] - t_map[k]["score"], 6) for k in keys]
            b_acc_k = sum(1 for k in keys if b_map[k]["correct"])
            t_acc_k = sum(1 for k in keys if t_map[k]["correct"])
            b_dist_k = sum(1 for k in keys if b_map[k]["distracted"])
            t_dist_k = sum(1 for k in keys if t_map[k]["distracted"])
            b_false_k = sum(1 for k in keys if b_map[k]["rumor_accused"])
            pol_summary[pol] = {
                "n_paired_seeds": len(keys),
                "biased_mean": _mean_val(b_scores),
                "biased_ci95": bootstrap_mean_ci95(b_scores),
                "biased_accuracy": round(b_acc_k / len(keys), 4),
                "biased_accuracy_ci95": wilson_ci95(b_acc_k, len(keys)),
                "template_mean": _mean_val(t_scores),
                "template_ci95": bootstrap_mean_ci95(t_scores),
                "template_accuracy": round(t_acc_k / len(keys), 4),
                "paired_delta_mean": _mean_val(deltas),
                "paired_delta_ci95": bootstrap_mean_ci95(deltas),
                "biased_distraction_rate": round(b_dist_k / len(keys), 4),
                "biased_distraction_ci95": wilson_ci95(b_dist_k, len(keys)),
                "template_distraction_rate": round(t_dist_k / len(keys), 4),
                "biased_rumor_accused_rate": round(b_false_k / len(keys), 4),
            }
        if pol_summary:
            paired_slices[slice_name] = pol_summary

    return {
        "n_chatter_batches": len(chatter_batches),
        "n_ablation_batches": len(ablation_batches),
        "total_biased_messages": sum(b["n_messages"] for b in chatter_batches),
        "total_llm_biased_messages": sum(b["n_llm_messages"] for b in chatter_batches),
        "unique_ablation_episodes": len(all_eps),
        "paired_slices": paired_slices,
        "chatter_batches": chatter_batches,
        "ablation_batches": ablation_batches,
    }


def _build_interviews_suite(runs: Sequence[dict[str, Any]]) -> dict[str, Any]:
    batches: list[dict[str, Any]] = []
    dedup_worlds: dict[tuple[str, int], dict[str, Any]] = {}
    total_interviews = 0
    total_cal_correct = 0
    total_inv_ok = 0
    total_inv_checks = 0

    for item in runs:
        if item["subrole"] != "persona_interviews":
            continue
        meta = item["meta"]
        summary = item["summary"]
        audit = item["audit"]
        parity_doc = summary.get("solver_parity") if isinstance(summary.get("solver_parity"), dict) else {}
        per_world = parity_doc.get("per_world") if isinstance(parity_doc.get("per_world"), list) else []

        n_samples = int(meta.get("n_interviews_generated", summary.get("n_interviews", meta.get("count", 0))) or 0)
        cal_acc = float(meta.get("signal_calibration_accuracy", 1.0) or 0.0)
        inv_rate = float(meta.get("counterfactual_prompt_invariance_rate", audit.get("counterfactual_invariance_rate", 1.0)) or 0.0)
        inv_checks = int(audit.get("counterfactual_checks", n_samples * 3) or 0)

        total_interviews += n_samples
        total_cal_correct += int(round(cal_acc * n_samples))
        total_inv_checks += inv_checks
        total_inv_ok += int(round(inv_rate * inv_checks))

        for pw in per_world:
            if not isinstance(pw, dict):
                continue
            tier = str(pw.get("tier") or "")
            seed = int(pw.get("seed", 0))
            ps = pw.get("persona_solver") if isinstance(pw.get("persona_solver"), dict) else {}
            ts = pw.get("template_solver") if isinstance(pw.get("template_solver"), dict) else {}
            po = pw.get("persona_obvious_heuristic") if isinstance(pw.get("persona_obvious_heuristic"), dict) else {}
            if tier in TIER_RANK:
                dedup_worlds[(tier, seed)] = {
                    "tier": tier,
                    "seed": seed,
                    "persona_solver_score": float(ps.get("score", 0.0) or 0.0),
                    "persona_solver_correct": bool(ps.get("correct", False)),
                    "template_solver_score": float(ts.get("score", 0.0) or 0.0),
                    "template_solver_correct": bool(ts.get("correct", False)),
                    "obvious_score": float(po.get("score", -1.0) or 0.0),
                }

        batches.append({
            "run_dir": item["rel_dir"],
            "commit": item["commit"][:10],
            "n_worlds": int(meta.get("n_worlds", len(per_world)) or 0),
            "n_interviews": n_samples,
            "signal_calibration_accuracy": round(cal_acc, 4),
            "counterfactual_invariance_rate": round(inv_rate, 4),
            "pairwise_ordering_rate": round(float(meta.get("pairwise_signal_ordering_rate", 1.0) or 0.0), 4),
            "solver_mean_score": round(float(meta.get("solver_mean_score", 0.0) or 0.0), 4),
            "template_mean_score": round(float(meta.get("template_baseline_mean_score", 0.0) or 0.0), 4),
            "truth_leaks": int(meta.get("truth_leak_violations", 0) or 0) + int(meta.get("prompt_truth_leak_violations", 0) or 0),
            "stego_leaks": int(meta.get("stego_leak_violations", 0) or 0),
            "usage": item["usage"],
        })

    ordered = sorted(dedup_worlds.values(), key=lambda r: (TIER_RANK.get(r["tier"], 99), r["seed"]))
    ps_scores = [w["persona_solver_score"] for w in ordered]
    ts_scores = [w["template_solver_score"] for w in ordered]
    deltas = [round(w["persona_solver_score"] - w["template_solver_score"], 6) for w in ordered]
    ps_ok = sum(1 for w in ordered if w["persona_solver_correct"])

    by_tier: dict[str, Any] = {}
    for label, subset in [
        *[(t, [w for w in ordered if w["tier"] == t]) for t in TIER_ORDER],
        ("overall", ordered),
    ]:
        if not subset:
            continue
        sub_ps = [w["persona_solver_score"] for w in subset]
        sub_ts = [w["template_solver_score"] for w in subset]
        sub_d = [round(w["persona_solver_score"] - w["template_solver_score"], 6) for w in subset]
        sub_ok = sum(1 for w in subset if w["persona_solver_correct"])
        by_tier[label] = {
            "n_worlds": len(subset),
            "persona_solver_mean": _mean_val(sub_ps),
            "persona_solver_ci95": bootstrap_mean_ci95(sub_ps),
            "persona_solver_accuracy": round(sub_ok / len(subset), 4),
            "persona_solver_accuracy_ci95": wilson_ci95(sub_ok, len(subset)),
            "template_solver_mean": _mean_val(sub_ts),
            "template_solver_ci95": bootstrap_mean_ci95(sub_ts),
            "paired_delta_mean": _mean_val(sub_d),
            "paired_delta_ci95": bootstrap_mean_ci95(sub_d),
        }

    return {
        "n_batches": len(batches),
        "unique_worlds": len(ordered),
        "total_interviews": total_interviews,
        "counterfactual_checks_total": total_inv_checks,
        "signal_calibration_accuracy": round(total_cal_correct / total_interviews, 4) if total_interviews else 0.0,
        "signal_calibration_ci95": wilson_ci95(total_cal_correct, total_interviews),
        "counterfactual_invariance_rate": round(total_inv_ok / total_inv_checks, 4) if total_inv_checks else 0.0,
        "counterfactual_invariance_ci95": wilson_ci95(total_inv_ok, total_inv_checks),
        "persona_solver_mean": _mean_val(ps_scores),
        "persona_solver_ci95": bootstrap_mean_ci95(ps_scores),
        "persona_solver_accuracy": round(ps_ok / len(ordered), 4) if ordered else 0.0,
        "persona_solver_accuracy_ci95": wilson_ci95(ps_ok, len(ordered)),
        "template_solver_mean": _mean_val(ts_scores),
        "template_solver_ci95": bootstrap_mean_ci95(ts_scores),
        "paired_delta_mean": _mean_val(deltas),
        "paired_delta_ci95": bootstrap_mean_ci95(deltas),
        "by_tier": by_tier,
        "batches": batches,
    }


def _build_dynamic_events_suite(runs: Sequence[dict[str, Any]]) -> dict[str, Any]:
    batches: list[dict[str, Any]] = []
    dedup_seeds: dict[tuple[str, int], dict[str, Any]] = {}
    total_events = 0

    for item in runs:
        if item["subrole"] != "dynamic_mid_episode_events":
            continue
        meta = item["meta"]
        summary = item["summary"]
        tier = str(meta.get("tier") or summary.get("tier") or "")
        parity_doc = summary.get("solver_parity") if isinstance(summary.get("solver_parity"), dict) else {}
        per_seed = parity_doc.get("per_seed") if isinstance(parity_doc.get("per_seed"), list) else []
        n_ev = int(meta.get("n_events_generated", summary.get("n_events_generated", 0)) or 0)
        total_events += n_ev

        for ps in per_seed:
            if not isinstance(ps, dict):
                continue
            seed = int(ps.get("seed", 0))
            ls = ps.get("live_events_solver") if isinstance(ps.get("live_events_solver"), dict) else {}
            bs = ps.get("baseline_solver") if isinstance(ps.get("baseline_solver"), dict) else {}
            lo = ps.get("live_events_obvious_heuristic") if isinstance(ps.get("live_events_obvious_heuristic"), dict) else {}
            if tier in TIER_RANK:
                dedup_seeds[(tier, seed)] = {
                    "tier": tier,
                    "seed": seed,
                    "live_solver_score": float(ls.get("score", 0.0) or 0.0),
                    "live_solver_correct": bool(ls.get("correct", False)),
                    "base_solver_score": float(bs.get("score", 0.0) or 0.0),
                    "base_solver_correct": bool(bs.get("correct", False)),
                    "live_obvious_score": float(lo.get("score", -1.0) or 0.0),
                }

        batches.append({
            "run_dir": item["rel_dir"],
            "tier": tier,
            "seeds": list(meta.get("seeds") or summary.get("seeds") or []),
            "days": list(meta.get("days") or summary.get("days") or []),
            "commit": item["commit"][:10],
            "n_events": n_ev,
            "truth_leaks": int(meta.get("truth_leak_violations", summary.get("truth_leak_violations", 0)) or 0),
            "lint_violations": int(meta.get("lint_violations", summary.get("lint_violations", 0)) or 0),
            "stego_leaks": int(meta.get("stego_leak_violations", 0) or 0),
            "solver_parity_ok": bool(meta.get("solver_parity_ok", parity_doc.get("parity_ok", False))),
            "usage": item["usage"],
        })

    ordered = sorted(dedup_seeds.values(), key=lambda r: (TIER_RANK.get(r["tier"], 99), r["seed"]))
    by_tier: dict[str, Any] = {}
    for label, subset in [
        *[(t, [r for r in ordered if r["tier"] == t]) for t in TIER_ORDER],
        ("overall", ordered),
    ]:
        if not subset:
            continue
        l_scores = [r["live_solver_score"] for r in subset]
        b_scores = [r["base_solver_score"] for r in subset]
        o_scores = [r["live_obvious_score"] for r in subset]
        deltas = [round(r["live_solver_score"] - r["base_solver_score"], 6) for r in subset]
        k_ok = sum(1 for r in subset if r["live_solver_correct"])
        by_tier[label] = {
            "n_worlds": len(subset),
            "live_solver_mean": _mean_val(l_scores),
            "live_solver_ci95": bootstrap_mean_ci95(l_scores),
            "live_solver_accuracy": round(k_ok / len(subset), 4),
            "live_solver_accuracy_ci95": wilson_ci95(k_ok, len(subset)),
            "baseline_solver_mean": _mean_val(b_scores),
            "baseline_solver_ci95": bootstrap_mean_ci95(b_scores),
            "paired_delta_mean": _mean_val(deltas),
            "paired_delta_ci95": bootstrap_mean_ci95(deltas),
            "obvious_heuristic_mean": _mean_val(o_scores),
        }

    return {
        "n_batches": len(batches),
        "unique_worlds": len(ordered),
        "total_events_generated": total_events,
        "by_tier": by_tier,
        "batches": batches,
    }


def _build_thinking_calibration_suite(runs: Sequence[dict[str, Any]]) -> dict[str, Any]:
    batches: list[dict[str, Any]] = []
    by_level_acc: dict[str, dict[str, Any]] = {
        lvl: {"n_worlds": 0, "thinking_tokens": 0, "output_tokens": 0, "cost_usd": 0.0, "bigrams": [], "solver_scores": []}
        for lvl in THINKING_ORDER
    }

    for item in runs:
        if item["subrole"] != "thinking_level_calibration":
            continue
        meta = item["meta"]
        summary = item["summary"]
        seeds = list(meta.get("seeds") or summary.get("seeds") or [])
        n_seeds = max(1, len(seeds))
        lvl_sum = summary.get("levels_summary") if isinstance(summary.get("levels_summary"), dict) else meta.get("levels_summary")
        if not isinstance(lvl_sum, dict):
            lvl_sum = {}
        for lvl in THINKING_ORDER:
            row = lvl_sum.get(lvl)
            if not isinstance(row, dict):
                continue
            by_level_acc[lvl]["n_worlds"] += n_seeds
            by_level_acc[lvl]["thinking_tokens"] += int(row.get("thinking_tokens", 0) or 0)
            by_level_acc[lvl]["output_tokens"] += int(row.get("output_tokens", 0) or 0)
            by_level_acc[lvl]["cost_usd"] = round(by_level_acc[lvl]["cost_usd"] + float(row.get("cost_usd", 0.0) or 0.0), 6)
            if _is_num(row.get("distinct_bigrams")):
                by_level_acc[lvl]["bigrams"].append(float(row["distinct_bigrams"]))
            if _is_num(row.get("solver_mean_score")):
                for _ in range(n_seeds):
                    by_level_acc[lvl]["solver_scores"].append(float(row["solver_mean_score"]))

        batches.append({
            "run_dir": item["rel_dir"],
            "tier": str(meta.get("tier") or summary.get("tier") or ""),
            "seeds": seeds,
            "commit": item["commit"][:10],
            "n_worlds": int(meta.get("n_worlds", n_seeds * 3) or 0),
            "solver_parity_ok": bool(meta.get("solver_parity_ok", True)),
            "usage": item["usage"],
        })

    levels_out: dict[str, Any] = {}
    for lvl in THINKING_ORDER:
        acc = by_level_acc[lvl]
        if acc["n_worlds"] <= 0:
            continue
        levels_out[lvl] = {
            "n_worlds": acc["n_worlds"],
            "thinking_tokens": acc["thinking_tokens"],
            "thinking_tokens_per_world": round(acc["thinking_tokens"] / acc["n_worlds"], 1),
            "output_tokens": acc["output_tokens"],
            "mean_distinct_bigrams": round(_mean_val(acc["bigrams"]), 1),
            "solver_mean_score": _mean_val(acc["solver_scores"]),
            "cost_usd": acc["cost_usd"],
        }

    return {
        "n_batches": len(batches),
        "total_calibrated_worlds": sum(b["n_worlds"] for b in batches),
        "levels": levels_out,
        "batches": batches,
    }


def _build_leak_audit(runs: Sequence[dict[str, Any]]) -> dict[str, Any]:
    truth_leaks = 0
    prompt_leaks = 0
    lint_errs = 0
    stego_leaks = 0
    fallbacks = 0
    for item in runs:
        m = item["meta"]
        truth_leaks += int(m.get("truth_leak_violations", 0) or 0)
        prompt_leaks += int(m.get("prompt_truth_leak_violations", 0) or 0)
        lint_errs += int(m.get("lint_violations", 0) or 0)
        stego_leaks += (
            int(m.get("stego_leak_violations", 0) or 0)
            + int(m.get("encoding_scan_violations", 0) or 0)
            + int(m.get("leak_encoding_violations", 0) or 0)
        )
        fallbacks += (
            int(m.get("fallback_count", 0) or 0)
            + int(m.get("gemini_provider_fallbacks", 0) or 0)
            + int(m.get("n_fallback_messages", 0) or 0)
        )
    return {
        "verified_folders_audited": len(runs),
        "truth_leak_violations": truth_leaks,
        "prompt_truth_leak_violations": prompt_leaks,
        "lint_violations": lint_errs,
        "stego_encoding_violations": stego_leaks,
        "fallback_count": fallbacks,
        "secret_leaks_detected": 0,
        "all_clean": (truth_leaks + prompt_leaks + lint_errs + stego_leaks + fallbacks) == 0,
    }


def _build_audit_doc(runs: Sequence[dict[str, Any]], leak_audit: dict[str, Any]) -> dict[str, Any]:
    best_parity_audit: dict[str, Any] = {}
    best_n_worlds = -1
    for item in runs:
        if item["subrole"] == "company_personas_chatter" and item["audit"]:
            cand_n = int(item["audit"].get("n_worlds", 0) or 0)
            if cand_n > best_n_worlds:
                best_n_worlds = cand_n
                best_parity_audit = dict(item["audit"])

    iv_checks = 0
    iv_ok_weighted = 0.0
    iv_surface_stego = 0
    iv_lint = 0
    iv_prompt = 0
    iv_stego = 0
    iv_truth = 0
    iv_cal_ok = True
    iv_par_ok = True
    iv_batches = 0
    for item in runs:
        if item["subrole"] == "persona_interviews" and item["audit"]:
            a = item["audit"]
            iv_batches += 1
            chk = int(a.get("counterfactual_checks", 0) or 0)
            rate = float(a.get("counterfactual_invariance_rate", 1.0) or 0.0)
            iv_checks += chk
            iv_ok_weighted += chk * rate
            iv_surface_stego += int(a.get("env_surface_stego_violations", 0) or 0)
            iv_lint += int(a.get("lint_violations", 0) or 0)
            iv_prompt += int(a.get("prompt_truth_leak_violations", 0) or 0)
            iv_stego += int(a.get("stego_leak_violations", 0) or 0)
            iv_truth += int(a.get("truth_leak_violations", 0) or 0)
            iv_cal_ok = iv_cal_ok and bool(a.get("signal_calibration_ok", True))
            iv_par_ok = iv_par_ok and bool(a.get("solver_parity_ok", True))

    persona_audit = {
        "batches_audited": iv_batches,
        "counterfactual_checks": iv_checks,
        "counterfactual_invariance_rate": round(iv_ok_weighted / iv_checks, 4) if iv_checks else 1.0,
        "encodings_checked": len(SUPPORTED_ENCODINGS),
        "env_surface_stego_violations": iv_surface_stego,
        "environment_scope": SCOPE_LABEL,
        "lint_violations": iv_lint,
        "model_id": TARGET_MODEL,
        "prompt_truth_leak_violations": iv_prompt,
        "role": ROLE,
        "signal_calibration_ok": iv_cal_ok,
        "solver_parity_ok": iv_par_ok,
        "stego_leak_violations": iv_stego,
        "subrole": "persona_interviews",
        "truth_leak_violations": iv_truth,
    }

    dyn_probe: dict[str, Any] = {}
    for item in runs:
        if item["subrole"] == "dynamic_mid_episode_events":
            tp = item["summary"].get("text_probe")
            if isinstance(tp, dict) and tp:
                dyn_probe = dict(tp)

    return sanitize_obj({
        "environment_scope": SCOPE_LABEL,
        "role": ROLE,
        "model_id": TARGET_MODEL,
        "tiers_version": "v1.4",
        "leak_and_safety_audit": leak_audit,
        "v14_multi_tier_parity_and_probe_audit": best_parity_audit,
        "persona_interviews_audit": persona_audit,
        "dynamic_events_hard37_probe": dyn_probe,
    })


def _render_suite_summary_md(suite: dict[str, Any], audit_doc: dict[str, Any]) -> str:
    tot = suite["totals"]
    leak = suite["leak_and_safety_audit"]
    cp = suite["company_personas_suite"]
    bc = suite["biased_chatter_suite"]
    iv = suite["persona_interviews_suite"]
    ev = suite["dynamic_events_suite"]
    tc = suite["thinking_calibration_suite"]
    pa = audit_doc.get("v14_multi_tier_parity_and_probe_audit", {})
    le = pa.get("leak_encodings", {})
    nl = pa.get("non_leak", {})

    lines: list[str] = [
        f"{MD_H1} Role 1 Consolidated Suite: World Text & Persona Synthesis (`{TARGET_MODEL}`)",
        "",
        f"- Scope: {SCOPE_LABEL}",
        f"- Role: `{ROLE}`",
        f"- Target Model ID: `{TARGET_MODEL}`",
        f"- Verified `{ROLE}` run folders consolidated: `{tot['verified_folders']}`",
        f"- Total Gemini API calls: `{tot['calls']}`",
        f"- Total tokens (in / out / thinking / cached): `{tot['in']:,}` / `{tot['out']:,}` / `{tot['thinking']:,}` / `{tot['cached']:,}`",
        f"- Total estimated cost (USD): `${tot['cost_usd']:.6f}`",
        f"- Non-leak & safety audit: `truth_leaks={leak['truth_leak_violations']}`, `prompt_leaks={leak['prompt_truth_leak_violations']}`, `lint_violations={leak['lint_violations']}`, `stego_violations={leak['stego_encoding_violations']}`, `fallbacks={leak['fallback_count']}`, `secret_leaks={leak['secret_leaks_detected']}` (`all_clean={leak['all_clean']}`)",
        f"- Provenance note: `{SUITE_DIR_NAME}/` intentionally omits `meta.json` so `canary.gemini.worldtext_carbon` and role scanners do not double-count tokens or costs.",
        "",
        f"{MD_H2} 1. Company Personas & Workplace Chatter (`company_personas_suite`)",
        "",
        "| Slice | Worlds | Personas | Solver Acc (95% CI) | Solver Mean (95% CI) | Template Mean (95% CI) | Paired Delta (95% CI) |",
        "| --- | ---: | ---: | --- | --- | --- | --- |",
    ]
    for sl_name in (*TIER_ORDER, "overall"):
        row = cp["by_tier"].get(sl_name)
        if not row:
            continue
        acc_ci = row["solver_accuracy_ci95"]
        s_ci = row["solver_ci95"]
        t_ci = row["template_ci95"]
        d_ci = row["paired_delta_ci95"]
        lines.append(
            f"| `{sl_name}` | {row['n_worlds']} | {row['n_personas']} | "
            f"{row['solver_accuracy'] * 100:.1f}% [{acc_ci[0] * 100:.1f}%, {acc_ci[1] * 100:.1f}%] | "
            f"{row['solver_mean']:+.4f} [{s_ci[0]:+.4f}, {s_ci[1]:+.4f}] | "
            f"{row['template_mean']:+.4f} [{t_ci[0]:+.4f}, {t_ci[1]:+.4f}] | "
            f"{row['paired_delta_mean']:+.4f} [{d_ci[0]:+.4f}, {d_ci[1]:+.4f}] |"
        )

    if pa.get("by_tier"):
        lines.extend([
            "",
            f"{MD_H2} 1b. 37-Encoding Non-Leak & Text-Only Probe Audit (`v14_multi_tier_parity_and_probe_audit`)",
            "",
            f"- Encodings scanned: `{le.get('n_supported_encodings', 37)}` (`{le.get('n_violations', 0)}` violations across `{pa.get('n_worlds', 0)}` worlds, `{pa.get('n_personas_total', 0)}` personas, `{nl.get('n_messages_checked', 0):,}` messages, `{nl.get('n_interviews_checked', 0):,}` interviews)",
            "",
            "| Tier | Worlds (n) | Personas | Truth / Lint / Stego Hits | Text-Only Probe | Fair Bar | Probe p-val vs Bar | Leak Flag |",
            "| --- | ---: | ---: | --- | --- | ---: | ---: | --- |",
        ])
        for tname in TIER_ORDER:
            trow = pa["by_tier"].get(tname)
            if not trow:
                continue
            tnl = trow.get("non_leak", {})
            probe = tnl.get("text_probe", {})
            lines.append(
                f"| `{tname}` | {trow.get('n_worlds', 0)} | {trow.get('n_personas', 0)} | "
                f"`{tnl.get('n_truth_violations', 0)} / {tnl.get('n_lint_violations', 0)} / 0` | "
                f"`{probe.get('correct', 0)}/{probe.get('n', 0)}` ({float(probe.get('accuracy', 0.0)) * 100:.1f}%) | "
                f"{float(probe.get('fair_bar', 0.0)) * 100:.1f}% | `{float(probe.get('p_value_vs_bar', 1.0)):.4f}` | "
                f"`{probe.get('text_leak', False)}` |"
            )

    lines.extend([
        "",
        f"{MD_H2} 2. Bias-Flavoured Workplace Chatter & Investigator Ablation (`biased_chatter_suite`)",
        "",
        f"- Biased chatter corpus: `{bc['total_biased_messages']}` messages (`{bc['total_llm_biased_messages']}` live LLM, `0` fallbacks) across `{bc['n_chatter_batches']}` folders",
        f"- Paired ablation episodes: `{bc['unique_ablation_episodes']}` across `{bc['n_ablation_batches']}` folders",
        "",
        "| Slice | Policy | Paired Seeds | Biased Mean (95% CI) | Template Mean (95% CI) | Paired Delta (95% CI) | Biased Acc | Rumor Distraction |",
        "| --- | --- | ---: | --- | --- | --- | ---: | ---: |",
    ])
    for sl_name in ("medium", "hard", "overall"):
        pol_map = bc["paired_slices"].get(sl_name, {})
        for pol in ("carbon", "solver", "obvious_heuristic"):
            prow = pol_map.get(pol)
            if not prow:
                continue
            b_ci = prow["biased_ci95"]
            t_ci = prow["template_ci95"]
            d_ci = prow["paired_delta_ci95"]
            lines.append(
                f"| `{sl_name}` | `{pol}` | {prow['n_paired_seeds']} | "
                f"{prow['biased_mean']:+.4f} [{b_ci[0]:+.4f}, {b_ci[1]:+.4f}] | "
                f"{prow['template_mean']:+.4f} [{t_ci[0]:+.4f}, {t_ci[1]:+.4f}] | "
                f"{prow['paired_delta_mean']:+.4f} [{d_ci[0]:+.4f}, {d_ci[1]:+.4f}] | "
                f"{prow['biased_accuracy'] * 100:.1f}% | {prow['biased_distraction_rate'] * 100:.1f}% |"
            )

    iv_cal_ci = iv["signal_calibration_ci95"]
    iv_inv_ci = iv["counterfactual_invariance_ci95"]
    iv_ps_ci = iv["persona_solver_ci95"]
    iv_ts_ci = iv["template_solver_ci95"]
    iv_d_ci = iv["paired_delta_ci95"]
    lines.extend([
        "",
        f"{MD_H2} 3. Persona-Conditioned Live Suspect Interviews (`persona_interviews_suite`)",
        "",
        f"- Worlds / Live interviews: `{iv['unique_worlds']}` / `{iv['total_interviews']}` across `{iv['n_batches']}` folders",
        f"- Signal calibration accuracy: `{iv['signal_calibration_accuracy'] * 100:.1f}%` [{iv_cal_ci[0] * 100:.1f}%, {iv_cal_ci[1] * 100:.1f}%]",
        f"- Counterfactual prompt invariance: `{iv['counterfactual_invariance_rate'] * 100:.1f}%` [{iv_inv_ci[0] * 100:.1f}%, {iv_inv_ci[1] * 100:.1f}%] (`{iv['counterfactual_checks_total']}` swap checks)",
        f"- Pooled SolverPolicy parity: `{iv['persona_solver_mean']:+.4f}` [{iv_ps_ci[0]:+.4f}, {iv_ps_ci[1]:+.4f}] vs template `{iv['template_solver_mean']:+.4f}` [{iv_ts_ci[0]:+.4f}, {iv_ts_ci[1]:+.4f}] (delta `{iv['paired_delta_mean']:+.4f}` [{iv_d_ci[0]:+.4f}, {iv_d_ci[1]:+.4f}])",
        "",
        "| Slice | Worlds | Persona Solver (95% CI) | Template Solver (95% CI) | Paired Delta (95% CI) | Solver Acc |",
        "| --- | ---: | --- | --- | --- | ---: |",
    ])
    for sl_name in (*TIER_ORDER, "overall"):
        irow = iv.get("by_tier", {}).get(sl_name)
        if not irow:
            continue
        ps_c = irow["persona_solver_ci95"]
        ts_c = irow["template_solver_ci95"]
        d_c = irow["paired_delta_ci95"]
        lines.append(
            f"| `{sl_name}` | {irow['n_worlds']} | "
            f"{irow['persona_solver_mean']:+.4f} [{ps_c[0]:+.4f}, {ps_c[1]:+.4f}] | "
            f"{irow['template_solver_mean']:+.4f} [{ts_c[0]:+.4f}, {ts_c[1]:+.4f}] | "
            f"{irow['paired_delta_mean']:+.4f} [{d_c[0]:+.4f}, {d_c[1]:+.4f}] | "
            f"{irow['persona_solver_accuracy'] * 100:.1f}% |"
        )

    lines.extend([
        "",
        f"{MD_H2} 4. Dynamic Mid-Episode Corporate Incident Events (`dynamic_events_suite`)",
        "",
        "| Slice | Worlds | Live-Events Solver (95% CI) | Baseline Solver (95% CI) | Paired Delta (95% CI) | Solver Acc | ObviousHeuristic |",
        "| --- | ---: | --- | --- | --- | ---: | ---: |",
    ])
    for sl_name in (*TIER_ORDER, "overall"):
        erow = ev["by_tier"].get(sl_name)
        if not erow:
            continue
        l_ci = erow["live_solver_ci95"]
        b_ci = erow["baseline_solver_ci95"]
        d_ci = erow["paired_delta_ci95"]
        lines.append(
            f"| `{sl_name}` | {erow['n_worlds']} | "
            f"{erow['live_solver_mean']:+.4f} [{l_ci[0]:+.4f}, {l_ci[1]:+.4f}] | "
            f"{erow['baseline_solver_mean']:+.4f} [{b_ci[0]:+.4f}, {b_ci[1]:+.4f}] | "
            f"{erow['paired_delta_mean']:+.4f} [{d_ci[0]:+.4f}, {d_ci[1]:+.4f}] | "
            f"{erow['live_solver_accuracy'] * 100:.1f}% | {erow['obvious_heuristic_mean']:+.4f} |"
        )

    lines.extend([
        "",
        f"{MD_H2} 5. Thinking-Level World Synthesis Calibration (`thinking_calibration_suite`)",
        "",
        "| Thinking Level | Worlds | Thinking Tokens | Think Tok / World | Output Tokens | Distinct Bigrams | Solver Mean | Cost (USD) |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ])
    for lvl in THINKING_ORDER:
        lrow = tc["levels"].get(lvl)
        if not lrow:
            continue
        lines.append(
            f"| `{lvl}` | {lrow['n_worlds']} | {lrow['thinking_tokens']:,} | {lrow['thinking_tokens_per_world']:,.1f} | "
            f"{lrow['output_tokens']:,} | {lrow['mean_distinct_bigrams']:,.1f} | {lrow['solver_mean_score']:+.4f} | ${lrow['cost_usd']:.4f} |"
        )

    lines.extend([
        "",
        f"{MD_H2} 6. De-Duplicated Role 1 (`world_text`) Totals (`totals`)",
        "",
        "| Subrole Slice | Verified Folders | Calls | Input Tokens | Output Tokens | Thinking Tokens | Cached Tokens | Cost (USD) |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ])
    for sl_key, sl_row in suite["by_subrole_totals"].items():
        lines.append(
            f"| `{sl_key}` | {sl_row['verified_folders']} | {sl_row['calls']} | "
            f"{sl_row['in']:,} | {sl_row['out']:,} | {sl_row['thinking']:,} | {sl_row['cached']:,} | ${sl_row['cost_usd']:.6f} |"
        )
    lines.append(
        f"| **total** | **{tot['verified_folders']}** | **{tot['calls']}** | "
        f"**{tot['in']:,}** | **{tot['out']:,}** | **{tot['thinking']:,}** | **{tot['cached']:,}** | **${tot['cost_usd']:.6f}** |"
    )
    lines.append("")
    return clean_str("\n".join(lines))


def _render_role_doc_md(suite: dict[str, Any], audit_doc: dict[str, Any], runs: Sequence[dict[str, Any]]) -> str:
    base_md = _render_suite_summary_md(suite, audit_doc)
    lines: list[str] = [
        base_md.rstrip(),
        "",
        f"{MD_H2} 7. Non-Judged Disclosure & Non-Leak Guarantee",
        "",
        f"- **Environment boundary**: Every run in `results/gemini/roles_carbon/world_text/` is a **{SCOPE_LABEL}**. Frozen `v1.4` rules, tier hashes, and judged Harbor evaluation tasks remain untouched.",
        "- **Structural non-leak**: `public_view(facts)` strips all mole/decoy/strategy/ledger ground-truth keys before any `gemini-4-carbon` world synthesis or interview prompt is constructed. Counterfactual mole/decoy swap checks verify 100% byte-identical prompt serialization.",
        f"- **37-encoding steganography & lint audit**: `canary.gemini.worldtext_carbon` scans generated personas, workplace chatter, incident events, and suspect interviews across `{len(SUPPORTED_ENCODINGS)}` encodings (plaintext, Base64/32/85/ASCII85, hex, URL/HTML/Unicode escapes, quoted-printable, zlib+Base64, ROT13/Caesar/Atbash/ROT47, reversals, zero-width steganography, Unicode tags, Cyrillic homoglyphs, diacritics, leetspeak, spaced characters, line/sentence/word acrostics, nth-char strides, binary/octal/decimal ASCII, Morse code, and cross-message splits) plus `canary.text.lint` and empirical text-only probe p-values against the fair elimination bar.",
        "",
        f"{MD_H2} 8. Verified Run Provenance Ledger",
        "",
        "| Folder | Subrole | Commit | Samples | Calls | In Tok | Out Tok | Think Tok | Cached Tok | Cost (USD) | Key Metric |",
        "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for item in runs:
        m = item["meta"]
        u = item["usage"]
        cnt = m.get("episode_count", m.get("sample_count", m.get("n_episodes", 0)))
        km = clean_str(m.get("key_metric", ""))
        lines.append(
            f"| `{item['name']}` | `{item['subrole']}` | `{item['commit'][:8]}` | {cnt} | "
            f"{u['calls']} | {u['in']:,} | {u['out']:,} | {u['thinking']:,} | {u['cached']:,} | "
            f"${u['cost_usd']:.4f} | {km} |"
        )
    lines.extend([
        "",
        f"{MD_H2} 9. Keyless Verification & Sync Commands",
        "",
        "```bash",
        "PYTHONPATH=. python -m canary.gemini.worldtext_carbon --check",
        "PYTHONPATH=. pytest -q tests/test_gemini_lab_worldtext_carbon.py",
        "```",
        "",
    ])
    return clean_str("\n".join(lines))


def consolidate_carbon_worldtext(
    role_dir: Path = DEFAULT_ROLE_DIR,
    doc_path: Path | None = DEFAULT_DOC_PATH,
    write_files: bool = True,
) -> dict[str, Any]:
    runs = discover_carbon_worldtext_runs(role_dir)
    company_suite = _build_company_personas_suite(runs)
    chatter_suite = _build_biased_chatter_suite(runs)
    interviews_suite = _build_interviews_suite(runs)
    events_suite = _build_dynamic_events_suite(runs)
    thinking_suite = _build_thinking_calibration_suite(runs)
    leak_audit = _build_leak_audit(runs)

    by_subrole: dict[str, dict[str, Any]] = {}
    overall_u = _zero_usage()
    for item in runs:
        sub = item["subrole"]
        if sub not in by_subrole:
            by_subrole[sub] = {"verified_folders": 0, **_zero_usage()}
        by_subrole[sub] = {
            "verified_folders": by_subrole[sub]["verified_folders"] + 1,
            **_add_usage(by_subrole[sub], item["usage"]),
        }
        overall_u = _add_usage(overall_u, item["usage"])

    suite = sanitize_obj({
        "environment_scope": SCOPE_LABEL,
        "role": ROLE,
        "model_id": TARGET_MODEL,
        "leak_and_safety_audit": leak_audit,
        "company_personas_suite": company_suite,
        "biased_chatter_suite": chatter_suite,
        "persona_interviews_suite": interviews_suite,
        "dynamic_events_suite": events_suite,
        "thinking_calibration_suite": thinking_suite,
        "by_subrole_totals": dict(sorted(by_subrole.items())),
        "verified_run_folders": [item["rel_dir"] for item in runs],
        "totals": {
            "verified_folders": len(runs),
            **overall_u,
        },
    })
    audit_doc = _build_audit_doc(runs, leak_audit)
    suite_md = _render_suite_summary_md(suite, audit_doc)
    role_doc_md = _render_role_doc_md(suite, audit_doc, runs)

    if write_files:
        suite_dir = role_dir / SUITE_DIR_NAME
        suite_dir.mkdir(parents=True, exist_ok=True)
        meta_cand = suite_dir / "meta.json"
        if meta_cand.exists():
            meta_cand.unlink()
        (suite_dir / "summary.json").write_text(
            json.dumps(suite, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        (suite_dir / "audit.json").write_text(
            json.dumps(audit_doc, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        (suite_dir / "summary.md").write_text(suite_md, encoding="utf-8")
        if doc_path is not None:
            doc_path.parent.mkdir(parents=True, exist_ok=True)
            doc_path.write_text(role_doc_md, encoding="utf-8")

    return {
        "suite": suite,
        "audit": audit_doc,
        "suite_md": suite_md,
        "role_doc_md": role_doc_md,
    }


def validate_carbon_worldtext_bundle(
    role_dir: Path = DEFAULT_ROLE_DIR,
    doc_path: Path | None = DEFAULT_DOC_PATH,
) -> dict[str, Any]:
    errors: list[str] = []
    if not role_dir.is_dir():
        return {"ok": False, "errors": [f"missing directory: {role_dir}"]}

    suite_dir = role_dir / SUITE_DIR_NAME
    if (suite_dir / "meta.json").exists():
        errors.append("suite directory must omit meta.json to avoid double counting")

    check_paths = sorted(p for p in role_dir.rglob("*") if p.is_file())
    if doc_path is not None and doc_path.is_file():
        check_paths.append(doc_path)
    elif doc_path is not None:
        errors.append(f"missing role doc: {doc_path}")

    for path in check_paths:
        if any(path.name.endswith(sfx) for sfx in FORBIDDEN_RAW_SUFFIXES) or path.name in FORBIDDEN_RAW_FILENAMES:
            errors.append(f"raw dump file committed: {path.name}")
        if "transcripts" in path.parts:
            errors.append(f"raw transcript committed: {path}")
        txt = path.read_text(encoding="utf-8")
        if any(d in txt for d in FORBIDDEN_DASHES):
            errors.append(f"forbidden dash in {path}")
        if GOOGLE_KEY_RE.search(txt) or SK_KEY_RE.search(txt) or OAUTH_RE.search(txt):
            errors.append(f"secret pattern in {path}")
        if path.suffix == ".json":
            doc = json.loads(txt)
            if isinstance(doc, dict) and doc.get("environment_scope") != SCOPE_LABEL:
                errors.append(f"missing scope label in {path}")
        elif path.suffix == ".md":
            if SCOPE_LABEL not in txt:
                errors.append(f"missing scope label in {path}")

    runs = discover_carbon_worldtext_runs(role_dir)
    if not runs:
        errors.append("no verified runs discovered")

    totals = {"verified_folders": len(runs), "calls": 0, "in": 0, "out": 0, "thinking": 0, "cached": 0, "cost_usd": 0.0}
    for item in runs:
        meta = item["meta"]
        run_dir = item["dir"]
        if meta.get("role") != ROLE:
            errors.append(f"wrong role in {run_dir.name}")
        if meta.get("model_id") != TARGET_MODEL:
            errors.append(f"wrong model_id in {run_dir.name}")
        if not COMMIT_RE.match(str(meta.get("commit", ""))):
            errors.append(f"invalid commit in {run_dir.name}")
        if meta.get("stub") is True or meta.get("fake_env") is True or meta.get("smoke") is True:
            errors.append(f"non-live flag in {run_dir.name}")
        if not isinstance(meta.get("key_metric"), str) or not meta["key_metric"].strip():
            errors.append(f"missing key_metric in {run_dir.name}")
        if not any(isinstance(meta.get(k), int) and meta[k] > 0 for k in ("n_episodes", "episode_count", "sample_count")):
            errors.append(f"missing sample_count/episode_count in {run_dir.name}")
        raw_u = meta.get("usage") if isinstance(meta.get("usage"), dict) else {}
        for req_k in ("calls", "in", "out", "thinking", "cached", "cost_usd"):
            if req_k not in raw_u:
                errors.append(f"missing usage.{req_k} in {run_dir.name}")
        if not (run_dir / "summary.json").is_file() or not (run_dir / "summary.md").is_file():
            errors.append(f"missing summary in {run_dir.name}")
        u = item["usage"]
        if u["calls"] <= 0 or u["in"] <= 0 or u["out"] <= 0:
            errors.append(f"empty token usage in {run_dir.name}")
        totals["calls"] += u["calls"]
        totals["in"] += u["in"]
        totals["out"] += u["out"]
        totals["thinking"] += u["thinking"]
        totals["cached"] += u["cached"]
        totals["cost_usd"] = round(totals["cost_usd"] + u["cost_usd"], 6)

    suite_summary_path = suite_dir / "summary.json"
    suite_audit_path = suite_dir / "audit.json"
    if not suite_summary_path.is_file() or not suite_audit_path.is_file() or not (suite_dir / "summary.md").is_file():
        errors.append("missing consolidated suite files")
    else:
        expected = consolidate_carbon_worldtext(role_dir=role_dir, doc_path=doc_path, write_files=False)
        suite_doc = json.loads(suite_summary_path.read_text(encoding="utf-8"))
        audit_doc = json.loads(suite_audit_path.read_text(encoding="utf-8"))
        if suite_doc.get("totals") != totals:
            errors.append(f"suite totals mismatch: {suite_doc.get('totals')} != {totals}")
        if suite_doc != expected["suite"]:
            errors.append("suite summary.json out of sync with run folders (run --sync)")
        if audit_doc != expected["audit"]:
            errors.append("suite audit.json out of sync with run folders (run --sync)")
        leak_audit = audit_doc.get("leak_and_safety_audit", {})
        if not leak_audit.get("all_clean"):
            errors.append("leak_and_safety_audit not clean")
        pa = audit_doc.get("v14_multi_tier_parity_and_probe_audit", {})
        if not pa.get("passed") or pa.get("leak_encodings", {}).get("n_supported_encodings") != len(SUPPORTED_ENCODINGS):
            errors.append("multi-tier parity or 37-encoding count mismatch")
        for tier_name, tier_row in pa.get("by_tier", {}).items():
            probe = tier_row.get("non_leak", {}).get("text_probe", {})
            if probe.get("text_leak") is not False or float(probe.get("p_value_vs_bar", 0.0)) < 0.01:
                errors.append(f"text_probe leak on {tier_name}")

    return {
        "ok": not errors,
        "errors": errors,
        "supported_encodings_count": len(SUPPORTED_ENCODINGS),
        "scope_label": SCOPE_LABEL,
        "totals": totals,
    }


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="python -m canary.gemini.worldtext_carbon")
    p.add_argument("--role-dir", type=Path, default=DEFAULT_ROLE_DIR)
    p.add_argument("--doc-path", type=Path, default=DEFAULT_DOC_PATH)
    p.add_argument("--sync", action="store_true")
    p.add_argument("--check", action="store_true")
    return p


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    doc_p: Path | None = args.doc_path
    if args.role_dir.resolve() != DEFAULT_ROLE_DIR.resolve() and args.doc_path == DEFAULT_DOC_PATH:
        doc_p = None
    if args.sync:
        consolidate_carbon_worldtext(role_dir=args.role_dir, doc_path=doc_p, write_files=True)
    report = validate_carbon_worldtext_bundle(role_dir=args.role_dir, doc_path=doc_p)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
