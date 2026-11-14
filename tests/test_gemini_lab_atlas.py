"""Failure Atlas: keyless tests (fake google-genai client). Packing, quote verification, schemas, the full pipeline
with a fake Gemini, offline replay from the response cache, deterministic fallback, and the agreement sheet."""
from __future__ import annotations

import json
import re
from argparse import Namespace
from pathlib import Path
from types import SimpleNamespace

import pytest

from canary.gemini.atlas_data import (align_rationale, compact_args, load_run, pack_corpus, pack_episode,
                                      _calls_from_jsonl_transcript)
from canary.gemini.atlas_schema import Taxonomy, Verifier, inline_schema, parse, quote_in

ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / "data" / "runs" / "committed" / "codex-gpt-5.5" / "medium"


@pytest.fixture(scope="module")
def eps():
    out = load_run(RUN)
    for i, e in enumerate(out):
        e.id = f"codex.m{e.seed}#{i}"
    return out


@pytest.fixture(autouse=True)
def _ledger(tmp_path, monkeypatch):
    monkeypatch.setenv("CANARY_GEMINI_LEDGER", str(tmp_path / "ledger.jsonl"))


# ------------------------------------------------------------------------------------ packing

def test_pack_has_regret_belief_and_agent_words(eps):
    assert eps and all(e.steps for e in eps)
    assert any(s.rationale for e in eps for s in e.steps), "codex agent messages aligned to steps"
    assert all(e.rationale_source == "agent_messages" for e in eps if any(s.rationale for s in e.steps))
    text, blocks = pack_corpus(eps)
    assert text.count("=== EPISODE") == len(eps) and set(blocks) == {e.id for e in eps}
    assert "REGRET" in text and "top=" in text and "says:" in text
    # regret in the pack is the solver's (canary.solver.regret.attribute), summed by code
    e = max(eps, key=lambda e: e.total_regret)
    assert e.total_regret == pytest.approx(sum(s.regret for s in e.steps) + e.terminal_regret)


def test_compact_args_groups_canary_variants():
    s = compact_args("plant_canary", {"assignment": {"e03": "B", "e01": "A", "e02": "A"}, "doc_title": "x"})
    assert s == "A:e01,e02 | B:e03"


def test_alignment_walks_by_tool_name():
    steps = [{"tool": "status"}, {"tool": "plant_canary"}, {"tool": "advance_day"}]
    calls = [("status", "look"), ("bogus_tool", "oops"), ("plant_canary", "split the six"), ("advance_day", "")]
    assert align_rationale(steps, calls) == ["look", "oops\nsplit the six", ""]


def test_opencode_transcript_parsing():
    lines = ['$ opencode run', json.dumps({"type": "text", "part": {"text": "I will plant a canary."}}),
             json.dumps({"type": "tool_use", "part": {"tool": "canary_plant_canary"}}),
             json.dumps({"type": "text", "part": {"text": "Accused e38."}})]
    calls, src = _calls_from_jsonl_transcript("\n".join(lines))
    assert calls == [("plant_canary", "I will plant a canary.\nAccused e38.")] and src == "agent_messages"


# ------------------------------------------------------------------------------------ verification

def test_quote_in_normalises_but_requires_verbatim():
    hay = "I’ll run this like a Bayesian   investigation: first map employees."
    assert quote_in("I'll run this like a Bayesian investigation", hay)
    assert quote_in("run this like ... map employees", hay)              # ellipsis fragments in order
    assert not quote_in("map employees ... run this like", hay)          # wrong order
    assert not quote_in("I'll run this like a frequentist investigation", hay)
    assert not quote_in("first", hay)                                     # too short to be evidence


def test_verifier_counts_and_drops(eps):
    text, blocks = pack_corpus(eps)
    v = Verifier(eps, blocks)
    e = next(e for e in eps if any(s.rationale for s in e.steps))
    s = next(s for s in e.steps if len(s.rationale) > 40)
    good = " ".join(s.rationale.split()[:8])
    assert v.check(e.id, s.t, good)["step_verified"]
    assert not v.check(e.id, s.t, "the mole is obviously the angry engineer")["verified"]
    assert not v.check("no-such-episode", 3, good)["verified"]
    summ = v.summary()
    assert summ["quotes_checked"] == 3 and summ["quotes_verified"] == 1 and summ["dropped"] == 2
    assert summ["pass_rate"] == pytest.approx(1 / 3, abs=1e-3)


def test_inline_schema_and_parse():
    sch = inline_schema(Taxonomy)
    assert "$defs" not in json.dumps(sch) and "$ref" not in json.dumps(sch)
    ok = {"summary": "s", "modes": [{"id": "a", "name": "A", "description": "d", "decision": "canary_design",
                                     "mechanism": "m", "solver_would": "w", "evidence": []}]}
    assert parse("```json\n" + json.dumps(ok) + "\n```", Taxonomy)[0].modes[0].id == "a"
    bad = dict(ok, modes=[dict(ok["modes"][0], decision="vibes")])
    assert parse(json.dumps(bad), Taxonomy)[0] is None
    assert parse("not json", Taxonomy)[0] is None


# ------------------------------------------------------------------------------------ fake Gemini

class FakeModels:
    def __init__(self, outer):
        self.o = outer

    def count_tokens(self, model, contents):
        return SimpleNamespace(total_tokens=len(str(contents)) // 4)

    def embed_content(self, model, contents, config=None):
        vecs = []
        for i, t in enumerate(contents):
            h = abs(hash(t.split()[0] if t.split() else "")) % 3
            vecs.append(SimpleNamespace(values=[1.0 if j == h else 0.01 * ((i + j) % 5) for j in range(8)]))
        return SimpleNamespace(embeddings=vecs)

    def generate_content(self, model, contents, config):
        self.o.calls += 1
        if self.o.fail:
            raise RuntimeError("PERMISSION_DENIED fake")
        prompt = "\n".join(p.text for c in contents for p in c.parts if getattr(p, "text", None))
        corpus = self.o.cache_text if getattr(config, "cached_content", None) else prompt
        props = (config.response_json_schema or {}).get("properties", {})
        out = self.o.answer(props, prompt, corpus)
        um = SimpleNamespace(prompt_token_count=1000, candidates_token_count=100, thoughts_token_count=10,
                             cached_content_token_count=900 if getattr(config, "cached_content", None) else 0)
        return SimpleNamespace(text=json.dumps(out), usage_metadata=um)


class FakeCaches:
    def __init__(self, outer):
        self.o = outer

    def create(self, model, config):
        self.o.cache_text = config.contents[0].parts[0].text
        return SimpleNamespace(name="cachedContents/fake", usage_metadata=SimpleNamespace(total_token_count=12345))

    def delete(self, name):
        self.o.deleted = name


class FakeGenai:
    """Answers each structured question from the corpus it was given: one verbatim and one invented quote per mode."""

    def __init__(self, eps, fail=False):
        self.eps, self.fail, self.calls, self.cache_text = eps, fail, 0, ""
        self.models, self.caches = FakeModels(self), FakeCaches(self)

    def _line(self, corpus, ep_id, t):
        m = re.search(rf"=== EPISODE {re.escape(ep_id)} .*?(?=\n=== EPISODE|\Z)", corpus, re.S)
        if not m:
            return "missing"
        lm = re.search(rf"^t{t} d\d+ [^\n]{{20,}}", m.group(0), re.M)
        return lm.group(0)[:60] if lm else "missing"

    def answer(self, props, prompt, corpus):
        hr = sorted(((e, s) for e in self.eps for s in e.steps if s.regret > 0), key=lambda es: -es[1].regret)
        if "modes" in props:
            ev = [{"episode": e.id, "t": s.t, "quote": self._line(corpus, e.id, s.t), "why": "w"} for e, s in hr[:3]]
            ev.append({"episode": hr[0][0].id, "t": hr[0][1].t, "quote": "an invented sentence nobody wrote", "why": "x"})
            return {"summary": "fake", "modes": [
                {"id": "wide_split", "name": "Wide split", "description": "d", "decision": "canary_design",
                 "mechanism": "m", "solver_would": "w", "evidence": ev},
                {"id": "rush", "name": "Rush", "description": "d", "decision": "commit_timing", "mechanism": "m",
                 "solver_would": "w", "evidence": []}]}
        if "labels" in props:
            pairs = re.findall(r"^(\S+) t=(\d+) ", prompt, re.M)
            return {"labels": [{"episode": e, "t": int(t), "mode": "wide_split" if i % 2 == 0 else "rush",
                                "confidence": 0.8, "quote": self._line(corpus, e, int(t)), "explanation": "x"}
                               for i, (e, t) in enumerate(pairs)]}
        if "cohorts" in props:
            return {"cohorts": [{"cohort": "gpt-5.5/codex/v1.2", "dominant_modes": ["wide_split"], "behaviour": "b",
                                 "evidence": []}], "cross_family_finding": "f", "caveats": "c"}
        if "items" in props:
            pairs = re.findall(r"^(\S+) t=(\d+) ", prompt, re.M)
            return {"items": [{"episode": e, "t": int(t), "agent_did": "a", "solver_would": "s", "why_diverged": "w",
                               "quote": self._line(corpus, e, int(t))} for e, t in pairs]}
        if "divergence_t" in props:
            m = re.search(r"^(t(\d+) d\d+ [^\n]{20,})", prompt, re.M)
            return {"divergence_t": int(m.group(2)) if m else 0, "what_chart_shows": "c", "what_agent_believed": "b",
                    "quote": m.group(1)[:50] if m else "none"}
        if "clusters" in props:
            return {"clusters": [{"cluster": i, "name": f"c{i}", "description": "d"} for i in range(6)]}
        return {}


def _args(tmp_path, **kw):
    a = dict(runs=[str(RUN)], model="gemini-4-carbon", cache_model="gemini-3.8-flash", out=str(tmp_path / "out"),
             cache_dir=str(tmp_path / "cache"), replay=False, max_tokens=900_000, limit=0, charts=1, no_cache=False,
             skip_labels=False, batch=False, batch_timeout=1, embed=False)
    a.update(kw)
    return Namespace(**a)


def _run(tmp_path, eps, monkeypatch, fake, **kw):
    import canary.gemini.atlas as atlas
    import canary.gemini.atlas_gemini as ag
    monkeypatch.setattr(atlas, "load_corpus", lambda paths: eps)
    monkeypatch.setattr(ag, "sdk_client", lambda: fake)
    return atlas.run(_args(tmp_path, **kw))


def test_pipeline_with_fake_gemini_verifies_and_computes_in_code(tmp_path, eps, monkeypatch):
    fake = FakeGenai(eps)
    r = _run(tmp_path, eps, monkeypatch, fake)
    out = tmp_path / "out"
    j = json.loads((out / "atlas.json").read_text())
    for k in ("modes", "corpus", "human_agreement", "generated_at", "git_sha", "ledger_run_ids"):
        assert k in j
    assert {"episodes", "tokens", "cached_tokens"} <= set(j["corpus"]) and j["corpus"]["episodes"] == len(eps)
    assert j["corpus"]["cached_tokens"] > 0 and fake.deleted == "cachedContents/fake"
    m = j["modes"][0]
    assert {"id", "name", "description", "decision", "regret_share", "episodes", "quotes", "chart"} <= set(m)
    # the invented quote was dropped and counted; the verbatim ones survived
    assert all(q["verified"] for mm in j["modes"] for q in mm["quotes"])
    assert j["verification"]["dropped"] >= 1 and 0 < j["verification"]["pass_rate"] < 1
    # shares come from code: labelled regret over total regret, never above 1
    total = sum(e.total_regret for e in eps)
    lab_regret = sum(mm["regret"] for mm in j["modes"])
    assert lab_regret <= total + 1e-6 and sum(mm["regret_share"] for mm in j["modes"]) <= 1 + 1e-6
    assert j["labels"]["source"] == "cached" and j["labels"]["n"] > 0
    assert (out / "atlas.md").read_text().startswith("# Canary Failure Atlas")
    assert list((out / "atlas_charts").glob("*.png"))
    rows = [json.loads(x) for x in (tmp_path / "ledger.jsonl").read_text().splitlines()]
    assert rows and all(x["feature"] == "atlas" for x in rows) and {"cache", "generate"} <= {x["kind"] for x in rows}
    assert r["ledger_run_ids"]

    # offline replay: no client, same answers from results cache
    fake2 = FakeGenai(eps, fail=True)
    r2 = _run(tmp_path, eps, monkeypatch, fake2, replay=True, out=str(tmp_path / "out2"))
    assert fake2.calls == 0
    assert [m["id"] for m in r2["modes"]] == [m["id"] for m in r["modes"]]
    assert [m["regret_share"] for m in r2["modes"]] == [m["regret_share"] for m in r["modes"]]


def test_deterministic_fallback_when_gemini_fails(tmp_path, eps, monkeypatch):
    r = _run(tmp_path, eps, monkeypatch, FakeGenai(eps, fail=True), charts=0)
    assert r["labels"]["source"] == "fallback"
    ids = {m["id"] for m in r["modes"]}
    assert "low_information_canary" in ids
    assert r["errors"]


def test_agreement_sheet_roundtrip(tmp_path):
    from canary.gemini.atlas_agreement import agreement, claims_from_atlas, make_sheet, parse_sheet
    atlas = {"git_sha": "x", "modes": [{"id": "m", "name": "M", "quotes": [
        {"episode": f"e{i}", "t": i, "quote": "q q q", "verified": True, "why": "w"} for i in range(40)]}],
        "labels": {"steps": []}, "counterfactuals": [], "localisation": {"rows": []}}
    assert len(claims_from_atlas(atlas)) == 30
    sheet = tmp_path / "v.md"
    make_sheet(atlas, None, sheet, tmp_path / "ctx.md")
    txt = sheet.read_text()
    filled = []
    for line in txt.splitlines():
        m = re.match(r"^\| (\d+) \|", line)
        if m:
            v = ["agree", "d", "unsure"][int(m.group(1)) % 3]
            cells = line.split("|")
            cells[6] = f" {v} "
            line = "|".join(cells)
        filled.append(line)
    sheet.write_text("\n".join(filled))
    ha = agreement(parse_sheet(sheet.read_text()))
    assert ha["status"] == "done" and ha["n_labelled"] == 30 and ha["agree"] == 10 and ha["disagree"] == 10
    assert ha["score"] == 0.5
    with pytest.raises(SystemExit):
        make_sheet(atlas, None, sheet, tmp_path / "ctx.md")


def test_pack_episode_marks_high_regret_words(eps):
    e = max(eps, key=lambda e: e.total_regret)
    block = pack_episode(e)
    assert block.startswith("=== EPISODE") and f"total_regret={e.total_regret:.3f}" in block
