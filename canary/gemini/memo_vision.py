from __future__ import annotations

import hashlib
import io
import json
import os
import random
import re
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any, Callable

from PIL import Image, ImageDraw, ImageFont

from canary.env import Env
from canary.eval import run_episode
from canary.gemini.ledger import record
from canary.gemini.sdk import genai_client
from canary.llm.base import LLMError, is_retryable
from canary.rules import TIERS_VERSION
from canary.solver.policy import SolverPolicy
from canary.types import EpisodeResult, Step, ToolResult

DEFAULT_MODEL = "gemini-4-carbon"
FEATURE = "multimodal_evidence"
SUBROLE = "visual_memo_blind_ablation"
VALID_VARIANTS = ("A", "B", "C", "D", "E", "F", "G", "H")
MEMO_IMAGE_SIZE = (880, 620)
VISION_MODES = frozenset({"gemini", "blind", "stub"})

VARIANT_PALETTE: dict[str, tuple[tuple[int, int, int], tuple[int, int, int]]] = {
    "A": ((18, 128, 82), (226, 250, 238)),
    "B": ((26, 92, 184), (228, 240, 255)),
    "C": ((186, 52, 42), (255, 234, 230)),
    "D": ((132, 56, 168), (245, 232, 254)),
    "E": ((184, 118, 18), (255, 244, 224)),
    "F": ((18, 132, 148), (226, 248, 252)),
    "G": ((164, 42, 108), (254, 232, 244)),
    "H": ((62, 88, 122), (232, 238, 248)),
}

MEMO_VISION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "observed_doc_id": {
            "type": "string",
            "description": "Exact document ID printed on the leaked memo scan, such as c3 or d1-1.",
        },
        "observed_day_surfaced": {
            "type": "integer",
            "description": "Integer day surfaced printed on the leaked memo scan.",
        },
        "has_canary_watermark": {
            "type": "boolean",
            "description": "True if the scan carries a controlled canary watermark (A-H), False if COPY-CODE: NONE.",
        },
        "copy_code_variant": {
            "type": "string",
            "description": "Single uppercase canary variant letter A-H read from COPY-CODE: <variant>, header bar pattern, and footer ticks, or NONE if unwatermarked.",
        },
        "observed_footer_ticks": {
            "type": "integer",
            "description": "Active watermark tick count in the footer register (0 for NONE, 1 for A, 2 for B, 3 for C, up to 8 for H).",
        },
        "confidence": {
            "type": "number",
            "description": "Confidence between 0.0 and 1.0 in the visual watermark reading.",
        },
        "visual_evidence": {
            "type": "string",
            "description": "Concise visual readout of the header bar pattern, COPY-CODE stamp, and footer ticks. Use plain ASCII hyphens (-), never em dashes.",
        },
    },
    "required": [
        "observed_doc_id",
        "observed_day_surfaced",
        "has_canary_watermark",
        "copy_code_variant",
        "observed_footer_ticks",
        "confidence",
        "visual_evidence",
    ],
}

MEMO_VISION_PROMPT = (
    "You are a forensic leak investigator inspecting a scanned corporate leaked-memo PNG.\n\n"
    "Read all visual watermark fields directly from the scanned page:\n"
    "1. Top Header Bar Pattern: watermarked canary memos display N colored patterned bar segments (A=1, B=2, C=3, "
    "D=4, E=5, F=6, G=7, H=8) alongside a 'VARIANT <letter>' banner; unwatermarked regular memos display a flat "
    "neutral gray 'UNWATERMARKED' header bar.\n"
    "2. Central Forensic Stamp Box: reads 'COPY-CODE: <variant>' (single letter A-H) for planted canary memos, or "
    "'COPY-CODE: NONE' for unwatermarked regular memos.\n"
    "3. Bottom Footer Watermark Ticks: an 8-slot tick register (A=1 .. H=8) lighting K tall colored vertical ticks "
    "for variant K, or 0 active ticks for NONE.\n"
    "4. Left Metadata Block: shows DOC-ID and SURFACED: DAY <NN>.\n\n"
    "Return JSON matching the schema. Set copy_code_variant to the exact uppercase letter A-H when watermarked, or "
    "NONE when unwatermarked. Use plain ASCII hyphens (-) in visual_evidence."
)


def sanitize_text(text: str) -> str:
    return (text or "").replace("\u2014", "-").replace("\u2013", "-").strip()


def memo_sha256(png_bytes: bytes) -> str:
    return hashlib.sha256(png_bytes).hexdigest()


def normalize_variant(val: Any) -> str | None:
    if val is None or isinstance(val, bool):
        return None
    raw = str(val).strip().upper()
    if raw in {"", "NONE", "NULL", "UNMARKED", "UNWATERMARKED", "-"}:
        return None
    if raw in VALID_VARIANTS:
        return raw
    m = re.search(r"\b([A-H])\b", raw)
    return m.group(1) if m else None


def extract_public_memo_fields(item: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(item, dict):
        raise ValueError("leak feed item must be a dict")
    doc_id = str(item.get("doc_id") or "").strip()
    if not doc_id:
        raise ValueError("leak feed item missing doc_id")
    raw_day = item.get("day_surfaced") if "day_surfaced" in item else item.get("surfaced_day")
    if raw_day is None or isinstance(raw_day, bool):
        raise ValueError("leak feed item missing day_surfaced / surfaced_day")
    day_surfaced = int(raw_day)
    variant = normalize_variant(item.get("variant"))
    return {
        "doc_id": doc_id,
        "day_surfaced": day_surfaced,
        "variant": variant,
    }


def _load_font(size: int, bold: bool = False, mono: bool = True) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    try:
        import matplotlib
        ttf_dir = Path(matplotlib.get_data_path()) / "fonts" / "ttf"
        if mono:
            fname = "DejaVuSansMono-Bold.ttf" if bold else "DejaVuSansMono.ttf"
        else:
            fname = "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
        fpath = ttf_dir / fname
        if fpath.exists():
            return ImageFont.truetype(str(fpath), size=size)
    except Exception:
        pass
    return ImageFont.load_default()


def render_leak_memo_png(*, doc_id: str, day_surfaced: int, variant: str | None = None) -> bytes:
    clean_doc = sanitize_text(str(doc_id))
    if not clean_doc:
        raise ValueError("doc_id must be non-empty")
    day_num = int(day_surfaced)
    norm_var = normalize_variant(variant)
    v_idx = (VALID_VARIANTS.index(norm_var) + 1) if norm_var is not None else 0

    width, height = MEMO_IMAGE_SIZE
    img = Image.new("RGB", (width, height), (20, 26, 38))
    draw = ImageDraw.Draw(img)

    f_hdr_lg = _load_font(16, bold=True, mono=True)
    f_hdr_sm = _load_font(12, bold=True, mono=True)
    f_meta_k = _load_font(12, bold=True, mono=False)
    f_meta_v = _load_font(20, bold=True, mono=True)
    f_stamp_top = _load_font(12, bold=True, mono=False)
    f_stamp_big = _load_font(31, bold=True, mono=True)
    f_stamp_sub = _load_font(13, bold=True, mono=True)
    f_tick_hdr = _load_font(13, bold=True, mono=True)
    f_tick_lbl = _load_font(13, bold=True, mono=True)
    f_tiny = _load_font(11, bold=False, mono=True)

    px0, py0, px1, py1 = 26, 20, width - 26, height - 20
    draw.rounded_rectangle((px0, py0, px1, py1), radius=6, fill=(247, 245, 239), outline=(172, 168, 158), width=2)

    for cx, cy, dx, dy in ((px0 + 8, py0 + 8, 1, 1), (px1 - 8, py0 + 8, -1, 1), (px0 + 8, py1 - 8, 1, -1), (px1 - 8, py1 - 8, -1, -1)):
        draw.line((cx, cy, cx + 14 * dx, cy), fill=(120, 124, 132), width=2)
        draw.line((cx, cy, cx, cy + 14 * dy), fill=(120, 124, 132), width=2)

    hx0, hy0, hx1, hy1 = 46, 38, width - 46, 108
    if norm_var is not None:
        ink, tint = VARIANT_PALETTE[norm_var]
        draw.rounded_rectangle((hx0, hy0, hx1, hy1), radius=5, fill=tint, outline=ink, width=2)
        pat_x0, pat_x1 = hx0 + 10, 476
        total_pat_w = pat_x1 - pat_x0
        gap = 6
        seg_w = max(16, (total_pat_w - gap * (v_idx - 1)) // v_idx)
        for s_i in range(v_idx):
            sx0 = pat_x0 + s_i * (seg_w + gap)
            sx1 = min(pat_x1, sx0 + seg_w)
            draw.rectangle((sx0, hy0 + 10, sx1, hy1 - 10), fill=ink)
            for stripe_x in range(sx0 + 6, sx1 - 2, 12):
                draw.line((stripe_x, hy1 - 12, min(sx1 - 2, stripe_x + 8), hy0 + 12), fill=tint, width=2)
        draw.rounded_rectangle((490, hy0 + 8, hx1 - 10, hy1 - 8), radius=4, fill=ink)
        draw.text((504, hy0 + 14), f"HEADER BAR: {v_idx} SEGMENT(S)", fill=(255, 255, 255), font=f_hdr_sm)
        draw.text((504, hy0 + 34), f"CANARY VARIANT {norm_var}", fill=(255, 255, 255), font=f_hdr_lg)
    else:
        draw.rounded_rectangle((hx0, hy0, hx1, hy1), radius=5, fill=(224, 226, 230), outline=(126, 132, 142), width=2)
        draw.line((hx0 + 14, hy0 + 22, 472, hy0 + 22), fill=(144, 150, 160), width=3)
        draw.line((hx0 + 14, hy1 - 22, 472, hy1 - 22), fill=(144, 150, 160), width=3)
        draw.rounded_rectangle((490, hy0 + 8, hx1 - 10, hy1 - 8), radius=4, fill=(92, 98, 110))
        draw.text((504, hy0 + 14), "HEADER BAR: 0 SEGMENTS", fill=(242, 244, 248), font=f_hdr_sm)
        draw.text((504, hy0 + 34), "UNWATERMARKED (NONE)", fill=(255, 255, 255), font=f_hdr_lg)

    draw.line((46, 122, width - 46, 122), fill=(192, 188, 178), width=1)

    draw.text((50, 136), "INTERCEPTED LEAK FEED MEMORANDUM SCAN", fill=(72, 78, 92), font=f_meta_k)
    draw.rounded_rectangle((48, 160, 398, 246), radius=5, fill=(236, 234, 226), outline=(176, 172, 162), width=1)
    draw.text((62, 172), f"DOC-ID: {clean_doc}", fill=(22, 28, 40), font=f_meta_v)
    draw.text((62, 206), f"SURFACED: DAY {day_num:02d}", fill=(44, 54, 72), font=f_hdr_lg)

    digest = hashlib.sha256(f"{clean_doc}:{day_num}".encode("utf-8")).digest()
    draw.text((50, 264), "SANITIZED BODY EXCERPT (TEXT WATERMARK REDACTED):", fill=(92, 98, 110), font=f_tiny)
    for row_i in range(7):
        ly = 288 + row_i * 25
        line_w = 190 + (digest[row_i] % 135)
        draw.rounded_rectangle((50, ly, 50 + line_w, ly + 11), radius=2, fill=(196, 194, 186))
        if row_i in (1, 4):
            rx0 = 50 + min(line_w - 70, 84)
            draw.rectangle((rx0, ly - 1, rx0 + 78, ly + 12), fill=(48, 54, 66))

    sx0, sy0, sx1, sy1 = 424, 176, width - 48, 398
    if norm_var is not None:
        ink, tint = VARIANT_PALETTE[norm_var]
        draw.rounded_rectangle((sx0, sy0, sx1, sy1), radius=8, fill=tint, outline=ink, width=4)
        draw.rounded_rectangle((sx0 + 8, sy0 + 8, sx1 - 8, sy1 - 8), radius=5, fill=tint, outline=ink, width=2)
        draw.text((sx0 + 24, sy0 + 24), "CONTROLLED CANARY COPY STAMP", fill=ink, font=f_stamp_top)
        draw.line((sx0 + 22, sy0 + 48, sx1 - 22, sy0 + 48), fill=ink, width=2)
        draw.text((sx0 + 26, sy0 + 78), f"COPY-CODE: {norm_var}", fill=ink, font=f_stamp_big)
        draw.line((sx0 + 22, sy0 + 134, sx1 - 22, sy0 + 134), fill=ink, width=2)
        draw.text((sx0 + 26, sy0 + 152), f"WATERMARK VARIANT = {norm_var} ({v_idx}/8)", fill=ink, font=f_stamp_sub)
        draw.text((sx0 + 26, sy0 + 178), f"DOC {clean_doc} | DAY {day_num:02d}", fill=(58, 66, 78), font=f_tiny)
    else:
        ink_n = (88, 94, 108)
        tint_n = (236, 238, 242)
        draw.rounded_rectangle((sx0, sy0, sx1, sy1), radius=8, fill=tint_n, outline=ink_n, width=3)
        draw.rounded_rectangle((sx0 + 8, sy0 + 8, sx1 - 8, sy1 - 8), radius=5, fill=tint_n, outline=(146, 152, 164), width=1)
        draw.text((sx0 + 24, sy0 + 24), "GENERAL RELEASE COPY STAMP", fill=ink_n, font=f_stamp_top)
        draw.line((sx0 + 22, sy0 + 48, sx1 - 22, sy0 + 48), fill=(146, 152, 164), width=2)
        draw.text((sx0 + 26, sy0 + 78), "COPY-CODE: NONE", fill=(52, 58, 70), font=f_stamp_big)
        draw.line((sx0 + 22, sy0 + 134, sx1 - 22, sy0 + 134), fill=(146, 152, 164), width=2)
        draw.text((sx0 + 26, sy0 + 152), "NO CANARY WATERMARK (0/8)", fill=ink_n, font=f_stamp_sub)
        draw.text((sx0 + 26, sy0 + 178), f"DOC {clean_doc} | DAY {day_num:02d}", fill=(88, 94, 108), font=f_tiny)

    fx0, fy0, fx1, fy1 = 46, 476, width - 46, 582
    draw.rounded_rectangle((fx0, fy0, fx1, fy1), radius=6, fill=(28, 35, 48), outline=(72, 86, 112), width=2)
    tick_tag = f"FOOTER TICKS: {v_idx}/8 ACTIVE -> COPY-CODE {norm_var}" if norm_var else "FOOTER TICKS: 0/8 ACTIVE -> COPY-CODE NONE"
    hdr_col = (135, 242, 195) if norm_var else (182, 192, 210)
    draw.text((fx0 + 16, fy0 + 10), tick_tag, fill=hdr_col, font=f_tick_hdr)

    slot_w = 88
    start_x = fx0 + 24
    for idx, letter in enumerate(VALID_VARIANTS, start=1):
        tx0 = start_x + (idx - 1) * slot_w
        active = idx <= v_idx
        is_target = (norm_var == letter)
        if active and norm_var is not None:
            bar_col = VARIANT_PALETTE[norm_var][0]
            outline_col = (255, 255, 255) if is_target else (195, 215, 235)
            draw.rounded_rectangle((tx0, fy0 + 34, tx0 + 68, fy1 - 10), radius=4, fill=bar_col, outline=outline_col, width=2 if is_target else 1)
            for notch in range(3):
                nx = tx0 + 16 + notch * 18
                draw.line((nx, fy0 + 40, nx, fy0 + 62), fill=(255, 255, 255), width=3)
            lbl = f"[{letter}:{idx}]" if is_target else f" {letter}:{idx} "
            draw.text((tx0 + 8, fy0 + 68), lbl, fill=(255, 255, 255), font=f_tick_lbl)
        else:
            draw.rounded_rectangle((tx0, fy1 - 22, tx0 + 68, fy1 - 10), radius=2, fill=(44, 54, 72), outline=(66, 78, 102), width=1)
            draw.text((tx0 + 14, fy0 + 52), f"{letter}:{idx}", fill=(108, 120, 144), font=f_tiny)

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def render_leak_memo_from_item(item: dict[str, Any]) -> bytes:
    pub = extract_public_memo_fields(item)
    return render_leak_memo_png(
        doc_id=pub["doc_id"],
        day_surfaced=pub["day_surfaced"],
        variant=pub["variant"],
    )


def inspect_memo_png(
    png_bytes: bytes,
    *,
    model_id: str = DEFAULT_MODEL,
    sdk_client: Any = None,
    run_id: str = "",
    seed: int | None = None,
    thinking_level: str | None = None,
    max_retries: int | None = None,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    from google.genai import types

    if sdk_client is None:
        sdk_client = genai_client()

    retries = int(os.environ.get("CANARY_LLM_MAX_RETRIES", "10")) if max_retries is None else int(max_retries)
    img_sha = memo_sha256(png_bytes)
    image_part = types.Part.from_bytes(data=png_bytes, mime_type="image/png")

    tc_kwargs: dict[str, Any] = {"include_thoughts": True}
    if thinking_level:
        tc_kwargs["thinking_level"] = thinking_level.upper()

    cfg = types.GenerateContentConfig(
        response_mime_type="application/json",
        response_json_schema=MEMO_VISION_SCHEMA,
        thinking_config=types.ThinkingConfig(**tc_kwargs),
    )

    meta: dict[str, Any] = {"role": FEATURE, "subrole": SUBROLE, "memo_sha256": img_sha}
    if seed is not None:
        meta["seed"] = seed

    attempt = 0
    while True:
        t0 = time.time()
        try:
            resp = sdk_client.models.generate_content(
                model=model_id,
                contents=[image_part, MEMO_VISION_PROMPT],
                config=cfg,
            )
            dt = time.time() - t0
            um = getattr(resp, "usage_metadata", None)
            raw_text = getattr(resp, "text", None) or ""
            if not raw_text.strip():
                cands = getattr(resp, "candidates", None) or []
                if cands and getattr(cands[0], "content", None):
                    parts = getattr(cands[0].content, "parts", None) or []
                    raw_text = "".join(
                        p.text for p in parts if getattr(p, "text", None) and not getattr(p, "thought", False)
                    )
            if not raw_text.strip():
                record(
                    FEATURE,
                    model_id,
                    kind="generate",
                    usage=um,
                    latency_s=dt,
                    ok=False,
                    error="EmptyResponseError: empty JSON response text",
                    run_id=run_id,
                    meta=meta,
                )
                raise LLMError("EmptyResponseError: empty JSON response text from memo vision call")
            parsed = json.loads(raw_text)
            ledger_row = record(
                FEATURE,
                model_id,
                kind="generate",
                usage=um,
                latency_s=dt,
                ok=True,
                run_id=run_id,
                meta=meta,
            )
            break
        except Exception as exc:
            dt = time.time() - t0
            if not isinstance(exc, LLMError):
                record(
                    FEATURE,
                    model_id,
                    kind="generate",
                    usage=None,
                    latency_s=dt,
                    ok=False,
                    error=f"{type(exc).__name__}: {exc}",
                    run_id=run_id,
                    meta=meta,
                )
            retryable = is_retryable(exc) or isinstance(exc, (LLMError, json.JSONDecodeError))
            if attempt >= retries or not retryable:
                raise
            delay = min(1.5 * (2 ** attempt), 45.0) * (1.0 + 0.1 * random.random())
            attempt += 1
            sleep_fn(delay)

    has_wm = bool(parsed.get("has_canary_watermark", False))
    raw_code = str(parsed.get("copy_code_variant", "NONE")).strip().upper()
    decoded_variant = normalize_variant(raw_code) if has_wm or raw_code in VALID_VARIANTS else None
    if raw_code in {"NONE", "NULL", "UNMARKED", "UNWATERMARKED"} or not has_wm:
        if not has_wm and raw_code == "NONE":
            decoded_variant = None
        elif not has_wm:
            decoded_variant = None

    ticks = int(parsed.get("observed_footer_ticks", 0) or 0)
    confidence = round(max(0.0, min(1.0, float(parsed.get("confidence", 0.0) or 0.0))), 4)

    return {
        "variant": decoded_variant,
        "model_response": {
            "observed_doc_id": sanitize_text(str(parsed.get("observed_doc_id", ""))),
            "observed_day_surfaced": int(parsed.get("observed_day_surfaced", 0) or 0),
            "has_canary_watermark": bool(decoded_variant is not None),
            "copy_code_variant": decoded_variant if decoded_variant is not None else "NONE",
            "observed_footer_ticks": max(0, min(8, ticks)),
            "confidence": confidence,
            "visual_evidence": sanitize_text(str(parsed.get("visual_evidence", ""))),
        },
        "usage": {
            "in": int(ledger_row["in"]),
            "out": int(ledger_row["out"]),
            "thinking": int(ledger_row["thinking"]),
            "cached": int(ledger_row["cached"]),
            "cost_usd": float(ledger_row["cost_usd"]),
            "latency_s": float(ledger_row["latency_s"]),
        },
        "model_version": getattr(resp, "model_version", None) or model_id,
        "memo_sha256": img_sha,
    }


class VisualMemoEnv:
    def __init__(
        self,
        env: Any,
        *,
        vision_mode: str = "gemini",
        model_id: str = DEFAULT_MODEL,
        sdk_client: Any = None,
        stub_reader: Callable[[bytes, str], str | None] | dict[str, str | None] | None = None,
        run_id: str = "",
        seed_label: int | None = None,
        out_memos_dir: Path | None = None,
        rel_memos_prefix: str = "memos",
        thinking_level: str | None = None,
        max_retries: int | None = None,
        sleep_fn: Callable[[float], None] = time.sleep,
    ):
        if vision_mode not in VISION_MODES:
            raise ValueError(f"vision_mode must be one of {sorted(VISION_MODES)}, got {vision_mode!r}")
        self._env = env
        self.vision_mode = vision_mode
        self.model_id = model_id
        self.sdk_client = sdk_client
        self._stub_reader = stub_reader
        self.run_id = run_id
        self.seed_label = seed_label if seed_label is not None else getattr(env, "seed", None)
        self.out_memos_dir = Path(out_memos_dir) if out_memos_dir is not None else None
        self.rel_memos_prefix = rel_memos_prefix.strip("/")
        self.thinking_level = thinking_level
        self.max_retries = max_retries
        self.sleep_fn = sleep_fn

        self._history: list[Step] = []
        self._memo_order: list[str] = []
        self._memo_pngs: dict[str, bytes] = {}
        self._memo_meta: dict[str, dict[str, Any]] = {}
        self._expected_variants: dict[str, str | None] = {}
        self._inspected_public: dict[str, dict[str, Any]] = {}
        self._audit_rows: list[dict[str, Any]] = []

    @property
    def tier(self) -> str:
        return self._env.tier

    @property
    def seed(self) -> int:
        return self._env.seed

    @property
    def p(self):
        return self._env.p

    @property
    def done(self) -> bool:
        return self._env.done

    @property
    def history(self) -> list[Step]:
        return self._history

    def tools_spec(self) -> list[dict]:
        return self._env.tools_spec()

    def instruction(self) -> str:
        return self._env.instruction()

    def peek_status(self) -> dict:
        return self._env.peek_status()

    def verdict(self) -> dict:
        return self._env.verdict()

    def score(self) -> float:
        return self._env.score()

    def result(self, agent_name: str) -> EpisodeResult:
        res = self._env.result(agent_name)
        return EpisodeResult(
            tier=res.tier,
            seed=res.seed,
            agent=res.agent,
            steps=list(self._history),
            score=res.score,
            accused=res.accused,
            correct=res.correct,
            final_day=res.final_day,
            end_reason=res.end_reason,
            meta=dict(res.meta),
        )

    def surfaced_memo_ids(self) -> list[str]:
        return list(self._memo_order)

    def memo_png(self, doc_id: str) -> bytes:
        if doc_id not in self._memo_pngs:
            raise KeyError(f"memo scan not surfaced in check_leak_feed: {doc_id}")
        return self._memo_pngs[doc_id]

    def _register_surfaced_item(self, item: dict[str, Any]) -> None:
        pub = extract_public_memo_fields(item)
        doc_id = pub["doc_id"]
        if doc_id in self._memo_pngs:
            return
        png_bytes = render_leak_memo_png(
            doc_id=doc_id,
            day_surfaced=pub["day_surfaced"],
            variant=pub["variant"],
        )
        sha = memo_sha256(png_bytes)
        with Image.open(io.BytesIO(png_bytes)) as im:
            width, height = im.size

        fname = f"seed_{self.seed_label}_{doc_id}.png" if self.seed_label is not None else f"{doc_id}.png"
        rel_path = f"{self.rel_memos_prefix}/{fname}" if self.rel_memos_prefix else fname
        if self.out_memos_dir is not None:
            self.out_memos_dir.mkdir(parents=True, exist_ok=True)
            (self.out_memos_dir / fname).write_bytes(png_bytes)

        self._memo_order.append(doc_id)
        self._memo_pngs[doc_id] = png_bytes
        self._expected_variants[doc_id] = pub["variant"]
        self._memo_meta[doc_id] = {
            "seed": self.seed_label,
            "doc_id": doc_id,
            "day_surfaced": pub["day_surfaced"],
            "path": rel_path,
            "sha256": sha,
            "bytes": len(png_bytes),
            "size": [width, height],
        }

    def call(self, tool: str, args: dict) -> ToolResult:
        step_idx = len(self._history)
        status_before = self._env.peek_status()
        day_before = int(status_before.get("day", 1))
        raw_res = self._env.call(tool, args)

        if tool == "check_leak_feed" and raw_res.ok:
            redacted_items: list[dict[str, Any]] = []
            for item in raw_res.data.get("items", []):
                self._register_surfaced_item(item)
                clean_item = {k: v for k, v in item.items() if k != "variant"}
                redacted_items.append(clean_item)
            public_res = ToolResult(True, {"items": redacted_items}, raw_res.error)
        else:
            public_res = raw_res

        self._history.append(
            Step(
                t=step_idx,
                day=day_before,
                tool=tool if isinstance(tool, str) else repr(tool),
                args=dict(args) if isinstance(args, dict) else {"_raw": repr(args)},
                result=asdict(public_res),
            )
        )
        return public_res

    def inspect_memo(self, doc_id: str) -> dict[str, Any]:
        if doc_id not in self._memo_pngs:
            raise KeyError(f"memo scan not surfaced in check_leak_feed: {doc_id}")
        if doc_id in self._inspected_public:
            return dict(self._inspected_public[doc_id])

        png_bytes = self._memo_pngs[doc_id]
        mmeta = self._memo_meta[doc_id]
        zero_usage = {"in": 0, "out": 0, "thinking": 0, "cached": 0, "cost_usd": 0.0, "latency_s": 0.0}

        if self.vision_mode == "blind":
            decoded_variant = None
            model_resp = {
                "observed_doc_id": doc_id,
                "observed_day_surfaced": mmeta["day_surfaced"],
                "has_canary_watermark": False,
                "copy_code_variant": "NONE",
                "observed_footer_ticks": 0,
                "confidence": 0.0,
                "visual_evidence": "vision disabled in blind ablation mode",
            }
            usage = dict(zero_usage)
            model_ver = "blind"
        elif self.vision_mode == "stub":
            if callable(self._stub_reader):
                raw_val = self._stub_reader(png_bytes, doc_id)
            elif isinstance(self._stub_reader, dict):
                raw_val = self._stub_reader.get(doc_id)
            else:
                raw_val = None
            decoded_variant = normalize_variant(raw_val)
            t_count = (VALID_VARIANTS.index(decoded_variant) + 1) if decoded_variant is not None else 0
            model_resp = {
                "observed_doc_id": doc_id,
                "observed_day_surfaced": mmeta["day_surfaced"],
                "has_canary_watermark": bool(decoded_variant is not None),
                "copy_code_variant": decoded_variant if decoded_variant is not None else "NONE",
                "observed_footer_ticks": t_count,
                "confidence": 1.0 if decoded_variant is not None else 0.99,
                "visual_evidence": f"stub reader output={decoded_variant or 'NONE'}",
            }
            usage = dict(zero_usage)
            model_ver = "stub"
        else:
            vis = inspect_memo_png(
                png_bytes,
                model_id=self.model_id,
                sdk_client=self.sdk_client,
                run_id=self.run_id,
                seed=self.seed_label,
                thinking_level=self.thinking_level,
                max_retries=self.max_retries,
                sleep_fn=self.sleep_fn,
            )
            decoded_variant = vis["variant"]
            model_resp = vis["model_response"]
            usage = vis["usage"]
            model_ver = vis["model_version"]

        public_entry = {
            "seed": self.seed_label,
            "doc_id": doc_id,
            "day_surfaced": mmeta["day_surfaced"],
            "mode": self.vision_mode,
            "variant": decoded_variant,
            "memo_path": mmeta["path"],
            "memo_sha256": mmeta["sha256"],
            "memo_bytes": mmeta["bytes"],
            "memo_size": mmeta["size"],
            "model_version": model_ver,
            "model_response": model_resp,
            "usage": usage,
        }
        expected_var = self._expected_variants[doc_id]
        audit_entry = {
            **public_entry,
            "expected_variant": expected_var,
            "is_canary_memo": expected_var is not None,
            "variant_exact_match": decoded_variant == expected_var,
        }
        self._inspected_public[doc_id] = public_entry
        self._audit_rows.append(audit_entry)
        return dict(public_entry)

    def audit_records(self) -> list[dict[str, Any]]:
        return [dict(r) for r in self._audit_rows]

    def total_vision_usage(self) -> dict[str, Any]:
        tot = {"calls": 0, "in": 0, "out": 0, "thinking": 0, "cached": 0, "cost_usd": 0.0, "latency_s": 0.0}
        for row in self._audit_rows:
            if row["mode"] != "gemini":
                continue
            u = row["usage"]
            tot["calls"] += 1
            tot["in"] += int(u["in"])
            tot["out"] += int(u["out"])
            tot["thinking"] += int(u["thinking"])
            tot["cached"] += int(u["cached"])
            tot["cost_usd"] = round(tot["cost_usd"] + float(u["cost_usd"]), 6)
            tot["latency_s"] = round(tot["latency_s"] + float(u["latency_s"]), 3)
        return tot


class VisionMemoSolverPolicy:
    def __init__(self, visual_env: VisualMemoEnv, solver: SolverPolicy | None = None, name: str | None = None):
        self.visual_env = visual_env
        self.solver = solver if solver is not None else SolverPolicy()
        self.name = name or f"solver_{visual_env.vision_mode}"
        self._augmented_steps: list[Step] = []

    def reset(self, tools_spec: list[dict], instruction: str) -> None:
        self._augmented_steps = []
        self.solver.reset(tools_spec, instruction)

    def max_posterior(self) -> float:
        if not self.solver.post:
            return 0.0
        return round(float(max(self.solver.post.values())), 4)

    def act(self, history: list[Step]) -> tuple[str, dict[str, Any]]:
        if len(history) < len(self._augmented_steps):
            self._augmented_steps = []
        for st in history[len(self._augmented_steps):]:
            if st.tool == "check_leak_feed" and isinstance(st.result, dict) and st.result.get("ok"):
                data = st.result.get("data") or {}
                raw_items = data.get("items") or []
                aug_items: list[dict[str, Any]] = []
                for it in raw_items:
                    entry = {k: v for k, v in it.items() if k != "variant"}
                    vis = self.visual_env.inspect_memo(entry["doc_id"])
                    if vis.get("variant") is not None:
                        entry["variant"] = vis["variant"]
                    aug_items.append(entry)
                new_res = dict(st.result)
                new_res["data"] = {**data, "items": aug_items}
                self._augmented_steps.append(
                    Step(t=st.t, day=st.day, tool=st.tool, args=st.args, result=new_res)
                )
            else:
                self._augmented_steps.append(st)
        return self.solver.act(self._augmented_steps)


def verify_history_variants_redacted(steps: list[Step]) -> bool:
    for st in steps:
        if st.tool != "check_leak_feed":
            continue
        res = st.result or {}
        data = res.get("data") or {}
        for item in data.get("items") or []:
            if "variant" in item and item["variant"] is not None:
                return False
            if "variant" in item:
                return False
    return True


def _episode_summary(ep: EpisodeResult, max_post: float, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    out = {
        "score": round(float(ep.score), 4),
        "correct": bool(ep.correct),
        "accused": ep.accused,
        "final_day": int(ep.final_day),
        "end_reason": ep.end_reason,
        "max_posterior": round(float(max_post), 4),
        "tool_calls": len(ep.steps),
    }
    if extra:
        out.update(extra)
    return out


def run_paired_ablation_seed(
    seed: int,
    *,
    tier: str = "medium",
    model_id: str = DEFAULT_MODEL,
    vision_mode: str = "gemini",
    sdk_client: Any = None,
    stub_reader: Callable[[bytes, str], str | None] | dict[str, str | None] | None = None,
    run_id: str = "",
    out_memos_dir: Path | None = None,
    rel_memos_prefix: str = "memos",
    thinking_level: str | None = None,
    max_retries: int | None = None,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    mm_env = VisualMemoEnv(
        Env(tier, seed),
        vision_mode=vision_mode,
        model_id=model_id,
        sdk_client=sdk_client,
        stub_reader=stub_reader,
        run_id=run_id,
        seed_label=seed,
        out_memos_dir=out_memos_dir,
        rel_memos_prefix=rel_memos_prefix,
        thinking_level=thinking_level,
        max_retries=max_retries,
        sleep_fn=sleep_fn,
    )
    mm_pol = VisionMemoSolverPolicy(mm_env, SolverPolicy(), name="multimodal_carbon")
    mm_ep = run_episode(mm_env, mm_pol)
    mm_redacted = verify_history_variants_redacted(mm_env.history)
    if not mm_redacted:
        raise RuntimeError(f"text check_leak_feed variant redaction failed in multimodal run on seed {seed}")

    blind_env = VisualMemoEnv(
        Env(tier, seed),
        vision_mode="blind",
        model_id=model_id,
        run_id=run_id,
        seed_label=seed,
    )
    blind_pol = VisionMemoSolverPolicy(blind_env, SolverPolicy(), name="blind_no_vision")
    blind_ep = run_episode(blind_env, blind_pol)
    blind_redacted = verify_history_variants_redacted(blind_env.history)
    if not blind_redacted:
        raise RuntimeError(f"text check_leak_feed variant redaction failed in blind run on seed {seed}")

    oracle_env = Env(tier, seed)
    oracle_pol = SolverPolicy()
    oracle_ep = run_episode(oracle_env, oracle_pol)
    oracle_max_post = round(float(max(oracle_pol.post.values())), 4) if oracle_pol.post else 0.0

    audit_rows = mm_env.audit_records()
    canary_rows = [r for r in audit_rows if r["is_canary_memo"]]
    exact_all = sum(1 for r in audit_rows if r["variant_exact_match"])
    exact_canary = sum(1 for r in canary_rows if r["variant_exact_match"])

    return {
        "seed": seed,
        "tier": tier,
        "tiers_version": TIERS_VERSION,
        "multimodal_carbon": _episode_summary(
            mm_ep,
            mm_pol.max_posterior(),
            {
                "text_feed_variants_redacted": mm_redacted,
                "n_memos_inspected": len(audit_rows),
                "n_canary_memos_inspected": len(canary_rows),
                "vision_exact_matches": exact_all,
                "canary_vision_exact_matches": exact_canary,
            },
        ),
        "blind_no_vision": _episode_summary(
            blind_ep,
            blind_pol.max_posterior(),
            {
                "text_feed_variants_redacted": blind_redacted,
                "n_memos_inspected": len(blind_env.audit_records()),
            },
        ),
        "text_oracle": _episode_summary(oracle_ep, oracle_max_post),
        "vision_calls": audit_rows,
        "usage": mm_env.total_vision_usage(),
    }
