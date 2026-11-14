import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "web"))
import export

DAYS = Path(export.__file__).parent / "days"


def run(tmp, monkeypatch, *argv):
    monkeypatch.setattr(export, "OUT", tmp)
    monkeypatch.setattr(sys, "argv", ["export", *argv])
    export.main()


def test_staff_without_landing_runs(tmp_path, monkeypatch):
    run(tmp_path, monkeypatch, "--seeds", "2", "--teams", "staff")
    assert (tmp_path / "2-staff.json").exists()


def test_landing_pair_not_clobbered(tmp_path, monkeypatch):
    for n in ("1-staff.json", "1-procedure.json"):
        shutil.copy(DAYS / n, tmp_path / n)
    before = (tmp_path / "1-staff.json").read_bytes()
    run(tmp_path, monkeypatch, "--seeds", "1", "--teams", "staff")
    assert (tmp_path / "1-staff.json").read_bytes() == before
    assert (tmp_path / "1-procedure.json").exists()


def test_default_pair_is_staff_vs_procedure():
    rows = json.load(open(DAYS / "index.json"))
    s = next(r for r in rows if r["team"] == "staff")
    assert s["reward"] == 0
    assert next(r for r in rows if r["seed"] == s["seed"] and r["team"] == "procedure")["reward"] == 1


def test_export_labels_scripted():
    from web import export

    doc = export.build(2, "oracle", True)
    assert doc["result"][0]["agent_kind"] == "scripted" and doc["provenance"]["provenance"] == "scripted"
