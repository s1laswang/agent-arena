from train.eval import model_id
from lab.run import agent_model

def test_ids(monkeypatch):
    assert model_id("Qwen/Qwen2.5-0.5B-Instruct", "a", "run3").startswith("Qwen2.5-0.5B-Instruct+run3+")
    assert "+base+" in model_id("Qwen/Qwen2.5-0.5B-Instruct", None, "run3")
    monkeypatch.setenv("SLEEPER_MODEL_ID", "x+y+z")
    assert agent_model("local:a@b") == "x+y+z"
