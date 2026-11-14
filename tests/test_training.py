"""Tests for training/ (stdlib unittest; run: python -m unittest discover -s tests).

No GPU and no ML libraries needed: the LoRA script is only compiled and dry-run, and the
small-model eval runs with fake models.
"""
import contextlib
import io
import json
import os
import py_compile
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pinbox.client import EpisodeClient  # noqa: E402
from pinbox.episode import Episode  # noqa: E402
from pinbox.grader import grade  # noqa: E402
from pinbox.tasks import all_tasks, get_task  # noqa: E402
from training import common, eval_small_model, export_sft, train_lora  # noqa: E402


def quiet(fn, *a, **kw):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        res = fn(*a, **kw)
    return res, buf.getvalue()


def run_script(*args):
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    return subprocess.run([sys.executable, *map(str, args)], cwd=str(ROOT), capture_output=True, text=True,
                          encoding="utf-8", env=env, timeout=300)


class ExportTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.built = export_sft.build(n_per_family=2, log=None)
        cls.rows = cls.built["rows"]

    def test_two_train_seeds_per_family(self):
        fams = [t.family for t in all_tasks()]
        self.assertIn("ap_run", fams)
        for fam in fams:
            got = [r for r in self.rows if r["family"] == fam]
            skipped = [s for s in self.built["skipped"] if s.get("episode_id", "").startswith(fam + "-s")]
            self.assertEqual(len(got) + len(skipped), 2, fam)
        self.assertEqual(len([r for r in self.rows if r["family"] == "ap_run"]), 2)

    def test_no_eval_seeds_and_only_train_seeds(self):
        banned = export_sft.eval_seeds()
        for r in self.rows:
            task = get_task(r["family"])
            self.assertIn(r["seed"], task.train_seeds())
            self.assertNotIn(r["seed"], banned[r["family"]])
        export_sft.assert_no_eval_leak(self.rows)   # must not raise

    def test_rows_are_valid_chat_rows(self):
        for r in self.rows:
            self.assertEqual(common.validate_row(r), [], r["id"])
            self.assertEqual(r["reward"], 1)
            msgs = r["messages"]
            self.assertEqual(msgs[0]["role"], "system")
            self.assertIn("policy", msgs[0]["content"].lower())
            names = {t["function"]["name"] for t in r["tools"]}
            for m in msgs:
                for tc in m.get("tool_calls") or []:
                    self.assertIn(tc["function"]["name"], names)
                    self.assertIsInstance(json.loads(tc["function"]["arguments"]), dict)
            for t in r["tools"]:
                self.assertEqual(t["type"], "function")
                self.assertEqual(t["function"]["parameters"]["type"], "object")

    def test_rows_replay_to_reward_1(self):
        """The tool calls in each row, sent again to a fresh world, give the same results and reward 1."""
        for r in self.rows:
            ep = Episode.create(r["family"], r["seed"], r["difficulty"])
            pending = {}
            for m in r["messages"]:
                for tc in m.get("tool_calls") or []:
                    pending[tc["id"]] = (tc["function"]["name"], json.loads(tc["function"]["arguments"]))
                if m["role"] == "tool":
                    name, args = pending.pop(m["tool_call_id"])
                    out = EpisodeClient(ep).call_args(name, args)
                    self.assertEqual(common.tool_content(out), m["content"])
            self.assertEqual(grade(ep).reward, 1, r["id"])

    def test_written_file_parses(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = export_sft.write_jsonl(self.rows, Path(tmp) / "sft.jsonl")
            with open(out, encoding="utf-8") as f:
                back = [json.loads(line) for line in f if line.strip()]
            self.assertEqual(len(back), len(self.rows))
            self.assertEqual(back[0]["messages"], self.rows[0]["messages"])
            out2 = export_sft.write_jsonl(self.rows, Path(tmp) / "oa.jsonl", openai_only=True)
            with open(out2, encoding="utf-8") as f:
                self.assertEqual(set(json.loads(f.readline())), {"messages", "tools"})

    def test_leak_guard_raises(self):
        task = get_task("ap_run")
        seed, diff = task.eval_specs()[0]
        bad = dict(self.rows[0], seed=seed, difficulty=diff, id="leak")
        with self.assertRaises(export_sft.EvalSeedLeak):
            export_sft.assert_no_eval_leak([bad])
        with self.assertRaises(AssertionError):     # it is an AssertionError, raised even under -O
            export_sft.assert_no_eval_leak([bad])

    def test_train_pairs_skip_eval_seeds(self):
        class Dummy:
            difficulties = (1, 2)

            def train_seeds(self):
                return range(0, 5)

            def eval_specs(self):
                return [(1, 1), (2, 2)]
        pairs = export_sft.train_pairs(Dummy(), 6)
        self.assertEqual(len(pairs), 6)
        self.assertEqual(len(set(pairs)), 6)
        self.assertFalse({s for s, _ in pairs} & {1, 2})
        self.assertEqual(len(export_sft.train_pairs(Dummy(), 100)), 6)   # capped at seeds x difficulties

    def test_recorded_runs_filtered(self):
        task = get_task("ap_run")
        train_seed = list(task.train_seeds())[5]
        eval_seed, eval_diff = task.eval_specs()[0]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "recorded"

            def save(seed, diff, agent, act):
                ep = Episode.create("ap_run", seed, diff, info={"agent": agent, "kind": "llm"})
                act(EpisodeClient(ep))
                ep.save(root / agent / ep.episode_id)

            save(train_seed, 2, "fake-llm", task.reference)                 # good: kept
            save(eval_seed, eval_diff, "fake-llm", task.reference)          # eval seed: skipped
            save(train_seed, 1, "fake-llm", lambda c: c.call("list_invoices"))   # reward 0: skipped
            rows, skipped = export_sft.recorded_rows(root, log=None)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["source"], "recorded:fake-llm")
            self.assertEqual((rows[0]["seed"], rows[0]["difficulty"]), (train_seed, 2))
            whys = " | ".join(s["why"] for s in skipped)
            self.assertIn("eval seed", whys)
            self.assertIn("reward 0", whys)
            built = export_sft.build(families=["ap_run"], n_per_family=1, recorded=[root], log=None)
            self.assertEqual(len(built["rows"]), 2)

    def test_cli_script_mode(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "d" / "sft.jsonl"
            p = run_script(ROOT / "training" / "export_sft.py", "--families", "ap_run", "--n-per-family", "2",
                           "--out", out)
            self.assertEqual(p.returncode, 0, p.stderr)
            self.assertIn("no eval seeds", p.stdout)
            with open(out, encoding="utf-8") as f:
                self.assertEqual(sum(1 for line in f if line.strip()), 2)
            meta = json.loads(out.with_suffix(".meta.json").read_text(encoding="utf-8"))
            self.assertEqual(meta["eval_seed_check"], "passed")


class ParserTest(unittest.TestCase):
    def test_formats(self):
        P = common.parse_tool_calls
        self.assertEqual(P('<tool_call>\n{"name": "list_invoices", "arguments": {"status": "open"}}\n</tool_call>'),
                         [("list_invoices", {"status": "open"})])
        self.assertEqual(P('<tool_call>{"name": "get_task", "arguments": {}}'), [("get_task", {})])   # unclosed
        self.assertEqual(P('Next.\n```json\n{"tool": "read_email", "args": {"email_id": "E3"}}\n```'),
                         [("read_email", {"email_id": "E3"})])
        self.assertEqual(P('{"name": "pay_invoice", "arguments": "{\\"invoice_id\\": \\"INV-101\\"}"}'),
                         [("pay_invoice", {"invoice_id": "INV-101"})])
        self.assertEqual(P('{"function": {"name": "list_vendors", "arguments": "{}"}}'), [("list_vendors", {})])
        self.assertEqual(P('<tool_call>{"name": "flag_invoice", "arguments": {"invoice_id": "INV-1", '
                           '"reason": "duplicate",},}</tool_call>'),
                         [("flag_invoice", {"invoice_id": "INV-1", "reason": "duplicate"})])
        self.assertEqual(P("<tool_call>{'name': 'x'}</tool_call>"), [])
        self.assertEqual(P('<think>maybe {"name": "pay_invoice"}</think>All done, nothing left.'), [])
        two = P('<tool_call>{"name": "a", "arguments": {}}</tool_call>\n<tool_call>{"name": "b"}</tool_call>')
        self.assertEqual(two, [("a", {}), ("b", {})])
        self.assertEqual(P("Done. Paid INV-101 and flagged INV-102."), [])

    def test_model_short_name(self):
        m = common.model_short_name
        self.assertEqual(m("Qwen/Qwen3-4B-Instruct-2507"), "Qwen3-4B-Instruct-2507")
        self.assertEqual(m("C:\\Users\\a b\\tiny\\model\\"), "model")
        self.assertEqual(m("/scratch/models/qwen/"), "qwen")

    def test_looks_like_call_and_prose(self):
        self.assertTrue(common.looks_like_call('<tool_call>{"name": broken'))
        self.assertFalse(common.looks_like_call("All finished."))
        self.assertEqual(common.prose_before_calls('Checking.\n<tool_call>{"name":"a"}</tool_call>'), "Checking.")


class CharTokenizer:
    """One token per character; enough to test the label mask without transformers."""

    def __init__(self, fast=True, chat_template=None):
        self.is_fast = fast
        self.chat_template = chat_template

    def __call__(self, text, add_special_tokens=False, return_offsets_mapping=False):
        out = {"input_ids": [ord(c) for c in text]}
        if return_offsets_mapping:
            out["offset_mapping"] = [(i, i + 1) for i in range(len(text))]
        return out


class QwenLikeTokenizer(CharTokenizer):
    """Fake 'native' template in the Qwen style (with an empty think block in the generation prompt)."""

    def __init__(self):
        super().__init__(True, "{% if tools %}...tool_call...{% endif %}")

    def apply_chat_template(self, messages, tools=None, tokenize=False, add_generation_prompt=False, **kw):
        out = "<|im_start|>system\n" + messages[0]["content"] + "\n# Tools\n" + json.dumps(tools) + "<|im_end|>\n"
        for m in messages[1:]:
            if m["role"] == "assistant":
                body = m["content"]
                for tc in m.get("tool_calls", []):
                    assert isinstance(tc["function"]["arguments"], dict)
                    body += "<tool_call>" + json.dumps(tc["function"]) + "</tool_call>"
                out += "<|im_start|>assistant\n" + body + "<|im_end|>\n"
            elif m["role"] == "tool":
                out += "<|im_start|>user\n<tool_response>" + m["content"] + "</tool_response><|im_end|>\n"
            else:
                out += f"<|im_start|>{m['role']}\n{m['content']}<|im_end|>\n"
        if add_generation_prompt:
            out += "<|im_start|>assistant\n" + ("<think>\n\n</think>\n\n" if kw.get("enable_thinking") is False else "")
        return out


class RenderTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.row = export_sft.build(families=["ap_run"], n_per_family=1, log=None)["rows"][0]

    def test_plain_spans_and_labels(self):
        msgs, tools = self.row["messages"], self.row["tools"]
        n_asst = sum(1 for m in msgs if m["role"] == "assistant")
        full, spans = common.assistant_char_spans(None, msgs, tools)
        self.assertEqual(len(spans), n_asst)
        for a, b in spans[:-1]:
            self.assertTrue(full[a:b].startswith("<tool_call>"))
        self.assertTrue(full[spans[-1][0]:spans[-1][1]].startswith("Done."))
        self.assertIn("# Tools", full)
        self.assertIn("[tool result]", full)
        for fast in (True, False):
            ex = train_lora.tokenize_example(CharTokenizer(fast), self.row, "plain", 10 ** 7, False)
            self.assertEqual("".join(chr(i) for i in ex["input_ids"]), full)
            trained = "".join(chr(t) for t in ex["labels"] if t != -100)
            self.assertEqual(trained, "".join(full[a:b] for a, b in spans))
        self.assertIsNone(train_lora.tokenize_example(CharTokenizer(), self.row, "plain", 100, False))
        cut = train_lora.tokenize_example(CharTokenizer(), self.row, "plain", 100, True)
        self.assertIsNone(cut)   # first 100 chars are all system prompt: nothing to learn, dropped

    def test_native_template_path(self):
        tok = QwenLikeTokenizer()
        self.assertEqual(common.choose_protocol(tok), "native")
        self.assertEqual(common.choose_protocol(CharTokenizer()), "plain")
        full, spans = common.assistant_char_spans(tok, self.row["messages"], self.row["tools"])
        self.assertIsNotNone(spans)
        self.assertEqual(len(spans), sum(1 for m in self.row["messages"] if m["role"] == "assistant"))
        self.assertIn("<tool_call>", full[spans[0][0]:spans[0][1]])
        self.assertTrue(full[spans[-1][0]:spans[-1][1]].rstrip().endswith("<|im_end|>"))
        ex = train_lora.tokenize_example(tok, self.row, "native", 10 ** 7, False)
        self.assertTrue(any(t != -100 for t in ex["labels"]))


class EvalSmallModelTest(unittest.TestCase):
    def test_dry_run_before_after(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "res.json"
            runs_dir = Path(tmp) / "runs"
            rc, text = quiet(eval_small_model.main, ["--dry-run", "--limit", "2", "--families", "ap_run",
                                                     "--out", str(out), "--save-runs", str(runs_dir), "--quiet"])
            self.assertEqual(rc, 0)
            self.assertIn("after - before", text)
            res = json.loads(out.read_text(encoding="utf-8"))
            self.assertTrue(res["dry_run"])
            by_variant = {v["variant"]: res["summary"][k] for k, v in res["agents"].items()}
            self.assertEqual(by_variant["after"]["mean_reward"], 1.0)
            self.assertEqual(by_variant["before"]["mean_reward"], 0.0)
            self.assertEqual(by_variant["ref"]["mean_reward"], 1.0)
            for e in res["eval_set"]:   # the small-model eval runs on the frozen eval set
                self.assertIn((e["seed"], e["difficulty"]), get_task(e["family"]).eval_specs())
            from pinbox.eval import run_recorded
            rec = run_recorded(runs_dir, quiet=True)
            self.assertEqual({len(v["runs"]) for v in rec.values()}, {2})
            for agent, entry in rec.items():
                want = 1 if "after" in agent else 0
                for r in entry["runs"]:
                    self.assertEqual(r["reward"], want, agent)
                    self.assertTrue(r["replay_consistent"])

    def test_agent_loop_nudges_and_stops(self):
        class Garbled:
            def __init__(self):
                self.n = 0

            def generate(self, messages, tools):
                self.n += 1
                return '<tool_call>{"name": "list_invoices", "arguments": {"status": "open"' if self.n == 1 \
                    else ('<tool_call>{"name": "get_task", "arguments": {}}</tool_call>' if self.n == 2 else "Done.")
        ep = Episode.create("ap_run", 1001, 1)
        info = eval_small_model.run_text_agent(EpisodeClient(ep), Garbled())
        self.assertEqual(info["stop_reason"], "model_done")
        self.assertEqual(info["tool_calls"], 2)       # the unclosed call is still read, then get_task
        self.assertEqual(len(ep.trajectory), 2)

        class Babbler:
            def generate(self, messages, tools):
                return '{"name": oops'
        ep2 = Episode.create("ap_run", 1001, 1)
        info2 = eval_small_model.run_text_agent(EpisodeClient(ep2), Babbler())
        self.assertEqual(info2["parse_errors"], 3)    # 2 nudges, then it counts as finished
        self.assertEqual(info2["stop_reason"], "model_done")
        self.assertEqual(grade(ep2).reward, 0)

    def test_pick_specs_limit(self):
        specs = eval_small_model.pick_specs(["ap_run"], limit=3)
        self.assertEqual(len(specs), 3)
        self.assertEqual(sorted({d for _, _, d in specs}), [1, 2, 3])   # spread over difficulties


class TrainLoraTest(unittest.TestCase):
    def test_compiles(self):
        for p in sorted((ROOT / "training").glob("*.py")):
            py_compile.compile(str(p), doraise=True)

    def test_dry_run_script(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp) / "sft.jsonl"
            rows = export_sft.build(families=["ap_run"], n_per_family=2, log=None)["rows"]
            export_sft.write_jsonl(rows, data)
            p = run_script(ROOT / "training" / "train_lora.py", "--dry-run", "--data", data)
            self.assertEqual(p.returncode, 0, p.stderr)
            self.assertIn("dry run", p.stdout)
            cfg = json.loads(p.stdout[: p.stdout.rindex("}") + 1])
            self.assertTrue(cfg["config"]["fp16"])
            self.assertFalse(cfg["config"]["bf16"])
            self.assertEqual(cfg["config"]["attn"], "sdpa")
            self.assertEqual(cfg["data"]["rows"], 2)
            self.assertEqual(cfg["data"]["invalid_rows"], 0)

    def test_compat_kwargs_old_and_new_names(self):
        args = train_lora.parse_args(["--warmup-ratio", "0.1"])
        kw = train_lora.trainer_kwargs(args)
        new = set(kw) | {"dataset_kwargs", "packing", "max_length"}           # transformers 5 / TRL 1
        out = train_lora.compat_kwargs(kw, new, trl=True, max_len=4096)
        self.assertEqual(out["warmup_steps"], 0.1)
        self.assertEqual(out["eval_strategy"], "epoch")
        self.assertEqual(out["max_length"], 4096)
        self.assertEqual(out["dataset_kwargs"], {"skip_prepare_dataset": True})
        old = (set(kw) - {"warmup_steps", "eval_strategy"}) | {"warmup_ratio", "evaluation_strategy",
                                                               "max_seq_length", "dataset_kwargs", "packing"}
        out = quiet(train_lora.compat_kwargs, kw, old, True, 4096)[0]
        self.assertEqual(out["warmup_ratio"], 0.1)
        self.assertEqual(out["evaluation_strategy"], "epoch")
        self.assertEqual(out["max_seq_length"], 4096)
        self.assertNotIn("warmup_steps", out)
        self.assertTrue(out["fp16"])
        self.assertFalse(out["bf16"])

    def test_dry_run_no_ml_imports(self):
        rc, text = quiet(train_lora.main, ["--dry-run", "--data", str(Path(tempfile.gettempdir()) / "nope.jsonl")])
        self.assertEqual(rc, 0)
        self.assertIn("missing", text)
        for mod in ("torch", "transformers", "peft", "trl"):
            self.assertNotIn(mod, sys.modules)


if __name__ == "__main__":
    unittest.main()
