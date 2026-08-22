# GharOS — tracked debt

Every entry needs an owner and a repayment phase, per `PHASES.md` §2.1 rule 1 and the `gharos-standards` skill. Undocumented shortcuts are rejected at review; documented ones live here until repaid, then get struck through with the repayment date, never deleted (history stays visible).

---

## OPEN

### DEBT-001 — GCP billing account not active

**Opened:** Phase 0, 2026-08-22
**Owner:** operator (this is an external Google Cloud console action, not a code fix)
**Repayment phase:** before Phase 2 (Mandatory Stack Proof) gates — Phase 2 hard-requires a live deployed Cloud Run service, live Firestore, live Pub/Sub, and a live Scheduler job, none of which are reachable until billing is active.

**What's blocked:** `infra/setup_gcp.sh` cannot proceed past step 3/5 (API enablement, Firestore database creation). `infra/budget_alert.sh` cannot create a budget (GCP Budgets require a billing account). Both scripts are written, idempotent, and were reviewed directly by the CTO — the code is not the gap, the account state is.

**Root cause:** the operator's billing account (`016373-05772C-CB9E99`, display name "Main") shows `OPEN: False` in `gcloud billing accounts list`, independent of which GCP project it's linked to (confirmed across two different projects). This points to the billing account itself not being fully activated on Google's side — most likely a pending payment-method verification step in the console that hasn't been completed, rather than anything project-specific.

**Why this does NOT block Phase 0 or Phase 1:** Gate 0's other six items are all independently verified and passing (see `verification.md`, Phase 0 section) — only the "budget alert active" item is affected. Phase 1 (graph substrate) runs entirely against the Firestore *emulator* per its own gate checklist; it has no dependency on a live GCP project at all.

**Repayment condition:** operator confirms the billing account shows `OPEN: True` in `gcloud billing accounts list`; CTO (or whoever's running the session) re-runs `infra/setup_gcp.sh` and `infra/budget_alert.sh`, confirms both complete, and strikes this entry with the date.

---

### DEBT-002 — ACTION_RECORD and APPROVAL_REQUEST are not yet reachable by any graph edge

**Opened:** Phase 1, 2026-08-22
**Owner:** cto (contract) + e1 (integrity checker's current special-case) + e3 (the actual producer of these nodes)
**Repayment phase:** Phase 5 (Arbitration, Approval & Action Layer) — the first phase where ACTION_RECORD and APPROVAL_REQUEST nodes are actually produced by real code rather than existing only as seed-data shapes.

**What's the gap:** every other node type in `contracts/graph_types.py` has at least one edge type in `EdgeType` that can name it as an endpoint. ACTION_RECORD and APPROVAL_REQUEST have none — nothing connects an approval request to the action it authorized, or an action record to who approved it or what it acted on. E1's Phase 1 graph integrity checker special-cases both types out of orphan detection (documented in `app/graph/integrity_checker.py`) rather than either producing permanent false-positive noise on every seeded graph or inventing an edge type without CTO sign-off.

**Why this isn't being fixed right now:** closing this properly needs two things together — a contract change (new edge types, e.g. something like `authorizes`: APPROVAL_REQUEST → ACTION_RECORD, and `approved_by`: APPROVAL_REQUEST → PERSON) AND real code that actually populates those edges when an approval/action genuinely happens. Adding the edge types alone, now, with nothing using them, would just be a different flavor of the same "contract defines something nothing produces" problem ADR-005 just removed. Phase 5 is where the Approval Gate and Action Record become real — that's the right place to design these edges against actual usage, not speculatively now.

**Repayment condition:** Phase 5's CTO contract freeze includes the connecting edge type(s) for ACTION_RECORD/APPROVAL_REQUEST, Phase 5's implementation actually writes them, the integrity checker's special-case is removed, and this entry is struck with the date.
