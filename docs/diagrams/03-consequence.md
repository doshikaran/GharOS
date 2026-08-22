# Consequence Engine pipeline

Source: `GharOS_Build_Spec_v2.md` §7.3, `PHASES.md` §5.3.

```mermaid
sequenceDiagram
    participant S as Source Document
    participant E as A3 Extraction
    participant I as A12 Implication
    participant C as A13 Constraint Checker
    participant R as A14 Conflict Radar
    participant W as A15 Writer
    participant G as Graph

    S->>E: raw multimodal payload
    E->>G: SOURCE_DOCUMENT + extracted fields with spans
    E->>I: extraction + household context
    Note over I: every implication MUST cite a source span<br/>uncitable → DISCARDED
    I->>C: candidate obligations
    Note over C: hard-constraint ambiguity → ESCALATE, never resolve
    C->>R: validated candidates
    R->>G: query availability + open obligations
    R->>W: candidates + conflict flags
    W->>G: obligations with full provenance
```

**Reading this diagram:** extraction (A3) and implication (A12) are deliberately separate agents — mixing them would launder a hallucinated inference as an "extracted" fact. Every candidate obligation A12 produces must trace to a specific source span or it is discarded before it ever reaches the Constraint Checker. A13 never resolves a hard-constraint ambiguity itself; ambiguity is a first-class outcome that escalates.
