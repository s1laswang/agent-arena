"""USD per 1M tokens (input, output). Approximate; unknown model -> cost 0 + flag."""
PRICES: dict[str, tuple[float, float]] = {
    "gpt-4o": (2.5, 10.0), "gpt-5.5": (5.0, 30.0), "gpt-4o-mini": (0.15, 0.6),
    "gpt-4.1": (2.0, 8.0), "gpt-4.1-mini": (0.4, 1.6), "gpt-4.1-nano": (0.1, 0.4),
    "gpt-5": (1.25, 10.0), "gpt-5-mini": (0.25, 2.0), "gpt-5-nano": (0.05, 0.4),
    "o3": (2.0, 8.0), "o4-mini": (1.1, 4.4),
    "gemini-2.5-pro": (1.25, 10.0), "gemini-2.5-flash": (0.3, 2.5),
    "gemini-2.5-flash-lite": (0.1, 0.4), "gemini-2.0-flash": (0.1, 0.4),
}


# Cached-input list price (USD / 1M). gpt-5.5: $0.50, verified on developers.openai.com/api/docs/pricing
# (2026-11-14, <272K context). Prompt caching is automatic; usage reports cached tokens.
CACHED_PRICES: dict[str, float] = {"gpt-5.5": 0.5}


def cost(model: str, tin: int, tout: int, cached: int = 0) -> dict:
    p = PRICES.get(model)
    if p is None:  # try longest prefix (e.g. dated snapshots)
        cands = [k for k in PRICES if model.startswith(k)]
        p = PRICES[max(cands, key=len)] if cands else None
    if p is None:
        return {"cost_usd": 0.0, "cost_unknown": True}
    out = {"cost_usd": (tin * p[0] + tout * p[1]) / 1e6}  # upper bound: all input at the full price
    if cached:
        key = model if model in CACHED_PRICES else next((k for k in CACHED_PRICES if model.startswith(k)), None)
        pc = CACHED_PRICES[key] if key else p[0] * 0.1
        out["cached_in"] = cached
        out["cost_usd_est"] = ((tin - cached) * p[0] + cached * pc + tout * p[1]) / 1e6
    return out
