from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import check_frontier_ext_replication as checker

EXT_REL = Path("results") / "frontier_replication" / "v1.4" / "opencode-gemini-4-carbon-ext"
COMM_V14_REL = Path("data") / "runs" / "committed" / "v1.4"


def _load_checker():
    return checker


def _read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _write_override(path: Path, content: str) -> None:
    if path.is_symlink() or path.exists():
        path.unlink()
    path.write_text(content, encoding="utf-8")


def _make_symlinked_repo(base_dir: Path) -> Path:
    repo = base_dir / "repo"
    ext_dst = repo / EXT_REL
    ext_dst.mkdir(parents=True)
    for item in (ROOT / EXT_REL).iterdir():
        (ext_dst / item.name).symlink_to(item)

    comm_v14_dst = repo / COMM_V14_REL
    comm_v14_dst.mkdir(parents=True)
    for item in (ROOT / COMM_V14_REL).iterdir():
        if item.name == "opencode-gemini-4-carbon-ext":
            comm_ext_hard_dst = comm_v14_dst / item.name / "hard"
            comm_ext_hard_dst.mkdir(parents=True)
            (comm_ext_hard_dst / "episodes.jsonl").symlink_to(item / "hard" / "episodes.jsonl")
        else:
            (comm_v14_dst / item.name).symlink_to(item)
    return repo


def test_verify_frontier_ext_replication_root():
    mod = _load_checker()
    comm_eps = _read_jsonl(ROOT / COMM_V14_REL / "opencode-gemini-4-carbon-ext" / "hard" / "episodes.jsonl")
    report = mod.verify_frontier_ext_replication(ROOT)
    assert report["ok"] is True
    assert report["dedup_seeds"] == [30, 34, 37, 42, 45, 48, 57, 58]
    assert report["replayed_episodes"] == 37 + len(comm_eps)
    assert all(chk["passed"] for chk in report["checks"])
    assert mod.main(["--repo", str(ROOT)]) == 0


def test_verify_frontier_ext_replication_pr3_eight_seed_committed_layout(tmp_path: Path):
    mod = _load_checker()
    tmp_repo = _make_symlinked_repo(tmp_path)

    fleet_eps = _read_jsonl(ROOT / EXT_REL / "hard" / "episodes.jsonl")
    comm_eps = _read_jsonl(ROOT / COMM_V14_REL / "opencode-gemini-4-carbon-ext" / "hard" / "episodes.jsonl")
    g1_eps = [ep for ep in comm_eps if ep["seed"] in (34, 37)]
    assert [ep["seed"] for ep in g1_eps] == [34, 37]

    by_seed = {ep["seed"]: ep for ep in fleet_eps}
    for ep in g1_eps:
        by_seed[ep["seed"]] = ep
    merged_eight = [by_seed[seed] for seed in sorted(by_seed)]
    assert [ep["seed"] for ep in merged_eight] == [30, 34, 37, 42, 45, 48, 57, 58]
    assert merged_eight[0]["seed"] == 30

    comm_ep_dst = tmp_repo / COMM_V14_REL / "opencode-gemini-4-carbon-ext" / "hard" / "episodes.jsonl"
    _write_override(
        comm_ep_dst,
        "\n".join(json.dumps(ep) for ep in merged_eight) + "\n",
    )

    report = mod.verify_frontier_ext_replication(tmp_repo)
    assert report["ok"] is True
    assert report["replayed_episodes"] == 45
    assert report["dedup_seeds"] == [30, 34, 37, 42, 45, 48, 57, 58]
    assert all(chk["passed"] for chk in report["checks"])


def test_verify_frontier_ext_replication_tampered_paired_table_ext8(tmp_path: Path):
    mod = _load_checker()
    tmp_repo = _make_symlinked_repo(tmp_path)

    table_path = tmp_repo / EXT_REL / "paired_table_ext8_combined.json"
    rows = json.loads(table_path.read_text(encoding="utf-8"))
    rows[0]["mean"] = float(rows[0]["mean"]) + 0.125
    _write_override(table_path, json.dumps(rows, indent=2) + "\n")

    report = mod.verify_frontier_ext_replication(tmp_repo)
    assert report["ok"] is False
    by_name = {chk["name"]: chk for chk in report["checks"]}
    assert by_name["paired_tables"]["passed"] is False
    assert any("paired_table_ext8_combined.json" in err for err in by_name["paired_tables"]["errors"])
    assert mod.main(["--repo", str(tmp_repo)]) == 1


def test_verify_frontier_ext_replication_tampered_tags_ext8(tmp_path: Path):
    mod = _load_checker()
    tmp_repo = _make_symlinked_repo(tmp_path)

    tags_path = tmp_repo / EXT_REL / "tags_ext8_combined.json"
    tags = json.loads(tags_path.read_text(encoding="utf-8"))
    tags["opencode:google/gemini-4-carbon"]["episodes"] = 99
    _write_override(tags_path, json.dumps(tags, indent=2) + "\n")

    report = mod.verify_frontier_ext_replication(tmp_repo)
    assert report["ok"] is False
    by_name = {chk["name"]: chk for chk in report["checks"]}
    assert by_name["tags_and_accuse"]["passed"] is False
    assert any("tags_ext8_combined.json" in err for err in by_name["tags_and_accuse"]["errors"])
    assert mod.main(["--repo", str(tmp_repo)]) == 1


def test_verify_frontier_ext_replication_tampered_accuse_ext8(tmp_path: Path):
    mod = _load_checker()
    tmp_repo = _make_symlinked_repo(tmp_path)

    accuse_path = tmp_repo / EXT_REL / "accuse_ext8_combined.md"
    orig_md = accuse_path.read_text(encoding="utf-8")
    _write_override(accuse_path, orig_md + "\n| opencode:google/gemini-4-carbon | hard | 99 | e01 | 0.500 |\n")

    report = mod.verify_frontier_ext_replication(tmp_repo)
    assert report["ok"] is False
    by_name = {chk["name"]: chk for chk in report["checks"]}
    assert by_name["tags_and_accuse"]["passed"] is False
    assert any("accuse_ext8_combined.md" in err for err in by_name["tags_and_accuse"]["errors"])
    assert mod.main(["--repo", str(tmp_repo)]) == 1
