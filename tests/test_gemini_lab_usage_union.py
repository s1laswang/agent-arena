"""B1: one usage total. The de-duplicated union of every committed ledger is idempotent, and the dashboard shows exactly it."""
import gzip
import json
import re
import shutil
from pathlib import Path

import pytest

from canary.gemini import dashboard as dash
from canary.gemini import usage_union as uu

FX = Path(__file__).parent / "fixtures" / "gemini_lab"
RES = dash.ROOT / "results" / "gemini"


def _payload(html: str) -> dict:
    m = re.search(r'<script id="data" type="application/json">(.*?)</script>', html, re.S)
    assert m, "embedded data block missing"
    return json.loads(m.group(1).replace("<\\/", "</"))


@pytest.fixture
def res(tmp_path):
    """Fixture results with the fixture ledger committed twice at different depths, plus an exported copy of it."""
    r = tmp_path / "results"
    shutil.copytree(FX / "results", r)
    src = sorted((FX / "ledger").glob("*.jsonl"))
    (r / "a_ledger.jsonl.gz").write_bytes(gzip.compress(b"".join(p.read_bytes() for p in src)))
    (r / "scale" / "x").mkdir(parents=True)
    (r / "scale" / "x" / "ladder_ledger.jsonl.gz").write_bytes((r / "a_ledger.jsonl.gz").read_bytes())
    dash.export_ledger([str(p) for p in src], r / "usage_ledger.jsonl.gz")
    return r


def test_committed_ledgers_found_at_any_depth(res):
    names = {Path(f).relative_to(res).as_posix() for f in dash.committed_ledgers(res)}
    assert names == {"a_ledger.jsonl.gz", "scale/x/ladder_ledger.jsonl.gz", "usage_ledger.jsonl.gz"}


def test_union_is_idempotent(res):
    one = uu.union(res)
    n_src = len(dash.load_ledger([FX / "ledger"]))
    assert one["calls"] == n_src > 0 and one["duplicates_removed"] == 2 * n_src  # three copies count once
    # exporting the union and adding it back changes nothing
    dash.export_ledger(dash.committed_ledgers(res), res / "union_ledger.jsonl.gz")
    two = uu.union(res)
    assert {k: two[k] for k in ("calls", "input_tokens", "cached_tokens", "thinking_tokens", "output_tokens", "cost_usd_list")} == \
           {k: one[k] for k in ("calls", "input_tokens", "cached_tokens", "thinking_tokens", "output_tokens", "cost_usd_list")}


def test_response_id_dedups_even_when_composite_key_differs(tmp_path):
    base = {"ts": 1.0, "host": "h", "pid": 1, "feature": "f", "model": "m", "in": 10, "out": 1, "response_id": "r1"}
    p = tmp_path / "x_ledger.jsonl"
    p.write_text(json.dumps(base) + "\n" + json.dumps(dict(base, host="other")) + "\n" + json.dumps(dict(base, response_id="r2", ts=2.0)) + "\n")
    assert len(dash.load_ledger([p])) == 2


def test_dashboard_total_equals_usage_total(res, tmp_path):
    u = uu.union(res)
    out = tmp_path / "d.html"
    assert dash.main(["--ledger", "committed", "--results", str(res), "--out", str(out)]) == 0
    t = _payload(out.read_text())["usage"]["totals"]
    assert (t["calls"], t["in"], t["cached"], t["thinking"], t["out"]) == \
           (u["calls"], u["input_tokens"], u["cached_tokens"], u["thinking_tokens"], u["output_tokens"])
    assert t["cost_usd"] == pytest.approx(u["cost_usd_list"])


def test_committed_usage_total_matches_committed_ledgers_and_dashboard():
    """The committed usage_total.json is current: it recomputes from the committed ledgers, and dashboard.html shows it."""
    f = RES / "usage_total.json"
    if not f.exists():
        pytest.skip("usage_total.json not committed")
    u = json.loads(f.read_text())
    now = uu.union(RES)
    assert (now["calls"], now["input_tokens"], now["thinking_tokens"]) == (u["calls"], u["input_tokens"], u["thinking_tokens"])
    t = _payload((RES / "dashboard.html").read_text())["usage"]["totals"]
    assert (t["calls"], t["in"], t["thinking"]) == (u["calls"], u["input_tokens"], u["thinking_tokens"])
