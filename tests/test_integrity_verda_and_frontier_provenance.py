from __future__ import annotations

import importlib.util
import io
import json
import shutil
import sys
import tokenize
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts" / "integrity_verda_and_frontier_provenance.py"
REPORT_PATH = ROOT / "docs" / "reports" / "integrity_verda_and_frontier_provenance.md"


def _load_audit_module():
    spec = importlib.util.spec_from_file_location("integrity_verda_and_frontier_provenance", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


audit_mod = _load_audit_module()


@pytest.fixture(scope="module")
def audit_result(tmp_path_factory):
    scratch = tmp_path_factory.mktemp("w7_scratch")
    return audit_mod.run_full_audit(root=ROOT, fast_tables=True, scratch_parent=scratch)


def test_verda_ws4_provenance_and_honest_readout(audit_result):
    assert audit_result["overall_ok"] is True
    v = audit_result["verda_ws4"]
    assert v["ok"] is True
    assert v["n_verda_run_dirs"] >= 5
    assert v["total_verda_episodes"] >= 450
    assert v["total_verda_steps"] >= 37696
    assert v["n_j4_run_dirs"] >= 3
    assert v["total_j4_episodes"] >= 19
    assert v["total_j4_steps"] >= 2337
    assert all(r["ok"] is True for r in v["verda_runs"])
    assert all(r["ok"] is True for r in v["j4_runs"])

    curves = v["curves"]
    assert curves["ok"] is True
    assert curves["n_curve_files"] >= 4
    assert curves["total_curve_steps"] >= 1816
    assert curves["early_s0_prefix_match"] is True

    td = v["tables_and_docs"]
    assert td["ok"] is True
    assert td["cross_run_shared_seed_pairs"] >= 249
    assert td["cross_run_identical_worlds"] == 0
    assert td["two_sample_required_proven"] is True
    assert td["pooling"]["j4_v1_raw_episodes"] == 17
    assert td["pooling"]["j4_v1_pooled_n"] == 12
    assert td["pooling"]["j4_v1_order_sensitive"] is True
    assert td["pooling"]["v3_4k_s0_pooled_n"] == 180
    assert td["pooling"]["v3_4k_s0_order_invariant"] is True
    assert td["n_ws4_tables"] >= 6
    assert td["committed_rows_checked"] >= 55
    assert td["delta_cells_checked"] >= 227
    assert td["whom_rows_checked"] >= 3
    assert td["pooled_v3_precision"] == {"correct": 15, "accused": 135}
    assert td["table_mismatches"] == []
    assert td["doc_checks"]["ws4_table_v3_all_4_bar_not_met"] is True
    assert td["doc_checks"]["readme_66a26f5c_honest_tiebreak"] is True
    assert td["doc_checks"]["fr8_doc_has_0400_correction"] is True
    assert td["doc_checks"]["fr8_doc_has_0445_readout_bar_not_met"] is True

    assert v["secret_scan"]["ok"] is True
    assert v["secret_scan"]["secret_hits"] == []


def test_frontier_replication_floor_bounds_and_growth_resilience(audit_result, tmp_path):
    r = audit_result["frontier_replication"]
    assert r["ok"] is True
    assert r["outside_default_anticheat_scope"] is True
    assert r["n_cohorts"] >= 1
    assert r["n_shards"] >= 3
    assert r["total_episodes"] >= 30
    assert r["primary_medium_episodes"] >= 30
    assert r["total_steps"] >= 1550
    assert r["total_pre_1bc3e281_detail_normalized"] >= 7
    assert r["total_transcripts"] >= 30
    assert r["duplicate_cohort_seeds"] == []
    assert r["unique_seeds_0_to_29"] is True
    assert all(s["ok"] is True for s in r["shards"])
    assert r["secret_scan"]["ok"] is True

    ps = r["paired_stats_vs_solver"]
    assert ps is not None
    assert ps["n"] == 30
    assert abs(ps["mean"] - 0.4343) < 1e-3
    assert abs(ps["solver_mean"] - 0.6450) < 1e-3

    rep_grow = tmp_path / "v1.4"
    shutil.copytree(
        ROOT / "results" / "frontier_replication" / "v1.4" / "opencode-gemini-3.5-flash" / "medium-s28",
        rep_grow / "opencode-gemini-3.5-flash" / "medium-s28",
    )
    sol_src = ROOT / "data" / "runs" / "committed" / "v1.4" / "reference" / "solver-hard-seeds30to59"
    ref_dst = rep_grow / "reference" / "solver-hard-sub"
    ref_dst.mkdir(parents=True)
    shutil.copy2(sol_src / "meta.json", ref_dst / "meta.json")
    first_sol_line = (sol_src / "episodes.jsonl").read_text(encoding="utf-8").splitlines()[0]
    (ref_dst / "episodes.jsonl").write_text(first_sol_line + "\n", encoding="utf-8")

    grown_res = audit_mod.audit_frontier_replication(
        root=ROOT,
        replication_dir=rep_grow,
        compute_paired_stats=False,
    )
    assert grown_res["ok"] is True
    assert grown_res["n_cohorts"] == 2
    assert grown_res["n_shards"] == 2
    assert grown_res["total_episodes"] == 2

    dup_dst = rep_grow / "reference" / "solver-hard-dup"
    shutil.copytree(ref_dst, dup_dst)
    dup_res = audit_mod.audit_frontier_replication(
        root=ROOT,
        replication_dir=rep_grow,
        compute_paired_stats=False,
    )
    assert dup_res["ok"] is False
    assert len(dup_res["duplicate_cohort_seeds"]) == 1


def test_g1_partial_extension_quota_and_gpt55_prereg(audit_result):
    g = audit_result["g1_partial_extension"]
    assert g["ok"] is True

    ext_r = g["ext_replay"]
    assert ext_r["ok"] is True
    assert ext_r["n_episodes"] >= 2
    assert ext_r["n_steps"] >= 115
    assert ext_r["pre_1bc3e281_detail_normalized"] >= 1
    assert ext_r["meta_usage_matches_episodes"] is True

    sol_r = g["solver_30to59_replay"]
    assert sol_r["ok"] is True
    assert sol_r["n_episodes"] == 30
    assert sol_r["n_steps"] == 2150
    assert g["solver_meta_summary_ok"] is True
    assert g["accuse_md_ok"] is True
    assert g["tags_json_ok"] is True

    qe = g["quota_exclusions"]
    assert qe["ok"] is True
    assert qe["planned_count"] == 30
    assert qe["excluded_attempts_count"] >= 31
    assert qe["violations"] == []

    pt = g["paired_tables"]
    assert pt["ext30to59"]["exact_canonical_match"] is True
    assert pt["ext30to59"]["md_exact_match"] is True
    assert pt["pooled0to59"]["numeric_exact_match"] is True
    assert pt["pooled0to59"]["n_rows"] == 17
    assert pt["pooled0to59"]["md_exact_match_pre_e379c38c_label"] is True

    gp = g["gpt55_prereg_and_panel_fix_a"]
    assert gp["ok"] is True
    assert gp["panel_fix_a_raw_before_luck"] is True
    assert gp["seeds_0_29_post_hoc_lock_disclosed"] is True
    assert gp["gpt55_prereg_doc_ok"] is True
    assert gp["afterquery_final_58716742_ok"] is True
    assert gp["provider_routing_ok"] is True
    assert gp["runner_spend_and_stop_flags_ok"] is True
    assert gp["openai_key_isolated_from_mcp_server"] is True
    assert g["secret_scan"]["ok"] is True


def test_pre_1bc3e281_error_detail_normalization_and_tamper_controls(audit_result):
    c = audit_result["tamper_positive_controls"]
    assert c["all_caught"] is True
    assert len(c["controls"]) == 8
    assert all(val is True for val in c["controls"].values())

    p_pre, was_pre = audit_mod._normalize_pre_1bc3e281_error_detail(
        False,
        {"detail": "missing required field: employee"},
        "invalid arguments",
        {"ok": False, "data": {}, "error": "invalid arguments"},
    )
    assert was_pre is True
    assert p_pre == {"ok": False, "data": {}, "error": "invalid arguments"}

    p_post, was_post = audit_mod._normalize_pre_1bc3e281_error_detail(
        False,
        {"detail": "missing required field: employee"},
        "invalid arguments",
        {"ok": False, "data": {"detail": "forged"}, "error": "invalid arguments"},
    )
    assert was_post is False
    assert p_post["data"] == {"detail": "missing required field: employee"}

    p_other, was_other = audit_mod._normalize_pre_1bc3e281_error_detail(
        False,
        {"detail": "other"},
        "episode over",
        {"ok": False, "data": {}, "error": "episode over"},
    )
    assert was_other is False
    assert p_other["data"] == {"detail": "other"}

    with pytest.raises(SystemExit):
        audit_mod.main(["--workers", "2", "--fast"])


def test_report_and_owned_files_hygiene(audit_result, tmp_path):
    assert REPORT_PATH.is_file()
    chk = audit_mod.check_report_md(REPORT_PATH)
    assert chk["ok"] is True, chk

    rendered = audit_mod.render_markdown_report(audit_result)
    tmp_rep = tmp_path / "rendered.md"
    tmp_rep.write_text(rendered, encoding="utf-8")
    assert audit_mod.check_report_md(tmp_rep)["ok"] is True

    em_dash = chr(0x2014)
    en_dash = chr(0x2013)
    minus_sign = chr(0x2212)
    hash_ch = chr(35)
    co_author = "-".join(("Co", "Authored", "By"))

    test_path = Path(__file__).resolve()
    for p in (SCRIPT_PATH, REPORT_PATH, test_path):
        txt = p.read_text(encoding="utf-8")
        assert em_dash not in txt, p
        assert en_dash not in txt, p
        assert minus_sign not in txt, p
        assert co_author.lower() not in txt.lower(), p

    rep_txt = REPORT_PATH.read_text(encoding="utf-8")
    assert rep_txt.index("65% [24%, 98%]") < rep_txt.index("72% [52%, 91%]")
    assert "post-hoc lock" in rep_txt
    assert "registered beforehand" in rep_txt
    assert "advance lock" in rep_txt
    assert "-".join(("pre", "reg")) not in rep_txt.lower()
    assert "".join(("pre", "reg")) not in rep_txt.lower()

    for py_path in (SCRIPT_PATH, test_path):
        src = py_path.read_text(encoding="utf-8")
        assert hash_ch not in src, py_path
        comments = [
            tok for tok in tokenize.generate_tokens(io.StringIO(src).readline)
            if tok.type == tokenize.COMMENT
        ]
        assert comments == [], (py_path, comments)


def test_secret_scanner_and_quota_validator_edge_cases(tmp_path):
    leak_file = tmp_path / "sample.txt"
    fake_oai = "sk-proj-" + ("A" * 24)
    fake_hf = "hf_" + ("B" * 24)
    leak_file.write_text(
        f"OPENAI={fake_oai}\nHF={fake_hf}\nHOST=127.0.0.1\nPUB=203.0.113.42\n",
        encoding="utf-8",
    )
    scan = audit_mod.scan_secrets_and_ips([leak_file], root=tmp_path)
    assert scan["ok"] is False
    kinds = {h["kind"] for h in scan["secret_hits"]}
    assert kinds == {"openai_api_key", "hf_token"}
    assert scan["unique_non_loopback_ips"] == ["203.0.113.42"]

    bad_meta = {
        "planned_seeds": list(range(30, 60)),
        "seeds": [34],
        "status": "INCOMPLETE: wrong status string",
        "invalid_episodes": [{"seed": 35}],
        "infra_invalid_attempts_excluded": [
            "malformed-line",
            "opencode-hard-99-031000: invalid: infra:provider_quota",
        ],
    }
    q = audit_mod.validate_g1_quota_exclusions(bad_meta, [{"seed": 34}, {"seed": 37}])
    assert q["ok"] is False
    v_kinds = {v["kind"] for v in q["violations"]}
    assert "meta_seeds_mismatch" in v_kinds
    assert "unexpected_invalid_episodes_in_committed" in v_kinds
    assert "status_missing_list_mismatch" in v_kinds
    assert "malformed_exclusion_entry" in v_kinds
    assert "exclusion_seed_outside_planned" in v_kinds


def test_deliverables_do_not_touch_protected_paths():
    hash_ch = chr(35)
    prot_file = ROOT / ".github" / "protected-paths.txt"
    prefixes = [
        line.strip()
        for line in prot_file.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith(hash_ch)
    ]
    owned = (
        "scripts/integrity_verda_and_frontier_provenance.py",
        "docs/reports/integrity_verda_and_frontier_provenance.md",
        "tests/test_integrity_verda_and_frontier_provenance.py",
    )
    for rel in owned:
        for pref in prefixes:
            if pref.endswith("/"):
                assert not rel.startswith(pref), (rel, pref)
            else:
                assert rel != pref, (rel, pref)

