"""Tests for shared utility modules: serializers, text_utils, datetime_utils."""

import uuid
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock

from libs.datetime_utils import as_utc, utcnow
from libs.text_utils import strip_code_fences
from utils.serializers import _convert_value, serialize_model


# ---------------------------------------------------------------------------
# datetime_utils
# ---------------------------------------------------------------------------

class TestAsUtc:
    def test_naive_datetime_gets_utc(self):
        dt = datetime(2026, 1, 1, 12, 0)
        result = as_utc(dt)
        assert result.tzinfo == timezone.utc
        assert result.hour == 12

    def test_utc_datetime_unchanged(self):
        dt = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
        result = as_utc(dt)
        assert result == dt

    def test_non_utc_converted(self):
        eastern = timezone(timedelta(hours=-5))
        dt = datetime(2026, 1, 1, 12, 0, tzinfo=eastern)
        result = as_utc(dt)
        assert result.tzinfo == timezone.utc
        assert result.hour == 17


class TestUtcnow:
    def test_returns_utc(self):
        result = utcnow()
        assert result.tzinfo == timezone.utc

    def test_recent(self):
        before = datetime.now(timezone.utc)
        result = utcnow()
        after = datetime.now(timezone.utc)
        assert before <= result <= after


# ---------------------------------------------------------------------------
# text_utils
# ---------------------------------------------------------------------------

class TestStripCodeFences:
    def test_no_fences(self):
        assert strip_code_fences('hello') == 'hello'

    def test_json_fence(self):
        text = '```json\n{"key": "value"}\n```'
        assert strip_code_fences(text) == '{"key": "value"}'

    def test_plain_fence(self):
        text = '```\nsome code\n```'
        assert strip_code_fences(text) == 'some code'

    def test_fence_no_newline(self):
        text = '```content```'
        assert strip_code_fences(text) == 'content'

    def test_whitespace_stripped(self):
        text = '  ```json\n  data  \n```  '
        assert strip_code_fences(text) == 'data'


# ---------------------------------------------------------------------------
# serializers
# ---------------------------------------------------------------------------

class TestConvertValue:
    def test_uuid_to_string(self):
        uid = uuid.uuid4()
        assert _convert_value(uid) == str(uid)

    def test_datetime_to_isoformat(self):
        dt = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
        assert _convert_value(dt) == dt.isoformat()

    def test_plain_value_passthrough(self):
        assert _convert_value(42) == 42
        assert _convert_value("hello") == "hello"
        assert _convert_value(None) is None


class TestSerializeModel:
    def test_explicit_fields(self):
        obj = MagicMock()
        obj.name = "test"
        obj.value = 42
        result = serialize_model(obj, fields=["name", "value"])
        assert result == {"name": "test", "value": 42}

    def test_exclude_fields(self):
        obj = MagicMock()
        obj.name = "test"
        obj.secret = "hidden"  # pragma: allowlist secret
        result = serialize_model(obj, fields=["name", "secret"], exclude={"secret"})
        assert "secret" not in result
        assert result["name"] == "test"

    def test_extra_merged(self):
        obj = MagicMock()
        obj.name = "test"
        result = serialize_model(obj, fields=["name"], extra={"count": 5})
        assert result["name"] == "test"
        assert result["count"] == 5

    def test_auto_discover_columns(self):
        col1 = MagicMock()
        col1.key = "id"
        col2 = MagicMock()
        col2.key = "name"
        table = MagicMock()
        table.columns = [col1, col2]
        obj = MagicMock()
        obj.__table__ = table
        obj.id = uuid.uuid4()
        obj.name = "test"
        result = serialize_model(obj)
        assert result["id"] == str(obj.id)
        assert result["name"] == "test"

    def test_fallback_to_dict_keys(self):
        obj = MagicMock(spec=[])
        obj.__dict__ = {"name": "test", "value": 1, "_sa_state": "internal"}
        # Remove __table__ to trigger fallback
        if hasattr(obj, '__table__'):
            del obj.__table__
        result = serialize_model(obj)
        assert "name" in result
        assert "_sa_state" not in result
