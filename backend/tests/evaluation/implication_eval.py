"""A12's honest evaluation harness (PHASES.md Phase 4, "The honest
evaluation" — the flagship agent's real hallucination rate, the project's
own words: "the number that matters" / "the project's real risk signal").

Runs `ImplicationAgent.imply` against every document in
`held_out_documents.EVAL_DOCUMENTS` (real Vertex AI Gemini calls, Pro-tier,
matching this repo's established `live_gcp` convention — see
`test_live_gemini_intake.py`) and exposes the raw, structured results this
module's own author then reads by hand to score recall, hallucination
rate, obligations missed, and citation validity against the hand-written
ground truth — recorded honestly in `docs/IMPLICATION_BASELINE.md`, not
computed here as a single pass/fail number. Matching a real, freely-worded
model obligation to a hand-written ground-truth description is a semantic
judgment call (gharos-standards skill's own instruction on partial credit,
applied to scoring, not just to fixture construction) — automating that
match with a second LLM call would just substitute one model's judgment
for another's, not remove the judgment call. What *is* automated and
enforced here, every run: every produced citation resolves to a real span
in its own document (`citation_validator.py` already guarantees this
inside `ImplicationAgent.imply` itself — nothing here re-implements that),
and every discarded inference carries a non-empty, specific reason.

    GHAROS_RUN_LIVE_GCP_TESTS=1 GCP_PROJECT_ID=<project> \\
        uv run pytest tests/evaluation/implication_eval.py -m live_gcp -v -s

Two extra offline sanity checks (not `live_gcp`-marked, run in the default
suite for free) guard the ground-truth data itself: exactly twenty
documents, unique ids, and every ground-truth citation hint a real,
verbatim substring of the document it claims to come from — so this
evaluation's own scoring reference cannot silently drift from the text it
was written against.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

import pytest
import structlog
from contracts.graph_types import NodeId

from app.agents.consequence.implication_agent import ImplicationAgent
from app.agents.consequence.types import ImplicationRequest, ImplicationRunResult
from app.reasoning.gemini_client import GeminiClient
from app.reasoning.model_router import ModelRouter
from app.settings import Settings

from .held_out_documents import EVAL_DOCUMENTS, HeldOutDocument

logger = structlog.get_logger(__name__)

_LIVE_TESTS_ENABLED = os.environ.get("GHAROS_RUN_LIVE_GCP_TESTS") == "1"
_LIVE_PROJECT_ID = os.environ.get("GCP_PROJECT_ID", "")
_SKIP_REASON = (
    "live GCP test — set GHAROS_RUN_LIVE_GCP_TESTS=1 and GCP_PROJECT_ID to run "
    "the real Gemini calls this evaluation depends on"
)


@dataclass(frozen=True, slots=True)
class DocumentEvalOutcome:
    """One held-out document's real `ImplicationAgent.imply` output,
    paired back with the document it came from so a reader can line up
    `result.candidates`/`result.discarded` against `document.ground_truth_implied`
    without a second lookup."""

    document: HeldOutDocument
    result: ImplicationRunResult


def build_live_agent() -> ImplicationAgent:
    """Constructs a real, live-Gemini-backed `ImplicationAgent` — no fakes,
    matching `test_live_gemini_intake.py`'s `_live_router` pattern.

    A12 calls exclusively at Pro-tier (`implication_agent.py` hardcodes
    `ModelTier.PRO`), so — unlike the Flash-heavy intake live tests —
    `location_pro` must be set explicitly to `settings.vertex_ai_location_pro`
    ("global"): `gemini-2.5-pro` 404s regionally in `asia-south1` for this
    project (ADR-010, `app/settings.py`'s own documented finding); omitting
    it would make every single call in this evaluation fail before any
    real scoring question could even be asked.
    """
    settings = Settings(gcp_project_id=_LIVE_PROJECT_ID)
    router = ModelRouter(
        project_id=settings.gcp_project_id,
        location=settings.vertex_ai_location,
        model_flash=settings.gemini_model_flash,
        model_pro=settings.gemini_model_pro,
        location_pro=settings.vertex_ai_location_pro,
    )
    client = GeminiClient(router=router)
    return ImplicationAgent(gemini_client=client)


def run_document(agent: ImplicationAgent, document: HeldOutDocument) -> DocumentEvalOutcome:
    """Runs one held-out document through a real `ImplicationAgent.imply`
    call and returns the paired outcome, logging a structured summary
    (never `print`, per gharos-standards) so a full evaluation run leaves
    an audit trail even before any hand-scoring happens."""
    request = ImplicationRequest(
        source_document_id=NodeId(document.doc_id),
        document_text=document.document_text,
        household_context=document.household_context,
    )
    result = agent.imply(request)
    logger.info(
        "evaluation.implication_eval.document_completed",
        doc_id=document.doc_id,
        ground_truth_count=len(document.ground_truth_implied),
        candidate_count=len(result.candidates),
        discarded_count=len(result.discarded),
    )
    return DocumentEvalOutcome(document=document, result=result)


def run_all_documents(agent: ImplicationAgent) -> tuple[DocumentEvalOutcome, ...]:
    """Runs every document in `EVAL_DOCUMENTS` through `run_document`, in
    order, returning one outcome per document. Sequential, not
    parallelised — this is a hand-scored evaluation run, not a
    throughput-sensitive production path, and sequential calls keep the
    structured log trail in document order for easier reading."""
    return tuple(run_document(agent, document) for document in EVAL_DOCUMENTS)


def render_report(outcomes: tuple[DocumentEvalOutcome, ...]) -> str:
    """Renders a full, human-readable audit dump of one evaluation run:
    per document, the hand-written ground truth next to A12's real
    candidates and discarded inferences. This is the worksheet
    `docs/IMPLICATION_BASELINE.md`'s per-document breakdown is scored
    from — a pure function (no I/O) so callers choose how to surface it
    (a caller-owned driver script writing it to a file; this module itself
    never prints or writes)."""
    lines: list[str] = []
    for outcome in outcomes:
        document = outcome.document
        result = outcome.result
        lines.append(f"\n{'=' * 88}\n{document.doc_id} — {document.title}\n{'=' * 88}")
        lines.append(f"\n--- document text ---\n{document.document_text}\n")
        if document.notes:
            lines.append(f"--- notes ---\n{document.notes}\n")
        lines.append("--- ground truth (hand-written before this run) ---")
        if not document.ground_truth_implied:
            lines.append("  (none — hallucination-rate control document)")
        for gt in document.ground_truth_implied:
            lines.append(f"  [{gt.ground_truth_id}] ({gt.certainty}) {gt.description}")
            lines.append(f"      expected trigger: {gt.expected_citation_hint!r}")
        lines.append(f"\n--- A12 produced ({len(result.candidates)} candidate(s)) ---")
        if not result.candidates:
            lines.append("  (none)")
        for candidate in result.candidates:
            lines.append(f"  * {candidate.title}  [confidence={candidate.confidence:.2f}]")
            lines.append(f"      reasoning: {candidate.reasoning}")
            lines.append(f"      cited_span_text: {candidate.cited_span_text!r}")
            lines.append(f"      citation.region: {candidate.citation.region}")
        lines.append(f"\n--- A12 discarded ({len(result.discarded)} inference(s)) ---")
        for discarded in result.discarded:
            lines.append(f"  * {discarded.title}")
            lines.append(f"      discard_reason: {discarded.discard_reason}")
            lines.append(f"      claimed_span_text: {discarded.claimed_span_text!r}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Offline data-integrity checks — free, run in the default suite, no live
# credentials needed. These guard the evaluation's own scoring reference,
# not A12 itself.
# ---------------------------------------------------------------------------


def test_exactly_twenty_held_out_documents() -> None:
    assert len(EVAL_DOCUMENTS) == 20


def test_document_ids_are_unique() -> None:
    ids = [document.doc_id for document in EVAL_DOCUMENTS]
    assert len(ids) == len(set(ids))


def test_ground_truth_citation_hints_are_real_substrings_of_their_document() -> None:
    """Every hand-written `expected_citation_hint` must really appear,
    verbatim, in the document it was written against — otherwise the
    ground truth itself could silently drift from the text a reader
    would check it against."""
    for document in EVAL_DOCUMENTS:
        for ground_truth in document.ground_truth_implied:
            assert ground_truth.expected_citation_hint in document.document_text, (
                f"{document.doc_id}/{ground_truth.ground_truth_id}: "
                f"hint {ground_truth.expected_citation_hint!r} not found verbatim in document text"
            )


def test_control_documents_have_empty_ground_truth() -> None:
    """The two hallucination-rate control documents (`eval-15`, `eval-20`)
    must have an empty `ground_truth_implied` — any candidate A12 produces
    for either is a hallucination by construction, and that only holds if
    the control's own ground truth really is empty."""
    control_ids = {"eval-15-grocery-receipt", "eval-20-library-books"}
    for document in EVAL_DOCUMENTS:
        if document.doc_id in control_ids:
            assert document.ground_truth_implied == ()


# ---------------------------------------------------------------------------
# The real evaluation run — live Gemini, Pro-tier, `live_gcp`-marked.
# ---------------------------------------------------------------------------


@pytest.mark.live_gcp
@pytest.mark.skipif(not _LIVE_TESTS_ENABLED or not _LIVE_PROJECT_ID, reason=_SKIP_REASON)
def test_a12_real_run_against_all_twenty_held_out_documents() -> None:
    """Runs the real evaluation end to end and asserts only the structural
    invariants `ImplicationAgent.imply` itself already guarantees for
    every candidate it returns (non-empty, resolvable citation region;
    confidence at/above its own floor) and for every discard (a specific,
    non-empty reason) — this is deliberately NOT where recall/hallucination-
    rate/citation-validity numbers get asserted as a pass/fail gate (see
    this module's docstring): those are semantic judgment calls this
    module's author makes by reading `render_report`'s output, recorded in
    `docs/IMPLICATION_BASELINE.md`, not something a live, non-deterministic
    model call should silently gate the rest of the suite on.
    """
    agent = build_live_agent()
    outcomes = run_all_documents(agent)

    assert len(outcomes) == len(EVAL_DOCUMENTS)
    for outcome in outcomes:
        for candidate in outcome.result.candidates:
            assert candidate.citation.region, f"{outcome.document.doc_id}: candidate with empty region"
            start, end = (int(part) for part in candidate.citation.region.split("-"))
            assert 0 <= start < end
            assert candidate.cited_span_text
            assert candidate.confidence >= 0.5
        for discarded in outcome.result.discarded:
            assert discarded.discard_reason, f"{outcome.document.doc_id}: discard with empty reason"

    logger.info(
        "evaluation.implication_eval.run_completed",
        document_count=len(outcomes),
        total_candidates=sum(len(o.result.candidates) for o in outcomes),
        total_discarded=sum(len(o.result.discarded) for o in outcomes),
    )


__all__ = [
    "DocumentEvalOutcome",
    "build_live_agent",
    "render_report",
    "run_all_documents",
    "run_document",
]
