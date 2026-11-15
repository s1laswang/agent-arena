from __future__ import annotations

import argparse
from contextlib import contextmanager
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import sys
import tarfile
import tempfile
import types
import urllib.request
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from canary.env import Env
from canary.eval import run_episode
from canary.solver.policy import SolverPolicy

DEFAULT_OUT = ROOT / "docs" / "arena" / "data" / "living_office_pack.js"
DEFAULT_SEEDS: tuple[int, ...] = (0, 1, 6)
SOURCE_COMMIT_SHORT = "95322b44"
CANDIDATE_GIT_REFS: tuple[str, ...] = (
    "95322b44e9bb97bb273e77e12fdc572c0336dcff",
    "95322b44",
    "origin/fr8/canary/canary-staffai-w1-demo",
    "fr8/canary/canary-staffai-w1-demo",
    "origin/fr8/canary/demo-living-office",
    "origin/fr8/canary/staffai",
)

HASH_CH = chr(35)
SLASH_SLASH = chr(47) * 2
SLASH_STAR = chr(47) + chr(42)
STAR_SLASH = chr(42) + chr(47)
EM_DASH = chr(0x2014)
EN_DASH = chr(0x2013)
UNICODE_MINUS = chr(0x2212)
LSQUO = chr(0x2018)
RSQUO = chr(0x2019)
LDQUO = chr(0x201C)
RDQUO = chr(0x201D)
ELLIPSIS = chr(0x2026)
NBSP = chr(0x00A0)

SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
MULTI_SPACE_RE = re.compile(r"\s+")

BANNER_TEXT = (
    "OFF-BY-DEFAULT v1.6 PREVIEW: Did NOT pass Gate B gap gate "
    "(v1.5 biased employees moved gemini-4-carbon 61% -> 108% of SolverPolicy on hard seeds 0-9; "
    "relayed v1.6 0.617 vs 0.523 v1.4 control); "
    "100% offline cached gemini-4-carbon chatter, 0 API calls, 0 solver score drift (0.576 == 0.576)."
)

PRE_END_FORBIDDEN_KEYS: frozenset[str] = frozenset({
    "mole",
    "true_mole",
    "mole_id",
    "is_mole",
    "decoy",
    "true_decoy",
    "decoy_id",
    "is_decoy",
    "decoy_mood",
    "correct",
    "accused_correct",
    "true_v",
    "true_V",
    "V",
    "visible_v",
    "hud_v",
    "display_v",
    "shown_v",
    "is_canary",
    "world_seed",
    "_world",
    "leaking_sprite_employee",
    "mole_sprite",
    "culprit_sprite",
    "leaker_employee",
})


def sanitize_ascii(value: str) -> str:
    text = str(value or "")
    text = text.replace(EM_DASH, " - ")
    text = text.replace(EN_DASH, "-")
    text = text.replace(UNICODE_MINUS, "-")
    text = text.replace(LSQUO, "'").replace(RSQUO, "'")
    text = text.replace(LDQUO, '"').replace(RDQUO, '"')
    text = text.replace(ELLIPSIS, "...")
    text = text.replace(NBSP, " ")
    text = text.replace(HASH_CH, "")
    text = text.replace(SLASH_SLASH, "/")
    text = text.replace(SLASH_STAR, " ")
    text = text.replace(STAR_SLASH, " ")
    text = MULTI_SPACE_RE.sub(" ", text).strip()
    if not text.isascii():
        text = text.encode("ascii", "ignore").decode("ascii")
    return text


def sanitize_channel(raw_channel: str) -> str:
    cleaned = str(raw_channel or "").strip()
    while cleaned.startswith(HASH_CH):
        cleaned = cleaned[1:].strip()
    return sanitize_ascii(cleaned) or "general"


@contextmanager
def offline_network_guard(cache_dir: Path):
    def _deny_net(*_a: object, **_kw: object) -> None:
        raise RuntimeError("forbidden live network call during offline Living Office export")

    env_keys = (
        "CANARY_OFFLINE",
        "CANARY_GEMINI_CACHE_DIR",
        "GEMINI_" + "API_KEY",
        "GOOGLE_GENERATIVE_AI_" + "API_KEY",
        "OPENAI_" + "API_KEY",
    )
    saved_env = {k: os.environ.get(k) for k in env_keys}
    orig_connect = socket.socket.connect
    orig_create = socket.create_connection
    orig_urlopen = urllib.request.urlopen

    os.environ["CANARY_OFFLINE"] = "1"
    os.environ["CANARY_GEMINI_CACHE_DIR"] = str(cache_dir)
    for k in env_keys[2:]:
        os.environ[k] = ""

    socket.socket.connect = _deny_net
    socket.create_connection = _deny_net
    urllib.request.urlopen = _deny_net
    try:
        yield
    finally:
        socket.socket.connect = orig_connect
        socket.create_connection = orig_create
        urllib.request.urlopen = orig_urlopen
        for k, prev in saved_env.items():
            if prev is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = prev


def _resolve_git_ref(repo_root: Path, explicit_ref: str | None) -> str | None:
    refs = (explicit_ref,) if explicit_ref else CANDIDATE_GIT_REFS
    for ref in refs:
        if not ref:
            continue
        proc = subprocess.run(
            ["git", "cat-file", "-e", f"{ref}^{{commit}}"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if proc.returncode == 0:
            return ref
    return None


@contextmanager
def _social_runtime(
    repo_root: Path,
    social_root: Path | None = None,
    cache_dir: Path | None = None,
    source_ref: str | None = None,
):
    direct_root = social_root if social_root is not None else repo_root
    direct_social = direct_root / "canary" / "social"
    direct_llm_cache = direct_root / "canary" / "text" / "llm_cache.py"
    direct_cache = cache_dir if cache_dir is not None else (direct_root / "data" / "gemini_cache")

    scratch_base = Path("/tmp/opencode")
    scratch_base.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(dir=str(scratch_base), prefix="arena_living_export_") as tmp:
        tmp_path = Path(tmp)
        if direct_social.is_dir() and direct_llm_cache.is_file() and direct_cache.is_dir():
            active_root = direct_root
            active_cache = direct_cache
        else:
            ref = _resolve_git_ref(repo_root, source_ref)
            if ref is None:
                raise RuntimeError("social cache source not found on disk or in git refs")
            archive_proc = subprocess.run(
                [
                    "git",
                    "archive",
                    ref,
                    "canary/social",
                    "canary/text/llm_cache.py",
                    "data/gemini_cache",
                ],
                cwd=repo_root,
                capture_output=True,
                timeout=20,
            )
            if archive_proc.returncode != 0:
                raise RuntimeError(f"git archive failed for ref {ref}")
            import io

            with tarfile.open(fileobj=io.BytesIO(archive_proc.stdout), mode="r:") as tf:
                if "filter" in tarfile.TarFile.extractall.__code__.co_varnames:
                    tf.extractall(path=tmp_path, filter="data")
                else:
                    tf.extractall(path=tmp_path)
            active_root = tmp_path
            active_cache = cache_dir if cache_dir is not None else (tmp_path / "data" / "gemini_cache")

        saved_modules: dict[str, types.ModuleType | None] = {}

        def _load_pkg_module(mod_name: str, file_path: Path, pkg_paths: list[str] | None = None) -> Any:
            if mod_name not in saved_modules:
                saved_modules[mod_name] = sys.modules.get(mod_name)
            spec = importlib.util.spec_from_file_location(
                mod_name,
                file_path,
                submodule_search_locations=pkg_paths,
            )
            if spec is None or spec.loader is None:
                raise RuntimeError(f"unable to load {mod_name} from {file_path}")
            mod = importlib.util.module_from_spec(spec)
            sys.modules[mod_name] = mod
            spec.loader.exec_module(mod)
            return mod

        try:
            _load_pkg_module("canary.text.llm_cache", active_root / "canary" / "text" / "llm_cache.py")
            social_dir = active_root / "canary" / "social"
            _load_pkg_module("canary.social", social_dir / "__init__.py", [str(social_dir)])
            gemini_chatter_mod = _load_pkg_module(
                "canary.social.gemini_chatter",
                social_dir / "gemini_chatter.py",
            )
            engine_mod = _load_pkg_module("canary.social.engine", social_dir / "engine.py")
            llm_cache_mod = sys.modules["canary.text.llm_cache"]
            yield engine_mod, gemini_chatter_mod, llm_cache_mod, active_cache
        finally:
            for m_name, prev_mod in saved_modules.items():
                if prev_mod is None:
                    sys.modules.pop(m_name, None)
                else:
                    sys.modules[m_name] = prev_mod


def _audit_cache_files_subset(cache_dir: Path, used_keys: list[str]) -> dict[str, Any]:
    unique_keys = sorted(set(used_keys))
    real_count = 0
    model_hits = 0
    for key in unique_keys:
        fp = cache_dir / f"{key}.json"
        if not fp.is_file():
            raise RuntimeError(f"missing expected cache file {fp.name}")
        obj = json.loads(fp.read_text(encoding="utf-8"))
        prov = obj.get("provenance") or {}
        if prov.get("label") == "REAL":
            real_count += 1
        if prov.get("model") == "gemini-4-carbon":
            model_hits += 1
    return {
        "unique_keys": len(unique_keys),
        "real_count": real_count,
        "gemini_4_carbon_count": model_hits,
    }


def build_pack_dict(
    repo_root: Path = ROOT,
    seeds: tuple[int, ...] = DEFAULT_SEEDS,
    social_root: Path | None = None,
    cache_dir: Path | None = None,
    source_ref: str | None = None,
) -> dict[str, Any]:
    with _social_runtime(
        repo_root=repo_root,
        social_root=social_root,
        cache_dir=cache_dir,
        source_ref=source_ref,
    ) as (engine_mod, gemini_chatter_mod, llm_cache_mod, active_cache):
        episodes: dict[str, Any] = {}
        all_hit_keys: list[str] = []
        total_social_messages = 0
        total_rejects = 0

        orig_cached_chat = gemini_chatter_mod.cached_chat

        for seed in seeds:
            prompt_sha_by_day: dict[int, str] = {}
            seed_hits: list[str] = []

            def _tracked_cached_chat(cdir: Any, client: Any, model: str, system: str, user: str, **kw: Any) -> dict[str, Any]:
                k = llm_cache_mod.cache_key(model, system, [{"role": "user", "content": user}], None, 0, None)
                day_num = len(prompt_sha_by_day) + 1
                for part in user.split(". "):
                    if part.startswith("Day ") and part[4:].isdigit():
                        day_num = int(part[4:])
                        break
                prompt_sha_by_day[day_num] = k
                res = orig_cached_chat(cdir, client, model, system, user, **kw)
                seed_hits.append(k)
                return res

            gemini_chatter_mod.cached_chat = _tracked_cached_chat
            try:
                with offline_network_guard(active_cache):
                    prov = engine_mod.V16SocialProvider(
                        "v5_full9_cocktail",
                        mode="gemini",
                        cache_dir=str(active_cache),
                    )
                    env = Env("hard", seed=seed, text_provider=prov)
                    emp_res = env.call("list_employees", {})
                    raw_emps = emp_res.data.get("employees") or []
                    employees: list[dict[str, Any]] = []
                    emp_by_id: dict[str, dict[str, Any]] = {}
                    for emp in raw_emps:
                        clean_emp = {
                            "id": sanitize_ascii(emp["id"]),
                            "name": sanitize_ascii(emp["name"]),
                            "dept": sanitize_ascii(emp.get("dept") or emp.get("department") or ""),
                            "role": sanitize_ascii(emp.get("role") or ""),
                            "clearance": int(emp.get("clearance", 1)),
                        }
                        employees.append(clean_emp)
                        emp_by_id[clean_emp["id"]] = clean_emp

                    company_name = sanitize_ascii(env._facts(1).company)
                    max_day = int(env.p.n_days)

                    for d in range(1, max_day + 1):
                        if d > 1:
                            env.call("advance_day", {})
                        env.call("search_messages", {"query": "doc"})

                    true_v_end = round(float(env.V), 4)
                    true_mole = sanitize_ascii(env._world.mole)
                    true_decoy = sanitize_ascii(env._world.decoy)
            finally:
                gemini_chatter_mod.cached_chat = orig_cached_chat

            st = next(iter(prov._states.values()))
            total_rejects += int(prov.rejects)
            all_hit_keys.extend(seed_hits)

            rendered_social_by_day: dict[int, list[dict[str, Any]]] = {}
            for (d_num, *_rest), rendered_list in sorted(st.rendered_by_day.items(), key=lambda kv: kv[0][0]):
                rendered_social_by_day[int(d_num)] = [
                    m for m in rendered_list if "-s" in str(m.get("id", ""))
                ]

            grudge_pairs_meta: list[dict[str, Any]] = []
            for accuser_id, target_id in st.grudge_pairs:
                acc_emp = emp_by_id.get(accuser_id, {})
                tgt_emp = emp_by_id.get(target_id, {})
                grudge_pairs_meta.append({
                    "a": sanitize_ascii(accuser_id),
                    "a_name": acc_emp.get("name", sanitize_ascii(accuser_id)),
                    "b": sanitize_ascii(target_id),
                    "b_name": tgt_emp.get("name", sanitize_ascii(target_id)),
                    "dept": tgt_emp.get("dept", ""),
                    "reason": "recurring doc review clash",
                })

            grudge_tracker: dict[tuple[str, str], dict[str, Any]] = {}
            days_payload: list[dict[str, Any]] = []

            for d in range(1, max_day + 1):
                raw_evs = list(st.events_by_day.get(d, ()))
                day_msgs = rendered_social_by_day.get(d, [])
                new_rumours: list[dict[str, Any]] = []
                new_chat_feed: list[dict[str, Any]] = []
                new_gossip_edges: list[dict[str, Any]] = []

                for idx, msg in enumerate(day_msgs):
                    ev = raw_evs[idx] if idx < len(raw_evs) else {}
                    msg_id = sanitize_ascii(msg.get("id", f"m{d}-s{idx}"))
                    sender_id = sanitize_ascii(msg.get("sender", ""))
                    sender_name = emp_by_id.get(sender_id, {}).get("name", sender_id)
                    target_id = sanitize_ascii(ev.get("target") or "")
                    if not target_id:
                        extracted = gemini_chatter_mod.extract_target(msg)
                        target_id = sanitize_ascii(extracted or "")
                    target_name = emp_by_id.get(target_id, {}).get("name", target_id or "office")
                    channel = sanitize_channel(msg.get("channel", "general"))
                    subject = sanitize_ascii(msg.get("subject", ""))
                    body = sanitize_ascii(msg.get("body", ""))
                    bias_type = sanitize_ascii(ev.get("bias") or "rumour")
                    doc_title = sanitize_ascii(ev.get("doc_title") or "")
                    recipients = [sanitize_ascii(r) for r in (msg.get("recipients") or [])]

                    if bias_type == "grudge" and sender_id and target_id:
                        pair_key = (sender_id, target_id)
                        entry = grudge_tracker.get(pair_key)
                        if entry is None:
                            entry = {
                                "a": sender_id,
                                "a_name": sender_name,
                                "b": target_id,
                                "b_name": target_name,
                                "dept": emp_by_id.get(target_id, {}).get("dept", ""),
                                "incidents": 0,
                                "first_day": d,
                                "last_day": d,
                            }
                            grudge_tracker[pair_key] = entry
                        entry["incidents"] = int(entry["incidents"]) + 1
                        entry["last_day"] = d

                    new_rumours.append({
                        "id": msg_id,
                        "day": d,
                        "from": sender_id,
                        "from_name": sender_name,
                        "to": target_id or "office",
                        "to_name": target_name,
                        "channel": channel,
                        "subject": subject,
                        "text": body,
                        "bias_type": bias_type,
                        "doc_title": doc_title,
                    })

                    new_chat_feed.append({
                        "id": msg_id,
                        "day": d,
                        "channel": channel,
                        "sender": sender_id,
                        "sender_name": sender_name,
                        "target": target_id or "office",
                        "target_name": target_name,
                        "recipients": recipients,
                        "subject": subject,
                        "body": body,
                        "text": body,
                        "bias_type": bias_type,
                    })

                    if sender_id and target_id:
                        new_gossip_edges.append({
                            "day": d,
                            "source": sender_id,
                            "source_name": sender_name,
                            "target": target_id,
                            "target_name": target_name,
                            "channel": channel,
                            "bias_type": bias_type,
                            "weight": 1,
                            "message_id": msg_id,
                        })

                total_social_messages += len(new_rumours)

                active_grudges: list[dict[str, Any]] = []
                for g_entry in grudge_tracker.values():
                    inc = int(g_entry["incidents"])
                    last_d = int(g_entry["last_day"])
                    noun = "clash" if inc == 1 else "clashes"
                    active_grudges.append({
                        "a": g_entry["a"],
                        "a_name": g_entry["a_name"],
                        "b": g_entry["b"],
                        "b_name": g_entry["b_name"],
                        "dept": g_entry["dept"],
                        "reason": f"doc review {noun} ({inc}x through D{last_d:02d})",
                        "incidents": inc,
                        "first_day": int(g_entry["first_day"]),
                        "last_day": last_d,
                    })

                days_payload.append({
                    "day": d,
                    "prompt_sha256": prompt_sha_by_day.get(d),
                    "new_rumours": new_rumours,
                    "new_chat_feed": new_chat_feed,
                    "new_gossip_edges": new_gossip_edges,
                    "active_grudges": active_grudges,
                })

            solver_ep = run_episode(Env("hard", seed=seed), SolverPolicy("hard"))
            primary_focus = sanitize_ascii(st.primary_suspect)
            secondary_focus = sanitize_ascii(st.secondary_suspect)
            active_days_count = sum(1 for item in days_payload if item["new_rumours"])

            episodes[f"hard:{seed}"] = {
                "tier": "hard",
                "seed": int(seed),
                "company": company_name,
                "max_day": max_day,
                "active_social_days": active_days_count,
                "cache_prompt_sha256_by_day": {
                    str(k): v for k, v in sorted(prompt_sha_by_day.items())
                },
                "employees": employees,
                "focal_targets": {
                    "primary": primary_focus,
                    "secondary": secondary_focus,
                },
                "grudge_pairs": grudge_pairs_meta,
                "days": days_payload,
                "sealed_reveal": {
                    "tier": "hard",
                    "seed": int(seed),
                    "mole": true_mole,
                    "mole_name": emp_by_id.get(true_mole, {}).get("name", true_mole),
                    "decoy": true_decoy,
                    "decoy_name": emp_by_id.get(true_decoy, {}).get("name", true_decoy),
                    "true_v_day21": true_v_end,
                    "primary_focus": primary_focus,
                    "secondary_focus": secondary_focus,
                    "primary_focus_is_mole": primary_focus == true_mole,
                    "secondary_focus_is_mole": secondary_focus == true_mole,
                    "solver_accused": sanitize_ascii(solver_ep.accused or ""),
                    "solver_correct": bool(solver_ep.correct),
                    "solver_final_day": int(solver_ep.final_day),
                    "solver_score": round(float(solver_ep.score), 4),
                },
            }

        cache_check = _audit_cache_files_subset(active_cache, all_hit_keys)
        if cache_check["unique_keys"] != len(all_hit_keys):
            raise RuntimeError("unexpected duplicate cache prompt keys across seeds/days")
        if cache_check["real_count"] != len(all_hit_keys) or cache_check["gemini_4_carbon_count"] != len(all_hit_keys):
            raise RuntimeError("cache provenance mismatch: expected 100% REAL gemini-4-carbon")
        if total_rejects != 0:
            raise RuntimeError(f"expected 0 validator rejects on cached prompts, got {total_rejects}")

        return {
            "schema_version": "canary.arena.living_office_pack.v1",
            "mode_id": "living",
            "label": "Living Office",
            "badge": "V1.6 PREVIEW - OFF BY DEFAULT",
            "default_enabled": False,
            "off_by_default": True,
            "gateBPassed": False,
            "gate_b_passed": False,
            "judged_benchmark_version": "v1.4",
            "tier": "hard",
            "default_seeds": [int(s) for s in seeds],
            "seeds": [int(s) for s in seeds],
            "max_day": 21,
            "active_social_days": 18,
            "banner": BANNER_TEXT,
            "gate_b_disclosure": {
                "gateBPassed": False,
                "gate_b_passed": False,
                "default_enabled": False,
                "shipped_benchmark_version": "v1.4",
                "v15_hard_0_9_gemini_pct_of_solver_before": 60.9,
                "v15_hard_0_9_gemini_pct_of_solver_after": 108.0,
                "v15_summary": (
                    "v1.5 biased employees moved gemini-4-carbon 61% -> 108% of SolverPolicy "
                    "on hard seeds 0-9 because non-mole rumour targets acted as an exoneration signal"
                ),
                "v16_solver_hard_0_9_v14": 0.576,
                "v16_solver_hard_0_9_v16": 0.576,
                "v16_relayed_30_32_v5_mean": 0.617,
                "v16_relayed_30_32_v0_control_mean": 0.523,
                "verdict": "GATE NOT MET - DO NOT SHIP AS DEFAULT",
            },
            "provenance": {
                "offline_only": True,
                "live_api_calls": 0,
                "model": "gemini-4-carbon",
                "label": "REAL",
                "source_commit": SOURCE_COMMIT_SHORT,
                "cache_prompts_total": len(all_hit_keys),
                "cache_prompts_hit": len(all_hit_keys),
                "cache_hit_rate": 1.0,
                "social_messages_total": total_social_messages,
                "validator_rejects": total_rejects,
            },
            "episodes": episodes,
        }


def serialize_pack_js(pack: dict[str, Any]) -> str:
    payload_json = json.dumps(pack, indent=2, sort_keys=False, ensure_ascii=True)
    js_src = (
        "export const CANARY_LIVING_OFFICE_PACK = "
        + payload_json
        + ";\n\nglobalThis.CANARY_LIVING_OFFICE_PACK = CANARY_LIVING_OFFICE_PACK;\n"
    )
    _assert_text_hygiene(js_src, "living_office_pack.js")
    return js_src


def _assert_text_hygiene(src: str, label: str) -> None:
    if not src.isascii():
        raise ValueError(f"{label}: non-ASCII byte found")
    for bad_tok, bad_name in (
        (HASH_CH, "hash"),
        (SLASH_SLASH, "line-comment"),
        (SLASH_STAR, "block-comment-open"),
        (STAR_SLASH, "block-comment-close"),
        (EM_DASH, "em-dash"),
        (EN_DASH, "en-dash"),
        (UNICODE_MINUS, "unicode-minus"),
    ):
        if bad_tok in src:
            raise ValueError(f"{label}: forbidden {bad_name} marker found")


def _scan_pre_end_forbidden_keys(node: Any, loc: str) -> list[str]:
    hits: list[str] = []
    if isinstance(node, dict):
        for k, v in node.items():
            ks = str(k)
            if ks == "sealed_reveal":
                continue
            cur = f"{loc}.{ks}"
            if ks in PRE_END_FORBIDDEN_KEYS:
                hits.append(cur)
            hits.extend(_scan_pre_end_forbidden_keys(v, cur))
    elif isinstance(node, list):
        for idx, item in enumerate(node):
            hits.extend(_scan_pre_end_forbidden_keys(item, f"{loc}[{idx}]"))
    return hits


def validate_pack_file(pack_path: Path, seeds: tuple[int, ...] = DEFAULT_SEEDS) -> dict[str, Any]:
    if not pack_path.is_file():
        raise FileNotFoundError(f"missing {pack_path}")
    raw = pack_path.read_text(encoding="utf-8")
    _assert_text_hygiene(raw, pack_path.name)

    prefix = "export const CANARY_LIVING_OFFICE_PACK = "
    if not raw.startswith(prefix):
        raise ValueError("living_office_pack.js missing canonical export const header")
    if "globalThis.CANARY_LIVING_OFFICE_PACK = CANARY_LIVING_OFFICE_PACK;" not in raw:
        raise ValueError("living_office_pack.js missing globalThis assignment")

    decoder = json.JSONDecoder()
    pack, _end = decoder.raw_decode(raw, len(prefix))
    if not isinstance(pack, dict):
        raise ValueError("decoded pack is not an object")

    if pack.get("gateBPassed") is not False or pack.get("gate_b_passed") is not False:
        raise ValueError("gateBPassed must be False")
    if pack.get("default_enabled") is not False:
        raise ValueError("default_enabled must be False")
    if "Did NOT pass Gate B" not in str(pack.get("banner", "")):
        raise ValueError("banner missing mandatory Gate B failure disclosure")

    prov = pack.get("provenance") or {}
    if prov.get("offline_only") is not True or int(prov.get("live_api_calls", -1)) != 0:
        raise ValueError("invalid offline provenance")
    if prov.get("model") != "gemini-4-carbon" or prov.get("label") != "REAL":
        raise ValueError("invalid model/label provenance")
    if int(prov.get("cache_prompts_total", 0)) != 54 or int(prov.get("cache_prompts_hit", 0)) != 54:
        raise ValueError("expected 54/54 cached gemini-4-carbon prompts")

    leak_hits = _scan_pre_end_forbidden_keys(pack, "CANARY_LIVING_OFFICE_PACK")
    if leak_hits:
        raise ValueError(f"pre-end forbidden keys found outside sealed_reveal: {leak_hits}")

    episodes = pack.get("episodes") or {}
    for seed in seeds:
        ep_key = f"hard:{seed}"
        if ep_key not in episodes:
            raise ValueError(f"missing episode {ep_key}")
        ep = episodes[ep_key]
        days = ep.get("days") or []
        if len(days) != 21:
            raise ValueError(f"{ep_key}: expected 21 days, got {len(days)}")
        for idx, d_obj in enumerate(days, 1):
            if int(d_obj.get("day", 0)) != idx:
                raise ValueError(f"{ep_key}: day index mismatch at {idx}")
            sha = d_obj.get("prompt_sha256")
            if idx <= 18:
                if not isinstance(sha, str) or not SHA256_RE.match(sha):
                    raise ValueError(f"{ep_key}: missing sha256 on active day {idx}")
                if not d_obj.get("new_rumours"):
                    raise ValueError(f"{ep_key}: expected cached rumours on day {idx}")
            else:
                if d_obj.get("new_rumours"):
                    raise ValueError(f"{ep_key}: unexpected new rumours on late window day {idx}")

        live_env = Env("hard", seed=seed)
        sr = ep.get("sealed_reveal") or {}
        if sr.get("mole") != live_env._world.mole or sr.get("decoy") != live_env._world.decoy:
            raise ValueError(f"{ep_key}: sealed_reveal world truth mismatch")
        if len(ep.get("employees") or []) != 40:
            raise ValueError(f"{ep_key}: expected 40 employees")

    return pack


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Export offline cached Living Office pack for Canary Arena.")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT, help="Output JS module path")
    ap.add_argument("--social-root", type=Path, default=None, help="Optional root containing canary/social")
    ap.add_argument("--cache-dir", type=Path, default=None, help="Optional directory of cached gemini-4-carbon JSONs")
    ap.add_argument("--source-ref", default=None, help="Optional git ref for w1-demo social cache source")
    ap.add_argument("--check", action="store_true", help="Verify committed pack matches deterministic export")
    args = ap.parse_args(argv)

    if args.check:
        validate_pack_file(args.out)
        try:
            regenerated = serialize_pack_js(
                build_pack_dict(
                    repo_root=ROOT,
                    social_root=args.social_root,
                    cache_dir=args.cache_dir,
                    source_ref=args.source_ref,
                )
            )
        except RuntimeError:
            regenerated = None
        if regenerated is not None:
            current = args.out.read_text(encoding="utf-8")
            if current != regenerated:
                print("FAIL: docs/arena/data/living_office_pack.js is out of sync with deterministic export")
                return 1
        print(f"PASS: {args.out} verified (54/54 REAL gemini-4-carbon prompts, 0 API calls, 0 pre-end leaks)")
        return 0

    pack = build_pack_dict(
        repo_root=ROOT,
        social_root=args.social_root,
        cache_dir=args.cache_dir,
        source_ref=args.source_ref,
    )
    rendered = serialize_pack_js(pack)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(rendered, encoding="utf-8")
    validate_pack_file(args.out)
    print(f"WROTE {args.out} ({len(rendered)} bytes, 54/54 REAL gemini-4-carbon prompts, 0 API calls)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
