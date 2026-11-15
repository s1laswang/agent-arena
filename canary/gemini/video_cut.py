"""Assemble the 2-minute Gemini demo video (docs/gemini/VIDEO-2MIN.md): HoldUp opening, then the Canary Lab proof.

    python -m canary.gemini.video_cut [--out docs/gemini/assets/canary-lab-2min.mp4] [--build data/gemini/video-build]
                                      [--html PATH] [--ladder-html PATH] [--no-capture] [--no-xprov] [--plan] [--preview]

Keyless and local: no Gemini calls. Inputs are committed files only:
  - shot 0: docs/gemini/assets/holdup-demo-20s.mp4, two 10 s stretches (11-21 s, 44.25-54.25 s) of
    docs/demo/holdup-mock-demo.mp4 at s1laswang/junction-meta-glasses tag gemini-quote-0515, scaled 1.2x with its yellow
    simulation banner kept in frame (see VIDEO-2MIN.md for the fetch + cut command);
  - dashboard panels, captured with headless Chrome at 2x (same `?panel=` focus mode as canary.gemini.shoot);
  - narration clips docs/gemini/assets/narration-2min/<id>.wav and the Live commentator clip;
  - numbers on cards are parsed from, or cited to, committed result files (source line on every caption);
  - optional: results/gemini/xprov.png (cross-provider control), used only if it and the clip 03b-xprov.wav exist.
The timeline is data-driven (`shots_v2`): each shot lasts lead + clip/tempo + tail (shot 0 at least 20 s). The VO tempo
is 1.0 unless the cut would exceed --max-total (140 s), then the slowest atempo factor that fits (pitch kept) is used.
The v1 cut (fixed 2:00, eight clips) is the gemini-pr2 version of this file in git history.
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
MAX_TOTAL = 139.5               # v2 spec: <= 2:20 (0.5 s margin for container rounding)
NARR = ROOT / "docs/gemini/assets/narration-2min"
COMMENTATOR = ROOT / "docs/gemini/assets/narration/commentator-demo.wav"
COMMENTATOR_CUT = 5.45          # natural pause in the commentator clip (silencedetect 5.25-5.60 s)
END_HOLD = 2.2                  # end card after the last line
HOLDUP_CLIP = ROOT / "docs/gemini/assets/holdup-demo-20s.mp4"
HOLDUP_SECONDS = 20.0
HOLDUP_SCALE = 1.2              # 1280x720 -> 1536x864 at top-left; captions use the freed right column and bottom band
HOLDUP_BG = (9, 15, 22)         # the HoldUp page background, so the scaled frame sits seamlessly
XPROV_PNG = ROOT / "results/gemini/xprov.png"
LADDER_FRONTIER_BOX = (186, 714, 1416, 1142)   # cost-frontier region of the ladder panel (1x page coords)
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
    d.text((306, 530), "Gemini plays, attacks and explains", font=font("sans", 50), fill=DARK_INK)
    d.text((306, 600), "an insider-threat benchmark.", font=font("sans", 50), fill=DARK_MUTED)
    kicker(d, (306, 300), "GOOGLE DEEPMIND · BEST USE OF GEMINI API", DARK_MUTED)
    return im


def card_hook() -> Image.Image:
    im, d = canvas(DARK)
    f = font("serif", 96)
    d.text((160, 380), "How do you earn", font=f, fill=DARK_INK)
    d.text((160, 500), "trust in an agent?", font=font("serif_b", 96), fill=ACCENT)
    kicker(d, (164, 320), "HOLDUP IS THE PRODUCT · CANARY LAB IS THE PROOF", DARK_MUTED)
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


@dataclass
class Shot:
    """One beat of the cut. Its length comes from its narration clip: lead + clip/tempo + tail (at least min_dur);
    a shot without a clip has a fixed length. `audio` is a non-VO clip played from the shot start, untempo'd."""
    key: str
    vo: str | None = None
    lead: float = 0.23
    tail: float = 0.22
    min_dur: float = 0.0
    fixed: float = 0.0
    audio: tuple[Path, float] | None = None       # (wav, trim seconds)


@dataclass
class Slot:
    shot: Shot
    t0: float
    t1: float
    vs: float = 0.0          # VO start (absolute)
    ve: float = 0.0          # VO end (absolute)


def shots_v2(xprov: bool = False) -> list[Shot]:
    s = [Shot("holdup", "00-holdup", lead=0.5, min_dur=HOLDUP_SECONDS),
         Shot("hook", "01-hook"),
         Shot("live", fixed=COMMENTATOR_CUT + 0.45, audio=(COMMENTATOR, COMMENTATOR_CUT)),
         Shot("ladder", "03-ladder")]
    if xprov:
        s.append(Shot("xprov", "03b-xprov"))
    s += [Shot("atlas", "04-atlas"), Shot("swarm", "05-swarm"), Shot("innovative", "06-innovative"),
          Shot("essential", "07-essential"), Shot("close", "08-close", tail=END_HOLD)]
    return s


def layout(shots: list[Shot], tempo: float, durs: dict[str, float]) -> list[Slot]:
    slots, t = [], 0.0
    for sh in shots:
        if sh.vo:
            vs = t + sh.lead
            ve = vs + durs[sh.vo] / tempo
            t1 = max(t + sh.min_dur, ve + sh.tail)
        else:
            vs = ve = t
            t1 = t + sh.fixed
        slots.append(Slot(sh, t, t1, vs, ve))
        t = t1
    return slots


def plan(shots: list[Shot] | None = None, max_total: float = MAX_TOTAL, narr: Path | None = None) -> tuple[float, list[Slot]]:
    """Slowest VO tempo (>= 1, pitch kept) at which the whole cut fits in max_total; shot lengths follow the clips."""
    shots = shots if shots is not None else shots_v2(xprov_available())
    narr = narr or NARR
    durs = {sh.vo: wav_seconds(narr / f"{sh.vo}.wav") for sh in shots if sh.vo}
    total = lambda k: layout(shots, k, durs)[-1].t1
    tempo = 1.0
    if total(1.0) > max_total:
        lo, hi = 1.0, 3.0
        for _ in range(50):
            mid = (lo + hi) / 2
            lo, hi = (mid, hi) if total(mid) > max_total else (lo, mid)
        tempo = hi
    return tempo, layout(shots, tempo, durs)


def xprov_available() -> bool:
    return XPROV_PNG.exists() and (NARR / "03b-xprov.wav").exists()


def ladder_numbers(md_path: Path = ROOT / "results/gemini/ladder.md") -> dict:
    """Hard-tier cells quoted in VO[03] (carbon high, 3.6-flash high) and the episode count, from ladder.md."""
    md = md_path.read_text()
    hard = md.split("## hard", 1)[1]
    def cell(model: str, level: str) -> dict:
        m = re.search(rf"^\| {re.escape(model)} \| {level} \| (\d+) \|.*?\*\*([-\d]+% \[[^\]]+\])\*\*.*\| ([\d.]+) \| [\d.]+ \|$", hard, re.M)
        return {"n": int(m.group(1)), "ratio": m.group(2), "usd": float(m.group(3))}
    return {"episodes": int(re.search(r"(\d+) valid Gemini episodes", md).group(1)),
            "carbon": cell("gemini-4-carbon", "high"), "flash": cell("gemini-3.6-flash (requested as 3.5-flash)", "high")}


class HoldupFrames:
    """The committed 20 s HoldUp segment, decoded once to JPEGs at the cut's frame rate and HOLDUP_SCALE."""
    def __init__(self, src: Path, build: Path):
        self.dir = build / "holdup"
        self.size = (round(1280 * HOLDUP_SCALE), round(720 * HOLDUP_SCALE))
        stamp = self.dir / f".src-{src.stat().st_size}-{self.size[0]}"
        if not stamp.exists():
            self.dir.mkdir(parents=True, exist_ok=True)
            for old in self.dir.glob("*.jpg"):
                old.unlink()
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(src), "-vf",
                            f"fps={FPS},scale={self.size[0]}:{self.size[1]}:flags=lanczos", "-q:v", "2",
                            str(self.dir / "%04d.jpg")], check=True)
            stamp.touch()
        self.n = len(list(self.dir.glob("*.jpg")))

    def at(self, t: float) -> Image.Image:
        k = min(self.n, max(1, int(t * FPS) + 1))   # holds the last frame if the shot outlasts the clip
        return Image.open(self.dir / f"{k:04d}.jpg").convert("RGB")


def side_caption(title: str, source: str = "", y: int = 120, x: int = 1430, maxw: int = 440, size: int = 36) -> Image.Image:
    """Caption box for the empty right column next to the scaled HoldUp frame."""
    ov = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(ov)
    ft, fs = sans_b(size), font("mono", 19)
    tl = wrap(d, title, ft, maxw)
    sl = wrap(d, source, fs, maxw) if source else []
    h = 30 + int(size * 1.3) * len(tl) + 26 * len(sl) + (10 if sl else 0) + 18
    d.rounded_rectangle((x - 30, y, x + maxw + 24, y + h), 16, fill=(24, 27, 33, 240))
    d.rectangle((x - 30, y + 14, x - 22, y + h - 14), fill=ACCENT + (255,))
    for i, t in enumerate(tl):
        d.text((x, y + 22 + i * int(size * 1.3)), t, font=ft, fill=(250, 248, 240, 255))
    for i, t in enumerate(sl):
        d.text((x, y + 32 + int(size * 1.3) * len(tl) + i * 26), t, font=fs, fill=(170, 170, 165, 255))
    return ov


def holdup_render(frames: HoldupFrames, dur: float) -> Callable[[float], Image.Image]:
    def f(u: float) -> Image.Image:
        im = Image.new("RGB", (W, H), HOLDUP_BG)
        im.paste(frames.at(u * dur), (0, 0))       # top-left: the yellow SIMULATION banner stays in frame
        return im
    return f


def timeline(slots: list[Slot], shots_png: dict[str, Path], replay_lines: list[str], tempo: float,
             swarm_md: Path = ROOT / "results/gemini/swarm.md", holdup: HoldupFrames | None = None) -> list[Seg]:
    by = {s.shot.key: s for s in slots}
    img = {k: Image.open(v) for k, v in shots_png.items()}
    total = slots[-1].t1
    segs: list[Seg] = []

    def at(key: str, frac: float) -> float:
        """Absolute time of a word fraction of the shot's clip, snapped to the nearest real pause."""
        s = by[key]
        clip = s.shot.vo
        return s.vs + snap(clip, wav_seconds(NARR / f"{clip}.wav") * frac) / tempo

    # 0 HoldUp (browser simulation of the glasses flow; its own yellow banner stays visible)
    s = by["holdup"]
    hsrc = "github.com/s1laswang/junction-meta-glasses · docs/demo/holdup-mock-demo.mp4 @ gemini-quote-0515"
    t_live, t_754 = at("holdup", 8 / 43), at("holdup", 33 / 43)
    segs.append(Seg(s.t0, s.t1, holdup_render(holdup, s.t1 - s.t0),
                    [(s.t0, s.t1, side_caption("HoldUp: browser simulation of the glasses flow", hsrc, y=110)),
                     (t_live, s.t1, side_caption("Product: Gemini Live API · camera + voice in, speech out", y=470, size=32)),
                     (t_754, s.t1, caption("0 of 754 confident strength reads were wrong (1,740 images, 95% upper bound 0.4%)",
                                           "junction-meta-glasses GEMINI.md @ gemini-quote-0515 (offline eval, not this simulation)"))],
                    "0 holdup"))

    # 1 hook: the trust question, then the Canary Lab title
    s = by["hook"]
    t_lab = at("hook", 8 / 19)
    segs.append(Seg(s.t0, t_lab, still(card_hook(), 1.0, 1.04), label="1 hook"))
    segs.append(Seg(t_lab, s.t1, still(card_intro(), 1.0, 1.03), label="1 title"))

    # 1b Gemini Live commentator over the game headline panel
    s = by["live"]
    segs.append(Seg(s.t0, s.t1, pan(img["headline"], (150, 0, 1300), (160, 10, 1000)),
                    [(s.t0 + 0.3, s.t1, caption("Live commentary: Gemini Live API", "assets/narration/commentator-demo.wav · gemini-3.8-live"))],
                    "1 live commentary"))

    # 3 ladder (numbers parsed from results/gemini/ladder.md)
    s = by["ladder"]
    L = ladder_numbers()
    src = "results/gemini/ladder.md"
    q2 = s.t0 + 2.2
    t_hard, t_cost = at("ladder", 15 / 77), at("ladder", 44 / 77)
    c, fl = L["carbon"], L["flash"]
    segs.append(Seg(s.t0, q2, still(card_section("Q2", "Gemini integration", "Gemini plays: five models, up to four thinking levels, paired with a Bayesian solver."), 1.0, 1.03), label="3 card"))
    segs.append(Seg(q2, t_cost, pan(img["ladder"], (150, 130, 1300), (195, 255, 540)),
                    [(q2 + 0.2, t_hard, caption(f"5 models · up to 4 thinking levels · {L['episodes']} paired episodes", src)),
                     (t_hard, t_cost, caption(f"Hard · gemini-4-carbon, high thinking: {c['ratio']} of the solver · ${c['usd']:.2f} per episode (n = {c['n']})", src))],
                    "3 heatmap"))
    segs.append(Seg(t_cost, s.t1, still(focus(img["ladder"], LADDER_FRONTIER_BOX, fill=0.94), 1.0, 1.06),
                    [(t_cost, s.t1, caption(f"Hard · gemini-3.6-flash (requested as 3.5-flash), high thinking: {fl['ratio']} of the solver · "
                                            f"${fl['usd']:.2f} per episode (n = {fl['n']}) · not distinguishable, wider CI", src))],
                    "3 cost frontier"))

    # 3b cross-provider control (optional)
    if "xprov" in by:
        s = by["xprov"]
        xp = Image.open(XPROV_PNG).convert("RGB")
        k = min(W * 0.92 / xp.width, (H - 200) * 0.95 / xp.height)
        xp = xp.resize((round(xp.width * k), round(xp.height * k)), Image.LANCZOS)
        im, _ = canvas(BG)
        im.paste(xp, ((W - xp.width) // 2, max(30, (H - 200 - xp.height) // 2)))
        segs.append(Seg(s.t0, s.t1, still(im, 1.0, 1.03),
                        [(s.t0 + 0.2, s.t1, caption("Cross-provider control", "results/gemini/xprov.md · results/gemini/xprov.png"))], "3b xprov"))

    # 4 atlas (blind re-run: Gemini never saw our labels)
    s = by["atlas"]
    bn = blind_numbers()
    t_blind, t_table = at("atlas", 13 / 42), at("atlas", 28 / 42)
    src = "results/gemini/atlas_blind.md"
    segs.append(Seg(s.t0, t_table, still(focus(img["atlas"], (128, 128, 1432, 360), fill=0.94), 1.0, 1.06),
                    [(s.t0 + 0.2, t_blind, caption(f"All {bn['eps']} trajectories in one cached context · no labels, no regret, no solver", src)),
                     (t_blind, t_table, caption(f"Blind: {bn['rec']} of {bn['tags']} code-defined failure modes recovered · {bn['new']} new modes named", src))],
                    "4 blind tiles"))
    segs.append(Seg(t_table, s.t1, still(focus(img["atlas"], (185, 385, 1420, 680)), 1.0, 1.05),
                    [(t_table, s.t1, caption(f"Coverage is weak: the steps Gemini cites hold {bn['cov']}% of all solver regret", src))],
                    "4 blind recall"))

    # 5 swarm (final multi-wave swarm.md)
    s = by["swarm"]
    sw = swarm_numbers(swarm_md)
    t_pc = at("swarm", 19 / 33)
    src = "results/gemini/swarm.md (final, all waves)"
    segs.append(Seg(s.t0, t_pc, still(card_swarm(sw, src), 1.0, 1.04), label="5 swarm"))
    segs.append(Seg(t_pc, s.t1, still(card_positive_control(sw, src), 1.0, 1.035), label="5 positive control"))

    # 6 innovative
    s = by["innovative"]
    q3 = s.t0 + 2.4
    segs.append(Seg(s.t0, q3, still(card_section("Q3", "What's innovative", "A benchmark that measures, explains and audits itself."), 1.0, 1.03), label="6 card"))
    segs.append(Seg(q3, s.t1, still(card_gallery(gallery_numbers()), 1.0, 1.05), label="6 gallery"))

    # 7 essential
    s = by["essential"]
    q4 = s.t0 + 2.2
    t_feat = at("essential", 19 / 43)
    segs.append(Seg(s.t0, q4, still(card_section("Q4", "Why Gemini is essential", "Three API features the lab cannot run without."), 1.0, 1.03), label="7 card"))
    segs.append(Seg(q4, t_feat, pan(img["usage"], (150, 120, 1300), (180, 225, 1080)),
                    [(max(q4, at("essential", 6 / 43)), at("essential", 12 / 43), caption("thinking_level: the ladder's knob")),
                     (at("essential", 12 / 43), t_feat, caption("thought signatures: reasoning kept across tool calls"))], "7 usage"))
    segs.append(Seg(t_feat, s.t1, still(card_features(usage_numbers()), 1.0, 1.03), label="7 features"))

    # 8 close
    s = by["close"]
    t_end = s.ve + 0.35
    n = len(replay_lines)

    def term(u: float, _cache={}):
        k = min(n, 2 + int(u * 1.6 * n))
        if k not in _cache:
            _cache[k] = terminal_card(replay_lines, k)
        return _cache[k]
    segs.append(Seg(s.t0, t_end, term, label="8 replay"))
    segs.append(Seg(t_end, total, still(card_end(), 1.0, 1.02), label="8 end card"))
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


def render(segs: list[Seg], audio_args: list[str], out: Path, height: int, crf: int, total: float, workers: int = 6) -> None:
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
    n = int(round(total * FPS))
    with mp.get_context("fork").Pool(workers) as pool:
        for fi, b in enumerate(pool.imap(frame_bytes, range(n), chunksize=12)):
            p.stdin.write(b)
            if fi % 600 == 0:
                print(f"  frame {fi}/{n}", flush=True)
    p.stdin.close()
    if p.wait() != 0:
        raise SystemExit("ffmpeg failed")


def audio_inputs(tempo: float, slots: list[Slot]) -> list[str]:
    """Every VO clip at its slot's start (one tempo), plus untempo'd shot audio (the Live commentator), mixed and loudnormed."""
    args, fc, labels = [], [], []
    k = 1                                   # input 0 is the raw video pipe
    total = slots[-1].t1
    for s in slots:
        if s.shot.audio:
            wav, trim = s.shot.audio
            args += ["-i", str(wav)]
            fc.append(f"[{k}:a]atrim=0:{trim},afade=t=out:st={trim - 0.25}:d=0.25,aresample=48000,volume=0.9,"
                      f"adelay={int(s.t0 * 1000)}:all=1[a{k}]")
            labels.append(f"[a{k}]")
            k += 1
        if s.shot.vo:
            args += ["-i", str(NARR / f"{s.shot.vo}.wav")]
            fc.append(f"[{k}:a]atempo={tempo:.4f},aresample=48000,adelay={int(s.vs * 1000)}:all=1[a{k}]")
            labels.append(f"[a{k}]")
            k += 1
    fc.append(f"{''.join(labels)}amix=inputs={len(labels)}:normalize=0:duration=longest,apad,atrim=0:{total},"
              f"loudnorm=I=-16:TP=-1.5:LRA=11,aresample=48000[a]")
    return args + ["-filter_complex", ";".join(fc), "-map", "0:v", "-map", "[a]"]


def resolved_script(script: Path, out: Path) -> Path:
    """Copy of the script whose VO lines are the exact spoken text (narration index.json), for video_qa.
    Lines whose clip is not in the cut (e.g. the optional VO[03b-xprov] before it is narrated) are dropped."""
    text = {k: v["text"] for k, v in json.loads((NARR / "index.json").read_text()).items()}
    lines = []
    for line in script.read_text().splitlines(keepends=True):
        m = re.match(r"^(>\s*VO\[(?P<id>[\w.-]+)\]:\s*).+$", line.rstrip("\n"))
        if m:
            if m.group("id") not in text or not (NARR / f"{m.group('id')}.wav").exists():
                continue
            line = m.group(1) + text[m.group("id")] + "\n"
        lines.append(line)
    out.write_text("".join(lines))
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", type=Path, default=ROOT / "docs/gemini/assets/canary-lab-2min.mp4")
    ap.add_argument("--build", type=Path, default=ROOT / "data/gemini/video-build")
    ap.add_argument("--html", type=Path, default=ROOT / "results/gemini/dashboard.html")
    ap.add_argument("--ladder-html", type=Path, default=None, help="dashboard build whose ladder panel to use")
    ap.add_argument("--replay-log", type=Path, default=None, help="captured `make lab-replay` output")
    ap.add_argument("--swarm-md", type=Path, default=ROOT / "results/gemini/swarm.md", help="final multi-wave swarm report")
    ap.add_argument("--holdup", type=Path, default=HOLDUP_CLIP, help="20 s HoldUp segment (shot 0)")
    ap.add_argument("--no-xprov", action="store_true", help="skip the optional cross-provider shot even if its inputs exist")
    ap.add_argument("--max-total", type=float, default=MAX_TOTAL)
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--no-capture", action="store_true", help="reuse <build>/shots/*@2x.png")
    ap.add_argument("--height", type=int, default=1080)
    ap.add_argument("--crf", type=int, default=21)
    ap.add_argument("--plan", action="store_true", help="print the timeline and exit")
    ap.add_argument("--preview", action="store_true", help="write one mid-segment frame per segment to <build>/preview")
    a = ap.parse_args(argv)

    tempo, slots = plan(shots_v2(xprov_available() and not a.no_xprov), a.max_total)
    total = slots[-1].t1
    shots_dir = a.build / "shots"
    panels = ["headline", "atlas", "swarm", "usage"]
    if not a.no_capture and not a.plan:
        capture_panels(a.html, panels, shots_dir)
        capture_panels(a.ladder_html or a.html, ["ladder"], shots_dir)
    shots = {p: shots_dir / f"{p}@2x.png" for p in panels + ["ladder"]}
    lines = replay_excerpt(a.replay_log or (a.build / "replay.txt"))
    print(f"VO tempo x{tempo:.3f}; total {total:.2f} s")
    for s in slots:
        print(f"  shot {s.shot.key:10s} {s.t0:6.2f}-{s.t1:6.2f}" + (f"  VO {s.shot.vo} {s.vs:.2f}-{s.ve:.2f}" if s.shot.vo else ""))
    if a.plan and not all(p.exists() for p in shots.values()):
        return 0
    segs = timeline(slots, shots, lines, tempo, a.swarm_md, HoldupFrames(a.holdup, a.build))
    for s in segs:
        print(f"  {s.start:6.2f}-{s.end:6.2f}  {s.label}")
    if a.plan:
        return 0
    if a.preview:
        pv = a.build / "preview"
        pv.mkdir(parents=True, exist_ok=True)
        for k, s in enumerate(segs):
            tm = s.end - 0.5 if s.end - s.start > 1.2 else (s.start + s.end) / 2
            fr = s.render((tm - s.start) / max(1e-6, s.end - s.start)).convert("RGBA")
            for c0, c1, ov in s.captions:
                if c0 <= tm < c1:
                    fr.alpha_composite(ov)
            fr.convert("RGB").resize((960, 540), Image.LANCZOS).save(pv / f"{k:02d}.jpg", quality=85)
        print(f"previews in {pv}")
        return 0
    render(segs, audio_inputs(tempo, slots), a.out, a.height, a.crf, total, a.workers)
    print(f"wrote {a.out} ({a.out.stat().st_size / 1e6:.1f} MB, {total:.2f} s)")
    qa = resolved_script(ROOT / "docs/gemini/VIDEO-2MIN.md", a.build / "VIDEO-2MIN.resolved.md")
    print(f"QA script (spoken text): {qa}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
