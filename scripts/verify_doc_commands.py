"""Verify Makefile targets, script/module paths, CLI flags, and Harbor commands across judge-facing docs.

    python scripts/verify_doc_commands.py [--root .] [--json]

Scans judge-facing Markdown files for fenced shell code blocks and inline backtick
command spans, then runs four fast keyless checks:
  1. Makefile Targets Check: every documented `make <target>` exists in Makefile.
  2. Script & Module Paths Check: every `scripts/*.py`, `harbor/*.py`, `game/*.py`,
     and `python -m canary.<mod>` resolves to an existing file on disk.
  3. CLI Long-Flag Check: every `--long-flag` passed to `scripts/*.py`, `harbor/*.py`,
     `game/*.py`, or `python -m canary.<mod>` is supported by that CLI's argparse options.
  4. Harbor CLI & Env-Var Check: every `harbor run` snippet avoids `--ae CANARY_*=...`,
     forwards `GOOGLE_GENERATIVE_AI_API_KEY` on `-a opencode -m google/...`, and uses
     only valid `ORACLE_POLICY` values.
"""
from __future__ import annotations

import argparse
import ast
import fnmatch
import json
import os
import re
import shlex
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Sequence

ROOT = Path(__file__).resolve().parents[1]
HASH_CHAR = chr(35)
PLACEHOLDER_TOKEN = "__DOC_PLACEHOLDER__"

DEFAULT_DOCS: tuple[str, ...] = (
    "README.md",
    "JUDGE_QUICKSTART.md",
    "docs/JUDGE-WALKTHROUGH.md",
    "docs/REPRODUCIBILITY.md",
    "docs/PEER-REVIEW-QA.md",
    "docs/DEMO.md",
    "docs/EXPLOITS.md",
    "docs/DIFFICULTY.md",
    "docs/HISTORY.md",
    "docs/reports/gap.md",
    "docs/reports/failure_analysis_v1.4.md",
    "docs/reports/reference_optimality.md",
    "harbor/README.md",
)

FLAG_CHECK_DOCS: frozenset[str] = frozenset(DEFAULT_DOCS)

PLANNING_BRIEF_PATTERNS: tuple[str, ...] = (
    "docs/agents/*.md",
    "docs/gemini/sessions/*.md",
    "docs/PLAN*.md",
    "docs/gemini/PLAN.md",
)

VALID_HARBOR_ORACLE_POLICIES: frozenset[str] = frozenset({
    "solver",
    "do_nothing",
    "stop_early",
    "guess_day1",
    "cheat_probe",
    "cheat",
})

SHELL_FENCE_LANGS: frozenset[str] = frozenset({
    "",
    "bash",
    "sh",
    "shell",
    "zsh",
    "console",
})

NON_SHELL_FENCE_LANGS: frozenset[str] = frozenset({
    "json",
    "jsonl",
    "toml",
    "yaml",
    "yml",
    "python",
    "py",
    "html",
    "xml",
    "css",
    "js",
    "ts",
    "sql",
    "diff",
    "markdown",
    "md",
    "text",
    "txt",
})

ENV_ASSIGN_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=.*$")
MAKE_TARGET_TOKEN_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_-]*$")
MAKEFILE_RULE_RE = re.compile(r"^([A-Za-z0-9_-]+)\s*:(?!=)")
SCRIPT_PATH_RE = re.compile(r"^(?:scripts|harbor|game)/[A-Za-z0-9_./-]+\.py$")
LONG_FLAG_RE = re.compile(r"^--[A-Za-z0-9][A-Za-z0-9_-]*$")
HELP_LONG_FLAG_RE = re.compile(r"--[A-Za-z0-9][A-Za-z0-9_-]*")
ANGLE_PLACEHOLDER_RE = re.compile(r"<[A-Za-z0-9_./-][^>\n]{0,80}>")
UNICODE_PLACEHOLDER_RE = re.compile(r"\u27e8[^\u27e9\n]{1,120}\u27e9")
EXTERNAL_BRANCH_RE = re.compile(r"\bon\s+branch\s+`?([A-Za-z0-9_./-]+)`?", re.IGNORECASE)
INLINE_CODE_RE = re.compile(r"(`+)([^`]+?)\1")

UV_RUN_VALUE_FLAGS: frozenset[str] = frozenset({
    "--python",
    "-p",
    "--extra",
    "--group",
    "--with",
    "--directory",
    "--project",
    "--env-file",
})

UV_RUN_BOOL_FLAGS: frozenset[str] = frozenset({
    "--all-extras",
    "--no-sync",
    "--frozen",
    "--locked",
    "--isolated",
    "--quiet",
    "-q",
    "--no-project",
    "--no-dev",
})

MAKE_TWO_ARG_FLAGS: frozenset[str] = frozenset({"-C", "-f", "--directory", "--file", "--makefile"})
SHELL_CONTROL_PREFIXES: frozenset[str] = frozenset({"do", "then", "else", "elif", "time"})
PROSE_STOP_TOKENS: frozenset[str] = frozenset({"->", "\u2192", "=>"})
CURRENT_BRANCH_NAMES: frozenset[str] = frozenset({"justsilas", "afterquery-final"})


@dataclass
class CheckResult:
    name: str
    status: str
    summary: str
    details: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class DocSnippet:
    doc: str
    line: int
    text: str
    kind: str
    raw_line: str
    heading: str


@dataclass(frozen=True)
class MakeInvocation:
    doc: str
    line: int
    target: str
    superseded: bool


@dataclass(frozen=True)
class TargetInvocation:
    doc: str
    line: int
    kind: str
    display: str
    rel_candidates: tuple[str, ...]
    module_name: str | None
    long_flags: tuple[str, ...]
    external_branch: str | None
    superseded: bool


@dataclass(frozen=True)
class HarborInvocation:
    doc: str
    line: int
    agent: str | None
    model: str | None
    agent_envs: tuple[str, ...]
    api_key_names: tuple[str, ...]
    superseded: bool


def _strip_shell_comment(line: str) -> str:
    in_single = False
    in_double = False
    escaped = False
    for idx, ch in enumerate(line):
        if escaped:
            escaped = False
            continue
        if ch == "\\" and not in_single:
            escaped = True
            continue
        if ch == "'" and not in_double:
            in_single = not in_single
            continue
        if ch == '"' and not in_single:
            in_double = not in_double
            continue
        if ch == HASH_CHAR and not in_single and not in_double:
            if idx == 0 or line[idx - 1].isspace():
                return line[:idx].rstrip()
    return line.rstrip()


def parse_makefile_targets(makefile_path: Path) -> set[str]:
    targets: set[str] = set()
    raw_lines = makefile_path.read_text(encoding="utf-8").splitlines()
    logical_lines: list[str] = []
    buf = ""
    for raw in raw_lines:
        if raw.startswith("\t") and not buf:
            continue
        no_comment = raw.split(HASH_CHAR, 1)[0].rstrip()
        if not no_comment:
            if buf:
                logical_lines.append(buf)
                buf = ""
            continue
        if no_comment.endswith("\\"):
            buf += no_comment[:-1].rstrip() + " "
        else:
            buf += no_comment
            logical_lines.append(buf)
            buf = ""
    if buf:
        logical_lines.append(buf)

    for line in logical_lines:
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith(".PHONY:"):
            rest = stripped.split(":", 1)[1]
            for tok in rest.split():
                if MAKE_TARGET_TOKEN_RE.fullmatch(tok):
                    targets.add(tok)
            continue
        m = MAKEFILE_RULE_RE.match(stripped)
        if m:
            targets.add(m.group(1))
    return targets


def _join_fenced_lines(lines: list[tuple[int, str]]) -> list[tuple[int, str]]:
    out: list[tuple[int, str]] = []
    cur_line = 0
    buf = ""
    for lineno, raw in lines:
        cleaned = _strip_shell_comment(raw)
        if not cleaned.strip():
            if buf.strip():
                out.append((cur_line, buf.strip()))
                buf = ""
            continue
        if not buf:
            cur_line = lineno
        if cleaned.endswith("\\"):
            buf += cleaned[:-1].rstrip() + " "
        else:
            buf += cleaned.strip()
            out.append((cur_line, buf.strip()))
            buf = ""
    if buf.strip():
        out.append((cur_line, buf.strip()))
    return out


def _is_planning_brief(doc_rel: str) -> bool:
    norm = doc_rel.replace("\\", "/").lstrip("./")
    return any(fnmatch.fnmatch(norm, pat) for pat in PLANNING_BRIEF_PATTERNS)


def extract_doc_snippets(root: Path, doc_rel: str) -> list[DocSnippet]:
    path = root / doc_rel
    if not path.is_file():
        return []
    is_brief = _is_planning_brief(doc_rel)
    raw_lines = path.read_text(encoding="utf-8").splitlines()
    snippets: list[DocSnippet] = []
    in_fence = False
    fence_marker = ""
    fence_lang = ""
    fence_buf: list[tuple[int, str]] = []
    headings: dict[int, str] = {}

    for lineno, raw_line in enumerate(raw_lines, 1):
        stripped = raw_line.strip()
        if not in_fence:
            if stripped.startswith("```") or stripped.startswith("~~~"):
                marker_char = stripped[0]
                m_fence = re.match(rf"^({re.escape(marker_char)}{{3,}})(.*)$", stripped)
                if m_fence:
                    in_fence = True
                    fence_marker = m_fence.group(1)
                    info = m_fence.group(2).strip().split()
                    fence_lang = info[0].lower() if info else ""
                    fence_buf = []
                    continue

            if stripped.startswith(HASH_CHAR):
                hashes = len(stripped) - len(stripped.lstrip(HASH_CHAR))
                if 1 <= hashes <= 6 and (len(stripped) == hashes or stripped[hashes].isspace()):
                    title = stripped[hashes:].strip()
                    for lvl in list(headings):
                        if lvl >= hashes:
                            del headings[lvl]
                    headings[hashes] = title

            active_heading = " > ".join(headings[k] for k in sorted(headings))
            is_table_row = stripped.startswith("|")
            for match in INLINE_CODE_RE.finditer(raw_line):
                span = match.group(2).strip()
                if not span:
                    continue
                if is_table_row:
                    span = span.replace(r"\|", "|")
                snippets.append(
                    DocSnippet(
                        doc=doc_rel,
                        line=lineno,
                        text=span,
                        kind="inline",
                        raw_line=raw_line,
                        heading=active_heading,
                    )
                )
        else:
            if stripped.startswith(fence_marker) and stripped.strip(fence_marker[0]) == "":
                allow_shell_fence = (
                    fence_lang in SHELL_FENCE_LANGS
                    and fence_lang not in NON_SHELL_FENCE_LANGS
                    and not (is_brief and fence_lang == "")
                )
                if allow_shell_fence:
                    active_heading = " > ".join(headings[k] for k in sorted(headings))
                    for logical_lineno, logical_text in _join_fenced_lines(fence_buf):
                        snippets.append(
                            DocSnippet(
                                doc=doc_rel,
                                line=logical_lineno,
                                text=logical_text,
                                kind="fence",
                                raw_line=logical_text,
                                heading=active_heading,
                            )
                        )
                in_fence = False
                fence_marker = ""
                fence_lang = ""
                fence_buf = []
            else:
                fence_buf.append((lineno, raw_line))

    return snippets


def _normalize_placeholders(text: str) -> str:
    text = ANGLE_PLACEHOLDER_RE.sub(PLACEHOLDER_TOKEN, text)
    text = UNICODE_PLACEHOLDER_RE.sub(PLACEHOLDER_TOKEN, text)
    return text


def _split_command_segments(command_line: str) -> list[str]:
    segments: list[str] = []
    cur: list[str] = []
    in_single = False
    in_double = False
    escaped = False
    i = 0
    n = len(command_line)
    while i < n:
        ch = command_line[i]
        if escaped:
            cur.append(ch)
            escaped = False
            i += 1
            continue
        if ch == "\\" and not in_single:
            cur.append(ch)
            escaped = True
            i += 1
            continue
        if ch == "'" and not in_double:
            in_single = not in_single
            cur.append(ch)
            i += 1
            continue
        if ch == '"' and not in_single:
            in_double = not in_double
            cur.append(ch)
            i += 1
            continue
        if not in_single and not in_double:
            if command_line.startswith("&&", i) or command_line.startswith("||", i):
                seg = "".join(cur).strip()
                if seg:
                    segments.append(seg)
                cur = []
                i += 2
                continue
            if ch == ";":
                seg = "".join(cur).strip()
                if seg:
                    segments.append(seg)
                cur = []
                i += 1
                continue
            if ch == "|":
                prev_ws = i > 0 and command_line[i - 1].isspace()
                next_ws = (i + 1 < n) and command_line[i + 1].isspace()
                if prev_ws and next_ws:
                    seg = "".join(cur).strip()
                    if seg:
                        segments.append(seg)
                    cur = []
                    i += 1
                    continue
        cur.append(ch)
        i += 1
    tail = "".join(cur).strip()
    if tail:
        segments.append(tail)
    return segments


def _tokenize_segment(segment: str) -> list[str]:
    s = segment.strip()
    if s.startswith("$ "):
        s = s[2:].strip()
    s = _normalize_placeholders(s)
    try:
        return shlex.split(s, posix=True)
    except ValueError:
        return s.split()


def _extract_long_flags(arg_tokens: Sequence[str]) -> tuple[tuple[str, ...], list[str]]:
    flags: list[str] = []
    seen: set[str] = set()
    passthrough: list[str] = []
    for idx, raw_tok in enumerate(arg_tokens):
        if raw_tok == "--":
            passthrough = list(arg_tokens[idx + 1 :])
            break
        if raw_tok in PROSE_STOP_TOKENS or raw_tok.startswith("("):
            break
        cleaned = raw_tok.lstrip("[").rstrip("],;:")
        if not cleaned.startswith("--") or len(cleaned) <= 2:
            continue
        opt = cleaned.split("=", 1)[0]
        if PLACEHOLDER_TOKEN in opt:
            continue
        if LONG_FLAG_RE.fullmatch(opt) and opt not in seen:
            seen.add(opt)
            flags.append(opt)
    return tuple(flags), passthrough


def _is_placeholder_or_glob(val: str) -> bool:
    return (
        PLACEHOLDER_TOKEN in val
        or "$" in val
        or "*" in val
        or "?" in val
        or "{" in val
        or "}" in val
    )


def _expand_module_specs(mod_spec: str) -> list[str]:
    cleaned = mod_spec.strip("`'\",;:")
    if "|" not in cleaned:
        return [cleaned]
    pkg, sep, tail = cleaned.rpartition(".")
    parts = [p for p in tail.split("|") if p]
    if not sep:
        return parts
    return [f"{pkg}.{p}" for p in parts]


def _module_rel_candidates(mod_name: str) -> tuple[str, ...]:
    rel = "/".join(mod_name.split("."))
    return (f"{rel}.py", f"{rel}/__main__.py")


def _detect_external_branch(snippet: DocSnippet) -> str | None:
    for hay in (snippet.raw_line, snippet.heading):
        m = EXTERNAL_BRANCH_RE.search(hay)
        if m:
            branch = m.group(1).strip()
            if branch.lower() not in CURRENT_BRANCH_NAMES and not branch.lower().startswith("fr8/"):
                return branch
    return None


def _is_superseded(snippet: DocSnippet) -> bool:
    return "superseded" in snippet.heading.lower() or _is_planning_brief(snippet.doc)


def _skip_command_prefixes(tokens: Sequence[str]) -> int:
    idx = 0
    n = len(tokens)
    while idx < n:
        tok = tokens[idx]
        if tok in SHELL_CONTROL_PREFIXES:
            idx += 1
            continue
        if ENV_ASSIGN_RE.match(tok):
            idx += 1
            continue
        if tok == "env":
            idx += 1
            while idx < n:
                etok = tokens[idx]
                if etok in {"-u", "--unset"} and idx + 1 < n:
                    idx += 2
                    continue
                if etok.startswith("-") or ENV_ASSIGN_RE.match(etok):
                    idx += 1
                    continue
                break
            continue
        break
    return idx


def _skip_uv_run(tokens: Sequence[str], idx: int) -> int:
    n = len(tokens)
    if idx + 1 >= n or tokens[idx] != "uv" or tokens[idx + 1] != "run":
        return idx
    idx += 2
    while idx < n:
        tok = tokens[idx]
        if tok == "--":
            return idx + 1
        if tok in UV_RUN_VALUE_FLAGS:
            idx += 2
            continue
        if any(tok.startswith(f"{vf}=") for vf in UV_RUN_VALUE_FLAGS):
            idx += 1
            continue
        if tok in UV_RUN_BOOL_FLAGS:
            idx += 1
            continue
        break
    return idx


def _skip_uv_tool_or_uvx(tokens: Sequence[str], idx: int) -> int:
    n = len(tokens)
    if idx + 2 < n and tokens[idx] == "uv" and tokens[idx + 1] == "tool" and tokens[idx + 2] == "run":
        idx += 3
        while idx < n and tokens[idx].startswith("-"):
            if tokens[idx] == "--":
                return idx + 1
            idx += 1
        return idx
    if idx + 1 < n and tokens[idx] == "uvx":
        idx += 1
        while idx < n and tokens[idx].startswith("-"):
            if tokens[idx] == "--":
                return idx + 1
            idx += 1
        return idx
    return idx


def _parse_harbor_run_args(
    arg_tokens: Sequence[str],
    snippet: DocSnippet,
    superseded: bool,
) -> HarborInvocation:
    agent: str | None = None
    model: str | None = None
    agent_envs: list[str] = []
    api_key_names: list[str] = []
    k = 0
    n = len(arg_tokens)
    while k < n:
        raw_tok = arg_tokens[k]
        if raw_tok == "--":
            break
        if raw_tok in PROSE_STOP_TOKENS or raw_tok.startswith("("):
            break
        tok = raw_tok.rstrip(",;:")
        if tok in {"-a", "--agent"} and k + 1 < n:
            agent = arg_tokens[k + 1].rstrip(",;:")
            k += 2
            continue
        if tok.startswith("-a=") or tok.startswith("--agent="):
            agent = tok.split("=", 1)[1]
            k += 1
            continue
        if tok in {"-m", "--model"} and k + 1 < n:
            model = arg_tokens[k + 1].rstrip(",;:")
            k += 2
            continue
        if tok.startswith("-m=") or tok.startswith("--model="):
            model = tok.split("=", 1)[1]
            k += 1
            continue
        if tok in {"--ae", "--agent-env"} and k + 1 < n:
            agent_envs.append(arg_tokens[k + 1].rstrip(",;:"))
            k += 2
            continue
        if tok.startswith("--ae=") or tok.startswith("--agent-env="):
            agent_envs.append(tok.split("=", 1)[1])
            k += 1
            continue
        if tok == "--api-key-name" and k + 1 < n:
            api_key_names.append(arg_tokens[k + 1].rstrip(",;:"))
            k += 2
            continue
        if tok.startswith("--api-key-name="):
            api_key_names.append(tok.split("=", 1)[1])
            k += 1
            continue
        k += 1
    return HarborInvocation(
        doc=snippet.doc,
        line=snippet.line,
        agent=agent,
        model=model,
        agent_envs=tuple(agent_envs),
        api_key_names=tuple(api_key_names),
        superseded=superseded,
    )


def _parse_tokens_invocations(
    tokens: Sequence[str],
    snippet: DocSnippet,
) -> tuple[list[MakeInvocation], list[TargetInvocation], list[HarborInvocation]]:
    make_invocations: list[MakeInvocation] = []
    target_invocations: list[TargetInvocation] = []
    harbor_invocations: list[HarborInvocation] = []
    if not tokens:
        return make_invocations, target_invocations, harbor_invocations

    superseded = _is_superseded(snippet)
    ext_branch = _detect_external_branch(snippet)

    idx = _skip_command_prefixes(tokens)
    if idx >= len(tokens):
        return make_invocations, target_invocations, harbor_invocations

    idx = _skip_uv_run(tokens, idx)
    if idx >= len(tokens):
        return make_invocations, target_invocations, harbor_invocations

    idx = _skip_uv_tool_or_uvx(tokens, idx)
    if idx >= len(tokens):
        return make_invocations, target_invocations, harbor_invocations

    cmd = tokens[idx]

    if Path(cmd).name == "harbor" and idx + 1 < len(tokens) and tokens[idx + 1] == "run":
        harbor_invocations.append(_parse_harbor_run_args(tokens[idx + 2 :], snippet, superseded))
        return make_invocations, target_invocations, harbor_invocations

    if cmd == "make":
        j = idx + 1
        while j < len(tokens):
            mtok = tokens[j]
            if mtok in PROSE_STOP_TOKENS or mtok.startswith("("):
                break
            if mtok in MAKE_TWO_ARG_FLAGS:
                j += 2
                continue
            if mtok.startswith("-"):
                j += 1
                continue
            if "=" in mtok:
                j += 1
                continue
            if _is_placeholder_or_glob(mtok):
                j += 1
                continue
            if MAKE_TARGET_TOKEN_RE.fullmatch(mtok):
                make_invocations.append(
                    MakeInvocation(
                        doc=snippet.doc,
                        line=snippet.line,
                        target=mtok,
                        superseded=superseded,
                    )
                )
            j += 1
        return make_invocations, target_invocations, harbor_invocations

    py_name = Path(cmd).name
    if py_name in {"python", "python3"}:
        j = idx + 1
        while j < len(tokens) and tokens[j].startswith("-") and tokens[j] not in {"-m", "-c", "-"}:
            j += 1
        if j >= len(tokens):
            return make_invocations, target_invocations, harbor_invocations
        if tokens[j] == "-m":
            if j + 1 >= len(tokens):
                return make_invocations, target_invocations, harbor_invocations
            mod_spec = tokens[j + 1]
            flags, passthrough = _extract_long_flags(tokens[j + 2 :])
            for mod_name in _expand_module_specs(mod_spec):
                if _is_placeholder_or_glob(mod_name):
                    continue
                if mod_name == "canary" or mod_name.startswith("canary."):
                    target_invocations.append(
                        TargetInvocation(
                            doc=snippet.doc,
                            line=snippet.line,
                            kind="module",
                            display=f"python -m {mod_name}",
                            rel_candidates=_module_rel_candidates(mod_name),
                            module_name=mod_name,
                            long_flags=flags,
                            external_branch=ext_branch,
                            superseded=superseded,
                        )
                    )
            if passthrough:
                sub_m, sub_t, sub_h = _parse_tokens_invocations(passthrough, snippet)
                make_invocations.extend(sub_m)
                target_invocations.extend(sub_t)
                harbor_invocations.extend(sub_h)
            return make_invocations, target_invocations, harbor_invocations

        script_tok = tokens[j]
        if not _is_placeholder_or_glob(script_tok) and SCRIPT_PATH_RE.fullmatch(script_tok):
            flags, passthrough = _extract_long_flags(tokens[j + 1 :])
            target_invocations.append(
                TargetInvocation(
                    doc=snippet.doc,
                    line=snippet.line,
                    kind="script",
                    display=script_tok,
                    rel_candidates=(script_tok,),
                    module_name=None,
                    long_flags=flags,
                    external_branch=ext_branch,
                    superseded=superseded,
                )
            )
            if passthrough:
                sub_m, sub_t, sub_h = _parse_tokens_invocations(passthrough, snippet)
                make_invocations.extend(sub_m)
                target_invocations.extend(sub_t)
                harbor_invocations.extend(sub_h)
        return make_invocations, target_invocations, harbor_invocations

    if not _is_placeholder_or_glob(cmd) and SCRIPT_PATH_RE.fullmatch(cmd):
        flags, passthrough = _extract_long_flags(tokens[idx + 1 :])
        target_invocations.append(
            TargetInvocation(
                doc=snippet.doc,
                line=snippet.line,
                kind="script",
                display=cmd,
                rel_candidates=(cmd,),
                module_name=None,
                long_flags=flags,
                external_branch=ext_branch,
                superseded=superseded,
            )
        )
        if passthrough:
            sub_m, sub_t, sub_h = _parse_tokens_invocations(passthrough, snippet)
            make_invocations.extend(sub_m)
            target_invocations.extend(sub_t)
            harbor_invocations.extend(sub_h)
        return make_invocations, target_invocations, harbor_invocations

    if snippet.kind == "inline" and cmd == "build.py" and len(tokens) > idx + 1:
        flags, _ = _extract_long_flags(tokens[idx + 1 :])
        if flags:
            target_invocations.append(
                TargetInvocation(
                    doc=snippet.doc,
                    line=snippet.line,
                    kind="script",
                    display="harbor/build.py",
                    rel_candidates=("harbor/build.py",),
                    module_name=None,
                    long_flags=flags,
                    external_branch=ext_branch,
                    superseded=superseded,
                )
            )

    if snippet.kind == "inline" and cmd == "fuzz" and len(tokens) > idx + 1:
        flags, _ = _extract_long_flags(tokens[idx + 1 :])
        if flags:
            target_invocations.append(
                TargetInvocation(
                    doc=snippet.doc,
                    line=snippet.line,
                    kind="module",
                    display="python -m canary.redteam.fuzz",
                    rel_candidates=_module_rel_candidates("canary.redteam.fuzz"),
                    module_name="canary.redteam.fuzz",
                    long_flags=flags,
                    external_branch=ext_branch,
                    superseded=superseded,
                )
            )

    return make_invocations, target_invocations, harbor_invocations


def extract_invocations(
    root: Path,
    docs: Sequence[str] = DEFAULT_DOCS,
) -> tuple[list[str], list[MakeInvocation], list[TargetInvocation], list[HarborInvocation]]:
    present_docs: list[str] = []
    all_make: list[MakeInvocation] = []
    all_targets: list[TargetInvocation] = []
    all_harbor: list[HarborInvocation] = []

    for doc_rel in docs:
        if not (root / doc_rel).is_file():
            continue
        present_docs.append(doc_rel)
        for snippet in extract_doc_snippets(root, doc_rel):
            for seg in _split_command_segments(snippet.text):
                tokens = _tokenize_segment(seg)
                m_inv, t_inv, h_inv = _parse_tokens_invocations(tokens, snippet)
                all_make.extend(m_inv)
                all_targets.extend(t_inv)
                all_harbor.extend(h_inv)

    return present_docs, all_make, all_targets, all_harbor


def _ast_long_flags(py_file: Path) -> tuple[bool, set[str]]:
    try:
        source = py_file.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(py_file))
    except (OSError, SyntaxError):
        return False, set()

    has_parser = False
    add_help_disabled = False
    flags: set[str] = set()

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func_name = ""
        if isinstance(node.func, ast.Name):
            func_name = node.func.id
        elif isinstance(node.func, ast.Attribute):
            func_name = node.func.attr

        if func_name == "ArgumentParser":
            has_parser = True
            for kw in node.keywords:
                if kw.arg == "add_help" and isinstance(kw.value, ast.Constant) and kw.value.value is False:
                    add_help_disabled = True

        if func_name in {"add_argument", "add_option"}:
            has_parser = True
            is_bool_optional = False
            for kw in node.keywords:
                if kw.arg == "action":
                    if isinstance(kw.value, ast.Attribute) and kw.value.attr == "BooleanOptionalAction":
                        is_bool_optional = True
                    elif isinstance(kw.value, ast.Name) and kw.value.id == "BooleanOptionalAction":
                        is_bool_optional = True
            for arg in node.args:
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    val = arg.value
                    if val.startswith("--") and len(val) > 2 and LONG_FLAG_RE.fullmatch(val):
                        flags.add(val)
                        if is_bool_optional:
                            flags.add(f"--no-{val[2:]}")

    if has_parser and not add_help_disabled:
        flags.add("--help")
    return has_parser, flags


def _help_long_flags(root: Path, target_file: Path, module_name: str | None) -> tuple[bool, set[str], str]:
    cmd = (
        [sys.executable, "-m", module_name, "--help"]
        if module_name
        else [sys.executable, str(target_file), "--help"]
    )
    env = {**os.environ, "PYTHONPATH": str(root)}
    try:
        proc = subprocess.run(
            cmd,
            cwd=root,
            env=env,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except subprocess.TimeoutExpired:
        return False, set(), "--help timed out after 5s"
    except OSError as exc:
        return False, set(), f"--help failed to execute: {exc}"

    combined = f"{proc.stdout or ''}\n{proc.stderr or ''}"
    extracted = set(HELP_LONG_FLAG_RE.findall(combined))
    if proc.returncode != 0:
        snippet = (proc.stderr or proc.stdout or "").strip().splitlines()
        msg = snippet[-1] if snippet else f"exit code {proc.returncode}"
        return False, extracted, f"--help exited with {proc.returncode}: {msg}"
    return True, extracted, ""


class FlagInspector:
    def __init__(self, root: Path) -> None:
        self.root = root
        self._ast_cache: dict[Path, tuple[bool, set[str]]] = {}
        self._help_cache: dict[tuple[Path, str | None], tuple[bool, set[str], str]] = {}

    def verify_flags(
        self,
        target_file: Path,
        module_name: str | None,
        required_flags: Sequence[str],
    ) -> tuple[list[str], set[str], str]:
        resolved = target_file.resolve()
        if resolved not in self._ast_cache:
            self._ast_cache[resolved] = _ast_long_flags(resolved)
        has_ast_parser, ast_flags = self._ast_cache[resolved]

        supported = set(ast_flags)
        missing = [fl for fl in required_flags if fl not in supported]
        if has_ast_parser and not missing:
            return [], supported, ""

        cache_key = (resolved, module_name)
        if cache_key not in self._help_cache:
            self._help_cache[cache_key] = _help_long_flags(self.root, resolved, module_name)
        help_ok, help_flags, help_err = self._help_cache[cache_key]
        supported |= help_flags
        missing = [fl for fl in required_flags if fl not in supported]
        err_note = "" if (has_ast_parser or help_ok) else help_err
        return missing, supported, err_note


def check_makefile_targets(
    root: Path,
    present_docs: Sequence[str],
    make_invocations: Sequence[MakeInvocation],
) -> CheckResult:
    name = "Makefile Targets Check"
    makefile_path = root / "Makefile"
    if not makefile_path.is_file():
        if make_invocations:
            return CheckResult(
                name,
                "FAIL",
                f"Makefile missing at {makefile_path} while {len(make_invocations)} make invocation(s) are documented",
                [f"{inv.doc}:{inv.line}: make {inv.target} (Makefile missing)" for inv in make_invocations],
            )
        return CheckResult(name, "WARN", "Makefile not found and 0 make invocations documented")

    valid_targets = parse_makefile_targets(makefile_path)
    failures: list[str] = []
    warnings: list[str] = []

    for inv in make_invocations:
        if inv.target not in valid_targets:
            msg = (
                f"{inv.doc}:{inv.line}: unknown make target '{inv.target}' "
                f"(valid: {', '.join(sorted(valid_targets)) or 'none'})"
            )
            if inv.superseded:
                warnings.append(f"{msg} [superseded section]")
            else:
                failures.append(msg)

    unique_used = sorted({inv.target for inv in make_invocations if inv.target in valid_targets})
    if failures:
        return CheckResult(
            name,
            "FAIL",
            f"{len(failures)} invalid make target invocation(s) across {len(present_docs)} doc(s)",
            failures + warnings,
        )
    if warnings:
        return CheckResult(
            name,
            "WARN",
            f"checked {len(make_invocations)} make invocation(s) against {len(valid_targets)} Makefile target(s); "
            f"{len(warnings)} superseded warning(s)",
            warnings,
        )
    return CheckResult(
        name,
        "PASS",
        f"checked {len(make_invocations)} make invocation(s) ({len(unique_used)} distinct: "
        f"{', '.join(unique_used) or 'none'}) against {len(valid_targets)} Makefile target(s)",
    )


def _resolve_target_file(root: Path, inv: TargetInvocation) -> Path | None:
    for rel in inv.rel_candidates:
        candidate = root / rel
        if candidate.is_file():
            return candidate
    return None


def check_script_and_module_paths(
    root: Path,
    present_docs: Sequence[str],
    target_invocations: Sequence[TargetInvocation],
) -> CheckResult:
    name = "Script & Module Paths Check"
    failures: list[str] = []
    warnings: list[str] = []
    resolved_count = 0

    for inv in target_invocations:
        found = _resolve_target_file(root, inv)
        if found is not None:
            resolved_count += 1
            continue
        expected = " or ".join(inv.rel_candidates)
        if inv.external_branch:
            warnings.append(
                f"{inv.doc}:{inv.line}: {inv.display} ({expected}) not on current tree "
                f"(documented as external branch '{inv.external_branch}')"
            )
        elif inv.superseded:
            warnings.append(
                f"{inv.doc}:{inv.line}: {inv.display} ({expected}) missing in superseded archive section"
            )
        else:
            failures.append(f"{inv.doc}:{inv.line}: {inv.display} missing on disk (expected {expected})")

    if failures:
        return CheckResult(
            name,
            "FAIL",
            f"{len(failures)} missing script/module reference(s) across {len(present_docs)} doc(s)",
            failures + warnings,
        )
    if warnings:
        return CheckResult(
            name,
            "WARN",
            f"{resolved_count} script/module reference(s) resolved on disk; "
            f"{len(warnings)} external-branch/archive advisory warning(s)",
            warnings,
        )
    return CheckResult(
        name,
        "PASS",
        f"all {resolved_count} script/module reference(s) across {len(present_docs)} doc(s) exist on disk",
    )


def check_cli_long_flags(
    root: Path,
    target_invocations: Sequence[TargetInvocation],
    flag_docs: frozenset[str] = FLAG_CHECK_DOCS,
) -> CheckResult:
    name = "CLI Long-Flag Check"
    inspector = FlagInspector(root)
    failures: list[str] = []
    warnings: list[str] = []
    checked_invocations = 0
    checked_flags = 0

    for inv in target_invocations:
        if inv.doc not in flag_docs or not inv.long_flags:
            continue
        target_file = _resolve_target_file(root, inv)
        if target_file is None:
            continue
        checked_invocations += 1
        checked_flags += len(inv.long_flags)
        missing, supported, err_note = inspector.verify_flags(
            target_file=target_file,
            module_name=inv.module_name,
            required_flags=inv.long_flags,
        )
        if missing:
            sup_str = ", ".join(sorted(supported)) if supported else "none detected"
            extra = f" ({err_note})" if err_note else ""
            msg = (
                f"{inv.doc}:{inv.line}: {inv.display} unsupported flag(s) "
                f"{', '.join(missing)} (supported: {sup_str}){extra}"
            )
            if inv.superseded:
                warnings.append(f"{msg} [superseded section]")
            else:
                failures.append(msg)

    if failures:
        return CheckResult(
            name,
            "FAIL",
            f"{len(failures)} CLI long-flag mismatch(es) across {checked_invocations} invocation(s)",
            failures + warnings,
        )
    if warnings:
        return CheckResult(
            name,
            "WARN",
            f"verified {checked_flags} flag(s) across {checked_invocations} invocation(s); "
            f"{len(warnings)} superseded warning(s)",
            warnings,
        )
    return CheckResult(
        name,
        "PASS",
        f"verified {checked_flags} long-flag occurrence(s) across {checked_invocations} CLI invocation(s)",
    )


def check_harbor_commands(
    harbor_invocations: Sequence[HarborInvocation],
    present_docs: Sequence[str] = (),
) -> CheckResult:
    name = "Harbor CLI & Env-Var Check"
    failures: list[str] = []
    warnings: list[str] = []

    for inv in harbor_invocations:
        inv_issues: list[str] = []

        for ae in inv.agent_envs:
            raw_key, sep, raw_val = ae.partition("=")
            env_key = raw_key.strip()
            env_val = raw_val.strip()
            display_ae = ae.replace(PLACEHOLDER_TOKEN, "<placeholder>")
            if env_key.upper().startswith("CANARY_"):
                inv_issues.append(
                    f"{inv.doc}:{inv.line}: harbor run passes forbidden CANARY_* env var "
                    f"'--ae {display_ae}' into agent container (check_isolation.sh fails on any CANARY_* in main)"
                )
            elif env_key == "ORACLE_POLICY":
                if not sep or (
                    not _is_placeholder_or_glob(env_val)
                    and env_val not in VALID_HARBOR_ORACLE_POLICIES
                ):
                    valid_str = ", ".join(sorted(VALID_HARBOR_ORACLE_POLICIES))
                    inv_issues.append(
                        f"{inv.doc}:{inv.line}: harbor run has invalid '--ae {display_ae}' "
                        f"(valid ORACLE_POLICY: {valid_str})"
                    )

        agent_val = (inv.agent or "").strip()
        model_val = (inv.model or "").strip()
        if agent_val == "opencode" and model_val.lower().startswith("google/"):
            if "GOOGLE_GENERATIVE_AI_API_KEY" not in [k.strip() for k in inv.api_key_names]:
                display_model = model_val.replace(PLACEHOLDER_TOKEN, "<placeholder>")
                inv_issues.append(
                    f"{inv.doc}:{inv.line}: harbor run with '-a opencode -m {display_model}' "
                    "must include '--api-key-name GOOGLE_GENERATIVE_AI_API_KEY'"
                )

        for msg in inv_issues:
            if inv.superseded:
                warnings.append(f"{msg} [superseded section]")
            else:
                failures.append(msg)

    if failures:
        return CheckResult(
            name,
            "FAIL",
            f"{len(failures)} Harbor CLI/env violation(s) across {len(harbor_invocations)} harbor run invocation(s)",
            failures + warnings,
        )
    if warnings:
        return CheckResult(
            name,
            "WARN",
            f"checked {len(harbor_invocations)} harbor run invocation(s) across {len(present_docs)} doc(s); "
            f"{len(warnings)} superseded warning(s)",
            warnings,
        )
    return CheckResult(
        name,
        "PASS",
        f"verified {len(harbor_invocations)} harbor run invocation(s) across {len(present_docs)} doc(s) "
        "(0 CANARY_* leaks, Google OpenCode key forwarding ok, ORACLE_POLICY values valid)",
    )


def verify_repo(
    root: Path = ROOT,
    docs: Sequence[str] = DEFAULT_DOCS,
) -> list[CheckResult]:
    present_docs, make_invocations, target_invocations, harbor_invocations = extract_invocations(root, docs)
    if not present_docs:
        return [
            CheckResult(
                "Documentation Discovery",
                "FAIL",
                f"none of the target judge docs exist under {root}",
                list(docs),
            )
        ]
    return [
        check_makefile_targets(root, present_docs, make_invocations),
        check_script_and_module_paths(root, present_docs, target_invocations),
        check_cli_long_flags(root, target_invocations, frozenset(docs)),
        check_harbor_commands(harbor_invocations, present_docs),
    ]


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
        description="Verify Makefile targets, script/module paths, CLI flags, and Harbor commands across judge-facing docs."
    )
    ap.add_argument("--root", type=Path, default=ROOT, help="Repository root to verify")
    ap.add_argument(
        "--doc",
        action="append",
        dest="docs",
        default=None,
        help="Relative doc path to verify (repeatable; defaults to DEFAULT_DOCS)",
    )
    ap.add_argument("--json", action="store_true", help="Emit JSON report")
    args = ap.parse_args(argv)

    target_docs: Sequence[str] = tuple(args.docs) if args.docs else DEFAULT_DOCS
    t0 = time.monotonic()
    results = verify_repo(root=args.root.resolve(), docs=target_docs)
    elapsed = time.monotonic() - t0
    passed = not any(r.status == "FAIL" for r in results)

    if args.json:
        payload = {
            "results": [asdict(r) for r in results],
            "elapsed_s": round(elapsed, 4),
            "passed": passed,
        }
        print(json.dumps(payload, indent=2))
    else:
        print(format_report(results, elapsed))

    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
