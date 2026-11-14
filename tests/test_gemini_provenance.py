from __future__ import annotations

import io
import json
import shutil
import tokenize
from pathlib import Path

import pytest

from canary.gemini.provenance import (
    REQUIRED_ROLES,
    TARGET_MODEL,
    audit_provenance,
    main,
    render_manifest_json,
    render_manifest_md,
    scan_file_secrets,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
VALID_COMMIT = "71a4255c0ffee0123456789abcdef01234567890"[:40]
SHORT_COMMIT = "71a4255"


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _build_valid_tree(root: Path) -> Path:
    explicit_roles = (
        ("world_text", 6, 12000, 3400, 0.058),
        ("adaptive_mole", 8, 18000, 4200, 0.078),
        ("failure_analyst", 20, 240000, 5100, 0.531),
        ("exploit_hunter", 10, 95000, 8200, 0.272),
        ("multimodal_evidence", 4, 31000, 2900, 0.091),
    )
    for idx, (role, count, tin, tout, usd) in enumerate(explicit_roles):
        run_dir = root / "results" / "gemini_roles" / role / f"run_{idx:02d}"
        meta = {
            "role": role,
            "model_id": TARGET_MODEL,
            "commit": VALID_COMMIT if idx % 2 == 0 else SHORT_COMMIT,
            "sample_count": count,
            "usage": {"in": tin, "out": tout, "cost_usd": usd},
            "fake_env": False,
            "smoke": False,
        }
        _write_json(run_dir / "meta.json", meta)
        (run_dir / "transcript.txt").write_text(
            "d1 plant_canary(key=trap_alpha) -> ok\n"
            "task-investigation-plan risk-assessment-step\n"
            "GEMINI_API_KEY= GOOGLE_GENERATIVE_AI_API_KEY= pytest\n",
            encoding="utf-8",
        )
        if role == "multimodal_evidence":
            (run_dir / "chart.png").write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR")

    inv_dir = root / "data" / "runs" / "committed" / "v1.4" / "gemini-4-carbon" / "hard"
    _write_json(
        inv_dir / "meta.json",
        {
            "agent": f"gemini:{TARGET_MODEL}",
            "model": TARGET_MODEL,
            "provider": "gemini",
            "git_sha": VALID_COMMIT,
            "tier": "hard",
            "seeds": [0, 1, 2],
            "usage": {"in": 50000, "out": 6000, "cost_usd": 0.16},
            "fake_env": False,
            "smoke": False,
        },
    )
    (inv_dir / "episodes.jsonl").write_text(
        "\n".join(json.dumps({"seed": s, "score": 0.65}) for s in (0, 1, 2)) + "\n",
        encoding="utf-8",
    )

    ref_dir = root / "data" / "runs" / "committed" / "v1.4" / "reference" / "solver-hard"
    _write_json(
        ref_dir / "meta.json",
        {"agent": "solver", "model": None, "git_sha": SHORT_COMMIT, "seeds": [0, 1]},
    )
    sup_dir = root / "data" / "runs" / "committed" / "v1.4" / "superseded" / "old-smoke"
    _write_json(
        sup_dir / "meta.json",
        {"role": "investigators", "model": "stub", "git_sha": "bad", "smoke": True},
    )
    return root


def test_required_roles_exact_tuple() -> None:
    assert REQUIRED_ROLES == (
        "world_text",
        "adaptive_mole",
        "investigators",
        "failure_analyst",
        "exploit_hunter",
        "multimodal_evidence",
    )


def test_valid_six_role_tree_passes_and_renders_manifests(tmp_path: Path) -> None:
    _build_valid_tree(tmp_path)
    report = audit_provenance(tmp_path)

    assert report["verified"] is True
    assert report["ok"] is True
    assert report["missing_roles"] == []
    assert tuple(report["verified_roles"]) == REQUIRED_ROLES
    assert report["secret_leaks"] == []
    assert report["totals"]["scanned_runs"] == 6
    assert report["totals"]["verified_runs"] == 6
    assert report["totals"]["count"] == 6 + 8 + 20 + 10 + 4 + 3
    assert report["totals"]["tokens_in"] == 12000 + 18000 + 240000 + 95000 + 31000 + 50000
    assert report["totals"]["tokens_out"] == 3400 + 4200 + 5100 + 8200 + 2900 + 6000
    assert report["totals"]["cost_usd"] == pytest.approx(1.19)

    inv = report["roles"]["investigators"]
    assert inv["verified"] is True
    assert inv["run_dir"] == "data/runs/committed/v1.4/gemini-4-carbon/hard"
    assert inv["model_id"] == TARGET_MODEL
    assert inv["commit"] == VALID_COMMIT
    assert inv["count"] == 3

    rc = main(["--root", str(tmp_path), "--write", "results/gemini_roles/MANIFEST", "--strict"])
    assert rc == 0

    json_file = tmp_path / "results" / "gemini_roles" / "MANIFEST.json"
    md_file = tmp_path / "results" / "gemini_roles" / "MANIFEST.md"
    assert json_file.is_file()
    assert md_file.is_file()

    saved = json.loads(json_file.read_text(encoding="utf-8"))
    assert saved["verified"] is True
    assert set(saved["roles"].keys()) == set(REQUIRED_ROLES)

    md_text = md_file.read_text(encoding="utf-8")
    assert "**VERIFIED**" in md_text
    assert "\u2014" not in md_text
    assert "\u2013" not in md_text
    for role in REQUIRED_ROLES:
        assert f"`{role}`" in md_text

    rerun = audit_provenance(tmp_path)
    assert rerun["verified"] is True


def test_missing_role_fails_verification(tmp_path: Path) -> None:
    _build_valid_tree(tmp_path)
    shutil.rmtree(tmp_path / "results" / "gemini_roles" / "exploit_hunter")

    report = audit_provenance(tmp_path)
    assert report["verified"] is False
    assert report["missing_roles"] == ["exploit_hunter"]
    assert report["roles"]["exploit_hunter"]["verified"] is False
    assert "no_runs_found" in report["roles"]["exploit_hunter"]["errors"]

    assert main(["--root", str(tmp_path)]) == 0
    assert main(["--root", str(tmp_path), "--strict"]) == 1


def test_missing_role_field_in_gemini_roles_fails(tmp_path: Path) -> None:
    _build_valid_tree(tmp_path)
    meta_path = tmp_path / "results" / "gemini_roles" / "world_text" / "run_00" / "meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    del meta["role"]
    _write_json(meta_path, meta)

    report = audit_provenance(tmp_path)
    assert report["verified"] is False
    assert "world_text" in report["missing_roles"]
    bad = next(r for r in report["runs"] if "world_text" in r["run_dir"])
    assert bad["verified"] is False
    assert "missing_role" in bad["errors"]


@pytest.mark.parametrize(
    ("usage_override", "extra_fields", "expected_err"),
    [
        ({"in": 0, "out": 0, "cost_usd": 0.0}, {}, "zero_or_invalid_usage"),
        ({"in": 1500, "out": 0, "cost_usd": 0.01}, {}, "zero_or_invalid_usage"),
        ({"in": 0, "out": 400, "cost_usd": 0.01}, {}, "zero_or_invalid_usage"),
        (None, {}, "missing_usage"),
        ({"in": 1200, "out": 300, "cost_usd": 0.0}, {"provider": "stub"}, "stub_run"),
        ({"in": 1200, "out": 300, "cost_usd": 0.0}, {"agent": "stub:script"}, "stub_run"),
        ({"in": 1200, "out": 300, "cost_usd": 0.02}, {"smoke": True}, "smoke_run"),
        ({"in": 1200, "out": 300, "cost_usd": 0.02}, {"fake_env": True}, "fake_env"),
    ],
)
def test_stub_zero_token_smoke_and_fake_env_fail(
    tmp_path: Path,
    usage_override: dict[str, object] | None,
    extra_fields: dict[str, object],
    expected_err: str,
) -> None:
    _build_valid_tree(tmp_path)
    meta_path = tmp_path / "results" / "gemini_roles" / "adaptive_mole" / "run_01" / "meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta["usage"] = usage_override
    meta.update(extra_fields)
    _write_json(meta_path, meta)

    report = audit_provenance(tmp_path)
    assert report["verified"] is False
    assert report["missing_roles"] == ["adaptive_mole"]
    assert expected_err in report["roles"]["adaptive_mole"]["errors"]
    assert main(["--root", str(tmp_path), "--strict"]) == 1


@pytest.mark.parametrize("bad_model", ["gemini-3.8-flash", "gpt-5.5", "stub", ""])
def test_wrong_or_missing_model_fails(tmp_path: Path, bad_model: str) -> None:
    _build_valid_tree(tmp_path)
    meta_path = tmp_path / "results" / "gemini_roles" / "failure_analyst" / "run_02" / "meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta["model_id"] = bad_model
    _write_json(meta_path, meta)

    report = audit_provenance(tmp_path)
    assert report["verified"] is False
    assert report["missing_roles"] == ["failure_analyst"]
    expected = f"wrong_model:{bad_model}" if bad_model else "missing_model_id"
    assert expected in report["roles"]["failure_analyst"]["errors"]


@pytest.mark.parametrize("bad_commit", ["", "unknown", "abc123", "zzzzzzz", "a" * 41])
def test_missing_or_invalid_commit_fails(tmp_path: Path, bad_commit: str) -> None:
    _build_valid_tree(tmp_path)
    meta_path = tmp_path / "results" / "gemini_roles" / "multimodal_evidence" / "run_04" / "meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta["commit"] = bad_commit
    _write_json(meta_path, meta)

    report = audit_provenance(tmp_path)
    assert report["verified"] is False
    assert report["missing_roles"] == ["multimodal_evidence"]
    errs = report["roles"]["multimodal_evidence"]["errors"]
    assert any(e == "missing_commit" or e.startswith("invalid_commit:") for e in errs)


@pytest.mark.parametrize(
    ("secret_builder", "expected_kind"),
    [
        (lambda: "AIza" + "Sy" + "DummyKeyValue0000000001", "google_api_key"),
        (lambda: "sk-" + "proj-" + "DummySecretValue0000001", "sk_api_key"),
        (lambda: "GEMINI_API" + "_KEY=" + "leaked_secret_token_99", "env_api_key"),
    ],
)
def test_leaked_secret_fails_and_is_never_echoed(
    tmp_path: Path,
    secret_builder,
    expected_kind: str,
) -> None:
    _build_valid_tree(tmp_path)
    secret_value = secret_builder()
    leak_file = tmp_path / "results" / "gemini_roles" / "world_text" / "run_00" / "debug.log"
    leak_file.write_text(f"request header {secret_value}\n", encoding="utf-8")

    report = audit_provenance(tmp_path)
    assert report["verified"] is False
    assert any(item["kind"] == expected_kind for item in report["secret_leaks"])
    assert main(["--root", str(tmp_path), "--strict"]) == 1

    rendered_json = render_manifest_json(report)
    rendered_md = render_manifest_md(report)
    assert secret_value not in rendered_json
    assert secret_value not in rendered_md


def test_base64_thought_signature_substring_does_not_false_positive(tmp_path: Path) -> None:
    _build_valid_tree(tmp_path)
    prefix = "EvQBCvEBAXLI2nyapw615t"
    mid = "AI" + "zaaXyO"
    suffix = "9kLmN0pQrStUvWxYz0123456789_" * 80
    tx_file = tmp_path / "data" / "runs" / "committed" / "v1.4" / "gemini-4-carbon" / "hard" / "transcripts" / "21.json"
    _write_json(tx_file, {"turns": [{"thought_signature": prefix + mid + suffix}, {"thought_signature": mid + suffix}]})

    assert scan_file_secrets(tx_file, tmp_path) == []
    report = audit_provenance(tmp_path)
    assert report["verified"] is True
    assert report["secret_leaks"] == []


def test_multiple_investigator_tiers_and_pricing_fallback(tmp_path: Path) -> None:
    _build_valid_tree(tmp_path)
    med_dir = tmp_path / "data" / "runs" / "committed" / "v1.4" / "gemini-4-carbon" / "medium"
    _write_json(
        med_dir / "meta.json",
        {
            "agent": f"gemini:{TARGET_MODEL}",
            "model": TARGET_MODEL,
            "git_sha": SHORT_COMMIT,
            "seeds": [0, 1],
            "usage": {"in": 10000, "out": 1000},
            "fake_env": False,
            "smoke": False,
        },
    )
    other_dir = tmp_path / "data" / "runs" / "committed" / "v1.4" / "gpt-5.5" / "hard"
    _write_json(
        other_dir / "meta.json",
        {
            "agent": "openai:gpt-5.5",
            "model": "gpt-5.5",
            "git_sha": SHORT_COMMIT,
            "seeds": [0],
            "usage": {"in": 5000, "out": 500, "cost_usd": 0.04},
        },
    )

    report = audit_provenance(tmp_path)
    assert report["verified"] is True
    inv = report["roles"]["investigators"]
    assert inv["verified"] is True
    assert len(inv["run_dirs"]) == 2
    assert inv["count"] == 5
    assert inv["tokens_in"] == 60000
    assert inv["tokens_out"] == 7000
    assert inv["cost_usd"] == pytest.approx(0.16 + 0.03)


def test_source_files_have_no_comments_em_dashes_or_keys() -> None:
    targets = [
        REPO_ROOT / "canary" / "gemini" / "provenance.py",
        REPO_ROOT / "tests" / "test_gemini_provenance.py",
    ]
    for path in targets:
        text = path.read_text(encoding="utf-8")
        assert "\u2014" not in text
        assert "\u2013" not in text
        tokens = list(tokenize.generate_tokens(io.StringIO(text).readline))
        comments = [tok for tok in tokens if tok.type == tokenize.COMMENT]
        assert comments == [], f"found comment in {path}: {comments}"
        assert scan_file_secrets(path, REPO_ROOT) == []
