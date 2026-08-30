# System overview

Source: `GharOS_Build_Spec_v2.md` §6.1, `PHASES.md` §5.1. This is the top-level architecture diagram for the submission.

```mermaid
flowchart TB
    subgraph IN[Inputs]
        A1[Email — Gmail / Outlook<br/>OAuth connectors, Phase 14.5]
        A2[Documents / photos<br/>drag-drop · Drive picker]
        A3[WhatsApp / UPI SMS<br/>forwarded / exported — no vendor API]
        A4[Voice utterance<br/>browser mic]
        A5[Scheduled tick<br/>Cloud Scheduler]
    end

    A5 --> PS[(Cloud Pub/Sub<br/>events · heartbeat · consolidation · followup)]
    A1 & A2 & A3 --> ING["POST /ingest — IngestionOrchestrator<br/>synchronous, idempotent per content hash"]
    A4 --> WS["voice/session WebSocket<br/>A62 Session Manager"]
    PS --> INTAKE
    ING --> INTAKE
    WS --> INTAKE["Intake Layer<br/>A2 route · A3/A3b/A3c extract · A5 resolve"]
    INTAKE --> GRAPH[(Firestore<br/>Household Knowledge Graph<br/>provenance-tagged, versioned)]
    INTAKE --> ORCH{Google ADK Orchestrator<br/>A0 Household Coordinator}

    ORCH --> S1[1 Consequence Engine]
    ORCH --> S2[2 Fair Allocator]
    ORCH --> S3[3 Intention→Action]
    ORCH --> S4[4 Household Ledger]
    ORCH --> S5[5 Simulator]
    ORCH --> S6[6 Council]
    ORCH --> S7[7 Outbound Concierge]

    S1 & S2 & S3 & S4 & S5 & S6 & S7 --> ARB[Arbitration — A57 Confidence Arbiter<br/>confidence · risk tier R0–R4]
    ARB -->|R0/R1| ACT[Action Layer<br/>idempotent, separately-permissioned tools]
    ARB -->|R2/R3| GATE[Approval Gate<br/>evidence bundle · expiry escalates]
    ARB -->|R4| ESC[A58 Escalation — humans decide]
    GATE -->|approved| ACT
    ACT --> EXT[External world<br/>calls · payments · messages]
    ACT --> GRAPH
    ACT --> AUD[(Audit Log<br/>immutable, written before execute)]
    GRAPH --> UI[Next.js on Cloud Run<br/>live graph viz · approvals · council]
```

**Reading this diagram:** every inbound signal is normalised by the same intake layer and lands in one graph, but there are three entry *styles*, deliberately: Cloud Scheduler ticks and async events arrive through **Pub/Sub** and wake `gharos-api` with nobody present (this is the autonomy proof); on-demand ingestion ("scan my Gmail") is a **synchronous `POST /ingest`** call into `IngestionOrchestrator` (Phase 14.5), idempotent per `compute_content_hash` so a re-scan writes nothing new; voice is a **WebSocket session**. The seven subsystems are reasoning consumers of the shared graph, not seven parallel products. **Arbitration (A57) is the single chokepoint between reasoning (Layer 3) and action (Layer 5)** — reasoning agents hold no action credentials; see `02-layers.md`.

**Mandatory-requirement anchors visible here:** Gemini 3.5+ via **Vertex AI** powers every reasoning agent (Flash/Pro-tier routed in `reasoning/model_router.py`); the **Google ADK** orchestrator (`A0`) sequences the subsystems with tool isolation and approval-gate callbacks; **Cloud Run + Firestore + Pub/Sub + Cloud Scheduler** are the running infrastructure. Deploy topology is `06-deployment.md`; proof is `docs/DEPLOYMENT_PROOF.md`.
