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

### DEBT-009 — no end-to-end raw-document-to-graph orchestrator exists for any node type

**Opened:** Phase 7, 2026-08-27
**Decision (operator-delegated to CTO), 2026-08-27:** repayment phase assigned — **Phase 15 (Demo Hardening)**, not sooner. The demo will be built around a real orchestrator by Phase 15, not permanently scoped around pre-staged documents as a design choice — but Phases 8-14 proceed on the existing staged-testing discipline unchanged, since building the orchestrator now would risk the remaining phases with four days left in the submission window. This is a real, tracked commitment, not a deferral-by-silence: Phase 15's own gate must not sign off without this repaid.
**Owner:** cto (design) + whichever role(s) Phase 15's contract freeze assigns.
**Repayment phase:** Phase 15 (Demo Hardening & Deployment Proof) — assigned, not just "likely."

**What's the gap, and how it was found:** investigating DEBT-004's attendance-specific write-path gap (see that entry, this same update) surfaced a broader, project-wide fact: **no phase built to date has an actual orchestrator wiring raw document → extraction → entity resolution → downstream writer agents together end to end, for any node type.** Every gate from Phase 1 through Phase 7 has been verified via staged, targeted tests calling each agent/strategy directly with already-prepared inputs (e.g. Phase 3's "receipt produces LEDGER_EVENT + PURCHASE_ITEM" gate item calls the strategy directly with pre-extracted fields; Phase 4's Implication Agent tests construct a `HouseholdContext` directly rather than assembling it from a live graph read of a just-ingested document). This is real, deliberate, and has produced genuinely correct per-stage code — but it means a claim like "upload a real photo of a handwritten register and watch a correct salary obligation appear" is not actually true yet against the live system, only against hand-assembled test fixtures that skip the entity-resolution and cross-stage-handoff steps a live run would need.

**Why this isn't being fixed now:** designing the actual orchestrator (an ADK-based runner sequencing A2 → A3/A3b/A3c → A5 → the relevant writer agent(s), per spec §7.3's own stage list) is real, non-trivial architecture work that deserves its own CTO-led design pass against a concrete demo scenario, not a rushed addition discovered mid-Phase-7-review. Every individual stage's own correctness is not in question — this is purely about the connective tissue between stages, which has never yet been built for anything.

**Repayment condition:** a real orchestrator (or an explicit, reasoned decision that ADK's own agent-composition model already provides this and just needs wiring, not new code) demonstrated against at least one real raw-document-to-graph-write flow live, end to end, with a test proving it — at that point this entry is struck and DEBT-004's own repayment condition (a) is satisfied as a side effect for attendance specifically.

---

### DEBT-010 — A31 Follow-up/Persistence has no real producer this phase; only test doubles satisfy its `FollowUpTrackable` Protocol

**Opened:** Phase 7, 2026-08-27
**Owner:** e2 (A30 `RecoveryDraft`) + e3 (A33 vendor-request tracking, `FollowUpTrackable` itself)
**Repayment phase:** whichever phase first needs a real, durable, cross-scheduler-run "open recovery draft" or "open vendor request" to actually re-contact or escalate — plausibly Phase 10 (Outbound Concierge, when drafts actually get dispatched and following up on them becomes real) or a dedicated repayment named at that point.

**What's the gap:** E3's `app.events.followup_scan.FollowUpScanner`/`FollowUpDispatcher` (A31) are real, correct, and well-tested against a structural `FollowUpTrackable` Protocol (`id`, `created_at`, `last_contact_attempt_at`, `attempt_count`, `vendor_id`, `status`, `involves_financial`) — deliberately designed this way, per this phase's own dispatch instructions, so E3 didn't have to block on or guess at E2's real `RecoveryDraft` type while both built in parallel. Checked directly by the CTO: **neither of this phase's two candidate producers actually satisfies it.** E2's `RecoveryDraft` (`app.agents.ledger.types`) is, by explicit design, a pure draft-content value object — `target_vendor`, `ask`, `message_text`, `draft_kind`, `confidence`, `reasoning` — with no `id`, `created_at`, `attempt_count`, or `status` at all (spec's own A30 forbidden list is "sending; moving money," and E2 correctly read that as "draft only," which structurally excludes lifecycle-tracking fields too). E3's own `VendorRequestObservation` (`app.adapters.vendor_relations`) similarly carries only `vendor_id`, no tracking fields either. The two test files proving A31's logic (`test_followup_scan.py`, `test_followup_dispatcher.py`) both construct a local fake dataclass satisfying the Protocol — real, correct unit tests of A31's own logic, but not proof any real Phase 7 output can actually be tracked by it yet.

**Why this isn't being fixed now:** the tracking metadata A31 needs (`created_at`, `attempt_count`, `last_contact_attempt_at`, `status`) is durable, cross-scheduler-run state — it needs to survive between Cloud Scheduler ticks, which means it belongs on a real graph-resident node, not an in-memory dataclass field bolted onto `RecoveryDraft`. Designing that node/edge shape now, before Phase 10 gives a real "a draft was actually sent and needs following up" consumption pattern to design against, risks the exact "declared a shape nothing produces or consumes correctly" mistake this project has corrected multiple times already (Phase 3's `utility_bill`/`insurance_document` edge mismatches; DEBT-004/005/006's identical reasoning).

**Repayment condition:** whichever phase first makes A30's drafts or A33's vendor requests durably trackable (real graph-resident lifecycle state, not just in-memory value objects) either adds a graph-resident node/edge shape carrying the `FollowUpTrackable` fields, or extends the existing types with them, designed against that phase's real need — verified by a real (not fake-double) object flowing through `FollowUpScanner`/`FollowUpDispatcher`.

---

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

### DEBT-004 — no graph node shape for per-day attendance marks — SUBSTANTIALLY REPAID, not struck, 2026-08-27

**Opened:** Phase 3, 2026-08-23. **Updated:** Phase 7, 2026-08-27.
**Owner:** cto (contract, done) + e1 (persistence wiring, done) + e2 (consumption via A34, done; production write-path, still open)
**Repayment phase:** Phase 7 (Household Ledger — A34 Staff Payroll Agent).

**What was done this phase:** the CTO contract freeze added a real `AttendanceRecord` node type and `attendance_of` edge (ADR-013, `contracts/graph_types.py`). E1 wired it fully into persistence (`app.persistence.collections`/`codecs.nodes`) and the Phase 6 graph-visualisation label dispatch (`app.graph.serialization`) — verified: a round-trip encode/decode and a snapshot-envelope test both pass against a real `AttendanceRecord`. E2's A34 (`app.agents.ledger.staff_payroll_agent`) genuinely consumes a real `AttendanceRecord` (interprets ambiguous marks, calls `app.solvers.salary_calculator`, writes the resulting salary `Obligation`) — verified by real tests covering both the clean-register and below-floor-mark paths.

**What is honestly still missing, found by the CTO during this phase's own gate review (not by any automated test, since nothing exercises this path end to end):** nothing in the actual production code ever *constructs and writes* a fresh `AttendanceRecord` from a freshly-extracted register. `backend/app/agents/intake/strategies/attendance_register_strategy.py` (Phase 3) still returns `nodes=(), edges=()` unchanged — `AttendanceRecord(...)` is constructed in exactly two places in the entire codebase: the codec's `decode_attendance_record` (reads one back) and `seeds/demo_household.py` (a hand-written demo instance). A34's own input (`PayrollRequest.attendance: AttendanceRecord`) assumes an already-resolved, already-written record is handed to it.

**Why this isn't a Phase-7-specific miss, and why it isn't being force-fixed now:** the root cause is structural and pre-existing, not new to attendance data — `ExtractionStrategy.map_to_graph` has no `GraphReader` (ADR-008, by design), so it structurally cannot resolve a raw name mention ("Maya") to an existing PERSON node id, exactly the same limitation `PermissionSlipExtractionStrategy` already has for its own `owned_by` edge (see that strategy's own docstring — it deliberately does not fabricate a capability-aware owner and leaves that to "a downstream agent with real graph access"). Investigating this, the CTO confirmed **no phase of this project has yet built a genuine end-to-end raw-document → extraction → entity-resolution → graph-write orchestrator for any node type** — every gate so far (Phases 1, 3, 4) has been verified via staged, targeted tests of each agent/strategy in isolation (e.g. Phase 3's "receipt produces LEDGER_EVENT + PURCHASE_ITEM" gate item was proven by calling the strategy directly with pre-extracted fields, not by running a real uploaded receipt through a live pipeline). Attendance is not behind the rest of the project; the rest of the project has this same gap for every node type, undiscovered until this review because it was the first time a debt-repayment review specifically asked "does anything actually construct this node in production."

**Repayment condition (revised):** either (a) a dedicated end-to-end ingestion orchestrator is built (naturally scoped to whichever phase first needs a real raw-document-to-graph demo path proven live, very plausibly Phase 15's Demo Hardening, or an earlier phase if the demo script needs it sooner) and attendance's write-path falls out of it like every other node type's, or (b) if attendance specifically needs to work standalone before then, a small, precisely-scoped writer step is added ahead of that (taking an already-entity-resolved staff `Person` plus the raw extracted register fields and performing the write) — either way, verified with a real test proving a raw extracted register produces a real, graph-written `AttendanceRecord`, not just a hand-constructed test fixture. Flagged to the operator as an open item this phase, not silently claimed complete.
