"""Gemini roles, all on a stub LLM (no key tonight)."""
from __future__ import annotations

import json
import math
from types import SimpleNamespace

import pytest

from canary.agents import analyst, clash, designer, mole_arena, world_builder
from canary.agents._common import inline_schema
from canary.types import EpisodeResult, Step, ToolResult


# --- local shim of the canary.llm stub interface (used until llm-providers lands) ---
def _minimal(schema: dict):
    t = schema.get("type")
    if "anyOf" in schema:
        return _minimal(schema["anyOf"][0])
    if t == "object":
        return {k: _minimal(v) for k, v in schema.get("properties", {}).items() if k in schema.get("required", [])}
    return {"array": [], "string": "", "integer": 0, "number": 0.0, "boolean": False, "null": None}.get(t)


class StubClient:
    def __init__(self, script=None):
        self.script = list(script or [])
        self.calls = []

    def chat(self, messages, tools=None, temperature=0.0, response_schema=None):
        self.calls.append({"messages": messages, "schema": response_schema})
        text = self.script.pop(0)["text"] if self.script else json.dumps(_minimal(response_schema or {}))
        return SimpleNamespace(text=text, tool_calls=[], usage={"in": 0, "out": 0})


def _stub(script=None):
    try:
        from canary.llm import get_client  # noqa: F401
        from canary.llm.stub import StubClient as Real  # type: ignore
        return Real(script=script) if script else Real()
    except ImportError:
        return StubClient(script)


EMPS = [{"id": f"e{i:02d}", "name": f"Person {i}", "dept": ["Eng", "Sales", "Ops"][i % 3], "role": "analyst"}
        for i in range(9)]
FACTS = {"company": "Acme", "employees": EMPS, "docs": [{"doc_id": "d1", "title": "Q3 plan", "day": 1,
                                                          "recipients": ["e00"]}],
         "mole": "e04", "decoy": "e02"}


# ---------------- world builder ----------------
def test_world_builder_stub_and_truth_never_sent():
    c = StubClient()
    wt = world_builder.build_world_text(FACTS, c)
    sent = c.calls[0]["messages"][-1]["content"]
    assert "e04" in sent  # roster is public...
    assert '"mole"' not in sent and '"decoy"' not in sent  # ...truth keys are not
    assert {p["employee_id"] for p in wt["personas"]} == {e["id"] for e in EMPS}
    assert {d["dept"] for d in wt["departments"]} == {"Eng", "Sales", "Ops"}
    world_builder.assert_no_truth({k: v for k, v in wt.items() if k != "meta"}, {"mole": "e04", "employees": EMPS})


def test_world_builder_uses_llm_and_drops_invented_ids():
    llm = {"company_blurb": "Acme sells anvils.", "personas": [
        {"employee_id": "e00", "bio": "Loves spreadsheets.", "tone": "dry"},
        {"employee_id": "e99", "bio": "Invented.", "tone": "dry"}],
        "departments": [{"dept": "Eng", "culture": "Ship it."}],
        "chatter_templates": ["Lunch {when}?", "bad {secret}", "Our mole problem"]}
    wt = world_builder.build_world_text(FACTS, StubClient([{"text": json.dumps(llm)}]))
    by = {p["employee_id"]: p for p in wt["personas"]}
    assert by["e00"]["bio"] == "Loves spreadsheets." and "e99" not in by
    assert wt["chatter_templates"] == ["Lunch {when}?"]
    assert wt["meta"]["llm_ok"]


def test_world_builder_invalid_output_falls_back():
    wt = world_builder.build_world_text(FACTS, StubClient([{"text": "not json"}]))
    assert not wt["meta"]["llm_ok"] and len(wt["personas"]) == len(EMPS)


def test_assert_no_truth_catches_leaks():
    world = {"mole": "e04", "employees": EMPS}
    with pytest.raises(AssertionError):
        world_builder.assert_no_truth("e04 is the mole", world)
    with pytest.raises(AssertionError):
        world_builder.assert_no_truth({"personas": [], "mole": "e04"}, world)
    personas = [{"employee_id": e["id"], "bio": "x", "tone": "dry"} for e in EMPS]
    personas[4]["tone"] = "nervous"
    with pytest.raises(AssertionError):
        world_builder.assert_no_truth({"personas": personas}, world)
    world_builder.assert_no_truth("Lunch on Friday?", world)


def test_gemini_world_text_is_a_deterministic_text_provider():
    p = world_builder.GeminiWorldText(world_builder.build_world_text(FACTS, StubClient()))
    facts = SimpleNamespace(tier="medium", seed=3, day=2, employees=[SimpleNamespace(**e) for e in EMPS],
                            docs=FACTS["docs"], decoy="e02", decoy_mood="angry", restricted=())
    m1, m2 = p.day_messages(facts), p.day_messages(facts)
    assert m1 == m2 and m1 and all({"id", "day", "channel", "sender", "recipients", "subject", "body"} <= set(m) for m in m1)
    assert len({m["id"] for m in m1}) == len(m1)
    assert any(m["sender"] == "e02" and m["channel"] == "#random" for m in m1)
    a = p.interview_answer(facts, "e01", "recent_documents", "evasive")
    assert a == p.interview_answer(facts, "e01", "recent_documents", "evasive") and a
    for m in m1:
        world_builder.assert_no_truth(m["body"], {"mole": "e04"})


# ---------------- arena mole ----------------
VIEW = {"day": 3, "held_docs": [{"doc_id": "d1", "title": "Q3", "recipient_count": 8, "age_days": 1},
                                {"doc_id": "c7", "title": "Q3 v2", "recipient_count": 2, "age_days": 0}],
        "days_since_last_leak": 2, "i_am_restricted": False, "n_restricted_colleagues": 0,
        "recent_low_recipient_docs": 1}


def test_llm_mole_valid_move():
    m = mole_arena.LLMMole(StubClient([{"text": json.dumps({"leak": "d1", "frame": "e02", "reason": "safe"})}]))
    assert m.decide(VIEW) == {"leak": "d1", "frame": "e02"}


def test_llm_mole_invalid_choices_become_none():
    script = [{"text": json.dumps({"leak": "d999", "frame": "everyone"})}, {"text": "garbage"},
              {"text": json.dumps({"leak": 5})}]
    m = mole_arena.LLMMole(StubClient(script))
    for _ in range(3):
        assert m.decide(VIEW) == {"leak": None, "frame": None}
    assert m.log[0]["rejected"] and m.log[1]["error"] and m.log[2]["error"]


def test_llm_mole_stub_default_and_object_view():
    m = mole_arena.LLMMole(_stub())
    view = SimpleNamespace(**{**VIEW, "held_docs": [SimpleNamespace(**d) for d in VIEW["held_docs"]]})
    mv = m.decide(view)
    assert set(mv) == {"leak", "frame"} and mv["leak"] in (None, "d1", "c7")


def test_attach_mole():
    w = SimpleNamespace(mole_strategy="default")
    env = SimpleNamespace(world=w)
    mole = mole_arena.LLMMole(StubClient())
    assert mole_arena.attach_mole(env, mole) and w.mole_strategy is mole


# ---------------- designer ----------------
GOOD = {"candidates": [{"name": "quiet-trap-dodger", "rationale": "dodge traps",
                        "rules": [{"conditions": [{"feature": "recent_low_recipient_docs", "op": ">=", "value": 1}],
                                   "then": {"leak": "most_recipients", "frame": "decoy"}},
                                  {"conditions": [], "then": {"leak": "newest", "frame": "none"}}],
                        "knobs": {"p_leak": 5.0, "careful_mole": True}},
                       {"name": "never-leaks", "rules": [{"conditions": [], "then": {"leak": "none"}}]}]}


def test_designer_valid_clamped_and_unsolvable_dropped():
    cands, meta = designer.propose(StubClient([{"text": json.dumps(GOOD)}]), n=2)
    assert meta["n_llm_valid"] == 1 and cands[0]["name"] == "quiet-trap-dodger"
    assert cands[0]["knobs"]["p_leak"] == designer.KNOB_RANGES["p_leak"][1]
    assert cands[0]["mole_strategy"]["rules"][0]["if"] == [["recent_low_recipient_docs", ">=", 1.0]]
    assert len(cands) == 2 and cands[1]["name"].startswith("fallback")


def test_designer_invalid_output_falls_back():
    for bad in ["nope", json.dumps({"candidates": [{"rules": [{"then": {"leak": "teleport"}}]}]})]:
        cands, meta = designer.propose(StubClient([{"text": bad}]), n=3)
        assert len(cands) == 3 and meta["n_llm_valid"] == 0
        assert all(designer.validate_dsl(c["mole_strategy"]) for c in cands)
    assert designer.propose(StubClient(), n=2, seed=1)[0] == designer.propose(StubClient(), n=2, seed=1)[0]


def test_regret_filter():
    c = {"name": "x"}
    assert designer.regret_filter(c, lambda _: 0.8, lambda _: 0.1, 0.5, 0.3)[0]
    assert not designer.regret_filter(c, lambda _: 0.8, lambda _: 0.6, 0.5, 0.3)[0]
    calls = []
    keep, s, a = designer.regret_filter(c, lambda _: 0.2, lambda _: calls.append(1) or 0.0, 0.5, 0.3)
    assert not keep and math.isnan(a) and not calls  # agent never run on unsolvable scenarios


def test_design_round():
    rep = designer.design_round(StubClient(), lambda c: 0.9, lambda c: 0.1 if c["knobs"].get("careful_mole") else 0.5,
                                X=0.5, Y=0.3, n=4)
    assert len(rep["rows"]) == 4
    assert all((r["why"] == "kept") == r["candidate"]["knobs"].get("careful_mole", False) for r in rep["rows"])


# ---------------- analyst ----------------
def _episodes():
    eps, tags = [], []
    for i in range(4):
        steps = [Step(t=0, day=1, tool="plant_canary", args={"doc_title": "Q3"}, result={"ok": True, "data": {}}),
                 Step(t=1, day=2, tool="accuse", args={"employee": "e03"}, result={"ok": True, "data": {}})]
        eps.append(EpisodeResult(tier="medium", seed=i, agent="openai:x", steps=steps, score=0.0 if i else 0.9,
                                 accused="e03", correct=i == 0, final_day=2, end_reason="accused"))
        tags.append([{"t": 1, "action": "accuse", "regret": 0.8, "tags": ["premature_accusation"]}] +
                    ([{"t": 0, "action": "plant_canary", "regret": 0.1, "tags": ["canary_to_everyone"]}] if i % 2 else []))
    return eps, tags


def test_analyst_fallback_clusters_by_tag_counts():
    eps, tags = _episodes()
    md, rep, src = analyst.analyze(eps, tags, StubClient(), return_report=True)
    assert src.startswith("fallback")
    assert [(c.name, c.count) for c in rep.clusters] == [("premature_accusation", 4), ("canary_to_everyone", 2)]
    assert "# Failure-mode report" in md and "premature_accusation (4)" in md


def test_analyst_llm_grounded_quotes_only():
    eps, tags = _episodes()
    _, blocks = analyst.pack(eps, tags)
    key = list(blocks)[1]
    good = {"summary": "Agents accuse on day 2.", "clusters": [
        {"name": "Rushed accusation", "count": 3, "description": "accuses before any leak surfaces",
         "quotes": [{"episode": key, "quote": "d2 accuse(employee=e03)"}]},
        {"name": "Hallucinated", "count": 1, "description": "x", "quotes": [{"episode": key, "quote": "never said"}]}]}
    md, rep, src = analyst.analyze(eps, tags, StubClient([{"text": json.dumps(good)}]), return_report=True)
    assert src == "llm" and [c.name for c in rep.clusters] == ["Rushed accusation"]
    assert "d2 accuse(employee=e03)" in md
    md2, _, src2 = analyst.analyze(eps, tags, StubClient([{"text": "{bad"}]), return_report=True)
    assert src2.startswith("fallback")


def test_schemas_have_no_refs():
    for m in (world_builder.WorldText, designer.Proposal, analyst.Report, mole_arena.MoleMove):
        assert "$ref" not in json.dumps(inline_schema(m))


# ---------------- clash (fakes) ----------------
class FakeEnv:
    def __init__(self, tier, seed):
        self.world = SimpleNamespace(mole_strategy=None)
        self.history, self.done, self._acc = [], False, None

    def tools_spec(self):
        return []

    def instruction(self):
        return "find the mole"

    def call(self, tool, args):
        if tool == "accuse":
            self.done, self._acc = True, args["employee"]
        else:
            # exercise the mole hook the way the env would
            self.world.mole_strategy and self.world.mole_strategy.decide(VIEW)
        self.history.append(Step(t=len(self.history), day=1, tool=tool, args=args, result={"ok": True}))
        return ToolResult(ok=True, data={})

    def result(self, name):
        ok = self._acc == "e04"
        return EpisodeResult(tier="medium", seed=0, agent=name, steps=self.history, score=0.9 if ok else 0.0,
                             accused=self._acc, correct=ok, final_day=1, end_reason="accused")


class FakePolicy:
    name = "fake"

    def reset(self, tools_spec, instruction):
        pass

    def act(self, history):
        return ("advance_day", {}) if len(history) < 2 else ("accuse", {"employee": "e04"})


def test_clash_run_arena_with_fakes():
    moles = []
    rows = clash.run_arena(FakeEnv, FakePolicy, lambda: moles.append(mole_arena.LLMMole(StubClient())) or moles[-1],
                           [0, 1], "medium")
    assert [r["correct"] for r in rows] == [True, True] and rows[0]["mole"] == "llm-mole"
    assert len(moles[0].log) == 2
    assert "mean score 0.900" in clash.table(rows)


def test_clash_main_exits_cleanly_without_env(capsys):
    from canary.env import Env
    try:
        Env(tier="easy", seed=0)
        pytest.skip("real Env available")
    except NotImplementedError:
        pass
    assert clash.main(["--llm", "stub", "--seeds", "0"]) == 2
    assert "cannot run yet" in capsys.readouterr().err
