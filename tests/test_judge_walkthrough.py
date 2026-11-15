from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import time
from pathlib import Path
from typing import Iterator

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts" / "verify_judge_walkthrough.py"
SELF_PATH = Path(__file__).resolve()
OPENCODE_TMP = Path("/tmp/opencode")
H = chr(35)
EM_DASH = chr(0x2014)
EN_DASH = chr(0x2013)


def _load_verifier():
    spec = importlib.util.spec_from_file_location("verify_judge_walkthrough", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


vjw = _load_verifier()


@pytest.fixture()
def clean_tmp() -> Iterator[Path]:
    OPENCODE_TMP.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=str(OPENCODE_TMP), prefix="test-judge-walkthrough-") as tmp_str:
        yield Path(tmp_str)


def _make_synthetic_repo(base: Path, overrides: dict[str, str | bytes | None]) -> Path:
    base.mkdir(parents=True, exist_ok=True)
    norm_overrides = {Path(k).as_posix(): v for k, v in overrides.items()}
    split_dirs: set[str] = {""}
    for rel_key in norm_overrides:
        parts = Path(rel_key).parts
        for depth in range(1, len(parts)):
            split_dirs.add(Path(*parts[:depth]).as_posix())

    def _populate_dir(rel_dir: str) -> None:
        src_dir = ROOT if not rel_dir else (ROOT / rel_dir)
        dst_dir = base if not rel_dir else (base / rel_dir)
        dst_dir.mkdir(parents=True, exist_ok=True)
        if not src_dir.is_dir():
            return
        for child in src_dir.iterdir():
            if not rel_dir and child.name == ".git":
                continue
            child_rel = child.name if not rel_dir else f"{rel_dir}/{child.name}"
            if child_rel in norm_overrides:
                continue
            if child_rel in split_dirs:
                _populate_dir(child_rel)
            else:
                (dst_dir / child.name).symlink_to(child)

    _populate_dir("")

    for rel_key, content in norm_overrides.items():
        target = base / rel_key
        if target.is_symlink() or target.is_file():
            target.unlink()
        if content is None:
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            target.write_bytes(content)
        else:
            target.write_text(content, encoding="utf-8")

    return base


def test_source_files_have_zero_hash_and_zero_em_en_dashes() -> None:
    for path in (SCRIPT_PATH, SELF_PATH):
        src = path.read_text(encoding="utf-8")
        assert H not in src, f"unexpected hash character in {path.name}"
        assert EM_DASH not in src, f"unexpected em dash in {path.name}"
        assert EN_DASH not in src, f"unexpected en dash in {path.name}"


def test_real_repo_passes_api_and_cli_under_two_seconds(capsys: pytest.CaptureFixture[str]) -> None:
    t0 = time.monotonic()
    rc_json = vjw.main(["--root", str(ROOT), "--json"])
    wall_s = time.monotonic() - t0
    payload = json.loads(capsys.readouterr().out)

    assert rc_json == 0
    assert payload["passed"] is True
    assert payload["elapsed_s"] < 5.0
    assert wall_s < 5.0
    assert [r["name"] for r in payload["results"]] == list(vjw.CHECK_NAMES)
    assert [r["status"] for r in payload["results"]] == ["PASS", "PASS", "PASS", "PASS"]
    assert payload["checks"] == payload["results"]

    alias_results = vjw.verify_repo(ROOT)
    assert [r.status for r in alias_results] == ["PASS", "PASS", "PASS", "PASS"]

    rc_text = vjw.main(["--root", str(ROOT)])
    out_text = capsys.readouterr().out
    assert rc_text == 0
    assert "SUMMARY: 4 PASS, 0 WARN, 0 FAIL" in out_text


def test_gitless_directory_full_pass(clean_tmp: Path, capsys: pytest.CaptureFixture[str]) -> None:
    gitless_repo = _make_synthetic_repo(clean_tmp / "gitless_ok", {})
    assert not (gitless_repo / ".git").exists()

    rc = vjw.main(["--root", str(gitless_repo), "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert payload["passed"] is True
    assert [r["status"] for r in payload["results"]] == ["PASS", "PASS", "PASS", "PASS"]


def test_pillar1_paired_table_and_unapproved_model_guard_fail(
    clean_tmp: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    paired_rel = "data/runs/committed/v1.4/paired_table_gemini.json"
    paired_rows = json.loads((ROOT / paired_rel).read_text(encoding="utf-8"))
    for row in paired_rows:
        if row.get("group") == "v1.4/opencode-gemini-4-carbon" and row.get("tier") == "hard":
            if "alternative" not in str(row.get("label", "")).lower():
                row["post_expected_ratio"] = 0.61
    repo_paired = _make_synthetic_repo(
        clean_tmp / "p1_paired",
        {paired_rel: json.dumps(paired_rows, indent=1) + "\n"},
    )
    rc = vjw.main(["--root", str(repo_paired), "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert rc == 1
    assert payload["passed"] is False
    assert payload["results"][0]["status"] == "FAIL"
    assert any("Pillar 1A row 1" in d for d in payload["results"][0]["details"])

    doc_rel = "docs/JUDGE-WALKTHROUGH.md"
    wt_mut = (ROOT / doc_rel).read_text(encoding="utf-8") + (
        "\nSecond model note: OpenCode + `gemini-3.5-flash` over MCP on hard.\n"
    )
    repo_unapproved = _make_synthetic_repo(clean_tmp / "p1_unapproved", {doc_rel: wt_mut})
    res_unapproved = vjw.check_pillar1_frontier_gap(repo_unapproved)
    assert res_unapproved.status == "FAIL"
    assert any("gap.md" in d and "gemini-3.5-flash" in d for d in res_unapproved.details)


def test_pillar1_oracle_guess_day1_rehearsal_and_gap_mutations_fail(clean_tmp: Path) -> None:
    oracle_rel = "results/oracle_range_v1.4.json"
    oracle_obj = json.loads((ROOT / oracle_rel).read_text(encoding="utf-8"))
    for r in oracle_obj["rows"]:
        if r.get("agent") == "solver" and r.get("tier") == "hard":
            r["k10"]["mean"] = 0.512
    res_oracle = vjw.check_pillar1_frontier_gap(
        _make_synthetic_repo(clean_tmp / "p1_oracle", {oracle_rel: json.dumps(oracle_obj)})
    )
    assert res_oracle.status == "FAIL"
    assert any("oracle_range_v1.4" in d for d in res_oracle.details)

    gd1_rel = "results/solver_range/guess_day1_hard_judge40.json"
    gd1_obj = json.loads((ROOT / gd1_rel).read_text(encoding="utf-8"))
    gd1_obj["p"]["0.5"] = -0.85
    res_gd1 = vjw.check_pillar1_frontier_gap(
        _make_synthetic_repo(clean_tmp / "p1_gd1", {gd1_rel: json.dumps(gd1_obj)})
    )
    assert res_gd1.status == "FAIL"
    assert any("guess_day1_hard_judge40" in d for d in res_gd1.details)

    reh_rel = "results/harbor/rehearsal-dry/TABLE.md"
    reh_mut = (ROOT / reh_rel).read_text(encoding="utf-8").replace("+0.467", "+0.501")
    res_reh = vjw.check_pillar1_frontier_gap(
        _make_synthetic_repo(clean_tmp / "p1_reh", {reh_rel: reh_mut})
    )
    assert res_reh.status == "FAIL"
    assert any("rehearsal-dry" in d for d in res_reh.details)

    gap_rel = "docs/reports/gap.md"
    gap_mut = (ROOT / gap_rel).read_text(encoding="utf-8").replace("84% [52%, 128%]", "79% [52%, 128%]")
    res_gap = vjw.check_pillar1_frontier_gap(
        _make_synthetic_repo(clean_tmp / "p1_gap", {gap_rel: gap_mut})
    )
    assert res_gap.status == "FAIL"
    assert any("gap.md" in d for d in res_gap.details)


def test_pillar2_additive_decomposition_and_rates_mutations_fail(
    clean_tmp: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    fa_rel = "results/failure_analysis_v1.4.json"
    fa_obj = json.loads((ROOT / fa_rel).read_text(encoding="utf-8"))
    fa_obj["summary"]["gap"]["penalty"] = 3.10
    repo_decomp = _make_synthetic_repo(clean_tmp / "p2_decomp", {fa_rel: json.dumps(fa_obj)})

    rc = vjw.main(["--root", str(repo_decomp), "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert rc == 1
    assert payload["passed"] is False
    assert payload["results"][1]["status"] == "FAIL"
    assert any("la_gap" in d or "Pillar 2A" in d for d in payload["results"][1]["details"])

    fa_rates = json.loads((ROOT / fa_rel).read_text(encoding="utf-8"))
    fa_rates["summary"]["opencode"]["interviews"] = 41.0
    res_rates = vjw.check_pillar2_failure_and_fairness(
        _make_synthetic_repo(clean_tmp / "p2_rates", {fa_rel: json.dumps(fa_rates)}),
        _fa_obj=fa_rates,
    )
    assert res_rates.status == "FAIL"
    assert any("interviews/episode" in d for d in res_rates.details)


def test_pillar2_wrong_seeds_and_failure_gallery_mutations_fail(clean_tmp: Path) -> None:
    fa_rel = "results/failure_analysis_v1.4.json"
    fa_wrong = json.loads((ROOT / fa_rel).read_text(encoding="utf-8"))
    fa_wrong["summary"]["wrong_detail"][3]["seed"] = 27
    res_wrong = vjw.check_pillar2_failure_and_fairness(
        _make_synthetic_repo(clean_tmp / "p2_wrong", {fa_rel: json.dumps(fa_wrong)}),
        _fa_obj=fa_wrong,
    )
    assert res_wrong.status == "FAIL"
    assert any("wrong_detail" in d for d in res_wrong.details)

    fg_rel = "docs/reports/failure_gallery.md"
    fg_mut = (ROOT / fg_rel).read_text(encoding="utf-8").replace(
        "Unexplained: 0.0e+00",
        "Unexplained: 1.5e-02",
    )
    res_fg = vjw.check_pillar2_failure_and_fairness(
        _make_synthetic_repo(clean_tmp / "p2_fg", {fg_rel: fg_mut})
    )
    assert res_fg.status == "FAIL"
    assert any("failure_gallery.md" in d for d in res_fg.details)


def test_pillar3_exploits_and_isolation_mutations_fail(
    clean_tmp: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    ex_rel = "results/anticheat/exploits.json"
    ex_obj = json.loads((ROOT / ex_rel).read_text(encoding="utf-8"))
    ex_obj["rows"] = ex_obj["rows"][:-1]
    repo_ex = _make_synthetic_repo(clean_tmp / "p3_ex", {ex_rel: json.dumps(ex_obj)})

    rc = vjw.main(["--root", str(repo_ex), "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert rc == 1
    assert payload["passed"] is False
    assert payload["results"][2]["status"] == "FAIL"
    assert any("exploits.json" in d for d in payload["results"][2]["details"])

    iso_rel = "results/harbor/c1-oracle/canary-hard-900000__dpQE5Fs/agent/isolation.txt"
    repo_iso = _make_synthetic_repo(
        clean_tmp / "p3_iso",
        {iso_rel: "ISOLATION FAIL: leaked CANARY_WORLD_SECRET\n"},
    )
    res_iso = vjw.check_pillar3_reward_integrity(repo_iso)
    assert res_iso.status == "FAIL"
    assert any("isolation.txt" in d or "harbor_consistency" in d for d in res_iso.details)


def test_pillar3_harbor_consistency_mutation_fails(clean_tmp: Path) -> None:
    rew_rel = "results/harbor/c1-do_nothing/canary-hard-900000__sKBg5SN/verifier/reward.txt"
    repo_hb = _make_synthetic_repo(clean_tmp / "p3_hb", {rew_rel: "0.99\n"})
    res_hb = vjw.check_pillar3_reward_integrity(repo_hb)
    assert res_hb.status == "FAIL"
    assert any("harbor_consistency" in d for d in res_hb.details)


def test_pillar3_swarm_corpus_and_judge_hunt_mutations_fail(clean_tmp: Path) -> None:
    sw_rel = "results/gemini/swarm.json"
    sw_obj = json.loads((ROOT / sw_rel).read_text(encoding="utf-8"))
    sw_obj["counts"]["exploits"] = 1
    res_sw = vjw.check_pillar3_reward_integrity(
        _make_synthetic_repo(clean_tmp / "p3_sw", {sw_rel: json.dumps(sw_obj)})
    )
    assert res_sw.status == "FAIL"
    assert any("swarm" in d for d in res_sw.details)

    corp_rel = "results/anticheat/corpus_eval.txt"
    corp_mut = (ROOT / corp_rel).read_text(encoding="utf-8").replace("1161", "1100")
    res_corp = vjw.check_pillar3_reward_integrity(
        _make_synthetic_repo(clean_tmp / "p3_corp", {corp_rel: corp_mut})
    )
    assert res_corp.status == "FAIL"
    assert any("corpus_eval.txt" in d for d in res_corp.details)

    jh_rel = "results/anticheat/judge_hunt.md"
    jh_mut = (ROOT / jh_rel).read_text(encoding="utf-8").replace("| yes |", "| no |", 1)
    res_jh = vjw.check_pillar3_reward_integrity(
        _make_synthetic_repo(clean_tmp / "p3_jh", {jh_rel: jh_mut})
    )
    assert res_jh.status == "FAIL"
    assert any("judge_hunt.md" in d for d in res_jh.details)


def test_pillar4_tier_hashes_and_fresh_clone_mutations_fail(
    clean_tmp: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    rules_rel = "canary/rules.py"
    rules_mut = (ROOT / rules_rel).read_text(encoding="utf-8").replace(
        "KNOWN_V_MODE = True",
        "KNOWN_V_MODE = False",
        1,
    )
    repo_rules = _make_synthetic_repo(clean_tmp / "p4_rules", {rules_rel: rules_mut})
    rc = vjw.main(["--root", str(repo_rules), "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert rc == 1
    assert payload["passed"] is False
    assert payload["results"][3]["status"] == "FAIL"
    assert any("tier hash" in d for d in payload["results"][3]["details"])

    fc_rel = "results/fresh_clone/README.md"
    fc_mut = (ROOT / fc_rel).read_text(encoding="utf-8").replace("159 s, ok", "212 s, ok", 1)
    res_fc = vjw.check_pillar4_craft_and_commands(
        _make_synthetic_repo(clean_tmp / "p4_fc", {fc_rel: fc_mut})
    )
    assert res_fc.status == "FAIL"
    assert any("fresh_clone/README.md" in d for d in res_fc.details)


def test_pillar4_doc_commands_and_walkthrough_mutations_fail(clean_tmp: Path) -> None:
    doc_rel = "docs/JUDGE-WALKTHROUGH.md"
    orig_doc = (ROOT / doc_rel).read_text(encoding="utf-8")

    bad_cmd_doc = orig_doc + "\nRun `make nonexistent-walkthrough-target` to test.\n"
    res_cmd = vjw.check_pillar4_craft_and_commands(
        _make_synthetic_repo(clean_tmp / "p4_cmd", {doc_rel: bad_cmd_doc})
    )
    assert res_cmd.status == "FAIL"
    assert any("verify_doc_commands" in d for d in res_cmd.details)

    bad_link_doc = orig_doc + f"\nBroken [missing](does_not_exist.md) and dash {EM_DASH} here.\n"
    res_link = vjw.check_pillar4_craft_and_commands(
        _make_synthetic_repo(clean_tmp / "p4_link", {doc_rel: bad_link_doc})
    )
    assert res_link.status == "FAIL"
    assert any("does_not_exist.md" in d for d in res_link.details)
    assert any("dash" in d for d in res_link.details)
