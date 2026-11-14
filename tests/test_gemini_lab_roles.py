"""Canary Lab roles runner (G5): dev-seed guard, p_leak gate, index built from result files. Keyless."""
import json
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest

from canary.gemini import roles

FX = Path(__file__).parent / "fixtures" / "gemini_lab"


def test_judge_seeds_are_refused():
    from canary.rules import JUDGE_SEEDS
    assert roles.dev_only([0, 1, 2]) == [0, 1, 2]
    with pytest.raises(SystemExit):
        roles.dev_only([0, list(JUDGE_SEEDS)[0]])
    assert roles.parse_seeds("0-2,5") == [0, 1, 2, 5]


class _Client:
    model = "fake"

    def chat(self, messages, tools=None, temperature=0.0, response_schema=None, **kw):
        return SimpleNamespace(text=json.dumps({"leak": "d1", "frame": "e03", "reason": "test"}))


def test_gated_mole_respects_p_leak_gate():
    m = roles.GatedLLMMole(_Client())
    doc = SimpleNamespace(doc_id="d1", title="T", recipient_count=3, age_days=0)
    open_ = SimpleNamespace(day=1, docs=(doc,), days_since_last_leak=1, i_am_restricted=0, n_restricted_colleagues=0,
                            recent_low_recipient_docs=0, peers=("e03",), can_leak=True)
    closed = SimpleNamespace(**{**vars(open_), "day": 2, "can_leak": False})
    assert m.decide(open_) == {"leak": "d1", "frame": "e03"}
    assert m.decide(closed) == {"leak": None, "frame": "e03"}
    assert m.days[1]["gemini_move"]["leak"] == "d1" and not m.days[1]["p_leak_gate_open"]


def test_index_and_roles_md_from_result_files(tmp_path):
    res = tmp_path / "res"
    shutil.copytree(FX / "results", res)
    (res / "roles" / "mole").mkdir(parents=True)
    (res / "roles" / "mole" / "meta.json").write_text(json.dumps(
        {"model": "gemini-4-carbon", "thinking_level": "medium", "git_sha": "abc1234567890", "finished_at": "t",
         "seeds": [0, 1], "investigators": ["solver"], "tier": "medium"}))
    (res / "roles" / "mole" / "summary.json").write_text(json.dumps({"by_investigator": {"solver": {
        "n": 2, "gemini_mole_mean_score": 0.5, "default_mole_mean_score": 0.7, "paired_diff_mean": -0.2,
        "gemini_mole_caught": 2}}}))
    md = tmp_path / "ROLES.md"
    assert roles.main(["index", "--results", str(res), "--md", str(md)]) == 0
    idx = json.loads((res / "roles" / "index.json").read_text())["roles"]
    assert [r["key"] for r in idx] == ["frontier", "analyst", "swarm", "mole"]
    text = md.read_text()
    assert "paired -0.20" in text and "Mole Forge" in text and "| Role |" in text
    # addendum: arena label, n and seed span, three caveats
    assert "arena mode, not the judged env" in text and "n=2: medium dev seeds 0\u20131" in text
    assert "flat per leak" in text and "scripted moles" in text and "watermarking" in text
    assert idx[-1]["caveats"] == roles.MOLE_CAVEATS
