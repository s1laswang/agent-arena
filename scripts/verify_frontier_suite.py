"""Fast offline master artifact and cross-report consistency verifier for Canary v1.4 frontier deliverables.

    PYTHONPATH=. python scripts/verify_frontier_suite.py --write
    PYTHONPATH=. python scripts/verify_frontier_suite.py --check
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

SCHEMA_VERSION = "v1.4-frontier-suite-manifest-1"
TIERS_VERSION = "v1.4"
MAX_JSON_BYTES = 25_000

DEFAULT_JSON = ROOT / "results" / "frontier_replication" / "v1.4" / "suite_manifest_v14.json"
DEFAULT_MD = ROOT / "docs" / "reports" / "frontier_master_index_v14.md"

H1 = chr(35)
H2 = chr(35) * 2
H3 = chr(35) * 3
EM_DASH = chr(0x2014)
EN_DASH = chr(0x2013)

_GOOGLE_KEY_PREFIX = "AI" + "za"
_OPENAI_KEY_PREFIX = "s" + "k-"
_GITHUB_PAT_PREFIX = "gh" + "p_"
_PRIVATE_KEY_MARKER = "BEGIN " + "PRIVATE KEY"

_SECRET_DETECTORS: tuple[tuple[str, bytes, re.Pattern[bytes]], ...] = (
    (
        "google_api_key",
        _GOOGLE_KEY_PREFIX.encode("ascii"),
        re.compile(rb"(?<![0-9A-Za-z+/_-])" + _GOOGLE_KEY_PREFIX.encode("ascii") + rb"[0-9A-Za-z_-]{20,}"),
    ),
    (
        "sk_api_key",
        _OPENAI_KEY_PREFIX.encode("ascii"),
        re.compile(
            rb"(?<![0-9A-Za-z+/_-])"
            + _OPENAI_KEY_PREFIX.encode("ascii")
            + rb"(?:proj-|ant-|live-|test-|svcacct-)?[0-9A-Za-z_-]{16,}"
        ),
    ),
    (
        "github_pat",
        _GITHUB_PAT_PREFIX.encode("ascii"),
        re.compile(rb"(?<![0-9A-Za-z_])" + _GITHUB_PAT_PREFIX.encode("ascii") + rb"[0-9A-Za-z]{30,}"),
    ),
    (
        "private_key_pem",
        _PRIVATE_KEY_MARKER.encode("ascii"),
        re.compile(re.escape(_PRIVATE_KEY_MARKER.encode("ascii"))),
    ),
    (
        "unredacted_thought_signature",
        b'"thoughtSignature":',
        re.compile(rb'"thoughtSignature":\s?"[^"<]{64,}"'),
    ),
)

UPSTREAM_JSON_SPECS: tuple[dict[str, Any], ...] = (
    {
        "deliverable_id": "frontier_replication",
        "json_rel": "results/frontier_replication/v1.4/replication_summary.json",
        "max_bytes": 48_000,
        "script_rel": "scripts/verify_frontier_replication.py",
        "report_rel": "docs/reports/frontier_replication_v14.md",
        "test_rel": "tests/test_frontier_replication.py",
        "cohort_n_summary": "777 pool (30 primary/tier, 30 gpt-5.5, 2 G1, 5 FR8, 6 union, 30 flash med)",
        "verify_cmd": "PYTHONPATH=. python scripts/verify_frontier_replication.py --check",
    },
    {
        "deliverable_id": "frontier_g2_families",
        "json_rel": "results/frontier_replication/v1.4/g2_families_audit.json",
        "max_bytes": 45_000,
        "script_rel": "scripts/frontier_g2_families_audit.py",
        "report_rel": "docs/reports/frontier_g2_families_v14.md",
        "test_rel": "tests/test_frontier_g2_families_audit.py",
        "cohort_n_summary": "60 G2 hard (30 argon + 30 hydrogen) + 60 carbon/solver = 120 paired (532 w/ committed)",
        "verify_cmd": "PYTHONPATH=. python scripts/frontier_g2_families_audit.py --check",
    },
    {
        "deliverable_id": "frontier_infra_sensitivity",
        "json_rel": "results/frontier_replication/v1.4/infra_sensitivity.json",
        "max_bytes": 45 * 1024,
        "script_rel": "scripts/frontier_infra_sensitivity.py",
        "report_rel": "docs/reports/frontier_infra_sensitivity_v14.md",
        "test_rel": "tests/test_frontier_infra_sensitivity.py",
        "cohort_n_summary": "777 pool (6 committed + 2 sharded cohorts, 71 infra exclusions, 5 timeout caps)",
        "verify_cmd": "PYTHONPATH=. python scripts/frontier_infra_sensitivity.py --check",
    },
    {
        "deliverable_id": "frontier_mole_stratified_gap",
        "json_rel": "results/frontier_replication/v1.4/mole_stratified_gap.json",
        "max_bytes": 45_000,
        "script_rel": "scripts/frontier_mole_stratified_gap.py",
        "report_rel": "docs/reports/frontier_mole_stratified_gap_v14.md",
        "test_rel": "tests/test_frontier_mole_stratified_gap.py",
        "cohort_n_summary": "90 worlds (med 0-29, hard 0-29, hard 30-59), 14 cohorts (337 cohort eps in 777 pool)",
        "verify_cmd": "PYTHONPATH=. python scripts/frontier_mole_stratified_gap.py --check",
    },
    {
        "deliverable_id": "frontier_queue_preflight",
        "json_rel": "results/frontier_replication/v1.4/queue_manifest.json",
        "max_bytes": 50 * 1024,
        "script_rel": "scripts/frontier_queue_preflight.py",
        "report_rel": None,
        "test_rel": "tests/test_frontier_queue_preflight.py",
        "cohort_n_summary": "777 pool (35/90 FR8 landed, 6/30 distinct carbon ext, 30/30 gpt-5.5, 8 preflight gates)",
        "verify_cmd": "PYTHONPATH=. python scripts/frontier_queue_preflight.py --check --validate-template-waves",
    },
    {
        "deliverable_id": "frontier_trajectory_audit",
        "json_rel": "results/frontier_replication/v1.4/trajectory_audit.json",
        "max_bytes": 50_000,
        "script_rel": "scripts/frontier_trajectory_audit.py",
        "report_rel": "docs/reports/frontier_trajectory_audit_v14.md",
        "test_rel": "tests/test_frontier_trajectory_audit.py",
        "cohort_n_summary": "277 active episodes across 11 cohorts (6 OpenCode, 2 in-proc, 3 solver) in 777 pool",
        "verify_cmd": "PYTHONPATH=. python scripts/frontier_trajectory_audit.py --check",
    },
    {
        "deliverable_id": "frontier_transcript_forensics",
        "json_rel": "results/frontier_replication/v1.4/transcript_forensics.json",
        "max_bytes": 45_000,
        "script_rel": "scripts/frontier_transcript_forensics.py",
        "report_rel": "docs/reports/frontier_transcript_forensics_v14.md",
        "test_rel": "tests/test_frontier_transcript_forensics.py",
        "cohort_n_summary": "97+ OpenCode transcripts (5+ active cohorts, 10 forensic case dossiers) in 777 pool",
        "verify_cmd": "PYTHONPATH=. python scripts/frontier_transcript_forensics.py --check",
    },
    {
        "deliverable_id": "frontier_stopping_counterfactual",
        "json_rel": "results/frontier_replication/v1.4/stopping_counterfactual_v14.json",
        "max_bytes": 35_000,
        "script_rel": "scripts/frontier_stopping_counterfactual_v14.py",
        "report_rel": "docs/reports/frontier_stopping_counterfactual_v14.md",
        "test_rel": "tests/test_frontier_stopping_counterfactual_v14.py",
        "cohort_n_summary": "246 episodes across 9 v1.4 cohorts (Bayes break-even abstention and EV decomposition)",
        "verify_cmd": "PYTHONPATH=. python scripts/frontier_stopping_counterfactual_v14.py --check",
    },
)

MASTER_SUITE_SPEC: dict[str, Any] = {
    "deliverable_id": "frontier_suite_master",
    "json_rel": "results/frontier_replication/v1.4/suite_manifest_v14.json",
    "max_bytes": MAX_JSON_BYTES,
    "script_rel": "scripts/verify_frontier_suite.py",
    "report_rel": "docs/reports/frontier_master_index_v14.md",
    "test_rel": "tests/test_frontier_suite_master.py",
    "cohort_n_summary": "777 v1.4 pool (472 committed + 305 replication) + 60 G2 + 29 Harbor rehearsal trials",
    "verify_cmd": "PYTHONPATH=. python scripts/verify_frontier_suite.py --check",
}

EXPECTED_COMMITTED_EPISODES = 472
EXPECTED_REPLICATION_EPISODES = 305
EXPECTED_COMBINED_EPISODES = 777
EXPECTED_G1_SEEDS = [34, 37]
EXPECTED_FR8_SEEDS = [30, 34, 42, 45, 57]
EXPECTED_UNION_SEEDS = [30, 34, 37, 42, 45, 57]
EXPECTED_GPT55_NON_ACCUSE_SEEDS = [0, 17]
EXPECTED_HARBOR_RATIOS_PCT = [93, 116, 131]


def default_json_path(root: Path = ROOT) -> Path:
    return DEFAULT_JSON if root == ROOT else root / MASTER_SUITE_SPEC["json_rel"]


def default_md_path(root: Path = ROOT) -> Path:
    return DEFAULT_MD if root == ROOT else root / MASTER_SUITE_SPEC["report_rel"]


def clean_json(obj: Any, float_ndigits: int | None = 6) -> Any:
    if isinstance(obj, bool) or obj is None:
        return obj
    if isinstance(obj, int):
        return obj
    if isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            raise ValueError(f"non-finite float in manifest payload: {obj!r}")
        return round(obj, float_ndigits) if float_ndigits is not None else obj
    if isinstance(obj, dict):
        return {str(k): clean_json(v, float_ndigits) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [clean_json(v, float_ndigits) for v in obj]
    return obj


def _fmt_json_compact(obj: Any, depth: int = 0, max_expand_depth: int = 2) -> str:
    if depth >= max_expand_depth or not isinstance(obj, (dict, list)) or not obj:
        return json.dumps(obj, sort_keys=True, allow_nan=False, separators=(",", ":"))
    pad = " " * depth
    inner_pad = " " * (depth + 1)
    if isinstance(obj, list):
        if all(not isinstance(x, (dict, list)) for x in obj):
            return json.dumps(obj, allow_nan=False, separators=(",", ":"))
        items = [inner_pad + _fmt_json_compact(v, depth + 1, max_expand_depth) for v in obj]
        return "[\n" + ",\n".join(items) + "\n" + pad + "]"
    items = [
        f"{inner_pad}{json.dumps(k)}: {_fmt_json_compact(obj[k], depth + 1, max_expand_depth)}"
        for k in sorted(obj.keys())
    ]
    return "{\n" + ",\n".join(items) + "\n" + pad + "}"


def serialize_manifest_json(manifest: dict[str, Any]) -> str:
    cleaned = clean_json(manifest, float_ndigits=6)
    blob = _fmt_json_compact(cleaned, depth=0, max_expand_depth=2) + "\n"
    size = len(blob.encode("utf-8"))
    if size > MAX_JSON_BYTES:
        raise ValueError(f"suite_manifest_v14.json size {size} exceeds {MAX_JSON_BYTES} byte cap")
    return blob


def scan_secrets_bytes(raw: bytes, label: str) -> list[str]:
    hits: list[str] = []
    for kind, token, rx in _SECRET_DETECTORS:
        if token in raw:
            for match in rx.finditer(raw):
                snippet = match.group(0)[:6].decode("ascii", errors="replace")
                hits.append(f"{label}:{kind}:{snippet}...")
    return hits


def scan_dashes_text(text: str, label: str) -> list[str]:
    hits: list[str] = []
    if EM_DASH in text:
        hits.append(f"{label}:em_dash")
    if EN_DASH in text:
        hits.append(f"{label}:en_dash")
    return hits


def _assert_close(actual: float, expected: float, tol: float, label: str) -> None:
    if not math.isclose(float(actual), float(expected), rel_tol=0.0, abs_tol=tol):
        raise ValueError(f"{label} mismatch: got {actual!r}, expected {expected!r} (tol={tol})")


def _assert_eq(actual: Any, expected: Any, label: str) -> None:
    if actual != expected:
        raise ValueError(f"{label} mismatch: got {actual!r}, expected {expected!r}")


def parse_harbor_rehearsal_table(text: str) -> dict[str, Any]:
    row_rx = re.compile(
        r"^\|\s*(opencode-1|opencode-2|opencode-3|do_nothing|stop_early)\s*\|\s*"
        r"(\d+)\s*\|\s*(\d+)\s*\|\s*([0-9]+\s*/\s*[0-9]+)\s*\|\s*"
        r"([+-]?\d+\.\d+)\s*\|\s*([+-]?\d+\.\d+)\s*\|\s*"
        r"(\d+)%\s*\[(\d+)%,\s*(\d+)%\]",
        re.MULTILINE,
    )
    rows: dict[str, dict[str, Any]] = {}
    for m in row_rx.finditer(text):
        run_id = m.group(1)
        corr_parts = [int(x.strip()) for x in m.group(4).split("/")]
        rows[run_id] = {
            "n_valid": int(m.group(2)),
            "infra_excluded": int(m.group(3)),
            "correct": corr_parts[0],
            "accused": corr_parts[1],
            "mean": float(m.group(5)),
            "oracle_same_tasks": float(m.group(6)),
            "ratio_pct": int(m.group(7)),
            "ci_pct": [int(m.group(8)), int(m.group(9))],
        }
    for req in ("opencode-1", "opencode-2", "opencode-3", "do_nothing", "stop_early"):
        if req not in rows:
            raise ValueError(f"Harbor TABLE.md missing summary row for {req!r}")

    corr_rx = re.compile(
        r"Final:\s*run\s*3\s*has\s*(\d+)\s*valid\s*trials\s*"
        r"\([^)]*?(\d+)\s*infra-excluded\),\s*"
        r"mean\s*([+-]?\d+\.\d+)\s*=\s*(\d+)%\s*\[(\d+)%,\s*(\d+)%\]\s*of\s*the\s*oracle;\s*"
        r"runs\s*1\s*and\s*2\s*are\s*unchanged\s*\((\d+)%,\s*(\d+)%\)"
    )
    corr_m = corr_rx.search(text)
    if corr_m is not None:
        r3_n = int(corr_m.group(1))
        r3_inf = int(corr_m.group(2))
        r3_mean = float(corr_m.group(3))
        r3_ratio = int(corr_m.group(4))
        r3_ci = [int(corr_m.group(5)), int(corr_m.group(6))]
        note_r1 = int(corr_m.group(7))
        note_r2 = int(corr_m.group(8))
        _assert_eq(note_r1, rows["opencode-1"]["ratio_pct"], "Harbor TABLE.md note run 1 ratio")
        _assert_eq(note_r2, rows["opencode-2"]["ratio_pct"], "Harbor TABLE.md note run 2 ratio")
    else:
        r3_n = rows["opencode-3"]["n_valid"]
        r3_inf = rows["opencode-3"]["infra_excluded"]
        r3_mean = rows["opencode-3"]["mean"]
        r3_ratio = rows["opencode-3"]["ratio_pct"]
        r3_ci = list(rows["opencode-3"]["ci_pct"])

    r1 = rows["opencode-1"]
    r2 = rows["opencode-2"]
    _assert_eq(r1["n_valid"], 10, "Harbor opencode-1 n_valid")
    _assert_eq(r1["infra_excluded"], 0, "Harbor opencode-1 infra_excluded")
    _assert_close(r1["mean"], 0.472, 1e-6, "Harbor opencode-1 mean")
    _assert_close(r1["oracle_same_tasks"], 0.506, 1e-6, "Harbor opencode-1 oracle")
    _assert_eq(r1["ratio_pct"], 93, "Harbor opencode-1 ratio_pct")
    _assert_eq(r1["ci_pct"], [20, 371], "Harbor opencode-1 ci_pct")

    _assert_eq(r2["n_valid"], 10, "Harbor opencode-2 n_valid")
    _assert_eq(r2["infra_excluded"], 0, "Harbor opencode-2 infra_excluded")
    _assert_close(r2["mean"], 0.585, 1e-6, "Harbor opencode-2 mean")
    _assert_close(r2["oracle_same_tasks"], 0.506, 1e-6, "Harbor opencode-2 oracle")
    _assert_eq(r2["ratio_pct"], 116, "Harbor opencode-2 ratio_pct")
    _assert_eq(r2["ci_pct"], [78, 363], "Harbor opencode-2 ci_pct")

    _assert_eq(r3_n, 9, "Harbor opencode-3 final n_valid")
    _assert_eq(r3_inf, 1, "Harbor opencode-3 final infra_excluded")
    _assert_close(r3_mean, 0.626, 1e-6, "Harbor opencode-3 final mean")
    _assert_eq(r3_ratio, 131, "Harbor opencode-3 final ratio_pct")
    _assert_eq(r3_ci, [86, 590], "Harbor opencode-3 final ci_pct")

    _assert_eq(rows["do_nothing"]["ratio_pct"], 0, "Harbor do_nothing ratio_pct")
    _assert_eq(rows["stop_early"]["ratio_pct"], 0, "Harbor stop_early ratio_pct")

    final_ratios = [r1["ratio_pct"], r2["ratio_pct"], r3_ratio]
    _assert_eq(final_ratios, EXPECTED_HARBOR_RATIOS_PCT, "Harbor final ratios")

    return {
        "source_rel": "results/harbor/rehearsal/TABLE.md",
        "tag": "afterquery-final",
        "tag_commit": "1bc3e281",
        "final_branch_commit": "d0ead011",
        "tasks_count": 10,
        "seed_range": [900000, 900009],
        "final_ratios_pct": final_ratios,
        "runs": [
            {
                "run": "opencode-1",
                "n_valid": r1["n_valid"],
                "infra_excluded": r1["infra_excluded"],
                "mean": r1["mean"],
                "oracle_same_tasks": r1["oracle_same_tasks"],
                "ratio_pct": r1["ratio_pct"],
                "ci_pct": r1["ci_pct"],
            },
            {
                "run": "opencode-2",
                "n_valid": r2["n_valid"],
                "infra_excluded": r2["infra_excluded"],
                "mean": r2["mean"],
                "oracle_same_tasks": r2["oracle_same_tasks"],
                "ratio_pct": r2["ratio_pct"],
                "ci_pct": r2["ci_pct"],
            },
            {
                "run": "opencode-3",
                "n_valid": r3_n,
                "infra_excluded": r3_inf,
                "mean": r3_mean,
                "oracle_same_tasks": None,
                "ratio_pct": r3_ratio,
                "ci_pct": r3_ci,
                "snapshot_0852_n_valid": rows["opencode-3"]["n_valid"],
                "snapshot_0852_ratio_pct": rows["opencode-3"]["ratio_pct"],
            },
        ],
        "total_valid_opencode_trials": r1["n_valid"] + r2["n_valid"] + r3_n,
        "do_nothing_ratio_pct": rows["do_nothing"]["ratio_pct"],
        "stop_early_ratio_pct": rows["stop_early"]["ratio_pct"],
    }


def _count_nonempty_lines(path: Path) -> int:
    with path.open("rb") as fh:
        return sum(1 for ln in fh if ln.strip())


def compute_suite_manifest(root: Path = ROOT) -> dict[str, Any]:
    secret_hits: list[str] = []
    dash_hits: list[str] = []
    loaded_jsons: dict[str, dict[str, Any]] = {}

    for spec in UPSTREAM_JSON_SPECS:
        jpath = root / spec["json_rel"]
        if not jpath.is_file():
            raise ValueError(f"missing required frontier JSON artifact: {spec['json_rel']}")
        raw = jpath.read_bytes()
        size = len(raw)
        if size == 0 or size > int(spec["max_bytes"]):
            raise ValueError(
                f"{spec['json_rel']} size {size} violates cap 1..{spec['max_bytes']} bytes"
            )
        secret_hits.extend(scan_secrets_bytes(raw, spec["json_rel"]))
        txt = raw.decode("utf-8")
        dash_hits.extend(scan_dashes_text(txt, spec["json_rel"]))
        obj = json.loads(txt)
        if not isinstance(obj, dict):
            raise ValueError(f"{spec['json_rel']} root must be a JSON object")
        _assert_eq(obj.get("tiers_version"), TIERS_VERSION, f"{spec['json_rel']} tiers_version")
        loaded_jsons[spec["deliverable_id"]] = obj

        if spec["report_rel"] is not None:
            rpath = root / spec["report_rel"]
            if rpath.is_file():
                rraw = rpath.read_bytes()
                secret_hits.extend(scan_secrets_bytes(rraw, spec["report_rel"]))
                dash_hits.extend(scan_dashes_text(rraw.decode("utf-8"), spec["report_rel"]))
        for code_rel_key in ("script_rel", "test_rel"):
            cpath = root / spec[code_rel_key]
            if cpath.is_file():
                craw = cpath.read_bytes()
                secret_hits.extend(scan_secrets_bytes(craw, spec[code_rel_key]))
                dash_hits.extend(scan_dashes_text(craw.decode("utf-8"), spec[code_rel_key]))

    ptg_rel = "data/runs/committed/v1.4/paired_table_gemini.json"
    ptg_path = root / ptg_rel
    if not ptg_path.is_file():
        raise ValueError(f"missing required committed table: {ptg_rel}")
    ptg_raw = ptg_path.read_bytes()
    secret_hits.extend(scan_secrets_bytes(ptg_raw, ptg_rel))
    ptg_rows = json.loads(ptg_raw.decode("utf-8"))
    if not isinstance(ptg_rows, list) or not ptg_rows:
        raise ValueError(f"{ptg_rel} must be a non-empty JSON list")

    harbor_rel = "results/harbor/rehearsal/TABLE.md"
    harbor_path = root / harbor_rel
    if not harbor_path.is_file():
        raise ValueError(f"missing required Harbor rehearsal table: {harbor_rel}")
    harbor_raw = harbor_path.read_bytes()
    secret_hits.extend(scan_secrets_bytes(harbor_raw, harbor_rel))
    harbor_summary = parse_harbor_rehearsal_table(harbor_raw.decode("utf-8"))

    rep_dir = root / "results" / "frontier_replication" / "v1.4"
    for sub in sorted(rep_dir.rglob("meta.json")) + sorted(rep_dir.rglob("*.txt")):
        rel_lbl = str(sub.relative_to(root))
        secret_hits.extend(scan_secrets_bytes(sub.read_bytes(), rel_lbl))

    comm_dir = root / "data" / "runs" / "committed" / "v1.4"
    comm_ep_files = sorted(comm_dir.rglob("episodes.jsonl")) if comm_dir.is_dir() else []
    rep_ep_files = sorted(rep_dir.rglob("episodes.jsonl")) if rep_dir.is_dir() else []
    if comm_ep_files:
        disk_comm_eps = sum(_count_nonempty_lines(p) for p in comm_ep_files)
        _assert_eq(disk_comm_eps, EXPECTED_COMMITTED_EPISODES, "on-disk committed v1.4 episodes")
    if rep_ep_files:
        disk_rep_eps = sum(_count_nonempty_lines(p) for p in rep_ep_files)
        _assert_eq(disk_rep_eps, EXPECTED_REPLICATION_EPISODES, "on-disk replication v1.4 episodes")

    if secret_hits:
        raise ValueError(f"secret/signature leak(s) detected: {secret_hits}")
    if dash_hits:
        raise ValueError(f"forbidden em/en dash(es) detected in frontier deliverables: {dash_hits}")

    rep = loaded_jsons["frontier_replication"]
    g2 = loaded_jsons["frontier_g2_families"]
    inf = loaded_jsons["frontier_infra_sensitivity"]
    mol = loaded_jsons["frontier_mole_stratified_gap"]
    que = loaded_jsons["frontier_queue_preflight"]
    trj = loaded_jsons["frontier_trajectory_audit"]
    fsc = loaded_jsons["frontier_transcript_forensics"]
    stp = loaded_jsons["frontier_stopping_counterfactual"]

    corpus_checks = (
        ("replication_summary.committed", rep["replay_verification"]["committed_v14"]["total"], EXPECTED_COMMITTED_EPISODES),
        ("replication_summary.committed_verified", rep["replay_verification"]["committed_v14"]["verified"], EXPECTED_COMMITTED_EPISODES),
        ("replication_summary.committed_mismatches", rep["replay_verification"]["committed_v14"]["mismatches"], 0),
        ("replication_summary.committed_duplicates", rep["replay_verification"]["committed_v14"]["duplicates"], 0),
        ("replication_summary.replication", rep["replay_verification"]["replication_v14"]["total"], EXPECTED_REPLICATION_EPISODES),
        ("replication_summary.replication_verified", rep["replay_verification"]["replication_v14"]["verified"], EXPECTED_REPLICATION_EPISODES),
        ("replication_summary.replication_mismatches", rep["replay_verification"]["replication_v14"]["mismatches"], 0),
        ("replication_summary.replication_duplicates", rep["replay_verification"]["replication_v14"]["duplicates"], 0),
        ("g2.committed_verified", g2["verification_totals"]["committed_v14_episodes_verified"], EXPECTED_COMMITTED_EPISODES),
        ("g2.g2_verified", g2["verification_totals"]["g2_episodes_replay_verified"], 60),
        ("g2.committed_plus_g2", g2["verification_totals"]["committed_plus_g2_v14_episodes_verified"], EXPECTED_COMMITTED_EPISODES + 60),
        ("g2.all_mismatches", g2["verification_totals"]["all_mismatches"], 0),
        ("infra.committed_verified", inf["seed_lock_and_replay"]["committed_v14_replay"]["verified"], EXPECTED_COMMITTED_EPISODES),
        ("infra.replication_verified", inf["seed_lock_and_replay"]["replication_v14_replay"]["verified"], EXPECTED_REPLICATION_EPISODES),
        ("infra.combined_verified", inf["seed_lock_and_replay"]["combined_v14_replay"]["verified"], EXPECTED_COMBINED_EPISODES),
        ("infra.combined_mismatches", inf["seed_lock_and_replay"]["combined_v14_replay"]["mismatches"], 0),
        ("mole.committed_verified", mol["replay_verification"]["committed_v14"]["verified"], EXPECTED_COMMITTED_EPISODES),
        ("mole.replication_verified", mol["replay_verification"]["replication_v14"]["verified"], EXPECTED_REPLICATION_EPISODES),
        ("mole.combined_verified", mol["summary"]["total_pool_episodes_replay_verified"], EXPECTED_COMBINED_EPISODES),
        ("queue.committed_verified", que["summary"]["committed_v14_replay_verified_episodes"], EXPECTED_COMMITTED_EPISODES),
        ("queue.replication_verified", que["summary"]["replication_replay_verified_episodes"], EXPECTED_REPLICATION_EPISODES),
        ("queue.combined_verified", que["summary"]["combined_v14_replay_verified_episodes"], EXPECTED_COMBINED_EPISODES),
        ("trajectory.committed_verified", trj["replay_verification"]["committed_v14"]["verified"], EXPECTED_COMMITTED_EPISODES),
        ("trajectory.replication_verified", trj["replay_verification"]["replication_v14"]["verified"], EXPECTED_REPLICATION_EPISODES),
        ("trajectory.combined_verified", trj["summary"]["total_pool_episodes_replay_verified"], EXPECTED_COMBINED_EPISODES),
        ("forensics.committed_verified", fsc["replay_and_transcript_verification"]["committed_v14"]["verified"], EXPECTED_COMMITTED_EPISODES),
        ("forensics.replication_verified", fsc["replay_and_transcript_verification"]["replication_v14"]["verified"], EXPECTED_REPLICATION_EPISODES),
        ("forensics.combined_verified", fsc["replay_and_transcript_verification"]["combined_verified_episodes"], EXPECTED_COMBINED_EPISODES),
        ("forensics.secret_leaks", fsc["replay_and_transcript_verification"]["secret_key_leaks"], 0),
        ("forensics.unredacted_sigs", fsc["replay_and_transcript_verification"]["unredacted_thought_signatures"], 0),
        ("stopping.committed_verified", stp["provenance"]["committed_v14_episodes"], EXPECTED_COMMITTED_EPISODES),
        ("stopping.replication_verified", stp["provenance"]["replication_v14_episodes"], EXPECTED_REPLICATION_EPISODES),
        ("stopping.combined_verified", stp["provenance"]["combined_v14_episodes"], EXPECTED_COMBINED_EPISODES),
        ("stopping.solver_sub_breakeven", stp["summary"]["solver_sub_breakeven_total"], 0),
        ("stopping.harbor_ratios", stp["provenance"]["harbor_rehearsal_ratios_pct"], EXPECTED_HARBOR_RATIOS_PCT),
        ("stopping.gpt55_non_accuse", stp["provenance"]["gpt_5_5_clean_rc0_non_accuse_seeds"], EXPECTED_GPT55_NON_ACCUSE_SEEDS),
        ("stopping.g1_seeds", stp["provenance"]["g1_seeds"], EXPECTED_G1_SEEDS),
        ("stopping.fr8_seeds", stp["provenance"]["fr8_rep_seeds"], EXPECTED_FR8_SEEDS),
        ("stopping.union6_seeds", stp["provenance"]["carbon_hard_30_59_dedup_union_seeds"], EXPECTED_UNION_SEEDS),
    )
    for lbl, got, exp in corpus_checks:
        _assert_eq(got, exp, lbl)

    ptg_c_hard = next(
        (
            r for r in ptg_rows
            if r.get("agent") == "opencode:google/gemini-4-carbon"
            and r.get("tier") == "hard"
            and "alternative" not in str(r.get("label", ""))
        ),
        None,
    )
    ptg_c_med = next(
        (
            r for r in ptg_rows
            if r.get("agent") == "opencode:google/gemini-4-carbon"
            and r.get("tier") == "medium"
            and "alternative" not in str(r.get("label", ""))
        ),
        None,
    )
    ptg_gpt_hard = next(
        (r for r in ptg_rows if r.get("agent") == "opencode:openai/gpt-5.5" and r.get("tier") == "hard"),
        None,
    )
    ptg_s_hard = next(
        (r for r in ptg_rows if r.get("agent") == "solver" and r.get("tier") == "hard"),
        None,
    )
    if ptg_c_hard is None or ptg_c_med is None or ptg_gpt_hard is None or ptg_s_hard is None:
        raise ValueError("paired_table_gemini.json missing required headline rows")

    _assert_eq(ptg_c_hard["n"], 30, "ptg carbon hard n")
    _assert_eq(ptg_c_hard["seeds"], list(range(30)), "ptg carbon hard seeds")
    _assert_eq(round(ptg_c_hard["mean"], 3), 0.322, "ptg carbon hard rounded mean")
    _assert_eq(round(ptg_s_hard["mean"], 3), 0.499, "ptg solver hard rounded mean")
    _assert_eq(round(ptg_c_hard["ratio"] * 100), 65, "ptg carbon hard raw pct")
    _assert_eq(round(ptg_c_hard["post_expected_ratio"] * 100), 72, "ptg carbon hard LA pct")
    _assert_eq([round(ptg_c_hard["ratio_lo"] * 100), round(ptg_c_hard["ratio_hi"] * 100)], [24, 98], "ptg carbon hard raw CI pct")
    _assert_eq(
        [round(ptg_c_hard["post_expected_lo"] * 100), round(ptg_c_hard["post_expected_hi"] * 100)],
        [52, 91],
        "ptg carbon hard LA CI pct",
    )

    rep_c_hard = next(
        r for r in rep["primary_v14_0_29"]["rows"]
        if r["agent"] == "opencode:google/gemini-4-carbon" and r["tier"] == "hard" and "alternative" not in r["label"]
    )
    g2_c_hard = g2["families"]["carbon"]["paired_vs_solver"]
    inf_c_hard = inf["imputation_sensitivity_0_29"]["hard_0_29_regimes"][0]
    mol_c_hard = next(
        r["overall"] for r in mol["blocks"]["primary_hard_0_29"] if r["cohort_id"] == "opencode_carbon_hard_0_29"
    )
    mol_s_hard = next(
        r["overall"] for r in mol["blocks"]["primary_hard_0_29"] if r["cohort_id"] == "solver_hard_0_29"
    )
    trj_c_hard = next(c for c in trj["cohorts"] if c["cohort_id"] == "opencode_gemini_4_carbon_hard")
    trj_s_hard = next(c for c in trj["cohorts"] if c["cohort_id"] == "solver_hard_0_29")
    fsc_h_pair = fsc["paired_hard_headline_0_29"]

    for lbl, val in (
        ("rep.carbon_hard.mean", rep_c_hard["mean"]),
        ("g2.carbon_hard.mean", g2_c_hard["mean_score"]),
        ("inf.carbon_hard.mean", inf_c_hard["mean"]),
        ("mol.carbon_hard.raw", mol_c_hard["raw"]),
        ("trj.carbon_hard.mean", trj_c_hard["outcomes"]["mean_score"]),
        ("fsc.carbon_hard.mean", fsc_h_pair["carbon_mean_score"]),
    ):
        _assert_close(val, ptg_c_hard["mean"], 1e-4, lbl)

    for lbl, val in (
        ("rep.carbon_hard.pe", rep_c_hard["post_expected"]),
        ("g2.carbon_hard.pe", g2_c_hard["mean_post_expected"]),
        ("inf.carbon_hard.pe", inf_c_hard["post_expected"]),
        ("mol.carbon_hard.luck", mol_c_hard["luck"]),
        ("fsc.carbon_hard.pe", fsc_h_pair["carbon_mean_post_expected"]),
    ):
        _assert_close(val, ptg_c_hard["post_expected"], 1e-4, lbl)

    for lbl, val in (
        ("rep.carbon_hard.ratio", rep_c_hard["ratio"]),
        ("g2.carbon_hard.ratio", g2_c_hard["raw_ratio_vs_solver"]),
        ("inf.carbon_hard.ratio", inf_c_hard["ratio"]),
        ("fsc.carbon_hard.ratio", fsc_h_pair["raw_ratio_vs_solver"]),
    ):
        _assert_close(val, ptg_c_hard["ratio"], 1e-5, lbl)

    for lbl, val in (
        ("rep.carbon_hard.la_ratio", rep_c_hard["post_expected_ratio"]),
        ("g2.carbon_hard.la_ratio", g2_c_hard["luck_adjusted_ratio_vs_solver"]),
        ("inf.carbon_hard.la_ratio", inf_c_hard["post_expected_ratio"]),
        ("mol.carbon_hard.la_ratio", mol_c_hard["ratio"]),
        ("fsc.carbon_hard.la_ratio", fsc_h_pair["luck_adjusted_ratio_vs_solver"]),
    ):
        _assert_close(val, ptg_c_hard["post_expected_ratio"], 1e-4, lbl)

    for lbl, val in (
        ("rep.solver_hard.mean", rep_c_hard["solver_same_seeds"]),
        ("g2.solver_hard.mean", g2["solver_baseline_hard_0_29"]["mean_score"]),
        ("inf.solver_hard.mean", inf_c_hard["solver_same_seeds"]),
        ("mol.solver_hard.raw", mol_s_hard["raw"]),
        ("trj.solver_hard.mean", trj_s_hard["outcomes"]["mean_score"]),
        ("fsc.solver_hard.mean", fsc_h_pair["solver_mean_score"]),
    ):
        _assert_close(val, ptg_s_hard["mean"], 1e-5, lbl)

    _assert_eq(ptg_gpt_hard["n"], 30, "ptg gpt55 hard n")
    _assert_eq(ptg_gpt_hard["n_p"], 28, "ptg gpt55 hard n_p")
    _assert_eq(round(ptg_gpt_hard["mean"], 3), 0.504, "ptg gpt55 hard rounded mean")
    _assert_eq(round(ptg_gpt_hard["ratio"] * 100), 101, "ptg gpt55 hard raw pct")
    _assert_eq(round(ptg_gpt_hard["post_expected_ratio"] * 100), 84, "ptg gpt55 hard LA pct")
    _assert_eq([round(ptg_gpt_hard["ratio_lo"] * 100), round(ptg_gpt_hard["ratio_hi"] * 100)], [79, 140], "ptg gpt55 raw CI pct")
    _assert_eq(
        [round(ptg_gpt_hard["post_expected_lo"] * 100), round(ptg_gpt_hard["post_expected_hi"] * 100)],
        [67, 103],
        "ptg gpt55 LA CI pct",
    )

    rep_gpt = next(r for r in rep["primary_v14_0_29"]["rows"] if r["agent"] == "opencode:openai/gpt-5.5")
    g2_gpt = g2["committed_v14_and_gpt55_comparison"]["gpt_5_5_hard_0_29"]
    inf_gpt = inf["imputation_sensitivity_0_29"]["gpt55_hard_0_29_audit"]
    mol_gpt = next(
        r["overall"] for r in mol["blocks"]["primary_hard_0_29"] if r["cohort_id"] == "opencode_gpt55_hard_0_29"
    )
    que_gpt = que["corpus_reconciliation"]["gpt55_hard_0_29_committed"]
    trj_gpt = next(c for c in trj["cohorts"] if c["cohort_id"] == "opencode_gpt_5_5_hard")

    for lbl, val in (
        ("rep.gpt55.mean", rep_gpt["mean"]),
        ("g2.gpt55.mean", g2_gpt["paired_vs_solver"]["mean_score"]),
        ("inf.gpt55.mean", inf_gpt["regime_metrics"]["mean"]),
        ("mol.gpt55.raw", mol_gpt["raw"]),
        ("trj.gpt55.mean", trj_gpt["outcomes"]["mean_score"]),
    ):
        _assert_close(val, ptg_gpt_hard["mean"], 1e-4, lbl)

    for lbl, val in (
        ("rep.gpt55.pe", rep_gpt["post_expected"]),
        ("g2.gpt55.pe", g2_gpt["paired_vs_solver"]["mean_post_expected"]),
        ("inf.gpt55.pe", inf_gpt["regime_metrics"]["post_expected"]),
        ("mol.gpt55.luck", mol_gpt["luck"]),
    ):
        _assert_close(val, ptg_gpt_hard["post_expected"], 1e-4, lbl)

    for lbl, val in (
        ("rep.gpt55.la_ratio", rep_gpt["post_expected_ratio"]),
        ("g2.gpt55.la_ratio", g2_gpt["paired_vs_solver"]["luck_adjusted_ratio_vs_solver"]),
        ("inf.gpt55.la_ratio", inf_gpt["regime_metrics"]["post_expected_ratio"]),
        ("mol.gpt55.la_ratio", mol_gpt["ratio"]),
    ):
        _assert_close(val, ptg_gpt_hard["post_expected_ratio"], 1e-4, lbl)

    for lbl, seeds_val in (
        ("g2.gpt55.non_accuse_seeds", g2_gpt["clean_rc0_non_accuse_zero_day_seeds"]),
        ("inf.gpt55.non_accuse_seeds", inf_gpt["clean_rc0_non_accusation_stop_seeds"]),
        ("mol.gpt55.non_accuse_seeds", mol["provenance_and_locks"]["gpt_5_5_hard_0_29"]["clean_rc0_non_accuse_zero_day_seeds"]),
        ("que.gpt55.non_accuse_seeds", que_gpt["clean_unended_rc0_seeds"]),
    ):
        _assert_eq(seeds_val, EXPECTED_GPT55_NON_ACCUSE_SEEDS, lbl)

    _assert_eq(g2_gpt["accused_count"], 28, "g2.gpt55.accused_count")
    _assert_eq(g2_gpt["correct_count"], 28, "g2.gpt55.correct_count")
    _assert_eq(inf_gpt["excluded_attempts_total"], 0, "inf.gpt55.excluded_attempts_total")
    _assert_eq(que_gpt["infra_excluded"], 0, "que.gpt55.infra_excluded")
    _assert_eq(trj_gpt["collateral_and_horizon"]["abstention_count"], 2, "trj.gpt55.abstention_count")
    _assert_eq(trj_gpt["outcomes"]["wrong_accusation_count"], 0, "trj.gpt55.wrong_accusation_count")

    for lbl, g1_seeds in (
        ("rep.g1.seeds", rep["g1_committed_ext_hard_n2"]["seeds"]),
        ("inf.g1.seeds", inf["ext_survivor_duration_audit"]["completed_seeds"]),
        ("mol.g1.seeds", mol["provenance_and_locks"]["g1_hard_30_59_extension"]["completed_seeds"]),
        ("que.g1.seeds", que["corpus_reconciliation"]["carbon_hard_30_59_extension"]["committed_g1_partial"]["landed_seeds"]),
        ("trj.g1.seeds", next(c["seeds"] for c in trj["cohorts"] if c["cohort_id"] == "opencode_gemini_4_carbon_hard_ext")),
        ("fsc.g1.seeds", fsc["provenance_and_locks"]["g1_hard_30_59_extension"]["completed_seeds"]),
    ):
        _assert_eq(g1_seeds, EXPECTED_G1_SEEDS, lbl)

    for lbl, fr8_seeds in (
        ("rep.fr8.seeds", rep["pre_registered_rule"]["replication_carbon_hard_seeds"]),
        ("inf.fr8.seeds", inf["ext_survivor_duration_audit"]["fr8_replication_carbon_hard"]["seeds"]),
        ("mol.fr8.seeds", next(r["seeds"] for r in mol["blocks"]["extension_hard_30_59"] if r["cohort_id"] == "opencode_carbon_fr8_rep_hard")),
        ("que.fr8.seeds", que["corpus_reconciliation"]["carbon_hard_30_59_extension"]["fr8_replication"]["landed_seeds"]),
        ("trj.fr8.seeds", next(c["seeds"] for c in trj["cohorts"] if c["cohort_id"] == "opencode_gemini_4_carbon_hard_rep")),
        ("fsc.fr8.seeds", next(c["seeds"] for c in fsc["cohorts"] if c["cohort_id"] == "opencode_gemini_4_carbon_hard_rep")),
    ):
        _assert_eq(fr8_seeds, EXPECTED_FR8_SEEDS, lbl)

    for lbl, union_seeds in (
        ("rep.union6.seeds", rep["union_dedup_hard_n6"]["seeds"]),
        ("mol.union6.seeds", mol["gap_drivers"]["extension_6_seed_union_selection_profile"]["union_seeds"]),
        ("que.union6.seeds", que["corpus_reconciliation"]["carbon_hard_30_59_extension"]["combined_distinct_landed_seeds"]),
    ):
        _assert_eq(union_seeds, EXPECTED_UNION_SEEDS, lbl)

    _assert_eq(len(EXPECTED_UNION_SEEDS), 6, "dedup union n")
    _assert_eq(rep["union_dedup_hard_n6"]["shared_seeds"], [34], "rep union6 shared_seeds")
    _assert_eq(rep["union_dedup_hard_n6"]["dropped_duplicate_episodes"], 1, "rep union6 dropped_duplicate_episodes")
    _assert_eq(
        que["corpus_reconciliation"]["carbon_hard_30_59_extension"]["combined_remaining_count"],
        24,
        "que union6 remaining_count",
    )
    _assert_eq(
        rep["secondary_pooled_hard_reconciliation"]["all_luck_adjusted_95ci_exclude_parity"],
        True,
        "rep secondary pooled CIs exclude parity",
    )

    for lbl, c_sha in (
        ("rep.primary_episodes_commit", rep["pre_registered_rule"]["primary_episodes_commit"]),
        ("g2.primary_episodes_commit", g2["provenance_and_headline_lock"]["primary_0_29_lock"]["episodes_commit"]),
        ("inf.primary_episodes_commit", inf["seed_lock_and_replay"]["primary_commits"]["episodes_commit"]),
        ("mol.primary_episodes_commit", mol["provenance_and_locks"]["primary_0_29_lock"]["episodes_commit"]),
        ("que.primary_episodes_commit", que["provenance_honesty"]["cohorts"]["primary_carbon_0_29"]["episodes_commit"]),
        ("trj.primary_episodes_commit", trj["provenance_and_locks"]["primary_0_29_lock"]["episodes_commit"]),
        ("fsc.primary_episodes_commit", fsc["provenance_and_locks"]["primary_0_29_lock"]["episodes_commit"]),
    ):
        _assert_eq(c_sha, "8fd4dec", lbl)

    for lbl, l_sha in (
        ("rep.primary_lock_commit", rep["pre_registered_rule"]["primary_lock_commit"]),
        ("g2.primary_lock_commit", g2["provenance_and_headline_lock"]["primary_0_29_lock"]["seed_lock_commit"]),
        ("inf.primary_lock_commit", inf["seed_lock_and_replay"]["primary_commits"]["seed_lock_commit"]),
        ("mol.primary_lock_commit", mol["provenance_and_locks"]["primary_0_29_lock"]["lock_commit"]),
        ("que.primary_lock_commit", que["provenance_honesty"]["cohorts"]["primary_carbon_0_29"]["lock_commit"]),
        ("trj.primary_lock_commit", trj["provenance_and_locks"]["primary_0_29_lock"]["lock_commit"]),
        ("fsc.primary_lock_commit", fsc["provenance_and_locks"]["primary_0_29_lock"]["seed_lock_commit"]),
    ):
        _assert_eq(l_sha, "671ed96", lbl)

    for lbl, pr_sha in (
        ("rep.g1_prereg", rep["pre_registered_rule"]["g1_prereg_commit"]),
        ("g2.prereg", g2["provenance_and_headline_lock"]["g2_families_provenance"]["prereg_commit"]),
        ("inf.g1_prereg", inf["seed_lock_and_replay"]["extension_preregistration_commit"]),
        ("mol.g1_prereg", mol["provenance_and_locks"]["g1_hard_30_59_extension"]["prereg_commit"]),
        ("que.g1_prereg", que["provenance_honesty"]["cohorts"]["g1_carbon_hard_30_59"]["pre_registered_commit"]),
        ("trj.g1_prereg", trj["provenance_and_locks"]["g1_hard_30_59_extension"]["prereg_commit"]),
        ("fsc.g1_prereg", fsc["provenance_and_locks"]["g1_hard_30_59_extension"]["prereg_commit"]),
    ):
        _assert_eq(pr_sha, "f9fb7a4a", lbl)

    for lbl, gpt_sha in (
        ("rep.gpt55_prereg", rep["pre_registered_rule"]["gpt_5_5_prereg_commit"]),
        ("inf.gpt55_prereg", inf["seed_lock_and_replay"]["gpt55_preregistration_commit"]),
        ("mol.gpt55_prereg", mol["provenance_and_locks"]["gpt_5_5_hard_0_29"]["prereg_commit"]),
        ("que.gpt55_prereg", que["provenance_honesty"]["cohorts"]["gpt_5_5_hard_0_29"]["pre_registered_commit"]),
        ("trj.gpt55_prereg", trj["provenance_and_locks"]["gpt_5_5_hard_0_29"]["prereg_commit"]),
        ("fsc.gpt55_prereg", fsc["provenance_and_locks"]["gpt_5_5_second_family"]["prereg_commit"]),
    ):
        _assert_eq(gpt_sha, "cf394894", lbl)

    g2_arg = g2["families"]["argon"]["paired_vs_solver"]
    g2_hyd = g2["families"]["hydrogen"]["paired_vs_solver"]
    _assert_eq(round(g2_arg["mean_score"], 3), 0.512, "g2 argon raw mean")
    _assert_eq(round(g2_arg["raw_ratio_vs_solver"] * 100), 103, "g2 argon raw pct")
    _assert_eq(round(g2_arg["luck_adjusted_ratio_vs_solver"] * 100), 60, "g2 argon LA pct")
    _assert_eq(g2["verification_totals"]["argon_exceeding_900s_count"], 30, "g2 argon >900s")
    _assert_eq(g2["verification_totals"]["argon_exceeding_3600s_count"], 0, "g2 argon >3600s")
    _assert_eq(round(g2_hyd["mean_score"], 3), 0.575, "g2 hydrogen raw mean")
    _assert_eq(round(g2_hyd["raw_ratio_vs_solver"] * 100), 115, "g2 hydrogen raw pct")
    _assert_eq(round(g2_hyd["luck_adjusted_ratio_vs_solver"] * 100), 97, "g2 hydrogen LA pct")
    _assert_eq(g2["verification_totals"]["hydrogen_exceeding_900s_count"], 0, "g2 hydrogen >900s")

    flash_med = rep["cohort_c_flash_and_cross_model"]["flash_medium_n29_row"]
    _assert_eq(flash_med["n"], 30, "flash medium n")
    _assert_eq(round(flash_med["mean"], 3), 0.434, "flash medium raw mean")
    _assert_eq(round(flash_med["ratio"] * 100), 67, "flash medium raw pct")
    _assert_eq(round(flash_med["post_expected_ratio"] * 100), 75, "flash medium LA pct")

    g1_row = rep["g1_committed_ext_hard_n2"]["rows"][0]
    fr8_row = rep["cohort_a_carbon_hard_replication"]["paired_5_seeds_rows"][0]
    u6_row = rep["union_dedup_hard_n6"]["rows"][0]
    p32_row = rep["secondary_pooled_hard_reconciliation"]["n32_primary_plus_g1"]["rows"][0]
    p35_row = rep["cohort_b_secondary_pooled_hard_n35"]["rows"][0]
    p36_row = rep["secondary_pooled_hard_reconciliation"]["n36_primary_plus_union6"]["rows"][0]

    deliverable_rows = []
    for spec in (MASTER_SUITE_SPEC, *UPSTREAM_JSON_SPECS):
        deliverable_rows.append(
            {
                "deliverable_id": spec["deliverable_id"],
                "script_rel": spec["script_rel"],
                "json_rel": spec["json_rel"],
                "max_json_bytes": int(spec["max_bytes"]),
                "report_rel": spec["report_rel"],
                "test_rel": spec["test_rel"],
                "cohort_n_summary": spec["cohort_n_summary"],
                "verify_cmd": spec["verify_cmd"],
            }
        )

    return {
        "schema_version": SCHEMA_VERSION,
        "tiers_version": TIERS_VERSION,
        "pure_cpu_zero_api_calls": True,
        "zero_subprocesses": True,
        "zero_git_history_calls": True,
        "upstream_justsilas_sync_commit": "5f9b3297",
        "corpus_totals": {
            "committed_v14_episodes": EXPECTED_COMMITTED_EPISODES,
            "replication_v14_episodes": EXPECTED_REPLICATION_EPISODES,
            "combined_v14_episodes": EXPECTED_COMBINED_EPISODES,
            "g2_cross_family_hard_episodes": 60,
            "committed_plus_g2_episodes": EXPECTED_COMMITTED_EPISODES + 60,
            "replay_mismatches": 0,
            "duplicate_episodes": 0,
        },
        "provenance_locks": {
            "primary_0_29_classification": "post_hoc_lock",
            "primary_episodes_commit": "8fd4dec",
            "primary_lock_commit": "671ed96",
            "primary_lock_delay_s": 28,
            "g1_and_g2_prereg_commit": "f9fb7a4a",
            "gpt_5_5_prereg_commit": "cf394894",
            "gpt_5_5_results_commit": "ca0a0dc0",
            "step_error_detail_compat_commit": "1bc3e281",
            "shared_seed_dedup_rule_commit": "eb9dee54",
        },
        "headline_and_cross_model": {
            "primary_carbon_hard_0_29": {
                "agent": "opencode:google/gemini-4-carbon",
                "tier": "hard",
                "n": 30,
                "mean_score": round(ptg_c_hard["mean"], 6),
                "ci_score": round(ptg_c_hard["ci"], 6),
                "solver_mean_score": round(ptg_s_hard["mean"], 6),
                "raw_ratio_pct": 65,
                "raw_ratio_ci_pct": [24, 98],
                "post_expected": round(ptg_c_hard["post_expected"], 6),
                "solver_post_expected": round(ptg_c_hard["solver_post_expected"], 6),
                "luck_adjusted_ratio_pct": 72,
                "luck_adjusted_ratio_ci_pct": [52, 91],
            },
            "primary_carbon_medium_0_29": {
                "agent": "opencode:google/gemini-4-carbon",
                "tier": "medium",
                "n": 30,
                "mean_score": round(ptg_c_med["mean"], 6),
                "solver_mean_score": round(ptg_c_med["solver_same_seeds"], 6),
                "raw_ratio_pct": round(ptg_c_med["ratio"] * 100),
                "raw_ratio_ci_pct": [round(ptg_c_med["ratio_lo"] * 100), round(ptg_c_med["ratio_hi"] * 100)],
                "post_expected": round(ptg_c_med["post_expected"], 6),
                "luck_adjusted_ratio_pct": round(ptg_c_med["post_expected_ratio"] * 100),
                "luck_adjusted_ratio_ci_pct": [
                    round(ptg_c_med["post_expected_lo"] * 100),
                    round(ptg_c_med["post_expected_hi"] * 100),
                ],
            },
            "gpt_5_5_hard_0_29": {
                "agent": "opencode:openai/gpt-5.5",
                "tier": "hard",
                "n": 30,
                "accused_count": 28,
                "correct_count": 28,
                "clean_rc0_non_accuse_seeds": list(EXPECTED_GPT55_NON_ACCUSE_SEEDS),
                "infra_excluded_attempts": 0,
                "mean_score": round(ptg_gpt_hard["mean"], 6),
                "ci_score": round(ptg_gpt_hard["ci"], 6),
                "solver_mean_score": round(ptg_gpt_hard["solver_same_seeds"], 6),
                "raw_ratio_pct": 101,
                "raw_ratio_ci_pct": [79, 140],
                "post_expected": round(ptg_gpt_hard["post_expected"], 6),
                "luck_adjusted_ratio_pct": 84,
                "luck_adjusted_ratio_ci_pct": [67, 103],
            },
            "g2_argon_hard_0_29": {
                "agent": "opencode:google/gemini-4-argon",
                "tier": "hard",
                "n": 30,
                "mean_score": round(g2_arg["mean_score"], 6),
                "raw_ratio_pct": 103,
                "raw_ratio_ci_pct": [71, 144],
                "post_expected": round(g2_arg["mean_post_expected"], 6),
                "luck_adjusted_ratio_pct": 60,
                "luck_adjusted_ratio_ci_pct": [33, 85],
                "exceed_900s_count": 30,
                "exceed_3600s_count": 0,
            },
            "g2_hydrogen_hard_0_29": {
                "agent": "opencode:google/gemini-4-hydrogen",
                "tier": "hard",
                "n": 30,
                "mean_score": round(g2_hyd["mean_score"], 6),
                "raw_ratio_pct": 115,
                "raw_ratio_ci_pct": [92, 157],
                "post_expected": round(g2_hyd["mean_post_expected"], 6),
                "luck_adjusted_ratio_pct": 97,
                "luck_adjusted_ratio_ci_pct": [75, 119],
                "exceed_900s_count": 0,
                "exceed_3600s_count": 0,
            },
            "fr8_flash_medium_0_29": {
                "agent": "opencode:google/gemini-3.5-flash",
                "tier": "medium",
                "n": 30,
                "mean_score": round(flash_med["mean"], 6),
                "raw_ratio_pct": 67,
                "raw_ratio_ci_pct": [29, 103],
                "post_expected": round(flash_med["post_expected"], 6),
                "luck_adjusted_ratio_pct": 75,
                "luck_adjusted_ratio_ci_pct": [45, 105],
            },
        },
        "carbon_hard_30_59_reconciliation": {
            "g1_committed_ext": {
                "n": 2,
                "seeds": list(EXPECTED_G1_SEEDS),
                "provider_quota_excluded": 31,
                "mean_score": round(g1_row["mean"], 6),
                "post_expected": round(g1_row["post_expected"], 6),
                "solver_same_seeds": round(g1_row["solver_same_seeds"], 6),
                "raw_ratio_pct": round(g1_row["ratio"] * 100),
                "luck_adjusted_ratio_pct": round(g1_row["post_expected_ratio"] * 100),
            },
            "fr8_replication": {
                "n": 5,
                "seeds": list(EXPECTED_FR8_SEEDS),
                "mean_score": round(fr8_row["mean"], 6),
                "post_expected": round(fr8_row["post_expected"], 6),
                "solver_same_seeds": round(fr8_row["solver_same_seeds"], 6),
                "raw_ratio_pct": round(fr8_row["ratio"] * 100),
                "luck_adjusted_ratio_pct": round(fr8_row["post_expected_ratio"] * 100),
            },
            "dedup_union_n6": {
                "n": 6,
                "seeds": list(EXPECTED_UNION_SEEDS),
                "shared_seeds": [34],
                "shared_seed_precedence": "committed_g1_per_eb9dee54",
                "dropped_duplicate_episodes": 1,
                "remaining_unplayed_seeds_count": 24,
                "mean_score": round(u6_row["mean"], 6),
                "post_expected": round(u6_row["post_expected"], 6),
                "solver_same_seeds": round(u6_row["solver_same_seeds"], 6),
                "raw_ratio_pct": round(u6_row["ratio"] * 100),
                "luck_adjusted_ratio_pct": round(u6_row["post_expected_ratio"] * 100),
            },
            "secondary_pooled_sensitivity": {
                "classification": "secondary_sensitivity_only",
                "all_la_95ci_exclude_parity": True,
                "n32_la_ratio_pct": round(p32_row["post_expected_ratio"] * 100),
                "n35_la_ratio_pct": round(p35_row["post_expected_ratio"] * 100),
                "n36_la_ratio_pct": round(p36_row["post_expected_ratio"] * 100),
            },
        },
        "harbor_rehearsal": harbor_summary,
        "hygiene_and_caps": {
            "all_json_within_byte_caps": True,
            "suite_manifest_max_bytes": MAX_JSON_BYTES,
            "upstream_json_count": len(UPSTREAM_JSON_SPECS),
            "total_frontier_deliverables": len(deliverable_rows),
            "zero_secrets_verified": True,
            "zero_em_en_dashes_verified": True,
        },
        "deliverables": deliverable_rows,
    }


def render_markdown(manifest: dict[str, Any]) -> str:
    ct = manifest["corpus_totals"]
    pl = manifest["provenance_locks"]
    hc = manifest["headline_and_cross_model"]
    ch = hc["primary_carbon_hard_0_29"]
    cm = hc["primary_carbon_medium_0_29"]
    gp = hc["gpt_5_5_hard_0_29"]
    ar = hc["g2_argon_hard_0_29"]
    hy = hc["g2_hydrogen_hard_0_29"]
    fl = hc["fr8_flash_medium_0_29"]
    ext = manifest["carbon_hard_30_59_reconciliation"]
    g1 = ext["g1_committed_ext"]
    fr8 = ext["fr8_replication"]
    u6 = ext["dedup_union_n6"]
    sp = ext["secondary_pooled_sensitivity"]
    hr = manifest["harbor_rehearsal"]

    lines: list[str] = [
        f"{H1} Canary v1.4 Frontier Replication and Forensics Master Index",
        "",
        "Single-entry judge index and cross-artifact consistency manifest for all `frontier` v1.4 replication, cross-family, sensitivity, trajectory, and transcript forensics deliverables (`0` live API calls, `0` subprocesses, `0` `.git` runtime calls).",
        "",
        "Fast offline master check (`< 1.5s`, keyless):",
        "",
        "```bash",
        "PYTHONPATH=. python scripts/verify_frontier_suite.py --check",
        "PYTHONPATH=. pytest -q tests/test_frontier_suite_master.py",
        "```",
        "",
        f"{H2} 1. Corpus Totals and Provenance Locks (Synced with `justSilas@{manifest['upstream_justsilas_sync_commit']}`)",
        "",
        f"- **Replay-verified v1.4 corpus (`{ct['combined_v14_episodes']}` episodes, `{ct['replay_mismatches']}` mismatches, `{ct['duplicate_episodes']}` duplicates):** `{ct['committed_v14_episodes']}` committed episodes in `data/runs/committed/v1.4/` plus `{ct['replication_v14_episodes']}` FR8 replication episodes in `results/frontier_replication/v1.4/` (`{ct['committed_v14_episodes']} + {ct['replication_v14_episodes']} = {ct['combined_v14_episodes']}`), alongside `{ct['g2_cross_family_hard_episodes']}` G2 Gemini-4 cross-family hard episodes (`{ct['committed_plus_g2_episodes']}` with committed) and `{hr['total_valid_opencode_trials']}` valid OpenCode Harbor judge-path rehearsal trials (`10 + 10 + 9`).",
        f"- **Registration and lock honesty:** Primary `gemini-4-carbon` `seeds 0-29` (`{pl['primary_episodes_commit']}`) are governed by a **post-hoc seed lock** (`{pl['primary_lock_commit']}`, `{pl['primary_lock_delay_s']}s` after `{pl['primary_episodes_commit']}`), never mislabeled as pre-registered. Pre-registered extensions/families: G1 `gemini-4-carbon` hard `30-59` and G2 `gemini-4-argon` / `gemini-4-hydrogen` hard `0-29` (`{pl['g1_and_g2_prereg_commit']}`), and OpenAI `gpt-5.5` hard `0-29` (`{pl['gpt_5_5_prereg_commit']}`, committed at `{pl['gpt_5_5_results_commit']}`). Step replay applies `{pl['step_error_detail_compat_commit']}` MCP error unwrapping, and repeated extension seeds deduplicate with committed G1 precedence (`{pl['shared_seed_dedup_rule_commit']}`).",
        "",
        f"{H2} 2. Frontier Deliverables Master Index (Scripts, JSON Artifacts, Reports, Cohort N, Commands)",
        "",
        "| deliverable | script | JSON artifact (byte cap) | report | cohort N / scope | verification command |",
        "|---|---|---|---|---|---|",
    ]

    for d in manifest["deliverables"]:
        rep_cell = f"`{d['report_rel']}`" if d["report_rel"] else "indexed here (manifest-only)"
        lines.append(
            f"| `{d['deliverable_id']}` | `{d['script_rel']}` | `{d['json_rel']}` (`<={d['max_json_bytes']}` B) | "
            f"{rep_cell} | {d['cohort_n_summary']} | `{d['verify_cmd']}` |"
        )

    lines.extend(
        [
            "",
            f"{H2} 3. Cross-Artifact Headline, Cross-Model, Extension, and Harbor Rehearsal Summary",
            "",
            "| cohort / track | tier & seeds | n | raw score | solver raw | frontier / solver [95% CI] | luck-adj. score | luck-adj. / solver [95% CI] | provenance / note |",
            "|---|---|---:|---:|---:|---|---:|---|---|",
            f"| **OpenCode `gemini-4-carbon` (PRIMARY)** | hard `0-29` | {ch['n']} | {ch['mean_score']:.3f} | {ch['solver_mean_score']:.3f} | **{ch['raw_ratio_pct']}% [{ch['raw_ratio_ci_pct'][0]}%, {ch['raw_ratio_ci_pct'][1]}%]** | {ch['post_expected']:.3f} | **{ch['luck_adjusted_ratio_pct']}% [{ch['luck_adjusted_ratio_ci_pct'][0]}%, {ch['luck_adjusted_ratio_ci_pct'][1]}%]** | locked primary (`{pl['primary_lock_commit']}`) |",
            f"| OpenCode `gemini-4-carbon` | medium `0-29` | {cm['n']} | {cm['mean_score']:.3f} | {cm['solver_mean_score']:.3f} | {cm['raw_ratio_pct']}% [{cm['raw_ratio_ci_pct'][0]}%, {cm['raw_ratio_ci_pct'][1]}%] | {cm['post_expected']:.3f} | {cm['luck_adjusted_ratio_pct']}% [{cm['luck_adjusted_ratio_ci_pct'][0]}%, {cm['luck_adjusted_ratio_ci_pct'][1]}%] | locked primary (`{pl['primary_lock_commit']}`) |",
            f"| OpenCode `gpt-5.5` (OpenAI family 2) | hard `0-29` | {gp['n']} | {gp['mean_score']:.3f} | {gp['solver_mean_score']:.3f} | **{gp['raw_ratio_pct']}% [{gp['raw_ratio_ci_pct'][0]}%, {gp['raw_ratio_ci_pct'][1]}%]** | {gp['post_expected']:.3f} | **{gp['luck_adjusted_ratio_pct']}% [{gp['luck_adjusted_ratio_ci_pct'][0]}%, {gp['luck_adjusted_ratio_ci_pct'][1]}%]** | pre-reg `{pl['gpt_5_5_prereg_commit']}`; `rc=0` non-accuse `{gp['clean_rc0_non_accuse_seeds']}` |",
            f"| OpenCode `gemini-4-argon` (G2) | hard `0-29` | {ar['n']} | {ar['mean_score']:.3f} | {ch['solver_mean_score']:.3f} | {ar['raw_ratio_pct']}% [{ar['raw_ratio_ci_pct'][0]}%, {ar['raw_ratio_ci_pct'][1]}%] | {ar['post_expected']:.3f} | {ar['luck_adjusted_ratio_pct']}% [{ar['luck_adjusted_ratio_ci_pct'][0]}%, {ar['luck_adjusted_ratio_ci_pct'][1]}%] | pre-reg `{pl['g1_and_g2_prereg_commit']}` (`30/30 > 900s`) |",
            f"| OpenCode `gemini-4-hydrogen` (G2) | hard `0-29` | {hy['n']} | {hy['mean_score']:.3f} | {ch['solver_mean_score']:.3f} | {hy['raw_ratio_pct']}% [{hy['raw_ratio_ci_pct'][0]}%, {hy['raw_ratio_ci_pct'][1]}%] | {hy['post_expected']:.3f} | {hy['luck_adjusted_ratio_pct']}% [{hy['luck_adjusted_ratio_ci_pct'][0]}%, {hy['luck_adjusted_ratio_ci_pct'][1]}%] | pre-reg `{pl['g1_and_g2_prereg_commit']}` (`0/30 > 900s`) |",
            f"| OpenCode `gemini-3.5-flash` (FR8) | medium `0-29` | {fl['n']} | {fl['mean_score']:.3f} | {cm['solver_mean_score']:.3f} | {fl['raw_ratio_pct']}% [{fl['raw_ratio_ci_pct'][0]}%, {fl['raw_ratio_ci_pct'][1]}%] | {fl['post_expected']:.3f} | {fl['luck_adjusted_ratio_pct']}% [{fl['luck_adjusted_ratio_ci_pct'][0]}%, {fl['luck_adjusted_ratio_ci_pct'][1]}%] | FR8 cross-model replication |",
            f"| OpenCode `gemini-4-carbon` G1 ext | hard `{g1['seeds']}` | {g1['n']} | {g1['mean_score']:.3f} | {g1['solver_same_seeds']:.3f} | {g1['raw_ratio_pct']}% | {g1['post_expected']:.3f} | {g1['luck_adjusted_ratio_pct']}% | pre-reg `{pl['g1_and_g2_prereg_commit']}` (`{g1['provider_quota_excluded']}` quota excl.) |",
            f"| OpenCode `gemini-4-carbon` FR8 rep | hard `{fr8['seeds']}` | {fr8['n']} | {fr8['mean_score']:.3f} | {fr8['solver_same_seeds']:.3f} | {fr8['raw_ratio_pct']}% | {fr8['post_expected']:.3f} | {fr8['luck_adjusted_ratio_pct']}% | FR8 `--timeout 3600` shards |",
            f"| OpenCode `gemini-4-carbon` dedup union | hard `{u6['seeds']}` | {u6['n']} | {u6['mean_score']:.3f} | {u6['solver_same_seeds']:.3f} | {u6['raw_ratio_pct']}% | {u6['post_expected']:.3f} | {u6['luck_adjusted_ratio_pct']}% | G1 precedence on `[34]` (`{pl['shared_seed_dedup_rule_commit']}`); secondary `n=32/35/36` LA `{sp['n32_la_ratio_pct']}%/{sp['n35_la_ratio_pct']}%/{sp['n36_la_ratio_pct']}%` |",
            "",
            f"{H3} 3.1 Harbor 0.26.0 Judge-Path Rehearsal (`results/harbor/rehearsal/TABLE.md`, tag `{hr['tag']}`)",
            "",
            "| run | valid trials | infra excluded | mean score | oracle (same tasks) | run / oracle [95% CI] | note |",
            "|---|---:|---:|---:|---|---|---|",
            f"| `opencode-1` | {hr['runs'][0]['n_valid']} | {hr['runs'][0]['infra_excluded']} | +{hr['runs'][0]['mean']:.3f} | +{hr['runs'][0]['oracle_same_tasks']:.3f} | **{hr['runs'][0]['ratio_pct']}% [{hr['runs'][0]['ci_pct'][0]}%, {hr['runs'][0]['ci_pct'][1]}%]** | complete 10/10 |",
            f"| `opencode-2` | {hr['runs'][1]['n_valid']} | {hr['runs'][1]['infra_excluded']} | +{hr['runs'][1]['mean']:.3f} | +{hr['runs'][1]['oracle_same_tasks']:.3f} | **{hr['runs'][1]['ratio_pct']}% [{hr['runs'][1]['ci_pct'][0]}%, {hr['runs'][1]['ci_pct'][1]}%]** | complete 10/10 |",
            f"| `opencode-3` (final `{hr['final_branch_commit']}`) | {hr['runs'][2]['n_valid']} | {hr['runs'][2]['infra_excluded']} | +{hr['runs'][2]['mean']:.3f} | same 9 tasks | **{hr['runs'][2]['ratio_pct']}% [{hr['runs'][2]['ci_pct'][0]}%, {hr['runs'][2]['ci_pct'][1]}%]** | supersedes 08:52 7-trial `{hr['runs'][2]['snapshot_0852_ratio_pct']}%` snapshot |",
            "",
            f"{H2} 4. Full Suite Verification Commands",
            "",
            "```bash",
            "PYTHONPATH=. python scripts/verify_frontier_suite.py --check",
            "PYTHONPATH=. python scripts/verify_replay.py data/runs/committed/v1.4 results/frontier_replication/v1.4",
            "PYTHONPATH=. pytest -q " + " ".join(d["test_rel"] for d in manifest["deliverables"]),
            "```",
            "",
        ]
    )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    t0 = time.perf_counter()
    ap = argparse.ArgumentParser(
        description="Offline master consistency verifier for Canary v1.4 frontier deliverables."
    )
    ap.add_argument("--root", default=str(ROOT), help="repository root directory")
    ap.add_argument("--out-json", default=None, help="override suite_manifest_v14.json path")
    ap.add_argument("--out-md", default=None, help="override frontier_master_index_v14.md path")
    ap.add_argument("--write", action="store_true", help="write suite_manifest_v14.json and frontier_master_index_v14.md")
    ap.add_argument("--check", action="store_true", help="verify byte-identity and cross-artifact consistency")
    ap.add_argument("--stdout", action="store_true", help="print rendered markdown index to stdout")
    args = ap.parse_args(argv)

    if args.write and args.check:
        ap.error("pass either --write or --check, not both")

    root = Path(args.root).resolve()
    out_json = Path(args.out_json).resolve() if args.out_json else default_json_path(root)
    out_md = Path(args.out_md).resolve() if args.out_md else default_md_path(root)

    if args.check:
        if not out_json.is_file():
            print(f"FAIL: missing {out_json}", file=sys.stderr)
            return 1
        if not out_md.is_file():
            print(f"FAIL: missing {out_md}", file=sys.stderr)
            return 1
        if out_json.stat().st_size > MAX_JSON_BYTES:
            print(
                f"FAIL: {out_json} is {out_json.stat().st_size} bytes (> {MAX_JSON_BYTES})",
                file=sys.stderr,
            )
            return 1

    try:
        manifest = compute_suite_manifest(root=root)
        json_blob = serialize_manifest_json(manifest)
        md_blob = render_markdown(manifest)
    except (ValueError, KeyError, OSError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1

    json_bytes = json_blob.encode("utf-8")
    md_bytes = md_blob.encode("utf-8")

    own_secrets = scan_secrets_bytes(json_bytes, str(out_json)) + scan_secrets_bytes(md_bytes, str(out_md))
    own_dashes = scan_dashes_text(json_blob, str(out_json)) + scan_dashes_text(md_blob, str(out_md))
    if own_secrets or own_dashes:
        print(f"FAIL: generated output hygiene error secrets={own_secrets} dashes={own_dashes}", file=sys.stderr)
        return 1

    if args.check:
        disk_json = out_json.read_bytes()
        disk_md = out_md.read_bytes()
        disk_hygiene = (
            scan_secrets_bytes(disk_json, str(out_json))
            + scan_secrets_bytes(disk_md, str(out_md))
            + scan_dashes_text(disk_json.decode("utf-8", errors="replace"), str(out_json))
            + scan_dashes_text(disk_md.decode("utf-8", errors="replace"), str(out_md))
        )
        if disk_hygiene:
            print(f"FAIL: on-disk hygiene violation: {disk_hygiene}", file=sys.stderr)
            return 1
        if disk_json != json_bytes:
            print(f"FAIL: {out_json} is not byte-identical to fresh manifest; re-run with --write", file=sys.stderr)
            return 1
        if disk_md != md_bytes:
            print(f"FAIL: {out_md} is not byte-identical to fresh markdown index; re-run with --write", file=sys.stderr)
            return 1
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        ct = manifest["corpus_totals"]
        hr = manifest["harbor_rehearsal"]["final_ratios_pct"]
        print(
            f"OK frontier_suite=PASS episodes={ct['committed_v14_episodes']}+{ct['replication_v14_episodes']}="
            f"{ct['combined_v14_episodes']} carbon_hard=65%/72% gpt55_hard=101%/84% "
            f"harbor={hr[0]}%,{hr[1]}%,{hr[2]}% json_bytes={len(disk_json)} elapsed_ms={elapsed_ms:.1f}"
        )
        return 0

    if args.write:
        out_json.parent.mkdir(parents=True, exist_ok=True)
        out_md.parent.mkdir(parents=True, exist_ok=True)
        out_json.write_bytes(json_bytes)
        out_md.write_bytes(md_bytes)
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        print(
            f"WROTE {out_json} ({len(json_bytes)} bytes) and {out_md} ({len(md_bytes)} bytes) in {elapsed_ms:.1f} ms"
        )
        return 0

    if args.stdout:
        sys.stdout.write(md_blob)
        return 0

    sys.stdout.write(md_blob)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
