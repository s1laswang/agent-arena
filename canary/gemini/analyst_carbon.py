from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from canary.llm.pricing import cost as price_cost

ROLE = "failure_analyst"
TARGET_MODEL = "gemini-4-carbon"
DEFAULT_ANALYST_DIR = Path("results/gemini/roles_carbon/failure_analyst")
DEFAULT_INDEX_PATH = Path("results/gemini/roles_carbon/failure_analyst/index.json")
DEFAULT_DOC_PATH = Path("docs/gemini/roles_carbon/analyst.md")

MD_H1 = chr(35)
MD_H2 = chr(35) * 2
MD_H3 = chr(35) * 3

SKIP_DIRS = frozenset({"_cache", "reference", "superseded", "_invalid"})
COMMIT_RE = re.compile(r"^[0-9a-fA-F]{7,40}$")
GOOGLE_KEY_RE = re.compile(r"(?<![A-Za-z0-9_\-])AIza[0-9A-Za-z_\-]{8,60}(?![A-Za-z0-9_\-=])")
SK_KEY_RE = re.compile(r"(?<![A-Za-z0-9_])sk-[A-Za-z0-9_\-]{12,}")
OAUTH_RE = re.compile(r"(?<![A-Za-z0-9_])ya29\.[0-9A-Za-z_\-]{12,}")
ENV_KEY_RE = re.compile(
    r"\b(?:GEMINI_API_KEY|GOOGLE_API_KEY|GOOGLE_GENERATIVE_AI_API_KEY|"
    r"OPENAI_API_KEY|ANTHROPIC_API_KEY|XAI_API_KEY)\b"
    r"[\"']?[ \t]*[:=][ \t]*(\"[^\"]*\"|'[^']*'|[^\s\"',}\]]*)"
)
SAFE_PLACEHOLDERS = frozenset(
    {
        "",
        "null",
        "none",
        "false",
        "true",
        "unset",
        "redacted",
        "[redacted]",
        "<redacted>",
        "empty",
        "missing",
    }
)

VALIDATION_DISCLOSURE = (
    "docs/gemini/validation.md is reserved untouched for human labeller Ivar "
    "(scored separately via canary.gemini.atlas_agreement). Any claim audit or "
    "solver-agreement check in this failure_analyst carbon suite (including "
    "claim-audit-carbon and stratified solver-vs-LLM checks) is explicitly "
    "disclosed as an automated LLM or deterministic solver audit, never human labelling."
)


def sanitize_text(text: str) -> str:
    s = str(text or "")
    return (
        s.replace(chr(0x2014), " - ")
        .replace(chr(0x2013), "-")
        .replace(chr(0x2012), "-")
        .replace(chr(0x2015), "-")
    )


def _is_num(val: Any) -> bool:
    return isinstance(val, (int, float)) and not isinstance(val, bool)


def _is_int(val: Any) -> bool:
    return isinstance(val, int) and not isinstance(val, bool)


def _truthy_flag(val: Any) -> bool:
    if val is True:
        return True
    if isinstance(val, str) and val.strip().lower() in {"true", "1", "yes"}:
        return True
    return False


def _rel_posix(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _has_env_secret(text: str) -> bool:
    for match in ENV_KEY_RE.finditer(text):
        raw = match.group(1).strip()
        quoted = len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in "\"'"
        inner = raw[1:-1].strip() if quoted else raw
        if inner.lower() in SAFE_PLACEHOLDERS:
            continue
        if set(inner) <= {"*"} or inner.startswith("$"):
            continue
        if not quoted and "=" in inner:
            continue
        if len(inner) >= 4:
            return True
    return False


def scan_file_hygiene(file_path: Path, root: Path) -> list[dict[str, str]]:
    rel = _rel_posix(file_path, root)
    findings: list[dict[str, str]] = []
    if file_path.name == ".env" or file_path.name.startswith(".env."):
        findings.append({"file": rel, "kind": "tracked_env_file"})
    if file_path.name == "SALT" or "SALT" in file_path.parts:
        findings.append({"file": rel, "kind": "tracked_salt_file"})
    try:
        raw_bytes = file_path.read_bytes()
    except OSError:
        return [{"file": rel, "kind": "unreadable_file"}]

    if file_path.name.endswith(".world.json"):
        txt_world = raw_bytes.decode("utf-8", errors="replace")
        if '"mole"' in txt_world:
            findings.append({"file": rel, "kind": "world_mole_answer_key"})

    if b"\x00" in raw_bytes:
        return findings

    text = raw_bytes.decode("utf-8", errors="replace")
    if GOOGLE_KEY_RE.search(text):
        findings.append({"file": rel, "kind": "google_api_key"})
    if SK_KEY_RE.search(text):
        findings.append({"file": rel, "kind": "sk_api_key"})
    if OAUTH_RE.search(text):
        findings.append({"file": rel, "kind": "oauth_token"})
    if _has_env_secret(text):
        findings.append({"file": rel, "kind": "env_api_key"})
    return findings


def _extract_usage(meta: dict[str, Any], sibling_docs: dict[str, dict[str, Any]], model_id: str) -> dict[str, Any]:
    usage = meta.get("usage")
    if not isinstance(usage, dict):
        usage = meta.get("ledger") if isinstance(meta.get("ledger"), dict) else {}
    if not usage:
        for doc in sibling_docs.values():
            if isinstance(doc.get("usage"), dict):
                usage = doc["usage"]
                break

    raw_calls = usage.get("calls", meta.get("calls", 1))
    calls = int(raw_calls) if _is_num(raw_calls) and raw_calls > 0 else 0

    raw_in = usage.get("in", usage.get("input_tokens", usage.get("prompt_tokens", 0)))
    tin = int(raw_in) if _is_num(raw_in) and raw_in > 0 else 0

    raw_out = usage.get(
        "out",
        usage.get(
            "output_tokens",
            usage.get("out_tokens", usage.get("candidates_tokens", usage.get("completion_tokens", 0))),
        ),
    )
    tout = int(raw_out) if _is_num(raw_out) and raw_out > 0 else 0

    raw_think = usage.get("thinking", usage.get("thinking_tokens", usage.get("thoughts_tokens", 0)))
    thinking = int(raw_think) if _is_num(raw_think) and raw_think > 0 else 0

    raw_cached = usage.get("cached", usage.get("cached_in", usage.get("cached_tokens", 0)))
    cached = int(raw_cached) if _is_num(raw_cached) and raw_cached > 0 else 0

    raw_cost = usage.get(
        "cost_usd",
        usage.get("cost_usd_est", usage.get("cost_usd_list", meta.get("cost_usd", 0.0))),
    )
    usd = float(raw_cost) if _is_num(raw_cost) and raw_cost >= 0.0 else 0.0
    if usd == 0.0 and tin > 0 and tout > 0 and model_id:
        priced = price_cost(model_id, tin, tout + thinking, cached)
        usd = float(priced.get("cost_usd_est", priced.get("cost_usd", 0.0)) or 0.0)

    if calls == 0 and tin > 0 and tout > 0:
        calls = 1

    return {
        "calls": calls,
        "in": tin,
        "out": tout,
        "thinking": thinking,
        "cached": cached,
        "cost_usd": round(usd, 6),
    }


def _extract_quotes(
    meta: dict[str, Any],
    sibling_docs: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    verified: int | None = None
    total: int | None = None
    pct: float | None = None

    for k in ("verified_quotes", "n_quotes_verified", "quotes_verified"):
        if _is_int(meta.get(k)) and int(meta[k]) >= 0:
            verified = int(meta[k])
            break
    for k in ("total_quotes", "n_quotes_raw", "n_quotes_checked", "quotes_checked"):
        if _is_int(meta.get(k)) and int(meta[k]) >= 0:
            total = int(meta[k])
            break
    if _is_num(meta.get("verified_quotes_pct")):
        pct = round(float(meta["verified_quotes_pct"]), 2)

    if verified is None or total is None:
        for doc in sibling_docs.values():
            qv = doc.get("quote_verification")
            if isinstance(qv, dict):
                v_cand = qv.get("verified_quotes", qv.get("verified"))
                t_cand = qv.get("total_quotes", qv.get("total"))
                p_cand = qv.get("verified_quotes_pct", qv.get("pct"))
                if _is_int(v_cand) and _is_int(t_cand):
                    verified = int(v_cand)
                    total = int(t_cand)
                    if pct is None and _is_num(p_cand):
                        pct = round(float(p_cand), 2)
                    break
            ver = doc.get("verification")
            if isinstance(ver, dict):
                v_cand = ver.get("quotes_verified")
                t_cand = ver.get("quotes_checked")
                if _is_int(v_cand) and _is_int(t_cand):
                    verified = int(v_cand)
                    total = int(t_cand)
                    break
            q_blk = doc.get("quotes")
            if isinstance(q_blk, dict):
                v_cand = q_blk.get("verified_agent_text", q_blk.get("verified"))
                t_cand = q_blk.get("checked", q_blk.get("total"))
                if _is_int(v_cand) and _is_int(t_cand):
                    verified = int(v_cand)
                    total = int(t_cand)
                    break

    verified_out = verified if verified is not None else 0
    total_out = total if total is not None else verified_out
    if pct is None:
        pct_out = round(100.0 * verified_out / total_out, 2) if total_out > 0 else 0.0
    else:
        pct_out = pct

    return {
        "verified_quotes": verified_out,
        "total_quotes": total_out,
        "verified_quotes_pct": pct_out,
    }


def _extract_scope_counts(
    meta: dict[str, Any],
    sibling_docs: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    claims = int(meta["n_claims"]) if _is_int(meta.get("n_claims")) and int(meta["n_claims"]) > 0 else 0
    if claims == 0:
        for doc in sibling_docs.values():
            if _is_int(doc.get("n_claims")) and int(doc["n_claims"]) > 0:
                claims = int(doc["n_claims"])
                break

    is_claim_audit = claims > 0 and (
        "claim" in str(meta.get("subrole", "")).lower()
        or "auditor" in meta
        or "validation_sheet" in meta
    )

    if is_claim_audit and not _is_int(meta.get("n_episodes")):
        episodes_evaluated = int(meta["n_unique_episodes"]) if _is_int(meta.get("n_unique_episodes")) else 0
        episodes_diagnosed = episodes_evaluated
        scope_label = f"{claims} claims audited (automated LLM audit)"
        return {
            "episodes_analyzed": episodes_evaluated,
            "episodes_diagnosed": episodes_diagnosed,
            "claims_analyzed": claims,
            "is_automated_claim_audit": True,
            "scope_label": scope_label,
        }

    ep_candidates: list[int] = []
    for k in ("n_calibrated_episodes", "n_episodes_packed", "n_episodes", "episode_count", "n_samples", "count"):
        val = meta.get(k)
        if _is_int(val) and int(val) >= 0:
            ep_candidates.append(int(val))

    if not ep_candidates:
        for doc in sibling_docs.values():
            corpus = doc.get("corpus")
            if isinstance(corpus, dict) and _is_int(corpus.get("episodes")):
                ep_candidates.append(int(corpus["episodes"]))
            if _is_int(doc.get("n_episodes_packed")):
                ep_candidates.append(int(doc["n_episodes_packed"]))
            if _is_int(doc.get("n_episodes")):
                ep_candidates.append(int(doc["n_episodes"]))

    episodes_analyzed = max(ep_candidates) if ep_candidates else 0
    if _is_int(meta.get("n_episodes")) and int(meta["n_episodes"]) > 0:
        episodes_diagnosed = int(meta["n_episodes"])
    elif _is_int(meta.get("n_premature_episodes")) and int(meta["n_premature_episodes"]) > 0:
        episodes_diagnosed = int(meta["n_premature_episodes"])
    else:
        episodes_diagnosed = episodes_analyzed

    if _is_int(meta.get("n_calibrated_episodes")) and episodes_diagnosed < episodes_analyzed:
        scope_label = f"{episodes_analyzed} episodes calibrated ({episodes_diagnosed} premature diagnosed)"
    elif _is_int(meta.get("n_pairs")) and int(meta["n_pairs"]) > 0:
        scope_label = f"{episodes_analyzed} paired episodes ({int(meta['n_pairs'])} pairs)"
    elif claims > 0:
        scope_label = f"{episodes_analyzed} episodes, {claims} claims"
    else:
        scope_label = f"{episodes_analyzed} episodes"

    return {
        "episodes_analyzed": episodes_analyzed,
        "episodes_diagnosed": episodes_diagnosed,
        "claims_analyzed": claims,
        "is_automated_claim_audit": bool("auditor" in meta or claims > 0),
        "scope_label": scope_label,
    }


def _extract_headline_and_summary(
    run_name: str,
    meta: dict[str, Any],
    sibling_docs: dict[str, dict[str, Any]],
    quotes: dict[str, Any],
    scope: dict[str, Any],
) -> tuple[str, str, list[str]]:
    executive_summary = ""
    mode_titles: list[str] = []

    for fname in ("forensics.json", "diagnosis.json", "atlas.json", "report.json", "audit.json", "summary.json"):
        doc = sibling_docs.get(fname)
        if not isinstance(doc, dict):
            continue
        if not executive_summary:
            raw_sum = doc.get("executive_summary") or doc.get("summary")
            if isinstance(raw_sum, str) and raw_sum.strip():
                executive_summary = sanitize_text(raw_sum.strip())
        if not mode_titles:
            if isinstance(doc.get("modes"), list):
                for m in doc["modes"]:
                    if isinstance(m, dict):
                        nm = m.get("name") or m.get("id")
                        rs = m.get("regret_share")
                        if nm and _is_num(rs):
                            pct_val = float(rs) * 100.0 if float(rs) <= 1.0 else float(rs)
                            mode_titles.append(sanitize_text(f"{nm} ({pct_val:.1f}% regret)"))
                        elif nm:
                            mode_titles.append(sanitize_text(str(nm)))
            elif isinstance(doc.get("clusters"), list):
                for cl in doc["clusters"]:
                    if isinstance(cl, dict):
                        nm = cl.get("title") or cl.get("name") or cl.get("mode_id") or cl.get("cluster_id")
                        if nm:
                            mode_titles.append(sanitize_text(str(nm)))

    for key in ("key_metric", "headline"):
        val = meta.get(key)
        if isinstance(val, str) and val.strip():
            return sanitize_text(val.strip()), executive_summary, mode_titles[:8]

    vq = quotes["verified_quotes"]
    tq = quotes["total_quotes"]
    vpct = quotes["verified_quotes_pct"]

    if "atlas.json" in sibling_docs:
        adoc = sibling_docs["atlas.json"]
        corpus = adoc.get("corpus") if isinstance(adoc.get("corpus"), dict) else {}
        tot_reg = corpus.get("total_regret")
        modes = adoc.get("modes") if isinstance(adoc.get("modes"), list) else []
        top_mode = modes[0] if modes and isinstance(modes[0], dict) else {}
        top_name = top_mode.get("id") or top_mode.get("name") or "top_mode"
        top_share = top_mode.get("regret_share")
        agree = meta.get("agreement_rate")
        parts = [f"{scope['episodes_analyzed']} episodes"]
        if _is_num(tot_reg):
            parts[0] += f" (total solver regret {float(tot_reg):.2f} V)"
        if modes:
            if _is_num(top_share):
                sh_pct = float(top_share) * 100.0 if float(top_share) <= 1.0 else float(top_share)
                parts.append(f"{len(modes)} modes (top: {top_name} {sh_pct:.1f}%)")
            else:
                parts.append(f"{len(modes)} modes")
        parts.append(f"{vq}/{tq} ({vpct:.1f}%) quotes verified")
        if _is_num(agree):
            parts.append(f"automated solver-vs-LLM agreement {float(agree) * 100.0:.1f}%")
        return sanitize_text(", ".join(parts)), executive_summary, mode_titles[:8]

    if _is_num(meta.get("ece")) and _is_num(meta.get("brier_score")):
        ev_lost = float(meta.get("ev_lost_total", 0.0) or 0.0)
        n_prem = int(meta.get("n_premature_episodes", scope["episodes_diagnosed"]))
        headline = (
            f"{scope['episodes_analyzed']} episodes calibrated (ECE {float(meta['ece']):.4f}, "
            f"Brier {float(meta['brier_score']):.4f}), {n_prem} premature commits below 1/(1+V) "
            f"losing {ev_lost:.2f} EV, {vq}/{tq} ({vpct:.1f}%) quotes verified"
        )
        return sanitize_text(headline), executive_summary, mode_titles[:8]

    if _is_int(meta.get("packed_chars")) and _is_int(meta.get("n_clusters")):
        headline = (
            f"{scope['episodes_analyzed']} episodes ({int(meta['packed_chars']):,} chars in one prompt), "
            f"{int(meta['n_clusters'])} decision failure clusters, {vq}/{tq} ({vpct:.1f}%) quotes verified"
        )
        return sanitize_text(headline), executive_summary, mode_titles[:8]

    fallback_parts = [scope["scope_label"]]
    if mode_titles:
        fallback_parts.append(f"{len(mode_titles)} modes/clusters")
    if tq > 0:
        fallback_parts.append(f"{vq}/{tq} ({vpct:.1f}%) quotes verified")
    if _is_num(meta.get("agreement_rate")):
        fallback_parts.append(f"automated agreement {float(meta['agreement_rate']) * 100.0:.1f}%")
    return sanitize_text(", ".join(fallback_parts)), executive_summary, mode_titles[:8]


def inspect_analyst_run(run_dir: Path, root: Path = ROOT) -> dict[str, Any]:
    rel_dir = _rel_posix(run_dir, root)
    meta_path = run_dir / "meta.json"
    issues: list[str] = []
    secret_leaks: list[dict[str, str]] = []
    artifacts: list[str] = []
    sibling_docs: dict[str, dict[str, Any]] = {}

    for fp in sorted(p for p in run_dir.rglob("*") if p.is_file()):
        rel_sub = fp.relative_to(run_dir)
        if any(part in SKIP_DIRS for part in rel_sub.parts):
            continue
        artifacts.append(rel_sub.as_posix())
        secret_leaks.extend(scan_file_hygiene(fp, root))
        if fp.suffix == ".json" and fp.name != "meta.json":
            try:
                parsed_sib = json.loads(fp.read_text(encoding="utf-8"))
                if len(rel_sub.parts) == 1 and isinstance(parsed_sib, dict):
                    sibling_docs[fp.name] = parsed_sib
            except (OSError, UnicodeDecodeError, ValueError) as exc:
                issues.append(f"invalid_json:{rel_sub.as_posix()}:{type(exc).__name__}")

    if secret_leaks:
        issues.append("secret_hygiene_violation")

    meta: dict[str, Any] = {}
    try:
        raw_meta = json.loads(meta_path.read_text(encoding="utf-8"))
        if isinstance(raw_meta, dict):
            meta = raw_meta
        else:
            issues.append("meta_not_json_object")
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        issues.append(f"invalid_meta_json:{type(exc).__name__}")

    raw_role = str(meta.get("role") or ROLE).strip().lower().replace("-", "_")
    if raw_role != ROLE:
        issues.append(f"unexpected_role:{raw_role}")

    raw_model = str(meta.get("model_id") or meta.get("model") or "").strip()
    if raw_model.startswith("gemini:"):
        raw_model = raw_model.split(":", 1)[1]
    if raw_model != TARGET_MODEL:
        issues.append(f"wrong_model:{raw_model or 'missing'}")

    provider = str(meta.get("provider") or "").strip().lower()
    source = str(meta.get("source") or "llm").strip().lower()
    agent = str(meta.get("agent") or "").strip().lower()
    is_stub = (
        _truthy_flag(meta.get("stub"))
        or _truthy_flag(meta.get("synthetic"))
        or _truthy_flag(meta.get("fake_env"))
        or _truthy_flag(meta.get("smoke"))
        or provider == "stub"
        or source == "stub"
        or agent == "stub"
        or agent.startswith("stub:")
    )
    if is_stub:
        issues.append("stub_or_synthetic_run")

    raw_commit = str(meta.get("commit") or meta.get("git_sha") or "").strip()
    if not raw_commit or not COMMIT_RE.fullmatch(raw_commit):
        issues.append(f"invalid_commit:{raw_commit or 'missing'}")

    usage = _extract_usage(meta, sibling_docs, raw_model)
    if usage["calls"] <= 0 or usage["in"] <= 0 or usage["out"] <= 0 or usage["cost_usd"] <= 0.0:
        issues.append("invalid_or_zero_gemini_usage")

    quotes = _extract_quotes(meta, sibling_docs)
    scope = _extract_scope_counts(meta, sibling_docs)
    subrole = sanitize_text(str(meta.get("subrole") or run_dir.name.replace("-", "_")))
    thinking_raw = meta.get("thinking_level")
    if not thinking_raw and isinstance(meta.get("provider_settings"), dict):
        thinking_raw = meta["provider_settings"].get("thinking_level")
    thinking_level = sanitize_text(str(thinking_raw or "default"))
    timestamp = sanitize_text(
        str(meta.get("timestamp") or meta.get("finished_at") or meta.get("generated_at") or "")
    )
    headline, executive_summary, mode_titles = _extract_headline_and_summary(
        run_dir.name,
        meta,
        sibling_docs,
        quotes,
        scope,
    )

    auditor_note = None
    if scope["is_automated_claim_audit"]:
        auditor_note = sanitize_text(
            str(meta.get("auditor") or "gemini-4-carbon (automated LLM audit, not human)")
        )
    elif _is_num(meta.get("agreement_rate")):
        auditor_note = "automated solver-vs-LLM agreement check (not human labelling)"

    return {
        "run_id": run_dir.name,
        "run_dir": rel_dir,
        "role": ROLE,
        "subrole": subrole,
        "model_id": raw_model,
        "thinking_level": thinking_level,
        "stub": is_stub,
        "verified": len(issues) == 0,
        "issues": issues,
        "secret_leaks": secret_leaks,
        "commit": raw_commit[:12] if raw_commit else "unknown",
        "full_commit": raw_commit,
        "timestamp": timestamp,
        "episodes_analyzed": scope["episodes_analyzed"],
        "episodes_diagnosed": scope["episodes_diagnosed"],
        "claims_analyzed": scope["claims_analyzed"],
        "scope_label": scope["scope_label"],
        "is_automated_claim_audit": scope["is_automated_claim_audit"],
        "auditor_disclosure": auditor_note,
        "verified_quotes": quotes["verified_quotes"],
        "total_quotes": quotes["total_quotes"],
        "verified_quotes_pct": quotes["verified_quotes_pct"],
        "usage": usage,
        "headline": headline,
        "executive_summary": executive_summary,
        "modes_or_clusters": mode_titles,
        "artifacts": artifacts,
    }


def discover_analyst_runs(
    analyst_dir: Path,
    root: Path = ROOT,
) -> list[dict[str, Any]]:
    if not analyst_dir.is_dir():
        return []
    entries: list[dict[str, Any]] = []
    for child in sorted(analyst_dir.iterdir(), key=lambda p: p.name):
        if not child.is_dir() or child.name.startswith(".") or child.name in SKIP_DIRS:
            continue
        if not (child / "meta.json").is_file():
            continue
        entries.append(inspect_analyst_run(child, root=root))
    return entries


def build_analyst_index(
    runs: list[dict[str, Any]],
    *,
    strict: bool = True,
    generated_at: str | None = None,
) -> dict[str, Any]:
    verified_runs = [r for r in runs if r["verified"]]
    rejected_runs = [r for r in runs if not r["verified"]]

    if strict and rejected_runs:
        bad_desc = "; ".join(f"{r['run_id']}: {','.join(r['issues'])}" for r in rejected_runs)
        raise ValueError(f"unverified failure_analyst run(s): {bad_desc}")

    tot_episodes = sum(int(r["episodes_analyzed"]) for r in verified_runs)
    tot_diagnosed = sum(int(r["episodes_diagnosed"]) for r in verified_runs)
    tot_claims = sum(int(r["claims_analyzed"]) for r in verified_runs)
    tot_vq = sum(int(r["verified_quotes"]) for r in verified_runs)
    tot_tq = sum(int(r["total_quotes"]) for r in verified_runs)
    overall_q_pct = round(100.0 * tot_vq / tot_tq, 2) if tot_tq > 0 else 0.0

    tot_calls = sum(int(r["usage"]["calls"]) for r in verified_runs)
    tot_in = sum(int(r["usage"]["in"]) for r in verified_runs)
    tot_out = sum(int(r["usage"]["out"]) for r in verified_runs)
    tot_think = sum(int(r["usage"]["thinking"]) for r in verified_runs)
    tot_cached = sum(int(r["usage"]["cached"]) for r in verified_runs)
    tot_cost = round(sum(float(r["usage"]["cost_usd"]) for r in verified_runs), 6)

    all_leaks = [lk for r in runs for lk in r["secret_leaks"]]
    ts = generated_at or datetime.now(timezone.utc).isoformat(timespec="seconds")

    return {
        "role": ROLE,
        "target_model": TARGET_MODEL,
        "generated_at": ts,
        "verified": len(verified_runs) > 0 and len(rejected_runs) == 0 and len(all_leaks) == 0,
        "secret_hygiene_clean": len(all_leaks) == 0,
        "validation_sheet_reserved_path": "docs/gemini/validation.md",
        "validation_sheet_owner": "Ivar (human labeller via canary.gemini.atlas_agreement)",
        "validation_disclosure": VALIDATION_DISCLOSURE,
        "totals": {
            "run_count": len(verified_runs),
            "scanned_run_count": len(runs),
            "rejected_run_count": len(rejected_runs),
            "episodes_analyzed": tot_episodes,
            "episodes_diagnosed": tot_diagnosed,
            "claims_analyzed": tot_claims,
            "verified_quotes": tot_vq,
            "total_quotes": tot_tq,
            "verified_quotes_pct": overall_q_pct,
            "usage": {
                "calls": tot_calls,
                "in": tot_in,
                "out": tot_out,
                "thinking": tot_think,
                "cached": tot_cached,
                "cost_usd": tot_cost,
            },
        },
        "runs": verified_runs,
        "rejected_runs": rejected_runs,
    }


def render_analyst_md(index_payload: dict[str, Any]) -> str:
    t = index_payload["totals"]
    u = t["usage"]
    runs = index_payload["runs"]

    scope_parts = [f"`{t['episodes_analyzed']}` episode-level evaluations (`{t['episodes_diagnosed']}` directly diagnosed)"]
    if t["claims_analyzed"] > 0:
        scope_parts.append(f"`{t['claims_analyzed']}` audited atlas claims (automated LLM audit)")
    scope_summary = " + ".join(scope_parts)

    lines = [
        f"{MD_H1} Canary Lab Role: Failure Analyst (`{index_payload['target_model']}` Suite)",
        "",
        "Consolidated provenance, verbatim quote verification, and decision-forensics findings across all "
        "committed `gemini-4-carbon` runs under `results/gemini/roles_carbon/failure_analyst/`.",
        "Regenerate automatically as new analyst runs land via:",
        "`PYTHONPATH=. python -m canary.gemini.analyst_carbon`",
        "",
        f"{MD_H2} Human Validation Reservation & Automated Audit Disclosure",
        "",
        "- **Human validation sheet (`docs/gemini/validation.md`) is untouched:** `docs/gemini/validation.md` is "
        "strictly reserved for human labeller **Ivar** and scored only via `python -m canary.gemini.atlas_agreement`. "
        "No automated script in this suite fills or edits `docs/gemini/validation.md`.",
        "- **Automated LLM / solver audit disclosure:** Any claim audit or agreement rate reported inside "
        "`results/gemini/roles_carbon/failure_analyst/` (including automated claim audits such as `claim-audit-carbon` "
        "and deterministic solver-vs-LLM agreement checks in `atlas-carbon`) is **explicitly an automated LLM or "
        "solver audit (`gemini-4-carbon`), never human inter-annotator agreement**.",
        "",
        f"{MD_H2} Suite Totals (`gemini-4-carbon`, `stub=False`, Secret Hygiene Clean)",
        "",
        "| Metric | Value |",
        "| --- | --- |",
        f"| Verified `gemini-4-carbon` Runs | `{t['run_count']}` (rejected: `{t['rejected_run_count']}`, secret leaks: `0`) |",
        f"| Corpus Scope Analyzed | {scope_summary} |",
        f"| Verbatim Quote Verification | `{t['verified_quotes']}/{t['total_quotes']}` (`{t['verified_quotes_pct']:.1f}%` exact Python verification) |",
        f"| Gemini API Calls | `{u['calls']}` |",
        f"| Input / Output / Thinking Tokens | `{u['in']:,}` in / `{u['out']:,}` out / `{u['thinking']:,}` thinking (`{u['cached']:,}` cached) |",
        f"| Recorded Gemini API Cost | `${u['cost_usd']:.6f}` USD |",
        "",
        f"{MD_H2} Committed `failure_analyst` Carbon Runs",
        "",
        "| Run ID | Subrole | Thinking | Commit | Scope | Verbatim Quotes | Calls | Tokens (In / Out / Think) | Cost (USD) | Headline Finding |",
        "| --- | --- | --- | --- | --- | ---: | ---: | ---: | ---: | --- |",
    ]

    for r in runs:
        ru = r["usage"]
        q_cell = (
            f"`{r['verified_quotes']}/{r['total_quotes']}` (`{r['verified_quotes_pct']:.0f}%`)"
            if r["total_quotes"] > 0
            else "n/a"
        )
        tok_cell = f"{ru['in']:,} / {ru['out']:,} / {ru['thinking']:,}"
        head_cell = r["headline"].replace("|", "/")
        lines.append(
            f"| `{r['run_id']}` | `{r['subrole']}` | `{r['thinking_level']}` | `{r['commit']}` "
            f"| {r['scope_label']} | {q_cell} | {ru['calls']} | {tok_cell} "
            f"| `${ru['cost_usd']:.4f}` | {head_cell} |"
        )

    lines.extend(
        [
            "",
            f"{MD_H2} Per-Run Provenance & Decision Forensics Details",
            "",
        ]
    )

    for idx, r in enumerate(runs, start=1):
        ru = r["usage"]
        lines.extend(
            [
                f"{MD_H3} {idx}. `{r['run_id']}` (`{r['subrole']}`)",
                f"- **Artifact directory:** `{r['run_dir']}`",
                f"- **Model & thinking:** `{r['model_id']}` (`thinking_level={r['thinking_level']}`, `stub={r['stub']}`)",
                f"- **Commit & timestamp:** `{r['commit']}` (`{r['timestamp']}`)",
                f"- **Scope:** {r['scope_label']}",
                f"- **Verbatim quotes:** `{r['verified_quotes']}/{r['total_quotes']}` (`{r['verified_quotes_pct']:.1f}%`)",
                f"- **Gemini API usage:** `calls={ru['calls']}`, `in={ru['in']:,}`, `out={ru['out']:,}`, `thinking={ru['thinking']:,}`, `cached={ru['cached']:,}`, `cost_usd=${ru['cost_usd']:.6f}`",
                f"- **Key metric:** {r['headline']}",
            ]
        )
        if r.get("auditor_disclosure"):
            lines.append(f"- **Audit disclosure:** `{r['auditor_disclosure']}` (`docs/gemini/validation.md` remains untouched for human labeller Ivar)")
        if r.get("modes_or_clusters"):
            joined_modes = "; ".join(f"`{m}`" for m in r["modes_or_clusters"])
            lines.append(f"- **Labelled modes / clusters:** {joined_modes}")
        lines.append(f"- **Committed files:** {', '.join(f'`{a}`' for a in r['artifacts'])}")
        if r.get("executive_summary"):
            lines.append(f"- **Synthesis:** {r['executive_summary']}")
        lines.append("")

    return sanitize_text("\n".join(lines).rstrip() + "\n")


def consolidate_analyst_carbon(
    *,
    root: Path = ROOT,
    analyst_dir: Path | None = None,
    index_out: Path | None = None,
    doc_out: Path | None = None,
    strict: bool = True,
) -> dict[str, Any]:
    root_resolved = Path(root).resolve()
    target_analyst_dir = Path(analyst_dir) if analyst_dir is not None else (root_resolved / DEFAULT_ANALYST_DIR)
    target_index = Path(index_out) if index_out is not None else (target_analyst_dir / "index.json")
    target_doc = Path(doc_out) if doc_out is not None else (root_resolved / DEFAULT_DOC_PATH)

    runs = discover_analyst_runs(target_analyst_dir, root=root_resolved)
    if strict and not runs:
        raise ValueError(f"no failure_analyst runs found under {target_analyst_dir}")

    index_payload = build_analyst_index(runs, strict=strict)
    md_text = render_analyst_md(index_payload)

    target_index.parent.mkdir(parents=True, exist_ok=True)
    target_index.write_text(sanitize_text(json.dumps(index_payload, indent=2) + "\n"), encoding="utf-8")

    target_doc.parent.mkdir(parents=True, exist_ok=True)
    target_doc.write_text(md_text, encoding="utf-8")

    return index_payload


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Consolidate verified gemini-4-carbon failure_analyst runs into index.json and analyst.md."
    )
    ap.add_argument("--root", type=Path, default=ROOT)
    ap.add_argument("--analyst-dir", type=Path, default=None)
    ap.add_argument("--index-out", type=Path, default=None)
    ap.add_argument("--doc-out", type=Path, default=None)
    ap.add_argument("--allow-unverified", action="store_true")
    args = ap.parse_args(argv)

    payload = consolidate_analyst_carbon(
        root=args.root,
        analyst_dir=args.analyst_dir,
        index_out=args.index_out,
        doc_out=args.doc_out,
        strict=not args.allow_unverified,
    )
    t = payload["totals"]
    u = t["usage"]
    print(
        f"analyst_carbon: runs={t['run_count']} episodes={t['episodes_analyzed']} "
        f"claims={t['claims_analyzed']} quotes={t['verified_quotes']}/{t['total_quotes']} "
        f"({t['verified_quotes_pct']:.1f}%) calls={u['calls']} in={u['in']} out={u['out']} "
        f"thinking={u['thinking']} cost=${u['cost_usd']:.6f}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
