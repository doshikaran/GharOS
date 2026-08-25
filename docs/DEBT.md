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

## RESOLVED (continued)

### ~~DEBT-002 — ACTION_RECORD and APPROVAL_REQUEST are not yet reachable by any graph edge~~ — RESOLVED 2026-08-25

Phase 5's CTO contract freeze added three edge types (`ACTS_ON`, `AUTHORIZES`, `APPROVED_BY` — ADR-012). `app.arbitration.approval_gate.ApprovalGate.approve_and_execute` writes all three for real, atomically alongside every `ActionRecord` it creates, on every successful approval → execution flow. `app/graph/integrity_checker.py`'s special-case was narrowed accordingly: `ActionRecord` is removed from it entirely (a correctly-written one is now always edge-connected by construction — verified by a new adversarial test, `test_action_record_with_no_edges_is_now_a_real_orphan`, proving one written with no edges IS now flagged). `ApprovalRequest` stays special-cased, but for a materially different and narrower reason than before: a `PENDING`, `REJECTED`, or `EXPIRED` request — or an `APPROVED` one whose underlying tool invocation then failed — is legitimately, permanently edge-orphaned by design (nothing was ever authorized), not corruption; this is normal lifecycle state, not further deferred debt. Seed data (`seeds/demo_household.py`) updated to carry the same three edges its `action_record1`/`approval_request1` pair would have if written by a real `ApprovalGate` run. Verified: full backend suite (599 passed, 7 skipped), `mypy` clean (190 files), `ruff` clean, including `test_integrity_checker_is_clean_gate_1` against the real seeded demo graph.

Original entry, for the record:

> **Owner:** cto (contract) + e1 (integrity checker's current special-case) + e3 (the actual producer of these nodes). **Repayment phase:** Phase 5.
> Every other node type in `contracts/graph_types.py` has at least one edge type in `EdgeType` that can name it as an endpoint. ACTION_RECORD and APPROVAL_REQUEST had none.

---

## OPEN

### DEBT-007 — A12 Implication Agent does not reliably recognize "nothing is genuinely implied" — DOWNGRADED (not struck) 2026-08-24

**Opened:** Phase 4, 2026-08-24. **Downgraded from blocking to monitoring:** 2026-08-24 (same day, after the v2 fix + re-run below).
**Owner:** e2 (prompt fix, done) + cto (re-run independently re-verified — this update)
**Repayment phase (original):** before Phase 5 gates. **Actual disposition:** substantially repaid; not struck, because the original repayment condition ("control-document hallucination rate drops to 0%") was not fully met. Phase 5 is proceeding on the CTO's explicit, reasoned call below rather than a fully clean number.

**What was done:** `backend/app/prompts/a12_implication_agent/v2.md` (ADR-003 versioning; `manifest.json`'s `"A12"` bumped `"v1"` → `"v2"`) adds a worked negative example (a grocery-receipt document contrasted against a genuine nut-allergy-triggered implication) and an explicit pre-emission test: *"would a thoughtful family member have already assumed this with zero reasoning?"* A full, honest, no-longer-blind re-run against the same 20 held-out documents was performed and hand-scored by the CTO with the same rigor as the v1 baseline. Full numbers and per-document detail: `docs/IMPLICATION_BASELINE.md`'s "v2 re-run" section.

**Result — a real trade-off, not a clean win:**

| Metric | v1 | v2 |
|---|---|---|
| Recall | 81% | 71% (−10 pts) |
| Hallucination, organic (non-control) | 9% | **0%** |
| Hallucination, overall | 15% | 4% |
| Control docs fully clean | 0/2 | 1/2 |
| Citation validity | 85% | 96% |

Organic hallucination reached the target (0%) and one of the two control documents is now fully clean. The other (`eval-20-library-books`) still emits one candidate — down from two in v1, but not zero. In exchange, A12 became more conservative and missed several implications it had correctly caught in v1 (the sports-day transport conflict, the allergy-fasting window, a medication-schedule notification, a budget note) — recall dropped 10 points.

**Why this is being downgraded rather than struck or re-iterated further:** the original repayment condition (0% control-document hallucination) is not literally met, so this is not marked resolved. But: (1) the specifically dangerous failure mode — organic hallucination on real household documents — is fully eliminated, not just reduced; (2) the one remaining control-document candidate is a single, identified, narrow pattern ("a child needs an adult to prepare something"), not evidence of a broad or unpredictable failure mode; (3) a third full live-evaluation cycle costs real time and real API spend for a narrowing, well-understood residual, with diminishing evidence a third prompt iteration converges rather than just trades errors again; (4) Phase 5's own Approval Gate — built next — is structurally exactly the downstream safety net this class of residual risk over-relies on and should be caught by before anything ever becomes a real action. Proceeding to Phase 5 without a third iteration is the CTO's explicit, reasoned call, made openly rather than silently declared "fixed."

**Repayment condition (revised, to actually strike this entry):** either (a) a future prompt iteration reaches 0/2 control documents clean without reintroducing organic hallucination or materially regressing recall further, verified by another full honest re-run: or (b) Phase 5's Approval Gate is shown in practice to catch this exact residual pattern before any downstream action, at which point the repayment condition shifts from "the agent never hallucinates" (unrealistic as a hard bar for any LLM-based agent) to "the system never acts on a hallucination" (the actually load-bearing guarantee) — and this entry is re-framed and closed against that guarantee instead.

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

### DEBT-004 — no graph node shape for per-day attendance marks

**Opened:** Phase 3, 2026-08-23
**Owner:** cto (contract) + e1/e2 (whoever builds Phase 7's Staff Payroll pipeline)
**Repayment phase:** Phase 7 (Household Ledger — A34 Staff Payroll Agent), before its gate.

**What's the gap:** `contracts.graph_types.Person` has no field or related node type for per-day presence marks. E2's `attendance_register` `ExtractionStrategy` (Phase 3) therefore writes zero graph nodes for a successfully-extracted register — the extracted marks are summarized into `GraphMappingResult.verification_findings` (text) only, nothing durable or queryable.

**Why this isn't being fixed now:** Phase 7's A34 Staff Payroll Agent is what actually consumes attendance data ("days worked − absences − advances → salary due"). Designing the right node/edge shape (e.g. an `ATTENDANCE_RECORD` node per day, or a per-month aggregate, or something else) needs Phase 7's real consumption pattern in view — guessing now risks the same "declared a shape nothing produces or nothing consumes correctly" mistake this exact gate review just corrected twice (utility_bill/insurance_document target_edge_types, see `verification.md` Phase 3).

**Repayment condition:** Phase 7's CTO contract freeze adds the real node/edge shape for attendance data; `attendance_register`'s `ExtractionStrategy` is updated to actually write it (not just summarize into findings text); this entry struck with the date.
