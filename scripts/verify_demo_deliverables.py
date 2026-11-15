from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import struct
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

EM_DASH = chr(0x2014)
EN_DASH = chr(0x2013)
UNICODE_MINUS = chr(0x2212)
PLUS_MINUS = chr(0x00B1)
MIDDOT = chr(0x00B7)

LEGACY_DOCS_DEMO_EM_DASH_LINE = (
    chr(35) * 2
    + f" 0:00{EN_DASH}1:00 {MIDDOT} The story (P) {EM_DASH} sets up everything"
)

CHECK_NUMERIC_PROVENANCE = "Demo Numeric Provenance Parity"
CHECK_LIVING_OFFICE_HONESTY = "Living Office v1.6 Honesty Guard"
CHECK_OFFLINE_ASSETS_HYGIENE = "Demo Offline file://, Asset Budget & Hygiene"

CHECK_NAMES: tuple[str, ...] = (
    CHECK_NUMERIC_PROVENANCE,
    CHECK_LIVING_OFFICE_HONESTY,
    CHECK_OFFLINE_ASSETS_HYGIENE,
)

EXPECTED_TIERS_VERSION = "v1.4"
EXPECTED_V14_HASH = "a8f99c2537c91d72"
MAX_MP4_BYTES = 15 * 1024 * 1024

DEFAULT_BASE = "origin/justSilas"

SILAS_PROTECTED_EXACT: frozenset[str] = frozenset(
    {
        "canary/env.py",
        "canary/rules.py",
        "canary/reproduce.py",
    }
)
SILAS_PROTECTED_PREFIXES: tuple[str, ...] = (
    "canary/solver/",
    "harbor/",
)

ALLOWED_ENV_TEMPLATES: frozenset[str] = frozenset(
    {".env.example", ".env.sample", ".env.template"}
)

API_KEY_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "google_api_key",
        re.compile(r"(?<![0-9A-Za-z+/_-])AIza[0-9A-Za-z_-]{20,}"),
    ),
    (
        "sk_api_key",
        re.compile(
            r"(?<![0-9A-Za-z+/_-])sk-(?:proj-|ant-|live-|test-|svcacct-)?[0-9A-Za-z_-]{16,}"
        ),
    ),
    (
        "github_pat",
        re.compile(
            r"(?<![0-9A-Za-z_])(?:gh[pousr]_[0-9A-Za-z]{20,}|github_pat_[0-9A-Za-z_]{20,})"
        ),
    ),
    (
        "inline_env_secret",
        re.compile(
            r"\b(?:GEMINI_API_KEY|GOOGLE_API_KEY|OPENAI_API_KEY|ANTHROPIC_API_KEY)\s*=\s*['\"]?[A-Za-z0-9_-]{16,}"
        ),
    ),
)

RAW_HEADLINE_CI_RX = re.compile(r"65%\s*\[\s*24%\s*,\s*98%\s*\]")
LA_HEADLINE_CI_RX = re.compile(r"72%\s*\[\s*52%\s*,\s*91%\s*\]")
N30_RX = re.compile(r"\bn\s*=\s*30\b", re.IGNORECASE)
SEEDS_029_RX = re.compile(r"\b0\s*-\s*29\b")
POSTHOC_LOCK_RX = re.compile(
    r"(?:post-hoc|671ed96|not\s+(?:a\s+)?pre-register\w*)",
    re.IGNORECASE,
)
BAD_PREREG_029_RX = re.compile(
    r"(?:pre-register\w*[^\n]{0,50}\b0\s*-\s*29\b|\b0\s*-\s*29\b[^\n]{0,50}pre-register\w*)",
    re.IGNORECASE,
)
INTERROGATIVE_PREREG_029_RX = re.compile(
    r"\b(?:were|was|are|is)\s+(?:the\s+)?(?:primary\s+|locked\s+)?(?:dev\s+)?seeds?\s+`?0\s*-\s*29`?\s+pre-register\w*[^\n?]*\?",
    re.IGNORECASE,
)
UNAPPROVED_FLASH_GAP_RX = re.compile(
    r"(?:75%\s*\[\s*36%\s*,\s*123%\s*\]|opencode-gemini-3\.5-flash|opencode:google/gemini-3\.5-flash)",
    re.IGNORECASE,
)

V16_CITATION_RX = re.compile(
    r"(?:\bv1\.6\b|living_office_v16\.html|living[\s_-]+office)",
    re.IGNORECASE,
)
OFF_BY_DEFAULT_RX = re.compile(r"\boff[-\s]+by[-\s]+default\b", re.IGNORECASE)
GATE_B_RX = re.compile(r"\bgate[-\s]*b\b", re.IGNORECASE)
GATE_B_NEGATIVE_RX = re.compile(
    r"(?:did\s+not\s+pass|does\s+not\s+pass|not\s+pass\w*|never\s+pass\w*|"
    r"gate[-\s]*b[^\n.]{0,80}\b(?:not|fail\w*|drop\w*|negativ\w*|never)\b|"
    r"\b(?:negative|failed|dropped)[^\n.]{0,50}gate[-\s]*b\b)",
    re.IGNORECASE,
)
V16_REPLACED_V14_RX = re.compile(
    r"(?:"
    r"\bv1\.6\b[^\n.;]{0,70}\b(?:replaced|replaces|superseded|supersedes)\b[^\n.;]{0,50}\b(?:v1\.4|a8f99c2537c91d72)\b"
    r"|\b(?:replaced|replaces|superseded|supersedes)\s+(?:frozen\s+)?(?:v1\.4|a8f99c2537c91d72)\b"
    r"|\bv1\.6\s+is\s+(?:now\s+)?(?:the\s+)?(?:judged\s+default|default\s+benchmark|on[-\s]+by[-\s]+default|active\s+default)\b"
    r"|\bTIERS_VERSION\s*[:=]\s*['\"]?v1\.6\b"
    r")",
    re.IGNORECASE,
)
V16_PASSED_GATE_B_RX = re.compile(
    r"(?<!not\s)(?<!never\s)\b(?:v1\.6\s+)?passed\s+(?:the\s+)?gate[-\s]*b\b|\bgate[-\s]*b\s*:\s*pass(?:ed)?\b",
    re.IGNORECASE,
)

HTML_SCRIPT_TAG_RX = re.compile(r"<script\b[^>]*>", re.IGNORECASE)
HTML_LINK_TAG_RX = re.compile(r"<link\b[^>]*>", re.IGNORECASE)
HTML_MEDIA_TAG_RX = re.compile(
    r"<(?:img|iframe|video|audio|source|embed|object)\b[^>]*>",
    re.IGNORECASE,
)
HTML_SRC_ATTR_RX = re.compile(
    r"\bsrc\s*=\s*(?:\"([^\"]*)\"|'([^']*)'|([^\s>\"']+))",
    re.IGNORECASE,
)
HTML_HREF_ATTR_RX = re.compile(
    r"\bhref\s*=\s*(?:\"([^\"]*)\"|'([^']*)'|([^\s>\"']+))",
    re.IGNORECASE,
)
HTML_REL_ATTR_RX = re.compile(
    r"\brel\s*=\s*(?:\"([^\"]*)\"|'([^']*)'|([^\s>\"']+))",
    re.IGNORECASE,
)
CSS_EXTERNAL_IMPORT_RX = re.compile(
    r"@import\s+(?:url\s*\(\s*)?['\"]?(?:https?:)?//",
    re.IGNORECASE,
)
CSS_EXTERNAL_URL_RX = re.compile(
    r"url\s*\(\s*['\"]?(?:https?:)?//[^)'\"\s]+",
    re.IGNORECASE,
)
JS_EXTERNAL_FETCH_RX = re.compile(
    r"\bfetch\s*\(\s*['\"`](?:https?:)?//",
    re.IGNORECASE,
)
JS_EXTERNAL_IMPORT_RX = re.compile(
    r"\bimport\s+(?:[^'\"\n]+\s+from\s+|\(\s*)['\"`](?:https?:)?//",
    re.IGNORECASE,
)
JS_EXTERNAL_XHR_WS_RX = re.compile(
    r"(?:\.open\s*\(\s*['\"][A-Za-z]+['\"]\s*,\s*['\"`](?:https?:)?//|\bnew\s+WebSocket\s*\(\s*['\"`]wss?://)",
    re.IGNORECASE,
)
LIVE_LLM_ENDPOINT_RX = re.compile(
    r"(?:generativelanguage\.googleapis\.com|api\.openai\.com|api\.anthropic\.com|openrouter\.ai/api)",
    re.IGNORECASE,
)
ALLOWED_ARENA_PYODIDE_SRC_RX = re.compile(
    r"^https://cdn\.jsdelivr\.net/pyodide/v[0-9.]+/full/pyodide\.js$",
    re.IGNORECASE,
)

AVC_CODEC_TAGS: tuple[bytes, ...] = (
    b"avc1",
    b"avc3",
    b"avcC",
    b"h264",
    b"H264",
)
MP4_CONTAINER_ATOMS: frozenset[bytes] = frozenset(
    {b"moov", b"trak", b"mdia", b"minf", b"stbl", b"edts", b"dinf", b"udta"}
)


@dataclass
class CheckResult:
    name: str
    status: str
    summary: str
    details: list[str] = field(default_factory=list)


def _normalize_numeric_text(text: str) -> str:
    return (
        text.replace(UNICODE_MINUS, "-")
        .replace(EN_DASH, "-")
        .replace(PLUS_MINUS, "+/-")
    )


def _attr_val(match: re.Match[str] | None) -> str:
    if match is None:
        return ""
    return (match.group(1) or match.group(2) or match.group(3) or "").strip()


def _is_external_http_url(url: str) -> bool:
    low = url.strip().lower()
    return low.startswith(("http://", "https://", "//"))


def _compute_tier_hash(tiers: dict[str, Any], known_v_mode: bool) -> str:
    obj = {
        "tiers": {k: v.to_dict() for k, v in tiers.items()},
        "known_v_mode": known_v_mode,
    }
    encoded = json.dumps(obj, sort_keys=True, default=list).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:16]


def _is_silas_protected(rel_path: str) -> bool:
    norm = rel_path.replace("\\", "/").strip()
    while norm.startswith("./"):
        norm = norm[2:]
    if norm in SILAS_PROTECTED_EXACT or norm in {"canary/solver", "harbor"}:
        return True
    return any(norm.startswith(prefix) for prefix in SILAS_PROTECTED_PREFIXES)


def _git_env(root: Path) -> dict[str, str]:
    env = dict(os.environ)
    env["GIT_CEILING_DIRECTORIES"] = str(root.parent)
    return env


def _parse_name_status_z(raw_bytes: bytes) -> list[str]:
    tokens = raw_bytes.decode("utf-8", errors="replace").split("\0")
    paths: list[str] = []
    idx = 0
    while idx < len(tokens) and tokens[idx]:
        status_tok = tokens[idx]
        idx += 1
        code = status_tok[0]
        if code in {"R", "C"}:
            if idx + 1 < len(tokens):
                paths.append(tokens[idx])
                paths.append(tokens[idx + 1])
                idx += 2
        else:
            if idx < len(tokens):
                paths.append(tokens[idx])
                idx += 1
    return [p for p in paths if p]


def _find_primary_hard_row(rows: Sequence[Any]) -> dict[str, Any] | None:
    for item in rows:
        if not isinstance(item, dict):
            continue
        if item.get("group") != "v1.4/opencode-gemini-4-carbon":
            continue
        if item.get("tier") != "hard":
            continue
        label_low = str(item.get("label", "")).lower()
        if "alternative" in label_low or "not the headline" in label_low:
            continue
        return item
    return None


def _load_seed_map(jsonl_paths: Sequence[Path]) -> dict[int, dict[str, Any]]:
    out: dict[int, dict[str, Any]] = {}
    for path in jsonl_paths:
        if not path.is_file():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            if isinstance(row, dict) and isinstance(row.get("seed"), int):
                out[int(row["seed"])] = row
    return out


def _verify_committed_v14_ground_truth(root: Path) -> list[str]:
    failures: list[str] = []
    v14_dir = root / "data" / "runs" / "committed" / "v1.4"
    if not v14_dir.is_dir():
        return failures

    paired_json = v14_dir / "paired_table_gemini.json"
    if not paired_json.is_file():
        failures.append("missing data/runs/committed/v1.4/paired_table_gemini.json")
    else:
        try:
            rows = json.loads(paired_json.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            failures.append(f"paired_table_gemini.json unreadable/invalid ({exc})")
            rows = None
        if isinstance(rows, list):
            hard_row = _find_primary_hard_row(rows)
            if hard_row is None:
                failures.append(
                    "paired_table_gemini.json missing primary v1.4/opencode-gemini-4-carbon hard row"
                )
            else:
                if hard_row.get("n") != 30 or hard_row.get("seeds") != list(range(30)):
                    failures.append(
                        "paired_table_gemini.json primary hard row expected n=30 and seeds 0..29"
                    )
                if round(float(hard_row.get("mean", -999.0)), 3) != 0.322:
                    failures.append(
                        f"paired_table_gemini.json primary hard mean {hard_row.get('mean')} != 0.322"
                    )
                if round(float(hard_row.get("solver_same_seeds", -999.0)), 3) != 0.499:
                    failures.append(
                        f"paired_table_gemini.json solver_same_seeds {hard_row.get('solver_same_seeds')} != 0.499"
                    )
                raw_triplet = (
                    round(float(hard_row.get("ratio", 0.0)) * 100),
                    round(float(hard_row.get("ratio_lo", 0.0)) * 100),
                    round(float(hard_row.get("ratio_hi", 0.0)) * 100),
                )
                if raw_triplet != (65, 24, 98):
                    failures.append(
                        f"paired_table_gemini.json raw ratio triplet {raw_triplet} != (65, 24, 98)"
                    )
                la_triplet = (
                    round(float(hard_row.get("post_expected_ratio", 0.0)) * 100),
                    round(float(hard_row.get("post_expected_lo", 0.0)) * 100),
                    round(float(hard_row.get("post_expected_hi", 0.0)) * 100),
                )
                if la_triplet != (72, 52, 91):
                    failures.append(
                        f"paired_table_gemini.json luck-adjusted triplet {la_triplet} != (72, 52, 91)"
                    )

    gem_ep_path = v14_dir / "opencode-gemini-4-carbon" / "hard" / "episodes.jsonl"
    ref_dir = v14_dir / "reference"
    solver_ep_paths = (
        sorted(ref_dir.glob("solver-hard-*/episodes.jsonl")) if ref_dir.is_dir() else []
    )
    if gem_ep_path.is_file() and solver_ep_paths:
        try:
            gem_map = _load_seed_map([gem_ep_path])
            sol_map = _load_seed_map(solver_ep_paths)
        except (OSError, ValueError) as exc:
            failures.append(f"committed hard episodes.jsonl parse failure ({exc})")
            return failures

        expected_seeds = (
            (6, "e34", 0.71, 6, "e34", True, 0.73, 6),
            (26, "e08", 0.69, 7, "e04", False, -1.00, 10),
        )
        for (
            seed_num,
            true_mole,
            sol_score,
            sol_day,
            gem_accused,
            gem_correct,
            gem_score,
            gem_day,
        ) in expected_seeds:
            s_ep = sol_map.get(seed_num)
            g_ep = gem_map.get(seed_num)
            if s_ep is None or g_ep is None:
                failures.append(f"committed hard episodes missing seed {seed_num}")
                continue
            if (
                s_ep.get("accused") != true_mole
                or not bool(s_ep.get("correct"))
                or round(float(s_ep.get("score", -999.0)), 2) != sol_score
                or int(s_ep.get("final_day", -1)) != sol_day
            ):
                failures.append(f"committed solver seed {seed_num} mismatch vs locked ground truth")
            if (
                g_ep.get("accused") != gem_accused
                or bool(g_ep.get("correct")) is not gem_correct
                or round(float(g_ep.get("score", -999.0)), 2) != gem_score
                or int(g_ep.get("final_day", -1)) != gem_day
            ):
                failures.append(f"committed gemini seed {seed_num} mismatch vs locked ground truth")

    return failures


def _check_headline_and_lock_in_doc(rel: str, norm_text: str, require_means: bool) -> list[str]:
    errs: list[str] = []
    if not RAW_HEADLINE_CI_RX.search(norm_text):
        errs.append(f"{rel}: missing locked raw headline CI '65% [24%, 98%]'")
    if not LA_HEADLINE_CI_RX.search(norm_text):
        errs.append(f"{rel}: missing locked luck-adjusted headline CI '72% [52%, 91%]'")
    if not N30_RX.search(norm_text):
        errs.append(f"{rel}: missing locked sample size 'n=30'")
    if not SEEDS_029_RX.search(norm_text):
        errs.append(f"{rel}: missing locked dev seed range '0-29'")
    if not POSTHOC_LOCK_RX.search(norm_text):
        errs.append(f"{rel}: missing post-hoc seed-lock provenance ('post-hoc' / '671ed96')")

    if require_means:
        if not re.search(r"[+]?0\.322\b", norm_text):
            errs.append(f"{rel}: missing Gemini hard mean '+0.322'")
        if not re.search(r"[+]?0\.499\b", norm_text):
            errs.append(f"{rel}: missing paired SolverPolicy hard mean '+0.499'")

    for lineno, line in enumerate(norm_text.splitlines(), 1):
        stripped_q = INTERROGATIVE_PREREG_029_RX.sub("", line)
        if BAD_PREREG_029_RX.search(stripped_q) and not POSTHOC_LOCK_RX.search(stripped_q):
            errs.append(
                f"{rel}:{lineno}: false pre-registration claim on dev seeds 0-29 (must disclose post-hoc lock)"
            )
        if UNAPPROVED_FLASH_GAP_RX.search(line):
            errs.append(
                f"{rel}:{lineno}: unapproved gemini-3.5-flash gap claim cited in demo deliverable"
            )
    return errs


def _check_seed6_facts(rel: str, norm_text: str) -> list[str]:
    errs: list[str] = []
    if not re.search(r"\be34\b", norm_text):
        errs.append(f"{rel}: Seed 6 Caught missing true mole 'e34'")
    if not re.search(r"(?<![0-9])[+]?0\.73(?![0-9])", norm_text):
        errs.append(f"{rel}: Seed 6 Caught missing Gemini score '+0.73'")
    if not re.search(r"(?<![0-9])[+]?0\.71(?![0-9])", norm_text):
        errs.append(f"{rel}: Seed 6 Caught missing SolverPolicy score '+0.71'")
    if not re.search(r"\bday\s*0?6\b|\bd0?6\b|\|\s*6\s*\|", norm_text, re.IGNORECASE):
        errs.append(f"{rel}: Seed 6 Caught missing Day 6")
    return errs


def _check_seed26_facts(rel: str, norm_text: str, require_true_mole_e08: bool) -> list[str]:
    errs: list[str] = []
    if require_true_mole_e08 and not re.search(r"\be08\b", norm_text):
        errs.append(f"{rel}: Seed 26 Fooled missing true mole 'e08'")
    if not re.search(r"\be04\b", norm_text):
        errs.append(f"{rel}: Seed 26 Fooled missing wrongly accused 'e04'")
    if not re.search(r"-1(?:\.00|\.0)?(?![0-9])", norm_text):
        errs.append(f"{rel}: Seed 26 Fooled missing Gemini wrong-accusation score '-1.00'")
    if not re.search(r"(?<![0-9])[+]?0\.69(?![0-9])", norm_text):
        errs.append(f"{rel}: Seed 26 Fooled missing SolverPolicy score '+0.69'")
    if not re.search(r"\bday\s*10\b|\bd10\b|\b10\s*\|", norm_text, re.IGNORECASE):
        errs.append(f"{rel}: Seed 26 Fooled missing Gemini accusation Day 10")
    if not re.search(r"\bday\s*0?7\b|\bd0?7\b|\|\s*7\s*\|", norm_text, re.IGNORECASE):
        errs.append(f"{rel}: Seed 26 Fooled missing SolverPolicy accusation Day 7")
    return errs


def check_demo_numeric_provenance(root: Path = ROOT) -> CheckResult:
    resolved = root.resolve()
    failures: list[str] = _verify_committed_v14_ground_truth(resolved)
    audited_surfaces: list[str] = []

    docs_demo_path = resolved / "docs" / "DEMO.md"
    if not docs_demo_path.is_file():
        failures.append("missing required docs/DEMO.md")
    else:
        audited_surfaces.append("docs/DEMO.md")
        raw_docs_demo = docs_demo_path.read_text(encoding="utf-8", errors="replace")
        norm_docs_demo = _normalize_numeric_text(raw_docs_demo)
        failures.extend(
            _check_headline_and_lock_in_doc("docs/DEMO.md", norm_docs_demo, require_means=False)
        )
        if re.search(r"\bseed\s+6\b", norm_docs_demo, re.IGNORECASE):
            failures.extend(_check_seed6_facts("docs/DEMO.md", norm_docs_demo))
        if re.search(r"\bseed\s+26\b", norm_docs_demo, re.IGNORECASE):
            failures.extend(
                _check_seed26_facts(
                    "docs/DEMO.md",
                    norm_docs_demo,
                    require_true_mole_e08=False,
                )
            )
        else:
            failures.append("docs/DEMO.md: missing Seed 26 Fooled replay provenance")
        if re.search(r"--seed\s+4\b|\bdev\s+seed\s+4\b", norm_docs_demo, re.IGNORECASE):
            if not (
                re.search(r"\be11\b", norm_docs_demo)
                and re.search(r"(?<![0-9])[+]?0\.73(?![0-9])", norm_docs_demo)
                and re.search(r"(?<![0-9])[+]?0\.40(?![0-9])", norm_docs_demo)
            ):
                failures.append("docs/DEMO.md: Seed 4 replay numbers drifted from e11 / +0.73 / +0.40")

    root_demo_path = resolved / "DEMO.md"
    if root_demo_path.is_file():
        audited_surfaces.append("DEMO.md")
        raw_root_demo = root_demo_path.read_text(encoding="utf-8", errors="replace")
        norm_root_demo = _normalize_numeric_text(raw_root_demo)
        failures.extend(
            _check_headline_and_lock_in_doc("DEMO.md", norm_root_demo, require_means=True)
        )
        if not re.search(r"\bseed\s*6\b", norm_root_demo, re.IGNORECASE):
            failures.append("DEMO.md: missing Seed 6 Caught walkthrough")
        else:
            failures.extend(_check_seed6_facts("DEMO.md", norm_root_demo))
        if not re.search(r"\bseed\s*26\b", norm_root_demo, re.IGNORECASE):
            failures.append("DEMO.md: missing Seed 26 Fooled walkthrough")
        else:
            failures.extend(
                _check_seed26_facts("DEMO.md", norm_root_demo, require_true_mole_e08=True)
            )

    replay_html_path = resolved / "docs" / "demo" / "replay.html"
    if replay_html_path.is_file():
        audited_surfaces.append("docs/demo/replay.html")
        raw_replay = replay_html_path.read_text(encoding="utf-8", errors="replace")
        norm_replay = _normalize_numeric_text(raw_replay)
        failures.extend(_check_seed6_facts("docs/demo/replay.html", norm_replay))
        failures.extend(
            _check_seed26_facts(
                "docs/demo/replay.html",
                norm_replay,
                require_true_mole_e08=True,
            )
        )
        if UNAPPROVED_FLASH_GAP_RX.search(norm_replay):
            failures.append("docs/demo/replay.html: unapproved gemini-3.5-flash gap claim")
        for lineno, line in enumerate(norm_replay.splitlines(), 1):
            stripped_q = INTERROGATIVE_PREREG_029_RX.sub("", line)
            if BAD_PREREG_029_RX.search(stripped_q) and not POSTHOC_LOCK_RX.search(stripped_q):
                failures.append(
                    f"docs/demo/replay.html:{lineno}: false pre-registration claim on dev seeds 0-29"
                )
        if re.search(r"\[\s*\d+%\s*,\s*\d+%\s*\]", norm_replay):
            if "65%" in norm_replay and not RAW_HEADLINE_CI_RX.search(norm_replay):
                failures.append(
                    "docs/demo/replay.html: raw headline CI drifted from '65% [24%, 98%]'"
                )
            if "72%" in norm_replay and not LA_HEADLINE_CI_RX.search(norm_replay):
                failures.append(
                    "docs/demo/replay.html: luck-adjusted headline CI drifted from '72% [52%, 91%]'"
                )

    if failures:
        return CheckResult(
            CHECK_NUMERIC_PROVENANCE,
            "FAIL",
            f"{len(failures)} numeric provenance failure(s) across {len(audited_surfaces)} surface(s)",
            failures,
        )
    return CheckResult(
        CHECK_NUMERIC_PROVENANCE,
        "PASS",
        f"headline (65% [24%, 98%] raw, 72% [52%, 91%] luck-adj, n=30 0-29) & seed replays verified across {', '.join(audited_surfaces)}",
    )


def check_living_office_honesty(root: Path = ROOT) -> CheckResult:
    resolved = root.resolve()
    failures: list[str] = []

    if (resolved / "canary" / "rules.py").is_file():
        try:
            from canary import rules

            v14_hash = _compute_tier_hash(rules.TIERS, rules.KNOWN_V_MODE)
            if rules.TIERS_VERSION != EXPECTED_TIERS_VERSION:
                failures.append(
                    f"canary.rules.TIERS_VERSION expected {EXPECTED_TIERS_VERSION!r}, got {rules.TIERS_VERSION!r}"
                )
            if v14_hash != EXPECTED_V14_HASH:
                failures.append(
                    f"frozen v1.4 tier hash expected {EXPECTED_V14_HASH}, got {v14_hash}"
                )
        except Exception as exc:
            failures.append(f"failed verifying frozen v1.4 hash ({type(exc).__name__}: {exc})")

    candidates: tuple[tuple[str, bool], ...] = (
        ("docs/DEMO.md", True),
        ("DEMO.md", True),
        ("docs/demo/replay.html", True),
        ("docs/demo/living_office_v16.html", True),
        ("docs/arena/index.html", False),
    )

    checked_v16_surfaces: list[str] = []
    for rel, require_gate_b in candidates:
        fp = resolved / rel
        if not fp.is_file():
            continue
        text = fp.read_text(encoding="utf-8", errors="replace")
        norm = _normalize_numeric_text(text)

        for m in V16_REPLACED_V14_RX.finditer(norm):
            failures.append(
                f"{rel}: dishonest claim that v1.6 replaced or superseded frozen v1.4 ({EXPECTED_V14_HASH}): '{m.group(0).strip()}'"
            )
        for m in V16_PASSED_GATE_B_RX.finditer(norm):
            failures.append(
                f"{rel}: dishonest claim that v1.6 passed Gate B: '{m.group(0).strip()}'"
            )

        is_v16_surface = rel == "docs/demo/living_office_v16.html" or bool(
            V16_CITATION_RX.search(norm)
        )
        if not is_v16_surface:
            continue

        checked_v16_surfaces.append(rel)
        if not OFF_BY_DEFAULT_RX.search(norm):
            failures.append(
                f"{rel}: cites Living Office / v1.6 without explicit 'off-by-default' / 'off by default' disclosure"
            )
        if require_gate_b:
            if not (GATE_B_RX.search(norm) and GATE_B_NEGATIVE_RX.search(norm)):
                failures.append(
                    f"{rel}: cites Living Office / v1.6 without explicit Gate-B-not-passed disclosure"
                )
        if rel in {"docs/demo/living_office_v16.html", "docs/arena/index.html"}:
            if "v1.4" not in norm:
                failures.append(
                    f"{rel}: Living Office preview must explicitly preserve frozen v1.4 as default benchmark"
                )

    if failures:
        return CheckResult(
            CHECK_LIVING_OFFICE_HONESTY,
            "FAIL",
            f"{len(failures)} Living Office v1.6 honesty violation(s)",
            failures,
        )

    if checked_v16_surfaces:
        summary = (
            f"off-by-default & Gate-B-not-passed disclosures verified across {', '.join(checked_v16_surfaces)}; "
            f"frozen v1.4 ({EXPECTED_V14_HASH}) preserved"
        )
    else:
        summary = f"0 Living Office v1.6 replacement claims; frozen v1.4 ({EXPECTED_V14_HASH}) preserved"
    return CheckResult(CHECK_LIVING_OFFICE_HONESTY, "PASS", summary)


def _audit_html_offline_deps(rel: str, html_text: str, allow_optional_pyodide_cdn: bool) -> list[str]:
    errs: list[str] = []

    for tag_match in HTML_SCRIPT_TAG_RX.finditer(html_text):
        tag = tag_match.group(0)
        src = _attr_val(HTML_SRC_ATTR_RX.search(tag))
        if not src or not _is_external_http_url(src):
            continue
        if allow_optional_pyodide_cdn and ALLOWED_ARENA_PYODIDE_SRC_RX.match(src):
            tag_low = tag.lower()
            if "async" in tag_low or "defer" in tag_low:
                continue
        errs.append(f"{rel}: external script dependency '{src}' breaks offline file:// execution")

    for tag_match in HTML_LINK_TAG_RX.finditer(html_text):
        tag = tag_match.group(0)
        href = _attr_val(HTML_HREF_ATTR_RX.search(tag))
        if not href or not _is_external_http_url(href):
            continue
        rel_val = _attr_val(HTML_REL_ATTR_RX.search(tag)).lower()
        if not rel_val or any(
            tok in rel_val
            for tok in ("stylesheet", "preload", "modulepreload", "icon", "manifest", "import")
        ):
            errs.append(
                f"{rel}: external link/stylesheet dependency '{href}' breaks offline file:// execution"
            )

    for tag_match in HTML_MEDIA_TAG_RX.finditer(html_text):
        tag = tag_match.group(0)
        src = _attr_val(HTML_SRC_ATTR_RX.search(tag))
        if src and _is_external_http_url(src):
            errs.append(f"{rel}: external media asset '{src}' breaks offline file:// execution")

    if CSS_EXTERNAL_IMPORT_RX.search(html_text):
        errs.append(f"{rel}: external CSS @import breaks offline file:// execution")
    if CSS_EXTERNAL_URL_RX.search(html_text):
        errs.append(f"{rel}: external CSS url(...) asset breaks offline file:// execution")
    if JS_EXTERNAL_FETCH_RX.search(html_text):
        errs.append(f"{rel}: external http(s) fetch(...) call forbidden in offline demo HTML")
    if JS_EXTERNAL_IMPORT_RX.search(html_text):
        errs.append(f"{rel}: external http(s) ES module import forbidden in offline demo HTML")
    if JS_EXTERNAL_XHR_WS_RX.search(html_text):
        errs.append(f"{rel}: external XMLHttpRequest/WebSocket call forbidden in offline demo HTML")
    if LIVE_LLM_ENDPOINT_RX.search(html_text):
        errs.append(f"{rel}: live LLM API endpoint reference forbidden in offline demo HTML")

    return errs


def _iter_bmff_boxes(buf: bytes, start: int = 0, end: int | None = None) -> tuple[list[tuple[bytes, int, int]], str | None]:
    limit = len(buf) if end is None else min(len(buf), end)
    pos = start
    boxes: list[tuple[bytes, int, int]] = []
    while pos < limit:
        if pos + 8 > limit:
            return boxes, f"truncated ISO BMFF box header at byte {pos}"
        size32, box_type = struct.unpack(">I4s", buf[pos : pos + 8])
        header_len = 8
        if size32 == 1:
            if pos + 16 > limit:
                return boxes, f"truncated 64-bit ISO BMFF box header at byte {pos}"
            (box_size,) = struct.unpack(">Q", buf[pos + 8 : pos + 16])
            header_len = 16
        elif size32 == 0:
            box_size = limit - pos
        else:
            box_size = size32
        if box_size < header_len or pos + box_size > limit:
            return boxes, f"invalid ISO BMFF box size {box_size} at byte {pos}"
        payload_start = pos + header_len
        payload_end = pos + box_size
        boxes.append((box_type, payload_start, payload_end))
        pos = payload_end
    return boxes, None


def _contains_avc_atom(buf: bytes, start: int, end: int) -> bool:
    boxes, err = _iter_bmff_boxes(buf, start, end)
    if err is not None:
        return False
    for box_type, p_start, p_end in boxes:
        if box_type in AVC_CODEC_TAGS:
            return True
        if box_type in MP4_CONTAINER_ATOMS:
            if _contains_avc_atom(buf, p_start, p_end):
                return True
        elif box_type == b"stsd" and p_end - p_start >= 8:
            if _contains_avc_atom(buf, p_start + 8, p_end):
                return True
    return False


def _audit_mp4_file(rel: str, mp4_path: Path) -> list[str]:
    errs: list[str] = []
    try:
        size = mp4_path.stat().st_size
    except OSError as exc:
        return [f"{rel}: unreadable MP4 ({type(exc).__name__})"]

    if size <= 0:
        return [f"{rel}: MP4 file is empty (0 bytes)"]
    if size >= MAX_MP4_BYTES:
        mb = size / (1024 * 1024)
        errs.append(f"{rel}: MP4 size {mb:.2f} MiB ({size} bytes) exceeds 15 MiB budget")
        return errs

    try:
        data = mp4_path.read_bytes()
    except OSError as exc:
        return [f"{rel}: failed reading MP4 bytes ({type(exc).__name__})"]

    top_boxes, box_err = _iter_bmff_boxes(data, 0, len(data))
    if box_err is not None or not top_boxes:
        return [f"{rel}: invalid MP4 / ISO BMFF container ({box_err or 'no boxes'})"]

    if top_boxes[0][0] != b"ftyp":
        errs.append(f"{rel}: first ISO BMFF atom must be 'ftyp', got {top_boxes[0][0]!r}")

    moov_ranges = [(s, e) for t, s, e in top_boxes if t == b"moov"]
    mdat_ranges = [(s, e) for t, s, e in top_boxes if t == b"mdat" and e > s]

    if not moov_ranges:
        errs.append(f"{rel}: missing 'moov' metadata atom")
    if not mdat_ranges:
        errs.append(f"{rel}: missing non-empty 'mdat' media payload atom")

    if moov_ranges:
        has_avc = any(
            _contains_avc_atom(data, ms, me)
            or any(tag in data[ms:me] for tag in AVC_CODEC_TAGS)
            for ms, me in moov_ranges
        )
        if not has_avc:
            errs.append(f"{rel}: missing H.264/AVC ('avc1'/'h264') codec atom inside 'moov'")

    return errs


def _audit_protected_paths(root: Path, base_ref: str | None = None) -> list[str]:
    dot_git = root / ".git"
    if not (dot_git.exists() or dot_git.is_symlink()):
        return []

    env = _git_env(root)
    touched: set[str] = set()

    for cmd in (
        ["git", "diff", "-z", "--name-status"],
        ["git", "diff", "-z", "--cached", "--name-status"],
    ):
        try:
            proc = subprocess.run(cmd, cwd=root, env=env, capture_output=True, timeout=15)
        except (OSError, subprocess.SubprocessError):
            proc = None
        if proc is not None and proc.returncode == 0:
            touched.update(_parse_name_status_z(proc.stdout))

    try:
        untracked = subprocess.run(
            ["git", "ls-files", "-z", "--others", "--exclude-standard"],
            cwd=root,
            env=env,
            capture_output=True,
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError):
        untracked = None
    if untracked is not None and untracked.returncode == 0:
        for rel in untracked.stdout.decode("utf-8", errors="replace").split("\0"):
            if rel:
                touched.add(rel)

    effective_base = base_ref or DEFAULT_BASE
    try:
        verify_proc = subprocess.run(
            ["git", "rev-parse", "--verify", "--quiet", f"{effective_base}^{{commit}}"],
            cwd=root,
            env=env,
            capture_output=True,
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError):
        verify_proc = None

    if verify_proc is not None and verify_proc.returncode == 0:
        try:
            diff_base = subprocess.run(
                ["git", "diff", "-z", "--name-status", f"{effective_base}...HEAD"],
                cwd=root,
                env=env,
                capture_output=True,
                timeout=15,
            )
        except (OSError, subprocess.SubprocessError):
            diff_base = None
        if diff_base is not None and diff_base.returncode == 0:
            touched.update(_parse_name_status_z(diff_base.stdout))
    elif base_ref is not None:
        return [f"protected-paths base ref '{base_ref}' not found"]

    return [
        f"protected path modified: {rel}"
        for rel in sorted(touched)
        if _is_silas_protected(rel)
    ]


def check_demo_offline_assets_and_hygiene(
    root: Path = ROOT,
    *,
    base_ref: str | None = None,
) -> CheckResult:
    resolved = root.resolve()
    failures: list[str] = []
    audited_html = 0
    audited_mp4 = False

    demo_dir = resolved / "docs" / "demo"
    strict_html_paths: list[Path] = []
    if demo_dir.is_dir():
        strict_html_paths.extend(sorted(p for p in demo_dir.glob("*.html") if p.is_file()))

    for html_fp in strict_html_paths:
        rel = html_fp.relative_to(resolved).as_posix()
        audited_html += 1
        html_text = html_fp.read_text(encoding="utf-8", errors="replace")
        failures.extend(_audit_html_offline_deps(rel, html_text, allow_optional_pyodide_cdn=False))

    arena_index = resolved / "docs" / "arena" / "index.html"
    if arena_index.is_file():
        audited_html += 1
        arena_text = arena_index.read_text(encoding="utf-8", errors="replace")
        failures.extend(
            _audit_html_offline_deps(
                "docs/arena/index.html",
                arena_text,
                allow_optional_pyodide_cdn=True,
            )
        )

    mp4_path = resolved / "docs" / "demo" / "canary_demo.mp4"
    if mp4_path.exists():
        audited_mp4 = True
        failures.extend(_audit_mp4_file("docs/demo/canary_demo.mp4", mp4_path))

    em_dash_targets: list[Path] = []
    for rel_cand in ("docs/DEMO.md", "DEMO.md", "docs/arena/index.html"):
        cand = resolved / rel_cand
        if cand.is_file():
            em_dash_targets.append(cand)
    em_dash_targets.extend(strict_html_paths)

    for fp in em_dash_targets:
        rel = fp.relative_to(resolved).as_posix()
        txt = fp.read_text(encoding="utf-8", errors="replace")
        legacy_exempt_used = False
        for lineno, line in enumerate(txt.splitlines(), 1):
            if EM_DASH not in line:
                continue
            if (
                rel == "docs/DEMO.md"
                and not legacy_exempt_used
                and line.strip() == LEGACY_DOCS_DEMO_EM_DASH_LINE
            ):
                legacy_exempt_used = True
                continue
            failures.append(f"{rel}:{lineno}: forbidden em dash (U+2014) in demo surface")

    secret_scan_files: list[Path] = list(em_dash_targets)
    if demo_dir.is_dir():
        for extra in sorted(demo_dir.rglob("*")):
            if extra.is_file() and extra.suffix.lower() in {".js", ".json", ".md", ".css"}:
                secret_scan_files.append(extra)
    arena_dir = resolved / "docs" / "arena"
    if arena_dir.is_dir():
        for extra in sorted(arena_dir.rglob("*")):
            if extra.is_file() and extra.suffix.lower() in {".js", ".json", ".md", ".css", ".html"}:
                if extra not in secret_scan_files:
                    secret_scan_files.append(extra)

    for fp in secret_scan_files:
        rel = fp.relative_to(resolved).as_posix()
        try:
            raw = fp.read_bytes()
        except OSError:
            continue
        if b"\x00" in raw:
            continue
        txt = raw.decode("utf-8", errors="replace")
        for kind, rx in API_KEY_PATTERNS:
            for match in rx.finditer(txt):
                tok = match.group(0)
                failures.append(f"{rel}: leaked API key / secret ({kind}: {tok[:6]}...)")

    for root_entry in sorted(resolved.iterdir()) if resolved.is_dir() else []:
        if not root_entry.is_file():
            continue
        nm = root_entry.name
        if nm == ".env" or (nm.startswith(".env.") and nm not in ALLOWED_ENV_TEMPLATES):
            failures.append(f"forbidden env file in repo root: {nm}")
        if nm == "SALT":
            failures.append("forbidden SALT file in repo root")

    failures.extend(_audit_protected_paths(resolved, base_ref=base_ref))

    if failures:
        return CheckResult(
            CHECK_OFFLINE_ASSETS_HYGIENE,
            "FAIL",
            f"{len(failures)} offline/asset/hygiene violation(s)",
            failures,
        )

    mp4_note = "MP4 verified (<15 MiB, avc1)" if audited_mp4 else "MP4 optional (absent)"
    return CheckResult(
        CHECK_OFFLINE_ASSETS_HYGIENE,
        "PASS",
        f"{audited_html} HTML surface(s) offline-clean, {mp4_note}, 0 em dashes, 0 API keys, 0 protected paths",
    )


def verify_repo(root: Path = ROOT, *, base_ref: str | None = None) -> list[CheckResult]:
    resolved = root.resolve()
    return [
        check_demo_numeric_provenance(resolved),
        check_living_office_honesty(resolved),
        check_demo_offline_assets_and_hygiene(resolved, base_ref=base_ref),
    ]


def audit_repo(root: Path = ROOT, *, base_ref: str | None = None) -> list[CheckResult]:
    return verify_repo(root=root, base_ref=base_ref)


def format_report(results: Sequence[CheckResult], elapsed_s: float) -> str:
    lines: list[str] = []
    counts = {"PASS": 0, "WARN": 0, "FAIL": 0}
    for r in results:
        counts[r.status] = counts.get(r.status, 0) + 1
        lines.append(f"[{r.status}] {r.name}: {r.summary}")
        for detail in r.details:
            lines.append(f"       - {detail}")
    lines.append(
        f"SUMMARY: {counts['PASS']} PASS, {counts['WARN']} WARN, {counts['FAIL']} FAIL ({elapsed_s:.2f}s)"
    )
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Keyless read-only verifier for Canary 09:00 and stage demo deliverables."
    )
    ap.add_argument("--root", type=Path, default=ROOT, help="Repository root to audit")
    ap.add_argument("--base", type=str, default=None, help="Optional git base ref for protected-path diff")
    ap.add_argument("--json", action="store_true", help="Emit JSON report")
    args = ap.parse_args(argv)

    t0 = time.monotonic()
    results = audit_repo(root=args.root.resolve(), base_ref=args.base)
    elapsed = time.monotonic() - t0
    passed = not any(r.status == "FAIL" for r in results)

    if args.json:
        items = [asdict(r) for r in results]
        payload = {
            "results": items,
            "checks": items,
            "elapsed_s": round(elapsed, 4),
            "passed": passed,
        }
        print(json.dumps(payload, indent=2))
    else:
        print(format_report(results, elapsed))

    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
