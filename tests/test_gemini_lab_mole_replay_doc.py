from __future__ import annotations

import io
from pathlib import Path
import re
from statistics import mean
import sys
import tokenize

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from canary.gemini import mole_replay_audit as mra

DOC_PATH = ROOT / "docs" / "gemini" / "roles_carbon" / "adaptive_mole_replay.md"
AUDIT_MOD_PATH = ROOT / "canary" / "gemini" / "mole_replay_audit.py"
AUDIT_TEST_PATH = ROOT / "tests" / "test_gemini_lab_mole_replay_audit.py"
SELF_TEST_PATH = Path(__file__).resolve()

HASH = chr(0x23)
FORBIDDEN_DASHES: tuple[str, ...] = tuple(chr(c) for c in (*range(0x2010, 0x2016), 0x2212))
ESCAPED_DASH_TOKENS: tuple[str, ...] = tuple(
    "\\" + f"u{code:04x}" for code in (*range(0x2010, 0x2016), 0x2212)
)

EXPECTED_SCOPE = "arena mode, not the judged v1.4 environment"
TODO_TBD_RE = re.compile(r"\b(?:TODO|TBD|DRAFT)\b", re.IGNORECASE)
ANGLE_PLACEHOLDER_RE = re.compile(chr(0x3C) + r"[A-Za-z0-9_.\-/ ]+" + chr(0x3E))
DOC_RUN_PATH_RE = re.compile(
    r"(?<![A-Za-z0-9_.\-/])(results/gemini/roles_carbon/[A-Za-z0-9_.\-/]+)"
)
SECRET_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?<![0-9A-Za-z+/_-])" + "AI" + "za" + r"[0-9A-Za-z_-]{16,}"),
    re.compile(r"(?<![0-9A-Za-z+/_-])" + "s" + "k-" + r"(?:proj-|ant-|live-|test-|svcacct-)?[0-9A-Za-z_-]{12,}"),
    re.compile(r"(?<![0-9A-Za-z_])" + "ya" + r"29\.[0-9A-Za-z_-]{12,}"),
    re.compile(
        r"\b(?:GEMINI_API_KEY|GOOGLE_API_KEY|GOOGLE_GENERATIVE_AI_API_KEY|CANARY_WORLD_SECRET|CANARY_LEDGER_KEY)"
        r"\s*=\s*['\"]?[0-9A-Za-z_-]{4,}"
    ),
)


@pytest.fixture(scope="module")
def keyless_replay_bundle() -> tuple[str, list[mra.StrategyRun], mra.ReplayAuditSummary]:
    mp = pytest.MonkeyPatch()
    for env_key in (
        "GEMINI_API_KEY",
        "GOOGLE_API_KEY",
        "GOOGLE_GENERATIVE_AI_API_KEY",
        "GEMINI_GATEWAY_URL",
    ):
        mp.delenv(env_key, raising=False)
    try:
        doc_text = DOC_PATH.read_text(encoding="utf-8")
        loaded_runs = mra.load_strategy_runs(mra.DEFAULT_ROLES_DIR)
        summary = mra.audit_adaptive_mole_runs(mra.DEFAULT_ROLES_DIR, seeds=mra.DEFAULT_DEV_SEEDS)
        return doc_text, loaded_runs, summary
    finally:
        mp.undo()


def _strip_ticks(cell: str) -> str:
    val = cell.strip()
    if len(val) >= 2 and val.startswith("`") and val.endswith("`"):
        return val[1:-1].strip()
    return val


def _extract_section(doc_text: str, heading_prefix: str) -> str:
    lines = doc_text.splitlines()
    start_idx: int | None = None
    heading_level = 0
    for idx, line in enumerate(lines):
        if line.startswith(heading_prefix):
            start_idx = idx + 1
            heading_level = len(line) - len(line.lstrip(HASH))
            break
    assert start_idx is not None, f"missing heading: {heading_prefix}"
    end_idx = len(lines)
    for idx in range(start_idx, len(lines)):
        stripped = lines[idx]
        if stripped.startswith(HASH):
            lvl = len(stripped) - len(stripped.lstrip(HASH))
            if lvl <= heading_level:
                end_idx = idx
                break
    return "\n".join(lines[start_idx:end_idx])


def _parse_markdown_table(section_text: str) -> list[dict[str, str]]:
    table_lines = [ln.strip() for ln in section_text.splitlines() if ln.strip().startswith("|")]
    assert len(table_lines) >= 3, "expected markdown table with header, divider, and data rows"
    headers = [c.strip() for c in table_lines[0].strip("|").split("|")]
    rows: list[dict[str, str]] = []
    for raw_line in table_lines[2:]:
        cells = [c.strip() for c in raw_line.strip("|").split("|")]
        if len(cells) != len(headers):
            break
        rows.append(dict(zip(headers, cells, strict=True)))
    assert rows, "parsed zero data rows from markdown table"
    return rows


def _extract_fenced_block(section_text: str, fence_lang: str) -> str:
    open_marker = f"```{fence_lang}"
    lines = section_text.splitlines()
    in_block = False
    collected: list[str] = []
    for line in lines:
        if not in_block:
            if line.strip() == open_marker:
                in_block = True
        else:
            if line.strip() == "```":
                return "\n".join(collected)
            collected.append(line)
    raise AssertionError(f"missing fenced block {open_marker}")


def test_replay_doc_and_test_hygiene_zero_comments_and_dashes() -> None:
    assert DOC_PATH.is_file()
    doc_text = DOC_PATH.read_text(encoding="utf-8")
    assert doc_text.strip()

    for py_path in (SELF_TEST_PATH, AUDIT_MOD_PATH, AUDIT_TEST_PATH):
        py_src = py_path.read_text(encoding="utf-8")
        assert HASH not in py_src, f"unexpected hash character in {py_path}"
        tokens = list(tokenize.generate_tokens(io.StringIO(py_src).readline))
        comment_tokens = [tok for tok in tokens if tok.type == tokenize.COMMENT]
        assert not comment_tokens, f"comment token found in {py_path}"
        for dash in FORBIDDEN_DASHES:
            assert dash not in py_src, f"forbidden dash { hex(ord(dash)) } in {py_path}"

    for dash in FORBIDDEN_DASHES:
        assert dash not in doc_text, f"forbidden dash {hex(ord(dash))} in {DOC_PATH}"
    lower_doc = doc_text.lower()
    for esc in ESCAPED_DASH_TOKENS:
        assert esc not in lower_doc, f"escaped forbidden dash {esc} in {DOC_PATH}"

    assert "results/gemini_roles/" not in doc_text
    assert TODO_TBD_RE.search(doc_text) is None
    assert ANGLE_PLACEHOLDER_RE.search(doc_text) is None
    for pat in SECRET_PATTERNS:
        assert pat.search(doc_text) is None

    cited_paths = DOC_RUN_PATH_RE.findall(doc_text)
    assert len(cited_paths) >= 15
    for rel_str in cited_paths:
        target = ROOT / rel_str.rstrip("/")
        assert target.exists(), f"cited path does not exist on disk: {rel_str}"


def test_replay_doc_scope_and_gate_disclosures(
    keyless_replay_bundle: tuple[str, list[mra.StrategyRun], mra.ReplayAuditSummary],
) -> None:
    doc_text, _, _ = keyless_replay_bundle
    scope_section = _extract_section(doc_text, f"{HASH}{HASH} Scope & Verification Gates")

    assert EXPECTED_SCOPE in scope_section
    assert "[0, 1, 2, 3, 4]" in scope_section
    assert "JUDGE_SEEDS" in scope_section
    assert "validate_dev_seeds" in scope_section
    assert "a8f99c2537c91d72" in scope_section

    for gate_name in ("deterministic_ok", "leaks_ok", "catchable_ok", "mole_view_clean_ok"):
        assert f"`{gate_name}`" in scope_section

    assert len(mra.ALLOWED_MOLE_VIEW_FIELDS) == 11
    assert len(mra.ALLOWED_MOLE_DOC_FIELDS) == 4
    assert len(mra.PRIVILEGED_FIELD_NAMES) == 20
    assert "`11`-field `MoleView` allowlist" in scope_section
    assert "`4`-field `MoleDoc` allowlist" in scope_section
    assert "`20` forbidden privileged identifiers" in scope_section


def test_replay_doc_headline_metrics_match_live_audit(
    keyless_replay_bundle: tuple[str, list[mra.StrategyRun], mra.ReplayAuditSummary],
) -> None:
    doc_text, loaded_runs, summary = keyless_replay_bundle
    headline = _extract_section(doc_text, f"{HASH}{HASH} Headline Replay & Equivalence Summary")

    assert summary.populated is True
    assert summary.all_passed is True
    assert summary.seeds == (0, 1, 2, 3, 4)
    assert summary.n_runs == 14
    assert summary.n_mole_forge_runs == 4
    assert summary.n_paired_designer_runs == 10

    episodes_per_policy = sum(len(r.episodes) for r in summary.runs)
    total_env_episodes = episodes_per_policy * 4
    solver_wins = sum(1 for r in summary.runs for ep in r.episodes if ep.solver_correct)
    obvious_wins = sum(1 for r in summary.runs for ep in r.episodes if ep.obvious_correct)
    solver_mean = mean(r.solver_mean_score for r in summary.runs)
    solver_acc = mean(r.solver_accuracy for r in summary.runs) * 100.0
    obvious_mean = mean(r.obvious_mean_score for r in summary.runs)
    obvious_acc = mean(r.obvious_accuracy for r in summary.runs) * 100.0
    margin_mean = mean(r.catchability_margin for r in summary.runs)
    solver_leaks = sum(r.total_leak_count for r in summary.runs)
    obvious_leaks = sum(r.obvious_total_leak_count for r in summary.runs)
    forge_views = sum(r.views_checked for r in summary.runs if r.source_kind == "mole_forge")
    paired_views = sum(r.views_checked for r in summary.runs if r.source_kind == "paired_designer")
    total_views = forge_views + paired_views
    total_viols = sum(len(r.privileged_field_violations) for r in summary.runs)

    forge_entries = sum(len(lr.entries) for lr in loaded_runs if lr.source_kind == "mole_forge")
    paired_entries = sum(len(lr.entries) for lr in loaded_runs if lr.source_kind == "paired_designer")
    all_eq = summary.all_strategies_equivalence
    top_eq = summary.top_strategies_equivalence

    assert episodes_per_policy == 70
    assert total_env_episodes == 280
    assert solver_wins == 68
    assert obvious_wins == 6
    assert solver_leaks == 382
    assert obvious_leaks == 360
    assert forge_views == 260
    assert paired_views == 774
    assert total_views == 1034
    assert total_viols == 0
    assert forge_entries == 57
    assert paired_entries == 49
    assert all_eq.n_strategies == 106
    assert all_eq.n_syntactic_unique == 105
    assert all_eq.n_equivalence_classes == 93
    assert all_eq.n_synthetic_views == 2163
    assert top_eq.n_strategies == 14
    assert top_eq.n_syntactic_unique == 14
    assert top_eq.n_equivalence_classes == 13

    expected_tokens = (
        "`14/14` (`100.00%`) `PASS`",
        f"`{episodes_per_policy}` unique `(run, seed)` pairs",
        f"`{total_env_episodes}` total `Env` episodes",
        f"`{solver_mean:+.4f}`",
        f"`{solver_acc:.2f}%`",
        f"(`{solver_wins}/{episodes_per_policy}`)",
        f"`{obvious_mean:+.4f}`",
        f"`{obvious_acc:.2f}%`",
        f"(`{obvious_wins}/{episodes_per_policy}`)",
        f"`{margin_mean:+.4f}`",
        f"`{solver_leaks}` solver-episode leaks",
        f"`{obvious_leaks}` heuristic-episode leaks",
        f"`{total_views:,}`",
        f"`{forge_views}` `mole_forge` + `{paired_views}` `paired_designer`",
        f"`{all_eq.n_synthetic_views:,}`",
        f"`{forge_entries}` `mole_forge` Hall-of-Fame strategies + `{paired_entries}` `paired_designer` kept strategies",
        f"`{all_eq.n_strategies}`",
        f"`{all_eq.n_syntactic_unique}`",
        f"`{all_eq.n_equivalence_classes}`",
        f"`{top_eq.n_equivalence_classes}`",
    )
    for token in expected_tokens:
        assert token in headline, f"missing headline token: {token}"


def test_replay_doc_source_kind_and_tier_slice_tables_exact_parity(
    keyless_replay_bundle: tuple[str, list[mra.StrategyRun], mra.ReplayAuditSummary],
) -> None:
    doc_text, loaded_runs, summary = keyless_replay_bundle

    kind_sec = _extract_section(doc_text, f"{HASH}{HASH}{HASH} By Source Kind")
    kind_rows = {_strip_ticks(r["Source Kind"]): r for r in _parse_markdown_table(kind_sec)}
    assert set(kind_rows.keys()) == {"mole_forge", "paired_designer", "overall"}

    for key in ("mole_forge", "paired_designer", "overall"):
        sub_rep = [r for r in summary.runs if key == "overall" or r.source_kind == key]
        sub_runs = [lr for lr in loaded_runs if key == "overall" or lr.source_kind == key]
        row = kind_rows[key]
        n_r = len(sub_rep)
        n_ent = sum(len(lr.entries) for lr in sub_runs)
        n_eps = sum(len(r.episodes) for r in sub_rep)
        s_mean = mean(r.solver_mean_score for r in sub_rep)
        s_acc = mean(r.solver_accuracy for r in sub_rep) * 100.0
        o_mean = mean(r.obvious_mean_score for r in sub_rep)
        o_acc = mean(r.obvious_accuracy for r in sub_rep) * 100.0
        m_mean = mean(r.catchability_margin for r in sub_rep)
        s_leaks = sum(r.total_leak_count for r in sub_rep)
        o_leaks = sum(r.obvious_total_leak_count for r in sub_rep)
        views = sum(r.views_checked for r in sub_rep)
        viols = sum(len(r.privileged_field_violations) for r in sub_rep)
        passed_cnt = sum(1 for r in sub_rep if r.passed)

        assert int(row["Runs"]) == n_r
        assert int(row["Loaded Entries"]) == n_ent
        assert int(row["Episodes / Policy"]) == n_eps
        assert row["Solver Mean"] == f"{s_mean:+.4f}"
        assert row["Solver Acc"] == f"{s_acc:.2f}%"
        assert row["Obvious Mean"] == f"{o_mean:+.4f}"
        assert row["Obvious Acc"] == f"{o_acc:.2f}%"
        assert row["Mean Margin"] == f"{m_mean:+.4f}"
        assert int(row["Solver Leaks"]) == s_leaks
        assert int(row["Obvious Leaks"]) == o_leaks
        assert int(row["Live Views"]) == views
        assert int(row["Violations"]) == viols
        assert row["Pass Rate"] == f"{passed_cnt}/{n_r}"

    tier_sec = _extract_section(doc_text, f"{HASH}{HASH}{HASH} By Difficulty Tier")
    tier_rows = {_strip_ticks(r["Tier"]): r for r in _parse_markdown_table(tier_sec)}
    assert set(tier_rows.keys()) == {"easy", "medium", "hard", "overall"}

    for key in ("easy", "medium", "hard", "overall"):
        sub_rep = [r for r in summary.runs if key == "overall" or r.tier == key]
        sub_runs = [lr for lr in loaded_runs if key == "overall" or lr.tier == key]
        row = tier_rows[key]
        n_r = len(sub_rep)
        n_ent = sum(len(lr.entries) for lr in sub_runs)
        n_eps = sum(len(r.episodes) for r in sub_rep)
        s_mean = mean(r.solver_mean_score for r in sub_rep)
        s_acc = mean(r.solver_accuracy for r in sub_rep) * 100.0
        o_mean = mean(r.obvious_mean_score for r in sub_rep)
        o_acc = mean(r.obvious_accuracy for r in sub_rep) * 100.0
        m_mean = mean(r.catchability_margin for r in sub_rep)
        s_leaks = sum(r.total_leak_count for r in sub_rep)
        o_leaks = sum(r.obvious_total_leak_count for r in sub_rep)
        views = sum(r.views_checked for r in sub_rep)
        viols = sum(len(r.privileged_field_violations) for r in sub_rep)
        passed_cnt = sum(1 for r in sub_rep if r.passed)

        assert int(row["Runs"]) == n_r
        assert int(row["Loaded Entries"]) == n_ent
        assert int(row["Episodes / Policy"]) == n_eps
        assert row["Solver Mean"] == f"{s_mean:+.4f}"
        assert row["Solver Acc"] == f"{s_acc:.2f}%"
        assert row["Obvious Mean"] == f"{o_mean:+.4f}"
        assert row["Obvious Acc"] == f"{o_acc:.2f}%"
        assert row["Mean Margin"] == f"{m_mean:+.4f}"
        assert int(row["Solver Leaks"]) == s_leaks
        assert int(row["Obvious Leaks"]) == o_leaks
        assert int(row["Live Views"]) == views
        assert int(row["Violations"]) == viols
        assert row["Pass Rate"] == f"{passed_cnt}/{n_r}"


def test_replay_doc_per_run_table_exact_14_row_parity(
    keyless_replay_bundle: tuple[str, list[mra.StrategyRun], mra.ReplayAuditSummary],
) -> None:
    doc_text, loaded_runs, summary = keyless_replay_bundle
    per_run_sec = _extract_section(doc_text, f"{HASH}{HASH} 2. Per-Run Deterministic Replay & Privilege Audit")
    rows = _parse_markdown_table(per_run_sec)

    assert len(rows) == 14
    assert len(rows) == len(summary.runs) == len(loaded_runs)
    entries_by_run = {lr.run_id: len(lr.entries) for lr in loaded_runs}

    for row, rep in zip(rows, summary.runs, strict=True):
        expected_folder = f"results/gemini/roles_carbon/adaptive_mole/{rep.run_id}"
        assert _strip_ticks(row["Run Folder"]) == expected_folder
        assert _strip_ticks(row["Source Kind"]) == rep.source_kind
        assert _strip_ticks(row["Tier"]) == rep.tier
        assert _strip_ticks(row["Top Strategy Label"]) == rep.strategy_label
        assert int(row["Entries"]) == entries_by_run[rep.run_id]
        assert row["Solver Mean"] == f"{rep.solver_mean_score:+.4f}"
        assert row["Solver Acc"] == f"{rep.solver_accuracy * 100.0:.2f}%"
        assert row["Obvious Mean"] == f"{rep.obvious_mean_score:+.4f}"
        assert row["Obvious Acc"] == f"{rep.obvious_accuracy * 100.0:.2f}%"
        assert row["Margin"] == f"{rep.catchability_margin:+.4f}"
        assert int(row["Solver Leaks"]) == rep.total_leak_count
        assert int(row["Min Seed Leaks"]) == rep.min_seed_leak_count
        assert int(row["Obvious Leaks"]) == rep.obvious_total_leak_count
        assert int(row["Live Views"]) == rep.views_checked
        assert _strip_ticks(row["Behavioral Sig"]) == rep.behavioral_signature
        assert _strip_ticks(row["Status"]) == ("PASS" if rep.passed else "FAIL")


def test_replay_doc_equivalence_summary_and_multi_member_classes_parity(
    keyless_replay_bundle: tuple[str, list[mra.StrategyRun], mra.ReplayAuditSummary],
) -> None:
    doc_text, loaded_runs, summary = keyless_replay_bundle

    eq_sec = _extract_section(doc_text, f"{HASH}{HASH} 3. Behavioral Equivalence Deduplication")
    pool_rows = {_strip_ticks(r["Strategy Pool"]): r for r in _parse_markdown_table(eq_sec)}
    assert set(pool_rows.keys()) == {"all_strategies", "top_strategies"}

    for pool_key, eq_obj in (
        ("all_strategies", summary.all_strategies_equivalence),
        ("top_strategies", summary.top_strategies_equivalence),
    ):
        prow = pool_rows[pool_key]
        singletons = sum(1 for c in eq_obj.classes if c.member_count == 1)
        multi = sum(1 for c in eq_obj.classes if c.member_count > 1)
        assert int(prow["Total Entries"]) == eq_obj.n_strategies
        assert int(prow["Syntactic Unique JSON"]) == eq_obj.n_syntactic_unique
        assert int(prow["Behavioral Equivalence Classes"]) == eq_obj.n_equivalence_classes
        assert int(prow["Singleton Classes"]) == singletons
        assert int(prow["Multi-Member Classes"]) == multi
        assert int(prow["Synthetic Probe Views"]) == eq_obj.n_synthetic_views
        assert singletons + multi == eq_obj.n_equivalence_classes

    multi_sec = _extract_section(doc_text, f"{HASH}{HASH}{HASH} Multi-Member Behavioral Equivalence Classes")
    multi_rows = _parse_markdown_table(multi_sec)
    expected_multi = [c for c in summary.all_strategies_equivalence.classes if c.member_count > 1]
    assert len(multi_rows) == len(expected_multi) == 6

    entry_lookup = {
        (lr.run_id, entry.label): entry.strategy
        for lr in loaded_runs
        for entry in lr.entries
    }

    for mrow, eq_cls in zip(multi_rows, expected_multi, strict=True):
        assert _strip_ticks(mrow["Behavioral Sig"]) == eq_cls.signature
        assert int(mrow["Members"]) == eq_cls.member_count
        assert _strip_ticks(mrow["Source Kinds"]) == ", ".join(eq_cls.source_kinds)
        assert _strip_ticks(mrow["Representative Run"]) == eq_cls.representative_run_id
        assert _strip_ticks(mrow["Representative Label"]) == eq_cls.representative_label
        assert mrow["Algebraic Cause"].strip()

        sigs = {
            mra.behavioral_signature(entry_lookup[(m["run_id"], m["label"])])
            for m in eq_cls.members
        }
        assert sigs == {eq_cls.signature}


def test_replay_doc_verbatim_cli_summary_table_matches_format_summary_table(
    keyless_replay_bundle: tuple[str, list[mra.StrategyRun], mra.ReplayAuditSummary],
) -> None:
    doc_text, _, summary = keyless_replay_bundle
    cli_sec = _extract_section(doc_text, f"{HASH}{HASH} 4. Verbatim CLI Summary & Keyless Reproduction")

    bash_block = _extract_fenced_block(cli_sec, "bash")
    assert "python -m canary.gemini.mole_replay_audit --require-populated" in bash_block
    assert "pytest -q tests/test_gemini_lab_mole_replay_audit.py tests/test_gemini_lab_mole_replay_doc.py" in bash_block

    text_block = _extract_fenced_block(cli_sec, "text")
    doc_lines = [ln.rstrip() for ln in text_block.splitlines()]
    live_lines = [ln.rstrip() for ln in mra.format_summary_table(summary).splitlines()]
    assert doc_lines == live_lines
