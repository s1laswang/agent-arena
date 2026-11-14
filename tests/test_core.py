"""Core tests: dispatcher safety, budget, determinism, events, secrecy, save/load, CLI."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pinbox.client import EpisodeClient  # noqa: E402
from pinbox.episode import Episode, parse_spec  # noqa: E402
from pinbox.rng import (MoneyError, find_ibans, fmt_cents, format_iban, iban_checksum_ok, make_fi_iban,  # noqa: E402
                        make_rng, normalize_phone, to_cents)
from pinbox.state import canonical_json  # noqa: E402
from pinbox.tasks import all_tasks, get_task  # noqa: E402
from pinbox.tools import dispatch, tool_specs  # noqa: E402

WEIRD_VALUES = [
    None, True, False, 0, -1, -0.0, 1e308, -1e308, float("nan"), float("inf"), float("-inf"),
    10 ** 40, "", " ", "x" * 100000, "../../etc/passwd", "C:\\Windows\\system32\\config", "INV-101' OR '1'='1",
    "\u202eevil\u200b\u0000", "Järvisen €", [], [None], ["a"] * 500, {}, {"$ne": 1}, {"a": {"b": {"c": []}}},
]


def _all_families():
    return [t.family for t in all_tasks()]


class DispatcherSafety(unittest.TestCase):
    def setUp(self):
        self.ep = Episode.create("ap_run", 3, 2)

    def assertShape(self, out):
        self.assertIsInstance(out, dict)
        self.assertEqual(set(out), {"ok", "result", "error"})
        json.dumps(out)  # always JSON-able

    def test_never_raises_on_weird_input(self):
        names = [None, 123, "", "x" * 5000, "no_such_tool", "../etc/passwd", "__class__", "hidden", "\u0000",
                 ["pay_invoice"], {"t": 1}]
        for name in names:
            for args in (None, [], "str", 5, {"a": 1}, {1: 2}, {None: None}):
                out = dispatch(self.ep.state, name, args, self.ep.trajectory)
                self.assertShape(out)
                self.assertFalse(out["ok"])

    def test_every_tool_survives_garbage(self):
        for fam in _all_families():
            ep = Episode.create(fam, 5, 3)
            ep.state["meta"]["budget"] = 100000
            for spec in tool_specs(fam):
                params = list(spec["parameters"]["properties"])
                for w in WEIRD_VALUES:
                    out = ep.call(spec["name"], {p: w for p in params})
                    self.assertShape(out)
                    for p in params:
                        out = ep.call(spec["name"], {p: w})
                        self.assertShape(out)
                out = ep.call(spec["name"], {"definitely_not_a_param": 1})
                self.assertFalse(out["ok"])
                self.assertIn("unknown argument", out["error"])

    def test_unknown_tool_and_args(self):
        out = self.ep.call("drop_tables", {})
        self.assertFalse(out["ok"])
        self.assertIn("unknown tool", out["error"])
        out = self.ep.call("list_invoices", {"status": "open", "extra": 1})
        self.assertFalse(out["ok"])
        self.assertIn("unknown argument", out["error"])
        out = self.ep.call("read_email", {})
        self.assertFalse(out["ok"])
        self.assertIn("missing required", out["error"])
        out = self.ep.call("read_email", {"email_id": 5})
        self.assertFalse(out["ok"])
        self.assertIn("must be a string", out["error"])
        out = self.ep.call("list_invoices", {"status": "everything"})
        self.assertFalse(out["ok"])
        self.assertIn("must be one of", out["error"])

    def test_bad_amounts_change_nothing(self):
        inv = self.ep.state["ap_run"]["invoices"][0]
        before = canonical_json(self.ep.state["ap_run"])
        for amount in (float("nan"), float("inf"), -1, 0, -0.0, 0.001, 12.345, 1e308, True, "100", None, [1]):
            out = self.ep.call("pay_invoice", {"invoice_id": inv["invoice_id"], "amount": amount,
                                               "iban": inv["remit_iban"]})
            self.assertFalse(out["ok"], amount)
        self.assertEqual(before, canonical_json(self.ep.state["ap_run"]))

    def test_path_like_and_unicode_ids(self):
        for bad in ("../../state.json", "C:\\x", "INV-101/..", "ïnv-101", "INV-101\u200b", "*"):
            for tool, key in (("read_email", "email_id"), ("read_document", "doc_id")):
                out = self.ep.call(tool, {key: bad})
                self.assertFalse(out["ok"])

    def test_budget_exhaustion(self):
        ep = Episode.create("ap_run", 1, 1)
        budget = ep.state["meta"]["budget"]
        for _ in range(budget):
            self.assertTrue(ep.call("list_vendors", {})["ok"])
        snapshot = canonical_json({k: v for k, v in ep.state.items()})
        for tool, args in (("list_vendors", {}), ("pay_invoice", {"invoice_id": "INV-101", "amount": 1, "iban": "x"}),
                           ("nope", {})):
            out = ep.call(tool, args)
            self.assertFalse(out["ok"])
            self.assertEqual(out["error"], "tool budget exhausted")
        self.assertEqual(snapshot, canonical_json(ep.state))
        self.assertEqual(ep.state["calls"], budget)

    def test_errors_count_as_calls(self):
        ep = Episode.create("ap_run", 1, 1)
        ep.call("nope", {})
        ep.call("read_email", {})
        self.assertEqual(ep.state["calls"], 2)
        self.assertEqual(len(ep.trajectory), 2)

    def test_results_are_detached_copies(self):
        client = EpisodeClient(self.ep)
        out = client.call("list_invoices", status="open")
        out["result"]["invoices"][0]["status"] = "paid"
        out["result"]["invoices"][0]["amount"] = "0.01"
        self.assertEqual(self.ep.state["ap_run"]["invoices"][0]["status"], "open")


class Secrecy(unittest.TestCase):
    def test_hidden_never_in_tool_results(self):
        from pinbox.agents.baselines import known_agents, make_agent, run_agent
        from pinbox.eval import _fuzz_agent
        canary = "CANARY-7f3a9c-SECRET"
        for fam in _all_families():
            for seed, diff in ((2, 1), (7, 2), (11, 3)):
                agents = [make_agent(n, Episode.create(fam, seed, diff)) for n in known_agents()] + [_fuzz_agent]
                for agent in agents:
                    if agent is None:
                        continue
                    ep = Episode.create(fam, seed, diff)
                    ep.state["hidden"]["canary"] = canary
                    ep.state["hidden"]["truth_canary"] = {"x": canary}
                    run_agent(agent, ep)
                    for name in ("get_task", "list_emails", "list_documents"):
                        ep.call(name, {})
                    outputs = [{"result": r.get("result"), "error": r.get("error")} for r in ep.trajectory]
                    text = json.dumps(outputs, ensure_ascii=False)
                    self.assertNotIn(canary, text)
                    self.assertNotIn('"hidden"', text)
                    self.assertNotIn('"truth"', text)
                    self.assertNotIn('"pending"', text)

    def test_instruction_has_no_seed_or_truth(self):
        for fam in _all_families():
            ep = Episode.create(fam, 98765, 3)
            for text in (ep.instruction(), json.dumps(ep.call("get_task", {}))):
                self.assertNotIn("98765", text)
                self.assertNotIn("truth", text.lower().replace("truthful", ""))


class Determinism(unittest.TestCase):
    def test_same_seed_same_world(self):
        for fam in _all_families():
            for seed, diff in ((0, 1), (9, 2), (42, 3)):
                a = get_task(fam).generate(seed, diff)
                b = get_task(fam).generate(seed, diff)
                self.assertEqual(canonical_json(a), canonical_json(b))

    def test_different_seeds_differ(self):
        a = get_task("ap_run").generate(1, 2)
        b = get_task("ap_run").generate(2, 2)
        self.assertNotEqual(canonical_json(a), canonical_json(b))

    def test_same_calls_same_results(self):
        for fam in _all_families():
            runs = []
            for _ in range(2):
                ep = Episode.create(fam, 17, 3)
                get_task(fam).reference(EpisodeClient(ep))
                runs.append((canonical_json(ep.trajectory), canonical_json(ep.state)))
            self.assertEqual(runs[0], runs[1])

    def test_independent_of_hash_seed(self):
        """Set iteration order must never leak into the world (PYTHONHASHSEED differs per process)."""
        code = ("import sys,hashlib; sys.path.insert(0, sys.argv[1]);"
                "from pinbox.tasks import all_tasks; from pinbox.state import canonical_json;"
                "print(hashlib.sha256(''.join(canonical_json(t.generate(s, d)) for t in all_tasks()"
                " for s in (1, 5, 33) for d in (1, 2, 3)).encode()).hexdigest())")
        outs = set()
        for hs in ("1", "2", "999"):
            env = dict(os.environ, PYTHONHASHSEED=hs)
            res = subprocess.run([sys.executable, "-c", code, str(ROOT)], capture_output=True, text=True, env=env,
                                 timeout=120)
            self.assertEqual(res.returncode, 0, res.stderr)
            outs.add(res.stdout.strip())
        self.assertEqual(len(outs), 1)


class Events(unittest.TestCase):
    def _late_world(self):
        for s in range(100):
            ep = Episode.create("ap_run", s, 3)
            if ep.state["events"]["pending"]:
                return ep
        self.fail("no world with a late arrival")

    def test_event_fires_once_after_first_successful_payment(self):
        ep = self._late_world()
        n0 = len(ep.state["ap_run"]["invoices"])
        # a failed payment does not fire it
        ep.call("pay_invoice", {"invoice_id": "INV-999", "amount": 1, "iban": "FI00"})
        self.assertEqual(len(ep.state["events"]["fired"]), 0)
        self.assertEqual(len(ep.state["ap_run"]["invoices"]), n0)
        get_task("ap_run").reference(EpisodeClient(ep))
        self.assertEqual(len(ep.state["events"]["fired"]), 1)
        self.assertEqual(ep.state["events"]["pending"], [])
        added = len(ep.state["events"]["fired"][0]["effects"])
        n_inv = sum(1 for e in ep.state["events"]["fired"][0]["effects"] if e["path"] == "ap_run.invoices")
        self.assertGreater(added, 0)
        self.assertEqual(len(ep.state["ap_run"]["invoices"]), n0 + n_inv)
        ids = [i["invoice_id"] for i in ep.state["ap_run"]["invoices"]]
        self.assertEqual(len(ids), len(set(ids)))
        for e in ep.state["emails"]:
            self.assertNotEqual(e["received_at"], "@now")


class SpecsAndClient(unittest.TestCase):
    def test_tool_specs_well_formed(self):
        for fam in _all_families():
            specs = tool_specs(fam)
            names = [s["name"] for s in specs]
            self.assertEqual(len(names), len(set(names)), fam)
            for s in specs:
                self.assertTrue(s["description"])
                params = s["parameters"]
                self.assertEqual(params["type"], "object")
                self.assertTrue(set(params["required"]) <= set(params["properties"]))
                json.dumps(s)
            for shared in ("get_task", "list_emails", "read_email", "send_email", "list_documents", "read_document",
                           "search_contacts", "call_phone"):
                self.assertIn(shared, names)

    def test_client_interface(self):
        ep = Episode.create("ap_run", 4, 1)
        c = EpisodeClient(ep)
        self.assertIn("AP policy", c.instruction())
        self.assertTrue(c.tools())
        out = c.call("get_task")
        self.assertTrue(out["ok"])
        self.assertIn("instruction", out["result"])
        self.assertEqual(c.call_args("list_vendors", {})["ok"], True)

    def test_parse_spec(self):
        self.assertEqual(parse_spec("ap_run:7:2"), ("ap_run", 7, 2))
        self.assertEqual(parse_spec("ap_run-s7-d2"), ("ap_run", 7, 2))
        self.assertIsNone(parse_spec("../etc"))


class Helpers(unittest.TestCase):
    def test_money(self):
        self.assertEqual(to_cents(1234.5), 123450)
        self.assertEqual(to_cents("1234.50"), 123450)
        self.assertEqual(to_cents(0.29), 29)
        self.assertEqual(to_cents(19.99), 1999)
        self.assertEqual(fmt_cents(5), "0.05")
        for bad in (float("nan"), float("inf"), True, None, "abc", 1.005, "1e999"):
            with self.assertRaises(MoneyError):
                to_cents(bad)
        for c in range(0, 100000, 7):
            self.assertEqual(to_cents(c / 100), c)

    def test_iban(self):
        rng = make_rng("t", 1)
        for _ in range(200):
            ib = make_fi_iban(rng)
            self.assertTrue(ib.startswith("FI") and len(ib) == 18 and ib[2:].isdigit())
            self.assertTrue(iban_checksum_ok(ib))
            self.assertTrue(iban_checksum_ok(format_iban(ib)))
            self.assertEqual(find_ibans(f"pay to {format_iban(ib)} today"), [ib])
        self.assertTrue(iban_checksum_ok("FI2112345600000785"))
        self.assertFalse(iban_checksum_ok("FI2112345600000786"))

    def test_phone(self):
        self.assertEqual(normalize_phone("+358 40 123 4567"), "358401234567")
        self.assertEqual(normalize_phone("040-1234567"), "358401234567")
        self.assertEqual(normalize_phone("00358401234567"), "358401234567")


class SaveLoadAndCli(unittest.TestCase):
    def test_roundtrip_in_awkward_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp) / "runs with spaces" / "ö-ä Ünïcode"
            ep = Episode.create("ap_run", 8, 2, path=folder)
            get_task("ap_run").reference(EpisodeClient(ep))
            ep.save()
            back = Episode.load(folder)
            self.assertEqual(canonical_json(back.state), canonical_json(ep.state))
            self.assertEqual(back.trajectory, ep.trajectory)
            self.assertEqual(back.grade().reward, 1)

    def test_cli_end_to_end(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = dict(os.environ, PYTHONPATH=str(ROOT))
            runs = str(Path(tmp) / "rüns dir")

            def run(*args):
                res = subprocess.run([sys.executable, "-m", "pinbox", *args], capture_output=True, text=True,
                                     encoding="utf-8", env=env, cwd=tmp, timeout=120)
                return res

            res = run("new", "ap_run", "--seed", "4", "--difficulty", "2", "--runs-dir", runs)
            self.assertEqual(res.returncode, 0, res.stderr)
            folder = res.stdout.strip()
            res = run("call", folder, "list_invoices", "status=open")
            self.assertEqual(res.returncode, 0, res.stderr)
            self.assertTrue(json.loads(res.stdout)["ok"])
            res = run("call", folder, "flag_invoice", "--json", '{"invoice_id": "INV-101", "reason": "duplicate"}')
            self.assertIn('"ok"', res.stdout)
            res = run("grade", folder, "--json")
            self.assertEqual(res.returncode, 0, res.stderr)
            self.assertEqual(json.loads(res.stdout)["reward"], 0)
            res = run("run", "reference", "ap_run:5:3", "--runs-dir", runs)
            self.assertEqual(res.returncode, 0, res.stderr)
            self.assertIn("reward 1", res.stdout)
            traj = Path(runs) / "ap_run-s5-d3" / "trajectory.jsonl"
            res = run("replay", str(traj), "--json")
            self.assertEqual(res.returncode, 0, res.stderr)
            data = json.loads(res.stdout)
            self.assertEqual(data["reward"], 1)
            self.assertTrue(data["consistent"])
            res = run("tools", folder)
            self.assertIn("pay_invoice", res.stdout)


if __name__ == "__main__":
    unittest.main()
