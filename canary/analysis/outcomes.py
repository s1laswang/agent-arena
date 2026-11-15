"""Interpret the legacy CLI importer's non-terminal, clean agent exits."""


def is_clean_agent_stop(episode: dict) -> bool:
    """A successful CLI exit without an accusation is a zero-score outcome.

    Older imports label this as ``error``; require the explicit importer note
    and successful exit so genuine infrastructure errors stay invalid.
    """
    meta = episode.get("meta") or {}
    return (
        isinstance(meta, dict)
        and meta.get("rc") == 0
        and episode.get("rc") != "timeout"
        and meta.get("valid") is not False
        and episode.get("valid") is not False
        and episode.get("accused") is None
        and episode.get("score") == 0
        and str(meta.get("note") or "").startswith(
            "agent stopped without ending the episode"
        )
    )
