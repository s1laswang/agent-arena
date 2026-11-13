"""LLM provider layer. Owner: HEAD-AGENTS (engineer: llm-providers).

    client = get_client("stub" | "openai:<model>" | "gemini:<model>")
    resp = client.chat(messages: list[dict], tools: list[dict] | None = None,
                       temperature: float = 0.0, response_schema: dict | None = None) -> LLMResponse
    LLMResponse: {text: str, tool_calls: list[{id, name, args}], usage: {in, out}, raw: Any}

Keys come from .env (GEMINI_API_KEY, OPENAI_API_KEY) via python-dotenv. Never log keys.
Missing key -> clear error. `stub` always works (deterministic) so every Gemini path is
tested tonight without a key; in the morning only the key changes.
"""
