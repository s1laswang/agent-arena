from __future__ import annotations

import importlib.util
import io
import json
import subprocess
import sys
import tokenize
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts" / "verify_research_deception.py"
SELF_PATH = Path(__file__).resolve()
H = chr(35)
EM = "\u2014"
EN = "\u2013"


def _load_verifier():
    spec = importlib.util.spec_from_file_location("verify_research_deception", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


V = _load_verifier()


def _valid_research_markdown() -> str:
    lines = [
        f"{H} Deception Grounding Synthesis",
        "",
        f"{H}{H} 1. Literature Grounding",
        "",
        f"{H}{H}{H} 1.1 Bond and DePaulo (2006)",
        "- **Citation:** Bond, C. F., & DePaulo, B. M. (2006). Accuracy of Deception Judgments.",
        "- **Live Link:** https://doi.org/10.1207/s15327957pspr1003_2 (also see https://doi.org/10.1016/S0065-2601(06)39004-1).",
        '> "We analyze the accuracy of deception judgments, synthesizing research results from 206 documents and 24,483 judges."',
        "",
        f"{H}{H} 2. Quantitative Canary Mapping",
        "",
        "On Canary `v1.4` hard (`n_employees = 40`, `n_days = 21`, `interview_lr = 1.2`, `p_evasive_innocent = 0.2`,",
        "`fingerprint_accuracy = 0.95`), frozen hash `a8f99c2537c91d72`, `SolverPolicy` scores `0.499 +/- 0.119`",
        "while OpenCode `gemini-4-carbon` scores `0.322 +/- 0.199` (raw paired gap `5.30 V`, luck-adjusted gap `4.19 V`,",
        "exhausting daily budget on `242` of `303` under-planted days via `plant_canary` crowding).",
        "",
        "| Channel | P(inn) | P(mole) | LLR+ | LLR- | KL |",
        "|---|---:|---:|---:|---:|---:|",
        "| `interview` (`hard`, `LR=1.2`) | 0.200 | 0.240 | +0.1823 | -0.0513 | `0.00477` nats |",
        "",
        f"{H}{H} 3. Concrete Proposals",
        "",
        f"{H}{H}{H} Proposal P9.1: Zero-Leakage Evidence Check",
        "Targets `canary/social/biases.py` and `canary/mole/dsl.py` via `PublicDayFacts` with strict zero hidden mole leakage",
        "while preserving the `v1.4` frozen hash when disabled.",
        "",
        "```json",
        json.dumps(
            {
                "name": "test_mole_v15",
                "rules": [],
                "default": {"leak": "random_seeded", "frame": "none"},
            },
            indent=2,
        ),
        "```",
        "",
    ]
    return "\n".join(lines)


def _init_git_repo(repo: Path, files: dict[str, str]) -> None:
    repo.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
    for rel, content in files.items():
        p = repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=repo, check=True)


def test_real_repo_passes_offline_verification(capsys):
    rc = V.main(["--root", str(ROOT), "--require-flagship", "--strict", "--json"])
    out = capsys.readouterr().out
    payload = json.loads(out)
    assert rc == 0
    assert payload["passed"] is True
    assert payload["elapsed_s"] < 30.0
    assert len(payload["docs_checked"]) >= 4
    assert payload["unique_url_count"] >= 100
    assert payload["verbatim_quote_count"] >= 75
    by_name = {r["name"]: r for r in payload["results"]}
    assert by_name["Research Target & Markdown Structure Audit"]["status"] == "PASS"
    assert by_name["Typography, Comment & Secret Hygiene"]["status"] == "PASS"
    assert by_name["Citation URLs & Verbatim Quotes Grounding"]["status"] == "PASS"
    assert by_name["Exact Canary Repo & Information-Theoretic Numbers Audit"]["status"] == "PASS"
    assert by_name["Concrete Proposals & Zero-Leakage Design Audit"]["status"] == "PASS"
    assert by_name["Protected Paths & Git Diff Guard"]["status"] == "PASS"


def test_self_files_zero_comments_zero_dashes_pure_ascii():
    for path in (SCRIPT_PATH, SELF_PATH):
        src = path.read_text(encoding="utf-8")
        assert EM not in src, f"em-dash found in {path}"
        assert EN not in src, f"en-dash found in {path}"
        assert H not in src, f"raw hash char found in {path}"
        assert all(ord(ch) < 128 for ch in src), f"non-ASCII char found in {path}"
        tokens = list(tokenize.generate_tokens(io.StringIO(src).readline))
        comment_tokens = [tok for tok in tokens if tok.type == tokenize.COMMENT]
        assert not comment_tokens, f"Python comment found in {path}: {comment_tokens}"


def test_structure_gate_catches_missing_flagship_unclosed_fence_and_bad_json(tmp_path):
    empty_root = tmp_path / "empty"
    empty_root.mkdir()
    assert V.check_doc_structure(empty_root, []).status == "FAIL"

    sub_only = tmp_path / "sub_only"
    doc_p = sub_only / "docs" / "research" / "01_test.md"
    doc_p.parent.mkdir(parents=True)
    doc_p.write_text(_valid_research_markdown(), encoding="utf-8")

    warn_res = V.check_doc_structure(sub_only, [doc_p], require_flagship=False)
    assert warn_res.status == "WARN"
    fail_req = V.check_doc_structure(sub_only, [doc_p], require_flagship=True)
    assert fail_req.status == "FAIL"

    flagship = sub_only / "docs" / "research-deception.md"
    flagship.write_text(_valid_research_markdown(), encoding="utf-8")
    pass_res = V.check_doc_structure(sub_only, [flagship, doc_p], require_flagship=True)
    assert pass_res.status == "PASS"

    unclosed = tmp_path / "unclosed.md"
    unclosed.write_text(_valid_research_markdown() + "\n```python\nx = 1\n", encoding="utf-8")
    res_unclosed = V.check_doc_structure(tmp_path, [unclosed], explicit_mode=True)
    assert res_unclosed.status == "FAIL"
    assert any("unclosed" in d for d in res_unclosed.details)

    bad_json = tmp_path / "bad_json.md"
    bad_json.write_text(_valid_research_markdown() + "\n```json\n{invalid}\n```\n", encoding="utf-8")
    res_json = V.check_doc_structure(tmp_path, [bad_json], explicit_mode=True)
    assert res_json.status == "FAIL"
    assert any("invalid JSON" in d for d in res_json.details)


def test_hygiene_catches_dashes_comments_coauthored_placeholders_and_secrets(tmp_path):
    clean_doc = tmp_path / "clean.md"
    clean_doc.write_text(_valid_research_markdown(), encoding="utf-8")
    clean_py = tmp_path / "clean.py"
    clean_py.write_text("x = 1\n", encoding="utf-8")
    assert V.check_hygiene(tmp_path, [clean_doc], extra_py_files=[clean_py]).status == "PASS"

    em_doc = tmp_path / "em.md"
    em_doc.write_text(_valid_research_markdown() + f"\nBad {EM} dash.\n", encoding="utf-8")
    res_em = V.check_hygiene(tmp_path, [em_doc], extra_py_files=[])
    assert res_em.status == "FAIL"
    assert any("U+2014" in d for d in res_em.details)

    en_doc = tmp_path / "en.md"
    en_doc.write_text(_valid_research_markdown() + f"\nPages 10{EN}20.\n", encoding="utf-8")
    res_en = V.check_hygiene(tmp_path, [en_doc], extra_py_files=[])
    assert res_en.status == "FAIL"
    assert any("U+2013" in d for d in res_en.details)

    co_doc = tmp_path / "co.md"
    co_doc.write_text(_valid_research_markdown() + "\nCo-Authored-By: Someone <a@b.c>\n", encoding="utf-8")
    res_co = V.check_hygiene(tmp_path, [co_doc], extra_py_files=[])
    assert res_co.status == "FAIL"
    assert any("Co-Authored-By" in d for d in res_co.details)

    todo_doc = tmp_path / "todo.md"
    todo_doc.write_text(_valid_research_markdown() + "\nTODO: add quote\n", encoding="utf-8")
    res_todo = V.check_hygiene(tmp_path, [todo_doc], extra_py_files=[])
    assert res_todo.status == "FAIL"
    assert any("todo_marker" in d for d in res_todo.details)

    raw_key = "AI" + "za" + "SyRealLookingToken" + ("Z" * 20)
    sec_doc = tmp_path / "sec.md"
    sec_doc.write_text(_valid_research_markdown() + f"\nk={raw_key}\n", encoding="utf-8")
    res_sec = V.check_hygiene(tmp_path, [sec_doc], extra_py_files=[])
    assert res_sec.status == "FAIL"
    joined = "\n".join(res_sec.details)
    assert "google_api_key" in joined
    assert raw_key not in joined

    commented_py = tmp_path / "commented.py"
    commented_py.write_text(f"x = 1  {H} forbidden comment\n", encoding="utf-8")
    res_py = V.check_hygiene(tmp_path, [clean_doc], extra_py_files=[commented_py])
    assert res_py.status == "FAIL"
    assert any("forbidden Python comment" in d for d in res_py.details)


def test_citations_and_quotes_extracts_paren_doi_and_catches_missing_grounding(tmp_path):
    good_doc = tmp_path / "good.md"
    good_doc.write_text(_valid_research_markdown(), encoding="utf-8")
    url_map, q_cnt = V.extract_urls_and_quotes(tmp_path, [good_doc])
    assert "https://doi.org/10.1016/S0065-2601(06)39004-1" in url_map
    assert "https://doi.org/10.1207/s15327957pspr1003_2" in url_map
    assert q_cnt == 1
    assert V.check_citations_and_quotes(tmp_path, [good_doc]).status == "PASS"

    no_quote = tmp_path / "no_quote.md"
    no_quote.write_text(
        "\n".join(
            [
                f"{H} Title",
                f"{H}{H} Sec 1",
                f"{H}{H}{H} 1.1 Study",
                "- **Citation:** Doe (2020).",
                "- **Link:** https://doi.org/10.1037/h0040525",
                f"{H}{H} Sec 2",
                "Body without blockquote.",
            ]
        ),
        encoding="utf-8",
    )
    res_nq = V.check_citations_and_quotes(tmp_path, [no_quote])
    assert res_nq.status == "FAIL"
    assert any("blockquote" in d for d in res_nq.details)

    bad_link = tmp_path / "bad_link.md"
    bad_link.write_text(
        _valid_research_markdown()
        + f"\nSee [missing](does_not_exist.md) and [bad anchor]({H}missing-section) and https://example.com/fake.pdf.\n",
        encoding="utf-8",
    )
    res_bl = V.check_citations_and_quotes(tmp_path, [bad_link])
    assert res_bl.status == "FAIL"
    joined = "\n".join(res_bl.details)
    assert "broken relative markdown link" in joined
    assert "broken internal heading anchor" in joined
    assert "example.com" in joined


def test_http_verification_with_injected_fetcher(tmp_path):
    doc = tmp_path / "http_doc.md"
    doc.write_text(_valid_research_markdown(), encoding="utf-8")

    ok_res = V.check_citations_and_quotes(
        tmp_path,
        [doc],
        check_http=True,
        http_fetcher=lambda u, t: (200, "ok"),
    )
    assert ok_res.status == "PASS"
    assert "2/2 live HTTP-verified" in ok_res.summary

    dead_res = V.check_citations_and_quotes(
        tmp_path,
        [doc],
        check_http=True,
        http_fetcher=lambda u, t: (404, "not-found") if "10.1016" in u else (200, "ok"),
    )
    assert dead_res.status == "FAIL"
    assert any("404" in d for d in dead_res.details)

    warn_res = V.check_citations_and_quotes(
        tmp_path,
        [doc],
        check_http=True,
        strict_http=False,
        http_fetcher=lambda u, t: (403, "anti-bot"),
    )
    assert warn_res.status == "WARN"

    strict_fail = V.check_citations_and_quotes(
        tmp_path,
        [doc],
        check_http=True,
        strict_http=True,
        http_fetcher=lambda u, t: (403, "anti-bot"),
    )
    assert strict_fail.status == "FAIL"


def test_repo_numbers_catches_mismatches_and_stale_claims(tmp_path):
    good = tmp_path / "good.md"
    good.write_text(_valid_research_markdown(), encoding="utf-8")
    assert V.check_repo_numbers(ROOT, [good]).status == "PASS"

    bad_hash = tmp_path / "bad_hash.md"
    bad_hash.write_text(
        _valid_research_markdown().replace("a8f99c2537c91d72", "deadbeef12345678"),
        encoding="utf-8",
    )
    res_hash = V.check_repo_numbers(ROOT, [bad_hash])
    assert res_hash.status == "FAIL"
    assert any("tier hash mismatch" in d for d in res_hash.details)

    bad_param = tmp_path / "bad_param.md"
    bad_param.write_text(
        _valid_research_markdown().replace("n_employees = 40", "n_employees = 30"),
        encoding="utf-8",
    )
    res_param = V.check_repo_numbers(ROOT, [bad_param])
    assert res_param.status == "FAIL"
    assert any("n_employees" in d for d in res_param.details)

    bad_kl = tmp_path / "bad_kl.md"
    bad_kl.write_text(
        _valid_research_markdown().replace("0.00477", "0.09999"),
        encoding="utf-8",
    )
    res_kl = V.check_repo_numbers(ROOT, [bad_kl])
    assert res_kl.status == "FAIL"
    assert any("KL claimed" in d for d in res_kl.details)

    bad_score = tmp_path / "bad_score.md"
    bad_score.write_text(
        _valid_research_markdown().replace("0.322 +/- 0.199", "0.410 +/- 0.199"),
        encoding="utf-8",
    )
    res_score = V.check_repo_numbers(ROOT, [bad_score])
    assert res_score.status == "FAIL"
    assert any("0.410" in d for d in res_score.details)

    stale_doc = tmp_path / "stale.md"
    stale_doc.write_text(_valid_research_markdown() + "\nNote: frontier gap is not established.\n", encoding="utf-8")
    res_stale = V.check_repo_numbers(ROOT, [stale_doc])
    assert res_stale.status == "FAIL"
    assert any("gap_not_established" in d for d in res_stale.details)

    flash_doc = tmp_path / "flash.md"
    flash_doc.write_text(_valid_research_markdown() + "\nRow: gemini-3.5-flash 75% / 22%.\n", encoding="utf-8")
    res_flash = V.check_repo_numbers(ROOT, [flash_doc])
    assert res_flash.status == "FAIL"
    assert any("unapproved_flash_gap_row" in d for d in res_flash.details)


def test_proposals_and_protected_paths_guard(tmp_path):
    no_prop = tmp_path / "no_prop.md"
    no_prop.write_text(
        "\n".join(
            [
                f"{H} Pure Literature",
                f"{H}{H} Sec 1",
                "https://doi.org/10.1037/h0040525",
                '> "Substantive verbatim quote from primary literature source."',
                f"{H}{H} Sec 2",
                "Mentions v1.4 and plant_canary without proposals.",
            ]
        ),
        encoding="utf-8",
    )
    assert V.check_proposals(tmp_path, [no_prop]).status == "FAIL"

    bad_mole_json = tmp_path / "bad_mole.md"
    bad_mole_json.write_text(
        _valid_research_markdown().replace('"leak": "random_seeded"', '"wrong_key": "x"'),
        encoding="utf-8",
    )
    res_mole = V.check_proposals(tmp_path, [bad_mole_json])
    assert res_mole.status == "FAIL"
    assert any("missing 'leak'" in d for d in res_mole.details)

    repo = tmp_path / "git_guard"
    _init_git_repo(
        repo,
        {
            ".github/protected-paths.txt": "canary/env.py\ncanary/rules.py\nharbor/\n",
            "docs/research-deception.md": _valid_research_markdown(),
            "canary/rules.py": "TIERS_VERSION = 'v1.4'\n",
        },
    )
    subprocess.run(["git", "branch", "base-ref"], cwd=repo, check=True)
    assert V.check_protected_paths(repo, base_ref="base-ref").status == "PASS"

    (repo / "canary" / "rules.py").write_text("TIERS_VERSION = 'v1.5'\n", encoding="utf-8")
    res_prot = V.check_protected_paths(repo, base_ref="base-ref")
    assert res_prot.status == "FAIL"
    assert any("canary/rules.py" in d for d in res_prot.details)
