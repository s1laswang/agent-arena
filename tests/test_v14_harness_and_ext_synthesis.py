from __future__ import annotations

from contextlib import redirect_stdout
import copy
import io
import json
import math
import posixpath
import re
import sys
import tokenize
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import analyze_v14_harness_and_family_gap as synth_mod

SCRIPT_PATH = ROOT / "scripts" / "analyze_v14_harness_and_family_gap.py"
REPORT_PATH = ROOT / "docs" / "reports" / "frontier_v14_harness_and_ext_synthesis.md"
PAIRED_GEMINI_JSON = ROOT / "data" / "runs" / "committed" / "v1.4" / "paired_table_gemini.json"
POOLED38_JSON = (
    ROOT / "results" / "frontier_replication" / "v1.4" / "opencode-gemini-4-carbon-ext" / "paired_table_pooled38.json"
)
COMMITTED_V14_DIR = ROOT / "data" / "runs" / "committed" / "v1.4"
COMMITTED_EXT_EPISODES = COMMITTED_V14_DIR / "opencode-gemini-4-carbon-ext" / "hard" / "episodes.jsonl"
FLEET_EXT_EPISODES = (
    ROOT / "results" / "frontier_replication" / "v1.4" / "opencode-gemini-4-carbon-ext" / "hard" / "episodes.jsonl"
)

EM_DASH = chr(0x2014)
EN_DASH = chr(0x2013)
MINUS_SIGN = chr(0x2212)
HASH_CHAR = chr(35)

_CACHED_BASE_DATA: dict[str, Any] | None = None


def _base_data() -> dict[str, Any]:
    global _CACHED_BASE_DATA
    if _CACHED_BASE_DATA is None:
        _CACHED_BASE_DATA = synth_mod.analyze_harness_and_family_gap(repo=ROOT)
    return _CACHED_BASE_DATA


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _strip_md(cell: str) -> str:
    return cell.replace("**", "").replace("`", "").strip()


def _extract_markdown_tables(md_text: str) -> list[list[list[str]]]:
    tables: list[list[list[str]]] = []
    cur: list[list[str]] = []
    for raw_line in md_text.splitlines():
        line = raw_line.strip()
        if line.startswith("|") and line.endswith("|"):
            cur.append([c.strip() for c in line.strip("|").split("|")])
        else:
            if len(cur) >= 3:
                tables.append(cur)
            cur = []
    if len(cur) >= 3:
        tables.append(cur)
    return tables


def _make_staged_committed_root(base_dir: Path) -> Path:
    comm_root = base_dir / "committed"
    v14_dst = comm_root / "v1.4"
    v14_dst.mkdir(parents=True, exist_ok=True)
    for item in COMMITTED_V14_DIR.iterdir():
        (v14_dst / item.name).symlink_to(item)
    return comm_root


def test_hygiene_zero_comments_zero_unicode_dashes_and_valid_links():
    assert SCRIPT_PATH.is_file()
    assert REPORT_PATH.is_file()
    this_test = Path(__file__).resolve()

    for py_path in (SCRIPT_PATH, this_test):
        py_bytes = py_path.read_bytes()
        py_text = py_bytes.decode("utf-8")
        comment_tokens = [
            tok for tok in tokenize.tokenize(io.BytesIO(py_bytes).readline) if tok.type == tokenize.COMMENT
        ]
        assert comment_tokens == [], f"unexpected COMMENT tokens in {py_path}: {comment_tokens}"
        assert HASH_CHAR not in py_text
        assert EM_DASH not in py_text and EN_DASH not in py_text and MINUS_SIGN not in py_text

    md_text = REPORT_PATH.read_text(encoding="utf-8")
    assert EM_DASH not in md_text and EN_DASH not in md_text and MINUS_SIGN not in md_text

    link_re = re.compile(r"\[[^\]]+\]\(([^)]+)\)")
    md_dir = "docs/reports"
    checked_links = 0
    in_fence = False
    for line in md_text.splitlines():
        if line.strip().startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        for match in link_re.finditer(line):
            target = match.group(1).strip().split(HASH_CHAR, 1)[0]
            if not target or target.startswith(("http://", "https://", "mailto:")):
                continue
            resolved = posixpath.normpath(posixpath.join(md_dir, target))
            assert (ROOT / resolved).exists(), f"broken relative link {target} -> {resolved}"
            checked_links += 1
    assert checked_links >= 15


def test_cli_check_and_json_keyless(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("CANARY_ALLOW_DEV", "1")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    out_check = io.StringIO()
    with redirect_stdout(out_check):
        rc_check = synth_mod.main(["--check"])
    assert rc_check == 0
    assert "PASS:" in out_check.getvalue()

    out_json = io.StringIO()
    with redirect_stdout(out_json):
        rc_json = synth_mod.main(["--json"])
    assert rc_json == 0
    payload = json.loads(out_json.getvalue())
    assert payload["schema_version"] == "v1.4-harness-family-ext-synthesis-1"
    assert payload["provenance"]["primary_seeds"] == list(range(0, 30))
    assert payload["provenance"]["dedup_ext8_seeds"] == [30, 34, 37, 42, 45, 48, 57, 58]
    assert len(payload["provenance"]["unobserved_ext22_seeds"]) == 22

    gpt55_live = COMMITTED_V14_DIR / "opencode-gpt-5.5" / "hard" / "episodes.jsonl"
    if gpt55_live.is_file():
        assert "opencode-gpt-5.5" in payload["g2_families"]["detected"]
        gpt_coh = payload["g2_families"]["cohorts"]["opencode_gpt55"]
        assert gpt_coh["n"] == 30
        assert round(100.0 * gpt_coh["raw_ratio"]) == 101
        assert round(100.0 * gpt_coh["luck_adjusted_ratio"]) == 84
        assert gpt_coh["correct_count"] == 28
        assert gpt_coh["wrong_count"] == 0
        assert gpt_coh["abstention_count"] == 2

    tampered_md = tmp_path / "tampered_report.md"
    tampered_md.write_text(
        REPORT_PATH.read_text(encoding="utf-8").replace("72.0%", "99.9%", 1),
        encoding="utf-8",
    )
    out_fail = io.StringIO()
    with redirect_stdout(out_fail):
        rc_fail = synth_mod.main(["--check", "--report-md", str(tampered_md)])
    assert rc_fail == 1
    assert "[FAIL]" in out_fail.getvalue()


def test_core_cohorts_and_identities_match_committed_tables(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("CANARY_ALLOW_DEV", "1")
    data = _base_data()

    paired_rows = json.loads(PAIRED_GEMINI_JSON.read_text(encoding="utf-8"))
    by_tier_agent = {
        (r["tier"], r["group"], r["agent"]): r
        for r in paired_rows
        if "alternative" not in r["label"]
    }

    c0 = data["cohorts_0to29"]
    cm = data["medium_cohorts_0to29"]
    checks = [
        (c0["opencode_carbon"], by_tier_agent[("hard", "v1.4/opencode-gemini-4-carbon", "opencode:google/gemini-4-carbon")]),
        (c0["inproc_carbon"], by_tier_agent[("hard", "v1.4/inproc-gemini-4-carbon", "gemini:gemini-4-carbon")]),
        (c0["opencode_flash"], by_tier_agent[("hard", "v1.4/opencode-gemini-3.5-flash", "opencode:google/gemini-3.5-flash")]),
        (c0["solver"], by_tier_agent[("hard", "v1.4/reference", "solver")]),
        (c0["heuristic_committed20"], by_tier_agent[("hard", "v1.4/reference", "heuristic")]),
        (cm["opencode_carbon_medium"], by_tier_agent[("medium", "v1.4/opencode-gemini-4-carbon", "opencode:google/gemini-4-carbon")]),
        (cm["inproc_carbon_medium"], by_tier_agent[("medium", "v1.4/inproc-gemini-4-carbon", "gemini:gemini-4-carbon")]),
        (cm["solver_medium"], by_tier_agent[("medium", "v1.4/reference", "solver")]),
    ]
    for coh, ref in checks:
        assert coh["n"] == ref["n"]
        assert abs(coh["raw_mean"] - ref["mean"]) < 1e-12
        assert abs(coh["raw_ci"] - ref["ci"]) < 1e-12
        assert abs(coh["accuracy"] - ref["accuracy"]) < 1e-12
        assert abs(coh["accused_rate"] - ref["accused_rate"]) < 1e-12
        assert abs(coh["luck_adjusted_mean"] - ref["post_expected"]) < 1e-12
        if coh["agent"] != "solver":
            assert abs(coh["raw_diff"] - ref["diff"]) < 1e-12
            assert abs(coh["raw_diff_ci"] - ref["diff_ci"]) < 1e-12
            assert abs(coh["raw_ratio"] - ref["ratio"]) < 1e-12
            assert abs(coh["raw_ratio_lo"] - ref["ratio_lo"]) < 1e-12
            assert abs(coh["raw_ratio_hi"] - ref["ratio_hi"]) < 1e-12
            assert abs(coh["luck_adjusted_ratio"] - ref["post_expected_ratio"]) < 1e-12
            assert abs(coh["luck_adjusted_ratio_lo"] - ref["post_expected_lo"]) < 1e-12
            assert abs(coh["luck_adjusted_ratio_hi"] - ref["post_expected_hi"]) < 1e-12

    if POOLED38_JSON.is_file():
        p38_rows = json.loads(POOLED38_JSON.read_text(encoding="utf-8"))
        p38_map = {(r["tier"], r["group"]): r for r in p38_rows if "alternative" not in r["label"]}
        ext_ref = p38_map[("hard", "v1.4/opencode-gemini-4-carbon-ext")]
        pool_ref = p38_map[("hard", "v1.4/opencode-gemini-4-carbon+v1.4/opencode-gemini-4-carbon-ext")]
        for coh, ref in (
            (data["extension_comparison"]["cohorts"]["carbon_ext8"], ext_ref),
            (data["extension_comparison"]["cohorts"]["carbon_pooled38"], pool_ref),
        ):
            assert coh["n"] == ref["n"]
            assert abs(coh["raw_mean"] - ref["mean"]) < 1e-12
            assert abs(coh["luck_adjusted_mean"] - ref["post_expected"]) < 1e-12
            assert abs(coh["raw_ratio"] - ref["ratio"]) < 1e-12
            assert abs(coh["luck_adjusted_ratio"] - ref["post_expected_ratio"]) < 1e-12

    assert synth_mod._validate_invariants(data) == []

    hg = data["harness_gap"]["hard_0to29"]
    assert hg["head_to_head"]["raw"]["wtl"] == "16-0-14"
    assert hg["head_to_head"]["luck_adjusted"]["wtl"] == "12-0-18"
    assert hg["both_correct_n"] == 24
    assert abs((hg["luck_adjusted_diff"] + hg["luck_windfall_delta"]) - hg["raw_diff"]) < 1e-12

    hm = data["harness_gap"]["medium_0to29"]["head_to_head"]
    assert hm["raw"]["wtl"] == "18-2-10"
    assert hm["luck_adjusted"]["wtl"] == "18-1-11"

    mg = data["model_tier_gap"]["hard_0to29"]
    assert mg["head_to_head"]["raw"]["wtl"] == "14-1-15"
    assert mg["head_to_head"]["luck_adjusted"]["wtl"] == "17-0-13"
    assert (
        abs(
            mg["luck_adjusted_diff"]
            - (c0["opencode_carbon"]["luck_adjusted_mean"] - c0["opencode_flash"]["luck_adjusted_mean"])
        )
        < 1e-12
    )
    assert round(mg["luck_adjusted_diff"], 3) == 0.250

    ext_h = data["extension_comparison"]["head_to_head"]
    assert ext_h["carbon_ext8_vs_heuristic"]["raw"]["wtl"] == "8-0-0"
    assert ext_h["carbon_ext8_vs_heuristic"]["luck_adjusted"]["wtl"] == "8-0-0"
    assert ext_h["carbon_ext8_vs_solver"]["luck_adjusted"]["wtl"] == "7-0-1"
    assert ext_h["carbon_pooled38_vs_heuristic"]["luck_adjusted"]["wtl"] == "32-0-6"
    assert ext_h["carbon_pooled38_vs_solver"]["luck_adjusted"]["wtl"] == "17-0-21"


def test_forward_compat_opencode_gpt55_g2_families_and_pr3_ext8(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("CANARY_ALLOW_DEV", "1")
    base_data = _base_data()
    expected_md = REPORT_PATH.read_text(encoding="utf-8")

    pre_root = _make_staged_committed_root(tmp_path / "pre_justsilas")
    for opt_name in ("opencode-gpt-5.5", "opencode-gemini-4-argon", "opencode-gemini-4-hydrogen"):
        opt_link = pre_root / "v1.4" / opt_name
        if opt_link.is_symlink():
            opt_link.unlink()
    buf_pre = io.StringIO()
    with redirect_stdout(buf_pre):
        assert synth_mod.main(["--check", "--json", "--committed-root", str(pre_root)]) == 0
    pre_payload = json.loads(buf_pre.getvalue())
    assert pre_payload["ok"] is True
    assert pre_payload["data"]["g2_families"]["detected"] == []
    assert synth_mod.render_markdown(pre_payload["data"]) == expected_md

    comm_root = _make_staged_committed_root(tmp_path / "post_justsilas_and_g2")
    v14_dir = comm_root / "v1.4"
    carbon_eps = _read_jsonl(COMMITTED_V14_DIR / "opencode-gemini-4-carbon" / "hard" / "episodes.jsonl")

    gpt55_eps: list[dict[str, Any]] = []
    for ep in carbon_eps:
        cloned = copy.deepcopy(ep)
        cloned["agent"] = "opencode:openai/gpt-5.5"
        if int(cloned["seed"]) in (0, 17):
            cloned["score"] = 0.0
            cloned["accused"] = None
            cloned["correct"] = False
            cloned["final_day"] = 0
            cloned["end_reason"] = "error"
            cloned_meta = dict(cloned.get("meta") or {})
            cloned_meta.pop("V", None)
            cloned_meta["V_final"] = None
            cloned_meta["valid"] = True
            cloned["meta"] = cloned_meta
            cloned["steps"] = [st for st in (cloned.get("steps") or []) if st.get("tool") != "accuse"]
        gpt55_eps.append(cloned)

    argon_eps = []
    for ep in carbon_eps[:5]:
        cloned = copy.deepcopy(ep)
        cloned["agent"] = "opencode:google/gemini-4-argon"
        argon_eps.append(cloned)

    hydrogen_eps = []
    for ep in carbon_eps[:1]:
        cloned = copy.deepcopy(ep)
        cloned["agent"] = "opencode:google/gemini-4-hydrogen"
        hydrogen_eps.append(cloned)

    for sub_name, rows in (
        ("opencode-gpt-5.5", gpt55_eps),
        ("opencode-gemini-4-argon", argon_eps),
        ("opencode-gemini-4-hydrogen", hydrogen_eps),
    ):
        target_dir = v14_dir / sub_name / "hard"
        if (v14_dir / sub_name).is_symlink():
            (v14_dir / sub_name).unlink()
        target_dir.mkdir(parents=True, exist_ok=True)
        (target_dir / "episodes.jsonl").write_text(
            "\n".join(json.dumps(r) for r in rows) + "\n",
            encoding="utf-8",
        )

    buf_check = io.StringIO()
    with redirect_stdout(buf_check):
        rc = synth_mod.main(["--check", "--json", "--committed-root", str(comm_root)])
    assert rc == 0
    post_payload = json.loads(buf_check.getvalue())
    assert post_payload["ok"] is True
    assert post_payload["errors"] == []
    post_data = post_payload["data"]
    assert synth_mod.render_markdown(post_data) == expected_md
    assert post_data["g2_families"]["detected"] == [
        "opencode-gemini-4-argon",
        "opencode-gemini-4-hydrogen",
        "opencode-gpt-5.5",
    ]
    assert post_data["g2_families"]["cohorts"]["opencode_gpt55"]["n"] == 30
    assert post_data["g2_families"]["cohorts"]["opencode_gpt55"]["abstention_count"] >= 2
    assert post_data["g2_families"]["cohorts"]["opencode_argon"]["n"] == 5
    assert post_data["g2_families"]["cohorts"]["opencode_hydrogen"]["n"] == 1
    pair_ids = {h["id"] for h in post_data["g2_families"]["head_to_head"]}
    assert "opencode_gpt55_vs_solver" in pair_ids
    assert "opencode_gpt55_vs_opencode_carbon" in pair_ids
    assert "opencode_argon_vs_opencode_gpt55" in pair_ids
    assert "opencode_argon_vs_opencode_hydrogen" in pair_ids
    assert "opencode_hydrogen_vs_opencode_gpt55" in pair_ids
    cross_ids = [r["id"] for r in post_data["cross_family_rows_0to29"]]
    assert "opencode_gpt55" in cross_ids and "opencode_argon" in cross_ids and "opencode_hydrogen" in cross_ids

    comm_ext_eps = _read_jsonl(COMMITTED_EXT_EPISODES)
    fleet_eps = _read_jsonl(FLEET_EXT_EPISODES)
    g1_by_seed = {int(ep["seed"]): ep for ep in comm_ext_eps if int(ep["seed"]) in (34, 37)}
    pr3_by_seed = {int(ep["seed"]): ep for ep in fleet_eps}
    pr3_by_seed.update(g1_by_seed)
    pr3_eps = [pr3_by_seed[s] for s in sorted(pr3_by_seed)]
    assert [int(ep["seed"]) for ep in pr3_eps] == [30, 34, 37, 42, 45, 48, 57, 58]

    pr3_jsonl = tmp_path / "pr3_ext8_episodes.jsonl"
    pr3_jsonl.write_text("\n".join(json.dumps(ep) for ep in pr3_eps) + "\n", encoding="utf-8")
    missing_fleet = tmp_path / "missing_fleet_episodes.jsonl"

    pr3_data = synth_mod.analyze_harness_and_family_gap(
        repo=ROOT,
        committed_ext_jsonl=pr3_jsonl,
        fleet_ext_jsonl=missing_fleet,
    )
    assert pr3_data["provenance"]["committed_ext_layout"] == "pr3_ext8"
    assert json.dumps(pr3_data["extension_comparison"], sort_keys=True) == json.dumps(
        base_data["extension_comparison"], sort_keys=True
    )
    assert synth_mod.render_markdown(pr3_data) == expected_md
    assert (
        synth_mod.main([
            "--check",
            "--committed-ext-jsonl",
            str(pr3_jsonl),
            "--fleet-ext-jsonl",
            str(missing_fleet),
        ])
        == 0
    )

    fleet_seed34 = next(ep for ep in fleet_eps if int(ep["seed"]) == 34)
    bad_pr3_eps = [fleet_seed34 if int(ep["seed"]) == 34 else ep for ep in pr3_eps]
    bad_jsonl = tmp_path / "bad_seed34_episodes.jsonl"
    bad_jsonl.write_text("\n".join(json.dumps(ep) for ep in bad_pr3_eps) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="seed 34"):
        synth_mod.analyze_harness_and_family_gap(repo=ROOT, committed_ext_jsonl=bad_jsonl)


def test_every_markdown_table_cell_matches_deterministic_json(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("CANARY_ALLOW_DEV", "1")
    data = _base_data()
    md_text = REPORT_PATH.read_text(encoding="utf-8")
    assert md_text == synth_mod.render_markdown(data)

    tables = _extract_markdown_tables(md_text)
    assert len(tables) == 7

    c0 = data["cohorts_0to29"]
    t2a_expected = [
        c0["opencode_carbon"],
        c0["inproc_carbon"],
        c0["opencode_flash"],
        c0["solver"],
        c0["heuristic"],
        c0["heuristic_committed20"],
    ]
    t2a_rows = tables[0][2:]
    assert len(t2a_rows) == len(t2a_expected)
    for cells, coh in zip(t2a_rows, t2a_expected):
        assert cells[0] == coh["label"]
        assert int(cells[1]) == coh["n"]
        assert _strip_md(cells[2]) == f"{coh['raw_mean']:+.3f} +/- {coh['raw_ci']:.3f}"
        assert _strip_md(cells[4]) == f"{coh['luck_adjusted_mean']:+.3f} +/- {coh['luck_adjusted_ci']:.3f}"
        assert (
            _strip_md(cells[6])
            == f"{100.0 * coh['accuracy']:.1f}% ({coh['correct_count']}/{coh['wrong_count']}/{coh['abstention_count']})"
        )
        assert _strip_md(cells[7]) == f"{coh['p_accused_mean']:.3f}"
        assert _strip_md(cells[8]) == f"{coh['accuse_day_mean']:.1f}"
        assert _strip_md(cells[9]) == f"{coh['canary_mean']:.1f} / {coh['interview_mean']:.1f}"

    t2b_rows = tables[1][2:]
    assert len(t2b_rows) == 5
    mat = data["head_to_head_matrix_0to29"]
    for row_idx, id_a in enumerate(synth_mod.CORE_MATRIX_ORDER):
        cells = t2b_rows[row_idx]
        for col_idx, id_b in enumerate(synth_mod.CORE_MATRIX_ORDER):
            val = _strip_md(cells[col_idx + 1])
            if id_a == id_b:
                assert val == "0-30-0"
            else:
                h2h = mat[id_a][id_b]
                assert val == f"{h2h['raw']['wtl']} / {h2h['luck_adjusted']['wtl']}"

    t2c_rows = tables[2][2:]
    assert len(t2c_rows) == len(data["head_to_head_0to29_core"])
    for cells, h2h in zip(t2c_rows, data["head_to_head_0to29_core"]):
        rw = h2h["raw"]
        lw = h2h["luck_adjusted"]
        assert _strip_md(cells[1]) == f"{rw['wtl']} ({100.0 * rw['win_rate']:.1f}%)"
        assert _strip_md(cells[2]) == f"{rw['diff']:+.3f} +/- {rw['diff_ci']:.3f}"
        assert _strip_md(cells[3]) == f"{rw['sign_flip_p_two_sided']:.4f}"
        assert _strip_md(cells[4]) == f"{lw['wtl']} ({100.0 * lw['win_rate']:.1f}%)"
        assert _strip_md(cells[5]) == f"{lw['diff']:+.3f} +/- {lw['diff_ci']:.3f}"
        assert _strip_md(cells[6]) == f"{lw['sign_flip_p_two_sided']:.4f}"

    t3a_rows = tables[3][2:]
    assert len(t3a_rows) == 2
    assert _strip_md(t3a_rows[0][0]) == "hard"
    assert _strip_md(t3a_rows[1][0]) == "medium"

    ext_c = data["extension_comparison"]["cohorts"]
    t5a_expected = [
        ext_c["carbon_g1_ext2"],
        ext_c["carbon_pooled32"],
        ext_c["carbon_ext8"],
        ext_c["solver_ext8"],
        ext_c["heuristic_ext8"],
        ext_c["carbon_pooled38"],
        ext_c["solver_pooled38"],
        ext_c["heuristic_pooled38"],
        ext_c["solver_ext30to59"],
        ext_c["heuristic_ext30to59"],
    ]
    t5a_rows = tables[4][2:]
    assert len(t5a_rows) == len(t5a_expected)
    for cells, coh in zip(t5a_rows, t5a_expected):
        assert cells[0] == coh["label"]
        assert _strip_md(cells[2]) == f"{coh['raw_mean']:+.3f} +/- {coh['raw_ci']:.3f}"
        assert _strip_md(cells[4]) == f"{coh['luck_adjusted_mean']:+.3f} +/- {coh['luck_adjusted_ci']:.3f}"
        assert _strip_md(cells[6]) == f"{100.0 * coh['accuracy']:.1f}% ({coh['correct_count']}/{coh['n']})"

    t5b_rows = tables[5][2:]
    assert len(t5b_rows) == 8
    t5c_rows = tables[6][2:]
    assert len(t5c_rows) == 8
    for cells, row in zip(t5c_rows, data["extension_comparison"]["ext8_per_seed"]):
        assert int(cells[0]) == row["seed"]
        assert _strip_md(cells[1]) == row["source"]
        assert (
            _strip_md(cells[2])
            == f"{row['carbon_raw']:+.3f} / {row['carbon_luck_adjusted']:+.3f} (d{row['carbon_day']}, {row['carbon_p_accused']:.3f})"
        )
        assert math.isfinite(row["solver_luck_adjusted"]) and math.isfinite(row["heuristic_luck_adjusted"])
