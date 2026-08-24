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

## RESOLVED (continued)

### ~~DEBT-003 — Pro-tier Gemini not available in `asia-south1` for this project~~ — RESOLVED 2026-08-24

`ModelRouter` now takes an independently-configurable `location_pro`, defaulting to `Settings.vertex_ai_location_pro` (`"global"`) for Pro-tier calls while Flash stays regional. Verified live: a real Pro-tier call (`gemini-2.5-pro`, agent `A12`) succeeded end-to-end through the fixed router. Three new regression tests in `test_model_router.py` prove the per-tier routing; a stale test (`test_every_currently_allowlisted_agent_can_route_pro_tier`, which had silently drifted to test a strict subset of the real allowlist) was fixed to derive its parametrization from the live allowlist instead of a hand-copied list. Full detail: ADR-010.

Original entry, for the record:

> **Owner:** e2 (routing fix) + cto (settings/region decision). **Repayment phase:** before Phase 4 gates.
> Pro-tier (`gemini-2.5-pro`) 404s in `asia-south1` after ~15 model-id variants tried, works via `"global"`.

---

## OPEN

### DEBT-007 — A12 Implication Agent does not reliably recognize "nothing is genuinely implied"

**Opened:** Phase 4, 2026-08-24
**Owner:** e2 (prompt fix) + cto (re-run must be independently re-verified before this is struck)
**Repayment phase:** before Phase 5 (Arbitration, Approval & Action Layer) gates — PHASES.md's own words: "everything downstream assumes this agent is trustworthy," and Phase 5 builds the Approval Gate that will route this agent's output toward real (if gated) action.

**What's the gap:** the honest evaluation (`docs/IMPLICATION_BASELINE.md`, 20 held-out documents, real live Gemini calls) included two deliberate hallucination-rate control documents — ordinary documents with zero genuine implied obligations by design. A12 produced 2 plausible-sounding but fabricated candidates for *each* — a 100% failure rate on both designed "nothing to imply" tests, out of 4 candidates total. Organic hallucination rate on the other 18 real-world-shaped documents is a more modest 9% (5/56), and recall on those same 18 documents is strong (81%) — this is a narrow, specific, well-understood gap (no working "produce zero candidates" output path), not evidence of broad unreliability.

**Why this isn't being fixed in the same session:** the fix is a specific prompt change (`backend/app/prompts/a12_implication_agent/`, a new version per ADR-003 — explicit instruction/worked example for the zero-candidate case). Validating that fix honestly requires a full 20-document re-run scored with the same rigor as the baseline, not a quick partial check under time pressure — conflating "fix the prompt" with "re-score quickly to get a cleaner number" would undermine the rigor this evaluation exists to enforce.

**Repayment condition:** a new A12 prompt version explicitly handling the "nothing genuinely implied" case; a full re-run against the same 20 held-out documents (openly labeled as no-longer-strictly-blind, per `IMPLICATION_BASELINE.md`'s own honesty requirement); the control-document hallucination rate drops to 0%; the CTO independently re-verifies the new numbers before this entry is struck.

---

### DEBT-008 — citation-validator's span-length safeguard has a short-document blind spot

**Opened:** Phase 4, 2026-08-24
**Owner:** cto (design decision) + e2 (implementation)
**Repayment phase:** whenever chat/SMS-shaped documents (naturally short) become a demo-relevant citation case — not urgent, causes a real miss but not a hallucination.

**What's the gap:** `citation_validator.py`'s `_MAX_SPAN_FRACTION_OF_DOCUMENT = 0.6` (reject a located span covering >60% of the whole document — a deliberate anti-gaming measure against "cite the whole email") discarded A12's single best inference in the entire Phase 4 evaluation: a correct, accurately-cited insight from a ~140-character WhatsApp message, discarded solely because the necessarily-short document meant the specific citation covered 80% of the whole message. The reasoning was right; the citation was real and specific; a structural, document-length-blind threshold discarded it anyway.

**Why this isn't being fixed now:** the current behavior (reject rather than risk gaming) is the safer default while a better design is worked out — patching the threshold hastily, under the time pressure of finishing an evaluation write-up, risks reopening the exact "cite the whole email" vulnerability the threshold exists to prevent. A length-aware threshold (e.g. an absolute minimum span length combined with the fraction, rather than a bare fraction) needs its own considered design, not a reactive patch.

**Repayment condition:** a designed, ADR-documented fix (e.g. document-length-aware thresholding) verified against both the original gaming case the 60% threshold was built for and this newly-discovered short-document false-negative case; this entry struck.

---

### DEBT-005 — `Obligation` has no field expressing required-resource identity

**Opened:** Phase 4, 2026-08-24
**Owner:** cto (contract)
**Repayment phase:** whichever phase first needs real resource-conflict detection demonstrated (not gated by Phase 4 — Gate 4's checklist doesn't require it).

**What's the gap:** spec §7.3 names "resource" (e.g. the car, cash on hand) as one of four conflict types the Conflict Radar checks. E1's Phase 4 deterministic pre-pass (`app/solvers/conflict_prepass.py`) can detect temporal, capability, and load conflicts against real `Obligation`/`Person` fields, but resource conflicts have no field to check — `contracts.graph_types.Obligation` has no notion of "this obligation needs resource X," and no edge/metadata convention for it exists anywhere in the codebase (confirmed by E1 grepping for one before reporting this as a gap rather than inventing an ungrounded heuristic). The pre-pass is wired via an injectable `ResourceIdentityResolver` Protocol that honestly no-ops (`resource_detection_skipped=True`) when none is supplied, rather than fabricating a check.

**Why this isn't being fixed now:** no demo scenario or gate item currently needs resource-conflict detection demonstrated. Adding a field speculatively risks the exact "declared a shape nothing produces or consumes correctly" mistake already corrected twice this project (Phase 3's `utility_bill`/`insurance_document` edge-type mismatches).

**Repayment condition:** when a real scenario needs it (e.g. the demo's "book a dentist" flow implies a car/resource conflict, or a later phase's worked example names one explicitly), add the field with that concrete use in view, wire `ResourceIdentityResolver`, strike this entry.

---

### DEBT-006 — no `Person.availability` field; no `Obligation.location` field

**Opened:** Phase 4, 2026-08-24
**Owner:** cto (contract)
**Repayment phase:** Phase 9 (Intention→Action — A25 Window Scheduling, "business-hours-aware window finding," is the first agent that structurally needs real availability data) for `Person.availability`; whenever travel-time-aware conflict detection is first demonstrated, for `Obligation.location`.

**What's the gap:** spec §5.2's PERSON node description names an "availability model" as part of the node, and spec §7.3 Stage 4 names "must-start-by computed backwards through dependencies and availability" — but `contracts.graph_types.Person` has no availability field at all; it was never added when the node was first frozen in Phase 0. Similarly, spec's field-trip worked example implies travel-time buffering ("cash must travel with the child"), which needs some notion of location on an OBLIGATION — also absent. Phase 4's must-start-by computation (E2, this phase) works from `depends_on` chains and due dates alone, which is real and correct as far as it goes, but is not availability-aware — a person's actual free/busy windows never factor in, because there is nowhere on the graph to read them from.

**Why this isn't being fixed now:** Phase 9's A25 Window Scheduling is the real, spec-named consumer of availability data ("person free AND counterparty open AND historically likely") — designing the field now, without that phase's actual query patterns in view, risks guessing wrong. Same reasoning as DEBT-004/DEBT-005.

**Repayment condition:** Phase 9's CTO contract freeze adds a real `Person.availability` shape (and `Obligation.location` if the travel-time-aware conflict work lands then too) designed against Phase 9's actual needs; must-start-by computation is revisited to use it; this entry struck.

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
