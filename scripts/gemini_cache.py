import sys
import tarfile
from pathlib import Path

CACHE = Path(__file__).resolve().parent.parent / ".cache" / "gemini"

if len(sys.argv) != 3 or sys.argv[1] not in ("pack", "unpack"):
    sys.exit("usage: gemini_cache.py pack|unpack FILE.tar.gz")
if sys.argv[1] == "pack":
    with tarfile.open(sys.argv[2], "w:gz") as t:
        for f in sorted(CACHE.glob("*.json")):
            t.add(f, arcname=f.name)
else:
    CACHE.mkdir(parents=True, exist_ok=True)
    with tarfile.open(sys.argv[2]) as t:
        for m in t.getmembers():
            if m.isfile() and "/" not in m.name and m.name.endswith(".json"):
                (CACHE / m.name).write_bytes(t.extractfile(m).read())
