from __future__ import annotations

import importlib.util
import io
import json
import re
import shutil
import subprocess
import tokenize
from pathlib import Path
from typing import Any

import pytest

from canary.env import Env
from canary.rules import HELDOUT_SEEDS, JUDGE_SEEDS, TRAIN_SEEDS

ROOT = Path(__file__).resolve().parents[1]
ARENA_PY = ROOT / "docs" / "arena" / "arena_integrity.py"
ARENA_JS = ROOT / "docs" / "arena" / "arena_integrity.js"
THIS_TEST = Path(__file__).resolve()

HASH_CH = chr(35)
SLASH_SLASH = chr(47) * 2
SLASH_STAR = chr(47) + chr(42)
STAR_SLASH = chr(42) + chr(47)
EM_DASH = chr(0x2014)
EN_DASH = chr(0x2013)
UNICODE_MINUS = chr(0x2212)


def _load_arena_integrity() -> Any:
    spec = importlib.util.spec_from_file_location("arena_integrity_mod", ARENA_PY)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _find_node() -> str:
    preferred = Path("/home/silas/tools/node/bin/node")
    if preferred.is_file():
        return str(preferred)
    found = shutil.which("node")
    if found:
        return found
    for fallback in (Path("/usr/local/bin/node"), Path("/usr/bin/node")):
        if fallback.is_file():
            return str(fallback)
    pytest.skip("node binary not available")


def test_owned_files_strict_hygiene_and_secret_free() -> None:
    forbidden_words = (
        "CANARY_" + "WORLD_SECRET",
        "CANARY_" + "LEDGER_TOKEN",
        "CANARY_" + "ADMIN_TOKEN",
        "GEMINI_" + "API_KEY",
        "OPENAI_" + "API_KEY",
        "ANTHROPIC_" + "API_KEY",
        "data/worlds/judge/" + "SALT",
        "AI" + "za",
    )
    for fp in (ARENA_PY, ARENA_JS, THIS_TEST):
        assert fp.is_file(), f"missing {fp}"
        text = fp.read_text(encoding="utf-8")
        assert text.isascii(), f"non-ASCII char in {fp.name}"
        assert HASH_CH not in text, f"hash comment char in {fp.name}"
        assert SLASH_SLASH not in text, f"line comment marker in {fp.name}"
        assert SLASH_STAR not in text, f"block comment open in {fp.name}"
        assert STAR_SLASH not in text, f"block comment close in {fp.name}"
        assert EM_DASH not in text, f"em dash in {fp.name}"
        assert EN_DASH not in text, f"en dash in {fp.name}"
        assert UNICODE_MINUS not in text, f"unicode minus in {fp.name}"
        for bad in forbidden_words:
            assert bad not in text, f"forbidden token in {fp.name}"
        if fp.suffix == ".py":
            toks = list(tokenize.generate_tokens(io.StringIO(text).readline))
            assert [t for t in toks if t.type == tokenize.COMMENT] == []

    py_src = ARENA_PY.read_text(encoding="utf-8")
    assert ("self" + ".env") not in py_src


def test_check_arena_seed_firewall() -> None:
    ai = _load_arena_integrity()
    modes = (
        "duel",
        "duel_gemini",
        "solver",
        "beat_solver",
        "mole",
        "be_the_mole",
        "living",
        "living_office",
    )
    valid_seeds = (0, 6, 26, 59, 3000, 4500, 9999, "0", "6", "3000", "9999")
    for mode in modes:
        for s in valid_seeds:
            checked = ai.check_arena_seed(mode, s)
            assert isinstance(checked, int) and not isinstance(checked, bool)
            assert checked == int(s)

    for j_seed in JUDGE_SEEDS:
        with pytest.raises(ValueError):
            ai.check_arena_seed("duel", j_seed)
        with pytest.raises(ValueError):
            ai.check_arena_seed(j_seed)

    for h_seed in (min(HELDOUT_SEEDS), 800015, max(HELDOUT_SEEDS)):
        with pytest.raises(ValueError):
            ai.check_arena_seed("solver", h_seed)

    for t_seed in (min(TRAIN_SEEDS), 150000, max(TRAIN_SEEDS)):
        with pytest.raises(ValueError):
            ai.check_arena_seed("mole", t_seed)

    bad_inputs: tuple[Any, ...] = (
        True,
        False,
        None,
        3000.0,
        6.25,
        float("nan"),
        float("inf"),
        -1,
        -3000,
        60,
        2999,
        10000,
        " 3000",
        "3000 ",
        "\n6",
        "+3000",
        "03000",
        "3000.0",
        "3e3",
        "abc",
        "",
        [],
        {},
    )
    for bad in bad_inputs:
        with pytest.raises(ValueError):
            ai.check_arena_seed("duel", bad)

    for bad_mode in ("judge", "train", "", None, True, 123, " duel"):
        with pytest.raises(ValueError):
            ai.check_arena_seed(bad_mode, 3000)


def test_investigator_session_closure_zero_drain_and_strip() -> None:
    ai = _load_arena_integrity()
    sess = ai.create_investigator_session("medium", 3000, mode="duel")

    assert not hasattr(sess, "env")
    assert not hasattr(sess, "_env")
    assert not hasattr(sess, "_world")
    assert not hasattr(sess, "__dict__")
    assert len(sess.history) == 0
    assert len(sess.actions) == 0

    hud0 = json.loads(sess.hud_json())
    frame0 = json.loads(sess.office_frame_json())
    assert len(sess.history) == 0
    assert hud0["tool_calls"] == 0
    assert hud0["leaking_sprite_employee"] is None
    assert frame0["leaking_sprite_employee"] is None
    for hidden in ("mole", "true_mole", "decoy", "correct", "true_v", "world_seed"):
        assert hidden not in hud0
        assert hidden not in frame0
    ai.assert_pre_end_clean(hud0, "hud0")
    ai.assert_pre_end_clean(frame0, "frame0")

    with pytest.raises(PermissionError):
        sess.reveal_json()

    bad_call = json.loads(sess.call_json("status", "{bad_json"))
    assert bad_call["ok"] is False
    assert len(sess.history) == 0

    emp_res = json.loads(sess.call_json("list_employees", "{}"))
    assert emp_res["ok"] is True
    assert len(emp_res["data"]["employees"]) == 20
    assert len(sess.history) == 1
    ai.assert_pre_end_clean(emp_res, "list_employees")


def test_call_json_strips_accidental_truth_keys_from_step_tool(monkeypatch: pytest.MonkeyPatch) -> None:
    ai = _load_arena_integrity()
    from canary.types import ToolResult

    class _InjectingEnv(Env):
        def step_tool(self, tool: str, args: dict[str, Any]) -> ToolResult:
            base = self.call(tool, args)
            leaked_data = dict(base.data)
            leaked_data.update(
                {
                    "mole": "e09",
                    "true_mole": "e09",
                    "decoy": "e03",
                    "correct": True,
                    "true_v": 0.72,
                    "world_seed": 123456,
                    "V": 0.72,
                }
            )
            return ToolResult(base.ok, leaked_data, base.error)

    monkeypatch.setattr(ai, "Env", _InjectingEnv)
    sess = ai.create_investigator_session("medium", 3000, mode="solver")
    out = json.loads(sess.call_json("status", "{}"))
    assert out["ok"] is True
    assert out["known_v"] == 1.0
    assert out["data"]["V"] == 1.0
    for stripped in ("mole", "true_mole", "decoy", "correct", "true_v", "world_seed"):
        assert stripped not in out["data"]
        assert stripped not in out
    ai.assert_pre_end_clean(out, "injected_step_tool")


@pytest.mark.parametrize("hard_seed,check_days", [(6, (2, 3)), (26, (3, 5))])
def test_hard_seeds_6_and_26_known_v_vs_true_v_and_post_end_reveal(
    hard_seed: int,
    check_days: tuple[int, ...],
) -> None:
    ai = _load_arena_integrity()
    sess = ai.create_investigator_session("hard", hard_seed, mode="duel_gemini")
    ref_env = Env("hard", hard_seed)
    true_mole = ref_env._world.mole
    true_decoy = ref_env._world.decoy

    assert not hasattr(sess, "env")
    assert not hasattr(sess, "_world")
    assert len(sess.history) == 0

    saw_divergence = False
    target_max = max(check_days)
    while sess.day < target_max:
        step_out = json.loads(sess.call_json("advance_day", "{}"))
        ref_env.call("advance_day", {})
        hud = json.loads(sess.hud_json())
        frame = json.loads(sess.office_frame_json())
        kv = ref_env.visible_V()
        tv = round(ref_env.V, 10)

        assert step_out["known_v"] == kv
        assert step_out["data"]["V"] == kv
        assert hud["known_v"] == kv
        assert hud["V"] == kv
        assert hud["leaking_sprite_employee"] is None
        assert frame["known_v"] == kv
        assert frame["V"] == kv
        assert frame["leaking_sprite_employee"] is None

        for forbidden in ("mole", "true_mole", "decoy", "correct", "true_v", "world_seed"):
            assert forbidden not in step_out
            assert forbidden not in step_out["data"]
            assert forbidden not in hud
            assert forbidden not in frame

        ai.assert_pre_end_clean(step_out, f"seed{hard_seed}_step_d{sess.day}")
        ai.assert_pre_end_clean(hud, f"seed{hard_seed}_hud_d{sess.day}")
        ai.assert_pre_end_clean(frame, f"seed{hard_seed}_frame_d{sess.day}")

        if sess.day in check_days:
            assert abs(tv - kv) > 1e-9
            assert abs(hud["known_v"] - tv) > 1e-9
            saw_divergence = True

        with pytest.raises(PermissionError):
            sess.reveal_json()

    assert saw_divergence

    acc_out = json.loads(sess.call_json("accuse", json.dumps({"employee": true_mole})))
    ref_env.call("accuse", {"employee": true_mole})
    assert acc_out["done"] is True
    assert "correct" not in acc_out["data"]
    assert "mole" not in acc_out["data"]

    hud_done = json.loads(sess.hud_json())
    frame_done = json.loads(sess.office_frame_json())
    assert hud_done["done"] is True
    assert hud_done["leaking_sprite_employee"] == true_mole
    assert frame_done["leaking_sprite_employee"] == true_mole

    rev = json.loads(sess.reveal_json())
    verdict = ref_env.verdict()
    assert rev["done"] is True
    assert rev["mole"] == true_mole
    assert rev["decoy"] == true_decoy
    assert rev["accused"] == true_mole
    assert rev["correct"] is True
    assert rev["score"] == verdict["score"]
    assert rev["known_v"] == ref_env.visible_V()
    assert rev["true_v"] == verdict["V"]
    assert rev["true_v"] < rev["known_v"]
    assert rev["final_day"] == verdict["final_day"]
    assert rev["tool_calls"] == len(ref_env.history)
    assert rev["end_reason"] == "accused"
    assert rev["leaking_sprite_employee"] == true_mole


def test_mode3_mole_session_closure_canary_and_posterior_stripping() -> None:
    ai = _load_arena_integrity()
    msess = ai.create_mole_session("medium", 3002)

    assert not hasattr(msess, "env")
    assert not hasattr(msess, "_env")
    assert not hasattr(msess, "_world")
    assert not hasattr(msess, "_solver")
    assert not hasattr(msess, "__dict__")

    with pytest.raises(PermissionError):
        msess.reveal_json()

    view1 = json.loads(msess.view_json())
    assert view1["done"] is False
    assert len(view1["leakable_docs"]) >= 2
    ai.assert_pre_end_clean(view1, "mole_view_day1")

    raw_dump = json.dumps(view1)
    for forbidden_str in ("is_canary", "canary_variants", "posterior", "top_suspect", "true_v"):
        assert forbidden_str not in raw_dump

    for doc in view1["leakable_docs"]:
        assert re.match(r"^doc_\d+$", doc["doc_id"])
        assert not doc["doc_id"].startswith("c")
        assert isinstance(doc["recipient_count"], int) and doc["recipient_count"] >= 1
        assert doc["sensitivity"] in {"restricted", "confidential", "internal"}
        assert isinstance(doc["days_old"], int) and doc["days_old"] >= 0
        assert "is_canary" not in doc
        assert "canary_variants" not in doc
        assert "variants" not in doc

    reject_c1 = msess.step_mole_day({"type": "leak", "doc_id": "c1"})
    assert reject_c1["ok"] is False

    guard = 0
    while not msess.done and guard < 20:
        cur_view = msess.get_mole_day_view()
        ai.assert_pre_end_clean(cur_view, f"mole_loop_{guard}")
        if cur_view["leakable_docs"]:
            pick = min(cur_view["leakable_docs"], key=lambda d: d["recipient_count"])["doc_id"]
            step_res = msess.step_mole_day({"type": "leak", "doc_id": pick})
        else:
            step_res = msess.step_mole_day({"type": "hold"})
        assert step_res["ok"] is True
        if not step_res["done"]:
            ai.assert_pre_end_clean(step_res["day_view"], f"mole_after_{guard}")
            with pytest.raises(PermissionError):
                msess.reveal_json()
        guard += 1

    assert msess.done is True
    debrief = json.loads(msess.reveal_json())
    assert debrief["done"] is True
    assert isinstance(debrief["posterior_curve"], list) and len(debrief["posterior_curve"]) >= 1
    assert "mole" in debrief and "decoy" in debrief
    assert "true_v" in debrief and "known_v" in debrief
    assert isinstance(debrief["leaked_canaries"], list)


def test_opponent_step_sealing_and_payload_seal_roundtrip() -> None:
    ai = _load_arena_integrity()
    raw_steps = [
        {
            "t": 0,
            "day": 1,
            "tool": "interview",
            "args": {"employee": "e07", "topic": "workload"},
            "result": {"ok": True, "data": {"employee": "e07", "answer": "Busy"}},
            "summary": "Interviewed e07",
            "known_v": 1.0,
            "true_v": 0.95,
            "V": 0.95,
            "mole": "e29",
        },
        {
            "t": 1,
            "day": 2,
            "tool": "accuse",
            "args": {"employee": "e29"},
            "summary": "Accused e29 based on canary A",
            "rationale": "Suspect e29 vs decoy e14",
            "result": {"ok": True, "data": {"accused": "e29", "episode_over": True}},
            "accused": "e29",
            "correct": True,
            "score": 0.94,
            "mole": "e29",
            "decoy": "e14",
            "true_v": 0.94,
            "known_v": 0.99,
            "V": 0.94,
        },
        {
            "t": 2,
            "day": 5,
            "tool": "status",
            "args": {},
            "result": {"ok": True, "data": {"day": 5, "V": 0.9}},
        },
    ]

    day1_only = ai.sanitize_opponent_steps(raw_steps, human_day=1, human_done=False)
    assert len(day1_only) == 1
    assert day1_only[0]["V"] == 1.0
    assert "true_v" not in day1_only[0]
    assert "mole" not in day1_only[0]
    ai.assert_pre_end_clean(day1_only, "day1_only")

    day3_locked = ai.sanitize_opponent_steps(raw_steps, human_day=3, human_done=False)
    assert len(day3_locked) == 2
    acc_step = day3_locked[1]
    assert acc_step["args"]["employee"] == "[SEALED]"
    assert acc_step["sealed"] is True
    assert "e29" not in json.dumps(acc_step)
    assert "e14" not in json.dumps(acc_step)
    for stripped in ("accused", "correct", "score", "mole", "decoy", "true_v"):
        assert stripped not in acc_step
    assert acc_step["V"] == 0.99
    assert ai.assert_pre_end_clean(day3_locked, "day3_locked") is True
    assert (
        ai.assert_pre_end_clean(
            {"day": 2, "tool": "accuse", "args": "[SEALED]", "summary": "Accusation filed [SEALED]", "sealed": True},
            "craft_sealed_accuse",
        )
        is True
    )
    with pytest.raises(ValueError):
        ai.assert_pre_end_clean(
            {"day": 2, "tool": "accuse", "args": {"employee": "[SEALED]", "note": "e29"}},
            "leaked_accuse_args_note",
        )
    with pytest.raises(ValueError):
        ai.assert_pre_end_clean({"leakable_docs": [{"doc_id": "c1"}]}, "unmasked_leakable_docs")

    with pytest.raises(ValueError):
        ai.assert_pre_end_clean(raw_steps[:2], "unsealed_raw")

    unlocked = ai.sanitize_opponent_steps(raw_steps, human_day=5, human_done=True)
    assert len(unlocked) == 3
    assert unlocked[1]["args"]["employee"] == "e29"
    assert unlocked[1]["score"] == 0.94

    secret_reveal = {"mole": "e29", "decoy": "e14", "correct": True, "score": 0.94, "true_v": 0.94}
    token = ai.seal_payload(secret_reveal)
    assert token.startswith("sealed:")
    assert "e29" not in token
    with pytest.raises(PermissionError):
        ai.unseal_payload(token, False)
    assert ai.unseal_payload(token, True) == secret_reveal


def test_js_bridge_exports_window_global_and_python_parity() -> None:
    ai = _load_arena_integrity()
    node_bin = _find_node()

    sess6 = ai.create_investigator_session("hard", 6, mode="duel")
    sess6.call_json("advance_day", "{}")
    py_hud = json.loads(sess6.hud_json())
    py_frame = json.loads(sess6.office_frame_json())

    msess = ai.create_mole_session("medium", 3002)
    py_mole_view = json.loads(msess.view_json())

    py_sealed = ai.seal_payload({"mole": "e34", "decoy": "e20", "true_v": 0.95, "score": 0.95})

    node_script = """
import assert from "node:assert/strict";
import { pathToFileURL } from "node:url";

globalThis.window = globalThis;
const payload = JSON.parse(process.argv[1]);
const mod = await import(pathToFileURL(payload.jsPath).href);
const winApi = globalThis.window.CanaryArenaIntegrity;
const globApi = globalThis.CanaryArenaIntegrity;

assert.ok(winApi, "window.CanaryArenaIntegrity missing");
assert.strictEqual(winApi, globApi);

const expectedFns = [
  "checkArenaSeed",
  "sanitizeOpponentSteps",
  "sanitizeOpponentStepForHud",
  "sanitizeOfficeFrame",
  "sanitizeMoleView",
  "sealReveal",
  "unsealReveal",
  "assertPreEndClean"
];
for (const fn of expectedFns) {
  assert.strictEqual(typeof mod[fn], "function", "missing ES export " + fn);
  assert.strictEqual(winApi[fn], mod[fn], "window mismatch on " + fn);
}

for (const mode of ["duel", "duel_gemini", "solver", "beat_solver", "mole", "be_the_mole", "living", "living_office"]) {
  assert.strictEqual(mod.checkArenaSeed(mode, 6), 6);
  assert.strictEqual(mod.checkArenaSeed(mode, 26), 26);
  assert.strictEqual(mod.checkArenaSeed(mode, 3000), 3000);
  assert.strictEqual(mod.checkArenaSeed(mode, "9999"), 9999);
}

for (const badSeed of [900000, 900039, 800000, 800199, 100000, 199999, true, false, null, undefined, 3000.5, -1, 60, 2999, 10000, " 3000", "3000 ", "+3000", "03000", "3e3", "abc", ""]) {
  assert.throws(() => mod.checkArenaSeed("duel", badSeed));
}
assert.throws(() => mod.checkArenaSeed("judge", 3000));

assert.strictEqual(mod.assertPreEndClean(payload.pyHud, "pyHud"), true);
assert.strictEqual(mod.assertPreEndClean(payload.pyFrame, "pyFrame"), true);
assert.strictEqual(mod.assertPreEndClean(payload.pyMoleView, "pyMoleView"), true);

const oppSteps = [
  { day: 1, tool: "status", args: {}, summary: "Day 1 status", V: 0.95, known_v: 1.0, true_v: 0.95, mole: "e34" },
  {
    day: 2,
    tool: "accuse",
    args: { employee: "e34" },
    summary: "Accusing e34 now",
    rationale: "Pinned e34 over decoy e20",
    result: { ok: true, data: { accused: "e34", episode_over: true } },
    accused: "e34",
    correct: true,
    score: 0.95,
    mole: "e34",
    decoy: "e20",
    true_v: 0.95,
    known_v: 1.0,
    V: 0.95
  },
  { day: 6, tool: "advance_day", args: {}, summary: "Day 6" }
];

const preEndOpp = mod.sanitizeOpponentSteps(oppSteps, 3, false);
assert.strictEqual(preEndOpp.length, 2);
assert.strictEqual(preEndOpp[0].V, 1.0);
assert.strictEqual(preEndOpp[1].args.employee, "[SEALED]");
assert.ok(!JSON.stringify(preEndOpp[1]).includes("e34"));
assert.ok(!JSON.stringify(preEndOpp[1]).includes("e20"));
assert.strictEqual("accused" in preEndOpp[1], false);
assert.strictEqual("correct" in preEndOpp[1], false);
assert.strictEqual("score" in preEndOpp[1], false);
assert.strictEqual(mod.assertPreEndClean(preEndOpp, "preEndOpp"), true);
assert.throws(() => mod.assertPreEndClean(oppSteps.slice(0, 2), "rawOpp"));

const postEndOpp = mod.sanitizeOpponentSteps(oppSteps, 6, true);
assert.strictEqual(postEndOpp.length, 3);
assert.strictEqual(postEndOpp[1].args.employee, "e34");
assert.strictEqual(postEndOpp[1].score, 0.95);

const dirtyFrame = {
  day: 2,
  done: false,
  known_v: 1.0,
  V: 0.95,
  true_v: 0.95,
  mole: "e34",
  decoy: "e20",
  leaking_sprite_employee: "e34",
  mole_sprite: "e34",
  culprit_sprite: "e34",
  leaker_employee: "e34"
};
assert.throws(() => mod.assertPreEndClean(dirtyFrame, "dirtyFrame"));
const cleanFrame = mod.sanitizeOfficeFrame(dirtyFrame, false);
assert.strictEqual(cleanFrame.leaking_sprite_employee, null);
assert.strictEqual(cleanFrame.V, 1.0);
assert.strictEqual("mole_sprite" in cleanFrame, false);
assert.strictEqual("culprit_sprite" in cleanFrame, false);
assert.strictEqual("leaker_employee" in cleanFrame, false);
assert.strictEqual("mole" in cleanFrame, false);
assert.strictEqual(mod.assertPreEndClean(cleanFrame, "cleanFrame"), true);
const unlockedFrame = mod.sanitizeOfficeFrame(dirtyFrame, true);
assert.strictEqual(unlockedFrame.leaking_sprite_employee, "e34");

const dirtyMole = {
  mode: "be_the_mole",
  day: 2,
  n_staff: 20,
  known_v: 1.0,
  true_v: 0.96,
  posterior: 0.42,
  top_suspects: ["e09", "e02"],
  leakable_docs: [
    { doc_id: "c1", title: "Canary trap alpha", day: 1, recipients: ["e09", "e02"], is_canary: true, canary_variants: { A: ["e09"] } },
    { doc_id: "d2-1", title: "Q2 Sales budget forecast", day: 2, recipients: ["e01", "e02", "e03", "e09"], is_canary: false }
  ]
};
assert.throws(() => mod.assertPreEndClean(dirtyMole, "dirtyMole"));
const cleanMole = mod.sanitizeMoleView(dirtyMole, false);
assert.strictEqual(cleanMole.leakable_docs[0].doc_id, "doc_0");
assert.ok(!cleanMole.leakable_docs[0].title.toLowerCase().includes("canary"));
assert.strictEqual(cleanMole.leakable_docs[0].recipient_count, 2);
assert.strictEqual(cleanMole.leakable_docs[0].days_old, 1);
assert.strictEqual(cleanMole.leakable_docs[0].sensitivity, "restricted");
assert.strictEqual("is_canary" in cleanMole.leakable_docs[0], false);
assert.strictEqual("canary_variants" in cleanMole.leakable_docs[0], false);
assert.strictEqual("posterior" in cleanMole, false);
assert.strictEqual("top_suspects" in cleanMole, false);
assert.strictEqual(mod.assertPreEndClean(cleanMole, "cleanMole"), true);

for (const notDone of [false, 0, "true", null, undefined]) {
  assert.throws(() => mod.unsealReveal(payload.pySealed, notDone));
}
const decodedFromPy = mod.unsealReveal(payload.pySealed, true);
assert.deepStrictEqual(decodedFromPy, { mole: "e34", decoy: "e20", true_v: 0.95, score: 0.95 });

const jsSealed = mod.sealReveal({ mole: "e08", decoy: "e38", correct: false, score: -1.0 });
assert.ok(jsSealed.startsWith("sealed:"));
assert.ok(!jsSealed.includes("e08"));
console.log(JSON.stringify({ ok: true, jsSealed }));
""".strip()

    arg_blob = json.dumps(
        {
            "jsPath": str(ARENA_JS),
            "pyHud": py_hud,
            "pyFrame": py_frame,
            "pyMoleView": py_mole_view,
            "pySealed": py_sealed,
        }
    )
    proc = subprocess.run(
        [node_bin, "--input-type=module", "-e", node_script, arg_blob],
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    assert proc.returncode == 0, f"node failed:\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
    node_out = json.loads(proc.stdout.strip().splitlines()[-1])
    assert node_out["ok"] is True

    with pytest.raises(PermissionError):
        ai.unseal_payload(node_out["jsSealed"], False)
    decoded_from_js = ai.unseal_payload(node_out["jsSealed"], True)
    assert decoded_from_js == {"mole": "e08", "decoy": "e38", "correct": False, "score": -1.0}
