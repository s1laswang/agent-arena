import re
import subprocess
import sys
import time
from pathlib import Path

try:
    import pytest
    pytest.importorskip("playwright.sync_api")
except ImportError:
    pass
from playwright.sync_api import sync_playwright

def test_ui():
    web = Path(__file__).parent
    srv = subprocess.Popen([sys.executable, "-m", "http.server", "8766", "-d", str(web)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(1)
    try:
        with sync_playwright() as p:
            b = p.chromium.launch(executable_path="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
            pg = b.new_page()
            pg.goto("http://localhost:8766/replay.html?day=2-noop&vs=2-oracle")
            pg.wait_for_selector(".desk")
            tick = lambda: int(re.search(r"tick (\d+)", pg.inner_text("#tick")).group(1))
            assert tick() == 0
            pg.click("#play")
            time.sleep(1.8)
            assert tick() > 0
            pg.click("#play")
            t = tick()
            time.sleep(1)
            assert tick() == t
            pg.keyboard.press("ArrowRight")
            assert tick() == t + 1
            pg.keyboard.press("ArrowLeft")
            assert tick() == t
            pg.keyboard.press("Space")
            time.sleep(1.2)
            assert tick() > t
            pg.keyboard.press("Space")
            assert not pg.is_visible(".tag:has-text('SLEEPER')")
            pg.click("#reveal")
            assert pg.is_visible(".tag:has-text('SLEEPER')")
            assert pg.locator(".pill").count() == 0 or "post_chat" not in pg.inner_text(".panel")
            pg.goto("http://localhost:8766/index.html")
            pg.wait_for_selector("#days tbody tr")
            boxes = pg.locator("input[type=checkbox]")
            pg.locator("input[value='2-noop']").check()
            pg.locator("input[value='2-oracle']").check()
            assert pg.is_enabled("#cmp")
            pg.click("#cmp")
            pg.wait_for_selector(".compare")
            pg.goto("http://localhost:8766/results.html")
            pg.wait_for_selector("#gap tbody tr")
            assert pg.locator("tbody tr").count() >= 1
            assert "FIXTURE" in pg.inner_text("#flag") or pg.inner_text("#flag") == ""
            pg.goto("http://localhost:8766/replay.html")
            pg.wait_for_selector(".compare .desk")
            assert pg.locator(".run").count() == 2
            venv = web.parent / ".venv" / "bin" / "python"
            if venv.exists():
                live = subprocess.Popen([str(venv), str(web / "export.py"), "--seeds", "2", "--teams", "oracle", "--live"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                try:
                    time.sleep(2.5)
                    pg.goto("http://localhost:8766/replay.html?day=live")
                    pg.wait_for_selector(".desk")
                    a = tick()
                    time.sleep(3)
                    assert tick() > a
                finally:
                    live.terminate()
                    (web / "days" / "live.json").unlink(missing_ok=True)
            b.close()
        print("ok")
    finally:
        srv.terminate()



if __name__ == "__main__":
    test_ui()
