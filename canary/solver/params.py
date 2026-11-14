"""Recover TierParams from the public instruction text (so noise-swept tiers work without hardcoding)."""
from __future__ import annotations

import re
from dataclasses import replace

from ..rules import TIERS, TierParams

_F = r"([0-9]*\.?[0-9]+)"
_PATS = {
    "p_leak": rf"leaks one with probability {_F}",
    "leak_damage": rf"Each leak costs V -{_F}",
    "canary_cost": rf"plant_canary costs V -{_F}",
    "restrict_cost_per_day": rf"restricted employee costs V -{_F}",
    "log_rate_benign": rf"innocent rate {_F}",
    "log_rate_mole": rf"mole rate {_F}",
    "p_after_hours_benign": rf"after_hours with prob {_F} \(innocent\)",
    "p_after_hours_mole": rf"or {_F} \(mole\)",
    "framing_rate": rf"adds Poisson\({_F}\) fake",
    "framing_decoy_share": rf"the decoy with prob {_F}",
    "p_evasive_innocent": rf"evasive with probability {_F} for innocents",
    "wrong_accusation_score": r"innocent employee the score is (-?[0-9]*\.?[0-9]+)",
    "interview_lr": rf"for the mole[^0-9]*{_F} x {_F}",
}
_INTS = {"n_days": r"at most (\d+) days", "canaries_per_day": r"at most (\d+) per day",
         "max_variants": r"at most (\d+) distinct variant", "actions_per_day": r"limited to (\d+) per day",
         "tool_call_cap": r"global cap of (\d+)", "leak_window_days": r"received in the last (\d+) days",
         "n_employees": r"company with (\d+) employees"}


def _from_param_block(text: str) -> TierParams | None:
    """Parse the '## Exact parameters' block of instruction.md (`- name: value` lines)."""
    if "## Exact parameters" not in (text or ""):
        return None
    from dataclasses import fields
    kv = dict(re.findall(r"^- (\w+): (.*)$", text.split("## Exact parameters", 1)[1], re.M))
    upd = {}
    for f in fields(TierParams):
        if f.name not in kv:
            return None
        raw = kv[f.name].strip()
        if f.name == "name":
            upd[f.name] = raw
        elif raw in ("on", "off"):
            upd[f.name] = raw == "on"
        elif "tuple" in str(f.type):
            upd[f.name] = tuple(int(x) for x in raw.split(","))
        elif f.type in (int, "int"):
            upd[f.name] = int(raw)
        else:
            upd[f.name] = float(raw)
    return TierParams(**upd)


def _from_exact_block(text: str) -> TierParams | None:
    """Parse the instruction's 'Exact parameters' block (one `- key: value` per line)."""
    i = (text or "").find("Exact parameters")
    if i < 0:
        return None
    from dataclasses import fields
    kv = dict(re.findall(r"^- (\w+): (.+)$", text[i:], flags=re.M))
    name = kv.get("name")
    if name not in TIERS:
        return None
    base = TIERS[name]
    upd = {}
    for f in fields(TierParams):
        if f.name not in kv or f.name == "name":
            continue
        raw, cur = kv[f.name].strip(), getattr(base, f.name)
        try:
            if isinstance(cur, bool):
                upd[f.name] = raw.lower() in ("on", "true", "1", "yes")
            elif isinstance(cur, tuple):
                upd[f.name] = tuple(int(x) for x in raw.split(","))
            elif isinstance(cur, int):
                upd[f.name] = int(float(raw))
            elif isinstance(cur, float):
                upd[f.name] = float(raw)
        except ValueError:
            pass
    return replace(base, **upd)


def params_from_instruction(text: str) -> TierParams | None:
    p = _from_exact_block(text)
    if p is not None:
        return p
    return _params_from_prose(text)


def _params_from_prose(text: str) -> TierParams | None:
    blk = _from_param_block(text)
    if blk is not None:
        return blk
    m = re.search(r"Tier:\s*(\w+)", text or "")
    if not m or m.group(1) not in TIERS:
        return None
    p = TIERS[m.group(1)]
    upd = {}
    for k, pat in _PATS.items():
        mm = re.search(pat, text)
        if mm:
            upd[k] = float(mm.group(mm.lastindex))
    for k, pat in _INTS.items():
        mm = re.search(pat, text)
        if mm:
            upd[k] = int(mm.group(1))
    mm = re.search(r"after a delay uniform over \[([0-9, ]+)\]", text)
    if mm:
        upd["delay_choices"] = tuple(int(x) for x in mm.group(1).split(","))
    mm = re.search(r"at least (\d+)% of all staff", text)
    upd["doc_recipient_share"] = int(mm.group(1)) / 100 if mm else 0.0
    mm = re.search(r"one whole department \((\d+)%\)", text)
    if mm:
        upd["p_single_dept_recipients"] = int(mm.group(1)) / 100
    upd["careful_mole"] = "Careful mole" in text
    upd["framing"] = "Framing:" in text
    upd["decoy"] = "A decoy exists" in text
    return replace(p, **upd)
