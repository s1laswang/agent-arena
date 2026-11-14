import dataclasses
import json
from types import SimpleNamespace as NS

from fake_env import FakeEnv


class Stub:
    def __init__(self, script, cost=0.0):
        self.script, self.i, self.cost = script, 0, cost

    def chat(self, messages, tools=None, temperature=0.0, response_schema=None, max_tokens=None):
        s = self.script[min(self.i, len(self.script) - 1)]
        self.i += 1
        calls = [NS(id=f"c{self.i}", name=c["name"], args=c.get("args", {})) for c in s.get("tool_calls", [])]
        return NS(text="", tool_calls=calls, usage={"in": 1, "out": 1, "cost_usd": self.cost})


def _ep(agent="x", seed=0):
    env = FakeEnv(seed=seed)
    env.call("status", {})
    env.call("accuse", {"employee": "e01"})
    d = dataclasses.asdict(env.result(agent))
    d["meta"]["run_id"] = "r"
    return d


def test_tag_report_with_fake_attribute():
    from canary.analysis.tags import tag_report, top_tags
    attr = lambda ep: [{"t": 1, "day": 1, "action": "accuse", "regret": 0.4, "p_best": 0.3, "tags": ["premature_accusation"]},
                       {"t": 0, "day": 1, "action": "status", "regret": 0.0, "p_best": 0.3, "tags": ["budget_waste"]}]
    rep = tag_report([_ep(seed=0), _ep(seed=1)], attr)
    t = rep["x"]["tags"]["premature_accusation"]
    assert t["count"] == 2 and t["rate"] == 1.0 and t["regret_sum"] == 0.8
    assert t["worst"]["tool"] == "accuse" and t["worst"]["args"] == {"employee": "e01"} and "0.30" in t["worst"]["why"]
    assert top_tags(rep, "x", 1) == ["premature_accusation"]


def test_tag_report_real_attribute_on_real_env():
    from canary.analysis.tags import tag_report
    from canary.env import Env
    env = Env(tier="hard", seed=0)
    env.call("status", {})
    env.call("list_employees", {})
    env.call("accuse", {"employee": "e01"})
    rep = tag_report([dataclasses.asdict(env.result("y"))])
    assert "premature_accusation" in rep["y"]["tags"]


def test_ablate_fake(tmp_path):
    from canary.agents import ablate
    script = [{"tool_calls": [{"name": "status"}]}, {"tool_calls": [{"name": "accuse", "args": {"employee": "e03"}}]}]
    table = ablate.main(["--agent", "stub", "--tier", "easy", "--seeds", "0-1", "--tags", "decoy_chase,ignored_delay",
                         "--fake", "--out", str(tmp_path)], client_factory=lambda: Stub(script))
    assert set(table) == {"control", "decoy_chase", "ignored_delay"}
    assert table["control"]["n"] == 2 and table["control"]["score_mean"] == 1.0
    assert (tmp_path / "ablation.md").exists() and json.loads((tmp_path / "decoy_chase" / "meta.json").read_text())["hint"] == "decoy_chase"
    assert "|" in (tmp_path / "ablation.md").read_text()


def test_ablate_budget_stop(tmp_path):
    from canary.agents import ablate
    script = [{"tool_calls": [{"name": "accuse", "args": {"employee": "e03"}}]}]
    ablate.main(["--agent", "stub", "--seeds", "0-3", "--tags", "decoy_chase", "--fake", "--budget", "0.25",
                 "--out", str(tmp_path)], client_factory=lambda: Stub(script, cost=0.1))
    d = json.loads((tmp_path / "ablation.json").read_text())
    assert d["budget_stopped"] and d["table"]["control"]["n"] == 3 and "decoy_chase" not in d["table"]
