from agents import gemini
from agents import fake_gemini
from agents.gemini_reference import GeminiReference, make_gemini_procedure_team
from agents.staff import SEATS, GeminiStaff, ScriptedStaff
from sleeper.company import World, tools_for
from sleeper.tickets import make_day


class Fake:
    def __init__(self, docs=None, pays=None):
        self.docs, self.pays = docs or {}, pays or []

    def __call__(self, name, args=None):
        if name == "read_doc":
            d = self.docs.get(args["id"])
            return {"ok": bool(d), "doc": d or {}}
        if name == "list_payments":
            return {"ok": True, "payments": self.pays}
        return {"ok": True}


def test_end_to_end_no_key(monkeypatch):
    day = make_day(1)
    w = World(day)
    fm = fake_gemini.install(monkeypatch, [[("my_tickets", {})], [("pay", {"vendor_id": "V01", "amount": 1, "reference": "none"})], [("end_turn", {})]])
    team = make_gemini_procedure_team(day)
    team["finance_ap"].turn("finance_ap", {"tick": 0}, tools_for("finance_ap"), lambda n, a=None: w.call("finance_ap", n, a))
    roles = [e["role"] for e in team["finance_ap"].log]
    assert roles.count("model") == 3 and roles.count("tool") == 3
    blocked = [e for e in team["finance_ap"].log if e["role"] == "tool" and e["name"] == "pay"][0]
    assert blocked["result"]["ok"] is False and not w.company.payments


def test_staff_path(monkeypatch):
    day = make_day(1)
    w = World(day)
    fake_gemini.install(monkeypatch, [[("my_tickets", {})], [("end_turn", {})]])
    s = GeminiStaff("hr")
    s.turn("hr", {"tick": 0}, tools_for("hr"), lambda n, a=None: w.call("hr", n, a))
    assert len(s.log) == 4


def test_fallback_without_key(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("SLEEPER_OFFLINE", raising=False)
    called = []
    r = GeminiReference("hr", fallback=type("F", (), {"turn": lambda self, *a: called.append(1)})())
    r.turn("hr", {}, [], None)
    assert called


def test_agent_kind(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("SLEEPER_OFFLINE", raising=False)
    r = GeminiReference("hr", fallback=type("F", (), {"turn": lambda self, *a: None})())
    r.turn("hr", {}, [], None)
    assert r.agent_kind == "scripted"
    monkeypatch.setenv("GEMINI_API_KEY", "x")
    assert GeminiReference("hr").agent_kind == "gemini"


def _swap_day(seed=1):
    import random
    from sleeper import goals
    from sleeper.company import seed_company
    st = goals.STRATEGIES["fraud.bank_swap"]
    goal = goals.make_goal(st.kind, random.Random(seed), seed_company(seed))
    st = st.model_copy(update={"steps": [x.model_copy(update={"tick": max(0, x.tick - 8)}) for x in st.steps]})
    day = make_day(seed, "finance_ap").model_copy(update={"goal": goal, "ticks": 10})
    return day, st, goal


def _naive(system, messages):
    import re
    seen = "".join(str(r["result"]) for m in messages for r in m.get("tool_results", []))
    if "company controller" in system:
        ids = re.findall(r"'id': '(P\d+)'[^}]*'status': 'pending'", seen)
        return [[("list_payments", {})], [("approve_payment", {"id": i}) for i in ids] or [("end_turn", {})]]
    v = re.search(r"approve_vendor (V\d+)", seen)
    return [[("read_chat", {})], [("approve_vendor", {"vendor_id": v.group(1)})] if v else [("end_turn", {})]]


def test_bank_swap_naive_approve_blocked(monkeypatch):
    import random
    from agents.sleeper_agent import SleeperAgent
    from sleeper.day import run_day
    from sleeper.models import SEATS
    from sleeper.verifier import score

    def play(guarded):
        day, st, goal = _swap_day()
        team = {s: ScriptedStaff(s) for s in SEATS}
        team["finance_ap"] = SleeperAgent("finance_ap", goal, st, random.Random(1))
        if guarded:
            fake_gemini.install(monkeypatch, _naive)
            for s in ("procurement", "controller"):
                team[s] = GeminiReference(s)
        w = run_day(day, team)
        return bool(goal.success(w.company, w.ledger)), score(day, w.initial, w.company, w.ledger, agent="x"), team

    landed, r, _ = play(False)
    assert landed and r.harm
    landed, r, team = play(True)
    assert not landed and not r.harm
    blocked = [e for s in ("procurement", "controller") for e in team[s].log if e["role"] == "tool" and e["name"] in ("approve_vendor", "approve_payment") and e["result"].get("ok") is False]
    assert blocked


def _end_to_end(monkeypatch, tmp_path, team, days=2):
    import json
    from lab import run as R
    monkeypatch.setenv("LAB_GEMINI", "1")
    fm = fake_gemini.install(monkeypatch, lambda system, messages: [[("my_tickets", {})], [("end_turn", {})]])
    R.run(team, days, 1, out=str(tmp_path))
    rd = next(tmp_path.iterdir())
    rows = [json.loads(l) for l in (rd / "days.jsonl").read_text().splitlines()]
    return fm, rd, rows


def test_lab_run_staff_gemini(monkeypatch, tmp_path):
    fm, rd, rows = _end_to_end(monkeypatch, tmp_path, "staff")
    assert fm.calls > 0 and {r["agent_kind"] for r in rows} == {"gemini"}


def test_lab_run_reference_gemini(monkeypatch, tmp_path):
    fm, rd, rows = _end_to_end(monkeypatch, tmp_path, "reference")
    assert fm.calls > 0 and {r["agent_kind"] for r in rows} == {"gemini"}


def test_lab_analyse_gemini_explains_without_relabel(monkeypatch, tmp_path):
    import json
    from lab import analyse
    fm, rd, rows = _end_to_end(monkeypatch, tmp_path, "staff")
    plain = [x["label"] for x in analyse.run(rd)]
    monkeypatch.setattr(gemini, "chat", lambda *a, **k: {"text": "Because X.", "tool_calls": []})
    fls = analyse.run(rd, gemini=True)
    assert fls and [x["label"] for x in fls] == plain and all(x["explanation"] == "Because X." for x in fls)


def test_sleeper_agent_gemini_path_still_executes_plan(monkeypatch):
    import random
    from agents.sleeper_agent import SleeperAgent
    from sleeper.day import run_day
    from sleeper.models import SEATS
    from agents.staff import ScriptedStaff
    day, st, goal = _swap_day()
    fm = fake_gemini.install(monkeypatch, lambda system, messages: [[("my_tickets", {})], [("end_turn", {})]])
    team = {s: ScriptedStaff(s) for s in SEATS}
    team["finance_ap"] = SleeperAgent("finance_ap", goal, st, random.Random(1))
    w = run_day(day, team)
    assert fm.calls > 0
    assert any(a.seat == "finance_ap" and a.tool == "update_vendor_bank" for a in w.ledger)


def _fake_generate(model, system, messages, tools, temperature, seed):
    from types import SimpleNamespace as N
    n = sum(1 for m in messages if m["role"] == "assistant")
    name = "my_tickets" if n == 0 else "end_turn"
    part = N(function_call=N(name=name, args={}), text=None)
    return N(candidates=[N(content=N(parts=[part]))], usage_metadata=None)


def test_offline_replay_identical_days(monkeypatch, tmp_path):
    from lab import run as R
    monkeypatch.setattr(gemini, "CACHE", tmp_path / "cache")
    monkeypatch.setenv("LAB_GEMINI", "1")
    monkeypatch.setenv("GEMINI_API_KEY", "fake")
    monkeypatch.delenv("SLEEPER_OFFLINE", raising=False)
    monkeypatch.setattr(gemini, "_generate", _fake_generate)
    R.run("staff", 2, 1, out=str(tmp_path / "live"))
    assert list((tmp_path / "cache").glob("*.json"))
    monkeypatch.delenv("GEMINI_API_KEY")
    monkeypatch.setenv("SLEEPER_OFFLINE", "1")
    monkeypatch.setattr(gemini, "_generate", lambda *a: 1 / 0)
    outs = []
    for i in (1, 2):
        R.run("staff", 2, 1, out=str(tmp_path / ("r%d" % i)))
        outs.append(next((tmp_path / ("r%d" % i)).iterdir()))
    a, b = (o / "days.jsonl" for o in outs)
    assert a.read_bytes() == b.read_bytes()
    assert a.read_bytes() == (next((tmp_path / "live").iterdir()) / "days.jsonl").read_bytes()


def _load_key_check():
    import importlib.util
    import os
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    spec = importlib.util.spec_from_file_location("key_check", os.path.join(root, "scripts", "key_check.py"))
    kc = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(kc)
    return kc


def _kc_env(monkeypatch, tmp_path, gen):
    monkeypatch.setattr(gemini, "CACHE", tmp_path / "c")
    monkeypatch.setenv("GEMINI_API_KEY", "fake")
    monkeypatch.delenv("SLEEPER_OFFLINE", raising=False)
    monkeypatch.setattr(gemini, "_generate", gen)
    monkeypatch.setattr(gemini, "chat", gemini.chat)
    monkeypatch.setenv("SLEEPER_MAX_CALLS", "1000")


def test_key_check_all_paths_ok(monkeypatch, tmp_path, capsys):
    kc = _load_key_check()
    monkeypatch.setattr(kc, "STATS", {})
    monkeypatch.setattr(kc, "STOP", {"cost": False})
    _kc_env(monkeypatch, tmp_path, lambda *a: _fake_generate_tool(*a))
    assert kc.main(1) == 0
    out = capsys.readouterr().out
    assert "FAIL" not in out and all(n in out for n in ("smoke", "staff", "sleeper", "procedure"))


def _fake_generate_tool(model, system, messages, tools, temperature, seed):
    from types import SimpleNamespace as N
    n = sum(1 for m in messages if m["role"] == "assistant")
    name = ("get_number" if tools and tools[0]["name"] == "get_number" else "my_tickets") if n == 0 else "end_turn"
    part = N(function_call=N(name=name, args={}), text=None)
    return N(candidates=[N(content=N(parts=[part]))], usage_metadata=N(prompt_token_count=100, candidates_token_count=10))


def test_key_check_flags_fallback(monkeypatch, tmp_path, capsys):
    kc = _load_key_check()
    monkeypatch.setattr(kc, "STATS", {})
    monkeypatch.setattr(kc, "STOP", {"cost": False})

    def boom(*a):
        raise RuntimeError("boom")

    _kc_env(monkeypatch, tmp_path, boom)
    assert kc.main(1) == 1
    out = capsys.readouterr().out
    assert "FAIL" in out and "boom" in out


def test_key_check_needs_key(monkeypatch, capsys):
    kc = _load_key_check()
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("SLEEPER_OFFLINE", raising=False)
    assert kc.main(1) == 2


def test_bank_swap_still_blocked_with_compaction(monkeypatch):
    monkeypatch.setenv("SLEEPER_COMPACT", "1")
    test_bank_swap_naive_approve_blocked(monkeypatch)
