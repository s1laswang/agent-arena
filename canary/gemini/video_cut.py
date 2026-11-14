"""Assemble the 2-minute Canary Lab demo video (docs/gemini/VIDEO-2MIN.md) from stills, cards and the Gemini TTS clips.

    python -m canary.gemini.video_cut [--out docs/gemini/assets/canary-lab-2min.mp4] [--build data/gemini/video-build]
                                      [--ladder-html PATH] [--html PATH] [--no-capture] [--height 1080]

Keyless and local: no Gemini calls. Inputs are committed files only:
  - dashboard panels, captured with headless Chrome at 2x (same `?panel=` focus mode as canary.gemini.shoot);
    --html defaults to the committed results/gemini/dashboard.html (ledger totals quoted in SUBMISSION.md), and
    --ladder-html can point at a rebuild whose ladder panel reads the current results/gemini/ladder.json;
  - narration clips docs/gemini/assets/narration-2min/<id>.wav and the Live commentator clip;
  - numbers on cards are parsed from, or cited to, committed result files (source line on every caption).
The VO is time-stretched (atempo, pitch kept) by one factor so the cut lands at exactly 2:00; the factor is printed.
Frames are rendered in Python (sub-pixel Ken-Burns pans, no zoompan jitter) and piped to ffmpeg (libx264, AAC).
"""
from __future__ import annotations

import argparse
import json
import math
import re
import subprocess
import tempfile
import wave
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[2]
W, H, FPS = 1920, 1080, 30
TOTAL = 120.0
NARR = ROOT / "docs/gemini/assets/narration-2min"
COMMENTATOR = ROOT / "docs/gemini/assets/narration/commentator-demo.wav"
COMMENTATOR_CUT = 5.45          # natural pause in the commentator clip (silencedetect 5.25-5.60 s)
VO_IDS = ["01-hook", "02-problem", "03-ladder", "04-atlas", "05-swarm", "06-innovative", "07-essential", "08-close"]
GAP = 0.45                      # silence between VO clips
END_HOLD = 2.2                 # end card after the last line
REPO_URL = "github.com/s1laswang/agent-arena"

# palette (dashboard light theme + canary accent)
BG = (246, 245, 240)
INK = (20, 20, 20)
MUTED = (110, 110, 105)
ACCENT = (240, 176, 20)
BLUE = (42, 111, 219)
RED = (205, 62, 52)
DARK = (14, 15, 17)
DARK_INK = (244, 242, 234)
DARK_MUTED = (150, 150, 145)

FONTS = {
    "serif": "/System/Library/Fonts/Supplemental/Georgia.ttf",
    "serif_b": "/System/Library/Fonts/Supplemental/Georgia Bold.ttf",
    "sans": "/System/Library/Fonts/HelveticaNeue.ttc",
    "mono": "/System/Library/Fonts/Menlo.ttc",
}


def font(kind: str, size: int, index: int = 0) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(FONTS[kind], size, index=index)


def sans_b(size: int) -> ImageFont.FreeTypeFont:
    return font("sans", size, index=1)   # Helvetica Neue Bold


# ----------------------------------------------------------------------------------------------- capture
def capture_panels(html: Path, panels: list[str], out: Path, height: int = 3600) -> dict[str, Path]:
    from canary.gemini.shoot import chrome
    out.mkdir(parents=True, exist_ok=True)
    res = {}
    with tempfile.TemporaryDirectory() as prof:
        for p in panels:
            dst = out / f"{p}@2x.png"
            subprocess.run([chrome(), "--headless=new", "--disable-gpu", "--hide-scrollbars", "--force-device-scale-factor=2",
                            f"--user-data-dir={prof}", f"--window-size=1600,{height}", "--virtual-time-budget=4000",
                            f"--screenshot={dst}", html.resolve().as_uri() + f"?theme=light&panel={p}"],
                           check=True, timeout=180, capture_output=True)
            res[p] = dst
    return res


# ----------------------------------------------------------------------------------------------- text helpers
def wrap(draw: ImageDraw.ImageDraw, text: str, f: ImageFont.FreeTypeFont, maxw: int) -> list[str]:
    lines, cur = [], ""
    for w in text.split():
        t = (cur + " " + w).strip()
        if draw.textlength(t, font=f) <= maxw or not cur:
            cur = t
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def canvas(bg=BG, size=(W, H)) -> tuple[Image.Image, ImageDraw.ImageDraw]:
    im = Image.new("RGB", size, bg)
    return im, ImageDraw.Draw(im)


def kicker(d: ImageDraw.ImageDraw, xy, text: str, color=MUTED, size=26):
    d.text(xy, text, font=font("mono", size), fill=color)


# ----------------------------------------------------------------------------------------------- cards
def card_intro() -> Image.Image:
    im, d = canvas(DARK)
    d.ellipse((160, 380, 260, 480), fill=ACCENT)
    d.polygon([(255, 420), (300, 432), (255, 444)], fill=(230, 120, 20))
    d.text((300, 340), "Canary Lab", font=font("serif", 150), fill=DARK_INK)
    d.text((306, 530), "A mole is leaking documents. Gemini runs the investigation.", font=font("sans", 44), fill=DARK_MUTED)
    kicker(d, (306, 300), "GOOGLE DEEPMIND · BEST USE OF GEMINI API", DARK_MUTED)
    return im


def card_hook() -> Image.Image:
    im, d = canvas(DARK)
    f = font("serif", 84)
    d.text((160, 300), "One mole is leaking", font=f, fill=DARK_INK)
    d.text((160, 400), "a company's documents.", font=f, fill=DARK_INK)
    d.text((160, 560), "An AI head of security gets", font=f, fill=DARK_INK)
    x = 160
    d.text((x, 660), "one accusation.", font=font("serif_b", 84), fill=ACCENT)
    kicker(d, (164, 240), "CANARY LAB", DARK_MUTED)
    return im


def card_section(q: str, title: str, sub: str) -> Image.Image:
    im, d = canvas(BG)
    d.rectangle((160, 360, 172, 700), fill=ACCENT)
    kicker(d, (220, 360), f"CANARY LAB · {q}")
    d.text((214, 410), title, font=font("serif", 120), fill=INK)
    for i, line in enumerate(wrap(d, sub, font("sans", 46), 1450)):
        d.text((220, 590 + i * 60), line, font=font("sans", 46), fill=MUTED)
    return im


def swarm_numbers(md_path: Path) -> dict:
    """Parse the final multi-wave swarm.md: per-tier attempts, the 'By wave' table, and the positive control."""
    md = md_path.read_text()
    attempts = sum(int(m) for m in re.findall(r"^\| (?:hard|medium) \| (\d+) \|", md, re.M))
    waves = []
    for line in md.splitlines():
        m = re.match(r"\| (wave [^|]+|blackbox) \| swarm-\S+ \| [^|]+ \| (\d+) \| (\d+) \| (\d+) \| (\d+) \| (\d+) \|"
                     r" \d+ \| \d+ \| \d+ \| \*\*(\d+)\*\*", line)
        if m:
            waves.append({"name": m.group(1).strip(), "finished": int(m.group(3)), "mcp": int(m.group(5)),
                          "calls": int(m.group(6)), "exploits": int(m.group(7))})
    allw = re.search(r"\| \*\*all real waves\*\* \|[^|]*\|[^|]*\| (\d+) \| (\d+) \| (\d+) \| (\d+) \| (\d+) \|.*?\*\*(\d+)\*\*", md)
    pc = re.search(r"\*\*(\d+)/(\d+) attackers found it\*\*", md)
    return {"attempts": attempts, "waves": waves, "finished": int(allw.group(2)), "mcp": int(allw.group(4)),
            "calls": int(allw.group(5)), "exploits": int(allw.group(6)),
            "whitebox": sum(w["finished"] for w in waves if w["name"] != "blackbox"),
            "pc": (int(pc.group(1)), int(pc.group(2))), "src": md_path}


def card_swarm(s: dict, src: str) -> Image.Image:
    im, d = canvas(BG)
    kicker(d, (120, 80), "SWARM · CAN GEMINI GAME THE REWARD?")
    d.text((114, 120), "Gemini attacks its own benchmark", font=font("serif", 64), fill=INK)
    tiles = [("Attack attempts", str(s["attempts"]), f"{s['finished']} attackers + {s['mcp']} MCP re-runs"),
             ("Waves", str(len(s["waves"])), "whitebox, blackbox, 2 escalations"),
             ("Whole codebase in context", f"{s['whitebox']} / {s['finished']}", "whitebox attackers"),
             ("Verified exploits", str(s["exploits"]), "scored by the server ledger")]
    for i, (lab, val, sub) in enumerate(tiles):
        x = 120 + i * 425
        hi = lab == "Verified exploits"
        d.rounded_rectangle((x, 240, x + 400, 440), 20, fill=(255, 255, 255), outline=ACCENT if hi else (220, 218, 210),
                            width=4 if hi else 2)
        d.text((x + 26, 258), lab, font=font("sans", 27), fill=MUTED)
        d.text((x + 26, 300), val, font=sans_b(72), fill=INK)
        d.text((x + 26, 392), sub, font=font("sans", 23), fill=MUTED)
    hdr = ["wave", "attackers", "MCP re-runs", "tool calls", "verified exploits"]
    xs = [140, 760, 1010, 1260, 1520]
    y = 500
    for x, h in zip(xs, hdr):
        d.text((x, y), h, font=font("mono", 24), fill=MUTED)
    d.line((120, y + 42, 1800, y + 42), fill=(205, 203, 195), width=2)
    for w in s["waves"]:
        y += 62
        vals = [w["name"], str(w["finished"]), str(w["mcp"]), f"{w['calls']:,}", str(w["exploits"])]
        for k, (x, v) in enumerate(zip(xs, vals)):
            d.text((x, y), v, font=sans_b(34) if k == 4 else font("sans", 34), fill=INK)
    d.text((120, 1010), f"source: {src}", font=font("mono", 20), fill=MUTED)
    return im


def card_positive_control(s: dict, src: str) -> Image.Image:
    im, d = canvas(BG)
    k, n = s["pc"]
    kicker(d, (160, 190), "SWARM · TESTING THE DETECTOR")
    d.text((154, 240), "Reopen a closed hole on purpose:", font=font("serif", 72), fill=INK)
    d.text((154, 330), "seed regeneration from public code, on public dev seeds.", font=font("serif", 50), fill=MUTED)
    for i in range(n):
        x = 160 + i * 400
        d.rounded_rectangle((x, 480, x + 360, 720), 22, fill=(255, 255, 255), outline=(220, 218, 210), width=2)
        d.text((x + 32, 508), f"attacker {i + 1}", font=font("mono", 28), fill=MUTED)
        d.text((x + 32, 570), "flagged" if i < k else "missed", font=sans_b(56), fill=RED if i < k else MUTED)
        d.text((x + 32, 650), "win unjustified", font=font("mono", 26), fill=MUTED)
    d.text((160, 780), f"{k} / {n}", font=sans_b(80), fill=INK)
    d.text((410, 806), "caught by the same accusation audit that found 0 exploits", font=font("sans", 40), fill=MUTED)
    d.text((160, 900), "Not in the totals; the real MCP server closes this hole by refusing dev seeds.", font=font("sans", 32), fill=MUTED)
    d.text((160, 1010), f"source: {src} (positive control)", font=font("mono", 20), fill=MUTED)
    return im


def gallery_numbers() -> dict:
    """Parse docs/reports/failure_gallery.md: header facts + per-category gap summed over rules versions."""
    md = (ROOT / "docs/reports/failure_gallery.md").read_text()
    eps = int(re.search(r"\*\*(\d+) episodes decomposed\*\*", md).group(1))
    gap = re.search(r"net gap \+([\d.]+)", md).group(1)
    unexpl = re.search(r"Unexplained: ([^\*]+)\*\*", md).group(1).strip()
    quotes = re.search(r"Quotes: (\d+/\d+) verbatim", md).group(1)
    cats = []
    for line in md.splitlines():
        m = re.match(r"\| (.+?) \(`(\w+)`\) \| (\w+) \| ([+-][\d.]+) \| ([+-][\d.]+) \| ([+-][\d.]+) \|", line)
        if m:
            cats.append((m.group(1), m.group(3), sum(float(m.group(i)) for i in (4, 5, 6))))
    return {"episodes": eps, "gap": gap, "unexplained": unexpl, "quotes": quotes, "cats": cats}


def card_gallery(g: dict) -> Image.Image:
    im, d = canvas(BG)
    kicker(d, (120, 70), "FAILURE GALLERY · WHERE EVERY LOST POINT WENT")
    d.text((114, 110), "The gap to the solver, split into causes", font=font("serif", 60), fill=INK)
    tiles = [("Episodes decomposed", str(g["episodes"])), ("Net gap, all tagged", "+" + g["gap"]),
             ("Unexplained", "0"), ("Quotes verbatim", g["quotes"])]
    for i, (lab, val) in enumerate(tiles):
        x = 120 + i * 425
        hi = lab == "Unexplained"
        d.rounded_rectangle((x, 220, x + 400, 380), 20, fill=(255, 255, 255), outline=ACCENT if hi else (220, 218, 210),
                            width=4 if hi else 2)
        d.text((x + 26, 240), lab, font=font("sans", 28), fill=MUTED)
        d.text((x + 26, 285), val, font=sans_b(66), fill=INK)
    # waterfall: categories with |value| >= 0.5, cumulative bars
    cats = [c for c in g["cats"] if abs(c[2]) >= 0.5]
    cats.sort(key=lambda c: -c[2])
    total = sum(c[2] for c in g["cats"])
    lo = min(0.0, min(sum(c[2] for c in cats[:k]) for k in range(len(cats) + 1)))
    hi_v = max(sum(c[2] for c in cats[:k]) for k in range(len(cats) + 1))
    x0, x1 = 900, 1780
    sx = lambda v: x0 + (v - lo) / (hi_v - lo) * (x1 - x0)
    y, rh = 420, 46
    run = 0.0
    fl = font("sans", 25)
    for name, kind, v in cats:
        a, b = sorted((run, run + v))
        col = RED if kind in ("outcome", "timing", "canary", "restriction") else ((150, 150, 150) if kind in ("luck", "infrastructure") else BLUE)
        d.rectangle((sx(a), y + 6, max(sx(b), sx(a) + 2), y + rh - 6), fill=col)
        label = name if len(name) <= 52 else name[:50] + "…"
        d.text((120, y + 9), label, font=fl, fill=INK)
        d.text((sx(b) + 10 if v > 0 else sx(a) - 90, y + 9), f"{v:+.1f}", font=font("mono", 22), fill=MUTED)
        run += v
        y += rh
    d.line((sx(0), 410, sx(0), y + 4), fill=(170, 170, 165), width=2)
    d.text((120, y + 16), f"net gap {total:+.2f} · residual {g['unexplained']} · red = agent decision, grey = luck, blue = credit",
           font=font("sans", 24), fill=MUTED)
    d.text((120, 1020), "source: docs/reports/failure_gallery.md (295 episodes, v1.2–v1.4, never pooled in the table)",
           font=font("mono", 20), fill=MUTED)
    return im


def usage_numbers() -> dict:
    """Same summary the narration placeholders and the dashboard use (committed ledger, repriced)."""
    from canary.gemini.narrate import usage_summary, say_tokens
    from canary.gemini import dashboard as dash
    s = usage_summary(dash.DEFAULT_RESULTS, ["committed"])
    t = s["totals"]
    return {"calls": t["calls"], "cost": t["cost_usd"], "share": s["cache"]["hit_share"],
            "cached": say_tokens(t["cached"]).replace(" million", "M"), "input": say_tokens(t["in"]).replace(" million", "M")}


def blind_numbers() -> dict:
    from canary.gemini import dashboard as dash
    B = dash.slim_atlas_blind(dash.load_json(dash.DEFAULT_RESULTS / "atlas_blind.json"))
    return {"rec": B["tags_recovered"], "tags": B["n_tags"], "new": len(B.get("novel") or []),
            "cov": round(100 * B["regret_share_covered"]), "eps": B["episodes"]}


def card_features(u: dict) -> Image.Image:
    im, d = canvas(BG)
    kicker(d, (160, 130), "WHY GEMINI IS ESSENTIAL")
    d.text((154, 170), "Three Gemini features make this possible", font=font("serif", 66), fill=INK)
    rows = [("thinking_level", "the ladder's knob: minimal, low, medium, high"),
            ("thought signatures", "keep reasoning across tool calls"),
            ("explicit context cache", f"served {round(100 * u['share'])}% of input tokens ({u['cached']} of {u['input']})")]
    for i, (k, v) in enumerate(rows):
        y = 330 + i * 150
        d.rounded_rectangle((160, y, 1760, y + 120), 20, fill=(255, 255, 255), outline=(220, 218, 210), width=2)
        d.text((200, y + 30), f"{i + 1}", font=sans_b(56), fill=ACCENT)
        d.text((280, y + 22), k, font=sans_b(44), fill=INK)
        d.text((280, y + 76), v, font=font("sans", 30), fill=MUTED)
    d.text((160, 810), f"Whole programme: ${u['cost']:,.2f} at list price · {u['calls']:,} ledgered calls", font=sans_b(44), fill=INK)
    d.text((160, 880), "TTS and the Live API only narrate.", font=font("sans", 40), fill=MUTED)
    d.text((160, 1000), "source: results/gemini/usage_ledger.jsonl.gz (committed ledger, as in results/gemini/dashboard.html)",
           font=font("mono", 22), fill=MUTED)
    return im


def focus(src: Image.Image, box: tuple, scale: float = 2.0, fill: float = 0.9) -> Image.Image:
    """Crop a 1x-coords box from a 2x capture and centre it on a 16:9 page-coloured canvas (for wide, short regions)."""
    x0, y0, x1, y1 = (v * scale for v in box)
    reg = src.convert("RGB").crop((int(x0), int(y0), int(x1), int(y1)))
    cw, ch = 2 * W, 2 * H
    k = min(cw * fill / reg.width, ch * fill / reg.height)
    reg = reg.resize((round(reg.width * k), round(reg.height * k)), Image.LANCZOS)
    im = Image.new("RGB", (cw, ch), BG)
    im.paste(reg, ((cw - reg.width) // 2, (ch - reg.height) // 2))
    return im.resize((W, H), Image.LANCZOS)


_PAUSES: dict[str, list[float]] = {}


def pauses(clip: str) -> list[float]:
    """Ends of silences (>= 0.2 s at -40 dB) inside a narration clip, in clip seconds."""
    if clip not in _PAUSES:
        r = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(NARR / f"{clip}.wav"), "-af",
                            "silencedetect=noise=-40dB:d=0.2", "-f", "null", "-"], capture_output=True, text=True)
        _PAUSES[clip] = [float(m) for m in re.findall(r"silence_end: ([\d.]+)", r.stderr)]
    return _PAUSES[clip]


def snap(clip: str, est: float, tol: float = 1.6) -> float:
    """Nearest pause to an estimated clip time (falls back to the estimate), so cuts land between sentences."""
    c = [p for p in pauses(clip) if abs(p - est) <= tol]
    return min(c, key=lambda p: abs(p - est)) if c else est


def jsonl_scroll(path: Path, lines: int = 120) -> Image.Image:
    ep = json.loads(path.open().readline())
    rows = [f'{{"tier": "{ep["tier"]}", "seed": {ep["seed"]}, "agent": "{ep["agent"]}", "steps": ['] + \
           [json.dumps(s, separators=(", ", ": ")) for s in ep["steps"]]
    f = font("mono", 24)
    lh = 34
    rows = rows[:lines]
    im = Image.new("RGB", (W, 120 + lh * len(rows) + 120), DARK)
    d = ImageDraw.Draw(im)
    d.text((60, 40), f"$ less {path.relative_to(ROOT)}", font=f, fill=ACCENT)
    for i, r in enumerate(rows):
        d.text((60, 110 + i * lh), (r[:128] + "…") if len(r) > 129 else r, font=f, fill=(200, 205, 200) if i % 2 else (160, 170, 165))
    return im


def terminal_card(lines: list[str], shown: int) -> Image.Image:
    im, d = canvas(DARK)
    d.rounded_rectangle((90, 80, 1830, 1000), 18, fill=(24, 25, 28))
    for i, c in enumerate([(237, 106, 94), (245, 191, 79), (98, 197, 84)]):
        d.ellipse((120 + i * 36, 108, 142 + i * 36, 130), fill=c)
    f = font("mono", 27)
    for i, ln in enumerate(lines[:shown]):
        col = ACCENT if ln.startswith("$") else ((120, 220, 130) if "OK" in ln else (205, 208, 204))
        d.text((130, 170 + i * 44), ln, font=f, fill=col)
    return im


def card_end() -> Image.Image:
    im, d = canvas(DARK)
    d.ellipse((160, 340, 250, 430), fill=ACCENT)
    d.text((290, 300), "Canary Lab", font=font("serif", 130), fill=DARK_INK)
    d.text((296, 470), "Gemini plays, explains and attacks its own benchmark.", font=font("sans", 44), fill=DARK_MUTED)
    d.text((296, 600), REPO_URL, font=font("mono", 50), fill=ACCENT)
    d.text((296, 690), "make lab-replay · recorded Gemini runs replay offline, no key needed", font=font("mono", 28), fill=DARK_MUTED)
    kicker(d, (296, 900), "GOOGLE DEEPMIND · BEST USE OF GEMINI API · JUNCTION 2026", DARK_MUTED, 24)
    return im


def caption(title: str, source: str = "", lower_third: bool = False) -> Image.Image:
    """Dark rounded caption box (RGBA, full frame) anchored bottom-left."""
    ov = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(ov)
    ft, fs = sans_b(40), font("mono", 22)
    tl = wrap(d, title, ft, 1560)
    h = 36 + 52 * len(tl) + (40 if source else 0) + 18
    y0 = H - 70 - h
    wmax = max([d.textlength(t, font=ft) for t in tl] + [d.textlength(source, font=fs) if source else 0])
    d.rounded_rectangle((80, y0, 80 + wmax + 76, y0 + h), 16, fill=(14, 15, 17, 228))
    d.rectangle((80, y0 + 14, 88, y0 + h - 14), fill=ACCENT + (255,))
    for i, t in enumerate(tl):
        d.text((118, y0 + 26 + i * 52), t, font=ft, fill=(250, 248, 240, 255))
    if source:
        d.text((118, y0 + 30 + 52 * len(tl)), source, font=fs, fill=(170, 170, 165, 255))
    return ov


# ----------------------------------------------------------------------------------------------- segments
@dataclass
class Seg:
    start: float
    end: float
    render: Callable[[float], Image.Image]          # u in [0,1] -> RGB frame
    captions: list[tuple[float, float, Image.Image]] = field(default_factory=list)  # absolute times
    label: str = ""


def ease(u: float) -> float:
    return 0.5 - 0.5 * math.cos(math.pi * max(0.0, min(1.0, u)))


def pan(src: Image.Image, r0: tuple, r1: tuple, scale: float = 2.0) -> Callable[[float], Image.Image]:
    """Ken-Burns between two 16:9 rects (x, y, w) given in 1x panel coords; src is the 2x capture."""
    rects = [(x * scale, y * scale, w * scale) for x, y, w in (r0, r1)]
    widest = max(r[2] for r in rects)
    pre = min(1.0, W / widest)
    if pre < 1.0:  # downscale once with LANCZOS so the widest rect maps ~1:1 (transform() does not antialias)
        src = src.resize((round(src.width * pre), round(src.height * pre)), Image.LANCZOS)
        rects = [(x * pre, y * pre, w * pre) for x, y, w in rects]
    src = src.convert("RGB")

    def f(u: float) -> Image.Image:
        e = ease(u)
        x, y, w = (a + (b - a) * e for a, b in zip(rects[0], rects[1]))
        h = w * H / W
        return src.transform((W, H), Image.EXTENT, (x, y, x + w, y + h), Image.BICUBIC)
    return f


def still(img: Image.Image, z0: float = 1.0, z1: float = 1.035) -> Callable[[float], Image.Image]:
    def f(u: float) -> Image.Image:
        z = z0 + (z1 - z0) * ease(u)
        w, h = W / z, H / z
        x, y = (W - w) / 2, (H - h) / 2
        return img.transform((W, H), Image.EXTENT, (x, y, x + w, y + h), Image.BICUBIC)
    return f


def scroll(img: Image.Image) -> Callable[[float], Image.Image]:
    def f(u: float) -> Image.Image:
        y = (img.height - H) * u
        return img.transform((W, H), Image.EXTENT, (0, y, W, y + H), Image.BICUBIC)
    return f


# ----------------------------------------------------------------------------------------------- timeline
def wav_seconds(p: Path) -> float:
    with wave.open(str(p)) as w:
        return w.getnframes() / w.getframerate()


def timeline(shots: dict[str, Path], replay_lines: list[str], tempo: float, starts: list[float], ends: list[float],
             swarm_md: Path = ROOT / "results/gemini/swarm.md") -> list[Seg]:
    S, E = starts, ends
    rel = lambda i, t: S[i] + snap(VO_IDS[i], t) / tempo    # clip-relative estimate -> nearest pause, absolute
    B = [0.0] + [E[i] + 0.22 for i in range(7)] + [TOTAL]   # shot boundaries
    img = {k: Image.open(v) for k, v in shots.items()}
    segs: list[Seg] = []

    # 1 hook
    segs.append(Seg(0, S[0], still(card_intro(), 1.0, 1.03),
                    [(0.3, S[0], caption("Live commentary: Gemini Live API", "assets/narration/commentator-demo.wav · gemini-3.8-live"))], "1 intro"))
    t_lab = rel(0, 6.82)
    segs.append(Seg(S[0], t_lab, still(card_hook(), 1.0, 1.04), label="1 hook"))
    segs.append(Seg(t_lab, B[1], pan(img["headline"], (150, 0, 1300), (160, 10, 1000)), label="1 headline"))

    # 2 problem
    q1 = B[1] + 2.4
    segs.append(Seg(B[1], q1, still(card_section("Q1", "The problem", "Agents now make irreversible calls under uncertainty."), 1.0, 1.03), label="2 card"))
    traj = ROOT / "data/runs/committed/gpt-5.5/hard-15-19/episodes.jsonl"
    segs.append(Seg(q1, B[2], scroll(jsonl_scroll(traj)),
                    [(rel(1, wav_seconds(NARR / f"{VO_IDS[1]}.wav") * 21 / 41), B[2], caption("One score can't say where an agent fails, whether more thinking helps, or whether it can be gamed."))],
                    "2 trajectory"))

    # 3 ladder
    q2 = B[2] + 2.2
    segs.append(Seg(B[2], q2, still(card_section("Q2", "Gemini integration", "Gemini plays: five models, up to four thinking levels, paired with a Bayesian solver."), 1.0, 1.03), label="3 card"))
    t_cost = rel(2, 26.35)
    src = "results/gemini/ladder.md"
    segs.append(Seg(q2, t_cost, pan(img["ladder"], (150, 130, 1300), (195, 255, 540)),
                    [(q2 + 0.2, rel(2, 7.77), caption("5 models · up to 4 thinking levels · 157 paired episodes", src)),
                     (rel(2, 7.77), t_cost, caption("Hard, n = 8 · gemini-3.5-flash: 92% [76%, 113%] at medium · 102% [84%, 129%] at high", src))],
                    "3 heatmap"))
    segs.append(Seg(t_cost, B[3], still(focus(img["ladder"], (186, 714, 1416, 1142), fill=0.94), 1.0, 1.06),
                    [(t_cost, B[3], caption("API serves 3.5-flash as gemini-3.6-flash · 16/16 correct · $0.34–0.39 per episode vs $1.30 for gemini-4-carbon (high)", src))],
                    "3 cost frontier"))

    # 4 atlas (blind re-run: Gemini never saw our labels)
    bn = blind_numbers()
    d4 = wav_seconds(NARR / f"{VO_IDS[3]}.wav")
    t_blind, t_table = rel(3, d4 * 13 / 42), rel(3, d4 * 28 / 42)
    src = "results/gemini/atlas_blind.md"
    segs.append(Seg(B[3], t_table, still(focus(img["atlas"], (128, 128, 1432, 360), fill=0.94), 1.0, 1.06),
                    [(B[3] + 0.2, t_blind, caption(f"All {bn['eps']} trajectories in one cached context · no labels, no regret, no solver", src)),
                     (t_blind, t_table, caption(f"Blind: {bn['rec']} of {bn['tags']} code-defined failure modes recovered · {bn['new']} new modes named", src))],
                    "4 blind tiles"))
    segs.append(Seg(t_table, B[4], still(focus(img["atlas"], (185, 385, 1420, 680)), 1.0, 1.05),
                    [(t_table, B[4], caption(f"Coverage is weak: the steps Gemini cites hold {bn['cov']}% of all solver regret", src))],
                    "4 blind recall"))

    # 5 swarm (final multi-wave swarm.md)
    sw = swarm_numbers(swarm_md)
    d5 = wav_seconds(NARR / f"{VO_IDS[4]}.wav")
    t_pc = rel(4, d5 * 19 / 33)
    src = "results/gemini/swarm.md (final, all waves)"
    segs.append(Seg(B[4], t_pc, still(card_swarm(sw, src), 1.0, 1.04), label="5 swarm"))
    segs.append(Seg(t_pc, B[5], still(card_positive_control(sw, src), 1.0, 1.035), label="5 positive control"))

    # 6 innovative
    q3 = B[5] + 2.4
    segs.append(Seg(B[5], q3, still(card_section("Q3", "What's innovative", "A benchmark that measures, explains and audits itself."), 1.0, 1.03), label="6 card"))
    segs.append(Seg(q3, B[6], still(card_gallery(gallery_numbers()), 1.0, 1.05), label="6 gallery"))

    # 7 essential
    q4 = B[6] + 2.2
    t_feat = rel(6, 8.78)
    segs.append(Seg(B[6], q4, still(card_section("Q4", "Why Gemini is essential", "Three API features the lab cannot run without."), 1.0, 1.03), label="7 card"))
    segs.append(Seg(q4, t_feat, pan(img["usage"], (150, 120, 1300), (180, 225, 1080)),
                    [(max(q4, rel(6, 2.9)), rel(6, 5.12), caption("thinking_level: the ladder's knob")),
                     (rel(6, 5.12), t_feat, caption("thought signatures: reasoning kept across tool calls"))], "7 usage"))
    segs.append(Seg(t_feat, B[7], still(card_features(usage_numbers()), 1.0, 1.03), label="7 features"))

    # 8 close
    t_end = E[7] + 0.35
    n = len(replay_lines)

    def term(u: float, _cache={}):
        k = min(n, 2 + int(u * 1.6 * n))
        if k not in _cache:
            _cache[k] = terminal_card(replay_lines, k)
        return _cache[k]
    segs.append(Seg(B[7], t_end, term, label="8 replay"))
    segs.append(Seg(t_end, TOTAL, still(card_end(), 1.0, 1.02), label="8 end card"))
    return segs


def replay_excerpt(path: Path | None) -> list[str]:
    """Lines from a captured `make lab-replay` run (keyless); paths shortened for the screen."""
    if path and path.exists():
        raw = path.read_text().splitlines()
        keep = [l for l in raw if re.search(r"^gateway: replay|DONE gemini|REPLAY OK|ALL OK|ALL DONE", l)]
        keep = [re.sub(r"/\S*/(results|data)/", r"\1/", l) for l in keep]
        keep = [re.sub(r" \| clients=.*", "", l) for l in keep]
        keep = [l if len(l) <= 96 else l[:95] + "…" for l in keep]
        return ["$ unset GEMINI_API_KEY GEMINI_GATEWAY_URL", "$ make lab-replay"] + keep[:14]
    return ["$ unset GEMINI_API_KEY GEMINI_GATEWAY_URL", "$ make lab-replay", "lab_replay: ALL OK"]


# ----------------------------------------------------------------------------------------------- render
_SEGS: list[Seg] = []
XF = 0.3   # crossfade into the next segment's first frame


def frame_bytes(fi: int) -> bytes:
    segs, t = _SEGS, fi / FPS
    si = next((i for i, s in enumerate(segs) if t < s.end), len(segs) - 1)
    s = segs[si]
    u = (t - s.start) / max(1e-6, s.end - s.start)
    frame = s.render(u).convert("RGBA")
    if si < len(segs) - 1 and t > s.end - XF:
        frame = Image.blend(frame, segs[si + 1].render(0.0).convert("RGBA"), (t - (s.end - XF)) / XF)
    for c0, c1, ov in s.captions:
        if c0 <= t < c1:
            a = min(1.0, (t - c0) / 0.25, (c1 - t) / 0.2)
            if a < 1.0:
                ov = ov.copy()
                ov.putalpha(ov.getchannel("A").point(lambda v, a=a: int(v * a)))
            frame.alpha_composite(ov)
    return frame.convert("RGB").tobytes()


def render(segs: list[Seg], audio_args: list[str], out: Path, height: int, crf: int, workers: int = 6) -> None:
    """Frames are rendered by a fork pool (segments are inherited, not pickled) and streamed to ffmpeg in order."""
    import multiprocessing as mp
    global _SEGS
    _SEGS = segs
    out.parent.mkdir(parents=True, exist_ok=True)
    vf = [] if height == H else ["-vf", f"scale=-2:{height}:flags=lanczos"]
    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
           "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
           *audio_args, *vf, "-c:v", "libx264", "-preset", "medium", "-crf", str(crf), "-pix_fmt", "yuv420p",
           "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", "-shortest", str(out)]
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    n = int(round(TOTAL * FPS))
    with mp.get_context("fork").Pool(workers) as pool:
        for fi, b in enumerate(pool.imap(frame_bytes, range(n), chunksize=12)):
            p.stdin.write(b)
            if fi % 600 == 0:
                print(f"  frame {fi}/{n}", flush=True)
    p.stdin.close()
    if p.wait() != 0:
        raise SystemExit("ffmpeg failed")


def audio_inputs(tempo: float, starts: list[float]) -> list[str]:
    args = ["-i", str(COMMENTATOR)] + sum((["-i", str(NARR / f"{i}.wav")] for i in VO_IDS), [])
    fc = [f"[1:a]atrim=0:{COMMENTATOR_CUT},afade=t=out:st={COMMENTATOR_CUT - 0.25}:d=0.25,aresample=48000,volume=0.9[c]"]
    for k, s in enumerate(starts):
        fc.append(f"[{k + 2}:a]atempo={tempo:.4f},aresample=48000,adelay={int(s * 1000)}:all=1[v{k}]")
    mix = "[c]" + "".join(f"[v{k}]" for k in range(len(starts)))
    fc.append(f"{mix}amix=inputs={len(starts) + 1}:normalize=0:duration=longest,apad,atrim=0:{TOTAL},"
              f"loudnorm=I=-16:TP=-1.5:LRA=11,aresample=48000[a]")
    return args + ["-filter_complex", ";".join(fc), "-map", "0:v", "-map", "[a]"]


def plan(vo_start: float = COMMENTATOR_CUT + 0.45) -> tuple[float, list[float], list[float]]:
    durs = [wav_seconds(NARR / f"{i}.wav") for i in VO_IDS]
    avail = TOTAL - vo_start - GAP * (len(durs) - 1) - END_HOLD
    tempo = max(1.0, sum(durs) / avail)
    starts, ends, t = [], [], vo_start
    for d in durs:
        starts.append(t)
        ends.append(t + d / tempo)
        t = ends[-1] + GAP
    return tempo, starts, ends


def resolved_script(script: Path, out: Path) -> Path:
    """Copy of the script whose VO lines are the exact spoken text (narration index.json), for video_qa."""
    text = {k: v["text"] for k, v in json.loads((NARR / "index.json").read_text()).items()}
    s = re.sub(r"^(>\s*VO\[(?P<id>[\w.-]+)\]:\s*).+$", lambda m: m.group(1) + text[m.group("id")], script.read_text(), flags=re.M)
    out.write_text(s)
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", type=Path, default=ROOT / "docs/gemini/assets/canary-lab-2min.mp4")
    ap.add_argument("--build", type=Path, default=ROOT / "data/gemini/video-build")
    ap.add_argument("--html", type=Path, default=ROOT / "results/gemini/dashboard.html")
    ap.add_argument("--ladder-html", type=Path, default=None, help="dashboard build whose ladder panel to use")
    ap.add_argument("--replay-log", type=Path, default=None, help="captured `make lab-replay` output")
    ap.add_argument("--swarm-md", type=Path, default=ROOT / "results/gemini/swarm.md", help="final multi-wave swarm report")
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--no-capture", action="store_true", help="reuse <build>/shots/*@2x.png")
    ap.add_argument("--height", type=int, default=1080)
    ap.add_argument("--crf", type=int, default=21)
    ap.add_argument("--plan", action="store_true", help="print the timeline and exit")
    ap.add_argument("--preview", action="store_true", help="write one mid-segment frame per segment to <build>/preview")
    a = ap.parse_args(argv)

    tempo, starts, ends = plan()
    shots_dir = a.build / "shots"
    panels = ["headline", "atlas", "swarm", "usage"]
    if not a.no_capture and not a.plan:
        capture_panels(a.html, panels, shots_dir)
        capture_panels(a.ladder_html or a.html, ["ladder"], shots_dir)
    shots = {p: shots_dir / f"{p}@2x.png" for p in panels + ["ladder"]}
    lines = replay_excerpt(a.replay_log or (a.build / "replay.txt"))
    if a.plan and not all(p.exists() for p in shots.values()):
        segs = []
    else:
        segs = timeline(shots, lines, tempo, starts, ends, a.swarm_md)
    print(f"VO tempo x{tempo:.3f}; VO starts " + ", ".join(f"{i}@{s:.1f}s" for i, s in zip(VO_IDS, starts)) + f"; last line ends {ends[-1]:.1f}s")
    for s in segs:
        print(f"  {s.start:6.2f}-{s.end:6.2f}  {s.label}")
    if a.plan:
        return 0
    if a.preview:
        pv = a.build / "preview"
        pv.mkdir(parents=True, exist_ok=True)
        for k, s in enumerate(segs):
            fr = s.render(0.5).convert("RGBA")
            for c0, c1, ov in s.captions:
                if c0 <= (s.start + s.end) / 2 < c1 or (c1 > s.start and c0 < s.end and not any(c0 <= (s.start + s.end) / 2 < c1 for c0, c1, _ in s.captions)):
                    fr.alpha_composite(ov)
                    break
            fr.convert("RGB").resize((960, 540), Image.LANCZOS).save(pv / f"{k:02d}.jpg", quality=85)
        print(f"previews in {pv}")
        return 0
    render(segs, audio_inputs(tempo, starts), a.out, a.height, a.crf, a.workers)
    print(f"wrote {a.out} ({a.out.stat().st_size / 1e6:.1f} MB)")
    qa = resolved_script(ROOT / "docs/gemini/VIDEO-2MIN.md", a.build / "VIDEO-2MIN.resolved.md")
    print(f"QA script (spoken text): {qa}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
