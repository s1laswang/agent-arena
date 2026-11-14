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



def test_kv_reuse_matches_full_reencode():
    """Tiny random Qwen2 + real tokenizer: greedy text with KV reuse == without, over turns."""
    import torch
    from transformers import AutoTokenizer, Qwen2Config, Qwen2ForCausalLM
    from train.eval_hf import HFPolicy
    from train.fake import FakeEnv
    tok = AutoTokenizer.from_pretrained(TOK)
    cfg = Qwen2Config(vocab_size=151936, hidden_size=64, intermediate_size=128, num_hidden_layers=2,
                      num_attention_heads=4, num_key_value_heads=2)
    torch.manual_seed(0)
    model = Qwen2ForCausalLM(cfg).eval()
    env = FakeEnv("easy", 0)
    a = HFPolicy(model, tok, "a", max_new=8, kv_reuse=True)
    b = HFPolicy(model, tok, "b", max_new=8, kv_reuse=False)
    for p in (a, b):
        p.reset(env.tools_spec(), env.instruction())
    for tool in ["list_employees", "check_leak_feed", "advance_day", "check_leak_feed"]:
        env.call(tool, {})
        assert a.generate_text(env.history) == b.generate_text(env.history)
    assert a.reused > 0
