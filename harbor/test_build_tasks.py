"""Checks for harbor/build_tasks.py (stdlib only, no Docker needed).

    python -m unittest discover -s harbor -p "test_*.py"
"""
from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(HERE))

import build_tasks  # noqa: E402

try:
    import tomllib
except ImportError:  # Python 3.10
    tomllib = None


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _one_episode_per_family() -> list[str]:
    from pinbox.eval import eval_set
    seen, out = set(), []
    for ep in eval_set():
        if ep["family"] not in seen:
            seen.add(ep["family"])
            out.append(f"{ep['family']}:{ep['seed']}:{ep['difficulty']}")
    return out


class BuildTasksTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(prefix="pinbox harbor ö ")
        cls.out = Path(cls.tmp.name) / "tasks"
        cls.shared_out = Path(cls.tmp.name) / "shared"
        cls.specs = _one_episode_per_family()
        build_tasks.main(["--out", str(cls.out), "--episodes", ",".join(cls.specs)])
        build_tasks.main(["--out", str(cls.shared_out), "--episodes", cls.specs[0], "--verifier", "shared"])
        cls.folders = sorted(p for p in cls.out.iterdir() if p.is_dir())

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_one_folder_per_episode_with_harbor_layout(self):
        self.assertEqual(len(self.folders), len(self.specs))
        for f in self.folders:
            for rel in ["task.toml", "instruction.md", "environment/Dockerfile", "environment/docker-compose.yaml",
                        "environment/pinbox-env/Dockerfile", "environment/pinbox-env/pinbox.zip",
                        "environment/pinbox-env/start.sh", "environment/pinbox-env/collect.py",
                        "solution/solve.sh", "solution/run_solution.py", "solution/pinbox.zip",
                        "tests/test.sh", "tests/verify.py", "tests/expected.json", "tests/Dockerfile"]:
                self.assertTrue((f / rel).is_file(), f"{f.name}: missing {rel}")

    @unittest.skipIf(tomllib is None, "tomllib needs Python 3.11+")
    def test_task_toml(self):
        for f in self.folders:
            cfg = tomllib.loads((f / "task.toml").read_text(encoding="utf-8"))
            self.assertEqual(cfg["task"]["name"], f"poisoned-inbox/{f.name}")
            self.assertEqual(cfg["verifier"]["environment_mode"], "separate")
            self.assertEqual(cfg["verifier"]["collect"][0]["service"], "pinbox-env")
            self.assertEqual(cfg["artifacts"][0], {"source": "/srv/pinbox/out", "service": "pinbox-env"})
            mcp = cfg["environment"]["mcp_servers"][0]
            self.assertEqual((mcp["name"], mcp["transport"], mcp["url"]),
                             ("pinbox", "streamable-http", "http://pinbox-env:8000/mcp"))
            self.assertEqual(cfg["metadata"]["episode_id"], f.name)

    def test_shell_scripts_are_lf(self):
        for f in self.folders + [p for p in self.shared_out.iterdir() if p.is_dir()]:
            for path in f.rglob("*"):
                if path.is_file() and path.suffix != ".zip":
                    data = path.read_bytes()
                    self.assertNotIn(b"\r\n", data, f"CRLF in {path}")
                    self.assertNotIn(b"@@", data, f"unfilled placeholder in {path}")
            for sh in f.rglob("*.sh"):
                self.assertTrue(sh.read_bytes().startswith(b"#!"), sh)

    def test_agent_image_carries_nothing(self):
        for f in self.folders:
            df = (f / "environment" / "Dockerfile").read_text(encoding="utf-8")
            self.assertNotRegex(df, r"(?m)^\s*(COPY|ADD)\b")
            self.assertIn("pinbox-env", (f / "environment" / ".dockerignore").read_text(encoding="utf-8"))

    def test_zip_is_deterministic_and_complete(self):
        a, b = build_tasks.pinbox_zip(), build_tasks.pinbox_zip()
        self.assertEqual(a, b)
        for f in self.folders:
            self.assertEqual((f / "environment/pinbox-env/pinbox.zip").read_bytes(), a)
            self.assertEqual((f / "solution/pinbox.zip").read_bytes(), a)
        names = set(zipfile.ZipFile(f / "solution/pinbox.zip").namelist())
        for need in ["pinbox/mcp_server.py", "pinbox/mcp_client.py", "pinbox/grader.py", "pinbox/data/payloads.json"]:
            self.assertIn(need, names)
        self.assertFalse(any("__pycache__" in n for n in names))

    def test_instruction_is_the_episode_instruction_plus_tool_notes(self):
        from pinbox.episode import Episode, parse_spec
        for spec in self.specs:
            fam, seed, diff = parse_spec(spec)
            f = self.out / f"{fam}-s{seed}-d{diff}"
            text = (f / "instruction.md").read_text(encoding="utf-8")
            self.assertTrue(text.startswith(Episode.create(fam, seed, diff).instruction().rstrip("\n")))
            self.assertIn("http://pinbox-env:8000/mcp", text)

    def test_secrets_only_in_shared_mode(self):
        for f in self.folders:
            self.assertFalse((f / "tests" / "admin_token").exists())
            self.assertNotIn("PINBOX_ADMIN_TOKEN", (f / "environment/docker-compose.yaml").read_text(encoding="utf-8"))
        shared = next(p for p in self.shared_out.iterdir() if p.is_dir())
        token = (shared / "tests" / "admin_token").read_text(encoding="utf-8").strip()
        self.assertEqual(len(token), 64)
        self.assertIn(token, (shared / "environment/docker-compose.yaml").read_text(encoding="utf-8"))
        self.assertFalse((shared / "tests" / "Dockerfile").exists())
        self.assertFalse((shared / "artifacts").exists())
        self.assertNotIn(token, (shared / "instruction.md").read_text(encoding="utf-8"))
        self.assertNotIn(token, (shared / "task.toml").read_text(encoding="utf-8"))

    def test_rebuild_in_place_removes_stray_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            spec = self.specs[0]
            build_tasks.main(["--out", tmp, "--episodes", spec, "--verifier", "shared"])
            folder = next(p for p in Path(tmp).iterdir() if p.is_dir())
            (folder / "solution" / "junk.txt").write_text("x", encoding="utf-8")
            build_tasks.main(["--out", tmp, "--episodes", spec])
            self.assertFalse((folder / "tests" / "admin_token").exists())
            self.assertFalse((folder / "solution" / "junk.txt").exists())
            self.assertTrue((folder / "tests" / "Dockerfile").exists())
            self.assertNotIn("PINBOX_ADMIN_TOKEN",
                             (folder / "environment/docker-compose.yaml").read_text(encoding="utf-8"))

    def test_verify_validation(self):
        verify = _load_module(self.folders[0] / "tests" / "verify.py", "pinbox_harbor_verify")
        expected = json.loads((self.folders[0] / "tests" / "expected.json").read_text(encoding="utf-8"))
        good = {k: expected[k] for k in ("episode_id", "family", "seed", "difficulty")}
        good.update({"reward": 1, "checks": [{"name": "a", "passed": True}]})
        self.assertEqual(verify.validate(good, expected), [])
        self.assertTrue(verify.validate(dict(good, episode_id="other-s1-d1"), expected))
        self.assertTrue(verify.validate(dict(good, checks=[{"name": "a", "passed": False}]), expected))
        self.assertTrue(verify.validate(dict(good, reward=True), expected))
        self.assertTrue(verify.validate(dict(good, reward=2), expected))
        self.assertTrue(verify.validate(dict(good, checks=[]), expected))
        self.assertTrue(verify.validate([good], expected))

    def test_stale_generated_folders_are_removed_but_others_kept(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            (out / "not-ours").mkdir()
            (out / "not-ours" / "task.toml").write_text("[task]\n", encoding="utf-8")
            from pinbox.eval import eval_set
            fam = eval_set()[0]["family"]
            build_tasks.main(["--out", str(out), "--families", fam])
            n = len([p for p in out.iterdir() if p.is_dir()])
            (out / f"{fam}-s999999-d1").mkdir()
            (out / f"{fam}-s999999-d1" / "task.toml").write_text(build_tasks.MARKER + "\n", encoding="utf-8")
            build_tasks.main(["--out", str(out), "--families", fam])
            self.assertFalse((out / f"{fam}-s999999-d1").exists())
            self.assertTrue((out / "not-ours").exists())
            self.assertEqual(len([p for p in out.iterdir() if p.is_dir()]), n)


if __name__ == "__main__":
    unittest.main()
