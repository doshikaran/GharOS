"""Shared JSON-response parsing for the LLM-backed Outbound Concierge
agents (A50, A52, A53, A55 — E2's half of `backend/app/agents/concierge/`).
Mirrors `app.agents.intention_action.json_utils`/`app.agents.
fair_allocator.json_utils`'s role for their own packages deliberately as
a separate module, not a shared import, so this package's typed-error
handling (`errors.ModelResponseMalformed`) stays uniform across every
caller.

Every prompt in `backend/app/prompts/a5{0,2,3,5}_*/` demands a single
JSON object with no markdown fences, but real model output occasionally
wraps the object in a ```json ... ``` fence anyway — this module strips
that defensively before parsing, and raises a typed error (never returns
a best-guess partial structure) when the result still is not valid JSON.
"""

from __future__ import annotations

import json
import re

from contracts.graph_types import AgentId

from .errors import ModelResponseMalformed

_FENCE_PATTERN = re.compile(r"^```(?:json)?\s*\n?(.*?)\n?```$", re.DOTALL)


def parse_json_response(*, agent_id: AgentId, text: str) -> dict[str, object]:
    """Parses one LLM response as a single JSON object.

    Args:
        agent_id: the calling agent's id, for error context.
        text: the raw model response text.

    Returns:
        The parsed JSON object as a `dict`.

    Raises:
        ModelResponseMalformed: `text` (after stripping an optional
            markdown code fence) is not valid JSON, or does not parse to
            a JSON object (e.g. a bare array or scalar).
    """
    candidate = text.strip()
    fence_match = _FENCE_PATTERN.match(candidate)
    if fence_match is not None:
        candidate = fence_match.group(1).strip()

    try:
        parsed = json.loads(candidate)
    except json.JSONDecodeError as exc:
        raise ModelResponseMalformed(agent_id=agent_id, reason=f"invalid JSON: {exc}", raw_text=text) from exc

    if not isinstance(parsed, dict):
        raise ModelResponseMalformed(
            agent_id=agent_id, reason=f"expected a JSON object, got {type(parsed).__name__}", raw_text=text
        )
    return parsed


def _type_mismatch(
    *, agent_id: AgentId, obj: dict[str, object], key: str, expected: str, value: object
) -> ModelResponseMalformed:
    return ModelResponseMalformed(
        agent_id=agent_id,
        reason=f"expected {expected} field '{key}', got {type(value).__name__}",
        raw_text=str(obj),
    )


def require_str(obj: dict[str, object], key: str, *, agent_id: AgentId) -> str:
    value = obj.get(key)
    if not isinstance(value, str):
        raise _type_mismatch(agent_id=agent_id, obj=obj, key=key, expected="string", value=value)
    return value


def require_float(
    obj: dict[str, object], key: str, *, agent_id: AgentId, default: float | None = None
) -> float:
    value = obj.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise _type_mismatch(agent_id=agent_id, obj=obj, key=key, expected="numeric", value=value)
    return float(value)


def require_bool(obj: dict[str, object], key: str, *, agent_id: AgentId, default: bool | None = None) -> bool:
    value = obj.get(key, default)
    if not isinstance(value, bool):
        raise _type_mismatch(agent_id=agent_id, obj=obj, key=key, expected="boolean", value=value)
    return value


def require_list(obj: dict[str, object], key: str, *, agent_id: AgentId) -> list[object]:
    value = obj.get(key, [])
    if value is None:
        value = []
    if not isinstance(value, list):
        raise _type_mismatch(agent_id=agent_id, obj=obj, key=key, expected="array", value=value)
    return value


def optional_str(obj: dict[str, object], key: str) -> str | None:
    value = obj.get(key)
    return value if isinstance(value, str) else None


__all__ = [
    "optional_str",
    "parse_json_response",
    "require_bool",
    "require_float",
    "require_list",
    "require_str",
]
