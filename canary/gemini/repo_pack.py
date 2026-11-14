"""Whole-repo whitebox pack for the Gemini red-team swarm (long context, one prompt).

    python -m canary.gemini.repo_pack [--count-tokens --model gemini-3.8-flash] [--list]

Packs the judge-path source an attacker would read (canary/**, harbor/**, CONTRACT, EXPLOITS, README and the
integrity tests) into one text block with `=== FILE: <path> ===` headers. Secrets never enter the pack:
- path rules: no .env*, no data/ (judge worlds, SALT, runs), no .git/.venv/wt/.claude, no SALT/secret/token files,
  no canary/gemini (our lab tooling, not the env);
- content rules: a file is dropped if it contains the value of any secret env var (GEMINI_API_KEY, OPENAI_API_KEY,
  CANARY_WORLD_SECRET, CANARY_LEDGER_TOKEN, ...) or the bytes of data/worlds/judge/SALT, or a world dump with a
  `"mole": "eNN"` field.
`Pack.excluded` lists every skipped path with the reason, so tests and the report can show what was withheld.
"""
from __future__ import annotations

import argparse
import fnmatch
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

DEFAULT_INCLUDE = (
    "README.md", "docs/CONTRACT.md", "docs/EXPLOITS.md",
    "canary/**/*.py", "canary/**/*.md",
    "harbor/**/*",
    "tests/test_integrity*.py", "tests/integrity_helpers.py",
)
EXCLUDE_DIRS = {".git", ".venv", "venv", "node_modules", "__pycache__", ".pytest_cache", "data", "wt", ".claude",
                "judge", "runs", "results"}
EXCLUDE_PREFIXES = ("canary/gemini/",)   # lab tooling (this module, swarm, ledger): not part of the env
EXCLUDE_NAME_PATTERNS = (".env*", "SALT", "*secret*.txt", "*secret*.json", "*.secret", "*token*.txt", "*.key", "*.pem", "*.pyc", "*.png", "*.jpg",
                         "*.gif", "*.ico", "*.zip", "*.gz", "*.safetensors", "*.db", "*.sqlite")
SECRET_ENV_VARS = ("GEMINI_API_KEY", "GOOGLE_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "CANARY_WORLD_SECRET",
                   "CANARY_LEDGER_TOKEN", "CANARY_ADMIN_TOKEN", "XAI_API_KEY", "HF_TOKEN")
MOLE_FIELD = re.compile(r'"mole"\s*:\s*"e\d{2}"')
MAX_FILE_BYTES = 200_000


@dataclass
class Pack:
    text: str
    files: list[str] = field(default_factory=list)
    excluded: list[tuple[str, str]] = field(default_factory=list)

    @property
    def n_bytes(self) -> int:
        return len(self.text.encode())


def _secret_values(root: Path, environ=None) -> list[bytes]:
    environ = os.environ if environ is None else environ
    vals = [environ[k].strip().encode() for k in SECRET_ENV_VARS if len(environ.get(k, "").strip()) >= 8]
    for env_file in root.glob(".env*"):  # values in .env even when not exported
        try:
            for line in env_file.read_text(errors="ignore").splitlines():
                if "=" in line and not line.lstrip().startswith("#"):
                    k, v = line.split("=", 1)
                    v = v.strip().strip('"').strip("'")
                    if len(v) >= 8 and re.search(r"KEY|SECRET|TOKEN|PASS", k.upper()):
                        vals.append(v.encode())
        except OSError:
            pass
    salt = root / "data" / "worlds" / "judge" / "SALT"
    if salt.exists():
        b = salt.read_bytes().strip()
        if b:
            vals.append(b)
    return vals


def _path_reason(rel: str) -> str | None:
    parts = rel.split("/")
    if any(p in EXCLUDE_DIRS for p in parts[:-1]):
        return "excluded directory"
    if rel.startswith(EXCLUDE_PREFIXES):
        return "lab tooling"
    name = parts[-1]
    if any(fnmatch.fnmatch(name, pat) for pat in EXCLUDE_NAME_PATTERNS):
        return "secret or binary name"
    return None


def pack_repo(root: Path | str = REPO, include: tuple[str, ...] = DEFAULT_INCLUDE, environ=None) -> Pack:
    root = Path(root)
    secrets_ = _secret_values(root, environ)
    seen: set[str] = set()
    out, files, excluded = [], [], []
    for pat in include:
        for p in sorted(root.glob(pat)):
            if not p.is_file():
                continue
            rel = p.relative_to(root).as_posix()
            if rel in seen:
                continue
            seen.add(rel)
            why = _path_reason(rel)
            if why is None and p.stat().st_size > MAX_FILE_BYTES:
                why = "too large"
            data = b""
            if why is None:
                data = p.read_bytes()
                if b"\x00" in data[:4096]:
                    why = "binary"
                elif any(s in data for s in secrets_):
                    why = "contains a secret value"
                elif MOLE_FIELD.search(data.decode(errors="ignore")):
                    why = "world dump with a mole field"
            if why:
                excluded.append((rel, why))
                continue
            files.append(rel)
            out.append(f"=== FILE: {rel} ===\n{data.decode(errors='replace')}\n")
    header = (f"# Canary repository pack ({len(files)} files). Secrets, judge worlds, data/ and .env are withheld.\n\n")
    return Pack(header + "\n".join(out), files, excluded)


def count_tokens(text: str, model: str = "gemini-3.8-flash", run_id: str = "") -> int | None:
    """Exact token count from the Gemini API (ledgered as kind=count). None if no key / SDK."""
    import time

    from .ledger import record
    try:
        from .swarm import sdk_client
        c = sdk_client()
        t0 = time.time()
        r = c.models.count_tokens(model=model, contents=text)
        n = int(getattr(r, "total_tokens", 0) or 0)
        record("swarm", model, kind="count", latency_s=time.time() - t0, run_id=run_id, tokens={"in": 0, "out": 0},
               meta={"counted_tokens": n})
        return n
    except Exception:  # noqa: BLE001
        return None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--count-tokens", action="store_true")
    ap.add_argument("--model", default="gemini-3.8-flash")
    ap.add_argument("--list", action="store_true")
    a = ap.parse_args(argv)
    p = pack_repo()
    print(f"files={len(p.files)} bytes={p.n_bytes} excluded={len(p.excluded)} (~{p.n_bytes // 4} tokens est.)")
    if a.list:
        for f in p.files:
            print("  +", f)
        for f, why in p.excluded:
            print("  -", f, f"({why})")
    if a.count_tokens:
        print("tokens:", count_tokens(p.text, a.model))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
