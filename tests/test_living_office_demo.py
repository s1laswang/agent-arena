from __future__ import annotations

import ast
from contextlib import contextmanager
from dataclasses import replace
from html.parser import HTMLParser
import http.client
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import tokenize
from typing import Any
import urllib.request

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) in sys.path:
    sys.path.remove(str(ROOT))
sys.path.insert(0, str(ROOT))

BUILDER_SCRIPT = ROOT / "scripts" / "build_living_office_demo.py"
DEMO_HTML = ROOT / "docs" / "demo" / "living_office_v16.html"
CACHE_DIR = ROOT / "data" / "gemini_cache"
SOCIAL_DIR = ROOT / "canary" / "social"

EM_DASH = chr(0x2014)
EN_DASH = chr(0x2013)
SHA256_JSON_RE = re.compile(r"^[0-9a-f]{64}\.json$")
SECRET_RE = re.compile(r"AIza[0-9A-Za-z_\-]{20,}|sk-[0-9A-Za-z_\-]{16,}|ghp_[0-9A-Za-z]{20,}")
SCHEME_URL_RE = re.compile(r"(?:https?|wss?|ftp)://", re.I)
SCRIPT_SRC_RE = re.compile(r"<script\b[^>]*\bsrc\s*=", re.I)
LINK_HREF_RE = re.compile(r"<link\b[^>]*\bhref\s*=", re.I)
IFRAME_SRC_RE = re.compile(r"<iframe\b[^>]*\bsrc\s*=", re.I)
IMG_EXT_RE = re.compile(r"<img\b[^>]*\bsrc\s*=\s*['\"]?(?:https?:)?//", re.I)
CSS_IMPORT_RE = re.compile(r"@import\b", re.I)
CSS_URL_RE = re.compile(r"url\s*\(", re.I)
EMBEDDED_DATA_RE = re.compile(
    r"<script\b[^>]*\bid=['\"]living-office-data['\"][^>]*\btype=['\"]application/json['\"][^>]*>(.*?)</script>"
    r"|<script\b[^>]*\btype=['\"]application/json['\"][^>]*\bid=['\"]living-office-data['\"][^>]*>(.*?)</script>",
    re.I | re.S,
)
GATE_BANNER_RE = re.compile(
    r"<section\b[^>]*\bdata-testid=['\"]gate-b-banner['\"][^>]*>(.*?)</section>",
    re.I | re.S,
)
PRIOR_DAY_CALLBACK_RE = re.compile(r"\bday\s+([1-9]|1\d|2[01])\b", re.I)
EMP_ID_RE = re.compile(r"\be\d{2,3}\b", re.I)
MOLE_WORD_RE = re.compile(r"\bmole\b", re.I)
JS_NETWORK_APIS = (
    "fetch(",
    "XMLHttpRequest",
    "WebSocket(",
    "EventSource(",
    "navigator.sendBeacon",
)
FALSE_GATE_CLAIMS = (
    "gate b is met",
    "passed gate b",
    "passes gate b",
    "met gate b",
)

FORBIDDEN_MOLE_TRUTH_KEYS = frozenset({
    "mole",
    "mole_id",
    "is_mole",
    "true_mole",
    "_world",
    "world_secret",
})
FORBIDDEN_EMPLOYEE_KEYS = FORBIDDEN_MOLE_TRUTH_KEYS | frozenset({
    "decoy",
    "decoy_id",
    "is_decoy",
    "decoy_mood",
})
PROTECTED_PREFIXES = (
    "canary/env.py",
    "canary/rules.py",
    "canary/reproduce.py",
    "canary/solver/",
    "harbor/",
)


def _demo_artifacts_present() -> bool:
    if os.environ.get("CANARY_REQUIRE_LIVING_OFFICE_DEMO") == "1":
        return True
    return BUILDER_SCRIPT.exists() or DEMO_HTML.exists()


def _require_demo_branch() -> None:
    if not _demo_artifacts_present():
        pytest.skip("living office demo builder/html not on this standalone test branch yet")
    assert BUILDER_SCRIPT.is_file(), f"missing {BUILDER_SCRIPT}"
    assert DEMO_HTML.is_file(), f"missing {DEMO_HTML}"
    assert SOCIAL_DIR.is_dir(), f"missing {SOCIAL_DIR}"
    assert CACHE_DIR.is_dir(), f"missing {CACHE_DIR}"


def _load_builder_module() -> Any:
    assert BUILDER_SCRIPT.is_file(), f"missing {BUILDER_SCRIPT}"
    mod_name = "build_living_office_demo_under_test"
    spec = importlib.util.spec_from_file_location(mod_name, BUILDER_SCRIPT)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = mod
    spec.loader.exec_module(mod)
    return mod


@contextmanager
def offline_zero_api_guard(monkeypatch: pytest.MonkeyPatch, cache_dir: Path | None = None):
    def _deny_network(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("forbidden network or live API call during offline Living Office demo")

    monkeypatch.setenv("CANARY_OFFLINE", "1")
    monkeypatch.setenv("SLEEPER_OFFLINE", "1")
    monkeypatch.setenv("GEMINI_API_KEY", "")
    monkeypatch.setenv("GOOGLE_GENERATIVE_AI_API_KEY", "")
    monkeypatch.setenv("OPENAI_API_KEY", "")
    if cache_dir is not None:
        monkeypatch.setenv("CANARY_GEMINI_CACHE_DIR", str(cache_dir))

    monkeypatch.setattr(socket.socket, "connect", _deny_network)
    monkeypatch.setattr(socket.socket, "connect_ex", _deny_network)
    monkeypatch.setattr(socket, "create_connection", _deny_network)
    monkeypatch.setattr(urllib.request, "urlopen", _deny_network)
    monkeypatch.setattr(http.client.HTTPConnection, "request", _deny_network)
    monkeypatch.setattr(http.client.HTTPSConnection, "request", _deny_network)

    try:
        import canary.llm as canary_llm

        monkeypatch.setattr(canary_llm, "get_client", _deny_network)
    except ImportError:
        pass

    yield


def find_external_url_violations(html_text: str) -> list[str]:
    violations: list[str] = []
    if SCHEME_URL_RE.search(html_text):
        violations.append("external_scheme_url")
    if SCRIPT_SRC_RE.search(html_text):
        violations.append("script_src")
    if LINK_HREF_RE.search(html_text):
        violations.append("link_href")
    if IFRAME_SRC_RE.search(html_text):
        violations.append("iframe_src")
    if IMG_EXT_RE.search(html_text):
        violations.append("img_external_src")
    if CSS_IMPORT_RE.search(html_text):
        violations.append("css_import")
    if CSS_URL_RE.search(html_text):
        violations.append("css_url")
    return violations


def extract_embedded_payload(html_text: str) -> dict[str, Any]:
    match = EMBEDDED_DATA_RE.search(html_text)
    assert match is not None, "missing <script id='living-office-data' type='application/json'> block"
    raw = match.group(1) if match.group(1) is not None else match.group(2)
    assert raw is not None and raw.strip()
    parsed = json.loads(raw)
    assert isinstance(parsed, dict)
    return parsed


def validate_gate_b_negative_disclosure(html_text: str, payload: dict[str, Any]) -> None:
    banner_match = GATE_BANNER_RE.search(html_text)
    assert banner_match is not None, "missing <section data-testid='gate-b-banner'> disclosure banner"
    banner_plain = re.sub(r"<[^>]+>", " ", banner_match.group(1))
    banner_low = " ".join(banner_plain.lower().split())

    assert "off-by-default" in banner_low or "off by default" in banner_low
    assert "v1.6" in banner_low
    assert "gate b" in banner_low
    assert any(
        phrase in banner_low
        for phrase in ("did not pass", "not pass", "not met", "do not ship", "failed")
    )
    assert "v1.4" in banner_low
    assert "gemini-4-carbon" in banner_low
    assert "offline" in banner_low or "0 live api" in banner_low or "0 api" in banner_low
    for bad_claim in FALSE_GATE_CLAIMS:
        assert bad_claim not in banner_low, f"false Gate B claim in banner: {bad_claim}"

    prov = payload.get("provenance")
    assert isinstance(prov, dict), "payload missing provenance dict"
    assert prov.get("offline_only") is True
    assert int(prov.get("api_calls", -1)) == 0
    assert prov.get("gate_b_passed") is False
    assert prov.get("judged_benchmark_version") == "v1.4"
    assert prov.get("default_enabled") is False
    assert prov.get("model") == "gemini-4-carbon"
    assert prov.get("label") == "REAL"
    assert float(prov.get("cache_hit_rate", 0.0)) == pytest.approx(1.0)
    assert int(prov.get("cache_files_used", 0)) == 54


def _collect_forbidden_keys(
    obj: Any,
    path: str = "",
    forbidden: frozenset[str] = FORBIDDEN_MOLE_TRUTH_KEYS,
) -> list[str]:
    hits: list[str] = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            ks = str(k)
            cur = f"{path}.{ks}" if path else ks
            if ks.lower() in forbidden:
                hits.append(cur)
            hits.extend(_collect_forbidden_keys(v, cur, forbidden))
    elif isinstance(obj, list):
        for idx, item in enumerate(obj):
            hits.extend(_collect_forbidden_keys(item, f"{path}[{idx}]", forbidden))
    return hits


def validate_seed_multiday_and_public_isolation(seed_entry: dict[str, Any]) -> None:
    assert isinstance(seed_entry, dict)
    seed_num = int(seed_entry["seed"])
    assert seed_num in {0, 1, 2, 3, 5, 6}

    employees = seed_entry.get("employees")
    assert isinstance(employees, list) and len(employees) >= 10
    emp_truth_leaks = _collect_forbidden_keys(employees, "employees", FORBIDDEN_EMPLOYEE_KEYS)
    assert emp_truth_leaks == [], f"truth keys leaked in employees: {emp_truth_leaks}"

    days = seed_entry.get("days")
    assert isinstance(days, list) and len(days) == 21
    day_numbers = [int(d["day"]) for d in days]
    assert day_numbers in (list(range(1, 22)), list(range(21)))
    day_truth_leaks = _collect_forbidden_keys(days, "days", FORBIDDEN_MOLE_TRUTH_KEYS)
    assert day_truth_leaks == [], f"mole truth keys leaked in pre-reveal days: {day_truth_leaks}"

    grudge_ledger = seed_entry.get("grudge_ledger")
    rumour_chains = seed_entry.get("rumour_chains")
    gossip_carryover = seed_entry.get("gossip_carryover")
    assert grudge_ledger, f"empty grudge_ledger on seed {seed_num}"
    assert rumour_chains, f"empty rumour_chains on seed {seed_num}"
    assert gossip_carryover, f"empty gossip_carryover on seed {seed_num}"

    days_with_chatter = 0
    prior_day_callbacks = 0
    target_days: dict[str, set[int]] = {}

    for d_obj in days:
        d_num = int(d_obj["day"])
        day_blob = json.dumps(d_obj, sort_keys=True)
        social_items: list[Any] = []
        for candidate_key in ("social_events", "rumours", "gossip", "chat_feed", "messages", "events"):
            val = d_obj.get(candidate_key)
            if isinstance(val, list) and val:
                if candidate_key == "messages":
                    social_items.extend(
                        m for m in val if isinstance(m, dict) and (m.get("is_social") or "-s" in str(m.get("id", "")))
                    )
                else:
                    social_items.extend(val)
        if social_items:
            days_with_chatter += 1
        for item in social_items:
            txt = json.dumps(item, sort_keys=True)
            for m in PRIOR_DAY_CALLBACK_RE.finditer(txt):
                ref_day = int(m.group(1))
                if ref_day < d_num:
                    prior_day_callbacks += 1
            for eid in EMP_ID_RE.findall(txt):
                target_days.setdefault(eid.lower(), set()).add(d_num)
        for m in PRIOR_DAY_CALLBACK_RE.finditer(day_blob):
            if int(m.group(1)) < d_num:
                prior_day_callbacks += 1

    assert days_with_chatter >= 15, f"expected >=15 active social days on seed {seed_num}, got {days_with_chatter}"
    recurring_targets = [eid for eid, dset in target_days.items() if len(dset) >= 3]
    assert recurring_targets, f"no recurring multi-day employee mentions on seed {seed_num}"
    assert prior_day_callbacks >= 1 or len(recurring_targets) >= 2

    cache_audit = seed_entry.get("cache_audit")
    assert isinstance(cache_audit, dict), f"missing cache_audit on seed {seed_num}"
    if "prompts_hit" in cache_audit:
        assert int(cache_audit["prompts_hit"]) == 18
    if "prompts_total" in cache_audit:
        assert int(cache_audit["prompts_total"]) == 18
    if "prompts_fallback" in cache_audit:
        assert int(cache_audit["prompts_fallback"]) == 0
    if "hit_rate" in cache_audit:
        assert float(cache_audit["hit_rate"]) == pytest.approx(1.0)

    assert isinstance(seed_entry.get("solver_arm"), dict)
    assert isinstance(seed_entry.get("rumour_follower_arm"), dict)


def _assert_python_file_hygiene(py_path: Path) -> None:
    src = py_path.read_text(encoding="utf-8")
    assert EM_DASH not in src, f"em dash in {py_path}"
    assert EN_DASH not in src, f"en dash in {py_path}"
    assert not SECRET_RE.search(src), f"secret token in {py_path}"
    ast.parse(src, filename=str(py_path))
    tokens = list(tokenize.generate_tokens(io.StringIO(src).readline))
    comment_lines = [tok.start[0] for tok in tokens if tok.type == tokenize.COMMENT]
    assert comment_lines == [], f"code comments in {py_path} at lines {comment_lines}"


def test_validator_unit_guards_and_self_hygiene(monkeypatch: pytest.MonkeyPatch) -> None:
    _assert_python_file_hygiene(Path(__file__).resolve())

    clean_html = (
        "<!doctype html><html><body>"
        "<section class='gate-banner' data-testid='gate-b-banner'>"
        "OFF-BY-DEFAULT v1.6 PREVIEW: Did NOT pass Gate B gap gate; v1.4 remains judged benchmark; "
        "100% offline cached gemini-4-carbon chatter (0 live API calls), open via file://."
        "</section>"
        "<script id='living-office-data' type='application/json'>"
        + json.dumps(
            {
                "schema_version": "canary.living_office_demo.v16.v1",
                "provenance": {
                    "offline_only": True,
                    "api_calls": 0,
                    "gate_b_passed": False,
                    "judged_benchmark_version": "v1.4",
                    "default_enabled": False,
                    "cache_files_used": 54,
                    "cache_hit_rate": 1.0,
                    "model": "gemini-4-carbon",
                    "label": "REAL",
                },
                "seeds": [],
            }
        )
        + "</script></body></html>"
    )
    assert find_external_url_violations(clean_html) == []
    extracted = extract_embedded_payload(clean_html)
    validate_gate_b_negative_disclosure(clean_html, extracted)

    bad_scheme = "https:" + "//example.com/app.js"
    assert "external_scheme_url" in find_external_url_violations(f"<a href='{bad_scheme}'>x</a>")
    assert "script_src" in find_external_url_violations("<script src='bundle.js'></script>")
    assert "link_href" in find_external_url_violations("<link rel='stylesheet' href='a.css'>")
    assert "css_import" in find_external_url_violations("<style>@import 'a.css';</style>")
    assert "css_url" in find_external_url_violations("<style>.bg{background:url(a.png)}</style>")

    assert _collect_forbidden_keys({"employees": [{"id": "e01", "mole": True}]}) == ["employees[0].mole"]
    assert _collect_forbidden_keys({"employees": [{"id": "e01", "dept": "Eng"}]}) == []

    with offline_zero_api_guard(monkeypatch):
        with pytest.raises(AssertionError, match="forbidden network"):
            socket.create_connection(("127.0.0.1", 9), timeout=0.05)


def test_zero_protected_paths_modified_vs_justsilas() -> None:
    ref_check = subprocess.run(
        ["git", "rev-parse", "--verify", "origin/justSilas"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    if ref_check.returncode != 0:
        return
    diff_proc = subprocess.run(
        ["git", "diff", "--name-only", "origin/justSilas...HEAD"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    changed = [ln.strip() for ln in diff_proc.stdout.splitlines() if ln.strip()]
    protected_touched = [
        p for p in changed if any(p == pref or p.startswith(pref) for pref in PROTECTED_PREFIXES)
    ]
    assert protected_touched == [], f"protected paths modified: {protected_touched}"


def test_committed_54_real_gemini_cache_files_and_provenance() -> None:
    _require_demo_branch()
    files = sorted(CACHE_DIR.glob("*.json"))
    assert len(files) >= 54
    for fp in files:
        assert SHA256_JSON_RE.match(fp.name), f"non-sha256 cache filename: {fp.name}"
        raw = fp.read_text(encoding="utf-8")
        assert not SECRET_RE.search(raw), f"secret marker in {fp.name}"
        entry = json.loads(raw)
        assert isinstance(entry, dict)
        assert {"provenance", "text", "tool_calls"}.issubset(entry.keys())
        prov = entry["provenance"]
        assert prov.get("label") == "REAL"
        assert prov.get("model") == "gemini-4-carbon"
        inner = json.loads(entry["text"])
        bodies = inner.get("bodies")
        assert isinstance(bodies, list) and bodies
        assert all(isinstance(b, str) and b.strip() for b in bodies)


def test_builder_zero_api_calls_100pct_cache_hit_and_solver_invariance(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _require_demo_branch()
    _assert_python_file_hygiene(BUILDER_SCRIPT)
    builder = _load_builder_module()

    assert hasattr(builder, "DEFAULT_SEEDS")
    default_seeds = tuple(int(s) for s in builder.DEFAULT_SEEDS)
    assert len(default_seeds) == 3
    assert set(default_seeds).issubset({0, 1, 2, 3, 5, 6})

    import canary.text.llm_cache as llm_cache

    orig_cached_chat = llm_cache.cached_chat
    cache_calls: list[dict[str, Any]] = []
    unique_cache_keys: set[str] = set()
    cache_misses: list[str] = []

    def _counting_cached_chat(
        cache_dir_arg: Any,
        client: Any,
        model: str,
        system: str,
        user: str,
        response_schema: dict[str, Any] | None = None,
        label: str = "REAL",
    ) -> dict[str, Any]:
        key = llm_cache.cache_key(model, system, [{"role": "user", "content": user}], None, 0, None)
        try:
            res = orig_cached_chat(
                cache_dir_arg,
                client,
                model,
                system,
                user,
                response_schema=response_schema,
                label=label,
            )
        except Exception as exc:
            cache_misses.append(f"{key[:12]}:{exc}")
            raise
        assert res.get("provenance", {}).get("label") == "REAL"
        assert res.get("provenance", {}).get("model") == "gemini-4-carbon"
        cache_calls.append({"model": model, "label": label, "key": key})
        unique_cache_keys.add(key)
        return res

    monkeypatch.setattr(llm_cache, "cached_chat", _counting_cached_chat)
    try:
        import canary.social.gemini_chatter as gemini_chatter

        monkeypatch.setattr(gemini_chatter, "cached_chat", _counting_cached_chat)
    except ImportError:
        pass

    with offline_zero_api_guard(monkeypatch, CACHE_DIR):
        payload = builder.build_living_office_payload(seeds=default_seeds, cache_dir=CACHE_DIR)

    assert isinstance(payload, dict)
    assert payload.get("schema_version") == "canary.living_office_demo.v16.v1"
    assert cache_misses == []
    assert len(cache_calls) >= 54
    assert len(unique_cache_keys) == 54

    seeds_data = payload.get("seeds")
    assert isinstance(seeds_data, list) and len(seeds_data) == 3
    assert [int(s["seed"]) for s in seeds_data] == list(default_seeds)

    from canary.env import Env
    from canary.eval import run_episode
    from canary.solver.policy import SolverPolicy
    from canary.text.template import TemplateProvider

    for seed_entry in seeds_data:
        validate_seed_multiday_and_public_isolation(seed_entry)
        s_num = int(seed_entry["seed"])
        ref_ep = run_episode(Env("hard", seed=s_num, text_provider=TemplateProvider()), SolverPolicy("hard"))
        solver_arm = seed_entry["solver_arm"]
        if "score" in solver_arm:
            assert float(solver_arm["score"]) == pytest.approx(float(ref_ep.score))
        if "correct" in solver_arm:
            assert bool(solver_arm["correct"]) is bool(ref_ep.correct)

    out_html = tmp_path / "living_office_v16.html"
    out_json = tmp_path / "living_office_v16.json"
    with offline_zero_api_guard(monkeypatch, CACHE_DIR):
        rendered = builder.render_living_office_html(payload, out_path=out_html)
    assert out_html.is_file()
    assert rendered == out_html.read_text(encoding="utf-8")
    assert find_external_url_violations(rendered) == []
    assert EM_DASH not in rendered and EN_DASH not in rendered
    validate_gate_b_negative_disclosure(rendered, extract_embedded_payload(rendered))

    with offline_zero_api_guard(monkeypatch, CACHE_DIR):
        rc_build = builder.main(["--out", str(out_html), "--json-out", str(out_json)])
        assert rc_build == 0
        assert out_json.is_file()
        rc_check_ok = builder.main(["--out", str(out_html), "--check"])
        assert rc_check_ok == 0

        out_html.write_text(out_html.read_text(encoding="utf-8") + "\n<div>tampered</div>\n", encoding="utf-8")
        try:
            rc_tampered = builder.main(["--out", str(out_html), "--check"])
        except SystemExit as exc:
            rc_tampered = int(exc.code) if isinstance(exc.code, int) else 1
        assert rc_tampered != 0


def test_committed_living_office_html_self_contained_and_check_clean(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _require_demo_branch()
    html_text = DEMO_HTML.read_text(encoding="utf-8")
    assert "<!doctype html>" in html_text.lower()
    assert EM_DASH not in html_text
    assert EN_DASH not in html_text
    assert not SECRET_RE.search(html_text)
    assert find_external_url_violations(html_text) == []

    payload = extract_embedded_payload(html_text)
    assert payload.get("schema_version") == "canary.living_office_demo.v16.v1"
    validate_gate_b_negative_disclosure(html_text, payload)

    seeds_data = payload.get("seeds")
    assert isinstance(seeds_data, list) and len(seeds_data) == 3
    for seed_entry in seeds_data:
        validate_seed_multiday_and_public_isolation(seed_entry)

    builder = _load_builder_module()
    with offline_zero_api_guard(monkeypatch, CACHE_DIR):
        rc = builder.main(["--check"])
    assert rc == 0


class _SelfContainedHTMLAuditor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self.has_doctype = False
        self.external_attrs: list[tuple[str, str, str]] = []
        self.gate_banners: list[dict[str, Any]] = []
        self.json_scripts: dict[str, str] = {}
        self.inline_scripts: list[str] = []
        self.inline_styles: list[str] = []
        self.html_comments: list[str] = []
        self._active_tag: str | None = None
        self._active_attrs: dict[str, str | None] = {}
        self._buf: list[str] = []
        self._banner_depth = 0
        self._banner_buf: list[str] = []
        self._banner_attrs: dict[str, str | None] = {}

    def handle_decl(self, decl: str) -> None:
        if decl.strip().lower().startswith("doctype html"):
            self.has_doctype = True

    def handle_comment(self, data: str) -> None:
        self.html_comments.append(data)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        t = tag.lower()
        attr_map = {k.lower(): v for k, v in attrs}
        for attr_name in ("src", "href", "action", "poster", "data", "srcset"):
            val = attr_map.get(attr_name)
            if val is None:
                continue
            sval = val.strip()
            if t in ("script", "link"):
                self.external_attrs.append((t, attr_name, sval))
            elif sval.startswith(("http:", "https:", "//", "ws:", "wss:", "ftp:")):
                self.external_attrs.append((t, attr_name, sval))

        if attr_map.get("data-testid") == "gate-b-banner" and self._banner_depth == 0:
            self._banner_depth = 1
            self._banner_buf = []
            self._banner_attrs = dict(attr_map)
        elif self._banner_depth > 0 and t not in ("br", "hr", "img", "input", "meta", "link"):
            self._banner_depth += 1

        if t in ("script", "style"):
            self._active_tag = t
            self._active_attrs = attr_map
            self._buf = []

    def handle_endtag(self, tag: str) -> None:
        t = tag.lower()
        if self._active_tag == t:
            content = "".join(self._buf)
            if t == "script":
                sid = self._active_attrs.get("id") or ""
                stype = (self._active_attrs.get("type") or "").strip().lower()
                if stype == "application/json" or sid == "living-office-data":
                    self.json_scripts[sid] = content
                else:
                    self.inline_scripts.append(content)
            elif t == "style":
                self.inline_styles.append(content)
            self._active_tag = None
            self._active_attrs = {}
            self._buf = []

        if self._banner_depth > 0:
            self._banner_depth -= 1
            if self._banner_depth == 0:
                self.gate_banners.append({
                    "attrs": self._banner_attrs,
                    "text": " ".join("".join(self._banner_buf).split()),
                })
                self._banner_buf = []
                self._banner_attrs = {}

    def handle_data(self, data: str) -> None:
        if self._active_tag is not None:
            self._buf.append(data)
        if self._banner_depth > 0:
            self._banner_buf.append(data)


def audit_html_dom_and_js_isolation(html_text: str) -> list[str]:
    auditor = _SelfContainedHTMLAuditor()
    auditor.feed(html_text)
    auditor.close()
    issues: list[str] = []
    if not auditor.has_doctype:
        issues.append("missing_doctype")
    if auditor.external_attrs:
        issues.append("external_dom_attrs")
    if auditor.html_comments:
        issues.append("html_comments")
    for css in auditor.inline_styles:
        low_css = css.lower()
        if "@import" in low_css or "url(" in low_css:
            issues.append("external_css_ref")
    for js in auditor.inline_scripts:
        for net_api in JS_NETWORK_APIS:
            if net_api in js:
                issues.append(f"js_network_api:{net_api}")
    if len(auditor.gate_banners) != 1:
        issues.append("missing_or_duplicate_gate_banner")
    else:
        b = auditor.gate_banners[0]
        if "hidden" in b["attrs"]:
            issues.append("hidden_gate_banner_attr")
        b_style = (b["attrs"].get("style") or "").replace(" ", "").lower()
        if "display:none" in b_style or "visibility:hidden" in b_style:
            issues.append("hidden_gate_banner_style")
        b_low = b["text"].lower()
        for bad_claim in FALSE_GATE_CLAIMS:
            if bad_claim in b_low:
                issues.append(f"false_gate_claim:{bad_claim}")
    banner_pos = html_text.find('data-testid="gate-b-banner"')
    if banner_pos < 0:
        banner_pos = html_text.find("data-testid='gate-b-banner'")
    main_pos = html_text.lower().find("<main")
    if banner_pos > 0 and main_pos > 0 and banner_pos > main_pos:
        issues.append("banner_after_main")
    if "living-office-data" not in auditor.json_scripts:
        issues.append("missing_living_office_data_script")
    return issues


def find_future_day_callback_violations(days: list[dict[str, Any]]) -> list[str]:
    problems: list[str] = []
    for d_rec in days:
        d_num = int(d_rec["day"])
        for key_name in ("social_events", "rumours", "gossip", "chat_feed", "messages", "events"):
            seq = d_rec.get(key_name)
            if not isinstance(seq, list):
                continue
            for idx, item in enumerate(seq):
                if not isinstance(item, dict):
                    continue
                if key_name == "messages" and not (
                    item.get("is_social") or "-s" in str(item.get("id", ""))
                ):
                    continue
                text_blob = f"{item.get('subject', '')}\n{item.get('body', '')}\n{item.get('text', '')}"
                for m in PRIOR_DAY_CALLBACK_RE.finditer(text_blob):
                    ref_d = int(m.group(1))
                    if ref_d > d_num:
                        problems.append(f"day_{d_num}_{key_name}[{idx}]_refs_future_day_{ref_d}")
                for carry_key in ("carried_from_day", "origin_day", "from_day", "since_day"):
                    c_val = item.get(carry_key)
                    if isinstance(c_val, int) and (c_val < 1 or c_val > d_num):
                        problems.append(f"day_{d_num}_{key_name}[{idx}]_bad_{carry_key}_{c_val}")
    return problems


def test_dom_auditor_and_causal_carryover_unit_guards() -> None:
    good_html = (
        "<!doctype html><html><head><style>body{margin:0}</style></head><body>"
        "<section class='gate-banner' data-testid='gate-b-banner'>"
        "OFF-BY-DEFAULT v1.6 PREVIEW: Did NOT pass Gate B gap gate; v1.4 remains judged benchmark; "
        "100% offline cached gemini-4-carbon chatter (0 live API calls)."
        "</section>"
        "<main><div id='app'></div></main>"
        "<script id='living-office-data' type='application/json'>{\"seeds\":[]}</script>"
        "<script>const x = document.getElementById('living-office-data').textContent;</script>"
        "</body></html>"
    )
    assert audit_html_dom_and_js_isolation(good_html) == []

    hidden_html = good_html.replace(
        "data-testid='gate-b-banner'",
        "data-testid='gate-b-banner' style='display: none'",
    )
    assert "hidden_gate_banner_style" in audit_html_dom_and_js_isolation(hidden_html)

    fetch_html = good_html.replace("const x =", "fetch('/api'); const x =")
    assert "js_network_api:fetch(" in audit_html_dom_and_js_isolation(fetch_html)

    comment_open = "<" + "!--"
    comment_close = "--" + ">"
    commented_html = good_html.replace("<main>", f"{comment_open} note {comment_close}<main>")
    assert "html_comments" in audit_html_dom_and_js_isolation(commented_html)

    false_claim_html = good_html.replace("Did NOT pass Gate B", "Passed Gate B")
    assert any(
        x.startswith("false_gate_claim:") for x in audit_html_dom_and_js_isolation(false_claim_html)
    )

    clean_days = [
        {"day": 1, "social_events": [{"body": "Initial doc note on e01."}]},
        {"day": 4, "social_events": [{"body": "Following Day 1 meeting on e01.", "carried_from_day": 1}]},
    ]
    assert find_future_day_callback_violations(clean_days) == []

    bad_days = [
        {"day": 3, "social_events": [{"body": "Following Day 9 leak review on e01."}]},
        {"day": 4, "rumours": [{"text": "Carry check", "carried_from_day": 7}]},
    ]
    bad_hits = find_future_day_callback_violations(bad_days)
    assert len(bad_hits) == 2


def test_sha256_prompt_key_recomputation_canary_invariance_and_offline_miss(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _require_demo_branch()
    from canary.env import Env
    from canary.social import make_v16_provider
    from canary.social.gemini_chatter import SOCIAL_SCHEMA, SOCIAL_SYSTEM, build_social_prompt
    from canary.text.llm_cache import OfflineCacheMiss, cache_key, cached_chat

    builder = _load_builder_module()
    seeds = [int(s) for s in builder.DEFAULT_SEEDS]
    files = sorted(CACHE_DIR.glob("*.json"))
    by_stem = {fp.stem: fp for fp in files}

    for fp in files:
        inner = json.loads(json.loads(fp.read_text(encoding="utf-8"))["text"])
        for body_txt in inner["bodies"]:
            assert MOLE_WORD_RE.search(body_txt) is None, f"mole word leaked in {fp.name}"

    with offline_zero_api_guard(monkeypatch, CACHE_DIR):
        recomputed_keys: set[str] = set()
        for seed in seeds:
            prov_tpl = make_v16_provider("v5_full9_cocktail", mode="template")
            env = Env("hard", seed=seed, text_provider=prov_tpl)
            seed_day_hits = 0
            for day in range(1, 22):
                facts = env._facts(day)
                msgs_tpl = prov_tpl.day_messages(facts)
                social_tpl = [m for m in msgs_tpl if "-s" in str(m.get("id", ""))]
                if social_tpl:
                    st = prov_tpl.episode_state(facts.tier, facts.seed)
                    assert st is not None
                    raw_evs = st.events_by_day[day]
                    prompt_items = []
                    for idx, m in enumerate(social_tpl):
                        item = dict(m)
                        if idx < len(raw_evs):
                            item["target"] = str(raw_evs[idx]["target"])
                            item["meta"] = {
                                "bias": str(raw_evs[idx]["bias"]),
                                "target": str(raw_evs[idx]["target"]),
                            }
                        prompt_items.append(item)
                    prompt_clean = build_social_prompt(facts, prompt_items)
                    prompt_canary = build_social_prompt(
                        replace(
                            facts,
                            docs=tuple(facts.docs)
                            + (
                                {
                                    "doc_id": f"c{day}-probe",
                                    "title": "Planted Canary Variant",
                                    "day": day,
                                    "recipients": [facts.employees[0].id],
                                },
                            ),
                        ),
                        prompt_items,
                    )
                    assert prompt_clean == prompt_canary
                    key = cache_key("gemini-4-carbon", SOCIAL_SYSTEM, [{"role": "user", "content": prompt_clean}])
                    assert key in by_stem, f"missing committed cache file for seed={seed} day={day}"
                    recomputed_keys.add(key)
                    seed_day_hits += 1
                if day < 21:
                    assert env.call("advance_day", {}).ok
            assert seed_day_hits == 18
        assert len(recomputed_keys) == 54

    empty_cache = tmp_path / "empty_cache"
    empty_cache.mkdir()
    with offline_zero_api_guard(monkeypatch, empty_cache):
        with pytest.raises(OfflineCacheMiss):
            cached_chat(
                empty_cache,
                None,
                "gemini-4-carbon",
                SOCIAL_SYSTEM,
                "unseen-living-office-offline-miss-check",
                response_schema=SOCIAL_SCHEMA,
                label="REAL",
            )


def test_multiday_causality_grudge_persistence_decoy_scrub_and_arm_divergence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _require_demo_branch()
    from canary.env import Env
    from canary.social.biases import ANGER_WORDS, DECOY_VOCAB
    from canary.text.template import TemplateProvider

    builder = _load_builder_module()
    with offline_zero_api_guard(monkeypatch, CACHE_DIR):
        payload = builder.build_living_office_payload(cache_dir=CACHE_DIR)

    for seed_entry in payload["seeds"]:
        seed = int(seed_entry["seed"])
        days = seed_entry["days"]
        assert find_future_day_callback_violations(days) == []

        emp_ids = {str(e["id"]) for e in seed_entry["employees"]}
        decoy_id = Env("hard", seed=seed, text_provider=TemplateProvider())._facts(1).decoy
        assert decoy_id in emp_ids

        seen_targets: set[str] = set()
        grudge_days: set[int] = set()
        strict_prior_callbacks = 0

        for d_rec in days:
            d_num = int(d_rec["day"])
            social_evs = d_rec.get("social_events") or d_rec.get("rumours") or []
            for ev in social_evs:
                if not isinstance(ev, dict):
                    continue
                sender = str(ev.get("sender") or ev.get("from") or "")
                target = str(ev.get("target") or ev.get("about") or ev.get("to") or "")
                bias = str(ev.get("bias") or ev.get("bias_type") or "")
                text_blob = f"{ev.get('subject', '')}\n{ev.get('body', '')}\n{ev.get('text', '')}"
                if sender:
                    assert sender in emp_ids and sender != decoy_id
                if target:
                    assert target in emp_ids and target != decoy_id
                    if d_num >= 3:
                        assert target in seen_targets, f"seed {seed} day {d_num} target {target} not seeded earlier"
                    seen_targets.add(target)
                if bias == "grudge":
                    grudge_days.add(d_num)
                for m in PRIOR_DAY_CALLBACK_RE.finditer(text_blob):
                    if int(m.group(1)) < d_num:
                        strict_prior_callbacks += 1

            msgs = d_rec.get("messages") or d_rec.get("chat_feed") or []
            for msg in msgs:
                if not isinstance(msg, dict):
                    continue
                m_sender = str(msg.get("sender") or msg.get("from") or "")
                m_low = f"{msg.get('subject', '')}\n{msg.get('body', '')}\n{msg.get('text', '')}".lower()
                if m_sender and m_sender != decoy_id:
                    assert not any(aw in m_low for aw in ANGER_WORDS)
                if bool(msg.get("is_social")) or "-s" in str(msg.get("id", "")):
                    assert m_sender != decoy_id
                    assert not any(dv in m_low for dv in DECOY_VOCAB)
                    for m in PRIOR_DAY_CALLBACK_RE.finditer(m_low):
                        if int(m.group(1)) < d_num:
                            strict_prior_callbacks += 1

        assert len(grudge_days) >= 4 or len(seed_entry["grudge_ledger"]) >= 2
        assert strict_prior_callbacks >= 10

        solver_arm = seed_entry["solver_arm"]
        rf_arm = seed_entry["rumour_follower_arm"]
        if "accused" in solver_arm and "accused" in rf_arm:
            assert rf_arm["accused"] != solver_arm["accused"]
        if "score" in solver_arm and "score" in rf_arm:
            assert float(rf_arm["score"]) < float(solver_arm["score"])


def test_keyless_subprocess_cli_dom_audit_and_ast_world_isolation(
    tmp_path: Path,
) -> None:
    _require_demo_branch()
    from canary import rules

    assert rules.TIERS_VERSION == "v1.4"
    assert audit_html_dom_and_js_isolation(DEMO_HTML.read_text(encoding="utf-8")) == []

    tree = ast.parse(BUILDER_SCRIPT.read_text(encoding="utf-8"), filename=str(BUILDER_SCRIPT))
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            assert node.attr not in ("_world", "mole"), f"forbidden private attr {node.attr}"
        elif isinstance(node, ast.ImportFrom) and node.module:
            assert "world" not in node.module, f"forbidden world import {node.module}"

    out_html = tmp_path / "subproc_living_office_v16.html"
    out_json = tmp_path / "subproc_living_office_v16.json"
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT)
    env["CANARY_OFFLINE"] = "1"
    env["SLEEPER_OFFLINE"] = "1"
    env["CANARY_GEMINI_CACHE_DIR"] = str(CACHE_DIR)
    for key_name in (
        "GOOGLE_GENERATIVE_AI_API_KEY",
        "GEMINI_API_KEY",
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "OPENROUTER_API_KEY",
    ):
        env[key_name] = ""

    proc_build = subprocess.run(
        [
            sys.executable,
            str(BUILDER_SCRIPT),
            "--out",
            str(out_html),
            "--json-out",
            str(out_json),
        ],
        cwd=str(ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=True,
    )
    assert proc_build.returncode == 0
    assert out_html.is_file() and out_json.is_file()
    assert out_html.read_text(encoding="utf-8") == DEMO_HTML.read_text(encoding="utf-8")

    proc_check = subprocess.run(
        [sys.executable, str(BUILDER_SCRIPT), "--check"],
        cwd=str(ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=True,
    )
    assert proc_check.returncode == 0

