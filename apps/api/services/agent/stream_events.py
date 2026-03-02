"""Typed stream event system for agent communication.

Replaces raw dict events with structured, typed dataclasses.
"""

import json
from dataclasses import dataclass, field, asdict
from typing import Any, Literal


@dataclass
class StreamEvent:
    """Typed event yielded during agent execution.

    Event types:
    - content: Text content chunk for the user
    - thought: Internal agent reasoning (not shown to user)
    - tool_start: Tool execution beginning
    - tool_result: Tool execution complete
    - action: UI action trigger
    - plan_step: Plan progress update
    - status: Phase/status change
    - done: Stream complete
    - error: Error occurred
    """

    type: Literal[
        "content", "thought", "tool_start", "tool_result",
        "action", "plan_step", "status", "done", "error"
    ]
    data: dict[str, Any] = field(default_factory=dict)

    def to_sse(self) -> dict:
        """Convert to SSE-compatible format for the orchestrator."""
        if self.type == "content":
            return {"event": "message", "data": json.dumps({"content": self.data.get("content", "")})}
        elif self.type == "tool_start":
            event_data = {"status": "running", "tool": self.data.get("tool", "")}
            if self.data.get("explanation"):
                event_data["explanation"] = self.data["explanation"]
            return {"event": "tool_status", "data": json.dumps(event_data)}
        elif self.type == "tool_result":
            event_data = {"status": "complete", "tool": self.data.get("tool", "")}
            if self.data.get("explanation"):
                event_data["explanation"] = self.data["explanation"]
            return {"event": "tool_status", "data": json.dumps(event_data)}
        elif self.type == "action":
            return {"event": "action", "data": json.dumps(self.data)}
        elif self.type == "plan_step":
            return {"event": "plan_step", "data": json.dumps(self.data)}
        elif self.type == "status":
            return {"event": "status", "data": json.dumps(self.data)}
        elif self.type == "done":
            return {"event": "done", "data": json.dumps(self.data)}
        elif self.type == "error":
            return {"event": "error", "data": json.dumps(self.data)}
        else:
            return {"event": self.type, "data": json.dumps(self.data)}

    def to_dict(self) -> dict:
        """Convert to legacy dict format for backward compatibility."""
        return {"type": self.type, **self.data}

    @classmethod
    def content(cls, text: str) -> "StreamEvent":
        return cls(type="content", data={"content": text})

    @classmethod
    def thought(cls, text: str) -> "StreamEvent":
        return cls(type="thought", data={"content": text})

    @classmethod
    def tool_start(cls, tool: str, input_data: str = "", explanation: str = "") -> "StreamEvent":
        d = {"tool": tool, "input": input_data}
        if explanation:
            d["explanation"] = explanation
        return cls(type="tool_start", data=d)

    @classmethod
    def tool_result(cls, tool: str, result: str = "", explanation: str = "") -> "StreamEvent":
        d = {"tool": tool, "result": result}
        if explanation:
            d["explanation"] = explanation
        return cls(type="tool_result", data=d)

    @classmethod
    def action(cls, action_type: str, **kwargs) -> "StreamEvent":
        return cls(type="action", data={"type": action_type, **kwargs})

    @classmethod
    def status(cls, phase: str, **kwargs) -> "StreamEvent":
        return cls(type="status", data={"phase": phase, **kwargs})

    @classmethod
    def done(cls, **kwargs) -> "StreamEvent":
        return cls(type="done", data=kwargs)

    @classmethod
    def error(cls, message: str) -> "StreamEvent":
        return cls(type="error", data={"message": message})
