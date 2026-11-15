from __future__ import annotations

import ast
from collections import Counter
import hashlib
import io
import json
from pathlib import Path
import re
import shutil
import socket
import struct
import tokenize
from typing import Any
import zlib

import pytest

from canary.gemini import exploit_carbon as EC
from canary.gemini import multimodal_carbon as MC

REPO_ROOT = Path(__file__).resolve().parents[1]
ROLES_CARBON_ROOT = REPO_ROOT / "results" / "gemini" / "roles_carbon"
MM_ROOT = ROLES_CARBON_ROOT / "multimodal_evidence"
MM_INDEX_PATH = MM_ROOT / "index.json"
MM_DOC_PATH = REPO_ROOT / "docs" / "gemini" / "roles_carbon" / "multimodal_evidence.md"
EH_ROOT = ROLES_CARBON_ROOT / "exploit_hunter"
EH_INDEX_PATH = EH_ROOT / "index.json"
EH_DOC_PATH = REPO_ROOT / "docs" / "gemini" / "roles_carbon" / "exploit_hunter.md"
SELF_PATH = Path(__file__).resolve()

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
JUDGE_SEED_MIN = 900000
HASH_CHAR = chr(35)
UNICODE_DASHES: tuple[str, ...] = tuple(
    chr(cp) for cp in (0x2010, 0x2011, 0x2012, 0x2013, 0x2014, 0x2015, 0x2212)
)

SHA256_HEX_RE = re.compile(r"^[0-9a-f]{64}$")
MEMO_PNG_RE = re.compile(r"^memos/seed_(\d+)_([A-Za-z0-9_-]+)\.png$")
RASTER_PNG_RE = re.compile(r"^rasters/(medium|hard)_seed_(\d+)\.png$")
DOSSIER_PNG_RE = re.compile(
    r"^dossiers/(badge_raster|leaked_memo_scans|org_canary_map)_seed_(medium|hard)_(\d+)\.png$"
)
CHART_PNG_RE = re.compile(r"^charts/ep_(\d+)(?:_(medium|hard)_seed(\d+))?\.png$")

GOOGLE_KEY_RE = re.compile(r"(?<![A-Za-z0-9_\-])AIza[0-9A-Za-z_\-]{8,80}(?![A-Za-z0-9_\-=])")
SK_KEY_RE = re.compile(r"(?<![A-Za-z0-9_])sk-[A-Za-z0-9_\-]{12,}")
OAUTH_RE = re.compile(r"(?<![A-Za-z0-9_])ya29\.[0-9A-Za-z_\-.]{8,}")
ENV_KEY_RE = re.compile(
    r"\b(?:GEMINI_API_KEY|GOOGLE_API_KEY|GOOGLE_GENERATIVE_AI_API_KEY|"
    r"OPENAI_API_KEY|ANTHROPIC_API_KEY|XAI_API_KEY)\b"
    r"[\"']?[ \t]*[:=][ \t]*(\"[^\"]*\"|'[^']*'|[^\s\"',}\]]*)"
)
SAFE_PLACEHOLDERS = frozenset(
    {
        "",
        "null",
        "none",
        "false",
        "true",
        "unset",
        "redacted",
        "[redacted]",
        "<redacted>",
        "empty",
        "missing",
    }
)

API_ENV_VARS: tuple[str, ...] = (
    "GEMINI_API_KEY",
    "GOOGLE_GENERATIVE_AI_API_KEY",
    "GOOGLE_API_KEY",
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "XAI_API_KEY",
)

EXPECTED_17_MM_RUNS: tuple[str, ...] = (
    "access-heatmap-carbon",
    "access-heatmap-hard-carbon",
    "access-heatmap-v14-high-s8to11-carbon",
    "access-heatmap-v14-low-s8to11-carbon",
    "access-heatmap-v14-sweep-carbon",
    "belief-chart-forensics-carbon",
    "carbon-trajectory-forensics",
    "carbon-trajectory-forensics-v14-expanded",
    "memo-watermark-ablation-carbon",
    "memo-watermark-hard-ablation-carbon",
    "memo-watermark-hard-seeds10to14-carbon",
    "memo-watermark-hard-seeds5to9-carbon",
    "memo-watermark-med-seeds6to11-carbon",
    "multi-image-dossier-carbon",
    "multi-image-dossier-med6to8-hard5to7-carbon",
    "multi-image-dossier-v14-expanded-carbon",
    "scanned-evidence-ablation-carbon",
)

EXPECTED_2_EH_RUNS: tuple[str, ...] = (
    "blackbox-swarm-carbon",
    "whitebox-swarm-carbon",
)

VALID_DOSSIER_KINDS = frozenset({"badge_raster", "leaked_memo_scans", "org_canary_map"})
VALID_IMAGE_KINDS = frozenset(
    {
        "memo_scan",
        "soc_raster",
        "badge_raster",
        "leaked_memo_scans",
        "org_canary_map",
        "trajectory_chart",
    }
)


class _BlockedSocket:
    def __new__(cls, *_args: Any, **_kwargs: Any) -> Any:
        raise RuntimeError("socket.socket instantiation blocked in keyless audit")

    def __init__(self, *_args: Any, **_kwargs: Any) -> None:
        raise RuntimeError("socket.socket instantiation blocked in keyless audit")


def _deny_network(*_args: Any, **_kwargs: Any) -> Any:
    raise RuntimeError("network access blocked in keyless audit")


@pytest.fixture(autouse=True)
def _keyless_and_socket_blocked_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in API_ENV_VARS:
        monkeypatch.setenv(var, "")
    monkeypatch.delenv("GEMINI_GATEWAY_URL", raising=False)
    monkeypatch.setattr(socket, "socket", _BlockedSocket)
    monkeypatch.setattr(socket, "create_connection", _deny_network)
    monkeypatch.setattr(socket, "getaddrinfo", _deny_network)
    if hasattr(socket, "socketpair"):
        monkeypatch.setattr(socket, "socketpair", _deny_network)


def _is_pos_int(val: Any) -> bool:
    return isinstance(val, int) and not isinstance(val, bool) and val > 0


def _is_nonneg_int(val: Any) -> bool:
    return isinstance(val, int) and not isinstance(val, bool) and val >= 0


def _png_chunk(chunk_type: bytes, payload: bytes) -> bytes:
    crc = zlib.crc32(chunk_type + payload) & 0xFFFFFFFF
    return struct.pack(">I", len(payload)) + chunk_type + payload + struct.pack(">I", crc)


def encode_minimal_png(
    width: int,
    height: int,
    rgba: tuple[int, int, int, int] = (24, 64, 128, 255),
) -> bytes:
    if not (_is_pos_int(width) and _is_pos_int(height)):
        raise ValueError("PNG dimensions must be positive integers")
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    row_pixels = bytes(rgba) * width
    raw_scanlines = b"".join(b"\x00" + row_pixels for _ in range(height))
    idat = zlib.compress(raw_scanlines, level=6)
    return PNG_SIGNATURE + _png_chunk(b"IHDR", ihdr) + _png_chunk(b"IDAT", idat) + _png_chunk(b"IEND", b"")


def verify_png_bytes(raw: bytes) -> dict[str, Any]:
    if not isinstance(raw, (bytes, bytearray)) or len(raw) == 0:
        raise ValueError("empty_png_bytes")
    data = bytes(raw)
    if len(data) < 33 or data[:8] != PNG_SIGNATURE:
        raise ValueError("invalid_png_signature")

    offset = 8
    chunk_index = 0
    width = 0
    height = 0
    bit_depth = 0
    color_type = 0
    interlace = 0
    saw_ihdr = False
    saw_iend = False
    idat_parts: list[bytes] = []

    while offset < len(data):
        if saw_iend:
            raise ValueError("trailing_bytes_after_iend")
        if offset + 12 > len(data):
            raise ValueError("truncated_png_chunk_header")
        length, chunk_type = struct.unpack(">I4s", data[offset : offset + 8])
        end_payload = offset + 8 + length
        if end_payload + 4 > len(data):
            raise ValueError("truncated_png_chunk_payload")
        payload = data[offset + 8 : end_payload]
        (expected_crc,) = struct.unpack(">I", data[end_payload : end_payload + 4])
        actual_crc = zlib.crc32(chunk_type + payload) & 0xFFFFFFFF
        if actual_crc != expected_crc:
            raise ValueError(f"png_crc_mismatch:{chunk_type.decode('latin1', errors='replace')}")

        if chunk_index == 0 and chunk_type != b"IHDR":
            raise ValueError("missing_leading_ihdr")

        if chunk_type == b"IHDR":
            if saw_ihdr or length != 13:
                raise ValueError("invalid_ihdr_chunk")
            width, height, bit_depth, color_type, comp, filt, interlace = struct.unpack(">IIBBBBB", payload)
            if width <= 0 or height <= 0:
                raise ValueError("non_positive_ihdr_dimensions")
            if bit_depth not in {1, 2, 4, 8, 16}:
                raise ValueError("invalid_png_bit_depth")
            if color_type not in {0, 2, 3, 4, 6}:
                raise ValueError("invalid_png_color_type")
            if comp != 0 or filt != 0 or interlace not in {0, 1}:
                raise ValueError("invalid_png_compression_or_filter")
            saw_ihdr = True
        elif chunk_type == b"IDAT":
            if not saw_ihdr:
                raise ValueError("idat_before_ihdr")
            idat_parts.append(payload)
        elif chunk_type == b"IEND":
            if length != 0:
                raise ValueError("non_empty_iend")
            saw_iend = True

        offset = end_payload + 4
        chunk_index += 1

    if not saw_ihdr or not saw_iend or not idat_parts:
        raise ValueError("incomplete_png_stream")

    compressed = b"".join(idat_parts)
    if not compressed:
        raise ValueError("empty_idat_stream")
    try:
        decompressed = zlib.decompress(compressed)
    except zlib.error as exc:
        raise ValueError("corrupt_idat_zlib_stream") from exc
    if len(decompressed) == 0:
        raise ValueError("empty_decompressed_scanlines")

    if interlace == 0:
        channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}[color_type]
        bits_per_row = width * channels * bit_depth
        row_bytes = (bits_per_row + 7) // 8
        expected_raw_len = height * (1 + row_bytes)
        if len(decompressed) != expected_raw_len:
            raise ValueError("scanline_length_mismatch")

    return {
        "width": int(width),
        "height": int(height),
        "size": [int(width), int(height)],
        "bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "bit_depth": int(bit_depth),
        "color_type": int(color_type),
        "chunk_count": chunk_index,
    }


def _classify_png_path(rel_path: str, subfamily: str | None = None) -> str:
    if not isinstance(rel_path, str) or not rel_path.endswith(".png"):
        raise ValueError(f"invalid_png_extension:{rel_path!r}")
    if ".." in Path(rel_path).parts or rel_path.startswith("/"):
        raise ValueError(f"unsafe_png_path:{rel_path!r}")

    m_memo = MEMO_PNG_RE.fullmatch(rel_path)
    if m_memo:
        if subfamily is not None and subfamily != "watermark_memo_ablation":
            raise ValueError(f"subfamily_path_mismatch:{subfamily}:{rel_path}")
        if int(m_memo.group(1)) >= JUDGE_SEED_MIN:
            raise ValueError(f"judge_seed_in_png_path:{rel_path}")
        return "memo_scan"

    m_raster = RASTER_PNG_RE.fullmatch(rel_path)
    if m_raster:
        if subfamily is not None and subfamily != "soc_access_heatmap_vision":
            raise ValueError(f"subfamily_path_mismatch:{subfamily}:{rel_path}")
        if int(m_raster.group(2)) >= JUDGE_SEED_MIN:
            raise ValueError(f"judge_seed_in_png_path:{rel_path}")
        return "soc_raster"

    m_dos = DOSSIER_PNG_RE.fullmatch(rel_path)
    if m_dos:
        if subfamily is not None and subfamily != "multi_image_incident_dossier":
            raise ValueError(f"subfamily_path_mismatch:{subfamily}:{rel_path}")
        if int(m_dos.group(3)) >= JUDGE_SEED_MIN:
            raise ValueError(f"judge_seed_in_png_path:{rel_path}")
        return m_dos.group(1)

    m_chart = CHART_PNG_RE.fullmatch(rel_path)
    if m_chart:
        if subfamily is not None and subfamily != "visual_chart_forensics":
            raise ValueError(f"subfamily_path_mismatch:{subfamily}:{rel_path}")
        if m_chart.group(3) is not None and int(m_chart.group(3)) >= JUDGE_SEED_MIN:
            raise ValueError(f"judge_seed_in_png_path:{rel_path}")
        return "trajectory_chart"

    raise ValueError(f"unrecognized_png_naming:{rel_path}")


def _validate_image_record(
    rec: dict[str, Any],
    *,
    subfamily: str | None = None,
    require_width_height_keys: bool = False,
) -> dict[str, Any]:
    if not isinstance(rec, dict):
        raise ValueError("image_record_not_dict")

    path_val = rec.get("path") or rec.get("memo_path") or rec.get("raster_path") or rec.get("chart_path")
    if not isinstance(path_val, str):
        raise ValueError("missing_image_path")
    inferred_kind = _classify_png_path(path_val, subfamily=subfamily)

    explicit_kind = rec.get("kind")
    if explicit_kind is not None:
        if not isinstance(explicit_kind, str) or explicit_kind not in VALID_IMAGE_KINDS:
            raise ValueError(f"invalid_image_kind:{explicit_kind!r}")
        if inferred_kind in VALID_DOSSIER_KINDS and explicit_kind != inferred_kind:
            raise ValueError(f"dossier_kind_mismatch:{explicit_kind}!={inferred_kind}")

    sha_val = (
        rec.get("sha256")
        if "sha256" in rec
        else rec.get("memo_sha256", rec.get("raster_sha256", rec.get("chart_sha256")))
    )
    if not isinstance(sha_val, str) or SHA256_HEX_RE.fullmatch(sha_val) is None:
        raise ValueError(f"invalid_sha256:{sha_val!r}")

    bytes_val = (
        rec.get("bytes")
        if "bytes" in rec
        else rec.get("memo_bytes", rec.get("raster_bytes", rec.get("chart_bytes_len")))
    )
    if not _is_pos_int(bytes_val):
        raise ValueError(f"invalid_image_bytes:{bytes_val!r}")

    size_val = rec.get("size", rec.get("memo_size", rec.get("raster_size")))
    w_val = rec.get("width")
    h_val = rec.get("height")

    if require_width_height_keys:
        if not (_is_pos_int(w_val) and _is_pos_int(h_val)):
            raise ValueError(f"invalid_width_height:{w_val!r}x{h_val!r}")

    if size_val is not None:
        if (
            not isinstance(size_val, list)
            or len(size_val) != 2
            or not _is_pos_int(size_val[0])
            or not _is_pos_int(size_val[1])
        ):
            raise ValueError(f"invalid_size_pair:{size_val!r}")
        width, height = int(size_val[0]), int(size_val[1])
        if w_val is not None and (not _is_pos_int(w_val) or int(w_val) != width):
            raise ValueError("width_mismatch_vs_size")
        if h_val is not None and (not _is_pos_int(h_val) or int(h_val) != height):
            raise ValueError("height_mismatch_vs_size")
    elif _is_pos_int(w_val) and _is_pos_int(h_val):
        width, height = int(w_val), int(h_val)
    else:
        raise ValueError("missing_image_dimensions")

    return {
        "path": path_val,
        "kind": explicit_kind or inferred_kind,
        "sha256": sha_val,
        "bytes": int(bytes_val),
        "width": width,
        "height": height,
        "size": [width, height],
    }


def _extract_optional_json_image_records(doc: Any) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    if isinstance(doc, dict):
        if isinstance(doc.get("images"), list):
            for item in doc["images"]:
                if isinstance(item, dict):
                    records.append(item)
        elif isinstance(doc.get("images"), dict):
            for item in doc["images"].values():
                if isinstance(item, dict):
                    records.append(item)
        if isinstance(doc.get("image_manifest"), dict):
            imgs = doc["image_manifest"].get("images")
            if isinstance(imgs, list):
                records.extend(x for x in imgs if isinstance(x, dict))
        for list_key in ("memos", "rasters", "charts", "records"):
            arr = doc.get(list_key)
            if isinstance(arr, list):
                records.extend(x for x in arr if isinstance(x, dict))
        if isinstance(doc.get("dossiers"), list):
            for d in doc["dossiers"]:
                if isinstance(d, dict) and isinstance(d.get("images"), list):
                    records.extend(x for x in d["images"] if isinstance(x, dict))
    elif isinstance(doc, list):
        records.extend(x for x in doc if isinstance(x, dict))
    return records


def audit_multimodal_tree(role_dir: Path) -> dict[str, Any]:
    index_path = role_dir / "index.json"
    if not index_path.is_file():
        raise ValueError("missing_index_json")
    index_payload = json.loads(index_path.read_text(encoding="utf-8"))

    totals = index_payload.get("totals")
    if not isinstance(totals, dict):
        raise ValueError("missing_index_totals")
    expected_total_images = totals.get("images_read_by_model")
    expected_total_bytes = totals.get("image_bytes_verified")
    if not _is_pos_int(expected_total_images) or not _is_pos_int(expected_total_bytes):
        raise ValueError("invalid_index_image_totals")

    runs = index_payload.get("runs")
    if not isinstance(runs, list) or not runs:
        raise ValueError("missing_index_runs")

    index_by_run: dict[str, dict[str, Any]] = {}
    for run_entry in runs:
        if not isinstance(run_entry, dict):
            raise ValueError("index_run_not_dict")
        rid = str(run_entry.get("run_id") or "")
        if not rid or rid in index_by_run:
            raise ValueError(f"invalid_or_duplicate_run_id:{rid!r}")
        if run_entry.get("part_from_bytes") is not True:
            raise ValueError(f"index_missing_part_from_bytes:{rid}")
        n_img = run_entry.get("n_images_read_by_model")
        im_sum = run_entry.get("image_manifest_summary")
        if not _is_pos_int(n_img) or not isinstance(im_sum, dict):
            raise ValueError(f"invalid_index_manifest_summary:{rid}")
        if im_sum.get("count") != n_img:
            raise ValueError(f"index_summary_count_mismatch:{rid}")
        if im_sum.get("mime_type") != "image/png":
            raise ValueError(f"index_summary_bad_mime:{rid}")
        if not _is_pos_int(im_sum.get("total_bytes")):
            raise ValueError(f"index_summary_bad_bytes:{rid}")
        dims = im_sum.get("dimensions")
        if not isinstance(dims, list) or not dims:
            raise ValueError(f"index_summary_missing_dimensions:{rid}")
        for pair in dims:
            if (
                not isinstance(pair, list)
                or len(pair) != 2
                or not _is_pos_int(pair[0])
                or not _is_pos_int(pair[1])
            ):
                raise ValueError(f"index_summary_bad_dimension_pair:{rid}:{pair!r}")
        index_by_run[rid] = run_entry

    run_dirs = sorted(p for p in role_dir.iterdir() if p.is_dir() and p.name not in MC.SKIP_DIRS)
    if [p.name for p in run_dirs] != sorted(index_by_run.keys()):
        raise ValueError("run_folder_set_mismatch_vs_index")

    manifest_lookup: dict[tuple[str, str], dict[str, Any]] = {}
    subfamily_image_counts: Counter[str] = Counter()
    subfamily_byte_totals: Counter[str] = Counter()
    all_sha256: list[str] = []
    optional_json_files_checked = 0
    optional_json_records_checked = 0

    for opt_root_name in ("summary.json", "manifest.json"):
        opt_root_path = role_dir / opt_root_name
        if opt_root_path.is_file():
            opt_doc = json.loads(opt_root_path.read_text(encoding="utf-8"))
            opt_recs = _extract_optional_json_image_records(opt_doc)
            if not opt_recs:
                raise ValueError(f"empty_optional_manifest:{opt_root_name}")
            for rec in opt_recs:
                _validate_image_record(rec)
                optional_json_records_checked += 1
            optional_json_files_checked += 1

    for rdir in run_dirs:
        rid = rdir.name
        idx_entry = index_by_run[rid]
        subfamily = str(idx_entry["subfamily"])
        meta_path = rdir / "meta.json"
        if not meta_path.is_file():
            raise ValueError(f"missing_meta_json:{rid}")
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        if meta.get("part_from_bytes") is not True:
            raise ValueError(f"meta_missing_part_from_bytes:{rid}")

        manifest = meta.get("image_manifest")
        if not isinstance(manifest, dict):
            raise ValueError(f"missing_image_manifest:{rid}")
        m_count = manifest.get("count")
        m_bytes = manifest.get("total_bytes")
        m_mime = manifest.get("mime_type")
        m_dims = manifest.get("dimensions")
        m_images = manifest.get("images")

        if not _is_pos_int(m_count) or m_count != idx_entry["n_images_read_by_model"]:
            raise ValueError(f"manifest_count_mismatch:{rid}")
        if m_mime != "image/png":
            raise ValueError(f"manifest_mime_mismatch:{rid}")
        if not _is_pos_int(m_bytes) or m_bytes != idx_entry["image_manifest_summary"]["total_bytes"]:
            raise ValueError(f"manifest_total_bytes_mismatch:{rid}")
        if not isinstance(m_dims, list) or m_dims != idx_entry["image_manifest_summary"]["dimensions"]:
            raise ValueError(f"manifest_dimensions_mismatch:{rid}")
        if not isinstance(m_images, list) or len(m_images) != m_count:
            raise ValueError(f"manifest_images_len_mismatch:{rid}")

        observed_dims: set[tuple[int, int]] = set()
        run_byte_sum = 0
        by_rel_path: dict[str, dict[str, Any]] = {}

        for raw_img in m_images:
            norm = _validate_image_record(raw_img, subfamily=subfamily, require_width_height_keys=True)
            if norm["path"] in by_rel_path:
                raise ValueError(f"duplicate_manifest_image_path:{rid}:{norm['path']}")
            by_rel_path[norm["path"]] = norm
            manifest_lookup[(rid, norm["path"])] = norm
            observed_dims.add((norm["width"], norm["height"]))
            run_byte_sum += norm["bytes"]
            all_sha256.append(norm["sha256"])

        if run_byte_sum != m_bytes:
            raise ValueError(f"manifest_byte_sum_mismatch:{rid}:{run_byte_sum}!={m_bytes}")
        expected_dim_set = {(int(d[0]), int(d[1])) for d in m_dims}
        if observed_dims != expected_dim_set:
            raise ValueError(f"manifest_dimension_set_mismatch:{rid}")

        if subfamily == "watermark_memo_ablation":
            memos = meta.get("memos")
            if not isinstance(memos, list) or len(memos) != m_count:
                raise ValueError(f"memos_list_count_mismatch:{rid}")
            for memo in memos:
                nm = _validate_image_record(memo, subfamily=subfamily)
                ref = by_rel_path.get(nm["path"])
                if ref is None or ref["sha256"] != nm["sha256"] or ref["bytes"] != nm["bytes"] or ref["size"] != nm["size"]:
                    raise ValueError(f"memo_vs_manifest_mismatch:{rid}:{nm['path']}")

            vcalls_path = rdir / "vision_calls.jsonl"
            if not vcalls_path.is_file():
                raise ValueError(f"missing_vision_calls_jsonl:{rid}")
            vrows = [json.loads(ln) for ln in vcalls_path.read_text(encoding="utf-8").splitlines() if ln.strip()]
            if len(vrows) != m_count:
                raise ValueError(f"vision_calls_count_mismatch:{rid}")
            for vrow in vrows:
                nv = _validate_image_record(vrow, subfamily=subfamily)
                ref = by_rel_path.get(nv["path"])
                if ref is None or ref["sha256"] != nv["sha256"] or ref["bytes"] != nv["bytes"] or ref["size"] != nv["size"]:
                    raise ValueError(f"vision_call_vs_manifest_mismatch:{rid}:{nv['path']}")

        elif subfamily == "soc_access_heatmap_vision":
            rasters = meta.get("rasters")
            if not isinstance(rasters, list) or len(rasters) != m_count:
                raise ValueError(f"rasters_list_count_mismatch:{rid}")
            for ras in rasters:
                nr = _validate_image_record(ras, subfamily=subfamily)
                ref = by_rel_path.get(nr["path"])
                if ref is None or ref["sha256"] != nr["sha256"] or ref["bytes"] != nr["bytes"] or ref["size"] != nr["size"]:
                    raise ValueError(f"raster_vs_manifest_mismatch:{rid}:{nr['path']}")

            res_path = rdir / "results.json"
            if not res_path.is_file():
                raise ValueError(f"missing_soc_results_json:{rid}")
            res = json.loads(res_path.read_text(encoding="utf-8"))
            worlds = res.get("worlds")
            if not isinstance(worlds, list) or len(worlds) != m_count:
                raise ValueError(f"soc_worlds_count_mismatch:{rid}")
            for w in worlds:
                nw = _validate_image_record(w, subfamily=subfamily)
                ref = by_rel_path.get(nw["path"])
                if ref is None or ref["sha256"] != nw["sha256"] or ref["bytes"] != nw["bytes"] or ref["size"] != nw["size"]:
                    raise ValueError(f"soc_world_vs_manifest_mismatch:{rid}:{nw['path']}")

        elif subfamily == "multi_image_incident_dossier":
            dossiers = meta.get("dossiers")
            if not isinstance(dossiers, list) or len(dossiers) * 3 != m_count:
                raise ValueError(f"dossiers_list_count_mismatch:{rid}")
            for dos in dossiers:
                d_imgs = dos.get("images")
                if not isinstance(d_imgs, list) or len(d_imgs) != 3:
                    raise ValueError(f"dossier_entry_image_count_mismatch:{rid}")
                kinds_seen: set[str] = set()
                for d_img in d_imgs:
                    nd = _validate_image_record(d_img, subfamily=subfamily)
                    kinds_seen.add(nd["kind"])
                    ref = by_rel_path.get(nd["path"])
                    if ref is None or ref["sha256"] != nd["sha256"] or ref["bytes"] != nd["bytes"] or ref["size"] != nd["size"]:
                        raise ValueError(f"dossier_meta_vs_manifest_mismatch:{rid}:{nd['path']}")
                if kinds_seen != VALID_DOSSIER_KINDS:
                    raise ValueError(f"dossier_kinds_incomplete:{rid}:{kinds_seen}")

            res_path = rdir / "results.json"
            if not res_path.is_file():
                raise ValueError(f"missing_dossier_results_json:{rid}")
            res = json.loads(res_path.read_text(encoding="utf-8"))
            worlds = res.get("worlds")
            if not isinstance(worlds, list) or len(worlds) * 3 != m_count:
                raise ValueError(f"dossier_worlds_count_mismatch:{rid}")
            for w in worlds:
                w_imgs = w.get("images")
                if not isinstance(w_imgs, dict) or set(w_imgs.keys()) != VALID_DOSSIER_KINDS:
                    raise ValueError(f"dossier_world_images_keys_mismatch:{rid}")
                for k_name, d_img in w_imgs.items():
                    nd = _validate_image_record(d_img, subfamily=subfamily)
                    if nd["kind"] != k_name:
                        raise ValueError(f"dossier_world_kind_key_mismatch:{rid}:{k_name}")
                    ref = by_rel_path.get(nd["path"])
                    if ref is None or ref["sha256"] != nd["sha256"] or ref["bytes"] != nd["bytes"] or ref["size"] != nd["size"]:
                        raise ValueError(f"dossier_world_vs_manifest_mismatch:{rid}:{nd['path']}")

        elif subfamily == "visual_chart_forensics":
            diag_path = rdir / "diagnoses.json"
            if not diag_path.is_file():
                raise ValueError(f"missing_diagnoses_json:{rid}")
            diags = json.loads(diag_path.read_text(encoding="utf-8"))
            if not isinstance(diags, list) or len(diags) != m_count:
                raise ValueError(f"diagnoses_count_mismatch:{rid}")
            for d_row in diags:
                ref = by_rel_path.get(str(d_row.get("chart_path") or ""))
                if ref is None:
                    raise ValueError(f"unknown_chart_path_in_diagnoses:{rid}:{d_row.get('chart_path')!r}")
                enriched = {
                    "chart_path": d_row.get("chart_path"),
                    "chart_sha256": d_row.get("chart_sha256"),
                    "chart_bytes_len": d_row.get("chart_bytes_len"),
                    "size": ref["size"],
                }
                nc = _validate_image_record(enriched, subfamily=subfamily)
                if ref["sha256"] != nc["sha256"] or ref["bytes"] != nc["bytes"]:
                    raise ValueError(f"diagnosis_vs_manifest_mismatch:{rid}:{nc['path']}")
        else:
            raise ValueError(f"unexpected_subfamily:{subfamily}")

        for opt_name in ("summary.json", "manifest.json"):
            opt_path = rdir / opt_name
            if opt_path.is_file():
                opt_doc = json.loads(opt_path.read_text(encoding="utf-8"))
                opt_recs = _extract_optional_json_image_records(opt_doc)
                if not opt_recs:
                    raise ValueError(f"empty_optional_run_manifest:{rid}:{opt_name}")
                for rec in opt_recs:
                    n_opt = _validate_image_record(rec, subfamily=subfamily)
                    ref = by_rel_path.get(n_opt["path"])
                    if ref is None or ref["sha256"] != n_opt["sha256"] or ref["bytes"] != n_opt["bytes"] or ref["size"] != n_opt["size"]:
                        raise ValueError(f"optional_json_vs_manifest_mismatch:{rid}:{opt_name}:{n_opt['path']}")
                    optional_json_records_checked += 1
                optional_json_files_checked += 1

        subfamily_image_counts[subfamily] += m_count
        subfamily_byte_totals[subfamily] += m_bytes

    disk_png_files = sorted(role_dir.rglob("*.png"))
    verified_disk_pngs: list[dict[str, Any]] = []
    for png_file in disk_png_files:
        rel_to_role = png_file.relative_to(role_dir)
        parts = rel_to_role.parts
        png_info = verify_png_bytes(png_file.read_bytes())
        if len(parts) >= 2 and parts[0] in index_by_run:
            run_id = parts[0]
            sub_rel = Path(*parts[1:]).as_posix()
            subfam = str(index_by_run[run_id]["subfamily"])
            _classify_png_path(sub_rel, subfamily=subfam)
            ref = manifest_lookup.get((run_id, sub_rel))
            if ref is None:
                raise ValueError(f"unlisted_disk_png:{run_id}:{sub_rel}")
            if (
                png_info["sha256"] != ref["sha256"]
                or png_info["bytes"] != ref["bytes"]
                or png_info["size"] != ref["size"]
            ):
                raise ValueError(f"disk_png_mismatch_vs_manifest:{run_id}:{sub_rel}")
        else:
            _classify_png_path(rel_to_role.as_posix())
        verified_disk_pngs.append({"path": rel_to_role.as_posix(), **png_info})

    total_images_sum = sum(subfamily_image_counts.values())
    total_bytes_sum = sum(subfamily_byte_totals.values())
    if total_images_sum != expected_total_images:
        raise ValueError(f"total_images_mismatch:{total_images_sum}!={expected_total_images}")
    if total_bytes_sum != expected_total_bytes:
        raise ValueError(f"total_bytes_mismatch:{total_bytes_sum}!={expected_total_bytes}")

    return {
        "run_count": len(run_dirs),
        "total_images": total_images_sum,
        "total_bytes": total_bytes_sum,
        "distinct_sha256_count": len(set(all_sha256)),
        "subfamily_image_counts": dict(subfamily_image_counts),
        "subfamily_byte_totals": dict(subfamily_byte_totals),
        "disk_png_count": len(verified_disk_pngs),
        "optional_json_files_checked": optional_json_files_checked,
        "optional_json_records_checked": optional_json_records_checked,
    }


def _scan_secrets_in_text(text: str) -> list[str]:
    hits: list[str] = []
    if GOOGLE_KEY_RE.search(text):
        hits.append("google_api_key")
    if SK_KEY_RE.search(text):
        hits.append("sk_api_key")
    if OAUTH_RE.search(text):
        hits.append("oauth_token")
    for match in ENV_KEY_RE.finditer(text):
        raw = match.group(1).strip()
        quoted = len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in "\"'"
        inner = raw[1:-1].strip() if quoted else raw
        if inner.lower() in SAFE_PLACEHOLDERS:
            continue
        if set(inner) <= {"*"} or inner.startswith("$"):
            continue
        if not quoted and "=" in inner:
            continue
        if len(inner) >= 4:
            hits.append("env_api_key")
    return hits


def _collect_evaluated_seeds(obj: Any, out: list[int]) -> None:
    if isinstance(obj, dict):
        for key, val in obj.items():
            if key == "tool_calls":
                continue
            if key == "seed":
                if isinstance(val, int) and not isinstance(val, bool):
                    out.append(int(val))
            elif key in {"seeds", "medium_seeds", "hard_seeds", "observed_dev_seeds"} and isinstance(val, list):
                for item in val:
                    if isinstance(item, int) and not isinstance(item, bool):
                        out.append(int(item))
            elif key == "tier_seeds" and isinstance(val, dict):
                for arr in val.values():
                    if isinstance(arr, list):
                        for item in arr:
                            if isinstance(item, int) and not isinstance(item, bool):
                                out.append(int(item))
            elif key == "seed_tag" and isinstance(val, str):
                parts = val.rsplit("_", 1)
                if len(parts) == 2 and parts[1].isdigit():
                    out.append(int(parts[1]))
            else:
                _collect_evaluated_seeds(val, out)
    elif isinstance(obj, list):
        for item in obj:
            _collect_evaluated_seeds(item, out)


def test_live_multimodal_png_and_cryptographic_manifest_audit_260_images() -> None:
    report = audit_multimodal_tree(MM_ROOT)
    assert report["run_count"] == 17
    assert report["total_images"] == 260
    assert report["total_bytes"] == 27268097
    assert report["distinct_sha256_count"] == 214
    assert report["disk_png_count"] == 0
    assert list(p.name for p in sorted(MM_ROOT.iterdir()) if p.is_dir()) == list(EXPECTED_17_MM_RUNS)
    assert report["subfamily_image_counts"] == {
        "watermark_memo_ablation": 156,
        "multi_image_incident_dossier": 51,
        "soc_access_heatmap_vision": 28,
        "visual_chart_forensics": 25,
    }
    assert sum(report["subfamily_image_counts"].values()) == 260
    assert report["subfamily_byte_totals"] == {
        "watermark_memo_ablation": 4887883,
        "multi_image_incident_dossier": 6903017,
        "soc_access_heatmap_vision": 6480688,
        "visual_chart_forensics": 8996509,
    }
    assert sum(report["subfamily_byte_totals"].values()) == 27268097


def test_duplicate_and_overlap_accounting_across_all_four_subfamilies() -> None:
    index_payload = json.loads(MM_INDEX_PATH.read_text(encoding="utf-8"))
    runs_by_subfamily: dict[str, list[str]] = {}
    for run_entry in index_payload["runs"]:
        runs_by_subfamily.setdefault(run_entry["subfamily"], []).append(run_entry["run_id"])

    assert len(runs_by_subfamily["watermark_memo_ablation"]) == 6
    memo_worlds_unique: dict[tuple[str, int], list[tuple[str, str, int, tuple[int, int], bool]]] = {}
    memo_overlap_worlds: list[tuple[str, int]] = []
    memo_overlap_scan_count = 0
    memo_batch_scan_count = 0
    memo_batch_episodes = 0

    for rid in sorted(runs_by_subfamily["watermark_memo_ablation"]):
        rdir = MM_ROOT / rid
        comp = json.loads((rdir / "comparison.json").read_text(encoding="utf-8"))
        memo_batch_episodes += len(comp["per_seed"])
        vrows = [
            json.loads(ln)
            for ln in (rdir / "vision_calls.jsonl").read_text(encoding="utf-8").splitlines()
            if ln.strip()
        ]
        memo_batch_scan_count += len(vrows)
        grouped: dict[tuple[str, int], list[tuple[str, str, int, tuple[int, int], bool]]] = {}
        for row in vrows:
            wkey = (str(row["tier"]), int(row["seed"]))
            sig = (
                str(row["doc_id"]),
                str(row["memo_sha256"]),
                int(row["memo_bytes"]),
                (int(row["memo_size"][0]), int(row["memo_size"][1])),
                bool(row["is_canary_memo"]),
            )
            grouped.setdefault(wkey, []).append(sig)
        for wkey, sigs in grouped.items():
            sigs_sorted = sorted(sigs)
            if wkey in memo_worlds_unique:
                assert memo_worlds_unique[wkey] == sigs_sorted
                memo_overlap_worlds.append(wkey)
                memo_overlap_scan_count += len(sigs_sorted)
            else:
                memo_worlds_unique[wkey] = sigs_sorted

    unique_memo_scans = sum(len(v) for v in memo_worlds_unique.values())
    unique_canary_scans = sum(1 for v in memo_worlds_unique.values() for s in v if s[4])
    assert len(memo_worlds_unique) == 27
    assert sum(1 for t, _ in memo_worlds_unique if t == "medium") == 12
    assert sum(1 for t, _ in memo_worlds_unique if t == "hard") == 15
    assert memo_batch_episodes == 30
    assert unique_memo_scans == 140
    assert unique_canary_scans == 45
    assert sorted(memo_overlap_worlds) == [("medium", 3), ("medium", 4), ("medium", 5)]
    assert memo_overlap_scan_count == 16
    assert unique_memo_scans + memo_overlap_scan_count == memo_batch_scan_count == 156

    assert len(runs_by_subfamily["multi_image_incident_dossier"]) == 3
    dossier_worlds: dict[tuple[str, int], dict[str, str]] = {}
    dossier_batch_images = 0
    dossier_overlap_images = 0
    for rid in sorted(runs_by_subfamily["multi_image_incident_dossier"]):
        res = json.loads((MM_ROOT / rid / "results.json").read_text(encoding="utf-8"))
        for w in res["worlds"]:
            wkey = (str(w["tier"]), int(w["seed"]))
            kind_shas = {k: str(v["sha256"]) for k, v in w["images"].items()}
            assert set(kind_shas.keys()) == VALID_DOSSIER_KINDS
            dossier_batch_images += 3
            if wkey in dossier_worlds:
                assert dossier_worlds[wkey] == kind_shas
                dossier_overlap_images += 3
            else:
                dossier_worlds[wkey] = kind_shas

    unique_dossier_images = len(dossier_worlds) * 3
    assert len(dossier_worlds) == 17
    assert sum(1 for t, _ in dossier_worlds if t == "medium") == 9
    assert sum(1 for t, _ in dossier_worlds if t == "hard") == 8
    assert dossier_overlap_images == 0
    assert unique_dossier_images == dossier_batch_images == 51

    assert len(runs_by_subfamily["soc_access_heatmap_vision"]) == 5
    soc_worlds: dict[tuple[str, int], tuple[str, int, tuple[int, int]]] = {}
    soc_overlap_worlds: list[tuple[str, int]] = []
    soc_batch_images = 0
    for rid in sorted(runs_by_subfamily["soc_access_heatmap_vision"]):
        meta = json.loads((MM_ROOT / rid / "meta.json").read_text(encoding="utf-8"))
        res = json.loads((MM_ROOT / rid / "results.json").read_text(encoding="utf-8"))
        for w in res["worlds"]:
            tier_name = str(w.get("tier") or meta.get("tier"))
            wkey = (tier_name, int(w["seed"]))
            sig = (
                str(w["raster_sha256"]),
                int(w["raster_bytes"]),
                (int(w["raster_size"][0]), int(w["raster_size"][1])),
            )
            soc_batch_images += 1
            if wkey in soc_worlds:
                assert soc_worlds[wkey] == sig
                soc_overlap_worlds.append(wkey)
            else:
                soc_worlds[wkey] = sig

    assert len(soc_worlds) == 22
    assert len(soc_overlap_worlds) == 6
    assert sorted(soc_overlap_worlds) == [
        ("hard", 8),
        ("hard", 9),
        ("hard", 10),
        ("hard", 11),
        ("medium", 8),
        ("medium", 9),
    ]
    assert len(soc_worlds) + len(soc_overlap_worlds) == soc_batch_images == 28

    assert len(runs_by_subfamily["visual_chart_forensics"]) == 3
    chart_episodes: dict[tuple[str, str, str, int], tuple[str, int]] = {}
    chart_overlap_episodes: list[tuple[str, str, str, int]] = []
    chart_batch_images = 0
    for rid in sorted(runs_by_subfamily["visual_chart_forensics"]):
        meta = json.loads((MM_ROOT / rid / "meta.json").read_text(encoding="utf-8"))
        diags = json.loads((MM_ROOT / rid / "diagnoses.json").read_text(encoding="utf-8"))
        for d in diags:
            se = d["source_episode"]
            ekey = (
                str(se.get("tiers_version") or meta.get("tiers_version")),
                str(se["agent"]),
                str(se["tier"]),
                int(se["seed"]),
            )
            sig = (str(d["chart_sha256"]), int(d["chart_bytes_len"]))
            chart_batch_images += 1
            if ekey in chart_episodes:
                assert chart_episodes[ekey] == sig
                chart_overlap_episodes.append(ekey)
            else:
                chart_episodes[ekey] = sig

    assert len(chart_episodes) == 20
    assert len(chart_overlap_episodes) == 5
    assert len(chart_episodes) + len(chart_overlap_episodes) == chart_batch_images == 25

    unique_images_all = unique_memo_scans + unique_dossier_images + len(soc_worlds) + len(chart_episodes)
    overlap_images_all = (
        memo_overlap_scan_count + dossier_overlap_images + len(soc_overlap_worlds) + len(chart_overlap_episodes)
    )
    assert unique_images_all == 233
    assert overlap_images_all == 27
    assert unique_images_all + overlap_images_all == 260
    assert memo_batch_scan_count + dossier_batch_images + soc_batch_images + chart_batch_images == 260


def test_summary_md_sha256_digests_match_manifests_across_runs() -> None:
    hex64_in_md_re = re.compile(r"`([0-9a-f]{64})`")
    checked_digests = 0
    for rid in EXPECTED_17_MM_RUNS:
        rdir = MM_ROOT / rid
        meta = json.loads((rdir / "meta.json").read_text(encoding="utf-8"))
        manifest_shas = {img["sha256"] for img in meta["image_manifest"]["images"]}
        md_text = (rdir / "summary.md").read_text(encoding="utf-8")
        for digest in hex64_in_md_re.findall(md_text):
            assert digest in manifest_shas, f"{rid}: summary.md digest {digest} missing from image_manifest"
            checked_digests += 1
    assert checked_digests >= 28


def test_on_disk_png_and_optional_summary_manifest_json_verification_in_sandbox(tmp_path: Path) -> None:
    sandbox_mm = tmp_path / "multimodal_evidence"
    run_name = "access-heatmap-carbon"
    shutil.copytree(MM_ROOT / run_name, sandbox_mm / run_name)

    png_specs = [
        ("rasters/medium_seed_0.png", 16, 12, (20, 80, 160, 255)),
        ("rasters/medium_seed_1.png", 16, 12, (90, 30, 140, 255)),
        ("rasters/medium_seed_2.png", 16, 12, (40, 150, 70, 255)),
    ]
    manifest_images: list[dict[str, Any]] = []
    rasters_list: list[dict[str, Any]] = []

    for seed_idx, (rel_p, w, h, color) in enumerate(png_specs):
        raw_png = encode_minimal_png(w, h, color)
        info = verify_png_bytes(raw_png)
        out_png = sandbox_mm / run_name / rel_p
        out_png.parent.mkdir(parents=True, exist_ok=True)
        out_png.write_bytes(raw_png)
        manifest_images.append(
            {
                "path": rel_p,
                "size": [w, h],
                "width": w,
                "height": h,
                "bytes": info["bytes"],
                "sha256": info["sha256"],
            }
        )
        rasters_list.append(
            {
                "seed": seed_idx,
                "path": rel_p,
                "sha256": info["sha256"],
                "bytes": info["bytes"],
                "size": [w, h],
            }
        )

    total_b = sum(x["bytes"] for x in manifest_images)
    meta_path = sandbox_mm / run_name / "meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta["rasters"] = rasters_list
    meta["image_manifest"] = {
        "count": 3,
        "mime_type": "image/png",
        "total_bytes": total_b,
        "dimensions": [[16, 12]],
        "images": manifest_images,
    }
    meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")

    res_path = sandbox_mm / run_name / "results.json"
    res = json.loads(res_path.read_text(encoding="utf-8"))
    for idx, w_obj in enumerate(res["worlds"]):
        w_obj["raster_path"] = manifest_images[idx]["path"]
        w_obj["raster_sha256"] = manifest_images[idx]["sha256"]
        w_obj["raster_bytes"] = manifest_images[idx]["bytes"]
        w_obj["raster_size"] = manifest_images[idx]["size"]
    res_path.write_text(json.dumps(res, indent=2), encoding="utf-8")

    (sandbox_mm / run_name / "manifest.json").write_text(
        json.dumps({"images": manifest_images}, indent=2), encoding="utf-8"
    )
    (sandbox_mm / run_name / "summary.json").write_text(
        json.dumps({"rasters": rasters_list}, indent=2), encoding="utf-8"
    )
    (sandbox_mm / "summary.json").write_text(
        json.dumps({"records": manifest_images}, indent=2), encoding="utf-8"
    )

    live_idx = json.loads(MM_INDEX_PATH.read_text(encoding="utf-8"))
    single_run_entry = next(r for r in live_idx["runs"] if r["run_id"] == run_name)
    single_run_entry = json.loads(json.dumps(single_run_entry))
    single_run_entry["image_manifest_summary"] = {
        "count": 3,
        "mime_type": "image/png",
        "total_bytes": total_b,
        "dimensions": [[16, 12]],
    }
    sandbox_idx = {
        "role": "multimodal_evidence",
        "target_model": "gemini-4-carbon",
        "totals": {
            "run_count": 1,
            "images_read_by_model": 3,
            "image_bytes_verified": total_b,
        },
        "runs": [single_run_entry],
    }
    (sandbox_mm / "index.json").write_text(json.dumps(sandbox_idx, indent=2), encoding="utf-8")

    audit_res = audit_multimodal_tree(sandbox_mm)
    assert audit_res["run_count"] == 1
    assert audit_res["total_images"] == 3
    assert audit_res["disk_png_count"] == 3
    assert audit_res["optional_json_files_checked"] == 3
    assert audit_res["optional_json_records_checked"] == 9

    target_png = sandbox_mm / run_name / "rasters/medium_seed_0.png"
    good_bytes = target_png.read_bytes()
    target_png.write_bytes(encode_minimal_png(16, 12, (255, 0, 0, 255)))
    with pytest.raises(ValueError, match="disk_png_mismatch_vs_manifest"):
        audit_multimodal_tree(sandbox_mm)

    target_png.write_bytes(b"NOT_A_PNG_HEADER" + good_bytes[16:])
    with pytest.raises(ValueError, match="invalid_png_signature"):
        audit_multimodal_tree(sandbox_mm)
    target_png.write_bytes(good_bytes)

    bad_summary = {"rasters": [{**rasters_list[0], "sha256": "Z" * 64}]}
    (sandbox_mm / run_name / "summary.json").write_text(json.dumps(bad_summary), encoding="utf-8")
    with pytest.raises(ValueError, match="invalid_sha256"):
        audit_multimodal_tree(sandbox_mm)


def test_binary_png_verifier_rejects_corrupt_crc_idat_dims_and_trailing_bytes() -> None:
    valid = encode_minimal_png(8, 6, (10, 20, 30, 255))
    parsed = verify_png_bytes(valid)
    assert parsed["size"] == [8, 6]
    assert parsed["bytes"] == len(valid)
    assert SHA256_HEX_RE.fullmatch(parsed["sha256"]) is not None

    with pytest.raises(ValueError, match="empty_png_bytes"):
        verify_png_bytes(b"")

    with pytest.raises(ValueError, match="invalid_png_signature"):
        verify_png_bytes(b"\x89JPG\r\n\x1a\n" + valid[8:])

    corrupt_crc = bytearray(valid)
    corrupt_crc[29] ^= 0xFF
    with pytest.raises(ValueError, match="png_crc_mismatch"):
        verify_png_bytes(bytes(corrupt_crc))

    bad_idat = PNG_SIGNATURE + _png_chunk(b"IHDR", struct.pack(">IIBBBBB", 4, 4, 8, 6, 0, 0, 0))
    bad_idat += _png_chunk(b"IDAT", b"not_valid_zlib_payload") + _png_chunk(b"IEND", b"")
    with pytest.raises(ValueError, match="corrupt_idat_zlib_stream"):
        verify_png_bytes(bad_idat)

    zero_w = PNG_SIGNATURE + _png_chunk(b"IHDR", struct.pack(">IIBBBBB", 0, 4, 8, 6, 0, 0, 0))
    zero_w += _png_chunk(b"IDAT", zlib.compress(b"\x00")) + _png_chunk(b"IEND", b"")
    with pytest.raises(ValueError, match="non_positive_ihdr_dimensions"):
        verify_png_bytes(zero_w)

    with pytest.raises(ValueError, match="trailing_bytes_after_iend"):
        verify_png_bytes(valid + b"\x00")


def test_record_validator_rejects_bad_sha_dims_bytes_and_naming() -> None:
    good = {
        "path": "dossiers/badge_raster_seed_medium_0.png",
        "kind": "badge_raster",
        "sha256": "a" * 64,
        "bytes": 1024,
        "width": 1274,
        "height": 996,
        "size": [1274, 996],
    }
    out = _validate_image_record(good, subfamily="multi_image_incident_dossier", require_width_height_keys=True)
    assert out["kind"] == "badge_raster"

    with pytest.raises(ValueError, match="invalid_sha256"):
        _validate_image_record({**good, "sha256": "A" * 64})
    with pytest.raises(ValueError, match="invalid_sha256"):
        _validate_image_record({**good, "sha256": "abc123"})
    with pytest.raises(ValueError, match="invalid_size_pair"):
        _validate_image_record({**good, "size": [0, 996], "width": 0})
    with pytest.raises(ValueError, match="invalid_image_bytes"):
        _validate_image_record({**good, "bytes": 0})
    with pytest.raises(ValueError, match="dossier_kind_mismatch"):
        _validate_image_record({**good, "kind": "org_canary_map"})
    with pytest.raises(ValueError, match="judge_seed_in_png_path"):
        _validate_image_record({**good, "path": "dossiers/badge_raster_seed_hard_900000.png"})


def test_socket_blocker_actively_denies_socket_creation_and_connections() -> None:
    with pytest.raises(RuntimeError, match="blocked"):
        socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    with pytest.raises(RuntimeError, match="blocked"):
        socket.create_connection(("127.0.0.1", 80))
    with pytest.raises(RuntimeError, match="blocked"):
        socket.getaddrinfo("generativelanguage.googleapis.com", 443)


def test_socket_blocked_keyless_multimodal_and_exploit_carbon_check_and_json_modes(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    mm_idx_before = MM_INDEX_PATH.read_bytes()
    mm_doc_before = MM_DOC_PATH.read_bytes()
    eh_idx_before = EH_INDEX_PATH.read_bytes()
    eh_doc_before = EH_DOC_PATH.read_bytes()

    rc_mm_check = MC.main(["--check"])
    out_mm_check = capsys.readouterr().out
    assert rc_mm_check == 0
    assert "multimodal_carbon [OK]" in out_mm_check

    rc_mm_check_json = MC.main(["--check", "--json"])
    payload_mm_check_json = json.loads(capsys.readouterr().out)
    assert rc_mm_check_json == 0
    assert payload_mm_check_json["ok"] is True
    assert payload_mm_check_json["errors"] == []
    assert payload_mm_check_json["totals"]["run_count"] == 17
    assert payload_mm_check_json["totals"]["images_read_by_model"] == 260

    rc_eh_check = EC.main(["--check"])
    out_eh_check = capsys.readouterr().out
    assert rc_eh_check == 0
    assert "exploit_carbon: CHECK OK" in out_eh_check

    rc_eh_check_json = EC.main(["--check", "--json"])
    payload_eh_check_json = json.loads(capsys.readouterr().out)
    assert rc_eh_check_json == 0
    assert payload_eh_check_json["ok"] is True
    assert payload_eh_check_json["errors"] == []
    assert payload_eh_check_json["totals"]["run_count"] == 2
    assert payload_eh_check_json["totals"]["attempts"] == 11

    assert MM_INDEX_PATH.read_bytes() == mm_idx_before
    assert MM_DOC_PATH.read_bytes() == mm_doc_before
    assert EH_INDEX_PATH.read_bytes() == eh_idx_before
    assert EH_DOC_PATH.read_bytes() == eh_doc_before

    sandbox_root = tmp_path / "repo"
    shutil.copytree(
        MM_ROOT,
        sandbox_root / "results" / "gemini" / "roles_carbon" / "multimodal_evidence",
    )
    shutil.copytree(
        EH_ROOT,
        sandbox_root / "results" / "gemini" / "roles_carbon" / "exploit_hunter",
    )

    rc_mm_json = MC.main(["--root", str(sandbox_root), "--json"])
    payload_mm_json = json.loads(capsys.readouterr().out)
    assert rc_mm_json == 0
    assert payload_mm_json["ok"] is True
    assert (
        sandbox_root / "results" / "gemini" / "roles_carbon" / "multimodal_evidence" / "index.json"
    ).read_bytes() == mm_idx_before
    assert (
        sandbox_root / "docs" / "gemini" / "roles_carbon" / "multimodal_evidence.md"
    ).read_bytes() == mm_doc_before

    rc_eh_json = EC.main(["--root", str(sandbox_root), "--json"])
    payload_eh_json = json.loads(capsys.readouterr().out)
    assert rc_eh_json == 0
    assert payload_eh_json["role"] == "exploit_hunter"
    assert payload_eh_json["verified"] is True
    assert (
        sandbox_root / "results" / "gemini" / "roles_carbon" / "exploit_hunter" / "index.json"
    ).read_bytes() == eh_idx_before
    assert (
        sandbox_root / "docs" / "gemini" / "roles_carbon" / "exploit_hunter.md"
    ).read_bytes() == eh_doc_before


def test_zero_judge_seeds_zero_world_json_and_zero_api_keys_across_both_roles() -> None:
    eh_run_dirs = sorted(p.name for p in EH_ROOT.iterdir() if p.is_dir() and p.name not in EC.SKIP_DIRS)
    assert eh_run_dirs == list(EXPECTED_2_EH_RUNS)
    assert list(EH_ROOT.rglob("*.png")) == []

    world_files_roles = list(ROLES_CARBON_ROOT.rglob("*.world.json"))
    assert world_files_roles == []
    worlds_dir = REPO_ROOT / "data" / "worlds"
    if worlds_dir.exists():
        assert list(worlds_dir.rglob("*.world.json")) == []

    mm_seeds: list[int] = []
    eh_seeds: list[int] = []
    judge_probe_calls_checked = 0

    for role_root, seed_sink in ((MM_ROOT, mm_seeds), (EH_ROOT, eh_seeds)):
        for fp in sorted(p for p in role_root.rglob("*") if p.is_file()):
            assert not fp.name.endswith(".world.json"), fp
            assert fp.name != ".env" and not fp.name.startswith(".env."), fp
            assert fp.name != "SALT" and "SALT" not in fp.parts, fp

            text = fp.read_text(encoding="utf-8")
            assert _scan_secrets_in_text(text) == [], f"secret pattern in {fp}"
            for dash in UNICODE_DASHES:
                assert dash not in text, f"unicode dash {ord(dash):04x} in {fp}"

            if fp.suffix == ".json":
                parsed = json.loads(text)
                _collect_evaluated_seeds(parsed, seed_sink)
                if role_root == EH_ROOT and isinstance(parsed, dict) and isinstance(parsed.get("attempts"), list):
                    for att in parsed["attempts"]:
                        for tc in att.get("tool_calls") or []:
                            args = tc.get("args") if isinstance(tc, dict) else None
                            if (
                                isinstance(args, dict)
                                and tc.get("tool") == "public_world_match"
                                and isinstance(args.get("seed_from"), int)
                                and int(args["seed_from"]) >= JUDGE_SEED_MIN
                            ):
                                res_str = str(tc.get("result") or "")
                                assert '"matches": []' in res_str or '"matches":[]' in res_str
                                judge_probe_calls_checked += 1
            elif fp.suffix == ".jsonl":
                for line in text.splitlines():
                    if line.strip():
                        _collect_evaluated_seeds(json.loads(line), seed_sink)

    for doc_fp in (MM_DOC_PATH, EH_DOC_PATH):
        doc_txt = doc_fp.read_text(encoding="utf-8")
        assert _scan_secrets_in_text(doc_txt) == []
        for dash in UNICODE_DASHES:
            assert dash not in doc_txt

    assert len(mm_seeds) > 0
    assert all(0 <= s < JUDGE_SEED_MIN for s in mm_seeds)
    assert sorted(set(mm_seeds)) == list(range(15))

    assert len(eh_seeds) > 0
    assert all(0 <= s < JUDGE_SEED_MIN for s in eh_seeds)
    assert judge_probe_calls_checked >= 1


def test_per_run_17_manifest_counts_dimensions_and_bytes_exact_reconciliation() -> None:
    index_payload = json.loads(MM_INDEX_PATH.read_text(encoding="utf-8"))
    md_text = MM_DOC_PATH.read_text(encoding="utf-8")
    expected_per_run_counts = {
        "access-heatmap-carbon": 3,
        "access-heatmap-hard-carbon": 3,
        "access-heatmap-v14-high-s8to11-carbon": 6,
        "access-heatmap-v14-low-s8to11-carbon": 6,
        "access-heatmap-v14-sweep-carbon": 10,
        "belief-chart-forensics-carbon": 6,
        "carbon-trajectory-forensics": 7,
        "carbon-trajectory-forensics-v14-expanded": 12,
        "memo-watermark-ablation-carbon": 16,
        "memo-watermark-hard-ablation-carbon": 18,
        "memo-watermark-hard-seeds10to14-carbon": 39,
        "memo-watermark-hard-seeds5to9-carbon": 25,
        "memo-watermark-med-seeds6to11-carbon": 21,
        "multi-image-dossier-carbon": 15,
        "multi-image-dossier-med6to8-hard5to7-carbon": 18,
        "multi-image-dossier-v14-expanded-carbon": 18,
        "scanned-evidence-ablation-carbon": 37,
    }
    assert sum(expected_per_run_counts.values()) == 260

    by_id = {r["run_id"]: r for r in index_payload["runs"]}
    assert set(by_id.keys()) == set(expected_per_run_counts.keys())
    for rid, exp_count in expected_per_run_counts.items():
        idx_run = by_id[rid]
        meta = json.loads((MM_ROOT / rid / "meta.json").read_text(encoding="utf-8"))
        im = meta["image_manifest"]
        assert idx_run["n_images_read_by_model"] == exp_count
        assert idx_run["image_manifest_summary"]["count"] == exp_count
        assert im["count"] == exp_count
        assert len(im["images"]) == exp_count
        assert f"`{rid}`" in md_text


def test_companion_and_manifest_cross_tamper_detection(tmp_path: Path) -> None:
    sandbox_mm = tmp_path / "mm"
    shutil.copytree(MM_ROOT, sandbox_mm)
    assert audit_multimodal_tree(sandbox_mm)["total_images"] == 260

    vc_path = sandbox_mm / "memo-watermark-ablation-carbon" / "vision_calls.jsonl"
    orig_vc = vc_path.read_text(encoding="utf-8")
    vc_lines = [ln for ln in orig_vc.splitlines() if ln.strip()]
    first_vc = json.loads(vc_lines[0])
    first_vc["memo_sha256"] = "0" * 64
    vc_path.write_text("\n".join([json.dumps(first_vc), *vc_lines[1:]]) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="vision_call_vs_manifest_mismatch"):
        audit_multimodal_tree(sandbox_mm)
    vc_path.write_text(orig_vc, encoding="utf-8")

    dos_res_path = sandbox_mm / "multi-image-dossier-carbon" / "results.json"
    orig_dos_res = dos_res_path.read_text(encoding="utf-8")
    dos_res = json.loads(orig_dos_res)
    dos_res["worlds"][0]["images"]["badge_raster"]["sha256"] = "f" * 64
    dos_res_path.write_text(json.dumps(dos_res, indent=2), encoding="utf-8")
    with pytest.raises(ValueError, match="dossier_world_vs_manifest_mismatch"):
        audit_multimodal_tree(sandbox_mm)
    dos_res_path.write_text(orig_dos_res, encoding="utf-8")

    diag_path = sandbox_mm / "belief-chart-forensics-carbon" / "diagnoses.json"
    orig_diag = diag_path.read_text(encoding="utf-8")
    diags = json.loads(orig_diag)
    diags[0]["chart_bytes_len"] += 1
    diag_path.write_text(json.dumps(diags, indent=2), encoding="utf-8")
    with pytest.raises(ValueError, match="diagnosis_vs_manifest_mismatch"):
        audit_multimodal_tree(sandbox_mm)
    diag_path.write_text(orig_diag, encoding="utf-8")

    unlisted_png = sandbox_mm / "access-heatmap-carbon" / "rasters" / "medium_seed_99.png"
    unlisted_png.parent.mkdir(parents=True, exist_ok=True)
    unlisted_png.write_bytes(encode_minimal_png(8, 8))
    with pytest.raises(ValueError, match="unlisted_disk_png"):
        audit_multimodal_tree(sandbox_mm)
    unlisted_png.unlink()

    idx_path = sandbox_mm / "index.json"
    idx_obj = json.loads(idx_path.read_text(encoding="utf-8"))
    idx_obj["totals"]["images_read_by_model"] = 261
    idx_path.write_text(json.dumps(idx_obj, indent=2), encoding="utf-8")
    with pytest.raises(ValueError, match="total_images_mismatch"):
        audit_multimodal_tree(sandbox_mm)


def test_socket_blocked_tamper_rejection_on_world_json_judge_seed_and_api_keys(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    sandbox_root = tmp_path / "repo"
    mm_dst = sandbox_root / "results" / "gemini" / "roles_carbon" / "multimodal_evidence"
    eh_dst = sandbox_root / "results" / "gemini" / "roles_carbon" / "exploit_hunter"
    shutil.copytree(MM_ROOT, mm_dst)
    shutil.copytree(EH_ROOT, eh_dst)
    assert MC.main(["--root", str(sandbox_root), "--sync"]) == 0
    assert EC.main(["--root", str(sandbox_root), "--sync"]) == 0
    capsys.readouterr()

    mm_world = mm_dst / "access-heatmap-carbon" / "0.world.json"
    mm_world.write_text(json.dumps({"tier": "medium", "mole": "e05"}), encoding="utf-8")
    assert MC.main(["--root", str(sandbox_root), "--check", "--json"]) == 1
    assert json.loads(capsys.readouterr().out)["ok"] is False
    mm_world.unlink()

    eh_world = eh_dst / "blackbox-swarm-carbon" / "800100.world.json"
    eh_world.write_text(json.dumps({"tier": "medium", "mole": "e04"}), encoding="utf-8")
    assert EC.main(["--root", str(sandbox_root), "--check", "--json"]) == 1
    assert json.loads(capsys.readouterr().out)["ok"] is False
    eh_world.unlink()

    eh_swarm_p = eh_dst / "blackbox-swarm-carbon" / "swarm.json"
    orig_swarm = eh_swarm_p.read_text(encoding="utf-8")
    swarm_obj = json.loads(orig_swarm)
    swarm_obj["attempts"][0]["seed"] = 900000
    eh_swarm_p.write_text(json.dumps(swarm_obj, indent=2), encoding="utf-8")
    assert EC.main(["--root", str(sandbox_root), "--check", "--json"]) == 1
    assert json.loads(capsys.readouterr().out)["ok"] is False
    eh_swarm_p.write_text(orig_swarm, encoding="utf-8")

    fake_key = "AI" + "za" + "FakeFixtureTestValue1234567890"
    eh_md_p = eh_dst / "whitebox-swarm-carbon" / "swarm.md"
    orig_md = eh_md_p.read_text(encoding="utf-8")
    eh_md_p.write_text(orig_md + f"\n{fake_key}\n", encoding="utf-8")
    assert EC.main(["--root", str(sandbox_root), "--check", "--json"]) == 1
    assert json.loads(capsys.readouterr().out)["ok"] is False
    eh_md_p.write_text(orig_md, encoding="utf-8")


def test_self_and_consolidator_source_hygiene_zero_comments_zero_dashes() -> None:
    for py_path in (
        SELF_PATH,
        REPO_ROOT / "canary" / "gemini" / "multimodal_carbon.py",
        REPO_ROOT / "canary" / "gemini" / "exploit_carbon.py",
    ):
        src = py_path.read_text(encoding="utf-8")
        for dash in UNICODE_DASHES:
            assert dash not in src, f"unicode dash in {py_path}"
        tokens = list(tokenize.generate_tokens(io.StringIO(src).readline))
        comments = [tok for tok in tokens if tok.type == tokenize.COMMENT]
        assert comments == [], f"comment token in {py_path}"
        assert HASH_CHAR not in src, f"hash character in {py_path}"
        assert _scan_secrets_in_text(src) == [], f"secret pattern in {py_path}"
        ast.parse(src)
