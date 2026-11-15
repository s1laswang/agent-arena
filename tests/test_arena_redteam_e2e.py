from __future__ import annotations

import importlib
import importlib.util
import inspect
import io
import json
from pathlib import Path
import socket
import sys
import tokenize
from typing import Any
import urllib.request

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from canary.arena.be_the_mole import (
    BeTheMoleSession,
    check_arena_seed,
    create_session,
    list_mole_advisors,
)
from canary.arena.living_office import (
    BIAS_TYPES,
    LivingOfficeSession,
    list_living_office_variants,
    list_mole_opponents,
    list_v16_checkpoint_replays,
    load_v16_checkpoint_replay,
)
from canary.rules import HELDOUT_SEEDS, JUDGE_SEEDS

ARENA_DIR = ROOT / "canary" / "arena"
OWNED_FILES: tuple[Path, ...] = (
    ROOT / "scripts" / "verify_mole_strategies_gate.py",
    ROOT / "tests" / "test_verify_mole_strategies_gate.py",
    Path(__file__).resolve(),
)

OPTIONAL_ARENA_MODULES: tuple[str, ...] = (
    "canary.arena.head_to_head",
    "canary.arena.scenarios",
    "canary.arena.server",
)

HASH_CHAR = chr(35)
EM_DASH = chr(0x2014)
EN_DASH = chr(0x2013)
UNICODE_MINUS = chr(0x2212)

FORBIDDEN_JS_SINKS: tuple[str, ...] = (
    "innerHTML",
    "outerHTML",
    "insertAdjacentHTML",
    "document.write",
)

FORBIDDEN_SHARED_PRE_DONE_KEYS: frozenset[str] = frozenset(
    {
        "true_mole",
        "true_mole_id",
        "mole_id",
        "mole",
        "is_canary",
        "bias_tags",
        "canary_xray",
        "variants",
        "mole_variant",
        "shown_variant",
        "select_weights",
        "daily_p_mole",
        "primary_suspect",
        "secondary_suspect",
        "target_suspect",
        "focal_rumor_suspects",
    }
)

FORBIDDEN_JSON_TOKENS: tuple[str, ...] = (
    '"true_mole"',
    '"true_mole_id"',
    '"mole_id"',
    '"is_canary"',
    '"bias_tags"',
)


def _collect_dict_keys(obj: Any, out: set[str]) -> None:
    if isinstance(obj, dict):
        for k, v in obj.items():
            out.add(str(k))
            _collect_dict_keys(v, out)
    elif isinstance(obj, list):
        for item in obj:
            _collect_dict_keys(item, out)


def _import_optional_arena_module(mod_name: str) -> Any | None:
    try:
        spec = importlib.util.find_spec(mod_name)
    except ModuleNotFoundError:
        return None
    if spec is None:
        return None
    return importlib.import_module(mod_name)


@pytest.fixture(autouse=True)
def _enforce_zero_network_and_zero_api_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GOOGLE_API_KEY", "")
    monkeypatch.setenv("GEMINI_API_KEY", "")
    monkeypatch.setenv("OPENAI_API_KEY", "")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")

    def _deny_network(*args: Any, **kwargs: Any) -> None:
        raise AssertionError(f"network access is strictly forbidden in Arena red-team QA: {args!r}")

    monkeypatch.setattr(socket.socket, "connect", _deny_network)
    monkeypatch.setattr(socket.socket, "connect_ex", _deny_network)
    monkeypatch.setattr(socket, "create_connection", _deny_network)
    monkeypatch.setattr(urllib.request, "urlopen", _deny_network)


def test_zero_network_and_zero_api_key_enforcement_e2e() -> None:
    with pytest.raises(AssertionError, match="strictly forbidden"):
        socket.create_connection(("example.com", 443))

    sock = socket.socket()
    try:
        with pytest.raises(AssertionError, match="strictly forbidden"):
            sock.connect(("127.0.0.1", 9))
    finally:
        sock.close()

    advisors = list_mole_advisors()
    assert len(advisors) >= 7
    assert json.loads(json.dumps(advisors, allow_nan=False))

    btm = create_session("medium", 3000)
    st0 = btm.state_dict()
    assert st0["done"] is False
    st1 = btm.step_turn(leak="oldest", frame="random_peer")
    assert st1["day"] == 2
    fin_btm = btm.auto_play("frontier_synthesis_v14")
    assert fin_btm["done"] is True
    rev = btm.reveal_dict()
    assert set(rev["investigators"].keys()) == {"gemini_proxy", "solver", "hinted_heuristic"}
    assert json.loads(json.dumps(rev, allow_nan=False))["true_mole_id"] == rev["true_mole_id"]

    variants = list_living_office_variants()
    opponents = list_mole_opponents()
    replays = list_v16_checkpoint_replays()
    assert len(variants) >= 6
    assert "frontier_synthesis_v14" in opponents
    assert len(replays) == 10

    ckpt = load_v16_checkpoint_replay("v5_full9_cocktail", seed=30)
    assert ckpt["replay_verified"] is True
    assert ckpt["seed"] == 30
    assert ckpt["done"] is True
    assert ckpt["xray"]["solver_comparison"]["bit_exact_immunity"] is True

    lo = LivingOfficeSession(
        tier="medium",
        seed=3010,
        variant="v5_full9_cocktail",
        mole_opponent="frontier_synthesis_v14",
    )
    assert lo.call_tool("list_employees", {})["ok"] is True
    step_g = lo.step_auto_investigator("gemini_proxy")
    assert step_g["policy"] == "gemini_proxy"
    if not lo.done:
        step_s = lo.step_auto_investigator("solver")
        assert step_s["policy"] == "solver"
    if not lo.done:
        lo.call_tool("accuse", {"employee": "e00"})
    assert lo.done is True
    xray = lo.bias_xray_dict()
    assert set(BIAS_TYPES).issubset(set(xray["biases"].keys()))
    assert json.loads(json.dumps(xray, allow_nan=False))["variant"] == "v5_full9_cocktail"

    for mod_name in OPTIONAL_ARENA_MODULES:
        mod = _import_optional_arena_module(mod_name)
        if mod is None:
            continue
        for helper_name in ("list_scenarios", "list_duel_seeds", "list_opponents", "list_modes"):
            fn = getattr(mod, helper_name, None)
            if callable(fn):
                sig = inspect.signature(fn)
                req = [
                    p
                    for p in sig.parameters.values()
                    if p.default is inspect.Parameter.empty
                    and p.kind in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
                ]
                if not req:
                    res = fn()
                    encoded = json.dumps(res, allow_nan=False)
                    assert EM_DASH not in encoded and EN_DASH not in encoded


def test_pre_done_zero_spoiler_and_mole_swap_invariance() -> None:
    btm = BeTheMoleSession("medium", 3006)
    assert not btm.done
    with pytest.raises(ValueError):
        btm.reveal_dict()

    for step_idx in range(2):
        if btm.done:
            break
        state = btm.state_dict()
        assert state["done"] is False
        assert state["reveal"] is None
        raw_btm = json.dumps(state, allow_nan=False)
        for secret_tok in FORBIDDEN_JSON_TOKENS:
            assert secret_tok not in raw_btm
        btm_keys: set[str] = set()
        _collect_dict_keys(state, btm_keys)
        assert btm_keys.isdisjoint(FORBIDDEN_SHARED_PRE_DONE_KEYS)
        assert btm_keys.isdisjoint({"accused", "correct", "true_v", "mole_summary"})
        for doc in state["mole_view"]["docs"]:
            assert set(doc.keys()) == {"doc_id", "title", "recipient_count", "age_days"}
        if step_idx == 0:
            btm.step_turn(leak="none", frame="none")
        else:
            btm.auto_play("frontier_synthesis_v14", max_turns=1)

    solver_docs = btm._worlds["solver"].env._doc_by_id.values()
    assert any(bool(d.get("is_canary")) for d in solver_docs)
    if not btm.done:
        with pytest.raises(ValueError):
            btm.reveal_dict()

    lo_a = LivingOfficeSession("medium", 3008, variant="v5_full9_cocktail", mole_opponent="frontier_synthesis_v14")
    lo_b = LivingOfficeSession("medium", 3008, variant="v5_full9_cocktail", mole_opponent="frontier_synthesis_v14")
    assert not lo_a.done

    with pytest.raises(ValueError):
        lo_a.bias_xray_dict()

    orig_mole = lo_b.env._world.mole
    alt_mole = next(
        eid
        for eid in lo_b.env._ids
        if eid != orig_mole and eid != lo_b.env._world.decoy
    )
    lo_b.env._world.mole = alt_mole

    assert json.dumps(lo_a.state_dict(), sort_keys=True, allow_nan=False) == json.dumps(
        lo_b.state_dict(), sort_keys=True, allow_nan=False
    )

    neutral_emp = next(
        eid
        for eid in lo_a.env._ids
        if eid not in {orig_mole, alt_mole, lo_a.env._world.decoy}
    )
    shared_actions: tuple[tuple[str, dict[str, Any]], ...] = (
        ("list_employees", {}),
        ("list_documents", {"day_from": 1, "day_to": 1}),
        ("interview", {"employee": neutral_emp, "topic": "workload"}),
        ("advance_day", {}),
        ("search_messages", {"query": "doc", "day_from": 1, "day_to": 2}),
    )
    for tool_name, tool_args in shared_actions:
        lo_a.call_tool(tool_name, tool_args)
        lo_b.call_tool(tool_name, tool_args)
        assert not lo_a.done
        with pytest.raises(ValueError):
            lo_a.bias_xray_dict()

        st_a = lo_a.state_dict()
        st_b = lo_b.state_dict()
        assert st_a["floorplan"] == st_b["floorplan"]
        assert st_a["social_feed"] == st_b["social_feed"]
        assert st_a["verdict"] is None
        assert st_a["xray"] is None

        raw_lo = json.dumps(st_a, allow_nan=False)
        for secret_tok in FORBIDDEN_JSON_TOKENS:
            assert secret_tok not in raw_lo
        assert '"player_mole_id"' not in raw_lo
        lo_keys: set[str] = set()
        _collect_dict_keys(st_a, lo_keys)
        assert lo_keys.isdisjoint(FORBIDDEN_SHARED_PRE_DONE_KEYS)

        public_lower = json.dumps(
            {"floorplan": st_a["floorplan"], "social_feed": st_a["social_feed"]},
            allow_nan=False,
        ).lower()
        for bias_name in BIAS_TYPES:
            assert bias_name not in public_lower

    h2h_mod = _import_optional_arena_module("canary.arena.head_to_head")
    if h2h_mod is not None:
        sess_cls = getattr(h2h_mod, "HeadToHeadSession", None) or getattr(h2h_mod, "DuelSession", None)
        if sess_cls is not None:
            sig = inspect.signature(sess_cls)
            kwargs: dict[str, Any] = {}
            if "tier" in sig.parameters:
                kwargs["tier"] = "medium"
            if "seed" in sig.parameters:
                kwargs["seed"] = 3000
            h2h_sess = sess_cls(**kwargs)
            if hasattr(h2h_sess, "done") and not h2h_sess.done:
                if hasattr(h2h_sess, "state_dict"):
                    raw_h2h = json.dumps(h2h_sess.state_dict(), allow_nan=False)
                    for secret_tok in FORBIDDEN_JSON_TOKENS:
                        assert secret_tok not in raw_h2h
                if hasattr(h2h_sess, "reveal_dict"):
                    with pytest.raises(ValueError):
                        h2h_sess.reveal_dict()


def test_adversarial_seed_tier_and_selector_fuzzing() -> None:
    heldout_sample = min(HELDOUT_SEEDS)
    judge_sample = min(JUDGE_SEEDS)
    adversarial_seeds: tuple[Any, ...] = (
        True,
        False,
        3000.5,
        3000.0,
        float("nan"),
        float("inf"),
        "",
        "   ",
        "abc",
        "3000abc",
        "3000; rm -rf /",
        "<script>3000</script>",
        "0xbbc",
        "3000.0",
        "None",
        "null",
        None,
        [3000],
        {"seed": 3000},
        -100,
        -1,
        0,
        4,
        26,
        30,
        2999,
        10000,
        10001,
        30000,
        800000,
        heldout_sample,
        900000,
        judge_sample,
    )
    for bad_seed in adversarial_seeds:
        with pytest.raises(ValueError):
            check_arena_seed(bad_seed)
        with pytest.raises(ValueError):
            BeTheMoleSession("medium", bad_seed)
        with pytest.raises(ValueError):
            LivingOfficeSession("medium", bad_seed)

    adversarial_tiers: tuple[Any, ...] = (
        "easy",
        "hard_forge",
        "hard_rl",
        "",
        "   ",
        "MEDIUM",
        "HARD",
        "invalid_tier",
        None,
        123,
        True,
    )
    for bad_tier in adversarial_tiers:
        with pytest.raises(ValueError):
            BeTheMoleSession(bad_tier, 3000)
        with pytest.raises(ValueError):
            LivingOfficeSession(bad_tier, 3000)

    btm = BeTheMoleSession("medium", 3009)
    player_id = btm.state_dict()["company"]["player_mole_id"]
    for bad_leak in ("canary", "all_docs", "doc_999999", "../etc/passwd", 123, True):
        with pytest.raises(ValueError):
            btm.step_turn(leak=bad_leak, frame="none")
    assert btm.day == 1 and btm.turn_log == []

    for bad_frame in ("mole", "e999", player_id, "<svg onload=alert(1)>", 123, True):
        with pytest.raises(ValueError):
            btm.step_turn(leak="none", frame=bad_frame)
    assert btm.day == 1 and btm.turn_log == []

    for bad_advisor in ("nonexistent_advisor", "", "<script>"):
        with pytest.raises(ValueError):
            btm.auto_play(bad_advisor)

    for bad_turns in (-1, True, False, 1.5, "2"):
        with pytest.raises(ValueError):
            btm.auto_play("frontier_synthesis_v14", max_turns=bad_turns)

    for bad_variant in ("nonexistent_variant", "", "<img src=x onerror=alert(1)>"):
        with pytest.raises(ValueError):
            LivingOfficeSession("medium", 3009, variant=bad_variant)
        with pytest.raises(ValueError):
            load_v16_checkpoint_replay(bad_variant, seed=30)

    for bad_opp in ("unknown_mole_opponent", 123):
        with pytest.raises(ValueError):
            LivingOfficeSession("medium", 3009, mole_opponent=bad_opp)

    lo = LivingOfficeSession("medium", 3009)
    for bad_pol in ("unknown_investigator", "", "gpt4"):
        with pytest.raises(ValueError):
            lo.step_auto_investigator(bad_pol)

    for bad_ckpt_seed in (True, False, 30.5, "garbage", 0, 4, 26, 29, 34, 3000, 800000, 900000):
        with pytest.raises(ValueError):
            load_v16_checkpoint_replay("v5_full9_cocktail", seed=bad_ckpt_seed)

    for mod_name in ("canary.arena.head_to_head", "canary.arena.scenarios"):
        mod = _import_optional_arena_module(mod_name)
        if mod is None:
            continue
        for validator_name in ("check_arena_seed", "validate_seed", "validate_arena_seed"):
            vfn = getattr(mod, validator_name, None)
            if callable(vfn):
                for bad_s in (True, False, 3000.5, "garbage", 800000, 900000):
                    with pytest.raises(ValueError):
                        vfn(bad_s)


def test_strict_canary_craft_source_hygiene_across_arena_and_owned_files() -> None:
    arena_py_files = sorted(ARENA_DIR.rglob("*.py"))
    assert len(arena_py_files) >= 2
    arena_names = {p.name for p in arena_py_files}
    assert {"be_the_mole.py", "living_office.py"}.issubset(arena_names)

    py_targets: list[Path] = []
    seen_resolved: set[Path] = set()
    for p in (*arena_py_files, *OWNED_FILES):
        rp = p.resolve()
        assert rp.is_file(), f"missing expected Python file: {rp}"
        if rp not in seen_resolved:
            seen_resolved.add(rp)
            py_targets.append(rp)

    for py_path in py_targets:
        raw = py_path.read_text(encoding="utf-8")
        assert raw.isascii() is True, f"non-ASCII character in {py_path}"
        assert HASH_CHAR not in raw, f"forbidden hash character in {py_path}"
        assert EM_DASH not in raw, f"forbidden em dash in {py_path}"
        assert EN_DASH not in raw, f"forbidden en dash in {py_path}"
        assert UNICODE_MINUS not in raw, f"forbidden unicode minus in {py_path}"
        tokens = list(tokenize.generate_tokens(io.StringIO(raw).readline))
        comments = [tok for tok in tokens if tok.type == tokenize.COMMENT]
        assert comments == [], f"comment tokens found in {py_path}"

    arena_js_files = sorted(ARENA_DIR.rglob("*.js"))
    for js_path in arena_js_files:
        raw_js = js_path.read_text(encoding="utf-8")
        assert raw_js.isascii() is True, f"non-ASCII character in {js_path}"
        assert EM_DASH not in raw_js, f"forbidden em dash in {js_path}"
        assert EN_DASH not in raw_js, f"forbidden en dash in {js_path}"
        assert UNICODE_MINUS not in raw_js, f"forbidden unicode minus in {js_path}"
        for sink in FORBIDDEN_JS_SINKS:
            assert sink not in raw_js, f"forbidden DOM XSS sink {sink} in {js_path}"
