"""`app.persistence.region_resolver` (PHASES.md Phase 3 work item:
"source-document storage with region references") — proves a
`contracts.graph_types.SourceRef` genuinely resolves to real payload bytes
plus a validated region locator, for both documented conventions
(byte-offset span, page+bbox), and that every failure path raises its
documented typed error rather than fabricating a result.

Uses the real Firestore emulator (`writer`/`reader`/`store` fixtures from
`conftest.py`) for the SOURCE_DOCUMENT node side, and a real
`LocalFilesystemPayloadStore` (via `tmp_path`) for the payload side — no
mocks, matching gharos-standards' integration-test rule.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from contracts.graph_types import NodeId, SourceDocument, SourceRef

from app.graph.reader import FirestoreGraphReader
from app.graph.writer import FirestoreGraphWriter
from app.persistence.errors import (
    MalformedRegion,
    RawPayloadNotFound,
    RegionOutOfBounds,
    SourceDocumentNotFound,
)
from app.persistence.raw_payload_store import LocalFilesystemPayloadStore
from app.persistence.region_resolver import (
    BoundingBox,
    PageBoundingBoxRegion,
    TextSpanRegion,
    parse_region,
    resolve_source_ref,
)
from tests.conftest import make_provenance


@pytest.fixture
def payload_store(tmp_path: Path) -> LocalFilesystemPayloadStore:
    return LocalFilesystemPayloadStore(storage_dir=tmp_path / "raw_payloads")


def _write_source_document(writer: FirestoreGraphWriter, *, node_id: str, raw_payload_ref: str) -> NodeId:
    doc = SourceDocument(
        id=NodeId(node_id),
        provenance=make_provenance(),
        channel="email",
        raw_payload_ref=raw_payload_ref,
        document_type="school_communication",
        ingested_at=datetime(2026, 8, 20, 9, 0, tzinfo=UTC),
        original_language="en",
    )
    return writer.write_node(doc)


# ---------------------------------------------------------------------------
# parse_region — convention parsing / well-formedness
# ---------------------------------------------------------------------------


class TestParseTextSpanConvention:
    def test_parses_a_valid_span(self) -> None:
        assert parse_region("120-340") == TextSpanRegion(start=120, end=340)

    def test_parses_zero_start(self) -> None:
        assert parse_region("0-10") == TextSpanRegion(start=0, end=10)

    def test_rejects_start_equal_to_end(self) -> None:
        with pytest.raises(MalformedRegion):
            parse_region("50-50")

    def test_rejects_start_greater_than_end(self) -> None:
        with pytest.raises(MalformedRegion):
            parse_region("100-50")


class TestParsePageBoundingBoxConvention:
    def test_parses_a_valid_bbox(self) -> None:
        assert parse_region("page=1;bbox=10,20,300,400") == PageBoundingBoxRegion(
            page=1, bbox=BoundingBox(x0=10, y0=20, x1=300, y1=400)
        )

    def test_parses_fractional_coordinates(self) -> None:
        result = parse_region("page=2;bbox=10.5,20.25,300.0,400.75")
        assert isinstance(result, PageBoundingBoxRegion)
        assert result.page == 2
        assert result.bbox == BoundingBox(x0=10.5, y0=20.25, x1=300.0, y1=400.75)

    def test_rejects_page_zero(self) -> None:
        with pytest.raises(MalformedRegion):
            parse_region("page=0;bbox=0,0,10,10")

    def test_rejects_degenerate_bbox(self) -> None:
        with pytest.raises(MalformedRegion):
            parse_region("page=1;bbox=10,10,10,20")  # x1 == x0


class TestParseRejectsUnsupportedConventions:
    @pytest.mark.parametrize(
        "region",
        [
            "",
            "not-a-region",
            "page=1",
            "bbox=1,2,3,4",
            "page=1;bbox=1,2,3",  # missing a coordinate
            "-5-10",
            "audio=00:00:01-00:00:05",
        ],
    )
    def test_rejects(self, region: str) -> None:
        with pytest.raises(MalformedRegion):
            parse_region(region)


# ---------------------------------------------------------------------------
# resolve_source_ref — end-to-end resolution against real storage
# ---------------------------------------------------------------------------


class TestResolveTextSpanSourceRef:
    def test_resolves_real_bytes_and_region(
        self,
        reader: FirestoreGraphReader,
        writer: FirestoreGraphWriter,
        payload_store: LocalFilesystemPayloadStore,
    ) -> None:
        payload = b"Dear parents, the field trip is on Tuesday at 9am."
        ref = payload_store.store(payload, content_type="text/plain")
        _write_source_document(writer, node_id="doc-text-1", raw_payload_ref=ref)

        source_ref = SourceRef(source_document_id=NodeId("doc-text-1"), region="5-12")
        resolved = resolve_source_ref(source_ref, graph_reader=reader, payload_store=payload_store)

        assert resolved.payload == payload
        assert resolved.content_type == "text/plain"
        assert resolved.raw_payload_ref == ref
        assert resolved.region == TextSpanRegion(start=5, end=12)
        assert isinstance(resolved.region, TextSpanRegion)
        assert resolved.payload[resolved.region.start : resolved.region.end] == b"parents"


class TestResolvePageBoundingBoxSourceRef:
    def test_resolves_real_bytes_and_region(
        self,
        reader: FirestoreGraphReader,
        writer: FirestoreGraphWriter,
        payload_store: LocalFilesystemPayloadStore,
    ) -> None:
        payload = b"\xff\xd8\xff\xe0fake-jpeg-bytes"
        ref = payload_store.store(payload, content_type="image/jpeg")
        _write_source_document(writer, node_id="doc-image-1", raw_payload_ref=ref)

        source_ref = SourceRef(source_document_id=NodeId("doc-image-1"), region="page=1;bbox=10,20,300,400")
        resolved = resolve_source_ref(source_ref, graph_reader=reader, payload_store=payload_store)

        assert resolved.payload == payload
        assert resolved.content_type == "image/jpeg"
        assert resolved.region == PageBoundingBoxRegion(page=1, bbox=BoundingBox(10, 20, 300, 400))


class TestResolveSourceRefFailureModes:
    def test_unknown_source_document_id_raises(
        self, reader: FirestoreGraphReader, payload_store: LocalFilesystemPayloadStore
    ) -> None:
        source_ref = SourceRef(source_document_id=NodeId("does-not-exist"), region="0-10")
        with pytest.raises(SourceDocumentNotFound):
            resolve_source_ref(source_ref, graph_reader=reader, payload_store=payload_store)

    def test_malformed_region_raises_before_touching_the_store(
        self,
        reader: FirestoreGraphReader,
        writer: FirestoreGraphWriter,
        payload_store: LocalFilesystemPayloadStore,
    ) -> None:
        ref = payload_store.store(b"some text", content_type="text/plain")
        _write_source_document(writer, node_id="doc-text-2", raw_payload_ref=ref)

        source_ref = SourceRef(source_document_id=NodeId("doc-text-2"), region="not-a-region")
        with pytest.raises(MalformedRegion):
            resolve_source_ref(source_ref, graph_reader=reader, payload_store=payload_store)

    def test_out_of_bounds_text_span_raises(
        self,
        reader: FirestoreGraphReader,
        writer: FirestoreGraphWriter,
        payload_store: LocalFilesystemPayloadStore,
    ) -> None:
        payload = b"short"
        ref = payload_store.store(payload, content_type="text/plain")
        _write_source_document(writer, node_id="doc-text-3", raw_payload_ref=ref)

        source_ref = SourceRef(source_document_id=NodeId("doc-text-3"), region="0-999")
        with pytest.raises(RegionOutOfBounds):
            resolve_source_ref(source_ref, graph_reader=reader, payload_store=payload_store)

    def test_raw_payload_ref_that_was_never_actually_stored_raises(
        self,
        reader: FirestoreGraphReader,
        writer: FirestoreGraphWriter,
        payload_store: LocalFilesystemPayloadStore,
    ) -> None:
        # SOURCE_DOCUMENT node exists and points at a well-formed-looking
        # ref, but that ref's payload was never actually stored (e.g. the
        # store's backing data was lost) — this is exactly the "opaque
        # string nobody can resolve" failure mode this module exists to
        # prevent from going undetected.
        never_stored_ref = f"sha256:{'0' * 64}"
        _write_source_document(writer, node_id="doc-text-4", raw_payload_ref=never_stored_ref)

        source_ref = SourceRef(source_document_id=NodeId("doc-text-4"), region="0-5")
        with pytest.raises(RawPayloadNotFound):
            resolve_source_ref(source_ref, graph_reader=reader, payload_store=payload_store)
