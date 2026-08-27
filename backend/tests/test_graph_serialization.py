"""Unit tests for `app.graph.serialization` — the node/edge wire-JSON
envelope builders shared by `/graph/snapshot`, `/graph/stream`, and the
justification endpoint (PHASES.md Phase 6)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from contracts.graph_types import AttendanceRecord, EdgeType, Person

from app.graph.serialization import (
    NODE_TYPE_TAGS,
    build_edge_envelope,
    build_node_envelope,
    json_safe,
    node_label,
)
from app.persistence.collections import NODE_TYPE_TO_COLLECTION


def test_node_type_tags_key_set_matches_collections_registry() -> None:
    """The wire-convention tag table must cover exactly the 17 registered
    node types — same set `app.persistence.collections` uses, since a
    silently-missing entry would 500 on any node of that type reaching
    `/graph/snapshot` or `/graph/stream`."""
    assert set(NODE_TYPE_TAGS.keys()) == set(NODE_TYPE_TO_COLLECTION.keys())


def test_node_type_tags_are_upper_snake_case_class_names() -> None:
    assert NODE_TYPE_TAGS[Person] == "PERSON"


class TestNodeLabel:
    def test_person(self) -> None:
        assert node_label("PERSON", {"display_name": "Priya"}) == "Priya"

    def test_constraint_title_cases_kind(self) -> None:
        assert node_label("CONSTRAINT", {"kind": "dietary"}) == "Dietary constraint"

    def test_obligation(self) -> None:
        assert node_label("OBLIGATION", {"title": "Pick up Aarav"}) == "Pick up Aarav"

    def test_ledger_event(self) -> None:
        label = node_label("LEDGER_EVENT", {"kind": "debit", "currency": "INR", "amount": 2500.0})
        assert label == "debit — INR 2500.0"

    def test_recurring_commitment(self) -> None:
        assert node_label("RECURRING_COMMITMENT", {"label": "Society maintenance"}) == "Society maintenance"

    def test_vendor_with_contact(self) -> None:
        label = node_label("VENDOR", {"category": "grocery", "contacts": ["+91-80000-00002"]})
        assert label == "grocery (+91-80000-00002)"

    def test_vendor_without_contact(self) -> None:
        assert node_label("VENDOR", {"category": "housing", "contacts": []}) == "housing"

    def test_provider(self) -> None:
        assert node_label("PROVIDER", {"name": "Mehta Pharmacy"}) == "Mehta Pharmacy"

    def test_decision(self) -> None:
        assert node_label("DECISION", {"question": "Delivery or pickup?"}) == "Delivery or pickup?"

    def test_branch(self) -> None:
        assert node_label("BRANCH", {"label": "Home delivery"}) == "Home delivery"

    def test_council_position(self) -> None:
        label = node_label("COUNCIL_POSITION", {"held_by_agent": "A42", "stance": "supports"})
        assert label == "A42 — supports"

    def test_outcome_truncates_long_text(self) -> None:
        predicted = "x" * 100
        label = node_label("OUTCOME", {"predicted": predicted})
        assert len(label) == 60
        assert label.endswith("…")

    def test_outcome_short_text_untouched(self) -> None:
        assert node_label("OUTCOME", {"predicted": "Delivered on time"}) == "Delivered on time"

    def test_source_document_with_type(self) -> None:
        label = node_label("SOURCE_DOCUMENT", {"channel": "email", "document_type": "RECEIPT"})
        assert label == "email document (RECEIPT)"

    def test_source_document_without_type(self) -> None:
        label = node_label("SOURCE_DOCUMENT", {"channel": "sms", "document_type": None})
        assert label == "sms document"

    def test_action_record(self) -> None:
        assert node_label("ACTION_RECORD", {"action_type": "send_reminder"}) == "send_reminder"

    def test_approval_request(self) -> None:
        label = node_label("APPROVAL_REQUEST", {"proposed_action_summary": "Request delivery"})
        assert label == "Request delivery"

    def test_purchase_item(self) -> None:
        assert node_label("PURCHASE_ITEM", {"description": "Milk 1L"}) == "Milk 1L"

    def test_pattern_truncates(self) -> None:
        description = "y" * 80
        label = node_label("PATTERN", {"description": description})
        assert len(label) == 60

    def test_attendance_record(self) -> None:
        assert node_label("ATTENDANCE_RECORD", {"month": "2026-08"}) == "2026-08 attendance"

    def test_unknown_tag_raises(self) -> None:
        with pytest.raises(ValueError, match="no label dispatcher"):
            node_label("NOT_A_REAL_TYPE", {})

    def test_covers_all_seventeen_tags(self) -> None:
        """Every tag in NODE_TYPE_TAGS must have a working label
        dispatcher — a KeyError here would mean a real /graph/snapshot 500
        for that node type."""
        minimal_fields_by_tag: dict[str, dict[str, object]] = {
            "PERSON": {"display_name": "x"},
            "CONSTRAINT": {"kind": "dietary"},
            "OBLIGATION": {"title": "x"},
            "LEDGER_EVENT": {"kind": "debit", "currency": "INR", "amount": 1.0},
            "RECURRING_COMMITMENT": {"label": "x"},
            "VENDOR": {"category": "x", "contacts": []},
            "PROVIDER": {"name": "x"},
            "DECISION": {"question": "x"},
            "BRANCH": {"label": "x"},
            "COUNCIL_POSITION": {"held_by_agent": "A1", "stance": "supports"},
            "OUTCOME": {"predicted": "x"},
            "SOURCE_DOCUMENT": {"channel": "email", "document_type": None},
            "ACTION_RECORD": {"action_type": "x"},
            "APPROVAL_REQUEST": {"proposed_action_summary": "x"},
            "PURCHASE_ITEM": {"description": "x"},
            "PATTERN": {"description": "x"},
            "ATTENDANCE_RECORD": {"month": "2026-08"},
        }
        assert set(minimal_fields_by_tag.keys()) == set(NODE_TYPE_TAGS.values())
        for tag, fields in minimal_fields_by_tag.items():
            assert isinstance(node_label(tag, fields), str)


class TestJsonSafe:
    def test_datetime_becomes_isoformat(self) -> None:
        dt = datetime(2026, 8, 19, 10, 0, tzinfo=UTC)
        assert json_safe(dt) == dt.isoformat()

    def test_nested_dict_and_list(self) -> None:
        dt = datetime(2026, 8, 19, 10, 0, tzinfo=UTC)
        value = {"a": [dt, {"b": dt}], "c": 1}
        result = json_safe(value)
        assert result == {"a": [dt.isoformat(), {"b": dt.isoformat()}], "c": 1}

    def test_primitives_pass_through(self) -> None:
        assert json_safe("x") == "x"
        assert json_safe(1) == 1
        assert json_safe(1.5) == 1.5
        assert json_safe(True) is True
        assert json_safe(None) is None

    def test_tuple_becomes_list(self) -> None:
        assert json_safe((1, 2, 3)) == [1, 2, 3]


class TestBuildNodeEnvelope:
    def test_full_shape_with_source_ref(self) -> None:
        created_at = datetime(2026, 8, 19, 10, 0, tzinfo=UTC)
        raw = {
            "id": "person-priya",
            "provenance": {
                "derivation": "extracted",
                "source_ref": {"source_document_id": "doc-x", "region": "120-340"},
                "confidence": 0.9,
                "deriving_agent": "A7",
                "created_at": created_at,
                "superseded_at": None,
            },
            "display_name": "Priya",
            "aliases": ["Priya Sharma"],
            "role": "adult",
            "_version_seq": 3,
        }
        envelope = build_node_envelope(Person, "person-priya", raw)
        assert envelope["id"] == "person-priya"
        assert envelope["type"] == "PERSON"
        assert envelope["label"] == "Priya"
        assert envelope["derivation"] == "extracted"
        assert envelope["confidence"] == 0.9
        assert envelope["source_document_id"] == "doc-x"
        assert envelope["region"] == "120-340"
        assert envelope["created_at"] == created_at.isoformat()
        assert "id" not in envelope["fields"]
        assert "provenance" not in envelope["fields"]
        assert "_version_seq" not in envelope["fields"]
        assert envelope["fields"]["display_name"] == "Priya"
        assert envelope["fields"]["aliases"] == ["Priya Sharma"]

    def test_none_source_ref_yields_none_source_fields(self) -> None:
        from contracts.graph_types import Pattern

        created_at = datetime(2026, 8, 19, 10, 0, tzinfo=UTC)
        raw = {
            "id": "pattern-1",
            "provenance": {
                "derivation": "ambiguous",
                "source_ref": None,
                "confidence": 0.6,
                "deriving_agent": "A7",
                "created_at": created_at,
                "superseded_at": None,
            },
            "description": "Grocery runs pattern",
            "support_count": 2,
            "contributing_outcome_ids": ["outcome-1"],
        }
        envelope = build_node_envelope(Pattern, "pattern-1", raw)
        assert envelope["source_document_id"] is None
        assert envelope["region"] is None
        assert envelope["derivation"] == "ambiguous"

    def test_attendance_record_does_not_raise(self) -> None:
        """DEBT-004/ADR-013's explicit failure mode: an AttendanceRecord
        reaching this envelope builder with no NODE_TYPE_TAGS/label-dispatch
        entry raises `ValueError` and would break `/graph/snapshot` and
        `/graph/stream` the moment real attendance data exists — this
        proves the wiring is complete, not just present in the tag table."""
        created_at = datetime(2026, 8, 19, 10, 0, tzinfo=UTC)
        raw = {
            "id": "attendance-1",
            "provenance": {
                "derivation": "extracted",
                "source_ref": {"source_document_id": "doc-register", "region": "whole-document"},
                "confidence": 0.7,
                "deriving_agent": "A7",
                "created_at": created_at,
                "superseded_at": None,
            },
            "staff_person_id": "person-maya",
            "month": "2026-08",
            "days_present": 22,
            "days_absent": 2,
            "days_on_leave": 1,
            "total_days_in_period": 25,
            "daily_marks": {"01": "present", "02": "absent"},
            "advance_notations": ["₹2,000 advance, 12 Aug"],
        }
        envelope = build_node_envelope(AttendanceRecord, "attendance-1", raw)
        assert envelope["type"] == "ATTENDANCE_RECORD"
        assert envelope["label"] == "2026-08 attendance"
        assert envelope["fields"]["staff_person_id"] == "person-maya"


class TestBuildEdgeEnvelope:
    @pytest.mark.parametrize(
        "edge_type",
        [EdgeType.CONFLICTS_WITH.value, EdgeType.VIOLATES.value, EdgeType.CONTRADICTS.value],
    )
    def test_conflict_edge_types_marked(self, edge_type: str) -> None:
        raw = {
            "id": "edge-1",
            "provenance": {
                "derivation": "inferred",
                "source_ref": None,
                "confidence": 0.8,
                "deriving_agent": "A7",
                "created_at": datetime(2026, 8, 19, tzinfo=UTC),
                "superseded_at": None,
            },
            "edge_type": edge_type,
            "from_id": "a",
            "to_id": "b",
            "metadata": {},
        }
        envelope = build_edge_envelope("edge-1", raw)
        assert envelope["is_conflict"] is True
        assert envelope["type"] == edge_type

    def test_non_conflict_edge_type_not_marked(self) -> None:
        raw = {
            "id": "edge-2",
            "provenance": {
                "derivation": "extracted",
                "source_ref": None,
                "confidence": 0.9,
                "deriving_agent": "A7",
                "created_at": datetime(2026, 8, 19, tzinfo=UTC),
                "superseded_at": None,
            },
            "edge_type": "implies",
            "from_id": "doc-x",
            "to_id": "obligation-y",
            "metadata": {},
        }
        envelope = build_edge_envelope("edge-2", raw)
        assert envelope["is_conflict"] is False
        assert envelope["from_id"] == "doc-x"
        assert envelope["to_id"] == "obligation-y"
