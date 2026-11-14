import subprocess, sys, time
from pathlib import Path
from conftest import launch
import pytest
sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright

PAGES = [("index", "index.html"), ("results", "results.html"), ("replay-compare", "replay.html?day=1-procedure&vs=1-oracle&tick=12&reveal=1")]


def test_stage():
    web = Path(__file__).parent
    srv = subprocess.Popen([sys.executable, "-m", "http.server", "8769", "-d", str(web)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(1)
    try:
        with sync_playwright() as p:
            b = launch(p)
            pg = b.new_page(viewport={"width": 1280, "height": 720})
            ext = []
            pg.on("request", lambda r: ext.append(r.url) if not r.url.startswith("http://localhost") else None)
            for name, url in PAGES:
                pg.goto("http://localhost:8769/" + url)
                pg.wait_for_selector("table tbody tr, .desk")
                assert pg.evaluate("document.documentElement.scrollWidth <= window.innerWidth"), name
                pg.screenshot(path=str(web.parent / f"pitch/capture/stage-{name}-1280x720.png"))
            assert not ext, ext
            b.close()
    finally:
        srv.kill()
