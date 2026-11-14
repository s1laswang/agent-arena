import subprocess
import sys
import time
from pathlib import Path

import pytest

pytest.importorskip("playwright.sync_api")
from playwright.sync_api import sync_playwright


def test_seat_mode_view():
    web = Path(__file__).parent
    srv = subprocess.Popen([sys.executable, "-m", "http.server", "8767", "-d", str(web)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(1)
    try:
        with sync_playwright() as p:
            b = p.chromium.launch(executable_path="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
            pg = b.new_page(viewport={"width": 1500, "height": 900})
            pg.goto("http://localhost:8767/replay.html?day=0-seat-finance_ap")
            pg.wait_for_selector(".desk")
            assert pg.locator(".desk.sut").count() == 1
            assert "Finance" in pg.inner_text(".desk.sut") or "finance" in pg.inner_text(".desk.sut").lower()
            assert pg.locator(".desk.bg").count() == 7
            assert "background (scripted procedure)" in pg.inner_text(".desk.bg")
            pg.click("#scrub")
            pg.fill("#scrub", pg.get_attribute("#scrub", "max"))
            pg.dispatch_event("#scrub", "input")
            assert pg.locator(".trow.sut").count() == 1
            pg.screenshot(path=str(web / "fixtures" / "seat-mode.png"))
            b.close()
    finally:
        srv.terminate()
