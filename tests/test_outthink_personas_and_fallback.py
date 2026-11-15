from __future__ import annotations

import ast
from collections import defaultdict
import copy
from dataclasses import asdict
import gzip
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import tokenize

import pytest

from canary.agents.world_builder import (
    TRUTH_KEYS,
    TRUTH_WORDS,
    GeminiWorldText,
    assert_no_truth,
)
from canary.env import Env
from canary.gemini import outthink_personas as op
from canary.rules import tier_params_for_episode
from canary.solver.policy import SolverPolicy
from canary.text.lint import lint_messages, lint_text
from canary.types import Step
from canary.world import HELDOUT_SEEDS, JUDGE_SEEDS

ROOT = Path(__file__).resolve().parents[1]
DEMO_DIR = ROOT / "demo" / "out-think-gemini"
ENGINE_PATH = DEMO_DIR / "engine.js"
PERSONAS_JS_PATH = DEMO_DIR / "personas.js"
FALLBACK_JS_PATH = DEMO_DIR / "fallback_cases.js"
MODULE_PATH = ROOT / "canary" / "gemini" / "outthink_personas.py"
LEDGER_GZ = ROOT / "results" / "gemini" / "ladder_ledger.jsonl.gz"
PROTECTED_PATHS_FILE = ROOT / ".github" / "protected-paths.txt"

EM_DASH = chr(0x2014)
EN_DASH = chr(0x2013)
FIG_DASH = chr(0x2012)
HORIZ_BAR = chr(0x2015)
HASH_CHAR = chr(35)
SLASH = chr(47)
STAR = chr(42)
LT_CHAR = chr(60)
BANG_CHAR = chr(33)
LINE_COMMENT = SLASH + SLASH
BLOCK_COMMENT_OPEN = SLASH + STAR
HTML_COMMENT_OPEN = LT_CHAR + BANG_CHAR + "--"
FETCH_CALL = "fet" + "ch("
XHR_TOKEN = "XML" + "HttpRequest"

EXPECTED_WORLD_KEYS = [
    "hard:1",
    "hard:3",
    "hard:4",
    "hard:7",
    "hard:18",
    "medium:1",
    "medium:2",
    "medium:4",
    "medium:6",
    "medium:8",
    "medium:9",
]

EXPECTED_CASE_IDS = [
    "carbon-hard-1",
    "flash-lite-hard-4",
    "flash38-hard-7",
    "carbon-medium-4",
    "flash-lite-medium-1",
    "hydrogen-hard-3",
    "flash38-medium-9",
    "flash35-hard-1",
    "argon-hard-18",
    "argon-medium-6",
    "hydrogen-medium-2",
    "flash35-medium-8",
]


def _resolve_js_cmd() -> tuple[list[str], dict[str, str]]:
    clean_env = {
        k: v
        for k, v in os.environ.items()
        if k not in {"GEMINI_API_KEY", "GOOGLE_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY"}
    }
    for binary in ("node", "nodejs", "bun"):
        found = shutil.which(binary)
        if found:
            return [found, "-e"], clean_env
    for cand in (
        shutil.which("opencode"),
        str(Path.home() / "momin" / "bin" / "opencode"),
        str(Path.home() / ".opencode" / "bin" / "opencode"),
        str(Path.home() / ".local" / "bin" / "opencode"),
    ):
        if cand and Path(cand).is_file() and os.access(cand, os.X_OK):
            bun_env = dict(clean_env)
            bun_env["BUN_BE_BUN"] = "1"
            return [cand, "-e"], bun_env
    pytest.skip("no JavaScript runtime available")


def _run_js(js_body: str, payload: dict | list | None = None) -> dict:
    cmd_prefix, env = _resolve_js_cmd()
    run_env = dict(env)
    run_env["OUTTHINK_ENGINE_PATH"] = str(ENGINE_PATH)
    run_env["OUTTHINK_PERSONAS_PATH"] = str(PERSONAS_JS_PATH)
    run_env["OUTTHINK_FALLBACK_PATH"] = str(FALLBACK_JS_PATH)
    run_env["OUTTHINK_TEST_PAYLOAD"] = json.dumps(payload if payload is not None else {})
    wrapper = (
        "globalThis.window = globalThis.window || {};\n"
        "const PAYLOAD = JSON.parse(process.env.OUTTHINK_TEST_PAYLOAD);\n"
        "const out = (() => {\n"
        + js_body
        + "\n})();\n"
        "process.stdout.write(JSON.stringify(out));\n"
    )
    proc = subprocess.run(
        [*cmd_prefix, wrapper],
        cwd=ROOT,
        env=run_env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert proc.returncode == 0, f"JS runtime failed:\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
    return json.loads(proc.stdout)


def _find_js_comments(source: str) -> list[tuple[int, str]]:
    hits: list[tuple[int, str]] = []
    n = len(source)
    i = 0
    line = 1
    in_quote: str | None = None
    in_regex = False
    in_regex_class = False
    prev_sig = "("

    while i < n:
        ch = source[i]
        if in_quote is not None:
            if ch == "\\":
                if i + 1 < n and source[i + 1] == "\n":
                    line += 1
                i += 2
                continue
            if ch == "\n":
                line += 1
            elif ch == in_quote:
                in_quote = None
                prev_sig = '"'
            i += 1
            continue

        if in_regex:
            if ch == "\\":
                i += 2
                continue
            if ch == "\n":
                in_regex = False
                in_regex_class = False
                line += 1
                i += 1
                continue
            if ch == "[" and not in_regex_class:
                in_regex_class = True
            elif ch == "]" and in_regex_class:
                in_regex_class = False
            elif ch == SLASH and not in_regex_class:
                in_regex = False
                prev_sig = SLASH
            i += 1
            continue

        if ch in ("'", '"', "`"):
            in_quote = ch
            i += 1
            continue

        if ch == "\n":
            line += 1
            i += 1
            continue

        if ch.isspace():
            i += 1
            continue

        if ch == SLASH and i + 1 < n:
            nxt = source[i + 1]
            if nxt == SLASH:
                hits.append((line, LINE_COMMENT))
                i += 2
                while i < n and source[i] != "\n":
                    i += 1
                continue
            if nxt == STAR:
                hits.append((line, BLOCK_COMMENT_OPEN))
                i += 2
                while i < n:
                    if source[i] == "\n":
                        line += 1
                    if source[i] == STAR and i + 1 < n and source[i + 1] == SLASH:
                        i += 2
                        break
                    i += 1
                continue
            if prev_sig in " (,=:[!&|?{};+-*%<>^~":
                in_regex = True
                in_regex_class = False
                i += 1
                continue

        prev_sig = ch
        i += 1

    return hits


def _load_protected_rules() -> list[str]:
    assert PROTECTED_PATHS_FILE.is_file()
    rules: list[str] = []
    for raw_line in PROTECTED_PATHS_FILE.read_text(encoding="utf-8").splitlines():
        stripped = raw_line.strip()
        if not stripped or stripped.startswith(HASH_CHAR):
            continue
        rules.append(stripped)
    return rules


def _matches_protected_rule(rel_path: str, rules: list[str]) -> bool:
    for rule in rules:
        if rule.endswith(SLASH):
            if rel_path.startswith(rule):
                return True
        elif rel_path == rule:
            return True
    return False


def _run_solver_episode(env: Env) -> tuple[bool, float]:
    sp = SolverPolicy(None)
    sp.reset(env.tools_spec(), env.instruction())
    t_idx = 0
    while not env.done and t_idx < 400:
        tool_name, tool_args = sp.act(list(env.history))
        env.call(tool_name, tool_args)
        t_idx += 1
    res = env.result(sp.name)
    return bool(res.correct), float(res.score)


def test_cli_check_roundtrip_and_tamper_detection(tmp_path: Path, capsys):
    assert PERSONAS_JS_PATH.is_file()
    assert FALLBACK_JS_PATH.is_file()
    assert PERSONAS_JS_PATH.stat().st_size < 400_000
    assert FALLBACK_JS_PATH.stat().st_size < 400_000

    rc_ok = op.main(["--check"])
    out_ok = capsys.readouterr()
    assert rc_ok == 0, out_ok.err
    assert "OK: 11 worlds (320 personas) and 12 fallback cases verified." in out_ok.out

    tmp_personas = tmp_path / "personas.js"
    tmp_fallback = tmp_path / "fallback_cases.js"

    rc_missing = op.main(["--check", "--personas-out", str(tmp_personas), "--fallback-out", str(tmp_fallback)])
    err_missing = capsys.readouterr().err
    assert rc_missing != 0
    assert "missing" in err_missing

    rc_write = op.main(["--personas-out", str(tmp_personas), "--fallback-out", str(tmp_fallback)])
    out_write = capsys.readouterr().out
    assert rc_write == 0
    assert "Wrote" in out_write
    assert tmp_personas.read_text(encoding="utf-8") == PERSONAS_JS_PATH.read_text(encoding="utf-8")
    assert tmp_fallback.read_text(encoding="utf-8") == FALLBACK_JS_PATH.read_text(encoding="utf-8")

    orig_p = tmp_personas.read_text(encoding="utf-8")
    tmp_personas.write_text(orig_p.replace("OUTTHINK_PERSONAS", "OUTTHINK_PERSONAS_DRIFT", 1), encoding="utf-8")
    rc_p_drift = op.main(["--check", "--personas-out", str(tmp_personas), "--fallback-out", str(tmp_fallback)])
    assert rc_p_drift != 0
    assert "out of date" in capsys.readouterr().err

    tmp_personas.write_text(orig_p, encoding="utf-8")
    orig_f = tmp_fallback.read_text(encoding="utf-8")
    tmp_fallback.write_text(orig_f.replace("OUTTHINK_FALLBACK_DATA", "OUTTHINK_FALLBACK_DRIFT", 1), encoding="utf-8")
    rc_f_drift = op.main(["--check", "--personas-out", str(tmp_personas), "--fallback-out", str(tmp_fallback)])
    assert rc_f_drift != 0
    assert "out of date" in capsys.readouterr().err


def test_js_runtime_exports_helpers_and_engine_fallback_plus_persona_merge():
    py_personas = op.build_personas_payload()
    py_fallback = op.build_fallback_payload(py_personas)

    res = _run_js(
        """
        globalThis.window = {};
        delete globalThis.OUTTHINK_DATA;
        delete globalThis.OUTTHINK_FALLBACK_DATA;
        delete globalThis.OUTTHINK_PERSONAS;

        const FallbackMod = require(process.env.OUTTHINK_FALLBACK_PATH);
        const PersonasMod = require(process.env.OUTTHINK_PERSONAS_PATH);
        const Engine = require(process.env.OUTTHINK_ENGINE_PATH);

        const winDataUntouched = window.OUTTHINK_DATA === undefined;
        const fbSameRef = window.OUTTHINK_FALLBACK_DATA === FallbackMod;
        const fbCasesRef = window.OUTTHINK_FALLBACK_CASES === FallbackMod.cases;
        const perSameRef = window.OUTTHINK_PERSONAS === PersonasMod;

        const pDirect = window.getOutthinkPersona("hard", 1, "e00");
        const pPair = window.getOutthinkPersona("hard:1", "e00");
        const pTriple = window.getOutthinkPersona("hard:1:e00");
        const pByCase = window.getOutthinkPersona({
          caseId: "carbon-hard-1",
          suspectId: "e00",
          true_mole: "e33",
          secret: "NIGHTJAR_DROP_99"
        });
        const pWorld = window.getOutthinkPersona("medium:4");
        const pCaseWorld = window.getOutthinkPersona("carbon-medium-4");

        const fbLookupById = window.getOutthinkFallbackCase("argon-hard-18");
        const fbLookupByWorld = window.getOutthinkFallbackCase("hard", 18);
        const fbLookupByColon = window.getOutthinkFallbackCase("hard:18");

        const dsFallback = Engine.loadDataset();
        const sb = Engine.createScoreboard();
        for (let i = 0; i < dsFallback.cases.length; i += 1) {
          const c = dsFallback.cases[i];
          const call = c.solver.recommended_call === "accuse"
            ? { action: "accuse", suspectId: c.solver.top_suspect }
            : { action: "hold_fire" };
          const ev = Engine.evaluateCall(c, call);
          sb.record(c.id, ev, c);
        }
        const sbSummary = sb.getSummary();

        window.OUTTHINK_DATA = {
          meta: { title: "Primary Override Check", isBootstrapFallback: false },
          cases: [
            {
              id: "carbon-hard-1",
              tier: "hard",
              seed: 1,
              value_at_decision: 0.71,
              true_mole: "e33",
              suspects: [
                { id: "e00", name: "Kaisa Turunen", dept: "Engineering", role: "tech lead", persona_note: "inline note" }
              ]
            }
          ]
        };
        const dsPrimary = Engine.loadDataset();

        return {
          winDataUntouched,
          fbSameRef,
          fbCasesRef,
          perSameRef,
          pDirect,
          pEqPair: JSON.stringify(pDirect) === JSON.stringify(pPair),
          pEqTriple: JSON.stringify(pDirect) === JSON.stringify(pTriple),
          pEqByCase: JSON.stringify(pDirect) === JSON.stringify(pByCase),
          pWorldEqCase: JSON.stringify(pWorld) === JSON.stringify(pCaseWorld),
          fbLookupId: fbLookupById && fbLookupById.id,
          fbLookupEq: fbLookupById === fbLookupByWorld && fbLookupByWorld === fbLookupByColon,
          fbMeta: FallbackMod.meta,
          perMeta: PersonasMod.meta,
          perWorldKeys: Object.keys(PersonasMod.worlds),
          dsSource: dsFallback.source,
          dsIsFallback: dsFallback.isFallback,
          dsIsBoot: dsFallback.isBootstrapFallback,
          dsCount: dsFallback.count,
          dsCaseIds: dsFallback.cases.map(c => c.id),
          dsWorldPairs: dsFallback.cases.map(c => c.tier + ":" + String(c.seed)),
          firstSuspectNote: dsFallback.cases[0].suspects[0].persona_note,
          anyPosteriorLeakInNotes: dsFallback.cases.some(c =>
            c.suspects.some(s => String(s.persona_note || "").toLowerCase().indexOf("posterior") !== -1)
          ),
          sbSummary,
          priSource: dsPrimary.source,
          priIsFallback: dsPrimary.isFallback,
          priMergedNote: dsPrimary.cases[0].suspects[0].persona_note
        };
        """
    )

    assert res["winDataUntouched"] is True
    assert res["fbSameRef"] is True
    assert res["fbCasesRef"] is True
    assert res["perSameRef"] is True
    assert res["pEqPair"] is True
    assert res["pEqTriple"] is True
    assert res["pEqByCase"] is True
    assert res["pWorldEqCase"] is True
    assert res["fbLookupId"] == "argon-hard-18"
    assert res["fbLookupEq"] is True

    assert res["perWorldKeys"] == EXPECTED_WORLD_KEYS
    assert res["perMeta"]["world_count"] == 11
    assert res["perMeta"]["case_count"] == 12
    assert res["perMeta"]["persona_count"] == 320
    assert res["fbMeta"] == py_fallback["meta"]

    assert res["dsSource"] == "fallback"
    assert res["dsIsFallback"] is True
    assert res["dsIsBoot"] is False
    assert res["dsCount"] == 12
    assert res["dsCaseIds"] == EXPECTED_CASE_IDS
    assert sorted(set(res["dsWorldPairs"])) == sorted(EXPECTED_WORLD_KEYS)

    expected_e00_note = py_personas["worlds"]["hard:1"]["suspects"]["e00"]["persona_note"]
    assert res["firstSuspectNote"] == expected_e00_note
    assert res["anyPosteriorLeakInNotes"] is False

    sb = res["sbSummary"]
    assert sb["casesPlayed"] == 12
    assert sb["judge"]["optimalCount"] == 12
    assert set(sb["byLevel"].keys()) == {"minimal", "low", "medium", "high", "xhigh"}
    assert sum(b["count"] for b in sb["byLevel"].values()) == 39

    assert res["priSource"] == "data"
    assert res["priIsFallback"] is False
    assert res["priMergedNote"] == expected_e00_note


def test_personas_public_facts_invariance_non_leak_37_encodings_and_solver_parity():
    payload = op.build_personas_payload()
    assert op.validate_personas_payload(payload) == []
    assert len(op.SUPPORTED_ENCODINGS) == 37

    prov = payload["provenance"]
    assert prov["role"] == "world_text"
    assert prov["model_id"] == "gemini-4-carbon"
    assert prov["verified_folders"] == 16
    assert prov["calls"] == 1637
    assert prov["cost_usd"] == pytest.approx(22.728348)
    assert prov["personas"] == 648
    assert prov["worlds"] == 24
    assert prov["live_interviews"] == 120
    assert prov["signal_calibration_accuracy"] == pytest.approx(1.0)
    assert prov["encodings_scanned"] == 37
    assert prov["leaks_detected"] == 0

    b64_probe = op.scan_text_for_secret("payload QUxQSEFfU0VDUkVUXzk5 end", ["ALPHA_SECRET_99"])
    assert any(h["encoding"] == "base64" for h in b64_probe)

    for tier, seed in op.FROZEN_WORLDS:
        w_key = f"{tier}:{seed}"
        w_entry = payload["worlds"][w_key]
        env = Env(tier, seed)
        assert_no_truth(w_entry, env._world)

        pub = op.extract_public_world_facts(tier, seed)
        poisoned_a = dict(pub, mole="e00", decoy="e01", secret="OMEGA_DROP_1", mole_strategy="burst")
        poisoned_b = dict(pub, mole="e19", decoy="e07", secret="SIGMA_DROP_2", mole_strategy="quiet")
        assert op.build_world_personas(tier, seed, poisoned_a) == w_entry
        assert op.build_world_personas(tier, seed, poisoned_b) == w_entry

    parity_worlds = [("medium", 1), ("medium", 4), ("medium", 6), ("hard", 1), ("hard", 7)]
    for tier, seed in parity_worlds:
        w_entry = payload["worlds"][f"{tier}:{seed}"]
        wt_provider = GeminiWorldText(w_entry, name="gemini:gemini-4-carbon")
        env_persona = Env(tier, seed, text_provider=wt_provider)
        env_template = Env(tier, seed)

        search_res = env_persona.call("search_messages", {"query": "a", "day_from": 1, "day_to": 1})
        msgs = (search_res.data or {}).get("messages") or []
        assert lint_messages(msgs) == []
        for m in msgs:
            assert TRUTH_WORDS.search(str(m.get("snippet") or "")) is None

        iv_res = env_persona.call("interview", {"employee": "e00", "topic": "recent_documents"})
        ans_txt = str((iv_res.data or {}).get("answer") or "")
        assert ans_txt
        assert lint_text(ans_txt) == []
        assert TRUTH_WORDS.search(ans_txt) is None

        fresh_persona_env = Env(tier, seed, text_provider=GeminiWorldText(w_entry, name="gemini:gemini-4-carbon"))
        p_ok, p_score = _run_solver_episode(fresh_persona_env)
        t_ok, t_score = _run_solver_episode(env_template)
        assert p_ok == t_ok
        assert p_score == pytest.approx(t_score, abs=1e-6)


def test_fallback_cases_step_by_step_env_and_bayesian_solver_replay():
    payload = op.build_fallback_payload()
    assert op.validate_fallback_payload(payload) == []

    bad_copy = copy.deepcopy(payload)
    bad_copy["cases"][0]["true_mole"] = "e999"
    assert any("true_mole" in e for e in op.validate_fallback_payload(bad_copy))

    ledger_run_ids: set[str] = set()
    with gzip.open(LEDGER_GZ, "rt", encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                rid = json.loads(line).get("run_id")
                if rid:
                    ledger_run_ids.add(str(rid))

    cases = payload["cases"]
    assert [c["id"] for c in cases] == EXPECTED_CASE_IDS

    calls_seen: set[str] = set()
    levels_seen: set[str] = set()

    for c in cases:
        cid = c["id"]
        tier = c["tier"]
        seed = c["seed"]
        d_step = c["decision_step"]
        assert seed not in HELDOUT_SEEDS
        assert seed not in JUDGE_SEEDS
        assert d_step == len(c["tool_steps"]) > 0

        env = Env(tier, seed)
        sp = SolverPolicy(tier_params_for_episode(tier, []))
        canary_assignments: dict[str, dict[str, str]] = {}
        latest_feed: list[dict] = []
        seen_logs: set[tuple[int, str, str, bool]] = set()
        after_hours_by_emp: dict[str, int] = defaultdict(int)

        for idx, st in enumerate(c["tool_steps"]):
            assert st["t"] == idx
            assert st["day"] == env.day
            live_res = env.call(st["tool"], st["args"])
            sp._ingest(
                Step(
                    t=st["t"],
                    day=st["day"],
                    tool=st["tool"],
                    args=st["args"],
                    result=asdict(live_res),
                )
            )
            if not live_res.ok:
                continue
            data = live_res.data or {}
            if st["tool"] == "plant_canary":
                can_id = str(data.get("canary_id") or "")
                if can_id:
                    canary_assignments[can_id] = {
                        str(k): str(v) for k, v in (st["args"] or {}).get("assignment", {}).items()
                    }
            elif st["tool"] == "check_leak_feed":
                latest_feed = list(data.get("items") or [])
            elif st["tool"] == "read_access_logs":
                for lg in data.get("logs") or []:
                    lk_key = (
                        int(lg.get("day", st["day"])),
                        str(lg.get("employee") or ""),
                        str(lg.get("doc_id") or ""),
                        bool(lg.get("after_hours", False)),
                    )
                    if lk_key not in seen_logs and lk_key[1]:
                        seen_logs.add(lk_key)
                        if lk_key[3]:
                            after_hours_by_emp[lk_key[1]] += 1

        sp.seen = d_step
        sp.obs.leak_timing_known = sp.v_drops_reveal_leaks()
        live_post = sp.belief()

        assert c["true_mole"] == env._world.mole
        assert c["decision_day"] == env.day
        assert c["value_at_decision"] == pytest.approx(float(env.V), abs=1e-4)

        solver = c["solver"]
        calls_seen.add(solver["recommended_call"])
        assert sum(solver["posterior"].values()) == pytest.approx(1.0, abs=1e-3)
        for emp_id, live_p in live_post.items():
            assert solver["posterior"][emp_id] == pytest.approx(float(live_p), abs=1e-4), f"{cid}:{emp_id}"

        canary_hits_by_emp: dict[str, int] = defaultdict(int)
        for item in latest_feed:
            doc_id = str(item.get("doc_id") or "")
            l_var = str(item["variant"]) if item.get("variant") is not None else None
            if doc_id in canary_assignments and l_var is not None:
                for emp_id, assigned_var in canary_assignments[doc_id].items():
                    if assigned_var == l_var:
                        canary_hits_by_emp[emp_id] += 1

        for s in c["suspects"]:
            sid = s["id"]
            assert s["canary_hits"] == canary_hits_by_emp[sid]
            assert s["after_hours_count"] == after_hours_by_emp[sid]
            assert TRUTH_KEYS.isdisjoint(s.keys())

        for lv in c["thinking_levels"]:
            levels_seen.add(lv["thinking_level"])
            assert lv["run_id"] in ledger_run_ids
            assert lv["cost_usd"] > 0.0
            assert lv["analyst_quote"]

        assert len(c["cross_model_carbon"]) >= 1

    assert calls_seen == {"accuse", "hold_fire"}
    assert levels_seen == {"minimal", "low", "medium", "high", "xhigh"}


def test_strict_hygiene_zero_comments_zero_dashes_zero_api_and_protected_paths():
    self_path = Path(__file__).resolve()
    targets = (MODULE_PATH, PERSONAS_JS_PATH, FALLBACK_JS_PATH, self_path)

    for target in targets:
        assert target.is_file(), f"missing {target}"
        src = target.read_text(encoding="utf-8")
        assert EM_DASH not in src, f"em dash in {target}"
        assert EN_DASH not in src, f"en dash in {target}"
        assert FIG_DASH not in src, f"figure dash in {target}"
        assert HORIZ_BAR not in src, f"horizontal bar in {target}"
        assert HASH_CHAR not in src, f"hash char in {target}"
        assert LINE_COMMENT not in src, f"line comment token in {target}"
        assert BLOCK_COMMENT_OPEN not in src, f"block comment token in {target}"
        assert HTML_COMMENT_OPEN not in src, f"html comment token in {target}"
        assert FETCH_CALL not in src, f"network token in {target}"
        assert XHR_TOKEN not in src, f"XHR token in {target}"

    for js_target in (PERSONAS_JS_PATH, FALLBACK_JS_PATH):
        assert _find_js_comments(js_target.read_text(encoding="utf-8")) == []

    for py_target in (MODULE_PATH, self_path):
        py_src = py_target.read_text(encoding="utf-8")
        py_comments = [
            tok for tok in tokenize.generate_tokens(io.StringIO(py_src).readline) if tok.type == tokenize.COMMENT
        ]
        assert py_comments == []
        tree = ast.parse(py_src)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert "genai" not in alias.name and "google" not in alias.name
            elif isinstance(node, ast.ImportFrom) and node.module:
                assert "genai" not in node.module and "google" not in node.module

    rules = _load_protected_rules()
    assert rules

    checked_paths = {t.relative_to(ROOT).as_posix() for t in targets}

    violations = sorted(rel for rel in checked_paths if _matches_protected_rule(rel, rules))
    assert violations == [], f"protected-paths.txt violations: {violations}"
