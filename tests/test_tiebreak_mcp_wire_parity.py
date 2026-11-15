from __future__ import annotations

import ast
import io
import json
import os
from pathlib import Path
import re
import shutil
import sys
import time
import tokenize
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from canary.env import Env
from canary.eval import run_episode
from canary.text.template import TemplateProvider
from canary.types import Step
import scripts.tiebreak_mcp_wire_parity as mwp
import scripts.verify_tiebreak_submission as gate

SCRIPT_PATH = REPO_ROOT / "scripts" / "tiebreak_mcp_wire_parity.py"
SUMMARY_PATH = REPO_ROOT / "results" / "tiebreak" / "mcp_wire_parity" / "mcp_wire_parity_summary.json"
REPORT_PATH = REPO_ROOT / "docs" / "reports" / "tiebreak_mcp_wire_parity.md"
SELF_PATH = Path(__file__).resolve()


@pytest.fixture(scope="module")
def loaded_bundles() -> dict[str, Any]:
    return {
        pid: mwp.load_direct_and_wire_factories(pid, repo_root=REPO_ROOT)
        for pid in mwp.POLICY_ORDER
    }


def test_source_hygiene_and_strict_ast_inference_isolation(monkeypatch: pytest.MonkeyPatch) -> None:
    hash_char = chr(35)
    em_dash = chr(0x2014)
    en_dash = chr(0x2013)
    unicode_minus = chr(0x2212)
    forbidden_pkgs = {"torch", "transformers", "subprocess"}

    for py_path in (SCRIPT_PATH, SELF_PATH):
        errs = mwp.check_python_source_hygiene(py_path, run_tokenize=True)
        assert errs == [], errs
        src = py_path.read_text(encoding="utf-8")
        toks = list(tokenize.generate_tokens(io.StringIO(src).readline))
        assert not [t for t in toks if t.type == tokenize.COMMENT]
        assert hash_char not in src
        assert em_dash not in src
        assert en_dash not in src
        assert unicode_minus not in src
        assert src.isascii()

        tree = ast.parse(src, filename=str(py_path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    root_mod = alias.name.split(".")[0]
                    if py_path == SCRIPT_PATH:
                        assert root_mod not in forbidden_pkgs
                        assert not alias.name.startswith(("canary.solver", "canary.world"))
                    else:
                        assert root_mod not in {"torch", "transformers"}
            elif isinstance(node, ast.ImportFrom) and node.module:
                root_mod = node.module.split(".")[0]
                if py_path == SCRIPT_PATH:
                    assert root_mod not in forbidden_pkgs
                    assert not node.module.startswith(("canary.solver", "canary.world"))
                    if node.module == "canary":
                        imported = {a.name for a in node.names}
                        assert "solver" not in imported
                        assert "world" not in imported
                else:
                    assert root_mod not in {"torch", "transformers"}

    assert "torch" not in sys.modules
    assert "transformers" not in sys.modules

    monkeypatch.chdir(REPO_ROOT)
    ast_res = gate.check_ast_inference_isolation(
        root=REPO_ROOT,
        extra_paths=[Path("scripts/tiebreak_mcp_wire_parity.py")],
        strict=True,
    )
    assert ast_res.passed is True, ast_res.errors
    assert ast_res.errors == []
    assert "scripts/tiebreak_mcp_wire_parity.py" in ast_res.metrics["modules_checked"]
    checked_classes = set(ast_res.metrics["policy_classes_checked"])
    for cls_name in (
        "WireCompactLinearDAggerPolicy",
        "WireTinyMLPPolicy",
        "WireScalingLogisticPolicy",
        "WireEmpiricalBayesPolicy",
    ):
        assert f"scripts/tiebreak_mcp_wire_parity.py:{cls_name}" in checked_classes


def test_committed_summary_and_markdown_exact_check_fast(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert SUMMARY_PATH.is_file()
    assert REPORT_PATH.is_file()
    assert not (SUMMARY_PATH.parent / "summary.json").exists()
    assert not (SUMMARY_PATH.parent / "table.md").exists()
    assert mwp.MAX_CHECK_SECONDS >= 10.0

    t0 = time.perf_counter()
    rc = mwp.main(["--check"])
    dt = time.perf_counter() - t0
    assert rc == 0
    assert dt < mwp.MAX_CHECK_SECONDS
    out_human = capsys.readouterr().out
    assert "OK: verified" in out_human
    assert "360/360 MCP wire parity" in out_human

    rc_json = mwp.main(["--check", "--json"])
    assert rc_json == 0
    verdict = json.loads(capsys.readouterr().out)
    assert verdict["passed"] is True
    assert verdict["errors"] == []
    assert verdict["elapsed_seconds"] <= mwp.MAX_CHECK_SECONDS

    ver_art = mwp.verify_artifacts(root=REPO_ROOT)
    assert ver_art["passed"] is True
    assert ver_art["errors"] == []

    raw_json = SUMMARY_PATH.read_text(encoding="utf-8")
    summary = json.loads(raw_json)
    md_text = REPORT_PATH.read_text(encoding="utf-8")
    assert md_text == mwp.render_markdown_report(summary)
    assert mwp._scan_json_for_judge_numbers(summary, raw_json) == []
    for tok_match in re.finditer(r"\b\d+\b", raw_json):
        assert int(tok_match.group(0)) < 900_000

    assert summary["world_secret_tag"] == "sha256:ebf2f09716cf76d3"
    assert summary["heldout_seed_range"] == "800000..800029"
    assert summary["episodes_per_policy"] == 90
    assert summary["eval_seeds_per_tier"] == 30
    assert summary["public_mcp_tools"] == list(mwp.PUBLIC_MCP_TOOLS)
    assert len(summary["public_mcp_tools"]) == 13
    assert summary["seed_isolation"]["judge_episodes_touched"] == 0
    assert summary["seed_isolation"]["dev_episodes_touched"] == 0
    assert summary["seed_isolation"]["train_episodes_in_heldout_eval"] == 0

    totals = summary["totals"]
    assert totals["policies_audited"] == 4
    assert totals["total_paired_episodes"] == 360
    assert totals["tool_sequence_exact_matches"] == 360
    assert totals["wire_observation_exact_matches"] == 360
    assert totals["reward_bit_identical_matches"] == 360
    assert totals["terminal_verdict_exact_matches"] == 360
    assert totals["exact_13_public_tools_handshakes"] == 360
    assert totals["wire_hidden_key_leaks"] == 0
    assert totals["shared_reference_violations"] == 0
    assert totals["max_abs_score_diff"] == 0.0

    for pid in mwp.POLICY_ORDER:
        pb = summary["policies"][pid]
        assert pb["n"] == 90
        assert pb["is_open_weight_llm"] is False
        assert pb["parity"]["tool_sequence_exact_matches"] == 90
        assert pb["parity"]["reward_bit_identical_matches"] == 90
        assert pb["parity"]["direct_traces_sha256"] == pb["parity"]["wire_traces_sha256"]


def test_shallow_ci_and_git_free_archive_root_flags(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    no_git_root = tmp_path / "unzipped_judge_export"
    for rel in (
        "results/tiebreak/mcp_wire_parity/mcp_wire_parity_summary.json",
        "docs/reports/tiebreak_mcp_wire_parity.md",
        "results/tiebreak/experiment_ledger.json",
        "scripts/tiebreak_mcp_wire_parity.py",
    ):
        dst = no_git_root / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(REPO_ROOT / rel, dst)

    assert not (no_git_root / ".git").exists()

    monkeypatch.setenv("PATH", "")
    assert mwp.main(["--check", "--repo-root", str(no_git_root)]) == 0
    _ = capsys.readouterr()
    assert mwp.main(["--check", "--root", str(no_git_root)]) == 0
    _ = capsys.readouterr()

    shallow_root = tmp_path / "shallow_detached_ci"
    shutil.copytree(no_git_root, shallow_root)
    (shallow_root / ".git").mkdir()
    (shallow_root / ".git" / "shallow").write_text("f3ec5361\n", encoding="utf-8")
    (shallow_root / ".git" / "HEAD").write_text("f3ec5361\n", encoding="utf-8")
    assert mwp.main(["--check", "--repo-root", str(shallow_root)]) == 0
    _ = capsys.readouterr()

    forbidden_sib = shallow_root / "results" / "tiebreak" / "mcp_wire_parity" / "summary.json"
    forbidden_sib.write_text("{}\n", encoding="utf-8")
    assert mwp.main(["--check", "--repo-root", str(shallow_root)]) == 1
    err_sib = capsys.readouterr().err
    assert "forbidden sibling" in err_sib
    forbidden_sib.unlink()

    md_copy = shallow_root / "docs" / "reports" / "tiebreak_mcp_wire_parity.md"
    orig_md = md_copy.read_text(encoding="utf-8")
    md_copy.write_text(orig_md.replace("360/360", "359/360", 1), encoding="utf-8")
    assert mwp.main(["--check", "--repo-root", str(shallow_root)]) == 1
    err_md = capsys.readouterr().err
    assert "out of sync" in err_md
    md_copy.write_text(orig_md + "\nForbidden " + chr(0x2014) + " dash\n", encoding="utf-8")
    assert mwp.main(["--check", "--repo-root", str(shallow_root)]) == 1
    assert "em dash" in capsys.readouterr().err
    md_copy.write_text(orig_md, encoding="utf-8")

    json_copy = shallow_root / "results" / "tiebreak" / "mcp_wire_parity" / "mcp_wire_parity_summary.json"
    bad_summary = json.loads(json_copy.read_text(encoding="utf-8"))
    bad_summary["rogue_judge_int"] = 900_000
    json_copy.write_text(json.dumps(bad_summary, indent=2) + "\n", encoding="utf-8")
    assert mwp.main(["--check", "--repo-root", str(shallow_root)]) == 1
    assert "900000" in capsys.readouterr().err


def test_live_mcp_wire_adapter_bit_identical_across_all_4_policies(
    loaded_bundles: dict[str, Any],
) -> None:
    provider = TemplateProvider()
    tiers_cycle = ("easy", "medium", "hard", "easy")
    seeds_cycle = (800_000, 800_001, 800_002, 800_003)

    with mwp._scoped_world_secret(mwp.HELDOUT_WORLD_SECRET):
        for pid, tier, seed in zip(mwp.POLICY_ORDER, tiers_cycle, seeds_cycle):
            direct_fac, wire_fac, meta = loaded_bundles[pid]
            assert meta["is_open_weight_llm"] is False

            ep_direct = run_episode(Env(tier, seed, text_provider=provider), direct_fac(seed))
            ep_wire, tel = mwp.run_mcp_wire_episode(
                Env(tier, seed, text_provider=provider),
                wire_fac(seed),
            )

            assert tel["exact_13_public_tools"] is True
            assert tuple(tel["advertised_tools"]) == mwp.PUBLIC_MCP_TOOLS
            assert tel["leak_violations"] == []
            assert tel["envelope_mismatches"] == 0
            assert tel["shared_reference_violations"] == 0
            assert tel["total_wire_bytes"] > 0

            seq_d = [(s.t, s.day, s.tool, s.args, s.result) for s in ep_direct.steps]
            seq_w = [(s.t, s.day, s.tool, s.args, s.result) for s in tel["wire_steps"]]
            assert seq_d == seq_w
            assert float(ep_direct.score).hex() == float(ep_wire.score).hex()
            assert ep_direct.accused == ep_wire.accused
            assert ep_direct.correct == ep_wire.correct
            assert ep_direct.final_day == ep_wire.final_day
            assert ep_direct.end_reason == ep_wire.end_reason


def test_wire_boundary_strips_tainted_attributes_and_rejects_non_json(
    loaded_bundles: dict[str, Any],
) -> None:
    provider = TemplateProvider()
    probe = mwp.run_redteam_taint_stripping_probe(loaded_bundles, provider)
    assert probe["all_passed"] is True
    assert probe["cases_tested"] == 12
    assert probe["cases_passed"] == 12
    assert probe["non_json_rejections_verified"] == 4

    tainted_step = Step(
        t=0,
        day=1,
        tool="status",
        args={},
        result={"ok": True, "data": {"day": 1, "V": 1.0}, "error": None, "_extra": "secret"},
    )
    ws = mwp.sanitize_mcp_step(tainted_step)
    assert isinstance(ws, mwp.WireStep)
    assert not hasattr(ws, "__dict__")
    assert set(ws.result.keys()) == {"ok", "data", "error"}

    with pytest.raises(AttributeError):
        ws.mole = "e00"

    for bad_val in (object(), {1, 2}, float("nan"), float("inf")):
        with pytest.raises((TypeError, ValueError)):
            mwp.sanitize_mcp_call("status", {"bad": bad_val})
        with pytest.raises((TypeError, ValueError)):
            mwp.sanitize_mcp_step(
                {"t": 0, "day": 1, "tool": "status", "args": {}, "result": {"ok": True, "data": {"x": bad_val}, "error": None}}
            )

    leaks = mwp.scan_wire_payload_for_leaks(
        {
            "ok": True,
            "data": {
                "mole": "e04",
                "items": [{"doc_id": "c1", "surfaced_day": 4, "variant": "A"}],
            },
            "error": None,
        },
        current_day=2,
        tool_name="check_leak_feed",
    )
    assert any("mole" in lk for lk in leaks)
    assert any("unsurfaced leak" in lk for lk in leaks)

    srv = mwp.MCPWireServerBoundary(Env("easy", 106_500, text_provider=provider))
    unknown_resp = json.loads(
        srv.handle_jsonrpc(json.dumps({"jsonrpc": "2.0", "id": 99, "method": "admin/ledger"}))
    )
    assert unknown_resp["id"] == 99
    assert unknown_resp["error"]["code"] == -32601
