import argparse
import datetime
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

DOC = Path(__file__).resolve().parent.parent / "docs" / "EXPLOITS.md"
START, END = "<!-- report:start -->", "<!-- report:end -->"
TESTS = ["tests/test_exploits.py", "tests/test_leak_corpus.py", "tests/test_leak_variants.py"]


def run_suite():
    with tempfile.NamedTemporaryFile(suffix=".xml") as f:
        subprocess.run([sys.executable, "-m", "pytest", "-q", f"--junitxml={f.name}", *TESTS], capture_output=True, text=True)
        rows = []
        for c in ET.parse(f.name).getroot().iter("testcase"):
            kids = {k.tag: k for k in c}
            st = "FAIL" if "failure" in kids or "error" in kids else "known-open" if "skipped" in kids else "pass"
            msg = (kids["skipped"].get("message") if "skipped" in kids else "") or ""
            rows.append((c.get("classname").split(".")[-1] + "::" + c.get("name"), st, msg))
        return rows


def run_sweep(days):
    from redteam import sweep
    from multiprocessing import Pool
    lo, hi = map(int, days.split(".."))
    jobs = [(g, s, d, 0) for g in sweep.AGENTS for s in sweep.SEATS for d in range(lo, hi + 1)]
    with Pool() as p:
        return p.map(sweep.one, jobs, chunksize=4)


def render(rows, sweep_rows, days):
    n = {k: sum(r[1] == k for r in rows) for k in ("pass", "known-open", "FAIL")}
    err = [r for r in sweep_rows if "error" in r]
    bad = [r for r in sweep_rows if r.get("reward")]
    out = [START, "", f"## Latest run ({datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%d %H:%M UTC')})", "",
           f"Regenerate with `python -m redteam.report`. Suite: {n['pass']} pass, {n['known-open']} known-open, {n['FAIL']} FAIL. "
           f"Seat sweep (6 agents x 8 seats x days {days}, 1 trial): {len(sweep_rows)} runs, {len(err)} errors, {len(bad)} with reward > 0.", ""]
    if bad:
        out += ["Sweep cells with reward > 0:", ""] + [f"- {r['agent']} seat={r['seat']} day={r['day']} harm={r['harm']}" for r in bad] + [""]
    if err:
        out += ["Sweep errors:", ""] + [f"- {r}" for r in err[:10]] + [""]
    out += ["| test | actual | note |", "|---|---|---|"]
    out += [f"| {t} | {s} | {m[:90]} |" for t, s, m in rows if s != "pass"]
    out += [f"| ... {n['pass']} passing tests not listed | pass | |", "", END]
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", default="1000..1009")
    a = ap.parse_args()
    rows = run_suite()
    sw = run_sweep(a.days)
    block = render(rows, sw, a.days)
    s = DOC.read_text()
    if START in s:
        s = s[: s.index(START)] + block + s[s.index(END) + len(END):]
    else:
        s = s.rstrip("\n") + "\n\n" + block + "\n"
    DOC.write_text(s)
    print(block.split("\n\n")[2])
    return 1 if any(r[1] == "FAIL" for r in rows) or any(r.get("reward") or "error" in r for r in sw) else 0


if __name__ == "__main__":
    sys.exit(main())
