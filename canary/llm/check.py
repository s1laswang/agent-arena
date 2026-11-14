"""Smoke test: python -m canary.llm.check gemini|openai|stub|<spec>. Never prints keys."""
from __future__ import annotations

import sys

from . import get_client


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    spec = argv[0] if argv else "stub"
    try:
        c = get_client(spec)
        # thinking models count thoughts against max_output_tokens, so leave room
        r = c.chat([{"role": "user", "content": "Reply with the single word OK."}], max_tokens=2048)
        fc = None
        if spec.startswith("gemini"):  # function calling, as the investigator loop uses it
            tool = {"name": "status", "description": "Return the current day.",
                    "input_schema": {"type": "object", "properties": {}}}
            t = c.chat([{"role": "user", "content": "Call the status tool."}], tools=[tool])
            fc = [x.name for x in t.tool_calls]
            if fc != ["status"]:
                raise RuntimeError(f"function calling failed: tool_calls={fc} text={t.text[:80]!r}")
    except Exception as e:  # noqa: BLE001
        print(f"FAIL {spec}: {type(e).__name__}: {e}", file=sys.stderr)
        return 1
    print(f"OK {c.name} text={r.text.strip()[:40]!r} tokens_in={r.usage.get('in')} "
          f"tokens_out={r.usage.get('out')} cost_usd={r.usage.get('cost_usd', 0):.6f}"
          + (f" function_call={fc}" if fc is not None else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
