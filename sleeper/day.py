from sleeper.company import World, tools_for
from sleeper.models import SEATS, Message


def deliver_events(world):
    c = world.company
    for e in world.day.events:
        e = e if isinstance(e, dict) else e.model_dump()
        if e["tick"] == world.tick:
            c.messages.append(Message(id=f"M{len(c.messages) + 1:04d}", tick=world.tick, sender_seat=e["sender"],
                                      to=[e.get("to_seat") or "all"], channel=e.get("channel", "email"), body=e["body"],
                                      subject=e.get("kind", ""), attachments=e.get("attachments", [])))


def play_round(world, team, skip=None):
    deliver_events(world)
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
