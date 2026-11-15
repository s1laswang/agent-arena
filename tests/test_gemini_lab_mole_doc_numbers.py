from __future__ import annotations

import ast
import io
import json
from pathlib import Path
import re
import statistics
import sys
import tokenize
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from canary.gemini import mole_carbon as mc

DOC_PATH = ROOT / "docs" / "gemini" / "roles_carbon" / "adaptive_mole.md"
REPLAY_DOC_PATH = ROOT / "docs" / "gemini" / "roles_carbon" / "adaptive_mole_replay.md"
ROLES_DIR = ROOT / "results" / "gemini" / "roles_carbon" / "adaptive_mole"
SUITE_DIR = ROLES_DIR / "carbon-vs-carbon-suite"
SUITE_JSON_PATH = SUITE_DIR / "suite.json"
SUITE_SUMMARY_PATH = SUITE_DIR / "summary.md"
SELF_TEST_PATH = Path(__file__).resolve()

HASH = chr(0x23)
H1 = HASH
H2 = HASH * 2
H3 = HASH * 3

FORBIDDEN_DASHES: tuple[str, ...] = tuple(chr(c) for c in (*range(0x2010, 0x2016), 0x2212))
ESCAPED_DASH_TOKENS: tuple[str, ...] = tuple(
    "\\" + f"u{code:04x}" for code in (*range(0x2010, 0x2016), 0x2212)
)

EXPECTED_SCOPE = "arena mode, not the judged v1.4 environment"
EXPECTED_JUDGE_HASH = "a8f99c2537c91d72"
STUB_WORD_RE = re.compile(r"\b(?:TODO|TBD|DRAFT|PLACEHOLDER|FIXME)\b", re.IGNORECASE)
ANGLE_PLACEHOLDER_RE = re.compile(chr(0x3C) + r"[A-Za-z0-9_.\-/ ]+" + chr(0x3E))
DOC_RUN_PATH_RE = re.compile(
    r"(?<![A-Za-z0-9_.\-/])(results/gemini/roles_carbon/adaptive_mole/[A-Za-z0-9_.\-]+)"
)


@pytest.fixture(autouse=True)
def _keyless_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in mc.SECRET_ENV_VARS:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.delenv("GEMINI_GATEWAY_URL", raising=False)


def _strip_formatting(cell: str) -> str:
    val = cell.strip()
    if len(val) >= 4 and val.startswith("**") and val.endswith("**"):
        val = val[2:-2].strip()
    if len(val) >= 2 and val.startswith("`") and val.endswith("`"):
        val = val[1:-1].strip()
    return val


def _parse_int(cell: str) -> int:
    return int(_strip_formatting(cell).replace(",", ""))


def _parse_usd(cell: str) -> float:
    cleaned = _strip_formatting(cell)
    assert cleaned.startswith("$"), f"expected USD prefix in {cell!r}"
    return float(cleaned[1:].replace(",", ""))


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


def _extract_direct_subsection(doc_text: str, heading_prefix: str) -> str:
    sec = _extract_section(doc_text, heading_prefix)
    out: list[str] = []
    for line in sec.splitlines():
        if line.startswith(HASH):
            break
        out.append(line)
    return "\n".join(out)


def _parse_markdown_table(section_text: str) -> list[dict[str, str]]:
    table_lines = [ln.strip() for ln in section_text.splitlines() if ln.strip().startswith("|")]
    assert len(table_lines) >= 3, "expected markdown table with header, separator, and data rows"
    headers = [c.strip() for c in table_lines[0].strip("|").split("|")]
    rows: list[dict[str, str]] = []
    for raw_line in table_lines[2:]:
        cells = [c.strip() for c in raw_line.strip("|").split("|")]
        if len(cells) != len(headers):
            break
        rows.append(dict(zip(headers, cells, strict=True)))
    assert rows, "parsed zero data rows from markdown table"
    return rows


def _fmt_pct(val: float) -> str:
    return f"{val * 100.0:.2f}%"


def _fmt_pct_ci95(ci: list[float]) -> str:
    return f"[{ci[0] * 100.0:.1f}%, {ci[1] * 100.0:.1f}%]"


def _fmt_signed_ci95(ci: list[float]) -> str:
    return f"[{ci[0]:+.4f}, {ci[1]:+.4f}]"


def _iter_raw_run_dirs() -> list[Path]:
    assert ROLES_DIR.is_dir()
    out: list[Path] = []
    for entry in sorted(ROLES_DIR.iterdir()):
        if not entry.is_dir():
            continue
        if entry.name in mc.SKIP_DIRS or entry.name == mc.SUITE_DIR_NAME:
            continue
        assert (entry / "meta.json").is_file(), f"missing meta.json in {entry}"
        out.append(entry)
    return out


def test_doc_numbers_hygiene_zero_comments_dashes_stubs_and_secrets() -> None:
    self_src = SELF_TEST_PATH.read_text(encoding="utf-8")
    assert HASH not in self_src
    tokens = list(tokenize.generate_tokens(io.StringIO(self_src).readline))
    assert [tok for tok in tokens if tok.type == tokenize.COMMENT] == []
    tree = ast.parse(self_src)
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            assert ast.get_docstring(node) is None
    for dash in FORBIDDEN_DASHES:
        assert dash not in self_src
    assert mc.scan_file_secrets(SELF_TEST_PATH, ROOT) == []

    assert not (SUITE_DIR / "meta.json").exists()
    for path in (DOC_PATH, SUITE_SUMMARY_PATH, SUITE_JSON_PATH):
        assert path.is_file(), f"missing file: {path}"
        text = path.read_text(encoding="utf-8")
        assert text.strip()
        for dash in FORBIDDEN_DASHES:
            assert dash not in text, f"forbidden dash {hex(ord(dash))} in {path}"
        lower_text = text.lower()
        for esc in ESCAPED_DASH_TOKENS:
            assert esc not in lower_text, f"escaped forbidden dash {esc} in {path}"
        assert "results/gemini_roles/" not in text
        assert STUB_WORD_RE.search(text) is None
        assert ANGLE_PLACEHOLDER_RE.search(text) is None
        assert mc.scan_file_secrets(path, ROOT) == []

    doc_text = DOC_PATH.read_text(encoding="utf-8")
    summary_text = SUITE_SUMMARY_PATH.read_text(encoding="utf-8")
    raw_rels = {f"results/gemini/roles_carbon/adaptive_mole/{p.name}" for p in _iter_raw_run_dirs()}
    assert len(raw_rels) == 39

    for label, text in (("adaptive_mole.md", doc_text), ("summary.md", summary_text)):
        cited = set(DOC_RUN_PATH_RE.findall(text))
        assert cited == raw_rels, f"{label} cited paths mismatch: {cited ^ raw_rels}"
        for rel in cited:
            assert (ROOT / rel).is_dir(), f"cited directory missing: {rel}"


def test_committed_suite_and_doc_byte_exact_with_consolidator_recomputation(tmp_path: Path) -> None:
    out_suite = tmp_path / "recomputed_suite"
    out_doc = tmp_path / "recomputed_adaptive_mole.md"
    payload = mc.consolidate_adaptive_mole(root=ROOT, out_dir=out_suite, doc_path=out_doc)

    assert not (out_suite / "meta.json").exists()
    assert payload["skipped_runs"] == []
    assert payload["role"] == "adaptive_mole"
    assert payload["target_model"] == "gemini-4-carbon"
    assert payload["environment_scope"] == EXPECTED_SCOPE

    committed_suite_json = SUITE_JSON_PATH.read_text(encoding="utf-8")
    committed_summary_md = SUITE_SUMMARY_PATH.read_text(encoding="utf-8")
    committed_doc_md = DOC_PATH.read_text(encoding="utf-8")

    assert (out_suite / "suite.json").read_text(encoding="utf-8") == committed_suite_json
    assert (out_suite / "summary.md").read_text(encoding="utf-8") == committed_summary_md
    assert out_doc.read_text(encoding="utf-8") == committed_doc_md

    summary_lines = committed_summary_md.splitlines()
    assert summary_lines[0] == f"{H1} Consolidated Suite: Adaptive Gemini Mole (`gemini-4-carbon`)"
    summary_body = "\n".join(summary_lines[2:]).strip()
    assert committed_doc_md.rstrip().endswith(summary_body)


def test_scope_disclosure_and_headline_numbers_independently_recomputed_from_disk() -> None:
    doc_text = DOC_PATH.read_text(encoding="utf-8")
    scope_sec = _extract_section(doc_text, f"{H2} Scope & Non-Judged Arena Disclosure")
    headline_sec = _extract_section(doc_text, f"{H2} Headline Summary (`gemini-4-carbon`)")

    assert EXPECTED_SCOPE in scope_sec
    assert EXPECTED_JUDGE_HASH in scope_sec
    assert "`0..59`" in scope_sec
    assert "`5020..5399`" in scope_sec
    assert "flat per leak regardless of recipient" in scope_sec

    raw_dirs = _iter_raw_run_dirs()
    assert len(raw_dirs) == 39

    usages: list[dict[str, Any]] = []
    decisions_count = 0
    views_count = 0
    hof_strategies_count = 0
    forge_runs_count = 0
    forge_tiers: set[str] = set()
    forge_valid_children = 0
    paired_runs_count = 0
    paired_valid = 0
    paired_kept = 0
    clash_rows: list[dict[str, Any]] = []
    arena_adaptive_eps: list[dict[str, Any]] = []
    arena_default_eps: list[dict[str, Any]] = []
    catch_meta: dict[str, Any] | None = None

    for run_dir in raw_dirs:
        meta = json.loads((run_dir / "meta.json").read_text(encoding="utf-8"))
        assert meta["role"] == "adaptive_mole"
        assert meta["model_id"] == "gemini-4-carbon"
        usages.append(mc.normalize_usage(meta["usage"], meta["model_id"]))

        dec_file = run_dir / "mole_decisions.jsonl"
        if dec_file.is_file():
            dec_rows = [
                json.loads(ln)
                for ln in dec_file.read_text(encoding="utf-8").splitlines()
                if ln.strip()
            ]
            decisions_count += len(dec_rows)
            views_count += sum(1 for r in dec_rows if r.get("mole_view") is not None)

        mlog_file = run_dir / "mole_log.json"
        if mlog_file.is_file():
            mlog = json.loads(mlog_file.read_text(encoding="utf-8"))
            decisions_count += len(mlog["clash_mole_log"]) + len(mlog["solver_mole_log"])

        hof_file = run_dir / "hall_of_fame.jsonl"
        if hof_file.is_file():
            hof_lines = [ln for ln in hof_file.read_text(encoding="utf-8").splitlines() if ln.strip()]
            hof_strategies_count += len(hof_lines)

        name = run_dir.name
        if name.startswith("mole-forge-carbon-"):
            forge_runs_count += 1
            forge_tiers.add(str(meta["tier"]))
            forge_valid_children += int(meta["n_valid_llm_children"])
        elif name.startswith("paired-"):
            paired_runs_count += 1
            paired_valid += int(meta["n_llm_valid"])
            paired_kept += int(meta["n_kept"])
        elif name.startswith("carbon-vs-carbon-"):
            clash_rows.append(meta)
        elif name.startswith("arena-live-carbon-"):
            ep_doc = json.loads((run_dir / "episodes.json").read_text(encoding="utf-8"))
            arena_adaptive_eps.extend(ep_doc["adaptive_mole"])
            arena_default_eps.extend(ep_doc["default_mole"])
        elif name == "catchability-audit-carbon":
            catch_meta = meta

    assert decisions_count == 988
    assert views_count == 696
    assert hof_strategies_count == 57
    iso_live = mc.audit_committed_mole_runs(ROLES_DIR, ROOT)
    assert iso_live == {
        "passed": True,
        "decisions_checked": 988,
        "views_checked": 696,
        "strategies_checked": 57,
        "isolation_violations": 0,
        "secret_leaks": 0,
    }
    assert f"checks `{decisions_count}`" in scope_sec
    assert f"(`{views_count}` `MoleView` snapshots)" in scope_sec
    assert f"`{hof_strategies_count}`\n   Hall-of-Fame DSL strategies" in scope_sec
    assert "with `0` privileged-state violations" in scope_sec
    assert "and `0` file secret leaks." in scope_sec

    grand = mc.sum_usages(usages)
    assert grand["calls"] == 2257
    assert grand["in"] == 37033571
    assert grand["out"] == 152090
    assert grand["thinking"] == 641214
    assert grand["cached"] == 33025731
    assert grand["cost_usd"] == pytest.approx(19.251309, abs=1e-6)

    assert forge_runs_count == 4
    assert sorted(forge_tiers) == ["easy", "hard", "medium"]
    assert forge_valid_children == 123
    assert paired_runs_count == 10
    assert paired_kept == 49
    assert paired_valid == 56

    arena_sort_key = lambda e: (mc.TIER_RANK.get(str(e["tier"]), 99), str(e["tier"]), int(e["seed"]))
    arena_adaptive_sorted = sorted(arena_adaptive_eps, key=arena_sort_key)
    arena_default_sorted = sorted(arena_default_eps, key=arena_sort_key)

    sol_adapt = [float(e["score"]) for e in arena_adaptive_sorted if e["investigator"] == "solver"]
    sol_def = [float(e["score"]) for e in arena_default_sorted if e["investigator"] == "solver"]
    sol_adapt_k = sum(1 for e in arena_adaptive_sorted if e["investigator"] == "solver" and e["correct"])
    grok_adapt = [float(e["score"]) for e in arena_adaptive_sorted if e["investigator"] == "grok_tactics"]
    grok_def = [float(e["score"]) for e in arena_default_sorted if e["investigator"] == "grok_tactics"]

    sol_diffs = mc._paired_episode_diffs(
        [e for e in arena_adaptive_sorted if e["investigator"] == "solver"],
        [e for e in arena_default_sorted if e["investigator"] == "solver"],
    )
    grok_diffs = mc._paired_episode_diffs(
        [e for e in arena_adaptive_sorted if e["investigator"] == "grok_tactics"],
        [e for e in arena_default_sorted if e["investigator"] == "grok_tactics"],
    )

    sol_adapt_mean = round(statistics.mean(sol_adapt), 4)
    sol_def_mean = round(statistics.mean(sol_def), 4)
    sol_delta = round(sol_adapt_mean - sol_def_mean, 4)
    grok_adapt_mean = round(statistics.mean(grok_adapt), 4)
    grok_def_mean = round(statistics.mean(grok_def), 4)
    grok_delta = round(grok_adapt_mean - grok_def_mean, 4)

    clash_sorted = sorted(
        clash_rows,
        key=lambda m: (mc.TIER_RANK.get(str(m["tier"]), 99), str(m["tier"]), int(m["seed"])),
    )
    clash_n = len(clash_sorted)
    clash_eps = sum(int(m["episode_count"]) for m in clash_sorted)
    clash_inv_k = sum(1 for m in clash_sorted if m["investigator_correct"])
    clash_solv_k = sum(1 for m in clash_sorted if m["solvable"])
    clash_inv_scores = [float(m["investigator_score"]) for m in clash_sorted]
    clash_sol_scores = [float(m["solver_score"]) for m in clash_sorted]

    assert catch_meta is not None
    c_pass = int(catch_meta["n_catchability_passed"])
    c_targ = int(catch_meta["n_catchability_targets"])
    c_ci = mc.wilson_ci95(c_pass, c_targ)

    expected_headline_fragments = (
        f"`{len(raw_dirs)}` folders, `{grand['calls']}` Gemini API calls",
        f"`{grand['in']:,}` input / `{grand['out']:,}` output / `{grand['thinking']:,}` thinking / `{grand['cached']:,}` cached tokens",
        f"**`${grand['cost_usd']:.2f}`** (`${grand['cost_usd']:.6f}`)",
        f"(`n={forge_runs_count}` runs across `easy, hard, medium`)",
        f"`{forge_valid_children}` valid",
        "confirmation holdouts (`5020..5059`)",
        f"(`n={paired_runs_count}` runs)",
        f"`{paired_kept}/{paired_valid}` (`{_fmt_pct(paired_kept / paired_valid)}`)",
        f"(`n={len(sol_adapt)}` paired episodes per investigator)",
        f"from `{sol_def_mean:+.4f}` (default mole)",
        f"to `{sol_adapt_mean:+.4f}` {_fmt_signed_ci95(mc.bootstrap_mean_ci95(sol_adapt))}",
        f"(paired delta `{sol_delta:+.4f}` {_fmt_signed_ci95(mc.bootstrap_mean_ci95(sol_diffs))}",
        f"`{_fmt_pct(sol_adapt_k / len(sol_adapt))}` {_fmt_pct_ci95(mc.wilson_ci95(sol_adapt_k, len(sol_adapt)))}",
        f"from `{grok_def_mean:+.4f}` to\n  `{grok_adapt_mean:+.4f}` (paired delta `{grok_delta:+.4f}` {_fmt_signed_ci95(mc.bootstrap_mean_ci95(grok_diffs))})",
        f"(`n={clash_n}` shards, `{clash_eps}` episodes)",
        f"`{_fmt_pct(clash_inv_k / clash_n)}` {_fmt_pct_ci95(mc.wilson_ci95(clash_inv_k, clash_n))}",
        f"`{round(statistics.mean(clash_inv_scores), 4):+.4f}` {_fmt_signed_ci95(mc.bootstrap_mean_ci95(clash_inv_scores))} mean score",
        f"`{round(statistics.mean(clash_sol_scores), 4):+.4f}` {_fmt_signed_ci95(mc.bootstrap_mean_ci95(clash_sol_scores))}",
        f"`{_fmt_pct(clash_solv_k / clash_n)}` {_fmt_pct_ci95(mc.wilson_ci95(clash_solv_k, clash_n))}",
        f"`{c_pass}/{c_targ}`",
        f"(`{_fmt_pct(c_pass / c_targ)}` {_fmt_pct_ci95(c_ci)})",
        f"- Environment scope: `{EXPECTED_SCOPE}`",
        f"- Verified `adaptive_mole` run folders consolidated: `{len(raw_dirs)}`",
        f"- Total Gemini API calls: `{grand['calls']}`",
        f"- Total estimated cost (USD): `${grand['cost_usd']:.6f}`",
    )
    for frag in expected_headline_fragments:
        assert frag in headline_sec, f"missing headline fragment: {frag!r}"


def test_section1_clash_suite_and_16_shard_tables_match_raw_meta_and_logs() -> None:
    doc_text = DOC_PATH.read_text(encoding="utf-8")
    slice_sec = _extract_direct_subsection(doc_text, f"{H2} 1. Head-to-Head Carbon-vs-Carbon Clash Suite")
    shard_sec = _extract_section(doc_text, f"{H3} Per-Seed Clash Shards")

    slice_rows = {_strip_formatting(r["Slice"]): r for r in _parse_markdown_table(slice_sec)}
    assert set(slice_rows.keys()) == {"easy", "medium", "hard", "overall"}

    shard_rows = _parse_markdown_table(shard_sec)
    assert len(shard_rows) == 16

    raw_shards: list[dict[str, Any]] = []
    for row in shard_rows:
        rel_dir = _strip_formatting(row["Run Folder"])
        run_dir = ROOT / rel_dir
        meta = json.loads((run_dir / "meta.json").read_text(encoding="utf-8"))
        mlog = json.loads((run_dir / "mole_log.json").read_text(encoding="utf-8"))

        clash_entries = mlog["clash_mole_log"]
        solver_entries = mlog["solver_mole_log"]
        leaks = sum(1 for e in clash_entries if e["move"]["leak"] is not None)
        frames = sum(1 for e in clash_entries if e["move"]["frame"] is not None)
        errors = sum(1 for e in [*clash_entries, *solver_entries] if e.get("error") is not None)

        inv_s = float(meta["investigator_score"])
        sol_s = float(meta["solver_score"])
        regret = float(meta["regret"])
        norm_u = mc.normalize_usage(meta["usage"], meta["model_id"])
        inv_u = mc.normalize_usage(meta["usage"]["clash_investigator"], meta["model_id"])
        mole_u = mc.normalize_usage(meta["usage"]["clash_mole"], meta["model_id"])

        assert _strip_formatting(row["Tier"]) == meta["tier"]
        assert _parse_int(row["Seed"]) == int(meta["seed"])
        assert _strip_formatting(row["Commit"]) == meta["commit"][:10]
        assert row["Inv Score"] == f"{inv_s:+.4f}"
        assert row["Inv Correct"] == str(bool(meta["investigator_correct"]))
        assert row["Solver Score"] == f"{sol_s:+.4f}"
        assert row["Solver Correct"] == str(bool(meta["solver_correct"]))
        assert row["Solvable"] == str(bool(meta["solvable"]))
        assert regret == pytest.approx(sol_s - inv_s, abs=1e-6)
        assert row["Regret"] == f"{regret:+.4f}"
        assert _parse_int(row["Leaks"]) == leaks == int(meta["mole_clash_leaks"])
        assert _parse_int(row["Frames"]) == frames == int(meta["mole_clash_frames"])
        assert _parse_int(row["Errors"]) == errors == 0
        assert row["Cost (USD)"] == f"${norm_u['cost_usd']:.4f}"

        raw_shards.append(
            {
                "tier": meta["tier"],
                "episodes": int(meta["episode_count"]),
                "inv_score": inv_s,
                "inv_correct": bool(meta["investigator_correct"]),
                "sol_score": sol_s,
                "sol_correct": bool(meta["solver_correct"]),
                "solvable": bool(meta["solvable"]),
                "regret": regret,
                "leaks": leaks,
                "frames": frames,
                "errors": errors,
                "combined_u": norm_u,
                "inv_u": inv_u,
                "mole_u": mole_u,
            }
        )

    for key in ("easy", "medium", "hard", "overall"):
        sub = [s for s in raw_shards if key == "overall" or s["tier"] == key]
        srow = slice_rows[key]
        n = len(sub)
        inv_k = sum(1 for s in sub if s["inv_correct"])
        sol_k = sum(1 for s in sub if s["sol_correct"])
        solv_k = sum(1 for s in sub if s["solvable"])
        inv_vals = [s["inv_score"] for s in sub]
        sol_vals = [s["sol_score"] for s in sub]
        reg_vals = [s["regret"] for s in sub]
        cu = mc.sum_usages([s["combined_u"] for s in sub])
        iu = mc.sum_usages([s["inv_u"] for s in sub])
        mu = mc.sum_usages([s["mole_u"] for s in sub])

        assert _parse_int(srow["Shards"]) == n
        assert _parse_int(srow["Episodes"]) == sum(s["episodes"] for s in sub)
        assert (
            srow["Investigator Acc (95% CI)"]
            == f"{_fmt_pct(round(inv_k / n, 4))} {_fmt_pct_ci95(mc.wilson_ci95(inv_k, n))}"
        )
        assert (
            srow["Investigator Mean (95% CI)"]
            == f"{round(statistics.mean(inv_vals), 4):+.4f} {_fmt_signed_ci95(mc.bootstrap_mean_ci95(inv_vals))}"
        )
        assert srow["Solver Acc"] == _fmt_pct(round(sol_k / n, 4))
        assert (
            srow["Solver Mean (95% CI)"]
            == f"{round(statistics.mean(sol_vals), 4):+.4f} {_fmt_signed_ci95(mc.bootstrap_mean_ci95(sol_vals))}"
        )
        assert (
            srow["Solvable Rate (95% CI)"]
            == f"{_fmt_pct(round(solv_k / n, 4))} {_fmt_pct_ci95(mc.wilson_ci95(solv_k, n))}"
        )
        assert (
            srow["Mean Regret (95% CI)"]
            == f"{round(statistics.mean(reg_vals), 4):+.4f} {_fmt_signed_ci95(mc.bootstrap_mean_ci95(reg_vals))}"
        )
        assert _parse_int(srow["Mole Leaks"]) == sum(s["leaks"] for s in sub)
        assert _parse_int(srow["Mole Frames"]) == sum(s["frames"] for s in sub)
        assert _parse_int(srow["Mole Errors"]) == sum(s["errors"] for s in sub) == 0
        assert _strip_formatting(srow["Combined Tokens (in/out/think)"]) == f"{cu['in']:,}/{cu['out']:,}/{cu['thinking']:,}"
        assert srow["Inv Cost"] == f"${iu['cost_usd']:.4f}"
        assert srow["Mole Cost"] == f"${mu['cost_usd']:.4f}"
        assert srow["Total Cost"] == f"${cu['cost_usd']:.4f}"
        assert iu["cost_usd"] + mu["cost_usd"] == pytest.approx(cu["cost_usd"], abs=1e-4)


def test_section2_live_arena_tables_match_raw_episodes_and_decision_logs() -> None:
    doc_text = DOC_PATH.read_text(encoding="utf-8")
    arena_slice_sec = _extract_direct_subsection(doc_text, f"{H2} 2. Live Arena Adaptive Mole Suite")
    batch_sec = _extract_section(doc_text, f"{H3} Live Arena Seed Batches")

    slice_rows = _parse_markdown_table(arena_slice_sec)
    assert len(slice_rows) == 9
    batch_rows = _parse_markdown_table(batch_sec)
    assert len(batch_rows) == 8

    adaptive_all: list[dict[str, Any]] = []
    default_all: list[dict[str, Any]] = []

    for brow in batch_rows:
        rel_dir = _strip_formatting(brow["Run Folder"])
        run_dir = ROOT / rel_dir
        meta = json.loads((run_dir / "meta.json").read_text(encoding="utf-8"))
        ep_doc = json.loads((run_dir / "episodes.json").read_text(encoding="utf-8"))
        dec_rows = [
            json.loads(ln)
            for ln in (run_dir / "mole_decisions.jsonl").read_text(encoding="utf-8").splitlines()
            if ln.strip()
        ]
        norm_u = mc.normalize_usage(meta["usage"], meta["model_id"])

        leaks = sum(1 for d in dec_rows if d.get("leak") is not None)
        frames = sum(1 for d in dec_rows if d.get("frame") is not None)
        errors = sum(1 for d in dec_rows if d.get("error"))

        assert _strip_formatting(brow["Tier"]) == meta["tier"]
        assert _strip_formatting(brow["Seeds"]) == str(meta["seeds"])
        assert _strip_formatting(brow["Commit"]) == meta["commit"][:10]
        assert _parse_int(brow["Decisions"]) == len(dec_rows) == int(meta["mole_decisions_count"])
        assert _parse_int(brow["Leaks"]) == leaks
        assert _parse_int(brow["Frames"]) == frames
        assert _parse_int(brow["LLM Errors"]) == errors == 0
        assert brow["Solvable"] == str(bool(meta["solvability_verified"])) == "True"
        assert _parse_int(brow["Calls"]) == norm_u["calls"] == len(dec_rows)
        assert _strip_formatting(brow["Tokens (in/out/think)"]) == f"{norm_u['in']:,}/{norm_u['out']:,}/{norm_u['thinking']:,}"
        assert brow["Cost (USD)"] == f"${norm_u['cost_usd']:.4f}"

        adaptive_all.extend(ep_doc["adaptive_mole"])
        default_all.extend(ep_doc["default_mole"])

    row_map = {
        (r["Slice"], _strip_formatting(r["Investigator"])): r
        for r in slice_rows
    }
    for slice_name, expected_n in (("medium", 12), ("hard", 12), ("overall", 24)):
        for inv in ("solver", "grok_tactics", "obvious_heuristic"):
            cell_key = (f"`{slice_name}` (n={expected_n})", inv)
            assert cell_key in row_map, f"missing live arena slice row: {cell_key}"
            srow = row_map[cell_key]

            a_sub = [
                e for e in adaptive_all
                if e["investigator"] == inv and (slice_name == "overall" or e["tier"] == slice_name)
            ]
            d_sub = [
                e for e in default_all
                if e["investigator"] == inv and (slice_name == "overall" or e["tier"] == slice_name)
            ]
            assert len(a_sub) == len(d_sub) == expected_n

            a_scores = [float(e["score"]) for e in a_sub]
            d_scores = [float(e["score"]) for e in d_sub]
            a_k = sum(1 for e in a_sub if e["correct"])
            d_k = sum(1 for e in d_sub if e["correct"])
            diffs = mc._paired_episode_diffs(a_sub, d_sub)

            a_mean = round(statistics.mean(a_scores), 4)
            d_mean = round(statistics.mean(d_scores), 4)
            delta_mean = round(a_mean - d_mean, 4)

            assert (
                srow["Adaptive Mole Mean (95% CI)"]
                == f"{a_mean:+.4f} {_fmt_signed_ci95(mc.bootstrap_mean_ci95(a_scores))}"
            )
            assert (
                srow["Adaptive Mole Acc (95% CI)"]
                == f"{_fmt_pct(round(a_k / expected_n, 4))} {_fmt_pct_ci95(mc.wilson_ci95(a_k, expected_n))}"
            )
            assert (
                srow["Default Mole Mean (95% CI)"]
                == f"{d_mean:+.4f} {_fmt_signed_ci95(mc.bootstrap_mean_ci95(d_scores))}"
            )
            assert srow["Default Mole Acc"] == _fmt_pct(round(d_k / expected_n, 4))
            assert (
                srow["Paired Delta Mean (95% CI)"]
                == f"{delta_mean:+.4f} {_fmt_signed_ci95(mc.bootstrap_mean_ci95(diffs))}"
            )


def test_section3_mole_forge_and_section4_paired_designer_tables_match_raw_artifacts() -> None:
    doc_text = DOC_PATH.read_text(encoding="utf-8")
    forge_sec = _extract_section(doc_text, f"{H2} 3. Mole Forge Evolutionary DSL Suite")
    paired_sec = _extract_section(doc_text, f"{H2} 4. PAIRED Solvable Scenario Designer Suite")

    forge_rows = _parse_markdown_table(forge_sec)
    assert len(forge_rows) == 4
    for frow in forge_rows:
        rel_dir = _strip_formatting(frow["Run Folder"])
        run_dir = ROOT / rel_dir
        meta = json.loads((run_dir / "meta.json").read_text(encoding="utf-8"))
        gens_doc = json.loads((run_dir / "generations.json").read_text(encoding="utf-8"))
        hold_doc = json.loads((run_dir / "holdout_generalization.json").read_text(encoding="utf-8"))
        norm_u = mc.normalize_usage(meta["usage"], meta["model_id"])

        n_conf = len(hold_doc["splits"]["confirm_seeds"])
        c_acc = round(float(hold_doc["summary"]["top1_confirm_solver_acc"]), 4)
        assert n_conf == 40

        assert _strip_formatting(frow["Tier"]) == meta["tier"]
        assert _parse_int(frow["Gens"]) == int(meta["gens"]) == len(gens_doc["generations"])
        assert _parse_int(frow["Valid LLM Children"]) == int(meta["n_valid_llm_children"])
        assert frow["Best Fitness"] == f"{round(float(meta['best_fitness']), 4):.4f}"
        assert frow["Default Dev Fitness"] == f"{round(float(meta['default_dev_fitness']), 4):.4f}"
        assert frow["Fresh Solver Acc"] == _fmt_pct(round(float(meta["fresh_solver_accuracy"]), 4))
        assert frow["Fresh Min Regret"] == f"{round(float(meta['fresh_min_regret']), 4):.4f}"
        assert frow["Default Fresh Min Regret"] == f"{round(float(meta['default_fresh_min_regret']), 4):.4f}"
        assert frow["Confirm Holdout Acc"] == f"{_fmt_pct(c_acc)} (n={n_conf})"
        assert _parse_int(frow["Calls"]) == norm_u["calls"]
        assert frow["Cost (USD)"] == f"${norm_u['cost_usd']:.4f}"

    paired_rows = _parse_markdown_table(paired_sec)
    assert len(paired_rows) == 10
    for prow in paired_rows:
        rel_dir = _strip_formatting(prow["Run Folder"])
        run_dir = ROOT / rel_dir
        meta = json.loads((run_dir / "meta.json").read_text(encoding="utf-8"))
        gap_doc = json.loads((run_dir / "skill_gap.json").read_text(encoding="utf-8"))
        norm_u = mc.normalize_usage(meta["usage"], meta["model_id"])

        raw_sol = meta.get("kept_solver_mean")
        if raw_sol is None:
            raw_sol = meta["design_solver_mean"]
        raw_heur = meta.get("kept_heuristic_mean")
        if raw_heur is None:
            raw_heur = meta["design_heuristic_mean"]

        hc = gap_doc["headline_comparison"]
        hold_sol = round(float(hc["full_solver"]["designed_mean_score"]), 4)
        hold_heur = round(float(hc["heuristic_bisection"]["designed_mean_score"]), 4)

        assert _strip_formatting(prow["Tier"]) == meta["tier"]
        assert _strip_formatting(prow["Subrole"]) == meta["subrole"]
        assert prow["Kept / Valid"] == f"{int(meta['n_kept'])}/{int(meta['n_llm_valid'])}"
        assert prow["Design/Kept Solver Mean"] == f"{round(float(raw_sol), 4):+.4f}"
        assert prow["Design/Kept Heuristic Mean"] == f"{round(float(raw_heur), 4):+.4f}"
        assert prow["Holdout Full Solver Mean"] == f"{hold_sol:+.4f}"
        assert prow["Holdout Heuristic Mean"] == f"{hold_heur:+.4f}"
        assert _strip_formatting(prow["Top Scenario"]) == meta["top_scenario_name"] == gap_doc["selected_scenario"]["name"]
        assert _parse_int(prow["Calls"]) == norm_u["calls"]
        assert prow["Cost (USD)"] == f"${norm_u['cost_usd']:.4f}"


def test_catchability_audit_totals_table_and_cross_doc_consistency_with_replay_md() -> None:
    doc_text = DOC_PATH.read_text(encoding="utf-8")
    catch_sec = _extract_section(doc_text, f"{H2} Catchability & Secret-Isolation Audit")
    other_sec = _extract_section(doc_text, f"{H2} Additional Verified Adaptive Mole Runs")
    totals_sec = _extract_section(doc_text, f"{H2} 5. De-Duplicated Totals")

    catch_dir = ROLES_DIR / "catchability-audit-carbon"
    catch_meta = json.loads((catch_dir / "meta.json").read_text(encoding="utf-8"))
    catch_u = mc.normalize_usage(catch_meta["usage"], catch_meta["model_id"])
    c_pass = int(catch_meta["n_catchability_passed"])
    c_targ = int(catch_meta["n_catchability_targets"])
    c_ci = mc.wilson_ci95(c_pass, c_targ)

    assert f"`results/gemini/roles_carbon/adaptive_mole/catchability-audit-carbon` (commit `{catch_meta['commit'][:10]}`)" in catch_sec
    assert (
        f"`{catch_meta['n_runs_audited']}` / `{catch_meta['n_strategies_audited']}` / "
        f"`{catch_meta['n_decisions_audited']}` / `{catch_meta['n_views_checked']}`"
    ) in catch_sec
    assert "`0` (file secret leaks: `0`)" in catch_sec
    assert f"`{c_pass}/{c_targ}` (`{_fmt_pct(c_pass / c_targ)}` {_fmt_pct_ci95(c_ci)})" in catch_sec
    assert "`True`" in catch_sec

    other_rows = _parse_markdown_table(other_sec)
    assert len(other_rows) == 1
    orow = other_rows[0]
    assert _strip_formatting(orow["Run Folder"]) == "results/gemini/roles_carbon/adaptive_mole/catchability-audit-carbon"
    assert _strip_formatting(orow["Subrole"]) == catch_meta["subrole"]
    assert _strip_formatting(orow["Commit"]) == catch_meta["commit"][:10]
    assert _parse_int(orow["Calls"]) == catch_u["calls"]
    assert _strip_formatting(orow["Tokens (in/out/think)"]) == f"{catch_u['in']:,}/{catch_u['out']:,}/{catch_u['thinking']:,}"
    assert orow["Cost (USD)"] == f"${catch_u['cost_usd']:.4f}"

    tot_rows = _parse_markdown_table(totals_sec)
    assert len(tot_rows) == 6
    by_label = {_strip_formatting(r["Suite Slice"]): r for r in tot_rows}
    slice_keys = (
        "clash_suite",
        "live_arena_suite",
        "mole_forge_suite",
        "paired_designer_suite",
        "other_verified_runs",
    )
    assert set(by_label.keys()) == {*slice_keys, "total"}

    bucket_map = {
        "clash": "clash_suite",
        "live_arena": "live_arena_suite",
        "mole_forge": "mole_forge_suite",
        "paired_designer": "paired_designer_suite",
        "other": "other_verified_runs",
    }
    raw_by_slice: dict[str, list[dict[str, Any]]] = {k: [] for k in slice_keys}
    for run_dir in _iter_raw_run_dirs():
        ok, rec, errs = mc.verify_adaptive_mole_run(run_dir / "meta.json", ROOT)
        assert ok and rec is not None and errs == []
        raw_by_slice[bucket_map[mc._classify_run(rec)]].append(rec["usage"])

    sum_folders = 0
    sum_calls = 0
    sum_in = 0
    sum_out = 0
    sum_think = 0
    sum_cached = 0
    sum_cost = 0.0

    for skey in slice_keys:
        trow = by_label[skey]
        su = mc.sum_usages(raw_by_slice[skey])
        nf = len(raw_by_slice[skey])
        assert _parse_int(trow["Verified Folders"]) == nf
        assert _parse_int(trow["Calls"]) == su["calls"]
        assert _parse_int(trow["Input Tokens"]) == su["in"]
        assert _parse_int(trow["Output Tokens"]) == su["out"]
        assert _parse_int(trow["Thinking Tokens"]) == su["thinking"]
        assert _parse_int(trow["Cached Tokens"]) == su["cached"]
        assert trow["Cost (USD)"] == f"${su['cost_usd']:.6f}"

        sum_folders += nf
        sum_calls += su["calls"]
        sum_in += su["in"]
        sum_out += su["out"]
        sum_think += su["thinking"]
        sum_cached += su["cached"]
        sum_cost = round(sum_cost + su["cost_usd"], 6)

    total_row = by_label["total"]
    assert _parse_int(total_row["Verified Folders"]) == sum_folders == 39
    assert _parse_int(total_row["Calls"]) == sum_calls == 2257
    assert _parse_int(total_row["Input Tokens"]) == sum_in == 37033571
    assert _parse_int(total_row["Output Tokens"]) == sum_out == 152090
    assert _parse_int(total_row["Thinking Tokens"]) == sum_think == 641214
    assert _parse_int(total_row["Cached Tokens"]) == sum_cached == 33025731
    assert _parse_usd(total_row["Cost (USD)"]) == pytest.approx(sum_cost, abs=1e-6)
    assert _strip_formatting(total_row["Cost (USD)"]) == f"${sum_cost:.6f}"

    if REPLAY_DOC_PATH.is_file():
        replay_text = REPLAY_DOC_PATH.read_text(encoding="utf-8")
        assert EXPECTED_SCOPE in replay_text
        assert EXPECTED_JUDGE_HASH in replay_text

        forge_rows = _parse_markdown_table(_extract_section(doc_text, f"{H2} 3. Mole Forge Evolutionary DSL Suite"))
        paired_rows = _parse_markdown_table(_extract_section(doc_text, f"{H2} 4. PAIRED Solvable Scenario Designer Suite"))
        replay_per_run = _parse_markdown_table(
            _extract_section(replay_text, f"{H2} 2. Per-Run Deterministic Replay & Privilege Audit")
        )
        assert len(replay_per_run) == len(forge_rows) + len(paired_rows) == 14

        doc_forge_tiers = {_strip_formatting(r["Run Folder"]): _strip_formatting(r["Tier"]) for r in forge_rows}
        doc_paired_info = {
            _strip_formatting(r["Run Folder"]): (
                _strip_formatting(r["Tier"]),
                _strip_formatting(r["Top Scenario"]),
                int(r["Kept / Valid"].split("/")[0]),
            )
            for r in paired_rows
        }

        replay_forge_entries = 0
        replay_paired_entries = 0
        for rrow in replay_per_run:
            rfolder = _strip_formatting(rrow["Run Folder"])
            rkind = _strip_formatting(rrow["Source Kind"])
            rtier = _strip_formatting(rrow["Tier"])
            rlabel = _strip_formatting(rrow["Top Strategy Label"])
            rentries = _parse_int(rrow["Entries"])
            if rkind == "mole_forge":
                assert doc_forge_tiers[rfolder] == rtier
                replay_forge_entries += rentries
            else:
                assert rkind == "paired_designer"
                exp_tier, exp_top, exp_kept = doc_paired_info[rfolder]
                assert rtier == exp_tier
                assert rlabel == exp_top
                assert rentries == exp_kept
                replay_paired_entries += rentries

        assert replay_forge_entries == 57
        assert replay_paired_entries == 49
