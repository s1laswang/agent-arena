from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

CHECK_COMMITTED_RUNS = "Committed Run Meta & Episode Provenance"
CHECK_RESULTS_ARTIFACTS = "Results Artifact Provenance"
CHECK_DOC_SHAS = "Doc Commit-SHA Reference Check"

CHECK_NAMES: tuple[str, ...] = (
    CHECK_COMMITTED_RUNS,
    CHECK_RESULTS_ARTIFACTS,
    CHECK_DOC_SHAS,
)

TARGET_DOC_RELS: tuple[str, ...] = (
    "README.md",
    "JUDGE_QUICKSTART.md",
    "docs/JUDGE-WALKTHROUGH.md",
    "docs/PEER-REVIEW-QA.md",
    "docs/REPRODUCIBILITY.md",
    "docs/SUBMISSION.md",
    "VERDA.md",
    "results/fresh_clone/README.md",
    "docs/reports/CEO.md",
    "docs/reports/gap.md",
    "docs/reports/integrity.md",
)

EXPECTED_SOLVER_RANGE_AGENTS: tuple[str, ...] = ("solver", "guess_day1")
EXPECTED_TIERS: tuple[str, ...] = ("easy", "medium", "hard")
LEGACY_TIERS_VERSION = "v1.2"
CURRENT_TIERS_VERSION = "v1.4"

CANONICAL_FROZEN_TIER_HASHES: frozenset[str] = frozenset(
    {
        "a8f99c2537c91d72",
        "8df71cf570bb48bc",
        "eb77b13554f366aa",
        "6ebdb2489b082c77",
    }
)
DOCUMENTED_VERDA_INSTANCE_IDS: frozenset[str] = frozenset(
    {
        "dbd083ca",
        "f4378173",
        "3bb74f5a",
        "ac58df04",
        "68bbe201",
        "18acfa5d",
        "714d8144",
        "924e81d8",
        "e9ea8b2e",
    }
)

HEX_SHA_RX = re.compile(r"^[0-9a-f]{7,40}$", re.IGNORECASE)
HEX7_FAST_RX = re.compile(r"[0-9a-fA-F]{7}")
VERSION_RX = re.compile(r"^v\d+(?:\.\d+)+$")
PATH_VERSION_SEG_RX = re.compile(r"^v\d+(?:\.\d+)*$")
FENCE_OPEN_RX = re.compile(r"^\s*(?:>\s*)*(`{3,}|~{3,})")
TABLE_SEP_CELL_RX = re.compile(r"^:?-{2,}:?$")

JUDGE_TABLE_HEADER_GIT_RX = re.compile(r"^-\s+git:\s*`([^`\n]+)`", re.MULTILINE)
JUDGE_TABLE_HEADER_FP_RX = re.compile(
    r"^-\s+judge-world secret:.*sha256 fingerprint\s+`([0-9a-f]{8,64})`",
    re.MULTILINE,
)
JUDGE_TABLE_REPORTED_NOTE_RX = re.compile(
    r"replayed,\s+(?:NON-)?judge seeds,\s+\d+\s+seeds,\s+git\s+([^()]+)\(([^()]+)\)"
)
SOLVER_RANGE_FILENAME_RX = re.compile(r"^([A-Za-z0-9_]+)_(easy|medium|hard)_judge40\.json$")
HARBOR_REHEARSAL_HEADING_RX = re.compile(
    r"Judge rehearsal on tag `([^`\n]+)` \(([0-9a-f]{7,40})\):\s*Harbor\s+([0-9][0-9A-Za-z._-]*)",
    re.IGNORECASE,
)
HARBOR_REHEARSAL_COMMIT_NOTE_RX = re.compile(
    r"\(commit\s+`?([^`\s)]+)`?\)",
    re.IGNORECASE,
)
DRY_REHEARSAL_CODE_SHA_RX = re.compile(
    r"^\s*-\s+\*\*Code:\*\*\s*`([0-9a-f]{7,40})`",
    re.MULTILINE | re.IGNORECASE,
)
PAIRED_LABEL_COMMIT_RX = re.compile(
    r"(?:\bat\s+|\bpre-)([0-9a-f]{7,40})\b",
    re.IGNORECASE,
)
REDTEAM_GENERATED_RX = re.compile(
    r"^Generated\s+(\S+)\s+at\s+`([^`\n]+)`\.",
    re.MULTILINE,
)
REDTEAM_HEADLINE_ATTACKERS_RX = re.compile(
    r"\*\*(\d+)\s+Gemini\s+attackers\*\*"
)
REDTEAM_EXPLOITS_LINE_RX = re.compile(
    r"^-\s+Verified exploits:\s*\*\*(\d+)\*\*.*invariant violations:\s*(\d+)\b",
    re.MULTILINE,
)
REDTEAM_COMMIT_SPLIT_HEADING_RX = re.compile(
    r"Combined count split by commit \(SHA\)",
    re.IGNORECASE,
)

URL_SPAN_RX = re.compile(r"https?://[^\s)\]>]+", re.IGNORECASE)
UUID_SPAN_RX = re.compile(
    r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b",
    re.IGNORECASE,
)
DATE_OR_ROUND_DEC_RX = re.compile(r"^(?:20\d{6}|\d0{5,})$")

LOCAL_NON_COMMIT_PREFIX_RX = re.compile(
    r"(?:sha-?256"
    r"|(?<!canary\s)(?<!5%\s)(?<![0-9]%-)\bfingerprints?\b"
    r"|code[_\s]+fingerprints?"
    r"|\bsecret\s+[`\"'(\[]*$"
    r"|canary_world_secret"
    r"|(?:frozen\s+)?tier[s_\s-]+hash(?:es)?"
    r"|\bpins?\s+hash\b"
    r"|\bhash\s+[`\"'(\[]*$"
    r"|\btiers_version\b|\btiers_v\d+\b"
    r"|\bverda\s+(?:gpus?|instances?|boxes|spot|on-demand)\b|\bfr8[/\s]+gpus?\b|\bgpus?\b|\binstances?\b"
    r"|\b(?:a100|h100|v100)(?:-[0-9a-z]+)?(?:\s+(?:spot|on-demand))?\b"
    r"|default_rng)",
    re.IGNORECASE,
)

EXPLICIT_DOC_COMMIT_RXES: tuple[re.Pattern[str], ...] = (
    re.compile(
        r"\b(?:commit|commits|committed|git|fix|fixed|merged(?:\s+as)?|verified|pre-registered(?:\s+at)?|revision|rev)\s*:?\s*(?:\*\*|`)?([0-9a-f]{7,40})(?:\*\*|`)?(?![0-9a-fA-Z_])",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bcommitted\b[^.\n;|]{0,55}?\bin\s+(?:\*\*|`)?([0-9a-f]{7,40})(?:\*\*|`)?(?![0-9a-fA-Z_])",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:played|cloned|built|tested|verified|recorded|ran)\s+at\s+(?:\*\*|`)?([0-9a-f]{7,40})(?:\*\*|`)?(?![0-9a-fA-Z_])",
        re.IGNORECASE,
    ),
    re.compile(r"\bat\s+`([0-9a-f]{7,40})`"),
    re.compile(
        r"\b(?:rebased\s+onto|cherry-picked)\s+(?:\*\*|`)?([0-9a-f]{7,40})(?:\*\*|`)?(?![0-9a-fA-Z_])",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:@|\s@\s)\s*(?:\*\*|`)?([0-9a-f]{7,40})(?:\*\*|`)?(?![0-9a-fA-Z_])"
    ),
    re.compile(
        r"\bon\s+(?:\*\*|`)?([0-9a-f]{7,40})(?:\*\*|`)?(?![0-9a-fA-Z_-])",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:`?(?:justSilas(?:-[A-Za-z0-9_.-]+)?|afterquery-(?:final|submit(?:-2)?)|fr8/[A-Za-z0-9_./-]+|ENV)`?)\s+(?:\*\*|`)?([0-9a-f]{7,40})(?:\*\*|`)?(?![0-9a-fA-Z_])"
    ),
    re.compile(
        r"\bjustSilas\s+[0-9a-f]{7,40}\s*\+\s*(?:\*\*|`)?([0-9a-f]{7,40})(?:\*\*|`)?(?![0-9a-fA-Z_])"
    ),
    re.compile(r"(?:justSilas|afterquery_(?:final|submit(?:_2)?))_([0-9a-f]{7,40})(?![0-9a-fA-Za-z])"),
)

BACKTICK_HEX_RX = re.compile(r"`([0-9a-f]{7,40})`")
PAREN_SPAN_RX = re.compile(r"\(([^()\n]+)\)")
PAREN_HEX_TOKEN_RX = re.compile(r"(?:^|,)\s*([0-9a-f]{7,40})(?=\s*(?:,|$))")

EXTERNAL_BRANCH_CONTEXT_RX = re.compile(
    r"(?:\bjustSilas-[A-Za-z0-9_.-]+\b"
    r"|\bs\d+-[A-Za-z0-9_.-]+\b"
    r"|\bgemini-(?:pr\d+|scale/[A-Za-z0-9_.-]+|track)\b"
    r"|\borigin/(?!justSilas\b)[A-Za-z0-9_./-]+\b"
    r"|\bon\s+branch\s+(?!justSilas\b)(?!afterquery-(?:final|submit(?:-2)?)\b)`?[A-Za-z0-9_./-]+`?"
    r"|\bnot\s+(?:shipped|merged)\b"
    r"|\b(?:external|unmerged)\s+branch\b"
    r"|\buntagged\s+build\b"
    r"|\bdry\s+rehearsal\b"
    r"|\bBlind\s+Spot\b"
    r"|\bivar/[A-Za-z0-9_./-]+\b"
    r"|\bIvar\s+has\s+since\b)",
    re.IGNORECASE,
)


@dataclass
class CheckResult:
    name: str
    status: str
    summary: str
    details: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class DocCommitCitation:
    doc: str
    line: int
    sha: str
    external_branch: bool


try:
    from pydantic_core import SchemaValidator as _SchemaValidator
    from pydantic_core import ValidationError as _ValidationError
    from pydantic_core import core_schema as _core_schema
    from pydantic_core import from_json as _pydantic_from_json

    _EPISODE_META_PROJECTION = _core_schema.nullable_schema(
        _core_schema.typed_dict_schema(
            {
                "tiers_version": _core_schema.typed_dict_field(_core_schema.any_schema(), required=False),
                "git_sha": _core_schema.typed_dict_field(_core_schema.any_schema(), required=False),
                "valid": _core_schema.typed_dict_field(_core_schema.any_schema(), required=False),
            },
            extra_behavior="ignore",
        )
    )
    _EPISODE_FAST_SCHEMA = _core_schema.typed_dict_schema(
        {
            "tier": _core_schema.typed_dict_field(_core_schema.any_schema(), required=False),
            "agent": _core_schema.typed_dict_field(_core_schema.any_schema(), required=False),
            "seed": _core_schema.typed_dict_field(_core_schema.any_schema(), required=False),
            "score": _core_schema.typed_dict_field(_core_schema.any_schema(), required=False),
            "meta": _core_schema.typed_dict_field(_EPISODE_META_PROJECTION, required=False),
            "tiers_version": _core_schema.typed_dict_field(_core_schema.any_schema(), required=False),
            "git_sha": _core_schema.typed_dict_field(_core_schema.any_schema(), required=False),
            "valid": _core_schema.typed_dict_field(_core_schema.any_schema(), required=False),
        },
        extra_behavior="ignore",
    )
    _EPISODE_LIST_VALIDATOR: Any = _SchemaValidator(
        _core_schema.list_schema(_EPISODE_FAST_SCHEMA),
        config={"allow_inf_nan": True},
    )
    _EPISODE_VALIDATOR: Any = _SchemaValidator(
        _core_schema.typed_dict_schema(
            {
                "tier": _core_schema.typed_dict_field(_core_schema.any_schema(), required=False),
                "agent": _core_schema.typed_dict_field(_core_schema.any_schema(), required=False),
                "seed": _core_schema.typed_dict_field(_core_schema.any_schema(), required=False),
                "score": _core_schema.typed_dict_field(_core_schema.any_schema(), required=False),
                "meta": _core_schema.typed_dict_field(_core_schema.any_schema(), required=False),
                "tiers_version": _core_schema.typed_dict_field(_core_schema.any_schema(), required=False),
                "git_sha": _core_schema.typed_dict_field(_core_schema.any_schema(), required=False),
                "valid": _core_schema.typed_dict_field(_core_schema.any_schema(), required=False),
            },
            extra_behavior="ignore",
        ),
        config={"allow_inf_nan": True},
    )
    _REDTEAM_SUMMARY_VALIDATOR: Any = _SchemaValidator(
        _core_schema.typed_dict_schema(
            {
                "generated_at": _core_schema.typed_dict_field(_core_schema.any_schema(), required=False),
                "git_sha": _core_schema.typed_dict_field(_core_schema.any_schema(), required=False),
                "ledger_run_ids": _core_schema.typed_dict_field(_core_schema.any_schema(), required=False),
                "counts": _core_schema.typed_dict_field(_core_schema.any_schema(), required=False),
                "by_sha": _core_schema.typed_dict_field(_core_schema.any_schema(), required=False),
            },
            extra_behavior="ignore",
        ),
        config={"allow_inf_nan": True},
    )
except Exception:
    _pydantic_from_json = None
    _EPISODE_LIST_VALIDATOR = None
    _EPISODE_VALIDATOR = None
    _REDTEAM_SUMMARY_VALIDATOR = None
    _ValidationError = ValueError


def _loads_json_bytes(raw: bytes) -> Any:
    if _pydantic_from_json is not None:
        return _pydantic_from_json(raw, allow_inf_nan=True)
    return json.loads(raw.decode("utf-8"))


def _loads_episode_projection(raw: bytes) -> Any:
    if _EPISODE_VALIDATOR is not None:
        try:
            return _EPISODE_VALIDATOR.validate_json(raw)
        except _ValidationError as exc:
            errs = exc.errors()
            if errs and errs[0].get("type") == "json_invalid":
                raise ValueError(str(exc)) from None
            return None
    return _loads_json_bytes(raw)


def _loads_redteam_summary_projection(raw: bytes) -> Any:
    if _REDTEAM_SUMMARY_VALIDATOR is not None:
        try:
            return _REDTEAM_SUMMARY_VALIDATOR.validate_json(raw)
        except _ValidationError as exc:
            errs = exc.errors()
            if errs and errs[0].get("type") == "json_invalid":
                raise ValueError(str(exc)) from None
            return None
    return _loads_json_bytes(raw)


def _is_finite_number(val: Any) -> bool:
    return isinstance(val, (int, float)) and not isinstance(val, bool) and math.isfinite(float(val))


def _is_int(val: Any) -> bool:
    return isinstance(val, int) and not isinstance(val, bool)


def _is_hex_sha(val: Any) -> bool:
    return isinstance(val, str) and HEX_SHA_RX.fullmatch(val.strip()) is not None


def _blocked_by_git_ceiling(root: Path) -> bool:
    raw = os.environ.get("GIT_CEILING_DIRECTORIES", "").strip()
    if not raw:
        return False
    for part in raw.split(os.pathsep):
        cleaned = part.strip()
        if not cleaned:
            continue
        try:
            if Path(cleaned).resolve() == root:
                return True
        except OSError:
            continue
    return False


class GitCommitInspector:
    def __init__(self, root: Path) -> None:
        self.root = Path(root).resolve()
        dot_git = self.root / ".git"
        self.has_git = (dot_git.exists() or dot_git.is_symlink()) and not _blocked_by_git_ceiling(self.root)
        self._cache: dict[str, tuple[str, str]] = {}
        self._head_commits_loaded = False
        self._head_commits: set[str] | None = None
        self._shallow_loaded = False
        self._is_shallow = False

    def _git_env(self) -> dict[str, str]:
        env = dict(os.environ)
        ceiling = str(self.root.parent)
        existing = env.get("GIT_CEILING_DIRECTORIES", "").strip()
        env["GIT_CEILING_DIRECTORIES"] = f"{ceiling}{os.pathsep}{existing}" if existing else ceiling
        return env

    @property
    def is_shallow(self) -> bool:
        if not self.has_git:
            return False
        if self._shallow_loaded:
            return self._is_shallow
        self._shallow_loaded = True
        if (self.root / ".git" / "shallow").is_file():
            self._is_shallow = True
            return True
        try:
            proc = subprocess.run(
                ["git", "rev-parse", "--is-shallow-repository"],
                cwd=self.root,
                env=self._git_env(),
                capture_output=True,
                text=True,
                timeout=10,
            )
            self._is_shallow = proc.returncode == 0 and proc.stdout.strip().lower() == "true"
        except (OSError, subprocess.SubprocessError):
            self._is_shallow = False
        return self._is_shallow

    def head_commits(self) -> set[str] | None:
        if not self.has_git:
            return None
        if self._head_commits_loaded:
            return self._head_commits
        self._head_commits_loaded = True
        try:
            proc = subprocess.run(
                ["git", "rev-list", "HEAD"],
                cwd=self.root,
                env=self._git_env(),
                capture_output=True,
                text=True,
                timeout=15,
            )
        except (OSError, subprocess.SubprocessError):
            self._head_commits = None
            return None
        if proc.returncode != 0:
            self._head_commits = None
            return None
        self._head_commits = {ln.strip().lower() for ln in proc.stdout.splitlines() if ln.strip()}
        return self._head_commits

    def _single_cat_file(self, sha: str) -> tuple[str, str]:
        git_env = self._git_env()
        try:
            proc_t = subprocess.run(
                ["git", "cat-file", "-t", sha],
                cwd=self.root,
                env=git_env,
                capture_output=True,
                text=True,
                timeout=10,
            )
        except (OSError, subprocess.SubprocessError):
            return ("error", "")
        if proc_t.returncode != 0:
            stderr_l = (proc_t.stderr or "").lower()
            if "not a git repository" in stderr_l:
                return ("error", "")
            return ("missing", "")
        obj_type = proc_t.stdout.strip()
        full_sha = sha
        try:
            proc_p = subprocess.run(
                ["git", "rev-parse", "--verify", sha],
                cwd=self.root,
                env=git_env,
                capture_output=True,
                text=True,
                timeout=10,
            )
            if proc_p.returncode == 0 and proc_p.stdout.strip():
                full_sha = proc_p.stdout.strip().lower()
        except (OSError, subprocess.SubprocessError):
            pass
        return (obj_type, full_sha)

    def resolve_shas(self, shas: Iterable[str]) -> dict[str, tuple[str, str]]:
        normalized = sorted({s.strip().lower() for s in shas if _is_hex_sha(s)})
        if not self.has_git or not normalized:
            return {}

        pending = [s for s in normalized if s not in self._cache]
        if pending:
            batch_ok = False
            try:
                proc = subprocess.run(
                    ["git", "cat-file", "--batch-check"],
                    cwd=self.root,
                    env=self._git_env(),
                    input="\n".join(pending) + "\n",
                    capture_output=True,
                    text=True,
                    timeout=15,
                )
                out_lines = proc.stdout.splitlines()
                if proc.returncode == 0 and len(out_lines) == len(pending):
                    batch_ok = True
                    for req_sha, line in zip(pending, out_lines):
                        parts = line.strip().split()
                        if len(parts) >= 2 and parts[1] == "missing":
                            self._cache[req_sha] = ("missing", "")
                        elif len(parts) >= 2 and parts[1] == "ambiguous":
                            self._cache[req_sha] = ("ambiguous", "")
                        elif len(parts) >= 2:
                            self._cache[req_sha] = (parts[1], parts[0].lower())
                        else:
                            self._cache[req_sha] = self._single_cat_file(req_sha)
            except (OSError, subprocess.SubprocessError):
                batch_ok = False

            if not batch_ok:
                for req_sha in pending:
                    self._cache[req_sha] = self._single_cat_file(req_sha)

        return {s: self._cache[s] for s in normalized}


def _expected_dir_tiers_version(rel_committed_parts: Sequence[str]) -> str:
    for seg in rel_committed_parts:
        if PATH_VERSION_SEG_RX.fullmatch(seg):
            return seg
    return LEGACY_TIERS_VERSION


def _read_and_project_episodes_file(
    ep_path: Path,
) -> tuple[OSError | None, list[tuple[int, Any, Exception | None]]]:
    try:
        raw_ep_bytes = ep_path.read_bytes()
    except OSError as exc:
        return (exc, [])

    if not raw_ep_bytes or not raw_ep_bytes.strip():
        return (None, [])

    if (
        _EPISODE_LIST_VALIDATOR is not None
        and raw_ep_bytes[0] not in b" \t\r\n"
        and b"\n\n" not in raw_ep_bytes
        and b"\r" not in raw_ep_bytes
    ):
        body = raw_ep_bytes[:-1] if raw_ep_bytes.endswith(b"\n") else raw_ep_bytes
        if body and not body.endswith(b"\n"):
            try:
                expected_lines = body.count(b"\n") + 1
                joined = b"[" + body.replace(b"\n", b",") + b"]"
                projected = _EPISODE_LIST_VALIDATOR.validate_json(joined)
                if len(projected) == expected_lines:
                    return (
                        None,
                        [(lineno, ep, None) for lineno, ep in enumerate(projected, 1)],
                    )
            except _ValidationError:
                pass

    nonempty: list[tuple[int, bytes]] = [
        (lineno, raw_line)
        for lineno, raw_line in enumerate(raw_ep_bytes.splitlines(), 1)
        if raw_line.strip()
    ]
    if not nonempty:
        return (None, [])

    if _EPISODE_LIST_VALIDATOR is not None:
        try:
            joined = b"[" + b",".join(raw_line for _, raw_line in nonempty) + b"]"
            projected = _EPISODE_LIST_VALIDATOR.validate_json(joined)
            if len(projected) == len(nonempty):
                return (
                    None,
                    [(lineno, ep, None) for (lineno, _), ep in zip(nonempty, projected)],
                )
        except _ValidationError:
            pass

    fallback_rows: list[tuple[int, Any, Exception | None]] = []
    for lineno, raw_line in nonempty:
        try:
            ep = _loads_episode_projection(raw_line)
            fallback_rows.append((lineno, ep, None))
        except (UnicodeDecodeError, ValueError) as exc:
            fallback_rows.append((lineno, None, exc))
    return (None, fallback_rows)


def check_committed_run_provenance(
    root: Path = ROOT,
    *,
    inspector: GitCommitInspector | None = None,
) -> CheckResult:
    name = CHECK_COMMITTED_RUNS
    root_resolved = Path(root).resolve()
    git_inspector = inspector if inspector is not None else GitCommitInspector(root_resolved)
    committed_root = root_resolved / "data" / "runs" / "committed"
    if not committed_root.is_dir():
        return CheckResult(
            name,
            "FAIL",
            "missing data/runs/committed directory",
            ["missing directory: data/runs/committed"],
        )

    discovered_dirs: set[Path] = set()
    for cur_root, dirnames, filenames in os.walk(committed_root):
        dirnames[:] = sorted(d for d in dirnames if d not in {"superseded", "transcripts"})
        if "meta.json" in filenames or "episodes.jsonl" in filenames:
            discovered_dirs.add(Path(cur_root))
    run_dirs = sorted(discovered_dirs)
    if not run_dirs:
        return CheckResult(
            name,
            "FAIL",
            "no non-superseded committed run directories found under data/runs/committed",
        )

    failures: list[str] = []
    meta_sha_refs: list[tuple[str, str]] = []
    total_valid_episodes = 0
    total_invalid_episodes = 0
    grok_unknown_dirs = 0
    v14_dirs = 0

    for run_dir in run_dirs:
        rel_dir = run_dir.relative_to(root_resolved).as_posix()
        rel_parts = run_dir.relative_to(committed_root).parts
        expected_version = _expected_dir_tiers_version(rel_parts)
        if rel_parts and rel_parts[0] == CURRENT_TIERS_VERSION:
            v14_dirs += 1

        meta_path = run_dir / "meta.json"
        ep_path = run_dir / "episodes.jsonl"
        rel_meta = f"{rel_dir}/meta.json"
        rel_ep = f"{rel_dir}/episodes.jsonl"

        if not meta_path.is_file():
            failures.append(f"{rel_dir}: missing meta.json")
            continue
        if not ep_path.is_file():
            failures.append(f"{rel_dir}: missing episodes.jsonl")
            continue

        try:
            meta = _loads_json_bytes(meta_path.read_bytes())
        except (OSError, UnicodeDecodeError, ValueError) as exc:
            failures.append(f"{rel_meta}: invalid JSON ({exc})")
            continue
        if not isinstance(meta, dict):
            failures.append(f"{rel_meta}: expected JSON object, got {type(meta).__name__}")
            continue

        if "tiers_version" in meta:
            raw_tv = meta["tiers_version"]
            if not isinstance(raw_tv, str) or not VERSION_RX.fullmatch(raw_tv.strip()):
                failures.append(f"{rel_meta}: malformed tiers_version {raw_tv!r}")
                resolved_version = expected_version
            else:
                resolved_version = raw_tv.strip()
                if resolved_version != expected_version:
                    failures.append(
                        f"{rel_meta}: tiers_version {resolved_version!r} inconsistent with directory expectation {expected_version!r}"
                    )
        else:
            resolved_version = expected_version

        if rel_parts and rel_parts[0] == CURRENT_TIERS_VERSION and resolved_version != CURRENT_TIERS_VERSION:
            failures.append(
                f"{rel_meta}: run under data/runs/committed/v1.4/ resolved to {resolved_version!r}, expected 'v1.4'"
            )

        is_grok = ("grok" in rel_parts) or (meta.get("agent") == "grok")
        raw_sha = meta.get("git_sha")
        if is_grok and (raw_sha is None or raw_sha == "unknown"):
            grok_unknown_dirs += 1
        elif not _is_hex_sha(raw_sha):
            failures.append(f"{rel_meta}: invalid or missing hex git_sha {raw_sha!r}")
        else:
            meta_sha_refs.append((rel_meta, str(raw_sha).strip().lower()))

        if "git_shas" in meta:
            raw_shas = meta["git_shas"]
            if not isinstance(raw_shas, list) or not raw_shas:
                failures.append(f"{rel_meta}: git_shas must be a non-empty list when present")
            else:
                bad_list_shas = [s for s in raw_shas if not _is_hex_sha(s)]
                if bad_list_shas:
                    failures.append(f"{rel_meta}: malformed entry in git_shas: {bad_list_shas!r}")
                else:
                    for extra_s in raw_shas:
                        meta_sha_refs.append((rel_meta, str(extra_s).strip().lower()))
                    if _is_hex_sha(raw_sha):
                        norm_list = {str(s).strip().lower() for s in raw_shas}
                        if str(raw_sha).strip().lower() not in norm_list:
                            failures.append(
                                f"{rel_meta}: primary git_sha {raw_sha!r} missing from git_shas list"
                            )

        meta_tier = meta.get("tier") if isinstance(meta.get("tier"), str) and meta.get("tier") else None
        meta_agent = meta.get("agent") if isinstance(meta.get("agent"), str) and meta.get("agent") else None

        seen_valid: dict[tuple[str, int], int] = {}
        dir_records = 0
        io_err, parsed_rows = _read_and_project_episodes_file(ep_path)
        if io_err is not None:
            failures.append(f"{rel_ep}: unreadable episodes.jsonl ({io_err})")
            continue

        for lineno, ep, parse_exc in parsed_rows:
            loc = f"{rel_ep}:{lineno}"
            if parse_exc is not None:
                failures.append(f"{loc}: invalid JSON ({parse_exc})")
                continue
            if not isinstance(ep, dict):
                failures.append(f"{loc}: episode record must be a JSON object")
                continue

            dir_records += 1
            ep_tier = ep.get("tier")
            ep_agent = ep.get("agent")
            if not isinstance(ep_tier, str) or not ep_tier.strip():
                failures.append(f"{loc}: missing or invalid tier {ep_tier!r}")
                continue
            if not isinstance(ep_agent, str) or not ep_agent.strip():
                failures.append(f"{loc}: missing or invalid agent {ep_agent!r}")
                continue
            if "seed" not in ep or isinstance(ep.get("seed"), bool):
                failures.append(f"{loc}: missing or boolean seed {ep.get('seed')!r}")
                continue
            try:
                seed = int(ep["seed"])
            except (TypeError, ValueError):
                failures.append(f"{loc}: non-integer seed {ep.get('seed')!r}")
                continue

            if not _is_finite_number(ep.get("score")):
                failures.append(f"{loc}: non-finite score {ep.get('score')!r}")

            if meta_tier is not None and ep_tier != meta_tier:
                failures.append(f"{loc}: episode tier {ep_tier!r} != meta.json tier {meta_tier!r}")
            if meta_agent is not None and ep_agent != meta_agent:
                failures.append(f"{loc}: episode agent {ep_agent!r} != meta.json agent {meta_agent!r}")

            ep_meta = ep.get("meta")
            if ep_meta is not None and not isinstance(ep_meta, dict):
                failures.append(f"{loc}: episode meta must be an object when present")
                ep_meta_dict: dict[str, Any] = {}
            else:
                ep_meta_dict = ep_meta or {}

            for tv_source, tv_container in (("episode", ep), ("episode.meta", ep_meta_dict)):
                if "tiers_version" in tv_container:
                    ep_tv = tv_container["tiers_version"]
                    if not isinstance(ep_tv, str) or not VERSION_RX.fullmatch(ep_tv.strip()):
                        failures.append(f"{loc}: malformed {tv_source} tiers_version {ep_tv!r}")
                    elif ep_tv.strip() != resolved_version:
                        failures.append(
                            f"{loc}: {tv_source} tiers_version {ep_tv!r} != directory version {resolved_version!r}"
                        )

            for sha_source, sha_container in (("episode", ep), ("episode.meta", ep_meta_dict)):
                if "git_sha" in sha_container:
                    ep_sha = sha_container["git_sha"]
                    if not (is_grok and ep_sha == "unknown") and not _is_hex_sha(ep_sha):
                        failures.append(f"{loc}: malformed {sha_source} git_sha {ep_sha!r}")

            if "valid" in ep and not isinstance(ep["valid"], bool):
                failures.append(f"{loc}: episode valid field must be boolean, got {ep['valid']!r}")
                continue
            if "valid" in ep_meta_dict and not isinstance(ep_meta_dict["valid"], bool):
                failures.append(
                    f"{loc}: episode meta.valid field must be boolean, got {ep_meta_dict['valid']!r}"
                )
                continue

            is_valid = (ep.get("valid") is not False) and (ep_meta_dict.get("valid") is not False)
            if is_valid:
                total_valid_episodes += 1
                key = (ep_tier, seed)
                if key in seen_valid:
                    failures.append(
                        f"{loc}: duplicate valid (tier={ep_tier!r}, seed={seed}) in directory (first at line {seen_valid[key]})"
                    )
                else:
                    seen_valid[key] = lineno
            else:
                total_invalid_episodes += 1

        if dir_records == 0:
            failures.append(f"{rel_ep}: empty episodes.jsonl (0 episode records)")

    if git_inspector.has_git and meta_sha_refs:
        resolved_meta = git_inspector.resolve_shas(sha for _, sha in meta_sha_refs)
        if not all(info[0] == "error" for info in resolved_meta.values()):
            for rel_meta, sha_val in meta_sha_refs:
                obj_type, _ = resolved_meta.get(sha_val, ("missing", ""))
                if obj_type == "missing":
                    if not git_inspector.is_shallow:
                        failures.append(f"{rel_meta}: git_sha {sha_val!r} does not exist in .git")
                elif obj_type != "commit":
                    failures.append(f"{rel_meta}: git_sha {sha_val!r} resolves to {obj_type!r}, expected 'commit'")

    if failures:
        return CheckResult(
            name,
            "FAIL",
            f"{len(failures)} provenance issue(s) across {len(run_dirs)} non-superseded run dir(s)",
            failures,
        )

    return CheckResult(
        name,
        "PASS",
        f"verified {len(run_dirs)} run dir(s) ({v14_dirs} v1.4), "
        f"{total_valid_episodes} valid + {total_invalid_episodes} invalid episode(s), "
        f"0 duplicate valid seeds ({grok_unknown_dirs} historical grok unknown-SHA dir(s) allowed)",
    )


def _audit_judge_table_provenance(
    root: Path,
    failures: list[str],
    merged_shas: list[tuple[str, str]],
) -> int:
    rel = "results/judge_table.md"
    jt_path = root / rel
    if not jt_path.is_file():
        failures.append(f"missing artifact: {rel}")
        return 0
    try:
        text = jt_path.read_text(encoding="utf-8")
    except OSError as exc:
        failures.append(f"{rel}: unreadable file ({exc})")
        return 0

    if "[FAST MODE: not the reported numbers]" in text:
        failures.append(f"{rel}: generated in FAST MODE rather than full judge reproduction")

    m_git = JUDGE_TABLE_HEADER_GIT_RX.search(text)
    if m_git is None:
        failures.append(f"{rel}: missing '- git: `<sha>`' provenance line in header")
    elif not _is_hex_sha(m_git.group(1)):
        failures.append(f"{rel}: malformed header git SHA {m_git.group(1)!r}")
    else:
        merged_shas.append((rel, m_git.group(1).strip().lower()))

    if JUDGE_TABLE_HEADER_FP_RX.search(text) is None:
        failures.append(f"{rel}: missing judge-world secret sha256 fingerprint provenance line")

    if "Reported agent runs: v1.4 (current rules):" not in text:
        failures.append(f"{rel}: missing 'Reported agent runs: v1.4 (current rules):' section")

    reported_notes = list(JUDGE_TABLE_REPORTED_NOTE_RX.finditer(text))
    if not reported_notes:
        failures.append(f"{rel}: no reported run provenance notes found")
        return 0

    referenced_dirs: set[str] = set()
    meta_sha_cache: dict[str, Any] = {}
    for match in reported_notes:
        lineno = 1 + text.count("\n", 0, match.start())
        raw_shas = [tok.strip() for tok in match.group(1).strip().split(",") if tok.strip()]
        raw_dirs = [tok.strip() for tok in match.group(2).strip().split(",") if tok.strip()]
        if not raw_shas or not raw_dirs:
            failures.append(f"{rel}:{lineno}: empty git SHA or run directory list in reported row")
            continue

        is_grok_row = all("grok" in Path(d).parts for d in raw_dirs)
        if raw_shas == ["unknown"]:
            if not is_grok_row:
                failures.append(f"{rel}:{lineno}: unexpected 'git unknown' on non-grok dirs {raw_dirs}")
        else:
            bad_tokens = [tok for tok in raw_shas if not _is_hex_sha(tok)]
            if bad_tokens:
                failures.append(f"{rel}:{lineno}: malformed reported git SHA token(s) {bad_tokens!r}")
                continue
            for tok in raw_shas:
                merged_shas.append((f"{rel}:{lineno}", tok.lower()))

        for run_rel in raw_dirs:
            referenced_dirs.add(Path(run_rel).as_posix())
            if run_rel not in meta_sha_cache:
                meta_file = root / run_rel / "meta.json"
                if not meta_file.is_file():
                    meta_sha_cache[run_rel] = ("missing", None)
                else:
                    try:
                        meta_obj = _loads_json_bytes(meta_file.read_bytes())
                        meta_sha_cache[run_rel] = (
                            ("ok", meta_obj.get("git_sha")) if isinstance(meta_obj, dict) else ("bad", None)
                        )
                    except (OSError, UnicodeDecodeError, ValueError):
                        meta_sha_cache[run_rel] = ("bad", None)
            state, meta_sha = meta_sha_cache[run_rel]
            if state != "ok":
                failures.append(f"{rel}:{lineno}: referenced run dir {run_rel!r} has {state} meta.json")
                continue
            if is_grok_row and (meta_sha is None or meta_sha == "unknown"):
                continue
            if _is_hex_sha(meta_sha):
                short_prefix = str(meta_sha).strip().lower()[:7]
                norm_row_shas = [tok.lower() for tok in raw_shas]
                if not any(
                    tok.startswith(short_prefix) or short_prefix.startswith(tok)
                    for tok in norm_row_shas
                ):
                    failures.append(
                        f"{rel}:{lineno}: reported git {raw_shas} does not match {run_rel}/meta.json git_sha {meta_sha!r}"
                    )

    v14_root = root / "data" / "runs" / "committed" / CURRENT_TIERS_VERSION
    if v14_root.is_dir():
        for cur_root, dirnames, filenames in os.walk(v14_root):
            dirnames[:] = sorted(d for d in dirnames if d not in {"superseded", "transcripts"})
            if "meta.json" in filenames or "episodes.jsonl" in filenames:
                rel_v14 = Path(cur_root).relative_to(root).as_posix()
                if rel_v14 not in referenced_dirs:
                    failures.append(
                        f"{rel}: committed v1.4 run directory {rel_v14!r} missing from reported notes"
                    )

    return len(reported_notes)


def _audit_failure_analysis_provenance(root: Path, failures: list[str]) -> int:
    rel = "results/failure_analysis_v1.4.json"
    fa_path = root / rel
    if not fa_path.is_file():
        failures.append(f"missing artifact: {rel}")
        return 0
    try:
        data = _loads_json_bytes(fa_path.read_bytes())
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        failures.append(f"{rel}: invalid JSON ({exc})")
        return 0
    if not isinstance(data, dict):
        failures.append(f"{rel}: expected JSON object")
        return 0

    g_map = data.get("G")
    i_map = data.get("I")
    s_map = data.get("S")
    summary = data.get("summary")
    if not (
        isinstance(g_map, dict)
        and isinstance(i_map, dict)
        and isinstance(s_map, dict)
        and isinstance(summary, dict)
    ):
        failures.append(f"{rel}: missing required top-level 'G', 'I', 'S', or 'summary' object")
        return 0

    if not g_map or set(g_map.keys()) != set(i_map.keys()) or set(g_map.keys()) != set(s_map.keys()):
        failures.append(f"{rel}: non-empty paired seed sets across G, I, S do not match")
        return 0

    n_seeds = len(g_map)
    oc_sum = summary.get("opencode")
    sv_sum = summary.get("solver")
    gap_sum = summary.get("gap")
    if not (isinstance(oc_sum, dict) and isinstance(sv_sum, dict) and isinstance(gap_sum, dict)):
        failures.append(f"{rel}: summary missing 'opencode', 'solver', or 'gap' section")
        return n_seeds

    if oc_sum.get("n") != n_seeds or sv_sum.get("n") != n_seeds:
        failures.append(
            f"{rel}: summary n mismatch (opencode.n={oc_sum.get('n')!r}, solver.n={sv_sum.get('n')!r}, seeds={n_seeds})"
        )

    for seed_key, rec in g_map.items():
        if not isinstance(rec, dict) or not isinstance(rec.get("agent"), str) or not rec["agent"]:
            failures.append(f"{rel}: G[{seed_key!r}] missing agent provenance")
            break
    for seed_key, rec in s_map.items():
        if not isinstance(rec, dict) or rec.get("agent") != "solver":
            failures.append(f"{rel}: S[{seed_key!r}] expected agent='solver'")
            break

    oc_hard_meta = root / "data" / "runs" / "committed" / "v1.4" / "opencode-gemini-4-carbon" / "hard" / "meta.json"
    if oc_hard_meta.is_file():
        try:
            meta_obj = _loads_json_bytes(oc_hard_meta.read_bytes())
            if isinstance(meta_obj, dict):
                tv = meta_obj.get("tiers_version", CURRENT_TIERS_VERSION)
                if tv != CURRENT_TIERS_VERSION:
                    failures.append(
                        f"{rel}: source opencode hard meta.json has tiers_version={tv!r}, expected 'v1.4'"
                    )
                planned = meta_obj.get("seeds")
                if isinstance(planned, list) and len(planned) != n_seeds:
                    failures.append(
                        f"{rel}: G seed count {n_seeds} != committed opencode hard meta.json seeds {len(planned)}"
                    )
        except (OSError, UnicodeDecodeError, ValueError):
            pass

    return n_seeds


def _audit_oracle_range_provenance(root: Path, failures: list[str]) -> int:
    rel = "results/oracle_range_v1.4.json"
    or_path = root / rel
    if not or_path.is_file():
        failures.append(f"missing artifact: {rel}")
        return 0
    try:
        data = _loads_json_bytes(or_path.read_bytes())
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        failures.append(f"{rel}: invalid JSON ({exc})")
        return 0
    if not isinstance(data, dict):
        failures.append(f"{rel}: expected JSON object")
        return 0

    for str_key in ("command", "secrets"):
        val = data.get(str_key)
        if not isinstance(val, str) or not val.strip():
            failures.append(f"{rel}: missing or empty provenance field {str_key!r}")

    rows = data.get("rows")
    if not isinstance(rows, list) or not rows:
        failures.append(f"{rel}: missing or empty 'rows' list")
        return 0

    has_solver_hard = False
    for idx, row in enumerate(rows):
        if not isinstance(row, dict):
            failures.append(f"{rel}: rows[{idx}] is not an object")
            continue
        agent = row.get("agent")
        tier = row.get("tier")
        builds = row.get("builds")
        k10 = row.get("k10")
        if not isinstance(agent, str) or not agent.strip():
            failures.append(f"{rel}: rows[{idx}] missing valid agent")
        if tier not in EXPECTED_TIERS:
            failures.append(f"{rel}: rows[{idx}] invalid tier {tier!r}")
        if not _is_int(builds) or int(builds) < 100:
            failures.append(f"{rel}: rows[{idx}] expected integer builds >= 100, got {builds!r}")
        if not isinstance(k10, dict) or not all(
            _is_finite_number(k10.get(metric)) for metric in ("mean", "sd", "p5", "p95")
        ):
            failures.append(f"{rel}: rows[{idx}] missing finite k10 provenance stats")
        if agent == "solver" and tier == "hard":
            has_solver_hard = True

    if not has_solver_hard:
        failures.append(f"{rel}: missing solver hard row")

    return len(rows)


def _audit_solver_range_provenance(root: Path, failures: list[str]) -> int:
    sr_dir = root / "results" / "solver_range"
    if not sr_dir.is_dir():
        failures.append("missing directory: results/solver_range")
        return 0

    expected_names = {
        f"{agent}_{tier}_judge40.json"
        for agent in EXPECTED_SOLVER_RANGE_AGENTS
        for tier in EXPECTED_TIERS
    }
    discovered = sorted(sr_dir.glob("*_judge40.json"))
    discovered_names = {p.name for p in discovered}
    for req_name in sorted(expected_names - discovered_names):
        failures.append(f"missing artifact: results/solver_range/{req_name}")

    for sr_path in discovered:
        rel = f"results/solver_range/{sr_path.name}"
        try:
            obj = _loads_json_bytes(sr_path.read_bytes())
        except (OSError, UnicodeDecodeError, ValueError) as exc:
            failures.append(f"{rel}: invalid JSON ({exc})")
            continue
        if not isinstance(obj, dict):
            failures.append(f"{rel}: expected JSON object")
            continue

        m_name = SOLVER_RANGE_FILENAME_RX.match(sr_path.name)
        agent = obj.get("agent")
        tier = obj.get("tier")
        builds = obj.get("builds")
        seeds = obj.get("seeds")

        if not isinstance(agent, str) or not agent.strip():
            failures.append(f"{rel}: missing valid 'agent'")
        elif m_name and agent != m_name.group(1):
            failures.append(f"{rel}: agent {agent!r} does not match filename '{m_name.group(1)}'")

        if tier not in EXPECTED_TIERS:
            failures.append(f"{rel}: invalid 'tier' {tier!r}")
        elif m_name and tier != m_name.group(2):
            failures.append(f"{rel}: tier {tier!r} does not match filename '{m_name.group(2)}'")

        if not _is_int(builds) or int(builds) < 100:
            failures.append(f"{rel}: expected integer builds >= 100, got {builds!r}")
        elif "build_means" in obj:
            bm = obj["build_means"]
            if not isinstance(bm, list) or len(bm) != int(builds):
                failures.append(
                    f"{rel}: build_means length {len(bm) if isinstance(bm, list) else type(bm).__name__} != builds {builds}"
                )

        if not isinstance(seeds, list) or not seeds or not all(_is_int(s) for s in seeds):
            failures.append(f"{rel}: missing or invalid integer 'seeds' list")

        if not _is_finite_number(obj.get("mean")) or not _is_finite_number(obj.get("sd")):
            failures.append(f"{rel}: missing finite 'mean' or 'sd'")

    return len(discovered)


def _audit_gemini_ladder_provenance(
    root: Path,
    failures: list[str],
    external_shas: list[tuple[str, str]],
) -> tuple[int, int]:
    rel = "results/gemini/ladder.json"
    lad_path = root / rel
    if not lad_path.is_file():
        failures.append(f"missing artifact: {rel}")
        return (0, 0)
    try:
        data = _loads_json_bytes(lad_path.read_bytes())
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        failures.append(f"{rel}: invalid JSON ({exc})")
        return (0, 0)
    if not isinstance(data, dict):
        failures.append(f"{rel}: expected JSON object")
        return (0, 0)

    top_sha = data.get("git_sha")
    if not _is_hex_sha(top_sha):
        failures.append(f"{rel}: missing or malformed top-level git_sha {top_sha!r}")
    else:
        external_shas.append((rel, str(top_sha).strip().lower()))

    gen_at = data.get("generated_at")
    if not isinstance(gen_at, str) or not gen_at.strip():
        failures.append(f"{rel}: missing or empty generated_at timestamp")

    episodes = data.get("episodes")
    if not _is_int(episodes) or int(episodes) <= 0:
        failures.append(f"{rel}: expected positive integer 'episodes', got {episodes!r}")
        episodes_int = 0
    else:
        episodes_int = int(episodes)

    rows = data.get("rows")
    if not isinstance(rows, list) or not rows:
        failures.append(f"{rel}: missing or empty 'rows' list")
        return (0, episodes_int)

    summed_n = 0
    for idx, row in enumerate(rows):
        if not isinstance(row, dict):
            failures.append(f"{rel}: rows[{idx}] is not an object")
            continue
        model = row.get("model")
        level = row.get("level")
        tier = row.get("tier")
        n_val = row.get("n")
        if not isinstance(model, str) or not model.strip():
            failures.append(f"{rel}: rows[{idx}] missing valid 'model'")
        if not isinstance(level, str) or not level.strip():
            failures.append(f"{rel}: rows[{idx}] missing valid 'level'")
        if tier not in EXPECTED_TIERS:
            failures.append(f"{rel}: rows[{idx}] invalid tier {tier!r}")
        if not _is_int(n_val) or int(n_val) <= 0:
            failures.append(f"{rel}: rows[{idx}] expected positive integer 'n', got {n_val!r}")
        else:
            summed_n += int(n_val)

        tv_list = row.get("tiers_versions")
        if not isinstance(tv_list, list) or not tv_list:
            failures.append(f"{rel}: rows[{idx}] missing non-empty 'tiers_versions'")
        else:
            for tv_item in tv_list:
                if not isinstance(tv_item, str) or not tv_item.strip():
                    failures.append(f"{rel}: rows[{idx}] invalid tiers_versions entry {tv_item!r}")
                    continue
                tv_head = tv_item.strip().split()[0]
                if not VERSION_RX.fullmatch(tv_head) or tv_head != CURRENT_TIERS_VERSION:
                    failures.append(
                        f"{rel}: rows[{idx}] unexpected tiers_versions entry {tv_item!r} (expected v1.4)"
                    )

        launch_shas = row.get("launch_git_shas")
        if not isinstance(launch_shas, list) or not launch_shas:
            failures.append(f"{rel}: rows[{idx}] missing non-empty 'launch_git_shas'")
        else:
            bad_lshas = [s for s in launch_shas if not _is_hex_sha(s)]
            if bad_lshas:
                failures.append(f"{rel}: rows[{idx}] malformed launch_git_shas {bad_lshas!r}")
            else:
                for lsha in launch_shas:
                    external_shas.append((rel, str(lsha).strip().lower()))

    if episodes_int > 0 and summed_n != episodes_int:
        failures.append(
            f"{rel}: dynamic episode sum {summed_n} across {len(rows)} row(s) != top-level episodes {episodes_int}"
        )

    return (len(rows), episodes_int)


def _audit_harbor_rehearsal_provenance(
    root: Path,
    failures: list[str],
    merged_shas: list[tuple[str, str]],
    external_shas: list[tuple[str, str]],
) -> int:
    rel_build = "results/harbor/rehearsal/BUILD.txt"
    rel_table = "results/harbor/rehearsal/TABLE.md"
    build_path = root / rel_build
    table_path = root / rel_table

    kv: dict[str, str] = {}
    build_sha = ""
    if not build_path.is_file():
        failures.append(f"missing artifact: {rel_build}")
    else:
        try:
            build_text = build_path.read_text(encoding="utf-8")
        except OSError as exc:
            failures.append(f"{rel_build}: unreadable file ({exc})")
            build_text = ""
        for raw_ln in build_text.splitlines():
            if ":" in raw_ln:
                k, v = raw_ln.split(":", 1)
                k_clean = k.strip().lower()
                if k_clean and k_clean not in kv:
                    kv[k_clean] = v.strip()
        build_sha = kv.get("sha", "")
        if not _is_hex_sha(build_sha):
            failures.append(f"{rel_build}: missing or malformed sha {build_sha!r}")
        else:
            merged_shas.append((rel_build, build_sha.lower()))
        for req_field in ("describe", "built_utc", "harbor"):
            if not kv.get(req_field, ""):
                failures.append(f"{rel_build}: missing or empty provenance field {req_field!r}")

    if not table_path.is_file():
        failures.append(f"missing artifact: {rel_table}")
        return 0
    try:
        table_text = table_path.read_text(encoding="utf-8")
    except OSError as exc:
        failures.append(f"{rel_table}: unreadable file ({exc})")
        return 0

    m_head = HARBOR_REHEARSAL_HEADING_RX.search(table_text)
    if m_head is None:
        failures.append(f"{rel_table}: missing rehearsal heading with tag, short SHA, and Harbor version")
    else:
        tag_name = m_head.group(1).strip()
        table_sha = m_head.group(2).strip().lower()
        harbor_ver = m_head.group(3).strip()
        merged_shas.append((rel_table, table_sha))
        if _is_hex_sha(build_sha):
            b_low = build_sha.lower()
            if not (b_low.startswith(table_sha) or table_sha.startswith(b_low)):
                failures.append(
                    f"{rel_table}: heading SHA {table_sha!r} does not match {rel_build} sha {build_sha!r}"
                )
        if kv.get("describe") and tag_name != kv["describe"]:
            failures.append(
                f"{rel_table}: heading tag {tag_name!r} != {rel_build} describe {kv['describe']!r}"
            )
        if kv.get("harbor") and harbor_ver != kv["harbor"]:
            failures.append(
                f"{rel_table}: heading Harbor version {harbor_ver!r} != {rel_build} harbor {kv['harbor']!r}"
            )

    if "BUILD.txt" not in table_text:
        failures.append(f"{rel_table}: missing BUILD.txt provenance reference")

    for m_commit in HARBOR_REHEARSAL_COMMIT_NOTE_RX.finditer(table_text):
        note_sha = m_commit.group(1).strip()
        if not _is_hex_sha(note_sha):
            failures.append(f"{rel_table}: malformed commit note SHA {note_sha!r}")
        else:
            external_shas.append((rel_table, note_sha.lower()))

    expected_runs = ("opencode-1", "opencode-2", "opencode-3", "do_nothing", "stop_early")
    found_runs: set[str] = set()
    for raw_ln in table_text.splitlines():
        s = raw_ln.strip()
        if not (s.startswith("|") and s.endswith("|")):
            continue
        cells = [c.strip() for c in s[1:-1].split("|")]
        if len(cells) >= 5 and cells[0] in expected_runs:
            found_runs.add(cells[0])
            if cells[0] in {"do_nothing", "stop_early"} and cells[4] not in {"+0.000", "0.000", "0"}:
                failures.append(
                    f"{rel_table}: expected 0.000 mean for {cells[0]}, got {cells[4]!r}"
                )

    for req_run in expected_runs:
        if req_run not in found_runs:
            failures.append(f"{rel_table}: missing summary row for {req_run!r}")

    return len(found_runs)


def _audit_redteam_1000_provenance(
    root: Path,
    failures: list[str],
    merged_shas: list[tuple[str, str]],
    external_shas: list[tuple[str, str]],
) -> tuple[int, int]:
    rel_md = "results/redteam_1000/summary.md"
    rel_json = "results/redteam_1000/summary.json"
    md_path = root / rel_md
    if not md_path.is_file():
        failures.append(f"missing artifact: {rel_md}")
        return (0, 0)
    try:
        md_text = md_path.read_text(encoding="utf-8")
    except OSError as exc:
        failures.append(f"{rel_md}: unreadable file ({exc})")
        return (0, 0)

    gen_ts = ""
    gen_sha = ""
    m_gen = REDTEAM_GENERATED_RX.search(md_text)
    if m_gen is None:
        failures.append(f"{rel_md}: missing 'Generated <timestamp> at `<sha>`.' provenance header")
    else:
        gen_ts = m_gen.group(1).strip()
        gen_sha = m_gen.group(2).strip()
        if not _is_hex_sha(gen_sha):
            failures.append(f"{rel_md}: malformed generator git SHA {gen_sha!r}")
        else:
            external_shas.append((rel_md, gen_sha.lower()))

    headline_attackers = 0
    m_att = REDTEAM_HEADLINE_ATTACKERS_RX.search(md_text)
    if m_att is None:
        failures.append(f"{rel_md}: missing '**<N> Gemini attackers**' headline count")
    else:
        headline_attackers = int(m_att.group(1))
        if headline_attackers <= 0:
            failures.append(f"{rel_md}: expected positive Gemini attackers count, got {headline_attackers}")

    m_exp = REDTEAM_EXPLOITS_LINE_RX.search(md_text)
    if m_exp is None:
        failures.append(f"{rel_md}: missing Verified exploits / invariant violations summary line")
    elif int(m_exp.group(1)) != 0 or int(m_exp.group(2)) != 0:
        failures.append(
            f"{rel_md}: expected 0 verified exploits and 0 invariant violations, got {m_exp.group(1)} and {m_exp.group(2)}"
        )

    m_split = REDTEAM_COMMIT_SPLIT_HEADING_RX.search(md_text)
    commit_rows = 0
    summed_attempts = 0
    total_attempts: int | None = None
    md_split_by_sha: dict[str, int] = {}
    if m_split is None:
        failures.append(f"{rel_md}: missing 'Combined count split by commit (SHA)' table")
    else:
        tail_lines = md_text[m_split.end() :].splitlines()
        col_map: dict[str, int] | None = None
        seen_table = False
        for raw_ln in tail_lines:
            s = raw_ln.strip()
            if not s:
                if seen_table:
                    break
                continue
            if not (s.startswith("|") and s.endswith("|")):
                if seen_table:
                    break
                continue
            seen_table = True
            cells = [c.strip() for c in s[1:-1].split("|")]
            if cells and all(TABLE_SEP_CELL_RX.match(c) for c in cells if c):
                continue
            if col_map is None:
                col_map = {c.strip("`* ").lower(): idx for idx, c in enumerate(cells)}
                for req_col in ("commit (sha)", "attempts", "ledger-verified", "invariant violations", "verified exploits"):
                    if req_col not in col_map:
                        failures.append(f"{rel_md}: commit-split table missing column {req_col!r}")
                continue

            if not all(
                k in col_map
                for k in ("commit (sha)", "attempts", "ledger-verified", "invariant violations", "verified exploits")
            ):
                break
            sha_cell = cells[col_map["commit (sha)"]].strip("`* ")
            try:
                att_val = int(cells[col_map["attempts"]].strip("`* "))
                ver_val = int(cells[col_map["ledger-verified"]].strip("`* "))
                viol_val = int(cells[col_map["invariant violations"]].strip("`* "))
                expl_val = int(cells[col_map["verified exploits"]].strip("`* "))
            except (IndexError, ValueError) as exc:
                failures.append(f"{rel_md}: invalid integer cell in commit-split row {sha_cell!r} ({exc})")
                continue

            if sha_cell.upper().startswith("TOTAL"):
                total_attempts = att_val
                if ver_val != att_val or viol_val != 0 or expl_val != 0:
                    failures.append(
                        f"{rel_md}: TOTAL commit-split row invariant mismatch (attempts={att_val}, verified={ver_val}, violations={viol_val}, exploits={expl_val})"
                    )
            else:
                if not _is_hex_sha(sha_cell):
                    failures.append(f"{rel_md}: malformed commit SHA {sha_cell!r} in commit-split table")
                else:
                    sha_low = sha_cell.lower()
                    merged_shas.append((rel_md, sha_low))
                    md_split_by_sha[sha_low] = att_val
                if att_val <= 0 or ver_val != att_val or viol_val != 0 or expl_val != 0:
                    failures.append(
                        f"{rel_md}: commit-split row {sha_cell!r} invariant mismatch (attempts={att_val}, verified={ver_val}, violations={viol_val}, exploits={expl_val})"
                    )
                commit_rows += 1
                summed_attempts += att_val

        if commit_rows == 0:
            failures.append(f"{rel_md}: commit-split table contains 0 commit rows")
        if total_attempts is None:
            failures.append(f"{rel_md}: commit-split table missing TOTAL row")
        elif summed_attempts != total_attempts:
            failures.append(
                f"{rel_md}: commit-split dynamic sum {summed_attempts} != TOTAL row {total_attempts}"
            )
        if headline_attackers > 0 and summed_attempts != headline_attackers:
            failures.append(
                f"{rel_md}: commit-split dynamic sum {summed_attempts} != headline {headline_attackers} Gemini attackers"
            )

    json_path = root / rel_json
    if not json_path.is_file():
        failures.append(f"missing artifact: {rel_json}")
    else:
        try:
            jdata = _loads_redteam_summary_projection(json_path.read_bytes())
        except (OSError, UnicodeDecodeError, ValueError) as exc:
            failures.append(f"{rel_json}: invalid JSON ({exc})")
            jdata = None
        if jdata is not None and not isinstance(jdata, dict):
            failures.append(f"{rel_json}: expected JSON object")
        elif isinstance(jdata, dict):
            j_sha = jdata.get("git_sha")
            if not _is_hex_sha(j_sha):
                failures.append(f"{rel_json}: missing or malformed git_sha {j_sha!r}")
            else:
                j_sha_l = str(j_sha).strip().lower()
                external_shas.append((rel_json, j_sha_l))
                if _is_hex_sha(gen_sha) and not (
                    j_sha_l.startswith(gen_sha.lower()) or gen_sha.lower().startswith(j_sha_l)
                ):
                    failures.append(
                        f"{rel_json}: git_sha {j_sha!r} does not match {rel_md} generator SHA {gen_sha!r}"
                    )
            j_ts = jdata.get("generated_at")
            if not isinstance(j_ts, str) or not j_ts.strip():
                failures.append(f"{rel_json}: missing generated_at timestamp")
            elif gen_ts and j_ts.strip() != gen_ts:
                failures.append(
                    f"{rel_json}: generated_at {j_ts!r} != {rel_md} Generated timestamp {gen_ts!r}"
                )
            run_ids = jdata.get("ledger_run_ids")
            if not isinstance(run_ids, list) or not run_ids:
                failures.append(f"{rel_json}: missing non-empty ledger_run_ids list")

            if "counts" in jdata:
                counts_obj = jdata["counts"]
                if not isinstance(counts_obj, dict):
                    failures.append(f"{rel_json}: expected 'counts' object")
                else:
                    c_att = counts_obj.get("attempts")
                    c_ver = counts_obj.get("ledger_verified")
                    c_exp = counts_obj.get("exploits")
                    c_viol = counts_obj.get("invariant_violations")
                    if summed_attempts > 0 and (c_att != summed_attempts or c_ver != summed_attempts):
                        failures.append(
                            f"{rel_json}: counts attempts/ledger_verified ({c_att}/{c_ver}) != {rel_md} sum {summed_attempts}"
                        )
                    if c_exp != 0 or c_viol != 0:
                        failures.append(
                            f"{rel_json}: counts expected 0 exploits and 0 invariant_violations, got {c_exp!r} and {c_viol!r}"
                        )

            if "by_sha" in jdata:
                by_sha_list = jdata["by_sha"]
                if not isinstance(by_sha_list, list) or not by_sha_list:
                    failures.append(f"{rel_json}: 'by_sha' must be a non-empty list when present")
                else:
                    json_split_by_sha: dict[str, int] = {}
                    for idx, item in enumerate(by_sha_list):
                        if not isinstance(item, dict):
                            failures.append(f"{rel_json}: by_sha[{idx}] is not an object")
                            continue
                        item_sha = item.get("git_sha")
                        item_att = item.get("attempts")
                        item_ver = item.get("ledger_verified")
                        item_viol = item.get("invariant_violations")
                        item_exp = item.get("exploits")
                        if not _is_hex_sha(item_sha):
                            failures.append(f"{rel_json}: by_sha[{idx}] malformed git_sha {item_sha!r}")
                            continue
                        item_sha_l = str(item_sha).strip().lower()
                        merged_shas.append((rel_json, item_sha_l))
                        if (
                            not _is_int(item_att)
                            or int(item_att) <= 0
                            or item_ver != item_att
                            or item_viol != 0
                            or item_exp != 0
                        ):
                            failures.append(
                                f"{rel_json}: by_sha[{idx}] ({item_sha_l}) invariant mismatch"
                            )
                            continue
                        json_split_by_sha[item_sha_l] = int(item_att)
                    if md_split_by_sha and json_split_by_sha != md_split_by_sha:
                        failures.append(
                            f"{rel_json}: by_sha split {json_split_by_sha} != {rel_md} split {md_split_by_sha}"
                        )

    return (commit_rows, summed_attempts)


def _audit_paired_table_provenance(
    root: Path,
    failures: list[str],
    merged_shas: list[tuple[str, str]],
) -> int:
    rel = "data/runs/committed/v1.4/paired_table_gemini.json"
    pt_path = root / rel
    if not pt_path.is_file():
        return 0
    try:
        rows = _loads_json_bytes(pt_path.read_bytes())
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        failures.append(f"{rel}: invalid JSON ({exc})")
        return 0
    if not isinstance(rows, list) or not rows:
        failures.append(f"{rel}: expected non-empty JSON list")
        return 0

    for idx, row in enumerate(rows):
        if not isinstance(row, dict):
            failures.append(f"{rel}: row[{idx}] is not an object")
            continue
        grp = row.get("group")
        if not isinstance(grp, str) or not grp.strip():
            failures.append(f"{rel}: row[{idx}] missing valid 'group'")
        elif not (root / "data" / "runs" / "committed" / grp).is_dir():
            failures.append(f"{rel}: row[{idx}] group directory data/runs/committed/{grp} missing")
        label = row.get("label")
        if isinstance(label, str):
            for m_sha in PAIRED_LABEL_COMMIT_RX.finditer(label):
                cand = m_sha.group(1).lower()
                if any(ch in "abcdef" for ch in cand) or len(cand) >= 7:
                    merged_shas.append((rel, cand))

    return len(rows)


def check_results_artifact_provenance(
    root: Path = ROOT,
    *,
    inspector: GitCommitInspector | None = None,
) -> CheckResult:
    name = CHECK_RESULTS_ARTIFACTS
    root_resolved = Path(root).resolve()
    git_inspector = inspector if inspector is not None else GitCommitInspector(root_resolved)
    failures: list[str] = []
    merged_shas: list[tuple[str, str]] = []
    external_shas: list[tuple[str, str]] = []

    n_jt = _audit_judge_table_provenance(root_resolved, failures, merged_shas)
    n_fa = _audit_failure_analysis_provenance(root_resolved, failures)
    n_or = _audit_oracle_range_provenance(root_resolved, failures)
    n_sr = _audit_solver_range_provenance(root_resolved, failures)
    n_lad_rows, n_lad_eps = _audit_gemini_ladder_provenance(root_resolved, failures, external_shas)
    n_reh_rows = _audit_harbor_rehearsal_provenance(root_resolved, failures, merged_shas, external_shas)
    n_rt_commits, n_rt_att = _audit_redteam_1000_provenance(
        root_resolved,
        failures,
        merged_shas,
        external_shas,
    )
    _audit_paired_table_provenance(root_resolved, failures, merged_shas)

    if git_inspector.has_git and (merged_shas or external_shas):
        all_req = {s for _, s in merged_shas} | {s for _, s in external_shas}
        resolved = git_inspector.resolve_shas(all_req)
        if not all(info[0] == "error" for info in resolved.values()):
            for loc, sha_val in merged_shas:
                obj_type, _ = resolved.get(sha_val, ("missing", ""))
                if obj_type == "missing":
                    if not git_inspector.is_shallow:
                        failures.append(f"{loc}: commit SHA {sha_val!r} does not exist in .git")
                elif obj_type != "commit":
                    failures.append(f"{loc}: SHA {sha_val!r} resolves to {obj_type!r}, expected 'commit'")
            for loc, sha_val in external_shas:
                obj_type, _ = resolved.get(sha_val, ("missing", ""))
                if obj_type not in {"commit", "missing"}:
                    failures.append(f"{loc}: SHA {sha_val!r} resolves to {obj_type!r}, expected 'commit'")

    if failures:
        return CheckResult(
            name,
            "FAIL",
            f"{len(failures)} results artifact provenance violation(s)",
            failures,
        )

    return CheckResult(
        name,
        "PASS",
        f"judge_table ({n_jt} reported notes), failure_analysis (n={n_fa}), "
        f"oracle_range ({n_or} rows), solver_range ({n_sr} files), "
        f"gemini/ladder ({n_lad_rows} rows, {n_lad_eps} episodes), "
        f"harbor/rehearsal ({n_reh_rows} rows), redteam_1000 ({n_rt_commits} commits, {n_rt_att} attacks) verified",
    )


@lru_cache(maxsize=1)
def _canary_rules_tier_hashes() -> frozenset[str]:
    computed: set[str] = set()
    try:
        from canary import rules as canary_rules

        current_obj = {
            "tiers": {k: v.to_dict() for k, v in canary_rules.TIERS.items()},
            "known_v_mode": canary_rules.KNOWN_V_MODE,
        }
        computed.add(
            hashlib.sha256(json.dumps(current_obj, sort_keys=True, default=list).encode("utf-8")).hexdigest()[:16]
        )
        history = getattr(canary_rules, "TIERS_HISTORY", {})
        if isinstance(history, dict):
            for hist_ver, hist_tiers in history.items():
                if isinstance(hist_tiers, dict):
                    known_v = hist_ver != "v1.2"
                    hist_obj = {
                        "tiers": {k: v.to_dict() for k, v in hist_tiers.items()},
                        "known_v_mode": known_v,
                    }
                    computed.add(
                        hashlib.sha256(
                            json.dumps(hist_obj, sort_keys=True, default=list).encode("utf-8")
                        ).hexdigest()[:16]
                    )
    except Exception:
        pass
    return frozenset(computed)


def known_non_commit_hex_tokens(root: Path | None = None) -> set[str]:
    tokens: set[str] = set(CANONICAL_FROZEN_TIER_HASHES) | set(DOCUMENTED_VERDA_INSTANCE_IDS)
    if root is None or (root / "canary" / "rules.py").is_file():
        tokens |= set(_canary_rules_tier_hashes())

    if root is not None:
        verda_readme = root / "fr8" / "verda" / "README.md"
        if verda_readme.is_file():
            try:
                verda_text = verda_readme.read_text(encoding="utf-8")
                for m_uuid in UUID_SPAN_RX.finditer(verda_text):
                    parts = m_uuid.group(0).lower().split("-")
                    tokens.add(parts[0])
                    tokens.add(parts[-1])
            except OSError:
                pass

        jt_file = root / "results" / "judge_table.md"
        if jt_file.is_file():
            try:
                jt_text = jt_file.read_text(encoding="utf-8")
                for m_fp in JUDGE_TABLE_HEADER_FP_RX.finditer(jt_text):
                    tokens.add(m_fp.group(1).lower())
            except OSError:
                pass

    return tokens


def documented_external_commit_shas(root: Path) -> set[str]:
    ext_shas: set[str] = set()
    reh_table = root / "results" / "harbor" / "rehearsal" / "TABLE.md"
    if reh_table.is_file():
        try:
            for raw_ln in reh_table.read_text(encoding="utf-8").splitlines():
                if EXTERNAL_BRANCH_CONTEXT_RX.search(raw_ln) is not None:
                    for m_note in HARBOR_REHEARSAL_COMMIT_NOTE_RX.finditer(raw_ln):
                        cand = m_note.group(1).strip().lower()
                        if _is_hex_sha(cand):
                            ext_shas.add(cand)
        except OSError:
            pass
    dry_readme = root / "results" / "harbor" / "rehearsal-dry" / "README.md"
    if dry_readme.is_file():
        try:
            for m_dry in DRY_REHEARSAL_CODE_SHA_RX.finditer(dry_readme.read_text(encoding="utf-8")):
                ext_shas.add(m_dry.group(1).strip().lower())
        except OSError:
            pass
    return ext_shas


def _clause_prefix_before(raw_line: str, start: int) -> str:
    head = raw_line[:start]
    clause_start = 0
    for sep in ("|", ";", ". "):
        idx = head.rfind(sep)
        if idx != -1:
            clause_start = max(clause_start, idx + len(sep))
    for reset_kw in (", git ", ", commit ", "(git ", "(commit "):
        idx = head.lower().rfind(reset_kw)
        if idx != -1 and idx >= clause_start:
            clause_start = idx + 1
    return raw_line[max(clause_start, start - 95) : start]


def _is_non_commit_span(
    raw_line: str,
    start: int,
    end: int,
    cand: str,
    non_commit_tokens: set[str],
    *,
    allow_instance_lookup: bool = True,
) -> bool:
    cand_l = cand.lower()
    if cand_l == "ed25519" or DATE_OR_ROUND_DEC_RX.fullmatch(cand_l):
        return True
    if cand_l in CANONICAL_FROZEN_TIER_HASHES:
        return True
    if allow_instance_lookup and cand_l in non_commit_tokens:
        return True
    for m_url in URL_SPAN_RX.finditer(raw_line):
        if m_url.start() <= start and end <= m_url.end():
            return True
    for m_uuid in UUID_SPAN_RX.finditer(raw_line):
        if m_uuid.start() <= start and end <= m_uuid.end():
            return True
    prefix = _clause_prefix_before(raw_line, start)
    if LOCAL_NON_COMMIT_PREFIX_RX.search(prefix) is not None:
        return True
    return False


def extract_doc_commit_citations(
    doc_rel: str,
    text: str,
    *,
    non_commit_tokens: set[str] | None = None,
) -> tuple[list[DocCommitCitation], list[str]]:
    known_non_commits = non_commit_tokens if non_commit_tokens is not None else known_non_commit_hex_tokens()
    citations: list[DocCommitCitation] = []
    malformed_errors: list[str] = []
    headers: list[str] | None = None
    in_fence = False
    fence_char = ""
    fence_len = 0

    for lineno, raw_line in enumerate(text.splitlines(), 1):
        stripped = raw_line.strip()
        m_fence = FENCE_OPEN_RX.match(raw_line) if ("`" in raw_line or "~" in raw_line) else None
        if not in_fence:
            if m_fence:
                marker = m_fence.group(1)
                in_fence = True
                fence_char = marker[0]
                fence_len = len(marker)
                headers = None
                continue
        else:
            if m_fence:
                marker = m_fence.group(1)
                if marker[0] == fence_char and len(marker) >= fence_len:
                    in_fence = False
                    fence_char = ""
                    fence_len = 0
            continue

        found_on_line: set[str] = set()
        ext_checked = False
        is_ext = False

        if stripped.startswith("|") and stripped.endswith("|"):
            cells = [c.strip() for c in stripped[1:-1].split("|")]
            if cells and all(TABLE_SEP_CELL_RX.match(c) for c in cells if c):
                pass
            elif headers is None:
                headers = [c.strip("`* ").lower() for c in cells]
            else:
                for col_name, raw_cell in zip(headers, cells):
                    if col_name not in {"commit", "git", "git_sha", "sha"}:
                        continue
                    clean_cell = raw_cell.strip("`* ")
                    if not clean_cell or clean_cell in {"-", "unknown", "none", "n/a"}:
                        continue
                    if _is_hex_sha(clean_cell):
                        sha_l = clean_cell.lower()
                        if sha_l not in found_on_line:
                            if not ext_checked:
                                is_ext = EXTERNAL_BRANCH_CONTEXT_RX.search(raw_line) is not None
                                ext_checked = True
                            found_on_line.add(sha_l)
                            citations.append(DocCommitCitation(doc_rel, lineno, sha_l, is_ext))
                    else:
                        malformed_errors.append(
                            f"{doc_rel}:{lineno}: malformed commit SHA {clean_cell!r} in '{col_name}' table column"
                        )
        else:
            headers = None

        if HEX7_FAST_RX.search(raw_line) is None:
            continue
        if not ext_checked:
            is_ext = EXTERNAL_BRANCH_CONTEXT_RX.search(raw_line) is not None

        for rx_idx, rx in enumerate(EXPLICIT_DOC_COMMIT_RXES):
            check_instance_ctx = rx_idx in {5, 6}
            for match in rx.finditer(raw_line):
                sha_l = match.group(1).lower()
                if sha_l in found_on_line:
                    continue
                if _is_non_commit_span(
                    raw_line,
                    match.start(1),
                    match.end(1),
                    sha_l,
                    known_non_commits,
                    allow_instance_lookup=check_instance_ctx,
                ):
                    continue
                found_on_line.add(sha_l)
                citations.append(DocCommitCitation(doc_rel, lineno, sha_l, is_ext))

        for match in BACKTICK_HEX_RX.finditer(raw_line):
            cand = match.group(1).lower()
            if cand in found_on_line:
                continue
            if _is_non_commit_span(
                raw_line,
                match.start(1),
                match.end(1),
                cand,
                known_non_commits,
                allow_instance_lookup=True,
            ):
                continue
            has_hex_alpha = any(ch in "abcdef" for ch in cand)
            if has_hex_alpha or cand.startswith("0") or len(cand) in {7, 8}:
                found_on_line.add(cand)
                citations.append(DocCommitCitation(doc_rel, lineno, cand, is_ext))

        if "(" in raw_line and ")" in raw_line:
            for p_match in PAREN_SPAN_RX.finditer(raw_line):
                inner = p_match.group(1)
                if HEX7_FAST_RX.search(inner) is None:
                    continue
                base_offset = p_match.start(1)
                for h_match in PAREN_HEX_TOKEN_RX.finditer(inner):
                    cand = h_match.group(1).lower()
                    if cand in found_on_line:
                        continue
                    abs_start = base_offset + h_match.start(1)
                    abs_end = base_offset + h_match.end(1)
                    if _is_non_commit_span(
                        raw_line,
                        abs_start,
                        abs_end,
                        cand,
                        known_non_commits,
                        allow_instance_lookup=True,
                    ):
                        continue
                    has_hex_alpha = any(ch in "abcdef" for ch in cand)
                    if has_hex_alpha or cand.startswith("0") or len(cand) in {7, 8}:
                        found_on_line.add(cand)
                        citations.append(DocCommitCitation(doc_rel, lineno, cand, is_ext))

    return citations, malformed_errors


def check_doc_commit_references(
    root: Path = ROOT,
    *,
    docs: Sequence[str] = TARGET_DOC_RELS,
    inspector: GitCommitInspector | None = None,
) -> CheckResult:
    name = CHECK_DOC_SHAS
    root_resolved = Path(root).resolve()
    git_inspector = inspector if inspector is not None else GitCommitInspector(root_resolved)
    non_commit_tokens = known_non_commit_hex_tokens(root_resolved)

    present_docs: list[str] = []
    all_citations: list[DocCommitCitation] = []
    failures: list[str] = []

    for doc_rel in docs:
        doc_path = root_resolved / doc_rel
        if not doc_path.is_file():
            continue
        present_docs.append(doc_rel)
        try:
            text = doc_path.read_text(encoding="utf-8")
        except OSError as exc:
            failures.append(f"{doc_rel}: unreadable documentation file ({exc})")
            continue
        doc_citations, malformed_errs = extract_doc_commit_citations(
            doc_rel,
            text,
            non_commit_tokens=non_commit_tokens,
        )
        all_citations.extend(doc_citations)
        failures.extend(malformed_errs)

    if not present_docs:
        return CheckResult(
            name,
            "FAIL",
            f"none of the target docs exist under {root_resolved}",
            list(docs),
        )

    distinct_shas = sorted({c.sha for c in all_citations})

    if not git_inspector.has_git:
        if failures:
            return CheckResult(
                name,
                "FAIL",
                f"gitless fallback (.git absent): {len(failures)} malformed commit SHA reference(s) across {len(present_docs)} doc(s)",
                failures,
            )
        if not all_citations:
            return CheckResult(
                name,
                "PASS",
                f"gitless fallback (.git absent): scanned {len(present_docs)} doc(s), 0 commit SHA citations",
            )
        advisory = [
            f"{c.doc}:{c.line}: gitless fallback verified hex format for '{c.sha}' (git cat-file skipped)"
            for c in all_citations
        ]
        return CheckResult(
            name,
            "WARN",
            f"gitless fallback (.git absent): verified {len(all_citations)} well-formed hex citation(s) "
            f"({len(distinct_shas)} distinct) across {len(present_docs)} doc(s); git object lookup skipped",
            advisory,
        )

    resolved_map = git_inspector.resolve_shas(distinct_shas)
    if distinct_shas and all(resolved_map.get(s, ("error", ""))[0] == "error" for s in distinct_shas):
        if failures:
            return CheckResult(
                name,
                "FAIL",
                f"git unavailable fallback: {len(failures)} malformed commit SHA reference(s) across {len(present_docs)} doc(s)",
                failures,
            )
        advisory_err = [
            f"{c.doc}:{c.line}: git unavailable fallback verified hex format for '{c.sha}'"
            for c in all_citations
        ]
        return CheckResult(
            name,
            "WARN",
            f"git unavailable fallback: verified {len(all_citations)} well-formed hex citation(s) "
            f"({len(distinct_shas)} distinct) across {len(present_docs)} doc(s)",
            advisory_err,
        )

    head_set = git_inspector.head_commits()
    doc_ext_shas = documented_external_commit_shas(root_resolved)
    warnings: list[str] = []
    verified_count = 0
    shallow_omitted = 0

    for cit in all_citations:
        obj_type, full_sha = resolved_map.get(cit.sha, ("missing", ""))
        loc = f"{cit.doc}:{cit.line}"
        known_ext = cit.external_branch or any(
            cit.sha.startswith(ext_s) or ext_s.startswith(cit.sha) for ext_s in doc_ext_shas
        )
        if obj_type == "missing":
            if known_ext:
                warnings.append(
                    f"{loc}: external-branch/unmerged commit SHA '{cit.sha}' is not fetched in local .git"
                )
            elif git_inspector.is_shallow:
                shallow_omitted += 1
                warnings.append(
                    f"{loc}: shallow .git clone omits historical commit SHA '{cit.sha}'"
                )
            else:
                failures.append(
                    f"{loc}: cited commit SHA '{cit.sha}' does not exist in .git (git cat-file missing)"
                )
        elif obj_type == "ambiguous":
            failures.append(f"{loc}: cited short SHA '{cit.sha}' is ambiguous in .git")
        elif obj_type != "commit":
            failures.append(
                f"{loc}: cited SHA '{cit.sha}' resolves to git {obj_type!r}, expected 'commit'"
            )
        else:
            is_merged = (head_set is not None) and (full_sha in head_set)
            if head_set is None:
                if known_ext:
                    warnings.append(
                        f"{loc}: commit SHA '{cit.sha}' ({full_sha[:12]}) resolves to valid commit on external/unmerged branch"
                    )
                else:
                    verified_count += 1
            elif not is_merged:
                warnings.append(
                    f"{loc}: commit SHA '{cit.sha}' ({full_sha[:12]}) resolves to valid commit on external/unmerged branch"
                )
            else:
                verified_count += 1

    if failures:
        return CheckResult(
            name,
            "FAIL",
            f"{len(failures)} invalid/missing commit SHA citation(s) across {len(present_docs)} doc(s)",
            failures + warnings,
        )
    if warnings:
        warn_kind = (
            "shallow/external commit warning(s)"
            if shallow_omitted > 0
            else "external-branch/unmerged commit warning(s)"
        )
        return CheckResult(
            name,
            "WARN",
            f"verified {verified_count} merged commit citation(s) across {len(present_docs)} doc(s); "
            f"{len(warnings)} {warn_kind}",
            warnings,
        )
    return CheckResult(
        name,
        "PASS",
        f"verified {verified_count} commit SHA citation(s) ({len(distinct_shas)} distinct) across {len(present_docs)} doc(s)",
    )


def verify_repo(
    root: Path = ROOT,
    *,
    docs: Sequence[str] = TARGET_DOC_RELS,
) -> list[CheckResult]:
    resolved = Path(root).resolve()
    inspector = GitCommitInspector(resolved)
    return [
        check_committed_run_provenance(resolved, inspector=inspector),
        check_results_artifact_provenance(resolved, inspector=inspector),
        check_doc_commit_references(resolved, docs=docs, inspector=inspector),
    ]


verify_commit_provenance = verify_repo
audit_repo = verify_repo


def format_report(results: Sequence[CheckResult], elapsed_s: float) -> str:
    lines: list[str] = []
    counts = {"PASS": 0, "WARN": 0, "FAIL": 0}
    for r in results:
        counts[r.status] = counts.get(r.status, 0) + 1
        lines.append(f"[{r.status}] {r.name}: {r.summary}")
        for detail in r.details:
            lines.append(f"       - {detail}")
    lines.append(
        f"SUMMARY: {counts['PASS']} PASS, {counts['WARN']} WARN, {counts['FAIL']} FAIL ({elapsed_s:.2f}s)"
    )
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Keyless provenance audit for Canary committed runs, results artifacts, and doc commit SHAs."
    )
    ap.add_argument("--root", type=Path, default=ROOT, help="Repository root to verify")
    ap.add_argument("--json", action="store_true", help="Emit JSON report")
    args = ap.parse_args(list(argv) if argv is not None else None)

    t0 = time.monotonic()
    results = verify_repo(root=args.root.resolve())
    elapsed = time.monotonic() - t0
    passed = not any(r.status == "FAIL" for r in results)

    if args.json:
        items: list[dict[str, Any]] = [asdict(r) for r in results]
        payload = {
            "results": items,
            "checks": items,
            "elapsed_s": round(elapsed, 4),
            "passed": passed,
        }
        print(json.dumps(payload, indent=2))
    else:
        print(format_report(results, elapsed))

    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
