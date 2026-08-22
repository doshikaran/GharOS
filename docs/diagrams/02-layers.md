# Layers and the action barrier

Source: `GharOS_Build_Spec_v2.md` §6.2, `PHASES.md` §5.2.

```mermaid
flowchart LR
    L0[L0 Adapters] --> L1[L1 Perception] --> L2[(L2 Graph)] --> L3[L3 Reasoning<br/>7 subsystems]
    L3 -->|proposes only| L4[L4 Arbitration]
    L4 -->|the ONLY path to action| L5[L5 Action Tools]
    L5 --> L6[(L6 Audit)]
    L5 --> L2
    style L3 fill:#3b1d6e,color:#fff
    style L4 fill:#8a6320,color:#fff
    style L5 fill:#7a1f1f,color:#fff
```

**The L3→L5 barrier is the architecture.** Reasoning agents hold no action credentials. This is safety invariant #1 (no agent that reasons about money holds a financial tool credential) generalised to every subsystem: extraction agents cannot write the graph directly (that's A7 Graph Builder's job), reconciliation cannot pay, drafting cannot send, ranking cannot call. Every arrow crossing L3→L4→L5 is a proposal being evaluated, never a direct effect.

- **L0 — Ingestion adapters.** Channel-specific, swappable (email, upload, SMS, WhatsApp export, voice, scheduled tick).
- **L1 — Perception.** Extraction, entity resolution. Writes SOURCE_DOCUMENT.
- **L2 — Graph.** The substrate. All reads and writes pass through it.
- **L3 — Reasoning.** The seven subsystems. Read graph, propose changes. No direct external action.
- **L4 — Arbitration.** Confidence, risk tiering, approval gating.
- **L5 — Action.** Tools that touch the outside world. Separately permissioned. Idempotent.
- **L6 — Audit.** Immutable record, written before L5 executes.
