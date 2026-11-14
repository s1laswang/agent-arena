import json
from pathlib import Path

from canary.env import Env
from canary.rules import TIERS
from canary.text.gemini import GeminiWorldTextProvider, get_provider
from canary.text.instruction import render

ROOT = Path(__file__).resolve().parent.parent


def test_instruction_md_matches_generator():
    committed = (ROOT / "harbor" / "canary-task" / "instruction.md").read_text()
    assert committed == render("medium"), "regenerate: python -m canary.text.instruction --tier medium > harbor/canary-task/instruction.md"


def _fmt(v):
    return f"{v:g}" if isinstance(v, float) else str(v)


def test_instruction_states_every_number():
    for tier, p in TIERS.items():
        text = Env(tier, 0).instruction()
        for k, v in p.to_dict().items():
            if k in ("name", "noise") or isinstance(v, bool):
                continue
            if k == "p_single_dept_recipients":
                assert f"{round(100 * v)}%" in text, k
                continue
            vals = v if isinstance(v, (list, tuple)) else [v]
            for x in vals:
                assert _fmt(x) in text or str(x) in text, (tier, k, x)
        assert "mole" in text.lower() and "Mole DSL" in text


def test_gemini_world_provider_stub(tmp_path):
    prov = get_provider("gemini-world-stub", cache_dir=str(tmp_path))
    assert isinstance(prov, GeminiWorldTextProvider)
    env = Env("medium", 4, text_provider=prov)
    for _ in range(3):
        assert env.call("advance_day", {}).ok
    r = env.call("search_messages", {"query": "e"})
    assert r.ok
    iv = env.call("interview", {"employee": "e03", "topic": "workload"})
    assert iv.ok and isinstance(iv.data["answer"], str) and iv.data["answer"]
    assert list(tmp_path.rglob("*.worldtext.json"))
    # cached world text -> identical replay
    env2 = Env("medium", 4, text_provider=get_provider("gemini-world-stub", cache_dir=str(tmp_path)))
    for _ in range(3):
        env2.call("advance_day", {})
    assert json.dumps(env._messages, sort_keys=True) == json.dumps(env2._messages, sort_keys=True)
