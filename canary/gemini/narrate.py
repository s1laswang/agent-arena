"""Gemini TTS narration for the Canary Lab demo video.

    python -m canary.gemini.narrate [--video docs/gemini/VIDEO.md] [--out docs/gemini/assets/narration]
                                    [--voice Kore] [--voices Kore,Charon,Puck] [--only 01-hook,02-ladder]
                                    [--model gemini-3.8-flash-tts] [--dry-run] [--allow-pending]

Reads every `> VO[<id>]: <text>` line of VIDEO.md, fills `{placeholders}` from results/gemini/*.json and the ledger summary
(the same numbers the dashboard shows), then makes one Gemini TTS call per clip and writes `<out>/<id>.wav` (24 kHz mono PCM)
plus `<out>/index.json` (id, voice, words, seconds, text). `--voices` writes `<id>.<voice>.wav` auditions instead.
Every TTS call is logged to the ledger: record(feature="narrate", kind="tts", ...).
An unresolved placeholder stops the run (so the video never quotes a number we can't back) unless --allow-pending.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import wave
from pathlib import Path
from typing import Any

from canary.gemini import dashboard as dash
from canary.gemini.ledger import record

ROOT = dash.ROOT
VO_RE = re.compile(r"^>\s*VO\[(?P<id>[\w.-]+)\]:\s*(?P<text>.+?)\s*$", re.M)
PH_RE = re.compile(r"\{(\w+)\}")
DEFAULT_MODEL = "gemini-3.8-flash-tts"
DEFAULT_VOICE = "Kore"
# gemini-3.8-flash-tts reads style prefixes aloud ("Say in a ... voice: ") for most voices and rejects system_instruction
# (probed Sat 14:45), so the default is no prefix: the voice choice carries the style.
STYLE = ""
QA_MODEL = "gemini-3.8-flash"
WPM = 150


# ------------------------------------------------------------- spoken formatting
def say_model(m: str) -> str:
    s = str(m).replace("gemini-", "Gemini ").replace("-", " ")
    return " ".join(w.capitalize() if w.isalpha() else w for w in s.split())


def say_pct(x: float) -> str:
    return f"{round(x * 100)} percent"


def say_tokens(n: float) -> str:
    n = float(n)
    if n >= 1e9:
        return f"{n / 1e9:.1f}".rstrip("0").rstrip(".") + " billion"
    if n >= 1e6:
        return f"{n / 1e6:.1f}".rstrip("0").rstrip(".") + " million"
    if n >= 1e4:
        return f"{round(n / 1e3)} thousand"
    return f"{int(n):,}"


def say_score(x: float) -> str:
    return ("minus " if x < 0 else "") + f"{abs(x):.2f}"


# ------------------------------------------------------------- placeholder values
def cell_values(cells: list[dict], prefix: str, model: str, level: str, tier: str) -> dict[str, str]:
    """One named ladder cell, spoken with its n, paired CI and cost. The model is named as the API served it when that
    differs from what we requested (gemini-3.5-flash is served as gemini-3.6-flash). Cells under FRONTIER_MIN_N are skipped."""
    c = next((c for c in cells if c["model"] == model and c["level"] == level and c["tier"] == tier), None)
    if not c or int(c.get("n") or 0) < FRONTIER_MIN_N or c.get("ratio_lo") is None or c.get("ratio_hi") is None:
        return {}
    served = [m for m in (c.get("model_versions") or []) if m]
    name = served[0] if len(served) == 1 else model
    cost = c.get("cost_usd_per_episode")
    out = {f"{prefix}_model": say_model(name), f"{prefix}_level": level, f"{prefix}_n": str(int(c["n"])),
           f"{prefix}_pct": say_pct(c["pct_solver"]), f"{prefix}_ci": f"{say_pct(c['ratio_lo'])} to {say_pct(c['ratio_hi'])}"}
    if cost:
        out[f"{prefix}_cost"] = f"{cost:.2f} dollars"
        out[f"{prefix}_cost_raw"] = f"{cost}"
    return out


def usage_summary(results_dir: Path, ledger: list) -> dict | None:
    """The dashboard's usage summary: same ledger sources, same repricing (ladder.json prices), same summarize()."""
    if list(ledger) == ["committed"]:
        ledger = dash.committed_ledgers(results_dir)
    elif list(ledger) == ["auto"]:
        ledger = dash.discover_ledgers()
    rows = dash.load_ledger(ledger)
    if not rows:
        return None
    lad = dash.load_json(Path(results_dir) / "ladder.json") or {}
    dash.reprice(rows, lad.get("prices_usd_per_1m") if isinstance(lad.get("prices_usd_per_1m"), dict) else None)
    return dash.summarize(rows)


def say_usd(x: float) -> str:
    return f"{round(float(x))} dollars"


FRONTIER_MIN_N = 8  # a spoken ladder claim needs at least this many paired episodes in the cell


def frontier_values(cells: list[dict], tier: str) -> dict[str, str]:
    """The best-scoring ladder cell with n >= FRONTIER_MIN_N on `tier`, with its CI, against the cost per episode of
    gemini-4-carbon's largest-n cell on the same tier. Small-n cells are never spoken."""
    big = [c for c in cells if c["tier"] == tier and int(c.get("n") or 0) >= FRONTIER_MIN_N
           and (c.get("cost_usd_per_episode") or 0) > 0 and c["model"] != "gemini-4-carbon"]
    ref = [c for c in cells if c["tier"] == tier and c["model"] == "gemini-4-carbon" and (c.get("cost_usd_per_episode") or 0) > 0]
    if not big or not ref:
        return {}
    f = max(big, key=lambda c: c["pct_solver"])
    r = max(ref, key=lambda c: int(c.get("n") or 0))
    served = [m for m in (f.get("model_versions") or []) if m and m != f["model"]]
    out = {"frontier_model": say_model(f["model"]) + (f", served as {say_model(served[0])}," if len(served) == 1 else ""),
           "frontier_level": str(f["level"]), "frontier_tier": tier, "frontier_n": str(int(f["n"])),
           "frontier_pct": say_pct(f["pct_solver"]),
           "frontier_cost_share": say_pct(f["cost_usd_per_episode"] / r["cost_usd_per_episode"]),
           "frontier_ref": say_model(r["model"]) + (f" at {r['level']}" if r.get("level") not in (None, "", "default") else " at its default"),
           "frontier_ref_n": str(int(r.get("n") or 0))}
    if f.get("ratio_lo") is not None and f.get("ratio_hi") is not None:
        out["frontier_ci"] = f"{say_pct(f['ratio_lo'])} to {say_pct(f['ratio_hi'])}"
    return out


def values(results_dir: Path, ledger: list) -> dict[str, str]:
    v: dict[str, str] = {}
    s = usage_summary(results_dir, ledger)
    if s:
        t = s["totals"]
        v.update(calls=f"{t['calls']:,}", tokens=say_tokens(t["tokens"]), thinking=say_tokens(t["thinking"]),
                 cache_share=say_pct(s["cache"]["hit_share"]), models=str(t["n_models"]), features=str(t["n_features"]),
                 cost=say_usd(t["cost_usd"]))
    R = dash.load_results(results_dir)
    L = R.get("ladder")
    if L and (L.get("rows") or L.get("cells")):
        cells = []
        for c in L.get("rows") or L.get("cells"):  # G2 rows (ratio, cost_per_ep) or the older cells shape
            c = dict(c)
            pct = c.get("ratio", c.get("pct_solver"))
            if pct is None and c.get("score_mean") is not None and c.get("solver_mean"):
                pct = c["score_mean"] / c["solver_mean"]
            if pct is None:
                continue
            c["pct_solver"] = pct
            c.setdefault("level", c.get("thinking_level", ""))
            c["cost_usd_per_episode"] = c.get("cost_per_ep", c.get("cost_usd_per_episode", c.get("cost_per_episode")))
            cells.append(c)
        if cells:
            v["ladder_models"] = str(len({c["model"] for c in cells}))
            v["ladder_levels"] = str(len({c["level"] for c in cells}))
            v["ladder_episodes"] = f"{sum(int(c.get('n') or c.get('episodes') or 0) for c in cells):,}"
            tiers = {c["tier"] for c in cells}
            tier = "hard" if "hard" in tiers else sorted(tiers)[0]
            carb = [c for c in cells if c["model"] == "gemini-4-carbon" and c["tier"] == "hard"]
            if carb:
                hi = [c for c in carb if c["level"] == "high"] or carb
                v["carbon_hard_pct"] = say_pct(max(c["pct_solver"] for c in hi))
            tc = [c for c in cells if c["tier"] == tier and (c.get("cost_usd_per_episode") or 0) > 0]
            if tc:
                best = max(tc, key=lambda c: c["pct_solver"])
                cheaper = [c for c in tc if c["cost_usd_per_episode"] < best["cost_usd_per_episode"]
                           and c["pct_solver"] >= 0.8 * best["pct_solver"]]
                if cheaper and best["pct_solver"] > 0:
                    val = min(cheaper, key=lambda c: c["cost_usd_per_episode"])
                    v.update(value_model=say_model(val["model"]), value_level=str(val["level"]),
                             value_pct_of_best=say_pct(val["pct_solver"] / best["pct_solver"]),
                             value_cost_share=say_pct(val["cost_usd_per_episode"] / best["cost_usd_per_episode"]),
                             best_model=say_model(best["model"]), best_level=str(best["level"]))
            v.update(frontier_values(cells, tier))
            v.update(cell_values(cells, "lead", "gemini-4-carbon", "high", tier))
            v.update(cell_values(cells, "cheap", "gemini-3.5-flash", "high", tier))
            if "lead_cost_raw" in v and "cheap_cost_raw" in v and float(v["cheap_cost_raw"]) > 0:
                v["cheap_times"] = f"{float(v['lead_cost_raw']) / float(v['cheap_cost_raw']):.1f}"
    A = R.get("atlas")
    if A and A.get("modes"):
        C = A.get("corpus") or {}
        if C.get("episodes") is not None:
            v["atlas_episodes"] = f"{int(C['episodes']):,}"
        if C.get("tokens") is not None:
            v["atlas_tokens"] = say_tokens(C["tokens"])
        modes = sorted(A["modes"], key=lambda m: -(m.get("regret_share") or 0))
        for i, m in enumerate(modes[:3], 1):
            v[f"mode{i}"] = str(m.get("name") or m.get("id"))
            v[f"mode{i}_share"] = say_pct(m.get("regret_share") or 0)
        ha = A.get("human_agreement")
        rate = ha if isinstance(ha, (int, float)) else (ha or {}).get("rate") if isinstance(ha, dict) else None
        if isinstance(ha, dict) and rate is None and ha.get("total"):
            rate = ha["agree"] / ha["total"]
        if rate is not None:
            v["agreement"] = say_pct(rate)
    B = dash.slim_atlas_blind(dash.load_json(results_dir / "atlas_blind.json"))
    if B:
        v["blind_recovered"] = str(B["tags_recovered"])
        if B.get("n_tags") is not None:
            v["blind_tags"] = str(B["n_tags"])
        v["blind_new"] = str(len(B.get("novel") or []))
        if B.get("regret_share_covered") is not None:
            v["blind_regret_covered"] = say_pct(B["regret_share_covered"])
        if B.get("episodes") is not None:
            v["blind_episodes"] = f"{int(B['episodes']):,}"
    S = R.get("swarm")
    if S and S.get("attempts"):
        at = S["attempts"]
        v["attackers"] = str(S.get("attackers") or len(at))
        v["personas"] = str(len({a.get("persona") for a in at}))
        b = S.get("best_non_solver")
        b = b.get("score") if isinstance(b, dict) else b
        if b is None:
            b = max(a["score"] for a in at if a.get("ledger_verified"))
        v["best_non_solver"] = say_score(float(b))
        sol = S.get("solver_score", S.get("solver"))
        if sol is not None:
            v["solver_score"] = say_score(float(sol))
        ex = sum(1 for a in at if a.get("exploit") and a.get("ledger_verified"))
        tw = S.get("tests_written")
        tw = tw if tw is not None else sum(1 for f in S.get("findings") or [] if f.get("test"))
        if ex == 0:
            v["exploit_sentence"] = ("None of them beat the reward." if not tw else
                                     f"None of them beat the reward, and {tw} of their findings " + ("is" if tw == 1 else "are") + " now regression tests.")
        else:
            v["exploit_sentence"] = (f"{ex} found a real exploit." +
                                     (f" Each one is now a regression test." if tw and tw >= ex else ""))
        # the dashboard's reading (slim_swarm): best score the evidence can't justify, skipping flags overturned on review
        if S.get("best_unjustified") is not None:
            v["swarm_best_unjustified"] = say_score(float(S["best_unjustified"]))
            v["swarm_best_tier"] = str(S.get("best_unjustified_tier") or "")
            if S.get("best_unjustified_solver") is not None:
                v["swarm_best_solver"] = say_score(float(S["best_unjustified_solver"]))
        pc = S.get("positive_control") or {}
        if pc.get("attempts"):
            v["pc_found"], v["pc_attempts"] = str(pc.get("attackers_found")), str(pc["attempts"])
    return v


def script(video: Path, vals: dict[str, str], allow_pending: bool = False) -> list[dict]:
    clips, missing = [], set()
    for m in VO_RE.finditer(video.read_text()):
        text = m.group("text")

        def sub(mm, _missing=missing):
            k = mm.group(1)
            if k in vals:
                return vals[k]
            _missing.add(k)
            return "pending"
        text = PH_RE.sub(sub, text)
        words = len(text.split())
        clips.append({"id": m.group("id"), "text": text, "words": words, "est_s": round(words / WPM * 60, 1)})
    if missing and not allow_pending:
        raise SystemExit(f"unresolved placeholders (results not in yet?): {', '.join(sorted(missing))}. "
                         "Use --allow-pending for a draft.")
    return clips


# ------------------------------------------------------------- TTS
def _client():
    from google import genai
    from google.genai import types

    from canary.llm.base import load_env
    load_env()
    # The SDK default API version rejects speech_config for the 3.8 TTS models (400 "Unknown name speechConfig");
    # v1beta accepts it (probed Sat 14:40).
    kw: dict[str, Any] = {"http_options": types.HttpOptions(api_version="v1beta")}
    try:  # route through the Canary Lab gateway when configured (G1)
        from canary.gemini.gateway import gateway_http_options  # type: ignore
        ho = gateway_http_options()
        if ho:
            kw["http_options"] = types.HttpOptions(**{"api_version": "v1beta", **ho}) if isinstance(ho, dict) else ho
    except Exception:  # noqa: BLE001
        pass
    return genai.Client(**kw), types


def _rate(mime: str) -> int:
    m = re.search(r"rate=(\d+)", mime or "")
    return int(m.group(1)) if m else 24000


def tts(client, types, text: str, voice: str, model: str, style: str = STYLE, run_id: str = "") -> tuple[bytes, int]:
    cfg = types.GenerateContentConfig(
        response_modalities=["AUDIO"],
        speech_config=types.SpeechConfig(voice_config=types.VoiceConfig(
            prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=voice))))
    t0 = time.time()
    last = None
    for attempt in range(4):
        try:
            r = client.models.generate_content(model=model, contents=style + text, config=cfg)
            part = r.candidates[0].content.parts[0]
            pcm, mime = part.inline_data.data, part.inline_data.mime_type
            record("narrate", model, kind="tts", usage=r.usage_metadata, latency_s=time.time() - t0, run_id=run_id,
                   meta={"voice": voice, "chars": len(text)})
            return pcm, (0 if "wav" in (mime or "") else _rate(mime))
        except Exception as e:  # noqa: BLE001
            last = e
            record("narrate", model, kind="tts", latency_s=time.time() - t0, ok=False,
                   error=f"{type(e).__name__}: {e}", run_id=run_id, meta={"voice": voice})
            if re.search(r"\b4(?!29)\d\d\b", str(e)):  # client error other than 429: retrying won't help
                break
            time.sleep(2 ** attempt)
    raise RuntimeError(f"TTS failed after retries: {type(last).__name__}")


def _words(s: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", s.lower().replace("-", " "))


def qa(client, types, wav: bytes, text: str, run_id: str = "") -> dict:
    """Gemini listens to the clip: verbatim transcript + word recall/precision against the script."""
    t0 = time.time()
    r = client.models.generate_content(
        model=QA_MODEL, contents=[types.Part.from_bytes(data=wav, mime_type="audio/wav"),
                                  "Transcribe this narration verbatim. Output only the transcript."],
        config=types.GenerateContentConfig(thinking_config=types.ThinkingConfig(thinking_level="LOW")))
    record("narrate", QA_MODEL, usage=r.usage_metadata, latency_s=time.time() - t0, run_id=run_id, meta={"qa": "transcribe"})
    heard, want = _words(r.text or ""), _words(text)
    hs, ws = set(heard), set(want)
    return {"transcript": (r.text or "").strip(), "recall": round(len(ws & hs) / max(1, len(ws)), 3),
            "extra_words": len(heard) - len(want)}


def write_wav(path: Path, pcm: bytes, rate: int) -> float:
    """Write a WAV; rate=0 means `pcm` is already a WAV file (the API returns audio/wav for 3.8 TTS)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if rate == 0:
        path.write_bytes(pcm)
        with wave.open(str(path)) as w:
            return w.getnframes() / w.getframerate()
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm)
    return len(pcm) / 2 / rate


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--video", default=str(ROOT / "docs" / "gemini" / "VIDEO.md"))
    ap.add_argument("--out", default=str(ROOT / "docs" / "gemini" / "assets" / "narration"))
    ap.add_argument("--results", default=str(dash.DEFAULT_RESULTS))
    ap.add_argument("--ledger", nargs="*", default=["committed"],
                    help="ledger files/dirs, or 'committed' (default: results/gemini ledgers only) or 'auto'")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--voice", default=DEFAULT_VOICE)
    ap.add_argument("--voices", default="", help="comma list: audition voices, writes <id>.<voice>.wav")
    ap.add_argument("--only", default="", help="comma list of clip ids")
    ap.add_argument("--style", default=STYLE, help="style prefix ( for none)")
    ap.add_argument("--check", action="store_true", help="Gemini transcribes each clip and checks it against the script")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--allow-pending", action="store_true")
    a = ap.parse_args(argv)
    clips = script(Path(a.video), values(Path(a.results), a.ledger), a.allow_pending)
    if a.only:
        keep = set(a.only.split(","))
        clips = [c for c in clips if c["id"] in keep]
    if a.dry_run:
        for c in clips:
            print(f"[{c['id']}] {c['words']} words ~{c['est_s']} s\n  {c['text']}\n")
        print(f"total {sum(c['words'] for c in clips)} words ~{sum(c['est_s'] for c in clips):.0f} s")
        return 0
    client, types = _client()
    out = Path(a.out)
    voices = [v for v in a.voices.split(",") if v] or [a.voice]
    index_path = out / "index.json"
    index = json.loads(index_path.read_text()) if index_path.exists() else {}
    run_id = f"narrate-{int(time.time())}"
    for c in clips:
        for v in voices:
            pcm, rate = tts(client, types, c["text"], v, a.model, style=a.style, run_id=run_id)
            name = f"{c['id']}.wav" if not a.voices else f"{c['id']}.{v}.wav"
            secs = write_wav(out / name, pcm, rate)
            q = qa(client, types, (out / name).read_bytes(), c["text"], run_id) if a.check else {}
            flag = f"  recall {q['recall']:.0%} extra {q['extra_words']:+d}" if q else ""
            print(f"{out / name}  {secs:.1f} s  ({c['words']} words, voice {v}){flag}", flush=True)
            if not a.voices:
                index[c["id"]] = {"file": name, "voice": v, "model": a.model, "seconds": round(secs, 2),
                                  "words": c["words"], "text": c["text"], **({"qa": q} if q else {})}
    if not a.voices:
        index_path.write_text(json.dumps(index, indent=1, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
