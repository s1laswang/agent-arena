from __future__ import annotations

import argparse
import concurrent.futures
import gzip
import json
import os
import re
import subprocess
from collections import defaultdict
from pathlib import Path
from typing import Any

from canary.analysis.tags import WHY, to_result
from canary.gemini.ladder_report import (
    LEVEL_ORDER,
    MODEL_ORDER,
    PRICES,
    SERVED_AS,
    TIERS,
    load_import,
    load_ladder,
    price,
    reference_episodes,
)
from canary.solver.regret import attribute
from canary.world import HELDOUT_SEEDS, JUDGE_SEEDS

ROOT = Path(__file__).resolve().parents[2]
HIGHLIGHT_TAGS = (
    "premature_accusation",
    "uninformative_canary",
    "ignored_delay",
    "over_restriction",
)
UNICODE_DASHES = "".join(chr(c) for c in (0x2012, 0x2013, 0x2014, 0x2015))
OWN_PATHS = (
    "canary/gemini/outthink_annotations.py",
    "results/gemini/outthink_annotations.json",
    "demo/out-think-gemini/annotations.js",
)


def _clean_prose(text: str | None) -> str:
    if not text:
        return ""
    out = str(text)
    for ch in UNICODE_DASHES:
        out = out.replace(ch, " - ")
    return re.sub(r"\s+", " ", out).strip()


def _has_unicode_dash(text: str) -> bool:
    return any(ch in text for ch in UNICODE_DASHES)


def _model_short(model: str) -> str:
    m = model.lower().replace("gemini-", "g").replace("gpt-", "gpt")
    return re.sub(r"[^a-z0-9.]+", "", m)[:14]


def _atlas_episode_id(model: str, level: str, tier: str, seed: int) -> str:
    lv = "" if level == "default" else f"-{level}"
    return f"{_model_short(model)}{lv}.in.v14.{tier[0]}{seed}"


def _parse_atlas_episode_id(ep_id: str) -> tuple[str, str, str, int] | None:
    m = re.match(r"^([a-z0-9.]+?)(?:-([a-z]+))?\.in\.v14\.([mh])(\d+)$", ep_id or "")
    if not m:
        return None
    short, lv, t_char, seed_s = m.groups()
    short_map = {_model_short(mod): mod for mod in MODEL_ORDER}
    model = short_map.get(short)
    if not model:
        return None
    level = lv or "default"
    tier = "medium" if t_char == "m" else "hard"
    return (model, level, tier, int(seed_s))


def _read_raw_source(rel_path: str, cache: dict[str, str]) -> str:
    if rel_path not in cache:
        full = ROOT / rel_path
        if rel_path.endswith(".gz"):
            with gzip.open(full, "rt", encoding="utf-8") as fh:
                cache[rel_path] = fh.read()
        else:
            cache[rel_path] = full.read_text(encoding="utf-8")
    return cache[rel_path]


def _best_verbatim_span(
    candidate: str,
    raw_source: str,
    extra_haystack: str | None = None,
    min_len: int = 12,
    max_len: int = 240,
) -> str | None:
    if not candidate:
        return None
    trimmed = candidate
    for suffix in (" [...]", "[...]"):
        if trimmed.endswith(suffix):
            trimmed = trimmed[: -len(suffix)]
    sep_pattern = "[" + re.escape(UNICODE_DASHES) + r"\r\n]+"
    raw_chunks = [c.strip() for c in re.split(sep_pattern, trimmed) if c.strip()]
    candidates_out: list[str] = []
    for chunk in raw_chunks:
        sub_chunks = [chunk]
        if chunk not in raw_source or (extra_haystack is not None and chunk not in extra_haystack):
            sub_chunks = [
                s.strip()
                for s in re.split(r'["\\]+', chunk)
                if s.strip()
            ]
        for sub in sub_chunks:
            cur = sub
            if len(cur) > max_len:
                cut = cur[:max_len]
                if " " in cut[min_len:]:
                    cut = cut.rsplit(" ", 1)[0]
                cur = cut.strip()
            if len(cur) < min_len:
                continue
            if _has_unicode_dash(cur):
                continue
            if cur in candidate and cur in raw_source:
                if extra_haystack is None or cur in extra_haystack:
                    candidates_out.append(cur)
    if not candidates_out:
        return None
    candidates_out.sort(key=lambda s: (-len(s), candidate.find(s)))
    best = candidates_out[0]
    assert best in raw_source
    assert best in candidate
    assert not _has_unicode_dash(best)
    if extra_haystack is not None:
        assert best in extra_haystack
    return best


def _emit_quote(
    dest: list[dict[str, Any]],
    seen: set[tuple[str, str]],
    quote: str,
    raw_source: str,
    source_file: str,
    source_kind: str,
    t: int | None = None,
    day: int | None = None,
    tool: str | None = None,
    mode: str | None = None,
    note: str | None = None,
) -> None:
    assert quote, f"empty quote for {source_file}"
    assert quote in raw_source, f"quote not verbatim in {source_file}: {quote!r}"
    assert not _has_unicode_dash(quote), f"unicode dash in quote: {quote!r}"
    dedup_key = (source_file, quote)
    if dedup_key in seen:
        return
    seen.add(dedup_key)
    item: dict[str, Any] = {
        "quote": quote,
        "source_kind": source_kind,
        "source_file": source_file,
    }
    if t is not None:
        item["t"] = int(t)
    if day is not None:
        item["day"] = int(day)
    if tool:
        item["tool"] = str(tool)
    if mode:
        item["mode"] = _clean_prose(mode)
    if note:
        item["note"] = _clean_prose(note)
    dest.append(item)


def _git_input_sha() -> str:
    excl = [f":!{p}" for p in OWN_PATHS]
    out = subprocess.check_output(
        ["git", "log", "-1", "--format=%H", "--", ".", *excl],
        cwd=ROOT,
        text=True,
    ).strip()
    if out:
        return out
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        text=True,
    ).strip()


def _load_ledger_index() -> dict[str, list[dict[str, Any]]]:
    by_run: dict[str, list[dict[str, Any]]] = defaultdict(list)
    seen_rows: set[tuple[Any, ...]] = set()
    for rel in (
        "results/gemini/ladder_ledger.jsonl.gz",
        "results/gemini/scale/ladder30/ladder_ledger.jsonl.gz",
    ):
        fp = ROOT / rel
        if not fp.exists():
            continue
        with gzip.open(fp, "rt", encoding="utf-8") as fh:
            for line in fh:
                if not line.strip():
                    continue
                r = json.loads(line)
                if r.get("feature") != "ladder":
                    continue
                sig = (
                    r.get("run_id"),
                    r.get("ts"),
                    r.get("in"),
                    r.get("out"),
                    r.get("thinking"),
                    r.get("cached"),
                    r.get("ok"),
                )
                if sig in seen_rows:
                    continue
                seen_rows.add(sig)
                rid = r.get("run_id")
                if rid:
                    by_run[rid].append(r)
    return by_run


def _load_all_episodes(
    raw_cache: dict[str, str],
) -> tuple[dict[tuple[str, str, str, int], dict[str, Any]], dict[str, Any]]:
    ladder_json_path = ROOT / "results" / "gemini" / "ladder.json"
    ladder_doc = json.loads(ladder_json_path.read_text(encoding="utf-8"))

    primary_rel = "results/gemini/ladder_episodes.jsonl.gz"
    scale30_rel = "results/gemini/scale/ladder30/ladder_episodes.jsonl.gz"

    scale30_cells: set[tuple[str, str, str, int]] = set()
    scale30_lines: list[tuple[tuple[str, str, str, int], str, dict[str, Any]]] = []
    if (ROOT / scale30_rel).exists():
        raw30 = _read_raw_source(scale30_rel, raw_cache)
        for line in raw30.splitlines():
            if not line.strip():
                continue
            ep = json.loads(line)
            if (ep.get("meta") or {}).get("valid") is False or ep.get("end_reason") == "error":
                continue
            lad = (ep.get("meta") or {}).get("ladder") or {}
            cell = (lad["model"], lad["level"], lad["tier"], int(lad["seed"]))
            scale30_cells.add(cell)
            scale30_lines.append((cell, line, ep))

    records: dict[tuple[str, str, str, int], dict[str, Any]] = {}
    raw_primary = _read_raw_source(primary_rel, raw_cache)
    for line in raw_primary.splitlines():
        if not line.strip():
            continue
        ep = json.loads(line)
        if (ep.get("meta") or {}).get("valid") is False or ep.get("end_reason") == "error":
            continue
        lad = (ep.get("meta") or {}).get("ladder") or {}
        cell = (lad["model"], lad["level"], lad["tier"], int(lad["seed"]))
        if cell not in records:
            records[cell] = {
                "ep": ep,
                "raw_line": line,
                "source_file": primary_rel,
                "dataset": "ladder",
                "in_ladder30": cell in scale30_cells,
            }

    for cell, line, ep in scale30_lines:
        if cell not in records:
            records[cell] = {
                "ep": ep,
                "raw_line": line,
                "source_file": scale30_rel,
                "dataset": "ladder30",
                "in_ladder30": True,
            }

    default_seeds_by_tier = {
        r["tier"]: set(int(s) for s in r.get("seeds") or [])
        for r in ladder_doc.get("rows") or []
        if r.get("model") == "gemini-4-carbon" and r.get("level") == "default"
    }
    inproc_dir = ROOT / "data" / "runs" / "committed" / "v1.4" / "inproc-gemini-4-carbon"
    if inproc_dir.exists() and default_seeds_by_tier:
        for tier in TIERS:
            ep_file = inproc_dir / tier / "episodes.jsonl"
            if not ep_file.exists():
                continue
            rel_ep = str(ep_file.relative_to(ROOT))
            raw_imp = _read_raw_source(rel_ep, raw_cache)
            wanted = default_seeds_by_tier.get(tier, set())
            for line in raw_imp.splitlines():
                if not line.strip():
                    continue
                ep = json.loads(line)
                if ep.get("end_reason") == "error" or ep.get("tier") != tier:
                    continue
                seed_i = int(ep["seed"])
                if seed_i not in wanted:
                    continue
                cell = ("gemini-4-carbon", "default", tier, seed_i)
                if cell not in records:
                    records[cell] = {
                        "ep": ep,
                        "raw_line": line,
                        "source_file": rel_ep,
                        "dataset": "ladder_import",
                        "in_ladder30": False,
                    }

    for _, _, _, seed_i in records:
        assert seed_i not in JUDGE_SEEDS and seed_i not in HELDOUT_SEEDS

    return records, ladder_doc


def _attribute_worker(ep: dict[str, Any]) -> list[dict[str, Any]]:
    return attribute(to_result(ep)) or []


def _compute_regret_map(
    records: dict[tuple[str, str, str, int], dict[str, Any]],
) -> dict[tuple[str, str, str, int], list[dict[str, Any]]]:
    ordered_keys = sorted(records.keys())
    eps_list = [records[k]["ep"] for k in ordered_keys]
    workers = min(8, max(1, os.cpu_count() or 4))
    with concurrent.futures.ProcessPoolExecutor(max_workers=workers) as ex:
        results = list(ex.map(_attribute_worker, eps_list, chunksize=8))
    return dict(zip(ordered_keys, results))


def _collect_atlas_annotations(
    rel_path: str,
    source_kind: str,
    raw_cache: dict[str, str],
) -> tuple[
    dict[tuple[str, str, str, int], list[dict[str, Any]]],
    dict[tuple[str, str, str, int], list[dict[str, Any]]],
]:
    quotes_by_cell: dict[tuple[str, str, str, int], list[dict[str, Any]]] = defaultdict(list)
    cf_by_cell: dict[tuple[str, str, str, int], list[dict[str, Any]]] = defaultdict(list)
    seen_by_cell: dict[tuple[str, str, str, int], set[tuple[str, str]]] = defaultdict(set)

    fp = ROOT / rel_path
    if not fp.exists():
        return quotes_by_cell, cf_by_cell

    raw_text = _read_raw_source(rel_path, raw_cache)
    doc = json.loads(raw_text)

    for mode in doc.get("modes") or []:
        mode_id = mode.get("id") or ""
        for qobj in (mode.get("quotes") or []) + (mode.get("examples") or []):
            cell = _parse_atlas_episode_id(qobj.get("episode") or "")
            if not cell:
                continue
            q_raw = qobj.get("quote") or ""
            span = _best_verbatim_span(q_raw, raw_text, min_len=14, max_len=240)
            if span:
                _emit_quote(
                    quotes_by_cell[cell],
                    seen_by_cell[cell],
                    span,
                    raw_text,
                    rel_path,
                    source_kind,
                    t=qobj.get("t"),
                    mode=mode_id,
                    note=qobj.get("why") or mode.get("name"),
                )

    for lbl in (doc.get("labels") or {}).get("steps") or []:
        cell = _parse_atlas_episode_id(lbl.get("episode") or "")
        if not cell:
            continue
        q_raw = lbl.get("quote") or ""
        span = _best_verbatim_span(q_raw, raw_text, min_len=14, max_len=240)
        if span:
            _emit_quote(
                quotes_by_cell[cell],
                seen_by_cell[cell],
                span,
                raw_text,
                rel_path,
                source_kind,
                t=lbl.get("t"),
                mode=lbl.get("mode"),
                note=lbl.get("explanation"),
            )

    for cf in doc.get("counterfactuals") or []:
        cell = _parse_atlas_episode_id(cf.get("episode") or "")
        if not cell:
            continue
        cf_by_cell[cell].append(
            {
                "source_file": rel_path,
                "t": cf.get("t"),
                "agent_did": _clean_prose(cf.get("agent_did")),
                "solver_would": _clean_prose(cf.get("solver_would")),
                "why_diverged": _clean_prose(cf.get("why_diverged")),
            }
        )

    for loc in (doc.get("localisation") or {}).get("rows") or []:
        cell = _parse_atlas_episode_id(loc.get("episode") or "")
        if not cell:
            continue
        cf_by_cell[cell].append(
            {
                "source_file": rel_path,
                "t": loc.get("code_t"),
                "gemini_t": loc.get("gemini_t"),
                "what_chart_shows": _clean_prose(loc.get("what_chart_shows")),
                "what_agent_believed": _clean_prose(loc.get("what_agent_believed")),
            }
        )

    return quotes_by_cell, cf_by_cell


def _collect_validation_context(
    raw_cache: dict[str, str],
) -> dict[tuple[str, str, str, int], list[dict[str, Any]]]:
    rel_path = "docs/gemini/validation_context.md"
    quotes_by_cell: dict[tuple[str, str, str, int], list[dict[str, Any]]] = defaultdict(list)
    seen_by_cell: dict[tuple[str, str, str, int], set[tuple[str, str]]] = defaultdict(set)
    if not (ROOT / rel_path).exists():
        return quotes_by_cell

    raw_text = _read_raw_source(rel_path, raw_cache)
    sections = re.split(r"(?m)^##\s+\d+\.\s+", raw_text)
    for sec in sections[1:]:
        lines = sec.splitlines()
        if not lines:
            continue
        m_head = re.match(r"^(\S+)\s+t=(\d+)\s+\(([^)]+)\)", lines[0].strip())
        if not m_head:
            continue
        ep_id, t_str, kind = m_head.groups()
        cell = _parse_atlas_episode_id(ep_id)
        if not cell:
            continue
        target_t = int(t_str)
        claim = ""
        for ln in lines[1:6]:
            if ln.startswith("**Claim:**"):
                claim = ln.replace("**Claim:**", "", 1).strip()
                break
        current_t: int | None = None
        preferred: list[tuple[int, int | None, str]] = []
        for ln in lines:
            mt = re.match(r"^(?:>>>\s+)?t(\d+)\s+d(\d+)\s+([a-z_]+)\(", ln)
            if mt:
                current_t = int(mt.group(1))
                if ln.startswith(">>> "):
                    preferred.append((1, current_t, ln))
            elif ln.startswith("   says: "):
                body = ln[len("   says: ") :]
                prio = 0 if current_t == target_t else 2
                preferred.append((prio, current_t, body))
        preferred.sort(key=lambda x: x[0])
        for _, st_t, cand in preferred[:4]:
            span = _best_verbatim_span(cand, raw_text, min_len=16, max_len=240)
            if span:
                _emit_quote(
                    quotes_by_cell[cell],
                    seen_by_cell[cell],
                    span,
                    raw_text,
                    rel_path,
                    "validation_context",
                    t=st_t if st_t is not None else target_t,
                    mode=kind,
                    note=claim,
                )
    return quotes_by_cell


def _collect_replay_showcase(
    raw_cache: dict[str, str],
) -> dict[tuple[str, str, str, int], list[dict[str, Any]]]:
    quotes_by_cell: dict[tuple[str, str, str, int], list[dict[str, Any]]] = defaultdict(list)
    seen_by_cell: dict[tuple[str, str, str, int], set[tuple[str, str]]] = defaultdict(set)
    showcase_dir = ROOT / "results" / "gemini" / "replay-ladder-showcase"
    manifest_fp = showcase_dir / "manifest.json"
    if not manifest_fp.exists():
        return quotes_by_cell

    manifest = json.loads(manifest_fp.read_text(encoding="utf-8"))
    model_to_cell: dict[str, tuple[str, str, str, int]] = {}
    for rel_ep in manifest.get("episodes") or {}:
        parts = Path(rel_ep).parts
        if len(parts) >= 4:
            m_name, lv, tr, sd = parts[0], parts[1], parts[2], int(parts[3])
            model_to_cell[m_name] = (m_name, lv, tr, sd)

    entries_by_cell: dict[tuple[str, str, str, int], list[tuple[int, float, str, str, str, str]]] = defaultdict(list)
    for gz_fp in sorted(showcase_dir.glob("*/*.json.gz")):
        rel_fp = str(gz_fp.relative_to(ROOT))
        raw_gz = _read_raw_source(rel_fp, raw_cache)
        outer = json.loads(raw_gz)
        m_name = outer.get("model") or ""
        cell = model_to_cell.get(m_name)
        if not cell:
            continue
        body_str = outer.get("body") or ""
        try:
            body = json.loads(body_str)
        except json.JSONDecodeError:
            continue
        cands = body.get("candidates") or []
        parts = (cands[0].get("content") or {}).get("parts") or [] if cands else []
        fcalls = [p["functionCall"] for p in parts if isinstance(p, dict) and "functionCall" in p]
        tool_name = fcalls[0].get("name", "") if fcalls else ""
        tool_rank = {
            "accuse": 0,
            "restrict_access": 1,
            "plant_canary": 2,
            "interview": 3,
        }.get(tool_name, 4)
        for p in parts:
            if not isinstance(p, dict) or not p.get("text"):
                continue
            part_text = p["text"]
            kind_note = "thought" if p.get("thought") else "response_text"
            span = _best_verbatim_span(
                part_text,
                raw_gz,
                extra_haystack=body_str,
                min_len=20,
                max_len=240,
            )
            if span:
                entries_by_cell[cell].append(
                    (tool_rank, float(outer.get("ts") or 0.0), rel_fp, tool_name, kind_note, span)
                )

    for cell, items in entries_by_cell.items():
        items.sort(key=lambda x: (x[0], -x[1], x[2]))
        for _, _, rel_fp, tool_name, kind_note, span in items[:4]:
            raw_gz = _read_raw_source(rel_fp, raw_cache)
            _emit_quote(
                quotes_by_cell[cell],
                seen_by_cell[cell],
                span,
                raw_gz,
                rel_fp,
                "replay_showcase",
                tool=tool_name or None,
                note=f"replay-ladder-showcase {kind_note}",
            )

    return quotes_by_cell


def _collect_inproc_transcripts(
    cells: set[tuple[str, str, str, int]],
    raw_cache: dict[str, str],
) -> dict[tuple[str, str, str, int], list[dict[str, Any]]]:
    quotes_by_cell: dict[tuple[str, str, str, int], list[dict[str, Any]]] = defaultdict(list)
    seen_by_cell: dict[tuple[str, str, str, int], set[tuple[str, str]]] = defaultdict(set)
    base_dir = ROOT / "data" / "runs" / "committed" / "v1.4" / "inproc-gemini-4-carbon"
    if not base_dir.exists():
        return quotes_by_cell

    for cell in sorted(cells):
        model, level, tier, seed = cell
        if model != "gemini-4-carbon" or level != "default":
            continue
        tr_fp = base_dir / tier / "transcripts" / f"{seed}.json"
        if not tr_fp.exists():
            continue
        rel_tr = str(tr_fp.relative_to(ROOT))
        raw_tr = _read_raw_source(rel_tr, raw_cache)
        msgs = json.loads(raw_tr)
        ranked: list[tuple[int, int, str, str]] = []
        call_idx = 0
        for m in msgs:
            if m.get("role") != "assistant":
                continue
            tcalls = m.get("tool_calls") or []
            first_tool = tcalls[0].get("name", "") if tcalls else ""
            trank = {"accuse": 0, "restrict_access": 1, "plant_canary": 2}.get(first_tool, 3)
            for it in m.get("provider_items") or []:
                if not isinstance(it, dict):
                    continue
                for p in it.get("parts") or []:
                    if isinstance(p, dict) and p.get("thought") and p.get("text"):
                        span = _best_verbatim_span(p["text"], raw_tr, min_len=20, max_len=240)
                        if span:
                            ranked.append((trank, -call_idx, first_tool, span))
            call_idx += max(1, len(tcalls))
        ranked.sort(key=lambda x: (x[0], x[1]))
        for _, neg_idx, tool_name, span in ranked[:2]:
            _emit_quote(
                quotes_by_cell[cell],
                seen_by_cell[cell],
                span,
                raw_tr,
                rel_tr,
                "transcript",
                t=-neg_idx,
                tool=tool_name or None,
                note="committed inproc thought summary",
            )
    return quotes_by_cell


def _extract_step_quotes_from_line(
    ep: dict[str, Any],
    raw_line: str,
    raw_file_text: str,
    source_file: str,
    regret_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    reg_by_t = {
        int(r["t"]): r
        for r in regret_rows
        if isinstance(r.get("t"), int) and r.get("action") != "(no accusation)"
    }
    steps = ep.get("steps") or []
    scored_steps: list[tuple[int, float, int, dict[str, Any]]] = []
    for s in steps:
        t_val = int(s.get("t", 0))
        tool = s.get("tool") or ""
        reg = float((reg_by_t.get(t_val) or {}).get("regret") or 0.0)
        prio = (
            0
            if tool == "accuse"
            else 1
            if reg > 0 and tool in ("plant_canary", "restrict_access", "interview")
            else 2
            if reg > 0
            else 3
            if tool in ("plant_canary", "restrict_access", "interview")
            else 4
        )
        scored_steps.append((prio, -reg, -t_val, s))
    scored_steps.sort(key=lambda x: (x[0], x[1], x[2]))

    for _, _, _, s in scored_steps:
        if len(out) >= 2:
            break
        t_val = int(s.get("t", 0))
        day_val = int(s.get("day", 0))
        tool = s.get("tool") or ""
        r_info = reg_by_t.get(t_val) or {}
        tags = r_info.get("tags") or []

        candidates = [
            json.dumps(s, sort_keys=True),
            json.dumps(s),
            json.dumps({"args": s.get("args") or {}}, sort_keys=True)[1:-1],
            json.dumps({"args": s.get("args") or {}})[1:-1],
        ]
        chosen: str | None = None
        for cand in candidates:
            if not cand or _has_unicode_dash(cand):
                continue
            if len(cand) <= 240 and cand in raw_line and cand in raw_file_text:
                chosen = cand
                break
        if chosen is None:
            pat = rf'"t":\s*{t_val},\s*"tool":\s*"{re.escape(tool)}"'
            m = re.search(pat, raw_line)
            if m and not _has_unicode_dash(m.group(0)) and m.group(0) in raw_file_text:
                chosen = m.group(0)
        if chosen:
            _emit_quote(
                out,
                seen,
                chosen,
                raw_file_text,
                source_file,
                "episode_step",
                t=t_val,
                day=day_val,
                tool=tool,
                mode=tags[0] if tags else None,
                note="verbatim episode step JSON",
            )
    return out


def _verify_against_ladder_report(
    episodes_map: dict[str, dict[str, Any]],
    ladder_doc: dict[str, Any],
) -> None:
    ref_loaded = load_ladder(ROOT / "results" / "gemini" / "ladder_episodes.jsonl.gz")
    assert len(ref_loaded) == 550
    for e in ref_loaded:
        c = e["_cell"]
        ek = f"{c['model']}/{c['level']}/{c['tier']}/{c['seed']}"
        assert ek in episodes_map, f"missing ladder cell {ek}"
        got = episodes_map[ek]
        assert abs(got["cost_usd"] - c["cost_usd"]) < 1e-12, f"cost mismatch on {ek}"
        assert abs(got["score"] - float(e["score"])) < 1e-12, f"score mismatch on {ek}"

    grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for ep_entry in episodes_map.values():
        grouped[(ep_entry["model"], ep_entry["level"], ep_entry["tier"])].append(ep_entry)

    for row in ladder_doc.get("rows") or []:
        cell_key = (row["model"], row["level"], row["tier"])
        cell_eps = grouped.get(cell_key) or []
        assert len(cell_eps) == row["n"], f"count mismatch on {cell_key}: {len(cell_eps)} != {row['n']}"
        mean_cost = sum(x["cost_usd"] for x in cell_eps) / len(cell_eps)
        mean_score = sum(x["score"] for x in cell_eps) / len(cell_eps)
        mean_solver = sum(x["solver_score"] for x in cell_eps) / len(cell_eps)
        assert abs(mean_cost - row["cost_per_ep"]) < 1e-9, f"cell cost mismatch on {cell_key}"
        assert abs(mean_score - row["mean"]) < 1e-9, f"cell score mismatch on {cell_key}"
        assert abs(mean_solver - row["solver_same_seeds"]) < 1e-9, f"solver score mismatch on {cell_key}"


def build_annotations() -> dict[str, Any]:
    raw_cache: dict[str, str] = {}
    records, ladder_doc = _load_all_episodes(raw_cache)
    ledger_by_run = _load_ledger_index()

    pairs = {(tier, seed) for (_, _, tier, seed) in records}
    solver_eps = reference_episodes(pairs, agents=("solver",))
    solver_scores = {(e["tier"], int(e["seed"])): float(e["score"]) for e in solver_eps}

    regret_map = _compute_regret_map(records)

    atlas1_q, atlas1_cf = _collect_atlas_annotations("results/gemini/atlas.json", "atlas", raw_cache)
    atlas2_q, atlas2_cf = _collect_atlas_annotations("results/gemini/v2/atlas.json", "atlas_v2", raw_cache)
    blind_q, _ = _collect_atlas_annotations("results/gemini/atlas_blind.json", "atlas_blind", raw_cache)
    val_q = _collect_validation_context(raw_cache)
    replay_q = _collect_replay_showcase(raw_cache)
    tr_q = _collect_inproc_transcripts(set(records.keys()), raw_cache)

    def _cell_sort_key(cell: tuple[str, str, str, int]) -> tuple[int, str, int, str, int, str, int]:
        m, lv, tr, sd = cell
        return (
            MODEL_ORDER.index(m) if m in MODEL_ORDER else 99,
            m,
            LEVEL_ORDER.index(lv) if lv in LEVEL_ORDER else 99,
            lv,
            TIERS.index(tr) if tr in TIERS else 9,
            tr,
            sd,
        )

    episodes_out: dict[str, dict[str, Any]] = {}
    by_scenario: dict[str, dict[str, dict[str, str]]] = {}

    tag_episode_counts: dict[str, int] = defaultdict(int)
    dataset_counts: dict[str, int] = defaultdict(int)
    quote_source_counts: dict[str, int] = defaultdict(int)
    total_quotes = 0

    for cell in sorted(records.keys(), key=_cell_sort_key):
        model, level, tier, seed = cell
        rec = records[cell]
        ep = rec["ep"]
        source_file = rec["source_file"]
        raw_line = rec["raw_line"]
        raw_file_text = _read_raw_source(source_file, raw_cache)

        meta = ep.get("meta") or {}
        lad = meta.get("ladder") or {}
        run_id = lad.get("run_id") or meta.get("run_id")
        ledger_rows = [r for r in ledger_by_run.get(run_id or "", []) if r.get("ok", True)]

        if rec["dataset"] in ("ladder", "ladder30"):
            tok = lad.get("tokens") or {}
            if tok:
                tin = int(tok.get("in") or 0)
                tout = int(tok.get("out") or 0)
                tthink = int(tok.get("thinking") or 0)
                tcached = int(tok.get("cached") or 0)
                tcalls = int(tok.get("calls") or 0)
            else:
                tin = sum(int(r.get("in") or 0) for r in ledger_rows)
                tout = sum(int(r.get("out") or 0) for r in ledger_rows)
                tthink = sum(int(r.get("thinking") or 0) for r in ledger_rows)
                tcached = sum(int(r.get("cached") or 0) for r in ledger_rows)
                tcalls = len(ledger_rows)
            tout_incl_thinking = tout + tthink
            thinking_val: int | None = tthink
            thinking_is_estimate = False
            cost_usd = price(model, tin, tout_incl_thinking, tcached)
        else:
            usage = meta.get("usage") or {}
            tin = int(usage.get("in") or 0)
            tout_incl_thinking = int(usage.get("out") or 0)
            tcached = int(usage.get("cached_in") or 0)
            tcalls = int(usage.get("calls") or 0)
            tout = 0
            thinking_val = tout_incl_thinking
            thinking_is_estimate = True
            cost_usd = price(model, tin, tout_incl_thinking, tcached)

        reg_items = regret_map[cell]
        regret_total = round(sum(float(it.get("regret") or 0.0) for it in reg_items), 6)

        tag_stats: dict[str, dict[str, Any]] = {}
        regret_steps: list[dict[str, Any]] = []
        for it in reg_items:
            r_val = float(it.get("regret") or 0.0)
            it_tags = list(it.get("tags") or [])
            t_step = it.get("t")
            p_best = it.get("p_best")
            if r_val > 0 or it_tags:
                step_entry: dict[str, Any] = {
                    "t": t_step,
                    "day": it.get("day"),
                    "action": it.get("action"),
                    "regret": round(r_val, 6),
                    "p_best": p_best,
                    "tags": it_tags,
                }
                if "p_accused" in it:
                    step_entry["p_accused"] = it["p_accused"]
                if it_tags:
                    p_fmt = float(p_best or 0.0)
                    step_entry["why"] = _clean_prose(
                        "; ".join(WHY.get(tg, tg).format(p=p_fmt) for tg in it_tags)
                    )
                regret_steps.append(step_entry)
            for tg in it_tags:
                st = tag_stats.setdefault(
                    tg,
                    {
                        "count": 0,
                        "regret": 0.0,
                        "steps": [],
                        "why": _clean_prose(WHY.get(tg, tg).format(p=float(p_best or 0.0))),
                    },
                )
                st["count"] += 1
                st["regret"] = round(st["regret"] + r_val, 6)
                if isinstance(t_step, int):
                    st["steps"].append(t_step)

        for tg in tag_stats:
            tag_episode_counts[tg] += 1

        highlighted = {
            tg: {
                "present": tg in tag_stats,
                "count": tag_stats[tg]["count"] if tg in tag_stats else 0,
                "regret": tag_stats[tg]["regret"] if tg in tag_stats else 0.0,
                "steps": tag_stats[tg]["steps"] if tg in tag_stats else [],
            }
            for tg in HIGHLIGHT_TAGS
        }

        primary_failure_tag: str | None = None
        if tag_stats:
            primary_failure_tag = sorted(
                tag_stats.keys(),
                key=lambda k: (-tag_stats[k]["regret"], -tag_stats[k]["count"], k),
            )[0]

        ep_quotes: list[dict[str, Any]] = []
        seen_q: set[tuple[str, str]] = set()
        for q_list in (
            atlas1_q.get(cell, []),
            atlas2_q.get(cell, []),
            blind_q.get(cell, []),
            val_q.get(cell, []),
            replay_q.get(cell, []),
            tr_q.get(cell, []),
        ):
            for q_item in q_list:
                raw_src = _read_raw_source(q_item["source_file"], raw_cache)
                _emit_quote(
                    ep_quotes,
                    seen_q,
                    q_item["quote"],
                    raw_src,
                    q_item["source_file"],
                    q_item["source_kind"],
                    t=q_item.get("t"),
                    day=q_item.get("day"),
                    tool=q_item.get("tool"),
                    mode=q_item.get("mode"),
                    note=q_item.get("note"),
                )

        step_quotes = _extract_step_quotes_from_line(
            ep,
            raw_line,
            raw_file_text,
            source_file,
            reg_items,
        )
        for sq in step_quotes:
            _emit_quote(
                ep_quotes,
                seen_q,
                sq["quote"],
                raw_file_text,
                sq["source_file"],
                sq["source_kind"],
                t=sq.get("t"),
                day=sq.get("day"),
                tool=sq.get("tool"),
                mode=sq.get("mode"),
                note=sq.get("note"),
            )

        ep_quotes = ep_quotes[:6]
        for q_item in ep_quotes:
            quote_source_counts[q_item["source_kind"]] += 1
            total_quotes += 1

        cfs = (atlas1_cf.get(cell, []) + atlas2_cf.get(cell, []))[:4]

        slash_key = f"{model}/{level}/{tier}/{seed}"
        pipe_key = f"{model}|{level}|{tier}|{seed}"
        s_score = solver_scores[(tier, seed)]
        ep_score = float(ep["score"])
        dataset_counts[rec["dataset"]] += 1

        worst_regret_step = (
            max(regret_steps, key=lambda s: (s["regret"], s.get("t") or 0))
            if regret_steps
            else None
        )

        episodes_out[slash_key] = {
            "key": slash_key,
            "pipe_key": pipe_key,
            "atlas_id": _atlas_episode_id(model, level, tier, seed),
            "model": model,
            "served_model": SERVED_AS.get(model, model),
            "level": level,
            "tier": tier,
            "seed": seed,
            "dataset": rec["dataset"],
            "in_ladder30": rec["in_ladder30"],
            "source_file": source_file,
            "run_id": run_id,
            "score": ep_score,
            "solver_score": s_score,
            "score_vs_solver_diff": round(ep_score - s_score, 6),
            "correct": bool(ep.get("correct", False)),
            "accused": ep.get("accused"),
            "final_day": int(ep.get("final_day", 0)),
            "end_reason": ep.get("end_reason", ""),
            "step_count": len(ep.get("steps") or []),
            "tokens": {
                "in": tin,
                "out": tout,
                "thinking": thinking_val,
                "tout_incl_thinking": tout_incl_thinking,
                "cached": tcached,
                "calls": tcalls,
                "thinking_is_estimate": thinking_is_estimate,
            },
            "cost_usd": round(cost_usd, 9),
            "ledger_calls_recorded": len(ledger_rows),
            "regret_total": regret_total,
            "primary_failure_tag": primary_failure_tag,
            "worst_regret_step": worst_regret_step,
            "highlighted_tags": highlighted,
            "tags": dict(sorted(tag_stats.items(), key=lambda kv: (-kv[1]["regret"], kv[0]))),
            "regret_steps": regret_steps,
            "quotes": ep_quotes,
            "counterfactuals": cfs,
        }

        scen_key = f"{tier}/{seed}"
        by_scenario.setdefault(scen_key, {}).setdefault(model, {})[level] = slash_key

    _verify_against_ladder_report(episodes_out, ladder_doc)

    sorted_scenarios: dict[str, dict[str, dict[str, str]]] = {}
    for scen_key in sorted(
        by_scenario.keys(),
        key=lambda sk: (
            TIERS.index(sk.split("/")[0]) if sk.split("/")[0] in TIERS else 9,
            int(sk.split("/")[1]),
        ),
    ):
        m_dict = by_scenario[scen_key]
        sorted_scenarios[scen_key] = {}
        for m_name in sorted(
            m_dict.keys(),
            key=lambda m: (MODEL_ORDER.index(m) if m in MODEL_ORDER else 99, m),
        ):
            lv_dict = m_dict[m_name]
            sorted_scenarios[scen_key][m_name] = {
                lv: lv_dict[lv]
                for lv in sorted(
                    lv_dict.keys(),
                    key=lambda lv: (LEVEL_ORDER.index(lv) if lv in LEVEL_ORDER else 99, lv),
                )
            }

    prices_json = {m: list(vals) for m, vals in PRICES.items()}
    summary = {
        "total_episodes": len(episodes_out),
        "datasets": dict(sorted(dataset_counts.items())),
        "scenarios_count": len(sorted_scenarios),
        "models": [m for m in MODEL_ORDER if any(e["model"] == m for e in episodes_out.values())],
        "levels": [lv for lv in LEVEL_ORDER if any(e["level"] == lv for e in episodes_out.values())],
        "tiers": list(TIERS),
        "total_cost_usd": round(sum(e["cost_usd"] for e in episodes_out.values()), 6),
        "ladder_only_cost_usd": round(
            sum(e["cost_usd"] for e in episodes_out.values() if e["dataset"] == "ladder"),
            6,
        ),
        "mean_regret_total": round(
            sum(e["regret_total"] for e in episodes_out.values()) / max(1, len(episodes_out)),
            6,
        ),
        "highlighted_tag_episode_counts": {tg: tag_episode_counts.get(tg, 0) for tg in HIGHLIGHT_TAGS},
        "tag_episode_counts": dict(sorted(tag_episode_counts.items(), key=lambda kv: (-kv[1], kv[0]))),
        "total_verified_quotes": total_quotes,
        "quotes_by_source_kind": dict(sorted(quote_source_counts.items())),
        "episodes_with_quotes": sum(1 for e in episodes_out.values() if e["quotes"]),
    }

    return {
        "generated_from_git_sha": _git_input_sha(),
        "prices_usd_per_1m": prices_json,
        "summary": summary,
        "episodes": episodes_out,
        "by_scenario": sorted_scenarios,
    }


def render_js(doc: dict[str, Any]) -> str:
    payload = json.dumps(doc, separators=(",", ":"), ensure_ascii=True)
    helper = (
        'if (typeof window === "undefined") {\n'
        "  var window = globalThis;\n"
        "}\n"
        f"window.OUTTHINK_ANNOTATIONS = {payload};\n"
        "window.getOutthinkAnnotation = function(model, level, tier, seed) {\n"
        "  var store = window.OUTTHINK_ANNOTATIONS && window.OUTTHINK_ANNOTATIONS.episodes;\n"
        "  if (!store || model === null || model === undefined) {\n"
        "    return null;\n"
        "  }\n"
        '  if (arguments.length === 1 && typeof model === "object") {\n'
        "    var obj = model;\n"
        "    model = obj.model;\n"
        "    level = obj.level || obj.thinking_level;\n"
        "    tier = obj.tier;\n"
        "    seed = obj.seed;\n"
        "  }\n"
        '  if (arguments.length === 1 && typeof model === "string") {\n'
        "    var raw = model.trim();\n"
        "    if (store[raw]) {\n"
        "      return store[raw];\n"
        "    }\n"
        '    if (raw.indexOf("|") !== -1) {\n'
        '      var parts = raw.split("|");\n'
        "      if (parts.length === 4) {\n"
        "        model = parts[0];\n"
        "        level = parts[1];\n"
        "        tier = parts[2];\n"
        "        seed = parts[3];\n"
        "      }\n"
        '    } else if (raw.indexOf("/") !== -1) {\n'
        '      var sp = raw.split("/");\n'
        "      if (sp.length === 4) {\n"
        "        model = sp[0];\n"
        "        level = sp[1];\n"
        "        tier = sp[2];\n"
        "        seed = sp[3];\n"
        "      }\n"
        "    }\n"
        "  }\n"
        '  var m = String(model || "").replace(/^gemini:/, "").trim();\n'
        '  var lv = String(level || "").trim().toLowerCase();\n'
        '  var tr = String(tier || "").trim().toLowerCase();\n'
        '  var sd = String(seed !== undefined && seed !== null ? seed : "").trim();\n'
        '  var key = m + "/" + lv + "/" + tr + "/" + sd;\n'
        "  return store[key] || null;\n"
        "};\n"
        'if (typeof module !== "undefined" && module.exports) {\n'
        "  module.exports = {\n"
        "    OUTTHINK_ANNOTATIONS: window.OUTTHINK_ANNOTATIONS,\n"
        "    getOutthinkAnnotation: window.getOutthinkAnnotation\n"
        "  };\n"
        "}\n"
    )
    return helper


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m canary.gemini.outthink_annotations")
    ap.add_argument(
        "--json-out",
        type=Path,
        default=ROOT / "results" / "gemini" / "outthink_annotations.json",
    )
    ap.add_argument(
        "--js-out",
        type=Path,
        default=ROOT / "demo" / "out-think-gemini" / "annotations.js",
    )
    args = ap.parse_args(argv)

    doc = build_annotations()
    json_text = json.dumps(doc, indent=1, ensure_ascii=True) + "\n"
    js_text = render_js(doc)

    assert not _has_unicode_dash(json_text)
    assert not _has_unicode_dash(js_text)
    for code in (0x2012, 0x2013, 0x2014, 0x2015):
        esc = "\\u" + f"{code:04x}"
        assert esc not in json_text
        assert esc not in js_text

    args.json_out.parent.mkdir(parents=True, exist_ok=True)
    args.js_out.parent.mkdir(parents=True, exist_ok=True)
    args.json_out.write_text(json_text, encoding="utf-8")
    args.js_out.write_text(js_text, encoding="utf-8")

    s = doc["summary"]
    print(
        f"outthink_annotations: {s['total_episodes']} episodes, "
        f"{s['scenarios_count']} scenarios, {s['total_verified_quotes']} verified quotes -> "
        f"{args.json_out.relative_to(ROOT)}, {args.js_out.relative_to(ROOT)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
