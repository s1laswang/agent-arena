import pytest

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"


def launch(p):
    try:
        return p.chromium.launch()
    except Exception:
        import os
        if os.path.exists(CHROME):
            return p.chromium.launch(executable_path=CHROME)
        pytest.skip("no chromium for playwright")
