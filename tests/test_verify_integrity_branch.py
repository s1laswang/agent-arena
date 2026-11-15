from __future__ import annotations

import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import time
import tokenize

ROOT = Path(__file__).resolve().parents[1]
VERIFIER_PATH = ROOT / "scripts" / "verify_integrity_branch.py"
LEDGER_PATH = ROOT / "docs" / "reports" / "integrity_issue_ledger.md"
TEST_PATH = ROOT / "tests" / "test_verify_integrity_branch.py"


def _load_verifier():
    spec = importlib.util.spec_from_file_location("verify_integrity_branch", VERIFIER_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


vib = _load_verifier()


def _init_git_repo(repo: Path) -> None:
    repo.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    cfg = repo / ".git" / "config"
    cfg.write_text(
        cfg.read_text(encoding="utf-8") + "[user]\n\temail = test@fleet.local\n\tname = test-worker\n",
        encoding="utf-8",
    )


def _git_fast_commits(repo: Path, commits: tuple[tuple[str, dict[str, str]], ...]) -> None:
    _init_git_repo(repo)
    stream = bytearray()
    latest_files: dict[str, str] = {}
    for idx, (msg, files) in enumerate(commits, 1):
        latest_files.update(files)
        msg_b = msg.encode("utf-8")
        stream.extend(b"commit refs/heads/main\n")
        stream.extend(f"mark :{idx}\n".encode("ascii"))
        stream.extend(b"committer test-worker <test@fleet.local> 1700000000 +0000\n")
        stream.extend(f"data {len(msg_b)}\n".encode("ascii"))
        stream.extend(msg_b + b"\n")
        if idx > 1:
            stream.extend(f"from :{idx - 1}\n".encode("ascii"))
        for rel, content in sorted(latest_files.items()):
            raw = content.encode("utf-8")
            stream.extend(f"M 100644 inline {rel}\n".encode("utf-8"))
            stream.extend(f"data {len(raw)}\n".encode("ascii"))
            stream.extend(raw + b"\n")
        stream.extend(b"\n")
    subprocess.run(["git", "fast-import", "--quiet"], cwd=repo, input=bytes(stream), check=True)
    (repo / ".git" / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
    for rel, content in latest_files.items():
        fp = repo / rel
        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_text(content, encoding="utf-8")


def test_verify_integrity_branch_cli_passes(tmp_path: Path) -> None:
    out_json = tmp_path / "verify_report.json"
    t0 = time.perf_counter()
    rc = vib.main(["--unit-fast", "--json-out", str(out_json)])
    elapsed = time.perf_counter() - t0
    assert rc == 0
    assert elapsed < 60.0
    assert out_json.is_file()

    rep = json.loads(out_json.read_text(encoding="utf-8"))
    assert rep["all_passed"] is True
    assert rep["gates_passed"] == 6
    assert rep["gates_total"] == 6
    assert rep["live_llm_calls"] == 0

    g1 = rep["gates"]["gate_1_protected_paths"]
    assert g1["passed"] is True
    assert g1["protected_touched_count"] == 0
    assert g1["violations"] == []

    g2 = rep["gates"]["gate_2_squad_hygiene"]
    assert g2["passed"] is True
    assert g2["python_comment_tokens"] == 0
    assert g2["em_en_dash_count"] == 0
    assert g2["co_authored_by_commits"] == 0
    assert g2["diff_only_files_checked"] >= 0
    assert g2["full_files_checked"] >= len(vib.KNOWN_SQUAD_OWNED_FILES) - 1

    g3 = rep["gates"]["gate_3_zero_api_and_ast_safety"]
    assert g3["passed"] is True
    assert g3["hunter_live_llm_blocked"] is True
    assert g3["python_ast_files_checked"] >= 27

    g4 = rep["gates"]["gate_4_panel_honesty_and_ledger_sync"]
    assert g4["passed"] is True
    assert g4["c3_exploits_md_citations"]["passed"] is True
    assert g4["c3_exploits_md_citations"]["variant"] in (
        "pre_refresh",
        "post_craft_refresh",
        "post_gpt55_refresh",
    )
    assert g4["ledger_ids_verified"] == 20
    assert g4["ledger_tokens_verified"] == len(vib.REQUIRED_LEDGER_TOKENS)

    g5 = rep["gates"]["gate_5_env_and_detail_invariants"]
    assert g5["passed"] is True
    assert g5["tiers_version"] == "v1.4"
    assert g5["detail_parity_checks"] == 32
    assert g5["sidecar_simulation_passed"] is True

    g6 = rep["gates"]["gate_6_rehearsal_and_tamper_guard"]
    assert g6["passed"] is True
    assert g6["rehearsal_table_byte_equal"] is True
    assert g6["sample_harbor_trials_checked"] == 3
    assert g6["pre1bc_detail_normalization_ok"] is True
    assert g6["null_step_tamper_caught"] is True
    assert g6["committed_outcomes_ok"] is True
    assert g6["committed_files_checked"] >= 64
    assert g6["committed_episodes_checked"] >= 1061
    assert g6["valid_agent_stopped_episodes"] >= 2
    assert g6["gpt55_replayed_episodes"] >= 30

    summary_txt = vib.format_summary(rep)
    assert "OVERALL: PASS (6/6 gates passed" in summary_txt


def test_protected_path_and_disk_rule_detectors(tmp_path: Path) -> None:
    rules = vib.load_protected_rules(ROOT)
    for bad in (
        "canary/env.py",
        "canary/rules.py",
        "canary/world.py",
        "canary/reproduce.py",
        "canary/mcp_server.py",
        "canary/solver/policy.py",
        "harbor/build.py",
        "Makefile",
        "configs/default.yaml",
        "data/runs/committed/v1.4/opencode-gemini-4-carbon/hard/episodes.jsonl",
        "results/judge_table.md",
        ".github/protected-paths.txt",
        ".github/workflows/ci.yml",
    ):
        assert vib.is_protected_path(bad, rules) is not None

    for ok_rel in (
        "canary/redteam/gemini_mcp_hunter.py",
        "canary/redteam/harbor_sidecar_audit.py",
        "canary/redteam/tamper_guard.py",
        "scripts/integrity_game_and_gateway_audit.py",
        "scripts/verify_integrity_branch.py",
        "docs/reports/integrity_issue_ledger.md",
        "tests/test_verify_integrity_branch.py",
    ):
        assert vib.is_protected_path(ok_rel, rules) is None

    repo = tmp_path / "scratch_repo"
    _init_git_repo(repo)
    (repo / "canary").mkdir(parents=True)
    (repo / "canary" / "env.py").write_text("x = 1\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "base"], cwd=repo, check=True)

    (repo / "canary" / "env.py").write_text("x = 2\n", encoding="utf-8")
    (repo / "model.safetensors").write_bytes(b"weights")
    (repo / ".venv").mkdir()
    salt = repo / "data" / "worlds" / "judge" / "SALT"
    salt.parent.mkdir(parents=True)
    salt.write_text("secret\n", encoding="utf-8")
    subprocess.run(["git", "add", "canary/env.py", "model.safetensors"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "bad touch"], cwd=repo, check=True)

    g1 = vib.gate_1_protected_paths(repo, base_ref="HEAD~1", include_worktree=True)
    assert g1["passed"] is False
    assert g1["protected_touched_count"] == 1
    joined = "\n".join(g1["violations"])
    assert "canary/env.py" in joined
    assert "model.safetensors" in joined
    assert ".venv" in joined
    assert "SALT" in joined


def test_python_comment_dash_coauthor_and_secret_detectors() -> None:
    clean_src = 'x = "' + chr(35) + ' literal hash inside string"\ny = 42\n'
    assert vib.scan_python_comments(clean_src) == []

    bad_src = "x = 1  " + chr(35) + " trailing comment\n"
    found = vib.scan_python_comments(bad_src)
    assert len(found) == 1
    assert found[0][0] == 1

    em = chr(0x2014)
    en = chr(0x2013)
    coauth = "Co-Authored" + "-By: Bot <bot@example.com>"
    fake_gkey = "AI" + "za" + ("A" * 35)
    fake_sk = "s" + "k-proj-" + ("B" * 24)
    fake_hf = "hf" + "_" + ("C" * 30)
    fake_aws = "AK" + "IA" + ("D" * 16)

    issues = vib.scan_text_hygiene(
        f"a {em} b {en} c\n{coauth}\n{fake_gkey}\n{fake_sk}\n{fake_hf}\n{fake_aws}\n",
        "synthetic.md",
    )
    joined = "\n".join(issues)
    assert "em dash" in joined
    assert "en dash" in joined
    assert ("Co-Authored" + "-By") in joined
    assert "google_api_key" in joined
    assert "sk_api_key" in joined
    assert "hf_token" in joined
    assert "aws_access_key" in joined


def test_upstream_diff_only_hygiene_handles_preexisting_rehearsal_table_dash(tmp_path: Path) -> None:
    repo = tmp_path / "diff_repo"
    upstream_line = 'cells = ["' + chr(0x2013) + '"]\n'
    _git_fast_commits(
        repo,
        (
            ("upstream base", {"scripts/rehearsal_table.py": upstream_line + "x = 1\n"}),
            ("clean squad diff", {"scripts/rehearsal_table.py": upstream_line + "x = 2\ny = 3\n"}),
            ("bad dash diff", {"scripts/rehearsal_table.py": upstream_line + 'z = "' + chr(0x2014) + '"\n'}),
        ),
    )

    (repo / "scripts" / "rehearsal_table.py").write_text(upstream_line + "x = 2\ny = 3\n", encoding="utf-8")
    proc_clean = subprocess.run(
        ["git", "diff", "-U0", "HEAD~2...HEAD~1", "--", "scripts/rehearsal_table.py"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    )
    assert chr(0x2013) not in "\n".join(
        ln for ln in proc_clean.stdout.splitlines() if ln.startswith("+") and not ln.startswith("+++")
    )

    g2_bad = vib.gate_2_squad_hygiene(repo, base_ref="HEAD~2", include_worktree=False)
    assert g2_bad["passed"] is False
    assert any("added diff line contains em/en dash" in v for v in g2_bad["violations"])

    repo_clean = tmp_path / "diff_repo_clean"
    _git_fast_commits(
        repo_clean,
        (
            ("upstream base", {"scripts/rehearsal_table.py": upstream_line + "x = 1\n"}),
            ("clean squad diff", {"scripts/rehearsal_table.py": upstream_line + "x = 2\ny = 3\n"}),
        ),
    )
    g2_clean = vib.gate_2_squad_hygiene(repo_clean, base_ref="HEAD~1", include_worktree=False)
    assert g2_clean["passed"] is True
    assert g2_clean["em_en_dash_count"] == 0


def test_zero_api_ast_scanner_detectors() -> None:
    clean_code = (
        "from canary.llm.base import ToolCall\n"
        "from canary.llm import get_client\n"
        "c = get_client('stub')\n"
    )
    assert vib.scan_ast_zero_api(clean_code, "clean.py") == []

    bad_snippets = (
        "import openai\n",
        "import anthropic\n",
        "from google import genai\n",
        "import google.generativeai\n",
        "from canary.llm import gemini_client\n",
        "from canary.llm import get_client\nc = get_client('gemini:gemini-4-carbon')\n",
    )
    for idx, snippet in enumerate(bad_snippets):
        errs = vib.scan_ast_zero_api(snippet, f"bad_{idx}.py")
        assert len(errs) >= 1


def test_panel_fix_a_honesty_and_ledger_completeness_detectors(tmp_path: Path) -> None:
    good_md = (
        "Headline gap is raw 65% [24%, 98%] before luck-adjusted 72% [52%, 91%]. "
        "Seeds 0-29 are a post-hoc lock, not pre-registered. "
        "Separately, cf394894 pre-registered the gpt-5.5 run.\n"
    )
    assert vib.scan_markdown_honesty(good_md, "good.md") == []

    bad_prereg = "Benchmark seeds 0-29 were pre-registered prior to running carbon.\n"
    errs_prereg = vib.scan_markdown_honesty(bad_prereg, "bad_prereg.md")
    assert any("unnegated pre-registration" in e for e in errs_prereg)

    bad_order = "Headline ratio is luck-adjusted 72% [52%, 91%] (raw 65% [24%, 98%]).\n"
    errs_order = vib.scan_markdown_honesty(bad_order, "bad_order.md")
    assert any("without leading raw 65% first" in e for e in errs_order)

    repo = tmp_path / "ledger_repo"
    _git_fast_commits(repo, (("init", {"docs/reports/integrity_issue_ledger.md": "incomplete ledger\n"}),))

    g4_bad = vib.gate_4_panel_honesty_and_ledger_sync(repo, base_ref="HEAD", include_worktree=False)
    assert g4_bad["passed"] is False
    assert any("replay-ladder-showcase" in v for v in g4_bad["violations"])
    assert any("INT-LEDGER-01" in v for v in g4_bad["violations"])


def test_c3_exploits_md_citations_and_cross_squad_merge_compatibility(tmp_path: Path) -> None:
    real_c3 = vib.C3_exploits_md_citations(ROOT)
    assert real_c3["passed"] is True
    assert real_c3["variant"] in ("pre_refresh", "post_craft_refresh", "post_gpt55_refresh")

    exploits_src = (ROOT / "docs" / "EXPLOITS.md").read_text(encoding="utf-8")

    pre_repo = tmp_path / "pre_refresh_repo"
    (pre_repo / "docs").mkdir(parents=True)
    pre_txt = (
        exploits_src.replace("1,021 of 1,031", "989 of 999")
        .replace("1,051 of 1,061", "989 of 999")
        .replace("51,814", "49,549")
        .replace("53,889", "49,549")
        .replace("all 61 committed Harbor trials", "all 31 committed Harbor trials")
        .replace("61 of 61 committed Harbor trials", "31 of 31 committed Harbor trials")
    )
    (pre_repo / "docs" / "EXPLOITS.md").write_text(pre_txt, encoding="utf-8")
    c3_pre = vib.C3_exploits_md_citations(pre_repo)
    assert c3_pre["passed"] is True
    assert c3_pre["variant"] == "pre_refresh"

    post_repo = tmp_path / "post_craft_repo"
    (post_repo / "docs").mkdir(parents=True)
    post_txt = (
        pre_txt.replace("989 of 999", "1,021 of 1,031")
        .replace("49,549", "51,814")
        .replace("all 31 committed Harbor trials", "all 61 committed Harbor trials")
        .replace("31 of 31 committed Harbor trials", "61 of 61 committed Harbor trials")
    )
    (post_repo / "docs" / "EXPLOITS.md").write_text(post_txt, encoding="utf-8")
    c3_post = vib.C3_exploits_md_citations(post_repo)
    assert c3_post["passed"] is True
    assert c3_post["variant"] == "post_craft_refresh"

    gpt55_repo = tmp_path / "post_gpt55_repo"
    (gpt55_repo / "docs").mkdir(parents=True)
    gpt55_txt = post_txt.replace("1,021 of 1,031", "1,051 of 1,061").replace("51,814", "53,889")
    (gpt55_repo / "docs" / "EXPLOITS.md").write_text(gpt55_txt, encoding="utf-8")
    c3_gpt55 = vib.C3_exploits_md_citations(gpt55_repo)
    assert c3_gpt55["passed"] is True
    assert c3_gpt55["variant"] == "post_gpt55_refresh"

    bad_repo = tmp_path / "bad_exploits_repo"
    (bad_repo / "docs").mkdir(parents=True)
    (bad_repo / "docs" / "EXPLOITS.md").write_text("replay: 500 of 500 and 10,000 steps\n", encoding="utf-8")
    c3_bad = vib.C3_exploits_md_citations(bad_repo)
    assert c3_bad["passed"] is False

    merge_repo = tmp_path / "cross_squad_merge"
    _git_fast_commits(
        merge_repo,
        (
            (
                "base",
                {
                    "docs/EXPLOITS.md": post_txt,
                    "docs/reports/integrity_issue_ledger.md": LEDGER_PATH.read_text(encoding="utf-8"),
                },
            ),
            (
                "merge craft and frontier",
                {
                    "docs/SUBMISSION.md": "Craft doc " + chr(0x2014) + " prose\n",
                    "scripts/frontier_runner.py": "import openai\n" + chr(35) + " other squad comment\n",
                },
            ),
        ),
    )

    assert vib.gate_2_squad_hygiene(merge_repo, base_ref="HEAD~1", include_worktree=False)["passed"] is True
    assert vib.gate_3_zero_api_and_ast_safety(merge_repo, base_ref="HEAD~1", include_worktree=False)["passed"] is True
    assert vib.gate_4_panel_honesty_and_ledger_sync(merge_repo, base_ref="HEAD~1", include_worktree=False)["passed"] is True


def test_w9_and_w2_w3_files_strict_hygiene() -> None:
    w2_script = ROOT / "scripts" / "integrity_game_and_gateway_audit.py"
    w3_hunter = ROOT / "canary" / "redteam" / "gemini_mcp_hunter.py"
    for p in (VERIFIER_PATH, LEDGER_PATH, TEST_PATH):
        assert p.is_file()
        assert p.stat().st_size <= 130 * 1024

    ledger_low = LEDGER_PATH.read_text(encoding="utf-8").lower()
    assert "pre-reg" not in ledger_low
    assert "prereg" not in ledger_low

    for p in (VERIFIER_PATH, LEDGER_PATH, TEST_PATH, w2_script, w3_hunter):
        assert p.is_file()
        txt = p.read_text(encoding="utf-8")
        assert chr(0x2014) not in txt
        assert chr(0x2013) not in txt
        assert ("co-authored" + "-by") not in txt.lower()

    for py_path in (VERIFIER_PATH, TEST_PATH):
        src = py_path.read_text(encoding="utf-8")
        assert chr(35) not in src
        comments = [
            tok for tok in tokenize.generate_tokens(io.StringIO(src).readline) if tok.type == tokenize.COMMENT
        ]
        assert comments == []

    for py_path in (w2_script, w3_hunter):
        src = py_path.read_text(encoding="utf-8")
        assert vib.scan_python_comments(src) == []


def test_committed_episode_outcome_verifier_recognizes_opencode_clean_stop(tmp_path: Path) -> None:
    assert vib.is_integrity_squad_path("canary/redteam/anticheat.py") is False
    assert vib.is_integrity_squad_path("canary/redteam/tamper_guard.py") is True

    run_dir = tmp_path / "data" / "runs" / "committed" / "v1.4" / "opencode-synth" / "hard"
    run_dir.mkdir(parents=True)
    ep_file = run_dir / "episodes.jsonl"

    clean_stopped = {
        "tier": "hard",
        "seed": 0,
        "agent": "opencode:openai/gpt-5.5",
        "score": 0.0,
        "correct": False,
        "accused": None,
        "end_reason": "error",
        "meta": {
            "valid": True,
            "rc": 0,
            "note": "agent stopped without ending the episode (no accusation)",
        },
        "steps": [],
    }
    flagged_invalid = {
        "tier": "hard",
        "seed": 1,
        "agent": "opencode:openai/gpt-5.5",
        "score": 0.0,
        "correct": False,
        "accused": None,
        "end_reason": "error",
        "meta": {"valid": False, "rc": "timeout", "note": "infra:timeout"},
        "steps": [],
    }
    ep_file.write_text(
        json.dumps(clean_stopped) + "\n" + json.dumps(flagged_invalid) + "\n",
        encoding="utf-8",
    )
    res_ok = vib.verify_committed_episode_outcomes(tmp_path)
    assert res_ok["passed"] is True
    assert res_ok["files_checked"] == 1
    assert res_ok["episodes_checked"] == 2
    assert res_ok["valid_agent_stopped_episodes"] == 1

    bad_cases = (
        {**clean_stopped, "meta": {"valid": True, "rc": 1, "note": "agent stopped without ending the episode"}},
        {**clean_stopped, "meta": {"valid": True, "rc": "timeout", "note": "agent stopped without ending the episode"}},
        {**clean_stopped, "meta": {"valid": True, "rc": 0, "note": "unexpected crash"}},
        {**clean_stopped, "score": 0.5},
    )
    for idx, bad_ep in enumerate(bad_cases):
        ep_file.write_text(json.dumps(bad_ep) + "\n", encoding="utf-8")
        res_bad = vib.verify_committed_episode_outcomes(tmp_path)
        assert res_bad["passed"] is False, f"bad case {idx} unexpectedly passed"


def test_shallow_ci_checkout_and_uv_venv_fallback(tmp_path: Path) -> None:
    ci_repo = tmp_path / "shallow_ci_checkout"
    _init_git_repo(ci_repo)
    (ci_repo / "docs" / "reports").mkdir(parents=True)
    (ci_repo / "Makefile").write_text("test:\n\tpytest -q\n", encoding="utf-8")
    (ci_repo / "pyproject.toml").write_text("[project]\nname = 'canary'\n", encoding="utf-8")
    (ci_repo / ".gitignore").write_text(".venv/\nnode_modules/\n", encoding="utf-8")
    (ci_repo / "docs" / "EXPLOITS.md").write_text(
        (ROOT / "docs" / "EXPLOITS.md").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (ci_repo / "docs" / "reports" / "integrity_issue_ledger.md").write_text(
        LEDGER_PATH.read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    subprocess.run(["git", "add", "."], cwd=ci_repo, check=True)
    subprocess.run(["git", "commit", "-qm", "shallow merge commit"], cwd=ci_repo, check=True)
    subprocess.run(["git", "checkout", "-q", "--detach", "HEAD"], cwd=ci_repo, check=True)

    (ci_repo / ".venv").mkdir()
    (ci_repo / ".venv" / "pyvenv.cfg").write_text("home = /usr/bin\n", encoding="utf-8")

    resolved_ref, is_fallback = vib.resolve_base_ref(ci_repo, "origin/justSilas")
    assert resolved_ref == "HEAD"
    assert is_fallback is True
    assert vib.gate_1_protected_paths(ci_repo)["passed"] is True
    assert vib.gate_2_squad_hygiene(ci_repo)["passed"] is True
    assert vib.gate_3_zero_api_and_ast_safety(ci_repo)["passed"] is True
    assert vib.gate_4_panel_honesty_and_ledger_sync(ci_repo)["passed"] is True

    subprocess.run(["git", "add", "-f", ".venv/pyvenv.cfg"], cwd=ci_repo, check=True)
    subprocess.run(["git", "commit", "-qm", "accidental tracked venv"], cwd=ci_repo, check=True)
    g1_tracked_venv = vib.gate_1_protected_paths(ci_repo)
    assert g1_tracked_venv["passed"] is False
    assert any(".venv" in v for v in g1_tracked_venv["violations"])
