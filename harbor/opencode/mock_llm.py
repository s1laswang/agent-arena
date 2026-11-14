import json, sys, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PLAN = ["my_tickets", "end_turn"]


def pick(tools, suffix):
    for t in tools:
        n = t["function"]["name"]
        if n == suffix or n.endswith("_" + suffix):
            return n


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        sys.stderr.write(" ".join(map(str, a)) + "\n")

    def do_GET(self):
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"data":[{"id":"scripted","object":"model"}]}')

    def do_POST(self):
        req = json.loads(self.rfile.read(int(self.headers["content-length"])))
        msgs, tools = req["messages"], req.get("tools") or []
        done = sum(1 for m in msgs if m["role"] == "tool")
        delta = {"role": "assistant"}
        finish = "stop"
        name = pick(tools, PLAN[done]) if done < len(PLAN) else None
        if name:
            delta["tool_calls"] = [{"index": 0, "id": f"call{done}", "type": "function",
                                    "function": {"name": name, "arguments": "{}"}}]
            finish = "tool_calls"
        else:
            delta["content"] = "done"
        sys.stderr.write(f"turn tools={len(tools)} done={done} -> {name}\n")
        base = {"id": "x", "object": "chat.completion.chunk", "created": int(time.time()), "model": "scripted"}
        chunks = [dict(base, choices=[{"index": 0, "delta": delta, "finish_reason": None}]),
                  dict(base, choices=[{"index": 0, "delta": {}, "finish_reason": finish}]),
                  dict(base, choices=[], usage={"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2})]
        self.send_response(200)
        self.send_header("content-type", "text/event-stream")
        self.end_headers()
        for c in chunks:
            self.wfile.write(f"data: {json.dumps(c)}\n\n".encode())
        self.wfile.write(b"data: [DONE]\n\n")


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", int(sys.argv[1]) if len(sys.argv) > 1 else 8899), H).serve_forever()
