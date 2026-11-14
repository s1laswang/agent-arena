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
            b = p.chromium.launch(executable_path="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
            pg = b.new_page(viewport={"width": 1500, "height": 700})
            pg.goto("http://localhost:8767/results.html")
            pg.wait_for_selector("#gap tbody tr")
            t = pg.inner_text("#gap tbody")
            assert "SCRIPTED PLACEHOLDER" in t and "NOT FOUND" in t and "REAL" not in t.replace("NOT FOUND", "")
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
