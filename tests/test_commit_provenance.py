from __future__ import annotations

import contextlib
import copy
import hashlib
import importlib.util
import io
import json
import os
import shutil
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

    gpt_meta = {
        "agent": "opencode:openai/gpt-5.5",
        "tier": "hard",
        "tiers_version": "v1.4",
        "seeds": [0, 1],
        "git_sha": commit_sha,
        "git_shas": [commit_sha],
    }
    gpt_episodes = "\n".join(
        [
            json.dumps(
                {
                    "agent": "opencode:openai/gpt-5.5",
                    "tier": "hard",
                    "seed": 0,
                    "score": 0.60,
                    "correct": True,
                    "accused": "e01",
                    "meta": {"valid": True},
                }
            ),
            json.dumps(
                {
                    "agent": "opencode:openai/gpt-5.5",
                    "tier": "hard",
                    "seed": 1,
                    "score": 0.65,
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

    paired_table = [
        {
            "label": "OpenCode + gemini-4-carbon over MCP",
            "group": "v1.4/opencode-gemini-4-carbon",
            "agent": "opencode:google/gemini-4-carbon",
            "tier": "hard",
            "n": 2,
        },
        {
            "label": f"OpenCode + gpt-5.5 over MCP (pre-registered at {short_sha})",
            "group": "v1.4/opencode-gpt-5.5",
            "agent": "opencode:openai/gpt-5.5",
            "tier": "hard",
            "n": 2,
        },
        {
            "label": "reference solver",
            "group": "v1.4/reference",
            "agent": "solver",
            "tier": "hard",
            "n": 2,
        },
    ]

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
                "| opencode:openai/gpt-5.5 | reported | 2 | 0 | +0.625 +/- 0.050 | "
                f"replayed, NON-judge seeds, 2 seeds, git {short7} "
                "(data/runs/committed/v1.4/opencode-gpt-5.5/hard) |"
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

    rehearsal_build = "\n".join(
        [
            f"sha: {commit_sha}",
            "describe: afterquery-final",
            "built_utc: 2026-11-15T03:09:17Z",
            "harbor: 0.26.0",
        ]
    ) + "\n"

    rehearsal_table = "\n".join(
        [
            f"> Correction: final run-3 table is on branch `s1-rehearsal-final` (commit {short_sha}).",
            "",
            f"{HASH_CHAR} Judge rehearsal on tag `afterquery-final` ({short_sha}): Harbor 0.26.0 + OpenCode + gemini-4-carbon",
            "",
            "Recorded in `BUILD.txt` before deadline.",
            "",
            "| run | n valid | infra (excluded) | correct / accused | mean | oracle, same tasks |",
            "|---|---:|---:|---|---:|---:|",
            "| opencode-1 | 10 | 0 | 9 / 10 | +0.472 | +0.506 |",
            "| opencode-2 | 10 | 0 | 10 / 10 | +0.585 | +0.506 |",
            "| opencode-3 | 7 | 1 | 7 / 7 | +0.656 | +0.429 |",
            "| do_nothing | 10 | 0 | 0 / 0 | +0.000 | +0.506 |",
            "| stop_early | 10 | 0 | 0 / 0 | +0.000 | +0.506 |",
        ]
    ) + "\n"

    rt_sha = commit_sha[:10]
    redteam_md = "\n".join(
        [
            f"{HASH_CHAR} Canary Lab swarm: Gemini attackers vs the Canary reward",
            "",
            f"Generated 2026-11-15T04:04:29+00:00 at `{rt_sha}`.",
            "",
            "**25 Gemini attackers** tested the environment.",
            "",
            "- Verified exploits: **0** ; invariant violations: 0 (none)",
            "",
            f"{HASH_CHAR}{HASH_CHAR} Combined count split by commit (SHA)",
            "",
            "| commit (SHA) | attempts | ledger-verified | invariant violations | verified exploits |",
            "|---|---:|---:|---:|---:|",
            f"| `{rt_sha}` | 25 | 25 | 0 | **0** |",
            "| **TOTAL (combined)** | **25** | **25** | 0 | **0** |",
        ]
    ) + "\n"

    redteam_json = {
        "generated_at": "2026-11-15T04:04:29+00:00",
        "git_sha": commit_sha,
        "ledger_run_ids": ["swarm-20261115-000001"],
        "counts": {
            "attempts": 25,
            "ledger_verified": 25,
            "exploits": 0,
            "invariant_violations": 0,
        },
        "by_sha": [
            {
                "git_sha": rt_sha,
                "attempts": 25,
                "ledger_verified": 25,
                "invariant_violations": 0,
                "exploits": 0,
            }
        ],
    }

    files: dict[str, str] = {
        "data/runs/committed/v1.4/opencode-gemini-4-carbon/hard/meta.json": json.dumps(oc_meta),
        "data/runs/committed/v1.4/opencode-gemini-4-carbon/hard/episodes.jsonl": oc_episodes,
        "data/runs/committed/v1.4/opencode-gpt-5.5/hard/meta.json": json.dumps(gpt_meta),
        "data/runs/committed/v1.4/opencode-gpt-5.5/hard/episodes.jsonl": gpt_episodes,
        "data/runs/committed/v1.4/reference/solver-hard/meta.json": json.dumps(sv_meta),
        "data/runs/committed/v1.4/reference/solver-hard/episodes.jsonl": sv_episodes,
        "data/runs/committed/v1.4/paired_table_gemini.json": json.dumps(paired_table),
        "data/runs/committed/grok/hard/meta.json": json.dumps(grok_meta),
        "data/runs/committed/grok/hard/episodes.jsonl": grok_episodes,
        "results/judge_table.md": judge_table,
        "results/failure_analysis_v1.4.json": json.dumps(fa_json),
        "results/oracle_range_v1.4.json": json.dumps(oracle_json),
        "results/gemini/ladder.json": json.dumps(ladder_json),
        "results/harbor/rehearsal/BUILD.txt": rehearsal_build,
        "results/harbor/rehearsal/TABLE.md": rehearsal_table,
        "results/redteam_1000/summary.md": redteam_md,
        "results/redteam_1000/summary.json": json.dumps(redteam_json),
        "README.md": (
            f"{HASH_CHAR} Canary\n"
            f"Tags: `afterquery-final` ({short_sha}) and `afterquery-submit-2` ({short_sha}).\n"
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
            f"Tag `afterquery-submit-2` at `{short_sha}`, `VERDA.md` (`{short_sha}`), integrity `{short7}` "
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
        "VERDA.md": (
            f"{HASH_CHAR} Canary on Verda\n"
            "Instances (`3bb74f5a`, `ac58df04`, `dbd083ca`, `924e81d8`, `68bbe201`, `f4378173`, `18acfa5d`, `714d8144`, `e9ea8b2e`).\n"
            f"Solver reward made crash-proof (commit `{short7}`).\n"
        ),
        "results/fresh_clone/README.md": (
            f"{HASH_CHAR} Fresh clone\n"
            f"{HASH_CHAR}{HASH_CHAR} Linux x86_64 (`{short_sha}`)\n"
            "| run | commit | reproduce |\n"
            "|---|---|---:|\n"
            f"| linux_x86_64_justSilas_{short_sha}.log.txt | {short_sha} | 52 s |\n"
            "Secret sha256 fingerprint `996353b5a6c1`.\n"
        ),
        "docs/reports/CEO.md": (
            f"{HASH_CHAR} CEO log\n"
            f"Tags: `afterquery-final` ({short_sha}), `afterquery-submit` ({short7}), `afterquery-submit-2` ({short_sha}).\n"
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


def _copy_synthetic_repo(template_repo: Path, dest: Path) -> Path:
    shutil.copytree(template_repo, dest)
    return dest


@pytest.fixture(scope="module")
def synthetic_repo_template() -> Iterator[tuple[Path, str, dict[str, str]]]:
    OPENCODE_TMP.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=str(OPENCODE_TMP), prefix="test-prov-tmpl-") as tmp_dir:
        tmpl_repo = Path(tmp_dir) / "template_repo"
        base_sha, base_files = _init_synthetic_git_repo(tmpl_repo)
        main_branch = _git_run(tmpl_repo, ["branch", "--show-current"])
        _git_run(tmpl_repo, ["checkout", "-q", "-b", "justSilas-expert"])
        (tmpl_repo / "side_note.txt").write_text("external experiment\n", encoding="utf-8")
        _git_run(tmpl_repo, ["add", "side_note.txt"])
        _git_run(tmpl_repo, ["commit", "-q", "-m", "side experiment"])
        _git_run(tmpl_repo, ["checkout", "-q", main_branch])
        yield (tmpl_repo, base_sha, base_files)


@pytest.fixture(scope="module")
def real_root_audit() -> dict[str, Any]:
    watched = tuple(ROOT / rel for rel in prov.TARGET_DOC_RELS) + (ROOT / "results" / "judge_table.md",)
    before_digests = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in watched}

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc_json = prov.main(["--root", str(ROOT), "--json"])
    cli_payload = json.loads(buf.getvalue())

    inspector = prov.GitCommitInspector(ROOT)
    after_digests = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in watched}
    assert before_digests == after_digests

    return {
        "rc": rc_json,
        "payload": cli_payload,
        "inspector": inspector,
    }


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
        "VERDA.md",
        "results/fresh_clone/README.md",
        "docs/reports/CEO.md",
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


def test_real_root_via_api_and_cli(
    clean_tmp: Path,
    real_root_audit: dict[str, Any],
    synthetic_repo_template: tuple[Path, str, dict[str, str]],
) -> None:
    rc_json = real_root_audit["rc"]
    cli_payload = real_root_audit["payload"]
    inspector: prov.GitCommitInspector = real_root_audit["inspector"]

    assert rc_json == 0
    assert cli_payload["passed"] is True
    assert cli_payload["elapsed_s"] < 2.5
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

    for expected_real_sha in (
        "5f9b3297",
        "aa1c679e",
        "9225f2ad",
        "1bc3e281",
        "ca0a0dc0",
        "cf394894",
        "58716742",
        "0f397ce",
        "d0ead011",
        "f9fb7a4a",
        "29ca3bc5",
        "469338f6",
        "2bb6729",
        "3603f25",
        "41f7b3d5",
        "bddc0ff9",
    ):
        assert expected_real_sha in extracted_shas

    for non_commit_hex in (
        "a8f99c2537c91d72",
        "8df71cf570bb48bc",
        "893b837616b9",
        "705484a74e3a",
        "dbd083ca",
        "f4378173",
        "3bb74f5a",
        "ac58df04",
        "68bbe201",
        "18acfa5d",
        "714d8144",
        "924e81d8",
        "e9ea8b2e",
    ):
        assert non_commit_hex not in extracted_shas

    verda_probe_cits, verda_probe_errs = prov.extract_doc_commit_citations(
        "probe.md",
        "Synced `VERDA.md` (`5407ad25`) and tag `afterquery-submit-2` `aa1c679e`.\n",
        non_commit_tokens=non_commit_tokens,
    )
    assert not verda_probe_errs
    assert {c.sha for c in verda_probe_cits} == {"5407ad25", "aa1c679e"}

    ext_rehearsal_shas = prov.documented_external_commit_shas(ROOT)
    assert "d0ead011" in ext_rehearsal_shas
    assert "be435fd5" in ext_rehearsal_shas

    gpt_meta = prov._loads_json_bytes(
        (ROOT / "data" / "runs" / "committed" / "v1.4" / "opencode-gpt-5.5" / "hard" / "meta.json").read_bytes()
    )
    assert str(gpt_meta["git_sha"]).startswith("cf394894")

    paired_rows = prov._loads_json_bytes(
        (ROOT / "data" / "runs" / "committed" / "v1.4" / "paired_table_gemini.json").read_bytes()
    )
    gpt_rows = [r for r in paired_rows if r.get("agent") == "opencode:openai/gpt-5.5" and r.get("tier") == "hard"]
    assert len(gpt_rows) == 1
    assert gpt_rows[0]["n"] == 30
    assert "cf394894" in gpt_rows[0]["label"]
    assert round(float(gpt_rows[0]["ratio"]) * 100) == 101
    assert round(float(gpt_rows[0]["ratio_lo"]) * 100) == 79
    assert round(float(gpt_rows[0]["ratio_hi"]) * 100) == 140

    rehearsal_table_txt = (ROOT / "results" / "harbor" / "rehearsal" / "TABLE.md").read_text(encoding="utf-8")
    assert "131%" in rehearsal_table_txt
    assert "9 valid trials" in rehearsal_table_txt
    assert "d0ead011" in rehearsal_table_txt

    ceo_txt = (ROOT / "docs" / "reports" / "CEO.md").read_text(encoding="utf-8")
    assert "93%, 116%, 131%" in ceo_txt
    assert "afterquery-submit-2" in ceo_txt and "aa1c679e" in ceo_txt

    readme_txt = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "131%" in readme_txt
    assert "DAgger" in readme_txt and "honest null" in readme_txt

    verda_txt = (ROOT / "VERDA.md").read_text(encoding="utf-8")
    assert "104.46" in verda_txt
    assert "0.060" in verda_txt and "+0.728" in verda_txt

    rt_summary = prov._loads_redteam_summary_projection(
        (ROOT / "results" / "redteam_1000" / "summary.json").read_bytes()
    )
    assert rt_summary["counts"]["attempts"] == 1034
    assert rt_summary["counts"]["exploits"] == 0
    assert len(rt_summary["by_sha"]) == 6
    assert sum(int(item["attempts"]) for item in rt_summary["by_sha"]) == 1034
    by_sha_map = {str(item["git_sha"]): int(item["attempts"]) for item in rt_summary["by_sha"]}
    assert by_sha_map.get("1bc3e281db") == 521

    if inspector.has_git and not inspector.is_shallow:
        head_commits = inspector.head_commits()
        assert head_commits is not None
        landmark_resolved = inspector.resolve_shas(
            (
                "5f9b3297",
                "aa1c679e",
                "9225f2ad",
                "5407ad25",
                "ce2233e9",
                "c59ecfd0",
                "ca0a0dc0",
                "cf394894",
                "f4485ec1",
                "03dba6d8",
                "58716742",
                "1bc3e281",
            )
        )
        for sha_k, (obj_t, full_s) in landmark_resolved.items():
            assert obj_t == "commit", f"{sha_k} resolved to {obj_t}"
            assert full_s in head_commits, f"{sha_k} ({full_s}) not in HEAD ancestry"

    _, base_sha, base_files = synthetic_repo_template
    gitless_cli_dir = clean_tmp / "cli_subproc_smoke"
    _write_files(gitless_cli_dir, base_files)
    sub_env = dict(os.environ)
    sub_env["GIT_CEILING_DIRECTORIES"] = str(gitless_cli_dir.resolve().parent)
    proc = subprocess.run(
        [sys.executable, str(SCRIPT_PATH), "--root", str(gitless_cli_dir), "--json"],
        cwd=gitless_cli_dir,
        env=sub_env,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    sub_payload = json.loads(proc.stdout)
    assert sub_payload["passed"] is True
    assert [r["status"] for r in sub_payload["results"]] == ["PASS", "PASS", "WARN"]

    ladder_data = prov._loads_json_bytes((ROOT / "results" / "gemini" / "ladder.json").read_bytes())
    assert int(ladder_data["episodes"]) > 0
    assert len(ladder_data["rows"]) >= 30
    assert sum(int(r["n"]) for r in ladder_data["rows"]) == int(ladder_data["episodes"])

    ladder_shas: set[str] = {str(ladder_data["git_sha"])}
    for row in ladder_data["rows"]:
        ladder_shas.update(str(s) for s in row.get("launch_git_shas", []))
    resolved_ladder = inspector.resolve_shas(ladder_shas)
    bad_ladder = {
        sha: info for sha, info in resolved_ladder.items() if info[0] not in {"commit", "missing"}
    }
    assert not bad_ladder, f"ladder.json SHAs resolved to non-commit git objects: {bad_ladder}"


def test_negative_duplicate_valid_seed_and_invalid_retry_allowed(
    clean_tmp: Path,
    synthetic_repo_template: tuple[Path, str, dict[str, str]],
    capsys,
) -> None:
    tmpl_repo, base_sha, base_files = synthetic_repo_template
    repo = _copy_synthetic_repo(tmpl_repo, clean_tmp / "dup_seed_repo")
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

    non_dict_meta_line = json.dumps(
        {
            "agent": "opencode:google/gemini-4-carbon",
            "tier": "hard",
            "seed": 99,
            "score": 0.4,
            "meta": "not_an_object",
        }
    )
    (repo / ep_rel).write_text(
        base_files[ep_rel] + non_dict_meta_line + "\n",
        encoding="utf-8",
    )
    res_bad_meta_obj = prov.check_committed_run_provenance(repo)
    assert res_bad_meta_obj.status == "FAIL"
    assert any("episode meta must be an object when present" in d for d in res_bad_meta_obj.details)

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


def test_negative_malformed_and_mismatched_tiers_version_and_meta_sha(
    clean_tmp: Path,
    synthetic_repo_template: tuple[Path, str, dict[str, str]],
    capsys,
) -> None:
    tmpl_repo, base_sha, _ = synthetic_repo_template
    repo = _copy_synthetic_repo(tmpl_repo, clean_tmp / "tiers_ver_repo")
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


def test_results_artifact_provenance_and_dynamic_ladder_refresh(
    clean_tmp: Path,
    synthetic_repo_template: tuple[Path, str, dict[str, str]],
) -> None:
    tmpl_repo, base_sha, base_files = synthetic_repo_template
    repo = _copy_synthetic_repo(tmpl_repo, clean_tmp / "results_prov_repo")
    shared_ins = prov.GitCommitInspector(repo)

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
    res_lad = prov.check_results_artifact_provenance(repo, inspector=shared_ins)
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
    res_sr = prov.check_results_artifact_provenance(repo, inspector=shared_ins)
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
    res_jt = prov.check_results_artifact_provenance(repo, inspector=shared_ins)
    assert res_jt.status == "FAIL"
    assert any("does not match" in d for d in res_jt.details)

    (repo / "results" / "judge_table.md").write_text(base_files["results/judge_table.md"], encoding="utf-8")
    (repo / "results" / "harbor" / "rehearsal" / "BUILD.txt").write_text(
        base_files["results/harbor/rehearsal/BUILD.txt"].replace("describe: afterquery-final", "describe: wrong-tag"),
        encoding="utf-8",
    )
    res_reh = prov.check_results_artifact_provenance(repo, inspector=shared_ins)
    assert res_reh.status == "FAIL"
    assert any("heading tag" in d for d in res_reh.details)

    (repo / "results" / "harbor" / "rehearsal" / "BUILD.txt").write_text(
        base_files["results/harbor/rehearsal/BUILD.txt"],
        encoding="utf-8",
    )
    (repo / "results" / "harbor" / "rehearsal" / "TABLE.md").write_text(
        base_files["results/harbor/rehearsal/TABLE.md"].replace(
            f"(commit {base_sha[:8]})",
            "(commit NOT_A_HEX_SHA)",
        ),
        encoding="utf-8",
    )
    res_reh_note = prov.check_results_artifact_provenance(repo, inspector=shared_ins)
    assert res_reh_note.status == "FAIL"
    assert any("malformed commit note SHA" in d for d in res_reh_note.details)

    (repo / "results" / "harbor" / "rehearsal" / "TABLE.md").write_text(
        base_files["results/harbor/rehearsal/TABLE.md"],
        encoding="utf-8",
    )
    (repo / "results" / "redteam_1000" / "summary.md").write_text(
        base_files["results/redteam_1000/summary.md"].replace("**25 Gemini attackers**", "**99 Gemini attackers**"),
        encoding="utf-8",
    )
    res_rt = prov.check_results_artifact_provenance(repo, inspector=shared_ins)
    assert res_rt.status == "FAIL"
    assert any("headline 99 Gemini attackers" in d for d in res_rt.details)

    (repo / "results" / "redteam_1000" / "summary.md").write_text(
        base_files["results/redteam_1000/summary.md"],
        encoding="utf-8",
    )
    bad_rt_json = json.loads(base_files["results/redteam_1000/summary.json"])
    bad_rt_json["by_sha"][0]["attempts"] = 24
    bad_rt_json["by_sha"][0]["ledger_verified"] = 24
    (repo / "results" / "redteam_1000" / "summary.json").write_text(json.dumps(bad_rt_json), encoding="utf-8")
    res_rt_split = prov.check_results_artifact_provenance(repo, inspector=shared_ins)
    assert res_rt_split.status == "FAIL"
    assert any("by_sha split" in d for d in res_rt_split.details)

    (repo / "results" / "redteam_1000" / "summary.json").write_text(
        base_files["results/redteam_1000/summary.json"],
        encoding="utf-8",
    )
    bad_pt = json.loads(base_files["data/runs/committed/v1.4/paired_table_gemini.json"])
    bad_pt[1]["group"] = "v1.4/missing-gpt-group"
    (repo / "data" / "runs" / "committed" / "v1.4" / "paired_table_gemini.json").write_text(
        json.dumps(bad_pt),
        encoding="utf-8",
    )
    res_pt = prov.check_results_artifact_provenance(repo, inspector=shared_ins)
    assert res_pt.status == "FAIL"
    assert any("missing-gpt-group" in d for d in res_pt.details)


def test_negative_fabricated_doc_sha_blob_sha_and_external_branch_warn(
    clean_tmp: Path,
    synthetic_repo_template: tuple[Path, str, dict[str, str]],
    capsys,
) -> None:
    tmpl_repo, _, base_files = synthetic_repo_template
    repo = _copy_synthetic_repo(tmpl_repo, clean_tmp / "doc_sha_repo")
    shared_ins = prov.GitCommitInspector(repo)

    (repo / "JUDGE_QUICKSTART.md").write_text(
        base_files["JUDGE_QUICKSTART.md"] + "Verified at commit `deadbeef1234`.\n",
        encoding="utf-8",
    )
    res_fab = prov.check_doc_commit_references(repo, inspector=shared_ins)
    assert res_fab.status == "FAIL"
    assert any("deadbeef1234" in d for d in res_fab.details)

    rc_fail = prov.main(["--root", str(repo), "--json"])
    payload_fail = json.loads(capsys.readouterr().out)
    assert rc_fail == 1
    assert payload_fail["passed"] is False

    blob_sha, ext_full_sha = _git_run(repo, ["rev-parse", "HEAD:.gitignore", "justSilas-expert"]).splitlines()
    ext_sha = ext_full_sha[:8]
    (repo / "JUDGE_QUICKSTART.md").write_text(
        base_files["JUDGE_QUICKSTART.md"] + f"Citing a blob as commit `{blob_sha[:10]}`.\n",
        encoding="utf-8",
    )
    res_blob = prov.check_doc_commit_references(repo, inspector=shared_ins)
    assert res_blob.status == "FAIL"
    assert any("blob" in d for d in res_blob.details)

    (repo / "JUDGE_QUICKSTART.md").write_text(base_files["JUDGE_QUICKSTART.md"], encoding="utf-8")
    (repo / "docs" / "reports" / "gap.md").write_text(
        base_files["docs/reports/gap.md"]
        + f"Negative ablation: results/expert_verdict.json on justSilas-expert {ext_sha}.\n",
        encoding="utf-8",
    )
    res_ext = prov.check_doc_commit_references(repo, inspector=shared_ins)
    assert res_ext.status == "WARN"
    assert any(ext_sha in d for d in res_ext.details)

    rc_warn = prov.main(["--root", str(repo), "--json"])
    payload_warn = json.loads(capsys.readouterr().out)
    assert rc_warn == 0
    assert payload_warn["passed"] is True


def test_gitless_fallback_pass_warn_and_malformed_fail(
    clean_tmp: Path,
    synthetic_repo_template: tuple[Path, str, dict[str, str]],
    monkeypatch: pytest.MonkeyPatch,
    capsys,
) -> None:
    tmpl_repo, _, _ = synthetic_repo_template
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

    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmpl_repo.resolve()))
    try:
        ceiling_ins = prov.GitCommitInspector(tmpl_repo)
        assert ceiling_ins.has_git is False
        rc_ceil = prov.main(["--root", str(tmpl_repo), "--json"])
        payload_ceil = json.loads(capsys.readouterr().out)
        assert rc_ceil == 0
        assert payload_ceil["passed"] is True
        assert [r["status"] for r in payload_ceil["results"]] == ["PASS", "PASS", "WARN"]
    finally:
        monkeypatch.delenv("GIT_CEILING_DIRECTORIES", raising=False)

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


def test_shallow_clone_detached_head_provenance(
    clean_tmp: Path,
    synthetic_repo_template: tuple[Path, str, dict[str, str]],
    capsys,
) -> None:
    tmpl_repo, base_sha, base_files = synthetic_repo_template
    origin_repo = _copy_synthetic_repo(tmpl_repo, clean_tmp / "origin_full_repo")
    _git_run(origin_repo, ["tag", "afterquery-final", base_sha])
    mid_sha = _git_run(origin_repo, ["rev-parse", "HEAD"])

    (origin_repo / "README.md").write_text(
        base_files["README.md"] + f"Synced at commit `{mid_sha[:8]}`.\n",
        encoding="utf-8",
    )
    _git_run(origin_repo, ["add", "README.md"])
    _git_run(origin_repo, ["commit", "-q", "-m", "advance head past historical shas"])
    head_sha = _git_run(origin_repo, ["rev-parse", "HEAD"])

    shallow_repo = clean_tmp / "shallow_detached_ci"
    subprocess.run(
        ["git", "clone", "-q", "--depth", "1", "--no-tags", f"file://{origin_repo}", str(shallow_repo)],
        check=True,
        capture_output=True,
        text=True,
    )
    _git_run(shallow_repo, ["checkout", "-q", "--detach", "HEAD"])

    sym_proc = subprocess.run(
        ["git", "symbolic-ref", "-q", "HEAD"],
        cwd=shallow_repo,
        capture_output=True,
        text=True,
        check=False,
    )
    assert sym_proc.returncode != 0
    assert _git_run(shallow_repo, ["tag", "-l"]) == ""

    missing_proc = subprocess.run(
        ["git", "cat-file", "-t", base_sha],
        cwd=shallow_repo,
        capture_output=True,
        text=True,
        check=False,
    )
    assert missing_proc.returncode != 0

    inspector = prov.GitCommitInspector(shallow_repo)
    assert inspector.has_git is True
    assert inspector.is_shallow is True
    assert inspector.head_commits() == {head_sha.lower()}

    res_runs = prov.check_committed_run_provenance(shallow_repo, inspector=inspector)
    res_artifacts = prov.check_results_artifact_provenance(shallow_repo, inspector=inspector)
    res_docs = prov.check_doc_commit_references(shallow_repo, inspector=inspector)
    assert res_runs.status == "PASS", res_runs.details
    assert res_artifacts.status == "PASS", res_artifacts.details
    assert res_docs.status == "WARN", res_docs.details
    assert any("shallow .git clone omits historical commit SHA" in d for d in res_docs.details)

    rc = prov.main(["--root", str(shallow_repo), "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert payload["passed"] is True
    assert payload["elapsed_s"] < 2.5
    assert [r["status"] for r in payload["results"]] == ["PASS", "PASS", "WARN"]
    report_txt = prov.format_report([prov.CheckResult(**r) for r in payload["results"]], payload["elapsed_s"])
    assert "0 FAIL" in report_txt

    head_doc_only = _copy_synthetic_repo(shallow_repo, clean_tmp / "shallow_head_only_docs")
    for rel_doc in prov.TARGET_DOC_RELS:
        (head_doc_only / rel_doc).write_text(
            f"{HASH_CHAR} {rel_doc}\nVerified at commit `{head_sha[:8]}`.\n",
            encoding="utf-8",
        )
    assert prov.check_doc_commit_references(head_doc_only).status == "PASS"

    blob_sha = _git_run(shallow_repo, ["rev-parse", "HEAD:.gitignore"])
    (shallow_repo / "JUDGE_QUICKSTART.md").write_text(
        base_files["JUDGE_QUICKSTART.md"] + f"Citing blob `{blob_sha[:10]}`.\n",
        encoding="utf-8",
    )
    res_blob_shallow = prov.check_doc_commit_references(shallow_repo)
    assert res_blob_shallow.status == "FAIL"
    assert any("blob" in d for d in res_blob_shallow.details)
