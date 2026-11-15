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
from typing import Sequence
import unicodedata
import urllib.parse
import zlib

import pytest

from canary.agents.world_builder import TRUTH_WORDS
from canary.text.lint import lint_text

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
        ".-": "a", "-...": "b", "-.-.": "c", "-..": "d", ".": "e",
        "..-.": "f", "--.": "g", "....": "h", "..": "i", ".---": "j",
        "-.-": "k", ".-..": "l", "--": "m", "-.": "n", "---": "o",
        ".--.": "p", "--.-": "q", ".-.": "r", "...": "s", "-": "t",
        "..-": "u", "...-": "v", ".--": "w", "-..-": "x", "-.--": "y",
        "--..": "z", "-----": "0", ".----": "1", "..---": "2", "...--": "3",
        "....-": "4", ".....": "5", "-....": "6", "--...": "7", "---..": "8",
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
PROTECTED_PATHS_FILE = ROOT / ".github" / "protected-paths.txt"

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


def _run_chatter_js(js_body: str, payload: dict | list | None = None) -> dict:
    cmd_prefix, env = _resolve_js_cmd()
    run_env = dict(env)
    run_env["OUTTHINK_CHATTER_PATH"] = str(CHATTER_PATH)
    run_env["OUTTHINK_TEST_PAYLOAD"] = json.dumps(payload if payload is not None else {})
    wrapper = (
        "globalThis.window = globalThis.window || {};\n"
        "const Chatter = require(process.env.OUTTHINK_CHATTER_PATH);\n"
        "const PAYLOAD = JSON.parse(process.env.OUTTHINK_TEST_PAYLOAD);\n"
        "const out = (() => {\n"
        + js_body
        + "\n})();\n"
        "process.stdout.write(JSON.stringify(out));\n"
    )
    proc = subprocess.run(
        [*cmd_prefix, wrapper],
        cwd=ROOT,
        env=run_env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert proc.returncode == 0, f"JS runtime failed:\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
    return json.loads(proc.stdout)


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


def test_exports_offline_binding_and_provenance_stats():
    assert CHATTER_PATH.is_file()
    res = _run_chatter_js(
        """
        globalThis.window = {};
        delete require.cache[require.resolve(process.env.OUTTHINK_CHATTER_PATH)];
        const Fresh = require(process.env.OUTTHINK_CHATTER_PATH);
        const sample = window.getOutthinkChatter({
          tier: "hard",
          seed: 7,
          suspectId: "e04",
          dept: "Strategy",
          role: "Director",
          afterHoursCount: 2
        });
        return {
          winObjSame: window.OUTTHINK_CHATTER === Fresh,
          rootObjSame: globalThis.OUTTHINK_CHATTER === Fresh,
          winFnType: typeof window.getOutthinkChatter,
          rootFnType: typeof globalThis.getOutthinkChatter,
          modFnSame: Fresh.getOutthinkChatter === window.getOutthinkChatter,
          provenance: Fresh.provenance,
          sampleProvenance: sample.provenance,
          encodings: Fresh.supported_encodings
        };
        """
    )
    assert res["winObjSame"] is True
    assert res["rootObjSame"] is True
    assert res["winFnType"] == "function"
    assert res["rootFnType"] == "function"
    assert res["modFnSame"] is True
    assert res["encodings"] == list(SUPPORTED_ENCODINGS)

    prov = res["provenance"]
    assert prov == res["sampleProvenance"]
    assert prov["role"] == "world_text"
    assert prov["model_id"] == "gemini-4-carbon"
    assert prov["environment_scope"] == "demo/research layer (v1.5 candidate), not part of the judged v1.4 environment"
    assert prov["verified_folders"] == 16
    assert prov["verified_carbon_folders"] == 16
    assert prov["calls"] == 1637
    assert prov["api_calls"] == 1637
    assert prov["personas"] == 648
    assert prov["worlds"] == 24
    assert prov["worlds_by_tier"] == {"easy": 4, "medium": 10, "hard": 10}
    assert prov["personas_by_tier"] == {"easy": 48, "medium": 200, "hard": 400}
    assert prov["live_interviews"] == 120
    assert prov["signal_calibration_accuracy"] == pytest.approx(1.0)
    assert prov["signal_calibration_pct"] == pytest.approx(100.0)
    assert prov["encodings_scanned"] == 37
    assert prov["leaks_detected"] == 0
    assert prov["all_clean"] is True
    assert prov["cost_usd"] == pytest.approx(22.728348)


def test_determinism_and_key_sensitivity_across_tiers_seeds_and_suspects():
    res = _run_chatter_js(
        """
        const getChatter = globalThis.getOutthinkChatter;
        const baseOpts = {
          tier: "hard",
          seed: 18,
          suspectId: "e04",
          dept: "Strategy",
          role: "Director",
          afterHoursCount: 2
        };
        const a1 = getChatter(baseOpts);
        const a2 = getChatter({
          difficulty: "HARD",
          world_seed: 18,
          suspect_id: "e04",
          department: "Strategy",
          job_title: "Director",
          after_hours_count: 2
        });
        const diffTier = getChatter(Object.assign({}, baseOpts, { tier: "easy" }));
        const diffSeed = getChatter(Object.assign({}, baseOpts, { seed: 19 }));
        const diffSuspect = getChatter(Object.assign({}, baseOpts, { suspectId: "e09" }));
        const diffDept = getChatter(Object.assign({}, baseOpts, { dept: "Clinical Ops" }));
        const diffRole = getChatter(Object.assign({}, baseOpts, { role: "Biostatistician" }));
        const diffAhZero = getChatter(Object.assign({}, baseOpts, { afterHoursCount: 0 }));
        const diffAhOne = getChatter(Object.assign({}, baseOpts, { afterHoursCount: 1 }));
        const withTruthA = getChatter(Object.assign({}, baseOpts, {
          true_mole: "e04",
          mole: "e04",
          secret: "NIGHTJAR_DROP_99",
          mole_strategy: "export_burst"
        }));
        const withTruthB = getChatter(Object.assign({}, baseOpts, {
          true_mole: "e01",
          mole: "e01",
          secret: "CORVID_DROP_11",
          mole_strategy: "quiet_drip"
        }));
        const rosterCall = getChatter({
          tier: "medium",
          seed: 3001,
          suspectId: "e02",
          dept: "Clinical Data",
          role: "Biostatistician",
          afterHoursCount: 0,
          suspects: [
            { id: "e01", dept: "Assay Ops", role: "Lab Lead", after_hours_count: 1 },
            { id: "e02", dept: "Clinical Data", role: "Biostatistician", after_hours_count: 0 },
            { id: "e03", dept: "Partner Relations", role: "Alliances Manager", after_hours_count: 2 }
          ]
        });
        return {
          a1,
          a2,
          diffTier,
          diffSeed,
          diffSuspect,
          diffDept,
          diffRole,
          diffAhZero,
          diffAhOne,
          withTruthA,
          withTruthB,
          rosterCall
        };
        """
    )

    assert res["a1"] == res["a2"]
    assert res["a1"] == res["withTruthA"]
    assert res["withTruthA"] == res["withTruthB"]

    a1 = res["a1"]
    assert len(a1["chatter"]) == 4
    assert len(a1["rumors"]) == 2
    assert all(item["is_distractor"] is False for item in a1["chatter"])
    assert all(item["kind"] in {"slack", "hallway"} for item in a1["chatter"])

    for rumor in a1["rumors"]:
        assert rumor["is_distractor"] is True
        assert rumor["is_biased_rumor"] is True
        assert rumor["evidentiary_weight"] == 0.0
        assert "RUMOR" in rumor["label"] and "DISTRACTOR" in rumor["label"]
        assert "canary" in rumor["why_canary_beats_rumor"].lower()

    assert "canary" in a1["canary_vs_rumor"]["core_principle"].lower()
    assert "rumor" in a1["canary_vs_rumor"]["headline"].lower()

    assert res["diffTier"]["chatter"] != a1["chatter"]
    assert res["diffTier"]["interview"]["text"] != a1["interview"]["text"]
    assert res["diffSeed"]["chatter"] != a1["chatter"]
    assert res["diffSeed"]["rumors"] != a1["rumors"]
    assert res["diffSeed"]["interview"]["text"] != a1["interview"]["text"]

    assert res["diffSuspect"]["chatter"] == a1["chatter"]
    assert res["diffSuspect"]["rumors"] == a1["rumors"]
    assert res["diffSuspect"]["interview"]["key"] != a1["interview"]["key"]
    assert res["diffDept"]["interview"]["text"] != a1["interview"]["text"]
    assert "Clinical Ops" in res["diffDept"]["interview"]["text"]
    assert res["diffRole"]["interview"]["text"] != a1["interview"]["text"]
    assert "Biostatistician" in res["diffRole"]["interview"]["text"]
    assert res["diffAhZero"]["interview"]["text"] != a1["interview"]["text"]
    assert "zero after-hours" in res["diffAhZero"]["interview"]["text"]
    assert "one after-hours" in res["diffAhOne"]["interview"]["text"]
    assert "two after-hours" in a1["interview"]["text"]

    roster_iv = res["rosterCall"]["interviews_by_suspect"]
    assert set(roster_iv.keys()) == {"e01", "e02", "e03"}
    assert roster_iv["e01"]["text"] != roster_iv["e02"]["text"]
    assert roster_iv["e02"]["text"] != roster_iv["e03"]["text"]


def test_non_leak_across_all_37_encodings_and_worldtext_lint():
    assert len(SUPPORTED_ENCODINGS) == 37

    b64_secret = base64.b64encode(b"MOLE_SECRET_X9").decode("ascii")
    rot13_secret = codecs.encode("MOLE_SECRET_X9", "rot_13")
    assert any(h["encoding"] == "plaintext" for h in scan_text_for_secret("leaked e04 now", ["e04"]))
    assert any(h["encoding"] == "base64" for h in scan_text_for_secret(f"token {b64_secret}", ["MOLE_SECRET_X9"]))
    assert any(h["encoding"] == "rot13" for h in scan_text_for_secret(f"note {rot13_secret}", ["MOLE_SECRET_X9"]))

    res = _run_chatter_js(
        """
        const Chatter = globalThis.OUTTHINK_CHATTER;
        const getChatter = globalThis.getOutthinkChatter;
        const tiers = ["easy", "medium", "hard"];
        const seeds = [0, 1, 5, 11, 29, 3001];
        const suspects = [
          { id: "e01", dept: "Assay Ops", role: "Lab Lead", ah: 0 },
          { id: "e03", dept: "Partner Relations", role: "Alliances Manager", ah: 2 },
          { id: "e04", dept: "Strategy", role: "Director", ah: 1 },
          { id: "e17", dept: "Platform Infra", role: "Principal SRE", ah: 4 },
          { id: "e27", dept: "Clinical Data", role: "Biostatistician", ah: 25 }
        ];
        const bundles = [];
        for (let ti = 0; ti < tiers.length; ti += 1) {
          for (let si = 0; si < seeds.length; si += 1) {
            const s = suspects[(ti + si) % suspects.length];
            bundles.push(getChatter({
              tier: tiers[ti],
              seed: seeds[si],
              suspectId: s.id,
              dept: s.dept,
              role: s.role,
              afterHoursCount: s.ah,
              true_mole: s.id,
              secret: "MOLE_SECRET_X9"
            }));
          }
        }
        return {
          slackPool: Chatter.slack_hallway_pool,
          rumorPool: Chatter.bias_rumor_pool,
          explainer: Chatter.canary_vs_rumor_explainer,
          provenanceLine: Chatter.provenance.summary_line,
          bundles
        };
        """
    )

    mole_ids_only = ["e01", "e02", "e03", "e04", "e05", "e09", "e12", "e17", "e27", "e34"]
    mixed_secrets = [
        "e01",
        "e03",
        "e04",
        "e17",
        "e27",
        "MOLE_SECRET_X9",
        "CORVID_DROP_77",
        "NIGHTJAR_KEY",
    ]

    all_texts: list[str] = [res["provenanceLine"]]
    for val in res["explainer"].values():
        all_texts.append(val)
    for item in res["slackPool"]:
        all_texts.append(item["text"])
        all_texts.append(item["topic"])
    for item in res["rumorPool"]:
        all_texts.append(item["text"])
        all_texts.append(item["why_canary_beats_rumor"])

    for bundle in res["bundles"]:
        msg_batch = [m["text"] for m in bundle["chatter"]] + [r["text"] for r in bundle["rumors"]]
        assert scan_messages_for_secret(msg_batch, mixed_secrets) == []
        assert scan_messages_for_secret(msg_batch, mole_ids_only) == []
        all_texts.extend(msg_batch)
        all_texts.append(bundle["interview"]["question"])
        all_texts.append(bundle["interview"]["text"])
        all_texts.append(bundle["interview"]["audit_note"])

    for txt in all_texts:
        assert scan_text_for_secret(txt, mole_ids_only) == [], f"mole ID leak in: {txt}"
        assert scan_text_for_secret(txt, mixed_secrets) == [], f"secret leak in: {txt}"
        assert lint_text(txt) == [], f"lint_text violation in: {txt}"
        assert TRUTH_WORDS.search(txt) is None, f"TRUTH_WORDS match in: {txt}"


def test_default_options_nested_suspect_and_input_sanitization():
    res = _run_chatter_js(
        """
        const getChatter = globalThis.getOutthinkChatter;
        const emptyA = getChatter();
        const emptyB = getChatter(null);
        const nested = getChatter({
          tier: "medium",
          seed: 4,
          suspect: {
            id: "e07",
            dept: "Infra",
            role: "SRE",
            afterHoursCount: 3
          }
        });
        const flat = getChatter({
          tier: "medium",
          seed: 4,
          suspectId: "e07",
          dept: "Infra",
          role: "SRE",
          afterHoursCount: 3
        });
        const sanitized = getChatter({
          tier: "hard",
          seed: 9,
          suspectId: "e04",
          dept: "Strategy e04 mole culprit",
          role: "Director spy e04",
          afterHoursCount: -5
        });
        return { emptyA, emptyB, nested, flat, sanitized };
        """
    )

    assert res["emptyA"] == res["emptyB"]
    assert res["nested"] == res["flat"]
    assert "three after-hours" in res["nested"]["interview"]["text"]

    san_iv = res["sanitized"]["interview"]
    assert san_iv["after_hours_count"] == 0
    assert scan_text_for_secret(san_iv["text"], ["e04", "MOLE_SECRET_X9"]) == []
    assert lint_text(san_iv["text"]) == []
    assert TRUTH_WORDS.search(san_iv["text"]) is None


def test_strict_lint_hygiene_and_protected_paths():
    self_path = Path(__file__).resolve()
    for target in (CHATTER_PATH, self_path):
        src = target.read_text(encoding="utf-8")
        assert EM_DASH not in src, f"em dash in {target}"
        assert EN_DASH not in src, f"en dash in {target}"
        assert FIG_DASH not in src, f"figure dash in {target}"
        assert HORIZ_BAR not in src, f"horizontal bar in {target}"
        assert HASH_CHAR not in src, f"hash comment char in {target}"
        assert LINE_COMMENT not in src, f"line comment token in {target}"
        assert BLOCK_COMMENT_OPEN not in src, f"block comment token in {target}"
        assert HTML_COMMENT_OPEN not in src, f"html comment token in {target}"
        assert FETCH_CALL not in src, f"network call token in {target}"
        assert XHR_TOKEN not in src, f"XHR token in {target}"

    js_src = CHATTER_PATH.read_text(encoding="utf-8")
    assert _find_js_comments(js_src) == []

    py_src = self_path.read_text(encoding="utf-8")
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
