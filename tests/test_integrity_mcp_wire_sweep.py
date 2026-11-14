from __future__ import annotations

import os
import stat
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from canary.mcp_server import BOOT_FD, PLAIN_SECRET_VARS, SECRET_FILE_VARS
import scripts.integrity_mcp_wire_sweep as sweep


def test_vector_catalog_complete_and_unique() -> None:
    ep_ids = [v[0] for v in sweep.EPISODE_VECTORS]
    proc_ids = [v[0] for v in sweep.PROCESS_VECTORS]
    all_ids = sorted(ep_ids + proc_ids)
    expected = [f"W{i:02d}" for i in range(1, 25)]
    assert len(ep_ids) == 19
    assert len(proc_ids) == 5
    assert all_ids == expected
    assert sweep.ALL_TIERS == ("easy", "medium", "hard", "hard_forge")
    assert sweep.ALL_SEEDS == tuple(range(900005, 900013))


def test_base_clean_env_and_write_0600(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    for var in (*SECRET_FILE_VARS, *PLAIN_SECRET_VARS, "CANARY_BOOTSTRAPPED", "CANARY_CONSUME_SECRET_FILES",
                "CANARY_ALLOW_DEV", "CANARY_LEDGER_LIVE"):
        monkeypatch.setenv(var, "must-be-stripped")
    cleaned = sweep.base_clean_env()
    for var in (*SECRET_FILE_VARS, *PLAIN_SECRET_VARS, "CANARY_BOOTSTRAPPED", "CANARY_CONSUME_SECRET_FILES",
                "CANARY_ALLOW_DEV", "CANARY_LEDGER_LIVE"):
        assert var not in cleaned

    secret_file = tmp_path / "tok"
    written = sweep.write_0600(secret_file, "secret-payload")
    assert written == str(secret_file)
    assert secret_file.read_text(encoding="utf-8") == "secret-payload"
    mode = stat.S_IMODE(os.stat(secret_file).st_mode)
    assert mode == 0o600


def test_wire_session_decode_rpc_json_and_sse() -> None:
    assert sweep.WireSession.decode_rpc(200, "   ", "application/json", 1) is None

    plain = sweep.WireSession.decode_rpc(
        200,
        '{"jsonrpc":"2.0","id":7,"result":{"ok":true}}',
        "application/json",
        7,
    )
    assert plain == {"jsonrpc": "2.0", "id": 7, "result": {"ok": True}}

    sse_payload = (
        "event: message\n"
        'data: {"jsonrpc":"2.0","method":"notifications/message","params":{}}\n\n'
        "event: message\n"
        'data: {"jsonrpc":"2.0","id":42,"result":{"tools":[]}}\n\n'
    )
    parsed = sweep.WireSession.decode_rpc(200, sse_payload, "text/event-stream; charset=utf-8", 42)
    assert parsed == {"jsonrpc": "2.0", "id": 42, "result": {"tools": []}}


def test_reconstruct_ledger_v_exact_and_tamper() -> None:
    p = sweep.tier_params("easy")
    v_after_canary = round(1.0 - p.canary_cost, 10)
    v_after_restrict_2d = round(v_after_canary - 2 * p.restrict_cost_per_day, 10)
    v_after_leak = round(v_after_restrict_2d - p.leak_damage, 10)
    valid_horizon = {
        "final_day": p.n_days,
        "end_reason": "horizon",
        "V": v_after_leak,
        "ledger": [
            {"day": 1, "event": "canary_planted", "detail": {"V": v_after_canary}},
            {"day": 1, "event": "restricted", "detail": {"employee": "e01"}},
            {"day": 3, "event": "unrestricted", "detail": {"employee": "e01"}},
            {"day": 4, "event": "leak", "detail": {"V": v_after_leak}},
        ],
    }
    exact, calc_v, rep_v = sweep.reconstruct_ledger_v("easy", valid_horizon)
    assert exact is True
    assert calc_v == pytest.approx(v_after_leak)
    assert rep_v == pytest.approx(v_after_leak)

    tampered = {
        "final_day": 3,
        "end_reason": "accused",
        "V": 0.999,
        "ledger": [
            {"day": 1, "event": "canary_planted", "detail": {"V": v_after_canary}},
        ],
    }
    exact_bad, _, _ = sweep.reconstruct_ledger_v("easy", tampered)
    assert exact_bad is False


def test_format_summary_table_renders_all_columns() -> None:
    sample = {
        "tiers": ["easy", "medium", "hard", "hard_forge"],
        "seeds": [900005, 900012],
        "total_vectors": 1,
        "vectors_held": 1,
        "total_runs": 4,
        "runs_held": 4,
        "elapsed_secs": 1.25,
        "vectors": [
            {
                "id": "W01",
                "name": "concurrent_plant_canary_race",
                "how": "test",
                "runs": 4,
                "held_runs": 4,
                "all_held": True,
                "by_tier": {"easy": "1/1", "medium": "1/1", "hard": "1/1", "hard_forge": "1/1"},
                "total_secs": 1.10,
                "sample_note": "ok=1|1 healthy=True",
            }
        ],
        "failures": [],
    }
    rendered = sweep.format_summary_table(sample)
    assert "| W01 | `concurrent_plant_canary_race` | 4/4 |" in rendered
    assert "ok=1/1 healthy=True" in rendered
    assert "Summary: 1/1 vectors held across 4/4 live subprocess runs" in rendered


def test_report_markdown_integrity() -> None:
    report_path = REPO / "docs" / "reports" / "integrity_mcp_wire_sweep.md"
    assert report_path.is_file()
    text = report_path.read_text(encoding="utf-8")
    assert "\u2014" not in text
    assert "628" in text
    for idx in range(1, 25):
        assert f"| W{idx:02d} |" in text


@pytest.fixture(scope="module")
def live_srv(tmp_path_factory: pytest.TempPathFactory):
    root = tmp_path_factory.mktemp("w2_mcp_live")
    srv = sweep.ManagedMCPServer("easy", 900005, tmp_root=root, marker_prefix="w2pytest")
    try:
        yield srv
    finally:
        srv.stop()


def test_live_proc_and_unlinked_secret_files_hygiene(live_srv: sweep.ManagedMCPServer) -> None:
    assert all(not p.exists() for p in live_srv.secret_paths.values())
    assert live_srv.proc is not None
    pid = live_srv.proc.pid
    proc_dir = Path(f"/proc/{pid}")
    if not proc_dir.is_dir():
        pytest.skip("/proc not mounted")

    assert not (proc_dir / "fd" / str(BOOT_FD)).exists()
    assert not (proc_dir / "fdinfo" / str(BOOT_FD)).exists()

    raw_env = (proc_dir / "environ").read_bytes().decode("utf-8", errors="replace")
    raw_cmd = (proc_dir / "cmdline").read_bytes().decode("utf-8", errors="replace")
    env_entries = [x for x in raw_env.split("\x00") if x]
    env_keys = {x.split("=", 1)[0] for x in env_entries if "=" in x}

    assert "CANARY_BOOTSTRAPPED=1" in env_entries
    assert not ((set(SECRET_FILE_VARS) | set(PLAIN_SECRET_VARS) | {"CANARY_CONSUME_SECRET_FILES"}) & env_keys)
    for secret in (
        "900005",
        live_srv.ledger_token,
        live_srv.admin_token or "",
        live_srv.ledger_key or "",
        live_srv.world_secret or "",
    ):
        assert secret and secret not in raw_env
        assert secret not in raw_cmd


@pytest.mark.parametrize(
    "vec_fn",
    [
        sweep.w01_concurrent_plant_canary_race,
        sweep.w02_concurrent_action_cap_race,
        sweep.w05_concurrent_delete_session_persistence,
        sweep.w06_json_unicode_escaped_keys,
        sweep.w07_duplicate_nested_keys_plant_canary,
        sweep.w08_ieee754_numbers_and_types,
        sweep.w10_plant_canary_schema_and_unicode_boundaries,
        sweep.w11_mcp_delete_transport_matrix,
        sweep.w12_mcp_get_sse_transport_matrix,
        sweep.w13_wrong_content_type_and_accept,
        sweep.w14_chunked_and_truncated_json,
        sweep.w15_http_methods_and_dns_rebinding,
        sweep.w16_jsonrpc_methods_versions_and_ids,
        sweep.w17_ledger_hpp_and_header_spoofing,
        sweep.w18_mid_episode_ledger_redaction_and_hmac,
        sweep.w20_cross_tier_reset_and_leak_audit,
    ],
)
def test_live_one_seed_wire_subset(live_srv: sweep.ManagedMCPServer, vec_fn) -> None:
    live_srv.reset("easy", 900005)
    held, note = vec_fn(live_srv)
    assert held, note
