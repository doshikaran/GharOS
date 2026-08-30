"""DEBT-013 repayment proof (Phase 15, E2).

`app.agents.intention_action.intention_capture_agent` used to carry a
byte-for-byte private copy of the staleness rule (`_is_stale` plus its
`_STALE_*` / `_TERMINAL_STATUSES` constants) because E1, extracting the
shared `app.solvers.staleness` module in Phase 14 (ADR-021), had no write
access to this E2-owned file to redirect the call site. Phase 15 removes
the private copy: A22 now imports `app.solvers.staleness.is_stale`.

This module is the equivalence net that lets the duplication stay gone: a
table of obligations spanning every branch of the rule (terminal status,
`due_at` grace boundary, `must_start_by`, no-deadline untouched window,
recently-touched), asserting the agent's `StaleObligationDetection` and a
direct `app.solvers.staleness.is_stale` call agree on every field for
every row. The pre-existing `test_intention_capture_agent.py::
TestStaleObligationDetection` cases (unchanged) remain the behavioural
spec; this file proves the two entry points cannot silently diverge.
"""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime, timedelta

from contracts.graph_types import NodeId, Obligation, ObligationDerivation, ObligationStatus

from app.agents.intention_action.intention_capture_agent import IntentionCaptureAgent
from app.reasoning.gemini_client import GeminiClient
from app.solvers.staleness import is_stale
from tests.conftest import make_provenance

from ._gemini_fakes import FakeModels, fake_router

_NOW = datetime(2026, 8, 30, tzinfo=UTC)


def _agent() -> IntentionCaptureAgent:
    fake_models = FakeModels(texts=["staleness detection never calls the model"])
    return IntentionCaptureAgent(gemini_client=GeminiClient(router=fake_router(fake_models)))


def _obligation(
    *,
    status: ObligationStatus = ObligationStatus.DERIVED,
    due_at: datetime | None = None,
    must_start_by: datetime | None = None,
    created_at: datetime = _NOW,
) -> Obligation:
    return Obligation(
        id=NodeId("obligation-under-test"),
        provenance=dataclasses.replace(make_provenance(), created_at=created_at),
        title="Call the dentist",
        obligation_type="health_admin",
        due_at=due_at,
        must_start_by=must_start_by,
        effort_estimate_minutes=15,
        status=status,
        stated_or_implied=ObligationDerivation.STATED,
    )


# One row per meaningful branch / boundary of the rule.
_TABLE: tuple[tuple[str, Obligation], ...] = (
    ("no deadline, fresh", _obligation(created_at=_NOW - timedelta(days=2))),
    ("no deadline, one day short of threshold", _obligation(created_at=_NOW - timedelta(days=20))),
    ("no deadline, exactly at threshold", _obligation(created_at=_NOW - timedelta(days=21))),
    ("no deadline, months untouched", _obligation(created_at=_NOW - timedelta(days=120))),
    ("due_at in the future", _obligation(due_at=_NOW + timedelta(days=3))),
    ("due_at within grace (1 day)", _obligation(due_at=_NOW - timedelta(days=1))),
    ("due_at exactly at grace boundary (3 days)", _obligation(due_at=_NOW - timedelta(days=3))),
    ("due_at well past grace (10 days)", _obligation(due_at=_NOW - timedelta(days=10))),
    ("must_start_by within grace", _obligation(must_start_by=_NOW - timedelta(days=2))),
    ("must_start_by past grace", _obligation(must_start_by=_NOW - timedelta(days=9))),
    (
        "both due_at and must_start_by set (due_at wins)",
        _obligation(due_at=_NOW - timedelta(days=5), must_start_by=_NOW - timedelta(days=40)),
    ),
    (
        "completed, deadline long gone",
        _obligation(status=ObligationStatus.COMPLETED, due_at=_NOW - timedelta(days=400)),
    ),
    (
        "dropped, deadline long gone",
        _obligation(status=ObligationStatus.DROPPED, due_at=_NOW - timedelta(days=400)),
    ),
    (
        "superseded, untouched for a year",
        _obligation(status=ObligationStatus.SUPERSEDED, created_at=_NOW - timedelta(days=365)),
    ),
)


def test_agent_and_solver_agree_on_every_row() -> None:
    agent = _agent()
    for label, obligation in _TABLE:
        solver = is_stale(obligation, now=_NOW)
        detection = agent.detect_stale_obligation(obligation, now=_NOW)

        if not solver.is_stale:
            assert detection is None, f"{label}: solver says not-stale, agent produced {detection!r}"
            continue

        assert detection is not None, f"{label}: solver says stale, agent produced None"
        assert detection.reason == solver.reason, label
        assert detection.days_stale == solver.days_stale, label
        assert detection.threshold_days == solver.threshold_days, label
        assert detection.obligation_id == obligation.id, label
        assert detection.detected_at == _NOW, label


def test_agent_no_longer_defines_a_private_staleness_rule() -> None:
    """The duplication must not creep back: the agent module exposes no
    private staleness rule or thresholds of its own — the canonical
    `app.solvers.staleness` is the only definition."""
    from app.agents.intention_action import intention_capture_agent as mod

    forbidden_names = (
        "_is_stale",
        "_STALE_AFTER_DEADLINE_DAYS",
        "_STALE_NO_DEADLINE_DAYS",
        "_TERMINAL_STATUSES",
    )
    for forbidden in forbidden_names:
        assert not hasattr(mod, forbidden), (
            f"{forbidden} is back in intention_capture_agent — DEBT-013 duplication has re-appeared; "
            "import from app.solvers.staleness instead"
        )
    # The name the agent module now binds for `is_stale` is the canonical
    # solver function object itself, not a private re-definition.
    assert vars(mod).get("is_stale") is is_stale
