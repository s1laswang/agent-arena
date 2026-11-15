from __future__ import annotations

import base64
import io
import json
import math
import shutil
import subprocess
import sys
import textwrap
import tokenize
from functools import lru_cache
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import scripts.verify_arena_duel_parity as vdp
from canary.env import Env

HASH_CHAR = chr(35)
EM_DASH = chr(0x2014)
EN_DASH = chr(0x2013)
UNICODE_MINUS = chr(0x2212)

OWNED_FILES = (
    "scripts/verify_arena_duel_parity.py",
    "docs/arena/arena_duel_parity_v14.json",
    "tests/test_verify_arena_duel_parity.py",
)

DISJOINT_PEER_FILES = (
    "docs/arena/scoring_parity.py",
    "scripts/verify_arena_modes_parity.py",
    "scripts/verify_arena_bundle_parity.py",
)


@lru_cache(maxsize=1)
def _cached_live_report() -> dict[str, Any]:
    return vdp.build_parity_report(root=ROOT)


@lru_cache(maxsize=4)
def _load_committed_gemini_row(tier: str, seed: int) -> dict[str, Any]:
    ep_file = (
        ROOT
        / "data"
        / "runs"
        / "committed"
        / "v1.4"
        / "opencode-gemini-4-carbon"
        / tier
        / "episodes.jsonl"
    )
    by_seed = vdp.load_jsonl_episodes_by_seed([ep_file], seeds=(seed,))
    return by_seed[seed]


def _make_sim_root(tmp_path: Path, name: str) -> Path:
    sim = tmp_path / name
    (sim / "docs" / "arena").mkdir(parents=True, exist_ok=True)
    (sim / "docs" / "demo").mkdir(parents=True, exist_ok=True)
    for rel_dir in ("data", "canary", "game"):
        src = ROOT / rel_dir
        if src.exists():
            (sim / rel_dir).symlink_to(src)
    shutil.copy2(
        ROOT / vdp.DEFAULT_OUT_REL,
        sim / vdp.DEFAULT_OUT_REL,
    )
    return sim


def test_owned_files_hygiene_disjointness_and_protected_paths() -> None:
    assert set(OWNED_FILES).isdisjoint(set(DISJOINT_PEER_FILES))

    protected_file = ROOT / ".github" / "protected-paths.txt"
    protected_prefixes: list[str] = []
    for raw in protected_file.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith(HASH_CHAR):
            continue
        protected_prefixes.append(line)

    for rel in OWNED_FILES:
        fp = ROOT / rel
        assert fp.is_file(), f"missing owned file {rel}"
        src = fp.read_text(encoding="utf-8")
        assert src.isascii(), f"non-ASCII char in {rel}"
        assert HASH_CHAR not in src, f"comment char in {rel}"
        assert EM_DASH not in src, f"em dash in {rel}"
        assert EN_DASH not in src, f"en dash in {rel}"
        assert UNICODE_MINUS not in src, f"unicode minus in {rel}"
        co_authored_tok = "Co-Authored" + "-By"
        assert co_authored_tok not in src, f"{co_authored_tok} in {rel}"
        for prefix in protected_prefixes:
            if prefix.endswith("/"):
                assert not rel.startswith(prefix), f"{rel} touches protected dir {prefix}"
            else:
                assert rel != prefix, f"{rel} touches protected file {prefix}"
        if fp.suffix == ".py":
            toks = list(tokenize.generate_tokens(io.StringIO(src).readline))
            assert [t for t in toks if t.type == tokenize.COMMENT] == []

    artifact_bytes = (ROOT / vdp.DEFAULT_OUT_REL).read_bytes()
    assert len(artifact_bytes) <= vdp.MAX_ARTIFACT_BYTES

    probe = textwrap.dedent(
        """
        import json, sys
        sys.path.insert(0, sys.argv[1])
        import scripts.verify_arena_duel_parity as m
        stdlib = set(sys.stdlib_module_names) | {"builtins", "__main__", "_frozen_importlib", "_frozen_importlib_external"}
        non_stdlib = sorted(
            name for name in sys.modules
            if name.split(".")[0] not in stdlib
            and name.split(".")[0] not in {"canary", "scripts"}
        )
        print(json.dumps({"non_stdlib": non_stdlib, "schema": "arena_duel_parity_v14.v1"}))
        """
    )
    proc = subprocess.run(
        [sys.executable, "-c", probe, str(ROOT)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    payload = json.loads(proc.stdout.strip().splitlines()[-1])
    assert payload["non_stdlib"] == []


def test_committed_artifact_and_live_60_gemini_plus_60_solver_parity() -> None:
    report = _cached_live_report()
    assert report["schema_version"] == "arena_duel_parity_v14.v1"
    assert report["tiers_version"] == "v1.4"
    assert report["agent"] == "opencode:google/gemini-4-carbon"
    assert report["all_gates_passed"] is True

    summary = report["summary"]
    assert summary["gemini_carbon_episodes_verified"] == 60
    assert summary["paired_solver_episodes_verified"] == 60
    assert summary["mismatch_count"] == 0
    assert summary["max_abs_score_diff"] < vdp.PARITY_TOL
    assert summary["pre_end_day_views_verified"] == 1050
    assert summary["unsurfaced_leak_gap_steps_verified"] > 200
    assert summary["pre_end_hidden_truth_leaks"] == 0
    assert summary["featured_seeds_verified"] is True
    assert summary["external_bundles_ok"] is True

    hard_tier = report["tiers"]["hard"]
    med_tier = report["tiers"]["medium"]
    assert hard_tier["n_episodes"] == 30
    assert hard_tier["mismatch_count"] == 0
    assert hard_tier["pre_end_day_views_verified"] == 630
    assert hard_tier["live_solver_verified_count"] >= 3
    assert med_tier["n_episodes"] == 30
    assert med_tier["mismatch_count"] == 0
    assert med_tier["pre_end_day_views_verified"] == 420
    assert med_tier["live_solver_verified_count"] >= 3

    committed = json.loads((ROOT / vdp.DEFAULT_OUT_REL).read_text(encoding="utf-8"))
    assert vdp.canonical_artifact_projection(committed) == vdp.canonical_artifact_projection(report)

    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "verify_arena_duel_parity.py"), "--check", "--json"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    cli_json = json.loads(proc.stdout)
    assert cli_json["all_gates_passed"] is True
    assert cli_json["summary"]["mismatch_count"] == 0


def test_featured_hard_seeds_6_and_26_contracts_and_day_sync_projection() -> None:
    report = _cached_live_report()
    highlights = report["featured_duel_seeds"]
    contracts = report["featured_ai_duel_contracts"]

    s6_post = highlights["hard_seed_6"]["post_end"]
    assert s6_post["true_mole"] == "e34"
    assert s6_post["true_decoy"] == "e20"
    assert s6_post["gemini_final"] == {
        "accused": "e34",
        "correct": True,
        "final_day": 6,
        "tool_calls": 57,
        "score": 0.73,
    }
    assert s6_post["solver_final"] == {
        "accused": "e34",
        "correct": True,
        "final_day": 6,
        "tool_calls": 52,
        "score": 0.71,
    }

    s26_post = highlights["hard_seed_26"]["post_end"]
    assert s26_post["true_mole"] == "e08"
    assert s26_post["gemini_final"] == {
        "accused": "e04",
        "correct": False,
        "final_day": 10,
        "tool_calls": 91,
        "score": -1.0,
    }
    assert s26_post["solver_final"] == {
        "accused": "e08",
        "correct": True,
        "final_day": 7,
        "tool_calls": 60,
        "score": 0.69,
    }

    c6 = contracts["hard_seed_6"]
    c26 = contracts["hard_seed_26"]
    for c in (c6, c26):
        assert set(c.keys()) == set(vdp.CONTRACT_TOP_KEYS)
        assert set(c["final"].keys()) == set(vdp.CONTRACT_FINAL_KEYS)
        for st in c["steps"]:
            assert set(st.keys()) == set(vdp.CONTRACT_STEP_KEYS)

    env6 = Env("hard", 6)
    day2_known_v = None
    day2_true_v = None
    for st in c6["steps"]:
        env6.call(st["tool"], st["args"])
        if st["day"] == 2 and day2_known_v is None:
            day2_known_v = env6.visible_V()
            day2_true_v = round(env6.V, 10)
            assert math.isclose(st["V"], 0.98, abs_tol=1e-9)
            assert math.isclose(day2_known_v, 0.98, abs_tol=1e-9)
            assert math.isclose(day2_true_v, 0.93, abs_tol=1e-9)

    v6_day5 = vdp.project_ai_duel_view(c6, human_day=5, human_done=False)
    assert v6_day5["status"] == "hunting"
    assert v6_day5["accused"] is None
    assert v6_day5["final"] is None
    assert vdp.find_forbidden_pre_end_keys(v6_day5) == []

    v6_day6_pre = vdp.project_ai_duel_view(c6, human_day=6, human_done=False)
    assert v6_day6_pre["status"] == "sealed_accusation"
    assert v6_day6_pre["sealed_day"] == 6
    assert v6_day6_pre["accused"] == "[SEALED]"
    assert v6_day6_pre["final"] is None
    assert v6_day6_pre["steps"][-1]["tool"] == "accuse"
    assert v6_day6_pre["steps"][-1]["args"] == {"employee": "[SEALED]"}
    assert v6_day6_pre["steps"][-1]["summary"] == "[SEALED]"
    assert v6_day6_pre["steps"][-1]["sealed"] is True
    assert "e34" not in json.dumps(v6_day6_pre["steps"][-1])

    v6_done = vdp.project_ai_duel_view(c6, human_day=6, human_done=True)
    assert v6_done["status"] == "unlocked"
    assert v6_done["final"] == s6_post["gemini_final"]

    v26_day10_pre = vdp.project_ai_duel_view(c26, human_day=10, human_done=False)
    assert v26_day10_pre["status"] == "sealed_accusation"
    assert v26_day10_pre["accused"] == "[SEALED]"
    assert v26_day10_pre["steps"][-1]["args"] == {"employee": "[SEALED]"}
    assert "e04" not in json.dumps(v26_day10_pre["steps"][-1])

    sp_path = ROOT / "docs" / "arena" / "scoring_parity.py"
    if sp_path.is_file():
        arena_dir_str = str(ROOT / "docs" / "arena")
        if arena_dir_str not in sys.path:
            sys.path.insert(0, arena_dir_str)
        import scoring_parity as sp

        assert sp.validate_craft_final_verdict(c6["final"], tool_calls=57) == c6["final"]
        assert sp.validate_craft_final_verdict(c26["final"], tool_calls=91) == c26["final"]
        duel_s26 = sp.duel_end_screen_summary(
            "hard",
            26,
            {"accused": "e08", "correct": True, "final_day": 6, "tool_calls": 44, "score": 0.74},
            c26["final"],
            s26_post["solver_final"],
        )
        assert duel_s26["caught_first"] == "human"
        assert duel_s26["ranking"] == ["human", "solver", "gemini"]

    panel_js = ROOT / "docs" / "arena" / "ui" / "ai_duel_panel.js"
    node_bin = shutil.which("node")
    if panel_js.is_file() and node_bin:
        js_code = (
            f"import * as p from {json.dumps(panel_js.as_uri())};"
            f"const c6 = {json.dumps(c6)};"
            "const pre = p.sanitizeGeminiView(c6, 6, false);"
            "const post = p.sanitizeGeminiView(c6, 6, true);"
            "console.log(JSON.stringify({pre, post}));"
        )
        np = subprocess.run(
            [node_bin, "--input-type=module", "-e", js_code],
            capture_output=True,
            text=True,
            check=True,
        )
        parsed_np = json.loads(np.stdout.strip())
        assert parsed_np["pre"]["status"] == "sealed_accusation"
        assert parsed_np["pre"]["final"] is None
        assert parsed_np["post"]["final"] == c6["final"]


def test_opencode_edge_cases_unavailable_tool_truncation_and_1bc3e281_detail() -> None:
    report = _cached_live_report()
    edge = report["opencode_compatibility_proof"]
    assert edge["flash_hard_episodes_verified"] == 30
    assert edge["client_refused_unavailable_tool_count"] == 1
    assert edge["client_truncated_output_count"] == 2
    assert edge["mismatch_count"] == 0
    assert report["summary"]["detail_1bc3e281_compat_steps_carbon"] > 0
    assert report["summary"]["detail_1bc3e281_compat_steps_total"] == 63

    refused_step = {
        "day": 3,
        "tool": "bash",
        "args": {"cmd": "ls"},
        "result": {
            "ok": False,
            "data": {},
            "error": "Model tried to call unavailable tool 'bash'. Available tools: status",
        },
    }
    assert vdp.is_client_refused_unavailable_tool(refused_step) is True
    assert vdp.is_client_refused_unavailable_tool({"tool": "status", "result": {"ok": False, "error": "x"}}) is False

    trunc_raw = {
        "raw": "...4096 bytes truncated... The tool call succeeded but the output was truncated. Full output saved to: /tmp/out.txt"
    }
    assert vdp.parse_client_truncated_bytes(trunc_raw) == 4096
    assert vdp.parse_client_truncated_bytes({"ok": True}) is None

    wrapped_err = {
        "ok": False,
        "error": json.dumps({"ok": False, "data": {}, "error": "invalid arguments"}),
    }
    assert vdp.unwrap_mcp_error_payload(wrapped_err) == {
        "ok": False,
        "data": {},
        "error": "invalid arguments",
    }

    ep6 = json.loads(json.dumps(_load_committed_gemini_row("hard", 6)))
    ep6["steps"].insert(2, refused_step)
    rep_with_refused = vdp.replay_and_verify_episode(ep6)
    assert rep_with_refused["parity_ok"] is True
    assert len(rep_with_refused["client_refused_steps"]) == 1
    assert rep_with_refused["server_step_count"] == 57

    ep6_bad_trunc = json.loads(json.dumps(_load_committed_gemini_row("hard", 6)))
    ep6_bad_trunc["steps"][0]["result"] = {
        "raw": "...999999 bytes truncated... The tool call succeeded but the output was truncated. Full output saved to: /tmp/x"
    }
    rep_bad_trunc = vdp.replay_and_verify_episode(ep6_bad_trunc)
    assert rep_bad_trunc["parity_ok"] is False
    assert any("truncated_byte_mismatch" in m["reason"] for m in rep_bad_trunc["step_mismatches"])

    ep6_bad_score = json.loads(json.dumps(_load_committed_gemini_row("hard", 6)))
    ep6_bad_score["score"] = 0.99
    rep_bad_score = vdp.replay_and_verify_episode(ep6_bad_score)
    assert rep_bad_score["parity_ok"] is False
    assert any(m.startswith("score:") for m in rep_bad_score["verdict_mismatches"])


def test_bundle_autodiscovery_clean_sibling_merge_and_negative_leak_controls(tmp_path: Path) -> None:
    report = _cached_live_report()
    c6 = report["featured_ai_duel_contracts"]["hard_seed_6"]

    clean_sim = _make_sim_root(tmp_path, "clean_sim")
    sealed_steps = []
    for st in c6["steps"]:
        if st["tool"] == "accuse":
            sealed_steps.append(
                {
                    **st,
                    "args": {"employee": "[SEALED]"},
                    "summary": "[SEALED]",
                    "sealed": True,
                }
            )
        else:
            sealed_steps.append(dict(st))

    reveal_b64 = base64.b64encode(
        json.dumps({"final": c6["final"], "mole": "e34"}).encode("utf-8")
    ).decode("ascii")
    clean_duel_pack = {
        "schema_version": "canary_duel_pack.v1",
        "seeds": {"hard": [6, 26], "medium": [0, 12]},
        "episodes": {
            "hard:6:gemini": {
                "tier": "hard",
                "seed": 6,
                "agent": "gemini",
                "steps": sealed_steps,
                "final": {"sealed": True, "final_day": 6},
                "sealed_reveal_b64": f"sealed:{reveal_b64}",
            }
        },
    }
    (clean_sim / "docs" / "arena" / "duel_pack.js").write_text(
        "globalThis.CANARY_DUEL_PACK = " + json.dumps(clean_duel_pack) + ";\n",
        encoding="utf-8",
    )
    inv_doc_bundle = {
        "tier": "hard",
        "seed": 6,
        "mode": "investigator",
        "done": False,
        "steps": [
            {
                "day": 1,
                "tool": "list_documents",
                "args": {},
                "ok": True,
                "result": {
                    "ok": True,
                    "data": {"documents": [{"id": "d1", "is_canary": False}]},
                    "error": None,
                },
            }
        ],
    }
    (clean_sim / "docs" / "demo" / "inv_docs.json").write_text(
        json.dumps(inv_doc_bundle),
        encoding="utf-8",
    )

    assert vdp.main(["--root", str(clean_sim), "--check"]) == 0
    clean_bundle_audit = vdp.audit_arena_and_demo_bundles(
        root=clean_sim,
        known_verdicts={
            ("hard", 6, "gemini"): dict(c6["final"]),
            ("hard", 6, "opencode:google/gemini-4-carbon"): dict(c6["final"]),
        },
        skip_rel_paths={vdp.DEFAULT_OUT_REL},
    )
    assert clean_bundle_audit["ok"] is True
    assert clean_bundle_audit["bundle_files_discovered"] == 2
    assert clean_bundle_audit["episodes_verified"] >= 1

    known_verdicts = {
        ("hard", 6, "gemini"): dict(c6["final"]),
        ("hard", 6, "opencode:google/gemini-4-carbon"): dict(c6["final"]),
    }

    leak_mole = {"tier": "hard", "seed": 6, "human_done": False, "mole": "e34", "steps": []}
    leaks_1, _, _ = vdp._scan_bundle_node(leak_mole, "ctrl_mole", known_verdicts)
    assert any(".mole" in x for x in leaks_1)

    day2_idx = next(i for i, st in enumerate(c6["steps"]) if st["day"] == 2)
    leaked_v_steps = json.loads(json.dumps(c6["steps"][: day2_idx + 1]))
    leaked_v_steps[day2_idx]["V"] = 0.93
    leak_true_v = {"tier": "hard", "seed": 6, "human_done": False, "steps": leaked_v_steps}
    leaks_2, _, _ = vdp._scan_bundle_node(leak_true_v, "ctrl_true_v", known_verdicts)
    assert any("unsurfaced true_V=0.93" in x for x in leaks_2)

    leak_accuse = {
        "tier": "hard",
        "seed": 6,
        "human_done": False,
        "steps": [
            {"day": 6, "call_idx": 0, "tool": "accuse", "args": {"employee": "e34"}, "ok": True, "summary": "Accused e34", "V": 0.73}
        ],
    }
    leaks_3, _, _ = vdp._scan_bundle_node(leak_accuse, "ctrl_accuse", known_verdicts)
    assert any("unsealed pre-end accuse target e34" in x for x in leaks_3)

    leak_mole_canary = {
        "tier": "medium",
        "seed": 3000,
        "mode": "be_the_mole",
        "done": False,
        "documents": [{"id": "d1", "is_canary": True}],
    }
    leaks_4, _, _ = vdp._scan_bundle_node(leak_mole_canary, "ctrl_mole_canary", known_verdicts)
    assert any("is_canary" in x for x in leaks_4)

    leak_seeds = {"seeds": {"hard": [6, 900000], "held": [800000]}}
    leaks_5, _, _ = vdp._scan_bundle_node(leak_seeds, "ctrl_seeds", known_verdicts)
    assert len(leaks_5) == 2

    bad_reveal_b64 = base64.b64encode(
        json.dumps({"final": {**c6["final"], "score": 0.99}}).encode("utf-8")
    ).decode("ascii")
    bad_pack_node = {
        "tier": "hard",
        "seed": 6,
        "agent": "gemini",
        "steps": sealed_steps,
        "final": {"sealed": True, "final_day": 6},
        "sealed_reveal_b64": f"sealed:{bad_reveal_b64}",
    }
    _, score_mis, _ = vdp._scan_bundle_node(bad_pack_node, "ctrl_bad_score", known_verdicts)
    assert any("0.99" in x for x in score_mis)

    bad_sim = _make_sim_root(tmp_path, "bad_sim")
    (bad_sim / "docs" / "arena" / "leak.json").write_text(json.dumps(leak_mole), encoding="utf-8")
    assert vdp.main(["--root", str(bad_sim), "--check"]) == 1

    tampered_sim = _make_sim_root(tmp_path, "tampered_artifact_sim")
    art_obj = json.loads((tampered_sim / vdp.DEFAULT_OUT_REL).read_text(encoding="utf-8"))
    art_obj["tiers"]["hard"]["gemini_mean_score"] = 0.999999
    (tampered_sim / vdp.DEFAULT_OUT_REL).write_text(json.dumps(art_obj), encoding="utf-8")
    assert vdp.main(["--root", str(tampered_sim), "--check"]) == 1
