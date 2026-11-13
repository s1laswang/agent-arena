import struct
import zlib

from agents.images import render_invoice


def test_png_valid(tmp_path):
    p = render_invoice(["INVOICE 42", "ACME OY", "IBAN FI21 1234 5600 0007 85", "TOTAL 12500.00 EUR"], tmp_path / "i.png")
    b = open(p, "rb").read()
    assert b[:8] == b"\x89PNG\r\n\x1a\n"
    w, h = struct.unpack(">II", b[16:24])
    i = b.index(b"IDAT")
    n = struct.unpack(">I", b[i - 4:i])[0]
    raw = zlib.decompress(b[i + 4:i + 4 + n])
    assert len(raw) == h * (w + 1) and 0x20 in raw
