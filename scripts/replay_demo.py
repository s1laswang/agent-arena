import hashlib
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace as NS

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents import gemini
from scripts import gemini_cache


def fake_generate(model, system, messages, tools, temperature, seed):
    part = NS(function_call=NS(name="my_tickets" if len(messages) < 2 else "end_turn", args={}), text=None)
    return NS(candidates=[NS(content=NS(parts=[part]))], usage_metadata=NS(prompt_token_count=100, candidates_token_count=5))


def day_hash(out):
    d = next(Path(out).iterdir())
    return hashlib.sha256((d / "days.jsonl").read_bytes()).hexdigest()[:16]


def main():
    env, cache, gen = dict(os.environ), gemini.CACHE, gemini._generate
    try:
        return run()
    finally:
        os.environ.clear()
        os.environ.update(env)
        gemini.CACHE, gemini._generate = cache, gen


def run():
    from lab import run as R
    tmp = Path(tempfile.mkdtemp())
    gemini.CACHE = tmp / "cache"
    os.environ["LAB_GEMINI"] = "1"
    os.environ.pop("SLEEPER_OFFLINE", None)
    os.environ["GEMINI_API_KEY"] = "fake"
    gemini._generate = fake_generate
    gemini.reset_usage()
    R.run("staff", 1, 1, out=str(tmp / "live"))
    live = gemini.usage()
    print("live (fake model): calls=%d day=%s" % (live["calls"], day_hash(tmp / "live")))
    tar = tmp / "cache.tar.gz"
    gemini_cache.pack(tar, gemini.CACHE)
    print("packed %d files, %d bytes, sha=%s" % (len(list(gemini.CACHE.glob("*.json"))), tar.stat().st_size, hashlib.sha256(tar.read_bytes()).hexdigest()[:16]))
    for f in gemini.CACHE.glob("*.json"):
        f.unlink()
    gemini_cache.unpack(tar, gemini.CACHE)
    del os.environ["GEMINI_API_KEY"]
    os.environ["SLEEPER_OFFLINE"] = "1"

    def no_net(*a, **k):
        raise AssertionError("network call during replay")

    gemini._generate = no_net
    gemini.reset_usage()
    R.run("staff", 1, 1, out=str(tmp / "replay"))
    rep = gemini.usage()
    same = day_hash(tmp / "live") == day_hash(tmp / "replay")
    print("replay (no key): calls=%d cache_hits=%d day=%s byte_identical=%s" % (rep["calls"], rep["cache_hits"], day_hash(tmp / "replay"), same))
    return 0 if same and rep["calls"] == 0 and rep["cache_hits"] > 0 else 1


if __name__ == "__main__":
    sys.exit(main())
