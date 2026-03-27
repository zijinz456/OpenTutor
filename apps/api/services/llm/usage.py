"""LLM usage recording, pricing estimation, and aggregation.

Inspired by OpenFang's metering engine with 60+ model pricing table.
Records every LLM call and provides aggregation queries for dashboards.
"""

import logging
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.usage_event import UsageEvent

logger = logging.getLogger(__name__)


# ── Model Pricing Table ──
# (input_cost_per_million, output_cost_per_million) in USD
# Order matters: more specific patterns checked first (e.g. "gpt-4o-mini" before "gpt-4o")

MODEL_PRICING: list[tuple[str, float, float]] = [
    # OpenAI
    ("gpt-4.1-mini", 0.40, 1.60),
    ("gpt-4.1-nano", 0.10, 0.40),
    ("gpt-4.1", 2.00, 8.00),
    ("gpt-4o-mini", 0.15, 0.60),
    ("gpt-4o", 2.50, 10.00),
    ("o3-mini", 1.10, 4.40),
    ("o3", 10.00, 40.00),
    ("o4-mini", 1.10, 4.40),

    # Anthropic
    ("claude-opus-4", 15.00, 75.00),
    ("claude-sonnet-4", 3.00, 15.00),
    ("claude-haiku-4", 0.80, 4.00),
    ("claude-3.5-sonnet", 3.00, 15.00),
    ("claude-3.5-haiku", 0.80, 4.00),

    # Google
    ("gemini-2.5-pro", 1.25, 10.00),
    ("gemini-2.5-flash", 0.15, 0.60),
    ("gemini-2.0-flash", 0.10, 0.40),
    ("gemini-1.5-pro", 1.25, 5.00),
    ("gemini-1.5-flash", 0.075, 0.30),

    # DeepSeek
    ("deepseek-chat", 0.14, 0.28),
    ("deepseek-reasoner", 0.55, 2.19),

    # Groq (hosted open-source, priced by Groq)
    ("llama-3.3-70b", 0.59, 0.79),
    ("llama-3.1-8b", 0.05, 0.08),
    ("mixtral-8x7b", 0.24, 0.24),
    ("gemma2-9b", 0.20, 0.20),

    # Open-source / local (effectively free)
    ("qwen", 0.0, 0.0),
    ("llama", 0.0, 0.0),
    ("mistral", 0.0, 0.0),
    ("phi", 0.0, 0.0),
]

# Fallback pricing for unknown models
DEFAULT_PRICING = (1.0, 3.0)  # $1/M input, $3/M output


def estimate_cost(model_name: str, input_tokens: int, output_tokens: int) -> float:
    """Estimate USD cost for a single LLM call.

    Uses pattern matching against the pricing table.
    """
    model_lower = model_name.lower()
    input_rate, output_rate = DEFAULT_PRICING

    for pattern, in_rate, out_rate in MODEL_PRICING:
        if pattern in model_lower:
            input_rate, output_rate = in_rate, out_rate
            break

    cost = (input_tokens * input_rate + output_tokens * output_rate) / 1_000_000
    return round(cost, 6)


# Local model providers that should not be tracked for usage/cost
_LOCAL_PROVIDERS = {"lmstudio", "lm_studio", "lm-studio", "ollama", "local"}
_CLOUD_PROVIDERS = {
    "groq", "openai", "anthropic", "deepseek", "openrouter",
    "gemini", "together", "fireworks", "azure", "bedrock",
}
_LOCAL_MODEL_PATTERNS = ("qwen", "llama", "mistral", "phi", "gemma", "yi-", "codestral")


def _is_local_model(model_provider: str, model_name: str) -> bool:
    """Check if a model is local (free) and should skip usage recording."""
    provider_lower = model_provider.lower()
    if provider_lower in _LOCAL_PROVIDERS:
        return True
    # Known cloud providers always incur cost, even for open-weight models
    if provider_lower in _CLOUD_PROVIDERS:
        return False
    # Unknown provider: fall back to model name heuristic
    name_lower = model_name.lower()
    return any(p in name_lower for p in _LOCAL_MODEL_PATTERNS)


async def record_usage(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    course_id: uuid.UUID | None = None,
    agent_name: str | None = None,
    scene: str | None = None,
    model_provider: str = "unknown",
    model_name: str = "unknown",
    input_tokens: int = 0,
    output_tokens: int = 0,
    tool_calls: int = 0,
    metadata: dict | None = None,
) -> UsageEvent | None:
    """Record a single LLM usage event. Skips local models (ollama, lmstudio)."""
    if _is_local_model(model_provider, model_name):
        logger.debug("Skipping usage recording for local model: %s/%s", model_provider, model_name)
        return None

    cost = estimate_cost(model_name, input_tokens, output_tokens)

    event = UsageEvent(
        user_id=user_id,
        course_id=course_id,
        agent_name=agent_name,
        scene=scene,
        model_provider=model_provider,
        model_name=model_name,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        estimated_cost_usd=cost,
        tool_calls=tool_calls,
        metadata_json=metadata,
    )
    db.add(event)
    await db.commit()
    return event


# ── Aggregation Queries ──


def _period_start(period: str) -> datetime:
    """Get the start of the given time period."""
    now = datetime.now(timezone.utc)
    if period == "day":
        return now - timedelta(days=1)
    elif period == "week":
        return now - timedelta(weeks=1)
    elif period == "month":
        return now - timedelta(days=30)
    return now - timedelta(days=1)


async def get_usage_summary(
    db: AsyncSession,
    user_id: uuid.UUID,
    period: str = "day",
    course_id: uuid.UUID | None = None,
) -> dict:
    """Get aggregate usage summary for a time period."""
    start = _period_start(period)

    q = (
        select(
            func.count(UsageEvent.id).label("total_calls"),
            func.coalesce(func.sum(UsageEvent.input_tokens), 0).label("total_input_tokens"),
            func.coalesce(func.sum(UsageEvent.output_tokens), 0).label("total_output_tokens"),
            func.coalesce(func.sum(UsageEvent.estimated_cost_usd), 0).label("total_cost_usd"),
            func.coalesce(func.sum(UsageEvent.tool_calls), 0).label("total_tool_calls"),
        )
        .where(UsageEvent.user_id == user_id, UsageEvent.created_at >= start)
    )
    if course_id:
        q = q.where(UsageEvent.course_id == course_id)

    result = await db.execute(q)
    row = result.one()

    return {
        "period": period,
        "total_calls": row.total_calls,
        "total_input_tokens": row.total_input_tokens,
        "total_output_tokens": row.total_output_tokens,
        "total_cost_usd": round(float(row.total_cost_usd), 4),
        "total_tool_calls": row.total_tool_calls,
    }


async def get_usage_by_agent(
    db: AsyncSession,
    user_id: uuid.UUID,
    days: int = 30,
) -> list[dict]:
    """Get usage breakdown by agent for the last N days."""
    start = datetime.now(timezone.utc) - timedelta(days=days)

    result = await db.execute(
        select(
            UsageEvent.agent_name,
            func.count(UsageEvent.id).label("calls"),
            func.coalesce(func.sum(UsageEvent.input_tokens), 0).label("input_tokens"),
            func.coalesce(func.sum(UsageEvent.output_tokens), 0).label("output_tokens"),
            func.coalesce(func.sum(UsageEvent.estimated_cost_usd), 0).label("cost_usd"),
        )
        .where(UsageEvent.user_id == user_id, UsageEvent.created_at >= start)
        .group_by(UsageEvent.agent_name)
        .order_by(func.sum(UsageEvent.estimated_cost_usd).desc())
    )

    return [
        {
            "agent_name": row.agent_name or "unknown",
            "calls": row.calls,
            "input_tokens": row.input_tokens,
            "output_tokens": row.output_tokens,
            "cost_usd": round(float(row.cost_usd), 4),
        }
        for row in result.all()
    ]


async def get_usage_by_course(
    db: AsyncSession,
    user_id: uuid.UUID,
    days: int = 30,
) -> list[dict]:
    """Get usage breakdown by course for the last N days."""
    start = datetime.now(timezone.utc) - timedelta(days=days)

    result = await db.execute(
        select(
            UsageEvent.course_id,
            func.count(UsageEvent.id).label("calls"),
            func.coalesce(func.sum(UsageEvent.estimated_cost_usd), 0).label("cost_usd"),
            func.coalesce(func.sum(UsageEvent.input_tokens + UsageEvent.output_tokens), 0).label("total_tokens"),
        )
        .where(UsageEvent.user_id == user_id, UsageEvent.created_at >= start)
        .group_by(UsageEvent.course_id)
        .order_by(func.sum(UsageEvent.estimated_cost_usd).desc())
    )

    return [
        {
            "course_id": str(row.course_id) if row.course_id else None,
            "calls": row.calls,
            "cost_usd": round(float(row.cost_usd), 4),
            "total_tokens": row.total_tokens,
        }
        for row in result.all()
    ]


async def get_daily_usage(
    db: AsyncSession,
    user_id: uuid.UUID,
    days: int = 30,
) -> list[dict]:
    """Get daily usage time series for charts."""
    start = datetime.now(timezone.utc) - timedelta(days=days)

    # Use func.date() for SQLite compatibility (cast+Date fails with timezone-aware datetimes)
    day_col = func.date(UsageEvent.created_at).label("day")

    result = await db.execute(
        select(
            day_col,
            func.count(UsageEvent.id).label("calls"),
            func.coalesce(func.sum(UsageEvent.estimated_cost_usd), 0).label("cost_usd"),
            func.coalesce(func.sum(UsageEvent.input_tokens + UsageEvent.output_tokens), 0).label("total_tokens"),
        )
        .where(UsageEvent.user_id == user_id, UsageEvent.created_at >= start)
        .group_by(day_col)
        .order_by(day_col)
    )

    return [
        {
            "date": row.day.isoformat() if hasattr(row.day, "isoformat") else str(row.day),
            "calls": row.calls,
            "cost_usd": round(float(row.cost_usd), 4),
            "total_tokens": row.total_tokens,
        }
        for row in result.all()
    ]
