import pytest

pytest.importorskip("torch")


def test_weighted_ce_matches_plain_when_unweighted():
    import torch
    from train.lora_sft import weighted_ce
    torch.manual_seed(0)
    lg = torch.randn(1, 6, 11)
    y = torch.tensor([[-100, 3, 4, -100, 5, 1]])
    plain = torch.nn.functional.cross_entropy(lg[:, :-1].reshape(-1, 11), y[:, 1:].reshape(-1), ignore_index=-100)
    assert torch.allclose(weighted_ce(lg, y, torch.ones(1, 6), 1.0), plain)
