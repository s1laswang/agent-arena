"""Mole Forge (CONTRACT §7): evolve mole strategies that beat investigators but stay solver-catchable."""
from .mutate import Mutator, StubMutator, LLMMutator, get_mutator, validate_strategy, DEFAULT_STRATEGY_JSON
from .fitness import evaluate

__all__ = ["Mutator", "StubMutator", "LLMMutator", "get_mutator", "validate_strategy",
           "DEFAULT_STRATEGY_JSON", "evaluate"]
