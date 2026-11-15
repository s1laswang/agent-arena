from __future__ import annotations

import hashlib
import json
import re
import sys
import tempfile
from pathlib import Path
from typing import Any
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import scripts.verify_doc_commands as verify_doc_commands

QUICKSTART_REL = "JUDGE_QUICKSTART.md"
QUICKSTART_PATH = ROOT / QUICKSTART_REL
HASH_CHAR = chr(35)
EM_DASH = chr(0x2014)
EN_DASH = chr(0x2013)
FENCE_OPEN_RX = re.compile(r"^\s*(?:>\s*)*(`{3,}|~{3,})")
INLINE_CODE_RX = re.compile(r"(`+)(?:(?!\1)[^\n])+\1")
MD_LINK_RX = re.compile(r"!?\[(?:[^\[\]\n]|\[[^\[\]\n]*\])*\]\(([^)\n]+)\)")


def _strip_code_preserving_lines(md_text: str) -> list[str]:
    out: list[str] = []
    in_fence = False
    fence_char = ""
    fence_len = 0
    for raw_line in md_text.splitlines():
        m = FENCE_OPEN_RX.match(raw_line)
        if not in_fence:
            if m:
                marker = m.group(1)
                in_fence = True
                fence_char = marker[0]
                fence_len = len(marker)
                out.append("")
                continue
            out.append(INLINE_CODE_RX.sub("", raw_line))
        else:
            if m:
                marker = m.group(1)
                if marker[0] == fence_char and len(marker) >= fence_len:
                    in_fence = False
                    fence_char = ""
                    fence_len = 0
            out.append("")
    return out


def _extract_relative_links(md_path: Path) -> tuple[list[str], list[str]]:
    root_resolved = md_path.parent.resolve()
    text = md_path.read_text(encoding="utf-8")
    resolved_rels: list[str] = []
    broken: list[str] = []
    for lineno, line in enumerate(_strip_code_preserving_lines(text), 1):
        for match in MD_LINK_RX.finditer(line):
            raw = match.group(1).strip()
            if not raw:
                continue
            target = raw[1 : raw.index(">")].strip() if (raw.startswith("<") and ">" in raw) else raw.split()[0].strip()
            if not target:
                continue
            lower = target.lower()
            if lower.startswith(("http://", "https://", "mailto:")) or target.startswith(HASH_CHAR):
                continue
            path_part = unquote(target.split(HASH_CHAR, 1)[0]).strip()
            if not path_part:
                continue
            resolved = (md_path.parent / path_part).resolve()
            try:
                rel_target = resolved.relative_to(root_resolved).as_posix()
            except ValueError:
                broken.append(f"{lineno}: {target} resolves outside repo root")
                continue
            if not resolved.exists():
                broken.append(f"{lineno}: {target} -> missing {rel_target}")
                continue
            resolved_rels.append(rel_target)
    return resolved_rels, broken


def _pct(val: Any) -> str:
    return f"{float(val) * 100.0:.0f}%"


def _has_token(text: str, tok: str) -> bool:
    pattern = r"(?<![0-9])(?<!\d\.)" + re.escape(tok) + r"(?![0-9])(?!\.\d)"
    return re.search(pattern, text) is not None


def _find_paired_row(
    rows: list[dict[str, Any]],
    group: str,
    tier: str,
    agent: str | None = None,
) -> dict[str, Any]:
    for row in rows:
        if row.get("group") != group or row.get("tier") != tier:
            continue
        if agent is not None and row.get("agent") != agent:
            continue
        label_lower = str(row.get("label", "")).lower()
        if "alternative" in label_lower or "not the headline" in label_lower:
            continue
        return row
    raise AssertionError(f"missing row for group={group} tier={tier} agent={agent}")


def test_judge_quickstart_exists_line_limit_and_ascii() -> None:
    assert QUICKSTART_PATH.is_file(), f"missing {QUICKSTART_PATH}"
    text = QUICKSTART_PATH.read_text(encoding="utf-8")
    lines = text.splitlines()
    assert 10 <= len(lines) <= 95, f"expected <= 95 lines (and <= 100), got {len(lines)}"
    assert EM_DASH not in text, "em dash found in JUDGE_QUICKSTART.md"
    assert EN_DASH not in text, "en dash found in JUDGE_QUICKSTART.md"
    non_ascii = [f"line {i}: {ch!r}" for i, ln in enumerate(lines, 1) for ch in ln if ord(ch) >= 128]
    assert not non_ascii, f"non-ASCII characters found: {non_ascii[:5]}"

    test_src = Path(__file__).read_text(encoding="utf-8")
    assert HASH_CHAR not in test_src
    assert EM_DASH not in test_src
    assert EN_DASH not in test_src


def test_judge_quickstart_markdown_links() -> None:
    resolved_rels, broken = _extract_relative_links(QUICKSTART_PATH)
    assert not broken, f"broken relative markdown links: {broken}"
    required_targets = {
        "docs/JUDGE-WALKTHROUGH.md",
        "docs/reports/gap.md",
        "docs/reports/failure_analysis_v1.4.md",
        "docs/reports/failure_gallery.md",
        "docs/DIFFICULTY.md",
        "docs/EXPLOITS.md",
        "results/gemini/swarm.md",
        "docs/gemini/SUBMISSION.md",
        "results/harbor/rehearsal/README.md",
    }
    missing_targets = sorted(required_targets - set(resolved_rels))
    assert not missing_targets, f"missing required links in JUDGE_QUICKSTART.md: {missing_targets}"


def test_judge_quickstart_passes_doc_commands_verifier() -> None:
    results = verify_doc_commands.verify_repo(root=ROOT, docs=(QUICKSTART_REL,))
    assert len(results) >= 3
    failures = [f"{r.name}: {r.status} ({r.details})" for r in results if r.status != "PASS"]
    assert not failures, f"verify_doc_commands failed on {QUICKSTART_REL}: {failures}"

    text = QUICKSTART_PATH.read_text(encoding="utf-8")
    required_snippets = (
        "make setup && make reproduce",
        "make accept",
        "uv run python scripts/paired_gemini.py --version v1.4 --seeds 0-29",
        "uv run python scripts/demo_replay.py --seed 4 --verify",
        "uv run python scripts/failure_analysis_v14.py --check",
        "make anticheat-verify",
        "make game-serve",
        "uv tool install harbor && uv run python harbor/build.py",
        "harbor run -p harbor/dataset -a oracle -n 4",
        "ORACLE_POLICY=do_nothing",
        "ORACLE_POLICY=stop_early",
        "ORACLE_POLICY=cheat_probe",
        "--api-key-name GOOGLE_GENERATIVE_AI_API_KEY",
        "--agent-setup-timeout-multiplier 3",
    )
    for snippet in required_snippets:
        assert snippet in text, f"missing command snippet: {snippet}"


def test_judge_quickstart_matches_committed_json_numbers() -> None:
    from canary import rules

    text = QUICKSTART_PATH.read_text(encoding="utf-8")
    paired_rows = json.loads((ROOT / "data" / "runs" / "committed" / "v1.4" / "paired_table_gemini.json").read_text(encoding="utf-8"))
    oracle_data = json.loads((ROOT / "results" / "oracle_range_v1.4.json").read_text(encoding="utf-8"))
    gd1_data = json.loads((ROOT / "results" / "solver_range" / "guess_day1_hard_judge40.json").read_text(encoding="utf-8"))

    tier_obj = {"tiers": {k: v.to_dict() for k, v in rules.TIERS.items()}, "known_v_mode": rules.KNOWN_V_MODE}
    tier_hash = hashlib.sha256(json.dumps(tier_obj, sort_keys=True, default=list).encode()).hexdigest()[:16]
    assert f'TIERS_VERSION="{rules.TIERS_VERSION}"' in text
    assert tier_hash in text

    oc_hard = _find_paired_row(paired_rows, "v1.4/opencode-gemini-4-carbon", "hard")
    oc_med = _find_paired_row(paired_rows, "v1.4/opencode-gemini-4-carbon", "medium")
    ip_hard = _find_paired_row(paired_rows, "v1.4/inproc-gemini-4-carbon", "hard")
    sv_hard = _find_paired_row(paired_rows, "v1.4/reference", "hard", agent="solver")
    sv_med = _find_paired_row(paired_rows, "v1.4/reference", "medium", agent="solver")

    oracle_solver_hard = next(
        r for r in oracle_data["rows"] if r.get("agent") == "solver" and r.get("tier") == "hard"
    )
    k10 = oracle_solver_hard["k10"]

    for baseline_agent in ("do_nothing", "stop_early"):
        b_row = next(
            r for r in oracle_data["rows"] if r.get("agent") == baseline_agent and r.get("tier") == "hard"
        )
        assert float(b_row["k10"]["mean"]) == 0.0

    expected_tokens = [
        f"n={int(oc_hard['n'])}",
        f"{float(oc_hard['mean']):+.3f} +/- {float(oc_hard['ci']):.3f}",
        f"{float(oc_hard['solver_same_seeds']):+.3f} +/- {float(sv_hard['ci']):.3f}",
        f"{_pct(oc_hard['ratio'])} [{_pct(oc_hard['ratio_lo'])}, {_pct(oc_hard['ratio_hi'])}]",
        f"{_pct(oc_hard['post_expected_ratio'])} [{_pct(oc_hard['post_expected_lo'])}, {_pct(oc_hard['post_expected_hi'])}]",
        f"{float(oc_hard['post_expected']):+.3f}",
        f"{float(ip_hard['mean']):+.3f} +/- {float(ip_hard['ci']):.3f}",
        f"{_pct(ip_hard['ratio'])} [{_pct(ip_hard['ratio_lo'])}, {_pct(ip_hard['ratio_hi'])}]",
        f"{float(oc_med['mean']):+.3f} +/- {float(oc_med['ci']):.3f}",
        f"{float(oc_med['solver_same_seeds']):+.3f} +/- {float(sv_med['ci']):.3f}",
        f"{_pct(oc_med['ratio'])} [{_pct(oc_med['ratio_lo'])}, {_pct(oc_med['ratio_hi'])}]",
        f"{float(k10['p5']):+.2f}",
        f"{float(k10['p95']):+.2f}",
        f"{float(k10['mean']):+.3f}",
        f"{float(k10['sd']):.3f}",
        f"-{abs(float(gd1_data['mean'])):.2f}",
        "+0.000",
        "295 episodes",
        "0.0e+00",
        "91 finished attackers",
        "4,325 calls",
        "0 exploits",
    ]
    missing = [tok for tok in expected_tokens if not _has_token(text, tok)]
    assert not missing, f"JUDGE_QUICKSTART.md missing expected JSON-backed tokens: {missing}"

    gap_text = (ROOT / "docs" / "reports" / "gap.md").read_text(encoding="utf-8")
    if "gemini-3.5-flash" not in gap_text:
        walkthrough_text = (ROOT / "docs" / "JUDGE-WALKTHROUGH.md").read_text(encoding="utf-8")
        for doc_name, doc_body in (
            ("JUDGE_QUICKSTART.md", text),
            ("docs/JUDGE-WALKTHROUGH.md", walkthrough_text),
        ):
            for unapproved_tok in ("75% [36%, 123%]", "22% [-23%, 63%]", "+0.373"):
                assert unapproved_tok not in doc_body, f"{doc_name} quotes {unapproved_tok} before gap.md"


def test_link_and_token_helpers_detect_regressions() -> None:
    tmp_root = Path("/tmp/opencode")
    tmp_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=str(tmp_root), prefix="quickstart-test-") as tmp_str:
        base = Path(tmp_str)
        (base / "docs").mkdir()
        (base / "docs" / "ok.md").write_text("ok\n", encoding="utf-8")
        sample = base / "JUDGE_QUICKSTART.md"
        sample.write_text(
            "\n".join(
                [
                    f"Good [ok](docs/ok.md{HASH_CHAR}sec) and [ext](https://example.com) and [self]({HASH_CHAR}top).",
                    "Inline `[ignored](docs/missing_inline.md)` is skipped.",
                    "```markdown",
                    "[fenced](docs/missing_fenced.md)",
                    "```",
                    "Broken [bad](docs/missing.md) and [escape](../outside.md).",
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        resolved_rels, broken = _extract_relative_links(sample)
        assert resolved_rels == ["docs/ok.md"]
        assert len(broken) == 2
        assert any("docs/missing.md" in item for item in broken)
        assert any("outside repo root" in item for item in broken)

    assert _has_token("score +0.322 +/- 0.199", "+0.322 +/- 0.199")
    assert not _has_token("score +0.3225 +/- 0.199", "+0.322")
    assert not _has_token("score 165%", "65%")

