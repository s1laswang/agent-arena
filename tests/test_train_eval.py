import json

import pytest

from train.render import parse_tool_call
from train.eval_hf import main, mean_ci, HFPolicy

NAMES = {"status", "accuse", "advance_day"}


@pytest.mark.parametrize("text,want", [
    ('<tool_call>\n{"name": "accuse", "arguments": {"employee": "e03"}}\n</tool_call><|im_end|>',
     ("accuse", {"employee": "e03"})),
    ('sure! {"name":"advance_day","arguments":"{}"}', ("advance_day", {})),
    ('{"function":{"name":"status","arguments":{}}}', ("status", {})),
    ('<tool_call>{"name": "accuse", "arguments": {"employee": "e0', None),
    ('{"name": "rm_rf", "arguments": {}}', None),
    ("I think it is e03.", None),
    ('{"name": "accuse", "arguments": ["e01"]}', None),
])
def test_parse(text, want):
    assert parse_tool_call(text, NAMES) == want


def test_invalid_output_is_wasted_status_call():
    class P(HFPolicy):
        def generate_text(self, history):
            return "no json here"
    p = P(None, None, "x")
    p.reset([{"name": "status", "input_schema": {}}], "rules")
    assert p.act([]) == ("status", {}) and p.invalid == 1


def test_mean_ci():
    m, h = mean_ci([0.0, 1.0] * 50)
    assert m == 0.5 and 0.09 < h < 0.11


def test_fake_eval_writes_run(tmp_path, capsys):
    main(["--fake", "--n", "4", "--tiers", "easy,medium", "--out", str(tmp_path), "--run-id", "r"])
    eps = [json.loads(l) for l in open(tmp_path / "r" / "episodes.jsonl")]
    assert len(eps) == 8 and all(e["correct"] for e in eps)
    s = json.load(open(tmp_path / "r" / "summary.json"))
    assert s["by_tier"]["all"]["accuracy"] == 1.0
