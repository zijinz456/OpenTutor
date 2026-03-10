"""File-based prompt template loader.

Loads system prompts from .md files in the prompts/ directory,
supporting variable substitution and includes.
"""

import logging
import re
from functools import lru_cache
from pathlib import Path

logger = logging.getLogger(__name__)

PROMPTS_DIR = Path(__file__).parent.parent.parent / "prompts"


@lru_cache(maxsize=64)
def _load_template(name: str) -> str | None:
    """Load a template file by name (cached).

    Searches: prompts/{name}.md, prompts/{name}/prompt.md
    """
    candidates = [
        PROMPTS_DIR / f"{name}.md",
        PROMPTS_DIR / name / "prompt.md",
    ]
    for path in candidates:
        if path.is_file():
            try:
                return path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError) as e:
                logger.exception("Failed to read template %s: %s", path, e)
    return None


def _resolve_includes(template: str, depth: int = 0) -> str:
    """Resolve {{include:name}} directives.

    Max depth of 3 to prevent infinite loops.
    """
    if depth > 3:
        return template

    def replace_include(match):
        include_name = match.group(1).strip()
        included = _load_template(f"includes/{include_name}") or _load_template(
            include_name
        )
        if included:
            return _resolve_includes(included, depth + 1)
        logger.warning("Include not found: %s", include_name)
        return ""

    return re.sub(r"\{\{include:([^}]+)\}\}", replace_include, template)


def render_prompt(template_name: str, **variables) -> str | None:
    """Load and render a prompt template.

    Args:
        template_name: Name of the template (without .md extension).
                       Can include path like "scenes/study_session".
        **variables: Variables to substitute {{variable_name}}.

    Returns:
        Rendered template string, or None if template not found.
    """
    template = _load_template(template_name)
    if template is None:
        return None

    # Resolve includes first
    template = _resolve_includes(template)

    # Substitute variables
    for key, value in variables.items():
        template = template.replace(f"{{{{{key}}}}}", str(value))

    # Warn about unresolved variables
    unresolved = re.findall(r"\{\{(\w+)\}\}", template)
    if unresolved:
        logger.debug("Unresolved template variables: %s", unresolved)

    return template


def clear_cache():
    """Clear the template cache (useful for development)."""
    _load_template.cache_clear()
