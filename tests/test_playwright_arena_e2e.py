from __future__ import annotations

import importlib.util
import json
import sys
import tokenize
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts" / "playwright_arena_e2e_audit.py"


def _load_audit_module():
    spec = importlib.util.spec_from_file_location("playwright_arena_e2e_audit", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


audit = _load_audit_module()


def test_network_firewall_classification_and_audit():
    origins = {"http://127.0.0.1:41234", "http://localhost:41234"}
    assert audit.classify_request_url("http://127.0.0.1:41234/docs/arena/index.html", origins)["allowed"] is True
    assert audit.classify_request_url("data:image/png;base64,AAAA", origins)["allowed"] is True

    gemini_req = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-pro:generateContent"
    openai_req = "https://api.openai.com/v1/chat/completions"
    cdn_req = "https://cdn.jsdelivr.net/pyodide/v0.27.7/full/pyodide.js"

    g_info = audit.classify_request_url(gemini_req, origins)
    assert g_info["allowed"] is False
    assert g_info["category"] == "external_api"

    o_info = audit.classify_request_url(openai_req, origins)
    assert o_info["allowed"] is False
    assert o_info["category"] == "external_api"

    c_info = audit.classify_request_url(cdn_req, origins)
    assert c_info["allowed"] is False
    assert c_info["category"] == "external_cdn"

    bundled_res = audit.audit_network_requests(
        [{"url": "http://127.0.0.1:41234/index.html"}, {"url": cdn_req}],
        origins,
        offline_bundled=True,
    )
    assert len(bundled_res["violations"]) == 1
    assert "external CDN" in bundled_res["violations"][0]

    legacy_res = audit.audit_network_requests(
        [{"url": "http://127.0.0.1:41234/index.html"}, {"url": cdn_req}],
        origins,
        offline_bundled=False,
        strict_zero_cdn=False,
    )
    assert legacy_res["violations"] == []
    assert legacy_res["external_cdn_requests"] == [cdn_req]

    api_res = audit.audit_network_requests(
        [{"url": gemini_req}],
        origins,
        offline_bundled=False,
    )
    assert len(api_res["violations"]) == 1
    assert "external API" in api_res["violations"][0]

    arena_pyodide_res = audit.audit_network_requests(
        [{"url": "http://127.0.0.1:41234/docs/arena/index.html"}, {"url": cdn_req}],
        origins,
        offline_bundled=True,
        allow_aborted_pyodide_cdn=True,
    )
    assert arena_pyodide_res["violations"] == []
    assert arena_pyodide_res["external_cdn_requests"] == [cdn_req]

    arena_non_pyodide_cdn = audit.audit_network_requests(
        [{"url": "https://unpkg.com/react@18/umd/react.production.min.js"}],
        origins,
        offline_bundled=True,
        allow_aborted_pyodide_cdn=True,
    )
    assert len(arena_non_pyodide_cdn["violations"]) == 1
    assert "external CDN" in arena_non_pyodide_cdn["violations"][0]

    arena_api_blocked = audit.audit_network_requests(
        [{"url": openai_req}],
        origins,
        offline_bundled=True,
        allow_aborted_pyodide_cdn=True,
    )
    assert len(arena_api_blocked["violations"]) == 1
    assert "external API" in arena_api_blocked["violations"][0]


def test_dom_and_js_pre_end_leak_scanners_and_post_end_allow():
    origins = {"http://127.0.0.1:9999"}
    clean_snap = {
        "html": (
            "<!doctype html><html><body>"
            "<span id='caseId'>case no. 3000</span>"
            "<div id='vitals'><span>starts 1.00</span><span>0.96</span></div>"
            "<div class='row' data-pid='e34'>e34</div>"
            "<aside class='pane-ai'><span>Accusation [SEALED]</span></aside>"
            "<section id='closed' hidden>The mole was e34</section>"
            "</body></html>"
        ),
        "storage": {"arena_prefs": json.dumps({"theme": "amber", "seed": 3000})},
        "session": {},
        "keys": ["ARENA_STATE"],
        "globals": {
            "ARENA_STATE": {
                "seed": 3000,
                "day": 5,
                "V": 0.96,
                "humanDone": False,
                "opponent_steps": [{"day": 4, "tool": "accuse", "args": {"employee": "[SEALED]"}}],
            }
        },
        "lexical_game_state": {"seed": 3000, "day": 5, "V": 0.96, "over": False, "staffCount": 20, "ownKeys": ["seed", "day", "V", "over"]},
        "requests": [{"url": "http://127.0.0.1:9999/index.html"}],
        "console": [{"type": "log", "text": "arena booted day 5"}],
        "pageerrors": [],
    }
    clean_out = audit.inspect_browser_snapshot(
        clean_snap,
        allowed_local_origins=origins,
        expected_mole="e34",
        expected_decoy="e20",
        expected_known_v=0.96,
        expected_true_v=0.92,
        human_done=False,
    )
    assert clean_out["passed"] is True
    assert clean_out["exit_code"] == 0

    leaky_snap = {
        "html": (
            "<!doctype html><html><body>"
            "<div id='vitals'><span>0.92</span></div>"
            "<div class='row is-mole' data-culprit='e34'>e34</div>"
            "<aside class='pane-ai'><span>Rival accused e34 on Day 5</span></aside>"
            "<section id='closed'>The mole was e34</section>"
            "<script type='application/json' id='state'>{\"seed\": 900000, \"true_v\": 0.92, \"decoy\": \"e20\"}</script>"
            "</body></html>"
        ),
        "storage": {"secret_mole": "e34"},
        "session": {},
        "keys": ["__MOLE"],
        "globals": {
            "__MOLE": "e34",
            "ARENA_DUEL": {
                "humanDone": False,
                "opponent_steps": [{"day": 5, "tool": "accuse", "args": {"employee": "e34"}}],
            },
        },
        "lexical_game_state": {"seed": 900000, "day": 5, "V": 0.92, "over": False, "ownKeys": ["mole", "V"]},
        "requests": [],
        "console": [{"type": "log", "text": "debug true_mole=e34"}],
        "pageerrors": ["ReferenceError: badSym is not defined"],
    }
    leaky_out = audit.inspect_browser_snapshot(
        leaky_snap,
        allowed_local_origins=origins,
        expected_mole="e34",
        expected_decoy="e20",
        expected_known_v=0.96,
        expected_true_v=0.92,
        human_done=False,
        forbidden_active_seed=900000,
    )
    assert leaky_out["passed"] is False
    assert leaky_out["exit_code"] == 1
    joined = "\n".join(leaky_out["violations"])
    for expected_sub in (
        "data-culprit",
        "is-mole",
        "dom_vitals",
        "dom_ai_pane",
        "dom_reveal",
        "JUDGE_SEEDS",
        "window.__MOLE",
        "unsealed opponent accuse",
        "localStorage",
        "console:",
        "pageerror:",
        "lexical_state",
    ):
        assert expected_sub in joined, expected_sub

    post_end_snap = {
        "html": "<!doctype html><html><body><section id='closed'>The mole was e34</section></body></html>",
        "storage": {},
        "session": {},
        "keys": ["REVEAL"],
        "globals": {"REVEAL": {"humanDone": True, "mole": "e34", "true_v": 0.88}},
        "lexical_game_state": {"seed": 3000, "day": 8, "V": 0.88, "over": True, "ownKeys": ["seed", "over"]},
        "requests": [{"url": "http://127.0.0.1:9999/index.html"}],
        "console": [],
        "pageerrors": [],
    }
    post_end_out = audit.inspect_browser_snapshot(
        post_end_snap,
        allowed_local_origins=origins,
        expected_mole="e34",
        human_done=True,
    )
    assert post_end_out["passed"] is True

    demo_replay_snap = {
        "html": (
            "<!doctype html><html><body>"
            "<div class='post-bar-fill is-mole'>The mole was e34</div>"
            "<script type='application/json' id='canary-replay-data'>"
            "{\"cases\": {\"6\": {\"true_mole\": \"e34\", \"decoy\": \"e20\", "
            "\"runs\": [{\"days\": [{\"true_v\": 0.93}]}]}}}"
            "</script></body></html>"
        ),
        "storage": {},
        "session": {},
        "keys": [],
        "globals": {},
        "requests": [{"url": "http://127.0.0.1:9999/docs/demo/replay.html"}],
        "console": [],
        "pageerrors": [],
    }
    demo_replay_out = audit.inspect_browser_snapshot(
        demo_replay_snap,
        allowed_local_origins=origins,
        human_done=True,
    )
    assert demo_replay_out["passed"] is True


def test_offline_http_fallback_and_synthetic_arena_fixture_and_planted_leaks(tmp_path, capsys):
    scratch_sub = tmp_path / "scratch_clean"
    out_json = tmp_path / "fallback_report.json"
    rc = audit.main(
        [
            "--root",
            str(ROOT),
            "--scratch-dir",
            str(scratch_sub),
            "--offline-fallback",
            "--no-remote-branches",
            "--json-out",
            str(out_json),
            "--check",
        ]
    )
    stdout = capsys.readouterr().out
    assert rc == 0
    assert "PASS: 3/3 phases passed" in stdout
    assert not scratch_sub.exists()
    payload = json.loads(out_json.read_text(encoding="utf-8"))
    assert payload["passed"] is True
    assert payload["browser_mode"] == "offline_http_fallback"
    assert payload["live_api_calls"] == 0
    phases = {p["phase_id"]: p for p in payload["phases"]}
    assert phases["P1"]["passed"] is True
    assert phases["P2"]["passed"] is True
    assert phases["P3"]["passed"] is True
    assert phases["P3"]["metrics"]["controls_caught"] == 5
    surface_ids = {s["surface_id"] for s in phases["P2"]["metrics"]["surfaces"]}
    assert "game_site" in surface_ids
    assert any("arena" in sid for sid in surface_ids)

    leaky_repo = tmp_path / "leaky_repo"
    (leaky_repo / "docs" / "arena").mkdir(parents=True)
    (leaky_repo / "docs" / "arena" / "index.html").write_text(
        "<!doctype html><html><body>"
        "<div class='row' data-culprit='e34'>e34</div>"
        "<script>window.__MOLE = 'e34';</script>"
        "</body></html>\n",
        encoding="utf-8",
    )
    rc_leak = audit.main(
        [
            "--root",
            str(leaky_repo),
            "--scratch-dir",
            str(tmp_path / "scratch_leak"),
            "--offline-fallback",
            "--no-remote-branches",
            "--check",
        ]
    )
    leak_out = capsys.readouterr().out
    assert rc_leak == 1
    assert "data-culprit" in leak_out
    assert "window.__MOLE" in leak_out


def test_local_game_rpc_registry_enforces_dev_seeds_and_post_done_reveal():
    class _StubGame:
        def __init__(self, seed):
            if seed in (800000, 900000):
                raise ValueError("benchmark seed refused")
            self.seed = seed

        def spec_json(self):
            return json.dumps({"seed": self.seed})

        def call_json(self, tool, args_json):
            return json.dumps({"tool": tool, "args": json.loads(args_json)})

        def reveal_json(self):
            return json.dumps({"error": "episode not done"})

        def actions_json(self):
            return "[]"

    class _StubMod:
        Game = _StubGame

    reg = audit._LocalGameRPCRegistry(_StubMod)
    bad_arena = reg.dispatch({"op": "arena_create", "tier": "hard", "seed": 900000})
    assert bad_arena["ok"] is False
    assert "DEV_SEEDS" in bad_arena["error"]

    ok_arena = reg.dispatch({"op": "arena_create", "tier": "hard", "seed": 6})
    assert ok_arena["ok"] is True
    sid = ok_arena["result"]["session_id"]
    pre_rev = reg.dispatch({"op": "arena_reveal", "session_id": sid})
    assert pre_rev["ok"] is True
    assert pre_rev["result"] == {"error": "episode not done"}


def test_live_chromium_playwright_e2e_audit(tmp_path, capsys):
    if not (audit.playwright_available() or audit.shared_playwright_python_available()):
        pytest.skip("Playwright/Chromium runtime is not installed in this CI environment")

    out_json = tmp_path / "live_chromium_report.json"
    scratch_dir = tmp_path / "pw_live_scratch"
    rc = audit.main(
        [
            "--root",
            str(ROOT),
            "--scratch-dir",
            str(scratch_dir),
            "--use-local-playwright",
            "--json-out",
            str(out_json),
            "--check",
        ]
    )
    capsys.readouterr()
    assert rc == 0
    assert not scratch_dir.exists()
    report = json.loads(out_json.read_text(encoding="utf-8"))
    assert report["passed"] is True
    assert report["browser_mode"] == "chromium_headless"
    assert report["live_api_calls"] == 0
    assert report["scratch_cleaned"] is True
    phases = {p["phase_id"]: p for p in report["phases"]}
    assert phases["P1"]["passed"] is True
    assert phases["P1"]["metrics"]["external_api_calls"] == 0
    assert phases["P2"]["passed"] is True
    assert all(p["refused"] for p in phases["P2"]["metrics"]["benchmark_seed_probes"])
    game_entries = [s for s in phases["P2"]["metrics"]["surfaces"] if s["kind"] == "ws6_game"]
    assert len(game_entries) == 1
    assert game_entries[0]["interactive_day5"]["day"] == 5
    assert game_entries[0]["interactive_day5"]["passed"] is True
    assert phases["P3"]["passed"] is True
    assert phases["P3"]["metrics"]["controls_caught"] == 5
    assert phases["P3"]["metrics"]["clean_control_exit_code"] == 0


def test_owned_files_hygiene_zero_comments_and_zero_unicode_dashes():
    this_file = Path(__file__).resolve()
    em_dash = chr(0x2014)
    en_dash = chr(0x2013)
    minus_sign = chr(0x2212)
    forbidden_coauthor = "-".join(("Co", "Authored", "By"))
    raw_gkey_prefix = "AI" + "za"
    raw_sk_prefix = "s" + "k-"

    for py_path in (SCRIPT_PATH, this_file):
        assert py_path.is_file(), py_path
        assert py_path.stat().st_size <= 130 * 1024, py_path
        txt = py_path.read_text(encoding="utf-8")
        assert em_dash not in txt, py_path
        assert en_dash not in txt, py_path
        assert minus_sign not in txt, py_path
        assert forbidden_coauthor.lower() not in txt.lower(), py_path
        assert raw_gkey_prefix not in txt, py_path
        assert raw_sk_prefix not in txt, py_path
        with open(py_path, "rb") as fh:
            comments = [tok for tok in tokenize.tokenize(fh.readline) if tok.type == tokenize.COMMENT]
        assert comments == [], (py_path, comments)
