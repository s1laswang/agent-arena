from __future__ import annotations

import importlib.util
import io
import json
import subprocess
import sys
import tempfile
import tokenize
from pathlib import Path
from typing import Iterator

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts" / "audit_arena_hygiene.py"
SELF_PATH = Path(__file__).resolve()
OPENCODE_TMP = Path("/tmp/opencode")

H = chr(35)
EM_DASH = chr(0x2014)
EN_DASH = chr(0x2013)
UNICODE_MINUS = chr(0x2212)
SLASH_SLASH = chr(47) * 2
SLASH_STAR = chr(47) + chr(42)
STAR_SLASH = chr(42) + chr(47)
HTTPS_SCHEME = "https" + ":" + SLASH_SLASH

TOK_WORLD_SECRET = "CANARY_" + "WORLD_SECRET"
TOK_LEDGER_TOKEN = "CANARY_" + "LEDGER_TOKEN"
TOK_JUDGE_SALT = "data/worlds/" + "judge/SALT"
FAKE_AI_KEY = "AI" + "zaSyD1234567890abcdefGHIJKL"
FAKE_SK_KEY = "s" + "k-proj-1234567890abcdefGHIJ"
FAKE_GHP_KEY = "gh" + "p_1234567890abcdefghijKLMN"

PNG_1X1 = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"

PROTECTED_PATHS = (
    "canary/env.py",
    "canary/rules.py",
    "canary/reproduce.py",
    "canary/solver",
    "harbor",
)


def _load_module():
    spec = importlib.util.spec_from_file_location("audit_arena_hygiene", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


arena_hygiene = _load_module()


@pytest.fixture()
def arena_tmp() -> Iterator[Path]:
    OPENCODE_TMP.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=str(OPENCODE_TMP), prefix="test-arena-hygiene-") as tmp_str:
        yield Path(tmp_str)


def _write_files(repo: Path, files: dict[str, str | bytes]) -> None:
    repo.mkdir(parents=True, exist_ok=True)
    for rel, content in files.items():
        target = repo / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            target.write_bytes(content)
        else:
            target.write_text(content, encoding="utf-8")


def _make_clean_arena_repo(repo: Path) -> Path:
    _write_files(
        repo,
        {
            "docs/arena/README.md": (
                f"{H} Canary Arena\n\n"
                f"See [walkthrough](WALKTHROUGH.md{H}quick-path), [UI](ui/app.js), "
                f"and [license]({HTTPS_SCHEME}creativecommons.org/publicdomain/zero/1.0/).\n"
                f"Never depends on `{TOK_WORLD_SECRET}`.\n"
                "![badge](assets/badge.png)\n"
            ),
            "docs/arena/WALKTHROUGH.md": (
                f"{H} Walkthrough\n\n"
                f"{H}{H} Quick Path\n\n"
                " Keyless offline walkthrough.\n"
            ),
            "docs/arena/ui/app.js": (
                "const FORBIDDEN_TRUTH_KEYS = new Set([\n"
                '  "mole",\n'
                f'  "{TOK_WORLD_SECRET}"\n'
                "]);\n"
                "export function mountArena() {\n"
                "  return FORBIDDEN_TRUTH_KEYS.size;\n"
                "}\n"
            ),
            "docs/arena/ui/arena.css": ".arena-shell { display: grid; gap: 8px; }\n",
            "docs/arena/assets/badge.png": PNG_1X1,
        },
    )
    return repo


def test_owned_files_strict_hygiene() -> None:
    literal_secret_probes = (
        "AI" + "zaSy",
        "s" + "k-proj-",
        "gh" + "p_",
        TOK_WORLD_SECRET,
        TOK_LEDGER_TOKEN,
        TOK_JUDGE_SALT,
    )
    for py_path in (SCRIPT_PATH, SELF_PATH):
        raw = py_path.read_text(encoding="utf-8")
        assert raw.isascii(), f"non-ASCII character in {py_path.name}"
        assert H not in raw, f"unexpected hash character in {py_path.name}"
        assert EM_DASH not in raw, f"em dash in {py_path.name}"
        assert EN_DASH not in raw, f"en dash in {py_path.name}"
        assert UNICODE_MINUS not in raw, f"unicode minus in {py_path.name}"
        assert SLASH_SLASH not in raw, f"double-slash comment marker in {py_path.name}"
        for probe in literal_secret_probes:
            assert probe not in raw, f"raw literal probe '{probe}' found in {py_path.name}"
        tokens = list(tokenize.generate_tokens(io.StringIO(raw).readline))
        comments = [tok for tok in tokens if tok.type == tokenize.COMMENT]
        assert comments == [], f"python comment token found in {py_path.name}"


def test_real_repo_passes_check_and_json(capsys: pytest.CaptureFixture[str]) -> None:
    assert arena_hygiene.audit_repo is arena_hygiene.audit_arena_hygiene
    assert arena_hygiene.MAX_ARENA_BYTES == 15 * 1024 * 1024

    results = arena_hygiene.audit_arena_hygiene(ROOT)
    assert [r.name for r in results] == list(arena_hygiene.CHECK_NAMES)
    for item in results:
        assert item.status == "PASS", f"{item.name} failed: {item.details}"

    rc_json = arena_hygiene.main(["--check", "--json", "--root", str(ROOT)])
    payload = json.loads(capsys.readouterr().out)
    assert rc_json == 0
    assert payload["check_mode"] is True
    assert payload["passed"] is True
    assert payload["elapsed_s"] < 5.0
    assert 0 < payload["arena_bytes"] < arena_hygiene.MAX_ARENA_BYTES
    assert payload["max_arena_bytes"] == arena_hygiene.MAX_ARENA_BYTES
    assert payload["checks"] == payload["results"]
    assert len(payload["results"]) == 5

    proc = subprocess.run(
        [sys.executable, str(SCRIPT_PATH), "--check"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "5 PASS, 0 WARN, 0 FAIL" in proc.stdout


@pytest.mark.parametrize(
    ("rel_path", "bad_content", "expected_fragment"),
    [
        ("docs/arena/data/config.js", f'export const KEY = "{FAKE_AI_KEY}";\n', "google_api_key"),
        ("docs/arena/data/openai.json", f'{{"apiKey": "{FAKE_SK_KEY}"}}\n', "sk_api_key"),
        ("docs/arena/README.md", f"{H} Arena\nToken: {FAKE_GHP_KEY}\n", "github_pat"),
        ("docs/arena/data/leak.json", f'{{"{TOK_WORLD_SECRET}": " leaked_val_123"}}\n', TOK_WORLD_SECRET),
        ("docs/arena/ui/app.js", f"const s = process.env.{TOK_WORLD_SECRET};\n", TOK_WORLD_SECRET),
        ("docs/arena/README.md", f"{H} Arena\nExport {TOK_WORLD_SECRET}=secretvalue123\n", TOK_WORLD_SECRET),
        ("docs/arena/data/ledger.js", f'export const hdr = "{TOK_LEDGER_TOKEN}";\n', TOK_LEDGER_TOKEN),
        ("docs/arena/mole_mode.py", f'SALT_FILE = "{TOK_JUDGE_SALT}"\n', TOK_JUDGE_SALT),
    ],
)
def test_secret_and_credential_tokens_fail(
    arena_tmp: Path,
    capsys: pytest.CaptureFixture[str],
    rel_path: str,
    bad_content: str,
    expected_fragment: str,
) -> None:
    repo = _make_clean_arena_repo(arena_tmp / "secret_case")
    _write_files(repo, {rel_path: bad_content})

    res = arena_hygiene.check_arena_secrets(repo)
    assert res.status == "FAIL"
    assert any(rel_path in d and expected_fragment in d for d in res.details), res.details

    rc = arena_hygiene.main(["--check", "--json", "--root", str(repo)])
    payload = json.loads(capsys.readouterr().out)
    assert rc == 1
    assert payload["passed"] is False


def test_forbidden_secret_filenames_and_raw_salt_bytes_fail(arena_tmp: Path) -> None:
    for bad_name in ("docs/arena/SALT", "docs/arena/.env", "docs/arena/data/seed6.world.json"):
        repo = _make_clean_arena_repo(arena_tmp / Path(bad_name).name.replace(".", "_"))
        _write_files(repo, {bad_name: "placeholder\n"})
        res = arena_hygiene.check_arena_secrets(repo)
        assert res.status == "FAIL"
        assert any(bad_name in d for d in res.details), res.details

    salt_repo = _make_clean_arena_repo(arena_tmp / "raw_salt_leak")
    _write_files(
        salt_repo,
        {
            TOK_JUDGE_SALT: "ultra_secret_judge_salt_998877\n",
            "docs/arena/data/pack.js": 'export const blob = "ultra_secret_judge_salt_998877";\n',
        },
    )
    res_salt = arena_hygiene.check_arena_secrets(salt_repo)
    assert res_salt.status == "FAIL"
    assert any("raw repository secret bytes" in d for d in res_salt.details), res_salt.details


@pytest.mark.parametrize(
    "endpoint",
    [
        "generativelanguage." + "googleapis.com",
        "api." + "openai.com",
        "api." + "anthropic.com",
        "api." + "x.ai",
    ],
)
def test_live_outbound_llm_endpoints_fail(
    arena_tmp: Path,
    capsys: pytest.CaptureFixture[str],
    endpoint: str,
) -> None:
    repo = _make_clean_arena_repo(arena_tmp / endpoint.replace(".", "_"))
    _write_files(
        repo,
        {
            "docs/arena/data/client.js": f'const url = "{HTTPS_SCHEME}{endpoint}/v1/chat";\n',
        },
    )
    res = arena_hygiene.check_arena_outbound_endpoints(repo)
    assert res.status == "FAIL"
    assert any("docs/arena/data/client.js:1" in d and endpoint in d for d in res.details), res.details

    rc = arena_hygiene.main(["--check", "--root", str(repo)])
    out = capsys.readouterr().out
    assert rc == 1
    assert endpoint in out


def test_markdown_internal_links_anchors_and_images(arena_tmp: Path) -> None:
    clean_repo = _make_clean_arena_repo(arena_tmp / "md_clean")
    _write_files(
        clean_repo,
        {
            "docs/reports/gap.md": f"{H} Frontier Gap\n\n{H}{H} Calibration\nDetails.\n",
            "docs/arena/index.html": '<!doctype html><div id="arena-root"></div>\n',
            "canary/rules.py": 'TIERS_VERSION = "v1.4"\nKNOWN_V_MODE = True\n',
            "docs/arena/WALKTHROUGH.md": "\n".join(
                [
                    f"{H} Walkthrough",
                    f"{H}{H} Quick Path",
                    f"Jump to [second note]({H}notes-1), [gap](../reports/gap.md{H}calibration),",
                    f"[html mount](index.html{H}arena-root), [rules](../../canary/rules.py{H}L1-L2),",
                    "and <img src=\"assets/badge.png\" width=\"16\" alt=\"badge\">.",
                    f"Inline `[ignored](missing_inline.md)` is ignored.",
                    "```markdown",
                    "[ignored_fenced](missing_fenced.md)",
                    "```",
                    f"{H}{H} Notes",
                    "First.",
                    f"{H}{H} Notes",
                    "Second.",
                ]
            )
            + "\n",
        },
    )
    res_ok = arena_hygiene.check_arena_markdown_links(clean_repo)
    assert res_ok.status == "PASS", res_ok.details

    broken_repo = _make_clean_arena_repo(arena_tmp / "md_broken")
    _write_files(
        broken_repo,
        {
            "docs/arena/assets/empty.png": b"",
            "docs/arena/WALKTHROUGH.md": "\n".join(
                [
                    f"{H} Walkthrough",
                    "[missing file](ui/nonexistent.js)",
                    f"[bad slug](README.md{H}does-not-exist)",
                    "![missing img](assets/no_such.png)",
                    '<img src="assets/empty.png" alt="zero">',
                    "[escape](../../../../etc/hosts)",
                ]
            )
            + "\n",
        },
    )
    res_bad = arena_hygiene.check_arena_markdown_links(broken_repo)
    assert res_bad.status == "FAIL"
    assert any("ui/nonexistent.js" in d for d in res_bad.details), res_bad.details
    assert any("does-not-exist" in d for d in res_bad.details), res_bad.details
    assert any("no_such.png" in d for d in res_bad.details), res_bad.details
    assert any("empty.png" in d and "0 bytes" in d for d in res_bad.details), res_bad.details
    assert any("outside repository root" in d for d in res_bad.details), res_bad.details


def test_ui_ascii_em_dashes_and_js_css_comments(arena_tmp: Path) -> None:
    bad_cases = (
        ("em_dash", {"docs/arena/ui/app.js": f'export const label = "A {EM_DASH} B";\n'}, "em dash"),
        ("en_dash", {"docs/arena/ui/app.js": f'export const rng = "6{EN_DASH}26";\n'}, "en dash"),
        ("non_ascii", {"docs/arena/ui/app.js": 'export const word = "caf\u00e9";\n'}, "U+00E9"),
        ("line_comm", {"docs/arena/ui/app.js": f"export const x = 1; {SLASH_SLASH} note\n"}, SLASH_SLASH),
        (
            "block_open",
            {"docs/arena/ui/arena.css": f"{SLASH_STAR} header {STAR_SLASH}\n.a {{ color: red; }}\n"},
            SLASH_STAR,
        ),
        ("block_close", {"docs/arena/ui/app.js": f'export const s = "{STAR_SLASH}";\n'}, STAR_SLASH),
        ("md_em_dash", {"docs/arena/README.md": f"{H} Arena {EM_DASH} Guide\n"}, "em dash"),
    )
    for case_id, overrides, expected in bad_cases:
        repo = _make_clean_arena_repo(arena_tmp / f"ui_{case_id}")
        _write_files(repo, overrides)
        res = arena_hygiene.check_arena_ui_hygiene(repo)
        assert res.status == "FAIL", f"{case_id} unexpectedly passed"
        assert any(expected in d for d in res.details), (case_id, res.details)


def test_pyodide_verbatim_canary_mirror_exempted(arena_tmp: Path) -> None:
    section_sign = chr(0x00A7)
    repo = _make_clean_arena_repo(arena_tmp / "pyodide_mirror_ok")
    _write_files(
        repo,
        {
            "docs/arena/py/canary/world.py": (
                "import os\n"
                "def _key():\n"
                f'    return os.environ.get("{TOK_WORLD_SECRET}")\n'
            ),
            "docs/arena/py/canary/rules.py": f'DOC = "Rule {section_sign}1.4 {EM_DASH} hard"\n',
        },
    )
    results = arena_hygiene.audit_arena_hygiene(repo)
    assert all(r.status == "PASS" for r in results), [r.details for r in results]

    leaked_repo = _make_clean_arena_repo(arena_tmp / "pyodide_mirror_leak")
    _write_files(
        leaked_repo,
        {
            "docs/arena/py/canary/world.py": f'{TOK_WORLD_SECRET} = "leaked_secret_value_99"\n',
        },
    )
    res_leak = arena_hygiene.check_arena_secrets(leaked_repo)
    assert res_leak.status == "FAIL"
    assert any("docs/arena/py/canary/world.py" in d for d in res_leak.details), res_leak.details


def test_size_budget_under_and_over_limit(
    arena_tmp: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = _make_clean_arena_repo(arena_tmp / "size_case")
    res_ok = arena_hygiene.check_arena_size_budget(repo)
    assert res_ok.status == "PASS"

    rc_tight = arena_hygiene.main(["--check", "--json", "--root", str(repo), "--max-bytes", "64"])
    payload_tight = json.loads(capsys.readouterr().out)
    assert rc_tight == 1
    assert payload_tight["passed"] is False
    by_name = {r["name"]: r for r in payload_tight["results"]}
    assert by_name[arena_hygiene.CHECK_SIZE_BUDGET]["status"] == "FAIL"

    real_size_fn = arena_hygiene._file_size_bytes

    def _mock_oversized(path: Path) -> int:
        if path.name == "badge.png":
            return 16 * 1024 * 1024
        return real_size_fn(path)

    monkeypatch.setattr(arena_hygiene, "_file_size_bytes", _mock_oversized)
    res_over_15mb = arena_hygiene.check_arena_size_budget(repo)
    assert res_over_15mb.status == "FAIL"
    assert "15.00 MB" in res_over_15mb.summary
    assert any("badge.png" in d for d in res_over_15mb.details)


def test_zero_protected_paths_modified_on_branch() -> None:
    for base_ref in ("origin/justSilas", "origin/fr8/canary/craft-arena"):
        check_ref = subprocess.run(
            ["git", "rev-parse", "--verify", f"{base_ref}^{{commit}}"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if check_ref.returncode != 0:
            continue
        mb = subprocess.run(
            ["git", "merge-base", base_ref, "HEAD"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
            timeout=10,
        ).stdout.strip()
        diff_proc = subprocess.run(
            ["git", "diff", "--name-only", mb, "--", *PROTECTED_PATHS],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
            timeout=10,
        )
        assert diff_proc.stdout.strip() == "", f"protected paths modified vs {base_ref}: {diff_proc.stdout}"
