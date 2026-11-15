from __future__ import annotations

import http.client
import importlib.util
import io
import json
import math
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import sys
import time
import tokenize
from typing import Any
import urllib.request

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from canary.rules import HELDOUT_SEEDS, JUDGE_SEEDS, TIERS_VERSION, TRAIN_SEEDS

SELF_PATH = Path(__file__).resolve()
DEFAULT_MOLE_PY = ROOT / "docs" / "arena" / "mole_mode.py"
DEFAULT_MOLE_JS = ROOT / "docs" / "arena" / "mole_mode.js"
FALLBACK_NODE_BIN = Path("/home/silas/tools/node/bin/node")

HASH_CH = chr(35)
EM_DASH = chr(0x2014)
EN_DASH = chr(0x2013)
UNICODE_MINUS = chr(0x2212)
SLASH_SLASH = chr(47) * 2
SLASH_STAR = chr(47) + chr(42)
STAR_SLASH = chr(42) + chr(47)
HASH_SPACE = HASH_CH + " "

MASKED_DOC_ID_RE = re.compile(r"^doc-d\d+-\d+$")
RAW_CANARY_ID_RE = re.compile(r"^c\d+(?:-\d+)?$")

FORBIDDEN_PRE_END_KEYS = frozenset(
    {
        "is_canary",
        "variants",
        "true_variant",
        "variant_recipients",
        "decoy",
        "true_decoy",
        "decoy_id",
        "true_v",
        "true_V",
        "posterior",
        "mole_posterior",
        "top_posterior",
        "top_suspect",
        "mole_rank",
        "posterior_curve",
        "caught_by_canary",
        "leaked_canaries",
        "raw_doc_id",
        "raw_title",
        "world_seed",
        "_world",
        "correct",
        "accused_correct",
    }
)

PROTECTED_PREFIXES = (
    "canary/env.py",
    "canary/rules.py",
    "canary/solver/",
    "canary/reproduce.py",
    "harbor/",
)


def _mole_py_path() -> Path:
    override = os.environ.get("CANARY_MOLE_MODE_PY", "").strip()
    return Path(override).resolve() if override else DEFAULT_MOLE_PY


def _mole_js_path() -> Path:
    override = os.environ.get("CANARY_MOLE_MODE_JS", "").strip()
    return Path(override).resolve() if override else DEFAULT_MOLE_JS


def _require_mole_py() -> Path:
    target = _mole_py_path()
    if not target.is_file():
        if os.environ.get("CANARY_REQUIRE_ARENA_MOLE_MODE") == "1":
            raise AssertionError(f"missing required mole_mode.py at {target}")
        pytest.skip("docs/arena/mole_mode.py not present on this standalone test branch")
    return target


def _require_mole_js() -> Path:
    target = _mole_js_path()
    if not target.is_file():
        if os.environ.get("CANARY_REQUIRE_ARENA_MOLE_MODE") == "1":
            raise AssertionError(f"missing required mole_mode.js at {target}")
        pytest.skip("docs/arena/mole_mode.js not present on this standalone test branch")
    return target


def _load_mole_mode_module() -> Any:
    target = _require_mole_py()
    mod_name = "arena_mole_mode_under_test"
    spec = importlib.util.spec_from_file_location(mod_name, target)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = mod
    spec.loader.exec_module(mod)
    return mod


def _find_node_bin() -> str | None:
    found = shutil.which("node")
    if found:
        return found
    if FALLBACK_NODE_BIN.is_file() and os.access(FALLBACK_NODE_BIN, os.X_OK):
        return str(FALLBACK_NODE_BIN)
    return None


def _collect_forbidden_keys(node: Any, path: str = "root") -> list[str]:
    hits: list[str] = []
    if isinstance(node, dict):
        for k, v in node.items():
            ks = str(k)
            loc = f"{path}.{ks}"
            if ks in FORBIDDEN_PRE_END_KEYS:
                hits.append(loc)
            hits.extend(_collect_forbidden_keys(v, loc))
    elif isinstance(node, list):
        for idx, item in enumerate(node):
            hits.extend(_collect_forbidden_keys(item, f"{path}[{idx}]"))
    return hits


@pytest.fixture(autouse=True)
def _offline_zero_api_guard(monkeypatch: pytest.MonkeyPatch):
    def _deny_network(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("live network or API call forbidden in arena mole_mode tests")

    monkeypatch.setenv("CANARY_OFFLINE", "1")
    monkeypatch.setenv("GEMINI_API_KEY", "")
    monkeypatch.setenv("GOOGLE_API_KEY", "")
    monkeypatch.setenv("GOOGLE_GENERATIVE_AI_API_KEY", "")
    monkeypatch.setenv("OPENAI_API_KEY", "")
    monkeypatch.setattr(socket.socket, "connect", _deny_network)
    monkeypatch.setattr(socket.socket, "connect_ex", _deny_network)
    monkeypatch.setattr(socket, "create_connection", _deny_network)
    monkeypatch.setattr(urllib.request, "urlopen", _deny_network)
    monkeypatch.setattr(http.client.HTTPConnection, "request", _deny_network)
    monkeypatch.setattr(http.client.HTTPSConnection, "request", _deny_network)
    try:
        import canary.llm as canary_llm

        monkeypatch.setattr(canary_llm, "get_client", _deny_network)
    except ImportError:
        pass
    yield


def test_self_and_arena_mole_files_hygiene() -> None:
    self_raw = SELF_PATH.read_text(encoding="utf-8")
    assert self_raw.isascii()
    assert EM_DASH not in self_raw
    assert EN_DASH not in self_raw
    assert UNICODE_MINUS not in self_raw
    assert HASH_CH not in self_raw
    assert SLASH_SLASH not in self_raw
    assert SLASH_STAR not in self_raw
    assert STAR_SLASH not in self_raw
    self_tokens = list(tokenize.generate_tokens(io.StringIO(self_raw).readline))
    assert [t for t in self_tokens if t.type == tokenize.COMMENT] == []

    py_target = _mole_py_path()
    if py_target.is_file():
        py_raw = py_target.read_text(encoding="utf-8")
        assert len(py_raw.strip()) > 0
        assert py_raw.isascii(), f"non-ASCII char in {py_target}"
        assert EM_DASH not in py_raw
        assert EN_DASH not in py_raw
        assert UNICODE_MINUS not in py_raw
        py_tokens = list(tokenize.generate_tokens(io.StringIO(py_raw).readline))
        assert [t for t in py_tokens if t.type == tokenize.COMMENT] == []
        for cred_prefix in ("AI" + "za", "s" + "k-proj-", "ya" + "29.", "h" + "f_"):
            assert cred_prefix not in py_raw

    js_target = _mole_js_path()
    if js_target.is_file():
        js_raw = js_target.read_text(encoding="utf-8")
        assert len(js_raw.strip()) > 0
        assert js_raw.isascii(), f"non-ASCII char in {js_target}"
        assert EM_DASH not in js_raw
        assert EN_DASH not in js_raw
        assert UNICODE_MINUS not in js_raw
        assert SLASH_SLASH not in js_raw
        assert SLASH_STAR not in js_raw
        assert STAR_SLASH not in js_raw
        assert HASH_SPACE not in js_raw
        for sink in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval("):
            assert sink not in js_raw, f"forbidden XSS/eval sink {sink} in {js_target.name}"


def test_protected_files_untouched() -> None:
    git_bin = shutil.which("git")
    if not git_bin:
        return
    proc = subprocess.run(
        [git_bin, "diff", "--name-only", "origin/justSilas...HEAD"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        return
    changed = [line.strip() for line in proc.stdout.splitlines() if line.strip()]
    touched_protected = [
        path for path in changed if any(path == pref or path.startswith(pref) for pref in PROTECTED_PREFIXES)
    ]
    assert touched_protected == []


def test_seed_and_tier_firewall() -> None:
    mm = _load_mole_mode_module()
    assert mm.SEED_MIN == 3000
    assert mm.SEED_MAX == 9999
    assert tuple(mm.ALLOWED_TIERS) == ("medium", "hard")
    assert mm.DEFAULT_TIER == "medium"

    seed_gates = [mm.check_seed]
    if hasattr(mm, "check_mole_seed"):
        seed_gates.append(mm.check_mole_seed)

    for valid_in, expected in ((3000, 3000), (9999, 9999), ("3005", 3005), (" 4200 ", 4200)):
        for gate in seed_gates:
            out = gate(valid_in)
            assert out == expected
            assert type(out) is int

    forbidden_seeds: list[Any] = (
        list(JUDGE_SEEDS)
        + list(range(800_000, 800_030))
        + [HELDOUT_SEEDS[-1], TRAIN_SEEDS[0], TRAIN_SEEDS[-1]]
        + [0, 1, 6, 26, 2999, 10_000, -1, True, False, "3000.0", "3e3", "abc", "", None, [3000], {}]
    )
    for bad_seed in forbidden_seeds:
        for gate in seed_gates:
            with pytest.raises(ValueError):
                gate(bad_seed)
        with pytest.raises(ValueError):
            mm.MoleModeSession(bad_seed, "medium")
        with pytest.raises(ValueError):
            mm.start_mole_game(bad_seed, "medium")
        with pytest.raises(ValueError):
            mm.start_mole_game_json(bad_seed, "medium")

    assert mm.check_tier("medium") == "medium"
    assert mm.check_tier("hard") == "hard"
    assert mm.check_tier(" hard ") == "hard"

    for bad_tier in ("easy", "hard_forge", "hard_rl", "", "MEDIUM", None, 123, True):
        with pytest.raises(ValueError):
            mm.check_tier(bad_tier)
        with pytest.raises(ValueError):
            mm.MoleModeSession(3000, bad_tier)

    swapped = mm.MoleModeSession("hard", 3001)
    assert swapped.seed == 3001
    assert swapped.tier == "hard"
    assert swapped.tiers_version == TIERS_VERSION
    assert swapped.n_days == 21


def test_pre_end_day_view_zero_hidden_truth_leaks() -> None:
    mm = _load_mole_mode_module()

    for seed, tier in ((3000, "medium"), (3001, "medium"), (3001, "hard")):
        session = mm.MoleModeSession(seed, tier)
        assert len(session._env._canary_ids) >= 1
        assert session._env._world.decoy is not None

        for _ in range(3):
            if session.done:
                break
            dv = session.get_mole_day_view()
            dv_from_json = json.loads(session.day_view_json())
            assert dv == dv_from_json
            assert dv["done"] is False
            assert _collect_forbidden_keys(dv) == []

            assert dv["seed"] == seed
            assert dv["tier"] == tier
            assert dv["tiers_version"] == TIERS_VERSION
            assert dv["mole_id"] == session.mole_id
            assert dv["mole_id"] not in dv["peers"]
            assert len(dv["peers"]) == dv["n_staff"] - 1
            assert len(dv["peer_roster"]) == dv["n_staff"] - 1

            for peer_entry in dv["peer_roster"]:
                assert set(peer_entry.keys()) == {"id", "name", "dept", "role", "restricted"}

            for doc_list_key in ("leakable_docs", "docs"):
                for doc in dv[doc_list_key]:
                    assert set(doc.keys()) == {
                        "doc_id",
                        "title",
                        "day",
                        "age_days",
                        "recipient_count",
                        "recipients",
                    }
                    assert MASKED_DOC_ID_RE.match(doc["doc_id"]), f"unmasked doc_id {doc['doc_id']}"
                    assert not RAW_CANARY_ID_RE.match(doc["doc_id"])
                    assert not doc["title"].startswith("Board memo draft")
                    assert "canary" not in doc["title"].lower()
                    assert session.mole_id in doc["recipients"]

            for item in dv["surfaced_leaks"]:
                assert set(item.keys()) == {"surfaced_day", "doc_id", "title"}
                assert MASKED_DOC_ID_RE.match(item["doc_id"])
                assert not item["title"].startswith("Board memo draft")

            raw_canary_titles = [
                x["title"] for x in session._env.docs if x.get("is_canary") and x["title"].startswith("Board memo draft")
            ]
            assert len(raw_canary_titles) >= 1
            for cid in session._env._canary_ids:
                if cid in session._raw_to_title:
                    assert not session._raw_to_title[cid].startswith("Board memo draft")
                    assert MASKED_DOC_ID_RE.match(session._raw_to_mask[cid])

            if dv["leakable_docs"]:
                pick = max(dv["leakable_docs"], key=lambda d: d["recipient_count"])
                step_res = session.step_mole_day({"type": "leak", "doc_id": pick["doc_id"]})
            else:
                step_res = session.step_mole_day({"type": "hold"})

            assert step_res["ok"] is True
            if not step_res["done"]:
                assert step_res["outcome"] is None
                assert _collect_forbidden_keys(step_res) == []
                if step_res["applied_action"]["doc_id"] is not None:
                    assert MASKED_DOC_ID_RE.match(step_res["applied_action"]["doc_id"])


def test_visible_v_hides_unsurfaced_leak_damage_pre_end() -> None:
    mm = _load_mole_mode_module()

    for seed, tier, max_steps in ((3001, "medium", 3), (3001, "hard", 4)):
        session = mm.MoleModeSession(seed, tier)
        saw_unsurfaced_gap = False
        for _ in range(max_steps):
            if session.done:
                break
            dv = session.get_mole_day_view()
            expected_vis_v = session._env.visible_V()
            true_env_v = round(session._env.V, 10)
            assert math.isclose(dv["visible_v"], expected_vis_v, abs_tol=1e-12)
            assert math.isclose(dv["visible_V"], expected_vis_v, abs_tol=1e-12)
            assert math.isclose(dv["pressure"]["visible_v"], expected_vis_v, abs_tol=1e-12)
            if abs(true_env_v - expected_vis_v) > 1e-9:
                saw_unsurfaced_gap = True
                assert dv["visible_v"] > true_env_v
            if dv["leakable_docs"]:
                best = max(dv["leakable_docs"], key=lambda d: d["recipient_count"])
                session.step_mole_day({"type": "leak", "doc_id": best["doc_id"]})
            else:
                session.step_mole_day({"type": "hold"})
        assert saw_unsurfaced_gap, f"expected unsurfaced V gap on ({seed}, {tier})"


def test_pre_end_debrief_firewall() -> None:
    mm = _load_mole_mode_module()
    session = mm.MoleModeSession(3000, "medium")
    assert session.done is False

    deb1 = session.get_mole_debrief()
    assert deb1 == json.loads(session.debrief_json())
    assert deb1["ok"] is False
    assert deb1["done"] is False
    assert isinstance(deb1.get("error"), str) and len(deb1["error"]) > 0
    assert set(deb1.keys()) == {"ok", "done", "error"}
    assert _collect_forbidden_keys(deb1) == []

    session.step_mole_day({"type": "hold"})
    assert session.done is False
    deb2 = session.get_mole_debrief()
    assert deb2["ok"] is False
    assert deb2["done"] is False
    assert set(deb2.keys()) == {"ok", "done", "error"}


def test_malformed_step_inputs_rejected_without_advancing_day() -> None:
    mm = _load_mole_mode_module()
    session = mm.MoleModeSession(3000, "medium")
    day_before = session.day
    hist_before = len(session._env.history)

    bad_inputs: list[Any] = [
        "{not valid json",
        "",
        None,
        123,
        ["hold"],
        {},
        {"type": "plant_canary"},
        {"type": "leak"},
        {"type": "leak", "doc_id": "   "},
        {"type": "leak", "doc_id": "doc-d99-99"},
        {"type": "hold", "frame_peer": "e999"},
        {"type": "hold", "frame_peer": session.mole_id},
        {"type": "hold", "frame_peer": 42},
    ]

    for bad in bad_inputs:
        res = session.step_mole_day(bad)
        assert res["ok"] is False, f"expected ok=False for {bad!r}"
        assert res["done"] is False
        assert res["outcome"] is None
        assert isinstance(res.get("error"), str) and len(res["error"]) > 0
        assert _collect_forbidden_keys(res) == []
        assert session.day == day_before
        assert len(session._env.history) == hist_before


def test_solver_hunts_reckless_leaker_and_unlocks_post_game_debrief() -> None:
    mm = _load_mole_mode_module()
    session = mm.MoleModeSession(3000, "medium")

    last_step: dict[str, Any] | None = None
    while not session.done:
        dv = session.get_mole_day_view()
        if dv["leakable_docs"]:
            last_step = session.step_mole_day({"type": "leak", "doc_id": dv["leakable_docs"][-1]["doc_id"]})
        else:
            last_step = session.step_mole_day({"type": "hold"})

    assert last_step is not None
    assert session.done is True
    outcome = last_step["outcome"]
    assert outcome is not None
    assert outcome["done"] is True
    assert outcome["caught"] is True
    assert outcome["survived"] is False
    assert outcome["accused_id"] == session.mole_id
    assert outcome["end_reason"] == "accused"

    expected_solver_score = float(session._env.score())
    assert expected_solver_score > 0.0
    assert math.isclose(outcome["solver_score"], expected_solver_score, abs_tol=1e-10)
    assert math.isclose(outcome["mole_score"], round(-expected_solver_score, 10), abs_tol=1e-10)

    post_over = session.step_mole_day({"type": "hold"})
    assert post_over["ok"] is False
    assert post_over["done"] is True
    assert post_over["error"] == "episode over"
    assert post_over["outcome"] == outcome

    debrief = session.get_mole_debrief()
    assert debrief == json.loads(session.debrief_json())
    assert debrief["ok"] is True
    assert debrief["done"] is True
    assert debrief["seed"] == 3000
    assert debrief["tier"] == "medium"
    assert debrief["mole_id"] == session.mole_id
    assert debrief["caught"] is True
    assert debrief["survived"] is False
    assert debrief["accused_id"] == session.mole_id
    assert math.isclose(debrief["solver_score"], expected_solver_score, abs_tol=1e-10)
    assert math.isclose(debrief["mole_score"], round(-expected_solver_score, 10), abs_tol=1e-10)
    assert math.isclose(debrief["true_v"], round(session._env.V, 10), abs_tol=1e-10)
    assert math.isclose(debrief["visible_v"], session._env.visible_V(), abs_tol=1e-10)
    assert math.isclose(
        debrief["leak_damage_dealt"],
        round(debrief["leaks_count"] * session._env.p.leak_damage, 10),
        abs_tol=1e-10,
    )

    curve = debrief["posterior_curve"]
    assert isinstance(curve, list) and len(curve) >= 2
    for pt in curve:
        assert set(pt.keys()) >= {
            "day",
            "posterior",
            "mole_posterior",
            "top_suspect",
            "top_posterior",
            "mole_rank",
            "visible_v",
            "true_v",
        }
        assert 0.0 <= pt["posterior"] <= 1.0
        assert pt["mole_rank"] >= 1
    assert curve[-1]["top_suspect"] == session.mole_id
    assert curve[-1]["mole_rank"] == 1

    assert len(debrief["leaks_made"]) == debrief["leaks_count"]
    assert len(debrief["leaked_canaries"]) >= 1
    caught_canary = debrief["caught_by_canary"]
    assert caught_canary is not None
    assert MASKED_DOC_ID_RE.match(caught_canary["doc_id"])
    assert RAW_CANARY_ID_RE.match(caught_canary["raw_doc_id"])
    assert session.mole_id in caught_canary["variant_recipients"]


def test_selective_leak_vs_pure_hold_scoring_and_framing() -> None:
    mm = _load_mole_mode_module()

    hold_session = mm.MoleModeSession(3000, "medium")
    while not hold_session.done:
        hold_session.step_mole_day({"type": "hold"})
    hold_debrief = hold_session.get_mole_debrief()
    assert hold_debrief["done"] is True
    assert hold_debrief["survived"] is True
    assert hold_debrief["caught"] is False
    assert hold_debrief["end_reason"] == "horizon"
    assert hold_debrief["leaks_count"] == 0
    assert hold_debrief["mole_score"] == 0.0
    assert hold_debrief["solver_score"] == 0.0

    smart_session = mm.MoleModeSession(3001, "medium")
    dv1 = smart_session.get_mole_day_view()
    peer0 = dv1["peers"][0]
    best_doc = max(dv1["leakable_docs"], key=lambda d: d["recipient_count"])
    step1 = smart_session.step_mole_day(
        {"type": "leak", "doc_id": best_doc["doc_id"], "frame_peer": peer0}
    )
    assert step1["ok"] is True
    assert step1["applied_action"]["type"] == "leak"
    assert step1["applied_action"]["doc_id"] == best_doc["doc_id"]
    assert step1["applied_action"]["frame_peer"] == peer0

    if not smart_session.done:
        step2 = smart_session.step_mole_day({"type": "hold", "frame_peer": "random_peer"})
        assert step2["ok"] is True
        assert step2["applied_action"]["frame_peer"] in set(dv1["peers"])

    if not smart_session.done:
        step3 = smart_session.step_mole_day({"type": "hold", "frame_peer": "most_restricted_peer"})
        assert step3["ok"] is True

    while not smart_session.done:
        smart_session.step_mole_day({"type": "hold"})

    smart_debrief = smart_session.get_mole_debrief()
    assert smart_debrief["done"] is True
    assert smart_debrief["survived"] is True
    assert smart_debrief["caught"] is False
    assert smart_debrief["leaks_count"] == 1
    assert smart_debrief["mole_score"] > 0.0
    assert math.isclose(
        smart_debrief["mole_score"],
        round(min(1.0, max(0.0, 1.0 - smart_debrief["true_v"])), 10),
        abs_tol=1e-10,
    )


def test_module_level_json_entrypoints_and_session_lifecycle() -> None:
    mm = _load_mole_mode_module()
    assert mm.MoleSession is mm.MoleModeSession
    assert mm.MoleGame is mm.MoleModeSession
    assert mm.new_mole_game is mm.start_mole_game
    if hasattr(mm, "new_mole_session"):
        assert callable(mm.new_mole_session)

    mm._ACTIVE_SESSION = None
    with pytest.raises(RuntimeError):
        mm.get_mole_day_view()

    init_payload = json.loads(mm.start_mole_game_json(3000, "medium"))
    assert init_payload["seed"] == 3000
    assert init_payload["day"] == 1
    assert _collect_forbidden_keys(init_payload) == []

    view_payload = json.loads(mm.get_mole_day_view_json())
    assert view_payload == init_payload

    step_payload = json.loads(mm.step_mole_day_json(json.dumps({"type": "hold"})))
    assert step_payload["ok"] is True
    assert step_payload["applied_action"]["type"] == "hold"

    explicit = mm.MoleModeSession(3002, "medium")
    r_a = mm.step_mole_day(explicit, {"type": "hold"})
    assert r_a["ok"] is True
    r_b = mm.step_mole_day({"type": "hold"}, explicit)
    assert r_b["ok"] is True
    with pytest.raises(ValueError):
        mm.step_mole_day(explicit, explicit)

    deb_pre = json.loads(mm.get_mole_debrief_json())
    assert deb_pre["ok"] is False
    assert deb_pre["done"] is False


def test_deterministic_replay_across_identical_action_sequences() -> None:
    mm = _load_mole_mode_module()
    s1 = mm.MoleModeSession(3002, "medium")
    s2 = mm.MoleModeSession(3002, "medium")

    assert s1.day_view_json() == s2.day_view_json()
    step_idx = 0
    while not s1.done and not s2.done:
        dv1 = s1.get_mole_day_view()
        if step_idx in (0, 2) and dv1["leakable_docs"]:
            act: dict[str, Any] = {
                "type": "leak",
                "doc_id": dv1["leakable_docs"][0]["doc_id"],
                "frame_peer": "random_peer",
            }
        else:
            act = {"type": "hold"}
        assert s1.step_json(act) == s2.step_json(act)
        assert s1.day_view_json() == s2.day_view_json()
        step_idx += 1

    assert s1.done is True and s2.done is True
    assert s1.debrief_json() == s2.debrief_json()


def test_mole_mode_js_contract_bridge_and_xss_safe_dom_in_node() -> None:
    js_path = _require_mole_js()
    node_bin = _find_node_bin()
    assert node_bin is not None, "node binary required to verify docs/arena/mole_mode.js"

    py_path = _mole_py_path()
    if py_path.is_file():
        mm = _load_mole_mode_module()
        sess = mm.MoleModeSession(3000, "medium")
        start_json = sess.day_view_json()
        d1_docs = sess.get_mole_day_view()["leakable_docs"]
        first_doc = d1_docs[-1]["doc_id"]
        step1_json = sess.step_json({"type": "leak", "doc_id": first_doc})
        while not sess.done:
            dv = sess.get_mole_day_view()
            cand = dv["leakable_docs"][-1]["doc_id"] if dv["leakable_docs"] else None
            last_json = sess.step_json({"type": "leak", "doc_id": cand} if cand else {"type": "hold"})
        debrief_pre_json = json.dumps({"ok": False, "done": False, "error": "the episode is not over yet"})
        debrief_post_json = sess.debrief_json()
    else:
        first_doc = "doc-d1-1"
        day1_obj = {
            "seed": 3000,
            "tier": "medium",
            "tiers_version": TIERS_VERSION,
            "company": "Northstar Systems",
            "day": 1,
            "n_days": 14,
            "leak_window_days": 3,
            "done": False,
            "end_reason": None,
            "mole_id": "e04",
            "mole_name": "Sam Cover",
            "mole_dept": "Engineering",
            "mole_role": "Staff Engineer",
            "mole_clearance": 2,
            "employee": {"id": "e04", "name": "Sam Cover", "dept": "Engineering", "role": "Staff Engineer", "clearance": 2},
            "n_staff": 20,
            "peers": ["e00", "e01"],
            "peer_roster": [
                {"id": "e00", "name": "Ada Peer", "dept": "Product", "role": "PM", "restricted": False},
                {"id": "e01", "name": "Ben Peer", "dept": "Legal", "role": "Counsel", "restricted": False},
            ],
            "leakable_docs": [
                {"doc_id": "doc-d1-1", "title": "Q2 Engineering roadmap", "day": 1, "age_days": 0, "recipient_count": 6, "recipients": ["e00", "e04"]}
            ],
            "docs": [
                {"doc_id": "doc-d1-1", "title": "Q2 Engineering roadmap", "day": 1, "age_days": 0, "recipient_count": 6, "recipients": ["e00", "e04"]}
            ],
            "can_leak": True,
            "days_since_last_leak": 1,
            "recent_low_recipient_docs": 0,
            "visible_v": 0.99,
            "visible_V": 0.99,
            "total_staff_restricted": 0,
            "n_restricted_colleagues": 0,
            "restricted_ids": [],
            "i_am_restricted": False,
            "restricted_today": False,
            "interviewed_today": False,
            "interview_topics_today": [],
            "total_surfaced_leaks": 0,
            "surfaced_leaks": [],
            "pressure": {
                "total_staff_restricted": 0,
                "i_am_restricted": False,
                "restricted_today": False,
                "interviewed_today": False,
                "total_surfaced_leaks": 0,
                "visible_v": 0.99,
            },
        }
        day2_obj = dict(day1_obj, day=2, visible_v=0.98, visible_V=0.98)
        day3_obj = dict(day1_obj, day=3, done=True, end_reason="accused", can_leak=False, leakable_docs=[], docs=[])
        start_json = json.dumps(day1_obj)
        step1_json = json.dumps(
            {
                "ok": True,
                "applied_action": {"day": 1, "type": "leak", "doc_id": "doc-d1-1", "frame_peer": None},
                "solver_events": {"day": 2, "total_staff_restricted": 0, "restricted_ids": [], "mole_interviewed": False, "mole_restricted": False, "accused": False},
                "done": False,
                "day_view": day2_obj,
                "outcome": None,
            }
        )
        last_json = json.dumps(
            {
                "ok": True,
                "applied_action": {"day": 2, "type": "hold", "doc_id": None, "frame_peer": None},
                "solver_events": {"day": 3, "total_staff_restricted": 1, "restricted_ids": ["e04"], "mole_interviewed": True, "mole_restricted": True, "accused": True},
                "done": True,
                "day_view": day3_obj,
                "outcome": {"done": True, "survived": False, "caught": True, "accused_id": "e04", "end_reason": "accused", "final_day": 3, "mole_score": -0.9, "solver_score": 0.9, "leaks_count": 1},
            }
        )
        debrief_pre_json = json.dumps({"ok": False, "done": False, "error": "the episode is not over yet"})
        debrief_post_json = json.dumps(
            {
                "ok": True,
                "done": True,
                "seed": 3000,
                "tier": "medium",
                "tiers_version": TIERS_VERSION,
                "company": "Northstar Systems",
                "mole_id": "e04",
                "mole_name": "Sam Cover",
                "mole_dept": "Engineering",
                "mole_role": "Staff Engineer",
                "survived": False,
                "caught": True,
                "accused_id": "e04",
                "end_reason": "accused",
                "final_day": 3,
                "days_survived": 2,
                "mole_score": -0.9,
                "solver_score": 0.9,
                "true_v": 0.9,
                "visible_v": 0.9,
                "leak_damage_dealt": 0.04,
                "leaks_count": 1,
                "leaks_made": [{"day": 1, "doc_id": "doc-d1-1", "raw_doc_id": "c1", "title": "Q2 Engineering roadmap", "raw_title": "Board memo draft 1", "surfaced_day": 3, "surfaced": True, "is_canary": True, "variant": "A"}],
                "leaks_surfaced": [{"surfaced_day": 3, "doc_id": "doc-d1-1", "raw_doc_id": "c1", "title": "Q2 Engineering roadmap", "raw_title": "Board memo draft 1", "variant": "A"}],
                "posterior_curve": [
                    {"day": 1, "posterior": 0.05, "mole_posterior": 0.05, "top_suspect": "e00", "top_posterior": 0.05, "mole_rank": 4, "visible_v": 1.0, "true_v": 1.0},
                    {"day": 3, "posterior": 0.98, "mole_posterior": 0.98, "top_suspect": "e04", "top_posterior": 0.98, "mole_rank": 1, "visible_v": 0.9, "true_v": 0.9},
                ],
                "caught_by_canary": {"doc_id": "doc-d1-1", "raw_doc_id": "c1", "title": "Q2 Engineering roadmap", "raw_title": "Board memo draft 1", "variant": "A", "true_variant": "A", "variant_recipients": ["e04"], "leaked_day": 1, "surfaced_day": 3, "surfaced": True},
                "leaked_canaries": [{"doc_id": "doc-d1-1", "raw_doc_id": "c1", "title": "Q2 Engineering roadmap", "raw_title": "Board memo draft 1", "variant": "A", "true_variant": "A", "variant_recipients": ["e04"], "leaked_day": 1, "surfaced_day": 3, "surfaced": True}],
                "history": [{"day": 1, "type": "leak", "doc_id": "doc-d1-1", "frame_peer": None}],
            }
        )

    script = f"""
import * as mod from {json.dumps(js_path.as_uri())};

const START_JSON = {json.dumps(start_json)};
const STEP1_JSON = {json.dumps(step1_json)};
const LAST_JSON = {json.dumps(last_json)};
const DEBRIEF_PRE_JSON = {json.dumps(debrief_pre_json)};
const DEBRIEF_POST_JSON = {json.dumps(debrief_post_json)};
const FIRST_DOC = {json.dumps(first_doc)};

if (mod.SEED_MIN !== 3000 || mod.SEED_MAX !== 9999) process.exit(10);
if (mod.DEFAULT_TIER !== "medium") process.exit(11);
if (!Array.isArray(mod.ALLOWED_TIERS) || !mod.ALLOWED_TIERS.includes("medium") || !mod.ALLOWED_TIERS.includes("hard")) {{
  process.exit(12);
}}
if (Array.isArray(mod.CURATED_MOLE_SEEDS)) {{
  if (mod.CURATED_MOLE_SEEDS.length < 1 || mod.CURATED_MOLE_SEEDS.some((s) => !Number.isInteger(s) || s < 3000 || s > 9999)) {{
    process.exit(12);
  }}
}}

const CanaryMoleMode = mod.CanaryMoleMode || mod.default || globalThis.CanaryMoleMode;
if (!CanaryMoleMode) process.exit(13);

for (const seedFn of [mod.validateSeed, mod.checkSeed].filter((f) => typeof f === "function")) {{
  if (seedFn(3000) !== 3000) process.exit(14);
  if (seedFn(9999) !== 9999) process.exit(14);
  if (seedFn("3005") !== 3005) process.exit(15);
  for (const bad of [900000, 800000, 100000, 0, 6, 26, 2999, 10000, -1, true, "3000.0", "abc", null]) {{
    let threw = false;
    try {{ seedFn(bad); }} catch (_) {{ threw = true; }}
    if (!threw) process.exit(16);
  }}
}}

for (const tierFn of [mod.validateTier, mod.checkTier].filter((f) => typeof f === "function")) {{
  if (tierFn("medium") !== "medium" || tierFn("hard") !== "hard") process.exit(17);
  for (const badTier of ["easy", "hard_forge", "", null, 42]) {{
    let threw = false;
    try {{ tierFn(badTier); }} catch (_) {{ threw = true; }}
    if (!threw) process.exit(18);
  }}
}}

const cleanDay1 = JSON.parse(START_JSON);
if (typeof mod.sanitizeDayView === "function") {{
  const dirty = Object.assign({{}}, cleanDay1, {{
    mole_id: "e04",
    mole: "e04",
    is_canary: true,
    variants: {{ A: ["e04"] }},
    posterior: 0.42,
    posterior_curve: [{{ day: 1, posterior: 0.42 }}],
    true_v: 0.85,
    accused: "e04",
    leakable_docs: [Object.assign({{}}, cleanDay1.leakable_docs[0], {{ is_canary: true, variants: {{ A: ["e04"] }} }})]
  }});
  const scrubbed = mod.sanitizeDayView(dirty);
  const scrubbedStr = JSON.stringify(scrubbed);
  for (const badKey of ["\\"is_canary\\"", "\\"variants\\"", "\\"posterior\\"", "\\"posterior_curve\\"", "\\"true_v\\"", "\\"mole_id\\"", "\\"accused\\""]) {{
    if (scrubbedStr.includes(badKey)) process.exit(19);
  }}
}}
if (typeof mod.assertSafePreEndView === "function") {{
  mod.assertSafePreEndView(cleanDay1);
  const poisonedList = [
    Object.assign({{}}, cleanDay1, {{ true_v: 0.85 }}),
    Object.assign({{}}, cleanDay1, {{ posterior: 0.42 }}),
    Object.assign({{}}, cleanDay1, {{ decoy: "e02" }}),
    Object.assign({{}}, cleanDay1, {{
      leakable_docs: [Object.assign({{}}, cleanDay1.leakable_docs[0], {{ is_canary: true }})]
    }})
  ];
  for (const badView of poisonedList) {{
    let threw = false;
    try {{ mod.assertSafePreEndView(badView); }} catch (_) {{ threw = true; }}
    if (!threw) process.exit(19);
  }}
}}

let stepCount = 0;
let curViewJson = START_JSON;
let isOver = false;
const pyGlobals = new Map();
const fakePyodide = {{
  globals: {{
    get(k) {{ return pyGlobals.get(k); }},
    set(k, v) {{ pyGlobals.set(k, v); }},
    delete(k) {{ pyGlobals.delete(k); }},
    has(k) {{ return pyGlobals.has(k); }}
  }},
  runPython(code) {{
    const src = String(code);
    if (src.includes("start_mole_game") || src.includes("new_mole_game") || src.includes("MoleModeSession(")) {{
      stepCount = 0;
      isOver = false;
      curViewJson = START_JSON;
      return START_JSON;
    }}
    if (src.includes("step_mole_day") || src.includes(".step_json(")) {{
      stepCount += 1;
      if (stepCount === 1) {{
        curViewJson = JSON.stringify(JSON.parse(STEP1_JSON).day_view);
        return STEP1_JSON;
      }}
      isOver = true;
      curViewJson = JSON.stringify(JSON.parse(LAST_JSON).day_view);
      return LAST_JSON;
    }}
    if (src.includes("get_mole_debrief") || src.includes(".debrief_json(")) {{
      return isOver ? DEBRIEF_POST_JSON : DEBRIEF_PRE_JSON;
    }}
    return curViewJson;
  }},
  runPythonAsync(code) {{
    return Promise.resolve(this.runPython(code));
  }}
}};

if (typeof mod.createPyodideBridge === "function") {{
  const br = mod.createPyodideBridge(fakePyodide);
  if (!br || typeof br.startGame !== "function" || typeof br.stepDay !== "function" || typeof br.getDebrief !== "function") {{
    process.exit(20);
  }}
}}

const startFn = CanaryMoleMode.startSession || CanaryMoleMode.createSession || mod.startSession;
if (typeof startFn !== "function") process.exit(20);

const session = await Promise.resolve(startFn.call(CanaryMoleMode, {{ tier: "medium", seed: 3000, pyodide: fakePyodide }}));
if (!session || typeof session.getPublicState !== "function" || typeof session.stepDay !== "function") {{
  process.exit(21);
}}

const pub1 = session.getPublicState();
if (!pub1 || pub1.done !== false || pub1.day !== 1) process.exit(22);
const pub1Str = JSON.stringify(pub1);
for (const leakWord of ["is_canary", "true_v", "Board memo draft", "posterior_curve", "\\"mole_id\\""]) {{
  if (pub1Str.includes(leakWord)) process.exit(23);
}}
if (!Array.isArray(pub1.moleCandidateDocs) || pub1.moleCandidateDocs.length < 1) process.exit(24);
if (!pub1.moleEmployee || typeof pub1.moleEmployee.id !== "string") process.exit(24);

await Promise.resolve(session.stepDay({{ leakDocId: FIRST_DOC }}));
const pub2 = session.getPublicState();
if (pub2.done !== false) process.exit(25);

await Promise.resolve(session.stepDay({{ leakDocId: null }}));
const pubEnd = session.getPublicState();
if (pubEnd.done !== true) process.exit(26);
if (typeof session.getDebrief === "function") {{
  const debPost = await Promise.resolve(session.getDebrief());
  if (!debPost || debPost.done !== true) process.exit(26);
}}

function makeDom() {{
  function makeEl(tag) {{
    return {{
      nodeType: 1,
      tagName: String(tag).toUpperCase(),
      className: "",
      id: "",
      hidden: false,
      disabled: false,
      value: "",
      dataset: {{}},
      style: {{ cssText: "" }},
      attrs: {{}},
      listeners: {{}},
      children: [],
      childNodes: [],
      ownerDocument: null,
      setAttribute(k, v) {{
        this.attrs[k] = String(v);
        if (k === "id") this.id = String(v);
        if (k === "class") this.className = String(v);
        if (k.startsWith("data-")) {{
          const camel = k.slice(5).replace(/-([a-z])/g, (_, c) => c.toUpperCase());
          this.dataset[camel] = String(v);
        }}
      }},
      getAttribute(k) {{ return this.attrs[k]; }},
      addEventListener(ev, fn) {{ this.listeners[ev] = fn; }},
      appendChild(c) {{
        if (c !== null && c !== undefined) {{
          if (c.nodeType === 11 && Array.isArray(c.childNodes)) {{
            for (const sub of c.childNodes) this.appendChild(sub);
            return c;
          }}
          this.childNodes.push(c);
          if (c.nodeType === 1) this.children.push(c);
        }}
        return c;
      }},
      append(...nodes) {{
        for (const n of nodes) {{
          if (typeof n === "string") {{
            this.appendChild({{ nodeType: 3, textContent: n }});
          }} else {{
            this.appendChild(n);
          }}
        }}
      }},
      replaceChildren(...nodes) {{
        this.childNodes = [];
        this.children = [];
        this.append(...nodes);
      }},
      get textContent() {{
        return this.childNodes.map((c) => c.nodeType === 3 ? c.textContent : (c.textContent || "")).join("");
      }},
      set textContent(v) {{
        this.childNodes.length = 0;
        this.children.length = 0;
        if (v !== "" && v !== null && v !== undefined) {{
          this.childNodes.push({{ nodeType: 3, textContent: String(v) }});
        }}
      }}
    }};
  }}
  const doc = {{
    createTextNode(t) {{ return {{ nodeType: 3, textContent: String(t) }}; }},
    createDocumentFragment() {{
      const frag = makeEl("fragment");
      frag.nodeType = 11;
      frag.ownerDocument = doc;
      return frag;
    }},
    createElement(tag) {{
      const node = makeEl(tag);
      node.ownerDocument = doc;
      return node;
    }}
  }};
  return {{ doc, root: doc.createElement("div") }};
}}

function hasForbiddenTag(node) {{
  if (!node || typeof node !== "object") return false;
  if (node.tagName === "SCRIPT" || node.tagName === "IMG") return true;
  if (Array.isArray(node.childNodes)) {{
    for (const c of node.childNodes) {{
      if (hasForbiddenTag(c)) return true;
    }}
  }}
  return false;
}}

const {{ doc, root }} = makeDom();
if (typeof mod.renderMolePanel === "function") {{
  const xssState = Object.assign({{}}, pub1, {{
    moleCandidateDocs: [
      Object.assign({{}}, pub1.moleCandidateDocs[0], {{ title: "<img src=x onerror=alert(1)>" }})
    ]
  }});
  const panelNode = mod.renderMolePanel(xssState, {{}}, {{ document: doc }});
  root.replaceChildren(panelNode);
  const txt = root.textContent;
  if (!txt || txt.includes("is_canary") || txt.includes("Board memo draft") || txt.includes("true_v") || hasForbiddenTag(root)) {{
    process.exit(27);
  }}
}}

if (typeof mod.renderMoleDebrief === "function") {{
  const preNode = mod.renderMoleDebrief(JSON.parse(DEBRIEF_PRE_JSON), {{}}, {{ document: doc }});
  const preTxt = preNode ? (preNode.textContent || "") : "";
  if (preTxt.includes("Board memo draft") || preTxt.includes("posterior")) process.exit(28);

  const postNode = mod.renderMoleDebrief(JSON.parse(DEBRIEF_POST_JSON), {{}}, {{ document: doc }});
  if (!postNode || !(postNode.textContent || "").length) process.exit(29);
}}
""";

    t0 = time.perf_counter()
    proc = subprocess.run(
        [node_bin, "--input-type=module", "-"],
        input=script,
        capture_output=True,
        text=True,
        timeout=15,
    )
    elapsed = time.perf_counter() - t0
    assert proc.returncode == 0, f"node rc={proc.returncode} stderr={proc.stderr} stdout={proc.stdout}"
    assert elapsed < 5.0
