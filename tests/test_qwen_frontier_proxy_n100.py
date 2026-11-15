from __future__ import annotations

import ast
import copy
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import time
import tokenize
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts" / "audit_qwen_frontier_proxy_n100.py"
JSON_PATH = ROOT / "results" / "moletrain" / "qwen_frontier_proxy_n100.json"
MD_PATH = ROOT / "docs" / "reports" / "qwen_frontier_proxy_n100.md"
TEST_PATH = Path(__file__).resolve()


def _load_audit_module():
    spec = importlib.util.spec_from_file_location("audit_qwen_frontier_proxy_n100", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


M = _load_audit_module()


def _build_synthetic_log_from_committed(doc: dict) -> str:
    prov = doc["provenance"]
    raw_final = {
        "schema": doc["schema"],
        "tier": doc["tier"],
        "n_per_split": doc["n_per_split"],
        "splits": copy.deepcopy(doc["splits"]),
        "shared_world_secret_sha256_16": doc["shared_world_secret_sha256_16"],
        "agents": list(doc["agents"]),
        "cpu_baselines": copy.deepcopy(doc["cpu_baselines"]),
        "qwen_v100_models": {},
        "total_seconds": prov["total_seconds"],
    }

    for run_id, m_obj in doc["qwen_v100_models"].items():
        modes_full = {}
        for mode, md_obj in m_obj["modes"].items():
            sp_full = {}
            for sp, sv in md_obj.items():
                s = sv["summary"]
                sv_copy = copy.deepcopy(sv)
                for dk, bname in (
                    ("diff_vs_default", "default_mole"),
                    ("diff_vs_rl_v1", "rl_mole_v1"),
                    ("diff_vs_rl_v2", "rl_mole_v2"),
                ):
                    base_s = doc["cpu_baselines"][bname][sp]
                    d_blk = sv_copy[dk]
                    d_blk["regret_gemini_carbon_proxy"] = list(d_blk["frontier_proxy_gap_gain"])
                    for ag in ("gemini_carbon_proxy", "grok_tactics", "heuristic", "hinted_heuristic"):
                        sc_k = f"{ag}_score"
                        if sc_k not in d_blk:
                            pt = round(float(s[ag]["score"][0]) - float(base_s[ag]["score"][0]), 4)
                            d_blk[sc_k] = [pt, round(pt - 0.05, 4), round(pt + 0.05, 4)]
                        rg_k = f"regret_{ag}"
                        if rg_k not in d_blk:
                            pt_r = round(
                                (float(s["solver"]["score"][0]) - float(s[ag]["score"][0]))
                                - (float(base_s["solver"]["score"][0]) - float(base_s[ag]["score"][0])),
                                4,
                            )
                            d_blk[rg_k] = [pt_r, round(pt_r - 0.05, 4), round(pt_r + 0.05, 4)]
                sp_full[sp] = sv_copy
            modes_full[mode] = sp_full
        raw_final["qwen_v100_models"][run_id] = {
            "model": m_obj["model"],
            "modes": modes_full,
            "mutual_information_24actions": copy.deepcopy(m_obj["mutual_information_24actions"]),
        }

    lines = [
        f"=== [{prov['job_name']}] Host, Date, GPU ===",
        prov["host"],
        prov["started_utc"],
        "name, memory.total [MiB], memory.free [MiB]",
        f"{prov['gpu_model']}, {prov['gpu_vram_mib']} MiB, 32495 MiB",
        f"[init] device={prov['device']} secret_sha16={doc['shared_world_secret_sha256_16']}",
    ]
    for bname, sec in prov["cpu_baseline_seconds"].items():
        lines.append(f"[cpu_baseline] {bname} n=100x2 done in {sec:.1f}s")
    lines.append(f"[mi_views] collected={prov['mi_views_collected']}")

    for run_id, _, modes in M.QWEN_MODEL_SPECS:
        mi = doc["qwen_v100_models"][run_id]["mutual_information_24actions"]
        lines.append(f"[mi] {run_id}: {json.dumps(mi)}")
        for mode in modes:
            md_obj = doc["qwen_v100_models"][run_id]["modes"][mode]
            s8 = md_obj["heldout_800k_n100"]["summary"]
            s2 = md_obj["heldout_200k_n100"]["summary"]
            lines.append(
                f"[done] {run_id}:{mode} 800k acc={s8['solver']['acc'][0]} gap={json.dumps(s8['frontier_proxy_gap'])} "
                f"200k acc={s2['solver']['acc'][0]} gap={json.dumps(s2['frontier_proxy_gap'])} "
                f"min_reg3={s2['min_regret_scripted3']}"
            )

    lines.append(f"[FINAL_PROXY_N100_JSON] {json.dumps(raw_final)}")
    lines.append(f"=== [{prov['job_name']}] COMPLETE ===")
    lines.append(prov["completed_utc"])
    return "\n".join(lines) + "\n"


def test_hygiene_zero_comments_zero_dashes_zero_forbidden_imports():
    hash_ch = chr(35)
    em_dash = chr(0x2014)
    en_dash = chr(0x2013)
    co_author = "co-authored" + "-by"
    forbidden_modules = {
        "torch",
        "transformers",
        "peft",
        "trl",
        "cuda",
        "google",
        "genai",
        "openai",
        "anthropic",
    }

    for py_path in (SCRIPT_PATH, TEST_PATH):
        src = py_path.read_text(encoding="utf-8")
        assert hash_ch not in src, f"forbidden hash character in {py_path}"
        toks = list(tokenize.generate_tokens(io.StringIO(src).readline))
        assert [t for t in toks if t.type == tokenize.COMMENT] == []
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert alias.name.split(".")[0] not in forbidden_modules
            elif isinstance(node, ast.ImportFrom) and node.module:
                assert node.module.split(".")[0] not in forbidden_modules

    for artifact_path in (SCRIPT_PATH, JSON_PATH, MD_PATH, TEST_PATH):
        assert artifact_path.is_file(), f"missing deliverable: {artifact_path}"
        txt = artifact_path.read_text(encoding="utf-8")
        assert em_dash not in txt, f"em-dash found in {artifact_path}"
        assert en_dash not in txt, f"en-dash found in {artifact_path}"
        assert co_author not in txt.lower(), f"co-author trailer found in {artifact_path}"

    assert JSON_PATH.stat().st_size < 25_000
    assert JSON_PATH.stat().st_size < 25 * 1024
    assert "torch" not in sys.modules
    assert "transformers" not in sys.modules


def test_offline_check_fast_and_gitless_shallow_ci(tmp_path: Path):
    t0 = time.perf_counter()
    rc = M.main(["--check"])
    elapsed = time.perf_counter() - t0
    assert rc == 0
    assert elapsed < 1.0

    gitless = tmp_path / "gitless_ci_root"
    (gitless / "results" / "moletrain").mkdir(parents=True)
    (gitless / "docs" / "reports").mkdir(parents=True)
    (gitless / "scripts").mkdir(parents=True)

    shutil.copy2(JSON_PATH, gitless / "results" / "moletrain" / "qwen_frontier_proxy_n100.json")
    shutil.copy2(MD_PATH, gitless / "docs" / "reports" / "qwen_frontier_proxy_n100.md")
    shutil.copy2(SCRIPT_PATH, gitless / "scripts" / "audit_qwen_frontier_proxy_n100.py")

    rc_gitless = M.main(
        [
            "--check",
            "--out-json",
            str(gitless / "results" / "moletrain" / "qwen_frontier_proxy_n100.json"),
            "--out-md",
            str(gitless / "docs" / "reports" / "qwen_frontier_proxy_n100.md"),
            "--repo-root",
            str(gitless),
        ]
    )
    assert rc_gitless == 0

    empty_home = tmp_path / "isolated_home"
    empty_home.mkdir()
    env = {**os.environ, "HOME": str(empty_home)}
    t_sub = time.perf_counter()
    proc = subprocess.run(
        [sys.executable, "scripts/audit_qwen_frontier_proxy_n100.py", "--check"],
        cwd=gitless,
        env=env,
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )
    sub_elapsed = time.perf_counter() - t_sub
    assert proc.returncode == 0, proc.stderr
    assert sub_elapsed < 1.0
    assert "OK: offline check passed" in proc.stdout


def test_committed_metrics_catchability_mi_and_markdown_parity():
    doc = json.loads(JSON_PATH.read_text(encoding="utf-8"))
    assert M.validate_artifact(doc, repo_root=ROOT) == []
    assert MD_PATH.read_text(encoding="utf-8") == M.render_markdown(doc)

    assert doc["schema"] == "qwen_frontier_proxy_n100_v1"
    assert doc["tiers_version"] == "v1.4"
    assert doc["tier"] == "hard"
    assert doc["n_per_split"] == 100
    assert doc["total_paired_seeds"] == 200
    assert doc["splits"] == {
        "rules_heldout_800k": "800000-800099",
        "ws3_heldout_200k": "200000-200099",
    }
    assert doc["shared_world_secret_sha256_16"] == "35c2090f05fb78b9"
    assert doc["all_qwen_v100_catchable_85"] is True

    prov = doc["provenance"]
    assert prov["final_json_line"] == 125
    assert prov["mi_log_lines"] == {
        "canary-qwen3-1p7b-mole-v1": 18,
        "canary-qwen3-0p6b-mole-v1": 82,
        "canary-qwen-mole-v1": 112,
    }
    assert prov["mi_views_collected"] == 185
    assert prov["device"] == "cuda"
    assert "Tesla V100" in prov["gpu_model"]

    cpu = doc["cpu_baselines"]
    assert cpu["rl_mole_v1"]["heldout_800k_n100"]["solver"]["acc"][0] == 0.82
    assert cpu["rl_mole_v1"]["heldout_800k_n100"]["catchable_85"] is False
    assert cpu["rl_mole_v1"]["heldout_200k_n100"]["solver"]["acc"][0] == 0.75
    assert cpu["rl_mole_v1"]["heldout_200k_n100"]["catchable_85"] is False
    assert cpu["rl_mole_v2"]["heldout_800k_n100"]["solver"]["acc"][0] == 0.95
    assert cpu["rl_mole_v2"]["heldout_200k_n100"]["solver"]["acc"][0] == 0.97
    assert cpu["rl_mole_v2"]["heldout_200k_n100"]["frontier_proxy_gap"] == [0.4047, 0.2989, 0.518]
    assert cpu["carbon_distilled_dsl"]["heldout_800k_n100"]["catchable_85"] is True
    assert cpu["carbon_distilled_dsl"]["heldout_200k_n100"]["min_regret_scripted3"] == 0.321

    qwen = doc["qwen_v100_models"]
    assert qwen["canary-qwen3-1p7b-mole-v1"]["mutual_information_24actions"]["mi_nats"] == 0.032337
    assert qwen["canary-qwen3-0p6b-mole-v1"]["mutual_information_24actions"]["mi_nats"] == 0.065003
    assert qwen["canary-qwen-mole-v1"]["mutual_information_24actions"]["mi_nats"] == 0.017108

    best = doc["best_model"]
    assert best["run_id"] == "canary-qwen3-0p6b-mole-v1"
    assert best["mode"] == "constrained_trap_only_none"
    assert best["catchable_85"] is True
    assert best["solver_acc_800k"] == 0.98
    assert best["solver_acc_200k"] == 0.97
    assert best["frontier_proxy_gap_800k"] == [0.3993, 0.2956, 0.5066]
    assert best["frontier_proxy_gap_200k"] == [0.3632, 0.2744, 0.4493]
    assert best["mean_frontier_proxy_gap_200seeds"] == 0.3812

    c06_800 = qwen["canary-qwen3-0p6b-mole-v1"]["modes"]["constrained_trap_only_none"]["heldout_800k_n100"]
    assert c06_800["diff_vs_default"]["gemini_carbon_proxy_score"][2] < 0.0
    assert c06_800["diff_vs_rl_v1"]["frontier_proxy_gap_gain"][1] > 0.0

    c17_200 = qwen["canary-qwen3-1p7b-mole-v1"]["modes"]["greedy"]["heldout_200k_n100"]
    assert c17_200["summary"]["min_regret_scripted3"] == 0.3508
    for ag in ("grok_tactics", "heuristic", "hinted_heuristic"):
        assert c17_200["diff_vs_default"][f"regret_{ag}"][1] > 0.0

    md_txt = MD_PATH.read_text(encoding="utf-8")
    for token in (
        "800000-800099",
        "200000-200099",
        "0.065003",
        "0.032337",
        "0.017108",
        "0.3993 [0.2956, 0.5066]",
        "0.3632 [0.2744, 0.4493]",
        "0.3508",
        "35c2090f05fb78b9",
    ):
        assert token in md_txt


def test_from_log_roundtrip_and_tamper_guards(tmp_path: Path):
    base_doc = json.loads(JSON_PATH.read_text(encoding="utf-8"))
    synth_log = tmp_path / "canary-qwen-frontier-proxy-n100-r2.log"
    synth_log.write_text(_build_synthetic_log_from_committed(base_doc), encoding="utf-8")

    out_json = tmp_path / "out" / "qwen_frontier_proxy_n100.json"
    out_md = tmp_path / "out" / "qwen_frontier_proxy_n100.md"
    assert M.main(["--from-log", str(synth_log), "--out-json", str(out_json), "--out-md", str(out_md)]) == 0
    assert out_json.stat().st_size < M.MAX_JSON_BYTES
    assert (
        M.main(["--from-log", str(synth_log), "--out-json", str(out_json), "--out-md", str(out_md), "--check"])
        == 0
    )
    assert M.main(["--check", "--out-json", str(out_json), "--out-md", str(out_md)]) == 0

    parsed = json.loads(out_json.read_text(encoding="utf-8"))
    assert parsed["cpu_baselines"] == base_doc["cpu_baselines"]
    assert parsed["qwen_v100_models"] == base_doc["qwen_v100_models"]
    assert parsed["best_model"] == base_doc["best_model"]
    assert parsed["headline"] == base_doc["headline"]

    bad_ci = copy.deepcopy(parsed)
    bad_ci["cpu_baselines"]["default_mole"]["heldout_800k_n100"]["solver"]["score"] = [0.6148, 0.65, 0.68]
    p_bad_ci = tmp_path / "bad_ci.json"
    p_bad_ci.write_text(M.format_artifact_json(bad_ci), encoding="utf-8")
    assert M.main(["--check", "--out-json", str(p_bad_ci), "--out-md", str(out_md)]) == 1

    bad_catch = copy.deepcopy(parsed)
    bad_catch["cpu_baselines"]["rl_mole_v1"]["heldout_200k_n100"]["catchable_85"] = True
    p_bad_catch = tmp_path / "bad_catch.json"
    p_bad_catch.write_text(M.format_artifact_json(bad_catch), encoding="utf-8")
    assert M.main(["--check", "--out-json", str(p_bad_catch), "--out-md", str(out_md)]) == 1

    bad_mi = copy.deepcopy(parsed)
    bad_mi["qwen_v100_models"]["canary-qwen3-0p6b-mole-v1"]["mutual_information_24actions"]["mi_nats"] = 0.123456
    p_bad_mi = tmp_path / "bad_mi.json"
    p_bad_mi.write_text(M.format_artifact_json(bad_mi), encoding="utf-8")
    assert M.main(["--check", "--out-json", str(p_bad_mi), "--out-md", str(out_md)]) == 1

    bad_seed = copy.deepcopy(parsed)
    bad_seed["seed_ranges"]["ws3_heldout"] = [900_000, 900_099]
    p_bad_seed = tmp_path / "bad_seed.json"
    p_bad_seed.write_text(M.format_artifact_json(bad_seed), encoding="utf-8")
    assert M.main(["--check", "--out-json", str(p_bad_seed), "--out-md", str(out_md)]) == 1

    p_oversized = tmp_path / "oversized.json"
    p_oversized.write_text(" " * 25_001 + M.format_artifact_json(parsed), encoding="utf-8")
    assert M.main(["--check", "--out-json", str(p_oversized), "--out-md", str(out_md)]) == 1

    drifted_md = tmp_path / "drifted.md"
    drifted_md.write_text(out_md.read_text(encoding="utf-8") + "\nextra line\n", encoding="utf-8")
    assert M.main(["--check", "--out-json", str(out_json), "--out-md", str(drifted_md)]) == 1

    corrupt_log = tmp_path / "corrupt.log"
    corrupt_log.write_text(
        synth_log.read_text(encoding="utf-8").replace('"mi_nats": 0.065003', '"mi_nats": 0.099999', 1),
        encoding="utf-8",
    )
    assert M.main(["--from-log", str(corrupt_log), "--out-json", str(out_json), "--out-md", str(out_md)]) == 1
