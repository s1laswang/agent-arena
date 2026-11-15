from __future__ import annotations

import contextlib
import json
import os
import secrets
import shutil
import stat
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

WIRE_SUBSET_IDS = (
    "W01",
    "W05",
    "W06",
    "W07",
    "W12",
    "W18",
)


@pytest.fixture(scope="module")
def sweep_mod() -> Any:
    import scripts.integrity_mcp_wire_sweep as sweep

    return sweep


@pytest.fixture(scope="module")
def inproc_srv(sweep_mod: Any, tmp_path_factory: pytest.TempPathFactory) -> Any:
    root = tmp_path_factory.mktemp("w2_mcp_inproc")
    srv = sweep_mod.ManagedMCPServer("easy", 900005, tmp_root=root, marker_prefix="w2inproc", inproc=True)
    try:
        yield srv
    finally:
        srv.stop()


def test_vector_catalog_complete_and_unique(sweep_mod: Any) -> None:
    ep_ids = [v[0] for v in sweep_mod.EPISODE_VECTORS]
    proc_ids = [v[0] for v in sweep_mod.PROCESS_VECTORS]
    all_ids = sorted(ep_ids + proc_ids)
    expected = [f"W{i:02d}" for i in range(1, 25)]
    assert len(ep_ids) == 19
    assert len(proc_ids) == 5
    assert all_ids == expected
    assert sweep_mod.ALL_TIERS == ("easy", "medium", "hard", "hard_forge")
    assert sweep_mod.ALL_SEEDS == tuple(range(900005, 900013))


def test_base_clean_env_and_write_0600(
    sweep_mod: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from canary.mcp_server import PLAIN_SECRET_VARS, SECRET_FILE_VARS

    for var in (
        *SECRET_FILE_VARS,
        *PLAIN_SECRET_VARS,
        "CANARY_BOOTSTRAPPED",
        "CANARY_CONSUME_SECRET_FILES",
        "CANARY_ALLOW_DEV",
        "CANARY_LEDGER_LIVE",
    ):
        monkeypatch.setenv(var, "must-be-stripped")
    cleaned = sweep_mod.base_clean_env()
    for var in (
        *SECRET_FILE_VARS,
        *PLAIN_SECRET_VARS,
        "CANARY_BOOTSTRAPPED",
        "CANARY_CONSUME_SECRET_FILES",
        "CANARY_ALLOW_DEV",
        "CANARY_LEDGER_LIVE",
    ):
        assert var not in cleaned

    secret_file = tmp_path / "tok"
    written = sweep_mod.write_0600(secret_file, "secret-payload")
    assert written == str(secret_file)
    assert secret_file.read_text(encoding="utf-8") == "secret-payload"
    mode = stat.S_IMODE(os.stat(secret_file).st_mode)
    assert mode == 0o600


def test_wire_session_decode_rpc_json_and_sse(sweep_mod: Any) -> None:
    assert sweep_mod.WireSession.decode_rpc(200, "   ", "application/json", 1) is None

    plain = sweep_mod.WireSession.decode_rpc(
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
    parsed = sweep_mod.WireSession.decode_rpc(200, sse_payload, "text/event-stream; charset=utf-8", 42)
    assert parsed == {"jsonrpc": "2.0", "id": 42, "result": {"tools": []}}


def test_reconstruct_ledger_v_exact_and_tamper(sweep_mod: Any) -> None:
    p = sweep_mod.tier_params("easy")
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
    exact, calc_v, rep_v = sweep_mod.reconstruct_ledger_v("easy", valid_horizon)
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
    exact_bad, _, _ = sweep_mod.reconstruct_ledger_v("easy", tampered)
    assert exact_bad is False


def test_format_summary_table_renders_all_columns(sweep_mod: Any) -> None:
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
    rendered = sweep_mod.format_summary_table(sample)
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


def test_live_proc_and_unlinked_secret_files_hygiene(
    tmp_path: Path, sweep_mod: Any, inproc_srv: Any
) -> None:
    from canary.mcp_server import (
        BOOT_FD,
        PLAIN_SECRET_VARS,
        SECRET_FILE_VARS,
        _cfg_from_boot,
        _cfg_to_boot,
        consume_secret_files,
        load_config,
    )

    assert all(not p.exists() for p in inproc_srv.secret_paths.values())

    sdir = tmp_path / "sec_boot"
    sdir.mkdir(parents=True, exist_ok=True)
    os.chmod(sdir, 0o700)
    world_secret = f"w2pytest-ws-{secrets.token_hex(16)}"
    ledger_token = f"w2pytest-ltok-{secrets.token_hex(12)}"
    admin_token = f"w2pytest-atok-{secrets.token_hex(12)}"
    ledger_key = f"w2pytest-lkey-{secrets.token_hex(16)}"
    file_env = {
        "CANARY_EPISODE_FILE": sweep_mod.write_0600(sdir / "ep.json", json.dumps({"tier": "easy", "seed": 900005})),
        "CANARY_WORLD_SECRET_FILE": sweep_mod.write_0600(sdir / "ws", world_secret),
        "CANARY_LEDGER_TOKEN_FILE": sweep_mod.write_0600(sdir / "lt", ledger_token),
        "CANARY_ADMIN_TOKEN_FILE": sweep_mod.write_0600(sdir / "at", admin_token),
        "CANARY_LEDGER_KEY_FILE": sweep_mod.write_0600(sdir / "lk", ledger_key),
    }
    cfg = load_config(file_env)
    removed = consume_secret_files(file_env)
    assert set(removed) == set(SECRET_FILE_VARS)
    assert all(not Path(p).exists() for p in file_env.values())

    boot_bytes = _cfg_to_boot(cfg)
    roundtrip_cfg = _cfg_from_boot(boot_bytes)
    assert roundtrip_cfg["tier"] == "easy" and roundtrip_cfg["seed"] == 900005
    assert roundtrip_cfg["world_secret"] == world_secret.encode("utf-8")

    boot_env = sweep_mod.base_clean_env()
    boot_env["CANARY_BOOTSTRAPPED"] = "1"
    if hasattr(os, "memfd_create"):
        mfd = os.memfd_create("canary-cfg", 0)
        os.write(mfd, boot_bytes)
        os.lseek(mfd, 0, os.SEEK_SET)
    else:
        r_p, w_p = os.pipe()
        os.write(w_p, boot_bytes)
        os.close(w_p)
        mfd = r_p

    child_code = (
        f"import json, os, sys; "
        f"raw = os.read({BOOT_FD}, 65536); os.close({BOOT_FD}); "
        f"obj = json.loads(raw.decode('utf-8')); "
        f"sys.stdout.write(str(obj['seed']) + '\\n'); sys.stdout.flush(); "
        f"sys.stdin.readline()"
    )
    saved_73: int | None = None
    try:
        try:
            os.fstat(BOOT_FD)
            saved_73 = os.dup(BOOT_FD)
        except OSError:
            saved_73 = None
        if mfd != BOOT_FD:
            os.dup2(mfd, BOOT_FD)
            os.close(mfd)
        os.set_inheritable(BOOT_FD, True)
        proc = subprocess.Popen(
            [sys.executable, "-S", "-c", child_code],
            env=boot_env,
            cwd=str(REPO),
            pass_fds=(BOOT_FD,),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    finally:
        with contextlib.suppress(OSError):
            os.close(BOOT_FD)
        if saved_73 is not None:
            os.dup2(saved_73, BOOT_FD)
            os.close(saved_73)

    try:
        assert proc.stdout is not None
        ready_line = proc.stdout.readline().strip()
        assert ready_line == "900005"

        proc_dir = Path(f"/proc/{proc.pid}")
        if proc_dir.is_dir():
            assert not (proc_dir / "fd" / str(BOOT_FD)).exists()
            assert not (proc_dir / "fdinfo" / str(BOOT_FD)).exists()

            raw_env = (proc_dir / "environ").read_bytes().decode("utf-8", errors="replace")
            raw_cmd = (proc_dir / "cmdline").read_bytes().decode("utf-8", errors="replace")
            env_entries = [x for x in raw_env.split("\x00") if x]
            env_keys = {x.split("=", 1)[0] for x in env_entries if "=" in x}

            assert "CANARY_BOOTSTRAPPED=1" in env_entries
            assert not ((set(SECRET_FILE_VARS) | set(PLAIN_SECRET_VARS) | {"CANARY_CONSUME_SECRET_FILES"}) & env_keys)
            for secret in ("900005", ledger_token, admin_token, ledger_key, world_secret):
                assert secret and secret not in raw_env
                assert secret not in raw_cmd
    finally:
        if proc.stdin is not None:
            with contextlib.suppress(OSError):
                proc.stdin.write("\n")
                proc.stdin.flush()
        proc.kill()
        proc.wait(timeout=2)
        shutil.rmtree(sdir, ignore_errors=True)


@pytest.mark.parametrize("vec_id", WIRE_SUBSET_IDS)
def test_live_one_seed_wire_subset(sweep_mod: Any, inproc_srv: Any, vec_id: str) -> None:
    by_id = {v[0]: v[3] for v in sweep_mod.EPISODE_VECTORS}
    inproc_srv.reset("easy", 900005)
    held, note = by_id[vec_id](inproc_srv)
    assert held, note
