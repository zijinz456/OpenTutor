"""Deprecated compatibility shim for tutor prompt constants.

Use ``services.agent.agents.prompts`` directly.
"""

from __future__ import annotations

import warnings

from services.agent.agents.prompts import *  # noqa: F403

warnings.warn(
    "services.agent.agents.tutor_prompts is deprecated; "
    "import from services.agent.agents.prompts instead.",
    DeprecationWarning,
    stacklevel=2,
)

