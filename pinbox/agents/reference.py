"""The reference agent: a scripted expert that follows the written policy.

Each family writes its expert as Task.reference(client); it may only use client.call and
the instruction text. This module just looks it up for an episode.
"""
from __future__ import annotations


def reference_for(family: str):
    """The reference agent callable `agent(client)` for a family."""
    from ..tasks import get_task
    return get_task(family).reference


def run_reference(episode) -> None:
    """Run the reference on an episode (in place)."""
    from ..client import EpisodeClient
    reference_for(episode.family)(EpisodeClient(episode))
