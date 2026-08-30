# Outbound Concierge

Source: `GharOS_Build_Spec_v2.md` §13.2-13.3, `PHASES.md` §5.5, `docs/adr/016-outbound-concierge-scope.md`.

```mermaid
sequenceDiagram
    participant U as User
    participant CL as A50 Clarifier
    participant G as Graph
    participant DS as A51 Discovery
    participant RK as A52 Ranking
    participant CP as A53 Call Planner
    participant GT as Approval Gate
    participant VC as A54 Voice Call Agent
    participant FB as A56 Fallback
    participant VF as A55 Verifier

    U->>CL: "book a dentist"
    CL->>G: what do we already know?
    CL->>U: ask ONLY the unknown (≤2 questions, code-enforced ceiling)
    CL->>DS: requirements + urgency
    DS->>RK: candidate providers
    RK->>GT: ranked shortlist WITH REASONS (demotes real no-show history)
    GT->>U: approve calling #1?
    U->>GT: approved
    GT->>CP: build pre-call brief within approved bounds
    CP->>VC: objective · authorised bounds · disclosable facts · must-not-answer list
    VC->>VC: disclose it is automated (non-disableable), negotiate within bounds
    alt requested slot gone
        VC->>VC: adapt within authorised bounds
    else out of bounds / call fails
        VC->>FB: retry ladder → web fallback → human escalation, pre-prepared
    end
    VC->>VF: outcome + transcript
    Note over VF: structural check THEN semantic check —<br/>can only narrow a pass into a fail. NEVER record an unverified booking.
    VF->>G: booking + calendar + OUTCOME (only if verified)
```

**Reading this diagram:** the clarifier is graph-first — it asks only what the graph genuinely cannot answer, which is what keeps the demo's clarifying step to two questions instead of twenty (the ≤2 ceiling is enforced in code, not prompted). A53 copies the approved bounds verbatim and cannot widen them. The Approval Gate sits before any call is placed (R2) and again before money changes hands if the booking has a deposit (R3). The verifier (A55) is a hard gate on writing to the graph: a two-layer structural-then-semantic check that can only turn a pass into a fail, never the reverse — a call that "sounds like" it succeeded is not the same as a call cross-checked against what was requested, and only the latter is ever recorded.

**Demo honesty (ADR-016):** the counterparty in the demo is a **sandboxed, independently-reasoning LLM persona**, never a real phone call to a real business. Bounds enforcement, the mandatory automated-disclosure turn, the slot-gone adaptation, and verification-before-recording are all fully real. Synthesized *audio* is produced by the separate Phase 13 voice channel (Gemini native TTS); the concierge conversation itself is a real multi-turn text/transcript exchange.
