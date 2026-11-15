from __future__ import annotations

import contextlib
import importlib.util
import io
import json
from pathlib import Path
import shutil
import sys
import time
import tokenize
from typing import Iterator

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts" / "audit_azure_numbers.py"
SELF_PATH = Path(__file__).resolve()


def _load_audit_module():
    spec = importlib.util.spec_from_file_location("audit_azure_numbers", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


audit = _load_audit_module()


def _stage_workspace(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"
    (ws / "docs" / "reports").mkdir(parents=True)
    (ws / "results" / "mole_strategies").mkdir(parents=True)
    (ws / "results" / "v16_social").mkdir(parents=True)

    for mp in sorted((ROOT / "docs" / "reports").glob("mole_*.md")):
        shutil.copy2(mp, ws / "docs" / "reports" / mp.name)
    for mp in sorted((ROOT / "docs" / "reports").glob("v16_*.md")):
        shutil.copy2(mp, ws / "docs" / "reports" / mp.name)
    for jp in sorted((ROOT / "results" / "mole_strategies").glob("*.json")):
        shutil.copy2(jp, ws / "results" / "mole_strategies" / jp.name)
    for jp in sorted((ROOT / "results" / "v16_social").glob("*.json")):
        shutil.copy2(jp, ws / "results" / "v16_social" / jp.name)

    shutil.copytree(
        ROOT / "results" / "v16_social" / "partial",
        ws / "results" / "v16_social" / "partial",
    )
    return ws


@pytest.fixture(scope="module")
def base_workspace(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return _stage_workspace(tmp_path_factory.mktemp("azure_audit_base"))


@contextlib.contextmanager
def _mutate_text(path: Path, new_text: str) -> Iterator[None]:
    orig = path.read_text(encoding="utf-8")
    path.write_text(new_text, encoding="utf-8")
    try:
        yield
    finally:
        path.write_text(orig, encoding="utf-8")


@contextlib.contextmanager
def _replace_in_file(path: Path, old: str, new: str) -> Iterator[None]:
    orig = path.read_text(encoding="utf-8")
    assert old in orig, f"expected substring {old!r} in {path}"
    path.write_text(orig.replace(old, new, 1), encoding="utf-8")
    try:
        yield
    finally:
        path.write_text(orig, encoding="utf-8")


@contextlib.contextmanager
def _temp_file(path: Path, content: str) -> Iterator[Path]:
    assert not path.exists()
    path.write_text(content, encoding="utf-8")
    try:
        yield path
    finally:
        path.unlink(missing_ok=True)


def test_real_repo_passes_audit_fast_keyless(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    for k in ("GOOGLE_API_KEY", "GEMINI_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY"):
        monkeypatch.setenv(k, "")

    t0 = time.perf_counter()
    rc_json = audit.main(["--root", str(ROOT), "--json"])
    elapsed = time.perf_counter() - t0
    out_json = capsys.readouterr().out
    payload = json.loads(out_json)

    assert rc_json == 0
    assert payload["passed"] is True
    assert elapsed < 5.0
    assert payload["elapsed_s"] < 5.0
    by_name = {r["name"]: r for r in payload["results"]}
    assert by_name["Azure Report & JSON Hygiene"]["status"] == "PASS"
    assert by_name["Mole Strategy JSON Schemas & Gates"]["status"] == "PASS"
    assert by_name["Mole Reports Ledger & Numerical Parity"]["status"] == "PASS"
    assert by_name["V1.6 Social Reports & Ledger Parity"]["status"] == "PASS"

    rc_txt = audit.main(["--root", str(ROOT)])
    out_txt = capsys.readouterr().out
    assert rc_txt == 0
    assert "SUMMARY: 4 PASS, 0 WARN, 0 FAIL" in out_txt


def test_hygiene_catches_missing_groups_and_solver_pct_claims(base_workspace: Path, tmp_path: Path) -> None:
    empty_ws = tmp_path / "empty"
    empty_ws.mkdir()
    assert audit.check_artifact_hygiene(empty_ws).status == "FAIL"

    p_mole = base_workspace / "docs" / "reports" / "mole_strategies_v14.md"
    with _mutate_text(p_mole, p_mole.read_text(encoding="utf-8") + "\nClaim: reaches 75" + "% of " + "solver on hard.\n"):
        res1 = audit.check_artifact_hygiene(base_workspace)
        assert res1.status == "FAIL"
        assert any("mole_strategies_v14.md" in d for d in res1.details)

    p_v16 = base_workspace / "docs" / "reports" / "v16_social_eval.md"
    with _mutate_text(
        p_v16,
        p_v16.read_text(encoding="utf-8") + "\nHeadline: 65% [24%, 98%] of the reference " + "solver's score.\n",
    ):
        res2 = audit.check_artifact_hygiene(base_workspace)
        assert res2.status == "FAIL"
        assert any("v16_social_eval.md" in d for d in res2.details)

    with _temp_file(
        base_workspace / "docs" / "reports" / "gap.md",
        "Headline: 65" + "% of " + "solver on hard.\n",
    ):
        assert audit.check_artifact_hygiene(base_workspace).status == "PASS"


def test_hygiene_catches_em_en_dashes_and_coauthor_trailer(base_workspace: Path) -> None:
    t_em = base_workspace / "docs" / "reports" / "mole_lever_ablation_v14.md"
    with _mutate_text(t_em, t_em.read_text(encoding="utf-8") + f"\nBad {chr(0x2014)} dash\n"):
        res_em = audit.check_artifact_hygiene(base_workspace)
        assert res_em.status == "FAIL"
        assert any("U+2014" in d for d in res_em.details)

    t_en = base_workspace / "results" / "mole_strategies" / "lever_ablation_v14.json"
    with _replace_in_file(t_en, "6600-6639", f"6600{chr(0x2013)}6639"):
        res_en = audit.check_artifact_hygiene(base_workspace)
        assert res_en.status == "FAIL"
        assert any("U+2013" in d for d in res_en.details)

    t_co = base_workspace / "docs" / "reports" / "mole_cross_model_transfer.md"
    trailer = "Co-Authored-" + "By: Bot <bot@example.com>"
    with _mutate_text(t_co, t_co.read_text(encoding="utf-8") + f"\n{trailer}\n"):
        res_co = audit.check_artifact_hygiene(base_workspace)
        assert res_co.status == "FAIL"
        assert any("trailer" in d for d in res_co.details)


def test_hygiene_catches_secrets_and_redacts_tokens(base_workspace: Path) -> None:
    fake_google = "AI" + "za" + "SySyntheticLeak" + ("Z" * 20)
    fake_sk = "s" + "k-proj-" + ("Q" * 24)
    fake_world_sec = "super_secret_judge_salt_999"
    target = base_workspace / "docs" / "reports" / "mole_transcript_mining.md"
    with _mutate_text(
        target,
        target.read_text(encoding="utf-8")
        + f"\ng={fake_google}\no={fake_sk}\nCANARY_WORLD_SECRET={fake_world_sec}\n",
    ):
        res = audit.check_artifact_hygiene(base_workspace)
        assert res.status == "FAIL"
        joined = "\n".join(res.details)
        assert "google_api_key" in joined
        assert "sk_api_key" in joined
        assert "CANARY_WORLD_SECRET" in joined
        assert fake_google not in joined
        assert fake_sk not in joined
        assert fake_world_sec not in joined


def test_mole_json_schemas_catch_nan_secret_keys_seed_hygiene_and_gates(base_workspace: Path) -> None:
    with _temp_file(
        base_workspace / "results" / "mole_strategies" / "extra_nan.json",
        '{"n_seeds": 30, "score": NaN}\n',
    ):
        res_nan = audit.check_mole_json_schemas(base_workspace)
        assert res_nan.status == "FAIL"
        assert any("NaN" in d or "non-finite" in d for d in res_nan.details)

    p_v14 = base_workspace / "results" / "mole_strategies" / "v14_fresh_6000_6199.json"
    obj_v14 = json.loads(p_v14.read_text(encoding="utf-8"))
    obj_v14["true_mole"] = "e07"
    obj_v14["seeds"][0] = 12
    obj_v14["strategies"]["default_v0"]["solver"]["accuracy"] = 0.50
    obj_v14["strategies"]["default_v0"]["baselines"]["do_nothing"]["max_abs_score"] = 0.05
    with _mutate_text(p_v14, json.dumps(obj_v14)):
        res_sec = audit.check_mole_json_schemas(base_workspace)
        assert res_sec.status == "FAIL"
        joined = "\n".join(res_sec.details)
        assert "true_mole" in joined
        assert "forbidden committed range" in joined
        assert "solver accuracy" in joined
        assert "do_nothing" in joined

    p_trf = base_workspace / "results" / "mole_strategies" / "cross_model_transfer.json"
    obj_trf = json.loads(p_trf.read_text(encoding="utf-8"))
    obj_trf["api_calls"] = 2
    obj_trf["catalog"]["default"]["strategy_json"]["default"]["leak"] = "omniscient_canary_snoop"
    with _mutate_text(p_trf, json.dumps(obj_trf)):
        res_dsl = audit.check_mole_json_schemas(base_workspace)
        assert res_dsl.status == "FAIL"
        joined_dsl = "\n".join(res_dsl.details)
        assert "api_calls" in joined_dsl
        assert "invalid MoleStrategy" in joined_dsl


def test_mole_report_ledger_and_table_parity_catches_drift(base_workspace: Path) -> None:
    with _replace_in_file(
        base_workspace / "docs" / "reports" / "mole_strategies_v14.md",
        "0.544 +/- 0.041",
        "0.599 +/- 0.041",
    ):
        assert audit.check_mole_ledger_and_report_parity(base_workspace).status == "FAIL"

    with _replace_in_file(
        base_workspace / "docs" / "reports" / "mole_lever_ablation_v14.md",
        "+0.586 +/- 0.084",
        "+0.611 +/- 0.084",
    ):
        assert audit.check_mole_ledger_and_report_parity(base_workspace).status == "FAIL"

    with _replace_in_file(
        base_workspace / "docs" / "reports" / "mole_cross_model_transfer.md",
        "+0.644 (100.0%)",
        "+0.700 (100.0%)",
    ):
        assert audit.check_mole_ledger_and_report_parity(base_workspace).status == "FAIL"

    with _replace_in_file(
        base_workspace / "docs" / "reports" / "mole_regret_portfolio_v14.md",
        "`0.865691`",
        "`0.765691`",
    ):
        assert audit.check_mole_ledger_and_report_parity(base_workspace).status == "FAIL"

    with _replace_in_file(
        base_workspace / "docs" / "reports" / "mole_transcript_mining.md",
        "`codex_medium_le3_share=0.753`",
        "`codex_medium_le3_share=0.500`",
    ):
        res5 = audit.check_mole_ledger_and_report_parity(base_workspace)
        assert res5.status == "FAIL"
        assert any("codex_medium_le3_share" in d for d in res5.details)

    with _replace_in_file(
        base_workspace / "docs" / "reports" / "mole_ladder_scale_analysis.md",
        "**0.783 -> 0.503** | **+0.280",
        "**0.783 -> 0.503** | **+0.350",
    ):
        res6 = audit.check_mole_ledger_and_report_parity(base_workspace)
        assert res6.status == "FAIL"
        assert any("P(mole) drop" in d for d in res6.details)

    j_v14 = base_workspace / "results" / "mole_strategies" / "v14_fresh_6000_6199.json"
    obj = json.loads(j_v14.read_text(encoding="utf-8"))
    obj["strategies"]["surgical_trap_shield"]["behavior_hash"] = "0" * 32
    with _mutate_text(j_v14, json.dumps(obj)):
        res7 = audit.check_mole_ledger_and_report_parity(base_workspace)
        assert res7.status == "FAIL"
        assert any("behavior_hash" in d for d in res7.details)


def test_v16_reports_and_ledgers_catch_drift(base_workspace: Path) -> None:
    with _replace_in_file(base_workspace / "docs" / "reports" / "v16_social_fairness_audit.md", "16/16", "15/16"):
        res1 = audit.check_v16_reports_and_ledgers(base_workspace)
        assert res1.status == "FAIL"
        assert any("v16_social_fairness_audit.md" in d for d in res1.details)

    with _replace_in_file(base_workspace / "docs" / "reports" / "v16_social_eval.md", "1.178 (117.8%)", "0.878 (87.8%)"):
        res2 = audit.check_v16_reports_and_ledgers(base_workspace)
        assert res2.status == "FAIL"
        assert any("ratio_vs_v0_control" in d for d in res2.details)

    with _replace_in_file(base_workspace / "docs" / "reports" / "v16_social_eval.md", "`117.8%`", "`105.0%`"):
        res2b = audit.check_v16_reports_and_ledgers(base_workspace)
        assert res2b.status == "FAIL"
        assert any("headline prose" in d for d in res2b.details)

    jp = base_workspace / "results" / "v16_social" / "partial_summary.json"
    ps = json.loads(jp.read_text(encoding="utf-8"))
    ps["per_variant_seed_table"][0]["gemini_score"] = 0.99
    with _mutate_text(jp, json.dumps(ps)):
        res3 = audit.check_v16_reports_and_ledgers(base_workspace)
        assert res3.status == "FAIL"
        assert any("episodes.jsonl" in d or "social_audit_report.json" in d for d in res3.details)


def test_forward_compatible_extra_mole_artifacts(base_workspace: Path) -> None:
    extra_json_content = json.dumps({
        "schema_version": "synthetic.v1",
        "n_seeds": 30,
        "seeds": list(range(6900, 6930)),
        "all_passed": True,
        "strategy_json": {
            "name": "synth_valid",
            "rules": [],
            "default": {"leak": "random_seeded", "frame": "random_peer"},
        },
    })
    h1 = chr(35)
    extra_md_content = (
        f"{h1} Synthetic Curve Report\n\n"
        "Backed by `results/mole_strategies/synthetic_curve.json`.\n\n"
        "| Strategy | Solver Acc |\n"
        "|---|---|\n"
        "| `synth_valid` | 0.950 |\n\n"
        "<!-- SYNTH_LEDGER_START -->\n"
        "```json\n"
        '{"n_seeds": 30, "solver_acc": 0.95}\n'
        "```\n"
        "<!-- SYNTH_LEDGER_END -->\n"
    )
    extra_json_path = base_workspace / "results" / "mole_strategies" / "synthetic_curve.json"
    extra_md_path = base_workspace / "docs" / "reports" / "mole_synthetic_curve.md"
    with _temp_file(extra_json_path, extra_json_content), _temp_file(extra_md_path, extra_md_content):
        results = audit.audit_azure_repo(base_workspace)
        assert all(r.status == "PASS" for r in results)

        with _replace_in_file(extra_md_path, "synthetic_curve.json", "missing_file.json"):
            res_missing = audit.check_mole_ledger_and_report_parity(base_workspace)
            assert res_missing.status == "FAIL"
            assert any("missing_file.json" in d for d in res_missing.details)


def test_source_files_have_zero_comments_dashes_and_trailers() -> None:
    coauthor = "co-authored-" + "by"
    hash_ch = chr(35)
    for path in (SCRIPT_PATH, SELF_PATH):
        src = path.read_text(encoding="utf-8")
        assert chr(0x2014) not in src, f"em dash in {path}"
        assert chr(0x2013) not in src, f"en dash in {path}"
        assert coauthor not in src.lower(), f"coauthor trailer in {path}"
        assert hash_ch not in src, f"hash char in {path}"
        tokens = list(tokenize.generate_tokens(io.StringIO(src).readline))
        comments = [t for t in tokens if t.type == tokenize.COMMENT]
        assert comments == [], f"tokenize.COMMENT found in {path}: {comments[:3]}"
