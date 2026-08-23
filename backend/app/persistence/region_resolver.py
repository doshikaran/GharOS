"""Region-reference resolution — given a `contracts.graph_types.SourceRef`
(`source_document_id` + `region`), proves the reference is real: it
resolves to the actual raw payload bytes (via an injected `RawPayloadStore`)
and confirms `region` is well-formed for one of the two region-locator
conventions documented below.

Spec §5.6 deliberately leaves the region format open ("a bounding box, a
line range, a character span... whatever the source medium supports"), so
every extraction agent from Phase 3's E2 side onward must produce regions
in a format this module can parse — these are the two conventions this
codebase commits to, chosen to cover the two source-document shapes the
Document-Type Registry actually produces (spec §5.4): text-shaped sources
(email bodies, chat exports, SMS) and image/scan-shaped sources
(photographed forms, handwritten attendance registers).

**Convention 1 — byte-offset span, for text-shaped documents:**
`"<start>-<end>"`, e.g. `"120-340"`. Zero-indexed, half-open
(`payload[start:end]`, matching Python slice semantics), against the raw
payload bytes exactly as stored — `0 <= start < end <= len(payload)`.

**Convention 2 — page + bounding box, for image/scan-shaped documents:**
`"page=<n>;bbox=<x0>,<y0>,<x1>,<y1>"`, e.g. `"page=1;bbox=10,20,300,400"`.
`page` is 1-indexed. `bbox` coordinates are non-negative numbers in
whatever consistent unit the producing extractor used (typically pixels
of the rendered page/image) with `x1 > x0` and `y1 > y0`. This module
validates syntactic well-formedness only for this convention — confirming
the bbox is genuinely *within* a specific page's rendered dimensions
requires rendering the page, which is Phase 6 frontend work, not this
module's job (this module's job is proving the reference is real and
resolvable, which is what makes Phase 6 possible later).

This module does **not** render or crop the referenced region — that is
explicitly out of scope (Phase 6 frontend work per the Phase 3 work item's
own framing). It proves the reference is real and resolvable: the
SOURCE_DOCUMENT node exists, its raw payload genuinely retrieves, and the
region string is at least syntactically honest about a real place in that
medium.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from contracts.graph_types import NodeId, SourceDocument, SourceRef
from contracts.repositories import GraphReader

from app.persistence.errors import MalformedRegion, RegionOutOfBounds, SourceDocumentNotFound
from app.persistence.raw_payload_store import RawPayloadStore

_TEXT_SPAN_PATTERN = re.compile(r"^(?P<start>\d+)-(?P<end>\d+)$")
_PAGE_BBOX_PATTERN = re.compile(
    r"^page=(?P<page>\d+);bbox="
    r"(?P<x0>\d+(?:\.\d+)?),(?P<y0>\d+(?:\.\d+)?),(?P<x1>\d+(?:\.\d+)?),(?P<y1>\d+(?:\.\d+)?)$"
)


@dataclass(frozen=True, slots=True)
class TextSpanRegion:
    """Convention 1 — a half-open byte-offset span `payload[start:end]`."""

    start: int
    end: int


@dataclass(frozen=True, slots=True)
class BoundingBox:
    x0: float
    y0: float
    x1: float
    y1: float


@dataclass(frozen=True, slots=True)
class PageBoundingBoxRegion:
    """Convention 2 — a bounding box on a 1-indexed page of an
    image/scan-shaped document."""

    page: int
    bbox: BoundingBox


RegionLocator = TextSpanRegion | PageBoundingBoxRegion
"""The parsed form of a `SourceRef.region` string — exactly one of the two
documented conventions."""


@dataclass(frozen=True, slots=True)
class ResolvedSourceRegion:
    """The proof-of-resolvability result: the real payload bytes behind a
    `SourceRef`, plus its parsed, validated region locator. Deliberately
    does not crop/render the region — see this module's docstring."""

    source_document_id: NodeId
    raw_payload_ref: str
    payload: bytes
    content_type: str
    region: RegionLocator


def parse_region(region: str) -> RegionLocator:
    """Parses `region` against the two supported region-locator
    conventions (this module's docstring), returning whichever matches.

    Raises:
        MalformedRegion: `region` matches neither convention, or matches
            one syntactically but fails that convention's own validity
            rule (e.g. `start >= end`, `x1 <= x0`, `page < 1`).
    """
    text_match = _TEXT_SPAN_PATTERN.match(region)
    if text_match is not None:
        start, end = int(text_match["start"]), int(text_match["end"])
        if start >= end:
            raise MalformedRegion(region=region, reason=f"start ({start}) must be < end ({end})")
        return TextSpanRegion(start=start, end=end)

    bbox_match = _PAGE_BBOX_PATTERN.match(region)
    if bbox_match is not None:
        page = int(bbox_match["page"])
        if page < 1:
            raise MalformedRegion(region=region, reason=f"page must be >= 1, got {page}")
        x0, y0, x1, y1 = (
            float(bbox_match["x0"]),
            float(bbox_match["y0"]),
            float(bbox_match["x1"]),
            float(bbox_match["y1"]),
        )
        if x1 <= x0 or y1 <= y0:
            raise MalformedRegion(
                region=region, reason=f"bbox must have x1 > x0 and y1 > y0, got ({x0},{y0},{x1},{y1})"
            )
        return PageBoundingBoxRegion(page=page, bbox=BoundingBox(x0=x0, y0=y0, x1=x1, y1=y1))

    raise MalformedRegion(
        region=region,
        reason=(
            "matches neither the 'start-end' byte-offset convention "
            "nor the 'page=N;bbox=x0,y0,x1,y1' convention"
        ),
    )


def resolve_source_ref(
    source_ref: SourceRef,
    *,
    graph_reader: GraphReader,
    payload_store: RawPayloadStore,
) -> ResolvedSourceRegion:
    """Resolves `source_ref` to (a) the real raw payload bytes behind its
    SOURCE_DOCUMENT, and (b) a validated, parsed region locator — proving
    the reference is genuinely resolvable, not just an opaque string.

    Args:
        source_ref: pointer to a SOURCE_DOCUMENT and a region within it.
        graph_reader: resolves `source_ref.source_document_id` to its
            current node.
        payload_store: resolves the resolved node's `raw_payload_ref` to
            real bytes.

    Returns:
        A `ResolvedSourceRegion` carrying the real payload bytes, its
        content type, and the parsed `RegionLocator`.

    Raises:
        SourceDocumentNotFound: `source_ref.source_document_id` does not
            resolve to a current `SourceDocument` node.
        RawPayloadNotFound: the resolved node's `raw_payload_ref` does not
            resolve to any stored payload (propagated from
            `payload_store.retrieve`).
        MalformedRegion: `source_ref.region` matches neither supported
            region-locator convention.
        RegionOutOfBounds: `source_ref.region` is syntactically
            well-formed but not resolvable against the actual retrieved
            payload (e.g. a byte-offset span whose `end` exceeds the
            payload's real length).
    """
    node = graph_reader.get_node(source_ref.source_document_id)
    if not isinstance(node, SourceDocument):
        raise SourceDocumentNotFound(source_document_id=str(source_ref.source_document_id))

    region = parse_region(source_ref.region)
    payload = payload_store.retrieve(node.raw_payload_ref)

    if isinstance(region, TextSpanRegion) and region.end > len(payload):
        raise RegionOutOfBounds(
            region=source_ref.region,
            detail=f"end offset {region.end} exceeds payload length {len(payload)}",
        )

    content_type = payload_store.content_type_of(node.raw_payload_ref)

    return ResolvedSourceRegion(
        source_document_id=node.id,
        raw_payload_ref=node.raw_payload_ref,
        payload=payload,
        content_type=content_type,
        region=region,
    )
