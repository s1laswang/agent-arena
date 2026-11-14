import json
import subprocess

from train.export_sft import export
from train.to_mlx import main, trim
from train.eval_hf import MLXPolicy


def test_to_mlx_layout(tmp_path):
    export("train", ["easy"], 4, str(tmp_path / "d"), policy="fake")
    export("val", ["easy"], 2, str(tmp_path / "d"), policy="fake")
    main(["--train", str(tmp_path / "d/train-*.jsonl"), "--val", str(tmp_path / "d/val-*.jsonl"),
          "--out", str(tmp_path / "m")])
    rows = [json.loads(l) for l in open(tmp_path / "m/train.jsonl")]
    assert len(rows) == 4 and set(rows[0]) == {"messages", "tools"}
    assert rows[0]["messages"][-1]["role"] == "assistant"


def test_trim_ends_at_assistant():
    rec = {"tools": [], "messages": [{"role": "system", "content": "s"}, {"role": "user", "content": "u"}]
           + [{"role": "assistant", "content": "x" * 50}, {"role": "tool", "content": "y" * 50}] * 10}
    t = trim(rec, 300)
    assert t["messages"][-1]["role"] == "assistant" and 2 < len(t["messages"]) < 22


def test_mlx_policy_shares_parse_path():
    class P(MLXPolicy):
        def generate_text(self, history):
            return '<tool_call>{"name":"status","arguments":{}}</tool_call>'
    p = P(None, None, "m")
    p.reset([{"name": "status", "input_schema": {}}], "r")
    assert p.act([]) == ("status", {}) and p.invalid == 0


def test_mlx_script_syntax_and_help():
    subprocess.run(["bash", "-n", "train/mlx_lora.sh"], check=True)
    out = subprocess.run(["bash", "train/mlx_lora.sh", "--help"], capture_output=True, text=True, check=True)
    assert "--size" in out.stdout


def test_merge_scripts_syntax(tmp_path):
    for f in ["train/peft_to_mlx.sh", "fr8/j4_merge.sbatch"]:
        subprocess.run(["bash", "-n", f], check=True)
    (tmp_path / "adapter_config.json").write_text('{"base_model_name_or_path": "/m/base"}')
    from train.merge_peft import base_of
    assert base_of(str(tmp_path), None) == "/m/base" and base_of(str(tmp_path), "/x") == "/x"


def test_mlx_name_without_adapter(monkeypatch):
    import sys, types
    fake = types.ModuleType("mlx_lm")
    fake.load = lambda spec, adapter_path=None: ("M", "T")
    monkeypatch.setitem(sys.modules, "mlx_lm", fake)
    from train.eval_hf import load_mlx
    assert load_mlx("data/fr8/j4/run-44397/mlx-4bit", None) == ("M", "T", "mlx:mlx-4bit")
