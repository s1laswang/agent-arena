from sleeper.company import World, tools_for
from sleeper.day import play_round
from agents.staff import make_team
from sleeper.tickets import make_day
from sleeper.verifier import score


class SeatSession:
    def __init__(self, day, seat="controller", team=None):
        self.world = World(day)
        self.seat = seat
        self.team = team or make_team(day, day.seed)
        self.over = False

    def tools(self):
        return tools_for(self.seat)

    def call(self, tool, args=None):
        if self.over:
            return {"ok": False, "error": "the day is over"}
        out = self.world.call(self.seat, tool, args)
        if tool == "end_turn":
            play_round(self.world, self.team, skip=self.seat)
            self.over = self.world.tick >= self.world.day.ticks
        return out

    def result(self, agent="opencode", model="?"):
        w = self.world
        return score(w.day, w.initial, w.company, w.ledger, agent=agent, seat_under_test=self.seat, model=model)


def new_session(seed, seat="controller", team=None, **kw):
    return SeatSession(make_day(seed, **kw), seat, team)
