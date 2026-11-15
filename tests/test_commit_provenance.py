from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Iterator

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts" / "verify_commit_provenance.py"
SELF_PATH = Path(__file__).resolve()
OPENCODE_TMP = Path("/tmp/opencode")

HASH_CHAR = chr(35)
EM_DASH = chr(0x2014)
EN_DASH = chr(0x2013)


def _load_provenance_module():
    spec = importlib.util.spec_from_file_location("verify_commit_provenance", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


prov = _load_provenance_module()


@pytest.fixture()
def clean_tmp() -> Iterator[Path]:
    OPENCODE_TMP.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=str(OPENCODE_TMP), prefix="test-commit-prov-") as tmp_dir:
        yield Path(tmp_dir)


def _write_files(repo: Path, files: dict[str, str]) -> None:
    repo.mkdir(parents=True, exist_ok=True)
    for rel, content in files.items():
        target = repo / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")


def _git_run(repo: Path, args: list[str]) -> str:
    proc = subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    return proc.stdout.strip()


def _build_synthetic_files(commit_sha: str) -> dict[str, str]:
    short_sha = commit_sha[:8]
    short7 = commit_sha[:7]

    oc_meta = {
        "agent": "opencode:google/gemini-4-carbon",
        "tier": "hard",
        "tiers_version": "v1.4",
        "seeds": [0, 1],
        "git_sha": commit_sha,
        "git_shas": [commit_sha],
    }
    oc_episodes = "\n".join(
        [
            json.dumps(
                {
                    "agent": "opencode:google/gemini-4-carbon",
                    "tier": "hard",
                    "seed": 0,
                    "score": 0.45,
                    "correct": True,
                    "accused": "e01",
                    "meta": {"valid": True},
                }
            ),
            json.dumps(
                {
                    "agent": "opencode:google/gemini-4-carbon",
                    "tier": "hard",
                    "seed": 1,
                    "score": 0.55,
                    "correct": True,
                    "accused": "e02",
                    "meta": {"valid": True},
                }
            ),
        ]
    ) + "\n"

    sv_meta = {
        "agent": "solver",
        "tier": "hard",
        "seeds": [0, 1],
        "git_sha": commit_sha,
    }
    sv_episodes = "\n".join(
        [
            json.dumps(
                {
                    "agent": "solver",
                    "tier": "hard",
                    "seed": 0,
                    "score": 0.65,
                    "correct": True,
                    "accused": "e01",
                }
            ),
            json.dumps(
                {
                    "agent": "solver",
                    "tier": "hard",
                    "seed": 1,
                    "score": 0.70,
                    "correct": True,
                    "accused": "e02",
                }
            ),
        ]
    ) + "\n"

    grok_meta = {
        "agent": "grok",
        "tier": "hard",
        "seeds": [900000],
        "source": "replayed external MCP transcripts",
    }
    grok_episodes = (
        json.dumps(
            {
                "agent": "grok",
                "tier": "hard",
                "seed": 900000,
                "score": 0.60,
                "correct": True,
                "accused": "e04",
            }
        )
        + "\n"
    )

    judge_table = "\n".join(
        [
            f"{HASH_CHAR} Canary judge table",
            "",
            "- seeds: 40 judge seeds per tier (900000..900039)",
            "- judge-world secret: statistical, sha256 fingerprint `baff236f997e` (statistical reproduction)",
            f"- git: `{commit_sha[:12]}`, generated 2026-11-15T00:01:25+0200, 21.4 s",
            "",
            f"{HASH_CHAR}{HASH_CHAR} hard (headline)",
            "",
            "Reported agent runs: v1.4 (current rules):",
            "",
            "| agent | kind | n | invalid | score +/- 95% CI | note |",
            "|---|---|---:|---|---:|---|",
            (
                "| opencode:google/gemini-4-carbon | reported | 2 | 0 | +0.500 +/- 0.100 | "
                f"replayed, NON-judge seeds, 2 seeds, git {short7} "
                "(data/runs/committed/v1.4/opencode-gemini-4-carbon/hard) |"
            ),
            (
                "| solver | reported | 2 | 0 | +0.675 +/- 0.050 | "
                f"replayed, NON-judge seeds, 2 seeds, git {short7} "
                "(data/runs/committed/v1.4/reference/solver-hard) |"
            ),
            (
                "| grok | reported | 1 | 0 | +0.600 +/- 0.000 | "
                "replayed, judge seeds, 1 seeds, git unknown "
                "(data/runs/committed/grok/hard) |"
            ),
        ]
    ) + "\n"

    fa_json = {
        "G": {
            "0": {"agent": "opencode:google/gemini-4-carbon", "score": 0.45},
            "1": {"agent": "opencode:google/gemini-4-carbon", "score": 0.55},
        },
        "I": {
            "0": {"agent": "gemini:gemini-4-carbon", "score": 0.50},
            "1": {"agent": "gemini:gemini-4-carbon", "score": 0.60},
        },
        "S": {
            "0": {"agent": "solver", "score": 0.65},
            "1": {"agent": "solver", "score": 0.70},
        },
        "summary": {
            "opencode": {"n": 2, "score": 0.50},
            "inproc": {"n": 2, "score": 0.55},
            "solver": {"n": 2, "score": 0.675},
            "gap": {"raw_gap": 0.35, "la_gap": 0.30},
        },
    }

    oracle_json = {
        "command": "uv run python scripts/oracle_range.py --builds 200",
        "secrets": "sha256('oracle-range:1:<b>')",
        "rows": [
            {
                "agent": "solver",
                "tier": "hard",
                "builds": 200,
                "k10": {"mean": 0.569, "sd": 0.094, "p5": 0.393, "p95": 0.678},
            },
            {
                "agent": "do_nothing",
                "tier": "hard",
                "builds": 200,
                "k10": {"mean": 0.0, "sd": 0.0, "p5": 0.0, "p95": 0.0},
            },
        ],
    }

    ladder_json = {
        "generated_at": "2026-11-15T01:00:00+0200",
        "git_sha": commit_sha,
        "episodes": 35,
        "rows": [
            {
                "model": "gemini-4-carbon",
                "level": "high",
                "tier": "hard",
                "n": 20,
                "tiers_versions": ["v1.4"],
                "launch_git_shas": [short7, commit_sha],
            },
            {
                "model": "gemini-4-carbon",
                "level": "default",
                "tier": "medium",
                "n": 15,
                "tiers_versions": ["v1.4 (imported dir)"],
                "launch_git_shas": [commit_sha],
            },
        ],
    }

    files: dict[str, str] = {
        "data/runs/committed/v1.4/opencode-gemini-4-carbon/hard/meta.json": json.dumps(oc_meta),
        "data/runs/committed/v1.4/opencode-gemini-4-carbon/hard/episodes.jsonl": oc_episodes,
        "data/runs/committed/v1.4/reference/solver-hard/meta.json": json.dumps(sv_meta),
        "data/runs/committed/v1.4/reference/solver-hard/episodes.jsonl": sv_episodes,
        "data/runs/committed/grok/hard/meta.json": json.dumps(grok_meta),
        "data/runs/committed/grok/hard/episodes.jsonl": grok_episodes,
        "results/judge_table.md": judge_table,
        "results/failure_analysis_v1.4.json": json.dumps(fa_json),
        "results/oracle_range_v1.4.json": json.dumps(oracle_json),
        "results/gemini/ladder.json": json.dumps(ladder_json),
        "README.md": (
            f"{HASH_CHAR} Canary\n"
            "Frozen rules: `TIERS_VERSION = \"v1.4\"` (`canary/rules.py`).\n"
        ),
        "JUDGE_QUICKSTART.md": (
            f"{HASH_CHAR} Quickstart\n"
            "Frozen rules: `TIERS_VERSION=\"v1.4\"` (SHA-256 prefix `a8f99c2537c91d72`).\n"
        ),
        "docs/JUDGE-WALKTHROUGH.md": (
            f"{HASH_CHAR} Walkthrough\n"
            f"Pre-registration recorded at commit `{short7}` (P0 fix `{short_sha}`).\n"
            "Verda/FR8 GPUs (`3bb74f5a`, `ac58df04`, `dbd083ca`, `f4378173`).\n"
        ),
        "docs/PEER-REVIEW-QA.md": (
            f"{HASH_CHAR} Peer Review QA\n"
            f"Tag `afterquery-final` at `{short_sha}`, latest integrity audit `{short7}` "
            "| Frozen rules: `TIERS_VERSION = \"v1.4\"` (SHA-256 `a8f99c2537c91d72`).\n"
        ),
        "docs/REPRODUCIBILITY.md": (
            f"{HASH_CHAR} Reproducibility\n"
            "| Command | Scope | Wall-Clock |\n"
            "|---|---|---:|\n"
            f"| `python scripts/audit_submission.py` | Frozen tier hashes (`a8f99c2537c91d72`, `8df71cf570bb48bc`) | `4 s` fresh clone on `{short_sha}` |\n"
        ),
        "docs/SUBMISSION.md": (
            f"{HASH_CHAR} Submission\n"
            f"Committed table (git `{commit_sha[:12]}`, secret fingerprint `893b837616b9`, "
            "run fingerprint `705484a74e3a`, prior fingerprints `6a38958f8096`, `b0fcc11725f3`, on secret `34ac6b625563`).\n"
        ),
        "results/fresh_clone/README.md": (
            f"{HASH_CHAR} Fresh clone\n"
            f"{HASH_CHAR}{HASH_CHAR} Linux x86_64 (`{short_sha}`)\n"
            "| run | commit | reproduce |\n"
            "|---|---|---:|\n"
            f"| linux_x86_64_justSilas_{short_sha}.log.txt | {short_sha} | 52 s |\n"
            "Secret sha256 fingerprint `996353b5a6c1`.\n"
        ),
        "docs/reports/gap.md": (
            f"{HASH_CHAR} Gap report\n"
            f"v1.4 headline (runs committed {short7}; pre-registered at commit {short7}).\n"
        ),
        "docs/reports/integrity.md": (
            f"{HASH_CHAR} Integrity report\n"
            f"Final hunt on `{short_sha}` (tiers v1.4 @ {short7}, 424 attacks on {short_sha}).\n"
        ),
    }

    for agent in ("solver", "guess_day1"):
        for tier in ("easy", "medium", "hard"):
            mean_val = 0.55 if agent == "solver" else -0.95
            files[f"results/solver_range/{agent}_{tier}_judge40.json"] = json.dumps(
                {
                    "agent": agent,
                    "tier": tier,
                    "seeds": [900000, 900039],
                    "builds": 120,
                    "mean": mean_val,
                    "sd": 0.05,
                    "build_means": [mean_val] * 120,
                }
            )

    return files


def _init_synthetic_git_repo(repo: Path) -> tuple[str, dict[str, str]]:
    repo.mkdir(parents=True, exist_ok=True)
    _git_run(repo, ["init", "-q"])
    _git_run(repo, ["config", "user.email", "test@example.com"])
    _git_run(repo, ["config", "user.name", "Test"])
    (repo / ".gitignore").write_text("results/latest/\n", encoding="utf-8")
    _git_run(repo, ["add", ".gitignore"])
    _git_run(repo, ["commit", "-q", "-m", "root commit"])
    base_sha = _git_run(repo, ["rev-parse", "HEAD"])
    files = _build_synthetic_files(base_sha)
    _write_files(repo, files)
    _git_run(repo, ["add", "."])
    _git_run(repo, ["commit", "-q", "-m", "populate synthetic artifacts"])
    return base_sha, files


def test_strict_hygiene_on_owned_files_and_docs() -> None:
    forbidden_flash_model = "gemini-3." + "5-flash"
    forbidden_raw_gap = "7" + "5% [36%, 123%]"
    forbidden_la_gap = "2" + "2% [-23%, 63%]"
    forbidden_hardcoded_ladder = ("3" + "57", "$" + "0.33", "1" + "09%")

    expected_docs = {
        "README.md",
        "JUDGE_QUICKSTART.md",
        "docs/JUDGE-WALKTHROUGH.md",
        "docs/PEER-REVIEW-QA.md",
        "docs/REPRODUCIBILITY.md",
        "docs/SUBMISSION.md",
        "results/fresh_clone/README.md",
        "docs/reports/gap.md",
        "docs/reports/integrity.md",
    }
    assert set(prov.TARGET_DOC_RELS) == expected_docs
    assert prov.audit_repo is prov.verify_repo
    assert prov.verify_commit_provenance is prov.verify_repo

    for path in (SCRIPT_PATH, SELF_PATH):
        src = path.read_text(encoding="utf-8")
        assert HASH_CHAR not in src, f"unexpected hash character in {path.name}"
        assert EM_DASH not in src, f"unexpected em dash in {path.name}"
        assert EN_DASH not in src, f"unexpected en dash in {path.name}"
        non_ascii = [ch for ch in src if ord(ch) >= 128]
        assert not non_ascii, f"unexpected non-ASCII char(s) in {path.name}: {non_ascii[:5]}"
        assert forbidden_flash_model not in src, f"unexpected flash claim token in {path.name}"
        assert forbidden_raw_gap not in src, f"unexpected 75% gap claim in {path.name}"
        assert forbidden_la_gap not in src, f"unexpected 22% gap claim in {path.name}"
        for ladder_tok in forbidden_hardcoded_ladder:
            assert ladder_tok not in src, f"hardcoded ladder token {ladder_tok!r} in {path.name}"

    gap_doc = (ROOT / "docs" / "reports" / "gap.md").read_text(encoding="utf-8")
    if forbidden_flash_model not in gap_doc:
        for rel_doc in ("JUDGE_QUICKSTART.md", "docs/JUDGE-WALKTHROUGH.md"):
            doc_txt = (ROOT / rel_doc).read_text(encoding="utf-8")
            assert forbidden_raw_gap not in doc_txt, f"{rel_doc} cites unapproved flash raw gap"
            assert forbidden_la_gap not in doc_txt, f"{rel_doc} cites unapproved flash luck-adjusted gap"


def test_real_root_via_api_and_cli(clean_tmp: Path, capsys) -> None:
    watched = tuple(ROOT / rel for rel in prov.TARGET_DOC_RELS) + (ROOT / "results" / "judge_table.md",)
    before_digests = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in watched}

    direct_results = prov.verify_repo(ROOT)
    assert len(direct_results) == 3
    assert all(r.status != "FAIL" for r in direct_results)

    rc_json = prov.main(["--root", str(ROOT), "--json"])
    cli_payload = json.loads(capsys.readouterr().out)
    assert rc_json == 0
    assert cli_payload["passed"] is True
    assert cli_payload["elapsed_s"] < 2.0
    assert len(cli_payload["results"]) == 3
    assert cli_payload["checks"] == cli_payload["results"]
    assert [r["name"] for r in cli_payload["results"]] == list(prov.CHECK_NAMES)

    by_name = {r["name"]: r for r in cli_payload["results"]}
    for check_name, res in by_name.items():
        assert res["status"] != "FAIL", f"{check_name} failed on ROOT: {res['details']}"
    assert by_name[prov.CHECK_COMMITTED_RUNS]["status"] == "PASS"
    assert by_name[prov.CHECK_RESULTS_ARTIFACTS]["status"] == "PASS"
    assert by_name[prov.CHECK_DOC_SHAS]["status"] in {"PASS", "WARN"}
    assert f"across {len(prov.TARGET_DOC_RELS)} doc(s)" in by_name[prov.CHECK_DOC_SHAS]["summary"]

    reconstructed = [prov.CheckResult(**r) for r in cli_payload["results"]]
    text_report = prov.format_report(reconstructed, cli_payload["elapsed_s"])
    assert "0 FAIL" in text_report
    assert "SUMMARY:" in text_report

    non_commit_tokens = prov.known_non_commit_hex_tokens(ROOT)
    extracted_shas: set[str] = set()
    for rel_doc in prov.TARGET_DOC_RELS:
        cits, errs = prov.extract_doc_commit_citations(
            rel_doc,
            (ROOT / rel_doc).read_text(encoding="utf-8"),
            non_commit_tokens=non_commit_tokens,
        )
        assert not errs
        extracted_shas.update(c.sha for c in cits)
    for expected_real_sha in ("1bc3e281", "58716742", "cf394894", "f9fb7a4a", "29ca3bc5", "469338f6"):
        assert expected_real_sha in extracted_shas
    for non_commit_hex in (
        "a8f99c2537c91d72",
        "8df71cf570bb48bc",
        "893b837616b9",
        "705484a74e3a",
        "dbd083ca",
        "f4378173",
    ):
        assert non_commit_hex not in extracted_shas

    sub_repo = clean_tmp / "cli_subproc_smoke"
    _init_synthetic_git_repo(sub_repo)
    proc = subprocess.run(
        [sys.executable, str(SCRIPT_PATH), "--root", str(sub_repo), "--json"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    sub_payload = json.loads(proc.stdout)
    assert sub_payload["passed"] is True
    assert [r["status"] for r in sub_payload["results"]] == ["PASS", "PASS", "PASS"]

    ladder_data = json.loads((ROOT / "results" / "gemini" / "ladder.json").read_text(encoding="utf-8"))
    assert int(ladder_data["episodes"]) > 0
    assert len(ladder_data["rows"]) >= 30
    assert sum(int(r["n"]) for r in ladder_data["rows"]) == int(ladder_data["episodes"])

    inspector = prov.GitCommitInspector(ROOT)
    ladder_shas: set[str] = {str(ladder_data["git_sha"])}
    for row in ladder_data["rows"]:
        ladder_shas.update(str(s) for s in row.get("launch_git_shas", []))
    meta_shas: set[str] = set()
    for cur_root, dirnames, filenames in os.walk(ROOT / "data" / "runs" / "committed"):
        dirnames[:] = [d for d in dirnames if d not in {"superseded", "transcripts"}]
        if "meta.json" in filenames:
            meta_obj = json.loads((Path(cur_root) / "meta.json").read_text(encoding="utf-8"))
            if prov._is_hex_sha(meta_obj.get("git_sha")):
                meta_shas.add(str(meta_obj["git_sha"]))
            for extra_sha in meta_obj.get("git_shas") or []:
                if prov._is_hex_sha(extra_sha):
                    meta_shas.add(str(extra_sha))
    if inspector.has_git and not inspector.is_shallow:
        resolved_meta = inspector.resolve_shas(meta_shas)
        bad_meta = {sha: info for sha, info in resolved_meta.items() if info[0] != "commit"}
        assert not bad_meta, f"meta.json SHAs not resolving to git commits: {bad_meta}"
    resolved_ladder = inspector.resolve_shas(ladder_shas)
    bad_ladder = {
        sha: info for sha, info in resolved_ladder.items() if info[0] not in {"commit", "missing"}
    }
    assert not bad_ladder, f"ladder.json SHAs resolved to non-commit git objects: {bad_ladder}"

    after_digests = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in watched}
    assert before_digests == after_digests


def test_negative_duplicate_valid_seed_and_invalid_retry_allowed(clean_tmp: Path, capsys) -> None:
    repo = clean_tmp / "dup_seed_repo"
    base_sha, base_files = _init_synthetic_git_repo(repo)
    assert [r.status for r in prov.verify_commit_provenance(repo)] == ["PASS", "PASS", "PASS"]

    ep_rel = "data/runs/committed/v1.4/opencode-gemini-4-carbon/hard/episodes.jsonl"
    retry_invalid_line = json.dumps(
        {
            "agent": "opencode:google/gemini-4-carbon",
            "tier": "hard",
            "seed": 0,
            "score": 0.0,
            "correct": False,
            "accused": None,
            "meta": {"valid": False, "error": "infra:provider_unavailable"},
        }
    )
    (repo / ep_rel).write_text(
        base_files[ep_rel] + retry_invalid_line + "\n",
        encoding="utf-8",
    )
    sup_rel = "data/runs/committed/superseded/old-run/hard"
    _write_files(
        repo,
        {
            f"{sup_rel}/meta.json": json.dumps({"agent": "solver", "tier": "hard", "git_sha": base_sha}),
            f"{sup_rel}/episodes.jsonl": (
                json.dumps({"agent": "solver", "tier": "hard", "seed": 0, "score": 0.5})
                + "\n"
                + json.dumps({"agent": "solver", "tier": "hard", "seed": 0, "score": 0.5})
                + "\n"
            ),
        },
    )
    assert prov.check_committed_run_provenance(repo).status == "PASS"

    dup_valid_line = json.dumps(
        {
            "agent": "opencode:google/gemini-4-carbon",
            "tier": "hard",
            "seed": 0,
            "score": 0.48,
            "correct": True,
            "accused": "e01",
            "valid": True,
        }
    )
    (repo / ep_rel).write_text(
        base_files[ep_rel] + dup_valid_line + "\n",
        encoding="utf-8",
    )
    res_dup = prov.check_committed_run_provenance(repo)
    assert res_dup.status == "FAIL"
    assert any("duplicate valid" in d and "seed=0" in d for d in res_dup.details)

    rc = prov.main(["--root", str(repo), "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert rc == 1
    assert payload["passed"] is False


def test_negative_malformed_and_mismatched_tiers_version_and_meta_sha(clean_tmp: Path, capsys) -> None:
    repo = clean_tmp / "tiers_ver_repo"
    base_sha, _ = _init_synthetic_git_repo(repo)
    meta_rel = "data/runs/committed/v1.4/opencode-gemini-4-carbon/hard/meta.json"

    bad_format_meta = {
        "agent": "opencode:google/gemini-4-carbon",
        "tier": "hard",
        "tiers_version": "malformed_version_token",
        "seeds": [0, 1],
        "git_sha": base_sha,
    }
    (repo / meta_rel).write_text(json.dumps(bad_format_meta), encoding="utf-8")
    res_malformed = prov.check_committed_run_provenance(repo)
    assert res_malformed.status == "FAIL"
    assert any("malformed tiers_version" in d for d in res_malformed.details)

    rc = prov.main(["--root", str(repo), "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert rc == 1
    assert payload["passed"] is False

    wrong_dir_meta = dict(bad_format_meta, tiers_version="v1.3")
    (repo / meta_rel).write_text(json.dumps(wrong_dir_meta), encoding="utf-8")
    res_mismatch = prov.check_committed_run_provenance(repo)
    assert res_mismatch.status == "FAIL"
    assert any("inconsistent with directory expectation" in d for d in res_mismatch.details)

    bad_sha_meta = dict(bad_format_meta, tiers_version="v1.4", git_sha="not_a_hex_sha")
    (repo / meta_rel).write_text(json.dumps(bad_sha_meta), encoding="utf-8")
    res_bad_sha = prov.check_committed_run_provenance(repo)
    assert res_bad_sha.status == "FAIL"
    assert any("git_sha" in d for d in res_bad_sha.details)


def test_results_artifact_provenance_and_dynamic_ladder_refresh(clean_tmp: Path) -> None:
    repo = clean_tmp / "results_prov_repo"
    base_sha, base_files = _init_synthetic_git_repo(repo)

    refreshed_ladder: dict[str, Any] = {
        "generated_at": "2026-11-15T02:30:00+0200",
        "git_sha": "7edf2d0d50e3231ea31404aef91a8d398678cd03",
        "episodes": 417,
        "rows": [
            {
                "model": "gemini-4-carbon",
                "level": "high",
                "tier": "hard",
                "n": 400,
                "tiers_versions": ["v1.4"],
                "launch_git_shas": [base_sha],
            },
            {
                "model": "gemini-4-carbon",
                "level": "default",
                "tier": "medium",
                "n": 17,
                "tiers_versions": ["v1.4 (imported dir)"],
                "launch_git_shas": [base_sha],
            },
        ],
    }
    (repo / "results" / "gemini" / "ladder.json").write_text(json.dumps(refreshed_ladder), encoding="utf-8")
    assert prov.check_results_artifact_provenance(repo).status == "PASS"

    broken_ladder = copy.deepcopy(refreshed_ladder)
    broken_ladder["episodes"] = 999
    (repo / "results" / "gemini" / "ladder.json").write_text(json.dumps(broken_ladder), encoding="utf-8")
    res_lad = prov.check_results_artifact_provenance(repo)
    assert res_lad.status == "FAIL"
    assert any("dynamic episode sum" in d for d in res_lad.details)

    (repo / "results" / "gemini" / "ladder.json").write_text(base_files["results/gemini/ladder.json"], encoding="utf-8")
    (repo / "results" / "solver_range" / "solver_hard_judge40.json").write_text(
        json.dumps(
            {
                "agent": "solver",
                "tier": "hard",
                "seeds": [900000, 900039],
                "builds": 25,
                "mean": 0.55,
                "sd": 0.05,
                "build_means": [0.55] * 25,
            }
        ),
        encoding="utf-8",
    )
    res_sr = prov.check_results_artifact_provenance(repo)
    assert res_sr.status == "FAIL"
    assert any("builds >= 100" in d for d in res_sr.details)

    (repo / "results" / "solver_range" / "solver_hard_judge40.json").write_text(
        base_files["results/solver_range/solver_hard_judge40.json"],
        encoding="utf-8",
    )
    (repo / "results" / "judge_table.md").write_text(
        base_files["results/judge_table.md"].replace(f"git {base_sha[:7]}", "git fffffff"),
        encoding="utf-8",
    )
    res_jt = prov.check_results_artifact_provenance(repo)
    assert res_jt.status == "FAIL"
    assert any("does not match" in d for d in res_jt.details)


def test_negative_fabricated_doc_sha_blob_sha_and_external_branch_warn(clean_tmp: Path, capsys) -> None:
    repo = clean_tmp / "doc_sha_repo"
    _, base_files = _init_synthetic_git_repo(repo)

    (repo / "JUDGE_QUICKSTART.md").write_text(
        base_files["JUDGE_QUICKSTART.md"] + "Verified at commit `deadbeef1234`.\n",
        encoding="utf-8",
    )
    res_fab = prov.check_doc_commit_references(repo)
    assert res_fab.status == "FAIL"
    assert any("deadbeef1234" in d for d in res_fab.details)

    rc_fail = prov.main(["--root", str(repo), "--json"])
    payload_fail = json.loads(capsys.readouterr().out)
    assert rc_fail == 1
    assert payload_fail["passed"] is False

    blob_sha = _git_run(repo, ["rev-parse", "HEAD:.gitignore"])
    (repo / "JUDGE_QUICKSTART.md").write_text(
        base_files["JUDGE_QUICKSTART.md"] + f"Citing a blob as commit `{blob_sha[:10]}`.\n",
        encoding="utf-8",
    )
    res_blob = prov.check_doc_commit_references(repo)
    assert res_blob.status == "FAIL"
    assert any("blob" in d for d in res_blob.details)

    (repo / "JUDGE_QUICKSTART.md").write_text(base_files["JUDGE_QUICKSTART.md"], encoding="utf-8")
    main_branch = _git_run(repo, ["branch", "--show-current"])
    _git_run(repo, ["checkout", "-q", "-b", "justSilas-expert"])
    (repo / "side_note.txt").write_text("external experiment\n", encoding="utf-8")
    _git_run(repo, ["add", "side_note.txt"])
    _git_run(repo, ["commit", "-q", "-m", "side experiment"])
    ext_sha = _git_run(repo, ["rev-parse", "HEAD"])[:8]
    _git_run(repo, ["checkout", "-q", main_branch])

    (repo / "docs" / "reports" / "gap.md").write_text(
        base_files["docs/reports/gap.md"]
        + f"Negative ablation: results/expert_verdict.json on justSilas-expert {ext_sha}.\n",
        encoding="utf-8",
    )
    res_ext = prov.check_doc_commit_references(repo)
    assert res_ext.status == "WARN"
    assert any(ext_sha in d for d in res_ext.details)

    rc_warn = prov.main(["--root", str(repo), "--json"])
    payload_warn = json.loads(capsys.readouterr().out)
    assert rc_warn == 0
    assert payload_warn["passed"] is True


def test_gitless_fallback_pass_warn_and_malformed_fail(clean_tmp: Path, capsys) -> None:
    gitless_repo = clean_tmp / "gitless_archive"
    fake_commit = "a1b2c3d4e5f60718293a4b5c6d7e8f90a1b2c3d4"
    files = _build_synthetic_files(fake_commit)
    _write_files(gitless_repo, files)
    assert not (gitless_repo / ".git").exists()

    results = prov.verify_commit_provenance(gitless_repo)
    assert [r.status for r in results] == ["PASS", "PASS", "WARN"]
    assert "gitless fallback" in results[2].summary

    rc_warn = prov.main(["--root", str(gitless_repo), "--json"])
    payload_warn = json.loads(capsys.readouterr().out)
    assert rc_warn == 0
    assert payload_warn["passed"] is True

    zero_sha_repo = clean_tmp / "gitless_zero_shas"
    zero_files = dict(files)
    for rel_doc in prov.TARGET_DOC_RELS:
        zero_files[rel_doc] = f"{HASH_CHAR} {rel_doc}\nNo commit citations.\n"
    _write_files(zero_sha_repo, zero_files)
    res_zero = prov.check_doc_commit_references(zero_sha_repo)
    assert res_zero.status == "PASS"
    assert "gitless fallback" in res_zero.summary

    malformed_gitless = clean_tmp / "gitless_bad_col"
    bad_col_files = dict(files)
    bad_col_files["results/fresh_clone/README.md"] = (
        f"{HASH_CHAR} Fresh clone\n"
        "| run | commit | reproduce |\n"
        "|---|---|---:|\n"
        "| run.log.txt | NOT_A_HEX_SHA | 50 s |\n"
    )
    _write_files(malformed_gitless, bad_col_files)
    res_bad = prov.check_doc_commit_references(malformed_gitless)
    assert res_bad.status == "FAIL"
    assert any("NOT_A_HEX_SHA" in d for d in res_bad.details)

    rc_bad = prov.main(["--root", str(malformed_gitless), "--json"])
    payload_bad = json.loads(capsys.readouterr().out)
    assert rc_bad == 1
    assert payload_bad["passed"] is False
