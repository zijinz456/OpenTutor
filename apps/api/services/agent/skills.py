"""Teaching skills system — auto-matched pedagogical strategies.

Skills are markdown files with YAML frontmatter in the skills/ directory.
They are matched to conversations based on keyword triggers and scene context,
then injected into agent system prompts.
"""

import logging
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)

SKILLS_DIR = Path(__file__).parent.parent.parent / "skills"


@dataclass
class Skill:
    """A teaching skill/strategy."""
    name: str
    triggers: list[str] = field(default_factory=list)
    scenes: list[str] = field(default_factory=list)
    priority: int = 5
    content: str = ""


@lru_cache(maxsize=1)
def load_skills() -> list[Skill]:
    """Load all skills from the skills/ directory."""
    skills = []
    if not SKILLS_DIR.is_dir():
        logger.info("Skills directory not found: %s", SKILLS_DIR)
        return skills

    for path in sorted(SKILLS_DIR.glob("*.md")):
        try:
            text = path.read_text(encoding="utf-8")
            # Parse YAML frontmatter
            fm_match = re.match(r"^---\n(.*?)\n---\n(.*)", text, re.DOTALL)
            if not fm_match:
                logger.warning("Skill file %s has no frontmatter, skipping", path.name)
                continue

            meta = yaml.safe_load(fm_match.group(1))
            content = fm_match.group(2).strip()

            skills.append(Skill(
                name=meta.get("name", path.stem),
                triggers=meta.get("triggers", []),
                scenes=meta.get("scenes", []),
                priority=meta.get("priority", 5),
                content=content,
            ))
        except (OSError, UnicodeDecodeError, ValueError, KeyError) as e:
            logger.exception("Failed to load skill %s: %s", path.name, e)

    logger.info("Loaded %d teaching skills", len(skills))
    return skills


def match_skills(
    message: str,
    scene: str | None = None,
    limit: int = 2,
) -> list[Skill]:
    """Find matching skills for the current context.

    Matching criteria:
    1. Keyword triggers in the user message (case-insensitive)
    2. Scene compatibility

    Returns top skills sorted by (trigger matches * priority), limited.
    """
    all_skills = load_skills()
    if not all_skills:
        return []

    message_lower = message.lower()
    scored: list[tuple[float, Skill]] = []

    for skill in all_skills:
        # Count trigger matches
        trigger_hits = sum(1 for t in skill.triggers if t.lower() in message_lower)
        if trigger_hits == 0:
            continue

        # Scene bonus
        scene_match = 1.0
        if scene and skill.scenes:
            if scene in skill.scenes:
                scene_match = 1.5
            else:
                scene_match = 0.5  # Penalize but don't exclude

        score = trigger_hits * skill.priority * scene_match
        scored.append((score, skill))

    # Sort by score descending
    scored.sort(key=lambda x: x[0], reverse=True)
    return [skill for _, skill in scored[:limit]]


def clear_cache():
    """Clear the skills cache."""
    load_skills.cache_clear()
