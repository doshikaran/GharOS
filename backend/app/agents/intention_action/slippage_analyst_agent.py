"""A26 — Slippage Analyst (spec §9.3 Stage 4, §9.5, §15.9).

*Responsibility:* on repeat unblocking failure, re-diagnose — genuinely
reconsidering that the *first* diagnosis may have been wrong (spec §9.3
Stage 4's own framing), not blindly re-running the same conclusion — and,
once a real, documented attempt threshold is reached, escalate with three
real, concrete options: drop, delegate, or pay. Spec's own failure mode
(§9.5) names exactly what this agent must never produce: "a vague 'this
keeps failing' message with no options."

*The threshold, N = 3:* three real, distinct failed unblocking attempts
on the *same* obligation (see `_ESCALATION_THRESHOLD` below for the full
reasoning) — a documented, defensible product constant, not a guess,
matching every other threshold this package defines
(`intention_capture_agent._STALE_AFTER_DEADLINE_DAYS`, `window_scheduling_
agent._WINDOW_BLOCKER_SUPPORT_UNLIKELY_THRESHOLD`).

*Model tier:* Pro-tier (`model_router.PRO_TIER_ALLOWLIST`) — re-diagnosing
against a real attempt history, and producing three genuinely concrete
escalation options grounded in real household data, is judgment, not
lookup.

*Forbidden:* this module holds no tool of any kind — no read, no write,
no send. Every fact it reasons over (the attempt history, the real
capability-eligible delegate candidates, the real market-rate hint for a
"pay" option) arrives pre-resolved on `types.SlippageAnalysisRequest`,
this codebase's established "pre-resolved by the caller" precedent. It
proposes an escalation; it never itself drops, delegates, or pays
anything.
"""

from __future__ import annotations

import uuid

from contracts.agents import ModelTier
from contracts.graph_types import AgentId, NodeId

from ...prompts.loader import load_prompt
from ...reasoning.gemini_client import GeminiClient
from .errors import ModelResponseMalformed
from .json_utils import (
    optional_float,
    optional_str,
    parse_json_response,
    require_bool,
    require_float,
    require_str,
)
from .types import (
    BlockerType,
    DelegateCandidate,
    EscalationOption,
    EscalationOptionKind,
    SlippageAnalysisRequest,
    SlippageAnalysisResult,
    SlippageReDiagnosis,
    UnblockingAttempt,
)

AGENT_ID = AgentId("A26")

_ESCALATION_THRESHOLD = 3
"""Three real, distinct failed unblocking attempts on the same obligation
before A26 escalates with drop/delegate/pay options. Spec §9.5's own
illustrative failure-mode text ("this has slipped 4 times") is flavour,
not a prescribed count — this module deliberately escalates one attempt
sooner than that example, on the reasoning that a household has already
lost real time and at least one genuine re-diagnosis cycle by attempt 3,
and further silent retries past that point cost more than surfacing real
options would. Two failures is treated as "worth re-diagnosing, not yet
worth escalating" — a single bad attempt is not evidence of a systemic
problem; three is."""


def _known_facts_block(attempts: tuple[UnblockingAttempt, ...]) -> str:
    lines = []
    for attempt in attempts:
        lines.append(
            f"- attempt {attempt.attempt_number} ({attempt.attempted_at.isoformat()}): "
            f'diagnosed as "{attempt.diagnosis.blocker_type.value}" — "{attempt.diagnosis.diagnosis_text}"; '
            f'action taken: "{attempt.action_taken}"; outcome: {attempt.outcome}'
        )
    return "\n".join(lines) if lines else "(no attempts recorded)"


def _delegates_block(delegates: tuple[DelegateCandidate, ...]) -> str:
    if not delegates:
        return "(no eligible delegate identified)"
    return "\n".join(
        f'- id="{d.person_id}" name="{d.display_name}" — {d.relevant_capability_note}' for d in delegates
    )


class SlippageAnalystAgent:
    """A26 Slippage Analyst. Dependency-injected on a `GeminiClient`
    only — no tool of any kind (see module docstring)."""

    def __init__(self, *, gemini_client: GeminiClient) -> None:
        self._gemini_client = gemini_client

    def analyze(self, request: SlippageAnalysisRequest) -> SlippageAnalysisResult:
        """Analyzes one obligation's real unblocking-attempt history.

        Args:
            request: the full, real, chronological attempt history plus
                real eligible delegates and an optional market-rate hint.

        Returns:
            A `SlippageAnalysisResult`. `re_diagnosis` is populated
            whenever `len(request.attempts) >= 2` (a genuine repeat, spec
            §9.5's own trigger for re-diagnosis) regardless of whether the
            escalation threshold has been reached; `escalation_options`
            is populated (always exactly three, one per `EscalationOptionKind`)
            only once `len(request.attempts) >= _ESCALATION_THRESHOLD`.

        Raises:
            errors.ModelResponseMalformed: the model response could not
                be parsed, named a re-diagnosis blocker type outside the
                six-type taxonomy, named a `"delegate"` option's candidate
                outside `request.eligible_delegates`, or did not return
                exactly one option per kind when escalation triggered.
        """
        attempt_count = len(request.attempts)
        escalation_triggered = attempt_count >= _ESCALATION_THRESHOLD

        if attempt_count < 2:
            return SlippageAnalysisResult(
                obligation_id=request.obligation_id,
                person_id=request.person_id,
                attempt_count=attempt_count,
                threshold=_ESCALATION_THRESHOLD,
                escalation_triggered=False,
                re_diagnosis=None,
                escalation_options=(),
                message_text="",
                confidence=1.0,
                model_tier="pro",
                prompt_version="n/a",
                invocation_id=uuid.uuid4().hex,
            )

        prompt = load_prompt("A26")
        rendered = prompt.text.format(
            obligation_title=request.obligation_title,
            attempts_block=_known_facts_block(request.attempts),
            escalation_triggered=str(escalation_triggered),
            threshold=_ESCALATION_THRESHOLD,
            delegates_block=_delegates_block(request.eligible_delegates),
            market_rate_hint=request.market_rate_hint or "(no real market-rate data available)",
        )
        call_result = self._gemini_client.generate_structured(
            agent_id=AGENT_ID, tier=ModelTier.PRO, prompt=rendered
        )
        parsed = parse_json_response(agent_id=AGENT_ID, text=call_result.text)

        re_diagnosis = self._parse_re_diagnosis(parsed, raw_text=call_result.text)
        escalation_options: tuple[EscalationOption, ...] = ()
        if escalation_triggered:
            escalation_options = self._parse_escalation_options(
                parsed, request=request, raw_text=call_result.text
            )

        return SlippageAnalysisResult(
            obligation_id=request.obligation_id,
            person_id=request.person_id,
            attempt_count=attempt_count,
            threshold=_ESCALATION_THRESHOLD,
            escalation_triggered=escalation_triggered,
            re_diagnosis=re_diagnosis,
            escalation_options=escalation_options,
            message_text=require_str(parsed, "message_text", agent_id=AGENT_ID),
            confidence=require_float(parsed, "confidence", agent_id=AGENT_ID, default=0.0),
            model_tier="pro",
            prompt_version=prompt.version,
            invocation_id=uuid.uuid4().hex,
        )

    def _parse_re_diagnosis(self, parsed: dict[str, object], *, raw_text: str) -> SlippageReDiagnosis:
        re_diag_raw = parsed.get("re_diagnosis")
        if not isinstance(re_diag_raw, dict):
            raise ModelResponseMalformed(
                agent_id=AGENT_ID, reason="expected object field 're_diagnosis'", raw_text=raw_text
            )
        blocker_type_raw = require_str(re_diag_raw, "likely_blocker_type", agent_id=AGENT_ID)
        try:
            blocker_type = BlockerType(blocker_type_raw)
        except ValueError as exc:
            raise ModelResponseMalformed(
                agent_id=AGENT_ID,
                reason=f"unrecognised re_diagnosis.likely_blocker_type {blocker_type_raw!r}",
                raw_text=raw_text,
            ) from exc
        return SlippageReDiagnosis(
            likely_blocker_type=blocker_type,
            reasoning=require_str(re_diag_raw, "reasoning", agent_id=AGENT_ID),
            confidence=require_float(re_diag_raw, "confidence", agent_id=AGENT_ID, default=0.0),
            changed_from_prior=require_bool(
                re_diag_raw, "changed_from_prior", agent_id=AGENT_ID, default=False
            ),
        )

    def _parse_escalation_options(
        self, parsed: dict[str, object], *, request: SlippageAnalysisRequest, raw_text: str
    ) -> tuple[EscalationOption, ...]:
        raw_options = parsed.get("escalation_options")
        if not isinstance(raw_options, list) or len(raw_options) != 3:
            raise ModelResponseMalformed(
                agent_id=AGENT_ID,
                reason=f"expected exactly 3 escalation_options, got {raw_options!r}",
                raw_text=raw_text,
            )

        eligible_ids = {str(d.person_id) for d in request.eligible_delegates}
        options: list[EscalationOption] = []
        seen_kinds: set[str] = set()
        for raw_option in raw_options:
            if not isinstance(raw_option, dict):
                raise ModelResponseMalformed(
                    agent_id=AGENT_ID,
                    reason="each escalation_options entry must be an object",
                    raw_text=raw_text,
                )
            kind_raw = require_str(raw_option, "kind", agent_id=AGENT_ID)
            if kind_raw not in {"drop", "delegate", "pay"}:
                raise ModelResponseMalformed(
                    agent_id=AGENT_ID,
                    reason=f"unrecognised escalation option kind {kind_raw!r}",
                    raw_text=raw_text,
                )
            if kind_raw in seen_kinds:
                raise ModelResponseMalformed(
                    agent_id=AGENT_ID,
                    reason=f"duplicate escalation option kind {kind_raw!r}",
                    raw_text=raw_text,
                )
            seen_kinds.add(kind_raw)

            description = require_str(raw_option, "description", agent_id=AGENT_ID)
            candidate_person_id: NodeId | None = None
            estimated_cost: float | None = None

            if kind_raw == "delegate":
                candidate_raw = optional_str(raw_option, "candidate_person_id")
                if request.eligible_delegates:
                    if candidate_raw is None or candidate_raw not in eligible_ids:
                        raise ModelResponseMalformed(
                            agent_id=AGENT_ID,
                            reason=(
                                "delegate option must name a candidate from "
                                f"eligible_delegates, got {candidate_raw!r}"
                            ),
                            raw_text=raw_text,
                        )
                    candidate_person_id = NodeId(candidate_raw)
            elif kind_raw == "pay":
                model_cost = optional_float(raw_option, "estimated_cost")
                # Never trust a fabricated figure this module has no
                # grounding for — only surfaced when the caller supplied a
                # real market-rate hint to ground it in (see
                # `types.SlippageAnalysisRequest.market_rate_hint`'s own
                # docstring).
                estimated_cost = model_cost if request.market_rate_hint is not None else None

            options.append(
                EscalationOption(
                    kind=EscalationOptionKind(kind_raw),
                    description=description,
                    candidate_person_id=candidate_person_id,
                    estimated_cost=estimated_cost,
                )
            )

        if seen_kinds != {"drop", "delegate", "pay"}:
            raise ModelResponseMalformed(
                agent_id=AGENT_ID,
                reason=f"escalation_options must cover exactly drop/delegate/pay once each, got {seen_kinds}",
                raw_text=raw_text,
            )
        return tuple(options)


__all__ = ["AGENT_ID", "SlippageAnalystAgent"]
