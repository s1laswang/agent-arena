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
        msgs.append({"role": "user", "content": h["obs"][:OBS_CHARS]})
        msgs.append({"role": "assistant", "content": call_json(h["tool"], h.get("args", {}))})
    msgs.append({"role": "user", "content": obs[:OBS_CHARS]})
    return msgs
