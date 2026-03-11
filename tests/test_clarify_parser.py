"""Tests for _parse_clarify_inputs in the orchestrator module."""

import json
import pytest
from services.agent.orchestrator import _parse_clarify_inputs


class TestParseClarifyInputsJSON:
    """Test JSON format parsing."""

    def test_json_format(self):
        msg = json.dumps({"type": "clarify", "key": "deadline", "value": "2 weeks"})
        assert _parse_clarify_inputs(msg) == {"deadline": "2 weeks"}

    def test_json_special_chars_in_value(self):
        msg = json.dumps({"type": "clarify", "key": "scope", "value": "math:algebra"})
        assert _parse_clarify_inputs(msg) == {"scope": "math:algebra"}

    def test_invalid_json_returns_empty(self):
        assert _parse_clarify_inputs("{not valid json}") == {}

    def test_json_wrong_type_field_returns_empty(self):
        msg = json.dumps({"type": "other", "key": "deadline", "value": "2 weeks"})
        assert _parse_clarify_inputs(msg) == {}


class TestParseClarifyInputsLegacy:
    """Test legacy [CLARIFY:key:value] format parsing."""

    def test_legacy_format(self):
        assert _parse_clarify_inputs("[CLARIFY:deadline:2 weeks]") == {"deadline": "2 weeks"}

    def test_legacy_colon_in_value(self):
        assert _parse_clarify_inputs("[CLARIFY:deadline:2026-03-15]") == {"deadline": "2026-03-15"}


class TestParseClarifyInputsEdgeCases:
    """Test edge cases and fallback behaviour."""

    def test_regular_message_returns_empty(self):
        assert _parse_clarify_inputs("Hello, how are you?") == {}

    def test_whitespace_handling(self):
        msg = "  " + json.dumps({"type": "clarify", "key": "deadline", "value": "2 weeks"}) + "  "
        assert _parse_clarify_inputs(msg) == {"deadline": "2 weeks"}
