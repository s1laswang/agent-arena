"""Canary Lab dashboard (G5): keyless, fixture-backed, < 5 s."""
import json
import re
import shutil
from pathlib import Path

import pytest

from canary.gemini import dashboard as dash

FX = Path(__file__).parent / "fixtures" / "gemini_lab"
FAKE_KEY = "AIzaFAKE-fixture-not-a-key"


@pytest.fixture(scope="module")
def rows():
    return dash.load_ledger([FX / "ledger"])


def _payload(html: str) -> dict:
    m = re.search(r'<script id="data" type="application/json">(.*?)</script>', html, re.S)
    assert m, "embedded data block missing"
    return json.loads(m.group(1).replace("<\\/", "</"))


def test_summary_numbers(rows):
    s = dash.summarize(rows)
    t = s["totals"]
    assert t["calls"] == len(rows) > 1500
    assert t["in"] == sum(r["in"] for r in rows) and t["thinking"] > 0 and t["cached"] > 0
    assert 0 < t["error_rate"] < 0.1 and t["p95_latency_s"] >= t["p50_latency_s"] > 0
    assert {"ladder", "atlas", "swarm", "forge", "world", "narrate"} <= set(t["features"])
    assert sum(f["calls"] for f in s["by_feature"]) == t["calls"]
    assert sum(c["calls"] for c in s["matrix"]["cells"]) == t["calls"]
    assert sum(sum(b["counts"].values()) for b in s["timeline"]["bins"]) == t["calls"]
    assert s["cache"]["saved_usd"] > 0 and s["batch"]["calls"] == 160
    assert {"thinking", "context caching", "batch API", "embeddings", "TTS", "Live API"} <= set(s["capabilities"])
    # model order is canonical, not alphabetical
    ms = t["models"]
    assert ms.index("gemini-3.1-flash-lite") < ms.index("gemini-4-carbon")


def test_renders_all_panels_from_fixtures(tmp_path):
    out = tmp_path / "d.html"
    assert dash.main(["--ledger", str(FX / "ledger"), "--results", str(FX / "results"), "--out", str(out)]) == 0
    html = out.read_text()
    assert html.startswith("<!doctype html>") and "<title>Canary Lab Dashboard</title>" in html
    for pid in ("p-headline", "p-usage", "p-ladder", "p-atlas", "p-swarm"):
        assert f'id="{pid}"' in html
    p = _payload(html)
    assert p["usage"]["totals"]["calls"] > 1500
    assert p["results"]["ladder"]["cells"] and p["results"]["atlas"]["modes"] and p["results"]["swarm"]["attempts"]
    # self-contained: no network fetches
    assert not re.search(r'(src|href)="https?://', html)
    assert "@import" not in html and "fetch(" not in html


def test_no_secrets_or_prompts(tmp_path, rows):
    assert any(FAKE_KEY in (r.get("error") or "") for r in rows)  # the fixture plants one
    out = tmp_path / "d.html"
    dash.main(["--ledger", str(FX / "ledger"), "--results", str(FX / "results"), "--out", str(out)])
    html = out.read_text()
    assert FAKE_KEY not in html and "AIza" not in html
    assert '"meta"' not in json.dumps(_payload(html)["usage"])  # ledger meta never embedded
    assert "API key not valid" not in html  # raw error strings reduced to their type


def test_missing_results_render_pending(tmp_path):
    out = tmp_path / "d.html"
    dash.main(["--ledger", str(tmp_path / "nope"), "--results", str(tmp_path / "none"), "--out", str(out)])
    p = _payload(out.read_text())
    assert p["usage"]["totals"]["calls"] == 0
    assert p["results"]["ladder"] is None and p["results"]["atlas"] is None and p["results"]["swarm"] is None


def test_partial_results_and_bad_json(tmp_path):
    res = tmp_path / "res"
    res.mkdir()
    shutil.copy(FX / "results" / "atlas.json", res / "atlas.json")
    (res / "swarm.json").write_text("{not json")
    (res / "ladder.json").write_text(json.dumps({"cells": [], "note": f"key={FAKE_KEY}"}))
    r = dash.load_results(res)
    assert r["atlas"]["modes"] and r["swarm"] is None
    assert FAKE_KEY not in json.dumps(r)


def test_json_mode(capsys):
    assert dash.main(["--ledger", str(FX / "ledger"), "--json"]) == 0
    s = json.loads(capsys.readouterr().out)
    assert s["totals"]["calls"] > 1500 and "by_model" in s and "timeline" not in s


def test_error_type_reduction():
    assert dash.error_type("ClientError: 429 RESOURCE_EXHAUSTED. {'error': ...}") == "429 RESOURCE_EXHAUSTED"
    assert dash.error_type("TimeoutError: read timed out") == "TimeoutError"
    assert dash.error_type("weird message with key=abc") == "other"
    assert dash.redact("x AIzaSyABCDEFGHIJKLMN y") == "x [redacted] y"
