from __future__ import annotations

from .biases import (
    ANGER_WORDS,
    AUTHORITY_ROLES,
    BIAS_GENERATORS,
    BIAS_TYPES,
    DECOY_VOCAB,
    SALIENCE_TERMS,
    SocialDayContext,
    gen_anchoring,
    gen_authority,
    gen_bandwagon,
    gen_confirmation,
    gen_false_memory,
    gen_grudge,
    gen_misforward,
    gen_recency,
    gen_sycophancy,
    generate_bias_event,
    sanitize_non_decoy_base_message,
    validate_social_message,
)
from .engine import EpisodeSocialState, V16SocialProvider, make_v16_provider, parse_v16_spec
from .office_replay import BIAS_BASELINES, RumourFollower
from .variants import VARIANTS, get_variant_spec, parse_variant_biases, register_fr8_variant, run_variant_day

BIASES = BIAS_TYPES
SocialV2Provider = V16SocialProvider

__all__ = [
    "ANGER_WORDS",
    "AUTHORITY_ROLES",
    "BIASES",
    "BIAS_BASELINES",
    "BIAS_GENERATORS",
    "BIAS_TYPES",
    "DECOY_VOCAB",
    "EpisodeSocialState",
    "RumourFollower",
    "SALIENCE_TERMS",
    "SocialDayContext",
    "SocialV2Provider",
    "V16SocialProvider",
    "VARIANTS",
    "gen_anchoring",
    "gen_authority",
    "gen_bandwagon",
    "gen_confirmation",
    "gen_false_memory",
    "gen_grudge",
    "gen_misforward",
    "gen_recency",
    "gen_sycophancy",
    "generate_bias_event",
    "get_variant_spec",
    "make_v16_provider",
    "parse_v16_spec",
    "parse_variant_biases",
    "register_fr8_variant",
    "run_variant_day",
    "sanitize_non_decoy_base_message",
    "validate_social_message",
]
