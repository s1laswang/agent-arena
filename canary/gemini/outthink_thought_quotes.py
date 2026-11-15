from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_JSON_OUT = ROOT / "results" / "gemini" / "outthink_thought_quotes.json"
MAX_JSON_BYTES = 250_000

MODEL_ORDER = (
    "gemini-3.1-flash-lite",
    "gemini-3.5-flash",
    "gemini-3.8-flash",
    "gemini-4-hydrogen",
    "gemini-4-argon",
    "gemini-4-carbon",
)
LEVEL_ORDER = ("minimal", "low", "medium", "high", "xhigh", "default")
TIER_ORDER = ("easy", "medium", "hard")
KIND_ORDER = ("thought_part", "accuse_rationale", "atlas_verified_quote")
UNICODE_DASH_CODES = (0x2010, 0x2011, 0x2012, 0x2013, 0x2014, 0x2015, 0x2212)
UNICODE_DASHES = "".join(chr(c) for c in UNICODE_DASH_CODES)
SECRET_PATTERNS = (
    re.compile(r"AIza[0-9A-Za-z_\-]{20,}"),
    re.compile(r"sk-[A-Za-z0-9]{20,}"),
)

SHORT_TO_MODEL = {
    "g3.1flashlite": "gemini-3.1-flash-lite",
    "g3.5flash": "gemini-3.5-flash",
    "g3.8flash": "gemini-3.8-flash",
    "g4hydrogen": "gemini-4-hydrogen",
    "g4argon": "gemini-4-argon",
    "g4carbon": "gemini-4-carbon",
}

INPUT_PATHS = (
    "results/gemini/replay-ladder",
    "results/gemini/replay-ladder-showcase",
    "results/gemini/replay/showcase.json",
    "results/gemini/atlas.json",
    "results/gemini/v2/atlas.json",
    "results/gemini/atlas_blind.json",
    "data/runs/committed/v1.4/inproc-gemini-4-carbon",
    "data/runs/committed/v1.4/opencode-gemini-4-carbon",
    "data/runs/committed/v1.4/opencode-gemini-3.5-flash",
)


def _has_unicode_dash(text: str) -> bool:
    if any(ch in text for ch in UNICODE_DASHES):
        return True
    low = text.lower()
    for code in UNICODE_DASH_CODES:
        if ("\\u" + f"{code:04x}") in low:
            return True
    return False


def _has_secret(text: str) -> bool:
    return any(pat.search(text) for pat in SECRET_PATTERNS)


def _read_raw(root: Path, rel_path: str, cache: dict[str, str]) -> str:
    if rel_path not in cache:
        full = root / rel_path
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
    min_len: int = 16,
    max_len: int = 210,
) -> str | None:
    if not candidate:
        return None
    trimmed = candidate
    for suffix in (" [...]", "[...]"):
        if trimmed.endswith(suffix):
            trimmed = trimmed[: -len(suffix)]
    sep_pat = "[" + re.escape(UNICODE_DASHES) + r"\r\n\t]+"
    chunks = [c.strip() for c in re.split(sep_pat, trimmed) if c.strip()]
    found: list[str] = []
    for chunk in chunks:
        if chunk.lower() == "thought":
            continue
        sub_chunks = [chunk]
        if chunk not in raw_source or (extra_haystack is not None and chunk not in extra_haystack):
            sub_chunks = [
                s.strip()
                for s in re.split(r'["\\]+', chunk)
                if s.strip() and s.strip().lower() != "thought"
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
            if _has_unicode_dash(cur) or _has_secret(cur):
                continue
            if cur in candidate and cur in raw_source:
                if extra_haystack is None or cur in extra_haystack:
                    found.append(cur)
    if not found:
        return None
    found.sort(key=lambda s: (-len(s), candidate.find(s)))
    best = found[0]
    assert best in candidate
    assert best in raw_source
    assert not _has_unicode_dash(best)
    assert not _has_secret(best)
    if extra_haystack is not None:
        assert best in extra_haystack
    return best


def _git_input_sha(root: Path) -> str:
    ann_fp = root / "results" / "gemini" / "outthink_annotations.json"
    if ann_fp.is_file():
        try:
            ann_doc = json.loads(ann_fp.read_text(encoding="utf-8"))
            sha = str(ann_doc.get("generated_from_git_sha") or "").strip()
            if len(sha) == 40 and all(ch in "0123456789abcdef" for ch in sha):
                return sha
        except Exception:
            pass
    if (root / ".git").exists():
        try:
            out = subprocess.check_output(
                ["git", "log", "-1", "--format=%H", "--", *INPUT_PATHS],
                cwd=root,
                text=True,
                stderr=subprocess.DEVNULL,
            ).strip()
            if out:
                return out
            out = subprocess.check_output(
                ["git", "rev-parse", "HEAD"],
                cwd=root,
                text=True,
                stderr=subprocess.DEVNULL,
            ).strip()
            if out:
                return out
        except Exception:
            pass
    digest = hashlib.sha256()
    for rel in (
        "results/gemini/atlas.json",
        "results/gemini/v2/atlas.json",
        "results/gemini/atlas_blind.json",
        "results/gemini/replay/showcase.json",
        "results/gemini/replay-ladder/manifest.json",
        "results/gemini/replay-ladder-showcase/manifest.json",
        "data/runs/committed/v1.4/inproc-gemini-4-carbon/accuse.md",
        "data/runs/committed/v1.4/opencode-gemini-4-carbon/accuse.md",
        "data/runs/committed/v1.4/opencode-gemini-3.5-flash/accuse.md",
    ):
        fp = root / rel
        if fp.exists():
            digest.update(rel.encode("utf-8"))
            digest.update(fp.read_bytes())
    return digest.hexdigest()[:40]


def _parse_atlas_episode(ep_id: str) -> dict[str, Any] | None:
    m = re.match(r"^([a-z0-9.]+?)(?:-([a-z]+))?\.(in|op)\.v14\.([emh])(\d+)$", ep_id or "")
    if not m:
        return None
    short, lv, harness, t_char, seed_s = m.groups()
    model = SHORT_TO_MODEL.get(short)
    if not model:
        return None
    tier = {"e": "easy", "m": "medium", "h": "hard"}[t_char]
    seed = int(seed_s)
    if harness == "op":
        level = lv or ("high" if model == "gemini-3.5-flash" else "default")
        episode = f"opencode:{model}/{level}/{tier}/{seed}"
    else:
        level = lv or "default"
        episode = f"{model}/{level}/{tier}/{seed}"
    return {
        "model": model,
        "thinking_level": level,
        "tier": tier,
        "seed": seed,
        "episode": episode,
    }


def _parse_accuse_md(raw_md: str) -> dict[tuple[str, int], dict[str, Any]]:
    out: dict[tuple[str, int], dict[str, Any]] = {}
    for line in raw_md.splitlines():
        s = line.strip()
        if not s.startswith("|") or s.startswith("| tier") or s.startswith("|---"):
            continue
        cols = [c.strip() for c in s.strip("|").split("|")]
        if len(cols) < 10:
            continue
        tier = cols[0]
        try:
            seed = int(cols[2])
            day = int(cols[3])
            score = float(cols[6])
        except ValueError:
            continue
        accused = None if cols[4] == "None" else cols[4]
        correct = cols[5] == "True"
        verdict = cols[9]
        failure_tag: str | None = None
        if verdict in ("lucky", "premature-wrong"):
            failure_tag = "premature_accusation"
        elif verdict == "none":
            failure_tag = "no_accusation"
        elif not correct:
            failure_tag = "wrong_accusation"
        out[(tier, seed)] = {
            "day": day,
            "accused": accused,
            "correct": correct,
            "score": score,
            "verdict": verdict,
            "failure_tag": failure_tag,
            "raw_line": s,
        }
    return out


def _load_episodes_index(ep_jsonl: Path) -> dict[int, dict[str, Any]]:
    by_seed: dict[int, dict[str, Any]] = {}
    if not ep_jsonl.exists():
        return by_seed
    for line in ep_jsonl.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        ep = json.loads(line)
        if ep.get("end_reason") == "error":
            continue
        by_seed[int(ep["seed"])] = ep
    return by_seed


def _load_worst_tags_index(tags_fp: Path) -> dict[tuple[str, int, int], str]:
    out: dict[tuple[str, int, int], str] = {}
    if not tags_fp.exists():
        return out
    doc = json.loads(tags_fp.read_text(encoding="utf-8"))
    for agent_block in doc.values():
        if not isinstance(agent_block, dict):
            continue
        tags_dict = agent_block.get("tags") or {}
        for tag_name, tag_info in sorted(tags_dict.items()):
            worst = (tag_info or {}).get("worst") or {}
            tier = worst.get("run_id")
            seed = worst.get("seed")
            t_val = worst.get("t")
            if isinstance(tier, str) and isinstance(seed, int) and isinstance(t_val, int):
                out[(tier, seed, t_val)] = tag_name
    return out


def _infer_tool_from_atlas_quote(quote_str: str) -> str | None:
    m = re.match(r"^t\d+\s+d\d+\s+([a-z_]+)\(", (quote_str or "").strip())
    if m:
        return m.group(1)
    for tool_name in (
        "accuse",
        "restrict_access",
        "plant_canary",
        "interview",
        "check_leak_feed",
        "read_access_logs",
        "search_messages",
        "read_message",
        "read_document",
        "list_documents",
        "list_employees",
        "advance_day",
        "status",
    ):
        if tool_name in (quote_str or ""):
            return tool_name
    return None


def _collect_replay_store_quotes(
    root: Path,
    store_rel: str,
    max_per_model: int,
    raw_cache: dict[str, str],
) -> tuple[list[dict[str, Any]], int, int]:
    store_dir = root / store_rel
    manifest_fp = store_dir / "manifest.json"
    if not store_dir.exists():
        return [], 0, 0

    episodes_by_model: dict[str, list[tuple[str, str, int]]] = defaultdict(list)
    if manifest_fp.exists():
        manifest = json.loads(manifest_fp.read_text(encoding="utf-8"))
        for rel_ep in sorted((manifest.get("episodes") or {}).keys()):
            parts = Path(rel_ep).parts
            if len(parts) >= 4:
                m_name, lv, tr, sd = parts[0], parts[1], parts[2], int(parts[3])
                episodes_by_model[m_name].append((lv, tr, sd))

    gz_files = sorted(store_dir.rglob("*.json.gz"))
    parsed_resps: list[tuple[str, float, str, dict[str, Any], str]] = []
    sig_parts = 0
    thoughts_tokens = 0

    for gz_fp in gz_files:
        rel_fp = gz_fp.relative_to(root).as_posix()
        raw_gz = _read_raw(root, rel_fp, raw_cache)
        outer = json.loads(raw_gz)
        m_name = outer.get("model") or ""
        body_str = outer.get("body") or ""
        try:
            body = json.loads(body_str)
        except json.JSONDecodeError:
            continue
        um = body.get("usageMetadata") or {}
        thoughts_tokens += int(um.get("thoughtsTokenCount") or 0)
        for cand in body.get("candidates") or []:
            for pt in (cand.get("content") or {}).get("parts") or []:
                if isinstance(pt, dict) and pt.get("thoughtSignature"):
                    sig_parts += 1
        parsed_resps.append((m_name, float(outer.get("ts") or 0.0), rel_fp, body, body_str))

    by_model_resps: dict[str, list[tuple[float, str, dict[str, Any], str]]] = defaultdict(list)
    for m_name, ts_val, rel_fp, body, body_str in parsed_resps:
        by_model_resps[m_name].append((ts_val, rel_fp, body, body_str))

    candidates_out: list[dict[str, Any]] = []
    tool_prio = {
        "accuse": 0,
        "restrict_access": 1,
        "plant_canary": 2,
        "check_leak_feed": 3,
        "interview": 4,
    }

    for m_name in sorted(by_model_resps.keys()):
        if m_name not in MODEL_ORDER:
            continue
        ep_specs = episodes_by_model.get(m_name) or []
        single_ep = ep_specs[0] if len(ep_specs) == 1 else None
        default_lv = ep_specs[0][0] if ep_specs else None
        default_tr = ep_specs[0][1] if ep_specs else None

        seq = sorted(by_model_resps[m_name], key=lambda x: (x[0], x[1]))
        ranked: list[tuple[int, int, dict[str, Any]]] = []
        step_cursor = 0

        for idx, (_, rel_fp, body, body_str) in enumerate(seq):
            raw_gz = _read_raw(root, rel_fp, raw_cache)
            cands = body.get("candidates") or []
            parts = (cands[0].get("content") or {}).get("parts") or [] if cands else []
            fcalls = [p["functionCall"] for p in parts if isinstance(p, dict) and "functionCall" in p]
            has_sig = any(isinstance(p, dict) and bool(p.get("thoughtSignature")) for p in parts)
            first_tool = fcalls[0].get("name") if fcalls else None
            step_t = step_cursor if single_ep is not None else None
            step_cursor += max(1, len(fcalls))

            for pt in parts:
                if not isinstance(pt, dict) or not pt.get("thought") or not pt.get("text"):
                    continue
                span = _best_verbatim_span(pt["text"], raw_gz, extra_haystack=body_str)
                if not span:
                    continue
                if single_ep is not None:
                    lv, tr, sd = single_ep
                    ep_key: str | None = f"{m_name}/{lv}/{tr}/{sd}"
                    seed_val: int | None = sd
                else:
                    lv = default_lv
                    tr = default_tr
                    seed_val = None
                    ep_key = None
                rec = {
                    "text": span,
                    "source_file": rel_fp,
                    "kind": "thought_part",
                    "model": m_name,
                    "thinking_level": lv,
                    "tier": tr,
                    "seed": seed_val,
                    "episode": ep_key,
                    "step_t": step_t,
                    "action_or_tool": first_tool,
                    "failure_tag": None,
                    "has_thought_signature": has_sig,
                    "char_len": len(span),
                }
                prio = tool_prio.get(first_tool or "", 5)
                ranked.append((prio, -idx, rec))

        ranked.sort(key=lambda x: (x[0], x[1], x[2]["source_file"]))
        seen_spans: set[str] = set()
        kept = 0
        for _, _, rec in ranked:
            if rec["text"] in seen_spans:
                continue
            seen_spans.add(rec["text"])
            candidates_out.append(rec)
            kept += 1
            if kept >= max_per_model:
                break

    return candidates_out, sig_parts, thoughts_tokens


def _collect_replay_showcase_json(
    root: Path,
    raw_cache: dict[str, str],
) -> list[dict[str, Any]]:
    rel_fp = "results/gemini/replay/showcase.json"
    fp = root / rel_fp
    if not fp.exists():
        return []
    raw_txt = _read_raw(root, rel_fp, raw_cache)
    doc = json.loads(raw_txt)
    m_name = doc.get("model") or "gemini-3.1-flash-lite"
    if m_name not in MODEL_ORDER:
        return []
    out: list[dict[str, Any]] = []
    for idx, st in enumerate(doc.get("steps") or []):
        if not isinstance(st, dict) or not st.get("text"):
            continue
        span = _best_verbatim_span(st["text"], raw_txt, min_len=16, max_len=210)
        if not span:
            continue
        step_kind = st.get("step") or ""
        q_kind = "accuse_rationale" if step_kind == "function_response" else "thought_part"
        out.append(
            {
                "text": span,
                "source_file": rel_fp,
                "kind": q_kind,
                "model": m_name,
                "thinking_level": "low",
                "tier": None,
                "seed": None,
                "episode": None,
                "step_t": idx,
                "action_or_tool": "check_leak" if step_kind == "function_response" else step_kind,
                "failure_tag": None,
                "has_thought_signature": step_kind == "function_response",
                "char_len": len(span),
            }
        )
    return out


def _collect_inproc_committed(
    root: Path,
    raw_cache: dict[str, str],
) -> tuple[list[dict[str, Any]], int]:
    base_rel = "data/runs/committed/v1.4/inproc-gemini-4-carbon"
    base_dir = root / base_rel
    if not base_dir.exists():
        return [], 0

    out: list[dict[str, Any]] = []
    sig_parts = 0

    accuse_rel = f"{base_rel}/accuse.md"
    accuse_map: dict[tuple[str, int], dict[str, Any]] = {}
    if (root / accuse_rel).exists():
        raw_acc = _read_raw(root, accuse_rel, raw_cache)
        accuse_map = _parse_accuse_md(raw_acc)
        for (tier, seed), info in sorted(accuse_map.items()):
            if info["verdict"] in ("lucky", "premature-wrong"):
                line_span = info["raw_line"]
                if not _has_unicode_dash(line_span) and line_span in raw_acc:
                    out.append(
                        {
                            "text": line_span,
                            "source_file": accuse_rel,
                            "kind": "accuse_rationale",
                            "model": "gemini-4-carbon",
                            "thinking_level": "default",
                            "tier": tier,
                            "seed": seed,
                            "episode": f"gemini-4-carbon/default/{tier}/{seed}",
                            "step_t": None,
                            "action_or_tool": "accuse",
                            "failure_tag": info["failure_tag"],
                            "has_thought_signature": False,
                            "char_len": len(line_span),
                        }
                    )

    worst_tags = _load_worst_tags_index(base_dir / "tags.json")

    for tier in ("medium", "hard"):
        tier_dir = base_dir / tier
        if not tier_dir.exists():
            continue
        eps_by_seed = _load_episodes_index(tier_dir / "episodes.jsonl")
        tr_dir = tier_dir / "transcripts"
        if not tr_dir.exists():
            continue

        for tr_fp in sorted(tr_dir.glob("*.json"), key=lambda p: int(p.stem) if p.stem.isdigit() else 9999):
            if not tr_fp.stem.isdigit():
                continue
            seed = int(tr_fp.stem)
            rel_tr = tr_fp.relative_to(root).as_posix()
            raw_tr = _read_raw(root, rel_tr, raw_cache)
            msgs = json.loads(raw_tr)
            ep_key = f"gemini-4-carbon/default/{tier}/{seed}"
            acc_info = accuse_map.get((tier, seed)) or {}
            ep_steps = (eps_by_seed.get(seed) or {}).get("steps") or []

            non_accuse_candidates: list[tuple[int, int, dict[str, Any]]] = []
            accuse_candidate: dict[str, Any] | None = None
            step_idx = 0

            for m in msgs:
                if m.get("role") != "assistant":
                    continue
                tcalls = m.get("tool_calls") or []
                first_tool = tcalls[0].get("name") if tcalls else None
                cur_t = step_idx if step_idx < len(ep_steps) else step_idx
                turn_has_sig = False
                thought_texts: list[str] = []

                for p_item in m.get("provider_items") or []:
                    if not isinstance(p_item, dict):
                        continue
                    for pt in p_item.get("parts") or []:
                        if not isinstance(pt, dict):
                            continue
                        if pt.get("thoughtSignature") or pt.get("thought_signature"):
                            sig_parts += 1
                            turn_has_sig = True
                        if pt.get("thought") and pt.get("text"):
                            thought_texts.append(pt["text"])

                for t_txt in thought_texts:
                    span = _best_verbatim_span(t_txt, raw_tr)
                    if not span:
                        continue
                    step_tag = worst_tags.get((tier, seed, cur_t))
                    if first_tool == "accuse":
                        ftag = step_tag or acc_info.get("failure_tag")
                        accuse_candidate = {
                            "text": span,
                            "source_file": rel_tr,
                            "kind": "accuse_rationale",
                            "model": "gemini-4-carbon",
                            "thinking_level": "default",
                            "tier": tier,
                            "seed": seed,
                            "episode": ep_key,
                            "step_t": cur_t,
                            "action_or_tool": "accuse",
                            "failure_tag": ftag,
                            "has_thought_signature": turn_has_sig,
                            "char_len": len(span),
                        }
                    else:
                        prio = (
                            0
                            if step_tag
                            else 1
                            if first_tool == "restrict_access"
                            else 2
                            if first_tool == "plant_canary"
                            else 3
                            if first_tool == "check_leak_feed"
                            else 4
                        )
                        non_accuse_candidates.append(
                            (
                                prio,
                                -cur_t,
                                {
                                    "text": span,
                                    "source_file": rel_tr,
                                    "kind": "thought_part",
                                    "model": "gemini-4-carbon",
                                    "thinking_level": "default",
                                    "tier": tier,
                                    "seed": seed,
                                    "episode": ep_key,
                                    "step_t": cur_t,
                                    "action_or_tool": first_tool,
                                    "failure_tag": step_tag,
                                    "has_thought_signature": turn_has_sig,
                                    "char_len": len(span),
                                },
                            )
                        )
                step_idx += max(1, len(tcalls))

            if non_accuse_candidates:
                non_accuse_candidates.sort(key=lambda x: (x[0], x[1]))
                chosen_tp = non_accuse_candidates[0][2]
                if seed < 15 or chosen_tp["failure_tag"] is not None or acc_info.get("failure_tag") is not None:
                    out.append(chosen_tp)

            if accuse_candidate is not None:
                if seed < 12 or accuse_candidate["failure_tag"] is not None:
                    out.append(accuse_candidate)

    return out, sig_parts


def _collect_opencode_committed(
    root: Path,
    run_rel: str,
    model: str,
    thinking_level: str,
    tiers: tuple[str, ...],
    max_rationales_per_tier: int,
    raw_cache: dict[str, str],
) -> tuple[list[dict[str, Any]], int]:
    base_dir = root / run_rel
    if not base_dir.exists():
        return [], 0

    out: list[dict[str, Any]] = []
    sig_parts = 0

    accuse_rel = f"{run_rel}/accuse.md"
    accuse_map: dict[tuple[str, int], dict[str, Any]] = {}
    if (root / accuse_rel).exists():
        raw_acc = _read_raw(root, accuse_rel, raw_cache)
        accuse_map = _parse_accuse_md(raw_acc)
        for (tier, seed), info in sorted(accuse_map.items()):
            if info["verdict"] in ("lucky", "premature-wrong") or not info["correct"]:
                line_span = info["raw_line"]
                if not _has_unicode_dash(line_span) and line_span in raw_acc:
                    out.append(
                        {
                            "text": line_span,
                            "source_file": accuse_rel,
                            "kind": "accuse_rationale",
                            "model": model,
                            "thinking_level": thinking_level,
                            "tier": tier,
                            "seed": seed,
                            "episode": f"opencode:{model}/{thinking_level}/{tier}/{seed}",
                            "step_t": None,
                            "action_or_tool": "accuse",
                            "failure_tag": info["failure_tag"],
                            "has_thought_signature": False,
                            "char_len": len(line_span),
                        }
                    )
                    if sum(1 for r in out if r["source_file"] == accuse_rel) >= 6:
                        break

    for tier in tiers:
        tier_dir = base_dir / tier
        tr_dir = tier_dir / "transcripts"
        if not tr_dir.exists():
            continue
        eps_by_seed = _load_episodes_index(tier_dir / "episodes.jsonl")
        tier_rationales: list[tuple[int, int, dict[str, Any]]] = []

        for tr_fp in sorted(tr_dir.glob("*.txt"), key=lambda p: int(p.stem) if p.stem.isdigit() else 9999):
            if not tr_fp.stem.isdigit():
                continue
            seed = int(tr_fp.stem)
            rel_tr = tr_fp.relative_to(root).as_posix()
            raw_tr = _read_raw(root, rel_tr, raw_cache)
            ep_key = f"opencode:{model}/{thinking_level}/{tier}/{seed}"
            acc_info = accuse_map.get((tier, seed)) or {}
            ep_steps = (eps_by_seed.get(seed) or {}).get("steps") or []
            accuse_step_t: int | None = None
            for st in ep_steps:
                if st.get("tool") == "accuse":
                    accuse_step_t = int(st.get("t", 0))

            tool_idx = 0
            accuse_sig = False
            last_tool: str | None = None
            last_tool_sig = False
            text_events: list[tuple[int, str | None, bool, str]] = []

            for ln in raw_tr.splitlines():
                if not ln.startswith("{"):
                    continue
                try:
                    ev = json.loads(ln)
                except json.JSONDecodeError:
                    continue
                pt = ev.get("part") or {}
                has_sig = bool(((pt.get("metadata") or {}).get("google") or {}).get("thoughtSignature"))
                if has_sig:
                    sig_parts += 1
                if ev.get("type") == "tool_use":
                    raw_tool = str(pt.get("tool") or "")
                    clean_tool = raw_tool[len("canary_") :] if raw_tool.startswith("canary_") else raw_tool
                    last_tool = clean_tool or None
                    last_tool_sig = has_sig
                    if clean_tool == "accuse" and has_sig:
                        accuse_sig = True
                    tool_idx += 1
                elif ev.get("type") == "text" and pt.get("text"):
                    text_events.append((max(0, tool_idx - 1), last_tool, last_tool_sig, pt["text"]))

            for ev_t, prev_tool, prev_sig, raw_ev_text in text_events:
                stripped = raw_ev_text.strip()
                if stripped.lower().startswith("thought"):
                    span = _best_verbatim_span(stripped, raw_tr)
                    if span:
                        out.append(
                            {
                                "text": span,
                                "source_file": rel_tr,
                                "kind": "thought_part",
                                "model": model,
                                "thinking_level": thinking_level,
                                "tier": tier,
                                "seed": seed,
                                "episode": ep_key,
                                "step_t": ev_t,
                                "action_or_tool": prev_tool,
                                "failure_tag": acc_info.get("failure_tag") if prev_tool == "accuse" else None,
                                "has_thought_signature": prev_sig,
                                "char_len": len(span),
                            }
                        )

            non_thought_texts = [
                (ev_t, prev_tool, prev_sig, txt)
                for (ev_t, prev_tool, prev_sig, txt) in text_events
                if not txt.strip().lower().startswith("thought")
            ]
            if non_thought_texts:
                ev_t, prev_tool, prev_sig, final_txt = non_thought_texts[-1]
                span = _best_verbatim_span(final_txt, raw_tr)
                if span:
                    ftag = acc_info.get("failure_tag")
                    prio = 0 if ftag is not None else 1
                    tier_rationales.append(
                        (
                            prio,
                            seed,
                            {
                                "text": span,
                                "source_file": rel_tr,
                                "kind": "accuse_rationale",
                                "model": model,
                                "thinking_level": thinking_level,
                                "tier": tier,
                                "seed": seed,
                                "episode": ep_key,
                                "step_t": accuse_step_t if accuse_step_t is not None else ev_t,
                                "action_or_tool": "accuse" if acc_info.get("accused") else prev_tool,
                                "failure_tag": ftag,
                                "has_thought_signature": accuse_sig or prev_sig,
                                "char_len": len(span),
                            },
                        )
                    )

        tier_rationales.sort(key=lambda x: (x[0], x[1]))
        for _, _, rec in tier_rationales[:max_rationales_per_tier]:
            out.append(rec)

    return out, sig_parts


def _collect_atlas_quotes(
    root: Path,
    rel_path: str,
    max_step_records: int,
    raw_cache: dict[str, str],
) -> list[dict[str, Any]]:
    fp = root / rel_path
    if not fp.exists():
        return []
    raw_txt = _read_raw(root, rel_path, raw_cache)
    doc = json.loads(raw_txt)
    out: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()

    for mode in doc.get("modes") or []:
        mode_id = mode.get("id") or None
        for qobj in (mode.get("quotes") or []) + (mode.get("examples") or []):
            if not isinstance(qobj, dict) or qobj.get("verified") is False:
                continue
            parsed = _parse_atlas_episode(qobj.get("episode") or "")
            if not parsed:
                continue
            q_raw = qobj.get("quote") or ""
            span = _best_verbatim_span(q_raw, raw_txt, min_len=14, max_len=210)
            if not span:
                continue
            key = (parsed["episode"], span)
            if key in seen:
                continue
            seen.add(key)
            t_val = qobj.get("t")
            out.append(
                {
                    "text": span,
                    "source_file": rel_path,
                    "kind": "atlas_verified_quote",
                    "model": parsed["model"],
                    "thinking_level": parsed["thinking_level"],
                    "tier": parsed["tier"],
                    "seed": parsed["seed"],
                    "episode": parsed["episode"],
                    "step_t": int(t_val) if isinstance(t_val, int) else None,
                    "action_or_tool": _infer_tool_from_atlas_quote(q_raw),
                    "failure_tag": mode_id,
                    "has_thought_signature": False,
                    "char_len": len(span),
                }
            )

    step_candidates: list[tuple[int, str, int, dict[str, Any]]] = []
    for st in (doc.get("labels") or {}).get("steps") or []:
        if not isinstance(st, dict) or st.get("verified") is False:
            continue
        parsed = _parse_atlas_episode(st.get("episode") or "")
        if not parsed:
            continue
        q_raw = st.get("quote") or ""
        span = _best_verbatim_span(q_raw, raw_txt, min_len=14, max_len=210)
        if not span:
            continue
        key = (parsed["episode"], span)
        if key in seen:
            continue
        t_val = st.get("t")
        is_agent_words = st.get("source") == "agent_words"
        prio = 0 if is_agent_words else 1
        rec = {
            "text": span,
            "source_file": rel_path,
            "kind": "atlas_verified_quote",
            "model": parsed["model"],
            "thinking_level": parsed["thinking_level"],
            "tier": parsed["tier"],
            "seed": parsed["seed"],
            "episode": parsed["episode"],
            "step_t": int(t_val) if isinstance(t_val, int) else None,
            "action_or_tool": _infer_tool_from_atlas_quote(q_raw),
            "failure_tag": st.get("mode") or None,
            "has_thought_signature": False,
            "char_len": len(span),
        }
        step_candidates.append((prio, parsed["episode"], int(t_val or 0), rec))

    step_candidates.sort(key=lambda x: (x[0], x[1], x[2]))
    step_kept = 0
    for prio, ep_k, _, rec in step_candidates:
        key = (ep_k, rec["text"])
        if key in seen:
            continue
        if prio > 0 and step_kept >= max_step_records:
            continue
        seen.add(key)
        out.append(rec)
        if prio > 0:
            step_kept += 1

    return out


def _verify_quote_record(rec: dict[str, Any], root: Path, raw_cache: dict[str, str]) -> None:
    raw_src = _read_raw(root, rec["source_file"], raw_cache)
    txt = rec["text"]
    assert isinstance(txt, str) and len(txt) > 0
    assert txt in raw_src, f"quote not verbatim in {rec['source_file']}: {txt!r}"
    assert rec["char_len"] == len(txt)
    assert rec["kind"] in KIND_ORDER
    assert rec["model"] in MODEL_ORDER
    assert isinstance(rec["has_thought_signature"], bool)
    assert not _has_unicode_dash(txt)
    assert not _has_secret(txt)


def build_thought_quotes(root: Path = ROOT) -> dict[str, Any]:
    root = Path(root).resolve()
    raw_cache: dict[str, str] = {}
    sig_by_source: dict[str, int] = {}

    rl_quotes, rl_sigs, rl_toks = _collect_replay_store_quotes(
        root, "results/gemini/replay-ladder", max_per_model=8, raw_cache=raw_cache
    )
    rls_quotes, rls_sigs, rls_toks = _collect_replay_store_quotes(
        root, "results/gemini/replay-ladder-showcase", max_per_model=6, raw_cache=raw_cache
    )
    show_quotes = _collect_replay_showcase_json(root, raw_cache=raw_cache)

    inproc_quotes, inproc_sigs = _collect_inproc_committed(root, raw_cache=raw_cache)
    oc_c_quotes, oc_c_sigs = _collect_opencode_committed(
        root,
        "data/runs/committed/v1.4/opencode-gemini-4-carbon",
        model="gemini-4-carbon",
        thinking_level="default",
        tiers=("medium", "hard"),
        max_rationales_per_tier=12,
        raw_cache=raw_cache,
    )
    oc_f_quotes, oc_f_sigs = _collect_opencode_committed(
        root,
        "data/runs/committed/v1.4/opencode-gemini-3.5-flash",
        model="gemini-3.5-flash",
        thinking_level="high",
        tiers=("hard",),
        max_rationales_per_tier=16,
        raw_cache=raw_cache,
    )

    atlas1_quotes = _collect_atlas_quotes(root, "results/gemini/atlas.json", max_step_records=18, raw_cache=raw_cache)
    atlas2_quotes = _collect_atlas_quotes(root, "results/gemini/v2/atlas.json", max_step_records=22, raw_cache=raw_cache)
    blind_quotes = _collect_atlas_quotes(
        root, "results/gemini/atlas_blind.json", max_step_records=10, raw_cache=raw_cache
    )

    if rl_sigs:
        sig_by_source["replay-ladder"] = rl_sigs
    if rls_sigs:
        sig_by_source["replay-ladder-showcase"] = rls_sigs
    if inproc_sigs:
        sig_by_source["inproc-gemini-4-carbon"] = inproc_sigs
    if oc_c_sigs:
        sig_by_source["opencode-gemini-4-carbon"] = oc_c_sigs
    if oc_f_sigs:
        sig_by_source["opencode-gemini-3.5-flash"] = oc_f_sigs

    combined = (
        rls_quotes
        + rl_quotes
        + show_quotes
        + inproc_quotes
        + oc_c_quotes
        + oc_f_quotes
        + atlas1_quotes
        + atlas2_quotes
        + blind_quotes
    )

    deduped: list[dict[str, Any]] = []
    seen_global: set[tuple[str, str, str]] = set()
    for rec in combined:
        gkey = (rec["source_file"], rec["kind"], rec["text"])
        if gkey in seen_global:
            continue
        seen_global.add(gkey)
        _verify_quote_record(rec, root, raw_cache)
        deduped.append(rec)

    def _quote_sort_key(r: dict[str, Any]) -> tuple[Any, ...]:
        k_idx = KIND_ORDER.index(r["kind"]) if r["kind"] in KIND_ORDER else 99
        m_idx = MODEL_ORDER.index(r["model"]) if r["model"] in MODEL_ORDER else 99
        lv = r["thinking_level"] or ""
        lv_idx = LEVEL_ORDER.index(lv) if lv in LEVEL_ORDER else 99
        tr = r["tier"] or ""
        tr_idx = TIER_ORDER.index(tr) if tr in TIER_ORDER else 99
        sd = r["seed"] if isinstance(r["seed"], int) else 999999
        st = r["step_t"] if isinstance(r["step_t"], int) else 999999
        return (k_idx, m_idx, lv_idx, tr_idx, sd, st, r["source_file"], r["text"])

    deduped.sort(key=_quote_sort_key)

    quotes_out: list[dict[str, Any]] = []
    by_episode_raw: dict[str, list[str]] = defaultdict(list)
    by_tier_seed_raw: dict[str, list[str]] = defaultdict(list)
    counts_by_kind: dict[str, int] = defaultdict(int)
    counts_by_model: dict[str, int] = defaultdict(int)
    counts_by_level: dict[str, int] = defaultdict(int)
    verified_count = 0
    quotes_with_sig = 0

    for idx, rec in enumerate(deduped, start=1):
        qid = f"tq_{idx:04d}"
        ordered_rec = {
            "quote_id": qid,
            "text": rec["text"],
            "source_file": rec["source_file"],
            "kind": rec["kind"],
            "model": rec["model"],
            "thinking_level": rec["thinking_level"],
            "tier": rec["tier"],
            "seed": rec["seed"],
            "episode": rec["episode"],
            "step_t": rec["step_t"],
            "action_or_tool": rec["action_or_tool"],
            "failure_tag": rec["failure_tag"],
            "has_thought_signature": rec["has_thought_signature"],
            "char_len": rec["char_len"],
        }
        _verify_quote_record(ordered_rec, root, raw_cache)
        verified_count += 1
        if ordered_rec["has_thought_signature"]:
            quotes_with_sig += 1
        counts_by_kind[ordered_rec["kind"]] += 1
        counts_by_model[ordered_rec["model"]] += 1
        lv_key = ordered_rec["thinking_level"] or "unknown"
        counts_by_level[lv_key] += 1
        if ordered_rec["episode"]:
            by_episode_raw[ordered_rec["episode"]].append(qid)
        if ordered_rec["tier"] is not None and ordered_rec["seed"] is not None:
            by_tier_seed_raw[f"{ordered_rec['tier']}/{ordered_rec['seed']}"].append(qid)
        quotes_out.append(ordered_rec)

    assert verified_count == len(quotes_out)

    by_episode = {k: by_episode_raw[k] for k in sorted(by_episode_raw.keys())}
    by_tier_seed = {
        k: by_tier_seed_raw[k]
        for k in sorted(
            by_tier_seed_raw.keys(),
            key=lambda ts: (
                TIER_ORDER.index(ts.split("/")[0]) if ts.split("/")[0] in TIER_ORDER else 99,
                int(ts.split("/")[1]),
            ),
        )
    }

    total_sig_parts = sum(sig_by_source.values())
    summary = {
        "total_quotes": len(quotes_out),
        "verified_quotes": verified_count,
        "counts_by_kind": {k: counts_by_kind[k] for k in KIND_ORDER if counts_by_kind.get(k, 0) > 0},
        "counts_by_model": {m: counts_by_model[m] for m in MODEL_ORDER if counts_by_model.get(m, 0) > 0},
        "counts_by_thinking_level": {
            lv: counts_by_level[lv]
            for lv in (*LEVEL_ORDER, "unknown")
            if counts_by_level.get(lv, 0) > 0
        },
        "thought_signature_part_count": total_sig_parts,
        "quotes_with_thought_signature": quotes_with_sig,
        "thought_signature_parts_by_source": dict(sorted(sig_by_source.items())),
        "thoughts_token_count_total": rl_toks + rls_toks,
        "episodes_covered": len(by_episode),
        "tier_seeds_covered": len(by_tier_seed),
    }

    return {
        "generated_from_git_sha": _git_input_sha(root),
        "summary": summary,
        "by_episode": by_episode,
        "by_tier_seed": by_tier_seed,
        "quotes": quotes_out,
    }


def validate_thought_quotes(doc: dict[str, Any], root: Path = ROOT) -> list[str]:
    root = Path(root).resolve()
    errors: list[str] = []
    if not isinstance(doc, dict):
        return ["top-level document must be a JSON object"]
    expected_keys = {"generated_from_git_sha", "summary", "by_episode", "by_tier_seed", "quotes"}
    if set(doc.keys()) != expected_keys:
        errors.append(f"unexpected top-level keys: {sorted(doc.keys())}")
        return errors
    sha = doc.get("generated_from_git_sha")
    if not isinstance(sha, str) or len(sha) != 40 or not all(ch in "0123456789abcdef" for ch in sha):
        errors.append(f"invalid generated_from_git_sha: {sha!r}")
    quotes = doc.get("quotes")
    summary = doc.get("summary")
    by_ep = doc.get("by_episode")
    by_ts = doc.get("by_tier_seed")
    if not isinstance(quotes, list) or not isinstance(summary, dict):
        errors.append("quotes must be list and summary must be dict")
        return errors
    if not isinstance(by_ep, dict) or not isinstance(by_ts, dict):
        errors.append("by_episode and by_tier_seed must be dicts")
        return errors

    raw_cache: dict[str, str] = {}
    seen_qids: set[str] = set()
    for q in quotes:
        qid = q.get("quote_id")
        if not isinstance(qid, str) or qid in seen_qids:
            errors.append(f"duplicate or missing quote_id: {qid!r}")
            continue
        seen_qids.add(qid)
        try:
            _verify_quote_record(q, root, raw_cache)
        except Exception as exc:
            errors.append(f"{qid}: {exc}")

    if summary.get("total_quotes") != len(quotes):
        errors.append(f"summary.total_quotes {summary.get('total_quotes')} != {len(quotes)}")
    if summary.get("verified_quotes") != len(quotes):
        errors.append(f"summary.verified_quotes {summary.get('verified_quotes')} != {len(quotes)}")
    if summary.get("episodes_covered") != len(by_ep):
        errors.append(f"summary.episodes_covered {summary.get('episodes_covered')} != {len(by_ep)}")
    if summary.get("tier_seeds_covered") != len(by_ts):
        errors.append(f"summary.tier_seeds_covered {summary.get('tier_seeds_covered')} != {len(by_ts)}")

    for ep_k, qids in by_ep.items():
        if not isinstance(qids, list) or not qids or any(qid not in seen_qids for qid in qids):
            errors.append(f"invalid by_episode entry for {ep_k!r}")
    for ts_k, qids in by_ts.items():
        if not isinstance(qids, list) or not qids or any(qid not in seen_qids for qid in qids):
            errors.append(f"invalid by_tier_seed entry for {ts_k!r}")

    return errors


def render_json(doc: dict[str, Any]) -> str:
    txt = json.dumps(doc, indent=1, ensure_ascii=True) + "\n"
    if len(txt.encode("utf-8")) > 240_000:
        txt = json.dumps(doc, separators=(",", ":"), ensure_ascii=True) + "\n"
    assert not _has_unicode_dash(txt)
    assert not _has_secret(txt)
    return txt


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m canary.gemini.outthink_thought_quotes")
    ap.add_argument("--root", type=Path, default=ROOT)
    ap.add_argument(
        "--out",
        "--json-out",
        dest="out",
        type=Path,
        default=None,
    )
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args(argv)
    root = Path(args.root).resolve()
    out_path = Path(args.out) if args.out is not None else (root / "results" / "gemini" / "outthink_thought_quotes.json")

    doc = build_thought_quotes(root=root)
    errors = validate_thought_quotes(doc, root=root)
    if errors:
        for err in errors:
            sys.stderr.write(f"ERROR: {err}\n")
        return 1

    payload = render_json(doc)
    payload_bytes = len(payload.encode("utf-8"))
    if payload_bytes >= MAX_JSON_BYTES:
        sys.stderr.write(f"ERROR: JSON size {payload_bytes} exceeds {MAX_JSON_BYTES} bytes\n")
        return 1

    if args.check:
        if not out_path.is_file():
            sys.stderr.write(f"ERROR: missing {out_path}\n")
            return 1
        on_disk = out_path.read_text(encoding="utf-8")
        if on_disk != payload:
            sys.stderr.write(f"ERROR: {out_path} does not match deterministic build\n")
            return 1
        s = doc["summary"]
        sys.stdout.write(
            f"OK: {s['total_quotes']} verified quotes, "
            f"{s['thought_signature_part_count']} thoughtSignature parts, "
            f"{payload_bytes} bytes verified.\n"
        )
        return 0

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(payload, encoding="utf-8")

    s = doc["summary"]
    sys.stdout.write(
        f"outthink_thought_quotes: {s['total_quotes']} verified quotes, "
        f"{s['thought_signature_part_count']} thoughtSignature parts -> {out_path}\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
