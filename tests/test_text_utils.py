"""Tests for libs/text_utils.py — LLM output parsing utilities."""

import pytest
from libs.text_utils import strip_code_fences, parse_llm_json


class TestStripCodeFences:
    def test_removes_json_fences(self):
        text = '```json\n{"key": "value"}\n```'
        assert strip_code_fences(text) == '{"key": "value"}'

    def test_removes_plain_fences(self):
        text = '```\n[1, 2, 3]\n```'
        assert strip_code_fences(text) == "[1, 2, 3]"

    def test_passes_through_plain_text(self):
        text = '{"key": "value"}'
        assert strip_code_fences(text) == '{"key": "value"}'

    def test_strips_whitespace(self):
        text = '  ```json\n{"a": 1}\n```  '
        assert strip_code_fences(text) == '{"a": 1}'


class TestParseLlmJson:
    def test_parses_clean_json(self):
        assert parse_llm_json('{"key": "value"}') == {"key": "value"}

    def test_parses_json_with_code_fences(self):
        text = '```json\n{"key": "value"}\n```'
        assert parse_llm_json(text) == {"key": "value"}

    def test_parses_json_array(self):
        assert parse_llm_json("[1, 2, 3]") == [1, 2, 3]

    def test_extracts_json_from_surrounding_text(self):
        text = 'Here is the result:\n{"answer": 42}\nEnd of response.'
        assert parse_llm_json(text) == {"answer": 42}

    def test_extracts_array_from_surrounding_text(self):
        text = 'The questions are:\n[{"q": "What?"}]\nDone.'
        result = parse_llm_json(text)
        assert isinstance(result, list)
        assert result[0]["q"] == "What?"

    def test_returns_default_on_unparseable(self):
        assert parse_llm_json("no json here", default="fallback") == "fallback"

    def test_returns_none_default(self):
        assert parse_llm_json("just text") is None

    def test_handles_empty_string(self):
        assert parse_llm_json("", default=[]) == []

    def test_handles_nested_json(self):
        text = '{"outer": {"inner": [1, 2]}}'
        result = parse_llm_json(text)
        assert result["outer"]["inner"] == [1, 2]

    def test_prefers_direct_parse_over_extraction(self):
        # When the entire string is valid JSON, use it directly
        text = '{"a": 1}'
        assert parse_llm_json(text) == {"a": 1}
