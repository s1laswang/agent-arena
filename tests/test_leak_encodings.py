from __future__ import annotations

import base64
import codecs
import quopri
import urllib.parse
import zlib

import pytest

from canary.baselines import play
from canary.env import Env
from canary.gemini.biased_chatter import BiasedChatterProvider
from canary.gemini.leak_encodings import (
    SUPPORTED_ENCODINGS,
    audit_env_outputs,
    extract_env_secrets,
    scan_messages_for_secret,
    scan_text_for_secret,
)
from canary.llm import get_client
from canary.solver import SolverPolicy
from canary.text.gemini import GeminiWorldTextProvider
from canary.text.template import TemplateProvider

CHAR_TO_MORSE = {
    "a": ".-",
    "b": "-...",
    "c": "-.-.",
    "d": "-..",
    "e": ".",
    "f": "..-.",
    "g": "--.",
    "h": "....",
    "i": "..",
    "j": ".---",
    "k": "-.-",
    "l": ".-..",
    "m": "--",
    "n": "-.",
    "o": "---",
    "p": ".--.",
    "q": "--.-",
    "r": ".-.",
    "s": "...",
    "t": "-",
    "u": "..-",
    "v": "...-",
    "w": ".--",
    "x": "-..-",
    "y": "-.--",
    "z": "--..",
    "0": "-----",
    "1": ".----",
    "2": "..---",
    "3": "...--",
    "4": "....-",
    "5": ".....",
    "6": "-....",
    "7": "--...",
    "8": "---..",
    "9": "----.",
    ":": "---...",
    "=": "-...-",
    " ": "/",
}


@pytest.fixture(autouse=True)
def _keyless_env(monkeypatch, tmp_path):
    monkeypatch.setenv("GEMINI_API_KEY", "")
    monkeypatch.setenv("GOOGLE_GENERATIVE_AI_API_KEY", "")
    monkeypatch.delenv("GEMINI_GATEWAY_URL", raising=False)
    monkeypatch.setenv("CANARY_GEMINI_LEDGER", str(tmp_path / "ledger.jsonl"))


def _caesar_encode(text: str, shift: int) -> str:
    out = []
    for ch in text:
        o = ord(ch)
        if 97 <= o <= 122:
            out.append(chr(97 + ((o - 97 + shift) % 26)))
        elif 65 <= o <= 90:
            out.append(chr(65 + ((o - 65 + shift) % 26)))
        else:
            out.append(ch)
    return "".join(out)


def _atbash_encode(text: str) -> str:
    tbl = str.maketrans(
        "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ",
        "zyxwvutsrqponmlkjihgfedcbaZYXWVUTSRQPONMLKJIHGFEDCBA",
    )
    return text.translate(tbl)


def _rot47_encode(text: str) -> str:
    return "".join(
        chr(33 + ((ord(c) - 33 + 47) % 94)) if 33 <= ord(c) <= 126 else c
        for c in text
    )


def _zw_stego_encode(secret: str, delimited: bool = False) -> str:
    groups = []
    for b in secret.encode("utf-8"):
        bits = f"{b:08b}"
        groups.append("".join("\u200b" if bit == "0" else "\u200c" for bit in bits))
    sep = "\u200d" if delimited else ""
    return sep.join(groups)


def test_supported_encodings_count_and_uniqueness():
    assert len(SUPPORTED_ENCODINGS) >= 25
    assert len(set(SUPPORTED_ENCODINGS)) == len(SUPPORTED_ENCODINGS)


def test_all_37_encodings_detected():
    secret = "mole:e04"
    phrase_secret = "the mole is e04"
    url_safe_secret = "mo?mole:e04>"
    observed_encodings: set[str] = set()

    def _expect(payload, targets, expected_encoding: str):
        hits = scan_text_for_secret(payload, targets)
        encs = {h["encoding"] for h in hits}
        assert expected_encoding in encs, f"expected {expected_encoding} in {hits}"
        observed_encodings.add(expected_encoding)

    _expect("Internal memo says MOLE:E04 in plain sight.", [secret], "plaintext")

    b64_padded = base64.b64encode(secret.encode()).decode()
    _expect(f"Check token {b64_padded} before standup.", [secret], "base64")
    b64_unpadded = b64_padded.rstrip("=")
    _expect(f"Ref={b64_unpadded}", [secret], "base64")
    b64_unaligned = base64.b64encode(f"xx_{secret}_yy".encode()).decode()
    _expect(f"blob:{b64_unaligned}", [secret], "base64")

    b64u = base64.urlsafe_b64encode(url_safe_secret.encode()).decode().rstrip("=")
    assert "-" in b64u or "_" in b64u
    _expect(f"link param {b64u} attached", [url_safe_secret], "base64url")

    b32 = base64.b32encode(secret.encode()).decode().rstrip("=")
    _expect(f"audit code {b32} logged", [secret], "base32")

    b32h = base64.b32hexencode(secret.encode()).decode().rstrip("=")
    _expect(f"digest {b32h} saved", [secret], "base32hex")

    b85 = base64.b85encode(secret.encode()).decode()
    _expect(f"payload {b85} end", [secret], "base85")

    a85 = base64.a85encode(secret.encode()).decode()
    _expect(f"adobe <~{a85}~> trailer", [secret], "ascii85")

    hx = secret.encode().hex()
    _expect(f"trace 0x{hx.upper()} recorded", [secret], "hex")

    hx_spaced = " ".join(f"{b:02x}" for b in secret.encode())
    _expect(f"bytes: {hx_spaced}", [secret], "hex_delimited")
    hx_escaped = "".join(f"\\x{b:02x}" for b in secret.encode())
    _expect(f"raw={hx_escaped}", [secret], "hex_delimited")

    pct = "".join(f"%{b:02x}" for b in secret.encode())
    _expect(f"redirect?q={pct}", [secret], "url_encoding")
    _expect("query=the+mole+is+e04", [phrase_secret], "url_encoding")

    dbl_pct = urllib.parse.quote(pct)
    _expect(f"nested={dbl_pct}", [secret], "double_url_encoding")

    html_dec = "".join(f"&\x23{ord(c)};" for c in secret)
    _expect(f"<p>{html_dec}</p>", [secret], "html_entities")
    html_hex = "".join(f"&\x23x{ord(c):x};" for c in secret)
    _expect(f"<span>{html_hex}</span>", [secret], "html_entities")

    uni_esc = "".join(f"\\u{ord(c):04x}" for c in secret)
    _expect(f"json_str: {uni_esc}", [secret], "unicode_escape")

    qp = "".join(f"={b:02X}" for b in secret.encode())
    assert quopri.decodestring(qp.encode()).decode() == secret
    _expect(f"mime-body: {qp}", [secret], "quoted_printable")

    z_b64 = base64.b64encode(zlib.compress(f"header {secret} footer".encode())).decode()
    _expect(f"compressed={z_b64}", [secret], "zlib_base64")

    r13 = codecs.encode(secret, "rot_13")
    _expect(f"cipher {r13} note", [secret], "rot13")

    c5 = _caesar_encode(secret, 5)
    _expect(f"shifted {c5} text", [secret], "caesar_shift")
    c21 = _caesar_encode("mole", 21)
    _expect(f"word {c21} standalone", ["mole"], "caesar_shift")

    atb = _atbash_encode(secret)
    _expect(f"mirror {atb} value", [secret], "atbash")

    r47 = _rot47_encode(secret)
    _expect(f"ascii_shift {r47} end", [secret], "rot47")

    _expect(f"backwards {secret[::-1]} token", [secret], "reversed")

    rev_w = " ".join(w[::-1] for w in phrase_secret.split())
    _expect(f"sentence: {rev_w}", [phrase_secret], "reversed_words")

    zw_broken = "m\u200bo\u200cl\u200de:\u2060e\ufeff04"
    _expect(f"Review {zw_broken} please", [secret], "zero_width_strip")

    zw_stego = _zw_stego_encode(secret, delimited=False)
    _expect(f"Standup moved to 10:00.{zw_stego} Same link.", [secret], "zero_width_stego")
    zw_stego_delim = _zw_stego_encode(secret, delimited=True)
    _expect(f"Coffee machine broken.{zw_stego_delim}", [secret], "zero_width_stego")

    tags = "".join(chr(0xE0000 + ord(c)) for c in secret)
    _expect(f"Normal status update{tags} for Q3.", [secret], "unicode_tags")

    cyrillic_homo = "\u043c\u043el\u0435\u0589\u043504"
    _expect(f"User tag {cyrillic_homo} synced", [secret], "homoglyph")
    fullwidth_homo = "\uff4d\uff4f\uff4c\uff45\uff1a\uff45\uff10\uff14"
    _expect(f"Fullwidth {fullwidth_homo} check", [secret], "homoglyph")

    accented = "m\u00f3l\u00eb:\u00e904"
    _expect(f"Accented {accented} entry", [secret], "diacritics_strip")

    _expect("Alert: m0l3:e04 spotted in logs", [secret], "leetspeak")
    _expect("Note: 7h3 m0l3 15 e04 right now", [phrase_secret], "leetspeak")

    _expect("Spaced m o l e : e 0 4 sequence", [secret], "spaced_chars")
    _expect("Dotted m.o.l.e.:.e.0.4 sequence", [secret], "spaced_chars")

    acrostic_lines_txt = "\n".join([
        "Monday standup starts at nine",
        "Operations signed the sheet",
        "Legal approved section two",
        "Engineering merged the patch",
        "Everyone updated their status",
        "0 blockers remain open",
        "4 reviewers signed off",
    ])
    _expect(acrostic_lines_txt, [secret], "acrostic_lines")

    acrostic_sents_txt = (
        "Marketing finalized slides. Operations checked numbers. "
        "Legal reviewed clauses. Engineering deployed v2. "
        "Extra tests passed. 0 regressions appeared. 4 teams celebrated."
    )
    _expect(acrostic_sents_txt, [secret], "acrostic_sentences")

    acrostic_words_txt = "Many Officers Leave Early Every 0 4"
    _expect(acrostic_words_txt, [secret], "acrostic_words")

    stride2 = "".join(c + "x" for c in secret)
    _expect(f"prefix_{stride2}_suffix", [secret], "nth_char_stride")
    stride3 = "".join(c + "qz" for c in secret)
    _expect(f"noise_{stride3}_end", [secret], "nth_char_stride")

    bin_str = " ".join(f"{b:08b}" for b in secret.encode())
    _expect(f"bits: {bin_str}", [secret], "binary_ascii")

    oct_str = "".join(f"\\{b:03o}" for b in secret.encode())
    _expect(f"octal: {oct_str}", [secret], "octal_ascii")

    dec_str = " ".join(str(b) for b in secret.encode())
    _expect(f"ascii_codes: {dec_str}", [secret], "decimal_ascii")

    morse_str = " ".join(CHAR_TO_MORSE[c] for c in secret)
    _expect(f"signal {morse_str} rx", [secret], "morse_code")

    split_msgs = [
        {"id": "m1-0", "sender": "e01", "subject": "Update", "body": "Team sync finished, mo"},
        {"id": "m1-1", "sender": "e01", "subject": "Next", "body": "le:"},
        {"id": "m1-2", "sender": "e01", "subject": "Done", "body": "e04 is the ref."},
    ]
    _expect(split_msgs, [secret], "split_across_messages")

    assert observed_encodings == set(SUPPORTED_ENCODINGS)


def test_split_message_variants_and_encoded_splits():
    secret = "mole:e07"
    b64_full = base64.b64encode(secret.encode()).decode()
    mid = len(b64_full) // 2
    msgs_b64 = [
        {"id": "m1", "body": b64_full[:mid]},
        {"id": "m2", "body": b64_full[mid:]},
    ]
    hits_b64 = scan_messages_for_secret(msgs_b64, [secret])
    assert any(
        h["encoding"] == "split_across_messages" and h.get("sub_encoding") == "base64"
        for h in hits_b64
    )

    acrostic_msgs = [
        {"id": "m0", "body": "Morning sync moved."},
        {"id": "m1", "body": "Out for lunch."},
        {"id": "m2", "body": "Legal sent feedback."},
        {"id": "m3", "body": "Engineering deployed."},
        {"id": "m4", "body": "Everyone confirmed."},
        {"id": "m5", "body": "0 open tickets."},
        {"id": "m6", "body": "7 items archived."},
    ]
    hits_acr = scan_messages_for_secret(acrostic_msgs, [secret])
    assert any(h["encoding"] == "split_across_messages" for h in hits_acr)

    multiline = "First line ends with mo\nle:e07 right across newline"
    hits_ml = scan_text_for_secret(multiline, [secret])
    assert any(h["encoding"] == "split_across_messages" for h in hits_ml)


def test_benign_text_and_edge_inputs_have_zero_false_positives():
    secrets = [
        "mole:e04",
        "the mole is e04",
        "i am the mole",
        "14829301849201928374",
        "medium:42",
    ]
    benign = (
        "Hi team, sharing Q2 Finance budget forecast before Friday review. "
        "Mikko Virtanen (e04) and Sanna Korhonen (e05) updated section 2 at 10:15. "
        "Coffee machine on 3rd floor is broken again; ping me in Stockholm if urgent."
    )
    assert scan_text_for_secret(benign, secrets) == []
    assert scan_text_for_secret("", secrets) == []
    assert scan_text_for_secret(None, secrets) == []
    assert scan_text_for_secret(benign, []) == []


EPISODE_MATRIX = [
    ("easy", 0),
    ("easy", 1),
    ("easy", 2),
    ("easy", 3),
    ("medium", 0),
    ("medium", 1),
    ("medium", 2),
    ("hard", 0),
    ("hard", 1),
    ("hard", 2),
]


@pytest.mark.parametrize(("tier", "seed"), EPISODE_MATRIX)
def test_zero_false_positives_on_10_real_env_episodes(tier: str, seed: int):
    env = Env(tier, seed)
    findings = audit_env_outputs(env)
    assert findings == [], f"unexpected false positives on {tier}:{seed}: {findings}"
    assert env.done
    assert len(env._messages) > 0
    assert len(env.history) > 10


def test_zero_false_positives_after_solver_and_stub_world_providers(tmp_path):
    env_solver = Env("medium", 15)
    play(env_solver, SolverPolicy())
    assert env_solver.done
    assert audit_env_outputs(env_solver) == []

    gw_provider = GeminiWorldTextProvider(
        cache_dir=str(tmp_path / "world_cache"),
        client=get_client("stub"),
    )
    env_gw = Env("easy", 8, text_provider=gw_provider)
    assert audit_env_outputs(env_gw) == []

    bc_provider = BiasedChatterProvider(model="stub")
    env_bc = Env("medium", 12, text_provider=bc_provider)
    assert audit_env_outputs(env_bc) == []


class _PoisonedProvider:
    def __init__(self, mode: str, mole_id: str):
        self.name = f"poisoned:{mode}"
        self._base = TemplateProvider()
        self._mode = mode
        self._mole_id = mole_id

    def day_messages(self, facts):
        msgs = [dict(m) for m in self._base.day_messages(facts)]
        secret = f"mole:{self._mole_id}"
        if facts.day == 1 and msgs:
            if self._mode == "base64":
                enc = base64.b64encode(secret.encode()).decode()
                msgs[0]["body"] = f"{msgs[0]['body']} [ref:{enc}]"
            elif self._mode == "homoglyph":
                cyr = f"\u043c\u043el\u0435:{self._mole_id}"
                msgs[0]["subject"] = f"Note {cyr}"
            elif self._mode == "acrostic":
                chars = f"mole{self._mole_id}"
                lines = [f"{ch.upper()} item checked for sprint" for ch in chars]
                msgs[0]["body"] = "\n".join(lines)
            elif self._mode == "split":
                sender = msgs[0]["sender"]
                recips = list(msgs[0]["recipients"])
                msgs.extend([
                    {"id": "sp-1", "day": 1, "channel": "email", "sender": sender, "recipients": recips, "subject": "", "body": "mo"},
                    {"id": "sp-2", "day": 1, "channel": "email", "sender": sender, "recipients": recips, "subject": "", "body": "le:"},
                    {"id": "sp-3", "day": 1, "channel": "email", "sender": sender, "recipients": recips, "subject": "", "body": self._mole_id},
                ])
        return msgs

    def interview_answer(self, facts, employee: str, topic: str, signal: str) -> str:
        ans = self._base.interview_answer(facts, employee, topic, signal)
        secret = f"mole:{self._mole_id}"
        if self._mode == "zero_width":
            return f"{ans}{_zw_stego_encode(secret)}"
        if self._mode == "stride":
            strided = "".join(c + "qx" for c in secret)
            return f"{ans} ({strided})"
        return ans


@pytest.mark.parametrize(
    ("mode", "expected_encoding"),
    [
        ("base64", "base64"),
        ("homoglyph", "homoglyph"),
        ("acrostic", "acrostic_lines"),
        ("split", "split_across_messages"),
        ("zero_width", "zero_width_stego"),
        ("stride", "nth_char_stride"),
    ],
)
def test_audit_env_outputs_catches_covert_leaks(mode: str, expected_encoding: str):
    probe = Env("easy", 5)
    mole_id = probe._world.mole
    global_s, world_s = extract_env_secrets(probe)
    assert f"mole:{mole_id}" in global_s
    assert "i am the mole" in world_s

    poisoned_env = Env("easy", 5, text_provider=_PoisonedProvider(mode, mole_id))
    findings = audit_env_outputs(poisoned_env)
    assert findings, f"missed covert {mode} leak"
    assert any(f["encoding"] == expected_encoding for f in findings), findings
