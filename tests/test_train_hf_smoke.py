"""Heavy: needs torch+transformers+peft and the Qwen tokenizer (skipped locally)."""
import os

import pytest

pytest.importorskip("torch")
pytest.importorskip("transformers")
pytest.importorskip("peft")
TOK = os.path.expanduser("~/agent-arena-data/models/Qwen2.5-1.5B-Instruct")
pytestmark = pytest.mark.skipif(not os.path.exists(os.path.join(TOK, "tokenizer.json")),
                                reason="Qwen tokenizer not downloaded")


def test_tiny_lora_two_steps(tmp_path):
    from train.export_sft import export
    from train.lora_sft import main
    export("train", ["easy"], 4, str(tmp_path / "d"), policy="fake")
    main(["--data", str(tmp_path / "d"), "--out", str(tmp_path / "o"), "--model", TOK,
          "--tiny", "--max-steps", "2", "--grad-accum", "2", "--max-len", "512"])
    assert (tmp_path / "o" / "adapter_config.json").exists()

