"""Helpers for compact provenance payloads used by chat and durable tasks."""

from __future__ import annotations

from typing import Any


def build_provenance(
    *,
    workflow: str | None = None,
    scene: str | None = None,
    content_refs: list[dict[str, Any]] | None = None,
    content_count: int | None = None,
    memory_count: int = 0,
    tool_names: list[str] | None = None,
    action_count: int = 0,
    source_labels: list[str] | None = None,
    generated: bool = True,
    user_input: bool = False,
    scheduler_trigger: str | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    refs = [ref for ref in (content_refs or []) if isinstance(ref, dict)]
    tools = [tool for tool in (tool_names or []) if tool]
    labels = list(source_labels or [])

    if workflow and "workflow" not in labels:
        labels.append("workflow")
    if generated and "generated" not in labels:
        labels.append("generated")
    if user_input and "user_input" not in labels:
        labels.append("user_input")
    if refs and "course" not in labels:
        labels.append("course")
    if memory_count > 0 and "memory" not in labels:
        labels.append("memory")

    payload: dict[str, Any] = {
        "scene": scene,
        "workflow": workflow,
        "source_labels": labels,
        "generated": generated,
        "user_input": user_input,
        "content_count": content_count if content_count is not None else len(refs),
        "content_refs": refs[:5],
        "content_titles": [ref.get("title") for ref in refs[:5] if ref.get("title")],
        "memory_count": memory_count,
        "tool_count": len(tools),
        "tool_names": tools[:5],
        "action_count": action_count,
    }
    if scheduler_trigger:
        payload["scheduler_trigger"] = scheduler_trigger
    if extra:
        payload.update(extra)
    return payload


def merge_provenance(existing: dict[str, Any] | None, updates: dict[str, Any] | None) -> dict[str, Any] | None:
    if not existing and not updates:
        return None

    merged: dict[str, Any] = dict(existing or {})
    incoming = dict(updates or {})
    for key, value in incoming.items():
        if value is None:
            continue
        if key == "source_labels":
            merged[key] = sorted({*(merged.get(key) or []), *value})
            continue
        merged[key] = value
    return merged
