import argparse, json, pathlib, shutil

H = pathlib.Path(__file__).parent
TOML = '''schema_version = "1.4"

[task]
name = "sleeper/{seat}-{seed}"
description = "The Sleeper, seed {seed}, agent plays {seat}"

[metadata]
seat = "{seat}"
seed = "{seed}"

[agent]
timeout_sec = 1800

[verifier]
timeout_sec = 300

[environment]
build_timeout_sec = 900
env = {{ SLEEPER_SEAT = "{seat}", SLEEPER_DAY = "{seed}" }}

[[environment.mcp_servers]]
name = "sleeper"
transport = "stdio"
command = "python"
args = ["-m", "sleeper.mcp_server", "--seat", "{seat}", "--day", "{seed}"]
'''


def render(out, seat, seed, base=None):
    seats = json.loads((H / "seats.json").read_text())
    title, duties, powers = seats[seat]
    d = pathlib.Path(out) / f"{seat}-{seed}"
    d.mkdir(parents=True, exist_ok=True)
    (d / "task.toml").write_text(TOML.format(seat=seat, seed=seed))
    t = (H / "instruction.md.tmpl").read_text()
    (d / "instruction.md").write_text(t.format(title=title, duties=duties, powers=powers))
    for sub in ("environment", "tests", "solution"):
        if base and (pathlib.Path(base) / sub).exists():
            shutil.copytree(pathlib.Path(base) / sub, d / sub, dirs_exist_ok=True)
    return d


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--out", default="harbor/tasks")
    p.add_argument("--seat", default="controller")
    p.add_argument("--seeds", type=int, nargs="+", default=[1])
    p.add_argument("--base", default="harbor/base")
    a = p.parse_args()
    for s in a.seeds:
        print(render(a.out, a.seat, s, a.base))
