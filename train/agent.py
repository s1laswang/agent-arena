import os
from train.policy import LocalSeat
from sleeper.company import SEATS

_cache = {}

def make_team(spec, day, trial):
    lora, _, base = spec.partition("@")
    base = base or os.environ.get("SLEEPER_BASE_MODEL", "Qwen/Qwen2.5-1.5B-Instruct")
    key = (lora, base)
    if key not in _cache:
        _cache[key] = LocalSeat(lora or None, base)
    return {s: _cache[key] for s in SEATS}
