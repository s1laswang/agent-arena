from __future__ import annotations

import hashlib
import math
import random
from dataclasses import dataclass, field
from typing import Any

from canary.mole.dsl import DEFAULT_STRATEGY, MoleDoc, MoleStrategy, MoleView


def _stable_rank(tag: str, peer: str) -> int:
    digest = hashlib.sha256(f"{tag}:{peer}".encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big")


def _non_decoy_scapegoats(view: MoleView, tag: str, k: int) -> tuple[str, ...]:
    pool = [p for p in view.peers if p != view.decoy]
    if not pool:
        pool = list(view.peers)
    if not pool or k <= 0:
        return ()
    sig = f"{tag}:{','.join(view.peers)}:{view.decoy or ''}"
    ranked = sorted(pool, key=lambda p: (_stable_rank(sig, p), p))
    return tuple(ranked[: min(k, len(ranked))])


def _pick_scapegoat(
    view: MoleView,
    scapegoats: tuple[str, ...],
    step_count: int,
    prefer_restricted: bool = True,
) -> str | None:
    if prefer_restricted and view.restricted_peers:
        non_decoy_r = [p for p in view.restricted_peers if p != view.decoy]
        if non_decoy_r:
            return non_decoy_r[step_count % len(non_decoy_r)]
    if not scapegoats:
        return None
    if len(scapegoats) == 1:
        return scapegoats[0]
    schedule_idx = (0, 0, 1, 0, 0, 1, 2, 0)[step_count % 8]
    return scapegoats[schedule_idx % len(scapegoats)]


def _narrow_trap_cap(n_staff: int, seen_counts: list[int], frac_floor: float = 0.16) -> int:
    structural_cap = max(4, min(7, int(math.ceil(n_staff * frac_floor))))
    if len(seen_counts) < 6:
        return structural_cap
    ordered = sorted(seen_counts)
    q25 = ordered[min(len(ordered) - 1, int(0.25 * len(ordered)))]
    return max(4, min(structural_cap, q25))


def _select_widest_doc(
    docs: tuple[MoleDoc, ...],
    prefer_aged: bool = False,
    min_safe_rc: int = 0,
) -> str | None:
    if not docs:
        return None
    wide = [d for d in docs if d.recipient_count >= min_safe_rc] if min_safe_rc > 0 else list(docs)
    candidates = wide if wide else list(docs)
    if prefer_aged:
        aged = [d for d in candidates if d.age_days >= 1]
        if aged:
            candidates = aged
    best_idx = max(
        range(len(candidates)),
        key=lambda idx: (candidates[idx].recipient_count, candidates[idx].age_days, -idx),
    )
    return candidates[best_idx].doc_id


def _sample_seeded_pool(
    view: MoleView,
    rng: random.Random,
    min_safe_rc: int = 0,
    prefer_aged: bool = False,
) -> str | None:
    docs = view.docs
    if not docs:
        return None
    base_weights = (
        list(view.select_weights)
        if view.select_weights is not None and len(view.select_weights) == len(docs)
        else [1.0] * len(docs)
    )
    idxs = [i for i, d in enumerate(docs) if d.recipient_count >= min_safe_rc] if min_safe_rc > 0 else list(range(len(docs)))
    if not idxs:
        idxs = list(range(len(docs)))
    if prefer_aged:
        aged_idxs = [i for i in idxs if docs[i].age_days >= 1]
        if aged_idxs:
            idxs = aged_idxs
    weights = [max(0.0, float(base_weights[i])) for i in idxs]
    if sum(weights) <= 0.0:
        return docs[idxs[0]].doc_id
    chosen = rng.choices(idxs, weights=weights, k=1)[0]
    return docs[chosen].doc_id


@dataclass
class AdaptiveMoleBase:
    name: str = "adaptive_base"
    scapegoat_ring_size: int = 4
    _last_day: int = field(default=0, init=False, repr=False)
    _episode_sig: tuple[tuple[str, ...], str | None] | None = field(default=None, init=False, repr=False)
    _scapegoats: tuple[str, ...] = field(default=(), init=False, repr=False)
    _seen_rc: list[int] = field(default_factory=list, init=False, repr=False)
    _leaks_emitted: int = field(default=0, init=False, repr=False)
    _days_observed: int = field(default=0, init=False, repr=False)

    def reset_episode(self) -> None:
        self._last_day = 0
        self._episode_sig = None
        self._scapegoats = ()
        self._seen_rc = []
        self._leaks_emitted = 0
        self._days_observed = 0

    def _sync_episode(self, view: MoleView) -> None:
        sig = (view.peers, view.decoy)
        if view.day == 1 or view.day <= self._last_day or sig != self._episode_sig:
            self.reset_episode()
            self._episode_sig = sig
            self._scapegoats = _non_decoy_scapegoats(view, self.name, self.scapegoat_ring_size)
        self._last_day = view.day
        self._days_observed += 1
        for d in view.docs:
            self._seen_rc.append(int(d.recipient_count))

    def _choose_leak(self, view: MoleView, rng: random.Random) -> str | None:
        raise NotImplementedError

    def _choose_frame(self, view: MoleView, rng: random.Random) -> str | None:
        return _pick_scapegoat(view, self._scapegoats, self._days_observed - 1, prefer_restricted=True)

    def decide(self, view: MoleView, rng: random.Random) -> dict[str, str | None]:
        self._sync_episode(view)
        leak_id: str | None = None
        if view.can_leak and view.docs:
            leak_id = self._choose_leak(view, rng)
            if leak_id is not None:
                self._leaks_emitted += 1
        frame_id = self._choose_frame(view, rng)
        return {"leak": leak_id, "frame": frame_id}

    def clone(self) -> AdaptiveMoleBase:
        return adaptive_from_json(self.to_json())

    def to_json(self) -> dict[str, Any]:
        return {
            "kind": "adaptive_mole",
            "strategy": self.name,
            "scapegoat_ring_size": self.scapegoat_ring_size,
        }


@dataclass
class CrowdShieldMole(AdaptiveMoleBase):
    name: str = "adaptive_crowd_shield"
    scapegoat_ring_size: int = 2
    wide_frac: float = 0.16

    def _choose_leak(self, view: MoleView, rng: random.Random) -> str | None:
        n_staff = len(view.peers) + 1
        trap_cap = _narrow_trap_cap(n_staff, self._seen_rc, frac_floor=self.wide_frac) if view.day <= 6 else 0
        return _sample_seeded_pool(view, rng, min_safe_rc=trap_cap, prefer_aged=False)

    def to_json(self) -> dict[str, Any]:
        base = super().to_json()
        base["wide_frac"] = self.wide_frac
        return base


@dataclass
class ReactiveLagMole(AdaptiveMoleBase):
    name: str = "adaptive_reactive_lag"
    scapegoat_ring_size: int = 2
    early_burst_days: int = 2

    def _choose_leak(self, view: MoleView, rng: random.Random) -> str | None:
        n_staff = len(view.peers) + 1
        trap_cap = _narrow_trap_cap(n_staff, self._seen_rc, frac_floor=0.15) if view.day <= 6 else 0
        if view.day <= self.early_burst_days:
            return _select_widest_doc(view.docs, prefer_aged=False, min_safe_rc=trap_cap)
        return _sample_seeded_pool(view, rng, min_safe_rc=trap_cap, prefer_aged=(view.day <= 5))

    def to_json(self) -> dict[str, Any]:
        base = super().to_json()
        base["early_burst_days"] = self.early_burst_days
        return base


@dataclass
class HorizonSqueezeMole(AdaptiveMoleBase):
    name: str = "adaptive_horizon_squeeze"
    scapegoat_ring_size: int = 2
    burst_target: int = 3
    lull_start: int = 5
    lull_end: int = 6

    def _choose_leak(self, view: MoleView, rng: random.Random) -> str | None:
        n_staff = len(view.peers) + 1
        trap_cap = _narrow_trap_cap(n_staff, self._seen_rc, frac_floor=0.16) if view.day <= 6 else 0
        if (
            self._leaks_emitted >= self.burst_target
            and self.lull_start <= view.day <= self.lull_end
            and view.days_since_last_leak < 2
        ):
            very_wide = [d for d in view.docs if d.recipient_count >= max(trap_cap + 6, int(0.45 * n_staff))]
            if very_wide:
                return _select_widest_doc(tuple(very_wide), prefer_aged=True)
            return None
        return _sample_seeded_pool(view, rng, min_safe_rc=trap_cap, prefer_aged=False)

    def to_json(self) -> dict[str, Any]:
        base = super().to_json()
        base.update({
            "burst_target": self.burst_target,
            "lull_start": self.lull_start,
            "lull_end": self.lull_end,
        })
        return base


@dataclass
class CounterFrontierMole(AdaptiveMoleBase):
    name: str = "adaptive_counter_frontier"
    scapegoat_ring_size: int = 2
    wide_frac: float = 0.16
    pause_narrow_until_day: int = 6

    def _choose_leak(self, view: MoleView, rng: random.Random) -> str | None:
        n_staff = len(view.peers) + 1
        if view.day > self.pause_narrow_until_day:
            return _sample_seeded_pool(view, rng, min_safe_rc=0, prefer_aged=False)
        trap_cap = _narrow_trap_cap(n_staff, self._seen_rc, frac_floor=self.wide_frac)
        safe_docs = [d for d in view.docs if d.recipient_count >= trap_cap]
        if not safe_docs:
            if self._leaks_emitted >= 2 and view.days_since_last_leak < 2:
                return None
            return _sample_seeded_pool(view, rng, min_safe_rc=0, prefer_aged=True)
        return _sample_seeded_pool(view, rng, min_safe_rc=trap_cap, prefer_aged=(4 <= view.day <= 5))

    def to_json(self) -> dict[str, Any]:
        base = super().to_json()
        base.update({
            "wide_frac": self.wide_frac,
            "pause_narrow_until_day": self.pause_narrow_until_day,
        })
        return base


ADAPTIVE_CLASSES: dict[str, type[AdaptiveMoleBase]] = {
    "adaptive_crowd_shield": CrowdShieldMole,
    "adaptive_reactive_lag": ReactiveLagMole,
    "adaptive_horizon_squeeze": HorizonSqueezeMole,
    "adaptive_counter_frontier": CounterFrontierMole,
}

DISTILLED_DSL_JSON: dict[str, dict[str, Any]] = {
    "dsl_surgical_shield": {
        "name": "dsl_surgical_shield",
        "rules": [
            {
                "if": [["recent_low_recipient_docs", ">=", 2], ["day", "<=", 10]],
                "then": {"leak": "most_recipients", "frame": "most_restricted_peer"},
            },
            {
                "if": [["recent_low_recipient_docs", ">=", 1], ["day", "<=", 5]],
                "then": {"leak": "most_recipients", "frame": "random_peer"},
            },
        ],
        "default": {"leak": "random_seeded", "frame": "random_peer"},
    },
    "dsl_paced_crowd": {
        "name": "dsl_paced_crowd",
        "rules": [
            {
                "if": [["day", ">=", 5], ["day", "<=", 7], ["days_since_last_leak", "<", 2]],
                "then": {"leak": "none", "frame": "decoy"},
            },
            {
                "if": [["recent_low_recipient_docs", ">=", 2]],
                "then": {"leak": "most_recipients", "frame": "decoy"},
            },
        ],
        "default": {"leak": "random_seeded", "frame": "decoy"},
    },
}

DISTILLED_DSL_STRATEGIES: dict[str, MoleStrategy] = {
    name: MoleStrategy.from_json(spec) for name, spec in DISTILLED_DSL_JSON.items()
}


def adaptive_from_json(obj: dict[str, Any]) -> AdaptiveMoleBase:
    if not isinstance(obj, dict) or obj.get("kind") != "adaptive_mole":
        raise ValueError("expected adaptive_mole JSON object")
    strat_name = str(obj.get("strategy") or "")
    cls = ADAPTIVE_CLASSES.get(strat_name)
    if cls is None:
        raise ValueError(f"unknown adaptive mole strategy {strat_name!r}")
    kwargs: dict[str, Any] = {}
    if "scapegoat_ring_size" in obj:
        kwargs["scapegoat_ring_size"] = int(obj["scapegoat_ring_size"])
    if cls is CrowdShieldMole and "wide_frac" in obj:
        kwargs["wide_frac"] = float(obj["wide_frac"])
    elif cls is ReactiveLagMole and "early_burst_days" in obj:
        kwargs["early_burst_days"] = int(obj["early_burst_days"])
    elif cls is HorizonSqueezeMole:
        for key in ("burst_target", "lull_start", "lull_end"):
            if key in obj:
                kwargs[key] = int(obj[key])
    elif cls is CounterFrontierMole:
        if "wide_frac" in obj:
            kwargs["wide_frac"] = float(obj["wide_frac"])
        if "pause_narrow_until_day" in obj:
            kwargs["pause_narrow_until_day"] = int(obj["pause_narrow_until_day"])
    return cls(**kwargs)


def make_mole_strategy(spec: str | dict[str, Any] | AdaptiveMoleBase | MoleStrategy) -> AdaptiveMoleBase | MoleStrategy:
    if isinstance(spec, AdaptiveMoleBase):
        return spec.clone()
    if isinstance(spec, MoleStrategy):
        return spec
    if isinstance(spec, dict):
        if spec.get("kind") == "adaptive_mole":
            return adaptive_from_json(spec)
        return MoleStrategy.from_json(spec)
    key = str(spec).strip()
    if key in ("default", "default_v0"):
        return DEFAULT_STRATEGY
    if key in ADAPTIVE_CLASSES:
        return ADAPTIVE_CLASSES[key]()
    if key in DISTILLED_DSL_STRATEGIES:
        return DISTILLED_DSL_STRATEGIES[key]
    raise ValueError(f"unknown mole strategy {spec!r}")


def list_adaptive_strategy_names(include_dsl: bool = True, include_default: bool = False) -> tuple[str, ...]:
    names: list[str] = []
    if include_default:
        names.append("default_v0")
    if include_dsl:
        names.extend(DISTILLED_DSL_STRATEGIES.keys())
    names.extend(ADAPTIVE_CLASSES.keys())
    return tuple(names)


__all__ = [
    "ADAPTIVE_CLASSES",
    "AdaptiveMoleBase",
    "CounterFrontierMole",
    "CrowdShieldMole",
    "DISTILLED_DSL_JSON",
    "DISTILLED_DSL_STRATEGIES",
    "HorizonSqueezeMole",
    "ReactiveLagMole",
    "adaptive_from_json",
    "list_adaptive_strategy_names",
    "make_mole_strategy",
]
