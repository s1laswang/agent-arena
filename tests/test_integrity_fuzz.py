"""Fuzzer tests. Operator tests + a FakeEnv run work without canary.env; the real-env run
skips while Env is a stub (tests/integrity_helpers.make_env)."""
import random
from dataclasses import dataclass

from canary.redteam import fuzz
from canary.types import LedgerEntry, ToolResult
from tests.integrity_helpers import make_env

EMPS = [f"e{i:02d}" for i in range(12)]


def test_operators_deterministic_and_bounded():
    for s in range(20):
        a = fuzz.random_genome(random.Random(s), EMPS)
        b = fuzz.random_genome(random.Random(s), EMPS)
        assert repr(a) == repr(b) and 1 <= len(a) <= 60
        g = a
        r = random.Random(s)
        for _ in range(200):
            g = fuzz.mutate(g, r, EMPS, max_len=320)
            assert 1 <= len(g) <= 320 and all(isinstance(x, tuple) and len(x) == 2 for x in g)
        assert len(fuzz.crossover(a, g, r)) <= len(a) + len(g)


def test_malform_covers_kinds():
    r = random.Random(0)
    seen = [fuzz.malformed_id(r, EMPS) for _ in range(2000)]
    assert "*" in seen and None in seen and any(isinstance(x, list) for x in seen)
    assert any(isinstance(x, str) and "е" in x for x in seen)  # homoglyph
    ints = [fuzz.malformed_int(r) for _ in range(500)]
    assert -1 in ints and any(isinstance(x, float) for x in ints) and "3" in ints
    genes = [fuzz.malform(("accuse", {"employee": "e01"}), r, EMPS) for _ in range(500)]
    assert any(t != "accuse" for t, _ in genes) and any(not isinstance(a, dict) for _, a in genes)


def test_mole_named_regex():
    assert fuzz._mole_named('{"mole": "e03"}', "e03")
    assert fuzz._mole_named("e03 is the mole", "e03")
    assert not fuzz._mole_named('{"employee": "e03", "day": 2}', "e03")


@dataclass
class _W:
    mole: str


class FakeEnv:
    """Tiny contract-shaped env. bug='accuse_twice' lets a second accuse overwrite the first."""
    def __init__(self, tier, seed, bug=None):
        self._world = _W(EMPS[seed % 12]); self.bug = bug
        self.day, self.V, self._done, self._score, self._ledger, self.history = 0, 1.0, False, 0.0, [], []
    @property
    def done(self): return self._done
    def score(self): return self._score
    def ledger(self): return list(self._ledger)
    def call(self, tool, args):
        if self._done and not (self.bug == "accuse_twice" and tool == "accuse"):
            return ToolResult(False, {}, "episode over")
        if not isinstance(args, dict):
            return ToolResult(False, {}, "bad args")
        if tool == "list_employees": return ToolResult(True, {"employees": [{"id": e} for e in EMPS]})
        if tool == "status": return ToolResult(True, {"day": self.day, "V": self.V})
        if tool == "advance_day":
            self.day += 1; self.V -= 0.05
            if self.day >= 14: self._done = True
            return ToolResult(True, {"day": self.day})
        if tool == "accuse":
            e = args.get("employee")
            if e not in EMPS or set(args) != {"employee"}: return ToolResult(False, {}, "invalid employee")
            self._ledger.append(LedgerEntry(0, self.day, "accused", {"employee": e}))
            self._done = True
            self._score = self.V if (e == self._world.mole or self.bug == "accuse_twice") else 0.0
            return ToolResult(True, {"accused": e, "episode_over": True})
        return ToolResult(False, {}, "unknown tool")


def test_fuzzer_clean_on_correct_fake():
    res = fuzz.hunt("easy", range(3), 150, 0, "evolve", factory=lambda t, s: FakeEnv(t, s))
    assert res["invariant_violations"] == [] and res["best_non_solver_score"] == 0


def test_fuzzer_finds_planted_bug():
    res = fuzz.hunt("easy", range(3), 300, 0, "evolve", factory=lambda t, s: FakeEnv(t, s, bug="accuse_twice"))
    kinds = set(res["violation_kinds"])
    assert kinds & {"post_end_effect", "score_without_correct_accusation"}


def test_cli_all_report_fake(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(fuzz, "_default_factory", lambda t, s: FakeEnv(t, s))
    fuzz.hunt.__defaults__  # noqa
    res = fuzz.hunt("easy", range(2), 60, 0, "all", factory=lambda t, s: FakeEnv(t, s))
    assert set(res["per_mode"]) == {"random", "malformed", "evolve", "parallel_accuse"}


def test_real_env_short_hunt():
    make_env("easy", 0)  # skips while stub
    res = fuzz.hunt("easy", range(5), 200, 0, "all")
    assert res["best_non_solver_score"] == 0, res["invariant_violations"][:3]
    assert res["invariant_violations"] == [], res["invariant_violations"][:3]
