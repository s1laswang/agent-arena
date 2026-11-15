"""Screenshot the dashboard panels with headless Chrome (no playwright needed).

    python -m canary.gemini.shoot [--html results/gemini/dashboard.html] [--out docs/gemini/assets]
                                  [--panels headline,usage,ladder,atlas,swarm,all] [--theme light|dark] [--width 1600]

Each panel is opened as `dashboard.html?panel=<name>&theme=<theme>` (the page's focus mode), captured
tall, then cropped to its content and saved as dashboard-<panel>[-dark].png (1600 px wide).
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from PIL import Image, ImageChops

CHROME_CANDIDATES = ["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
                     "/Applications/Chromium.app/Contents/MacOS/Chromium",
                     "google-chrome", "chromium", "chromium-browser"]
PAGE_BG = {"light": (246, 245, 240), "dark": (13, 13, 13)}


def chrome() -> str:
    for c in CHROME_CANDIDATES:
        if os.path.exists(c) or shutil.which(c):
            return c
    raise SystemExit("no Chrome/Chromium found for headless screenshots")


def capture(url: str, out: Path, width: int, height: int, profile: str) -> None:
    subprocess.run([chrome(), "--headless=new", "--disable-gpu", "--hide-scrollbars", "--force-device-scale-factor=1",
                    f"--user-data-dir={profile}", f"--window-size={width},{height}", "--virtual-time-budget=4000",
                    f"--screenshot={out}", url], check=True, timeout=120, capture_output=True)


def crop_to_content(path: Path, bg: tuple, pad: int = 28) -> None:
    im = Image.open(path).convert("RGB")
    diff = ImageChops.difference(im, Image.new("RGB", im.size, bg)).convert("L").point(lambda v: 255 if v > 6 else 0)
    box = diff.getbbox()
    if box:
        im = im.crop((0, 0, im.width, min(im.height, box[3] + pad)))
    im.save(path, optimize=True)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--html", default="results/gemini/dashboard.html")
    ap.add_argument("--out", default="docs/gemini/assets")
    ap.add_argument("--panels", default="headline,usage,ladder,atlas,swarm,roles,leaderboard")
    ap.add_argument("--theme", default="light", choices=["light", "dark"])
    ap.add_argument("--width", type=int, default=1600)
    ap.add_argument("--height", type=int, default=3600)
    a = ap.parse_args(argv)
    html = Path(a.html).resolve()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as prof:
        for p in a.panels.split(","):
            q = f"?theme={a.theme}" + ("" if p == "all" else f"&panel={p}")
            name = f"dashboard-{p}{'-dark' if a.theme == 'dark' else ''}.png"
            dst = out / name
            capture(html.as_uri() + q, dst, a.width, 7000 if p == "all" else a.height, prof)
            crop_to_content(dst, PAGE_BG[a.theme])
            print(f"{dst} {Image.open(dst).size} {dst.stat().st_size // 1024} KB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
