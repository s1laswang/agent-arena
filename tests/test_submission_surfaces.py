from __future__ import annotations

import gzip
import importlib.util
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Iterator

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts" / "verify_submission_surfaces.py"
SELF_PATH = Path(__file__).resolve()
OPENCODE_TMP = Path("/tmp/opencode")
H = chr(35)
H2 = H * 2
EM_DASH = chr(0x2014)
EN_DASH = chr(0x2013)
PNG_BYTES = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
MP4_BYTES = b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00mp42isom"
MP3_BYTES = b"ID3\x03\x00\x00\x00\x00\x00\x10FAKE_MP3"
WAV_BYTES = b"RIFF$\x00\x00\x00WAVEfmt \x10\x00\x00\x00"


def _load_module():
    spec = importlib.util.spec_from_file_location("verify_submission_surfaces", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


surfaces = _load_module()


@pytest.fixture()
def opencode_tmp() -> Iterator[Path]:
    OPENCODE_TMP.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        dir=str(OPENCODE_TMP), prefix="test-submission-surfaces-"
    ) as tmp_str:
        yield Path(tmp_str)


def _valid_task_toml() -> str:
    return "\n".join(
        [
            'schema_version = "1.4"',
            "",
            "[task]",
            'name = "canary/${TASK_ID}"',
            "",
            "[metadata]",
            'tier = "${TIER}"',
            "",
            "[verifier]",
            "timeout_sec = 120.0",
            'environment_mode = "${VERIFIER_MODE}"',
            "${VERIFIER_ENV_LINE}",
            "",
            "[[verifier.collect]]",
            'service = "canary-server"',
            'command = "python /opt/canary-server/collect.py"',
            "timeout_sec = 60.0",
            "",
            "[agent]",
            "timeout_sec = 10800.0",
            "",
            "[environment]",
            "build_timeout_sec = 900.0",
            'workdir = "/app"',
            "",
            "[[environment.mcp_servers]]",
            'name = "canary"',
            'transport = "streamable-http"',
            'url = "http://canary-server:8765/mcp"',
            "",
        ]
    )


def _valid_swarm_json() -> str:
    return json.dumps(
        {
            "counts": {
                "attempts": 100,
                "ledger_verified": 100,
                "exploits": 0,
                "invariant_violations": 0,
                "tool_calls": 4325,
            },
            "waves": [
                {"wave": "wave 1 (whitebox)", "planned": 40, "finished": 35, "mcp_reruns": 0},
                {"wave": "blackbox", "planned": 16, "finished": 16, "mcp_reruns": 2},
                {"wave": "wave 2 (escalation)", "planned": 24, "finished": 24, "mcp_reruns": 4},
                {"wave": "wave 2b (escalation)", "planned": 16, "finished": 16, "mcp_reruns": 3},
            ],
            "attempts": [
                {"id": "w1-000", "score": 0.0, "exploit": False, "ledger_verified": True}
            ],
        }
    )


def _valid_swarm_md() -> str:
    return "\n".join(
        [
            f"{H} Canary Lab swarm",
            "",
            "- Verified exploits: **0**",
            "",
            "| wave | run | models | planned | finished | lost | mcp | calls | pf | iv | flag | verified exploits |",
            "|---|---|---|---|---|---|---|---|---|---|---|---|",
            "| **all real waves** | | | 96 | 91 | 5 | 9 | 4325 | 17 | 0 | 1 | **0** |",
            "",
        ]
    )


def _valid_afterquery_submission_md() -> str:
    sections = [
        f"{H2} 1. What Canary is\nInsider-threat environment.\n",
        f"{H2} 2. Judges: run this\nmake setup && make reproduce\n",
        f"{H2} 3. Rubric: The gap (30)\nRaw 65% [24%, 98%], luck-adjusted 72% [52%, 91%].\n",
        f"{H2} 4. Rubric: Meaningful difficulty (30)\nSkill ladder.\n",
        f"{H2} 5. Rubric: Reward integrity (25)\nAnti-cheat battery.\n",
        f"{H2} 6. Rubric: Craft (15)\nReproducible.\n",
        f"{H2} 7. Tiebreak: does a small model improve after training on Canary?\nHonest readout.\n",
        f"{H2} 8. Known limits\nDisclosed limits.\n",
        f"{H2} 9. Team and roles\nTeam table.\n",
    ]
    return "\n".join(
        [
            f"{H} Canary: AfterQuery submission",
            "",
            "Project name: Canary",
            "Tagline (58 chars): Catch the mole with canary traps",
            "Description (594 chars): On hard, raw 65% and luck-adjusted 72% of the solver.",
            "",
            *sections,
        ]
    )


def _valid_pooled_ext_json() -> str:
    return json.dumps(
        [
            {
                "label": "OpenCode + gemini-4-carbon over MCP, pooled (primary + extension)",
                "agent": "opencode:google/gemini-4-carbon",
                "tier": "hard",
                "n": 32,
                "mean": 0.34875,
                "solver_same_seeds": 0.51375,
            },
            {
                "label": "reference solver",
                "agent": "solver",
                "tier": "hard",
                "n": 60,
                "mean": 0.4985,
                "solver_same_seeds": 0.4985,
            },
        ]
    )


def _valid_pooled_ext_md() -> str:
    return "\n".join(
        [
            "| tier | run | n | score |",
            "|---|---|---|---|",
            "| hard | OpenCode + gemini-4-carbon over MCP, pooled (primary + extension) | 32 | 0.349 |",
            "| hard | reference solver | 60 | 0.498 |",
            "",
        ]
    )


def _valid_ladder_json() -> str:
    return json.dumps(
        {
            "episodes": 587,
            "rows": [
                {"model": "gemini-3.5-flash", "level": "minimal", "tier": "hard", "n": 287},
                {"model": "gemini-3.5-flash", "level": "high", "tier": "hard", "n": 300},
            ],
        }
    )


def _valid_ablations_json() -> str:
    return json.dumps(
        {
            "thought_signatures": {
                "on": {"valid_episodes": 10, "api_errors": 0},
                "off": {
                    "episodes_attempted": 10,
                    "valid_episodes": 0,
                    "api_errors": 10,
                    "second_call_rejected_seeds": list(range(10)),
                    "rejection_rate_of_function_call_turns": 1.0,
                },
            },
            "explicit_cache": {
                "atlas_plus_gallery": {
                    "cached_tokens": 54584568,
                    "usd_paid": 21.72,
                    "usd_if_uncached": 58.56,
                    "usd_saved": 36.84,
                    "pct_saved": 62.9,
                },
                "programme": {
                    "cached_tokens": 744897721,
                    "usd_paid": 214.89,
                    "usd_if_uncached": 893.08,
                    "usd_saved": 678.19,
                    "pct_saved": 75.9,
                },
            },
            "thinking_sweep": [
                {
                    "model": "gemini-3.5-flash",
                    "level": "minimal",
                    "tier": "hard",
                    "n": 10,
                    "pct_of_solver": -32,
                    "ci95": [-124, 34],
                },
                {
                    "model": "gemini-3.5-flash",
                    "level": "medium",
                    "tier": "hard",
                    "n": 20,
                    "pct_of_solver": 78,
                    "ci95": [28, 151],
                },
            ],
        }
    )


def _valid_ablations_md() -> str:
    return "\n".join(
        [
            f"{H} Gemini ablations",
            f"{H2} 1. Thought-signature replay: OFF vs ON",
            "Rejected on 10/10 seeds without thought_signature replay.",
            f"{H2} 2. Explicit context cache: cost delta",
            "Explicit context caching saved $678.19 (75.9%) across the programme.",
            f"{H2} 3. Thinking-level sweep",
            "Varying thinking_level on one model shifts % of solver.",
            "",
        ]
    )


def _make_valid_repo_files() -> dict[str, str | bytes]:
    gz_payload = gzip.compress(b'{"text": "cached gateway response"}')
    return {
        ".gitignore": ".env\nresults/latest/\ndata/gemini/\n",
        "harbor/.gitignore": "dataset/\ndataset-*/\n",
        "harbor/build.py": (
            'import argparse\n'
            'ap = argparse.ArgumentParser()\n'
            'ap.add_argument("--verifier", choices=["separate", "shared"], default="separate")\n'
        ),
        "harbor/README.md": f"{H} Canary on Harbor\nSeparate verifier architecture.\n",
        "harbor/check_isolation.sh": "set -u\necho ISOLATION OK\n",
        "harbor/template/task.toml": _valid_task_toml(),
        "results/harbor/rehearsal/README.md": f"{H} Judge rehearsal\nPre-registered protocol.\n",
        "results/harbor/rehearsal-dry/README.md": (
            f"{H} Dry judge rehearsal\nThis was a dry run before final tag.\n"
        ),
        "results/harbor/rehearsal-dry/TABLE.md": "| task | oracle |\n|---|---|\n| hard-900000 | +0.47 |\n",
        "results/harbor_negative/c1-tamper/result.json": json.dumps(
            {
                "n_total_trials": 1,
                "stats": {
                    "evals": {
                        "oracle__dataset-c1-tamper": {
                            "metrics": [{"mean": 0.0}],
                        }
                    }
                },
            }
        ),
        "docs/SUBMISSION.md": _valid_afterquery_submission_md(),
        "data/runs/committed/v1.4/opencode-gemini-4-carbon-ext/paired_table_pooled0to59.json": _valid_pooled_ext_json(),
        "data/runs/committed/v1.4/opencode-gemini-4-carbon-ext/paired_table_pooled0to59.md": _valid_pooled_ext_md(),
        "results/eval_v14/headline_gap_paired_v14.png": PNG_BYTES,
        "results/eval_v14/posterior_calibration_v14.png": PNG_BYTES,
        "fr8/analysis/out/ws4_table_v3.md": "| model | n | score |\n|---|---|---|\n| v3-4k-s0 | 180 | -0.147 |\n",
        "fr8/analysis/out/ws4_table_8k_s1s2.md": "| model | n | score |\n|---|---|---|\n| v3_8k_s2 | 90 | -0.050 |\n",
        "fr8/analysis/out/ws4_whom_v3.md": "| run | held-out accused |\n|---|---|\n| v3-4k-s0 | 38/180 |\n",
        "fr8/verda/README.md": f"{H} Verda GPU queue\nInstance ledger.\n",
        "docs/reports/verda-evidence.md": f"{H} Verda evidence\nCompute track summary.\n",
        "results/gemini/swarm.json": _valid_swarm_json(),
        "results/gemini/swarm.md": _valid_swarm_md(),
        "results/gemini/swarm_control.md": f"{H} Positive control\nVerified exploits: **4**\n",
        "docs/reports/failure_gallery.md": f"{H} Failure gallery\n295 episodes decomposed.\n",
        "docs/gemini/SUBMISSION.md": (
            f"{H} Canary Lab\n91 attackers over 4 waves: **0 verified exploits**.\n"
        ),
        "docs/gemini/SUBMISSION-LONG.md": (
            f"{H} Canary Lab (full write-up)\n587 paired episodes and 3 ablations.\n"
        ),
        "docs/gemini/VIDEO-2MIN.md": (
            f"{H} Canary Lab: 2-minute demo video\nStoryboard and VO.\n"
        ),
        "pitch/GEMINI.md": (
            f"{H} Canary x Gemini\n91 attackers over 4 waves, with 0 verified exploits.\n"
        ),
        "results/gemini/ladder.json": _valid_ladder_json(),
        "results/gemini/frontier.png": PNG_BYTES,
        "results/gemini/frontier_medium.png": PNG_BYTES,
        "results/gemini/ablations.json": _valid_ablations_json(),
        "results/gemini/ablations.md": _valid_ablations_md(),
        "results/gemini/replay/showcase.json": json.dumps({"model": "gemini-3.1-flash-lite", "steps": [{"step": "ok"}]}),
        "results/gemini/replay/aa/resp1.json.gz": gz_payload,
        "results/gemini/replay-ladder/manifest.json": json.dumps(
            {"name": "ladder", "cmd": ["python"], "episodes": {}}
        ),
        "results/gemini/replay-ladder/bb/resp2.json.gz": gz_payload,
        "game/build.py": "def build():\n    return {}\n",
        "game/tests/parity.mjs": "console.log('parity ok');\n",
        "scripts/demo_replay.py": "print('MATCH')\n",
        "docs/DEMO.md": f"{H} Live 10-minute demo\nWalkthrough.\n",
        "docs/video/vo/index.json": json.dumps(
            [
                {"id": "01-hook", "file": "01-hook.mp3"},
                {"id": "02-env", "file": "02-env.mp3"},
            ]
        ),
        "docs/video/vo/01-hook.mp3": MP3_BYTES,
        "docs/video/vo/02-env.mp3": MP3_BYTES,
        "docs/gemini/assets/narration-2min/index.json": json.dumps(
            {
                "01-hook": {"file": "01-hook.wav"},
                "02-problem": {"file": "02-problem.wav"},
            }
        ),
        "docs/gemini/assets/narration-2min/01-hook.wav": WAV_BYTES,
        "docs/gemini/assets/narration-2min/02-problem.wav": WAV_BYTES,
        "docs/gemini/assets/canary-lab-2min.mp4": MP4_BYTES,
        "docs/gemini/assets/dashboard-headline.png": PNG_BYTES,
        "docs/gemini/assets/dashboard-swarm.png": PNG_BYTES,
    }


def _write_repo(repo: Path, files: dict[str, str | bytes]) -> Path:
    repo.mkdir(parents=True, exist_ok=True)
    for rel, content in files.items():
        target = repo / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            target.write_bytes(content)
        else:
            target.write_text(content, encoding="utf-8")
    return repo


def _init_git_repo(repo: Path, files: dict[str, str | bytes]) -> Path:
    _write_repo(repo, files)
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=repo, check=True)
    return repo


def test_source_files_have_zero_hash_and_zero_em_en_dashes():
    for path in (SCRIPT_PATH, SELF_PATH):
        src = path.read_text(encoding="utf-8")
        assert H not in src, f"unexpected hash character in {path.name}"
        assert EM_DASH not in src, f"unexpected em dash in {path.name}"
        assert EN_DASH not in src, f"unexpected en dash in {path.name}"


def test_real_repo_passes_api_and_cli(capsys):
    assert surfaces.audit_repo is surfaces.verify_submission_surfaces

    api_results = surfaces.verify_submission_surfaces(ROOT)
    alias_results = surfaces.audit_repo(ROOT)
    assert len(api_results) == 4
    assert [r.name for r in api_results] == list(surfaces.CHECK_NAMES)
    assert [r.status for r in api_results] == [r.status for r in alias_results]
    for res in api_results:
        assert res.status == "PASS", f"{res.name} failed: {res.details}"

    rc_json = surfaces.main(["--root", str(ROOT), "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert rc_json == 0
    assert payload["passed"] is True
    assert payload["elapsed_s"] < 10.0
    assert len(payload["results"]) == 4
    assert payload["checks"] == payload["results"]
    for item in payload["results"]:
        assert item["status"] == "PASS", item

    rc_text = surfaces.main(["--root", str(ROOT)])
    text_out = capsys.readouterr().out
    assert rc_text == 0
    assert "0 FAIL" in text_out
    assert "SUMMARY: 4 PASS, 0 WARN, 0 FAIL" in text_out


@pytest.mark.parametrize(
    ("case_name", "mutator", "expected_substr"),
    [
        (
            "missing_check_isolation",
            lambda f: f.pop("harbor/check_isolation.sh"),
            "harbor/check_isolation.sh",
        ),
        (
            "shared_verifier_mode",
            lambda f: f.__setitem__(
                "harbor/template/task.toml",
                _valid_task_toml().replace("${VERIFIER_MODE}", "shared"),
            ),
            "environment_mode expected 'separate'",
        ),
        (
            "shared_default_in_build_py",
            lambda f: f.__setitem__(
                "harbor/build.py",
                'ap.add_argument("--verifier", default="shared")\n',
            ),
            "environment_mode expected 'separate'",
        ),
        (
            "missing_verifier_collect",
            lambda f: f.__setitem__(
                "harbor/template/task.toml",
                _valid_task_toml().replace("[[verifier.collect]]\nservice = \"canary-server\"\ncommand = \"python /opt/canary-server/collect.py\"\ntimeout_sec = 60.0\n", ""),
            ),
            "[[verifier.collect]]",
        ),
        (
            "missing_agent_timeout",
            lambda f: f.__setitem__(
                "harbor/template/task.toml",
                _valid_task_toml().replace("timeout_sec = 10800.0", "timeout_sec = 0"),
            ),
            "agent timeout",
        ),
        (
            "canary_env_leak",
            lambda f: f.__setitem__(
                "harbor/template/task.toml",
                _valid_task_toml() + "\n[environment.env]\nCANARY_WORLD_SECRET = \"leaked\"\n",
            ),
            "CANARY_",
        ),
        (
            "missing_dry_run_label",
            lambda f: f.__setitem__(
                "results/harbor/rehearsal-dry/README.md",
                f"{H} Official benchmark evaluation\nFinal headline numbers.\n",
            ),
            "dry-run label",
        ),
        (
            "tamper_nonzero_reward",
            lambda f: f.__setitem__(
                "results/harbor_negative/c1-tamper/result.json",
                json.dumps(
                    {
                        "stats": {
                            "evals": {
                                "oracle__dataset-c1-tamper": {"metrics": [{"mean": 1.0}]}
                            }
                        }
                    }
                ),
            ),
            "expected mean 0.0",
        ),
    ],
)
def test_check1_harbor_surface_failures(
    opencode_tmp: Path,
    capsys,
    case_name: str,
    mutator,
    expected_substr: str,
):
    files = _make_valid_repo_files()
    mutator(files)
    repo = _write_repo(opencode_tmp / f"harbor_{case_name}", files)

    rc = surfaces.main(["--root", str(repo), "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert rc == 1
    assert payload["passed"] is False
    by_name = {r["name"]: r for r in payload["results"]}
    assert by_name[surfaces.CHECK_HARBOR]["status"] == "FAIL"
    assert any(expected_substr in d for d in by_name[surfaces.CHECK_HARBOR]["details"])
    for other in (surfaces.CHECK_GEMINI, surfaces.CHECK_MEDIA, surfaces.CHECK_GITIGNORE):
        assert by_name[other]["status"] == "PASS"


@pytest.mark.parametrize(
    ("case_name", "mutator", "expected_substr"),
    [
        (
            "wrong_finished_count_json",
            lambda f: f.__setitem__(
                "results/gemini/swarm.json",
                json.dumps(
                    {
                        "counts": {"exploits": 0},
                        "waves": [{"wave": "w1", "finished": 51}],
                    }
                ),
            ),
            "expected 91, got 51",
        ),
        (
            "nonzero_exploits_json",
            lambda f: f.__setitem__(
                "results/gemini/swarm.json",
                json.dumps(
                    {
                        "counts": {"exploits": 1},
                        "waves": [{"wave": "w1", "finished": 91}],
                    }
                ),
            ),
            "counts.exploits expected 0",
        ),
        (
            "swarm_md_disagrees_on_91",
            lambda f: f.__setitem__(
                "results/gemini/swarm.md",
                _valid_swarm_md().replace("| 96 | 91 |", "| 96 | 51 |"),
            ),
            "expected 91",
        ),
        (
            "submission_md_missing_91",
            lambda f: f.__setitem__(
                "docs/gemini/SUBMISSION.md",
                f"{H} Canary Lab\n51 attackers: **0 verified exploits**.\n",
            ),
            "docs/gemini/SUBMISSION.md",
        ),
        (
            "pitch_missing_zero_exploits",
            lambda f: f.__setitem__(
                "pitch/GEMINI.md",
                f"{H} Pitch\n91 attackers over 4 waves.\n",
            ),
            "pitch/GEMINI.md",
        ),
        (
            "missing_failure_gallery",
            lambda f: f.pop("docs/reports/failure_gallery.md"),
            "docs/reports/failure_gallery.md",
        ),
        (
            "empty_replay_cache_gz",
            lambda f: f.__setitem__("results/gemini/replay-ladder/bb/resp2.json.gz", b""),
            "empty *.json.gz",
        ),
        (
            "no_replay_dirs",
            lambda f: [
                f.pop(k)
                for k in list(f)
                if k.startswith("results/gemini/replay")
            ],
            "replay*",
        ),
    ],
)
def test_check2_gemini_surface_failures(
    opencode_tmp: Path,
    case_name: str,
    mutator,
    expected_substr: str,
):
    files = _make_valid_repo_files()
    mutator(files)
    repo = _write_repo(opencode_tmp / f"gemini_{case_name}", files)

    results = surfaces.verify_submission_surfaces(repo)
    by_name = {r.name: r for r in results}
    assert by_name[surfaces.CHECK_GEMINI].status == "FAIL"
    assert any(expected_substr in d for d in by_name[surfaces.CHECK_GEMINI].details)
    for other in (surfaces.CHECK_HARBOR, surfaces.CHECK_MEDIA, surfaces.CHECK_GITIGNORE):
        assert by_name[other]["status"] if isinstance(by_name[other], dict) else by_name[other].status == "PASS"


def test_check2_gemini_surface_accepts_75_plus_16_split(opencode_tmp: Path):
    files = _make_valid_repo_files()
    files["docs/gemini/SUBMISSION.md"] = (
        f"{H} Canary Lab\n"
        "100 ledger-verified attacks (75 whitebox, 16 blackbox, 9 MCP re-runs): **0 verified exploits**.\n"
    )
    repo = _write_repo(opencode_tmp / "gemini_split_75_16", files)
    results = surfaces.verify_submission_surfaces(repo)
    by_name = {r.name: r for r in results}
    assert by_name[surfaces.CHECK_GEMINI].status == "PASS"


@pytest.mark.parametrize(
    ("case_name", "mutator", "expected_substr"),
    [
        (
            "missing_parity_mjs",
            lambda f: f.pop("game/tests/parity.mjs"),
            "game/tests/parity.mjs",
        ),
        (
            "missing_referenced_mp3",
            lambda f: f.pop("docs/video/vo/02-env.mp3"),
            "02-env.mp3",
        ),
        (
            "empty_referenced_wav",
            lambda f: f.__setitem__("docs/gemini/assets/narration-2min/01-hook.wav", b""),
            "01-hook.wav",
        ),
        (
            "empty_mp4_video",
            lambda f: f.__setitem__("docs/gemini/assets/canary-lab-2min.mp4", b""),
            "canary-lab-2min.mp4",
        ),
        (
            "missing_dashboard_pngs",
            lambda f: [
                f.pop(k)
                for k in list(f)
                if k.startswith("docs/gemini/assets/dashboard-")
            ],
            "dashboard-*.png",
        ),
        (
            "empty_dashboard_png",
            lambda f: f.__setitem__("docs/gemini/assets/dashboard-swarm.png", b""),
            "dashboard-swarm.png",
        ),
        (
            "corrupt_dashboard_png_magic",
            lambda f: f.__setitem__("docs/gemini/assets/dashboard-swarm.png", b"NOT_PNG_BYTES"),
            "invalid PNG magic bytes",
        ),
    ],
)
def test_check3_media_surface_failures(
    opencode_tmp: Path,
    case_name: str,
    mutator,
    expected_substr: str,
):
    files = _make_valid_repo_files()
    mutator(files)
    repo = _write_repo(opencode_tmp / f"media_{case_name}", files)

    results = surfaces.verify_submission_surfaces(repo)
    by_name = {r.name: r for r in results}
    assert by_name[surfaces.CHECK_MEDIA].status == "FAIL"
    assert any(expected_substr in d for d in by_name[surfaces.CHECK_MEDIA].details)
    for other in (surfaces.CHECK_HARBOR, surfaces.CHECK_GEMINI, surfaces.CHECK_GITIGNORE):
        assert by_name[other].status == "PASS"


def test_check4_gitless_fallback_pass_and_failures(opencode_tmp: Path, capsys):
    nested_gitless = _write_repo(opencode_tmp / "gitless_nested", _make_valid_repo_files())
    assert not (nested_gitless / ".git").exists()
    res_nested = surfaces.verify_submission_surfaces(nested_gitless)
    assert [r.status for r in res_nested] == ["PASS", "PASS", "PASS", "PASS"]
    assert "gitless fallback" in res_nested[3].summary

    root_only_files = _make_valid_repo_files()
    root_only_files.pop("harbor/.gitignore")
    root_only_files[".gitignore"] = ".env\nresults/latest/\nharbor/dataset/\n"
    root_gitless = _write_repo(opencode_tmp / "gitless_root_only", root_only_files)
    res_root = surfaces.check_gitignore_surface(root_gitless)
    assert res_root.status == "PASS"

    missing_harbor_ignore = _make_valid_repo_files()
    missing_harbor_ignore.pop("harbor/.gitignore")
    bad_gitless = _write_repo(opencode_tmp / "gitless_missing_harbor_ds", missing_harbor_ignore)
    res_bad = surfaces.check_gitignore_surface(bad_gitless)
    assert res_bad.status == "FAIL"
    assert any("harbor/dataset/" in d for d in res_bad.details)

    rc = surfaces.main(["--root", str(bad_gitless)])
    text_out = capsys.readouterr().out
    assert rc == 1
    assert "[FAIL]" in text_out


def test_check4_git_tracked_scratch_isolation_and_gitignore_rules(opencode_tmp: Path):
    clean_git = _init_git_repo(opencode_tmp / "git_clean", _make_valid_repo_files())
    _write_repo(
        clean_git,
        {
            "results/latest/judge_table.md": "untracked scratch\n",
            "harbor/dataset/canary-hard-900000/task.toml": "untracked build\n",
            "data/gemini/replay-check/ladder/episodes.jsonl": "{}\n",
        },
    )
    res_clean = surfaces.check_gitignore_surface(clean_git)
    assert res_clean.status == "PASS", res_clean.details

    dirty_git = _init_git_repo(opencode_tmp / "git_tracked_scratch", _make_valid_repo_files())
    _write_repo(
        dirty_git,
        {
            "results/latest/judge_table.md": "accidental force-add\n",
            "harbor/dataset/canary-hard-900000/SALT": "secret\n",
            "data/gemini/replay-check/showcase-ledger.jsonl": "{}\n",
        },
    )
    subprocess.run(
        [
            "git",
            "add",
            "-f",
            "results/latest/judge_table.md",
            "harbor/dataset/canary-hard-900000/SALT",
            "data/gemini/replay-check/showcase-ledger.jsonl",
        ],
        cwd=dirty_git,
        check=True,
    )
    res_dirty = surfaces.check_gitignore_surface(dirty_git)
    assert res_dirty.status == "FAIL"
    joined = "\n".join(res_dirty.details)
    assert "results/latest/judge_table.md" in joined
    assert "harbor/dataset/canary-hard-900000/SALT" in joined
    assert "data/gemini/replay-check/showcase-ledger.jsonl" in joined

    missing_env_files = _make_valid_repo_files()
    missing_env_files[".gitignore"] = "results/latest/\ndata/gemini/\n"
    missing_env_git = _init_git_repo(opencode_tmp / "git_no_dotenv", missing_env_files)
    res_no_env = surfaces.check_gitignore_surface(missing_env_git)
    assert res_no_env.status == "FAIL"
    assert any(".env" in d for d in res_no_env.details)


@pytest.mark.parametrize(
    ("case_name", "mutator", "expected_substr"),
    [
        (
            "missing_docs_submission",
            lambda f: f.pop("docs/SUBMISSION.md"),
            "docs/SUBMISSION.md",
        ),
        (
            "submission_missing_project_name",
            lambda f: f.__setitem__(
                "docs/SUBMISSION.md",
                _valid_afterquery_submission_md().replace("Project name: Canary", "Project name: Other"),
            ),
            "Project name: Canary",
        ),
        (
            "submission_missing_tagline",
            lambda f: f.__setitem__(
                "docs/SUBMISSION.md",
                _valid_afterquery_submission_md().replace("Tagline", "Subtitle"),
            ),
            "Tagline",
        ),
        (
            "submission_missing_description",
            lambda f: f.__setitem__(
                "docs/SUBMISSION.md",
                _valid_afterquery_submission_md().replace("Description", "Summary"),
            ),
            "Description",
        ),
        (
            "submission_missing_65_pct",
            lambda f: f.__setitem__(
                "docs/SUBMISSION.md",
                _valid_afterquery_submission_md().replace("65%", "55%"),
            ),
            "65%",
        ),
        (
            "submission_missing_72_pct",
            lambda f: f.__setitem__(
                "docs/SUBMISSION.md",
                _valid_afterquery_submission_md().replace("72%", "62%"),
            ),
            "72%",
        ),
        (
            "submission_missing_rubric_section_7",
            lambda f: f.__setitem__(
                "docs/SUBMISSION.md",
                _valid_afterquery_submission_md().replace(f"{H2} 7. Tiebreak", f"{H2} Tiebreak"),
            ),
            "missing rubric section heading(s): 7",
        ),
        (
            "missing_pooled_ext_json",
            lambda f: f.pop(surfaces.POOLED_EXT_JSON),
            surfaces.POOLED_EXT_JSON,
        ),
        (
            "corrupt_pooled_ext_json",
            lambda f: f.__setitem__(surfaces.POOLED_EXT_JSON, "{broken_json"),
            "invalid JSON",
        ),
        (
            "pooled_json_wrong_opencode_n",
            lambda f: f.__setitem__(
                surfaces.POOLED_EXT_JSON,
                _valid_pooled_ext_json().replace('"n": 32', '"n": 30'),
            ),
            "missing hard OpenCode row with n=32",
        ),
        (
            "pooled_json_wrong_solver_n",
            lambda f: f.__setitem__(
                surfaces.POOLED_EXT_JSON,
                _valid_pooled_ext_json().replace('"n": 60', '"n": 30'),
            ),
            "missing hard solver row with n=60",
        ),
        (
            "pooled_md_missing_n32",
            lambda f: f.__setitem__(
                surfaces.POOLED_EXT_MD,
                _valid_pooled_ext_md().replace("| 32 |", "| 30 |"),
            ),
            "missing hard OpenCode row with n=32",
        ),
        (
            "pooled_md_missing_n60",
            lambda f: f.__setitem__(
                surfaces.POOLED_EXT_MD,
                _valid_pooled_ext_md().replace("| 60 |", "| 30 |"),
            ),
            "missing hard solver row with n=60",
        ),
        (
            "missing_headline_gap_png",
            lambda f: f.pop("results/eval_v14/headline_gap_paired_v14.png"),
            "headline_gap_paired_v14.png",
        ),
        (
            "corrupt_posterior_calibration_png",
            lambda f: f.__setitem__(
                "results/eval_v14/posterior_calibration_v14.png",
                b"NOT_A_VALID_PNG",
            ),
            "invalid PNG magic bytes in results/eval_v14/posterior_calibration_v14.png",
        ),
        (
            "missing_ws4_table_v3",
            lambda f: f.pop("fr8/analysis/out/ws4_table_v3.md"),
            "ws4_table_v3.md",
        ),
        (
            "corrupt_ws4_table_8k_no_table",
            lambda f: f.__setitem__(
                "fr8/analysis/out/ws4_table_8k_s1s2.md",
                "plain prose without pipe table\n",
            ),
            "ws4_table_8k_s1s2.md missing markdown table rows",
        ),
        (
            "empty_ws4_whom_v3",
            lambda f: f.__setitem__("fr8/analysis/out/ws4_whom_v3.md", ""),
            "ws4_whom_v3.md",
        ),
        (
            "missing_fr8_verda_readme",
            lambda f: f.pop("fr8/verda/README.md"),
            "fr8/verda/README.md",
        ),
        (
            "whitespace_verda_evidence",
            lambda f: f.__setitem__("docs/reports/verda-evidence.md", "   \n\t\n"),
            "whitespace-only file: docs/reports/verda-evidence.md",
        ),
    ],
)
def test_check1_afterquery_and_ws4_surface_failures(
    opencode_tmp: Path,
    case_name: str,
    mutator,
    expected_substr: str,
):
    files = _make_valid_repo_files()
    mutator(files)
    repo = _write_repo(opencode_tmp / f"aq_ws4_{case_name}", files)

    results = surfaces.verify_submission_surfaces(repo)
    by_name = {r.name: r for r in results}
    assert by_name[surfaces.CHECK_HARBOR].status == "FAIL"
    assert any(expected_substr in d for d in by_name[surfaces.CHECK_HARBOR].details), (
        by_name[surfaces.CHECK_HARBOR].details
    )
    for other in (surfaces.CHECK_GEMINI, surfaces.CHECK_MEDIA, surfaces.CHECK_GITIGNORE):
        assert by_name[other].status == "PASS"


@pytest.mark.parametrize(
    ("case_name", "mutator", "expected_substr"),
    [
        (
            "missing_submission_long_md",
            lambda f: f.pop("docs/gemini/SUBMISSION-LONG.md"),
            "docs/gemini/SUBMISSION-LONG.md",
        ),
        (
            "missing_video_2min_md",
            lambda f: f.pop("docs/gemini/VIDEO-2MIN.md"),
            "docs/gemini/VIDEO-2MIN.md",
        ),
        (
            "missing_ladder_json",
            lambda f: f.pop("results/gemini/ladder.json"),
            "results/gemini/ladder.json",
        ),
        (
            "corrupt_ladder_json",
            lambda f: f.__setitem__("results/gemini/ladder.json", "{bad_json"),
            "invalid JSON in results/gemini/ladder.json",
        ),
        (
            "ladder_below_500_episodes",
            lambda f: f.__setitem__(
                "results/gemini/ladder.json",
                json.dumps(
                    {
                        "episodes": 412,
                        "rows": [
                            {"model": "gemini-3.5-flash", "level": "high", "tier": "hard", "n": 412}
                        ],
                    }
                ),
            ),
            "episodes >= 500",
        ),
        (
            "ladder_row_sum_disagrees",
            lambda f: f.__setitem__(
                "results/gemini/ladder.json",
                json.dumps(
                    {
                        "episodes": 587,
                        "rows": [
                            {"model": "gemini-3.5-flash", "level": "high", "tier": "hard", "n": 520}
                        ],
                    }
                ),
            ),
            "disagrees with episodes=587",
        ),
        (
            "corrupt_frontier_png_magic",
            lambda f: f.__setitem__("results/gemini/frontier.png", b"BAD_PNG_HEADER"),
            "invalid PNG magic bytes in results/gemini/frontier.png",
        ),
        (
            "missing_frontier_medium_png",
            lambda f: f.pop("results/gemini/frontier_medium.png"),
            "results/gemini/frontier_medium.png",
        ),
        (
            "missing_ablations_json",
            lambda f: f.pop("results/gemini/ablations.json"),
            "results/gemini/ablations.json",
        ),
        (
            "ablation_sig_off_not_10_of_10",
            lambda f: f.__setitem__(
                "results/gemini/ablations.json",
                _valid_ablations_json().replace('"api_errors": 10', '"api_errors": 8'),
            ),
            "thought_signatures.off.api_errors expected 10",
        ),
        (
            "ablation_explicit_cache_zero_savings",
            lambda f: f.__setitem__(
                "results/gemini/ablations.json",
                _valid_ablations_json().replace('"usd_saved": 678.19', '"usd_saved": 0.0'),
            ),
            "explicit_cache.programme missing positive usd_saved/pct_saved",
        ),
        (
            "ablation_thinking_sweep_not_multi_level",
            lambda f: f.__setitem__(
                "results/gemini/ablations.json",
                _valid_ablations_json().replace('"level": "medium"', '"level": "minimal"'),
            ),
            "thinking_sweep lacks multi-level thinking sweep",
        ),
        (
            "ablations_md_missing_10_of_10",
            lambda f: f.__setitem__(
                "results/gemini/ablations.md",
                _valid_ablations_md().replace("10/10", "9/10"),
            ),
            "missing 10/10 thought-signature rejection ablation",
        ),
        (
            "ablations_md_missing_cache_savings",
            lambda f: f.__setitem__(
                "results/gemini/ablations.md",
                _valid_ablations_md().replace("saved", "recorded"),
            ),
            "missing explicit cache savings ablation",
        ),
        (
            "ablations_md_missing_thinking_sweep",
            lambda f: f.__setitem__(
                "results/gemini/ablations.md",
                _valid_ablations_md().replace("Thinking-level", "Model").replace("thinking_level", "model_id"),
            ),
            "missing thinking-level sweep ablation",
        ),
    ],
)
def test_check2_gemini_ladder_and_ablations_failures(
    opencode_tmp: Path,
    case_name: str,
    mutator,
    expected_substr: str,
):
    files = _make_valid_repo_files()
    mutator(files)
    repo = _write_repo(opencode_tmp / f"gemini_new_{case_name}", files)

    results = surfaces.verify_submission_surfaces(repo)
    by_name = {r.name: r for r in results}
    assert by_name[surfaces.CHECK_GEMINI].status == "FAIL"
    assert any(expected_substr in d for d in by_name[surfaces.CHECK_GEMINI].details), (
        by_name[surfaces.CHECK_GEMINI].details
    )
    for other in (surfaces.CHECK_HARBOR, surfaces.CHECK_MEDIA, surfaces.CHECK_GITIGNORE):
        assert by_name[other].status == "PASS"
