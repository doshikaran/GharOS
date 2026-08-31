# GharOS — architecture diagrams

The canonical set. Each diagram is a rendered `.png` plus its `.mmd` source (edit the source,
re-render at [mermaid.live](https://mermaid.live), replace the `.png`).

| # | Diagram | Shows |
|---|---|---|
| 01 | `01-system-context` | End-to-end flow: the three entry styles (Pub/Sub events · synchronous `POST /ingest` · voice WebSocket) → intake → the Firestore knowledge graph → the ADK orchestrator → seven reasoning subsystems → the A57 Confidence Arbiter → Approval Gate / Escalation → Action Layer + Audit Log. |
| 02 | `02-gcp-deployment` | The real Google Cloud resources and their trust boundaries: two Cloud Run services (source-deployed via Buildpacks, `min-instances=0`), Firestore Native, Pub/Sub with OIDC-verified push, three Cloud Scheduler jobs, Secret Manager, Vertex AI, Cloud Logging, IAM. |
| 03 | `03-event-to-action` | One worked path — a school email lands on Pub/Sub with nobody present — traced to a real action, with each of the eight safety invariants marked at the point it bites. |
| 04 | `04-ingestion-pipeline` | Raw input → provenance-linked graph nodes: fetch → normalise → content-hash dedupe → raw store → audit-before-write → route → extract → resolve → strategy → provenance-guarded writer. Every terminal state is a visible outcome. |
| 05 | `05-knowledge-graph` | The Household Knowledge Graph: all 18 node types, the key edges, and the provenance rule (every node/edge carries `derivation` + `source_ref` + `confidence` + agent + timestamp; a write missing any of it cannot be constructed; versioned, never mutated). |
| 06 | `06-council-mechanism` | The Council as a sequence diagram: specialists on disjoint graph scopes (anti-anchoring), hard-constraint elimination, conflicting delegate scores, an Adversary, and a deterministic minimax-regret arbiter (Savage 1951). Not debate. |
| 07 | `07-safety-invariants` | The eight safety invariants mapped to the pipeline stage where each is enforced — by construction (a structural impossibility, an AST scan, a repo-wide grep, a type that raises), each with a real never-skipped test. |
