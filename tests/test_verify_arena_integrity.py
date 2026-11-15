from __future__ import annotations

import importlib.util
import json
import sys
import tokenize
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts" / "verify_arena_integrity.py"
REPORT_MD_PATH = ROOT / "docs" / "reports" / "integrity_arena_pre_end_audit.md"


def _load_verifier():
    spec = importlib.util.spec_from_file_location("verify_arena_integrity", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


verifier = _load_verifier()


@pytest.fixture(scope="module")
def repo_audit_payload():
    return verifier.verify_arena_integrity(root=ROOT)


def test_verify_arena_real_repo_cli_check_and_json_out(tmp_path, capsys):
    out_json = tmp_path / "arena_audit.json"
    rc = verifier.main(["--root", str(ROOT), "--json-out", str(out_json), "--check"])
    stdout = capsys.readouterr().out
    assert rc == 0
    assert "PASS: 3/3 checks passed" in stdout
    assert out_json.is_file()
    payload = json.loads(out_json.read_text(encoding="utf-8"))
    assert payload["passed"] is True
    assert payload["status"] == "PASS"
    assert payload["live_api_calls"] == 0
    assert payload["elapsed_s"] < 5.0
    assert not verifier.DEFAULT_SCRATCH.exists()


def test_verify_arena_check_a1_firewall_and_planted_secret_violations(repo_audit_payload, tmp_path):
    by_id = {c["check_id"]: c for c in repo_audit_payload["checks"]}
    a1 = by_id["A1"]
    assert a1["passed"] is True
    m = a1["metrics"]
    assert m["game_files_scanned"] == 6
    assert m["site_built_files"] == 19
    assert m["site_python_files"] == 15
    assert m["manifest_checked"] is True
    assert m["forbidden_manifest_hits"] == 0
    assert m["api_key_hits"] == 0
    assert m["secret_literal_hits"] == 0
    assert m["benchmark_seed_bundle_hits"] == 0
    assert m["judge_seeds_rejected"] == "40/40"
    assert m["heldout_seeds_rejected"] == "30/30"
    assert m["extra_boundary_rejected"] == "11/11"

    key_dir = tmp_path / "key_leak"
    (key_dir / "docs" / "arena").mkdir(parents=True)
    fake_gkey = ("AI" + "za") + "SySyntheticArenaKey" + ("X" * 20)
    fake_sk = ("s" + "k-") + "proj-" + ("Y" * 24)
    (key_dir / "docs" / "arena" / "app.js").write_text(
        f'const k1 = "{fake_gkey}";\nconst k2 = "{fake_sk}";\n',
        encoding="utf-8",
    )
    res_keys = verifier.run_check_a1(key_dir, scratch_root=tmp_path, skip_site_build=True)
    assert res_keys.passed is False
    joined_keys = "\n".join(res_keys.violations)
    assert "google_api_key" in joined_keys
    assert "sk_api_key" in joined_keys
    assert fake_gkey not in joined_keys
    assert fake_sk not in joined_keys

    sec_dir = tmp_path / "secret_leak"
    (sec_dir / "docs" / "arena" / "py").mkdir(parents=True)
    (sec_dir / "docs" / "arena" / "config.json").write_text(
        json.dumps({"CANARY_WORLD_SECRET": "leaked_secret_token_1234", "CANARY_LEDGER_TOKEN": "tok_abcdef123456"}),
        encoding="utf-8",
    )
    (sec_dir / "docs" / "arena" / "SALT").write_text("0123456789abcdef", encoding="utf-8")
    (sec_dir / "docs" / "arena" / "py" / "manifest.json").write_text(
        json.dumps({"files": ["canary/env.py", "canary/redteam/hunter.py", "canary/mcp_server.py"]}),
        encoding="utf-8",
    )
    res_sec = verifier.run_check_a1(sec_dir, scratch_root=tmp_path, skip_site_build=True)
    assert res_sec.passed is False
    joined_sec = "\n".join(res_sec.violations)
    assert "SALT" in joined_sec
    assert "redteam" in joined_sec
    assert "mcp_server.py" in joined_sec

    held_dir = tmp_path / "heldout_bundle"
    (held_dir / "docs" / "demo").mkdir(parents=True)
    (held_dir / "docs" / "demo" / "replays.json").write_text(
        json.dumps({"episodes": [{"tier": "medium", "seed": 800000, "steps": []}]}),
        encoding="utf-8",
    )
    res_held = verifier.run_check_a1(held_dir, scratch_root=tmp_path, skip_site_build=True)
    assert res_held.passed is False
    assert any("HELDOUT_SEEDS" in v and "800000" in v for v in res_held.violations)


def test_verify_arena_check_a2_hard_seeds_6_and_26_and_game_init(repo_audit_payload):
    by_id = {c["check_id"]: c for c in repo_audit_payload["checks"]}
    a2 = by_id["A2"]
    assert a2["passed"] is True
    m = a2["metrics"]
    assert m["game_init_zero_history"] is True
    assert m["reveal_pre_end_guarded"] is True
    assert m["app_js_no_auto_status"] is True
    assert m["game_3000_day5_unsurfaced_ok"] is True
    assert m["ws6_self_env_in_python_scope"] is True

    s6 = m["hard_seed_6"]
    assert s6["seed"] == 6
    assert s6["true_mole"] == "e34"
    assert s6["decoy"] == "e20"
    assert s6["total_steps"] == 57
    assert s6["pre_terminal_steps"] == 56
    assert s6["unsurfaced_leak_steps"] == 40
    assert s6["unsurfaced_leak_days"] == [2, 3, 4, 5]
    assert s6["v_responses_verified"] == 7
    assert s6["correct"] is True
    assert s6["score"] == 0.73

    s26 = m["hard_seed_26"]
    assert s26["seed"] == 26
    assert s26["true_mole"] == "e08"
    assert s26["decoy"] == "e38"
    assert s26["total_steps"] == 91
    assert s26["pre_terminal_steps"] == 90
    assert s26["unsurfaced_leak_steps"] == 49
    assert s26["unsurfaced_leak_days"] == [3, 5, 6, 7, 9]
    assert s26["v_responses_verified"] == 10
    assert s26["correct"] is False
    assert s26["terminal_true_v"] == 0.67
    assert s26["score"] == -1.0


@pytest.mark.parametrize("control_name,expected_substr", verifier.PLANTED_CONTROLS)
def test_verify_arena_check_a3_six_planted_controls_exit_1(tmp_path, capsys, control_name, expected_substr):
    case_dir = tmp_path / control_name
    verifier._write_planted_control_bundle(case_dir, control_name)
    rc = verifier.main(["--root", str(case_dir), "--no-controls", "--check"])
    out = capsys.readouterr().out
    assert rc == 1
    assert "FAIL" in out
    assert expected_substr in out


def test_verify_arena_clean_and_leaky_arena_demo_bundles(tmp_path, capsys):
    clean_root = tmp_path / "merged_clean"
    arena = clean_root / "docs" / "arena"
    demo = clean_root / "docs" / "demo"
    arena.mkdir(parents=True)
    demo.mkdir(parents=True)

    (arena / "arena_integrity.py").write_text(
        "def check_seed(seed):\n"
        "    s = int(seed)\n"
        "    if not (0 <= s <= 9999):\n"
        "        raise ValueError('dev seeds only')\n"
        "    return s\n"
        "def make_session(seed):\n"
        "    check_seed(seed)\n"
        "    return {'call': lambda t, a: '{}'}\n",
        encoding="utf-8",
    )
    (arena / "index.html").write_text(
        '<!doctype html><script type="application/json">'
        '{"tier":"hard","seed":6,"mode":"investigator","steps":['
        '{"t":0,"day":1,"done":false,"tool":"list_documents","args":{"day_from":1,"day_to":1},'
        '"result":{"ok":true,"data":{"documents":[{"doc_id":"d1-1","title":"Doc","day":1,"recipients":["e00"],"is_canary":false}]},"error":null}},'
        '{"t":1,"day":1,"done":true,"tool":"accuse","args":{"employee":"e34"},'
        '"result":{"ok":true,"data":{"accused":"e34","episode_over":true},"error":null}}'
        '],"reveal":{"done":true,"mole":"e34"}}'
        "</script>\n",
        encoding="utf-8",
    )
    (demo / "fooled_bundle.js").write_text(
        'window.DEMO_REPLAY = {"tier":"hard","seed":26,"steps":['
        '{"t":0,"day":1,"done":false,"tool":"status","args":{},"result":{"ok":true,"data":{"day":1,"V":1.0},"error":null}}'
        '],"verdict":{"done":true,"true_mole":"e08"}};\n',
        encoding="utf-8",
    )
    (arena / "tiebreak_traces.js").write_text(
        'window.TIEBREAK_TRACES = {"episodes":[{"tier":"hard","seed":6,"steps":['
        '{"day":1,"call_idx":0,"tool":"status","args":{},"ok":true,"summary":"status","V":1.0},'
        '{"day":6,"call_idx":56,"tool":"accuse","args":{},"ok":true,"summary":"accuse sealed","V":0.73}'
        '],"final":{"accused":"e34","correct":true,"final_day":6,"tool_calls":57,"score":0.73}}]};\n',
        encoding="utf-8",
    )
    (arena / "data").mkdir(parents=True, exist_ok=True)
    (arena / "data" / "gemini_replays.json").write_text(
        json.dumps(
            {
                "episodes": [
                    {
                        "tier": "hard",
                        "seed": 6,
                        "steps": [
                            {
                                "t": 0,
                                "day": 1,
                                "done": False,
                                "tool": "status",
                                "args": {},
                                "result": {"ok": True, "data": {"day": 1, "V": 1.0}, "error": None},
                            }
                        ],
                        "sealed_reveal": {"commitment": "sha256:abcdef0123456789"},
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    rc_clean = verifier.main(["--root", str(clean_root), "--no-controls", "--check"])
    capsys.readouterr()
    assert rc_clean == 0
    rep_clean = verifier.verify_arena_integrity(clean_root, include_positive_controls=False, skip_site_build=True)
    by_id = {c["check_id"]: c for c in rep_clean["checks"]}
    assert by_id["A1"]["metrics"]["arena_guard_checked"] is True
    assert by_id["A2"]["metrics"]["arena_closure_guard_present"] is True

    leaky_root = tmp_path / "merged_leaky"
    (leaky_root / "docs" / "demo").mkdir(parents=True)
    (leaky_root / "docs" / "demo" / "leak.html").write_text(
        '<!doctype html><script>window.DEMO_STATE = '
        '{"tier":"hard","seed":26,"steps":[{"t":0,"day":3,"done":false,"decoy":"e38","true_v":0.95,"known_v":1.0}]};'
        "</script>\n",
        encoding="utf-8",
    )
    rc_leaky = verifier.main(["--root", str(leaky_root), "--no-controls", "--check"])
    out_leaky = capsys.readouterr().out
    assert rc_leaky == 1
    assert "decoy" in out_leaky
    assert "true_v" in out_leaky


def test_verify_arena_owned_files_hygiene_and_report_parity():
    assert SCRIPT_PATH.is_file()
    assert REPORT_MD_PATH.is_file()
    this_file = Path(__file__).resolve()

    em_dash = chr(0x2014)
    en_dash = chr(0x2013)
    minus_sign = chr(0x2212)
    forbidden_prereg_1 = "pre" + "-reg"
    forbidden_prereg_2 = "pre" + "reg"
    forbidden_coauthor = "-".join(("Co", "Authored", "By"))
    raw_gkey_prefix = "AI" + "za"
    raw_sk_prefix = "s" + "k-"

    for path in (SCRIPT_PATH, REPORT_MD_PATH, this_file):
        assert path.stat().st_size <= 130 * 1024, path
        txt = path.read_text(encoding="utf-8")
        assert em_dash not in txt, path
        assert en_dash not in txt, path
        assert minus_sign not in txt, path
        assert forbidden_coauthor.lower() not in txt.lower(), path
        assert raw_gkey_prefix not in txt, path
        assert raw_sk_prefix not in txt, path

    md_txt = REPORT_MD_PATH.read_text(encoding="utf-8")
    assert forbidden_prereg_1 not in md_txt.lower()
    assert forbidden_prereg_2 not in md_txt.lower()
    for token in (
        "e19e2bd2",
        "58716742",
        "post-hoc locked",
        "40/40",
        "30/30",
        "57",
        "40",
        "[2, 3, 4, 5]",
        "91",
        "49",
        "[3, 5, 6, 7, 9]",
        "6/6",
        "planted_step_mole_id",
        "planted_unsurfaced_true_v",
        "planted_unsealed_ai_accuse",
        "planted_pixel_sprite_leak",
        "planted_mole_mode_is_canary",
        "planted_judge_seed_bundle",
        "game/canary_game.py:39",
        "docs/arena/arena_integrity.py",
    ):
        assert token in md_txt, token

    for py_path in (SCRIPT_PATH, this_file):
        with open(py_path, "rb") as fh:
            comments = [tok for tok in tokenize.tokenize(fh.readline) if tok.type == tokenize.COMMENT]
        assert comments == [], (py_path, comments)
