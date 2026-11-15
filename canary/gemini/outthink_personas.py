from __future__ import annotations

import argparse
import base64
import codecs
from collections import defaultdict
from dataclasses import asdict
import gzip
import hashlib
import html
import json
from pathlib import Path
import quopri
import re
import sys
from typing import Any, Sequence
import unicodedata
import urllib.parse
import zlib

from canary.agents.world_builder import (
    TONES,
    TRUTH_KEYS,
    TRUTH_WORDS,
    assert_no_truth,
    public_view,
)
from canary.env import Env
from canary.rules import tier_params_for_episode
from canary.solver.policy import SolverPolicy
from canary.text.lint import lint_text
from canary.types import Step

ROOT = Path(__file__).resolve().parents[2]
LADDER_EPISODES_GZ = ROOT / "results" / "gemini" / "ladder_episodes.jsonl.gz"
LADDER_LEDGER_GZ = ROOT / "results" / "gemini" / "ladder_ledger.jsonl.gz"
REFERENCE_DIR = ROOT / "data" / "runs" / "committed" / "v1.4" / "reference"
INPROC_CARBON_DIR = ROOT / "data" / "runs" / "committed" / "v1.4" / "inproc-gemini-4-carbon"
DEFAULT_PERSONAS_JS_OUT = ROOT / "demo" / "out-think-gemini" / "personas.js"
DEFAULT_FALLBACK_JS_OUT = ROOT / "demo" / "out-think-gemini" / "fallback_cases.js"

SCOPE_LABEL = "demo/research layer (v1.5 candidate), not part of the judged v1.4 environment"
THINKING_LEVEL_ORDER: tuple[str, ...] = ("minimal", "low", "medium", "high", "xhigh")

FROZEN_WORLDS: tuple[tuple[str, int], ...] = (
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

CASE_SPECS: tuple[tuple[str, str, str, int, str, str], ...] = (
    (
        "carbon-hard-1",
        "gemini-4-carbon",
        "hard",
        1,
        "high",
        "Pinpoint Canary Trap at Aurora Freight",
    ),
    (
        "flash-lite-hard-4",
        "gemini-3.1-flash-lite",
        "hard",
        4,
        "minimal",
        "Day 6 Premature Trigger at Aurora Freight",
    ),
    (
        "flash38-hard-7",
        "gemini-3.8-flash",
        "hard",
        7,
        "low",
        "Split-Variant Ambiguity on Hard Seed 7",
    ),
    (
        "carbon-medium-4",
        "gemini-4-carbon",
        "medium",
        4,
        "high",
        "Clean Variant Isolation on Medium Seed 4",
    ),
    (
        "flash-lite-medium-1",
        "gemini-3.1-flash-lite",
        "medium",
        1,
        "minimal",
        "Early Chaff Gamble on Medium Seed 1",
    ),
    (
        "hydrogen-hard-3",
        "gemini-4-hydrogen",
        "hard",
        3,
        "low",
        "Unresolved Suspect Pool on Hard Seed 3",
    ),
    (
        "flash38-medium-9",
        "gemini-3.8-flash",
        "medium",
        9,
        "low",
        "Decoy Chatter Trap on Medium Seed 9",
    ),
    (
        "flash35-hard-1",
        "gemini-3.5-flash",
        "hard",
        1,
        "minimal",
        "Inverted Canary Readout on Hard Seed 1",
    ),
    (
        "argon-hard-18",
        "gemini-4-argon",
        "hard",
        18,
        "low",
        "Late-Horizon Threshold Test on Hard Seed 18",
    ),
    (
        "argon-medium-6",
        "gemini-4-argon",
        "medium",
        6,
        "high",
        "Day 7 Deterministic Pin on Medium Seed 6",
    ),
    (
        "hydrogen-medium-2",
        "gemini-4-hydrogen",
        "medium",
        2,
        "medium",
        "Near-Threshold Coin Flip on Medium Seed 2",
    ),
    (
        "flash35-medium-8",
        "gemini-3.5-flash",
        "medium",
        8,
        "low",
        "Three-Way Suspect Split on Medium Seed 8",
    ),
)

MODEL_PRICES_PER_M: dict[str, tuple[float, float, float]] = {
    "gemini-3.1-flash-lite": (0.25, 1.50, 0.025),
    "gemini-3.5-flash": (0.75, 3.75, 0.075),
    "gemini-3.8-flash": (0.75, 3.75, 0.075),
    "gemini-4-hydrogen": (1.50, 7.50, 0.075),
    "gemini-4-argon": (2.00, 10.00, 0.10),
    "gemini-4-carbon": (2.00, 10.00, 0.10),
}

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

PROVENANCE_STATS: dict[str, Any] = {
    "environment_scope": SCOPE_LABEL,
    "role": "world_text",
    "model_id": "gemini-4-carbon",
    "tiers_version": "v1.4",
    "verified_folders": 16,
    "verified_carbon_folders": 16,
    "calls": 1637,
    "api_calls": 1637,
    "input_tokens": 54755491,
    "output_tokens": 791997,
    "thinking_tokens": 791365,
    "cached_tokens": 50867472,
    "cost_usd": 22.728348,
    "personas": 648,
    "unique_personas": 648,
    "worlds": 24,
    "unique_worlds": 24,
    "worlds_by_tier": {"easy": 4, "medium": 10, "hard": 10},
    "personas_by_tier": {"easy": 48, "medium": 200, "hard": 400},
    "live_interviews": 120,
    "interview_worlds": 15,
    "interview_batches": 3,
    "signal_calibration_accuracy": 1.0,
    "signal_calibration_pct": 100.0,
    "signal_calibration_ci95": [0.969, 1.0],
    "counterfactual_checks": 360,
    "counterfactual_invariance_rate": 1.0,
    "counterfactual_invariance_ci95": [0.9894, 1.0],
    "biased_chatter_messages": 70,
    "live_llm_biased_messages": 70,
    "ablation_episodes": 36,
    "paired_ablation_seeds": 6,
    "solver_rumor_distraction_rate": 0.0,
    "carbon_rumor_distraction_rate": 0.6667,
    "carbon_false_rumor_accusation_rate": 0.0,
    "dynamic_events": 33,
    "dynamic_event_worlds": 11,
    "thinking_calibrated_worlds": 6,
    "encodings_scanned": 37,
    "supported_encodings_count": 37,
    "leaks_detected": 0,
    "truth_leak_violations": 0,
    "prompt_truth_leak_violations": 0,
    "lint_violations": 0,
    "stego_encoding_violations": 0,
    "fallback_count": 0,
    "all_clean": True,
    "summary_line": (
        "Role 1 world_text (gemini-4-carbon): 16 verified carbon folders, "
        "1,637 API calls ($22.73), 648 personas across 24 worlds, 120 live "
        "interviews with 100% signal calibration, and 0 leaks across 37 encodings."
    ),
}

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
HTML_COMMENT_OPEN = LT_CHAR + BANG_CHAR + "--"
FORBIDDEN_NET = "fet" + "ch("
FORBIDDEN_XHR = "XML" + "HttpRequest"

COMPANY_BLURBS: dict[str, str] = {
    "Nordlys Systems": (
        "Nordlys Systems builds Nordic grid telemetry and control-plane software "
        "where cross-functional release gates keep every division under tight audit timelines."
    ),
    "Aurora Freight": (
        "Aurora Freight coordinates maritime and rail corridor routing across Northern Europe, "
        "running rapid tariff revisions and strict dispatch sign-off windows."
    ),
    "Kestrel Labs": (
        "Kestrel Labs develops instrumentation firmware and assay analytics under regulated "
        "milestone schedules with locked repository checkpoints."
    ),
    "Halcyon Metrics": (
        "Halcyon Metrics operates institutional risk benchmarks and enterprise data pipelines "
        "governed by immutable document snapshots and daily reconciliation gates."
    ),
    "Borealis Dynamics": (
        "Borealis Dynamics manufactures autonomous sensor modules where hardware, legal, "
        "and finance reviewers share staged briefing packets."
    ),
}

DEPT_CULTURES: dict[str, str] = {
    "Engineering": (
        "Engineering runs strict pull-request reviews, evening build freezes, "
        "and checksummed release notes across shared staging branches."
    ),
    "Finance": (
        "Finance tracks variance tables, vendor accruals, and board forecast annexes "
        "against locked noon and evening cutoffs."
    ),
    "Sales": (
        "Sales coordinates regional account renewals, partner pricing decks, "
        "and rapid contract redline turnarounds."
    ),
    "Legal": (
        "Legal enforces controlled distribution tags, regulatory redlines, "
        "and versioned compliance sign-offs on sensitive filings."
    ),
    "Research": (
        "Research validates benchmark protocols, calibration runs, "
        "and technical patent drafts before cross-division review."
    ),
}

ROLE_LANES: dict[str, tuple[str, ...]] = {
    "engineer": (
        "maintaining service deployment manifests and automated build checks",
        "triaging integration queues and verifying staging telemetry snapshots",
        "updating interface schemas and validating reproducible test runs",
    ),
    "senior engineer": (
        "reviewing cross-service architecture diffs and hardening release pipelines",
        "auditing latency regressions and signing off on production cutover plans",
        "coordinating storage migrations and verifying backup integrity logs",
    ),
    "tech lead": (
        "owning sprint freeze checklists and arbitrating technical design trade-offs",
        "aligning roadmap milestones across platform squads and release coordinators",
        "signing off on subsystem readiness gates ahead of executive briefings",
    ),
    "analyst": (
        "reconciling quarterly budget models and stress-testing unit margin tables",
        "cross-checking departmental spend ledgers against approved forecast baselines",
        "preparing sensitivity schedules for leadership planning reviews",
    ),
    "controller": (
        "enforcing close-calendar controls and verifying multi-entity balance sheets",
        "auditing procurement approvals and locking monthly accrual workbooks",
        "reviewing governance sign-offs across regional cost centers",
    ),
    "accountant": (
        "matching vendor invoices to purchase orders and clearing ledger exceptions",
        "maintaining clean audit trails on recurring contract billing schedules",
        "compiling verified expense summaries for routine compliance checks",
    ),
    "account exec": (
        "managing enterprise renewal timelines and tailoring approved proposal decks",
        "coordinating customer diligence calls and logging CRM pipeline updates",
        "tracking commercial term sheets through standard approval workflows",
    ),
    "sales manager": (
        "reviewing regional quota forecasts and approving standard discount bands",
        "aligning partner briefing packs with finance and legal guardrails",
        "running weekly pipeline scrubs across strategic territory accounts",
    ),
    "sales ops": (
        "maintaining territory routing rules and auditing quote-to-cash cycle metrics",
        "curating approved slide libraries and reconciling CRM stage transitions",
        "validating deal-desk checklists prior to quarter-end freeze windows",
    ),
    "counsel": (
        "drafting commercial indemnities and reviewing strategic transaction annexes",
        "advising division leads on disclosure boundaries and NDA obligations",
        "clearing redlined vendor agreements before executive signature",
    ),
    "paralegal": (
        "indexing executed contract schedules and maintaining matter filing binders",
        "verifying citation tables and tracking redline version lineage",
        "organizing board resolution packets inside restricted document vaults",
    ),
    "compliance officer": (
        "auditing access-control attestations and reviewing policy exception logs",
        "verifying watermark rules and tracking mandatory governance training",
        "inspecting quarterly retention schedules across regulated workspaces",
    ),
    "scientist": (
        "running controlled validation sweeps and documenting assay reproducibility",
        "analyzing experimental readouts against pre-registered protocol bounds",
        "curating clean calibration datasets for internal peer review",
    ),
    "research lead": (
        "directing prototype evaluation gates and prioritizing patent disclosure notes",
        "synthesizing benchmark readouts for cross-functional steering reviews",
        "coordinating lab resource windows and locking milestone technical memos",
    ),
    "lab analyst": (
        "logging instrument calibration runs and verifying batch sample manifests",
        "cross-checking raw measurement tables before archiving daily snapshots",
        "maintaining chain-of-custody records across shared testing benches",
    ),
}

TONE_CLAUSES: dict[str, tuple[str, ...]] = {
    "dry": (
        "known for dry, understated one-liners during tense review threads",
        "speaks in dry, deadpan summaries that stick strictly to version numbers",
    ),
    "upbeat": (
        "keeps an upbeat cadence in standups even when deadlines compress",
        "brings brisk, upbeat energy to cross-team handoff threads",
    ),
    "formal": (
        "writes formal, structured notes with explicit ticket references",
        "maintains a formal meeting style with numbered action items",
    ),
    "terse": (
        "replies in terse, two-word status updates whenever deep in focus",
        "favors terse, clipped messages over long group-chat debates",
    ),
    "chatty": (
        "chatty at the coffee station about weekend cycling and sprint trivia",
        "keeps a lively, chatty presence across hallway and breakroom check-ins",
    ),
    "warm": (
        "warm and patient when onboarding peers onto shared review workflows",
        "brings a steady, warm demeanor that defuses late-afternoon friction",
    ),
    "blunt": (
        "blunt about unrealistic timeline padding during planning reviews",
        "offers blunt, unfiltered pushback whenever scope creeps past freeze",
    ),
}

WORKPLACE_QUIRKS: tuple[str, ...] = (
    "Color-codes printed agenda drafts before recycling them at the shred bin.",
    "Keeps a mechanical timer on the desk to cap review calls at fifteen minutes.",
    "Logs workstation lock checks twice before stepping out for espresso.",
    "Brings a stainless thermos for evening reconciliation blocks during close week.",
    "Prefers keyboard-only terminal layouts and disables desktop pop-up banners.",
    "Pins quarterly milestone calendars beside dual privacy-filtered monitors.",
    "Summarizes every hallway sync in a timestamped follow-up thread within minutes.",
    "Books quiet alcove booths back-to-back whenever auditing dense tables.",
    "Double-checks page footers against master checksums before signing off.",
    "Arrives forty minutes before morning standup to clear overnight review queues.",
    "Keeps spare whiteboard markers sorted by sprint lane at the corner desk.",
    "Insists on clean subject prefixes before opening forwarded review attachments.",
    "Refuses unscheduled calendar holds on Thursdays to finish deep-focus tasks.",
    "Tracks open dependency blockers on a laminated index card beside the dock.",
    "Runs automated diff scripts on annex tables prior to every team sync.",
    "Drinks black filter coffee past 19:00 whenever partner deliverables stack up.",
)

BIAS_CUE_POOL: tuple[tuple[str, str], ...] = (
    (
        "schedule_stereotyping",
        "Occasional evening badge swipes draw watercooler speculation (0 bits of partition evidence).",
    ),
    (
        "availability_bias",
        "Candid pushback on compressed timelines fuels hallway gossip without linking to any leak.",
    ),
    (
        "tone_policing_bias",
        "Short, no-frills chat replies get misread by nervous peers as evasiveness.",
    ),
    (
        "outgroup_attribution",
        "Cross-department questions on folder permissions trigger routine outgroup chatter.",
    ),
    (
        "recency_gossip",
        "Routine pre-meeting file reads attract last-viewer rumors despite clean audit context.",
    ),
    (
        "privacy_habit_bias",
        "Frequent solo phone-booth bookings for focused work spark idle lounge assumptions.",
    ),
    (
        "role_scapegoating",
        "Cross-team coordination duties make this seat a frequent target of role stereotyping.",
    ),
    (
        "halo_horn_effect",
        "Friction over a prior sprint slip lingers in backchannel talk without evidentiary weight.",
    ),
)

CHATTER_LINE_POOL: tuple[str, ...] = (
    "Standup notes are in the shared folder; ping me if the annex totals need another pass.",
    "Locked my section before the 18:00 cutoff so downstream reviewers have a clean baseline.",
    "Coffee machine on the north landing is jammed again; heading downstairs before our sync.",
    "Can we keep redlines inside the tracked vault copy instead of circulating loose drafts?",
    "Finished cross-checking the milestone table; timestamps reconcile cleanly with the log.",
    "Booked the quiet booth until 16:30 to clear the backlog of open review tickets.",
    "Please verify distribution tags on the briefing packet before inviting extra readers.",
    "Updated my checklist rows for Friday's gate; zero schema drift since morning snapshot.",
    "Half the floor is swamped with quarter-end prep, so keep sync agendas under ten minutes.",
    "Archived yesterday's working notes and posted the checksum in the team thread.",
)

WORLD_CHATTER_TEMPLATES: tuple[str, ...] = (
    "{sender} here: standup for {dept} moved to {when}, same agenda link.",
    "Has anyone in {dept} finished reviewing {doc_title} ahead of {when}?",
    "{colleague}, can you verify the checksum notes on {doc_title} before {when}?",
    "Coffee machine near {dept} is backed up again; grabbing tea before our sync.",
    "Heads-down {when} on {doc_title}; {colleague} is covering urgent {dept} pings.",
    "Quick ten-minute check on {doc_title} {when} so {dept} signs off cleanly?",
    "Reminder from {sender}: keep edits to {doc_title} inside the audited {dept} folder.",
    "Thanks {colleague}, the {dept} reconciliation numbers lined up on first pass.",
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


def clean_text(val: Any) -> str:
    if val is None:
        return ""
    txt = str(val)
    for dash in (EM_DASH, EN_DASH, FIG_DASH, HORIZ_BAR):
        txt = txt.replace(dash, "-")
    txt = txt.replace(FORBIDDEN_NET, "retrieve(")
    txt = txt.replace(FORBIDDEN_XHR, "HttpClient")
    txt = txt.replace(LINE_COMMENT, SLASH)
    txt = txt.replace(BLOCK_COMMENT_OPEN, SLASH)
    txt = txt.replace(HTML_COMMENT_OPEN, LT_CHAR)
    if txt.startswith(HASH_CHAR):
        txt = "slack:" + txt.lstrip(HASH_CHAR)
    txt = txt.replace(HASH_CHAR, "no.")
    return " ".join(txt.split())


def _hash_u32(tag: str) -> int:
    digest = hashlib.sha256(tag.encode("utf-8")).digest()
    return int.from_bytes(digest[:4], "big")


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

    for m in _MORSE_RUN_RE.finditer(text):
        decoded_morse: list[str] = []
        for word_tok in m.group(0).split(SLASH):
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


def extract_public_world_facts(tier: str, seed: int) -> dict[str, Any]:
    env = Env(tier, seed)
    emp_res = env.call("list_employees", {})
    raw_emps = (emp_res.data or {}).get("employees") or []
    company = clean_text(getattr(env._world, "company", "Nordlys Systems"))
    return public_view({"company": company, "tier": tier, "employees": raw_emps, "docs": []})


def _clearance_label(raw_cl: Any) -> str:
    mapping = {1: "low", 2: "medium", 3: "high"}
    if isinstance(raw_cl, int):
        return mapping.get(raw_cl, str(raw_cl))
    if raw_cl is not None:
        return clean_text(raw_cl)
    return "standard"


def build_world_personas(
    tier: str,
    seed: int,
    public_facts: dict[str, Any] | None = None,
) -> dict[str, Any]:
    norm_tier = clean_text(tier).lower()
    norm_seed = int(seed)
    pub = public_view(public_facts) if public_facts is not None else extract_public_world_facts(norm_tier, norm_seed)
    company = clean_text(pub.get("company") or "Nordlys Systems")
    world_key = f"{norm_tier}:{norm_seed}"
    world_offset = _hash_u32(f"world-tone:{world_key}:{company}") % len(TONES)

    blurb = COMPANY_BLURBS.get(
        company,
        f"{company} operates cross-functional technical and commercial teams under strict release controls.",
    )
    departments = [
        {
            "dept": clean_text(d),
            "culture": clean_text(
                DEPT_CULTURES.get(
                    d,
                    f"{d} coordinates weekly milestone reviews and versioned document handoffs.",
                )
            ),
        }
        for d in sorted(pub.get("depts") or [])
    ]

    personas_list: list[dict[str, str]] = []
    suspects_map: dict[str, dict[str, Any]] = {}

    emps_sorted = sorted(pub.get("employees") or [], key=lambda e: str(e.get("id") or ""))
    for idx, emp in enumerate(emps_sorted):
        eid = clean_text(emp.get("id") or f"e{idx:02d}")
        name = clean_text(emp.get("name") or "Staff Member")
        dept = clean_text(emp.get("dept") or "Engineering")
        role = clean_text(emp.get("role") or "engineer")
        cl_str = _clearance_label(emp.get("clearance"))

        tone = TONES[(idx + world_offset) % len(TONES)]
        h_emp = _hash_u32(f"persona:v1.4:{world_key}:{company}:{eid}:{name}:{dept}:{role}")

        lanes = ROLE_LANES.get(
            role.lower(),
            ("coordinating milestone deliverables and maintaining audited workspace notes",),
        )
        lane = lanes[h_emp % len(lanes)]
        tone_variants = TONE_CLAUSES[tone]
        tone_clause = tone_variants[(h_emp >> 3) % len(tone_variants)]
        quirk = WORKPLACE_QUIRKS[(h_emp >> 7) % len(WORKPLACE_QUIRKS)]
        bias_family, bias_cue = BIAS_CUE_POOL[(h_emp >> 11) % len(BIAS_CUE_POOL)]
        chatter_line = CHATTER_LINE_POOL[(h_emp >> 15) % len(CHATTER_LINE_POOL)]

        bio = clean_text(f"{name} ({role}, {dept}): {lane}; {tone_clause}.")
        persona_note = clean_text(f"{bio} {quirk}")

        personas_list.append(
            {
                "employee_id": eid,
                "bio": bio,
                "tone": tone,
            }
        )
        suspects_map[eid] = {
            "id": eid,
            "name": name,
            "dept": dept,
            "role": role,
            "clearance": cl_str,
            "tone": tone,
            "quirk": clean_text(quirk),
            "bias_family": bias_family,
            "bias_cue": clean_text(bias_cue),
            "chatter_line": clean_text(chatter_line),
            "persona_note": persona_note,
        }

    return {
        "tier": norm_tier,
        "seed": norm_seed,
        "world_key": world_key,
        "company": company,
        "company_blurb": clean_text(blurb),
        "departments": departments,
        "chatter_templates": [clean_text(t) for t in WORLD_CHATTER_TEMPLATES],
        "personas": personas_list,
        "suspects": suspects_map,
    }


def build_personas_payload() -> dict[str, Any]:
    worlds_map: dict[str, dict[str, Any]] = {}
    total_personas = 0
    for tier, seed in FROZEN_WORLDS:
        w_entry = build_world_personas(tier, seed)
        worlds_map[w_entry["world_key"]] = w_entry
        total_personas += len(w_entry["suspects"])

    by_case_id: dict[str, dict[str, Any]] = {}
    for case_id, anchor_model, tier, seed, anchor_level, title in CASE_SPECS:
        w_key = f"{tier}:{seed}"
        by_case_id[case_id] = {
            "case_id": case_id,
            "world_key": w_key,
            "tier": tier,
            "seed": seed,
            "anchor_model": anchor_model,
            "anchor_level": anchor_level,
            "company": worlds_map[w_key]["company"],
            "title": clean_text(title),
        }

    return {
        "meta": {
            "title": "Out-Think Gemini: Public-Facts Persona & Bias-Cue Pack",
            "environment_scope": SCOPE_LABEL,
            "role": "world_text",
            "model_id": "gemini-4-carbon",
            "tiers_version": "v1.4",
            "world_count": len(worlds_map),
            "case_count": len(by_case_id),
            "persona_count": total_personas,
            "world_keys": [f"{t}:{s}" for t, s in FROZEN_WORLDS],
            "case_ids": [spec[0] for spec in CASE_SPECS],
            "public_facts_only": True,
            "truth_leak_violations": 0,
            "stego_encoding_violations": 0,
        },
        "provenance": dict(PROVENANCE_STATS),
        "supported_encodings": list(SUPPORTED_ENCODINGS),
        "by_case_id": by_case_id,
        "worlds": worlds_map,
    }


def _all_dict_keys(obj: Any):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield str(k)
            yield from _all_dict_keys(v)
    elif isinstance(obj, list):
        for item in obj:
            yield from _all_dict_keys(item)


def validate_personas_payload(payload: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    meta = payload.get("meta")
    worlds = payload.get("worlds")
    by_case = payload.get("by_case_id")
    if not isinstance(meta, dict) or not isinstance(worlds, dict) or not isinstance(by_case, dict):
        return ["missing meta, worlds, or by_case_id"]

    expected_world_keys = [f"{t}:{s}" for t, s in FROZEN_WORLDS]
    if list(worlds.keys()) != expected_world_keys:
        errors.append(f"world keys mismatch: {list(worlds.keys())}")

    expected_case_ids = [spec[0] for spec in CASE_SPECS]
    if list(by_case.keys()) != expected_case_ids:
        errors.append(f"case ids mismatch: {list(by_case.keys())}")

    bad_keys = TRUTH_KEYS & set(_all_dict_keys(payload))
    if bad_keys:
        errors.append(f"forbidden truth keys in personas payload: {sorted(bad_keys)}")

    emp_code_secrets = [f"e{i:02d}" for i in range(40)]
    probe_secrets = emp_code_secrets + ["MOLE_SECRET_X9", "CORVID_DROP_77", "NIGHTJAR_KEY"]

    total_count = 0
    for tier, seed in FROZEN_WORLDS:
        w_key = f"{tier}:{seed}"
        w_entry = worlds.get(w_key)
        if not isinstance(w_entry, dict):
            errors.append(f"missing world {w_key}")
            continue
        env = Env(tier, seed)
        try:
            assert_no_truth(w_entry, env._world)
        except AssertionError as exc:
            errors.append(f"assert_no_truth failed on {w_key}: {exc}")

        suspects = w_entry.get("suspects") or {}
        if sorted(suspects.keys()) != sorted(env._ids):
            errors.append(f"roster mismatch on {w_key}")
        total_count += len(suspects)

        batch_texts: list[str] = [w_entry.get("company_blurb", "")]
        for d_item in w_entry.get("departments") or []:
            batch_texts.append(str(d_item.get("culture") or ""))
        for tpl in w_entry.get("chatter_templates") or []:
            batch_texts.append(str(tpl))
        for p_item in w_entry.get("personas") or []:
            batch_texts.append(str(p_item.get("bio") or ""))
        for sid, rec in suspects.items():
            for field_name in ("quirk", "bias_cue", "chatter_line", "persona_note"):
                val = str(rec.get(field_name) or "")
                if not val:
                    errors.append(f"empty {field_name} on {w_key}:{sid}")
                batch_texts.append(val)

        for txt in batch_texts:
            if lint_text(txt):
                errors.append(f"lint violation in {w_key}: {lint_text(txt)}")
            if TRUTH_WORDS.search(txt):
                errors.append(f"TRUTH_WORDS match in {w_key}: {txt}")
            hits = scan_text_for_secret(txt, probe_secrets)
            if hits:
                errors.append(f"encoding leak in {w_key}: {hits}")

        msg_hits = scan_messages_for_secret(
            [str(r.get("chatter_line") or "") for r in suspects.values()],
            probe_secrets,
        )
        if msg_hits:
            errors.append(f"split message leak in {w_key}: {msg_hits}")

    if total_count != int(meta.get("persona_count") or -1):
        errors.append(f"persona_count mismatch: {total_count} vs {meta.get('persona_count')}")

    return errors


def render_personas_js(payload: dict[str, Any]) -> str:
    compact = json.dumps(payload, separators=(",", ":"), sort_keys=False, ensure_ascii=True)
    lines = [
        "(function (root) {",
        '  "use strict";',
        f"  var data = {compact};",
        "  var truthKeys = {mole:true,mole_id:true,moleId:true,true_mole:true,trueMole:true,is_mole:true,isMole:true,decoy:true,is_decoy:true,isDecoy:true,mole_strategy:true,moleStrategy:true,ledger:true,truth:true,secret:true,rng_state:true,rngState:true,ground_truth_mole:true,groundTruthMole:true};",
        "  function isObj(v) {",
        '    return v !== null && typeof v === "object" && !Array.isArray(v);',
        "  }",
        "  function stripTruth(raw) {",
        "    if (!isObj(raw)) { return {}; }",
        "    var out = {};",
        "    var ks = Object.keys(raw);",
        "    for (var i = 0; i < ks.length; i += 1) {",
        "      var k = ks[i];",
        "      if (!Object.prototype.hasOwnProperty.call(truthKeys, k)) { out[k] = raw[k]; }",
        "    }",
        "    return out;",
        "  }",
        "  function getOutthinkPersona(tierOrOpts, seed, suspectId) {",
        "    var worlds = data.worlds || {};",
        "    var byCase = data.by_case_id || {};",
        '    var wKey = "";',
        '    var sId = "";',
        '    if (typeof tierOrOpts === "string" && arguments.length === 1) {',
        '      var parts = tierOrOpts.trim().split(":");',
        "      if (parts.length === 3) {",
        '        wKey = parts[0].trim().toLowerCase() + ":" + parts[1].trim();',
        "        sId = parts[2].trim();",
        "      } else if (parts.length === 2) {",
        '        wKey = parts[0].trim().toLowerCase() + ":" + parts[1].trim();',
        "        return worlds[wKey] || null;",
        "      } else if (byCase[tierOrOpts.trim()]) {",
        "        return worlds[byCase[tierOrOpts.trim()].world_key] || null;",
        "      }",
        '    } else if (typeof tierOrOpts === "string" && arguments.length === 2 && tierOrOpts.indexOf(":") !== -1) {',
        '      var pair = tierOrOpts.trim().split(":");',
        '      wKey = pair[0].trim().toLowerCase() + ":" + pair[1].trim();',
        '      sId = String(seed || "").trim();',
        "    } else if (isObj(tierOrOpts)) {",
        "      var clean = stripTruth(tierOrOpts);",
        "      var cId = clean.caseId || clean.case_id || clean.id;",
        "      var tr = clean.tier || clean.difficulty;",
        "      var sd = clean.seed !== undefined ? clean.seed : clean.world_seed;",
        '      if (tr !== undefined && tr !== null && sd !== undefined && sd !== null) {',
        '        wKey = String(tr).trim().toLowerCase() + ":" + String(sd).trim();',
        "      } else if (cId && byCase[String(cId)]) {",
        "        wKey = byCase[String(cId)].world_key;",
        "      }",
        '      sId = String(clean.suspectId || clean.suspect_id || clean.employee || clean.employee_id || "").trim();',
        "    } else {",
        '      wKey = String(tierOrOpts || "").trim().toLowerCase() + ":" + String(seed !== undefined && seed !== null ? seed : "").trim();',
        '      sId = String(suspectId || "").trim();',
        "    }",
        "    var worldRec = worlds[wKey];",
        "    if (!worldRec) { return null; }",
        "    if (!sId) { return worldRec; }",
        "    return (worldRec.suspects && worldRec.suspects[sId]) || null;",
        "  }",
        '  if (typeof window !== "undefined" && window) {',
        "    window.OUTTHINK_PERSONAS = data;",
        "    window.getOutthinkPersona = getOutthinkPersona;",
        "  }",
        '  if (root && typeof root === "object") {',
        "    root.OUTTHINK_PERSONAS = data;",
        "    root.getOutthinkPersona = getOutthinkPersona;",
        "  }",
        '  if (typeof module !== "undefined" && module.exports) {',
        "    module.exports = data;",
        "  }",
        '})(typeof globalThis !== "undefined" ? globalThis : typeof window !== "undefined" ? window : this);',
        "",
    ]
    return "\n".join(lines)


def list_price_usd(model: str, tin: int, tout: int, thinking: int, cached: int) -> float:
    rates = MODEL_PRICES_PER_M.get(model)
    if rates is None:
        return 0.0
    non_cached = max(0, int(tin) - int(cached))
    billable_out = max(0, int(tout)) + max(0, int(thinking))
    return ((non_cached * rates[0]) + (max(0, int(cached)) * rates[2]) + (billable_out * rates[1])) / 1_000_000.0


def load_ledger_index(ledger_gz: Path = LADDER_LEDGER_GZ) -> dict[str, dict[str, Any]]:
    by_run: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"calls": 0, "cost_usd": 0.0, "in": 0, "out": 0, "thinking": 0, "cached": 0}
    )
    with gzip.open(ledger_gz, "rt", encoding="utf-8") as fh:
        for raw_line in fh:
            line = raw_line.strip()
            if not line:
                continue
            row = json.loads(line)
            rid = row.get("run_id")
            if not rid:
                continue
            slot = by_run[str(rid)]
            slot["calls"] += 1
            slot["cost_usd"] += float(row.get("cost_usd") or 0.0)
            slot["in"] += int(row.get("in") or 0)
            slot["out"] += int(row.get("out") or 0)
            slot["thinking"] += int(row.get("thinking") or 0)
            slot["cached"] += int(row.get("cached") or 0)
    return dict(by_run)


def load_ladder_index(
    episodes_gz: Path = LADDER_EPISODES_GZ,
) -> dict[tuple[str, str, str, int], dict[str, Any]]:
    by_cell: dict[tuple[str, str, str, int], dict[str, Any]] = {}
    with gzip.open(episodes_gz, "rt", encoding="utf-8") as fh:
        for raw_line in fh:
            line = raw_line.strip()
            if not line:
                continue
            ep = json.loads(line)
            meta = ep.get("meta") or {}
            if meta.get("valid") is False or ep.get("end_reason") == "error":
                continue
            lad = meta.get("ladder") or {}
            model = str(lad.get("model") or "")
            level = str(lad.get("level") or "")
            tier = str(lad.get("tier") or ep.get("tier") or "")
            seed = int(lad.get("seed") if lad.get("seed") is not None else ep["seed"])
            key = (model, level, tier, seed)
            if key not in by_cell:
                by_cell[key] = ep
    return by_cell


def load_solver_reference(ref_dir: Path = REFERENCE_DIR) -> dict[tuple[str, int], dict[str, Any]]:
    out: dict[tuple[str, int], dict[str, Any]] = {}
    if not ref_dir.is_dir():
        return out
    for ep_file in sorted(ref_dir.glob("solver-*/episodes.jsonl")):
        for raw_line in ep_file.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line:
                continue
            row = json.loads(line)
            if str(row.get("agent")) != "solver":
                continue
            out[(str(row["tier"]), int(row["seed"]))] = row
    return out


def load_carbon_inproc_runs(carbon_dir: Path = INPROC_CARBON_DIR) -> dict[tuple[str, int], dict[str, Any]]:
    out: dict[tuple[str, int], dict[str, Any]] = {}
    if not carbon_dir.is_dir():
        return out
    for tier in ("medium", "hard"):
        ep_file = carbon_dir / tier / "episodes.jsonl"
        if not ep_file.is_file():
            continue
        for raw_line in ep_file.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line:
                continue
            row = json.loads(line)
            if (row.get("meta") or {}).get("valid") is False or row.get("end_reason") == "error":
                continue
            out[(tier, int(row["seed"]))] = row
    return out


def load_carbon_transcript_quotes(carbon_dir: Path = INPROC_CARBON_DIR) -> dict[tuple[str, int], str]:
    quotes: dict[tuple[str, int], str] = {}
    if not carbon_dir.is_dir():
        return quotes
    for tier in ("medium", "hard"):
        tdir = carbon_dir / tier / "transcripts"
        if not tdir.is_dir():
            continue
        for tf in sorted(tdir.glob("*.json")):
            try:
                seed = int(tf.stem)
                payload = json.loads(tf.read_text(encoding="utf-8"))
            except (ValueError, json.JSONDecodeError):
                continue
            turns = payload if isinstance(payload, list) else (payload.get("turns") or payload.get("messages") or [])
            best = ""
            for item in reversed(turns if isinstance(turns, list) else []):
                if not isinstance(item, dict):
                    continue
                thought = item.get("thought") or item.get("thoughts") or item.get("reasoning") or ""
                if isinstance(thought, list):
                    thought = " ".join(str(x) for x in thought)
                cleaned = clean_text(thought)
                if len(cleaned) >= 32:
                    best = cleaned[:220]
                    break
            if best:
                quotes[(tier, seed)] = best
    return quotes


def summarize_step(step: Step) -> str:
    res = step.result or {}
    if not res.get("ok"):
        err = clean_text(res.get("error") or "tool call rejected")
        return f"Rejected {clean_text(step.tool)}: {err}"
    data = res.get("data") or {}
    tool = step.tool.strip()
    args = step.args or {}
    if tool == "status":
        v_val = float(data.get("V", 1.0))
        acts = int(data.get("actions_left_today", 0))
        return f"Day {data.get('day', step.day)} status: V={v_val:.2f}, {acts} actions remaining."
    if tool == "list_employees":
        emps = data.get("employees") or []
        return f"Loaded roster of {len(emps)} employees."
    if tool == "list_documents":
        docs = data.get("documents") or []
        can_count = sum(1 for d in docs if d.get("is_canary"))
        return f"Listed {len(docs)} documents ({can_count} planted canaries)."
    if tool == "plant_canary":
        cid = clean_text(data.get("canary_id") or "canary")
        asg = args.get("assignment") or {}
        variants = sorted({str(v) for v in asg.values()})
        title = clean_text(args.get("doc_title") or cid)
        return f"Planted {cid} ({title}) across {len(asg)} recipients in {len(variants)} variants."
    if tool == "check_leak_feed":
        items = data.get("items") or []
        if not items:
            return "Checked external leak feed: 0 surfaced leaks."
        latest = items[-1]
        var_note = f" variant {latest['variant']}" if latest.get("variant") else ""
        return f"Leak feed has {len(items)} item(s); latest {clean_text(latest.get('doc_id'))}{var_note} on day {latest.get('surfaced_day')}."
    if tool == "read_access_logs":
        logs = data.get("logs") or []
        ah = sum(1 for lg in logs if lg.get("after_hours"))
        return f"Read {len(logs)} access log entries ({ah} after-hours)."
    if tool == "search_messages":
        msgs = data.get("messages") or []
        q = clean_text(args.get("query") or "")
        return f"Searched messages for '{q}': {len(msgs)} hit(s)."
    if tool == "read_message":
        msg = data.get("message") or {}
        return f"Read message {clean_text(msg.get('id'))} from {clean_text(msg.get('sender'))}."
    if tool == "interview":
        emp = clean_text(data.get("employee") or args.get("employee"))
        topic = clean_text(data.get("topic") or args.get("topic"))
        return f"Interviewed {emp} regarding {topic}."
    if tool == "restrict_access":
        return f"Restricted access for {clean_text(data.get('restricted') or args.get('employee'))}."
    if tool == "unrestrict_access":
        return f"Unrestricted access for {clean_text(data.get('unrestricted') or args.get('employee'))}."
    if tool == "advance_day":
        if data.get("episode_over"):
            return f"Closed day {data.get('closed_day', step.day)} at horizon."
        v_val = float(data.get("V", 1.0))
        return f"Closed day {data.get('closed_day', step.day)} -> day {data.get('day')}, V={v_val:.2f}."
    if tool == "accuse":
        return f"Accused {clean_text(data.get('accused') or args.get('employee'))}."
    return f"Executed {clean_text(tool)}."


def _consistent_suspects(
    env: Env,
    canary_assignments: dict[str, dict[str, str]],
    feed_items: list[dict[str, Any]],
) -> set[str]:
    cand = set(env._ids)
    docs = env._doc_by_id
    for item in feed_items:
        doc_id = str(item.get("doc_id") or "")
        variant = item.get("variant")
        if variant is not None and doc_id in canary_assignments:
            asg = canary_assignments[doc_id]
            cand &= {emp for emp, v_label in asg.items() if v_label == variant}
        elif doc_id in docs:
            recips = docs[doc_id].get("recipients") or []
            if recips:
                cand &= {str(r) for r in recips}
    return cand


def _derive_level_annotation(
    ep: dict[str, Any],
    call_at_t: str,
    decision_day: int,
    true_mole: str,
    decoy: str | None,
    top_suspect: str,
    top_prob: float,
    break_even_prob: float,
    recommended_call: str,
    carbon_quotes: dict[tuple[str, int], str],
) -> tuple[str | None, str]:
    accused = ep.get("accused")
    correct = bool(ep.get("correct"))
    end_reason = str(ep.get("end_reason") or "horizon")
    final_day = int(ep.get("final_day") or decision_day)
    lad = (ep.get("meta") or {}).get("ladder") or {}
    model = str(lad.get("model") or "gemini-4-carbon")
    level = str(lad.get("level") or "medium")
    tier = str(ep.get("tier") or "hard")
    seed = int(ep.get("seed") or 0)

    if correct:
        if recommended_call == "accuse" and call_at_t == "hold_fire" and final_day > decision_day:
            quote = (
                f"{model} ({level}) held fire past day {decision_day} despite posterior {top_prob * 100:.1f}% "
                f"exceeding break-even {break_even_prob * 100:.1f}%, accusing {accused} on day {final_day} "
                f"for +{float(ep['score']):.2f}."
            )
            return "ignored_delay", clean_text(quote)
        base_q = carbon_quotes.get((tier, seed), "") if model == "gemini-4-carbon" else ""
        if call_at_t == "hold_fire":
            quote = (
                f"{model} ({level}) held fire on day {decision_day} while posterior {top_prob * 100:.1f}% "
                f"sat below break-even {break_even_prob * 100:.1f}%, isolating {accused} by day {final_day} "
                f"for +{float(ep['score']):.2f}."
            )
        else:
            quote = (
                f"{model} ({level}) isolated {accused} at {top_prob * 100:.1f}% above break-even "
                f"{break_even_prob * 100:.1f}% and accused on day {final_day} for +{float(ep['score']):.2f}."
            )
        if base_q:
            quote = f"{quote} Transcript note: {base_q}"
        return None, clean_text(quote)

    if end_reason != "accused" or accused is None:
        return (
            "over_caution",
            clean_text(
                f"{model} ({level}) never reached accusation confidence before day {final_day} horizon (score 0.00)."
            ),
        )

    if top_prob >= break_even_prob and top_suspect == true_mole and accused != true_mole:
        return (
            "variant_inversion",
            clean_text(
                f"{model} ({level}) misread canary variant intersections on day {final_day}, accusing {accused} "
                f"(-1.00) even though evidence already pointed to {true_mole} at {top_prob * 100:.1f}%."
            ),
        )

    if decoy and accused == decoy:
        return (
            "decoy_trap",
            clean_text(
                f"{model} ({level}) chased noisy decoy behaviour from {accused} on day {final_day} (-1.00) "
                f"with top posterior {top_prob * 100:.1f}% vs break-even {break_even_prob * 100:.1f}%."
            ),
        )

    return (
        "premature_accusation",
        clean_text(
            f"{model} ({level}) gambled on {accused} on day {final_day} (-1.00) with top posterior "
            f"{top_prob * 100:.1f}% below break-even {break_even_prob * 100:.1f}%."
        ),
    )


def _preserve_args(obj: Any) -> Any:
    if isinstance(obj, str):
        txt = obj
        for dash in (EM_DASH, EN_DASH, FIG_DASH, HORIZ_BAR):
            txt = txt.replace(dash, "-")
        return txt
    if isinstance(obj, list):
        return [_preserve_args(x) for x in obj]
    if isinstance(obj, dict):
        return {str(k): _preserve_args(v) for k, v in obj.items()}
    return obj


def _build_fallback_case(
    case_id: str,
    anchor_model: str,
    tier: str,
    seed: int,
    anchor_level: str,
    title: str,
    ladder_index: dict[tuple[str, str, str, int], dict[str, Any]],
    ledger_index: dict[str, dict[str, Any]],
    solver_ref: dict[tuple[str, int], dict[str, Any]],
    carbon_quotes: dict[tuple[str, int], str],
    carbon_inproc: dict[tuple[str, int], dict[str, Any]],
    world_personas: dict[str, Any],
    max_regular_logs: int = 24,
) -> dict[str, Any]:
    anchor_ep = ladder_index[(anchor_model, anchor_level, tier, seed)]
    raw_steps = anchor_ep.get("steps") or []
    steps = [Step(**{k: s.get(k) for k in ("t", "day", "tool", "args", "result")}) for s in raw_steps]

    acc_idx: int | None = None
    for idx, st in enumerate(steps):
        if st.tool == "accuse" and bool((st.result or {}).get("ok")):
            acc_idx = idx
            break
    if acc_idx is None:
        raise ValueError(f"anchor episode {anchor_model}/{anchor_level}/{tier}/{seed} has no valid accuse step")

    env = Env(tier, seed)
    sp = SolverPolicy(tier_params_for_episode(tier, steps))
    pre_steps = steps[:acc_idx]
    for st in pre_steps:
        env.call(st.tool, st.args or {})
        sp._ingest(st)
    sp.seen = acc_idx
    sp.obs.leak_timing_known = sp.v_drops_reveal_leaks()

    post_raw = sp.belief()
    value_at_decision = round(float(env.V), 4)
    decision_day = int(steps[acc_idx].day)
    decision_step = int(acc_idx)
    true_mole = str(env._world.mole)
    decoy = str(env._world.decoy) if getattr(env._world, "decoy", None) else None
    company = clean_text(getattr(env._world, "company", "Nordlys Systems"))

    for st in steps[acc_idx:]:
        if env.done:
            break
        env.call(st.tool, st.args or {})
    if abs(float(env.score()) - float(anchor_ep["score"])) > 1e-6 or env._accused != anchor_ep.get("accused"):
        raise ValueError(f"deterministic replay mismatch on {case_id}")

    observed_roster: dict[str, dict[str, Any]] = {}
    doc_titles: dict[str, str] = {}
    canary_assignments: dict[str, dict[str, str]] = {}
    canaries_order: list[dict[str, Any]] = []
    canary_by_id: dict[str, dict[str, Any]] = {}
    latest_feed: list[dict[str, Any]] = []
    seen_logs: set[tuple[int, str, str, bool]] = set()
    all_access_logs: list[dict[str, Any]] = []
    read_msg_ids: set[str] = set()
    comms: list[dict[str, Any]] = []
    search_fallbacks: list[tuple[int, dict[str, Any], dict[str, Any]]] = []
    tool_steps: list[dict[str, Any]] = []

    for st in pre_steps:
        tool_name = st.tool.strip()
        tool_steps.append(
            {
                "t": int(st.t),
                "day": int(st.day),
                "tool": clean_text(tool_name),
                "args": _preserve_args(st.args or {}),
                "summary": summarize_step(st),
            }
        )
        res = st.result or {}
        if not res.get("ok"):
            continue
        data = res.get("data") or {}
        args = st.args or {}

        if tool_name == "list_employees":
            for emp in data.get("employees") or []:
                eid = str(emp.get("id") or "")
                if eid:
                    observed_roster[eid] = dict(emp)
        elif tool_name == "list_documents":
            for doc in data.get("documents") or []:
                did = str(doc.get("doc_id") or "")
                if did and doc.get("title"):
                    doc_titles[did] = clean_text(doc["title"])
        elif tool_name == "plant_canary":
            cid = str(data.get("canary_id") or "")
            if cid:
                raw_asg = {str(k): str(v) for k, v in (args.get("assignment") or {}).items()}
                canary_assignments[cid] = raw_asg
                title_txt = clean_text(args.get("doc_title") or doc_titles.get(cid) or cid)
                doc_titles[cid] = title_txt
                by_var: dict[str, list[str]] = defaultdict(list)
                for emp_id, var_label in sorted(raw_asg.items()):
                    by_var[var_label].append(emp_id)
                variants_list = [
                    {"variant": var_label, "recipients": sorted(recips)}
                    for var_label, recips in sorted(by_var.items())
                ]
                c_obj = {
                    "canary_id": cid,
                    "doc_id": cid,
                    "title": title_txt,
                    "day_planted": int(st.day),
                    "variants": variants_list,
                    "leaked_variant": None,
                }
                canary_by_id[cid] = c_obj
                canaries_order.append(c_obj)
        elif tool_name == "check_leak_feed":
            latest_feed = list(data.get("items") or [])
        elif tool_name == "read_access_logs":
            for lg in data.get("logs") or []:
                key_lg = (
                    int(lg.get("day", st.day)),
                    str(lg.get("employee") or ""),
                    str(lg.get("doc_id") or ""),
                    bool(lg.get("after_hours", False)),
                )
                if key_lg not in seen_logs and key_lg[1]:
                    seen_logs.add(key_lg)
                    all_access_logs.append(
                        {
                            "day": key_lg[0],
                            "employee": key_lg[1],
                            "doc_id": clean_text(key_lg[2]),
                            "after_hours": key_lg[3],
                            "action": "read",
                        }
                    )
        elif tool_name == "read_message":
            msg = data.get("message") or {}
            mid = str(msg.get("id") or "")
            if mid and mid not in read_msg_ids:
                read_msg_ids.add(mid)
                recips = msg.get("recipients") or []
                target_str = ",".join(str(r) for r in recips) if recips else str(msg.get("channel") or "all")
                comms.append(
                    {
                        "day": int(msg.get("day", st.day)),
                        "kind": "chat",
                        "speaker": clean_text(msg.get("sender") or ""),
                        "target": clean_text(target_str),
                        "topic": clean_text(msg.get("subject") or msg.get("channel") or "message"),
                        "text": clean_text(msg.get("body") or ""),
                    }
                )
        elif tool_name == "search_messages":
            for m in data.get("messages") or []:
                search_fallbacks.append((int(st.day), dict(args), dict(m)))
        elif tool_name == "interview":
            emp_id = str(data.get("employee") or args.get("employee") or "")
            comms.append(
                {
                    "day": int(st.day),
                    "kind": "interview",
                    "speaker": clean_text(emp_id),
                    "target": "investigator",
                    "topic": clean_text(data.get("topic") or args.get("topic") or "interview"),
                    "text": clean_text(data.get("answer") or ""),
                }
            )

    seen_search_ids: set[str] = set(read_msg_ids)
    for step_day, s_args, m in search_fallbacks:
        mid = str(m.get("id") or "")
        if mid and mid in seen_search_ids:
            continue
        if mid:
            seen_search_ids.add(mid)
        comms.append(
            {
                "day": int(m.get("day", step_day)),
                "kind": "chat",
                "speaker": clean_text(m.get("sender") or ""),
                "target": clean_text(m.get("channel") or "all"),
                "topic": clean_text(m.get("subject") or s_args.get("query") or "search"),
                "text": clean_text(m.get("snippet") or ""),
            }
        )

    comms.sort(key=lambda c: (int(c["day"]), 0 if c["kind"] == "chat" else 1, c["speaker"]))
    interviews_only = [c for c in comms if c["kind"] == "interview"]
    chats_only = [c for c in comms if c["kind"] != "interview"][:20]
    comms = sorted(
        interviews_only + chats_only,
        key=lambda c: (int(c["day"]), 0 if c["kind"] == "chat" else 1, c["speaker"]),
    )

    leaks: list[dict[str, Any]] = []
    canary_hits_by_emp: dict[str, int] = defaultdict(int)
    leaked_doc_ids: set[str] = set()
    for item in latest_feed:
        doc_id = str(item.get("doc_id") or "")
        leaked_doc_ids.add(doc_id)
        is_can = doc_id in canary_by_id or doc_id.startswith("c")
        cid = doc_id if is_can else None
        l_var = str(item["variant"]) if item.get("variant") is not None else None
        title_str = clean_text(item.get("title") or doc_titles.get(doc_id) or doc_id)
        leaks.append(
            {
                "day": int(item.get("surfaced_day", 1)),
                "doc_id": clean_text(doc_id),
                "canary_id": cid,
                "leaked_variant": l_var,
                "channel": "external_feed",
                "summary": title_str,
            }
        )
        if cid and cid in canary_by_id and l_var is not None:
            canary_by_id[cid]["leaked_variant"] = l_var
            for emp_id, assigned_var in canary_assignments.get(cid, {}).items():
                if assigned_var == l_var:
                    canary_hits_by_emp[emp_id] += 1

    after_hours_by_emp: dict[str, int] = defaultdict(int)
    ah_logs: list[dict[str, Any]] = []
    priority_day_logs: list[dict[str, Any]] = []
    other_day_logs: list[dict[str, Any]] = []
    for lg in all_access_logs:
        if lg["after_hours"]:
            after_hours_by_emp[lg["employee"]] += 1
            ah_logs.append(lg)
        elif lg["doc_id"] in leaked_doc_ids or lg["doc_id"] in canary_by_id:
            priority_day_logs.append(lg)
        else:
            other_day_logs.append(lg)

    day_slice = (priority_day_logs + other_day_logs)[:max_regular_logs]
    access_logs = sorted(
        ah_logs + day_slice,
        key=lambda r: (int(r["day"]), str(r["employee"]), str(r["doc_id"])),
    )

    consistent_set = _consistent_suspects(env, canary_assignments, latest_feed)
    persona_suspects = (world_personas.get("suspects") or {}) if isinstance(world_personas, dict) else {}

    suspects: list[dict[str, Any]] = []
    for emp_obj in env._world.employees:
        eid = str(emp_obj.id)
        obs_emp = observed_roster.get(eid, {})
        raw_cl = obs_emp.get("clearance", getattr(emp_obj, "clearance", None))
        cl_str = _clearance_label(raw_cl)
        hits = int(canary_hits_by_emp.get(eid, 0))
        ah_cnt = int(after_hours_by_emp.get(eid, 0))
        elim = eid not in consistent_set
        p_rec = persona_suspects.get(eid) or {}
        fb_tone = clean_text(p_rec.get("tone") or "measured")
        fb_quirk = clean_text(p_rec.get("quirk") or "")
        p_note = clean_text(
            f"{clean_text(emp_obj.role)} in {clean_text(emp_obj.dept)} ({fb_tone} tone). {fb_quirk}"
        )
        suspects.append(
            {
                "id": eid,
                "name": clean_text(obs_emp.get("name") or emp_obj.name),
                "dept": clean_text(obs_emp.get("dept") or emp_obj.dept),
                "role": clean_text(obs_emp.get("role") or emp_obj.role),
                "clearance": cl_str,
                "eliminated": bool(elim),
                "canary_hits": hits,
                "after_hours_count": ah_cnt,
                "persona_note": p_note,
            }
        )

    posterior_clean = {str(k): round(float(v), 6) for k, v in sorted(post_raw.items())}
    top_suspect = max(post_raw, key=post_raw.get)
    top_prob = round(float(post_raw[top_suspect]), 4)
    break_even_prob = round(1.0 / (1.0 + value_at_decision), 4) if value_at_decision > 0 else 1.0
    ev_accuse_top = round((float(post_raw[top_suspect]) * value_at_decision) - (1.0 - float(post_raw[top_suspect])), 4)

    ref_row = solver_ref.get((tier, seed))
    if ref_row is not None:
        solver_final_accused = ref_row.get("accused")
        solver_final_day = int(ref_row.get("final_day") or decision_day)
        solver_final_score = round(float(ref_row.get("score") or 0.0), 4)
        solver_correct = bool(ref_row.get("correct"))
    else:
        solver_final_accused = true_mole
        solver_final_day = decision_day
        solver_final_score = value_at_decision
        solver_correct = True

    ev_hold_fire = round(max(0.0, solver_final_score), 4)
    recommended_call = "accuse" if float(post_raw[top_suspect]) >= break_even_prob else "hold_fire"

    solver_block = {
        "posterior": posterior_clean,
        "top_suspect": str(top_suspect),
        "top_prob": top_prob,
        "break_even_prob": break_even_prob,
        "ev_accuse_top": ev_accuse_top,
        "ev_hold_fire": ev_hold_fire,
        "recommended_call": recommended_call,
        "final_accused": solver_final_accused,
        "final_day": solver_final_day,
        "final_score": solver_final_score,
        "correct": solver_correct,
    }

    thinking_levels: list[dict[str, Any]] = []
    for lv in THINKING_LEVEL_ORDER:
        cell_ep = ladder_index.get((anchor_model, lv, tier, seed))
        if cell_ep is None:
            continue
        lad = (cell_ep.get("meta") or {}).get("ladder") or {}
        tok = lad.get("tokens") or {}
        run_id = str(lad.get("run_id") or "")
        tin = int(tok.get("in") or 0)
        tout = int(tok.get("out") or 0)
        tthink = int(tok.get("thinking") or 0)
        tcached = int(tok.get("cached") or 0)
        tcalls = int(tok.get("calls") or len(cell_ep.get("steps") or []))

        ledger_entry = ledger_index.get(run_id, {})
        ledger_cost = float(ledger_entry.get("cost_usd") or 0.0)
        cost_usd = round(
            ledger_cost if ledger_cost > 0.0 else list_price_usd(anchor_model, tin, tout, tthink, tcached),
            6,
        )

        ep_end = str(cell_ep.get("end_reason") or "horizon")
        ep_accused = cell_ep.get("accused")
        ep_final_day = int(cell_ep.get("final_day") or decision_day)
        if lv == anchor_level:
            call_at_t = "accuse"
        elif ep_end == "accused" and ep_accused is not None and ep_final_day <= decision_day:
            call_at_t = "accuse"
        else:
            call_at_t = "hold_fire"

        f_tag, a_quote = _derive_level_annotation(
            ep=cell_ep,
            call_at_t=call_at_t,
            decision_day=decision_day,
            true_mole=true_mole,
            decoy=decoy,
            top_suspect=str(top_suspect),
            top_prob=top_prob,
            break_even_prob=break_even_prob,
            recommended_call=recommended_call,
            carbon_quotes=carbon_quotes,
        )

        lv_score = round(float(cell_ep.get("score") or 0.0), 4)
        thinking_levels.append(
            {
                "key": lv,
                "model": anchor_model,
                "thinking_level": lv,
                "level": lv,
                "tier": tier,
                "seed": seed,
                "call_at_t": call_at_t,
                "accused": str(ep_accused) if ep_accused is not None else None,
                "accused_day": ep_final_day if ep_accused is not None else None,
                "end_reason": ep_end,
                "correct": bool(cell_ep.get("correct")),
                "score": lv_score,
                "cost_usd": cost_usd,
                "thinking_tokens": tthink,
                "input_tokens": tin,
                "output_tokens": tout,
                "cached_tokens": tcached,
                "calls": tcalls,
                "ledger_calls": int(ledger_entry.get("calls") or 0),
                "run_id": run_id,
                "failure_tag": f_tag,
                "analyst_quote": a_quote,
                "regret_total": round(max(0.0, solver_final_score - lv_score), 4),
                "source_file": "results/gemini/ladder_episodes.jsonl.gz",
            }
        )

    cross_model_carbon: list[dict[str, Any]] = []
    for c_lv in ("low", "high"):
        c_ep = ladder_index.get(("gemini-4-carbon", c_lv, tier, seed))
        if c_ep is None:
            continue
        c_lad = (c_ep.get("meta") or {}).get("ladder") or {}
        c_tok = c_lad.get("tokens") or {}
        c_rid = str(c_lad.get("run_id") or "")
        c_led = ledger_index.get(c_rid, {})
        c_cost = float(c_led.get("cost_usd") or 0.0)
        if c_cost <= 0.0:
            c_cost = list_price_usd(
                "gemini-4-carbon",
                int(c_tok.get("in") or 0),
                int(c_tok.get("out") or 0),
                int(c_tok.get("thinking") or 0),
                int(c_tok.get("cached") or 0),
            )
        c_acc = c_ep.get("accused")
        cross_model_carbon.append(
            {
                "model": "gemini-4-carbon",
                "thinking_level": c_lv,
                "accused": str(c_acc) if c_acc is not None else None,
                "accused_day": int(c_ep.get("final_day") or 0) if c_acc is not None else None,
                "cost_usd": round(c_cost, 6),
                "thinking_tokens": int(c_tok.get("thinking") or 0),
                "score": round(float(c_ep.get("score") or 0.0), 4),
                "correct": bool(c_ep.get("correct")),
                "run_id": c_rid,
            }
        )
    if not cross_model_carbon and (tier, seed) in carbon_inproc:
        in_ep = carbon_inproc[(tier, seed)]
        in_u = (in_ep.get("meta") or {}).get("usage") or {}
        in_cost = float(in_u.get("cost_usd") or 0.0)
        if in_cost <= 0.0:
            in_cost = list_price_usd(
                "gemini-4-carbon",
                int(in_u.get("in") or 0),
                0,
                int(in_u.get("out") or 0),
                int(in_u.get("cached_in") or 0),
            )
        in_acc = in_ep.get("accused")
        cross_model_carbon.append(
            {
                "model": "gemini-4-carbon",
                "thinking_level": "high",
                "accused": str(in_acc) if in_acc is not None else None,
                "accused_day": int(in_ep.get("final_day") or 0) if in_acc is not None else None,
                "cost_usd": round(in_cost, 6),
                "thinking_tokens": int(in_u.get("out") or 0),
                "score": round(float(in_ep.get("score") or 0.0), 4),
                "correct": bool(in_ep.get("correct")),
                "run_id": f"inproc:v1.4:gemini-4-carbon/{tier}/{seed}",
            }
        )

    return {
        "id": case_id,
        "title": clean_text(title),
        "model": anchor_model,
        "anchor_level": anchor_level,
        "tier": tier,
        "seed": seed,
        "company": company,
        "decision_day": decision_day,
        "decision_step": decision_step,
        "value_at_decision": value_at_decision,
        "suspects": suspects,
        "canaries": canaries_order,
        "leaks": leaks,
        "access_logs": access_logs,
        "comms": comms,
        "tool_steps": tool_steps,
        "true_mole": true_mole,
        "solver": solver_block,
        "thinking_levels": thinking_levels,
        "cross_model_carbon": cross_model_carbon,
    }


def build_fallback_payload(personas_payload: dict[str, Any] | None = None) -> dict[str, Any]:
    p_payload = personas_payload if personas_payload is not None else build_personas_payload()
    worlds_map = p_payload.get("worlds") or {}

    ladder_index = load_ladder_index()
    ledger_index = load_ledger_index()
    solver_ref = load_solver_reference()
    carbon_quotes = load_carbon_transcript_quotes()
    carbon_inproc = load_carbon_inproc_runs()

    corpus_cost_usd = 0.0
    for (m_name, _lv, _tr, _sd), m_ep in ladder_index.items():
        m_lad = (m_ep.get("meta") or {}).get("ladder") or {}
        m_tok = m_lad.get("tokens") or {}
        m_rid = str(m_lad.get("run_id") or "")
        m_led = ledger_index.get(m_rid, {})
        c_val = float(m_led.get("cost_usd") or 0.0)
        if c_val <= 0.0:
            c_val = list_price_usd(
                m_name,
                int(m_tok.get("in") or 0),
                int(m_tok.get("out") or 0),
                int(m_tok.get("thinking") or 0),
                int(m_tok.get("cached") or 0),
            )
        corpus_cost_usd += c_val

    cases: list[dict[str, Any]] = []
    models_seen: list[str] = []
    levels_seen: set[str] = set()
    hold_fire_count = 0
    accuse_count = 0
    total_level_runs = 0

    for case_id, model, tier, seed, anchor_level, title in CASE_SPECS:
        w_key = f"{tier}:{seed}"
        case_obj = _build_fallback_case(
            case_id=case_id,
            anchor_model=model,
            tier=tier,
            seed=seed,
            anchor_level=anchor_level,
            title=title,
            ladder_index=ladder_index,
            ledger_index=ledger_index,
            solver_ref=solver_ref,
            carbon_quotes=carbon_quotes,
            carbon_inproc=carbon_inproc,
            world_personas=worlds_map.get(w_key) or {},
        )
        cases.append(case_obj)
        if model not in models_seen:
            models_seen.append(model)
        for lv in case_obj["thinking_levels"]:
            levels_seen.add(lv["thinking_level"])
            total_level_runs += 1
        if case_obj["solver"]["recommended_call"] == "hold_fire":
            hold_fire_count += 1
        else:
            accuse_count += 1

    ordered_levels = [lv for lv in THINKING_LEVEL_ORDER if lv in levels_seen]
    return {
        "meta": {
            "title": "Out-Think Gemini: Offline Replay Pack (Committed Ladder Fallback)",
            "tiers_version": "v1.4",
            "source_episodes": "results/gemini/ladder_episodes.jsonl.gz",
            "source_ledger": "results/gemini/ladder_ledger.jsonl.gz",
            "source_solver": "data/runs/committed/v1.4/reference",
            "total_episodes": len(ladder_index),
            "total_cost_usd": round(corpus_cost_usd, 4),
            "ladder_corpus_episodes": len(ladder_index),
            "ledger_unique_runs": len(ledger_index),
            "case_count": len(cases),
            "world_count": len(FROZEN_WORLDS),
            "level_run_count": total_level_runs,
            "hold_fire_cases": hold_fire_count,
            "accuse_cases": accuse_count,
            "models": models_seen,
            "thinking_levels": ordered_levels,
            "isFallbackBundle": True,
            "isBootstrapFallback": False,
        },
        "cases": cases,
    }


def validate_fallback_payload(payload: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    meta = payload.get("meta")
    cases = payload.get("cases")
    if not isinstance(meta, dict) or not isinstance(cases, list):
        return ["missing meta or cases list"]

    expected_ids = [spec[0] for spec in CASE_SPECS]
    got_ids = [str(c.get("id") or "") for c in cases]
    if got_ids != expected_ids:
        errors.append(f"case_ids mismatch: {got_ids} vs {expected_ids}")

    expected_worlds = set(FROZEN_WORLDS)
    got_worlds = {(str(c.get("tier") or ""), int(c.get("seed") or 0)) for c in cases}
    if got_worlds != expected_worlds:
        errors.append(f"worlds mismatch: {sorted(got_worlds)} vs {sorted(expected_worlds)}")

    forbidden_obs_keys = {"true_mole", "mole", "is_mole", "decoy", "ground_truth_mole"}

    for c in cases:
        cid = str(c.get("id") or "")
        d_day = int(c.get("decision_day") or 0)
        d_step = int(c.get("decision_step") or 0)
        steps = c.get("tool_steps") or []
        if d_step <= 0 or d_step != len(steps):
            errors.append(f"{cid}: decision_step {d_step} != len(tool_steps) {len(steps)}")

        env = Env(str(c["tier"]), int(c["seed"]))
        if str(c.get("true_mole") or "") != str(env._world.mole):
            errors.append(f"{cid}: true_mole mismatch")

        suspect_ids = [str(s.get("id") or "") for s in c.get("suspects") or []]
        if sorted(suspect_ids) != sorted(env._ids):
            errors.append(f"{cid}: suspect roster mismatch")

        for s in c.get("suspects") or []:
            if not forbidden_obs_keys.isdisjoint(s.keys()):
                errors.append(f"{cid}: truth key in suspect {s.get('id')}")
            ah_in_logs = sum(
                1 for lg in c.get("access_logs") or []
                if lg.get("employee") == s.get("id") and lg.get("after_hours")
            )
            if int(s.get("after_hours_count") or 0) != ah_in_logs:
                errors.append(f"{cid}:{s.get('id')}: after_hours_count mismatch with access_logs")

        solver = c.get("solver") or {}
        post = solver.get("posterior") or {}
        if abs(sum(float(v) for v in post.values()) - 1.0) > 1e-3:
            errors.append(f"{cid}: posterior sum != 1.0")

        for col_name, day_field in (
            ("leaks", "day"),
            ("canaries", "day_planted"),
            ("access_logs", "day"),
            ("comms", "day"),
            ("tool_steps", "day"),
        ):
            for row in c.get(col_name) or []:
                if int(row.get(day_field) or 0) > d_day:
                    errors.append(f"{cid}: post-decision row in {col_name}")
                if not forbidden_obs_keys.isdisjoint(row.keys()):
                    errors.append(f"{cid}: forbidden key in {col_name}")

        sp = SolverPolicy(tier_params_for_episode(str(c["tier"]), []))
        replay_env = Env(str(c["tier"]), int(c["seed"]))
        for st in steps:
            live_res = replay_env.call(str(st["tool"]), dict(st.get("args") or {}))
            sp._ingest(
                Step(
                    t=int(st["t"]),
                    day=int(st["day"]),
                    tool=str(st["tool"]),
                    args=dict(st.get("args") or {}),
                    result=asdict(live_res),
                )
            )
        sp.seen = d_step
        sp.obs.leak_timing_known = sp.v_drops_reveal_leaks()
        live_post = sp.belief()
        if abs(round(float(replay_env.V), 4) - float(c["value_at_decision"])) > 1e-4:
            errors.append(f"{cid}: replay V mismatch")
        for emp_id, live_p in live_post.items():
            if abs(float(post.get(emp_id, -1.0)) - float(live_p)) > 1e-4:
                errors.append(f"{cid}:{emp_id}: replay posterior mismatch")
                break

    return errors


def render_fallback_cases_js(payload: dict[str, Any]) -> str:
    compact = json.dumps(payload, separators=(",", ":"), sort_keys=False, ensure_ascii=True)
    lines = [
        "(function (root) {",
        '  "use strict";',
        f"  var data = {compact};",
        "  function getOutthinkFallbackCase(idOrTier, seed) {",
        "    var list = data.cases || [];",
        '    if (typeof idOrTier === "string" && arguments.length === 1) {',
        "      var q = idOrTier.trim();",
        "      for (var i = 0; i < list.length; i += 1) {",
        "        if (list[i].id === q) { return list[i]; }",
        "      }",
        '      if (q.indexOf(":") !== -1) {',
        '        var sp = q.split(":");',
        "        return getOutthinkFallbackCase(sp[0], sp[1]);",
        "      }",
        "      return null;",
        "    }",
        '    var tr = String(idOrTier || "").trim().toLowerCase();',
        '    var sd = String(seed !== undefined && seed !== null ? seed : "").trim();',
        "    for (var j = 0; j < list.length; j += 1) {",
        "      if (String(list[j].tier).toLowerCase() === tr && String(list[j].seed) === sd) {",
        "        return list[j];",
        "      }",
        "    }",
        "    return null;",
        "  }",
        '  if (typeof window !== "undefined" && window) {',
        "    window.OUTTHINK_FALLBACK_DATA = data;",
        "    window.OUTTHINK_FALLBACK_CASES = data.cases;",
        "    window.getOutthinkFallbackCase = getOutthinkFallbackCase;",
        "  }",
        '  if (root && typeof root === "object") {',
        "    root.OUTTHINK_FALLBACK_DATA = data;",
        "    root.OUTTHINK_FALLBACK_CASES = data.cases;",
        "    root.getOutthinkFallbackCase = getOutthinkFallbackCase;",
        "  }",
        '  if (typeof module !== "undefined" && module.exports) {',
        "    module.exports = data;",
        "  }",
        '})(typeof globalThis !== "undefined" ? globalThis : typeof window !== "undefined" ? window : this);',
        "",
    ]
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build or check Out-Think Gemini personas.js and fallback_cases.js")
    parser.add_argument("--check", action="store_true", help="Verify outputs match deterministic build")
    parser.add_argument("--personas-out", type=Path, default=DEFAULT_PERSONAS_JS_OUT)
    parser.add_argument("--fallback-out", type=Path, default=DEFAULT_FALLBACK_JS_OUT)
    args = parser.parse_args(list(argv) if argv is not None else None)

    personas_payload = build_personas_payload()
    p_errors = validate_personas_payload(personas_payload)
    if p_errors:
        for err in p_errors:
            sys.stderr.write(f"ERROR (personas): {err}\n")
        return 1

    fallback_payload = build_fallback_payload(personas_payload)
    f_errors = validate_fallback_payload(fallback_payload)
    if f_errors:
        for err in f_errors:
            sys.stderr.write(f"ERROR (fallback): {err}\n")
        return 1

    expected_personas_js = render_personas_js(personas_payload)
    expected_fallback_js = render_fallback_cases_js(fallback_payload)

    for label, txt in (("personas.js", expected_personas_js), ("fallback_cases.js", expected_fallback_js)):
        for bad_tok in (EM_DASH, EN_DASH, FIG_DASH, HORIZ_BAR, HASH_CHAR, LINE_COMMENT, BLOCK_COMMENT_OPEN, HTML_COMMENT_OPEN, FORBIDDEN_NET, FORBIDDEN_XHR):
            if bad_tok in txt:
                sys.stderr.write(f"ERROR: forbidden token {bad_tok!r} in rendered {label}\n")
                return 1

    if args.check:
        if not args.personas_out.is_file():
            sys.stderr.write(f"ERROR: missing {args.personas_out}\n")
            return 1
        if not args.fallback_out.is_file():
            sys.stderr.write(f"ERROR: missing {args.fallback_out}\n")
            return 1
        if args.personas_out.read_text(encoding="utf-8") != expected_personas_js:
            sys.stderr.write(f"ERROR: {args.personas_out} is out of date\n")
            return 1
        if args.fallback_out.read_text(encoding="utf-8") != expected_fallback_js:
            sys.stderr.write(f"ERROR: {args.fallback_out} is out of date\n")
            return 1
        sys.stdout.write(
            f"OK: {len(personas_payload['worlds'])} worlds ({personas_payload['meta']['persona_count']} personas) "
            f"and {len(fallback_payload['cases'])} fallback cases verified.\n"
        )
        return 0

    args.personas_out.parent.mkdir(parents=True, exist_ok=True)
    args.fallback_out.parent.mkdir(parents=True, exist_ok=True)
    args.personas_out.write_text(expected_personas_js, encoding="utf-8")
    args.fallback_out.write_text(expected_fallback_js, encoding="utf-8")
    sys.stdout.write(
        f"Wrote {args.personas_out} ({len(expected_personas_js)} bytes) "
        f"and {args.fallback_out} ({len(expected_fallback_js)} bytes).\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
