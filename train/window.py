import json

N = 6
SYSTEM = "You work at a company. Use one tool per turn and reply with a JSON tool call."
OBS_CHARS = 1500

def call_json(tool, args):
    return json.dumps({"tool": tool, "args": args}, sort_keys=True)

def summary(history):
    closed = [h["args"].get("id") for h in history if h["tool"] == "close_ticket"]
    return f"calls used: {len(history)}/60. tickets closed: {closed}."

def render(x):
    return json.dumps(x, sort_keys=True, default=str)[:OBS_CHARS]

def prompt(system, seat, history, header, n=N):
    msgs = [{"role": "system", "content": f"{system}\nYou are the {seat} seat. {summary(history)}"},
            {"role": "user", "content": render(header)}]
    for h in history[-n:]:
        msgs.append({"role": "assistant", "content": call_json(h["tool"], h.get("args") or {})})
        msgs.append({"role": "user", "content": render(h["effect"])})
    return msgs

SIMPLE = "{% for m in messages %}<|{{ m.role }}|>{{ m.content }}\n{% endfor %}{% if add_generation_prompt %}<|assistant|>{% endif %}"

def ensure_template(tok):
    if not getattr(tok, "chat_template", None):
        tok.chat_template = SIMPLE
    return tok
