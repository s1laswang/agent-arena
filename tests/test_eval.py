"""Integration checks for the eval runner and the player-facing CLI (stdlib only)."""
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pinbox import cli  # noqa: E402
from pinbox.eval import eval_set, run_eval, run_probes  # noqa: E402
from pinbox.tasks import all_tasks  # noqa: E402


class ProbeTests(unittest.TestCase):
    def test_every_exploit_probe_is_blocked(self):
        rows = run_probes(eval_set(), quiet=True)
        self.assertGreaterEqual(len(rows), 19)
        for row in rows:
            self.assertGreater(row["episodes"], 0, row["id"])
            if row.get("control"):
                self.assertTrue(row["as_expected"], row)
            else:
                self.assertTrue(row["blocked"], row)

    def test_probes_cover_every_family(self):
        rows = run_probes(eval_set(), quiet=True)
        fams = {s["family"] for s in eval_set()}
        self.assertEqual(fams, {t.family for t in all_tasks()})
        # each family has at least one family-specific attack beyond the generic ones
        ids = {r["id"] for r in rows}
        for pid in ("X10", "X12", "X14", "X17", "X18"):
            self.assertIn(pid, ids)


class EvalTests(unittest.TestCase):
    def _run(self):
        return run_eval(agents=["reference", "do_nothing", "stop_early_50", "stop_before_last_write"],
                        repeats=2, out=None, runs_dir=None, ladder=True, probes=False,
                        save_trajectories=False, quiet=True)

    def test_eval_checks_and_determinism(self):
        a, b = self._run(), self._run()
        for r in (a, b):
            r.pop("seconds")
        self.assertEqual(json.dumps(a, sort_keys=True), json.dumps(b, sort_keys=True))
        self.assertTrue(a["checks"]["reference_all_pass"])
        self.assertTrue(a["checks"]["ladder_non_decreasing"])
        for name, mean in a["checks"]["zero_baselines"].items():
            self.assertEqual(mean, 0.0, name)
        self.assertTrue(all(e["deterministic"] for e in a["agents"].values()))
        self.assertEqual(a["summary"]["reference"]["pass_k"]["2"], 1.0)

    def test_eval_writes_grade_next_to_trajectory(self):
        with tempfile.TemporaryDirectory() as tmp:
            res = run_eval(agents=["do_nothing"], repeats=1, out=None, runs_dir=tmp, families=["refunds"],
                           ladder=False, probes=False, quiet=True)
            run = res["agents"]["do_nothing"]["runs"][0]
            ep = run["episode_id"]
            g = json.loads((Path(tmp) / "do_nothing" / ep / "grade.json").read_text(encoding="utf-8"))
            self.assertEqual(g["reward"], 0)
            self.assertTrue(any(not c["passed"] for c in g["checks"]))


class CliPlayerTests(unittest.TestCase):
    def test_compact_json_is_valid_and_short(self):
        obj = {"ok": True, "result": {"items": [{"id": "A", "n": 1, "tags": ["x"]}, {"id": "B", "n": 2}],
                                      "nested": {"deep": {"x": 1}}}, "error": None}
        text = cli.compact_json(obj)
        self.assertEqual(json.loads(text), obj)
        self.assertIn('{"id": "A", "n": 1, "tags": ["x"]}', text)   # a flat record stays on one line

    def test_bare_value_for_single_required_arg(self):
        from pinbox.tools import get_tool
        self.assertEqual(cli._parse_kv(get_tool("ap_run", "read_email"), ["E3"]), {"email_id": "E3"})
        with self.assertRaises(SystemExit) as cm:
            cli._parse_kv(get_tool("ap_run", "pay_invoice"), ["INV-101"])
        self.assertIn("invoice_id=", str(cm.exception))

    def test_instruction_tells_how_to_call_tools(self):
        with tempfile.TemporaryDirectory() as tmp:
            cwd = os.getcwd()
            os.chdir(tmp)
            try:
                for fam in [t.family for t in all_tasks()]:
                    buf = io.StringIO()
                    with redirect_stdout(buf):
                        cli.main(["instruction", f"{fam}:1:1", "--runs-dir", "runs"])
                    out = buf.getvalue()
                    self.assertIn("python -m pinbox call", out)
                    self.assertIn("policy", out.lower())
                    buf = io.StringIO()
                    with redirect_stdout(buf):
                        cli.main(["instruction", f"{fam}:1:1", "--runs-dir", "runs", "--plain"])
                    self.assertNotIn("python -m pinbox call", buf.getvalue())
            finally:
                os.chdir(cwd)


if __name__ == "__main__":
    unittest.main()
