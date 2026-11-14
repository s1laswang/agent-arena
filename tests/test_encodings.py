from __future__ import annotations

import base64
import pytest

from canary.env import Env
from canary.redteam.encodings import (
    DECODERS,
    ENCODERS,
    SPLIT_ENCODERS,
    _collect_episode_texts,
    _episode_secret_tokens,
    audit_env_no_encoded_leak,
    main,
    scan_for_secret,
    self_test,
)
from canary.text.template import TemplateProvider


def test_registry_size_and_distinctness():
    assert len(ENCODERS) >= 80
    assert len(DECODERS) >= 80
    assert set(ENCODERS) == set(DECODERS)
    probe = "Mole=e07? Seed:900003"
    outputs = {fn(probe) for fn in ENCODERS.values()}
    assert len(outputs) >= 80


@pytest.mark.parametrize("enc_name", sorted(ENCODERS))
def test_every_encoder_100_percent_recall(enc_name: str):
    secret = "mole=e07"
    encoded = ENCODERS[enc_name](secret)
    assert isinstance(encoded, str) and encoded
    hits = scan_for_secret([encoded], [secret])
    assert hits, f"missed {enc_name}: {encoded!r}"
    assert any(h["token"] == secret for h in hits)

    decoded = DECODERS[enc_name](encoded)
    if enc_name == "vowel_stripped":
        assert decoded == "ml=07"
    else:
        assert secret.casefold() in decoded.casefold(), f"decoder {enc_name} returned {decoded!r}"


@pytest.mark.parametrize("secret", ["900007", "a94f1c82e70d4b11", "medium:900004"])
def test_numeric_and_hex_secrets_across_all_encoders(secret: str):
    res = self_test(secret)
    assert res["ok"], res
    assert res["recall"] == 1.0
    assert res["false_positives"] == 0


@pytest.mark.parametrize("split_name", sorted(SPLIT_ENCODERS))
def test_split_across_messages_detection(split_name: str):
    secret = "mole=e14"
    parts = SPLIT_ENCODERS[split_name](secret)
    assert len(parts) >= 2
    hits = scan_for_secret(parts, [secret])
    assert any(h["token"] == secret for h in hits), split_name


def test_cross_message_acrostics():
    secret = "mole=e05"
    first_msgs = [f"{ch} update from yesterday" for ch in secret]
    last_msgs = [f"reviewed item {ch}" for ch in secret]
    assert any(h["token"] == secret for h in scan_for_secret(first_msgs, [secret]))
    assert any(h["token"] == secret for h in scan_for_secret(last_msgs, [secret]))


def test_embedded_in_prose_and_negative_controls():
    secret = "mole=e11"
    inline_names = (
        "base64", "urlsafe_base64", "hex_lower", "hex_spaced", "hex_0x",
        "rot13", "caesar_07", "morse", "binary_8bit", "decimal_ascii",
        "url_percent", "html_hex_entities", "json_unicode_escape",
        "punycode", "zero_width_stego", "unicode_fullwidth", "math_bold",
    )
    for name in inline_names:
        msg = f"Hi team, reference token ({ENCODERS[name](secret)}) for the Friday sync."
        hits = scan_for_secret([msg], [secret])
        assert any(h["token"] == secret for h in hits), name

    benign = [
        "Quarterly budget review moved to Thursday morning.",
        "Employee e11 submitted the travel expense sheet.",
        "Exactly one employee is a mole who leaks sensitive documents.",
        base64.b64encode(b"mole=e12").decode("ascii"),
        b"900008".hex(),
    ]
    assert scan_for_secret(benign, [secret, "900007", "deadbeefcafe9999"]) == []


def test_audit_env_no_encoded_leak_clean():
    judge_res = audit_env_no_encoded_leak(tier="medium", seeds=range(900_000, 900_004))
    assert judge_res["ok"] is True
    assert judge_res["clean"] is True
    assert judge_res["leak_count"] == 0
    assert judge_res["leaks"] == []
    assert judge_res["n_encodings"] >= 80
    assert judge_res["texts_scanned"] > 100

    dev_res = audit_env_no_encoded_leak(tier="easy", seeds=range(2))
    assert dev_res["ok"] is True
    assert dev_res["leak_count"] == 0


def test_audit_catches_planted_stego_leak():
    class LeakyProvider(TemplateProvider):
        def __init__(self, payload: str):
            self._payload = payload

        def day_messages(self, facts):
            msgs = super().day_messages(facts)
            if facts.day == 1 and msgs:
                msgs[0] = dict(msgs[0], body=msgs[0]["body"] + " " + self._payload)
            return msgs

    probe_env = Env("easy", 900_002)
    true_mole = probe_env._world.mole
    planted = ENCODERS["zero_width_stego"](f"mole={true_mole}")
    leaky_env = Env("easy", 900_002, text_provider=LeakyProvider(planted))
    texts = _collect_episode_texts(leaky_env)
    tokens = _episode_secret_tokens(leaky_env, "easy", 900_002, b"secret-key-bytes-1234")
    hits = scan_for_secret(texts, tokens)
    assert any(h["token"] == f"mole={true_mole}" for h in hits)


def test_cli_entrypoint(capsys):
    rc = main(["--tier", "easy", "--seeds", "900000-900001"])
    out = capsys.readouterr().out
    assert rc == 0
    assert '"ok": true' in out
