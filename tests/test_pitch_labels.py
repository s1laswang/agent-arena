import glob, re

P = "NOT FOUND (lead-lab pending)"


def test_register_matches():
    reg = open("pitch/HANDOFF.md").read().split("## 1.")[0]
    for f in glob.glob("pitch/*.md"):
        if f.endswith("HANDOFF.md"):
            continue
        c = open(f).read().count(P)
        m = re.search(re.escape(f) + r": (\d+)", reg)
        assert (int(m.group(1)) if m else 0) == c, f


def test_table_rows_labelled():
    for line in open("pitch/MULTIMODEL.md"):
        if line.startswith("|") and re.search(r"\d\.\d{3}|NOT FOUND", line):
            assert "SCRIPTED" in line or "REAL" in line, line
