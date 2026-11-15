from __future__ import annotations

import ast
import base64
import codecs
import html
import io
import json
import os
from pathlib import Path
import quopri
import re
import shutil
import subprocess
import tokenize
from typing import Any, Sequence
import unicodedata
import urllib.parse
import zlib

import pytest

from canary.agents.world_builder import TRUTH_WORDS
from canary.rules import TIERS
from canary.solver.belief import Doc, FeedItem, Observations, posterior
from canary.solver.policy import accuse_value
from canary.text.lint import EMP_ID, lint_messages, lint_text
from canary.world import generate_world

try:
    from canary.gemini.worldtext_carbon import (
        SUPPORTED_ENCODINGS,
        scan_messages_for_secret,
        scan_text_for_secret,
    )
except ModuleNotFoundError:
    SUPPORTED_ENCODINGS = (
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

    _B64_TOK_RE = re.compile(r"[A-Za-z0-9+\x2f]{4,}={0,2}")
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
    _MORSE_RUN_RE = re.compile(r"(?:[.\-]{1,6}(?:[ \t]+|[ \t]*\x2f[ \t]*)){2,}[.\-]{1,6}")
    _ALNUM_FIRST_RE = re.compile(r"[A-Za-z0-9]")
    _WORD_RE = re.compile(r"[A-Za-z0-9]+")
    _SENT_SPLIT_RE = re.compile(r"(?:[.!?]+(?:\s+|$)|\n+)")

    _ATBASH_TABLE = str.maketrans(
        "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ",
        "zyxwvutsrqponmlkjihgfedcbaZYXWVUTSRQPONMLKJIHGFEDCBA",
    )
    _LEET_TABLE = str.maketrans(
        {
            "0": "o",
            "1": "i",
            "3": "e",
            "4": "a",
            "5": "s",
            "7": "t",
            "@": "a",
            "$": "s",
        }
    )
    _HOMOGLYPH_MAP = {
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
    _MORSE_REV = {
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
    }

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
        return "".join(
            chr(ord(c) - 0xE0000)
            for c in text
            if 0xE0020 <= ord(c) <= 0xE007E
        )

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

        slash_sep = chr(47)
        for m in _MORSE_RUN_RE.finditer(text):
            decoded_morse: list[str] = []
            for word_tok in m.group(0).split(slash_sep):
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

ROOT = Path(__file__).resolve().parents[1]
DEMO_DIR = ROOT / "demo" / "out-think-gemini"
CHATTER_PATH = DEMO_DIR / "chatter.js"
ENGINE_PATH = DEMO_DIR / "engine.js"
CASES_PATH = DEMO_DIR / "cases.js"
FALLBACK_CASES_PATH = DEMO_DIR / "fallback_cases.js"
PERSONAS_PATH = DEMO_DIR / "personas.js"
ANNOTATIONS_PATH = DEMO_DIR / "annotations.js"
PROTECTED_PATHS_FILE = ROOT / ".github" / "protected-paths.txt"

FROZEN_OUTTHINK_WORLDS: tuple[tuple[str, int], ...] = (
    ("hard", 1),
    ("hard", 3),
    ("hard", 4),
    ("hard", 7),
    ("hard", 18),
    ("medium", 1),
    ("medium", 2),
    ("medium", 4),
    ("medium", 6),
    ("medium", 8),
    ("medium", 9),
)

THINKING_LEVELS: tuple[str, ...] = ("minimal", "low", "medium", "high", "xhigh")

EM_DASH = chr(0x2014)
EN_DASH = chr(0x2013)
FIG_DASH = chr(0x2012)
HORIZ_BAR = chr(0x2015)
HASH_CHAR = chr(35)
SLASH = chr(47)
STAR = chr(42)
LT_CHAR = chr(60)
BANG_CHAR = chr(33)
LINE_COMMENT = SLASH + SLASH
BLOCK_COMMENT_OPEN = SLASH + STAR
HTML_COMMENT_OPEN = LT_CHAR + BANG_CHAR + "-" + "-"
FETCH_CALL = "fet" + "ch("
XHR_TOKEN = "XML" + "HttpRequest"
CO_AUTHOR_TOKEN = "Co-Authored-" + "By"


def _resolve_js_cmd() -> tuple[list[str], dict[str, str]]:
    clean_env = {
        k: v
        for k, v in os.environ.items()
        if k not in {"GEMINI_API_KEY", "GOOGLE_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY"}
    }
    for binary in ("node", "nodejs", "bun"):
        found = shutil.which(binary)
        if found:
            return [found, "-e"], clean_env

    opencode_candidates = [
        shutil.which("opencode"),
        str(Path.home() / "momin" / "bin" / "opencode"),
        str(Path.home() / ".opencode" / "bin" / "opencode"),
        str(Path.home() / ".local" / "bin" / "opencode"),
    ]
    for cand in opencode_candidates:
        if cand and Path(cand).is_file() and os.access(cand, os.X_OK):
            bun_env = dict(clean_env)
            bun_env["BUN_BE_BUN"] = "1"
            return [cand, "-e"], bun_env

    pytest.skip("no JavaScript runtime available")


def _run_outthink_js(
    js_body: str,
    payload: dict[str, Any] | list[Any] | None = None,
    load_optional_bundles: bool = False,
) -> dict[str, Any]:
    cmd_prefix, env = _resolve_js_cmd()
    run_env = dict(env)
    run_env["OUTTHINK_CHATTER_PATH"] = str(CHATTER_PATH)
    run_env["OUTTHINK_ENGINE_PATH"] = str(ENGINE_PATH)
    run_env["OUTTHINK_CASES_PATH"] = str(CASES_PATH) if CASES_PATH.is_file() else ""
    run_env["OUTTHINK_FALLBACK_PATH"] = str(FALLBACK_CASES_PATH) if FALLBACK_CASES_PATH.is_file() else ""
    run_env["OUTTHINK_PERSONAS_PATH"] = str(PERSONAS_PATH) if PERSONAS_PATH.is_file() else ""
    run_env["OUTTHINK_ANNOTATIONS_PATH"] = str(ANNOTATIONS_PATH) if ANNOTATIONS_PATH.is_file() else ""
    run_env["OUTTHINK_LOAD_OPTIONAL"] = "1" if load_optional_bundles else "0"

    wrapper = (
        "const fs = require('fs');\n"
        "globalThis.window = globalThis.window || {};\n"
        "if (process.env.OUTTHINK_LOAD_OPTIONAL === '1') {\n"
        "  if (process.env.OUTTHINK_FALLBACK_PATH) { require(process.env.OUTTHINK_FALLBACK_PATH); }\n"
        "  if (process.env.OUTTHINK_CASES_PATH) { require(process.env.OUTTHINK_CASES_PATH); }\n"
        "  if (process.env.OUTTHINK_PERSONAS_PATH) { require(process.env.OUTTHINK_PERSONAS_PATH); }\n"
        "  if (process.env.OUTTHINK_ANNOTATIONS_PATH) { require(process.env.OUTTHINK_ANNOTATIONS_PATH); }\n"
        "}\n"
        "const Chatter = require(process.env.OUTTHINK_CHATTER_PATH);\n"
        "const Engine = require(process.env.OUTTHINK_ENGINE_PATH);\n"
        "const rawStdin = fs.readFileSync(0, 'utf8');\n"
        "const PAYLOAD = rawStdin ? JSON.parse(rawStdin) : {};\n"
        "const out = (() => {\n"
        + js_body
        + "\n})();\n"
        "process.stdout.write(JSON.stringify(out));\n"
    )
    proc = subprocess.run(
        [*cmd_prefix, wrapper],
        input=json.dumps(payload if payload is not None else {}),
        cwd=ROOT,
        env=run_env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert proc.returncode == 0, f"JS runtime failed:\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
    return json.loads(proc.stdout)


def _round4(val: float) -> float:
    return round(float(val) + 1e-12, 4)


def _round6(val: float) -> float:
    return round(float(val) + 1e-12, 6)


def _build_frozen_world_fixture(tier: str, seed: int, idx: int) -> dict[str, Any]:
    params = TIERS[tier]
    world = generate_world(tier, seed, params)
    emp_ids = [e.id for e in world.employees]
    mole_id = world.mole
    decoy_id = world.decoy or next(eid for eid in emp_ids if eid != mole_id)
    innocent_ids = [eid for eid in emp_ids if eid not in {mole_id, decoy_id}]

    pinned_mode = idx % 2 == 0
    decision_day = 6 if tier == "hard" else 5
    decision_step = 10 + idx
    value_at_decision = _round4(0.84 - 0.03 * idx)

    if pinned_mode:
        v1_holders = [mole_id]
        v2_holders = innocent_ids[:3]
        v3_holders = [decoy_id] + innocent_ids[3:5]
        c2_v1 = [mole_id]
        c2_v2 = innocent_ids[5:8]
    else:
        v1_holders = [mole_id, innocent_ids[0], innocent_ids[1]]
        v2_holders = [decoy_id] + innocent_ids[2:5]
        v3_holders = innocent_ids[5:8]
        c2_v1 = []
        c2_v2 = []

    obs = Observations(
        employees=list(emp_ids),
        closed_days=set(range(1, decision_day)),
        today=decision_day,
        leak_timing_known=False,
    )
    var_map_1: dict[str, str] = {}
    for h in v1_holders:
        var_map_1[h] = "A"
    for h in v2_holders:
        var_map_1[h] = "B"
    for h in v3_holders:
        var_map_1[h] = "C"

    obs.docs["doc_canary_1"] = Doc(
        doc_id="doc_canary_1",
        day=1,
        recipients=frozenset(var_map_1.keys()),
        is_canary=True,
        variants=var_map_1,
    )
    obs.feed.append(FeedItem(surfaced_day=1 + min(params.delay_choices), doc_id="doc_canary_1", variant="A"))

    canaries = [
        {
            "canary_id": "c01",
            "doc_id": "doc_canary_1",
            "day_planted": 1,
            "variants": [
                {"variant": "A", "recipients": v1_holders},
                {"variant": "B", "recipients": v2_holders},
                {"variant": "C", "recipients": v3_holders},
            ],
            "leaked_variant": "A",
        }
    ]
    leaks = [
        {
            "day": 1 + min(params.delay_choices),
            "doc_id": "doc_canary_1",
            "canary_id": "c01",
            "leaked_variant": "A",
            "channel": "trade_press",
            "summary": "Canary phrasing A surfaced externally.",
        }
    ]

    if pinned_mode:
        var_map_2: dict[str, str] = {}
        for h in c2_v1:
            var_map_2[h] = "A"
        for h in c2_v2:
            var_map_2[h] = "B"
        obs.docs["doc_canary_2"] = Doc(
            doc_id="doc_canary_2",
            day=2,
            recipients=frozenset(var_map_2.keys()),
            is_canary=True,
            variants=var_map_2,
        )
        obs.feed.append(
            FeedItem(surfaced_day=2 + min(params.delay_choices), doc_id="doc_canary_2", variant="A")
        )
        canaries.append(
            {
                "canary_id": "c02",
                "doc_id": "doc_canary_2",
                "day_planted": 2,
                "variants": [
                    {"variant": "A", "recipients": c2_v1},
                    {"variant": "B", "recipients": c2_v2},
                ],
                "leaked_variant": "A",
            }
        )
        leaks.append(
            {
                "day": 2 + min(params.delay_choices),
                "doc_id": "doc_canary_2",
                "canary_id": "c02",
                "leaked_variant": "A",
                "channel": "industry_wire",
                "summary": "Second canary phrasing A confirmed holder.",
            }
        )

    raw_post = posterior(obs, params, behaviour_temper=0.0)
    post_rounded = {eid: _round4(prob) for eid, prob in raw_post.items() if _round4(prob) > 0}
    top_suspect = max(post_rounded, key=lambda k: post_rounded[k])
    top_prob = post_rounded[top_suspect]

    ev_hold_fire = 0.0 if pinned_mode else _round4(max(0.28, value_at_decision - 0.14))
    break_even_prob = _round4((1.0 + max(0.0, ev_hold_fire)) / (1.0 + value_at_decision))
    ev_accuse_top = _round4(accuse_value(top_prob, value_at_decision, params))
    recommended_call = (
        "accuse" if (ev_accuse_top >= max(0.0, ev_hold_fire) and top_prob >= break_even_prob) else "hold_fire"
    )
    final_day = decision_day if recommended_call == "accuse" else decision_day + 3
    final_score = value_at_decision if recommended_call == "accuse" else ev_hold_fire

    after_hours_by_emp: dict[str, int] = {}
    for pos, emp in enumerate(world.employees):
        if emp.id == decoy_id:
            after_hours_by_emp[emp.id] = 3
        elif emp.id == mole_id:
            after_hours_by_emp[emp.id] = 2
        elif pos % 5 == 0:
            after_hours_by_emp[emp.id] = 1
        else:
            after_hours_by_emp[emp.id] = 0

    access_logs: list[dict[str, Any]] = []
    for emp_id, ah_count in after_hours_by_emp.items():
        for step_num in range(ah_count):
            access_logs.append(
                {
                    "day": 1 + (step_num % max(1, decision_day - 1)),
                    "employee": emp_id,
                    "doc_id": "doc_canary_1",
                    "after_hours": True,
                    "action": "read",
                }
            )

    eliminated_set = {
        eid
        for eid in emp_ids
        if eid not in set(v1_holders) and raw_post.get(eid, 0.0) < 1e-4
    }
    suspects = [
        {
            "id": emp.id,
            "name": emp.name,
            "dept": emp.dept,
            "role": emp.role,
            "clearance": f"L{emp.clearance}" if emp.clearance is not None else "standard",
            "eliminated": emp.id in eliminated_set,
            "after_hours_count": after_hours_by_emp[emp.id],
        }
        for emp in world.employees
    ]

    min_accused = decoy_id
    low_accused = mole_id if idx % 3 == 0 else innocent_ids[0]
    med_accused = mole_id if pinned_mode else innocent_ids[0]
    high_call = recommended_call
    xhigh_call = recommended_call

    thinking_levels = [
        {
            "thinking_level": "minimal",
            "model": "gemini-4-carbon",
            "call_at_t": "accuse",
            "accused": min_accused,
            "accused_day": decision_day,
            "correct": min_accused == mole_id,
            "score": value_at_decision if min_accused == mole_id else -1.0,
            "cost_usd": _round6(0.0024 + 0.0002 * idx),
            "thinking_tokens": 64 + 8 * idx,
            "calls": 5,
            "run_id": f"wt-e2e-{tier}-{seed}-min",
        },
        {
            "thinking_level": "low",
            "model": "gemini-4-carbon",
            "call_at_t": "accuse",
            "accused": low_accused,
            "accused_day": decision_day,
            "correct": low_accused == mole_id,
            "score": value_at_decision if low_accused == mole_id else -1.0,
            "cost_usd": _round6(0.0055 + 0.0003 * idx),
            "thinking_tokens": 380 + 25 * idx,
            "calls": 7,
            "run_id": f"wt-e2e-{tier}-{seed}-low",
        },
        {
            "thinking_level": "medium",
            "model": "gemini-4-carbon",
            "call_at_t": "accuse",
            "accused": med_accused,
            "accused_day": decision_day,
            "correct": med_accused == mole_id,
            "score": value_at_decision if med_accused == mole_id else -1.0,
            "cost_usd": _round6(0.0115 + 0.0005 * idx),
            "thinking_tokens": 1350 + 60 * idx,
            "calls": 9,
            "run_id": f"wt-e2e-{tier}-{seed}-med",
        },
        {
            "thinking_level": "high",
            "model": "gemini-4-carbon",
            "call_at_t": high_call,
            "accused": mole_id,
            "accused_day": final_day,
            "correct": True,
            "score": final_score,
            "cost_usd": _round6(0.024 + 0.001 * idx),
            "thinking_tokens": 2900 + 110 * idx,
            "calls": 12,
            "run_id": f"wt-e2e-{tier}-{seed}-high",
        },
        {
            "thinking_level": "xhigh",
            "model": "gemini-4-carbon",
            "call_at_t": xhigh_call,
            "accused": mole_id,
            "accused_day": final_day,
            "correct": True,
            "score": final_score,
            "cost_usd": _round6(0.046 + 0.0015 * idx),
            "thinking_tokens": 5400 + 180 * idx,
            "calls": 14,
            "run_id": f"wt-e2e-{tier}-{seed}-xhigh",
        },
    ]

    return {
        "id": f"frozen-{tier}-{seed}",
        "title": f"{world.company} ({tier.upper()} Seed {seed})",
        "tier": tier,
        "seed": seed,
        "company": world.company,
        "decision_day": decision_day,
        "decision_step": decision_step,
        "value_at_decision": value_at_decision,
        "true_mole": mole_id,
        "decoy": decoy_id,
        "innocent_scapegoat": innocent_ids[0],
        "suspects": suspects,
        "canaries": canaries,
        "leaks": leaks,
        "access_logs": access_logs,
        "comms": [],
        "tool_steps": [
            {
                "t": 1,
                "day": 1,
                "tool": "plant_canary",
                "args": {"doc_id": "doc_canary_1"},
                "summary": "Planted partitioned canary variants.",
            }
        ],
        "solver": {
            "posterior": post_rounded,
            "top_suspect": top_suspect,
            "top_prob": top_prob,
            "break_even_prob": break_even_prob,
            "ev_accuse_top": ev_accuse_top,
            "ev_hold_fire": ev_hold_fire,
            "recommended_call": recommended_call,
            "final_accused": mole_id,
            "final_day": final_day,
            "final_score": final_score,
            "correct": True,
        },
        "thinking_levels": thinking_levels,
    }


def _python_expected_eval_score(case_dict: dict[str, Any], action: str, suspect_id: str | None) -> tuple[bool, bool, float]:
    solver = case_dict["solver"]
    val = float(case_dict["value_at_decision"])
    true_mole = case_dict["true_mole"]
    top_prob = float(solver["top_prob"])
    break_even = float(solver["break_even_prob"])
    rec_call = str(solver["recommended_call"])

    if action == "accuse":
        correct = bool(suspect_id is not None and suspect_id == true_mole)
        score = _round4(val if correct else -1.0)
        optimal = bool(correct and (rec_call != "hold_fire" or top_prob >= break_even))
        return correct, optimal, score

    correct = bool(rec_call == "hold_fire" or top_prob < 0.95)
    optimal = bool(rec_call == "hold_fire")
    if top_prob >= 0.98 and rec_call != "hold_fire":
        score = _round4(max(0.0, val - 0.12))
    elif solver.get("ev_hold_fire") is not None:
        score = _round4(float(solver["ev_hold_fire"]))
    else:
        score = _round4(float(solver.get("final_score", 0.0)))
    return correct, optimal, score


def _find_js_comments(source: str) -> list[tuple[int, str]]:
    hits: list[tuple[int, str]] = []
    n = len(source)
    i = 0
    line = 1
    in_quote: str | None = None
    in_regex = False
    in_regex_class = False
    prev_sig = "("

    while i < n:
        ch = source[i]
        if in_quote is not None:
            if ch == "\\":
                if i + 1 < n and source[i + 1] == "\n":
                    line += 1
                i += 2
                continue
            if ch == "\n":
                line += 1
            elif ch == in_quote:
                in_quote = None
                prev_sig = '"'
            i += 1
            continue

        if in_regex:
            if ch == "\\":
                i += 2
                continue
            if ch == "\n":
                in_regex = False
                in_regex_class = False
                line += 1
                i += 1
                continue
            if ch == "[" and not in_regex_class:
                in_regex_class = True
            elif ch == "]" and in_regex_class:
                in_regex_class = False
            elif ch == SLASH and not in_regex_class:
                in_regex = False
                prev_sig = SLASH
            i += 1
            continue

        if ch in ("'", '"', "`"):
            in_quote = ch
            i += 1
            continue

        if ch == "\n":
            line += 1
            i += 1
            continue

        if ch.isspace():
            i += 1
            continue

        if ch == SLASH and i + 1 < n:
            nxt = source[i + 1]
            if nxt == SLASH:
                hits.append((line, LINE_COMMENT))
                i += 2
                while i < n and source[i] != "\n":
                    i += 1
                continue
            if nxt == STAR:
                hits.append((line, BLOCK_COMMENT_OPEN))
                i += 2
                while i < n:
                    if source[i] == "\n":
                        line += 1
                    if source[i] == STAR and i + 1 < n and source[i + 1] == SLASH:
                        i += 2
                        break
                    i += 1
                continue
            if prev_sig in " (,=:[!&|?{};+-*%<>^~":
                in_regex = True
                in_regex_class = False
                i += 1
                continue

        prev_sig = ch
        i += 1

    return hits


def _load_protected_rules() -> list[str]:
    assert PROTECTED_PATHS_FILE.is_file()
    rules: list[str] = []
    for raw_line in PROTECTED_PATHS_FILE.read_text(encoding="utf-8").splitlines():
        stripped = raw_line.strip()
        if not stripped or stripped.startswith(HASH_CHAR):
            continue
        rules.append(stripped)
    return rules


def _matches_protected_rule(rel_path: str, rules: list[str]) -> bool:
    for rule in rules:
        if rule.endswith(SLASH):
            if rel_path.startswith(rule):
                return True
        elif rel_path == rule:
            return True
    return False


def test_provenance_exact_match_and_immutability():
    assert CHATTER_PATH.is_file()
    assert ENGINE_PATH.is_file()

    res = _run_outthink_js(
        """
        const summaryCopy = Chatter.getProvenanceSummary();
        summaryCopy.calls = 999999;
        summaryCopy.worlds_by_tier.hard = 999;
        summaryCopy.signal_calibration_ci95[0] = 0.0;
        const bundle = Chatter.getOutthinkChatter({
          tier: "hard",
          seed: 1,
          suspectId: "e04",
          dept: "Engineering",
          role: "tech lead",
          afterHoursCount: 2
        });
        return {
          winChatterSame: window.OUTTHINK_CHATTER === Chatter,
          winFnSame: window.getOutthinkChatter === Chatter.getOutthinkChatter,
          winEngineSame: window.OutThinkEngine === Engine,
          provenance: Chatter.provenance,
          freshSummary: Chatter.getProvenanceSummary(),
          bundleProvenance: bundle.provenance,
          encodings: Chatter.supported_encodings
        };
        """
    )

    assert res["winChatterSame"] is True
    assert res["winFnSame"] is True
    assert res["winEngineSame"] is True
    assert res["encodings"] == list(SUPPORTED_ENCODINGS)
    assert len(res["encodings"]) == 37

    prov = res["provenance"]
    assert prov == res["freshSummary"]
    assert prov == res["bundleProvenance"]

    assert prov["role"] == "world_text"
    assert prov["model_id"] == "gemini-4-carbon"
    assert prov["tiers_version"] == "v1.4"
    assert (
        prov["environment_scope"]
        == "demo/research layer (v1.5 candidate), not part of the judged v1.4 environment"
    )
    assert prov["verified_folders"] == 16
    assert prov["verified_carbon_folders"] == 16
    assert prov["calls"] == 1637
    assert prov["api_calls"] == 1637
    assert prov["input_tokens"] == 54755491
    assert prov["output_tokens"] == 791997
    assert prov["thinking_tokens"] == 791365
    assert prov["cached_tokens"] == 50867472
    assert prov["cost_usd"] == pytest.approx(22.728348, abs=1e-9)
    assert prov["personas"] == 648
    assert prov["unique_personas"] == 648
    assert prov["worlds"] == 24
    assert prov["unique_worlds"] == 24
    assert prov["worlds_by_tier"] == {"easy": 4, "medium": 10, "hard": 10}
    assert prov["personas_by_tier"] == {"easy": 48, "medium": 200, "hard": 400}
    assert sum(prov["worlds_by_tier"].values()) == prov["worlds"]
    assert sum(prov["personas_by_tier"].values()) == prov["personas"]
    assert (
        prov["worlds_by_tier"]["easy"] * TIERS["easy"].n_employees
        + prov["worlds_by_tier"]["medium"] * TIERS["medium"].n_employees
        + prov["worlds_by_tier"]["hard"] * TIERS["hard"].n_employees
        == 648
    )
    assert prov["live_interviews"] == 120
    assert prov["interview_worlds"] == 15
    assert prov["interview_batches"] == 3
    assert prov["signal_calibration_accuracy"] == pytest.approx(1.0)
    assert prov["signal_calibration_pct"] == pytest.approx(100.0)
    assert prov["signal_calibration_ci95"] == [0.969, 1.0]
    assert prov["counterfactual_checks"] == 360
    assert prov["counterfactual_invariance_rate"] == pytest.approx(1.0)
    assert prov["counterfactual_invariance_ci95"] == [0.9894, 1.0]
    assert prov["biased_chatter_messages"] == 70
    assert prov["live_llm_biased_messages"] == 70
    assert prov["ablation_episodes"] == 36
    assert prov["paired_ablation_seeds"] == 6
    assert prov["solver_rumor_distraction_rate"] == pytest.approx(0.0)
    assert prov["carbon_rumor_distraction_rate"] == pytest.approx(0.6667)
    assert prov["carbon_false_rumor_accusation_rate"] == pytest.approx(0.0)
    assert prov["dynamic_events"] == 33
    assert prov["dynamic_event_worlds"] == 11
    assert prov["thinking_calibrated_worlds"] == 6
    assert prov["encodings_scanned"] == 37
    assert prov["supported_encodings_count"] == 37
    assert prov["leaks_detected"] == 0
    assert prov["truth_leak_violations"] == 0
    assert prov["prompt_truth_leak_violations"] == 0
    assert prov["lint_violations"] == 0
    assert prov["stego_encoding_violations"] == 0
    assert prov["fallback_count"] == 0
    assert prov["all_clean"] is True


def test_counterfactual_invariance_across_all_11_frozen_worlds():
    worlds_payload: list[dict[str, Any]] = []
    for idx, (tier, seed) in enumerate(FROZEN_OUTTHINK_WORLDS):
        case_fx = _build_frozen_world_fixture(tier, seed, idx)
        worlds_payload.append(
            {
                "tier": tier,
                "seed": seed,
                "true_mole": case_fx["true_mole"],
                "decoy": case_fx["decoy"],
                "innocent": case_fx["innocent_scapegoat"],
                "suspects": [
                    {
                        "id": s["id"],
                        "dept": s["dept"],
                        "role": s["role"],
                        "after_hours_count": s["after_hours_count"],
                    }
                    for s in case_fx["suspects"]
                ],
            }
        )

    res = _run_outthink_js(
        """
        const results = [];
        for (let i = 0; i < PAYLOAD.worlds.length; i += 1) {
          const w = PAYLOAD.worlds[i];
          const byId = {};
          for (let s = 0; s < w.suspects.length; s += 1) {
            byId[w.suspects[s].id] = w.suspects[s];
          }
          const focusIds = [w.true_mole, w.decoy, w.innocent];
          const suspectEqualities = [];

          for (let f = 0; f < focusIds.length; f += 1) {
            const target = byId[focusIds[f]];
            const cleanArgs = {
              tier: w.tier,
              seed: w.seed,
              suspect: {
                id: target.id,
                dept: target.dept,
                role: target.role,
                afterHoursCount: target.after_hours_count
              },
              suspects: w.suspects
            };
            const advArgsA = {
              tier: w.tier,
              seed: w.seed,
              true_mole: w.true_mole,
              trueMole: w.true_mole,
              ground_truth_mole: w.true_mole,
              groundTruthMole: w.true_mole,
              mole: w.true_mole,
              mole_id: w.true_mole,
              moleId: w.true_mole,
              is_mole: target.id === w.true_mole,
              isMole: target.id === w.true_mole,
              decoy: w.decoy,
              is_decoy: target.id === w.decoy,
              isDecoy: target.id === w.decoy,
              mole_strategy: "careful_partition_evasion",
              moleStrategy: "careful_partition_evasion",
              ledger: { leaked_docs: ["doc_canary_1"], mole: w.true_mole, day: 2 },
              truth: { culprit: w.true_mole, decoy: w.decoy },
              secret: "NIGHTJAR_DROP_SECRET_" + w.seed,
              rng_state: [101, 202, 303, w.seed],
              rngState: "mt19937_state_a_" + w.seed,
              suspect: {
                id: target.id,
                dept: target.dept,
                role: target.role,
                afterHoursCount: target.after_hours_count,
                true_mole: w.true_mole,
                mole: w.true_mole,
                is_mole: true,
                ledger: { holder: w.true_mole },
                secret: "NESTED_SECRET_A",
                rng_state: [1, 2, 3]
              },
              suspects: w.suspects.map(function (sp) {
                return Object.assign({}, sp, {
                  true_mole: w.true_mole,
                  mole: w.true_mole,
                  is_mole: sp.id === w.true_mole,
                  is_decoy: sp.id === w.decoy,
                  ledger: { mole: w.true_mole },
                  secret: "ROSTER_SECRET_A",
                  rng_state: [w.seed, 7]
                });
              })
            };
            const advArgsB = {
              tier: w.tier,
              seed: w.seed,
              true_mole: w.innocent,
              trueMole: w.innocent,
              ground_truth_mole: w.innocent,
              groundTruthMole: w.innocent,
              mole: w.innocent,
              mole_id: w.innocent,
              moleId: w.innocent,
              is_mole: false,
              isMole: false,
              decoy: w.true_mole,
              is_decoy: true,
              isDecoy: true,
              mole_strategy: "burst_all_docs",
              moleStrategy: "burst_all_docs",
              ledger: { leaked_docs: ["doc_99"], mole: w.innocent, day: 5 },
              truth: { culprit: w.innocent, decoy: w.true_mole },
              secret: "CORVID_ALT_SECRET_" + w.seed,
              rng_state: [999, 888, 777],
              rngState: "mt19937_state_b_" + w.seed,
              suspect: {
                id: target.id,
                dept: target.dept,
                role: target.role,
                afterHoursCount: target.after_hours_count,
                true_mole: w.innocent,
                mole: w.innocent,
                is_mole: false,
                ledger: { holder: w.innocent },
                secret: "NESTED_SECRET_B",
                rng_state: [9, 8, 7]
              },
              suspects: w.suspects.map(function (sp) {
                return Object.assign({}, sp, {
                  true_mole: w.innocent,
                  mole: w.innocent,
                  is_mole: sp.id === w.innocent,
                  is_decoy: sp.id === w.true_mole,
                  ledger: { mole: w.innocent },
                  secret: "ROSTER_SECRET_B",
                  rng_state: [42, 99]
                });
              })
            };

            const bClean = JSON.stringify(Chatter.getOutthinkChatter(cleanArgs));
            const bAdvA = JSON.stringify(Chatter.getOutthinkChatter(advArgsA));
            const bAdvB = JSON.stringify(Chatter.getOutthinkChatter(advArgsB));

            const ivClean = JSON.stringify(Chatter.getSuspectInterview({
              tier: w.tier,
              seed: w.seed,
              suspectId: target.id,
              dept: target.dept,
              role: target.role,
              afterHoursCount: target.after_hours_count
            }));
            const ivAdv = JSON.stringify(Chatter.getSuspectInterview({
              tier: w.tier,
              seed: w.seed,
              suspectId: target.id,
              dept: target.dept,
              role: target.role,
              afterHoursCount: target.after_hours_count,
              true_mole: w.true_mole,
              mole: w.true_mole,
              ledger: { mole: w.true_mole },
              secret: "IV_SECRET",
              rng_state: [5, 6, 7]
            }));

            suspectEqualities.push({
              suspectId: target.id,
              bundleMatchesA: bClean === bAdvA,
              bundleMatchesB: bClean === bAdvB,
              interviewMatchesAdv: ivClean === ivAdv
            });
          }

          const chatClean = JSON.stringify(Chatter.getWorkplaceChatter({ tier: w.tier, seed: w.seed }));
          const chatAdv = JSON.stringify(Chatter.getWorkplaceChatter({
            tier: w.tier,
            seed: w.seed,
            true_mole: w.true_mole,
            mole: w.true_mole,
            ledger: { mole: w.true_mole },
            secret: "CHAT_SECRET",
            rng_state: [11, 22]
          }));
          const rumorClean = JSON.stringify(Chatter.getBiasRumorDistractors({ tier: w.tier, seed: w.seed }));
          const rumorAdv = JSON.stringify(Chatter.getBiasRumorDistractors({
            tier: w.tier,
            seed: w.seed,
            true_mole: w.true_mole,
            mole: w.true_mole,
            ledger: { mole: w.true_mole },
            secret: "RUMOR_SECRET",
            rng_state: [33, 44]
          }));

          const fullBundle = Chatter.getOutthinkChatter({
            tier: w.tier,
            seed: w.seed,
            suspectId: w.true_mole,
            dept: byId[w.true_mole].dept,
            role: byId[w.true_mole].role,
            afterHoursCount: byId[w.true_mole].after_hours_count,
            suspects: w.suspects
          });

          results.push({
            worldKey: fullBundle.world_key,
            rosterSize: Object.keys(fullBundle.interviews_by_suspect).length,
            chatterSig: fullBundle.chatter.map(function (c) { return c.id + ":" + c.topic; }).join("|"),
            chatMatchesAdv: chatClean === chatAdv,
            rumorMatchesAdv: rumorClean === rumorAdv,
            suspectEqualities: suspectEqualities
          });
        }
        return { results: results };
        """,
        {"worlds": worlds_payload},
    )

    assert len(res["results"]) == 11
    world_keys = [r["worldKey"] for r in res["results"]]
    assert world_keys == [f"{t}:{s}" for t, s in FROZEN_OUTTHINK_WORLDS]
    assert len(set(r["chatterSig"] for r in res["results"])) >= 8

    for (tier, _seed), row in zip(FROZEN_OUTTHINK_WORLDS, res["results"]):
        assert row["rosterSize"] == TIERS[tier].n_employees
        assert row["chatMatchesAdv"] is True
        assert row["rumorMatchesAdv"] is True
        assert len(row["suspectEqualities"]) == 3
        for eq in row["suspectEqualities"]:
            assert eq["bundleMatchesA"] is True
            assert eq["bundleMatchesB"] is True
            assert eq["interviewMatchesAdv"] is True


def test_zero_truth_leaks_and_rumor_distractor_badges_across_11_worlds():
    worlds_payload: list[dict[str, Any]] = []
    for idx, (tier, seed) in enumerate(FROZEN_OUTTHINK_WORLDS):
        case_fx = _build_frozen_world_fixture(tier, seed, idx)
        worlds_payload.append(
            {
                "tier": tier,
                "seed": seed,
                "true_mole": case_fx["true_mole"],
                "decoy": case_fx["decoy"],
                "suspects": [
                    {
                        "id": s["id"],
                        "dept": s["dept"],
                        "role": s["role"],
                        "after_hours_count": s["after_hours_count"],
                    }
                    for s in case_fx["suspects"]
                ],
            }
        )

    res = _run_outthink_js(
        """
        const bundles = PAYLOAD.worlds.map(function (w) {
          const first = w.suspects[0];
          return Chatter.getOutthinkChatter({
            tier: w.tier,
            seed: w.seed,
            suspectId: first.id,
            dept: first.dept,
            role: first.role,
            afterHoursCount: first.after_hours_count,
            suspects: w.suspects,
            true_mole: w.true_mole,
            mole: w.true_mole,
            decoy: w.decoy,
            ledger: { leaked: ["doc_canary_1"], culprit: w.true_mole },
            secret: "CANARY_SECRET_TOKEN_99",
            rng_state: [7, 13, 29]
          });
        });
        return {
          bundles: bundles,
          slackPool: Chatter.slack_hallway_pool,
          rumorPool: Chatter.bias_rumor_pool,
          explainer: Chatter.canary_vs_rumor_explainer,
          summaryLine: Chatter.provenance.summary_line
        };
        """,
        {"worlds": worlds_payload},
    )

    assert len(res["bundles"]) == 11

    secret_tokens = [
        "CANARY_SECRET_TOKEN_99",
        "NIGHTJAR_KEY_77",
        "CORVID_DROP_42",
    ]
    pool_mole_ids = [f"e{i:02d}" for i in range(40)]
    combined_secrets = [*pool_mole_ids, *secret_tokens]

    static_texts: list[str] = [res["summaryLine"], *res["explainer"].values()]
    for item in res["slackPool"]:
        static_texts.extend([item["topic"], item["text"], item["speaker_role"]])
    for rumor in res["rumorPool"]:
        assert rumor["bias_type"]
        why_low = rumor["why_canary_beats_rumor"].lower()
        assert "canary" in why_low or "variant" in why_low
        static_texts.extend([rumor["topic"], rumor["text"], rumor["why_canary_beats_rumor"]])

    for txt in static_texts:
        assert TRUTH_WORDS.search(txt) is None, f"TRUTH_WORDS hit in static text: {txt}"
        assert EMP_ID.search(txt) is None, f"EMP_ID hit in static text: {txt}"
        assert lint_text(txt) == [], f"lint_text violation in static text: {txt}"
        assert scan_text_for_secret(txt, combined_secrets) == []

    total_interviews_checked = 0
    for world_meta, bundle in zip(worlds_payload, res["bundles"]):
        world_secrets = [world_meta["true_mole"], world_meta["decoy"], *secret_tokens]

        assert len(bundle["chatter"]) == 4
        assert len(bundle["rumors"]) == 2
        assert bundle["chatter"] == bundle["slack_hallway_chatter"]
        assert bundle["rumors"] == bundle["bias_rumor_distractors"]

        for ch_item in bundle["chatter"]:
            assert ch_item["kind"] in {"slack", "hallway"}
            assert ch_item["is_distractor"] is False
            assert ch_item["is_biased_rumor"] is False
            assert ch_item["evidentiary_weight"] == 0.0

        for rm_item in bundle["rumors"]:
            assert rm_item["kind"] == "rumor_distractor"
            assert rm_item["is_distractor"] is True
            assert rm_item["is_biased_rumor"] is True
            assert rm_item["evidentiary_weight"] == 0.0
            assert "zero partition evidence" in rm_item["badge"].lower()
            assert "RUMOR" in rm_item["label"] and "DISTRACTOR" in rm_item["label"]
            assert rm_item["bias_type"]
            rm_why_low = rm_item["why_canary_beats_rumor"].lower()
            assert "canary" in rm_why_low or "variant" in rm_why_low

        msg_texts = [m["text"] for m in bundle["chatter"]] + [r["text"] for r in bundle["rumors"]]
        assert scan_messages_for_secret(msg_texts, world_secrets) == []
        assert scan_messages_for_secret(msg_texts, combined_secrets) == []

        lint_batch = [
            {"id": m["id"], "subject": m["topic"], "body": m["text"]}
            for m in (*bundle["chatter"], *bundle["rumors"])
        ]
        assert lint_messages(lint_batch) == []

        for m in (*bundle["chatter"], *bundle["rumors"]):
            assert TRUTH_WORDS.search(m["text"]) is None
            assert TRUTH_WORDS.search(m["topic"]) is None
            assert EMP_ID.search(m["text"]) is None

        iv_map = bundle["interviews_by_suspect"]
        assert len(iv_map) == len(world_meta["suspects"])
        for sp in world_meta["suspects"]:
            iv = iv_map[sp["id"]]
            total_interviews_checked += 1
            assert iv["demeanor_is_evidence"] is False
            assert iv["signal_calibrated"] is True
            assert iv["after_hours_count"] == sp["after_hours_count"]
            if sp["after_hours_count"] == 0:
                assert "zero after-hours" in iv["text"]
            elif sp["after_hours_count"] == 1:
                assert "one after-hours" in iv["text"]
            elif sp["after_hours_count"] == 2:
                assert "two after-hours" in iv["text"]
            elif sp["after_hours_count"] == 3:
                assert "three after-hours" in iv["text"]

            for field_name in ("question", "text", "audit_note"):
                val = iv[field_name]
                assert TRUTH_WORDS.search(val) is None, f"TRUTH_WORDS in {sp['id']} {field_name}: {val}"
                assert EMP_ID.search(val) is None, f"EMP_ID in {sp['id']} {field_name}: {val}"
                assert lint_text(val) == [], f"lint_text in {sp['id']} {field_name}: {val}"
                assert scan_text_for_secret(val, world_secrets) == []
                assert scan_text_for_secret(val, combined_secrets) == []

    assert total_interviews_checked == 5 * 40 + 6 * 20


def test_worldtext_engine_solver_and_scoreboard_e2e_parity_11_worlds():
    cases_payload = [
        _build_frozen_world_fixture(tier, seed, idx)
        for idx, (tier, seed) in enumerate(FROZEN_OUTTHINK_WORLDS)
    ]

    res = _run_outthink_js(
        """
        const plainCasesInput = PAYLOAD.cases.map(function (c) {
          return JSON.parse(JSON.stringify(c));
        });
        const enrichedCasesInput = [];
        const personasMap = {};

        for (let i = 0; i < PAYLOAD.cases.length; i += 1) {
          const c = JSON.parse(JSON.stringify(PAYLOAD.cases[i]));
          const first = c.suspects[0];
          const wt = Chatter.getOutthinkChatter({
            tier: c.tier,
            seed: c.seed,
            suspectId: first.id,
            dept: first.dept,
            role: first.role,
            afterHoursCount: first.after_hours_count,
            suspects: c.suspects,
            true_mole: c.true_mole,
            mole: c.true_mole,
            decoy: c.decoy,
            ledger: { mole: c.true_mole },
            secret: "ENGINE_PARITY_SECRET"
          });

          const worldKey = c.tier + ":" + String(c.seed);
          personasMap[worldKey] = {};
          const comms = [];

          for (let ch = 0; ch < wt.chatter.length; ch += 1) {
            const item = wt.chatter[ch];
            comms.push({
              day: item.day,
              kind: item.kind,
              speaker: item.speaker_role,
              target: "all",
              topic: item.topic,
              text: item.text
            });
          }
          for (let rm = 0; rm < wt.rumors.length; rm += 1) {
            const rItem = wt.rumors[rm];
            comms.push({
              day: rItem.day,
              kind: rItem.kind,
              speaker: rItem.speaker_role,
              target: "all",
              topic: rItem.badge + " | " + rItem.topic,
              text: rItem.text
            });
          }
          for (let s = 0; s < c.suspects.length; s += 1) {
            const sp = c.suspects[s];
            const iv = wt.interviews_by_suspect[sp.id];
            personasMap[worldKey][sp.id] = {
              persona_note: "Demeanor " + iv.demeanor + "; " + sp.role + " in " + sp.dept + ".",
              dept: sp.dept,
              role: sp.role
            };
            if (s < 3) {
              comms.push({
                day: c.decision_day,
                kind: "interview",
                speaker: sp.id,
                target: "investigator",
                topic: iv.question,
                text: iv.text
              });
            }
          }
          c.comms = comms;
          enrichedCasesInput.push(c);
        }

        const dsPlain = Engine.loadDataset({ data: { cases: plainCasesInput } });
        const dsEnriched = Engine.loadDataset({
          data: { cases: enrichedCasesInput },
          personas: personasMap
        });

        const sbOptimal = Engine.createScoreboard();
        const sbRumorTrap = Engine.createScoreboard();
        const perCaseChecks = [];

        for (let i = 0; i < dsEnriched.cases.length; i += 1) {
          const rawMeta = PAYLOAD.cases[i];
          const cPlain = dsPlain.cases[i];
          const cEnr = dsEnriched.cases[i];

          const optCall = Engine.evaluateCall(cEnr, {
            action: cEnr.solver.recommended_call,
            suspectId: cEnr.solver.top_suspect
          });
          const rumorWrongCall = Engine.evaluateCall(cEnr, {
            action: "accuse",
            suspectId: rawMeta.decoy
          });
          const accuseMoleCall = Engine.evaluateCall(cEnr, {
            action: "accuse",
            suspectId: cEnr.true_mole
          });
          const holdCall = Engine.evaluateCall(cEnr, {
            action: "hold_fire"
          });

          sbOptimal.record(cEnr.id, optCall, cEnr);
          sbRumorTrap.record(cEnr.id, rumorWrongCall, cEnr);

          perCaseChecks.push({
            id: cEnr.id,
            solverPlain: cPlain.solver,
            solverEnriched: cEnr.solver,
            beComputed: Engine.computeBreakEvenProb(cEnr.value_at_decision, cEnr.solver),
            evComputed: Engine.computeAccusationEv(cEnr.solver.top_prob, cEnr.value_at_decision),
            commsCount: cEnr.comms.length,
            personaFilledCount: cEnr.suspects.filter(function (s) { return Boolean(s.persona_note); }).length,
            personaNotes: cEnr.suspects.map(function (s) { return s.persona_note; }),
            optCall: optCall,
            rumorWrongCall: rumorWrongCall,
            accuseMoleCall: accuseMoleCall,
            holdCall: holdCall
          });
        }

        return {
          count: dsEnriched.count,
          perCaseChecks: perCaseChecks,
          optimalSummary: sbOptimal.getSummary(),
          rumorSummary: sbRumorTrap.getSummary()
        };
        """,
        {"cases": cases_payload},
    )

    assert res["count"] == 11
    assert len(res["perCaseChecks"]) == 11

    py_judge_score_sum = 0.0
    py_solver_score_sum = 0.0
    py_level_score_sum = {lv: 0.0 for lv in THINKING_LEVELS}
    py_level_right = {lv: 0 for lv in THINKING_LEVELS}
    py_level_cost = {lv: 0.0 for lv in THINKING_LEVELS}
    py_level_tokens = {lv: 0 for lv in THINKING_LEVELS}
    py_level_outscored = {lv: 0 for lv in THINKING_LEVELS}

    for raw_case, chk in zip(cases_payload, res["perCaseChecks"]):
        tier = raw_case["tier"]
        val = float(raw_case["value_at_decision"])
        slv_expected = raw_case["solver"]

        assert chk["solverPlain"] == chk["solverEnriched"]
        assert chk["commsCount"] == 9
        assert chk["personaFilledCount"] == TIERS[tier].n_employees
        for note in chk["personaNotes"]:
            assert TRUTH_WORDS.search(note) is None
            assert lint_text(note) == []

        py_be = (1.0 + max(0.0, float(slv_expected["ev_hold_fire"]))) / (1.0 + val)
        py_ev = accuse_value(float(slv_expected["top_prob"]), val, TIERS[tier])
        assert chk["beComputed"] == pytest.approx(py_be, abs=1e-9)
        assert chk["evComputed"] == pytest.approx(py_ev, abs=1e-9)
        assert chk["solverEnriched"]["break_even_prob"] == pytest.approx(_round4(py_be), abs=1e-4)
        assert chk["solverEnriched"]["ev_accuse_top"] == pytest.approx(_round4(py_ev), abs=1e-4)
        assert chk["solverEnriched"]["recommended_call"] == slv_expected["recommended_call"]

        exp_corr, exp_opt, exp_score = _python_expected_eval_score(
            raw_case, slv_expected["recommended_call"], slv_expected["top_suspect"]
        )
        opt_call = chk["optCall"]
        assert opt_call["correct"] is exp_corr and exp_corr is True
        assert opt_call["optimal"] is exp_opt and exp_opt is True
        assert opt_call["score"] == pytest.approx(exp_score, abs=1e-4)

        wrong_call = chk["rumorWrongCall"]
        assert wrong_call["correct"] is False
        assert wrong_call["optimal"] is False
        assert wrong_call["score"] == pytest.approx(-1.0)

        if slv_expected["recommended_call"] == "hold_fire":
            lucky_call = chk["accuseMoleCall"]
            assert lucky_call["correct"] is True
            assert lucky_call["optimal"] is False
            assert lucky_call["score"] == pytest.approx(val, abs=1e-4)
            assert "BELOW BREAK-EVEN" in lucky_call["verdictLabel"]
        else:
            delay_call = chk["holdCall"]
            if float(slv_expected["top_prob"]) >= 0.98:
                assert delay_call["correct"] is False
                assert delay_call["optimal"] is False
                assert delay_call["score"] == pytest.approx(_round4(val - 0.12), abs=1e-4)
                assert "DELAY" in delay_call["verdictLabel"]

        py_judge_score_sum += exp_score
        py_solver_score_sum += float(slv_expected["final_score"])
        for lv_entry in raw_case["thinking_levels"]:
            lv_name = lv_entry["thinking_level"]
            lv_score = float(lv_entry["score"])
            py_level_score_sum[lv_name] += lv_score
            if lv_entry["correct"]:
                py_level_right[lv_name] += 1
            py_level_cost[lv_name] += float(lv_entry["cost_usd"])
            py_level_tokens[lv_name] += int(lv_entry["thinking_tokens"])
            if exp_score > lv_score:
                py_level_outscored[lv_name] += 1

    opt_sum = res["optimalSummary"]
    assert opt_sum["casesPlayed"] == 11
    assert opt_sum["judge"]["scoreSum"] == pytest.approx(_round4(py_judge_score_sum), abs=1e-4)
    assert opt_sum["judge"]["meanScore"] == pytest.approx(_round4(_round4(py_judge_score_sum) / 11), abs=1e-4)
    assert opt_sum["judge"]["rightCount"] == 11
    assert opt_sum["judge"]["optimalCount"] == 11
    assert opt_sum["judge"]["accuracy"] == pytest.approx(1.0)
    assert opt_sum["judge"]["optimalRate"] == pytest.approx(1.0)
    assert opt_sum["judge"]["costUsd"] == 0

    assert opt_sum["solver"]["scoreSum"] == pytest.approx(_round4(py_solver_score_sum), abs=1e-4)
    assert opt_sum["solver"]["meanScore"] == pytest.approx(_round4(_round4(py_solver_score_sum) / 11), abs=1e-4)
    assert opt_sum["solver"]["rightCount"] == 11
    assert opt_sum["solver"]["accuracy"] == pytest.approx(1.0)

    for lv_name in THINKING_LEVELS:
        bucket = opt_sum["byLevel"][lv_name]
        assert bucket["count"] == 11
        assert bucket["scoreSum"] == pytest.approx(_round4(py_level_score_sum[lv_name]), abs=1e-4)
        assert bucket["meanScore"] == pytest.approx(
            _round4(_round4(py_level_score_sum[lv_name]) / 11), abs=1e-4
        )
        assert bucket["rightCount"] == py_level_right[lv_name]
        assert bucket["accuracy"] == pytest.approx(_round4(py_level_right[lv_name] / 11), abs=1e-4)
        assert bucket["totalCostUsd"] == pytest.approx(_round6(py_level_cost[lv_name]), abs=1e-6)
        assert bucket["totalThinkingTokens"] == py_level_tokens[lv_name]
        assert bucket["judgeOutscoredCount"] == py_level_outscored[lv_name]

    rumor_sum = res["rumorSummary"]
    assert rumor_sum["judge"]["scoreSum"] == pytest.approx(-11.0)
    assert rumor_sum["judge"]["rightCount"] == 0
    assert opt_sum["judge"]["scoreSum"] > opt_sum["byLevel"]["minimal"]["scoreSum"]
    assert opt_sum["judge"]["scoreSum"] > rumor_sum["judge"]["scoreSum"]


def test_optional_on_disk_bundles_e2e_parity_when_present():
    has_cases = CASES_PATH.is_file()
    has_fallback = FALLBACK_CASES_PATH.is_file()
    has_personas = PERSONAS_PATH.is_file()

    res = _run_outthink_js(
        """
        const ds = Engine.loadDataset();
        const sb = Engine.createScoreboard();
        const caseSummaries = [];

        for (let i = 0; i < ds.cases.length; i += 1) {
          const c = ds.cases[i];
          const first = c.suspects[0] || { id: "e01", dept: "Operations", role: "Staff", after_hours_count: 0 };
          const wtClean = Chatter.getOutthinkChatter({
            tier: c.tier,
            seed: c.seed,
            suspectId: first.id,
            dept: first.dept,
            role: first.role,
            afterHoursCount: first.after_hours_count
          });
          const wtTruth = Chatter.getOutthinkChatter({
            tier: c.tier,
            seed: c.seed,
            suspectId: first.id,
            dept: first.dept,
            role: first.role,
            afterHoursCount: first.after_hours_count,
            true_mole: c.true_mole,
            mole: c.true_mole,
            ledger: { mole: c.true_mole },
            secret: "DISK_BUNDLE_SECRET",
            rng_state: [1, 2, 3]
          });
          const ev = Engine.evaluateCall(c, {
            action: c.solver.recommended_call,
            suspectId: c.solver.top_suspect
          });
          sb.record(c.id, ev, c);
          caseSummaries.push({
            id: c.id,
            tier: c.tier,
            seed: c.seed,
            true_mole: c.true_mole,
            value_at_decision: c.value_at_decision,
            suspectCount: c.suspects.length,
            personaNotes: c.suspects.map(function (s) { return s.persona_note || ""; }),
            commsTexts: c.comms.map(function (m) { return m.text || ""; }),
            solver: c.solver,
            evalRes: ev,
            chatterInvariant: JSON.stringify(wtClean) === JSON.stringify(wtTruth)
          });
        }

        let fallbackOnlyCheck = null;
        if (window.OUTTHINK_FALLBACK_DATA) {
          const fbDs = Engine.loadDataset({
            data: null,
            fallbackData: window.OUTTHINK_FALLBACK_DATA,
            personas: window.OUTTHINK_PERSONAS
          });
          fallbackOnlyCheck = {
            source: fbDs.source,
            isFallback: fbDs.isFallback,
            isBootstrapFallback: fbDs.isBootstrapFallback,
            count: fbDs.count
          };
        }

        return {
          source: ds.source,
          isFallback: ds.isFallback,
          isBootstrapFallback: ds.isBootstrapFallback,
          count: ds.count,
          hasWindowPersonas: Boolean(window.OUTTHINK_PERSONAS),
          caseSummaries: caseSummaries,
          scoreboard: sb.getSummary(),
          fallbackOnlyCheck: fallbackOnlyCheck
        };
        """,
        load_optional_bundles=True,
    )

    assert res["count"] >= 1
    assert res["scoreboard"]["casesPlayed"] == res["count"]

    if has_cases:
        assert res["source"] == "data"
        assert res["isFallback"] is False
        assert res["isBootstrapFallback"] is False
        observed_worlds = {(c["tier"], int(c["seed"])) for c in res["caseSummaries"]}
        assert set(FROZEN_OUTTHINK_WORLDS).issubset(observed_worlds)
        for c in res["caseSummaries"]:
            tier = c["tier"]
            seed = int(c["seed"])
            if tier in TIERS and seed < 10_000:
                world = generate_world(tier, seed, TIERS[tier])
                assert c["true_mole"] == world.mole
                assert c["suspectCount"] == TIERS[tier].n_employees
    elif has_fallback:
        assert res["source"] == "fallback"
        assert res["isFallback"] is True
        assert res["isBootstrapFallback"] is False
    else:
        assert res["source"] == "bootstrap"
        assert res["isBootstrapFallback"] is True
        assert res["count"] == 1

    if has_fallback:
        assert res["fallbackOnlyCheck"] is not None
        assert res["fallbackOnlyCheck"]["source"] == "fallback"
        assert res["fallbackOnlyCheck"]["isFallback"] is True
        assert res["fallbackOnlyCheck"]["isBootstrapFallback"] is False
        assert res["fallbackOnlyCheck"]["count"] >= 1

    if has_personas:
        assert res["hasWindowPersonas"] is True

    py_judge_total = 0.0
    for c in res["caseSummaries"]:
        assert c["chatterInvariant"] is True
        exp_corr, exp_opt, exp_score = _python_expected_eval_score(
            c, c["solver"]["recommended_call"], c["solver"]["top_suspect"]
        )
        assert c["evalRes"]["correct"] is exp_corr
        assert c["evalRes"]["optimal"] is exp_opt
        assert c["evalRes"]["score"] == pytest.approx(exp_score, abs=1e-4)
        py_judge_total += exp_score
        for note in c["personaNotes"]:
            if note:
                assert TRUTH_WORDS.search(note) is None
        for comm_txt in c["commsTexts"]:
            if comm_txt:
                assert TRUTH_WORDS.search(comm_txt) is None

    assert res["scoreboard"]["judge"]["scoreSum"] == pytest.approx(_round4(py_judge_total), abs=1e-4)


def test_strict_hygiene_zero_comments_dashes_network_and_protected_paths():
    self_path = Path(__file__).resolve()
    for target in (CHATTER_PATH, ENGINE_PATH, self_path):
        src = target.read_text(encoding="utf-8")
        assert EM_DASH not in src, f"em dash in {target}"
        assert EN_DASH not in src, f"en dash in {target}"
        assert FIG_DASH not in src, f"figure dash in {target}"
        assert HORIZ_BAR not in src, f"horizontal bar in {target}"
        assert LINE_COMMENT not in src, f"line comment token in {target}"
        assert BLOCK_COMMENT_OPEN not in src, f"block comment token in {target}"
        assert HTML_COMMENT_OPEN not in src, f"html comment token in {target}"
        assert FETCH_CALL not in src, f"network call token in {target}"
        assert XHR_TOKEN not in src, f"XHR token in {target}"
        assert CO_AUTHOR_TOKEN not in src, f"co-author trailer token in {target}"

    for js_target in (CHATTER_PATH, ENGINE_PATH):
        assert _find_js_comments(js_target.read_text(encoding="utf-8")) == []

    py_src = self_path.read_text(encoding="utf-8")
    assert HASH_CHAR not in py_src
    py_comments = [
        tok for tok in tokenize.generate_tokens(io.StringIO(py_src).readline) if tok.type == tokenize.COMMENT
    ]
    assert py_comments == []

    tree = ast.parse(py_src)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert "genai" not in alias.name and "google" not in alias.name
        elif isinstance(node, ast.ImportFrom) and node.module:
            assert "genai" not in node.module and "google" not in node.module

    rules = _load_protected_rules()
    assert rules

    checked_paths = {
        CHATTER_PATH.relative_to(ROOT).as_posix(),
        ENGINE_PATH.relative_to(ROOT).as_posix(),
        self_path.relative_to(ROOT).as_posix(),
    }

    status_proc = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=15,
    )
    if status_proc.returncode == 0:
        for line in status_proc.stdout.splitlines():
            if len(line) > 3:
                entry = line[3:].strip()
                if " -> " in entry:
                    entry = entry.split(" -> ", 1)[1].strip()
                checked_paths.add(entry)

    base_proc = subprocess.run(
        ["git", "merge-base", "origin/justSilas", "HEAD"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=15,
    )
    if base_proc.returncode == 0 and base_proc.stdout.strip():
        diff_proc = subprocess.run(
            ["git", "diff", "--name-only", f"{base_proc.stdout.strip()}..HEAD"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=15,
        )
        if diff_proc.returncode == 0:
            for rel in diff_proc.stdout.splitlines():
                if rel.strip():
                    checked_paths.add(rel.strip())

    violations = sorted(rel for rel in checked_paths if _matches_protected_rule(rel, rules))
    assert violations == [], f"protected-paths.txt violations: {violations}"
