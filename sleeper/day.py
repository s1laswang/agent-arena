from sleeper.company import World, tools_for
from sleeper.models import SEATS


def play_round(world, team, skip=None):
    for seat in SEATS:
        if seat == skip or seat in world.company.quarantined or seat not in team:
            continue
        team[seat].turn(seat, {"tick": world.tick, "seat": seat, "round": world.tick}, tools_for(seat),
                        lambda name, args=None, s=seat: world.call(s, name, args))
    world.advance()


def run_day(day, team):
    world = World(day)
    while world.tick < day.ticks:
        play_round(world, team)
    return world
