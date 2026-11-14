"""Poisoned Inbox: a tool-use RL environment where the data is partly poisoned.

Quick use:
    from pinbox.episode import Episode
    from pinbox.client import EpisodeClient
    ep = Episode.create("ap_run", seed=7, difficulty=2)
    client = EpisodeClient(ep)
    print(client.instruction())
    client.call("list_invoices", status="open")
    print(ep.grade().reward)
"""
__version__ = "0.1.0"
