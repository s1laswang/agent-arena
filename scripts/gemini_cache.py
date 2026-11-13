import gzip
import io
import sys
import tarfile
from pathlib import Path

CACHE = Path(__file__).resolve().parent.parent / ".cache" / "gemini"

if len(sys.argv) != 3 or sys.argv[1] not in ("pack", "unpack"):
    sys.exit("usage: gemini_cache.py pack|unpack FILE.tar.gz")
if sys.argv[1] == "pack":
    with open(sys.argv[2], "wb") as raw, gzip.GzipFile(fileobj=raw, mode="wb", mtime=0, filename="") as gz:
        with tarfile.open(fileobj=gz, mode="w") as t:
            for f in sorted(CACHE.glob("*.json")):
                data = f.read_bytes()
                ti = tarfile.TarInfo(f.name)
                ti.size, ti.mtime, ti.mode, ti.uid, ti.gid, ti.uname, ti.gname = len(data), 0, 0o644, 0, 0, "", ""
                t.addfile(ti, io.BytesIO(data))
else:
    CACHE.mkdir(parents=True, exist_ok=True)
    with tarfile.open(sys.argv[2]) as t:
        for m in t.getmembers():
            if m.isfile() and "/" not in m.name and m.name.endswith(".json"):
                (CACHE / m.name).write_bytes(t.extractfile(m).read())
