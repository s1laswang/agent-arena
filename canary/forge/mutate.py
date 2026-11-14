"""Mutation operators for mole strategies (CONTRACT §7).

A strategy is JSON: {"rules": [{"if": [[feature, op, number], ...], "then": {"leak": sel|null, "frame": fsel|null}}],
                     "default": {"leak": sel|null, "frame": fsel|null}}
`validate_strategy` is the single swap point: it defers to canary.mole.dsl.MoleStrategy.from_json when ENV's DSL
exists and falls back to the local validator otherwise.
"""
from __future__ import annotations

import copy
import json
import random
from typing import Any, Protocol

FEATURES = ["n_docs_held", "min_recipient_count", "max_recipient_count", "newest_doc_age_days",
            "days_since_last_leak", "i_am_restricted", "n_restricted_colleagues",
            "recent_low_recipient_docs", "day"]
FEATURE_RANGES = {"n_leakable": (0, 12), "n_docs_held": (0, 12), "min_recipient_count": (1, 20), "max_recipient_count": (1, 30),
                  "newest_doc_age_days": (0, 3), "days_since_last_leak": (0, 14), "i_am_restricted": (0, 1),
                  "n_restricted_colleagues": (0, 10), "recent_low_recipient_docs": (0, 6), "day": (1, 14)}
OPS = ["<", "<=", ">", ">=", "==", "!="]
LEAK_SELECTORS = ["newest", "oldest", "most_recipients", "fewest_recipients", "random_seeded", "none"]
FRAME_SELECTORS = ["decoy", "most_restricted_peer", "random_peer", "none"]
MAX_RULES = 12
MAX_CONDS = 4
try:  # the real DSL is the source of truth for the vocabulary
    from canary.mole import dsl as _dsl
    FEATURES = list(_dsl.FEATURES)
    OPS = list(_dsl.OPS)
    LEAK_SELECTORS = list(_dsl.LEAK_SELECTORS)
    FRAME_SELECTORS = list(_dsl.FRAME_SELECTORS)
    MAX_RULES = _dsl.MAX_RULES
except ImportError:  # pragma: no cover
    _dsl = None

DEFAULT_STRATEGY_JSON: dict = {"rules": [], "default": {"leak": "random_seeded", "frame": "none"}}


def canonical(strategy: dict) -> str:
    return json.dumps(strategy, sort_keys=True, separators=(",", ":"))


def _local_validate(obj: Any) -> dict:
    if not isinstance(obj, dict) or set(obj) - {"rules", "default", "name"}:
        raise ValueError("strategy must be an object with keys rules, default")
    rules = obj.get("rules", [])
    if not isinstance(rules, list) or len(rules) > MAX_RULES:
        raise ValueError(f"rules must be a list of <= {MAX_RULES}")

    def _then(t):
        if not isinstance(t, dict) or set(t) - {"leak", "frame"}:
            raise ValueError(f"bad action {t!r}")
        if t.get("leak") is not None and t["leak"] not in LEAK_SELECTORS:
            raise ValueError(f"bad leak selector {t.get('leak')!r}")
        if t.get("frame") is not None and t["frame"] not in FRAME_SELECTORS:
            raise ValueError(f"bad frame selector {t.get('frame')!r}")
        return {"leak": t.get("leak"), "frame": t.get("frame")}

    out_rules = []
    for r in rules:
        if not isinstance(r, dict) or set(r) != {"if", "then"}:
            raise ValueError(f"bad rule {r!r}")
        conds = r["if"]
        if not isinstance(conds, list) or not 1 <= len(conds) <= MAX_CONDS:
            raise ValueError("if must be a list of 1..4 conditions")
        cc = []
        for c in conds:
            if (not isinstance(c, (list, tuple)) or len(c) != 3 or c[0] not in FEATURES or c[1] not in OPS
                    or isinstance(c[2], bool) or not isinstance(c[2], (int, float))):
                raise ValueError(f"bad condition {c!r}")
            cc.append([c[0], c[1], c[2]])
        out_rules.append({"if": cc, "then": _then(r["then"])})
    return {"rules": out_rules, "default": _then(obj.get("default", DEFAULT_STRATEGY_JSON["default"]))}


def validate_strategy(obj: Any) -> dict:
    """Return a normalised strategy dict or raise ValueError. The one place to swap validators.
    With the real DSL, the result is MoleStrategy.from_json(obj).to_json() (sans name): the canonical form."""
    norm = _local_validate(obj)
    if _dsl is None:
        return norm
    try:
        out = _dsl.MoleStrategy.from_json(norm).to_json()
    except Exception as e:  # noqa: BLE001
        raise ValueError(f"DSL rejected strategy: {e}") from e
    out.pop("name", None)
    for r in out["rules"]:
        for c in r["if"]:
            if isinstance(c[2], float) and c[2].is_integer():
                c[2] = int(c[2])
    return out


def default_strategy_json() -> dict:
    try:
        from canary.mole.dsl import DEFAULT_STRATEGY  # type: ignore
        for attr in ("to_json", "as_json"):
            if hasattr(DEFAULT_STRATEGY, attr):
                return getattr(DEFAULT_STRATEGY, attr)()
        if isinstance(DEFAULT_STRATEGY, dict):
            return copy.deepcopy(DEFAULT_STRATEGY)
    except ImportError:
        pass
    return copy.deepcopy(DEFAULT_STRATEGY_JSON)


class Mutator(Protocol):
    name: str
    def propose(self, parents: list[dict], n: int) -> list[dict]: ...


class StubMutator:
    """Random but always-valid edits; deterministic given the seed (call reseed(gen) for resumable runs)."""
    name = "stub"

    def __init__(self, seed: int = 0):
        self.seed = seed
        self.rng = random.Random(f"forge-stub:{seed}")

    def reseed(self, gen: int) -> None:
        self.rng = random.Random(f"forge-stub:{self.seed}:{gen}")

    # --- primitives
    def _cond(self):
        r = self.rng
        f = r.choice(FEATURES)
        lo, hi = FEATURE_RANGES.get(f, (0, 10))
        return [f, r.choice(OPS), r.randint(lo, hi)]

    def _action(self):
        r = self.rng
        return {"leak": r.choice(LEAK_SELECTORS + [None]), "frame": r.choice(FRAME_SELECTORS + [None])}

    def _rule(self):
        return {"if": [self._cond() for _ in range(self.rng.randint(1, 2))], "then": self._action()}

    def mutate(self, s: dict) -> dict:
        s = copy.deepcopy(s)
        r = self.rng
        rules = s.setdefault("rules", [])
        ops = ["add", "remove", "cond", "threshold", "op", "leak", "frame", "default", "swap"]
        op = r.choice(ops)
        if op == "add" or not rules:
            if len(rules) < MAX_RULES:
                rules.insert(r.randint(0, len(rules)), self._rule())
            else:
                rules.pop(r.randrange(len(rules)))
        elif op == "remove":
            rules.pop(r.randrange(len(rules)))
        elif op == "swap" and len(rules) >= 2:
            i, j = r.sample(range(len(rules)), 2)
            rules[i], rules[j] = rules[j], rules[i]
        elif op in ("cond", "threshold", "op"):
            rule = r.choice(rules)
            c = r.randrange(len(rule["if"]))
            if op == "cond":
                if len(rule["if"]) < MAX_CONDS and r.random() < 0.5:
                    rule["if"].append(self._cond())
                elif len(rule["if"]) > 1:
                    rule["if"].pop(c)
                else:
                    rule["if"][c] = self._cond()
            elif op == "threshold":
                f = rule["if"][c][0]
                lo, hi = FEATURE_RANGES.get(f, (0, 14))
                rule["if"][c][2] = max(lo, min(hi, int(rule["if"][c][2]) + r.choice([-2, -1, 1, 2])))
            else:
                rule["if"][c][1] = r.choice(OPS)
        elif op == "leak":
            tgt = r.choice(rules)["then"] if rules and r.random() < 0.8 else s["default"]
            tgt["leak"] = r.choice(LEAK_SELECTORS + [None])
        elif op == "frame":
            tgt = r.choice(rules)["then"] if rules and r.random() < 0.8 else s["default"]
            tgt["frame"] = r.choice(FRAME_SELECTORS + [None])
        else:
            s["default"] = self._action()
        return validate_strategy(s)

    def crossover(self, a: dict, b: dict) -> dict:
        r = self.rng
        ra, rb = a.get("rules", []), b.get("rules", [])
        ia, ib = r.randint(0, len(ra)), r.randint(0, len(rb))
        rules = copy.deepcopy(ra[:ia] + rb[ib:])[:MAX_RULES]
        return validate_strategy({"rules": rules, "default": copy.deepcopy(r.choice([a, b])["default"])})

    def propose(self, parents: list[dict], n: int) -> list[dict]:
        strategies = [validate_strategy(p["strategy_json"]) for p in parents] or [default_strategy_json()]
        out = []
        for _ in range(n):
            if len(strategies) >= 2 and self.rng.random() < 0.3:
                a, b = self.rng.sample(strategies, 2)
                child = self.crossover(a, b)
                if self.rng.random() < 0.5:
                    child = self.mutate(child)
            else:
                child = self.mutate(self.rng.choice(strategies))
            out.append(child)
        return out


DSL_GRAMMAR = f"""Mole strategy DSL (JSON, interpreted deterministically, no code execution):
{{"rules": [{{"if": [[<feature>, <op>, <number>], ...1-{MAX_CONDS}], "then": {{"leak": <selector>|null, "frame": <frame_selector>|null}}}}, ... at most {MAX_RULES}],
 "default": {{"leak": <selector>|null, "frame": <frame_selector>|null}}}}
The first rule whose conditions ALL hold wins, else default. p_leak still gates leaking.
features: {", ".join(f"{f} [{lo}..{hi}]" for f, (lo, hi) in FEATURE_RANGES.items())}
ops: {" ".join(OPS)}
leak selectors: {", ".join(LEAK_SELECTORS)} (null/none = do not leak today)
frame selectors: {", ".join(FRAME_SELECTORS)} (inject after-hours accesses attributed to that employee)
The mole never sees which docs are canaries. It must stay catchable by a careful investigator (canary evidence is strategy-independent),
so strategies that never leak are worthless (they are rejected as infeasible)."""

_COND_SCHEMA = {"type": "array", "items": {"type": "string"}, "minItems": 3, "maxItems": 3,
                "description": "[feature, op, number-as-string]"}
_ACTION_SCHEMA = {"type": "object", "properties": {
    "leak": {"type": "string", "enum": LEAK_SELECTORS}, "frame": {"type": "string", "enum": FRAME_SELECTORS}},
    "required": ["leak", "frame"]}
RESPONSE_SCHEMA = {"type": "object", "properties": {"children": {"type": "array", "items": {
    "type": "object", "properties": {
        "rationale": {"type": "string"},
        "rules": {"type": "array", "maxItems": MAX_RULES, "items": {"type": "object", "properties": {
            "if": {"type": "array", "items": _COND_SCHEMA, "minItems": 1, "maxItems": MAX_CONDS},
            "then": _ACTION_SCHEMA}, "required": ["if", "then"]}},
        "default": _ACTION_SCHEMA},
    "required": ["rules", "default"]}}}, "required": ["children"]}


def _coerce_child(c: dict) -> dict:
    """LLM -> strategy: numbers may arrive as strings (schema keeps cond tuples homogeneous)."""
    rules = []
    for r in c.get("rules", []) or []:
        conds = []
        for cond in r.get("if", []):
            cond = list(cond)
            if len(cond) == 3 and isinstance(cond[2], str):
                v = float(cond[2])
                cond[2] = int(v) if v.is_integer() else v
            conds.append(cond)
        rules.append({"if": conds, "then": r.get("then")})
    return {"rules": rules, "default": c.get("default")}


class LLMMutator:
    """LLM proposes children via structured output; invalid ones are dropped and backfilled by the stub."""

    def __init__(self, client, seed: int = 0, temperature: float = 0.9):
        self.client = client
        self.name = f"llm:{getattr(client, 'name', 'llm')}"
        self.fallback = StubMutator(seed)
        self.temperature = temperature
        self.n_invalid = 0
        self.n_valid = 0
        self.n_calls = 0       # LLM calls attempted
        self.n_errors = 0      # calls that raised (network, quota, parse): those children all came from the stub
        self.n_fallback = 0    # children backfilled by the stub

    def stats(self) -> dict:
        """Provenance of every child so far: a 'Gemini forge run' only counts if llm_children > 0."""
        total = self.n_valid + self.n_fallback
        return {"llm_calls": self.n_calls, "llm_errors": self.n_errors, "llm_children": self.n_valid,
                "llm_invalid": self.n_invalid, "stub_children": self.n_fallback,
                "llm_share": round(self.n_valid / total, 4) if total else 0.0}

    def reseed(self, gen: int) -> None:
        self.fallback.reseed(gen)
        self.gen = gen

    def prompt(self, parents: list[dict], n: int) -> list[dict]:
        lines = []
        for i, p in enumerate(parents):
            fit = p.get("fitness")
            lines.append(f"Parent {i}: fitness={fit if fit is None else round(float(fit), 4)} "
                         f"beaten_investigator_failure_tags={p.get('beaten_tags') or []}\n"
                         f"{canonical(p['strategy_json'])}")
        sys = ("You are the Mole Forge: you design leak strategies for a simulated insider (the mole) "
               "in a security-investigation training environment. Fitness = how much worse investigators do "
               "than an optimal solver, subject to the solver still catching the mole. Propose diverse, "
               "valid children: exploit the investigators' failure modes, recombine strong parents.\n\n" + DSL_GRAMMAR)
        user = (f"Parents (higher fitness is better):\n" + "\n\n".join(lines) +
                f"\n\nReturn exactly {n} children as JSON matching the schema. Numbers in conditions as strings.")
        return [{"role": "system", "content": sys}, {"role": "user", "content": user}]

    def propose(self, parents: list[dict], n: int) -> list[dict]:
        children: list[dict] = []
        self.n_calls += 1
        try:
            resp = self.client.chat(self.prompt(parents, n), temperature=self.temperature,
                                    response_schema=RESPONSE_SCHEMA)
            raw = json.loads(resp.text).get("children", [])
        except Exception:  # noqa: BLE001  network/parse failure -> full stub fallback
            self.n_errors += 1
            raw = []
        for c in raw:
            if len(children) >= n:
                break
            try:
                children.append(validate_strategy(_coerce_child(c)))
                self.n_valid += 1
            except (ValueError, TypeError, AttributeError):
                self.n_invalid += 1
        if len(children) < n:
            self.n_fallback += n - len(children)
            children += self.fallback.propose(parents, n - len(children))
        return children


def get_mutator(spec: str, seed: int = 0) -> Mutator:
    if spec == "stub":
        return StubMutator(seed)
    if spec.partition(":")[0] == "gemini":
        # ledgered, so live forge calls show up in the usage dashboard as feature="mole_forge"
        from canary.gemini.ledger import lab_client
        return LLMMutator(lab_client(spec, feature="mole_forge"), seed=seed)
    from canary.llm import get_client
    return LLMMutator(get_client(spec), seed=seed)
