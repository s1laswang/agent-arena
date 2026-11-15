from __future__ import annotations

from pathlib import Path

import pytest

from canary.redteam.harbor_sidecar_audit import (
    GEMINI_API_KEY_COMPOSE_LINE,
    PLACEHOLDER_LINE,
    RAW_TEMPLATE_GEMINI_KEY_LINE,
    audit_harbor_sidecar_key_gating,
    gemini_api_key_compose_line,
    simulate_compose_render,
)

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(
    ("provider", "expected"),
    [
        ("template", ""),
        ("", ""),
        ("   ", ""),
        ("stub", ""),
        ("openai:gpt-4o", ""),
        ("not-gemini", ""),
        ("gemini", GEMINI_API_KEY_COMPOSE_LINE),
        ("gemini:gemini-4-carbon", GEMINI_API_KEY_COMPOSE_LINE),
        ("  GEMINI:gemini-4-carbon  ", GEMINI_API_KEY_COMPOSE_LINE),
        ("Gemini", GEMINI_API_KEY_COMPOSE_LINE),
    ],
)
def test_gemini_api_key_compose_line(provider: str, expected: str):
    assert gemini_api_key_compose_line(provider) == expected


def test_audit_harbor_sidecar_key_gating_on_repo():
    build_before = (ROOT / "harbor" / "build.py").read_bytes()
    compose_before = (ROOT / "harbor" / "template" / "environment" / "docker-compose.yaml").read_bytes()

    report = audit_harbor_sidecar_key_gating(ROOT)

    assert (ROOT / "harbor" / "build.py").read_bytes() == build_before
    assert (ROOT / "harbor" / "template" / "environment" / "docker-compose.yaml").read_bytes() == compose_before
    assert report["simulation_passed"] is True
    assert report["simulated_template_key_absent"] is True
    assert report["simulated_gemini_key_present"] is True
    assert report["simulated_gemini_model_key_present"] is True
    assert report["no_double_dollar_leak"] is True
    assert report["gemini_matches_unpatched"] is True
    assert report["currently_unconditional"] or report["already_gated"]


def test_audit_harbor_sidecar_key_gating_unpatched_and_patched_layouts(tmp_path: Path):
    unpatched = tmp_path / "unpatched"
    (unpatched / "harbor" / "template" / "environment").mkdir(parents=True)
    (unpatched / "harbor" / "build.py").write_text(
        (ROOT / "harbor" / "build.py").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    orig_compose = (ROOT / "harbor" / "template" / "environment" / "docker-compose.yaml").read_text(encoding="utf-8")
    (unpatched / "harbor" / "template" / "environment" / "docker-compose.yaml").write_text(
        orig_compose,
        encoding="utf-8",
    )

    rep_unpatched = audit_harbor_sidecar_key_gating(unpatched)
    assert rep_unpatched["currently_unconditional"] is True
    assert rep_unpatched["already_gated"] is False
    assert rep_unpatched["current_template_exposes_key"] is True
    assert rep_unpatched["simulation_passed"] is True

    patched = tmp_path / "patched"
    (patched / "harbor" / "template" / "environment").mkdir(parents=True)
    (patched / "harbor" / "build.py").write_text(
        (ROOT / "harbor" / "build.py").read_text(encoding="utf-8") + "\nGEMINI_API_KEY_LINE = ''\n",
        encoding="utf-8",
    )
    patched_compose = orig_compose.replace(RAW_TEMPLATE_GEMINI_KEY_LINE, PLACEHOLDER_LINE, 1)
    (patched / "harbor" / "template" / "environment" / "docker-compose.yaml").write_text(
        patched_compose,
        encoding="utf-8",
    )

    rep_patched = audit_harbor_sidecar_key_gating(patched)
    assert rep_patched["currently_unconditional"] is False
    assert rep_patched["already_gated"] is True
    assert rep_patched["current_template_exposes_key"] is False
    assert rep_patched["simulation_passed"] is True

    with_token = simulate_compose_render(patched_compose, "template", ledger_token="abc123")
    assert "GEMINI_API_KEY" not in with_token
    assert 'CANARY_LEDGER_TOKEN: "abc123"' in with_token
