import sys
import time

from agents import gemini

if not gemini.enable_live():
    sys.exit("no GEMINI_API_KEY")
tool = {"name": "get_number", "description": "returns a number", "parameters": {"type": "object", "properties": {}}}
t = time.time()
r = gemini.chat(gemini.model_for("staff"), "Use the tool.", [{"role": "user", "text": "Call get_number."}], [tool], seed=0)
print(r)
print(gemini.usage(), "%.1fs" % (time.time() - t))
assert r["tool_calls"], "no tool call returned"
