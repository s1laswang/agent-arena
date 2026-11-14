from conftest import launch
import subprocess, sys, time
from pathlib import Path
import pytest
sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright

def test_multimodel():
    web = Path(__file__).parent
    srv = subprocess.Popen([sys.executable, "-m", "http.server", "8767", "-d", str(web)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(1)
    try:
        with sync_playwright() as p:
            b = launch(p)
            pg = b.new_page(viewport={"width": 1500, "height": 700})
            pg.goto("http://localhost:8767/results.html?src=fixtures/gaptable.json")
            pg.wait_for_selector("#gap tbody tr")
            t = pg.inner_text("#gap tbody")
            assert "SCRIPTED PLACEHOLDER" in t and "NOT FOUND" in t and "100%" not in t.split("\n")[0] and "oracle" in t
            pg.screenshot(path=str(web.parent / "pitch/capture/multimodel-gap-table.png"))
            run = "run:fixtures/frontier/gemini-4-carbon/placeholder/finance_ap-s1.json"
            pg.goto(f"http://localhost:8767/replay.html?day={run}&vs=1-procedure&tick=99&reveal=1")
            pg.wait_for_selector(".desk")
            assert pg.locator(".badge").first.inner_text() == "SCRIPTED PLACEHOLDER"
            assert pg.locator("li.fooled").count() >= 1
            pg.screenshot(path=str(web.parent / "pitch/capture/multimodel-compare.png"), full_page=True)
            b.close()
    finally:
        srv.kill()

def test_landing_and_paired(tmp_path):
    import json
    web = Path(__file__).parent
    rows = [{"row": "Gemini 4 Carbon", "mode": "seat", "n_days": 3, "reward": 0.3, "model": "gemini-4-carbon", "commit": "abc", "provenance": "real", "agent": "scripted", "capped": True, "paired_diff": 0.4, "paired_ci": [0.1, 0.7], "verdict": "SIGNIFICANT"},
            {"row": "Claude", "mode": "seat", "n_days": 3, "reward": 0.2, "model": "claude", "commit": "abc", "provenance": "real", "agent": "claude", "gap_ref": 0.5}]
    f = web / "fixtures" / "_paired_tmp.json"
    f.write_text(json.dumps(rows))
    srv = subprocess.Popen([sys.executable, "-m", "http.server", "8768", "-d", str(web)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(1)
    try:
        with sync_playwright() as p:
            b = launch(p)
            pg = b.new_page(viewport={"width": 1500, "height": 700})
            pg.goto("http://localhost:8768/index.html?src=fixtures/_paired_tmp.json")
            pg.wait_for_selector("#gap tbody tr")
            t = pg.inner_text("#gap tbody")
            assert "CAPPED" in t and "SIGNIFICANT" in t and "0.40" in t
            assert pg.locator("#gap tbody tr", has_text="Gemini").locator(".badge.scripted").count() == 1
            assert pg.locator("#gap tbody tr", has_text="Claude").locator(".badge.real").count() == 1
            assert pg.locator("#days tbody tr").count() > 0
            b.close()
    finally:
        srv.kill()
        f.unlink()


def test_gemini_export_never_scripted():
    import json
    web = Path(__file__).parent
    run = json.load(open(web / "fixtures/frontier/gemini-4-carbon/placeholder/finance_ap-s1.json"))
    run.update(agent="gemini", provenance=None)
    run["transcript"]["result"][0]["agent"] = "staff"
    f = web / "fixtures" / "_gem_tmp.json"
    f.write_text(json.dumps(run))
    srv = subprocess.Popen([sys.executable, "-m", "http.server", "8770", "-d", str(web)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(1)
    try:
        with sync_playwright() as p:
            b = launch(p)
            pg = b.new_page()
            pg.goto("http://localhost:8770/replay.html?day=run:fixtures/_gem_tmp.json")
            pg.wait_for_selector(".badge")
            assert pg.locator(".badge").first.inner_text() == "UNVERIFIED"
            b.close()
    finally:
        srv.kill()
        f.unlink()


def test_ticket_and_excluded_labels():
    import json
    web = Path(__file__).parent
    rows = [{"row": "Gemini 3.5 Flash", "mode": "seat", "n_days": 4, "reward": 0.0, "model": "gemini-3.5-flash", "provenance": "real", "agent": "gemini", "headline": True, "n_excluded": 1, "excluded_seeds": [1003], "invalid": 0, "capped": 0}]
    f = web / "fixtures" / "_ex_tmp.json"
    f.write_text(json.dumps(rows))
    real = web.parent / "results/frontier/gemini-3.5-flash/ce5a8ce/finance_ap-s1004-t0.json"
    srv = subprocess.Popen([sys.executable, "-m", "http.server", "8773", "-d", str(web.parent)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(1)
    try:
        with sync_playwright() as p:
            b = launch(p)
            pg = b.new_page()
            pg.goto("http://localhost:8773/web/results.html?src=fixtures/_ex_tmp.json")
            pg.wait_for_selector("#gap tbody tr")
            t = pg.inner_text("#gap tbody")
            assert "1 seeds excluded" in t and "1003" in t
            if real.exists():
                pg.goto("http://localhost:8773/web/replay.html?day=run:../results/frontier/gemini-3.5-flash/ce5a8ce/finance_ap-s1004-t0.json&tick=99")
                pg.wait_for_selector(".panel:not([hidden])")
                assert "Correct 43 / 50 (closed 48)" in pg.inner_text(".panel")
            b.close()
    finally:
        srv.kill()
        f.unlink()
