"""Direct, non-Firestore unit tests for `app.persistence.provenance_guard`
— closes every branch `test_provenance_guard.py`'s emulator-backed fuzz
suite doesn't happen to reach, since Gate 1 requires 100% coverage on the
provenance guard specifically, not merely >=80%.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from contracts.errors import ProvenanceMissing
from contracts.graph_types import AgentId, Derivation, NodeId, SourceRef

from app.persistence.provenance_guard import subject_from_raw_document, validate_provenance


class TestValidateProvenanceSourceRefBranches:
    def test_present_but_none_source_ref_on_non_ambiguous_is_rejected(self) -> None:
        """Distinct from an *absent* source_ref attribute (covered by the
        hypothesis fuzz suite): here `source_ref` exists and is explicitly
        `None`, which is only valid for AMBIGUOUS derivation."""
        provenance = SimpleNamespace(
            derivation=Derivation.EXTRACTED,
            source_ref=None,
            confidence=0.9,
            deriving_agent=AgentId("A0"),
            created_at=datetime.now(UTC),
            superseded_at=None,
        )
        with pytest.raises(ProvenanceMissing) as exc_info:
            validate_provenance(SimpleNamespace(id=NodeId("n1"), provenance=provenance))
        assert "source_ref" in exc_info.value.missing_fields

    def test_present_and_populated_source_ref_is_accepted(self) -> None:
        provenance = SimpleNamespace(
            derivation=Derivation.EXTRACTED,
            source_ref=SourceRef(source_document_id=NodeId("doc-1"), region="p1"),
            confidence=0.9,
            deriving_agent=AgentId("A0"),
            created_at=datetime.now(UTC),
            superseded_at=None,
        )
        validate_provenance(SimpleNamespace(id=NodeId("n1"), provenance=provenance))  # does not raise


class TestSubjectFromRawDocument:
    def test_raw_document_is_none(self) -> None:
        subject = subject_from_raw_document("doc-1", None)
        with pytest.raises(ProvenanceMissing):
            validate_provenance(subject)

    def test_raw_document_missing_provenance_key(self) -> None:
        subject = subject_from_raw_document("doc-1", {"display_name": "no provenance key at all"})
        with pytest.raises(ProvenanceMissing):
            validate_provenance(subject)

    def test_raw_document_with_provenance_none(self) -> None:
        subject = subject_from_raw_document("doc-1", {"provenance": None})
        with pytest.raises(ProvenanceMissing):
            validate_provenance(subject)

    def test_raw_document_with_malformed_non_dict_provenance(self) -> None:
        subject = subject_from_raw_document("doc-1", {"provenance": "not-a-dict"})
        with pytest.raises(ProvenanceMissing):
            validate_provenance(subject)

    def test_raw_document_with_complete_provenance_dict_is_accepted(self) -> None:
        subject = subject_from_raw_document(
            "doc-1",
            {
                "provenance": {
                    "derivation": "extracted",
                    "source_ref": {"source_document_id": "doc-0", "region": "p1"},
                    "confidence": 0.9,
                    "deriving_agent": "A0",
                    "created_at": datetime.now(UTC),
                    "superseded_at": None,
                }
            },
        )
        validate_provenance(subject)  # does not raise

    def test_raw_document_with_ambiguous_derivation_and_none_source_ref_is_accepted(self) -> None:
        subject = subject_from_raw_document(
            "doc-1",
            {
                "provenance": {
                    "derivation": "ambiguous",
                    "source_ref": None,
                    "confidence": 0.5,
                    "deriving_agent": "A0",
                    "created_at": datetime.now(UTC),
                    "superseded_at": None,
                }
            },
        )
        validate_provenance(subject)  # does not raise
