import json

N = 6
OBS_CHARS = 1500

def call_json(tool, args):
    return json.dumps({"tool": tool, "args": args}, sort_keys=True)

def summary(history):
    closed = [h["args"].get("id") for h in history if h["tool"] == "close_ticket"]
    return f"calls used: {len(history)}/60. tickets closed: {closed}."

def prompt(system, seat, history, obs, n=N):
    msgs = [{"role": "system", "content": f"{system}\nYou are the {seat} seat. {summary(history)}"}]
    for h in history[-n:]:
        msgs.append({"role": "user", "content": h["view"][:OBS_CHARS]})
        msgs.append({"role": "assistant", "content": call_json(h["tool"], h.get("args") or {})})
    msgs.append({"role": "user", "content": obs[:OBS_CHARS]})
    return msgs

SIMPLE = "{% for m in messages %}<|{{ m.role }}|>{{ m.content }}\n{% endfor %}{% if add_generation_prompt %}<|assistant|>{% endif %}"

def ensure_template(tok):
    if not getattr(tok, "chat_template", None):
        tok.chat_template = SIMPLE
    return tok
