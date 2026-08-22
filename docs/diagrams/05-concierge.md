# Outbound Concierge

Source: `GharOS_Build_Spec_v2.md` §13.2-13.3, `PHASES.md` §5.5.

```mermaid
sequenceDiagram
    participant U as User
    participant CL as A50 Clarifier
    participant G as Graph
    participant RK as A52 Ranking
    participant GT as Approval Gate
    participant VC as A54 Voice Agent
    participant VF as A55 Verifier

    U->>CL: "book a dentist"
    CL->>G: what do we already know?
    CL->>U: ask ONLY the unknown (≤2 questions)
    CL->>RK: requirements + urgency
    RK->>GT: ranked shortlist WITH REASONS
    GT->>U: approve calling #1?
    U->>GT: approved
    GT->>VC: pre-call brief + authorised bounds
    VC->>VC: disclose automated, negotiate within bounds
    VC->>VF: outcome + transcript
    Note over VF: NEVER record an unverified booking
    VF->>G: booking + calendar + OUTCOME
```

**Reading this diagram:** the clarifier is graph-first — it asks only what the graph genuinely cannot answer, which is what keeps the demo's clarifying step to two questions instead of twenty. The Approval Gate sits before any call is placed (R2) and again implicitly before money changes hands if the booking has a deposit (R3). The verifier is a hard gate on writing to the graph: a call that "sounds like" it succeeded is not the same as a call that was cross-checked against what was requested, and only the latter is ever recorded as a booking.
