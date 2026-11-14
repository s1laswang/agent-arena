import gzip
import io
import os
import re
import sys
import tarfile
from pathlib import Path

CACHE = Path(__file__).resolve().parent.parent / ".cache" / "gemini"
SECRET = re.compile(r"AIza[0-9A-Za-z_\-]{30,}|api[_-]?key", re.I)
LIMIT_MB = 25


def check(cache=CACHE):
    bad, size = [], 0
    for f in sorted(cache.glob("*.json")):
        b = f.read_bytes()
        size += len(b)
        t = b.decode("utf8", "replace")
        key = os.environ.get("GEMINI_API_KEY")
        if SECRET.search(t) or (key and key in t):
            bad.append(f.name)
    return bad, size


def pack(out, cache=CACHE):
    with open(out, "wb") as raw, gzip.GzipFile(fileobj=raw, mode="wb", mtime=0, filename="") as gz:
        with tarfile.open(fileobj=gz, mode="w") as t:
            for f in sorted(cache.glob("*.json")):
                data = f.read_bytes()
                ti = tarfile.TarInfo(f.name)
                ti.size, ti.mtime, ti.mode, ti.uid, ti.gid, ti.uname, ti.gname = len(data), 0, 0o644, 0, 0, "", ""
                t.addfile(ti, io.BytesIO(data))


def unpack(src, cache=CACHE):
    cache.mkdir(parents=True, exist_ok=True)
    with tarfile.open(src) as t:
        for m in t.getmembers():
            if m.isfile() and "/" not in m.name and m.name.endswith(".json"):
                (cache / m.name).write_bytes(t.extractfile(m).read())


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "check":
        bad, size = check()
        print("%d bytes, %.2f MB" % (size, size / 1e6))
        if bad:
            sys.exit("secret pattern in: " + ", ".join(bad))
        if size > LIMIT_MB * 1e6:
            sys.exit("cache above %d MB" % LIMIT_MB)
    elif cmd in ("pack", "unpack") and len(sys.argv) == 3:
        bad, _ = check() if cmd == "pack" else ([], 0)
        if bad:
            sys.exit("refusing to pack, secret pattern in: " + ", ".join(bad))
        (pack if cmd == "pack" else unpack)(sys.argv[2])
    else:
        sys.exit("usage: gemini_cache.py check | pack FILE.tar.gz | unpack FILE.tar.gz")
