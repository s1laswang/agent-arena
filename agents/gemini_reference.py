import zlib

from agents import gemini
from agents.procedure import PROCEDURE_TEXT, Evidence, check, make_procedure_team
from agents.staff import BUDGET, ROLE_PROMPTS, SEATS

NOTE = "\n\nTool calls that break the procedure are blocked and you get an error: change course."


class GeminiReference:
    def __init__(self, seat, seed=0, fallback=None, ev=None):
        self.seat = seat
        self.seed = zlib.crc32(("%s:%s" % (seed, seat)).encode())
        self.fallback = fallback
        self.ev = ev or Evidence()
        self.log = []
        self.agent_kind = "gemini" if gemini.enabled() else "scripted"

    def turn(self, seat, view, tools, call):
        if not gemini.enabled():
            self.agent_kind = "scripted"
            return self.fallback.turn(seat, view, tools, call)
        cache = {}
        try:
            return gemini.run_tool_loop(gemini.model_for("reference"), ROLE_PROMPTS[seat] + "\n\n" + PROCEDURE_TEXT + NOTE, str(view), tools, call,
                                        max_steps=BUDGET, role="reference", seed=self.seed, log=self.log.append,
                                        guard=lambda n, a: check(n, a, call, seat, cache, self.ev))
        except gemini.GeminiUnavailable:
            self.agent_kind = "scripted"
            return self.fallback.turn(seat, view, tools, call)


def make_gemini_procedure_team(day=None, seed=0):
    scripted = make_procedure_team(day, seed=seed)
    ev = Evidence()
    return {s: GeminiReference(s, seed, scripted[s], ev) for s in SEATS}
