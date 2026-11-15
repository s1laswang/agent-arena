from __future__ import annotations

import json
from pathlib import Path

from canary.social.biases import BIAS_TYPES
import canary.social.horizon_escalation as he
import canary.social.multiday_memory as mm
import canary.social.sleeper_chains as sc
from canary.social.variants import VARIANTS

ROOT = Path(__file__).resolve().parents[1]
DESIGN_DOC = ROOT / "docs" / "v16-social-design.md"
RULES_DOC = ROOT / "docs" / "v16-readme-and-rules.md"
CACHE_DIR = ROOT / "data" / "gemini_cache"


def test_v16_social_design_doc_exists_and_clean() -> None:
    assert DESIGN_DOC.is_file()
    text = DESIGN_DOC.read_text(encoding="utf-8")
    assert "\u2014" not in text
    assert "\u2013" not in text
    assert "gemini-3.5-flash" not in text
    assert "pre-registered" not in text.lower()

    h1 = chr(35) + " "
    h2 = chr(35) * 2 + " "
    h3 = chr(35) * 3 + " "
    required_headings = (
        h1 + "Canary V1.6 Social Layer: Architecture, Cognitive Biases, and Replayability",
        h2 + "1. Motivation and Lessons from V1.5 Gate B",
        h2 + "2. Research-Grounded Cognitive Bias Taxonomy",
        h3 + "Literature Grounding Notes",
        h3 + "Variant Matrix",
        h2 + "3. Cached `gemini-4-carbon` Rendering and Canary-Invariant Replay",
        h2 + "4. Fairness, Rules Disclosure, and Gate B Status",
        h3 + "Honest Gate B Outcome",
    )
    for heading in required_headings:
        assert heading in text

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
    he.register_horizon_escalation_variant()
    assert VARIANTS.get("v6_horizon_escalation") is not None
    assert "`v6_horizon_escalation`" in text
    assert "`sleeper_social_chains`" in text
    assert sc is not None
    assert VARIANTS.get("sleeper_social_chains") is not None

    for citation in (
        "Milgram, 1963",
        "Asch, 1951",
        "Bikhchandani et al., 1992",
        "1973",
        "1974",
        "Nickerson, 1998",
        "Loftus, 2005",
        "Pennycook et al., 2018",
        "Hartwig & Bond, 2011",
        "Hewstone et al., 2002",
    ):
        assert citation in text

    cache_files = list(CACHE_DIR.glob("*.json"))
    real_count = sum(
        1 for fp in cache_files if json.loads(fp.read_text(encoding="utf-8"))["provenance"]["label"] == "REAL"
    )
    assert len(cache_files) == 256 and real_count == 256
    for token in ("`256`", "`158/180`", "`18/18 = 100%`", "`16/18`", "`17/18`", "`0/18`", "`22`"):
        assert token in text

    assert "post-hoc lock" in text
    assert "671ed96" in text and "8fd4dec" in text
    raw_idx = text.index("65% [24%, 98%]")
    luck_idx = text.index("72% [52%, 91%]")
    assert raw_idx < luck_idx
    assert "Gate B is NOT met" in text


def test_v16_rules_doc_links_resolve() -> None:
    rules_text = RULES_DOC.read_text(encoding="utf-8")
    assert "docs/v16-social-design.md" in rules_text
    assert (ROOT / "docs" / "v16-social-design.md").is_file()
