"""USD per 1M tokens (input, output). Approximate; unknown model -> cost 0 + flag."""
PRICES: dict[str, tuple[float, float]] = {
    "gpt-4o": (2.5, 10.0), "gpt-4o-mini": (0.15, 0.6),
    "gpt-4.1": (2.0, 8.0), "gpt-4.1-mini": (0.4, 1.6), "gpt-4.1-nano": (0.1, 0.4),
    "gpt-5": (1.25, 10.0), "gpt-5-mini": (0.25, 2.0), "gpt-5-nano": (0.05, 0.4),
    "o3": (2.0, 8.0), "o4-mini": (1.1, 4.4),
    "gemini-2.5-pro": (1.25, 10.0), "gemini-2.5-flash": (0.3, 2.5),
    "gemini-2.5-flash-lite": (0.1, 0.4), "gemini-2.0-flash": (0.1, 0.4),
}


def cost(model: str, tin: int, tout: int) -> dict:
    p = PRICES.get(model)
    if p is None:  # try longest prefix (e.g. dated snapshots)
        cands = [k for k in PRICES if model.startswith(k)]
        p = PRICES[max(cands, key=len)] if cands else None
    if p is None:
        return {"cost_usd": 0.0, "cost_unknown": True}
    return {"cost_usd": (tin * p[0] + tout * p[1]) / 1e6}
