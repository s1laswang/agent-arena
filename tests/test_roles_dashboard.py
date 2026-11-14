from __future__ import annotations

import io
import json
import re
import tokenize
from pathlib import Path

import pytest

from canary.gemini import roles_dashboard as rd


def _write_json(path: Path, obj: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2), encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")


@pytest.fixture()
def six_role_root(tmp_path: Path) -> Path:
    root = tmp_path / "workspace"

    _write_json(
        root / "results" / "gemini_roles" / "world_text" / "carbon-v14-seeds012" / "meta.json",
        {
            "role": "world_text",
            "subrole": "company_personas_chatter",
            "model_id": "gemini-4-carbon",
            "commit": "a1b2c3d4e5f601",
            "timestamp": "2026-11-14T14:00:00Z",
            "command": "PYTHONPATH=. python scripts/run_role_world_text.py --llm gemini:gemini-4-carbon",
            "n_worlds": 5,
            "truth_leak_violations": 0,
            "lint_violations": 0,
            "usage": {"in": 18500, "out": 4200, "thinking": 1500, "calls": 12, "cost_usd": 0.094},
        },
    )

    _write_json(
        root / "results" / "gemini_roles" / "adaptive_mole" / "arena-live-carbon-med012" / "meta.json",
        {
            "role": "adaptive_mole",
            "subrole": "live_arena_mole",
            "model_id": "gemini-4-carbon",
            "commit": "b2c3d4e5f6a702",
            "timestamp": "2026-11-14T14:05:00Z",
            "solver_accuracy": 1.0,
            "heuristic_mean": -0.82,
            "usage": {"in": 24100, "out": 3100, "calls": 18, "cost_usd": 0.0792},
        },
    )

    _write_json(
        root / "data" / "runs" / "committed" / "v1.4" / "gemini-4-carbon" / "medium-0-1" / "meta.json",
        {
            "agent": "gemini:gemini-4-carbon",
            "model": "gemini-4-carbon",
            "provider": "gemini",
            "git_sha": "c3d4e5f6a7b803",
            "tier": "medium",
            "tiers_version": "v1.4",
            "seeds": [0, 1],
            "usage": {"in": 95000, "out": 8400, "thinking": 6200, "cached_in": 40000, "calls": 34},
            "fake_env": False,
            "smoke": False,
        },
    )
    _write_jsonl(
        root / "data" / "runs" / "committed" / "v1.4" / "gemini-4-carbon" / "medium-0-1" / "episodes.jsonl",
        [
            {
                "tier": "medium",
                "seed": 0,
                "agent": "gemini:gemini-4-carbon",
                "score": 0.70,
                "correct": True,
                "accused": "e05",
                "final_day": 8,
                "end_reason": "accused",
                "meta": {"valid": True},
            },
            {
                "tier": "medium",
                "seed": 1,
                "agent": "gemini:gemini-4-carbon",
                "score": 0.44,
                "correct": True,
                "accused": "e02",
                "final_day": 13,
                "end_reason": "accused",
                "meta": {"valid": True},
            },
        ],
    )

    _write_json(
        root / "data" / "runs" / "committed" / "v1.4" / "gemini-4-carbon" / "hard-0" / "meta.json",
        {
            "role": "investigators",
            "model_id": "gemini-4-carbon",
            "commit": "c9d8e7f6a5b403",
            "tier": "hard",
            "tiers_version": "v1.4",
            "seeds": [0],
            "usage": {"in": 62000, "out": 5100, "thinking": 4900, "calls": 22, "cost_usd": 0.224},
            "fake_env": False,
            "smoke": False,
        },
    )
    _write_jsonl(
        root / "data" / "runs" / "committed" / "v1.4" / "gemini-4-carbon" / "hard-0" / "episodes.jsonl",
        [
            {
                "tier": "hard",
                "seed": 0,
                "agent": "gemini:gemini-4-carbon",
                "score": 0.52,
                "correct": True,
                "accused": "e11",
                "final_day": 10,
                "end_reason": "accused",
                "meta": {"valid": True},
            },
        ],
    )

    _write_json(
        root / "data" / "runs" / "committed" / "v1.4" / "reference" / "solver-medium" / "meta.json",
        {"agent": "solver", "model": None, "git_sha": "a54c8966b690cb4bb", "tier": "medium"},
    )
    _write_jsonl(
        root / "data" / "runs" / "committed" / "v1.4" / "reference" / "solver-medium" / "episodes.jsonl",
        [
            {"tier": "medium", "seed": 0, "agent": "solver", "score": 0.74, "correct": True, "accused": "e05", "final_day": 7},
            {"tier": "medium", "seed": 1, "agent": "solver", "score": 0.40, "correct": True, "accused": "e02", "final_day": 14},
        ],
    )
    _write_jsonl(
        root / "data" / "runs" / "committed" / "v1.4" / "reference" / "solver-hard" / "episodes.jsonl",
        [
            {"tier": "hard", "seed": 0, "agent": "solver", "score": 0.65, "correct": True, "accused": "e11", "final_day": 9},
        ],
    )

    _write_json(
        root / "results" / "gemini_roles" / "failure_analyst" / "carbon-longctx-corpus" / "meta.json",
        {
            "role": "failure_analyst",
            "model_id": "gemini-4-carbon",
            "commit": "d4e5f6a7b8c904",
            "n_episodes_packed": 28,
            "source": "llm",
            "verified_quotes_pct": 100.0,
            "usage": {"prompt_tokens": 310000, "out_tokens": 5200, "cost_usd": 0.672, "calls": 2},
        },
    )
    _write_json(
        root / "results" / "gemini_roles" / "failure_analyst" / "carbon-longctx-corpus" / "report.json",
        {"summary": "4 grounded failure modes", "clusters": [{"name": "premature_commit"}, {"name": "canary_overlap"}]},
    )

    _write_json(
        root / "results" / "gemini_roles" / "exploit_hunter" / "whitebox-swarm-carbon" / "meta.json",
        {
            "role": "exploit_hunter",
            "subrole": "whitebox_repo_swarm",
            "model_id": "gemini-4-carbon",
            "commit": "e5f6a7b8c9d005",
            "attempts": 4,
            "exploits": 0,
            "invariant_violations": 0,
            "usage": {"in": 420000, "out": 9100, "thinking": 14000, "cached": 380000, "calls": 28, "cost_usd": 0.359},
        },
    )

    _write_json(
        root / "results" / "gemini_roles" / "multimodal_evidence" / "visual-canary-scans-carbon" / "meta.json",
        {
            "role": "multimodal_evidence",
            "subrole": "visual_canary_scans",
            "model_id": "gemini-4-carbon",
            "commit": "f6a7b8c9d0e106",
            "n_images_read_by_model": 6,
            "variant_vision_accuracy": 1.0,
            "multimodal_mean_score": 0.72,
            "blind_ablation_mean_score": 0.0,
            "usage": {"in": 32000, "out": 2600, "calls": 8, "cost_usd": 0.09},
        },
    )

    return root


def test_six_roles_markdown_and_html(six_role_root: Path, tmp_path: Path) -> None:
    out_dir = tmp_path / "out_gemini"
    payload = rd.build_roles_dashboard(six_role_root, out_dir)

    md_path = out_dir / "ROLES_TABLE.md"
    html_path = out_dir / "roles_dashboard.html"
    assert md_path.is_file()
    assert html_path.is_file()

    md = md_path.read_text(encoding="utf-8")
    html_doc = html_path.read_text(encoding="utf-8")

    assert payload["totals"]["all_roles_verified"] is True
    assert payload["totals"]["n_roles_verified"] == 6
    assert payload["totals"]["n_runs"] == 7
    assert payload["totals"]["n_verified_runs"] == 7

    assert "| Role | Subrole | Model ID | Commit | Run Folder | Key Metric | Tokens (in/out) | Verified |" in md

    expected_commits = [
        "a1b2c3d4e5f601",
        "b2c3d4e5f6a702",
        "c3d4e5f6a7b803",
        "c9d8e7f6a5b403",
        "d4e5f6a7b8c904",
        "e5f6a7b8c9d005",
        "f6a7b8c9d0e106",
    ]
    expected_folders = [
        "results/gemini_roles/world_text/carbon-v14-seeds012",
        "results/gemini_roles/adaptive_mole/arena-live-carbon-med012",
        "data/runs/committed/v1.4/gemini-4-carbon/medium-0-1",
        "data/runs/committed/v1.4/gemini-4-carbon/hard-0",
        "results/gemini_roles/failure_analyst/carbon-longctx-corpus",
        "results/gemini_roles/exploit_hunter/whitebox-swarm-carbon",
        "results/gemini_roles/multimodal_evidence/visual-canary-scans-carbon",
    ]

    for role in rd.ROLES:
        assert role in md
        assert f'data-arch-role="{role}"' in html_doc
        assert f'data-role="{role}"' in html_doc

    for sha in expected_commits:
        assert f"`{sha}`" in md
        assert sha in html_doc

    for folder in expected_folders:
        assert f"`{folder}`" in md
        assert folder in html_doc

    assert "data/runs/committed/v1.4/reference" not in md
    assert "gemini-4-carbon" in md
    assert "gemini-4-carbon" in html_doc
    assert "SolverPolicy" in html_doc

    tiers = {t["tier"]: t for t in payload["paired_comparison"]["tiers"]}
    assert set(tiers) == {"medium", "hard"}
    assert tiers["medium"]["n"] == 2
    assert tiers["medium"]["carbon_mean"] == pytest.approx(0.57, abs=1e-4)
    assert tiers["medium"]["solver_mean"] == pytest.approx(0.57, abs=1e-4)
    assert tiers["medium"]["ratio"] == pytest.approx(1.0, abs=1e-4)
    assert tiers["hard"]["n"] == 1
    assert tiers["hard"]["carbon_mean"] == pytest.approx(0.52, abs=1e-4)
    assert tiers["hard"]["solver_mean"] == pytest.approx(0.65, abs=1e-4)
    assert tiers["hard"]["ratio"] == pytest.approx(0.8, abs=1e-4)

    assert html_doc.startswith("<!doctype html>")
    assert not re.search(r'(src|href)="https?://', html_doc)
    assert "@import" not in html_doc
    assert "fetch(" not in html_doc

    m = re.search(r'<script id="roles-data" type="application/json">(.*?)</script>', html_doc, re.S)
    assert m is not None
    embedded = json.loads(m.group(1))
    assert embedded["totals"]["n_roles_verified"] == 6


def test_html_escaping_and_xss_safety(tmp_path: Path) -> None:
    root = tmp_path / "xss_root"
    xss_payload = '<script>alert("xss")</script>" onmouseover="alert(1)'
    _write_json(
        root / "results" / "gemini_roles" / "world_text" / "xss-run" / "meta.json",
        {
            "role": "world_text",
            "subrole": f"sub_{xss_payload}",
            "model_id": "gemini-4-carbon",
            "commit": "abcdef123456",
            "key_metric": f"metric {xss_payload} & <img src=x onerror=alert(2)>",
            "command": f"echo {xss_payload}",
            "usage": {"in": 100, "out": 50, "cost_usd": 0.001},
        },
    )

    out_dir = tmp_path / "xss_out"
    rd.build_roles_dashboard(root, out_dir)
    html_doc = (out_dir / "roles_dashboard.html").read_text(encoding="utf-8")

    assert '<script>alert("xss")</script>' not in html_doc
    assert '" onmouseover="alert(1)' not in html_doc
    assert "<img src=x" not in html_doc
    assert "&lt;script&gt;alert(&quot;xss&quot;)&lt;/script&gt;" in html_doc


def test_unverified_flags_and_secret_redaction(tmp_path: Path) -> None:
    root = tmp_path / "sec_root"
    fake_api_key = "AIza" + "SyntheticKey9876543210"
    fake_env_secret = "GEMINI_API_KEY=" + "TopSecretValue12345"

    _write_json(
        root / "results" / "gemini_roles" / "exploit_hunter" / "leaky-run" / "meta.json",
        {
            "role": "exploit_hunter",
            "subrole": "leaky_test",
            "model_id": "gemini-4-carbon",
            "commit": "1234567890ab",
            "command": f"{fake_env_secret} python run.py --k {fake_api_key}",
            "usage": {"in": 500, "out": 120, "cost_usd": 0.01},
        },
    )
    _write_json(
        root / "results" / "gemini_roles" / "world_text" / "stub-run" / "meta.json",
        {
            "role": "world_text",
            "subrole": "stub_smoke",
            "model_id": "stub",
            "commit": "bad",
            "smoke": True,
            "usage": {"in": 0, "out": 0},
        },
    )

    out_dir = tmp_path / "sec_out"
    data = rd.build_roles_dashboard(root, out_dir)
    md = (out_dir / "ROLES_TABLE.md").read_text(encoding="utf-8")
    html_doc = (out_dir / "roles_dashboard.html").read_text(encoding="utf-8")

    assert data["totals"]["n_roles_verified"] == 0
    by_folder = {r["run_folder"]: r for r in data["runs"]}
    leaky = by_folder["results/gemini_roles/exploit_hunter/leaky-run"]
    assert leaky["verified"] is False
    assert "secret detected" in leaky["verified_reasons"]

    stub = by_folder["results/gemini_roles/world_text/stub-run"]
    assert stub["verified"] is False
    assert "non-gemini model" in stub["verified_reasons"]
    assert "invalid commit" in stub["verified_reasons"]
    assert "zero tokens" in stub["verified_reasons"]
    assert "smoke" in stub["verified_reasons"]

    for artifact in (md, html_doc, json.dumps(data)):
        assert fake_api_key not in artifact
        assert "TopSecretValue12345" not in artifact

    assert "GEMINI_API_KEY= GOOGLE_GENERATIVE_AI_API_KEY= PYTHONPATH=." in md
    assert "GEMINI_API_KEY= GOOGLE_GENERATIVE_AI_API_KEY= PYTHONPATH=." in html_doc


def test_empty_root_and_cli_modes(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    empty_root = tmp_path / "empty"
    empty_root.mkdir()
    out_dir = tmp_path / "cli_out"

    rc = rd.main(["--root", str(empty_root), "--out", str(out_dir)])
    assert rc == 0
    stdout_line = capsys.readouterr().out
    assert "0/6 roles verified" in stdout_line

    md = (out_dir / "ROLES_TABLE.md").read_text(encoding="utf-8")
    html_doc = (out_dir / "roles_dashboard.html").read_text(encoding="utf-8")
    for role in rd.ROLES:
        assert f"| {role} | pending |" in md
        assert role in html_doc

    rc_json = rd.main(["--root", str(empty_root), "--out", str(out_dir), "--json"])
    assert rc_json == 0
    parsed = json.loads(capsys.readouterr().out)
    assert parsed["totals"]["n_runs"] == 0
    assert len(parsed["roles"]) == 6


def test_nested_subruns_subroles_and_live_solver_fallback(tmp_path: Path) -> None:
    root = tmp_path / "subroles_root"

    _write_json(
        root / "results" / "gemini_roles" / "adaptive_mole" / "mole-forge-carbon-v14" / "meta.json",
        {
            "role": "adaptive_mole",
            "subrole": "mole_forge",
            "model_id": "gemini-4-carbon",
            "commit": "112233445566",
            "best_fitness": 0.415,
            "fresh_solver_accuracy": 0.90,
            "n_valid_llm_children": 6,
            "usage": {"in": 14000, "out": 2800},
        },
    )
    _write_json(
        root / "results" / "gemini_roles" / "adaptive_mole" / "carbon-vs-carbon-seed0" / "meta.json",
        {
            "role": "adaptive_mole",
            "subrole": "carbon_vs_carbon_clash",
            "model_id": "gemini-4-carbon",
            "commit": "223344556677",
            "investigator_score": 0.62,
            "solver_score": 0.74,
            "usage": {"in": 28000, "out": 4100},
        },
    )

    ladder_dir = root / "results" / "gemini_roles" / "investigators" / "thinking-ladder-carbon-med01"
    _write_json(
        ladder_dir / "meta.json",
        {
            "role": "investigators",
            "subrole": "thinking_level_ablation",
            "model_id": "gemini-4-carbon",
            "commit": "334455667788",
            "levels_summary": {"low": {"mean_score": 0.35}, "high": {"mean_score": 0.68}},
            "usage": {"in": 50000, "out": 6000, "thinking": 9000},
        },
    )
    _write_json(
        ladder_dir / "low" / "meta.json",
        {
            "agent": "gemini:gemini-4-carbon",
            "model": "gemini-4-carbon",
            "git_sha": "334455667788",
            "usage": {"in": 20000, "out": 2000},
        },
    )

    _write_json(
        root / "data" / "runs" / "committed" / "v1.4" / "gemini-4-carbon" / "medium-0" / "meta.json",
        {
            "role": "investigators",
            "model_id": "gemini-4-carbon",
            "commit": "445566778899",
            "tier": "medium",
            "seeds": [0],
            "usage": {"in": 31000, "out": 2900},
        },
    )
    _write_jsonl(
        root / "data" / "runs" / "committed" / "v1.4" / "gemini-4-carbon" / "medium-0" / "episodes.jsonl",
        [
            {
                "tier": "medium",
                "seed": 0,
                "agent": "gemini:gemini-4-carbon",
                "score": 0.74,
                "correct": True,
                "accused": "e05",
                "final_day": 7,
                "end_reason": "accused",
            }
        ],
    )

    out_dir = tmp_path / "subroles_out"
    data = rd.build_roles_dashboard(root, out_dir)

    inv_runs = [r for r in data["runs"] if r["role"] == "investigators"]
    assert len(inv_runs) == 2
    assert all(not r["run_folder"].endswith("/low") for r in inv_runs)

    mole_runs = [r for r in data["runs"] if r["role"] == "adaptive_mole"]
    assert len(mole_runs) == 2
    assert any("fitness 0.415" in r["key_metric"] for r in mole_runs)
    assert any("investigator +0.620 vs solver +0.740" in r["key_metric"] for r in mole_runs)
    assert all(r["usage"]["cost_usd"] > 0 for r in mole_runs)

    assert len(data["paired_comparison"]["seeds"]) == 1
    assert data["paired_comparison"]["seeds"][0]["solver_score"] > 0.0


def test_cli_module_execution(six_role_root: Path, tmp_path: Path) -> None:
    import os
    import subprocess
    import sys

    out_dir = tmp_path / "proc_out"
    env = {
        **os.environ,
        "GEMINI_API_KEY": "",
        "GOOGLE_GENERATIVE_AI_API_KEY": "",
        "PYTHONPATH": str(Path(rd.__file__).resolve().parents[2]),
    }
    proc = subprocess.run(
        [sys.executable, "-m", "canary.gemini.roles_dashboard", "--root", str(six_role_root), "--out", str(out_dir)],
        env=env,
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert proc.returncode == 0, proc.stderr
    assert "6/6 roles verified" in proc.stdout
    assert (out_dir / "ROLES_TABLE.md").is_file()
    assert (out_dir / "roles_dashboard.html").is_file()


def test_no_comments_or_em_dashes(six_role_root: Path, tmp_path: Path) -> None:
    src_files = [
        Path(rd.__file__).resolve(),
        Path(__file__).resolve(),
    ]
    c_open = "/" + "*"
    h_open = "<!" + "--"
    for fp in src_files:
        text = fp.read_text(encoding="utf-8")
        assert "\u2014" not in text
        assert "\u2013" not in text
        assert c_open not in text
        assert h_open not in text
        tokens = list(tokenize.generate_tokens(io.StringIO(text).readline))
        comment_tokens = [tok for tok in tokens if tok.type == tokenize.COMMENT]
        assert not comment_tokens, f"Found comment in {fp}: {comment_tokens}"

    out_dir = tmp_path / "clean_out"
    rd.build_roles_dashboard(six_role_root, out_dir)
    assert "\u2014" not in (out_dir / "ROLES_TABLE.md").read_text(encoding="utf-8")
    assert "\u2014" not in (out_dir / "roles_dashboard.html").read_text(encoding="utf-8")
