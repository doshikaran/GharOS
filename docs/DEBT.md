# GharOS — tracked debt

Every entry needs an owner and a repayment phase, per `PHASES.md` §2.1 rule 1 and the `gharos-standards` skill. Undocumented shortcuts are rejected at review; documented ones live here until repaid, then get struck through with the repayment date, never deleted (history stays visible).

---

## RESOLVED

### ~~DEBT-001 — GCP billing account not active~~ — RESOLVED 2026-08-22

Operator activated a new billing account (`01EC81-ACAC3A-3D4415`, "main billing account", currency INR, confirmed `OPEN: True`) and linked it to `blissful-trail-506312-t0`. `infra/setup_gcp.sh` re-run to completion: all required APIs enabled, Firestore (Native, `asia-south1`) created.

`infra/budget_alert.sh` also required a real fix while resolving this (not just a re-run): it hardcoded `--budget-amount="${AMOUNT}USD"`, which fails with an opaque `INVALID_ARGUMENT` on any non-USD-denominated billing account — this billing account is INR. Root-caused by testing the underlying `gcloud billing budgets create` call directly, isolating the currency mismatch (confirmed by checking `gcloud billing accounts describe`'s `currencyCode` field), and fixing the script to detect the account's real currency and use a currency-aware default amount (`BUDGET_AMOUNT_NATIVE` override available) instead of assuming USD. Verified end to end: budget alert now active, ₹2,000/month, 50%/90% thresholds, on the real project.

Original entry, for the record:

> **Owner:** operator. **Repayment phase:** before Phase 2 gates.
> Billing account showed `OPEN: False` regardless of project; blocked `infra/setup_gcp.sh` past step 3/5 and `infra/budget_alert.sh` entirely.

---

## OPEN

### DEBT-003 — Pro-tier Gemini not available in `asia-south1` for this project

**Opened:** Phase 2, 2026-08-22
**Owner:** e2 (routing fix) + cto (settings/region decision)
**Repayment phase:** before Phase 4 (Consequence Engine) gates — Phase 4's flagship Implication Agent is Pro-tier, elevated thinking, and cannot ship without a working Pro-tier call path.

**What's the gap:** E2 live-tested Vertex AI Gemini calls against `blissful-trail-506312-t0`. Flash-tier (`gemini-2.5-flash`) works correctly in `asia-south1`. Pro-tier (`gemini-2.5-pro`) 404s in `asia-south1` after ~15 model-id variants tried, but works via the "global" Vertex AI location. This is a real regional Model Garden availability gap on this project/account, not a code defect.

**Why this doesn't block Phase 2:** Gate 2 only requires Flash-tier plumbing proof (`/debug/gemini-ping`), which passed live. Pro-tier isn't exercised by any real agent until Phase 4.

**Repayment condition:** before Phase 4 starts, decide and implement one of: (a) route Pro-tier calls through `location="global"` while Flash stays regional for latency (needs a second location field, e.g. `vertex_ai_location_pro`, and `model_router.py`/`gemini_client.py` routing logic to use it based on `ModelTier`), or (b) request/confirm regional Pro-tier access for this project and keep single-region routing. Whichever is chosen gets a short ADR (it's a real infra/latency trade-off, not a trivial config tweak) and this entry is struck with the date.

---

### DEBT-002 — ACTION_RECORD and APPROVAL_REQUEST are not yet reachable by any graph edge

**Opened:** Phase 1, 2026-08-22
**Owner:** cto (contract) + e1 (integrity checker's current special-case) + e3 (the actual producer of these nodes)
**Repayment phase:** Phase 5 (Arbitration, Approval & Action Layer) — the first phase where ACTION_RECORD and APPROVAL_REQUEST nodes are actually produced by real code rather than existing only as seed-data shapes.

**What's the gap:** every other node type in `contracts/graph_types.py` has at least one edge type in `EdgeType` that can name it as an endpoint. ACTION_RECORD and APPROVAL_REQUEST have none — nothing connects an approval request to the action it authorized, or an action record to who approved it or what it acted on. E1's Phase 1 graph integrity checker special-cases both types out of orphan detection (documented in `app/graph/integrity_checker.py`) rather than either producing permanent false-positive noise on every seeded graph or inventing an edge type without CTO sign-off.

**Why this isn't being fixed right now:** closing this properly needs two things together — a contract change (new edge types, e.g. something like `authorizes`: APPROVAL_REQUEST → ACTION_RECORD, and `approved_by`: APPROVAL_REQUEST → PERSON) AND real code that actually populates those edges when an approval/action genuinely happens. Adding the edge types alone, now, with nothing using them, would just be a different flavor of the same "contract defines something nothing produces" problem ADR-005 just removed. Phase 5 is where the Approval Gate and Action Record become real — that's the right place to design these edges against actual usage, not speculatively now.

**Repayment condition:** Phase 5's CTO contract freeze includes the connecting edge type(s) for ACTION_RECORD/APPROVAL_REQUEST, Phase 5's implementation actually writes them, the integrity checker's special-case is removed, and this entry is struck with the date.

---

### DEBT-004 — no graph node shape for per-day attendance marks

**Opened:** Phase 3, 2026-08-23
**Owner:** cto (contract) + e1/e2 (whoever builds Phase 7's Staff Payroll pipeline)
**Repayment phase:** Phase 7 (Household Ledger — A34 Staff Payroll Agent), before its gate.

**What's the gap:** `contracts.graph_types.Person` has no field or related node type for per-day presence marks. E2's `attendance_register` `ExtractionStrategy` (Phase 3) therefore writes zero graph nodes for a successfully-extracted register — the extracted marks are summarized into `GraphMappingResult.verification_findings` (text) only, nothing durable or queryable.

**Why this isn't being fixed now:** Phase 7's A34 Staff Payroll Agent is what actually consumes attendance data ("days worked − absences − advances → salary due"). Designing the right node/edge shape (e.g. an `ATTENDANCE_RECORD` node per day, or a per-month aggregate, or something else) needs Phase 7's real consumption pattern in view — guessing now risks the same "declared a shape nothing produces or nothing consumes correctly" mistake this exact gate review just corrected twice (utility_bill/insurance_document target_edge_types, see `verification.md` Phase 3).

**Repayment condition:** Phase 7's CTO contract freeze adds the real node/edge shape for attendance data; `attendance_register`'s `ExtractionStrategy` is updated to actually write it (not just summarize into findings text); this entry struck with the date.
