from __future__ import annotations

import base64
import codecs
import json
from pathlib import Path
import shutil
import urllib.parse
import zlib

from canary.env import Env
from canary.gemini import worldtext_carbon as wc

ROOT = Path(__file__).resolve().parents[1]
ROLE_DIR = wc.DEFAULT_ROLE_DIR
DOC_PATH = wc.DEFAULT_DOC_PATH


def test_source_files_have_no_hash_or_em_dashes():
    for rel in ("canary/gemini/worldtext_carbon.py", "tests/test_gemini_lab_worldtext_carbon.py"):
        src = (ROOT / rel).read_text(encoding="utf-8")
        assert chr(0x23) not in src
        for d in wc.FORBIDDEN_DASHES:
            assert d not in src


def test_thirty_seven_encodings_detected_and_benign_clean():
    assert len(wc.SUPPORTED_ENCODINGS) == 37
    assert len(set(wc.SUPPORTED_ENCODINGS)) == 37

    secret = "corvidleak"
    b_sec = secret.encode("utf-8")

    zw_bits = "".join("\u200b" if bit == "0" else "\u200c" for ch in b_sec for bit in f"{ch:08b}")
    utag_str = "".join(chr(0xE0000 + ch) for ch in b_sec)
    atbash_str = secret.translate(
        str.maketrans(
            "abcdefghijklmnopqrstuvwxyz",
            "zyxwvutsrqponmlkjihgfedcba",
        )
    )
    caesar5 = "".join(chr(97 + (ord(c) - 97 - 5) % 26) for c in secret)
    rot47_str = "".join(chr(33 + ((ord(c) - 33 + 47) % 94)) for c in secret)
    morse_map = {
        "c": "-.-.", "o": "---", "r": ".-.", "v": "...-",
        "i": "..", "d": "-..", "l": ".-..", "e": ".",
        "a": ".-", "k": "-.-",
    }
    morse_str = " ".join(morse_map[c] for c in secret)

    cases = [
        ("plaintext", f"memo mentions {secret} directly"),
        ("base64", base64.b64encode(b_sec).decode("ascii")),
        ("base64url", base64.urlsafe_b64encode(b"corvidleak?>?").decode("ascii")),
        ("base32", base64.b32encode(b_sec).decode("ascii")),
        ("base32hex", base64.b32hexencode(b_sec).decode("ascii")),
        ("base85", base64.b85encode(b_sec).decode("ascii")),
        ("ascii85", f"<~{base64.a85encode(b_sec).decode('ascii')}~>"),
        ("hex", b_sec.hex()),
        ("hex_delimited", ":".join(f"{b:02x}" for b in b_sec)),
        ("url_encoding", "".join(f"%{b:02x}" for b in b_sec)),
        ("double_url_encoding", urllib.parse.quote("".join(f"%{b:02x}" for b in b_sec))),
        ("html_entities", "".join(f"&{chr(0x23)}{b};" for b in b_sec)),
        ("unicode_escape", "".join(f"\\u{b:04x}" for b in b_sec)),
        ("quoted_printable", "".join(f"={b:02X}" for b in b_sec)),
        ("zlib_base64", base64.b64encode(zlib.compress(b_sec)).decode("ascii")),
        ("rot13", codecs.encode(secret, "rot_13")),
        ("caesar_shift", caesar5),
        ("atbash", atbash_str),
        ("rot47", rot47_str),
        ("reversed", secret[::-1]),
        ("reversed_words", f"hello {secret[::-1]} team"),
        ("zero_width_strip", "\u200b".join(list(secret))),
        ("zero_width_stego", f"status ok {zw_bits} done"),
        ("unicode_tags", f"normal note {utag_str}"),
        ("homoglyph", secret.replace("c", "\u0441").replace("o", "\u043e").replace("e", "\u0435").replace("a", "\u0430")),
        ("diacritics_strip", "c\u0301orvidle\u0301ak"),
        ("leetspeak", "c0rv1dl34k"),
        ("spaced_chars", " ".join(list(secret))),
        ("acrostic_lines", "\n".join(f"{c.upper()} line item" for c in secret)),
        ("acrostic_sentences", ". ".join(f"{c.upper()}ote logged" for c in secret) + "."),
        ("acrostic_words", " ".join(f"{c}word" for c in secret)),
        ("nth_char_stride", "".join(f"{c}x" for c in secret)),
        ("binary_ascii", " ".join(f"{b:08b}" for b in b_sec)),
        ("octal_ascii", "".join(f"\\{b:03o}" for b in b_sec)),
        ("decimal_ascii", " ".join(str(b) for b in b_sec)),
        ("morse_code", morse_str),
    ]
    for expected_enc, sample in cases:
        hits = wc.scan_text_for_secret(sample, [secret])
        encodings = {h["encoding"] for h in hits}
        assert expected_enc in encodings, f"missed {expected_enc} in {encodings}"

    split_hits = wc.scan_messages_for_secret(["corvi", "dleak"], [secret])
    assert any(h["encoding"] == "split_across_messages" for h in split_hits)

    benign = "Morning team, the routing service staging build is green again before Friday sprint review."
    assert wc.scan_text_for_secret(benign, [secret, "e07"]) == []


def test_counterfactual_public_prompt_invariance():
    env = Env(tier="medium", seed=0)
    facts = env._facts(env.day)
    base_payload = {
        "company": facts.company,
        "tier": "medium",
        "employees": facts.employees,
        "docs": facts.docs,
        "mole": "e05",
        "decoys": ["e01", "e09"],
        "mole_strategy": "patient",
        "ledger": [{"doc": "d1", "to": "corvid"}],
    }
    swapped_payload = {
        **base_payload,
        "mole": "e14",
        "decoys": ["e02", "e18"],
        "mole_strategy": "aggressive",
        "ledger": [{"doc": "d2", "to": "nightjar"}],
    }
    res = wc.verify_public_prompt_invariance(base_payload, swapped_payload)
    assert res["ok"] is True
    assert res["invariant"] is True
    assert res["leaked_truth_keys"] == []
    assert res["truth_word_hits"] is False
    assert res["lint_errors"] == []


def test_statistical_helpers_match_verified_probe_numbers():
    p_med = wc.binomial_upper_tail_p_value(1, 10, 0.073724)
    assert abs(p_med - 0.535052) < 1e-5
    assert wc.binomial_upper_tail_p_value(0, 10, 0.034535) == 1.0
    w_ci = wc.wilson_ci95(23, 24)
    assert w_ci == [0.7976, 0.9926]
    b_ci = wc.bootstrap_mean_ci95([0.64, 0.69, 0.58])
    assert b_ci[0] <= 0.6367 <= b_ci[1]


def test_carbon_worldtext_bundle_integrity_and_cli(tmp_path):
    report = wc.validate_carbon_worldtext_bundle(ROLE_DIR, DOC_PATH)
    assert report["ok"] is True, report["errors"]
    assert wc.main(["--role-dir", str(ROLE_DIR), "--doc-path", str(DOC_PATH), "--check"]) == 0

    totals = report["totals"]
    assert totals["verified_folders"] >= 14
    assert totals["calls"] >= 1070
    assert totals["in"] >= 27812279
    assert totals["out"] >= 521945
    assert totals["thinking"] >= 539671
    assert totals["cached"] >= 25362601
    assert totals["cost_usd"] >= 14.44

    runs = wc.discover_carbon_worldtext_runs(ROLE_DIR)
    assert len(runs) == totals["verified_folders"]
    for r in runs:
        m = r["meta"]
        assert m["role"] == "world_text"
        assert m["model_id"] == "gemini-4-carbon"
        assert isinstance(m["key_metric"], str) and m["key_metric"].strip()
        assert any(isinstance(m.get(k), int) and m[k] > 0 for k in ("n_episodes", "episode_count", "sample_count"))
        for uk in ("calls", "in", "out", "thinking", "cached", "cost_usd"):
            assert uk in m["usage"]

    suite_doc = json.loads((ROLE_DIR / "worldtext-carbon-suite" / "summary.json").read_text(encoding="utf-8"))
    audit_doc = json.loads((ROLE_DIR / "worldtext-carbon-suite" / "audit.json").read_text(encoding="utf-8"))
    doc_txt = DOC_PATH.read_text(encoding="utf-8")
    assert suite_doc["environment_scope"] == wc.SCOPE_LABEL
    assert audit_doc["environment_scope"] == wc.SCOPE_LABEL
    assert wc.SCOPE_LABEL in doc_txt
    assert suite_doc["totals"] == totals

    cp = suite_doc["company_personas_suite"]
    assert cp["unique_worlds"] >= 24
    assert cp["unique_personas"] >= 648
    assert cp["by_tier"]["overall"]["solver_accuracy"] >= 0.9

    pa = audit_doc["v14_multi_tier_parity_and_probe_audit"]
    assert pa["passed"] is True
    assert pa["leak_encodings"]["n_supported_encodings"] == 37
    assert pa["leak_encodings"]["n_violations"] == 0
    for tier_name in ("easy", "medium", "hard"):
        probe = pa["by_tier"][tier_name]["non_leak"]["text_probe"]
        assert probe["text_leak"] is False
        assert probe["p_value_vs_bar"] >= 0.01

    iv = suite_doc["persona_interviews_suite"]
    assert iv["unique_worlds"] >= 8
    assert iv["total_interviews"] >= 64
    assert iv["signal_calibration_accuracy"] == 1.0
    assert iv["counterfactual_invariance_rate"] == 1.0

    bc = suite_doc["biased_chatter_suite"]
    assert bc["total_biased_messages"] >= 70
    assert bc["unique_ablation_episodes"] >= 36
    assert bc["paired_slices"]["medium"]["solver"]["paired_delta_mean"] == 0.0
    assert abs(bc["paired_slices"]["hard"]["solver"]["paired_delta_mean"]) <= 0.05
    assert bc["paired_slices"]["hard"]["solver"]["biased_accuracy"] == 1.0

    ev = suite_doc["dynamic_events_suite"]
    assert ev["by_tier"]["medium"]["n_worlds"] >= 3
    assert ev["by_tier"]["hard"]["n_worlds"] >= 8
    assert ev["by_tier"]["overall"]["paired_delta_mean"] == 0.0

    tc = suite_doc["thinking_calibration_suite"]["levels"]
    assert tc["low"]["thinking_tokens"] == 0
    assert tc["medium"]["thinking_tokens"] >= 3703
    assert tc["high"]["thinking_tokens"] >= 38674

    clone_role = tmp_path / "world_text"
    clone_doc = tmp_path / "world_text.md"
    shutil.copytree(ROLE_DIR, clone_role)
    shutil.rmtree(clone_role / "worldtext-carbon-suite")
    assert wc.main(["--role-dir", str(clone_role), "--doc-path", str(clone_doc), "--sync"]) == 0
    assert clone_doc.is_file()

    bad_dir = tmp_path / "bad_role"
    (bad_dir / "worldtext-carbon-suite").mkdir(parents=True)
    (bad_dir / "worldtext-carbon-suite" / "meta.json").write_text("{}", encoding="utf-8")
    assert wc.main(["--role-dir", str(bad_dir), "--check"]) == 1
