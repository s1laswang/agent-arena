import os
from train.policy import LocalSeat, Policy
from sleeper.company import SEATS

_cache = {}

def make_team(spec, day, trial):
    if spec == "careful":
        from train.teacher import Careful
        return {s: Careful() for s in SEATS}
    lora, _, base = spec.partition("@")
    base = base or os.environ.get("SLEEPER_BASE_MODEL", "Qwen/Qwen2.5-1.5B-Instruct")
    key = (lora, base)
    if key not in _cache:
        _cache[key] = Policy(base, lora or None)
    return {s: LocalSeat(_cache[key]) for s in SEATS}
