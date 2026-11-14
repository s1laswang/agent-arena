"""Keyless: the Mole Forge logs how many children Gemini actually wrote (vs stub backfill)."""
import json
from types import SimpleNamespace

from canary.forge import evolve
from canary.forge.mutate import LLMMutator, default_strategy_json, validate_strategy

CHILD = {"rules": [{"if": [["day", ">=", "3"]], "then": {"leak": "newest", "frame": "decoy"}}],
         "default": {"leak": "random_seeded", "frame": "none"}}


class FakeClient:
    name = "fake-gemini"

    def __init__(self, fail=False):
        self.fail = fail

    def chat(self, messages, temperature=None, response_schema=None):
        if self.fail:
            raise RuntimeError("quota")
        return SimpleNamespace(text=json.dumps({"children": [CHILD, {"rules": "bad"}]}))


def _parents():
    return [{"strategy_json": validate_strategy(default_strategy_json()), "fitness": 0.1, "beaten_tags": []}]


def test_counts_llm_and_stub_children():
    m = LLMMutator(FakeClient(), seed=0)
    m.reseed(0)
    out = m.propose(_parents(), 4)
    assert len(out) == 4
    s = m.stats()
    assert (s["llm_calls"], s["llm_errors"], s["llm_children"], s["llm_invalid"], s["stub_children"]) == (1, 0, 1, 1, 3)
    assert s["llm_share"] == 0.25


def test_failed_calls_are_all_stub():
    m = LLMMutator(FakeClient(fail=True), seed=0)
    m.reseed(0)
    m.propose(_parents(), 3)
    s = m.stats()
    assert s["llm_errors"] == 1 and s["llm_children"] == 0 and s["stub_children"] == 3 and s["llm_share"] == 0.0


def test_log_carries_mutator_stats(tmp_path, monkeypatch):
    monkeypatch.setattr(evolve, "get_mutator", lambda spec, seed=0: LLMMutator(FakeClient(), seed=seed))
    evolve.run("gemini:fake", tier="hard", pop_size=4, gens=2, seeds=range(2), out=tmp_path, fake=True, log=lambda *a: None)
    last = json.loads((tmp_path / "log.jsonl").read_text().splitlines()[-1])
    assert last["mutator"] == "llm:fake-gemini"
    assert last["mutator_stats"]["llm_children"] >= 1
