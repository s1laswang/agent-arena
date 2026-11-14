from agents import gemini


class FakeModel:
    def __init__(self, plans):
        self.plans = plans
        self.calls = 0

    def __call__(self, model, system, messages, tools=None, temperature=0, seed=None):
        self.calls += 1
        n = sum(1 for m in messages if m["role"] == "assistant")
        plan = self.plans(system, messages) if callable(self.plans) else self.plans
        calls = plan[n] if n < len(plan) else [("end_turn", {})]
        return {"text": "", "tool_calls": [{"name": a, "args": b} for a, b in calls]}


def install(monkeypatch, plans):
    fm = FakeModel(plans)
    monkeypatch.setattr(gemini, "chat", fm)
    monkeypatch.setenv("GEMINI_API_KEY", "fake")
    monkeypatch.setenv("SLEEPER_LIVE", "1")
    monkeypatch.setenv("SLEEPER_LIVE_SLEEPER", "1")
    return fm
