from __future__ import annotations

import ast
import glob
import io
import json
import math
import os
import shutil
import struct
import subprocess
import sys
import tokenize
from pathlib import Path
from typing import Any, Iterator

import pytest

ROOT = Path(__file__).resolve().parent.parent
VIDEO_PATH = ROOT / "docs" / "demo" / "canary_demo.mp4"
SCRIPT_PATH = ROOT / "scripts" / "record_demo_video.py"
SELF_PATH = Path(__file__).resolve()

PROTECTED_PREFIXES = (
    "canary/env.py",
    "canary/rules.py",
    "canary/solver/",
    "canary/reproduce.py",
    "harbor/",
)

HIGH_PROFILE_IDCS = frozenset({44, 83, 86, 100, 110, 118, 122, 128, 134, 135, 138, 139, 244})


class BitReader:
    def __init__(self, data: bytes) -> None:
        self.data = data
        self.bit_pos = 0
        self.total_bits = len(data) * 8

    def read_bits(self, count: int) -> int:
        if count < 0 or self.bit_pos + count > self.total_bits:
            raise ValueError("bitstream overrun")
        val = 0
        for _ in range(count):
            byte_idx = self.bit_pos >> 3
            bit_idx = 7 - (self.bit_pos & 7)
            val = (val << 1) | ((self.data[byte_idx] >> bit_idx) & 1)
            self.bit_pos += 1
        return val

    def read_ue(self) -> int:
        zeros = 0
        while True:
            if self.bit_pos >= self.total_bits:
                raise ValueError("unterminated exp-golomb code")
            if self.read_bits(1) == 1:
                break
            zeros += 1
            if zeros > 31:
                raise ValueError("exp-golomb code too wide")
        if zeros == 0:
            return 0
        return (1 << zeros) - 1 + self.read_bits(zeros)


def strip_emulation_prevention(nal_body: bytes) -> bytes:
    out = bytearray()
    i = 0
    n = len(nal_body)
    while i < n:
        if i + 2 < n and nal_body[i] == 0 and nal_body[i + 1] == 0 and nal_body[i + 2] == 3:
            out.append(0)
            out.append(0)
            i += 3
        else:
            out.append(nal_body[i])
            i += 1
    return bytes(out)


def parse_h264_sps_nal(sps_nal: bytes) -> dict[str, int]:
    if len(sps_nal) < 4:
        raise ValueError("SPS NAL too short")
    nal_unit_type = sps_nal[0] & 0x1F
    if nal_unit_type != 7:
        raise ValueError(f"expected SPS nal_unit_type 7, got {nal_unit_type}")
    rbsp = strip_emulation_prevention(sps_nal[1:])
    br = BitReader(rbsp)
    profile_idc = br.read_bits(8)
    constraint_flags = br.read_bits(8)
    level_idc = br.read_bits(8)
    sps_id = br.read_ue()
    if profile_idc in HIGH_PROFILE_IDCS:
        chroma_format_idc = br.read_ue()
        if chroma_format_idc == 3:
            br.read_bits(1)
        bit_depth_luma_minus8 = br.read_ue()
        bit_depth_chroma_minus8 = br.read_ue()
    else:
        chroma_format_idc = 1
        bit_depth_luma_minus8 = 0
        bit_depth_chroma_minus8 = 0
    return {
        "profile_idc": profile_idc,
        "constraint_flags": constraint_flags,
        "level_idc": level_idc,
        "sps_id": sps_id,
        "chroma_format_idc": chroma_format_idc,
        "bit_depth_luma": 8 + bit_depth_luma_minus8,
        "bit_depth_chroma": 8 + bit_depth_chroma_minus8,
    }


def parse_avcc_payload(payload: bytes) -> dict[str, Any]:
    if len(payload) < 7:
        raise ValueError("avcC payload too short")
    config_version = payload[0]
    if config_version != 1:
        raise ValueError(f"unsupported avcC configurationVersion {config_version}")
    profile_idc = payload[1]
    profile_compat = payload[2]
    level_idc = payload[3]
    nal_length_size = (payload[4] & 0x03) + 1
    num_sps = payload[5] & 0x1F
    if num_sps < 1:
        raise ValueError("avcC contains zero SPS entries")
    pos = 6
    sps_list: list[bytes] = []
    for _ in range(num_sps):
        if pos + 2 > len(payload):
            raise ValueError("truncated SPS length in avcC")
        sps_len = struct.unpack(">H", payload[pos : pos + 2])[0]
        pos += 2
        if sps_len == 0 or pos + sps_len > len(payload):
            raise ValueError("truncated SPS NAL in avcC")
        sps_list.append(payload[pos : pos + sps_len])
        pos += sps_len
    if pos >= len(payload):
        raise ValueError("missing PPS count in avcC")
    num_pps = payload[pos]
    pos += 1
    for _ in range(num_pps):
        if pos + 2 > len(payload):
            raise ValueError("truncated PPS length in avcC")
        pps_len = struct.unpack(">H", payload[pos : pos + 2])[0]
        pos += 2
        if pos + pps_len > len(payload):
            raise ValueError("truncated PPS NAL in avcC")
        pos += pps_len

    sps_info = parse_h264_sps_nal(sps_list[0])
    chroma_format_idc = sps_info["chroma_format_idc"]
    bit_depth_luma = sps_info["bit_depth_luma"]
    bit_depth_chroma = sps_info["bit_depth_chroma"]

    avcc_ext_chroma: int | None = None
    if profile_idc in {100, 110, 122, 244} and pos + 4 <= len(payload):
        avcc_ext_chroma = payload[pos] & 0x03
        ext_luma = 8 + (payload[pos + 1] & 0x07)
        ext_chroma = 8 + (payload[pos + 2] & 0x07)
        if avcc_ext_chroma != chroma_format_idc:
            raise ValueError(f"avcC chroma {avcc_ext_chroma} disagrees with SPS chroma {chroma_format_idc}")
        if ext_luma != bit_depth_luma or ext_chroma != bit_depth_chroma:
            raise ValueError("avcC bit depth disagrees with SPS bit depth")

    if chroma_format_idc == 1 and bit_depth_luma == 8 and bit_depth_chroma == 8:
        pix_fmt = "yuv420p"
    elif chroma_format_idc == 2 and bit_depth_luma == 8 and bit_depth_chroma == 8:
        pix_fmt = "yuv422p"
    elif chroma_format_idc == 3 and bit_depth_luma == 8 and bit_depth_chroma == 8:
        pix_fmt = "yuv444p"
    else:
        pix_fmt = f"chroma{chroma_format_idc}_luma{bit_depth_luma}_chroma{bit_depth_chroma}"

    return {
        "configuration_version": config_version,
        "profile_idc": profile_idc,
        "profile_compat": profile_compat,
        "level_idc": level_idc,
        "nal_length_size": nal_length_size,
        "sps_count": num_sps,
        "pps_count": num_pps,
        "chroma_format_idc": chroma_format_idc,
        "avcc_ext_chroma": avcc_ext_chroma,
        "bit_depth_luma": bit_depth_luma,
        "bit_depth_chroma": bit_depth_chroma,
        "pix_fmt": pix_fmt,
    }


def iter_mp4_boxes(buf: bytes, start: int = 0, end: int | None = None) -> Iterator[tuple[str, int, int, int, bytes]]:
    limit = len(buf) if end is None else end
    if limit > len(buf) or start < 0 or start > limit:
        raise ValueError("invalid box slice bounds")
    pos = start
    while pos < limit:
        if pos + 8 > limit:
            raise ValueError(f"truncated MP4 box header at offset {pos}")
        size32 = struct.unpack(">I", buf[pos : pos + 4])[0]
        box_type = buf[pos + 4 : pos + 8].decode("latin1")
        hdr = 8
        if size32 == 1:
            if pos + 16 > limit:
                raise ValueError(f"truncated 64-bit MP4 box header at offset {pos}")
            box_size = struct.unpack(">Q", buf[pos + 8 : pos + 16])[0]
            hdr = 16
        elif size32 == 0:
            box_size = limit - pos
        else:
            box_size = size32
        if box_size < hdr or pos + box_size > limit:
            raise ValueError(f"invalid MP4 box {box_type!r} size {box_size} at offset {pos}")
        box_end = pos + box_size
        yield box_type, pos, hdr, box_end, buf[pos + hdr : box_end]
        pos = box_end


def _parse_timescale_duration(payload: bytes) -> tuple[int, int]:
    if len(payload) < 20:
        raise ValueError("header box too short")
    version = payload[0]
    if version == 0:
        timescale, duration = struct.unpack(">II", payload[12:20])
    elif version == 1:
        if len(payload) < 32:
            raise ValueError("version 1 header box too short")
        timescale, duration = struct.unpack(">IQ", payload[20:32])
    else:
        raise ValueError(f"unsupported fullbox version {version}")
    if timescale <= 0:
        raise ValueError(f"non-positive timescale {timescale}")
    return timescale, duration


def _parse_tkhd_dims(payload: bytes) -> tuple[int, int]:
    version = payload[0]
    offset = 76 if version == 0 else 88
    if len(payload) < offset + 8:
        raise ValueError("tkhd box too short")
    w_fixed, h_fixed = struct.unpack(">II", payload[offset : offset + 8])
    return w_fixed >> 16, h_fixed >> 16


def _parse_video_trak(trak_payload: bytes) -> dict[str, Any] | None:
    tkhd_dims = (0, 0)
    handler_type: str | None = None
    mdhd_ts = 0
    mdhd_dur = 0
    stbl_payload: bytes | None = None

    for btype, _, _, _, bpay in iter_mp4_boxes(trak_payload):
        if btype == "tkhd":
            tkhd_dims = _parse_tkhd_dims(bpay)
        elif btype == "mdia":
            for mtype, _, _, _, mpay in iter_mp4_boxes(bpay):
                if mtype == "mdhd":
                    mdhd_ts, mdhd_dur = _parse_timescale_duration(mpay)
                elif mtype == "hdlr":
                    if len(mpay) < 12:
                        raise ValueError("hdlr box too short")
                    handler_type = mpay[8:12].decode("latin1")
                elif mtype == "minf":
                    for ntype, _, _, _, npay in iter_mp4_boxes(mpay):
                        if ntype == "stbl":
                            stbl_payload = npay

    if handler_type != "vide":
        return None
    if stbl_payload is None:
        raise ValueError("video track missing stbl box")

    codec_tag: str | None = None
    stsd_width = 0
    stsd_height = 0
    depth = 0
    avcc_info: dict[str, Any] | None = None
    sample_count = 0
    sample_sizes: list[int] = []
    sync_sample_count: int | None = None

    for stype, _, _, _, spay in iter_mp4_boxes(stbl_payload):
        if stype == "stsd":
            if len(spay) < 16:
                raise ValueError("stsd box too short")
            entry_count = struct.unpack(">I", spay[4:8])[0]
            if entry_count < 1:
                raise ValueError("stsd has zero sample entries")
            for etype, _, ehdr, _, epay in iter_mp4_boxes(spay, 8, len(spay)):
                if ehdr != 8 or len(epay) < 78:
                    raise ValueError(f"visual sample entry {etype!r} too short")
                codec_tag = etype
                stsd_width, stsd_height = struct.unpack(">HH", epay[24:28])
                depth = struct.unpack(">H", epay[74:76])[0]
                for ctype, _, _, _, cpay in iter_mp4_boxes(epay, 78, len(epay)):
                    if ctype == "avcC":
                        avcc_info = parse_avcc_payload(cpay)
                break
        elif stype == "stsz":
            if len(spay) < 12:
                raise ValueError("stsz box too short")
            fixed_size, count = struct.unpack(">II", spay[4:12])
            sample_count = count
            if fixed_size > 0:
                sample_sizes = [fixed_size] * count
            else:
                expected_end = 12 + 4 * count
                if len(spay) < expected_end:
                    raise ValueError("truncated stsz sample table")
                sample_sizes = list(struct.unpack(f">{count}I", spay[12:expected_end])) if count else []
        elif stype == "stss":
            if len(spay) < 8:
                raise ValueError("stss box too short")
            sync_sample_count = struct.unpack(">I", spay[4:8])[0]

    video_duration_s = (mdhd_dur / mdhd_ts) if mdhd_ts > 0 else 0.0
    fps = (sample_count / video_duration_s) if video_duration_s > 0 else 0.0
    return {
        "codec_tag": codec_tag,
        "width": stsd_width or tkhd_dims[0],
        "height": stsd_height or tkhd_dims[1],
        "tkhd_width": tkhd_dims[0],
        "tkhd_height": tkhd_dims[1],
        "depth": depth,
        "avcc": avcc_info,
        "video_duration_s": video_duration_s,
        "sample_count": sample_count,
        "distinct_sample_sizes": len(set(sample_sizes)),
        "min_sample_size": min(sample_sizes) if sample_sizes else 0,
        "max_sample_size": max(sample_sizes) if sample_sizes else 0,
        "total_sample_bytes": sum(sample_sizes),
        "sync_sample_count": sync_sample_count,
        "fps": fps,
    }


def inspect_mp4_bytes(buf: bytes) -> dict[str, Any]:
    if len(buf) < 32:
        raise ValueError("MP4 buffer smaller than 32 bytes")
    top_boxes: list[str] = []
    major_brand: str | None = None
    mvhd_duration_s: float | None = None
    video_track: dict[str, Any] | None = None
    mdat_payload_bytes = 0

    for btype, _, _, _, bpay in iter_mp4_boxes(buf):
        top_boxes.append(btype)
        if btype == "ftyp":
            if len(bpay) < 8:
                raise ValueError("ftyp box too short")
            major_brand = bpay[0:4].decode("latin1")
        elif btype == "mdat":
            mdat_payload_bytes += len(bpay)
        elif btype == "moov":
            for mtype, _, _, _, mpay in iter_mp4_boxes(bpay):
                if mtype == "mvhd":
                    ts, dur = _parse_timescale_duration(mpay)
                    mvhd_duration_s = dur / ts
                elif mtype == "trak" and video_track is None:
                    parsed = _parse_video_trak(mpay)
                    if parsed is not None:
                        video_track = parsed

    if major_brand is None:
        raise ValueError("missing ftyp box")
    if mvhd_duration_s is None:
        raise ValueError("missing mvhd box in moov")
    if video_track is None:
        raise ValueError("missing video track in moov")

    return {
        "file_size_bytes": len(buf),
        "top_boxes": top_boxes,
        "major_brand": major_brand,
        "duration_s": mvhd_duration_s,
        "mdat_payload_bytes": mdat_payload_bytes,
        "video": video_track,
    }


def validate_demo_mp4_info(info: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    top = info.get("top_boxes") or []
    for req in ("ftyp", "moov", "mdat"):
        if req not in top:
            errors.append(f"missing top-level {req} box")

    dur = float(info.get("duration_s") or 0.0)
    if not (60.0 <= dur <= 90.0):
        errors.append(f"container duration {dur:.3f}s outside [60.0, 90.0]")

    vid = info.get("video") or {}
    vdur = float(vid.get("video_duration_s") or 0.0)
    if not (60.0 <= vdur <= 90.0):
        errors.append(f"video track duration {vdur:.3f}s outside [60.0, 90.0]")
    if abs(dur - vdur) > 2.0:
        errors.append(f"mvhd duration {dur:.3f}s and mdhd duration {vdur:.3f}s diverge")

    codec = vid.get("codec_tag")
    if codec not in {"avc1", "avc3"}:
        errors.append(f"expected H.264 codec avc1/avc3, got {codec!r}")

    avcc = vid.get("avcc")
    if not isinstance(avcc, dict):
        errors.append("missing avcC decoder configuration box")
    else:
        if avcc.get("pix_fmt") != "yuv420p":
            errors.append(f"expected pix_fmt yuv420p, got {avcc.get('pix_fmt')!r}")
        if avcc.get("chroma_format_idc") != 1:
            errors.append(f"expected chroma_format_idc 1, got {avcc.get('chroma_format_idc')!r}")
        if avcc.get("bit_depth_luma") != 8 or avcc.get("bit_depth_chroma") != 8:
            errors.append("expected 8-bit luma and chroma for yuv420p")

    width = int(vid.get("width") or 0)
    height = int(vid.get("height") or 0)
    if width < 1280 or height < 720 or width % 2 != 0 or height % 2 != 0:
        errors.append(f"invalid video dimensions {width}x{height}")

    sample_count = int(vid.get("sample_count") or 0)
    fps = float(vid.get("fps") or 0.0)
    if sample_count < 900:
        errors.append(f"too few video frames: {sample_count}")
    if not (12.0 <= fps <= 60.0):
        errors.append(f"fps {fps:.2f} outside [12.0, 60.0]")
    if int(vid.get("distinct_sample_sizes") or 0) < 25:
        errors.append(f"suspiciously uniform frame sizes: {vid.get('distinct_sample_sizes')}")
    if int(info.get("mdat_payload_bytes") or 0) < 100_000:
        errors.append(f"mdat payload too small: {info.get('mdat_payload_bytes')}")

    return errors


def _mp4_box(box_type: str, payload: bytes) -> bytes:
    return struct.pack(">I4s", 8 + len(payload), box_type.encode("latin1")) + payload


def _encode_ue_bits(val: int) -> str:
    code_num = val + 1
    bit_len = code_num.bit_length()
    zeros = bit_len - 1
    return ("0" * zeros) + format(code_num, f"0{bit_len}b")


def _pack_bitstring(bits: str) -> bytes:
    padded = bits + "1"
    while len(padded) % 8 != 0:
        padded += "0"
    return int(padded, 2).to_bytes(len(padded) // 8, "big")


def _build_synthetic_mp4(
    *,
    codec_tag: str = "avc1",
    profile_idc: int = 100,
    chroma_format_idc: int = 1,
    bit_depth_minus8: int = 0,
    include_avcc_ext: bool = True,
    width: int = 1280,
    height: int = 720,
    duration_s: float = 75.0,
    fps: int = 30,
    varied_samples: bool = True,
) -> bytes:
    ftyp = _mp4_box("ftyp", b"isom" + struct.pack(">I", 512) + b"isomiso2avc1mp41")
    timescale = 1000
    dur_units = int(round(duration_s * timescale))
    mvhd = _mp4_box(
        "mvhd",
        b"\x00\x00\x00\x00"
        + struct.pack(">IIII", 0, 0, timescale, dur_units)
        + struct.pack(">IH", 0x00010000, 0x0100)
        + (b"\x00" * 10)
        + (b"\x00" * 36)
        + (b"\x00" * 24)
        + struct.pack(">I", 2),
    )
    tkhd = _mp4_box(
        "tkhd",
        b"\x00\x00\x00\x03"
        + struct.pack(">III4sI", 0, 0, 1, b"\x00" * 4, dur_units)
        + (b"\x00" * 8)
        + struct.pack(">HHHH", 0, 0, 0, 0)
        + (b"\x00" * 36)
        + struct.pack(">II", width << 16, height << 16),
    )
    mdhd = _mp4_box(
        "mdhd",
        b"\x00\x00\x00\x00" + struct.pack(">IIIIHH", 0, 0, timescale, dur_units, 0x55C4, 0),
    )
    hdlr = _mp4_box("hdlr", b"\x00\x00\x00\x00\x00\x00\x00\x00vide" + (b"\x00" * 12) + b"VideoHandler\x00")

    bits = format(profile_idc, "08b") + "00000000" + format(31, "08b") + _encode_ue_bits(0)
    if profile_idc in HIGH_PROFILE_IDCS:
        bits += _encode_ue_bits(chroma_format_idc)
        if chroma_format_idc == 3:
            bits += "0"
        bits += _encode_ue_bits(bit_depth_minus8)
        bits += _encode_ue_bits(bit_depth_minus8)
    sps_nal = b"\x67" + _pack_bitstring(bits)
    pps_nal = b"\x68\xEB\xE3\xCB\x22\xC0"

    avcc_body = (
        bytes([1, profile_idc, 0, 31, 0xFF, 0xE1])
        + struct.pack(">H", len(sps_nal))
        + sps_nal
        + bytes([1])
        + struct.pack(">H", len(pps_nal))
        + pps_nal
    )
    if include_avcc_ext and profile_idc in {100, 110, 122, 244}:
        avcc_body += bytes([0xFC | (chroma_format_idc & 0x03), 0xF8 | bit_depth_minus8, 0xF8 | bit_depth_minus8, 0])
    avcc_box = _mp4_box("avcC", avcc_body) if codec_tag in {"avc1", "avc3"} else b""

    sample_entry_payload = (
        (b"\x00" * 6)
        + struct.pack(">H", 1)
        + (b"\x00" * 16)
        + struct.pack(">HHII", width, height, 0x00480000, 0x00480000)
        + (b"\x00" * 4)
        + struct.pack(">H", 1)
        + (b"\x00" * 32)
        + struct.pack(">Hh", 0x0018, -1)
        + avcc_box
    )
    sample_entry = _mp4_box(codec_tag, sample_entry_payload)
    stsd = _mp4_box("stsd", b"\x00\x00\x00\x00" + struct.pack(">I", 1) + sample_entry)

    frame_count = max(1, int(round(duration_s * fps)))
    if varied_samples:
        sizes = [1200 + ((idx * 137) % 4096) for idx in range(frame_count)]
    else:
        sizes = [64] * frame_count
    stsz = _mp4_box(
        "stsz",
        b"\x00\x00\x00\x00" + struct.pack(">II", 0, frame_count) + struct.pack(f">{frame_count}I", *sizes),
    )
    stss = _mp4_box("stss", b"\x00\x00\x00\x00" + struct.pack(">III", 2, 1, max(2, frame_count // 2)))
    stbl = _mp4_box("stbl", stsd + stsz + stss)
    minf = _mp4_box("minf", stbl)
    mdia = _mp4_box("mdia", mdhd + hdlr + minf)
    trak = _mp4_box("trak", tkhd + mdia)
    moov = _mp4_box("moov", mvhd + trak)
    mdat = _mp4_box("mdat", b"\x00\x00\x00\x02\x65\x88" * 25_000)
    return ftyp + moov + mdat


def _find_ffmpeg_exe() -> str | None:
    on_path = shutil.which("ffmpeg")
    if on_path:
        return on_path
    try:
        import imageio_ffmpeg

        exe = imageio_ffmpeg.get_ffmpeg_exe()
        if exe and Path(exe).is_file():
            return str(exe)
    except Exception:
        pass
    patterns = (
        "/localscratch/fleet-silas/demo-video/venv/lib/python*/site-packages/imageio_ffmpeg/binaries/ffmpeg-*",
        "/tmp/fleet-silas/shared/*venv*/lib/python*/site-packages/imageio_ffmpeg/binaries/ffmpeg-*",
    )
    for pat in patterns:
        for cand in sorted(glob.glob(pat)):
            if os.path.isfile(cand) and os.access(cand, os.X_OK):
                return cand
    return None


def _decode_rgb_frame(ffmpeg_exe: str, mp4_path: Path, timestamp_s: float, width: int, height: int) -> bytes:
    proc = subprocess.run(
        [
            ffmpeg_exe,
            "-hide_banner",
            "-loglevel",
            "error",
            "-ss",
            f"{timestamp_s:.2f}",
            "-i",
            str(mp4_path),
            "-frames:v",
            "1",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            "-",
        ],
        capture_output=True,
        timeout=30,
    )
    assert proc.returncode == 0, proc.stderr.decode("utf-8", errors="replace")[-500:]
    expected = width * height * 3
    assert len(proc.stdout) == expected, f"expected {expected} rgb24 bytes at t={timestamp_s:.2f}s, got {len(proc.stdout)}"
    return proc.stdout


def _frame_stats(rgb: bytes, stride: int = 97) -> tuple[float, float]:
    sampled = rgb[::stride]
    mean_val = sum(sampled) / len(sampled)
    variance = sum((b - mean_val) ** 2 for b in sampled) / len(sampled)
    return mean_val, math.sqrt(variance)


def _mean_abs_diff(rgb_a: bytes, rgb_b: bytes, stride: int = 97) -> float:
    sa = rgb_a[::stride]
    sb = rgb_b[::stride]
    n = min(len(sa), len(sb))
    return sum(abs(sa[i] - sb[i]) for i in range(n)) / n


def _audit_source_hygiene(py_path: Path) -> list[str]:
    issues: list[str] = []
    raw = py_path.read_bytes()
    text = raw.decode("utf-8")
    em_dash = chr(0x2014)
    en_dash = chr(0x2013)
    if em_dash in text:
        issues.append(f"{py_path.name} contains em dash U+2014")
    if en_dash in text:
        issues.append(f"{py_path.name} contains en dash U+2013")
    for tok in tokenize.generate_tokens(io.StringIO(text).readline):
        if tok.type == tokenize.COMMENT:
            issues.append(f"{py_path.name} contains comment at line {tok.start[0]}: {tok.string[:40]!r}")
    tree = ast.parse(text, filename=str(py_path))
    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[0] in {"playwright", "imageio_ffmpeg"}:
                    issues.append(f"{py_path.name} imports {alias.name} at module top level")
        elif isinstance(node, ast.ImportFrom) and node.module:
            if node.module.split(".")[0] in {"playwright", "imageio_ffmpeg"}:
                issues.append(f"{py_path.name} imports from {node.module} at module top level")
    return issues


def _load_committed_hard_episode(dirs: list[Path], seed: int) -> dict[str, Any]:
    for d in dirs:
        ep_file = d / "episodes.jsonl"
        if not ep_file.is_file():
            continue
        for line in ep_file.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            if int(row.get("seed", -1)) == seed:
                return row
    raise AssertionError(f"committed hard seed {seed} not found in {dirs}")


def _extract_seed_record(manifest: dict[str, Any], seed: int) -> dict[str, Any]:
    candidates: list[dict[str, Any]] = []
    for key in ("replays", "office_replays", "episodes", "seeds"):
        val = manifest.get(key)
        if isinstance(val, list):
            for item in val:
                if isinstance(item, dict) and int(item.get("seed", -1)) == seed:
                    candidates.append(item)
        elif isinstance(val, dict):
            sub = val.get(str(seed)) or val.get(seed)
            if isinstance(sub, dict):
                candidates.append(sub)
    for key in (f"seed_{seed}", f"hard_seed_{seed}"):
        sub = manifest.get(key)
        if isinstance(sub, dict):
            candidates.append(sub)
    if not candidates:
        raise AssertionError(f"seed {seed} missing from --dry-run manifest keys {sorted(manifest)}")
    return candidates[0]


def test_mp4_inspector_accepts_valid_h264_yuv420p_high_and_main_profiles():
    high_mp4 = _build_synthetic_mp4(profile_idc=100, chroma_format_idc=1, duration_s=74.5, fps=30)
    high_info = inspect_mp4_bytes(high_mp4)
    assert validate_demo_mp4_info(high_info) == []
    assert high_info["video"]["avcc"]["pix_fmt"] == "yuv420p"
    assert high_info["video"]["width"] == 1280
    assert high_info["video"]["height"] == 720

    main_mp4 = _build_synthetic_mp4(profile_idc=77, include_avcc_ext=False, duration_s=65.0, fps=24)
    main_info = inspect_mp4_bytes(main_mp4)
    assert validate_demo_mp4_info(main_info) == []
    assert main_info["video"]["avcc"]["pix_fmt"] == "yuv420p"


def test_mp4_inspector_rejects_wrong_chroma_codec_duration_and_static_samples():
    yuv444_mp4 = _build_synthetic_mp4(profile_idc=244, chroma_format_idc=3)
    errs_444 = validate_demo_mp4_info(inspect_mp4_bytes(yuv444_mp4))
    assert any("yuv420p" in e for e in errs_444)

    ten_bit_mp4 = _build_synthetic_mp4(profile_idc=110, chroma_format_idc=1, bit_depth_minus8=2)
    errs_10b = validate_demo_mp4_info(inspect_mp4_bytes(ten_bit_mp4))
    assert any("8-bit" in e or "yuv420p" in e for e in errs_10b)

    hevc_mp4 = _build_synthetic_mp4(codec_tag="hev1")
    errs_hevc = validate_demo_mp4_info(inspect_mp4_bytes(hevc_mp4))
    assert any("H.264" in e for e in errs_hevc)

    short_mp4 = _build_synthetic_mp4(duration_s=42.0)
    errs_short = validate_demo_mp4_info(inspect_mp4_bytes(short_mp4))
    assert any("outside [60.0, 90.0]" in e for e in errs_short)

    long_mp4 = _build_synthetic_mp4(duration_s=96.0)
    errs_long = validate_demo_mp4_info(inspect_mp4_bytes(long_mp4))
    assert any("outside [60.0, 90.0]" in e for e in errs_long)

    static_mp4 = _build_synthetic_mp4(varied_samples=False)
    errs_static = validate_demo_mp4_info(inspect_mp4_bytes(static_mp4))
    assert any("uniform frame sizes" in e for e in errs_static)

    with pytest.raises(ValueError):
        inspect_mp4_bytes(b"not-an-mp4")


def test_emulation_prevention_stripping_in_sps_nal():
    tail = _pack_bitstring(_encode_ue_bits(0) + _encode_ue_bits(1) + _encode_ue_bits(0) + _encode_ue_bits(0))
    raw_rbsp = bytes([100, 0, 0]) + tail
    epb_rbsp = raw_rbsp[:3] + b"\x03" + raw_rbsp[3:]
    parsed = parse_h264_sps_nal(b"\x67" + epb_rbsp)
    assert parsed["profile_idc"] == 100
    assert parsed["constraint_flags"] == 0
    assert parsed["level_idc"] == 0
    assert parsed["sps_id"] == 0
    assert parsed["chroma_format_idc"] == 1
    assert parsed["bit_depth_luma"] == 8
    assert parsed["bit_depth_chroma"] == 8


def test_committed_demo_seeds_ground_truth_and_game_build(tmp_path, monkeypatch):
    monkeypatch.setenv("CANARY_ALLOW_DEV", "1")
    sys.path.insert(0, str(ROOT / "game"))
    import build as game_build
    import canary_game

    site_dir = tmp_path / "site"
    manifest = game_build.build(site_dir)
    assert (site_dir / "index.html").is_file()
    assert (site_dir / "app.js").is_file()
    assert (site_dir / "style.css").is_file()
    assert (site_dir / "py" / "manifest.json").is_file()
    assert "canary_game.py" in manifest["files"]

    solver_3000 = canary_game.solver_result(3000)
    assert solver_3000["correct"] is True
    assert abs(float(solver_3000["score"]) - 0.79) < 1e-9
    assert int(solver_3000["final_day"]) == 6

    from scripts.verify_replay import replay_episode

    v14 = ROOT / "data" / "runs" / "committed" / "v1.4"
    solver_dirs = [v14 / "reference" / "solver-hard-20261114-121126", v14 / "reference" / "solver-hard-seeds20to29"]
    gemini_dirs = [v14 / "opencode-gemini-4-carbon" / "hard"]

    gem_6 = _load_committed_hard_episode(gemini_dirs, 6)
    sol_6 = _load_committed_hard_episode(solver_dirs, 6)
    assert gem_6["accused"] == "e34" and gem_6["correct"] is True
    assert abs(float(gem_6["score"]) - 0.73) < 1e-9
    assert int(gem_6["final_day"]) == 6
    assert sol_6["accused"] == "e34" and sol_6["correct"] is True
    assert abs(float(sol_6["score"]) - 0.71) < 1e-9
    assert abs(float(replay_episode(gem_6)["score"]) - 0.73) < 1e-9

    gem_26 = _load_committed_hard_episode(gemini_dirs, 26)
    sol_26 = _load_committed_hard_episode(solver_dirs, 26)
    assert sol_26["accused"] == "e08" and sol_26["correct"] is True
    assert abs(float(sol_26["score"]) - 0.69) < 1e-9
    assert int(sol_26["final_day"]) == 7
    assert gem_26["accused"] == "e04" and gem_26["correct"] is False
    assert abs(float(gem_26["score"]) - (-1.0)) < 1e-9
    assert int(gem_26["final_day"]) == 10
    assert abs(float(replay_episode(gem_26)["score"]) - (-1.0)) < 1e-9

    transcript_26 = v14 / "opencode-gemini-4-carbon" / "hard" / "transcripts" / "26.txt"
    assert transcript_26.is_file()
    assert "e04" in transcript_26.read_text(encoding="utf-8")


def test_self_hygiene_and_zero_protected_paths():
    assert _audit_source_hygiene(SELF_PATH) == []
    assert all(b < 128 for b in SELF_PATH.read_bytes())
    assert chr(35) not in SELF_PATH.read_text(encoding="utf-8")

    if (ROOT / ".git").exists():
        base_check = subprocess.run(
            ["git", "cat-file", "-e", "587167429aabe85fdf53786cb78c47b272ea0325^{commit}"],
            cwd=ROOT,
            capture_output=True,
            timeout=10,
        )
        if base_check.returncode == 0:
            diff = subprocess.run(
                ["git", "diff", "--name-only", "587167429aabe85fdf53786cb78c47b272ea0325..HEAD"],
                cwd=ROOT,
                capture_output=True,
                text=True,
                timeout=10,
                check=True,
            )
            touched = [ln.strip() for ln in diff.stdout.splitlines() if ln.strip()]
            forbidden = [
                p for p in touched if any(p == pref or p.startswith(pref) for pref in PROTECTED_PREFIXES)
            ]
            assert forbidden == [], f"protected paths modified: {forbidden}"


def test_live_script_hygiene_help_and_dry_run_parity():
    assert SCRIPT_PATH.is_file(), f"missing recorder script at {SCRIPT_PATH}"
    assert _audit_source_hygiene(SCRIPT_PATH) == []

    env = {**os.environ, "PYTHONPATH": str(ROOT), "CANARY_ALLOW_DEV": "1"}
    help_proc = subprocess.run(
        [sys.executable, str(SCRIPT_PATH), "--help"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert help_proc.returncode == 0, help_proc.stderr
    assert "--dry-run" in help_proc.stdout and "--out" in help_proc.stdout

    dry_proc = subprocess.run(
        [sys.executable, str(SCRIPT_PATH), "--dry-run"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert dry_proc.returncode == 0, dry_proc.stderr
    manifest = json.loads(dry_proc.stdout)
    assert isinstance(manifest, dict)

    width = int(manifest.get("width") or 0)
    height = int(manifest.get("height") or 0)
    fps = float(manifest.get("fps") or 0.0)
    dur_target = float(manifest.get("duration_target_s") or manifest.get("target_duration_s") or 0.0)
    assert width >= 1280 and height >= 720
    assert 12.0 <= fps <= 60.0
    assert 60.0 <= dur_target <= 90.0

    game_seed = manifest.get("game_seed")
    if game_seed is None and isinstance(manifest.get("game"), dict):
        game_seed = manifest["game"].get("seed")
    assert int(game_seed) == 3000

    acts = manifest.get("acts") or manifest.get("scenes")
    assert isinstance(acts, list) and len(acts) >= 3

    rec6 = _extract_seed_record(manifest, 6)
    assert rec6.get("mole") == "e34"
    assert abs(float(rec6["gemini_score"]) - 0.73) < 1e-6
    assert bool(rec6["gemini_correct"]) is True
    assert rec6.get("gemini_accused") == "e34"
    assert abs(float(rec6["solver_score"]) - 0.71) < 1e-6

    rec26 = _extract_seed_record(manifest, 26)
    assert rec26.get("mole") == "e08"
    assert abs(float(rec26["gemini_score"]) - (-1.0)) < 1e-6
    assert bool(rec26["gemini_correct"]) is False
    assert rec26.get("gemini_accused") == "e04"
    assert abs(float(rec26["solver_score"]) - 0.69) < 1e-6


def test_live_artifact_canary_demo_mp4_container_codec_duration_and_frames():
    assert VIDEO_PATH.is_file(), f"missing demo video at {VIDEO_PATH}"
    assert not VIDEO_PATH.is_symlink()
    raw = VIDEO_PATH.read_bytes()
    assert not raw.startswith(b"version https://git-lfs.github.com/spec/"), "MP4 must not be a Git LFS pointer"
    assert 150_000 <= len(raw) <= 25 * 1024 * 1024, f"unexpected MP4 byte size {len(raw)}"

    info = inspect_mp4_bytes(raw)
    errors = validate_demo_mp4_info(info)
    assert errors == [], f"MP4 spec violations: {errors}"

    ffmpeg_exe = _find_ffmpeg_exe()
    if ffmpeg_exe is not None:
        dur = float(info["duration_s"])
        w = int(info["video"]["width"])
        h = int(info["video"]["height"])
        fractions = (0.08, 0.24, 0.44, 0.62, 0.80, 0.93)
        frames = [_decode_rgb_frame(ffmpeg_exe, VIDEO_PATH, dur * frac, w, h) for frac in fractions]
        for idx, frame in enumerate(frames):
            _, std_val = _frame_stats(frame)
            assert std_val > 8.0, f"decoded frame {idx} appears blank or near-uniform (std={std_val:.2f})"
        cross_act_diffs = [
            _mean_abs_diff(frames[0], frames[2]),
            _mean_abs_diff(frames[2], frames[4]),
            _mean_abs_diff(frames[0], frames[4]),
        ]
        assert max(cross_act_diffs) > 5.0, f"frames across acts look static: {cross_act_diffs}"
        assert sum(1 for d in cross_act_diffs if d > 2.5) >= 2, f"insufficient scene transitions: {cross_act_diffs}"
