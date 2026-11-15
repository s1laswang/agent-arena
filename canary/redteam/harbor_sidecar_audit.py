"""Read-only auditor and compose helper for gating GEMINI_API_KEY in Harbor sidecars."""
from __future__ import annotations

import string
from pathlib import Path
from typing import Any

GEMINI_API_KEY_COMPOSE_LINE = '      GEMINI_API_KEY: "${GEMINI_API_KEY:-}"'
RAW_TEMPLATE_GEMINI_KEY_LINE = '      GEMINI_API_KEY: "$${GEMINI_API_KEY:-}"'
PLACEHOLDER_LINE = "${GEMINI_API_KEY_LINE}"


def gemini_api_key_compose_line(provider: str) -> str:
    """Return the rendered compose environment line only for Gemini providers."""
    if (provider or "").strip().lower().startswith("gemini"):
        return GEMINI_API_KEY_COMPOSE_LINE
    return ""


def simulate_compose_render(compose_template_text: str, provider: str, ledger_token: str = "") -> str:
    """Simulate harbor/build.py string.Template substitution with GEMINI_API_KEY_LINE gating."""
    patched = (
        compose_template_text
        if PLACEHOLDER_LINE in compose_template_text
        else compose_template_text.replace(RAW_TEMPLATE_GEMINI_KEY_LINE, PLACEHOLDER_LINE, 1)
    )
    subs = {
        "LEDGER_TOKEN_LINE": f'      CANARY_LEDGER_TOKEN: "{ledger_token}"' if ledger_token else "",
        "GEMINI_API_KEY_LINE": gemini_api_key_compose_line(provider),
    }
    return string.Template(patched).substitute(subs)


def audit_harbor_sidecar_key_gating(root: Path) -> dict[str, Any]:
    """Read harbor/build.py and docker-compose.yaml without modifying them and verify key gating."""
    build_path = root / "harbor" / "build.py"
    compose_path = root / "harbor" / "template" / "environment" / "docker-compose.yaml"
    build_text = build_path.read_text(encoding="utf-8")
    compose_text = compose_path.read_text(encoding="utf-8")

    currently_unconditional = (
        RAW_TEMPLATE_GEMINI_KEY_LINE in compose_text
        and PLACEHOLDER_LINE not in compose_text
    )
    already_gated = (
        PLACEHOLDER_LINE in compose_text
        and "GEMINI_API_KEY_LINE" in build_text
    )

    current_subs = {
        "LEDGER_TOKEN_LINE": "",
        "GEMINI_API_KEY_LINE": gemini_api_key_compose_line("template"),
    }
    current_rendered_default = string.Template(compose_text).safe_substitute(current_subs)
    current_template_exposes_key = "GEMINI_API_KEY" in current_rendered_default

    rendered_template = simulate_compose_render(compose_text, "template")
    rendered_gemini = simulate_compose_render(compose_text, "gemini")
    rendered_gemini_model = simulate_compose_render(compose_text, "gemini:gemini-4-carbon")

    if "GEMINI_API_KEY" in rendered_template:
        raise AssertionError("GEMINI_API_KEY remained present under provider='template'")
    if 'GEMINI_API_KEY: "${GEMINI_API_KEY:-}"' not in rendered_gemini:
        raise AssertionError("GEMINI_API_KEY interpolation line missing under provider='gemini'")
    if 'GEMINI_API_KEY: "${GEMINI_API_KEY:-}"' not in rendered_gemini_model:
        raise AssertionError("GEMINI_API_KEY interpolation line missing under provider='gemini:gemini-4-carbon'")
    if "$${GEMINI_API_KEY" in rendered_gemini:
        raise AssertionError("Double-dollar template escape leaked into rendered compose YAML")

    gemini_matches_unpatched = (
        rendered_gemini == string.Template(compose_text).substitute({"LEDGER_TOKEN_LINE": ""})
        if currently_unconditional
        else True
    )
    if not gemini_matches_unpatched:
        raise AssertionError("Rendered compose under provider='gemini' differed from original compose output")

    return {
        "build_py": "harbor/build.py",
        "compose_template": "harbor/template/environment/docker-compose.yaml",
        "currently_unconditional": currently_unconditional,
        "already_gated": already_gated,
        "current_template_exposes_key": current_template_exposes_key,
        "simulated_template_key_absent": "GEMINI_API_KEY" not in rendered_template,
        "simulated_gemini_key_present": 'GEMINI_API_KEY: "${GEMINI_API_KEY:-}"' in rendered_gemini,
        "simulated_gemini_model_key_present": 'GEMINI_API_KEY: "${GEMINI_API_KEY:-}"' in rendered_gemini_model,
        "no_double_dollar_leak": "$${GEMINI_API_KEY" not in rendered_gemini,
        "gemini_matches_unpatched": gemini_matches_unpatched,
        "simulation_passed": True,
    }
