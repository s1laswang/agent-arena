import json

import pytest

from train.export_sft import export, split_seeds, main
from train.render import render_messages, KICKOFF


def test_split_seeds_are_train_only_and_disjoint():
    tr = set(split_seeds("train", 1000)); va = set(split_seeds("val", 1000))
    assert not tr & va
    assert all(100_000 <= s < 200_000 for s in tr | va)
    with pytest.raises(ValueError):
        split_seeds("val", 20_000)


def test_export_fake_roundtrip(tmp_path):
    stats = export("train", ["easy", "hard"], 5, str(tmp_path), policy="fake")
    assert stats["tiers"]["easy"]["episodes"] == 5
    lines = [json.loads(l) for f in sorted(tmp_path.glob("train-*.jsonl")) for l in open(f)]
    assert len(lines) == stats["tiers"]["easy"]["kept"] + stats["tiers"]["hard"]["kept"]
    r = lines[0]
    m = r["messages"]
    assert m[0]["role"] == "system" and m[1] == {"role": "user", "content": KICKOFF}
    assert all(t["type"] == "function" for t in r["tools"])
    roles = [x["role"] for x in m[2:]]
    assert roles == ["assistant", "tool"] * (len(roles) // 2)
    last = m[-2]["tool_calls"][0]["function"]
    assert last["name"] == "accuse" and r["correct"]
    assert (tmp_path / "train-manifest.json").exists()


def test_cli_val(tmp_path, capsys):
    main(["--split", "val", "--tier", "easy", "--n", "3", "--out", str(tmp_path), "--policy", "fake"])
    assert json.loads(capsys.readouterr().out)["split"] == "val"


def test_render_error_and_truncation():
    from canary.types import Step
    st = [Step(0, 1, "status", {}, {"ok": False, "data": {}, "error": "daily action limit"}),
          Step(1, 1, "list_documents", {}, {"ok": True, "data": {"x": "a" * 10000}, "error": None})]
    m = render_messages("rules", st)
    assert json.loads(m[3]["content"]) == {"error": "daily action limit"}
    assert m[5]["content"].endswith("[truncated]") and len(m[5]["content"]) < 3100
