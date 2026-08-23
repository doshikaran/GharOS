"""Tests for `app.agents.intake.json_utils` — the shared response-parsing
helpers every LLM-backed intake agent uses.

`test_require_list_treats_null_as_empty` is a regression test for a real
bug this phase's `live_gcp` suite caught: a real Gemini response returned
JSON `null` (not `[]`) for `candidate_person_ids` on a confident,
unambiguous A5 match — `require_list` must treat that the same as an
empty list, not raise `ModelResponseMalformed`.
"""

from __future__ import annotations

import pytest
from contracts.graph_types import AgentId

from app.agents.intake.errors import ModelResponseMalformed
from app.agents.intake.json_utils import (
    parse_json_response,
    require_bool,
    require_float,
    require_list,
    require_str,
)

_AGENT = AgentId("A2")


class TestParseJsonResponse:
    def test_strips_markdown_fence(self) -> None:
        parsed = parse_json_response(agent_id=_AGENT, text='```json\n{"a": 1}\n```')
        assert parsed == {"a": 1}

    def test_plain_json_object(self) -> None:
        assert parse_json_response(agent_id=_AGENT, text='{"a": 1}') == {"a": 1}

    def test_invalid_json_raises(self) -> None:
        with pytest.raises(ModelResponseMalformed):
            parse_json_response(agent_id=_AGENT, text="not json")

    def test_bare_array_raises(self) -> None:
        with pytest.raises(ModelResponseMalformed):
            parse_json_response(agent_id=_AGENT, text="[1, 2, 3]")


class TestRequireList:
    def test_present_list_returned(self) -> None:
        assert require_list({"k": [1, 2]}, "k", agent_id=_AGENT) == [1, 2]

    def test_missing_key_defaults_empty(self) -> None:
        assert require_list({}, "k", agent_id=_AGENT) == []

    def test_null_treated_as_empty_not_malformed(self) -> None:
        """Regression test — see module docstring."""
        assert require_list({"k": None}, "k", agent_id=_AGENT) == []

    def test_wrong_type_raises(self) -> None:
        with pytest.raises(ModelResponseMalformed):
            require_list({"k": "not a list"}, "k", agent_id=_AGENT)


class TestRequireStr:
    def test_present(self) -> None:
        assert require_str({"k": "v"}, "k", agent_id=_AGENT) == "v"

    def test_missing_raises(self) -> None:
        with pytest.raises(ModelResponseMalformed):
            require_str({}, "k", agent_id=_AGENT)

    def test_wrong_type_raises(self) -> None:
        with pytest.raises(ModelResponseMalformed):
            require_str({"k": 5}, "k", agent_id=_AGENT)


class TestRequireFloat:
    def test_int_accepted(self) -> None:
        assert require_float({"k": 5}, "k", agent_id=_AGENT) == 5.0

    def test_bool_rejected(self) -> None:
        """bool is a subclass of int in Python — must not silently pass
        as a numeric field."""
        with pytest.raises(ModelResponseMalformed):
            require_float({"k": True}, "k", agent_id=_AGENT)

    def test_default_used_when_missing(self) -> None:
        assert require_float({}, "k", agent_id=_AGENT, default=0.5) == 0.5


class TestRequireBool:
    def test_present(self) -> None:
        assert require_bool({"k": True}, "k", agent_id=_AGENT) is True

    def test_wrong_type_raises(self) -> None:
        with pytest.raises(ModelResponseMalformed):
            require_bool({"k": "true"}, "k", agent_id=_AGENT)
