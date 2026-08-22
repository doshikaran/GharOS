# System overview

Source: `GharOS_Build_Spec_v2.md` §6.1, `PHASES.md` §5.1.

```mermaid
flowchart TB
    subgraph IN[Inputs]
        A1[Email]
        A2[Documents / photos]
        A3[WhatsApp / UPI SMS]
        A4[Voice utterance]
        A5[Scheduled tick]
    end

    A1 & A2 & A3 & A4 & A5 --> PS[(Cloud Pub/Sub)]
    PS --> INTAKE[Intake Layer<br/>route · extract · resolve]
    INTAKE --> GRAPH[(Firestore<br/>Household Knowledge Graph)]
    INTAKE --> ORCH{ADK Orchestrator<br/>A0 Household Coordinator}

    ORCH --> S1[1 Consequence Engine]
    ORCH --> S2[2 Fair Allocator]
    ORCH --> S3[3 Intention→Action]
    ORCH --> S4[4 Household Ledger]
    ORCH --> S5[5 Simulator]
    ORCH --> S6[6 Council]
    ORCH --> S7[7 Outbound Concierge]

    S1 & S2 & S3 & S4 & S5 & S6 & S7 --> ARB[Arbitration<br/>confidence · risk tier]
    ARB -->|R0/R1| ACT[Action Layer<br/>idempotent tools]
    ARB -->|R2/R3| GATE[Approval Gate]
    ARB -->|R4| ESC[Escalate — humans decide]
    GATE -->|approved| ACT
    ACT --> EXT[External world<br/>calls · payments · messages]
    ACT --> GRAPH
    ACT --> AUD[(Audit Log)]
    GRAPH --> UI[Next.js on Cloud Run]
```

**Reading this diagram:** every inbound signal — regardless of channel — enters through the same Pub/Sub topic and the same intake layer. There is one pipeline, not seven parallel ones; the seven subsystems are reasoning consumers of the same graph, not separate products. Arbitration is the single chokepoint between reasoning (Layer 3) and action (Layer 5) — see `02-layers.md`.
