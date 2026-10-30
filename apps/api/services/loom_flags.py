"""Single switch for the experimental LOOM/LECTOR layer.

Every producer and consumer of the concept graph (graph build at ingestion,
concept_mastery updates, prerequisite gaps, confusion pairs, LECTOR review
sessions, chat greeting review summary, scheduler cross-course linking,
agent signals) must check these helpers and return an empty/neutral result
when the layer is off.  The flag is read at call time so tests can
monkeypatch ``config.settings``.
"""

from config import settings


def loom_enabled() -> bool:
    """True when ENABLE_EXPERIMENTAL_LOOM is set."""
    return bool(settings.enable_experimental_loom)


def lector_enabled() -> bool:
    """LECTOR needs the LOOM graph, so it is on only when both flags are set."""
    return loom_enabled() and bool(settings.enable_experimental_lector)
