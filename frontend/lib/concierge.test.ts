import { describe, expect, it } from "vitest";
import {
  AARAV_ID,
  MAX_CLARIFYING_QUESTIONS,
  buildBookingOutcome,
  disclosureOpening,
  getAaravFollowupBookingOutcome,
  getAaravFollowupCall,
  getAaravFollowupFallback,
  getAaravFollowupRetryDecision,
  getAaravFollowupVerification,
  getAaravToothacheApproval,
  getAaravToothacheBookingOutcome,
  getAaravToothacheCall,
  getAaravToothacheCallBrief,
  getAaravToothacheCandidates,
  getAaravToothacheClarification,
  getAaravToothacheRanking,
  getAaravToothacheReliabilitySignals,
  getAaravToothacheVerification,
  getDadiCleaningBookingOutcome,
  getDadiCleaningCall,
  getDadiCleaningFallback,
  getDadiCleaningVerification,
  outcomeReportFromConversation,
  revealedTurnCount,
  verifyCallOutcome,
  type CallBrief,
  type CallOutcomeReport,
  type VerificationResult,
} from "./concierge";

describe("getAaravToothacheClarification", () => {
  it("never asks more than the real MAX_CLARIFYING_QUESTIONS ceiling", () => {
    const result = getAaravToothacheClarification();
    expect(result.questions.length).toBeLessThanOrEqual(MAX_CLARIFYING_QUESTIONS);
    expect(result.questions.length).toBe(2);
  });

  it("demonstrates the ceiling is real: a genuine third unknown was pushed to assumptions, not dropped", () => {
    const result = getAaravToothacheClarification();
    expect(result.assumptions.length).toBeGreaterThan(0);
    expect(result.assumptions[0]).toMatch(/clinic preference/i);
  });

  it("every resolved_from_graph fact carries a real provenance source string, never blank", () => {
    const result = getAaravToothacheClarification();
    expect(result.resolvedFromGraph.length).toBeGreaterThan(0);
    for (const fact of result.resolvedFromGraph) {
      expect(fact.source.length).toBeGreaterThan(0);
    }
  });

  it("sets elevated urgency directly from the household's own request text", () => {
    const result = getAaravToothacheClarification();
    expect(result.urgency).toBe("elevated");
    expect(result.personId).toBe(AARAV_ID);
  });
});

describe("getAaravToothacheRanking", () => {
  it("gives #1 and #2 genuinely different, specific reasons, never interchangeable", () => {
    const ranking = getAaravToothacheRanking();
    const [first, second] = ranking.ranked;
    expect(first.reasons.join(" ")).not.toBe(second.reasons.join(" "));
    expect(first.reasons.some((r) => /urgency|same-day|today/i.test(r))).toBe(true);
    expect(second.reasons.some((r) => /3-4 days|slower/i.test(r))).toBe(true);
  });

  it("flags the demoted provider visibly, with a real no-show reason, not a silent lower rank", () => {
    const ranking = getAaravToothacheRanking();
    const demoted = ranking.ranked.find((p) => p.demotedForReliability);
    expect(demoted).toBeDefined();
    expect(demoted?.reasons.some((r) => /no-show/i.test(r))).toBe(true);
    expect(demoted?.rank).toBe(3);
  });

  it("every ranked provider publishes a full score_components breakdown alongside its score", () => {
    const ranking = getAaravToothacheRanking();
    for (const provider of ranking.ranked) {
      expect(Object.keys(provider.scoreComponents).length).toBeGreaterThan(0);
      expect(provider.reasons.length).toBeGreaterThan(0);
    }
  });

  it("ranks strictly 1..N with no gaps or repeats", () => {
    const ranking = getAaravToothacheRanking();
    expect(ranking.ranked.map((p) => p.rank)).toEqual([1, 2, 3]);
  });

  it("candidates and reliability signals reference only real, declared provider ids", () => {
    const candidateIds = new Set(getAaravToothacheCandidates().map((c) => c.providerId));
    for (const signal of getAaravToothacheReliabilitySignals()) {
      expect(candidateIds.has(signal.providerId)).toBe(true);
    }
  });
});

describe("disclosureOpening", () => {
  it("is always the first thing the transcript says, never conditional on anything the counterparty does", () => {
    const brief = getAaravToothacheCallBrief();
    const opening = disclosureOpening(brief);
    expect(opening).toMatch(/^Hello, this is an automated assistant calling on behalf of a household/);
    expect(opening).toContain(brief.objective);
  });

  it("names the real preferred slot in plain, spoken language", () => {
    const brief = getAaravToothacheCallBrief();
    const opening = disclosureOpening(brief);
    expect(opening).toContain("Friday August 28 at 04:30 PM");
  });
});

describe("getAaravToothacheCall, the hero flow: adapts, then succeeds", () => {
  it("turn zero is exactly the disclosure line, unmissable, structurally first", () => {
    const call = getAaravToothacheCall();
    expect(call.conversation.turns[0]?.turnIndex).toBe(0);
    expect(call.conversation.turns[0]?.speaker).toBe("caller");
    expect(call.conversation.turns[0]?.utterance).toBe(disclosureOpening(call.brief));
  });

  it("adapts to the counterparty's offered alternative slot within authorised bounds", () => {
    const call = getAaravToothacheCall();
    // 4:30pm (the first preferred slot, requested in the disclosure turn)
    // was reported taken; the call adapts to 5:15pm — the second
    // preferred slot the counterparty actually offered — never a slot
    // outside what was authorised.
    expect(call.conversation.claimedSlot).toBe("2026-08-28T17:15:00Z");
    expect(call.brief.preferredSlots).toContain(call.conversation.claimedSlot);
  });

  it("reports no out-of-bounds event and no callback need for a clean success", () => {
    const call = getAaravToothacheCall();
    expect(call.conversation.outOfBoundsEncountered).toBe(false);
    expect(call.conversation.requiresHumanCallback).toBe(false);
  });

  it("outcomeReportFromConversation always sets disclosureGiven true, mirroring the real engine's structural guarantee", () => {
    const call = getAaravToothacheCall();
    const report = outcomeReportFromConversation(call.callId, call.transcriptSourceDocumentId, call.brief.targetProviderId, call.conversation);
    expect(report.disclosureGiven).toBe(true);
  });
});

describe("verifyCallOutcome, a real port of the backend's structural check", () => {
  const brief: CallBrief = getAaravToothacheCallBrief();

  it("verifies a clean, in-bounds, preferred-slot outcome", () => {
    const call = getAaravToothacheCall();
    const verdict = verifyCallOutcome(brief, call.outcomeReport);
    expect(verdict.verified).toBe(true);
    expect(verdict.discrepancies).toEqual([]);
  });

  it("fails closed when disclosure_given is false, checked before anything else", () => {
    const report: CallOutcomeReport = { ...getAaravToothacheCall().outcomeReport, disclosureGiven: false };
    const verdict = verifyCallOutcome(brief, report);
    expect(verdict.verified).toBe(false);
    expect(verdict.discrepancies).toHaveLength(1);
    expect(verdict.discrepancies[0]).toMatch(/disclosure_given is False/);
  });

  it("fails when no slot was claimed, nothing to record, never fabricated", () => {
    const report: CallOutcomeReport = { ...getAaravToothacheCall().outcomeReport, claimedSlot: null };
    const verdict = verifyCallOutcome(brief, report);
    expect(verdict.verified).toBe(false);
    expect(verdict.requiresHumanCallback).toBe(true);
  });

  it("catches a claimed slot outside the authorised date range", () => {
    const report: CallOutcomeReport = { ...getAaravToothacheCall().outcomeReport, claimedSlot: "2026-09-15T10:00:00Z" };
    const verdict = verifyCallOutcome(brief, report);
    expect(verdict.verified).toBe(false);
    expect(verdict.discrepancies.some((d) => d.includes("falls outside the authorised date_range"))).toBe(true);
  });

  it("catches a claimed slot that is in-bounds but not preferred, when fallback is disallowed, the real scenario-C mismatch", () => {
    const call = getAaravFollowupCall();
    const verdict = verifyCallOutcome(call.brief, call.outcomeReport);
    expect(verdict.verified).toBe(false);
    expect(verdict.discrepancies.some((d) => d.includes("is not one of the authorised preferred_slots"))).toBe(true);
  });

  it("does NOT flag the same in-bounds-but-non-preferred slot when fallback IS allowed", () => {
    const call = getAaravFollowupCall();
    const permissiveBrief: CallBrief = { ...call.brief, fallbackAcceptable: true };
    const verdict = verifyCallOutcome(permissiveBrief, call.outcomeReport);
    expect(verdict.verified).toBe(true);
  });
});

describe("buildBookingOutcome, the structural 'no write without verification' guard, ported to the frontend", () => {
  it("produces a confirmed booking only for a real, positive verification with a real slot", () => {
    const call = getAaravToothacheCall();
    const outcome = buildBookingOutcome({
      verification: getAaravToothacheVerification(),
      outcomeReport: call.outcomeReport,
      obligationId: "obligation-x",
      personId: AARAV_ID,
      confirmedPrice: 1800,
      attributionTags: [],
      verifiedByAgent: "A55",
    });
    expect(outcome.kind).toBe("confirmed");
    if (outcome.kind === "confirmed") {
      expect(outcome.booking.confirmedSlot).toBe(call.outcomeReport.claimedSlot);
    }
  });

  it("never confirms when verified is false, regardless of what else is true", () => {
    const call = getAaravToothacheCall();
    const falseVerification: VerificationResult = { ...getAaravToothacheVerification(), verified: false };
    const outcome = buildBookingOutcome({
      verification: falseVerification,
      outcomeReport: call.outcomeReport,
      obligationId: "obligation-x",
      personId: AARAV_ID,
      confirmedPrice: 1800,
      attributionTags: [],
      verifiedByAgent: "A55",
    });
    expect(outcome.kind).toBe("not_recorded");
  });

  it("never confirms when verified is true but claimedSlot is null, a contradiction the guard refuses to paper over", () => {
    const call = getAaravToothacheCall();
    const trueVerificationNoSlot: VerificationResult = { ...getAaravToothacheVerification(), verified: true };
    const noSlotReport: CallOutcomeReport = { ...call.outcomeReport, claimedSlot: null };
    const outcome = buildBookingOutcome({
      verification: trueVerificationNoSlot,
      outcomeReport: noSlotReport,
      obligationId: "obligation-x",
      personId: AARAV_ID,
      confirmedPrice: 1800,
      attributionTags: [],
      verifiedByAgent: "A55",
    });
    expect(outcome.kind).toBe("not_recorded");
  });

  it("the real, fixture-driven scenarios land on the correct side of the guard", () => {
    expect(getAaravToothacheBookingOutcome().kind).toBe("confirmed");
    expect(getDadiCleaningBookingOutcome().kind).toBe("not_recorded");
    expect(getAaravFollowupBookingOutcome().kind).toBe("not_recorded");
  });
});

describe("Scenario B, Dadi's cleaning escalates on an out-of-scope question", () => {
  it("the call ends with requiresHumanCallback true and no claimed slot", () => {
    const call = getDadiCleaningCall();
    expect(call.conversation.requiresHumanCallback).toBe(true);
    expect(call.conversation.claimedSlot).toBeNull();
  });

  it("verification fails structurally, deterministically, no model call needed", () => {
    const verification = getDadiCleaningVerification();
    expect(verification.verified).toBe(false);
    expect(verification.modelTier).toBe("deterministic");
  });

  it("the fallback decision is a real ESCALATE with a full evidence bundle, never a generic message", () => {
    const fallback = getDadiCleaningFallback();
    expect(fallback.action).toBe("escalate");
    expect(fallback.escalationPayload).not.toBeNull();
    expect(fallback.escalationPayload?.evidenceBundle.evidenceConsulted.length).toBeGreaterThan(0);
    expect(fallback.escalationPayload?.relatedNodeId).toBe("obligation-book-dadi-dentist-cleaning");
  });
});

describe("Scenario C, retry, then a real, caught mismatch", () => {
  it("the retry decision carries a real retryAfter time and no escalation payload", () => {
    const retry = getAaravFollowupRetryDecision();
    expect(retry.action).toBe("retry");
    expect(retry.retryAfter).not.toBeNull();
    expect(retry.escalationPayload).toBeNull();
  });

  it("the call itself reports success, the mismatch is caught only by independent verification", () => {
    const call = getAaravFollowupCall();
    expect(call.conversation.outOfBoundsEncountered).toBe(false);
    expect(call.conversation.requiresHumanCallback).toBe(false);
    const verification = getAaravFollowupVerification();
    expect(verification.verified).toBe(false);
    expect(verification.discrepancies.length).toBeGreaterThan(0);
  });

  it("the fallback decision after the mismatch is a real ESCALATE, not a silent retry", () => {
    const fallback = getAaravFollowupFallback();
    expect(fallback.action).toBe("escalate");
    expect(fallback.escalationPayload?.summary).toContain("Friday");
  });
});

describe("getAaravToothacheApproval, the R2 gate that fires before any call", () => {
  it("carries a full, real evidence bundle referencing the actual ranking", () => {
    const approval = getAaravToothacheApproval();
    expect(approval.riskTier).toBe("R2");
    expect(approval.evidenceBundle.evidenceConsulted.some((e) => e.includes("QuickCare"))).toBe(true);
    expect(approval.evidenceBundle.confidence).toBeGreaterThan(0);
  });
});

describe("revealedTurnCount, pure progressive-reveal timing", () => {
  it("reveals nothing before time zero, and nothing for zero turns", () => {
    expect(revealedTurnCount(5, -1)).toBe(0);
    expect(revealedTurnCount(0, 1000)).toBe(0);
  });

  it("reveals one turn immediately, then advances one turn per interval", () => {
    expect(revealedTurnCount(3, 0)).toBe(1);
    expect(revealedTurnCount(3, 900)).toBe(2);
    expect(revealedTurnCount(3, 1800)).toBe(3);
  });

  it("never reveals more than the real total turn count", () => {
    expect(revealedTurnCount(3, 100_000)).toBe(3);
  });
});
