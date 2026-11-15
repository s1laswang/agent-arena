from __future__ import annotations

from pathlib import Path

from canary.social.biases import BIAS_TYPES
from canary.social.variants import VARIANTS
import canary.social.multiday_memory as mm
import canary.social.sleeper_chains as sc

ROOT = Path(__file__).resolve().parents[1]
DESIGN_DOC = ROOT / "docs" / "v16-social-design.md"
RULES_DOC = ROOT / "docs" / "v16-readme-and-rules.md"


def test_v16_social_design_doc_exists_and_clean() -> None:
    assert DESIGN_DOC.is_file()
    text = DESIGN_DOC.read_text(encoding="utf-8")
    assert "\u2014" not in text
    assert "\u2013" not in text
    assert "gemini-3.5-flash" not in text
    for bias in BIAS_TYPES:
        assert f"`{bias}`" in text
    for variant in (
        "v0_v14_control",
        "v1_anchoring_authority_confirmation",
        "v2_recency_bandwagon_sycophancy",
        "v3_grudge_falsemem_misforward",
        "v4_triad_authority_recency_grudge",
        "v5_full9_cocktail",
    ):
        assert variant in VARIANTS
        assert f"`{variant}`" in text
    mm.register_multiday_memory_variant()
    assert f"`{mm.DEFAULT_VARIANT_NAME}`" in text
    assert "`sleeper_social_chains`" in text
    assert sc is not None
    assert VARIANTS.get("sleeper_social_chains") is not None
    assert "Gate B is NOT met" in text


def test_v16_rules_doc_links_resolve() -> None:
    rules_text = RULES_DOC.read_text(encoding="utf-8")
    assert "docs/v16-social-design.md" in rules_text
    assert (ROOT / "docs" / "v16-social-design.md").is_file()
