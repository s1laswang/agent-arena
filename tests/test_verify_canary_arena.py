from __future__ import annotations

import copy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tokenize
import types
from typing import Any
import urllib.parse
import urllib.request

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from canary import llm as canary_llm
from canary.arena.be_the_mole import BeTheMoleSession, check_arena_seed
from canary.arena.living_office import GATE_B_METRICS, LivingOfficeSession
from canary.env import Env
from scripts import verify_canary_arena as VCA

SCRIPT_PATH = ROOT / "scripts" / "verify_canary_arena.py"
TEST_PATH = Path(__file__).resolve()

HASH_CHAR = chr(35)
SLASH_CHAR = chr(47)
STAR_CHAR = chr(42)
EM_DASH = chr(0x2014)
EN_DASH = chr(0x2013)


def test_offline_arena_guard_clears_keys_sets_offline_and_restores_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GOOGLE_API_KEY", "restored_google_val")
    monkeypatch.setenv("GEMINI_API_KEY", "restored_gemini_val")
    monkeypatch.setenv("OPENAI_API_KEY", "restored_openai_val")
    monkeypatch.setenv("CANARY_OFFLINE", "0")
    monkeypatch.setenv("SLEEPER_OFFLINE", "0")

    with VCA.offline_arena_guard() as tel:
        assert os.environ.get("GOOGLE_API_KEY") == ""
        assert os.environ.get("GEMINI_API_KEY") == ""
        assert os.environ.get("OPENAI_API_KEY") == ""
        assert os.environ.get("CANARY_OFFLINE") == "1"
        assert os.environ.get("SLEEPER_OFFLINE") == "1"
        assert tel["live_api_calls"] == 0

    assert os.environ.get("GOOGLE_API_KEY") == "restored_google_val"
    assert os.environ.get("GEMINI_API_KEY") == "restored_gemini_val"
    assert os.environ.get("OPENAI_API_KEY") == "restored_openai_val"
    assert os.environ.get("CANARY_OFFLINE") == "0"
    assert os.environ.get("SLEEPER_OFFLINE") == "0"


def test_offline_arena_guard_allows_stub_and_blocks_real_llm_providers() -> None:
    with VCA.offline_arena_guard() as tel:
        c1 = canary_llm.get_client("stub")
        c2 = canary_llm.get_client("stub:")
        assert c1 is not None and c2 is not None
        assert tel["stub_llm_calls"] == 2

        for provider_spec in ("gemini", "gemini:gemini-4-carbon", "openai:gpt-5.5"):
            with pytest.raises(RuntimeError, match="offline_arena_guard"):
                canary_llm.get_client(provider_spec)

        assert tel["live_api_calls"] == 0
        assert tel["blocked_llm_calls"] == 3
        assert tel["blocked_calls"] == 3
        assert tel["blocked_api_attempts"] == 3


def test_offline_arena_guard_blocks_external_urllib_and_allows_loopback() -> None:
    class _PingHandler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:
            return

        def do_GET(self) -> None:
            body = b'{"ok":true}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _PingHandler)
    port = int(httpd.server_address[1])
    import threading

    th = threading.Thread(target=httpd.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True)
    th.start()
    try:
        with VCA.offline_arena_guard() as tel:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/ping", timeout=3) as resp:
                assert resp.status == 200
                assert json.loads(resp.read().decode("utf-8")) == {"ok": True}
            with urllib.request.urlopen(f"http://localhost:{port}/ping", timeout=3) as resp2:
                assert resp2.status == 200
            assert tel["loopback_requests"] == 2

            with pytest.raises(RuntimeError, match="non-loopback"):
                urllib.request.urlopen("https://example.com/v1/models", timeout=1)
            assert tel["blocked_network_calls"] == 1
            assert tel["live_api_calls"] == 0
    finally:
        httpd.shutdown()
        httpd.server_close()
        th.join(timeout=2)


def test_protected_paths_clean_and_synthetic_tamper_detected() -> None:
    clean_res = VCA.check_protected_paths(root=ROOT)
    assert clean_res.passed is True
    assert clean_res.status == "PASS"

    safe_override = VCA.check_protected_paths(
        root=ROOT,
        changed_files_override=["scripts/verify_canary_arena.py", "tests/test_verify_canary_arena.py"],
    )
    assert safe_override.passed is True

    for forbidden_path in (
        "canary/env.py",
        "canary/rules.py",
        "canary/solver/policy.py",
        "harbor/canary-task/instruction.md",
        "data/runs/committed/run.jsonl",
    ):
        bad_res = VCA.check_protected_paths(
            root=ROOT,
            changed_files_override=["scripts/verify_canary_arena.py", forbidden_path],
        )
        assert bad_res.passed is False
        assert bad_res.status == "FAIL"
        assert forbidden_path in bad_res.summary


def test_python_comment_scanner_ignores_hex_colors_and_catches_real_comments() -> None:
    clean_py = "\n".join(
        [
            "def render_styles(accent: str) -> str:",
            f'    bg = "{HASH_CHAR}0f172a"',
            f'    fg = "{HASH_CHAR}e2e8f0"',
            f'    css = f"body {{ background: {HASH_CHAR}0f172a; color: {{accent}}; border: 1px solid {HASH_CHAR}334155; }}"',
            f'    anchor = "{HASH_CHAR}arena-stage"',
            "    return bg + fg + css + anchor",
        ]
    )
    assert VCA.scan_python_comments(clean_py) == []

    commented_py = clean_py + f"\nx = 1  {HASH_CHAR} forbidden inline comment\n"
    hits = VCA.scan_python_comments(commented_py)
    assert len(hits) == 1
    assert hits[0]["kind"] == "python_comment"
    assert hits[0]["line"] == 7


def test_js_comment_scanner_ignores_urls_and_regex_and_catches_comments() -> None:
    line_comment = SLASH_CHAR * 2
    block_open = SLASH_CHAR + STAR_CHAR
    block_close = STAR_CHAR + SLASH_CHAR

    clean_js = "\n".join(
        [
            'const API_HTTP = "http://127.0.0.1:8000/api/health";',
            "const API_HTTPS = 'https://localhost:8443/api/catalog';",
            "const TPL = `http://127.0.0.1:${8000}/arena`;",
            r"const URL_RE = /^https?:\/\/[^/]+\//i;",
            "const ratio = 100 / 5;",
        ]
    )
    assert VCA.scan_js_comments(clean_js) == []

    bad_line_js = clean_js + f"\nconst y = 2; {line_comment} trailing comment\n"
    hits_line = VCA.scan_js_comments(bad_line_js)
    assert len(hits_line) == 1
    assert hits_line[0]["kind"] == "js_line_comment"

    bad_block_js = f"{block_open} block header {block_close}\n" + clean_js
    hits_block = VCA.scan_js_comments(bad_block_js)
    assert len(hits_block) == 1
    assert hits_block[0]["kind"] == "js_block_comment"

    bad_tpl_expr_js = f"const z = `http://localhost/${{1 + 2 {block_open} inner {block_close}}}`;\n"
    hits_tpl = VCA.scan_js_comments(bad_tpl_expr_js)
    assert len(hits_tpl) == 1
    assert hits_tpl[0]["kind"] == "js_block_comment"


def test_dash_scanner_catches_em_and_en_dashes() -> None:
    assert VCA.scan_dashes("clean ASCII hyphen - and range 3000..9999") == []

    em_hits = VCA.scan_dashes(f"line one\nbad {EM_DASH} dash")
    assert len(em_hits) == 1
    assert em_hits[0]["kind"] == "em_dash"
    assert em_hits[0]["line"] == 2

    en_hits = VCA.scan_dashes(f"seeds 3000{EN_DASH}9999")
    assert len(en_hits) == 1
    assert en_hits[0]["kind"] == "en_dash"
    assert en_hits[0]["line"] == 1


def test_secret_scanner_catches_google_and_sk_keys_and_redacts() -> None:
    benign = "const cls = 'desk-panel-layout-wrapper'; const slug = 'task-identifier-1234567890123456';"
    assert VCA.scan_secrets(benign) == []

    fake_google = "AI" + "zaSySyntheticUnitTestToken0123456789"
    fake_sk = "sk" + "-proj-SyntheticOpenAIToken0123456789abcdef"
    leaked_src = f'KEY_A = "{fake_google}"\nKEY_B = "{fake_sk}"\n'
    hits = VCA.scan_secrets(leaked_src)
    assert len(hits) == 2
    kinds = {h["kind"] for h in hits}
    assert kinds == {"google_api_key", "sk_api_key"}
    for h in hits:
        assert fake_google not in h["redacted"]
        assert fake_sk not in h["redacted"]


def test_code_hygiene_synthetic_workspace_with_docs_arena_and_assets_md(tmp_path: Path) -> None:
    (tmp_path / "canary" / "arena").mkdir(parents=True)
    (tmp_path / "scripts").mkdir(parents=True)
    (tmp_path / "tests").mkdir(parents=True)
    (tmp_path / "docs" / "arena").mkdir(parents=True)
    (tmp_path / "docs" / "demo").mkdir(parents=True)

    (tmp_path / "canary" / "arena" / "theme.py").write_text(
        f'THEME_BG = "{HASH_CHAR}0f172a"\nTHEME_ACCENT = "{HASH_CHAR}38bdf8"\n',
        encoding="utf-8",
    )
    (tmp_path / "scripts" / "run_arena_tool.py").write_text("VALUE = 42\n", encoding="utf-8")
    (tmp_path / "tests" / "test_sample_arena.py").write_text("def test_ok():\n    assert 1 == 1\n", encoding="utf-8")
    (tmp_path / "docs" / "arena" / "client.js").write_text(
        'export const DEFAULT_ORIGIN = "http://127.0.0.1:8000";\n',
        encoding="utf-8",
    )
    (tmp_path / "docs" / "arena" / "sprite.png").write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR")
    (tmp_path / "docs" / "demo" / "ASSETS.md").write_text(
        "CC0 16x16 office tileset manifest - public domain.\n",
        encoding="utf-8",
    )

    clean_res = VCA.check_code_hygiene(root=tmp_path)
    assert clean_res.passed is True
    assert clean_res.metrics["n_files_scanned"] == 5

    (tmp_path / "docs" / "demo" / "ASSETS.md").write_text(
        f"Bad dash {EM_DASH} in assets doc.\n",
        encoding="utf-8",
    )
    bad_res = VCA.check_code_hygiene(root=tmp_path)
    assert bad_res.passed is False
    assert any("em_dash" in d for d in bad_res.details)


def test_be_the_mole_engine_check_passes_live() -> None:
    with VCA.offline_arena_guard() as tel:
        res = VCA.check_be_the_mole_engine()
        assert res.passed is True
        assert res.status == "PASS"
        assert tel["live_api_calls"] == 0


def test_be_the_mole_pre_end_leak_catcher_detects_tampering() -> None:
    sess = BeTheMoleSession("medium", 3000)
    clean_state = sess.state_dict()
    if not clean_state["mole_view"]["docs"]:
        clean_state = sess.step_turn(None, None)
    assert len(clean_state["mole_view"]["docs"]) >= 1
    assert VCA.inspect_be_the_mole_pre_end_state(clean_state) == []

    tampered_reveal = copy.deepcopy(clean_state)
    tampered_reveal["reveal"] = {"true_mole_id": "e01"}
    issues_rev = VCA.inspect_be_the_mole_pre_end_state(tampered_reveal)
    assert any("reveal" in msg for msg in issues_rev)

    tampered_canary = copy.deepcopy(clean_state)
    tampered_canary["mole_view"]["docs"][0]["is_canary"] = True
    issues_can = VCA.inspect_be_the_mole_pre_end_state(tampered_canary)
    assert any("is_canary" in msg for msg in issues_can)

    tampered_variants = copy.deepcopy(clean_state)
    tampered_variants["mole_view"]["docs"][0]["variants"] = {"A": ["e00"], "B": ["e01"]}
    issues_var = VCA.inspect_be_the_mole_pre_end_state(tampered_variants)
    assert any("variants" in msg for msg in issues_var)


def test_living_office_engine_check_passes_live() -> None:
    with VCA.offline_arena_guard() as tel:
        res = VCA.check_living_office_engine()
        assert res.passed is True
        assert res.status == "PASS"
        assert tel["live_api_calls"] == 0


def test_living_office_pre_end_leak_catcher_detects_tampering() -> None:
    sess = LivingOfficeSession("medium", 3001, "v5_full9_cocktail", "frontier_synthesis_v14")
    true_mole = str(sess.env._world.mole)
    decoy_id = sess.env._world.decoy
    clean_state = sess.state_dict()
    assert VCA.inspect_living_office_pre_end_state(clean_state, true_mole=true_mole, decoy=decoy_id) == []

    t_verdict = copy.deepcopy(clean_state)
    t_verdict["verdict"] = {"score": 0.8}
    assert VCA.inspect_living_office_pre_end_state(t_verdict, true_mole=true_mole)

    t_xray = copy.deepcopy(clean_state)
    t_xray["xray"] = {"biases": {}}
    assert VCA.inspect_living_office_pre_end_state(t_xray, true_mole=true_mole)

    t_desk_mole = copy.deepcopy(clean_state)
    t_desk_mole["floorplan"]["desks"][0]["is_mole"] = False
    assert any("is_mole" in m for m in VCA.inspect_living_office_pre_end_state(t_desk_mole, true_mole=true_mole))

    t_desk_decoy = copy.deepcopy(clean_state)
    t_desk_decoy["floorplan"]["desks"][0]["is_decoy"] = True
    assert any("is_decoy" in m for m in VCA.inspect_living_office_pre_end_state(t_desk_decoy, true_mole=true_mole))

    t_status = copy.deepcopy(clean_state)
    t_status["floorplan"]["desks"][0]["status"] = "true_mole"
    assert any("status" in m for m in VCA.inspect_living_office_pre_end_state(t_status, true_mole=true_mole))

    t_hidden = copy.deepcopy(clean_state)
    t_hidden["debug_mole_hint"] = true_mole
    assert any(true_mole in m for m in VCA.inspect_living_office_pre_end_state(t_hidden, true_mole=true_mole))


def test_living_office_gate_b_tamper_detected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(GATE_B_METRICS, "gate_met", True)
    res = VCA.check_living_office_engine()
    assert res.passed is False
    assert any("gate_met" in d for d in res.details)


def test_optional_modules_skip_when_absent_and_fail_under_require_all(tmp_path: Path) -> None:
    skip_h2h = VCA.check_head_to_head(root=tmp_path, require_present=False)
    skip_srv = VCA.check_arena_server(root=tmp_path, require_present=False)
    skip_riv = VCA.check_mole_rivals(root=tmp_path, require_present=False)
    assert skip_h2h.status == "SKIP" and skip_h2h.passed is True
    assert skip_srv.status == "SKIP" and skip_srv.passed is True
    assert skip_riv.status == "SKIP" and skip_riv.passed is True

    fail_h2h = VCA.check_head_to_head(root=tmp_path, require_present=True)
    fail_srv = VCA.check_arena_server(root=tmp_path, require_present=True)
    fail_riv = VCA.check_mole_rivals(root=tmp_path, require_present=True)
    assert fail_h2h.status == "FAIL" and fail_h2h.passed is False
    assert fail_srv.status == "FAIL" and fail_srv.passed is False
    assert fail_riv.status == "FAIL" and fail_riv.passed is False


def test_head_to_head_engine_check_passes_live() -> None:
    with VCA.offline_arena_guard() as tel:
        res = VCA.check_head_to_head(root=ROOT, require_present=True)
        assert res.passed is True, res.details
        assert res.status == "PASS"
        assert res.metrics.get("ghost_replays", 0) >= 5
        assert tel["live_api_calls"] == 0


def test_head_to_head_synthetic_clean_and_tampered_module() -> None:
    clean_mod = types.ModuleType("synthetic_head_to_head_clean")

    class CleanHeadToHeadSession:
        def __init__(self, tier: str = "medium", seed: int = 3000) -> None:
            if tier not in ("medium", "hard"):
                raise ValueError("invalid tier")
            self.seed = check_arena_seed(seed)
            self.tier = tier
            self.env = Env(tier, self.seed)
            self.done = False

        def state_dict(self) -> dict[str, Any]:
            return {
                "mode": "head_to_head",
                "tier": self.tier,
                "seed": self.seed,
                "day": self.env.day,
                "done": self.done,
                "employees": [{"id": e.id, "name": e.name} for e in self.env._world.employees],
                "verdict": None,
                "reveal": None,
            }

    clean_mod.HeadToHeadSession = CleanHeadToHeadSession
    clean_mod.check_arena_seed = check_arena_seed
    clean_mod.list_ghost_replays = lambda: [{"id": "gemini:hard:0", "tier": "hard", "seed": 0}]
    clean_mod.load_ghost_replay = lambda replay_id: {"id": replay_id, "steps": [], "done": True}

    res_ok = VCA.check_head_to_head(module_override=clean_mod, require_present=True)
    assert res_ok.passed is True
    assert res_ok.status == "PASS"

    leaky_mod = types.ModuleType("synthetic_head_to_head_leaky")

    class LeakyHeadToHeadSession(CleanHeadToHeadSession):
        def state_dict(self) -> dict[str, Any]:
            base = super().state_dict()
            base["true_mole"] = str(self.env._world.mole)
            return base

    leaky_mod.HeadToHeadSession = LeakyHeadToHeadSession
    leaky_mod.list_ghost_replays = clean_mod.list_ghost_replays
    leaky_mod.load_ghost_replay = clean_mod.load_ghost_replay

    res_leak = VCA.check_head_to_head(module_override=leaky_mod, require_present=True)
    assert res_leak.passed is False
    assert any("true_mole" in d for d in res_leak.details)


def _build_synthetic_server_module(
    *,
    reject_bad_seeds: bool = True,
    leak_true_mole: bool = False,
) -> Any:
    srv_mod = types.ModuleType("synthetic_arena_server")
    btm_sessions: dict[str, BeTheMoleSession] = {}
    lo_sessions: dict[str, LivingOfficeSession] = {}

    class _Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:
            return

        def _send(self, status: int, body: Any, ctype: str = "application/json") -> None:
            raw = body.encode("utf-8") if isinstance(body, str) else json.dumps(body).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def do_GET(self) -> None:
            parsed = urllib.parse.urlsplit(self.path)
            qs = dict(urllib.parse.parse_qsl(parsed.query))
            if parsed.path == "/":
                self._send(200, "<!doctype html><html><body>Canary Arena</body></html>", "text/html")
            elif parsed.path == "/api/health":
                self._send(200, {"ok": True, "offline": True})
            elif parsed.path == "/api/catalog":
                self._send(200, {"modes": ["be_the_mole", "living_office", "head_to_head"]})
            elif parsed.path == "/api/living_office/replay":
                variant = qs.get("variant", "v5_full9_cocktail")
                seed = int(qs.get("seed", "30"))
                self._send(
                    200,
                    {
                        "variant": variant,
                        "seed": seed,
                        "provenance_badge": "v16-real-gemini-replay",
                        "done": True,
                    },
                )
            else:
                self._send(404, {"error": "not_found"})

        def do_POST(self) -> None:
            length = int(self.headers.get("Content-Length") or 0)
            payload = json.loads(self.rfile.read(length).decode("utf-8")) if length else {}
            if self.path == "/api/be_the_mole/start":
                raw_seed = payload.get("seed", 3000)
                if reject_bad_seeds:
                    try:
                        seed = check_arena_seed(raw_seed)
                    except ValueError as exc:
                        self._send(400, {"error": "SeedHygieneError", "detail": str(exc)})
                        return
                else:
                    seed = 3000
                sess = BeTheMoleSession(payload.get("tier", "medium"), seed)
                btm_sessions["btm1"] = sess
                self._send(200, {"session_id": "btm1", "state": sess.state_dict()})
            elif self.path == "/api/be_the_mole/autoplay":
                sid = payload.get("session_id", "btm1")
                sess = btm_sessions[sid]
                st = sess.auto_play(payload.get("strategy_name") or payload.get("strategy") or "frontier_synthesis_v14")
                self._send(200, {"session_id": sid, "done": st["done"], "state": st})
            elif self.path == "/api/living_office/start":
                raw_seed = payload.get("seed", 3001)
                if reject_bad_seeds:
                    try:
                        seed = check_arena_seed(raw_seed)
                    except ValueError as exc:
                        self._send(400, {"error": "SeedHygieneError", "detail": str(exc)})
                        return
                else:
                    seed = 3001
                lo = LivingOfficeSession(
                    payload.get("tier", "medium"),
                    seed,
                    payload.get("variant", "v5_full9_cocktail"),
                    payload.get("mole_opponent", "frontier_synthesis_v14"),
                )
                lo_sessions["lo1"] = lo
                out: dict[str, Any] = {"session_id": "lo1", "state": lo.state_dict()}
                if leak_true_mole:
                    out["true_mole"] = str(lo.env._world.mole)
                self._send(200, out)
            elif self.path == "/api/living_office/step":
                sid = payload.get("session_id", "lo1")
                lo = lo_sessions[sid]
                stepped = lo.step_auto_investigator(payload.get("policy") or "solver")
                self._send(200, {"session_id": sid, **stepped})
            elif self.path == "/api/head_to_head/start":
                raw_seed = payload.get("seed", 3002)
                if reject_bad_seeds:
                    try:
                        seed = check_arena_seed(raw_seed)
                    except ValueError as exc:
                        self._send(400, {"error": "SeedHygieneError", "detail": str(exc)})
                        return
                else:
                    seed = 3002
                env = Env("medium", seed)
                resp: dict[str, Any] = {
                    "session_id": "h2h1",
                    "done": False,
                    "day": 1,
                    "verdict": None,
                }
                if leak_true_mole:
                    resp["secret_mole"] = str(env._world.mole)
                self._send(200, resp)
            else:
                self._send(404, {"error": "not_found"})

    def create_server(host: str = "127.0.0.1", port: int = 0) -> ThreadingHTTPServer:
        return ThreadingHTTPServer((host, port), _Handler)

    srv_mod.create_server = create_server
    return srv_mod


def test_arena_server_ephemeral_loopback_clean_passes_under_offline_guard() -> None:
    srv_mod = _build_synthetic_server_module(reject_bad_seeds=True, leak_true_mole=False)
    with VCA.offline_arena_guard() as tel:
        res = VCA.check_arena_server(module_override=srv_mod, require_present=True)
        assert res.passed is True, res.details
        assert res.status == "PASS"
        assert tel["loopback_requests"] >= 10
        assert tel["live_api_calls"] == 0
        assert tel["blocked_network_calls"] == 0


def test_arena_server_catches_missing_http_400_seed_guard_and_pre_end_leak() -> None:
    no_guard_srv = _build_synthetic_server_module(reject_bad_seeds=False, leak_true_mole=False)
    res_seed = VCA.check_arena_server(module_override=no_guard_srv, require_present=True)
    assert res_seed.passed is False
    assert any("HTTP 400" in d for d in res_seed.details)

    leaky_srv = _build_synthetic_server_module(reject_bad_seeds=True, leak_true_mole=True)
    res_leak = VCA.check_arena_server(module_override=leaky_srv, require_present=True)
    assert res_leak.passed is False
    assert any("true_mole" in d or "secret_mole" in d for d in res_leak.details)


def test_mole_rivals_synthetic_clean_and_warm_budget_check(tmp_path: Path) -> None:
    rivals_dir = tmp_path / "docs" / "arena"
    rivals_dir.mkdir(parents=True)
    rivals_file = rivals_dir / "mole_rivals.py"
    rivals_file.write_text(
        "\n".join(
            [
                "from typing import Any",
                "",
                "def get_mole_briefing(tier: str = 'hard') -> dict[str, Any]:",
                "    return {'tier': tier, 'rivals': ['default_v0', 'frontier_synthesis_v14']}",
                "",
                "def compare_human_mole(human_summary: dict[str, Any], tier: str = 'hard') -> dict[str, Any]:",
                "    return {'tier': tier, 'beat_default': True, 'human_score': human_summary.get('score', 0.0)}",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    res_ok = VCA.check_mole_rivals(root=tmp_path, require_present=True, max_warm_ms=80.0)
    assert res_ok.passed is True
    assert res_ok.metrics["warm_ms"] < 80.0

    slow_mod = types.ModuleType("slow_mole_rivals")
    slow_mod.get_mole_briefing = lambda tier="hard": {"tier": tier}

    def _slow_compare(human_summary: dict[str, Any]) -> dict[str, Any]:
        import time as _t

        _t.sleep(0.02)
        return {"ok": True}

    slow_mod.compare_human_mole = _slow_compare
    res_slow = VCA.check_mole_rivals(module_override=slow_mod, require_present=True, max_warm_ms=5.0)
    assert res_slow.passed is False
    assert any("warm execution took" in d for d in res_slow.details)


def test_cli_check_and_json_out_smoke(tmp_path: Path) -> None:
    json_out = tmp_path / "arena_verify_report.json"
    rc = VCA.main(["--check", "--json-out", str(json_out)])
    assert rc == 0
    assert json_out.is_file()
    payload = json.loads(json_out.read_text(encoding="utf-8"))
    assert payload["passed"] is True
    assert payload["total_duration_ms"] < 60_000.0
    assert payload["telemetry"]["live_api_calls"] == 0

    fake_root = tmp_path / "empty_ws"
    (fake_root / "canary" / "arena").mkdir(parents=True)
    (fake_root / "canary" / "arena" / "stub.py").write_text("X = 1\n", encoding="utf-8")
    rc_req = VCA.main(["--check", "--require-all", "--root", str(fake_root)])
    assert rc_req == 1

    proc = subprocess.run(
        [sys.executable, str(SCRIPT_PATH), "--check"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 0, proc.stdout + "\n" + proc.stderr
    assert "OVERALL: PASS" in proc.stdout


def test_verifier_and_test_files_have_zero_comments_dashes_or_secrets() -> None:
    for path in (SCRIPT_PATH, TEST_PATH):
        text = path.read_text(encoding="utf-8")
        assert text.isascii() is True, f"non-ASCII character found in {path}"
        assert EM_DASH not in text, f"em dash found in {path}"
        assert EN_DASH not in text, f"en dash found in {path}"
        assert HASH_CHAR not in text, f"hash char found in {path}"
        assert VCA.scan_dashes(text) == []
        assert VCA.scan_secrets(text) == []
        assert VCA.scan_python_comments(text) == []
        tokens = list(tokenize.generate_tokens(io.StringIO(text).readline))
        assert [t for t in tokens if t.type == tokenize.COMMENT] == []
